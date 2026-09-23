"""Find, date and classify every delisting of one security (D6, D16, D17, D20).

A delisting is a Form 25 that removed the security's class from its exchange
and left it on no exchange or on a new one. Securities with no Form 25 fall back
to the classifier's no-Form-25 paths; a security that ended with no evidence at
all is reported for review instead of being dropped.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from .classifier import DelistClassifier, DelistRecord
from .crsp_codes import CrspBucket
from .edgar import EdgarSubmission
from .figi_resolution import class_letter
from .form25 import (
    REGIONAL_EXCHANGES, Form25, SecurityRef, class_kind, class_label, effective_date, list_form25, match_security,
    notice_last_trade, parse_form25,
)
from .last_trade import LastTrade, decide_last_trade, eightk_last_trade
from .listing_status import exchanges_around, withdrawal_kind
from .midas import MIDAS_START
from .nasdaq_halts import last_trade_from_halt
from .security_master import Security
from .trading_calendar import previous_trading_day

FORM25_LOOKBACK_DAYS = 30           # how far before the security's first sighting to look for a Form 25
SAME_EVENT_DAYS = 30                # Form 25s of this security this close together are one delisting
IGNORE_AFTER_DEFINITIVE_DAYS = 30   # once truly delisted, a later Form 25 past this is suspect
SEEN_AFTER_DAYS = 5                 # sighted this long past the effective date: the security kept trading
SIBLING_ALIVE_BEFORE_DAYS = 30      # a sibling's own first sighting, minus this: still alive
SIBLING_ALIVE_AFTER_DAYS = 400      # a sibling's own last sighting, plus this: still alive
MIDAS_BEFORE_DAYS, MIDAS_AFTER_DAYS, MIDAS_STILL_TRADING_DAYS = 75, 10, 5
EIGHTK_BEFORE_DAYS, EIGHTK_AFTER_DAYS = 60, 5      # single-filing 8-K window (fallback path)
EIGHTK_GROUP_AFTER_DAYS = 15                       # group 8-K window: latest filed + this many days
DEREG_FALLBACK_BEFORE_DAYS = 30     # a fallback Form 15 must be within [last_seen - this, ...
DEREG_FALLBACK_AFTER_DAYS = 120     # ... last_seen + this] to date the delisting

# Preferred exchange for a multi-exchange delisting group: the filing on the
# most-senior exchange supplies the event's `exchange` and `form25`/`form25_sub`.
EXCHANGE_PREFERENCE = ("NYSE", "NASDAQ", "NYSE AMERICAN", "CBOE BZX", "NYSE ARCA")


@dataclass(frozen=True)
class ReviewItem:
    sec_id: str
    ticker: str
    cik: int | None
    flag: str
    reason: str
    delist_date: str = ""
    last_seen: str = ""


@dataclass
class DelistingEvent:
    sec_id: str
    cik: int
    ticker: str
    delist_date: str
    record: DelistRecord
    last_trade: LastTrade
    form25: Form25 | None
    form25_sub: EdgarSubmission | None
    exchange: str
    flags: list[str] = field(default_factory=list)


@dataclass
class SecurityContext:
    security: Security
    siblings: list[SecurityRef]
    ticker_on: Callable[[str], str | None]
    last_seen: str
    seen_after: Callable[[str], bool]
    listed_today: bool | None
    expected_name: str | None
    # sec_id -> (first sighting, last sighting), ISO. A sibling absent here is
    # treated as alive at every filing date (the caller doesn't know its span).
    sibling_spans: dict[str, tuple[str, str]] = field(default_factory=dict)


def _d(s: str) -> date:
    return date.fromisoformat(s)


class DelistingFinder:
    def __init__(self, edgar, classifier: DelistClassifier, *, midas=None, halts=None) -> None:
        self.edgar, self.classifier, self.midas, self.halts = edgar, classifier, midas, halts

    # -- sibling / class matching -----------------------------------------
    def _alive_at(self, ctx: SecurityContext, sec_id: str, filing_date: str) -> bool:
        span = ctx.sibling_spans.get(sec_id)
        if span is None:
            return True
        first, last = span
        lo = (_d(first) - timedelta(days=SIBLING_ALIVE_BEFORE_DAYS)).isoformat()
        hi = (_d(last) + timedelta(days=SIBLING_ALIVE_AFTER_DAYS)).isoformat()
        return lo <= filing_date <= hi

    def _class_conflict(self, f25: Form25, ref: SecurityRef) -> bool:
        """True when the Form 25's class letter and the matched sibling's class
        letter both exist and disagree: `match_security`'s single-sibling branch
        (`len(same) == 1`) accepts by elimination without checking letters, so
        this is the backstop for a class the universe doesn't actually hold."""
        f_letter = class_letter(class_label(f25.class_text))
        r_letter = class_letter(ref.share_class)
        return bool(f_letter and r_letter and f_letter != r_letter)

    # -- last trade (single filing; used by the no-Form-25 fallback) -----
    def _eightk_window(self, cik: int, filings: list[EdgarSubmission], lo: date, hi: date,
                       anchor: date) -> tuple[date | None, str]:
        cands = [f for f in filings if f.form.startswith("8-K") and "3.01" in f.item_set
                 and f.filing_date and lo <= _d(f.filing_date) <= hi]
        for f in sorted(cands, key=lambda f: abs((_d(f.filing_date) - anchor).days)):
            got = eightk_last_trade(self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc))
            if got[0] is not None:
                return got
        return None, ""

    def _eightk(self, cik: int, filings: list[EdgarSubmission], filed: date) -> tuple[date | None, str]:
        return self._eightk_window(cik, filings, filed - timedelta(days=EIGHTK_BEFORE_DAYS),
                                   filed + timedelta(days=EIGHTK_AFTER_DAYS), filed)

    def _last_trade(self, cik: int, filings: list[EdgarSubmission], f25: Form25 | None, ticker: str,
                    filed: date) -> LastTrade:
        notice = notice_last_trade(f25) if f25 else (None, "")
        eightk = self._eightk(cik, filings, filed)
        midas = None
        if self.midas is not None and filed >= MIDAS_START:
            m = self.midas.last_trade_day(ticker, filed - timedelta(days=MIDAS_BEFORE_DAYS),
                                          filed + timedelta(days=MIDAS_AFTER_DAYS))
            if m is not None and m < filed + timedelta(days=MIDAS_STILL_TRADING_DAYS):
                midas = m
        halt = None
        if midas is None and self.halts is not None:
            guesses = [d for d, _ in (notice, eightk) if d] or [previous_trading_day(filed)]
            h = self.halts.deletion_halt(ticker, min(guesses) - timedelta(days=2),
                                         max(guesses) + timedelta(days=2), max_days=5)
            halt = last_trade_from_halt(h) if h else None
        return decide_last_trade(notice=notice, eightk=eightk, midas=midas, halt=halt)

    # -- last trade for a group of Form 25s of one delisting --------------
    def _last_trade_group(self, cik: int, filings: list[EdgarSubmission],
                          group: list[tuple[EdgarSubmission, Form25]], ticker: str) -> LastTrade:
        subs = [s for s, _ in group]
        earliest_filed = _d(min(s.filing_date for s in subs))
        latest_filed = _d(max(s.filing_date for s in subs))
        latest_eff = _d(max(effective_date(s.filing_date) for s in subs))

        ordered = sorted(group, key=lambda item: (item[0].form != "25-NSE", item[0].filing_date))
        notice: tuple[date | None, str] = (None, "")
        for _, f25 in ordered:
            n = notice_last_trade(f25)
            if n[0] is not None:
                notice = n
                break

        eightk = self._eightk_window(cik, filings, earliest_filed - timedelta(days=EIGHTK_BEFORE_DAYS),
                                     latest_filed + timedelta(days=EIGHTK_GROUP_AFTER_DAYS), earliest_filed)

        midas = None
        if self.midas is not None and earliest_filed >= MIDAS_START:
            m = self.midas.last_trade_day(ticker, earliest_filed - timedelta(days=MIDAS_BEFORE_DAYS),
                                          latest_eff + timedelta(days=MIDAS_AFTER_DAYS))
            if m is not None and m < latest_eff + timedelta(days=MIDAS_STILL_TRADING_DAYS):
                midas = m

        halt = None
        if midas is None and self.halts is not None:
            guesses = [d for d, _ in (notice, eightk) if d] or [previous_trading_day(latest_filed)]
            h = self.halts.deletion_halt(ticker, min(guesses) - timedelta(days=2),
                                         max(guesses) + timedelta(days=2), max_days=5)
            halt = last_trade_from_halt(h) if h else None

        return decide_last_trade(notice=notice, eightk=eightk, midas=midas, halt=halt)

    # -- grouping -----------------------------------------------------------
    def _group(self, candidates: list[tuple[EdgarSubmission, Form25]]
              ) -> list[list[tuple[EdgarSubmission, Form25]]]:
        """Chain matched Form 25s into one group per delisting: each filing joins
        the open group when it's within SAME_EVENT_DAYS of the group's latest
        filing so far, across exchanges."""
        groups: list[list[tuple[EdgarSubmission, Form25]]] = []
        for item in sorted(candidates, key=lambda i: i[0].filing_date):
            if groups and (_d(item[0].filing_date) - _d(groups[-1][-1][0].filing_date)).days <= SAME_EVENT_DAYS:
                groups[-1].append(item)
            else:
                groups.append([item])
        return groups

    def _exchange_rank(self, item: tuple[EdgarSubmission, Form25]) -> tuple[int, str]:
        sub, f25 = item
        try:
            return EXCHANGE_PREFERENCE.index(f25.exchange), sub.filing_date
        except ValueError:
            return len(EXCHANGE_PREFERENCE), sub.filing_date

    # -- review bookkeeping --------------------------------------------------
    def _review(self, review: list[ReviewItem], seen: set[tuple[str, str]], sec: Security, ticker: str,
               cik: int | None, flag: str, reason: str, sub: EdgarSubmission) -> None:
        key = (flag, sub.accession)
        if key in seen:
            return
        seen.add(key)
        review.append(ReviewItem(sec.sec_id, ticker, cik, flag, reason,
                                 delist_date=effective_date(sub.filing_date)))

    # -- main ------------------------------------------------------------
    def find(self, ctx: SecurityContext) -> tuple[list[DelistingEvent], list[ReviewItem]]:
        sec = ctx.security
        if not sec.eras:
            return [], []
        cik = sec.issuer_cik
        ticker_last = sec.eras[-1].ticker
        if cik is None:
            if ctx.listed_today is False:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "ended_without_delisting",
                                       "no issuer CIK to search for a Form 25", last_seen=ctx.last_seen)]
            return [], []

        filings = self.edgar.recent_filings(cik)
        first_seen = min(e.first for e in sec.eras)
        floor = (_d(first_seen) - timedelta(days=FORM25_LOOKBACK_DAYS)).isoformat()

        review: list[ReviewItem] = []
        seen_review: set[tuple[str, str]] = set()
        had_unmatched = False
        candidates: list[tuple[EdgarSubmission, Form25]] = []

        for sub in list_form25(filings):
            if sub.filing_date < floor:
                continue
            raw = self.edgar.fetch_filing_raw(cik, sub.accession)
            if not raw:
                self._review(review, seen_review, sec, ticker_last, cik, "form25_unreadable",
                             f"no filing text for {sub.form} {sub.accession}", sub)
                continue
            f25 = parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date)
            if class_kind(f25.class_text) == "other":
                self._review(review, seen_review, sec, ticker_last, cik, "form25_unclassified",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}) has no recognized class", sub)
                continue
            alive = [r for r in ctx.siblings if self._alive_at(ctx, r.sec_id, sub.filing_date)]
            matched, why = match_security(f25, alive)
            if matched is None:
                if why == "ambiguous class":
                    had_unmatched = True
                    self._review(review, seen_review, sec, ticker_last, cik, "form25_unmatched",
                                 f"{sub.form} {sub.accession} ({f25.class_text!r}): {why}", sub)
                continue
            if matched != sec.sec_id:
                continue
            ref = next((r for r in alive if r.sec_id == matched), None)
            if ref is not None and self._class_conflict(f25, ref):
                continue
            if f25.exchange in REGIONAL_EXCHANGES:
                continue
            eff = effective_date(sub.filing_date)
            continued = bool(ctx.listed_today) or ctx.seen_after(
                (_d(eff) + timedelta(days=SEEN_AFTER_DAYS)).isoformat())
            if continued:
                before, after = exchanges_around(self.edgar, cik, filings, _d(sub.filing_date))
                if withdrawal_kind(f25.exchange, before, after) == "secondary":
                    continue
                if after is not None and f25.exchange in after:
                    continue        # the next 10-K cover still names it: another class left, not this one
            candidates.append((sub, f25))

        events: list[DelistingEvent] = []
        last_definitive: DelistingEvent | None = None
        for group in self._group(candidates):
            earliest_sub = min(group, key=lambda item: item[0].filing_date)[0]
            if last_definitive is not None:
                gap = (_d(earliest_sub.filing_date) - _d(last_definitive.delist_date)).days
                if gap > IGNORE_AFTER_DEFINITIVE_DAYS and not ctx.seen_after(earliest_sub.filing_date):
                    continue        # a security truly gone can't have a later Form 25 of its own
            eff = effective_date(earliest_sub.filing_date)
            continued = bool(ctx.listed_today) or ctx.seen_after(
                (_d(eff) + timedelta(days=SEEN_AFTER_DAYS)).isoformat())
            ev = self._build_event(ctx, cik, filings, group, eff, continued)
            events.append(ev)
            if not continued:
                last_definitive = ev

        if not events:
            if ctx.listed_today is False:
                fb = self._fallback(ctx, cik, filings, ticker_last)
                if fb is not None:
                    events.append(fb)
                elif not had_unmatched:
                    review.append(ReviewItem(sec.sec_id, ticker_last, cik, "ended_without_delisting",
                                             "not listed today and no Form 25 or delisting filing found",
                                             last_seen=ctx.last_seen))
            elif ctx.listed_today is None:
                review.append(ReviewItem(sec.sec_id, ticker_last, cik, "listing_status_unknown",
                                         "listing status unknown and no delisting found",
                                         last_seen=ctx.last_seen))
        return events, review

    def _build_event(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
                     group: list[tuple[EdgarSubmission, Form25]], eff: str, continued: bool) -> DelistingEvent:
        sec = ctx.security
        winner_sub, winner_f25 = min(group, key=self._exchange_rank)
        ticker = ctx.ticker_on(winner_sub.filing_date) or sec.eras[-1].ticker
        lt = self._last_trade_group(cik, filings, group, ticker)
        anchor = lt.day.isoformat() if lt.day else winner_sub.filing_date
        rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=anchor, name=sec.name,
                                             expected_name=ctx.expected_name, kind=sec.kind, form25=winner_sub)
        return self._event(sec, cik, ticker, eff, rec, lt, winner_f25, winner_sub, continued)

    def _event(self, sec: Security, cik: int, ticker: str, delist_date: str, rec: DelistRecord, lt: LastTrade,
               f25: Form25 | None, sub: EdgarSubmission | None, continued: bool,
               extra_flags: tuple[str, ...] = ()) -> DelistingEvent:
        rec.sec_id = sec.sec_id
        rec.delist_date = delist_date
        flags = list(lt.flags) + list(extra_flags)
        if rec.bucket is CrspBucket.EXCHANGE_TRANSFER:
            if continued:
                rec.successor_sec_id = sec.sec_id
            else:
                flags.append("successor_unknown")
        ev_flags = rec.evidence.setdefault("flags", [])
        for f in flags:
            if f not in ev_flags:
                ev_flags.append(f)
        return DelistingEvent(sec.sec_id, cik, ticker, delist_date, rec, lt, f25, sub,
                              f25.exchange if f25 else "", flags)

    # -- no-Form-25 fallback ----------------------------------------------
    def _fallback_date(self, ctx: SecurityContext, ev: dict) -> tuple[str, tuple[str, ...]]:
        """Date a fallback delisting: the revocation filing, the confirmed
        bankruptcy 8-K, the anchor 8-K, then a Form 15 only if it falls within
        [last_seen - 30d, last_seen + 120d]; otherwise last_seen itself, flagged
        `delist_date_approx`."""
        for key in ("revoked_filing", "bankruptcy_8k", "anchor_8k"):
            f = ev.get(key)
            if f and f.get("filing_date"):
                return f["filing_date"], ()
        dereg = ev.get("dereg_filing")
        if dereg and dereg.get("filing_date"):
            fd = dereg["filing_date"]
            lo = (_d(ctx.last_seen) - timedelta(days=DEREG_FALLBACK_BEFORE_DAYS)).isoformat()
            hi = (_d(ctx.last_seen) + timedelta(days=DEREG_FALLBACK_AFTER_DAYS)).isoformat()
            if lo <= fd <= hi:
                return fd, ()
        return ctx.last_seen, ("delist_date_approx",)

    def _fallback(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
                  ticker: str) -> DelistingEvent | None:
        sec = ctx.security
        rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=ctx.last_seen, name=sec.name,
                                             expected_name=ctx.expected_name, kind=sec.kind, form25=None)
        ev = rec.evidence or {}
        if ev.get("delist_filing"):
            # The classifier picked a Form 25 on its own, ignoring class: the
            # main loop already decided about every Form 25 it could see, so a
            # filing that comes back here was rejected (ambiguous, another
            # sibling's, regional/secondary, another class, or before the
            # floor) — never revive it as this security's delisting.
            return None
        if rec.bucket is CrspBucket.UNKNOWN and not ev.get("deregistered"):
            return None
        ended_by, extra_flags = self._fallback_date(ctx, ev)
        lt = self._last_trade(cik, filings, None, ticker, _d(ended_by))
        if lt.day is None:
            lt = LastTrade(_d(ctx.last_seen), "", ("last_trade_date_unconfirmed",))
        return self._event(sec, cik, ticker, ended_by, rec, lt, None, None, False, ("no_form25", *extra_flags))

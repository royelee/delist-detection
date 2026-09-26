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
    REGIONAL_EXCHANGES, Form25, SecurityRef, class_kind, class_letters, effective_date, list_form25,
    match_securities, notice_last_trade, parse_form25, tied_securities,
)
from .last_trade import LastTrade, decide_last_trade, eightk_last_trade
from .listing_status import exchanges_around, issuer_exchange, withdrawal_kind
from .midas import MIDAS_START
from .nasdaq_halts import last_trade_from_halt
from .review_triage import ReviewItem
from .security_master import Security
from .store import DelistingKey
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
DEREG_FALLBACK_BEFORE_DAYS = 30     # a fallback revocation or Form 15 must be within
DEREG_FALLBACK_AFTER_DAYS = 120     # [last_seen - this, last_seen + this] to date the delisting

# Buckets whose delisting ends the security's exchange life even when it is
# sighted afterwards (OTC trading, a stale snapshot): all but a transfer and
# a delisting the classifier could not place.
ENDING_BUCKETS = frozenset({CrspBucket.MERGER, CrspBucket.LIQUIDATION, CrspBucket.COMPLIANCE_FAILURE,
                            CrspBucket.EXPIRATION})

# The review flag of an exchange transfer whose successor is not known yet; it
# comes off the delisting once a successor is found (`Delisting.set_successor`).
SUCCESSOR_UNKNOWN = "successor_unknown"

# Preferred exchange for a multi-exchange delisting group: the filing on the
# most-senior exchange supplies the delisting's `exchange` and `form25`/`form25_sub`.
EXCHANGE_PREFERENCE = ("NYSE", "NASDAQ", "NYSE AMERICAN", "CBOE BZX", "NYSE ARCA")


@dataclass
class Delisting:
    """One delisting of one security (CONTEXT.md): the Form 25 group (or the
    fallback filing) that ended its listing, dated and classified (`record`)."""
    sec_id: str
    cik: int
    ticker: str
    delist_date: str
    record: DelistRecord
    last_trade: LastTrade
    form25: Form25 | None
    form25_sub: EdgarSubmission | None
    exchange: str

    @property
    def key(self) -> DelistingKey:
        """`(sec_id, delist_date)`: the delisting's key in delistings.csv and in
        every per-delisting map of the run."""
        return DelistingKey(self.sec_id, self.delist_date)

    @property
    def flags(self) -> list[str]:
        """The delisting's review flags: its record's `evidence["flags"]`, the one
        list its delistings.csv row is built from (the classifier's flags, then
        the finder's and the pipeline's)."""
        return self.record.evidence.setdefault("flags", [])

    def add_flag(self, flag: str) -> None:
        self.flags.append(flag)

    def set_successor(self, sec_id: str) -> None:
        """Record `sec_id` as the successor: the row no longer says `successor_unknown`."""
        self.record.successor_sec_id = sec_id
        self.record.evidence["flags"] = [f for f in self.flags if f != SUCCESSOR_UNKNOWN]


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
    # The resolver tier that found this security's CIK (e.g. "cik_map",
    # "manual"); recorded on every DelistRecord this security's delistings
    # produce, in place of the classify_event default "security_master".
    resolution_source: str = "security_master"
    # True when an SEC fails-to-deliver row under one of the security's own
    # tickers is dated after the given ISO day: evidence of trading that an
    # observation alone does not give (a stale snapshot can list a security
    # long after it was acquired). Unknown (the default) counts as none.
    ftd_seen_after: Callable[[str], bool] = lambda day: False
    # Every ticker the security was sighted under between two ISO days (its own
    # and, from fails rows, an OTC symbol it moved to), for the exchange-trade
    # confirmations (MIDAS, Nasdaq halts): the ticker on a Form 25's date can be
    # the OTC symbol already (SAVE -> SAVEQ), which no exchange source knows.
    tickers_between: Callable[[str, str], list[str]] = lambda lo, hi: []


def _to_date(s: str) -> date:
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
        lo = (_to_date(first) - timedelta(days=SIBLING_ALIVE_BEFORE_DAYS)).isoformat()
        hi = (_to_date(last) + timedelta(days=SIBLING_ALIVE_AFTER_DAYS)).isoformat()
        return lo <= filing_date <= hi

    def _class_conflict(self, f25: Form25, ref: SecurityRef) -> bool:
        """True when the Form 25 names class letters and the matched sibling's
        class letter is not one of them: `match_securities`' single-sibling branch
        (`len(same) == 1`) accepts by elimination without checking letters, so
        this is the backstop for a class the universe doesn't actually hold."""
        f_letters = class_letters(f25.class_text)
        r_letter = class_letter(ref.share_class)
        return bool(f_letters and r_letter and r_letter not in f_letters)

    # -- last trade (single filing; used by the no-Form-25 fallback) -----
    def _eightk_window(self, cik: int, filings: list[EdgarSubmission], lo: date, hi: date,
                       anchor: date) -> tuple[date | None, str]:
        cands = [f for f in filings if f.form.startswith("8-K") and "3.01" in f.item_set
                 and f.filing_date and lo <= _to_date(f.filing_date) <= hi]
        for f in sorted(cands, key=lambda f: abs((_to_date(f.filing_date) - anchor).days)):
            got = eightk_last_trade(self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc))
            if got[0] is not None:
                return got
        return None, ""

    def _eightk(self, cik: int, filings: list[EdgarSubmission], filed: date) -> tuple[date | None, str]:
        return self._eightk_window(cik, filings, filed - timedelta(days=EIGHTK_BEFORE_DAYS),
                                   filed + timedelta(days=EIGHTK_AFTER_DAYS), filed)

    def _confirmations(self, tickers: list[str], filed: date, lo: date, hi: date, still_trading: date,
                       guesses: list[date]) -> tuple[date | None, date | None]:
        """(MIDAS last day with exchange volume, Nasdaq code-D halt day) over
        every ticker in `tickers`: MIDAS (asked when `filed` is in its
        coverage) takes the latest day in `[lo, hi]` before `still_trading`
        under any of them; the halt feed is asked only when MIDAS has nothing,
        around the text sources' `guesses`."""
        midas = None
        if self.midas is not None and filed >= MIDAS_START:
            days = [m for t in tickers if (m := self.midas.last_trade_day(t, lo, hi)) is not None
                    and m < still_trading]
            midas = max(days) if days else None
        halt = None
        if midas is None and self.halts is not None:
            for t in tickers:
                h = self.halts.deletion_halt(t, min(guesses) - timedelta(days=2),
                                             max(guesses) + timedelta(days=2), max_days=5)
                if h:
                    halt = last_trade_from_halt(h)
                    break
        return midas, halt

    @staticmethod
    def _tickers(ctx: SecurityContext | None, ticker: str, lo: date, hi: date) -> list[str]:
        """`ticker` first, then every other ticker the security carried in `[lo, hi]`."""
        others = ctx.tickers_between(lo.isoformat(), hi.isoformat()) if ctx is not None else []
        return list(dict.fromkeys([ticker, *others]))

    def _last_trade(self, cik: int, filings: list[EdgarSubmission], f25: Form25 | None, ticker: str,
                    filed: date, ctx: SecurityContext | None = None) -> LastTrade:
        notice = notice_last_trade(f25) if f25 else (None, "")
        eightk = self._eightk(cik, filings, filed)
        lo, hi = filed - timedelta(days=MIDAS_BEFORE_DAYS), filed + timedelta(days=MIDAS_AFTER_DAYS)
        midas, halt = self._confirmations(
            self._tickers(ctx, ticker, lo, hi), filed, lo, hi, filed + timedelta(days=MIDAS_STILL_TRADING_DAYS),
            [d for d, _ in (notice, eightk) if d] or [previous_trading_day(filed)])
        return decide_last_trade(notice=notice, eightk=eightk, midas=midas, halt=halt)

    # -- last trade for a group of Form 25s of one delisting --------------
    def _last_trade_group(self, cik: int, filings: list[EdgarSubmission],
                          group: list[tuple[EdgarSubmission, Form25]], ticker: str,
                          ctx: SecurityContext | None = None) -> LastTrade:
        subs = [s for s, _ in group]
        earliest_filed = _to_date(min(s.filing_date for s in subs))
        latest_filed = _to_date(max(s.filing_date for s in subs))
        latest_eff = _to_date(max(effective_date(s.filing_date) for s in subs))

        ordered = sorted(group, key=lambda item: (item[0].form != "25-NSE", item[0].filing_date))
        notice: tuple[date | None, str] = (None, "")
        for _, f25 in ordered:
            n = notice_last_trade(f25)
            if n[0] is not None:
                notice = n
                break

        eightk = self._eightk_window(cik, filings, earliest_filed - timedelta(days=EIGHTK_BEFORE_DAYS),
                                     latest_filed + timedelta(days=EIGHTK_GROUP_AFTER_DAYS), earliest_filed)

        lo = earliest_filed - timedelta(days=MIDAS_BEFORE_DAYS)
        hi = latest_eff + timedelta(days=MIDAS_AFTER_DAYS)
        midas, halt = self._confirmations(
            self._tickers(ctx, ticker, lo, hi), earliest_filed, lo, hi,
            latest_eff + timedelta(days=MIDAS_STILL_TRADING_DAYS),
            [d for d, _ in (notice, eightk) if d] or [previous_trading_day(latest_filed)])
        return decide_last_trade(notice=notice, eightk=eightk, midas=midas, halt=halt)

    # -- grouping -----------------------------------------------------------
    def _group(self, candidates: list[tuple[EdgarSubmission, Form25]]
              ) -> list[list[tuple[EdgarSubmission, Form25]]]:
        """Chain matched Form 25s into one group per delisting: each filing joins
        the open group when it's within SAME_EVENT_DAYS of the group's EARLIEST
        filing (not its latest member), across exchanges — so filings on days
        0, 28 and 55 make two delistings (day 55 is 55 days from day 0), not one."""
        groups: list[list[tuple[EdgarSubmission, Form25]]] = []
        for item in sorted(candidates, key=lambda i: i[0].filing_date):
            gap = (_to_date(item[0].filing_date) - _to_date(groups[-1][0][0].filing_date)).days if groups else None
            if gap is not None and gap <= SAME_EVENT_DAYS:
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
    def find(self, ctx: SecurityContext) -> tuple[list[Delisting], list[ReviewItem]]:
        sec = ctx.security
        if not sec.eras:
            return [], []
        cik = sec.issuer_cik
        ticker_last = sec.eras[-1].ticker
        if cik is None:
            if ctx.listed_today is False:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "ended_without_delisting",
                                       "no issuer CIK to search for a Form 25", last_seen=ctx.last_seen)]
            if ctx.listed_today is None:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "listing_status_unknown",
                                       "no issuer CIK and listing status unknown", last_seen=ctx.last_seen)]
            return [], []

        filings = self.edgar.recent_filings(cik)
        first_seen = min(e.first for e in sec.eras)
        floor = (_to_date(first_seen) - timedelta(days=FORM25_LOOKBACK_DAYS)).isoformat()

        review: list[ReviewItem] = []
        seen_review: set[tuple[str, str]] = set()
        had_unmatched = False
        candidates: list[tuple[EdgarSubmission, Form25]] = []
        early: list[EdgarSubmission] = []       # before the floor: only the fallback may take one

        for sub in list_form25(filings):
            if sub.filing_date < floor:
                early.append(sub)
                continue
            # Filings that plainly aren't about any security of this issuer
            # (none of the observed securities were even alive on this date)
            # get no review item at all, so these checks come before the
            # readability/classification ones below.
            alive = [r for r in ctx.siblings if self._alive_at(ctx, r.sec_id, sub.filing_date)]
            if not alive:
                continue
            raw = self.edgar.fetch_filing_raw(cik, sub.accession)
            if not raw:
                had_unmatched = True
                self._review(review, seen_review, sec, ticker_last, cik, "form25_unreadable",
                             f"no filing text for {sub.form} {sub.accession}", sub)
                continue
            f25 = parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date)
            if f25.exchange in REGIONAL_EXCHANGES:
                continue
            if class_kind(f25.class_text) == "other":
                had_unmatched = True
                self._review(review, seen_review, sec, ticker_last, cik, "form25_unclassified",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}) has no recognized class", sub)
                continue
            matched, why = match_securities(f25, alive)
            if not matched:
                if why == "ambiguous class":
                    had_unmatched = True
                    self._review(review, seen_review, sec, ticker_last, cik, "form25_unmatched",
                                 f"{sub.form} {sub.accession} ({f25.class_text!r}): {why}", sub)
                continue
            if sec.sec_id not in matched:
                if sec.sec_id in tied_securities(f25, alive):
                    # another class of this Form 25 matched; this one shares its
                    # letter with a sibling no name word tells apart, or has none
                    had_unmatched = True
                    self._review(review, seen_review, sec, ticker_last, cik, "form25_unmatched",
                                 f"{sub.form} {sub.accession} ({f25.class_text!r}): ambiguous class", sub)
                continue
            ref = next((r for r in alive if r.sec_id == sec.sec_id), None)
            if ref is not None and self._class_conflict(f25, ref):
                continue
            eff = effective_date(sub.filing_date)
            continued = bool(ctx.listed_today) or ctx.seen_after(
                (_to_date(eff) + timedelta(days=SEEN_AFTER_DAYS)).isoformat())
            if continued:
                before, after = exchanges_around(self.edgar, cik, filings, _to_date(sub.filing_date))
                if withdrawal_kind(f25.exchange, before, after) == "secondary":
                    continue
                if after is not None and f25.exchange in after:
                    continue        # the next 10-K cover still names it: another class left, not this one
            candidates.append((sub, f25))

        delistings: list[Delisting] = []
        last_definitive: Delisting | None = None
        for group in self._group(candidates):
            earliest_sub = min(group, key=lambda item: item[0].filing_date)[0]
            if last_definitive is not None:
                gap = (_to_date(earliest_sub.filing_date) - _to_date(last_definitive.delist_date)).days
                if gap > IGNORE_AFTER_DEFINITIVE_DAYS and not ctx.seen_after(earliest_sub.filing_date):
                    continue        # a security truly gone can't have a later Form 25 of its own
            eff = effective_date(earliest_sub.filing_date)
            continued = bool(ctx.listed_today) or ctx.seen_after(
                (_to_date(eff) + timedelta(days=SEEN_AFTER_DAYS)).isoformat())
            delisting = self._build_delisting(ctx, cik, filings, group, eff, continued)
            delistings.append(delisting)
            # Sightings after the effective date can be an OTC tail or a stale
            # snapshot, not a listing: only an exchange transfer (or a delisting
            # not classified) continues one. A merger, liquidation, compliance
            # failure or expiration ends the security's exchange life.
            if not continued or delisting.record.bucket in ENDING_BUCKETS:
                last_definitive = delisting

        # spec 8.10: run the fallback / ended_without_delisting logic whenever
        # no delisting found is a genuine end (every one is `continued`, e.g. an
        # exchange transfer the security kept trading through) -- not only
        # when `delistings` is empty. Otherwise a security whose only delistings
        # are continued ones gets neither a real delisting nor a review row.
        if last_definitive is None:
            if ctx.listed_today is False:
                fb = self._fallback(ctx, cik, filings, ticker_last, early)
                if fb is not None:
                    delistings.append(fb)
                else:
                    # Also next to form25_* rows: those say a filing could not be
                    # placed; accepting one as "not about this security" must not
                    # drop the security itself from review (spec 8.10, G6).
                    why = ("no Form 25 matched it (see its form25_* rows) and no other delisting filing found"
                           if had_unmatched else "no Form 25 or delisting filing found")
                    review.append(ReviewItem(sec.sec_id, ticker_last, cik, "ended_without_delisting",
                                             f"not listed today and {why}", last_seen=ctx.last_seen))
            elif ctx.listed_today is None:
                review.append(ReviewItem(sec.sec_id, ticker_last, cik, "listing_status_unknown",
                                         "listing status unknown and no delisting found",
                                         last_seen=ctx.last_seen))
        return delistings, review

    def _build_delisting(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
                     group: list[tuple[EdgarSubmission, Form25]], eff: str, continued: bool,
                     extra_flags: tuple[str, ...] = ()) -> Delisting:
        sec = ctx.security
        winner_sub, winner_f25 = min(group, key=self._exchange_rank)
        filing_ticker = ctx.ticker_on(winner_sub.filing_date) or sec.eras[-1].ticker
        lt = self._last_trade_group(cik, filings, group, filing_ticker, ctx)
        # spec 7.4: the delisting's ticker is the ticker on the last trade
        # date, not on the Form 25 filing date -- only fall back to the
        # filing-date ticker when the last trade date itself is unknown.
        ticker = (lt.day and ctx.ticker_on(lt.day.isoformat())) or filing_ticker
        anchor = lt.day.isoformat() if lt.day else winner_sub.filing_date
        rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=anchor, name=sec.name,
                                             expected_name=ctx.expected_name, kind=sec.kind, form25=winner_sub,
                                             resolution_source=ctx.resolution_source)
        return self._delisting(sec, cik, ticker, eff, rec, lt, winner_f25, winner_sub, continued, extra_flags)

    def _delisting(self, sec: Security, cik: int, ticker: str, delist_date: str, rec: DelistRecord, lt: LastTrade,
               f25: Form25 | None, sub: EdgarSubmission | None, continued: bool,
               extra_flags: tuple[str, ...] = (), exchange: str = "") -> Delisting:
        rec.sec_id = sec.sec_id
        rec.delist_date = delist_date
        flags = list(lt.flags) + list(extra_flags)
        if rec.bucket is CrspBucket.EXCHANGE_TRANSFER:
            if continued:
                rec.successor_sec_id = sec.sec_id
            else:
                flags.append(SUCCESSOR_UNKNOWN)
        delisting = Delisting(sec.sec_id, cik, ticker, delist_date, rec, lt, f25, sub,
                              f25.exchange if f25 else exchange)
        for f in flags:
            if f not in delisting.flags:
                delisting.add_flag(f)
        return delisting

    # -- no-Form-25 fallback ----------------------------------------------
    def _fallback_date(self, ctx: SecurityContext, evidence: dict) -> tuple[str, tuple[str, ...]]:
        """Date a fallback delisting: the confirmed bankruptcy 8-K, then the
        anchor 8-K, then the revocation filing or a Form 15 but only if either
        falls within [last_seen - 30d, last_seen + 120d]; otherwise last_seen
        itself, flagged `delist_date_approx`.

        A revocation is not trusted outright: SEC revokes a delinquent filer's
        registration years after trading actually stopped, and this date feeds
        the return calculation, so a distant revocation is no better than
        having no filing at all — last_seen plus the approx flag is closer to
        the truth than a multi-year-late revocation date.
        """
        for key in ("bankruptcy_8k", "anchor_8k"):
            f = evidence.get(key)
            if f and f.get("filing_date"):
                return f["filing_date"], ()
        lo = (_to_date(ctx.last_seen) - timedelta(days=DEREG_FALLBACK_BEFORE_DAYS)).isoformat()
        hi = (_to_date(ctx.last_seen) + timedelta(days=DEREG_FALLBACK_AFTER_DAYS)).isoformat()
        for key in ("revoked_filing", "dereg_filing"):
            f = evidence.get(key)
            fd = f.get("filing_date") if f else None
            if fd and lo <= fd <= hi:
                return fd, ()
        return ctx.last_seen, ("delist_date_approx",)

    def _early_group(self, ctx: SecurityContext, cik: int, picked: str,
                     early: list[EdgarSubmission]) -> list[tuple[EdgarSubmission, Form25]]:
        """The Form 25 `picked` (an accession) from `early`, the filings dated
        before the main scan's floor, with its early neighbours within
        SAME_EVENT_DAYS — each kept only when it matches this security by the
        main scan's own rules (readable, not regional, a recognized class, and
        `match_securities` against this security and the siblings alive then).
        The security itself counts as alive: its first sighting is what put
        the filing before the floor. Empty when `picked` is not early."""
        sec = ctx.security
        anchor = next((s for s in early if s.accession == picked), None)
        if anchor is None:
            return []
        own = next((r for r in ctx.siblings if r.sec_id == sec.sec_id), SecurityRef(sec.sec_id, sec.share_class,
                                                                                     sec.kind, sec.name))
        group: list[tuple[EdgarSubmission, Form25]] = []
        for sub in early:
            if abs((_to_date(sub.filing_date) - _to_date(anchor.filing_date)).days) > SAME_EVENT_DAYS:
                continue
            raw = self.edgar.fetch_filing_raw(cik, sub.accession)
            if not raw:
                continue
            f25 = parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date)
            if f25.exchange in REGIONAL_EXCHANGES or class_kind(f25.class_text) == "other":
                continue
            alive = [own] + [r for r in ctx.siblings
                             if r.sec_id != sec.sec_id and self._alive_at(ctx, r.sec_id, sub.filing_date)]
            matched, _ = match_securities(f25, alive)
            if sec.sec_id in matched and not self._class_conflict(f25, own):
                group.append((sub, f25))
        return group

    def _fallback(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
                  ticker: str, early: list[EdgarSubmission] | None = None) -> Delisting | None:
        sec = ctx.security
        rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=ctx.last_seen, name=sec.name,
                                             expected_name=ctx.expected_name, kind=sec.kind, form25=None,
                                             resolution_source=ctx.resolution_source)
        evidence = rec.evidence or {}
        if evidence.get("delist_filing"):
            # The classifier picked a Form 25 on its own, ignoring class. The
            # main loop already decided about every Form 25 from the floor on,
            # so such a filing was rejected (ambiguous, another sibling's,
            # regional/secondary, another class) — never revive it. A filing
            # from before the floor was never judged: the security's first
            # sighting came after it, as when a stale index snapshot kept
            # listing a security acquired months earlier. The classifier's own
            # frozen-tail rule chose it for a security gone today, so it is
            # the delisting when it matches this security by class and no
            # fails-to-deliver row under the security's own tickers shows it
            # trading after it; the observations after it are flagged
            # `observed_after_delisting`.
            group = self._early_group(ctx, cik, evidence["delist_filing"].get("accession") or "", early or [])
            if not group:
                return None
            eff = effective_date(min(s.filing_date for s, _ in group))
            if ctx.ftd_seen_after((_to_date(eff) + timedelta(days=SEEN_AFTER_DAYS)).isoformat()):
                return None
            return self._build_delisting(ctx, cik, filings, group, eff, False, ("observed_after_delisting",))
        if rec.bucket is CrspBucket.UNKNOWN and not evidence.get("deregistered"):
            return None
        ended_by, extra_flags = self._fallback_date(ctx, evidence)
        lt = self._last_trade(cik, filings, None, ticker, _to_date(ended_by), ctx)
        if lt.day is None:
            lt = LastTrade(_to_date(ctx.last_seen), "", ("last_trade_date_unconfirmed",))
        # No Form 25 means no exchange evidence from a filing; fall back to
        # whatever exchange EDGAR's own submissions JSON records for this
        # ticker (spec D22) rather than leaving it blank -- which otherwise
        # maps to Exchange.OTHER and applies the wrong Shumway constant.
        exch = issuer_exchange(self.edgar, cik, ticker) or ""
        return self._delisting(sec, cik, ticker, ended_by, rec, lt, None, None, False, ("no_form25", *extra_flags),
                           exchange=exch)

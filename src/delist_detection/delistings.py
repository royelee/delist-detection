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
from .form25 import (
    REGIONAL_EXCHANGES, Form25, SecurityRef, effective_date, list_form25, match_security, notice_last_trade,
    parse_form25,
)
from .last_trade import LastTrade, decide_last_trade, eightk_last_trade
from .listing_status import exchanges_around, withdrawal_kind
from .midas import MIDAS_START
from .nasdaq_halts import last_trade_from_halt
from .security_master import Security
from .trading_calendar import previous_trading_day

FORM25_LOOKBACK_DAYS = 30
SAME_EVENT_DAYS = 30
MIDAS_BEFORE_DAYS, MIDAS_AFTER_DAYS, MIDAS_STILL_TRADING_DAYS = 75, 10, 5
EIGHTK_BEFORE_DAYS, EIGHTK_AFTER_DAYS = 60, 5


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


def _d(s: str) -> date:
    return date.fromisoformat(s)


class DelistingFinder:
    def __init__(self, edgar, classifier: DelistClassifier, *, midas=None, halts=None) -> None:
        self.edgar, self.classifier, self.midas, self.halts = edgar, classifier, midas, halts

    # -- last trade ------------------------------------------------------
    def _eightk(self, cik: int, filings: list[EdgarSubmission], filed: date) -> tuple[date | None, str]:
        lo, hi = filed - timedelta(days=EIGHTK_BEFORE_DAYS), filed + timedelta(days=EIGHTK_AFTER_DAYS)
        cands = [f for f in filings if f.form.startswith("8-K") and "3.01" in f.item_set
                 and f.filing_date and lo <= _d(f.filing_date) <= hi]
        for f in sorted(cands, key=lambda f: abs((_d(f.filing_date) - filed).days)):
            got = eightk_last_trade(self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc))
            if got[0] is not None:
                return got
        return None, ""

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

    # -- main ------------------------------------------------------------
    def find(self, ctx: SecurityContext) -> tuple[list[DelistingEvent], list[ReviewItem]]:
        sec = ctx.security
        cik = sec.issuer_cik
        ticker_last = sec.eras[-1].ticker if sec.eras else ""
        if cik is None:
            if ctx.listed_today is False:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "ended_without_delisting",
                                       "no issuer CIK to search for a Form 25", last_seen=ctx.last_seen)]
            return [], []
        filings = self.edgar.recent_filings(cik)
        first_seen = min(e.first for e in sec.eras) if sec.eras else "0000-01-01"
        floor = (_d(first_seen) - timedelta(days=FORM25_LOOKBACK_DAYS)).isoformat()
        events: list[DelistingEvent] = []
        review: list[ReviewItem] = []
        for sub in list_form25(filings):
            if sub.filing_date < floor:
                continue
            f25 = parse_form25(self.edgar.fetch_filing_raw(cik, sub.accession), accession=sub.accession,
                               form=sub.form, filing_date=sub.filing_date)
            matched, why = match_security(f25, ctx.siblings)
            if matched is None:
                if why == "ambiguous class":
                    review.append(ReviewItem(sec.sec_id, ticker_last, cik, "form25_unmatched",
                                             f"{sub.form} {sub.accession} ({f25.class_text!r}): {why}"))
                continue
            if matched != sec.sec_id or f25.exchange in REGIONAL_EXCHANGES:
                continue
            eff = effective_date(sub.filing_date)
            continued = bool(ctx.listed_today) or ctx.seen_after(
                (_d(eff) + timedelta(days=5)).isoformat())
            if continued:
                before, after = exchanges_around(self.edgar, cik, filings, _d(sub.filing_date))
                if withdrawal_kind(f25.exchange, before, after) == "secondary":
                    continue
            if any(e.exchange == f25.exchange and abs((_d(e.form25_sub.filing_date) - _d(sub.filing_date)).days)
                   <= SAME_EVENT_DAYS for e in events if e.form25_sub):
                continue
            ticker = ctx.ticker_on(sub.filing_date) or ticker_last
            lt = self._last_trade(cik, filings, f25, ticker, _d(sub.filing_date))
            anchor = lt.day.isoformat() if lt.day else sub.filing_date
            rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=anchor, name=sec.name,
                                                 expected_name=ctx.expected_name, kind=sec.kind, form25=sub)
            events.append(self._event(sec, cik, ticker, eff, rec, lt, f25, sub, continued))
        if not events and ctx.listed_today is False:
            ev = self._fallback(ctx, cik, filings, ticker_last)
            if ev is not None:
                events.append(ev)
            else:
                review.append(ReviewItem(sec.sec_id, ticker_last, cik, "ended_without_delisting",
                                         "not listed today and no Form 25 or delisting filing found",
                                         last_seen=ctx.last_seen))
        return events, review

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

    def _fallback(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
                  ticker: str) -> DelistingEvent | None:
        sec = ctx.security
        rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=ctx.last_seen, name=sec.name,
                                             expected_name=ctx.expected_name, kind=sec.kind, form25=None)
        ev = rec.evidence or {}
        if rec.bucket is CrspBucket.UNKNOWN and not ev.get("deregistered"):
            return None
        delist_filing = ev.get("delist_filing") or {}
        ended_by = (delist_filing.get("filing_date") or (ev.get("revoked_filing") or {}).get("filing_date")
                    or (ev.get("anchor_8k") or {}).get("filing_date")
                    or (ev.get("dereg_filing") or {}).get("filing_date") or ctx.last_seen)
        delist_date = effective_date(ended_by) if delist_filing else ended_by
        lt = self._last_trade(cik, filings, None, ticker, _d(ended_by))
        if lt.day is None:
            lt = LastTrade(_d(ctx.last_seen), "", ("last_trade_date_unconfirmed",))
        return self._event(sec, cik, ticker, delist_date, rec, lt, None, None, False, ("no_form25",))

"""EDGAR filing-selection primitives, shared across merger extractors.

The tiered closing-8-K → announcement-8-K → merger-proxy selection logic was
factored out of `payout_extractor.py` so a forthcoming LLM merger extractor can
reuse the same window/sort/bound predicates. Pure: no network, no I/O.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .edgar import EdgarSubmission


# Deal-close 8-Ks (Item 2.01) can precede the recorded delist date by weeks
# to months (the security lingers on OTC, or the universe records a later
# last-trade date). Mirror the classifier's 120-day backscan on the "before"
# side; keep "after" tight since a true closing 8-K rarely lags the delist.
CLOSING_WINDOW = (timedelta(days=120), timedelta(days=30))    # (before, after) delist
ANNOUNCE_WINDOW = (timedelta(days=365), timedelta(days=7))    # before delist


def parse_date(s: str | None) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def in_window(f: EdgarSubmission, delist: date | None,
              before: timedelta, after: timedelta) -> bool:
    if delist is None:
        return True
    fd = parse_date(f.report_date) or parse_date(f.filing_date)
    if fd is None:
        return False
    return (delist - before) <= fd <= (delist + after)


def closing_8k(filings, delist):
    before, after = CLOSING_WINDOW
    out = [f for f in filings
           if f.form == "8-K" and "2.01" in f.item_set
           and in_window(f, delist, before, after)]
    anchor = delist or date.min
    out.sort(key=lambda f: abs(((parse_date(f.report_date) or parse_date(f.filing_date) or anchor) - anchor).days))
    return out


def announcement_8k(filings, delist):
    before, after = ANNOUNCE_WINDOW
    out = [f for f in filings
           if f.form == "8-K" and "1.01" in f.item_set
           and in_window(f, delist, before, after)]
    out.sort(key=lambda f: (parse_date(f.report_date) or parse_date(f.filing_date) or date.min), reverse=True)
    return out


def form_filings(filings, form, delist):
    out = [f for f in filings if f.form == form]
    if delist is not None:
        # A merger proxy is filed within a couple of years of close; bound
        # both sides so a recycled CIK's decades-old proxy cannot match.
        lo, hi = delist - timedelta(days=730), delist + timedelta(days=30)
        out = [f for f in out if (fd := parse_date(f.filing_date)) and lo <= fd <= hi]
    out.sort(key=lambda f: (parse_date(f.filing_date) or date.min), reverse=True)
    return out

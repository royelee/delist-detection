"""Pure evidence predicates over one company's EDGAR record. No network."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .edgar import EdgarSubmission

_BANKRUPTCY_TEXT = re.compile(r"bankruptcy|chapter\s+(?:11|7)\b|receivership", re.I)


def parse_day(s: str | None) -> date | None:
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def name_at(sub: dict, on: date) -> str:
    """The EDGAR name on `on`: the formerNames entry whose [from, to] covers it, else the current name."""
    for fn in sub.get("formerNames") or []:
        lo, hi = parse_day(fn.get("from")), parse_day(fn.get("to"))
        if lo and hi and lo <= on <= hi:
            return fn.get("name") or ""
    return sub.get("name") or ""


def names_near(sub: dict, on: date, days: int = 30) -> list[str]:
    """Every name the company carried within ±days of `on`, former names first.

    A delisting date and a rename date are often a day apart (EDGAR ends
    "Halyard Health" on 2018-06-28; HYH's last vendor row is 2018-06-29), so a
    single-day lookup misses the name the index used."""
    lo, hi = on - timedelta(days=days), on + timedelta(days=days)
    out: list[str] = []
    last_end: date | None = None
    for fn in sub.get("formerNames") or []:
        f_lo, f_hi = parse_day(fn.get("from")), parse_day(fn.get("to"))
        if f_hi and (last_end is None or f_hi > last_end):
            last_end = f_hi
        if f_lo and f_hi and f_lo <= hi and f_hi >= lo and fn.get("name"):
            out.append(fn["name"])
    if (last_end is None or last_end <= hi) and sub.get("name"):
        out.append(sub["name"])      # the current name runs from the last rename on
    return out


def first_filing(filings: list[EdgarSubmission]) -> date | None:
    days = [d for f in filings if (d := parse_day(f.filing_date))]
    return min(days) if days else None


def bankruptcy_8ks(filings: list[EdgarSubmission], on: date, before: int = 540, after: int = 30) -> list[EdgarSubmission]:
    """8-Ks tagged item 1.03 (Bankruptcy or Receivership) within [on-before, on+after]."""
    lo, hi = on - timedelta(days=before), on + timedelta(days=after)
    out = []
    for f in filings:
        d = parse_day(f.report_date) or parse_day(f.filing_date)
        if f.form.startswith("8-K") and "1.03" in f.item_set and d and lo <= d <= hi:
            out.append(f)
    return sorted(out, key=lambda f: f.filing_date)


def mentions_bankruptcy(text: str) -> bool:
    return bool(_BANKRUPTCY_TEXT.search(text or ""))


OPERATING_FORMS = {"10-K", "10-Q", "20-F", "40-F"}


def filed_operating_between(filings: list[EdgarSubmission], lo: date, hi: date) -> bool:
    """True if the company filed a periodic operating report (or an 8-K with
    earnings item 2.02) strictly between `lo` and `hi` — evidence that an
    earlier Form 25 candidate is a different, still-operating event rather
    than the anchor for the delisting at `hi`."""
    for f in filings:
        d = parse_day(f.filing_date)
        if d and lo < d < hi and (f.form in OPERATING_FORMS or (f.form == "8-K" and "2.02" in f.item_set)):
            return True
    return False

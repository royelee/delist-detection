"""Pure evidence predicates over one company's EDGAR record. No network."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .edgar import EdgarSubmission


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

"""Where a security is listed: before and after a Form 25, and today.

A Form 25 that withdraws a secondary listing (Apache from the Chicago Stock
Exchange in 2020 while it stayed on NYSE) is not a delisting (D17). The 10-K
cover page names every exchange a class is registered on, so the covers on
either side of the Form 25 tell the cases apart.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta

from .edgar import EdgarSubmission
from .evidence import parse_day
from .figi_resolution import is_placeholder
from .form25 import MAJOR_EXCHANGES, REGIONAL_EXCHANGES, exchange_label, exchanges_named

ANNUAL_FORMS = frozenset({"10-K", "10-K405", "10-KSB", "10-KT", "20-F", "40-F"})
EXCHANGE_VENUES = frozenset({"UN", "UW", "UQ", "UR", "UA", "UP", "UF"})
COVER_WINDOW_DAYS = 450


def cover_exchanges(text: str) -> set[str]:
    head = (text or "")[:12000]
    m = re.search(r"name of each exchange on which registered", head, re.I)
    window = head[m.start(): m.start() + 1500] if m else head[:4000]
    return exchanges_named(window) & (MAJOR_EXCHANGES | REGIONAL_EXCHANGES)


def _annual(filings: Iterable[EdgarSubmission]) -> list[tuple[date, EdgarSubmission]]:
    out = [(d, f) for f in filings if f.form in ANNUAL_FORMS and (d := parse_day(f.filing_date))]
    return sorted(out, key=lambda x: x[0])


def exchanges_around(edgar, cik: int, filings: list[EdgarSubmission],
                     day: date) -> tuple[set[str] | None, set[str] | None]:
    reports = _annual(filings)
    window = timedelta(days=COVER_WINDOW_DAYS)
    before = [f for d, f in reports if day - window <= d < day]
    after = [f for d, f in reports if day < d <= day + window]

    def read(f: EdgarSubmission) -> set[str]:
        return cover_exchanges(edgar.fetch_filing_text(cik, f.accession, f.primary_doc))

    return (read(before[-1]) if before else None), (read(after[0]) if after else None)


def withdrawal_kind(exchange: str, before: set[str] | None, after: set[str] | None) -> str:
    if exchange in REGIONAL_EXCHANGES:
        return "secondary"
    if exchange not in MAJOR_EXCHANGES or after is None:
        return "delisting"
    remaining = (after & MAJOR_EXCHANGES) - {exchange}
    if not remaining:
        return "delisting"
    if before is not None and remaining <= before:
        return "secondary"
    return "delisting"


def listed_today(figi, sec_id: str, *, edgar=None, cik: int | None = None) -> bool | None:
    if not is_placeholder(sec_id):
        ans = figi.map([{"idType": "COMPOSITE_ID_BB_GLOBAL", "idValue": sec_id}], use_cache=False)[0]
        if "error" in ans:
            return None
        return any(r.get("exchCode") in EXCHANGE_VENUES for r in ans.get("data") or [])
    if edgar is None or cik is None:
        return None
    sub = edgar.submissions(cik)
    labels = {exchange_label(x) for x in (sub.get("exchanges") or []) if x} if isinstance(sub, dict) else set()
    return bool(labels & MAJOR_EXCHANGES)

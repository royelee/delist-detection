"""Company-name tokens and the caller-supplied index-member names."""
from __future__ import annotations

import csv
import re
from bisect import bisect_right
from pathlib import Path

_STOP = {"CORP", "CORPORATION", "INC", "INCORPORATED", "COMPANY", "COS", "HOLDINGS", "HOLDING",
         "LTD", "LIMITED", "LLC", "PLC", "GROUP", "INTERNATIONAL", "INTL", "TRUST", "PARTNERS",
         "FUND", "BANK", "BANCORP", "BANCSHARES", "CLASS", "SERIES", "COMMON", "STOCK", "SHARES",
         "THE", "AND", "NEW"}


def name_tokens(name: str) -> set[str]:
    """Words of three or more letters, minus legal suffixes and fillers. Three-letter
    words stay because they are often the distinctive part (XTO, OIL, SVB, UTI)."""
    return {t for t in re.findall(r"[A-Z]{3,}", (name or "").upper()) if t not in _STOP}


def names_agree(a: str, b: str) -> bool:
    """Two names agree when they share min(2, |A|, |B|) words, and at least one.
    One shared word is not enough when both names have two or more: Forest Oil is
    not Forest City (FST), Leap Wireless is not Ribbit LEAP (LEAP)."""
    ta, tb = name_tokens(a), name_tokens(b)
    need = min(2, len(ta), len(tb))
    return need >= 1 and len(ta & tb) >= need


class MemberNames:
    """(ticker, date) -> the index member's name as the index recorded it.

    CSV columns: ticker, as_of, name. The row used is the latest one with
    as_of <= date (the member the index held before the delisting)."""

    def __init__(self, rows: dict[str, list[tuple[str, str]]]) -> None:
        self._rows = {t: sorted(v) for t, v in rows.items()}

    @classmethod
    def from_csv(cls, path: str | Path) -> "MemberNames":
        rows: dict[str, list[tuple[str, str]]] = {}
        with Path(path).open(newline="") as fh:
            for r in csv.DictReader(fh):
                rows.setdefault(r["ticker"].strip().upper(), []).append((r["as_of"], r["name"]))
        return cls(rows)

    def __call__(self, ticker: str, observed_date: str | None = None) -> str | None:
        rows = self._rows.get(ticker.upper())
        if not rows:
            return None
        if observed_date is None:
            return rows[-1][1]
        i = bisect_right([d for d, _ in rows], observed_date)
        return rows[i - 1][1] if i else None

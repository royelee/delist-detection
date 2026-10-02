"""What ties a placeholder's ticker to its CIK (decision 1 of the Delist Library
Reset: a placeholder counts as confirmed only when a filing check finds the
ticker under that CIK).

A placeholder is a security with no FIGI, known only by its issuer CIK and
share class. Its identity is confirmed when:
- the resolver tier that found the CIK of one of its eras already ties the
  ticker to it: a caller's pin or hand override (`cik_map`, `manual`,
  `rename`), the Form 25/15 full-text tier that matched the ticker's own
  `(TICKER)` token (`efts`), or EDGAR's current ticker map (`company_tickers`);
- or else EDGAR's full-text search finds the ticker in one of that CIK's own
  filings dated within a year of the era's sightings (`ticker_filing`).
A ticker shorter than MIN_SEARCH_TICKER is never searched: the phrase would
match ordinary words in the issuer's own filings.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

TICKER_TIERS = frozenset({"cik_map", "manual", "rename", "efts", "company_tickers"})
SEARCH_FORMS = "8-K,10-K,10-Q,DEF 14A,25-NSE,20-F,6-K,40-F"
SEARCH_PAD_DAYS = 365
MIN_SEARCH_TICKER = 3


@dataclass(frozen=True)
class EraEvidence:
    ticker: str
    first: str               # the era's first and last sightings, ISO dates
    last: str
    tier: str                # the resolver tier that found the era's CIK ("" when unknown)


def ticker_filing(search: Callable, cik: int, ticker: str, first: str, last: str) -> str | None:
    """The accession of a filing by `cik` whose text names `ticker`, filed within
    SEARCH_PAD_DAYS of [first, last], or None. `search` is
    EdgarClient.full_text_search; a hit counts only when its own `ciks` list
    holds `cik`."""
    if len(ticker) < MIN_SEARCH_TICKER:
        return None
    lo = date.fromisoformat(first) - timedelta(days=SEARCH_PAD_DAYS)
    hi = date.fromisoformat(last) + timedelta(days=SEARCH_PAD_DAYS)
    for hit in search(f'"{ticker}"', SEARCH_FORMS, lo, hi, ciks=(cik,)):
        src = hit.get("_source", {})
        if any(int(c) == cik for c in src.get("ciks") or []):
            return src.get("adsh") or hit.get("_id", "")
    return None


def evidence_for(cik: int | None, eras: Sequence[EraEvidence], search: Callable | None) -> str:
    """`tier:<tier>` when a resolver tier ties an era's ticker to `cik`, else
    `filing:<accession>` when `search` finds a filing, else "" (no evidence:
    no CIK, no search, or no hit)."""
    for era in eras:
        if era.tier in TICKER_TIERS:
            return f"tier:{era.tier}"
    if cik is None or search is None:
        return ""
    for era in eras:
        accession = ticker_filing(search, cik, era.ticker, era.first, era.last)
        if accession:
            return f"filing:{accession}"
    return ""

"""Listing-exchange normalization for delisting-bias corrections.

The Shumway 1997 / Shumway-Warther 1999 constants are exchange-specific:
NYSE/AMEX performance delistings average ~-30%, Nasdaq ~-55%. We collapse
the proliferation of venue strings (NYSE Arca, NYSE MKT, Nasdaq Global
Select, ...) to four buckets that match how the constants were estimated.
"""

from __future__ import annotations

from enum import Enum


class Exchange(str, Enum):
    NYSE = "nyse"
    AMEX = "amex"
    NASDAQ = "nasdaq"
    OTHER = "other"  # OTC, BATS, IEX, unknown — no Shumway constant applies


_NYSE_TOKENS = ("nyse", "new york stock exchange", "arca")
_AMEX_TOKENS = ("amex", "nyse american", "nyse mkt", "american stock exchange")
_NASDAQ_TOKENS = ("nasdaq",)


def normalize_exchange(raw: str | None) -> Exchange:
    """Map a raw exchange string to the canonical Exchange bucket.

    AMEX is checked before NYSE because "NYSE American" / "NYSE MKT" contain
    "nyse" but represent the AMEX successor venue.
    """
    if not raw:
        return Exchange.OTHER
    s = raw.strip().lower()
    if any(t in s for t in _AMEX_TOKENS):
        return Exchange.AMEX
    if any(t in s for t in _NYSE_TOKENS):
        return Exchange.NYSE
    if any(t in s for t in _NASDAQ_TOKENS):
        return Exchange.NASDAQ
    return Exchange.OTHER

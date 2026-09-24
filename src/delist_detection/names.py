"""Company-name tokens and agreement."""
from __future__ import annotations

import re

_STOP = {"CORP", "CORPORATION", "INC", "INCORPORATED", "COMPANY", "COS", "HOLDINGS", "HOLDING",
         "LTD", "LIMITED", "LLC", "PLC", "GROUP", "INTERNATIONAL", "INTL", "TRUST", "PARTNERS",
         "FUND", "BANK", "BANCORP", "BANCSHARES", "CLASS", "SERIES", "COMMON", "STOCK", "SHARES",
         "THE", "AND", "NEW"}


def name_tokens(name: str) -> set[str]:
    """Words of three or more letters, minus legal suffixes and fillers. Three-letter
    words stay because they are often the distinctive part (XTO, OIL, SVB, UTI).
    An apostrophe inside a word is dropped, not a break: EDGAR's "Macy's" is the
    snapshots' MACYS."""
    text = re.sub(r"['’]", "", (name or "").upper())
    return {t for t in re.findall(r"[A-Z]{3,}", text) if t not in _STOP}


def names_agree(a: str, b: str) -> bool:
    """Two names agree when they share min(2, |A|, |B|) words, and at least one.
    One shared word is not enough when both names have two or more: Forest Oil is
    not Forest City (FST), Leap Wireless is not Ribbit LEAP (LEAP)."""
    ta, tb = name_tokens(a), name_tokens(b)
    need = min(2, len(ta), len(tb))
    return need >= 1 and len(ta & tb) >= need

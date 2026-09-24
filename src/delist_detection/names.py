"""Company-name tokens and agreement."""
from __future__ import annotations

import re

_STOP = {"CORP", "CORPORATION", "INC", "INCORPORATED", "COMPANY", "COS", "HOLDINGS", "HOLDING",
         "LTD", "LIMITED", "LLC", "PLC", "GROUP", "INTERNATIONAL", "INTL", "TRUST", "PARTNERS",
         "FUND", "BANK", "BANCORP", "BANCSHARES", "CLASS", "SERIES", "COMMON", "STOCK", "SHARES",
         "THE", "AND", "NEW"}


def _words(name: str) -> list[set[str]]:
    """Each word of the name as the set of its spellings (see `name_tokens`),
    minus legal suffixes and fillers; a word with no spelling left is dropped."""
    text = re.sub(r"’", "'", (name or "").upper())
    out = []
    for w in re.findall(r"[A-Z]+(?:'[A-Z]+)*", text):
        forms = {f for f in (w.replace("'", ""), *w.split("'")) if len(f) >= 3 and f not in _STOP}
        if forms:
            out.append(forms)
    return out


def name_tokens(name: str) -> set[str]:
    """Words of three or more letters, minus legal suffixes and fillers. Three-letter
    words stay because they are often the distinctive part (XTO, OIL, SVB, UTI).
    A word with an apostrophe gives both spellings the snapshots use: joined
    (MACYS, OREILLY, FRANKS) and split at the apostrophe (MACY; REILLY; FRANK),
    so "Macy's" meets MACYS and "O'Reilly" meets O REILLY."""
    return {f for forms in _words(name) for f in forms}


def names_agree(a: str, b: str) -> bool:
    """Two names agree when they share min(2, |A|, |B|) words, and at least one.
    One shared word is not enough when both names have two or more: Forest Oil is
    not Forest City (FST), Leap Wireless is not Ribbit LEAP (LEAP). A word counts
    once however many spellings it has ("Wendy's Co" is one word, WENDYS or
    WENDY), and a word is shared when one of its spellings is in the other name;
    the shared count is the smaller of the two sides' counts, so two spellings
    of one word on one side cannot match two words on the other."""
    wa, wb = _words(a), _words(b)
    ta = {f for forms in wa for f in forms}
    tb = {f for forms in wb for f in forms}
    need = min(2, len(wa), len(wb))
    shared = min(sum(1 for forms in wa if forms & tb), sum(1 for forms in wb if forms & ta))
    return need >= 1 and shared >= need

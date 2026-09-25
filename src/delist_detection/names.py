"""Company-name tokens and agreement."""
from __future__ import annotations

import re
from collections.abc import Iterable

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


# What a fails-to-deliver description adds after the company's name: the kind of
# share and how it is held ("COM STK", "ADR REP 2 ORD SHS", "SH BEN INT", "SER N").
_SECURITY_WORDS = {"COM", "STK", "SHS", "ORD", "ORDINARY", "ADR", "ADS", "SPON", "SPONSORED", "REP", "USD",
                   "NPV", "PAR", "BEN", "INT", "SBI", "VOTING", "NON", "SER", "DEP"}


def _company_part(description: str) -> str:
    """A fails-to-deliver description without its security tail: the par value
    or the state of incorporation follows a ';' or '(' ("APPLE INC;COM NPV",
    "CYTTA CORP NEW COM STK (NV)")."""
    return re.split(r"[;(]", (description or "").upper(), maxsplit=1)[0]


def _company_words(text: str) -> list[set[str]]:
    """`_words` minus security words, each word also without a plural S
    (HANESBRANDS and HANESBRAND are one word)."""
    out = []
    for forms in _words(text):
        forms = forms - _SECURITY_WORDS
        if forms:
            out.append(forms | {f[:-1] for f in forms if len(f) > 3 and f.endswith("S")})
    return out


def _abbreviates(short: str, word: str) -> bool:
    """`short` is `word` written short: no longer, the same first letter, and its
    letters in `word` in order (GEN for GENERAL, MATLS for MATERIALS, APTAGROUP
    for APTARGROUP)."""
    if len(short) > len(word) or short[0] != word[0]:
        return False
    letters = iter(word)
    return all(ch in letters for ch in short)


def _joined(text: str) -> set[str]:
    """Two or three consecutive words of `text` written as one (MC DERMOTT ->
    MCDERMOTT, MARKET AXESS -> MARKETAXESS, BORG WARNER -> BORGWARNER)."""
    raw = re.findall(r"[A-Z]+", (text or "").upper())
    return {"".join(raw[i:i + n]) for n in (2, 3) for i in range(len(raw) - n + 1)}


def description_matches(description: str, names: Iterable[str]) -> bool:
    """Whether a fails-to-deliver row's `description` can name the company known
    by one of `names` (its observed names and the issuer's EDGAR names, current
    and former). SEC cuts descriptions at 30 characters, abbreviates freely and
    keeps an old name for years after a rename, so this is much looser than
    `names_agree`: it only has to tell another company on the same ticker
    (Cervecerias Unidas on Clear Channel's CCU, Stantec on Station Casinos' STN)
    from the company itself.

    A description matches when, leaving out its security words (COM STK, ADR,
    ORD SHS, ...), one of its words is a word of a name (a plural S aside:
    HANESBRANDS, HANESBRAND), or writes a name's word
    short (GEN ELEC for GENERAL ELECTRIC, MATLS for MATERIALS), or two or three
    of its words run together give a name's word, or the other way round
    (MC DERMOTT, BORG WARNER). With nothing to compare (no word left on one
    side: "3M COMPANY", "HP INC COM STK") it matches."""
    names = [n for n in names if n]
    d_words = _company_words(_company_part(description))
    n_words = [w for n in names for w in _company_words(n)]
    if not d_words or not n_words:
        return True
    d_forms = {f for w in d_words for f in w}
    n_forms = {f for w in n_words for f in w}
    if d_forms & n_forms:
        return True
    if any(_abbreviates(d, n) for d in d_forms for n in n_forms):
        return True
    return bool(_joined(_company_part(description)) & n_forms
                or any(_joined(n) & d_forms for n in names))

"""Issuer-name tokens and agreement."""
from __future__ import annotations

import re
from collections.abc import Iterable

_STOP = {"CORP", "CORPORATION", "INC", "INCORPORATED", "COMPANY", "COMPANIES", "COS", "HOLDINGS", "HOLDING",
         "LTD", "LIMITED", "LLC", "PLC", "GROUP", "INTERNATIONAL", "INTL", "TRUST", "PARTNERS",
         "FUND", "BANK", "BANCORP", "BANCSHARES", "CLASS", "SERIES", "COMMON", "STOCK", "SHARES",
         "THE", "AND", "NEW"}


def _words(name: str) -> list[set[str]]:
    """Each word of the name as the set of its spellings (see `name_tokens`),
    minus legal suffixes and fillers; a word with no spelling left is dropped.
    Letters and digits run together are one word, also spelled by each run of four
    letters or more in it (L3HARRIS meets HARRIS; SKY440 is never SKY, FB-009); a
    run of digits alone is no word."""
    text = re.sub(r"’", "'", (name or "").upper())
    out = []
    for w in re.findall(r"[A-Z0-9]*[A-Z][A-Z0-9]*(?:'[A-Z0-9]*[A-Z][A-Z0-9]*)*", text):
        spellings = (w.replace("'", ""), *w.split("'"))
        if re.search(r"\d", w):
            spellings += tuple(p for p in re.findall(r"[A-Z]{4,}", w))
        forms = {f for f in spellings if len(f) >= 3 and f not in _STOP}
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
    of one word on one side cannot match two words on the other.

    A word is shared in the ways `description_names` reads one (`_word_matches`): the
    same word, a plural S aside, written short on either side (MATLS for
    MATERIALS, WASHIN for WASHINGTON, a vendor's PPTYS for PROPERTIES), or run
    together (DU PONT and DUPONT), because the caller's snapshots abbreviate and
    truncate (FB-006). A word written short is never the only word shared: APPLE
    is not APPLEBEES. A name with no word of three letters (2U INC, 3M CO) agrees
    with one that has none either, when their remaining characters are the same."""
    wa, wb = _spelled(_words(a)), _spelled(_words(b))
    if not wa or not wb:
        return not wa and not wb and _run(a) != "" and _run(a) == _run(b)
    (exact_a, short_a), (exact_b, short_b) = (_word_matches(wa, wb, a, b, either=True, shortest=4),
                                              _word_matches(wb, wa, b, a, either=True, shortest=4))
    need = min(2, len(wa), len(wb))
    return min(exact_a, exact_b) >= 1 and min(exact_a + short_a, exact_b + short_b) >= need


def has_name(name: str) -> bool:
    """Whether the name can agree with another (`names_agree`): it has a word of three letters or more, or, with
    none (2U INC, 3M CO, HP INC), letters and digits left once legal suffixes and fillers are out."""
    return bool(_words(name)) or _run(name) != ""


def same_letters(a: str, b: str) -> bool:
    """Two names written with the same letters and digits, in any order, once legal suffixes and fillers are out:
    the same name with its words run together, split or reordered (E I DU PONT DE NEMOURS and DUPONT E I DE NEMOURS &
    CO), which no character-prefix search of a name index reaches. Stricter than `names_agree`: nothing may differ."""
    ra, rb = _run(a), _run(b)
    return ra != "" and sorted(ra) == sorted(rb)


def _run(name: str) -> str:
    """A name's letters and digits run together, legal suffixes and fillers out (2U INC and 2U, Inc. are 2U)."""
    parts = re.findall(r"[A-Z0-9]+", re.sub(r"['’]", "", (name or "").upper()))
    return "".join(p for p in parts if p not in _STOP and p != "CO")


# The vendor's abbreviations that are not a word's letters in order (PPTYS has a Y PROPERTIES lacks).
_VENDOR_ABBREVIATIONS = {"PPTY": "PROPERTY", "PPTYS": "PROPERTIES", "PRPTY": "PROPERTY", "PRPTYS": "PROPERTIES"}


def _spelled(words: list[set[str]]) -> list[set[str]]:
    """Each word's spellings, and also without a plural S (HANESBRANDS and HANESBRAND are one word) and, for a
    vendor's abbreviation, the word it stands for."""
    out = []
    for forms in words:
        forms = forms | {_VENDOR_ABBREVIATIONS[f] for f in forms if f in _VENDOR_ABBREVIATIONS}
        out.append(forms | {f[:-1] for f in forms if len(f) > 3 and f.endswith("S")})
    return out


def _word_matches(words: list[set[str]], others: list[set[str]], text: str, other_text: str, *,
                  either: bool, shortest: int = 1) -> tuple[int, int]:
    """How many of `words` (spelled by `_spelled`) are words of `others`, as (same word or run together, written
    short): the same spelling; written short, the word's letters in order from its first letter, as `others`' word
    (`either`: or `others`' word as this one; `shortest`: the short word has at least that many letters); the
    exact count has one more when two or three consecutive words of either text run together to make a word of
    the other that is not a word they share already (MC DERMOTT, DU PONT; not Macy's Foods and Macys Retail)."""
    forms = {f for w in others for f in w}
    own = {f for w in words for f in w}
    exact = short = 0
    for w in words:
        if w & forms:
            exact += 1
        elif any((len(d) >= shortest and _abbreviates(d, n)) or (either and len(n) >= shortest and _abbreviates(n, d))
                 for d in w for n in forms):
            short += 1
    if (_joined(text) & forms) - own or (_joined(other_text) & own) - forms:
        exact += 1                                          # MC DERMOTT and MCDERMOTT, one way or the other
    return exact, short


# What a fails-to-deliver description adds after the issuer's name: the kind of
# share and how it is held ("COM STK", "ADR REP 2 ORD SHS", "SH BEN INT", "SER N").
_SECURITY_WORDS = {"COM", "STK", "SHS", "ORD", "ORDINARY", "ADR", "ADS", "SPON", "SPONSORED", "REP", "USD",
                   "NPV", "PAR", "BEN", "INT", "SBI", "VOTING", "NON", "SER", "DEP"}


def _name_part(description: str) -> str:
    """A fails-to-deliver description without its security tail: the par value
    or the state of incorporation follows a ';' or '(' ("APPLE INC;COM NPV",
    "CYTTA CORP NEW COM STK (NV)")."""
    return re.split(r"[;(]", (description or "").upper(), maxsplit=1)[0]


def _issuer_words(text: str) -> list[set[str]]:
    """`_words` minus security words, each word also without a plural S
    (HANESBRANDS and HANESBRAND are one word)."""
    return _spelled([forms - _SECURITY_WORDS for forms in _words(text) if forms - _SECURITY_WORDS])


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


def description_names(description: str, name: str) -> bool:
    """Whether a fails-to-deliver `description` names the company `name` word by
    word: as many of its issuer words as the shorter side has, up to two, each
    matching a word of `name` the ways `description_matches` matches one (the
    same word, a plural S aside, written short, or run together). Stricter than
    `description_matches`, where one shared word is enough: CITIZENS
    COMMUNICATIONS does not name CLEAR CHANNEL COMMUNICTNS, while CORN PRODUCTS
    INTERNATIONAL names CORN PRODUCTS INT'L. With nothing to compare it names
    nothing."""
    d_words = _without_holding(_issuer_words(_name_part(description)))
    n_words = _without_holding(_issuer_words(name))
    if not d_words or not n_words:
        return False
    exact, short = _word_matches(d_words, n_words, _name_part(description), name, either=False)
    return exact + short >= min(2, len(d_words), len(n_words))


# The word a holding company's name adds to its operating company's: ExxonMobil Holdings is Exxon Mobil's holding
# company from July 2026 and keeps its name (FB-004). It names no company, so `description_names` leaves it out of
# the words it compares, when another word is left on that side.
_HOLDING_WORDS = {"HOLDINGS", "HOLDING", "HLDGS", "HLDG", "HOLDCO"}


def _without_holding(words: list[set[str]]) -> list[set[str]]:
    kept = [w for w in words if not w & _HOLDING_WORDS]
    return kept or words


def names_an_issuer(description: str) -> bool:
    """Whether a fails-to-deliver description leaves a word to compare once its
    security words go (2U INC COM STK and F5,INC. COMMON STOCK leave none)."""
    return bool(_issuer_words(_name_part(description)))


def description_matches(description: str, names: Iterable[str], *, empty: bool = True) -> bool:
    """Whether a fails-to-deliver row's `description` can name the issuer known
    by one of `names` (its observed names and the issuer's EDGAR names, current
    and former). SEC cuts descriptions at 30 characters, abbreviates freely and
    keeps an old name for years after a rename, so this is much looser than
    `names_agree`: it only has to tell another issuer on the same ticker
    (Cervecerias Unidas on Clear Channel's CCU, Stantec on Station Casinos' STN)
    from the issuer itself.

    A description matches when, leaving out its security words (COM STK, ADR,
    ORD SHS, ...), one of its words is a word of a name (a plural S aside:
    HANESBRANDS, HANESBRAND), or writes a name's word
    short (GEN ELEC for GENERAL ELECTRIC, MATLS for MATERIALS), or two or three
    of its words run together give a name's word, or the other way round
    (MC DERMOTT, BORG WARNER). With nothing to compare (no word left on one
    side: "3M COMPANY", "HP INC COM STK") the answer is `empty`: a match when
    telling issuers apart (the default), none when the description must name
    the issuer (the resolver's second pass)."""
    names = [n for n in names if n]
    d_words = _issuer_words(_name_part(description))
    n_words = [w for n in names for w in _issuer_words(n)]
    if not d_words or not n_words:
        return empty
    d_forms = {f for w in d_words for f in w}
    n_forms = {f for w in n_words for f in w}
    if d_forms & n_forms:
        return True
    if any(_abbreviates(d, n) for d in d_forms for n in n_forms):
        return True
    return bool(_joined(_name_part(description)) & n_forms
                or any(_joined(n) & d_forms for n in names))

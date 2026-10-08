"""How the library spells a security's identifiers, and how it reads a share class from text (CONTEXT.md: a security
is one share class).

A leaf: it imports nothing of the package, so the observations, the identity rules, the fails index and the data
clients spell a ticker one way, and every module reads a class through one named reader per kind of text.

Ticker spellings. The output tables spell a ticker as `normalize_ticker` gives it: upper case, a "-" between a base
and its class ("BRK-B").
- `normalize_ticker`: a caller's or a filing's spelling into the tables' ("brk.b", "BRK B" and "BF/A" are BRK-B and
  BF-A).
- `regular_way`: the line a when-issued ticker trades ahead of (EHAB-WI is EHAB).
- `bloomberg_ticker`: OpenFIGI's spelling (BF/A).
- `bare_ticker`: the fails files' spelling, with no separator (BRKB).
- `class_suffix`: a one-letter class ticker's base and letter (UAC-C: UAC and C).

The placeholder sec_id: `placeholder_id` (`CIK<cik>-<CLASS>`, decision 7) and `is_placeholder`.

The share class. A class code is COMMON, CLASS X or SERIES X (`SHARE_CLASS_CODE`, what `share_class_from_name`
gives); `class_letter` reads its letter. The readers of a class from text, one per kind of text, each with its own
rule (their docstrings give the rule and a real example):
- a security's name, observed, EDGAR's or OpenFIGI's: `share_class_from_name`, `name_class_letter`, and
  `strip_class_words` (the name without its class words);
- the class letter an OpenFIGI name ends with, after a dash and spaces: `figi_class_letter`;
- one fails-to-deliver description: `description_class_letter`; a CUSIP's descriptions together, by their own
  rule: `descriptions_class_letter`;
- the share class an LLM answer names: `answer_class_letter`;
- a filing's prose, an 8-K's sentence or an LLM answer's quote: `prose_class_letters`;
- the words that set a class apart in a name: `CLASS_MODIFIERS`, read with the letter by `class_of`.
Where two readers of one kind of text keep two rules, merging them would change what the replay reads (the step 13
decision log gives the inputs). A Form 25's class text is read by `form25` (segment by segment, past attached rights
and preferred clauses), which turns each class it names into a letter with `class_letter`.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

# --- ticker spellings -----------------------------------------------------------------------------------------------


def normalize_ticker(raw: str) -> str:
    """The tables' spelling of a ticker: upper case, each run of ".", "/" and spaces one "-", none at either end
    (" brk.b " and "BRK B" are BRK-B, "BF/A" is BF-A)."""
    return re.sub(r"[./\s]+", "-", (raw or "").strip().upper()).strip("-")


_WHEN_ISSUED = re.compile(r"-W-?I$")       # "EHAB WI", "EHAB.WI", "EHAB-WI", "EHAB/WI", "EHAB W/I"


def regular_way(ticker: str) -> str:
    """The regular-way line a when-issued ticker trades ahead of: "EHAB-WI" (or "EHAB WI", "EHAB.WI", "EHAB W/I")
    is EHAB, which the shares trade under once they are issued (Enhabit's 2022 spin-off). Any other ticker,
    normalized, is its own."""
    t = normalize_ticker(ticker)
    stripped = _WHEN_ISSUED.sub("", t)
    return stripped or t


def bloomberg_ticker(ticker: str) -> str:
    """OpenFIGI's spelling of a ticker, for a TICKER mapping job: the class after a "/" ("BF-A" is BF/A)."""
    return normalize_ticker(ticker).replace("-", "/")


def bare_ticker(ticker: str) -> str:
    """The fails files' spelling of a normalized ticker: no separator ("BRK-B" is BRKB, "BF-B" BFB). A post-split
    "...D" or a new CUSIP's "...ZZZZ" symbol is this spelling with the letters appended (YRCWD, NYCBZZZZ)."""
    return ticker.replace("-", "")


_CLASS_SUFFIX = re.compile(r"([A-Z]+)-([A-Z])")


def class_suffix(ticker: str) -> tuple[str, str] | None:
    """A one-letter class ticker's base and letter: "UAC-C" (a snapshot's spelling of Under Armour's class C, which
    the fails files list whole as UAC) is ("UAC", "C"), "BRK-B" ("BRK", "B"); None for any other ticker ("GOOGL",
    "EHAB-WI")."""
    m = _CLASS_SUFFIX.fullmatch(ticker)
    return (m.group(1), m.group(2)) if m else None


# --- the placeholder sec_id -----------------------------------------------------------------------------------------

SHARE_CLASS_CODE = re.compile(r"COMMON|CLASS [A-Z]|SERIES [A-Z0-9]")     # share_class_from_name's values


def placeholder_id(cik: int, share_class: str | None) -> str:
    """`CIK<cik>-<CLASS>` from a class code (decision 7): COMMON, CLASS X or SERIES X, as `share_class_from_name`
    gives it ("CIK14693-CLASS-A"; no class is COMMON). Free class text could give one class two IDs, so anything
    else raises ValueError."""
    code = (share_class or "COMMON").upper().strip()
    if not SHARE_CLASS_CODE.fullmatch(code):
        raise ValueError(f"placeholder_id: {share_class!r} is not a class code")
    return f"CIK{int(cik)}-{code.replace(' ', '-')}"


def is_placeholder(sec_id: str) -> bool:
    """Whether a sec_id is a placeholder (`placeholder_id`'s "CIK1-COMMON"), not a FIGI ("BBG000FJLFX8")."""
    return sec_id.startswith("CIK")


# --- the share class ------------------------------------------------------------------------------------------------


def share_class_from_name(name: str | None) -> str:
    """The class code a security's name states, observed, EDGAR's or OpenFIGI's: the first "CL X" or "CLASS X"
    ("ALPHABET INC-CL C", "META PLATFORMS INC-CLASS A"), else the first "SER X" or "SERIES X" ("LIBERTY
    BROADBAND-SER C"), else a "-X" it ends with ("DISCOVERY INC-A"); COMMON for a name that states none ("CLOROX
    CO")."""
    s = (name or "").upper().strip()
    m = re.search(r"\bCL(?:ASS)?\s*-?\s*([A-Z])\b", s)
    if m:
        return f"CLASS {m.group(1)}"
    m = re.search(r"\bSER(?:IES)?\s*-?\s*([A-Z0-9])\b", s)
    if m:
        return f"SERIES {m.group(1)}"
    m = re.search(r"-([A-Z])$", s)
    if m:
        return f"CLASS {m.group(1)}"
    return "COMMON"


def class_letter(share_class: str | None) -> str | None:
    """The letter of a class code ("CLASS A" is A, "SERIES C" C), None for COMMON or any other text."""
    m = re.fullmatch(r"(?:CLASS|SERIES)\s+([A-Z0-9])", (share_class or "").upper().strip())
    return m.group(1) if m else None


def name_class_letter(name: str | None) -> str | None:
    """The class letter a security's name states (`share_class_from_name`): "GOOGLE INC CLASS C" is C, "LIBERTY
    MEDIA CORP SERIES A" and "DISCOVERY INC-A" A; None for a name that states none ("GOOGLE INC"), which is unknown,
    not a class of its own."""
    return class_letter(share_class_from_name(name))


_CLASS_WORDS = re.compile(r"\b(?:CL(?:ASS)?|SER(?:IES)?)\s*-?\s*[A-Z0-9]\b|-[A-Z]$", re.I)


def strip_class_words(name: str | None) -> str:
    """A security's name without the class phrases it states, in any case, as a filing would print its issuer
    ("GOOGLE INC CLASS A", "ALPHABET INC-CL C" and "Liberty Media Corp Series A" are "GOOGLE INC", "ALPHABET INC"
    and "Liberty Media Corp"): each phrase becomes a space, spaces fold to one, and no space or "-" is left at
    either end."""
    return re.sub(r"\s+", " ", _CLASS_WORDS.sub(" ", name or "")).strip(" -")


_FIGI_CLASS = re.compile(r"(?:-\s*|\bCL(?:ASS)?\s*-?\s*)([A-Z])\s*$")


def figi_class_letter(name: str | None) -> str | None:
    """The class letter an OpenFIGI (Bloomberg) security name ends with, after a "-" or "CL"/"CLASS" and any spaces:
    "MSG NETWORKS INC- A", "STARZ - A", "GRAHAM HOLDINGS CO-CLASS B" (None: none, "HUBBELL INC")."""
    m = _FIGI_CLASS.search((name or "").upper().strip())
    return m.group(1) if m else None


_DESCRIPTION_CLASS = re.compile(r"\bCL(?:ASS)?\s*-?\s*([A-Z])\b")


def description_class_letter(description: str | None) -> str | None:
    """The class letter a fails-to-deliver description names, its first "CL X" or "CLASS X" ("UNDER ARMOUR INC CL
    C" is C); None when it names none."""
    m = _DESCRIPTION_CLASS.search((description or "").upper())
    return m.group(1) if m else None


_DESCRIPTIONS_CLASS = re.compile(r"\b(?:CL|CLASS|SER|SERIES)\s+([A-Z])\b")


def descriptions_class_letter(descriptions: Iterable[str]) -> str | None:
    """The one class letter a CUSIP's fails-to-deliver descriptions name, by "CL", "CLASS", "SER" or "SERIES" and a
    space ("SUNPOWER CORP CL A", "LIBERTY INTERACTIVE CORP SER A"); None when they name none, or more than one ("X
    CORP CLASS A" beside "X CORP CL B")."""
    letters = {m.group(1) for d in descriptions for m in _DESCRIPTIONS_CLASS.finditer((d or "").upper())}
    return letters.pop() if len(letters) == 1 else None


_ANSWER_CLASS = re.compile(r"(?i)\s*(?:(?:class|series)\s+)?([A-Z0-9])(?:\s+(?:common|ordinary)\b.*)?\s*")


def answer_class_letter(text: str | None) -> str:
    """The letter of the share class an LLM answer names, the whole answer one class: "B", "Class B", "Series C
    common" (CAA 2018's Lennar "Class B" leg, LEN-B); "" for any other answer ("preferred unit", "common")."""
    m = _ANSWER_CLASS.fullmatch(text or "")
    return m.group(1).upper() if m else ""


_PROSE_CLASS = re.compile(r"\b(?:Class|Series)\s+([A-Z])(?![\w-])")


def prose_class_letters(text: str | None) -> list[str]:
    """The class letters a filing's prose names, in order: each "Class X" or "Series X", capitalized as a filing
    writes them, whose letter ends the word ("each share of Class A common stock of Viacom ... into 0.59625 shares of
    ViacomCBS Class A Common Stock": A, A; "Series A-1" names none)."""
    return _PROSE_CLASS.findall(text or "")


# the words that set a class apart in its name ("COMCAST SPECIAL CORP CLASS A")
CLASS_MODIFIERS = ("SPECIAL", "NON-VOTING", "LIMITED VOTING")


def class_of(share_class: str | None, name: str | None) -> tuple[str, tuple[str, ...]]:
    """The class a security's statements must name: its class code's letter ("" for a plain common) and the
    `CLASS_MODIFIERS` its name carries ("CLASS A" and "COMCAST SPECIAL CORP CLASS A" are ("A", ("SPECIAL",)))."""
    up = (name or "").upper()
    return class_letter(share_class) or "", tuple(w for w in CLASS_MODIFIERS if w in up)

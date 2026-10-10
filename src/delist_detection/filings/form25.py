"""Form 25: the SEC notice that a class of securities is removed from an exchange.

The XML primary document names the exchange, the issuer, the class (free text)
and the rule; the exchange's EX-99.25 notice often dates the suspension. A Form
25 names no ticker or CUSIP, so it is matched to one security by its class text.
"""
from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..sources.edgar import EdgarSubmission
from ..sources.html_text import strip_html
from ..vocabulary.identifiers import class_letter
from ..vocabulary.names import name_tokens
from ..vocabulary.trading_calendar import previous_trading_day

FORM25_FORMS = frozenset({"25", "25-NSE", "25/A", "25-NSE/A"})
MAJOR_EXCHANGES = frozenset({"NYSE", "NYSE AMERICAN", "NASDAQ", "NYSE ARCA", "CBOE BZX"})
REGIONAL_EXCHANGES = frozenset({"CHICAGO", "NSX", "PACIFIC", "BOSTON", "PHLX"})
ISSUER_FORM25_FORMS = frozenset({"25", "25/A"})      # filed by the issuer, not by the exchange (25-NSE)

# Order matters: the specific names before the bare NYSE / NASDAQ patterns.
_EXCHANGES: list[tuple[str, str]] = [
    ("NYSE AMERICAN", r"NYSE\s*AMERICAN|NYSE\s*MKT|NYSE\s*AMEX|AMERICAN STOCK EXCHANGE|\bAMEX\b"),
    ("NYSE ARCA", r"NYSE\s*ARCA|ARCHIPELAGO"),
    ("CHICAGO", r"CHICAGO STOCK EXCHANGE|NYSE\s*CHICAGO"),
    ("NSX", r"NATIONAL STOCK EXCHANGE|NYSE\s*NATIONAL"),
    ("PACIFIC", r"PACIFIC (?:STOCK )?EXCHANGE"),
    ("BOSTON", r"BOSTON STOCK EXCHANGE|NASDAQ\s*(?:OMX\s*)?BX"),
    ("PHLX", r"PHILADELPHIA STOCK EXCHANGE|NASDAQ\s*(?:OMX\s*)?PHLX|\bPHLX\b"),
    # EDGAR's submissions write a bare "CBOE" for Cboe Global Markets, whose
    # shares list on Cboe BZX; an entity name such as "Cboe Exchange, Inc." is not it.
    ("CBOE BZX", r"CBOE\s*BZX|\bBATS\b|^\s*CBOE\s*$"),
    ("NASDAQ", r"NASDAQ"),
    ("NYSE", r"NEW YORK STOCK EXCHANGE|\bNYSE\b"),
]
_NYSE_BARE = r"NEW YORK STOCK EXCHANGE|\bNYSE\b(?!\s*(?:ARCA|AMERICAN|MKT|AMEX|CHICAGO|NATIONAL))"
_NASDAQ_BARE = r"NASDAQ(?!\s*(?:OMX\s*)?(?:BX|PHLX))"

_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
_DATE = rf"((?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})"


def exchange_label(text: str) -> str:
    for label, pat in _EXCHANGES:
        if re.search(pat, text or "", re.I):
            return label
    return ""


def exchanges_named(text: str) -> set[str]:
    t = text or ""
    found = {label for label, pat in _EXCHANGES if re.search(pat, t, re.I)}
    if "NYSE" in found and not re.search(_NYSE_BARE, t, re.I):
        found.discard("NYSE")
    if "NASDAQ" in found and not re.search(_NASDAQ_BARE, t, re.I):
        found.discard("NASDAQ")
    return found


@dataclass(frozen=True)
class Form25:
    accession: str
    form: str
    filing_date: str
    exchange: str
    class_text: str
    rule: str
    notice_text: str
    # The class a "This Notification relates solely to ..." sentence names ("Preferred Share Purchase Rights": BMET
    # 2006), else "".
    solely: str = ""


def is_involuntary(f25: Form25) -> bool:
    """An exchange's removal under rule 12d2-2(b) (a listing deficiency, a price, a market value), not a
    voluntary withdrawal or a merger's (a) filing: the class went to no other exchange."""
    return "(b)" in (f25.rule or "")


def _tag(raw: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", raw, re.S | re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def _notice(raw: str) -> str:
    m = re.search(r"<TYPE>EX-99\.25(.*?)(?=<TYPE>|</DOCUMENT>|\Z)", raw, re.S | re.I)
    return strip_html(m.group(1)) if m else ""


_CLASS_CAPTION = r"\(\s*Description of (?:the )?class(?:es)? of securit(?:y|ies)\s*\)"


def _text_class(text: str) -> str:
    """The class of a text (issuer-filed, HTML) Form 25: the words right above
    its "(Description of class of securities)" caption, after the "(Address
    ... executive offices)" caption before them. An older layout states it
    after a "Title of class of securities:" label. Never the rule checkboxes
    ("☐ 17 CFR 240.12d2-2(a)(1)") that follow "...strike the class of
    securities from listing and registration:"."""
    for pat in (rf"offices\s*\)\s*(.{{3,400}}?)\s*{_CLASS_CAPTION}",
                rf"\)\s*([^()]{{3,400}}?)\s*{_CLASS_CAPTION}"):
        m = re.search(pat, text, re.I | re.S)
        if m:
            return m.group(1).strip()
    m = re.search(r"(?:class|title) of (?:the )?securit(?:y|ies)[^:]{0,40}:\s*(.{3,120}?)(?:\s{2,}|\.|$)", text, re.I)
    if m and not re.search(r"17\s*CFR", m.group(1), re.I):
        return m.group(1).strip()
    return ""


_SOLELY = re.compile(r"relates\s+solely\s+to\s+(?:the\s+)?(?:withdrawal\s+from\s+listing\s+of\s+(?:the\s+|our\s+)?)?"
                     r"(.{3,80}?)\s+from", re.I)


def _solely(raw: str) -> str:
    """The class a "This Notification relates solely to the withdrawal from listing of <class> from ..." sentence
    names, anywhere in the filing, else ""."""
    m = _SOLELY.search(re.sub(r"\s+", " ", strip_html(raw)))
    return m.group(1).strip() if m else ""


def parse_form25(raw: str, *, accession: str, form: str, filing_date: str) -> Form25:
    exch_block = re.search(r"<exchange>(.*?)</exchange>", raw, re.S | re.I)
    exch_name = _tag(exch_block.group(1), "entityName") if exch_block else ""
    class_text = _tag(raw, "descriptionClassSecurity")
    rule = _tag(raw, "ruleProvision")
    if not exch_name:                         # a text Form 25 without the XML document
        text = strip_html(raw)
        exch_name = exchange_label(text[:4000])
        if not class_text:
            class_text = _text_class(text)
    return Form25(accession, form, filing_date, exchange_label(exch_name) or exch_name.upper(),
                  class_text, rule, _notice(raw), _solely(raw))


def list_form25(filings: Iterable[EdgarSubmission]) -> list[EdgarSubmission]:
    return sorted((f for f in filings if f.form in FORM25_FORMS), key=lambda f: (f.filing_date, f.accession))


# "Common Stock Purchase Warrants" / "Redeemable warrants included as part of the
# units, each exercisable for..." are warrants even though the text also carries
# COMMON or UNITS: checked first, against just the segment before the first comma
# (or the whole text, for the two named lead-ins), so a warrant named after the
# common isn't misread as the common itself.
_WARRANT_TAIL = re.compile(r"WARRANTS?$")
_WARRANT_LEAD = re.compile(r"^(?:COMMON STOCK PURCHASE WARRANTS?|REDEEMABLE WARRANTS?)")

# Units that are themselves the equity of an MLP, LLC or royalty trust (not a
# SPAC-style unit bundling a share + a warrant) are common. Checked before the
# generic unit rule.
_OWNERSHIP_UNIT_START = re.compile(r"^(?:CLASS [A-Z] )?(?:COMMON UNITS|DEPOSITARY UNITS|TRUST UNITS"
                                   r"|UNITS REPRESENTING)")
_OWNERSHIP_UNIT_INTEREST = re.compile(r"UNITS?\s+REPRESENTING.{0,80}?(?:PARTNER|LIMITED LIABILITY COMPANY|LLC)")


def class_kind(class_text: str) -> str:
    s = (class_text or "").upper().strip()
    if not s:
        return "other"
    before_comma = s.split(",", 1)[0].rstrip()
    if _WARRANT_TAIL.search(before_comma) or _WARRANT_LEAD.match(s):
        return "warrant"
    if re.match(r"^\W*(?:CLASS [A-Z] |SERIES [A-Z] )?(?:COMMON|ORDINARY)", s):
        return "common"
    if re.search(r"\bPURCHASE RIGHTS?$", before_comma) or re.match(r"^\W*RIGHTS? TO PURCHASE\b", s):
        # a rights plan names the preferred its rights buy; the class is the rights
        return "right"
    if re.search(r"DEPOSITARY SHARES?,? EACH REPRESENTING", s):
        # A depositary-share text is preferred only when it names a preferred
        # or preference security ("... each representing one ordinary share"
        # is common).
        return "preferred" if re.search(r"PREFERRED|PREFERENCE", s) else "common"
    if re.search(r"PREFERRED|PREFERENCE|CAPITAL SECURIT|TRUST PREFERRED|TRUST CERTIFICATE", s):
        return "preferred"
    if _OWNERSHIP_UNIT_START.match(s) or _OWNERSHIP_UNIT_INTEREST.search(s):
        return "common"
    if re.search(r"\bUNITS?\b|PURCHASE CONTRACTS?\b", s):
        return "unit"
    if re.search(r"\bWARRANTS?\b", s):
        return "warrant"
    if re.search(r"^\W*(?:[A-Z ]+ )?RIGHTS?\b", s) and "COMMON" not in s:
        return "right"
    if re.search(r"\bETF\b|\bETN\b|EXCHANGE[- ]TRADED|\bFUND\b|INDEX SHARES", s):
        return "fund"
    if re.search(r"\bNOTES?\b|DEBENTURES?|\bBONDS?\b|\bDUE\s+\d{4}\b", s):
        return "debt"
    if re.search(r"COMMON|ORDINARY|CLASS [A-Z]\b|SERIES [A-Z]\b|SHARES OF BENEFICIAL INTEREST|CAPITAL STOCK"
                 r"|AMERICAN DEPOSITARY|\bADS\b|\bSTOCK\b|\bSHARES\b", s):
        return "common"
    return "other"


# A class letter is only real when it names the security's own class, not a
# security attached to it (a rights-plan clause naming its own "Series A
# Junior Participating Preferred Stock", or a warrant on a different class).
# Split the whole text into segments at each comma, semicolon, "(", "&",
# " AND " or " WITH ", drop any segment that names an attached security
# (RIGHTS or WARRANT), and — only when the class itself is common — also drop
# a segment naming the preferred/preference security the rights are usually
# attached to ("Class A Common Stock and associated Series B Preferred Stock
# Purchase Rights" must not read as Series B). A preferred security keeps its
# own "Series C"/"Series F" segment ("Preferred Stock, Series C"; "5.750% ...
# Preference Share, Series F") since there's no other class it could belong
# to. A Liberty-style tracking stock ("Series A Liberty SiriusXM Common
# Stock") still carries its class as a series in its own (kept) segment.
_SEGMENT_END = re.compile(r"[,;(&]| AND | WITH ")
_ATTACHED_SECURITY = re.compile(r"RIGHTS|WARRANT")
_PREFERRED_WORD = re.compile(r"PREFERRED|PREFERENCE")
_CLASS_WORD = re.compile(r"\bCLASS\s+([A-Z])\b")
_SERIES_WORD = re.compile(r"\bSERIES\s+([A-Z])\b")


def _kept_segments(class_text: str) -> list[str]:
    s = (class_text or "").upper()
    is_common = class_kind(class_text) == "common"
    kept = []
    for seg in _SEGMENT_END.split(s):
        if not seg or _ATTACHED_SECURITY.search(seg):
            continue
        if is_common and _PREFERRED_WORD.search(seg):
            continue
        kept.append(seg)
    return kept


def _lettered_segments(class_text: str) -> list[tuple[str, str]]:
    """(label, segment) for each kept segment naming a class: its CLASS letter,
    or its SERIES letter when no segment names a CLASS."""
    kept = _kept_segments(class_text)
    pat, word = ((_CLASS_WORD, "CLASS") if any(_CLASS_WORD.search(seg) for seg in kept)
                 else (_SERIES_WORD, "SERIES"))
    out = []
    for seg in kept:
        m = pat.search(seg)
        if m:
            out.append((f"{word} {m.group(1)}", seg))
    return out


@dataclass(frozen=True)
class SecurityRef:
    sec_id: str
    share_class: str
    kind: str
    name: str = ""
    # The class letter the security's own CUSIP fails descriptions name ("SUNPOWER CORP CL A"), for a share
    # class without a letter of its own (`identifiers.descriptions_class_letter`); None when they name none, or
    # two.
    letter_hint: str | None = None


def _named_by(segment: str, hits: Sequence[SecurityRef]) -> list[SecurityRef]:
    """The hits whose own name words (those not shared by every hit) appear in
    the Form 25's segment: Liberty Media's Series A Liberty Live and Series A
    Formula One share the issuer and the letter, and only the group name tells
    them apart."""
    toks = [name_tokens(r.name) for r in hits]
    common = set.intersection(*toks) if toks else set()
    words = name_tokens(segment)
    return [r for r, t in zip(hits, toks) if (t - common) & words]


def _class_matches(f25: Form25, same: Sequence[SecurityRef]
                   ) -> tuple[list[str], list[str], bool, set[str]]:
    """Per class the text names: its one sibling of that letter (a tie of one
    letter broken by the class's own words). Returns the matched sec_ids, their
    letters, whether a name broke a tie, and the unmatched siblings the text may
    be about. A class that picks out no single sibling of its letter leaves
    tied: the siblings whose class has no letter and whose own name words it
    names (Liberty SiriusXM's letter-less Series C line), else the siblings of
    its letter it could not tell apart (a generic "Class B Common Stock" with a
    FIGI line and a placeholder of the same stock)."""
    matched: list[str] = []
    letters: list[str] = []
    by_name = False
    tied: set[str] = set()
    for label, seg in _lettered_segments(f25.class_text):
        letter = class_letter(label)
        hits = [r for r in same if class_letter(r.share_class) == letter]
        if not hits:
            # R2: no sibling's class carries the letter; a letterless one whose own CUSIP's fails descriptions
            # name it does (SunPower's "Class A & Class B" 25-NSE, 2011: the class A placeholder, "CL A")
            hits = [r for r in same if class_letter(r.share_class) is None and r.letter_hint == letter]
        named = len(hits) > 1
        picked = _named_by(seg, hits) if named else hits
        if len(picked) == 1:
            if picked[0].sec_id not in matched:
                matched.append(picked[0].sec_id)
                letters.append(letter)
                by_name = by_name or named
            continue
        letterless = [r for r in _named_by(seg, same) if class_letter(r.share_class) is None]
        if letterless:
            tied |= {r.sec_id for r in letterless}
        elif len(picked) > 1:
            tied |= {r.sec_id for r in picked}
        elif named and not _named_by(seg, same):
            tied |= {r.sec_id for r in hits}      # the class's words name no sibling at all
    return matched, letters, by_name, tied - set(matched)


def match_securities(f25: Form25, refs: Sequence[SecurityRef]) -> tuple[list[str], str]:
    """Every security of `refs` the Form 25 removes: the only one of its kind,
    or, per class the text names, the one sibling of that letter (among several
    of one letter, the one whose name the class's own words pick out)."""
    kind = class_kind(f25.class_text)
    same = [r for r in refs if r.kind == kind or (kind == "other" and r.kind == "common")]
    if not same:
        return [], f"no observed {kind} security"
    if len(same) == 1:
        return [same[0].sec_id], "only security of its kind"
    matched, letters, by_name, _ = _class_matches(f25, same)
    if not matched:
        return [], "ambiguous class"
    return matched, f"class {', '.join(dict.fromkeys(letters))}" + (" by name" if by_name else "")


def tied_securities(f25: Form25, refs: Sequence[SecurityRef]) -> set[str]:
    """The unmatched siblings a Form 25 that names class letters may still be
    about: two lines of one letter that no name word tells apart (often a FIGI
    line and a placeholder for the same stock), and a line whose class carries
    no letter (Liberty SiriusXM's Series C FIGI, named "... SIRIUSXM COR")."""
    kind = class_kind(f25.class_text)
    same = [r for r in refs if r.kind == kind or (kind == "other" and r.kind == "common")]
    if len(same) < 2:
        return set()
    return _class_matches(f25, same)[3]


def class_letters(class_text: str) -> set[str]:
    """Every class letter the Form 25's text names."""
    return {class_letter(label) for label, _ in _lettered_segments(class_text)} - {None}


# R3: a lettered tracking-stock segment ("Series A Liberty Capital Common Stock"). Its group words are the words
# between the letter and COMMON STOCK, less the issuer's own EDGAR name words and these.
_GROUP = re.compile(r"^\W*(?:SERIES|CLASS)\s+[A-Z]\s+(.+?)\s+COMMON\s+STOCK", re.I)
# CAPITAL is deliberately not a stop word: it is Liberty Capital's group word (the Liberty Series A reach case).
_GROUP_STOP = frozenset({"SPECIAL", "NON", "VOTING", "NONVOTING", "NEW", "OLD", "ORDINARY", "SUBORDINATE",
                         "SUBORDINATED", "CONVERTIBLE", "RESTRICTED", "LIMITED", "PARTICIPATING", "REDEEMABLE",
                         "EXCHANGEABLE", "MULTIPLE"})


def _meets(word: str, words: set[str]) -> bool:
    """`word` is one of `words`, or one is a prefix of the other and both have five or more letters (VENTURE,
    VENTURES)."""
    return any(word == w or (min(len(word), len(w)) >= 5 and (word.startswith(w) or w.startswith(word)))
               for w in words)


def other_class(f25: Form25, ref: SecurityRef, issuer_names: Iterable[str] = ()) -> str:
    """Why a common-class Form 25 of the security's issuer is about another class than `ref` (R3), else "": it
    "relates solely to" a class that is not common (BMET 2006: "Common Shares; Preferred Share Purchase Rights",
    solely the rights), or it has lettered tracking-stock segments and none of their group words (less the
    issuer's EDGAR name words, `issuer_names`) is a word of the security's name ("Series A Liberty Capital Common
    Stock, Series A Liberty Starz Common Stock" is not Liberty Interactive's Series A)."""
    if class_kind(f25.class_text) != "common":
        return ""
    if (f25.solely and class_kind(f25.solely) not in ("common", "other")
            and not re.search(r"\b(?:COMMON|ORDINARY|SHARES)\b", f25.solely.upper())):
        return f"relates solely to {f25.solely}"
    issuer_words = {w for n in issuer_names for w in name_tokens(n)}
    groups = []
    for _, seg in _lettered_segments(f25.class_text):
        m = _GROUP.search(seg.strip())
        if m:
            words = name_tokens(m.group(1)) - issuer_words - _GROUP_STOP
            if words:
                groups.append(words)
    mine = name_tokens(ref.name)
    if groups and not any(_meets(w, mine) for g in groups for w in g):
        return "names another group (" + ", ".join(sorted(set().union(*groups))) + ")"
    return ""


def _day(s: str) -> date:
    return datetime.strptime(re.sub(r"\s+", " ", s), "%B %d, %Y").date()


def notice_last_trade(f25: Form25) -> tuple[date | None, str]:
    """The last trade day the exchange's notice states, and how it said it.

    Spec 8.8: on an involuntary notice (rule 12d2-2(b)) the date is the
    Exchange's decision day, whatever the wording ("an announcement was made on
    the 'ticker' ... at the close of the trading session on February 2, 2015 of
    the suspension"), so it comes back as `notice_b_unconfirmed`: MIDAS or a
    Nasdaq halt must confirm it, else the delisting is flagged
    `last_trade_date_unconfirmed` (`last_trade.decide_last_trade`)."""
    t = re.sub(r"\s+", " ", f25.notice_text or "")
    involuntary = is_involuntary(f25)
    day, kind = _notice_day(t, involuntary) if t else (None, "")
    if day is not None and involuntary:
        return day, "notice_b_unconfirmed"
    if day is None:
        return _class_expiry(f25)
    return day, kind


_EXPIRING = re.compile(r"\bexpir\w*\s+(?:on\s+)?(?:(\d{1,2})/(\d{1,2})/(\d{4})|((?:January|February|March|April|May|"
                       r"June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}))", re.I)


def _class_expiry(f25: Form25) -> tuple[date | None, str]:
    """A rights or warrant class whose name dates its expiry ("Subscription Rights Expiring 7/27/2020": TMUSR
    2020, 5d): that day, the class's last trading day, kind `notice_expiry`; else (None, "")."""
    if class_kind(f25.class_text) not in ("right", "warrant"):
        return None, ""
    m = _EXPIRING.search(f25.class_text or "")
    if not m:
        return None, ""
    day = _day(m.group(4)) if m.group(4) else date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    # only an expiry that falls in [filing - 30 d, effective date]: a class "expiring 09/30/2026" on a 2023 Form 25
    # is no last trade (Roivant)
    try:
        filed = date.fromisoformat(f25.filing_date)
    except ValueError:
        return None, ""
    if not filed - timedelta(days=30) <= day <= filed + timedelta(days=10):
        return None, ""
    return day, "notice_expiry"


# The NYSE 12d2-2(b) template's "an announcement was made on the 'ticker' of the Exchange ... at the close of the
# trading session on D": D is the press day, never the last trade (TMA, IDARQ 2008).
_PRESS_DAY = re.compile(r"announcement was made on the [^.]{0,80}?\bof the Exchange[^.]{0,60}?"
                        r"(?:at|after) (?:the )?close of the trading session on", re.I)


def _notice_day(t: str, involuntary: bool) -> tuple[date | None, str]:
    m = re.search(rf"suspended from trading on {_DATE}", t, re.I)
    if m and not involuntary:
        return previous_trading_day(_day(m.group(1))), "notice_a"
    # "at the close of the trading session on D", "after market close on D"
    t_close = _PRESS_DAY.sub("PRESS", t)
    m = re.search(rf"(?:at|after) (?:the )?(?:market )?close(?: of (?:the )?(?:trading|market)(?: session)?)? on {_DATE}",
                  t_close, re.I)
    if m:
        return _day(m.group(1)), "notice_close"
    # "before the opening of trading on D", "before market open on D", "prior to market open on D"
    m = re.search(rf"(?:prior to|before) (?:the )?(?:market )?(?:open|opening)(?: of (?:the )?(?:trading|market)(?: session| day)?)? "
                  rf"on {_DATE}", t, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "notice_open"
    # NYSE Amex: "The security was suspended by the Exchange on D" (no trading on D)
    m = re.search(rf"suspended by the Exchange on {_DATE}", t, re.I)
    if m and not involuntary:
        return previous_trading_day(_day(m.group(1))), "notice_a"
    m = re.search(rf"would be suspended on {_DATE}", t, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "notice_nasdaq"
    # "On November 18, 2024, the Exchange determined that the common stock of Spirit Airlines, Inc.
    # ... should be suspended": allow periods inside the span (issuer names end in "Inc.").
    m = re.search(rf"on {_DATE},?.{{0,120}}?determined.{{0,400}}?suspended", t, re.I)
    if m:
        return _day(m.group(1)), "notice_b_unconfirmed"
    m = re.search(rf"suspended from trading on {_DATE}", t, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "notice_a"
    return None, ""


# R6b: the EX-99.25 notice says holders were paid ("acquired by", "converted into the right to receive $55.00 in
# cash"), and nothing of a reclassification, a holding company or a reorganization.
_ACQUIRED = re.compile(r"\bacquired\s+by\b|converted\s+into\s+(?:the\s+right\s+to\s+receive\s+)?(?:[^.]{0,120}?)"
                       r"(?:\$\s?[\d,.]+|\bcash\b)", re.I)
_REORGANIZED = re.compile(r"reclassif|formation\s+of\s+a\s+holding\s+company|holding\s+company\s+reorgani"
                          r"|reorganized\s+as|reorganization", re.I)


def notice_says_acquired(f25: Form25) -> bool:
    """Whether the exchange's EX-99.25 notice says the class was acquired or converted into cash (NTY 2010,
    "converted into the right to receive $55.00 in cash"; BMET 2007, "Acquired by LVB"), and nothing of a
    reclassification, a holding company's formation or a reorganization (HUB-B, HHC and APA 2021 stay
    continuations)."""
    t = re.sub(r"\s+", " ", f25.notice_text or "")
    return bool(_ACQUIRED.search(t)) and not _REORGANIZED.search(t)

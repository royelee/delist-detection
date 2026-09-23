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

from .edgar import EdgarSubmission, _strip_html
from .figi_resolution import class_letter
from .trading_calendar import previous_trading_day

FORM25_FORMS = frozenset({"25", "25-NSE", "25/A", "25-NSE/A"})
MAJOR_EXCHANGES = frozenset({"NYSE", "NYSE AMERICAN", "NASDAQ", "NYSE ARCA", "CBOE BZX"})
REGIONAL_EXCHANGES = frozenset({"CHICAGO", "NSX", "PACIFIC", "BOSTON", "PHLX"})

# Order matters: the specific names before the bare NYSE / NASDAQ patterns.
_EXCHANGES: list[tuple[str, str]] = [
    ("NYSE AMERICAN", r"NYSE\s*AMERICAN|NYSE\s*MKT|NYSE\s*AMEX|AMERICAN STOCK EXCHANGE|\bAMEX\b"),
    ("NYSE ARCA", r"NYSE\s*ARCA|ARCHIPELAGO"),
    ("CHICAGO", r"CHICAGO STOCK EXCHANGE|NYSE\s*CHICAGO"),
    ("NSX", r"NATIONAL STOCK EXCHANGE|NYSE\s*NATIONAL"),
    ("PACIFIC", r"PACIFIC (?:STOCK )?EXCHANGE"),
    ("BOSTON", r"BOSTON STOCK EXCHANGE|NASDAQ\s*(?:OMX\s*)?BX"),
    ("PHLX", r"PHILADELPHIA STOCK EXCHANGE|NASDAQ\s*(?:OMX\s*)?PHLX|\bPHLX\b"),
    ("CBOE BZX", r"CBOE\s*BZX|\bBATS\b"),
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


def _tag(raw: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", raw, re.S | re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def _notice(raw: str) -> str:
    m = re.search(r"<TYPE>EX-99\.25(.*?)(?=<TYPE>|</DOCUMENT>|\Z)", raw, re.S | re.I)
    return _strip_html(m.group(1)) if m else ""


def parse_form25(raw: str, *, accession: str, form: str, filing_date: str) -> Form25:
    exch_block = re.search(r"<exchange>(.*?)</exchange>", raw, re.S | re.I)
    exch_name = _tag(exch_block.group(1), "entityName") if exch_block else ""
    class_text = _tag(raw, "descriptionClassSecurity")
    rule = _tag(raw, "ruleProvision")
    if not exch_name:                         # a text Form 25 without the XML document
        text = _strip_html(raw)
        exch_name = exchange_label(text[:4000])
        if not class_text:
            m = re.search(r"(?:class|title) of (?:the )?securit(?:y|ies)[^:]{0,40}:\s*(.{3,120}?)(?:\s{2,}|\.|$)",
                          text, re.I)
            class_text = m.group(1).strip() if m else ""
    return Form25(accession, form, filing_date, exchange_label(exch_name) or exch_name.upper(),
                  class_text, rule, _notice(raw))


def list_form25(filings: Iterable[EdgarSubmission]) -> list[EdgarSubmission]:
    return sorted((f for f in filings if f.form in FORM25_FORMS), key=lambda f: (f.filing_date, f.accession))


def class_kind(class_text: str) -> str:
    s = (class_text or "").upper().strip()
    if not s:
        return "other"
    if re.match(r"^\W*(?:CLASS [A-Z] |SERIES [A-Z] )?(?:COMMON|ORDINARY)", s):
        return "common"
    if re.search(r"PREFERRED|DEPOSITARY SHARES?,? EACH REPRESENTING", s):
        return "preferred"
    if re.search(r"^\W*UNITS?\b", s):
        return "unit"
    if re.search(r"^\W*WARRANTS?\b", s):
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


def class_label(class_text: str) -> str | None:
    s = (class_text or "").upper()
    m = re.search(r"\bCLASS\s+([A-Z])\b", s)
    if m:
        return f"CLASS {m.group(1)}"
    m = re.search(r"\bSERIES\s+([A-Z])\b", s)
    if m:
        return f"SERIES {m.group(1)}"
    return None


@dataclass(frozen=True)
class SecurityRef:
    sec_id: str
    share_class: str
    kind: str


def match_security(f25: Form25, refs: Sequence[SecurityRef]) -> tuple[str | None, str]:
    kind = class_kind(f25.class_text)
    same = [r for r in refs if r.kind == kind or (kind == "other" and r.kind == "common")]
    if not same:
        return None, f"no observed {kind} security"
    if len(same) == 1:
        return same[0].sec_id, "only security of its kind"
    letter = class_letter(class_label(f25.class_text))
    if letter:
        hits = [r for r in same if class_letter(r.share_class) == letter]
        if len(hits) == 1:
            return hits[0].sec_id, f"class {letter}"
    return None, "ambiguous class"


def _day(s: str) -> date:
    return datetime.strptime(re.sub(r"\s+", " ", s), "%B %d, %Y").date()


def notice_last_trade(f25: Form25) -> tuple[date | None, str]:
    t = re.sub(r"\s+", " ", f25.notice_text or "")
    if not t:
        return None, ""
    involuntary = "(b)" in (f25.rule or "")
    m = re.search(rf"suspended from trading on {_DATE}", t, re.I)
    if m and not involuntary:
        return previous_trading_day(_day(m.group(1))), "notice_a"
    m = re.search(rf"(?:at|after) the close(?: of (?:the )?(?:trading|market)(?: session)?)? on {_DATE}", t, re.I)
    if m:
        return _day(m.group(1)), "notice_close"
    m = re.search(rf"(?:prior to|before) the (?:open|opening)(?: of (?:the )?trading)? on {_DATE}", t, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "notice_open"
    m = re.search(rf"would be suspended on {_DATE}", t, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "notice_nasdaq"
    # "On November 18, 2024, the Exchange determined that the common stock of Spirit Airlines, Inc.
    # ... should be suspended": allow periods inside the span (company names end in "Inc.").
    m = re.search(rf"on {_DATE},?.{{0,120}}?determined.{{0,400}}?suspended", t, re.I)
    if m:
        return _day(m.group(1)), "notice_b_unconfirmed"
    m = re.search(rf"suspended from trading on {_DATE}", t, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "notice_a"
    return None, ""


def effective_date(filing_date: str) -> str:
    return (date.fromisoformat(filing_date) + timedelta(days=10)).isoformat()

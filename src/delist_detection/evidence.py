"""Pure evidence predicates over one issuer's EDGAR record. No network."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .edgar import EdgarSubmission

_BANKRUPTCY_TEXT = re.compile(r"bankruptcy|chapter\s+(?:11|7)\b|receivership", re.I)
_TRANSFER_TEXT = re.compile(r"transfer(?:red)?\s+(?:the|its|of\s+(?:the|its))\s+listing", re.I)

_DEFICIENCY_TEXT = re.compile(
    r"minimum\s+bid\s+price|stockholders[’']?\s+equity\s+requirement|"
    r"market\s+value\s+of\s+(?:listed|publicly\s+held)|regain(?:ed)?\s+compliance|"
    r"not\s+in\s+compliance|failure\s+to\s+(?:timely\s+)?file|delinquen|"
    r"failure\s+to\s+(?:comply\s+with|satisfy)\s+(?:the|its|one\s+or\s+more)\s+continued\s+listing|"
    r"abnormally\s+low|average\s+global\s+market\s+capitali[sz]ation|"
    r"no\s+longer\s+suitable\s+for\s+(?:continued\s+)?listing|commence(?:d)?\s+proceedings\s+to\s+delist|"
    # sub-plan 5b: NYSE's market-capitalization removals (R.H. Donnelley 2008: "no longer complies with NYSE
    # continued listing requirements ... average market capitalization")
    r"no\s+longer\s+compl(?:ies|y)\s+with|below\s+(?:the\s+)?(?:NYSE|Exchange|Nasdaq)['’]?s?\s+continued\s+listing|"
    r"fallen\s+below\s+.{0,40}continued\s+listing|average\s+(?:total\s+)?market\s+capitali[sz]ation", re.I)

SPAC_SIC = "6770"
_SPAC_NAME = re.compile(r"\bacquisition\s+corp", re.I)

# Proxy and tender-offer filings that announce a takeover of the registrant.
MERGER_EVIDENCE_FORMS = {"DEFM14A", "DEFM14C", "PREM14A", "SC 14D9", "SC TO-T", "425"}


def parse_day(s: str | None) -> date | None:
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def edgar_names(sub: dict) -> tuple[str, ...]:
    """Every name EDGAR records for the issuer: its current name, then its former
    names (`formerNames`), blanks left out."""
    names = [sub.get("name") or "",
             *((fn.get("name") or "") for fn in sub.get("formerNames") or [] if isinstance(fn, dict))]
    return tuple(n for n in names if n.strip())


def name_at(sub: dict, on: date) -> str:
    """The EDGAR name on `on`: the formerNames entry whose [from, to] covers it, else the current name."""
    for fn in sub.get("formerNames") or []:
        lo, hi = parse_day(fn.get("from")), parse_day(fn.get("to"))
        if lo and hi and lo <= on <= hi:
            return fn.get("name") or ""
    return sub.get("name") or ""


def is_spac(sub: dict, on: date) -> bool:
    """True if the company is a blank-check acquisition company as of `on`.

    True when either:
      - the name at `on` (via `name_at`) matches "... Acquisition Corp"; or
      - the SIC is 6770 AND no `formerNames` entry has a `to` date on or
        before `on` (i.e. the company has not completed a rename by `on`).

    The bare SIC test is not enough: EDGAR doesn't always update a SIC after
    a de-SPAC merger, so a stale 6770 would pre-empt a real merger or
    compliance failure that happens later under the same CIK into a false
    EXPIRATION/600. Requiring no completed rename by `on` closes that gap
    while still catching genuine SPAC liquidations, which (like FST, BWC,
    HMA, LEAP) carry SIC 6770 and an empty `formerNames`.
    """
    if _SPAC_NAME.search(name_at(sub, on)):
        return True
    if str(sub.get("sic") or "") != SPAC_SIC:
        return False
    for fn in sub.get("formerNames") or []:
        hi = parse_day(fn.get("to"))
        if hi and hi <= on:
            return False
    return True


def names_near(sub: dict, on: date, days: int = 30) -> list[str]:
    """Every name the company carried within ±days of `on`, former names first.

    A delisting date and a rename date are often a day apart (EDGAR ends
    "Halyard Health" on 2018-06-28; HYH's last vendor row is 2018-06-29), so a
    single-day lookup misses the name the index used."""
    return names_between(sub, on - timedelta(days=days), on + timedelta(days=days))


def names_between(sub: dict, lo: date, hi: date) -> list[str]:
    """Every name the company carried at some point in [lo, hi], former names first."""
    out: list[str] = []
    last_end: date | None = None
    for fn in sub.get("formerNames") or []:
        f_lo, f_hi = parse_day(fn.get("from")), parse_day(fn.get("to"))
        if f_hi and (last_end is None or f_hi > last_end):
            last_end = f_hi
        if f_lo and f_hi and f_lo <= hi and f_hi >= lo and fn.get("name"):
            out.append(fn["name"])
    if (last_end is None or last_end <= hi) and sub.get("name"):
        out.append(sub["name"])      # the current name runs from the last rename on
    return out


def names_until(sub: dict, on: date) -> list[str]:
    """Every name the company carried on or before `on`, former names first: the
    former names that began by then (one with no start date counts), and the
    current name once it began (it runs from the last rename on)."""
    out: list[str] = []
    last_end: date | None = None
    for fn in sub.get("formerNames") or []:
        f_lo, f_hi = parse_day(fn.get("from")), parse_day(fn.get("to"))
        if f_hi and (last_end is None or f_hi > last_end):
            last_end = f_hi
        if fn.get("name") and (f_lo is None or f_lo <= on):
            out.append(fn["name"])
    if (last_end is None or last_end <= on) and sub.get("name"):
        out.append(sub["name"])
    return out


def first_filing(filings: list[EdgarSubmission]) -> date | None:
    days = [d for f in filings if (d := parse_day(f.filing_date))]
    return min(days) if days else None


def bankruptcy_8ks(filings: list[EdgarSubmission], on: date, before: int = 540, after: int = 30) -> list[EdgarSubmission]:
    """8-Ks tagged item 1.03 (Bankruptcy or Receivership) within [on-before, on+after]."""
    lo, hi = on - timedelta(days=before), on + timedelta(days=after)
    out = []
    for f in filings:
        d = parse_day(f.report_date) or parse_day(f.filing_date)
        if f.form.startswith("8-K") and "1.03" in f.item_set and d and lo <= d <= hi:
            out.append(f)
    return sorted(out, key=lambda f: f.filing_date)


def mentions_bankruptcy(text: str) -> bool:
    return bool(_BANKRUPTCY_TEXT.search(text or ""))


OPERATING_FORMS = {"10-K", "10-Q", "20-F", "40-F"}


def filed_operating_between(filings: list[EdgarSubmission], lo: date, hi: date) -> bool:
    """True if the company filed a periodic operating report (or an 8-K with
    earnings item 2.02) strictly between `lo` and `hi` — evidence that an
    earlier Form 25 candidate is a different, still-operating event rather
    than the anchor for the delisting at `hi`."""
    for f in filings:
        d = parse_day(f.filing_date)
        if d and lo < d < hi and (f.form in OPERATING_FORMS or (f.form == "8-K" and "2.02" in f.item_set)):
            return True
    return False


def renamed_near(sub: dict, on: date, days: int = 60) -> str | None:
    """The former name whose EDGAR-name-change end date falls within `days`
    of `on` — a rename around the delisting date, not just any old name."""
    for fn in sub.get("formerNames") or []:
        hi = parse_day(fn.get("to"))
        if hi and abs((hi - on).days) <= days:
            return fn.get("name")
    return None


def still_operating(filings: list[EdgarSubmission], on: date, days: int = 15) -> bool:
    """Reported results (10-K/10-Q or an 8-K item 2.02) after on+days and filed no Form 15 after on."""
    cutoff = on + timedelta(days=days)
    operating = deregistered = False
    for f in filings:
        d = parse_day(f.filing_date)
        if d is None or d <= on:
            continue
        if f.form.startswith("15-"):
            deregistered = True
        if d > cutoff and (f.form in OPERATING_FORMS or (f.form == "8-K" and "2.02" in f.item_set)):
            operating = True
    return operating and not deregistered


# An item number's digits and point may come apart: the HTML stripping spaces some filers' headings out ("ITEM 1 .0 3
# Bankruptcy or Receivership", "ITEM 3 . 01": CBL 2020, sub-plan 5g).
_ITEM_HEAD = re.compile(r"item\s*\d\s*\.\s*\d\s*\d(?!\d)", re.I)
ITEM_MIN_SECTION = 200   # shorter than this is an index entry or a cross-reference, not a section


def _item_mention(item: str) -> re.Pattern:
    """`Item {item}` in any case, spaces allowed inside its number, and no further digit after it."""
    return re.compile(r"item\s*" + r"\s*".join(re.escape(ch) for ch in item.replace(" ", "")) + r"(?!\d)", re.I)


def item_sections(text: str, item: str, width: int = 1500) -> list[str]:
    """Every `Item {item}` section of `text` (any case), in order.

    A section runs from a mention of the item to the next `Item N.NN` heading or
    `width` characters, whichever comes first. An 8-K's cover page indexes every
    item it carries, and the body cross-references items too, so a mention is
    often a one-line entry that says nothing: only sections of at least
    ITEM_MIN_SECTION characters count. If every one is shorter (a short filing
    with one heading), the first mention and `width` characters is the one
    section. A cross-reference long enough to count ("The information set forth
    below in Item 1.03 ... is incorporated by reference in this Item 1.01":
    Ascena 2020) can come before the item's own section, so a reader that looks
    for wording reads every section, not only the first.
    """
    text = text or ""
    matches = list(_item_mention(item).finditer(text))
    if not matches:
        return []
    out = []
    for m in matches:
        end = min(len(text), m.start() + width)
        nxt = _ITEM_HEAD.search(text, m.end())
        if nxt and nxt.start() < end:
            end = nxt.start()
        if end - m.start() >= ITEM_MIN_SECTION:
            out.append(text[m.start():end])
    return out or [text[matches[0].start():matches[0].start() + width]]


def item_text(text: str, item: str, width: int = 1500) -> str:
    """The first `Item {item}` section of `text` (`item_sections`), else ""."""
    sections = item_sections(text, item, width)
    return sections[0] if sections else ""


def says_listing_transfer(text: str) -> bool:
    """True if `text` describes transferring the listing to another exchange,
    as opposed to a compliance-deficiency notice."""
    return bool(_TRANSFER_TEXT.search(text or ""))


MERGER_EVIDENCE_DAYS = 400   # how far before `on` a merger proxy / tender filing still counts


def merger_evidence(filings: list[EdgarSubmission], on: date,
                    before: int = MERGER_EVIDENCE_DAYS, after: int = 30):
    """The latest merger proxy or tender-offer filing within [on-before, on+after], else None."""
    lo, hi = on - timedelta(days=before), on + timedelta(days=after)
    hits = [f for f in filings if f.form in MERGER_EVIDENCE_FORMS
            and (d := parse_day(f.filing_date)) and lo <= d <= hi]
    return max(hits, key=lambda f: f.filing_date) if hits else None


def cites_listing_deficiency(text: str) -> bool:
    """True if `text` (a 3.01 notice) cites a continued-listing deficiency."""
    return bool(_DEFICIENCY_TEXT.search(text or ""))

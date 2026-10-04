"""The last day a security traded on its exchange.

No rule requires an issuer to state it, so it is read from several places and
cross-checked: the exchange's Form 25 notice (form25.notice_last_trade), the
closing 8-K's Item 3.01 text (here), SEC MIDAS exchange volume and Nasdaq's
code-D halts. Measured volume beats wording, and wording that disagrees with it
is flagged. When nothing states the day, the closing day the filings give
(`closing_day`) is the worked-out day: kept in delistings.csv, never published
(decision 12; sub-plan 5d rule 4).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from .evidence import ITEM_MIN_SECTION
from .trading_calendar import is_trading_day, previous_trading_day

_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
_DATE = rf"((?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})"
# "on NASDAQ", "on the NYSE", "on The Nasdaq Global Select Market": the venue a timing phrase may name before its date
_VENUE = r"(?: on (?:the )?[A-Z][\w.&]*(?: [A-Z][\w.&]*){0,4})?"
_OPEN = (r"(?:(?:prior to|before|ahead of) (?:the )?(?:(?:market|NYSE|NASDAQ|Nasdaq|regular) )?"
         r"(?:(?:open|opening)(?: of (?:the )?(?:regular )?(?:trading|market|business)(?: day| session)?)?"
         r"|commencement of trading)"
         r"|(?:as of|at|effective as of|effective at|upon) the (?:[A-Z][A-Za-z]* )?(?:market )?(?:open|opening)"
         r"(?: of (?:the )?(?:trading|business|market))?)")
_CLOSE = (r"(?:at|after|following|as of|effective as of|effective after|upon) (?:the )?"
          r"(?:(?:market )?close(?: of (?:the )?(?:regular )?(?:trading|market|business)(?: day| session| hours)?)?"
          r"|closing of (?:the )?(?:regular )?(?:trading|market|business)(?: day| session)?)")
# a sentence about the security's trading or listing stopping
_STOP = re.compile(r"suspen|ceas|halt|delist|withdraw|no longer (?:be )?(?:listed|traded)|trading|traded|listed",
                   re.I)
_RECORD = re.compile(r"\brecord\b", re.I)
_OBLIGATIONS = re.compile(r"obligation|reporting|duty to file|registration", re.I)
_ABBREV = re.compile(r"\b(?:Inc|Corp|Co|Ltd|Inst|No|L\.P|N\.V|S\.A|U\.S|plc|p\.m|a\.m|St|Mr|Ms|Dr|Jr|Sr)\.$", re.I)
_ITEM_HEADING = re.compile(r"item\s*\d\.\d{2}\b\.?:?\s*[–—-]?\s*(?=[A-Z])", re.I)
_CROSS_REF = re.compile(r"(?:\b(?:in|under|see|to|and|of|with|per|into|by)\s+)$", re.I)
SECTION_WIDTH = 4000

# Readings, best first: a stated timing (before the open, after the close, the last day), then a bare suspension
# date (ruling R8: the trading day before D), then a suspension "immediately on D" (D, unconfirmed).
EXPLICIT_KINDS = frozenset({"8k_open", "8k_open_closing", "8k_close", "8k_close_closing", "8k_close_effective",
                            "8k_open_effective", "8k_last_day"})
_RANK = {**{k: 0 for k in EXPLICIT_KINDS}, "8k_suspended": 1, "8k_suspended_unconfirmed": 2}
OPEN_KINDS = frozenset({"8k_open", "8k_open_closing", "8k_open_effective"})

CLOSING_DAY = "closing_day"         # last_trade_date_source of a worked-out closing day (never published)


def _day(s: str) -> date:
    return datetime.strptime(re.sub(r"\s+", " ", s), "%B %d, %Y").date()


def _closing_date(text: str) -> date | None:
    """The day a filing defines as "the Closing Date" ("On July 5, 2023 (the “ Closing Date ”)")."""
    pattern = _DATE + r'\s*\((?:the\s*)?' + '["' + "'" + '“]?' + r'\s*Closing Date'
    m = re.search(pattern, text, re.I)
    return _day(m.group(1)) if m else None


_CLOCK = r"(\d{1,2}):(\d{2})\s*([AaPp])\.?\s*[Mm]\.?"


def _minutes(hour: str, minute: str, half: str) -> int:
    h = int(hour) % 12 + (12 if half.lower() == "p" else 0)
    return h * 60 + int(minute)


OPEN_MINUTES, CLOSE_MINUTES = 9 * 60 + 30, 16 * 60


def _effective_time(text: str) -> tuple[date, int] | None:
    """The day and the minute of the day of a filing's defined "Effective Time" ("On December 15, 2025 at 4:05 p.m.,
    New York City time (the “ Effective Time ”)", "at 8:28 A.M. (Eastern) on November 24, 2008 (the “Effective
    Time”)")."""
    for pattern in (rf"{_DATE},? at {_CLOCK}[^()]{{0,60}}\((?:the\s*)?[\"'“]?\s*Effective Time",
                    rf"at {_CLOCK}[^.;()]{{0,40}}? on {_DATE}\s*\((?:the\s*)?[\"'“]?\s*Effective Time"):
        m = re.search(pattern, text, re.I)
        if m:
            g = m.groups()
            if g[0][0].isalpha():
                return _day(g[0]), _minutes(*g[1:4])
            return _day(g[3]), _minutes(*g[0:3])
    return None


def sections_3_01(text: str, width: int = SECTION_WIDTH) -> list[str]:
    """Every Item 3.01 section of an 8-K (`evidence.item_sections`' rule: a mention shorter than ITEM_MIN_SECTION
    is an index entry; all short, the first mention), each running to the next item heading -- an "Item N.NN"
    followed by its capitalized title -- rather than to a cross-reference ("described in Item 1.01 above", "under
    Item 1.03 of this Current Report": NOVL 2011, WM 2008), or `width` characters."""
    text = text or ""
    out = []
    for m in re.finditer(r"item\s*3\.01", text, re.I):
        chunk = text[m.start(): m.start() + width]
        end = len(chunk)
        for h in _ITEM_HEADING.finditer(chunk, m.end() - m.start()):
            if not _CROSS_REF.search(chunk[max(0, h.start() - 12):h.start()]):
                end = h.start()
                break
        out.append(re.sub(r"\s+", " ", chunk[:end]))
    return [s for s in out if len(s) >= ITEM_MIN_SECTION] or out[:1]


def _sentences(text: str) -> list[str]:
    """`text` cut into sentences at a period or semicolon followed by a capital (not after "Inc.", "p.m.")."""
    out, start = [], 0
    for m in re.finditer(r"[.;](?=\s+[A-Z(“\"•])", text):
        if _ABBREV.search(text[max(0, m.start() - 6):m.end()]):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    out.append(text[start:].strip())
    return [s for s in out if s]


def _read_sentence(s: str, flat: str) -> tuple[date | None, str]:
    """One sentence's reading: (day, kind) or (None, "")."""
    if not _STOP.search(s):
        return None, ""

    def clear(m: re.Match) -> bool:      # not a record date ("holders of record as of the close of business on D")
        return not _RECORD.search(s[max(0, m.start() - 60):m.start()])

    m = re.search(rf"{_OPEN}{_VENUE}(?: on)? {_DATE}", s, re.I)
    if m and clear(m):
        return previous_trading_day(_day(m.group(1))), "8k_open"
    if re.search(rf"{_OPEN}[^.]{{0,40}}?Closing Date", s, re.I) and (cd := _closing_date(flat)):
        return previous_trading_day(cd), "8k_open_closing"
    m = re.search(rf"{_CLOSE}{_VENUE}(?: on)? {_DATE}", s, re.I)
    if m and clear(m):
        return _day(m.group(1)), "8k_close"
    if re.search(rf"{_CLOSE}[^.]{{0,40}}?Closing Date", s, re.I) and (cd := _closing_date(flat)):
        return cd, "8k_close_closing"
    if re.search(r"(?:after|following) the Effective Time", s, re.I) and re.search(r"suspen|delist|ceas|halt", s, re.I):
        et = _effective_time(flat)
        days = [_day(d) for d in re.findall(_DATE, s)]
        if et is not None and (not days or et[0] in days):
            if et[1] >= CLOSE_MINUTES:
                return et[0], "8k_close_effective"
            if et[1] < OPEN_MINUTES:
                return previous_trading_day(et[0]), "8k_open_effective"
    m = re.search(rf"last (?:day of trading|trading day|day (?:on which|that) [^.;]{{0,60}}? traded)[^.;]{{0,40}}?"
                  rf"(?:was|will be|is|would be) {_DATE}", s, re.I) \
        or re.search(rf"{_DATE},? (?:which|that) (?:was|will be|is|would be) the last (?:full )?(?:day|trading day)",
                     s, re.I) \
        or re.search(rf"(?:continue to be|will be|remain) listed(?: and traded)?{_VENUE} through {_DATE}", s, re.I)
    if m:
        return _day(m.group(1)), "8k_last_day"
    m = re.search(rf"suspended immediately on {_DATE}", s, re.I)
    if m:
        return _day(m.group(1)), "8k_suspended_unconfirmed"
    # Ruling R8: "suspended on D" with no timing word means the last trade was the trading day before D.
    m = re.search(rf"suspended(?: (?:from )?trading)?(?: (?:of|in) [^.;]{{0,100}}?)?{_VENUE} on {_DATE}", s, re.I)
    if m and not _OBLIGATIONS.search(s[max(0, m.start() - 80):m.start()]) and "immediately" not in m.group(0).lower():
        return previous_trading_day(_day(m.group(1))), "8k_suspended"
    return None, ""


def eightk_last_trade(text: str) -> tuple[date | None, str]:
    """The last trade day an 8-K's Item 3.01 states, read sentence by sentence (the whole filing when it has no 3.01
    section), and how it said it: the best reading of `_RANK`, the first of equals."""
    if not text:
        return None, ""
    flat = re.sub(r"\s+", " ", text)
    sections = sections_3_01(text) or [flat]
    best: tuple[date | None, str] = (None, "")
    for section in sections:
        for s in _sentences(section):
            day, kind = _read_sentence(s, flat)
            if day is not None and (best[0] is None or _RANK[kind] < _RANK[best[1]]):
                best = (day, kind)
                if _RANK[kind] == 0:
                    return best
    return best


def reading_rank(kind: str) -> int:
    """How strong an 8-K reading is (0 best); a kind `eightk_last_trade` never gives ranks last."""
    return _RANK.get(kind, 9)


# -- the closing day (rule 4: nothing states the last trade) ------------------
_DEAL = (r"(?:merger|mergers|acquisition|reorganization|arrangement|split-off|separation|combination|transactions?|"
         r"amalgamation|scheme)")
# "On D, ... completed its acquisition", "effected a short-form merger", "implemented a holding company
# reorganization", "Merger Sub merged with and into", "merged (the “Merger”) with and into", "upon consummation of
# the Reorganization": the deal word right after the verb, so "completed the sale of Porex" (HLTH 2009, an asset
# sale) is no closing, nor a subsidiary's own merger after it ("FCC merged with and into New Alpha": FCL 2009)
_COMPLETED = re.compile(
    rf"\bOn (?:the evening of )?{_DATE},? [^.;]{{0,900}}?(?:\b(?:completed|consummated|effected|implemented|closed)\s+"
    rf"(?:its |the |a |an )?(?:previously announced |proposed )?(?:[\w-]+ ){{0,2}}{_DEAL}\b"
    rf"|\b(?:Merger Sub|Merger Subsidiary|Purchaser|Acquisition Sub)(?: [^.;]{{0,40}}?)? (?:was )?merged with and into"
    rf"|\bmerged \((?:the\s*)?[\"'“]?\s*Merger\s*[\"'”]?\) with and into"
    rf"|\bupon (?:the )?(?:consummation|completion) of (?:the )?(?:[\w-]+ ){{0,2}}{_DEAL}\b)", re.I)
_NO_ABBREV = re.compile(r"\b(Inc|Corp|Co|Ltd|L\.P|N\.V|S\.A|U\.S|No|plc|LLC)\.", re.I)   # "Inc." ends no clause
_EVENING = re.compile(rf"\b(?:on )?the evening of {_DATE}", re.I)
_COMPLETION_ON = re.compile(rf"\b(?:closing|completion|consummation) (?:of )?(?:the )?(?:\w+ ){{0,2}}{_DEAL}"
                            rf"(?: on| as of)? {_DATE}", re.I)
_DEFINED_CLOSING = re.compile(rf"{_DATE}\s*\((?:the\s*)?[\"'“]?\s*(?:Closing Date|Closing|Merger Effective Date)\s*[\"'”]?"
                              r"\s*\)", re.I)
_TIMED = re.compile(rf"{_CLOCK}[^.;]{{0,60}}? on (?:\w+day, )?{_DATE}|{_DATE},? at {_CLOCK}", re.I)
_DEAL_WORDS = re.compile(rf"effective time|became effective|complet|consummat|{_DEAL}", re.I)


def closing_day(texts: Iterable[str], lo: date, hi: date) -> tuple[date, str] | None:
    """The day a deal closed, read from its filings, and the last trade day that gives: (day, kind). The closing day
    C is the latest completion the texts state within [lo, hi] -- a defined "Closing Date", "On D, ... completed
    (the merger)", "the closing of the transactions on D", "the evening of D", an effective time stated with a
    clock time; the last trade is C, or the trading day before C when every clock time stated on C is before the
    open (Imclone 2008: 8:28 A.M. on November 24) or C is no session (PNFP 2026: January 1). None when no text states a completion in the window. A tender
    offer's completion or a record date never counts."""
    found: list[tuple[date, int | None]] = []
    for text in texts:
        flat = re.sub(r"\s+", " ", text or "")
        if not flat:
            continue
        for s in _sentences(flat):
            if _RECORD.search(s):
                continue
            for m in _TIMED.finditer(s):
                if not _DEAL_WORDS.search(s):
                    break
                g = m.groups()
                if g[0] is not None:
                    found.append((_day(g[3]), _minutes(*g[0:3])))
                else:
                    found.append((_day(g[4]), _minutes(*g[5:8])))
            for rx in (_DEFINED_CLOSING, _EVENING, _COMPLETION_ON):
                found += [(_day(m.group(1)), None) for m in rx.finditer(s)]
            found += [(_day(m.group(1)), None) for m in _COMPLETED.finditer(_NO_ABBREV.sub(r"\1", s))]
    days = sorted({d for d, _ in found if lo <= d <= hi})
    if not days:
        return None
    c = days[-1]
    clocks = [t for d, t in found if d == c and t is not None]
    if (clocks and all(t < OPEN_MINUTES for t in clocks)) or not is_trading_day(c):
        return previous_trading_day(c), CLOSING_DAY
    return c, CLOSING_DAY


@dataclass(frozen=True)
class LastTrade:
    day: date | None
    source: str
    flags: tuple[str, ...]
    # Days of the Nasdaq halt feed this decision asked for and could not read
    # (nasdaq_halts: a failure, not "no halts"): the decision rests on them.
    halt_feed_failed: tuple[date, ...] = ()


def _confirmed(kind: str) -> bool:
    return bool(kind) and not kind.endswith("unconfirmed")


# A notice's own stated timing ("at the close of the trading session on D", "before the opening on D") beats any
# 8-K; its bare suspension date ("was suspended from trading on D": the trading day before D) gives way to an 8-K
# that states the timing and disagrees (TMHC 2026: "following the closing of trading on July 24").
BARE_NOTICE_KINDS = frozenset({"notice_a", "notice_nasdaq"})


def decide_last_trade(*, notice: tuple[date | None, str], eightk: tuple[date | None, str],
                      midas: date | None, halt: date | None) -> LastTrade:
    texts = [d for d, _ in (notice, eightk) if d is not None]

    def pick(day: date, source: str, extra: tuple[str, ...] = ()) -> LastTrade:
        conflict = ("last_trade_date_conflict",) if any(d != day for d in texts) else ()
        return LastTrade(day, source, extra + conflict)

    (n_day, n_kind), (e_day, e_kind) = notice, eightk
    if midas is not None:
        return pick(midas, "midas")
    if halt is not None:
        if e_day is not None and e_kind in OPEN_KINDS and e_day == previous_trading_day(halt):
            # the 8-K says the halt came at the open of the halt day (ruling R8: WM 2008, the regulatory halt "at
            # the NYSE market open on September 26", which the feed stamps 09:30:06): the day before
            return pick(e_day, "8k_301")
        return pick(halt, "nasdaq_halt")
    if n_day and _confirmed(n_kind):
        if n_kind in BARE_NOTICE_KINDS and e_day and e_kind in EXPLICIT_KINDS and e_day != n_day:
            return pick(e_day, "8k_301")
        return pick(n_day, "ex99_notice")
    if e_day and _confirmed(e_kind):
        return pick(e_day, "8k_301")
    if n_day:
        return pick(n_day, "ex99_notice", ("last_trade_date_unconfirmed",))
    if e_day:
        return pick(e_day, "8k_301", ("last_trade_date_unconfirmed",))
    return LastTrade(None, "", ("no_last_trade_date",))

"""The last trade date as one module (architecture step 4): the last day a security traded on its exchange, how
an ending is dated, and what that day means.

No rule requires an issuer to state the day, so it is read from several places and cross-checked:

- the exchange's Form 25 notice (`form25.notice_last_trade`);
- the 3.01 8-Ks' text (`eightk_last_trade`), read in windows around the Form 25 group or the fallback's dating
  filing;
- SEC MIDAS exchange volume and Nasdaq's code-D halts, the two confirmations. Each is an adapter of `Dating`: a real
  client (`midas.MidasClient`, `nasdaq_halts.NasdaqHaltClient`) or a fixture-backed double;
- the ticker's tenure (rule 3): a read by ticker from the day another CUSIP took it is that security's
  (`trading_record.TradingRecord.taken`: the security's trading record, which the finder passes in);
- when nothing states the day, the closing day the filings give (rule 4, `closing_day_read`) is the worked-out day,
  kept in delistings.csv and never published (decision 12).

Measured volume beats wording, and wording that disagrees with it is flagged (`decide_last_trade`).

The interface:
- `Dating` dates an ending: a Form 25 group (`of_group`, rule 4 inside), the no-Form-25 fallback (`of_fallback`),
  and stage 9c's re-dating of a handoff row from its own Form 25 notice (`from_notice`);
- `at_handoff`: the handoff stage's day for a continuation row and its cap on a worked-out day;
- the ending's anchor day (`anchor_day`: the day it is read around) and an added successor's first day after it
  (`first_day_after`).

The answer type `LastTrade`, its derived facts (`confirmed`, `worked_out`, `publishable`), the day an ending ends its
security's listing (`end_day`: the clip and stage 9e), the reading of a delistings.csv row (`of_row`, `effective_of`,
`published`), the sources (`SOURCES`, `EXCHANGE_PRINTS`) and the flags (`UNCONFIRMED`, `CONFLICT`, `NO_DAY`) the
module writes are defined once in exit_kind, the row vocabulary (architecture step 8a), so the verdict, the scorecard
and the contract read them without this module's clients.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from ..filings.evidence import ITEM_MIN_SECTION, item_mention
# the last trade's sources, flags and facts are the row vocabulary's (exit_kind): this module dates an ending and
# answers a `LastTrade`, the measurement side reads the same definitions back from a row
from ..vocabulary.exit_kind import (CLOSING_DAY, CONFLICT, EIGHTK_301, EX99_NOTICE, LAST_SIGHTING, MIDAS, NASDAQ_HALT,
                                    NO_DAY, UNCONFIRMED, UNSOURCED, LastTrade, effective_date)
from ..filings.form25 import ISSUER_FORM25_FORMS, Form25, is_involuntary, notice_last_trade, parse_form25
from ..sources.midas import MIDAS_START
from ..sources.nasdaq_halts import last_trade_from_halt
from ..vocabulary.trading_calendar import is_trading_day, next_trading_day, previous_trading_day

if TYPE_CHECKING:
    from ..sources.edgar import EdgarSubmission
    from .trading_record import TradingRecord

_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
_DATE = rf"((?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})"
# an optional weekday before the date ("on Friday, December 5, 2008": TMA, IDARQ 2008); same capture group
_WDATE = r"(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?" + _DATE
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
_BAD_MID = re.compile(r"\b(?:will|would|shall|may|could)\b|merger|consummat|complet|same day", re.I)
_RECORD = re.compile(r"\brecord\b", re.I)
_OBLIGATIONS = re.compile(r"obligation|reporting|duty to file|registration", re.I)
_ABBREV = re.compile(r"\b(?:Inc|Corp|Co|Ltd|Inst|No|L\.P|N\.V|S\.A|U\.S|plc|p\.m|a\.m|St|Mr|Ms|Dr|Jr|Sr)\.$", re.I)
# an item heading; its number may be spaced out by the HTML stripping ("ITEM 3 . 01": CBL 2020), as
# `evidence.item_sections` reads it (sub-plan 5g)
_ITEM_HEADING = re.compile(r"item\s*\d\s*\.\s*\d\s*\d\b\.?:?\s*[–—-]?\s*(?=[A-Z])", re.I)
_CROSS_REF = re.compile(r"(?:\b(?:in|under|see|to|and|of|with|per|into|by)\s+)$", re.I)
SECTION_WIDTH = 4000

# Readings, best first: a stated timing (before the open, after the close, a clock time, the last day), then a bare
# suspension date (ruling R8: the trading day before D), then a suspension "immediately on D" (D, unconfirmed).
EXPLICIT_KINDS = frozenset({"8k_open", "8k_open_closing", "8k_close", "8k_close_closing", "8k_close_effective",
                            "8k_open_effective", "8k_close_clock", "8k_open_clock", "8k_last_day"})
_RANK = {**{k: 0 for k in EXPLICIT_KINDS}, "8k_suspended": 1, "8k_suspended_unconfirmed": 2}
OPEN_KINDS = frozenset({"8k_open", "8k_open_closing", "8k_open_effective", "8k_open_clock"})


def _session_on_or_before(d: date) -> date:
    """A stated last trade that falls on no session moves to the trading day before (CNDT 2019: Sunday)."""
    return d if is_trading_day(d) else previous_trading_day(d)


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
# a suspension at a stated clock time ("Trading of the Company's common stock was suspended effective as of
# approximately 4:00 p.m. Eastern Time on September 17, 2020": SPNV 2020); groups: the clock's three, the date
_SUSPENDED_AT = re.compile(rf"suspended (?:effective )?(?:as of|at) (?:approximately |about )?{_CLOCK}[^.;]{{0,40}}?"
                           rf" on {_WDATE}", re.I)


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
    is an index entry; all short, the first mention; the number read with spaces inside it, `evidence.item_mention`),
    each running to the next item heading -- an "Item N.NN" followed by its capitalized title -- rather than to a
    cross-reference ("described in Item 1.01 above", "under Item 1.03 of this Current Report": NOVL 2011, WM 2008),
    or `width` characters."""
    text = text or ""
    out = []
    for m in item_mention("3.01").finditer(text):
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

    m = re.search(rf"{_OPEN}{_VENUE}(?: on)? {_WDATE}", s, re.I)
    if m and clear(m):
        return previous_trading_day(_day(m.group(1))), "8k_open"
    if re.search(rf"{_OPEN}[^.]{{0,40}}?Closing Date", s, re.I) and (cd := _closing_date(flat)):
        return previous_trading_day(cd), "8k_open_closing"
    m = re.search(rf"{_CLOSE}{_VENUE}(?: on)? {_WDATE}", s, re.I)
    if m and clear(m):
        return _session_on_or_before(_day(m.group(1))), "8k_close"
    if re.search(rf"{_CLOSE}[^.]{{0,40}}?Closing Date", s, re.I) and (cd := _closing_date(flat)):
        return _session_on_or_before(cd), "8k_close_closing"
    if re.search(r"(?:after|following) the Effective Time", s, re.I) and re.search(r"suspen|delist|ceas|halt", s, re.I):
        et = _effective_time(flat)
        days = [_day(d) for d in re.findall(_DATE, s)]
        if et is not None and (not days or et[0] in days):
            if et[1] >= CLOSE_MINUTES:
                return _session_on_or_before(et[0]), "8k_close_effective"
            if et[1] < OPEN_MINUTES:
                return previous_trading_day(et[0]), "8k_open_effective"
    # a suspension at a stated clock time on D: at or after the close, D (SPNV 2020's 4:00 p.m.); before the open,
    # the trading day before; during the session, no reading (the time says nothing of a last print)
    m = _SUSPENDED_AT.search(s)
    if m and clear(m) and not _OBLIGATIONS.search(s[max(0, m.start() - 80):m.start()]):
        minute, day = _minutes(*m.group(1, 2, 3)), _day(m.group(4))
        if minute >= CLOSE_MINUTES:
            return _session_on_or_before(day), "8k_close_clock"
        if minute < OPEN_MINUTES:
            return previous_trading_day(day), "8k_open_clock"
    m = re.search(rf"last (?:day of trading|trading day|day (?:on which|that) [^.;]{{0,60}}? traded)[^.;]{{0,40}}?"
                  rf"(?:was|will be|is|would be) {_WDATE}", s, re.I) \
        or re.search(rf"{_DATE},? (?:which|that) (?:was|will be|is|would be) the last (?:full )?(?:day|trading day)",
                     s, re.I) \
        or re.search(rf"(?:continue to be|will be|remain) listed(?: and traded)?{_VENUE} through {_WDATE}", s, re.I)
    if m:
        return _session_on_or_before(_day(m.group(1))), "8k_last_day"
    m = re.search(rf"suspended immediately on {_WDATE}", s, re.I)
    if m:
        return _day(m.group(1)), "8k_suspended_unconfirmed"
    # Ruling R8: "suspended on D" with no timing word means the last trade was the trading day before D.
    m = re.search(rf"suspended(?: (?:from )?trading)?(?: (?:of|in) [^.;]{{0,100}}?)?{_VENUE} on {_WDATE}", s, re.I)
    if m and not _OBLIGATIONS.search(s[max(0, m.start() - 80):m.start()]) and "immediately" not in m.group(0).lower():
        return previous_trading_day(_day(m.group(1))), "8k_suspended"
    # Ruling R8, date first: "On D, ... had been suspended from trading" (CBL 2020). Not with a modal, a completion
    # word, another date or "immediate" between the date and the verb (BMC 2013: the merger closed and trading was
    # suspended the same day; WeWork 2023: suspended immediately).
    m = re.search(rf"\bOn {_WDATE},? (?P<mid>[^;]{{0,400}}?)\b(?:had been|has been|was|were) suspended(?: from trading)?\b",
                  s)
    if m and "immediate" not in s.lower() and not _OBLIGATIONS.search(s[max(0, m.end() - 80):m.end()]) \
            and not _BAD_MID.search(m.group("mid")) and not re.search(_DATE, m.group("mid")):
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
    got = closing_day_read(texts, lo, hi)
    return got[:2] if got else None


def closing_day_read(texts: Iterable[str], lo: date, hi: date) -> tuple[date, str, bool] | None:
    """The day a deal closed, read from its filings, and the last trade day that gives: (day, kind). The closing day
    C is the latest completion the texts state within [lo, hi] -- a defined "Closing Date", "On D, ... completed
    (the merger)", "the closing of the transactions on D", "the evening of D", an effective time stated with a
    clock time; the last trade is C, or the trading day before C when every clock time stated on C is before the
    open (Imclone 2008: 8:28 A.M. on November 24) or C is no session (PNFP 2026: January 1). None when no text states a completion in the window. A tender
    offer's completion or a record date never counts. `closing_day` is this without the last field, whether the day
    is the one before C because a clock time on C is before the open (a text that dates the last trade exactly)."""
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
    before_open = bool(clocks) and all(t < OPEN_MINUTES for t in clocks)
    if before_open or not is_trading_day(c):
        return previous_trading_day(c), CLOSING_DAY, before_open
    return c, CLOSING_DAY, False


def _confirmed(kind: str) -> bool:
    return bool(kind) and not kind.endswith("unconfirmed")


# A notice's own stated timing ("at the close of the trading session on D", "before the opening on D") beats any
# 8-K; its bare suspension date ("was suspended from trading on D": the trading day before D) gives way to an 8-K
# that states the timing and disagrees (TMHC 2026: "following the closing of trading on July 24").
BARE_NOTICE_KINDS = frozenset({"notice_a", "notice_nasdaq"})


def decide_last_trade(*, notice: tuple[date | None, str], eightk: tuple[date | None, str],
                      midas: date | None, halt: date | None) -> LastTrade:
    """The source order over the readings: MIDAS, then a halt (but the 8-K's day when it puts the halt at the open of
    the halt day, ruling R8), the notice's own timing, an 8-K timing that disagrees with the notice's bare date, the
    notice, then the 8-K; a text day that disagrees with the one taken flags `CONFLICT`, an unconfirmed reading
    `UNCONFIRMED`, and nothing at all `NO_DAY`."""
    texts = [d for d, _ in (notice, eightk) if d is not None]

    def pick(day: date, source: str, extra: tuple[str, ...] = ()) -> LastTrade:
        conflict = (CONFLICT,) if any(d != day for d in texts) else ()
        return LastTrade(day, source, extra + conflict)

    (n_day, n_kind), (e_day, e_kind) = notice, eightk
    if midas is not None:
        return pick(midas, MIDAS)
    if halt is not None:
        if e_day is not None and e_kind in OPEN_KINDS and e_day == previous_trading_day(halt):
            # the 8-K says the halt came at the open of the halt day (ruling R8: WM 2008, the regulatory halt "at
            # the NYSE market open on September 26", which the feed stamps 09:30:06): the day before
            return pick(e_day, EIGHTK_301)
        return pick(halt, NASDAQ_HALT)
    if n_day and _confirmed(n_kind):
        if n_kind in BARE_NOTICE_KINDS and e_day and e_kind in EXPLICIT_KINDS and e_day != n_day:
            return pick(e_day, EIGHTK_301)
        return pick(n_day, EX99_NOTICE)
    if e_day and _confirmed(e_kind):
        return pick(e_day, EIGHTK_301)
    if n_day:
        return pick(n_day, EX99_NOTICE, (UNCONFIRMED,))
    if e_day:
        return pick(e_day, EIGHTK_301, (UNCONFIRMED,))
    return LastTrade(None, UNSOURCED, (NO_DAY,))


# -- dating an ending -------------------------------------------------------------
MIDAS_BEFORE_DAYS, MIDAS_AFTER_DAYS, MIDAS_STILL_TRADING_DAYS = 75, 10, 5
EIGHTK_BEFORE_DAYS, EIGHTK_AFTER_DAYS = 60, 5      # single-filing 8-K window (fallback path)
EIGHTK_GROUP_AFTER_DAYS = 15                       # group 8-K window: latest filed + this many days
CLOSING_BEFORE_DAYS = 10            # rule 4 (5d): a closing day stated this long before the Form 25 still counts
CLOSING_TEXT_AFTER_DAYS = 10        # ... read from the 8-Ks filed up to this long after it (CDWC, MYL, IMCL)
CLOSING_FALLBACK_AFTER_DAYS = 3     # no Form 25: a closing day up to this long after the completion 8-K
FALLBACK_COMPLETION_DAYS = 30       # ... the latest 2.01/5.01 8-K filed this long before the last sighting
TAKEN_AFTER_DAYS = 5                # rule 3 (5d): another CUSIP's fails rows this long past a read window


class Dating:
    """Dates one ending (the module docstring's interface). It reads the issuer's 8-K texts and Form 25s through the
    run's EDGAR client, and the two confirmations through their adapters: `midas` (`last_trade_day(ticker, lo, hi)`)
    and `halts` (`deletion_halt(ticker, lo, hi, max_days=)`, `failed_days()`). Either may be None: not asked."""

    def __init__(self, edgar, *, midas=None, halts=None) -> None:
        self.edgar, self.midas, self.halts = edgar, midas, halts

    # -- the entry points -----------------------------------------------------------
    def of_group(self, cik: int, filings: Sequence[EdgarSubmission], group: Sequence[tuple[EdgarSubmission, Form25]],
                 winner: tuple[EdgarSubmission, Form25], *, ticker: str, trading: TradingRecord,
                 continued: bool) -> LastTrade:
        """The last trade of a delisting made of the Form 25 `group` of CIK `cik` (`filings`: its filing list), whose
        `winner` supplies the delisting's exchange and which the security went on after when `continued`.

        The readings: the first notice that states a day (an exchange's 25-NSE first); the best 3.01 8-K reading
        filed in [earliest filing - EIGHTK_BEFORE_DAYS, latest + EIGHTK_GROUP_AFTER_DAYS]; MIDAS over [earliest -
        MIDAS_BEFORE_DAYS, latest effective + MIDAS_AFTER_DAYS] under `ticker` and every ticker the security carried
        then; the halt feed around the text days (else the Form 25 day). Then `decide_last_trade`.

        Rule 4 (5d): a group left undated, not continued, whose winner is an exchange's Form 25 (not the issuer's own,
        not an involuntary (b) removal: it follows the suspension by weeks, TMA 2008) takes the closing day the 8-Ks
        give within CLOSING_BEFORE_DAYS of its earliest filing day F (read from those filed up to
        CLOSING_TEXT_AFTER_DAYS after it), else F itself: source `closing_day`, flagged `UNCONFIRMED` (`worked_out`).
        The closing day never comes before the last day the security's own fails rows show it trading
        (`TradingRecord.trades_until`) when that day is no later than F and the text did not date the closing before
        the open (AVGO 2018, Z 2015; Imclone 2008's 8:28 A.M. stands)."""
        lt = self._group_reading(cik, filings, group, ticker, trading)
        sub, f25 = winner
        if lt.day is not None or continued or sub.form in ISSUER_FORM25_FORMS or is_involuntary(f25):
            return lt
        filed = date.fromisoformat(min(s.filing_date for s, _ in group))
        shown = trading.trades_until()
        got = self._closing_day(cik, filings, filed - timedelta(days=CLOSING_BEFORE_DAYS), filed,
                                date.fromisoformat(shown) if shown else None)
        return replace(got or LastTrade(filed, CLOSING_DAY, (UNCONFIRMED,)), halt_feed_failed=lt.halt_feed_failed)

    def of_fallback(self, cik: int, filings: Sequence[EdgarSubmission], *, ticker: str, ended_by: date,
                    last_seen: date, trading: TradingRecord, merger: bool) -> LastTrade:
        """The last trade of a delisting with no Form 25, dated by the filing `ended_by` (the fallback's dating
        filing) for a security last sighted on `last_seen`.

        The 3.01 8-Ks are read in [ended_by - EIGHTK_BEFORE_DAYS, max(ended_by, last_seen) + EIGHTK_AFTER_DAYS]: a
        suspension notice can follow the bankruptcy 8-K by weeks (VRM 2024); MIDAS stays anchored on `ended_by`. A
        `merger` left undated ends on the closing day its completion 8-K (the latest with item 2.01 or 5.01 filed in
        [last_seen - FALLBACK_COMPLETION_DAYS, last_seen + CLOSING_FALLBACK_AFTER_DAYS]) states (rule 4: FCL 2009,
        SGP 2009), never after the last sighting. Else the last sighting itself, unsourced and `UNCONFIRMED`."""
        lt = self._single_reading(cik, filings, ticker, ended_by, trading, max(ended_by, last_seen))
        if lt.day is None and merger:
            done = [date.fromisoformat(f.filing_date) for f in filings if f.form.startswith("8-K") and f.filing_date
                    and {"2.01", "5.01"} & f.item_set
                    and last_seen - timedelta(days=FALLBACK_COMPLETION_DAYS) <= date.fromisoformat(f.filing_date)
                    <= last_seen + timedelta(days=CLOSING_FALLBACK_AFTER_DAYS)]
            got = self._closing_day(cik, filings, max(done) - timedelta(days=CLOSING_BEFORE_DAYS),
                                    max(done) + timedelta(days=CLOSING_FALLBACK_AFTER_DAYS)) if done else None
            if got is not None and got.day <= last_seen:
                lt = replace(got, halt_feed_failed=lt.halt_feed_failed)
        if lt.day is None:
            lt = LastTrade(last_seen, UNSOURCED, (UNCONFIRMED,), lt.halt_feed_failed)
        return lt

    def from_notice(self, cik: int, filing: Mapping[str, str] | None, lt: LastTrade, *, before: str,
                    effective: str) -> LastTrade:
        """Stage 9c: a handoff continuation row dated by its last sighting (`LAST_SIGHTING`) whose Form 25 (`filing`:
        form, filing_date, accession) has a notice stating a confirmed last day of trading takes that day (source
        `ex99_notice`), provided it is before the successor's first sighting `before` (ISO; blank: no cap) and no
        later than the Form 25's effective date `effective`. Else `lt` itself, unchanged: a row dated another way is
        never read, and neither is a row without a Form 25; an unreadable notice reads as none."""
        if not filing or lt.source != LAST_SIGHTING:
            return lt
        raw = self.edgar.fetch_filing_raw(cik, filing["accession"])
        if not raw:
            return lt
        f25 = parse_form25(raw, accession=filing["accession"], form=filing["form"], filing_date=filing["filing_date"])
        got = decide_last_trade(notice=notice_last_trade(f25), eightk=(None, ""), midas=None, halt=None)
        if not got.confirmed:
            return lt
        if (before and got.day >= date.fromisoformat(before)) or got.day > date.fromisoformat(effective):
            return lt
        return got

    # -- the readings ---------------------------------------------------------------
    def _group_reading(self, cik: int, filings: Sequence[EdgarSubmission],
                       group: Sequence[tuple[EdgarSubmission, Form25]], ticker: str,
                       trading: TradingRecord) -> LastTrade:
        subs = [s for s, _ in group]
        earliest_filed = date.fromisoformat(min(s.filing_date for s in subs))
        latest_filed = date.fromisoformat(max(s.filing_date for s in subs))
        latest_eff = date.fromisoformat(max(effective_date(s.filing_date) for s in subs))
        notice: tuple[date | None, str] = (None, "")
        for _, f25 in sorted(group, key=lambda item: (item[0].form != "25-NSE", item[0].filing_date)):
            n = notice_last_trade(f25)
            if n[0] is not None:
                notice = n
                break
        eightk = self._eightk_window(cik, filings, earliest_filed - timedelta(days=EIGHTK_BEFORE_DAYS),
                                     latest_filed + timedelta(days=EIGHTK_GROUP_AFTER_DAYS), earliest_filed)
        lo = earliest_filed - timedelta(days=MIDAS_BEFORE_DAYS)
        hi = latest_eff + timedelta(days=MIDAS_AFTER_DAYS)
        texts = [d for d, _ in (notice, eightk) if d]
        confirmations = self._confirmations(
            self._tickers(trading, ticker, lo, hi), earliest_filed, lo, hi,
            latest_eff + timedelta(days=MIDAS_STILL_TRADING_DAYS),
            texts or [previous_trading_day(latest_filed), latest_filed], trading, texts)
        return self._decide(notice, eightk, confirmations)

    def _single_reading(self, cik: int, filings: Sequence[EdgarSubmission], ticker: str, filed: date,
                        trading: TradingRecord, eightk_until: date) -> LastTrade:
        """No Form 25: the 3.01 8-Ks in [filed - EIGHTK_BEFORE_DAYS, `eightk_until` + EIGHTK_AFTER_DAYS], MIDAS
        around `filed`, the halt feed around the 8-K's day (else the trading day before `filed`)."""
        notice: tuple[date | None, str] = (None, "")
        eightk = self._eightk_window(cik, filings, filed - timedelta(days=EIGHTK_BEFORE_DAYS),
                                     eightk_until + timedelta(days=EIGHTK_AFTER_DAYS), filed)
        lo, hi = filed - timedelta(days=MIDAS_BEFORE_DAYS), filed + timedelta(days=MIDAS_AFTER_DAYS)
        texts = [d for d, _ in (notice, eightk) if d]
        confirmations = self._confirmations(
            self._tickers(trading, ticker, lo, hi), filed, lo, hi, filed + timedelta(days=MIDAS_STILL_TRADING_DAYS),
            texts or [previous_trading_day(filed)], trading, texts)
        return self._decide(notice, eightk, confirmations)

    def _eightk_window(self, cik: int, filings: Sequence[EdgarSubmission], lo: date, hi: date,
                       anchor: date) -> tuple[date | None, str]:
        """The best last-trade reading (`reading_rank`) of the 3.01 8-Ks filed in [lo, hi], nearest `anchor` first
        among equals; the search stops at the first stated timing."""
        cands = [f for f in filings if f.form.startswith("8-K") and "3.01" in f.item_set
                 and f.filing_date and lo <= date.fromisoformat(f.filing_date) <= hi]
        best: tuple[date | None, str] = (None, "")
        for f in sorted(cands, key=lambda f: abs((date.fromisoformat(f.filing_date) - anchor).days)):
            got = eightk_last_trade(self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc))
            if got[0] is not None and (best[0] is None or reading_rank(got[1]) < reading_rank(best[1])):
                best = got
                if reading_rank(got[1]) == 0:
                    break
        return best

    def _closing_day(self, cik: int, filings: Sequence[EdgarSubmission], lo: date, hi: date,
                     shown: date | None = None) -> LastTrade | None:
        """Rule 4's reading: the closing day the issuer's 8-Ks filed in [lo, hi + CLOSING_TEXT_AFTER_DAYS] give for
        [lo, hi] (`closing_day_read`), source `closing_day`, flagged `UNCONFIRMED` (so the ranges always clip there
        and the contract publishes nothing). `shown`, the last day the security's own fails rows show it trading: a
        closing day before it, one the text did not step back from its stated day, becomes it (never after `hi`)."""
        texts = [self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc) for f in filings
                 if f.form.startswith("8-K") and f.filing_date
                 and lo <= date.fromisoformat(f.filing_date) <= hi + timedelta(days=CLOSING_TEXT_AFTER_DAYS)]
        got = closing_day_read(texts, lo, hi)
        if got is None:
            return None
        day = shown if shown is not None and not got[2] and got[0] < shown <= hi else got[0]
        return LastTrade(day, got[1], (UNCONFIRMED,))

    def _halt_feed_failures(self) -> tuple[date, ...]:
        """The halt feed's failed days so far on this thread (`NasdaqHaltClient.failed_days`)."""
        return tuple(self.halts.failed_days())

    def _confirmations(self, tickers: list[str], filed: date, lo: date, hi: date, still_trading: date,
                       guesses: list[date], trading: TradingRecord, texts: Sequence[date] = ()
                       ) -> tuple[date | None, date | None, tuple[date, ...]]:
        """(MIDAS last day with exchange volume, Nasdaq code-D halt day, halt feed days that failed to read) over
        every ticker in `tickers`: MIDAS (asked when `filed` is in its coverage) takes the latest day in `[lo, hi]`
        before `still_trading` under any of them; the halt feed is asked only when MIDAS has nothing, around the
        text sources' `guesses`.

        Rule 3: a MIDAS or halt day after a text day (`texts`) is the security's own only before another CUSIP began
        trading under that ticker (`TradingRecord.taken`): MIDAS is then read up to the day before (CCEP under CCE
        2016, Johnson Controls plc under JCI 2016, JET's ADS under GRUB 2021), and such a halt is dropped. Without a
        text day that disagrees, nothing is bounded, and the bound is only tried when MIDAS's day under the ticker
        falls before the still-trading cut (a successor's first fails rows can lag its first day: Sinclair Inc 2023,
        new TCF 2019)."""
        first_text = min(texts) if texts else None

        def taken(t: str) -> date | None:
            got = trading.taken(t, lo.isoformat(), (hi + timedelta(days=TAKEN_AFTER_DAYS)).isoformat())
            return date.fromisoformat(got) if got else None

        def read(t: str, until: date) -> date | None:
            m = self.midas.last_trade_day(t, lo, until) if until >= lo else None
            return m if m is not None and m < still_trading else None

        midas = None
        if self.midas is not None and filed >= MIDAS_START:
            days = {t: m for t in tickers if (m := read(t, hi)) is not None}
            for t, m in list(days.items()):
                if first_text is not None and first_text < m and (b := taken(t)) is not None and b <= m:
                    days[t] = read(t, min(hi, previous_trading_day(b)))
            found = [m for m in days.values() if m is not None]
            midas = max(found) if found else None
        halt, failed = None, ()
        if midas is None and self.halts is not None:
            before = len(self._halt_feed_failures())
            for t in tickers:
                h = self.halts.deletion_halt(t, min(guesses) - timedelta(days=2),
                                             max(guesses) + timedelta(days=2), max_days=5)
                if not h:
                    continue
                day = last_trade_from_halt(h)
                if first_text is not None and first_text < day and (b := taken(t)) is not None and b <= day:
                    continue
                halt = day
                break
            failed = self._halt_feed_failures()[before:]
        return midas, halt, failed

    @staticmethod
    def _decide(notice: tuple[date | None, str], eightk: tuple[date | None, str],
                confirmations: tuple[date | None, date | None, tuple[date, ...]]) -> LastTrade:
        """`decide_last_trade` over the text sources and the confirmations, carrying the halt feed days that failed
        to read."""
        midas, halt, failed = confirmations
        lt = decide_last_trade(notice=notice, eightk=eightk, midas=midas, halt=halt)
        return replace(lt, halt_feed_failed=failed) if failed else lt

    @staticmethod
    def _tickers(trading: TradingRecord, ticker: str, lo: date, hi: date) -> list[str]:
        """`ticker` first, then every other ticker the security carried in `[lo, hi]`."""
        return list(dict.fromkeys([ticker, *trading.tickers(lo.isoformat(), hi.isoformat())]))


# -- the handoff stage ------------------------------------------------------------
def handoff_day(a_last: str, b_first: str) -> date:
    """A's last trading day in a continuation (A hands its ticker to B): its last sighting under the ticker, but
    never on or after B's first (a fails row is dated the day after the close it carries, so the two can meet: ST
    2018, AON 2020)."""
    return min(date.fromisoformat(a_last), date.fromisoformat(b_first) - timedelta(days=1))


def at_handoff(lt: LastTrade | None, a_last: str, b_first: str) -> LastTrade:
    """The last trade of A's row in a continuation: a row the handoff stage writes (`lt` None) or a kept row with no
    day takes `handoff_day`, source `last_sighting`, so A's range ends before B's begins (PNFP 2026); a worked-out
    closing day (rule 4) never reaches B's first sighting under the ticker: past `handoff_day`, it becomes that day,
    source `last_sighting`, still unconfirmed. Any other day stands."""
    day = handoff_day(a_last, b_first)
    if lt is None:
        return LastTrade(day, LAST_SIGHTING, ())
    if lt.day is None:
        return replace(lt, day=day, source=LAST_SIGHTING, flags=tuple(f for f in lt.flags if f != NO_DAY))
    if lt.worked_out and lt.day > day:
        return replace(lt, day=day, source=LAST_SIGHTING)
    return lt


# -- the ending's anchor day ----------------------------------------------------------
def anchor_day(lt: LastTrade, delist_date: str, *, filed: str | None = None, anchor_8k: str | None = None) -> date:
    """The day an ending is read around (its anchor): its last trade; else its Form 25's filing date `filed`; else
    the filing date of the 8-K the classifier anchored on `anchor_8k`; else (approximate) its delisting date."""
    if lt.day is not None:
        return lt.day
    for day in (filed, anchor_8k):
        if day:
            return date.fromisoformat(day)
    return date.fromisoformat(delist_date)


def first_day_after(day: date) -> date:
    """The first day a successor the run adds is seen after its predecessor's last trade (or anchor) `day`: the next
    trading day (the 5h OKE fix)."""
    return next_trading_day(day)

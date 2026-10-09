"""Follow a security's line across a CUSIP or ticker change: stage 4b (sub-plan 5a, spec
2026-10-03-diagnosis-truth-fixes, section 3 "5a", rulings R1 and R2).

The caller's observations of a security can stop years before its line ends: the issuer reverse-split (a new CUSIP
under the same ticker), renamed itself (the same CUSIP under a new ticker), or did both. The fails-to-deliver rows
show the line going on. The stage follows each security past its observations, before the Form 25 search reads its
sightings, so a later real ending is found instead of a guess anchored on the old ticker's last row.

The interface is `follow_lines(identity, clients, *, as_of, log, meter) -> Lines`. A caller passes the identity
stage's answer (`identity.Identity`: the securities, each era's resolution, each security's CUSIPs, the fails index)
and the run's clients (`LineSources`: the issuer record, the EDGAR client, EDGAR's full-text search and OpenFIGI). It
gets the securities, resolutions and CUSIPs after the follow, the placeholders folded into a FIGI line (`renames`),
the FIGI lines another composite continues (`successors`, which stage 9 links) and the review items of stages 1 to
4b. Behind it:

- the rounds: up to `MAX_ROUNDS` steps a line (WIN's two reverse splits), each round's new CUSIPs loaded into the
  fails index to the run date and asked of OpenFIGI in one batch;
- the holders: a new CUSIP, or a successor composite, one security took is held for the rest of the round;
- the reads: every issuer read goes through the run's issuer record and its one failure policy (`_Reads`). A failed
  read is never remembered, a refusal (`fatal.FATAL`) or an OpenFIGI outage stops the run, and a degraded read of a
  CIK gives each of that CIK's steps a `resolution_degraded` item, as it does a security with no step;
- the folds: a placeholder folds into the FIGI line its new CUSIP names, and a ticker-tier line into its next CUSIP's
  composite when the ticker answered with today's holder (`_today_holder_fold`, sub-plan 5h).

The rules are functions over what was read. `candidate_steps` finds a line's next step in the fails rows (pure).
`corroborate` checks the step against the issuer's EDGAR record (R1, pure over what the stage read). `decide` applies
R2 (the new CUSIP's OpenFIGI composite) to it. Only `follow_lines` calls them in a run; they stay importable as the
surface of their own tests (tests/test_line_follow.py, and the real-case harness tests/test_line_follow_cases.py).
Stage 9's own-registration link reads `is_line_symbol`, `text_cusips` and `composites` too, since it applies the
same R2 reading to the new CUSIP of a same-CIK 8-K12B.

A step is followed only when the old registrant carries on (R1): it files a periodic report after the step, or the
step is its own successor registration (8-K12B/8-K12G3), and no other registrant's 8-K12B/8-K12G3 names it then.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import requests

from ..sources.capabilities import FullTextSearch
from ..outputs.degraded import DegradedWatch, degraded_item
from ..sources.edgar import EdgarSubmission
from ..filings.evidence import name_at, names_between
from ..sources.fatal import FATAL
from .figi_resolution import FigiCandidate, us_candidates
from ..filings.filing_search import successor_query
from ..sources.ftd import FtdIndex, FtdRow, is_deleted_symbol, is_unassigned_symbol, settled_last
from .issuer_record import IssuerRecord
from ..filings.listing_status import edgar_lists, lists_on_major_exchange
from ..outputs.manifest import StageMeter
from ..vocabulary.names import description_names, names_agree
from ..vocabulary.identifiers import (bare_ticker, class_letter, description_class_letter, is_placeholder,
                                      normalize_ticker)
from ..outputs.review_triage import ReviewItem
from .security_master import SWITCH_DAYS, SWITCH_TAIL_DAYS, EraResolution, Security, cusip_job
from ..vocabulary.trading_calendar import add_trading_days

if TYPE_CHECKING:
    from .identity import Identity

SWITCH, NEW_SYMBOL = "cusip_switch", "new_symbol"
ATTACH, FOLD, SUCCESSOR, REFUSED = "attach", "fold", "successor", "refused"
LINE_DAYS = 10                # trading days either side of the old CUSIP's settled last row
MIN_NEW_ROWS = 3              # fewer fails rows than this under the new CUSIP or symbol are noise
FILING_DAYS = 30              # an 8-K 5.03/3.03, an 8-K text or an 8-K12B this close to the first new row states it
RENAME_DAYS = 90              # an EDGAR rename this close to the first new row states it
BANKRUPTCY_BEFORE_DAYS, BANKRUPTCY_AFTER_DAYS = 180, 30    # an 8-K item 1.03 in this window refuses the step
NAME_DAYS = 30                # the new rows' descriptions must name a name in force this long from the first row
RECENT_DAYS = 120             # a step this close to the run date may have no periodic report after it yet
TEXT_SOURCE_DAYS = 30         # a line whose last row is this close to the run date has not been seen to stop
READ_FAILED = -1              # `other_registrant`: the read failed, nothing is known of another registrant
MAX_ROUNDS = 3                # steps followed per line (WIN's two reverse splits, LPI's switch then rename)
MAX_TEXTS = 5                 # 8-K texts read per step for a reverse split or the new CUSIP
PERIODIC_FORMS = frozenset({"10-K", "10-Q", "20-F", "40-F", "10-KT", "10-QT", "10-K405", "10-KSB", "10-KSB40",
                            "10-QSB"})
SUCCESSOR_FORMS = frozenset({"8-K12B", "8-K12G3"})
_REVERSE_SPLIT = re.compile(r"reverse\s+(?:stock\s+)?split|share\s+consolidation", re.I)
_NOT_COMMON = re.compile(r"pref|warrant|right|unit|\bWRT\b", re.I)     # OpenFIGI securityType of a line that is no common
_SYMBOL = re.compile(r"[A-Z]{1,5}(?:-[A-Z])?")
# "under the ticker symbol “CHX”", "the new trading symbol for the common stock is FNP"; the ticker is upper case
_TEXT_SYMBOL = re.compile(r"(?i:symbol)[^.;]{0,60}?(?:\b(?i:is|to|of|under)\b\s*|[\"“'(])\s*[\"“'(]?([A-Z]{1,5})\b(?![a-z])")
# "our ticker symbol was changed from “RRI” to “GEN,”": the symbol after "to" (sub-plan 5c; the first pattern
# alone reads RRI, the old one)
_TEXT_SYMBOL_CHANGE = re.compile(r"(?i:symbol)[^.;]{0,60}?\b(?i:from)\s+[\"“'(]?[A-Z]{1,5}[\"”')]?,?\s+(?i:to)\s+"
                                 r"[\"“'(]?([A-Z]{1,5})\b(?![a-z])")
_STATE_TAG = re.compile(r"\s*/[A-Z]+/?\s*$")          # EDGAR's "AETNA INC /PA/"
# "the CUSIP number changed to 316645100": a nine-character CUSIP within 60 characters of the word
_TEXT_CUSIP = re.compile(r"(?i:CUSIP)(?:\s*(?i:No)\.)?[^.;]{0,60}?\b([0-9A-Za-z]{8}[0-9])\b")


@dataclass(frozen=True)
class LineStep:
    """One step of a security's line in the fails rows: `kind` SWITCH (a new CUSIP under the line's ticker, its
    first-day "...ZZZZ" symbol, its post-split "...D" symbol, or a new ticker of the issuer) or NEW_SYMBOL (the same
    CUSIP under a new ticker). `old_last` is the old CUSIP's last row under the line's tickers once a fail still
    settling at the last close is set aside (`ftd.settled_last`); `first` is the new rows' first row; `symbol` the
    ticker they trade under; `descriptions` the new rows' descriptions in their first `NAME_DAYS` days."""
    sec_id: str
    kind: str
    old_cusip: str
    new_cusip: str
    symbol: str
    old_last: str
    first: str
    descriptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class LineSuccessor:
    """A FIGI line whose new CUSIP has its own composite (R2: two securities, the new one a continuation): the
    composite, the OpenFIGI candidate it came from, the step and the filing that states it."""
    sec_id: str
    composite: str
    candidate: FigiCandidate
    step: LineStep
    evidence: str


@dataclass(frozen=True)
class Decision:
    """What R2 makes of a step: ATTACH (one security), FOLD (a placeholder into `composite`), SUCCESSOR (a FIGI
    line continued by `composite`) or REFUSED (`why`)."""
    kind: str
    composite: str = ""
    why: str = ""
    candidate: FigiCandidate | None = None


def is_line_symbol(symbol: str) -> bool:
    """A symbol a listed line can trade under: letters, and a class letter after a dash (BF-B). Never a deleted
    "...XXXX" or first-day "...ZZZZ" symbol, a masked or CUSIP-tail one (P105PS), or a when-issued one."""
    return bool(_SYMBOL.fullmatch(symbol or "")) and not is_deleted_symbol(symbol) \
        and not is_unassigned_symbol(symbol)


def is_otc_symbol(symbol: str, tickers: Iterable[str]) -> bool:
    """An over-the-counter symbol after a delisting: five letters ending in Q (bankruptcy), F (foreign) or Y
    (ADR) -- RADCQ, WFTIF -- or one of the line's own tickers with a Q appended (DFQ)."""
    bare = bare_ticker(symbol)
    return (len(bare) == 5 and bare[-1] in "QFY") or any(bare == bare_ticker(t) + "Q" for t in tickers)


def _days(day: str, n: int) -> str:
    return add_trading_days(date.fromisoformat(day), n).isoformat()


def _line_symbol_of(rows: Sequence[FtdRow], tickers: Collection[str], fallback: str) -> str:
    """The ticker a new CUSIP's rows trade under: the first line symbol that is not a post-split "...D" spelling
    of one of the line's tickers (YRCWD for 20 days, then YRCW), else the scanned spelling stripped."""
    post_split = {bare_ticker(t) + "D" for t in tickers}
    for r in rows:
        if is_line_symbol(r.symbol) and r.symbol not in post_split:
            return r.symbol
    for t in tickers:
        if fallback in (bare_ticker(t) + "ZZZZ", bare_ticker(t) + "D"):
            return t
    return fallback


@dataclass(frozen=True)
class LineEnd:
    """Where a security's line stands in the fails rows: the CUSIP of its latest live row under one of its
    tickers (`cusip`), that CUSIP's last such row (`last`) and the row that opens its final run of one price
    (`settled`, `ftd.settled_last`)."""
    cusip: str
    last: str
    settled: str


def line_end(cusips: Sequence[str], tickers: Collection[str], ftd: FtdIndex) -> LineEnd | None:
    """The `LineEnd` of a security with `cusips` and `tickers`; None when no live row of its CUSIPs is under one
    of its tickers."""
    own = set(tickers)
    rows = sorted((r for r in ftd.trading_rows(cusips) if r.symbol in own), key=lambda r: (r.date, r.cusip))
    if not rows:
        return None
    old = [r for r in rows if r.cusip == rows[-1].cusip]
    return LineEnd(old[-1].cusip, old[-1].date, settled_last(old).date)


def _others(holders: Mapping[str, Collection[str]], cusip: str, sec_id: str) -> bool:
    return any(h != sec_id for h in holders.get(cusip, ()))


def _one_switch(switches: Mapping[str, LineStep], tickers: Collection[str]) -> list[LineStep]:
    """The one switch among several candidates: the one under the line's own ticker, else the one with the
    shortest symbol (an issuer's common trades under its shortest ticker: DHC beside its notes DHCNI and DHCNL);
    none when that leaves more than one."""
    picks = list(switches.values())
    if len(picks) > 1:
        picks = [s for s in picks if s.symbol in tickers] or picks
    if len(picks) > 1:
        short = min(len(s.symbol) for s in picks)
        picks = [s for s in picks if len(s.symbol) == short]
    return picks if len(picks) == 1 else []


def candidate_steps(sec_id: str, cusips: Sequence[str], tickers: Collection[str], ftd: FtdIndex, *,
                    holders: Mapping[str, Collection[str]] = {}, extra_symbols: Collection[str] = (),
                    extra_cusips: Collection[str] = (), days: int = LINE_DAYS, data_end: str | None = None) -> list[LineStep]:
    """The next steps of a security's line in the fails rows (pure). Its `line_end` opens a window of `days`
    trading days either side of the settled last row. `holders` maps a CUSIP to the securities of the run that
    hold it.

    - SWITCH: a CUSIP not among `cusips`, whose first row (under any symbol) falls in
      the window and that has at least `MIN_NEW_ROWS` rows, found under one of `tickers`, its "...ZZZZ" or "...D"
      spelling, one of `extra_symbols` (the issuer's other tickers), or among `extra_cusips` (CUSIPs its 8-K text
      names). The one picked (below) is dropped, and no step is taken, when another security holds it. None when
      the old CUSIP's last row is within `SWITCH_TAIL_DAYS` trading days of `data_end` (the last day the fails
      data covers, `FtdIndex.data_end`; the old line has not been seen to stop) and its settled row is more than
      `SWITCH_DAYS` trading days after the new CUSIP's first row (the old line trades on at changing prices beside it: CHTR's
      new preferred; no `data_end`: the rule is off), and None when the old CUSIP trades on past `SWITCH_TAIL_DAYS` after its last row under the tickers (a
      spin-off took the ticker while the old line went on: GOOG, AAN).
    - NEW_SYMBOL: the old CUSIP's first row under a line symbol that is not one of `tickers` and not an OTC
      symbol (`is_otc_symbol`), in the window, with at least `MIN_NEW_ROWS` rows under it. None when another
      security of the run holds the old CUSIP too, or when two symbols qualify.

    Of several switches, the one under the line's own ticker is taken, else the one with the shortest symbol
    (`_one_switch`)."""
    end = line_end(cusips, tickers, ftd)
    if end is None:
        return []
    own = set(tickers)
    lo, hi = _days(end.settled, -days), _days(end.settled, days)
    steps: list[LineStep] = []

    # a live line has no stop for the tail check below to see: at the data's edge a switch needs the old line to
    # have stopped (its settled row no more than SWITCH_DAYS after the new CUSIP's first row)
    at_edge = data_end is not None and end.last >= _days(data_end, -SWITCH_TAIL_DAYS)
    tail = _days(end.last, SWITCH_TAIL_DAYS)
    if not any(r.date > tail for r in ftd.trading_rows([end.cusip])):
        scan = {s for t in own for s in (t, bare_ticker(t) + "ZZZZ", bare_ticker(t) + "D")}
        found = {r.cusip: s for s in sorted(scan | set(extra_symbols)) for r in ftd.by_symbol(s, lo, hi)}
        found.update({c: "" for c in extra_cusips if c not in found})
        switches: dict[str, LineStep] = {}
        for c, s in sorted(found.items()):
            if c in cusips:
                continue
            new_rows = ftd.by_cusip(c)
            if not new_rows or not lo <= new_rows[0].date <= hi or len(new_rows) < MIN_NEW_ROWS:
                continue
            first = new_rows[0].date
            if at_edge and end.settled > _days(first, SWITCH_DAYS):
                continue     # the old line kept trading at changing prices beside the new CUSIP (CHTR's preferred)
            until = (date.fromisoformat(first) + timedelta(days=NAME_DAYS)).isoformat()
            descs = tuple(sorted({x.description for x in new_rows if x.date <= until}))
            switches[c] = LineStep(sec_id, SWITCH, end.cusip, c, _line_symbol_of(new_rows, own, s), end.settled,
                                   first, descs)
        steps += [st for st in _one_switch(switches, own) if not _others(holders, st.new_cusip, sec_id)]

    if not _others(holders, end.cusip, sec_id):
        renamed: dict[str, list[FtdRow]] = {}
        for r in ftd.trading_rows([end.cusip]):
            if r.symbol not in own and is_line_symbol(r.symbol) and not is_otc_symbol(r.symbol, own):
                renamed.setdefault(r.symbol, []).append(r)
        symbols = {s: rs for s, rs in renamed.items() if lo <= rs[0].date <= hi and len(rs) >= MIN_NEW_ROWS}
        if len(symbols) == 1:
            [(s, rs)] = symbols.items()
            steps.append(LineStep(sec_id, NEW_SYMBOL, end.cusip, end.cusip, s, end.settled, rs[0].date,
                                  tuple(sorted({x.description for x in rs[:MIN_NEW_ROWS]}))))
    return sorted(steps, key=lambda st: (st.first, st.kind))


def text_symbols(texts: Iterable[str]) -> set[str]:
    """The ticker symbols an 8-K's text names as the stock's new one ("under the ticker symbol "CHX"", "changed
    from "RRI" to "GEN""), upper-case."""
    return {m.group(1) for t in texts for rx in (_TEXT_SYMBOL, _TEXT_SYMBOL_CHANGE) for m in rx.finditer(t or "")}


def cusip_check_digit_ok(cusip: str) -> bool:
    """Whether the ninth character of `cusip` is its check digit (the CUSIP modulus-10 double-add-double rule)."""
    if len(cusip) != 9 or not cusip[8].isdigit():
        return False
    total = 0
    for i, ch in enumerate(cusip[:8]):
        v = int(ch) if ch.isdigit() else ord(ch) - ord("A") + 10 if ch.isalpha() else None
        if v is None:
            return False
        if i % 2:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10 == int(cusip[8])


def text_cusips(texts: Iterable[str]) -> set[str]:
    """The CUSIP numbers an 8-K's text names (each passing its check digit)."""
    return {c for t in texts for m in _TEXT_CUSIP.finditer(t or "") if cusip_check_digit_ok(c := m.group(1).upper())}


def _filed(f: EdgarSubmission) -> date | None:
    try:
        return date.fromisoformat(f.filing_date[:10])
    except ValueError:
        return None


def _near(filings: Sequence[EdgarSubmission], day: date, before: int, after: int,
          keep: Callable[[EdgarSubmission], bool]) -> list[EdgarSubmission]:
    lo, hi = day - timedelta(days=before), day + timedelta(days=after)
    return [f for f in filings if keep(f) and (d := _filed(f)) is not None and lo <= d <= hi]


def eightks_near(filings: Sequence[EdgarSubmission], day: date,
                 keep: Callable[[EdgarSubmission], bool] = lambda f: True) -> list[EdgarSubmission]:
    """The issuer's 8-Ks within `FILING_DAYS` of `day` that pass `keep`, nearest first, at most `MAX_TEXTS` (the
    filter first, then the cap): the ones whose text may state a reverse split or name the new CUSIP or ticker."""
    near = _near(filings, day, FILING_DAYS, FILING_DAYS, lambda f: f.form.startswith("8-K") and keep(f))
    return sorted(near, key=lambda f: (abs((_filed(f) - day).days), f.filing_date))[:MAX_TEXTS]


def corroborate(step: LineStep, *, filings: Sequence[EdgarSubmission], sub: Mapping | None, share_class: str,
                text_of: Callable[[EdgarSubmission], str], listed_now: Callable[[], bool], as_of: date,
                other_registrant: Callable[[], int | None] = lambda: None) -> tuple[str, str]:
    """(evidence, refusal) for `step` of a line (exactly one is non-empty), from its issuer's filings (`filings`),
    its EDGAR submissions JSON (`sub`), the 8-K texts `text_of` reads (only when no filing code states the change),
    whether its ticker is listed today (`listed_now`, asked only for a recent step), the run date and another CIK
    that filed an 8-K12B/8-K12G3 naming the issuer (`other_registrant`, asked only for a step nothing else
    refused; see `other_registrant()`). Refusals, in order:

    - "bankruptcy": an 8-K item 1.03 in [first - 180, first + 30] days (UAL's 2006 emergence: old shares cancelled);
    - "otc_move" (a new symbol only): an 8-K item 3.01, a Form 25 or a Form 15 within `FILING_DAYS`;
    - "name" (a switch only): no new row's description names (`names.description_names`) a name the issuer
      carried from the first new row on (`evidence.names_between`, `NAME_DAYS`): a ticker passed to another issuer
      (new LMCA 2013, new MSG 2015) carries the old name only as a former one;
    - "class" (a switch only): a new row's description states a class letter other than the line's;
    - "merged_out" (R1): no 10-K/10-Q/20-F/40-F for a period that ends after the first new row (a 10-Q filed
      days after the step reports on the old registrant's past: BXS 2017), the step is not the issuer's own
      8-K12B/8-K12G3 within `FILING_DAYS`, and it is not a step within `RECENT_DAYS` of the run date of a line
      listed today (UNIT 2025: Uniti Group LLC filed a 15-12G and no 10-Q);
    - "other_registrant" (R1): another CIK's 8-K12B/8-K12G3 names the issuer (SBGI 2023's new holding company);
    - "read_failed": `other_registrant` could not read (`READ_FAILED`): nothing is known of another registrant;
    - "no_filing" (a switch only): no 8-K item 5.03 or 3.03, own 8-K12B/8-K12G3 or 8-K text stating a reverse
      split or naming the new CUSIP within `FILING_DAYS`, and no EDGAR rename within `RENAME_DAYS`.

    The evidence names the filing (a new symbol of the same CUSIP needs none: "same CUSIP")."""
    first = date.fromisoformat(step.first)
    if _near(filings, first, BANKRUPTCY_BEFORE_DAYS, BANKRUPTCY_AFTER_DAYS,
             lambda f: f.form.startswith("8-K") and "1.03" in f.item_set):
        return "", "bankruptcy"
    if step.kind == NEW_SYMBOL and _near(filings, first, FILING_DAYS, FILING_DAYS, lambda f: (
            (f.form.startswith("8-K") and "3.01" in f.item_set) or f.form.startswith("25") or f.form.startswith("15"))):
        return "", "otc_move"
    if step.kind == SWITCH:
        lo = first
        names = names_between(sub, lo, lo + timedelta(days=NAME_DAYS)) if isinstance(sub, Mapping) else []
        if not any(description_names(d, n) for d in step.descriptions for n in names):
            return "", "name"
        own = class_letter(share_class)
        if own and any((letter := description_class_letter(d)) and letter != own
                       for d in step.descriptions):
            return "", "class"
    own_successor = _near(filings, first, FILING_DAYS, FILING_DAYS, lambda f: f.form in SUCCESSOR_FORMS)
    periodic = any(f.form.split("/")[0] in PERIODIC_FORMS and (f.report_date or "")[:10] > step.first
                   for f in filings)
    if not (periodic or own_successor or ((as_of - first).days <= RECENT_DAYS and listed_now())):
        return "", "merged_out"
    other = other_registrant()
    if other == READ_FAILED:
        return "", "read_failed"
    if other is not None:
        return "", "other_registrant"
    if step.kind == NEW_SYMBOL:
        return "same CUSIP", ""
    coded = _near(filings, first, FILING_DAYS, FILING_DAYS,
                  lambda f: f.form.startswith("8-K") and bool({"5.03", "3.03"} & f.item_set))
    if coded:
        f = min(coded, key=lambda f: abs((_filed(f) - first).days))
        return f"8-K {f.items} {f.filing_date}", ""
    if own_successor:
        f = min(own_successor, key=lambda f: abs((_filed(f) - first).days))
        return f"{f.form} {f.filing_date}", ""
    for fn in (sub.get("formerNames") or []) if isinstance(sub, Mapping) else ():
        to = (fn.get("to") or "")[:10]
        if to and abs((date.fromisoformat(to) - first).days) <= RENAME_DAYS:
            return f"renamed from {fn.get('name')} {to}", ""
    for f in eightks_near(filings, first):
        text = text_of(f) or ""
        if _REVERSE_SPLIT.search(text) or step.new_cusip in re.sub(r"\s+", "", text).upper():
            return f"8-K text {f.filing_date}", ""
    return "", "no_filing"


def name_on(sub: Mapping | None, day: date, fallback: str = "") -> str:
    """The issuer's EDGAR name on `day` (`evidence.name_at`) without EDGAR's state tag, else `fallback`: what
    another registrant's 8-K12B would have called it then."""
    name = name_at(sub, day) if isinstance(sub, Mapping) else ""
    return _STATE_TAG.sub("", name or "").strip() or fallback


def other_registrant(search: Callable | None, edgar, *, name: str, day: date, cik: int,
                     own_tickers: Collection[str]) -> int | None:
    """Another CIK whose 8-K12B/8-K12G3 names `name` in the successor search's window around `day`
    (`filing_search.successor_query`): a new registrant took the old one's place (R1). A filer that is another
    issuer's own, still-listed stock is skipped, as `successors.successor_from_8k12b` skips it: its EDGAR name
    does not agree with `name`, none of its tickers is one of `own_tickers`, and EDGAR lists one of them on a major
    exchange today (iHeartMedia's 8-K12G3 names its subsidiary Clear Channel Outdoor). None without a search;
    `READ_FAILED` when a read failed (`fatal.FATAL` is re-raised): the search counted itself degraded on this
    thread (`degraded.DegradedWatch`: production's `EdgarClient.full_text_search` answers [] for a failed read and
    counts it, so its "no hits" is no answer), or the search or a filer's listing raised. A filer's listing answered
    from a stale copy is an answer: it decides, and the caller's watch reports the step degraded."""
    if search is None or not name:
        return None
    try:
        own = {normalize_ticker(t) for t in own_tickers}
        watch = DegradedWatch()
        hits = search(*successor_query(name, day))
        if watch.tripped():
            return READ_FAILED
        for h in hits:
            src = h.get("_source", h)
            for cik_s, disp in zip(src.get("ciks") or [], src.get("display_names") or []):
                other = int(cik_s)
                if other == cik:
                    continue
                m = re.search(r"\(([^()]*)\)\s*\(CIK\s+\d+\)\s*$", disp)
                tickers = [normalize_ticker(t) for t in m.group(1).split(",") if t.strip()] if m else []
                edgar_name = disp[: m.start()].strip() if m else re.sub(r"\s*\(CIK\s+\d+\)\s*$", "", disp).strip()
                if (tickers and not names_agree(name, edgar_name) and not own & set(tickers)
                        and edgar_lists(edgar, other, tickers)):
                    continue
                return other
        return None
    except FATAL:
        raise
    except requests.RequestException:
        return READ_FAILED


def composites(answer: Mapping) -> list[FigiCandidate] | None:
    """The US composites OpenFIGI gives a CUSIP job's `answer`; None for an error answer (nothing settled)."""
    if "error" in answer:
        return None
    return us_candidates(answer.get("data") or [])


def decide(step: LineStep, sec: Security, cands: list[FigiCandidate] | None,
           securities: Mapping[str, Security]) -> Decision:
    """R2 for `step` of security `sec`: a new symbol of the same CUSIP is the same security (ATTACH). A switch
    follows its new CUSIP's US composites (`cands`): none, or `sec`'s own, ATTACH; several, or an OpenFIGI error,
    REFUSED "unsettled"; one other composite X: REFUSED "type" when OpenFIGI types it a preferred, warrant (also "Equity WRT"), right
    or unit (CHTR's new preferred CHTRP), REFUSED "other_issuer" when a security of the run of another
    issuer holds X, REFUSED "class" when one of another share class does, else FOLD into X for a placeholder (the
    truth set's reading of R2 for a line with no composite) and SUCCESSOR X for a FIGI line."""
    if step.kind == NEW_SYMBOL:
        return Decision(ATTACH)
    if cands is None or len(cands) > 1:
        return Decision(REFUSED, why="unsettled")
    if not cands or cands[0].composite == sec.sec_id:
        return Decision(ATTACH, cands[0].composite if cands else "", candidate=cands[0] if cands else None)
    x = cands[0]
    if _NOT_COMMON.search(x.security_type):
        return Decision(REFUSED, x.composite, "type", x)
    holder = securities.get(x.composite)
    if holder is not None and holder.issuer_cik is not None and holder.issuer_cik != sec.issuer_cik:
        return Decision(REFUSED, x.composite, "other_issuer", x)
    if holder is not None and holder.share_class != sec.share_class:
        return Decision(REFUSED, x.composite, "class", x)
    return Decision(FOLD if is_placeholder(sec.sec_id) else SUCCESSOR, x.composite, candidate=x)


# --- the stage: `follow_lines` -----------------------------------------------------------------------------------

LINE_FOLLOWED, LINE_REFUSED = "line_followed", "line_follow_refused"


class LineSources(Protocol):
    """What `follow_lines` reads through (`pipeline.Clients` has it all)."""
    issuers: IssuerRecord     # the run's issuer record: every issuer's submissions, filing list and 8-K texts
    edgar: Any                # the EDGAR client: a successor filer's listing
    full_text_search: FullTextSearch | None     # EDGAR full-text search (None: absent, no other registrant is found)
    figi: Any                 # OpenFIGI: `map(jobs)`, the new CUSIPs' composites


@dataclass
class Lines:
    """`follow_lines`' answer: the securities, each era's resolution and each security's CUSIPs after the line
    follow; the placeholders folded into a FIGI line (old sec_id -> the FIGI; a fold of a fold points at the last
    FIGI); the FIGI lines another composite continues (sec_id -> `LineSuccessor`, linked by stage 9); and the review
    items of stages 1 to 4b, the identity stage's first, a folded placeholder's moved to its FIGI line (its `no_figi`
    item dropped: it holds a FIGI after all)."""
    securities: dict[str, Security]
    resolutions: dict[str, EraResolution]
    cusips: dict[str, list[str]]
    renames: dict[str, str] = field(default_factory=dict)
    successors: dict[str, LineSuccessor] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)


class _Reads:
    """The stage's EDGAR reads, in one place. The issuers' submissions, filing lists and 8-K texts go through the
    run's issuer record and its failure policy: a failed read is unknown ([], None, "") and never remembered, and a
    refusal stops the run. The other-registrant search and its filer's listing (`other_registrant`) answer
    `READ_FAILED` for a failed read. A CIK is degraded when one of its issuer reads in the stage failed or was
    stale, or when its other-registrant search failed."""

    def __init__(self, clients: LineSources) -> None:
        self.issuers, self._edgar = clients.issuers, clients.edgar
        self._search = clients.full_text_search
        self._stage = self.issuers.watch()          # every issuer read of the stage
        self._search_failed: set[int] = set()       # the CIKs whose other-registrant search failed

    def degraded(self, cik: int | None) -> bool:
        return cik in self._stage.ciks or cik in self._search_failed

    def listed_symbols(self, cik: int) -> set[str]:
        """The line symbols among the tickers EDGAR lists for the issuer today."""
        sub = self.issuers.profile(cik)
        listed = [normalize_ticker(t) for t in (sub.get("tickers") or [])] if isinstance(sub, dict) else []
        return {t for t in listed if is_line_symbol(t)}

    def text_sources(self, s: Security, end: LineEnd) -> tuple[set[str], set[str]]:
        """The tickers and CUSIPs the issuer's own 8-Ks around a line's end name as the stock's new ones (APY's
        ChampionX "CHX", Liz Claiborne's "316645100" and "FNP"): read only when one of them is an 8-K item 5.03
        or 3.03 or an 8-K12B/8-K12G3, within `FILING_DAYS` of the line's settled last row (the filter before the
        `MAX_TEXTS` cap: a busy issuer's coded 8-K is read)."""
        near = eightks_near(self.issuers.filings(s.issuer_cik), date.fromisoformat(end.settled),
                            lambda f: f.form in SUCCESSOR_FORMS or bool({"5.03", "3.03"} & f.item_set))
        texts = [self.issuers.text(s.issuer_cik, f) for f in near]
        return {t for t in text_symbols(texts) if is_line_symbol(t)} - s.own_tickers(), text_cusips(texts)

    def corroborate(self, step: LineStep, s: Security, tickers: set[str], as_of: date) -> tuple[str, str]:
        """`corroborate` for a step of security `s` (its line's `tickers`), from the issuer's record."""
        cik, first = s.issuer_cik, date.fromisoformat(step.first)
        return corroborate(
            step, filings=self.issuers.filings(cik), sub=self.issuers.profile(cik), share_class=s.share_class,
            text_of=lambda f: self.issuers.text(cik, f), as_of=as_of,
            listed_now=lambda: lists_on_major_exchange(self.issuers.profile(cik), sorted(tickers | {step.symbol})),
            other_registrant=lambda: self._other_registrant(cik, name_on(self.issuers.profile(cik), first, s.name),
                                                            first, tickers))

    def _other_registrant(self, cik: int, name: str, day: date, tickers: set[str]) -> int | None:
        other = other_registrant(self._search, self._edgar, name=name, day=day, cik=cik, own_tickers=tickers)
        if other == READ_FAILED:
            self._search_failed.add(cik)
        return other


def _cusip_holders(cusips: Mapping[str, Sequence[str]]) -> dict[str, set[str]]:
    holders: dict[str, set[str]] = defaultdict(set)
    for sid, held in cusips.items():
        for c in held:
            holders[c].add(sid)
    return holders


def _fold(out: Lines, p: str, x: str, cand: FigiCandidate, step: LineStep, tickers: dict[str, set[str]]) -> None:
    """Fold `p` into the FIGI line `x` its new CUSIP's composite names: its eras resolve to `x` (source `handoff`,
    as a CUSIP handoff joins a line in stage 3), its CUSIPs and line tickers join `x`'s, and every earlier rename to
    `p` now points at `x`."""
    for e in out.securities[p].eras:
        out.resolutions[e.key] = replace(out.resolutions[e.key], sec_id=x, source="handoff", candidate=cand, flags=())
    out.cusips[x] = list(dict.fromkeys([*out.cusips.get(x, []), *out.cusips.pop(p, []), step.new_cusip]))
    tickers[x] = tickers.get(x, set()) | tickers.pop(p, set()) | {step.symbol}
    for old, now in list(out.renames.items()):
        if now == p:
            out.renames[old] = x
    out.renames[p] = x


def _today_holder_fold(decision: Decision | None, s: Security, resolutions: Mapping[str, EraResolution],
                       tickers: Collection[str]) -> Decision | None:
    """A SUCCESSOR decision made a FOLD (sub-plan 5h, R2): the line's composite came from the ticker tier alone
    (its CUSIPs have none of their own), that candidate is today's holder of one of the line's tickers, and the
    step's new composite has left them (its ticker today is another): the ticker answered with the line that took
    the ticker over later, and the line's own next CUSIP names its real composite. California Resources' 2014 era
    took CRC's post-2020 line BBG00Y04KP80 by ticker, while its 2016 reverse split's CUSIP is BBG0060B3M63 (CRCQQ
    after the 2020 bankruptcy); Peabody's took BTU's post-2017 line, its 2015 split's being BTUUQ's. A line whose
    ticker candidate left the ticker (an old line OpenFIGI still lists under it) keeps its successor."""
    if decision is None or decision.kind != SUCCESSOR or decision.candidate is None or s.figi_source != "ticker":
        return decision
    picks = [r.candidate for e in s.eras if (r := resolutions.get(e.key)) is not None and r.source == "ticker"
             and r.candidate is not None]
    own = {normalize_ticker(t) for t in tickers}
    if not picks or any(normalize_ticker(c.ticker) not in own for c in picks) \
            or normalize_ticker(decision.candidate.ticker) in own:
        return decision
    return Decision(FOLD, decision.composite, candidate=decision.candidate)


def _quiet(*_: Any) -> None:
    return None


def follow_lines(identity: "Identity", clients: LineSources, *, as_of: date,
                 log: Callable[[str], None] = _quiet, meter: StageMeter | None = None) -> Lines:
    """Stage 4b: each security of `identity` followed past its observations (module docstring), as of the run date
    `as_of`; `log` takes the stage's tally, `meter` its SEC traffic ("line follow"). The fails rows it reads, it
    asks the identity's index to follow (`FtdIndex.follow`: their rows over the run's fails window, to the run
    date): every line's tickers, spellings and issuer tickers first, each round's new CUSIPs and text symbols next.

    A round finds each line's next step in the fails rows (`candidate_steps`: a new CUSIP under the line's ticker,
    or a ticker of the issuer EDGAR lists today or its 8-K text names (`_Reads.text_sources`, read in the first
    round for a line with no step that stopped more than `TEXT_SOURCE_DAYS` before the run date); or the same CUSIP
    under a new ticker), has the index follow the new CUSIPs, asks OpenFIGI for their composites in one
    batch, checks each step against the issuer's filings (`corroborate`) and applies R2 (`decide`, then
    `_today_holder_fold`): the same security takes the new CUSIP and ticker; a placeholder folds into the FIGI line
    its new CUSIP names (the securities are rebuilt, `Identity.securities_of`); a FIGI line whose new CUSIP has its
    own composite keeps its CUSIPs and records that composite as its line successor. A new CUSIP one security
    attached or folded into, or a successor composite one took, is refused `taken` to the next in the round (sec_id
    order). A line that moved is followed again in the next round, up to `MAX_ROUNDS`. Every step followed or
    refused is an info review item (`line_followed`, `line_follow_refused:<why>`); a step whose reads rested on a
    failed request or a stale copy, or of a CIK one of whose reads in the stage did, gets a `resolution_degraded`
    one, and so does a security with no such step whose CIK's read did. A refusal (`fatal.FATAL`) or an OpenFIGI
    outage stops it. `identity` is left as it was (final review M7): a security the follow changes is a copy in
    `Lines`; only its fails index, which the stage asks to follow, holds more rows after."""
    meter = meter if meter is not None else StageMeter(log)
    mark = meter.start()
    reads = _Reads(clients)
    ftd = identity.ftd
    out = Lines(dict(identity.securities), dict(identity.resolutions),
                {k: list(v) for k, v in identity.cusips.items()})
    items: list[ReviewItem] = []
    tickers: dict[str, set[str]] = {sid: set(s.line_tickers) for sid, s in identity.securities.items()}

    def own(sid: str) -> set[str]:
        return out.securities[sid].own_tickers() | tickers.get(sid, set())

    todo = sorted(sid for sid, s in out.securities.items() if s.issuer_cik is not None)
    extra: dict[str, set[str]] = {sid: reads.listed_symbols(out.securities[sid].issuer_cik) - own(sid)
                                  for sid in todo}
    # every line's tickers, their first-day ZZZZ and post-split D spellings and the issuers' other tickers, to the
    # run date (stage 1 loaded the eras' tickers only to 400 days past their last observation)
    spellings = {bare_ticker(t) + suffix for sid in todo for t in own(sid) for suffix in ("", "ZZZZ", "D")}
    ftd.follow(symbols=spellings | {t for v in extra.values() for t in v})
    named: dict[str, set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()
    flagged: set[str] = set()            # securities whose step already got a resolution_degraded item
    for round_no in range(1, MAX_ROUNDS + 1):
        holders = _cusip_holders(out.cusips)

        def steps_of(sid: str) -> list[LineStep]:
            return candidate_steps(sid, out.cusips.get(sid, []), own(sid), ftd, holders=holders,
                                   extra_symbols=extra.get(sid, ()), extra_cusips=named.get(sid, ()),
                                   data_end=ftd.data_end())

        steps = {sid: steps_of(sid) for sid in todo}
        new_symbols: set[str] = set()
        if round_no == 1:
            stopped = (as_of - timedelta(days=TEXT_SOURCE_DAYS)).isoformat()
            for sid in todo:
                end = line_end(out.cusips.get(sid, []), own(sid), ftd)
                if steps[sid] or end is None or end.last >= stopped:
                    continue
                symbols, cusips = reads.text_sources(out.securities[sid], end)
                extra[sid] |= symbols
                named[sid] |= cusips
                new_symbols |= symbols
        new_cusips = {st.new_cusip for v in steps.values() for st in v if st.kind == SWITCH}
        new_cusips |= {c for v in named.values() for c in v}
        if new_cusips or new_symbols:
            ftd.follow(cusips=new_cusips, symbols=new_symbols)
            steps = {sid: steps_of(sid) for sid in todo}
        switch_cusips = sorted({v[0].new_cusip for v in steps.values() if v and v[0].kind == SWITCH})
        figi_answers = dict(zip(switch_cusips, clients.figi.map([cusip_job(c) for c in switch_cusips]))) \
            if switch_cusips else {}
        moved: set[str] = set()
        taken: dict[str, str] = {}       # a new CUSIP or successor composite a security took this round: its holder
        for sid in todo:
            if not steps[sid] or sid not in out.securities:
                continue
            step, s = steps[sid][0], out.securities[sid]
            cik = s.issuer_cik
            watch = reads.issuers.watch()          # this step's reads
            evidence, refused = reads.corroborate(step, s, own(sid), as_of)
            what = f"{step.old_cusip} -> {step.new_cusip} under {step.symbol} from {step.first}"
            decision = None if refused else decide(
                step, s, composites(figi_answers[step.new_cusip]) if step.kind == SWITCH else None, out.securities)
            decision = _today_holder_fold(decision, s, out.resolutions, own(sid))
            if decision is not None and decision.kind == REFUSED:
                refused = decision.why
            elif decision is not None and decision.kind in (ATTACH, FOLD) and step.kind == SWITCH \
                    and taken.setdefault(step.new_cusip, decision.composite or sid) != (decision.composite or sid):
                refused = "taken"     # another security of the run took this CUSIP earlier in the round
            elif decision is not None and decision.kind == SUCCESSOR \
                    and taken.setdefault(decision.composite, sid) != sid:
                refused = "taken"     # ... or this successor composite
            if watch.tripped() or reads.degraded(cik):
                flagged.add(sid)
                items.append(degraded_item(sid, step.symbol, cik, f"the line follow ({what})",
                                           "; run again once SEC answers", last_seen=step.old_last))
            if refused:
                counts[f"refused:{refused}"] += 1
                items.append(ReviewItem(sid, step.symbol, cik, f"{LINE_REFUSED}:{refused}",
                                        f"{what}: not followed ({refused})", last_seen=step.old_last))
                continue
            counts[decision.kind] += 1
            if decision.kind == ATTACH:
                if step.kind == SWITCH:
                    out.cusips.setdefault(sid, []).append(step.new_cusip)
                tickers.setdefault(sid, set()).add(step.symbol)
                moved.add(sid)
                result = "the same security"
            elif decision.kind == FOLD:
                _fold(out, sid, decision.composite, decision.candidate, step, tickers)
                moved.add(decision.composite)
                result = f"folded into {decision.composite}"
            else:
                out.successors[sid] = LineSuccessor(sid, decision.composite, decision.candidate, step, evidence)
                result = f"continued by {decision.composite}"
            items.append(ReviewItem(sid, step.symbol, cik, LINE_FOLLOWED, f"{what} ({evidence}): {result}",
                                    last_seen=step.old_last))
        if any(sid in out.renames for sid in out.securities):
            out.securities = identity.securities_of(out.resolutions)
        for sid, s in list(out.securities.items()):          # a copy of each security the follow changes
            line = frozenset(tickers.get(sid, set()) - {e.ticker for e in s.eras})
            if line != s.line_tickers:
                out.securities[sid] = replace(s, line_tickers=line)
        todo = sorted(sid for sid in moved if sid in out.securities)
        if not todo:
            break
    for sid, s in sorted(out.securities.items()):       # a failed read that left no step: its answer still rested on it
        if reads.degraded(s.issuer_cik) and sid not in flagged:
            items.append(degraded_item(sid, min(own(sid), default=""), s.issuer_cik, "the line follow",
                                       "; run again once SEC answers"))
    # a folded placeholder's review items follow it to its FIGI line, where it holds a FIGI after all
    out.review = [replace(r, sec_id=out.renames.get(r.sec_id, r.sec_id)) for r in [*identity.review, *items]
                  if not (r.flag == "no_figi" and r.sec_id in out.renames)]
    log(f"line follow: {dict(sorted(counts.items()))}; {len(out.renames)} placeholders folded, "
        f"{len(out.successors)} line successors")
    meter.done("line follow", mark)
    return out

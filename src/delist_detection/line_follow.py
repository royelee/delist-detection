"""Follow a security's line across a CUSIP or ticker change (sub-plan 5a, spec 2026-10-03-diagnosis-truth-fixes,
section 3 "5a", rulings R1 and R2).

The caller's observations of a security can stop years before its line ends: the issuer reverse-split (a new CUSIP
under the same ticker), renamed itself (the same CUSIP under a new ticker), or did both. The fails-to-deliver rows
show the line going on. `candidate_steps` finds, for one security, the next step of its line in those rows (pure);
`corroborate` checks the step against the issuer's EDGAR record (pure, over what the caller read); `decide` applies
R2 (the new CUSIP's OpenFIGI composite) to the step. The pipeline's stage 4b (`pipeline._follow_lines`) runs them,
up to `MAX_ROUNDS` steps a line, before the Form 25 search.

A step is followed only when the old registrant carries on (R1): it files a periodic report after the step, or the
step is its own successor registration (8-K12B/8-K12G3), and no other registrant's 8-K12B/8-K12G3 names it then.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .edgar import EdgarSubmission
from .evidence import name_at, names_between
from .figi_resolution import FigiCandidate, class_letter, is_placeholder, share_class_from_name, us_candidates
from .ftd import FtdIndex, FtdRow, is_deleted_symbol, is_unassigned_symbol, settled_last
from .listing_status import edgar_lists
from .names import description_names, names_agree
from .observations import normalize_ticker
from .security_master import SWITCH_TAIL_DAYS, Security
from .successors import successor_query
from .trading_calendar import add_trading_days

SWITCH, NEW_SYMBOL = "cusip_switch", "new_symbol"
ATTACH, FOLD, SUCCESSOR, REFUSED = "attach", "fold", "successor", "refused"
LINE_DAYS = 10                # trading days either side of the old CUSIP's settled last row
MIN_NEW_ROWS = 3              # fewer fails rows than this under the new CUSIP or symbol are noise
FILING_DAYS = 30              # an 8-K 5.03/3.03, an 8-K text or an 8-K12B this close to the first new row states it
RENAME_DAYS = 90              # an EDGAR rename this close to the first new row states it
BANKRUPTCY_BEFORE_DAYS, BANKRUPTCY_AFTER_DAYS = 180, 30    # an 8-K item 1.03 in this window refuses the step
NAME_DAYS = 30                # the new rows' descriptions must name a name in force this long from the first row
RECENT_DAYS = 120             # a step this close to the run date may have no periodic report after it yet
MAX_ROUNDS = 3                # steps followed per line (WIN's two reverse splits, LPI's switch then rename)
MAX_TEXTS = 5                 # 8-K texts read per step for a reverse split or the new CUSIP
PERIODIC_FORMS = frozenset({"10-K", "10-Q", "20-F", "40-F", "10-KT", "10-QT"})
SUCCESSOR_FORMS = frozenset({"8-K12B", "8-K12G3"})
_REVERSE_SPLIT = re.compile(r"reverse\s+(?:stock\s+)?split|share\s+consolidation", re.I)
_SYMBOL = re.compile(r"[A-Z]{1,5}(?:-[A-Z])?")
# "under the ticker symbol “CHX”", "the new trading symbol for the common stock is FNP"; the ticker is upper case
_TEXT_SYMBOL = re.compile(r"(?i:symbol)[^.;]{0,60}?(?:\b(?i:is|to|of|under)\b\s*|[\"“'(])\s*[\"“'(]?([A-Z]{1,5})\b(?![a-z])")
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
    bare = symbol.replace("-", "")
    return (len(bare) == 5 and bare[-1] in "QFY") or any(bare == t.replace("-", "") + "Q" for t in tickers)


def _days(day: str, n: int) -> str:
    return add_trading_days(date.fromisoformat(day), n).isoformat()


def _line_symbol_of(rows: Sequence[FtdRow], tickers: Collection[str], fallback: str) -> str:
    """The ticker a new CUSIP's rows trade under: the first line symbol that is not a post-split "...D" spelling
    of one of the line's tickers (YRCWD for 20 days, then YRCW), else the scanned spelling stripped."""
    post_split = {t.replace("-", "") + "D" for t in tickers}
    for r in rows:
        if is_line_symbol(r.symbol) and r.symbol not in post_split:
            return r.symbol
    for t in tickers:
        if fallback in (t.replace("-", "") + "ZZZZ", t.replace("-", "") + "D"):
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
                    extra_cusips: Collection[str] = (), days: int = LINE_DAYS) -> list[LineStep]:
    """The next steps of a security's line in the fails rows (pure). Its `line_end` opens a window of `days`
    trading days either side of the settled last row. `holders` maps a CUSIP to the securities of the run that
    hold it.

    - SWITCH: a CUSIP not among `cusips` and held by no other security, whose first row (under any symbol) falls in
      the window and that has at least `MIN_NEW_ROWS` rows, found under one of `tickers`, its "...ZZZZ" or "...D"
      spelling, one of `extra_symbols` (the issuer's other tickers), or among `extra_cusips` (CUSIPs its 8-K text
      names). None when the old CUSIP trades on past `SWITCH_TAIL_DAYS` after its last row under the tickers (a
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

    tail = _days(end.last, SWITCH_TAIL_DAYS)
    if not any(r.date > tail for r in ftd.trading_rows([end.cusip])):
        scan = {s for t in own for s in (t, t.replace("-", "") + "ZZZZ", t.replace("-", "") + "D")}
        found = {r.cusip: s for s in sorted(scan | set(extra_symbols)) for r in ftd.by_symbol(s, lo, hi)}
        found.update({c: "" for c in extra_cusips if c not in found})
        switches: dict[str, LineStep] = {}
        for c, s in sorted(found.items()):
            if c in cusips or _others(holders, c, sec_id):
                continue
            new_rows = ftd.by_cusip(c)
            if not new_rows or not lo <= new_rows[0].date <= hi or len(new_rows) < MIN_NEW_ROWS:
                continue
            first = new_rows[0].date
            until = (date.fromisoformat(first) + timedelta(days=NAME_DAYS)).isoformat()
            descs = tuple(sorted({x.description for x in new_rows if x.date <= until}))
            switches[c] = LineStep(sec_id, SWITCH, end.cusip, c, _line_symbol_of(new_rows, own, s), end.settled,
                                   first, descs)
        steps += _one_switch(switches, own)

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
    """The ticker symbols an 8-K's text names as the stock's new one ("under the ticker symbol "CHX""),
    upper-case."""
    return {m.group(1) for t in texts for m in _TEXT_SYMBOL.finditer(t or "")}


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


def eightks_near(filings: Sequence[EdgarSubmission], day: date) -> list[EdgarSubmission]:
    """The issuer's 8-Ks within `FILING_DAYS` of `day`, nearest first, at most `MAX_TEXTS`: the ones whose text
    may state a reverse split or name the new CUSIP or ticker."""
    near = _near(filings, day, FILING_DAYS, FILING_DAYS, lambda f: f.form.startswith("8-K"))
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
        if own and any((letter := class_letter(share_class_from_name(d))) and letter != own
                       for d in step.descriptions):
            return "", "class"
    own_successor = _near(filings, first, FILING_DAYS, FILING_DAYS, lambda f: f.form in SUCCESSOR_FORMS)
    periodic = any(f.form.split("/")[0] in PERIODIC_FORMS and (f.report_date or "")[:10] > step.first
                   for f in filings)
    if not (periodic or own_successor or ((as_of - first).days <= RECENT_DAYS and listed_now())):
        return "", "merged_out"
    if other_registrant() is not None:
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
    (`successors.successor_query`): a new registrant took the old one's place (R1). A filer that is another
    issuer's own, still-listed stock is skipped, as `successors.successor_from_8k12b` skips it: its EDGAR name
    does not agree with `name`, none of its tickers is one of `own_tickers`, and EDGAR lists one of them on a major
    exchange today (iHeartMedia's 8-K12G3 names its subsidiary Clear Channel Outdoor). None without a search."""
    if search is None or not name:
        return None
    own = {normalize_ticker(t) for t in own_tickers}
    for h in search(*successor_query(name, day)):
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


def composites(answer: Mapping) -> list[FigiCandidate] | None:
    """The US composites OpenFIGI gives a CUSIP job's `answer`; None for an error answer (nothing settled)."""
    if "error" in answer:
        return None
    return us_candidates(answer.get("data") or [])


def decide(step: LineStep, sec: Security, cands: list[FigiCandidate] | None,
           securities: Mapping[str, Security]) -> Decision:
    """R2 for `step` of security `sec`: a new symbol of the same CUSIP is the same security (ATTACH). A switch
    follows its new CUSIP's US composites (`cands`): none, or `sec`'s own, ATTACH; several, or an OpenFIGI error,
    REFUSED "unsettled"; one other composite X: REFUSED "other_issuer" when a security of the run of another
    issuer holds X, REFUSED "class" when one of another share class does, else FOLD into X for a placeholder (the
    truth set's reading of R2 for a line with no composite) and SUCCESSOR X for a FIGI line."""
    if step.kind == NEW_SYMBOL:
        return Decision(ATTACH)
    if cands is None or len(cands) > 1:
        return Decision(REFUSED, why="unsettled")
    if not cands or cands[0].composite == sec.sec_id:
        return Decision(ATTACH, cands[0].composite if cands else "", candidate=cands[0] if cands else None)
    x = cands[0]
    holder = securities.get(x.composite)
    if holder is not None and holder.issuer_cik is not None and holder.issuer_cik != sec.issuer_cik:
        return Decision(REFUSED, x.composite, "other_issuer", x)
    if holder is not None and holder.share_class != sec.share_class:
        return Decision(REFUSED, x.composite, "class", x)
    return Decision(FOLD if is_placeholder(sec.sec_id) else SUCCESSOR, x.composite, candidate=x)

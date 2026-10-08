"""Truth cases: what really happened to a security, checked by hand against a
cited source, and the judges that compare one run's tables to them.

What every truth set shares is defined here, once:

- the statuses: `pass` must hold now; `known_wrong` must not hold yet and names
  the plan expected to fix it in `fixed_by` (`check_status`). The diagnosis set
  adds `ruling_pending` (not judged), its own (`diagnosis_truth.RULING_PENDING`).
- the error: `TruthFileError`, a truth file of any set that cannot be read.
- the judgement: each set's judge (`judge` here, `diagnosis_truth.judge_case`)
  keeps its own rules and gives one `Judgement` per case, a `Mismatch` per
  checked field that disagrees. `tally` counts one set's judgements: the
  scorecard's G.*, A.* and D.* lines read it.
- the flip rule: `now_right` names every known_wrong case whose judgement now
  holds; each becomes pass, its fixed_by cleared. The golden set applies it
  with a note (`flip`), the diagnosis set with a change-log row
  (`truth_set.TruthSet.flip`); scripts/scorecard.py --flip applies it to both.
- the note convention: `noted`.

The golden set and the audit. One file format serves the golden set
(`data/golden_lifecycles.csv`, named cases every rebuild must keep right) and
the accuracy audit (`data/accuracy_audit.csv`, decision 17: a census of the
high-impact rows plus a random sample). A case names a security by a ticker
and a date it traded (`ticker`, `on`) and lists only what was checked; a blank
cell is not checked.

    issuer_cik        the issuer CIK of the security found at (ticker, on)
    tickers           `;`-joined tickers its lifecycle must have traded under
    terminal          active | ended
    ends_after        the lifecycle must not end before this date (ending on it is right: the audit puts the
                      true last trade there; operator ruling 2026-10-04)
    exit_kind         merger | exchange | liquidation | dropped | lost_source | expiration
                      (of the lifecycle's final ending)
    last_trade_date   delistings.csv's internal last_trade_date of the lifecycle's final ending (the chain's: a
                      successor's ending when the chain continues), never the contract's published day.
                      `TruthCase.final_last_trade_date` in code. The diagnosis set's column of the same name is the
                      other reading: the contract's published day of the security's own last ending.
    dlret, dlret_tol  of the final ending (measured, else the fill); tol defaults to 0.005
    successor_ticker  a later security of the chain traded under this ticker

`status` (golden only): pass or known_wrong. `group` (audit only):
`census:<category>` or `random`. `source` holds the URLs the checker opened;
`library_says` is what the output said when the case was drawn (a reminder
for the checker, never judged).
"""
from __future__ import annotations

import csv
import io
import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from .atomic_io import write_atomic
from .exit_kind import EXIT_KINDS, ending_fields
from .lifecycle import ACTIVE, ENDED, LifecycleView

if TYPE_CHECKING:
    from .diagnosis_truth import DiagnosisCase

TRUTH_COLUMNS = ("case", "group", "ticker", "on", "issuer_cik", "tickers", "terminal", "ends_after", "exit_kind",
                 "last_trade_date", "dlret", "dlret_tol", "successor_ticker", "status", "fixed_by", "source",
                 "library_says", "note")
PASS, KNOWN_WRONG = "pass", "known_wrong"
NOW_MATCHES = "the library now matches"          # why the flip rule moved a case to pass
DEFAULT_DLRET_TOL = 0.005


class TruthFileError(ValueError):
    """A truth file of any set (golden, audit, diagnosis: its rows, legs, change log or the loop's ledger) that
    cannot be read; the message names the file and line."""


def check_status(status: str, fixed_by: str, where: str, allowed: Sequence[str]) -> None:
    """Refuse a status outside `allowed` (the set's own statuses) and a known_wrong case with no fixed_by: the
    status rule every truth set's loader applies."""
    if status not in allowed:
        raise TruthFileError(f"{where}: status {status!r} is not one of {list(allowed)}")
    if status == KNOWN_WRONG and not fixed_by.strip():
        raise TruthFileError(f"{where}: a known_wrong case needs fixed_by")


def noted(note: str, text: str) -> str:
    """`note` with `text` added: `note; text`, or `text` alone when the note is empty."""
    return f"{note}; {text}" if note else text


# -- the judgement ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Mismatch:
    """One checked field of one case that the run gets wrong: the case, the field (a column of the case's truth file,
    or `security` / `ending` when what the field is read from is missing), what the truth says and what the library
    says. A field reads as its set defines it: the golden `last_trade_date` and the diagnosis `last_trade_date` are
    two readings (module docstring). `wording` is the judge's own text where `<field> <library> != <truth>` would not
    read (the golden judge's missing security, tickers, final ending or successor, and its early end)."""
    case_id: str
    field: str
    truth: str
    library: str
    wording: str = ""

    def __str__(self) -> str:
        return self.wording or f"{self.field} {self.library or '(blank)'} != {self.truth or '(blank)'}"


@dataclass(frozen=True)
class Judgement:
    """One case judged against one run: the case (a golden or audit `TruthCase`, a `diagnosis_truth.DiagnosisCase`;
    each has a `case_id` and a `status`) and every mismatch, in its judge's order. It holds (`ok`) when there is
    none."""
    case: TruthCase | DiagnosisCase
    mismatches: tuple[Mismatch, ...]

    @property
    def ok(self) -> bool:
        return not self.mismatches

    @property
    def case_id(self) -> str:
        return self.case.case_id

    def __str__(self) -> str:
        return f"{self.case_id}: {'; '.join(map(str, self.mismatches))}"


def now_right(judgements: Iterable[Judgement]) -> list[str]:
    """The flip rule: the case_id of every known_wrong case whose judgement holds, in the judgements' order. Each
    becomes pass with no fixed_by (`flip`, `truth_set.TruthSet.flip`); `Tally.now_right` counts them."""
    return [j.case_id for j in judgements if j.case.status == KNOWN_WRONG and j.ok]


@dataclass(frozen=True)
class Tally:
    """What the scorecard counts in one set's judgements (`tally`)."""
    cases: int                          # judged
    matching: int                       # whose judgement holds
    passing: int                        # pass cases that hold
    pass_failing: int                   # pass cases that do not, each one of `failures`
    known_wrong: int
    now_right: int                      # known_wrong cases that hold: what the flip rule moves (`now_right`)
    fields: Mapping[str, int]           # mismatches by field, read through `tally`'s `key`
    failures: tuple[str, ...]           # each failing pass case as `case_id: mismatch; mismatch` (str(Judgement))

    @property
    def errors(self) -> int:
        """The cases whose judgement does not hold."""
        return self.cases - self.matching

    @property
    def mismatches(self) -> int:
        return sum(self.fields.values())


def tally(judgements: Sequence[Judgement], *, key: Callable[[str], str] | None = None) -> Tally:
    """The counts of one set's judgements. `key` names the field a mismatch counts under (the diagnosis set's
    `field_key` counts a leg's fields as `legs`); without it, its own field."""
    fields = Counter((key or str)(m.field) for j in judgements for m in j.mismatches)
    passing = [j for j in judgements if j.case.status == PASS]
    return Tally(cases=len(judgements), matching=sum(j.ok for j in judgements), passing=sum(j.ok for j in passing),
                 pass_failing=sum(not j.ok for j in passing),
                 known_wrong=sum(j.case.status == KNOWN_WRONG for j in judgements),
                 now_right=len(now_right(judgements)), fields=dict(fields),
                 failures=tuple(str(j) for j in passing if not j.ok))


# -- the golden set and the audit ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TruthCase:
    """One golden or audit case (module docstring). `final_last_trade_date` is the file's `last_trade_date` column:
    delistings.csv's internal day of the lifecycle's final ending."""
    case_id: str
    group: str
    ticker: str
    on: str
    issuer_cik: str = ""
    tickers: tuple[str, ...] = ()
    terminal: str = ""
    ends_after: str = ""
    exit_kind: str = ""
    final_last_trade_date: str = ""
    dlret: float | None = None
    dlret_tol: float = DEFAULT_DLRET_TOL
    successor_ticker: str = ""
    status: str = ""
    fixed_by: str = ""
    source: str = ""

    @property
    def pending(self) -> bool:
        """Nothing checked yet: an audit row nobody has filled in."""
        return not (self.issuer_cik or self.tickers or self.terminal or self.ends_after or self.exit_kind
                    or self.final_last_trade_date or self.dlret is not None or self.successor_ticker)


def _date(cell: str, where: str) -> str:
    if cell:
        try:
            date.fromisoformat(cell)
        except ValueError:
            raise TruthFileError(f"{where}: {cell!r} is not a YYYY-MM-DD date") from None
    return cell


def _float(cell: str, where: str) -> float | None:
    if not cell:
        return None
    try:
        return float(cell)
    except ValueError:
        raise TruthFileError(f"{where}: {cell!r} is not a number") from None


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != TRUTH_COLUMNS:
            raise TruthFileError(f"{path}: columns {reader.fieldnames} are not {list(TRUTH_COLUMNS)}")
        return list(reader)


def load_truth(path: str | Path, *, allow_pending: bool = False) -> list[TruthCase]:
    """Every case in the truth file at `path`. Raises TruthFileError (file and
    line in the message) on a wrong header, a duplicate case id, a missing
    ticker or date, a bad date or number, an unknown terminal, exit_kind or
    status, a known_wrong case with no fixed_by, or (unless `allow_pending`,
    the audit worksheet) a case that checks nothing."""
    path = Path(path)
    out: list[TruthCase] = []
    seen: set[str] = set()
    for line, r in enumerate(_rows(path), start=2):
        where = f"{path}:{line}"
        if not r["case"] or r["case"] in seen:
            raise TruthFileError(f"{where}: case id {r['case']!r} is blank or repeated")
        seen.add(r["case"])
        if not r["ticker"] or not r["on"]:
            raise TruthFileError(f"{where}: ticker and on are required")
        if r["terminal"] not in ("", ACTIVE, ENDED):
            raise TruthFileError(f"{where}: terminal {r['terminal']!r} is not active or ended")
        if r["exit_kind"] and r["exit_kind"] not in EXIT_KINDS:
            raise TruthFileError(f"{where}: exit_kind {r['exit_kind']!r} is not one of {sorted(EXIT_KINDS)}")
        check_status(r["status"], r["fixed_by"], where, ("", PASS, KNOWN_WRONG))
        tol = _float(r["dlret_tol"], where)
        case = TruthCase(
            case_id=r["case"], group=r["group"], ticker=r["ticker"], on=_date(r["on"], where),
            issuer_cik=r["issuer_cik"].lstrip("0"), tickers=tuple(t for t in r["tickers"].split(";") if t),
            terminal=r["terminal"], ends_after=_date(r["ends_after"], where), exit_kind=r["exit_kind"],
            final_last_trade_date=_date(r["last_trade_date"], where), dlret=_float(r["dlret"], where),
            dlret_tol=DEFAULT_DLRET_TOL if tol is None else tol, successor_ticker=r["successor_ticker"],
            status=r["status"], fixed_by=r["fixed_by"], source=r["source"])
        if case.pending and not allow_pending:
            raise TruthFileError(f"{where}: case {case.case_id!r} checks nothing")
        out.append(case)
    return out


def write_truth(path: str | Path, rows: Sequence[dict[str, str]]) -> None:
    """Write truth rows (every TRUTH_COLUMNS key) to `path` in one atomic replace."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(TRUTH_COLUMNS), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(Path(path), buf.getvalue())


def judge(case: TruthCase, view: LifecycleView) -> Judgement:
    """Compare one case to the tables behind `view`; every checked field that
    disagrees is one Mismatch (none: the output is right)."""
    bad: list[Mismatch] = []

    def miss(name: str, truth: str, library: str, wording: str = "") -> None:
        bad.append(Mismatch(case.case_id, name, truth, library, wording))

    sec = view.security_on(case.ticker, case.on)
    if sec is None:
        miss("security", f"{case.ticker} on {case.on}", "(no single security)",
             f"no single security traded {case.ticker} on {case.on}")
        return Judgement(case, tuple(bad))
    lc = view.lifecycle(sec)
    if case.issuer_cik:
        issuer = view.issuer_of(sec, case.on)
        if issuer.lstrip("0") != case.issuer_cik:
            miss("issuer_cik", case.issuer_cik, issuer)
    if case.tickers:
        traded = view.tickers_of(lc.chain)
        missing = sorted(set(case.tickers) - traded)
        if missing:
            miss("tickers", ";".join(case.tickers), ";".join(sorted(traded)), f"tickers missing {';'.join(missing)}")
    if case.terminal and lc.kind != case.terminal:
        miss("terminal", case.terminal, lc.kind)
    end = view.end_of(lc)
    if case.ends_after and end is not None and end < case.ends_after:
        miss("ends_after", case.ends_after, end, f"ends {end}, before {case.ends_after}")
    final = lc.final                    # the chain's final ending, a delistings.csv row (its internal days)
    if case.exit_kind or case.final_last_trade_date or case.dlret is not None:
        if final is None:
            miss("ending", "present", lc.kind, f"no final ending ({lc.kind})")
        else:
            kind = ending_fields(final).exit_kind
            if case.exit_kind and kind != case.exit_kind:
                miss("exit_kind", case.exit_kind, kind or "(none)")
            if case.final_last_trade_date and final["last_trade_date"] != case.final_last_trade_date:
                miss("last_trade_date", case.final_last_trade_date, final["last_trade_date"])
            if case.dlret is not None:
                got = float(final["dlret"]) if final["dlret"] else None
                if got is None or abs(got - case.dlret) > case.dlret_tol:
                    miss("dlret", f"{case.dlret} +/- {case.dlret_tol}", final["dlret"])
    if case.successor_ticker:
        later = view.tickers_of(lc.chain[1:])
        if case.successor_ticker not in later:
            miss("successor_ticker", case.successor_ticker, ";".join(sorted(later)),
                 f"no successor traded {case.successor_ticker}")
    return Judgement(case, tuple(bad))


def judge_all(cases: Sequence[TruthCase], view: LifecycleView) -> list[Judgement]:
    return [judge(c, view) for c in cases]


def flip(path: str | Path, view: LifecycleView) -> list[str]:
    """The flip rule (`now_right`) on a golden truth file: every known_wrong case the run behind `view` now matches
    becomes pass, its fixed_by cleared, and its note records the flip (`<note>; the library now matches, was
    known_wrong until <fixed_by>`: the file has no change log). No other cell changes, and the file is rewritten
    (`write_truth`) only when a case flipped. Returns the flipped case ids. Raises TruthFileError as `load_truth`."""
    path = Path(path)
    flipped = now_right(judge_all(load_truth(path), view))
    if flipped:
        rows, moved = _rows(path), set(flipped)
        for r in rows:
            if r["case"] in moved:
                r["note"] = noted(r["note"], f"{NOW_MATCHES}, was known_wrong until {r['fixed_by']}")
                r["status"], r["fixed_by"] = PASS, ""
        write_truth(path, rows)
    return flipped


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson_upper(errors: int, n: int, confidence: float = 0.95) -> float:
    """The one-sided Clopper-Pearson upper bound on an error rate after
    `errors` wrong in `n` checked: the p at which seeing `errors` or fewer has
    probability 1 - confidence. 0 wrong in 100 gives about 0.0295."""
    if n <= 0:
        return 1.0
    if errors >= n:
        return 1.0
    alpha = 1.0 - confidence
    lo, hi = errors / n, 1.0
    for _ in range(100):                    # bisection: binom_cdf falls as p rises
        mid = (lo + hi) / 2
        if binom_cdf(errors, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi

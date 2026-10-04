"""Truth cases: what really happened to a security, checked by hand against a
cited source, and the judge that compares the output tables to it.

One file format serves the golden set (`data/golden_lifecycles.csv`, named
cases every rebuild must keep right) and the accuracy audit
(`data/accuracy_audit.csv`, decision 17: a census of the high-impact rows plus
a random sample). A case names a security by a ticker and a date it traded
(`ticker`, `on`) and lists only what was checked; a blank cell is not checked.

    issuer_cik        the issuer CIK of the security found at (ticker, on)
    tickers           `;`-joined tickers its lifecycle must have traded under
    terminal          active | ended
    ends_after        the lifecycle must not end before this date (ending on it is right: the audit puts the
                      true last trade there; operator ruling 2026-10-04)
    exit_kind         merger | exchange | liquidation | dropped | lost_source | expiration
                      (of the lifecycle's final ending)
    last_trade_date   of the final ending
    dlret, dlret_tol  of the final ending (measured, else the fill); tol defaults to 0.005
    successor_ticker  a later security of the chain traded under this ticker

`status` (golden only): `pass` must hold now; `known_wrong` must not hold yet
and names the plan expected to fix it in `fixed_by`. `group` (audit only):
`census:<category>` or `random`. `source` holds the URLs the checker opened;
`library_says` is what the output said when the case was drawn (a reminder
for the checker, never judged).
"""
from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .atomic_io import write_atomic
from .exit_kind import EXIT_KINDS, ending_fields
from .lifecycle import ACTIVE, ENDED, LifecycleView

TRUTH_COLUMNS = ("case", "group", "ticker", "on", "issuer_cik", "tickers", "terminal", "ends_after", "exit_kind",
                 "last_trade_date", "dlret", "dlret_tol", "successor_ticker", "status", "fixed_by", "source",
                 "library_says", "note")
CHECKED = ("issuer_cik", "tickers", "terminal", "ends_after", "exit_kind", "last_trade_date", "dlret",
           "successor_ticker")
PASS, KNOWN_WRONG = "pass", "known_wrong"
DEFAULT_DLRET_TOL = 0.005


class TruthFileError(ValueError):
    """A truth file that cannot be read; the message names the file and line."""


@dataclass(frozen=True)
class TruthCase:
    case: str
    group: str
    ticker: str
    on: str
    issuer_cik: str = ""
    tickers: tuple[str, ...] = ()
    terminal: str = ""
    ends_after: str = ""
    exit_kind: str = ""
    last_trade_date: str = ""
    dlret: float | None = None
    dlret_tol: float = DEFAULT_DLRET_TOL
    successor_ticker: str = ""
    status: str = ""
    fixed_by: str = ""
    source: str = ""

    @property
    def pending(self) -> bool:
        """Nothing checked yet: an audit row nobody has filled in."""
        return all(getattr(self, c) in ("", (), None) for c in CHECKED)


@dataclass(frozen=True)
class Judgement:
    case: TruthCase
    mismatches: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.mismatches


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


def load_truth(path: str | Path, *, allow_pending: bool = False) -> list[TruthCase]:
    """Every case in the truth file at `path`. Raises TruthFileError (file and
    line in the message) on a wrong header, a duplicate case id, a missing
    ticker or date, a bad date or number, an unknown terminal, exit_kind or
    status, a known_wrong case with no fixed_by, or (unless `allow_pending`,
    the audit worksheet) a case that checks nothing."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != TRUTH_COLUMNS:
            raise TruthFileError(f"{path}: columns {reader.fieldnames} are not {list(TRUTH_COLUMNS)}")
        out: list[TruthCase] = []
        seen: set[str] = set()
        for line, r in enumerate(reader, start=2):
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
            if r["status"] not in ("", PASS, KNOWN_WRONG):
                raise TruthFileError(f"{where}: status {r['status']!r} is not pass or known_wrong")
            if r["status"] == KNOWN_WRONG and not r["fixed_by"]:
                raise TruthFileError(f"{where}: a known_wrong case needs fixed_by")
            tol = _float(r["dlret_tol"], where)
            case = TruthCase(
                case=r["case"], group=r["group"], ticker=r["ticker"], on=_date(r["on"], where),
                issuer_cik=r["issuer_cik"].lstrip("0"), tickers=tuple(t for t in r["tickers"].split(";") if t),
                terminal=r["terminal"], ends_after=_date(r["ends_after"], where), exit_kind=r["exit_kind"],
                last_trade_date=_date(r["last_trade_date"], where), dlret=_float(r["dlret"], where),
                dlret_tol=DEFAULT_DLRET_TOL if tol is None else tol, successor_ticker=r["successor_ticker"],
                status=r["status"], fixed_by=r["fixed_by"], source=r["source"])
            if case.pending and not allow_pending:
                raise TruthFileError(f"{where}: case {case.case!r} checks nothing")
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
    disagrees is one mismatch (an empty list: the output is right)."""
    sec = view.security_on(case.ticker, case.on)
    if sec is None:
        return Judgement(case, (f"no single security traded {case.ticker} on {case.on}",))
    lc = view.lifecycle(sec)
    bad: list[str] = []
    if case.issuer_cik and view.issuer_of(sec, case.on).lstrip("0") != case.issuer_cik:
        bad.append(f"issuer_cik {view.issuer_of(sec, case.on) or '(blank)'} != {case.issuer_cik}")
    if case.tickers:
        missing = sorted(set(case.tickers) - view.tickers_of(lc.chain))
        if missing:
            bad.append(f"tickers missing {';'.join(missing)}")
    if case.terminal and lc.kind != case.terminal:
        bad.append(f"terminal {lc.kind} != {case.terminal}")
    end = view.end_of(lc)
    if case.ends_after and end is not None and end < case.ends_after:
        bad.append(f"ends {end}, before {case.ends_after}")
    final = lc.final
    if case.exit_kind or case.last_trade_date or case.dlret is not None:
        if final is None:
            bad.append(f"no final ending ({lc.kind})")
        else:
            kind = ending_fields(final).exit_kind
            if case.exit_kind and kind != case.exit_kind:
                bad.append(f"exit_kind {kind or '(none)'} != {case.exit_kind}")
            if case.last_trade_date and final["last_trade_date"] != case.last_trade_date:
                bad.append(f"last_trade_date {final['last_trade_date'] or '(blank)'} != {case.last_trade_date}")
            if case.dlret is not None:
                got = float(final["dlret"]) if final["dlret"] else None
                if got is None or abs(got - case.dlret) > case.dlret_tol:
                    bad.append(f"dlret {final['dlret'] or '(blank)'} != {case.dlret} +/- {case.dlret_tol}")
    if case.successor_ticker and case.successor_ticker not in view.tickers_of(lc.chain[1:]):
        bad.append(f"no successor traded {case.successor_ticker}")
    return Judgement(case, tuple(bad))


def judge_all(cases: Sequence[TruthCase], view: LifecycleView) -> list[Judgement]:
    return [judge(c, view) for c in cases]


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

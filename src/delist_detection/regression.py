"""The diagnosis loop's regression report (spec 2026-10-03-diagnosis-truth-fixes, section 1.4): every contract
field that changed between a base commit's run and this one, for securities outside the diagnosis truth set and
its successor chains.

A security's contract/delistings.csv row is compared column by column. The verdict column is left out: the loop
judges classification, and sub-plan 5i changes verdicts on purpose. Its contract/security_history.csv rows are
compared as one list of ranges, and a new contract/id_changes.csv row (a placeholder that now holds a FIGI) is
listed too. A report row is explained when the ledger settled that exact change as right (`new_right`); a
regressed row the loop added to the truth file as ruling_pending (fixed_by `regression`) stays unexplained until
the operator settles it."""
from __future__ import annotations

import csv
import io
import subprocess
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import store
from .atomic_io import write_atomic
from .diagnosis_truth import REGRESSION_PENDING, RULING_PENDING, DiagnosisCase

REPORT_COLUMNS = ("sec_id", "table", "field", "kind", "old", "new")
CHANGED, ADDED, REMOVED = "changed", "added", "removed"
SKIPPED_COLUMNS = frozenset({"sec_id", "verdict"})
BRIEF_COLUMNS = ("exit_kind", "drop_reason", "continuation", "successor_sec_id", "last_trade_date", "value_rule")


class RegressionInputError(ValueError):
    """A base commit or output folder that lacks a contract file; the message names it."""


@dataclass(frozen=True)
class Snapshot:
    """One run's contract files, as string rows."""
    delistings: Sequence[Mapping[str, str]]
    security_history: Sequence[Mapping[str, str]]
    id_changes: Sequence[Mapping[str, str]] = field(default=())


REQUIRED_COLUMNS = {
    "contract_delistings": ("sec_id", "successor_sec_id"),
    "security_history": ("sec_id", "ticker", "start_date", "end_date", "issuer_id"),
    "id_changes": ("old_sec_id", "new_sec_id"),
}


def _rows(text: str, table: str, where: str) -> list[dict[str, str]]:
    """The rows of one contract file, after its header is checked (an empty file is checked by its header)."""
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED_COLUMNS[table] if c not in (reader.fieldnames or [])]
    if missing:
        raise RegressionInputError(f"{where}: missing column(s) {', '.join(missing)}")
    return list(reader)


def read_snapshot(out_dir: str | Path) -> Snapshot:
    """The contract files under `out_dir` (contract/id_changes.csv may be missing)."""
    def rows(name: str, required: bool = True) -> list[dict[str, str]]:
        path = store.table_path(out_dir, name)
        if not path.exists():
            if required:
                raise RegressionInputError(f"{path}: missing")
            return []
        return _rows(path.read_text(encoding="utf-8"), name, str(path))
    return Snapshot(rows("contract_delistings"), rows("security_history"), rows("id_changes", required=False))


def snapshot_at(repo: str | Path, rev: str, out_dir: str | Path) -> Snapshot:
    """The contract files as commit `rev` of git repository `repo` holds them (`out_dir` lies inside `repo`)."""
    root = Path(repo).resolve()

    def rows(name: str, required: bool = True) -> list[dict[str, str]]:
        path = store.table_path(Path(out_dir).resolve(), name)
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            raise RegressionInputError(f"{path}: not inside the repository {root}") from None
        done = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{rel}"], capture_output=True, text=True)
        if done.returncode != 0:
            if required:
                raise RegressionInputError(f"{rev}:{rel}: {done.stderr.strip() or 'not in that commit'}")
            return []
        return _rows(done.stdout, name, f"{rev}:{rel}")
    return Snapshot(rows("contract_delistings"), rows("security_history"), rows("id_changes", required=False))


def successor_chain(sec_ids: Collection[str], *delistings: Sequence[Mapping[str, str]]) -> set[str]:
    """`sec_ids` and every security their contract rows lead to through successor_sec_id, in any of the tables."""
    nxt: dict[str, set[str]] = defaultdict(set)
    for rows in delistings:
        for r in rows:
            if r.get("successor_sec_id"):
                nxt[r["sec_id"]].add(r["successor_sec_id"])
    out: set[str] = set()
    todo = list(sec_ids)
    while todo:
        s = todo.pop()
        if s not in out:
            out.add(s)
            todo.extend(nxt.get(s, ()))
    return out


def _pending_regression(c: DiagnosisCase) -> bool:
    return c.status == RULING_PENDING and c.fixed_by == REGRESSION_PENDING


def excluded(cases: Sequence[DiagnosisCase], *delistings: Sequence[Mapping[str, str]]) -> set[str]:
    """The securities the report leaves out: every truth case's security and its successor chain, except a
    regressed row the loop could not settle (it keeps showing until the operator does)."""
    return successor_chain({c.sec_id for c in cases if not _pending_regression(c)}, *delistings)


def _row(sec: str, table: str, name: str, kind: str, old: str, new: str) -> dict[str, str]:
    return dict(zip(REPORT_COLUMNS, (sec, table, name, kind, old, new)))


def _brief(row: Mapping[str, str]) -> str:
    return ";".join(f"{c}={row.get(c, '')}" for c in BRIEF_COLUMNS)


def _ranges(rows: Sequence[Mapping[str, str]]) -> dict[str, str]:
    by: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by[r["sec_id"]].append(f"{r['ticker']}:{r['start_date']}..{r['end_date']}:{r['issuer_id']}")
    return {k: ";".join(sorted(v)) for k, v in by.items()}


def diff_contract(base: Snapshot, new: Snapshot, exclude: Collection[str] = ()) -> list[dict[str, str]]:
    """Every change from `base` to `new` outside `exclude`: delistings rows first (by sec_id, then column), then
    ticker ranges, then new id_changes rows."""
    skip = set(exclude)
    out: list[dict[str, str]] = []
    old_rows = {r["sec_id"]: r for r in base.delistings}
    new_rows = {r["sec_id"]: r for r in new.delistings}
    for sec in sorted((old_rows.keys() | new_rows.keys()) - skip):
        o, n = old_rows.get(sec), new_rows.get(sec)
        if o is None:
            out.append(_row(sec, "delistings", "", ADDED, "", _brief(n)))
        elif n is None:
            out.append(_row(sec, "delistings", "", REMOVED, _brief(o), ""))
        else:
            for col in dict.fromkeys([*o, *n]):
                if col not in SKIPPED_COLUMNS and o.get(col, "") != n.get(col, ""):
                    out.append(_row(sec, "delistings", col, CHANGED, o.get(col, ""), n.get(col, "")))
    old_r, new_r = _ranges(base.security_history), _ranges(new.security_history)
    for sec in sorted((old_r.keys() | new_r.keys()) - skip):
        if old_r.get(sec, "") != new_r.get(sec, ""):
            kind = ADDED if sec not in old_r else REMOVED if sec not in new_r else CHANGED
            out.append(_row(sec, "security_history", "ranges", kind, old_r.get(sec, ""), new_r.get(sec, "")))
    seen = {(r["old_sec_id"], r["new_sec_id"]) for r in base.id_changes}
    for r in new.id_changes:
        if (r["old_sec_id"], r["new_sec_id"]) not in seen and r["old_sec_id"] not in skip:
            out.append(_row(r["old_sec_id"], "id_changes", "new_sec_id", ADDED, r["old_sec_id"], r["new_sec_id"]))
    return out


def regression_key(row: Mapping[str, str]) -> str:
    """The ledger key of one report row."""
    return "reg|" + "|".join(row[c] for c in REPORT_COLUMNS)


def unexplained(rows: Sequence[Mapping[str, str]], cases: Sequence[DiagnosisCase],
                settled: Collection[str]) -> list[dict[str, str]]:
    """The report rows the ledger has not settled as right, then one row per regressed security the loop added to
    the truth file as ruling_pending."""
    left = [dict(r) for r in rows if regression_key(r) not in settled]
    left += [_row(c.sec_id, "truth", "status", RULING_PENDING, "", c.note) for c in cases if _pending_regression(c)]
    return left


def write_report(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(REPORT_COLUMNS), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(Path(path), buf.getvalue())

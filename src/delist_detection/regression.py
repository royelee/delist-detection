"""The diagnosis loop's regression report (spec 2026-10-03-diagnosis-truth-fixes, section 1.4): every contract
field that changed between a base commit's run and this one, for securities outside the diagnosis truth set and
its successor chains.

A security's contract/delistings.csv row is compared column by column. The verdict column and the columns
derived from other columns and prices (`SKIPPED_COLUMNS`) are left out: the loop judges classification, and
sub-plan 5i changes verdicts on purpose. Its contract/security_history.csv rows are compared as one list of ranges,
and a new contract/id_changes.csv row (a placeholder that now holds a FIGI) is listed too. A report row is
explained when the ledger settled that exact change as right (`new_right`); a
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
from .contract import id_change_rows
from .diagnosis_truth import REGRESSION_PENDING, RULING_PENDING, DiagnosisCase

REPORT_COLUMNS = ("sec_id", "table", "field", "kind", "old", "new")
CHANGED, ADDED, REMOVED, RENAMED = "changed", "added", "removed", "renamed"
# Columns the diff leaves out: the key, the verdict (5i changes it on purpose), and every column that is a function of
# other columns and of prices (a dlret moves with any price answer and says nothing the truth set scores).
SKIPPED_COLUMNS = frozenset({"sec_id", "verdict", "dlret", "dlret_fill", "terminal_value", "value_formula",
                             "terms_source", "terms_gate"})
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


def _at(repo: str | Path, rev: str, out_dir: str | Path, name: str, required: bool = True) -> list[dict[str, str]]:
    """Table `name` under `out_dir` as commit `rev` of the repository `repo` holds it (`out_dir` lies inside
    `repo`); [] when the commit lacks it and it is not `required`."""
    root = Path(repo).resolve()
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
    if name == "securities":
        return list(csv.DictReader(io.StringIO(done.stdout)))
    return _rows(done.stdout, name, f"{rev}:{rel}")


def snapshot_at(repo: str | Path, rev: str, out_dir: str | Path) -> Snapshot:
    """The contract files as commit `rev` of git repository `repo` holds them (`out_dir` lies inside `repo`)."""
    return Snapshot(_at(repo, rev, out_dir, "contract_delistings"), _at(repo, rev, out_dir, "security_history"),
                    _at(repo, rev, out_dir, "id_changes", required=False))


def id_changes_since(repo: str | Path, rev: str, out_dir: str | Path,
                     run_id_changes: Sequence[Mapping[str, str]] = ()) -> list[dict[str, str]]:
    """Every placeholder that now holds a FIGI since commit `rev`: `contract.id_change_rows` over that commit's
    securities.csv and this run's, plus the run's own contract/id_changes.csv rows (`run_id_changes`). The run's
    file is not cumulative (it lists one run's renames, empty on the next), so a rename that happened over several
    runs is found only by comparing against the base commit. A missing securities.csv on either side gives no
    computed renames."""
    now = store.table_path(out_dir, "securities")
    run = list(csv.DictReader(now.open(newline="", encoding="utf-8"))) if now.exists() else []
    found = id_change_rows(_at(repo, rev, out_dir, "securities", required=False), run, "") if run else []
    seen = {(r["old_sec_id"], r["new_sec_id"]) for r in run_id_changes}
    return [dict(r) for r in run_id_changes] + [r for r in found if (r["old_sec_id"], r["new_sec_id"]) not in seen]


def build_report(repo: str | Path, rev: str, out_dir: str | Path, cases: Sequence[DiagnosisCase],
                 id_changes: Sequence[Mapping[str, str]] | None = None) -> list[dict[str, str]]:
    """The regression report of the run under `out_dir` against commit `rev`: the one place that reads both
    snapshots, builds the exclusion set (truth cases, successor chains and renames) and diffs. `id_changes` are the
    renames to exclude (default: `id_changes_since`)."""
    base, new = snapshot_at(repo, rev, out_dir), read_snapshot(out_dir)
    if id_changes is None:
        id_changes = id_changes_since(repo, rev, out_dir, new.id_changes)
    return diff_contract(base, new, excluded(cases, base.delistings, new.delistings, id_changes=id_changes),
                         renames=id_changes)


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


def excluded(cases: Sequence[DiagnosisCase], *delistings: Sequence[Mapping[str, str]],
             id_changes: Sequence[Mapping[str, str]] = ()) -> set[str]:
    """The securities the report leaves out: every truth case's security and its successor chain, except a
    regressed row the loop could not settle (it keeps showing until the operator does). A placeholder whose
    `id_changes` row names an excluded security as its new sec_id is left out too (repeated, so a chain of
    renames is), since the rename belongs to the truth case."""
    out = successor_chain({c.sec_id for c in cases if not _pending_regression(c)}, *delistings)
    grew = True
    while grew:
        old = {r["old_sec_id"] for r in id_changes if r["new_sec_id"] in out}
        grew = not old <= out
        out |= old
    return out


def _row(sec: str, table: str, name: str, kind: str, old: str, new: str) -> dict[str, str]:
    return dict(zip(REPORT_COLUMNS, (sec, table, name, kind, old, new)))


def _brief(row: Mapping[str, str]) -> str:
    return ";".join(f"{c}={row.get(c, '')}" for c in BRIEF_COLUMNS)


def _ranges(rows: Sequence[Mapping[str, str]]) -> dict[str, str]:
    by: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by[r["sec_id"]].append(f"{r['ticker']}:{r['start_date']}..{r['end_date']}:{r['issuer_id']}")
    return {k: ";".join(sorted(v)) for k, v in by.items()}


def renamed_to(renames: Sequence[Mapping[str, str]]) -> dict[str, str]:
    """Each renamed placeholder's sec_id now (`renames`: id_changes rows), a chain of renames followed to its end
    (P renamed to M, M to F: P is F now)."""
    step = {r["old_sec_id"]: r["new_sec_id"] for r in renames if r.get("old_sec_id") and r.get("new_sec_id")}
    out: dict[str, str] = {}
    for old in step:
        now, seen = step[old], {old}
        while now in step and now not in seen:
            seen.add(now)
            now = step[now]
        out[old] = now
    return out


def _rekeyed(base: Snapshot, moved: Mapping[str, str]) -> Snapshot:
    """`base` with each renamed placeholder's rows under its sec_id now: its contract/delistings.csv row becomes
    that security's when the security had none of its own (its own row wins otherwise; of several placeholders the
    first in sec_id order wins), and its ticker ranges join that security's."""
    rows = {r["sec_id"]: r for r in base.delistings}
    out = [r for r in base.delistings if r["sec_id"] not in moved]
    taken = {r["sec_id"] for r in out}
    for old in sorted(moved):
        r, new_id = rows.get(old), moved[old]
        if r is not None and new_id not in taken:
            out.append({**r, "sec_id": new_id})
            taken.add(new_id)
    history = [{**r, "sec_id": moved.get(r["sec_id"], r["sec_id"])} for r in base.security_history]
    return Snapshot(out, history, base.id_changes)


def diff_contract(base: Snapshot, new: Snapshot, exclude: Collection[str] = (),
                  renames: Sequence[Mapping[str, str]] | None = None) -> list[dict[str, str]]:
    """Every change from `base` to `new` outside `exclude`: delistings rows first (by sec_id, then column), then
    ticker ranges, then the placeholder renames. A renamed placeholder (`renames`, id_changes rows; default the
    run's own contract/id_changes.csv) is compared under the sec_id it holds now (`_rekeyed`), so a placeholder a
    line folded into a FIGI shows as one `renamed` row under that FIGI, plus whatever of the FIGI's own row and
    ranges really changed, never as its own removed row and the FIGI's added one. A rename the base run already
    listed in its own contract/id_changes.csv is not reported again."""
    skip = set(exclude)
    moved = renamed_to(new.id_changes if renames is None else renames)
    base = _rekeyed(base, moved)
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
    for old, now in sorted(moved.items(), key=lambda kv: (kv[1], kv[0])):
        if (old, now) not in seen and old not in skip and now not in skip:
            out.append(_row(now, "id_changes", "sec_id", RENAMED, old, now))
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

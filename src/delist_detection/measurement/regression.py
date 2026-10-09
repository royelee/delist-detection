"""The diagnosis loop's regression report (spec 2026-10-03-diagnosis-truth-fixes, section 1.4): every contract
field that changed between a base commit's run and this one, for securities outside the diagnosis truth set and
its successor chains.

A security's contract/delistings.csv row is compared column by column. The verdict column and the columns
derived from other columns and prices (`SKIPPED_COLUMNS`) are left out: the loop judges classification, and
sub-plan 5i changes verdicts on purpose. Its contract/security_history.csv rows are compared as one list of ranges, a
basket's legs (contract/payout_legs.csv, schema 3: one list of legs per security, a missing file is none) the same
way, and a new contract/id_changes.csv row (a placeholder that now holds a FIGI) is listed too. Which report rows
the loop has explained, and each row's key and field name, are the loop round's (`loop_round.unexplained`,
`loop_round.regression_key`, `loop_round.Field`).

Both runs are run snapshots (`run_snapshot.RunSnapshot`: the base commit's, `RunSnapshot.at`, and the output
folder's, `RunSnapshot.read`); a snapshot that lacks contract/delistings.csv or contract/security_history.csv, or
whose file has another layout, raises `run_snapshot.SnapshotError` naming the file."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from ..sources.atomic_io import write_atomic
from ..outputs.contract import id_change_rows
from .diagnosis_truth import REGRESSION_PENDING, RULING_PENDING, DiagnosisCase
from ..outputs.run_snapshot import RunSnapshot

REPORT_COLUMNS = ("sec_id", "table", "field", "kind", "old", "new")
CHANGED, ADDED, REMOVED, RENAMED = "changed", "added", "removed", "renamed"
# Columns the diff leaves out: the key, the verdict (5i changes it on purpose), and every column that is a function of
# other columns and of prices (a dlret moves with any price answer and says nothing the truth set scores).
SKIPPED_COLUMNS = frozenset({"sec_id", "verdict", "dlret", "dlret_fill", "terminal_value", "value_formula",
                             "terms_source", "terms_gate"})
BRIEF_COLUMNS = ("exit_kind", "drop_reason", "continuation", "successor_sec_id", "last_trade_date", "value_rule")


class _Contract(NamedTuple):
    """The contract files one diff compares, from a run snapshot (`of`)."""
    delistings: Sequence[Mapping[str, str]]
    security_history: Sequence[Mapping[str, str]]
    id_changes: Sequence[Mapping[str, str]]
    legs: Sequence[Mapping[str, str]]

    @classmethod
    def of(cls, run: RunSnapshot) -> _Contract:
        """contract/delistings.csv and security_history.csv must be there; id_changes.csv and payout_legs.csv
        (schema 3) may be missing: none."""
        return cls(run.require("contract_delistings"), run.require("security_history"), run.id_changes or [],
                   run.payout_legs or [])


def id_changes_since(base: RunSnapshot, new: RunSnapshot) -> list[dict[str, str]]:
    """Every placeholder that now holds a FIGI since the `base` run: `contract.id_change_rows` over the base run's
    securities.csv and the `new` run's, plus the new run's own contract/id_changes.csv rows. The run's file is not
    cumulative (it lists one run's renames, empty on the next), so a rename that happened over several runs is found
    only by comparing against the base commit. A missing securities.csv on either side gives no computed renames."""
    run = new.securities if new.has("securities") else []
    found = id_change_rows(base.securities if base.has("securities") else [], run, "") if run else []
    run_id_changes = new.id_changes or []
    seen = {(r["old_sec_id"], r["new_sec_id"]) for r in run_id_changes}
    return [dict(r) for r in run_id_changes] + [r for r in found if (r["old_sec_id"], r["new_sec_id"]) not in seen]


def build_report(base: RunSnapshot, new: RunSnapshot, cases: Sequence[DiagnosisCase],
                 id_changes: Sequence[Mapping[str, str]] | None = None) -> list[dict[str, str]]:
    """The regression report of the `new` run against the `base` run (a commit's, `RunSnapshot.at`): the one place
    that builds the exclusion set (truth cases, successor chains and renames) and diffs. `id_changes` are the renames
    to exclude (default: `id_changes_since`)."""
    if id_changes is None:
        id_changes = id_changes_since(base, new)
    return diff_contract(base, new, excluded(cases, base.require("contract_delistings"),
                                             new.require("contract_delistings"), id_changes=id_changes),
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


def pending_regression(c: DiagnosisCase) -> bool:
    """A regressed row the loop added to the truth file and could not settle (ruling_pending, fixed_by
    `regression`): it keeps showing in the report, and counts as unexplained, until the operator settles it."""
    return c.status == RULING_PENDING and c.fixed_by == REGRESSION_PENDING


def excluded(cases: Sequence[DiagnosisCase], *delistings: Sequence[Mapping[str, str]],
             id_changes: Sequence[Mapping[str, str]] = ()) -> set[str]:
    """The securities the report leaves out: every truth case's security and its successor chain, except a
    regressed row the loop could not settle (it keeps showing until the operator does). A placeholder whose
    `id_changes` row names an excluded security as its new sec_id is left out too (repeated, so a chain of
    renames is), since the rename belongs to the truth case."""
    out = successor_chain({c.sec_id for c in cases if not pending_regression(c)}, *delistings)
    grew = True
    while grew:
        old = {r["old_sec_id"] for r in id_changes if r["new_sec_id"] in out}
        grew = not old <= out
        out |= old
    return out


def report_row(sec: str, table: str, name: str, kind: str, old: str, new: str) -> dict[str, str]:
    """One report row (REPORT_COLUMNS)."""
    return dict(zip(REPORT_COLUMNS, (sec, table, name, kind, old, new)))


def _brief(row: Mapping[str, str]) -> str:
    return ";".join(f"{c}={row.get(c, '')}" for c in BRIEF_COLUMNS)


def _ranges(rows: Sequence[Mapping[str, str]]) -> dict[str, str]:
    by: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by[r["sec_id"]].append(f"{r['ticker']}:{r['start_date']}..{r['end_date']}:{r['issuer_id']}")
    return {k: ";".join(sorted(v)) for k, v in by.items()}


def _legs(rows: Sequence[Mapping[str, str]]) -> dict[str, str]:
    """Each security's basket legs as one string, in leg order: the leg's ratio, price security and price ticker."""
    by: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for r in rows:
        by[r["sec_id"]].append((int(r["leg"]), f"{r['leg']}:{r['ratio']}:{r.get('price_sec_id', '')}:{r['price_ticker']}"))
    return {k: ";".join(t for _, t in sorted(v)) for k, v in by.items()}


def renamed_to(renames: Sequence[Mapping[str, str]]) -> dict[str, str]:
    """Each renamed placeholder's sec_id now (`renames`: id_changes rows), a chain of renames followed to its end
    (P renamed to M, M to F: P is F now). The one chain rule: the truth set renames by it too
    (`truth_set.TruthSet.rename`)."""
    step = {r["old_sec_id"]: r["new_sec_id"] for r in renames if r.get("old_sec_id") and r.get("new_sec_id")}
    out: dict[str, str] = {}
    for old in step:
        now, seen = step[old], {old}
        while now in step and now not in seen:
            seen.add(now)
            now = step[now]
        out[old] = now
    return out


def _rekeyed(base: _Contract, moved: Mapping[str, str]) -> _Contract:
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
    legs = [{**r, "sec_id": moved.get(r["sec_id"], r["sec_id"])} for r in base.legs]
    return _Contract(out, history, base.id_changes, legs)


def diff_contract(base_run: RunSnapshot, new_run: RunSnapshot, exclude: Collection[str] = (),
                  renames: Sequence[Mapping[str, str]] | None = None) -> list[dict[str, str]]:
    """Every change from `base` to `new` outside `exclude`: delistings rows first (by sec_id, then column), then
    ticker ranges, then the placeholder renames. A renamed placeholder (`renames`, id_changes rows; default the
    run's own contract/id_changes.csv) is compared under the sec_id it holds now (`_rekeyed`), so a placeholder a
    line folded into a FIGI shows as one `renamed` row under that FIGI, plus whatever of the FIGI's own row and
    ranges really changed, never as its own removed row and the FIGI's added one. A rename the base run already
    listed in its own contract/id_changes.csv is not reported again."""
    skip = set(exclude)
    base, new = _Contract.of(base_run), _Contract.of(new_run)
    moved = renamed_to(new.id_changes if renames is None else renames)
    base = _rekeyed(base, moved)
    out: list[dict[str, str]] = []
    old_rows = {r["sec_id"]: r for r in base.delistings}
    new_rows = {r["sec_id"]: r for r in new.delistings}
    for sec in sorted((old_rows.keys() | new_rows.keys()) - skip):
        o, n = old_rows.get(sec), new_rows.get(sec)
        if o is None:
            out.append(report_row(sec, "delistings", "", ADDED, "", _brief(n)))
        elif n is None:
            out.append(report_row(sec, "delistings", "", REMOVED, _brief(o), ""))
        else:
            for col in dict.fromkeys([*o, *n]):
                if col not in SKIPPED_COLUMNS and o.get(col, "") != n.get(col, ""):
                    out.append(report_row(sec, "delistings", col, CHANGED, o.get(col, ""), n.get(col, "")))
    old_r, new_r = _ranges(base.security_history), _ranges(new.security_history)
    for sec in sorted((old_r.keys() | new_r.keys()) - skip):
        if old_r.get(sec, "") != new_r.get(sec, ""):
            kind = ADDED if sec not in old_r else REMOVED if sec not in new_r else CHANGED
            out.append(report_row(sec, "security_history", "ranges", kind, old_r.get(sec, ""), new_r.get(sec, "")))
    old_l, new_l = _legs(base.legs), _legs(new.legs)
    for sec in sorted((old_l.keys() | new_l.keys()) - skip):
        if old_l.get(sec, "") != new_l.get(sec, ""):
            kind = ADDED if sec not in old_l else REMOVED if sec not in new_l else CHANGED
            out.append(report_row(sec, "payout_legs", "legs", kind, old_l.get(sec, ""), new_l.get(sec, "")))
    seen = {(r["old_sec_id"], r["new_sec_id"]) for r in base.id_changes}
    for old, now in sorted(moved.items(), key=lambda kv: (kv[1], kv[0])):
        if (old, now) not in seen and old not in skip and now not in skip:
            out.append(report_row(now, "id_changes", "sec_id", RENAMED, old, now))
    return out


def write_report(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(REPORT_COLUMNS), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(Path(path), buf.getvalue())

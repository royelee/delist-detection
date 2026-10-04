"""One diagnosis-loop round's error list, or the ledger's seed (spec 2026-10-03-diagnosis-truth-fixes, 1.7).

  python scripts/truth_loop_round.py --label 5a --base <commit> --round 1
  python scripts/truth_loop_round.py --label 5-0 --seed-ledger

A round does five things:
1. It renames truth rows whose placeholder now holds a FIGI (contract/id_changes.csv).
2. It judges the run under --output-dir against the truth file.
3. It writes output/regression_report.csv against --base.
4. It keeps the errors the ledger has not seen.
5. It writes them as case rows to output/diagnose_unknown_report/loop/<label>/round-<N>/cases.csv.

It prints one JSON line with the counts, the cases and the path. --seed-ledger records every current mismatch as
`known` (the reports already describe them). Offline (git only). Exit 2: a missing or unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection.diagnosis_truth import (COLUMNS, LibraryRows, judge_all, load_legs, parse_rows,
                                              write_diagnosis_truth)
from delist_detection.lifecycle import Tables
from delist_detection.regression import (RegressionInputError, diff_contract, excluded, read_snapshot,
                                         regression_key, snapshot_at, write_report)
from delist_detection.truth import TruthFileError

ROOT = Path(__file__).resolve().parents[1]


def _legs_rows(out_dir: Path):
    path = out_dir / "contract" / "payout_legs.csv"
    return dl.read_csv(path) if path.exists() else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True, help="the sub-plan, e.g. 5a")
    p.add_argument("--base", help="the commit the sub-plan started from (not needed with --seed-ledger)")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--seed-ledger", action="store_true")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, default=ROOT / "data" / "diagnosis_truth.csv")
    p.add_argument("--legs", type=Path, default=ROOT / "data" / "diagnosis_truth_legs.csv")
    p.add_argument("--changes", type=Path, default=ROOT / "data" / "diagnosis_truth_changes.csv")
    p.add_argument("--loop-dir", type=Path, default=ROOT / dl.LOOP_DIR)
    args = p.parse_args(argv)
    if not args.seed_ledger and not args.base:
        p.error("--base is required for a round")
    ledger_path = args.loop_dir / "diagnosed.csv"
    try:
        truth_rows = dl.read_csv(args.truth)
        id_changes = dl.read_csv(args.output_dir / "contract" / "id_changes.csv")
        truth_rows, renames = dl.rename_truth(truth_rows, id_changes)
        legs = load_legs(args.legs) if args.legs.exists() else {}
        cases = parse_rows(truth_rows, str(args.truth), legs)
        tables = Tables.read(args.output_dir)
        judged = judge_all(cases, LibraryRows.of(tables, _legs_rows(args.output_dir)))
        ledger = dl.read_ledger(ledger_path)
    except (TruthFileError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    if renames:
        write_diagnosis_truth(args.truth, [{c: r[c] for c in COLUMNS} for r in truth_rows])
        dl.write_changes(args.changes, dl.read_csv(args.changes) + renames)
    keys = dl.ledger_keys(ledger)
    if args.seed_ledger:
        seeded = dl.seed_rows(judged, keys, args.label)
        dl.write_ledger(ledger_path, ledger + seeded)
        print(json.dumps({"label": args.label, "seeded": len(seeded), "ledger": str(ledger_path)}))
        return 0
    try:
        base, new = snapshot_at(args.repo, args.base, args.output_dir), read_snapshot(args.output_dir)
    except RegressionInputError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    report = diff_contract(base, new, excluded(cases, base.delistings, new.delistings, id_changes=new.id_changes))
    write_report(args.output_dir / "regression_report.csv", report)
    mismatches = [m for j in judged for m in j.mismatches if dl.mismatch_key(m) not in keys]
    regressions = [r for r in report if regression_key(r) not in keys]
    rows = dl.case_rows(mismatches, regressions, tables, label=args.label, round_no=args.round,
                        truth_sec={c.case_id: c.sec_id for c in cases})
    path = args.loop_dir / args.label / f"round-{args.round}" / "cases.csv"
    dl.write_cases(path, rows)
    print(json.dumps({"label": args.label, "round": args.round, "mismatches_new": len(mismatches),
                      "regressions_new": len(regressions), "renamed": len(renames),
                      "cases": [{"case_id": r["case_id"], "mode": r["mode"], "ticker": r["ticker"]} for r in rows],
                      "path": str(path)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

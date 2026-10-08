"""One diagnosis-loop round's error list, or the ledger's seed (spec 2026-10-03-diagnosis-truth-fixes, 1.7).

  python scripts/truth_loop_round.py --label 5a --base <commit> --round 1
  python scripts/truth_loop_round.py --label 5-0 --seed-ledger

A round does five things:
1. It renames truth rows and legs that name a renamed security: by the run's contract/id_changes.csv and by comparing
   the --base commit's securities.csv with the run's (that file is not cumulative), and commits the truth set (the
   truth file, its legs and its change log together).
2. It judges the run under --output-dir against the truth file.
3. It writes output/regression_report.csv against --base.
4. It keeps the errors the ledger has not seen.
5. It writes them as case rows to output/diagnose_unknown_report/loop/<label>/round-<N>/cases.csv.

The truth file is --truth, by default the one data/scorecard.json names; its legs and change log are named after it
(`truth_set`). It prints one JSON line with the counts, the cases and the path. --seed-ledger records every current
mismatch as `known` (the reports already describe them), committed with the truth set. Offline (git only). Exit 2: a
missing or unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection.diagnosis_truth import LibraryRows, judge_all
from delist_detection.regression import build_report, id_changes_since, regression_key, write_report
from delist_detection.run_snapshot import RunSnapshot, SnapshotError
from delist_detection.truth import TruthFileError
from delist_detection.truth_set import TruthSet, configured

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True, help="the sub-plan, e.g. 5a")
    p.add_argument("--base", help="the commit the sub-plan started from (not needed with --seed-ledger)")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--seed-ledger", action="store_true")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, help="the truth file (default: the one the repo's data/scorecard.json names)")
    p.add_argument("--loop-dir", type=Path, default=ROOT / dl.LOOP_DIR)
    args = p.parse_args(argv)
    if not args.seed_ledger and not args.base:
        p.error("--base is required for a round")
    ledger_path = args.loop_dir / "diagnosed.csv"
    try:
        truth = TruthSet.open(args.truth or configured(args.repo), ledger=ledger_path)
        run = RunSnapshot.read(args.output_dir)
        base = None if args.seed_ledger else RunSnapshot.at(args.repo, args.base, args.output_dir)
        id_changes = list(run.id_changes or []) if base is None else id_changes_since(base, run)
        renamed = truth.rename(id_changes)
        cases = truth.cases
        judged = judge_all(cases, LibraryRows.of(run))
        truth.commit()
    except (TruthFileError, SnapshotError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    keys = truth.ledger_keys
    if args.seed_ledger:
        truth.settle(dl.seed_rows(judged, keys, args.label))
        truth.commit()
        print(json.dumps({"label": args.label, "seeded": len(truth.settled), "ledger": str(ledger_path)}))
        return 0
    try:
        report = build_report(base, run, cases, id_changes)
    except (SnapshotError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    write_report(args.output_dir / "regression_report.csv", report)
    mismatches = [m for j in judged for m in j.mismatches if dl.mismatch_key(m) not in keys]
    regressions = [r for r in report if regression_key(r) not in keys]
    rows = dl.case_rows(mismatches, regressions, run, label=args.label, round_no=args.round,
                        truth_sec={c.case_id: c.sec_id for c in cases})
    path = args.loop_dir / args.label / f"round-{args.round}" / "cases.csv"
    dl.write_cases(path, rows)
    print(json.dumps({"label": args.label, "round": args.round, "mismatches_new": len(mismatches),
                      "regressions_new": len(regressions), "renamed": renamed,
                      "cases": [{"case_id": r["case_id"], "mode": r["mode"], "ticker": r["ticker"]} for r in rows],
                      "path": str(path)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Open one diagnosis-loop round, or seed the ledger (spec 2026-10-03-diagnosis-truth-fixes, 1.7).

  python scripts/truth_loop_round.py --label 5a --base <commit> --round 1
  python scripts/truth_loop_round.py --label 5-0 --seed-ledger

Opening a round (`loop_round.Round.open`) renames the truth rows and legs that name a renamed security (by the run's
contract/id_changes.csv and by comparing the --base commit's securities.csv with the run's) and commits the truth
set, judges the run under --output-dir against it, writes <output-dir>/regression_report.csv against --base, keeps
the errors the ledger has not seen and writes them as case rows to <loop-dir>/<label>/round-<N>/cases.csv.
--seed-ledger (`loop_round.Loop.seed`) records every current mismatch as `known` (the reports already describe
them), committed with the truth set.

The truth file is --truth, by default the one data/scorecard.json names; its legs and change log are named after it
(`truth_set`), and the ledger is the loop folder's (`loop_round.Loop.ledger`). It prints one JSON line with the
counts, the cases and the path. Offline (git only). Exit 2: a missing or unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from delist_detection.measurement.loop_round import LOOP_DIR, Loop
from delist_detection.outputs.run_snapshot import RunSnapshot, SnapshotError
from delist_detection.measurement.truth import TruthFileError
from delist_detection.measurement.truth_set import configured

ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True, help="the sub-plan, e.g. 5a")
    p.add_argument("--base", help="the commit the sub-plan started from (not needed with --seed-ledger)")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--seed-ledger", action="store_true")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, help="the truth file (default: the one the repo's data/scorecard.json names)")
    p.add_argument("--loop-dir", type=Path, default=ROOT / LOOP_DIR)
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if not args.seed_ledger and not args.base:
        p.error("--base is required for a round")
    try:
        loop = Loop.of(args.repo, args.loop_dir)
        truth = args.truth or configured(args.repo)
        run = RunSnapshot.read(args.output_dir)
        if args.seed_ledger:
            done = loop.seed(truth, run, label=args.label)
        else:
            base = RunSnapshot.at(args.repo, args.base, args.output_dir)
            done = loop.round(args.label, args.round).open(truth, run, base,
                                                           report=args.output_dir / "regression_report.csv")
    except (TruthFileError, SnapshotError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(done.line()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Compare this run's contract with a base commit's, outside the diagnosis truth set (spec
2026-10-03-diagnosis-truth-fixes, section 1.4).

  python scripts/regression_report.py --base <commit>     # -> output/regression_report.csv

Offline (git only). Both runs are read as run snapshots (`run_snapshot.RunSnapshot`). Exit 2: the base commit or the
output folder lacks a contract file (or holds one of another layout), or the truth file is bad.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from delist_detection.measurement.regression import build_report, write_report
from delist_detection.outputs.run_snapshot import RunSnapshot, SnapshotError
from delist_detection.measurement.truth import TruthFileError
from delist_detection.measurement.truth_set import TruthSet, configured

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", required=True, help="the commit the sub-plan started from")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, help="the truth file (default: the one the repo's data/scorecard.json names)")
    p.add_argument("--out", type=Path, default=ROOT / "output" / "regression_report.csv")
    args = p.parse_args(argv)
    try:
        cases = TruthSet.open(args.truth or configured(args.repo)).cases
        rows = build_report(RunSnapshot.at(args.repo, args.base, args.output_dir), RunSnapshot.read(args.output_dir),
                            cases)
    except (SnapshotError, TruthFileError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    write_report(args.out, rows)
    print(f"{len(rows)} changed field(s) in {len({r['sec_id'] for r in rows})} securities -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

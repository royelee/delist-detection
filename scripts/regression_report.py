"""Compare this run's contract with a base commit's, outside the diagnosis truth set (spec
2026-10-03-diagnosis-truth-fixes, section 1.4).

  python scripts/regression_report.py --base <commit>     # -> output/regression_report.csv

Offline (git only). Exit 2: the base commit or the output folder lacks a contract file, or the truth file is bad.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from delist_detection.diagnosis_truth import load_diagnosis_truth
from delist_detection.regression import (RegressionInputError, diff_contract, excluded, read_snapshot, snapshot_at,
                                         write_report)
from delist_detection.truth import TruthFileError

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", required=True, help="the commit the sub-plan started from")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, default=ROOT / "data" / "diagnosis_truth.csv")
    p.add_argument("--out", type=Path, default=ROOT / "output" / "regression_report.csv")
    args = p.parse_args(argv)
    try:
        base, new = snapshot_at(args.repo, args.base, args.output_dir), read_snapshot(args.output_dir)
        cases = load_diagnosis_truth(args.truth) if args.truth.exists() else []
    except (RegressionInputError, TruthFileError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    rows = diff_contract(base, new, excluded(cases, base.delistings, new.delistings, id_changes=new.id_changes))
    write_report(args.out, rows)
    print(f"{len(rows)} changed field(s) in {len({r['sec_id'] for r in rows})} securities -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Close one diagnosis-loop round: apply it to data/diagnosis_truth.csv (spec 2026-10-03-diagnosis-truth-fixes, 1.6).

  python scripts/update_truth.py --label 5a --round 1 --base <commit>
  python scripts/update_truth.py --label pilot --round 1 --base HEAD --dry-run   # print the outcome, write nothing

Closing a round (`loop_round.Round.close`) reads <loop-dir>/<label>/round-<N>/cases.csv and the records/*.json beside
it; the truth set (--truth, by default the file data/scorecard.json names, its legs, its change log and the loop
folder's ledger); the contract at --base and the run under --output-dir. It applies the round (truth_update's rules:
a regression of a sec_id the run lacks, or of a placeholder renamed since --base, adds no truth row), turns every
known_wrong case that now matches into pass, commits the truth set (the truth file, its change log and the ledger
together) and writes the round's summary.md. It prints one JSON line of counts. Offline (git only). Exit 2: a
missing or unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from delist_detection.loop_round import LOOP_DIR, Loop
from delist_detection.run_snapshot import RunSnapshot, SnapshotError
from delist_detection.truth import TruthFileError
from delist_detection.truth_set import configured

ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, help="the truth file (default: the one the repo's data/scorecard.json names)")
    p.add_argument("--loop-dir", type=Path, default=ROOT / LOOP_DIR)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        rnd = Loop.of(args.repo, args.loop_dir).round(args.label, args.round)
        truth = args.truth or configured(args.repo)
        base, run = RunSnapshot.at(args.repo, args.base, args.output_dir), RunSnapshot.read(args.output_dir)
        done = rnd.close(truth, run, base, dry_run=args.dry_run)
    except (TruthFileError, SnapshotError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(done.line()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

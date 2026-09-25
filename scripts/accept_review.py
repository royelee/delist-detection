"""Bulk-accept every output/review.csv row carrying one flag, appending
`accept` decisions to data/review_decisions.csv (review_triage.accept_by_flag /
append_decisions do the work; this script is a thin CLI). Offline: reads and
writes only local CSVs, no network.

    python scripts/accept_review.py --flag terms_gate_failed --note "sampled 5, all fine"
    python scripts/accept_review.py --flag no_form25 --bucket merger --note "checked EDGAR" --dry-run
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.review_triage import ReviewDecisionError, accept_by_flag, append_decisions

DEFAULT_REVIEW = str(ROOT / "output" / "review.csv")
DEFAULT_DECISIONS = str(ROOT / "data" / "review_decisions.csv")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Accept every current review.csv row carrying one flag, in one decisions-file append.")
    p.add_argument("--flag", required=True,
                   help="Flag name to accept (the text before ':', e.g. terms_gate_failed)")
    p.add_argument("--note", required=True, help="What you checked; recorded on every decision, must be non-empty")
    p.add_argument("--bucket", default=None, help="Only rows whose bucket equals this")
    p.add_argument("--review", default=DEFAULT_REVIEW, help="review.csv to read (default output/review.csv)")
    p.add_argument("--decisions", default=DEFAULT_DECISIONS,
                   help="decisions CSV to append to (default data/review_decisions.csv)")
    p.add_argument("--dry-run", action="store_true", help="Report the count without writing")
    return p


def main() -> int:
    p = build_parser()
    args = p.parse_args()
    if not args.note.strip():
        p.error("--note must be non-empty")
    try:
        with open(args.review, newline="") as fh:
            review_rows = list(csv.DictReader(fh))
    except FileNotFoundError:
        p.error(f"--review {args.review}: file not found")
    try:
        decisions = accept_by_flag(review_rows, args.flag, note=args.note, bucket=args.bucket)
    except ReviewDecisionError as exc:
        p.error(str(exc))
    n = append_decisions(args.decisions, decisions, dry_run=args.dry_run)
    verb = "would add" if args.dry_run else "added"
    where = f" (bucket={args.bucket})" if args.bucket else ""
    print(f"{verb} {n} decision(s) for flag {args.flag!r}{where} to {args.decisions}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

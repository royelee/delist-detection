"""Apply one diagnosis-loop round to data/diagnosis_truth.csv (spec 2026-10-03-diagnosis-truth-fixes, 1.6).

  python scripts/update_truth.py --label 5a --round 1 --base <commit>
  python scripts/update_truth.py --label pilot --round 1 --base HEAD --dry-run   # print the outcome, write nothing

It reads:
- output/diagnose_unknown_report/loop/<label>/round-<N>/cases.csv, and the records/*.json beside it;
- the truth set: --truth (by default the file data/scorecard.json names), its legs, its change log and the ledger;
- the contract at --base and under --output-dir, the run's securities and the placeholders renamed since --base
  (a regression of a sec_id the run lacks, or of a renamed placeholder, adds no truth row).

It applies the round (`TruthSet.apply_round`), turns every known_wrong case that now matches into pass
(`TruthSet.flip`), commits the truth set (the truth file, its change log and the ledger together) and writes the
round's summary.md. It prints one JSON line of counts. Offline (git only). Exit 2: a missing or unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection.atomic_io import write_atomic
from delist_detection.diagnosis_truth import LibraryRows
from delist_detection.regression import id_changes_since
from delist_detection.run_snapshot import RunSnapshot, SnapshotError
from delist_detection.truth import TruthFileError
from delist_detection.truth_set import TruthSet, configured

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, help="the truth file (default: the one the repo's data/scorecard.json names)")
    p.add_argument("--loop-dir", type=Path, default=ROOT / dl.LOOP_DIR)
    args = p.parse_args(argv)
    round_dir = args.loop_dir / args.label / f"round-{args.round}"
    try:
        cases = dl.read_csv(round_dir / "cases.csv")
        if not (round_dir / "cases.csv").exists():
            raise ValueError(f"{round_dir / 'cases.csv'}: missing")
        records = {f.stem: json.loads(f.read_text()) for f in sorted((round_dir / "records").glob("*.json"))}
        truth = TruthSet.open(args.truth or configured(args.repo), ledger=args.loop_dir / "diagnosed.csv")
        base, new = RunSnapshot.at(args.repo, args.base, args.output_dir), RunSnapshot.read(args.output_dir)
        renamed = {r["old_sec_id"] for r in id_changes_since(base, new)}
        base_rows = {r["sec_id"]: r for r in base.require("contract_delistings")}
        new_rows = {r["sec_id"]: r for r in new.require("contract_delistings")}
        run_sec_ids = {r["sec_id"] for r in new.securities}
        lib = LibraryRows.of(new)      # a status flip judges a basket's legs too (sub-plan 5f)
    except (SnapshotError, TruthFileError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    rel_reports = (round_dir / "reports").relative_to(args.repo).as_posix() if round_dir.is_relative_to(args.repo) \
        else str(round_dir / "reports")
    try:
        res = truth.apply_round(cases, records, base_rows, new_rows, label=args.label, round_no=args.round,
                                report_dir=rel_reports, run_sec_ids=run_sec_ids, renamed=renamed)
        truth.flip(lib)
    except (TruthFileError, ValueError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    changes = truth.changes
    summary = {"label": args.label, "round": args.round, "cases": len(cases), "records": len(records),
               "truth_changes": len(changes), "ledger_rows": len(truth.settled), "retry": res.pending,
               "dry_run": args.dry_run}
    if not args.dry_run:
        # The truth file, the change log and the ledger move together: all are replaced, or none.
        truth.commit()
        lines = [f"# Loop {args.label}, round {args.round}", "", f"- cases: {len(cases)}, records: {len(records)}",
                 f"- truth changes: {len(changes)}", f"- retried next round (no record): {res.pending or 'none'}",
                 "", "| case | field | old | new | reason |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {c['case_id']} | {c['field']} | {c['old']} | {c['new']} | {c['reason']} |" for c in changes]
        write_atomic(round_dir / "summary.md", "\n".join(lines) + "\n")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())

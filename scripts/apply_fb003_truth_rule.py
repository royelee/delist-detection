"""FB-003, reopened (2026-10-12), applied to the diagnosis truth set (data/diagnosis_truth.csv and its change log,
committed together: `truth_set.TruthSet`).

  PYTHONPATH=src python scripts/apply_fb003_truth_rule.py [--truth PATH]

The old News Corporation's class A stock (NWS-A, then Twenty-First Century Fox's FOXA) was the placeholder
`CIK1308161-COMMON`. The issuer has two lines with no class letter the run can tell apart, so since FB-003 each
placeholder carries its CUSIP: the class A line is `CIK1308161-COMMON-65248E104`. A truth row that names the old
placeholder names a security the run no longer has; its `sec_id` becomes the line's id now. No other cell and no
status moves (the flip rule moves a status). The case_id stays.

`RENAMED` holds the ids. Cell-based and idempotent (a second run adds no change and no note). The loop's own rename
(`TruthSet.rename`) does not reach this row: contract/id_changes.csv lists a placeholder that became a FIGI, and this
placeholder became another placeholder.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delist_detection.measurement.truth import TruthFileError  # noqa: E402
from delist_detection.measurement.truth_set import Ruling, TruthSet, configured  # noqa: E402

TAG = "FB-003 (reopened) 2026-10-12"
REASON = ("the placeholder of the old News Corp class A line carries its CUSIP since FB-003 (the issuer has two "
          "lines with no class letter): {old} is {new} now, the same line, NWS-A to 2013-07-02 and FOXA after")
RENAMED = {"CIK1308161-COMMON": "CIK1308161-COMMON-65248E104"}


def rulings(truth: TruthSet) -> list[Ruling]:
    """The rulings the truth set still needs: none once no row names an old id."""
    return [Ruling(r["case_id"], [("sec_id", RENAMED[r["sec_id"]])],
                   REASON.format(old=r["sec_id"], new=RENAMED[r["sec_id"]]), tag=TAG)
            for r in truth.rows if r["sec_id"] in RENAMED]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--truth", type=Path, help="the truth file (default: the one data/scorecard.json names)")
    args = p.parse_args(argv)
    try:
        truth = TruthSet.open(args.truth or configured(ROOT))
        for ruling in rulings(truth):
            truth.rule(ruling)
        truth.commit()
    except TruthFileError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    print(f"{len(truth.changes)} truth changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

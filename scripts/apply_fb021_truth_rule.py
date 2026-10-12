"""FB-021 (2026-10-12), applied to the diagnosis truth set (data/diagnosis_truth.csv and its change log, committed
together: `truth_set.TruthSet`).

  PYTHONPATH=src python scripts/apply_fb021_truth_rule.py [--truth PATH]

The contract's `cash_per_share` is now all the cash one share received: a dividend the target paid its holders
because the deal closed is in it when the last close still carried it (`payout_gate._counted`). Before, the operator
ruling of 2026-10-04 left every special dividend out of the value, and a truth row scored the merger's cash alone.
A `cash_per_share` cell that states the cash without such a dividend states the old rule, so it becomes `*` (not
scored). No status moves.

`*` and not the sum because the committed output predates the rule: the sum would fail the `pass` case on it. The
output's rebuild sets the sum.

`WITHOUT_DIVIDEND` names the cases: the cell the old rule wrote, and the sum the new rule publishes. Cell-based and
idempotent (a second run adds no change and no note).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delist_detection.measurement.truth import TruthFileError  # noqa: E402
from delist_detection.measurement.truth_set import Ruling, TruthSet, configured  # noqa: E402

TAG = "FB-021 rule change 2026-10-12"
REASON = ("cash_per_share is all the cash one share received, a closing dividend the last close still carried "
          "included; the cell's {old} is the merger's cash alone, and the new rule publishes {new}, so the cell is "
          "not scored until the output is rebuilt")
WITHOUT_DIVIDEND = {
    # PRE: $137.50 of the merger, a $3.00 special dividend and a $0.13 pro rata dividend to the holders at the closing
    "BBG000BBBP59_2016-03-28": ("137.50", "140.63 (137.50 + 3.00 special + 0.13 pro rata)"),
}


def rulings(truth: TruthSet) -> list[Ruling]:
    """The rulings the truth set still needs: none once every cell is `*` (a cell that no longer holds the old
    rule's value is left alone)."""
    out = []
    for r in truth.rows:
        old, new = WITHOUT_DIVIDEND.get(r["case_id"], ("", ""))
        if old and r["cash_per_share"].strip() == old:
            out.append(Ruling(r["case_id"], [("cash_per_share", "*")], REASON.format(old=old, new=new), tag=TAG))
    return out


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

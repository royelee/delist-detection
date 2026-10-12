"""FB-021 (2026-10-12), applied to the diagnosis truth set (data/diagnosis_truth.csv and its change log, committed
together: `truth_set.TruthSet`).

  PYTHONPATH=src python scripts/apply_fb021_truth_rule.py [--truth PATH]

The contract's `cash_per_share` is now all the cash one share received: a dividend the target paid its holders
because the deal closed is in it when the last close still carried it (`payout_gate._counted`). Before, the operator
ruling of 2026-10-04 left every special dividend out of the value, and a truth row scored the merger's cash alone.
A `cash_per_share` cell that states the cash without such a dividend states the old rule, so it takes the sum the
filing's own sentences give. No status moves.

The cell was `*` (not scored) from the fix's commit to the output's rebuild, because the committed output predated
the rule and the sum would have failed the `pass` case on it. The change log keeps both steps.

`WITHOUT_DIVIDEND` names the cases: the cell the old rule wrote, the sum, and its parts. Cell-based and idempotent (a
second run adds no change and no note).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delist_detection.measurement.truth import TruthFileError  # noqa: E402
from delist_detection.measurement.truth_set import Ruling, TruthSet, configured  # noqa: E402

TAG = "FB-021 rule change 2026-10-12"
REBUILT = "FB-021 rule change, the output rebuilt 2026-10-12"
REASON = ("cash_per_share is all the cash one share received, a closing dividend the last close still carried "
          "included; the cell's {old} was the merger's cash alone, and the closing 8-K states {parts}")
WITHOUT_DIVIDEND = {
    # PRE: the closing 8-K (0000950103-16-011958) states the three amounts
    "BBG000BBBP59_2016-03-28": ("137.50", "140.63", "$137.50 of the merger, a $3.00 special dividend to every holder "
                                "immediately before the effective time and a $0.13 pro rata dividend to holders of "
                                "record on the closing date"),
}


def rulings(truth: TruthSet) -> list[Ruling]:
    """The rulings the truth set still needs: none once every cell holds its sum (a cell that holds neither the old
    rule's value nor the `*` of the commits before the rebuild is left alone)."""
    out = []
    for r in truth.rows:
        old, new, parts = WITHOUT_DIVIDEND.get(r["case_id"], ("", "", ""))
        if old and r["cash_per_share"].strip() in (old, "*"):
            out.append(Ruling(r["case_id"], [("cash_per_share", new)], REASON.format(old=old, parts=parts),
                              tag=REBUILT))
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

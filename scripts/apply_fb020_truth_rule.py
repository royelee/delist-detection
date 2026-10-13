"""FB-019 and FB-020 (2026-10-12), applied to the diagnosis truth set (data/diagnosis_truth.csv and its change log,
committed together: `truth_set.TruthSet`).

  PYTHONPATH=src python scripts/apply_fb020_truth_rule.py [--truth PATH]

The contract's `last_trade_date` is now the day the library holds, whatever its source (`exit_kind.published`).
Before, decision 12 published only a confirmed exchange print and left the cell blank otherwise, and a truth row
scored that blank. A cell that was blank for that reason alone states nothing about the ending any more, so it
becomes `*` (not scored). No day is added and no status moves: the day itself is scored where the truth holds one, in
`internal_last_trade_date`, and the contract's day is delistings.csv's day of the same row. The contract's price date
follows its last trade date (the trading day after), so a blank `price_date` goes with it on a row whose value rule
prices something (`PRICED`, or a rule not scored); a cash merger's blank price date is still blank, and scored.

Two groups, each cell-based and idempotent (a second run adds no change and no note):

- every case of shape `ending` or `ending_moved` whose `last_trade_date` is blank and whose
  `internal_last_trade_date` is a day: the truth says the ending has a day, which the contract withheld;
- `UNRULED`: the cases blank in both cells for which the library holds a day no exchange print confirms. The truth
  never ruled on that day (AQNT and RESP by the operator ruling of 2026-10-03: no source states the last session),
  so neither cell scores it.

A case blank in both cells for which the library holds no day keeps its blank: the cell is still blank, and scored.
`*` and not the day because the committed output predates the rule: a day would fail every such `pass` case on it.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delist_detection.measurement.truth import TruthFileError  # noqa: E402
from delist_detection.measurement.truth_set import Ruling, TruthSet, configured  # noqa: E402

TAG = "FB-019 and FB-020 rule change 2026-10-12"
SCORED_INSIDE = ("the contract publishes the day the library holds, whatever its source; the blank was decision 12's "
                 "(no confirmed exchange print), so the cell is not scored and internal_last_trade_date scores the day")
NEVER_RULED = ("the contract publishes the day the library holds, whatever its source; the blank was decision 12's "
               "(no confirmed exchange print) and the truth never ruled on the day the library holds ({day}, {source}), "
               "so neither cell scores it")
UNRULED = {
    "BBG000BMB7R1_2016-05-17": ("2016-05-17", "a handoff day with no source"),            # ITT
    "BBG000BMZLP6_2007-08-20": ("2007-08-10", "closing_day"),                             # AQNT
    "BBG000BS3FD4_2008-03-27": ("2008-03-14", "closing_day"),                             # RESP
    "BBG000BT0093_2024-09-10": ("2024-09-10", "a handoff day with no source"),            # SIRI
    "BBG000Q5RW63_2014-07-01": ("2014-07-01", "a handoff day with no source"),            # NRF
    "BBG00WYYC600_2017-11-09": ("2017-11-09", "a handoff day with no source"),            # WLL
    "BBG000F0KF42_5a-r2": ("2021-05-18", "closing_day"),                                  # STX
    "CIK1611983-COMMON_fb3-r1": ("2015-01-09", "closing_day"),                            # LBKRV
}
PRICED = ("stock", "cash_plus_stock", "basket", "otc_print", "*")    # value rules whose row carries a price date


def _cells(row: dict[str, str]) -> list[tuple[str, str]]:
    cells = [("last_trade_date", "*")]
    if not row["price_date"].strip() and row["value_rule"].strip() in PRICED:
        cells.append(("price_date", "*"))
    return cells


def rulings(truth: TruthSet) -> list[Ruling]:
    """The rulings the truth set still needs: none once every cell is `*` (a cell already `*` is left alone)."""
    out = []
    for r in truth.rows:
        if r["last_trade_date"].strip() or r["shape"] not in ("ending", "ending_moved"):
            continue
        if r["case_id"] in UNRULED:
            day, source = UNRULED[r["case_id"]]
            out.append(Ruling(r["case_id"], _cells(r), NEVER_RULED.format(day=day, source=source), tag=TAG))
        elif r["internal_last_trade_date"].strip() not in ("", "*"):
            out.append(Ruling(r["case_id"], _cells(r), SCORED_INSIDE, tag=TAG))
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

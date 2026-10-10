"""Sub-plan 5h's truth rulings (2026-10-04), applied to the diagnosis truth set (data/diagnosis_truth.csv and its change
log, committed together: `truth_set.TruthSet`). Only rows 5h owns (fixed_by 5h). The reasons:
docs/superpowers/plans/research/2026-10-04-5h-identity.md, section 4 (decision 6).

  PYTHONPATH=src python scripts/apply_5h_truth_rulings.py              # the ruling that holds now (applied)
  PYTHONPATH=src python scripts/apply_5h_truth_rulings.py --after-run  # the identity renames, once output/ holds a
                                                                       # full run of 5h's code

The identity renames name the security a run of 5h's code gives each case's era (read from --output-dir's
observation_map.csv, through the run snapshot): only such a run holds it, so applied before, the committed tables fail
the D.mismatches.sec_id floor. --truth names another truth file (default: the one data/scorecard.json names).
Idempotent: a ruling applies once (the truth set's rule); a second run, in either mode, changes nothing.
"""
import argparse
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delist_detection.outputs.run_snapshot import RunSnapshot, SnapshotError  # noqa: E402
from delist_detection.measurement.truth import TruthFileError  # noqa: E402
from delist_detection.measurement.truth_set import Ruling, TruthSet, configured  # noqa: E402

WHY = "5h ruling 2026-10-04 (identity follows the issuer and FIGI, R2)"
REPORT = "docs/superpowers/plans/research/2026-10-04-5h-identity.md"
rule = partial(Ruling, tag=WHY, report=REPORT, owner="5h")

NOW = [
    rule("BBG000BQHGR6_2026-09-28",     # OKE
         (("fixed_by", "5d"),),
         "5h links the continuation (its successor BBG024TZWVN1 past the fails data's end); what remains is the last "
         "trade date (worked out, so blank in the contract), 5d's"),
]
# case -> (the era whose sec_id the run gives, other cells, why)
AFTER_RUN = {
    "CIK1141399-COMMON_2008-09-20": (   # ABBI
        "ABBI@2008-01-16", (),
        "the observed security is the new Abraxis BioScience's (CIK 1409012), as the report finds; stage 2b's "
        "name_in_force check gives the era that issuer"),
    "CIK73887-COMMON_2013-06-28": (     # ERA
        "ERA@2013-06-28", (),
        "the observation belongs to Era Group (CIK 1525221), as the report finds; stage 2b's ticker_rows check gives "
        "the era that issuer (the fails rows under ERA say ERA GROUP INC)"),
    "BBG00Y04KP80_5a-r2": (             # CRC
        "CRC@2014-12-31", (("shape", "ending_moved"),),
        "controller ruling 2026-10-04 (5a acceptance): the 2014-2020 line is BBG0060B3M63 (the 2016 split's CUSIP "
        "13057Q206; BBG00Y04KP80 is the post-2020 line). On it the 2016 event is no ending and the line ends later "
        "(the 2020 bankruptcy, not scored here)"),
}


def after_run(observation_map) -> list[Ruling]:
    """The identity rulings, each naming the sec_id the run's observation_map gives its case's era."""
    held = {r["era"]: r["sec_id"] for r in observation_map if r["sec_id"]}
    return [rule(cid, (("sec_id", held[era]), *cells), why) for cid, (era, cells, why) in AFTER_RUN.items()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--after-run", action="store_true")
    p.add_argument("--truth", type=Path, help="the truth file (default: the one data/scorecard.json names)")
    p.add_argument("--output-dir", type=Path, default=ROOT / "output", help="the run --after-run reads")
    args = p.parse_args(argv)
    try:
        rulings = after_run(RunSnapshot.read(args.output_dir).observation_map) if args.after_run else NOW
        truth = TruthSet.open(args.truth or configured(ROOT))
        for ruling in rulings:
            truth.rule(ruling)
        truth.commit()
    except (TruthFileError, SnapshotError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    print(len(truth.changes), "truth change rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

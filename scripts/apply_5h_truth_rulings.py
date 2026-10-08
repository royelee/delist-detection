"""Sub-plan 5h's truth rulings (2026-10-04), applied to data/diagnosis_truth.csv with change-log rows, through
`diagnosis_loop.write_together` (both files or neither). Only rows 5h owns (fixed_by 5h). The reasons:
docs/superpowers/plans/research/2026-10-04-5h-identity.md, section 4 (decision 6).

  PYTHONPATH=src python scripts/apply_5h_truth_rulings.py              # the ruling that holds now (applied)
  PYTHONPATH=src python scripts/apply_5h_truth_rulings.py --after-run  # the identity renames, once output/ holds a
                                                                       # full run of 5h's code

The identity renames name the security a run of 5h's code gives each case's era (read from
output/observation_map.csv, through the run snapshot): only such a run holds it, so applied before, the committed tables fail the
D.mismatches.sec_id floor.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delist_detection import diagnosis_loop as dl  # noqa: E402
from delist_detection.diagnosis_truth import COLUMNS, load_legs, parse_rows  # noqa: E402
from delist_detection.run_snapshot import RunSnapshot  # noqa: E402

TRUTH, LEGS = ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_legs.csv"
CHANGES = ROOT / "data/diagnosis_truth_changes.csv"
WHY = "5h ruling 2026-10-04 (identity follows the issuer and FIGI, R2)"
REPORT = "docs/superpowers/plans/research/2026-10-04-5h-identity.md"

NOW = {
    "BBG000BQHGR6_2026-09-28": (        # OKE
        [("fixed_by", "5d")],
        "5h links the continuation (its successor BBG024TZWVN1 past the fails data's end); what remains is the last "
        "trade date (worked out, so blank in the contract), 5d's"),
}
# case -> (the era whose sec_id the run gives, other cells, why)
AFTER_RUN = {
    "CIK1141399-COMMON_2008-09-20": (   # ABBI
        "ABBI@2008-01-16", [],
        "the observed security is the new Abraxis BioScience's (CIK 1409012), as the report finds; stage 2b's "
        "name_in_force check gives the era that issuer"),
    "CIK73887-COMMON_2013-06-28": (     # ERA
        "ERA@2013-06-28", [],
        "the observation belongs to Era Group (CIK 1525221), as the report finds; stage 2b's ticker_rows check gives "
        "the era that issuer (the fails rows under ERA say ERA GROUP INC)"),
    "BBG00Y04KP80_5a-r2": (             # CRC
        "CRC@2014-12-31", [("shape", "ending_moved")],
        "controller ruling 2026-10-04 (5a acceptance): the 2014-2020 line is BBG0060B3M63 (the 2016 split's CUSIP "
        "13057Q206; BBG00Y04KP80 is the post-2020 line). On it the 2016 event is no ending and the line ends later "
        "(the 2020 bankruptcy, not scored here)"),
}


def _era_sec_ids() -> dict[str, str]:
    return {r["era"]: r["sec_id"] for r in RunSnapshot.read(ROOT / "output").observation_map if r["sec_id"]}


def main() -> int:
    if "--after-run" in sys.argv[1:]:
        held = _era_sec_ids()
        rulings = {cid: ([("sec_id", held[era]), *cells], why) for cid, (era, cells, why) in AFTER_RUN.items()}
    else:
        rulings = NOW
    rows = dl.read_csv(TRUTH)
    changes = []
    for r in rows:
        if r["case_id"] not in rulings:
            continue
        cells, why = rulings[r["case_id"]]
        if r["fixed_by"] != "5h" and ("fixed_by", r["fixed_by"]) not in cells:
            continue                # a later ruling moved the row on (wave 1 relabelled OKE to residual): leave it
        changed = False
        for f, v in cells:
            if r[f] != v:
                changed = True
                changes.append(dict(case_id=r["case_id"], field=f, old=r[f], new=v, reason=f"{WHY}: {why}",
                                    report=REPORT))
                r[f] = v
        if changed:                 # idempotent: a second run, in either mode, adds neither a change nor the note
            r["note"] = f"{r['note']}; {WHY}: {why}"
    parse_rows(rows, str(TRUTH), load_legs(LEGS))
    dl.write_together([(TRUTH, COLUMNS, rows), (CHANGES, dl.CHANGE_COLUMNS, dl.read_csv(CHANGES) + changes)])
    print(len(changes), "truth change rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

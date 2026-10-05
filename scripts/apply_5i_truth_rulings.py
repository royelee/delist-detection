"""Sub-plan 5i's truth rulings (2026-10-04), applied to data/diagnosis_truth.csv with change-log rows, through
`diagnosis_loop.write_together` (both files or neither). The reasons: docs/superpowers/plans/research/2026-10-04-5i-verdicts.md,
section 5.

  PYTHONPATH=src python scripts/apply_5i_truth_rulings.py

Three groups, each cell-based (a cell is set only when it differs, so the script reads the file as it stands and
leaves every other cell to the sub-plan that owns it: 5f edits other cells of THE and ABI) and idempotent (a second
run adds no change and no note):

- `RULINGS`: the 11 rows with fixed_by 5i. 5i changes verdicts only (spec 2.3), never a contract field, so none of
  them can pass by 5i's code: each goes to the sub-plan that owns what is left of it, or to the residual list. Three
  of them also take ruling R8 on their own EX-99.25 notice ("this security was suspended from trading on D": the
  last trade is the trading day before D, a published day), which their truth rows predate.
- `WAVE2`: the controller's R8 rulings on THE, ABI, LEG and OKE (`controller ruling 2026-10-04 (wave 2)`), each on
  its own NYSE notice in the cache. A row the ruling leaves with no mismatch turns `pass`.
- `NOTES`: a ruling that changes no cell (the four Liberty 2023 rows' last trade), and `CORRECTIONS`, a reason a
  ruling stated wrongly (MEL's exit kind), corrected in the note and in the change log.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delist_detection import diagnosis_loop as dl  # noqa: E402
from delist_detection.diagnosis_truth import COLUMNS, load_legs, parse_rows  # noqa: E402

TRUTH, LEGS = ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_legs.csv"
CHANGES = ROOT / "data/diagnosis_truth_changes.csv"
WHY = "5i ruling 2026-10-04"
WHY2 = "controller ruling 2026-10-04 (wave 2)"
REPORT = "docs/superpowers/plans/research/2026-10-04-5i-verdicts.md"
R8 = "ruling R8 on the NYSE 25-NSE notice {acc} ('{quote}'): the last trade is the trading day before, published"

MEL_BLOCK = ("its own matched 25-NSE (filed under CIK 64782, accession 0000876661-07-000586) states 'Each share of "
             "Common Stock of Mellon Financial Corporation was converted into one share of Common Stock of (New) The "
             "Bank of New York Mellon Corporation', which 5c's reader reads as one for one, ratio 1.0, no cash; what "
             "blocks the continuation is stage 8b's successor link (the BK line BBG000BD8PN9, issuer 1390777, starts "
             "in ticker_history only on 2007-12-21); 5i changes no contract field")
MEL_WRONG = ("5c's R1 reads the registrant's own 8-Ks, and Mellon filed none that states the exchange (the merger 8-K "
             "is The Bank of New York Mellon's, CIK 1390777); no remaining sub-plan reads a successor's filing for "
             "it, and 5i changes no contract field")
CORRECTIONS = [("BBG000BNXLK1_2007-07-12", MEL_WRONG, MEL_BLOCK)]

RULINGS = {
    "BBG000BH5K72_2007-12-28": (        # DJ
        [("last_trade_date", "2007-12-13"), ("fixed_by", "5f")],
        R8.format(acc="0000876661-07-000947", quote="suspended from trading on December 14, 2007")
        + "; what is left (cash_currency) is 5f's"),
    "CIK718482-COMMON_2007-10-11": (    # AGE
        [("last_trade_date", "2007-09-28"), ("price_date", "2007-10-01"), ("fixed_by", "5f")],
        R8.format(acc="0000876661-07-000790", quote="became effective before the opening on October 1, 2007 ... "
                                                    "suspended from trading on October 1, 2007")
        + ", and the price date is the trading day after it (spec 2.1); what is left (cash_currency) is 5f's"),
    "BBG000BNXLK1_2007-07-12": (        # MEL
        [("last_trade_date", "2007-06-29"), ("fixed_by", "residual")],
        R8.format(acc="0000876661-07-000586", quote="suspended from trading on July 2, 2007")
        + "; the exit kind is residual: " + MEL_BLOCK),
    "BBG000JBSJZ4_2014-07-01": (        # FNF
        [("fixed_by", "residual")],
        "what is left (internal_last_trade_date, the continued-filings row dated by the last sighting) is a "
        "last-trade reading 5d did not build; 5i changes no contract field"),
    "BBG00BDQ1H13_2022-10-10": (        # TEAM
        [("fixed_by", "residual")],
        "what is left (the last trade 2022-09-30 the scheme's 8-K states) is the handoff row's dating, a 5d reading "
        "that its unmatched Form 25 does not reach; 5i changes no contract field (its verdict stays timing-only: "
        "no R1 reading of the scheme)"),
    "BBG00BFHD827_2023-08-13": ([("fixed_by", "5f")], "what is left (the basket and its legs, R3) is 5f's"),
    "BBG00BFHD9S7_2023-08-13": ([("fixed_by", "5f")], "what is left (the basket and its legs, R3) is 5f's"),
    "BBG00BFHDCV6_2023-08-13": ([("fixed_by", "5f")], "what is left (the basket and its legs, R3) is 5f's"),
    "BBG00BFHDFR4_2023-08-13": ([("fixed_by", "5f")], "what is left (the basket and its legs, R3) is 5f's"),
    "CIK1355096-COMMON_2018-04-11": (   # QRTEA
        [("fixed_by", "residual")],
        "what is left (no ending: the placeholder is one line with BBG000PCQQL6, R2) is identity work 5a and 5h did "
        "not reach; 5i changes no contract field"),
    "CIK1620280-COMMON_2017-02-28": (   # CSAL
        [("fixed_by", "residual")],
        "what is left (no ending: the same-CIK rename to Uniti is one line, R2) is identity work 5a did not reach; "
        "5i changes no contract field"),
}

# the controller's R8 rulings: the library already publishes each day (the truth rows called them worked out)
WAVE2 = {
    "BBG000L93Q69_2007-07-22": (        # THE: cash_currency is 5f's, the row stays known_wrong
        [("last_trade_date", "2007-07-11"), ("price_date", "2007-07-12")],
        R8.format(acc="0000876661-07-000606", quote="suspended from trading on July 12, 2007")
        + ", and the price date is the trading day after it; what is left (cash_currency) is 5f's"),
    "BBG000FJJW82_2008-12-06": (        # ABI: the same
        [("last_trade_date", "2008-11-21"), ("price_date", "2008-11-24")],
        R8.format(acc="0000876661-08-000491", quote="suspended from trading on November 24, 2008")
        + ", and the price date is the trading day after it; what is left (cash_currency) is 5f's"),
    "BBG000BN53G7_2026-09-06": (        # LEG: nothing left, the row passes
        [("last_trade_date", "2026-08-26"), ("price_date", "2026-08-27"), ("status", "pass"), ("fixed_by", "")],
        R8.format(acc="0000876661-26-000712", quote="suspended from trading before market open on August 27, 2026")
        + " (R8's open case), and the price date is the trading day after it; the row matches on every scored field"),
    "BBG000BQHGR6_2026-09-28": (        # OKE: a continuation, no price date; nothing left, the row passes
        [("last_trade_date", "2026-09-09"), ("status", "pass"), ("fixed_by", "")],
        R8.format(acc="0000876661-26-000770", quote="suspended from trading on September 10, 2026")
        + "; the row matches on every scored field"),
}

# a ruling that changes no cell: the four Liberty 2023 rows keep a last-trade mismatch the baskets do not touch
_LIBERTY = ("the truth's last trade 2023-08-03 stands, on the 8-K 0001104659-23-087380 (item 3.03: the Reclassification "
            "'effective as of 5:00 p.m. New York City time' on August 3, 2023; the new series 'expected to begin "
            "trading ... on August 4, 2023'); this is a note, not an R8 ruling (no notice says 'suspended'). The "
            "library's 2023-08-04 is the handoff row's last sighting (source last_sighting), the day the new series "
            "began; no sub-plan reads a reclassification's effective time for a handoff row, so the row keeps this "
            "internal_last_trade_date mismatch after 5f's basket work and stays known_wrong until a later one does")
NOTES = {c: _LIBERTY for c in ("BBG00BFHD827_2023-08-13", "BBG00BFHD9S7_2023-08-13",
                               "BBG00BFHDCV6_2023-08-13", "BBG00BFHDFR4_2023-08-13")}


def _apply(r, cells, why, tag, changes) -> None:
    changed = False
    for f, v in cells:
        if r[f] != v:
            changed = True
            changes.append(dict(case_id=r["case_id"], field=f, old=r[f], new=v, reason=f"{tag}: {why}",
                                report=REPORT))
            r[f] = v
    if changed:
        r["note"] = f"{r['note']}; {tag}: {why}"


def main() -> int:
    rows = dl.read_csv(TRUTH)
    log = dl.read_csv(CHANGES)
    changes: list[dict] = []
    for r in rows:
        cid = r["case_id"]
        if cid in RULINGS:
            cells, why = RULINGS[cid]
            # a later ruling that moved the row on is left alone
            if r["fixed_by"] == "5i" or ("fixed_by", r["fixed_by"]) in cells:
                _apply(r, cells, why, WHY, changes)
        if cid in WAVE2:
            _apply(r, WAVE2[cid][0], WAVE2[cid][1], WHY2, changes)
        if cid in NOTES and NOTES[cid] not in r["note"]:
            changes.append(dict(case_id=cid, field="note", old="", new=NOTES[cid], reason=f"{WHY2}: {NOTES[cid]}",
                                report=REPORT))
            r["note"] = f"{r['note']}; {WHY2}: {NOTES[cid]}"
        for case_id, old, new in CORRECTIONS:
            if cid == case_id and old in r["note"]:
                r["note"] = r["note"].replace(old, new)
    for case_id, old, new in CORRECTIONS:          # the change log states the same reason
        for c in log:
            if c["case_id"] == case_id and old in c["reason"]:
                c["reason"] = c["reason"].replace(old, new)
    parse_rows(rows, str(TRUTH), load_legs(LEGS))
    dl.write_together([(TRUTH, COLUMNS, rows), (CHANGES, dl.CHANGE_COLUMNS, log + changes)])
    print(f"{len(changes)} truth changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

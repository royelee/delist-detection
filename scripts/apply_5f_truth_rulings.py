"""Sub-plan 5f's truth rulings (2026-10-04), applied to data/diagnosis_truth.csv and data/diagnosis_truth_legs.csv
with change-log rows, through `diagnosis_loop.write_together` (all three files or none). The rows are 5f's
(fixed_by 5f) and the two pass rows the brief carries to 5f (VMED's legs, R3; MHS's currency, R5), which become
known_wrong fixed_by 5f until output/ holds a run of 5f's code. The reasons:
docs/superpowers/plans/research/2026-10-04-5f-terms.md, section 5 (Decisions).

  PYTHONPATH=src python scripts/apply_5f_truth_rulings.py

Idempotent: a second run changes nothing.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delist_detection import diagnosis_loop as dl  # noqa: E402
from delist_detection.diagnosis_truth import COLUMNS, LEG_COLUMNS, parse_rows  # noqa: E402

TRUTH, LEGS = ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_legs.csv"
CHANGES = ROOT / "data/diagnosis_truth_changes.csv"
WHY = "5f ruling 2026-10-04"
REPORT = "docs/superpowers/plans/research/2026-10-04-5f-terms.md"
CARRIED = {"BBG000D3MB18_wave1-r1", "BBG000MRMY60_wave1-r1"}       # pass rows the brief carries to 5f
LATER = [("status", "known_wrong"), ("fixed_by", "5f")]          # until output/ holds a run of 5f's code

# case -> (cells, its legs: None keeps them, a list replaces them, why)
RULINGS = {
    "BBG000BLBGS2_2025-12-20": (        # SCS
        [("last_trade_date", "2025-12-09"), ("price_date", "2025-12-10")], None,
        "MIDAS dates the last trade 2025-12-09 (exchange volume, a publishable print: spec 1.2 and decision 12, as "
        "the operator ruled for ROVI's MIDAS day); the truth's own internal day; price date the session after"),
    "BBG000QGWY50_2025-06-12": (        # BLUE
        [("cash_per_share", "3.00")], None,
        "ruling R4: the closing 8-K (0001193125-25-132850) says holders who made no election are deemed to have "
        "made the Cash and CVR election, so the default package is $3.00 cash, the CVR a note; the report read no "
        "default"),
    "BBG006F8QZK4_2024-12-07": (        # VSTO
        [("value_rule", "cash_plus_stock"), ("stock_ratio", "1.0"), ("price_ticker", "GEAR"),
         ("price_date", "2024-11-27")], [],
        "ruling R3: a basket is two or more securities per share; $25.75 and one Revelyst share is one security and "
        "cash, published on the main row as cash_plus_stock (as CCE 2010's $10.00 and one New CCE share is)"),
    "BBG000D3MB18_wave1-r1": (          # VMED
        [*LATER, ("value_rule", "basket"), ("price_sec_id", "")],
        [{"leg": "1", "ratio": "0.2582", "price_sec_id": "BBG01K9HZH92", "price_ticker": "LBTYA",
          "price_date": "2013-06-10"},
         {"leg": "2", "ratio": "0.1928", "price_sec_id": "*", "price_ticker": "LBTYK", "price_date": "2013-06-10"}],
        "ruling R3 (the brief's VMED item): the closing 8-K 0001193125-13-256243 gives $17.50, 0.2582 Liberty Global "
        "class A and 0.1928 class C per share, a basket of two securities; the main row keeps the cash and no "
        "security, payout_legs.csv the legs (LBTYA on the wave 1 loop's line, the class C line not scored)"),
    "BBG000MRMY60_wave1-r1": (          # MHS
        [*LATER, ("cash_currency", "USD")], None,
        "ruling R5: the filing states the $28.80 cash in dollars; the wave 1 loop's regression row kept the base "
        "run's blank, which no source states"),
}


# 5f's rows a run of 5f's code still misses (the offline replay of the final code over the measurement run's
# caches), to the residual list with what would reach them (spec 2.4: the operator accepts the list)
_TICKER = "the LLM names the stock leg's issuer without its ticker and the run holds no line of it"
_LEFT = {
    "BBG000BBB3K1_2017-08-04": "prompt v3 still reads 1 BAT ADS for ADSs representing 0.5260 of an ordinary share",
    "BBG000BDN878_2019-03-04": "the terms are in the 6-K's EX-99.1 exhibit; the extractor reads primary documents only",
    "BBG006LYGNL7_2021-10-16": "the exchange offer's terms and last day are in 6-K exhibits the extractor does not read",
    "BBG000BF5RY1_2016-06-10": f"{_TICKER} (CCEP as CCE)",
    "BBG000BK1FD3_2014-12-04": f"{_TICKER} (AMFW)",
    "BBG000C496P7_2025-08-17": f"{_TICKER} (PSKY)",
    "BBG006F8QZK4_2024-12-07": f"{_TICKER} (Revelyst, GEAR)",
    "BBG000BJ9D07_2016-09-08": "R1's name tie needs TiVo Corp's former name (Titan Technologies), which no source gives",
    "BBG000BJV732_2007-12-01": "the prorated aggregate is in Vulcan's own 8-K exhibit, not a filing of the target; the "
                               "last trade too (5d)",
    "BBG000BX67G5_2008-05-24": "the last day is in the 3.01 8-K's EX-99.1 (\"after the close of market today\"), which "
                               "the last-trade reader does not read",
    "BBG000FJJW82_2008-12-06": "the published day is the notice's merger-effective day, which the truth calls worked "
                               "out (the notice reader's rule, 5d)",
    "BBG000L93Q69_2007-07-22": "prompt v3 states no package for TODCO's equalized election; the published day as ABI's",
    "BBG000H89QJ6_2016-05-28": "0.48908178 New Charter shares is stated only in the Form 25 notice",
    "BBG000M34GG1_2022-07-31": "the 2022 closing 8-K is MIC Hawaii's (CIK 1845290), not the run's issuer's",
    "BBG000PYZSR8_2016-05-18": "only the worked-out last trade is left (no Form 25; the last sighting, 5d)",
    "BBG0017T9998_2020-07-30": "only the published last trade is left (the loop's ruling: MIDAS's 07-20; 5d)",
    "BBG003P9ZSL3_2016-04-28": "R1 at the handoff stage: the timing continuation into new LMCA needs the exchange "
                               "statement's three securities (exchange_terms at the handoff, not built)",
    "BBG005SW6TK5_2016-04-28": "as LMCA 2016: R1 at the handoff stage",
    "CIK891103-COMMON_2014-06-30": "the line is not followed past its 2014 observations to the 2020 separation, and "
                                   "the handoff's basket needs R1 at the handoff stage",
    "BBG00DJ2LJF5_2019-01-07": "spec 5c rule 6 on the continued-filings branch (the class V election into class C), "
                               "not measured: built only on the successor branch",
    "BBG00FFJY867_2025-05-17": "the second leg's 1/15 is Starz's consolidation after the closing; the LLM gives 1",
    "CIK18568-COMMON_2007-09-16": "the truth's aggregate is inferred from 425 totals, not stated; R4 without a "
                                  "stated package publishes the all-cash alternative",
}

def main() -> int:
    rows = dl.read_csv(TRUTH)
    legs = dl.read_csv(LEGS)
    changes = []
    for r in rows:
        cid = r["case_id"]
        if cid not in RULINGS or (r["fixed_by"] != "5f" and cid not in CARRIED):
            continue
        cells, new_legs, why = RULINGS[cid]
        if cid in CARRIED and r["fixed_by"] == "5f":
            cells = [c for c in cells if c not in LATER]      # already moved: leave a later status flip alone
        changed = False
        for f, v in cells:
            if r[f] != v:
                changed = True
                changes.append(dict(case_id=cid, field=f, old=r[f], new=v, reason=f"{WHY}: {why}", report=REPORT))
                r[f] = v
        if new_legs is not None:
            old_legs = [x for x in legs if x["case_id"] == cid]
            want = [{"case_id": cid, **x} for x in new_legs]
            if [{c: x[c] for c in LEG_COLUMNS} for x in old_legs] != want:
                changed = True
                show = lambda ls: "; ".join(f"{x['leg']}: {x['ratio']} {x['price_ticker']}" for x in ls)  # noqa: E731
                changes.append(dict(case_id=cid, field="legs", old=show(old_legs), new=show(want),
                                    reason=f"{WHY}: {why}", report=REPORT))
                legs = [x for x in legs if x["case_id"] != cid] + want
        if changed:
            r["note"] = f"{r['note']}; {WHY}: {why}"
    for r in rows:                  # after the rulings above (VSTO's R3 ruling is its own)
        why = _LEFT.get(r["case_id"])
        if why is not None and r["fixed_by"] == "5f":
            changes.append(dict(case_id=r["case_id"], field="fixed_by", old="5f", new="residual",
                                reason=f"{WHY}: residual: {why}", report=REPORT))
            r["fixed_by"] = "residual"
            r["note"] = f"{r['note']}; {WHY}: residual: {why}"
    if not changes:
        print("no change")
        return 0
    parse_rows(rows, str(TRUTH))
    dl.write_together([(TRUTH, COLUMNS, rows), (LEGS, LEG_COLUMNS, legs),
                       (CHANGES, dl.CHANGE_COLUMNS, dl.read_csv(CHANGES) + changes)])
    print(f"{len(changes)} changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

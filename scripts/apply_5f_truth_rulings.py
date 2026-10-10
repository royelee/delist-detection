"""Sub-plan 5f's truth rulings (2026-10-04), applied to the diagnosis truth set (data/diagnosis_truth.csv, its legs and
its change log, committed together: `truth_set.TruthSet`). The rows are 5f's (fixed_by 5f) and the two pass rows the
brief carries to 5f (VMED's legs, R3; MHS's currency, R5), which became known_wrong fixed_by 5f until output/ held a
run of 5f's code. The reasons: docs/superpowers/plans/research/2026-10-04-5f-terms.md, section 5 (Decisions).

  PYTHONPATH=src python scripts/apply_5f_truth_rulings.py [--truth PATH]

The rulings are data (`Ruling`): first `RULINGS`, then `LEFT` (5f's rows a run of 5f's code still misses, to the
residual list), then `RESTORED` (back from the residual list). Idempotent: a ruling applies once (the truth set's
rule), so a second run, or a run after a later change moved a ruled cell on (the wave 2 loop's flips of VMED and MHS to
pass), changes nothing.
"""
import argparse
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delist_detection.measurement.truth import TruthFileError  # noqa: E402
from delist_detection.measurement.truth_set import Ruling, TruthSet, configured  # noqa: E402

WHY = "5f ruling 2026-10-04"
REPORT = "docs/superpowers/plans/research/2026-10-04-5f-terms.md"
LATER = (("status", "known_wrong"), ("fixed_by", "5f"))        # until output/ holds a run of 5f's code
rule = partial(Ruling, tag=WHY, report=REPORT, owner="5f")

RULINGS = [
    rule("BBG000BLBGS2_2025-12-20",     # SCS
         (("last_trade_date", "2025-12-09"), ("price_date", "2025-12-10")),
         "MIDAS dates the last trade 2025-12-09 (exchange volume, a publishable print: spec 1.2 and decision 12, as "
         "the operator ruled for ROVI's MIDAS day); the truth's own internal day; price date the session after"),
    rule("BBG000QGWY50_2025-06-12",     # BLUE
         (("cash_per_share", "3.00"),),
         "ruling R4: the closing 8-K (0001193125-25-132850) says holders who made no election are deemed to have "
         "made the Cash and CVR election, so the default package is $3.00 cash, the CVR a note; the report read no "
         "default"),
    rule("BBG006F8QZK4_2024-12-07",     # VSTO
         (("value_rule", "cash_plus_stock"), ("stock_ratio", "1.0"), ("price_ticker", "GEAR"),
          ("price_date", "2024-11-27")),
         "ruling R3: a basket is two or more securities per share; $25.75 and one Revelyst share is one security and "
         "cash, published on the main row as cash_plus_stock (as CCE 2010's $10.00 and one New CCE share is)",
         legs=()),
    rule("BBG000D3MB18_wave1-r1",       # VMED, a pass row the brief carries to 5f
         (*LATER, ("value_rule", "basket"), ("price_sec_id", "")),
         "ruling R3 (the brief's VMED item): the closing 8-K 0001193125-13-256243 gives $17.50, 0.2582 Liberty Global "
         "class A and 0.1928 class C per share, a basket of two securities; the main row keeps the cash and no "
         "security, payout_legs.csv the legs (LBTYA on the wave 1 loop's line, the class C line not scored)",
         legs=({"leg": "1", "ratio": "0.2582", "price_sec_id": "BBG01K9HZH92", "price_ticker": "LBTYA",
                "price_date": "2013-06-10"},
               {"leg": "2", "ratio": "0.1928", "price_sec_id": "*", "price_ticker": "LBTYK",
                "price_date": "2013-06-10"}),
         owner=None),
    rule("BBG000DST2V3_2012-06-04",     # EP: the controller's R4 ruling, whatever its fixed_by
         (("cash_per_share", "14.65"), ("stock_ratio", "0.4187")),
         "controller ruling 2026-10-04 (R4: non-electors' package): the closing 8-K 0001193125-12-253764 states the "
         "result for each election class and that \"Holders of approximately 14.9% of outstanding New El Paso shares "
         "... made no election. These holders will receive the Mixed Consideration\" (0.4187 of a share of Kinder "
         "Morgan Class P common stock, $14.65 in cash and 0.640 of a warrant); the stock electors' prorated 14.53 and "
         "0.4231 is an elector class's result, not the package",
         owner=None),
    rule("BBG000MRMY60_wave1-r1",       # MHS, a pass row the brief carries to 5f
         (*LATER, ("cash_currency", "USD")),
         "ruling R5: the filing states the $28.80 cash in dollars; the wave 1 loop's regression row kept the base "
         "run's blank, which no source states",
         owner=None),
]

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
LEFT = [rule(cid, (("fixed_by", "residual"),), f"residual: {why}") for cid, why in _LEFT.items()]

# rows the review fixes (2026-10-04) bring back from the residual list: the either-or reading of the earlier prompt's
# cached answer reaches THE's terms ($16.00 + 0.979 HERO), which v3 states no leg for
RESTORED = [rule("BBG000L93Q69_2007-07-22", (("fixed_by", "5f"),),
                 "restored from residual: the review fix keeps the earlier prompt's cached either-or reading when v3 "
                 "states no leg of an election with no stated default; the row's terms match again",
                 owner="residual")]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--truth", type=Path, help="the truth file (default: the one data/scorecard.json names)")
    args = p.parse_args(argv)
    try:
        truth = TruthSet.open(args.truth or configured(ROOT))
        for ruling in (*RULINGS, *LEFT, *RESTORED):
            truth.rule(ruling)
        if not truth.changes:
            print("no change")
            return 0
        truth.commit()
    except TruthFileError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    print(f"{len(truth.changes)} changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Sub-plan 5g's real cases (tests/distress_cases.py over tests/fixtures/distress/): the bankruptcy and liquidation
endings stage 5 gives them, and the drop reason, plan exchange and OTC symbol stage 9e reads for them. Each tuple is
(delist_date, bucket, CRSP code, drop reason, value rule, price ticker, stock ratio)."""
import pytest

from delist_detection.distress import price_only
from delist_detection.form25 import parse_form25
from distress_cases import EDGAR, FixtureEdgar, after, outcome

LAST = -1      # the security's last ending, the one the contract publishes


@pytest.mark.parametrize("sec_id, ticker, symbol", [
    ("BBG000BG09F5", "GPOR", "GPORQ"), ("BBG000BLY636", "IMB", "IDMC"), ("BBG000BRF6B5", "RHD", "RHDC"),
    ("BBG000BRWGG9", "RAD", "RADCQ"), ("BBG000DY8ZS4", "WFT", "WFTIF"), ("BBG000PSSG77", "IAR", "IDAR"),
    ("BBG009NGKQ45", "VRM", "VRMMQ"), ("BBG00D1WHZD9", "HTZ", "HTZGQ"), ("BBG00HY28P97", "GTX", "GTXMQ"),
    ("BBG000BJ3CN0", "CWTR", "CWTRQ"), ("BBG000BP62Y3", "MNI", "MNIQQ"), ("BBG000BGZ9V9", "ASNA", "ASNAQ"),
    ("BBG000FH5YM1", "FTR", "FTRCQ"), ("BBG000BBMT95", "DF", "DFODQ"), ("BBG0057K5Y79", "EPE", "EPEG"),
    ("BBG000BBG3P1", "TMA", "THMR"), ("BBG000BMLYZ2", "KWK", "KWKA"), ("BBG00ZSDS6T8", "TSP", "TSPH"),
])
def test_a_drop_is_priced_under_the_first_other_symbol_of_its_own_cusip(sec_id, ticker, symbol):
    got = outcome(sec_id)[LAST]
    assert got[4:6] == ("otc_print", symbol)


@pytest.mark.parametrize("sec_id, symbol", [
    ("BBG00GBV88T6", "BTUUQ"),      # BTU: its post-split CUSIP is not in its history; the 3.01 names the symbol
    ("CIK886835-COMMON", "SPNX"),   # SPNV: the fails history reads SPNV, another company's ticker; the 3.01 names SPNX
    ("BBG00Z6DX554", "CHKAQ"),      # CHK: no fails under its CUSIP after the last trade
])
def test_without_fails_evidence_the_3_01_notice_names_the_otc_symbol(sec_id, symbol):
    assert outcome(sec_id)[LAST][4:6] == ("otc_print", symbol)


@pytest.mark.parametrize("sec_id, symbol", [
    ("BBG009R0CVG1", "LKSD"),     # trades on under LKSD for months; LKSDQ only in April 2020
    ("BBG000BLDXH5", "MDRX"),     # the OTC Expert Market under its existing symbol
    ("BBG005DKMJ67", "LTRPA"),    # the OTCQB under LTRPA (its 2025 merger is no ending: ruling G4)
])
def test_an_exchange_symbol_that_keeps_trading_is_its_own_otc_symbol(sec_id, symbol):
    assert outcome(sec_id)[LAST][4:6] == ("otc_print", symbol)


@pytest.mark.parametrize("sec_id", [
    "BBG000BF2JS9",     # CNB: two days of fails settling under CNB; the 3.01 names only the NYSE symbol
    "BBG000BT0CM2",     # SIVB: a day of settling fails, no notice names an OTC symbol
    "BBG000CPZ0F5",     # PDLI: a month of fails at the one last close, no trading
    "BBG000BV18Z1",     # TDW: a prepackaged plan, no OTC trading
])
def test_no_evidence_of_an_otc_symbol_publishes_it_blank(sec_id):
    assert outcome(sec_id)[LAST][4:6] == ("otc_print", "")


@pytest.mark.parametrize("sec_id", ["BBG000BBG3P1", "BBG000BMLYZ2", "BBG000PSSG77", "BBG0057K5Y79",
                                    "BBG005DKMJ67", "BBG000DY8ZS4"])
def test_a_removal_for_a_price_deficiency_only_is_dropped_for_price(sec_id):
    """TMA (580 before), KWK, IAR, EPE, LTRPA (Nasdaq 5450(a)(1)) by the exchange's notice; WFT, with no Form 25,
    by its 3.01 notice ("abnormally low price levels"; the chapter 11 it mentions is no listing standard)."""
    got = outcome(sec_id)[LAST]
    assert got[1:4] == ("compliance_failure", 552, "price")


@pytest.mark.parametrize("sec_id, code, reason", [
    ("BBG000BRF6B5", 570, "guidelines"),    # RHD: market capitalization beside the $1 price
    ("CIK886835-COMMON", 570, "guidelines"),  # SPNV: market capitalization
    ("BBG009R0CVG1", 570, "guidelines"),    # LKSD: market capitalization
    ("BBG000BLDXH5", 570, "guidelines"),    # MDRX: a late annual report
    ("BBG00ZSDS6T8", 580, "filings_fees"),  # TSP: its own Form 25 (a voluntary removal) states no exchange reason
    ("BBG000CPZ0F5", 580, "filings_fees"),  # PDLI: the same
])
def test_another_standard_or_a_voluntary_removal_keeps_its_reason(sec_id, code, reason):
    assert outcome(sec_id)[LAST][1:4] == ("compliance_failure", code, reason)


def test_fst_back_door_listing_notice_is_not_a_price_deficiency():
    """FST 2014: the NYSE's notice cites the back-door listing (102.01) beside the sub-$1 price: guidelines. (The
    fixture does not hold the texts 5c's role refusal reads, so FST's ending is judged on its notice alone.)"""
    f25 = parse_form25(EDGAR["raws"]["0000876661-15-000019"], accession="0000876661-15-000019", form="25-NSE",
                       filing_date="2015-01-15")
    assert "102.01" in f25.notice_text and not price_only(f25.notice_text)


def test_sdrl_plan_exchange_is_a_bankruptcy_valued_by_the_stock_rule():
    """SDRL 2018: a 6-K filer with no 8-K items; the NYSE's notice says it emerged from bankruptcy and gave old
    holders 0.0037345 new shares each (R6): no longer unknown, and the stock rule on the new SDRL line."""
    found, _, _ = after("BBG000BKQ3V3")
    assert outcome("BBG000BKQ3V3") == [("2018-07-13", "liquidation", 470, "bankruptcy", "stock", "SDRL", "0.0037345")]
    assert "no_evidence_default" not in found[LAST].flags
    assert found[LAST].record.reason.startswith("Bankruptcy plan exchange (Form 25 2018-07-03 notice")


def test_wolf_plan_exchange_ratio_comes_from_the_plan_8ks_two_counts():
    """WOLF 2025: 1,306,896 new shares for 156,479,390 old (the 871,287-share reserve is conditional)."""
    edgar = FixtureEdgar()
    assert outcome("BBG000BG14P4", edgar=edgar) == [
        ("2025-10-09", "liquidation", 470, "bankruptcy", "stock", "WOLF", "0.00835187")]
    assert "0001193125-25-224251" in edgar.texts_read


def test_a_plan_that_states_no_ratio_keeps_the_otc_print():
    """WLL 2020: each old share became new shares and two series of warrants; no ratio is stated (and no field
    carries warrants), so no stock rule. No OTC symbol either: blank."""
    assert outcome("BBG000PX3XC0")[LAST][1:] == ("liquidation", 470, "bankruptcy", "otc_print", "", "")


def test_a_holding_companys_substitution_notice_is_no_plan_exchange():
    """APA 2021: an exchange transfer under 12d2-2(a)(3), no bankruptcy: stage 9e reads nothing for it."""
    found, terms, _ = after("BBG000BC2C10")
    assert [d.record.bucket.value for d in found] == ["exchange_transfer"]
    assert terms == {}


def test_cbl_bankruptcy_8k_with_a_spaced_item_heading_is_read():
    """CBL 2020: the 8-K's heading reads "ITEM 1 .0 3 Bankruptcy or Receivership" after HTML stripping; read as
    item 1.03 it confirms the bankruptcy, which beats the continued filings: dropped for bankruptcy, priced at the
    first CBLAQ print."""
    got = outcome("BBG000B9YSK6")
    assert len(got) == 1 and got[0][1:] == ("liquidation", 470, "bankruptcy", "otc_print", "CBLAQ", "")


def test_eqc_voluntary_delisting_during_its_liquidation_is_a_liquidation():
    """EQC 2025: its own Form 25 and 3.01 notice, the 8-K announcing its final liquidating distribution and the
    liquidating trust; it kept filing. A liquidation (CRSP 400), not a transfer (operator pre-ruling)."""
    found, _, _ = after("BBG000BLG1L7")
    assert [(d.delist_date, d.record.bucket.value, d.record.crsp_code) for d in found] == [
        ("2025-04-21", "liquidation", 400)]
    assert found[0].record.evidence["end_of_era"] == "liquidation"


# -- PMI 2011: a halt, the suspension 38 days later ---------------------------------------------------------------

def test_pmi_otc_symbol_is_the_one_the_fails_show_40_days_after_the_halt():
    """PMI 2011: the fails settle at 0.31 for a month, two OTC prints (0.05, 0.04) are still filed under PMI, and PPMIQ
    follows 40 days after the last trade. A 3-letter exchange symbol that shows no trading of its own is no OTC
    symbol."""
    assert outcome("BBG000BCTL84")[LAST][4:6] == ("otc_print", "PPMIQ")


# -- the R6 plan: its received close, and the old line's own last close ------------------------------------------

def _wolf():
    from datetime import date

    from delist_detection.manifest import StageMeter
    from delist_detection.pipeline import Overrides, _RunContext
    from distress_cases import AS_OF, DATA, clients, world
    found, terms, _ = after("BBG000BG14P4")
    securities, cusips, ftd = world()
    ctx = _RunContext(clients(), AS_OF, lambda *a: None, 1, StageMeter(lambda *a: None))
    return found[LAST], terms, securities, cusips, ftd, date.fromisoformat(DATA["ftd_from"]), ctx, Overrides()


def test_an_answered_plan_received_close_is_the_plans_value_not_the_shumway_fill():
    """WOLF 2025: stage 10g asks the new line's received close; with the answer the ending's dlret is the ratio x
    that close / the last close - 1 (a second run changes values only), never the bucket's Shumway -30%. Its method
    is its own (sub-plan 5f): a plan's new shares are no OTC print."""
    from delist_detection.dlret import DlretMethod
    from delist_detection.pipeline import Overrides, _plan_values
    from delist_detection.reconstruction import build_delistings_table
    d, terms, _, _, _, _, _, ov = _wolf()
    ratio = float(terms[d.key].plan_ratio)
    ov.acquirer_prices[d.key] = ("WOLF", 22.0)
    ov = _plan_values(ov, terms)
    assert ov.otc_prints == {}
    rows = build_delistings_table([d.record], last_trade_closes={d.key: 1.85}, otc_prints=ov.otc_prints,
                                  plan_values=ov.plan_values, exchanges={d.key: d.exchange})
    assert rows[0].dlret == pytest.approx(ratio * 22.0 / 1.85 - 1)
    assert rows[0].dlret_method is DlretMethod.PLAN_STOCK
    # an answer for another ticker is not the plan's
    assert _plan_values(Overrides(acquirer_prices={d.key: ("XXXX", 22.0)}), terms).plan_values == {}
    # an answered OTC print of the same ending wins: the plan value is not set
    assert _plan_values(Overrides(acquirer_prices={d.key: ("WOLF", 22.0)}, otc_prints={d.key: 1.0}),
                        terms).plan_values == {}


def test_a_plan_endings_last_close_is_never_the_new_lines():
    """WOLF 2025: the old CUSIP's last row is 9-26 (1.85); the new CUSIP (the notice names it) shares the ticker and
    has a 9-30 row at 22.10. The close is the old line's, flagged as a prior one."""
    from delist_detection.pipeline import _last_trade_closes
    d, _, securities, cusips, ftd, ftd_lo, ctx, ov = _wolf()
    assert d.last_trade.day.isoformat() == "2025-09-26"
    closes = _last_trade_closes(ctx, [d], securities, cusips, ftd, ftd_lo, ov)
    assert closes.get(d.key) != 22.1
    assert closes[d.key] == pytest.approx(1.85)
    assert any(f.startswith("ftd_close_prior") for f in d.flags)


# -- stage 9e's degraded path ---------------------------------------------------------------------------------------

def test_a_failed_read_in_stage_9e_gives_a_resolution_degraded_row():
    """WOLF's plan 8-K read counts itself degraded (a failed request, a stale copy): the delisting's own row and a
    review item carry resolution_degraded; the ratio read still stands (it is flagged, not dropped)."""
    from delist_detection.sec_stats import SEC_STATS

    class Degrading(FixtureEdgar):
        def fetch_filing_text(self, cik, accession, primary_doc):
            if accession == "0001193125-25-224251":
                SEC_STATS.degraded("filing text")
            return super().fetch_filing_text(cik, accession, primary_doc)

    found, terms, review = after("BBG000BG14P4", edgar=Degrading())
    assert "resolution_degraded" in found[LAST].flags
    assert any(i.flag == "resolution_degraded" and i.sec_id == "BBG000BG14P4" for i in review)
    assert terms[found[LAST].key].plan_ratio == "0.00835187"


def test_a_refusal_in_stage_9e_stops_the_run():
    from delist_detection.edgar import EdgarBlocked

    class Blocked(FixtureEdgar):
        def fetch_filing_text(self, cik, accession, primary_doc):
            raise EdgarBlocked("403")

    with pytest.raises(EdgarBlocked):
        after("BBG000BG14P4", edgar=Blocked())

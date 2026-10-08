"""dlret at its interface (architecture step 10): an ending's DLRET from its value inputs (`decide`: each method, its
value, its confidence, measured against fill, the table's cell and the firm month's DLRET), its value rule from its
delistings.csv row (`rule_of`: each rule and the one order a liquidation's value and rule read), and the contract's
value cells (`contract_value`)."""
import math

import pytest

from delist_detection.vocabulary.crsp_codes import CrspBucket
from delist_detection.outputs.dlret import (
    FILL, MEASURED, METHODS, SHUMWAY_NASDAQ, SHUMWAY_NYSE_AMEX, DistressTerms, DlretMethod, MergerInputs, ValueInputs,
    contract_value, decide, rule_of,
)
from delist_detection.vocabulary.exchanges import Exchange
from delist_detection.vocabulary.exit_kind import VALUE_RULES
from lifecycle_tables import ending

M, X, L, C, E, U = (CrspBucket.MERGER, CrspBucket.EXCHANGE_TRANSFER, CrspBucket.LIQUIDATION,
                    CrspBucket.COMPLIANCE_FAILURE, CrspBucket.EXPIRATION, CrspBucket.UNKNOWN)


def _v(bucket, exchange=Exchange.NYSE, close=None, **inputs):
    return decide(ValueInputs(bucket, exchange, close, **inputs))


# -- the DLRET: each method, its value and its confidence --------------------------------------------------------
def test_a_cash_merger_is_measured_with_its_reads_confidence():
    v = _v(M, close=100.0, payout_per_share=113.0, payout_confidence="high")
    assert (v.method, v.kind, v.confidence) == (DlretMethod.CASH_ONLY, MEASURED, "high")
    assert v.terminal_value == pytest.approx(113.0) and v.value == pytest.approx(0.13)
    assert v.firm_month == v.value and v.table_dlret == v.value


def test_a_cash_reads_missing_or_invalid_confidence_is_medium():
    for conf in (None, "", "unknown_tier"):
        assert _v(M, close=100.0, payout_per_share=113.0, payout_confidence=conf).confidence == "medium"


def test_aet_cvs_cash_plus_stock():
    # AET->CVS: $145 cash + 0.8378 CVS @ $80, last AET $190 -> +11.6%
    v = _v(M, close=190.0, payout_per_share=145.0, stock_ratio=0.8378, acquirer_price=80.0, payout_confidence="high")
    assert (v.method, v.confidence) == (DlretMethod.CASH_PLUS_STOCK, "medium")   # the stock leg rests on a price
    assert v.terminal_value == pytest.approx(212.024)
    assert v.value == pytest.approx(0.11592, abs=1e-4)


def test_a_stock_merger():
    v = _v(M, close=100.0, stock_ratio=1.5, acquirer_price=80.0)
    assert (v.method, v.confidence, v.kind) == (DlretMethod.STOCK_ONLY, "medium", MEASURED)
    assert v.terminal_value == pytest.approx(120.0) and v.value == pytest.approx(0.20)


def test_a_zero_payout_is_a_total_wipe_and_a_negative_one_has_no_value():
    wipe = _v(M, close=100.0, payout_per_share=0.0)
    assert wipe.method is DlretMethod.CASH_ONLY and wipe.value == pytest.approx(-1.0)
    for bad in ({"payout_per_share": -5.0}, {"stock_ratio": -1.0, "acquirer_price": 5.0}):
        v = _v(M, close=100.0, **bad)
        assert v.method is DlretMethod.UNKNOWN and math.isnan(v.value) and math.isnan(v.firm_month)
        assert v.confidence == "low"


def test_a_half_stock_leg_fails_loud():
    # stock_ratio without acquirer_price would silently understate DLRET to the cash floor
    with pytest.raises(ValueError, match="under-specified"):
        _v(M, close=190.0, payout_per_share=145.0, stock_ratio=0.8378)


def test_terms_without_a_valid_last_close_need_one():
    for bad in (None, 0.0, -5.0):
        v = _v(M, close=bad, payout_per_share=113.0)
        assert v.method is DlretMethod.NEEDS_LAST_TRADE and v.confidence == "low" and v.kind == ""
        assert math.isnan(v.value) and math.isnan(v.table_dlret) and math.isnan(v.firm_month)


def test_a_merger_with_no_consideration_is_assumed_par_in_the_table_and_zero_in_the_firm_month():
    """No empty DLRET in the table: a completed merger with a last close and no consideration assumes terminal = the
    last close (DLRET 0, a low-confidence fill). The firm month compounds the abstain's 0.0, by design (step 10)."""
    v = _v(M, close=10.0)
    assert (v.method, v.value, v.terminal_value, v.confidence, v.kind) == (DlretMethod.ASSUMED_PAR, 0.0, 10.0, "low",
                                                                           FILL)
    assert v.table_dlret == 0.0 and v.firm_month == 0.0


def test_a_merger_with_no_consideration_and_no_valid_price_has_no_value_anywhere():
    for bad in (None, 0.0, -5.0):
        v = _v(M, close=bad)
        assert v.method is DlretMethod.ABSTAIN_NO_CONSIDERATION and math.isnan(v.value)
        assert v.table_dlret is None and math.isnan(v.firm_month)      # blank in the table, a firm-month drop


def test_an_exchange_transfer_is_a_zero_fill_whatever_its_close():
    for close in (10.0, 0.0, None):
        v = _v(X, close=close)
        assert (v.method, v.value, v.confidence, v.kind, v.firm_month) == (
            DlretMethod.EXCHANGE_TRANSFER_ZERO, 0.0, "high", FILL, 0.0)


def test_a_liquidations_recovery_ratio_is_measured():
    v = _v(L, close=10.0, recovery_ratio=0.20)
    assert (v.method, v.confidence, v.kind) == (DlretMethod.RECOVERY_RATIO, "medium", MEASURED)
    assert v.value == pytest.approx(-0.80) and v.terminal_value == pytest.approx(2.0)
    neg = _v(L, close=10.0, recovery_ratio=-0.1)
    assert neg.method is DlretMethod.UNKNOWN and math.isnan(neg.value)


def test_a_drop_or_a_liquidation_without_a_print_takes_the_shumway_mark_of_its_venue():
    assert _v(C, Exchange.NYSE, 10.0).method is DlretMethod.SHUMWAY_NYSE_AMEX
    assert _v(C, Exchange.AMEX, 10.0).value == SHUMWAY_NYSE_AMEX == pytest.approx(-0.30)
    assert _v(C, Exchange.NASDAQ, 10.0).value == SHUMWAY_NASDAQ == pytest.approx(-0.55)
    assert _v(C, Exchange.OTHER, 10.0).value == SHUMWAY_NASDAQ             # conservative for an unknown venue
    v = _v(L, Exchange.NASDAQ, 10.0)
    assert (v.method, v.value, v.confidence, v.kind) == (DlretMethod.SHUMWAY_NASDAQ, SHUMWAY_NASDAQ, "medium", FILL)


def test_a_drop_without_a_valid_last_close_has_no_value():
    for bucket in (L, C):
        for bad in (None, 0.0, -1.0):
            v = _v(bucket, Exchange.NASDAQ, bad, recovery_ratio=0.5)
            assert v.method is DlretMethod.UNKNOWN and math.isnan(v.value) and v.table_dlret is None


def test_an_otc_print_values_a_drop_and_a_liquidation():
    v = _v(C, Exchange.NASDAQ, 2.00, otc_print=0.50)
    assert (round(v.value, 6), v.method, v.terminal_value, v.confidence, v.kind) == (
        -0.75, DlretMethod.OTC_PRINT, 0.50, "medium", MEASURED)
    v = _v(L, Exchange.NYSE, 4.00, otc_print=1.00)
    assert (round(v.value, 6), v.method) == (-0.75, DlretMethod.OTC_PRINT)
    assert _v(C, Exchange.NASDAQ, 2.00, otc_print=0.0).method is DlretMethod.SHUMWAY_NASDAQ   # no print: the mark


def test_a_plan_value_is_measured_and_graded_medium_like_an_otc_print():
    """Step 10's declared fix (controller ruling): a bankruptcy plan's value is the caller's answered close of the
    new line times the plan's ratio, the same kind of measured value as an OTC print, so it is graded medium (it fell
    through to low). lifecycle reads dlret_confidence for an ending's quality."""
    plan = _v(L, Exchange.NYSE, 1.85, plan_value=0.0037345 * 22.0)
    otc = _v(L, Exchange.NYSE, 1.85, otc_print=0.0037345 * 22.0)
    assert (plan.method, plan.kind, plan.confidence) == (DlretMethod.PLAN_STOCK, MEASURED, "medium")
    assert plan.confidence == otc.confidence and plan.value == otc.value == plan.firm_month
    assert plan.terminal_value == pytest.approx(0.0037345 * 22.0)


def test_a_liquidation_takes_its_recovery_then_its_plan_then_its_print():
    assert _v(L, close=4.0, recovery_ratio=0.5, plan_value=1.0, otc_print=1.0).method is DlretMethod.RECOVERY_RATIO
    assert _v(L, close=4.0, plan_value=2.0, otc_print=1.0).method is DlretMethod.PLAN_STOCK
    assert _v(L, close=4.0, plan_value=0.0, otc_print=1.0).method is DlretMethod.OTC_PRINT


def test_a_drop_takes_no_recovery_or_plan_and_a_merger_no_print():
    assert _v(C, Exchange.NASDAQ, 4.0, recovery_ratio=0.5, plan_value=2.0).method is DlretMethod.SHUMWAY_NASDAQ
    assert _v(M, close=10.0, payout_per_share=12.0, otc_print=1.0, recovery_ratio=0.5).method is \
        DlretMethod.CASH_ONLY


def test_an_expiration_is_assumed_par_in_the_table_and_a_drop_in_the_firm_month():
    """A fund or non-equity closure redeems at NAV ≈ its last trade: DLRET 0 in the table. The firm month drops it,
    by design (step 10's measurement: two such endings in output/)."""
    v = _v(E, close=25.0)
    assert (v.method, v.value, v.table_dlret, v.confidence) == (DlretMethod.ASSUMED_PAR, 0.0, 0.0, "low")
    assert math.isnan(v.firm_month)
    v = _v(E, close=None)
    assert v.method is DlretMethod.DROPPED_EXPIRATION and math.isnan(v.value) and math.isnan(v.firm_month)


def test_an_unknown_ending_is_blank_in_the_table_unless_deregistered_with_a_price():
    v = _v(U, close=0.001)
    assert (v.method, v.value, v.table_dlret, v.firm_month, v.confidence) == (DlretMethod.UNKNOWN, 0.0, None, 0.0,
                                                                              "low")
    par = _v(U, close=19.63, deregistered=True)
    assert (par.method, par.value, par.terminal_value, par.table_dlret, par.firm_month) == (
        DlretMethod.ASSUMED_PAR, 0.0, 19.63, 0.0, 0.0)
    assert _v(U, close=None, deregistered=True).method is DlretMethod.UNKNOWN


def test_every_method_has_its_kind_and_confidence_beside_it():
    assert set(METHODS) == set(DlretMethod)
    assert {k for k, _ in METHODS.values()} == {MEASURED, FILL, ""}
    assert {c for _, c in METHODS.values()} <= {"high", "medium", "low"}
    assert {m for m, (k, _) in METHODS.items() if k == MEASURED} == {
        DlretMethod.CASH_ONLY, DlretMethod.STOCK_ONLY, DlretMethod.CASH_PLUS_STOCK, DlretMethod.RECOVERY_RATIO,
        DlretMethod.OTC_PRINT, DlretMethod.PLAN_STOCK, DlretMethod.WORTHLESS}
    assert {m for m, (k, _) in METHODS.items() if k == FILL} == {
        DlretMethod.ASSUMED_PAR, DlretMethod.SHUMWAY_NYSE_AMEX, DlretMethod.SHUMWAY_NASDAQ,
        DlretMethod.EXCHANGE_TRANSFER_ZERO}


def test_worthless_is_reserved_and_never_decided():
    assert DlretMethod.WORTHLESS.value == "worthless"
    for bucket in CrspBucket:
        for close in (None, 4.0):
            assert _v(bucket, close=close, recovery_ratio=0.0, otc_print=0.0).method is not DlretMethod.WORTHLESS


# -- the contract's value cells ----------------------------------------------------------------------------------
def test_a_measured_value_is_dlret_and_a_fill_is_dlret_fill():
    cash = ending("S", "2018-11-29", dlret="0.110000", method="cash_only", crsp_code="231", terminal_value="11.1")
    par = ending("S", "2018-11-29", dlret="0.000000", method="assumed_par", crsp_code="231")
    mark = ending("S", "2020-05-11", "liquidation", dlret="-0.550000", method="shumway_nasdaq", crsp_code="470")
    xfer = ending("S", "2015-10-02", "exchange_transfer", dlret="0.000000", method="exchange_transfer_zero",
                  crsp_code="304")
    assert contract_value(cash) == ("0.110000", "", "11.1")
    assert contract_value(par)[:2] == ("", "0.000000")
    assert contract_value(mark)[:2] == ("", "-0.550000")
    assert contract_value(xfer)[:2] == ("", "0.000000")


def test_an_otc_print_and_a_plan_value_are_measured_not_fills():
    for method in ("otc_print", "plan_stock"):
        r = ending("S", "2012-05-01", "compliance_failure", dlret="-0.750000", method=method, crsp_code="500")
        assert contract_value(r)[:2] == ("-0.750000", "")


def test_a_continuation_has_no_value_and_a_blank_value_stays_blank():
    cont = ending("S", "2015-10-02", "exchange_transfer", successor="T", dlret="0.000000",
                  method="exchange_transfer_zero", crsp_code="304", terminal_value="5.0")
    assert contract_value(cont) == ("", "", "")
    assert contract_value(ending("S", "2009-03-08", "unknown", method="needs_last_trade"))[:2] == ("", "")
    went_on = ending("S", "2019-03-20", "merger", successor="S", dlret="0.100000", method="cash_only")
    assert contract_value(went_on)[0] == "0.100000"           # its own successor: no continuation


# -- the value rule ----------------------------------------------------------------------------------------------
def test_each_bucket_has_its_rule():
    rows = {"cash": ending("S", "2018-11-29", "merger", payout_per_share="10.0", last_trade_close="9.9"),
            "transfer": ending("S", "2015-10-02", "exchange_transfer"),
            "continuation": ending("S", "2015-10-02", "exchange_transfer", successor="T"),
            "recovery": ending("S", "2020-05-11", "liquidation", recovery_ratio="0.1"),
            "otc_print": ending("S", "2012-05-01", "compliance_failure", crsp_code="570"),
            "expiration": ending("S", "2010-01-04", "expiration"),
            "unknown": ending("S", "2009-03-08", "unknown")}
    for name, row in rows.items():
        assert rule_of(row, MergerInputs(), DistressTerms()).name == name
    assert set(rows) <= VALUE_RULES


def test_a_liquidations_rule_takes_a_recovery_else_a_plan_else_worthless_else_a_print():
    plan = DistressTerms(plan_ratio="0.0037345", plan_ticker="SDRL", plan_source="form25_notice")
    rec = ending("A", "2018-07-13", "liquidation", method="recovery_ratio", crsp_code="470", recovery_ratio="0.2")
    r = rule_of(rec, distress=plan)
    assert (r.name, r.recovery_ratio) == ("recovery", 0.2)
    mark = ending("A", "2018-07-13", "liquidation", method="shumway_nyse_amex", crsp_code="470", ticker="SDRL")
    r = rule_of(mark, distress=plan)
    assert (r.name, r.leg.ratio, r.leg.ticker, r.leg.sec_id, r.terms_source) == (
        "stock", "0.0037345", "SDRL", "", "form25_notice")
    assert rule_of(ending("A", "2014-12-20", "liquidation", method="worthless")).name == "worthless"
    r = rule_of(mark, distress=DistressTerms(otc_symbol="SDRLQ"))
    assert (r.name, r.print_sec_id, r.print_symbol) == ("otc_print", "A", "SDRLQ")


def test_a_drops_rule_is_its_print_even_with_a_recovery_or_a_plan():
    r = ending("A", "2014-12-20", "compliance_failure", method="shumway_nasdaq", crsp_code="570", ticker="ABCD",
               recovery_ratio="0.2")
    assert rule_of(r, distress=DistressTerms(plan_ratio="0.5", plan_ticker="X")).name == "otc_print"


def test_an_otc_print_is_named_by_stage_9es_symbol_else_the_exchange_ticker():
    r = ending("A", "2020-11-09", "liquidation", method="shumway_nyse_amex", crsp_code="470", ticker="HTZ")
    assert rule_of(r, distress=DistressTerms(otc_symbol="HTZGQ")).print_symbol == "HTZGQ"
    assert rule_of(r, distress=DistressTerms()).print_symbol == ""          # read, none found
    assert rule_of(r).print_symbol == "HTZ"                                  # not read


def test_the_value_and_the_rule_read_one_order():
    """A liquidation with a recovery and a plan: both the value and the rule take the recovery; with the plan read
    and answered, both take the plan; read and not answered, the rule stays the plan and the value fills its mark."""
    plan = DistressTerms(plan_ratio="0.5", plan_ticker="NEW")
    rec = ending("A", "2018-07-13", "liquidation", crsp_code="470", recovery_ratio="0.2")
    assert (rule_of(rec, distress=plan).name, _v(L, close=4.0, recovery_ratio=0.2, plan_value=2.0).method) == (
        "recovery", DlretMethod.RECOVERY_RATIO)
    row = ending("A", "2018-07-13", "liquidation", crsp_code="470")
    assert (rule_of(row, distress=plan).name, _v(L, close=4.0, plan_value=2.0).method) == (
        "stock", DlretMethod.PLAN_STOCK)
    assert _v(L, close=4.0).method is DlretMethod.SHUMWAY_NYSE_AMEX


def test_a_mergers_rule_follows_its_published_terms():
    cash = rule_of(ending("A", "2014-12-20", last_trade_close="10", payout_per_share="12.5", payout_source="8K_2.01"))
    assert (cash.name, cash.cash, cash.leg, cash.terms_source, cash.terms_gate) == ("cash", 12.5, None, "8K_2.01",
                                                                                  "passed")
    stock = rule_of(ending("A", "2014-12-20", last_trade_close="10", stock_ratio="0.8025", acquirer_ticker="QSR"),
                    MergerInputs(acquirer_sec_id="BBG0QSR"))
    assert (stock.name, stock.leg.ratio, stock.leg.ticker, stock.leg.sec_id) == ("stock", 0.8025, "QSR", "BBG0QSR")
    both = rule_of(ending("A", "2014-12-20", payout_per_share="65.5", stock_ratio="0.8025", acquirer_ticker="QSR"))
    assert (both.name, both.terms_gate) == ("cash_plus_stock", "")         # no last close: no gate verdict
    assert rule_of(ending("A", "2014-12-20", method="assumed_par")).name == "unknown"
    raw = rule_of(ending("A", "2014-12-20", method="assumed_par", last_trade_close="10"),
                  MergerInputs(raw_value=29.44, raw_source="8K_2.01"))
    assert (raw.name, raw.cash, raw.terms_source, raw.terms_gate) == ("cash", 29.44, "8K_2.01", "failed")
    given = rule_of(ending("A", "2014-12-20", payout_per_share="1", stock_ratio="2", acquirer_ticker="XXX"),
                    MergerInputs(override={"cash_per_share": 3.0, "stock_ratio": 0.5, "acquirer_ticker": "QSR"}))
    assert (given.name, given.cash, given.leg.ratio, given.leg.ticker, given.terms_source, given.terms_gate) == (
        "cash_plus_stock", 3.0, 0.5, "QSR", "--merger-terms", "")

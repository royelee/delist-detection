from dataclasses import replace

from delist_detection.terms.llm_merger_extractor import MergerTerms
from delist_detection.vocabulary.exit_kind import VALUE_RULES
from delist_detection.outputs.dlret import MergerInputs
from delist_detection.outputs.payout_rule import value_fields
from lifecycle_tables import ending

LTD = "2014-12-12"       # a Friday: price_date is Monday the 15th


def _terms(deal_type="cash_and_stock", cash=None, ratio=None, ticker=None, basis=""):
    return MergerTerms(deal_type, cash, ratio, None, ticker, "high", "8-K:0001", "", package_basis=basis)


def test_a_cash_merger_publishes_its_cash_and_source():
    r = ending("A", "2014-12-20", method="cash_only", last_trade_close="10", payout_per_share="12.5",
               payout_source="8K_2.01")
    f = value_fields(r, LTD)
    assert (f["value_rule"], f["cash_per_share"], f["stock_ratio"]) == ("cash", 12.5, None)
    assert (f["terms_source"], f["terms_gate"], f["price_ticker"], f["price_date"]) == ("8K_2.01", "passed", "", "")
    assert f["cash_currency"] == ""
    assert f["value_formula"] == "12.50 / last_close − 1"


def test_a_stock_merger_names_the_acquirer_and_the_day_after_the_last_trade():
    r = ending("A", "2014-12-20", method="stock_only", last_trade_close="10", stock_ratio="0.8025",
               acquirer_ticker="QSR", acquirer_price="50")
    f = value_fields(r, LTD, MergerInputs(llm=_terms(ratio=0.8025, ticker="QSR"), acquirer_sec_id="BBG0QSR"))
    assert (f["value_rule"], f["stock_ratio"], f["price_ticker"], f["price_sec_id"], f["price_date"]) == (
        "stock", 0.8025, "QSR", "BBG0QSR", "2014-12-15")
    assert f["terms_source"] == "llm" and f["terms_gate"] == "passed"
    assert f["value_formula"] == "0.8025 × price(QSR, 2014-12-15) / last_close − 1"


def test_a_stock_leg_names_its_acquirers_ticker_on_the_price_date():
    """Sub-plan 5e: CAL 2010's terms say UAUA, which UAL Corp traded as until the closing; the acquirer security
    traded as UAL on the price date, and that is the price ticker, in the formula too."""
    r = ending("A", "2014-12-20", last_trade_close="10")
    f = value_fields(r, LTD, MergerInputs(llm=_terms("stock", ratio=1.05, ticker="UAUA"), acquirer_sec_id="BBG0UAL",
                                          price_ticker="UAL"))
    assert (f["price_ticker"], f["price_sec_id"], f["terms_gate"]) == ("UAL", "BBG0UAL", "failed")
    assert f["value_formula"] == "1.05 × price(UAL, 2014-12-15) / last_close − 1"


def test_a_registrants_statement_publishes_one_share_of_the_new_issuer_ungated():
    """FB-003, FNFV 2017: stage 8b put the registrant's own statement (each share redeemed for one Cannae share) in
    place of terms the gate refused; delistings.csv carries the ratio and ticker, the contract a stock rule priced
    under the new issuer's ticker, no acquirer security, `terms_source` registrant_statement, the gate skipped."""
    from delist_detection.outputs.dlret import StatementTerms
    r = ending("A", "2014-12-20", last_trade_close="17.35", stock_ratio="1.0", acquirer_ticker="CNNE",
               payout_source="registrant_statement")
    s = StatementTerms(1.0, "CNNE", "Cannae Holdings, Inc.")
    f = value_fields(r, LTD, MergerInputs(llm=_terms(ratio=0.3066, ticker="BKI"), price_ticker="CNNE", statement=s))
    assert (f["value_rule"], f["stock_ratio"], f["price_ticker"], f["price_sec_id"], f["price_date"]) == (
        "stock", 1.0, "CNNE", "", "2014-12-15")
    assert (f["terms_source"], f["terms_gate"], f["cash_per_share"]) == ("registrant_statement", "skipped", None)
    assert f["value_formula"] == "1 × price(CNNE, 2014-12-15) / last_close − 1"


def test_cash_plus_stock_formula():
    r = ending("A", "2014-12-20", method="cash_plus_stock", last_trade_close="10", payout_per_share="65.5",
               stock_ratio="0.8025", acquirer_ticker="QSR")
    f = value_fields(r, LTD)
    assert f["value_rule"] == "cash_plus_stock"
    assert f["value_formula"] == "(65.50 + 0.8025 × price(QSR, 2014-12-15)) / last_close − 1"


def test_a_closing_dividend_is_in_the_cash_and_named_apart_in_the_formula():
    """FB-021 (Extended Stay 2021): `cash_per_share` is all the cash one share received, and the formula shows the
    merger's cash and the dividend the payout gate counted."""
    r = ending("A", "2021-06-26", method="cash_only", last_trade_close="20.46", payout_per_share="20.5",
               payout_source="8K_2.01")
    f = value_fields(r, LTD, MergerInputs(raw_value=18.75, raw_source="8K_2.01", dividend=1.75))
    assert (f["value_rule"], f["cash_per_share"], f["terms_gate"]) == ("cash", 20.5, "passed")
    assert f["value_formula"] == "(18.75 + 1.75 dividend) / last_close − 1"
    # Nordstrom 2025: a $0.25 special and a $0.1462 stub-period dividend
    r = ending("A", "2025-05-31", last_trade_close="24.66", payout_per_share="24.6462", payout_source="8K_2.01")
    f = value_fields(r, LTD, MergerInputs(raw_value=24.25, dividend=0.3962))
    assert f["value_formula"] == "(24.25 + 0.3962 dividend) / last_close − 1"
    # Vectren 2019: a pro rata dividend of $0.41145
    r = ending("A", "2019-02-11", last_trade_close="72.38", payout_per_share="72.41145", payout_source="8K_2.01")
    f = value_fields(r, LTD, MergerInputs(raw_value=72.0, dividend=0.41145))
    assert f["value_formula"] == "(72.00 + 0.41145 dividend) / last_close − 1"


def test_a_closing_dividend_beside_a_stock_leg_makes_the_rule_cash_plus_stock():
    # Livongo 2020: $4.24, 0.592 of a Teladoc share and a $7.09 dividend
    r = ending("A", "2020-11-09", last_trade_close="139.77", payout_per_share="11.33", stock_ratio="0.592",
               acquirer_ticker="TDOC", acquirer_price="217.89", payout_source="llm")
    f = value_fields(r, LTD, MergerInputs(llm=_terms(cash=4.24, ratio=0.592, ticker="TDOC"), dividend=7.09))
    assert (f["value_rule"], f["cash_per_share"], f["stock_ratio"]) == ("cash_plus_stock", 11.33, 0.592)
    assert f["value_formula"] == "(4.24 + 7.09 dividend + 0.592 × price(TDOC, 2014-12-15)) / last_close − 1"
    # Six Flags 2024: the dividend is all the cash
    r = ending("A", "2024-07-12", last_trade_close="32", payout_per_share="1.53", stock_ratio="0.58",
               acquirer_ticker="FUN", acquirer_price="52.11", payout_source="llm")
    f = value_fields(r, LTD, MergerInputs(llm=_terms("stock", ratio=0.58, ticker="FUN"), dividend=1.53))
    assert f["value_formula"] == "(1.53 dividend + 0.58 × price(FUN, 2014-12-15)) / last_close − 1"
    assert (f["value_rule"], f["cash_per_share"], f["cash_currency"]) == ("cash_plus_stock", 1.53, "USD")


def test_terms_the_gate_did_not_keep_take_no_dividend():
    r = ending("A", "2014-12-20", last_trade_close="10", flags="llm_gate_failed")
    f = value_fields(r, LTD, MergerInputs(llm=_terms("cash", cash=5.0, basis="fixed"), dividend=None))
    assert (f["cash_per_share"], f["terms_gate"], f["value_formula"]) == (5.0, "failed", "5.00 / last_close − 1")


def test_no_published_last_trade_date_leaves_the_price_date_blank():
    r = ending("A", "2014-12-20", method="stock_only", last_trade_close="10", stock_ratio="0.5",
               acquirer_ticker="QSR")
    assert value_fields(r, "")["price_date"] == ""


def test_a_merger_with_no_terms_is_unknown():
    r = ending("A", "2014-12-20", method="assumed_par")
    f = value_fields(r, LTD)
    assert (f["value_rule"], f["terms_gate"], f["terms_source"], f["value_formula"]) == ("unknown", "", "", "")


def test_the_gated_out_llm_terms_are_published_as_failed():
    r = ending("THI", "2014-12-20", method="assumed_par", last_trade_close="10")
    f = value_fields(r, LTD, MergerInputs(llm=_terms(cash=65.5, ratio=0.8025, ticker="QSR"), acquirer_sec_id="BBG0QSR"))
    assert (f["value_rule"], f["cash_per_share"], f["stock_ratio"], f["price_ticker"]) == (
        "cash_plus_stock", 65.5, 0.8025, "QSR")
    assert (f["terms_source"], f["terms_gate"], f["price_date"]) == ("llm", "failed", "2014-12-15")


def test_a_gated_out_regex_read_is_published_as_failed_with_its_source():
    r = ending("RAI", "2014-12-20", method="assumed_par", last_trade_close="10")
    f = value_fields(r, LTD, MergerInputs(raw_value=29.44, raw_source="8K_2.01"))
    assert (f["value_rule"], f["cash_per_share"], f["terms_source"], f["terms_gate"]) == ("cash", 29.44, "8K_2.01", "failed")


def test_a_failed_election_package_publishes_both_legs_as_read():
    r = ending("THI", "2014-12-20", method="assumed_par", last_trade_close="10")
    f = value_fields(r, LTD, MergerInputs(llm=_terms("election", cash=65.5, ratio=0.8025, ticker="QSR",
                                                     basis="default")))
    assert (f["value_rule"], f["terms_gate"]) == ("cash_plus_stock", "failed")
    assert f["value_formula"] == "(65.50 + 0.8025 × price(QSR, 2014-12-15)) / last_close − 1"


def test_an_election_that_states_no_package_publishes_only_its_all_cash_alternative():
    """TRH 2012: the filing gives "shares of Alleghany or cash" with no default; the legs of such an answer are the
    alternatives, which are never the package (the stock alternative is no package; both legs summed is double)."""
    r = ending("WSC", "2011-07-07", method="assumed_par", last_trade_close="380")
    f = value_fields(r, LTD, MergerInputs(llm=_terms("election", cash=385.0, ratio=5.0611, ticker="BRK-B")))
    assert (f["value_rule"], f["cash_per_share"], f["stock_ratio"], f["price_ticker"]) == ("cash", 385.0, None, "")
    assert f["terms_gate"] == "failed"
    stock_only = replace(_terms("election", ratio=0.145, ticker="Y"), stock_value=61.14)
    f = value_fields(r, LTD, MergerInputs(llm=stock_only))
    assert (f["value_rule"], f["cash_per_share"], f["stock_ratio"], f["price_ticker"]) == ("unknown", None, None, "")


def test_a_merger_terms_override_wins_and_carries_no_gate():
    r = ending("A", "2014-12-20", method="cash_plus_stock", last_trade_close="10", payout_per_share="1",
               stock_ratio="2", acquirer_ticker="XXX")
    inputs = MergerInputs(override={"cash_per_share": 3.0, "stock_ratio": 0.5, "acquirer_price": 40.0,
                                    "acquirer_ticker": "QSR"}, llm=_terms(cash=9, ratio=9, ticker="ZZZ"))
    f = value_fields(r, LTD, inputs)
    assert (f["cash_per_share"], f["stock_ratio"], f["price_ticker"]) == (3.0, 0.5, "QSR")
    assert (f["terms_source"], f["terms_gate"]) == ("--merger-terms", "")
    # the caller's acquirer ticker is published as given, never replaced by the run's line symbol
    f = value_fields(r, LTD, MergerInputs(override=inputs.override, llm=inputs.llm, acquirer_sec_id="BBG0UAL",
                                          price_ticker="UAL"))
    assert (f["price_ticker"], f["price_sec_id"]) == ("QSR", "BBG0UAL")


def test_row_terms_with_no_last_close_have_no_gate_verdict():
    r = ending("A", "2014-12-20", method="needs_last_trade", payout_per_share="12.5", payout_source="8K_2.01")
    assert value_fields(r, LTD)["terms_gate"] == ""


def test_a_continuation_has_no_terms():
    r = ending("A", "2014-12-20", "exchange_transfer", method="exchange_transfer_zero", successor="B")
    f = value_fields(r, LTD)
    assert (f["value_rule"], f["value_formula"], f["terms_gate"]) == ("continuation", "", "")


def test_an_exchange_transfer_without_a_successor_is_a_transfer():
    r = ending("A", "2014-12-20", "exchange_transfer", method="exchange_transfer_zero")
    assert value_fields(r, LTD)["value_rule"] == "transfer"


def test_a_drop_values_from_its_own_first_otc_print():
    r = ending("A", "2014-12-20", "compliance_failure", method="shumway_nasdaq", crsp_code="570",
               ticker="ABCD")
    f = value_fields(r, LTD)
    assert (f["value_rule"], f["price_sec_id"], f["price_ticker"], f["price_date"]) == ("otc_print", "A", "ABCD", "2014-12-15")
    assert f["value_formula"] == "otc_print(ABCD, from 2014-12-15) / last_close − 1"


def test_a_recovery_and_worthless_are_written_with_their_formulas():
    """The order a liquidation's rule takes (a recovery, else a plan, else worthless, else a print) is dlret's
    (test_dlret); here, how the contract writes each."""
    rec = ending("A", "2014-12-20", "liquidation", method="recovery_ratio", crsp_code="470", recovery_ratio="0.15")
    f = value_fields(rec, LTD)
    assert (f["value_rule"], f["recovery_ratio"], f["value_formula"]) == ("recovery", 0.15, "0.1500 − 1")
    f = value_fields(ending("A", "2014-12-20", "liquidation", method="worthless"), LTD)
    assert (f["value_rule"], f["value_formula"], f["price_ticker"], f["price_date"]) == ("worthless", "0 − 1", "", "")


def test_a_wind_down_with_no_recovery_read_asks_for_its_distributions():
    """FB-002: PDLI 2020, no recovery read and no OTC symbol: the rule is `recovery` with no ratio, the formula the
    sum of what holders received after the last trade over the last close, and no price is named."""
    from delist_detection.outputs.dlret import DistressTerms
    pdli = ending("A", "2021-01-07", "liquidation", method="pending_recovery", crsp_code="400")
    f = value_fields(pdli, LTD, distress=DistressTerms())
    assert (f["value_rule"], f["recovery_ratio"], f["price_ticker"], f["price_date"]) == ("recovery", None, "", "")
    assert f["value_formula"] == "distributions(?, after the last trade) / last_close − 1"


def test_expiration_and_unknown_buckets():
    assert value_fields(ending("A", "2014-12-20", "expiration", method="dropped_expiration"), LTD)["value_rule"] == "expiration"
    assert value_fields(ending("A", "2014-12-20", "unknown", method="unknown"), LTD)["value_rule"] == "unknown"
    assert {"cash", "unknown", "recovery"} <= VALUE_RULES


# -- sub-plan 5g: the OTC symbol and a bankruptcy plan's stock rule (DistressTerms, stage 9e) -------------------

from delist_detection.outputs.dlret import DistressTerms  # noqa: E402


def test_a_drop_is_priced_under_its_own_otc_symbol():
    r = ending("A", "2020-11-09", "liquidation", method="shumway_nyse_amex", crsp_code="470", ticker="HTZ")
    f = value_fields(r, "2020-10-29", distress=DistressTerms(otc_symbol="HTZGQ"))
    assert (f["value_rule"], f["price_sec_id"], f["price_ticker"], f["price_date"]) == \
        ("otc_print", "A", "HTZGQ", "2020-10-30")
    assert f["value_formula"] == "otc_print(HTZGQ, from 2020-10-30) / last_close − 1"


def test_an_unknown_otc_symbol_is_blank_not_the_exchange_symbol_left_behind():
    r = ending("A", "2023-05-12", "liquidation", method="shumway_nasdaq", crsp_code="470", ticker="SIVB")
    f = value_fields(r, "2023-03-09", distress=DistressTerms())
    assert (f["value_rule"], f["price_sec_id"], f["price_ticker"]) == ("otc_print", "A", "")
    assert f["value_formula"] == "otc_print(?, from 2023-03-10) / last_close − 1"


def test_a_bankruptcy_plan_exchange_is_the_stock_rule_on_the_new_line():
    r = ending("A", "2018-07-13", "liquidation", method="shumway_nyse_amex", crsp_code="470", ticker="SDRL")
    f = value_fields(r, "2018-07-02", distress=DistressTerms(plan_ratio="0.0037345", plan_ticker="SDRL",
                                                                   plan_source="form25_notice"))
    assert (f["value_rule"], f["stock_ratio"], f["price_sec_id"], f["price_ticker"], f["price_date"]) == \
        ("stock", "0.0037345", "", "SDRL", "2018-07-03")
    assert (f["terms_source"], f["terms_gate"], f["cash_per_share"]) == ("form25_notice", "", None)
    assert f["value_formula"] == "0.0037345 × price(SDRL, 2018-07-03) / last_close − 1"


def test_without_distress_terms_a_drop_keeps_its_exchange_symbol():
    r = ending("A", "2014-12-20", "compliance_failure", method="shumway_nasdaq", crsp_code="570", ticker="ABCD")
    assert value_fields(r, LTD)["price_ticker"] == "ABCD"

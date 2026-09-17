from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.payout_gate import DEFAULT_TOL, gate_payouts, reconcile


def _terms(deal_type, cash=None, ratio=None, ticker=None):
    return MergerTerms(deal_type, cash, ratio, None, ticker, "high", "8-K:x", "")


def test_a_payout_that_reconciles_is_kept():
    r = reconcile(170.0, 169.99, None, None, 0.15)
    assert (r.cash, r.source, r.flags) == (170.0, "regex", ())


def test_a_payout_far_from_the_last_close_is_dropped_for_the_llm_cash():
    r = reconcile(25.0, 12.18, _terms("cash", 12.0), None, 0.15)
    assert (r.cash, r.source) == (12.0, "llm")
    assert "payout_gate_failed:25" in r.flags


def test_no_reconciling_value_leaves_par():
    r = reconcile(61.5, 0.03, None, None, 0.15)
    assert r.cash is None and r.source == "none"
    assert "payout_gate_failed:61.5" in r.flags


def test_without_a_last_close_the_regex_value_is_kept_and_flagged():
    r = reconcile(170.0, None, _terms("cash", 12.0), None, 0.15)
    assert (r.cash, r.source, r.flags) == (170.0, "regex", ("no_last_close",))


def test_an_election_takes_the_leg_the_last_close_reconciles_with():
    # BLD: after the election deadline the stock traded at 20.2 x QXO
    r = reconcile(None, 354.53, _terms("election", 505.0, 20.2, "QXO"), 17.28, 0.15)
    assert (r.cash, r.stock_ratio, r.acquirer_price, r.source) == (None, 20.2, 17.28, "llm_election_stock")


def test_an_election_where_both_legs_fit_takes_the_nearer_leg():
    # cash +0.4% beats stock -11.6%; an exact tie goes to stock
    r = reconcile(None, 49.80, _terms("election", 50.0, 1.0, "X"), 44.0, DEFAULT_TOL)
    assert (r.cash, r.stock_ratio, r.source) == (50.0, None, "llm_election_cash")
    r = reconcile(None, 50.0, _terms("election", 50.0, 1.0, "X"), 50.0, DEFAULT_TOL)
    assert (r.cash, r.stock_ratio, r.source) == (None, 1.0, "llm_election_stock")


def test_an_election_takes_its_cash_leg_when_only_cash_fits():
    r = reconcile(None, 505.0, _terms("election", 505.0, 20.2, "QXO"), 17.28, DEFAULT_TOL)
    assert (r.cash, r.stock_ratio, r.acquirer_price, r.source) == (505.0, None, None, "llm_election_cash")


def test_an_election_regex_matching_the_cash_leg_records_no_flag():
    # BLD: the regex correctly read the 505.0 cash leg of the election, but the
    # price ended up settling by the stock leg -- the "failed" flag is spurious.
    r = reconcile(505.0, 354.53, _terms("election", 505.0, 20.2, "QXO"), 16.54, DEFAULT_TOL)
    assert (r.cash, r.stock_ratio, r.source, r.flags) == (None, 20.2, "llm_election_stock", ())


def test_an_election_regex_matching_neither_leg_keeps_the_flag():
    r = reconcile(999.0, 354.53, _terms("election", 505.0, 20.2, "QXO"), 16.54, DEFAULT_TOL)
    assert r.source == "llm_election_stock"
    assert r.flags == ("payout_gate_failed:999",)


def test_an_election_where_neither_leg_fits_keeps_the_flags():
    r = reconcile(25.0, 12.18, _terms("election", 50.0, 1.0, "X"), 44.0, DEFAULT_TOL)
    assert r == reconcile(25.0, 12.18, None, None, DEFAULT_TOL)
    assert (r.cash, r.stock_ratio, r.source, r.flags) == (None, None, "none", ("payout_gate_failed:25",))


def test_terms_with_a_stock_ratio_are_left_to_the_cash_and_stock_gate():
    # the stock leg alone fits, and so does the cash leg alone; neither is taken here
    assert reconcile(None, 10.0, _terms("stock", None, 0.5, "X"), 20.0, DEFAULT_TOL).source == "none"
    assert reconcile(None, 10.0, _terms("cash_and_stock", 10.0, 0.1, "X"), 5.0, DEFAULT_TOL).source == "none"
    assert reconcile(None, 10.0, _terms("cash", 10.0, 0.1, "X"), 5.0, DEFAULT_TOL).source == "none"


def test_a_cash_and_cvr_deal_labelled_other_recovers_its_cash():
    r = reconcile(None, 381.02, _terms("other", 380.0), None, DEFAULT_TOL)
    assert (r.cash, r.source) == (380.0, "llm")


def test_a_fitting_regex_value_wins_over_the_llm_terms():
    r = reconcile(12.0, 12.18, _terms("cash", 12.1), None, DEFAULT_TOL)
    assert (r.cash, r.source, r.flags) == (12.0, "regex", ())


def test_a_non_positive_regex_value_fails_the_gate():
    r = reconcile(0.0, 10.0, None, None, DEFAULT_TOL)
    assert (r.cash, r.source, r.flags) == (None, "none", ("payout_gate_failed:0",))


# --- gate_payouts: the routing classify_universe runs after the loop ---

K = ("ABC", "2020-01-02")


def _gate(payout=None, terms=None, close=10.0, csv=None, price=None):
    return gate_payouts(
        [K],
        {} if payout is None else {K: payout},
        {} if payout is None else {K: "8K_2.01"},
        {} if payout is None else {K: "high"},
        {} if terms is None else {K: terms},
        {} if close is None else {"ABC": close},
        csv or {},
        lambda ticker, date: price,
        DEFAULT_TOL,
    )


def test_a_merger_terms_csv_row_wins_over_the_llm():
    csv = {"ABC": {"stock_ratio": 0.5, "acquirer_price": 20.0}}
    g = _gate(terms=_terms("election", 10.0, 0.5, "XYZ"), csv=csv, price=20.0)
    assert (g.payouts, g.sources, g.merged_terms, g.llm_cash) == ({}, {}, csv, 0)
    g = _gate(terms=_terms("stock", None, 0.5, "XYZ"), csv=csv, price=20.0)
    assert (g.merged_terms, g.emitted, g.dropped["csv_override"]) == (csv, 0, 1)


def test_an_election_stock_leg_drops_the_payout_and_writes_terms():
    # the regex read the deal's real cash leg (505), even though the price
    # ended up reconciling with the stock leg -- no flag should be recorded.
    payouts = {K: 505.0}
    g = gate_payouts([K], payouts, {K: "8K_2.01"}, {K: "high"},
                     {K: _terms("election", 505.0, 20.2, "QXO")}, {"ABC": 354.53}, {},
                     lambda ticker, date: 16.54, DEFAULT_TOL)
    assert K not in g.payouts and payouts == {K: 505.0}
    assert (g.sources[K], g.confidences[K]) == ("llm_election_stock", "high")
    assert g.merged_terms[K] == {"stock_ratio": 20.2, "acquirer_price": 16.54, "acquirer_ticker": "QXO"}
    assert (g.flags, g.gate_failed, g.llm_cash) == ({}, 0, 0)


def test_a_stock_only_gate_pass_drops_a_regex_value_that_fit():
    g = _gate(payout=14.5, terms=_terms("stock", None, 0.375, "RRC"), close=14.72, price=38.53)
    assert K not in g.payouts and K not in g.sources and K not in g.confidences
    assert g.merged_terms[K] == {"stock_ratio": 0.375, "acquirer_price": 38.53, "acquirer_ticker": "RRC"}
    assert g.emitted == 1


def test_without_a_last_close_the_regex_value_is_kept():
    g = _gate(payout=170.0, close=None)
    assert (g.payouts[K], g.sources[K], g.flags[K]) == (170.0, "8K_2.01", ("no_last_close",))


def test_cash_terms_with_a_stock_ratio_go_through_the_cash_and_stock_gate():
    g = _gate(terms=_terms("cash", 10.0, 0.5, "XYZ"), close=12.0, price=4.0)
    assert (g.payouts, g.sources, g.llm_cash, g.emitted) == ({}, {}, 0, 1)
    assert g.merged_terms[K] == {"stock_ratio": 0.5, "acquirer_price": 4.0, "acquirer_ticker": "XYZ",
                                 "cash_per_share": 10.0}
    # the cash alone fits the close, but cash + stock does not: nothing is emitted
    g = _gate(terms=_terms("cash", 12.0, 0.5, "XYZ"), close=12.0, price=4.0)
    assert (g.payouts, g.merged_terms, g.dropped["fail_sanity"]) == ({}, {}, 1)


def test_full_terms_clear_the_failed_flag_of_their_cash_leg():
    # AET: the regex read the $145 cash leg of $145 + 0.8378 CVS
    g = _gate(payout=145.0, terms=_terms("cash_and_stock", 145.0, 0.8378, "CVS"), close=212.70, price=80.27)
    assert g.merged_terms[K]["cash_per_share"] == 145.0 and K not in g.payouts
    assert (g.flags, g.gate_failed) == ({}, 0)
    # when the full terms fail too, the regex flag stays and the terms-gate drop
    # (fail_sanity) is appended so the row still surfaces in review.csv
    g = _gate(payout=145.0, terms=_terms("cash_and_stock", 145.0, 0.8378, "CVS"), close=300.0, price=80.27)
    assert (g.flags[K], g.gate_failed, g.merged_terms) == (
        ("payout_gate_failed:145", "terms_gate_failed:fail_sanity"), 1, {})


def test_a_cash_and_cvr_deal_labelled_other_fills_the_payout():
    g = _gate(terms=_terms("other", 380.0), close=381.02)
    assert (g.payouts[K], g.sources[K], g.confidences[K], g.llm_cash) == (380.0, "llm", "high", 1)


# --- ruling 2: the cash+stock gate flags every drop reason but csv_override ---

def test_terms_gate_no_acq_ticker_flag():
    g = _gate(terms=_terms("stock", None, 0.5, None), close=12.0, price=4.0)
    assert g.dropped["no_acq_ticker"] == 1
    assert g.flags[K] == ("terms_gate_failed:no_acq_ticker",)


def test_terms_gate_no_acq_price_flag():
    g = _gate(terms=_terms("stock", None, 0.5, "XYZ"), close=12.0, price=None)
    assert g.dropped["no_acq_price"] == 1
    assert g.flags[K] == ("terms_gate_failed:no_acq_price",)


def test_terms_gate_no_last_close_flag_appends_to_the_reconcile_flag():
    # pass 1 (reconcile) already flagged no_last_close; pass 2 appends its own.
    g = _gate(terms=_terms("stock", None, 0.5, "XYZ"), close=None, price=4.0)
    assert g.dropped["no_last_close"] == 1
    assert g.flags[K] == ("no_last_close", "terms_gate_failed:no_last_close")


def test_terms_gate_fail_sanity_flag():
    g = _gate(terms=_terms("cash", 12.0, 0.5, "XYZ"), close=12.0, price=4.0)
    assert g.dropped["fail_sanity"] == 1
    assert g.flags[K] == ("terms_gate_failed:fail_sanity",)


def test_terms_gate_csv_override_records_no_flag():
    csv = {"ABC": {"stock_ratio": 0.5, "acquirer_price": 20.0}}
    g = _gate(terms=_terms("stock", None, 0.5, "XYZ"), csv=csv, price=20.0)
    assert g.dropped["csv_override"] == 1
    assert K not in g.flags

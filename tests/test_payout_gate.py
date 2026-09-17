from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.payout_gate import reconcile


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

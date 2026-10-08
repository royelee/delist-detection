"""Sub-plan 5i: the verdict-only rulings of spec 2.3 (the verdict's rulings A to F), each with its guard, on small
tables, through `verdict.decide`."""
import pytest

from delist_detection.exit_kind import GATE_FLAGS, ContinuationReading, flag_names
from delist_detection.verdict import STALE_CLOSE_DAYS, STALE_SEED_DAYS, decide
from tests.lifecycle_tables import ending, iv, obs, review, sec, tables

KEPT = "; the registrant kept filing after it"
F25 = dict(delist_filing_form="25-NSE", delist_filing_date="2015-03-03", cik="100", resolution_source="name_search")
GOOD = dict(ltd="2015-03-02", dlret="0.01", **F25)


def _verdicts(*endings, securities=None, history=None, observations=None, reviews=()):
    t = tables(securities or [sec("A")], history or [iv("A", "AAA", "2010-01-04", "2015-03-02")], list(endings),
               observations if observations is not None else [obs("AAA", "2010-06-30", "A", name="ALPHA CORP")], reviews)
    return decide(t, {})


def _reasons(row, **kw):
    return _verdicts(row, **kw).endings[(row["sec_id"], row["delist_date"])].reasons


def _unpriced(row):
    """Ruling D through the verdict: assumed par after a gate flag is a doubt unless every gate failed on the price
    side."""
    assert row["dlret_method"] == "assumed_par" and flag_names(row) & GATE_FLAGS
    return "assumed_par_after_failed_gate" not in _reasons(row)


# -- a relabel the matched Form 25 settles (note A theme 1) -------------------------------------------------------

@pytest.mark.parametrize("reason", [f"Change in control (8-K item 5.01 filed 2015-02-20){KEPT}",
                                    f"Completed acquisition (8-K item 2.01 filed 2015-02-27, 25-NSE 2015-03-03){KEPT}"])
def test_a_merger_relabel_with_its_own_form25_is_settled(reason):
    assert _reasons(ending("A", "2015-03-13", reason=reason, **GOOD)) == ()


@pytest.mark.parametrize("cells", [
    dict(delist_filing_form="", delist_filing_date=""),                       # no Form 25 (FCL, SGP 2009)
    dict(reason=f"Listing deficiency notice (8-K 2015-01-08), no merger evidence{KEPT}"),   # MDRX, RHD
    dict(reason=f"Liquidation: delisted while winding down (8-K 2015-01-08 announces a liquidating distribution, "
                f"trust or plan){KEPT}"),                                     # EQC 2025
    dict(reason=f"Bankruptcy (8-K 2015-01-02, item 1.03) before the completed sale (8-K item 2.01 filed "
                f"2015-02-27){KEPT}"),
])
def test_other_relabels_and_a_merger_without_a_form25_keep_the_doubt(cells):
    row = ending("A", "2015-03-13", **{**GOOD, "reason": f"Change in control (8-K item 5.01 filed 2015-02-20){KEPT}",
                                        **cells})
    assert "resolved_from_continued_filings" in _reasons(row)


# -- a successor registration confirms a continuation (note A themes 2 and 6) -------------------------------------

def _chain():
    return dict(securities=[sec("A"), sec("B", observed=False)],
                history=[iv("A", "AAA", "2010-01-04", "2017-07-03"), iv("B", "AAA", "2017-07-05")])


def test_a_continuation_by_its_successor_registration_is_confirmed():
    row = ending("A", "2017-07-15", "exchange_transfer", successor="B", ltd="2017-07-03",
                 reason=f"Successor registration 8-K12B 2017-07-03: the security continues under a successor{KEPT}; "
                        "successor by new issuer")
    assert _reasons(row, **_chain()) == ()


def test_a_successor_registration_with_no_successor_found_keeps_the_doubt():
    row = ending("A", "2017-07-15", "exchange_transfer", ltd="2017-07-03",
                 reason=f"Successor registration 8-K12B 2017-07-03: the security continues under a successor{KEPT}")
    assert "resolved_from_continued_filings" in _reasons(row)


def test_a_handoff_by_8k12b_is_confirmed():
    """GOOGL 2015: the handoff made the `unknown` Form 25 row a continuation, dropping its no-evidence default
    (`rewrites.continuation`); the 8-K12B in its reason confirms it."""
    row = ending("A", "2015-10-12", "exchange_transfer", successor="B", ltd="2015-10-02",
                 flags="handoff_continuation",
                 reason="Continuation (8-K12B 0001193125-15-336577): A last traded as AAA on 2015-10-05 and B took "
                        "the ticker from 2015-10-06; holders' shares became B's")
    assert _reasons(row, **_chain()) == ()


def test_a_handoff_by_timing_keeps_its_doubt():
    row = ending("A", "2023-08-13", "exchange_transfer", successor="B", ltd="2023-08-04",
                 flags="handoff_continuation",
                 reason="Continuation (timing:cik): A last traded as AAA on 2023-08-04 and B took the ticker from "
                        "2023-08-07; holders' shares became B's")
    assert _reasons(row, **_chain()) == ("continuation_by_timing_only",)


# -- the matched Form 25's filer is issuer evidence (note A theme 3) ----------------------------------------------

def _mapped(**cells):
    return ending("A", "2026-08-14", **{**GOOD, "resolution_source": "company_tickers",
                                        "flags": "resolved_by_current_ticker_map", **cells})


def test_an_issuer_from_todays_map_whose_own_form25_it_filed_is_confirmed():
    assert _reasons(_mapped()) == ()


@pytest.mark.parametrize("cells", [
    dict(cik="1487730"),                                                     # SPB: the Form 25's CIK is another
    dict(delist_filing_form="", delist_filing_date=""),                      # CBL, TDW: no Form 25
    dict(flags="resolved_by_current_ticker_map;member_name_mismatch"),       # CHK 2020: the name disagrees
])
def test_the_ticker_map_doubt_stays_without_the_issuers_own_form25(cells):
    assert "issuer_from_todays_ticker_map" in _reasons(_mapped(**cells))


def test_a_handoff_row_built_on_an_unmatched_form25_is_no_issuer_evidence():
    row = _mapped(resolution_source="", flags="resolved_by_current_ticker_map;handoff_continuation")
    assert "issuer_from_todays_ticker_map" in _reasons(row)


# -- an unpriced gate is not a failed one (decision 4, note A theme 4) --------------------------------------------

@pytest.mark.parametrize("flags", ["terms_gate_failed:no_acq_price;merger_at_par",            # GRUB 2021
                                   "llm_gate_failed:no_acq_price;merger_at_par",
                                   f"ftd_close_prior:{STALE_CLOSE_DAYS + 1};payout_gate_failed:315;llm_gate_failed",
                                   f"ftd_close_prior:{STALE_CLOSE_DAYS + 2};terms_gate_failed:fail_sanity"])
def test_a_gate_that_failed_only_on_the_price_side_is_unpriced(flags):
    row = ending("A", "2021-06-25", **{**GOOD, "method": "assumed_par", "flags": flags, "acquirer_ticker": "JET",
                                       "last_trade_close": "300", "terminal_value": "310"})
    assert _unpriced(row) and _reasons(row) == ()


@pytest.mark.parametrize("flags", [
    "ftd_close_lagged;payout_gate_failed:42.18;llm_gate_failed",          # MDP: a lagged close is not stale
    f"ftd_close_prior:{STALE_CLOSE_DAYS};terms_gate_failed:fail_sanity",  # a close this young still tests the terms
    "terms_gate_failed:no_acq_ticker",                                    # CCE 2016: the terms name no acquirer
    "payout_gate_failed:29.44;terms_gate_failed:no_acq_price",            # the regex cash failed a fresh close
])
def test_a_gate_that_failed_against_a_fresh_close_stays_a_doubt(flags):
    row = ending("A", "2021-06-25", **{**GOOD, "method": "assumed_par", "flags": flags})
    assert not _unpriced(row)


# -- stale seeds after a confirmed ending (note A theme 5) --------------------------------------------------------

def _stale(status="after_delisting", asof="2008-01-16", **cells):
    row = ending("A", "2007-11-05", **{**GOOD, "ltd": "2007-10-31", "delist_filing_date": "2007-10-26", **cells})
    o = [obs("AAA", "2004-07-07", "A", name="ALPHA CORP"), obs("AAA", asof, "A", status, name="ALPHA CORP")]
    return _verdicts(row, history=[iv("A", "AAA", "2004-07-07", "2007-10-31")], observations=o)


def test_a_stale_seed_after_a_confirmed_merger_leaves_the_security_and_ending_confirmed():
    v = _stale()
    assert v.securities["A"].confirmed and v.endings[("A", "2007-11-05")].confirmed
    assert [(r["kind"], r["reason"]) for r in v.uncertain_rows()] == [("seed", "outside_security_history")]


@pytest.mark.parametrize("status, cells", [
    ("after_unconfirmed_delisting", {}),                                   # CDWC, DADE: a worked-out last trade
    ("after_delisting", dict(source="closing_day", flags="last_trade_date_unconfirmed")),
    ("after_delisting", dict(delist_filing_form="", delist_filing_date="")),   # no Form 25
    ("backfilled_ticker", {}),
])
def test_a_seed_past_an_unsettled_ending_keeps_the_security_uncertain(status, cells):
    v = _stale(status, **cells)
    assert v.securities["A"].reasons == ("seeds_outside_history:1 from 2008-01-16",)
    assert v.endings[("A", "2007-11-05")].reasons[0] == "security_uncertain"


def test_a_stale_seed_after_a_continuation_keeps_the_security_uncertain():
    row = ending("A", "2007-11-05", "exchange_transfer", successor="B", ltd="2007-10-31",
                 reason="Continuation (8-K12B 0001-1): A last traded as AAA", **F25)
    o = [obs("AAA", "2004-07-07", "A"), obs("AAA", "2008-01-16", "A", "after_delisting")]
    v = _verdicts(row, securities=[sec("A"), sec("B", observed=False)],
                  history=[iv("A", "AAA", "2004-07-07", "2007-10-31"), iv("B", "BBB", "2007-11-01")], observations=o)
    assert v.securities["A"].reasons == ("seeds_outside_history:1 from 2008-01-16",)


# -- a security with no ending at all (the wave 1 gap) ------------------------------------------------------------

def test_an_observed_security_closed_with_no_ending_is_uncertain():
    v = _verdicts(history=[iv("A", "AAA", "2010-01-04", "2013-12-31")],
                  reviews=[review("A", "ended_without_delisting")])
    assert v.securities["A"].reasons == ("closed_no_event:2013-12-31",)
    assert [(r["kind"], r["reason"]) for r in v.uncertain_rows()] == [("security", "closed_no_event:2013-12-31")]


def test_an_open_interval_a_real_ending_or_an_added_security_is_no_such_doubt():
    assert _verdicts(history=[iv("A", "AAA", "2010-01-04")]).securities["A"].confirmed
    assert _verdicts(ending("A", "2015-03-10", reason="M&A 2.01+3.01+5.01", **GOOD)).securities["A"].confirmed
    added = _verdicts(securities=[sec("A"), sec("Q", observed=False)],
                      history=[iv("A", "AAA", "2010-01-04"), iv("Q", "QQQ", "2021-07-12", "2021-07-30")])
    assert added.securities["Q"].confirmed


def test_a_continuing_move_alone_is_no_ending():
    move = ending("A", "2012-05-01", "exchange_transfer", successor="A")
    v = _verdicts(move, history=[iv("A", "AAA", "2010-01-04", "2013-12-31")])
    assert v.securities["A"].reasons == ("closed_no_event:2013-12-31",)


# -- the review's guards (5i fix patch) ---------------------------------------------------------------------------

def test_rule_e_keeps_a_last_trade_conflict_and_a_one_for_one_merger_uncertain():
    # FRK 2007: the halt day against the NYSE notice's; MEL 2007: one share per share and no cash is R1's continuation
    assert not _stale(flags="last_trade_date_conflict").securities["A"].confirmed
    assert not _stale(stock_ratio="1.000000", payout_per_share="").securities["A"].confirmed
    assert _stale(stock_ratio="0.836").securities["A"].confirmed                 # another ratio is a merger
    assert _stale(stock_ratio="1.0", payout_per_share="5.0").securities["A"].confirmed   # a cash leg too


def test_rule_e_is_bound_in_time_after_the_ending():
    assert _stale(asof="2008-10-30").securities["A"].confirmed                  # 365 days after 2007-10-31
    late = _stale(asof="2013-01-02")                                           # a later era on a recycled ticker
    assert late.securities["A"].reasons == ("seeds_outside_history:1 from 2013-01-02",)
    assert STALE_SEED_DAYS == 365


def test_rule_a_refuses_the_issuers_own_form25():
    reason = f"Change in control (8-K item 5.01 filed 2015-02-20){KEPT}"
    own = ending("A", "2015-03-13", **{**GOOD, "reason": reason, "delist_filing_form": "25"})
    assert "resolved_from_continued_filings" in _reasons(own)
    assert _reasons(ending("A", "2015-03-13", **{**GOOD, "reason": reason, "delist_filing_form": "25-NSE/A"})) == ()


def test_rule_b_keeps_a_continuation_whose_own_filings_state_another_ratio():
    row = ending("A", "2016-05-18", "exchange_transfer", successor="B", ltd="2016-05-18",
                 reason=f"Successor registration 8-K12B 2016-05-20: the security continues under a successor{KEPT}; "
                        "successor by new issuer")
    t = tables(_chain()["securities"], _chain()["history"], [row], [obs("AAA", "2010-06-30", "A", name="ALPHA")])
    r = decide(t, {}, {("A", "2016-05-18"): ContinuationReading(doubt="ratio:0.9042")}
               ).endings[("A", "2016-05-18")].reasons
    assert r == ("continuation_not_one_for_one:ratio:0.9042", "resolved_from_continued_filings")
    assert decide(t, {}, {("A", "2016-05-18"): ContinuationReading()}).endings[("A", "2016-05-18")].reasons == ()


def test_a_skipped_gate_beside_a_price_side_token_stays_a_doubt():
    # 5f adds terms_gate_skipped to the gates (exit_kind.GATE_FLAGS): it can never be a price-side failure
    assert "terms_gate_skipped" in GATE_FLAGS
    for flags in ("terms_gate_skipped:CAD;llm_gate_failed:no_acq_price",
                  f"ftd_close_prior:{STALE_CLOSE_DAYS + 2};terms_gate_skipped:basket;payout_gate_failed:44.25",
                  f"ftd_close_prior:{STALE_CLOSE_DAYS + 2};terms_gate_skipped"):
        row = ending("A", "2021-06-25", **{**GOOD, "method": "assumed_par", "flags": flags,
                                           "last_trade_close": "44", "acquirer_ticker": "ACQ"})
        assert not _unpriced(row)


@pytest.mark.parametrize("ticker", ["", "NULL", "null", "None", "N/A", "-", " NA "])
def test_a_null_like_acquirer_ticker_is_a_missing_one(ticker):
    # GRUB 2021: the gate said no_acq_price for a ticker of the word NULL
    row = ending("A", "2021-06-25", **{**GOOD, "method": "assumed_par", "acquirer_ticker": ticker,
                                       "flags": "terms_gate_failed:no_acq_price;merger_at_par"})
    assert not _unpriced(row)
    named = ending("A", "2021-06-25", **{**GOOD, "method": "assumed_par", "acquirer_ticker": "JET",
                                         "flags": "terms_gate_failed:no_acq_price;merger_at_par"})
    assert _unpriced(named)


def test_a_stale_close_failure_counts_only_within_the_tolerance_its_age_widens():
    base = {**GOOD, "method": "assumed_par", "last_trade_close": "71"}
    age = STALE_CLOSE_DAYS + 1
    small = ending("A", "2021-06-25", **{**base, "flags": f"ftd_close_prior:{age};payout_gate_failed:75.0"})
    huge = ending("A", "2021-06-25", **{**base, "flags": f"ftd_close_prior:{age};payout_gate_failed:481.37"})   # AT
    assert _unpriced(small) and not _unpriced(huge)
    compared = ending("A", "2021-06-25", **{**base, "terminal_value": "480",
                                            "flags": f"ftd_close_prior:{age};terms_gate_failed:fail_sanity"})
    assert not _unpriced(compared)
    no_close = ending("A", "2021-06-25", **{**GOOD, "method": "assumed_par",
                                            "flags": f"ftd_close_prior:{age};payout_gate_failed:75.0"})
    assert not _unpriced(no_close)


def test_a_form25_filed_name_check_needs_an_observed_name():
    # member_name_mismatch is raised against an observed name only: a nameless seed gets no name check at all
    nameless = _verdicts(_mapped(), observations=[obs("AAA", "2010-06-30", "A")])
    assert "issuer_from_todays_ticker_map" in nameless.endings[("A", "2026-08-14")].reasons

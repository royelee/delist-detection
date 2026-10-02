import pytest

from delist_detection import store
from delist_detection.verdict import ENDING, SECURITY, SEED, decide, is_introduction
from tests.lifecycle_tables import ending, iv, obs, sec, tables

GOOD = dict(ltd="2015-03-02", dlret="0.01", reason="M&A 2.01+3.01+5.01", delist_filing_form="25-NSE",
            delist_filing_date="2015-03-03")


def _one(*endings, securities=None, history=None, observations=None, evidence=None):
    t = tables(securities or [sec("A")], history or [iv("A", "AAA", "2010-01-04", "2015-03-02")], list(endings),
               observations if observations is not None else [obs("AAA", "2010-06-30", "A")])
    return decide(t, evidence or {})


def test_a_figi_security_with_a_covered_introduction_and_a_printed_ending_is_confirmed():
    v = _one(ending("A", "2015-03-10", **GOOD))
    assert v.securities["A"].confirmed and v.endings[("A", "2015-03-10")].confirmed
    assert v.counts() == {SEED: 0, SECURITY: 0, ENDING: 0} and v.uncertain_rows() == []


def test_a_placeholder_needs_ticker_evidence():
    p = sec("CIK5-COMMON", cik="5", figi_source="placeholder")
    h = [iv("CIK5-COMMON", "PPP", "2010-01-04")]
    o = [obs("PPP", "2010-06-30", "CIK5-COMMON")]
    without = _one(securities=[p], history=h, observations=o)
    assert without.securities["CIK5-COMMON"].reasons == ("placeholder_without_ticker_filing:CIK 5",)
    assert without.counts()[SEED] == 1 and [r["kind"] for r in without.uncertain_rows()] == [SECURITY]
    assert _one(securities=[p], history=h, observations=o,
                evidence={"CIK5-COMMON": "filing:0001-1"}).securities["CIK5-COMMON"].confirmed


def test_an_introduction_outside_the_history_makes_the_security_uncertain():
    v = _one(ending("A", "2015-03-10", **GOOD), observations=[obs("AAA", "2016-06-30", "A", "after_delisting")])
    assert v.securities["A"].reasons == ("seeds_outside_history:1 from 2016-06-30",)
    assert v.endings[("A", "2015-03-10")].reasons == ("security_uncertain",)


def test_a_later_sighting_outside_the_history_is_an_uncertain_seed_only():
    o = [obs("AAA", "2010-06-30", "A"), obs("AAA", "2015-06-30", "A", "after_delisting", era="AAA@2010-06-30")]
    v = _one(ending("A", "2015-03-10", **GOOD), observations=o)
    assert v.securities["A"].confirmed and v.endings[("A", "2015-03-10")].confirmed
    assert v.uncertain_rows() == [{"kind": SEED, "ticker": "AAA", "sec_id": "A", "date": "2015-06-30",
                                   "reason": "outside_security_history", "candidates": ""}]


def test_is_introduction_reads_the_era_key():
    assert is_introduction(obs("AAA", "2010-06-30", era="AAA@2010-06-30#1"))
    assert not is_introduction(obs("AAA", "2011-06-30", era="AAA@2010-06-30"))


def test_two_securities_holding_one_ticker_at_once_are_both_uncertain_unless_an_ending_links_them():
    secs = [sec("A"), sec("B")]
    h = [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "AAA", "2015-01-05")]
    o = [obs("AAA", "2010-06-30", "A"), obs("AAA", "2015-06-30", "B")]
    v = _one(ending("A", "2015-03-10", **GOOD), securities=secs, history=h, observations=o)
    assert v.securities["A"].reasons == ("ticker_overlap:AAA",) and v.securities["B"].candidates == ("A",)
    linked = _one(ending("A", "2015-03-10", ticker_successor_sec_id="B", **GOOD), securities=secs, history=h,
                  observations=o)
    assert linked.securities["A"].confirmed and linked.securities["B"].confirmed


@pytest.mark.parametrize("cells, reason", [
    (dict(ltd=""), "no_last_trade_date"),
    (dict(source="last_sighting"), "last_trade_not_exchange_print:last_sighting"),
    (dict(flags="last_trade_date_unconfirmed"), "last_trade_date_unconfirmed"),
    (dict(source="ex99_notice", flags="last_trade_date_conflict"), "last_trade_date_text_conflict"),
    (dict(ltd="2015-03-16"), "last_trade_after_form25_effective:2015-03-13"),
    (dict(reason="Continued 10-K/Q filings >180d after delist"), "continued_filings_rule"),
    (dict(flags="no_evidence_default"), "no_evidence_default"),
    (dict(bucket="unknown"), "unknown_exit_kind"),
    (dict(flags="resolved_by_current_ticker_map"), "issuer_from_todays_ticker_map"),
    (dict(method="assumed_par", flags="payout_gate_failed:34.88"), "assumed_par_after_failed_gate"),
])
def test_each_ending_rule(cells, reason):
    row = ending("A", "2015-03-10", **{**GOOD, **cells})
    assert reason in _one(row).endings[("A", "2015-03-10")].reasons


@pytest.mark.parametrize("cells", [dict(source="midas", flags="last_trade_date_conflict"),
                                   dict(method="assumed_par", flags="merger_at_par")])
def test_a_measured_print_beats_contrary_text_and_par_after_a_passed_gate_stands(cells):
    assert _one(ending("A", "2015-03-10", **{**GOOD, **cells})).endings[("A", "2015-03-10")].confirmed


def test_a_continuation_needs_filing_or_cusip_evidence_but_no_last_trade_print():
    secs = [sec("A"), sec("B", observed=False)]
    h = [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "AAA", "2015-03-03")]
    by_filing = ending("A", "2015-03-10", "exchange_transfer", successor="B", ltd="2015-03-02", source="last_sighting",
                       reason="Continuation (8-K12B 0001-1): A last traded as AAA")
    assert _one(by_filing, securities=secs, history=h).endings[("A", "2015-03-10")].confirmed
    by_timing = ending("A", "2015-03-10", "exchange_transfer", successor="B", ltd="2015-03-02",
                       source="last_sighting", reason="Continuation (timing:cik): A last traded as AAA")
    assert _one(by_timing, securities=secs, history=h).endings[("A", "2015-03-10")].reasons == (
        "continuation_by_timing_only",)


def test_a_continuing_move_gets_no_ending_verdict():
    v = _one(ending("A", "2012-05-01", "exchange_transfer", successor="A"))
    assert v.endings == {}


def test_seeds_not_placed_or_seen_under_two_names_are_listed_with_candidates():
    secs = [sec("A"), sec("B")]
    h = [iv("A", "AAA", "2010-01-04"), iv("B", "BBB", "2010-01-04")]
    o = [obs("AAA", "2010-06-30", "A", "conflict", name="ALPHA"), obs("AAA", "2010-06-30", "B", "conflict", name="BETA"),
         obs("ZZZ", "2010-06-30", "", "unresolved"), obs("BBB", "2010-06-30", "B")]
    rows = {(r["ticker"], r["sec_id"]): r for r in _one(securities=secs, history=h, observations=o).uncertain_rows()}
    assert rows[("ZZZ", "")]["reason"] == "not_placed"
    assert rows[("AAA", "A")]["reason"].startswith("seen_under_two_names") and rows[("AAA", "A")]["candidates"] == "B"


def test_uncertain_rows_round_trip_through_the_uncertain_table(tmp_path):
    rows = _one(ending("A", "2015-03-10", **{**GOOD, "ltd": ""})).uncertain_rows()
    store.write_tables(tmp_path, {"uncertain": rows})
    assert store.read_table("uncertain", store.table_path(tmp_path, "uncertain")) == rows == [
        {"kind": ENDING, "ticker": "AAA", "sec_id": "A", "date": "2015-03-10", "reason": "no_last_trade_date",
         "candidates": ""}]


def test_one_security_seen_under_two_names_on_a_day_is_one_uncertain_row():
    o = [obs("AAA", "2010-06-30", "A", "conflict", name="ALPHA"), obs("AAA", "2010-06-30", "A", "conflict", name="ALFA")]
    rows = _one(observations=o).uncertain_rows()
    assert [(r["kind"], r["ticker"], r["date"], r["reason"]) for r in rows] == [
        ("seed", "AAA", "2010-06-30", "seen_under_two_names")]

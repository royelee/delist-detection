import pytest

from delist_detection import store
from delist_detection.lifecycle import (ACTIVE, CLOSED_NO_EVENT, ENDED, ENDED_INCOMPLETE, HIGH, LEFT_VIEW, LOOP, LOW,
                                        MEDIUM, NO_INTERVAL, NO_MAPPED_SIGHTING, LifecycleView, Tables, event_grade)
from tests.lifecycle_tables import ending, iv, obs, sec, tables


def _kind(t, sec_id="A"):
    return LifecycleView(t).lifecycle(sec_id).kind


def test_an_open_interval_with_no_ending_is_active():
    assert _kind(tables([sec("A")], [iv("A", "AAA", "2010-01-04")])) == ACTIVE


def test_an_ending_with_reason_date_and_dlret_is_ended():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")],
               [ending("A", "2015-03-10", ltd="2015-03-02", dlret="0.01")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.covered, lc.final["delist_date"]) == (ENDED, True, "2015-03-10")


@pytest.mark.parametrize("cells", [dict(bucket="unknown", ltd="2015-03-02", dlret="0.0"),
                                   dict(bucket="merger", ltd="", dlret="0.01"),
                                   dict(bucket="merger", ltd="2015-03-02", dlret="")])
def test_an_unknown_reason_or_a_blank_date_or_dlret_leaves_the_ending_incomplete(cells):
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")], [ending("A", "2015-03-10", **cells)])
    assert _kind(t) == ENDED_INCOMPLETE


def test_a_transfer_with_no_successor_has_left_view():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0")])
    assert _kind(t) == LEFT_VIEW


def test_closed_intervals_and_no_ending_is_closed_no_event():
    assert _kind(tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")])) == CLOSED_NO_EVENT


def test_a_security_with_no_interval_is_no_interval():
    assert _kind(tables([sec("A")], [], [ending("A", "2007-01-10", ltd="2007-01-09", dlret="0.0")])) == NO_INTERVAL


def test_a_continuing_move_is_not_an_event():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04")],
               [ending("A", "2012-05-01", "exchange_transfer", successor="A", dlret="0.0")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.events) == (ACTIVE, ())


def test_an_ending_that_names_a_successor_continues_the_walk_there():
    t = tables([sec("A"), sec("B", observed=False)],
               [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2015-03-03")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0", successor="B")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.chain, [e["sec_id"] for e in lc.events]) == (ACTIVE, ("A", "B"), ["A"])
    assert lc.final is None                                    # still trading: no final ending


def test_an_open_interval_after_the_last_ending_means_it_kept_trading():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2013-12-31"), iv("A", "AAA", "2016-01-04")],
               [ending("A", "2014-01-10", ltd="2013-12-31", dlret="0.0")])
    assert _kind(t) == ACTIVE


def test_a_successor_loop_stops():
    t = tables([sec("A"), sec("B")],
               [iv("A", "AAA", "2010-01-04", "2012-01-03"), iv("B", "BBB", "2012-01-04", "2014-01-03")],
               [ending("A", "2012-01-10", "exchange_transfer", successor="B"),
                ending("B", "2014-01-10", "exchange_transfer", successor="A")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.chain) == (LOOP, ("A", "B"))


def test_a_successor_missing_from_the_tables_ends_the_walk_in_no_interval():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2012-01-03")],
               [ending("A", "2012-01-10", "exchange_transfer", successor="GONE")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.chain) == (NO_INTERVAL, ("A", "GONE"))


@pytest.mark.parametrize("cells, grade", [
    (dict(method="shumway_nasdaq"), LOW), (dict(method="assumed_par"), LOW),
    (dict(flags="last_trade_date_conflict"), LOW), (dict(flags="resolved_by_current_ticker_map;no_form25"), LOW),
    (dict(confidence="medium"), MEDIUM), (dict(dlret_confidence="low"), MEDIUM),
    (dict(dlret_confidence=""), HIGH), (dict(flags="ftd_close_prior:3"), HIGH)])
def test_event_grade(cells, grade):
    assert event_grade(ending("A", "2015-03-10", **cells)) == grade


def test_quality_is_the_weakest_grade_and_a_ticker_only_figi_on_the_chain_is_medium():
    t = tables([sec("A"), sec("B", figi_source="ticker"), sec("C"), sec("D")],
               [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2015-03-03"),
                iv("C", "CCC", "2010-01-04", "2015-03-02"), iv("D", "DDD", "2010-01-04", "2015-03-02")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0", successor="B"),
                ending("C", "2015-03-10", ltd="2015-03-02", dlret="-0.3", method="shumway_nyse_amex"),
                ending("D", "2015-03-10", ltd="2015-03-02", dlret="0.0", flags="ftd_close_lagged")])
    view = LifecycleView(t)
    assert [view.lifecycle(s).quality for s in "ACD"] == [MEDIUM, LOW, HIGH]


def test_quality_is_set_only_on_a_covered_lifecycle():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0")])
    assert LifecycleView(t).lifecycle("A").quality is None


def test_by_security_covers_observed_securities_only():
    t = tables([sec("A"), sec("X", observed=False)], [iv("A", "AAA", "2010-01-04"), iv("X", "XXX", "2010-01-04")])
    assert set(LifecycleView(t).by_security()) == {"A"}


def test_an_input_ticker_takes_the_lifecycle_of_its_earliest_mapped_sighting():
    t = tables([sec("A"), sec("B")],
               [iv("A", "AAA", "2010-01-04", "2012-01-03"), iv("B", "AAA", "2013-01-04")],
               [ending("A", "2012-01-10", ltd="2012-01-03", dlret="0.0")],
               [obs("AAA", "2009-06-30", "", "unresolved"), obs("AAA", "2010-06-30", "A"),
                obs("AAA", "2014-06-30", "B"), obs("ZZZ", "2010-06-30", "", "unresolved")])
    by_ticker = LifecycleView(t).by_input_ticker()
    assert (by_ticker["AAA"].start, by_ticker["AAA"].kind) == ("A", ENDED)
    assert by_ticker["ZZZ"].kind == NO_MAPPED_SIGHTING and not by_ticker["ZZZ"].covered
    assert LifecycleView(t).first_sighting("AAA") == "2010-06-30"


def test_security_on_prefers_the_observation_map_then_one_covering_interval():
    t = tables([sec("A"), sec("B")],
               [iv("A", "AAA", "2010-01-04", "2012-06-29"), iv("B", "AAA", "2012-06-01")],
               observations=[obs("AAA", "2012-06-15", "A")])
    view = LifecycleView(t)
    assert view.security_on("AAA", "2012-06-15") == "A"           # the map answers
    assert view.security_on("AAA", "2011-01-03") == "A"           # one interval covers it
    assert view.security_on("AAA", "2012-06-20") is None          # two intervals cover it
    assert view.security_on("AAA", "2009-01-02") is None          # none does


def test_end_of_a_lifecycle():
    t = tables([sec("A"), sec("B"), sec("C"), sec("D")],
               [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2010-01-04", "2015-03-02"),
                iv("C", "CCC", "2010-01-04", "2011-05-31"), iv("D", "DDD", "2010-01-04")],
               [ending("A", "2015-03-10", ltd="2015-03-02", dlret="0.0"), ending("B", "2015-03-10")])
    view = LifecycleView(t)
    assert [view.end_of(view.lifecycle(s)) for s in "ABCD"] == ["2015-03-02", "2015-03-10", "2011-05-31", None]


def test_tables_read_the_written_tables(tmp_path):
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04")], [ending("A", "2015-03-10")], [obs("AAA", "2010-06-30", "A")])
    store.write_tables(tmp_path, {"securities": t.securities, "ticker_history": t.ticker_history,
                                  "delistings": t.delistings, "observation_map": t.observation_map})
    back = Tables.read(tmp_path)
    assert back.securities == t.securities and back.delistings == t.delistings and back.review == []

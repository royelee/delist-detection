"""Ticker handoffs (handoff plan, Part 2): one security stops trading under a
ticker and another security of the run starts under it within days."""
from datetime import date

import pytest

from delist_detection.history import Sighting
from delist_detection.handoffs import (
    CONTINUATION_DAYS, OVERLAP_DAYS, TAKEOVER_DAYS, HandoffPair, find_handoffs,
)


def _sig(*items):
    """(day, ticker[, source]) -> date-sorted Sightings."""
    return sorted(Sighting(d, t, s[0] if s else "ftd") for d, t, *s in items)


def _pairs(sightings):
    return [(p.ticker, p.a, p.b, p.a_last, p.b_first) for p in find_handoffs(sightings)]


def test_the_proposed_windows():
    assert (OVERLAP_DAYS, CONTINUATION_DAYS, TAKEOVER_DAYS) == (10, 10, 120)


def test_a_clean_adjoin_is_a_candidate():
    """MNST 2015: the old line's last sighting 2015-06-12, the holding company's
    first 2015-06-15."""
    pairs = find_handoffs({
        "OLD": _sig(("2014-12-31", "MNST", "observation"), ("2015-06-12", "MNST")),
        "NEW": _sig(("2015-06-15", "MNST"), ("2015-12-31", "MNST", "observation")),
    })
    assert pairs == [HandoffPair("MNST", "OLD", "NEW", "2015-06-12", "2015-06-15", "2015-06-15")]
    assert pairs[0].gap == 3


def test_the_same_day_is_a_candidate():
    """ST 2018 (NL -> UK): both lines sighted on 2018-03-28."""
    assert _pairs({"OLD": _sig(("2018-03-01", "ST"), ("2018-03-28", "ST")),
                   "NEW": _sig(("2018-03-28", "ST"), ("2018-06-29", "ST"))}) == [
        ("ST", "OLD", "NEW", "2018-03-28", "2018-03-28")]


def test_an_eight_day_overlap_is_a_candidate_and_the_taker_keeps_its_earlier_life():
    """CZR 2020: Eldorado (ERI) took the CZR ticker on 2020-07-22, while old
    Caesars' fails rows run to 2020-07-30. The taker's first sighting under any
    ticker (as ERI) is years earlier."""
    (p,) = find_handoffs({
        "CAESARS": _sig(("2019-12-31", "CZR", "observation"), ("2020-07-30", "CZR")),
        "ELDORADO": _sig(("2015-06-30", "ERI", "observation"), ("2020-07-20", "ERI"), ("2020-07-22", "CZR"),
                         ("2020-12-31", "CZR", "observation")),
    })
    assert (p.ticker, p.a, p.b, p.gap, p.b_first_any) == ("CZR", "CAESARS", "ELDORADO", -8, "2015-06-30")


def test_a_74_day_gap_is_a_candidate():
    """COHR 2022: Coherent's last sighting 2022-06-30, II-VI (renamed Coherent
    Corp) first under COHR 2022-09-12."""
    assert _pairs({"COHERENT": _sig(("2022-06-30", "COHR")),
                   "IIVI": _sig(("2012-06-29", "IIVI"), ("2022-09-12", "COHR"))}) == [
        ("COHR", "COHERENT", "IIVI", "2022-06-30", "2022-09-12")]


@pytest.mark.parametrize("a_last,b_first", [("2020-01-02", "2020-05-02"), ("2020-01-20", "2020-01-05")])
def test_a_pair_outside_the_window_is_not(a_last, b_first):
    """121 days apart, or an overlap of more than OVERLAP_DAYS (two lines that
    traded side by side under one ticker are no handoff)."""
    assert _pairs({"A": _sig(("2019-06-28", "XX"), (a_last, "XX")),
                   "B": _sig((b_first, "XX"), ("2020-12-31", "XX"))}) == []


def test_three_securities_in_sequence_give_two_pairs():
    """A -> B -> C under one ticker: each hands off to the next, never A to C."""
    assert _pairs({"A": _sig(("2010-01-04", "TT"), ("2010-06-30", "TT")),
                   "B": _sig(("2010-07-01", "TT"), ("2010-08-31", "TT")),
                   "C": _sig(("2010-09-01", "TT"), ("2011-06-30", "TT"))}) == [
        ("TT", "A", "B", "2010-06-30", "2010-07-01"), ("TT", "B", "C", "2010-08-31", "2010-09-01")]


def test_a_later_line_that_began_under_the_ticker_first_is_no_successor():
    """The pair runs forwards only: B must begin under the ticker after A did."""
    assert _pairs({"A": _sig(("2010-06-01", "TT"), ("2010-06-30", "TT")),
                   "B": _sig(("2010-01-04", "TT"), ("2010-06-25", "TT"))}) == []


def test_separator_spellings_are_one_ticker():
    assert _pairs({"A": _sig(("2010-06-30", "BF-B")), "B": _sig(("2010-07-01", "BFB"))}) == [
        ("BF-B", "A", "B", "2010-06-30", "2010-07-01")]

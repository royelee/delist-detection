from datetime import date
from types import SimpleNamespace

import pytest

from delist_detection.payout_rule import DistressTerms
from delist_detection.price_requests import (LAST_CLOSE, OTC_PRINT, RECEIVED_CLOSE, PriceAnswers, PriceKey, key_of,
                                             load_answers, request_rows)
from delist_detection.reconstruction import OverrideFileError
from delist_detection.store import DelistingKey
from lifecycle_tables import ending


def test_requests_ask_the_last_close_and_a_stock_legs_received_close():
    endings = {"A": ending("A", "2018-12-10", ltd="2018-11-28", ticker="AET"),
               "B": ending("B", "2019-01-10", ltd="2019-01-03", ticker="BBB"),
               "C": ending("C", "2015-03-10", "exchange_transfer", successor="Z", ltd="2015-03-02", ticker="CCC")}
    contract = [{"sec_id": "A", "last_trade_date": "2018-11-28", "continuation": False, "exit_kind": "merger"},
                {"sec_id": "B", "last_trade_date": "", "continuation": False, "exit_kind": "merger"},
                {"sec_id": "C", "last_trade_date": "2015-03-02", "continuation": True, "exit_kind": "merger"}]
    legs = {DelistingKey("A", "2018-12-10"): ("CVS", "BBG000BGRY34")}
    assert request_rows(contract, endings, legs) == [
        {"sec_id": "A", "last_trade_date": "2018-11-28", "kind": LAST_CLOSE, "lookup_sec_id": "A",
         "lookup_ticker": "AET", "date": "2018-11-28"},
        {"sec_id": "A", "last_trade_date": "2018-11-28", "kind": RECEIVED_CLOSE, "lookup_sec_id": "BBG000BGRY34",
         "lookup_ticker": "CVS", "date": "2018-11-29"}]


def test_a_drop_or_distress_ending_asks_for_the_first_otc_print():
    endings = {k: ending(k, "2015-03-10", ltd="2015-03-06", ticker="T" + k) for k in "DLMCB"}
    row = lambda k, kind, ltd="2015-03-06", cont=False: {
        "sec_id": k, "last_trade_date": ltd, "continuation": cont, "exit_kind": kind}
    contract = [row("D", "dropped"), row("L", "liquidation"), row("M", "merger"),
                row("C", "dropped", cont=True), row("B", "dropped", ltd="")]
    got = request_rows(contract, endings, {})
    assert [(r["sec_id"], r["kind"]) for r in got] == [
        ("D", LAST_CLOSE), ("D", "otc_print"), ("L", LAST_CLOSE), ("L", "otc_print"), ("M", LAST_CLOSE)]
    assert got[1] == {"sec_id": "D", "last_trade_date": "2015-03-06", "kind": "otc_print", "lookup_sec_id": "D",
                      "lookup_ticker": "TD", "date": "2015-03-09"}


# --- the answers, read through the request each value input makes ---

def _ending(sec_id, day, delist="2020-06-15"):
    return SimpleNamespace(sec_id=sec_id, key=DelistingKey(sec_id, delist), last_trade=SimpleNamespace(day=day))


def test_a_last_close_answer_is_the_close_of_each_delisting_of_its_security_and_day():
    a, b = _ending("A", date(2020, 6, 1)), _ending("B", date(2020, 6, 5))
    answers = PriceAnswers({PriceKey("A", "2020-06-01", LAST_CLOSE, "A", "2020-06-01"): 11.0,
                            PriceKey("B", "2020-06-05", RECEIVED_CLOSE, "ACQ", "2020-06-08"): 22.0,
                            PriceKey("B", "2020-01-01", LAST_CLOSE, "B", "2020-01-01"): 33.0})
    assert answers.last_closes([a, b], {}) == {("A", "2020-06-15"): 11.0}
    assert answers.received_close("B", date(2020, 6, 5), "ACQ") == 22.0
    assert answers.received_close("B", date(2020, 6, 5), "XYZ") is None          # another leg's request
    assert answers.received_close("B", None, "ACQ") is None                      # no last trade day: no request
    unmatched = PriceAnswers({PriceKey("Z", "2020-06-01", LAST_CLOSE, "Z", "2020-06-01"): 1.0})
    assert unmatched.last_closes([a, b], {}) == {}


def test_a_last_close_given_both_ways_stops_the_run():
    a = _ending("A", date(2020, 6, 1))
    answers = PriceAnswers({PriceKey("A", "2020-06-01", LAST_CLOSE, "A", "2020-06-01"): 11.0})
    with pytest.raises(OverrideFileError, match="both give the last close of: A 2020-06-01"):
        answers.last_closes([a], {"A": 10.0})


def test_an_otc_print_answer_values_the_drop_and_wins_over_a_plans_close():
    """An answered OTC print is the drop's value; a bankruptcy plan's value is its ratio times the answered close of
    its new line (ruling R6), unless an OTC print of the same ending is answered."""
    day, plan = date(2020, 6, 1), DistressTerms(plan_ratio="0.5", plan_ticker="NEW", plan_source="25")
    otc = PriceKey("A", "2020-06-01", OTC_PRINT, "A", "2020-06-02")
    close = PriceKey("A", "2020-06-01", RECEIVED_CLOSE, "NEW", "2020-06-02")
    assert PriceAnswers({otc: 0.4}).ending_values("A", day, None) == (0.4, None)
    assert PriceAnswers({close: 22.0}).ending_values("A", day, plan) == (None, 11.0)
    assert PriceAnswers({otc: 0.4, close: 22.0}).ending_values("A", day, plan) == (0.4, None)
    assert PriceAnswers({close: 22.0}).ending_values("A", day, DistressTerms()) == (None, None)
    assert PriceAnswers().ending_values("A", day, plan) == (None, None)


def test_an_answer_to_no_request_stops_the_run():
    asked = {"sec_id": "A", "last_trade_date": "2020-06-01", "kind": LAST_CLOSE, "lookup_sec_id": "A",
             "lookup_ticker": "A", "date": "2020-06-01"}
    answers = PriceAnswers({key_of(asked): 11.0})
    answers.refuse_unrequested([asked])
    stray = PriceAnswers({key_of(asked): 11.0, PriceKey("A", "2020-06-01", LAST_CLOSE, "AX", "2020-06-01"): 11.0})
    with pytest.raises(OverrideFileError, match="answer no request of this run: A 2020-06-01 last_close AX"):
        stray.refuse_unrequested([asked])


def _answers(tmp_path, *rows, header="sec_id,last_trade_date,kind,lookup_sec_id,lookup_ticker,date,price"):
    p = tmp_path / "answers.csv"
    p.write_text("\n".join([header, *rows]) + "\n")
    return p


def test_answers_are_read_by_request_and_a_blank_price_is_unanswered(tmp_path):
    p = _answers(tmp_path, "A,2018-11-28,last_close,A,AET,2018-11-28,191.32",
                 "A,2018-11-28,received_close,BBG000BGRY34,CVS,2018-11-29,")
    assert load_answers(p) == {PriceKey("A", "2018-11-28", LAST_CLOSE, "AET", "2018-11-28"): 191.32}
    assert key_of({"sec_id": "A", "last_trade_date": "2018-11-28", "kind": LAST_CLOSE, "lookup_sec_id": "A",
                   "lookup_ticker": "AET", "date": "2018-11-28"}) in load_answers(p)


@pytest.mark.parametrize("row,message", [
    ("A,2018-11-28,last_close,A,AET,2018-11-28,abc", "not a number"),
    ("A,2018-11-28,last_close,A,AET,2018-11-28,-1", "not positive"),
    ("A,2018-11-28,last_close,A,AET,2018-11-28,inf", "not positive"),
    ("A,2018-11-28,last_close,A,AET,2018-11-28,nan", "not positive"),
    ("A,2018-11-28,closing,A,AET,2018-11-28,191", "kind"),
])
def test_a_bad_answer_names_its_file_and_line(tmp_path, row, message):
    with pytest.raises(OverrideFileError, match=rf"answers.csv:2: .*{message}"):
        load_answers(_answers(tmp_path, row))


def test_a_repeated_request_with_another_price_is_refused_and_with_the_same_price_is_fine(tmp_path):
    row = "A,2018-11-28,last_close,A,AET,2018-11-28,"
    assert load_answers(_answers(tmp_path, row + "191.32", row + "191.32")) == {
        PriceKey("A", "2018-11-28", LAST_CLOSE, "AET", "2018-11-28"): 191.32}
    with pytest.raises(OverrideFileError, match=r"answers.csv:3: a second price for the same request \(first on line 2\)"):
        load_answers(_answers(tmp_path, row + "191.32", row + "190"))


def test_the_otc_print_is_asked_under_the_published_otc_symbol_and_a_plan_asks_no_print():
    endings = {k: ending(k, "2015-03-10", ltd="2015-03-06", ticker="T" + k) for k in "DUP"}
    row = lambda k, rule, ticker: {"sec_id": k, "last_trade_date": "2015-03-06", "continuation": False,
                                   "exit_kind": "dropped", "value_rule": rule, "price_ticker": ticker}
    contract = [row("D", "otc_print", "TDQ"), row("U", "otc_print", ""), row("P", "stock", "TP")]
    plans = {DelistingKey("P", "2015-03-10"): DistressTerms(plan_ratio="0.5", plan_ticker="TP", plan_source="25"),
             DelistingKey("U", "2015-03-10"): DistressTerms(otc_symbol="")}
    got = request_rows(contract, endings, {}, plans=plans)
    assert [(r["sec_id"], r["kind"], r["lookup_ticker"]) for r in got] == [
        ("D", LAST_CLOSE, "TD"), ("D", "otc_print", "TDQ"), ("U", LAST_CLOSE, "TU"), ("U", "otc_print", "TU"),
        ("P", LAST_CLOSE, "TP"), ("P", RECEIVED_CLOSE, "TP")]


def test_an_answers_file_without_the_price_column_is_refused(tmp_path):
    with pytest.raises(OverrideFileError, match="price"):
        load_answers(_answers(tmp_path, "A,2018-11-28,last_close,A,AET,2018-11-28",
                              header="sec_id,last_trade_date,kind,lookup_sec_id,lookup_ticker,date"))

from types import SimpleNamespace

import pytest

from delist_detection.price_requests import (LAST_CLOSE, RECEIVED_CLOSE, PriceKey, key_of, load_answers,
                                             request_rows, stock_legs)
from delist_detection.reconstruction import OverrideFileError
from delist_detection.store import DelistingKey
from lifecycle_tables import ending


def test_requests_ask_the_last_close_and_a_stock_legs_received_close():
    endings = {"A": ending("A", "2018-12-10", ltd="2018-11-28", ticker="AET"),
               "B": ending("B", "2019-01-10", ltd="2019-01-03", ticker="BBB"),
               "C": ending("C", "2015-03-10", "exchange_transfer", successor="Z", ltd="2015-03-02", ticker="CCC")}
    contract = [{"sec_id": "A", "last_trade_date": "2018-11-28", "continuation": False},
                {"sec_id": "B", "last_trade_date": "", "continuation": False},
                {"sec_id": "C", "last_trade_date": "2015-03-02", "continuation": True}]
    legs = {DelistingKey("A", "2018-12-10"): ("CVS", "BBG000BGRY34")}
    assert request_rows(contract, endings, legs) == [
        {"sec_id": "A", "last_trade_date": "2018-11-28", "kind": LAST_CLOSE, "lookup_sec_id": "A",
         "lookup_ticker": "AET", "date": "2018-11-28"},
        {"sec_id": "A", "last_trade_date": "2018-11-28", "kind": RECEIVED_CLOSE, "lookup_sec_id": "BBG000BGRY34",
         "lookup_ticker": "CVS", "date": "2018-11-29"}]


def test_a_stock_leg_comes_from_the_llm_terms_unless_the_caller_gave_terms():
    a, b = ending("A", "2018-12-10"), ending("B", "2019-01-10")
    llm = {DelistingKey("A", "2018-12-10"): SimpleNamespace(stock_ratio=0.8378, acquirer_ticker="cvs"),
           DelistingKey("B", "2019-01-10"): SimpleNamespace(stock_ratio=0.5, acquirer_ticker="XYZ")}
    given = {"B": {"cash_per_share": 10.0, "stock_ratio": 0.5, "acquirer_price": 20.0, "acquirer_ticker": "XYZ"}}
    assert stock_legs([a, b], llm, given, {DelistingKey("A", "2018-12-10"): "BBG000BGRY34"}) == {
        DelistingKey("A", "2018-12-10"): ("CVS", "BBG000BGRY34")}


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
    ("A,2018-11-28,closing,A,AET,2018-11-28,191", "kind"),
])
def test_a_bad_answer_names_its_file_and_line(tmp_path, row, message):
    with pytest.raises(OverrideFileError, match=rf"answers.csv:2: .*{message}"):
        load_answers(_answers(tmp_path, row))


def test_an_answers_file_without_the_price_column_is_refused(tmp_path):
    with pytest.raises(OverrideFileError, match="price"):
        load_answers(_answers(tmp_path, "A,2018-11-28,last_close,A,AET,2018-11-28",
                              header="sec_id,last_trade_date,kind,lookup_sec_id,lookup_ticker,date"))

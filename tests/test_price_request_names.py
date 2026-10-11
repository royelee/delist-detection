"""FB-008: every price request carries the name of the security a vendor series must match (`lookup_name`)."""
import pytest

from delist_detection.outputs.dlret import DistressTerms
from delist_detection.outputs.price_requests import LAST_CLOSE, RECEIVED_CLOSE, PriceKey, load_answers, request_rows
from delist_detection.outputs.reconstruction import OverrideFileError
from delist_detection.outputs.store import DelistingKey
from lifecycle_tables import ending


def _named(contract, endings, legs, **kw):
    return {(r["sec_id"], r["kind"], r["lookup_ticker"]): r["lookup_name"]
            for r in request_rows(contract, endings, legs, **kw)}


def test_every_kind_of_request_carries_a_lookup_name():
    endings = {k: ending(k, "2015-03-10", ltd="2015-03-06", ticker="T" + k) for k in "AHDPB"}
    row = lambda k, **kw: {"sec_id": k, "last_trade_date": "2015-03-06", "continuation": False, "exit_kind": "merger",
                           **kw}
    contract = [row("A"), row("H"), row("D", exit_kind="dropped", value_rule="otc_print", price_ticker="TDQ"),
                row("P", exit_kind="dropped", value_rule="stock", price_ticker="TP"), row("B", value_rule="basket")]
    names = {"A": "Target A", "H": "Target H", "D": "Dropped D", "P": "Plan P", "B": "Target B", "ACQ": "Acquirer Inc"}
    legs = {DelistingKey("A", "2015-03-10"): ("ACQ1", "ACQ", ""),              # a held acquirer: securities.csv name
            DelistingKey("H", "2015-03-10"): ("FOR", "", "Foreign Acquirer plc"),   # not held: the LLM's issuer name
            DelistingKey("B", "2015-03-10"): ("BAM", "", "")}                  # not held and no LLM name: blank
    plans = {DelistingKey("P", "2015-03-10"): DistressTerms(plan_ratio="0.5", plan_ticker="TPN", plan_source="25")}
    basket = [{"sec_id": "B", "leg": 2, "price_ticker": "LION", "price_sec_id": "ACQ"},
              {"sec_id": "B", "leg": 3, "price_ticker": "STRZ", "price_sec_id": ""},
              {"sec_id": "B", "leg": 4, "price_ticker": "XX", "price_sec_id": ""}]
    got = _named(contract, endings, legs, plans=plans, leg_rows=basket, names=names,
                 leg_issuers={"B": ("Liberty Media", "Starz Inc")})
    assert got == {("A", LAST_CLOSE, "TA"): "Target A", ("A", RECEIVED_CLOSE, "ACQ1"): "Acquirer Inc",
                   ("H", LAST_CLOSE, "TH"): "Target H", ("H", RECEIVED_CLOSE, "FOR"): "Foreign Acquirer plc",
                   ("D", LAST_CLOSE, "TD"): "Dropped D", ("D", "otc_print", "TDQ"): "Dropped D",
                   ("P", LAST_CLOSE, "TP"): "Plan P", ("P", RECEIVED_CLOSE, "TPN"): "Plan P",
                   ("B", LAST_CLOSE, "TB"): "Target B", ("B", RECEIVED_CLOSE, "BAM"): "",
                   ("B", RECEIVED_CLOSE, "LION"): "Acquirer Inc",        # a held leg: the security's name
                   ("B", RECEIVED_CLOSE, "STRZ"): "Starz Inc",            # not held: the LLM leg's issuer
                   ("B", RECEIVED_CLOSE, "XX"): ""}                       # no leg issuer read


def _file(tmp_path, header, *rows):
    p = tmp_path / "answers.csv"
    p.write_text("\n".join([header, *rows]) + "\n")
    return p


def test_an_answers_file_written_against_schema_3_or_without_the_name_loads(tmp_path):
    p = _file(tmp_path, "sec_id,last_trade_date,kind,lookup_ticker,date,price", "A,2018-11-28,last_close,AET,2018-11-28,191.32")
    assert load_answers(p) == {PriceKey("A", "2018-11-28", LAST_CLOSE, "AET", "2018-11-28"): 191.32}
    p = _file(tmp_path, "sec_id,last_trade_date,kind,lookup_sec_id,lookup_ticker,date,lookup_name,price",
              "A,2018-11-28,last_close,A,AET,2018-11-28,Aetna,191.32")
    assert len(load_answers(p)) == 1


def test_an_answers_file_without_lookup_ticker_is_refused_naming_it(tmp_path):
    with pytest.raises(OverrideFileError, match="lookup_ticker"):
        load_answers(_file(tmp_path, "sec_id,last_trade_date,kind,date,price", "A,2018-11-28,last_close,2018-11-28,191.32"))

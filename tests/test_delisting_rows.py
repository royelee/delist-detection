import math

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.reconstruction import (
    build_delistings_table, delisting_row, load_float_overrides, load_merger_terms_overrides,
    unmatched_override_keys,
)
from delist_detection.store import DELISTINGS_COLUMNS


def _rec(sec_id, dd, bucket=CrspBucket.MERGER, code=231):
    return DelistRecord("AET", 1122304, "2018-11-28", code, bucket, "high", "M&A",
                        evidence={"flags": [], "delist_filing": {"form": "25-NSE", "filing_date": "2018-11-29",
                                                                 "accession": "0000876661-18-001269"},
                                  "anchor_8k": {"items": "2.01,3.01,5.01"}, "name": "AETNA INC",
                                  "resolution_source": "security_master"},
                        sec_id=sec_id, delist_date=dd)


def test_table_keys_by_sec_id_and_delist_date():
    recs = [_rec("BBG1", "2018-12-09"), _rec("BBG1", "2010-01-01")]
    t = build_delistings_table(
        recs,
        last_trade_closes={"BBG1": 200.0, ("BBG1", "2018-12-09"): 212.70},
        merger_terms={("BBG1", "2018-12-09"): {"cash_per_share": 145.0, "stock_ratio": 0.8378,
                                               "acquirer_price": 80.27, "acquirer_ticker": "CVS"}},
    )
    assert t[0].last_trade_close == 212.70 and t[1].last_trade_close == 200.0
    assert t[0].sec_id == "BBG1" and t[0].delist_date == "2018-12-09"
    assert math.isclose(t[0].terminal_value, 145.0 + 0.8378 * 80.27)


def test_delisting_row_has_every_column_and_extras():
    (e,) = build_delistings_table([_rec("BBG1", "2018-12-09")], last_trade_closes={"BBG1": 212.70},
                                  payouts={"BBG1": 212.25})
    row = delisting_row(e, exchange="NYSE", last_trade_date="2018-11-28", last_trade_date_source="midas",
                        acquirer_sec_id="BBG000BGRY34", raw_payout_per_share=212.25)
    assert set(row) <= set(DELISTINGS_COLUMNS)
    assert row["sec_id"] == "BBG1" and row["delist_date"] == "2018-12-09" and row["exchange"] == "NYSE"
    assert row["delist_filing_accession"] == "0000876661-18-001269"
    assert row["anchor_8k_items"] == "2.01,3.01,5.01" and row["resolved_name"] == "AETNA INC"
    assert row["bucket"] == "merger" and row["dlret_method"] == "cash_only"


def test_unknown_without_price_has_blank_dlret():
    rec = _rec("BBG2", "2019-01-01", bucket=CrspBucket.UNKNOWN, code=None)
    (e,) = build_delistings_table([rec])
    assert delisting_row(e)["dlret"] is None


def test_loaders(tmp_path):
    p = tmp_path / "lt.csv"
    p.write_text("sec_id,last_trade_close,delist_date\nBBG1,212.70,2018-12-09\nBBG2,5.5,\n")
    assert load_float_overrides(p, "last_trade_close") == {("BBG1", "2018-12-09"): 212.70, "BBG2": 5.5}
    bad = tmp_path / "bad.csv"
    bad.write_text("ticker,last_trade_close\nAET,1\n")
    with pytest.raises(ValueError, match="sec_id"):
        load_float_overrides(bad, "last_trade_close")
    t = tmp_path / "terms.csv"
    t.write_text("sec_id,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker,delist_date\n"
                 "BBG1,145,0.8378,80.27,CVS,2018-12-09\n")
    assert load_merger_terms_overrides(t) == {("BBG1", "2018-12-09"): {
        "cash_per_share": 145.0, "stock_ratio": 0.8378, "acquirer_price": 80.27, "acquirer_ticker": "CVS"}}
    t.write_text("sec_id,stock_ratio\nBBG1,0.5\n")
    with pytest.raises(ValueError, match="incomplete stock leg"):
        load_merger_terms_overrides(t)


def test_unmatched_override_keys():
    events = [("BBG1", "2018-12-09")]
    assert unmatched_override_keys({"BBG1": 1.0, ("BBG1", "2018-12-09"): 2.0}, events) == []
    assert unmatched_override_keys({"BBG9": 1.0, ("BBG1", "2020-01-01"): 2.0}, events) == \
        ["BBG9", ("BBG1", "2020-01-01")]

import math
import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.dlret import DlretMethod
from delist_detection.exchanges import Exchange
from delist_detection.reconstruction import enrich, EnrichedDelistRecord


def _rec(ticker="AET", bucket=CrspBucket.MERGER, code=241, date="2018-11-28"):
    return DelistRecord(
        ticker=ticker, cik=1122304, observed_delist_date=date,
        crsp_code=code, bucket=bucket, confidence="high",
        reason="M&A 2.01+3.01+5.01", evidence={},
    )


def test_enrich_merger_cash_plus_stock():
    e = enrich(
        _rec(), exchange=Exchange.NYSE, last_trade_close=190.0,
        payout_per_share=145.0, stock_ratio=0.8378, acquirer_price=80.0,
        acquirer_ticker="CVS", payout_source="manual", payout_confidence="high",
    )
    assert isinstance(e, EnrichedDelistRecord)
    assert e.dlret_method is DlretMethod.CASH_PLUS_STOCK
    assert e.dlret == pytest.approx(0.11592, abs=1e-4)
    assert e.terminal_value == pytest.approx(212.024)
    assert e.acquirer_ticker == "CVS"
    assert e.dlret_confidence == "medium"   # stock leg depends on a market price


def test_enrich_merger_cash_only_inherits_payout_confidence():
    e = enrich(
        _rec(code=233), exchange=Exchange.NYSE, last_trade_close=100.0,
        payout_per_share=113.0, payout_confidence="high",
    )
    assert e.dlret_method is DlretMethod.CASH_ONLY
    assert e.dlret_confidence == "high"


def test_enrich_needs_last_trade_is_low_confidence_and_nan():
    e = enrich(_rec(), exchange=Exchange.NYSE, last_trade_close=None, payout_per_share=113.0)
    assert e.dlret_method is DlretMethod.NEEDS_LAST_TRADE
    assert math.isnan(e.dlret)
    assert e.dlret_confidence == "low"


def test_enrich_carries_classification_fields():
    e = enrich(_rec(ticker="ABMD", code=231), exchange=Exchange.NASDAQ, last_trade_close=300.0,
               payout_per_share=380.0)
    assert e.ticker == "ABMD"
    assert e.crsp_code == 231
    assert e.bucket is CrspBucket.MERGER
    assert e.reason == "M&A 2.01+3.01+5.01"

from delist_detection.reconstruction import (
    build_dlret_table, write_dlret_csv, enriched_to_row, DLRET_TABLE_COLUMNS,
)


def test_table_column_order_is_contractual():
    assert DLRET_TABLE_COLUMNS == [
        "ticker", "bucket", "observed_delist_date", "crsp_code", "dlret", "reason",
        "exchange", "last_trade_close", "payout_per_share", "stock_ratio",
        "acquirer_price", "acquirer_ticker", "recovery_ratio", "terminal_value",
        "dlret_method", "dlret_confidence", "payout_source",
    ]


def test_build_table_keys_on_ticker_and_uses_inputs():
    records = [
        _rec(ticker="AET", code=241, date="2018-11-28"),
        _rec(ticker="ABMD", code=231, date="2023-01-03", bucket=CrspBucket.MERGER),
    ]
    table = build_dlret_table(
        records,
        last_trade_closes={"AET": 190.0, "ABMD": 300.0},
        payouts={"AET": 145.0, "ABMD": 380.0},
        exchanges={"AET": "NYSE", "ABMD": "NASDAQ"},
        merger_terms={"AET": {"stock_ratio": 0.8378, "acquirer_price": 80.0, "acquirer_ticker": "CVS"}},
    )
    by_ticker = {e.ticker: e for e in table}
    assert by_ticker["AET"].dlret_method is DlretMethod.CASH_PLUS_STOCK
    assert by_ticker["ABMD"].dlret_method is DlretMethod.CASH_ONLY
    assert by_ticker["ABMD"].dlret == pytest.approx(380.0 / 300.0 - 1.0)


def test_row_blanks_nan_and_none():
    e = enrich(_rec(), exchange=Exchange.NYSE, last_trade_close=None, payout_per_share=113.0)
    row = enriched_to_row(e)
    assert row["dlret"] == ""          # NaN renders blank, never 0
    assert row["terminal_value"] == ""
    assert row["dlret_method"] == "needs_last_trade"


def test_write_csv_roundtrip(tmp_path):
    import csv
    records = [_rec(ticker="ABMD", code=231)]
    table = build_dlret_table(records, last_trade_closes={"ABMD": 300.0}, payouts={"ABMD": 380.0},
                              exchanges={"ABMD": "NASDAQ"})
    out = tmp_path / "dlret.csv"
    write_dlret_csv(table, out)
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == DLRET_TABLE_COLUMNS
    assert rows[0]["ticker"] == "ABMD"
    assert rows[0]["dlret_method"] == "cash_only"


def test_recycled_ticker_yields_one_row_per_delisting():
    # ALTR was Altera (2015 merger) then Altair (2025). Two DelistRecords with
    # the same ticker but different dates -> two output rows, one per event.
    records = [
        _rec(ticker="ALTR", code=233, date="2015-12-28"),
        _rec(ticker="ALTR", code=231, date="2025-03-26"),
    ]
    table = build_dlret_table(records, last_trade_closes={"ALTR": 50.0}, payouts={"ALTR": 54.0})
    assert len(table) == 2
    assert {e.observed_delist_date for e in table} == {"2015-12-28", "2025-03-26"}


def test_load_merger_terms_csv(tmp_path):
    from delist_detection.reconstruction import load_merger_terms_csv
    p = tmp_path / "terms.csv"
    p.write_text(
        "ticker,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker\n"
        "AET,145,0.8378,80,CVS\n"
        "ABMD,380,,,\n"
    )
    terms = load_merger_terms_csv(p)
    assert terms["AET"] == {"cash_per_share": 145.0, "stock_ratio": 0.8378,
                            "acquirer_price": 80.0, "acquirer_ticker": "CVS"}
    assert terms["ABMD"] == {"cash_per_share": 380.0}  # blanks omitted


def test_load_float_map_csv_reads_values(tmp_path):
    from delist_detection.reconstruction import load_float_map_csv
    p = tmp_path / "lt.csv"
    p.write_text("ticker,last_trade_close\nAET,190\nFOO,\n")
    assert load_float_map_csv(p, "last_trade_close") == {"AET": 190.0}  # blank-value row skipped


def test_load_float_map_csv_raises_on_missing_column(tmp_path):
    from delist_detection.reconstruction import load_float_map_csv
    p = tmp_path / "bad.csv"
    p.write_text("ticker,close\nAET,190\n")  # 'close' != 'last_trade_close'
    with pytest.raises(ValueError):
        load_float_map_csv(p, "last_trade_close")


def test_merger_no_consideration_valid_price_blanks_table_dlret():
    # Per the README "never silently zero" rule: a MERGER with no consideration
    # but a valid last_trade_close keeps dlret == 0.0 on the EnrichedDelistRecord
    # but blanks the rendered CSV cell so a reader cannot mistake an abstain for
    # a realized 0% return.
    e = enrich(_rec(), exchange=Exchange.NYSE, last_trade_close=10.0)
    assert e.dlret_method is DlretMethod.ABSTAIN_NO_CONSIDERATION
    assert e.dlret == 0.0               # value intact on the record
    row = enriched_to_row(e)
    assert row["dlret"] == ""           # but blanked in the table


def test_load_merger_terms_csv_raises_on_partial_stock_leg(tmp_path):
    from delist_detection.reconstruction import load_merger_terms_csv
    p = tmp_path / "bad_terms.csv"
    p.write_text(
        "ticker,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker\n"
        "AET,145,0.8378,,CVS\n"  # stock_ratio present but acquirer_price blank
    )
    with pytest.raises(ValueError, match="incomplete stock leg"):
        load_merger_terms_csv(p)


def test_cash_only_invalid_payout_confidence_yields_medium():
    # An empty or invalid payout_confidence on a CASH_ONLY result must yield
    # "medium" (a valid tier), not propagate junk or silently default "high".
    e_empty = enrich(
        _rec(code=233), exchange=Exchange.NYSE, last_trade_close=100.0,
        payout_per_share=113.0, payout_confidence="",
    )
    assert e_empty.dlret_method is DlretMethod.CASH_ONLY
    assert e_empty.dlret_confidence == "medium"

    e_junk = enrich(
        _rec(code=233), exchange=Exchange.NYSE, last_trade_close=100.0,
        payout_per_share=113.0, payout_confidence="unknown_tier",
    )
    assert e_junk.dlret_confidence == "medium"

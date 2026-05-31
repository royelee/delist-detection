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

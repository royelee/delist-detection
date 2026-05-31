import math
import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.exchanges import Exchange
from delist_detection.handling import (
    FirmMonthReturn, build_firm_month_correction,
)


def _rec(ticker="ALTR", bucket=CrspBucket.MERGER, code=231,
         delist="2025-03-26"):
    return DelistRecord(
        ticker=ticker, cik=1701732, observed_delist_date=delist,
        crsp_code=code, bucket=bucket, confidence="high", reason="test",
    )


def test_firm_month_correction_merger():
    out = build_firm_month_correction(
        record=_rec(bucket=CrspBucket.MERGER),
        prior_month_end_close=100.0, last_trade_close=105.0,
        exchange=Exchange.NASDAQ,
        payout_per_share=113.0,
    )
    assert isinstance(out, FirmMonthReturn)
    assert out.ticker == "ALTR"
    assert out.bucket is CrspBucket.MERGER
    assert out.exchange is Exchange.NASDAQ
    assert out.firm_month_return == pytest.approx(0.13)
    assert out.dlret == pytest.approx((113 - 105) / 105)
    assert out.r_partial == pytest.approx(0.05)


def test_firm_month_correction_compliance_nyse_default_exchange():
    # Exchange omitted -> defaults to OTHER -> conservative Nasdaq constant
    out = build_firm_month_correction(
        record=_rec(ticker="RSH", bucket=CrspBucket.COMPLIANCE_FAILURE,
                    code=584),
        prior_month_end_close=100.0, last_trade_close=80.0,
        exchange=None,
        payout_per_share=None,
    )
    # R_month = (0.80)(0.45) - 1
    assert out.firm_month_return == pytest.approx(-0.64)
    assert out.exchange is Exchange.OTHER


def test_firm_month_correction_expiration_returns_nan_and_flag():
    out = build_firm_month_correction(
        record=_rec(bucket=CrspBucket.EXPIRATION, code=600),
        prior_month_end_close=100.0, last_trade_close=80.0,
        exchange=Exchange.NYSE, payout_per_share=None,
    )
    assert math.isnan(out.firm_month_return)
    assert out.drop is True


def test_firm_month_correction_keeps_non_expiration_in_panel():
    out = build_firm_month_correction(
        record=_rec(bucket=CrspBucket.MERGER),
        prior_month_end_close=100.0, last_trade_close=105.0,
        exchange=Exchange.NASDAQ, payout_per_share=113.0,
    )
    assert out.drop is False


def test_firm_month_correction_no_delist_date_drops():
    rec = _rec(delist=None)
    out = build_firm_month_correction(
        record=rec, prior_month_end_close=100.0, last_trade_close=80.0,
        exchange=Exchange.NYSE, payout_per_share=None,
    )
    assert out.drop is True
    assert math.isnan(out.firm_month_return)


def test_firm_month_correction_zero_prior_close_drops():
    out = build_firm_month_correction(
        record=_rec(bucket=CrspBucket.COMPLIANCE_FAILURE, code=584),
        prior_month_end_close=0.0, last_trade_close=80.0,
        exchange=Exchange.NYSE, payout_per_share=None,
    )
    assert out.drop is True
    assert math.isnan(out.firm_month_return)
    assert math.isnan(out.r_partial)


def test_firm_month_merger_includes_stock_leg():
    # AET->CVS: prior 200, last 190 (R_partial=-0.05); DLRET from full
    # consideration 212.024/190-1=+0.11592 -> R_month=(0.95)(1.11592)-1
    from delist_detection.handling import build_firm_month_correction
    from delist_detection.classifier import DelistRecord
    from delist_detection.crsp_codes import CrspBucket
    from delist_detection.exchanges import Exchange
    rec = DelistRecord(
        ticker="AET", cik=1, observed_delist_date="2018-11-28",
        crsp_code=241, bucket=CrspBucket.MERGER, confidence="high", reason="", evidence={},
    )
    fm = build_firm_month_correction(
        record=rec, prior_month_end_close=200.0, last_trade_close=190.0,
        exchange=Exchange.NYSE, payout_per_share=145.0,
        stock_ratio=0.8378, acquirer_price=80.0,
    )
    assert fm.dlret == pytest.approx(0.11592, abs=1e-4)
    assert fm.firm_month_return == pytest.approx((0.95) * (1.11592) - 1.0, abs=1e-4)

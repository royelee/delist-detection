import math
import pytest

from delist_detection.bmp_correction import (
    SHUMWAY_NYSE_AMEX, SHUMWAY_NASDAQ, compute_dlret, bmp_firm_month_return,
)
from delist_detection.crsp_codes import CrspBucket
from delist_detection.exchanges import Exchange


# ---- DLRET resolution per bucket ----

def test_dlret_merger_uses_payout():
    # M&A cash: DLRET = payout/last_trade - 1
    dlret = compute_dlret(
        bucket=CrspBucket.MERGER,
        exchange=Exchange.NYSE,
        last_trade_close=100.0,
        payout_per_share=113.0,
    )
    assert dlret == pytest.approx(0.13)


def test_dlret_merger_missing_payout_returns_zero():
    # No deal terms -> neutral mark (DLRET=0); caller should flag for review
    dlret = compute_dlret(
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        last_trade_close=100.0, payout_per_share=None,
    )
    assert dlret == 0.0


def test_dlret_compliance_nyse_amex_uses_shumway_minus30():
    assert compute_dlret(
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NYSE,
        last_trade_close=10.0, payout_per_share=None,
    ) == SHUMWAY_NYSE_AMEX
    assert compute_dlret(
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.AMEX,
        last_trade_close=10.0, payout_per_share=None,
    ) == SHUMWAY_NYSE_AMEX
    assert SHUMWAY_NYSE_AMEX == pytest.approx(-0.30)


def test_dlret_compliance_nasdaq_uses_shumway_minus55():
    assert compute_dlret(
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NASDAQ,
        last_trade_close=10.0, payout_per_share=None,
    ) == SHUMWAY_NASDAQ
    assert SHUMWAY_NASDAQ == pytest.approx(-0.55)


def test_dlret_compliance_other_exchange_falls_back_to_nasdaq_constant():
    # Conservative default for unknown venues (OTC, BATS, etc.)
    assert compute_dlret(
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.OTHER,
        last_trade_close=10.0, payout_per_share=None,
    ) == SHUMWAY_NASDAQ


def test_dlret_liquidation_with_observed_recovery():
    # Recovery known: DLRET = recovery_ratio - 1
    dlret = compute_dlret(
        bucket=CrspBucket.LIQUIDATION, exchange=Exchange.NYSE,
        last_trade_close=10.0, payout_per_share=None,
        recovery_ratio=0.20,
    )
    assert dlret == pytest.approx(-0.80)


def test_dlret_liquidation_no_recovery_falls_back_to_shumway():
    # No recovery observed: treat as performance delisting
    dlret = compute_dlret(
        bucket=CrspBucket.LIQUIDATION, exchange=Exchange.NASDAQ,
        last_trade_close=10.0, payout_per_share=None,
        recovery_ratio=None,
    )
    assert dlret == SHUMWAY_NASDAQ


def test_dlret_exchange_transfer_is_zero():
    # Security continues elsewhere; no DLRET shock at this venue
    assert compute_dlret(
        bucket=CrspBucket.EXCHANGE_TRANSFER, exchange=Exchange.NYSE,
        last_trade_close=10.0, payout_per_share=None,
    ) == 0.0


def test_dlret_expiration_is_nan_to_signal_drop():
    # Not equity universe — caller should drop, not compound
    dlret = compute_dlret(
        bucket=CrspBucket.EXPIRATION, exchange=Exchange.NYSE,
        last_trade_close=10.0, payout_per_share=None,
    )
    assert math.isnan(dlret)


# ---- BMP compound formula ----

def test_bmp_compound_merger():
    # Prior month-end 100, last trade 105, payout 113
    # R_partial = 0.05, DLRET = 113/105 - 1 ≈ 0.0762
    # R_month = (1.05)(1.0762) - 1 ≈ 0.13
    r = bmp_firm_month_return(
        prior_month_end_close=100.0, last_trade_close=105.0,
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        payout_per_share=113.0,
    )
    assert r == pytest.approx(0.13)


def test_bmp_compound_compliance_nasdaq():
    # Prior 100, last trade 80 (-20% partial), Shumway -55% on Nasdaq
    # R_month = (0.80)(0.45) - 1 = -0.64
    r = bmp_firm_month_return(
        prior_month_end_close=100.0, last_trade_close=80.0,
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NASDAQ,
        payout_per_share=None,
    )
    assert r == pytest.approx(-0.64)


def test_bmp_compound_compliance_nyse():
    # Prior 100, last trade 80 (-20%), Shumway -30% on NYSE
    # R_month = (0.80)(0.70) - 1 = -0.44
    r = bmp_firm_month_return(
        prior_month_end_close=100.0, last_trade_close=80.0,
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NYSE,
        payout_per_share=None,
    )
    assert r == pytest.approx(-0.44)


def test_bmp_compound_expiration_is_nan():
    r = bmp_firm_month_return(
        prior_month_end_close=100.0, last_trade_close=80.0,
        bucket=CrspBucket.EXPIRATION, exchange=Exchange.NYSE,
        payout_per_share=None,
    )
    assert math.isnan(r)


def test_bmp_compound_invalid_prior_close_returns_nan():
    # Cannot compute R_partial without prior month-end
    r = bmp_firm_month_return(
        prior_month_end_close=0.0, last_trade_close=80.0,
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NYSE,
        payout_per_share=None,
    )
    assert math.isnan(r)


def test_dlret_merger_zero_last_trade_returns_nan():
    # Data corruption: non-positive last trade -> drop, not neutral mark
    dlret = compute_dlret(
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        last_trade_close=0.0, payout_per_share=113.0,
    )
    assert math.isnan(dlret)


def test_dlret_compliance_negative_last_trade_returns_nan():
    dlret = compute_dlret(
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NASDAQ,
        last_trade_close=-1.0, payout_per_share=None,
    )
    assert math.isnan(dlret)


def test_dlret_exchange_transfer_ignores_bad_last_trade():
    # EXCHANGE_TRANSFER is a no-op at this venue; last_trade is unused
    dlret = compute_dlret(
        bucket=CrspBucket.EXCHANGE_TRANSFER, exchange=Exchange.NYSE,
        last_trade_close=0.0, payout_per_share=None,
    )
    assert dlret == 0.0


def test_dlret_merger_negative_payout_returns_nan():
    dlret = compute_dlret(
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        last_trade_close=100.0, payout_per_share=-5.0,
    )
    assert math.isnan(dlret)


def test_dlret_merger_zero_payout_is_total_wipe():
    # Zero payout = -100% return; natural arithmetic, not corruption
    dlret = compute_dlret(
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        last_trade_close=100.0, payout_per_share=0.0,
    )
    assert dlret == pytest.approx(-1.0)


def test_dlret_liquidation_negative_recovery_returns_nan():
    dlret = compute_dlret(
        bucket=CrspBucket.LIQUIDATION, exchange=Exchange.NYSE,
        last_trade_close=10.0, payout_per_share=None,
        recovery_ratio=-0.1,
    )
    assert math.isnan(dlret)


def test_bmp_firm_month_propagates_nan_for_degenerate_last_trade():
    # NaN from compute_dlret should propagate through the compound
    r = bmp_firm_month_return(
        prior_month_end_close=100.0, last_trade_close=0.0,
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        payout_per_share=113.0,
    )
    assert math.isnan(r)

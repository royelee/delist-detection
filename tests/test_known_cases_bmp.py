"""Sanity tests on real delisting cases from output/delist_classifications.csv.

These pin the expected BMP-corrected return to published deal terms so a
regression in the formula or the constants table is caught immediately.
"""

import pytest

from delist_detection.bmp_correction import bmp_firm_month_return
from delist_detection.crsp_codes import CrspBucket
from delist_detection.exchanges import Exchange


def test_altair_siemens_acquisition_march_2025():
    # ALTR — Siemens cash deal at $113.00/share, last trade ~$111.85 on Nasdaq.
    # Feb 2025 month-end close ~ $111.50 (approximate).
    r = bmp_firm_month_return(
        prior_month_end_close=111.50,
        last_trade_close=111.85,
        bucket=CrspBucket.MERGER, exchange=Exchange.NASDAQ,
        payout_per_share=113.00,
    )
    # R_partial = 111.85/111.50 - 1 ≈ 0.00314
    # DLRET = 113/111.85 - 1 ≈ 0.01028
    # R_month ≈ 0.01345
    assert r == pytest.approx(0.01345, rel=5e-3)


def test_radioshack_compliance_failure_feb_2015():
    # RSH — Ch.11 bankruptcy filing 2015-02-05, delist 2015-02-09 on NYSE.
    # Stock collapsed from ~$0.50 (Jan close) to ~$0.05 (last quote).
    # NYSE Shumway = -0.30.
    r = bmp_firm_month_return(
        prior_month_end_close=0.50,
        last_trade_close=0.05,
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NYSE,
        payout_per_share=None,
    )
    # R_partial = 0.05/0.50 - 1 = -0.90
    # DLRET = -0.30
    # R_month = (0.10)(0.70) - 1 = -0.93
    assert r == pytest.approx(-0.93, rel=1e-3)


def test_altaba_liquidation_with_observed_recovery_nov_2019():
    # AABA — Altaba liquidation, returned ~$93/share in distributions vs
    # last trade ~$22.85. Recovery ratio reflects total returned-to-shareholders.
    # For this test, assume recovery_ratio=4.07 (very large; reflects fund-style
    # liquidation, not bankruptcy). This exercises that LIQUIDATION respects
    # observed recovery instead of Shumway.
    r = bmp_firm_month_return(
        prior_month_end_close=22.50,
        last_trade_close=22.85,
        bucket=CrspBucket.LIQUIDATION, exchange=Exchange.NYSE,
        payout_per_share=None,
        recovery_ratio=4.07,
    )
    # R_partial = 22.85/22.50 - 1 ≈ 0.01556
    # DLRET = 4.07 - 1 = 3.07
    # R_month = (1.01556)(4.07) - 1 ≈ 3.1333
    assert r == pytest.approx(3.1333, rel=1e-3)

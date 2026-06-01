"""Beaver-McNichols-Price (2007) firm-month return correction.

The unbiased firm-month return at delisting is:

    R_delisting_month = (1 + R_partial) * (1 + DLRET) - 1
    R_partial = last_trade_close / prior_month_end_close - 1

DLRET is computed by the hub module `dlret.py`. This module keeps the
firm-month compounding and re-exports the DLRET symbols for backward
compatibility.
"""

from __future__ import annotations

import math

from .crsp_codes import CrspBucket
from .dlret import (
    SHUMWAY_NYSE_AMEX, SHUMWAY_NASDAQ, compute_dlret, resolve_dlret, DlretResult, DlretMethod,
)
from .exchanges import Exchange


__all__ = [
    "SHUMWAY_NYSE_AMEX", "SHUMWAY_NASDAQ",
    "compute_dlret", "resolve_dlret", "DlretResult", "DlretMethod",
    "bmp_firm_month_return",
]


def bmp_firm_month_return(
    prior_month_end_close: float,
    last_trade_close: float,
    bucket: CrspBucket,
    exchange: Exchange,
    payout_per_share: float | None = None,
    recovery_ratio: float | None = None,
    stock_ratio: float | None = None,
    acquirer_price: float | None = None,
) -> float:
    """Compound R_partial and DLRET into the corrected firm-month return.

    Returns NaN for EXPIRATION and for invalid inputs (non-positive prior
    close). The caller treats NaN as \"drop this firm-month\".
    """
    dlret = compute_dlret(
        bucket=bucket, exchange=exchange,
        last_trade_close=last_trade_close,
        payout_per_share=payout_per_share,
        recovery_ratio=recovery_ratio,
        stock_ratio=stock_ratio,
        acquirer_price=acquirer_price,
    )
    if math.isnan(dlret):
        return float("nan")
    if prior_month_end_close <= 0:
        return float("nan")
    r_partial = (last_trade_close / prior_month_end_close) - 1.0
    return (1.0 + r_partial) * (1.0 + dlret) - 1.0

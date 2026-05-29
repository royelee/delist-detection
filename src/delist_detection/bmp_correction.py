"""Beaver-McNichols-Price (2007) firm-month return correction.

The CRSP "delisting bias" arises when the price panel truncates at the
last observed trade and discards the cash-out value at delist. BMP 2007
shows that the unbiased firm-month return is:

    R_delisting_month = (1 + R_partial) * (1 + DLRET) - 1

    R_partial = last_trade_close / prior_month_end_close - 1
    DLRET     = final_cashout_value  / last_trade_close      - 1

For panels without an observed DLRET (Tiingo, IEX, most alt-data feeds),
we synthesize DLRET per bucket:

  MERGER             : payout/last_trade - 1   (from EDGAR 8-K Item 2.01)
  EXCHANGE_TRANSFER  : 0                       (security continues; no shock)
  LIQUIDATION        : recovery_ratio - 1      (if observed)
                       Shumway constant by exchange (if not)
  COMPLIANCE_FAILURE : Shumway constant by exchange
  EXPIRATION         : NaN  (drop, not equity universe)

The Shumway constants come from:
  Shumway (1997)              : NYSE/AMEX performance delistings avg ~-30%
  Shumway & Warther (1999)    : Nasdaq performance delistings avg ~-55%
They are applied only when DLRET is unobservable AND the bucket is
performance-related (COMPLIANCE_FAILURE, or LIQUIDATION w/o recovery).
"""

from __future__ import annotations

import math

from .crsp_codes import CrspBucket
from .exchanges import Exchange


__all__ = [
    "SHUMWAY_NYSE_AMEX",
    "SHUMWAY_NASDAQ",
    "compute_dlret",
    "bmp_firm_month_return",
]


SHUMWAY_NYSE_AMEX: float = -0.30
SHUMWAY_NASDAQ: float = -0.55


def _shumway_constant(exchange: Exchange) -> float:
    """Return the exchange-appropriate Shumway constant.

    OTHER (OTC, BATS, IEX, unknown) defaults to the more conservative
    Nasdaq constant — it captures the typical "no real bid" outcome.
    """
    if exchange in (Exchange.NYSE, Exchange.AMEX):
        return SHUMWAY_NYSE_AMEX
    return SHUMWAY_NASDAQ


def compute_dlret(
    bucket: CrspBucket,
    exchange: Exchange,
    last_trade_close: float,
    payout_per_share: float | None,
    recovery_ratio: float | None = None,
) -> float:
    """Resolve DLRET for a single delisting event.

    Returns NaN for EXPIRATION (caller must drop). Returns 0.0 for
    EXCHANGE_TRANSFER (no shock at this venue; successor handles it).
    """
    if bucket is CrspBucket.EXPIRATION:
        return float("nan")

    if bucket is CrspBucket.EXCHANGE_TRANSFER:
        return 0.0

    if last_trade_close <= 0:
        return float("nan")

    if bucket is CrspBucket.MERGER:
        if payout_per_share is None:
            return 0.0  # neutral mark; caller may flag for review
        if payout_per_share < 0:
            return float("nan")
        return (payout_per_share / last_trade_close) - 1.0

    if bucket is CrspBucket.LIQUIDATION:
        if recovery_ratio is not None:
            if recovery_ratio < 0:
                return float("nan")
            return recovery_ratio - 1.0
        return _shumway_constant(exchange)

    if bucket is CrspBucket.COMPLIANCE_FAILURE:
        return _shumway_constant(exchange)

    # ACTIVE / UNKNOWN: no shock by default
    return 0.0


def bmp_firm_month_return(
    prior_month_end_close: float,
    last_trade_close: float,
    bucket: CrspBucket,
    exchange: Exchange,
    payout_per_share: float | None = None,
    recovery_ratio: float | None = None,
) -> float:
    """Compound R_partial and DLRET into the corrected firm-month return.

    Returns NaN for EXPIRATION and for invalid inputs (non-positive prior
    close). The caller treats NaN as "drop this firm-month".
    """
    dlret = compute_dlret(
        bucket=bucket, exchange=exchange,
        last_trade_close=last_trade_close,
        payout_per_share=payout_per_share,
        recovery_ratio=recovery_ratio,
    )
    if math.isnan(dlret):
        return float("nan")
    if prior_month_end_close <= 0:
        return float("nan")
    r_partial = (last_trade_close / prior_month_end_close) - 1.0
    return (1.0 + r_partial) * (1.0 + dlret) - 1.0

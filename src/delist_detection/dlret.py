"""DLRET hub: the self-explaining delisting-return computation.

`resolve_dlret(...)` returns a `DlretResult` (value + which rule fired +
terminal value). `compute_dlret(...)` is the backward-compatible float facade
(`= resolve_dlret(...).value`). The Shumway constants and exchange logic live
here; `bmp_correction.py` re-exports them for backward compatibility.

Merger DLRET captures the full consideration:
    terminal = cash_per_share + stock_ratio * acquirer_price
    DLRET    = terminal / last_trade_close - 1
Stock-leg terms and last_trade_close are externally provided.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .crsp_codes import CrspBucket
from .exchanges import Exchange


__all__ = [
    "SHUMWAY_NYSE_AMEX", "SHUMWAY_NASDAQ",
    "DlretMethod", "DlretResult", "resolve_dlret", "compute_dlret",
]


SHUMWAY_NYSE_AMEX: float = -0.30
SHUMWAY_NASDAQ: float = -0.55


class DlretMethod(str, Enum):
    CASH_ONLY = "cash_only"
    CASH_PLUS_STOCK = "cash_plus_stock"
    STOCK_ONLY = "stock_only"
    ABSTAIN_NO_CONSIDERATION = "abstain_no_consideration"
    NEEDS_LAST_TRADE = "needs_last_trade"
    EXCHANGE_TRANSFER_ZERO = "exchange_transfer_zero"
    RECOVERY_RATIO = "recovery_ratio"
    SHUMWAY_NYSE_AMEX = "shumway_nyse_amex"
    SHUMWAY_NASDAQ = "shumway_nasdaq"
    WORTHLESS = "worthless"            # reserved; not emitted in v1
    DROPPED_EXPIRATION = "dropped_expiration"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DlretResult:
    value: float                 # may be NaN
    method: DlretMethod
    terminal_value: float | None


def _shumway_result(exchange: Exchange) -> DlretResult:
    if exchange in (Exchange.NYSE, Exchange.AMEX):
        return DlretResult(SHUMWAY_NYSE_AMEX, DlretMethod.SHUMWAY_NYSE_AMEX, None)
    return DlretResult(SHUMWAY_NASDAQ, DlretMethod.SHUMWAY_NASDAQ, None)


def _resolve_merger(
    last_trade_close: float | None,
    payout_per_share: float | None,
    stock_ratio: float | None,
    acquirer_price: float | None,
) -> DlretResult:
    # A dangling stock term would silently understate DLRET to the cash floor with
    # falsely-high confidence; fail loud instead.
    if (stock_ratio is None) != (acquirer_price is None):
        raise ValueError(
            "merger stock leg under-specified: stock_ratio and acquirer_price "
            "must both be provided or both omitted"
        )

    cash: float | None = None
    if payout_per_share is not None:
        if payout_per_share < 0:
            return DlretResult(float("nan"), DlretMethod.UNKNOWN, None)
        cash = float(payout_per_share)

    stock: float | None = None
    if stock_ratio is not None and acquirer_price is not None:
        leg = float(stock_ratio) * float(acquirer_price)
        if leg < 0:
            return DlretResult(float("nan"), DlretMethod.UNKNOWN, None)
        stock = leg

    legs = [x for x in (cash, stock) if x is not None]

    # A valid last trade price is required. This guard precedes the
    # no-consideration abstain so a bad/absent price stays a NaN drop
    # regardless of legs — exactly as the original compute_dlret did, keeping
    # the firm-month path byte-for-byte unchanged.
    if last_trade_close is None or last_trade_close <= 0:
        method = (DlretMethod.ABSTAIN_NO_CONSIDERATION if not legs
                  else DlretMethod.NEEDS_LAST_TRADE)
        return DlretResult(float("nan"), method, None)

    if not legs:
        return DlretResult(0.0, DlretMethod.ABSTAIN_NO_CONSIDERATION, None)

    terminal = float(sum(legs))
    if cash is not None and stock is not None:
        method = DlretMethod.CASH_PLUS_STOCK
    elif cash is not None:
        method = DlretMethod.CASH_ONLY
    else:
        method = DlretMethod.STOCK_ONLY
    return DlretResult(terminal / last_trade_close - 1.0, method, terminal)


def resolve_dlret(
    bucket: CrspBucket,
    exchange: Exchange,
    last_trade_close: float | None,
    payout_per_share: float | None = None,
    stock_ratio: float | None = None,
    acquirer_price: float | None = None,
    recovery_ratio: float | None = None,
) -> DlretResult:
    if bucket is CrspBucket.EXPIRATION:
        return DlretResult(float("nan"), DlretMethod.DROPPED_EXPIRATION, None)
    if bucket is CrspBucket.EXCHANGE_TRANSFER:
        return DlretResult(0.0, DlretMethod.EXCHANGE_TRANSFER_ZERO, None)

    if bucket is CrspBucket.MERGER:
        return _resolve_merger(last_trade_close, payout_per_share, stock_ratio, acquirer_price)

    # Remaining buckets require a valid last trade price (preserves the
    # original compute_dlret guard, incl. the bad-price -> NaN cases).
    if last_trade_close is None or last_trade_close <= 0:
        return DlretResult(float("nan"), DlretMethod.UNKNOWN, None)

    if bucket is CrspBucket.LIQUIDATION:
        if recovery_ratio is not None:
            if recovery_ratio < 0:
                return DlretResult(float("nan"), DlretMethod.UNKNOWN, None)
            return DlretResult(
                recovery_ratio - 1.0, DlretMethod.RECOVERY_RATIO,
                recovery_ratio * last_trade_close,
            )
        return _shumway_result(exchange)

    if bucket is CrspBucket.COMPLIANCE_FAILURE:
        return _shumway_result(exchange)

    # ACTIVE / UNKNOWN: no shock by default (preserves original behavior).
    return DlretResult(0.0, DlretMethod.UNKNOWN, None)


def compute_dlret(
    bucket: CrspBucket,
    exchange: Exchange,
    last_trade_close: float | None,
    payout_per_share: float | None = None,
    recovery_ratio: float | None = None,
    stock_ratio: float | None = None,
    acquirer_price: float | None = None,
) -> float:
    """Backward-compatible float facade over `resolve_dlret`."""
    return resolve_dlret(
        bucket, exchange, last_trade_close, payout_per_share,
        stock_ratio, acquirer_price, recovery_ratio,
    ).value

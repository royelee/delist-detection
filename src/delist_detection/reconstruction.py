"""DLRET reconstruction: the library's primary output.

`enrich()` joins a classification `DelistRecord` with externally-provided DLRET
inputs (last_trade_close, cash/stock merger terms, recovery) and the computed
DLRET into a single `EnrichedDelistRecord` — the central type every downstream
consumer can derive from. `build_dlret_table()` (added next) serializes a
sequence of these into `output/dlret.csv`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .dlret import DlretMethod, resolve_dlret
from .exchanges import Exchange


@dataclass(frozen=True)
class EnrichedDelistRecord:
    # --- classification (from DelistRecord) ---
    ticker: str
    cik: int | None
    observed_delist_date: str | None
    crsp_code: int | None
    bucket: CrspBucket
    confidence: str
    reason: str
    evidence: dict | None
    # --- DLRET inputs (externally provided) ---
    exchange: Exchange
    last_trade_close: float | None
    payout_per_share: float | None
    stock_ratio: float | None
    acquirer_price: float | None
    acquirer_ticker: str | None
    recovery_ratio: float | None
    # --- DLRET outputs ---
    dlret: float
    dlret_method: DlretMethod
    terminal_value: float | None
    dlret_confidence: str
    # --- provenance carried through ---
    payout_source: str | None
    payout_confidence: str | None


def _dlret_confidence(value: float, method: DlretMethod, payout_confidence: str | None) -> str:
    if math.isnan(value):
        return "low"                     # never high when NaN
    if method is DlretMethod.CASH_ONLY:
        return payout_confidence or "high"
    if method is DlretMethod.EXCHANGE_TRANSFER_ZERO:
        return "high"
    if method in (
        DlretMethod.CASH_PLUS_STOCK, DlretMethod.STOCK_ONLY,
        DlretMethod.SHUMWAY_NYSE_AMEX, DlretMethod.SHUMWAY_NASDAQ,
        DlretMethod.RECOVERY_RATIO,
    ):
        return "medium"
    return "low"                         # ABSTAIN_NO_CONSIDERATION / UNKNOWN


def enrich(
    record: DelistRecord,
    *,
    exchange: Exchange = Exchange.OTHER,
    last_trade_close: float | None = None,
    payout_per_share: float | None = None,
    stock_ratio: float | None = None,
    acquirer_price: float | None = None,
    acquirer_ticker: str | None = None,
    recovery_ratio: float | None = None,
    payout_source: str | None = None,
    payout_confidence: str | None = None,
) -> EnrichedDelistRecord:
    res = resolve_dlret(
        record.bucket, exchange, last_trade_close,
        payout_per_share, stock_ratio, acquirer_price, recovery_ratio,
    )
    return EnrichedDelistRecord(
        ticker=record.ticker, cik=record.cik,
        observed_delist_date=record.observed_delist_date,
        crsp_code=record.crsp_code, bucket=record.bucket,
        confidence=record.confidence, reason=record.reason, evidence=record.evidence,
        exchange=exchange, last_trade_close=last_trade_close,
        payout_per_share=payout_per_share, stock_ratio=stock_ratio,
        acquirer_price=acquirer_price, acquirer_ticker=acquirer_ticker,
        recovery_ratio=recovery_ratio,
        dlret=res.value, dlret_method=res.method, terminal_value=res.terminal_value,
        dlret_confidence=_dlret_confidence(res.value, res.method, payout_confidence),
        payout_source=payout_source, payout_confidence=payout_confidence,
    )

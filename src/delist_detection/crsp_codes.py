"""CRSP DLSTCD scheme and the train/backtest bucket mapping we use.

Five operational buckets, each with deterministic train/backtest handling:

    ACTIVE              — still trading (DLSTCD == 100)
    MERGER              — 200s, neutral-to-positive return event, use cash payout
    EXCHANGE_TRANSFER   — 300s, ticker continues elsewhere; re-link, don't drop
    LIQUIDATION         — 400s, partial recovery; apply realized recovery
    COMPLIANCE_FAILURE  — 500s (and the dangerous half of 400s); apply -100% terminal
    EXPIRATION          — 600s, scheduled end (warrants/units/ADRs); drop from equity universe
    UNKNOWN             — could not classify with confidence
"""

from __future__ import annotations

from enum import Enum


class CrspBucket(str, Enum):
    ACTIVE = "active"
    MERGER = "merger"
    EXCHANGE_TRANSFER = "exchange_transfer"
    LIQUIDATION = "liquidation"
    COMPLIANCE_FAILURE = "compliance_failure"
    EXPIRATION = "expiration"
    UNKNOWN = "unknown"


DLST_CODE_TO_BUCKET: dict[int, CrspBucket] = {
    100: CrspBucket.ACTIVE,
    200: CrspBucket.MERGER, 231: CrspBucket.MERGER, 233: CrspBucket.MERGER,
    241: CrspBucket.MERGER, 251: CrspBucket.MERGER, 252: CrspBucket.MERGER,
    261: CrspBucket.MERGER, 262: CrspBucket.MERGER,
    300: CrspBucket.EXCHANGE_TRANSFER, 301: CrspBucket.EXCHANGE_TRANSFER,
    302: CrspBucket.EXCHANGE_TRANSFER, 303: CrspBucket.EXCHANGE_TRANSFER,
    304: CrspBucket.EXCHANGE_TRANSFER,
    400: CrspBucket.LIQUIDATION, 470: CrspBucket.LIQUIDATION,
    500: CrspBucket.COMPLIANCE_FAILURE, 520: CrspBucket.COMPLIANCE_FAILURE,
    535: CrspBucket.COMPLIANCE_FAILURE, 550: CrspBucket.COMPLIANCE_FAILURE,
    552: CrspBucket.COMPLIANCE_FAILURE, 560: CrspBucket.COMPLIANCE_FAILURE,
    570: CrspBucket.COMPLIANCE_FAILURE, 573: CrspBucket.COMPLIANCE_FAILURE,
    574: CrspBucket.COMPLIANCE_FAILURE, 580: CrspBucket.COMPLIANCE_FAILURE,
    584: CrspBucket.COMPLIANCE_FAILURE, 585: CrspBucket.COMPLIANCE_FAILURE,
    600: CrspBucket.EXPIRATION,
}


def bucket_for_code(code: int | None) -> CrspBucket:
    if code is None:
        return CrspBucket.UNKNOWN
    if code in DLST_CODE_TO_BUCKET:
        return DLST_CODE_TO_BUCKET[code]
    if 200 <= code < 300:
        return CrspBucket.MERGER
    if 300 <= code < 400:
        return CrspBucket.EXCHANGE_TRANSFER
    if 400 <= code < 500:
        return CrspBucket.LIQUIDATION
    if 500 <= code < 600:
        return CrspBucket.COMPLIANCE_FAILURE
    if 600 <= code < 700:
        return CrspBucket.EXPIRATION
    return CrspBucket.UNKNOWN

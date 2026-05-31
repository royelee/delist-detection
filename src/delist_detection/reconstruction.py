"""DLRET reconstruction: the library's primary output.

`enrich()` joins a classification `DelistRecord` with externally-provided DLRET
inputs (last_trade_close, cash/stock merger terms, recovery) and the computed
DLRET into a single `EnrichedDelistRecord` — the central type every downstream
consumer can derive from. `build_dlret_table()` (added next) serializes a
sequence of these into `output/dlret.csv`.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .dlret import DlretMethod, resolve_dlret
from .exchanges import Exchange, normalize_exchange


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


DLRET_TABLE_COLUMNS = [
    "ticker", "bucket", "observed_delist_date", "crsp_code", "dlret", "reason",
    "exchange", "last_trade_close", "payout_per_share", "stock_ratio",
    "acquirer_price", "acquirer_ticker", "recovery_ratio", "terminal_value",
    "dlret_method", "dlret_confidence", "payout_source",
]


def build_dlret_table(
    records: Iterable[DelistRecord],
    *,
    last_trade_closes: Mapping[str, float] | None = None,
    payouts: Mapping[str, float] | None = None,
    exchanges: Mapping[str, str] | None = None,
    merger_terms: Mapping[str, dict] | None = None,
    recovery_ratios: Mapping[str, float] | None = None,
    payout_sources: Mapping[str, str] | None = None,
    payout_confidences: Mapping[str, str] | None = None,
) -> list[EnrichedDelistRecord]:
    """Enrich each classification record into the primary DLRET table.

    Lookups are keyed on the upper-cased ticker. `merger_terms[ticker]` is a
    dict with optional keys: cash_per_share (overrides `payouts`), stock_ratio,
    acquirer_price, acquirer_ticker.
    """
    last_trade_closes = last_trade_closes or {}
    payouts = payouts or {}
    exchanges = exchanges or {}
    merger_terms = merger_terms or {}
    recovery_ratios = recovery_ratios or {}
    payout_sources = payout_sources or {}
    payout_confidences = payout_confidences or {}

    out: list[EnrichedDelistRecord] = []
    for rec in records:
        key = rec.ticker.upper()
        terms = merger_terms.get(key, {})
        cash = terms.get("cash_per_share", payouts.get(key))
        out.append(enrich(
            rec,
            exchange=normalize_exchange(exchanges.get(key)),
            last_trade_close=last_trade_closes.get(key),
            payout_per_share=cash,
            stock_ratio=terms.get("stock_ratio"),
            acquirer_price=terms.get("acquirer_price"),
            acquirer_ticker=terms.get("acquirer_ticker"),
            recovery_ratio=recovery_ratios.get(key),
            payout_source=payout_sources.get(key),
            payout_confidence=payout_confidences.get(key),
        ))
    return out


def _fmt(x: object) -> str:
    if x is None:
        return ""
    if isinstance(x, float):
        if math.isnan(x):
            return ""
        return f"{x:.6f}"
    return str(x)


def enriched_to_row(e: EnrichedDelistRecord) -> dict:
    return {
        "ticker": e.ticker,
        "bucket": e.bucket.value,
        "observed_delist_date": _fmt(e.observed_delist_date),
        "crsp_code": _fmt(e.crsp_code),
        "dlret": _fmt(e.dlret),
        "reason": e.reason,
        "exchange": e.exchange.value,
        "last_trade_close": _fmt(e.last_trade_close),
        "payout_per_share": _fmt(e.payout_per_share),
        "stock_ratio": _fmt(e.stock_ratio),
        "acquirer_price": _fmt(e.acquirer_price),
        "acquirer_ticker": _fmt(e.acquirer_ticker),
        "recovery_ratio": _fmt(e.recovery_ratio),
        "terminal_value": _fmt(e.terminal_value),
        "dlret_method": e.dlret_method.value,
        "dlret_confidence": e.dlret_confidence,
        "payout_source": _fmt(e.payout_source),
    }


def write_dlret_csv(records: Iterable[EnrichedDelistRecord], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=DLRET_TABLE_COLUMNS)
        writer.writeheader()
        for e in records:
            writer.writerow(enriched_to_row(e))


def load_merger_terms_csv(path: str | Path) -> dict[str, dict]:
    """Load merger-consideration terms keyed by upper-cased ticker.

    CSV columns: ticker, cash_per_share, stock_ratio, acquirer_price,
    acquirer_ticker. Blank numeric cells are omitted from the per-ticker dict.
    """
    out: dict[str, dict] = {}
    with Path(path).open(newline="") as fh:
        for row in csv.DictReader(fh):
            tkr = (row.get("ticker") or "").strip().upper()
            if not tkr:
                continue
            terms: dict = {}
            for k in ("cash_per_share", "stock_ratio", "acquirer_price"):
                v = (row.get(k) or "").strip()
                if v:
                    terms[k] = float(v)
            acq = (row.get("acquirer_ticker") or "").strip()
            if acq:
                terms["acquirer_ticker"] = acq
            out[tkr] = terms
    return out


def load_float_map_csv(path: str | Path, value_col: str) -> dict[str, float]:
    """Load a {ticker(upper): float} map from a CSV with columns ticker, <value_col>.

    Raises ValueError if the CSV header lacks 'ticker' or value_col, so a mistyped
    --last-trade-closes/--recoveries column fails loudly instead of silently
    returning {} (which would make every merger fall back to the no-price branch).
    Rows with a blank ticker or blank value are skipped.
    """
    out: dict[str, float] = {}
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        missing = [c for c in ("ticker", value_col) if c not in fields]
        if missing:
            raise ValueError(
                f"{path}: CSV missing required column(s) {missing}; found {fields}"
            )
        for row in reader:
            tkr = (row.get("ticker") or "").strip().upper()
            val = (row.get(value_col) or "").strip()
            if tkr and val:
                out[tkr] = float(val)
    return out

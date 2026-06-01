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
from .dlret import DlretMethod, DlretResult, resolve_dlret
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


_VALID_CONF = {"high", "medium", "low"}


def _dlret_confidence(value: float, method: DlretMethod, payout_confidence: str | None) -> str:
    if math.isnan(value):
        return "low"                     # never high when NaN
    if method is DlretMethod.CASH_ONLY:
        return payout_confidence if payout_confidence in _VALID_CONF else "medium"
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
    # No empty DLRET in the table: a completed merger or a fund/non-equity closure
    # with a known last price but no computable consideration has terminal value
    # ≈ that last price (merger arbitrage closes the gap to the deal value before
    # the last trade; a fund/ETF redeems at NAV ≈ its last trade). So DLRET ≈ 0 is
    # the maximum-likelihood estimate, NOT a missing value — emit it as ASSUMED_PAR
    # at low confidence so a reader never mistakes it for a realized/computed
    # return. Buckets whose price collapses AFTER delisting (compliance, liquidation)
    # already carry Shumway/recovery marks and never reach an abstain here. A valid
    # positive last price is required (no denominator otherwise). This is a
    # table-only estimate; the firm-month facade (compute_dlret) is untouched.
    if (
        record.bucket in (CrspBucket.MERGER, CrspBucket.EXPIRATION)
        and res.method in (DlretMethod.ABSTAIN_NO_CONSIDERATION, DlretMethod.DROPPED_EXPIRATION)
        and last_trade_close is not None and last_trade_close > 0
    ):
        res = DlretResult(0.0, DlretMethod.ASSUMED_PAR, last_trade_close)
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


# A merger/expiration abstain WITH a valid last price is upgraded to ASSUMED_PAR
# (DLRET 0, see enrich) and rendered, so the only abstains that reach the table are
# the no-price ones (NaN) — those, and UNKNOWN, are blanked so a reader never
# mistakes a genuinely-uncomputable row for a realized 0%. EXCHANGE_TRANSFER_ZERO
# and ASSUMED_PAR keep their explicit 0.
_DLRET_BLANK_IN_TABLE = {DlretMethod.ABSTAIN_NO_CONSIDERATION, DlretMethod.UNKNOWN}

DLRET_TABLE_COLUMNS = [
    "ticker", "bucket", "observed_delist_date", "crsp_code", "dlret", "reason",
    "exchange", "last_trade_close", "payout_per_share", "stock_ratio",
    "acquirer_price", "acquirer_ticker", "recovery_ratio", "terminal_value",
    "dlret_method", "dlret_confidence", "payout_source",
]


def _lookup(m: Mapping, ticker: str, observed_date: str | None):
    """Per-event lookup: an exact (ticker, observed_date) override wins; otherwise
    fall back to a bare-ticker default. Returns None if neither is present.

    This lets a recycled ticker (>1 delisting event) carry per-event inputs while
    the common single-event case stays a plain {ticker: value} map.
    """
    if (ticker, observed_date) in m:
        return m[(ticker, observed_date)]
    return m.get(ticker)


def build_dlret_table(
    records: Iterable[DelistRecord],
    *,
    last_trade_closes: Mapping[str | tuple[str, str | None], float] | None = None,
    payouts: Mapping[str | tuple[str, str | None], float] | None = None,
    exchanges: Mapping[str | tuple[str, str | None], str] | None = None,
    merger_terms: Mapping[str | tuple[str, str | None], dict] | None = None,
    recovery_ratios: Mapping[str | tuple[str, str | None], float] | None = None,
    payout_sources: Mapping[str | tuple[str, str | None], str] | None = None,
    payout_confidences: Mapping[str | tuple[str, str | None], str] | None = None,
) -> list[EnrichedDelistRecord]:
    """Enrich each classification record into the primary DLRET table.

    Lookups support two key forms for each input map:

    - Bare ticker (``"AET"``): applies to every delisting event for that ticker.
      This is the existing behavior and all single-event tickers should use it.
    - Per-event tuple (``("AET", "2018-11-28")``): applies only to the event
      whose ``observed_delist_date`` matches. This wins over the bare-ticker
      default, enabling recycled tickers (e.g. ALTR = Altera 2015 + Altair 2025)
      to carry different ``last_trade_close``, ``payout_per_share``, or
      ``exchange`` for each delisting.

    ``merger_terms[key]`` is a dict with optional keys: ``cash_per_share``
    (overrides ``payouts``), ``stock_ratio``, ``acquirer_price``,
    ``acquirer_ticker``.
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
        date = rec.observed_delist_date
        terms = _lookup(merger_terms, key, date) or {}
        cash = terms.get("cash_per_share", _lookup(payouts, key, date))
        out.append(enrich(
            rec,
            exchange=normalize_exchange(_lookup(exchanges, key, date)),
            last_trade_close=_lookup(last_trade_closes, key, date),
            payout_per_share=cash,
            stock_ratio=terms.get("stock_ratio"),
            acquirer_price=terms.get("acquirer_price"),
            acquirer_ticker=terms.get("acquirer_ticker"),
            recovery_ratio=_lookup(recovery_ratios, key, date),
            payout_source=_lookup(payout_sources, key, date),
            payout_confidence=_lookup(payout_confidences, key, date),
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
        "dlret": "" if e.dlret_method in _DLRET_BLANK_IN_TABLE else _fmt(e.dlret),
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


def load_merger_terms_csv(path: str | Path) -> dict[str | tuple[str, str], dict]:
    """Load merger-consideration terms keyed by upper-cased ticker.

    CSV columns: ticker, cash_per_share, stock_ratio, acquirer_price,
    acquirer_ticker. Blank numeric cells are omitted from the per-ticker dict.

    Optional column ``observed_delist_date``: when a row's date cell is
    non-blank, the entry is keyed by ``(ticker_upper, date)`` for per-event
    precision (recycled tickers). A blank/absent date cell falls back to a
    bare ``ticker_upper`` key that applies to all events of that ticker.
    """
    out: dict[str | tuple[str, str], dict] = {}
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
            if ("stock_ratio" in terms) != ("acquirer_price" in terms):
                raise ValueError(
                    f"{path}: ticker {tkr} has an incomplete stock leg — "
                    "stock_ratio and acquirer_price must both be present or both absent"
                )
            date = (row.get("observed_delist_date") or "").strip()
            out_key: str | tuple[str, str] = (tkr, date) if date else tkr
            out[out_key] = terms
    return out


def load_float_map_csv(path: str | Path, value_col: str) -> dict[str | tuple[str, str], float]:
    """Load a {ticker(upper): float} map from a CSV with columns ticker, <value_col>.

    Raises ValueError if the CSV header lacks 'ticker' or value_col, so a mistyped
    --last-trade-closes/--recoveries column fails loudly instead of silently
    returning {} (which would make every merger fall back to the no-price branch).
    Rows with a blank ticker or blank value are skipped.

    Optional column ``observed_delist_date``: when a row's date cell is
    non-blank, the entry is keyed by ``(ticker_upper, date)`` for per-event
    precision (recycled tickers). A blank/absent date cell falls back to a
    bare ``ticker_upper`` key that applies to all events of that ticker.
    """
    out: dict[str | tuple[str, str], float] = {}
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
                date = (row.get("observed_delist_date") or "").strip()
                out_key: str | tuple[str, str] = (tkr, date) if date else tkr
                out[out_key] = float(val)
    return out

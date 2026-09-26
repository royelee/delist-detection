"""DLRET reconstruction: the library's primary output.

`enrich()` joins a classification `DelistRecord` with externally-provided DLRET
inputs (last_trade_close, cash/stock merger terms, recovery) and the computed
DLRET into a single `EnrichedDelistRecord` — the central type every downstream
consumer can derive from. `build_delistings_table()` enriches a whole sequence
of records, keyed by `(sec_id, delist_date)`, and `delisting_row()` projects
one `EnrichedDelistRecord` into an `output/delistings.csv` row; `store.py` owns
writing the CSV.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

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
    # --- review ---
    review_flags: tuple[str, ...] = ()
    sec_id: str | None = None
    delist_date: str | None = None


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
    extra_flags: Iterable[str] = (),
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
    # The same holds for a deregistration the classifier found no merger or
    # distress evidence for (UNKNOWN + evidence["deregistered"]).
    if (record.bucket is CrspBucket.UNKNOWN and (record.evidence or {}).get("deregistered")
            and last_trade_close is not None and last_trade_close > 0):
        res = DlretResult(0.0, DlretMethod.ASSUMED_PAR, last_trade_close)
    if (
        record.bucket in (CrspBucket.MERGER, CrspBucket.EXPIRATION)
        and res.method in (DlretMethod.ABSTAIN_NO_CONSIDERATION, DlretMethod.DROPPED_EXPIRATION)
        and last_trade_close is not None and last_trade_close > 0
    ):
        res = DlretResult(0.0, DlretMethod.ASSUMED_PAR, last_trade_close)
    flags = list((record.evidence or {}).get("flags", [])) + list(extra_flags)
    # A merger whose consideration was never found lands at par silently, which
    # reads as a realized 0% return. Flag it so review.csv lists the row.
    if record.bucket is CrspBucket.MERGER and res.method is DlretMethod.ASSUMED_PAR:
        flags.append("merger_at_par")
    if (record.bucket in (CrspBucket.COMPLIANCE_FAILURE, CrspBucket.LIQUIDATION)
            and last_trade_close is not None and last_trade_close >= 5.0):
        flags.append("distress_at_normal_price")
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
        review_flags=tuple(dict.fromkeys(flags)),
        sec_id=record.sec_id, delist_date=record.delist_date,
    )


# A merger/expiration abstain WITH a valid last price is upgraded to ASSUMED_PAR
# (DLRET 0, see enrich) and rendered, so the only abstains that reach the table are
# the no-price ones (NaN) — those, and UNKNOWN, are blanked so a reader never
# mistakes a genuinely-uncomputable row for a realized 0%. EXCHANGE_TRANSFER_ZERO
# and ASSUMED_PAR keep their explicit 0.
_DLRET_BLANK_IN_TABLE = {DlretMethod.ABSTAIN_NO_CONSIDERATION, DlretMethod.UNKNOWN}


class DelistingKey(NamedTuple):
    """One delisting, as delistings.csv keys it. A plain tuple of the same two
    values is the same key (an override file's `(sec_id, delist_date)` rows)."""
    sec_id: str
    delist_date: str | None


def for_delisting(m: Mapping, key: tuple[str, str | None]):
    """The value `m` holds for the delisting `key`: its exact `(sec_id,
    delist_date)` entry wins; otherwise the security-wide `sec_id` entry. None
    if neither is present.

    This lets a security with more than one delisting carry per-delisting inputs
    while the common single-delisting case stays a plain {sec_id: value} map.
    """
    sec_id, _ = key
    if key in m:
        return m[key]
    return m.get(sec_id)


def build_delistings_table(
    records: Iterable[DelistRecord],
    *,
    last_trade_closes: Mapping | None = None,
    payouts: Mapping | None = None,
    exchanges: Mapping | None = None,
    merger_terms: Mapping | None = None,
    recovery_ratios: Mapping | None = None,
    payout_sources: Mapping | None = None,
    payout_confidences: Mapping | None = None,
    payout_flags: Mapping | None = None,
) -> list[EnrichedDelistRecord]:
    """Enrich each delisting into a `delistings.csv` record.

    Every input map is keyed by `sec_id` (applies to all of the security's
    delistings) or `(sec_id, delist_date)` (one delisting, which wins).
    `merger_terms[key]` may hold `cash_per_share` (overrides `payouts`),
    `stock_ratio`, `acquirer_price`, `acquirer_ticker`.
    """
    last_trade_closes = last_trade_closes or {}
    payouts = payouts or {}
    exchanges = exchanges or {}
    merger_terms = merger_terms or {}
    recovery_ratios = recovery_ratios or {}
    payout_sources = payout_sources or {}
    payout_confidences = payout_confidences or {}
    payout_flags = payout_flags or {}

    out: list[EnrichedDelistRecord] = []
    for rec in records:
        key = DelistingKey(rec.sec_id or rec.ticker.upper(), rec.delist_date)
        terms = for_delisting(merger_terms, key) or {}
        cash = terms.get("cash_per_share", for_delisting(payouts, key))
        out.append(enrich(
            rec,
            exchange=normalize_exchange(for_delisting(exchanges, key)),
            last_trade_close=for_delisting(last_trade_closes, key),
            payout_per_share=cash,
            stock_ratio=terms.get("stock_ratio"),
            acquirer_price=terms.get("acquirer_price"),
            acquirer_ticker=terms.get("acquirer_ticker"),
            recovery_ratio=for_delisting(recovery_ratios, key),
            payout_source=for_delisting(payout_sources, key),
            payout_confidence=for_delisting(payout_confidences, key),
            extra_flags=for_delisting(payout_flags, key) or (),
        ))
    return out


_ROW_EXTRAS = ("exchange", "last_trade_date", "last_trade_date_source", "successor_sec_id", "acquirer_sec_id",
               "raw_payout_per_share", "raw_payout_source", "raw_payout_confidence")


def delisting_row(e: EnrichedDelistRecord, **extra) -> dict:
    unknown = set(extra) - set(_ROW_EXTRAS)
    if unknown:
        raise TypeError(f"delisting_row: unexpected field(s) {sorted(unknown)}")
    ev = e.evidence or {}
    delist_filing = ev.get("delist_filing") or {}
    anchor_8k = ev.get("anchor_8k") or {}
    dereg_filing = ev.get("dereg_filing") or {}
    row = {
        "sec_id": e.sec_id, "delist_date": e.delist_date, "ticker": e.ticker, "cik": e.cik,
        "bucket": e.bucket.value, "crsp_code": e.crsp_code, "confidence": e.confidence, "reason": e.reason,
        "exchange": e.exchange.value,
        "last_trade_close": e.last_trade_close, "payout_per_share": e.payout_per_share,
        "stock_ratio": e.stock_ratio, "acquirer_price": e.acquirer_price, "acquirer_ticker": e.acquirer_ticker,
        "recovery_ratio": e.recovery_ratio, "terminal_value": e.terminal_value,
        "dlret": None if e.dlret_method in _DLRET_BLANK_IN_TABLE else e.dlret,
        "dlret_method": e.dlret_method.value, "dlret_confidence": e.dlret_confidence,
        "payout_source": e.payout_source,
        "delist_filing_form": delist_filing.get("form"), "delist_filing_date": delist_filing.get("filing_date"),
        "delist_filing_accession": delist_filing.get("accession"), "anchor_8k_items": anchor_8k.get("items"),
        "dereg_form": dereg_filing.get("form"), "resolved_name": ev.get("name"),
        "resolution_source": ev.get("resolution_source"),
        "review_flags": ";".join(e.review_flags),
    }
    row.update(extra)
    return row


def _key(row: Mapping[str, str], path) -> str | tuple[str, str] | None:
    sid = (row.get("sec_id") or "").strip()
    if not sid:
        return None
    date = (row.get("delist_date") or "").strip()
    return (sid, date) if date else sid


def load_float_overrides(path: str | Path, value_col: str) -> dict[str | tuple[str, str], float]:
    out: dict[str | tuple[str, str], float] = {}
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in ("sec_id", value_col) if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: CSV missing required column(s) {missing}; found {reader.fieldnames}")
        for row in reader:
            key, val = _key(row, path), (row.get(value_col) or "").strip()
            if key is not None and val:
                out[key] = float(val)
    return out


def load_merger_terms_overrides(path: str | Path) -> dict[str | tuple[str, str], dict]:
    out: dict[str | tuple[str, str], dict] = {}
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        if "sec_id" not in (reader.fieldnames or []):
            raise ValueError(f"{path}: CSV missing required column 'sec_id'; found {reader.fieldnames}")
        for row in reader:
            key = _key(row, path)
            if key is None:
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
                raise ValueError(f"{path}: {key} has an incomplete stock leg — stock_ratio and acquirer_price "
                                 "must both be present or both absent")
            out[key] = terms
    return out


def unmatched_override_keys(overrides: Mapping, events: Iterable[tuple[str, str]]) -> list:
    events = list(events)
    sids = {s for s, _ in events}
    pairs = set(events)
    return [k for k in overrides if (k not in pairs if isinstance(k, tuple) else k not in sids)]

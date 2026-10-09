"""DLRET reconstruction: the library's primary output.

`DelistRecord` is one delisting as the classifier hands it over, defined here, below the stages, so the table, the
merger readers and the handling read it without loading the classifier. `enrich()` joins a classification
`DelistRecord` with its value inputs (`dlret.ValueInputs`: the last close, a merger's terms, the caller's answers)
and the DLRET `dlret.decide` answers for them into a single `EnrichedDelistRecord` -- the central type every
downstream consumer can derive from -- with the review flags the value raises. `delisting_row()` projects one
`EnrichedDelistRecord` into an `output/delistings.csv` row; `store.py` owns writing the CSV. The caller's override
files (`--last-trade-closes`, `--merger-terms`, `--recoveries`) are read here too, keyed by `sec_id` or
`(sec_id, delist_date)` (`for_delisting`).
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..vocabulary.crsp_codes import CrspBucket
from .dlret import DlretMethod, EndingValue, ValueInputs, decide
from ..vocabulary.exchanges import Exchange


@dataclass
class DelistRecord:
    """One delisting as the classifier hands it over (`endings/classifier.py` builds it, the finder carries it on its
    `Delisting`): its CRSP code and bucket, confidence, reason and evidence, and the security, delisting date and
    successors the run settles. `enrich` starts its delistings.csv row from it, and the handling rebuilds it from that
    row (`qlib_adapter.record_from_row`)."""
    ticker: str
    cik: int | None
    observed_delist_date: str | None
    crsp_code: int | None
    bucket: CrspBucket
    confidence: str            # 'high' | 'medium' | 'low' | 'none'
    reason: str
    evidence: dict = field(default_factory=dict)
    sec_id: str | None = None                 # the security's US composite FIGI (or placeholder)
    delist_date: str | None = None            # Form 25 effective date (filing + 10 days) or fallback filing date
    successor_sec_id: str | None = None       # a continuation: the security a holder's shares became, one for one
    ticker_successor_sec_id: str | None = None   # another security that took over this ticker (not a continuation)

    @property
    def deregistered(self) -> bool:
        """The classifier found a deregistration and no merger or distress evidence (`evidence["deregistered"]`):
        an unknown ending valued at par (`dlret.ValueInputs.deregistered`)."""
        return bool((self.evidence or {}).get("deregistered"))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bucket"] = self.bucket.value
        return d


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
    # --- the DLRET dlret.decide answered ---
    answer: EndingValue
    # --- provenance carried through ---
    payout_source: str | None
    payout_confidence: str | None
    # --- review ---
    review_flags: tuple[str, ...] = ()
    sec_id: str | None = None
    delist_date: str | None = None

    @property
    def dlret(self) -> float:
        return self.answer.value

    @property
    def dlret_method(self) -> DlretMethod:
        return self.answer.method

    @property
    def terminal_value(self) -> float | None:
        return self.answer.terminal_value

    @property
    def dlret_confidence(self) -> str:
        return self.answer.confidence


def enrich(record: DelistRecord, value: ValueInputs, *, acquirer_ticker: str | None = None,
           payout_source: str | None = None, extra_flags: Iterable[str] = ()) -> EnrichedDelistRecord:
    """One delistings.csv record: `record`'s classification, its value inputs (`value`, of the record's own bucket)
    and the DLRET `dlret.decide` answers for them, with the merger's provenance (`acquirer_ticker`, `payout_source`)
    and its flags (`extra_flags`, after the classification's own). Two review flags follow from the value: a merger
    left at par (`merger_at_par`: its consideration was never found, which reads as a realized 0% return) and a
    distress ending at a normal price (`distress_at_normal_price`: a last close of $5 or more)."""
    if value.bucket is not record.bucket:
        raise ValueError(f"enrich: value inputs of bucket {value.bucket.value} for a {record.bucket.value} record")
    answer = decide(value)
    flags = list((record.evidence or {}).get("flags", [])) + list(extra_flags)
    if record.bucket is CrspBucket.MERGER and answer.method is DlretMethod.ASSUMED_PAR:
        flags.append("merger_at_par")
    close = value.last_trade_close
    if (record.bucket in (CrspBucket.COMPLIANCE_FAILURE, CrspBucket.LIQUIDATION)
            and close is not None and close >= 5.0):
        flags.append("distress_at_normal_price")
    return EnrichedDelistRecord(
        ticker=record.ticker, cik=record.cik,
        observed_delist_date=record.observed_delist_date,
        crsp_code=record.crsp_code, bucket=record.bucket,
        confidence=record.confidence, reason=record.reason, evidence=record.evidence,
        exchange=value.exchange, last_trade_close=close,
        payout_per_share=value.payout_per_share, stock_ratio=value.stock_ratio,
        acquirer_price=value.acquirer_price, acquirer_ticker=acquirer_ticker,
        recovery_ratio=value.recovery_ratio, answer=answer,
        payout_source=payout_source, payout_confidence=value.payout_confidence,
        review_flags=tuple(dict.fromkeys(flags)),
        sec_id=record.sec_id, delist_date=record.delist_date,
    )


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


_ROW_EXTRAS = ("exchange", "last_trade_date", "last_trade_date_source", "successor_sec_id", "ticker_successor_sec_id",
               "acquirer_sec_id",
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
        "exchange": e.exchange.value, "ticker_successor_sec_id": None,
        "last_trade_close": e.last_trade_close, "payout_per_share": e.payout_per_share,
        "stock_ratio": e.stock_ratio, "acquirer_price": e.acquirer_price, "acquirer_ticker": e.acquirer_ticker,
        "recovery_ratio": e.recovery_ratio, "terminal_value": e.terminal_value,
        "dlret": e.answer.table_dlret,
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


class OverrideFileError(ValueError):
    """A `--last-trade-closes` / `--merger-terms` / `--recoveries` file that cannot
    be trusted (a missing column, a value that is not a number, an incomplete
    stock leg, a value with no `sec_id`, a key given twice), or a row of one that
    matches no delisting of the run. The message is one line naming the file and
    line."""


class OverrideRows(dict):
    """One override file's values by key -- `sec_id` (every delisting of the
    security) or `(sec_id, delist_date)` (one delisting) -- remembering the file
    and the line each key came from, so a row can be named when it matches no
    delisting. Otherwise a plain dict."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = str(path)
        self.lines: dict[str | tuple[str, str], int] = {}


def override_row_name(overrides: Mapping, key: str | tuple[str, str]) -> str:
    """`key` as its override row: `<file> line <n>: <sec_id> [<delist_date>]` for
    a loaded file (`OverrideRows`), the bare key for any other map."""
    text = " ".join(key) if isinstance(key, tuple) else key
    if isinstance(overrides, OverrideRows) and key in overrides.lines:
        return f"{overrides.path} line {overrides.lines[key]}: {text}"
    return text


def _number(cells: Mapping[str, str], col: str, where: str) -> float | None:
    text = cells.get(col, "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise OverrideFileError(f"{where}: {col} {text!r} is not a number") from None


def _read_overrides(path: str | Path, required: tuple[str, ...],
                    value_of: Callable[[Mapping[str, str], str], Any]) -> OverrideRows:
    """Every row of the override CSV at `path` whose `value_of(cells, where)` is
    not None, keyed by `sec_id` or `(sec_id, delist_date)`. A blank row is
    skipped; anything that cannot be read as intended raises OverrideFileError."""
    out = OverrideRows(path)
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise OverrideFileError(f"{path} line 1: missing required column(s) {missing}; "
                                    f"found {reader.fieldnames}")
        for row in reader:
            where = f"{path} line {reader.line_num}"
            cells = {k: (v or "").strip() for k, v in row.items() if isinstance(k, str)}
            sid, day = cells.get("sec_id", ""), cells.get("delist_date", "")
            if not sid:
                if any(cells.values()):
                    raise OverrideFileError(f"{where}: no sec_id")
                continue
            value = value_of(cells, where)
            if value is None:
                continue
            key = (sid, day) if day else sid
            if key in out:
                raise OverrideFileError(f"{where}: {override_row_name({}, key)} repeats line {out.lines[key]}")
            out[key], out.lines[key] = value, reader.line_num
    return out


def load_float_overrides(path: str | Path, value_col: str) -> OverrideRows:
    """`--last-trade-closes` / `--recoveries`: `sec_id,<value_col>[,delist_date]`.
    A row with a blank value is skipped."""
    return _read_overrides(path, ("sec_id", value_col), lambda cells, where: _number(cells, value_col, where))


def _merger_terms(cells: Mapping[str, str], where: str) -> dict:
    terms: dict = {}
    for k in ("cash_per_share", "stock_ratio", "acquirer_price"):
        v = _number(cells, k, where)
        if v is not None:
            terms[k] = v
    if cells.get("acquirer_ticker"):
        terms["acquirer_ticker"] = cells["acquirer_ticker"]
    if ("stock_ratio" in terms) != ("acquirer_price" in terms):
        raise OverrideFileError(f"{where}: incomplete stock leg -- stock_ratio and acquirer_price must both be "
                                "present or both absent")
    return terms


def load_merger_terms_overrides(path: str | Path) -> OverrideRows:
    """`--merger-terms`: `sec_id,cash_per_share,stock_ratio,acquirer_price,
    acquirer_ticker[,delist_date]`; blank cells are left out of a row's terms."""
    return _read_overrides(path, ("sec_id",), _merger_terms)


def unmatched_override_keys(overrides: Mapping, delistings: Iterable[tuple[str, str]]) -> list:
    delistings = list(delistings)
    sids = {s for s, _ in delistings}
    pairs = set(delistings)
    return [k for k in overrides if (k not in pairs if isinstance(k, tuple) else k not in sids)]

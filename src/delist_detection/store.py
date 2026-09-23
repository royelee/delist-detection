"""CSV storage for the output tables.

Every table has one schema here: its column order and its key. All writes go
through `write_table`, which formats cells the same way everywhere, sorts rows
by key, and replaces the file only when the whole write succeeds. A later move
to DuckDB changes only this module.
"""
from __future__ import annotations

import csv
import math
import os
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...]


DELISTINGS_COLUMNS: tuple[str, ...] = (
    "sec_id", "delist_date", "ticker", "cik", "bucket", "crsp_code", "confidence", "reason",
    "exchange", "last_trade_date", "last_trade_close", "successor_sec_id", "acquirer_sec_id",
    "acquirer_ticker", "payout_per_share", "stock_ratio", "acquirer_price", "recovery_ratio",
    "terminal_value", "dlret", "dlret_method", "dlret_confidence", "payout_source",
    "delist_filing_form", "delist_filing_date", "delist_filing_accession", "anchor_8k_items",
    "dereg_form", "resolved_name", "resolution_source", "last_trade_date_source",
    "raw_payout_per_share", "raw_payout_source", "raw_payout_confidence", "review_flags",
)

TABLES: dict[str, TableSpec] = {t.name: t for t in (
    TableSpec("securities",
              ("sec_id", "issuer_cik", "share_class", "name", "security_type", "observed", "figi_source"),
              ("sec_id",)),
    TableSpec("ticker_history",
              ("sec_id", "ticker", "exchange", "valid_from", "valid_to", "source"),
              ("sec_id", "valid_from", "ticker")),
    TableSpec("cusip_history",
              ("sec_id", "cusip", "valid_from", "valid_to", "source"),
              ("sec_id", "valid_from", "cusip")),
    TableSpec("delistings", DELISTINGS_COLUMNS, ("sec_id", "delist_date")),
    TableSpec("payouts",
              ("sec_id", "delist_date", "ticker", "payout_per_share", "confidence", "source", "accession"),
              ("sec_id", "delist_date")),
    TableSpec("review",
              ("sec_id", "delist_date", "ticker", "cik", "bucket", "dlret", "review_flags", "reason",
               "anchor_8k", "last_seen"),
              ("sec_id", "delist_date", "ticker", "review_flags")),
)}


def format_cell(v: object) -> str:
    """The one cell format every table uses: empty for None/NaN, true/false for
    bools, six decimals for floats, ISO for dates, `;`-joined for sequences."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return "" if math.isnan(v) else f"{v:.6f}"
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return ";".join(format_cell(x) for x in v)
    return str(v)


@contextmanager
def replace_on_success(path: str | Path):
    """Yield a temp path beside `path`; `path` is replaced only when the block
    finishes, so an abort never leaves a partial file over the last complete one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        yield tmp
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def table_path(out_dir: str | Path, name: str) -> Path:
    return Path(out_dir) / f"{name}.csv"


def write_table(name: str, rows: Iterable[Mapping[str, object]], path: str | Path) -> int:
    """Write `rows` as table `name`; returns the row count. Missing columns are blank;
    an unknown column raises ValueError before anything is written. Rows are
    formatted before the file is opened, so a failing iterator leaves the old file."""
    spec = TABLES[name]
    formatted: list[dict[str, str]] = []
    for r in rows:
        extra = set(r) - set(spec.columns)
        if extra:
            raise ValueError(f"{name}: unknown column(s) {sorted(extra)}")
        formatted.append({c: format_cell(r.get(c)) for c in spec.columns})
    formatted.sort(key=lambda r: tuple(r[k] for k in spec.key) + tuple(r[c] for c in spec.columns))
    with replace_on_success(path) as tmp, tmp.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(spec.columns), lineterminator="\n")
        w.writeheader()
        w.writerows(formatted)
    return len(formatted)


def read_table(name: str, path: str | Path) -> list[dict[str, str]]:
    spec = TABLES[name]
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != spec.columns:
            raise ValueError(f"{path}: columns {reader.fieldnames} do not match table {name!r}")
        return list(reader)

"""CSV storage for the output tables.

Every table has one schema here: its column order and its key. All writes go
through `write_table`/`write_tables`, which format cells the same way
everywhere, sort rows by key (or keep the given order, for a table whose spec
has `sort=False`: review.csv comes pre-ordered by `review_triage`), and replace
the file only when the whole write succeeds. A later move to DuckDB changes
only this module.
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
    sort: bool = True          # False: rows are written in the order given


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
              ("severity", "sec_id", "delist_date", "ticker", "cik", "bucket", "dlret", "review_flags", "reason",
               "anchor_8k", "last_seen"),
              ("sec_id", "delist_date", "ticker", "review_flags"), sort=False),
    TableSpec("review_summary",
              ("severity", "flag", "rows", "in_review", "accepted", "description", "action", "examples"),
              ("flag",), sort=False),
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


def _sort(spec: TableSpec, rows: list[dict[str, str]]) -> None:
    """Sort formatted `rows` in place by key, then every column -- unless the
    table keeps the order it was given."""
    if spec.sort:
        rows.sort(key=lambda r: tuple(r[k] for k in spec.key) + tuple(r[c] for c in spec.columns))


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
    _sort(spec, formatted)
    with replace_on_success(path) as tmp, tmp.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(spec.columns), lineterminator="\n")
        w.writeheader()
        w.writerows(formatted)
    return len(formatted)


def write_tables(out_dir: str | Path, tables: Mapping[str, Iterable[Mapping[str, object]]]) -> dict[str, int]:
    """Write every table in `tables` atomically as one group.

    Every table's rows are formatted and validated first — an unknown column
    or a failing iterator raises before any file is touched. Each table is
    then written to its own temp file, and only once every temp file has
    been written successfully are they all renamed into place. So a later
    table's formatting or write failure never leaves an earlier table's new
    file sitting over the previous complete one; on any failure every
    previous file is left untouched and every temp file is cleaned up.

    Returns `{name: row_count}`.
    """
    formatted: dict[str, tuple] = {}
    for name, rows in tables.items():
        spec = TABLES[name]
        rows_fmt: list[dict[str, str]] = []
        for r in rows:
            extra = set(r) - set(spec.columns)
            if extra:
                raise ValueError(f"{name}: unknown column(s) {sorted(extra)}")
            rows_fmt.append({c: format_cell(r.get(c)) for c in spec.columns})
        _sort(spec, rows_fmt)
        formatted[name] = (spec, rows_fmt)

    paths = {name: Path(table_path(out_dir, name)) for name in tables}
    tmp_paths: dict[str, Path] = {}
    counts: dict[str, int] = {}
    try:
        for name, (spec, rows_fmt) in formatted.items():
            path = paths[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.tmp")
            # Registered before opening: a failure while writing THIS table's
            # temp file must still get it cleaned up in `finally` below, not
            # leak it.
            tmp_paths[name] = tmp
            with tmp.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(spec.columns), lineterminator="\n")
                w.writeheader()
                w.writerows(rows_fmt)
            counts[name] = len(rows_fmt)
        for name, tmp in tmp_paths.items():
            os.replace(tmp, paths[name])
    finally:
        for tmp in tmp_paths.values():
            tmp.unlink(missing_ok=True)
    return counts


def read_table(name: str, path: str | Path) -> list[dict[str, str]]:
    spec = TABLES[name]
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != spec.columns:
            raise ValueError(f"{path}: columns {reader.fieldnames} do not match table {name!r}")
        return list(reader)

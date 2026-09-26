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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NamedTuple

from .atomic_io import replace_all_on_success


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...]
    sort: bool = True          # False: rows are written in the order given


class DelistingKey(NamedTuple):
    """One delisting, as delistings.csv keys it (`TABLES["delistings"].key`). A
    plain tuple of the same two values is the same key (an override file's
    `(sec_id, delist_date)` rows). Here, beside the table keys, so both layers
    can use it: the finder keys each delisting by it, the handling layer each
    per-delisting input."""
    sec_id: str
    delist_date: str | None


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


def table_path(out_dir: str | Path, name: str) -> Path:
    return Path(out_dir) / f"{name}.csv"


def _sort(spec: TableSpec, rows: list[dict[str, str]]) -> None:
    """Sort formatted `rows` in place by key, then every column -- unless the
    table keeps the order it was given."""
    if spec.sort:
        rows.sort(key=lambda r: tuple(r[k] for k in spec.key) + tuple(r[c] for c in spec.columns))


def _formatted(name: str, rows: Iterable[Mapping[str, object]]) -> list[dict[str, str]]:
    """`rows` as table `name`'s formatted, sorted cells. Missing columns are blank;
    an unknown column raises ValueError."""
    spec = TABLES[name]
    out: list[dict[str, str]] = []
    for r in rows:
        extra = set(r) - set(spec.columns)
        if extra:
            raise ValueError(f"{name}: unknown column(s) {sorted(extra)}")
        out.append({c: format_cell(r.get(c)) for c in spec.columns})
    _sort(spec, out)
    return out


def _write_all(tables: Sequence[tuple[str, Iterable[Mapping[str, object]], str | Path]]) -> dict[str, int]:
    """Write each `(name, rows, path)` as one group: every table is formatted and
    validated first, so an unknown column or a failing iterator raises before
    any file is touched; then each goes to its own temp file, and only once every
    temp file is written are they all renamed into place (`replace_all_on_success`).
    Returns `{name: row_count}`."""
    formatted = [(name, _formatted(name, rows)) for name, rows, _ in tables]
    counts: dict[str, int] = {}
    with replace_all_on_success([path for _, _, path in tables]) as tmps:
        for (name, rows_fmt), tmp in zip(formatted, tmps):
            with tmp.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(TABLES[name].columns), lineterminator="\n")
                w.writeheader()
                w.writerows(rows_fmt)
            counts[name] = len(rows_fmt)
    return counts


def write_table(name: str, rows: Iterable[Mapping[str, object]], path: str | Path) -> int:
    """Write `rows` as table `name` at `path` (`_write_all`); returns the row count.
    Missing columns are blank; an unknown column or a failing iterator raises
    before the old file is touched."""
    return _write_all([(name, rows, path)])[name]


def write_tables(out_dir: str | Path, tables: Mapping[str, Iterable[Mapping[str, object]]]) -> dict[str, int]:
    """Write every table in `tables` under `out_dir` atomically as one group
    (`_write_all`): a later table's formatting or write failure never leaves an
    earlier table's new file sitting over the previous complete one; on any
    failure every previous file is left untouched and every temp file is
    cleaned up.

    Returns `{name: row_count}`.
    """
    return _write_all([(name, rows, table_path(out_dir, name)) for name, rows in tables.items()])


def read_table(name: str, path: str | Path) -> list[dict[str, str]]:
    spec = TABLES[name]
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != spec.columns:
            raise ValueError(f"{path}: columns {reader.fieldnames} do not match table {name!r}")
        return list(reader)


@dataclass(frozen=True)
class FrameTypes:
    """How `read_frame` types a table's columns: identifiers kept as strings,
    dates parsed (a blank or bad one is NaT), numbers parsed (blank or bad is
    NaN); every other column as pandas infers it."""
    strings: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()


FRAME_TYPES: dict[str, FrameTypes] = {
    "delistings": FrameTypes(
        strings=("sec_id", "ticker", "successor_sec_id", "acquirer_sec_id", "bucket"),
        dates=("delist_date", "last_trade_date"),
        numbers=("crsp_code", "last_trade_close", "payout_per_share", "terminal_value", "recovery_ratio", "cik"),
    ),
}


def read_frame(name: str, path: str | Path):
    """Table `name` at `path` as a pandas DataFrame, typed by `FRAME_TYPES`
    (the handling layer's view of delistings.csv). Raises ValueError when the
    file's columns are not the table's, as `read_table` does."""
    import pandas as pd  # noqa: PLC0415 -- only the pandas callers pay for the import

    types = FRAME_TYPES.get(name, FrameTypes())
    df = pd.read_csv(path, dtype={c: str for c in types.strings})
    if tuple(df.columns) != TABLES[name].columns:
        raise ValueError(f"{path}: columns {list(df.columns)} do not match table {name!r}")
    for c in types.dates:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in types.numbers:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

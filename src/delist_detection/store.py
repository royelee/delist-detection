"""CSV storage for the output tables.

Every table has one schema here: its column order and its key. All writes go
through `write_tables`, which formats cells the same way
everywhere, sorts rows by key (or keeps the given order, for a table whose spec
has `sort=False`: review.csv comes pre-ordered by `review_triage`), and replaces
the files only once every table's temp file is written (then one rename at a
time; see `write_tables`). A later move to DuckDB changes
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
    file: str = ""             # the path under the output folder; "" means "<name>.csv"


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
    "exchange", "last_trade_date", "last_trade_close", "successor_sec_id", "ticker_successor_sec_id",
    "acquirer_sec_id",
    "acquirer_ticker", "payout_per_share", "stock_ratio", "acquirer_price", "recovery_ratio",
    "terminal_value", "dlret", "dlret_method", "dlret_confidence", "payout_source",
    "delist_filing_form", "delist_filing_date", "delist_filing_accession", "anchor_8k_items",
    "dereg_form", "resolved_name", "resolution_source", "last_trade_date_source",
    "raw_payout_per_share", "raw_payout_source", "raw_payout_confidence", "review_flags",
)

# uncertain.csv (verdict.Verdicts.uncertain_rows): one row per uncertain seed,
# security or ending. `kind` is seed | security | ending; `reason` holds
# `;`-joined `code` or `code:detail` items; `candidates` the other sec_ids involved.
UNCERTAIN_COLUMNS: tuple[str, ...] = ("kind", "ticker", "sec_id", "date", "reason", "candidates")

# The contract (spec: Delist Library Reset, "The contract"; contract.py), written
# under contract/ beside the tables above for one release (decision 6).
CONTRACT_SCHEMA_VERSION = 3       # 2: contract/delistings.csv gains the payout-rule columns; 3: payout_legs.csv
SECURITY_HISTORY_COLUMNS: tuple[str, ...] = (
    "sec_id", "issuer_id", "start_date", "end_date", "ticker", "security_name", "share_class")
CONTRACT_DELISTINGS_COLUMNS: tuple[str, ...] = (
    "sec_id", "last_trade_date", "exit_kind", "drop_reason", "continuation", "successor_sec_id",
    "ticker_successor_sec_id", "dlret", "dlret_fill", "terminal_value", "verdict",
    # the payout rule (payout_rule.py): what one share turned into, for the caller to price
    "value_rule", "cash_per_share", "cash_currency", "stock_ratio", "price_sec_id", "price_ticker", "price_date",
    "recovery_ratio", "terms_source", "terms_gate", "value_formula")
SEEDS_COLUMNS: tuple[str, ...] = ("ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id", "sec_id", "verdict")
PRICE_REQUEST_COLUMNS: tuple[str, ...] = ("sec_id", "last_trade_date", "kind", "lookup_sec_id", "lookup_ticker", "date")
ID_CHANGES_COLUMNS: tuple[str, ...] = ("old_sec_id", "new_sec_id", "changed_on", "issuer_cik", "share_class")
# ruling R3 (schema 3): each security of a basket per share (payout_rule.basket_legs)
PAYOUT_LEGS_COLUMNS: tuple[str, ...] = ("sec_id", "leg", "ratio", "share_class", "price_sec_id", "price_ticker",
                                        "price_date")
CONTRACT_TABLES = ("security_history", "contract_delistings", "seeds", "price_requests", "id_changes", "payout_legs")

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
    TableSpec("observation_map",
              ("ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id", "era", "sec_id", "issuer_cik",
               "history_ticker", "in_ticker_history", "status"),
              ("ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id")),
    TableSpec("uncertain", UNCERTAIN_COLUMNS, ("kind", "sec_id", "date", "ticker")),
    TableSpec("security_history", SECURITY_HISTORY_COLUMNS, ("sec_id", "start_date", "ticker"),
              file="contract/security_history.csv"),
    TableSpec("contract_delistings", CONTRACT_DELISTINGS_COLUMNS, ("sec_id",), file="contract/delistings.csv"),
    TableSpec("seeds", SEEDS_COLUMNS, ("ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id"),
              file="contract/seeds.csv"),
    TableSpec("price_requests", PRICE_REQUEST_COLUMNS, ("sec_id", "kind", "date", "lookup_ticker"),
              file="contract/price_requests.csv"),
    TableSpec("id_changes", ID_CHANGES_COLUMNS, ("old_sec_id",), file="contract/id_changes.csv"),
    TableSpec("payout_legs", PAYOUT_LEGS_COLUMNS, ("sec_id", "leg"), file="contract/payout_legs.csv"),
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
    """Where table `name` lives under `out_dir`: its spec's `file`, else `<name>.csv`."""
    spec = TABLES.get(name)
    return Path(out_dir) / (spec.file if spec is not None and spec.file else f"{name}.csv")


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


def formatted(name: str, rows: Iterable[Mapping[str, object]]) -> list[dict[str, str]]:
    """`rows` as table `name` is written: every cell formatted, missing columns
    blank, sorted by key -- the rows `read_table` would read back. An unknown
    column raises ValueError."""
    return _formatted(name, rows)


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


def write_tables(out_dir: str | Path, tables: Mapping[str, Iterable[Mapping[str, object]]]) -> dict[str, int]:
    """Write every table in `tables` under `out_dir` as one group (`_write_all`):
    every table is formatted and written to its own temp file first, so a
    formatting or write failure in any of them leaves every previous file
    untouched and every temp file cleaned up. Only then are the temp files
    renamed into place, one at a time: a process killed between two renames
    leaves some tables new and the rest old (each one whole).

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


# How the handling layer types delistings.csv's columns as a frame: identifiers
# kept as strings, dates parsed (a blank or bad one is NaT), numbers parsed
# (blank or bad is NaN); every other column as pandas infers it.
DELISTINGS_FRAME_STRINGS = ("sec_id", "ticker", "successor_sec_id", "ticker_successor_sec_id", "acquirer_sec_id",
                            "bucket")
DELISTINGS_FRAME_DATES = ("delist_date", "last_trade_date")
DELISTINGS_FRAME_NUMBERS = ("crsp_code", "last_trade_close", "payout_per_share", "terminal_value", "recovery_ratio",
                            "cik")


def read_delistings_frame(path: str | Path):
    """delistings.csv at `path` as a pandas DataFrame, typed as above (the
    handling layer's view of it). Raises ValueError when the file's columns are
    not delistings.csv's, as `read_table` does."""
    import pandas as pd  # noqa: PLC0415 -- only the pandas callers pay for the import

    df = pd.read_csv(path, dtype={c: str for c in DELISTINGS_FRAME_STRINGS})
    if tuple(df.columns) != TABLES["delistings"].columns:
        raise ValueError(f"{path}: columns {list(df.columns)} do not match table 'delistings'")
    for c in DELISTINGS_FRAME_DATES:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in DELISTINGS_FRAME_NUMBERS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

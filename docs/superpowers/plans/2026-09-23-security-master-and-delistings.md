# Security Master and Delisting Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `delist_detection` so that, from caller observations `(ticker, as_of, …)`, it builds a FIGI-keyed security master (`securities`, `ticker_history`, `cusip_history`) and a `delistings` table found from EDGAR Form 25s and priced from SEC data, written as CSVs in `output/`.

**Architecture:** New pure modules (store, trading calendar, observations, Form 25 parsing, last-trade rules, FIGI acceptance, listing status) plus thin cached clients (OpenFIGI, SEC fails-to-deliver, SEC MIDAS, Nasdaq halts) feed a `pipeline.py` orchestrator. The existing classifier rule engine is reused unchanged through a new `classify_event` entry point that takes a known CIK and Form 25. The DLRET math (`dlret.py`, `payout_gate.py`) is reused, re-keyed from `(ticker, observed_delist_date)` to `(sec_id, delist_date)`.

**Tech Stack:** Python ≥ 3.10, requests, pandas, stdlib (`zipfile`, `xml.etree`, `csv`, `gzip`), pytest. No new dependencies.

**Spec:** [`docs/superpowers/feature-spec.md`](../feature-spec.md) (the PRD). Decision log with evidence: [`docs/superpowers/specs/2026-09-22-security-master-and-delistings-design.md`](../specs/2026-09-22-security-master-and-delistings-design.md). Glossary: [`CONTEXT.md`](../../../CONTEXT.md). Research: [`docs/research/last-trade-date-sources.md`](../../research/last-trade-date-sources.md).

## Global Constraints

- Python ≥ 3.10; no new third-party dependencies (`pyproject.toml` stays `requests, pandas, openai, python-dotenv`).
- Run tests with `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest` from the worktree root. Baseline: 433 passed.
- Run scripts with `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/<name>.py` (the editable install points at the main checkout, not this worktree).
- Tests are fully offline: fakes and committed fixtures only. Never add network to the test path.
- SEC fair access: ≤ 8 requests/s, descriptive User-Agent from `EDGAR_USER_AGENT` via `edgar.resolve_user_agent()`; a SEC 403/429 raises `EdgarBlocked`; the CLI exits 2.
- OpenFIGI key: env var `OPEN_FIGI_API_KEY` (environment first, then repo `.env`), sent as header `X-OPENFIGI-APIKEY`; 401/403 raises `OpenFigiBlocked`; the CLI exits 2.
- Outputs go to `output/`: `securities.csv`, `ticker_history.csv`, `cusip_history.csv`, `delistings.csv`, `payouts.csv`, `review.csv`. One CSV per table, fixed column order, ISO dates, empty cell for NULL, rows sorted by key, written atomically.
- Date ranges are inclusive; an empty `valid_to` means still open.
- `sec_id` is the US composite FIGI, or placeholder `CIK<cik>-<CLASS>` when none is confirmed.
- Do not change `CrspBucket`, `DLST_CODE_TO_BUCKET`, the classifier rule order, `dlret.py` formulas or the payout gate rules.
- No Tiingo, no Alpha Vantage: `av_listing.py`, `raw_tiingo.py`, `AV_LISTING_CSV`, `AV_ACTIVE_CSV`, `RAW_TIINGO_DIR`, `--raw-tiingo-dir`, `--names`, `--cik-map` are removed.
- Commit after every task with a message ending in:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg
  ```

## Review Focus

1. **Recycled ticker in observations** (same ticker, two companies, years apart, e.g. MON = Monsanto to 2018 then Monument Circle 2021): must become two eras and two securities, never one. Test in Task 3.
2. **Share-class punctuation across sources** (`BRK.B`, `BRK/B`, `BRK-B`, OpenFIGI `BF/A`, FTD `BF/A`): all normalize to `BF-A` style and match. Tests in Tasks 3, 5, 9.
3. **Security still listed with an old secondary Form 25** (Apache's 2020 Chicago Stock Exchange withdrawal): no delisting row and no review row. Test in Task 13 and Task 15.
4. **Delisting with no fails-to-deliver row near the last trade and no override**: `dlret` blank with `needs_last_trade`, a review row, no crash. Test in Task 17.
5. **SEC or OpenFIGI refusal mid-run**: exit code 2 and previously written output files untouched. Test in Task 17.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/delist_detection/store.py` | new | Table schemas, CSV cell formatting, atomic write/read |
| `src/delist_detection/trading_calendar.py` | new | NYSE trading days (holidays, special closures) |
| `src/delist_detection/observations.py` | new | Observation input, ticker normalization, ticker eras, name/pin lookups, converters |
| `src/delist_detection/sec_http.py` | new | Throttled, cached SEC downloads (zip files, index pages) |
| `src/delist_detection/ftd.py` | new | SEC fails-to-deliver: file index, parsing, symbol/CUSIP index, closes |
| `src/delist_detection/midas.py` | new | SEC MIDAS per-security volume: last exchange-trade day |
| `src/delist_detection/nasdaq_halts.py` | new | Nasdaq trade-halt feed: code-D halts |
| `src/delist_detection/openfigi.py` | new | Cached, rate-limited OpenFIGI client |
| `src/delist_detection/figi_resolution.py` | new | Pure FIGI candidate filtering, acceptance, share class, placeholders |
| `src/delist_detection/form25.py` | new | Form 25 parsing, class kinds, security matching, notice dates, exchange labels |
| `src/delist_detection/last_trade.py` | new | 8-K Item 3.01 date phrases and the last-trade decision |
| `src/delist_detection/listing_status.py` | new | 10-K cover exchanges, secondary-withdrawal rule, listed-today check |
| `src/delist_detection/security_master.py` | new | Eras → securities (FIGI), CUSIP and ticker ranges |
| `src/delist_detection/delistings.py` | new | Per-security delisting finder (Form 25 → classify → last trade) |
| `src/delist_detection/pipeline.py` | new | End-to-end run producing all tables |
| `src/delist_detection/edgar.py` | modify | Add `fetch_filing_raw` |
| `src/delist_detection/classifier.py` | modify | `DelistRecord` fields; `_classify_resolved`; `classify_event` |
| `src/delist_detection/reconstruction.py` | modify | Re-key to `(sec_id, delist_date)`; delisting rows; override loaders |
| `src/delist_detection/handling.py`, `qlib_adapter.py` | modify | Join on `sec_id`; values from delisting rows |
| `src/delist_detection/names.py` | modify | Remove `MemberNames` (observations replace it) |
| `src/delist_detection/av_listing.py`, `raw_tiingo.py` | delete | Replaced |
| `scripts/classify_universe.py` | rewrite | CLI over `pipeline.run` |
| `scripts/observations_from_snapshots.py`, `scripts/observations_from_instruments.py` | new | Input converters |
| `scripts/compute_corrected_returns.py`, `scripts/verify_against_web.py`, `scripts/build_golden_fixtures.py` | modify | New inputs, no AV |
| `README.md`, `CLAUDE.md`, `docs/data-flow.md` | modify | Document the new model |

---
### Task 1: Table store

**Files:**
- Create: `src/delist_detection/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TableSpec(name: str, columns: tuple[str, ...], key: tuple[str, ...])`
  - `TABLES: dict[str, TableSpec]` with keys `"securities"`, `"ticker_history"`, `"cusip_history"`, `"delistings"`, `"payouts"`, `"review"`
  - `DELISTINGS_COLUMNS: tuple[str, ...]`
  - `format_cell(v: object) -> str`
  - `replace_on_success(path) -> ContextManager[Path]`
  - `table_path(out_dir, name) -> Path`
  - `write_table(name: str, rows: Iterable[Mapping[str, object]], path) -> int`
  - `read_table(name: str, path) -> list[dict[str, str]]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store.py
from datetime import date

import pytest

from delist_detection.store import (
    DELISTINGS_COLUMNS, TABLES, format_cell, read_table, replace_on_success, table_path, write_table,
)


def test_format_cell_rules():
    assert format_cell(None) == ""
    assert format_cell(float("nan")) == ""
    assert format_cell(True) == "true"
    assert format_cell(False) == "false"
    assert format_cell(1.5) == "1.500000"
    assert format_cell(date(2018, 11, 28)) == "2018-11-28"
    assert format_cell(("a", "b")) == "a;b"
    assert format_cell(1122304) == "1122304"


def test_all_tables_have_keys_inside_columns():
    for spec in TABLES.values():
        assert set(spec.key) <= set(spec.columns), spec.name
    assert TABLES["delistings"].columns == DELISTINGS_COLUMNS
    assert TABLES["delistings"].key == ("sec_id", "delist_date")


def test_write_sorts_by_key_and_round_trips(tmp_path):
    p = table_path(tmp_path, "securities")
    rows = [
        {"sec_id": "BBG2", "issuer_cik": 2, "share_class": "COMMON", "name": "B", "security_type": "Common Stock",
         "observed": True, "figi_source": "ticker"},
        {"sec_id": "BBG1", "issuer_cik": 1, "share_class": "COMMON", "name": "A", "security_type": "Common Stock",
         "observed": False, "figi_source": "cusip"},
    ]
    assert write_table("securities", rows, p) == 2
    back = read_table("securities", p)
    assert [r["sec_id"] for r in back] == ["BBG1", "BBG2"]
    assert back[0]["observed"] == "false"
    assert p.read_text().splitlines()[0] == ",".join(TABLES["securities"].columns)


def test_missing_columns_are_blank_and_unknown_columns_raise(tmp_path):
    p = table_path(tmp_path, "cusip_history")
    write_table("cusip_history", [{"sec_id": "BBG1", "cusip": "00817Y108", "valid_from": "2004-01-02"}], p)
    assert read_table("cusip_history", p)[0]["valid_to"] == ""
    with pytest.raises(ValueError, match="unknown column"):
        write_table("cusip_history", [{"sec_id": "x", "bogus": 1}], p)


def test_failed_write_keeps_previous_file(tmp_path):
    p = table_path(tmp_path, "securities")
    write_table("securities", [{"sec_id": "BBG1"}], p)
    before = p.read_text()

    def boom():
        yield {"sec_id": "BBG9"}
        raise RuntimeError("mid-run failure")

    with pytest.raises(RuntimeError):
        write_table("securities", boom(), p)
    assert p.read_text() == before
    assert not list(tmp_path.glob(".*.tmp"))


def test_read_table_rejects_wrong_header(tmp_path):
    p = tmp_path / "securities.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="do not match"):
        read_table("securities", p)


def test_replace_on_success_removes_temp_on_error(tmp_path):
    target = tmp_path / "x.csv"
    with pytest.raises(RuntimeError):
        with replace_on_success(target) as tmp:
            tmp.write_text("partial")
            raise RuntimeError
    assert not target.exists()
    assert not (tmp_path / ".x.csv.tmp").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'delist_detection.store'`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/store.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_store.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/store.py tests/test_store.py
git commit -m "feat(store): one schema and atomic CSV writer per output table"
```
(append the two attribution lines from Global Constraints to every commit message)

---

### Task 2: NYSE trading calendar

**Files:**
- Create: `src/delist_detection/trading_calendar.py`
- Test: `tests/test_trading_calendar.py`

**Interfaces:**
- Produces:
  - `nyse_holidays(year: int) -> frozenset[date]`
  - `is_trading_day(d: date) -> bool`
  - `previous_trading_day(d: date) -> date` (strictly before `d`)
  - `next_trading_day(d: date) -> date` (strictly after `d`)
  - `add_trading_days(d: date, n: int) -> date` (`n` may be negative; `n == 0` returns `d`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_trading_calendar.py
from datetime import date

from delist_detection.trading_calendar import (
    add_trading_days, is_trading_day, next_trading_day, nyse_holidays, previous_trading_day,
)


def test_known_closures():
    assert date(2015, 4, 3) in nyse_holidays(2015)          # Good Friday
    assert date(2022, 6, 20) in nyse_holidays(2022)         # Juneteenth observed (Sun -> Mon)
    assert date(2021, 12, 31) not in nyse_holidays(2021)    # NY Day on Saturday is not moved back
    assert date(2025, 1, 9) in nyse_holidays(2025)          # national day of mourning (Carter)
    assert date(2012, 10, 29) in nyse_holidays(2012)        # Hurricane Sandy
    assert date(2020, 7, 3) in nyse_holidays(2020)          # July 4 on Saturday -> Friday
    assert date(1997, 1, 20) not in nyse_holidays(1997)     # MLK day only from 1998


def test_is_trading_day():
    assert is_trading_day(date(2018, 11, 28))
    assert not is_trading_day(date(2018, 11, 24))           # Saturday
    assert not is_trading_day(date(2018, 11, 22))           # Thanksgiving


def test_previous_and_next():
    assert previous_trading_day(date(2018, 11, 29)) == date(2018, 11, 28)
    assert previous_trading_day(date(2009, 1, 2)) == date(2008, 12, 31)     # MER
    assert previous_trading_day(date(2024, 11, 18)) == date(2024, 11, 15)   # SAVE (Monday)
    assert previous_trading_day(date(2015, 12, 28)) == date(2015, 12, 24)   # Altera
    assert next_trading_day(date(2018, 11, 28)) == date(2018, 11, 29)
    assert next_trading_day(date(2018, 11, 21)) == date(2018, 11, 23)       # skips Thanksgiving


def test_add_trading_days():
    assert add_trading_days(date(2018, 11, 28), 0) == date(2018, 11, 28)
    assert add_trading_days(date(2018, 11, 28), 2) == date(2018, 11, 30)
    assert add_trading_days(date(2018, 11, 26), -2) == date(2018, 11, 21)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_trading_calendar.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/trading_calendar.py
"""NYSE trading days: weekends, exchange holidays, and unscheduled closures.

Used to turn "suspended before the open on D" into the last trading day and to
line up SEC fails-to-deliver rows (a row dated D carries the prior day's close).
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# Unscheduled full-day closures since 1990.
_SPECIAL_CLOSURES = frozenset({
    date(1994, 4, 27),                                            # Nixon funeral
    date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),
    date(2004, 6, 11),                                            # Reagan funeral
    date(2007, 1, 2),                                             # Ford funeral
    date(2012, 10, 29), date(2012, 10, 30),                       # Hurricane Sandy
    date(2018, 12, 5),                                            # G.H.W. Bush funeral
    date(2025, 1, 9),                                             # Carter funeral
})


def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def _nth_weekday(y: int, month: int, weekday: int, n: int) -> date:
    first = date(y, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(y: int, month: int, weekday: int) -> date:
    d = (date(y + 1, 1, 1) if month == 12 else date(y, month + 1, 1)) - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> frozenset[date]:
    h: set[date] = set()
    new_year = date(year, 1, 1)
    if new_year.weekday() == 6:
        h.add(new_year + timedelta(days=1))
    elif new_year.weekday() != 5:          # a Saturday New Year's Day is not observed
        h.add(new_year)
    if year >= 1998:
        h.add(_nth_weekday(year, 1, 0, 3))  # Martin Luther King Jr. Day
    h.add(_nth_weekday(year, 2, 0, 3))      # Washington's Birthday
    h.add(_easter(year) - timedelta(days=2))  # Good Friday
    h.add(_last_weekday(year, 5, 0))        # Memorial Day
    if year >= 2022:
        h.add(_observed(date(year, 6, 19)))  # Juneteenth
    h.add(_observed(date(year, 7, 4)))
    h.add(_nth_weekday(year, 9, 0, 1))      # Labor Day
    h.add(_nth_weekday(year, 11, 3, 4))     # Thanksgiving
    h.add(_observed(date(year, 12, 25)))
    h |= {d for d in _SPECIAL_CLOSURES if d.year == year}
    return frozenset(h)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def add_trading_days(d: date, n: int) -> date:
    step = next_trading_day if n > 0 else previous_trading_day
    for _ in range(abs(n)):
        d = step(d)
    return d
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_trading_calendar.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/trading_calendar.py tests/test_trading_calendar.py
git commit -m "feat(calendar): NYSE trading days with holidays and closures"
```

---

### Task 3: Observations, ticker eras and input converters

**Files:**
- Create: `src/delist_detection/observations.py`
- Create: `scripts/observations_from_snapshots.py`
- Create: `scripts/observations_from_instruments.py`
- Test: `tests/test_observations.py`

**Interfaces:**
- Consumes: `names.names_agree(a: str, b: str) -> bool` (existing).
- Produces:
  - `normalize_ticker(raw: str) -> str` — upper-case; `.`, `/`, spaces → `-`; strips leading/trailing `-`.
  - `Observation(ticker: str, as_of: str, name: str | None = None, cusip: str | None = None, cik: int | None = None, sec_id: str | None = None)` (frozen)
  - `ObservationError(ValueError)`
  - `load_observations(path) -> list[Observation]`
  - `write_observations(obs: Iterable[Observation], path) -> int`
  - `TickerEra` dataclass: `ticker: str`, `first: str`, `last: str`, `observations: list[Observation]`; properties `names -> list[str]` (distinct, in date order), `name -> str | None` (latest), `cusips -> list[str]` (distinct, latest first), `cik_pin -> int | None`, `sec_id_pin -> str | None`, `key -> str` (`f"{ticker}@{first}"`)
  - `ERA_GAP_DAYS = 400`
  - `split_eras(obs: list[Observation]) -> list[TickerEra]` (one ticker, any order)
  - `ObservationIndex(observations)` with `.eras() -> list[TickerEra]`, `.era_for(ticker, day: str) -> TickerEra | None`, `.name_on(ticker, observed_date=None) -> str | None`, `.cik_pin_on(ticker, observed_date=None) -> int | None`
  - `observations_from_instruments(path) -> list[Observation]`
  - `observations_from_snapshots(folder, *, where: dict[str, str] | None = None, date_regex: str = DATE_IN_NAME) -> list[Observation]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_observations.py
import pytest

from delist_detection.observations import (
    Observation, ObservationError, ObservationIndex, load_observations, normalize_ticker,
    observations_from_instruments, observations_from_snapshots, split_eras, write_observations,
)


def test_normalize_ticker():
    assert normalize_ticker(" brk.b ") == "BRK-B"
    assert normalize_ticker("BF/A") == "BF-A"
    assert normalize_ticker("BRK B") == "BRK-B"
    assert normalize_ticker("AET") == "AET"


def test_load_validates_and_dedupes(tmp_path):
    p = tmp_path / "obs.csv"
    p.write_text(
        "ticker,as_of,name,cusip,cik,sec_id\n"
        "aet,2018-06-29,AETNA INC,00817y108,1122304,\n"
        "AET,2018-06-29,AETNA INC,00817Y108,1122304,\n"
        "BF.A,2018-06-29,BROWN FORMAN CORP CLASS A,,,\n"
    )
    obs = load_observations(p)
    assert obs == [
        Observation("AET", "2018-06-29", "AETNA INC", "00817Y108", 1122304, None),
        Observation("BF-A", "2018-06-29", "BROWN FORMAN CORP CLASS A", None, None, None),
    ]


def test_load_reports_bad_rows(tmp_path):
    p = tmp_path / "obs.csv"
    p.write_text("ticker,as_of\n,2018-01-01\nAET,2018-13-01\nAET,2018-01-02\n")
    with pytest.raises(ObservationError, match="line 2.*line 3"):
        load_observations(p)
    q = tmp_path / "noas.csv"
    q.write_text("ticker,name\nAET,x\n")
    with pytest.raises(ObservationError, match="as_of"):
        load_observations(q)


def test_recycled_ticker_splits_into_two_eras():
    obs = [
        Observation("MON", "2016-06-30", "MONSANTO CO"),
        Observation("MON", "2017-12-29", "MONSANTO CO"),
        Observation("MON", "2021-12-31", "MONUMENT CIRCLE ACQUISITION CORP"),
    ]
    eras = split_eras(obs)
    assert [(e.first, e.last, e.name) for e in eras] == [
        ("2016-06-30", "2017-12-29", "MONSANTO CO"),
        ("2021-12-31", "2021-12-31", "MONUMENT CIRCLE ACQUISITION CORP"),
    ]


def test_name_change_without_gap_splits_but_same_name_does_not():
    same = split_eras([Observation("X", "2020-06-30", "FOO INC"), Observation("X", "2020-12-31", "FOO INC")])
    assert len(same) == 1
    changed = split_eras([Observation("X", "2020-06-30", "FOREST OIL CORP"),
                          Observation("X", "2020-12-31", "FAST ACQUISITION CORP")])
    assert len(changed) == 2


def test_pin_change_splits():
    eras = split_eras([Observation("X", "2020-06-30", cik=1), Observation("X", "2020-12-31", cik=2)])
    assert [e.cik_pin for e in eras] == [1, 2]


def test_index_lookups():
    idx = ObservationIndex([
        Observation("ALTR", "2015-06-30", "ALTERA CORP"),
        Observation("ALTR", "2024-06-28", "ALTAIR ENGINEERING INC", cik=1701732),
    ])
    assert len(idx.eras()) == 2
    assert idx.name_on("ALTR", "2015-12-28") == "ALTERA CORP"
    assert idx.name_on("ALTR", "2025-03-26") == "ALTAIR ENGINEERING INC"
    assert idx.name_on("ALTR", "2010-01-01") == "ALTERA CORP"      # nearest after when none before
    assert idx.cik_pin_on("ALTR", "2025-03-26") == 1701732
    assert idx.cik_pin_on("ALTR", "2015-12-28") is None
    assert idx.era_for("ALTR", "2025-03-26").first == "2024-06-28"
    assert idx.name_on("ZZZZ") is None


def test_write_round_trip(tmp_path):
    obs = [Observation("B", "2020-01-02"), Observation("A", "2020-01-02", "A CO", "123456789", 7, "BBG1")]
    p = tmp_path / "o.csv"
    assert write_observations(obs, p) == 2
    assert load_observations(p) == sorted(obs, key=lambda o: (o.ticker, o.as_of))


def test_from_instruments(tmp_path):
    p = tmp_path / "all.txt"
    p.write_text("AABA\t2000-01-03\t2019-11-06\nBRK.B\t2000-01-03\t2026-05-22\n")
    obs = observations_from_instruments(p)
    assert [(o.ticker, o.as_of) for o in obs] == [
        ("AABA", "2000-01-03"), ("AABA", "2019-11-06"), ("BRK-B", "2000-01-03"), ("BRK-B", "2026-05-22")]


def test_from_snapshots(tmp_path):
    (tmp_path / "2018-06-29.csv").write_text(
        "ticker,name,asset_class\nAET,AETNA INC,Equity\nXTSLA,BLK CSH FND,Money Market\n")
    (tmp_path / "russell_20180102.csv").write_text("Ticker,Name\nAET,AETNA INC\n")
    (tmp_path / "2013-06-29.csv").write_text("ticker,name\n")          # header-only placeholder
    (tmp_path / "notes.csv").write_text("ticker,name\nZZZ,no date in name\n")
    obs = observations_from_snapshots(tmp_path, where={"asset_class": "Equity"})
    assert [(o.ticker, o.as_of, o.name) for o in obs] == [
        ("AET", "2018-01-02", "AETNA INC"), ("AET", "2018-06-29", "AETNA INC")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_observations.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/observations.py
"""Caller observations: "ticker T was seen trading on date D", with the name,
CUSIP and any identity pins the caller knows.

Observations are the library's only view of the caller's universe. A ticker's
observations are split into eras: runs that belong to one security. A new era
starts after a long gap, when the name stops agreeing, or when a pin changes,
because a recycled ticker (MON = Monsanto, later Monument Circle) must never be
merged into one security.
"""
from __future__ import annotations

import csv
import re
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .names import names_agree

ERA_GAP_DAYS = 400
DATE_IN_NAME = r"(\d{4}-\d{2}-\d{2}|\d{8})"
OBS_COLUMNS = ("ticker", "as_of", "name", "cusip", "cik", "sec_id")


def normalize_ticker(raw: str) -> str:
    return re.sub(r"[./\s]+", "-", (raw or "").strip().upper()).strip("-")


@dataclass(frozen=True)
class Observation:
    ticker: str
    as_of: str
    name: str | None = None
    cusip: str | None = None
    cik: int | None = None
    sec_id: str | None = None


class ObservationError(ValueError):
    pass


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _iso(s: str) -> str | None:
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def load_observations(path: str | Path) -> list[Observation]:
    out: dict[Observation, None] = {}
    bad: list[str] = []
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
        for need in ("ticker", "as_of"):
            if need not in cols:
                raise ObservationError(f"{path}: missing required column {need!r}; found {reader.fieldnames}")
        for lineno, row in enumerate(reader, start=2):
            get = lambda k: row.get(cols[k]) if k in cols else None
            ticker = normalize_ticker(get("ticker") or "")
            as_of = _iso(get("as_of") or "")
            cik_raw = _clean(get("cik"))
            if not ticker or as_of is None or (cik_raw is not None and not cik_raw.isdigit()):
                bad.append(f"line {lineno}")
                continue
            cusip = _clean(get("cusip"))
            out[Observation(
                ticker=ticker, as_of=as_of, name=_clean(get("name")),
                cusip=cusip.upper() if cusip else None,
                cik=int(cik_raw) if cik_raw else None, sec_id=_clean(get("sec_id")),
            )] = None
    if bad:
        raise ObservationError(f"{path}: bad observation rows: {', '.join(bad[:20])}")
    return list(out)


def write_observations(obs: Iterable[Observation], path: str | Path) -> int:
    rows = sorted(set(obs), key=lambda o: (o.ticker, o.as_of, o.name or "", o.cusip or ""))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(OBS_COLUMNS)
        for o in rows:
            w.writerow([o.ticker, o.as_of, o.name or "", o.cusip or "", "" if o.cik is None else o.cik,
                        o.sec_id or ""])
    return len(rows)


@dataclass
class TickerEra:
    ticker: str
    first: str
    last: str
    observations: list[Observation] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return list(dict.fromkeys(o.name for o in self.observations if o.name))

    @property
    def name(self) -> str | None:
        named = [o.name for o in self.observations if o.name]
        return named[-1] if named else None

    @property
    def cusips(self) -> list[str]:
        return list(dict.fromkeys(o.cusip for o in reversed(self.observations) if o.cusip))

    @property
    def cik_pin(self) -> int | None:
        return next((o.cik for o in reversed(self.observations) if o.cik is not None), None)

    @property
    def sec_id_pin(self) -> str | None:
        return next((o.sec_id for o in reversed(self.observations) if o.sec_id), None)

    @property
    def key(self) -> str:
        return f"{self.ticker}@{self.first}"


def _gap_days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def split_eras(obs: list[Observation]) -> list[TickerEra]:
    eras: list[TickerEra] = []
    for o in sorted(obs, key=lambda o: o.as_of):
        cur = eras[-1] if eras else None
        if cur is not None:
            last_name = cur.name
            pin_changed = ((o.cik is not None and cur.cik_pin is not None and o.cik != cur.cik_pin)
                           or (o.sec_id and cur.sec_id_pin and o.sec_id != cur.sec_id_pin))
            name_changed = bool(o.name and last_name and not names_agree(o.name, last_name)
                                and o.name.upper() != last_name.upper())
            if _gap_days(cur.last, o.as_of) <= ERA_GAP_DAYS and not pin_changed and not name_changed:
                cur.observations.append(o)
                cur.last = o.as_of
                continue
        eras.append(TickerEra(o.ticker, o.as_of, o.as_of, [o]))
    return eras


class ObservationIndex:
    def __init__(self, observations: Iterable[Observation]) -> None:
        by: dict[str, list[Observation]] = defaultdict(list)
        for o in observations:
            by[o.ticker].append(o)
        self._by = {t: sorted(v, key=lambda o: o.as_of) for t, v in by.items()}
        self._eras = {t: split_eras(v) for t, v in self._by.items()}

    def eras(self) -> list[TickerEra]:
        return [e for t in sorted(self._eras) for e in self._eras[t]]

    def era_for(self, ticker: str, day: str) -> TickerEra | None:
        eras = self._eras.get(normalize_ticker(ticker), [])
        best, best_gap = None, None
        for e in eras:
            if e.first <= day <= e.last:
                return e
            gap = min(abs(_gap_days(day, e.first)), abs(_gap_days(day, e.last)))
            if gap <= ERA_GAP_DAYS and (best_gap is None or gap < best_gap):
                best, best_gap = e, gap
        return best

    def name_on(self, ticker: str, observed_date: str | None = None) -> str | None:
        named = [o for o in self._by.get(normalize_ticker(ticker), []) if o.name]
        if not named:
            return None
        if observed_date is None:
            return named[-1].name
        i = bisect_right([o.as_of for o in named], observed_date)
        return named[i - 1].name if i else named[0].name

    def cik_pin_on(self, ticker: str, observed_date: str | None = None) -> int | None:
        if observed_date is None:
            eras = self._eras.get(normalize_ticker(ticker), [])
            return eras[-1].cik_pin if eras else None
        era = self.era_for(ticker, observed_date)
        return era.cik_pin if era else None


def observations_from_instruments(path: str | Path) -> list[Observation]:
    """A `(ticker, start, end)` file (tab- or comma-separated, optional header)
    becomes two observations per row, on its start and end dates."""
    out: list[Observation] = []
    for line in Path(path).read_text().splitlines():
        parts = [p.strip() for p in re.split(r"[\t,]", line)]
        if len(parts) < 3:
            continue
        ticker, start, end = normalize_ticker(parts[0]), _iso(parts[1]), _iso(parts[2])
        if not ticker or start is None or end is None:
            continue                              # header or malformed line
        out += [Observation(ticker, start), Observation(ticker, end)]
    return out


def observations_from_snapshots(folder: str | Path, *, where: dict[str, str] | None = None,
                                date_regex: str = DATE_IN_NAME) -> list[Observation]:
    """Every `*.csv` in `folder` whose file name contains a date is a snapshot:
    each row with a ticker becomes an observation on that date. `where` keeps only
    rows whose column equals the value (e.g. {"asset_class": "Equity"})."""
    out: dict[Observation, None] = {}
    for p in sorted(Path(folder).glob("*.csv")):
        m = re.search(date_regex, p.name)
        as_of = _iso(m.group(1)) if m else None
        if as_of is None:
            continue
        with p.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
            rows = list(reader)
        tcol = cols.get("ticker") or cols.get("symbol")
        if tcol is None:
            continue
        # A filter applies only where the file has that column filled in: the
        # Wikipedia snapshots carry an empty asset_class column.
        active = {cols[k.lower()]: v for k, v in (where or {}).items()
                  if k.lower() in cols and any((r.get(cols[k.lower()]) or "").strip() for r in rows)}
        for row in rows:
            if any((row.get(c) or "").strip() != v for c, v in active.items()):
                continue
            ticker = normalize_ticker(row.get(tcol) or "")
            if not ticker:
                continue
            cusip = _clean(row.get(cols["cusip"])) if "cusip" in cols else None
            out[Observation(ticker, as_of, _clean(row.get(cols["name"])) if "name" in cols else None,
                            cusip.upper() if cusip else None)] = None
    return sorted(out, key=lambda o: (o.ticker, o.as_of))
```

```python
# scripts/observations_from_snapshots.py
"""Turn folders of dated snapshot CSVs (ticker, name columns; date in the file
name) into an observations CSV for classify_universe.py.

    PYTHONPATH=src python scripts/observations_from_snapshots.py \
        --dir ../qlib_practice/fetch_data_aplha/data/ishares_russell_1000/raw \
        --dir ../qlib_practice/fetch_data_aplha/data/ishares_russell_1000/wikipedia_russell/raw \
        --where asset_class=Equity --out data/observations.csv
"""
from __future__ import annotations

import argparse
import sys

from delist_detection.observations import observations_from_snapshots, write_observations


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", action="append", required=True, help="folder of dated snapshot CSVs (repeatable)")
    p.add_argument("--where", action="append", default=[], help="COLUMN=VALUE row filter (repeatable); "
                   "a file without that column keeps all rows")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    where = dict(w.split("=", 1) for w in args.where)
    obs = []
    for d in args.dir:
        obs += observations_from_snapshots(d, where=where or None)
    n = write_observations(obs, args.out)
    print(f"Wrote {args.out}: {n} observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Also add this test to `tests/test_observations.py` (the Wikipedia snapshots have an empty `asset_class` column):

```python
def test_where_ignored_when_column_blank(tmp_path):
    (tmp_path / "russell_2008-01-16.csv").write_text("ticker,name,asset_class\nAET,AETNA INC,\n")
    obs = observations_from_snapshots(tmp_path, where={"asset_class": "Equity"})
    assert [o.ticker for o in obs] == ["AET"]
```

```python
# scripts/observations_from_instruments.py
"""Turn a `(ticker, start, end)` instruments file into observations (two per row).

    PYTHONPATH=src python scripts/observations_from_instruments.py --instruments all.txt --out obs.csv
"""
from __future__ import annotations

import argparse
import sys

from delist_detection.observations import observations_from_instruments, write_observations


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--instruments", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    n = write_observations(observations_from_instruments(args.instruments), args.out)
    print(f"Wrote {args.out}: {n} observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_observations.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/observations.py scripts/observations_from_snapshots.py scripts/observations_from_instruments.py tests/test_observations.py
git commit -m "feat(observations): caller observations, ticker eras, input converters"
```

---

### Task 4: SEC downloads and raw filing text

**Files:**
- Create: `src/delist_detection/sec_http.py`
- Modify: `src/delist_detection/edgar.py` (add `EdgarClient.fetch_filing_raw` after `fetch_filing_text`)
- Test: `tests/test_sec_http.py`

**Interfaces:**
- Consumes: `edgar._throttle()`, `edgar.check_response(resp)`, `edgar.resolve_user_agent()`, `edgar.EdgarBlocked`.
- Produces:
  - `sec_http.download(url: str, dest: Path, *, session=None, user_agent: str | None = None) -> Path` — cached by `dest`; 404 raises `FileNotFoundError`; 403/429 raise `EdgarBlocked`.
  - `sec_http.get_text(url: str, cache_file: Path, *, max_age_days: float = 7, session=None, user_agent=None) -> str` — refetches when the cache is older than `max_age_days`; serves the old cache if the refetch fails.
  - `EdgarClient.fetch_filing_raw(cik: int | str, accession: str) -> str` — the complete submission text (`{accession}.txt`, every document with its `<TYPE>` header), cached under `cache/edgar/raw/`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sec_http.py
import os
import time

import pytest
import requests

from delist_detection import sec_http
from delist_detection.edgar import EdgarBlocked, EdgarClient


class _Resp:
    def __init__(self, status=200, text="", content=b"", url="u"):
        self.status_code, self.text, self.content, self.url = status, text, content, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.headers = {}

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(sec_http, "_throttle", lambda: None)


def test_download_caches(tmp_path):
    s = _Session(_Resp(content=b"zipbytes"))
    p = sec_http.download("https://www.sec.gov/f.zip", tmp_path / "f.zip", session=s, user_agent="ua")
    assert p.read_bytes() == b"zipbytes"
    sec_http.download("https://www.sec.gov/f.zip", tmp_path / "f.zip", session=s, user_agent="ua")
    assert len(s.calls) == 1


def test_download_404_and_block(tmp_path):
    with pytest.raises(FileNotFoundError):
        sec_http.download("u", tmp_path / "a.zip", session=_Session(_Resp(404)), user_agent="ua")
    with pytest.raises(EdgarBlocked):
        sec_http.download("u", tmp_path / "b.zip", session=_Session(_Resp(429)), user_agent="ua")
    assert not (tmp_path / "a.zip").exists() and not (tmp_path / "b.zip").exists()


def test_get_text_refreshes_and_falls_back(tmp_path):
    cf = tmp_path / "index.html"
    s = _Session(_Resp(text="v1"))
    assert sec_http.get_text("u", cf, session=s, user_agent="ua") == "v1"
    assert sec_http.get_text("u", cf, session=s, user_agent="ua") == "v1"      # fresh cache
    assert len(s.calls) == 1
    old = time.time() - 10 * 86400
    os.utime(cf, (old, old))
    s2 = _Session(requests.ConnectionError("down"))
    assert sec_http.get_text("u", cf, session=s2, user_agent="ua") == "v1"     # stale cache served
    with pytest.raises(requests.ConnectionError):
        sec_http.get_text("u", tmp_path / "none.html", session=_Session(requests.ConnectionError("x")),
                          user_agent="ua")


def test_fetch_filing_raw(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    s = _Session(_Resp(text="<TYPE>25-NSE\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>"),
                 _Resp(404))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s)
    raw = ec.fetch_filing_raw(1122304, "0000876661-18-001269")
    assert "Common Stock" in raw
    assert s.calls[0].endswith("/Archives/edgar/data/1122304/000087666118001269/0000876661-18-001269.txt")
    assert ec.fetch_filing_raw(1122304, "0000876661-18-001269") == raw          # cached
    assert ec.fetch_filing_raw(1, "0000000000-00-000001") == ""                 # 404, cached empty
    assert ec.fetch_filing_raw(1, "0000000000-00-000001") == ""
    assert len(s.calls) == 2


def test_fetch_filing_raw_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=_Session(_Resp(403)))
    with pytest.raises(EdgarBlocked):
        ec.fetch_filing_raw(1, "0000000000-00-000002")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_sec_http.py -v`
Expected: FAIL with `ImportError` (no `sec_http`) and `AttributeError` (no `fetch_filing_raw`)

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/sec_http.py
"""Throttled, cached downloads of SEC data files (fails-to-deliver ZIPs, MIDAS
ZIPs, their index pages). Same fair-access rules as EdgarClient: one shared
8 req/s throttle, a descriptive User-Agent, and EdgarBlocked on 403/429."""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from .edgar import _throttle, check_response, resolve_user_agent


def _get(url: str, session, user_agent: str | None, timeout: int):
    s = session or requests.Session()
    headers = {"User-Agent": user_agent or resolve_user_agent(), "Accept": "*/*", "Host": "www.sec.gov"}
    _throttle()
    resp = s.get(url, headers=headers, timeout=timeout)
    check_response(resp)
    return resp


def download(url: str, dest: str | Path, *, session=None, user_agent: str | None = None) -> Path:
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    resp = _get(url, session, user_agent, timeout=180)
    if resp.status_code == 404:
        raise FileNotFoundError(url)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(resp.content)
    os.replace(tmp, dest)
    return dest


def get_text(url: str, cache_file: str | Path, *, max_age_days: float = 7, session=None,
             user_agent: str | None = None) -> str:
    cf = Path(cache_file)
    if cf.exists() and time.time() - cf.stat().st_mtime < max_age_days * 86400:
        return cf.read_text(encoding="utf-8", errors="replace")
    try:
        resp = _get(url, session, user_agent, timeout=60)
        resp.raise_for_status()
    except requests.RequestException:
        if cf.exists():
            return cf.read_text(encoding="utf-8", errors="replace")
        raise
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(resp.text, encoding="utf-8")
    return resp.text
```

In `src/delist_detection/edgar.py`, add this method to `EdgarClient` directly after `fetch_filing_text`:

```python
    def fetch_filing_raw(self, cik: int | str, accession: str) -> str:
        """The complete submission text file: every document of the filing with
        its <TYPE> header and raw markup (Form 25 XML plus its EX-99.25 notice).

        Cached under cache/edgar/raw/{accession_no_dashes}.txt. Returns '' on a
        404 (cached as a sticky miss) or a network error (not cached). A 403/429
        raises EdgarBlocked.
        """
        acc_nodash = accession.replace("-", "")
        raw_dir = self.cache_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        cp = raw_dir / f"{acc_nodash}.txt"
        if cp.exists():
            return cp.read_text(encoding="utf-8", errors="replace")
        url = f"{WWW_SEC_HOST}/Archives/edgar/data/{int(cik)}/{acc_nodash}/{accession}.txt"
        _throttle()
        try:
            resp = self.session.get(
                url,
                headers={**self.session.headers, "Host": "www.sec.gov", "Accept": "text/plain,*/*"},
                timeout=30,
            )
        except requests.RequestException:
            return ""
        check_response(resp)
        if resp.status_code != 200:
            if resp.status_code == 404:
                cp.write_text("", encoding="utf-8")
            return ""
        cp.write_text(resp.text, encoding="utf-8")
        return resp.text
```

In `tests/conftest.py`, add a `fetch_filing_raw` method to `_FakeEdgar` so later tests can serve raw filings:

```python
    raws: dict[str, str] = field(default_factory=dict)    # accession -> complete submission text

    def fetch_filing_raw(self, cik: int | str, accession: str) -> str:
        return self.raws.get(accession, "")
```
(`raws` goes after the existing `texts` field.) In `tests/golden.py`, add to `GoldenEdgar`:

```python
    def fetch_filing_raw(self, cik, accession):
        p = FIX / "raw" / f"{int(cik)}_{accession}.txt"
        return p.read_text(encoding="utf-8") if p.exists() else ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_sec_http.py -v && ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -p no:warnings`
Expected: 5 passed; full suite passes.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/sec_http.py src/delist_detection/edgar.py tests/test_sec_http.py tests/conftest.py tests/golden.py
git commit -m "feat(sec): cached SEC file downloads and raw filing text"
```

---

### Task 5: SEC fails-to-deliver (FTD) data

**Files:**
- Create: `src/delist_detection/ftd.py`
- Test: `tests/test_ftd.py`

**Interfaces:**
- Consumes: `sec_http.download`, `sec_http.get_text` (Task 4); `observations.normalize_ticker` (Task 3); `trading_calendar.next_trading_day`, `add_trading_days` (Task 2).
- Produces:
  - `FTD_INDEX_URL: str`
  - `FtdRow(date: str, cusip: str, symbol: str, description: str, price: float | None)` (frozen; `date` ISO; `symbol` normalized)
  - `period_of(url: str) -> tuple[date, date] | None`
  - `parse_index_links(html: str) -> list[str]` (absolute URLs, first occurrence of each period wins)
  - `parse_ftd_lines(lines: Iterable[str], *, symbols: set[str] | None = None, cusips: set[str] | None = None) -> Iterator[FtdRow]`
  - `FtdClient(cache_dir, *, session=None, user_agent=None)` with `.urls_for(lo: date, hi: date) -> list[str]` and `.rows(url, *, symbols=None, cusips=None) -> Iterator[FtdRow]`
  - `FtdIndex(rows: Iterable[FtdRow] = ())` with `.add(row)`, `.load(client, lo, hi, *, symbols=None, cusips=None) -> FtdIndex` (classmethod), `.extend(client, lo, hi, *, cusips)`, `.by_symbol(symbol, lo: str | None = None, hi: str | None = None) -> list[FtdRow]`, `.by_cusip(cusip, lo=None, hi=None) -> list[FtdRow]`, `.close_after(day: date, *, cusip: str | None = None, symbol: str | None = None, max_lag: int = 3) -> tuple[float, str, bool] | None`

Format facts (checked 2026-09-23): the index page `https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data` links ~434 ZIPs under several folders (`/files/data/fails-deliver-data/`, `/files/data/frequently-requested-foia-document-fails-deliver-data/`, `/files/data/other/fails-deliver-data/`, `/files/node/add/data_distribution/`). Names are `cnsfailsYYYYMM{a|b}.zip` (a = days 1–15, b = 16–end), sometimes with a `_0` suffix, and `cnsp_sec_fails_YYYYqN.zip` for 2004–2009 quarters (holding monthly `.txt` members). Every `.txt` member is pipe-delimited with header `SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE`, dates `YYYYMMDD`, price may be `.` or empty, and two trailer lines `Trailer record count N` / `Trailer total quantity of shares N`. A row dated D carries the close of the prior trading day (CVS row 2018-11-29 = 80.27 = the 2018-11-28 close).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ftd.py
import io
import zipfile
from datetime import date

from delist_detection.ftd import (
    FtdClient, FtdIndex, FtdRow, parse_ftd_lines, parse_index_links, period_of,
)

SAMPLE = """SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE
20181126|00817Y108|AET|89|AETNA INC.(NEW)|205.36
20181128|00817Y108|AET|1948|AETNA INC.(NEW)|210.10
20181129|00817Y108|AET|300|AETNA INC.(NEW)|212.70
20181130|00817Y108|AET|100|AETNA INC.(NEW)|212.70
20181129|126650100|CVS|5000|CVS HEALTH CORP|80.27
20040322|000375204|ABB|529463|ABB LTD ADS ( 1 REG SHS)|.
20181129|084670702|BRK/B|10|BERKSHIRE HATHAWAY INC|A|210.00
Trailer record count 7
Trailer total quantity of shares 5000
"""


def test_period_of():
    assert period_of("/files/data/fails-deliver-data/cnsfails201811b.zip") == (date(2018, 11, 16), date(2018, 11, 30))
    assert period_of("x/cnsfails201910a_0.zip") == (date(2019, 10, 1), date(2019, 10, 15))
    assert period_of("x/cnsp_sec_fails_2008q4.zip") == (date(2008, 10, 1), date(2008, 12, 31))
    assert period_of("x/readme.zip") is None


def test_parse_index_links_absolute_and_deduped():
    html = ('<a href="/files/data/fails-deliver-data/cnsfails201910a.zip">a</a>'
            '<a href="/files/data/fails-deliver-data/cnsfails201910a_0.zip">b</a>'
            '<a href="https://www.sec.gov/files/data/other/fails-deliver-data/cnsfails202308b_0.zip">c</a>'
            '<a href="/files/other.pdf">d</a>')
    assert parse_index_links(html) == [
        "https://www.sec.gov/files/data/fails-deliver-data/cnsfails201910a.zip",
        "https://www.sec.gov/files/data/other/fails-deliver-data/cnsfails202308b_0.zip",
    ]


def test_parse_lines_filters_and_handles_odd_rows():
    rows = list(parse_ftd_lines(SAMPLE.splitlines()))
    assert rows[0] == FtdRow("2018-11-26", "00817Y108", "AET", "AETNA INC.(NEW)", 205.36)
    abb = next(r for r in rows if r.symbol == "ABB")
    assert abb.price is None
    brk = next(r for r in rows if r.cusip == "084670702")
    assert brk.symbol == "BRK-B" and brk.description == "BERKSHIRE HATHAWAY INC|A" and brk.price == 210.0
    only = list(parse_ftd_lines(SAMPLE.splitlines(), symbols={"CVS"}))
    assert [r.symbol for r in only] == ["CVS"]
    by_cusip = list(parse_ftd_lines(SAMPLE.splitlines(), cusips={"00817Y108"}))
    assert len(by_cusip) == 4


def test_close_after_uses_next_trading_day_row():
    idx = FtdIndex(parse_ftd_lines(SAMPLE.splitlines()))
    assert idx.close_after(date(2018, 11, 28), cusip="00817Y108") == (212.70, "2018-11-29", False)
    assert idx.close_after(date(2018, 11, 28), symbol="CVS") == (80.27, "2018-11-29", False)
    # no row on the next trading day: the first later row within max_lag, flagged lagged
    assert idx.close_after(date(2018, 11, 27), cusip="00817Y108") == (210.10, "2018-11-28", False)
    assert idx.close_after(date(2018, 11, 23), cusip="00817Y108") == (205.36, "2018-11-26", False)
    assert idx.close_after(date(2018, 11, 21), cusip="00817Y108", max_lag=0) is None
    assert idx.close_after(date(2018, 11, 21), cusip="00817Y108", max_lag=3) == (205.36, "2018-11-26", True)


def test_by_symbol_and_cusip_ranges():
    idx = FtdIndex(parse_ftd_lines(SAMPLE.splitlines()))
    assert [r.date for r in idx.by_cusip("00817Y108", "2018-11-28", "2018-11-29")] == ["2018-11-28", "2018-11-29"]
    assert [r.date for r in idx.by_symbol("aet", hi="2018-11-26")] == ["2018-11-26"]


def _zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in members.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_client_reads_quarterly_zip(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(
        '<a href="/files/data/x/cnsp_sec_fails_2008q4.zip">q</a><a href="/files/data/x/cnsfails201811b.zip">b</a>')
    (tmp_path / "cnsp_sec_fails_2008q4.zip").write_bytes(_zip_bytes({
        "cnsp_sec_fails_200812.txt": "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
                                     "20081230|590188108|MER|10|MERRILL LYNCH & CO INC|11.07\n",
        "README.txt": "ignore me",
    }))
    c = FtdClient(tmp_path)
    assert c.urls_for(date(2008, 12, 1), date(2008, 12, 31)) == [
        "https://www.sec.gov/files/data/x/cnsp_sec_fails_2008q4.zip"]
    rows = list(c.rows(c.urls_for(date(2008, 12, 1), date(2008, 12, 31))[0]))
    assert rows == [FtdRow("2008-12-30", "590188108", "MER", "MERRILL LYNCH & CO INC", 11.07)]
    idx = FtdIndex.load(c, date(2008, 12, 1), date(2008, 12, 31), symbols={"MER"})
    assert idx.close_after(date(2008, 12, 29), symbol="MER") == (11.07, "2008-12-30", False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_ftd.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/ftd.py
"""SEC fails-to-deliver data: dated (CUSIP, symbol, description, price) rows.

Two uses: the close on a security's last trading day (a row dated D carries the
close of the prior trading day), and the CUSIP a symbol carried on a date.
Rows exist only on days with fails, so a quiet security has gaps.
"""
from __future__ import annotations

import calendar
import io
import re
import zipfile
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .observations import normalize_ticker
from .sec_http import download, get_text
from .trading_calendar import add_trading_days, next_trading_day

FTD_INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
_SEC = "https://www.sec.gov"
_HALF = re.compile(r"cnsfails(\d{4})(\d{2})([ab])(?:_\d+)?\.zip$", re.I)
_QTR = re.compile(r"cnsp_sec_fails_(\d{4})q([1-4])\.zip$", re.I)


@dataclass(frozen=True)
class FtdRow:
    date: str
    cusip: str
    symbol: str
    description: str
    price: float | None


def period_of(url: str) -> tuple[date, date] | None:
    name = url.rsplit("/", 1)[-1]
    m = _HALF.search(name)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if m.group(3).lower() == "a":
            return date(y, mo, 1), date(y, mo, 15)
        return date(y, mo, 16), date(y, mo, calendar.monthrange(y, mo)[1])
    m = _QTR.search(name)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        end_month = 3 * q
        return date(y, end_month - 2, 1), date(y, end_month, calendar.monthrange(y, end_month)[1])
    return None


def parse_index_links(html: str) -> list[str]:
    out: list[str] = []
    seen: set[tuple[date, date]] = set()
    for href in re.findall(r'href="([^"]+\.zip)"', html, re.I):
        p = period_of(href)
        if p is None or p in seen:
            continue
        seen.add(p)
        out.append(href if href.startswith("http") else _SEC + href)
    return out


def parse_ftd_lines(lines: Iterable[str], *, symbols: set[str] | None = None,
                    cusips: set[str] | None = None) -> Iterator[FtdRow]:
    """Rows from FTD text lines; header, trailer and malformed lines are skipped.
    With `symbols`/`cusips`, only rows matching either set are built (fast path)."""
    want = symbols is not None or cusips is not None
    symbols = symbols or set()
    cusips = cusips or set()
    for line in lines:
        parts = line.rstrip("\r\n").split("|")
        if len(parts) < 6:
            continue
        d = parts[0].strip()
        if len(d) != 8 or not d.isdigit():
            continue
        cusip = parts[1].strip().upper()
        symbol = normalize_ticker(parts[2])
        if want and symbol not in symbols and cusip not in cusips:
            continue
        try:
            price: float | None = float(parts[-1].strip())
        except ValueError:
            price = None
        yield FtdRow(f"{d[:4]}-{d[4:6]}-{d[6:]}", cusip, symbol, "|".join(parts[4:-1]).strip(), price)


class FtdClient:
    def __init__(self, cache_dir: str | Path, *, session=None, user_agent: str | None = None) -> None:
        self.dir = Path(cache_dir)
        self.session, self.user_agent = session, user_agent
        self._links: list[str] | None = None

    def links(self) -> list[str]:
        if self._links is None:
            html = get_text(FTD_INDEX_URL, self.dir / "index.html", max_age_days=7,
                            session=self.session, user_agent=self.user_agent)
            self._links = parse_index_links(html)
        return self._links

    def urls_for(self, lo: date, hi: date) -> list[str]:
        hits = [(period_of(u), u) for u in self.links()]
        return [u for p, u in sorted(hits) if p and p[0] <= hi and p[1] >= lo]

    def rows(self, url: str, *, symbols: set[str] | None = None,
             cusips: set[str] | None = None) -> Iterator[FtdRow]:
        dest = self.dir / url.rsplit("/", 1)[-1]
        path = download(url, dest, session=self.session, user_agent=self.user_agent)
        try:
            z = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            path.unlink(missing_ok=True)          # a truncated download: fetch it again once
            z = zipfile.ZipFile(download(url, dest, session=self.session, user_agent=self.user_agent))
        with z:
            for member in z.namelist():
                if not member.lower().endswith(".txt"):
                    continue
                with z.open(member) as fh:
                    yield from parse_ftd_lines(io.TextIOWrapper(fh, encoding="latin-1"),
                                               symbols=symbols, cusips=cusips)


class FtdIndex:
    def __init__(self, rows: Iterable[FtdRow] = ()) -> None:
        self._by_symbol: dict[str, list[FtdRow]] = defaultdict(list)
        self._by_cusip: dict[str, list[FtdRow]] = defaultdict(list)
        self._seen: set[FtdRow] = set()
        self._dirty = False
        for r in rows:
            self.add(r)

    def add(self, r: FtdRow) -> None:
        if r in self._seen:
            return
        self._seen.add(r)
        self._by_symbol[r.symbol].append(r)
        self._by_cusip[r.cusip].append(r)
        self._dirty = True

    @classmethod
    def load(cls, client: FtdClient, lo: date, hi: date, *, symbols: Iterable[str] | None = None,
             cusips: Iterable[str] | None = None) -> "FtdIndex":
        idx = cls()
        idx._scan(client, lo, hi, {normalize_ticker(s) for s in symbols or ()},
                  {c.upper() for c in cusips or ()})
        return idx

    def extend(self, client: FtdClient, lo: date, hi: date, *, cusips: Iterable[str]) -> None:
        new = {c.upper() for c in cusips} - set(self._by_cusip)
        if new:
            self._scan(client, lo, hi, set(), new)

    def _scan(self, client: FtdClient, lo: date, hi: date, symbols: set[str], cusips: set[str]) -> None:
        lo_s, hi_s = lo.isoformat(), hi.isoformat()
        for url in client.urls_for(lo, hi):
            for r in client.rows(url, symbols=symbols, cusips=cusips):
                if lo_s <= r.date <= hi_s:
                    self.add(r)

    def _sort(self) -> None:
        if self._dirty:
            for m in (self._by_symbol, self._by_cusip):
                for v in m.values():
                    v.sort(key=lambda r: (r.date, r.cusip, r.symbol))
            self._dirty = False

    @staticmethod
    def _slice(rows: list[FtdRow], lo: str | None, hi: str | None) -> list[FtdRow]:
        dates = [r.date for r in rows]
        i = bisect_left(dates, lo) if lo else 0
        j = bisect_right(dates, hi) if hi else len(rows)
        return rows[i:j]

    def by_symbol(self, symbol: str, lo: str | None = None, hi: str | None = None) -> list[FtdRow]:
        self._sort()
        return self._slice(self._by_symbol.get(normalize_ticker(symbol), []), lo, hi)

    def by_cusip(self, cusip: str, lo: str | None = None, hi: str | None = None) -> list[FtdRow]:
        self._sort()
        return self._slice(self._by_cusip.get(cusip.upper(), []), lo, hi)

    def close_after(self, day: date, *, cusip: str | None = None, symbol: str | None = None,
                    max_lag: int = 3) -> tuple[float, str, bool] | None:
        """The close of `day`: the first priced row dated on the next trading day,
        or up to `max_lag` further trading days later (then `lagged` is True; rows
        after the last trade repeat the last close, but after an OTC move they
        carry OTC prices, so a lagged value is flagged for review)."""
        first = next_trading_day(day)
        last = add_trading_days(first, max_lag)
        rows = (self.by_cusip(cusip, first.isoformat(), last.isoformat()) if cusip
                else self.by_symbol(symbol or "", first.isoformat(), last.isoformat()))
        for r in rows:
            if r.price is not None and r.price > 0:
                return r.price, r.date, r.date != first.isoformat()
        return None
```

Worked example for the tests: `close_after(date(2018, 11, 21), max_lag=3)` looks at 2018-11-23 (the next trading day; Thanksgiving is skipped) through 2018-11-28; the first priced row is 11-26, so it returns it with `lagged=True`. With `max_lag=0` only 11-23 is looked at, so it returns `None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_ftd.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/ftd.py tests/test_ftd.py
git commit -m "feat(ftd): SEC fails-to-deliver index for closes and CUSIPs"
```

---

### Task 6: SEC MIDAS last exchange-trade day

**Files:**
- Create: `src/delist_detection/midas.py`
- Test: `tests/test_midas.py`

**Interfaces:**
- Consumes: `sec_http.download`, `sec_http.get_text`; `observations.normalize_ticker`.
- Produces:
  - `MIDAS_INDEX_URL: str`, `MIDAS_START = date(2012, 1, 1)`
  - `quarter_of(url: str) -> tuple[int, int] | None` (the 2012 Q1 file is published as `_q10`)
  - `summarize_midas_csv(lines: Iterable[str]) -> dict[str, list[str]]` — ticker → sorted ISO dates with lit + hidden volume > 0
  - `MidasClient(cache_dir, *, session=None, user_agent=None)` with `.last_trade_day(ticker: str, lo: date, hi: date) -> date | None`

Format facts (checked 2026-09-23): index page `https://www.sec.gov/opa/data/market-structure/marketstructuredownloadshtml-by_security.html` links 58 ZIPs `/files/opa/data/market-structure/metrics-individual-security/individual_security_YYYY_qN.zip` (2012 Q1 is `individual_security_2012_q10.zip`). Each ZIP holds `README.txt` and one CSV (e.g. `q4_2018_all.csv`, ~50 MB) with header `Date,Security,Ticker,McapRank,TurnRank,VolatilityRank,PriceRank,LitVol('000),OrderVol('000),Hidden,TradesForHidden,HiddenVol('000),TradeVolForHidden('000),Cancels,LitTrades,OddLots,TradesForOddLots,OddLotVol('000),TradeVolForOddLots('000)` and dates `YYYYMMDD`. Some halt-day rows have orders but zero trades, so filter on volume, not presence.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_midas.py
import gzip
import io
import json
import zipfile
from datetime import date

from delist_detection.midas import MidasClient, quarter_of, summarize_midas_csv

CSV = """Date,Security,Ticker,McapRank,TurnRank,VolatilityRank,PriceRank,LitVol('000),OrderVol('000),Hidden,TradesForHidden,HiddenVol('000),TradeVolForHidden('000),Cancels,LitTrades,OddLots,TradesForOddLots,OddLotVol('000),TradeVolForOddLots('000)
20181127,Stock,AET,10,4,1,10,400.1,500,1,1,20.0,1,1,1,1,1,1,1
20181128,Stock,AET,10,4,1,10,300.0,500,1,1,0,1,1,1,1,1,1,1
20181129,Stock,AET,10,4,1,10,0,120.5,0,0,0,0,1,0,0,0,0,0
20181128,Stock,BRK.B,10,4,1,10,1.0,5,0,0,0,0,1,1,0,0,0,0
"""


def test_quarter_of():
    assert quarter_of("x/individual_security_2018_q4.zip") == (2018, 4)
    assert quarter_of("x/individual_security_2012_q10.zip") == (2012, 1)
    assert quarter_of("x/other.zip") is None


def test_summarize_filters_on_volume():
    s = summarize_midas_csv(CSV.splitlines())
    assert s["AET"] == ["2018-11-27", "2018-11-28"]      # 11-29 had orders but no trades
    assert s["BRK-B"] == ["2018-11-28"]


def test_client_last_trade_day_from_zip(tmp_path):
    (tmp_path / "index.html").write_text('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("README.txt", "readme")
        z.writestr("q4_2018_all.csv", CSV)
    (tmp_path / "individual_security_2018_q4.zip").write_bytes(buf.getvalue())
    c = MidasClient(tmp_path)
    assert c.last_trade_day("AET", date(2018, 10, 1), date(2018, 12, 10)) == date(2018, 11, 28)
    assert c.last_trade_day("AET", date(2018, 10, 1), date(2018, 11, 27)) == date(2018, 11, 27)
    assert c.last_trade_day("ZZZ", date(2018, 10, 1), date(2018, 12, 10)) is None
    assert c.last_trade_day("AET", date(2011, 1, 1), date(2011, 3, 1)) is None     # before MIDAS
    summary = tmp_path / "2018_q4.json.gz"
    assert json.loads(gzip.decompress(summary.read_bytes()))["AET"] == ["2018-11-27", "2018-11-28"]
    assert not (tmp_path / "individual_security_2018_q4.zip").exists()           # summary replaces the zip
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_midas.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/midas.py
"""SEC MIDAS "Metrics by Individual Security": daily exchange volume per ticker,
2012 onward. The last day with nonzero lit + hidden volume is the last day the
security traded on an exchange. Keyed by ticker only, exchange trades only.

Each quarterly ZIP (~15-25 MB) is summarized once into
`<cache>/<year>_q<q>.json.gz` (ticker -> dates with volume) and then deleted.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from .observations import normalize_ticker
from .sec_http import download, get_text

MIDAS_INDEX_URL = ("https://www.sec.gov/opa/data/market-structure/"
                   "marketstructuredownloadshtml-by_security.html")
MIDAS_START = date(2012, 1, 1)
_SEC = "https://www.sec.gov"
_Q = re.compile(r"individual_security_(\d{4})_q(\d+)\.zip$", re.I)


def quarter_of(url: str) -> tuple[int, int] | None:
    m = _Q.search(url.rsplit("/", 1)[-1])
    if not m:
        return None
    y, q = int(m.group(1)), int(m.group(2))
    if q == 10:
        q = 1
    return (y, q) if 1 <= q <= 4 else None


def _quarter(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def _quarters(lo: date, hi: date) -> list[tuple[int, int]]:
    out, (y, q) = [], _quarter(lo)
    while (y, q) <= _quarter(hi):
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def summarize_midas_csv(lines: Iterable[str]) -> dict[str, list[str]]:
    reader = csv.reader(lines)
    header = next(reader)
    idx = {h.strip(): i for i, h in enumerate(header)}
    i_date, i_tk = idx["Date"], idx["Ticker"]
    i_lit = next(i for h, i in idx.items() if h.startswith("LitVol"))
    i_hid = next(i for h, i in idx.items() if h.startswith("HiddenVol"))
    out: dict[str, set[str]] = defaultdict(set)
    for row in reader:
        if len(row) <= max(i_lit, i_hid):
            continue
        try:
            vol = float(row[i_lit] or 0) + float(row[i_hid] or 0)
        except ValueError:
            continue
        d = row[i_date].strip()
        if vol > 0 and len(d) == 8:
            out[normalize_ticker(row[i_tk])].add(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    return {t: sorted(v) for t, v in out.items()}


class MidasClient:
    def __init__(self, cache_dir: str | Path, *, session=None, user_agent: str | None = None) -> None:
        self.dir = Path(cache_dir)
        self.session, self.user_agent = session, user_agent
        self._links: dict[tuple[int, int], str] | None = None
        self._summaries: dict[tuple[int, int], dict[str, list[str]] | None] = {}

    def links(self) -> dict[tuple[int, int], str]:
        if self._links is None:
            html = get_text(MIDAS_INDEX_URL, self.dir / "index.html", max_age_days=30,
                            session=self.session, user_agent=self.user_agent)
            links: dict[tuple[int, int], str] = {}
            for href in re.findall(r'href="([^"]+\.zip)"', html, re.I):
                q = quarter_of(href)
                if q and q not in links:
                    links[q] = href if href.startswith("http") else _SEC + href
            self._links = links
        return self._links

    def _summary(self, yq: tuple[int, int]) -> dict[str, list[str]] | None:
        if yq in self._summaries:
            return self._summaries[yq]
        cache = self.dir / f"{yq[0]}_q{yq[1]}.json.gz"
        if cache.exists():
            s = json.loads(gzip.decompress(cache.read_bytes()))
        else:
            url = self.links().get(yq)
            if url is None:
                self._summaries[yq] = None
                return None
            zpath = download(url, self.dir / url.rsplit("/", 1)[-1], session=self.session,
                             user_agent=self.user_agent)
            with zipfile.ZipFile(zpath) as z:
                member = next(m for m in z.namelist() if m.lower().endswith(".csv"))
                with z.open(member) as fh:
                    s = summarize_midas_csv(io.TextIOWrapper(fh, encoding="latin-1"))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(gzip.compress(json.dumps(s).encode()))
            zpath.unlink(missing_ok=True)
        self._summaries[yq] = s
        return s

    def last_trade_day(self, ticker: str, lo: date, hi: date) -> date | None:
        if hi < MIDAS_START:
            return None
        t = normalize_ticker(ticker)
        lo_s, hi_s = max(lo, MIDAS_START).isoformat(), hi.isoformat()
        best: str | None = None
        for yq in _quarters(max(lo, MIDAS_START), hi):
            s = self._summary(yq)
            for d in (s or {}).get(t, []):
                if lo_s <= d <= hi_s and (best is None or d > best):
                    best = d
        return date.fromisoformat(best) if best else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_midas.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/midas.py tests/test_midas.py
git commit -m "feat(midas): last exchange-trade day from SEC MIDAS volume"
```

---

### Task 7: Nasdaq trade-halt feed

**Files:**
- Create: `src/delist_detection/nasdaq_halts.py`
- Test: `tests/test_nasdaq_halts.py`

**Interfaces:**
- Consumes: `trading_calendar.previous_trading_day`, `is_trading_day`; `observations.normalize_ticker`.
- Produces:
  - `HALTS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate={mmddyyyy}"`
  - `Halt(symbol: str, name: str, market: str, reason: str, halt_date: date, halt_time: str, resumption_date: date | None)` (frozen)
  - `parse_halts_rss(xml_text: str) -> list[Halt]`
  - `last_trade_from_halt(h: Halt) -> date` — halted before 09:30 → previous trading day, else the halt date
  - `NasdaqHaltClient(cache_dir, *, session=None, min_interval: float = 1.0)` with `.halts_on(day: date) -> list[Halt]` and `.deletion_halt(symbol: str, lo: date, hi: date, max_days: int = 7) -> Halt | None`

Format facts (checked 2026-09-23): RSS 2.0 with namespace `http://www.nasdaqtrader.com/`; each `<item>` has `ndaq:IssueSymbol`, `ndaq:IssueName`, `ndaq:Mkt`, `ndaq:ReasonCode`, `ndaq:HaltDate` (`MM/DD/YYYY`), `ndaq:HaltTime` (`HH:MM:SS`), `ndaq:ResumptionDate`. The response starts with a UTF-8 BOM. Code `D` = "security deletion from NASDAQ / CQS". Tested hits: ALTR halted 2025-03-25 19:50 (last trade 03-25); SAVE 2024-11-18 04:30 (last trade 2024-11-15); Altera 2015-12-28 08:52 (last trade 2015-12-24); LEH 2008-09-17 17:15.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_nasdaq_halts.py
from datetime import date

from delist_detection.nasdaq_halts import Halt, NasdaqHaltClient, last_trade_from_halt, parse_halts_rss

RSS = """﻿<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:ndaq="http://www.nasdaqtrader.com/">
  <channel>
    <item>
      <title>ALTR</title>
      <ndaq:IssueSymbol>ALTR</ndaq:IssueSymbol>
      <ndaq:IssueName>Altair Engineering Inc. Class A Common Stock</ndaq:IssueName>
      <ndaq:Mkt>Q</ndaq:Mkt>
      <ndaq:ReasonCode>D</ndaq:ReasonCode>
      <ndaq:HaltDate>03/25/2025</ndaq:HaltDate>
      <ndaq:HaltTime>19:50:00</ndaq:HaltTime>
      <ndaq:ResumptionDate>03/27/2025</ndaq:ResumptionDate>
    </item>
    <item>
      <title>CNSP</title>
      <ndaq:IssueSymbol>CNSP</ndaq:IssueSymbol>
      <ndaq:IssueName>CNS Pharmaceuticals</ndaq:IssueName>
      <ndaq:Mkt>Q</ndaq:Mkt>
      <ndaq:ReasonCode>T3</ndaq:ReasonCode>
      <ndaq:HaltDate>03/25/2025</ndaq:HaltDate>
      <ndaq:HaltTime>07:55:00</ndaq:HaltTime>
      <ndaq:ResumptionDate />
    </item>
  </channel>
</rss>"""


def test_parse():
    halts = parse_halts_rss(RSS)
    assert halts[0] == Halt("ALTR", "Altair Engineering Inc. Class A Common Stock", "Q", "D",
                            date(2025, 3, 25), "19:50:00", date(2025, 3, 27))
    assert halts[1].resumption_date is None


def test_last_trade_from_halt():
    after_close = Halt("ALTR", "", "Q", "D", date(2025, 3, 25), "19:50:00", None)
    before_open = Halt("SAVE", "", "N", "D", date(2024, 11, 18), "04:30:00", None)
    assert last_trade_from_halt(after_close) == date(2025, 3, 25)
    assert last_trade_from_halt(before_open) == date(2024, 11, 15)


class _Resp:
    status_code = 200

    def __init__(self, text):
        self.text = text


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return _Resp(RSS if "03252025" in url else RSS.replace("<item>", "<x>").replace("</item>", "</x>"))


def test_client_caches_and_finds_deletion(tmp_path):
    s = _Session()
    c = NasdaqHaltClient(tmp_path, session=s, min_interval=0)
    h = c.deletion_halt("ALTR", date(2025, 3, 24), date(2025, 3, 26))
    assert h is not None and h.halt_date == date(2025, 3, 25)
    assert c.deletion_halt("CNSP", date(2025, 3, 25), date(2025, 3, 25)) is None     # T3, not D
    n = len(s.urls)
    c.halts_on(date(2025, 3, 25))
    assert len(s.urls) == n                                                          # cached
    assert "haltdate=03252025" in s.urls[1] or "haltdate=03252025" in s.urls[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_nasdaq_halts.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/nasdaq_halts.py
"""Nasdaq Trader's keyless trade-halt feed, one day per request.

A code-D halt ("security deletion from NASDAQ / CQS") timestamps the end of
exchange trading, including some NYSE/CQS names. Many delistings have no entry,
so this only confirms a date; it is not a complete register.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from .observations import normalize_ticker
from .trading_calendar import is_trading_day, previous_trading_day

HALTS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate={mmddyyyy}"
_NS = {"ndaq": "http://www.nasdaqtrader.com/"}
_UA = "delist_detection research (halt history lookup)"


@dataclass(frozen=True)
class Halt:
    symbol: str
    name: str
    market: str
    reason: str
    halt_date: date
    halt_time: str
    resumption_date: date | None


def _mdy(s: str | None) -> date | None:
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_halts_rss(xml_text: str) -> list[Halt]:
    root = ET.fromstring(xml_text.lstrip("﻿").strip())
    out: list[Halt] = []
    for item in root.iter("item"):
        get = lambda tag: (item.findtext(f"ndaq:{tag}", default="", namespaces=_NS) or "").strip()
        hd = _mdy(get("HaltDate"))
        if hd is None:
            continue
        out.append(Halt(get("IssueSymbol"), get("IssueName"), get("Mkt"), get("ReasonCode"), hd,
                        get("HaltTime"), _mdy(get("ResumptionDate"))))
    return out


def last_trade_from_halt(h: Halt) -> date:
    return previous_trading_day(h.halt_date) if (h.halt_time or "00:00:00") < "09:30:00" else h.halt_date


class NasdaqHaltClient:
    def __init__(self, cache_dir: str | Path, *, session=None, min_interval: float = 1.0) -> None:
        self.dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self._last = 0.0

    def halts_on(self, day: date) -> list[Halt]:
        cp = self.dir / f"{day:%Y%m%d}.xml"
        if cp.exists():
            return parse_halts_rss(cp.read_text(encoding="utf-8"))
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            resp = self.session.get(HALTS_URL.format(mmddyyyy=f"{day:%m%d%Y}"),
                                    headers={"User-Agent": _UA}, timeout=30)
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        try:
            halts = parse_halts_rss(resp.text)
        except ET.ParseError:
            return []
        if day < date.today():                  # today's list can still grow
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(resp.text, encoding="utf-8")
        return halts

    def deletion_halt(self, symbol: str, lo: date, hi: date, max_days: int = 7) -> Halt | None:
        want = normalize_ticker(symbol)
        d, looked = lo, 0
        while d <= hi and looked < max_days:
            if is_trading_day(d):
                looked += 1
                for h in self.halts_on(d):
                    if h.reason == "D" and normalize_ticker(h.symbol) == want:
                        return h
            d += timedelta(days=1)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_nasdaq_halts.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/nasdaq_halts.py tests/test_nasdaq_halts.py
git commit -m "feat(halts): Nasdaq code-D halts confirm the last trading day"
```

---

### Task 8: OpenFIGI client

**Files:**
- Create: `src/delist_detection/openfigi.py`
- Test: `tests/test_openfigi.py`

**Interfaces:**
- Produces:
  - `OPENFIGI_URL = "https://api.openfigi.com/v3"`
  - `OpenFigiBlocked(RuntimeError)`
  - `resolve_api_key(env_file: Path = <repo>/.env) -> str | None` — `OPEN_FIGI_API_KEY` from the environment, else from the `.env` file
  - `OpenFigiClient(cache_dir, api_key: str | None = None, *, session=None, sleep=time.sleep)` with
    - `.max_jobs` (100 with a key, 10 without)
    - `.map(jobs: list[dict], *, use_cache: bool = True) -> list[dict]` — one answer per job, aligned; each answer is `{"data": [...]}`, `{"warning": "..."}` or `{"error": "..."}`; errors are never cached
    - `.filter(query: str, *, max_pages: int = 3, **fields) -> list[dict]` — `/v3/filter` data rows across pages, cached

Facts (checked 2026-09-23): with the key in `.env` (`OPEN_FIGI_API_KEY`), `/v3/mapping` answers with headers `ratelimit-limit: 250`, `ratelimit-remaining`, `ratelimit-reset` (seconds, 60-second window). Without a key: 25 requests/60 s and 10 jobs per request; filter/search share a 5/60 s budget. A 429 comes back as plain text with `retry-after`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_openfigi.py
import json

import pytest
import requests

from delist_detection.openfigi import OpenFigiBlocked, OpenFigiClient, resolve_api_key


class _Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    def __init__(self, *responses):
        self.responses, self.posts = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        return self.responses.pop(0)


AET = {"data": [{"figi": "BBG000FJLFX8", "compositeFIGI": "BBG000FJLFX8", "exchCode": "US", "ticker": "AET",
                 "name": "AETNA INC", "securityType": "Common Stock"}]}


def test_map_batches_caches_and_sends_key(tmp_path):
    s = _Session(_Resp(body=[AET, {"warning": "No identifier found."}]))
    c = OpenFigiClient(tmp_path, "k", session=s, sleep=lambda _: None)
    jobs = [{"idType": "TICKER", "idValue": "AET"}, {"idType": "TICKER", "idValue": "ZZZZ"}]
    assert c.map(jobs) == [AET, {"warning": "No identifier found."}]
    assert s.posts[0][0].endswith("/v3/mapping") and s.posts[0][2]["X-OPENFIGI-APIKEY"] == "k"
    assert c.map(jobs) == [AET, {"warning": "No identifier found."}]      # both answers cached
    assert len(s.posts) == 1


def test_map_splits_into_max_jobs_chunks(tmp_path):
    s = _Session(*[_Resp(body=[{"warning": "x"}] * 10), _Resp(body=[{"warning": "x"}] * 2)])
    c = OpenFigiClient(tmp_path, None, session=s, sleep=lambda _: None)
    assert c.max_jobs == 10
    c.map([{"idType": "TICKER", "idValue": f"T{i}"} for i in range(12)])
    assert [len(p[1]) for p in s.posts] == [10, 2]


def test_errors_not_cached_and_no_cache_mode(tmp_path):
    s = _Session(_Resp(body=[{"error": "Invalid idValue"}]), _Resp(body=[AET]), _Resp(body=[AET]))
    c = OpenFigiClient(tmp_path, "k", session=s, sleep=lambda _: None)
    job = [{"idType": "TICKER", "idValue": "AET"}]
    assert c.map(job) == [{"error": "Invalid idValue"}]
    assert c.map(job) == [AET]
    assert c.map(job, use_cache=False) == [AET]
    assert len(s.posts) == 3


def test_429_waits_then_succeeds_and_403_blocks(tmp_path):
    slept = []
    s = _Session(_Resp(429, headers={"retry-after": "7"}), _Resp(body=[AET]))
    c = OpenFigiClient(tmp_path, "k", session=s, sleep=slept.append)
    assert c.map([{"idType": "TICKER", "idValue": "AET"}]) == [AET]
    assert slept == [8]
    c2 = OpenFigiClient(tmp_path / "b", "bad", session=_Session(_Resp(403)), sleep=lambda _: None)
    with pytest.raises(OpenFigiBlocked):
        c2.map([{"idType": "TICKER", "idValue": "X"}])


def test_paces_when_budget_is_spent(tmp_path):
    slept = []
    s = _Session(_Resp(body=[AET], headers={"ratelimit-remaining": "0", "ratelimit-reset": "12"}))
    OpenFigiClient(tmp_path, "k", session=s, sleep=slept.append).map([{"idType": "TICKER", "idValue": "AET"}])
    assert slept == [13]


def test_filter_pages_and_caches(tmp_path):
    s = _Session(_Resp(body={"data": [{"figi": "A"}], "next": "p2"}), _Resp(body={"data": [{"figi": "B"}]}))
    c = OpenFigiClient(tmp_path, "k", session=s, sleep=lambda _: None)
    assert c.filter("QUESTCOR", exchCode="US") == [{"figi": "A"}, {"figi": "B"}]
    assert s.posts[1][1]["start"] == "p2"
    assert c.filter("QUESTCOR", exchCode="US") == [{"figi": "A"}, {"figi": "B"}]
    assert len(s.posts) == 2


def test_resolve_api_key(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPEN_FIGI_API_KEY=fromfile\n")
    monkeypatch.delenv("OPEN_FIGI_API_KEY", raising=False)
    assert resolve_api_key(env) == "fromfile"
    monkeypatch.setenv("OPEN_FIGI_API_KEY", "fromenv")
    assert resolve_api_key(env) == "fromenv"
    monkeypatch.delenv("OPEN_FIGI_API_KEY")
    assert resolve_api_key(tmp_path / "missing.env") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_openfigi.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/openfigi.py
"""OpenFIGI v3 client: every mapping job and filter query is cached on disk,
requests are paced on the ratelimit headers, a 429 is waited out, and a
401/403 raises OpenFigiBlocked (the CLI exits 2) instead of reading as a miss."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

OPENFIGI_URL = "https://api.openfigi.com/v3"
_REPO_ENV = Path(__file__).resolve().parents[2] / ".env"


class OpenFigiBlocked(RuntimeError):
    """OpenFIGI refused the request (bad key) or kept failing."""


def resolve_api_key(env_file: str | Path = _REPO_ENV) -> str | None:
    key = os.environ.get("OPEN_FIGI_API_KEY", "").strip()
    if key:
        return key
    if not Path(env_file).exists():
        return None
    from dotenv import dotenv_values  # noqa: PLC0415

    return (dotenv_values(env_file).get("OPEN_FIGI_API_KEY") or "").strip() or None


def _wait_seconds(headers, default: int) -> int:
    for k in ("retry-after", "ratelimit-reset"):
        v = str(headers.get(k) or "").strip()
        if v.isdigit():
            return int(v) + 1
    return default


class OpenFigiClient:
    MAX_RETRIES = 6

    def __init__(self, cache_dir: str | Path, api_key: str | None = None, *, session=None,
                 sleep=time.sleep) -> None:
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.session = session or requests.Session()
        self.sleep = sleep
        self.max_jobs = 100 if api_key else 10

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-OPENFIGI-APIKEY"] = self.api_key
        return h

    def _post(self, path: str, payload):
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self.session.post(f"{OPENFIGI_URL}{path}", json=payload, headers=self._headers(),
                                         timeout=60)
            except requests.RequestException:
                self.sleep(min(60, 2 ** attempt))
                continue
            if resp.status_code in (401, 403):
                raise OpenFigiBlocked(f"OpenFIGI returned {resp.status_code} for {path}; check OPEN_FIGI_API_KEY")
            if resp.status_code == 429 or resp.status_code >= 500:
                self.sleep(_wait_seconds(resp.headers, 60 if resp.status_code == 429 else 2 ** attempt))
                continue
            resp.raise_for_status()
            if str(resp.headers.get("ratelimit-remaining", "")).strip() == "0":
                self.sleep(_wait_seconds(resp.headers, 60))
            return resp.json()
        raise OpenFigiBlocked(f"OpenFIGI {path} kept failing after {self.MAX_RETRIES} attempts")

    def _cache_file(self, kind: str, payload) -> Path:
        h = hashlib.sha1(json.dumps({"kind": kind, "payload": payload}, sort_keys=True).encode()).hexdigest()
        return self.dir / f"{h}.json"

    def map(self, jobs: list[dict], *, use_cache: bool = True) -> list[dict]:
        results: list[dict | None] = [None] * len(jobs)
        todo: list[int] = []
        for i, job in enumerate(jobs):
            cf = self._cache_file("mapping", job)
            if use_cache and cf.exists():
                results[i] = json.loads(cf.read_text())
            else:
                todo.append(i)
        for k in range(0, len(todo), self.max_jobs):
            chunk = todo[k:k + self.max_jobs]
            answers = self._post("/mapping", [jobs[i] for i in chunk])
            for i, ans in zip(chunk, answers):
                results[i] = ans
                if use_cache and "error" not in ans:
                    self._cache_file("mapping", jobs[i]).write_text(json.dumps(ans))
        return [r if r is not None else {"error": "no answer"} for r in results]

    def filter(self, query: str, *, max_pages: int = 3, **fields) -> list[dict]:
        payload = {"query": query, **fields}
        cf = self._cache_file("filter", payload)
        if cf.exists():
            return json.loads(cf.read_text())
        data: list[dict] = []
        start = None
        for _ in range(max_pages):
            body = dict(payload)
            if start:
                body["start"] = start
            ans = self._post("/filter", body)
            data += ans.get("data", [])
            start = ans.get("next")
            if not start:
                break
        cf.write_text(json.dumps(data))
        return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_openfigi.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/openfigi.py tests/test_openfigi.py
git commit -m "feat(openfigi): cached, rate-limited OpenFIGI client"
```

---

### Task 9: FIGI candidate filtering and acceptance

**Files:**
- Create: `src/delist_detection/figi_resolution.py`
- Test: `tests/test_figi_resolution.py`

**Interfaces:**
- Consumes: `names.names_agree`; `observations.normalize_ticker`.
- Produces:
  - `FigiCandidate(composite: str, name: str, ticker: str, security_type: str, rows: tuple[dict, ...])` (frozen)
  - `us_candidates(rows: Iterable[dict]) -> list[FigiCandidate]` — one per US composite; drops foreign composites and when-issued / 144A / fund-NAV lines
  - `accept(cands: Sequence[FigiCandidate], *, ticker: str, names: Sequence[str], via_cusip: bool) -> FigiCandidate | None`
  - `share_class_from_name(name: str | None) -> str` — `"CLASS C"`, `"SERIES A"` or `"COMMON"`
  - `class_letter(share_class: str | None) -> str | None`
  - `placeholder_id(cik: int, share_class: str | None) -> str`
  - `is_placeholder(sec_id: str) -> bool`
  - `bloomberg_ticker(ticker: str) -> str` — `BF-A` → `BF/A`
  - `filter_query(name: str) -> str` — the name without legal suffixes (OpenFIGI ANDs the words)
  - `security_kind(security_type: str | None, name: str | None = None) -> str` — `"common"`, `"preferred"`, `"fund"`, `"warrant"`, `"unit"`, `"right"` or `"debt"`

Acceptance rules (spec 8.3): a candidate found through a CUSIP is accepted without a name check (the CUSIP identifies the security); with several US composites for one CUSIP, the one whose venue rows carry the observed ticker wins. A candidate found through a ticker or a name search is accepted only when one of its rows carries the observed ticker **and** a name that agrees with a known name; failing that, when exactly one candidate carries the ticker and its main name agrees. Bloomberg renames dead lines to the acquirer (QCOR → `MALLINCKRODT ARD LLC`), which is why the CUSIP route is tried first.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_figi_resolution.py
from delist_detection.figi_resolution import (
    FigiCandidate, accept, bloomberg_ticker, class_letter, filter_query, is_placeholder, placeholder_id,
    security_kind, share_class_from_name, us_candidates,
)


def _row(comp, exch, ticker, name, st="Common Stock", figi=None, st2="Common Stock"):
    return {"figi": figi or (comp if exch == "US" else comp + exch), "compositeFIGI": comp, "exchCode": exch,
            "ticker": ticker, "name": name, "securityType": st, "securityType2": st2}


def test_us_candidates_groups_and_filters():
    rows = [
        _row("BBG000FJLFX8", "US", "AET", "AETNA INC"),
        _row("BBG000FJLFX8", "UN", "AET", "AETNA INC"),
        _row("BBG000FGJDG1", "GR", "2675508D", "AETNA INC"),                    # German composite
        _row("BBG00WI00001", "US", "CHNGV", "CHANGE HEALTHCARE-WHEN ISSUED"),     # when-issued line
        _row("BBG00NAV0001", "US", "XCBHX", "SOME FUND NAV", st="Open-End Fund"),
    ]
    cands = us_candidates(rows)
    assert [c.composite for c in cands] == ["BBG000FJLFX8"]
    assert cands[0].name == "AETNA INC" and cands[0].ticker == "AET" and len(cands[0].rows) == 2


def test_accept_via_cusip_needs_no_name():
    renamed = FigiCandidate("BBG000BPVCR1", "MALLINCKRODT ARD LLC", "QCOR", "Common Stock",
                            (_row("BBG000BPVCR1", "US", "QCOR", "MALLINCKRODT ARD LLC"),))
    assert accept([renamed], ticker="QCOR", names=["QUESTCOR PHARMACEUTICALS INC"], via_cusip=True) is renamed
    assert accept([renamed], ticker="QCOR", names=["QUESTCOR PHARMACEUTICALS INC"], via_cusip=False) is None


def test_accept_via_ticker_uses_venue_rows_and_class():
    a = FigiCandidate("BBG009S39JX6", "ALPHABET INC-CL A", "GOOGL", "Common Stock",
                      (_row("BBG009S39JX6", "US", "GOOGL", "ALPHABET INC-CL A"),))
    c = FigiCandidate("BBG009S3NB30", "ALPHABET INC-CL C", "GOOG", "Common Stock",
                      (_row("BBG009S3NB30", "US", "GOOG", "ALPHABET INC-CL C"),))
    assert accept([a, c], ticker="GOOG", names=["ALPHABET INC"], via_cusip=False) is c
    etf = FigiCandidate("BBG01VRMNFB1", "PROSHARES S&P DYNAMIC BUFFER ETP", "FB", "ETP",
                        (_row("BBG01VRMNFB1", "US", "FB", "PROSHARES S&P DYNAMIC BUFFER ETP", st="ETP"),))
    assert accept([etf], ticker="FB", names=["FACEBOOK INC"], via_cusip=False) is None     # recycled ticker


def test_accept_old_name_on_a_venue_row():
    col = FigiCandidate("BBG000BN1XR3", "COLLINS AEROSPACE", "COL", "Common Stock", (
        _row("BBG000BN1XR3", "US", "COL", "COLLINS AEROSPACE"),
        _row("BBG000BN1XR3", "UN", "COL", "ROCKWELL COLLINS INC"),
    ))
    assert accept([col], ticker="COL", names=["ROCKWELL COLLINS INC"], via_cusip=False) is col


def test_share_class_and_placeholders():
    assert share_class_from_name("ALPHABET INC-CL C") == "CLASS C"
    assert share_class_from_name("META PLATFORMS INC-CLASS A") == "CLASS A"
    assert share_class_from_name("DISCOVERY INC-A") == "CLASS A"
    assert share_class_from_name("LIBERTY BROADBAND-SER C") == "SERIES C"
    assert share_class_from_name("CLOROX CO") == "COMMON"
    assert share_class_from_name(None) == "COMMON"
    assert class_letter("SERIES C") == "C" and class_letter("CLASS A") == "A" and class_letter("COMMON") is None
    assert placeholder_id(1122304, None) == "CIK1122304-COMMON"
    assert placeholder_id(14693, "CLASS A") == "CIK14693-CLASS-A"
    assert is_placeholder("CIK1-COMMON") and not is_placeholder("BBG000FJLFX8")


def test_small_helpers():
    assert bloomberg_ticker("BF-A") == "BF/A"
    assert bloomberg_ticker("aet") == "AET"
    assert filter_query("Aaron's Company, Inc.") == "AARON'S"
    assert filter_query("ALLEGHANY CORP /DE") == "ALLEGHANY"
    assert security_kind("Common Stock") == "common"
    assert security_kind("REIT") == "common"
    assert security_kind("ETP") == "fund"
    assert security_kind("Preferred") == "preferred"
    assert security_kind("", "GOLDMAN SACHS 6.125% NOTES DUE 2060") == "debt"
    assert security_kind(None) == "common"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_figi_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/figi_resolution.py
"""Pure rules for turning OpenFIGI answers into one US composite FIGI.

A composite FIGI groups one security's venue lines within a country; the US
composite is the library's sec_id. Acceptance never relies on Bloomberg's
current name alone, because Bloomberg renames a dead line to its acquirer.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .names import names_agree
from .observations import normalize_ticker

US_EXCH = frozenset({"US", "UN", "UW", "UQ", "UR", "UA", "UP", "UF", "UV", "PQ", "UB", "UC", "UM", "UX",
                     "UD", "UT", "UL", "UI", "UO", "UU", "VJ", "VK", "VY"})
_SIDELINE = re.compile(r"WHEN[- ]ISSUED|\bW/I\b|\b144A\b|\bNAV\b", re.I)
_FUND_TYPES = {"open-end fund", "mutual fund", "money market"}
_LEGAL = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "LLC", "PLC",
          "DE", "NEW", "THE", "HOLDINGS", "HOLDING", "GROUP", "LP", "L", "P", "SA", "NV", "AG"}


@dataclass(frozen=True)
class FigiCandidate:
    composite: str
    name: str
    ticker: str
    security_type: str
    rows: tuple[dict, ...]


def _is_sideline(r: dict) -> bool:
    ticker = (r.get("ticker") or "").upper()
    return (bool(_SIDELINE.search(r.get("name") or ""))
            or (r.get("securityType") or "").lower() in _FUND_TYPES
            or (r.get("securityType2") or "").lower() in {"mutual fund", "when issued"}
            or ticker.endswith((" WI", "-W", "/WI", " W/I")))


def us_candidates(rows: Iterable[dict]) -> list[FigiCandidate]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        comp = r.get("compositeFIGI")
        if comp:
            groups.setdefault(comp, []).append(r)
    out: list[FigiCandidate] = []
    for comp, rs in groups.items():
        us = next((r for r in rs if r.get("exchCode") == "US"), None)
        if us is None and not any(r.get("exchCode") in US_EXCH for r in rs):
            continue
        rep = us or rs[0]
        if _is_sideline(rep):
            continue
        out.append(FigiCandidate(comp, rep.get("name") or "", normalize_ticker(rep.get("ticker") or ""),
                                 rep.get("securityType") or "", tuple(rs)))
    return out


def _carries(c: FigiCandidate, ticker: str) -> bool:
    return any(normalize_ticker(r.get("ticker") or "") == ticker for r in c.rows)


def accept(cands: Sequence[FigiCandidate], *, ticker: str, names: Sequence[str],
           via_cusip: bool) -> FigiCandidate | None:
    t = normalize_ticker(ticker)
    names = [n for n in names if n]
    if via_cusip:
        if len(cands) == 1:
            return cands[0]
        with_t = [c for c in cands if _carries(c, t)]
        return with_t[0] if len(with_t) == 1 else None
    exact = [c for c in cands
             if any(normalize_ticker(r.get("ticker") or "") == t
                    and any(names_agree(r.get("name") or "", n) for n in names) for r in c.rows)]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    plain = [c for c in cands if _carries(c, t) and any(names_agree(c.name, n) for n in names)]
    return plain[0] if len(plain) == 1 else None


def share_class_from_name(name: str | None) -> str:
    s = (name or "").upper().strip()
    m = re.search(r"\bCL(?:ASS)?\s*-?\s*([A-Z])\b", s)
    if m:
        return f"CLASS {m.group(1)}"
    m = re.search(r"\bSER(?:IES)?\s*-?\s*([A-Z0-9])\b", s)
    if m:
        return f"SERIES {m.group(1)}"
    m = re.search(r"-([A-Z])$", s)
    if m:
        return f"CLASS {m.group(1)}"
    return "COMMON"


def class_letter(share_class: str | None) -> str | None:
    m = re.fullmatch(r"(?:CLASS|SERIES)\s+([A-Z0-9])", (share_class or "").upper().strip())
    return m.group(1) if m else None


def placeholder_id(cik: int, share_class: str | None) -> str:
    cls = re.sub(r"[^A-Z0-9]+", "-", (share_class or "COMMON").upper()).strip("-") or "COMMON"
    return f"CIK{int(cik)}-{cls}"


def is_placeholder(sec_id: str) -> bool:
    return sec_id.startswith("CIK")


def bloomberg_ticker(ticker: str) -> str:
    return normalize_ticker(ticker).replace("-", "/")


def filter_query(name: str) -> str:
    words = re.findall(r"[A-Z0-9&']+", (name or "").upper())
    return " ".join(w for w in words if w not in _LEGAL)


def security_kind(security_type: str | None, name: str | None = None) -> str:
    st = (security_type or "").lower()
    nm = (name or "").upper()
    if "preferred" in st or " PREFERRED" in nm:
        return "preferred"
    if st in {"etp", "closed-end fund", "open-end fund", "unit inv tst", "mutual fund"} or "fund" in st \
            or re.search(r"\bETF\b|\bETN\b", nm):
        return "fund"
    if "warrant" in st or re.search(r"\bWARRANTS?\b", nm):
        return "warrant"
    if "right" in st or re.search(r"\bRIGHTS\b", nm):
        return "right"
    if st.startswith("unit") or re.search(r"\bUNITS\b", nm):
        return "unit"
    if any(k in st for k in ("note", "bond", "debt")) or re.search(r"\bNOTES? DUE\b|\bDEBENTURES?\b", nm):
        return "debt"
    return "common"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_figi_resolution.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/figi_resolution.py tests/test_figi_resolution.py
git commit -m "feat(figi): US composite candidates, acceptance rules, share class"
```

---

### Task 10: Form 25 parsing, class matching and notice dates

**Files:**
- Create: `src/delist_detection/form25.py`
- Test: `tests/test_form25.py`
- Create fixtures: `tests/fixtures/form25/aet_25nse.txt`, `tests/fixtures/form25/rsh_25nse.txt`, `tests/fixtures/form25/save_25nse.txt`, `tests/fixtures/form25/discovery_series_c.txt`

**Interfaces:**
- Consumes: `edgar._strip_html`; `edgar.EdgarSubmission`; `trading_calendar.previous_trading_day`; `figi_resolution.class_letter`.
- Produces:
  - `FORM25_FORMS = frozenset({"25", "25-NSE", "25/A", "25-NSE/A"})`
  - `MAJOR_EXCHANGES = frozenset({"NYSE", "NYSE AMERICAN", "NASDAQ", "NYSE ARCA", "CBOE BZX"})`
  - `REGIONAL_EXCHANGES = frozenset({"CHICAGO", "NSX", "PACIFIC", "BOSTON", "PHLX"})`
  - `exchange_label(text: str) -> str` — first exchange named, canonical label, `""` if none
  - `exchanges_named(text: str) -> set[str]` — every exchange named
  - `Form25(accession: str, form: str, filing_date: str, exchange: str, class_text: str, rule: str, notice_text: str)` (frozen)
  - `parse_form25(raw: str, *, accession: str, form: str, filing_date: str) -> Form25`
  - `list_form25(filings: Iterable[EdgarSubmission]) -> list[EdgarSubmission]` (sorted by filing date)
  - `class_kind(class_text: str) -> str` — `"common"`, `"preferred"`, `"unit"`, `"warrant"`, `"right"`, `"fund"`, `"debt"` or `"other"`
  - `class_label(class_text: str) -> str | None` — `"CLASS A"` / `"SERIES C"`
  - `SecurityRef(sec_id: str, share_class: str, kind: str)` (frozen)
  - `match_security(f25: Form25, refs: Sequence[SecurityRef]) -> tuple[str | None, str]` — `(sec_id or None, reason)`
  - `notice_last_trade(f25: Form25) -> tuple[date | None, str]` — `(day, kind)`; kinds `notice_a`, `notice_close`, `notice_open`, `notice_nasdaq`, `notice_b_unconfirmed`, or `(None, "")`
  - `effective_date(filing_date: str) -> str` — filing date + 10 days (Rule 12d2-2(d)(1))

Facts (checked 2026-09-23): the complete submission text of AET's 25-NSE (`0000876661-18-001269`) contains `<TYPE>25-NSE` with `primary_doc.xml` (`<notificationOfRemoval>` with `<exchange><cik>…</cik><entityName>NEW YORK STOCK EXCHANGE LLC</entityName></exchange>`, `<issuer>…</issuer>`, `<descriptionClassSecurity>Common Stock</descriptionClassSecurity>`, `<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision>`) and `<TYPE>EX-99.25` with `ruleprovisionnotice.htm` whose text says "this security was suspended from trading on November 29, 2018." NYSE-family `(a)` notices name the first day *not* traded. RSH's `(b)` notice (`0000876661-15-000132`): "NYSE Regulation, on February 2, 2015, determined that the Common Stock of the Company should be suspended immediately from trading … an announcement was made on the 'ticker' of the Exchange immediately and at the close of the trading session on February 2, 2015" — RSH traded that day. SAVE's `(b)` notice (`0000876661-24-001142`): "On November 18, 2024, the Exchange determined … should be suspended from trading", no time of day — SAVE did not trade that day. Nasdaq `(a)(3)` notices are usually empty (ALTR). Discovery's three 2022 25-NSEs say "Series A/B/C Common Stock".

- [ ] **Step 1: Create the fixtures**

Fetch the real complete-submission files once (network, run from the worktree root) and commit them:

```bash
UA="$(PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -c 'from delist_detection.edgar import resolve_user_agent as r; print(r())')"
mkdir -p tests/fixtures/form25
curl -s -A "$UA" https://www.sec.gov/Archives/edgar/data/1122304/000087666118001269/0000876661-18-001269.txt -o tests/fixtures/form25/aet_25nse.txt
sleep 0.3
curl -s -A "$UA" https://www.sec.gov/Archives/edgar/data/96289/000087666115000132/0000876661-15-000132.txt -o tests/fixtures/form25/rsh_25nse.txt
sleep 0.3
curl -s -A "$UA" https://www.sec.gov/Archives/edgar/data/1498710/000087666124001142/0000876661-24-001142.txt -o tests/fixtures/form25/save_25nse.txt
sleep 0.3
curl -s -A "$UA" https://www.sec.gov/Archives/edgar/data/1437107/000135445722000231/0001354457-22-000231.txt -o tests/fixtures/form25/discovery_series_c.txt
grep -l "descriptionClassSecurity" tests/fixtures/form25/*.txt | wc -l    # expect 4
```

If a download is not a filing (e.g. an HTML error page), check the accession on EDGAR and retry; the sandbox needs `allowed_domains: ["www.sec.gov"]`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_form25.py
from datetime import date
from pathlib import Path

from delist_detection.edgar import EdgarSubmission
from delist_detection.form25 import (
    Form25, SecurityRef, class_kind, class_label, effective_date, exchange_label, exchanges_named,
    list_form25, match_security, notice_last_trade, parse_form25,
)

FIX = Path(__file__).parent / "fixtures" / "form25"


def _load(name, accession, filing_date):
    return parse_form25((FIX / name).read_text(encoding="utf-8", errors="replace"),
                        accession=accession, form="25-NSE", filing_date=filing_date)


def test_parse_aet():
    f = _load("aet_25nse.txt", "0000876661-18-001269", "2018-11-29")
    assert f.exchange == "NYSE"
    assert f.class_text == "Common Stock"
    assert f.rule.endswith("(a)(3)")
    assert "suspended from trading on November 29, 2018" in f.notice_text
    assert notice_last_trade(f) == (date(2018, 11, 28), "notice_a")


def test_notice_dates_for_involuntary_removals():
    rsh = _load("rsh_25nse.txt", "0000876661-15-000132", "2015-03-20")
    assert notice_last_trade(rsh) == (date(2015, 2, 2), "notice_close")
    save = _load("save_25nse.txt", "0000876661-24-001142", "2024-12-05")
    assert notice_last_trade(save) == (date(2024, 11, 18), "notice_b_unconfirmed")


def test_notice_text_patterns_synthetic():
    mk = lambda text, rule="17 CFR 240.12d2-2(b)": Form25("a", "25-NSE", "2016-05-20", "NASDAQ", "Common Stock",
                                                        rule, text)
    assert notice_last_trade(mk("trading in the Companys securities would be suspended on May 19, 2016")) \
        == (date(2016, 5, 18), "notice_nasdaq")
    assert notice_last_trade(mk("suspended prior to the opening of trading on January 2, 2009")) \
        == (date(2008, 12, 31), "notice_open")
    assert notice_last_trade(mk("")) == (None, "")


def test_discovery_series_c():
    f = _load("discovery_series_c.txt", "0001354457-22-000231", "2022-04-08")
    assert f.exchange == "NASDAQ"
    assert class_label(f.class_text) == "SERIES C"
    refs = [SecurityRef("BBG_A", "CLASS A", "common"), SecurityRef("BBG_B", "CLASS B", "common"),
            SecurityRef("BBG_C", "CLASS C", "common")]
    assert match_security(f, refs) == ("BBG_C", "class C")


def test_match_rules():
    common = Form25("a", "25-NSE", "2018-11-29", "NYSE", "Common Stock", "", "")
    pref = Form25("b", "25-NSE", "2018-11-29", "NYSE", "6.375% Series A Preferred Stock", "", "")
    single = [SecurityRef("BBG1", "COMMON", "common")]
    assert match_security(common, single) == ("BBG1", "only security of its kind")
    assert match_security(pref, single) == (None, "no observed preferred security")
    two = [SecurityRef("A", "CLASS A", "common"), SecurityRef("C", "CLASS C", "common")]
    assert match_security(common, two) == (None, "ambiguous class")


def test_class_kind():
    assert class_kind("Common Stock, $.01 par value, and Associated Preferred Stock Purchase Rights") == "common"
    assert class_kind("Class A Common Stock") == "common"
    assert class_kind("Ordinary Shares") == "common"
    assert class_kind("American Depositary Shares") == "common"
    assert class_kind("Depositary Shares, each representing 1/1000th of a share of 6.00% Preferred Stock") == "preferred"
    assert class_kind("Units, each consisting of one share of Class A Common Stock and one-half of one Warrant") == "unit"
    assert class_kind("Warrants to purchase Common Stock") == "warrant"
    assert class_kind("6.125% Notes due 2060") == "debt"
    assert class_kind("iShares MSCI Brazil ETF") == "fund"
    assert class_kind("") == "other"


def test_exchange_labels():
    assert exchange_label("NEW YORK STOCK EXCHANGE LLC") == "NYSE"
    assert exchange_label("NYSE American LLC") == "NYSE AMERICAN"
    assert exchange_label("NYSE MKT LLC") == "NYSE AMERICAN"
    assert exchange_label("NYSE Arca, Inc.") == "NYSE ARCA"
    assert exchange_label("The Nasdaq Stock Market LLC") == "NASDAQ"
    assert exchange_label("NASDAQ OMX BX, Inc.") == "BOSTON"
    assert exchange_label("Chicago Stock Exchange, Inc.") == "CHICAGO"
    assert exchange_label("Cboe BZX Exchange, Inc.") == "CBOE BZX"
    assert exchange_label("Pacific Exchange") == "PACIFIC"
    assert exchange_label("nothing here") == ""
    assert exchanges_named("New York Stock Exchange; Chicago Stock Exchange") == {"NYSE", "CHICAGO"}
    assert exchanges_named("NYSE Arca") == {"NYSE ARCA"}
    assert exchanges_named("The Nasdaq Stock Market LLC") == {"NASDAQ"}


def test_list_form25_and_effective_date():
    subs = [EdgarSubmission("x2", "25-NSE", "2020-01-02", "", "", "p"),
            EdgarSubmission("x1", "25", "2019-01-02", "", "", "p"),
            EdgarSubmission("x3", "8-K", "2019-01-02", "", "3.01", "p")]
    assert [s.accession for s in list_form25(subs)] == ["x1", "x2"]
    assert effective_date("2018-11-29") == "2018-12-09"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_form25.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write the implementation**

```python
# src/delist_detection/form25.py
"""Form 25: the SEC notice that a class of securities is removed from an exchange.

The XML primary document names the exchange, the issuer, the class (free text)
and the rule; the exchange's EX-99.25 notice often dates the suspension. A Form
25 names no ticker or CUSIP, so it is matched to one security by its class text.
"""
from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .edgar import EdgarSubmission, _strip_html
from .figi_resolution import class_letter
from .trading_calendar import previous_trading_day

FORM25_FORMS = frozenset({"25", "25-NSE", "25/A", "25-NSE/A"})
MAJOR_EXCHANGES = frozenset({"NYSE", "NYSE AMERICAN", "NASDAQ", "NYSE ARCA", "CBOE BZX"})
REGIONAL_EXCHANGES = frozenset({"CHICAGO", "NSX", "PACIFIC", "BOSTON", "PHLX"})

# Order matters: the specific names before the bare NYSE / NASDAQ patterns.
_EXCHANGES: list[tuple[str, str]] = [
    ("NYSE AMERICAN", r"NYSE\s*AMERICAN|NYSE\s*MKT|NYSE\s*AMEX|AMERICAN STOCK EXCHANGE|\bAMEX\b"),
    ("NYSE ARCA", r"NYSE\s*ARCA|ARCHIPELAGO"),
    ("CHICAGO", r"CHICAGO STOCK EXCHANGE|NYSE\s*CHICAGO"),
    ("NSX", r"NATIONAL STOCK EXCHANGE|NYSE\s*NATIONAL"),
    ("PACIFIC", r"PACIFIC (?:STOCK )?EXCHANGE"),
    ("BOSTON", r"BOSTON STOCK EXCHANGE|NASDAQ\s*(?:OMX\s*)?BX"),
    ("PHLX", r"PHILADELPHIA STOCK EXCHANGE|NASDAQ\s*(?:OMX\s*)?PHLX|\bPHLX\b"),
    ("CBOE BZX", r"CBOE\s*BZX|\bBATS\b"),
    ("NASDAQ", r"NASDAQ"),
    ("NYSE", r"NEW YORK STOCK EXCHANGE|\bNYSE\b"),
]
_NYSE_BARE = r"NEW YORK STOCK EXCHANGE|\bNYSE\b(?!\s*(?:ARCA|AMERICAN|MKT|AMEX|CHICAGO|NATIONAL))"
_NASDAQ_BARE = r"NASDAQ(?!\s*(?:OMX\s*)?(?:BX|PHLX))"

_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
_DATE = rf"((?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})"


def exchange_label(text: str) -> str:
    for label, pat in _EXCHANGES:
        if re.search(pat, text or "", re.I):
            return label
    return ""


def exchanges_named(text: str) -> set[str]:
    t = text or ""
    found = {label for label, pat in _EXCHANGES if re.search(pat, t, re.I)}
    if "NYSE" in found and not re.search(_NYSE_BARE, t, re.I):
        found.discard("NYSE")
    if "NASDAQ" in found and not re.search(_NASDAQ_BARE, t, re.I):
        found.discard("NASDAQ")
    return found


@dataclass(frozen=True)
class Form25:
    accession: str
    form: str
    filing_date: str
    exchange: str
    class_text: str
    rule: str
    notice_text: str


def _tag(raw: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", raw, re.S | re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def _notice(raw: str) -> str:
    m = re.search(r"<TYPE>EX-99\.25(.*?)(?=<TYPE>|</DOCUMENT>|\Z)", raw, re.S | re.I)
    return _strip_html(m.group(1)) if m else ""


def parse_form25(raw: str, *, accession: str, form: str, filing_date: str) -> Form25:
    exch_block = re.search(r"<exchange>(.*?)</exchange>", raw, re.S | re.I)
    exch_name = _tag(exch_block.group(1), "entityName") if exch_block else ""
    class_text = _tag(raw, "descriptionClassSecurity")
    rule = _tag(raw, "ruleProvision")
    if not exch_name:                         # a text Form 25 without the XML document
        text = _strip_html(raw)
        exch_name = exchange_label(text[:4000])
        if not class_text:
            m = re.search(r"(?:class|title) of (?:the )?securit(?:y|ies)[^:]{0,40}:\s*(.{3,120}?)(?:\s{2,}|\.|$)",
                          text, re.I)
            class_text = m.group(1).strip() if m else ""
    return Form25(accession, form, filing_date, exchange_label(exch_name) or exch_name.upper(),
                  class_text, rule, _notice(raw))


def list_form25(filings: Iterable[EdgarSubmission]) -> list[EdgarSubmission]:
    return sorted((f for f in filings if f.form in FORM25_FORMS), key=lambda f: (f.filing_date, f.accession))


def class_kind(class_text: str) -> str:
    s = (class_text or "").upper().strip()
    if not s:
        return "other"
    if re.match(r"^\W*(?:CLASS [A-Z] |SERIES [A-Z] )?(?:COMMON|ORDINARY)", s):
        return "common"
    if re.search(r"PREFERRED|DEPOSITARY SHARES?,? EACH REPRESENTING", s):
        return "preferred"
    if re.search(r"^\W*UNITS?\b", s):
        return "unit"
    if re.search(r"^\W*WARRANTS?\b", s):
        return "warrant"
    if re.search(r"^\W*(?:[A-Z ]+ )?RIGHTS?\b", s) and "COMMON" not in s:
        return "right"
    if re.search(r"\bETF\b|\bETN\b|EXCHANGE[- ]TRADED|\bFUND\b|INDEX SHARES", s):
        return "fund"
    if re.search(r"\bNOTES?\b|DEBENTURES?|\bBONDS?\b|\bDUE\s+\d{4}\b", s):
        return "debt"
    if re.search(r"COMMON|ORDINARY|CLASS [A-Z]\b|SERIES [A-Z]\b|SHARES OF BENEFICIAL INTEREST|CAPITAL STOCK"
                 r"|AMERICAN DEPOSITARY|\bADS\b|\bSTOCK\b|\bSHARES\b", s):
        return "common"
    return "other"


def class_label(class_text: str) -> str | None:
    s = (class_text or "").upper()
    m = re.search(r"\bCLASS\s+([A-Z])\b", s)
    if m:
        return f"CLASS {m.group(1)}"
    m = re.search(r"\bSERIES\s+([A-Z])\b", s)
    if m:
        return f"SERIES {m.group(1)}"
    return None


@dataclass(frozen=True)
class SecurityRef:
    sec_id: str
    share_class: str
    kind: str


def match_security(f25: Form25, refs: Sequence[SecurityRef]) -> tuple[str | None, str]:
    kind = class_kind(f25.class_text)
    same = [r for r in refs if r.kind == kind or (kind == "other" and r.kind == "common")]
    if not same:
        return None, f"no observed {kind} security"
    if len(same) == 1:
        return same[0].sec_id, "only security of its kind"
    letter = class_letter(class_label(f25.class_text))
    if letter:
        hits = [r for r in same if class_letter(r.share_class) == letter]
        if len(hits) == 1:
            return hits[0].sec_id, f"class {letter}"
    return None, "ambiguous class"


def _day(s: str) -> date:
    return datetime.strptime(re.sub(r"\s+", " ", s), "%B %d, %Y").date()


def notice_last_trade(f25: Form25) -> tuple[date | None, str]:
    t = re.sub(r"\s+", " ", f25.notice_text or "")
    if not t:
        return None, ""
    involuntary = "(b)" in (f25.rule or "")
    m = re.search(rf"suspended from trading on {_DATE}", t, re.I)
    if m and not involuntary:
        return previous_trading_day(_day(m.group(1))), "notice_a"
    m = re.search(rf"(?:at|after) the close(?: of (?:the )?(?:trading|market)(?: session)?)? on {_DATE}", t, re.I)
    if m:
        return _day(m.group(1)), "notice_close"
    m = re.search(rf"(?:prior to|before) the (?:open|opening)(?: of (?:the )?trading)? on {_DATE}", t, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "notice_open"
    m = re.search(rf"would be suspended on {_DATE}", t, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "notice_nasdaq"
    # "On November 18, 2024, the Exchange determined that the common stock of Spirit Airlines, Inc.
    # ... should be suspended": allow periods inside the span (company names end in "Inc.").
    m = re.search(rf"on {_DATE},?.{{0,120}}?determined.{{0,400}}?suspended", t, re.I)
    if m:
        return _day(m.group(1)), "notice_b_unconfirmed"
    m = re.search(rf"suspended from trading on {_DATE}", t, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "notice_a"
    return None, ""


def effective_date(filing_date: str) -> str:
    return (date.fromisoformat(filing_date) + timedelta(days=10)).isoformat()
```

Rule checks for the fixtures: RSH's text contains "determined … should be suspended" *and* "at the close of the trading session on February 2, 2015"; the `notice_close` pattern is tested before the `determined` pattern, so RSH gives `(2015-02-02, "notice_close")`. SAVE has only the `determined` sentence, so it gives `notice_b_unconfirmed` and step 3 of the last-trade decision (Task 11) replaces it with MIDAS's 2024-11-15. If a fixture's wording differs from the facts above, adjust the pattern (not the test expectation) and note the real wording in a comment.

- [ ] **Step 5: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_form25.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/form25.py tests/test_form25.py tests/fixtures/form25
git commit -m "feat(form25): parse Form 25, match class to security, date the notice"
```

---

### Task 11: Last trade date from 8-K text and the decision rule

**Files:**
- Create: `src/delist_detection/last_trade.py`
- Test: `tests/test_last_trade.py`

**Interfaces:**
- Consumes: `evidence.item_text(text, item, width)` (existing); `trading_calendar.previous_trading_day`.
- Produces:
  - `eightk_last_trade(text: str) -> tuple[date | None, str]` — kinds `8k_open`, `8k_open_closing`, `8k_close`, `8k_close_closing`, `8k_last_day`, `8k_suspended_unconfirmed`, or `(None, "")`
  - `LastTrade(day: date | None, source: str, flags: tuple[str, ...])` (frozen); `source` ∈ `midas`, `nasdaq_halt`, `ex99_notice`, `8k_301`, `""`
  - `decide_last_trade(*, notice: tuple[date | None, str], eightk: tuple[date | None, str], midas: date | None, halt: date | None) -> LastTrade`

Decision (spec 8.8 and D20): MIDAS (exchange volume) wins when present, then the Nasdaq halt, then a confirmed notice date, then a confirmed 8-K date, then an unconfirmed one (flag `last_trade_date_unconfirmed`). A text date that disagrees with the chosen date adds `last_trade_date_conflict`. No date at all gives `LastTrade(None, "", ("no_last_trade_date",))`. The 8-K wording can be a day off (ALTR's 8-K says "at the close of the market on March 26, 2025"; Nasdaq halted it on the evening of March 25).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_last_trade.py
from datetime import date

from delist_detection.last_trade import LastTrade, decide_last_trade, eightk_last_trade


def _k(item301: str, extra: str = "") -> str:
    return f"Item 2.01 Completion of Acquisition. {extra} Item 3.01 Notice of Delisting. {item301} Item 5.01 Changes."


def test_eightk_phrases():
    assert eightk_last_trade(_k("requested that trading be suspended prior to the opening of trading on "
                                "November 29, 2018")) == (date(2018, 11, 28), "8k_open")
    assert eightk_last_trade(_k("requested that Nasdaq suspend trading at the close of the market on "
                                "March 26, 2025")) == (date(2025, 3, 26), "8k_close")
    assert eightk_last_trade(_k("Trading was suspended immediately after the close on February 2, 2015")) \
        == (date(2015, 2, 2), "8k_close")
    assert eightk_last_trade(_k("requested a halt prior to the open of trading on the Closing Date",
                                extra="On October 13, 2023 (the “Closing Date”), the merger closed.")) \
        == (date(2023, 10, 12), "8k_open_closing")
    assert eightk_last_trade(_k("trading in the Common Stock was suspended immediately on November 18, 2024")) \
        == (date(2024, 11, 18), "8k_suspended_unconfirmed")
    assert eightk_last_trade(_k("The last day of trading was January 5, 2017.")) == (date(2017, 1, 5), "8k_last_day")
    assert eightk_last_trade(_k("nothing dated here")) == (None, "")
    assert eightk_last_trade("") == (None, "")


def test_decide_prefers_midas_and_flags_conflict():
    lt = decide_last_trade(notice=(None, ""), eightk=(date(2025, 3, 26), "8k_close"),
                           midas=date(2025, 3, 25), halt=date(2025, 3, 25))
    assert lt == LastTrade(date(2025, 3, 25), "midas", ("last_trade_date_conflict",))


def test_decide_halt_then_text():
    assert decide_last_trade(notice=(None, ""), eightk=(None, ""), midas=None, halt=date(2015, 12, 24)) \
        == LastTrade(date(2015, 12, 24), "nasdaq_halt", ())
    assert decide_last_trade(notice=(date(2018, 11, 28), "notice_a"), eightk=(date(2018, 11, 28), "8k_open"),
                             midas=None, halt=None) == LastTrade(date(2018, 11, 28), "ex99_notice", ())
    assert decide_last_trade(notice=(None, ""), eightk=(date(2018, 11, 28), "8k_open"), midas=None, halt=None) \
        == LastTrade(date(2018, 11, 28), "8k_301", ())


def test_decide_unconfirmed_and_missing():
    lt = decide_last_trade(notice=(date(2024, 11, 18), "notice_b_unconfirmed"), eightk=(None, ""),
                           midas=None, halt=None)
    assert lt == LastTrade(date(2024, 11, 18), "ex99_notice", ("last_trade_date_unconfirmed",))
    assert decide_last_trade(notice=(None, ""), eightk=(None, ""), midas=None, halt=None) \
        == LastTrade(None, "", ("no_last_trade_date",))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_last_trade.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/last_trade.py
"""The last day a security traded on its exchange.

No rule requires an issuer to state it, so it is read from several places and
cross-checked: the exchange's Form 25 notice (form25.notice_last_trade), the
closing 8-K's Item 3.01 text (here), SEC MIDAS exchange volume and Nasdaq's
code-D halts. Measured volume beats wording, and wording that disagrees with it
is flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .evidence import item_text
from .trading_calendar import previous_trading_day

_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
_DATE = rf"((?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})"
_OPEN = r"(?:prior to|before) (?:the )?(?:open|opening)(?: of (?:the )?(?:trading|market))?"
_CLOSE = r"(?:at|after|following) the close(?: of (?:the )?(?:trading|market|business)(?: day| session)?)?"


def _day(s: str) -> date:
    return datetime.strptime(re.sub(r"\s+", " ", s), "%B %d, %Y").date()


def _closing_date(text: str) -> date | None:
    m = re.search(rf"{_DATE}\s*\((?:the\s*)?[“\"']?Closing Date", text, re.I)
    return _day(m.group(1)) if m else None


def eightk_last_trade(text: str) -> tuple[date | None, str]:
    if not text:
        return None, ""
    flat = re.sub(r"\s+", " ", text)
    section = re.sub(r"\s+", " ", item_text(text, "3.01", width=3000) or "") or flat
    m = re.search(rf"{_OPEN}(?: on)? {_DATE}", section, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "8k_open"
    if re.search(rf"{_OPEN}[^.]{{0,40}}?Closing Date", section, re.I):
        cd = _closing_date(flat)
        if cd:
            return previous_trading_day(cd), "8k_open_closing"
    m = re.search(rf"{_CLOSE} on {_DATE}", section, re.I)
    if m:
        return _day(m.group(1)), "8k_close"
    if re.search(rf"{_CLOSE}[^.]{{0,40}}?Closing Date", section, re.I):
        cd = _closing_date(flat)
        if cd:
            return cd, "8k_close_closing"
    m = re.search(rf"last (?:day of trading|trading day)[^.]{{0,40}}?(?:was|will be|is) {_DATE}", section, re.I)
    if m:
        return _day(m.group(1)), "8k_last_day"
    m = re.search(rf"suspended (?:immediately )?on {_DATE}", section, re.I)
    if m:
        return _day(m.group(1)), "8k_suspended_unconfirmed"
    return None, ""


@dataclass(frozen=True)
class LastTrade:
    day: date | None
    source: str
    flags: tuple[str, ...]


def _confirmed(kind: str) -> bool:
    return bool(kind) and not kind.endswith("unconfirmed")


def decide_last_trade(*, notice: tuple[date | None, str], eightk: tuple[date | None, str],
                      midas: date | None, halt: date | None) -> LastTrade:
    texts = [d for d, _ in (notice, eightk) if d is not None]

    def pick(day: date, source: str, extra: tuple[str, ...] = ()) -> LastTrade:
        conflict = ("last_trade_date_conflict",) if any(d != day for d in texts) else ()
        return LastTrade(day, source, extra + conflict)

    if midas is not None:
        return pick(midas, "midas")
    if halt is not None:
        return pick(halt, "nasdaq_halt")
    (n_day, n_kind), (e_day, e_kind) = notice, eightk
    if n_day and _confirmed(n_kind):
        return pick(n_day, "ex99_notice")
    if e_day and _confirmed(e_kind):
        return pick(e_day, "8k_301")
    if n_day:
        return pick(n_day, "ex99_notice", ("last_trade_date_unconfirmed",))
    if e_day:
        return pick(e_day, "8k_301", ("last_trade_date_unconfirmed",))
    return LastTrade(None, "", ("no_last_trade_date",))
```

Check `item_text` in `src/delist_detection/evidence.py` (line ~153): `item_text(text, item, width=1500) -> str` returns the text following the "Item 3.01" heading. If it returns `""` for a text without the heading, the code falls back to the whole text, as the `_k("nothing dated here")` and phrase tests need.

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_last_trade.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/last_trade.py tests/test_last_trade.py
git commit -m "feat(last-trade): 8-K 3.01 date phrases and the source-priority decision"
```

---

### Task 12: Classifier entry point for a known security and Form 25

**Files:**
- Modify: `src/delist_detection/classifier.py` (`DelistRecord` fields; split `classify_ticker`; add `classify_event`)
- Test: `tests/test_classify_event.py`
- Modify: `tests/test_golden_events.py` (add the `classify_event` golden test)

**Interfaces:**
- Consumes: `ticker_resolver.TickerResolution(ticker, cik, name, source)` (existing).
- Produces:
  - `DelistRecord` gains three optional fields after `evidence`: `sec_id: str | None = None`, `delist_date: str | None = None`, `successor_sec_id: str | None = None`.
  - `NON_EQUITY_KINDS = frozenset({"preferred", "debt", "warrant", "unit", "right", "fund"})`
  - `DelistClassifier.classify_event(*, ticker: str, cik: int, anchor_date: str, name: str | None = None, expected_name: str | None = None, kind: str = "common", form25: EdgarSubmission | None = None) -> DelistRecord`
  - `DelistClassifier._classify_resolved(ticker, resolution, observed_delist_date, *, expected_name, delist_filing_override=None) -> DelistRecord` (private; shared by both entry points)

`classify_event` runs exactly the same rule chain as `classify_ticker` (D5: rules unchanged). The differences are only where the inputs come from: the CIK is already known (resolution source `"security_master"`), the Form 25 is the one the delisting finder matched (when given), the anchor date is the last trade date (or the Form 25 date), and the non-equity short-circuit uses the security's kind instead of Alpha Vantage.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_classify_event.py
from delist_detection.classifier import DelistClassifier, DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.ticker_resolver import TickerResolver


def _clf(fake_edgar):
    return DelistClassifier(fake_edgar, TickerResolver(fake_edgar))


def test_event_with_known_form25_matches_classify_ticker(fake_edgar):
    clf = _clf(fake_edgar)
    f25 = next(f for f in fake_edgar.recent_filings(1701732) if f.form == "25-NSE")
    ev = clf.classify_event(ticker="ALTR", cik=1701732, anchor_date="2025-03-25",
                            name="Altair Engineering Inc.", form25=f25)
    old = clf.classify_ticker("ALTR", "2025-03-26")
    assert ev.bucket is old.bucket is CrspBucket.MERGER
    assert ev.crsp_code == old.crsp_code
    assert ev.cik == 1701732
    assert ev.observed_delist_date == "2025-03-25"
    assert ev.evidence["delist_filing"]["accession"] == f25.accession
    assert ev.evidence["resolution_source"] == "security_master"


def test_event_without_form25_picks_one_like_classify_ticker(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="BAD", cik=999001, anchor_date="2023-05-10")
    assert ev.bucket is CrspBucket.COMPLIANCE_FAILURE and ev.crsp_code == 570


def test_event_non_equity_kind_is_expiration(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="GSF", cik=886982, anchor_date="2021-01-04", kind="debt")
    assert ev.bucket is CrspBucket.EXPIRATION and ev.crsp_code == 600 and ev.cik == 886982
    assert ev.evidence["asset_type"] == "debt"


def test_event_name_mismatch_is_flagged(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="ALTR", cik=1701732, anchor_date="2025-03-25",
                                         expected_name="Monsanto Company")
    assert "member_name_mismatch" in ev.evidence["flags"]


def test_delist_record_new_fields_default_none():
    r = DelistRecord("X", 1, "2020-01-01", 231, CrspBucket.MERGER, "high", "r")
    assert r.sec_id is None and r.delist_date is None and r.successor_sec_id is None
    assert r.to_dict()["sec_id"] is None
```

Append to `tests/test_golden_events.py`:

```python
from datetime import date


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_golden_classify_event_matches_classify_ticker(case, monkeypatch):
    """classify_event, given the CIK and the Form 25 classify_ticker anchors on, lands
    in the same bucket with the same code: the new entry point reuses the rules."""
    edgar = GoldenEdgar(case)
    patch_efts(monkeypatch, case)
    resolver = TickerResolver(edgar, manual_overrides=GOLDEN_MANUAL,
                              member_names=lambda t, d=None: case.member_name)
    clf = DelistClassifier(edgar, resolver)
    old = clf.classify_ticker(case.ticker, case.observed_delist_date)
    assert old.cik is not None
    f25, _ = clf._pick_delist_filing(edgar.recent_filings(old.cik), date.fromisoformat(case.observed_delist_date),
                                     old.cik)
    new = clf.classify_event(ticker=case.ticker, cik=old.cik, anchor_date=case.observed_delist_date,
                             name=old.evidence.get("name"), expected_name=case.member_name, form25=f25)
    assert new.bucket is old.bucket, (old.reason, new.reason)
    assert new.crsp_code == old.crsp_code
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_classify_event.py tests/test_golden_events.py -v`
Expected: FAIL with `AttributeError: 'DelistClassifier' object has no attribute 'classify_event'` and `TypeError` on the new `DelistRecord` fields.

- [ ] **Step 3: Write the implementation**

In `src/delist_detection/classifier.py`:

1. Add the three fields to `DelistRecord`, after `evidence`:

```python
    evidence: dict = field(default_factory=dict)
    sec_id: str | None = None                 # the security's US composite FIGI (or placeholder)
    delist_date: str | None = None            # Form 25 effective date (filing + 10 days) or fallback filing date
    successor_sec_id: str | None = None       # for exchange_transfer: the security a holder keeps
```

2. Add the constant near the other module constants:

```python
NON_EQUITY_KINDS = frozenset({"preferred", "debt", "warrant", "unit", "right", "fund"})
```

3. Split `classify_ticker`. Everything in the current body **after** the `if resolution.cik is None: return DelistRecord(...)` block (from `flags: list[str] = []` through the final `return DelistRecord(...)`) moves verbatim into a new method with this signature, with exactly two edits described below:

```python
    def _classify_resolved(
        self,
        ticker: str,
        resolution: TickerResolution,
        observed_delist_date: str | None,
        *,
        expected_name: str | None,
        delist_filing_override: EdgarSubmission | None = None,
    ) -> DelistRecord:
        observed = _parse_date(observed_delist_date) if observed_delist_date else None
        # ... the moved body ...
```

Edit A — replace the line `expected = self.resolver._expected_name(ticker.upper(), observed_delist_date)` with `expected = expected_name`.

Edit B — replace `delist_filing, gap = self._pick_delist_filing(filings, observed, resolution.cik)` with:

```python
        if delist_filing_override is not None:
            delist_filing = delist_filing_override
            fd = _parse_date(delist_filing.filing_date)
            gap = (observed - fd).days if (observed and fd) else None
        else:
            delist_filing, gap = self._pick_delist_filing(filings, observed, resolution.cik)
```

`classify_ticker` keeps its signature; its body becomes the non-equity short-circuit and resolution exactly as today, followed by:

```python
        return self._classify_resolved(
            ticker, resolution, observed_delist_date,
            expected_name=self.resolver._expected_name(ticker.upper(), observed_delist_date),
        )
```

4. Add `classify_event` below `classify_ticker` (import `TickerResolution` from `.ticker_resolver` at the top if it is not already imported):

```python
    def classify_event(
        self,
        *,
        ticker: str,
        cik: int,
        anchor_date: str,
        name: str | None = None,
        expected_name: str | None = None,
        kind: str = "common",
        form25: EdgarSubmission | None = None,
    ) -> DelistRecord:
        """Classify one delisting of a security whose issuer is already known.

        `anchor_date` is the last trade date (or the Form 25 filing date when the
        last trade is unknown); every rule window is measured from it. `form25` is
        the filing the delisting finder matched to this security; without it the
        Form 25 nearest the anchor is used, as classify_ticker does. `kind` comes
        from the security master; a non-equity kind is a scheduled end (600).
        """
        if kind in NON_EQUITY_KINDS:
            return DelistRecord(
                ticker=ticker.upper(), cik=cik, observed_delist_date=anchor_date,
                crsp_code=600, bucket=CrspBucket.EXPIRATION, confidence="high",
                reason=f"Non-equity security ({kind})",
                evidence={"asset_type": kind, "flags": []},
            )
        resolution = TickerResolution(ticker.upper(), int(cik), name, "security_master")
        return self._classify_resolved(ticker, resolution, anchor_date, expected_name=expected_name,
                                       delist_filing_override=form25)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_classify_event.py tests/test_golden_events.py tests/test_classifier.py -v`
Expected: all pass (the 31 golden `classify_ticker` cases, 31 new `classify_event` cases, 5 new unit tests, existing classifier tests).

If a golden `classify_event` case differs from `classify_ticker`, the refactor changed behavior: diff the two `reason` strings and fix the move, never the expectation.

- [ ] **Step 5: Run the full suite and commit**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -p no:warnings`
Expected: all pass

```bash
git add src/delist_detection/classifier.py tests/test_classify_event.py tests/test_golden_events.py
git commit -m "feat(classifier): classify_event for a known security and Form 25"
```

---

### Task 13: Listing status (secondary withdrawals, listed today)

**Files:**
- Create: `src/delist_detection/listing_status.py`
- Test: `tests/test_listing_status.py`

**Interfaces:**
- Consumes: `form25.exchanges_named`, `form25.exchange_label`, `MAJOR_EXCHANGES`, `REGIONAL_EXCHANGES` (Task 10); `figi_resolution.is_placeholder` (Task 9); `OpenFigiClient.map(jobs, use_cache=False)` (Task 8); `edgar.EdgarSubmission`; `evidence.parse_day`.
- Produces:
  - `ANNUAL_FORMS = frozenset({"10-K", "10-K405", "10-KSB", "10-KT", "20-F", "40-F"})`
  - `EXCHANGE_VENUES = frozenset({"UN", "UW", "UQ", "UR", "UA", "UP", "UF"})`
  - `cover_exchanges(text: str) -> set[str]`
  - `exchanges_around(edgar, cik: int, filings: list[EdgarSubmission], day: date) -> tuple[set[str] | None, set[str] | None]` — exchanges on the last annual report cover filed within 450 days before `day`, and the first within 450 days after (None when there is no such report)
  - `withdrawal_kind(exchange: str, before: set[str] | None, after: set[str] | None) -> str` — `"secondary"` or `"delisting"`
  - `listed_today(figi, sec_id: str, *, edgar=None, cik: int | None = None) -> bool | None`

Rule (D17, spec 8.6): a Form 25 is a delisting only when afterwards the security is on no exchange or has moved to a new one. A regional exchange (Chicago, Pacific, Boston, Philadelphia, NSX) is always a secondary listing for this library's securities. For a major exchange, the covers decide: if after the Form 25 another major exchange is listed that was already listed before, the main listing continued (secondary); if the other major exchange is new, it is an exchange transfer (a delisting); if none remains, it is a delisting. `listed_today` counts a security as listed only when OpenFIGI (without `includeUnlistedEquities`) returns a row on an exchange venue; an OTC-only security is not listed. Checked 2026-09-23: `COMPOSITE_ID_BB_GLOBAL` lookups return META (listed) and "No identifier found." for AET and LEH.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_listing_status.py
from datetime import date

from delist_detection.edgar import EdgarSubmission
from delist_detection.listing_status import (
    cover_exchanges, exchanges_around, listed_today, withdrawal_kind,
)

COVER_2019 = ("UNITED STATES SECURITIES AND EXCHANGE COMMISSION FORM 10-K ... Securities registered pursuant "
              "to Section 12(b) of the Act: Title of each class Trading Symbol(s) Name of each exchange on which "
              "registered Common Stock, $0.625 par value APA New York Stock Exchange Chicago Stock Exchange ...")
COVER_2021 = ("FORM 10-K ... Name of each exchange on which registered Common Stock APA "
              "Nasdaq Global Select Market ...")


def test_cover_exchanges():
    assert cover_exchanges(COVER_2019) == {"NYSE", "CHICAGO"}
    assert cover_exchanges(COVER_2021) == {"NASDAQ"}
    assert cover_exchanges("") == set()


def test_withdrawal_kind():
    assert withdrawal_kind("CHICAGO", {"NYSE", "CHICAGO"}, {"NYSE"}) == "secondary"        # Apache 2020
    assert withdrawal_kind("NYSE ARCA", {"NYSE", "NYSE ARCA"}, {"NYSE"}) == "secondary"    # IRF 2007
    assert withdrawal_kind("NASDAQ", {"NASDAQ"}, {"NYSE"}) == "delisting"                  # moved: transfer
    assert withdrawal_kind("NYSE", {"NYSE"}, None) == "delisting"                          # stopped filing
    assert withdrawal_kind("NYSE", {"NYSE"}, set()) == "delisting"                         # OTC afterwards
    assert withdrawal_kind("", None, None) == "delisting"


class _Edgar:
    def __init__(self, texts):
        self.texts = texts

    def fetch_filing_text(self, cik, accession, primary_doc):
        return self.texts.get(accession, "")


def test_exchanges_around():
    filings = [
        EdgarSubmission("k19", "10-K", "2020-02-21", "", "", "a.htm"),
        EdgarSubmission("k21", "10-K", "2021-02-25", "", "", "b.htm"),
        EdgarSubmission("q", "10-Q", "2020-08-01", "", "", "c.htm"),
    ]
    before, after = exchanges_around(_Edgar({"k19": COVER_2019, "k21": COVER_2021}), 6769, filings,
                                     date(2020, 6, 8))
    assert before == {"NYSE", "CHICAGO"} and after == {"NASDAQ"}
    assert exchanges_around(_Edgar({}), 1, [], date(2020, 6, 8)) == (None, None)


class _Figi:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def map(self, jobs, use_cache=True):
        self.calls.append((jobs, use_cache))
        return [self.answer]


class _Sub:
    def __init__(self, exchanges):
        self.exchanges = exchanges

    def submissions(self, cik, fresh_after=None):
        return {"exchanges": self.exchanges}


def test_listed_today():
    listed = _Figi({"data": [{"exchCode": "US"}, {"exchCode": "UW"}]})
    assert listed_today(listed, "BBG000MM2P62") is True
    assert listed.calls[0] == ([{"idType": "COMPOSITE_ID_BB_GLOBAL", "idValue": "BBG000MM2P62"}], False)
    assert listed_today(_Figi({"warning": "No identifier found."}), "BBG000FJLFX8") is False
    assert listed_today(_Figi({"data": [{"exchCode": "US"}, {"exchCode": "UV"}]}), "BBG1") is False   # OTC only
    assert listed_today(_Figi({"error": "x"}), "BBG1") is None
    assert listed_today(_Figi({}), "CIK1-COMMON", edgar=_Sub(["NYSE"]), cik=1) is True
    assert listed_today(_Figi({}), "CIK1-COMMON", edgar=_Sub(["OTC"]), cik=1) is False
    assert listed_today(_Figi({}), "CIK1-COMMON") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_listing_status.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/listing_status.py
"""Where a security is listed: before and after a Form 25, and today.

A Form 25 that withdraws a secondary listing (Apache from the Chicago Stock
Exchange in 2020 while it stayed on NYSE) is not a delisting (D17). The 10-K
cover page names every exchange a class is registered on, so the covers on
either side of the Form 25 tell the cases apart.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta

from .edgar import EdgarSubmission
from .evidence import parse_day
from .figi_resolution import is_placeholder
from .form25 import MAJOR_EXCHANGES, REGIONAL_EXCHANGES, exchange_label, exchanges_named

ANNUAL_FORMS = frozenset({"10-K", "10-K405", "10-KSB", "10-KT", "20-F", "40-F"})
EXCHANGE_VENUES = frozenset({"UN", "UW", "UQ", "UR", "UA", "UP", "UF"})
COVER_WINDOW_DAYS = 450


def cover_exchanges(text: str) -> set[str]:
    head = (text or "")[:12000]
    m = re.search(r"name of each exchange on which registered", head, re.I)
    window = head[m.start(): m.start() + 1500] if m else head[:4000]
    return exchanges_named(window) & (MAJOR_EXCHANGES | REGIONAL_EXCHANGES)


def _annual(filings: Iterable[EdgarSubmission]) -> list[tuple[date, EdgarSubmission]]:
    out = [(d, f) for f in filings if f.form in ANNUAL_FORMS and (d := parse_day(f.filing_date))]
    return sorted(out, key=lambda x: x[0])


def exchanges_around(edgar, cik: int, filings: list[EdgarSubmission],
                     day: date) -> tuple[set[str] | None, set[str] | None]:
    reports = _annual(filings)
    window = timedelta(days=COVER_WINDOW_DAYS)
    before = [f for d, f in reports if day - window <= d < day]
    after = [f for d, f in reports if day < d <= day + window]

    def read(f: EdgarSubmission) -> set[str]:
        return cover_exchanges(edgar.fetch_filing_text(cik, f.accession, f.primary_doc))

    return (read(before[-1]) if before else None), (read(after[0]) if after else None)


def withdrawal_kind(exchange: str, before: set[str] | None, after: set[str] | None) -> str:
    if exchange in REGIONAL_EXCHANGES:
        return "secondary"
    if exchange not in MAJOR_EXCHANGES or after is None:
        return "delisting"
    remaining = (after & MAJOR_EXCHANGES) - {exchange}
    if not remaining:
        return "delisting"
    if before is not None and remaining <= before:
        return "secondary"
    return "delisting"


def listed_today(figi, sec_id: str, *, edgar=None, cik: int | None = None) -> bool | None:
    if not is_placeholder(sec_id):
        ans = figi.map([{"idType": "COMPOSITE_ID_BB_GLOBAL", "idValue": sec_id}], use_cache=False)[0]
        if "error" in ans:
            return None
        return any(r.get("exchCode") in EXCHANGE_VENUES for r in ans.get("data") or [])
    if edgar is None or cik is None:
        return None
    sub = edgar.submissions(cik)
    labels = {exchange_label(x) for x in (sub.get("exchanges") or []) if x} if isinstance(sub, dict) else set()
    return bool(labels & MAJOR_EXCHANGES)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_listing_status.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/listing_status.py tests/test_listing_status.py
git commit -m "feat(listing): secondary-withdrawal rule and listed-today check"
```

---

### Task 14: Security master (eras → FIGI securities, CUSIP and ticker ranges)

**Files:**
- Create: `src/delist_detection/security_master.py`
- Test: `tests/test_security_master.py`

**Interfaces:**
- Consumes: `TickerEra`, `normalize_ticker` (Task 3); `FtdIndex`, `FtdRow` (Task 5); `OpenFigiClient.map/filter` (Task 8); `us_candidates`, `accept`, `FigiCandidate`, `share_class_from_name`, `placeholder_id`, `bloomberg_ticker`, `filter_query`, `security_kind` (Task 9); `names.names_agree`.
- Produces:
  - `Security` dataclass: `sec_id: str`, `issuer_cik: int | None`, `share_class: str`, `name: str`, `security_type: str`, `observed: bool`, `figi_source: str`, `kind: str = "common"`, `eras: list[TickerEra] = []`; method `row() -> dict` (the `securities.csv` columns)
  - `EraResolution(era_key: str, sec_id: str | None, source: str, candidate: FigiCandidate | None, flags: tuple[str, ...])` (frozen); `source` ∈ `pin`, `cusip`, `ticker`, `name`, `placeholder`, `unresolved`
  - `era_cusips(era: TickerEra, ftd: FtdIndex) -> list[str]`
  - `era_last_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400) -> str` — the latest of `era.last` and the last FTD row of the era's ticker within `horizon_days` after it whose description agrees with an era name (the whole horizon when the era has no names); used as the resolver's date
  - `FigiResolver(figi)` with `.resolve_many(eras: Sequence[TickerEra], *, ciks: Mapping[str, int | None], cusips: Mapping[str, list[str]]) -> dict[str, EraResolution]` (keyed by `era.key`)
  - `build_securities(resolutions: Mapping[str, EraResolution], eras: Mapping[str, TickerEra], ciks: Mapping[str, int | None]) -> dict[str, Security]`
  - `Range(value: str, valid_from: str, valid_to: str | None, source: str)` (frozen)
  - `ranges_from_sightings(sightings: Iterable[tuple[str, str, str]], *, end: str | None, open_ended: bool) -> list[Range]` — sightings are `(iso_date, value, source)` with `source` ∈ `observation`, `ftd`

Resolution order per era (spec 8.3, D19): a `sec_id` pin; else each CUSIP (the caller's, then the FTD CUSIPs the era's ticker carried, most frequent first; `ID_CINS` when the CUSIP starts with a letter) accepted without a name check; else the ticker lookup (no `exchCode`, `includeUnlistedEquities`) accepted only with a venue row carrying the ticker and an agreeing name; else a `/v3/filter` name search under the same rule; else the placeholder `CIK<cik>-<CLASS>` (flag `no_figi`); with no CIK either, `unresolved` (flag `observation_unresolved`). All mapping jobs for all eras go in one `map` call (the client chunks them); filter calls are made only for eras still unresolved.

Security fields: `name` is the era's observed name when there is one (Bloomberg renames dead lines to the acquirer), else the candidate's name; `share_class` comes from the candidate's name when it carries a class marker, else from the observed name; `security_type` from the candidate (empty for placeholders); `kind = security_kind(security_type, name)`; `issuer_cik` from the latest era; `observed = True`.

Ranges: a run of the same value becomes one range. The next run starts the day its first sighting was made, and the previous range ends the calendar day before (inclusive end dates, D10). The last range ends at `end` if given, stays open if `open_ended`, else ends at its last sighting. An FTD value seen only once for the security is noise and dropped; observation sightings are never dropped.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_security_master.py
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.observations import Observation, split_eras
from delist_detection.security_master import (
    EraResolution, FigiResolver, Range, build_securities, era_cusips, era_last_seen, ranges_from_sightings,
)


def _era(ticker, *obs):
    return split_eras([Observation(ticker, d, n) for d, n in obs])[0]


def _row(comp, exch, ticker, name, st="Common Stock"):
    return {"figi": comp if exch == "US" else comp + exch, "compositeFIGI": comp, "exchCode": exch,
            "ticker": ticker, "name": name, "securityType": st, "securityType2": "Common Stock"}


class _Figi:
    def __init__(self, answers, filters=None):
        self.answers, self.filters, self.jobs, self.filter_calls = answers, filters or {}, [], []

    def map(self, jobs, use_cache=True):
        self.jobs += jobs
        return [self.answers.get((j["idType"], j["idValue"]), {"warning": "No identifier found."}) for j in jobs]

    def filter(self, query, **fields):
        self.filter_calls.append(query)
        return self.filters.get(query, [])


def test_era_cusips_prefers_matching_description():
    era = _era("AET", ("2018-06-29", "AETNA INC"))
    ftd = FtdIndex([
        FtdRow("2018-06-28", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
        FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0),
        FtdRow("2018-06-29", "999999999", "AET", "SOMETHING ELSE ETF", 10.0),
    ])
    assert era_cusips(era, ftd) == ["00817Y108"]


def test_era_last_seen_extends_past_the_last_snapshot():
    era = _era("AET", ("2018-06-29", "AETNA INC"))
    ftd = FtdIndex([
        FtdRow("2018-11-29", "00817Y108", "AET", "AETNA INC.(NEW)", 212.7),
        FtdRow("2021-01-04", "11111111X", "AET", "SOME ETF TRUST", 20.0),       # a later holder, past the horizon
        FtdRow("2019-03-01", "22222222X", "AET", "UNRELATED CORP", 5.0),       # name does not agree
    ])
    assert era_last_seen(era, ftd) == "2018-11-29"
    assert era_last_seen(_era("ZZZ", ("2018-06-29", "Z CO")), ftd) == "2018-06-29"


def test_resolve_many_orders_routes():
    aet = _era("AET", ("2018-06-29", "AETNA INC"))
    qcor = _era("QCOR", ("2014-06-30", "QUESTCOR PHARMACEUTICALS INC"))
    goog = _era("GOOG", ("2020-06-30", "ALPHABET INC CLASS C"))
    fb = _era("FB", ("2021-06-30", "FACEBOOK INC CLASS A"))
    figi = _Figi({
        ("ID_CUSIP", "00817Y108"): {"data": [_row("BBG000FJLFX8", "US", "AET", "AETNA INC")]},
        ("ID_CUSIP", "74835Y101"): {"data": [_row("BBG000BPVCR1", "US", "QCOR", "MALLINCKRODT ARD LLC")]},
        ("TICKER", "GOOG"): {"data": [_row("BBG009S3NB30", "US", "GOOG", "ALPHABET INC-CL C")]},
        ("TICKER", "FB"): {"data": [_row("BBG01VRMNFB1", "US", "FB", "PROSHARES S&P DYNAMIC BUFFER ETP", "ETP")]},
    })
    res = FigiResolver(figi).resolve_many(
        [aet, qcor, goog, fb],
        ciks={aet.key: 1122304, qcor.key: 1034842, goog.key: 1652044, fb.key: 1326801},
        cusips={aet.key: ["00817Y108"], qcor.key: ["74835Y101"], goog.key: [], fb.key: []},
    )
    assert res[aet.key] == EraResolution(aet.key, "BBG000FJLFX8", "cusip", res[aet.key].candidate, ())
    assert res[qcor.key].sec_id == "BBG000BPVCR1" and res[qcor.key].source == "cusip"
    assert res[goog.key].sec_id == "BBG009S3NB30" and res[goog.key].source == "ticker"
    assert res[fb.key].sec_id == "CIK1326801-CLASS-A" and res[fb.key].flags == ("no_figi",)
    assert figi.filter_calls == ["FACEBOOK CLASS A"]          # only the unresolved era searched by name


def test_pin_and_unresolved():
    pinned = split_eras([Observation("X", "2020-01-02", "X CORP", sec_id="BBG000PIN001")])[0]
    orphan = _era("Y", ("2020-01-02", "Y CORP"))
    res = FigiResolver(_Figi({})).resolve_many([pinned, orphan], ciks={pinned.key: None, orphan.key: None},
                                               cusips={pinned.key: [], orphan.key: []})
    assert res[pinned.key].sec_id == "BBG000PIN001" and res[pinned.key].source == "pin"
    assert res[orphan.key].sec_id is None and res[orphan.key].flags == ("observation_unresolved",)


def test_build_securities_merges_eras_of_one_figi():
    fb = _era("FB", ("2021-12-31", "FACEBOOK INC CLASS A"))
    meta = _era("META", ("2022-06-30", "META PLATFORMS INC CLASS A"))
    from delist_detection.figi_resolution import FigiCandidate
    cand = FigiCandidate("BBG000MM2P62", "META PLATFORMS INC-CLASS A", "META", "Common Stock", ())
    secs = build_securities(
        {fb.key: EraResolution(fb.key, "BBG000MM2P62", "cusip", cand, ()),
         meta.key: EraResolution(meta.key, "BBG000MM2P62", "ticker", cand, ())},
        {fb.key: fb, meta.key: meta}, {fb.key: 1326801, meta.key: 1326801})
    s = secs["BBG000MM2P62"]
    assert [e.ticker for e in s.eras] == ["FB", "META"]
    assert s.share_class == "CLASS A" and s.issuer_cik == 1326801 and s.kind == "common" and s.observed
    assert s.row() == {"sec_id": "BBG000MM2P62", "issuer_cik": 1326801, "share_class": "CLASS A",
                       "name": "META PLATFORMS INC CLASS A", "security_type": "Common Stock",
                       "observed": True, "figi_source": "cusip"}


def test_ranges_from_sightings():
    s = [("2021-12-31", "FB", "observation"), ("2022-06-08", "FB", "ftd"), ("2022-06-09", "META", "ftd"),
         ("2022-06-10", "META", "ftd"), ("2022-06-30", "META", "observation"), ("2022-07-01", "MVRS", "ftd")]
    assert ranges_from_sightings(s, end=None, open_ended=True) == [
        Range("FB", "2021-12-31", "2022-06-08", "observation"),
        Range("META", "2022-06-09", None, "observation"),
    ]
    assert ranges_from_sightings(s, end="2022-12-30", open_ended=False)[-1] == \
        Range("META", "2022-06-09", "2022-12-30", "observation")
    assert ranges_from_sightings([("2020-01-02", "X", "ftd"), ("2020-01-03", "X", "ftd")], end=None,
                                 open_ended=False) == [Range("X", "2020-01-02", "2020-01-03", "ftd")]
    assert ranges_from_sightings([], end=None, open_ended=True) == []
```

(`FACEBOOK INC CLASS A` → `filter_query` drops `INC` → `"FACEBOOK CLASS A"`; the placeholder takes the class from the observed name.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/security_master.py
"""The security master: observation eras resolved to US composite FIGIs, merged
into securities, with dated ticker and CUSIP ranges.

A security is one share class traded in the US (CONTEXT.md). Eras of different
tickers that resolve to the same FIGI (FB, later META) are one security.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from .figi_resolution import (
    FigiCandidate, accept, bloomberg_ticker, filter_query, placeholder_id, security_kind,
    share_class_from_name, us_candidates,
)
from .ftd import FtdIndex
from .names import names_agree
from .observations import TickerEra


@dataclass
class Security:
    sec_id: str
    issuer_cik: int | None
    share_class: str
    name: str
    security_type: str
    observed: bool
    figi_source: str
    kind: str = "common"
    eras: list[TickerEra] = field(default_factory=list)

    def row(self) -> dict:
        return {"sec_id": self.sec_id, "issuer_cik": self.issuer_cik, "share_class": self.share_class,
                "name": self.name, "security_type": self.security_type, "observed": self.observed,
                "figi_source": self.figi_source}


@dataclass(frozen=True)
class EraResolution:
    era_key: str
    sec_id: str | None
    source: str
    candidate: FigiCandidate | None
    flags: tuple[str, ...]


def era_cusips(era: TickerEra, ftd: FtdIndex) -> list[str]:
    lo = (date.fromisoformat(era.first) - timedelta(days=10)).isoformat()
    hi = (date.fromisoformat(era.last) + timedelta(days=10)).isoformat()
    counts: Counter[str] = Counter()
    for r in ftd.by_symbol(era.ticker, lo, hi):
        if era.names and not any(names_agree(r.description, n) for n in era.names):
            continue
        counts[r.cusip] += 1
    return list(era.cusips) + [c for c, _ in counts.most_common() if c not in era.cusips]


def era_last_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400) -> str:
    lo = (date.fromisoformat(era.last) + timedelta(days=1)).isoformat()
    hi = (date.fromisoformat(era.last) + timedelta(days=horizon_days)).isoformat()
    best = era.last
    for r in ftd.by_symbol(era.ticker, lo, hi):
        if era.names and not any(names_agree(r.description, n) for n in era.names):
            continue
        best = max(best, r.date)
    return best


def _cusip_job(c: str) -> dict:
    return {"idType": "ID_CINS" if c[:1].isalpha() else "ID_CUSIP", "idValue": c, "includeUnlistedEquities": True}


class FigiResolver:
    MAX_CUSIPS = 3

    def __init__(self, figi) -> None:
        self.figi = figi

    def resolve_many(self, eras: Sequence[TickerEra], *, ciks: Mapping[str, int | None],
                     cusips: Mapping[str, list[str]]) -> dict[str, EraResolution]:
        out: dict[str, EraResolution] = {}
        jobs: list[dict] = []
        plan: dict[str, tuple[list[int], int]] = {}
        for era in eras:
            if era.sec_id_pin:
                out[era.key] = EraResolution(era.key, era.sec_id_pin, "pin", None, ())
                continue
            idx = []
            for c in cusips.get(era.key, [])[: self.MAX_CUSIPS]:
                idx.append(len(jobs))
                jobs.append(_cusip_job(c))
            t_idx = len(jobs)
            jobs.append({"idType": "TICKER", "idValue": bloomberg_ticker(era.ticker), "includeUnlistedEquities": True})
            plan[era.key] = (idx, t_idx)
        answers = self.figi.map(jobs) if jobs else []
        for era in eras:
            if era.key in out:
                continue
            idx, t_idx = plan[era.key]
            names = era.names
            for i in idx:
                c = accept(us_candidates(answers[i].get("data") or []), ticker=era.ticker, names=names,
                           via_cusip=True)
                if c:
                    out[era.key] = EraResolution(era.key, c.composite, "cusip", c, ())
                    break
            if era.key in out:
                continue
            c = accept(us_candidates(answers[t_idx].get("data") or []), ticker=era.ticker, names=names,
                       via_cusip=False)
            if c:
                out[era.key] = EraResolution(era.key, c.composite, "ticker", c, ())
                continue
            q = filter_query(era.name or "")
            if q:
                rows = self.figi.filter(q, exchCode="US", includeUnlistedEquities=True)
                c = accept(us_candidates(rows), ticker=era.ticker, names=names, via_cusip=False)
                if c:
                    out[era.key] = EraResolution(era.key, c.composite, "name", c, ())
                    continue
            cik = ciks.get(era.key)
            if cik is not None:
                out[era.key] = EraResolution(era.key, placeholder_id(cik, share_class_from_name(era.name)),
                                             "placeholder", None, ("no_figi",))
            else:
                out[era.key] = EraResolution(era.key, None, "unresolved", None, ("observation_unresolved",))
        return out


def build_securities(resolutions: Mapping[str, EraResolution], eras: Mapping[str, TickerEra],
                     ciks: Mapping[str, int | None]) -> dict[str, Security]:
    out: dict[str, Security] = {}
    for key in sorted(resolutions, key=lambda k: (eras[k].first, k)):
        res = resolutions[key]
        if res.sec_id is None:
            continue
        era, cand = eras[key], res.candidate
        sec = out.get(res.sec_id)
        if sec is None:
            name = era.name or (cand.name if cand else "")
            cand_class = share_class_from_name(cand.name) if cand else "COMMON"
            share = cand_class if cand_class != "COMMON" else share_class_from_name(era.name)
            stype = cand.security_type if cand else ""
            sec = Security(res.sec_id, ciks.get(key), share, name, stype, True, res.source,
                           security_kind(stype, name))
            out[res.sec_id] = sec
        sec.eras.append(era)
        if ciks.get(key) is not None:
            sec.issuer_cik = ciks[key]
        if era.name:
            sec.name = era.name
    return out


@dataclass(frozen=True)
class Range:
    value: str
    valid_from: str
    valid_to: str | None
    source: str


def ranges_from_sightings(sightings: Iterable[tuple[str, str, str]], *, end: str | None,
                          open_ended: bool) -> list[Range]:
    items = sorted(set(sightings))
    ftd_counts = Counter(v for _, v, s in items if s == "ftd")
    obs_values = {v for _, v, s in items if s == "observation"}
    items = [(d, v, s) for d, v, s in items if s == "observation" or ftd_counts[v] > 1 or v in obs_values]
    runs: list[list] = []                        # [value, first, last, sources]
    for d, v, s in items:
        if runs and runs[-1][0] == v:
            runs[-1][2] = d
            runs[-1][3].add(s)
        else:
            runs.append([v, d, d, {s}])
    out: list[Range] = []
    for i, (v, first, last, sources) in enumerate(runs):
        if i + 1 < len(runs):
            to: str | None = (date.fromisoformat(runs[i + 1][1]) - timedelta(days=1)).isoformat()
        elif end is not None:
            to = end
        elif open_ended:
            to = None
        else:
            to = last
        out.append(Range(v, first, to, "observation" if "observation" in sources else "ftd"))
    return out
```

Check against `test_ranges_from_sightings`: `MVRS` appears once from FTD and never in observations → dropped; FB run 2021-12-31..2022-06-08 ends the day before META's first sighting (2022-06-09); META's run includes the 2022-06-30 observation, so its source is `observation`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/security_master.py tests/test_security_master.py
git commit -m "feat(security-master): eras to FIGI securities, ticker and CUSIP ranges"
```

---

### Task 15: Delisting finder

**Files:**
- Create: `src/delist_detection/delistings.py`
- Test: `tests/test_delistings.py`

**Interfaces:**
- Consumes: `form25.list_form25`, `parse_form25`, `match_security`, `notice_last_trade`, `effective_date`, `SecurityRef`, `REGIONAL_EXCHANGES`, `Form25` (Task 10); `last_trade.eightk_last_trade`, `decide_last_trade`, `LastTrade` (Task 11); `listing_status.exchanges_around`, `withdrawal_kind` (Task 13); `midas.MIDAS_START` (Task 6); `nasdaq_halts.last_trade_from_halt` (Task 7); `trading_calendar.previous_trading_day`; `security_master.Security` (Task 14); `DelistClassifier.classify_event` (Task 12); `crsp_codes.CrspBucket`; `edgar.EdgarSubmission`.
- Produces:
  - `ReviewItem(sec_id: str, ticker: str, cik: int | None, flag: str, reason: str, delist_date: str = "", last_seen: str = "")` (frozen)
  - `DelistingEvent` dataclass: `sec_id: str`, `cik: int`, `ticker: str`, `delist_date: str`, `record: DelistRecord`, `last_trade: LastTrade`, `form25: Form25 | None`, `form25_sub: EdgarSubmission | None`, `exchange: str`, `flags: list[str]`
  - `SecurityContext` dataclass: `security: Security`, `siblings: list[SecurityRef]`, `ticker_on: Callable[[str], str | None]`, `last_seen: str`, `seen_after: Callable[[str], bool]`, `listed_today: bool | None`, `expected_name: str | None`
  - `DelistingFinder(edgar, classifier, *, midas=None, halts=None)` with `.find(ctx: SecurityContext) -> tuple[list[DelistingEvent], list[ReviewItem]]`

Behavior (spec 8.6–8.10, D6, D16, D17, D20):
1. Every Form 25 / 25-NSE / 25/A of the issuer filed on or after 30 days before the security's first sighting is parsed from the raw filing and matched to one security (D16). A match to another security of the issuer is skipped; `ambiguous class` adds a `form25_unmatched` review item; a class the universe does not hold (preferred, notes) is skipped silently.
2. A regional exchange withdrawal is skipped. When the security was still trading afterwards (listed today, or sighted more than 5 days after the effective date), the 10-K covers decide (`withdrawal_kind`); `secondary` is skipped.
3. The last trade date comes from `decide_last_trade(notice, 8-K, MIDAS, halt)`. MIDAS is asked for `[filed − 75 d, filed + 10 d]` and ignored when its last volume day is on or after `filed + 5 d` (the security kept trading: an exchange move). The halt feed is asked only when MIDAS has no answer.
4. `classify_event(anchor = last trade date or Form 25 filing date, form25 = the matched filing, kind = the security's kind)`; the record gets `sec_id`, `delist_date = effective_date(filing)`; for `exchange_transfer`, `successor_sec_id` is the security itself when it kept trading, else `None` with flag `successor_unknown`.
5. Form 25s within 30 days of each other on the same exchange (a 25 and its 25-NSE, or an amendment) are one delisting: keep the earliest.
6. With no delisting found and `listed_today is False`: classify with no Form 25, anchored on `last_seen`. A non-`unknown` bucket or a deregistration becomes a delisting dated by the filing that ended trading (flag `no_form25`); otherwise a review item `ended_without_delisting` with `last_seen`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_delistings.py
from datetime import date
from pathlib import Path

from delist_detection.classifier import DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import DelistingFinder, SecurityContext
from delist_detection.edgar import EdgarSubmission
from delist_detection.form25 import SecurityRef
from delist_detection.observations import Observation, split_eras
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "form25"
AET_RAW = (FIX / "aet_25nse.txt").read_text(encoding="utf-8", errors="replace")

CHICAGO_RAW = """<TYPE>25
<notificationOfRemoval><exchange><entityName>Chicago Stock Exchange, Inc.</entityName></exchange>
<descriptionClassSecurity>Common Stock</descriptionClassSecurity>
<ruleProvision>17 CFR 240.12d2-2(c)</ruleProvision></notificationOfRemoval>"""


def _sec(sec_id, cik, ticker, first, last, name):
    era = split_eras([Observation(ticker, first, name), Observation(ticker, last, name)])[0]
    return Security(sec_id, cik, "COMMON", name, "Common Stock", True, "cusip", "common", [era])


class _Midas:
    def __init__(self, day):
        self.day, self.calls = day, []

    def last_trade_day(self, ticker, lo, hi):
        self.calls.append((ticker, lo, hi))
        return self.day


def _aet_edgar(fake_edgar):
    fake_edgar.submissions_by_cik[1122304] = [
        EdgarSubmission("0000876661-18-001269", "25-NSE", "2018-11-29", "", "", "primary_doc.xml"),
        EdgarSubmission("0001122304-18-000178", "8-K", "2018-11-28", "2018-11-28",
                        "2.01,3.01,3.03,5.01,5.02,5.03,9.01", "k.htm"),
        EdgarSubmission("0001122304-18-000184", "15-12B", "2018-12-10", "", "", "f.htm"),
    ]
    fake_edgar.company_map["AET"] = {"cik_str": 1122304, "ticker": "AET", "title": "AETNA INC /PA/"}
    fake_edgar.raws["0000876661-18-001269"] = AET_RAW
    fake_edgar.texts["0001122304-18-000178"] = ("Item 3.01 Notice of Delisting. requested that trading be suspended "
                                                "prior to the opening of trading on November 29, 2018 " + "x" * 300)
    return fake_edgar


def _ctx(sec, *, listed=False, seen_after=False, last_seen="2018-11-28"):
    return SecurityContext(security=sec, siblings=[SecurityRef(sec.sec_id, sec.share_class, sec.kind)],
                           ticker_on=lambda d: sec.eras[-1].ticker, last_seen=last_seen,
                           seen_after=lambda d: seen_after, listed_today=listed, expected_name=sec.name)


def test_aet_merger_delisting(fake_edgar):
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG000FJLFX8", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    midas = _Midas(date(2018, 11, 28))
    events, review = DelistingFinder(edgar, clf, midas=midas).find(_ctx(sec))
    assert review == []
    (ev,) = events
    assert ev.sec_id == "BBG000FJLFX8" and ev.delist_date == "2018-12-09"
    assert ev.last_trade.day == date(2018, 11, 28) and ev.last_trade.source == "midas"
    assert ev.record.bucket is CrspBucket.MERGER
    assert ev.record.sec_id == "BBG000FJLFX8" and ev.record.delist_date == "2018-12-09"
    assert ev.record.observed_delist_date == "2018-11-28"
    assert ev.exchange == "NYSE"
    assert midas.calls[0][0] == "AET"


def test_midas_volume_past_the_window_is_ignored(fake_edgar):
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG000FJLFX8", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    (ev,), _ = DelistingFinder(edgar, clf, midas=_Midas(date(2018, 12, 7))).find(_ctx(sec))
    assert ev.last_trade.source == "ex99_notice" and ev.last_trade.day == date(2018, 11, 28)


def test_secondary_regional_withdrawal_is_skipped(fake_edgar):
    fake_edgar.submissions_by_cik[6769] = [EdgarSubmission("c1", "25", "2020-06-08", "", "", "p.xml")]
    fake_edgar.raws["c1"] = CHICAGO_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG000BBTJ69", 6769, "APA", "2019-06-28", "2020-12-31", "APACHE CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=True, seen_after=True))
    assert events == [] and review == []


def test_ambiguous_class_goes_to_review(fake_edgar):
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    a = _sec("BBG_A", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    b = _sec("BBG_B", 1122304, "AETB", "2017-06-30", "2018-06-29", "AETNA INC")
    a.share_class, b.share_class = "CLASS A", "CLASS B"
    ctx = _ctx(a)
    ctx.siblings = [SecurityRef("BBG_A", "CLASS A", "common"), SecurityRef("BBG_B", "CLASS B", "common")]
    events, review = DelistingFinder(edgar, clf).find(ctx)
    assert any(r.flag == "form25_unmatched" for r in review)


def test_ended_without_delisting(fake_edgar):
    fake_edgar.submissions_by_cik[555] = [EdgarSubmission("q1", "10-Q", "2015-05-01", "", "", "q.htm")]
    fake_edgar.company_map["QQQQ"] = {"cik_str": 555, "ticker": "QQQQ", "title": "QUIET CO"}
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_Q", 555, "QQQQ", "2014-06-30", "2015-06-30", "QUIET CO")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-06-30"))
    assert events == []
    assert [(r.flag, r.last_seen) for r in review] == [("ended_without_delisting", "2015-06-30")]


def test_listed_today_without_form25_is_quiet(fake_edgar):
    fake_edgar.submissions_by_cik[556] = []
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_L", 556, "LIVE", "2020-06-30", "2026-06-30", "LIVE CO")
    assert DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=True)) == ([], [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/delist_detection/delistings.py
"""Find, date and classify every delisting of one security (D6, D16, D17, D20).

A delisting is a Form 25 that removed the security's class from its exchange
and left it on no exchange or on a new one. Securities with no Form 25 fall back
to the classifier's no-Form-25 paths; a security that ended with no evidence at
all is reported for review instead of being dropped.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from .classifier import DelistClassifier, DelistRecord
from .crsp_codes import CrspBucket
from .edgar import EdgarSubmission
from .form25 import (
    REGIONAL_EXCHANGES, Form25, SecurityRef, effective_date, list_form25, match_security, notice_last_trade,
    parse_form25,
)
from .last_trade import LastTrade, decide_last_trade, eightk_last_trade
from .listing_status import exchanges_around, withdrawal_kind
from .midas import MIDAS_START
from .nasdaq_halts import last_trade_from_halt
from .security_master import Security
from .trading_calendar import previous_trading_day

FORM25_LOOKBACK_DAYS = 30
SAME_EVENT_DAYS = 30
MIDAS_BEFORE_DAYS, MIDAS_AFTER_DAYS, MIDAS_STILL_TRADING_DAYS = 75, 10, 5
EIGHTK_BEFORE_DAYS, EIGHTK_AFTER_DAYS = 60, 5


@dataclass(frozen=True)
class ReviewItem:
    sec_id: str
    ticker: str
    cik: int | None
    flag: str
    reason: str
    delist_date: str = ""
    last_seen: str = ""


@dataclass
class DelistingEvent:
    sec_id: str
    cik: int
    ticker: str
    delist_date: str
    record: DelistRecord
    last_trade: LastTrade
    form25: Form25 | None
    form25_sub: EdgarSubmission | None
    exchange: str
    flags: list[str] = field(default_factory=list)


@dataclass
class SecurityContext:
    security: Security
    siblings: list[SecurityRef]
    ticker_on: Callable[[str], str | None]
    last_seen: str
    seen_after: Callable[[str], bool]
    listed_today: bool | None
    expected_name: str | None


def _d(s: str) -> date:
    return date.fromisoformat(s)


class DelistingFinder:
    def __init__(self, edgar, classifier: DelistClassifier, *, midas=None, halts=None) -> None:
        self.edgar, self.classifier, self.midas, self.halts = edgar, classifier, midas, halts

    # -- last trade ------------------------------------------------------
    def _eightk(self, cik: int, filings: list[EdgarSubmission], filed: date) -> tuple[date | None, str]:
        lo, hi = filed - timedelta(days=EIGHTK_BEFORE_DAYS), filed + timedelta(days=EIGHTK_AFTER_DAYS)
        cands = [f for f in filings if f.form.startswith("8-K") and "3.01" in f.item_set
                 and f.filing_date and lo <= _d(f.filing_date) <= hi]
        for f in sorted(cands, key=lambda f: abs((_d(f.filing_date) - filed).days)):
            got = eightk_last_trade(self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc))
            if got[0] is not None:
                return got
        return None, ""

    def _last_trade(self, cik: int, filings: list[EdgarSubmission], f25: Form25 | None, ticker: str,
                    filed: date) -> LastTrade:
        notice = notice_last_trade(f25) if f25 else (None, "")
        eightk = self._eightk(cik, filings, filed)
        midas = None
        if self.midas is not None and filed >= MIDAS_START:
            m = self.midas.last_trade_day(ticker, filed - timedelta(days=MIDAS_BEFORE_DAYS),
                                          filed + timedelta(days=MIDAS_AFTER_DAYS))
            if m is not None and m < filed + timedelta(days=MIDAS_STILL_TRADING_DAYS):
                midas = m
        halt = None
        if midas is None and self.halts is not None:
            guesses = [d for d, _ in (notice, eightk) if d] or [previous_trading_day(filed)]
            h = self.halts.deletion_halt(ticker, min(guesses) - timedelta(days=2),
                                         max(guesses) + timedelta(days=2), max_days=5)
            halt = last_trade_from_halt(h) if h else None
        return decide_last_trade(notice=notice, eightk=eightk, midas=midas, halt=halt)

    # -- main ------------------------------------------------------------
    def find(self, ctx: SecurityContext) -> tuple[list[DelistingEvent], list[ReviewItem]]:
        sec = ctx.security
        cik = sec.issuer_cik
        ticker_last = sec.eras[-1].ticker if sec.eras else ""
        if cik is None:
            if ctx.listed_today is False:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "ended_without_delisting",
                                       "no issuer CIK to search for a Form 25", last_seen=ctx.last_seen)]
            return [], []
        filings = self.edgar.recent_filings(cik)
        first_seen = min(e.first for e in sec.eras) if sec.eras else "0000-01-01"
        floor = (_d(first_seen) - timedelta(days=FORM25_LOOKBACK_DAYS)).isoformat()
        events: list[DelistingEvent] = []
        review: list[ReviewItem] = []
        for sub in list_form25(filings):
            if sub.filing_date < floor:
                continue
            f25 = parse_form25(self.edgar.fetch_filing_raw(cik, sub.accession), accession=sub.accession,
                               form=sub.form, filing_date=sub.filing_date)
            matched, why = match_security(f25, ctx.siblings)
            if matched is None:
                if why == "ambiguous class":
                    review.append(ReviewItem(sec.sec_id, ticker_last, cik, "form25_unmatched",
                                             f"{sub.form} {sub.accession} ({f25.class_text!r}): {why}"))
                continue
            if matched != sec.sec_id or f25.exchange in REGIONAL_EXCHANGES:
                continue
            eff = effective_date(sub.filing_date)
            continued = bool(ctx.listed_today) or ctx.seen_after(
                (_d(eff) + timedelta(days=5)).isoformat())
            if continued:
                before, after = exchanges_around(self.edgar, cik, filings, _d(sub.filing_date))
                if withdrawal_kind(f25.exchange, before, after) == "secondary":
                    continue
            if any(e.exchange == f25.exchange and abs((_d(e.form25_sub.filing_date) - _d(sub.filing_date)).days)
                   <= SAME_EVENT_DAYS for e in events if e.form25_sub):
                continue
            ticker = ctx.ticker_on(sub.filing_date) or ticker_last
            lt = self._last_trade(cik, filings, f25, ticker, _d(sub.filing_date))
            anchor = lt.day.isoformat() if lt.day else sub.filing_date
            rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=anchor, name=sec.name,
                                                 expected_name=ctx.expected_name, kind=sec.kind, form25=sub)
            events.append(self._event(sec, cik, ticker, eff, rec, lt, f25, sub, continued))
        if not events and ctx.listed_today is False:
            ev = self._fallback(ctx, cik, filings, ticker_last)
            if ev is not None:
                events.append(ev)
            else:
                review.append(ReviewItem(sec.sec_id, ticker_last, cik, "ended_without_delisting",
                                         "not listed today and no Form 25 or delisting filing found",
                                         last_seen=ctx.last_seen))
        return events, review

    def _event(self, sec: Security, cik: int, ticker: str, delist_date: str, rec: DelistRecord, lt: LastTrade,
               f25: Form25 | None, sub: EdgarSubmission | None, continued: bool,
               extra_flags: tuple[str, ...] = ()) -> DelistingEvent:
        rec.sec_id = sec.sec_id
        rec.delist_date = delist_date
        flags = list(lt.flags) + list(extra_flags)
        if rec.bucket is CrspBucket.EXCHANGE_TRANSFER:
            if continued:
                rec.successor_sec_id = sec.sec_id
            else:
                flags.append("successor_unknown")
        ev_flags = rec.evidence.setdefault("flags", [])
        for f in flags:
            if f not in ev_flags:
                ev_flags.append(f)
        return DelistingEvent(sec.sec_id, cik, ticker, delist_date, rec, lt, f25, sub,
                              f25.exchange if f25 else "", flags)

    def _fallback(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
                  ticker: str) -> DelistingEvent | None:
        sec = ctx.security
        rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=ctx.last_seen, name=sec.name,
                                             expected_name=ctx.expected_name, kind=sec.kind, form25=None)
        ev = rec.evidence or {}
        if rec.bucket is CrspBucket.UNKNOWN and not ev.get("deregistered"):
            return None
        delist_filing = ev.get("delist_filing") or {}
        ended_by = (delist_filing.get("filing_date") or (ev.get("revoked_filing") or {}).get("filing_date")
                    or (ev.get("anchor_8k") or {}).get("filing_date")
                    or (ev.get("dereg_filing") or {}).get("filing_date") or ctx.last_seen)
        delist_date = effective_date(ended_by) if delist_filing else ended_by
        lt = self._last_trade(cik, filings, None, ticker, _d(ended_by))
        if lt.day is None:
            lt = LastTrade(_d(ctx.last_seen), "", ("last_trade_date_unconfirmed",))
        return self._event(sec, cik, ticker, delist_date, rec, lt, None, None, False, ("no_form25",))
```

Notes for the implementer:
- `test_aet_merger_delisting` depends on the classifier finding the 2.01+3.01+5.01 8-K near the anchor (2018-11-28): the fake 8-K is filed that day, so `_pick_8k_near` finds it and the fingerprint gives 231.
- In `test_ambiguous_class_goes_to_review` the AET Form 25 says "Common Stock" and both siblings are common with classes A and B, so `match_security` returns `ambiguous class`.
- In `test_ended_without_delisting` the issuer has no Form 25, no 8-K and no Form 15, so the fallback classification is `unknown` without `deregistered`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/delistings.py tests/test_delistings.py
git commit -m "feat(delistings): find, date and classify each delisting of a security"
```

---

### Task 16: Re-key the DLRET table to `(sec_id, delist_date)`

**Files:**
- Modify: `src/delist_detection/reconstruction.py`
- Modify: `tests/test_reconstruction.py` (port every test to the new functions; delete tests of removed functions)
- Test: `tests/test_delisting_rows.py`

**Interfaces:**
- Consumes: `DelistRecord.sec_id`, `.delist_date` (Task 12); `store.DELISTINGS_COLUMNS` (Task 1).
- Produces:
  - `EnrichedDelistRecord` gains `sec_id: str | None = None` and `delist_date: str | None = None` (after `review_flags`); `enrich()` copies them from the record.
  - `build_delistings_table(records, *, last_trade_closes=None, payouts=None, exchanges=None, merger_terms=None, recovery_ratios=None, payout_sources=None, payout_confidences=None, payout_flags=None) -> list[EnrichedDelistRecord]` — same as the old `build_dlret_table`, but every map is keyed by `sec_id` (all delistings of the security) or `(sec_id, delist_date)` (one delisting), via the existing `_lookup`.
  - `delisting_row(e: EnrichedDelistRecord, **extra) -> dict` — one `delistings.csv` row; `extra` may set `exchange`, `last_trade_date`, `last_trade_date_source`, `successor_sec_id`, `acquirer_sec_id`, `raw_payout_per_share`, `raw_payout_source`, `raw_payout_confidence`.
  - `load_float_overrides(path, value_col: str) -> dict[str | tuple[str, str], float]` — columns `sec_id`, `<value_col>`, optional `delist_date`.
  - `load_merger_terms_overrides(path) -> dict[str | tuple[str, str], dict]` — columns `sec_id`, `cash_per_share`, `stock_ratio`, `acquirer_price`, `acquirer_ticker`, optional `delist_date`.
  - `unmatched_override_keys(overrides: Mapping, events: Iterable[tuple[str, str]]) -> list` — keys that name no delisting.
- Removed: `DLRET_TABLE_COLUMNS`, `build_dlret_table`, `enriched_to_row`, `write_dlret_csv`, `load_merger_terms_csv`, `load_float_map_csv`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_delisting_rows.py
import math

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.reconstruction import (
    build_delistings_table, delisting_row, load_float_overrides, load_merger_terms_overrides,
    unmatched_override_keys,
)
from delist_detection.store import DELISTINGS_COLUMNS


def _rec(sec_id, dd, bucket=CrspBucket.MERGER, code=231):
    return DelistRecord("AET", 1122304, "2018-11-28", code, bucket, "high", "M&A",
                        evidence={"flags": [], "delist_filing": {"form": "25-NSE", "filing_date": "2018-11-29",
                                                                 "accession": "0000876661-18-001269"},
                                  "anchor_8k": {"items": "2.01,3.01,5.01"}, "name": "AETNA INC",
                                  "resolution_source": "security_master"},
                        sec_id=sec_id, delist_date=dd)


def test_table_keys_by_sec_id_and_delist_date():
    recs = [_rec("BBG1", "2018-12-09"), _rec("BBG1", "2010-01-01")]
    t = build_delistings_table(
        recs,
        last_trade_closes={"BBG1": 200.0, ("BBG1", "2018-12-09"): 212.70},
        merger_terms={("BBG1", "2018-12-09"): {"cash_per_share": 145.0, "stock_ratio": 0.8378,
                                               "acquirer_price": 80.27, "acquirer_ticker": "CVS"}},
    )
    assert t[0].last_trade_close == 212.70 and t[1].last_trade_close == 200.0
    assert t[0].sec_id == "BBG1" and t[0].delist_date == "2018-12-09"
    assert math.isclose(t[0].terminal_value, 145.0 + 0.8378 * 80.27)


def test_delisting_row_has_every_column_and_extras():
    (e,) = build_delistings_table([_rec("BBG1", "2018-12-09")], last_trade_closes={"BBG1": 212.70},
                                  payouts={"BBG1": 212.25})
    row = delisting_row(e, exchange="NYSE", last_trade_date="2018-11-28", last_trade_date_source="midas",
                        acquirer_sec_id="BBG000BGRY34", raw_payout_per_share=212.25)
    assert set(row) <= set(DELISTINGS_COLUMNS)
    assert row["sec_id"] == "BBG1" and row["delist_date"] == "2018-12-09" and row["exchange"] == "NYSE"
    assert row["delist_filing_accession"] == "0000876661-18-001269"
    assert row["anchor_8k_items"] == "2.01,3.01,5.01" and row["resolved_name"] == "AETNA INC"
    assert row["bucket"] == "merger" and row["dlret_method"] == "cash_only"


def test_unknown_without_price_has_blank_dlret():
    rec = _rec("BBG2", "2019-01-01", bucket=CrspBucket.UNKNOWN, code=None)
    (e,) = build_delistings_table([rec])
    assert delisting_row(e)["dlret"] is None


def test_loaders(tmp_path):
    p = tmp_path / "lt.csv"
    p.write_text("sec_id,last_trade_close,delist_date\nBBG1,212.70,2018-12-09\nBBG2,5.5,\n")
    assert load_float_overrides(p, "last_trade_close") == {("BBG1", "2018-12-09"): 212.70, "BBG2": 5.5}
    bad = tmp_path / "bad.csv"
    bad.write_text("ticker,last_trade_close\nAET,1\n")
    with pytest.raises(ValueError, match="sec_id"):
        load_float_overrides(bad, "last_trade_close")
    t = tmp_path / "terms.csv"
    t.write_text("sec_id,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker,delist_date\n"
                 "BBG1,145,0.8378,80.27,CVS,2018-12-09\n")
    assert load_merger_terms_overrides(t) == {("BBG1", "2018-12-09"): {
        "cash_per_share": 145.0, "stock_ratio": 0.8378, "acquirer_price": 80.27, "acquirer_ticker": "CVS"}}
    t.write_text("sec_id,stock_ratio\nBBG1,0.5\n")
    with pytest.raises(ValueError, match="incomplete stock leg"):
        load_merger_terms_overrides(t)


def test_unmatched_override_keys():
    events = [("BBG1", "2018-12-09")]
    assert unmatched_override_keys({"BBG1": 1.0, ("BBG1", "2018-12-09"): 2.0}, events) == []
    assert unmatched_override_keys({"BBG9": 1.0, ("BBG1", "2020-01-01"): 2.0}, events) == \
        ["BBG9", ("BBG1", "2020-01-01")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delisting_rows.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

In `src/delist_detection/reconstruction.py`:

1. Add the two fields at the end of `EnrichedDelistRecord`:

```python
    review_flags: tuple[str, ...] = ()
    sec_id: str | None = None
    delist_date: str | None = None
```

and in `enrich()`'s `return EnrichedDelistRecord(...)` add `sec_id=record.sec_id, delist_date=record.delist_date,`.

2. Replace everything from `DLRET_TABLE_COLUMNS = [` to the end of the file with:

```python
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
        key, date = rec.sec_id or rec.ticker.upper(), rec.delist_date
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
            extra_flags=_lookup(payout_flags, key, date) or (),
        ))
    return out


_ROW_EXTRAS = ("exchange", "last_trade_date", "last_trade_date_source", "successor_sec_id", "acquirer_sec_id",
               "raw_payout_per_share", "raw_payout_source", "raw_payout_confidence")


def delisting_row(e: EnrichedDelistRecord, **extra) -> dict:
    unknown = set(extra) - set(_ROW_EXTRAS)
    if unknown:
        raise TypeError(f"delisting_row: unexpected field(s) {sorted(unknown)}")
    ev = e.evidence or {}
    df = ev.get("delist_filing") or {}
    ak = ev.get("anchor_8k") or {}
    dr = ev.get("dereg_filing") or {}
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
        "delist_filing_form": df.get("form"), "delist_filing_date": df.get("filing_date"),
        "delist_filing_accession": df.get("accession"), "anchor_8k_items": ak.get("items"),
        "dereg_form": dr.get("form"), "resolved_name": ev.get("name"),
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
```

Keep `_lookup`, `_DLRET_BLANK_IN_TABLE`, `enrich`, `_dlret_confidence` unchanged. Remove the now-unused `_fmt` if nothing else uses it.

3. Port `tests/test_reconstruction.py`: every test of `enrich`/`_dlret_confidence` stays; every test of `build_dlret_table` becomes the same test against `build_delistings_table` with records carrying `sec_id`/`delist_date` and maps keyed by them; tests of `enriched_to_row`/`write_dlret_csv` become `delisting_row` tests; tests of `load_float_map_csv`/`load_merger_terms_csv` become loader tests with a `sec_id` column. Delete assertions about `DLRET_TABLE_COLUMNS`.

4. Search for other users of the removed names and leave them for their own tasks (they are rewritten in Tasks 17–19):

```bash
grep -rn "build_dlret_table\|write_dlret_csv\|enriched_to_row\|load_float_map_csv\|load_merger_terms_csv\|DLRET_TABLE_COLUMNS" src scripts tests
```

Expected after this task: hits only in `scripts/classify_universe.py`, `scripts/compute_corrected_returns.py` and `tests/test_classify_universe_outputs.py` (all rewritten in Tasks 17–18). Mark `tests/test_classify_universe_outputs.py` with `pytest.skip("rewritten in Task 17", allow_module_level=True)` at the top until Task 17 replaces it, so the suite stays green.

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delisting_rows.py tests/test_reconstruction.py -v && ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -p no:warnings`
Expected: all pass (the skipped module reported as skipped)

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/reconstruction.py tests/test_reconstruction.py tests/test_delisting_rows.py tests/test_classify_universe_outputs.py
git commit -m "refactor(reconstruction): key the DLRET table by (sec_id, delist_date)"
```

---

### Task 17: Pipeline and the `classify_universe.py` CLI

**Files:**
- Create: `src/delist_detection/pipeline.py`
- Rewrite: `scripts/classify_universe.py`
- Delete: `src/delist_detection/av_listing.py`, `src/delist_detection/raw_tiingo.py`, `tests/test_raw_tiingo.py`
- Modify: `src/delist_detection/names.py` (remove `MemberNames` and its `csv`/`bisect`/`Path` imports), `tests/test_names.py` (drop `MemberNames` tests), `tests/test_resolver_member_names.py` (use a plain callable instead of `MemberNames`)
- Rewrite: `tests/test_classify_universe_outputs.py` → `tests/test_pipeline.py` (delete the old file)

**Interfaces:**
- Consumes: everything from Tasks 1–16; `payout_gate.gate_payouts`, `DEFAULT_TOL`; `PayoutExtractor.extract(record, last_close=...)`; `LLMMergerTermsExtractor.extract(record)`.
- Produces:
  - `Clients` dataclass: `edgar`, `resolver`, `classifier`, `figi`, `ftd_client`, `midas=None`, `halts=None`, `payout_extractor=None`, `llm_extractor=None`
  - `Overrides` dataclass: `last_trade_closes: dict`, `merger_terms: dict`, `recoveries: dict` (keys `sec_id` or `(sec_id, delist_date)`)
  - `RunSummary` dataclass: `counts: dict[str, int]` (rows per table), `buckets: dict[str, int]`, `figi_sources: dict[str, int]`, `review_flags: dict[str, int]`
  - `run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path, tol: float = DEFAULT_TOL, limit: int | None = None, log=print_to_stderr) -> RunSummary`
  - `default_clients(index, *, cache_dir: Path, extract_payouts: bool = True, extract_llm: bool = False, llm_model: str | None = None, use_midas: bool = True, use_halts: bool = True) -> Clients`
  - `successor_from_8k12b(search, figi, *, name: str, day: date, exclude_cik: int) -> tuple[int, str] | None` — `(cik, ticker)` of a successor issuer named in an 8-K12B, where `search(q, forms, lo, hi) -> list[dict]` returns EDGAR full-text-search hits (`_source` dicts with `ciks`, `display_names`)

Pipeline order (spec 8.1–8.10), all computed before anything is written:
1. Eras from the index (`limit` keeps the first N eras). Issuer CIK per era: `resolver.resolve(era.ticker, era.last).cik` (pins travel through the resolver's `cik_map`, names through `member_names`).
2. `FtdIndex.load` for the eras' tickers and observed CUSIPs over `[max(2004-01-01, earliest first − 30 d), min(today, latest last + 400 d)]`.
3. `era_cusips` → `FigiResolver.resolve_many` → `build_securities`; resolution flags (`no_figi`, `observation_unresolved`) become review items.
4. `ftd.extend` with each security's CUSIPs (the first CUSIP of each era) up to today, to follow renamed and post-delisting symbols.
5. Per security: `listed_today`, a `SecurityContext` (sightings = observations + FTD rows of its CUSIPs), `DelistingFinder.find`.
6. Override keys must all match a delisting (`unmatched_override_keys`) or the run raises `ValueError` listing them (A2).
7. Closes: override, else `ftd.close_after(last_trade_date, cusip=..., symbol=ticker)`; a lagged row adds `ftd_close_lagged`; none adds `no_last_close`.
8. Merger delistings: regex payout (`PayoutExtractor.extract(record, last_close=...)`), LLM terms when enabled, then `gate_payouts` keyed by `(sec_id, delist_date)`; the acquirer's price is its FTD close on the target's last trade date (acquirer symbol rows loaded with `ftd.extend(..., symbols=...)`); the acquirer's security is resolved by its FTD CUSIP through OpenFIGI and added with `observed=False` (D18).
9. `exchange_transfer` delistings flagged `successor_unknown`: `successor_from_8k12b`; a hit is resolved to a FIGI by ticker and added with `observed=False`.
10. `build_delistings_table` → `delisting_row`; ticker and CUSIP ranges from sightings (clipped at the last delisting's last trade date unless the security is listed today; open when listed today); review rows from review items plus every delisting with `review_flags`.
11. Write `securities`, `ticker_history`, `cusip_history`, `delistings`, `payouts`, `review` with `store.write_table`.

- [ ] **Step 1: Extend `FtdIndex.extend` to take symbols**

Change the Task 5 signature to `extend(self, client, lo, hi, *, cusips=(), symbols=())` and scan when either set has something new (symbols already loaded for the same window are not rescanned: keep `self._loaded_symbols: set[str]` filled by `load` and `extend`). Add to `tests/test_ftd.py`:

```python
def test_extend_with_symbols(tmp_path):
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": SAMPLE}))
    c = FtdClient(tmp_path)
    idx = FtdIndex.load(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"AET"})
    assert idx.by_symbol("CVS") == []
    idx.extend(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"CVS"})
    assert idx.close_after(date(2018, 11, 28), symbol="CVS") == (80.27, "2018-11-29", False)
```

- [ ] **Step 2: Write the failing pipeline tests**

```python
# tests/test_pipeline.py
import csv
from datetime import date
from pathlib import Path

import pytest

from delist_detection.classifier import DelistClassifier
from delist_detection.edgar import EdgarBlocked, EdgarSubmission
from delist_detection.ftd import FtdRow
from delist_detection.observations import Observation, ObservationIndex
from delist_detection.pipeline import Clients, Overrides, run, successor_from_8k12b
from delist_detection.store import read_table, table_path
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "form25"
AET_RAW = (FIX / "aet_25nse.txt").read_text(encoding="utf-8", errors="replace")

AET_FIGI = {"data": [{"figi": "BBG000FJLFX8", "compositeFIGI": "BBG000FJLFX8", "exchCode": "US", "ticker": "AET",
                      "name": "AETNA INC", "securityType": "Common Stock", "securityType2": "Common Stock"}]}
LIVE_FIGI = {"data": [{"figi": "BBG000LIVE01", "compositeFIGI": "BBG000LIVE01", "exchCode": "US", "ticker": "LIVE",
                       "name": "LIVE CO", "securityType": "Common Stock", "securityType2": "Common Stock"},
                      {"figi": "BBG000LIVE02", "compositeFIGI": "BBG000LIVE01", "exchCode": "UN", "ticker": "LIVE",
                       "name": "LIVE CO", "securityType": "Common Stock", "securityType2": "Common Stock"}]}


class _Figi:
    def __init__(self):
        self.answers = {("ID_CUSIP", "00817Y108"): AET_FIGI, ("TICKER", "LIVE"): LIVE_FIGI,
                        ("COMPOSITE_ID_BB_GLOBAL", "BBG000LIVE01"): LIVE_FIGI}

    def map(self, jobs, use_cache=True):
        return [self.answers.get((j["idType"], j["idValue"]), {"warning": "No identifier found."}) for j in jobs]

    def filter(self, query, **fields):
        return []


class _FtdClient:
    ROWS = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0),
            FtdRow("2018-11-29", "00817Y108", "AET", "AETNA INC.(NEW)", 212.70)]

    def urls_for(self, lo, hi):
        return ["mem"]

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self.ROWS:
            if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                yield r


def _clients(fake_edgar, ftd_rows=None):
    fake_edgar.submissions_by_cik[1122304] = [
        EdgarSubmission("0000876661-18-001269", "25-NSE", "2018-11-29", "", "", "primary_doc.xml"),
        EdgarSubmission("0001122304-18-000178", "8-K", "2018-11-28", "2018-11-28", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("0001122304-18-000184", "15-12B", "2018-12-10", "", "", "f.htm"),
    ]
    fake_edgar.submissions_by_cik[777] = []
    fake_edgar.company_map["AET"] = {"cik_str": 1122304, "ticker": "AET", "title": "AETNA INC /PA/"}
    fake_edgar.company_map["LIVE"] = {"cik_str": 777, "ticker": "LIVE", "title": "LIVE CO"}
    fake_edgar.raws["0000876661-18-001269"] = AET_RAW
    fake_edgar.texts["0001122304-18-000178"] = ("Item 3.01 Notice. trading suspended prior to the opening of trading "
                                                "on November 29, 2018 " + "x" * 300)
    ftd = _FtdClient()
    if ftd_rows is not None:
        ftd.ROWS = ftd_rows
    obs = [Observation("AET", "2017-06-30", "AETNA INC", cik=1122304),
           Observation("AET", "2018-06-29", "AETNA INC", cik=1122304),
           Observation("LIVE", "2025-06-30", "LIVE CO", cik=777)]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, member_names=index.name_on, cik_map=index.cik_pin_on)
    return index, Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                          figi=_Figi(), ftd_client=ftd)


def test_end_to_end_tables(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    secs = {r["sec_id"]: r for r in read_table("securities", table_path(tmp_path, "securities"))}
    assert set(secs) == {"BBG000FJLFX8", "BBG000LIVE01"}
    assert secs["BBG000FJLFX8"]["figi_source"] == "cusip" and secs["BBG000LIVE01"]["figi_source"] == "ticker"
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert (d["sec_id"], d["delist_date"], d["bucket"]) == ("BBG000FJLFX8", "2018-12-09", "merger")
    assert d["last_trade_date"] == "2018-11-28" and d["last_trade_close"] == "212.700000"
    assert d["exchange"] == "NYSE"
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    aet = [r for r in th if r["sec_id"] == "BBG000FJLFX8"]
    assert aet == [{"sec_id": "BBG000FJLFX8", "ticker": "AET", "exchange": "NYSE", "valid_from": "2017-06-30",
                    "valid_to": "2018-11-28", "source": "observation"}]
    live = [r for r in th if r["sec_id"] == "BBG000LIVE01"]
    assert live[0]["valid_to"] == ""                                  # listed today: open range
    ch = read_table("cusip_history", table_path(tmp_path, "cusip_history"))
    assert [(r["cusip"], r["valid_from"], r["valid_to"]) for r in ch] == [("00817Y108", "2018-06-29", "2018-11-28")]
    assert summary.counts["delistings"] == 1 and summary.buckets == {"merger": 1}


def test_missing_close_leaves_blank_dlret_and_review(fake_edgar, tmp_path):
    rows = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0)]    # nothing after the last trade
    index, clients = _clients(fake_edgar, ftd_rows=rows)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["last_trade_close"] == "" and d["dlret"] == ""
    assert "no_last_close" in d["review_flags"]
    review = read_table("review", table_path(tmp_path, "review"))
    assert any(r["sec_id"] == "BBG000FJLFX8" and "no_last_close" in r["review_flags"] for r in review)


def test_unmatched_override_stops_before_writing(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    with pytest.raises(ValueError, match="BBG999"):
        run(index, clients, Overrides(last_trade_closes={"BBG999": 1.0}), out_dir=tmp_path, log=lambda *_: None)
    assert not list(tmp_path.glob("*.csv"))


def test_refusal_mid_run_keeps_previous_outputs(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    before = {p.name: p.read_text() for p in tmp_path.glob("*.csv")}

    def blocked(*a, **k):
        raise EdgarBlocked("SEC returned 403")

    clients.edgar.fetch_filing_raw = blocked
    with pytest.raises(EdgarBlocked):
        run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert {p.name: p.read_text() for p in tmp_path.glob("*.csv")} == before


def test_successor_from_8k12b():
    hits = [{"_source": {"ciks": ["0001288776"], "display_names": ["GOOGLE INC.  (GOOG)  (CIK 0001288776)"]}},
            {"_source": {"ciks": ["0001652044"], "display_names": ["Alphabet Inc.  (GOOGL, GOOG)  (CIK 0001652044)"]}}]
    got = successor_from_8k12b(lambda q, forms, lo, hi: hits, None, name="GOOGLE INC", day=date(2015, 10, 2),
                               exclude_cik=1288776)
    assert got == (1652044, "GOOGL")
    assert successor_from_8k12b(lambda *a: [], None, name="X", day=date(2015, 10, 2), exclude_cik=1) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'delist_detection.pipeline'`

- [ ] **Step 4: Write `src/delist_detection/pipeline.py`**

```python
# src/delist_detection/pipeline.py
"""End-to-end run: observations -> security master and delistings (spec §8).

Everything is computed first and written last, so a refusal or a bad override
file never leaves a half-written output over the previous complete one.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .crsp_codes import CrspBucket
from .delistings import DelistingEvent, DelistingFinder, ReviewItem, SecurityContext
from .figi_resolution import accept, us_candidates
from .form25 import SecurityRef
from .ftd import FtdIndex
from .listing_status import listed_today
from .observations import ObservationIndex, normalize_ticker
from .payout_gate import DEFAULT_TOL, gate_payouts
from .reconstruction import _lookup, build_delistings_table, delisting_row, unmatched_override_keys
from .security_master import (
    FigiResolver, Security, build_securities, era_cusips, era_last_seen, ranges_from_sightings,
)
from .store import table_path, write_table

FTD_START = date(2004, 1, 1)


@dataclass
class Clients:
    edgar: Any
    resolver: Any
    classifier: Any
    figi: Any
    ftd_client: Any
    midas: Any = None
    halts: Any = None
    payout_extractor: Any = None
    llm_extractor: Any = None


@dataclass
class Overrides:
    last_trade_closes: dict = field(default_factory=dict)
    merger_terms: dict = field(default_factory=dict)
    recoveries: dict = field(default_factory=dict)


@dataclass
class RunSummary:
    counts: dict[str, int]
    buckets: dict[str, int]
    figi_sources: dict[str, int]
    review_flags: dict[str, int]


def _stderr(*parts) -> None:
    print(*parts, file=sys.stderr, flush=True)


def _d(s: str) -> date:
    return date.fromisoformat(s)


def successor_from_8k12b(search: Callable, figi, *, name: str, day: date,
                         exclude_cik: int) -> tuple[int, str] | None:
    """The successor issuer that filed an 8-K12B naming `name` around `day`."""
    hits = search(f'"{name}"', "8-K12B,8-K12G3", day - timedelta(days=30), day + timedelta(days=60))
    for h in hits:
        src = h.get("_source", h)
        for cik_s, disp in zip(src.get("ciks") or [], src.get("display_names") or []):
            cik = int(cik_s)
            if cik == exclude_cik:
                continue
            m = re.search(r"\(([A-Z0-9.\-]+)(?:,|\))", disp)
            if m:
                return cik, normalize_ticker(m.group(1))
    return None


def _sightings(sec: Security, ftd: FtdIndex, cusips: list[str]) -> list[tuple[str, str, str]]:
    out = [(o.as_of, o.ticker, "observation") for e in sec.eras for o in e.observations]
    for c in cusips:
        out += [(r.date, r.symbol, "ftd") for r in ftd.by_cusip(c)]
    return sorted(set(out))


def _ticker_on(sig: list[tuple[str, str, str]]) -> Callable[[str], str | None]:
    def f(day: str) -> str | None:
        before = [t for d, t, _ in sig if d <= day]
        if before:
            return before[-1]
        return sig[0][1] if sig else None
    return f


def run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path,
        tol: float = DEFAULT_TOL, limit: int | None = None, log: Callable = _stderr) -> RunSummary:
    eras = index.eras()
    if limit:
        eras = eras[:limit]
    era_by_key = {e.key: e for e in eras}
    log(f"{len(eras)} ticker eras")

    if not eras:
        raise ValueError("no observations to process")

    # 1. FTD rows for the eras' tickers (first: they date each era's real last sighting)
    lo = max(FTD_START, min(_d(e.first) for e in eras) - timedelta(days=30))
    hi = min(date.today(), max(_d(e.last) for e in eras) + timedelta(days=400))
    ftd = FtdIndex.load(clients.ftd_client, lo, hi, symbols={e.ticker for e in eras},
                        cusips={c for e in eras for c in e.cusips})

    # 2. issuer CIK per era, resolved at the era's last sighting: index snapshots can
    # be months apart, and the resolver's Form 25 search is anchored on this date.
    ciks = {e.key: clients.resolver.resolve(e.ticker, era_last_seen(e, ftd)).cik for e in eras}

    # 3. FIGI per era -> securities
    cusips = {e.key: era_cusips(e, ftd) for e in eras}
    resolutions = FigiResolver(clients.figi).resolve_many(eras, ciks=ciks, cusips=cusips)
    securities = build_securities(resolutions, era_by_key, ciks)
    review: list[ReviewItem] = []
    for key, res in resolutions.items():
        era = era_by_key[key]
        for flag in res.flags:
            review.append(ReviewItem(res.sec_id or "", era.ticker, ciks.get(key), flag,
                                     f"{era.key} {era.name or ''}".strip(), last_seen=era.last))
    log(f"{len(securities)} securities; FIGI sources "
        f"{dict(Counter(s.figi_source for s in securities.values()))}")

    # 4. each security's CUSIPs over its whole life
    sec_cusips = {sid: list(dict.fromkeys(cusips[e.key][0] for e in s.eras if cusips[e.key]))
                  for sid, s in securities.items()}
    ftd.extend(clients.ftd_client, lo, date.today(), cusips={c for v in sec_cusips.values() for c in v})

    # 5. delistings
    siblings: dict[int, list[SecurityRef]] = defaultdict(list)
    for s in securities.values():
        if s.issuer_cik is not None:
            siblings[s.issuer_cik].append(SecurityRef(s.sec_id, s.share_class, s.kind))
    finder = DelistingFinder(clients.edgar, clients.classifier, midas=clients.midas, halts=clients.halts)
    events: list[DelistingEvent] = []
    listed: dict[str, bool | None] = {}
    sightings = {sid: _sightings(s, ftd, sec_cusips[sid]) for sid, s in securities.items()}
    for i, s in enumerate(sorted(securities.values(), key=lambda s: s.sec_id), 1):
        listed[s.sec_id] = listed_today(clients.figi, s.sec_id, edgar=clients.edgar, cik=s.issuer_cik)
        sig = sightings[s.sec_id]
        ctx = SecurityContext(
            security=s,
            siblings=siblings.get(s.issuer_cik) or [SecurityRef(s.sec_id, s.share_class, s.kind)],
            ticker_on=_ticker_on(sig),
            last_seen=sig[-1][0] if sig else max(e.last for e in s.eras),
            seen_after=lambda day, sig=sig: any(d > day for d, _, _ in sig),
            listed_today=listed[s.sec_id],
            expected_name=s.eras[-1].name if s.eras else None,
        )
        evs, rv = finder.find(ctx)
        events += evs
        review += rv
        if i % 50 == 0:
            log(f"[{i}/{len(securities)}] securities searched; {len(events)} delistings so far")

    # 6. every override must name a delisting
    keys = [(e.sec_id, e.delist_date) for e in events]
    bad = []
    for name, m in (("--last-trade-closes", overrides.last_trade_closes),
                    ("--merger-terms", overrides.merger_terms), ("--recoveries", overrides.recoveries)):
        bad += [f"{name}: {k}" for k in unmatched_override_keys(m, keys)]
    if bad:
        raise ValueError("override rows that match no delisting: " + "; ".join(map(str, bad)))

    # 7. last-trade closes
    closes: dict[tuple[str, str], float] = {}
    for e in events:
        key = (e.sec_id, e.delist_date)
        given = _lookup(overrides.last_trade_closes, e.sec_id, e.delist_date)
        if given is not None:
            closes[key] = given
            continue
        if e.last_trade.day is None:
            e.record.evidence["flags"].append("no_last_close")
            continue
        cusip = next((c for c in sec_cusips.get(e.sec_id, [])), None)
        got = (ftd.close_after(e.last_trade.day, cusip=cusip) if cusip else None) \
            or ftd.close_after(e.last_trade.day, symbol=e.ticker)
        if got is None:
            e.record.evidence["flags"].append("no_last_close")
            continue
        price, _, lagged = got
        closes[key] = price
        if lagged:
            e.record.evidence["flags"].append("ftd_close_lagged")

    # 8. merger payouts, LLM terms, acquirer prices and securities
    payouts_raw, llm_terms = {}, {}
    mergers = [e for e in events if e.record.bucket is CrspBucket.MERGER]
    for e in mergers:
        key = (e.sec_id, e.delist_date)
        if clients.payout_extractor is not None:
            payouts_raw[key] = clients.payout_extractor.extract(e.record, last_close=closes.get(key))
        if clients.llm_extractor is not None:
            t = clients.llm_extractor.extract(e.record)
            if t is not None:
                llm_terms[key] = t
    trade_day = {(e.sec_id, e.delist_date): e.last_trade.day for e in events}
    acq_symbols = {normalize_ticker(t.acquirer_ticker) for t in llm_terms.values() if t.acquirer_ticker}
    acq_symbols |= {normalize_ticker(v["acquirer_ticker"]) for v in overrides.merger_terms.values()
                    if v.get("acquirer_ticker")}
    if acq_symbols:
        days = [d for d in trade_day.values() if d]
        if days:
            ftd.extend(clients.ftd_client, min(days) - timedelta(days=10), max(days) + timedelta(days=10),
                       symbols=acq_symbols)
    by_delist_date = {dd: day for (_, dd), day in trade_day.items()}

    def acquirer_price(ticker: str, delist_date: str | None) -> float | None:
        day = by_delist_date.get(delist_date)
        got = ftd.close_after(day, symbol=ticker) if day and ticker else None
        return got[0] if got else None

    regex = {k: pr for k, pr in payouts_raw.items() if pr is not None and pr.value is not None}
    gated = gate_payouts(
        [(e.sec_id, e.delist_date) for e in mergers],
        {k: pr.value for k, pr in regex.items()}, {k: pr.source for k, pr in regex.items()},
        {k: pr.confidence for k, pr in regex.items()}, llm_terms, closes, overrides.merger_terms,
        acquirer_price, tol,
    )
    added: dict[str, Security] = {}
    acquirer_ids: dict[tuple[str, str], str] = {}
    for key, terms in gated.merged_terms.items():
        acq = normalize_ticker(terms.get("acquirer_ticker") or "")
        day = trade_day.get(key)
        if not acq or day is None:
            continue
        rows = ftd.by_symbol(acq, (day - timedelta(days=10)).isoformat(), (day + timedelta(days=10)).isoformat())
        cusip = Counter(r.cusip for r in rows).most_common(1)
        if not cusip:
            continue
        ans = clients.figi.map([{"idType": "ID_CUSIP", "idValue": cusip[0][0], "includeUnlistedEquities": True}])[0]
        cand = accept(us_candidates(ans.get("data") or []), ticker=acq, names=[], via_cusip=True)
        if cand is None:
            continue
        acquirer_ids[key] = cand.composite
        if cand.composite not in securities and cand.composite not in added:
            added[cand.composite] = Security(cand.composite, None, "COMMON", cand.name, cand.security_type,
                                             False, "cusip")
            sightings[cand.composite] = sorted({(r.date, r.symbol, "ftd") for r in rows})

    # 9. successors after a FIGI change
    # (search: EDGAR full-text search; wire the real one in default_clients via clients.edgar)
    successor_search = getattr(clients.edgar, "full_text_search", None)
    for e in events:
        if "successor_unknown" not in e.flags or successor_search is None:
            continue
        name = securities[e.sec_id].name
        day = e.last_trade.day or _d(e.delist_date)
        hit = successor_from_8k12b(successor_search, clients.figi, name=name, day=day, exclude_cik=e.cik)
        if hit is None:
            continue
        s_cik, s_ticker = hit
        ans = clients.figi.map([{"idType": "TICKER", "idValue": s_ticker.replace("-", "/")}])[0]
        cands = us_candidates(ans.get("data") or [])
        cand = cands[0] if len(cands) == 1 else None
        if cand is None:
            continue
        e.record.successor_sec_id = cand.composite
        e.record.evidence["flags"] = [f for f in e.record.evidence["flags"] if f != "successor_unknown"]
        if cand.composite not in securities and cand.composite not in added:
            added[cand.composite] = Security(cand.composite, s_cik, "COMMON", cand.name, cand.security_type,
                                             False, "ticker")
            sightings[cand.composite] = [(day.isoformat(), s_ticker, "ftd")]

    # 10. rows
    table = build_delistings_table(
        [e.record for e in events], last_trade_closes=closes, payouts=gated.payouts,
        exchanges={(e.sec_id, e.delist_date): e.exchange for e in events},
        merger_terms=gated.merged_terms, recovery_ratios=overrides.recoveries,
        payout_sources=gated.sources, payout_confidences=gated.confidences, payout_flags=gated.flags,
    )
    ev_by_key = {(e.sec_id, e.delist_date): e for e in events}
    delisting_rows, review_rows = [], []
    for enr in table:
        e = ev_by_key[(enr.sec_id, enr.delist_date)]
        pr = payouts_raw.get((e.sec_id, e.delist_date))
        delisting_rows.append(delisting_row(
            enr, exchange=e.exchange or None,
            last_trade_date=e.last_trade.day.isoformat() if e.last_trade.day else None,
            last_trade_date_source=e.last_trade.source or None,
            successor_sec_id=e.record.successor_sec_id,
            acquirer_sec_id=acquirer_ids.get((e.sec_id, e.delist_date)),
            raw_payout_per_share=pr.value if pr else None, raw_payout_source=pr.source if pr else None,
            raw_payout_confidence=pr.confidence if pr else None,
        ))
        if enr.review_flags:
            ak = (enr.evidence or {}).get("anchor_8k") or {}
            review_rows.append({"sec_id": enr.sec_id, "delist_date": enr.delist_date, "ticker": enr.ticker,
                                "cik": enr.cik, "bucket": enr.bucket.value,
                                "dlret": delisting_rows[-1]["dlret"], "review_flags": ";".join(enr.review_flags),
                                "reason": enr.reason, "anchor_8k": ak.get("items")})
    for r in review:
        review_rows.append({"sec_id": r.sec_id, "delist_date": r.delist_date, "ticker": r.ticker, "cik": r.cik,
                            "review_flags": r.flag, "reason": r.reason, "last_seen": r.last_seen})

    th_rows, ch_rows = [], []
    final = {}
    for e in sorted(events, key=lambda e: e.delist_date):
        final[e.sec_id] = e
    for sid, s in list(securities.items()) + list(added.items()):
        sig = sightings.get(sid, [])
        fe = final.get(sid)
        is_listed = bool(listed.get(sid))
        end = None
        if fe is not None and not is_listed and fe.last_trade.day is not None:
            end = fe.last_trade.day.isoformat()
        clipped = [x for x in sig if end is None or x[0] <= end]
        for rg in ranges_from_sightings(clipped, end=end, open_ended=is_listed):
            exch = fe.exchange if (fe is not None and end is not None and rg.valid_to == end) else None
            th_rows.append({"sec_id": sid, "ticker": rg.value, "exchange": exch, "valid_from": rg.valid_from,
                            "valid_to": rg.valid_to, "source": rg.source})
        cus = [(r.date, r.cusip, "ftd") for c in sec_cusips.get(sid, []) for r in ftd.by_cusip(c)]
        cus += [(o.as_of, o.cusip, "observation") for e in s.eras for o in e.observations if o.cusip]
        cus = [x for x in cus if end is None or x[0] <= end]
        for rg in ranges_from_sightings(cus, end=end, open_ended=is_listed):
            ch_rows.append({"sec_id": sid, "cusip": rg.value, "valid_from": rg.valid_from,
                            "valid_to": rg.valid_to, "source": rg.source})

    payout_rows = []
    for key, pr in payouts_raw.items():
        value = gated.payouts.get(key)
        payout_rows.append({"sec_id": key[0], "delist_date": key[1], "ticker": ev_by_key[key].ticker,
                            "payout_per_share": value, "confidence": gated.confidences.get(key, "none"),
                            "source": gated.sources.get(key, "none"),
                            "accession": (pr.accession if pr and value is not None else None)})

    # 11. write
    counts = {
        "securities": write_table("securities", [s.row() for s in securities.values()] +
                                  [s.row() for s in added.values()], table_path(out_dir, "securities")),
        "ticker_history": write_table("ticker_history", th_rows, table_path(out_dir, "ticker_history")),
        "cusip_history": write_table("cusip_history", ch_rows, table_path(out_dir, "cusip_history")),
        "delistings": write_table("delistings", delisting_rows, table_path(out_dir, "delistings")),
        "payouts": write_table("payouts", payout_rows, table_path(out_dir, "payouts")),
        "review": write_table("review", review_rows, table_path(out_dir, "review")),
    }
    flags = Counter(f.split(":", 1)[0] for r in review_rows for f in (r.get("review_flags") or "").split(";") if f)
    return RunSummary(counts, dict(Counter(e.record.bucket.value for e in events)),
                      dict(Counter(s.figi_source for s in securities.values())), dict(flags))
```

Notes for the implementer:
- In `test_end_to_end_tables`, the AET range ends at the last trade date (2018-11-28) and gets the Form 25 exchange; the FTD row dated 2018-11-29 (after the last trade) is clipped out of both histories. The CUSIP range therefore runs 2018-06-29 to 2018-11-28 (the first FTD row to the clip end).
- `test_refusal_mid_run_keeps_previous_outputs` works because every `write_table` call happens after all EDGAR reads.
- `LLMMergerTermsExtractor.extract` returns `MergerTerms` with `.acquirer_ticker`; `gate_payouts` is unchanged and treats the key's first element as an opaque id.
- If the golden `payout_gate` tests assume ticker keys, they still pass: the gate never parses the key.

- [ ] **Step 5: Add EDGAR full-text search to `EdgarClient`**

The successor search needs `EdgarClient.full_text_search(q: str, forms: str, lo: date, hi: date) -> list[dict]` returning the `hits.hits` list of `https://efts.sec.gov/LATEST/search-index?q=...&forms=...&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD`. Implement it in `edgar.py` with the same throttle, User-Agent and `check_response`; a network error or non-200 returns `[]` (not cached). Test it in `tests/test_sec_http.py` with the `_Session` fake (one hit parsed; a 403 raises `EdgarBlocked`).

- [ ] **Step 6: Rewrite `scripts/classify_universe.py`**

Keep `KNOWN_RENAMES` and `MANUAL_OVERRIDES` exactly as they are. Delete `AV_LISTING_CSV`, `AV_ACTIVE_CSV`, `ACQUIRER_RENAMES`, `_replace_on_success`, `_acquirer_price`, `load_cik_map_csv` and the old `main`. New body:

```python
"""Build the security master and the delisting table from caller observations.

Reads:  an observations CSV (ticker, as_of[, name, cusip, cik, sec_id])
Writes: output/securities.csv, ticker_history.csv, cusip_history.csv,
        delistings.csv, payouts.csv, review.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.edgar import EdgarBlocked
from delist_detection.observations import ObservationIndex, load_observations
from delist_detection.openfigi import OpenFigiBlocked
from delist_detection.payout_gate import DEFAULT_TOL
from delist_detection.pipeline import Overrides, default_clients, run
from delist_detection.reconstruction import load_float_overrides, load_merger_terms_overrides

KNOWN_RENAMES = {...unchanged...}
MANUAL_OVERRIDES: dict[str, int] = {...unchanged...}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--observations", required=True, help="CSV ticker,as_of[,name,cusip,cik,sec_id]")
    p.add_argument("--output-dir", default=str(ROOT / "output"))
    p.add_argument("--cache-dir", default=str(ROOT / "cache"))
    p.add_argument("--limit", type=int, default=None, help="process only the first N ticker eras")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--no-extract-payouts", action="store_true")
    p.add_argument("--no-midas", action="store_true", help="skip SEC MIDAS last-trade confirmation")
    p.add_argument("--no-halts", action="store_true", help="skip the Nasdaq halt feed")
    p.add_argument("--last-trade-closes", help="CSV sec_id,last_trade_close[,delist_date]")
    p.add_argument("--merger-terms", help="CSV sec_id,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker[,delist_date]")
    p.add_argument("--recoveries", help="CSV sec_id,recovery_ratio[,delist_date]")
    p.add_argument("--extract-merger-terms-llm", action="store_true")
    p.add_argument("--llm-model", default=None)
    p.add_argument("--merger-terms-sanity-tol", type=float, default=DEFAULT_TOL)
    args = p.parse_args()

    overrides = Overrides(
        last_trade_closes=load_float_overrides(args.last_trade_closes, "last_trade_close") if args.last_trade_closes else {},
        merger_terms=load_merger_terms_overrides(args.merger_terms) if args.merger_terms else {},
        recoveries=load_float_overrides(args.recoveries, "recovery_ratio") if args.recoveries else {},
    )
    index = ObservationIndex(load_observations(args.observations))
    clients = default_clients(
        index, cache_dir=Path(args.cache_dir), rename_map=KNOWN_RENAMES, manual_overrides=MANUAL_OVERRIDES,
        extract_payouts=not args.no_extract_payouts, extract_llm=args.extract_merger_terms_llm,
        llm_model=args.llm_model, use_midas=not args.no_midas, use_halts=not args.no_halts,
    )
    log = (lambda *a: None) if args.quiet else None
    summary = run(index, clients, overrides, out_dir=Path(args.output_dir), tol=args.merger_terms_sanity_tol,
                  limit=args.limit, **({"log": log} if log else {}))
    print("Rows written:", summary.counts)
    print("Delistings by bucket:", summary.buckets)
    print("FIGI sources:", summary.figi_sources)
    print("Review flags:", summary.review_flags)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EdgarBlocked, OpenFigiBlocked) as e:
        print(f"ABORTED: {e}", file=sys.stderr)
        sys.exit(2)
```

And in `pipeline.py` add `default_clients` (its signature gains `rename_map` and `manual_overrides`):

```python
def default_clients(index: ObservationIndex, *, cache_dir: Path, rename_map: dict | None = None,
                    manual_overrides: dict | None = None, extract_payouts: bool = True,
                    extract_llm: bool = False, llm_model: str | None = None, use_midas: bool = True,
                    use_halts: bool = True) -> Clients:
    from .classifier import DelistClassifier
    from .edgar import EdgarClient
    from .ftd import FtdClient
    from .midas import MidasClient
    from .nasdaq_halts import NasdaqHaltClient
    from .openfigi import OpenFigiClient, resolve_api_key
    from .payout_extractor import PayoutExtractor
    from .ticker_resolver import TickerResolver

    edgar = EdgarClient(cache_dir=cache_dir / "edgar")
    resolver = TickerResolver(edgar, rename_map=rename_map,
                              manual_overrides={k: v for k, v in (manual_overrides or {}).items() if v > 0},
                              cache_path=cache_dir / "ticker_resolution.json",
                              member_names=index.name_on, cik_map=index.cik_pin_on)
    llm = None
    if extract_llm:
        from .llm_client import default_llm_client
        from .llm_merger_extractor import LLMMergerTermsExtractor
        llm = LLMMergerTermsExtractor(edgar, default_llm_client(llm_model), cache_dir=cache_dir / "llm")
    return Clients(
        edgar=edgar, resolver=resolver, classifier=DelistClassifier(edgar, resolver),
        figi=OpenFigiClient(cache_dir / "openfigi", resolve_api_key()),
        ftd_client=FtdClient(cache_dir / "sec_data" / "ftd"),
        midas=MidasClient(cache_dir / "sec_data" / "midas") if use_midas else None,
        halts=NasdaqHaltClient(cache_dir / "nasdaq_halts") if use_halts else None,
        payout_extractor=PayoutExtractor(edgar) if extract_payouts else None,
        llm_extractor=llm,
    )
```

Note on the resolver cache: `cik_map` answers are never persisted (existing behavior), so observation pins behave like the old `--cik-map`.

- [ ] **Step 7: Delete the replaced modules and fix their tests**

```bash
git rm src/delist_detection/av_listing.py src/delist_detection/raw_tiingo.py tests/test_raw_tiingo.py tests/test_classify_universe_outputs.py
grep -rn "av_listing\|raw_tiingo\|MemberNames\|AV_LISTING_CSV\|RAW_TIINGO_DIR" src scripts tests
```

Remove `MemberNames` from `names.py` and its tests; in `tests/test_resolver_member_names.py` replace `MemberNames(...)`/`MemberNames.from_csv(...)` with a lambda `(ticker, date=None) -> name` that returns the same names (the resolver's `member_names` parameter is a callable). Every remaining grep hit must be in `scripts/compute_corrected_returns.py`, `scripts/verify_against_web.py` or `scripts/build_golden_fixtures.py`, which Tasks 18–19 rewrite.

- [ ] **Step 8: Run tests**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_ftd.py -v && ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -p no:warnings`
Expected: all pass

- [ ] **Step 9: Smoke-run the CLI offline-cached on a tiny input (network)**

```bash
printf 'ticker,as_of,name\nAET,2018-06-29,AETNA INC\nMETA,2024-06-28,META PLATFORMS INC CLASS A\n' > "$TMPDIR/obs_smoke.csv"
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py \
  --observations "$TMPDIR/obs_smoke.csv" --output-dir "$TMPDIR/out_smoke" --no-extract-payouts
```
Expected: exit 0; `delistings.csv` has one AET merger row with `last_trade_date` 2018-11-28 and `last_trade_close` 212.70; `securities.csv` has `BBG000FJLFX8` and `BBG000MM2P62`. (Needs network to www.sec.gov, efts.sec.gov, data.sec.gov, api.openfigi.com; the first FTD download is large.) If the numbers differ, debug with superpowers:systematic-debugging before continuing.

- [ ] **Step 10: Commit**

```bash
git add -A src/delist_detection scripts/classify_universe.py tests
git commit -m "feat(pipeline): observations to security master and delisting tables"
```

---

### Task 18: Handling code joins on `sec_id` and reads values from delisting rows

**Files:**
- Modify: `src/delist_detection/handling.py`, `src/delist_detection/qlib_adapter.py`, `src/delist_detection/__init__.py`
- Rewrite: `scripts/compute_corrected_returns.py`
- Modify tests: `tests/test_handling.py`, `tests/test_qlib_adapter.py`, `tests/test_qlib_adapter_bmp.py`, `tests/test_known_cases_bmp.py`, `tests/test_firm_month_correction.py` (whichever use the changed signatures)
- Test: `tests/test_qlib_adapter_sec_id.py`

**Interfaces:**
- Consumes: `store.write_table`/`read_table` (Task 1); `delistings.csv` columns (Task 16); `DelistRecord.successor_sec_id`.
- Produces (D14, A3):
  - `handling.build_train_label_adjustment(record, last_close, payout_per_share=None, recovery_ratio=DEFAULT_RECOVERY_RATIO)` — no `successor_map`; an exchange transfer re-links to `record.successor_sec_id`.
  - `handling.build_backtest_exit(record, last_close, payout_per_share=None, recovery_ratio=DEFAULT_RECOVERY_RATIO)` — no `successor_map`; `BacktestExit.successor_ticker` is renamed `successor_sec_id`.
  - `handling.adjustments_from_rows(rows: Iterable[Mapping[str, str]]) -> tuple[list[TrainLabelAdjustment], list[BacktestExit]]` replaces `apply_to_panel` (each row is a `delistings.csv` row; `last_trade_close` must be present, rows without it are skipped).
  - `qlib_adapter.load_delistings(path) -> pd.DataFrame`
  - `qlib_adapter.record_from_row(row) -> DelistRecord` — `observed_delist_date` = `last_trade_date`, else `delist_date`; carries `sec_id`, `delist_date`, `successor_sec_id`.
  - `qlib_adapter.row_payout(row) -> float | None` — `terminal_value` for a merger when present (covers cash + stock), else `payout_per_share`.
  - `qlib_adapter.inject_terminal_labels(panel, delistings_csv, horizon_days=21, label_col="LABEL", close_col="close")` — panel instruments are `sec_id`s; only rows dated on or before the last trade date are labeled.
  - `qlib_adapter.apply_backtest_exits(positions_df, delistings_csv, date_col="date", id_col="sec_id", price_col="price")`
  - `qlib_adapter.apply_bmp_corrections(panel, delistings_csv, return_col="monthly_return", close_col="close")` — exchange, last close, payout and recovery come from the row.
  - Removed: `load_classifications`, `_record_from_row`, every `payouts=`/`successor_map=`/`exchanges=`/`last_trade_closes=`/`recovery_ratios=` argument.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qlib_adapter_sec_id.py
import math

import numpy as np
import pandas as pd

from delist_detection.qlib_adapter import apply_backtest_exits, inject_terminal_labels, record_from_row, row_payout
from delist_detection.store import table_path, write_table


def _csv(tmp_path, **over):
    row = {"sec_id": "BBG1", "delist_date": "2025-04-05", "ticker": "ALTR", "cik": 1701732, "bucket": "merger",
           "crsp_code": 231, "confidence": "high", "reason": "M&A", "exchange": "NASDAQ",
           "last_trade_date": "2025-03-25", "last_trade_close": 111.85, "payout_per_share": 113.0,
           "terminal_value": 113.0, "dlret": 113.0 / 111.85 - 1, "dlret_method": "cash_only",
           "dlret_confidence": "high"}
    row.update(over)
    p = table_path(tmp_path, "delistings")
    write_table("delistings", [row], p)
    return p


def _panel():
    idx = pd.MultiIndex.from_product([pd.to_datetime(["2025-03-21", "2025-03-24", "2025-03-25", "2025-03-26"]),
                                      ["BBG1", "ALTR"]], names=["datetime", "instrument"])
    return pd.DataFrame({"close": 111.0, "LABEL": np.nan}, index=idx)


def test_labels_join_on_sec_id_and_stop_at_last_trade(tmp_path):
    out = inject_terminal_labels(_panel(), _csv(tmp_path), horizon_days=2)
    lab = out["LABEL"]
    want = 113.0 / 111.85 - 1
    assert math.isclose(lab[(pd.Timestamp("2025-03-24"), "BBG1")], want)
    assert math.isclose(lab[(pd.Timestamp("2025-03-25"), "BBG1")], want)
    assert np.isnan(lab[(pd.Timestamp("2025-03-26"), "BBG1")])          # vendor filler row after the last trade
    assert lab.xs("ALTR", level="instrument").isna().all()               # the ticker is not the key


def test_backtest_exit_on_last_trade_date(tmp_path):
    pos = pd.DataFrame({"date": pd.to_datetime(["2025-03-24", "2025-03-25"]), "sec_id": ["BBG1", "BBG1"],
                        "price": [111.5, 111.85]})
    out = apply_backtest_exits(pos, _csv(tmp_path))
    assert out.loc[out["date"] == "2025-03-25", "price"].item() == 113.0
    assert out.loc[out["date"] == "2025-03-24", "price"].item() == 111.5


def test_record_and_payout_from_row(tmp_path):
    p = _csv(tmp_path, successor_sec_id="BBG1", terminal_value=212.25, payout_per_share=145.0)
    row = pd.read_csv(p, dtype=str).iloc[0]
    rec = record_from_row(row)
    assert rec.sec_id == "BBG1" and rec.observed_delist_date == "2025-03-25" and rec.successor_sec_id == "BBG1"
    assert row_payout(row) == 212.25
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_qlib_adapter_sec_id.py -v`
Expected: FAIL with `ImportError` (`record_from_row`, `row_payout` do not exist)

- [ ] **Step 3: Implement**

In `handling.py`, delete the `successor_map` parameter from `build_train_label_adjustment` and `build_backtest_exit`, and replace each `successor = (successor_map or {}).get(record.ticker)` with `successor = record.successor_sec_id`. Rename the `BacktestExit` field `successor_ticker` to `successor_sec_id` and update the notes text to `f"Exchange transfer; re-link to {successor}"` (unchanged wording, new value). Replace `apply_to_panel` with:

```python
def adjustments_from_rows(rows: Iterable[Mapping[str, str]]) -> tuple[list[TrainLabelAdjustment], list[BacktestExit]]:
    """Train-label adjustments and backtest exits straight from delistings.csv rows."""
    from .qlib_adapter import record_from_row, row_payout   # local import: qlib_adapter imports this module

    train, exits = [], []
    for row in rows:
        close = _float(row.get("last_trade_close"))
        if close is None:
            continue
        rec = record_from_row(row)
        payout = row_payout(row)
        recovery = _float(row.get("recovery_ratio"))
        kw = {"recovery_ratio": recovery} if recovery is not None else {}
        train.append(build_train_label_adjustment(rec, close, payout, **kw))
        exits.append(build_backtest_exit(rec, close, payout, **kw))
    return train, exits


def _float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f
```

In `qlib_adapter.py`, replace `load_classifications` and `_record_from_row` with:

```python
_STR_COLS = {"sec_id": str, "ticker": str, "successor_sec_id": str, "acquirer_sec_id": str, "bucket": str}


def load_delistings(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=_STR_COLS)
    for c in ("delist_date", "last_trade_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ("crsp_code", "last_trade_close", "payout_per_share", "terminal_value", "recovery_ratio", "cik"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _iso(v) -> str | None:
    if v is None or (isinstance(v, float) and v != v) or v == "" or pd.isna(v):
        return None
    return pd.Timestamp(v).strftime("%Y-%m-%d")


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def record_from_row(row) -> DelistRecord:
    bucket = CrspBucket(row["bucket"]) if isinstance(row["bucket"], str) and row["bucket"] else CrspBucket.UNKNOWN
    code = _num(row.get("crsp_code"))
    cik = _num(row.get("cik"))
    succ = row.get("successor_sec_id")
    return DelistRecord(
        ticker=str(row.get("ticker") or ""), cik=int(cik) if cik is not None else None,
        observed_delist_date=_iso(row.get("last_trade_date")) or _iso(row.get("delist_date")),
        crsp_code=int(code) if code is not None else None, bucket=bucket,
        confidence=str(row.get("confidence") or ""), reason=str(row.get("reason") or ""),
        sec_id=str(row["sec_id"]), delist_date=_iso(row.get("delist_date")),
        successor_sec_id=succ if isinstance(succ, str) and succ else None,
    )


def row_payout(row) -> float | None:
    if row.get("bucket") == "merger" and _num(row.get("terminal_value")) is not None:
        return _num(row.get("terminal_value"))
    return _num(row.get("payout_per_share"))
```

Rewrite the three panel functions to iterate `load_delistings(csv).iterrows()`, key on `row["sec_id"]` against the `instrument` level (or `id_col` for positions), take `last_close` from `row["last_trade_close"]` (falling back to the panel's last close on or before the last trade date), the payout from `row_payout(row)`, the recovery from `row["recovery_ratio"]`, and the exchange from `normalize_exchange(row["exchange"])`. `inject_terminal_labels` labels the last `horizon_days` panel rows of that instrument **dated on or before the last trade date**. `apply_backtest_exits` rewrites the row whose date equals the last trade date (else the delist date). `apply_bmp_corrections` keeps its month-end logic with the delist anchor = last trade date and keeps the warning when a distress row has no last close.

Update `__init__.py`: export `adjustments_from_rows` instead of `apply_to_panel`.

Rewrite `scripts/compute_corrected_returns.py`:

```python
"""Apply BMP 2007 firm-month corrections to a monthly panel keyed by sec_id.

    PYTHONPATH=src python scripts/compute_corrected_returns.py \
        --panel data/monthly_panel.parquet --delistings output/delistings.csv \
        --out output/corrected_monthly_panel.parquet

--panel: parquet/csv with (date, instrument) where instrument is the sec_id, and
         columns close, monthly_return; dates are month-ends.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from delist_detection.qlib_adapter import apply_bmp_corrections

ROOT = Path(__file__).resolve().parents[1]


def _read_panel(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, parse_dates=["date"])
    if not isinstance(df.index, pd.MultiIndex):
        df = df.set_index(["date", "instrument"]).sort_index()
    return df


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--panel", required=True, type=Path)
    p.add_argument("--delistings", default=str(ROOT / "output" / "delistings.csv"))
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    out = apply_bmp_corrections(_read_panel(args.panel), args.delistings)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out) if args.out.suffix == ".parquet" else out.to_csv(args.out)
    print(f"Wrote {args.out}: {len(out)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Port the existing handling/adapter tests: every test that built a `delist_classifications`-style CSV now writes a `delistings.csv` with `store.write_table` (as in `_csv` above) and a panel keyed by `sec_id`; every `successor_map={"WYN": "WH"}` becomes `successor_sec_id` on the record/row; every `payouts=`, `exchanges=`, `last_trade_closes=`, `recovery_ratios=` dict becomes a column value on the row. Keep every behavioral assertion (values, warnings, dropped rows); only the plumbing changes.

- [ ] **Step 4: Run tests**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -p no:warnings`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add -A src/delist_detection scripts/compute_corrected_returns.py tests
git commit -m "refactor(handling): join on sec_id, read values from delisting rows"
```

---

### Task 19: Remaining scripts (verification, golden builder, cleanup)

**Files:**
- Modify: `scripts/verify_against_web.py`, `scripts/build_golden_fixtures.py`, `scripts/verify_altair.py` (only if it uses removed names), `tests/test_build_golden_fixtures.py`
- Delete: `scripts/list_unknowns.py` (superseded by `review.csv`)
- Modify: `src/delist_detection/llm_merger_extractor.py` (docstrings only: `build_dlret_table` → `build_delistings_table`), `src/delist_detection/classifier.py:573` comment (`delist_classifications.csv` → `delistings.csv`)

**Interfaces:**
- Consumes: `store.read_table("delistings", ...)`; `ftd.FtdClient`, `FtdIndex` (Task 5).

- [ ] **Step 1: `verify_against_web.py`**

Read `output/delistings.csv` (default `--input`). For each row use `cik`, `ticker`, `bucket`, `resolved_name` (as the name to check against EDGAR, replacing the AV name) and `last_trade_date` (else `delist_date`) as the observed date; keep every existing verdict rule (`OK`, `OK_recycled_ticker`, `no_cik`, `WEAK_*`, `MISMATCH_name`). Delete `--av-csv` and the AV name loading. Add `sec_id` as the first output column of `output/web_verification.csv`.

- [ ] **Step 2: `build_golden_fixtures.py`**

Replace `RawTiingoPrices` with the FTD close: build `FtdIndex.load(FtdClient(ROOT / "cache" / "sec_data" / "ftd"), day - 10 d, day + 10 d, symbols={acquirer})` and use `close_after(day, symbol=acquirer)`; drop `--raw-tiingo-dir` (the LLM capture runs whenever `OPENAI_API_KEY` is set). Existing fixtures stay as committed; this only changes how a rebuild prices the acquirer. Update `tests/test_build_golden_fixtures.py` for the removed argument.

- [ ] **Step 3: Cleanup and grep**

```bash
git rm scripts/list_unknowns.py
grep -rn "av_listing\|raw_tiingo\|RawTiingo\|MemberNames\|AV_LISTING_CSV\|AV_ACTIVE_CSV\|RAW_TIINGO_DIR\|delist_classifications\|dlret\.csv\|build_dlret_table\|--cik-map\|--names" src scripts tests
```
Expected: no hits in `src` and `scripts`; hits in `tests` only inside fixture data or historical comments you have reviewed.

- [ ] **Step 4: Run tests and commit**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -p no:warnings`
Expected: all pass

```bash
git add -A scripts src tests
git commit -m "chore(scripts): verification and golden builder on the new tables; drop AV/Tiingo"
```

---

### Task 20: Documentation

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/data-flow.md`, `docs/superpowers/feature-spec.md` (implementation notes only)

- [ ] **Step 1: `CLAUDE.md`**

Rewrite "What this is", "Commands" and "Architecture" for the new model while keeping the file's structure and invariants section:
- The library builds a FIGI-keyed security master and a Form-25-driven delisting table from caller observations; inputs come from SEC EDGAR, SEC fails-to-deliver, SEC MIDAS, the Nasdaq halt feed and OpenFIGI (no Tiingo, no Alpha Vantage).
- Commands: `pytest` (update the test count to the new total), `scripts/classify_universe.py --observations ...`, `scripts/observations_from_snapshots.py`, `scripts/observations_from_instruments.py`, `scripts/compute_corrected_returns.py --panel ... --delistings ...`, `scripts/verify_against_web.py`, `scripts/build_golden_fixtures.py`; the `PYTHONPATH=src` note for worktrees; override CSV columns keyed by `sec_id[,delist_date]`.
- Architecture: add the new modules (observations, store, trading_calendar, sec_http, ftd, midas, nasdaq_halts, openfigi, figi_resolution, form25, last_trade, listing_status, security_master, delistings, pipeline) in the classification layer; handling layer keyed by `sec_id`.
- Invariants: add "OpenFIGI refusals abort (OpenFigiBlocked, exit 2)", "every output is written only after the whole run succeeds", "`sec_id` is a US composite FIGI or a `CIK<cik>-<CLASS>` placeholder", "a delisting is a Form 25 removal (not a rename, not a secondary withdrawal)"; remove the AV and Tiingo lines; keep the SEC fair-access and offline-tests invariants; point to `CONTEXT.md` for vocabulary.

- [ ] **Step 2: `README.md` and `docs/data-flow.md`**

Replace the "Primary output" section with the six output tables (columns from `store.py`), replace the CLI section, replace the resolver/`--names`/`--cik-map` section with "Observations and pins", add a "Where each date and price comes from" section (Form 25 notice → 8-K 3.01 → MIDAS → Nasdaq halt; fails-to-deliver closes), and update `docs/data-flow.md`'s pipeline diagram to: observations → eras → CIK → FTD CUSIPs → FIGI → securities → Form 25 scan → match/secondary check → last trade → classify → closes/payouts → tables. Keep the bucket table and the CRSP code table unchanged (D5).

- [ ] **Step 3: `feature-spec.md`**

Add a short "Implementation notes" section at the end recording where the build differs from the spec text: FIGI resolution tries CUSIPs first (they need no name check), then the ticker, then the name search; `ticker_history.source` values are `observation` and `ftd`; `ticker_history.exchange` is filled from the Form 25 for ranges that end in a delisting and left empty otherwise.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md docs/data-flow.md docs/superpowers/feature-spec.md
git commit -m "docs: security master, observations, delisting table"
```

---

### Task 21: Acceptance run and verification loop (network)

**Files:**
- Create: `data/observations.csv` (committed input built from the `qlib_practice` snapshots)
- Regenerate: `output/*.csv` (committed artifacts); delete the old `output/dlret.csv` and `output/delist_classifications.csv`
- Create: `docs/validation/2026-09-23-acceptance.md`

- [ ] **Step 1: Build observations**

```bash
QP=/Users/royeli/repo/github.com/qlib_practice/fetch_data_aplha/data/ishares_russell_1000
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/observations_from_snapshots.py \
  --dir "$QP/raw" --dir "$QP/wikipedia_russell/raw" --where asset_class=Equity --out data/observations.csv
```
Expected: roughly 35,000 observations over roughly 2,200 tickers.

- [ ] **Step 2: Full run**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py \
  --observations data/observations.csv 2>&1 | tee output/run.log
```
Allowed network: `www.sec.gov`, `data.sec.gov`, `efts.sec.gov`, `api.openfigi.com`, `www.nasdaqtrader.com`. The first run downloads the fails-to-deliver history and MIDAS quarters (several hundred MB into `cache/sec_data/`); run it in the background and poll. An `ABORTED` exit 2 means a refusal: fix the cause (User-Agent, key, pacing), then rerun; caches make reruns cheap.

- [ ] **Step 3: Check the acceptance criteria (spec §13)**

Write a short script in `$TMPDIR` that reads the six tables and asserts:
- AET: `sec_id` `BBG000FJLFX8`; one `merger` delisting; `last_trade_date` 2018-11-28; `last_trade_close` 212.70.
- ALTR (Altair): `last_trade_date` 2025-03-25.
- SAVE: `last_trade_date` 2024-11-15.
- MON: Monsanto's delisting in 2018; no 2022 MON row.
- HOT, PE, TSS: `merger`, not `expiration`.
- Apache (APA/APA Corp predecessor): no delisting dated from the 2020 Chicago withdrawal.
- GOOG and GOOGL: two different `sec_id`s today.
- Every observed security is listed today, has a delisting, or appears in `review.csv` (count the three groups; they must add up to the observed total).
- At least 90% of 2004+ merger delistings have `last_trade_close`.

For every failed check, use superpowers:systematic-debugging: find the root cause in the code or data, fix it with a test (fixture-backed, offline), rerun the pipeline (cached), and recheck. Do not special-case tickers in code; data corrections go in `MANUAL_OVERRIDES` (identity) or observation pins.

- [ ] **Step 4: Independent verification**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/verify_against_web.py
```
Agreement on delisting rows must be at least 98.9%. Drill into each `MISMATCH_*` and `WEAK_*` row: curl the cited accession (see CLAUDE.md for the User-Agent recipe), decide whether the pipeline or the verifier is wrong, fix the root cause, rerun. Repeat until the rate holds and every remaining mismatch is explained in the validation note.

- [ ] **Step 5: Validation note and commit**

Write `docs/validation/2026-09-23-acceptance.md`: run date, input counts, table row counts, bucket counts, FIGI source counts, review flag counts, each acceptance check with its result, the verification rate, and a list of known residual issues with examples. Then:

```bash
git rm --cached output/dlret.csv output/delist_classifications.csv 2>/dev/null; rm -f output/dlret.csv output/delist_classifications.csv
git add data/observations.csv output docs/validation/2026-09-23-acceptance.md
git commit -m "data: acceptance run on the qlib_practice universe"
```

---

## Self-review checklist (done while writing this plan)

- Spec coverage: FR-1 (Task 3), FR-2 (Tasks 3, 17), FR-3 (Tasks 8, 9, 14), FR-4 (Task 14), FR-5 (Tasks 14, 17), FR-6 (Tasks 10, 13, 15), FR-7 (Task 12), FR-8 (Tasks 5, 6, 7, 10, 11, 15, 17), FR-9 (Tasks 16, 17), FR-10 (Task 15), FR-11 (Task 18); outputs §7 (Tasks 1, 16, 17); data sources §9 (Tasks 4–8); CLI §10 (Tasks 3, 17, 18); removals §12 (Tasks 17–19); acceptance §13 (Task 21); docs (Task 20).
- Review Focus tests: recycled ticker (Task 3 `test_recycled_ticker_splits_into_two_eras`), punctuation (Tasks 3, 5, 9), secondary withdrawal (Tasks 13, 15), missing close (Task 17 `test_missing_close_leaves_blank_dlret_and_review`), refusal mid-run (Task 17 `test_refusal_mid_run_keeps_previous_outputs`).
- Names used across tasks: `normalize_ticker`, `TickerEra.key/names/cusips/cik_pin/sec_id_pin`, `FtdIndex.load/extend/by_symbol/by_cusip/close_after`, `MidasClient.last_trade_day`, `NasdaqHaltClient.deletion_halt`, `last_trade_from_halt`, `OpenFigiClient.map/filter`, `us_candidates/accept`, `parse_form25/match_security/notice_last_trade/effective_date`, `eightk_last_trade/decide_last_trade/LastTrade`, `exchanges_around/withdrawal_kind/listed_today`, `FigiResolver.resolve_many/build_securities/era_cusips/ranges_from_sightings`, `DelistingFinder.find/SecurityContext/ReviewItem`, `classify_event`, `build_delistings_table/delisting_row/load_float_overrides/load_merger_terms_overrides/unmatched_override_keys`, `pipeline.run/Clients/Overrides/default_clients`.

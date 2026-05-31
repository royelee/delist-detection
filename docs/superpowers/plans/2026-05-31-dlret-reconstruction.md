# DLRET Reconstruction as Primary Output — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a per-delisting DLRET reconstruction table (`output/dlret.csv`) the library's primary output, built on a self-explaining DLRET core and a central `EnrichedDelistRecord`, with mixed cash+stock merger support and the 501/502 bucket fix.

**Architecture:** A new hub module `dlret.py` owns the DLRET computation: `resolve_dlret(...) -> DlretResult` (value + method + terminal_value) is the self-explaining core; `compute_dlret(...) -> float` stays as a backward-compatible facade (`= resolve_dlret(...).value`) so the entire existing test suite stays green. A new `reconstruction.py` adds `EnrichedDelistRecord` + `enrich(...)` + `build_dlret_table(...)`. Merger DLRET captures the full consideration `cash + stock_ratio*acquirer_price`; stock-leg terms and `last_trade_close` are externally provided. `crsp_codes` is fixed so 501/502/503–519 route to `EXCHANGE_TRANSFER`.

**Tech Stack:** Python ≥3.10, stdlib `dataclasses`/`enum`/`csv`, pytest (offline, `FakeEdgar`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-31-dlret-reconstruction-design.md`. **Research basis:** `docs/research/dlret-generation.md`.

**Deliberate deviations from the spec (low-risk, noted for the reviewer):**
- `compute_dlret` keeps its `float` return (facade); the `DlretResult` lives on the new `resolve_dlret`. This satisfies "DLRET is self-explaining" while preserving ~20 existing tests verbatim.
- `resolve_dlret` preserves every current `compute_dlret` value exactly, including `ACTIVE`/`UNKNOWN` bucket → `0.0` (not `NaN`) so firm-month behavior is unchanged. The table renders blank `dlret` whenever the value is `NaN` (the `NEEDS_LAST_TRADE` / `DROPPED_EXPIRATION` / bad-price cases).
- `qlib_adapter.py` is **not** rewritten to construct `EnrichedDelistRecord`s. It already derives from the hub *transitively*: `apply_bmp_corrections` → `build_firm_month_correction` → `compute_dlret`/`resolve_dlret`, and Task 6 gives it stock-leg support for free. A deeper `EnrichedDelistRecord`-based rewrite of `qlib_adapter` would add churn without changing behavior, so it is deferred. (The spec's "everything derives from the hub" is met computationally; the `EnrichedDelistRecord` is the table's transport type.)
- Input maps (`last_trade_closes`, `payouts`, …) are keyed by ticker, matching the existing `compute_corrected_returns.py` convention. Recycled tickers still produce one output **row per delisting event** (keyed on the record), but share a per-ticker input value; supplying event-specific prices for a recycled ticker is a known limitation, consistent with the rest of the repo.

**Run all tests with:** `conda activate rdagent4qlib && pytest -q` (the editable install + pytest live in that env).

---

## File Structure

- **Create** `src/delist_detection/dlret.py` — DLRET hub: `DlretMethod`, `DlretResult`, Shumway constants, `_shumway_*`, `resolve_dlret`, `compute_dlret` facade.
- **Create** `src/delist_detection/reconstruction.py` — `EnrichedDelistRecord`, `enrich`, `build_dlret_table`, `DLRET_TABLE_COLUMNS`, `enriched_to_row`, `write_dlret_csv`.
- **Modify** `src/delist_detection/bmp_correction.py` — re-export constants + `compute_dlret` from `dlret`; keep `bmp_firm_month_return`, threading optional `stock_ratio`/`acquirer_price`.
- **Modify** `src/delist_detection/crsp_codes.py` — route 501/502/503–519 to `EXCHANGE_TRANSFER`; fix docstring.
- **Modify** `src/delist_detection/handling.py` — thread optional `stock_ratio`/`acquirer_price` through `build_firm_month_correction`.
- **Modify** `scripts/classify_universe.py` — emit `output/dlret.csv` from optional input CSVs.
- **Modify** `README.md`, `CLAUDE.md` — reframe around the DLRET table.
- **Create** `tests/test_dlret.py`, `tests/test_reconstruction.py` — new coverage.
- **Modify** `tests/test_crsp_codes.py` — add 501/502 regression.

---

## Task 1: DLRET hub module (`dlret.py`)

**Files:**
- Create: `src/delist_detection/dlret.py`
- Test: `tests/test_dlret.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dlret.py`:

```python
import math
import pytest

from delist_detection.crsp_codes import CrspBucket
from delist_detection.exchanges import Exchange
from delist_detection.dlret import (
    DlretMethod, DlretResult, resolve_dlret, compute_dlret,
    SHUMWAY_NYSE_AMEX, SHUMWAY_NASDAQ,
)


def test_merger_cash_only():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 100.0, payout_per_share=113.0)
    assert r.method is DlretMethod.CASH_ONLY
    assert r.terminal_value == pytest.approx(113.0)
    assert r.value == pytest.approx(0.13)


def test_merger_cash_plus_stock_aet_cvs():
    # AET->CVS: $145 cash + 0.8378 CVS @ $80, last AET $190 -> +11.6%
    r = resolve_dlret(
        CrspBucket.MERGER, Exchange.NYSE, 190.0,
        payout_per_share=145.0, stock_ratio=0.8378, acquirer_price=80.0,
    )
    assert r.method is DlretMethod.CASH_PLUS_STOCK
    assert r.terminal_value == pytest.approx(212.024)
    assert r.value == pytest.approx(0.11592, abs=1e-4)


def test_merger_stock_only():
    r = resolve_dlret(
        CrspBucket.MERGER, Exchange.NYSE, 100.0,
        stock_ratio=1.5, acquirer_price=80.0,
    )
    assert r.method is DlretMethod.STOCK_ONLY
    assert r.terminal_value == pytest.approx(120.0)
    assert r.value == pytest.approx(0.20)


def test_merger_no_consideration_abstains_neutral():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 100.0)
    assert r.method is DlretMethod.ABSTAIN_NO_CONSIDERATION
    assert r.value == 0.0
    assert r.terminal_value is None


def test_merger_consideration_without_price_needs_last_trade():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 0.0, payout_per_share=113.0)
    assert r.method is DlretMethod.NEEDS_LAST_TRADE
    assert math.isnan(r.value)


def test_exchange_transfer_zero():
    r = resolve_dlret(CrspBucket.EXCHANGE_TRANSFER, Exchange.NYSE, 0.0)
    assert r.method is DlretMethod.EXCHANGE_TRANSFER_ZERO
    assert r.value == 0.0


def test_liquidation_recovery():
    r = resolve_dlret(CrspBucket.LIQUIDATION, Exchange.NYSE, 10.0, recovery_ratio=0.20)
    assert r.method is DlretMethod.RECOVERY_RATIO
    assert r.value == pytest.approx(-0.80)
    assert r.terminal_value == pytest.approx(2.0)


def test_liquidation_no_recovery_shumway():
    r = resolve_dlret(CrspBucket.LIQUIDATION, Exchange.NASDAQ, 10.0)
    assert r.method is DlretMethod.SHUMWAY_NASDAQ
    assert r.value == SHUMWAY_NASDAQ


def test_compliance_shumway_by_venue():
    assert resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.NYSE, 10.0).method is DlretMethod.SHUMWAY_NYSE_AMEX
    assert resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.AMEX, 10.0).value == SHUMWAY_NYSE_AMEX
    assert resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.NASDAQ, 10.0).value == SHUMWAY_NASDAQ
    assert resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.OTHER, 10.0).value == SHUMWAY_NASDAQ


def test_expiration_dropped():
    r = resolve_dlret(CrspBucket.EXPIRATION, Exchange.NYSE, 10.0)
    assert r.method is DlretMethod.DROPPED_EXPIRATION
    assert math.isnan(r.value)


def test_worthless_method_exists_but_unused_in_v1():
    # Reserved enum member; resolve_dlret never emits it in v1.
    assert DlretMethod.WORTHLESS.value == "worthless"


def test_compute_dlret_facade_matches_value():
    assert compute_dlret(
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        last_trade_close=100.0, payout_per_share=113.0,
    ) == pytest.approx(0.13)


def test_negative_payout_is_nan():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 100.0, payout_per_share=-5.0)
    assert math.isnan(r.value)


def test_zero_payout_is_total_wipe():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 100.0, payout_per_share=0.0)
    assert r.value == pytest.approx(-1.0)
    assert r.method is DlretMethod.CASH_ONLY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda activate rdagent4qlib && pytest tests/test_dlret.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'delist_detection.dlret'`

- [ ] **Step 3: Create `src/delist_detection/dlret.py`**

```python
"""DLRET hub: the self-explaining delisting-return computation.

`resolve_dlret(...)` returns a `DlretResult` (value + which rule fired +
terminal value). `compute_dlret(...)` is the backward-compatible float facade
(`= resolve_dlret(...).value`). The Shumway constants and exchange logic live
here; `bmp_correction.py` re-exports them for backward compatibility.

Merger DLRET captures the full consideration:
    terminal = cash_per_share + stock_ratio * acquirer_price
    DLRET    = terminal / last_trade_close - 1
Stock-leg terms and last_trade_close are externally provided.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .crsp_codes import CrspBucket
from .exchanges import Exchange


__all__ = [
    "SHUMWAY_NYSE_AMEX", "SHUMWAY_NASDAQ",
    "DlretMethod", "DlretResult", "resolve_dlret", "compute_dlret",
]


SHUMWAY_NYSE_AMEX: float = -0.30
SHUMWAY_NASDAQ: float = -0.55


class DlretMethod(str, Enum):
    CASH_ONLY = "cash_only"
    CASH_PLUS_STOCK = "cash_plus_stock"
    STOCK_ONLY = "stock_only"
    ABSTAIN_NO_CONSIDERATION = "abstain_no_consideration"
    NEEDS_LAST_TRADE = "needs_last_trade"
    EXCHANGE_TRANSFER_ZERO = "exchange_transfer_zero"
    RECOVERY_RATIO = "recovery_ratio"
    SHUMWAY_NYSE_AMEX = "shumway_nyse_amex"
    SHUMWAY_NASDAQ = "shumway_nasdaq"
    WORTHLESS = "worthless"            # reserved; not emitted in v1
    DROPPED_EXPIRATION = "dropped_expiration"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DlretResult:
    value: float                 # may be NaN
    method: DlretMethod
    terminal_value: float | None


def _shumway_result(exchange: Exchange) -> DlretResult:
    if exchange in (Exchange.NYSE, Exchange.AMEX):
        return DlretResult(SHUMWAY_NYSE_AMEX, DlretMethod.SHUMWAY_NYSE_AMEX, None)
    return DlretResult(SHUMWAY_NASDAQ, DlretMethod.SHUMWAY_NASDAQ, None)


def _resolve_merger(
    last_trade_close: float | None,
    payout_per_share: float | None,
    stock_ratio: float | None,
    acquirer_price: float | None,
) -> DlretResult:
    cash: float | None = None
    if payout_per_share is not None:
        if payout_per_share < 0:
            return DlretResult(float("nan"), DlretMethod.UNKNOWN, None)
        cash = float(payout_per_share)

    stock: float | None = None
    if stock_ratio is not None and acquirer_price is not None:
        leg = float(stock_ratio) * float(acquirer_price)
        if leg < 0:
            return DlretResult(float("nan"), DlretMethod.UNKNOWN, None)
        stock = leg

    legs = [x for x in (cash, stock) if x is not None]
    if not legs:
        return DlretResult(0.0, DlretMethod.ABSTAIN_NO_CONSIDERATION, None)

    terminal = float(sum(legs))
    if last_trade_close is None or last_trade_close <= 0:
        return DlretResult(float("nan"), DlretMethod.NEEDS_LAST_TRADE, None)

    if cash is not None and stock is not None:
        method = DlretMethod.CASH_PLUS_STOCK
    elif cash is not None:
        method = DlretMethod.CASH_ONLY
    else:
        method = DlretMethod.STOCK_ONLY
    return DlretResult(terminal / last_trade_close - 1.0, method, terminal)


def resolve_dlret(
    bucket: CrspBucket,
    exchange: Exchange,
    last_trade_close: float | None,
    payout_per_share: float | None = None,
    stock_ratio: float | None = None,
    acquirer_price: float | None = None,
    recovery_ratio: float | None = None,
) -> DlretResult:
    if bucket is CrspBucket.EXPIRATION:
        return DlretResult(float("nan"), DlretMethod.DROPPED_EXPIRATION, None)
    if bucket is CrspBucket.EXCHANGE_TRANSFER:
        return DlretResult(0.0, DlretMethod.EXCHANGE_TRANSFER_ZERO, None)

    if bucket is CrspBucket.MERGER:
        return _resolve_merger(last_trade_close, payout_per_share, stock_ratio, acquirer_price)

    # Remaining buckets require a valid last trade price (preserves the
    # original compute_dlret guard, incl. the bad-price -> NaN cases).
    if last_trade_close is None or last_trade_close <= 0:
        return DlretResult(float("nan"), DlretMethod.UNKNOWN, None)

    if bucket is CrspBucket.LIQUIDATION:
        if recovery_ratio is not None:
            if recovery_ratio < 0:
                return DlretResult(float("nan"), DlretMethod.UNKNOWN, None)
            return DlretResult(
                recovery_ratio - 1.0, DlretMethod.RECOVERY_RATIO,
                recovery_ratio * last_trade_close,
            )
        return _shumway_result(exchange)

    if bucket is CrspBucket.COMPLIANCE_FAILURE:
        return _shumway_result(exchange)

    # ACTIVE / UNKNOWN: no shock by default (preserves original behavior).
    return DlretResult(0.0, DlretMethod.UNKNOWN, None)


def compute_dlret(
    bucket: CrspBucket,
    exchange: Exchange,
    last_trade_close: float | None,
    payout_per_share: float | None = None,
    recovery_ratio: float | None = None,
    stock_ratio: float | None = None,
    acquirer_price: float | None = None,
) -> float:
    """Backward-compatible float facade over `resolve_dlret`."""
    return resolve_dlret(
        bucket, exchange, last_trade_close, payout_per_share,
        stock_ratio, acquirer_price, recovery_ratio,
    ).value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda activate rdagent4qlib && pytest tests/test_dlret.py -q`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/dlret.py tests/test_dlret.py
git commit -m "feat: add self-explaining DLRET hub (resolve_dlret + DlretResult) with mixed cash+stock"
```

---

## Task 2: Re-point `bmp_correction.py` at the hub

**Files:**
- Modify: `src/delist_detection/bmp_correction.py`
- Test: `tests/test_bmp_correction.py` (existing — must stay green)

- [ ] **Step 1: Replace the body of `bmp_correction.py`**

Replace the whole file with this (keeps the public names `SHUMWAY_NYSE_AMEX`, `SHUMWAY_NASDAQ`, `compute_dlret`, `bmp_firm_month_return` so existing imports/tests are unaffected; threads stock legs):

```python
"""Beaver-McNichols-Price (2007) firm-month return correction.

The unbiased firm-month return at delisting is:

    R_delisting_month = (1 + R_partial) * (1 + DLRET) - 1
    R_partial = last_trade_close / prior_month_end_close - 1

DLRET is computed by the hub module `dlret.py`. This module keeps the
firm-month compounding and re-exports the DLRET symbols for backward
compatibility.
"""

from __future__ import annotations

import math

from .crsp_codes import CrspBucket
from .dlret import (
    SHUMWAY_NYSE_AMEX, SHUMWAY_NASDAQ, compute_dlret, resolve_dlret, DlretResult, DlretMethod,
)
from .exchanges import Exchange


__all__ = [
    "SHUMWAY_NYSE_AMEX", "SHUMWAY_NASDAQ",
    "compute_dlret", "resolve_dlret", "DlretResult", "DlretMethod",
    "bmp_firm_month_return",
]


def bmp_firm_month_return(
    prior_month_end_close: float,
    last_trade_close: float,
    bucket: CrspBucket,
    exchange: Exchange,
    payout_per_share: float | None = None,
    recovery_ratio: float | None = None,
    stock_ratio: float | None = None,
    acquirer_price: float | None = None,
) -> float:
    """Compound R_partial and DLRET into the corrected firm-month return.

    Returns NaN for EXPIRATION and for invalid inputs (non-positive prior
    close). The caller treats NaN as "drop this firm-month".
    """
    dlret = compute_dlret(
        bucket=bucket, exchange=exchange,
        last_trade_close=last_trade_close,
        payout_per_share=payout_per_share,
        recovery_ratio=recovery_ratio,
        stock_ratio=stock_ratio,
        acquirer_price=acquirer_price,
    )
    if math.isnan(dlret):
        return float("nan")
    if prior_month_end_close <= 0:
        return float("nan")
    r_partial = (last_trade_close / prior_month_end_close) - 1.0
    return (1.0 + r_partial) * (1.0 + dlret) - 1.0
```

- [ ] **Step 2: Run the existing + new suites to verify green**

Run: `conda activate rdagent4qlib && pytest tests/test_bmp_correction.py tests/test_firm_month_correction.py tests/test_known_cases_bmp.py tests/test_qlib_adapter_bmp.py tests/test_dlret.py -q`
Expected: PASS (no regressions; the moved `compute_dlret` behaves identically)

- [ ] **Step 3: Commit**

```bash
git add src/delist_detection/bmp_correction.py
git commit -m "refactor: bmp_correction consumes the dlret hub; thread stock-leg terms"
```

---

## Task 3: Fix 501/502 bucketing in `crsp_codes.py`

**Files:**
- Modify: `src/delist_detection/crsp_codes.py:48-63` (the `bucket_for_code` ranges) and the module docstring
- Test: `tests/test_crsp_codes.py`

- [ ] **Step 1: Add failing regression tests**

Append to `tests/test_crsp_codes.py`:

```python
def test_up_migration_codes_are_exchange_transfer_not_compliance():
    # 501 (-> NYSE) / 502 (-> AMEX/NYSE MKT) are positive up-migrations,
    # NOT performance delistings. They must not land in COMPLIANCE_FAILURE
    # (which would apply a -55% Shumway shock to a good event).
    assert bucket_for_code(501) is CrspBucket.EXCHANGE_TRANSFER
    assert bucket_for_code(502) is CrspBucket.EXCHANGE_TRANSFER
    assert bucket_for_code(510) is CrspBucket.EXCHANGE_TRANSFER  # 503-519 sub-range


def test_genuine_5xx_still_compliance():
    assert bucket_for_code(500) is CrspBucket.COMPLIANCE_FAILURE
    assert bucket_for_code(520) is CrspBucket.COMPLIANCE_FAILURE
    assert bucket_for_code(555) is CrspBucket.COMPLIANCE_FAILURE
```

- [ ] **Step 2: Run to verify failure**

Run: `conda activate rdagent4qlib && pytest tests/test_crsp_codes.py -q`
Expected: FAIL — `bucket_for_code(501)` returns `COMPLIANCE_FAILURE`

- [ ] **Step 3: Fix `bucket_for_code`**

In `src/delist_detection/crsp_codes.py`, replace the `bucket_for_code` function (currently lines 48-63) with:

```python
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
    # Per Shumway & Warther (1999), only 501/502 (migration to NYSE/AMEX) are
    # positive up-migrations; 500 and 505-588 are performance-related distress
    # delistings (-> COMPLIANCE_FAILURE below). See docs/research/dlret-generation.md.
    if 501 <= code <= 502:
        return CrspBucket.EXCHANGE_TRANSFER
    if 500 <= code < 600:
        return CrspBucket.COMPLIANCE_FAILURE
    if 600 <= code < 700:
        return CrspBucket.EXPIRATION
    return CrspBucket.UNKNOWN
```

- [ ] **Step 4: Fix the misleading docstring**

In `src/delist_detection/crsp_codes.py`, change the docstring line:

```
    COMPLIANCE_FAILURE  — 500s (and the dangerous half of 400s); apply -100% terminal
```

to:

```
    COMPLIANCE_FAILURE  — 500s (excl. 501/502 up-migrations); apply the Shumway
                          constant (-30% NYSE/AMEX, -55% Nasdaq) per bmp_correction
```

- [ ] **Step 5: Run to verify pass**

Run: `conda activate rdagent4qlib && pytest tests/test_crsp_codes.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/crsp_codes.py tests/test_crsp_codes.py
git commit -m "fix: route CRSP 501-519 up-migrations to EXCHANGE_TRANSFER, not COMPLIANCE_FAILURE"
```

---

## Task 4: `EnrichedDelistRecord` + `enrich()` (`reconstruction.py`)

**Files:**
- Create: `src/delist_detection/reconstruction.py`
- Test: `tests/test_reconstruction.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_reconstruction.py`:

```python
import math
import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.dlret import DlretMethod
from delist_detection.exchanges import Exchange
from delist_detection.reconstruction import enrich, EnrichedDelistRecord


def _rec(ticker="AET", bucket=CrspBucket.MERGER, code=241, date="2018-11-28"):
    return DelistRecord(
        ticker=ticker, cik=1122304, observed_delist_date=date,
        crsp_code=code, bucket=bucket, confidence="high",
        reason="M&A 2.01+3.01+5.01", evidence={},
    )


def test_enrich_merger_cash_plus_stock():
    e = enrich(
        _rec(), exchange=Exchange.NYSE, last_trade_close=190.0,
        payout_per_share=145.0, stock_ratio=0.8378, acquirer_price=80.0,
        acquirer_ticker="CVS", payout_source="manual", payout_confidence="high",
    )
    assert isinstance(e, EnrichedDelistRecord)
    assert e.dlret_method is DlretMethod.CASH_PLUS_STOCK
    assert e.dlret == pytest.approx(0.11592, abs=1e-4)
    assert e.terminal_value == pytest.approx(212.024)
    assert e.acquirer_ticker == "CVS"
    assert e.dlret_confidence == "medium"   # stock leg depends on a market price


def test_enrich_merger_cash_only_inherits_payout_confidence():
    e = enrich(
        _rec(code=233), exchange=Exchange.NYSE, last_trade_close=100.0,
        payout_per_share=113.0, payout_confidence="high",
    )
    assert e.dlret_method is DlretMethod.CASH_ONLY
    assert e.dlret_confidence == "high"


def test_enrich_needs_last_trade_is_low_confidence_and_nan():
    e = enrich(_rec(), exchange=Exchange.NYSE, last_trade_close=None, payout_per_share=113.0)
    assert e.dlret_method is DlretMethod.NEEDS_LAST_TRADE
    assert math.isnan(e.dlret)
    assert e.dlret_confidence == "low"


def test_enrich_carries_classification_fields():
    e = enrich(_rec(ticker="ABMD", code=231), exchange=Exchange.NASDAQ, last_trade_close=300.0,
               payout_per_share=380.0)
    assert e.ticker == "ABMD"
    assert e.crsp_code == 231
    assert e.bucket is CrspBucket.MERGER
    assert e.reason == "M&A 2.01+3.01+5.01"
```

- [ ] **Step 2: Run to verify failure**

Run: `conda activate rdagent4qlib && pytest tests/test_reconstruction.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'delist_detection.reconstruction'`

- [ ] **Step 3: Create `reconstruction.py` (record + enrich only; table builder added in Task 5)**

```python
"""DLRET reconstruction: the library's primary output.

`enrich()` joins a classification `DelistRecord` with externally-provided DLRET
inputs (last_trade_close, cash/stock merger terms, recovery) and the computed
DLRET into a single `EnrichedDelistRecord` — the central type every downstream
consumer can derive from. `build_dlret_table()` (added next) serializes a
sequence of these into `output/dlret.csv`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .dlret import DlretMethod, resolve_dlret
from .exchanges import Exchange


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
```

- [ ] **Step 4: Run to verify pass**

Run: `conda activate rdagent4qlib && pytest tests/test_reconstruction.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/reconstruction.py tests/test_reconstruction.py
git commit -m "feat: EnrichedDelistRecord + enrich() — the central DLRET record type"
```

---

## Task 5: `build_dlret_table` + CSV writer

**Files:**
- Modify: `src/delist_detection/reconstruction.py`
- Test: `tests/test_reconstruction.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_reconstruction.py`:

```python
from delist_detection.reconstruction import (
    build_dlret_table, write_dlret_csv, enriched_to_row, DLRET_TABLE_COLUMNS,
)


def test_table_column_order_is_contractual():
    assert DLRET_TABLE_COLUMNS == [
        "ticker", "bucket", "observed_delist_date", "crsp_code", "dlret", "reason",
        "exchange", "last_trade_close", "payout_per_share", "stock_ratio",
        "acquirer_price", "acquirer_ticker", "recovery_ratio", "terminal_value",
        "dlret_method", "dlret_confidence", "payout_source",
    ]


def test_build_table_keys_on_ticker_and_uses_inputs():
    records = [
        _rec(ticker="AET", code=241, date="2018-11-28"),
        _rec(ticker="ABMD", code=231, date="2023-01-03", bucket=CrspBucket.MERGER),
    ]
    table = build_dlret_table(
        records,
        last_trade_closes={"AET": 190.0, "ABMD": 300.0},
        payouts={"AET": 145.0, "ABMD": 380.0},
        exchanges={"AET": "NYSE", "ABMD": "NASDAQ"},
        merger_terms={"AET": {"stock_ratio": 0.8378, "acquirer_price": 80.0, "acquirer_ticker": "CVS"}},
    )
    by_ticker = {e.ticker: e for e in table}
    assert by_ticker["AET"].dlret_method is DlretMethod.CASH_PLUS_STOCK
    assert by_ticker["ABMD"].dlret_method is DlretMethod.CASH_ONLY
    assert by_ticker["ABMD"].dlret == pytest.approx(380.0 / 300.0 - 1.0)


def test_row_blanks_nan_and_none():
    e = enrich(_rec(), exchange=Exchange.NYSE, last_trade_close=None, payout_per_share=113.0)
    row = enriched_to_row(e)
    assert row["dlret"] == ""          # NaN renders blank, never 0
    assert row["terminal_value"] == ""
    assert row["dlret_method"] == "needs_last_trade"


def test_write_csv_roundtrip(tmp_path):
    import csv
    records = [_rec(ticker="ABMD", code=231)]
    table = build_dlret_table(records, last_trade_closes={"ABMD": 300.0}, payouts={"ABMD": 380.0},
                              exchanges={"ABMD": "NASDAQ"})
    out = tmp_path / "dlret.csv"
    write_dlret_csv(table, out)
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == DLRET_TABLE_COLUMNS
    assert rows[0]["ticker"] == "ABMD"
    assert rows[0]["dlret_method"] == "cash_only"


def test_recycled_ticker_yields_one_row_per_delisting():
    # ALTR was Altera (2015 merger) then Altair (2025). Two DelistRecords with
    # the same ticker but different dates -> two output rows, one per event.
    records = [
        _rec(ticker="ALTR", code=233, date="2015-12-28"),
        _rec(ticker="ALTR", code=231, date="2025-03-26"),
    ]
    table = build_dlret_table(records, last_trade_closes={"ALTR": 50.0}, payouts={"ALTR": 54.0})
    assert len(table) == 2
    assert {e.observed_delist_date for e in table} == {"2015-12-28", "2025-03-26"}
```

- [ ] **Step 2: Run to verify failure**

Run: `conda activate rdagent4qlib && pytest tests/test_reconstruction.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_dlret_table'`

- [ ] **Step 3: Append the table builder to `reconstruction.py`**

Add these imports at the top of `reconstruction.py` (alongside existing imports):

```python
import csv
from collections.abc import Iterable, Mapping
from pathlib import Path

from .exchanges import normalize_exchange
```

Then append:

```python
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
```

Note: `crsp_code` is an `int`; `_fmt` returns `str(int)` (e.g. `"241"`), not `"241.000000"`, because the `isinstance(x, float)` branch is skipped for ints. Verified by `test_build_table...` reading the value back.

- [ ] **Step 4: Run to verify pass**

Run: `conda activate rdagent4qlib && pytest tests/test_reconstruction.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/reconstruction.py tests/test_reconstruction.py
git commit -m "feat: build_dlret_table + CSV writer (primary output schema)"
```

---

## Task 6: Thread stock legs through `handling.build_firm_month_correction`

**Files:**
- Modify: `src/delist_detection/handling.py:254-321`
- Test: `tests/test_firm_month_correction.py`

- [ ] **Step 1: Add a failing test**

Append to `tests/test_firm_month_correction.py`:

```python
def test_firm_month_merger_includes_stock_leg():
    # AET->CVS: prior 200, last 190 (R_partial=-0.05); DLRET from full
    # consideration 212.024/190-1=+0.11592 -> R_month=(0.95)(1.11592)-1
    from delist_detection.handling import build_firm_month_correction
    from delist_detection.classifier import DelistRecord
    from delist_detection.crsp_codes import CrspBucket
    from delist_detection.exchanges import Exchange
    rec = DelistRecord(
        ticker="AET", cik=1, observed_delist_date="2018-11-28",
        crsp_code=241, bucket=CrspBucket.MERGER, confidence="high", reason="", evidence={},
    )
    fm = build_firm_month_correction(
        record=rec, prior_month_end_close=200.0, last_trade_close=190.0,
        exchange=Exchange.NYSE, payout_per_share=145.0,
        stock_ratio=0.8378, acquirer_price=80.0,
    )
    assert fm.dlret == pytest.approx(0.11592, abs=1e-4)
    assert fm.firm_month_return == pytest.approx((0.95) * (1.11592) - 1.0, abs=1e-4)
```

(Ensure `import pytest` is present at the top of the file; add it if missing.)

- [ ] **Step 2: Run to verify failure**

Run: `conda activate rdagent4qlib && pytest tests/test_firm_month_correction.py::test_firm_month_merger_includes_stock_leg -q`
Expected: FAIL — `build_firm_month_correction() got an unexpected keyword argument 'stock_ratio'`

- [ ] **Step 3: Update `build_firm_month_correction`**

In `src/delist_detection/handling.py`, change the signature and the two internal calls. Replace the signature (currently lines ~254-261):

```python
def build_firm_month_correction(
    record: DelistRecord,
    prior_month_end_close: float,
    last_trade_close: float,
    exchange: Exchange | None,
    payout_per_share: float | None = None,
    recovery_ratio: float | None = None,
    stock_ratio: float | None = None,
    acquirer_price: float | None = None,
) -> FirmMonthReturn:
```

Replace the `dlret = compute_dlret(...)` call (currently lines ~289-294) with:

```python
    dlret = compute_dlret(
        bucket=record.bucket, exchange=ex,
        last_trade_close=last_trade_close,
        payout_per_share=payout_per_share,
        recovery_ratio=recovery_ratio,
        stock_ratio=stock_ratio,
        acquirer_price=acquirer_price,
    )
```

Replace the `r_month = bmp_firm_month_return(...)` call (currently lines ~295-301) with:

```python
    r_month = bmp_firm_month_return(
        prior_month_end_close=prior_month_end_close,
        last_trade_close=last_trade_close,
        bucket=record.bucket, exchange=ex,
        payout_per_share=payout_per_share,
        recovery_ratio=recovery_ratio,
        stock_ratio=stock_ratio,
        acquirer_price=acquirer_price,
    )
```

- [ ] **Step 4: Run to verify pass (and no regressions)**

Run: `conda activate rdagent4qlib && pytest tests/test_firm_month_correction.py tests/test_handling.py tests/test_qlib_adapter_bmp.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/handling.py tests/test_firm_month_correction.py
git commit -m "feat: full merger consideration (cash+stock) in firm-month correction"
```

---

## Task 7: Emit `output/dlret.csv` from `classify_universe.py`

**Files:**
- Modify: `scripts/classify_universe.py`
- Test: `tests/test_reconstruction.py` (offline integration — already covers the builder; add a CLI-helper test)

- [ ] **Step 1: Add a failing test for the input-map loader helper**

Append to `tests/test_reconstruction.py`:

```python
def test_load_merger_terms_csv(tmp_path):
    from delist_detection.reconstruction import load_merger_terms_csv
    p = tmp_path / "terms.csv"
    p.write_text(
        "ticker,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker\n"
        "AET,145,0.8378,80,CVS\n"
        "ABMD,380,,,\n"
    )
    terms = load_merger_terms_csv(p)
    assert terms["AET"] == {"cash_per_share": 145.0, "stock_ratio": 0.8378,
                            "acquirer_price": 80.0, "acquirer_ticker": "CVS"}
    assert terms["ABMD"] == {"cash_per_share": 380.0}  # blanks omitted
```

- [ ] **Step 2: Run to verify failure**

Run: `conda activate rdagent4qlib && pytest tests/test_reconstruction.py::test_load_merger_terms_csv -q`
Expected: FAIL — `ImportError: cannot import name 'load_merger_terms_csv'`

- [ ] **Step 3: Add `load_merger_terms_csv` to `reconstruction.py`**

Append to `src/delist_detection/reconstruction.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `conda activate rdagent4qlib && pytest tests/test_reconstruction.py::test_load_merger_terms_csv -q`
Expected: PASS

- [ ] **Step 5: Wire the DLRET table into `classify_universe.py`**

In `scripts/classify_universe.py`, add to the imports block (after the existing `from delist_detection...` lines):

```python
from delist_detection.reconstruction import (
    build_dlret_table, write_dlret_csv, load_merger_terms_csv,
)
```

Add a default output path next to `DEFAULT_OUTPUT`:

```python
DEFAULT_DLRET_OUTPUT = ROOT / "output" / "dlret.csv"
```

Add CLI args (in the `argparse` setup, alongside the existing args):

```python
    p.add_argument("--dlret-output", default=str(DEFAULT_DLRET_OUTPUT),
                   help="primary DLRET reconstruction table")
    p.add_argument("--last-trade-closes", default=None,
                   help="CSV: ticker,last_trade_close (merger DLRET needs this)")
    p.add_argument("--merger-terms", default=None,
                   help="CSV: ticker,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker")
    p.add_argument("--recoveries", default=None,
                   help="CSV: ticker,recovery_ratio")
```

Accumulate the classified records during the main loop. The loop is `for i, (ticker, observed) in enumerate(rows, start=1):` (line ~156) and produces `rec = classifier.classify_ticker(...)` (line ~158), where `rec` is set to `None` in the exception handler (line ~160). Add `all_records: list = []` immediately before the loop, and inside the loop — right after the block that may set `rec = None` — add a guarded append:

```python
            if rec is not None:
                all_records.append(rec)
```

Then, after the existing classification CSV + payouts CSV are written (just before `return 0`), add (the script already has `import csv` at module top and the `av` / `payout_by_ticker` / `extractor` variables in scope):

```python
    # --- PRIMARY OUTPUT: DLRET reconstruction table ---
    def _read_float_map(path, col):
        if not path:
            return {}
        with open(path, newline="") as fh:
            return {
                (r["ticker"] or "").strip().upper(): float(r[col])
                for r in csv.DictReader(fh)
                if (r.get("ticker") or "").strip() and (r.get(col) or "").strip()
            }

    last_trades = _read_float_map(args.last_trade_closes, "last_trade_close")
    recoveries = _read_float_map(args.recoveries, "recovery_ratio")
    merger_terms = load_merger_terms_csv(args.merger_terms) if args.merger_terms else {}
    exchanges = {
        r.ticker.upper(): (av.exchange(r.ticker, observed_date=r.observed_delist_date) or "")
        for r in all_records
    }
    payouts_map = {t.upper(): pr.value for t, pr in payout_by_ticker.items() if pr.value is not None} \
        if extractor is not None else {}
    payout_src = {t.upper(): pr.source for t, pr in payout_by_ticker.items()} if extractor is not None else {}
    payout_conf = {t.upper(): pr.confidence for t, pr in payout_by_ticker.items()} if extractor is not None else {}

    table = build_dlret_table(
        all_records,
        last_trade_closes=last_trades,
        payouts=payouts_map,
        exchanges=exchanges,
        merger_terms=merger_terms,
        recovery_ratios=recoveries,
        payout_sources=payout_src,
        payout_confidences=payout_conf,
    )
    write_dlret_csv(table, args.dlret_output)
    print(f"Wrote {args.dlret_output}: {len(table)} DLRET rows (PRIMARY OUTPUT)")
```

Notes for the implementer (variable names confirmed against the current script):
- `av` is the `AvListingLoader` constructed at line ~115 (`av = AvListingLoader(...)`); `av.exchange(ticker, observed_date=...)` is the method used (same as `scripts/compute_corrected_returns.py`).
- `payout_by_ticker: dict[str, PayoutResult]` (line ~145) and `extractor` (line ~144) already exist (used for `payouts.csv`). `PayoutResult` has `.value`, `.source`, `.confidence`.
- `args` is the parsed namespace (line ~112); the parser variable is `p`.

- [ ] **Step 6: Offline smoke check (no network)**

Run a tiny offline check that the script imports and the table builder is wired (does not hit EDGAR):

Run: `conda activate rdagent4qlib && python -c "import scripts.classify_universe as m; import inspect; assert 'build_dlret_table' in inspect.getsource(m); print('wired OK')"`
Expected: `wired OK`

(Full universe run — `python scripts/classify_universe.py --limit 5 --last-trade-closes ...` — is a network/manual step; not part of the offline test gate.)

- [ ] **Step 7: Run the whole suite**

Run: `conda activate rdagent4qlib && pytest -q`
Expected: PASS (all prior 122 tests + the new ones)

- [ ] **Step 8: Commit**

```bash
git add scripts/classify_universe.py src/delist_detection/reconstruction.py tests/test_reconstruction.py
git commit -m "feat: classify_universe emits output/dlret.csv as the primary output"
```

---

## Task 8: Documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Reframe `README.md` around the DLRET table**

Add a top-level section (near the start, after the intro) titled `## Primary output: the DLRET reconstruction table` that documents:
- the `output/dlret.csv` column schema (copy `DLRET_TABLE_COLUMNS`, with a one-line description of each column);
- the per-bucket DLRET policy table (from the spec's `DlretMethod` table);
- a worked **mixed cash+stock** example (AET→CVS: `145 + 0.8378×80 = 212.024`, `/190 − 1 = +11.6%`);
- the command: `python scripts/classify_universe.py --last-trade-closes <csv> --merger-terms <csv> --recoveries <csv>`;
- a note that merger rows without a supplied `last_trade_close` emit a blank `dlret` with `dlret_method=needs_last_trade` (not silently zero).

- [ ] **Step 2: Update `CLAUDE.md`**

- In the architecture section, add `dlret.py` (the DLRET hub: `resolve_dlret`/`DlretResult`/`compute_dlret`) and `reconstruction.py` (`EnrichedDelistRecord`, `enrich`, `build_dlret_table`, `output/dlret.csv`), and note that `output/dlret.csv` is the **primary output**.
- Revise the "Payout extraction is cash-only by design" invariant to: *Auto-extraction from EDGAR remains cash-only. The DLRET table abstains (neutral mark) only when no consideration terms are supplied; when stock-leg terms (`stock_ratio`, `acquirer_price`) are provided via `--merger-terms`, it computes the full cash+stock consideration (e.g. AET→CVS).*
- Add to the commands block: `python scripts/classify_universe.py --last-trade-closes ... --merger-terms ...   # full run incl. output/dlret.csv`.

- [ ] **Step 3: Verify docs reference real symbols**

Run: `conda activate rdagent4qlib && python -c "from delist_detection.reconstruction import DLRET_TABLE_COLUMNS; from delist_detection.dlret import DlretMethod; print(DLRET_TABLE_COLUMNS); print([m.value for m in DlretMethod])"`
Expected: prints the column list and method values referenced in the docs (sanity-check that names match).

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: reframe README/CLAUDE around the DLRET table as primary output"
```

---

## Final verification

- [ ] **Run the full offline suite**

Run: `conda activate rdagent4qlib && pytest -q`
Expected: PASS — all previously-passing tests plus the new `test_dlret.py`, `test_reconstruction.py`, and the added cases in `test_crsp_codes.py` / `test_firm_month_correction.py`.

- [ ] **Confirm the 501/502 fix end-to-end**

Run: `conda activate rdagent4qlib && python -c "from delist_detection.crsp_codes import bucket_for_code, CrspBucket; assert bucket_for_code(501) is CrspBucket.EXCHANGE_TRANSFER; assert bucket_for_code(555) is CrspBucket.COMPLIANCE_FAILURE; print('501/502 fix OK')"`
Expected: `501/502 fix OK`

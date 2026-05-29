# BMP 2007 Firm-Month Return Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Beaver-McNichols-Price (2007) firm-month return correction to `delist_detection`, producing a corrected `R_delisting_month = (1 + R_partial) * (1 + DLRET) - 1` per delisted firm, with exchange-aware Shumway constants for unobservable DLRETs.

**Architecture:** Two new pure modules (`exchanges.py`, `bmp_correction.py`) compute DLRET per bucket and compound it with the partial-month return. The existing event-level `handling.py` API is preserved; a parallel `build_firm_month_correction()` is added. `qlib_adapter.py` gains `apply_bmp_corrections()` that splices corrected monthly returns into a (date, ticker) panel. Downstream consumers (qlib_practice) call this once before normal training/backtest — no per-row special-cases needed afterward.

**Tech Stack:** Python 3.11, pandas, pytest. No new runtime deps. References: Beaver, McNichols & Price (2007, JAE); Shumway (1997, JoF); Shumway & Warther (1999, JoF); Gu, Kelly & Xiu (2020, RFS).

**Scope boundary:** This plan delivers the *corrected return matrix*. It does NOT change the existing event-level handling, and it does NOT touch `qlib_practice` training/backtest scripts — those consume the output and are a separate plan.

**Key facts the engineer must trust without re-deriving:**
- BMP formula: `R_delisting_month = (1 + R_partial) * (1 + DLRET) - 1`, where `R_partial` = return from prior-month-end close to last-trade-day close, `DLRET` = return from last-trade close to delisting cash-out value.
- Shumway constants apply **only** when DLRET is unobservable AND the bucket is performance-related (COMPLIANCE_FAILURE, or LIQUIDATION with no observed recovery). They are NOT applied to M&A.
- NYSE/AMEX performance constant: **-0.30** (Shumway 1997).
- Nasdaq performance constant: **-0.55** (Shumway & Warther 1999).
- The current event-level `forward_return` in `handling.py` is the DLRET, not the firm-month return. We compose them, not replace.

---

## File Structure

**Created:**
- `src/delist_detection/exchanges.py` — Exchange enum + normalize() from AV/EDGAR strings.
- `src/delist_detection/bmp_correction.py` — DLRET resolver per (bucket, exchange) + BMP compound formula.
- `tests/test_exchanges.py`
- `tests/test_bmp_correction.py`
- `tests/test_firm_month_correction.py` — exercises the public `handling.build_firm_month_correction` API.
- `tests/test_qlib_adapter_bmp.py` — exercises the new panel-splice function.
- `scripts/compute_corrected_returns.py` — CLI that reads classifications + a monthly panel CSV and writes a corrected-returns CSV.

**Modified:**
- `src/delist_detection/av_listing.py` — add `exchange()` lookup method (parallel to `.name()`, `.asset_type()`).
- `src/delist_detection/handling.py` — add `FirmMonthReturn` dataclass + `build_firm_month_correction()`.
- `src/delist_detection/qlib_adapter.py` — add `apply_bmp_corrections()`.
- `src/delist_detection/__init__.py` — re-export the new public symbols.
- `README.md` — append a "BMP firm-month correction" section under existing API docs.

---

## Task 1: Exchange enum + AV lookup

**Files:**
- Create: `src/delist_detection/exchanges.py`
- Create: `tests/test_exchanges.py`
- Modify: `src/delist_detection/av_listing.py` (add `exchange()` method)

- [ ] **Step 1: Write the failing test**

Create `tests/test_exchanges.py`:

```python
from delist_detection.exchanges import Exchange, normalize_exchange


def test_normalize_nyse_variants():
    assert normalize_exchange("NYSE") is Exchange.NYSE
    assert normalize_exchange("New York Stock Exchange") is Exchange.NYSE
    assert normalize_exchange("nyse arca") is Exchange.NYSE  # ARCA -> NYSE family


def test_normalize_nasdaq_variants():
    assert normalize_exchange("NASDAQ") is Exchange.NASDAQ
    assert normalize_exchange("Nasdaq Global Select") is Exchange.NASDAQ
    assert normalize_exchange("NASDAQ-NMS") is Exchange.NASDAQ


def test_normalize_amex():
    # AMEX = NYSE American post-2017; both map to AMEX for Shumway purposes
    assert normalize_exchange("AMEX") is Exchange.AMEX
    assert normalize_exchange("NYSE American") is Exchange.AMEX
    assert normalize_exchange("NYSE MKT") is Exchange.AMEX


def test_normalize_unknown_or_missing():
    assert normalize_exchange("") is Exchange.OTHER
    assert normalize_exchange(None) is Exchange.OTHER
    assert normalize_exchange("OTC Markets") is Exchange.OTHER
    assert normalize_exchange("BATS") is Exchange.OTHER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_exchanges.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'delist_detection.exchanges'`

- [ ] **Step 3: Implement `exchanges.py`**

Create `src/delist_detection/exchanges.py`:

```python
"""Listing-exchange normalization for delisting-bias corrections.

The Shumway 1997 / Shumway-Warther 1999 constants are exchange-specific:
NYSE/AMEX performance delistings average ~-30%, Nasdaq ~-55%. We collapse
the proliferation of venue strings (NYSE Arca, NYSE MKT, Nasdaq Global
Select, ...) to four buckets that match how the constants were estimated.
"""

from __future__ import annotations

from enum import Enum


class Exchange(str, Enum):
    NYSE = "nyse"
    AMEX = "amex"
    NASDAQ = "nasdaq"
    OTHER = "other"  # OTC, BATS, IEX, unknown — no Shumway constant applies


_NYSE_TOKENS = ("nyse", "new york stock exchange", "arca")
_AMEX_TOKENS = ("amex", "nyse american", "nyse mkt", "american stock exchange")
_NASDAQ_TOKENS = ("nasdaq",)


def normalize_exchange(raw: str | None) -> Exchange:
    """Map a raw exchange string to the canonical Exchange bucket.

    AMEX is checked before NYSE because "NYSE American" / "NYSE MKT" contain
    "nyse" but represent the AMEX successor venue.
    """
    if not raw:
        return Exchange.OTHER
    s = raw.strip().lower()
    if any(t in s for t in _AMEX_TOKENS):
        return Exchange.AMEX
    if any(t in s for t in _NYSE_TOKENS):
        return Exchange.NYSE
    if any(t in s for t in _NASDAQ_TOKENS):
        return Exchange.NASDAQ
    return Exchange.OTHER
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_exchanges.py -v`
Expected: 4 passed.

- [ ] **Step 5: Add the AV listing `exchange()` lookup method**

Modify `src/delist_detection/av_listing.py` — add this method to `AvListingLoader` right after `asset_type()`:

```python
    def exchange(self, ticker: str, observed_date: str | None = None,
                 max_days_off: int = 365) -> str | None:
        row = self.get(ticker)
        if not row:
            return None
        if observed_date and row.delist_date:
            try:
                from datetime import datetime
                ad = datetime.strptime(row.delist_date, "%Y-%m-%d").date()
                od = datetime.strptime(observed_date, "%Y-%m-%d").date()
                if abs((ad - od).days) > max_days_off:
                    return None
            except ValueError:
                pass
        return row.exchange
```

- [ ] **Step 6: Write a test for the AV exchange lookup**

Append to `tests/test_exchanges.py`:

```python
import textwrap
import pytest
from delist_detection.av_listing import AvListingLoader


@pytest.fixture
def av_csv(tmp_path):
    p = tmp_path / "delisted.csv"
    p.write_text(textwrap.dedent("""\
        symbol,name,exchange,assetType,ipoDate,delistingDate
        ALTR,Altair,NASDAQ,Stock,2017-10-25,2025-03-26
        RSH,RadioShack,NYSE,Stock,1971-08-12,2015-02-09
    """))
    return p


def test_av_loader_exchange_lookup(av_csv):
    loader = AvListingLoader(av_csv)
    assert loader.exchange("ALTR") == "NASDAQ"
    assert loader.exchange("RSH") == "NYSE"
    assert loader.exchange("DOESNOTEXIST") is None
```

- [ ] **Step 7: Run all tests in this task**

Run: `pytest tests/test_exchanges.py -v`
Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
git add src/delist_detection/exchanges.py src/delist_detection/av_listing.py tests/test_exchanges.py
git commit -m "feat: add Exchange enum and AV exchange lookup for Shumway constants"
```

---

## Task 2: BMP DLRET resolver + compound formula

**Files:**
- Create: `src/delist_detection/bmp_correction.py`
- Create: `tests/test_bmp_correction.py`

- [ ] **Step 1: Write failing tests for DLRET resolution**

Create `tests/test_bmp_correction.py`:

```python
import math
import pytest

from delist_detection.bmp_correction import (
    SHUMWAY_NYSE_AMEX, SHUMWAY_NASDAQ, compute_dlret, bmp_firm_month_return,
)
from delist_detection.crsp_codes import CrspBucket
from delist_detection.exchanges import Exchange


# ---- DLRET resolution per bucket ----

def test_dlret_merger_uses_payout():
    # M&A cash: DLRET = payout/last_trade - 1
    dlret = compute_dlret(
        bucket=CrspBucket.MERGER,
        exchange=Exchange.NYSE,
        last_trade_close=100.0,
        payout_per_share=113.0,
    )
    assert dlret == pytest.approx(0.13)


def test_dlret_merger_missing_payout_returns_zero():
    # No deal terms -> neutral mark (DLRET=0); caller should flag for review
    dlret = compute_dlret(
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        last_trade_close=100.0, payout_per_share=None,
    )
    assert dlret == 0.0


def test_dlret_compliance_nyse_amex_uses_shumway_minus30():
    assert compute_dlret(
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NYSE,
        last_trade_close=10.0, payout_per_share=None,
    ) == SHUMWAY_NYSE_AMEX
    assert compute_dlret(
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.AMEX,
        last_trade_close=10.0, payout_per_share=None,
    ) == SHUMWAY_NYSE_AMEX
    assert SHUMWAY_NYSE_AMEX == pytest.approx(-0.30)


def test_dlret_compliance_nasdaq_uses_shumway_minus55():
    assert compute_dlret(
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NASDAQ,
        last_trade_close=10.0, payout_per_share=None,
    ) == SHUMWAY_NASDAQ
    assert SHUMWAY_NASDAQ == pytest.approx(-0.55)


def test_dlret_compliance_other_exchange_falls_back_to_nasdaq_constant():
    # Conservative default for unknown venues (OTC, BATS, etc.)
    assert compute_dlret(
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.OTHER,
        last_trade_close=10.0, payout_per_share=None,
    ) == SHUMWAY_NASDAQ


def test_dlret_liquidation_with_observed_recovery():
    # Recovery known: DLRET = recovery_ratio - 1
    dlret = compute_dlret(
        bucket=CrspBucket.LIQUIDATION, exchange=Exchange.NYSE,
        last_trade_close=10.0, payout_per_share=None,
        recovery_ratio=0.20,
    )
    assert dlret == pytest.approx(-0.80)


def test_dlret_liquidation_no_recovery_falls_back_to_shumway():
    # No recovery observed: treat as performance delisting
    dlret = compute_dlret(
        bucket=CrspBucket.LIQUIDATION, exchange=Exchange.NASDAQ,
        last_trade_close=10.0, payout_per_share=None,
        recovery_ratio=None,
    )
    assert dlret == SHUMWAY_NASDAQ


def test_dlret_exchange_transfer_is_zero():
    # Security continues elsewhere; no DLRET shock at this venue
    assert compute_dlret(
        bucket=CrspBucket.EXCHANGE_TRANSFER, exchange=Exchange.NYSE,
        last_trade_close=10.0, payout_per_share=None,
    ) == 0.0


def test_dlret_expiration_is_nan_to_signal_drop():
    # Not equity universe — caller should drop, not compound
    dlret = compute_dlret(
        bucket=CrspBucket.EXPIRATION, exchange=Exchange.NYSE,
        last_trade_close=10.0, payout_per_share=None,
    )
    assert math.isnan(dlret)


# ---- BMP compound formula ----

def test_bmp_compound_merger():
    # Prior month-end 100, last trade 105, payout 113
    # R_partial = 0.05, DLRET = 113/105 - 1 ≈ 0.0762
    # R_month = (1.05)(1.0762) - 1 ≈ 0.13
    r = bmp_firm_month_return(
        prior_month_end_close=100.0, last_trade_close=105.0,
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        payout_per_share=113.0,
    )
    assert r == pytest.approx(0.13)


def test_bmp_compound_compliance_nasdaq():
    # Prior 100, last trade 80 (-20% partial), Shumway -55% on Nasdaq
    # R_month = (0.80)(0.45) - 1 = -0.64
    r = bmp_firm_month_return(
        prior_month_end_close=100.0, last_trade_close=80.0,
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NASDAQ,
        payout_per_share=None,
    )
    assert r == pytest.approx(-0.64)


def test_bmp_compound_compliance_nyse():
    # Prior 100, last trade 80 (-20%), Shumway -30% on NYSE
    # R_month = (0.80)(0.70) - 1 = -0.44
    r = bmp_firm_month_return(
        prior_month_end_close=100.0, last_trade_close=80.0,
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NYSE,
        payout_per_share=None,
    )
    assert r == pytest.approx(-0.44)


def test_bmp_compound_expiration_is_nan():
    r = bmp_firm_month_return(
        prior_month_end_close=100.0, last_trade_close=80.0,
        bucket=CrspBucket.EXPIRATION, exchange=Exchange.NYSE,
        payout_per_share=None,
    )
    assert math.isnan(r)


def test_bmp_compound_invalid_prior_close_returns_nan():
    # Cannot compute R_partial without prior month-end
    r = bmp_firm_month_return(
        prior_month_end_close=0.0, last_trade_close=80.0,
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NYSE,
        payout_per_share=None,
    )
    assert math.isnan(r)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bmp_correction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'delist_detection.bmp_correction'`

- [ ] **Step 3: Implement `bmp_correction.py`**

Create `src/delist_detection/bmp_correction.py`:

```python
"""Beaver-McNichols-Price (2007) firm-month return correction.

The CRSP "delisting bias" arises when the price panel truncates at the
last observed trade and discards the cash-out value at delist. BMP 2007
shows that the unbiased firm-month return is:

    R_delisting_month = (1 + R_partial) * (1 + DLRET) - 1

    R_partial = last_trade_close / prior_month_end_close - 1
    DLRET     = final_cashout_value  / last_trade_close      - 1

For panels without an observed DLRET (Tiingo, IEX, most alt-data feeds),
we synthesize DLRET per bucket:

  MERGER             : payout/last_trade - 1   (from EDGAR 8-K Item 2.01)
  EXCHANGE_TRANSFER  : 0                       (security continues; no shock)
  LIQUIDATION        : recovery_ratio - 1      (if observed)
                       Shumway constant by exchange (if not)
  COMPLIANCE_FAILURE : Shumway constant by exchange
  EXPIRATION         : NaN  (drop, not equity universe)

The Shumway constants come from:
  Shumway (1997)              : NYSE/AMEX performance delistings avg ~-30%
  Shumway & Warther (1999)    : Nasdaq performance delistings avg ~-55%
They are applied only when DLRET is unobservable AND the bucket is
performance-related (COMPLIANCE_FAILURE, or LIQUIDATION w/o recovery).
"""

from __future__ import annotations

import math

from .crsp_codes import CrspBucket
from .exchanges import Exchange


SHUMWAY_NYSE_AMEX: float = -0.30
SHUMWAY_NASDAQ: float = -0.55


def _shumway_constant(exchange: Exchange) -> float:
    """Return the exchange-appropriate Shumway constant.

    OTHER (OTC, BATS, IEX, unknown) defaults to the more conservative
    Nasdaq constant — it captures the typical "no real bid" outcome.
    """
    if exchange in (Exchange.NYSE, Exchange.AMEX):
        return SHUMWAY_NYSE_AMEX
    return SHUMWAY_NASDAQ


def compute_dlret(
    bucket: CrspBucket,
    exchange: Exchange,
    last_trade_close: float,
    payout_per_share: float | None,
    recovery_ratio: float | None = None,
) -> float:
    """Resolve DLRET for a single delisting event.

    Returns NaN for EXPIRATION (caller must drop). Returns 0.0 for
    EXCHANGE_TRANSFER (no shock at this venue; successor handles it).
    """
    if bucket is CrspBucket.EXPIRATION:
        return float("nan")

    if bucket is CrspBucket.EXCHANGE_TRANSFER:
        return 0.0

    if bucket is CrspBucket.MERGER:
        if payout_per_share is None or last_trade_close <= 0:
            return 0.0  # neutral mark; caller may flag for review
        return (payout_per_share / last_trade_close) - 1.0

    if bucket is CrspBucket.LIQUIDATION:
        if recovery_ratio is not None:
            return recovery_ratio - 1.0
        return _shumway_constant(exchange)

    if bucket is CrspBucket.COMPLIANCE_FAILURE:
        return _shumway_constant(exchange)

    # ACTIVE / UNKNOWN: no shock by default
    return 0.0


def bmp_firm_month_return(
    prior_month_end_close: float,
    last_trade_close: float,
    bucket: CrspBucket,
    exchange: Exchange,
    payout_per_share: float | None = None,
    recovery_ratio: float | None = None,
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
    )
    if math.isnan(dlret):
        return float("nan")
    if prior_month_end_close <= 0:
        return float("nan")
    r_partial = (last_trade_close / prior_month_end_close) - 1.0
    return (1.0 + r_partial) * (1.0 + dlret) - 1.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bmp_correction.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/bmp_correction.py tests/test_bmp_correction.py
git commit -m "feat: BMP 2007 DLRET resolver and firm-month compound formula"
```

---

## Task 3: Wire BMP into `handling.py` as a parallel public API

**Files:**
- Modify: `src/delist_detection/handling.py`
- Create: `tests/test_firm_month_correction.py`

The existing `build_train_label_adjustment` and `build_backtest_exit` stay untouched. We add a new function returning a new dataclass — they coexist.

- [ ] **Step 1: Write failing tests**

Create `tests/test_firm_month_correction.py`:

```python
import math
import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.exchanges import Exchange
from delist_detection.handling import (
    FirmMonthReturn, build_firm_month_correction,
)


def _rec(ticker="ALTR", bucket=CrspBucket.MERGER, code=231,
         delist="2025-03-26"):
    return DelistRecord(
        ticker=ticker, cik=1701732, observed_delist_date=delist,
        crsp_code=code, bucket=bucket, confidence="high", reason="test",
    )


def test_firm_month_correction_merger():
    out = build_firm_month_correction(
        record=_rec(bucket=CrspBucket.MERGER),
        prior_month_end_close=100.0, last_trade_close=105.0,
        exchange=Exchange.NASDAQ,
        payout_per_share=113.0,
    )
    assert isinstance(out, FirmMonthReturn)
    assert out.ticker == "ALTR"
    assert out.bucket is CrspBucket.MERGER
    assert out.exchange is Exchange.NASDAQ
    assert out.firm_month_return == pytest.approx(0.13)
    assert out.dlret == pytest.approx((113 - 105) / 105)
    assert out.r_partial == pytest.approx(0.05)


def test_firm_month_correction_compliance_nyse_default_exchange():
    # Exchange omitted -> defaults to OTHER -> conservative Nasdaq constant
    out = build_firm_month_correction(
        record=_rec(ticker="RSH", bucket=CrspBucket.COMPLIANCE_FAILURE,
                    code=584),
        prior_month_end_close=100.0, last_trade_close=80.0,
        exchange=None,
        payout_per_share=None,
    )
    # R_month = (0.80)(0.45) - 1
    assert out.firm_month_return == pytest.approx(-0.64)
    assert out.exchange is Exchange.OTHER


def test_firm_month_correction_expiration_returns_nan_and_flag():
    out = build_firm_month_correction(
        record=_rec(bucket=CrspBucket.EXPIRATION, code=600),
        prior_month_end_close=100.0, last_trade_close=80.0,
        exchange=Exchange.NYSE, payout_per_share=None,
    )
    assert math.isnan(out.firm_month_return)
    assert out.drop is True


def test_firm_month_correction_keeps_non_expiration_in_panel():
    out = build_firm_month_correction(
        record=_rec(bucket=CrspBucket.MERGER),
        prior_month_end_close=100.0, last_trade_close=105.0,
        exchange=Exchange.NASDAQ, payout_per_share=113.0,
    )
    assert out.drop is False


def test_firm_month_correction_no_delist_date_drops():
    rec = _rec(delist=None)
    out = build_firm_month_correction(
        record=rec, prior_month_end_close=100.0, last_trade_close=80.0,
        exchange=Exchange.NYSE, payout_per_share=None,
    )
    assert out.drop is True
    assert math.isnan(out.firm_month_return)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_firm_month_correction.py -v`
Expected: FAIL — `ImportError: cannot import name 'FirmMonthReturn'`

- [ ] **Step 3: Add `FirmMonthReturn` and `build_firm_month_correction`**

Modify `src/delist_detection/handling.py` — add these imports near the top:

```python
import math

from .bmp_correction import bmp_firm_month_return, compute_dlret
from .exchanges import Exchange
```

Add this dataclass after `BacktestExit`:

```python
@dataclass
class FirmMonthReturn:
    """BMP 2007 corrected firm-month return for the delisting month."""
    ticker: str
    bucket: CrspBucket
    exchange: Exchange
    delist_date: date
    firm_month_return: float    # the corrected R_month (NaN means drop)
    r_partial: float            # (last_trade / prior_month_end) - 1
    dlret: float                # cash-out return implied by bucket+exchange
    drop: bool                  # True -> remove this firm-month from panel
    notes: str = ""
```

Add this function at the bottom of the module:

```python
def build_firm_month_correction(
    record: DelistRecord,
    prior_month_end_close: float,
    last_trade_close: float,
    exchange: Exchange | None,
    payout_per_share: float | None = None,
    recovery_ratio: float | None = None,
) -> FirmMonthReturn:
    """Compute the BMP 2007 corrected firm-month return for one delisting.

    `exchange=None` falls back to Exchange.OTHER, which uses the
    conservative Nasdaq Shumway constant for performance delistings.
    """
    dd = _parse(record.observed_delist_date)
    ex = exchange or Exchange.OTHER
    if dd is None:
        return FirmMonthReturn(
            ticker=record.ticker, bucket=record.bucket, exchange=ex,
            delist_date=date.today(),
            firm_month_return=float("nan"), r_partial=float("nan"),
            dlret=float("nan"), drop=True,
            notes="No delist date; dropping from panel",
        )

    dlret = compute_dlret(
        bucket=record.bucket, exchange=ex,
        last_trade_close=last_trade_close,
        payout_per_share=payout_per_share,
        recovery_ratio=recovery_ratio,
    )
    r_month = bmp_firm_month_return(
        prior_month_end_close=prior_month_end_close,
        last_trade_close=last_trade_close,
        bucket=record.bucket, exchange=ex,
        payout_per_share=payout_per_share,
        recovery_ratio=recovery_ratio,
    )
    drop = math.isnan(r_month)

    r_partial = (
        (last_trade_close / prior_month_end_close) - 1.0
        if prior_month_end_close > 0 else float("nan")
    )

    return FirmMonthReturn(
        ticker=record.ticker, bucket=record.bucket, exchange=ex,
        delist_date=dd,
        firm_month_return=r_month, r_partial=r_partial, dlret=dlret,
        drop=drop,
        notes=(
            f"BMP({record.bucket.value}, {ex.value}): "
            f"R_partial={r_partial:.4f}, DLRET={dlret:.4f}"
            if not drop else
            f"Dropped ({record.bucket.value}): NaN firm-month return"
        ),
    )
```

- [ ] **Step 4: Run new tests + existing handling tests**

Run: `pytest tests/test_firm_month_correction.py tests/test_handling.py -v`
Expected: All pass. The existing `test_handling.py` is unchanged because we did not modify the existing API.

- [ ] **Step 5: Re-export from package init**

Modify `src/delist_detection/__init__.py` — append:

```python
from .exchanges import Exchange, normalize_exchange
from .bmp_correction import (
    SHUMWAY_NYSE_AMEX, SHUMWAY_NASDAQ,
    compute_dlret, bmp_firm_month_return,
)
from .handling import FirmMonthReturn, build_firm_month_correction
```

If `__init__.py` already has `__all__`, append: `"Exchange"`, `"normalize_exchange"`, `"SHUMWAY_NYSE_AMEX"`, `"SHUMWAY_NASDAQ"`, `"compute_dlret"`, `"bmp_firm_month_return"`, `"FirmMonthReturn"`, `"build_firm_month_correction"`.

- [ ] **Step 6: Run full test suite**

Run: `pytest -q`
Expected: All existing 19 tests still pass + new tests pass. No collection errors.

- [ ] **Step 7: Commit**

```bash
git add src/delist_detection/handling.py src/delist_detection/__init__.py tests/test_firm_month_correction.py
git commit -m "feat: build_firm_month_correction wires BMP into handling API"
```

---

## Task 4: Panel splice — `apply_bmp_corrections()` in `qlib_adapter.py`

**Files:**
- Modify: `src/delist_detection/qlib_adapter.py`
- Create: `tests/test_qlib_adapter_bmp.py`

This is the operational entry point: read classifications + monthly panel → splice corrected R_delisting_month into the panel.

**Input contract:** `panel` is a DataFrame with MultiIndex `(date, instrument)` where `date` is a *month-end* DatetimeIndex level and there is a `monthly_return` column (simple return for the month). The panel may also have a `close` column (last close of the month) — if present, we read prior-month-end close from it.

**Output:** new DataFrame with the same shape; for each delisted ticker, the row at `(delist_month_end, ticker)` has its `monthly_return` overwritten with the BMP-corrected value. If `drop=True`, the row is removed entirely.

- [ ] **Step 1: Write failing tests**

Create `tests/test_qlib_adapter_bmp.py`:

```python
import csv
from pathlib import Path

import pandas as pd
import pytest

from delist_detection.qlib_adapter import apply_bmp_corrections


@pytest.fixture
def classifications_csv(tmp_path: Path) -> Path:
    p = tmp_path / "cls.csv"
    p.write_text(
        "ticker,cik,observed_delist_date,crsp_code,bucket,confidence,reason\n"
        "ALTR,1701732,2025-03-26,231,merger,high,M&A\n"
        "RSH,1144980,2015-02-09,584,compliance_failure,high,Form 25 + Form 15\n"
        "ZEXP,9999999,2020-06-15,600,expiration,medium,scheduled\n"
    )
    return p


@pytest.fixture
def monthly_panel() -> pd.DataFrame:
    # Month-end panel with two columns: close + monthly_return.
    # ALTR delists 2025-03-26 (March): prior_month_end Feb 2025, last_trade 2025-03-25.
    # RSH  delists 2015-02-09 (Feb):   prior_month_end Jan 2015, last_trade 2015-02-06.
    # ZEXP delists 2020-06-15: should be dropped.
    rows = [
        ("2025-02-28", "ALTR", 100.0, 0.04),
        ("2025-03-31", "ALTR", 105.0, 0.05),   # truncated raw value; will be overwritten
        ("2015-01-31", "RSH",  0.50, -0.10),
        ("2015-02-28", "RSH",  0.40, -0.20),   # truncated; will be overwritten
        ("2020-05-31", "ZEXP", 1.00, 0.00),
        ("2020-06-30", "ZEXP", 1.00, 0.00),    # should be dropped
        ("2025-02-28", "OTHER", 50.0, 0.01),   # untouched
        ("2025-03-31", "OTHER", 52.0, 0.04),   # untouched
    ]
    df = pd.DataFrame(rows, columns=["date", "instrument", "close", "monthly_return"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index(["date", "instrument"]).sort_index()


def test_apply_bmp_corrections_overwrites_merger_month(
    monthly_panel, classifications_csv,
):
    out = apply_bmp_corrections(
        monthly_panel, str(classifications_csv),
        payouts={"ALTR": 113.0},
        exchanges={"ALTR": "NASDAQ", "RSH": "NYSE"},
        last_trade_closes={"ALTR": 105.0, "RSH": 0.40},
        return_col="monthly_return",
    )
    # ALTR: (1.05)(1.0762) - 1 ≈ 0.13
    altr = out.xs("ALTR", level="instrument")
    assert altr.loc[pd.Timestamp("2025-03-31"), "monthly_return"] == pytest.approx(0.13, rel=1e-3)
    # Prior month untouched
    assert altr.loc[pd.Timestamp("2025-02-28"), "monthly_return"] == pytest.approx(0.04)


def test_apply_bmp_corrections_compliance_uses_shumway_minus30_for_nyse(
    monthly_panel, classifications_csv,
):
    out = apply_bmp_corrections(
        monthly_panel, str(classifications_csv),
        payouts={},
        exchanges={"RSH": "NYSE"},
        last_trade_closes={"RSH": 0.40},
        return_col="monthly_return",
    )
    # R_partial Jan->Feb close: 0.40/0.50 - 1 = -0.20
    # DLRET (NYSE Shumway) = -0.30
    # R_month = (0.80)(0.70) - 1 = -0.44
    rsh = out.xs("RSH", level="instrument")
    assert rsh.loc[pd.Timestamp("2015-02-28"), "monthly_return"] == pytest.approx(-0.44, rel=1e-3)


def test_apply_bmp_corrections_drops_expiration_month(
    monthly_panel, classifications_csv,
):
    out = apply_bmp_corrections(
        monthly_panel, str(classifications_csv),
        payouts={}, exchanges={}, last_trade_closes={"ZEXP": 1.0},
        return_col="monthly_return",
    )
    zexp = out.xs("ZEXP", level="instrument")
    # June 2020 row dropped (expiration); May 2020 still present
    assert pd.Timestamp("2020-06-30") not in zexp.index
    assert pd.Timestamp("2020-05-31") in zexp.index


def test_apply_bmp_corrections_does_not_touch_unrelated_tickers(
    monthly_panel, classifications_csv,
):
    out = apply_bmp_corrections(
        monthly_panel, str(classifications_csv),
        payouts={"ALTR": 113.0},
        exchanges={"ALTR": "NASDAQ"},
        last_trade_closes={"ALTR": 105.0},
        return_col="monthly_return",
    )
    other = out.xs("OTHER", level="instrument")
    assert other.loc[pd.Timestamp("2025-03-31"), "monthly_return"] == pytest.approx(0.04)
    assert other.loc[pd.Timestamp("2025-02-28"), "monthly_return"] == pytest.approx(0.01)


def test_apply_bmp_corrections_returns_copy_not_mutation(
    monthly_panel, classifications_csv,
):
    before = monthly_panel.copy()
    _ = apply_bmp_corrections(
        monthly_panel, str(classifications_csv),
        payouts={"ALTR": 113.0}, exchanges={"ALTR": "NASDAQ"},
        last_trade_closes={"ALTR": 105.0}, return_col="monthly_return",
    )
    pd.testing.assert_frame_equal(monthly_panel, before)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_qlib_adapter_bmp.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_bmp_corrections'`

- [ ] **Step 3: Implement `apply_bmp_corrections`**

Modify `src/delist_detection/qlib_adapter.py` — add these imports at the top:

```python
from .exchanges import Exchange, normalize_exchange
from .handling import build_firm_month_correction
```

Add this function at the bottom of the module:

```python
def apply_bmp_corrections(
    panel: pd.DataFrame,
    classifications_csv: str,
    payouts: Mapping[str, float] | None = None,
    exchanges: Mapping[str, str] | None = None,
    last_trade_closes: Mapping[str, float] | None = None,
    recovery_ratios: Mapping[str, float] | None = None,
    return_col: str = "monthly_return",
    close_col: str = "close",
) -> pd.DataFrame:
    """Splice the BMP 2007 corrected R_delisting_month into a monthly panel.

    For each delisted ticker, find the panel row whose date-level value is the
    month-end containing `observed_delist_date`, then overwrite `return_col`
    with `(1 + R_partial) * (1 + DLRET) - 1`. If the firm-month must be
    dropped (EXPIRATION, no delist date, invalid prior close), remove the row.

    Args:
        panel: MultiIndex (date, instrument) DataFrame with month-end dates.
        payouts: ticker -> cash-equivalent payout per share (M&A).
        exchanges: ticker -> raw exchange string (NYSE, NASDAQ, AMEX, ...).
        last_trade_closes: ticker -> the close on the last trading day before
            delist. Required for M&A and for non-month-end delists. Falls back
            to the panel's close on the delist-month-end row if absent.
        recovery_ratios: ticker -> observed liquidation recovery fraction.
    """
    payouts = payouts or {}
    exchanges = exchanges or {}
    last_trade_closes = last_trade_closes or {}
    recovery_ratios = recovery_ratios or {}

    df = panel.copy()
    cls = load_classifications(classifications_csv)

    rows_to_drop: list[tuple] = []

    for _, row in cls.iterrows():
        rec = _record_from_row(row)
        ticker = rec.ticker
        if rec.observed_delist_date is None:
            continue
        if ticker not in df.index.get_level_values("instrument"):
            continue

        slc = df.xs(ticker, level="instrument", drop_level=False)
        if slc.empty:
            continue

        # Find the month-end on or after observed_delist_date that exists in
        # the panel for this ticker.
        delist_ts = pd.Timestamp(rec.observed_delist_date)
        ticker_dates = slc.index.get_level_values("date")
        candidates = ticker_dates[ticker_dates >= delist_ts]
        if len(candidates) == 0:
            # Panel ends before delist; nothing to splice
            continue
        delist_month_end = candidates.min()

        # Prior month-end row (last row strictly before delist_month_end)
        prior_dates = ticker_dates[ticker_dates < delist_month_end]
        if len(prior_dates) == 0:
            continue
        prior_month_end = prior_dates.max()

        prior_close = float(df.loc[(prior_month_end, ticker), close_col])
        last_trade_close = float(
            last_trade_closes.get(ticker, df.loc[(delist_month_end, ticker), close_col])
        )

        ex = normalize_exchange(exchanges.get(ticker))

        fm = build_firm_month_correction(
            record=rec,
            prior_month_end_close=prior_close,
            last_trade_close=last_trade_close,
            exchange=ex,
            payout_per_share=payouts.get(ticker),
            recovery_ratio=recovery_ratios.get(ticker),
        )

        if fm.drop:
            rows_to_drop.append((delist_month_end, ticker))
        else:
            df.loc[(delist_month_end, ticker), return_col] = fm.firm_month_return

    if rows_to_drop:
        df = df.drop(index=rows_to_drop)

    return df
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_qlib_adapter_bmp.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run full suite to confirm no regressions**

Run: `pytest -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/qlib_adapter.py tests/test_qlib_adapter_bmp.py
git commit -m "feat: apply_bmp_corrections splices corrected R_month into qlib panel"
```

---

## Task 5: End-to-end script — `compute_corrected_returns.py`

A CLI that reads classifications + a monthly panel + per-ticker metadata CSVs and emits a corrected-returns panel, so qlib_practice can pick it up without library dependencies.

**Files:**
- Create: `scripts/compute_corrected_returns.py`

- [ ] **Step 1: Write the script**

Create `scripts/compute_corrected_returns.py`:

```python
"""Apply BMP 2007 firm-month corrections to a monthly panel.

Usage:
    python scripts/compute_corrected_returns.py \
        --panel data/monthly_panel.parquet \
        --classifications output/delist_classifications.csv \
        --av-csv data/listing_status_delisted.csv \
        --payouts data/payouts.csv \
        --out output/corrected_monthly_panel.parquet

Inputs:
    --panel: parquet/csv with MultiIndex (date, instrument) and columns
             ['close', 'monthly_return']. Dates must be month-ends.
    --classifications: output of scripts/classify_universe.py
    --av-csv: Alpha Vantage delisted listing-status CSV (used for exchange)
    --payouts (optional): CSV with columns 'ticker,payout_per_share'
    --recoveries (optional): CSV with columns 'ticker,recovery_ratio'
    --last-trade-closes (optional): CSV with columns 'ticker,last_trade_close'
                       If absent, uses panel close on delist-month-end.

Output: same shape as input with monthly_return spliced to BMP-corrected
        value at the delisting month; EXPIRATION rows removed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from delist_detection.av_listing import AvListingLoader
from delist_detection.qlib_adapter import apply_bmp_corrections


def _read_panel(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, parse_dates=["date"])
    if not isinstance(df.index, pd.MultiIndex):
        df = df.set_index(["date", "instrument"]).sort_index()
    return df


def _read_map(path: Path | None, value_col: str) -> dict[str, float]:
    if not path:
        return {}
    df = pd.read_csv(path)
    return dict(zip(df["ticker"].astype(str).str.upper(), df[value_col].astype(float)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", type=Path, required=True)
    p.add_argument("--classifications", type=Path, required=True)
    p.add_argument("--av-csv", type=Path, required=True)
    p.add_argument("--payouts", type=Path, default=None)
    p.add_argument("--recoveries", type=Path, default=None)
    p.add_argument("--last-trade-closes", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    panel = _read_panel(args.panel)

    av = AvListingLoader(args.av_csv)
    cls_df = pd.read_csv(args.classifications, dtype={"ticker": str})
    exchanges: dict[str, str] = {}
    for ticker in cls_df["ticker"].dropna().unique():
        ex = av.exchange(str(ticker))
        if ex:
            exchanges[str(ticker).upper()] = ex

    payouts = _read_map(args.payouts, "payout_per_share")
    recoveries = _read_map(args.recoveries, "recovery_ratio")
    last_trades = _read_map(args.last_trade_closes, "last_trade_close")

    corrected = apply_bmp_corrections(
        panel=panel,
        classifications_csv=str(args.classifications),
        payouts=payouts,
        exchanges=exchanges,
        last_trade_closes=last_trades,
        recovery_ratios=recoveries,
        return_col="monthly_return",
        close_col="close",
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.suffix == ".parquet":
        corrected.to_parquet(args.out)
    else:
        corrected.to_csv(args.out)

    n_before = len(panel)
    n_after = len(corrected)
    print(
        f"BMP correction: {n_before} -> {n_after} rows "
        f"({n_before - n_after} dropped, "
        f"{len(cls_df)} delisting events processed)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test the script with a synthetic panel**

Run from repo root:

```bash
python -c "
import pandas as pd
from pathlib import Path
rows = [
    ('2025-02-28','ALTR',100.0, 0.04),
    ('2025-03-31','ALTR',105.0, 0.05),
    ('2025-02-28','OTHER',50.0, 0.01),
    ('2025-03-31','OTHER',52.0, 0.04),
]
df = pd.DataFrame(rows, columns=['date','instrument','close','monthly_return'])
df['date'] = pd.to_datetime(df['date'])
df = df.set_index(['date','instrument']).sort_index()
Path('/tmp/test_panel.csv').write_text(df.to_csv())
"
```

Then run:

```bash
python scripts/compute_corrected_returns.py \
    --panel /tmp/test_panel.csv \
    --classifications output/delist_classifications.csv \
    --av-csv data/listing_status_delisted.csv 2>/dev/null || true \
    --out /tmp/corrected.csv
```

(If `data/listing_status_delisted.csv` does not exist in this repo, the script must still work — substitute a one-line minimal CSV: `symbol,name,exchange,assetType,ipoDate,delistingDate\nALTR,Altair,NASDAQ,Stock,,2025-03-26`.)

Expected stdout: `BMP correction: 4 -> 4 rows (0 dropped, N delisting events processed)` where N = rows in classifications CSV.

- [ ] **Step 3: Commit**

```bash
git add scripts/compute_corrected_returns.py
git commit -m "feat: compute_corrected_returns.py CLI for BMP-corrected panel"
```

---

## Task 6: Verification against three known cases

Sanity-check the pipeline on real delistings from the classifier output:
- **ALTR** (Altair, NASDAQ, M&A 231): Siemens deal at $113/share, last trade ~$111.85 → corrected return ≈ payout-driven, near 0% if mid-month and price tracking deal.
- **AABA** (Altaba, NYSE, liquidation 400): observable recovery via cash distributions.
- **RSH** (RadioShack, NYSE, compliance 584): pre-bankruptcy crash; Shumway -30%.

**Files:**
- Create: `tests/test_known_cases_bmp.py`

- [ ] **Step 1: Write the test**

Create `tests/test_known_cases_bmp.py`:

```python
"""Sanity tests on real delisting cases from output/delist_classifications.csv.

These pin the expected BMP-corrected return to published deal terms so a
regression in the formula or the constants table is caught immediately.
"""

import pytest

from delist_detection.bmp_correction import bmp_firm_month_return
from delist_detection.crsp_codes import CrspBucket
from delist_detection.exchanges import Exchange


def test_altair_siemens_acquisition_march_2025():
    # ALTR — Siemens cash deal at $113.00/share, last trade ~$111.85 on Nasdaq.
    # Feb 2025 month-end close ~ $111.50 (approximate).
    r = bmp_firm_month_return(
        prior_month_end_close=111.50,
        last_trade_close=111.85,
        bucket=CrspBucket.MERGER, exchange=Exchange.NASDAQ,
        payout_per_share=113.00,
    )
    # R_partial = 111.85/111.50 - 1 ≈ 0.00314
    # DLRET = 113/111.85 - 1 ≈ 0.01028
    # R_month ≈ 0.01345
    assert r == pytest.approx(0.01345, rel=5e-3)


def test_radioshack_compliance_failure_feb_2015():
    # RSH — Ch.11 bankruptcy filing 2015-02-05, delist 2015-02-09 on NYSE.
    # Stock collapsed from ~$0.50 (Jan close) to ~$0.05 (last quote).
    # NYSE Shumway = -0.30.
    r = bmp_firm_month_return(
        prior_month_end_close=0.50,
        last_trade_close=0.05,
        bucket=CrspBucket.COMPLIANCE_FAILURE, exchange=Exchange.NYSE,
        payout_per_share=None,
    )
    # R_partial = 0.05/0.50 - 1 = -0.90
    # DLRET = -0.30
    # R_month = (0.10)(0.70) - 1 = -0.93
    assert r == pytest.approx(-0.93, rel=1e-3)


def test_altaba_liquidation_with_observed_recovery_nov_2019():
    # AABA — Altaba liquidation, returned ~$93/share in distributions vs
    # last trade ~$22.85. Recovery ratio reflects total returned-to-shareholders.
    # For this test, assume recovery_ratio=4.07 (very large; reflects fund-style
    # liquidation, not bankruptcy). This exercises that LIQUIDATION respects
    # observed recovery instead of Shumway.
    r = bmp_firm_month_return(
        prior_month_end_close=22.50,
        last_trade_close=22.85,
        bucket=CrspBucket.LIQUIDATION, exchange=Exchange.NYSE,
        payout_per_share=None,
        recovery_ratio=4.07,
    )
    # R_partial = 22.85/22.50 - 1 ≈ 0.01556
    # DLRET = 4.07 - 1 = 3.07
    # R_month = (1.01556)(4.07) - 1 ≈ 3.1333
    assert r == pytest.approx(3.1333, rel=1e-3)
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_known_cases_bmp.py -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_known_cases_bmp.py
git commit -m "test: pin BMP results for ALTR, RSH, AABA known delistings"
```

---

## Task 7: Document the new API in README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append new section to README**

Append the following section to `README.md` after the existing `### qlib panel integration` block:

````markdown
### BMP 2007 firm-month return correction

The handling/exit API above operates at the *event* level (one terminal
label, one exit cashflow per ticker). For papers that compute returns
the way CRSP does — at the firm-month level — use the BMP 2007
correction. It compounds the partial-month price return with a
synthesized DLRET to produce the unbiased return for the delisting
month, after which all training/backtest math is the same as for any
other firm-month.

```python
from delist_detection import (
    Exchange, build_firm_month_correction,
)
from delist_detection.qlib_adapter import apply_bmp_corrections

# Per-event API
fm = build_firm_month_correction(
    record=rec,
    prior_month_end_close=111.50, last_trade_close=111.85,
    exchange=Exchange.NASDAQ,
    payout_per_share=113.0,
)
# FirmMonthReturn(firm_month_return=0.0134, r_partial=0.0031, dlret=0.0103, ...)

# Panel-level API: splice corrected R_month into a monthly (date, ticker) panel
corrected_panel = apply_bmp_corrections(
    monthly_panel,
    "output/delist_classifications.csv",
    payouts={"ALTR": 113.0},
    exchanges={"ALTR": "NASDAQ", "RSH": "NYSE"},
    last_trade_closes={"ALTR": 111.85, "RSH": 0.05},
    return_col="monthly_return",
)
```

Shumway constants used when DLRET is not observed:

| Bucket | NYSE/AMEX | Nasdaq | Source |
|---|---|---|---|
| COMPLIANCE_FAILURE | -0.30 | -0.55 | Shumway 1997, Shumway-Warther 1999 |
| LIQUIDATION (no recovery) | -0.30 | -0.55 | as above |
| MERGER | payout-driven | payout-driven | EDGAR 8-K Item 2.01 |
| EXCHANGE_TRANSFER | 0 | 0 | security continues at successor |
| EXPIRATION | NaN (drop) | NaN (drop) | not equity universe |

CLI for batch correction of a monthly panel:

```bash
python scripts/compute_corrected_returns.py \
    --panel data/monthly_panel.parquet \
    --classifications output/delist_classifications.csv \
    --av-csv data/listing_status_delisted.csv \
    --payouts data/payouts.csv \
    --out output/corrected_monthly_panel.parquet
```
````

- [ ] **Step 2: Verify the README still renders cleanly**

Run: `python -c "import pathlib; print(pathlib.Path('README.md').read_text()[:200])"`
Expected: prints the first 200 characters of README (sanity check on encoding).

- [ ] **Step 3: Final full test suite run**

Run: `pytest -q`
Expected: All existing tests + new tests pass.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document BMP firm-month correction API in README"
```

---

## Out of scope (deferred to follow-up plans)

The user's write-up references training-side and backtest-side practices from Gu-Kelly-Xiu (2020) and Beaver-McNichols-Price (2007):

- **GKX-style training**: cross-sectional rank features to [-1,1], Huber loss, include all firm-months without filtering by price/share-code/sector.
- **BMP-style backtest**: portfolio return = weighted average of corrected firm-month returns, IC/R² on the same corrected matrix.

These belong in `qlib_practice`, not `delist_detection`. They consume `corrected_monthly_panel.parquet` from this plan. A separate plan (`2026-05-27-gkx-walk-forward-with-bmp.md`) should:

1. Wire `apply_bmp_corrections` into the qlib panel-build step.
2. Replace LightGBM's default L2 objective with Huber (`objective='huber'`).
3. Cross-sectionally rank Alpha158 features to [-1,1] per month.
4. Add an A/B test: same walk-forward run with and without BMP correction, comparing IC and decile-portfolio P&L. This is the Sloan-style sensitivity demonstration from BMP 2007.

That plan is out of scope here. Stop after Task 7.

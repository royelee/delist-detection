# DLRET Reconstruction as the Library's Primary Output — Design

*Spec · 2026-05-31 · status: approved for planning*

## Overview

Make a per-delisting **DLRET reconstruction table** the library's primary
deliverable, and refactor the codebase so DLRET is the structural hub. Today the
library's headline artifact is `output/delist_classifications.csv` (classification
facts), and DLRET is computed only incidentally inside `apply_bmp_corrections`
when splicing a price panel. This design elevates DLRET to a first-class,
self-explaining quantity: one row per delisting event carrying the DLRET value,
the bucket/code/reason, and **every input that produced the DLRET, each as its own
column**.

Background and the verified methodology this builds on: see
[`docs/research/dlret-generation.md`](../../research/dlret-generation.md) (how CRSP
generates DLRET; the Shumway −30% / Shumway-Warther −55% / worthless −1
corrections; the 501/502 bug this spec fixes).

### Goals

- A new central type, `EnrichedDelistRecord`, = classification facts + DLRET + all
  DLRET inputs + the method that produced the DLRET. Every public API derives from
  it.
- `compute_dlret` becomes self-explaining: returns *which* rule fired and the
  terminal value, not just a float.
- Merger DLRET captures the **full consideration** (cash + stock leg) when terms
  are supplied; abstains (neutral) only when they are not.
- `output/dlret.csv` is the new headline output.
- Downstream consumers (firm-month BMP correction, train labels, backtest exits,
  qlib adapter) read the computed DLRET from the enriched record instead of
  recomputing it.
- Fix the 501/502 misbucketing surfaced by the research (positive up-migrations
  must not receive a negative Shumway shock).

### Non-goals (out of scope)

- **Goal-2 portfolio position transition.** The table targets realized-return
  *labeling* (Goal 1): `(1+RET)(1+DLRET)−1` embeds the full economics; we do not
  track acquirer shares through a merger or continue holding the successor.
- **Auto-extracting stock-leg merger terms from EDGAR** (exchange ratio, acquirer
  price). These remain externally provided inputs. The existing cash-only payout
  extractor is unchanged.
- **Sourcing prices from `qlib_practice`.** `last_trade_close`, `acquirer_price`,
  and `recovery_ratio` are provided as inputs to the new method, keeping it
  decoupled and offline-testable.
- A separate `−100%` upper-bound column. The upper bound is a stress test, not a
  point estimate; the table emits the single best-estimate DLRET plus its method.

## Architecture

The library keeps its two-layer split (classification / handling) but adds a
**central enriched record** that joins them and becomes the type every public API
operates on.

```
classification layer (network)              handling layer (pure)
  DelistRecord  ──────────►  enrich(record, *inputs)  ──►  EnrichedDelistRecord
  (ticker, cik, date,          + last_trade_close,            (+ dlret, dlret_method,
   crsp_code, bucket,            payout_per_share,              terminal_value,
   confidence, reason,          stock_ratio, acquirer_price,    dlret_confidence)
   evidence)                    acquirer_ticker,
                                recovery_ratio, exchange)
                                         │
        ┌────────────────────────────────┼───────────────────────────────┐
        ▼                                ▼                                ▼
  build_dlret_table              bmp_firm_month_return            build_train_label_adjustment
  → output/dlret.csv             (uses .dlret)                    build_backtest_exit
  (PRIMARY OUTPUT)                                                (use .dlret / .inputs)
```

### New module: `dlret.py` (the hub)

- **Move** `compute_dlret` out of `bmp_correction.py` into `dlret.py`.
  `bmp_correction.py` then imports it. This makes DLRET structurally central.
- Define `DlretMethod` (enum), `DlretResult` (dataclass), `EnrichedDelistRecord`
  (dataclass), `enrich(...)`, and `build_dlret_table(...)` here (or split the
  table builder into `reconstruction.py` — decided at planning).

## Core types

### `DlretMethod` (enum)

The branch taken, surfaced as the `dlret_method` column for full transparency:

| Method | Bucket / case | DLRET value | `terminal_value` |
|---|---|---|---|
| `CASH_ONLY` | merger, cash leg only (CRSP 233 / extracted cash) | `terminal/last_trade − 1` | `cash_per_share` |
| `CASH_PLUS_STOCK` | merger, cash + stock legs (e.g. AET→CVS) | `terminal/last_trade − 1` | `cash_per_share + stock_ratio × acquirer_price` |
| `STOCK_ONLY` | merger, stock leg only | `terminal/last_trade − 1` | `stock_ratio × acquirer_price` |
| `ABSTAIN_NO_CONSIDERATION` | merger, no terms available | `0.0` (neutral) | `None` |
| `NEEDS_LAST_TRADE` | merger, consideration known but no price supplied | `NaN` | `None` |
| `EXCHANGE_TRANSFER_ZERO` | exchange transfer **incl. 501/502** | `0.0` | `None` |
| `RECOVERY_RATIO` | liquidation w/ observed recovery | `recovery_ratio − 1` | `recovery_ratio × last_trade` |
| `SHUMWAY_NYSE_AMEX` | NYSE/AMEX performance delist | `−0.30` | `None` |
| `SHUMWAY_NASDAQ` | Nasdaq/OTC performance delist | `−0.55` | `None` |
| `WORTHLESS` | declared worthless | `−1.0` | `0.0` |
| `DROPPED_EXPIRATION` | expiration / 6xx | `NaN` (drop) | `None` |
| `UNKNOWN` | unclassified | `NaN` | `None` |

### `DlretResult` (dataclass)

```python
@dataclass(frozen=True)
class DlretResult:
    value: float            # may be NaN
    method: DlretMethod
    terminal_value: float | None
```

`compute_dlret(...)` returns this. `bmp_firm_month_return` uses `.value`; the
firm-month math is unchanged.

### `EnrichedDelistRecord` (dataclass)

```python
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
    evidence: dict | None              # mirrors DelistRecord.evidence
    # --- DLRET inputs (externally provided) ---
    exchange: Exchange
    last_trade_close: float | None
    payout_per_share: float | None     # cash leg
    stock_ratio: float | None          # exchange ratio
    acquirer_price: float | None       # acquirer price at completion
    acquirer_ticker: str | None        # provenance
    recovery_ratio: float | None
    # --- DLRET outputs ---
    dlret: float                       # may be NaN
    dlret_method: DlretMethod
    terminal_value: float | None
    dlret_confidence: str              # high | medium | low
    # --- provenance carried through ---
    payout_source: str | None
    payout_confidence: str | None
```

`DelistRecord` is unchanged and remains the classification hand-off.
`EnrichedDelistRecord` is built by `enrich(record, *, exchange, last_trade_close,
payout_per_share, stock_ratio, acquirer_price, acquirer_ticker, recovery_ratio)`.

### DLRET computation logic

Resolution order inside `compute_dlret(bucket, exchange, last_trade_close,
payout_per_share, stock_ratio, acquirer_price, recovery_ratio)`:

1. `EXPIRATION` → `DlretResult(NaN, DROPPED_EXPIRATION, None)`.
2. `EXCHANGE_TRANSFER` → `DlretResult(0.0, EXCHANGE_TRANSFER_ZERO, None)`.
3. `MERGER`:
   - Compute legs: `cash = payout_per_share`, `stock = stock_ratio ×
     acquirer_price` (only if both present).
   - `terminal = (cash or 0) + (stock or 0)` when at least one leg present; else
     `None`.
   - No terminal → `ABSTAIN_NO_CONSIDERATION`, value `0.0`.
   - Terminal present but `last_trade_close` missing/≤0 → `NEEDS_LAST_TRADE`,
     value `NaN`.
   - Otherwise value `= terminal/last_trade − 1`, method per which legs present
     (`CASH_ONLY` / `STOCK_ONLY` / `CASH_PLUS_STOCK`).
4. `LIQUIDATION`: `recovery_ratio` present → `RECOVERY_RATIO`, value
   `recovery_ratio − 1`; else exchange Shumway constant
   (`SHUMWAY_NYSE_AMEX`/`SHUMWAY_NASDAQ`). *(See open decision on the liquidation
   fallback.)*
5. `COMPLIANCE_FAILURE`: exchange Shumway constant.
6. `ACTIVE` / `UNKNOWN`: `DlretResult(NaN, UNKNOWN, None)`.

`WORTHLESS` (value `−1.0`) is reserved for records carrying *explicit* evidence of
worthlessness (e.g. SEC revocation, or a bankruptcy with confirmed zero recovery).
If no such signal is available, `COMPLIANCE_FAILURE` keeps the Shumway constant —
i.e. `WORTHLESS` is opt-in, never the default for the 5xx bucket. The concrete
signal that selects it is an open decision (see below).

`dlret_confidence` (heuristic): `high` for `CASH_ONLY` from a high-confidence
extracted payout and for `EXCHANGE_TRANSFER_ZERO`; `medium` for `CASH_PLUS_STOCK` /
`STOCK_ONLY` (depends on a supplied market price) and for Shumway constants;
`low` for `ABSTAIN_NO_CONSIDERATION` and `RECOVERY_RATIO` without corroboration.
Exact mapping finalized in the plan; it must never be `high` when `dlret` is `NaN`.

## The DLRET table (primary output)

`build_dlret_table(records, *, last_trade_closes, payouts, exchanges,
merger_terms, recovery_ratios) -> list[EnrichedDelistRecord]`, plus a CSV writer.
Column order (maps to the user's requested schema):

```
ticker | bucket | observed_delist_date | crsp_code | dlret | reason |
exchange | last_trade_close | payout_per_share | stock_ratio | acquirer_price |
acquirer_ticker | recovery_ratio | terminal_value | dlret_method |
dlret_confidence | payout_source
```

| User column | Table column |
|---|---|
| Ticker | `ticker` |
| Delist Type | `bucket` |
| Delist Date | `observed_delist_date` |
| Code | `crsp_code` |
| DLRET | `dlret` |
| Description | `reason` |
| Extra information (one col each) | `exchange`, `last_trade_close`, `payout_per_share`, `stock_ratio`, `acquirer_price`, `acquirer_ticker`, `recovery_ratio`, `terminal_value`, `dlret_method`, `dlret_confidence`, `payout_source` |

Written to **`output/dlret.csv`** — the new headline artifact. One row per
delisting event; the key is `(ticker, observed_delist_date)` to respect ticker
recycling. `dlret` is left blank/`NaN` (never silently `0`) when `dlret_method` is
`NEEDS_LAST_TRADE`, `DROPPED_EXPIRATION`, or `UNKNOWN`.

## Downstream refactor (everything derives from the hub)

- `handling.py` — `build_train_label_adjustment`, `build_backtest_exit` take an
  `EnrichedDelistRecord` and read its `dlret`/inputs rather than recomputing.
- `bmp_correction.py` — `bmp_firm_month_return` consumes the enriched record's
  `dlret`; `compute_dlret` now lives in `dlret.py` and is imported.
- `qlib_adapter.py` — builds `EnrichedDelistRecord`s from the classifications CSV +
  provided input maps, then applies. `apply_bmp_corrections`,
  `inject_terminal_labels`, `apply_backtest_exits` route through the enriched
  record.

The two return-correction conventions CLAUDE.md warns about (event-level vs
firm-month) are preserved: the enriched record's `dlret` is the event-level
quantity; `bmp_firm_month_return` is the firm-month transform of it. They are not
conflated — the firm-month function simply consumes `dlret`.

## Bug fix: 501/502 routing

`crsp_codes.bucket_for_code` currently sends all of `500–599` to
`COMPLIANCE_FAILURE` via the range fallthrough, so codes **501 (migrated to NYSE)**
and **502 (migrated to AMEX/NYSE MKT)** — positive up-migrations — would receive a
`SHUMWAY_NASDAQ` −55% shock. Fix:

- Map `501`, `502`, and the `503–519` "Another Exchange" sub-range to
  `EXCHANGE_TRANSFER` *before* the `5xx → COMPLIANCE_FAILURE` fallthrough.
- Correct the `crsp_codes.py` module docstring that wrongly states
  `COMPLIANCE_FAILURE … apply -100% terminal` (the code applies the Shumway
  constant, which is the defensible choice).

## Script & outputs

- Primary script emits `output/dlret.csv`. Either extend `scripts/classify_universe.py`
  to culminate in the table or add `scripts/build_dlret_table.py` (decided in the
  plan; extending the existing script is preferred so there is one headline run).
- New optional inputs (provided, decoupled): `--last-trade-closes`
  (`ticker,last_trade_close`), `--merger-terms`
  (`ticker,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker`),
  `--recoveries` (`ticker,recovery_ratio`). Exchange continues to come from the AV
  listing loader. Absent a price, merger rows get `dlret=NaN,
  dlret_method=NEEDS_LAST_TRADE`.
- `output/delist_classifications.csv` and `output/payouts.csv` may remain as
  intermediate artifacts; `output/dlret.csv` is the documented primary output.

## Docs updates

- **README.md** reframed around the DLRET table as the deliverable (schema, the
  per-bucket DLRET policy table, worked examples including a mixed cash+stock
  case).
- **CLAUDE.md** — update the architecture description (DLRET hub, the new module)
  and revise the "payout extraction is cash-only by design / mixed abstains"
  invariant to: *abstain only when no consideration terms are supplied; compute the
  full consideration (cash + stock leg) when they are. Auto-extraction remains
  cash-only.*

## Testing (offline only)

Reuse `FakeEdgar` + committed fixtures; never add network to the test path.

- `compute_dlret` / `DlretResult` per bucket and method, including:
  - `CASH_ONLY`, `CASH_PLUS_STOCK` (AET→CVS golden: cash 145, ratio 0.8378,
    acquirer 80, last 190 → ≈ +0.116), `STOCK_ONLY`, `ABSTAIN_NO_CONSIDERATION`,
    `NEEDS_LAST_TRADE`.
  - `EXCHANGE_TRANSFER_ZERO`, `RECOVERY_RATIO`, `SHUMWAY_NYSE_AMEX`,
    `SHUMWAY_NASDAQ`, `WORTHLESS`, `DROPPED_EXPIRATION`, `UNKNOWN`.
- `crsp_codes` 501/502/503–519 → `EXCHANGE_TRANSFER` (regression test for the bug).
- `build_dlret_table` column contract (exact header order) and `(ticker,
  observed_delist_date)` keying with a recycled ticker.
- Refactored consumers (`handling`, `bmp_correction`, `qlib_adapter`) read `dlret`
  from `EnrichedDelistRecord`; firm-month identity `(1+R_partial)(1+DLRET)−1`
  unchanged.
- Existing 122 tests stay green or are migrated where signatures change.

## Open decisions (confirm during planning)

1. **Type name.** `EnrichedDelistRecord` (chosen) vs the shorter `DlretRecord`.
2. **Module split.** Keep `enrich` + `build_dlret_table` in `dlret.py`, or split
   the table builder into `reconstruction.py`.
3. **Script shape.** Extend `classify_universe.py` (preferred) vs a new
   `build_dlret_table.py`.
4. **Liquidation fallback.** The research notes liquidations (400) are
   announced/pre-priced and *not* performance-biased, so a missing recovery is
   likely "distribution not captured," not a wipeout. Decide whether the
   no-recovery fallback stays the Shumway constant (current behavior) or becomes a
   milder/neutral default. Low-stakes; default to keeping current behavior unless
   the plan argues otherwise.
5. **`WORTHLESS` signal.** Which concrete classifier signal selects `−1.0` over the
   Shumway constant (e.g. SEC-revocation codes 580/585, or bankruptcy 574 with
   evidence of zero recovery). If none is wired, `WORTHLESS` stays unused in v1 and
   the 5xx bucket uses the Shumway constant throughout.

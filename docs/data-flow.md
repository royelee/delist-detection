# Data flow

How a ticker travels through `delist_detection`, from the Tiingo universe
file to a per-ticker classification with deterministic train and backtest
handling.

## Inputs

| Source | Path | Role |
|---|---|---|
| Tiingo universe | the consumer's instruments file (`ticker, start, end`) | List of `(ticker, start_date, end_date)`. A row with `end_date < today` is a delisting candidate. |
| Alpha Vantage delisted list | an Alpha Vantage LISTING_STATUS delisted CSV | Provides `(ticker, name, exchange, assetType, ipoDate, delistingDate)` — used as a CIK-resolution hint and asset-type signal. |
| Alpha Vantage active list | an Alpha Vantage LISTING_STATUS active CSV | Fallback when a Tiingo ticker is missing from the delisted CSV (recycled or rename cases). |
| SEC EDGAR | `data.sec.gov/submissions/CIK########.json` and `efts.sec.gov/LATEST/search-index` | Ground truth for filings (Form 25, 8-K item codes, Form 15). All output classifications derive from these. |

## Pipeline

```
                ┌─────────────────────────────┐
                │ tiingo/instruments/all.txt  │   1846 rows; 461 delisted
                └────────────┬────────────────┘
                             │ awk filter end<today
                             ▼
                ┌─────────────────────────────┐
                │ data/delisted_tickers.tsv   │   ticker / start / end
                └────────────┬────────────────┘
                             │ scripts/classify_universe.py
                             ▼
       ┌─────────────────────────────────────────────┐
       │            TickerResolver                   │   ticker → CIK
       │  1. manual_overrides          (curated)     │
       │  2. company_tickers.json      (active)      │
       │  3. EFTS Form-25 + date       (precise)     │
       │  4. AV name + EDGAR cgi-bin   (fallback)    │
       │  5. EFTS 8-K frequency rank   (last resort) │
       │     validate: Form 25/15 in window AND      │
       │     (strict) no 10-Q after delist+90d       │
       └────────────┬────────────────────────────────┘
                    │ resolution + observed_date
                    ▼
       ┌─────────────────────────────────────────────┐
       │            DelistClassifier                 │
       │  short-circuits, in order:                  │
       │    asset_type ∈ {ETF, note, warrant, …}    │   → 600 EXPIRATION
       │    Form 'REVOKED' present                   │   → 573 COMPLIANCE
       │    confirmed 1.03 bankruptcy                │   → 470 LIQUIDATION
       │    rename / listing transfer                │   → 304 EXCHANGE
       │    SPAC trust liquidation                   │   → 600 EXPIRATION
       │    10-K/Q filings >180d after delist        │   → 304 EXCHANGE
       │  fingerprint + default cascade:              │
       │    Form 25 + 8-K items + Form 15;            │
       │    a distress bucket always needs positive   │
       │    evidence (full trigger table below)       │
       └────────────┬────────────────────────────────┘
                    │ DelistRecord per ticker
                    ▼
       ┌─────────────────────────────────────────────┐
       │   output/delist_classifications.csv         │
       │   ticker, cik, observed_delist_date,        │
       │   crsp_code, bucket, confidence, reason,    │
       │   delist_filing_form/date, anchor_8k_items, │
       │   dereg_form, resolved_name, source         │
       └────────────┬────────────────────────────────┘
                    │ handling.py / qlib_adapter.py
        ┌───────────┴───────────┐
        ▼                       ▼
┌────────────────┐    ┌──────────────────────┐
│ Train pipeline │    │ Backtest pipeline    │
│  bucket policy │    │  bucket policy       │
│  → forward     │    │  → exit_date,        │
│    return      │    │    exit_price        │
│    label       │    │                      │
└────────────────┘    └──────────────────────┘
```

## Caching

Every EDGAR JSON response is SHA1-keyed and cached in `cache/edgar/*.json`.
A second run of `classify_universe.py` over the same set is near-instant
(~3 s for 461 tickers) because no network calls happen. To force a refresh,
delete the relevant cache files. Each payload records the day it was fetched
(`__fetched__`; an older file is dated by its mtime). The resolver's checks
and the classifier read a company's submissions fresh as of `min(observed +
45 days, today)` (`edgar.submissions_fresh_after`), so a copy cached before a
later Form 25 is fetched again.

The ticker→CIK memo lives at `cache/ticker_resolution.json` and is keyed by
`(ticker, observed_date)` so a recycled ticker resolves to the right
issuer per date. The file is versioned (`{"__version__": 2, "entries": …}`);
a file without version 2 predates the date and name checks, so it is
ignored and replaced on the next save. Each entry records the member name
it was checked with, and a lookup with a different member name resolves
again. Misses, and answers reached while an EDGAR request failed
transiently, are used for the run but never saved.

## Resolver strategy in detail

EDGAR's `company_tickers.json` only lists currently-registered issuers, so
it cannot map deregistered tickers. We layer increasingly looser strategies
until something hits, then validate that the candidate looks like a delist
target rather than an acquirer.

1. **`--cik-map`.** The caller's own per-(ticker, era) identity table,
   resolved once against EDGAR and reviewed by a human (`cik_map` param on
   `TickerResolver`). Beats every other tier, including the manual override.
   Never written to `cache/ticker_resolution.json`: it answers before the
   on-disk memo is even consulted, so persisting it would let a stale pin
   outlive the caller correcting or dropping the map — the resolver must
   forget it the moment `--cik-map` does.

2. **Manual override.** Hand-curated `MANUAL_OVERRIDES` in
   `scripts/classify_universe.py`. Wins over everything below it; used for
   short tickers where EFTS picks the wrong issuer (e.g. `AET → 1122304 Aetna`).

3. **company_tickers.json.** Master active-tickers map.

4. **EFTS Form-25/15 with date window.** Searches
   `efts.sec.gov/LATEST/search-index` restricted to Form 25, 25-NSE, 15-12G,
   15-12B, 15-15D within ±90 days of the observed delist date. Skips
   known exchange CIKs (Nasdaq 1354457, NYSE LLC 876661, Cboe BZX 1417835, …) and prefers hits
   whose display_name contains the literal `(TICKER)`.

5. **AV name + EDGAR cgi-bin company search.** Uses the company name from
   Alpha Vantage's delisted CSV, generates variants (full name, suffix-
   stripped, leading 1-3 tokens), and queries
   `www.sec.gov/cgi-bin/browse-edgar?company=…&type=…&output=atom`.
   Rejects when AV's delistingDate is >365 days from the observed date
   (signals a recycled ticker — the AV name is for the prior issuer).

6. **EFTS 8-K frequency rank.** Counts CIKs appearing in 8-Ks that mention
   the ticker in the 120 days before delisting. Validates each candidate
   in strict mode (must have Form 25/15 in window AND no 10-K/Q in the
   five years after `delist + 90d` — the latter rejects the acquirer).

## Classifier rules

`classify_ticker` runs a fixed sequence of checks and returns as soon as one
applies, in this order:

| Trigger | CRSP code | Bucket |
|---|---|---|
| AV `assetType` ∈ {ETF, note, warrant, unit, right} OR name ∈ {"… Notes Due", "… ETF", "… Rights"} | 600 | EXPIRATION |
| Form `REVOKED` present | 573 | COMPLIANCE_FAILURE |
| 8-K item 1.03 whose own Item 1.03 section reports a bankruptcy, searched 540 days before to 30 days after the delisting (an unreadable section still counts, flagged `bankruptcy_text_missing`). Exception: when that 1.03 is more than 180 days before the delisting and a change-in-control 8-K (5.01, or 2.01 with 3.01 or 3.03) falls within 30 days of the delisting, the merger path wins instead and the row is flagged `bankruptcy_before_merger` | 470 | LIQUIDATION |
| A rename near the delisting, or a 3.01 notice that reads as a listing transfer rather than a deficiency, with the company still reporting results afterward. Yields to the merger path whenever a nearby 8-K shows an acquisition (5.01, or 2.01 with 3.01 or 3.03) | 304 | EXCHANGE_TRANSFER |
| SPAC trust liquidation (blank-check company, redeemed at trust value) | 600 | EXPIRATION |
| 10-K / 10-Q / 20-F filed more than 180 days after the delisting | 304 | EXCHANGE_TRANSFER |
| None of the above: the 8-K item fingerprint decides, anchored on the Form 25 filing date when one exists (else the observed delist date). A Form 25 more than 45 days before the observed date is a frozen vendor tail, flagged `frozen_tail:<days>` | | |
| 8-K items 2.01 + 3.01 + 5.01 | 231 | MERGER |
| 8-K items 2.01 + 5.01 | 233 | MERGER |
| 8-K item 5.01 without 2.01, alongside 3.01 or 3.03 (a change in control with no completed-acquisition item) | 231 | MERGER |
| 8-K items 2.01 + 3.01 (no 5.01) | 200 | MERGER |
| 8-K items 2.04 + 3.01 | 470 | LIQUIDATION |
| No conclusive fingerprint, or 3.01 alone: the default cascade below decides, all of which needs positive evidence | | |
| 2.01 present on the anchor 8-K and a Form 15 deregistration on file | 233 | MERGER |
| SPAC with no Form 25/15 in the window | 600 | EXPIRATION |
| A 3.01 notice citing a listing deficiency | 570, or 580 with an NT 10-K/Q in the prior year | COMPLIANCE_FAILURE |
| A merger proxy or tender filing within 400 days of the anchor (120 days when the 3.01 notice text could not be fetched) | 231 | MERGER |
| An NT 10-K/Q in the prior year, with no deficiency notice and no merger evidence | 580 | COMPLIANCE_FAILURE |
| None of the above | unknown, flagged `no_evidence_default`, `deregistered` recorded | UNKNOWN |

A distress bucket (`compliance_failure`, `liquidation`) is never the silent
default: every row above that ends in 470, 570, or 580 read the evidence
that put it there. A deregistration with no merger or distress evidence
lands `unknown`, which `enrich()` (`reconstruction.py`) resolves to par
(`dlret = 0`, `assumed_par`) when a valid last close exists, rather than
compounding an unexplained gap into a fabricated return.

## Outputs

`output/dlret.csv`: the primary deliverable. One row per delisting event
with the reconstructed delisting return (`dlret`), the method that produced
it, confidence, and the full audit trail (last trade close, payout terms,
recovery ratio, `review_flags`). Columns are `DLRET_TABLE_COLUMNS` in
`reconstruction.py`.

`output/delist_classifications.csv`: one row per ticker with the CRSP
code, bucket, confidence (`high | medium | low | none`), human-readable
reason, the evidence chain (Form 25 date, 8-K items, Form 15 form name,
resolved company name, which resolver tier won), and the raw extracted
payout (`payout_per_share`, `payout_source`, `payout_confidence`) before
the last-close gate runs.

`output/payouts.csv`: per-merger cash payout after the last-close gate:
only a payout (or cash+stock/stock-only terms) that reconciles with the
target's last trade close is kept, so a row the gate drops is blank here
even though `delist_classifications.csv` still carries the raw extracted
value.

`output/review.csv`: every row whose `review_flags` is non-empty, with its
`cik` and anchor 8-K item set, for a human to triage. Written by
`scripts/classify_universe.py` alongside `dlret.csv`.

`output/web_verification.csv` — independent EDGAR cross-check produced by
`scripts/verify_against_web.py`. Verdicts:

| Verdict | Meaning |
|---|---|
| `OK` | AV name shares ≥1 four-char token with EDGAR name, delist forms present in window |
| `OK_recycled_ticker` | AV name doesn't match (ticker recycled) but EDGAR CIK has Form 25 within ±30d of observed |
| `no_cik` | Classification is `expiration` — by design no CIK is resolved |
| `WEAK_no_delist_form` | Classification is `exchange_transfer` — no Form 25 expected (company stayed on OTC) |
| `WEAK_no_form15` / `WEAK_no_3_01` | Bucket-specific evidence weaker than expected |
| `MISMATCH_name` | AV name shares zero tokens with EDGAR and no nearby Form 25 — needs human review |

## Downstream integration

The classification CSV is consumed by `delist_detection.qlib_adapter`:

- `inject_terminal_labels(panel, csv_path, horizon_days=21, …)` rewrites the
  last *horizon* observations of each delisted ticker so the supervised
  label matches the bucket policy (merger payout, compliance -100%, etc.).
  Eliminates the most common form of survivorship bias in walk-forward
  training.
- `apply_backtest_exits(positions_df, csv_path, …)` rewrites the exit-day
  price per delisted ticker to the bucket-specific exit policy. Stops the
  backtest from marking a compliance-failed position at the last OTC quote.

## Coverage

On the Tiingo 2026-05-22 universe (461 delisted tickers):

| Bucket | Count | % |
|---|---|---|
| merger | 346 | 75.1 |
| exchange_transfer | 45 | 9.8 |
| compliance_failure | 31 | 6.7 |
| liquidation | 22 | 4.8 |
| expiration | 17 | 3.7 |
| unknown | 0 | 0.0 |

Confidence: 85% high, 15% medium.
Web verification: 98.9% strong agreement (OK + OK_recycled + by-design weak).

# Data flow

How a ticker travels through `delist_detection`, from the Tiingo universe
file to a per-ticker classification with deterministic train and backtest
handling.

## Inputs

| Source | Path | Role |
|---|---|---|
| Tiingo universe | `fetch_data_aplha/data/tiingo_2026_05_22/instruments/all.txt` | List of `(ticker, start_date, end_date)`. A row with `end_date < today` is a delisting candidate. |
| Alpha Vantage delisted list | `fetch_data_aplha/data/alphavantage_listing_status/listing_status_delisted_2026-05-19.csv` | Provides `(ticker, name, exchange, assetType, ipoDate, delistingDate)` — used as a CIK-resolution hint and asset-type signal. |
| Alpha Vantage active list | `…/listing_status_active_2026-05-19.csv` | Fallback when a Tiingo ticker is missing from the delisted CSV (recycled or rename cases). |
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
       │  short-circuits:                            │
       │    asset_type ∈ {ETF, note, warrant, …}    │   → 600 EXPIRATION
       │    Form 'REVOKED' present                   │   → 573 COMPLIANCE
       │    10-K/Q filings >180d after delist        │   → 304 EXCHANGE
       │  fingerprint:                               │
       │    Form 25 + 8-K items + Form 15            │
       │  rules:                                     │
       │    2.01+3.01+5.01 → 231 MERGER              │
       │    2.01+5.01      → 233 MERGER              │
       │    1.03           → 470 BANKRUPTCY          │
       │    3.01 alone     → 570 COMPLIANCE          │
       │    + NT 10-K/Q    → 580 DELINQUENT          │
       │    Form 25+15, no M&A items → 400 LIQUIDATION│
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
delete the relevant cache files.

The ticker→CIK memo lives at `cache/ticker_resolution.json` and is keyed by
`(ticker, observed_date)` so a recycled ticker resolves to the right
issuer per date.

## Resolver strategy in detail

EDGAR's `company_tickers.json` only lists currently-registered issuers, so
it cannot map deregistered tickers. We layer increasingly looser strategies
until something hits, then validate that the candidate looks like a delist
target rather than an acquirer.

1. **Manual override.** Hand-curated `MANUAL_OVERRIDES` in
   `scripts/classify_universe.py`. Always wins; used for short tickers
   where EFTS picks the wrong issuer (e.g. `AET → 1122304 Aetna`).

2. **company_tickers.json.** Master active-tickers map.

3. **EFTS Form-25/15 with date window.** Searches
   `efts.sec.gov/LATEST/search-index` restricted to Form 25, 25-NSE, 15-12G,
   15-12B, 15-15D within ±90 days of the observed delist date. Skips
   known exchange CIKs (Nasdaq 1354457, NYSE 1067442, …) and prefers hits
   whose display_name contains the literal `(TICKER)`.

4. **AV name + EDGAR cgi-bin company search.** Uses the company name from
   Alpha Vantage's delisted CSV, generates variants (full name, suffix-
   stripped, leading 1-3 tokens), and queries
   `www.sec.gov/cgi-bin/browse-edgar?company=…&type=…&output=atom`.
   Rejects when AV's delistingDate is >365 days from the observed date
   (signals a recycled ticker — the AV name is for the prior issuer).

5. **EFTS 8-K frequency rank.** Counts CIKs appearing in 8-Ks that mention
   the ticker in the 120 days before delisting. Validates each candidate
   in strict mode (must have Form 25/15 in window AND no 10-K/Q in the
   five years after `delist + 90d` — the latter rejects the acquirer).

## Classifier rules

A `DelistRecord` is produced by a series of early-exit checks plus the
filing-trio fingerprint:

| Trigger | CRSP code | Bucket |
|---|---|---|
| AV `assetType` ∈ {ETF, note, warrant, unit, right} OR name ∈ {"… Notes Due", "… ETF", "… Rights"} | 600 | EXPIRATION |
| Form `REVOKED` present | 573 | COMPLIANCE_FAILURE |
| 10-K / 10-Q / 20-F filed >180 days after delist | 304 | EXCHANGE_TRANSFER |
| 8-K item 1.03 | 470 | LIQUIDATION |
| 8-K items 2.01 + 3.01 + 5.01 | 231 | MERGER |
| 8-K items 2.01 + 5.01 | 233 | MERGER |
| 8-K items 2.01 + 3.01 | 200 | MERGER |
| 8-K items 2.04 + 3.01 | 470 | LIQUIDATION |
| 8-K item 3.01 alone | 570 | COMPLIANCE_FAILURE |
| 570 + NT 10-K/Q in prior year | 580 | COMPLIANCE_FAILURE |
| Form 25 + Form 15, 8-K without M&A items | 400 | LIQUIDATION |
| Form 25 with no nearby 8-K, no Form 15 | 570 | COMPLIANCE_FAILURE (default) |

## Outputs

`output/delist_classifications.csv` — primary deliverable. One row per
ticker with the CRSP code, bucket, confidence (`high | medium | low | none`),
human-readable reason, and the evidence chain (Form 25 date, 8-K items,
Form 15 form name, resolved company name, which resolver tier won).

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

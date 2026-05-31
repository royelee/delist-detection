# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A sidecar for the `qlib_practice` Tiingo pipeline that makes a US-equity quant
universe survivorship-bias-aware. It reads a Tiingo-style instruments file
(`ticker, start, end`) and, for every delisted ticker, uses **only public SEC
EDGAR data** to classify *why* it stopped trading into a CRSP-style `DLSTCD`
code + bucket, then emits drop-in train-label and backtest-exit handlers. The
library is self-contained; point it at any `(ticker, start, end)` file.

Read `README.md` for the bucket policies, the CRSP code table, and worked
examples; `docs/data-flow.md` for the full classifier trigger table.

## Commands

```bash
conda activate rdagent4qlib              # project env — pytest, pandas/requests, and the editable install live here (base lacks them)
pip install -e .                         # editable install (Python ≥3.10) — once per env
pytest                                    # full suite (160 tests, offline, no network)
pytest tests/test_payout_extractor.py -v  # one file
pytest tests/test_payout_extractor.py::test_match_in_cash_family_altr -v   # one test

python scripts/verify_altair.py          # smoke: ALTR → CRSP 231, high
python scripts/classify_universe.py      # full universe → output/*.csv (NETWORK; ~2min cold, free when cached)
python scripts/classify_universe.py --limit 20 --no-extract-payouts   # fast dev subset
python scripts/verify_against_web.py     # independent EDGAR cross-check → output/web_verification.csv
python scripts/regen_payout_fixtures.py  # refetch golden 8-K fixtures from live SEC
python scripts/classify_universe.py --last-trade-closes ... --merger-terms ...   # full run incl. output/dlret.csv

# Manual verify (OFFLINE — drives the real CLI on cached tickers, no network) → inspect output/dlret.csv:
python scripts/classify_universe.py --limit 15 --last-trade-closes lt.csv --merger-terms terms.csv --recoveries rec.csv --dlret-output /tmp/dlret.csv
python scripts/compute_corrected_returns.py --panel panel.csv --classifications output/delist_classifications.csv --av-csv "$AV_LISTING_CSV" --payouts output/payouts.csv --out /tmp/corrected.csv   # firm-month BMP path
# override-CSV columns: lt.csv=`ticker,last_trade_close` · terms.csv=`ticker,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker` · rec.csv=`ticker,recovery_ratio` — each also accepts an optional `observed_delist_date` column for per-event (recycled-ticker) overrides
```

There is **no lint/format tooling** configured — do not invent a lint command.

## Architecture: two layers joined by `DelistRecord`

The codebase splits cleanly into a **classification layer** (network, EDGAR) and
a **handling layer** (pure, no network). The `DelistRecord` dataclass
(`classifier.py`) is the hand-off object between them: `ticker, cik,
observed_delist_date, crsp_code, bucket, confidence, reason, evidence`.

**Classification (network):**
- `edgar.py` — throttled, on-disk-cached SEC client. `submissions()`,
  `recent_filings()`, `fetch_filing_text()` (strips HTML, separate text cache).
- `ticker_resolver.py` — `(ticker, as_of_date) → CIK`, 5 strategies in order of
  precision (manual override → `company_tickers.json` → EFTS Form-25/15 →
  AV-name company search → 8-K frequency rank), each strict-validated.
- `av_listing.py` — Alpha Vantage `LISTING_STATUS` loader; provides issuer name
  + asset type as resolver fallback and validation signals.
- `classifier.py` — the filing-trio fingerprint (**Form 25 + 8-K item codes +
  Form 15**). `_classify_items()` maps an 8-K item set to a `DLSTCD` code; the
  surrounding logic handles asset-type short-circuits, exchange-transfer
  detection, and SEC-revocation.
- `crsp_codes.py` — the truth table: `DLST_CODE_TO_BUCKET` plus a leading-digit
  range fallthrough (`2xx→merger`, `3xx→exchange_transfer`, `4xx→liquidation`,
  `5xx→compliance_failure`, `6xx→expiration`). **The bucket — not the exact code
  — drives all downstream handling.**
- `payout_extractor.py` — bridges the layers: extracts the per-share **cash**
  merger consideration from EDGAR filing text (network) for the `merger` bucket.

**Handling (pure):**
- `handling.py` — event-level: `build_train_label_adjustment` (forward-return
  label) and `build_backtest_exit` (exit cashflow + universe-exit date), one
  deterministic policy per bucket.
- `bmp_correction.py` + `exchanges.py` — firm-month BMP 2007 correction:
  `R_month = (1+R_partial)(1+DLRET)−1`, synthesizing `DLRET` per bucket with
  exchange-specific Shumway constants when no realized delist return is observed.
- `dlret.py` — DLRET hub: `resolve_dlret`/`DlretResult`/`compute_dlret` (self-explaining delisting return). `bmp_correction.py` re-exports for backward compatibility.
- `reconstruction.py` — `EnrichedDelistRecord`, `enrich`, `build_dlret_table`, `write_dlret_csv`. `output/dlret.csv` is the **primary output**.
- `qlib_adapter.py` — DataFrame splicers over a `(datetime, instrument)` panel:
  `inject_terminal_labels`, `apply_backtest_exits`, `apply_bmp_corrections`.

There are **two return-correction APIs** for different research conventions:
event-level (`handling.py`) vs CRSP-style firm-month (`bmp_correction.py`). Don't
conflate them.

## Non-obvious invariants

- **SEC fair access.** `EdgarClient` throttles to 8 req/s and requires a
  descriptive `User-Agent`. Every response is cached under `cache/edgar/` (JSON)
  and `cache/edgar/text/` (stripped filing HTML), so re-runs cost nothing; these
  caches are gitignored and re-derivable. `WebFetch` is **403'd by SEC** — for
  ad-hoc EDGAR fetches use `curl -A "delist_detection/0.1 (royelee@users.noreply.github.com)"`.
- **Tests are fully offline.** They use a `FakeEdgar` fixture (`tests/conftest.py`)
  and committed text fixtures (`tests/fixtures/`); never add network to the test
  path. Golden fixtures are regenerated out-of-band by `scripts/regen_payout_fixtures.py`.
- **Ticker recycling** (e.g. ALTR was Altera then Altair) is handled by keying
  resolution on `(ticker, observed_date)` and by `MANUAL_OVERRIDES` in
  `scripts/classify_universe.py` (~35 ambiguous short tickers). When web
  verification proves a wrong CIK, extend that dict — don't patch the resolver.
- **Payout extraction is cash-only; the DLRET table supports full consideration.** Auto-extraction from EDGAR remains cash-only. The DLRET table abstains (neutral mark) only when no consideration terms are supplied; when stock-leg terms (`stock_ratio`, `acquirer_price`) are provided via `--merger-terms`, it computes the full cash+stock consideration (e.g. AET→CVS: $145 cash + 0.8378 CVS @ $80 = $212.02, DLRET = +11.6%). The `--last-trade-closes`, `--recoveries`, and `--merger-terms` CSVs accept an optional `observed_delist_date` column for per-event overrides (blank/absent = applies to all events of that ticker); exchange and payout maps are derived per delisting event automatically.
- **Validation is the EDGAR-cross-check loop**, not eyeballing: re-run
  `classify_universe.py`, then `verify_against_web.py` (and curl the cited
  accession) to confirm output against an independent path. Drill mismatches to
  root cause and re-run.
- **Hardcoded external paths.** `classify_universe.py` points `AV_LISTING_CSV` /
  `AV_ACTIVE_CSV` at absolute paths inside `../qlib_practice`; it reads
  `data/delisted_tickers.tsv` and writes `output/`. Output CSVs are committed
  artifacts.

## Design/plan docs

Specs and implementation plans live under `docs/superpowers/specs/` and
`docs/superpowers/plans/` (e.g. the BMP correction and payout-extraction
features). Follow that location for new feature design docs.

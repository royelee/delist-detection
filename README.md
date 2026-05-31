# delist_detection

Classify why every delisted ticker in a US-equity quant universe stopped
trading, using only public SEC EDGAR data, and emit drop-in handlers that
make supervised training and backtesting survivorship-bias-aware.

Built as a sidecar for the [`qlib_practice`](../qlib_practice) Tiingo
pipeline, but the library is self-contained — point it at any
`(ticker, start_date, end_date)` instruments file.

---

## Why

Quant pipelines typically receive a Tiingo-style universe file that says,
for a delisted ticker, *"trading ended on date X."* That single date hides
seven very different events that demand different label and exit policies:

| Event | Forward return at delist | If you ignore it |
|---|---|---|
| Cash acquisition (M&A 231) | `payout / last_close − 1` | Drop the row → labels biased toward survivors |
| Stock-for-stock merger (M&A 233) | ≈ 0 | Drop the row → same bias |
| Exchange transfer (304) | ≈ 0, ticker continues elsewhere | Treat as exit → fake liquidity event |
| Liquidation (400/470) | `recovery_ratio − 1` | Mark to last quote → overstate recovery |
| **Compliance failure (570/580)** | **−1.0 (−100%)** | Drop the row → silently strip the worst returns from training |
| SEC revocation (573) | −1.0 | Same as above |
| Expiration of warrant/note (600) | varies | Misclassify as equity event |

The classifier walks SEC EDGAR's filing trio (Form 25 → 8-K item codes →
Form 15) for each delisted CIK and assigns a CRSP-style code from these
buckets. Two pure functions then turn that code into a forward-return
label (training) and an exit cashflow (backtest).

---

## What you get

| Bucket               | CRSP DLSTCD   | Train forward-return label                | Backtest exit price             |
|----------------------|---------------|-------------------------------------------|--------------------------------|
| `active`             | 100           | —                                         | —                              |
| `merger`             | 200, 231, 233 | `payout / last_close − 1`                 | `payout`                       |
| `exchange_transfer`  | 300s          | drop, re-link to successor                | hold successor                 |
| `liquidation`        | 400, 470      | `recovery − 1` (default −90%)             | `recovery * last_close`        |
| `compliance_failure` | 570, 573, 580 | **−1.0**                                  | **0.0**                        |
| `expiration`         | 600           | drop (not equity universe)                | 0.0                            |

### CRSP DLSTCD codes

CRSP's delisting code (`DLSTCD`) is a three-digit number whose leading digit is
the category (1xx active, 2xx merger, 3xx exchange move, 4xx liquidation, 5xx
delisted-for-cause, 6xx other). The classifier assigns the specific codes below;
any other numeric code routes to a bucket by its leading digit (the range
fallthrough in [`crsp_codes.py`](src/delist_detection/crsp_codes.py), e.g. 560
penny-stock delist and 585 protection-of-investors → `compliance_failure`).

| Code | Bucket | Meaning | How this tool assigns it |
|------|--------|---------|--------------------------|
| 100 | `active` | Still trading; not delisted | Default for a live issue |
| 200 | `merger` | Acquired/merged, terms unspecified | 8-K items 2.01 + 3.01 |
| 231 | `merger` | Acquired by an **external** acquirer (cash/stock to holders) | 8-K items 2.01 + 3.01 + 5.01 |
| 233 | `merger` | Acquired by a **parent / via subsidiary buyback** | 8-K items 2.01 + 5.01 (no 3.01) |
| 241, 251, 252, 261, 262 | `merger` | Other CRSP merger sub-types (payment-form variants) | Range fallthrough (2xx) |
| 300–303 | `exchange_transfer` | Moved to a different exchange / market | Range fallthrough (3xx) |
| 304 | `exchange_transfer` | Dropped by the exchange but the issuer keeps filing (OTC continuation / spin-off) | Periodic 10-K/Q/20-F filed >180 days after the delist date |
| 400 | `liquidation` | Voluntary dissolution / deregistration | Form 25 + Form 15, no merger 8-K |
| 470 | `liquidation` | **Bankruptcy / receivership** | 8-K item 1.03, or items 2.04 + 3.01 |
| 570 | `compliance_failure` | Delisted by the exchange (price/standards), no M&A | 8-K item 3.01 alone, or Form 25 with no qualifying 8-K |
| 573 | `compliance_failure` | **SEC revocation** of registration | EDGAR form `REVOKED` present |
| 580 | `compliance_failure` | **Delinquent in filings** | A 570 case plus NT 10-K / NT 10-Q in the prior year |
| 600 | `expiration` | Scheduled end of a non-equity security (warrant, unit, right, ETF/ETN, note) | Asset type or name indicates a non-equity instrument |

For the full trigger table see [`docs/data-flow.md`](docs/data-flow.md).

**Worked examples** — two real cases per bucket (ALTR, ATVI, WYN, ATH,
RSH, MDR, AABA, CIE, GSF, TMUSR) with the actual corporate event, the
classification evidence, and concrete train/backtest mechanics:
[`docs/sample_delist_by_category.md`](docs/sample_delist_by_category.md).

---

## Primary output: the DLRET reconstruction table

The pipeline's primary deliverable is `output/dlret.csv` — a single CSV that
contains, for every delisted ticker, the reconstructed delisting return (DLRET)
and the full audit trail explaining how it was computed.

### Column schema

```
ticker, bucket, observed_delist_date, crsp_code, dlret, reason,
exchange, last_trade_close, payout_per_share, stock_ratio,
acquirer_price, acquirer_ticker, recovery_ratio, terminal_value,
dlret_method, dlret_confidence, payout_source
```

These columns come from `DLRET_TABLE_COLUMNS` in
[`reconstruction.py`](src/delist_detection/reconstruction.py). Each row is an
`EnrichedDelistRecord` produced by the `enrich` function, and the final table is
written by `build_dlret_table` / `write_dlret_csv`.

### Per-bucket DLRET policy

| Bucket | `dlret_method` | DLRET formula | When used |
|---|---|---|---|
| `merger` | `cash_only` | `payout / last_close − 1` | Pure-cash deal, both values known |
| `merger` | `cash_plus_stock` | `(cash + stock_ratio × acquirer_price) / last_close − 1` | Cash+stock deal, all terms supplied |
| `merger` | `stock_only` | `stock_ratio × acquirer_price / last_close − 1` | All-stock deal, terms supplied |
| `merger` | `abstain_no_consideration` | *(blank)* | No consideration terms available |
| `merger` | `needs_last_trade` | *(blank)* | Consideration known but `last_trade_close` missing |
| `exchange_transfer` | `exchange_transfer_zero` | `0` | Security continues at successor exchange |
| `liquidation` | `recovery_ratio` | `recovery_ratio − 1` | Recovery ratio supplied |
| `liquidation` | `shumway_nyse_amex` | `−0.30` | No recovery; NYSE/AMEX listing |
| `liquidation` | `shumway_nasdaq` | `−0.55` | No recovery; Nasdaq listing |
| `compliance_failure` | `worthless` | `−1.0` | Exchange kicked the ticker; equity is worthless |
| `expiration` | `dropped_expiration` | *(NaN — drop)* | Non-equity instrument (warrant, ETN, etc.) |
| *(any)* | `unknown` | *(blank)* | Unclassified ticker |

### Worked example: AET → CVS (cash + stock)

AET was acquired by CVS Health for **$145.00 cash + 0.8378 CVS shares** per AET
share. With CVS trading at $80.00 at close:

```
terminal_value = 145 + 0.8378 × 80 = 212.024
dlret           = 212.024 / 190 − 1 = +11.6%
```

where `190` is the last trade close of AET. The row would show
`dlret_method=cash_plus_stock`.

### CLI

```bash
python scripts/classify_universe.py \
    --last-trade-closes <csv> \
    --merger-terms <csv> \
    --recoveries <csv>
```

This runs the full pipeline and writes `output/dlret.csv`.

> **Note:** Merger rows without a supplied `last_trade_close` emit a **blank**
> `dlret` with `dlret_method=needs_last_trade` — they are never silently set to
> zero. This makes it explicit that a price input is missing and the return
> cannot be computed.

---

## Quickstart

```bash
pip install -e .
python scripts/verify_altair.py        # smoke test: ALTR → CRSP 231 high
python scripts/classify_universe.py    # full universe → output CSV
pytest -q                              # 62 unit tests, no network
```

End-to-end on the Tiingo 2026-05-22 universe (461 delisted tickers):

```
merger              346  (75.1%)
exchange_transfer    45  ( 9.8%)
compliance_failure   31  ( 6.7%)
liquidation          22  ( 4.8%)
expiration           17  ( 3.7%)
unknown               0  ( 0.0%)
```

The same run auto-extracts the per-share cash merger consideration for the
346 merger tickers into `output/payouts.csv` (see *Payout extraction* below):
232 extracted (197 `high`, 35 `medium`), every extracted value confirmed as
**cash-only** consideration, and zero pure-cash deals missed — the 114 misses
are all all-stock, mixed cash+stock, or cash-or-stock-election deals, for which
a neutral mark is the correct treatment (emitting only the cash leg of a
cash+stock deal would understate the return).

385/461 (85%) classifications are `high` confidence; the rest are `medium`.
Independent EDGAR-based web verification agrees on 98.9%.

---

## API

### Classification (network, EDGAR-backed)

```python
from delist_detection import EdgarClient, TickerResolver, DelistClassifier
from delist_detection.av_listing import AvListingLoader

edgar = EdgarClient(cache_dir="cache/edgar")
av = AvListingLoader("…/listing_status_delisted.csv",
                     active_csv_path="…/listing_status_active.csv")
resolver = TickerResolver(edgar, name_lookup=av.name,
                          cache_path="cache/ticker_resolution.json")
classifier = DelistClassifier(edgar, resolver,
                              asset_type_lookup=av.asset_type,
                              name_hint_lookup=av.name)

rec = classifier.classify_ticker("ALTR", observed_delist_date="2025-03-26")
# DelistRecord(cik=1701732, crsp_code=231, bucket=CrspBucket.MERGER,
#              confidence='high', reason='M&A 2.01+3.01+5.01 ...',
#              evidence={'delist_filing': ..., 'anchor_8k': ..., 'dereg_filing': ...})
```

### Handling (pure, no network)

```python
from delist_detection import (
    build_train_label_adjustment, build_backtest_exit, apply_to_panel,
)

train = build_train_label_adjustment(rec, last_close=111.85, payout_per_share=113.00)
# TrainLabelAdjustment(forward_return=0.0103, keep_in_training=True, ...)

exit_ = build_backtest_exit(rec, last_close=111.85, payout_per_share=113.00)
# BacktestExit(exit_date=date(2025,3,26), exit_price=113.00, ...)
```

### qlib panel integration

```python
from delist_detection.qlib_adapter import (
    inject_terminal_labels, apply_backtest_exits, load_classifications,
)

panel = inject_terminal_labels(
    panel,                                       # MultiIndex (datetime, instrument)
    "output/delist_classifications.csv",
    horizon_days=21, label_col="LABEL", close_col="close",
    payouts={"ALTR": 113.0}, successor_map={"WYN": "WH"},
)

positions = apply_backtest_exits(
    positions, "output/delist_classifications.csv",
    payouts=..., successor_map=...,
)
```

### Payout extraction (network, EDGAR-backed)

`merger`-bucket tickers need a per-share cash payout to turn the delist into a
forward-return label (`payout / last_close − 1`) and a backtest exit. Rather
than hand-curating `data/payouts.csv`, `classify_universe.py` extracts it
straight from EDGAR. For each merger ticker it walks a tiered chain of filings
and regex-matches the cash consideration:

| Tier | Source | Window vs delist | Confidence |
|---|---|---|---|
| 1 | 8-K Item 2.01 (deal close) | `[−120d, +30d]` | `high` |
| 2 | 8-K Item 1.01 (deal signed) | `[−365d, −7d]` | `medium` |
| 3 | DEFM14A (definitive proxy)  | `[−730d, +30d]` | `medium` |
| 4 | PREM14A (preliminary proxy) | `[−730d, +30d]` | `low` |

The operative signal of a *cash* payout is the phrase **"in cash"** — closing
8-Ks say *"converted into the right to receive $113.00 in cash, without
interest"* (not "$113.00 per share"). Bare `$X per share` / "purchase price"
phrasings are trusted only inside clean merger-event 8-Ks and only with an
"in cash" phrase adjacent; they are disabled for multi-page proxies, where the
same wording also covers dividends, DCF valuation ranges, implied stock value,
and mixed-consideration tables. Dividend / par-value / rounding / option and
convertible-note ("$X per $1,000 principal") figures are guarded out.

**Mixed cash+stock deals are out of scope and abstain (miss).** A cash+stock
deal (e.g. AET = `$145.00 in cash and 0.8378 CVS shares`, STJ, CAVM) states a
stock leg joined to the cash by "and"/"plus" with a share ratio. Emitting only
the cash leg would badly understate the return, so the extractor detects the
stock co-consideration and returns no value — including when a *later* filing
quotes an intermediate all-cash bid (PMCS) or a cash-election leg (SCS); the
authoritative closing 8-K settles the ticker as mixed. Contingent CVRs are
*not* treated as a stock leg, so a cash+CVR deal still yields its cash floor.

```python
from delist_detection import EdgarClient, PayoutExtractor

edgar = EdgarClient(cache_dir="cache/edgar")
extractor = PayoutExtractor(edgar)
res = extractor.extract(rec)        # rec: a MERGER-bucket DelistRecord
# PayoutResult(value=113.0, confidence='high', source='8K_2.01',
#              accession='0001193125-25-066329', quote='... $113.00 in cash ...')
```

`classify_universe.py` writes `output/payouts.csv`
(`ticker,payout_per_share,confidence,source,accession`) and appends
`payout_per_share`, `payout_source`, `payout_confidence` columns to
`output/delist_classifications.csv`. Pass `--no-extract-payouts` to skip the
step during classifier development. Feed the result to the corrected-returns
CLI with `--payouts output/payouts.csv`, or hand-override any row in
`data/payouts.csv`.

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

---

## Project layout

```
src/delist_detection/
    crsp_codes.py        CRSP DLSTCD → bucket mapping (the truth table)
    edgar.py             Throttled SEC EDGAR client with on-disk JSON cache
    av_listing.py        Alpha Vantage delisted/active CSV loader (name + asset type)
    ticker_resolver.py   5-tier ticker→CIK resolver with strict/loose validation
    classifier.py        Form-25 + 8-K-item + Form-15 fingerprint classifier
    handling.py          Pure train-label and backtest-exit per bucket
    exchanges.py         Listing-exchange normalization (NYSE/AMEX/NASDAQ/OTHER)
    bmp_correction.py    BMP 2007 firm-month return correction (Shumway constants)
    payout_extractor.py  Per-share cash merger consideration from EDGAR filings
    qlib_adapter.py      DataFrame adapters: inject_terminal_labels, apply_backtest_exits

scripts/
    verify_altair.py        End-to-end sanity check on ALTR (Siemens deal)
    classify_universe.py    Reads delisted_tickers.tsv → writes classifications.csv
    list_unknowns.py        Helper: list any unresolved tickers with AV name
    verify_against_web.py   Independent EDGAR cross-check (writes verification.csv)
    compute_corrected_returns.py  CLI: read panel + classifications → write BMP-corrected panel
    regen_payout_fixtures.py      Regenerate golden payout test fixtures from live SEC

data/
    delisted_tickers.tsv     Derived from Tiingo all.txt; ticker / start / end

output/
    delist_classifications.csv   Per-ticker classification with evidence (+ payout cols)
    payouts.csv                  Per-merger extracted payout with source + accession
    web_verification.csv         Per-ticker independent cross-check verdict

cache/
    edgar/*.json                 SEC JSON cache (re-runs are free)
    ticker_resolution.json       Ticker→CIK memo, keyed by (ticker, observed_date)

tests/                            Pytest suite with a FakeEdgar fixture
docs/
    data-flow.md                 End-to-end pipeline diagram and rules
```

For the full pipeline diagram and the rule table, see
[`docs/data-flow.md`](docs/data-flow.md).

---

## How the resolver picks the right CIK

Tickers get recycled (e.g. ALTR was Altera 1988–2015, then Altair 2017–
2025), and EDGAR's master ticker map only lists currently-registered
issuers. The resolver tries strategies in order of precision, then
validates the candidate looks like a delist *target* (not an *acquirer*):

1. **Manual override.** Hand-curated for ~35 short ambiguous tickers
   (`AET`, `X`, `MER`, `KLG`, …). Always wins.
2. **`company_tickers.json`.** Master active map.
3. **EFTS Form-25/15 within ±90 days.** Most precise; skips known
   exchange CIKs (Nasdaq, NYSE, …) automatically.
4. **AV name → EDGAR cgi-bin company search.** Generates name variants
   (suffix-stripped, leading 1-3 tokens) and queries the ATOM endpoint.
   Skips when AV's recorded delist date is >365 days from observed
   (signals a recycled ticker — AV's name is for the prior issuer).
5. **EFTS 8-K frequency rank.** Counts CIKs in 8-Ks mentioning the
   ticker in the 120 days pre-delist; strict-validates each candidate.

Validation: a candidate CIK is only accepted if it filed Form 25 or
Form 15 within ±540 days of the observed delist date. In strict mode
(used for frequency-rank candidates) it must additionally have no
10-K/Q/20-F in the window `[delist + 90d, delist + 5y]` — the target
stops periodic reporting; an acquirer does not.

---

## Verifying the output

`scripts/verify_against_web.py` does an independent EDGAR cross-check for
each classified row and emits a verdict in `output/web_verification.csv`.
On the Tiingo 2026-05-22 universe:

| Verdict | Count | What it means |
|---|---|---|
| `OK` | 405 | AV name matches EDGAR; delist forms present |
| `OK_recycled_ticker` | 18 | AV name stale (recycled), but EDGAR CIK has Form 25 within ±30d |
| `no_cik` | 17 | Classification is `expiration` — no CIK by design |
| `WEAK_no_delist_form` | 16 | Classification is `exchange_transfer` — no Form 25 expected |
| `WEAK_no_form15` / `WEAK_no_3_01` | 1 + 1 | Bucket-specific weaker evidence |
| `MISMATCH_name` | 3 | Tokenizer false positives (`RadioShack` ↔ `RS Legacy Corp` post-Ch.11 rename) |

98.9% strong agreement; the only true residue is the tokenizer's
inability to bridge a post-bankruptcy rename.

---

## Known limitations

* Short / common tickers (≤3 chars) can be ambiguous when multiple companies
  delisted in the same window. The fix is to add an entry to
  `MANUAL_OVERRIDES` in `scripts/classify_universe.py`.
* Form 25 doesn't always exist for pre-2002 delistings — those fall to the
  8-K-only path with `medium` confidence.
* SPAC-style ticker recycling (new IPO inheriting an old delisted ticker)
  needs the date-window to disambiguate; our `(ticker, observed_date)`
  cache keying handles this automatically.
* Spin-offs (e.g. `WYN` splitting into `WH` + `TNL` in 2018) classify as
  `exchange_transfer` because the parent legal entity continues filing —
  you may want to override the train/backtest policy for these manually.

---

## Data sources

* SEC EDGAR `submissions/CIK########.json` (~50–200 KB per company, cached)
* SEC EDGAR full-text search `efts.sec.gov/LATEST/search-index`
* SEC EDGAR company search `www.sec.gov/cgi-bin/browse-edgar?…&output=atom`
* SEC fair access: ≤10 req/s, descriptive `User-Agent` required. The
  client throttles to 8 req/s and is single-threaded.
* Alpha Vantage `LISTING_STATUS` CSVs (read locally; we do not call AV)

# delist_detection

Build a FIGI-keyed **security master** and a Form-25-driven **delisting
table** for a US-equity quant universe, using only public SEC data (EDGAR,
fails-to-deliver, MIDAS, the Nasdaq halt feed) and OpenFIGI, and emit
drop-in handlers that make supervised training and backtesting
survivorship-bias-aware.

The library is self-contained and universe-agnostic: it needs no price
vendor and no index membership list. You send it **observations** — "ticker
`T` was seen trading, as of date `D`" — for whatever securities you care
about, and it identifies each one, finds every delisting from SEC EDGAR,
classifies why it happened, and prices the delisting return. See
`CONTEXT.md` for the vocabulary (security, listing, delisting, observation,
pin, …) used throughout this document.

---

## Why

Quant pipelines typically receive a price-vendor universe file that says,
for a delisted ticker, *"trading ended on date X."* That single date hides
seven very different events that demand different label and exit policies —
and the vendor's own end date is often wrong to begin with (in one check,
it matched the true last trading day in only 14 of 45 cases):

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
| 231 | `merger` | Acquired by an **external** acquirer (cash/stock to holders) | 8-K items 2.01 + 3.01 + 5.01; item 5.01 without 2.01, alongside 3.01 or 3.03, as a change in control; or, with no fingerprint at all, a merger proxy/tender filing found within 400 days of the delisting |
| 233 | `merger` | Acquired by a **parent / via subsidiary buyback** | 8-K items 2.01 + 5.01 (no 3.01); or, with no fingerprint, item 2.01 on the anchor 8-K plus a Form 15 deregistration |
| 241, 251, 252, 261, 262 | `merger` | Other CRSP merger sub-types (payment-form variants) | Range fallthrough (2xx) |
| 300–303 | `exchange_transfer` | Moved to a different exchange / market | Range fallthrough (3xx) |
| 304 | `exchange_transfer` | Dropped by the exchange but the issuer keeps filing (OTC continuation / spin-off), or a rename / listing transfer while the company keeps reporting | Periodic 10-K/Q/20-F filed >180 days after the delist date; or a rename near the delisting, or a 3.01 notice that reads as a listing transfer |
| 470 | `liquidation` | **Bankruptcy / receivership** | 8-K item 1.03, or items 2.04 + 3.01 |
| 570 | `compliance_failure` | Delisted by the exchange (price/standards), no M&A | A 3.01 notice that cites a listing deficiency (positive evidence required; a bare 3.01 no longer defaults to compliance failure) |
| 573 | `compliance_failure` | **SEC revocation** of registration | EDGAR form `REVOKED` present |
| 580 | `compliance_failure` | **Delinquent in filings** | An NT 10-K / NT 10-Q filed in the prior year, alone or alongside a 570-qualifying deficiency notice |
| 600 | `expiration` | Scheduled end of a non-equity security (warrant, unit, right, ETF/ETN, note); or a SPAC trust liquidation | Asset type or name indicates a non-equity instrument; or a blank-check company redeeming its trust (no Form 25/15 M&A evidence) |

For the full trigger table see [`docs/data-flow.md`](docs/data-flow.md).

**Worked examples** — two real cases per bucket (ALTR, ATVI, WYN, ATH,
RSH, MDR, AABA, CIE, GSF, TMUSR) with the actual corporate event, the
classification evidence, and concrete train/backtest mechanics:
[`docs/sample_delist_by_category.md`](docs/sample_delist_by_category.md).

---

## The six output tables

`classify_universe.py` writes six CSVs to `output/`, all committed artifacts
(one row layout each, fixed column order, ISO dates, `;`-joined lists, empty
cell for NULL, rows sorted by key — see [`store.py`](src/delist_detection/store.py)
for the schema every table shares). `delistings.csv` is the primary
deliverable; the other five support it.

### `securities.csv` — key `sec_id`

One row per identified security.

```
sec_id, issuer_cik, share_class, name, security_type, observed, figi_source
```

`sec_id` is the US composite FIGI, or a placeholder `CIK<cik>-<CLASS>` when
none is confirmed. `figi_source` is how it was found: `pin`, `ticker`,
`cusip`, `name`, or `placeholder`. `observed` is `false` for a
successor/acquirer security added only to price a delisting, never itself
observed.

### `ticker_history.csv` — key `(sec_id, valid_from, ticker)`

Point-in-time ticker ranges.

```
sec_id, ticker, exchange, valid_from, valid_to, source
```

`valid_to` is empty for the still-open range. `exchange` is filled for the
range that ends in a delisting (from the Form 25) and for the still-open
range (from the issuer's current EDGAR submissions listing); a closed range
that is neither has an empty `exchange` (see the spec's Implementation
notes). `source` is `observation`, `ftd`, or `edgar_8k` — the last one for an
added successor security's ticker range (exchange-transfer continuations),
built directly from the 8-K that named it rather than from FTD sightings;
an added acquirer security's range still comes from `ftd`.

### `cusip_history.csv` — key `(sec_id, valid_from, cusip)`

Point-in-time CUSIP ranges, same shape as `ticker_history.csv`:

```
sec_id, cusip, valid_from, valid_to, source
```

Built from SEC fails-to-deliver rows and caller-supplied CUSIPs.

### `delistings.csv` — key `(sec_id, delist_date)` — the primary output

One row per delisting event, with the reconstructed delisting return (DLRET)
and the full audit trail explaining how it was computed. There are no
`active` rows — a security with no delisting simply has no row here.

```
sec_id, delist_date, ticker, cik, bucket, crsp_code, confidence, reason,
exchange, last_trade_date, last_trade_close, successor_sec_id, acquirer_sec_id,
acquirer_ticker, payout_per_share, stock_ratio, acquirer_price, recovery_ratio,
terminal_value, dlret, dlret_method, dlret_confidence, payout_source,
delist_filing_form, delist_filing_date, delist_filing_accession, anchor_8k_items,
dereg_form, resolved_name, resolution_source, last_trade_date_source,
raw_payout_per_share, raw_payout_source, raw_payout_confidence, review_flags
```

These are `DELISTINGS_COLUMNS` in [`store.py`](src/delist_detection/store.py).
Each row is an `EnrichedDelistRecord` produced by `enrich`, and the table is
built by `build_delistings_table` / `delisting_row` in
[`reconstruction.py`](src/delist_detection/reconstruction.py). `delist_date`
is the Form 25 filing date plus 10 days (Rule 12d2-2(d)(1)), or the date of
the fallback filing that ended trading when no Form 25 exists.
`raw_payout_*` is the extraction before the last-close gate (see *Payout
reconciliation* below); `last_trade_date_source` is `ex99_notice`, `8k_301`,
`midas`, `nasdaq_halt`, or empty. `resolution_source` records the resolver
tier that found the security's CIK (`cik_map` for an observation's `cik` pin,
`manual`, `company_tickers`, `efts`, `name_search`, …), taken from the
security's latest era that has a CIK (`security_master` when none has one);
`SecurityContext.resolution_source` → `classify_event(resolution_source=...)`
carry it to the row. A `company_tickers` resolution also sets the
`resolved_by_current_ticker_map` flag (see the flags table below).

### `payouts.csv` — key `(sec_id, delist_date)`

Per-merger cash payout after the last-close gate.

```
sec_id, delist_date, ticker, payout_per_share, confidence, source, accession
```

### `review.csv` — key `(sec_id, delist_date, ticker, review_flags)`

Every row that needs a human look: a delisting whose `review_flags` is
non-empty, plus securities with no delisting at all (`ended_without_delisting`,
`listing_status_unknown`, `form25_unmatched`, `form25_unclassified`,
`form25_unreadable`, `observation_unresolved`, `error`), ticker_history
consistency checks (`ticker_range_overlap`, `ticker_shared`), and
observation checks: `observation_conflict:<date>` (one row per ticker seen
under two names on one date, `sec_id` empty) and `ticker_unconfirmed` (an
era whose ticker no SEC fails-to-deliver row shows).

```
sec_id, delist_date, ticker, cik, bucket, dlret, review_flags, reason, anchor_8k, last_seen
```

### Per-bucket DLRET policy

| Bucket | `dlret_method` | DLRET formula | When used |
|---|---|---|---|
| `merger` | `cash_only` | `payout / last_close − 1` | Pure-cash deal, both values known |
| `merger` | `cash_plus_stock` | `(cash + stock_ratio × acquirer_price) / last_close − 1` | Cash+stock deal, all terms supplied |
| `merger` | `stock_only` | `stock_ratio × acquirer_price / last_close − 1` | All-stock deal, terms supplied |
| `merger` / `expiration` | `assumed_par` | `0` (terminal = `last_trade_close`) | Completed deal / fund closure with a known last price but no priceable consideration — terminal ≈ last price, so DLRET ≈ 0; **`low` confidence** |
| `merger` | `needs_last_trade` | *(blank)* | Consideration known but `last_trade_close` missing (no denominator) |
| `merger` | `abstain_no_consideration` | *(blank)* | No consideration **and** no last price |
| `exchange_transfer` | `exchange_transfer_zero` | `0` | Security continues at successor exchange |
| `liquidation` | `recovery_ratio` | `recovery_ratio − 1` | Recovery ratio supplied |
| `liquidation` | `shumway_nyse_amex` | `−0.30` | No recovery; NYSE/AMEX listing |
| `liquidation` | `shumway_nasdaq` | `−0.55` | No recovery; Nasdaq listing |
| `compliance_failure` | `worthless` | `−1.0` | Exchange kicked the ticker; equity is worthless |
| `expiration` | `dropped_expiration` | *(blank)* | Non-equity instrument with no last price |
| *(any)* | `unknown` | *(blank)* | Unclassified ticker |

> **No empty, no silent zero.** Any merger or fund closure with a valid
> `last_trade_close` but no priceable consideration is filled with `dlret = 0`
> tagged `dlret_method = assumed_par` at **`low`** confidence — a completed deal's
> last price already reflects its terminal value (≈0 incremental return), so 0 is
> the maximum-likelihood estimate, not a missing value. Rows are blank only when
> there is genuinely no denominator (no `last_trade_close`). Filter on
> `dlret_confidence` to keep, down-weight, or drop the estimates.

### Review surface

Not every row is settled by clean evidence. `enrich()` collects every
classifier and payout-gate flag into a `review_flags` column on
`delistings.csv` (semicolon-joined), and `classify_universe.py` also writes
`output/review.csv`, one row per non-empty `review_flags` value (plus rows
for securities with no delisting at all — see *The six output tables*
above), with the ticker, bucket, `dlret`, reason, `cik`, and anchor 8-K item
set, so a human can triage without re-deriving which rows the automatic
rules could not settle on their own.

The full flag vocabulary (from `classifier.py`, `ticker_resolver.py`,
`delistings.py`, `payout_gate.py`, and `reconstruction.py`):

| Flag | Meaning |
|---|---|
| `frozen_tail:<days>` | The delisting's anchor date (last trade date, or the Form 25 filing date when no last trade is known) is more than 45 days from the matched Form 25's own filing date |
| `member_name_mismatch` | The resolved CIK's EDGAR name disagrees with the observation's `name` |
| `resolved_by_current_ticker_map` | Resolved through `company_tickers.json` (today's holder of the ticker) |
| `resolved_by_manual_override` | Resolved through `MANUAL_OVERRIDES`, and the name still disagrees |
| `resolved_by_cik_map` | Resolved through the observation's `cik` pin, and the name still disagrees |
| `bankruptcy_tag_unconfirmed` | An 8-K carried the 1.03 tag, but its own Item 1.03 section did not confirm a bankruptcy |
| `bankruptcy_text_missing` | The 1.03 filing's text could not be fetched, so the tag was kept unconfirmed |
| `bankruptcy_before_merger` | A confirmed bankruptcy predates the delisting by more than 180 days and a change-in-control 8-K sits near the delisting; the merger path decided instead |
| `spac` | Classified as a SPAC trust liquidation |
| `no_evidence_default` | No merger or distress evidence found; classified unknown |
| `notice_text_missing` | The 3.01 notice's text could not be fetched |
| `payout_gate_failed:<value>` | The regex-extracted cash payout (`<value>`) did not reconcile with the last trade close |
| `terms_gate_failed:<reason>` | The LLM cash+stock/stock-only terms did not reconcile (`no_acq_ticker`, `no_acq_price`, `no_last_close`, or `fail_sanity`) |
| `llm_gate_failed` | The LLM cash or election terms did not reconcile either |
| `no_last_close` | No last trade close was found (SEC fails-to-deliver, or `--last-trade-closes`), so the payout could not be checked |
| `merger_at_par` | A merger whose consideration was never found; DLRET assumed 0 from the last close |
| `submissions_stale` | A refetch of the company's EDGAR submissions failed; a cached copy was used instead |
| `distress_at_normal_price` | A compliance-failure or liquidation row whose last trade close was still ≥ $5 |
| `no_form25` | No Form 25 was found; the classifier's fallback path (8-K completion, Form 15, `REVOKED`, SPAC trust liquidation) found and dated the delisting |
| `delist_date_approx` | The fallback delisting date is the security's last sighting, not a filing date (see *Where each date and price comes from* below) |
| `observed_after_delisting` | The delisting's Form 25 was filed before the security's first observation, and no fails-to-deliver row under its own tickers shows it trading after that: the observations that follow are stale (a snapshot kept listing A.G. Edwards, acquired 2007-10-01, through 2009) |
| `successor_unknown` | An exchange-transfer delisting whose successor security could not be found. Before the successor issuer's 8-K12B is searched, a security of the run whose first sighting falls within [last trade − 5 d, last trade + 15 d] and that shares the issuer CIK or the ticker is taken when it is the only one (a holdco reorganization's new line, a rename's new FIGI); the reason then ends "successor by same issuer" / "successor by same ticker" |
| `last_trade_date_conflict` | The Form 25 notice / 8-K text and the MIDAS/Nasdaq-halt confirmation disagree on the last trade date |
| `last_trade_date_unconfirmed` | The last trade date comes from unconfirmed filing wording only, with no MIDAS/halt confirmation |
| `no_last_trade_date` | No source (notice, 8-K, MIDAS, halt) yielded a last trade date at all |
| `ftd_close_lagged` | The last-trade close is from a fails-to-deliver row more than one trading day after the last trade (no row on the next day) |
| `ftd_close_prior:<n>` | No fails-to-deliver row follows the last trade day (fails stop once trading stops), so the close is the latest one known on it: the price on a row dated the last trade day or up to 10 trading days earlier, which is the close of the trading day before that row. `<n>` is that close's age in trading days before the last trade (1 = the day before); the row's date is kept in the evidence (`ftd_close_row_date`) |
| `acquirer_close_lagged` | The acquirer price used in the merger's cash+stock / stock-only terms is from a fails-to-deliver row more than one trading day after the target's last trade |
| `ended_without_delisting` | Not listed today and no Form 25 or fallback delisting filing was found |
| `listing_status_unknown` | Listing status could not be confirmed and no delisting was found |
| `no_figi`, `observation_unresolved` | FIGI resolution fell back to a placeholder, or (with no CIK either) could not resolve at all |
| `form25_unmatched`, `form25_unclassified`, `form25_unreadable` | A Form 25 could not be matched to one security's class, its class text was unreadable, or its filing text could not be fetched |
| `error` | An unexpected exception processing one security; logged and skipped rather than aborting the run |
| `ticker_range_overlap` | Two of one security's own `ticker_history` ranges overlap |
| `ticker_shared` | The same ticker maps to two different securities on the same day |
| `observation_conflict:<date>` | The ticker was observed under two or more different names on `<date>` (a snapshot source that backfilled today's ticker: CB is both ACE LTD and CHUBB CORP in 2012-2014); both are kept, and the reason names each with the security it resolved to. `sec_id` is empty |
| `ticker_unconfirmed` | An era from 2004 on with no fails-to-deliver row under its ticker within 30 days of its first and last observation: the SEC data never shows that ticker then (a snapshot carrying a later ticker, such as APTV in 2012-2013, or a security gone before the snapshot date) |

### Payout reconciliation (the last-close gate)

Every merger payout, the regex cash figure or the LLM cash+stock terms, is
checked against the target's last trade close before it reaches
`payouts.csv` or `delistings.csv`. A completed deal trades at its
consideration, so a payout far from the last close is a misread, never a
return. `payout_gate.reconcile` does the check (default tolerance 15%,
`--merger-terms-sanity-tol`):

- Mixed or ambiguous consideration abstains: the row lands at par instead
  of shipping a partial or guessed value.
- When the regex cash value doesn't fit but an LLM-extracted cash figure
  does, the LLM value is taken instead.
- A cash-or-stock election resolves to whichever leg, cash or
  `stock_ratio x acquirer_price`, is closer to the last close.
- A value that fits neither leg, or has no last close to check against, is
  dropped and the row is flagged for review instead of shipped as a
  misread return.

### Worked example: AET → CVS (cash + stock)

AET was acquired by CVS Health for **$145.00 cash + 0.8378 CVS shares** per AET
share. With CVS trading at $80.27 on AET's last trading day:

```
terminal_value = 145 + 0.8378 × 80.27 = 212.25
dlret           = 212.25 / 212.70 − 1 = −0.21%
```

where `212.70` is AET's **last trade close** — not its pre-deal price. For a
*completed* merger the price has already converged to the deal value by the last
trade, so `dlret ≈ 0`: the ~11% acquisition premium was earned over the months
between announcement and close and lives in the ordinary `RET` of those months,
**not** in DLRET (putting it in both would double-count it). The row shows
`dlret_method=cash_plus_stock`.

### CLI

```bash
python scripts/classify_universe.py \
    --observations obs.csv \
    --last-trade-closes <csv> \
    --merger-terms <csv> \
    --recoveries <csv>
```

This runs the full pipeline and writes `output/securities.csv`,
`ticker_history.csv`, `cusip_history.csv`, `delistings.csv`, `payouts.csv`
and `review.csv`. See *Observations and pins* below for the required
`--observations` input.

> **Note:** Merger rows without a `last_trade_close` (SEC fails-to-deliver
> found none, and none was supplied via `--last-trade-closes`) emit a
> **blank** `dlret` with `dlret_method=needs_last_trade` — they are never
> silently set to zero. This makes it explicit that a price input is missing
> and the return cannot be computed.

> **Recycled tickers:** The `--last-trade-closes`, `--recoveries`, and
> `--merger-terms` CSVs are keyed by `sec_id` and accept an optional
> `delist_date` column. When a row's date is non-blank it overrides only that
> specific delisting event (e.g. Altera's and Altair's `ALTR` delistings each
> get their own `sec_id`, so no date is even needed to tell them apart); a
> blank or absent date applies to every delisting of that `sec_id`. A row
> matching no delisting stops the run. Exchange and payout maps are derived
> per delisting event automatically — no special casing needed for recycled
> tickers, since a recycled ticker is two different securities to begin with.

---

## Using DLRET to build training labels and backtests

`output/delistings.csv` gives you one number per delisting — `dlret`, the
return from a security's **last trade** to its **terminal value** (cash
received, stock received, liquidation recovery, or zero). Splicing that one
number into the delisting period is what makes both supervised labels and
backtest P&L survivorship-bias-aware. Key the table on `(sec_id,
delist_date)`; `dlret_confidence` tells you how far to trust each value.

### The two formulas

Both uses reduce to the same primitive — **a held position earns `DLRET` over the
delisting step**, on top of whatever partial return `RET` your pipeline already
computes up to the last trade:

| Use | Formula | Why it removes the bias |
|---|---|---|
| **Training label** (delisting period) | `label = (1 + RET) × (1 + DLRET) − 1` | An acquired name carries its merger premium and a compliance-failure name carries its −100% into the label, instead of the row being dropped — dropping silently biases labels toward survivors. |
| **Backtest exit** (delist date) | `exit_price = last_trade_close × (1 + DLRET)` (= the `terminal_value` column) | The position exits at the real delisting cashflow, instead of marking to the last quote (overstates) or force-selling at 0 (understates). Remove the instrument from the universe after `delist_date`. |

### Recipe (pandas, straight off `delistings.csv`)

```python
import pandas as pd

dl = pd.read_csv("output/delistings.csv", parse_dates=["delist_date"])

# --- Training labels: compound RET with DLRET at each security's delisting row ---
# `panel` is your MultiIndex (date, instrument) frame with a forward return RET,
# where `instrument` is the sec_id (join ticker_history.csv first if your panel
# is still ticker-keyed). Align delist_date to your panel's frequency first
# (month-end for a monthly panel; the trade date itself for a daily panel).
dlret = dl.set_index(["sec_id", "delist_date"])["dlret"]
panel["DLRET"] = panel.index.to_frame().apply(
    lambda r: dlret.get((r["instrument"], r["date"]), 0.0), axis=1   # 0 off delisting rows
)
panel["LABEL"] = (1 + panel["RET"].fillna(0)) * (1 + panel["DLRET"].fillna(0)) - 1

# --- Backtest exits: sell at terminal_value on the delist date, then drop ---
exits = dl.assign(
    exit_price=dl["terminal_value"].fillna(dl["last_trade_close"])    # = last_close×(1+dlret)
)[["sec_id", "delist_date", "exit_price", "dlret_method"]]
# exchange_transfer rows: don't exit — re-link the position to successor_sec_id.
```

### Trust the value with `dlret_confidence`

| confidence | what it is | suggested use |
|---|---|---|
| `high` | exact cash payout from a closing 8-K (`cash_only`), or an exchange transfer (`exchange_transfer_zero`) | use as-is |
| `medium` | reconstructed cash+stock / all-stock terminal, or a Shumway/recovery mark | use as-is; spot-check large \|dlret\| |
| `low` | `assumed_par` neutral estimate (completed deal / fund closure, terminal assumed = last price → DLRET ≈ 0) | down-weight, or exclude from training and treat the row as a drop |

Because the table is never blank and never *silently* zero, both `DLRET.fillna(0)`
(use the par estimates) and "drop where `dlret_confidence == 'low'`" (ignore them)
are one-liners — the choice is yours and stays explicit.

### Per-bucket intuition (what a long position experiences)

| Delisting | `dlret` | Effect on the label / exit |
|---|---|---|
| Cash merger at a premium | `payout/last_close − 1` > 0 | positive terminal return — kept, not dropped |
| Completed stock / cash+stock merger | ≈ 0 | premium already earned pre-close; no extra shock |
| Exchange transfer | 0 | continues at successor; re-link, don't exit |
| Liquidation | `recovery − 1`, else Shumway −0.30 / −0.55 | partial loss |
| Compliance failure / SEC revocation | −1.0 | total loss — the correction that matters most |

> **Programmatic alternative.** If you prefer typed helpers over the CSV, the
> same math is available per-event from `build_train_label_adjustment` /
> `build_backtest_exit` (see *API → Handling*), and the CRSP-style firm-month
> form from `apply_bmp_corrections` (see *BMP 2007 firm-month return correction*).
> `delistings.csv` is the precomputed, audit-trailed output of those paths.

---

## Quickstart

```bash
pip install -e .
python scripts/verify_altair.py          # smoke test: ALTR → CRSP 231 high

# Build an observations CSV, then run the pipeline:
python scripts/observations_from_instruments.py --instruments data/delisted_tickers.tsv --out obs.csv
# or: scripts/observations_from_snapshots.py --dir <folder of dated index-membership CSVs> --out obs.csv
python scripts/classify_universe.py --observations obs.csv   # → output/{securities,ticker_history,cusip_history,delistings,payouts,review}.csv

pytest -q                                # 984 unit tests, no network
```

`classify_universe.py` prints a summary when it finishes: rows written per
table, delistings by bucket, `securities.csv` FIGI sources (`pin` / `ticker` /
`cusip` / `name` / `placeholder`), and `review.csv` flag counts — the first
place to look for how well a run went. `output/review.csv` is the
triage list; see *Verifying the output* below for the independent
EDGAR cross-check.

The same run auto-extracts the per-share cash merger consideration for every
`merger`-bucket delisting into `output/payouts.csv` (see *Payout extraction*
below); pass `--no-extract-payouts` to skip it during classifier development.

---

## API

### The end-to-end pipeline (network: EDGAR, SEC data files, OpenFIGI)

```python
from pathlib import Path
from delist_detection.observations import ObservationIndex, load_observations
from delist_detection.pipeline import Overrides, default_clients, run

index = ObservationIndex(load_observations("obs.csv"))
clients = default_clients(index, cache_dir=Path("cache"))
summary = run(index, clients, Overrides(), out_dir=Path("output"))
# RunSummary(counts={'securities': ..., 'delistings': ...}, buckets={'merger': ...}, ...)
```

`default_clients` wires up `EdgarClient`, `TickerResolver`, `DelistClassifier`,
`OpenFigiClient`, `FtdClient`, `MidasClient`, `NasdaqHaltClient` and the
payout extractors; `run()` is what `classify_universe.py` calls.

### Classifying one delisting directly (network, EDGAR-backed)

For a security whose issuer CIK you already know, the lower-level classifier
API from before still works — it's what `scripts/verify_altair.py` uses as a
standalone smoke test:

```python
from delist_detection import EdgarClient, TickerResolver, DelistClassifier
from delist_detection.crsp_codes import CrspBucket

edgar = EdgarClient(cache_dir="cache/edgar")
resolver = TickerResolver(edgar, cache_path="cache/ticker_resolution.json")
classifier = DelistClassifier(edgar, resolver)

rec = classifier.classify_ticker("ALTR", observed_delist_date="2025-03-26")
# DelistRecord(cik=1701732, crsp_code=231, bucket=CrspBucket.MERGER,
#              confidence='high', reason='M&A 2.01+3.01+5.01 ...',
#              evidence={'delist_filing': ..., 'anchor_8k': ..., 'dereg_filing': ...})
```

### Handling (pure, no network)

```python
from delist_detection import build_train_label_adjustment, build_backtest_exit

train = build_train_label_adjustment(rec, last_close=111.85, payout_per_share=113.00)
# TrainLabelAdjustment(forward_return=0.0103, keep_in_training=True, ...)

exit_ = build_backtest_exit(rec, last_close=111.85, payout_per_share=113.00)
# BacktestExit(exit_date=date(2025,3,26), exit_price=113.00, ...)
```

### qlib panel integration

The panel-level adapters read every DLRET input straight off the matching
`delistings.csv` row — no more ticker-keyed `payouts=`/`successor_map=`/
`exchanges=` dictionaries to assemble by hand. All three splicers
(`inject_terminal_labels`, `apply_backtest_exits`, `apply_bmp_corrections`) —
and `handling.adjustments_from_rows` — skip a row whose `successor_sec_id`
equals its own `sec_id`: that's a continuing security (it kept trading under
the same FIGI, e.g. an exchange transfer that didn't relist under a new
identity), not an exit, so no label/exit/correction is emitted for it.

```python
from delist_detection.qlib_adapter import inject_terminal_labels, apply_backtest_exits

panel = inject_terminal_labels(
    panel,                                       # MultiIndex (datetime, instrument); instrument = sec_id
    "output/delistings.csv",
    horizon_days=21, label_col="LABEL", close_col="close",
)

positions = apply_backtest_exits(positions, "output/delistings.csv")
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
(`sec_id,delist_date,ticker,payout_per_share,confidence,source,accession`,
gated by the last-close check above) and the raw, ungated extraction into
`delistings.csv`'s `raw_payout_per_share` / `raw_payout_source` /
`raw_payout_confidence` columns. Pass `--no-extract-payouts` to skip the step
during classifier development.

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

# Panel-level API: splice corrected R_month into a monthly (date, sec_id) panel,
# reading exchange/payout/last_trade_close straight off delistings.csv
corrected_panel = apply_bmp_corrections(
    monthly_panel,
    "output/delistings.csv",
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

CLI for batch correction of a monthly panel keyed by `sec_id`:

```bash
python scripts/compute_corrected_returns.py \
    --panel data/monthly_panel.parquet \
    --delistings output/delistings.csv \
    --out output/corrected_monthly_panel.parquet
```

---

## Project layout

```
src/delist_detection/
    observations.py      Observation, TickerEra, ObservationIndex — splits sightings into eras
    store.py              Output-table schemas (columns, key, sort), atomic CSV write/read
    trading_calendar.py   NYSE trading-day calendar
    sec_http.py           Throttled, cached downloads shared by ftd.py / midas.py
    edgar.py              Throttled SEC EDGAR client with on-disk JSON cache
    prefetch.py           warm(): fills the SEC caches on fill-only threads ahead of each sequential stage
    manifest.py           run_manifest.json: run date, code version, workers, SEC traffic, degraded answers
    ftd.py                SEC fails-to-deliver rows: last-trade closes, CUSIP history
    midas.py               SEC MIDAS per-security exchange volume: last-trade confirmation
    nasdaq_halts.py        Nasdaq code-D halt feed: last-trade confirmation
    openfigi.py            OpenFIGI /v3/mapping and /v3/filter client
    figi_resolution.py     Pure rules: OpenFIGI answer → one US composite FIGI or placeholder
    ticker_resolver.py     6-tier ticker→CIK resolver with strict/loose validation
    security_master.py     FigiResolver, build_securities, ticker/CUSIP range building
    form25.py               Form 25 parsing, exchange/class labeling, security matching
    listing_status.py       Secondary-listing withdrawal detection; current listing status
    last_trade.py           Last-trade-date decision across notice/8-K/MIDAS/halt
    delistings.py            DelistingFinder: finds, groups, dates and classifies delistings
    classifier.py            Form-25 + 8-K-item + Form-15 fingerprint classifier
    crsp_codes.py             CRSP DLSTCD → bucket mapping (the truth table)
    pipeline.py               run(): observations → security master + delisting table
    handling.py               Pure train-label and backtest-exit per bucket
    exchanges.py               Listing-exchange normalization (NYSE/AMEX/NASDAQ/OTHER)
    bmp_correction.py          BMP 2007 firm-month return correction (Shumway constants)
    dlret.py                    DLRET hub: resolve_dlret / compute_dlret
    reconstruction.py           EnrichedDelistRecord, build_delistings_table — output/delistings.csv
    payout_extractor.py         Per-share cash merger consideration from EDGAR filings (regex)
    llm_merger_extractor.py     Cash+stock/stock-only merger terms via an LLM
    qlib_adapter.py             DataFrame adapters: inject_terminal_labels, apply_backtest_exits

scripts/
    verify_altair.py                 End-to-end sanity check on ALTR (Siemens deal)
    observations_from_instruments.py  Legacy (ticker,start,end) file → observations CSV
    observations_from_snapshots.py    Folder of dated snapshot CSVs → observations CSV
    classify_universe.py              Reads --observations → writes the six output tables
    verify_against_web.py             Independent EDGAR cross-check → output/web_verification.csv
    compute_corrected_returns.py      CLI: read panel + delistings.csv → write BMP-corrected panel
    regen_payout_fixtures.py          Regenerate golden payout test fixtures from live SEC
    build_golden_fixtures.py          Rebuild the golden regression set from live EDGAR

output/
    securities.csv        One row per identified security
    ticker_history.csv    Point-in-time ticker ranges per security
    cusip_history.csv     Point-in-time CUSIP ranges per security
    delistings.csv        One row per delisting, with DLRET and its audit trail (primary output)
    payouts.csv           Per-merger extracted payout with source + accession (gated)
    review.csv            Every row (delisting or not) that needs a human look
    run_manifest.json     What the run rested on: as_of, code version, SEC requests/cache/latency per endpoint
    web_verification.csv  Per-row independent cross-check verdict

cache/
    edgar/*.json                 SEC JSON cache (re-runs are free); search answers held by a TTL
    edgar/text/*                 Stripped filing text cache
    openfigi/*                   OpenFIGI mapping/filter response cache
    sec_data/ftd/*, sec_data/midas/*   Downloaded/summarized SEC data files
    nasdaq_halts/*                Nasdaq halt feed cache
    ticker_resolution.json       Ticker→CIK memo, keyed by (ticker, observed_date)

tests/                            Pytest suite with a FakeEdgar fixture and per-client fakes
docs/
    data-flow.md                 End-to-end pipeline diagram and rules
```

For the full pipeline diagram and the rule table, see
[`docs/data-flow.md`](docs/data-flow.md).

---

## Observations and pins

The library has no membership list and no vendor to ask "what traded here?"
— it only knows what you tell it. An **observation** is one row: `ticker T
was seen trading, as of date D`, optionally with the `name` it carried, its
`cusip`, and a `cik`/`sec_id` **pin** when you've already settled that
sighting's identity (see `CONTEXT.md`). `classify_universe.py --observations
obs.csv` requires this CSV; nothing else drives which securities get looked at.

```
ticker, as_of, name, cusip, cik, sec_id
```

Only `ticker` and `as_of` are required. Two helpers build one from what you
likely already have:

- `observations_from_instruments.py --instruments (ticker,start,end).tsv` —
  the legacy vendor-instruments shape becomes two observations per row, on
  the start and end dates.
- `observations_from_snapshots.py --dir <folder>` — a folder of dated
  index-membership CSVs (date in the file name, `ticker`/`symbol` and
  optionally `name`/`cusip` columns) becomes one observation per row per file.

`ObservationIndex` groups one ticker's observations into **eras** — runs
that belong to one security — splitting on a name mismatch, a `cik`/`sec_id`
pin change, or a gap over `ERA_GAP_DAYS` (400 days) that neither side's name
confirms as continuous. A recycled ticker (`MON` = Monsanto, later Monument
Circle) is never merged into one security by this rule.

### How an era resolves to a CIK

Tickers get recycled (e.g. `ALTR` was Altera 1988–2015, then Altair 2017–
2025), and EDGAR's master ticker map only lists currently-registered
issuers. `TickerResolver` tries strategies in order of precision, then
validates the candidate looks like a delist *target* (not an *acquirer*):

1. **The era's `cik` pin.** Beats every other tier, including the manual
   override, and is never written to the on-disk resolver cache
   (`cache/ticker_resolution.json`): the tier answers before the cache is
   even consulted, so persisting it would let a stale pin survive a later
   correction in the observations file.
2. **Manual override.** Hand-curated `MANUAL_OVERRIDES` for ~35 short
   ambiguous tickers (`AET`, `X`, `MER`, `KLG`, …) in
   `scripts/classify_universe.py`. Wins over everything below it.
3. **`company_tickers.json`.** Master active map.
4. **EFTS Form-25/15 within ±90 days.** Most precise; skips known
   exchange CIKs (Nasdaq, NYSE, …) automatically.
5. **The era's own `name` → EDGAR cgi-bin company search.** Generates name
   variants (suffix-stripped, leading 1-3 tokens) and queries the ATOM
   endpoint, using the name from the era's own observations — not a stale
   index-membership file elsewhere.
6. **EFTS 8-K frequency rank.** Counts CIKs in 8-Ks mentioning the
   ticker in the 120 days pre-delist; strict-validates each candidate.

Validation: a candidate CIK is only accepted if it filed Form 25 or
Form 15 within ±540 days of the observed delist date. In strict mode
(used for frequency-rank candidates) it must additionally have no
10-K/Q/20-F in the window `[delist + 90d, delist + 5y]` — the target
stops periodic reporting; an acquirer does not.

A pin does not silence the name check: whenever the era carries a `name`,
the resolved CIK's EDGAR name is checked against it and, on a disagreement,
the row is flagged `member_name_mismatch` regardless of how the CIK was
found (see the flag table above) — a pin states a fact about the security,
not about how the CIK was found, and even a pinned row can name the wrong
company.

### How an era resolves to a `sec_id`

`FigiResolver` queries OpenFIGI for each era: a `sec_id` pin wins outright;
otherwise it tries, in order, the era's known CUSIPs (a CUSIP hit needs no
name check), then the era's ticker (needs a matching per-venue ticker+name),
then an issuer-name filter search — see the spec's Implementation notes for
why CUSIP is tried first. When nothing is accepted, the security gets the
placeholder `sec_id` `CIK<cik>-<CLASS>` (flagged `no_figi`); with no CIK
either, the observation goes to `review.csv` as `observation_unresolved`.

---

## Verifying the output

`scripts/verify_against_web.py` reads `output/delistings.csv` (or `--input`)
and does an independent EDGAR cross-check for each row, checking the row's
own `resolved_name` — the name our resolver settled on — against the EDGAR
entity page's current and former names, and emits a verdict in
`output/web_verification.csv` (`sec_id, ticker, our_bucket, web_says, agree,
evidence_url, note`):

| Verdict | What it means |
|---|---|
| `OK` | `resolved_name` shares a token with EDGAR's name; bucket-specific evidence present (M&A items for `merger`, a 3.01 for `compliance_failure`, a Form 15 for `liquidation`) |
| `OK_recycled_ticker` | `resolved_name` shares no token with EDGAR's current/former names, but the CIK still has a Form 25 within ±30d of the observed date |
| `MISMATCH_name` | `resolved_name` shares no token with EDGAR's name and no nearby Form 25 — needs human review |
| `WEAK_no_delist_form`, `WEAK_no_ma_items`, `WEAK_no_3_01`, `WEAK_no_form15` | Names agree, but the bucket-specific evidence expected on EDGAR wasn't found |
| `no_cik`, `bad_cik`, `no_entity_data` | No CIK, an invalid one, or the EDGAR entity page had nothing to check |

Run it after a full `classify_universe.py` pass and use `--sample N` for a
stratified spot-check across buckets rather than the whole table.

---

## Known limitations

* Short / common tickers (≤3 chars) can be ambiguous when multiple companies
  delisted in the same window. The fix is to add an entry to
  `MANUAL_OVERRIDES` in `scripts/classify_universe.py`.
* Form 25 doesn't always exist for pre-2002 delistings — those fall to the
  8-K-only path with `medium` confidence.
* SPAC-style ticker recycling (new IPO inheriting an old delisted ticker)
  needs the date-window to disambiguate; `ObservationIndex`'s era-splitting
  and the resolver's `(ticker, observed_date)` cache keying handle this
  automatically.
* Spin-offs (e.g. `WYN` splitting into `WH` + `TNL` in 2018) classify as
  `exchange_transfer` because the parent legal entity continues filing —
  you may want to override the train/backtest policy for these manually.
* SEC fails-to-deliver and MIDAS have no row on a quiet day, so a `close_after`
  lookup can lag (flagged `ftd_close_lagged`) and MIDAS confirmation only
  goes back to 2012 — pre-2012 last-trade dates rely on filing text alone
  unless the Nasdaq halt feed has an entry.

---

## Where each date and price comes from

Every date and price in `delistings.csv` traces to a specific SEC source —
never a price vendor, never Alpha Vantage:

* **`delist_date`** — the Form 25 filing date plus 10 days (Rule
  12d2-2(d)(1)); or, when no Form 25 applies to this security, the date of
  whichever filing the classifier's fallback path used to confirm the
  delisting (a closing 8-K, a Form 15, an EDGAR `REVOKED` filing, or a SPAC
  trust liquidation) — or, failing that, the security's last sighting itself
  (flagged `delist_date_approx`).
* **`last_trade_date`** — decided in this order by `last_trade.decide_last_trade`:
  1. The exchange's **EX-99.25 notice** on the Form 25 (`form25.py`):
     "suspended from trading on D" → the trading day before D; "at/after the
     close on D" → D; "prior to the opening on D" → the trading day before D.
  2. The closing **8-K's Item 3.01** text (`last_trade.py`), read the same way.
  3. **SEC MIDAS** per-security exchange volume (`midas.py`, 2012+): the last
     day with nonzero lit+hidden exchange volume, when it falls in a plausible
     window around the filing date. When the requested window runs past
     MIDAS's coverage end (the last day of the latest quarter it could load)
     and the found day sits within 5 trading days of that edge, MIDAS answers
     `None` instead — an unpublished quarter always yields nothing, so a day
     that close to the edge is indistinguishable from "the next quarter just
     isn't out yet" and would otherwise beat the notice/8-K on stale grounds.
  4. **Nasdaq's trade-halt feed** (`nasdaq_halts.py`): a code-`D` ("security
     deletion") halt, used only when MIDAS has no answer.
  5. MIDAS beats a halt beats filing-text wording; a measured date that
     disagrees with the filing text is flagged `last_trade_date_conflict`;
     text alone with no confirmation is flagged `last_trade_date_unconfirmed`.
* **`last_trade_close` and `acquirer_price`** — **SEC fails-to-deliver**
  rows (`ftd.py`, 2004+): the row dated `last_trade_date + 1 trading day`
  carries `last_trade_date`'s close (fails-to-deliver rows are dated by
  settlement, one day after the trade). Looked up by CUSIP first
  (`cusip_history.csv`), falling back to the ticker on that date. The same
  lookup prices the acquirer on the merger's completion date. A quiet day
  with no fails-to-deliver row means the lookup walks forward up to 3
  trading days (flagged `ftd_close_lagged`); when no row follows the last
  trade at all (fails stop once trading stops), it looks back to the latest
  row dated on the last trade day or up to 10 trading days before it, whose
  price is the close of the day before that row (flagged
  `ftd_close_prior:<n>`, `<n>` its age in trading days; DLRET uses it as the
  last close), before giving up (`no_last_close`) — override with
  `--last-trade-closes`.

---

## Data sources

* SEC EDGAR `submissions/CIK########.json` (~50–200 KB per company, cached)
* SEC EDGAR full-text search `efts.sec.gov/LATEST/search-index`
* SEC EDGAR company search `www.sec.gov/cgi-bin/browse-edgar?…&output=atom`
* SEC fails-to-deliver data: `www.sec.gov/data-research/sec-markets-data/fails-deliver-data`
  (half-month ZIPs, 2004+)
* SEC MIDAS "Metrics by Individual Security": `www.sec.gov/opa/data/market-structure/…`
  (quarterly ZIPs, 2012+)
* Nasdaq Trader's keyless trade-halt feed: `www.nasdaqtrader.com/rss.aspx?feed=tradehalts`
* OpenFIGI `api.openfigi.com/v3/mapping` and `/v3/filter` (`OPEN_FIGI_API_KEY`
  optional but recommended: 250 mapping requests/60s with a key vs 25 without)
* SEC fair access: ≤10 req/s, descriptive `User-Agent` required. The
  client throttles to 8 req/s and is single-threaded; the FTD/MIDAS
  downloader shares the same throttle.
* Transient failures retry: a connection error, a timeout, or a 5xx on a
  submissions fetch, a filing-text/raw fetch, a full-text-search query, or a
  MIDAS/FTD download is retried up to 3 attempts with 2s/4s backoff
  (`edgar.retry_request`) before giving up. A 403/429 still raises
  `EdgarBlocked` immediately, never retried; a failure is never cached as an
  answer. A MIDAS quarter that keeps failing to download is remembered
  in-memory for the rest of the run, so later securities don't pay the same
  download-and-retry cost again.
* No price vendor, no Alpha Vantage — every price and date above comes from
  a public SEC data set.

## Exit codes (`classify_universe.py`)

| Code | Meaning |
|---|---|
| `0` | Success, no `error` or `resolution_degraded` rows in `review.csv`. |
| `2` | Aborted: SEC or OpenFIGI refused the request (`EdgarBlocked` / `OpenFigiBlocked`), or a start-up check failed (no `EDGAR_USER_AGENT`, an unusable SEC rate-lock file, or `--sec-workers` outside `[1, 8]`) — no output written. |
| `3` | Completed, but `review.csv` has one or more `error` rows (one security or extraction raised and was logged instead of aborting the run) or `resolution_degraded` rows (an answer rested on a failed SEC request or a stale copy) — outputs are still written; the run prints a banner to stderr with the counts. |

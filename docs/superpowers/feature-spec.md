# Security Master and Delisting Table — Feature Specification

*PRD / technical specification · 2026-09-23 · status: approved for planning*

| | |
|---|---|
| Owner | Roy Lee |
| Decision log | [`specs/2026-09-22-security-master-and-delistings-design.md`](specs/2026-09-22-security-master-and-delistings-design.md) (decisions D1–D23, evidence) |
| Glossary | [`CONTEXT.md`](../../CONTEXT.md) |
| Research | [`research/last-trade-date-sources.md`](../research/last-trade-date-sources.md), [`research/dlret-generation.md`](../research/dlret-generation.md) |
| Source design | [Handling delisted symbols, from universe to training data](https://claude.ai/artifact/7fBt5ZVbrGMP8kFtkCWzTp), steps 1 and 3 |

---

## 1. Summary

Rebuild `delist_detection` around a **security master** keyed by the US composite
FIGI. The caller sends **observations** (a ticker seen on a date). The library
identifies each observed security, builds its ticker and CUSIP history from SEC
data, finds every **delisting** of it from EDGAR Form 25 filings, classifies each
into the existing CRSP buckets, dates the last trade and prices the delisting
return from SEC data, and writes five CSV tables to `output/`. It needs no price
vendor and no Alpha Vantage data. Membership (which securities are in an index on
a date) stays with the caller.

## 2. Problem

Today the library is keyed by ticker and trusts the caller's `(ticker, start, end)`
file. Four problems follow:

1. **The caller's end date drives everything**, and it is often wrong. Tiingo's
   last row is a zero-volume filler in 274 of 461 delisted series; it matched the
   true last trading day in only 14 of 45 checked events.
2. **Recycled tickers produce wrong rows.** In the current `output/`, MON
   2022-12-23 carries Monsanto's CIK (the ticker then belonged to Monument Circle),
   and THOR, STR, THRX and KWK are similar. HOT, NFS, PAS, PE and TSS are
   classified `expiration` from Alpha Vantage ETF names; on those dates they were
   Starwood, Nationwide Financial, PepsiAmericas, Parsley Energy and TSYS.
3. **No permanent identity.** A ticker names a listing, not a security, so
   renames, reorgs and share classes cannot be followed.
4. **Prices come from outside.** DLRET needs `last_trade_close` and acquirer
   closes from the caller; without them most merger rows are blank.

## 3. Goals and non-goals

**Goals**
- G1. One row per security in `securities.csv`, keyed by `sec_id` = US composite
  FIGI (placeholder when no FIGI can be confirmed).
- G2. Point-in-time `ticker_history.csv` and `cusip_history.csv`.
- G3. `delistings.csv`: one row per delisting, found from EDGAR, classified with
  the unchanged bucket/CRSP-code rules, with last trade date, last close, terminal
  value and DLRET computed from SEC data.
- G4. Self-contained: the library downloads every input it uses (EDGAR, OpenFIGI,
  SEC fails-to-deliver, SEC MIDAS, Nasdaq halt feed). No vendor price key.
- G5. Universe-agnostic: works for any set of US observations; no index assumed.
- G6. Every observed security ends up either listed today, delisted, or listed in
  `review.csv` with a reason. Nothing is dropped silently.
- G7. Tests stay fully offline; the golden regression set stays green after being
  re-keyed.

**Non-goals**
- Membership intervals (step 2), the daily price panel (step 4), features, labels
  and walk-forward splits (steps 5–9).
- Spin-off and new-share-class links (`security_events` is dropped; D11).
- Vendor ID cross-reference (`vendor_xref` is dropped; D23).
- Non-US securities. A foreign acquirer keeps only `acquirer_ticker`.
- DuckDB. Storage is CSV for now, behind one schema module.
- Changing the bucket policies, CRSP code mapping, payout gate or DLRET formulas.

## 4. Users and consumers

- **Researchers** building survivorship-bias-aware training labels and backtests.
- **`qlib_practice`** (companion repo): today calls `scripts/classify_universe.py`
  through `build-dlret` and reads `dlret.csv`. It will migrate (section 13).

## 5. Domain model

Defined in [`CONTEXT.md`](../../CONTEXT.md); summary:

- **Security**: one share class traded in the US; `sec_id` = US composite FIGI, or
  a placeholder `CIK<cik>-<CLASS>` when no FIGI is confirmed.
- **Issuer**: the SEC filer (CIK). One issuer can have several securities.
- **Listing**: a security under one ticker on one exchange over a date range.
- **Delisting**: removal of a security from its US exchange listing, after which
  it is on no exchange or has moved to another one; recorded by a Form 25 (or the
  filing that ended trading when none exists). Not a rename; not the withdrawal of
  a secondary listing.
- **Bucket**: `merger`, `exchange_transfer`, `liquidation`, `compliance_failure`,
  `expiration` (and `active`/`unknown`), unchanged from today.
- **Successor**: the security a holder keeps after an `exchange_transfer`.
- **Observation**: a caller record `(ticker, as_of, name?, cusip?, cik?, sec_id?)`.
- **Pin**: a `cik` or `sec_id` on an observation that overrides resolution but is
  still name-checked.
- **Universe**: the caller's set of securities, known only through observations.

## 6. Inputs

### 6.1 Observations (required)

CSV, one row per sighting. Only `ticker` and `as_of` are required.

| Column | Type | Meaning |
|---|---|---|
| `ticker` | str | Ticker as the caller saw it (`BRK-B`, `BRK.B`, `BRK/B` are normalized) |
| `as_of` | ISO date | Date it was seen trading under that ticker |
| `name` | str, optional | Issuer/security name as seen (used for the name check) |
| `cusip` | str, optional | CUSIP as seen; checked against SEC data |
| `cik` | int, optional | Pin: the issuer CIK the caller has settled |
| `sec_id` | str, optional | Pin: the composite FIGI (or placeholder) the caller has settled |

A helper converts an old `(ticker, start, end)` file into two observations per
row (A5), and another turns a folder of dated snapshot CSVs (`ticker`, `name`
columns, date in the file name) into observations.

### 6.2 Value overrides (optional)

`--last-trade-closes`, `--merger-terms`, `--recoveries` keep their value columns
but are keyed by `(sec_id, delist_date)`; a blank `delist_date` applies to every
delisting of that security (D13). A row that matches no delisting stops the run
(A2).

### 6.3 Environment

| Variable | Use |
|---|---|
| `EDGAR_USER_AGENT` | Required for every SEC request (existing) |
| `OPEN_FIGI_API_KEY` | OpenFIGI key, sent as `X-OPENFIGI-APIKEY`; optional but present in `.env` (250 mapping requests/60 s with key vs 25 without) |
| `OPENAI_API_KEY`, `CHAT_MODEL` | Only for `--extract-merger-terms-llm` (existing) |

Removed: `AV_LISTING_CSV`, `AV_ACTIVE_CSV`, `RAW_TIINGO_DIR`.

## 7. Outputs

All tables are written to `output/` and committed (D9). One CSV per table, fixed
column order, ISO dates, empty cell for NULL, rows sorted by key. Date ranges are
inclusive and an empty end means still open (D10). One module (`store.py`) owns
every table's column list, key and sort order, so a later DuckDB backend changes
only that module.

### 7.1 `securities.csv` — key `sec_id`

| Column | Meaning |
|---|---|
| `sec_id` | US composite FIGI, or placeholder `CIK<cik>-<CLASS>` (D19) |
| `issuer_cik` | Issuer CIK |
| `share_class` | Class label (e.g. `COMMON`, `CLASS A`, `SERIES C`) |
| `name` | Security name (OpenFIGI name when resolved, else EDGAR name) |
| `security_type` | OpenFIGI `securityType` (e.g. `Common Stock`, `ETP`, `REIT`); empty for placeholders |
| `observed` | `true` if any observation resolved to it; `false` for successors/acquirers added by D18 |
| `figi_source` | How the FIGI was found: `pin`, `ticker`, `cusip`, `name`, or `placeholder` |

No `first_date`, `last_date` or `end_reason` (D15, A4).

### 7.2 `ticker_history.csv` — key `(sec_id, valid_from)`

| Column | Meaning |
|---|---|
| `sec_id` | Security |
| `ticker` | Ticker in canonical form (`BRK-B`) |
| `exchange` | Exchange of the main listing (`NYSE`, `NASDAQ`, `NYSE AMERICAN`, `NYSE ARCA`, `CBOE BZX`, `OTC`, or empty when unknown) |
| `valid_from` | First day under this ticker (inclusive) |
| `valid_to` | Last day under this ticker (inclusive); empty when open |
| `source` | Evidence for the range: `edgar_8k`, `form25`, `ftd`, `observation` |

### 7.3 `cusip_history.csv` — key `(sec_id, valid_from)`

`sec_id`, `cusip`, `valid_from`, `valid_to`, `source` (`ftd` or `observation`).
Built from SEC fails-to-deliver rows (D21).

### 7.4 `delistings.csv` — key `(sec_id, delist_date)`

Replaces `dlret.csv` and `delist_classifications.csv` (D8, A1). Column order:

```
sec_id, delist_date, ticker, cik, bucket, crsp_code, confidence, reason,
exchange, last_trade_date, last_trade_close, successor_sec_id, acquirer_sec_id,
acquirer_ticker, payout_per_share, stock_ratio, acquirer_price, recovery_ratio,
terminal_value, dlret, dlret_method, dlret_confidence, payout_source,
delist_filing_form, delist_filing_date, delist_filing_accession, anchor_8k_items,
dereg_form, resolved_name, resolution_source, last_trade_date_source,
raw_payout_per_share, raw_payout_source, raw_payout_confidence, review_flags
```

- `delist_date`: Form 25 filing date + 10 days (Rule 12d2-2(d)(1)), or the date of
  the fallback filing that ended trading when no Form 25 exists.
- `ticker`: the ticker on `last_trade_date` (or `delist_date`).
- `exchange`: the exchange named on the Form 25 (D22).
- `last_trade_date_source`: `ex99_notice`, `8k_301`, `midas`, `nasdaq_halt`,
  `override`, or empty.
- `raw_payout_*`: the extraction before the last-close gate (was in
  `delist_classifications.csv`).
- There are no `active` rows: a security with no delisting has no row.

### 7.5 `payouts.csv` and `review.csv`

Unchanged in content, re-keyed by `(sec_id, delist_date)` (A6). `review.csv` also
receives rows with no delisting: `ended_without_delisting`, `no_figi`,
`form25_unmatched`, `observation_unresolved` (section 8.10).

## 8. Functional requirements

### 8.1 Load observations (FR-1)
- Parse and validate the observation CSV; normalize tickers (`.`/`/` → `-`,
  upper-case); reject rows without `ticker` or a valid `as_of`.
- Group observations by `(ticker)` into contiguous sightings for resolution.

### 8.2 Resolve the issuer (FR-2)
- For each observation: a `cik` pin wins; otherwise `MANUAL_OVERRIDES`; otherwise
  the existing `TickerResolver` tiers, with the observation's `name` as the
  member name for the name check (replaces `--names`).
- A pin or resolution whose EDGAR name disagrees with the observation name is
  kept and flagged `member_name_mismatch` (existing behavior).
- `--cik-map` and `--names` are removed (D12).

### 8.3 Resolve the composite FIGI (FR-3)
- A `sec_id` pin wins.
- Otherwise query OpenFIGI `/v3/mapping` in this order, each with
  `includeUnlistedEquities: true`:
  1. `TICKER` without `exchCode` (per-venue rows keep the original ticker and name
     and point to the composite).
  2. `ID_CUSIP` (or `ID_CINS` for foreign CUSIPs starting with a letter) when a
     CUSIP is known from the observation or `cusip_history`.
  3. `/v3/filter` on the issuer name with legal suffixes stripped.
- Keep only rows whose composite is a US composite (`exchCode` `US`, or a US venue
  whose `compositeFIGI` is the US composite).
- Accept a candidate only when a check that does not depend on Bloomberg's
  current name passes: the CUSIP matches; or a per-venue row carries the
  observation's ticker and a name that agrees with the observation/EDGAR name; or
  the name matches the acquirer/successor named in the security's delisting 8-K.
  Bloomberg renames dead lines to the acquirer (QCOR → `MALLINCKRODT ARD LLC`),
  so a plain name check is not enough.
- Reject when-issued, 144A and fund-NAV lines (`securityType2` / ticker suffix
  checks) and candidates of a different share class.
- If no candidate is accepted, assign the placeholder `CIK<cik>-<CLASS>` and flag
  `no_figi` (D19). With no CIK either, the observation goes to `review.csv` as
  `observation_unresolved`.
- Cache every OpenFIGI response on disk; pace on the `ratelimit-*` headers; a
  429 waits for `retry-after`. A 401/403 aborts the run.

### 8.4 Build securities (FR-4)
- Observations that resolve to the same `sec_id` form one security.
- `share_class` from the OpenFIGI name suffix or EDGAR class text; `name` and
  `security_type` from OpenFIGI.

### 8.5 Build `ticker_history` (FR-5)
- Start from the observations: each `(sec_id, ticker)` pair gives a range from its
  first to last sighting.
- Widen and cut ranges with SEC evidence:
  - ticker-change announcements found by EDGAR full-text search for the new
    ticker near the switch ("ticker symbol", "trading symbol") give the change
    date; the old row ends the day before (`edgar_8k`);
  - fails-to-deliver rows give dated `(CUSIP, symbol)` pairs that extend each
    range (`ftd`);
  - the delisting's `last_trade_date` closes the final row on that exchange
    (`form25`).
- The main exchange per row comes from the Form 25 (for the row it ends) and
  from OpenFIGI's current listing for an open row.
- Ranges of one security must not overlap; a ticker must not map to two
  securities on the same day (checked, violations flagged).

### 8.6 Find delistings (FR-6)
- For each observed security's issuer, list every Form 25 / 25-NSE / 25/A in the
  submissions JSON, including the paginated older files.
- Parse the Form 25 XML (`notificationOfRemoval`: exchange, issuer,
  `descriptionClassSecurity`, `ruleProvision`) or, before XML, the text.
- **Match to one security (D16):** drop classes the issuer's observed securities
  are not (preferred, notes, warrants, units, rights); a single observed security
  of that kind takes it; otherwise match the class letter/series to
  `share_class`; zero or several matches → `review.csv` `form25_unmatched`.
- **Secondary listing check (D17):** a Form 25 counts only when the security has
  no exchange listing left afterwards or has moved to a new one. Evidence: the
  exchanges named for the class on 10-K cover pages before and after (XBRL
  `dei:SecurityExchangeName` since 2019, cover text before), plus OpenFIGI's
  current listing. Withdrawals from a regional/secondary exchange while the main
  listing continues (Apache/Chicago 2020, Toll Brothers/Pacific 2007) create no
  row.
- **No Form 25:** the classifier's existing fallback paths (8-K 2.01 completion,
  Form 15, `REVOKED`, SPAC trust liquidation) find and date the delisting.
- A security can have several delistings (e.g. an exchange transfer, later a
  merger).

### 8.7 Classify (FR-7)
- Run the existing `DelistClassifier` rules per delisting, anchored on the
  Form 25 date and `last_trade_date` instead of the vendor end date. The CRSP
  codes, buckets and rule order do not change (D5).
- Replace the Alpha Vantage inputs (D22): exchange from the Form 25; kind of
  security from the Form 25 class text, OpenFIGI `securityType` and the name
  keyword check; names from observations and EDGAR.
- A rename is not a delisting and never yields code 304 by itself.

### 8.8 Last trade date and closes (FR-8, D20)
- **Date:**
  1. The exchange's EX-99.25 notice on the Form 25-NSE. NYSE-family merger
     notices ("suspended from trading on D", rule `(a)(3)`): last trade = the
     trading day before D. Involuntary `(b)` notices: D is the decision day;
     confirm with step 3.
  2. The closing 8-K's Item 3.01 text ("prior to the opening of trading on D" →
     previous trading day; "after the close of trading on D" → D).
  3. Confirmation: SEC MIDAS per-security files (2012 onward; last day with
     exchange volume) and Nasdaq's trade-halt feed (halt code `D` timestamp).
  4. When sources disagree, prefer MIDAS, flag `last_trade_date_conflict`.
- **Closes:** SEC fails-to-deliver files (2004 onward). The row dated D carries the
  close of D−1. Look up by CUSIP (`cusip_history`), falling back to the symbol on
  that date. The same lookup prices the acquirer on the completion date.
- Missing close → `lt.csv` override; otherwise `dlret` stays blank
  (`needs_last_trade`) and the row goes to `review.csv`.
- Tiingo and `raw_tiingo.py` are removed (D20, D23).

### 8.9 Successors, acquirers, payouts, DLRET (FR-9)
- `exchange_transfer` with the same FIGI after the move → `successor_sec_id` =
  own `sec_id`.
- FIGI change (holdco reorg, reclassification) → the successor issuer's 8-K12B
  (Alphabet 2015-10-02; APA 2021-03-01) names it; its security of the matching
  class is the successor (D18).
- `acquirer_ticker` from the regex/LLM extractors is resolved to
  `acquirer_sec_id` through OpenFIGI on the completion date (US only).
- Successors and acquirers not observed get `securities` and `ticker_history`
  rows with `observed=false`; their own delistings are not searched (D18).
- Payout extraction, LLM terms, the last-close gate and `dlret.py` run unchanged,
  keyed by `(sec_id, delist_date)`.

### 8.10 Completeness check (FR-10, default for Q23)
- Every observed security must be listed today (OpenFIGI returns it without
  `includeUnlistedEquities`, or EDGAR's current ticker list shows it on an
  exchange) or have a delisting that took it off the exchanges. Otherwise it goes
  to `review.csv` as `ended_without_delisting` with its last observation date, and
  the run prints the count. No row is added to `delistings.csv`.

### 8.11 Handling layer (FR-11, D14)
- `handling.py`, `bmp_correction.py`, `qlib_adapter.py` read `delistings.csv` and
  join to panels on `sec_id` only.
- The dictionary arguments (`payouts`, `successor_map`, `exchanges`,
  `last_trade_closes`, `recovery_ratios`) are removed; each delisting row carries
  those values (A3). Per-event functions take one delisting row.

## 9. Data sources and access rules

| Source | Endpoint | Used for | Limits / caching |
|---|---|---|---|
| EDGAR submissions | `data.sec.gov/submissions/CIK##########.json` (+ paginated files) | Form 25/8-K/15/8-K12B lists, names | ≤ 8 req/s, User-Agent; `cache/edgar/` |
| EDGAR filing documents | `www.sec.gov/Archives/edgar/data/...` | Form 25 XML, EX-99.25, 8-K text, 10-K covers | same; `cache/edgar/text/` |
| EDGAR full-text search | `efts.sec.gov/LATEST/search-index` | ticker-change announcements, resolver tiers | same; `cache/edgar/`, each answer held 7–365 days by how long after its window it was fetched (§17) |
| OpenFIGI | `api.openfigi.com/v3/mapping`, `/v3/filter` | composite FIGI, security type | `ratelimit-*` headers; `cache/openfigi/` |
| SEC fails-to-deliver | `www.sec.gov/data-research/sec-markets-data/fails-deliver-data` (half-month ZIPs, 2004+) | closes, CUSIP history | same SEC rules; `cache/sec_data/ftd/`; download only the periods needed |
| SEC MIDAS by security | `www.sec.gov/opa/data/market-structure/marketstructuredownloadshtml-by_security.html` (quarterly ZIPs, 2012+) | last day with exchange volume | `cache/sec_data/midas/`; download only needed quarters |
| Nasdaq halt feed | `www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate=MMDDYYYY` | halt code `D` timestamp | keyless; `cache/nasdaq_halts/` |

Rules:
- Every response is cached on disk; re-runs are free. Caches are gitignored.
- A SEC 403/429 raises `EdgarBlocked` and the CLI exits 2 (existing). The same
  applies to the other SEC data sets. OpenFIGI 429 is waited out; 401/403 exits 2.
- Search evidence may be cached with a TTL; a resolver decision is never cached
  as a miss. EDGAR full-text-search and company-name-search answers, empties
  included, are cached with their fetch date and asked again when their TTL runs
  out (§17); every run re-derives a miss from that evidence with the current code.

## 10. CLI

```bash
python scripts/classify_universe.py --observations obs.csv \
    [--last-trade-closes lt.csv] [--merger-terms terms.csv] [--recoveries rec.csv] \
    [--extract-merger-terms-llm] [--no-extract-payouts] [--limit N]
# → output/securities.csv, ticker_history.csv, cusip_history.csv,
#   delistings.csv, payouts.csv, review.csv

python scripts/observations_from_snapshots.py --dir <folder of dated CSVs> --out obs.csv
python scripts/observations_from_instruments.py --instruments all.txt --out obs.csv   # (ticker,start,end) → 2 rows each
```

`compute_corrected_returns.py` reads `delistings.csv` and a panel keyed by
`sec_id`. `verify_against_web.py` reads `delistings.csv`.

## 11. Non-functional requirements

- **Offline tests.** Every new client (OpenFIGI, FTD, MIDAS, Nasdaq halts) has a
  fake or fixture-backed test double; no network in `pytest`.
- **Determinism.** Same inputs and caches → byte-identical CSVs.
- **SEC fair access** unchanged: ≤ 8 req/s, descriptive User-Agent.
- **Runtime.** A cold run on ~2,300 observed securities finishes overnight; a
  cached re-run in minutes.
- **No silent zero, no silent drop.** Blank values carry a method/flag; every
  unresolved case appears in `review.csv`.

## 12. Removed and changed

| Removed | Replaced by |
|---|---|
| `output/dlret.csv`, `output/delist_classifications.csv` | `output/delistings.csv` |
| `--names`, `--cik-map`, `names.py` `MemberNames` CSV loader | observation `name`, `cik`, `sec_id` |
| `av_listing.py`, `AV_LISTING_CSV`, `AV_ACTIVE_CSV` | Form 25 exchange/class, OpenFIGI type, observation names |
| `raw_tiingo.py`, `--raw-tiingo-dir`, `RAW_TIINGO_DIR` | SEC fails-to-deliver closes |
| `data/delisted_tickers.tsv` as the input | observations |
| ticker-keyed handling dictionaries | columns on the delisting row |

Docs to update: `CLAUDE.md`, `README.md`, `docs/data-flow.md` (the "only EDGAR
data" and "point it at any `(ticker, start, end)` file" statements, commands,
architecture, test count).

## 13. Acceptance criteria

1. `pytest` passes offline, including the re-keyed 31-case golden set.
2. A full run on the `qlib_practice` universe (observations from its iShares and
   Wikipedia snapshot CSVs) writes all six files with no crash and prints coverage.
3. Spot checks:
   - AET: `sec_id` `BBG000FJLFX8`; delisting bucket `merger`; `last_trade_date`
     2018-11-28; `last_trade_close` 212.70.
   - ALTR (Altair): `last_trade_date` 2025-03-25 (not Tiingo's 2025-03-26).
   - SAVE: `last_trade_date` 2024-11-15.
   - MON: Monsanto's delisting in 2018, not a 2022 row with Monsanto's CIK.
   - HOT, PE, TSS: `merger`, not `expiration`.
   - Apache: no delisting from the 2020 Chicago Stock Exchange withdrawal.
   - GOOG/GOOGL: Alphabet class A and class C are two securities.
4. Every observed security is listed today, has a delisting, or is in
   `review.csv` with a reason.
5. `verify_against_web.py` agreement on the delisting rows is at least the current
   98.9%.
6. `last_trade_close` is filled for at least 90% of 2004+ merger delistings.

## 14. `qlib_practice` migration (follow-up, separate repo)

1. Build observations from its iShares/Wikipedia snapshots; send its reviewed
   CIKs (`universe_identity.csv`) as `cik` pins.
2. Rename panel instruments from tickers to `sec_id` via `ticker_history.csv`
   before moving the pin (handling joins on `sec_id` only).
3. Key membership on `sec_id`; end intervals at the security's delisting.
4. Switch `inject_delist_labels_dlret.py`, `knob_sweep/extend_labels.py`,
   `apply_delist_exits.py`, `audit_delist_exits_dlret.py`, `audit_delist_exits.py`,
   `inject_delist_labels_lib.py` to `delistings.csv`.
5. Re-key its override files to `(sec_id, delist_date)`.
6. Decide the future of branch `feat/universe-identity` (its output becomes pins).
7. Its harsh training marks stay its own policy.
8. Move the SHA pin in `fetch_data_aplha/pyproject.toml` last.

## 15. Defaults taken without explicit confirmation

The interview ended before these were answered; the recommended option applies.

- Q23 → completeness check writes `review.csv` rows only (8.10).
- A1 `delist_classifications.csv` is removed with `dlret.csv`.
- A2 an override row matching no delisting stops the run.
- A3 handling functions lose their dictionary arguments.
- A4 `securities` has no `last_date`/`end_reason`.
- A5 an old `(ticker, start, end)` file converts to two observations per row.
- A6 `payouts.csv` and `review.csv` are keyed by `(sec_id, delist_date)`.
- The OpenFIGI key is read from `OPEN_FIGI_API_KEY`.

## 16. Risks

| Risk | Mitigation |
|---|---|
| Pre-2006 Form 25s are text, not XML, and pre-2004 8-Ks have no item codes | Fallback paths; `ended_without_delisting` review rows make gaps visible |
| Fails-to-deliver has no row on a quiet day | Look back a few rows (the price is the prior close); `lt.csv` override; blank with flag |
| MIDAS is keyed by ticker only and misses some securities | Used only to confirm; conflicts flagged |
| Name-based FIGI search picks another line of the issuer | Accept only with a name-independent check (8.3) |
| Class-text matching of Form 25 fails for odd wording | `form25_unmatched` review rows; golden cases for dual-class issuers |
| Large downloads (MIDAS ~11–23 MB per quarter) | Download only periods that contain a delisting; cache |
| Consumer breakage | `qlib_practice` pins a SHA and migrates on its own schedule (section 14) |

## 17. Implementation notes

Where the build made a call the spec text left open, or differs from it. Each
line changes observable output.

- **FIGI resolution order (§8.3).** `FigiResolver` tries the era's known
  CUSIPs first (a CUSIP hit needs no name check), then the era's ticker
  (needs a matching per-venue ticker+name), then an issuer-name filter
  search, in that order — not the order listed in §8.3.
- **EDGAR names in ticker and name acceptance (§8.3).** A ticker or name-search
  hit is accepted on the era's observed names first; only when they fail are
  its issuer's EDGAR names (current and former) added, so Northeast Utilities,
  seen under ES before its 2015 rename, takes Bloomberg's EVERSOURCE ENERGY
  line. A candidate only the EDGAR names accept is dropped when another era's
  pin or CUSIP contradicts it: an era of another known issuer is confirmed on
  it, or an era of the same issuer and share class is confirmed on another
  composite over overlapping dates. An issuer's names can outlive its stock
  and match a later line: the bankrupt General Growth Properties is now
  "GGP, Inc.", the name of the new issuer's GGP line, and Jacobs Engineering
  under a backfilled J in 2012 matches today's Jacobs Solutions line, a new
  composite since 2022, while its JEC era is on the old one. Nor may it take
  an era off its issuer's placeholder while another era of the same issuer
  and class has to stay there: that would put one stock on two `sec_id`s on the
  same dates and end the placeholder in a rename row (ACE LTD, backfilled
  under CB in 2012-14, while its ACE era finds no FIGI; Gannett under TGNA
  beside GCI; Weight Watchers under WW beside WTW). Such an era keeps its
  placeholder. These guards see only the eras in the same run: a universe
  that lacks the later issuer's CUSIP-confirmed era cannot contradict the
  match, so an old issuer can silently take the later issuer's line (drop new
  GGP from the observations and General Growth 2008 takes its FIGI; drop JEC
  and J 2012 takes Jacobs Solutions'). A review flag on every acceptance made
  only through EDGAR names is a follow-up.
- **§8.3's third acceptance route is not built.** Accepting a candidate
  because its name matches the acquirer or successor named in the security's
  delisting 8-K is not implemented: a security whose only OpenFIGI match
  carries that name keeps its placeholder, or its ticker/CUSIP match.
- **`ticker_history.source` values (§7.2).** Observed securities get only
  `observation` and `ftd` rows; `edgar_8k` appears only on a successor
  security's row, dated by its 8-K12B (the ticker-change search that would
  produce it for observed securities is deferred, see the next point).
- **§8.5's EDGAR ticker-change search is deferred.** `ticker_history` ranges
  are built only from observations and SEC fails-to-deliver rows; no search
  for a ticker-change announcement runs. Fails-to-deliver rows already date
  a ticker switch to within days, and parsing a change date out of 8-K text
  is a separate feature.
- **`ticker_history.exchange` (§7.2).** Filled from the matched Form 25 for
  the range that ends in a delisting, and from the issuer's current EDGAR
  submissions listing for the still-open range; every other range is empty.
- **§8.5 consistency checks are review rows, not aborts.** An overlap
  between two of one security's own `ticker_history` ranges, or the same
  ticker mapping to two securities on the same day, is written to
  `review.csv` as `ticker_range_overlap` / `ticker_shared` rather than
  failing the run.
- **Unexpected per-security failures don't abort the run.** A per-security
  or per-merger exception (other than `EdgarBlocked`/`OpenFigiBlocked`/
  `OpenFigiUnavailable`, which still abort) is logged and the security is skipped with a review row
  flagged `error`, so one bad security doesn't fail an overnight full run.
- **Era splitting (§5, "Observation"; §8.1).** A ticker's observations are
  grouped into eras (runs taken to be one security) in two stages. First,
  from observations alone: a new era starts on a pin change, on names that
  stop agreeing, or on a change of the class letter in the name (`CLASS A`
  → `CLASS C`; `CLASS A` and `SERIES A` are the same letter; a name with no
  class is unknown and never splits). A gap alone does not split here.
  Second, after the fails-to-deliver rows are loaded, each era is split
  again on that evidence under its ticker: where the FTD rows switch from
  one CUSIP to another (runs of 3+ rows; shorter runs are noise), and where
  the era's observation dates plus its FTD rows of those CUSIPs leave a gap
  over 400 days. FTD rows bridge the 2009 → 2012 snapshot gap for a
  security that kept trading; DELL (Dell Inc. to 2013, Dell Technologies
  from 2018), DOW, JEF and ADT split on the gap, FOX/FOXA, GOOG and UA on
  the CUSIP switch. The gap split runs first, so an observation of the new
  security dated before its CUSIP's first FTD row stays with it. A side
  with no observations is not an era. Eras that still resolve to the same
  FIGI (a reverse split's new CUSIP, a gap no row bridged) merge back into
  one security. No era is ever dropped: two eras of one ticker starting on
  the same date keep unique keys (`CB@2012-06-29`, `CB@2012-06-29#1`).
- **Two names for one ticker on one date (`observation_conflict`).** A
  snapshot source that backfilled today's ticker gives one ticker two names
  on a date (CB is both ACE LTD and CHUBB CORP from 2012-06-29 to
  2014-06-30; AGN both ALLERGAN INC and ALLERGAN PLC on 2014-06-30). Both
  observations are kept, and `review.csv` gets one row per such ticker and
  date, flagged `observation_conflict:<date>` (the date is in the flag so
  each keeps its own row under the table's key) and naming each name with
  the security it resolved to. Where the two names form separate eras on the
  same dates, the ticker's FTD CUSIP counts for an era only when its FTD
  description agrees with the era's names, so the backfilled name does not
  take the other security's CUSIP (ACE LTD never becomes Chubb Corp). It
  then resolves by name search, or else to its issuer placeholder.
- **Fallback delisting date (§8.6, no-Form-25 path).** Dated by a confirmed
  bankruptcy 8-K first, then the anchor 8-K, then a revocation or Form 15
  filing but only when it falls within `[last_seen − 30d, last_seen + 120d]`;
  otherwise the security's last sighting itself, flagged
  `delist_date_approx`. A late SEC revocation of a delinquent filer can come
  years after trading actually stopped, so an out-of-window revocation date
  is rejected in favor of last-seen rather than trusted at face value.
- **A Form 25 before the first sighting (§8.6, stale observations).** The
  Form 25 scan starts 30 days before the security's first sighting, so a
  snapshot that kept listing a security after it was acquired (A.G.
  Edwards, gone 2007-10-01, listed through 2009) would hide its delisting.
  When nothing from the first sighting on is a delisting and the security
  is not listed today, the classifier's fallback may still pick such an
  earlier Form 25 (its frozen-tail rule); it becomes the delisting when it
  matches the security by class and no fails-to-deliver row under the
  security's own tickers is dated after it, flagged
  `observed_after_delisting`. The close for a last trade before the
  fails-to-deliver window loaded for the eras is read from rows fetched
  for that day.
- **A successor already in the run (§8.9).** For an `exchange_transfer`
  delisting whose successor is unknown, the one security of the run
  (observed or added) whose first sighting falls within [last trade − 5 d,
  last trade + 15 d] and that shares the issuer CIK or the ticker becomes
  `successor_sec_id` before the 8-K12B search runs (the reason says "successor
  by same issuer" / "by same ticker"); zero or several candidates leave it to
  the 8-K12B search.
- **Only a transfer continues a listing (§8.6, §8.10).** A Form 25 group is
  "continued" when the security is listed today or sighted after its
  effective date, but a sighting after it can be OTC trading (a bankrupt
  security's tail) or a stale snapshot. A merger, liquidation, compliance
  failure or expiration therefore ends the security whatever follows it; only
  an exchange transfer (or an event the classifier could not place) that the
  security was sighted after leaves it open for a later delisting, the
  no-Form-25 fallback and the `ended_without_delisting` check.
- **Form 25 grouping (§8.6, D16).** Matched Form 25s chain into one
  delisting when a filing's date is within `SAME_EVENT_DAYS` (30 days) of
  the *group's earliest* member's filing date, not its latest — so filings
  55, 28 and 0 days apart form two delistings, not one long chain — and
  filings on different exchanges can still join the same group.
- **Siblings must be alive at the filing date (§8.6, D16 matching).** A
  sibling security only competes for a Form 25 match while it was alive
  around that filing's date (its own first/last sighting, widened by 30
  days before and 400 days after); a sibling with no sightings at all is
  always treated as alive, since its span is unknown.
- **Class-text reading (§8.6, class matching).** The Form 25 class text is
  read for units, equity units, purchase contracts, warrants (including
  "Common Stock Purchase Warrants"), capital securities, ADSs and bare
  "Preference Shares" — misreading any of these as common stock was fixed
  during the build. `class_label` skips over a segment that names an
  *attached* security (a rights-plan clause, or "PREFERRED"/"PREFERENCE"
  when the text is actually common) rather than always cutting at the
  first comma, so a class letter isn't picked up from the wrong clause.
- **Nasdaq halt feed failures don't abort (§9).** A halt-feed request that
  fails (network error, repeated 429/5xx) is logged and treated as "no
  halt" rather than raised — it's a confirmation source, not one of the
  required SEC sources, so a run should not fail over it.
- **`-W` ticker suffix (§8.3, sideline filtering).** Read as the US warrant
  suffix, not folded into the when-issued check — a warrant line is
  filtered out by `security_kind`/class matching instead, so dropping it in
  the when-issued check would have hidden a real security-type distinction.
- **Acquirer pricing keyed by the merger event (§8.9).** The acquirer's
  price is looked up keyed on the specific `(sec_id, delist_date)` merger —
  the only way to price the acquirer as of that merger's own completion
  date, since one acquirer ticker can price several targets on different
  dates.
- **Ticker spellings (§6.1, §7.2).** Fails-to-deliver rows written without
  a separator ("BFB") are keyed by the observed separator spelling ("BF-B"),
  also when the caller observed the bare spelling too (the index snapshots
  write both). A security's `ticker_history` uses one spelling per ticker: a
  spelling it was observed under, the separator form first — Hubbell's
  merged class keeps "HUBB", its class B (seen as "HUB-B" and "HUBB") is
  "HUB-B", and Viacom class B is "VIA-B" also for its Nasdaq years as VIAB.
- **The fails description must name the issuer (D21, §8.3).** An era takes
  an FTD CUSIP only when some fails row of that CUSIP has a description that
  names the era's company: its observed names or its issuer's EDGAR names,
  current and former (`names.description_matches`). The match is looser than
  the name check elsewhere, because SEC cuts descriptions at 30 characters,
  abbreviates (GEN ELEC, MATLS, HLDGS) and keeps an old name for years after a
  rename; it only has to tell another company on the same ticker from the
  company itself. So a snapshot that kept listing a company after it was gone
  no longer takes the next holder's CUSIP and FIGI (Clear Channel under CCU
  in 2009 is not Cervecerias Unidas, Station Casinos is not Stantec,
  ServiceMaster is not Silvercorp, Avaya is not Aviva, Northeast Utilities
  under ES in 2012 is not EnergySolutions); it resolves by ticker or name,
  or to its placeholder. An era with no issuer CIK also takes a CUSIP that an
  era with a known issuer took as that issuer's (CME's 2008 snapshots still
  say CHICAGO MERCANTILE HLDGS). Where a description is only a brand
  (FANNIE MAE, FREDDIE MAC) or an old name with no issuer CIK to explain it
  (AMERCO for UHALB), the caller supplies the CUSIP on the observation:
  `data/observations.csv` carries it for FNM, FRE and UHALB. The era's last
  sighting (`era_last_seen`, used only to date the issuer lookup) still counts
  the ticker's rows of its FTD CUSIPs before this check.
- **A security's CUSIPs (§7.3, §8.8).** Every CUSIP of an era whose OpenFIGI
  answer is accepted as the security's composite is kept (up to 3 tried per
  era, no extra requests); for a `sec_id` pin or a placeholder, where there is
  no composite to check against, the era's first candidate CUSIP is kept
  unchecked.
- **`securities.name` (§7.1).** The latest observation name of the
  security, not the OpenFIGI name; the OpenFIGI name is used only when no
  observation carries a name.
- **`listed_today` is asked live (§8.10, §11).** The completeness check's
  OpenFIGI lookup is not cached, so runs on different days over the same
  caches can differ where a listing changed in between.
- **`listed_today` needs EDGAR too when the CIK is known (§8.10).** OpenFIGI
  keeps exchange-venue rows for a dead composite FIGI (Celgene, TSS, old
  Apache still show UW/UN), so with the issuer's CIK known a security is
  listed today only when OpenFIGI shows a venue and the issuer's EDGAR
  submissions JSON lists one of the security's observed tickers, or the
  ticker OpenFIGI returns, on a major exchange. With no CIK, OpenFIGI alone
  decides; a placeholder is listed when EDGAR lists one of its own tickers
  on a major exchange.
- **`sec_id` pins are not name-checked (§5 "Pin", §8.3).** A `sec_id` pin is
  taken as given; only a `cik` pin gets the `member_name_mismatch` check.
- **No share-class rejection in FIGI acceptance (§8.3).** A candidate of a
  different share class is not rejected; the class-letter era split and the
  CUSIP-first order keep most classes apart.
- **SEC fair access across processes (§9, §11).** The 8 requests/s cap holds for
  the machine, not just the process: every SEC request takes an `flock`-guarded
  lock file outside the repo (`~/.cache/delist_detection/sec_rate.lock`, or
  `$DELIST_DETECTION_SEC_RATE_LOCK`) that holds the last start time, and waits
  1/8 s past it. `classify_universe.py --sec-workers N` (default 4, at most 8)
  prefetches on N threads under that one limit, and a 5xx pauses them all.
- **Determinism includes the run date (§11).** Every freshness rule reads one
  run date (`as_of`), so "same inputs and caches" means the same caches and the
  same `as_of` (`classify_universe.py --as-of`, default today). For those, the
  tables are byte-identical for any `--sec-workers`:
  prefetch threads only fill missing cache entries and never refresh one.
  `run_manifest.json` records `as_of`, the code version, the worker count and
  the SEC traffic.
- **Search answers held by age (§9).** A full-text-search answer holds
  `max(7, min(365, fetch date − window end))` days, and a window ending before
  2001 is never sent (EDGAR's index starts in 2001). A company-name-search
  answer holds 7 days. A 400/404 from full-text search is a rejected query, not
  an empty answer.
- **Degraded answers are reviewable (§11 "no silent drop").** An era, security,
  payout or successor search whose answer rested on a failed SEC request or a
  stale copy gets a `resolution_degraded` review row; its answer is used for
  the run but never saved, and the CLI exits 3.
- **An OpenFIGI outage is not a refusal (§9, §10).** Timeouts, connection
  errors or 5xx answers that outlast the OpenFIGI client's retries raise
  `OpenFigiUnavailable`, apart from a 401/403 refusal (`OpenFigiBlocked`,
  exit 2). The run stops before writing any table, so the previous outputs stay
  whole; nothing is cached, and no placeholder stands in (it would change
  `sec_id`s between runs). The CLI says "OpenFIGI unavailable after retries; no
  outputs written; rerun later" and exits 1.
- **`no_figi` is not in `review.csv` (D19, §7.5, §8.3).** The spec puts a
  placeholder into `review.csv` flagged `no_figi`. Review triage (requested
  later) grades `no_figi` `info`: the placeholder is a stable, joinable key and
  nothing suggests it is wrong, so a row whose flags are all `info` leaves
  `review.csv`. Placeholders are not lost: `securities.csv` lists every one
  (`figi_source=placeholder`) and `review_summary.csv` counts the `no_figi`
  rows. Unlike a delisting row's `info` flags, which stay on `delistings.csv`,
  `no_figi` belongs to a security, not a delisting, so it appears on no other
  table.

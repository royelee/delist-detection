# Security Master and Delisting Table — Design

*Spec · 2026-09-22 · status: draft, design interview in progress (see "Open questions")*

## Overview

Refactor the library so it builds two things from the pipeline in the design page
[Handling delisted symbols, from universe to training data](https://claude.ai/artifact/7fBt5ZVbrGMP8kFtkCWzTp):

- **Step 1, the security master:** a permanent ID per security, its ticker history
  and CUSIP history.
- **Step 3, the delisting table:** one row per delisting, with why it happened and
  what a holder received.

Step 2 (point-in-time membership) stays with the caller. The library assumes no
index: the caller says which securities it cares about by sending observations.
The tables are stored as CSV files, not DuckDB, for now.

Terms used here (security, issuer, listing, delisting, bucket, successor,
observation, pin, universe) are defined in [`CONTEXT.md`](../../../CONTEXT.md).

A companion refactor of `qlib_practice` is required. What it has to change is at
the end of this spec.

## Decisions

Each decision was made by the user during the design interview on 2026-09-22.

**D1. Scope is steps 1 and 3.** Membership (step 2) stays with the caller. The
library does not assume the Russell 1000 or any other index. The iShares and
Wikipedia downloaders only served membership, so they stay in `qlib_practice`.

**D2. The library is self-contained.** It downloads its own inputs instead of
reading files another repo fetched. Today that is EDGAR; this design adds
OpenFIGI and three SEC/exchange data sets (D20): the fails-to-deliver files,
MIDAS, and Nasdaq's halt feed. No vendor key is needed (D20, D22).

**D3. The input is observations.** Each row says a ticker was seen on a date:
`ticker, as_of`, plus optional `name`, `cusip`, `cik`, `sec_id`. The caller builds
them from whatever defines its universe (index snapshots, an instruments file, a
screen). The library builds a security for every observation and classifies
every delisting of those securities.

**D4. `sec_id` is the US composite FIGI** from OpenFIGI. Only the US market is in
scope. All US venues of a security share one composite FIGI, so an exchange move
keeps the ID. See "Evidence" for how OpenFIGI behaves on renames, reorgs and
delisted securities.

**D5. The delisting definition and buckets do not change.** They stay as in
`README.md` ("What you get" and the CRSP DLSTCD table): `merger` (200, 231, 233),
`exchange_transfer` (300s), `liquidation` (400, 470), `compliance_failure`
(570, 573, 580), `expiration` (600), `active` (100), with the same train-label
and backtest-exit policies. Two consequences of keying on `sec_id`:
- A security can have more than one delisting (an exchange transfer, later a
  merger).
- A rename is not a delisting. It files no Form 25 and only adds a
  `ticker_history` row. (Today's code 304 for a rename exists only because the
  vendor's old-ticker series ended.)

**D6. Delistings are found from EDGAR Form 25.** Every Form 25 or 25-NSE that
removes the security's class from an exchange is a delisting. It takes effect 10
days after filing. Where no Form 25 exists (before 2002, SPAC trust liquidations,
revocations), the classifier's existing fallback paths (8-K 2.01 completion,
Form 15, `REVOKED`) find and date it. The caller no longer supplies an end date.

**D7. `ticker_history` comes from EDGAR**, as the resolver and classifier already
use it (cover-page trading symbols, XBRL `dei:TradingSymbol` since 2019, Form 25
dates). OpenFIGI only reports a security's latest ticker, so it cannot supply
history.

**D8. `delistings.csv` replaces `dlret.csv`.** Key: `(sec_id, delist_date)`.
`delist_date` is the Form 25 effective date, or the fallback filing's date when no
Form 25 exists. `last_trade_date` is a separate column. The file keeps a `ticker`
column (the ticker on the delist date). `payouts.csv` and `review.csv` stay.

**D9. Storage is CSV in `output/`, committed** like today's outputs. One CSV per
table, fixed column order, ISO dates, empty cell for NULL, rows sorted by key.
One module owns the column schemas, so a later move to DuckDB changes only that
module. Nothing is minted (FIGI is external), so every run can rebuild all tables.

**D10. Date ranges include their end date.** An empty end means still open. At a
change, the old row ends the calendar day before the new row starts (FB ends
2022-06-08, META starts 2022-06-09).

**D11. `security_events` is dropped.** `delistings` carries `successor_sec_id`,
which is all the `exchange_transfer` "hold successor" rule needs. Spin-off and
new-share-class links can return as a table when a price step needs them.

**D12. Identity pins travel on observations.** An observation may carry a `cik` or
`sec_id`. A pin beats every resolver tier (as `--cik-map` does today) and still
gets the name check. `--names` and `--cik-map` go away. `MANUAL_OVERRIDES` stays
as the library's own fixes.

**D13. Value overrides are keyed by `(sec_id, delist_date)`.** This applies to
`lt.csv`, `terms.csv` and `rec.csv`. A blank date applies the row to every
delisting of that security.

**D14. The handling code matches on `sec_id` only.** `handling.py`,
`bmp_correction.py` and `qlib_adapter.py` join delistings to panels by `sec_id`.
A ticker-named panel must be renamed to FIGIs before it can use them.

**D15. `securities` has no `first_date` column.** A security's first date is the
earliest `valid_from` in its `ticker_history`.

**D16. A Form 25 is matched to one security by its class text.** A Form 25 names
no ticker or CUSIP, only the issuer and a free-text class (`descriptionClassSecurity`:
Aetna's 2018 25-NSE says "Common Stock"; Discovery's three 2022 25-NSEs say
"Series A/B/C Common Stock"). Matching runs in order:
1. Set aside a Form 25 whose class is a kind the issuer's observed securities are
   not (preferred, notes, warrants, units, rights).
2. If the issuer has exactly one observed security of that kind, it gets the row.
3. Otherwise match the class letter or series ("Series A", "Class C") to each
   security's share class (from OpenFIGI's name, e.g. `DISCOVERY INC-A`, and
   EDGAR's ticker list).
A Form 25 that still matches zero or several securities creates no row and goes
to `review.csv`.

**D17. Withdrawing a secondary listing is not a delisting.** A Form 25 counts only
when the security has no exchange listing left afterwards (it left the
exchanges) or it moved to a new one (`exchange_transfer`). The library tells
these apart from the exchanges the issuer names for that class on its 10-K cover
pages before and after the Form 25 (XBRL `dei:SecurityExchangeName` since 2019,
cover-page text before). These withdrawals are common: EDGAR full-text search
finds issuer Form 25s naming the Chicago Stock Exchange (74), the Pacific
Exchange (83) and NYSE Arca (271), e.g. Apache on 2020-06-08 (Chicago; stayed on
NYSE until the 2021 APA reorg) and Toll Brothers on 2007-01-10 (Pacific; stayed
on NYSE). CRSP tracks only a security's main exchange and records none of them.

**D18. Securities a delisting points to are included even if unobserved.** A
successor (`successor_sec_id`) or a US-listed stock-deal acquirer
(`acquirer_sec_id`) gets a `securities.csv` row and its `ticker_history`, with
`observed = false`. The library does not search for their own delistings, so
the work stays bounded by the caller's universe. A foreign acquirer (e.g. Natura
for Avon) is outside the US scope and keeps only `acquirer_ticker`. Successors
after a FIGI change are found from the successor issuer's 8-K12B (Alphabet
2015-10-02, `0001193125-15-336577`; APA Corp 2021-03-01,
`0001193125-21-063695`) instead of today's hand-written `successor_map`.

**D19. A security with no confirmed FIGI gets a placeholder `sec_id`** built from
its issuer's CIK and class, e.g. `CIK1122304-COMMON`. It can never be mistaken for
a FIGI (FIGIs start with `BBG`). The security and its delistings still appear,
flagged `no_figi` in `review.csv`. A later pin or lookup that finds the FIGI
replaces the placeholder, so that security's ID changes once. Dropping these
instead would remove delistings from `delistings.csv` in an unpinned run and
bring back survivorship bias. A security with neither a FIGI nor a CIK gets no
row and goes to `review.csv`.

The coverage check suggests truly missing FIGIs are rare: every "unresolved" row
re-queried had a FIGI that Bloomberg had renamed after the deal (QCOR →
`MALLINCKRODT ARD LLC` `BBG000BPVCR1`; PMCS → `MICROSEMI STORAGE SOLUTIONS`
`BBG000BBSX81`; IRF → `INFINEON TECHNOLOGIES AMERIC` `BBG000BM6KM3`; AOL →
`YAHOO INC/US` `BBG000DHNDK1`; JOY → `KOMATSU MINING CORP` `BBG000K14Q84`;
SCTY → via CUSIP `83416T100`, `TESLA ENERGY OPERATIONS INC` `BBG001BPFT54`).
Proposed resolution order (engineering, open to review): ticker lookup with no
exchCode and `includeUnlistedEquities`; then CUSIP when one is known; then name
filter. A hit is accepted only when a check that does not depend on today's
Bloomberg name passes: the CUSIP matches, a per-venue row keeps the original
name, or the name matches the acquirer or successor named in the delisting 8-K.

**D20. Last trade date and closes come from SEC data only; no vendor key.**
- `last_trade_date` comes from the exchange's EX-99.25 notice on the Form 25-NSE,
  or from the closing 8-K's Item 3.01 text when the notice has no date (Nasdaq
  mergers). The wording is interpreted ("suspended on D" in an NYSE merger
  notice means D was the first day without trading), then checked against SEC
  MIDAS (2012 onward) and Nasdaq's halt feed (halt code D).
- `last_trade_close` and the acquirer's close come from the SEC fails-to-deliver
  files (2004 onward), whose row dated D carries the close of D−1.
- Where no fails row exists, or the delisting predates 2004, the caller's
  `lt.csv` override fills it; otherwise the row keeps a blank `dlret`
  (`needs_last_trade`) and goes to `review.csv`.
Tiingo is not used: its last row is often a zero-volume filler (274 of 461
series), matching the true last trading day in only 14 of 45 checked events. The
fails-to-deliver close matched Tiingo in 40 of the 42 sampled delistings that had
a row. Evidence: [`docs/research/last-trade-date-sources.md`](../../research/last-trade-date-sources.md).

**D21. `cusip_history` comes from the SEC fails-to-deliver files** the library
already downloads for closes (D20). Each row carries a date, CUSIP, symbol and
description. A security's CUSIP on date D is the one on rows whose symbol matches
its `ticker_history` ticker on D and whose description matches the issuer name;
a CUSIP change shows up as a new CUSIP on later rows. A CUSIP the caller puts on
an observation is checked against these rows. Coverage starts in 2004; a security
with no fails for a long stretch has gaps. OpenFIGI never returns CUSIPs.

**D22. Alpha Vantage is dropped.** Its four uses in `scripts/classify_universe.py`
move to sources this design already reads:
- resolver name fallback and name hint → observation names, checked against
  EDGAR names;
- asset type for the `expiration` short-circuit → the class the Form 25 names
  ("Notes", "Warrants", "Units", "Rights"), OpenFIGI's `securityType`, and the
  existing name keyword check;
- exchange for the Shumway constants → the exchange named on the Form 25 (e.g.
  `NEW YORK STOCK EXCHANGE LLC` on Aetna's).
AV's names caused the HOT, NFS, PAS, PE and TSS misclassifications, and its
`delistingDate` copies Tiingo's last row, so it adds no independent evidence.
`AV_LISTING_CSV`, `AV_ACTIVE_CSV` and `av_listing.py` go away.

**D23. `vendor_xref` is dropped.** `sec_id` is the FIGI, the CIK is on
`securities`, CUSIPs are in `cusip_history` and tickers in `ticker_history`, and
the library talks to no price vendor (D20). A caller maps its own vendor series
to `sec_id` through `ticker_history.csv`. The table can return when the price
step (step 4) is designed. With D20 and D22, `raw_tiingo.py` and
`--raw-tiingo-dir` also go away: the LLM merger path gets the acquirer's close
from the fails-to-deliver files, after resolving `acquirer_ticker` to
`acquirer_sec_id` (D18).

## Tables

All files live in `output/`. Columns marked *(open)* depend on an open question.

| File | Key | Columns |
|---|---|---|
| `securities.csv` | `sec_id` | `sec_id`, `issuer_cik`, `share_class`, `name`, `observed` (D18), `security_type` (OpenFIGI, D22) |
| `ticker_history.csv` | `sec_id, valid_from` | `sec_id`, `ticker`, `exchange`, `valid_from`, `valid_to` |
| `cusip_history.csv` | `sec_id, valid_from` | `sec_id`, `cusip`, `valid_from`, `valid_to` (D21) |
| `delistings.csv` | `sec_id, delist_date` | see below |
| `payouts.csv` | `sec_id, delist_date` | as today, re-keyed (A6) |
| `review.csv` | `sec_id, delist_date` | as today, re-keyed (A6) |

`delistings.csv` draft columns: today's `dlret.csv` columns (`ticker`, `bucket`,
`crsp_code`, `dlret`, `reason`, `exchange`, `last_trade_close`,
`payout_per_share`, `stock_ratio`, `acquirer_price`, `acquirer_ticker`,
`recovery_ratio`, `terminal_value`, `dlret_method`, `dlret_confidence`,
`payout_source`, `review_flags`), plus `sec_id`, `delist_date`, `cik`,
`confidence`, `successor_sec_id`, `acquirer_sec_id`, `last_trade_date` (D20),
and the evidence columns from today's
`delist_classifications.csv` (`delist_filing_form`, `delist_filing_date`,
`anchor_8k_items`, `dereg_form`, `resolved_name`, `resolution_source`, and the
raw payout before the last-close gate) (A1).

Observation input columns: `ticker`, `as_of`, `name`, `cusip`, `cik`, `sec_id`.
Only `ticker` and `as_of` are required.

## Pipeline

```
observations (ticker, as_of, name?, cusip?, cik?, sec_id?)
   │
   ├─ resolve issuer CIK per (ticker, as_of)      existing TickerResolver; cik pin wins
   ├─ resolve US composite FIGI                   OpenFIGI; sec_id pin wins   (O2, O3)
   ├─ build ticker_history from EDGAR             D7
   │
   ├─ find delistings per security from EDGAR     Form 25 / 25-NSE, else fallback paths (D6)
   ├─ classify each delisting                     existing DelistClassifier → CRSP code + bucket
   ├─ last trade date, last close, acquirer close (O1)
   ├─ payout / terms extraction + last-close gate existing extractors
   │
   └─ write output/*.csv                          D8, D9
```

## Assumptions to confirm

These follow from the answers but were not stated outright.

- **A1.** `delist_classifications.csv` goes away along with `dlret.csv`; its
  evidence columns move into `delistings.csv`.
- **A2.** An override row that matches no delisting stops the run instead of being
  skipped.
- **A3.** The handling functions lose their dictionary arguments (`payouts`,
  `successor_map`, `exchanges`, `last_trade_closes`, `recovery_ratios`), because
  each delisting row carries those values.
- **A4.** `securities` also has no `last_date` or `end_reason`. A delisting row
  records how a security ended; `end_reason` only served minted IDs, which FIGI
  removes.
- **A5.** A caller's old `(ticker, start, end)` file can still be used by turning
  each row into two observations, on the start and end dates.
- **A6.** `payouts.csv` and `review.csv` are keyed by `(sec_id, delist_date)` like
  `delistings.csv`.

## Open questions

- **O1.** *(Resolved as D20.)* **Where do `last_trade_date`, the last close and
  the acquirer's close come from?** EDGAR gives the Form 25 date, not the last trading day or any price.
  Options so far: download just the needed closes from Tiingo's end-of-day
  endpoint (needs a key), or keep taking them from the caller. Research:
  [`docs/research/last-trade-date-sources.md`](../../research/last-trade-date-sources.md).
  Key findings there: the exchange's EX-99.25 notice on Form 25-NSE states a
  suspension date for NYSE-family and Cboe delistings (86 of 89 sampled) but not
  for Nasdaq mergers; the closing 8-K's Item 3.01 gives a date in 256 of 363
  cached filings; SEC MIDAS (2012+, volume only) and Nasdaq's keyless halt feed
  confirm the last exchange-trade day; SEC fails-to-deliver files (2004+) carry
  prior-day closes by CUSIP (42 of 45 sampled delistings covered, 40 matching
  Tiingo), including acquirer closes. Tiingo's own last date is often a
  zero-volume filler row (274 of 461 series), matching the true last trading day
  in only 14 of 45 checked events.
- **O2. How does an observation resolve to a FIGI, and what happens when it
  can't?** OpenFIGI's ticker lookup takes no date and returns today's holder;
  delisted securities appear only with `includeUnlistedEquities` and under
  Bloomberg's last ticker; CUSIP lookups work. Coverage on the 461 delisted
  tickers: 86% by ticker alone (no exchCode), 92% with every route, and name
  search can pick the wrong line of the right issuer (see Evidence). *(Resolved
  as D19: placeholder IDs, with a proposed resolution order and acceptance
  checks.)*
- **O3.** *(Resolved as D21.)* **Where do CUSIPs come from?** Needed if CUSIP is the reliable route to a
  FIGI. Candidates: the observation itself, EDGAR filings that print a CUSIP
  (e.g. Schedule 13D/13G cover pages), fund holdings (N-PORT), the SEC 13(f)
  securities list.
- **O4.** *(Resolved as D22.)* **Is Alpha Vantage still needed?** Its jobs could move elsewhere: names to
  observations, asset type to OpenFIGI's `securityType`, exchange to the Form 25
  filer. Securities OpenFIGI cannot resolve would have no security type.
- **O5.** *(Resolved as D23: dropped.)*
- **O6.** *(Resolved as D16.)*
- **O7.** *(Resolved.)* The OpenFIGI key is in `.env` as `OPEN_FIGI_API_KEY`
  (header `X-OPENFIGI-APIKEY`); with it mapping allows 250 requests per 60 s.
- **Q23 / completeness** *(default taken)*: an observed security that is neither
  listed today nor delisted goes to `review.csv` as `ended_without_delisting`; no
  `delistings.csv` row. The interview ended here; the implementation spec is
  [`../feature-spec.md`](../feature-spec.md).

Not changed by this spec: the bucket handling policies (D5), and the consumer's
own training marks (see the `qlib_practice` section).

## Evidence

### OpenFIGI (live API, `api.openfigi.com/v3/mapping`, 2026-09-22, no key)

| Query | Result | What it shows |
|---|---|---|
| TICKER `GOOG`, exchCode US | `BBG009S3NB30`, ALPHABET INC-CL C | |
| TICKER `GOOGL`, exchCode US | `BBG009S39JX6`, ALPHABET INC-CL A | |
| CUSIP `30303M102` (Facebook) | composite `BBG000MM2P62`, ticker META | A rename keeps the FIGI |
| TICKER `FB`, exchCode US | `BBG01VRMNFB1`, a ProShares ETP | Ticker lookup has no date; returns today's holder |
| TICKER `AET` | no result | Delisted securities are hidden by default |
| TICKER `AET`, `includeUnlistedEquities` | `BBG000FJLFX8`, AETNA INC (US) | The flag reaches them |
| CUSIP `00817Y108` (Aetna), unlisted | German-venue rows first (`BBG000FGJDG1`) | CUSIP results span countries; filter to US |
| CUSIP `524908100` (Lehman), unlisted | `BBG000BKRK35`, ticker `LEHMQ` | Same FIGI after the move to OTC; stored under the last ticker |
| TICKER `LEH`, unlisted | no result | Lookup by the original ticker fails |
| CUSIP `38259P508` (Google Inc A), unlisted | `BBG000BHSKN9`, ticker `8888000D` | The 2015 holdco reorg got a new FIGI (vs GOOGL `BBG009S39JX6`) |
| TICKER `DOW`, exchCode US | `BBG00BN96922`, DOW INC only | A recycled ticker returns one holder |
| `/v3/search` by company name | options contracts; non-JSON by the third query | Search is not a usable resolver without a key |

Consequence for D5: a FIGI does not end when a stock leaves an exchange (Lehman),
so "delisting" is defined by Form 25, not by the FIGI ending.

### OpenFIGI coverage of the 461 delisted tickers (2026-09-22, no key)

Measured against `output/delist_classifications.csv`, name-checked against the
EDGAR name; raw responses and scripts in `/tmp/claude-501/figi/` (not kept).

| Route | Resolved | Notes |
|---|---|---|
| TICKER, exchCode US, `includeUnlistedEquities` | 355 (77.0%); 370 (80.3%) counting EDGAR former names | The US row often shows Bloomberg's current ticker/name (renamed to the acquirer, e.g. COL → "COLLINS AEROSPACE") or a later holder (NFX → an ETF) |
| TICKER, no exchCode | 397 (86.1%) | Per-venue rows (UN, UW, UA…) keep the original ticker and name and point to the composite; contains every match of the row above |
| + `/v3/filter` on the name (legal suffixes stripped, unlisted) | 417 (90.5%) | Of 58 name matches, 14 were the wrong line of the same issuer (other class, "-OLD" predecessor, post-bankruptcy successor) and 11 only when-issued/144A lines |
| CUSIP (2017+ rows with a CUSIP from the 13F map or IWB file; ID_CINS for foreign "G" codes) | 260 of 330 (78.8%) | Agrees with the ticker route on 216 of 223; 90.6% of CUSIP hits show the original ticker |
| All routes combined | 425 (92.2%) | Unresolved include slash classes (BF/A), bankruptcy Q tickers, and SCTY (nothing by any route) |

Failures cluster in `exchange_transfer` (31% unresolved after ticker + filter)
and `expiration` (53%, where only Alpha Vantage names were available). A ticker
returning two US composites was rare (ANAT, PLL). Rate limits without a key:
mapping 25 requests/60 s (10 jobs each; 461 lookups took 67 s); filter and search
share 5 requests/60 s and mapping calls draw on that budget too (113 filter calls
took about 24 minutes).

### Errors in the current output found by the coverage check

Checked against `output/delist_classifications.csv`; each is a recycled ticker
whose delist date belongs to a later holder while the CIK or name belongs to an
earlier one:
- MON 2022-12-23 has Monsanto's CIK (acquired 2018); the ticker then belonged to
  Monument Circle Acquisition.
- THOR 2020-01-23 has Thoratec's CIK (acquired 2015); the ticker then belonged to
  Synthorx.
- STR 2025-08-18 has Questar's CIK (acquired 2016); the ticker then belonged to
  Sitio Royalties.
- THRX 2024-02-14 (manual override) has Theravance/Innoviva's CIK; the ticker then
  belonged to Theseus Pharmaceuticals.
- KWK 2015-01-16 (manual override) has T-Mobile US's CIK (1283699); KWK was
  Quicksilver Resources.
- HOT, NFS, PAS, PE, TSS are classified `expiration` from an Alpha Vantage ETF
  name, but on those dates the tickers were Starwood, Nationwide Financial,
  PepsiAmericas, Parsley Energy and TSYS.

Under this design these come from observations carrying their own dates and
names, and each delisting is found from the observed security's own Form 25.

### Tiingo fundamentals meta (`qlib_practice/fetch_data_aplha/data/tiingo_fundamentals/meta_*.json`)

`permaTicker` is one record per company, not per share class (GOOGL but no GOOG;
FOXA but no FOX; BF-B but no BF-A; LBRDA but no LBRDK; no BRK-A), lacks some dead
companies (old Dow Chemical CIK 29915, Google Inc CIK 1288776), and is
inconsistent across renames (FB→META one record; SKLZ and FIRY two records
sharing `dataProviderPermaTicker` 110037). This is why it was not used as
`sec_id`.

## Changes in this repo (for the implementation plan)

- New observation input for `scripts/classify_universe.py`; drop `--names` and
  `--cik-map`; keep `--last-trade-closes`, `--merger-terms`, `--recoveries` as
  overrides re-keyed per D13.
- New OpenFIGI client with an on-disk cache and throttling, like `EdgarClient`.
  Tests stay offline with saved responses.
- New Form 25 scan per security (D6), matched to the security's class (O6).
- `ticker_history` builder from EDGAR (D7).
- `DelistRecord` and `EnrichedDelistRecord` gain `sec_id` and `delist_date`.
- Handling layer matches on `sec_id` (D14).
- The golden regression set (`tests/fixtures/golden/`, `data/golden_events.csv`)
  is keyed by ticker and must be re-keyed.
- Docs to update: `CLAUDE.md` (it says the library uses only EDGAR data and takes
  any `(ticker, start, end)` file), `README.md`, `docs/data-flow.md`.

## `qlib_practice` refactor

Facts below come from a survey of `/Users/royeli/repo/github.com/qlib_practice` on
2026-09-22.

**How it uses this library today.**
- `build-dlret` (`fetch_data_aplha/cli.py:1392`) runs
  `fetch_data_aplha/src/av2qlib/delist_returns.py`, which calls this library's
  `scripts/classify_universe.py` as a subprocess. The library is pinned by commit
  SHA in `fetch_data_aplha/pyproject.toml`. Committed copies of the outputs live in
  `data/delist/`.
- `dlret.csv` readers: `scripts/inject_delist_labels_dlret.py` (training labels,
  with its own harsh marks of −1.0 for `compliance_failure` and −0.90 for
  `liquidation`), `scripts/knob_sweep/extend_labels.py`,
  `scripts/apply_delist_exits.py` (called from `model/pred.py:1507`),
  `scripts/audit_delist_exits_dlret.py`.
- Imports of `qlib_adapter` / `handling`: `scripts/audit_delist_exits.py`,
  `scripts/inject_delist_labels_lib.py` (reads `delist_classifications.csv` and
  `payouts.csv`).
- Workflows that run `build-dlret` then label injection:
  `.claude/workflows/e2e-delist-pipeline.js`, `.claude/workflows/refresh-to-date.js`.
- The unmerged branch `feat/universe-identity` (worktree
  `.worktrees/universe-identity`) builds `universe_identity.csv` (ticker × era →
  CIK) and writes the `--cik-map` this library reads.

**What it has to change.**
1. Build observations from its universe source (the iShares and Wikipedia
   snapshots already give `ticker, as_of, name`) instead of `delisted_tickers.tsv`.
   Pass its reviewed CIKs as observation pins instead of `--cik-map` (D3, D12).
2. Rename panel instruments from tickers to `sec_id` (FIGI), using
   `output/ticker_history.csv` to map each ticker on each date. This must happen
   before it moves the pin, because the handling code matches on `sec_id` only
   (D14). This touches the qlib instruments files and feature bins (step 4).
3. Key membership (step 2, e.g. `russell_historical.tsv`) on `sec_id`, and end
   each membership interval at the security's delisting.
4. Switch every reader of `dlret.csv` and `delist_classifications.csv` to
   `delistings.csv`, keyed by `(sec_id, delist_date)` (D8).
5. Re-key the override files it passes (e.g. `last_trade_closes.csv`) to
   `(sec_id, delist_date)` (D13).
6. Decide what happens to `feat/universe-identity`. Its ticker→CIK resolution
   overlaps this library's resolver; under D12 its output becomes a source of
   observation pins.
7. Its harsh training marks are its own policy and are not changed by this spec.
8. Move the SHA pin last, once 1–5 are done.

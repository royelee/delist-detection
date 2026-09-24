# Data flow

How an observation travels through `delist_detection`, from `(ticker, as_of)`
to an identified security, its ticker/CUSIP history, and every delisting it
had, with deterministic train and backtest handling on top. See `CONTEXT.md`
for the vocabulary (security, era, sighting, pin, …) these names assume.

## Inputs

| Source | Path | Role |
|---|---|---|
| Observations (required) | the caller's CSV (`ticker, as_of[, name, cusip, cik, sec_id]`) | The library's only view of the caller's universe. `cik`/`sec_id` are **pins**: they win resolution but are still name-checked. |
| SEC EDGAR | `data.sec.gov/submissions/CIK########.json`, `efts.sec.gov/LATEST/search-index`, filing documents | Form 25/8-K/15/8-K12B lists and text — ground truth for issuer identity, delisting evidence and classification. |
| OpenFIGI | `api.openfigi.com/v3/mapping`, `/v3/filter` | Resolves each observed security to its US composite FIGI (`sec_id`) and security type. |
| SEC fails-to-deliver | `www.sec.gov/data-research/sec-markets-data/fails-deliver-data` (2004+) | Last-trade and acquirer closes; CUSIP↔ticker history. |
| SEC MIDAS | `www.sec.gov/opa/data/market-structure/…` (2012+) | Confirms the last day with exchange volume. |
| Nasdaq halt feed | `www.nasdaqtrader.com/rss.aspx?feed=tradehalts` | A code-`D` ("security deletion") halt as a second last-trade-date confirmation. |

No price vendor, no Alpha Vantage: every date and price is SEC- or
OpenFIGI-sourced. Two helper scripts build an observations CSV from what a
caller likely already has: `observations_from_instruments.py` (an old
`(ticker, start, end)` file → two observations per row) and
`observations_from_snapshots.py` (a folder of dated index-membership CSVs →
one observation per row per file).

## Pipeline

```
              ┌────────────────────────────┐
              │  observations.csv          │   ticker, as_of[, name, cusip, cik, sec_id]
              └─────────────┬──────────────┘
                             │ ObservationIndex.eras()
                             ▼
              ┌────────────────────────────┐
              │  stage 1: TickerEra per    │   splits on pin change / name mismatch /
              │  (ticker, observations)    │   class-letter change; a gap alone never splits
              └─────────────┬──────────────┘
                             │ FtdIndex.load (era tickers' fails-to-deliver rows)
                             ▼
              ┌────────────────────────────┐
              │  stage 2: refine_eras      │   splits again on the ticker's FTD rows: a
              │                            │   CUSIP switch (runs of ≥ 3 rows), or a gap
              │                            │   > ERA_GAP_DAYS in observation + FTD dates
              └─────────────┬──────────────┘
                             │
                             ▼
              ┌────────────────────────────┐
              │  era_last_seen, era_cusips │   FTD-confirmed true last sighting + CUSIPs
              └─────────────┬──────────────┘
                             │ TickerResolver.resolve (era ticker, era_last_seen)
                             ▼
              ┌────────────────────────────┐
              │  TickerResolver: era → CIK │   1. cik pin  2. manual override
              │  6 strategies, precision   │   3. company_tickers.json  4. EFTS Form-25/15
              │  order, strict-validated   │   5. era name → EDGAR company search
              │                            │   6. EFTS 8-K frequency rank
              └─────────────┬──────────────┘
                             │ FigiResolver.resolve_many (OpenFIGI, per era)
                             ▼
              ┌────────────────────────────┐
              │  FigiResolver: era → sec_id│   sec_id pin → CUSIP → ticker → name filter
              │  (US composite FIGI, or    │   → placeholder CIK<cik>-<CLASS>
              │  placeholder)              │
              └─────────────┬──────────────┘
                             │ build_securities (merge eras sharing a sec_id)
                             ▼
              ┌────────────────────────────┐
              │  securities.csv            │   one row per identified security
              └─────────────┬──────────────┘
                             │ DelistingFinder.find, per security's issuer CIK
                             ▼
              ┌────────────────────────────┐
              │  Form 25 scan (issuer's    │   list_form25, parse XML/text (exchange,
              │  whole filing history)     │   class_text, rule); regional exchanges and
              │                            │   unreadable/unclassified filings skipped
              └─────────────┬──────────────┘
                             │ match_security (class kind + letter) + secondary-
                             │ listing check (10-K cover exchanges before/after)
                             ▼
              ┌────────────────────────────┐
              │  matched Form 25s, grouped │   chained within SAME_EVENT_DAYS of the
              │  into one delisting each   │   group's earliest filing, across exchanges;
              │                            │   no match → classifier's no-Form-25 fallback
              └─────────────┬──────────────┘
                             │ last_trade.decide_last_trade (notice → 8-K → MIDAS
                             │ → Nasdaq halt) + DelistClassifier.classify_event
                             ▼
              ┌────────────────────────────┐
              │  DelistRecord per delisting│   sec_id, delist_date, crsp_code, bucket,
              │                            │   confidence, reason, evidence
              └─────────────┬──────────────┘
                             │ ftd.close_after (last-trade + acquirer closes),
                             │ payout_extractor / llm_merger_extractor, payout_gate
                             ▼
              ┌────────────────────────────┐
              │  enrich() → delistings.csv │   + payouts.csv, review.csv,
              │  (+ ticker_history.csv,    │     cusip_history.csv from
              │     cusip_history.csv)     │     ranges_from_sightings
              └─────────────┬──────────────┘
                             │ handling.py / bmp_correction.py / qlib_adapter.py
                             │ — all keyed on sec_id
        ┌────────────────────┴────────────────────┐
        ▼                                          ▼
┌────────────────┐                        ┌──────────────────────┐
│ Train pipeline  │                        │ Backtest pipeline    │
│  bucket policy  │                        │  bucket policy       │
│  → forward      │                        │  → exit_date,        │
│    return label │                        │    exit_price        │
└─────────────────┘                        └──────────────────────┘
```

## Caching

Every EDGAR JSON response is SHA1-keyed and cached in `cache/edgar/*.json`;
filing text in `cache/edgar/text/`, complete submissions in `cache/edgar/raw/`.
OpenFIGI responses are cached under `cache/openfigi/`, paced on the
`ratelimit-*` headers. SEC fails-to-deliver and MIDAS downloads live under
`cache/sec_data/ftd/` and `cache/sec_data/midas/` (MIDAS summarizes each
quarterly ZIP once into a small JSON and deletes the ZIP). The Nasdaq halt feed
caches one file per day under `cache/nasdaq_halts/`. Each EDGAR payload records
the day it was fetched (`__fetched__`; an older file is dated by its mtime). The
resolver's checks and the classifier read a company's submissions fresh as of
`min(observed + 45 days, as_of)` (`edgar.submissions_fresh_after`), where
`as_of` is the run date, read once per run and passed to every client. A copy
cached before a later Form 25 is therefore fetched again — except the delisting
finder's own Form 25 scan (`DelistingFinder.find`, via `EdgarClient.recent_filings`),
which reads a cached submissions copy with no freshness bound at all, warm-filled
or not; a submissions copy a warm thread fills carries no TTL of its own either.
That is a known gap in the finder, out of scope for this plan. `pipeline.default_clients`
is what gives every client the one shared `as_of`; a caller who builds `Clients` by
hand and leaves it unset gets clients that each default `as_of` to today's
wall-clock date independently, at whatever moment they run. The MIDAS and FTD
index pages (the list of published ZIPs) age by wall clock instead, not by
`as_of` (`sec_http.get_text`'s day-old check), since SEC republishes them on its
own schedule, unrelated to the run date. A stale index page served after a
failed refresh counts `SEC_STATS.degraded("stale_copy")`, like every other
stale-copy fallback. Every cache file is
written atomically and durably (a temp file, fsync, `os.replace`, fsync of the
directory), so a crash, Ctrl-C or power loss never leaves a torn file; a killed
writer's temp files are removed when the next client starts.

Search answers are evidence, cached with a TTL; a resolver decision is never
cached as a miss. EDGAR full-text search (`efts.sec.gov`: the resolver's Form 25
and 8-K frequency tiers, and the successor search) goes through
`EdgarClient.efts_search`. Every answer, hits or empty, is written with its
schema version, window end and fetch date, and holds for
`max(7, min(365, fetch date − window end))` days (`edgar.efts_ttl_days`). A
window ending before 2001 is not covered by EDGAR's index and is never sent. A
400 or 404 is a rejected query: logged, counted, never written, not a failure. A
5xx after retries, a transport error, a non-JSON body, or a 200 body that is not
a recognized search answer (no `hits.hits` — an EDGAR error page or maintenance
page served as JSON) raises and is never cached: a bad 200 must not be mistaken
for a real empty answer, which could hide a filing for up to a year. Each hit
keeps `_id` and only the `_source` fields the library reads
(`EFTS_SOURCE_KEYS`). The EDGAR company-name search caches every answer, empties
included, for 7 days, and is retried like every other SEC request. EDGAR's
answer, a no-match included, is always a complete ATOM `<feed>` document, so a
200 whose body is not one (an HTML error page, a truncated feed) is treated
like a 5xx and never cached; a 400/404 is a rejected query, not cached and not
a failure. When the search still fails, a cached hit list is served marked
stale; with nothing to fall back on, it raises instead of answering "no match".

The ticker→CIK memo lives at `cache/ticker_resolution.json` and is keyed by
`(ticker, observed_date)` so a recycled ticker resolves to the right issuer per
date. The file is versioned (`{"__version__": 3, "entries": …}`); versions 2 and
3 load, and a file before version 2 predates the date and name checks, so it is
ignored and replaced on the next save. Answers of a withdrawn rule
(`company_tickers_name_mismatch`, which let today's ticker-map holder beat a
name-mismatched EFTS candidate) are dropped on load and resolved again. Each
entry records the era name it was checked with, and a lookup with a different
name resolves again. Misses are never saved: each run re-derives them, with the
current code, from the cached search evidence. An answer reached while an EDGAR
request failed, or through a stale copy (a submissions JSON or a company-search
hit served after a failed refetch), is used for the run but never saved, and
`review.csv` flags it `resolution_degraded`. The pipeline writes the memo after
each resolving stage and on the way out of a run.

A connection error, a timeout, or a 5xx on a submissions fetch, a filing text
or raw fetch (`fetch_filing_text` and `fetch_filing_raw` are both retried the
same way), a full-text-search query, or a MIDAS/FTD ZIP download is retried up
to 3 attempts with 2s/4s backoff (`edgar.retry_request`, reused by
`sec_http.py`) before giving up; a 403/429 still raises `EdgarBlocked`
immediately, never retried, and a failure is never cached as an answer. A
MIDAS quarter that keeps failing to download, or whose ZIP SEC no longer
serves (a 404), is remembered in-memory (`MidasClient`) for the rest of the
run so later securities don't repeat the same download-and-retry cost, and
logs one WARNING and counts `midas_miss:<yq>` in `SEC_STATS` — once per
quarter per run, even though a warm pass and the sequential pass each try the
download themselves.

`classify_universe.py --sec-workers N` (default 4, at most 8; the library's
`run()` defaults to 1) fills the SEC caches ahead of four sequential stages:
issuer resolution (one task per era), the Form 25 search (one per security),
payout extraction (one per merger) and the successor search (one per unresolved
exchange transfer). It runs each stage's own code on N threads
(`prefetch.warm`) and throws the answers away.
- **Fill-only threads.** Warm threads only fill missing cache entries; they
  never refresh an existing one (`edgar.fill_only`). The stage then runs one
  item at a time on the main thread, in the usual order, reading exactly what a
  one-thread run reads and refreshing stale copies itself. The same caches and
  run date therefore give byte-identical tables for any N — the *cache tree* can
  still end up larger than a single-worker run's, since a warm thread may fetch
  and keep (at its own normal TTL) a real SEC answer the sequential pass never
  asks for; that never changes a row the tables emit.
- **Warm finders.** They use the run's own MIDAS and Nasdaq-halt clients, each
  behind one lock (`prefetch.Serialized`), so they take the same last-trade
  anchors as the sequential pass.
- **What stays on the main thread.** The fails-to-deliver downloads, OpenFIGI
  and the LLM extractor. OpenFIGI's per-security listing check is sent as
  batched mapping requests.
- **Measured speed** (task 16's live measurement, 2026-09-24). Cold runs on
  150 eras: 1 worker 18m, 4 workers 11m, 8 workers 5m (3.6× wall time; issuer resolution 4.6×). A fully warm
  full-universe rerun takes about 3–4 min (2m47s at 1 worker, 4m13s at 4) with 0 SEC requests. Guidance: use
  `--sec-workers 8` for a cold or large refetch; use `--sec-workers 1` for a
  rerun whose caches are already warm — a warm pass redoes each stage's CPU
  work but sends no request, so a fully warm rerun at the default 4 workers is
  about 50% slower (+CPU only, no extra SEC traffic) than at 1; the default
  stays 4 (cold savings are hours, the warm-rerun cost is ~1.5 min, and 4
  keeps company-search pressure moderate). SEC's company-name search
  (`cgi-bin/browse-edgar`) is 89% of cold issuer-resolution time and can slow
  to ~10 s/request after about 1,500 searches in under an hour, recovering
  after ~20 idle minutes; every such answer is a normal 200 with a valid ATOM
  body, so nothing in the code notices the slowdown — it only costs time.
  Peak memory is 1.8–4.2 GB, mostly data (likely the fails-to-deliver panel; not profiled); threads add
  at most about 37 MB (measured). SEC does not keep full-text-search hit order stable
  between two fetches of the same query: the same cache always gives the same
  output, but a refetch can reorder tied hits (three EDGAR-side places take
  the first match in hit order — the resolver's first pass, the frequency
  ranking's stable sort of ties, and `successor_from_8k12b`'s first agreeing
  candidate — so two fetches of one query can resolve differently when two
  CIKs tie; sorting hits canonically before use would remove this, left as a
  main-branch follow-up).
- **The rate limit.** Every thread shares one limiter (`edgar.SEC_LIMITER`:
  request starts at least 1/8 s apart). A 5xx or dropped connection pauses
  every thread together. The limit is machine-wide: each start also takes an
  `flock` on `~/.cache/delist_detection/sec_rate.lock`
  (`$DELIST_DETECTION_SEC_RATE_LOCK` overrides it). That file holds the last
  start time, so every SEC client on the machine that uses the same file (runs
  in any worktree, `verify_against_web.py`, `build_golden_fixtures.py`) stays
  under 8 requests/s together. A library caller that builds its own clients
  instead of using `default_clients` must call `edgar.use_machine_wide_limit()`
  itself. A process never sleeps while holding the lock file's `flock` — it
  reads the last start time, releases the lock, then sleeps — so a suspended
  process (Ctrl-Z, a debugger) cannot stall every other SEC client on the
  machine; a process forked after the gate is installed shares the parent's
  lock (the same open file description). An unwritable lock path fails at
  start-up (`use_machine_wide_limit` raises `OSError`), not mid-run. An agent
  sandbox cannot write `~/.cache/...`, so this repo's agent runs set
  `DELIST_DETECTION_SEC_RATE_LOCK` to one path,
  `/tmp/claude/delist_detection/sec_rate.lock`. That is a *different* file
  from the terminal default, so an agent-sandbox run and a terminal run never
  share a gate with each other — only with other runs of their own kind. Only
  one SEC client may run at a time across the two; nothing in the code
  enforces that, so it is a manual rule (the controller confirms no other SEC
  client is running before a live run).
- **Timeouts.** An EDGAR request (submissions, filing text, full-text and
  company-name search) times out at 30 s; a MIDAS or FTD index page at 60 s; a
  SEC data-file download (a MIDAS or FTD ZIP) at 180 s.
- **Refusals and Ctrl-C.** A refusal (`EdgarBlocked`/`OpenFigiBlocked`) on any
  thread stops the pool: no item starts after it, and every running worker's
  next SEC request raises `PrefetchCancelled` instead of going out; the refusal
  is raised once the workers have stopped. A stopped worker may first sleep out
  a retry backoff or a shared rate-limiter pause (at most 4 s) before that next
  request raises; a request to another service (OpenFIGI, the Nasdaq halt feed)
  goes through no SEC limiter, so it is not cancelled — the worker stops at its
  next SEC request after it. A first Ctrl-C does the same, then waits for each
  worker's one in-flight request (an EDGAR request times out at 30 s, a
  MIDAS/FTD ZIP download at 180 s). A second Ctrl-C during that wait interrupts
  the wait itself and propagates at once, but the workers are not daemon
  threads, so the interpreter still waits for each one's in-flight request
  before the process exits.

Each run writes `run_manifest.json` next to the tables:
- the run date (`as_of`), the code version and the worker count;
- per-endpoint SEC request counts, cache answers and latency (p50, p95, max);
- degraded answers (failed requests, stale copies), rejected and not-covered
  full-text searches, and the count of `resolution_degraded` review rows.
  `degraded_answers` counts only what the *sequential* pass rested on; a
  warm/fill-only thread's own degraded reads (`edgar.filling_only()`) are
  counted apart, under `warm_degraded:<what>`, so `degraded_answers` is never
  inflated by a warm thread's own failed attempt at an answer the sequential
  pass never needed (only the sequential pass's own degraded reads can ever
  become a `resolution_degraded` review row and feed exit 3);
- per-warm-pass task failures (`warm_failed:<stage>` — logged at DEBUG and
  counted; the sequential pass meets and records the same failure itself, so a
  nonzero count here only flags a concurrency-only failure worth a second look);
- per-stage EDGAR requests and SEC data-file downloads.

The manifest is not part of the byte-identical-output guarantee: `as_of`, the
code version and the worker count make it expected to differ between two runs
even when their six tables come out identical. A run that aborts leaves the
previous manifest in place.

`scripts/classify_universe.py` exits:
- `0` on success;
- `2` when SEC or OpenFIGI refuses a request (`EdgarBlocked`/`OpenFigiBlocked`;
  no output written), or when a start-up check fails (no `EDGAR_USER_AGENT`, an
  unusable rate-lock file, or `--sec-workers` outside `[1, 8]`);
- `3` when the run completed but `review.csv` has one or more `error` rows (one
  security or payout extraction raised and was logged instead of aborting) or
  `resolution_degraded` rows (an answer rested on a failed SEC request or a
  stale copy). Outputs are still written, and a banner naming the counts goes to
  stderr.

## Resolver strategy in detail

EDGAR's `company_tickers.json` only lists currently-registered issuers, so
it cannot map deregistered tickers. We layer increasingly looser strategies
until something hits, then validate that the candidate looks like a delist
target rather than an acquirer.

1. **The era's `cik` pin**, from the observations CSV: `pipeline.py` passes each
   era's own pin (`resolve(..., pin=era.cik_pin)`), since a date lookup
   (`ObservationIndex.cik_pin_on`, the resolver's `cik_map` for other callers)
   can land nearer another era of the ticker. Beats every other tier, including the manual
   override. Never written to `cache/ticker_resolution.json`: it answers
   before the on-disk memo is even consulted, so persisting it would let a
   stale pin outlive a later correction in the observations file — the
   resolver must forget it the moment the pin does.

2. **Manual override.** Hand-curated `MANUAL_OVERRIDES` in
   `scripts/classify_universe.py`. Wins over everything below it; used for
   short tickers where EFTS picks the wrong issuer (e.g. `AET → 1122304 Aetna`).

3. **company_tickers.json.** Master active-tickers map. Taken only when
   today's holder of the ticker existed on the date under an agreeing name;
   a holder whose name disagrees is not used (a recycled ticker's historical
   era would otherwise go to today's holder). A wrong answer from a later
   tier is corrected with a `cik` pin or `MANUAL_OVERRIDES`, not here.

4. **EFTS Form-25/15 with date window.** Searches
   `efts.sec.gov/LATEST/search-index` restricted to Form 25, 25-NSE, 15-12G,
   15-12B, 15-15D within ±90 days of the observed delist date. Skips
   known exchange CIKs (Nasdaq 1354457, NYSE LLC 876661, Cboe BZX 1417835, …) and prefers hits
   whose display_name contains the literal `(TICKER)`.

5. **The era's own `name` → EDGAR cgi-bin company search.** Uses the `name`
   carried by the era's own observations (`ObservationIndex.name_on`), not a
   stale index-membership file elsewhere; generates variants (full name,
   suffix-stripped, leading 1-3 tokens), and queries
   `www.sec.gov/cgi-bin/browse-edgar?company=…&type=…&output=atom`.

6. **EFTS 8-K frequency rank.** Counts CIKs appearing in 8-Ks that mention
   the ticker in the 120 days before delisting. Validates each candidate
   in strict mode (must have Form 25/15 in window AND no 10-K/Q in the
   five years after `delist + 90d` — the latter rejects the acquirer).

A pin does not silence the name check: whenever the era carries a `name`,
the resolved CIK's EDGAR name is checked against it and a disagreement is
flagged `member_name_mismatch` regardless of which tier resolved the CIK.

## FIGI resolution

`FigiResolver.resolve_many` (`security_master.py`) resolves each era to a US
composite FIGI via OpenFIGI, one era at a time:

1. **The era's `sec_id` pin**, when the caller supplied one — wins outright.
2. **The era's CUSIPs** (`era_cusips`, FTD-confirmed, up to 3), queried via
   `ID_CUSIP`/`ID_CINS`. Tried first because a CUSIP hit needs no name check
   (see the spec's Implementation notes).
3. **The era's ticker**, queried via `TICKER`; accepted only when a per-venue
   row carries both the observation's ticker and a name that agrees with the
   observation/EDGAR name.
4. **An issuer-name filter search** (`/v3/filter`, legal suffixes stripped)
   as the last resort.

`figi_resolution.us_candidates` keeps only US-venue rows and drops
when-issued/144A/fund-NAV lines; `accept()` never trusts Bloomberg's current
name alone, since Bloomberg renames a dead line to its acquirer. With no
candidate accepted, the security gets the placeholder `sec_id`
`CIK<cik>-<CLASS>` (flagged `no_figi`); with no CIK either, the observation
goes to `review.csv` as `observation_unresolved`.

## Delisting discovery

`DelistingFinder.find` (`delistings.py`), per security:

1. **List every Form 25 / 25-NSE / 25/A** in the issuer's submissions,
   including paginated older files, from `FORM25_LOOKBACK_DAYS` before the
   security's first sighting onward.
2. **Skip** regional/secondary exchanges (`REGIONAL_EXCHANGES`) and filings
   whose class text is unreadable (`form25_unreadable`) or unclassified
   (`form25_unclassified`) — flagged for review, not silently dropped.
3. **Match** the remaining Form 25s to one of the issuer's observed
   securities by class kind (common/preferred/warrant/unit/…) and class
   letter (`form25.match_security`); zero or several matches is
   `form25_unmatched`. A sibling security only competes for the match while
   it was alive on the filing date (`SecurityContext.sibling_spans`).
4. **Secondary-listing check**: a matched Form 25 counts only when the
   security has no exchange listing left afterwards or has moved to a new
   one (`listing_status.withdrawal_kind`, from 10-K cover-page exchange
   lists before/after). Withdrawing a regional/secondary listing while the
   main one continues (Apache/Chicago 2020) creates no row.
5. **Group** the surviving Form 25s into one delisting per removal: filings
   chain into the same group when within `SAME_EVENT_DAYS` of the group's
   *earliest* member's filing date, across exchanges; the most-senior
   exchange in the group supplies the event's `exchange`.
6. **Date and classify** each group (`last_trade.decide_last_trade` +
   `DelistClassifier.classify_event`, anchored on the last trade date or the
   winning Form 25's filing date). The event's `ticker` is the ticker on the
   last trade date (`ctx.ticker_on(last_trade.day)`) when the last trade date
   is known, else the ticker on the Form 25 filing date (spec §7.4).
7. **Fallback / completeness**: this runs whenever none of the events found
   for a security is a genuine end (every one is `continued` — e.g. an
   exchange transfer the security kept trading through) — not only when no
   events were found at all, so a security that transferred exchanges and
   only later truly delisted still gets a second, later event instead of
   silently having none. With no Form 25 to anchor on, the classifier's
   existing fallback paths (8-K 2.01 completion, Form 15, `REVOKED`, SPAC
   trust liquidation) find and date the delisting, flagged `no_form25`; a
   fallback event has no Form 25 exchange evidence, so its `exchange` is
   read from the issuer's own EDGAR submissions JSON (`tickers`/`exchanges`
   at the ticker's index) instead, or left empty when that has nothing
   either. When even the fallback paths find nothing but the security isn't
   listed today, the security is dated by its last sighting instead, flagged
   `delist_date_approx`, and reported to `review.csv` as
   `ended_without_delisting` rather than fabricated as an event.

A security can have more than one delisting (e.g. an exchange transfer,
years later a merger).

## Classifier rules

`classify_event` runs a fixed sequence of checks and returns as soon as one
applies, in this order (unchanged rule order and codes from before the
security-master rebuild — see the spec's §8.7):

| Trigger | CRSP code | Bucket |
|---|---|---|
| Non-equity security kind (from the Form 25 class text / OpenFIGI `securityType` / name keywords: warrant, unit, right, fund, debt) | 600 | EXPIRATION |
| Form `REVOKED` present | 573 | COMPLIANCE_FAILURE |
| 8-K item 1.03 whose own Item 1.03 section reports a bankruptcy, searched 540 days before to 30 days after the anchor date (an unreadable section still counts, flagged `bankruptcy_text_missing`). Exception: when that 1.03 is more than 180 days before the anchor and a change-in-control 8-K (5.01, or 2.01 with 3.01 or 3.03) falls within 30 days of it, the merger path wins instead and the row is flagged `bankruptcy_before_merger` | 470 | LIQUIDATION |
| A rename near the anchor, or a 3.01 notice that reads as a listing transfer rather than a deficiency, with the company still reporting results afterward. Yields to the merger path whenever a nearby 8-K shows an acquisition (5.01, or 2.01 with 3.01 or 3.03) | 304 | EXCHANGE_TRANSFER |
| SPAC trust liquidation (blank-check company, redeemed at trust value) | 600 | EXPIRATION |
| 10-K / 10-Q / 20-F filed more than 180 days after the anchor | 304 | EXCHANGE_TRANSFER |
| None of the above: the 8-K item fingerprint decides, anchored on the matched Form 25's filing date (or the fallback filing date). A Form 25 more than 45 days from the anchor is a frozen tail, flagged `frozen_tail:<days>` | | |
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

## Last trade date and closes

`last_trade.decide_last_trade` picks among, in priority order (see the
README's *Where each date and price comes from* for the full detail):

1. The Form 25's EX-99.25 exchange notice.
2. The closing 8-K's Item 3.01 text.
3. SEC MIDAS per-security exchange volume (2012+) — the last day with
   nonzero exchange volume, when it falls in a plausible window. When the
   requested window runs past MIDAS's coverage end (the last day of the
   latest published quarter) and the found day is within 5 trading days of
   that edge, MIDAS answers `None`: an unpublished quarter always yields
   nothing, so a day that close to the edge can't be told apart from "the
   next quarter just isn't out yet".
4. Nasdaq's trade-halt feed (code `D`), used only when MIDAS has no answer.

MIDAS beats a halt beats filing-text wording; a disagreement between a
measured source and filing text is flagged `last_trade_date_conflict`; text
alone with no confirmation is flagged `last_trade_date_unconfirmed`.

Closes come from SEC fails-to-deliver rows (2004+, `ftd.close_after`): the
row dated `last_trade_date + 1 trading day` carries `last_trade_date`'s
close, looked up by CUSIP first, then by ticker. The same lookup prices the
acquirer on a merger's completion date. When no row follows the last trade
day (fails stop once trading stops), the latest row dated on it or up to 10
trading days before gives the close of the day before that row, flagged
`ftd_close_prior:<n>` with `<n>` the close's age in trading days before the
last trade (`ftd.close_through`; the row's date is kept in the evidence as
`ftd_close_row_date`). DLRET uses that close as the last close; the flag is
how a reader tells its age. Missing → `--last-trade-closes`
override; otherwise `dlret` stays blank (`needs_last_trade`) and the row
goes to `review.csv`.

## Outputs

Six CSVs written to `output/`, all committed artifacts; see `store.py` for
the exact schema. `delistings.csv` is the primary deliverable.

`output/securities.csv`: one row per identified security — `sec_id`,
`issuer_cik`, `share_class`, `name`, `security_type`, `observed`,
`figi_source`.

`output/ticker_history.csv` / `output/cusip_history.csv`: point-in-time
ticker and CUSIP ranges per security, keyed by `(sec_id, valid_from, ticker)`
and `(sec_id, valid_from, cusip)` respectively, built from observations plus
SEC fails-to-deliver rows. `ticker_history.exchange`
is filled for the range that ends in a delisting (from the Form 25) and for
the still-open range (from the issuer's current EDGAR submissions listing);
otherwise empty. `ticker_history.source` is `observation`, `ftd`, or
`edgar_8k`: an added successor security's range (an exchange-transfer
continuation, spec §8.5) is built directly from the 8-K that named it rather
than from FTD sightings; an added acquirer security's range still comes from
`ftd`.

`output/delistings.csv`: one row per delisting event with the CRSP code,
bucket, confidence, evidence chain (Form 25 date, 8-K items, Form 15 form
name, resolved company name, which resolver tier won), the reconstructed
delisting return (`dlret`), the method that produced it, and the raw
extracted payout (`raw_payout_per_share`, `raw_payout_source`,
`raw_payout_confidence`) before the last-close gate runs. Columns are
`DELISTINGS_COLUMNS` in `store.py`. `resolution_source` records the resolver
tier that found the security's CIK, taken from the security's latest era
that has a CIK (`security_master` when none has one); `SecurityContext
.resolution_source` → `classify_event(resolution_source=...)` carry it to
the row.

`output/payouts.csv`: per-merger cash payout after the last-close gate:
only a payout (or cash+stock/stock-only terms) that reconciles with the
target's last trade close is kept, so a row the gate drops is blank here
even though `delistings.csv` still carries the raw extracted value.

`output/review.csv`: every delisting row whose `review_flags` is non-empty,
plus every security with no delisting at all (`ended_without_delisting`,
`listing_status_unknown`, `form25_unmatched`, `form25_unclassified`,
`form25_unreadable`, `observation_unresolved`, `error`), plus
`ticker_history` consistency checks (`ticker_range_overlap`: two of one
security's own ranges overlap; `ticker_shared`: the same ticker maps to two
securities on the same day), plus observation checks
(`observation_conflict:<date>`: one row per ticker observed under two or
more names on that date, both kept, `sec_id` empty; `ticker_unconfirmed`: an
era from 2004 on with no fails-to-deliver row under its ticker within 30
days of its span), for a human to triage. Delisting rows can also carry
`acquirer_close_lagged` (the acquirer price in a merger's terms came from a
fails-to-deliver row later than the next trading day) and
`observed_after_delisting` (the delisting's Form 25 predates the security's
first observation and no fails-to-deliver row under its own tickers shows it
trading afterwards: the observations after it are a stale snapshot's). Written by
`scripts/classify_universe.py` alongside the other five tables.

`output/web_verification.csv` — independent EDGAR cross-check produced by
`scripts/verify_against_web.py`. Verdicts:

| Verdict | Meaning |
|---|---|
| `OK` | `resolved_name` shares a token with EDGAR's name; bucket-specific evidence present |
| `OK_recycled_ticker` | `resolved_name` doesn't match (ticker recycled) but the CIK has a Form 25 within ±30d of the observed date |
| `MISMATCH_name` | `resolved_name` shares no tokens with EDGAR's name and no nearby Form 25 — needs human review |
| `WEAK_no_delist_form`, `WEAK_no_ma_items`, `WEAK_no_3_01`, `WEAK_no_form15` | Names agree, but the bucket-specific evidence expected on EDGAR wasn't found |
| `no_cik`, `bad_cik`, `no_entity_data` | No CIK, an invalid one, or nothing to check on the EDGAR entity page |

The verifier reads the company's whole filing list (the submissions JSON's
`recent` block plus each older submissions file overlapping the window) and
counts evidence only within [delisting − 400 days, delisting + 120 days]: a
Form 25/15 for `WEAK_no_delist_form`; for a merger an 8-K item 2.01 or 5.01
or a merger document (SC 14D9, SC TO-T, DEFM14A/C, PREM14A/C, 425, SC 13E3);
for a liquidation a Form 15 or the bankruptcy 8-K (item 1.03); for a
compliance failure an 8-K item 3.01. Names are compared on words of four or
more letters, legal and share-class words dropped, both as written and split
on camelCase ("BlackRock" matches "BLACKROCK"). Agreement on the delisting
rows counts `MISMATCH_*`, `WEAK_no_ma_items`, `WEAK_no_3_01` and
`WEAK_no_form15` as disagreements; `WEAK_no_delist_form` and `no_*` are no
evidence either way.

## Downstream integration

`delistings.csv` is consumed by `delist_detection.qlib_adapter`, joined on
`sec_id` (the panel's `instrument` column):

- `inject_terminal_labels(panel, "output/delistings.csv", horizon_days=21, …)`
  rewrites the last *horizon* observations of each delisted security so the
  supervised label matches the bucket policy (merger payout, compliance
  -100%, etc.). Eliminates the most common form of survivorship bias in
  walk-forward training.
- `apply_backtest_exits(positions_df, "output/delistings.csv", …)` rewrites
  the exit-day price per delisted security to the bucket-specific exit
  policy. Stops the backtest from marking a compliance-failed position at
  the last OTC quote.
- `apply_bmp_corrections(panel, "output/delistings.csv", …)` splices the BMP
  2007 corrected firm-month return into a monthly panel.

Every input these three read (exchange, last trade close, payout, recovery
ratio, successor) comes straight off the matching `delistings.csv` row —
there are no more ticker-keyed dictionary arguments to assemble by hand.

All three splicers, and `handling.adjustments_from_rows`, skip a row whose
`successor_sec_id` equals its own `sec_id`: that security kept trading under
the same FIGI (e.g. an exchange transfer that didn't relist under a new
identity), so it isn't an exit at all — no label, exit price, or firm-month
correction is emitted for it.

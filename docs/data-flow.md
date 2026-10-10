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
                             │ FtdIndex.opened (era tickers' fails-to-deliver rows)
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
              │  second pass, never saved  │   the rest: 8-K frequency through guard G,
              │  (identity.EraIssuers)     │   else a shared CUSIP or a CUSIP handoff
              └─────────────┬──────────────┘
                             │ FigiResolver.resolve_many (OpenFIGI, per era)
                             ▼
              ┌────────────────────────────┐
              │  FigiResolver: era → sec_id│   sec_id pin → CUSIP → ticker → name filter
              │  (US composite FIGI, or    │   → CUSIP handoff (shared CUSIP/switch to a
              │  placeholder)              │      confirmed sibling) → backfill → placeholder
              │  + identity guard          │   no ticker/name pick for an unconfirmed era;
              │                            │   a weak era crossing a confirmed range detached
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
                             │ match_securities (class kind + letter) + secondary-
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
                             │ stage 5b (_dead_before_sighting): a security whose last
                             │ real ending came before its first observation and with no
                             │ trading fails row gets rows loaded for [end − 1095 d,
                             │ end + 10 d], takes the CUSIPs of rows under its tickers
                             │ in the 120 days before the end that name its issuer
                             │ (history.backfill_cusips; not CUSIPs another security holds), and its sightings are rebuilt
                             │ ftd.close_after (last-trade + acquirer closes),
                             │ payout_extractor / llm_merger_extractor, payout_gate
                             ▼
              ┌────────────────────────────┐
              │  successors, then the      │   successor search (a line of the run, else the
              │  handoff pass              │   successor's 8-K12B); ticker handoffs: a
              │  (endings/handoffs.py)     │   continuation's row + successor, a takeover's
              │                            │   ticker_successor_sec_id
              └─────────────┬──────────────┘
                             │
                             ▼
              ┌────────────────────────────┐
              │  enrich() → delistings.csv │   + review.csv +
              │  (+ cusip_history.csv)     │     review_summary.csv (review_triage),
              │                            │     cusip_history.csv from history.ranges_from_sightings
              └─────────────┬──────────────┘
                             │ handling/handling.py / handling/qlib_adapter.py (DLRET: dlret.decide)
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

`observation_map.csv` (one row per input observation, its era, `sec_id` and
status) is written in the same final row-building stage as the
`cusip_history.csv` box above (and the in-memory ticker ranges), from the same eras and
resolutions; see *Outputs* below for its schema and status rules.

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
`as_of` is the run date, read once per run (`classify_universe.py --as-of
YYYY-MM-DD`, default today) and passed to every client. A copy
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
stale-copy fallback. Every cache file — EDGAR answers and filing text, the
FTD and MIDAS ZIPs and index pages, MIDAS quarter summaries, Nasdaq halt days,
OpenFIGI answers, LLM answers and the resolver memo — is written atomically and
durably through `atomic_io.write_atomic` (a temp file, fsync, `os.replace`, fsync
of the directory), so a crash, Ctrl-C or power loss never leaves a torn file;
a killed writer's temp files (and a `.part` download left by the code before
this) are removed when the next client starts (`atomic_io.clean_orphan_temps`).

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
`(ticker, observed_date, observed name)` (`TICKER|date|NAME`) so a recycled
ticker resolves to the right issuer per date and an answer holds only for the
era name it was checked with. The file is versioned (`{"__version__": 4,
"entries": …}`); versions 2 and 3, keyed `TICKER|date`, load re-keyed from each
entry's `member_name`, and a file before version 2 predates the date and name
checks, so it is ignored and replaced on the next save. Answers of a withdrawn
rule (`company_tickers_name_mismatch`, which let today's ticker-map holder
beat a name-mismatched EFTS candidate) are dropped on load and resolved again;
`RETIRE_OLD_NAME_SEARCH` (off) would do the same for a version-2/3 file's
`name_search` answers, written before the name search ranked its candidates.
The second pass's answers are never saved. Misses are never saved: each run re-derives them, with the
current code, from the cached search evidence. An answer reached while an EDGAR
request failed, or through a stale copy (a submissions JSON or a company-search
hit served after a failed refetch), is used for the run but never saved, and
`review.csv` flags it `resolution_degraded`. The pipeline writes the memo after
each resolving stage and on the way out of a run.

A connection error, a timeout, or a 5xx on a submissions fetch, a filing text
or raw fetch (`fetch_filing_text` and `fetch_filing_raw` are both retried the
same way), a full-text-search query, or a MIDAS/FTD ZIP download is retried up
to 3 attempts with 2s/4s backoff (`edgar.retry_request`, inside
`edgar.sec_get`, the one request path `EdgarClient` and `sources/sec_http.py`
share) before giving up; a 403/429 still raises `EdgarBlocked`
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
  never refresh an existing one (`sec_stats.fill_only`). The stage then runs one
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
  ranking's stable sort of ties, and `successors.successor_from_8k12b`'s first agreeing
  candidate — so two fetches of one query can resolve differently when two
  CIKs tie; sorting hits canonically before use would remove this, left as a
  main-branch follow-up).
- **The rate limit.** Every thread shares one limiter (`sec_limiter.SEC_LIMITER`:
  request starts at least 1/8 s apart). A 5xx or dropped connection pauses
  every thread together. The limit is machine-wide: each start also takes an
  `flock` on `~/.cache/delist_detection/sec_rate.lock`
  (`$DELIST_DETECTION_SEC_RATE_LOCK` overrides it). That file holds the last
  start time, so every SEC client on the machine that uses the same file (runs
  in any worktree, `build_golden_fixtures.py`) stays
  under 8 requests/s together. A library caller that builds its own clients
  instead of using `default_clients` must call `sec_limiter.use_machine_wide_limit()`
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
- **Refusals and Ctrl-C.** A refusal (`EdgarBlocked`/`OpenFigiBlocked`), or
  OpenFIGI unavailable after its retries (`OpenFigiUnavailable`), on any
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
  warm/fill-only thread's own degraded reads (`sec_stats.filling_only()`) are
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
even when their seven tables come out identical. A run that aborts leaves the
previous manifest in place.

`scorecard.json` is built at stage 10h from the same rows the tables are
written from (`store.formatted`), so it equals what `scripts/scorecard.py`
recomputes from the written CSVs. It is written after the tables and before the
manifest, carries `drops` (floored numbers that got worse; never computed under
`--limit`) and `golden_failures`, and is compared to `data/scorecard.json`'s
floor. It is deterministic for the same tables, config and run date.

Before the write, stage 10e gathers each placeholder's ticker evidence
(`ticker_evidence.evidence_for`: a resolver tier that names the ticker, else
one full-text search of the CIK's own filings), 10f decides every verdict
(`verdict.decide` over the rows about to be written) and adds `uncertain.csv`
to the group, and 10h builds the scorecard from the same rows, so its V lines
count exactly what `uncertain.csv` lists.

10g, the contract (`pipeline._contract`): `_issuers_in_force` (one cached
submissions read per issuer CIK, and SEC's name index for a sighting whose era
CIK did not carry its name that day), then `outputs/contract.py`'s rows and
`price_requests.request_rows`. A price answer to no request stops the run here. An `otc_print` answer
is read at stage 10a through the request it answers (`price_requests.PriceAnswers.ending_values`);
`dlret.decide` (its `ValueInputs.otc_print`) then values a liquidation or
compliance-failure ending as `print / last_close − 1` (`dlret_method` `otc_print`).
A blank `exit_kind` in the contract means no kind is asserted; such a row's
verdict is always `uncertain`, so a reader must not filter it away as "no ending".
`contract/delistings.csv` also carries each ending's payout rule (`payout_rule.value_fields`; stage 8's
`merger_value.MergerValues.contract_inputs` hands it the `--merger-terms` row, the LLM terms and regex read from before the payout gate, and the acquirer's
sec_id): a merger's terms come from the override, else the delistings.csv row (`terms_gate` passed, or blank
when no last close existed), else the pre-gate read (`terms_gate=failed`; a failed election publishes both legs as read).
The scorecard counts endings by `R2.7.value_rule.<rule>` and `R2.7.payout_rule_known`.
10h, the scorecard.

`scripts/classify_universe.py` exits:
- `0` on success;
- `1` only on an unexpected crash (an uncaught exception: Python's own exit
  code, with its traceback);
- `2` when SEC or OpenFIGI refuses a request (`EdgarBlocked`/`OpenFigiBlocked`;
  no output written); when an input file is bad (one stderr line naming the
  file and line, no output written): an `--observations` file
  (`ObservationError`) or an override file (`reconstruction.OverrideFileError`:
  a missing column, a value that is not a number, an incomplete stock leg, a
  value with no `sec_id`, a key given twice) that is missing or malformed,
  override rows that match no delisting of the run (`pipeline._check_overrides`,
  once the delistings are known, before any table is written), or a
  `--review-decisions` file that's missing when given explicitly or that
  `review_triage.load_decisions` refuses; or when a start-up check fails (no
  `EDGAR_USER_AGENT`, an unusable rate-lock file, a bad argument such as
  `--sec-workers` outside `[1, 8]` or an unreadable `--as-of`);
- `3` when the run completed but `review.csv` has one or more `error` rows (one
  security or payout extraction raised and was logged instead of aborting) or
  `resolution_degraded` rows (an answer rested on a failed SEC or Nasdaq halt-feed request or a
  stale copy). Outputs are still written, and a banner naming the counts goes to
  stderr;
- `4` when OpenFIGI is unavailable after its retries (timeouts, connection
  errors or 5xx answers: `OpenFigiUnavailable`; no output written, nothing
  cached, no placeholder in its place; rerun later).

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
   today's holder of the ticker existed on the date under an agreeing name,
   and had filed by the era's first sighting (`resolve(..., since=era.first)`;
   also for a memo answer): a company formed while the era traded can have
   taken its name and ticker (Energizer's 2015 SpinCo, the 2016 Hertz holding
   company). A holder whose name disagrees is not used (a recycled ticker's
   historical era would otherwise go to today's holder). A wrong answer from a later
   tier is corrected with a `cik` pin or `MANUAL_OVERRIDES`, not here.

   The same first-sighting check holds every CIK a search proposes: tiers 4,
   5 (each ranked candidate) and 6 (the strict pass) take no company that had
   not filed by the era's first sighting, and a remembered answer from any of
   them is held to it too (Alcoa Corp, formed 2016, is no name-search answer
   for ALCOA INC 2008-2016; the new Clearwire of 2008 no Form 25 answer for
   the old one's CLWR). Pins, manual overrides and renames are not checked.

4. **EFTS Form-25/15 with date window.** Searches
   `efts.sec.gov/LATEST/search-index` restricted to Form 25, 25-NSE, 15-12G,
   15-12B, 15-15D within ±90 days of the observed delist date. Skips
   known exchange CIKs (Nasdaq 1354457, NYSE LLC 876661, Cboe BZX 1417835, …) and prefers hits
   whose display_name contains the literal `(TICKER)`.

5. **The era's own `name` → SEC's name index.** In a production run
   (`pipeline.default_clients`) the candidates come from SEC's
   `cik-lookup-data.txt` (`sources/cik_lookup.py`): about a million `NAME:CIK:` lines,
   every name each CIK filed under (MICHAEL KORS HOLDINGS LTD and CAPRI
   HOLDINGS LTD are both CIK 1530721), funds and individuals included,
   downloaded once and refreshed after 30 days under
   `cache/sec_data/cik_lookup/`. Names are compared normalized (case,
   periods, hyphens, punctuation, `&` and EDGAR's `/DE/` state tag ignored).
   For each spelling, its exact and character-prefix matches (snapshots cut
   names short: COCA COLA ENTERPRISE) stand in for the live search, read
   through their cached submissions JSON (`_index_candidates`):
   - the one CIK whose name is exactly the spelling and that filed within a
     year of the date is the answer, as EDGAR's company page was (FIRST
     REPUBLIC BANK never filed a Form 25); of several such, the one that
     carried the name (TCF FINANCIAL CORP in 2014, not its 2019 taker);
   - else the live search's form filter: under 25-NSE, then 25, then
     15-12G, the first form any of them filed decides. A lone filer counts
     when it carried the matched name in the 5 years before the date or just
     after (not FIRST REPUBLIC BANCORP, another bank's name in 1996-97).
     Of several, only the one the query names counts (`_one_filer`: the
     exact name, else exactly the observed name's words, ANHEUSER BUSCH
     COMPANIES, not ANHEUSER-BUSCH INBEV; then the one that carried the
     name by the date, then on it); none named, none;
   - with no filer, the one CIK of that exact name, else a spelling's only
     CIK, its date gap counted from its nearest filing;
   - a spelling matching more than 10 CIKs is read only when it keeps every
     word of the name (MEDCO HEALTH SOLUTIONS and its pharmacy subsidiaries:
     the top 10 carrying every word); a cut-off one (NORTHEAST of NORTHEAST
     UTILITIES, S P of S&P GLOBAL) names nothing.
   Without the form filter the file's funds, individuals and subsidiaries win
   (WEATHERFORD YVONNE for WEATHERFORD INTL, a first attempt showed). No live
   company search is sent. A resolver built
   without the index (the offline tests, the golden replay), or whose index
   cannot be loaded, uses the live search:

   **The era's own `name` → EDGAR cgi-bin company search.** Uses the `name`
   carried by the era's own observations (`pipeline.py` passes
   `resolve(..., name=era.name)`: a date lookup, `ObservationIndex.name_on`,
   can land on a neighbouring era's name when FTD rows of a shared CUSIP carry
   the last sighting past it), not a stale index-membership file elsewhere;
   generates variants (full name, suffix-stripped, leading 1-3 tokens), and
   queries `www.sec.gov/cgi-bin/browse-edgar?company=…&type=…&output=atom`. A
   hit with no name is no candidate: EDGAR answers a query matching several
   companies with a list and no conformed name, and the CIK read from it is
   the list's first (MICHAEL → Michael Baker). Up to 5 distinct CIKs are
   ranked by the words the name shares with their EDGAR names, current and
   former (the search matches a former name: MICHAEL KORS HOLDINGS LTD finds
   Capri Holdings), then by date gap, and checked in that order; a candidate
   below the first only when one of its EDGAR names agrees with the name
   (Keurig Green Mountain, sharing KEURIG, is no DPS).

6. **EFTS 8-K frequency rank.** Counts CIKs appearing in 8-Ks that mention
   the ticker in the 120 days before delisting. Validates each candidate
   in strict mode (must have Form 25/15 in window AND no 10-K/Q in the
   five years after `delist + 90d` — the latter rejects the acquirer).

**The second pass** (`identity.EraIssuers.infer`, after the memo is
flushed). A renamed issuer files no Form 25 and keeps filing 10-Ks, so tier 6
rejects it, and the company search sees only today's name. The eras left with
no CIK and no pin, with at least 3 fails rows of their own
(`identity.era_rows`, `era_last_seen`'s row choice from the first
observation to the last sighting), are answered in era-key order, and the
answers are never saved (they depend on the run's other eras). A candidate CIK
must pass **guard G**: it existed by the era's first fails row, every row's
description matches a name it carried by 30 days after the row's date
(`names.description_matches`; an earlier name counts, since SEC updates
descriptions slowly — HCP INC COM STK until 2019-11-05, a month after EDGAR
ends the name — while a name taken only later does not; a description that
leaves no word to compare, F5,INC. COMMON STOCK, says nothing either way, and
at least one must name the candidate: 2U INC COM STK confirms no one), and it
is the only candidate that did. Every answer must also have one of the era's
observed names match an EDGAR name of its issuer (TRI@2008, Triad Hospitals in
a stale snapshot, holds Thomson Reuters' CUSIP and takes nothing).

- **B, `efts_frequency_renamed`:** tier 6's candidates through G; the one left
  must also carry the era's name at its last sighting and have filed within
  400 days of it (KORS@2014 → Capri Holdings). Refused: GGP@2014 (Seritage
  Growth Properties matches too), a spin-off founded after the rows began, an
  ETN's rows under UAG.
- **C, `shared_cusip` / `cusip_handoff`,** swept until nothing new links: the
  issuer, through G, of the eras `security_master.cusip_handoffs` links to
  this one — the same CUSIP (MHP and MHFI), or a switch: this era's CUSIP last
  trades under its ticker within 5 trading days of another era's new CUSIP's
  first row (no earlier row, 30+ days into the scanned window), trades under
  no symbol 10 trading days later; and that era's issuer must be the old
  CUSIP's, renamed: it existed when the old CUSIP began failing (not Actavis
  plc, formed in 2013, for Actavis Inc), was renamed within 90 days of the
  switch, each old row description is named word by word by a name it carried
  in the 30 days up to that description's first row, or by the name the switch
  renamed it from (`names.description_names`: two words when both sides have
  two; CITIZENS COMMUNICATIONS does not name CLEAR CHANNEL COMMUNICTNS;
  Quintiles' TRANSNATIONAL rows are named by its pre-2016 name; ACE Ltd's 2008
  rows by ACE LTD, the name it dropped at the switch, as EDGAR keeps its names
  only from 2009; a name dropped years before names nothing — CBS Corp's
  VIACOM INC until 2005, TeraWulf's CHROMALINE until 2002 — nor does one taken
  after the rows began: A & B II became Alexander & Baldwin as the Holdings
  CUSIP it was spun off from switched), and it has no other CUSIP
  of its own trading at the switch (an acquirer that renamed itself at the
  merger: WEC Energy for Integrys, Catamaran for Catalyst Health Solutions) —
  a CUSIP of another share class, or one born at the switch, does not count
  (CBS class B → ViacomCBS as class A's switched too) — NU → ES, LUK → JEF,
  KORS → CPRI. A spin-off starting then carries no former name.

At the fixed point every answer is checked again against all it links to; one
that became ambiguous, or lost its link, is dropped. Each answer carries the
`check` flag `issuer_inferred`, whose reason says how. Rule C also runs over the
eras the first pass answered (unpinned): where it points to another issuer, the
first pass's answer stands and the `check` flag `issuer_cusip_disagrees` names
both (LSTR@2008's name search took LandStar Inc; the CUSIP it shares with
LSTR@2012 is Landstar System's).
The parent/subsidiary case is out of its reach: L-3 Communications Holdings
merged into its subsidiary L-3 Communications Corp (renamed L3 Technologies),
whose former name matches the parent's fails rows, so the Holdings eras take
the subsidiary's CIK — pin them.

A pin does not silence the name check: whenever the era carries a `name`,
the resolved CIK's EDGAR name is checked against it and a disagreement is
flagged `member_name_mismatch` regardless of which tier resolved the CIK.

## FIGI resolution

`FigiResolver.resolve_many` (`identity/security_master.py`) resolves each era to a US
composite FIGI via OpenFIGI, one era at a time. Each era's `Issuer` (its CIK
and its EDGAR names, current and former) is read at the end of issuer
resolution, inside that stage's meter and warm pass; a names read that fails
leaves the issuer with no EDGAR names for the run and flags its eras
`resolution_degraded` instead of stopping the run.

1. **The era's `sec_id` pin**, when the caller supplied one — wins outright.
2. **The era's CUSIPs** (`candidate_cusips`/`era_cusips`, FTD-confirmed, up
   to 3), queried via `ID_CUSIP`/`ID_CINS`. Tried first because a CUSIP hit
   needs no name check (see the spec's Implementation notes) — which holds
   only because the CUSIP was checked first: an era takes an FTD CUSIP only
   when some fails row of it has a description that `names.description_matches`
   the era's observed names or its issuer's EDGAR names (current and former),
   spec D21. A snapshot that kept listing a company after it was gone (Clear
   Channel under CCU in 2009, whose rows are Cervecerias Unidas') so takes no
   CUSIP and resolves by ticker or name, or to its placeholder. An era with no
   issuer CIK also takes a CUSIP that an era with a known issuer took.
3. **The era's ticker**, queried via `TICKER`; accepted only when a per-venue
   row carries both the observation's ticker and a name that agrees with the
   era's observed names or, failing that, its issuer's EDGAR names (current
   and former): Northeast Utilities, seen under ES before its rename, takes
   Bloomberg's EVERSOURCE ENERGY line. A candidate only the EDGAR names accept
   is dropped when another era's pin or CUSIP contradicts it: another issuer's
   era is confirmed on it (old General Growth Properties is now "GGP, Inc.",
   the name of the new issuer's GGP line), or an era of the same issuer and
   class is confirmed on another composite over overlapping dates (Jacobs
   under a backfilled J in 2012 is not today's Jacobs Solutions line) — see
   the placeholder-splitting guard below for what happens to a sibling era
   this leaves with no pick of its own.
4. **An issuer-name filter search** (`/v3/filter`, legal suffixes stripped)
   as the last resort, accepted by the same name rule as the ticker.
5. **A CUSIP handoff**, for an era steps 2-4 still leave with no pick (a
   renamed ticker's old CUSIP that OpenFIGI knows on no US venue): the same
   shared-CUSIP/CUSIP-switch evidence the issuer resolver's second pass uses
   (`security_master.cusip_handoffs`) links it to a sibling era of the same
   issuer and share class, and it takes that sibling's composite when the
   sibling is itself confirmed by a pin or a CUSIP — not by another handoff,
   so the join never chains through an unconfirmed era to reach a composite.
   KORS's G60754101 (no US venue) switches straight into CPRI's G1890L107
   (confirmed by CUSIP), so both KORS eras take CPRI's composite and keep
   their own CUSIP in `cusip_history`. An era whose links reach two different
   composites takes neither. The join is checked against the same two guards
   an EDGAR-names-only pick is (another known issuer confirmed on the
   composite; a same-issuer, same-class sibling confirmed on a different one
   over overlapping dates), with one difference from the placeholder-splitting
   guard below: a *chain* of eras linked by a shared CUSIP joins all together
   or not at all, so NU@2008 and ES@2012 (one issuer, joined by NU's switch
   into ES's later, CUSIP-confirmed line) must both go or neither, even though
   only NU@2008 carries the switch itself. `figi_source=handoff` marks the
   result, ranked between `name` and `placeholder`.

**The identity guard** (handoff plan, Part 1). The ticker and name tiers
answer with whoever holds the ticker or the name *today*, so:

- An era the fails data covers but never shows under its ticker (no row
  under it within 30 days of its span while rows of other symbols exist then:
  `security_master.guarded_eras`, the same fact `ticker_unconfirmed` reports)
  and that an era of its own issuer and class places -- confirmed (by a pin
  or a CUSIP) over overlapping dates on exactly one composite -- is a ticker a
  snapshot backfilled: it is not asked the ticker or name tier, and is placed
  (`figi_source=backfill`) on that composite. Jacobs under J in 2012-2014
  lands on the JEC line, and its observations become `backfilled_ticker` in
  `observation_map.csv`. An unconfirmed era with no such line keeps the ticker
  and name tiers: a stale snapshot's dead company finds its own line there
  (Dow Jones and Mellon, listed in 2008 after they were acquired), and a
  later holder's line is caught below (APTV in 2012-13).
- A plain own-name pick is not checked against other eras' confirmations: a
  line keeps its composite through a change of issuer (Merck's 2009 reverse
  merger, Medtronic's and Eaton's redomiciles), and an era's issuer CIK can be
  today's holder's. (The handoff plan asked for that check; the full run of
  2026-09-29 showed it and a blanket unconfirmed-era guard turning some 40
  correct FIGIs into placeholders, so neither is kept.)
- After the eras are resolved, a weak era (a ticker or name pick) whose merge
  would carry its security's range for the ticker across another security's
  confirmed span of that ticker (`crossing_weak_eras`: the confirmed span lies
  wholly between the weak era and another era of its own security) is taken
  back out and resolved again without the pick, until none crosses
  (`resolve_with_identity_guard`), with an `identity_detached` review row. ITT
  in 2008-2009 (CUSIP 450911102, no US line in OpenFIGI) reached today's ITT
  Inc line by ticker, which would have run 2008..today across the 2011 line's
  2011-2016 range. A weak era that merely shares dates with another security's
  era (ACE backfilled under CB in 2012-2014) is left to the observation-conflict
  review.
- A placeholder is not the line listed today when a FIGI security of its
  issuer and class, sharing one of its tickers, begins after its last
  observation (`superseded_placeholders`): EDGAR's ticker list names the
  issuer's current line, which would otherwise keep an old placeholder's range
  open over every later line.

**The placeholder-splitting guard** (controller ruling, superseding the
original all-or-none-withdrawal design): an issuer's placeholder holds every
era of one class that no FIGI confirms. A sibling era of the same issuer and
class left with *no pick at all* (a backfilled or stale-snapshot ticker: HCP's
own eras find no FIGI, but PEAK@2012 — a 2012-2014 snapshot artifact naming
HCP's later ticker before it existed — never does either) no longer holds a
group's ticker/name/handoff picks to the placeholder outright. Instead it
**follows the group onto its composite** itself, as a `handoff` pick, when the
same two guards (another known issuer confirmed on the composite; a
same-issuer, same-class sibling confirmed on a different one over overlapping
dates) do not rule it out there too — so HCP@2008, HCP@2014 and PEAK@2012 all
land on Healthpeak's composite together. Only when a guard rules the sibling
out specifically, or when the group's own picks disagree on the composite
(two chains reaching two composites), is the whole group withdrawn to the
placeholder together instead, exactly as the original design did
unconditionally; either way an era's own CUSIP-confirmed pick is untouched.

`figi_resolution.us_candidates` keeps only US-venue rows and drops
when-issued/144A/fund-NAV lines; `accept()` never trusts Bloomberg's current
name alone, since Bloomberg renames a dead line to its acquirer. With no
candidate accepted, the security gets the placeholder `sec_id`
`CIK<cik>-<CLASS>` (flagged `no_figi`, an `info` flag: counted in
`review_summary.csv`, not listed in `review.csv`; `securities.csv` marks it
`figi_source=placeholder`); with no CIK either, the observation goes to
`review.csv` as `observation_unresolved`.

## Delisting discovery

`DelistingFinder.find` (`endings/delistings.py`), per security:

1. **List every Form 25 / 25-NSE / 25/A** in the issuer's submissions,
   including paginated older files, from `FORM25_LOOKBACK_DAYS` before the
   security's first sighting onward.
2. **Skip** regional/secondary exchanges (`REGIONAL_EXCHANGES`) and filings
   whose class text is unreadable (`form25_unreadable`) or unclassified
   (`form25_unclassified`) — flagged for review, not silently dropped.
3. **Match** the remaining Form 25s to one of the issuer's observed
   securities by class kind (common/preferred/warrant/unit/…) and class
   letter (`form25.match_securities`); an ambiguous class, or a tie with a
   sibling no name word tells apart (`form25.tied_securities`), is
   `form25_unmatched`. A sibling security only competes for the match while
   it was alive on the filing date (`SecurityContext.spans`, from each sibling's trading record).
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
   `ended_without_delisting` rather than fabricated as an event — also when
   the issuer's Form 25s produced `form25_unmatched`/`form25_unclassified`/
   `form25_unreadable` rows for it, which stay next to it: accepting one of
   those as "not about this security" must not drop the security from review.

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
| 10-K / 10-Q / 20-F filed more than 180 days after the anchor: the end-of-era resolver (`endings/end_of_era.py`) takes the first branch that fits, reading 8-K items, successor filings and Form 25s in [end − 30 d, end + 120 d] and merger filings in [end − 540 d, end + 30 d]: | | |
| (1) the security still traded after the end (the finder's `continued`) | 304 | EXCHANGE_TRANSFER |
| (2) a successor registration (8-K12B, 8-K12G3); stage 9 finds the successor | 304 | EXCHANGE_TRANSFER |
| (3) a change in control (8-K item 5.01) | 231 (or the 8-K items' own merger code, 200/233) | MERGER |
| (4) a completed acquisition (8-K item 2.01) with a merger filing or a Form 25 | 231 (or the items' own merger code) | MERGER |
| (5) a 3.01 notice whose text cites a listing deficiency | 570 | COMPLIANCE_FAILURE |
| (6) none of the above: today's continued-filings reason, unchanged | 304 | EXCHANGE_TRANSFER |
| Sub-plan 5c, rule 1 (the exception to (3) and (4)): the registrant's own filings state no exchange of its own shares (`exchange_terms.own_exchange` finds none, a cash one included) and say it acquired another party (its shares were issued for the other's, or to it under the merger agreement; a top-up option is no such issue) or distributed another company's shares, kept by its holders: no merger from (3) or (4); the resolver goes on to (5) or (6). A bankruptcy before the completed sale (470) still decides, whatever the role | | |
| Sub-plan 5c, R1 without an item code: the filings state each share of the security's class became one share, with no cash (a special dividend is none) and no second leg of shares, rights, warrants, units or a CVR, into the registrant itself or a new issuer (first EDGAR filing at most 1,095 days before, named by the target) | 304, flag `r1_continuation` | EXCHANGE_TRANSFER |
| Sub-plan 5c, stage 8b: a merger whose published terms are one share and no cash (or cash equal to a special dividend the filings name), no `--merger-terms` row, the registrant's own filings saying the same in one reading, and a successor (a security of the run, else the new issuer's 8-K12B, named by the target) | 304, flag `r1_continuation` (was the merger code, kept in an `r1_rebucketed` review row) | EXCHANGE_TRANSFER |
| Sub-plan 5c, stage 9d: each successor the run added (a line's new CUSIP, an 8-K12B filer) takes its own Form 25 ending when one exists (no fallback ending); its span ends at that ending's last trade | the ending's own code | the ending's own bucket |
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
lands `unknown`, which `enrich()` (`outputs/reconstruction.py`) resolves to par
(`dlret = 0`, `assumed_par`) when a valid last close exists, rather than
compounding an unexplained gap into a fabricated return.

## Last trade date and closes

`last_trade.decide_last_trade` picks among, in priority order (see the
README's *Where each date and price comes from* for the full detail):

1. The Form 25's EX-99.25 exchange notice. On an involuntary notice
   (rule 12d2-2(b)) the date is the Exchange's decision day, whatever the
   wording (NYSE announces the suspension "at the close of the trading
   session on D"), so it counts only once MIDAS or a halt confirms it.
2. The closing 8-K's Item 3.01 text. An opening wording ("before the open",
   "prior to the market opening", "before market open", "prior to the
   commencement of trading", "as of the open of business", "at the opening of
   business" on D) dates the last trade on the trading day before D.
3. SEC MIDAS per-security exchange volume (2012+) — the last day with
   nonzero exchange volume, when it falls in a plausible window. When the
   requested window runs past MIDAS's coverage end (the last day of the
   latest published quarter) and the found day is within 5 trading days of
   that edge, MIDAS answers `None`: an unpublished quarter always yields
   nothing, so a day that close to the edge can't be told apart from "the
   next quarter just isn't out yet".
4. Nasdaq's trade-halt feed (code `D`), used only when MIDAS has no answer.
   A day's feed that parses, or a 404 (no halts that day), is an answer; a
   timeout, a connection error, a 429/5xx after the one retry, another
   status or a body that does not parse is a failure. A failed day reads as
   no halts for the run but is never cached, is counted in the manifest as
   `degraded_answers: nasdaq_halt_feed` (not as a failed SEC request), and is
   carried on the decision (`LastTrade.halt_feed_failed`): the delisting gets
   `resolution_degraded`, on its own row and in a review row naming the feed
   and the days, and the CLI exits 3, as for a failed SEC request.

MIDAS beats a halt beats filing-text wording; a disagreement between a
measured source and filing text is flagged `last_trade_date_conflict`; a
date from unconfirmed wording (an involuntary notice's decision day, an
8-K's bare "suspended on D") with no MIDAS or halt to confirm it is flagged
`last_trade_date_unconfirmed`.

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

## Ticker handoffs

`endings/handoffs.py`, run by `pipeline._handoffs` after the successor search and
before the history rows (so a row it adds clips the predecessor's ranges like
any other delisting). A handoff is one security of the run stopping under a
ticker and another starting under it within days (CONTEXT.md).

1. **Finding** (`find_handoffs`): per ticker (either separator spelling), the
   securities sighted under it in the order they began under it, over the
   sightings `ticker_history` is built from (backfilled observations
   dropped; a fails row is a sighting only when its symbol has a letter, because
   SEC's Aug–Dec 2007 files mask some symbols as "**********"); each and the next to begin form a pair when the next one's first
   sighting falls within [−`OVERLAP_DAYS`, `TAKEOVER_DAYS`] = [−10, 120] days
   of the first one's last (CZR's two lines overlap 8 days, COHR waits 74).
2. **Deciding** (`decide_handoff`), the first that applies: a continuation by
   filing (EDGAR full-text search for an 8-K12B/8-K12G3 filed by B's issuer
   naming A's issuer, under its EDGAR names around the handoff, today's, and
   its observed name (`predecessor_names`: Ashland Inc's CIK is ASHLAND LLC
   today), 30 days before to 60 after B's first sighting,
   `continuation_filing`; the filer may keep A's CIK, as Aon did). When the
   search finds nothing, or none exists, B's issuer's own filing list is read for
   the same 8-K12B/8-K12G3 in the same window (`own_continuation_filing`): a
   1:1 holding-company reorganization (Xerox 2019, Cigna 2018, Broadcom 2016/2018,
   QuidelOrtho 2022) names no predecessor the search can match. It is skipped
   when A's issuer carries on in another line, as that filing names no
   predecessor. A filing settles the continuation, so a merger row is rebucketed
   (`handoff_rebucketed`). Next, a
   continuation by timing and identity (at most `CONTINUATION_DAYS` = 10
   days apart, B sighted under no ticker before then, and the same issuer CIK
   or the ticker's CUSIP switching from A's to B's in the fails data,
   `cusip_switch`); a takeover (B traded before, under another ticker, or
   B's issuer is another company that filed with EDGAR over a year before:
   Eldorado, never observed as ERI, took CZR); otherwise nothing, and any
   `ticker_shared` row stays. Two guards stop a spin-off that takes the old
   ticker from reading as a continuation: A that lives on under another
   ticker (Delphi Automotive as APTV while Delphi Technologies took DLPH) is
   continued by nobody, and no continuation by timing is taken while A's
   issuer starts another line of its own at the handoff and B is another
   issuer's (old Liberty Media as STRZA while the new one took LMCA).
3. **Acting** (`apply_handoffs`). A continuation with no delisting of A near
   the handoff writes one: dated by A's ambiguous-class Form 25 (its
   `form25_unmatched` row) that took effect after A's last sighting and within
   30 days after the later of A's last and B's first sighting (not the Braves
   split-off's Form 25 a week before FWONA's last sighting; old LabCorp's five
   weeks after its sparse last fails row), else the day after A's last
   sighting; last trade on that sighting, but before B's first, `exchange_transfer` (CRSP 304, so DLRET 0),
   `successor_sec_id` = B, confidence `high` on a filing and `medium` on
   timing, flag `handoff_continuation`. A row near it takes B as its
   successor; an `unknown` or merger row is rewritten to the continuation's
   values (a merger keeps its old bucket in a `handoff_rebucketed` row),
   except a merger on timing evidence between two issuers (an acquirer's new
   holding company takes the target's ticker too: Wendy's into Wendy's/Arby's
   at 4.25 shares, IGT for cash and stock), or whose payout reconciled
   against timing evidence alone, a
   liquidation/compliance failure/expiration, or a row naming another
   successor: those stand, with a `handoff_conflict` row. A continuation drops
   A's `ended_without_delisting`, the ambiguous Form 25 rows of A and B it
   rests on, and the pair's `ticker_shared` rows. A takeover sets
   `ticker_successor_sec_id` = B on A's delisting nearest the handoff, else
   writes `handoff_takeover_no_delisting`.

**Stage 9c** (`pipeline._date_from_notices`) runs right after this stage, before
the added rows' price answers and closes. A continuation row built from an
unmatched Form 25 starts with its last sighting as its last trade day; 9c gives
it the day that Form 25's own EX-99.25 notice states (source `ex99_notice`, and
`observed_delist_date`), only when the day is confirmed (an involuntary
12d2-2(b) notice is not), is before B's first sighting, and is no later than the
row's `delist_date`. A failed read keeps the sighting and is reported as
`resolution_degraded`. Its SEC traffic is the `handoff notice dates` stage.

`run_manifest.json`'s `handoffs` key counts the pairs decided, continuations
by filing and by timing, takeovers, conflicts and rows added; its `stages`
carry the `handoff search` SEC traffic.

## Outputs

Nine CSVs written to `output/`, all committed artifacts; see `outputs/store.py` for
the exact schema. `delistings.csv` is the primary deliverable. The run also
writes the contract under `output/contract/` (stage 10g): `security_history.csv`,
`delistings.csv` (one row per ended security), `seeds.csv`, `price_requests.csv`
and `id_changes.csv`, beside the seven tables for one release.

`output/securities.csv`: one row per identified security — `sec_id`,
`issuer_cik`, `share_class`, `name`, `security_type`, `observed`,
`figi_source`.

`output/cusip_history.csv`: point-in-time CUSIP ranges per security, keyed by
`(sec_id, valid_from, cusip)`, built from observations plus SEC
fails-to-deliver rows. The ticker ranges are built the same way but no longer
written as `ticker_history.csv`: the run keeps them in memory as `ticker_history`
(the verdicts and the contract read them), and `contract/security_history.csv`
publishes them, split where the issuer in force changes, without the merger
acquirers the run adds (and without the `exchange` and `source` columns). In
memory, `ticker_history.exchange`
is filled for the range that ends in a delisting (from the Form 25) and for
the still-open range (from the issuer's current EDGAR submissions listing);
otherwise empty. `ticker_history.source` is `observation`, `ftd`, or
`edgar_8k`: an added successor security's range (an exchange-transfer
continuation, spec §8.5) is built directly from the 8-K that named it rather
than from FTD sightings; an added acquirer security's range still comes from
`ftd`.

A security's ranges are clipped at the last delisting that actually ends it
(`history.Histories`), not simply its last delisting: one whose
successor is the security itself (a continuing exchange transfer, D18) is
skipped. Beyond that, only a `merger` or `exchange_transfer` delisting with a
*confirmed* last-trade day (`LastTrade.confirmed`) is second-guessed at all: it is also skipped
when the security's own CUSIP keeps trading under its own ticker afterward —
at least 20 live fails rows over at least 60 days with 2 or more distinct
prices, so fails still settling at the last close don't count as continued
trading (WRK, a merger record after which WestRock kept trading). A
`liquidation`, `compliance_failure`, `expiration` or `unknown` delisting
always clips, however much (and however varied) the fails evidence that
follows: `ticker_history` records exchange listings (CONTEXT.md "Listing"),
and years of real, varying-price OTC pink-sheet trading after a bankruptcy
delisting (R H Donnelley, Smurfit-Stone Container, Idearc, General Growth
Properties) is not that listing continuing. An *unconfirmed* last-trade day
is equally too weak to second-guess: the classifier's no-Form-25 "continued
10-K/Q filings >180d after delist" fallback (`endings/delistings.py`'s
`_fallback_delisting`) substitutes the security's own last observed sighting
when it has no last-trade evidence at all, flagged
`last_trade_date_unconfirmed` — Monster Worldwide and SunPower both traded
normally for years past such a guessed date; the guess, not the listing, was
wrong. A security none of whose delistings ends it, and that is not listed
today either, is left unclipped, ending at its last real sighting.
Separately, an observation that `observation_map.csv` marks
`backfilled_ticker` (below) is never itself a ticker sighting here
(`history.filtered_ticker_sightings`) — a caller's
snapshot that projects today's ticker back onto a date the security did not
yet trade under it opens no range for that ticker; the delisting search's own
copy of the sightings (`ticker_sightings`, used for Form 25 matching and
last-trade dating) is untouched by either rule.

`output/observation_map.csv` (key `ticker, as_of, name, cusip, pin_cik,
pin_sec_id`): one row per distinct input observation (after the same
de-duplication `load_observations` does), naming the era it fell into, the
`sec_id` it resolved to (blank when none did), the era's issuer CIK, the
`ticker_history` spelling and coverage on that date (`history_ticker`,
`in_ticker_history`), and a `status` — the first of:

| Status | Rule |
|---|---|
| `unresolved` | the era's `sec_id` is None |
| `after_unconfirmed_delisting` | the security is not listed today, `as_of` is after its clipped `ticker_history` end (the same end date the paragraph above computes, not recomputed), and the delisting that set that clip has no confirmed last-trade day (`last_trade.day` is None, or flagged `last_trade_date_unconfirmed`) — the clip is a guess, so the caller keeps and checks this member instead of dropping it |
| `after_delisting` | the security is not listed today and `as_of` is after its clipped `ticker_history` end, whose delisting has a confirmed last-trade day |
| `conflict` | `(ticker, as_of)` is in `observations.observation_conflicts` (two names, one ticker, one day) |
| `backfilled_ticker` | `as_of` ≥ 2004-01-31, no fails-to-deliver row of the security's CUSIPs under the observed ticker (either separator spelling) within ±30 days, and at least one such row under another symbol in that window |
| `mapped` | everything else |

This is the caller's join surface: index membership comes from
`observation_map.csv` (every row that resolved is one observation's
`sec_id`), and a ticker lookup on a date goes through `contract/security_history.csv` by
`history_ticker` — the canonical spelling (`BF-B`, not the raw `BFB`) a
caller's own observed ticker may need normalizing to first. `--limit N` runs
only ever produce rows for the eras that ran; the log names how many of the
input's observations that is ("N of M observations mapped").

`output/delistings.csv`: one row per delisting event with the CRSP code,
bucket, confidence, evidence chain (Form 25 date, 8-K items, Form 15 form
name, resolved company name, which resolver tier won), the reconstructed
delisting return (`dlret`), the method that produced it, and the raw
extracted payout (`raw_payout_per_share`, `raw_payout_source`,
`raw_payout_confidence`) before the last-close gate runs. Columns are
`DELISTINGS_COLUMNS` in `outputs/store.py`. `resolution_source` records the resolver
tier that found the security's CIK, taken from the security's latest era
that has a CIK (`security_master` when none has one, and for a successor the
run added); `SecurityContext.resolution_source` →
`classify_event(resolution_source=...)` carry it to the row.

`delistings.csv`'s `payout_per_share` / `payout_source`: per-merger cash payout after the last-close gate:
only a payout (or cash+stock/stock-only terms) that reconciles with the
target's last trade close is kept, so a row the gate drops is blank there
even though the `raw_payout_*` columns still carry the raw extracted value.
The filing a payout came from is not published.

`output/review.csv`: the pipeline collects one candidate row per delisting
row whose `review_flags` is non-empty, plus every security with no delisting
at all (`ended_without_delisting`, `listing_status_unknown`,
`form25_unmatched`, `form25_unclassified`, `form25_unreadable`,
`observation_unresolved`, `error`), plus `ticker_history` consistency checks
(`ticker_range_overlap`: two of one security's own ranges overlap;
`ticker_shared`: the same ticker maps to two securities on the same day),
plus observation checks (`observation_conflict:<date>`: one row per ticker
observed under two or more names on that date, both kept, `sec_id` empty;
`ticker_unconfirmed`: an era from 2004 on with no fails-to-deliver row under
its ticker within 30 days of its span). Delisting rows can also carry
`acquirer_close_lagged` (the acquirer price in a merger's terms came from a
fails-to-deliver row later than the next trading day) and
`observed_after_delisting` (the delisting's Form 25 predates the security's
first observation and no fails-to-deliver row under its own tickers shows it
trading afterwards: the observations after it are a stale snapshot's).

`pipeline.py` adds a delisting to the triage input when it has flags **or**
a blank DLRET (`review_triage.is_blank`): `dlret.decide` can return NaN
with *no* flag at all when a `--last-trade-closes`/`--recoveries`/
`--merger-terms` override resolves to no consideration on a non-merger
bucket (the override was "given", so `no_last_close` is never added), and
such a row must still reach review, not vanish because `review_flags` was
empty.

`review_triage.triage()` (`outputs/review_triage.py`) first appends the token
`no_dlret` to every delisting row (non-blank `bucket`) whose `dlret` is still
blank, *before* any decision is applied — so accepting the row's other flags
never silently drops a delisting that still has no return; only supplying the
value or explicitly accepting `no_dlret` does. It then turns those candidate
rows plus `data/review_decisions.csv` (`--review-decisions`) into the final
`output/review.csv`: every row gets a leading `severity` — `fix` (`no_dlret`,
`observation_unresolved`, `ended_without_delisting` — a security that
stopped being observed with no delisting found has no DLRET either, and
would otherwise drop out of a backtest with no terminal return — or the
run/decisions file itself is broken: `error`, `resolution_degraded`,
`review_decision_unmatched`), `check` (a rule couldn't settle it), or `info`
(a less precise source, nothing suggests it's wrong) — and rows are ordered
by what they can move: `fix` before `check`; a delisting with a blank
`dlret` first (this grouping still reads `bucket`/`dlret` directly,
unaffected by tokens or decisions), then delisting rows by descending
`|dlret|`, then everything else; ties break on `(sec_id, delist_date,
ticker, review_flags)` and, for determinism, a few more columns. A flag's
severity can also depend on the row's `bucket`
(`FlagInfo.severity_by_bucket`/`severity_for`): `no_last_close`/
`no_last_trade_date` grade `info` on an `exchange_transfer` row (its DLRET
is 0 whatever the close, so the close changes no output) and stay `check`
elsewhere; `review_summary.csv`'s `severity` column always shows the
catalog's base severity, `in_review` reflects the downgrade. A row whose
remaining flags are all `info` is dropped from `review.csv` (a delisting
row's flags stay on `delistings.csv`; a security-level `info` flag such as
`no_figi` has no delisting row: it is counted in `review_summary.csv`, and
`securities.csv` lists every placeholder with `figi_source=placeholder`). A decision matches a row by the exact token and by
`(sec_id, delist_date, ticker)` compared as stripped strings (blank matches
blank); `error` and `resolution_degraded` can never be accepted; a decision
matching no row becomes a `fix` `review_decision_unmatched:<flag>` row (the
flag it names, not the bare name — so two stale decisions on one row get
distinct review keys instead of colliding) instead of vanishing, unless
`report_unmatched=False` (`pipeline.run()` passes `report_unmatched=(limit
is None)`: a `--limit` dev subset can only see a fraction of the rows a
decisions file was written against, so unmatched rows outside it are only
counted — `tri.counts["unmatched_decisions"]`, logged by the run — not
turned into review rows). `no_dlret` and `review_decision_unmatched:<flag>`
are the only tokens `triage()` itself creates — neither ever comes from the
pipeline or reaches `delistings.csv`. Decisions never change
`delistings.csv`. `output/review_summary.csv` (key `flag`) has one row per
flag name — `severity, flag, rows, in_review, accepted, description, action,
examples` — for triaging by cause; `scripts/accept_review.py --flag NAME
--note TEXT [--bucket B] [--yes]` bulk-appends `accept` decisions for every
row currently carrying that flag (`NAME` must be a bare `CATALOG` name, not
a token with a `:`; bulk-accepting a `fix`-severity flag needs `--yes`).
`append_decisions` validates an existing decisions file through
`load_decisions` first (both read `utf-8-sig`, so an Excel BOM doesn't blank
the first cell) and refuses to touch a file that doesn't load, rewriting a
valid one with every existing row/column preserved in the file's own header
order. Written by `scripts/classify_universe.py` alongside the other seven
output tables (eight in all, counting `uncertain.csv`).

## Downstream integration

`delistings.csv` is consumed by `delist_detection.handling.qlib_adapter`, joined on
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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A pipeline that builds a **FIGI-keyed security master** and a
**Form-25-driven delisting table** for a US-equity quant universe, from the
caller's own **observations** of what traded where (`ticker T seen on date
D`). It identifies each observed security (`sec_id` = US composite FIGI, or a
placeholder until one is confirmed), builds its ticker and CUSIP history,
finds every delisting from SEC EDGAR Form 25 filings, classifies each into a
CRSP-style `DLSTCD` code + bucket, dates the last trade and prices the
delisting return (DLRET) — all from **SEC EDGAR, SEC fails-to-deliver, SEC
MIDAS, the Nasdaq halt feed and OpenFIGI**. No Tiingo, no Alpha Vantage, no
price vendor. The library is self-contained and universe-agnostic: the
caller decides which securities to observe.

See `CONTEXT.md` for the domain vocabulary (security, listing, delisting,
observation, pin, …). Read `README.md` for the bucket policies, the CRSP
code table, and worked examples; `docs/data-flow.md` for the full classifier
trigger table and the pipeline diagram.

## Commands

The project's Python environment provides pytest, pandas, requests, and the
editable install.

```bash
pip install -e .                         # editable install (Python ≥3.10) — once per env
pytest                                    # full suite (1163 tests, offline, no network)
pytest tests/test_payout_extractor.py -v  # one file
pytest tests/test_payout_extractor.py::test_match_in_cash_family_altr -v   # one test

python scripts/verify_altair.py          # smoke: ALTR → CRSP 231, high
python scripts/classify_universe.py --observations obs.csv   # → output/{securities,ticker_history,cusip_history,delistings,payouts,review,review_summary}.csv (NETWORK; free when cached)
python scripts/classify_universe.py --observations obs.csv --limit 20 --no-extract-payouts --no-midas --no-halts   # fast dev subset
python scripts/classify_universe.py --observations obs.csv --sec-workers 1   # one SEC request at a time (default: 4 prefetch threads, max 8, one machine-wide 8 req/s limit)
python scripts/observations_from_snapshots.py --dir <folder of dated snapshot CSVs> --out obs.csv   # ticker/name columns, one date per file name
python scripts/observations_from_instruments.py --instruments all.txt --out obs.csv   # legacy (ticker,start,end) file → two observations per row
python scripts/verify_against_web.py     # independent EDGAR cross-check on output/delistings.csv → output/web_verification.csv
python scripts/regen_payout_fixtures.py  # refetch golden 8-K fixtures from live SEC
python scripts/build_golden_fixtures.py  # rebuild the 31-case golden regression set (NETWORK); --efts-only / --llm-only / --only ID
python scripts/accept_review.py --flag terms_gate_failed --note "sampled 5, all fine"   # bulk-accept every current review.csv row carrying that flag → appends to data/review_decisions.csv (offline); --bucket narrows, --dry-run previews, --yes required for a fix-severity flag
# End-to-end pipeline (the canonical way to use the library) — classify a universe → output/delistings.csv (+ 6 more tables), then firm-month-correct a returns panel:
python scripts/classify_universe.py --observations obs.csv --last-trade-closes lt.csv --merger-terms terms.csv --recoveries rec.csv   # → output/{securities,ticker_history,cusip_history,delistings,payouts,review,review_summary}.csv
python scripts/compute_corrected_returns.py --panel panel.csv --delistings output/delistings.csv --out corrected.parquet   # firm-month BMP correction, keyed on sec_id
# override-CSV columns are keyed by sec_id[,delist_date] (a blank/absent delist_date applies to every delisting of that security): lt.csv=`sec_id,last_trade_close[,delist_date]` · terms.csv=`sec_id,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker[,delist_date]` · rec.csv=`sec_id,recovery_ratio[,delist_date]`. A row that matches no delisting stops the run.
# --review-decisions PATH (default data/review_decisions.csv) is read the same way: sec_id,delist_date,ticker,flag,decision,note. Missing at the default path means no decisions; missing at an explicit path, or a bad file, exits 2.
# (append --limit N to classify_universe for a fast cached/offline subset)
# Auto-extract cash+stock merger terms with an LLM instead of hand-writing terms.csv (NETWORK: SEC + OpenAI; needs OPENAI_API_KEY + CHAT_MODEL in .env):
python scripts/classify_universe.py --observations obs.csv --extract-merger-terms-llm   # → output/delistings.csv with cash_plus_stock/stock_only rows
# LLM reads cash leg + stock ratio + acquirer ticker from EDGAR; acquirer_price is joined from SEC fails-to-deliver closes around the deal-completion date; a sanity gate (--merger-terms-sanity-tol, default 0.15) drops any term whose terminal value doesn't reconcile with last_trade_close. An explicit --merger-terms row always overrides the LLM. Calibrate the prompt with `python scripts/eval_merger_extractor.py` (10 labeled deals, live) before trusting a run.

# In this worktree the editable install still points at the main checkout, not this tree's src/ — prefix every script with PYTHONPATH=src, e.g.:
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations obs.csv
```

There is **no lint/format tooling** configured — do not invent a lint command.

## Architecture: two layers joined by `DelistRecord`

The codebase splits cleanly into a **classification layer** (network: EDGAR,
OpenFIGI, SEC data files) and a **handling layer** (pure, no network). The
`DelistRecord` dataclass (`classifier.py`) is the hand-off object between
them: `ticker, cik, observed_delist_date, crsp_code, bucket, confidence,
reason, evidence`, plus `sec_id`, `delist_date` and `successor_sec_id` —
optional fields the new pipeline (`delistings.py`/`pipeline.py`) fills in
alongside the original ones. `pipeline.py`'s `run()` is the orchestration
that turns a list of observations into the seven output tables: a short
`_run` calls one function per numbered stage (`_refine`, `_resolve_issuers`,
`_resolve_securities`, `_security_cusips`, `_find_delistings`,
`_check_overrides`, `_last_trade_closes`, `_merger_payouts`,
`_find_successors`, then the row builders and `_triage`), each with explicit
inputs and outputs and the run-wide `_RunContext` (clients, run date, log,
workers, SEC meter). See `CONTEXT.md` for the vocabulary its docstrings and
variable names assume (security, era, sighting, pin, …).

**Classification (network):**
- `observations.py` — `Observation`, `TickerEra`, `ObservationIndex`: splits
  one ticker's observations into eras (runs that belong to one security),
  splitting on a name mismatch, a pin change, or a gap over `ERA_GAP_DAYS`
  that neither side's name confirms as continuous.
- `edgar.py` — throttled, on-disk-cached SEC client. `submissions()`,
  `recent_filings()`, `fetch_filing_text()`/`fetch_filing_raw()` (HTML-stripped
  and raw text caches). Owns `EdgarBlocked`, the shared request throttle
  (`throttle()`), `resolve_user_agent()`, and `sec_get()`: the one SEC request
  path (throttle, User-Agent, SEC_STATS counting, `retry_request`, `EdgarBlocked`
  on 403/429) that `EdgarClient`, `sec_http.py` and `verify_against_web.py` share.
- `fatal.py` — `FATAL`: the exceptions that stop a run instead of becoming a
  review row (`EdgarBlocked`, `OpenFigiBlocked`, `OpenFigiUnavailable`).
- `atomic_io.py` — atomic file writes: `write_atomic` (one cache file, durable,
  through a writer-named temp file), `clean_orphan_temps` (a killed writer's
  leftovers), and `replace_on_success`/`replace_all_on_success` (the output
  tables and the decisions file, replaced only when the whole write succeeds).
- `sec_http.py` — throttled, cached `download()`/`get_text()` for the other SEC
  data files (FTD and MIDAS ZIPs and their index pages), sent through
  `edgar.sec_get` (so the same throttle, retries and `EdgarBlocked` on
  403/429). Index pages and ZIPs are both cached through
  `atomic_io.write_atomic` (text or bytes). Every cache file
  (EDGAR, SEC data files, MIDAS summaries, halt days, OpenFIGI and LLM answers)
  goes through it, and each client removes a killed run's temp files
  (`atomic_io.clean_orphan_temps`, also old `.part` downloads) when it starts.
- `ftd.py` — `FtdClient`/`FtdIndex`: SEC fails-to-deliver rows (`(date, CUSIP,
  symbol, price)`, 2004+). `close_after()` supplies every last-trade close and
  acquirer-completion price (`close_of`/`close_known_on`: by the security's
  CUSIP on the day, then its symbol); `by_cusip`/`by_symbol` supply CUSIP
  history, `trading_rows` the rows not under a deleted symbol, `symbol_deleted`
  whether a CUSIP's last rows are all under one, `descriptions` a CUSIP's names.
- `midas.py` — `MidasClient`: SEC MIDAS per-security exchange volume (2012+,
  ticker-keyed); `last_trade_day()` confirms the last day with lit+hidden
  exchange volume, suppressed to `None` when the window runs past MIDAS's
  coverage end and the found day is within 5 trading days of that edge (an
  unpublished quarter always yields nothing). A quarter that fails to
  download is remembered in-memory for the rest of the run.
- `nasdaq_halts.py` — `NasdaqHaltClient`: Nasdaq's keyless trade-halt feed;
  `deletion_halt()` finds a code-`D` ("security deletion") halt as a second
  last-trade-date confirmation when MIDAS has none.
- `openfigi.py` — `OpenFigiClient`: OpenFIGI `/v3/mapping` and `/v3/filter`,
  cached on disk (`atomic_io.write_atomic`: a run that dies mid-write leaves no
  cut-off answer), paced on the `ratelimit-*` headers. Owns `OpenFigiBlocked`
  (401/403) and `OpenFigiUnavailable` (timeouts/5xx after its retries).
- `figi_resolution.py` — pure rules turning an OpenFIGI answer into one US
  composite FIGI: `us_candidates()` groups rows by composite and keeps only US
  venues; `accept()` never trusts Bloomberg's current name alone (a dead line
  gets renamed to its acquirer) — a CUSIP hit needs no name check, a
  ticker/name hit does; `placeholder_id()` builds `CIK<cik>-<CLASS>` when
  nothing is confirmed.
- `ticker_resolver.py` — `(ticker, as_of_date) → CIK`, 6 strategies in order of
  precision (caller's `cik` pin → manual override → `company_tickers.json` →
  EFTS Form-25/15 → observation-name company search → 8-K frequency rank),
  each strict-validated. The pin and the observation name (from
  `ObservationIndex.cik_pin_on`/`.name_on`, wired in by `pipeline.py`) replace
  the old `--cik-map`/`--names` CLI files; the pin still beats every other
  tier and is never written to the on-disk resolver cache.
- `security_master.py` — `FigiResolver.resolve_many()` (a `sec_id` pin wins;
  else CUSIP jobs, then the ticker, then a name filter — see the spec's
  Implementation notes), `build_securities()` (merges eras sharing a
  `sec_id`), `candidate_cusips`/`era_cusips`/`era_last_seen` (FTD-confirmed
  CUSIPs and true last sighting; an era takes an FTD CUSIP only when a fails
  row's description names its issuer, `names.description_matches` against the
  observed and EDGAR names — spec D21), `ranges_from_sightings()` (turns dated
  `Sighting`s into `ticker_history`/`cusip_history` ranges). `Issuer` (a CIK
  and its EDGAR names; `issuers_by_era` builds the era key -> `Issuer` map
  `candidate_cusips` and `resolve_many` take) and `AddedAcquirer`/
  `AddedSuccessor` (a security the run adds, with its one ticker_history row)
  are its types. It also builds each security's sightings
  (`ticker_sightings`/`cusip_sightings`, `own_last_seen`), its
  `ticker_history`/`cusip_history` rows (`history_rows`), and checks the
  ticker ranges (`ticker_range_review`: `ticker_range_overlap`/`ticker_shared`).
- `successors.py` — the successor after a FIGI change: a security of the run
  that starts right after the last trade (`successor_in_run`, `SecurityStart`),
  else the successor issuer's 8-K12B found by full-text search
  (`successor_search_args`, `successor_query`, `successor_from_8k12b`,
  `successor_search_name`).
- `acquirers.py` — a merger's acquirer as a security: `find_acquirer` (its
  composite FIGI from the fails rows under the acquirer ticker) and
  `acquirer_cik` (its issuer CIK, never the target's).
- `form25.py` — parses a Form 25's XML or text (exchange, `class_text`, rule),
  labels the exchange, reads `class_kind` (common/preferred/warrant/unit/…)
  from the class text, and `match_security()`s it to one observed security of
  that kind/class letter.
- `listing_status.py` — `exchanges_around()`/`withdrawal_kind()`: reads the
  10-K cover page's exchange list before and after a Form 25 to tell a real
  delisting from the withdrawal of a secondary/regional listing while the
  main one continues; `listed_today()` for the completeness check;
  `issuer_exchange()` the exchange EDGAR's submissions JSON lists for a ticker.
- `last_trade.py` — `eightk_last_trade()` (Item 3.01 text) and
  `decide_last_trade()`, which picks among the Form 25 notice, the 8-K text,
  MIDAS and the Nasdaq halt (MIDAS beats a halt beats text; a text/measured
  disagreement is flagged `last_trade_date_conflict`).
- `delistings.py` — `DelistingFinder.find()`: lists an issuer's Form 25s,
  matches and groups them into one delisting per removal (chained within
  `SAME_EVENT_DAYS` of the group's earliest filing, across exchanges), dates
  and classifies each, and falls back to the classifier's no-Form-25 paths
  when none exists. `SecurityContext.sibling_spans` keeps a Form 25 from being
  matched to a sibling security that wasn't alive on the filing date.
- `classifier.py` — the filing-trio fingerprint (**Form 25 + 8-K item codes +
  Form 15**), now anchored on the Form 25/fallback filing date rather than a
  vendor end date. `_classify_items()` maps an 8-K item set to a `DLSTCD`
  code; the surrounding logic handles asset-type short-circuits,
  exchange-transfer detection, and SEC-revocation. Rule order unchanged.
- `crsp_codes.py` — the truth table: `DLST_CODE_TO_BUCKET` plus a leading-digit
  range fallthrough (`2xx→merger`, `3xx→exchange_transfer`, `4xx→liquidation`,
  `5xx→compliance_failure`, `6xx→expiration`). **The bucket — not the exact code
  — drives all downstream handling.**
- `payout_extractor.py` — bridges the layers: extracts the per-share **cash**
  merger consideration from EDGAR filing text (network, regex) for the `merger` bucket.
- `llm_merger_extractor.py` — the **cash+stock** counterpart: an LLM reads a
  filing and returns full structured terms (`cash_per_share`, `stock_ratio`,
  `acquirer_ticker`) the regex extractor can't generalize over. Uses
  `llm_client.py` (injectable OpenAI JSON client) and `filing_selection.py`
  (filing-tier picker shared with `payout_extractor.py`); responses cached under
  `cache/llm/`. Disabled by default — enabled by `--extract-merger-terms-llm`;
  `acquirer_price` and `last_trade_close` come from `ftd.py`, not a filing.
- `store.py` — every output table's column order, key and sort order
  (`TABLES`), `format_cell` (the one cell formatter every table shares),
  `write_table`/`write_tables`/`read_table` (all-or-nothing write via
  `atomic_io.replace_all_on_success`), and `read_frame` (a table as a typed
  pandas DataFrame, `FRAME_TYPES`: `qlib_adapter.load_delistings` reads
  through it). Every table read — `qlib_adapter`, `accept_review.py`,
  `verify_against_web.py` — goes through this module, so a later move to
  DuckDB changes only this module.
- `review_triage.py` — pure (no network): `CATALOG` maps every review flag to
  a severity (`fix`/`check`/`info`), a description and an action;
  `row_severity`/`triage()` turn the pipeline's merged review rows plus a
  decisions list into `review.csv` (severity-sorted, info-only rows hidden)
  and `review_summary.csv` (one row per flag). `Decision`/`load_decisions`/
  `ReviewDecisionError` read `data/review_decisions.csv`; `accept_by_flag`/
  `append_decisions` back `scripts/accept_review.py`'s bulk accept.
  `ReviewItem` is a flag raised outside a delisting's own row (the finder's,
  the security master's and the pipeline's), `.row()` its review row. Called
  by `pipeline.run()` just before the write; never touches `delistings.csv`.
- `trading_calendar.py` — NYSE trading days (weekends, exchange holidays,
  unscheduled closures); turns "suspended before the open on D" into the
  actual last trading day and lines up FTD rows (dated D, priced at D−1's close).

**Handling (pure), keyed by `sec_id`:**
- `handling.py` — event-level: `build_train_label_adjustment` (forward-return
  label) and `build_backtest_exit` (exit cashflow + universe-exit date), one
  deterministic policy per bucket. Each still takes a `DelistRecord` plus
  scalar `last_close`/`payout_per_share`/`recovery_ratio` (unchanged
  signature); `adjustments_from_rows` is the new wrapper that calls both
  straight from a `delistings.csv` row, via `qlib_adapter.record_from_row`/
  `row_payout` — no more ticker-keyed dictionary arguments to assemble.
- `bmp_correction.py` + `exchanges.py` — firm-month BMP 2007 correction:
  `R_month = (1+R_partial)(1+DLRET)−1`, synthesizing `DLRET` per bucket with
  exchange-specific Shumway constants when no realized delist return is observed.
- `dlret.py` — DLRET hub: `resolve_dlret`/`DlretResult`/`compute_dlret` (self-explaining delisting return). `bmp_correction.py` re-exports for backward compatibility.
- `reconstruction.py` — `EnrichedDelistRecord`, `enrich`, `build_delistings_table`,
  `delisting_row`. `output/delistings.csv` is the **primary output**, keyed by
  `(sec_id, delist_date)` (`DelistingKey`; `for_delisting` looks a delisting up
  in a map keyed by it or by the bare `sec_id`).
- `qlib_adapter.py` — DataFrame splicers over a `(datetime, instrument)` panel,
  where `instrument` is a `sec_id`: `inject_terminal_labels`,
  `apply_backtest_exits`, `apply_bmp_corrections`, each reading every input
  straight off the matching `delistings.csv` row. All three, and
  `handling.adjustments_from_rows`, skip a row whose `successor_sec_id`
  equals its own `sec_id` (a continuing security, e.g. an exchange transfer
  that kept the same FIGI) — it isn't an exit, so no label/exit/correction
  is emitted for it.

There are **two return-correction APIs** for different research conventions:
event-level (`handling.py`) vs CRSP-style firm-month (`bmp_correction.py`). Don't
conflate them.

## Non-obvious invariants

- **SEC fair access.** `EdgarClient` throttles to 8 req/s and requires a
  descriptive `User-Agent`. Every response is cached under `cache/edgar/` (JSON)
  and `cache/edgar/text/` (stripped filing HTML), so re-runs cost nothing; these
  caches are gitignored and re-derivable. The User-Agent comes from
  `EDGAR_USER_AGENT` (environment first, then the repo `.env`, via
  `edgar.resolve_user_agent()`); SEC 403s the noreply fallback, so set it.
  `sec_http.py` (FTD, MIDAS) shares the same throttle, User-Agent and
  `EdgarBlocked`. `WebFetch` is **403'd by SEC** — for ad-hoc EDGAR fetches use
  `curl -A "$(python -c 'from delist_detection.edgar import resolve_user_agent as r; print(r())')"`.
  A connection error, a timeout, or a 5xx on `_get_json`/`fetch_filing_raw`/
  `fetch_filing_text`/`full_text_search`/`sec_http` downloads retries up to 3
  attempts (2s/4s backoff, `edgar.retry_request`, inside `edgar.sec_get`); a 403/429 still raises
  `EdgarBlocked` at once, and a failure is never cached.
  The limiter (`edgar.SEC_LIMITER`) is shared by every thread of the process
  and, through `~/.cache/delist_detection/sec_rate.lock`
  (`$DELIST_DETECTION_SEC_RATE_LOCK`), by every SEC client on the machine
  (`edgar.use_machine_wide_limit()`, installed by the CLI, `default_clients`,
  `verify_against_web.py` and `build_golden_fixtures.py`). `--sec-workers N`
  threads prefetch through it (`prefetch.warm`); they only fill missing cache
  entries, so output is byte-identical for any N given the same caches and run
  date. A 5xx pauses every thread. The CLI refuses to start without
  `EDGAR_USER_AGENT`. Full-text-search and company-search answers, empties
  included, are cached with a TTL (see `docs/data-flow.md`); a resolver miss is
  never cached. An agent sandbox must set `DELIST_DETECTION_SEC_RATE_LOCK` to a
  writable shared path (the default `~/.cache/...` path may not be writable or
  shared there); this repo's agent runs use the one path
  `/tmp/claude/delist_detection/sec_rate.lock`. An agent-sandbox run and a
  terminal run therefore use *different* lock files and never share a gate —
  only one SEC client may run at a time across the two, coordinated by hand
  (the controller confirms no other client is running before a live run).
- **Measured SEC request speed** (task 16's live measurement, 2026-09-24). Cold
  runs on 150 eras: 1 worker 18m, 4 workers 11m, 8 workers 5m (3.6× wall time; issuer resolution 4.6×). A fully
  warm full-universe rerun takes about 3–4 min (2m47s at 1 worker, 4m13s at 4) with 0 SEC requests. Use
  `--sec-workers 8` for a cold or large refetch; use `--sec-workers 1` for a
  rerun whose caches are already warm (a warm pass redoes each stage's CPU
  work but sends no request, so 4 workers is about 50% slower than 1 on a
  fully warm rerun); the CLI default stays 4. SEC's company-name search
  (`cgi-bin/browse-edgar`, the resolver's fallback tier) is 89% of cold
  issuer-resolution time and can slow to ~10 s/request after about 1,500
  searches in under an hour, recovering after ~20 idle minutes — every such
  answer is a normal 200, so nothing in the code notices the slowdown; it only
  costs time. Peak memory is 1.8–4.2 GB (mostly data, likely the fails-to-deliver panel; not profiled);
  threads add at most about 37 MB (measured). SEC does not keep full-text-search hit order
  stable between two fetches of the same query: the same cache always gives
  the same output, but a refetch can reorder tied hits (see `docs/data-flow.md`).
- **OpenFIGI refusals abort too.** A 401/403 from OpenFIGI raises
  `OpenFigiBlocked` (`openfigi.py`); `classify_universe.py`'s CLI catches it
  alongside `EdgarBlocked` and exits 2. Every exception that stops a run is
  listed once, in `fatal.FATAL`: the pipeline's per-security and per-payout
  error handling, `listing_status.listing_answers`, the prefetch pool and the
  CLI all catch that tuple, so a new one is added there only. A 429 is waited out on the
  `ratelimit-*`/`retry-after` headers, never cached as an answer. Timeouts,
  connection errors or 5xx answers that outlast the client's retries raise
  `OpenFigiUnavailable` (not a subclass of `OpenFigiBlocked`): the run stops
  before writing anything, nothing is cached, no placeholder stands in for the
  answer (it would change `sec_id`s between runs), and the CLI prints "OpenFIGI
  unavailable after retries; no outputs written; rerun later" and exits 1. The key
  comes from `OPEN_FIGI_API_KEY` (environment first, then the repo `.env`),
  sent as header `X-OPENFIGI-APIKEY`. Exit 3 is a completed run whose
  `review.csv` has one or more `error` or `resolution_degraded` rows (an answer
  rested on a failed SEC request or a stale copy); outputs are still written,
  and a banner goes to stderr with the counts. This tally is taken *before*
  `review_triage.triage()` runs, so it is unaffected by decisions or hidden
  info-only rows — an `error`/`resolution_degraded` row always trips exit 3,
  whether or not a decision also exists for it (it can't: both flags are
  `acceptable=False`).
- **`review.csv` is triaged, not raw; `review_summary.csv` groups it by
  cause.** `review_triage.triage()` gives every row a `severity` — `fix`
  (`no_dlret`, `observation_unresolved`, `ended_without_delisting`, or the
  run/decisions file itself is broken: `error`, `resolution_degraded`,
  `review_decision_unmatched`), `check` (a rule couldn't settle it), or `info`
  (a less precise source, nothing suggests it's wrong). `no_dlret` is
  injected onto every delisting row (non-blank `bucket`) whose DLRET is still
  blank, *before* decisions are applied, so accepting a row's other flags
  never silently drops a delisting that still has no return — only supplying
  the value or explicitly accepting `no_dlret` itself does; `pipeline.py`
  adds a delisting to the triage input when it has flags **or** a blank
  DLRET (`review_triage.is_blank`), since `resolve_dlret` can return NaN with
  *no* flag at all (a `--last-trade-closes`/`--recoveries`/`--merger-terms`
  override that resolves to no consideration on a non-merger bucket — the
  override was "given", so `no_last_close` is never added). A flag's severity
  can be bucket-conditional (`FlagInfo.severity_by_bucket`,
  `FlagInfo.severity_for(bucket)`): `no_last_close`/`no_last_trade_date`
  grade `info` on an `exchange_transfer` row (its DLRET is 0 whatever the
  close) and stay `check` elsewhere; `review_summary.csv`'s `severity` column
  always shows the catalog's *base* severity, while `in_review` reflects the
  downgrade. Rows are ordered by what they can move: `fix` before `check`;
  within that, a delisting with a blank DLRET first (this grouping is
  unchanged — it reads `bucket`/`dlret` directly, not tokens), then delisting
  rows by descending `|dlret|`, then everything else; ties break on
  `(sec_id, delist_date, ticker, review_flags)` and, for full determinism, a
  few more columns after that. A row whose remaining flags are all `info`
  leaves `review.csv` — a delisting row's flags stay on `delistings.csv`; a
  security-level `info` flag such as `no_figi` has no delisting row: it is
  counted in `review_summary.csv`, and `securities.csv` lists every
  placeholder (`figi_source=placeholder`).
  `output/review_summary.csv` has one row per flag name: severity, how many
  rows carried it, how many are still in review, how many tokens were
  accepted, its catalog description/action, and up to 3 examples.
  `data/review_decisions.csv`
  (`sec_id,delist_date,ticker,flag,decision,note`, `decision` always
  `accept`) is a person's "I checked this exact flag on this exact row, it's
  fine": a decision matches only the identical `(sec_id, delist_date, ticker,
  flag)` (blank cells match blank; the flag is the full token, e.g.
  `terms_gate_failed:no_acq_price`, never just the name before `:`);
  `error`/`resolution_degraded` can never be accepted
  (`CATALOG[...].acceptable is False` — the run itself failed, the fix is a
  rerun, not a decision); a decision that matches no row becomes a `fix`
  `review_decision_unmatched:<flag>` row (the flag it names, not the bare
  name — so two stale decisions on one row get distinct review keys instead
  of colliding) instead of being silently dropped, *unless* `triage(...,
  report_unmatched=False)` — `pipeline.run()` passes `report_unmatched=(limit
  is None)`, so a `--limit` dev subset (which can only see a fraction of the
  rows a decisions file was written against) doesn't flood `review.csv` with
  noise; `counts["unmatched_decisions"]` still counts them regardless, and
  the run logs how many were skipped. Decisions never change `delistings.csv`.
  `classify_universe.py --review-decisions PATH` reads this file (default
  `data/review_decisions.csv`; missing at the default path means no
  decisions; missing at an explicit path, or a `ReviewDecisionError`, is
  reported on stderr and exits 2 — unlike a bad `--last-trade-closes` /
  `--merger-terms` / `--recoveries` file, which is not yet guarded and
  currently crashes with an uncaught traceback, exit 1).
- **`scripts/accept_review.py` refuses mistakes rather than silently doing
  nothing.** `--flag NAME --note TEXT [--bucket B] [--yes] [--dry-run]`
  bulk-accepts every row currently carrying flag `NAME` in one
  `data/review_decisions.csv` append. `NAME` must be a bare name in
  `review_triage.CATALOG` — a full token copied from `review.csv` (with a
  `:` in it, e.g. `payout_gate_failed:45.5`) or a typo (`no_last_clsoe`) used
  to silently match nothing and print "added 0 decision(s)"; both now exit 2
  (`review_triage.accept_by_flag` itself refuses them, so any direct caller
  gets the same protection). Zero matches print a warning instead of nothing.
  Bulk-accepting a **`fix`**-severity flag (`no_dlret`, `observation_unresolved`,
  `ended_without_delisting`) needs `--yes` — one note would otherwise clear
  every row of that cause at once, reopening the exact hole `no_dlret` closed
  — and the refusal says how many rows it would clear. `append_decisions`
  validates an existing decisions file through `load_decisions` first (both
  now read `utf-8-sig`, so an Excel-written BOM doesn't blank the first
  cell) and refuses (exit 2, nothing written) to touch a file that doesn't
  load; a file that does load is rewritten with every existing row and every
  existing column — including ones `load_decisions` itself ignores — in the
  file's own header order, never reformatted or dropped. A real write prints
  "rerun classify_universe.py to apply them"; `--dry-run` does not.
- **Every output is written only after the whole run succeeds.**
  `pipeline.run()` computes every table in memory first and writes all seven
  only at the end (`store.write_tables`, all or nothing), so a refusal or a
  bad override CSV midway through a run never leaves a half-written table
  over the previous complete one.
- **`sec_id` is a US composite FIGI, or a placeholder.** When no FIGI can be
  confirmed it is `CIK<cik>-<CLASS>` (`figi_resolution.placeholder_id`) —
  still a stable, joinable key, just not a real FIGI. `figi_resolution.py`
  never accepts a candidate on Bloomberg's current name alone: a dead line
  gets renamed to its acquirer, so acceptance needs a CUSIP match, or a
  ticker+name match against the observation name or, failing that, the
  issuer's EDGAR names (current and former; `FigiResolver` drops such a match
  when another era's pin or CUSIP contradicts it, or when it would leave a
  same-class sibling era alone on the issuer's placeholder). The spec's third
  route, an acquirer/successor name match, is not built (spec §17).
- **A delisting is a Form 25 removal — not a rename, not a secondary
  withdrawal.** A rename or an exchange move that keeps the security trading
  is not a delisting; withdrawing a secondary/regional listing while the main
  one continues (Apache/Chicago 2020) creates no row (`listing_status.py`). A
  security can have more than one delisting (an exchange transfer, later a
  merger).
- **Tests are fully offline.** They use a `FakeEdgar` fixture (`tests/conftest.py`)
  and committed text fixtures (`tests/fixtures/`); every new client (OpenFIGI,
  FTD, MIDAS, Nasdaq halts) has its own fake or fixture-backed double; never
  add network to the test path. Golden fixtures are regenerated out-of-band by
  `scripts/regen_payout_fixtures.py`.
- **Ticker recycling** (e.g. ALTR was Altera then Altair) is handled by
  `observations.split_eras` (a new era per security, on a name mismatch, a
  pin change, or an unconfirmed gap) and by `MANUAL_OVERRIDES` in
  `scripts/classify_universe.py` (~35 ambiguous short tickers). When web
  verification proves a wrong CIK, extend that dict — don't patch the resolver.
- **Payout extraction is cash-only; the DLRET table supports full consideration.** Auto-extraction from EDGAR remains cash-only. The DLRET table abstains (neutral mark) only when no consideration terms are supplied; when stock-leg terms (`stock_ratio`, `acquirer_price`) are provided via `--merger-terms`, it computes the full cash+stock consideration (e.g. AET→CVS: $145 cash + 0.8378 CVS @ $80 = $212.02, DLRET = +11.6%). The `--last-trade-closes`, `--recoveries`, and `--merger-terms` CSVs are keyed by `sec_id` and accept an optional `delist_date` column for per-event overrides (blank/absent = applies to all delistings of that security); a row matching no delisting stops the run.
- **The resolver cache is versioned.** `cache/ticker_resolution.json` carries
  `{"__version__": 3, ...}` (versions 2 and 3 load; an older file is ignored, not
  trusted, and replaced on the next save) and never holds a miss or an answer
  that rested on a failed request or a stale copy. The pipeline writes it after
  each resolving stage and on the way out of a run.
- **`payouts.csv` is gated; `delistings.csv` carries the raw extraction
  alongside it.** Every merger payout is checked against the last trade close
  (`payout_gate.reconcile`) before it reaches `payouts.csv`; `delistings.csv`
  keeps the raw, unchecked extraction in its `raw_payout_per_share` /
  `raw_payout_source` / `raw_payout_confidence` columns.
- **The golden set is the regression gate.** `tests/fixtures/golden/` (31
  cases, from `data/golden_events.csv`) replays real EDGAR responses
  offline; every case must stay green. `scripts/build_golden_fixtures.py`
  rebuilds it after a live-data change.
- **Validation is the EDGAR-cross-check loop**, not eyeballing: start from
  `output/review_summary.csv`, work `review.csv` top down, record each
  accepted row in `data/review_decisions.csv`, then re-run
  `classify_universe.py`, then `verify_against_web.py` on
  `output/delistings.csv` (and curl the cited accession) to confirm output
  against an independent path. Drill mismatches to root cause and re-run.
- **Configurable input paths.** `classify_universe.py` requires
  `--observations` (a CSV of `ticker, as_of[, name, cusip, cik, sec_id]`,
  built by `observations_from_snapshots.py` / `observations_from_instruments.py`
  or hand-supplied) and reads `--output-dir`/`--cache-dir` with repo-local
  defaults; it writes seven tables to `output/`, all committed artifacts.

## Design/plan docs

Specs and implementation plans live under `docs/superpowers/specs/` and
`docs/superpowers/plans/` (e.g. the BMP correction and payout-extraction
features). Follow that location for new feature design docs.

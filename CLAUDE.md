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
pytest   # full suite (3107 passed, 45 xfailed: 8 known-wrong golden + the diagnosis truth set's 37 known_wrong cases, all residual, all strict; offline, no network)
pytest tests/test_payout_extractor.py -v  # one file
pytest tests/test_payout_extractor.py::test_match_in_cash_family_altr -v   # one test

python scripts/verify_altair.py          # smoke: ALTR → CRSP 231, high
python scripts/scorecard.py              # offline: recompute output/'s scorecard vs data/scorecard.json; --check (exit 1 on a drop or a failing golden or diagnosis `pass` case), --base REV (recompute the regression report against that commit; --check then also fails on `D.unexplained_regressions` above 0), --write, --raise-floor, --lifecycles PATH
python scripts/build_diagnosis_truth.py   # the diagnosis truth file from the normalization pass (OpenFIGI for new CUSIPs; --no-figi offline)
python scripts/regression_report.py --base <commit>    # offline: contract changes outside the truth set -> output/regression_report.csv
python scripts/truth_loop_round.py --label 5a --base <commit> --round 1   # offline: one loop round's new errors -> loop/<label>/round-<N>/cases.csv (--seed-ledger records current mismatches as known)
python scripts/update_truth.py --label 5a --round 1 --base <commit>      # offline: apply the round's diagnoses to data/diagnosis_truth.csv, the change log and the ledger (--dry-run)
python scripts/scorecard.py --base REV --ledger PATH   # the ledger scorecard reads for D.unexplained_regressions (default output/diagnose_unknown_report/loop/diagnosed.csv; computed only with --base, never from output/regression_report.csv)
# The loop: run the Workflow tool with scriptPath ".claude/workflows/diagnosis-truth-loop.js" and args {"label": "<sub-plan>", "base": "<commit>"} (prepared cases: add "casesPath", which makes the update a dry run; at most 3 rounds, 5 agents). Normalization: scriptPath ".claude/workflows/diagnosis-truth-normalize.js", args {"cases": [...], "batch": 10}. Workflows are run by path; name lookup does not find them.
python scripts/draw_audit_sample.py --out data/accuracy_audit.csv   # offline: draw the decision-17 audit worksheet once (census + 100 random, seed 7)
python scripts/build_line_fixtures.py    # offline: tests/fixtures/lines/ (the line follow's real cases) from the local caches; rerun only to add a case
python scripts/build_form25_fixtures.py  # offline: tests/fixtures/form25_reach/ (sub-plan 5b's real Form 25 cases) from the local caches; rerun only to add a case
python scripts/build_issuer_role_fixtures.py  # offline: tests/fixtures/issuer_role/ (sub-plan 5c's real cases) from the local caches; rerun only to add a case
python scripts/build_last_trade_fixtures.py  # offline: tests/fixtures/last_trade/ (sub-plan 5d's last trade cases, 5c's builder) from the local caches
python scripts/build_acquirer_gate_fixtures.py --repo <checkout with output/ and cache/>   # offline: tests/fixtures/acquirer_gate/ (sub-plan 5e's acquirer line and gate cases), read-only on the caches
python scripts/build_distress_fixtures.py --repo <checkout with output/ and cache/>   # offline: tests/fixtures/distress/ (sub-plan 5g's drop and bankruptcy cases), read-only on the caches
python scripts/build_identity_fixtures.py --repo <checkout with output/ and cache/>   # offline: tests/fixtures/identity/ (sub-plan 5h's identity cases), read-only on the caches
python scripts/classify_universe.py --observations obs.csv   # → output/{securities,ticker_history,cusip_history,delistings,payouts,review,review_summary,observation_map,uncertain}.csv + contract/{security_history,delistings,seeds,price_requests,id_changes,payout_legs}.csv + scorecard.json (NETWORK; free when cached)
python scripts/classify_universe.py --observations obs.csv --limit 20 --no-extract-payouts --no-midas --no-halts   # fast dev subset
python scripts/classify_universe.py --observations obs.csv --sec-workers 1   # one SEC request at a time (default: 4 prefetch threads, max 8, one machine-wide 8 req/s limit)
python scripts/classify_universe.py --observations obs.csv --as-of 2026-09-25   # pin the run date (default today; run_manifest.json records it) to reproduce an earlier run's tables from the same caches
python scripts/classify_universe.py --observations obs.csv --price-answers answered.csv   # contract/price_requests.csv plus a price column: a second run changes values only; a row that answers no request exits 2
python scripts/classify_universe.py --observations obs.csv --id-baseline output/securities.csv   # compare placeholders with this securities.csv for contract/id_changes.csv (default: OUTPUT_DIR/securities.csv)
python scripts/seeds_from_observations.py --observations data/observations.csv --out seeds.csv   # one row per introduction: the seeds-only input
python scripts/observations_from_snapshots.py --dir <folder of dated snapshot CSVs> --out obs.csv   # ticker/name columns, one date per file name
python scripts/observations_from_instruments.py --instruments all.txt --out obs.csv   # legacy (ticker,start,end) file → two observations per row
python scripts/verify_against_web.py     # independent EDGAR cross-check on output/delistings.csv → output/web_verification.csv
python scripts/regen_payout_fixtures.py  # refetch golden 8-K fixtures from live SEC
python scripts/build_golden_fixtures.py  # rebuild the 31-case golden regression set (NETWORK); --efts-only / --llm-only / --only ID
python scripts/accept_review.py --flag terms_gate_failed --note "sampled 5, all fine"   # bulk-accept every current review.csv row carrying that flag → appends to data/review_decisions.csv (offline); --bucket narrows, --dry-run previews, --yes required for a fix-severity flag
# End-to-end pipeline (the canonical way to use the library) — classify a universe → output/delistings.csv (+ 8 more tables), then firm-month-correct a returns panel:
python scripts/classify_universe.py --observations obs.csv --last-trade-closes lt.csv --merger-terms terms.csv --recoveries rec.csv   # → output/{securities,ticker_history,cusip_history,delistings,payouts,review,review_summary,observation_map,uncertain}.csv + contract/{security_history,delistings,seeds,price_requests,id_changes,payout_legs}.csv + scorecard.json
python scripts/compute_corrected_returns.py --panel panel.csv --delistings output/delistings.csv --out corrected.parquet   # firm-month BMP correction, keyed on sec_id
# override-CSV columns are keyed by sec_id[,delist_date] (a blank/absent delist_date applies to every delisting of that security): lt.csv=`sec_id,last_trade_close[,delist_date]` · terms.csv=`sec_id,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker[,delist_date]` · rec.csv=`sec_id,recovery_ratio[,delist_date]`. A malformed file, or a row that matches no delisting, stops the run before anything is written (exit 2, one stderr line naming the file and line).
# --review-decisions PATH (default data/review_decisions.csv) is read the same way: sec_id,delist_date,ticker,flag,decision,note. Missing at the default path means no decisions; missing at an explicit path, or a bad file, exits 2.
# (append --limit N --output-dir /tmp/sub to classify_universe
# for a fast cached/offline subset; never write a subset into output/, the committed-output tests read it)
# Auto-extract cash+stock merger terms with an LLM instead of hand-writing terms.csv (NETWORK: SEC + OpenAI; needs OPENAI_API_KEY + CHAT_MODEL in .env):
python scripts/classify_universe.py --observations obs.csv --extract-merger-terms-llm   # → output/delistings.csv with cash_plus_stock/stock_only rows
# LLM (prompt v3, sub-plan 5f) reads the package one share became from EDGAR: cash leg and its currency, stock ratio (or a dollar value), acquirer name/ticker/class, further legs of a basket; acquirer_price is joined from SEC fails-to-deliver closes around the deal-completion date; a sanity gate (--merger-terms-sanity-tol, default 0.15) drops any term whose terminal value doesn't reconcile with last_trade_close. An explicit --merger-terms row always overrides the LLM. Calibrate the prompt with `python scripts/eval_merger_extractor.py` (10 labeled deals, live; `--truth` replays the diagnosis truth rows) before trusting a run.

# In this worktree the editable install still points at the main checkout, not this tree's src/ — prefix every script with PYTHONPATH=src, e.g.:
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations obs.csv
```

There is **no lint/format tooling** configured — do not invent a lint command.

## Architecture: two layers joined by `DelistRecord`

The codebase splits cleanly into a **classification layer** (network: EDGAR,
OpenFIGI, SEC data files) and a **handling layer** (pure, no network). The
`DelistRecord` dataclass (`classifier.py`) is the hand-off object between
them: `ticker, cik, observed_delist_date, crsp_code, bucket, confidence,
reason, evidence`, plus `sec_id`, `delist_date`, `successor_sec_id` (a
continuation only) and `ticker_successor_sec_id` (a ticker takeover) —
optional fields the new pipeline (`delistings.py`/`pipeline.py`) fills in
alongside the original ones. `pipeline.py`'s `run()` is the orchestration
that turns a list of observations into the nine output tables: a short
`_run` calls one function per numbered stage (`_refine`, `_resolve_issuers`,
`_resolve_securities`, `_security_cusips`, `_follow_lines` (stage 4b: each security's line followed past its
observations across a CUSIP or ticker change, `line_follow.py`; the same security takes the new CUSIP and ticker,
a placeholder folds into the FIGI line its new CUSIP names, a FIGI line with another composite records a line
successor for stage 9; metered as "line follow"; sub-plan 5h's `_today_holder_fold`: a ticker-tier line whose
candidate holds the ticker today folds into its next CUSIP's composite when that composite left the ticker, CRC and
BTU, whose post-bankruptcy lines took the ticker), `_other_issuers` (stage 4c: the one CIK other than a
security's own that was its issuer in force on every sighting, `issuer_in_force.issuer_changes`; stage 5 reads its
Form 25s too; metered as "other issuers in force"), `_find_delistings`,
`_dead_before_sighting` (stage 5b: a security whose last real ending came before its
first observation and that has no trading fails row died before the run's fails
window began, so (eligibility decided first, then) rows for [end − 1095 d, end + 10 d] are loaded, it takes the
CUSIPs `history.backfill_cusips` finds that no other security holds and its sightings are rebuilt; no `sec_id`
or issuer changes),
`_check_overrides`, `_last_trade_closes` (stage 7: a `--last-trade-closes` row, else the caller's answer to the
delisting's `last_close` request, `price_requests.PriceAnswers`, else the fails close), `_merger_values` (stage 8:
one call into `merger_value.value_mergers`, which answers one `MergerValue` per merger ending; the module map has
its steps), `_r1_continuations` (stage 8b: a merger whose published terms are one share and no cash, whose registrant's filings say the same of its own shares (`exchange_terms.own_exchange`), into a new issuer at most `NEW_ISSUER_DAYS` old or the same issuer (`successors.successor_by_terms`, else the new issuer's 8-K12B), is an exchange transfer to that successor, flagged `r1_continuation`, its payout reads dropped (`rewrites.continuation`, `Rule.R1`, with the run's merger values); the LLM's final terms must agree; the new issuer is named by the R1 statement's target (the name tie, below), its 8-K12B candidate included; a degraded read keeps the merger and flags the row; the run logs `role refusal: N rows (...)`, the delistings whose end-of-era reading refused a merger on the registrant's role; metered as "R1 continuations"),
`_find_successors` (stage 9, with sub-plan 5c's `_terms_links` before the 8-K12B search: the same issuer's class, a new issuer, or the security's own same-CIK 8-K12B line via OpenFIGI and R2; a name tie for any 8-K12B link; sub-plan 5h: `_own_registration_link` takes a text-named CUSIP with no fails row
yet when the fails data ends before the day, OKE 2026: the added successor starts on the next trading day, as every successor the run adds does (`last_trade.first_day_after`), and a Form 25 that already owns a delisting of the run raises no unmatched row in stage 9d; the stage ends by recording its links as rewrites, `_link_successors`), `_handoffs` (stage 9b: first `rewrites.mark_going_on`, the clip check's merger or transfer that does not end its security goes on as itself, here and only here, so the handoffs see it; then the handoffs), `_date_from_notices` (stage 9c: `last_trade.Dating.from_notice`, a handoff continuation row's last trade day from its own Form 25's confirmed EX-99.25 notice, when before the successor's first sighting, the handoff rewrite's typed `successor_from`, and no later than the effective date; the stage keeps the failed-read watch; metered as "handoff notice dates"), `_successor_endings` (stage 9d: the Form 25 search, matches only, for the line and 8-K12B successors the run added; the finder's items about a Form 25 that already owns a delisting are dropped by their typed `ReviewItem.filing`; metered as "successor endings"), `_distress` (stage 9e,
sub-plan 5g: for each liquidation, compliance-failure or unknown delisting with no successor, a bankruptcy plan's
stock rule (R6), a price-only removal's code 552, and the OTC symbol of its first off-exchange print, anchored on the
last trade day stage 5 dated; `distress.DistressTerms` for the contract; metered as "distress notices"; at stage 10a a
plan's `received_close` answer times its ratio is that ending's value and an answered OTC print a drop's, each read
through its own request, `PriceAnswers.ending_values`), then the row builders (stage 8's records feed 10a, 10c and
10g: `MergerValues.table_inputs`, `payout_rows`, `contract_inputs` and `requests`) and `_triage`; the contract (stage 10g) takes sub-plan 5h's `_era_renames` too: each placeholder whose eras
now hold one FIGI line is a `contract/id_changes.csv` rename, across a class label), each with explicit
inputs and outputs and the run-wide `_RunContext` (clients, run date, log,
workers, SEC meter `manifest.StageMeter`). Each stage returns what it produces
(`_Successors` for stage 9, for instance) and `_run` combines the answers. Every change of an ending's kind or
successor after the finder built it is a rewrite (`rewrites.py`), never a stage's own field edit. Helpers that
belong to one kind of data live with it, not in `pipeline.py`:
`issuer_record.py` (every stage's reads of an issuer's EDGAR record, `Clients.issuers`, and their failure policy),
`rewrites.py` (an ending's kind, successor, flags and provenance after it is built),
`degraded.py` (the `resolution_degraded` rows and flags), `ftd.close_age`,
`review_triage.merge_review_rows`, the era review rows in `security_master`.
See `CONTEXT.md` for the vocabulary its docstrings and variable names assume
(security, era, sighting, pin, …).

**Classification (network):**
- `observations.py` — `Observation`, `TickerEra`, `ObservationIndex`: splits
  one ticker's observations into eras (runs that belong to one security),
  splitting on a name mismatch, a pin change, or a gap over `ERA_GAP_DAYS`
  that neither side's name confirms as continuous. `regular_way` maps a when-issued ticker to its regular-way one
  (EHAB-WI is EHAB): `ObservationIndex` groups by it and each era carries it, while each observation keeps the
  caller's ticker.
- `edgar.py` — throttled, on-disk-cached SEC client. `submissions()`,
  `recent_filings()`, `fetch_filing_text()`/`fetch_filing_raw()` (HTML-stripped
  and raw text caches). Owns `EdgarBlocked`, `resolve_user_agent()`, and
  `sec_get()`: the one SEC request path (`sec_limiter.throttle`, User-Agent,
  `sec_stats` counting, `retry_request`, `EdgarBlocked` on 403/429) that
  `EdgarClient`, `sec_http.py` and `verify_against_web.py` share.
- `sec_limiter.py` — the SEC rate limit: `SEC_LIMITER` (a `RateLimiter`, 8
  request starts/s across the process's threads), `MachineGate` and
  `use_machine_wide_limit()` (the same limit across every process on the
  machine through the lock file), `throttle()` (every SEC request waits here),
  `PrefetchCancelled`.
- `sec_stats.py` — the counters behind run_manifest.json: `SEC_STATS` (a
  `RequestStats`: requests, cache answers and latency per endpoint,
  `endpoint_of`, and degraded answers), and fill-only mode (`fill_only`/
  `filling_only`: a prefetch thread only fills missing cache entries).
- `fatal.py` — `FATAL`: the exceptions that stop a run instead of becoming a
  review row (`EdgarBlocked`, `OpenFigiBlocked`, `OpenFigiUnavailable`).
- `retries.py` — `retrying()`: the one retry loop (attempts, the wait between
  them) behind SEC's `edgar.retry_request`, `OpenFigiClient._post` and
  `NasdaqHaltClient.halts_on`; each client passes its own policy (what is
  retried, how long to wait, what a refusal raises).
- `settings.py` — `env_setting()`: a setting from the environment, else the
  repo `.env` (one key only, `os.environ` untouched), behind
  `edgar.resolve_user_agent` and `openfigi.resolve_api_key`.
- `atomic_io.py` — atomic file writes: `write_atomic` (one cache file, durable,
  through a writer-named temp file), `clean_orphan_temps` (a killed writer's
  leftovers), and `replace_on_success`/`replace_all_on_success` (the output
  tables and the decisions file: every temp file is written first and nothing
  is replaced unless all are; then each is renamed into place, one at a time).
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
  CUSIP on the day, then its symbol, never from a row of a CUSIP another security of the run holds: `skip`,
  WEN 2008, sub-plan 5d); `by_cusip`/`by_symbol` supply CUSIP
  history, `trading_rows` the rows not under a deleted symbol, `symbol_deleted`
  whether a CUSIP's last rows are all under one, `descriptions` a CUSIP's names;
  `FTD_START` (2004-01-01, the data's first day) and `close_age` (a fails
  row's close age in trading days, for `ftd_close_prior:<n>`). `trades_after` (sub-plan 5b): whether a security's own CUSIPs, under any symbol it trades under
  (`is_trading_symbol`: no deleted, unassigned or digit-bearing symbol), have at least 20 fails rows over at least
  20 days at two or more prices after a day; the finder's test of whether it went on after a Form 25. `is_unassigned_symbol` (a new CUSIP's first-day
  `…ZZZZ` rows, no ticker) and `settled_last` (the row that opens a CUSIP's last one-price run: the fails still
  settling after its last trade). Sub-plan 5h: a one-letter class ticker whose suffix FTD writes onto a whole symbol
  (a snapshot's `UAC-C` for Under Armour's class C, FTD's `UAC`) also loads that base spelling; a base row is keyed
  by the class ticker only when the ticker's observed names agree with its description and the description names
  the class letter and is dated before the base symbol's own first observation when the run observes the base as a
  ticker (`FtdIndex.load(..., first_seen=)`: a class C spelled UA-C, whose base UA became its own line's symbol on
  2016-12-08) (`_relabel_base`); `by_symbol(base)` keeps only the rows left under it (HEI beside HEI-A).
- `midas.py` — `MidasClient`: SEC MIDAS per-security exchange volume (2012+,
  ticker-keyed); `last_trade_day()` confirms the last day with lit+hidden
  exchange volume, suppressed to `None` when the window runs past MIDAS's
  coverage end and the found day is within 5 trading days of that edge (an
  unpublished quarter always yields nothing). A quarter that fails to
  download is remembered in-memory for the rest of the run.
- `nasdaq_halts.py` — `NasdaqHaltClient`: Nasdaq's keyless trade-halt feed;
  `deletion_halt()` finds a code-`D` ("security deletion") halt as a second
  last-trade-date confirmation when MIDAS has none. A 404 is an answer (no
  halts); a timeout, connection error, 429/5xx after the retry, other status
  or unparseable body is a failure: never cached, counted as
  `degraded:nasdaq_halt_feed`, listed by `failed_days()` on the reading
  thread, carried on `LastTrade.halt_feed_failed` by the last trade module, and turned
  into `resolution_degraded` on that delisting by the pipeline.
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
- `issuer_record.py` — `IssuerRecord`, the run's issuer record (architecture step 2): one per run
  (`Clients.issuers`, the resolver's and the classifier's; `forget` when a run starts), over the EDGAR client. It
  reads each issuer's submissions JSON and filing list once (every issuer's `profile`, the JSON without its filings
  block, and first filing kept; at most `MEMO_SIZE` filing lists, least recently asked dropped) and answers `names`,
  `names_near`/`names_between`/`names_until`, `first_filed`, `existed_by`, `recent_form_dates` (read from the
  client each time), `profile`, `filings`, `text`, and `exact_holders` (SEC's name index, `name_index`, loaded on
  first use). `about=` (an event day) asks for a copy fetched by `edgar.submissions_fresh_after(about, today)`;
  every refresh of the run goes through it (the resolver's reads and the classifier's up-front read), so a held
  profile is the client's cached copy's. The failure policy, once: a
  `requests.RequestException` is unknown (None, [], (), "", False) and never remembered, `fatal.FATAL` stops the
  run, any other exception propagates, and a failed, stale (`STALE_KEY`) or self-counted degraded read logs its
  CIK on the reading thread; `watch()` gives a `ReadWatch` (`ciks`, `failed`, and `tripped()`, which also sees any
  other degraded SEC read on the thread) for the `resolution_degraded` rows. A warm pass reads through `shadow()`.
- `ticker_resolver.py` — `(ticker, as_of_date) → CIK`, 6 strategies in order of
  precision (caller's `cik` pin → manual override → `company_tickers.json` →
  EFTS Form-25/15 → observation-name company search → 8-K frequency rank),
  each strict-validated. Every read of an issuer's EDGAR record (names over time, first filing, filings, forms)
  and the name index go through its issuer record (`issuers`, built over its client, run date and `name_index=`
  unless given); a read that failed or was stale in a resolve (`_reset`/`_rested_on_failure`, the record's watch)
  marks its answer transient, as a failed search does. `expected_name` is the name an answer is checked with (the
  observed name, else the AV name). The name tier finds its candidates in SEC's
  `cik-lookup-data.txt` (`cik_lookup.py`: `CikLookupClient`, cached 30 days
  under `cache/sec_data/cik_lookup/`, and `CikNameIndex`, exact then
  character-prefix matches, read through their submissions JSON as the live
  search answered, `_index_candidates`: the one active holder of the exact
  name, else the 25-NSE/25/15-12G form filter's one filer the query names
  (`_one_filer`), else the exact name; `name_index=`, wired by
  `default_clients`; the rules and the cases behind them in
  `docs/data-flow.md`), not
  in the live company search, which runs only without an index (the offline
  tests, the golden replay) or when it cannot load. The pin and the observation name (from
  `ObservationIndex.cik_pin_on`/`.name_on`, wired in by `pipeline.py`) replace
  the old `--cik-map`/`--names` CLI files; the pin still beats every other
  tier and is never written to the on-disk resolver cache. The pipeline looks
  each era up under its own pin and name (`resolve(..., pin=, name=)`) and
  its first sighting (`since=`): every search tier, and a cached answer from
  one, takes only a company that had filed by then. The
  name search drops EDGAR's nameless multi-company hits and ranks up to 5
  candidates by the words the name shares with their EDGAR names (current
  and former). `infer_issuers` is a second pass, never cached, for eras left
  with no CIK and no pin (a renamed issuer files no Form 25 and keeps filing
  10-Ks): an 8-K frequency candidate (`efts_frequency_renamed`), or the issuer
  of an era linked by a shared CUSIP or a CUSIP switch after a rename
  (`shared_cusip`/`cusip_handoff`, `security_master.cusip_handoffs`), each
  through guard G (existed by the era's first fails row, every row's
  description matches a name it carried by 30 days after the row, the only
  candidate that did) and matching one of the era's own names; a switch's
  issuer must be the old CUSIP's, renamed (existed when it began, renamed near
  the switch, each old row named word by word by a name it carried in the 30
  days up to that row or by the name the switch renamed it from, no
  other CUSIP of its own and of the same class, begun before the switch,
  trading at it). Answers are checked again at the fixed point; each carries
  the check flag `issuer_inferred`. Rule C also runs over first-pass answers:
  where the CUSIP evidence points elsewhere, the first pass's answer stands
  and the check flag `issuer_cusip_disagrees` names both CIKs. Sub-plan 5h: `name_period_checks` (stage 2b, never
  saved): a first-pass name-search answer is replaced by the one other CIK SEC's name index lists under exactly the
  observed name that carried it over the era's span (`name_in_force`: ABBI 2008, an era with fewer than
  `ERA_MIN_ROWS` fails rows of its own) or, for an era with at least that many, whose name the era's own fails rows
  carry and the answer's do not (guard G's `_fits_rows`, `ticker_rows`: ERA 2013 is Era Group's; the rows alone
  decide, so the result never depends on which holder the first pass named);
  reported as `issuer_inferred`. A `ticker_rows` era keeps its CIK in force in stage 4c and the contract's issuer
  timeline.
- `security_master.py` — `FigiResolver.resolve_many()` (a `sec_id` pin wins;
  else CUSIP jobs, then the ticker, then a name filter — see the spec's
  Implementation notes), `build_securities()` (merges eras sharing a
  `sec_id`), `candidate_cusips`/`era_cusips`/`era_last_seen` (FTD-confirmed
  CUSIPs and true last sighting; an era takes an FTD CUSIP only when a fails
  row's description names its issuer, `names.description_matches` against the
  observed and EDGAR names — spec D21). `Issuer` (a CIK and its EDGAR names;
  `issuers_by_era` builds the era key -> `Issuer` map that `candidate_cusips`,
  `resolve_many` and `build_securities` take, the one source of an era's CIK,
  read with `cik_of`) is its type. The identity guard: an era the fails
  data covers but never shows under its ticker (`guarded_eras`), when the one
  line its issuer and class are confirmed on over its dates exists, is placed
  on it (`figi_source=backfill`) instead of asking the ticker or name tier
  (with no such line it keeps them: a stale snapshot's dead company finds its
  own line; own-name picks are not checked by `_contradicted`, since a line
  keeps its composite through a change of issuer, Merck 2009); `resolve_with_identity_guard` takes back
  a weak era whose merge would cross another security's confirmed span of the
  ticker (`crossing_weak_eras`, review `identity_detached`, `detached_review`);
  `superseded_placeholders` marks a placeholder a later FIGI line of its
  issuer and class holds the ticker for (not listed today). Its era-level
  review rows: `ticker_unconfirmed_review` (`ticker_unconfirmed`) and
  `observation_conflict_review` (`observation_conflict:<date>`). `Security.line_tickers`/`own_tickers()` (the era
  tickers and the ones stage 4b found; every own-ticker check reads it); `cusip_handoffs` times a switch from
  `ftd.settled_last` (SLE to HSH); `_handoff_joins` lets a shared CUSIP reach an era the ticker or name tier picked
  on its own name (SPW to SPXC); `cusip_job` is the one OpenFIGI CUSIP job. Sub-plan 5h: `foreign_ticker_eras`: an
  era whose rows under its ticker are all another security's (none names its issuer) is guarded too, and its
  backfill may take the line whose confirming CUSIP traded over its dates (`FigiResolver(cusip_span=, foreign=)`:
  UAG 2008-09 on PAG's line). `_handoff_joins` lets a CUSIP switch join a lettered era to a plain-named era of its
  issuer when OpenFIGI names that line with the same letter and the issuer's eras name no other
  (`line_class_letter`, `one_class_issuers`: MSG onto MSG Networks, LMCA onto Starz); never a shared CUSIP
  (tracking stocks).
- `history.py` — a security's dated history: its sightings
  (`ticker_sightings`/`cusip_sightings`, `own_last_seen`, `ticker_on`; a fails row is a ticker
  sighting only when its symbol has a letter, because SEC's Aug–Dec 2007 files mask some symbols as "**********"),
  `ranges_from_sightings()` (dated `Sighting`s into `ticker_history`/
  `cusip_history` ranges; `value_on` reads one), `backfill_cusips()` (the
  CUSIPs of fails rows under a dead security's tickers in the 120 days before its
  end, not under a deleted symbol, whose description names its issuer), its rows
  (`history_rows`), and the range review (`ticker_range_review`: `ticker_range_overlap`/`ticker_shared`).
  `filtered_ticker_sightings()` drops a backfilled observation
  (`is_backfilled`: no fails-to-deliver row of the security's CUSIPs under the
  observed ticker within 30 days, but at least one under another symbol) from
  the ticker_history-building sightings only — the delisting search's own
  copy is untouched. `observation_map_rows()` builds `observation_map.csv`:
  one row per observation, its era, `sec_id`, issuer CIK, `ticker_history`
  spelling/coverage on its date, and a status (`unresolved`,
  `after_unconfirmed_delisting` — past the clip, but the delisting that set it
  has no confirmed last-trade day, so the caller keeps and checks the member
  rather than dropping it — `after_delisting`, `conflict`, `backfilled_ticker`,
  `mapped`) — the caller's join surface:
  membership from this table, ticker look-ups through `ticker_history` by
  `history_ticker`. `pipeline._ends_the_security`/`_continues_after` (not
  here: they read `Delisting` records) decide which delisting actually clips a
  security's ranges — skipping one whose successor is the security itself, or
  one after which its own CUSIP keeps trading under its own ticker. A first-day `…ZZZZ` row is no ticker sighting;
  an observation is a sighting of its era's ticker. Sub-plan 5h: `cusip_sightings` drops an old CUSIP's `…ZZZZ`
  settle rows dated once another CUSIP of the security, begun after it, has begun (MSG 2015: the new CUSIP's range
  starts on its first row), and `clip_at_takeovers` (run by `_history_rows` over the observed securities' rows) ends
  a ticker range the day before another security's first day under it when the range only ran on to the security's
  next ticker (its own last sighting under it is earlier; the range is not its security's end).
- `added_securities.py` — `AddedAcquirer`/`AddedSuccessor`/`AddedLineSuccessor` (`AddedSecurity`; the last a FIGI
  line's successor stage 4b found, linked in stage 9 and added only for an ending that takes it): a
  security the run adds that no observation names, with its one
  ticker_history row. An `AddedSuccessor`'s span runs to its own ending's last trade when stage 9d found one
  (`last`).
- `successors.py` — the successor after a FIGI change: a security of the run
  that starts right after the last trade (`successor_in_run`, `SecurityStart`),
  else the successor issuer's 8-K12B found by full-text search
  (`successor_search_args`, `successor_query`, `successor_from_8k12b`,
  `successor_search_name`). Sub-plan 5c: `successor_by_terms` (the security an R1 statement names: the same
  issuer's class the target names, or a new issuer's line, at most `NEW_ISSUER_DAYS` (1095) old, first sighted in
  the window and named by the target); a successor is looked for around the ending's anchor (`Delisting.anchor`,
  `last_trade.anchor_day`).
- `handoffs.py` — ticker handoffs (CONTEXT.md: one security stops under a
  ticker, another of the run starts under it within days): `find_handoffs`
  (candidate pairs, [-10, 120] days), `decide_handoff` (continuation by the
  successor issuer's 8-K12B/8-K12G3 `continuation_filing`, found by the full-text
  search for the predecessor's name, else in the successor issuer's own filing list,
  `own_continuation_filing`, unless the old issuer carries on in another line; else by timing and
  the same CIK or a `cusip_switch`; else a takeover when the new line traded
  before), `apply_handoffs` (a continuation's missing `exchange_transfer` row
  or its successor, `handoff_continuation`/`handoff_rebucketed`/
  `handoff_conflict`; a takeover's `ticker_successor_sec_id` or
  `handoff_takeover_no_delisting`; a rule-6 merger, sub-plan 5f, stands as a `handoff_conflict`; every continuation,
  the row it writes included, is `rewrites.continuation` with `Rule.HANDOFF`, a rewritten merger's value dropped from
  `payouts=`; the ambiguous Form 25 is the finder's item's typed `filing`),
  `drop_resolved_shared`. Run by
  `pipeline._handoffs` after the successor search, before the history rows.
- `line_follow.py` — sub-plan 5a, pure: a security's line across a CUSIP or ticker change. `candidate_steps` (the
  next step in the fails rows within ±`LINE_DAYS` (10) trading days of the old CUSIP's settled last row: a new
  CUSIP under the line's ticker, its `…ZZZZ`/`…D` spellings, a ticker of the issuer EDGAR lists or its 8-K text
  names (`text_symbols`, which also reads "symbol ... changed from X to Y" as Y, curly quotes included: sub-plan 5c, RRI to GEN; `text_cusips`), or the same CUSIP under a new non-OTC ticker; never a CUSIP another
  security holds, nor a switch while the old CUSIP trades on at changing prices more than `SWITCH_DAYS` trading
  days after the new CUSIP's first row, applied only at the data edge (the old CUSIP's last row within
  `SWITCH_TAIL_DAYS` of `FtdIndex.last_date()`, passed as `data_end`: a live line has no stop to see; CHTR's new
  preferred; elsewhere the window is ±`LINE_DAYS` both sides, HYH 2018); the own-ticker pick is made before held CUSIPs are
  dropped, and a pick another security holds is no step (LMCA 2016)); `corroborate` (R1: refused for an 8-K 1.03 in
  [first − 180, first + 30] d, an OTC move, a description that names no name in force, a class conflict, a
  registrant that merged out or that another CIK's 8-K12B/12G3 replaces (`other_registrant`), no filing stating
  the change, or a failed `other_registrant` read (`read_failed`); the registrant carries on by a periodic report in `PERIODIC_FORMS`, which includes the small-business
  forms 10-K405, 10-KSB, 10-KSB40 and 10-QSB); `decide` (R2: attach, fold a placeholder, a line successor, or
  refused: `unsettled`, `type` for an OpenFIGI preferred/warrant/right/unit, `other_issuer`, `class`). Run by `pipeline._follow_lines` (stage 4b), up to `MAX_ROUNDS` steps a line; a CUSIP, or a successor composite, one
  security took is held for the rest of the round (a second is refused `taken`). A FIGI line with a line successor
  is not listed today (stage 5's `retired`). A failed EDGAR read is never cached, and any degraded read of a CIK gives each
  of that CIK's steps a `resolution_degraded` row, and so does a security with no step when a read of its CIK failed. Review flags `line_followed`, `line_follow_refused:<why>`
  (info). Its real cases replay offline from `tests/fixtures/lines/` (`scripts/build_line_fixtures.py`).
- `merger_value.py` — stage 8, one module (architecture step 1): `value_mergers(delistings, index, *, clients,
  closes, caller_terms, answers, tol, ftd_lo, workers, log)` gives `MergerValues`, one `MergerValue` per merger
  ending: the regex read and the LLM terms (`read`/`raw`, `llm`), the gate's verdict (`payout`, `source`,
  `confidence`, the priced stock leg `terms`, `flags`, `priced_by`), the acquirer security, its `price_ticker`, a
  basket's `leg_sec_ids`, and the received close its stock leg asks (`request`), plus the acquirers the run adds and
  the review items. Its steps: the reads (the LLM told the target's name; both filled ahead on the worker threads,
  the sequential pass then reading what they cached), sub-plan 5e's stage 8a acquirer line of every stock leg before
  the gate, passed or not (`acquirer_line`; a merger before the run's fails window reads its lines' rows into a
  private index, `LineIndex.fresh`), stage 8a' (`acquirer_ticker`: a leg with no ticker and no line), the gate
  (`payout_gate`: the terms' ticker price, then the line's, the line's first for a `line_first` leg whose ticker's
  rows are another line of the issuer's, TWC, VIA, STRZA), the acquirer (`acquirers`: the fails-row acquirer for
  ticker-settled terms, the only source of `AddedAcquirer`s, else the line or holder; a `line_first` leg publishes
  the line, another issuer's ticker security, IPHI, still wins) and its symbol on the price date. The first gate pass
  reads none of the caller's `--price-answers`: the acquirer and each leg's request come from it, and a second pass
  takes an answer only through the request it answers (the path the first pass settled on), so a second run changes
  values only. A `--merger-terms` row (`caller_terms`) wins for every delisting of its security and asks nothing; its
  acquirer ticker is published as given. The later stages read the records: `read_terms` and `drop` (8b),
  `reconciled` (9b), `table_inputs` (10a), `payout_rows` (10c), `contract_inputs` and `requests` (10g). The four rule
  modules are its collaborators, each with its own interface and real-case tests. Its real cases replay offline from
  `tests/fixtures/acquirer_gate/` (`tests/acquirer_gate_cases.py`, through `value_mergers`).
- `acquirers.py` — a merger's acquirer as a security (a collaborator of `merger_value`): `find_acquirer` (its
  composite FIGI from the fails rows under the acquirer ticker) and
  `acquirer_cik` (its issuer CIK, never the target's).
- `acquirer_line.py` — a merger's acquirer as a line of the run (sub-plan 5e; a collaborator of `merger_value`;
  `LineIndex.fresh` reads the same lines again over a fails index extended since). The terms' ticker and acquirer name
  are only evidence of the issuer. The issuer is the security that held the ticker on the last trade day
  (`LineIndex.holder`; a ticker beginning at the closing counts from the price date, and a hold that ends before the
  price date was handed over to the new holder), its issuer only when it filed by then and carries an agreeing name
  (`issuer_fits`); else the resolver's issuer of the ticker on that day, asked with the name (`issuer_by_ticker`);
  else the run's issuer that carried the name around the closing, best by shared words (`issuer_by_name`).
  `choose_line` picks the issuer's line: the class the quote names, else the CUSIP that began at the closing, else
  the holder; the class letter is read only from a quote about the target's own class (`named_class(quote,
  own_class)`: Viacom class B shares class A's read). `LineIndex.price` prices a closing CUSIP at its close on the
  price date, past the $0.01 and $1.00 placeholder rows (`is_placeholder_row`), and any other line at the last trade
  day's close. `symbol_on` gives the line's symbol from the row that carries that close: for a closing CUSIP the
  first non-placeholder row from the next trading day (JCI 2016, ABI's LIFE: the row dated the price date is still
  the old CUSIP), for any other line the row dated the price date.
- `html_text.py` — `strip_html()`: filing HTML as plain text, for the EDGAR
  client's text cache and Form 25 parsing.
- `form25.py` — parses a Form 25's XML or text (exchange, `class_text`, rule),
  labels the exchange, reads `class_kind` (common/preferred/warrant/unit/…)
  from the class text, and `match_security()`s it to one observed security of
  that kind/class letter. Sub-plan 5b: `is_involuntary` (a removal under rule 12d2-2(b)); `notice_last_trade` never reads the NYSE (b) template's "an
  announcement was made on the 'ticker' ... at the close of the trading session on D" press day, and `_class_expiry`
  takes an expiry only within [filing - 30 d, filing + 10 d]; `Form25.solely` and
  `other_class` (R3: a Form 25 that relates solely to a non-common class, or whose lettered tracking-stock segments
  name no word of the security's name, is not its own; a "solely" text that names a common class (COMMON, ORDINARY,
  SHARES) is the common's, generic descriptors such as SUBORDINATE, CONVERTIBLE, RESTRICTED, LIMITED,
  PARTICIPATING, REDEEMABLE, EXCHANGEABLE or MULTIPLE are not another tracking group, and CAPITAL is a group word,
  Liberty Capital); `notice_says_acquired` (R6b: the EX-99.25 notice says acquired or paid in cash, and nothing of
  a reclassification, a holding company or a reorganization); `SecurityRef.letter_hint` and `letter_hint` (R2: a
  letterless class takes the one letter its own CUSIP's fails descriptions name, only for a letter no sibling's
  share class carries).
- `listing_status.py` — `exchanges_around()`/`withdrawal_kind()`: reads the
  10-K cover page's exchange list before and after a Form 25 to tell a real
  delisting from the withdrawal of a secondary/regional listing while the
  main one continues; `listed_today()` for the completeness check;
  `issuer_exchange()` the exchange EDGAR's submissions JSON lists for a ticker.
- `last_trade.py` — architecture step 4: the last trade date as one module. The finder (stage 5 and 9d), the handoff
  stage (9b), stage 9c, the clip and the contract ask it; no other module decides or edits a last trade.
  `Dating(edgar, midas=, halts=)` dates an ending: `of_group` (a Form 25 group: the first notice that states a day,
  an exchange's 25-NSE first; the best 3.01 8-K reading filed in [earliest − 60 d, latest + 15 d]; MIDAS over
  [earliest − 75 d, latest effective + 10 d] under every ticker the security carried then, `OwnTrading.tickers`:
  SAVE and its OTC SAVEQ; the halt feed around the text days, else the Form 25 day, PHLY 2008), `of_fallback` (no
  Form 25: the 3.01 8-Ks up to the last sighting + 5 d, VRM 2024, MIDAS anchored on the dating filing; a merger
  left undated ends on the closing day its latest 2.01/5.01 8-K near the last sighting states, FCL, SGP 2009, never
  after the last sighting; else the last sighting, unsourced and unconfirmed) and `from_notice` (stage 9c: a
  handoff row dated by its last sighting takes its own Form 25 notice's confirmed day, before the successor's first
  sighting and no later than the effective date). MIDAS and the Nasdaq halt feed are its two adapters
  (`last_trade_day`; `deletion_halt`, `failed_days`), each a real client or a fixture-backed double; a halt-feed
  day it could not read rides on `LastTrade.halt_feed_failed`. Rule 3, the ticker's tenure (`ticker_taken`,
  `OwnTrading.taken`: the trading day before another CUSIP's first priced fails row under the ticker, on or after
  the security's own last one there; none without an own row; a $0.01 row is no trade): a MIDAS or halt day after a
  text day, from that day on, is the other security's: MIDAS is read up to the day before, the halt dropped (CCE,
  JCI 2016, GRUB 2021); without a disagreeing text day nothing is bounded (a successor's first fails rows can lag
  its first day: Sinclair Inc 2023, new TCF 2019). Rule 4, inside `of_group`: a group left undated, not continued,
  whose winner is an exchange's Form 25 (not the issuer's 25 or 25/A, not under (b): it follows the suspension by
  weeks, TMA) takes the closing day (`closing_day_read`: the 8-Ks in [F − 10, F + 10] for [F − 10, F]), else F,
  source `closing_day`, flagged unconfirmed (`LastTrade.worked_out`: the classification keeps F as its anchor); the
  closing day never comes before the last day its own fails rows show it trading (`OwnTrading.trades_until`,
  `last_row_trade_day`: the trading day before `ftd.settled_last`'s row of the CUSIP it held last; AVGO 2018, Z
  2015) unless the text dated the closing before the open (Imclone 2008's 8:28 A.M.). `at_handoff` (stage 9b): a row
  the handoff writes, or a kept row with no day, takes A's last sighting before B's first (`handoff_day`, source
  `last_sighting`); a worked-out closing day never reaches B's first sighting. The derived facts, one definition
  each: `LastTrade.confirmed` (dated and not flagged `last_trade_date_unconfirmed`: what the clip, the successor
  starts and 9c test), `LastTrade.publishable(effective)` (confirmed, from an exchange print, `EXCHANGE_PRINTS`, and
  no later than the Form 25 effective date; over a delistings.csv row, `of_row`, `effective_of` and `published`,
  which the contract, the verdict's reasons and the scorecard read), `anchor_day` (the day an ending is read
  around: its last trade, else its Form 25's filing date, else the anchor 8-K's, else its delisting date;
  `Delisting.anchor`: the successor searches and links, the R1 reading, the handoff pairs, stage 5b), `end_day` (the
  day it ended its security's listing: its last trade, else its delisting date, the Form 25's effective date; the
  clip and stage 9e) and `first_day_after` (an added successor's first day after a last trade: the next trading
  day, at all three sites that add one). The sources (`SOURCES`: `midas`, `nasdaq_halt`, `ex99_notice`, `8k_301`,
  `closing_day`, `last_sighting`, and `UNSOURCED` "") and the flags it writes (`UNCONFIRMED`, `CONFLICT`, `NO_DAY`)
  are defined here once. Its interface is tested in `tests/test_last_trade.py`, through fake MIDAS and halt
  adapters.

  The readers: `eightk_last_trade()` (Item 3.01 text) and `decide_last_trade()`, which picks among the Form 25
  notice, the 8-K text, MIDAS and the Nasdaq halt (MIDAS beats a halt beats text; a text/measured disagreement is
  flagged `last_trade_date_conflict`). The text's `_OPEN` wordings (suspended/halted "before the open", "prior to
  the market opening", "before market open", "prior to the commencement of trading", "as of the open of business",
  "at the opening of business", a halt "at the NYSE market open" on D) date the last trade on the trading day before
  D (source `8k_301`, kind `8k_open`). Sub-plan 5d: the reader reads every 3.01 section (`sections_3_01`: to the next
  item heading, not a cross-reference; the heading's number read with spaces inside it, `evidence.item_mention`, as
  sub-plan 5g's `item_sections` reads it: CBL 2020's "ITEM 3 . 01") sentence by sentence (`_read_sentence`, a stop
  word in the sentence, never a record date): `_CLOSE` ("at/after/following/as of the close/closing of
  trading/business/market [on <venue>] on D"; the Closing Date and an "after the Effective Time" at 4 p.m. or later
  resolve from the filing), a suspension at a stated clock time (architecture step 4, SPNV 2020: "suspended
  effective as of approximately 4:00 p.m. Eastern Time on September 17, 2020": at or after the close D,
  `8k_close_clock`; before the 9:30 open the trading day before, `8k_open_clock`; during the session nothing), the
  last day ("last day ... traded", "which was the last day", "continue to be listed through D"), a bare "suspended
  (trading ...) on D" (`8k_suspended`, the trading day before D: ruling R8) and "suspended immediately on D" (D,
  unconfirmed), and, date first, "On D, ... had been/was suspended (from trading)" (`8k_suspended` too: CBL 2020; no
  modal, completion word, other date or "immediate": BMC 2013, WeWork 2023); a weekday may precede any date ("on
  Friday, December 5, 2008": TMA, IDARQ); a stated close or last day that falls on no session moves to the trading
  day before (CNDT 2019); a stated timing ranks first (`reading_rank`). Source order: MIDAS, then a halt (but the
  8-K's day when it puts the halt at the open of the halt day, `OPEN_KINDS`: WM 2008, ruling R8), the notice's own
  timing, then an 8-K timing that disagrees with the notice's bare date (`BARE_NOTICE_KINDS`: TMHC 2026), then the
  notice, then the 8-K. `closing_day(texts, lo, hi)` (rule 4): when nothing states the last trade, the latest
  completion the 8-Ks state in the window (a defined Closing Date, "On D, ... completed its acquisition", "Merger Sub
  merged with and into", "the closing of the transactions on D", "the evening of D", an effective time with a clock
  time; the trading day before when every clock time that day is before 9:30 a.m.): source `closing_day`
  (`CLOSING_DAY`), never published.
- `rewrites.py` — architecture step 3: the one owner of a delisting's kind and successor after its record is built.
  Every rewrite names its rule (`Rule`, a closed set: `ISSUER_MOVE` the finder's R7, `CONTINUED` the finder's continued
  transfer, `TRADES_ON` the clip check at stage 9b's start, `R1` stage 8b, `LINE_FOLLOW` and `SUCCESSOR_LINK` stage 9,
  `HANDOFF` stage 9b, `PLAN_BANKRUPTCY` and `PRICE_DEFICIENCY` stage 9e) and is recorded as typed provenance on the
  delisting (`Delisting.rewrites`, one `Rewrite` each: the kind before, the successor, how it was found, the evidence,
  a handoff's `successor_from`). `continuation(d, successor, rule, ...)` sets CRSP `crsp_codes.CONTINUATION_CODE` (304)
  and the bucket together and drops what a continuation cannot carry, one rule for all: `no_evidence_default`,
  `successor_unknown` (`SUCCESSOR_UNKNOWN`), every payout or terms-gate flag (`PAYOUT_FLAGS`: `payout_gate_failed:*`,
  `terms_gate_*`, `acquirer_close_lagged`, ...) and the merger's value (one `MergerValues.drop` call through
  `payouts=`; a merger made a continuation without it raises). `security_goes_on(d, rule)` makes the security its
  own successor and keeps the kind and value (WRK, DIS); `mark_going_on(delistings, endings)` is the clip check's,
  filling only a blank successor; `reclassify(d, code, rule, ...)` any other kind (470, 552), a kind leaving
  `unknown` dropping the no-evidence default. Readings: `awaits_successor`, `is_real_ending` (in memory; the tables'
  is `exit_kind.is_real_ending`), `rewrite_by`, `successor_by`; `successor_note` is the reason's one wording of how a
  successor was found ("; successor by same ticker"). The classifier's own edits of the end-of-era verdict before it
  builds the record (rule 6, branch 5b, R6b) are no rewrites. Its rules are tested at its interface
  (`tests/test_rewrites.py`).
- `delistings.py` — `DelistingFinder.find()`: lists an issuer's Form 25s,
  matches and groups them into one delisting per removal (chained within
  `SAME_EVENT_DAYS` of the group's earliest filing, across exchanges), dates
  and classifies each, and falls back to the classifier's no-Form-25 paths
  when none exists. `SecurityContext.sibling_spans` keeps a Form 25 from being
  matched to a sibling security that wasn't alive on the filing date. `SecurityContext.cusip_switches`: a Form 25
  within `OWN_SWITCH_DAYS` (5) trading days of the security's own CUSIP switch, while it trades on, is no
  delisting (QGEN 2026). Sub-plan 5b: `_continued` (listed today; the issuer's own Form 25 (25 or 25/A, not
  25-NSE, not under (b)) with its 8-A12B (not 8-A12B/A, a rights-plan amendment) within `EIGHT_A_DAYS`, 10, R7; judged on every member
  of a group, the earliest member anchoring the row; or, not under (b),
  `SecurityContext.trades_after`; an observation alone never continues a security), `_judge` (one Form 25 against
  the security), early reach (Form 25s up to `EARLY_REACH_DAYS`, 365, before the floor, for a security gone today,
  the latest early group, flagged `observed_after_delisting`; none when an unreadable early Form 25 is dated
  after it, or for an issuer's own Form 25 with its 8-A12B), late reach (`SecurityContext.cusip_rows_near`,
  `LATE_ROW_DAYS` 30; and, with early reach where the security stands alone, the other CIK's reach, take only a Form 25 that names
  no class letter, or the security's own share-class letter or its `letter_hint`, `_names_other_letter`), and the
  other CIK in force (`SecurityContext.other_cik`, R5; the delisting carries the filer
  CIK; stage 4c gives a security whose submissions read failed a `resolution_degraded` row). An `unknown` row of a continued group with the issuer's 8-A12B becomes 304 with the security as its own
  successor. Each delisting is dated by the last trade module (`last_trade.Dating`, `self.dating`, built over the
  `midas` and `halts` adapters the finder is given: `of_group` for a Form 25 group, rules 3 and 4 inside;
  `of_fallback` for the no-Form-25 path), reading the security's own trading from `SecurityContext.trading`
  (`last_trade.OwnTrading`: its sightings, own CUSIPs, their trading fails rows and the fails index); a worked-out
  closing day (`LastTrade.worked_out`) is not the classification's anchor or the delisting's ticker day, which stay
  the Form 25's. Sub-plan 5h: `SecurityContext.has_cusips`: a security with no CUSIP gets no continued-filings
  ending dated by its last sighting alone (`ended_without_delisting` instead: WW 2013, NCRA 2013). The finder's R7 and
  its continued transfer's successor are rewrites (`rewrites.continuation`, `security_goes_on`); each `form25_*` review
  item carries the Form 25 typed (`review_triage.FilingRef`, `ReviewItem.filing`): the handoff stage and stage 9d read
  its form and accession there, never from the reason.
- `distress.py` — sub-plan 5g's pure readers for drop and bankruptcy endings: `otc_symbol_from_fails` (the
  security's own CUSIPs' fails rows after the last trade: the exchange symbol when its rows before any other symbol,
  leaving out those at the settled last close (the first own row's price), span more than `OTC_SETTLE_DAYS` (10) at
  two or more prices, else the first other trading symbol within `OTC_SYMBOL_DAYS` (60: PMI 2011, PPMIQ 40 days
  after the halt), else None), `otc_symbol_from_text` (a 3.01 sentence naming an OTC venue and "symbol X", the last
  one the sentence names, not about warrants or preferred only), `new_cusips` (the CUSIPs a plan notice gives the
  new shares: stage 7 never reads the old line's last close from their fails rows, WOLF 2025), `price_only` (price wording and no other listing standard: market
  capitalization, equity, back-door listing, filings), `substitutes_new_shares`/`plan_ratio` (R6: a 12d2-2(a)(3)
  notice naming new shares; the notice's stated ratio, else the plan 8-K's one old-share and one new-share count
  outside a condition), `liquidating` (a liquidating distribution, trust, or plan of liquidation or dissolution),
  and `DistressTerms` (what stage 9e hands the contract).
- `classifier.py` — the filing-trio fingerprint (**Form 25 + 8-K item codes +
  Form 15**), now anchored on the Form 25/fallback filing date rather than a
  vendor end date. `_classify_items()` maps an 8-K item set to a `DLSTCD`
  code; the surrounding logic handles asset-type short-circuits,
  exchange-transfer detection, and SEC-revocation. Rule order unchanged; the
  continued-filings rule now asks `end_of_era.resolve` instead of
  deciding alone, and records the branch in `evidence["end_of_era"]`. Sub-plan 5b: a revocation filed after a
  matched Form 25 the security did not trade past never decides its row (R6a); the continued-filings default
  (`continued_filings`) gives way to that Form 25's path when its notice says the class was acquired (R6b,
  `_classify_filings`; any answer but a merger is 231, `evidence["end_of_era"] == "form25_notice"`);
  `_confirms_bankruptcy` reads every Item 1.03 section (`evidence.item_sections`). Sub-plan 5c: `_survived` (rule 1,
  before end-of-era branches 3 and 4) and `_one_for_one` (R1: a one-for-one, no-cash statement of the security's
  class before the no-evidence default gives 304 with `r1_continuation`). Sub-plan 5g: `evidence.item_sections`
  and the classifier's heading strip read an item number the HTML stripping spaced out ("ITEM 1 .0 3", CBL 2020); no
  further digit may follow, and spaces only where the sub-number starts with 0 (a 10-K's index entry "Item 8. 29" is
  no heading). `_liquidation_notice` reads end-of-era branch 5b's 3.01 8-K. Sub-plan 5f: spec 5c's rule 6 on the
  successor branch (an unambiguous own-share statement with another ratio than one, or cash, is a merger 231,
  `end_of_era` `successor_merger`, CHTR 2016's 0.9042; a split factor n or 1/n is not, `_split_factor`, SIRI 2024's
  0.1); and before the no-evidence default, a 6-K or 8-K in [F − 30, F + 10] of the Form 25 day that states a
  completed acquisition, merger or arrangement (`_completion_report`, `COMPLETION`) is a merger 231 (TAHO, KING,
  BPYU).
- `end_of_era.py` — the end-of-era resolver's first step: where the registrant
  kept filing after the end. `signals()` reads the filings in the windows around
  the end date (8-K items, successor filings and Form 25s in [end − 30 d,
  end + 120 d]; merger filings — DEFM14A, DEFM14C, PREM14A, SC 14D9, SC TO-T,
  SC TO-I, SC 13E3, 425, S-4 — in [end − 540 d, end + 30 d]); `resolve()` takes
  the first branch that fits: (1) still trading after the end (the finder's
  `continued`, passed as `classify_event(..., trading_after=)`) → today's
  transfer; (2) a successor registration (8-K12B, 8-K12G3) → a transfer whose
  successor stage 9 finds; (3) a change in control (8-K 5.01) → merger; (4) a
  completed acquisition (8-K 2.01) with a merger filing or a Form 25 → merger,
  unless a bankruptcy 8-K the classifier confirmed (`bankruptcy_filing`) came on
  or before it → liquidation 470 (5g sub-rule 2, built in sub-plan 5b);
  (5) a 3.01 notice whose text cites a listing deficiency → compliance failure
  570; (5b, sub-plan 5g) a 3.01 8-K announcing a liquidating distribution, trust or plan of liquidation or
  dissolution → liquidation 400 (EQC 2025), read by `classifier._liquidation_notice` only when branch 6 would
  decide; (6) else today's continued-filings transfer (304), its reason string
  unchanged. The reason protocol the published column carries is defined here once and read from here
  (`CONTINUED_FILINGS`, the prefix of `CONTINUED`; `RESOLVED_FROM_CONTINUED_FILINGS`, a relabel's suffix: the finder,
  stage 9g, the verdict and the scorecard). EDGAR evidence only.
  Tried only where the continued-filings rule fires. Sub-plan 5c, rule 1: branches 3 and 4 never fire when
  `EraSignals.survived` holds (the classifier found no exchange of the registrant's own shares, and an acquirer's
  or a distributor's statement); `merges` says when they would.
- `crsp_codes.py` — the truth table: `DLST_CODE_TO_BUCKET` plus a leading-digit
  range fallthrough (`2xx→merger`, `3xx→exchange_transfer`, `4xx→liquidation`,
  `5xx→compliance_failure`, `6xx→expiration`). **The bucket — not the exact code
  — drives all downstream handling.** `CONTINUATION_CODE` (304) is every exchange transfer's code, one constant.
- `payout_extractor.py` — bridges the layers: extracts the per-share **cash**
  merger consideration from EDGAR filing text (network, regex) for the `merger` bucket. Each read carries its
  currency (`PayoutResult.currency`, sub-plan 5f, ruling R5: the letters before its "$", `currency.prefix_currency`).
- `currency.py` — sub-plan 5f, ruling R5, pure: the currency a filing states for a cash amount ("$"/"US$" USD,
  "C$"/"Cdn$" CAD, a sign or an ISO code next to the amount: `prefix_currency`, `stated_currency`; an LLM answer as
  a code, `normalize`). Never converted, never inferred from where a company is based: blank when not stated.
- `exchange_terms.py` — what a filing says the registrant's own shares became (sub-plan 5c, R1): `statements`
  reads each "each share of S ... converted into N shares of T" (and "received N shares of T for each share",
  "on a one-for-one basis", a cash one); `own_exchange` keeps those whose subject is the registrant's (its EDGAR
  names in the year before the event, a defined term for one, "the Company"/"its"/"our") and the security's class,
  and gives the ratio, cash in the exchange (par values, cash in lieu of fractions and special dividends set aside:
  a special dividend is never consideration; rollover shares and cash conversions are read), the target clause and
  its names (defined terms expanded), the target's class letter, and whether readings disagree (`ambiguous`);
  `acquires` (another party's shares became the registrant's, or it issued shares under the merger agreement) and
  `distributes` ("for every four shares", kept) are the registrant's other roles; `read_texts` reads the 8-Ks
  around an ending's days and its Form 25 notice. Pure apart from `read_texts`.
- `llm_merger_extractor.py` — the **cash+stock** counterpart: an LLM reads a
  filing and returns full structured terms (`cash_per_share`, `stock_ratio`,
  `acquirer_ticker`) the regex extractor can't generalize over. Uses
  `llm_client.py` (injectable OpenAI JSON client) and `filing_selection.py`
  (filing-tier picker shared with `payout_extractor.py`); responses cached under
  `cache/llm/`. Disabled by default — enabled by `--extract-merger-terms-llm`;
  `acquirer_price` and `last_trade_close` come from `ftd.py`, not a filing. `MergerTerms` answers for its own
  package, so the gate, the payout rule, the requests and stage 8 ask it instead of reading its fields: `ticker`
  (normalized; a spelled-out null, `NULL_TICKERS`, is cleaned when the answer is built, `clean_ticker`),
  `is_package`, `has_stock` (any security), `stock_leg` (a ratio or a dollar value: what asks a received close),
  `skip_reason` (why the gate cannot check it), `published` (the contract's legs: a non-package election only its
  all-cash alternative) and `legs(main_ticker)` (each security with its class and the ticker its class trades
  under). Prompt v3 (sub-plan 5f): the answer is
  the PACKAGE one share of the named target security became (ruling R4: the final prorated per-share result when
  stated, else what non-electors got, else the fixed terms, never the sum of an election's alternatives), with
  `cash_currency` (R5; the quote's own sign wins), `stock_value` (a dollar-valued leg, PCYC), the stock leg's issuer
  and class (`acquirer_*`: whose shares are received, New CCE not KO), `extra_legs` (a basket, R3), `package_basis`
  and notes. The user prompt names the target security and the filing; the cache key is
  `{accession}_{model}_v3_{ticker}`. Candidates, latest completion documents first: the closing 8-K, an 8-K reporting
  the closing without 2.01 (3.01/3.03/5.01 within 30 days), an announcement 8-K filed after the last merger proxy (an
  amendment, BOT), DEFM14A, the other announcement 8-Ks, PREM14A, a 6-K near the delisting; an unsure one-for-one
  answer whose quote states no share count is passed over (`unsupported_one_for_one`: ATH, CHTR); a spelled-out null
  ticker ("NULL") is none. A failed LLM call is a
  degraded miss (`SEC_STATS.degraded("llm_call")`: the delisting is `resolution_degraded`), never cached; with
  `--sec-workers` > 1 the calls are filled ahead on the worker threads. Calibrate with
  `scripts/eval_merger_extractor.py --truth` (the 10 deals and the truth set's terms cases).
- `store.py` — every output table's column order, key and sort order
  (`TABLES`), `DelistingKey` (a delisting's `(sec_id, delist_date)` key, here so
  the classification layer — the finder — and the handling layer can both use
  it without one importing the other), `format_cell` (the one cell formatter
  every table shares), `write_tables`/`read_table` (every table to a temp
  file first, then renamed into place one by one,
  `atomic_io.replace_all_on_success`), and `read_delistings_frame`
  (delistings.csv as a typed pandas DataFrame: `qlib_adapter.load_delistings`
  reads through it). `CONTRACT_SCHEMA_VERSION` 3 adds `contract/payout_legs.csv` (sub-plan 5f). Every table read — `qlib_adapter`, `accept_review.py`,
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
  the security master's and the pipeline's), `.row()` its review row; a finder's
  item about a Form 25 carries it typed (`filing`, a `FilingRef`: form, accession,
  filing date), never written;
  `merge_review_rows` joins rows that share a key. Called by `pipeline.run()`
  just before the write; never touches `delistings.csv`.
- `degraded.py` — answers that rested on a failed request or a stale copy:
  `DegradedWatch` (an SEC read on this thread counted itself degraded; a stage whose reads include an issuer's
  record asks `IssuerRecord.watch()` instead, which also sees an issuer read that failed without counting itself),
  `degraded_item`/`flag_degraded` (the `resolution_degraded` review row and
  the flag on a delisting's own row), `report_halt_feed_failures` (a
  last-trade decision that asked a Nasdaq halt-feed day that failed).
- `manifest.py` — `run_manifest.json` (`build`/`write`) and `StageMeter`, the
  per-stage SEC traffic it reports.
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
- `dlret.py` — DLRET hub: `resolve_dlret`/`DlretResult`/`compute_dlret` (self-explaining delisting return; `otc_print=` gives `DlretMethod.OTC_PRINT` on a liquidation or compliance_failure, a `--recoveries` ratio winning, a merger ignoring it; `plan_value=` gives `PLAN_STOCK`, an answered R6 plan value, sub-plan 5f). `bmp_correction.py` re-exports for backward compatibility.
- `reconstruction.py` — `EnrichedDelistRecord`, `enrich`, `build_delistings_table`,
  `delisting_row`. `output/delistings.csv` is the **primary output**, keyed by
  `(sec_id, delist_date)` (`store.DelistingKey`; `for_delisting` looks a delisting up
  in a map keyed by it or by the bare `sec_id`).
- `qlib_adapter.py` — DataFrame splicers over a `(datetime, instrument)` panel,
  where `instrument` is a `sec_id`: `inject_terminal_labels`,
  `apply_backtest_exits`, `apply_bmp_corrections`, each reading every input
  straight off the matching `delistings.csv` row. All three, and
  `handling.adjustments_from_rows`, skip a row whose `successor_sec_id`
  equals its own `sec_id` (a continuing security, e.g. an exchange transfer
  that kept the same FIGI) — it isn't an exit, so no label/exit/correction
  is emitted for it.

**Measurement (pure), over the output tables as string rows:**
- `lifecycle.py` — `Tables` (the tables `store.read_table` returns) and
  `LifecycleView`: every security's and every input ticker's lifecycle
  (`active`, `ended`, `ended_incomplete`, `left_view`, `closed_no_event`,
  `no_interval`, `loop`; `active`/`ended` are covered), quality (the weakest
  `event_grade` on a covered chain, `medium` for a ticker-only FIGI), and the
  look-ups a truth case needs (`security_on`, `issuer_of`, `tickers_of`,
  `end_of`). `EXIT_KIND_OF_BUCKET` maps today's bucket to the contract's
  `exit_kind` until reset-3 publishes that column.
- `truth.py` — truth cases, checked by hand at a cited source: the golden set
  (`data/golden_lifecycles.csv`, `pass` or `known_wrong` + `fixed_by`) and the
  decision-17 audit (`data/accuracy_audit.csv`, `census:<group>` or `random`;
  an unfilled row is pending). `load_truth`, `write_truth`, `judge` (one
  mismatch per checked field that disagrees), `clopper_pearson_upper`.
- `diagnosis_truth.py` — the diagnosis truth set (`data/diagnosis_truth.csv`, spec
  2026-10-03-diagnosis-truth-fixes): one row per diagnosed case. `shape` is ending, no_ending or ending_moved. Scored
  contract fields hold a value, a blank or `*`; `internal_last_trade_date` holds a worked-out date, and a side file
  holds a basket's legs. Its judge (`LibraryRows`, `judge_case`) gives one `Mismatch` per scored field, or one `sec_id` mismatch when the case's security is not in the run. The
  scorecard's `D.*` lines and `tests/test_diagnosis_truth_cases.py` (strict xfail on known_wrong) read it.
- `regression.py` — the contract diff against a base commit (`snapshot_at`), outside the truth set and its
  successor chains (`excluded`); `build_report` is the one place that builds the report (the standalone script, the
  round script and the scorecard all call it) and `id_changes_since` finds renames against the base commit.
  `SKIPPED_COLUMNS` leaves out `verdict` and the price-derived columns. `unexplained` gives the rows the ledger has
  not settled; they become `D.unexplained_regressions`, which `scripts/scorecard.py --check --base <commit>`
  requires to be 0. A renamed placeholder is compared under its FIGI (`renamed_to`): one `renamed` id_changes row
  (`regression.RENAMED`, `diff_contract(..., renames=)`) instead of its removed row and the FIGI's added one.
- `diagnosis_loop.py` — the loop's ledger (`output/diagnose_unknown_report/loop/diagnosed.csv`), error keys, case
  rows for the diagnose workflow, and placeholder renames (`contract/id_changes.csv` and the base commit's securities.csv, `regression.id_changes_since`; `write_together` writes the truth file and its change log as one set).
- `truth_update.py` — spec 1.6's rules for what a round's diagnoses may change in the truth file. A regression is
  added only when it is verified and upheld. A mismatch changes the truth only when the diagnosis cites a filing the
  earlier report missed. `flip_statuses` turns a known_wrong case that now matches into pass. A regression of a sec_id the run lacks, or
  of a renamed placeholder, adds no truth row (`apply_round`: `run_sec_ids`, `renamed`).
- `truth_build.py` — the first truth file, built from the normalization workflow's JSON rows (the R2 FIGI check,
  pending fields, the residual list, statuses).
- `scorecard.py` — `build` (the spec's gap table as one flat dict: L1/L2, R1.x,
  R2.x, G.x, A.x), `METRICS` (each floored number's good direction), `drops`,
  `raise_floor`, `load_config` (`data/scorecard.json`: the caller's window, the
  floor, the two truth files), `write` (`output/scorecard.json`).
- `audit.py` — decision 17's sample: `census` (each ending in its first group of
  distress, continuation, left_view, blank_no_value, assumed_par), `random_sample`
  (seeded, avoiding census chains), `worksheet_rows`.
- `verdict.py` — one verdict per seed (an observation_map row), security and
  ending (a delistings.csv row whose successor is not itself): `decide`
  returns `Verdicts`; `uncertain_rows()` is `uncertain.csv`. The rules are the
  spec's invariants, read from the tables (FIGI source, intervals, each
  ending's reason, flags, last-trade source and Form 25 date) plus each
  placeholder's ticker evidence. A seed is an era's first sighting for the
  security's coverage rule; later sightings outside the history are listed
  seeds only.
- `ticker_evidence.py` — decision 1: what ties a placeholder's ticker to its
  CIK. A resolver tier that names the ticker (`TICKER_TIERS`), else one
  EDGAR full-text search of the CIK's own filings (`full_text_search(...,
  ciks=)`), cached like every search.
- `exit_kind.py` — one delistings.csv row in the contract's terms: `ending_fields` (exit kind, drop reason,
  continuation, `dlret` and `dlret_fill`; `MEASURED_METHODS` includes `otc_print` and `plan_stock`, so an answered OTC print or plan value is a value, not a fill) and `is_distress`. Today's bucket and CRSP code map to the exit kind
  (a code-470 bankruptcy is `dropped` for `bankruptcy`; `unknown` asserts none; a compliance failure the exchange
  removed for a price deficiency only, its Form 25 notice, else its 3.01 items, carries CRSP 552, drop reason
  `price`, from stage 9e, and an issuer's own Form 25 changes nothing: sub-plan 5g). The contract, the golden judge
  and the scorecard all read through it. The one definition of the row predicates every table reader asks:
  `is_real_ending` (the successor is not the security itself) and `is_continuation` (a successor other than itself):
  contract, lifecycle, verdict, verdict_rules, scorecard and audit.
- `contract.py` — the contract's rows (spec "The contract", decisions 6, 7, 9, 10, 12), written under
  `output/contract/` beside today's tables for one release: `security_history_rows` (ticker ranges split where
  the issuer in force changes), `delisting_rows` (one per ended security, its last), `seed_rows` (the seed
  echo), `id_change_rows` (baseline placeholders that now hold a FIGI; stage 4b's folds by name, `renames`; and a baseline
  FIGI the run no longer holds that `renames` maps to a FIGI of this run, rule F: BTU, CRC; `regression.renamed_to`
  and `diagnosis_loop.rename_truth` read every row alike, placeholder or not), `payout_leg_rows` (schema 3, R3: each
  security of a basket ending per share, `contract/payout_legs.csv`). `run_manifest.json` carries
  `schema_version` (`store.CONTRACT_SCHEMA_VERSION`, 3).
- `issuer_in_force.py` — the issuer CIK on each sighting's date: the era's CIK when its EDGAR name that day agrees
  with the observed name, else the one other CIK SEC's name index lists under that name whose name agreed then
  (MRK 2008: old Merck & Co, CIK 64978). `issuer_changes` dates each change: it sorts sightings by day then CIK
  and records at most one change per day (a same-day sighting under another CIK changes nothing).
- `payout_rule.py` — the payout rule of each contract ending (`value_fields`, the eleven columns after `verdict` in
  `contract/delistings.csv`: the columns came in schema 2, the contract is now schema 3 with `payout_legs.csv`): `value_rule` (`VALUE_RULES`), `cash_per_share`, `cash_currency`, `stock_ratio`,
  `price_sec_id`/`price_ticker`/`price_date` (the acquirer for a stock leg, the security itself for `otc_print`; the
  trading day after the last trade), `recovery_ratio`, `terms_source`, `terms_gate` and `value_formula`; the caller
  computes `dlret = payout / last close − 1` with its own prices. `MergerInputs` (stage 8's
  `MergerValues.contract_inputs`) holds a merger's `--merger-terms` row, LLM terms and regex read from before the
  payout gate: terms the gate dropped are still published,
  `terms_gate=failed` (a failed election publishes both legs as read), `skipped` when the gate could not check them
  (`terms_gate_skipped:<why>`: a non-USD cash leg, a basket, a dollar-valued leg), blank with no last close.
  `cash_currency` (sub-plan 5f, R5) is the currency of the read that supplied the cash (the LLM's, the regex's;
  blank for a `--merger-terms` row). A package of two or more securities is `basket` (R3): the main row keeps the
  cash, `basket_legs` gives `contract/payout_legs.csv`'s rows; one security plus cash stays `cash_plus_stock`. A
  dollar-valued stock leg is carried in `value_formula` over `avg_price(<ticker>)`, no ratio. The payout gate
  (`payout_gate`) reads a v3 answer as its package (`MergerTerms.is_package`: basis final_prorated, default or fixed; a `none`
  answer keeps 5e's either-or reading): cash only in pass 1, with stock in pass 2; a regex cash never stands beside
  an election package with stock, a package no last close can check, or as the package's own cash leg (SUG, FWLT,
  AWH, SHAW); an LLM's "NULL" ticker is no ticker (GRUB, `MergerTerms` cleans it). Review fixes (5f): an election whose v3 answer states no leg (WSC, THE) takes the
  earlier prompt's cached either-or reading of the same filing (`LEGACY_VERSION`, cache only, never asked again; `no_default`,
  flag `election_no_default`), as does any election answer that states no package for non-electors (basis `none` with no cash or ratio stated, TRH; a basis `none` answer that states a leg, CYN, keeps it; or a
  `final_prorated` answer that is only one election class's result, `electors_only`, NMX: R4, the package is what
  non-electors received, `llm_merger_extractor.base_reading`; the first candidate that answers decides, a later candidate is never read (TRH, NMX); with no cached
  earlier answer the electors' result is a miss and the regex read stands); `MergerTerms.published` publishes any other
  non-package election only as its all-cash alternative, but a `no_default` reading as read (TRH's 14.22 + 0.145 Y); `MergerTerms.skip_reason` is checked for every answer shape (a dollar value, a further leg, CAD
  cash, a basket stating no package), a stock leg with no ratio is `terms_gate_failed:no_ratio`; a bare "$" never overrides
  the answer's non-USD code; a non-dict answer counts `degraded:llm_call`. `acquirer_ticker.py` (stage 8a'): a stock leg
  with no ticker and no acquirer line takes it from the filing's defined terms, SEC's name index and the issuer's EDGAR
  tickers, else the fails rows' description (SHAW's "CB&I" is CBI); a one-word name the filing does not define is no
  name (Orange). A basket leg keeps its class (`payout_legs.share_class`, `MergerTerms.legs`: CAA's Lennar class B
  is LEN-B, a preferred class has no ticker), and two legs never share a price request. `regression.py` diffs the
  legs too. The scorecard counts
  `R2.7.value_rule.<rule>` and floors `R2.7.payout_rule_known`. A stock leg's `price_ticker` is the published
  acquirer security's symbol on the price date (`MergerInputs.price_ticker`, sub-plan 5e). `value_fields(...,
  distress=)` (sub-plan 5g): an `otc_print` row is priced under `DistressTerms.otc_symbol` (blank when stage 9e read
  none; the exchange ticker only for a caller that passes no terms); a bankruptcy plan with a read ratio is `stock`
  on the new line (`stock_ratio` as read, a string; no `price_sec_id`; `terms_source` `form25_notice` or `plan_8k`).
- `price_requests.py` — both directions of the price round trip, matched on one key derivation: the requests
  (`request_rows`: `last_close` per ending with a published date, `received_close` per stock leg as stage 8 asked it
  (`MergerValue.request`: the acquirer security's symbol on the price date, sub-plan 5e, a leg with no LLM ticker
  asking once the line is known, a dollar-valued leg too, 5f), of a plan's new line (`plans=`, 5g) and of each
  further leg of a basket (`leg_rows=`; accepted, not used: the library prices no basket), `otc_print` per
  `dropped`/`liquidation` ending that is not a continuation, under the published OTC symbol (the exchange ticker
  when blank), dated the session after the last trade; a plan's `stock` row asks no OTC print) and the answers
  (`load_answers` for `--price-answers`, which refuses a price that is not a finite positive number, and
  `PriceAnswers`). Each request fills one value input, and a stage reads its answer only through the request it
  makes: `last_closes` (stage 7; one also given by `--last-trade-closes` stops the run), `received_close` (stage 8's
  stock leg, by its ticker), `ending_values` (stage 10a: an OTC print, else a plan's ratio times its new line's
  close) and `refuse_unrequested` (stage 10g: an answer whose `PriceKey` matches no request stops the run). A last
  close or an OTC print is matched on the security, its last trade day and the kind (the ticker and date are a
  hint), a received close on its ticker too.

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
  The limiter (`sec_limiter.SEC_LIMITER`) is shared by every thread of the process
  and, through `~/.cache/delist_detection/sec_rate.lock`
  (`$DELIST_DETECTION_SEC_RATE_LOCK`), by every SEC client on the machine
  (`sec_limiter.use_machine_wide_limit()`, installed by the CLI, `default_clients`,
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
  (`cgi-bin/browse-edgar`, the resolver's fallback tier) was 89% of cold
  issuer-resolution time and can slow to ~10 s/request after about 1,500
  searches in under an hour, recovering after ~20 idle minutes; on 2026-09-28
  it answered HTTP 429 (a run-stopping `EdgarBlocked`) three times in a cold
  full run, at 8, 2 and 1 workers. That is why the name tier now reads SEC's
  `cik-lookup-data.txt` (one ~38 MB download; building the index takes about
  9 s and ~440 MB) instead of searching. Peak memory is 1.8–4.2 GB (mostly data, likely the fails-to-deliver panel; not profiled);
  threads add at most about 37 MB (measured). SEC does not keep full-text-search hit order
  stable between two fetches of the same query: the same cache always gives
  the same output, but a refetch can reorder tied hits (see `docs/data-flow.md`).
- **OpenFIGI refusals abort too.** A 401/403 from OpenFIGI raises
  `OpenFigiBlocked` (`openfigi.py`); `classify_universe.py`'s CLI catches it
  alongside `EdgarBlocked` and exits 2. Every exception that stops a run is
  listed once, in `fatal.FATAL`, and every catch site re-raises that tuple
  before turning a failure into a row, a miss or a transient answer: the
  issuer record's reads (`IssuerRecord._read` and `name_index`: every issuer read of the resolver, the
  classifier's name check and the stages), the pipeline's delisting search and payout extraction,
  `listing_status.listing_answers`, the prefetch pool, the ticker resolver's
  company search (`_name_search`), and the CLI, which turns it into the exit code; a new one
  is added in `fatal.py` only. A 429 is waited out on the
  `ratelimit-*`/`retry-after` headers, never cached as an answer. Timeouts,
  connection errors or 5xx answers that outlast the client's retries raise
  `OpenFigiUnavailable` (not a subclass of `OpenFigiBlocked`): the run stops
  before writing anything, nothing is cached, no placeholder stands in for the
  answer (it would change `sec_id`s between runs), and the CLI prints "OpenFIGI
  unavailable after retries; no outputs written; rerun later" and exits 4. The key
  comes from `OPEN_FIGI_API_KEY` (environment first, then the repo `.env`),
  sent as header `X-OPENFIGI-APIKEY`. Exit 3 is a completed run whose
  `review.csv` has one or more `error` or `resolution_degraded` rows (an answer
  rested on a failed SEC or Nasdaq halt-feed request or a stale copy); outputs are still written,
  and a banner goes to stderr with the counts. A bad input file exits 2 with
  one stderr line naming the file and line (see *Configurable input paths*),
  and exit 1 means only an unexpected crash. This tally is taken *before*
  `review_triage.triage()` runs, so it is unaffected by decisions or hidden
  info-only rows — an `error`/`resolution_degraded` row always trips exit 3,
  whether or not a decision also exists for it (it can't: both flags are
  `acceptable=False`).
- **An issuer is read through the run's issuer record, once.** The resolver, the classifier's up-front refresh and
  name check, and the stages' reads of an issuer's names, filings and first filing (2's names, 4b, 4c/10g, 8a/8a',
  8b, 9's terms links, 9b) ask `Clients.issuers` (`issuer_record.IssuerRecord`). A read that fails after the
  client's retries is unknown and never remembered, a refusal stops the run, and the answer that rested on a failed
  or stale read gets `resolution_degraded` (`IssuerRecord.watch`): the handoff stage's read of the successor
  issuer's filings no longer stops a run that has no cached copy (exit 1). Reads still made straight from the
  client, left for later steps: the finder's (its per-security try makes a failure an `error` row),
  `listing_status`'s, `successors.successor_search_name`, stage 9e's 8-K list and stage 9g's
  `continuation_evidence`, and filing texts and notices outside the record.
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
  reported on one stderr line and exits 2, like a missing or malformed
  `--observations` / `--last-trade-closes` / `--merger-terms` /
  `--recoveries` file (`ObservationError`, `reconstruction.OverrideFileError`)
  and override rows that match no delisting of the run).
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
- **The scorecard only moves one way.** Every run builds `output/scorecard.json`
  (`pipeline._scorecard`, stage 10h) from the rows it is about to write and
  writes it after the nine tables and the contract files, before the manifest. `data/scorecard.json`
  holds the caller's training window (data, never code), the floor and the two
  truth files. `tests/test_scorecard_floor.py` recomputes the scorecard from the
  committed `output/` and fails when a floored number got worse, a floored
  metric disappeared, or a golden `pass` case fails;
  `tests/test_golden_lifecycles.py` runs every golden case (`known_wrong` is a
  strict xfail, so a fix forces the row to flip to `pass`). A plan that improves
  a number runs `scripts/scorecard.py --raise-floor`; a floor entry is lowered
  only by hand, with the reason in the commit. A `--limit` run is never compared
  to the floor. A drop or a failing golden case warns on stderr and never changes
  the exit code; a bad config or truth file exits 2.
- **Every fix sub-plan passes the diagnosis truth loop (spec 2026-10-03-diagnosis-truth-fixes).** After the cached
  full run: (1) `truth_loop_round.py` judges the run against `data/diagnosis_truth.csv` and writes the regression
  report against the sub-plan's base commit; (2) it keeps the errors the ledger has not seen (mismatch case ids are
  `<truth_case_id>_<label>-r<N>`, regression ids `<sec_id>_<label>-r<N>`; `regression.excluded(..., id_changes=)` also
  leaves out placeholders renamed to a truth security); (3) the `diagnosis-truth-loop` workflow diagnoses each one in
  regression or mismatch mode, with a skeptic per case; (4) `update_truth.py` applies the outcomes under fixed rules
  (a mismatched truth field never takes a library value unless a verified, upheld diagnosis cites an SEC accession
  the earlier report missed; a regressed row enters the truth file with the side the diagnosis found right for the
  fields the agent saw: a whole added or removed row scores only its brief, and a changed field keeps the base run's
  other scored values, which the regression guard presumes right) and writes the truth file, the change log and the ledger together (`atomic_io.replace_all_on_success`). A
  `pending` ledger row is never re-diagnosed automatically: the operator settles it or deletes the row. The loop
  stops after a round with no new error, or after 3 rounds. A sub-plan is accepted only when `D.mismatches` fell
  and `scripts/scorecard.py --check --base <commit>` passes (`D.unexplained_regressions` 0). `truth_build.UNSETTLED`: an OpenFIGI error or several US
  lines leave a CUSIP-change row `ruling_pending`.
- **Every seed, security and ending has a verdict, and every uncertain one is
  in `uncertain.csv`.** `kind` is seed | security | ending; `reason` holds
  `code` or `code:detail` items (verdict.py's docstring lists them). The
  verdict covers identity, exit kind and the last trade date, never the value
  (except assumed par after a failed payout, LLM or terms gate, decision 4). A seed whose
  only problem is its security is counted, not listed. Pipeline stages 10e
  (ticker evidence: about one cached EDGAR search per placeholder without a
  ticker tier), 10f (verdicts), 10g (the contract) and 10h (scorecard) run
  before the write; `uncertain.csv` is written with the other tables. An
  ending that is not its security's last real ending is uncertain
  (`earlier_ending:<the last one's delist_date>`). The scorecard's V lines
  read it; a committed output without it has no V lines. The scorecard's
  R2.4 lines still count assumed par by `dlret_method`, not by exit kind and
  fill, because assumed par also falls on unknown and expiration endings.
- **The contract is written beside today's tables for one release (decision 6).** Stage 10g writes
  `output/contract/{security_history,delistings,seeds,price_requests,id_changes,payout_legs}.csv` from the tables about to be
  written and the verdicts; the scorecard (10h) reads the issuer from `contract/security_history.csv`. Contract
  delistings hold one row per ended security, its last real ending; `last_trade_date` is published only when it
  is publishable (`last_trade.LastTrade.publishable`, read over the row by `last_trade.published`: confirmed, from an
  exchange print, no later than the Form 25 effective date; architecture step 4's ruling), and the price date and
  the price requests follow the published date; a continuation has no value; assumed par, Shumway marks
  and a transfer's 0.0 are `dlret_fill`. `--price-answers` (the requests plus a `price` column) feeds the closes and
  acquirer prices, so a second run changes values only: each stage reads the answer to its own request
  (`price_requests.PriceAnswers`; stage 7 a last close, stage 8 a stock leg's received close, stage 10a an OTC print
  or a plan's new-line close), and `pipeline.Overrides` holds only the caller's own files. A price that is not a finite positive
  number, an answer to no request, or a last close also given by `--last-trade-closes`, exits 2 before anything is
  written. Today's nine tables keep their columns.
- **Every output is written only after the whole run succeeds.**
  `pipeline.run()` computes every table in memory first and writes all nine
  and the six contract files (same group) only at the end (`store.write_tables`): each table is formatted and written
  to its own temp file first, and only then are the temp files renamed over
  the old tables. So a refusal, a bad override CSV or any failure before the
  renames leaves every previous table as it was. The renames themselves run
  one file at a time (`atomic_io.replace_all_on_success`), so a run killed
  between two renames can leave some tables new and the rest old; each
  single table is always whole.
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
- **A Form 25 is reached, matched and owns its row (sub-plan 5b).** A security goes on after a Form 25 only when it
  is listed today, when the issuer moved the class itself (its own Form 25 with an 8-A12B within 10 days), or, for
  a Form 25 not under rule 12d2-2(b), when its own CUSIPs keep trading (`ftd.trades_after`): never on an
  observation alone (a stale snapshot), never on the OTC tail after a removal under (b). A security gone today also
  takes the latest Form 25 group of the year before its first sighting, and a Form 25 after its alive window when
  its own CUSIP traded within 30 days before it; the one other CIK in force over its whole span is searched too. A
  Form 25 solely about rights or about another tracking group is not the common's. The matched Form 25's notice
  outranks the continued-filings default when it says the class was acquired, and a later SEC revocation never
  decides its row.
- **An ending's kind and successor change after the finder built it only by a rewrite (`rewrites.py`).** Each names
  its rule and is recorded typed on the delisting (`Delisting.rewrites`; never a column). A continuation carries no
  `no_evidence_default`, no `successor_unknown`, no payout or terms-gate flag and no payout read: a merger the handoff
  stage or R1 makes a continuation loses its merger value (`MergerValues.drop`: delistings.csv's payout, acquirer and
  raw payout columns go blank and payouts.csv has no row for it). A security that goes on (its own successor) keeps
  its kind and value. The clip check's marking (`rewrites.mark_going_on`) runs once, as stage 9b's first step.
- **An ending's kind follows the registrant's role and R1 (sub-plan 5c).** A registrant whose filings state no
  exchange of its own shares, and that acquired another party or distributed another company's shares, gets no
  merger from end-of-era branches 3 and 4. A one-for-one exchange with no cash (a special dividend is no cash) is a
  continuation only into a new issuer (first EDGAR filing at most 1,095 days before) or the same issuer: stage 5
  gives it when no 8-K item code decides, stage 8b rewrites a merger whose published terms say one share and no
  cash, stage 9 links a transfer to the security the statement names or to the new line its own same-CIK 8-K12B
  moved it to (OpenFIGI's CUSIP job, R2). The added successors take their own Form 25 endings (stage 9d; a failed
  Nasdaq halt-feed read there is `resolution_degraded` too, and a line successor's span ends at its own last
  trade). A text never decides a merger row alone: the LLM's terms must agree. The name tie (a new issuer is a
  successor only when the R1 statement's target names it: one of its tickers of two letters or more is a word of a
  target name, or a target name agrees, `names.names_agree`, with one of its EDGAR names) is carried by
  `successors.successor_by_terms` (stage 9's terms link and 8b's in-run link), by 8b's 8-K12B candidate
  (`_r1_successor`) and, as a registrant of that name first filed at most 1,095 days before or the registrant's own
  name, by stage 5's R1 (`classifier._names_new_issuer`); the same-CIK own-registration link and the same-issuer
  class link need none. A second leg after the first share (more shares, rights, warrants, units or a CVR) is no
  one-for-one.
- **A line is followed past its observations (sub-plan 5a, rulings R1 and R2).** Stage 4b follows each security
  across a reverse split or a rename the fails rows show after the caller's last observation, before the Form 25
  search: so a later real ending is found instead of a guess anchored on the old ticker's last row. A step needs a
  filing that states it (an 8-K 5.03/3.03, an own 8-K12B/12G3, an EDGAR rename, or 8-K text) and an old registrant
  that carries on (a periodic report for a period after the step, or its own 8-K12B; listed today for a step
  within 120 days of the run date; no other CIK's 8-K12B/12G3 naming it). R2 decides identity: the same composite
  or none is one security; a placeholder folds into the FIGI line its new CUSIP names (contract/id_changes.csv
  names it); another composite is a line successor, linked by stage 9 as a continuation (an `unknown` row at the
  switch is rewritten, `line_continuation`: it drops `no_evidence_default` and gets medium confidence).
- **`ticker_history` is clipped only at the delisting that actually ends the
  security.** One whose successor is the security itself (a continuing
  exchange transfer) never clips it. Otherwise, only a `merger` or
  `exchange_transfer` delisting with a *confirmed* last-trade day
  (`last_trade.LastTrade.confirmed`: dated, not flagged unconfirmed) can be second-guessed: it
  doesn't clip either when the security's own CUSIP keeps trading under its
  own ticker afterward — at least 20 live fails rows over at least 60 days
  with 2 or more distinct prices, so fails still settling at the last close
  don't read as continued trading (WRK). A `liquidation`, `compliance_failure`,
  `expiration` or `unknown` delisting always clips, however much (and however
  varied) the fails evidence that follows — `ticker_history` records exchange
  listings, and OTC pink-sheet trading after a real bankruptcy delisting is
  not that listing continuing (RHD, Smurfit-Stone, Idearc, GGP). An
  *unconfirmed* last-trade day (the no-Form-25 "continued 10-K/Q filings"
  fallback substitutes the security's own last sighting when it has no
  last-trade evidence at all) is too weak a guess to second-guess against
  fails evidence either — Monster Worldwide and SunPower traded normally for
  years after such a guess; the guess, not the listing, was wrong. A worked-out
  closing day (sub-plan 5d rule 4, source `closing_day`) is unconfirmed too: it
  clips the ranges at that day, before the Form 25's effective date, and is
  never second-guessed nor published. A security
  none of whose delistings ends it, and that isn't listed today either, is
  left unclipped, ending at its last real sighting.
  A successor's ticker is not its predecessor's (`pipeline._successor_starts`, one map shared by the clip check and
  the ranges): when a delisting's successor is another security X that holds ticker T from day F (X's first
  sighting under T on or after the delisting's confirmed last trade day, or from 30 days before its delist date
  when the day is unconfirmed or missing, and never more than 120 days after that anchor: a later one is a
  recycled ticker, no F; computed again from the final delistings after the handoff stage, which creates
  continuation rows, and a security with an ending whose ticker a successor took is not listed today, whatever its
  issuer's EDGAR listing says: AON 2012), the
  security's fails rows and sightings under T from F on are X's. They do not count as it continuing
  (`_continues_after`: AON 2012), and its T range (and old-CUSIP range) ends the day before F (`history_rows`:
  STX 2021, CRC 2016, ODP 2020).
- **`observation_map.csv` is the caller's join surface, not a review table.**
  Every distinct input observation gets one row: its era, its `sec_id` (blank
  when unresolved), the era's issuer CIK, the security's `ticker_history`
  spelling and coverage on that date (`history_ticker`/`in_ticker_history`),
  and a `status` — the first that applies: `unresolved` (no `sec_id`),
  `after_delisting` (not listed today, `as_of` past the clipped history end),
  `conflict` ((ticker, as_of) seen under two names), `backfilled_ticker` (no
  fails-to-deliver row of the security's CUSIPs under the observed ticker
  within 30 days, but one under another symbol — a caller's snapshot
  projected a later ticker backward), else `mapped`. A `backfilled_ticker`
  observation still gets its `sec_id` here, but adds no range to
  `ticker_history` (`history.filtered_ticker_sightings`) — index membership
  comes from this table, a ticker look-up by date from `ticker_history` keyed
  on `history_ticker`, not the raw observed ticker.
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
  `{"__version__": 4, ...}`, each answer keyed `TICKER|date|observed name`
  (versions 2 and 3, keyed `TICKER|date`, load re-keyed from their stored
  `member_name`; an older file is ignored, not trusted, and replaced on the
  next save) and never holds a miss, a second-pass (`infer_issuers`) answer, or
  an answer that rested on a failed request or a stale copy. The pipeline
  writes it after each resolving stage and on the way out of a run.
- **`payouts.csv` is gated; `delistings.csv` carries the raw extraction
  alongside it.** Every merger payout is checked against the last trade close
  (`payout_gate.reconcile`) before it reaches `payouts.csv`; `delistings.csv`
  keeps the raw, unchecked extraction in its `raw_payout_per_share` /
  `raw_payout_source` / `raw_payout_confidence` columns. An election whose cash and stock legs together reconcile,
  when neither does alone, is its default package (`llm_election_package`, sub-plan 5e); either-or legs are never
  summed.
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
  defaults; it writes nine tables to `output/` and the six contract files to
  `output/contract/` in the same group, all committed artifacts.

## Design/plan docs

Specs and implementation plans live under `docs/superpowers/specs/` and
`docs/superpowers/plans/` (e.g. the BMP correction and payout-extraction
features). Follow that location for new feature design docs.

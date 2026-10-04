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
pytest   # full suite (1831 passed, 281 xfailed: 18 known-wrong golden + the diagnosis truth set's known_wrong cases, all strict; offline, no network)
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
python scripts/classify_universe.py --observations obs.csv   # → output/{securities,ticker_history,cusip_history,delistings,payouts,review,review_summary,observation_map,uncertain}.csv + contract/{security_history,delistings,seeds,price_requests,id_changes}.csv + scorecard.json (NETWORK; free when cached)
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
python scripts/classify_universe.py --observations obs.csv --last-trade-closes lt.csv --merger-terms terms.csv --recoveries rec.csv   # → output/{securities,ticker_history,cusip_history,delistings,payouts,review,review_summary,observation_map,uncertain}.csv + contract/{security_history,delistings,seeds,price_requests,id_changes}.csv + scorecard.json
python scripts/compute_corrected_returns.py --panel panel.csv --delistings output/delistings.csv --out corrected.parquet   # firm-month BMP correction, keyed on sec_id
# override-CSV columns are keyed by sec_id[,delist_date] (a blank/absent delist_date applies to every delisting of that security): lt.csv=`sec_id,last_trade_close[,delist_date]` · terms.csv=`sec_id,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker[,delist_date]` · rec.csv=`sec_id,recovery_ratio[,delist_date]`. A malformed file, or a row that matches no delisting, stops the run before anything is written (exit 2, one stderr line naming the file and line).
# --review-decisions PATH (default data/review_decisions.csv) is read the same way: sec_id,delist_date,ticker,flag,decision,note. Missing at the default path means no decisions; missing at an explicit path, or a bad file, exits 2.
# (append --limit N --output-dir /tmp/sub to classify_universe
# for a fast cached/offline subset; never write a subset into output/, the committed-output tests read it)
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
reason, evidence`, plus `sec_id`, `delist_date`, `successor_sec_id` (a
continuation only) and `ticker_successor_sec_id` (a ticker takeover) —
optional fields the new pipeline (`delistings.py`/`pipeline.py`) fills in
alongside the original ones. `pipeline.py`'s `run()` is the orchestration
that turns a list of observations into the nine output tables: a short
`_run` calls one function per numbered stage (`_refine`, `_resolve_issuers`,
`_resolve_securities`, `_security_cusips`, `_find_delistings`,
`_dead_before_sighting` (stage 5b: a security whose last real ending came before its
first observation and that has no trading fails row died before the run's fails
window began, so (eligibility decided first, then) rows for [end − 1095 d, end + 10 d] are loaded, it takes the
CUSIPs `history.backfill_cusips` finds that no other security holds and its sightings are rebuilt; no `sec_id`
or issuer changes),
`_check_overrides`, `_last_trade_closes`, `_merger_payouts`,
`_find_successors`, `_handoffs`, `_date_from_notices` (stage 9c: a handoff continuation row's last trade day from its own Form 25's confirmed EX-99.25 notice, when before the successor's first sighting and no later than the effective date; metered as "handoff notice dates"), then the row builders and `_triage`), each with explicit
inputs and outputs and the run-wide `_RunContext` (clients, run date, log,
workers, SEC meter `manifest.StageMeter`). Each stage returns what it produces
(`_Successors` for stage 9, for instance) and `_run` combines the answers
(`_link_successors` records the successors on the delistings). Helpers that
belong to one kind of data live with it, not in `pipeline.py`:
`degraded.py` (the `resolution_degraded` rows and flags), `ftd.close_age`,
`review_triage.merge_review_rows`, the era review rows in `security_master`.
See `CONTEXT.md` for the vocabulary its docstrings and variable names assume
(security, era, sighting, pin, …).

**Classification (network):**
- `observations.py` — `Observation`, `TickerEra`, `ObservationIndex`: splits
  one ticker's observations into eras (runs that belong to one security),
  splitting on a name mismatch, a pin change, or a gap over `ERA_GAP_DAYS`
  that neither side's name confirms as continuous.
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
  CUSIP on the day, then its symbol); `by_cusip`/`by_symbol` supply CUSIP
  history, `trading_rows` the rows not under a deleted symbol, `symbol_deleted`
  whether a CUSIP's last rows are all under one, `descriptions` a CUSIP's names;
  `FTD_START` (2004-01-01, the data's first day) and `close_age` (a fails
  row's close age in trading days, for `ftd_close_prior:<n>`).
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
  thread, carried on `LastTrade.halt_feed_failed` by the finder, and turned
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
- `ticker_resolver.py` — `(ticker, as_of_date) → CIK`, 6 strategies in order of
  precision (caller's `cik` pin → manual override → `company_tickers.json` →
  EFTS Form-25/15 → observation-name company search → 8-K frequency rank),
  each strict-validated. The name tier finds its candidates in SEC's
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
  and the check flag `issuer_cusip_disagrees` names both CIKs.
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
  `observation_conflict_review` (`observation_conflict:<date>`).
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
  one after which its own CUSIP keeps trading under its own ticker.
- `added_securities.py` — `AddedAcquirer`/`AddedSuccessor` (`AddedSecurity`): a
  security the run adds that no observation names, with its one
  ticker_history row.
- `successors.py` — the successor after a FIGI change: a security of the run
  that starts right after the last trade (`successor_in_run`, `SecurityStart`),
  else the successor issuer's 8-K12B found by full-text search
  (`successor_search_args`, `successor_query`, `successor_from_8k12b`,
  `successor_search_name`).
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
  `handoff_takeover_no_delisting`), `drop_resolved_shared`. Run by
  `pipeline._handoffs` after the successor search, before the history rows.
- `acquirers.py` — a merger's acquirer as a security: `find_acquirer` (its
  composite FIGI from the fails rows under the acquirer ticker) and
  `acquirer_cik` (its issuer CIK, never the target's).
- `html_text.py` — `strip_html()`: filing HTML as plain text, for the EDGAR
  client's text cache and Form 25 parsing.
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
  disagreement is flagged `last_trade_date_conflict`). The text's `_OPEN`
  wordings (suspended/halted "before the open", "prior to the market opening",
  "before market open", "prior to the commencement of trading", "as of the open
  of business", "at the opening of business" on D) date the last trade on the
  trading day before D (source `8k_301`, kind `8k_open`).
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
  exchange-transfer detection, and SEC-revocation. Rule order unchanged; the
  continued-filings rule now asks `end_of_era.resolve` instead of
  deciding alone, and records the branch in `evidence["end_of_era"]`.
- `end_of_era.py` — the end-of-era resolver's first step: where the registrant
  kept filing after the end. `signals()` reads the filings in the windows around
  the end date (8-K items, successor filings and Form 25s in [end − 30 d,
  end + 120 d]; merger filings — DEFM14A, DEFM14C, PREM14A, SC 14D9, SC TO-T,
  SC TO-I, SC 13E3, 425, S-4 — in [end − 540 d, end + 30 d]); `resolve()` takes
  the first branch that fits: (1) still trading after the end (the finder's
  `continued`, passed as `classify_event(..., trading_after=)`) → today's
  transfer; (2) a successor registration (8-K12B, 8-K12G3) → a transfer whose
  successor stage 9 finds; (3) a change in control (8-K 5.01) → merger; (4) a
  completed acquisition (8-K 2.01) with a merger filing or a Form 25 → merger;
  (5) a 3.01 notice whose text cites a listing deficiency → compliance failure
  570; (6) else today's continued-filings transfer (304), its reason string
  unchanged (`lifecycle.CONTINUED_FILINGS` is its prefix). EDGAR evidence only.
  Tried only where the continued-filings rule fires.
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
  (`TABLES`), `DelistingKey` (a delisting's `(sec_id, delist_date)` key, here so
  the classification layer — the finder — and the handling layer can both use
  it without one importing the other), `format_cell` (the one cell formatter
  every table shares), `write_tables`/`read_table` (every table to a temp
  file first, then renamed into place one by one,
  `atomic_io.replace_all_on_success`), and `read_delistings_frame`
  (delistings.csv as a typed pandas DataFrame: `qlib_adapter.load_delistings`
  reads through it). Every table read — `qlib_adapter`, `accept_review.py`,
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
  the security master's and the pipeline's), `.row()` its review row;
  `merge_review_rows` joins rows that share a key. Called by `pipeline.run()`
  just before the write; never touches `delistings.csv`.
- `degraded.py` — answers that rested on a failed request or a stale copy:
  `DegradedWatch` (an SEC read on this thread counted itself degraded),
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
- `dlret.py` — DLRET hub: `resolve_dlret`/`DlretResult`/`compute_dlret` (self-explaining delisting return; `otc_print=` gives `DlretMethod.OTC_PRINT` on a liquidation or compliance_failure, a `--recoveries` ratio winning, a merger ignoring it). `bmp_correction.py` re-exports for backward compatibility.
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
  requires to be 0.
- `diagnosis_loop.py` — the loop's ledger (`output/diagnose_unknown_report/loop/diagnosed.csv`), error keys, case
  rows for the diagnose workflow, and placeholder renames (`contract/id_changes.csv` and the base commit's securities.csv, `regression.id_changes_since`; `write_together` writes the truth file and its change log as one set).
- `truth_update.py` — spec 1.6's rules for what a round's diagnoses may change in the truth file. A regression is
  added only when it is verified and upheld. A mismatch changes the truth only when the diagnosis cites a filing the
  earlier report missed. `flip_statuses` turns a known_wrong case that now matches into pass.
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
  continuation, `dlret` and `dlret_fill`; `MEASURED_METHODS` includes `otc_print`, so an answered OTC print is a value, not a fill) and `is_distress`. Today's bucket and CRSP code map to the exit kind
  (a code-470 bankruptcy is `dropped` for `bankruptcy`; `unknown` asserts none). The contract, the golden judge
  and the scorecard all read through it.
- `contract.py` — the contract's rows (spec "The contract", decisions 6, 7, 9, 10, 12), written under
  `output/contract/` beside today's tables for one release: `security_history_rows` (ticker ranges split where
  the issuer in force changes), `delisting_rows` (one per ended security, its last), `seed_rows` (the seed
  echo), `id_change_rows` (baseline placeholders that now hold a FIGI). `run_manifest.json` carries
  `schema_version` (`store.CONTRACT_SCHEMA_VERSION`).
- `issuer_in_force.py` — the issuer CIK on each sighting's date: the era's CIK when its EDGAR name that day agrees
  with the observed name, else the one other CIK SEC's name index lists under that name whose name agreed then
  (MRK 2008: old Merck & Co, CIK 64978). `issuer_changes` dates each change: it sorts sightings by day then CIK
  and records at most one change per day (a same-day sighting under another CIK changes nothing).
- `payout_rule.py` — the payout rule of each contract ending (`value_fields`, the eleven columns after `verdict` in
  `contract/delistings.csv`, schema version 2): `value_rule` (`VALUE_RULES`), `cash_per_share`, `stock_ratio`,
  `price_sec_id`/`price_ticker`/`price_date` (the acquirer for a stock leg, the security itself for `otc_print`; the
  trading day after the last trade), `recovery_ratio`, `terms_source`, `terms_gate` and `value_formula`; the caller
  computes `dlret = payout / last close − 1` with its own prices. `merger_inputs` collects a merger's `--merger-terms`
  row, LLM terms and regex read from before the payout gate: terms the gate dropped are still published,
  `terms_gate=failed` (a failed election publishes both legs as read). `cash_currency` is always blank. The scorecard counts
  `R2.7.value_rule.<rule>` and floors `R2.7.payout_rule_known`.
- `price_requests.py` — `contract/price_requests.csv` (`last_close` per ending with a published date,
  `received_close` per LLM-read stock leg, `otc_print` per `dropped`/`liquidation` ending that is not a continuation, dated the session after the last trade) and `load_answers` for `--price-answers`,
  which refuses a price that is not a finite positive number.

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
  pipeline's issuer-names read, delisting search and payout extraction,
  `listing_status.listing_answers`, the prefetch pool, the ticker resolver's
  four EDGAR checks (`_fits_date`, `_name_search`, `_name_match_score`,
  `_validate_cik`), and the CLI, which turns it into the exit code; a new one
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
  `output/contract/{security_history,delistings,seeds,price_requests,id_changes}.csv` from the tables about to be
  written and the verdicts; the scorecard (10h) reads the issuer from `contract/security_history.csv`. Contract
  delistings hold one row per ended security, its last real ending; `last_trade_date` is published only from an
  exchange print no later than the Form 25 effective date; a continuation has no value; assumed par, Shumway marks
  and a transfer's 0.0 are `dlret_fill`. `--price-answers` (the requests plus a `price` column) feeds the closes and
  acquirer prices, so a second run changes values only; the answers are applied at stage 6b and again after the
  handoff stage adds delistings, always from the caller's own overrides. A price that is not a finite positive
  number, an answer to no request, or a last close also given by `--last-trade-closes`, exits 2 before anything is
  written. Today's nine tables keep their columns.
- **Every output is written only after the whole run succeeds.**
  `pipeline.run()` computes every table in memory first and writes all nine
  and the five contract files (same group) only at the end (`store.write_tables`): each table is formatted and written
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
- **`ticker_history` is clipped only at the delisting that actually ends the
  security.** One whose successor is the security itself (a continuing
  exchange transfer) never clips it. Otherwise, only a `merger` or
  `exchange_transfer` delisting with a *confirmed* last-trade day (not
  `last_trade_date_unconfirmed`, and not blank) can be second-guessed: it
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
  years after such a guess; the guess, not the listing, was wrong. A security
  none of whose delistings ends it, and that isn't listed today either, is
  left unclipped, ending at its last real sighting.
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
  defaults; it writes nine tables to `output/` and the five contract files to
  `output/contract/` in the same group, all committed artifacts.

## Design/plan docs

Specs and implementation plans live under `docs/superpowers/specs/` and
`docs/superpowers/plans/` (e.g. the BMP correction and payout-extraction
features). Follow that location for new feature design docs.

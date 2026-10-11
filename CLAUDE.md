# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

It is an index. The long text lives in `docs/architecture.md` (every module), `docs/invariants.md` (every invariant in
full) and `docs/commands.md` (every command, with its notes). Read the entry's pointer before you change that area.

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
pytest   # full suite (4170 passed, 43 xfailed: the known-wrong golden cases and the diagnosis truth set's known_wrong cases, all strict; offline, no network)
pytest tests/test_payout_extractor.py -v  # one file
pytest tests/test_payout_extractor.py::test_match_in_cash_family_altr -v   # one test
python scripts/verify_altair.py          # smoke: ALTR → CRSP 231, high
python scripts/scorecard.py              # offline: recompute output/'s scorecard vs data/scorecard.json; --check (exit 1 on a drop or a failing golden or diagnosis `pass` case)
python scripts/classify_universe.py --observations obs.csv   # (NETWORK; free when cached)
python scripts/classify_universe.py --observations obs.csv --limit 20 --no-extract-payouts --no-midas --no-halts --output-dir /tmp/sub   # fast dev subset; never write a subset into output/
python scripts/classify_universe.py --observations obs.csv --sec-workers 1   # one SEC prefetch thread; with `--extract-merger-terms-llm` add `--llm-workers 1` for one SEC request at a time (default: 4 prefetch threads, max 8, one machine-wide 8 req/s limit)
python scripts/classify_universe.py --observations obs.csv --extract-merger-terms-llm --llm-workers 16   # threads that make the `--extract-merger-terms-llm` calls ahead; default 8, max 16; independent of `--sec-workers`; the tables are the same for any count
python scripts/classify_universe.py --observations obs.csv --as-of 2026-09-25   # pin the run date (default today; run_manifest.json records it)
python scripts/classify_universe.py --observations obs.csv --extract-merger-terms-llm   # → output/delistings.csv with cash_plus_stock/stock_only rows (NETWORK: SEC + the LLM endpoint)
python scripts/classify_universe.py --observations obs.csv --last-trade-closes lt.csv --merger-terms terms.csv --recoveries rec.csv   # override-CSV columns are keyed by sec_id[,delist_date]
python scripts/compute_corrected_returns.py --panel panel.csv --delistings output/delistings.csv --out corrected.parquet   # firm-month BMP correction, keyed on sec_id
python scripts/accept_review.py --flag terms_gate_failed --note "sampled 5, all fine"   # bulk-accept every current review.csv row carrying that flag → appends to data/review_decisions.csv (offline)
python scripts/build_golden_fixtures.py  # rebuild the 31-case golden regression set (NETWORK); --efts-only / --llm-only / --only ID
# In this worktree the editable install still points at the main checkout, not this tree's src/ — prefix every script with PYTHONPATH=src, e.g.:
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations obs.csv
```

There is **no lint/format tooling** configured — do not invent a lint command.

Every other script (the truth loop, the fixture builders, the observation builders, `regen_payout_fixtures.py`,
`--price-answers`, `--id-baseline`), the output file lists, the override-CSV columns and the notes on
`--review-decisions` and the LLM terms gate are in `docs/commands.md`. The files `classify_universe.py` writes are listed
there and in `docs/invariants.md`, "Configurable input paths".

## Architecture: concept subpackages, imports one way

The package is `src/delist_detection/`: nine subpackages and the run (`pipeline.py`) at the root. Full layout tree:
`docs/architecture.md`, "Package layout and import direction".

Imports run one way, and `tests/test_import_closure.py` reads them from the real import graph (top level, inside a
function and under `TYPE_CHECKING`). The vocabulary imports nothing; sources import the vocabulary; filings and
outputs import sources; identity imports filings and outputs; endings import identity; terms import endings; each
also imports everything below what it names. measurement and handling import outputs and the vocabulary, and from
sources only the plumbing that loads no client (`atomic_io`, `sec_stats`), never a client. Nothing imports
`pipeline.py`. The two named type-only exceptions and the reason `outputs` sits below the stages: the same section.

The entries below say what each subpackage holds. Each module's full description is under its subpackage's heading in
`docs/architecture.md`; `CONTEXT.md` has the vocabulary those descriptions assume (security, era, sighting, pin, …).

- `pipeline.py`: the run. `run()` turns a list of observations into the seven output tables; a short `_run` calls one
  function per numbered stage, each with explicit inputs and outputs and the run-wide `_RunContext`. `Clients` is the seam
  every stage reads SEC, OpenFIGI, the fails files, MIDAS, the halt feed and the LLM through. The stage list is in
  `docs/architecture.md`, "The run: pipeline.py".
- `DelistRecord` (`outputs/reconstruction.py`): the hand-off object from the classifier to the table and the handling.
  Detail: `docs/architecture.md`, "The hand-off object: DelistRecord".
- `vocabulary/`: the leaves, each importing nothing of the package: `identifiers`, `names`, `trading_calendar`,
  `crsp_codes` (the bucket, not the exact code, drives all downstream handling), `exchanges`, `exit_kind`. Detail:
  `docs/architecture.md`, "vocabulary/".
- `sources/`: the SEC, OpenFIGI, Nasdaq and LLM clients and their plumbing. `edgar` (the throttled, on-disk-cached SEC
  client), `sec_limiter` (the SEC rate limit), `sec_stats`, `fatal` (`FATAL`: the exceptions that stop a run), `retries`,
  `settings`, `atomic_io`, `sec_http`, `ftd` and `ftd_store` (fails-to-deliver), `midas`, `nasdaq_halts`, `openfigi`,
  `html_text`, `cik_lookup`, `llm_client`, `prefetch`, `capabilities`. Detail: `docs/architecture.md`, "sources/".
- `filings/`: what SEC filings say, read by several stages: `evidence`, `form25`, `listing_status`, `filing_search`.
  Detail: `docs/architecture.md`, "filings/".
- `outputs/`: what a run publishes, as rows: `store` (every table's column order, key and sort order, `TABLES`),
  `review_triage`, `degraded`, `manifest`, `run_snapshot`, `verdict`, `contract`, `dlret` (an ending's value, decided
  once), `payout_rule`, `price_requests`, `reconstruction`. Detail: `docs/architecture.md`, "outputs/".
- `identity/`: a security's identity, stages 1 to 4c: `observations`, `figi_resolution`, `security_master`,
  `ticker_resolver`, `issuer_record`, `issuer_in_force`, `identity`, `history`, `added_securities`, `ticker_evidence`,
  `line_follow`, `derived_lines`, `carried_price`. Detail: `docs/architecture.md`, "identity/".
- `endings/`: every delisting, found, dated and classified, stages 5 to 9g: `delistings` (`DelistingFinder.find()`),
  `trading_record`, `classifier`, `end_of_era`, `distress`, `exchange_terms`, `own_shares`, `continuation_evidence`,
  `last_trade` (the last trade date as one module), `rewrites` (the one owner of a delisting's kind and successor after
  its record is built), `registrants`, `successors`, `handoffs`. Detail: `docs/architecture.md`, "endings/".
- `terms/`: what one share of a merger ending became, stage 8: `merger_value`, `payout_gate`, `payout_extractor`,
  `llm_merger_extractor`, `filing_selection`, `currency`, `acquirer_line`, `acquirers`, `acquirer_ticker`. Detail:
  `docs/architecture.md`, "terms/".
- `measurement/`: how far a published run is from the truth: `lifecycle`, `scorecard`, `audit`, `truth`,
  `diagnosis_truth`, `truth_set`, `truth_build`, `truth_update`, `regression`, `loop_round`, `disputes`. Detail:
  `docs/architecture.md`, "measurement/".
- `handling/`: delistings.csv for training and backtests, pure, keyed by `sec_id`: `handling` (event-level) and
  `qlib_adapter` (DataFrame splicers over a `(datetime, instrument)` panel). Detail: `docs/architecture.md`,
  "handling/".

There are **two return-correction APIs** for different research conventions:
event-level (`handling.build_train_label_adjustment`/`build_backtest_exit`) vs CRSP-style firm-month
(`handling.firm_month_correction`, its DLRET from `dlret.decide`). Don't conflate them. Why the firm-month correction and
delistings.csv's `dlret` can differ on purpose: `docs/architecture.md`, "handling/".

## Rules that prevent expensive mistakes

Each rule is in full under the heading named after it in `docs/invariants.md`.

SEC and other networks:
- SEC fair access: `EdgarClient` throttles to 8 req/s and requires a descriptive `User-Agent`, from `EDGAR_USER_AGENT`
  (environment first, then the repo `.env`); SEC 403s the noreply fallback, so set it. The CLI refuses to start without
  it. Detail: "SEC fair access".
- One limiter, `sec_limiter.SEC_LIMITER`, is shared by every thread of the process and, through
  `~/.cache/delist_detection/sec_rate.lock` (`$DELIST_DETECTION_SEC_RATE_LOCK`), by every SEC client on the machine.
  Detail: "SEC fair access".
- `WebFetch` is **403'd by SEC**: for ad-hoc EDGAR fetches use
  `curl -A "$(python -c 'from delist_detection.sources.edgar import resolve_user_agent as r; print(r())')"`.
- An agent sandbox must set `DELIST_DETECTION_SEC_RATE_LOCK` to a writable shared path; this repo's agent runs use the
  one path `/tmp/claude/delist_detection/sec_rate.lock`. An agent-sandbox run and a terminal run use *different* lock
  files and never share a gate: only one SEC client may run at a time across the two, coordinated by hand (the
  controller confirms no other client is running before a live run). Detail: "SEC fair access".
- A failure is never cached, and a 403/429 raises `EdgarBlocked` at once. Detail: "SEC fair access".
- Speed: `--sec-workers 8` for a cold or large refetch, `--sec-workers 1` for a rerun whose caches are already warm; the
  CLI default stays 4. Output is byte-identical for any N given the same caches and run date. Measured figures and the
  company-name-search 429 history: "Measured SEC request speed".
- An agent-sandbox run must allow the host in `OPENAI_BASE_URL` (`api.anthropic.com` or `api.openai.com`): a blocked LLM
  host raises on every call, each becomes a miss, and the run exits 0 with those mergers' terms missing. Detail: "The LLM
  endpoint is the one `.env` names: OpenAI or Anthropic".

The LLM:
- The endpoint and model are the ones `.env` names (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `CHAT_MODEL`);
  `ANTHROPIC_API_KEY` is never read. The cache file name carries the model, so a new model sends every merger filing
  again; rerun `scripts/eval_merger_extractor.py` for it. An LLM call in flight is not cancelled by an abort or Ctrl-C.
  Detail: "The LLM endpoint is the one `.env` names: OpenAI or Anthropic".

Runs and outputs:
- Never write a `--limit` subset into `output/` (the committed-output tests read it): append `--output-dir /tmp/sub`.
  Detail: `docs/commands.md`.
- Exit codes: 0 completed; 1 only an unexpected crash; 2 a refusal (`EdgarBlocked`, `OpenFigiBlocked`) or a bad input
  file (one stderr line naming the file and line); 3 a completed run whose `review.csv` has an `error` or
  `resolution_degraded` row (outputs still written); 4 `OpenFigiUnavailable` (no outputs written; rerun later). Detail:
  "OpenFIGI refusals abort too".
- Every exception that stops a run is listed once, in `sources/fatal.py` `FATAL`, and every catch site re-raises that
  tuple before turning a failure into a row, a miss or a transient answer; a new one is added in `sources/fatal.py` only.
  Detail: "OpenFIGI refusals abort too".
- No placeholder stands in for an unavailable OpenFIGI answer (it would change `sec_id`s between runs). Detail: same.
- Every output is written only after the whole run succeeds (`store.write_tables`); a run killed between two renames can
  leave some tables new and the rest old, each single table whole. Detail: "Every output is written only after the
  whole run succeeds".
- Filing ids stay inside the library; a new `delistings.csv` column would make `run_snapshot` refuse every older commit's
  file. Detail: "A merger payout is gated; `delistings.csv` carries both the gated and the raw read".
- An ending's kind and successor change after the finder built it only by a rewrite (`endings/rewrites.py`), never a
  stage's own field edit. Detail: "An ending's kind and successor change after the finder built it only by a rewrite".
- The resolver cache `cache/ticker_resolution.json` is versioned (`__version__` 4); an older file is ignored and
  replaced. Detail: "The resolver cache is versioned".

Identity and data:
- `sec_id` is a US composite FIGI, or a placeholder `CIK<cik>-<CLASS>`; `identity/figi_resolution.py` never accepts a
  candidate on Bloomberg's current name alone. Detail: "`sec_id` is a US composite FIGI, or a placeholder".
- Ticker recycling (e.g. ALTR was Altera then Altair) is handled by `observations.split_eras` and by `MANUAL_OVERRIDES`
  in `scripts/classify_universe.py`. When web verification proves a wrong CIK, extend that dict — don't patch the
  resolver. Detail: "Ticker recycling".
- A delisting is a Form 25 removal, not a rename and not a secondary withdrawal. Detail: "A delisting is a Form 25
  removal — not a rename, not a secondary withdrawal".

Review, scorecard and tests:
- Tests are fully offline. Use the `FakeEdgar` fixture (`tests/conftest.py`) and committed fixtures; every client has its
  own fake or fixture-backed double; never add network to the test path. Detail: "Tests are fully offline".
- The golden set is the regression gate: `tests/fixtures/golden/` (31 cases, from `data/golden_events.csv`); every case
  must stay green. `scripts/build_golden_fixtures.py` rebuilds it after a live-data change. Detail: "The golden set is
  the regression gate".
- The scorecard only moves one way: `tests/test_scorecard_floor.py` fails when a floored number got worse; a floor entry
  is lowered only by hand, with the reason in the commit. A `--limit` run is never compared to the floor. Detail: "The
  scorecard only moves one way".
- Every fix sub-plan passes the diagnosis truth loop; it is accepted only when `D.mismatches` fell and
  `scripts/scorecard.py --check --base <commit>` passes. Detail: "Every fix sub-plan passes the diagnosis truth loop".
- `error` and `resolution_degraded` review rows can never be accepted (the fix is a rerun); decisions never change
  `delistings.csv`. `scripts/accept_review.py` takes a bare flag name in `review_triage.CATALOG` and needs `--yes` for a
  `fix`-severity flag. Detail: "`review.csv` is triaged, not raw; `review_summary.csv` groups it by cause" and
  "`scripts/accept_review.py` refuses mistakes rather than silently doing nothing".
- Validation is the review loop and the scorecard, not eyeballing. Detail: "Validation is the review loop and the
  scorecard".

## Invariants in full

Each heading below is in `docs/invariants.md`.

- "An issuer is read through the run's issuer record, once": every issuer read goes through `Clients.issuers`; a failed or
  stale read gets `resolution_degraded`.
- "`review.csv` is triaged, not raw; `review_summary.csv` groups it by cause": severities, `no_dlret`, decisions file.
- "The scorecard only moves one way" and "Every fix sub-plan passes the diagnosis truth loop": the floor and the loop.
- "Every seed, security and ending has a verdict, and every uncertain one is in `uncertain.csv`".
- "The contract is written beside today's tables for one release (decision 6)": `output/contract/` and `--price-answers`.
- "A Form 25 is reached, matched and owns its row (sub-plan 5b)".
- "An ending's kind follows the registrant's role and R1 (sub-plan 5c)".
- "A line is followed past its observations (sub-plan 5a, rulings R1 and R2)".
- "`ticker_history` is clipped only at the delisting that actually ends the security".
- "`observation_map.csv` is the caller's join surface, not a review table".
- "Payout extraction is cash-only; the DLRET table supports full consideration".
- "A merger payout is gated; `delistings.csv` carries both the gated and the raw read".
- "Configurable input paths": `--observations`, `--output-dir`, `--cache-dir`; the tables written.

## Design/plan docs

Specs and implementation plans live under `docs/superpowers/specs/` and
`docs/superpowers/plans/` (e.g. the BMP correction and payout-extraction
features). Follow that location for new feature design docs.

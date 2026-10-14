# Non-obvious invariants

## SEC fair access

- **SEC fair access.** `EdgarClient` throttles to 8 req/s and requires a
  descriptive `User-Agent`. Every response is cached under `cache/edgar/` (JSON)
  and `cache/edgar/text/` (stripped filing HTML), so re-runs cost nothing; these
  caches are gitignored and re-derivable; the parsed fails-to-deliver copies are a cache like the rest (1.9 GB;
  gitignored with `cache/`). The User-Agent comes from
  `EDGAR_USER_AGENT` (environment first, then the repo `.env`, via
  `edgar.resolve_user_agent()`); SEC 403s the noreply fallback, so set it.
  `sources/sec_http.py` (FTD, MIDAS) shares the same throttle, User-Agent and
  `EdgarBlocked`. `WebFetch` is **403'd by SEC** — for ad-hoc EDGAR fetches use
  `curl -A "$(python -c 'from delist_detection.sources.edgar import resolve_user_agent as r; print(r())')"`.
  A connection error, a timeout, or a 5xx on `_get_json`/`fetch_filing_raw`/
  `fetch_filing_text`/`full_text_search`/`sec_http` downloads retries up to 3
  attempts (2s/4s backoff, `edgar.retry_request`, inside `edgar.sec_get`); a 403/429 still raises
  `EdgarBlocked` at once, and a failure is never cached.
  A filing list is a main file and older pages, and its cached copies are read only as one list: each page
  fetched under the copy of the main file it is read with. Any other list is fetched again from the top, the main
  file first and the pages in order (`EdgarClient._whole_list`, FB-025), and a fetch that fails is a stale read,
  which flags the row that rested on it. A main file fetched again for its profile alone takes the pages the cache
  holds with it (`EdgarClient.submissions`, `_holds_a_page`), so a run never leaves a filing list with fewer
  filings in its cached copies than it found (McEwen, FB-028's runs: a fresh main file beside the page of May,
  23 filings of 2012 in neither).
  A cached filing list with no fetch date has no known age: it is fresh for no caller that asks for a fresh copy,
  and its file time is never read, because a copied cache carries the day of the copy (`edgar._stamped_on`, FB-028).
  The search for an ending reads an issuer's filings with no day of its own, so stage 5 first makes the issuer's
  list current for the security's last sighting (`issuers.profile(cik, about=last_seen)`). A security the search
  then leaves open (`pipeline._left_open`: no real ending found on or after its last sighting) has its issuers, a
  successor registrant in force among them, made current for the run date, and is searched again: the last
  sighting of a security with no fails row for 45 days says nothing of how old a copy may be. So a run as of D
  reads no list fetched before D for a security it leaves open. `run_manifest.json` counts the issuers of the
  securities the run leaves open whose list it read from a copy fetched before the run date, or with no fetch
  date (`open_issuers_read_before_as_of`, `pipeline._old_open_issuers`): 0 unless a read failed or a stage read
  an issuer the search did not.
  A security the run adds (a successor, an acquirer's line) is never searched by stage 5, so stage 9d reads its
  issuer as of the run date before it looks for its ending (`_successor_endings`).
  A run as of D leaves out the filings dated after D (`edgar._as_filed_by`) and reads the names as the copy has
  them: EDGAR lists a current name among the former ones with its first day (Accenture plc, from 2009-09-01), so
  a former name that outlasts D is no rename after D. A fresh copy can therefore date a name SEC had not dated
  before (Matson's "Matson, Inc." from 2012-07-03, added on 2026-10-01), and the issuer dates that rest on it move.
  The limiter (`sec_limiter.SEC_LIMITER`) is shared by every thread of the process
  and, through `~/.cache/delist_detection/sec_rate.lock`
  (`$DELIST_DETECTION_SEC_RATE_LOCK`), by every SEC client on the machine
  (`sec_limiter.use_machine_wide_limit()`, installed by the CLI, `default_clients`
  and `build_golden_fixtures.py`). `--sec-workers N`
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

## Measured SEC request speed

- **Measured SEC request speed** (task 16's live measurement, 2026-09-24). Cold
  runs on 150 eras: 1 worker 18m, 4 workers 11m, 8 workers 5m (3.6× wall time; issuer resolution 4.6×). A fully
  warm full-universe rerun (no SEC request, no LLM call) took 3 m 35 s at 1 worker and 4 m 11 s at 4, measured
  at `f808b15` on 2026-10-10 with the full `data/observations.csv`, `--as-of 2026-09-25` and
  `--extract-merger-terms-llm`. The untouched fork point `799d1bc` took 10 m 59 s on the same input (an upper figure: other work ran beside that run). A warm run
  has nothing to fetch, so extra threads only add contention: 4 workers were about 17% slower than 1. The first
  run on a cache without the parsed fails store took 4 m 07 s at 1 worker, about 31 s more than a warm run, the
  one-time build of the store. A two-ticker run (`DAL` and `NWA`, one observation each on 2008-01-16) took 3.7 s
  with the store built and 51.8 s while it built the whole store; the untouched code took 46.8 s. A run that must
  ask the model for every merger (784 calls, measured with a stand-in that sleeps 2.7 s per call, no LLM call
  paid for) took 7 m 51 s at `--llm-workers 8` and 5 m 52 s at 16; one call at a time would take about 39 minutes
  (estimated, not run). The cold-run figures beside these are older (2026-09-24) and were not measured again. Use
  `--sec-workers 8` for a cold or large refetch; use `--sec-workers 1` for a
  rerun whose caches are already warm (a warm pass redoes each stage's CPU
  work but sends no request, so 4 workers is about 17% slower than 1 on a
  fully warm rerun); the CLI default stays 4. SEC's company-name search
  (`cgi-bin/browse-edgar`, the resolver's fallback tier) was 89% of cold
  issuer-resolution time and can slow to ~10 s/request after about 1,500
  searches in under an hour, recovering after ~20 idle minutes; on 2026-09-28
  it answered HTTP 429 (a run-stopping `EdgarBlocked`) three times in a cold
  full run, at 8, 2 and 1 workers. That is why the name tier now reads SEC's
  `cik-lookup-data.txt` (one ~38 MB download; building the index takes about
  9 s and ~440 MB) instead of searching. Peak memory of the warm full-input run at `f808b15` was 4,107 MB at 1 worker (4,189 MB at 4); the untouched `799d1bc` peaked at 5,528 MB (older runs: 1.8–4.2 GB, not profiled); the offline
  whole-run replay (2,468 eras, every cache warm, 1 worker; architecture step 12, 2026-10-07) takes 580 s and a
  5.0 GiB maximum resident set, its fails index holding about 4.0 million rows at the end, and its passes over the
  fails files take 252 s of it, 117 s of them stage 5b's 68 one-security passes (each ~1.7 s);
  the 4-worker warm run peaked 82 MB above the 1-worker warm run, and the two 1-worker runs (first run, warm run) peaked at 4,088 and 4,107 MB, so worker threads add little memory. SEC does not keep full-text-search hit order
  stable between two fetches of the same query: the same cache always gives
  the same output, but a refetch can reorder tied hits (see `docs/data-flow.md`).

## OpenFIGI refusals abort too

- **OpenFIGI refusals abort too.** A 401/403 from OpenFIGI raises
  `OpenFigiBlocked` (`sources/openfigi.py`); `classify_universe.py`'s CLI catches it
  alongside `EdgarBlocked` and exits 2. Every exception that stops a run is
  listed once, in `fatal.FATAL`, and every catch site re-raises that tuple
  before turning a failure into a row, a miss or a transient answer: the
  issuer record's reads (`IssuerRecord._read` and `name_index`: every issuer read of the resolver, the
  classifier's name check and the stages), the pipeline's delisting search and payout extraction,
  `listing_status.listing_answers`, the prefetch pool, the ticker resolver's
  company search (`_name_search`), and the CLI, which turns it into the exit code; a new one
  is added in `sources/fatal.py` only. A 429 is waited out on the
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

## An issuer is read through the run's issuer record, once

- **An issuer is read through the run's issuer record, once.** The resolver, the classifier's up-front refresh and
  name check, and the stages' reads of an issuer's names, filings and first filing (2's names, 4b, 4c/10c3, 8a/8a',
  8b, 9's terms links, 9b) ask `Clients.issuers` (`issuer_record.IssuerRecord`); 10c3 reads the contract's issuer
  timeline before triage, so its failed or stale read is a reviewed row too, and 8a's one read outside the record
  (the resolver's SEC ticker map, which raises on a failed read with no cached copy) is reported by the stage
  itself. A read that fails after the
  client's retries is unknown and never remembered, a refusal stops the run, and the answer that rested on a failed
  or stale read gets `resolution_degraded` (`IssuerRecord.watch`): the handoff stage's read of the successor
  issuer's filings no longer stops a run that has no cached copy (exit 1). Reads still made straight from the
  client, left for later steps: the finder's (its per-security try makes a failure an `error` row),
  `listing_status`'s, `successors.successor_search_name` and stage 9e's 8-K list, and filing texts and notices
  outside the record (the own-share reading reads its filing list and names through the record since step 7b).

## `review.csv` is triaged, not raw; `review_summary.csv` groups it by cause

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
  DLRET (`review_triage.is_blank`), since `dlret.decide` can return NaN with
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

## `scripts/accept_review.py` refuses mistakes rather than silently doing nothing

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

## The scorecard only moves one way

- **The scorecard only moves one way.** Every run builds `output/scorecard.json`
  (`pipeline._scorecard`, stage 10h) from the run snapshot of the rows it is about to write
  (`RunSnapshot.of`; scripts/scorecard.py and the floor test build it from the written folder's, `RunSnapshot.read`,
  so the two agree by construction, payout legs and run date included) and
  writes it after the seven tables and the contract files, before the manifest. `data/scorecard.json`
  holds the caller's training window (data, never code), the floor and the two
  truth files. `tests/test_scorecard_floor.py` recomputes the scorecard from the
  committed `output/` and fails when a floored number got worse, a floored
  metric disappeared, or a golden `pass` case fails;
  `tests/test_golden_lifecycles.py` runs every golden case (`known_wrong` is a
  strict xfail, so a fix forces the row to flip to `pass`: `scripts/scorecard.py --flip`, the flip rule the
  diagnosis set's loop applies too). A plan that improves
  a number runs `scripts/scorecard.py --raise-floor`; a floor entry is lowered
  only by hand, with the reason in the commit. A `--limit` run is never compared
  to the floor. A drop or a failing golden case warns on stderr and never changes
  the exit code; a bad config or truth file exits 2.

## Every fix sub-plan passes the diagnosis truth loop (spec 2026-10-03-diagnosis-truth-fixes)

- **Every fix sub-plan passes the diagnosis truth loop (spec 2026-10-03-diagnosis-truth-fixes).** After the cached
  full run: (1) `truth_loop_round.py` opens the round (`loop_round.Round.open`): it renames the truth rows and legs
  that name a renamed security, judges the run against `data/diagnosis_truth.csv` (the file data/scorecard.json
  names; every script's `--truth` defaults to it) and writes the regression report against the sub-plan's base
  commit; (2) it keeps the errors the ledger (`loop_round.Loop.ledger`) has not seen (mismatch case ids are
  `<truth_case_id>_<label>-r<N>`, regression ids `<sec_id>_<label>-r<N>`, `loop_round.case_id`;
  `regression.excluded(..., id_changes=)` also leaves out placeholders renamed to a truth security); (3) the
  `diagnosis-truth-loop` workflow diagnoses each one in regression or mismatch mode, with a skeptic per case (its
  record vocabulary is `loop_round`'s, checked against the workflow by a test); (4) `update_truth.py` closes the
  round (`loop_round.Round.close`) and applies the outcomes under fixed rules
  (a mismatched truth field never takes a library value unless a verified, upheld diagnosis cites an SEC accession
  the earlier report missed; a regressed row enters the truth file with the side the diagnosis found right for the
  fields the agent saw: a whole added or removed row scores only its brief, and a changed field keeps the base run's
  other scored values, which the regression guard presumes right; the row keeps the ending its case examined, and
  the mismatches it makes are settled under the judge's own keys, `loop_round.new_row_keys`) and commits the truth
  set: the truth file, the
  change log and the ledger together (`truth_set.TruthSet.commit`, `atomic_io.replace_all_on_success`); no script
  writes one of them alone, and a sub-plan's rulings are data passed to `TruthSet.rule` (scripts/apply_5f/5h/5i, apply_fb020_truth_rule.py for the
  contract's `last_trade_date` rule of FB-019 and FB-020, apply_fb021_truth_rule.py for a `cash_per_share` cell
  that leaves out a closing dividend, and apply_fb003_truth_rule.py for a row that names the old News Corp line's
  former placeholder). A
  `pending` ledger row is never re-diagnosed automatically: the operator settles it or deletes the row. The loop
  stops after a round with no new error, or after 3 rounds. A sub-plan is accepted only when `D.mismatches` fell
  and `scripts/scorecard.py --check --base <commit>` passes (`D.unexplained_regressions` 0, `loop_round.unexplained`). `truth_build.UNSETTLED`: an OpenFIGI error or several US
  lines leave a CUSIP-change row `ruling_pending`. `data/diagnosis/` commits only what is read later: the ledger
  (`loop/diagnosed.csv`) and `reports/`, every report a truth row, a change-log row or a pending ledger row cites (the
  evidence for a truth value, which a later round's mismatch diagnosis reads first, and what the operator settles a
  pending row from; `Round.close` copies a round's there). Everything else is gitignored and stays in the checkout
  that wrote it: every sub-plan's loop folder (`loop/<label>/`: each round's cases.csv, records/, reports/ and
  summary.md, so a report only a settled ledger row cites, and the sub-plan's write-ups) and sub-plan 5-0's build
  files (truth_rows/, records/, source.csv, summary.csv, truth_review.md).

## Every seed, security and ending has a verdict, and every uncertain one is in `uncertain.csv`

- **Every seed, security and ending has a verdict, and every uncertain one is
  in `uncertain.csv`.** `kind` is seed | security | ending; `reason` holds
  `code` or `code:detail` items (outputs/verdict.py's docstring lists them). The
  verdict covers identity, exit kind and the last trade date, never the value
  (except assumed par after a failed payout, LLM or terms gate, decision 4, and an ending with no value at all,
  `value_pending`: a wind-down whose distributions are not read, ruling G, and a merger whose terms nothing
  states, FB-016; the spec's invariant; and a value the library knows to be incomplete,
  `value_incomplete:contingent_right`, FB-024: a merger whose terms note a contingent value right, a warrant or
  another contingent payment beside the package, flagged `contingent_right_unvalued` by stage 8; the row keeps its
  terms and its `dlret`, which is the value of the valued part, and a `--merger-terms` row takes no such doubt).
  Ruling G (upstream feedback) adds `no_history`,
  `history_after_last_trade`, `exchange_without_successor` and `kind_by_filing_history_only`; FB-027 adds
  `handoff_unchecked:<successor>` (a merger left standing against a handoff found by timing whose successor has
  no issuer, so no filing of the successor's could be looked for; with a known issuer and no successor
  registration found, the row keeps its verdict); and two security
  reasons, `issuer_unresolved` (FB-006: an observed security with a FIGI and no issuer CIK) and
  `open_under_bankruptcy_ticker` (FB-014: an observed security open under a five-letter ticker ending in Q). A seed whose
  only problem is its security is counted, not listed. Pipeline stages 10e
  (ticker evidence: about one cached EDGAR search per placeholder without a
  ticker tier), 10f (verdicts), 10g (the contract) and 10h (scorecard) run
  before the write, each over a run snapshot of the rows about to be written (`RunSnapshot.of`, carrying stage 9g's
  readings, which run_manifest.json records, doubts included); `uncertain.csv` is written with the other tables. The
  verdict never reads the truth files: `output/disputes.csv` (`measurement/disputes.py`, stage 10h, written with the
  tables in `store.TABLES`' one group because the pipeline has its rows in memory by then; `run_manifest.json`'s
  `disputes` is its count) lists what they dispute, one row per failing checked field of a golden, audit or diagnosis
  case (`sec_id,last_trade_date,truth_file,case,field,truth,library`, header-only when none, a `--limit` run too;
  scripts/scorecard.py --write rewrites it); nothing in measurement reads it back. An
  ending that is not its security's last real ending is uncertain
  (`earlier_ending:<the last one's delist_date>`). The scorecard's V lines
  read it; a committed output without it has no V lines. The scorecard's
  R2.4 lines still count assumed par by `dlret_method`, not by exit kind and
  fill, because assumed par also falls on unknown and expiration endings.

## The contract is written beside today's tables for one release (decision 6)

- **The contract is written beside today's tables for one release (decision 6).** Stage 10g writes
  `output/contract/{security_history,delistings,seeds,price_requests,id_changes,payout_legs}.csv` from the tables about to be
  written and the verdicts; the scorecard (10h) reads the issuer from `contract/security_history.csv`. Contract
  delistings hold one row per ended security, its last real ending; `last_trade_date` is the day the library holds
  for it, whatever its source (`exit_kind.published`; FB-019 and FB-020, which replaced decision 12's "blank when
  uncertain"), so it is the day the security's history ends on, and it is blank only when no source dates the
  ending. A day no exchange print gave is never the first day of the security that took the ticker, nor later
  (FB-022, `last_trade.before_successor`): a fails row is dated a trading day after the close it carries, so an old
  security's last row falls on its successor's first day, and that first day is read from the successor's own
  unassigned-symbol row (`history._first_days`). A row that keeps its value and is moved this way after stages 7
  and 8 ran has its close and its value read again on the day it now carries (`pipeline._read_again`), so its
  price requests and the caller's answers to them are keyed by one day. A day that is not a confirmed exchange print no later than the Form 25 effective date
  (`exit_kind.LastTrade.print_confirmed`; architecture step 4's ruling) makes the ending `uncertain`, with the
  failing part as its reason in `uncertain.csv`; a continuation's verdict does not judge its day. The price date and
  the price requests follow the published date; a continuation has no value and publishes no cash (cash paid to
  the old security's holders at the step is a dividend of the price series, dated on the successor's first day:
  FB-021); assumed par, Shumway marks and a transfer's 0.0 are `dlret_fill`. `--price-answers` (the requests plus a `price` column) feeds the closes and
  acquirer prices, so a second run changes values only: each stage reads the answer to its own request
  (`price_requests.PriceAnswers`; stage 7 a last close, stage 8 a stock leg's received close, stage 10a an OTC print
  or a plan's new-line close), and `pipeline.Overrides` holds only the caller's own files. What decides an identity,
  a kind or a request never reads an answer: stage 7 hands stage 8 the run's own closes beside the answered ones
  (`pipeline._Closes`), and stage 8's acquirer, requests and decisions rest on them alone. A price that is not a finite positive
  number, an answer to no request, or a last close also given by `--last-trade-closes`, exits 2 before anything is
  written. Today's seven tables keep their columns.

## Every output is written only after the whole run succeeds

- **Every output is written only after the whole run succeeds.**
  `pipeline.run()` computes every table in memory first and writes all seven
  and the six contract files (same group) only at the end (`store.write_tables`): each table is formatted and written
  to its own temp file first, and only then are the temp files renamed over
  the old tables. So a refusal, a bad override CSV or any failure before the
  renames leaves every previous table as it was. The renames themselves run
  one file at a time (`atomic_io.replace_all_on_success`), so a run killed
  between two renames can leave some tables new and the rest old; each
  single table is always whole.

## `sec_id` is a US composite FIGI, or a placeholder

- **`sec_id` is a US composite FIGI, or a placeholder.** When no FIGI can be
  confirmed it is `CIK<cik>-<CLASS>` (`identifiers.placeholder_id`) —
  still a stable, joinable key, just not a real FIGI. A placeholder holds one line: an issuer and class with more
  than one placeholder line (CUSIPs trading on the same days, no switch between them) name each
  `CIK<cik>-<CLASS>-<first CUSIP>` and the unsuffixed id is unused (`security_master.split_placeholder_lines`). `identity/figi_resolution.py`
  never accepts a candidate on Bloomberg's current name alone: a dead line
  gets renamed to its acquirer, so acceptance needs a CUSIP match, or a
  ticker+name match against the observation name or, failing that, the
  issuer's EDGAR names (current and former; `FigiResolver` drops such a match
  when another era's pin or CUSIP contradicts it, or when it would leave a
  same-class sibling era alone on the issuer's placeholder). The spec's third
  route, an acquirer/successor name match, is not built (spec §17). A pick is also withdrawn (FB-003, Fox 2019)
  when the ticker's holder today had not filed anything by the era's first sighting, is another company than the
  era's issuer and is no 8-K12B/8-K12G3 successor registration (`weak_eras_before_registrant`): the 2013 to 2019
  sightings of FOXA are Twenty-First Century Fox's, not Fox Corporation's FIGI (whose first filing is of 2018-10-09).
  A CUSIP change is not one line when another registrant replaced the class (`identity._Replaced`: the old
  registrant's Form 25 and closing 8-K, the new one registered by a Form 10, a spin-off, and filing no 8-K12B/8-K12G3): the
  old line ends there, with its own Form 25, and the new FIGI starts at its own CUSIP with the new issuer only. A
  one-for-one reorganization (Merck 2009, Clearwire 2008, Express Scripts 2012, Disney 2019) stays one security with its issuer
  change.

## A delisting is a Form 25 removal — not a rename, not a secondary withdrawal

- **A delisting is a Form 25 removal — not a rename, not a secondary
  withdrawal.** A rename or an exchange move that keeps the security trading
  is not a delisting; withdrawing a secondary/regional listing while the main
  one continues (Apache/Chicago 2020) creates no row (`filings/listing_status.py`). A
  security can have more than one delisting (an exchange transfer, later a
  merger).

## A Form 25 is reached, matched and owns its row (sub-plan 5b)

- **A Form 25 is reached, matched and owns its row (sub-plan 5b).** A security goes on after a Form 25 only when it
  is listed today, when the issuer moved the class itself (its own Form 25 with an 8-A12B within 10 days), or, for
  a Form 25 not under rule 12d2-2(b), when its own CUSIPs keep trading (`ftd.trades_after`): never on an
  observation alone (a stale snapshot), never on the OTC tail after a removal under (b). A security gone today also
  takes the latest Form 25 group of the year before its first sighting, and a Form 25 after its alive window when
  its own CUSIP traded within 30 days before it; the one other CIK in force over its whole span is searched too. A
  Form 25 solely about rights or about another tracking group is not the common's. A Form 25 its text leaves between
  siblings is the one that stops trading at it, never one picked by order (FB-004); a group the security traded on
  past with no exchange on the next annual cover is a move to the OTC market (520), not a transfer. The matched Form 25's notice
  outranks the continued-filings default when it says the class was acquired, and a later SEC revocation never
  decides its row.

## An ending's kind and successor change after the finder built it only by a rewrite (`endings/rewrites.py`)

- **An ending's kind and successor change after the finder built it only by a rewrite (`endings/rewrites.py`).** Each names
  its rule and is recorded typed on the delisting (`Delisting.rewrites`; never a column). A continuation carries no
  `no_evidence_default`, no `successor_unknown`, no payout or terms-gate flag and no payout read: a merger the handoff
  stage or R1 makes a continuation loses its merger value (`MergerValues.drop`: delistings.csv's payout, acquirer and
  raw payout columns go blank). A security that goes on (its own successor) keeps
  its kind and value. The clip check's marking (`rewrites.mark_going_on`) runs once, as stage 9b's first step.

## An ending's kind follows the registrant's role and R1 (sub-plan 5c)

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
  target name, or a target name agrees, `names.names_agree`, with one of its EDGAR names) is one function,
  `own_shares.names_target`, read by `successors.successor_by_terms` (stage 9's terms link and 8b's in-run link), by
  8b's 8-K12B candidate (`_r1_successor`), by stage 9g's confirming filing and, as a registrant of that name first
  filed at most 1,095 days before or the registrant's own name, by stage 5's R1 (`OwnShares.target_issuer`); the
  same-CIK own-registration link and the same-issuer class link need none. Every one of these reads the ending's one
  own-share reading (`own_shares`), of the security's FIGI share class, at the ending's anchor. A second leg after
  the first share (more shares, rights, warrants, units or a CVR) is no one-for-one.

## A line is followed past its observations (sub-plan 5a, rulings R1 and R2)

- **A line is followed past its observations (sub-plan 5a, rulings R1 and R2).** Stage 4b follows each security
  across a reverse split or a rename the fails rows show after the caller's last observation, before the Form 25
  search (a line with no step reads its issuer's 8-K text for a new ticker or CUSIP, in the first round and again for a line
  that moved and then stopped, once per line end: RRI to RRI Energy to GenOn): so a later real ending is found instead of a guess anchored on the old ticker's last row. A step needs a
  filing that states it (an 8-K 5.03/3.03, an own 8-K12B/12G3, an EDGAR rename, or 8-K text) and an old registrant
  that carries on (a periodic report, an operating company's or a registered investment company's, for a period after the step, or its own 8-K12B; listed today for a step
  within 120 days of the run date; no other CIK's 8-K12B/12G3 naming it). R2 decides identity: the same composite
  or none is one security; a placeholder folds into the FIGI line its new CUSIP names (contract/id_changes.csv
  names it); another composite is a line successor, linked by stage 9 as a continuation (an `unknown` row at the
  switch is rewritten, `line_continuation`: it drops `no_evidence_default` and gets medium confidence); so is a merger row at the switch when stage 4b followed the step (the old registrant carries on: TEAM, LSXMA, FWONA), unless its payout reconciled with the last close.
  A held pick is not always the end (FB-003, News Corp 2013): when the own-ticker switch's CUSIP is another
  issuer's security's and its rows do not name the issuer, while the issuer was renamed and a free switch's rows
  (an 8-K or the renamed-CUSIP scan names it) name its EDGAR name in force, that switch is the issuer's own next
  line, corroborated and decided as any step (NWS-A to Twenty-First Century Fox's FOXA on 90130A101, which has no
  composite: the placeholder carries on, folding into the issuer's other placeholder that holds the CUSIP). Of
  several, the one that began the day the held pick did.
  A step may begin after the window (FB-015): the fails files hold a row only on a day with a fail, so a quiet
  stock's new CUSIP can first appear years after the old one's last row (Ocwen: 2020-08-12, then 2023-07-14). A line
  whose FIGI its own CUSIP or a pin confirms, and that the round found no step for, takes the first later CUSIP
  under its own ticker when OpenFIGI names the line's own composite for it and the registrant carried on, and the
  same CUSIP under a ticker EDGAR lists for the issuer (ONIT). Such a late step needs no filing near its first row,
  a bankruptcy or an ended listing anywhere in the gap refuses it, and one that is not confirmed is dropped with no
  review item.
  The search for another registrant's 8-K12B/8-K12G3 is of a phrase, and SEC's name list shortens a name the
  filing writes out. So it is asked under the issuer's EDGAR name on the step's day and then under each of the
  line's own names that has other words (`line_follow.registrant_names`, FB-026: on a seed list Noble's Cayman
  line, seen in 2008 only, kept the Swiss company's CUSIP of 2009 as its own, because "NOBLE CORP" does not find
  the 8-K12G3 that names "Noble Corporation"; under the observed name it is found, the step is refused, and the
  line ends on 2009-03-26 as on every sighting). The first name that finds a registrant answers; a search that
  failed under one name is no answer unless another name finds one.
  A step stage 4b refuses because another registrant took over (`merged_out`, `other_registrant`), or whose new rows do
  not name the issuer's name after the step (`name`) but name the old line's, is a line of the run when it follows an
  era of the same ticker and its CUSIP is not the ticker's next era's: the identity stage keeps those fails rows as an
  era with one derived observation (`Observation.derived`), named by its fails description, looked up under it and its
  CUSIP, `observed=false`, in no echo table. A chain is followed up to `MAX_DERIVE_ROUNDS` rounds.
  A derived era knows the step it came from (`TickerEra.derived_from`) and `identify` checks it against that step
  after stage 3. It joins the security its step was refused from only when the price carried over across the step (rule
  J: the new CUSIP's first fails price within `CARRIED_PRICE`, 2/3 to 3/2, of the old CUSIP's last, or either missing;
  a continuation is "same holders, same claim, one for one": Uniti 2025 is 1.65, a merger at 0.6029 share per share);
  otherwise the era is not made and the step stays refused. An era from a `merged_out` step never takes the old
  line's issuer under a composite of its own, the origin's and the era's both FIGIs (a placeholder id is no second
  composite; the fold decides, Thornburg Mortgage 2008) (rule X: stage 4b found that issuer files no periodic report after the
  step): it is asked again with that issuer excluded from every resolver tier, and what that answers stands, another
  issuer or none. A `other_registrant` or `name` step keeps the origin's issuer (CHTR 2016). The verdicts
  (`not_made`, `without_old_issuer`) go from round to round (`Identity.verdicts`); the lookup that excludes a CIK has a
  memo key of its own. `CARRIED_PRICE` is defined once, in `identity/carried_price.py`, and the handoff stage's
  continuation by timing across two issuers reads the same band.

## `ticker_history` is clipped only at the delisting that actually ends the security

- **`ticker_history` (the in-memory history, never written: contract/security_history.csv is published from it) is clipped
  only at the delisting that actually ends the
  security** (`history.Histories`, the one module for where a history ends). One whose successor is the security
  itself (a continuing
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
  not that listing continuing (RHD, Smurfit-Stone, Idearc, GGP). The one exception is a security listed today
  whose CUSIP of the ending trades on under its own tickers: it returned, and the ending goes on as the security
  itself (GTX, relisted in 2021 on the CUSIP its Chapter 11 left in place; FB-001). An
  *unconfirmed* last-trade day (the no-Form-25 "continued 10-K/Q filings"
  fallback substitutes the security's own last sighting when it has no
  last-trade evidence at all) is too weak a guess to second-guess against
  fails evidence either — Monster Worldwide and SunPower traded normally for
  years after such a guess; the guess, not the listing, was wrong. A worked-out
  closing day (sub-plan 5d rule 4, source `closing_day`) is unconfirmed too: it
  clips the ranges at that day, before the Form 25's effective date, and is
  never second-guessed nor published. A security
  none of whose delistings ends it, and that isn't listed today either, is
  left unclipped, ending at its last real sighting - unless that sighting is a fails row at the fails data's last day
  (`Histories._at_data_edge`, FB-004; a row at the edge under a CUSIP no security of the run holds whose description
  names the security counts too, `history.unheld_trading_days`: XOM 2026): then it is still trading and its history stays open. A security whose ending
  went on as itself and whose old registrant a new one replaced (`endings/registrants.py`) is listed through the
  new registrant, and the contract names it as the issuer in force from its registration.
  A continuation leaves no trading day between its two histories (FB-029, `Histories.handoff_start`): a
  successor with no history on or before the predecessor's last day starts on the trading day after it, under the
  ticker and the CUSIP it is first seen with, when that first sighting comes within 10 trading days
  (`HANDOFF_START_TRADING_DAYS`). The successor's start moves and the predecessor's end, its last trade date,
  stays. A successor first seen later keeps its own start: across a longer gap nothing says which ticker it
  traded under. Exxon Mobil 2026: the old line ends on 2026-06-30, the holding company's CUSIP has its first
  fails row on 2026-07-02, and its history starts on 2026-07-01. When the successor takes a ticker another
  security of the run still holds on that day, that security keeps it only if it is sighted under it on or after
  the successor's own first sighting; otherwise its range under the ticker ends the day before the handoff and
  its next range starts on the handoff day, so no ticker is shared and no day is left out (Ingersoll Rand and
  Trane, 2020-03-02: IR passes to the former Gardner Denver and Trane is TT from that day, where its last IR
  fails row is dated 2020-03-02 and its first TT row 2020-03-03).
  A successor's ticker is not its predecessor's (`Histories._successor_starts`, one map shared by the clip check,
  the ranges and the listed answer): when a delisting's successor is another security X that holds ticker T from day F (X's first
  sighting under T on or after the delisting's confirmed last trade day, or from 30 days before its delist date
  when the day is unconfirmed or missing, and never more than 120 days after that anchor: a later one is a
  recycled ticker, no F; computed again from the final delistings after the handoff stage, which creates
  continuation rows, and a security with an ending whose ticker a successor took is not listed today, whatever its
  issuer's EDGAR listing says: AON 2012), the
  security's fails rows and sightings under T from F on are X's. They do not count as it continuing
  (`Histories._continues_after`: AON 2012), and its T range (and old-CUSIP range) ends the day before F (STX 2021,
  CRC 2016, ODP 2020).

## `observation_map.csv` is the caller's join surface, not a review table

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
  comes from this table, a ticker look-up by date from contract/security_history.csv keyed
  on `history_ticker`, not the raw observed ticker. A derived era's observation is no row of it.

## Tests are fully offline

- **Tests are fully offline.** They use a `FakeEdgar` fixture (`tests/conftest.py`)
  and committed text fixtures (`tests/fixtures/`); every new client (OpenFIGI,
  FTD, MIDAS, Nasdaq halts) has its own fake or fixture-backed double; never
  add network to the test path. A double is an adapter of the `pipeline.Clients` seam: it gives its client's
  required reads (`capabilities`' docstring lists them) and states each optional capability, offered (backed by
  its fixture) or absent, never silent (`capabilities.Undeclared` refuses that). `_FakeEdgar` and the real-case
  harnesses' EDGAR doubles state full-text search absent (`full_text_search = None`: their fixtures recorded no
  searches; a test that wants one sets it, and tests/test_line_follow_cases.py's double answers from its recorded
  searches); every LLM extractor double takes `security_name`, every LLM client double states `model`, and every
  resolver double passed to `Clients` its `issuers`. Golden fixtures are regenerated out-of-band by
  `scripts/regen_payout_fixtures.py`.

## Ticker recycling

- **Ticker recycling** (e.g. ALTR was Altera then Altair) is handled by
  `observations.split_eras` (a new era per security, on a name mismatch, a
  pin change, or an unconfirmed gap) and by `MANUAL_OVERRIDES` in
  `scripts/classify_universe.py` (~45 ambiguous short tickers). When web
  verification proves a wrong CIK, extend that dict — don't patch the resolver.

## Payout extraction is cash-only; the DLRET table supports full consideration

- **Payout extraction is cash-only; the DLRET table supports full consideration.** Auto-extraction from EDGAR remains cash-only. The DLRET table abstains (neutral mark) only when no consideration terms are supplied; when stock-leg terms (`stock_ratio`, `acquirer_price`) are provided via `--merger-terms`, it computes the full cash+stock consideration (e.g. AET→CVS: $145 cash + 0.8378 CVS @ $80 = $212.02, DLRET = +11.6%). The `--last-trade-closes`, `--recoveries`, and `--merger-terms` CSVs are keyed by `sec_id` and accept an optional `delist_date` column for per-event overrides (blank/absent = applies to all delistings of that security); a row matching no delisting stops the run.

## The LLM endpoint is the one `.env` names: OpenAI or Anthropic

- **The LLM endpoint is the one `.env` names: OpenAI or Anthropic.**
  `llm_client.OpenAIJsonClient` speaks the OpenAI chat-completions API and
  reads `OPENAI_API_KEY`, `OPENAI_BASE_URL` (unset means OpenAI) and
  `CHAT_MODEL`. For Claude it uses Anthropic's OpenAI-compatible endpoint:
  the Anthropic key goes under `OPENAI_API_KEY`,
  `OPENAI_BASE_URL=https://api.anthropic.com/v1/`,
  `CHAT_MODEL=claude-sonnet-5-5`; `ANTHROPIC_API_KEY` is never read. That
  endpoint answers 400 to a `temperature` (seen on `claude-sonnet-5-5`) and to
  `response_format` type `json_object`, so a model whose name contains
  `claude` is sent no temperature, and its first request, the `json_schema`
  one, is the one that answers. The cache file name
  (`cache/llm/<accession>_<model>_v3_<ticker>.json`; the earlier prompt's
  cache-only reading, `LEGACY_VERSION`, `<accession>_<model>_<version>.json`)
  carries the model the client calls (`OpenAIJsonClient.model`: `--llm-model`,
  else `CHAT_MODEL`), so a new model sends every merger filing again; rerun the
  10-deal eval for it (10/10 on `claude-sonnet-5-5`, 2026-10-07, with main's
  prompt v2; not yet rerun on v3). An
  agent-sandbox run must allow the host in `OPENAI_BASE_URL`
  (`api.anthropic.com` or `api.openai.com`): a blocked LLM host raises on
  every call, each becomes a miss, and the run exits 0 with those mergers'
  terms missing. The calls run on `--llm-workers` threads before the sequential
  pass reads their answer files. Those threads also read an uncached candidate
  filing's text from EDGAR, so up to that many SEC requests can be in flight,
  inside the 8 requests/s limit. An LLM call in flight is not cancelled by an
  abort or Ctrl-C: the run waits for it (the client sets no timeout).

## The resolver cache is versioned

- **The resolver cache is versioned.** `cache/ticker_resolution.json` carries
  `{"__version__": 4, ...}`, each answer keyed `TICKER|date|observed name`
  (versions 2 and 3, keyed `TICKER|date`, load re-keyed from their stored
  `member_name`; an older file is ignored, not trusted, and replaced on the
  next save) and never holds a miss, a second-pass or 2b (`identity.EraIssuers`) answer, or
  an answer that rested on a failed request or a stale copy. An answer found with an issuer excluded (rule X of the
  derived eras) is saved under its own key, the usual key followed by `|!<cik>`, so a lookup without the exclusion
  never reads it, and the cache's `__version__` did not change. The pipeline
  writes it after each resolving stage and on the way out of a run. A remembered `name_search` answer stands only
  while it agrees with the name tier's first rule (`TickerResolver._still_named`, FB-004: with the name index, the one
  active holder of exactly the expected name, `_exact_holder`, is the company): one the retired live company search
  remembered against it is resolved again (Realogy Holdings Corp. kept CIK 1355001, the LLC, over 1398987, the
  listed Anywhere Real Estate Inc.). Of several active holders that carried the name in the years before the date,
  `_exact_holder` takes the one that carried it within 30 days of it (`_one_filer`'s narrowing: Alberto-Culver, ACV
  2010, is the 2006 spin-off, CIK 1368457, not the old registrant renamed New Alberto-Culver LLC, 3327). With no
  index the remembered answer stands. With no exact holder or several it stands while it agrees with the tier's
  ranking rule (FB-026): an answer whose company EDGAR does not name with exactly the expected name's words is
  resolved again when the tier's answer today is a company it does name so (`BG|2009-02-19|BUNGE LIMITED`, kept
  as Bunge Limited Finance Corp, 1230396, becomes Bunge Ltd, 1144519). The tier's answer today is the one
  `resolve` would take: the first candidate in rank that existed by the era's first sighting and passes the tier's
  check (`_accepts`), so an answer the tier's last resort gave (DuPont 2017) stands. A remembered weak full-text
  answer (`efts_name_mismatch` from the search's second pass, a filer named without the ticker) stands until the
  name tier has a company that may replace it (`_may_replace`: its own Form 25 or 15 within 90 days of the date,
  or a delisted company of exactly the expected name, `_delisted_under_the_name`; FB-026:
  `TRI|2009-07-02|TRIAD HOSPITALS INC`, kept as TRI-S Security Corp, becomes Triad Hospitals, 1074771). So a
  change to either rule takes effect on a warm cache with no new `__version__`. The recheck searches nothing: it
  reads the name index and the issuers' copies, and an issuer it has not read before is one request, once. On the
  consumer's seed list it reads the tier's ranking for 107 of the 1,404 kept name-search answers (the others are
  a company of exactly the name's words) and resolves two again, both Bunge's. The older rule of the exact holder
  (FB-004) resolves a few answers again at every run, and each gets the answer it had (Aaron's Holdings 2020,
  Ferguson 2024, NorthStar Asset Management 2017, Pulte Homes 2010).

## A merger payout is gated; `delistings.csv` carries both the gated and the raw read

- **A merger payout is gated; `delistings.csv` carries both the gated and the raw read.** Every merger payout is
  checked against the last trade close (`payout_gate.reconcile`) before it reaches `delistings.csv`'s
  `payout_per_share` / `payout_source`; the same file keeps the raw, unchecked extraction in its
  `raw_payout_per_share` / `raw_payout_source` / `raw_payout_confidence` columns, and the contract carries the payout
  rule. There is no separate payouts table (removed 2026-10: nothing read it), and the filing a payout was read from
  (its accession) is not published: filing ids stay inside the library, and a new `delistings.csv` column would make
  `run_snapshot` refuse every older commit's file. An election whose cash and stock legs together reconcile,
  when neither does alone, is its default package (`llm_election_package`, sub-plan 5e); either-or legs are never
  summed.
- **A closing dividend declared before the closing 8-K is looked for only where the value is short (FB-023).**
  After a gate pass, a merger whose kept value is more than 1% under its last close, with no dividend read and no
  caller's terms, has its target's 8-Ks of the 60 days before the delisting asked the dividend question
  (`LLMMergerTermsExtractor.earlier_dividend`, `merger_value._EarlierDividends`; Plains Exploration 2013). A
  dividend counts only when it is less than twice the gap between the value and the close, so a merger not asked
  can be short by less than 2% of its close. What is read joins the run's dividends before the gate runs again,
  and every later pass decides on its own closes whether it counts. A merger only the caller's answers value (its
  stock leg, its close) is asked after the answered pass, so the first pass is the same in both runs. A filing that
  names a closing dividend and states no amount per share gives nothing to count (`ClosingDividend.amount` None);
  when no search finds the amount and the last pass values the merger more than 1% under its close, the row is
  flagged `closing_dividend_unstated` and is `uncertain` with `value_incomplete:closing_dividend`, its terms and
  `dlret` kept (Two Harbors 2026). A dividend whose quoted record date follows the merger is the acquirer's and
  is dropped when the answer is read, with or without an amount, so it puts no doubt on the row on any pass
  (Athene 2022: "a record date and payment date following the completion of the Mergers").
- **A closing dividend is read apart from the package and counts in the value only (FB-021).** It is cash the
  target paid its holders because the deal closed (Extended Stay 2021: $1.75 a share beside the merger's $18.75).
  `LLMMergerTermsExtractor.closing_dividend` reads it with a question of its own, for a merger either reader gave
  terms for, from a closing filing whose text names a dividend with a dollar amount. The filings state a record
  date and a payment date and no ex-date, so the last close decides: the dividend counts when the consideration
  with it is nearer the last close than the consideration alone (`payout_gate._counted`), and the gate then checks
  that total as it checks every value. When the consideration alone is nearer, the stock had gone ex-dividend, the
  price series carries the payment, and it does not count (USG 2019). The decision is made on the closes each gate
  pass reads, so a caller's answered close can change it, as it can change any value. A counted dividend is added
  only to the table's cash (`MergerValues.table_terms`): `payout_per_share` and the contract's `cash_per_share`
  are all the cash one share received, `raw_payout_per_share` stays the regex read, and `value_formula` names the
  parts (`(18.75 + 1.75 dividend) / last_close − 1`). What the run's decisions read (`read_terms`, `reconciled`)
  is the package without it, so the operator ruling of 2026-10-04 (a special dividend is never consideration)
  still decides an ending's kind, and a continuation publishes no cash (Kraft 2015, Baker Hughes 2017). A
  `--merger-terms` row takes no dividend: the caller states all the cash. No prompt version changed and no merger
  is read again; the question's answers are cached under `{accession}_{model}_div1_{ticker}`.

## The golden set is the regression gate

- **The golden set is the regression gate.** `tests/fixtures/golden/` (31
  cases, from `data/golden_events.csv`) replays real EDGAR responses
  offline; every case must stay green. `scripts/build_golden_fixtures.py`
  rebuilds it after a live-data change.

## Validation is the review loop and the scorecard

- **Validation is the review loop and the scorecard**, not eyeballing: start
  from `output/review_summary.csv`, work `review.csv` top down, record each
  accepted row in `data/review_decisions.csv`, then re-run
  `classify_universe.py`, then `python scripts/scorecard.py --check` (exit 1
  on a drop or a failing golden or diagnosis `pass` case). To confirm one row
  against an independent path, curl the accession it cites. Drill mismatches
  to root cause and re-run.

## Configurable input paths

- **Configurable input paths.** `classify_universe.py` requires
  `--observations` (a CSV of `ticker, as_of[, name, cusip, cik, sec_id]`,
  built by `observations_from_snapshots.py` / `observations_from_instruments.py`
  or hand-supplied) and reads `--output-dir`/`--cache-dir` with repo-local
  defaults; it writes eight tables to `output/` (disputes.csv among them) and the six contract files to
  `output/contract/` in the same group, all committed artifacts.

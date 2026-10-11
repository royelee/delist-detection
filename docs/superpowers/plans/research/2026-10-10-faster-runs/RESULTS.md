# Results: faster runs (measured 2026-10-10)

Two code bases. The numbers below the first heading were measured at `6e43e09`. The six changes were then rebased onto `c77365a`
(head of `worktree-reset-1-scorecard`; diffs in `changes-c77365a/`, which apply in order to the untouched `c77365a` tree); what could and could not be
measured there is in "At `c77365a`" below. Every figure is labelled with its commit.

**"Warm" means no SEC request and no LLM call. It does not mean offline:** `listing_status.listed_today` calls `figi.map(..., use_cache=False)`,
so every full run asks OpenFIGI for listing status even on a warm cache. `api.openfigi.com` must be reachable (without it the run exits 4), and every
time here includes those calls.

Code at `6e43e09` (copy in `tree/`, six commits on top of a baseline commit). Full input `data/observations.csv`, `--as-of 2026-09-25
--sec-workers 1 --extract-merger-terms-llm`, one run at a time on one machine. Times are wall seconds of the whole process
(`timeit.py`); memory is the process's peak resident set (`ru_maxrss`). Every run below used a fresh copy of `cache-full`
(or of `cache-built`: `cache-full` plus the parsed fails files from the first run of change 1). "Warm" means no SEC request and no LLM call.

<!-- table -->
| # | Change | Warm full run, before → after | Peak memory, before → after | Tables byte-identical to `out-full` |
| --- | --- | --- | --- | --- |
| 0 | Untouched code (reference, run twice) | 533.2 s and 521.9 s | 5,516 MB | yes (`contract/` and `scorecard.json` included) |
| 1 | Parse each fails ZIP once into a SQLite file (`ftd_store.py`) | 521.9 s → 310.4 s (first run, which builds the store: 334.8 s) | 5,516 → 5,484 MB | yes |
| 2 | `normalize_ticker`, `parse_day` fast paths | 310.4 s → 302.6 s | 5,484 → 5,572 MB (no change; noise) | yes |
| 3 | `recent_filings`: no default list per row | 302.6 s → 176.0 s | 5,572 → 5,503 MB | yes |
| 4 | `--llm-workers` (LLM calls on their own threads) | 176.0 s → 173.9 s warm (no call to make); LLM-bound run: see target 1 | 5,503 → 5,520 MB | yes |
| 5 | Bisect slices; `is_backfilled` window; `split_search` without copy | 173.9 s → 146.9 s | 5,520 → 5,450 MB | yes |
| 6 | `FtdRow` slots, texts held once | 146.9 s → 131.0 s | 5,450 → 4,101 MB | yes |
| – | Final tree (all six, rebuilt commit order), first run on fresh `cache-full` | 173.8 s (builds the store) | 4,058 MB | yes |
| – | Final tree, warm, `--sec-workers 1` | **131.3 s** | 4,073 MB | yes |
| – | Final tree, warm, `--sec-workers 4` | 169.2 s | 4,146 MB | yes (manifest: `sec_workers` 1 → 4 only) |
| c77 | `c77365a` untouched, offline except OpenFIGI, on a copy of the PR #7 worktree's cache | **not a valid reference** (see below); 1,160.5 s with ~150 failed SEC requests and their retries | 5,551 MB | no reference |
| c77 | `c77365a` + six changes | **not run** (Task C stopped: no valid reference) | – | – |
<!-- /table -->

Manifest rule: in every run `run_manifest.json` differed from the reference only in `code_version` (the reference says `unknown`),
the `cache_answers.*` counters, the `latency_ms.*` and `sec_requests.*` request counters and the per-stage `edgar_requests`
(the reference run made one `archives` request, the reruns none), and `sec_workers` when it was given another value. No other field.

The test suite: the untouched tree gives 3,522 passed, 45 xfailed (`PYTHONPATH=src python -m pytest -q -o addopts=""`);
the final tree gives 3,592 passed, 45 xfailed (70 new tests).

## Targets

**1. A run that makes all 769 LLM calls in under 10 minutes: met (measured, stand-in client).**
The stand-in client sleeps 2.7 s per call and answers with the cached answer of the same file, `--sec-workers 1`, the 769 sonnet answers removed from the cache copy:

| `--llm-workers` | wall time | calls made | most in flight | tables | the 769 answer files |
| --- | --- | --- | --- | --- | --- |
| 1 (the old behaviour, estimated, not run) | about 131 s + 769 × 2.7 s = about 35 min (the real run: 42 m 42 s) | 769 | 1 | – | – |
| 8 (recommended, the new default) | 392.6 s (c6) and 398.2 s (final tree) = 6 m 38 s | 769 | 8 | identical | byte-equal |
| 16 | 262.2 s | 769 | 16 | identical | byte-equal |

Recommended: 8 (the default). 16 saves two more minutes if the endpoint allows it (below). The remainder (about 131 s) is the warm run.

Live check (real client, `api.anthropic.com`, `claude-sonnet-5-5`; 20 of the 769 answer files deleted from a cache copy, `--llm-workers 8`, run on commit 6 of 6):
20 `chat.completions` calls, at most 8 in flight at once, 20 of 20 HTTP 200, no 429, no SDK retry, no exception; call latency 1.7 s minimum,
2.9 s median, 5.6 s maximum. All 20 answer files came back. Tables identical to the reference. 12 of the 20 files are byte-equal to the earlier
answers; 8 differ in wording only (the model is not deterministic: for example `acquirer_ticker` "FCE.A" for "FCEA", a punctuation change in a note), and none changed a table.
Not tested live: more than 8 workers (so the endpoint's limit at 16 or 32 is unknown; the account's rate limit was not reached at 8).

**2. A truly warm full run: 131 s (2 m 11 s), under 4 minutes: met (measured).** From 522 s; the documented 2 m 47 s was measured on older code. The
first run on a cache without the parsed files takes 174 s (the store build adds about 43 s once). Peak memory 4,073 MB, down from 5,516 MB
(the documented 1.8 to 4.2 GB does not match this input at the baseline either). With `--sec-workers 4` the warm run takes 169 s: on a warm
cache the threads only add contention, as the documentation already says.

**3. A two-ticker run (rows NWA and DAL of the seeds file) takes a few seconds: met once the parsed files exist (measured).**
Untouched code 45.8 s and 46.3 s; final tree 3.8 s (output identical to the untouched code's). The first run on a cache with no parsed files builds them: 48.7 s.
That one-time cost is not "a few seconds"; a process pool over the ZIPs could cut it, but was not built (a first use on a real cache also downloads the ZIPs, which takes longer).

## What each saved, and what stayed

After change 6 the profile (cProfile, 176 s with its own overhead) has no single large item left: reading the 8.1 million rows the 76 asks return
(`ftd_store.select`, `FtdIndex._add`) about 40 s of that, JSON parsing of cached submissions about 9 s, `ranges_from_sightings` 13 s, `parse_day` 12 s,
`recent_filings` row building 16 s (the Python objects themselves). Each is a few percent of the run.

## Checks beyond the full run

- Real-ZIP equivalence (`ftd_equiv.py`): every one of the 436 ZIPs in the cache, the stored rows against `parse_ftd_lines`, unfiltered and
  under a filter of symbols and CUSIPs, prices included (NaN and the sign of zero): 28,235,581 rows compared, 0 mismatches.
- Thread safety: a warm run at `--sec-workers 4` gives identical tables.
- Kill safety: a cut-off build's temp file is removed by the next build (`test_a_build_cut_off_by_a_killed_process_is_cleaned_up_by_the_next_one`);
  a truncated store is detected and rebuilt (`test_a_cut_off_store_is_built_again`).

## Disk

The parsed files add 1.9 GB beside the 0.6 GB of ZIPs (436 files under `sec_data/ftd/parsed/`, gitignored with the rest of `cache/`).

## At `c77365a` (rebased; measured 2026-10-10)

**Diffs and suite (measured).** All six rebased diffs (`changes-c77365a/01..06`) apply in order to the untouched `c77365a` tree and reproduce the rebased
tree exactly (checked with `git apply`, then a byte comparison of the two diffs against `c77365a`). The head's own untouched suite: 3,717 passed, 44 xfailed.
With the six changes and their tests: 3,793 passed, 44 xfailed (76 new tests).

**Conflicts resolved.** `02`: only the end of `tests/test_identifiers.py` (an appended test). `04`: `classify_universe.py` and `pipeline.py` (the new
`id_baseline_history` argument beside the lines changed) and `llm_merger_extractor.py`, where the head's `_llm_extract` counts answers (`_lock`, `_asked`,
`_count`, `usage()` for `run_manifest.json`'s `merger_terms`). The per-file lock now wraps the head's whole read, ask, write and count: a thread that waited for the lock
and then reads the file another thread wrote counts it as the head counts any cache read (`asked` when this run asked for that file, else `from_cache`), and a warm
thread's reads are still not counted (`_count` skips them). Two new tests pin this: six sequential-pass threads on one file give one model call and `asked` 6;
six warm threads give one call and no count, and the sequential read afterwards counts `asked` 1.

**Task C: no valid reference at the head (measured).** The untouched `c77365a` tree was run on a copy of the PR #7 worktree's cache (the 769 `claude-sonnet-5-5`
answers are in it), full input, `--as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm`, `--id-baseline` the head's `output/securities.csv`, allowing
`api.openfigi.com` only. It was not a valid reference: exit 3, not 0, and the manifest shows what the cache did not hold:

| Missing | Count |
| --- | --- |
| SEC requests attempted (all refused by the sandbox) | 150: `archives` (filing texts) 141, `full_text_search` 9; by stage: delisting search 66, payouts 75, handoff search 3, ticker evidence 6 |
| `degraded_answers.failed_request` | 50 |
| Nasdaq halt-feed days not cached (`www.nasdaqtrader.com` was not allowed: only OpenFIGI was) | 25 degraded answers |
| `merger_terms` | `asked` 0, `failed` 15, `from_cache` 768 (15 calls to the LLM host were attempted and refused; the head's candidate filings need answers that are not in the cache) |
| `resolution_degraded` review rows | 38 |
| `warm_failed` | none |

So the head's cache is not warm for this input: 141 filing texts, 9 full-text searches, 25 halt days and 15 LLM answers are missing. The check stopped there
and no live request and no LLM call was made. The 1,160.5 s of that run includes the retries of those refused requests and is not a speed figure. No comparison of the
rebased tree's tables with a reference was possible, so **rule 1 (byte-identical output) is not shown at `c77365a`**. What carries over: the changes are the ones shown
byte-identical at `6e43e09`; the head's suite passes with them; the rebase conflicts were in the LLM answer counting, argument lists and one appended test.
To close it: warm the head's cache once with live SEC, Nasdaq halt-feed and LLM access (about 150 SEC requests, 25 halt days, 15 LLM answers), make the reference run with the
untouched tree, then run the rebased tree twice (first run builds the store). The head's `run_manifest.json` also needs the `merger_terms` check: `asked` 0, `failed` 0.

## Review notes folded in

1. `CikNameIndex.split_search` now loops `range(start, len(entries))` and reads by index (constant time to the first match; a micro-benchmark: slice 1.81 ms,
   `islice` 0.73 ms, index loop 0.002 ms per call at 1,000,000 entries). The equivalence test is unchanged. Not re-timed in a full run at either commit.
2. `--sec-workers 1` and the LLM threads: the `pipeline.run` docstring, the `--llm-workers` help text, the CLAUDE.md step in the plan and the plan's Task 4 now say the same thing:
   the LLM threads also read an uncached candidate filing's text from EDGAR, so up to `llm_workers` SEC requests can be in flight (the shared 8 requests/s limit holds);
   `--sec-workers 1 --llm-workers 1` is one SEC request at a time. No behaviour change.
3. One reader of a fails line: `ftd_store.split_line`, used by the store's build and by `ftd.parse_ftd_lines` (no import cycle: `ftd` already imports `ftd_store`). Store build time for
   30 zips, measured: 2.67 to 2.73 s before, 2.67 to 2.69 s after. The equivalence tests no longer use it as their own reference: `tests/test_ftd_store.py` keeps a whole copy of the
   original line rule and compares the store and `parse_ftd_lines` with it (the real-ZIP script `ftd_equiv.py` does the same).
4. "Warm" is defined above (and in the plan's harness section) as needing OpenFIGI.

## Independent check by the controller (2026-10-10)

Run separately from the agent's own measurements, on a tree rebuilt from the diffs.

| Check | Result |
| --- | --- |
| The six `changes-c77365a/` diffs on a clean `c77365a` | apply in order; suite 3,793 passed, 44 xfailed |
| `6e43e09` + the six changes as first written, warm full run | 134.4 s, 4,074 MB, 14 tables byte-identical, no SEC request, no LLM call |
| The same, plus review notes 1 and 3 (`ftd.py`, `ftd_store.py`, `cik_lookup.py` as rebased), warm | 128.2 s, 4,063 MB, tables byte-identical |
| The same, from a cache with no parsed files (the reworked store build runs) | 160.6 s, 4,060 MB, tables byte-identical, 1.9 GB of parsed files written |

The branch did not change `ftd.py`, `cik_lookup.py`, `atomic_io.py`, `edgar.py` or `evidence.py` between `6e43e09`
and `c77365a`, so these three files are the same at both commits once the changes are applied.

## At `799d1bc` (branch `faster-runs`)

Measured by the controller on 2026-10-10. Code: branch `faster-runs` at `f808b15` (all six changes). Reference: the untouched fork point `799d1bc`. Input: the full `data/observations.csv`, `--as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm`, one fixed `--id-baseline`. One machine; the runs of Steps 2 to 5 ran one at a time. "Warm" means no SEC request and no LLM call (OpenFIGI is still asked for listing status). Every run: exit 0, no SEC request, no degraded answer, no `resolution_degraded` row. Every figure is measured unless marked estimated.

Suite: 3,838 passed, 44 xfailed (62 s). The fork point gave 3,760 passed, 44 xfailed; the branch adds 78 tests.

The reference (untouched `799d1bc`, warm) took 658.6 s (10 m 59 s) with a peak memory of 5,528 MB. Other work (test runs of this plan) ran beside it, so its time is an upper figure.

The warm figure here (3 m 35 s) is higher than the 2 m 11 s the same changes gave at `6e43e09`, because the untouched code itself is slower at this commit (659 s here against 522 s there). The saving is the same kind: about a third of the untouched time.

### First run, then warm

| Run | Wall time | Peak memory | Tables against the reference |
| --- | --- | --- | --- |
| First run on a fresh copy of the reference cache (it builds the parsed store) | 246.8 s (4 m 07 s) | 4,088 MB | byte-identical |
| Warm run on the cache that run left, `--sec-workers 1` | 215.4 s (3 m 35 s) | 4,107 MB | byte-identical |

The first run costs about 31 s more than a warm run: the one-time build of the store. The manifest differs in no field outside the allowed ones (`code_version`, `cache_answers.*`, `latency_ms.*`, `sec_requests.*`, per-stage `edgar_requests` and `seconds`).

### `--sec-workers 4`, warm

251.1 s (4 m 11 s), 4,189 MB, tables byte-identical. The one manifest field that differs is `sec_workers` (1, 4). On a warm cache 4 workers are about 17% slower than 1: the threads have nothing to fetch and only add contention.

### Stand-in LLM runs

Every merger-terms answer is asked again; each call sleeps 2.7 s; no LLM call is paid for.

| `--llm-workers` | Wall time | Calls made | Most in flight | Tables | Answer files |
| --- | --- | --- | --- | --- | --- |
| 8 (the default) | 470.7 s (7 m 51 s) | 784 | 8 | byte-identical | 784 written, all byte-equal to the saved answers |
| 16 (the maximum) | 352.1 s (5 m 52 s) | 784 | 16 | byte-identical | 784 written, all byte-equal |

784 calls for 784 answer files: none was paid for twice. The run reads 785 answers (`merger_terms.asked` 785): two mergers read one file. One saved file, `000119312513440103_..._ICE.json`, is an answer this code no longer asks for. One call at a time would take about 215 s + 784 × 2.7 s = 2,332 s (39 minutes): estimated, not run.

### Two-ticker run (`DAL` and `NWA`, one observation each on 2008-01-16)

| Code | Cache | Wall time | Tables |
| --- | --- | --- | --- |
| untouched `799d1bc` | reference cache | 46.8 s | the comparison base |
| this branch | parsed store already built | 3.7 s | byte-identical to the untouched code's |
| this branch | no parsed store yet (the run builds all of it) | 51.8 s | byte-identical |

### Disk

The parsed store is 434 files, 1.9 GB, under `sec_data/ftd/parsed/`; the fails folder is 2.5 GB with it (0.6 GB of ZIPs).

### Earlier checks on this branch (each compared with the same reference)

- Task 1's commit `93f9c14`, first run on a fresh cache copy: tables byte-identical.
- The real-ZIP equivalence script on that cache: `rows compared 28235581 mismatching zips/filters 0`.
- The commit after Task 4, `09fb516`, warm: tables byte-identical.

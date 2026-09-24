# SEC Request Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut a full `classify_universe.py` run from ~7 h of cold issuer resolution and 17–70 min warm reruns to roughly 1–2.5 h cold and a few minutes for a same-week rerun at the default 4 threads. For the same caches and run date the output must not change by a byte, and the machine must stay under SEC's rate however many SEC clients it runs.

**Architecture:**
- **Cache evidence, never decisions.** EDGAR full-text-search (EFTS) answers and company-name-search answers are cached with the day they were fetched and a TTL, hits and empties alike. EFTS answers hold 7–365 days, scaled by how long after their date window they were fetched; company-search answers hold 7 days. The resolver never caches a miss: each run re-derives it, with the current code, from that cached evidence.
- **One rate limit for the machine.** Every SEC request from every thread goes through one in-process `RateLimiter`. It spaces request starts at least 1/8 s apart, carries a stop signal for prefetch workers, and holds a pause that every thread honours while SEC is failing. It also takes an `fcntl.flock`-guarded lock file outside the repo that holds the last start time, so every SEC client on the machine shares the 8 req/s.
- **Warm, then sequential.** Before each SEC-heavy stage, `prefetch.warm()` runs the stage's own per-item code on `--sec-workers` threads only to fill the caches, and throws the answers away. Warm threads only fill missing cache entries; they never refresh an existing one. The stage then runs one item at a time on the main thread, in its usual order, and reads exactly what a one-thread run reads.
- **Provenance.** The whole run uses one run date (`as_of`). `run_manifest.json` records it with the code version, the worker count, request counts, cache answers, latency and degraded answers. An era or security whose answer rested on a failed request or a stale copy gets a `resolution_degraded` review row, and the CLI exits 3.

**Tech Stack:** Python ≥ 3.10, `requests`, stdlib `threading` / `concurrent.futures` / `queue` / `fcntl` / `subprocess`, pytest (offline).

**Spec:** `docs/superpowers/feature-spec.md`, §9 (data sources and access rules) and §11 (non-functional). This revision answers the quant review `.superpowers/sdd/2026-09-23-security-master-and-delistings/sec-speed-plan-review.md`, with the controller's rulings on it. Task 15 amends §9 and adds §17 notes.

**Baseline:** HEAD `90be234` on branch `feat-sec-speed`. The offline suite passes there with 759 tests. Every `file:line` below refers to 90be234 unless a task says it refers to an earlier task's code; if the branch has moved, locate code by the quoted text.

## Global Constraints

- **Determinism** (spec §11, verbatim): "Same inputs and caches → byte-identical CSVs." This plan makes the run date an input: the same caches and the same `as_of` give byte-identical CSVs for any `--sec-workers`.
- **SEC fair access** (spec §11, verbatim): "≤ 8 req/s, descriptive User-Agent." The limit holds across every thread of the process and every process on the machine that shares the rate-lock file. The User-Agent comes from `edgar.resolve_user_agent()`.
- **Refusals** (spec §9, verbatim): "A SEC 403/429 raises `EdgarBlocked` and the CLI exits 2 (existing)." A refusal is never retried, and no thread starts another SEC request after one.
- **Misses** (spec §9, verbatim): "A miss is never cached as an answer." This still holds for resolver decisions. Search evidence (EFTS and company-search answers) may be cached with a TTL; Task 15 rewords §9 to say so.
- **No silent drop** (spec §11, verbatim): "No silent zero, no silent drop. Blank values carry a method/flag; every unresolved case appears in `review.csv`."
- **Runtime** (spec §11, verbatim): "A cold run on ~2,300 observed securities finishes overnight; a cached re-run in minutes."
- **Offline tests** (spec §11): "no network in `pytest`." Use fakes and injectable clocks and sleeps. A test may use real threads only when its outcome cannot depend on their interleaving.
- **Frozen rules** (constraints file): do not change `CrspBucket`, `DLST_CODE_TO_BUCKET`, the classifier rule order, `dlret.py` formulas or the payout gate rules.
- **The golden set** (`tests/fixtures/golden/`, 31 cases) stays green without regeneration: every EFTS URL the resolver builds stays byte-identical.
- **Dependencies:** none new; `requires-python = ">=3.10"`; POSIX only (`fcntl`). The repo has no lint tooling; do not add any.
- **Library default:** `run(..., sec_workers=1)` warms nothing and sends SEC requests one at a time, as today. The CLI default is `--sec-workers 4`, with a maximum of 8.
- **Commands:** run tests with `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest` from the worktree root. Run scripts with `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/<name>.py`. Use relative paths in shell commands.
- **Network:** no live SEC, OpenFIGI or Nasdaq request in any task except Task 16, and Task 16 only while no other SEC client runs on the machine.
- **Commits:** run `git add <files>` and `git commit -m "<message>" -- <files>` as two separate plain Bash calls, with an explicit pathspec. Every message ends with the two trailer lines shown in each task's commit step.

## Review Focus

1. **A second SEC client on the machine during a run** (another run, `verify_against_web.py`, `build_golden_fixtures.py`, another worktree). Expected: combined request starts stay at least 1/8 s apart. Pinned by Task 2's `test_two_limiters_sharing_one_lock_file_space_their_starts` and `test_the_lock_file_is_held_while_a_start_is_taken`.
2. **SEC failing (5xx, dropped connections) while workers are in flight.** Expected: every thread backs off together. Any era, security, payout or successor search whose answer rested on a failed request or a stale copy is flagged `resolution_degraded`, is not saved, and makes the CLI exit 3. Pinned by Task 1's `test_retry_request_pauses_every_thread_on_each_failure`, Task 14's `test_an_era_resolved_through_a_failed_request_is_flagged_resolution_degraded`, and Task 14's CLI exit test.
3. **A refusal (403/429) on a worker thread during a warm pass.** Expected: the pool stops, `EdgarBlocked` reaches the caller, nothing is written, and the main thread never makes the refused call. Pinned by Task 9's `test_a_refusal_stops_the_pool_and_is_raised` and Task 12's `test_a_refusal_on_a_worker_thread_aborts_the_run_and_writes_nothing`.
4. **Caches written before this change**: bare-list EFTS files, version-2/3 resolver memos, stale company-search hits, and temp files left by a killed process. Expected: they are read, or replaced, without error. Pinned by Task 3's `test_temp_files_left_by_a_killed_process_are_removed_at_start`, Task 5's `test_a_file_of_another_schema_is_asked_again_and_replaced`, and the existing `tests/test_resolver_cache.py` version tests.
5. **The same starting caches and run date with 1 worker and with N.** The caches include a stale submissions copy that the sequential pass reads before it refreshes it. Expected: byte-identical CSVs and identical cache trees. Pinned by Task 13's `test_one_worker_and_n_give_the_same_bytes_from_the_same_starting_caches`.

---

## Revision notes

This revision answers the quant review and the controller's rulings on it. Each review item maps to the task that addresses it:

| Review item | Where it is addressed |
|---|---|
| **C1** remembered resolver misses | **Dropped** (the old Task 6). Resolver decisions are never cached as misses. Instead, company-search answers, empties included, are cached on disk with a 7-day TTL (Task 7), and EFTS answers with a lag-scaled TTL (Task 5). A miss is re-derived by the current code from cached evidence on every run. |
| **C2** a per-process limiter with an 8-thread default | Task 2 adds the machine-wide limiter (`MachineGate`, an `fcntl.flock` lock file outside the repo, the wait clamped to [0, 1/8 s], `DELIST_DETECTION_SEC_RATE_LOCK` to override). Task 11 sets the default to `--sec-workers 4`, with 8 as the maximum. Task 15 documents it. |
| **I1** EFTS hits kept for good | Task 5: one TTL for every answer, `max(7, min(365, fetch date − window end))` days. A window ending before 2001 is not covered and is never sent. Each file records its schema version and fetch date, and each hit keeps `_id`. |
| **I2** warm finders unlike the sequential finder, and an overstated byte-identical claim | Task 12: the warm finders get the real MIDAS and Nasdaq-halt clients behind one lock each (`prefetch.Serialized`), plus a copy of the classifier with a shadow resolver. Real clients alone do not make the claim true. A warm worker that *refreshes* a stale copy changes what the sequential pass reads, while a one-thread run reads the stale copy first. So warm threads only fill missing entries (`edgar.fill_only`: Task 3 for submissions, Task 5 for EFTS, Task 7 for company search, applied by `warm` in Task 9). Task 13 proves the claim with cloned cache snapshots, in a scenario that fails without fill-only. |
| **I3** provenance and the calendar date | Task 4 captures the run date once and passes it to the EDGAR client, the resolver, the classifier and the halt feed; Task 11 wires `as_of` through `default_clients` and `run`. Task 14 adds `run_manifest.json` and `resolution_degraded` rows (eras, securities, payouts, successor searches), which count toward exit 3. |
| **I4** fair access while SEC is failing | Task 1: `RateLimiter.pause`. `retry_request` pauses the shared limiter after every failed attempt. Task 3 does the same for the one request path that is not retried. |
| **I5** tests that pass without testing their claim | Task 12: the refusal test raises only on worker threads and asserts the main thread never made the call. A new test asserts the run's own resolver runs only on the main thread. Task 13 replaces the FakeEdgar byte test with a real-cache test. |
| **I6** the measurement protocol | Task 16: seed the FTD, MIDAS, halt and OpenFIGI caches; clone snapshots (`cp -c`); compare 1 worker against N workers from identical snapshots (CSVs and cache trees); measure the request mix and latency at 1, 4 and 8 workers from `run_manifest.json`, alternating the cold-run order; record peak RSS. |
| **I7** an EFTS 4xx counted as transient | Task 5: a 400 or 404 is a non-answer. It is not cached on disk, not transient, logged and counted, and kept in memory only so one run sends it once. A 5xx, a transport error or a non-JSON body still raises. Task 6 pins the resolver side. |
| **I8** no retry on the company search | Task 7: `retry_request` through `EdgarClient._get`. After the retries, a failure raises. A cached hit served after a failed refetch is marked `STALE_KEY`, and the resolver treats it as transient. Task 14 flags the affected eras. |
| **M1** code stale against HEAD | Every code block is rebased on 90be234. Task 12's stage-5 code keeps 4cd60a5's `SecurityRef(..., s.name)`. |
| **M2** the pipeline task is too big | Split into Task 11 (stage 2, CLI, run date, stage meter), Task 12 (stage 5) and Task 13 (stages 8 and 9, and the determinism proof). |
| **M3** the trimmed EFTS format cannot gain fields | Task 5: `schema` in each file, `_id` kept. A file of another schema is asked again and replaced. |
| **M4** one HTTP session for all threads | Task 3: one `requests.Session` per thread (an injected session is shared, for tests). No session-level `Host`; every request builds its own headers. |
| **M5** fail fast on the fallback User-Agent | Task 2 adds `edgar.require_user_agent()`. Task 11's CLI calls it before any request or pool. |
| **M6** `_write_atomic` hardening | Task 3: fsync of the file before the rename and of the directory after it. `clean_orphan_temps` removes a dead writer's temp files when the client (Task 3) or resolver (Task 8) starts. |
| **M7** the memo rewritten on every hit | Task 8: `TickerResolver(batch_writes=True)` with `flush()`. Task 11 flushes at the end of each resolving stage and on the way out of `run()`. The moving memo key, the real cause of 30–70 min reruns, is measured in Task 16 and not fixed here. |
| **M8** CLAUDE.md edits | Allowed by the controller's ruling 12. Task 15 edits CLAUDE.md, README.md, `docs/data-flow.md` and spec §9/§17. |
| **M9** the golden builder | Task 6: the builder's client has `search_cache=False` (it never reads or writes the search caches). It records raw EFTS answers from its session, keeping `hits.total`, so a rebuild does not change fixture shape. |
| **M10** per-stage counts mislabelled | Task 11: `_StageMeter` logs "N EDGAR requests, M SEC data-file downloads (all threads)" per stage and keeps them for the manifest. |
| **M11** a second Ctrl-C | Task 9's `warm` docstring and Task 15's docs. |
| Behaviour change 1 | Task 15: spec §9 now reads "search evidence may be cached with a TTL; a resolver decision is never cached as a miss". |
| Behaviour change 2 | Task 7: the company search raises when EDGAR cannot be reached (after retries). Task 14 flags the degraded eras. |
| Behaviour change 3 | Task 7: an answer reached through a stale copy (submissions, or a company-search hit) is used for the run but not saved. |
| Behaviour change 4 | Task 5: EFTS hits are trimmed to five `_source` fields plus `_id`, with a schema version. |
| "What I would measure" | Task 16. |

**Found while revising, not in the review.**
1. **Refresh order.** A refresh made on a warm thread would change what the sequential pass reads (see I2 above). The answer is fill-only warm threads, which has a cost. Refreshes of stale copies stay sequential: the ~1,300 submissions refetches of a rerun after new fails-to-deliver data are not parallelised. That case improves only through caching and OpenFIGI batching; see "Estimated effect".
2. **A pre-existing staleness bug in `DelistingFinder.find`.** It reads the issuer's submissions without any freshness bound. A copy cached before a Form 25 hides that Form 25 from the scan in the first run after the delisting, and the classifier refreshes the copy only afterwards. This is not fixed here: it changes classification. Task 13's scenario exercises it only to prove determinism.

---

## Where the time goes

Every number below is labelled with its source:
- **Measured:** read on 2026-09-23 from `output/`, `cache/` file counts and mtimes, and the run log. No network calls were made.
- **User:** reported in the request.
- **Estimated:** derived from the code paths plus the measured counts.

| Fact | Value | Source |
|---|---|---|
| Universe | 2,469 ticker eras, 2,660 after the FTD split; 2,272 securities (2,289 with acquirers and successors); 977 delistings | measured: `output/run.log`, `output/*.csv` |
| Cold resolution window (03:00–10:00) | 4,648 JSON cache files written: 1,652 submissions, 1,367 chunks, 1,629 company-search hits. No resolver EFTS answer and no empty company search was ever written | measured: mtimes |
| Sequential filing fetches | 3,416 fetches in one hour, **~1.05 s per request** | measured: mtimes |
| Resolver memo | 3,040 entries, no misses | measured: `cache/ticker_resolution.json` |
| Warm same-day rerun | ≤ 17 min 9 s. It wrote no EDGAR cache file, so all its EDGAR traffic was uncached by design. The delisting loop took ~7.6 min at ~5 securities/s, dominated by one uncached OpenFIGI request per security | measured: log, `stat` |
| Cold run | ~7 h | user |
| Warm rerun after new data | 30–70 min | user |

What that explains (estimated):
- **The cold 7 h** holds 17k–25k request slots at 1–1.5 s, against 4,648 files written. The ~12k–20k requests that left no file are mostly empty company-name searches and resolver EFTS queries, which were never cached. After Tasks 5 and 7, both are cached.
- **The warm same-day rerun (~17 min)** splits into ~7.6 min of per-security OpenFIGI calls (Task 10 batches them into ~23), up to ~8 min re-resolving last run's misses through uncached empty searches (Tasks 5 and 7 cache them), and ~1.5 min of empty successor searches asked again (Task 5 caches them).
- **The 30–70 min reruns** come from era keys that move with new fails-to-deliver data. Each moved key re-resolves and refetches submissions fresh as of today, about 1,300 requests at 1–1.5 s. Those refreshes stay sequential under this plan (see "Design decisions"). Task 16 measures them.

## Design decisions

### Caching: evidence with a TTL, never a decision

- **One EFTS entry point.** All full-text search goes through `EdgarClient.efts_search(url, *, window_end)`. That covers the resolver's two queries, which today call `requests.get` directly and so bypass the limiter, the cache and connection reuse, and the successor search's `full_text_search`. URLs stay byte-identical.
- **EFTS TTL.** Every answer, hits or empty, is written with its fetch date and holds for `efts_ttl_days(window_end, fetched) = max(7, min(365, (fetched − window_end).days))` days. An answer fetched soon after its window closed, or while the window is open, can still change as EDGAR indexes late filings, so it is asked again within a week. One fetched long after has settled, but SEC re-indexes, so even it is asked again yearly.
- **EFTS coverage.** A window that ends before 2001-01-01 is "not covered": no request is sent, it returns `[]`, and it is counted as `not_covered` in the manifest. An undated query is kept in memory for the run only.
- **EFTS file format.** `{"schema": 1, "window_end", "__fetched__", "efts_hits": [...]}`. Each hit is `{"_id", "_source": {ciks, display_names, form, file_date, adsh}}`. A file of another schema, including the old bare lists, is asked again and replaced.
- **EFTS answers that are not answers.**
  - A 400 or 404 is a rejected query: logged, counted, returned as `[]`, never written, never transient, and kept in memory so one run sends it once.
  - A 5xx after retries, a transport error or a non-JSON body raises `requests.RequestException`, is never cached, and makes the resolve transient.
- **Company search.** Every answer, hits or empty, is written with its fetch date and trusted for 7 days. The request goes through `retry_request`. If it still fails, a cached hit list is served with `STALE_KEY` on each hit; with nothing to fall back on, the search raises.
- **The resolver never saves a miss or a transient answer.** "Transient" now also covers a stale submissions copy and a stale company-search hit. Such answers are used for the run and reported through `is_degraded()`, which becomes a `resolution_degraded` review row. Memo writes are batched and flushed per stage.

### Concurrency: warm, then sequential

- **Limiter.**
  - In process, `edgar.SEC_LIMITER = RateLimiter(8.0)`. Its lock is held while it sleeps, so starts are at least 125 ms apart and no burst credit builds up.
  - `pause(s)` holds every thread's next start while SEC is failing.
  - `cancelled_by(stop)` lets a stopped prefetch worker's next request raise `PrefetchCancelled`, a `BaseException` that the library's `except Exception` handlers pass through.
  - Machine-wide, `edgar.use_machine_wide_limit()` installs a `MachineGate`: a lock file, by default `~/.cache/delist_detection/sec_rate.lock` (`$DELIST_DETECTION_SEC_RATE_LOCK` overrides it), holding the last start time as wall-clock seconds. Each start takes the in-process lock first, then the file's `flock`, waits `clamp(last + 1/8 − now, 0, 1/8)`, and writes its own start.
  - The CLI, `default_clients`, `verify_against_web.py` and `build_golden_fixtures.py` install the gate.
- **`EdgarClient` shared by threads.**
  - Each thread has its own `requests.Session`, and each request builds its own headers.
  - Each cache file has its own lock: check, fetch and write happen under it, so two threads needing one URL make one request.
  - Writes are atomic and durable: a temp file, fsync, `os.replace`, then fsync of the directory. A dead writer's temp files are removed when a client starts.
  - **Fill-only on warm threads.** Inside `edgar.fill_only()`, a read may fetch what is missing but returns an existing copy whatever its age: a submissions copy older than `fresh_after`, an expired search answer. So a warm pass never replaces a cached copy, and every refresh happens in the sequential pass in its own order, exactly as in a one-thread run. The cost is that refreshes of stale copies are not parallelised; misses, which are most of a cold run, still are.
- **Warm passes.** One per SEC-heavy stage:

  | Stage | Warm task |
  |---|---|
  | Issuer resolution | one per era: a shadow `TickerResolver` (a snapshot of the memo that saves nothing) |
  | Form 25 search | one per security: `DelistingFinder.find` with a copy of the classifier holding a shadow resolver, and the run's own MIDAS and halt clients, each behind one lock (`Serialized`) |
  | Payout extraction | one per merger |
  | Successor search | one EFTS query per unresolved exchange transfer |

  Each warm pass throws its answers away. The stage then runs as today on the main thread, one item at a time, in sorted order.
- **Refusal mid-pool.** The first `EdgarBlocked` or `OpenFigiBlocked`, or a Ctrl-C, sets the pool's stop event. No queued item starts, every running worker's next SEC request raises `PrefetchCancelled`, and the refusal is re-raised on the main thread. The CLI exits 2, and nothing is written, because outputs are written only at the end.
- **Provenance.**
  - `as_of` is read once, by `default_clients` or at the top of `run()`, and passed to every client.
  - `edgar.SEC_STATS` counts per endpoint, across threads: requests, cache answers, latency, and degraded answers (a stale copy served, a request that failed). `degraded()` also counts on the calling thread alone, which is how the pipeline ties a degraded answer to the era or security it served.
  - `run_manifest.json` is written after the tables, never on an aborted run.
- **Alternatives rejected.**
  - (a) Resolving concurrently and merging the results in order: it needs a thread-safe memo, and review-row order would depend on it.
  - (b) A static prefetch list: it misses the data-dependent resolver chain.
  - (c) An async rewrite: too invasive.
  - (d) A rate above 8/s: the spec forbids it.
  - (e) Remembered resolver misses (review C1): they freeze a survivorship-relevant decision.
  - (f) Warm threads that refresh: they break the determinism claim, as shown in Task 13.

### Not in scope

- The moving resolver memo key (`era_last_seen` moves with new FTD data). It is the cause of the 30–70 min reruns (review M7); Task 16 measures it.
- The finder's stale Form 25 scan ("Found while revising", item 2).
- Per-era CPU cost.
- `verify_against_web.py` concurrency. It only gets the machine-wide gate.

## Risks

| Risk | Mitigation (task) |
|---|---|
| Deadlock | A thread holds at most one of: an EdgarClient file lock, or a `Serialized` client lock (MIDAS and halts never touch EdgarClient, and the finder calls them outside any EdgarClient method). Then come the limiter lock, its pause lock and the machine `flock`, always in that order. `_locks_guard` covers only a dict lookup (T1–T3, T9) |
| A worker's refresh changing what the sequential pass reads | Warm threads are fill-only (T3, T5, T7, T9); proved by T13 |
| Two processes over SEC's 10 req/s | Machine-wide gate on a shared lock file (T2). A process that never installs it (a library caller that skips `default_clients`) is limited per process only; the docs say so (T15) |
| A stale lock-file stamp after a wall-clock step | The wait is clamped to [0, 1/8 s] (T2) |
| SEC failing under load | Shared pause on every failure (T1, T3); degraded answers flagged, never saved (T7, T8, T14) |
| Cancellation | A stop event plus `PrefetchCancelled` at the next request; queued items never start (T1, T9) |
| Memory with 8 workers | 8 threads may each parse a large issuer's submissions at once (largest file 5.1 MB; stripped 10-K text up to 3 MB). Under 1 GB worst case; T16 records peak RSS |
| Existing tests | `run()` defaults to one worker. Tests get a fresh, non-sleeping, in-process limiter per test (T1 `conftest`). The harness seams move from `requests.get` to `_efts_hits` (T6). Changed tests are listed in their tasks |
| Warm-pass CPU | The stage-5 warm pass repeats the loop's CPU (~1–2 min on a fully cached rerun, estimated). `--sec-workers 1` skips every warm pass |

## Estimated effect

| Run | Today | 4 workers (default) | 8 workers | Basis (estimated unless marked) |
|---|---|---|---|---|
| Cold: issuer resolution | ~7 h (user) | ~1.1–2.6 h | ~35–80 min | 15k–25k requests at 1–1.5 s each over 4 or 8 connections, capped at 8 req/s machine-wide |
| Cold: delisting search and payouts | ~1.75 h + ~8 min OpenFIGI | ~25–40 min + < 1 min | ~13–20 min + < 1 min | ~6k fetches at the measured 1.05 s; OpenFIGI batches of 100 |
| Warm rerun, same week | ~17 min (measured, same day) | ~3–5 min | same | EFTS and company-search answers cached; 2,289 OpenFIGI requests become ~23; what is left is CPU (~2 min) plus warm-pass CPU |
| Warm rerun after new FTD data | 30–70 min (user) | ~25–35 min | same | ~1,300 submissions refreshes stay sequential under fill-only; the rest as above |

The estimates assume SEC answers in 1–1.5 s per request and keeps answering with 4–8 requests in flight without 5xx. Nobody has measured that; Task 16 does. Without `OPEN_FIGI_API_KEY`, the listing batch is ~229 requests at 25 per 6 s, about 1 min.

## File structure

**Create:**
- `src/delist_detection/prefetch.py`: `warm()`, the thread pool that fills the SEC caches ahead of a sequential stage, and `Serialized`, one lock around a client that is not thread-safe.
- `src/delist_detection/manifest.py`: `run_manifest.json`, built from `edgar.SEC_STATS`.
- `tests/test_rate_limiter.py`, `tests/test_edgar_threads.py`, `tests/test_run_date.py`, `tests/test_request_stats.py`, `tests/test_edgar_efts_cache.py`, `tests/test_resolver_efts.py`, `tests/test_prefetch.py`, `tests/test_pipeline_prefetch.py`, `tests/test_run_provenance.py`.

**Modify source:**
- `src/delist_detection/edgar.py`:
  - limiter: `RateLimiter`, `SEC_LIMITER`, `MachineGate`, `use_machine_wide_limit`, `require_user_agent`, `PrefetchCancelled`;
  - client plumbing: per-thread sessions, `_get`, `_lock_for`, `_write_atomic`, `clean_orphan_temps`, `fill_only`;
  - accounting: `today`, `SEC_STATS`;
  - searches: `efts_search`, the company search.
- `src/delist_detection/sec_http.py`: request accounting.
- `src/delist_detection/ticker_resolver.py`: `today`, EFTS through the client, stale reads count as transient, `is_degraded`, batched writes, `shadow()`.
- `src/delist_detection/classifier.py`, `src/delist_detection/nasdaq_halts.py`: `today`.
- `src/delist_detection/listing_status.py`: `listing_job`, `listing_answers`, `listed_today(answer=)`.
- `src/delist_detection/pipeline.py`: `Clients.as_of`, `run(sec_workers=)`, `_StageMeter`, the warm passes, `successor_query`, `resolution_degraded` rows, the manifest.
- `scripts/classify_universe.py`, `scripts/build_golden_fixtures.py`, `scripts/verify_against_web.py`.

**Modify tests:** `tests/conftest.py`, `tests/golden.py`, `tests/test_resolver_member_names.py`, `tests/test_sec_http.py`, `tests/test_edgar_company_search_fresh.py`, `tests/test_resolver_cache.py`, `tests/test_listing_status.py`, `tests/test_pipeline.py`, `tests/test_classify_universe_cli.py`, `tests/test_build_golden_fixtures.py`, `tests/test_nasdaq_halts.py`.

**Modify docs:** `docs/data-flow.md`, `docs/superpowers/feature-spec.md` (§9, §17), `CLAUDE.md`, `README.md`.

---

## Tasks

| # | Title | Model |
|---|---|---|
| 1 | In-process SEC rate limiter: stop signal and shared failure pause | most capable |
| 2 | Machine-wide SEC rate limit and setup checks | most capable |
| 3 | EdgarClient safe to share between threads | most capable |
| 4 | One run date and request accounting | standard |
| 5 | Full-text-search answers cached with a lag-scaled TTL | standard |
| 6 | The resolver's full-text searches go through the client | standard |
| 7 | Company-name search: cached empties, retries, raises when unreachable | standard |
| 8 | Resolver: degraded answers are known, memo writes are batched | standard |
| 9 | `prefetch.warm` and `Serialized` | most capable |
| 10 | OpenFIGI listing lookups in batches | standard |
| 11 | Pipeline: run date, `--sec-workers`, stage-2 warm pass, stage meter | most capable |
| 12 | Stage-5 warm pass with the run's own MIDAS and halt clients | most capable |
| 13 | Stage 8 and 9 warm passes, and the determinism proof | most capable |
| 14 | Provenance: `resolution_degraded` and `run_manifest.json` | standard |
| 15 | Documentation | standard |
| 16 | Measure on the real universe (live) | most capable |

---

### Task 1: In-process SEC rate limiter: stop signal and shared failure pause

**Model:** most capable (limiter and threads).

**Files:**
- Modify: `src/delist_detection/edgar.py`:
  - imports (`:7-19`);
  - delete `_RATE_LOCK` / `_LAST_CALL` / `_MIN_INTERVAL` (`:75-77`);
  - replace `_throttle` (`:101-107`) and `retry_request` (`:116-146`).
- Modify: `tests/conftest.py` (new autouse fixture).
- Test: create `tests/test_rate_limiter.py`.

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `edgar.PrefetchCancelled(BaseException)`.
  - `edgar.RateLimiter(rate: float, *, clock=time.monotonic, sleep=time.sleep)`, with:
    - `.acquire() -> None`
    - `.pause(seconds: float) -> None`
    - `.cancelled_by(stop: threading.Event)` (a context manager)
    - `.interval: float`
    - `.count: int`
  - `edgar.SEC_MAX_RATE = 8.0` and `edgar.SEC_LIMITER: RateLimiter`.
  - `edgar._throttle() -> None`, which calls `SEC_LIMITER.acquire()` and keeps its zero-argument signature (tests patch it with `lambda: None`).
  - `edgar.retry_request(...)`: same signature; it now also calls `SEC_LIMITER.pause(wait)` after every failed attempt.
  - A `tests/conftest.py` autouse fixture `_fresh_sec_limiter` that gives each test its own non-sleeping, in-process `SEC_LIMITER`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rate_limiter.py
"""The process-wide SEC rate limiter: request starts spaced 1/rate apart across
threads, a pause every thread honours while SEC fails, and a stopped prefetch
worker that starts no further request."""
import threading

import pytest
import requests

from delist_detection import edgar
from delist_detection.edgar import PrefetchCancelled, RateLimiter


class _Clock:
    """A clock that only moves when someone sleeps on it."""

    def __init__(self):
        self.t, self.slept = 100.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 9))
        self.t += s


class _Resp:
    def __init__(self, status):
        self.status_code, self.url = status, "https://data.sec.gov/x"


def _limiter(c):
    return RateLimiter(8, clock=c.now, sleep=c.sleep)


def test_starts_are_spaced_by_the_interval():
    c = _Clock()
    lim = _limiter(c)
    starts = []
    for _ in range(3):
        lim.acquire()
        starts.append(c.t)
    assert starts == [100.0, 100.125, 100.25]
    assert c.slept == [0.125, 0.125]
    assert lim.count == 3


def test_a_caller_after_a_quiet_spell_does_not_wait():
    c = _Clock()
    lim = _limiter(c)
    lim.acquire()
    c.t += 1.0
    lim.acquire()
    assert c.slept == []


def test_threads_sharing_a_limiter_never_start_closer_than_the_interval():
    # The clock only moves inside the limiter's own sleeps, so every acquire after the
    # first must sleep one full interval -- whatever order the 16 threads run in.
    c = _Clock()
    lim = _limiter(c)
    threads = [threading.Thread(target=lim.acquire) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert lim.count == 16
    assert c.slept == [0.125] * 15
    assert c.t == pytest.approx(100.0 + 15 * 0.125)


def test_a_pause_holds_the_next_start():
    c = _Clock()
    lim = _limiter(c)
    lim.acquire()
    lim.pause(2.0)
    lim.acquire()
    assert c.slept == [2.0]
    assert c.t == pytest.approx(102.0)


def test_a_shorter_pause_never_cuts_a_longer_one():
    c = _Clock()
    lim = _limiter(c)
    lim.pause(4.0)
    lim.pause(2.0)
    lim.acquire()
    assert c.slept == [4.0]


def test_a_pause_set_on_one_thread_holds_every_other_thread():
    c = _Clock()
    lim = _limiter(c)
    t = threading.Thread(target=lim.pause, args=(2.0,))
    t.start()
    t.join(5)
    lim.acquire()
    assert c.slept == [2.0]


def test_retry_request_pauses_every_thread_on_each_failure(monkeypatch):
    c = _Clock()
    lim = _limiter(c)
    monkeypatch.setattr(edgar, "SEC_LIMITER", lim)
    answers = iter([_Resp(503), requests.ConnectionError("reset"), _Resp(200)])

    def make():
        r = next(answers)
        if isinstance(r, Exception):
            raise r
        return r

    slept = []
    assert edgar.retry_request(make, sleep=slept.append).status_code == 200
    assert slept == [2, 4]                     # this thread backs off as before...
    other = threading.Thread(target=lim.acquire)
    other.start()
    other.join(5)
    assert c.slept == [4.0]                    # ...and another thread's next start waits out the pause


def test_a_request_that_keeps_failing_leaves_the_pool_paused(monkeypatch):
    c = _Clock()
    lim = _limiter(c)
    monkeypatch.setattr(edgar, "SEC_LIMITER", lim)
    assert edgar.retry_request(lambda: _Resp(503), sleep=lambda s: None).status_code == 503
    lim.acquire()
    assert c.slept == [4.0]                    # the last backoff also holds everyone's next start


def test_a_stopped_worker_starts_no_further_request():
    c = _Clock()
    lim = _limiter(c)
    stop = threading.Event()
    with lim.cancelled_by(stop):
        lim.acquire()
        stop.set()
        with pytest.raises(PrefetchCancelled):
            lim.acquire()
    lim.acquire()                              # outside the block the event no longer applies
    assert lim.count == 2


def test_the_stop_event_applies_only_to_the_thread_that_entered_the_block():
    c = _Clock()
    lim = _limiter(c)
    stop = threading.Event()
    stop.set()
    with lim.cancelled_by(stop):
        other = threading.Thread(target=lim.acquire)
        other.start()
        other.join(5)
    assert lim.count == 1


def test_prefetch_cancelled_passes_through_except_exception():
    with pytest.raises(PrefetchCancelled):
        try:
            raise PrefetchCancelled()
        except Exception:                      # the library's broad handlers must not swallow it
            pytest.fail("PrefetchCancelled was caught by `except Exception`")


def test_every_sec_request_goes_through_the_shared_limiter(monkeypatch):
    calls = []

    class _Probe:
        def acquire(self):
            calls.append("acquire")

    monkeypatch.setattr(edgar, "SEC_LIMITER", _Probe())
    edgar._throttle()
    assert calls == ["acquire"]


def test_the_shared_limiter_allows_8_requests_per_second():
    assert edgar.SEC_LIMITER.interval == pytest.approx(0.125)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_rate_limiter.py -q`
Expected: collection error `ImportError: cannot import name 'PrefetchCancelled' from 'delist_detection.edgar'`.

- [ ] **Step 3: Implement**

In `src/delist_detection/edgar.py`, add `from contextlib import contextmanager` to the imports and delete these three lines:

```python
_RATE_LOCK = threading.Lock()
_LAST_CALL: list[float] = [0.0]
_MIN_INTERVAL = 1.0 / 8.0
```

Replace the whole `_throttle` function with:

```python
class PrefetchCancelled(BaseException):
    """Raised at a prefetch worker's next SEC request once its pool is stopping (a
    refusal on another thread, or Ctrl-C). A BaseException, like KeyboardInterrupt,
    so the library's `except Exception` handlers let it through and the worker ends
    without sending another request."""


class RateLimiter:
    """At most `rate` request starts per second across every thread that shares it.

    `acquire()` blocks until the caller may start one request: `interval` after
    the previous start, and not before a pause set by `pause()` has run out. The
    lock is held while sleeping, so callers queue behind it and no burst credit
    builds up. `clock` and `sleep` are injectable so tests never wait.
    """

    def __init__(self, rate: float, *, clock=time.monotonic, sleep=time.sleep) -> None:
        self.interval = 1.0 / rate
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()            # held from the wait through the start
        self._pause_lock = threading.Lock()      # guards _resume_at only; taken after _lock, never before
        self._last: float | None = None
        self._resume_at = float("-inf")
        self._local = threading.local()
        self.count = 0                           # requests started through this limiter

    def _raise_if_cancelled(self) -> None:
        stop = getattr(self._local, "stop", None)
        if stop is not None and stop.is_set():
            raise PrefetchCancelled()

    def pause(self, seconds: float) -> None:
        """Hold every caller's next request start until `seconds` from now. SEC is
        failing (a 5xx or a dropped connection), so the whole pool backs off
        together instead of each thread on its own. A longer pause already set is
        kept."""
        with self._pause_lock:
            self._resume_at = max(self._resume_at, self._clock() + seconds)

    def acquire(self) -> None:
        self._raise_if_cancelled()
        with self._lock:
            self._raise_if_cancelled()           # stopped while queued behind the lock
            with self._pause_lock:
                ready = self._resume_at
            if self._last is not None:
                ready = max(ready, self._last + self.interval)
            wait = ready - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._raise_if_cancelled()           # stopped while sleeping: the slot goes unused
            self._last = self._clock()
            self.count += 1

    @contextmanager
    def cancelled_by(self, stop: threading.Event):
        """Inside this block, the calling thread's acquire() raises PrefetchCancelled
        once `stop` is set. Other threads are not affected."""
        self._local.stop = stop
        try:
            yield
        finally:
            self._local.stop = None


SEC_MAX_RATE = 8.0      # SEC allows 10 requests/s per client; we stay under it (spec §9, §11)
SEC_LIMITER = RateLimiter(SEC_MAX_RATE)


def _throttle() -> None:
    """Wait for this process's next SEC request slot. Every SEC request in the
    library (EdgarClient, sec_http, verify_against_web) calls this, from any
    thread. It reads the module's SEC_LIMITER at each call, so a test or the
    CLI can swap or extend the limiter."""
    SEC_LIMITER.acquire()
```

Replace `retry_request` with:

```python
def retry_request(make_request, *, sleep=time.sleep, max_attempts: int = RETRY_MAX_ATTEMPTS,
                  backoff: tuple[float, ...] = RETRY_BACKOFF):
    """Call `make_request()` (a callable returning a `requests.Response`) up
    to `max_attempts` times, retrying a connection error, a timeout, or a 5xx
    response with `backoff` seconds between attempts (`sleep` is injectable
    for tests). `check_response` runs on every response that comes back, so a
    403/429 raises `EdgarBlocked` immediately -- it is never retried. A 404 or
    any other non-5xx response is returned on the first attempt, unchanged.

    After every failed attempt the shared SEC_LIMITER is paused for that
    attempt's backoff (the last attempt for the last backoff), so every other
    thread's next SEC request waits too: while SEC is failing, the pool backs
    off together instead of sending ~8 mostly failing requests a second.

    On final failure: if every attempt raised, the last exception is
    re-raised; if the last attempt returned a persistent 5xx response, that
    response is returned (the caller's own `raise_for_status()`/status check
    decides what happens next -- unchanged from before this helper existed).
    """
    last_exc: requests.RequestException | None = None
    resp = None
    for attempt in range(max_attempts):
        try:
            resp = make_request()
        except requests.RequestException as exc:
            last_exc, resp = exc, None
        else:
            check_response(resp)              # 403/429 -> EdgarBlocked, raised at once, never retried
            if resp.status_code < 500:
                return resp
            last_exc = None                   # a 5xx is retryable, not a transport exception
        wait = backoff[min(attempt, len(backoff) - 1)]
        SEC_LIMITER.pause(wait)               # every thread's next SEC request waits too
        if attempt < max_attempts - 1:
            sleep(wait)
    if resp is not None:
        return resp
    raise last_exc
```

Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _fresh_sec_limiter(monkeypatch):
    """Every test gets its own process-wide SEC limiter: in-process only (never a
    machine-wide lock file under the home directory), never sleeping, and with no
    pause or request count left over from another test."""
    from delist_detection import edgar
    monkeypatch.setattr(edgar, "SEC_LIMITER", edgar.RateLimiter(edgar.SEC_MAX_RATE, sleep=lambda s: None))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_rate_limiter.py tests/test_sec_http.py tests/test_edgar_blocked.py tests/test_verify_against_web.py tests/test_edgar_submissions_fresh.py tests/test_edgar_company_search_fresh.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass (759 + 13 new).

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/edgar.py tests/conftest.py tests/test_rate_limiter.py
```

```bash
git commit -m "perf(edgar): one process-wide SEC rate limiter with a stop signal and a pause every thread honours

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/edgar.py tests/conftest.py tests/test_rate_limiter.py
```

---

### Task 2: Machine-wide SEC rate limit and setup checks

**Model:** most capable (file locks across processes).

**Files:**
- Modify: `src/delist_detection/edgar.py`:
  - imports: add `fcntl` and `weakref`;
  - `RateLimiter.__init__` and `RateLimiter.acquire` (Task 1 code);
  - new `SEC_RATE_LOCK_ENV`, `default_rate_lock_path`, `MachineGate`, `use_machine_wide_limit`, `EdgarSetupError`, `require_user_agent`.
- Modify: `scripts/verify_against_web.py`: its import line (`:28`) and `main()` (`:226-232`).
- Test: `tests/test_rate_limiter.py` (append).

**Interfaces:**
- Consumes: `RateLimiter`, `SEC_LIMITER` (Task 1).
- Produces:
  - `RateLimiter(..., gate: MachineGate | None = None)` and the attribute `RateLimiter.gate`.
  - `edgar.MachineGate(path, interval, *, wall=time.time, sleep=time.sleep)`, with `.wait_turn() -> None` and `.path: Path`.
  - `edgar.SEC_RATE_LOCK_ENV = "DELIST_DETECTION_SEC_RATE_LOCK"`.
  - `edgar.default_rate_lock_path() -> Path`.
  - `edgar.use_machine_wide_limit(path: str | Path | None = None) -> MachineGate`: idempotent per path. It raises `OSError`, naming the path and the variable, when the lock file cannot be opened.
  - `edgar.EdgarSetupError(RuntimeError)` and `edgar.require_user_agent() -> str`, which raises `EdgarSetupError` when only `FALLBACK_UA` is left.

- [ ] **Step 1: Write the failing tests**

Add to the imports at the top of `tests/test_rate_limiter.py`:

```python
import fcntl
import os
from pathlib import Path

from delist_detection.edgar import SEC_RATE_LOCK_ENV, MachineGate, default_rate_lock_path
```

Append:

```python
def _gate(path, c):
    return MachineGate(path, 0.125, wall=c.now, sleep=c.sleep)


def test_two_limiters_sharing_one_lock_file_space_their_starts(tmp_path):
    # Two processes on one machine: each has its own in-process limiter, and both
    # use the same lock file. Their starts interleave but never come closer than
    # 1/8 s.
    c = _Clock()
    path = tmp_path / "sec_rate.lock"
    a = RateLimiter(8, clock=c.now, sleep=c.sleep, gate=_gate(path, c))
    b = RateLimiter(8, clock=c.now, sleep=c.sleep, gate=_gate(path, c))
    starts = []
    for lim in (a, b, a, b):
        lim.acquire()
        starts.append(c.t)
    assert starts == pytest.approx([100.0, 100.125, 100.25, 100.375])
    assert float(path.read_text()) == pytest.approx(100.375)


def test_a_wall_clock_step_back_waits_at_most_one_interval(tmp_path):
    c = _Clock()
    path = tmp_path / "sec_rate.lock"
    path.write_text("999999.0")                 # a start stamped "in the future": the clock stepped back
    _gate(path, c).wait_turn()
    assert c.slept == [0.125]


@pytest.mark.parametrize("content", ["", "garbage", "1.0"])
def test_an_old_or_unreadable_stamp_does_not_wait(tmp_path, content):
    c = _Clock()
    path = tmp_path / "sec_rate.lock"
    path.write_text(content)
    _gate(path, c).wait_turn()
    assert c.slept == []
    assert float(path.read_text()) == pytest.approx(100.0)


def test_the_lock_file_is_held_while_a_start_is_taken(tmp_path):
    path = tmp_path / "sec_rate.lock"
    gate = MachineGate(path, 0.125)             # real clock; a new file never waits
    holder = os.open(path, os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)          # another process is taking its start
    t = threading.Thread(target=gate.wait_turn)
    t.start()
    t.join(0.2)
    assert t.is_alive()                         # this one waits for the lock
    fcntl.flock(holder, fcntl.LOCK_UN)
    os.close(holder)
    t.join(5)
    assert not t.is_alive()


def test_the_lock_path_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(SEC_RATE_LOCK_ENV, str(tmp_path / "x.lock"))
    assert default_rate_lock_path() == tmp_path / "x.lock"
    monkeypatch.delenv(SEC_RATE_LOCK_ENV)
    assert default_rate_lock_path() == Path.home() / ".cache" / "delist_detection" / "sec_rate.lock"


def test_use_machine_wide_limit_gates_the_shared_limiter(monkeypatch, tmp_path):
    monkeypatch.setenv(SEC_RATE_LOCK_ENV, str(tmp_path / "sec_rate.lock"))
    gate = edgar.use_machine_wide_limit()
    assert edgar.SEC_LIMITER.gate is gate and gate.path == tmp_path / "sec_rate.lock"
    assert edgar.use_machine_wide_limit() is gate          # idempotent
    edgar._throttle()
    assert float((tmp_path / "sec_rate.lock").read_text()) > 0


def test_an_unwritable_lock_path_fails_at_setup_naming_the_variable(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    with pytest.raises(OSError, match=SEC_RATE_LOCK_ENV):
        edgar.use_machine_wide_limit(blocker / "sub" / "sec_rate.lock")   # a file where a directory must be
    assert edgar.SEC_LIMITER.gate is None


def test_require_user_agent_refuses_the_fallback(monkeypatch):
    monkeypatch.setattr(edgar, "resolve_user_agent", lambda: edgar.FALLBACK_UA)
    with pytest.raises(edgar.EdgarSetupError, match="EDGAR_USER_AGENT"):
        edgar.require_user_agent()
    monkeypatch.setattr(edgar, "resolve_user_agent", lambda: "Test Co test@example.com")
    assert edgar.require_user_agent() == "Test Co test@example.com"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_rate_limiter.py -q`
Expected: collection error `ImportError: cannot import name 'SEC_RATE_LOCK_ENV'`.

- [ ] **Step 3: Implement**

In `src/delist_detection/edgar.py`, add `import fcntl` and `import weakref` to the imports.

In `RateLimiter.__init__` (Task 1), change the signature to

```python
    def __init__(self, rate: float, *, clock=time.monotonic, sleep=time.sleep,
                 gate: "MachineGate | None" = None) -> None:
```

and add as its last line:

```python
        self.gate = gate                         # machine-wide spacing (MachineGate), taken after _lock
```

In `RateLimiter.acquire`, replace

```python
            self._raise_if_cancelled()           # stopped while sleeping: the slot goes unused
            self._last = self._clock()
```

with

```python
            self._raise_if_cancelled()           # stopped while sleeping: the slot goes unused
            if self.gate is not None:
                self.gate.wait_turn()            # every other process sharing the lock file
            self._last = self._clock()
```

Add to `RateLimiter`'s docstring, before "`clock` and `sleep`": "`gate` (a MachineGate) extends the spacing to every process on the machine that shares its lock file; it is taken after the in-process lock, so this process's own threads queue cheaply first."

After `SEC_LIMITER = RateLimiter(SEC_MAX_RATE)`, add:

```python
SEC_RATE_LOCK_ENV = "DELIST_DETECTION_SEC_RATE_LOCK"


def default_rate_lock_path() -> Path:
    """The machine-wide SEC rate lock file: $DELIST_DETECTION_SEC_RATE_LOCK, else
    ~/.cache/delist_detection/sec_rate.lock. Outside the repo on purpose: every
    checkout and worktree on the machine must share it."""
    env = os.environ.get(SEC_RATE_LOCK_ENV, "").strip()
    return Path(env).expanduser() if env else Path.home() / ".cache" / "delist_detection" / "sec_rate.lock"


class MachineGate:
    """Spaces SEC request starts across every process on the machine that uses one
    lock file. The file holds the wall-clock time of the last start. `wait_turn`
    takes the file's exclusive `flock`, waits until `interval` after that time,
    writes its own start and releases the lock. The wait is clamped to
    [0, interval], so a wall-clock step can neither stall the pool (a stamp "in
    the future") nor let a burst through; an unreadable stamp counts as none.
    The file is opened here, so an unwritable path fails at start-up, not in the
    middle of a run."""

    def __init__(self, path: str | Path, interval: float, *, wall=time.time, sleep=time.sleep) -> None:
        self.path, self.interval = Path(path), interval
        self._wall, self._sleep = wall, sleep
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        weakref.finalize(self, os.close, self._fd)

    def wait_turn(self) -> None:
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        try:
            try:
                last = float(os.pread(self._fd, 64, 0).decode("ascii").strip() or "0")
            except (UnicodeDecodeError, ValueError):
                last = 0.0
            wait = min(max(last + self.interval - self._wall(), 0.0), self.interval)
            if wait > 0:
                self._sleep(wait)
            stamp = f"{self._wall():.6f}".encode("ascii")
            os.ftruncate(self._fd, 0)
            os.pwrite(self._fd, stamp, 0)
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)


def use_machine_wide_limit(path: str | Path | None = None) -> MachineGate:
    """Extend SEC_LIMITER's spacing to every process on this machine that uses the
    same lock file (`path`, default `default_rate_lock_path()`). Call it once at
    start-up, before any SEC request: the CLI, `pipeline.default_clients`,
    `verify_against_web.py` and `build_golden_fixtures.py` do. Idempotent for one
    path. Raises OSError, naming the path and SEC_RATE_LOCK_ENV, when the lock
    file cannot be opened for writing."""
    p = Path(path).expanduser() if path is not None else default_rate_lock_path()
    gate = SEC_LIMITER.gate
    if gate is not None and gate.path == p:
        return gate
    try:
        gate = MachineGate(p, SEC_LIMITER.interval)
    except OSError as exc:
        raise OSError(f"cannot open the machine-wide SEC rate lock {p} ({exc}); set {SEC_RATE_LOCK_ENV} "
                      "to a writable file that every SEC client on this machine uses") from exc
    SEC_LIMITER.gate = gate
    return gate


class EdgarSetupError(RuntimeError):
    """The client is not set up to talk to SEC: no User-Agent SEC accepts."""


def require_user_agent() -> str:
    """The configured User-Agent. Raises EdgarSetupError when only the fallback
    is left, which SEC answers with 403, so a run stops before its first request
    instead of after a pool of threads has been refused."""
    ua = resolve_user_agent()
    if ua == FALLBACK_UA:
        raise EdgarSetupError(
            "EDGAR_USER_AGENT is not set (environment or the repo .env); SEC refuses the fallback "
            f"User-Agent {FALLBACK_UA!r}. Set it to a name and a contact address, e.g. 'Jane Doe jane@example.com'.")
    return ua
```

In `scripts/verify_against_web.py`, change the import to:

```python
from delist_detection.edgar import EdgarBlocked, _throttle, check_response, resolve_user_agent, use_machine_wide_limit
```

In its `main()`, right after `args = p.parse_args()`, add:

```python
    use_machine_wide_limit()     # share the 8 requests/s with every other SEC client on this machine
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_rate_limiter.py tests/test_verify_against_web.py tests/test_sec_http.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/edgar.py scripts/verify_against_web.py tests/test_rate_limiter.py
```

```bash
git commit -m "perf(edgar): a machine-wide SEC rate limit through a shared lock file, and a start-up User-Agent check

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/edgar.py scripts/verify_against_web.py tests/test_rate_limiter.py
```

---

### Task 3: EdgarClient safe to share between threads

**Model:** most capable (per-file locks, atomic writes, thread-local state).

**Files:**
- Modify: `src/delist_detection/edgar.py`:
  - new module functions `_write_atomic`, `_fsync_dir`, `_pid_alive`, `clean_orphan_temps`, `fill_only`, `filling_only`;
  - `EdgarClient.__init__` (`:166-181`), a new `session` property, `_headers`, `_get` and `_lock_for`;
  - `_get_json` (`:187-240`);
  - `company_search_atom` (`:294-305`, `:330-331`);
  - `fetch_filing_text` (`:342-383`), `fetch_filing_raw` (`:385-418`);
  - `full_text_search` (`:448-468`).
- Test: create `tests/test_edgar_threads.py`.

**Interfaces:**
- Consumes: `_throttle`, `SEC_LIMITER.pause`, `retry_request`, `RETRY_BACKOFF` (Task 1).
- Produces:
  - `edgar._write_atomic(path: Path, text: str) -> None`: a temp file, fsync, `os.replace`, then fsync of the directory.
  - `edgar.clean_orphan_temps(directory: Path) -> None`.
  - `edgar.fill_only()` (a context manager) and `edgar.filling_only() -> bool`: per thread.
  - `EdgarClient`:
    - `.user_agent: str`;
    - `.session`: the calling thread's session, or the injected one shared by all threads;
    - `._headers(host: str, accept: str) -> dict`;
    - `._get(url: str, *, host: str, accept: str, retry: bool = True) -> Response`;
    - `._lock_for(key: str) -> threading.Lock`, where the key is always `str(<cache file path>)`;
    - `._locks: dict[str, threading.Lock]`.
  - No session-level `Host` or `User-Agent` default any more.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_edgar_threads.py
"""EdgarClient shared by threads: one session per thread, each request's own
headers, one lock per cache file (one request per URL however many threads ask),
atomic and durable cache writes, a dead writer's temp files removed, and
fill-only reads for prefetch threads."""
import json
import os
import subprocess
import sys
import threading
from datetime import date

import pytest
import requests

from delist_detection import edgar
from delist_detection.edgar import EdgarClient, fill_only, filling_only

UA = "Test Co test@example.com"
SUB_URL = "https://data.sec.gov/submissions/CIK0000000042.json"


class _Resp:
    def __init__(self, status=200, text='{"name": "Co"}'):
        self.status_code, self.text, self.url = status, text, "u"

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    """Answers every GET with one status. Records each request's URL and headers
    and, given the client, which cache-file locks were held at that moment."""

    def __init__(self, status=200, client_box=None):
        self.status, self.client_box = status, client_box
        self.calls, self.seen, self.held = [], [], []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        self.seen.append((url, headers))
        if self.client_box:
            client = self.client_box[0]
            self.held.append(sorted(k for k, lock in client._locks.items() if lock.locked()))
        return _Resp(self.status)


def _client(tmp_path, session):
    return EdgarClient(cache_dir=tmp_path, user_agent=UA, session=session, sleep=lambda _: None)


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    return p.pid


def test_each_fetch_holds_the_lock_of_the_file_it_writes(tmp_path):
    box = []
    session = _Session(client_box=box)
    client = _client(tmp_path, session)
    box.append(client)
    client.submissions(42)
    client.fetch_filing_text(42, "0000000042-24-000001", "a.htm")
    client.fetch_filing_raw(42, "0000000042-24-000002")
    assert session.held == [
        [str(client._cache_path(SUB_URL))],
        [str(tmp_path / "text" / "000000004224000001.txt")],
        [str(tmp_path / "raw" / "000000004224000002.txt")],
    ]


def test_a_second_caller_waits_for_the_first_and_reads_its_answer(tmp_path):
    session = _Session()
    client = _client(tmp_path, session)
    cp = client._cache_path(SUB_URL)
    lock = client._lock_for(str(cp))
    lock.acquire()                                    # a first thread is mid-fetch of this URL
    out = []
    t = threading.Thread(target=lambda: out.append(client.submissions(42)))
    t.start()
    t.join(0.2)
    assert t.is_alive()                               # the second caller waits on the file's lock...
    assert session.calls == []                        # ...without sending a request of its own
    cp.write_text(json.dumps({"name": "First Co", "__fetched__": "2026-09-23"}))   # the first finishes
    lock.release()
    t.join(5)
    assert out == [{"name": "First Co", "__fetched__": "2026-09-23"}]
    assert session.calls == []


def test_an_interrupted_write_leaves_the_old_file_whole(tmp_path, monkeypatch):
    path = tmp_path / "x.json"
    path.write_text('{"old": 1}')

    def disk_full(src, dst):
        raise OSError("No space left on device")

    monkeypatch.setattr(edgar.os, "replace", disk_full)
    with pytest.raises(OSError):
        edgar._write_atomic(path, '{"new": 2}')
    assert path.read_text() == '{"old": 1}'
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]      # no temp file left behind


def test_a_write_replaces_the_file_in_one_step(tmp_path):
    path = tmp_path / "x.json"
    edgar._write_atomic(path, '{"new": 2}')
    assert path.read_text() == '{"new": 2}'
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_a_write_reaches_the_disk_before_it_replaces_the_file(tmp_path, monkeypatch):
    events = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        events.append("fsync")
        real_fsync(fd)

    def replace(src, dst):
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(edgar.os, "fsync", fsync)
    monkeypatch.setattr(edgar.os, "replace", replace)
    edgar._write_atomic(tmp_path / "x.json", "{}")
    assert events[:2] == ["fsync", "replace"]


def test_temp_files_left_by_a_killed_process_are_removed_at_start(tmp_path):
    (tmp_path / "text").mkdir()
    dead = tmp_path / "text" / f".a.txt.{_dead_pid()}.1.tmp"
    live = tmp_path / f".b.json.{os.getpid()}.1.tmp"          # this process: it may still be writing it
    other = tmp_path / ".c.json.tmp"                          # not a _write_atomic name
    for p in (dead, live, other):
        p.write_text("x")
    EdgarClient(cache_dir=tmp_path, user_agent=UA)
    assert not dead.exists() and live.exists() and other.exists()


def test_each_thread_gets_its_own_session(tmp_path):
    client = EdgarClient(cache_dir=tmp_path, user_agent=UA)
    mine = client.session
    assert client.session is mine and isinstance(mine, requests.Session)
    theirs = []
    t = threading.Thread(target=lambda: theirs.append(client.session))
    t.start()
    t.join(5)
    assert theirs[0] is not mine and isinstance(theirs[0], requests.Session)
    assert "Host" not in mine.headers                  # no session-wide Host: every request names its own


def test_an_injected_session_is_shared_by_every_thread(tmp_path):
    session = _Session()
    client = _client(tmp_path, session)
    theirs = []
    t = threading.Thread(target=lambda: theirs.append(client.session))
    t.start()
    t.join(5)
    assert client.session is session and theirs == [session]


def test_every_request_names_its_own_host_and_the_user_agent(tmp_path):
    session = _Session()
    client = _client(tmp_path, session)
    client.submissions(42)
    client.fetch_filing_text(42, "0000000042-24-000001", "a.htm")
    client.fetch_filing_raw(42, "0000000042-24-000002")
    client.company_search_atom("X CO")
    client.full_text_search("X", "8-K", date(2020, 1, 1), date(2020, 2, 1))
    assert [h["Host"] for _, h in session.seen] == [
        "data.sec.gov", "www.sec.gov", "www.sec.gov", "www.sec.gov", "efts.sec.gov"]
    assert {h["User-Agent"] for _, h in session.seen} == {UA}


def test_a_failed_filing_text_request_pauses_every_thread(tmp_path, monkeypatch):
    pauses = []

    class _Probe:
        def acquire(self):
            pass

        def pause(self, seconds):
            pauses.append(seconds)

    monkeypatch.setattr(edgar, "SEC_LIMITER", _Probe())
    client = _client(tmp_path, _Session(status=503))
    assert client.fetch_filing_text(42, "0000000042-24-000001", "a.htm") == ""
    assert pauses == [edgar.RETRY_BACKOFF[0]]


def test_a_prefetch_thread_fills_a_missing_copy_but_never_replaces_one(tmp_path):
    session = _Session()
    client = _client(tmp_path, session)
    cp = client._cache_path(SUB_URL)
    old = {"name": "Old Co", "__fetched__": "2020-01-01"}
    cp.write_text(json.dumps(old))
    with fill_only():
        assert client.submissions(42, fresh_after=date(2026, 9, 1)) == old   # older than asked: kept as is
        client.submissions(43)                                              # missing: filled
    assert json.loads(cp.read_text()) == old
    assert session.calls == ["https://data.sec.gov/submissions/CIK0000000043.json"]
    assert client.submissions(42, fresh_after=date(2026, 9, 1))["name"] == "Co"   # outside: refreshed


def test_fill_only_applies_to_the_calling_thread_alone():
    seen = []
    with fill_only():
        t = threading.Thread(target=lambda: seen.append(filling_only()))
        t.start()
        t.join(5)
        assert filling_only() is True
    assert seen == [False] and filling_only() is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_edgar_threads.py -q`
Expected: collection error `ImportError: cannot import name 'fill_only' from 'delist_detection.edgar'`.

- [ ] **Step 3: Implement the module functions**

In `src/delist_detection/edgar.py`, add after `_fetched_on`:

```python
def _fsync_dir(directory: Path) -> None:
    """Make a rename in `directory` durable. Best effort: some filesystems refuse
    to fsync a directory."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_atomic(path: Path, text: str) -> None:
    """Replace `path` with `text` in one step: a reader -- in this process or
    another -- sees the old file or the complete new one, never a part. The temp
    file sits in the same directory (os.replace is atomic only within one
    filesystem) and carries the process and thread id, so two writers never
    share one and `clean_orphan_temps` can tell a dead writer's leftover from a
    live one's. The data is fsynced before the rename and the directory after
    it, so the new file also survives a power loss."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    _fsync_dir(path.parent)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:              # EPERM: the process exists but belongs to another user
        return True
    return True


def clean_orphan_temps(directory: Path) -> None:
    """Delete the `_write_atomic` temp files (`.<name>.<pid>.<thread>.tmp`) in
    `directory` whose writing process has exited: it was killed mid-write. A
    live process's temp file is left alone, since it may still be writing it."""
    if not directory.is_dir():
        return
    for p in directory.glob(".*.tmp"):
        parts = p.name[1:-len(".tmp")].rsplit(".", 2)
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit() and not _pid_alive(int(parts[1])):
            p.unlink(missing_ok=True)


_FILL_ONLY = threading.local()


@contextmanager
def fill_only():
    """On the calling thread, EDGAR reads fill missing cache entries but never
    replace an existing one: a copy older than the caller's `fresh_after`, or an
    expired search answer, is returned as it is, with no request.
    `prefetch.warm` runs every task inside this. A warm pass therefore only adds
    answers the sequential pass would fetch the same way itself, and every
    refresh happens in the sequential pass, in its own order, exactly as in a
    one-thread run (spec §11: same inputs and caches -> byte-identical CSVs)."""
    prev = getattr(_FILL_ONLY, "on", False)
    _FILL_ONLY.on = True
    try:
        yield
    finally:
        _FILL_ONLY.on = prev


def filling_only() -> bool:
    """True inside `fill_only()` on this thread."""
    return getattr(_FILL_ONLY, "on", False)
```

- [ ] **Step 4: Implement the client**

Replace `EdgarClient.__init__` with the code below, and add the `session` property, `_headers`, `_get` and `_lock_for` right after it:

```python
    def __init__(
        self,
        cache_dir: str | Path,
        user_agent: str | None = None,
        session: requests.Session | None = None,
        sleep=time.sleep,
    ) -> None:
        """`session`: one HTTP session for every thread (tests inject a fake);
        without it each thread gets its own `requests.Session`."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or resolve_user_agent()
        self._session = session
        self._local = threading.local()
        self.sleep = sleep
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        for d in (self.cache_dir, self.cache_dir / "text", self.cache_dir / "raw"):
            clean_orphan_temps(d)

    @property
    def session(self) -> requests.Session:
        """The calling thread's HTTP session (requests.Session is not thread-safe:
        its cookie jar changes with every answer), or the session injected at
        construction, which every thread shares."""
        if self._session is not None:
            return self._session
        s = getattr(self._local, "session", None)
        if s is None:
            s = self._local.session = requests.Session()
        return s

    def _headers(self, host: str, accept: str) -> dict[str, str]:
        """Every request's headers, built per call: no session-wide default can
        send a wrong Host."""
        return {"User-Agent": self.user_agent, "Accept": accept, "Host": host}

    def _get(self, url: str, *, host: str, accept: str, retry: bool = True):
        """GET `url` on this thread's session, through the shared limiter, with this
        request's own headers. With `retry`, through `retry_request`: a transport
        error or a 5xx is retried with backoff, every thread pausing with it, and
        a 403/429 raises EdgarBlocked at once. Without it, one attempt, and a 5xx
        or a transport error still pauses every thread for the first backoff."""
        headers = self._headers(host, accept)
        session = self.session

        def make():
            _throttle()
            return session.get(url, headers=headers, timeout=30)

        if retry:
            return retry_request(make, sleep=self.sleep)
        try:
            resp = make()
        except requests.RequestException:
            SEC_LIMITER.pause(RETRY_BACKOFF[0])
            raise
        if resp.status_code >= 500:
            SEC_LIMITER.pause(RETRY_BACKOFF[0])
        return resp

    def _lock_for(self, key: str) -> threading.Lock:
        """The lock of one cache file (`key` = its path). Whoever holds it is the
        only thread checking, fetching or writing that file, so two threads
        needing the same answer make one request: the second waits, then reads
        what the first wrote. No method holds two of these at once."""
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = threading.Lock()
            return lock
```

Replace `_get_json`:

```python
    def _get_json(self, url: str, *, refresh: bool = False, fresh_after: date | None = None) -> Any:
        """The cached payload, unless `refresh` or it was fetched before `fresh_after`.

        When a refetch fails and a cached dict exists, that copy is returned with
        STALE_KEY added to the returned dict only. "Fails" deliberately covers a
        5xx as well as a transport error: `raise_for_status` raises
        `requests.HTTPError`, which is a `requests.RequestException`, so an SEC
        outage serves the cache instead of erroring the row out. `EdgarBlocked`
        (403/429) is a `RuntimeError` and still propagates, as does any failure
        with no cached copy to fall back on.

        One thread at a time per cache file (`_lock_for`): a second caller for
        the same URL waits, then reads what the first wrote. On a prefetch thread
        (`fill_only`) a cached copy is returned whatever its age.
        """
        cp = self._cache_path(url)
        with self._lock_for(str(cp)):
            cached: Any = None
            if cp.exists() and not refresh:
                try:
                    cached = json.loads(cp.read_text())
                except json.JSONDecodeError:
                    cp.unlink(missing_ok=True)
                else:
                    if fresh_after is None or filling_only() or _fetched_on(cp, cached) >= fresh_after:
                        return cached
            host = "data.sec.gov" if url.startswith(SEC_HOST) else "www.sec.gov"
            try:
                resp = self._get(url, host=host, accept="application/json")   # EdgarBlocked propagates
                if resp.status_code != 404:
                    resp.raise_for_status()
            except requests.RequestException:
                # A failed refresh must not turn a company with a usable cached copy
                # into an error row -- every event newer than SUBMISSIONS_FRESH_DAYS
                # refetches on every run. Serve the cache, marked stale in the
                # returned dict only, so callers can flag the row.
                if not isinstance(cached, dict):
                    raise
                return {**cached, STALE_KEY: True}
            today = date.today().isoformat()
            if resp.status_code == 404:
                data = {"__not_found__": True, "url": url, FETCHED_KEY: today}
                _write_atomic(cp, json.dumps(data))
                return data
            try:
                data = resp.json()
            except json.JSONDecodeError:
                data = {"__raw__": resp.text, "url": url}
            if isinstance(data, dict):
                data[FETCHED_KEY] = today
            _write_atomic(cp, json.dumps(data))
            return data
```

In `company_search_atom`, replace

```python
        _throttle()
        try:
            resp = self.session.get(
                url,
                headers={**self.session.headers, "Host": "www.sec.gov", "Accept": "application/atom+xml,text/xml"},
                timeout=30,
            )
            check_response(resp)          # EdgarBlocked is not a RequestException: it propagates
```

with

```python
        try:
            resp = self._get(url, host="www.sec.gov", accept="application/atom+xml,text/xml", retry=False)
            check_response(resp)          # EdgarBlocked is not a RequestException: it propagates
```

and replace `cp.write_text(json.dumps({"hits": out, FETCHED_KEY: date.today().isoformat()}))` with `_write_atomic(cp, json.dumps({"hits": out, FETCHED_KEY: date.today().isoformat()}))`.

Replace `fetch_filing_text` from `acc_nodash = accession.replace("-", "")` to the end of the method. The docstring and the `primary_doc` guard stay.

```python
        acc_nodash = accession.replace("-", "")
        text_dir = self.cache_dir / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        cp = text_dir / f"{acc_nodash}.txt"
        with self._lock_for(str(cp)):
            if cp.exists():
                return cp.read_text(encoding="utf-8")
            url = f"{WWW_SEC_HOST}/Archives/edgar/data/{int(cik)}/{acc_nodash}/{primary_doc}"
            try:
                resp = self._get(url, host="www.sec.gov", accept="text/html,*/*", retry=False)
            except requests.RequestException:
                return ""
            check_response(resp)
            if resp.status_code != 200:
                # Only a 404 is a stable "not found" worth caching as a sticky miss.
                # Caching other non-200s (429/503/etc.) would turn a transient outage
                # into a permanent empty result, so leave the cache untouched (FIX 6).
                if resp.status_code == 404:
                    _write_atomic(cp, "")
                return ""
            text = _strip_html(resp.text)
            _write_atomic(cp, text)
            return text
```

Replace `fetch_filing_raw`'s body after its docstring:

```python
        acc_nodash = accession.replace("-", "")
        raw_dir = self.cache_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        cp = raw_dir / f"{acc_nodash}.txt"
        with self._lock_for(str(cp)):
            if cp.exists():
                return cp.read_text(encoding="utf-8", errors="replace")
            url = f"{WWW_SEC_HOST}/Archives/edgar/data/{int(cik)}/{acc_nodash}/{accession}.txt"
            try:
                resp = self._get(url, host="www.sec.gov", accept="text/plain,*/*")   # EdgarBlocked propagates
            except requests.RequestException:
                return ""
            if resp.status_code != 200:
                if resp.status_code == 404:
                    _write_atomic(cp, "")
                return ""
            _write_atomic(cp, resp.text)
            return resp.text
```

In `full_text_search`, replace

```python
        def make():
            _throttle()
            return self.session.get(
                url,
                headers={**self.session.headers, "Host": "efts.sec.gov", "Accept": "application/json"},
                timeout=30,
            )

        try:
            resp = retry_request(make, sleep=self.sleep)   # EdgarBlocked propagates, not retried
        except requests.RequestException:
            return []
```

with

```python
        try:
            resp = self._get(url, host="efts.sec.gov", accept="application/json")   # EdgarBlocked propagates
        except requests.RequestException:
            return []
```

and replace `cp.write_text(json.dumps(hits))` with `_write_atomic(cp, json.dumps(hits))`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_edgar_threads.py tests/test_edgar_filing_text.py tests/test_edgar_submissions_fresh.py tests/test_edgar_blocked.py tests/test_edgar_user_agent.py tests/test_sec_http.py tests/test_resolver_cache.py tests/test_edgar_company_search_fresh.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/edgar.py tests/test_edgar_threads.py
```

```bash
git commit -m "perf(edgar): a session per thread, one lock and one durable atomic write per cache file, fill-only reads for prefetch

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/edgar.py tests/test_edgar_threads.py
```

---

### Task 4: One run date and request accounting

**Files:**
- Modify: `src/delist_detection/edgar.py`:
  - imports: `from collections import Counter, defaultdict`;
  - `submissions_fresh_after` (`:69-72`);
  - new `_endpoint`, `StatsMark`, `RequestStats` and `SEC_STATS`, after `_throttle`;
  - `EdgarClient.__init__`, a new `today` property, and `_get`, `_get_json`, `fetch_filing_text` and `fetch_filing_raw` (Task 3 code);
  - `company_search_atom` and `full_text_search`: their `date.today()` calls.
- Modify: `src/delist_detection/sec_http.py`: `_get` (`:19-27`).
- Modify: `src/delist_detection/ticker_resolver.py`: the datetime import (`:14`), `__init__` (`:49-73`), `_submissions` (`:111-117`).
- Modify: `src/delist_detection/classifier.py`: `DelistClassifier.__init__` (`:159-169`) and the `submissions_fresh_after(observed)` call (`:570`).
- Modify: `src/delist_detection/nasdaq_halts.py`: `NasdaqHaltClient.__init__` and `halts_on`'s `date.today()`.
- Test: create `tests/test_run_date.py` and `tests/test_request_stats.py`; append to `tests/test_nasdaq_halts.py`.

**Interfaces:**
- Consumes: `EdgarClient._get` (Task 3).
- Produces:
  - Run date:
    - `edgar.submissions_fresh_after(on: date, today: date | None = None) -> date`, which is `min(on + 45, today or date.today())`.
    - `EdgarClient(..., *, today: date | None = None)` and the property `EdgarClient.today -> date`: the injected date, else `date.today()` at each use.
    - `TickerResolver(..., today: date | None = None)` and `.today`.
    - `DelistClassifier(..., *, today: date | None = None)` and `.today`.
    - `NasdaqHaltClient(..., today: date | None = None)` and `.today`.
  - Accounting:
    - `edgar._endpoint(url: str) -> str`, one of `full_text_search`, `company_search`, `submissions`, `submissions_page`, `archives`, `company_tickers`, `sec_data`.
    - `edgar.RequestStats` with `.add(key)`, `.timing(endpoint, seconds)`, `.degraded(what)`, `.thread_degraded() -> int`, `.snapshot() -> StatsMark` and `.since(mark) -> tuple[dict[str, int], dict[str, list[float]]]`.
    - `edgar.SEC_STATS: RequestStats`.
    - Count keys: `request:<endpoint>`, `cache:<endpoint>`, `degraded:stale_copy`, `degraded:failed_request`. Tasks 5 and 7 add `rejected:full_text_search` and `not_covered:full_text_search`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_run_date.py
"""One run date for the whole run: the EDGAR client's fetch stamps, the
submissions freshness of the resolver and the classifier, and the halt feed's
cache rule all use the date they were given, not the clock."""
import json
from datetime import date

import requests

from delist_detection.classifier import DelistClassifier
from delist_detection.edgar import FETCHED_KEY, EdgarClient, submissions_fresh_after
from delist_detection.ticker_resolver import TickerResolver

AS_OF = date(2026, 9, 23)
UA = "Test Co test@example.com"
SUB_URL = "https://data.sec.gov/submissions/CIK0000000042.json"


class _Resp:
    status_code, text, url = 200, '{"name": "Co"}', "u"

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        pass


class _Session:
    def get(self, url, headers=None, timeout=None):
        return _Resp()


class _Recording:
    """Wraps FakeEdgar; records the fresh_after of every submissions read."""

    def __init__(self, inner):
        self.inner, self.fresh = inner, []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def submissions(self, cik, fresh_after=None):
        self.fresh.append(fresh_after)
        return self.inner.submissions(cik)


def test_the_submissions_freshness_is_bounded_by_the_run_date():
    assert submissions_fresh_after(date(2026, 9, 1), date(2026, 9, 23)) == date(2026, 9, 23)
    assert submissions_fresh_after(date(2018, 11, 28), date(2026, 9, 23)) == date(2019, 1, 12)
    assert submissions_fresh_after(date(2026, 9, 1)) == min(date(2026, 10, 16), date.today())


def test_a_client_stamps_its_run_date_not_the_clock(tmp_path):
    client = EdgarClient(cache_dir=tmp_path, user_agent=UA, session=_Session(), today=AS_OF)
    assert client.today == AS_OF
    client.submissions(42)
    assert json.loads(client._cache_path(SUB_URL).read_text())[FETCHED_KEY] == "2026-09-23"
    assert EdgarClient(cache_dir=tmp_path, user_agent=UA).today == date.today()


def test_the_resolver_reads_submissions_fresh_as_of_its_run_date(fake_edgar):
    e = _Recording(fake_edgar)
    r = TickerResolver(e, today=date(2023, 6, 1))
    r._submissions(999001, "2023-05-10")
    assert e.fresh == [date(2023, 6, 1)]              # min(2023-06-24, the run date)


def test_the_classifier_reads_submissions_fresh_as_of_its_run_date(fake_edgar):
    e = _Recording(fake_edgar)
    c = DelistClassifier(e, TickerResolver(e, today=date(2023, 6, 1)), today=date(2023, 6, 1))
    c.classify_event(ticker="BAD", cik=999001, anchor_date="2023-05-10")
    assert e.fresh[0] == date(2023, 6, 1)
```

```python
# tests/test_request_stats.py
"""edgar.SEC_STATS: requests sent and answers read from cache per EDGAR
endpoint, latency, and degraded answers (a stale copy served, a request that
failed), counted across threads and, for degraded answers, on the calling
thread alone."""
import json
import threading
from datetime import date

import pytest
import requests

from delist_detection import sec_http
from delist_detection.edgar import SEC_STATS, STALE_KEY, EdgarClient, FETCHED_KEY, _endpoint

UA = "Test Co test@example.com"
SUB_URL = "https://data.sec.gov/submissions/CIK0000000042.json"


class _Resp:
    def __init__(self, status=200, text='{"name": "Co"}', content=b"zip"):
        self.status_code, self.text, self.content, self.url = status, text, content, "u"

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    def __init__(self, status=200):
        self.status = status

    def get(self, url, headers=None, timeout=None):
        return _Resp(self.status)


def _client(tmp_path, status=200):
    return EdgarClient(cache_dir=tmp_path, user_agent=UA, session=_Session(status), sleep=lambda _: None,
                       today=date(2026, 9, 23))


@pytest.mark.parametrize("url, endpoint", [
    ("https://efts.sec.gov/LATEST/search-index?q=%22X%22", "full_text_search"),
    ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=X", "company_search"),
    ("https://data.sec.gov/submissions/CIK0000000042.json", "submissions"),
    ("https://data.sec.gov/submissions/CIK0000000042-submissions-001.json", "submissions_page"),
    ("https://www.sec.gov/Archives/edgar/data/42/000000004224000001/a.htm", "archives"),
    ("https://www.sec.gov/files/company_tickers.json", "company_tickers"),
    ("https://www.sec.gov/files/data/fails-deliver-data/cnsfails202401a.zip", "sec_data"),
])
def test_each_url_is_counted_under_its_endpoint(url, endpoint):
    assert _endpoint(url) == endpoint


def test_requests_and_cache_answers_are_counted_per_endpoint(tmp_path):
    client = _client(tmp_path)
    mark = SEC_STATS.snapshot()
    client.submissions(42)
    client.submissions(42)
    client.fetch_filing_raw(42, "0000000042-24-000002")
    client.fetch_filing_raw(42, "0000000042-24-000002")
    counts, timings = SEC_STATS.since(mark)
    assert counts == {"cache:archives": 1, "cache:submissions": 1,
                      "request:archives": 1, "request:submissions": 1}
    assert sorted(timings) == ["archives", "submissions"]
    assert all(len(v) == 1 and v[0] >= 0 for v in timings.values())


def test_a_stale_copy_counts_as_degraded_on_the_calling_thread_only(tmp_path):
    client = _client(tmp_path, status=503)
    client._cache_path(SUB_URL).write_text(json.dumps({"name": "Co", FETCHED_KEY: "2026-01-01"}))
    mark, mine = SEC_STATS.snapshot(), SEC_STATS.thread_degraded()
    assert client.submissions(42, fresh_after=date(2026, 9, 1))[STALE_KEY] is True
    other = []
    t = threading.Thread(target=lambda: other.append(SEC_STATS.thread_degraded()))
    t.start()
    t.join(5)
    assert SEC_STATS.since(mark)[0]["degraded:stale_copy"] == 1
    assert SEC_STATS.thread_degraded() == mine + 1 and other == [0]


def test_a_failed_filing_text_request_counts_as_degraded(tmp_path):
    client = _client(tmp_path, status=500)
    mark = SEC_STATS.snapshot()
    assert client.fetch_filing_text(42, "0000000042-24-000001", "a.htm") == ""
    assert SEC_STATS.since(mark)[0]["degraded:failed_request"] == 1


def test_a_sec_data_download_is_counted(tmp_path):
    mark = SEC_STATS.snapshot()
    sec_http.download("https://www.sec.gov/f.zip", tmp_path / "f.zip", session=_Session(), user_agent=UA)
    assert SEC_STATS.since(mark)[0] == {"request:sec_data": 1}
```

Append to `tests/test_nasdaq_halts.py`:

```python
def test_the_halt_feed_caches_only_days_before_its_run_date(tmp_path):
    c = NasdaqHaltClient(tmp_path, session=_RealFeedSession(), min_interval=0, today=date(2020, 11, 2))
    c.halts_on(date(2020, 11, 2))
    assert not (tmp_path / "20201102.xml").exists()        # the run's own day can still grow
    later = NasdaqHaltClient(tmp_path, session=_RealFeedSession(), min_interval=0, today=date(2020, 11, 3))
    later.halts_on(date(2020, 11, 2))
    assert (tmp_path / "20201102.xml").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_run_date.py tests/test_request_stats.py tests/test_nasdaq_halts.py -q`
Expected: collection errors: `ImportError: cannot import name 'SEC_STATS'`, and `TypeError: EdgarClient.__init__() got an unexpected keyword argument 'today'`.

- [ ] **Step 3: Implement in `edgar.py`**

Add `from collections import Counter, defaultdict` to the imports. Replace `submissions_fresh_after`:

```python
def submissions_fresh_after(on: date, today: date | None = None) -> date:
    """The `fresh_after` for reading a company's submissions about an event on `on`:
    `min(on + 45 days, today)`, where `today` is the run date (default: the clock).
    The classifier and the resolver both use it."""
    return min(on + timedelta(days=SUBMISSIONS_FRESH_DAYS), today or date.today())
```

After `_throttle` (and the Task 2 functions), add:

```python
def _endpoint(url: str) -> str:
    """The EDGAR endpoint a URL belongs to, as run_manifest.json counts requests.
    Everything that is not an EDGAR endpoint (fails-to-deliver and MIDAS ZIPs and
    their index pages) is `sec_data`."""
    if "efts.sec.gov" in url:
        return "full_text_search"
    if "/cgi-bin/browse-edgar" in url:
        return "company_search"
    if "/submissions/CIK" in url and "-submissions-" not in url:
        return "submissions"
    if "/submissions/" in url:
        return "submissions_page"
    if "/Archives/edgar/" in url:
        return "archives"
    if url.endswith("/company_tickers.json"):
        return "company_tickers"
    return "sec_data"


@dataclass(frozen=True)
class StatsMark:
    counts: dict
    timing_lengths: dict


class RequestStats:
    """The counters behind run_manifest.json, shared by every thread of the
    process: requests sent and answers read from cache, per endpoint
    ("request:<endpoint>", "cache:<endpoint>"); answers that rest on a failed
    request or a stale copy ("degraded:<what>"); and each request's latency. A
    run reports the change since a `snapshot()`. `degraded()` also counts on the
    calling thread alone (`thread_degraded()`), so the pipeline can tell which
    era or security a degraded answer served."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter = Counter()
        self._timings: dict[str, list[float]] = defaultdict(list)
        self._local = threading.local()

    def add(self, key: str) -> None:
        with self._lock:
            self._counts[key] += 1

    def timing(self, endpoint: str, seconds: float) -> None:
        with self._lock:
            self._timings[endpoint].append(seconds)

    def degraded(self, what: str) -> None:
        self.add(f"degraded:{what}")
        self._local.degraded = self.thread_degraded() + 1

    def thread_degraded(self) -> int:
        return getattr(self._local, "degraded", 0)

    def snapshot(self) -> StatsMark:
        with self._lock:
            return StatsMark(dict(self._counts), {k: len(v) for k, v in self._timings.items()})

    def since(self, mark: StatsMark) -> tuple[dict[str, int], dict[str, list[float]]]:
        """(counts, latencies in seconds per endpoint) added since `mark`."""
        with self._lock:
            counts = {k: v - mark.counts.get(k, 0) for k, v in self._counts.items()
                      if v != mark.counts.get(k, 0)}
            timings = {k: list(v[mark.timing_lengths.get(k, 0):]) for k, v in self._timings.items()
                       if len(v) > mark.timing_lengths.get(k, 0)}
        return dict(sorted(counts.items())), dict(sorted(timings.items()))


SEC_STATS = RequestStats()
```

Replace `EdgarClient.__init__` (Task 3) with the version below, and add the `today` property after it:

```python
    def __init__(
        self,
        cache_dir: str | Path,
        user_agent: str | None = None,
        session: requests.Session | None = None,
        sleep=time.sleep,
        *,
        today: date | None = None,
    ) -> None:
        """`session`: one HTTP session for every thread (tests inject a fake);
        without it each thread gets its own `requests.Session`. `today`: the run
        date every freshness rule and fetch stamp uses (default: the clock, read at
        each use)."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or resolve_user_agent()
        self._session = session
        self._local = threading.local()
        self.sleep = sleep
        self._today = today
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        for d in (self.cache_dir, self.cache_dir / "text", self.cache_dir / "raw"):
            clean_orphan_temps(d)

    @property
    def today(self) -> date:
        """The run date: the one given at construction, else the clock's."""
        return self._today or date.today()
```

Replace `_get` with:

```python
    def _get(self, url: str, *, host: str, accept: str, retry: bool = True):
        """GET `url` on this thread's session, through the shared limiter, with this
        request's own headers, counted and timed under its endpoint (SEC_STATS).
        With `retry`, through `retry_request`: a transport error or a 5xx is
        retried with backoff, every thread pausing with it, and a 403/429 raises
        EdgarBlocked at once. Without it, one attempt, and a 5xx or a transport
        error still pauses every thread for the first backoff."""
        headers = self._headers(host, accept)
        session = self.session
        endpoint = _endpoint(url)

        def make():
            _throttle()
            SEC_STATS.add(f"request:{endpoint}")
            started = time.monotonic()
            try:
                return session.get(url, headers=headers, timeout=30)
            finally:
                SEC_STATS.timing(endpoint, time.monotonic() - started)

        if retry:
            return retry_request(make, sleep=self.sleep)
        try:
            resp = make()
        except requests.RequestException:
            SEC_LIMITER.pause(RETRY_BACKOFF[0])
            raise
        if resp.status_code >= 500:
            SEC_LIMITER.pause(RETRY_BACKOFF[0])
        return resp
```

In `_get_json` (Task 3), make three changes:

1. Replace
```python
                    if fresh_after is None or filling_only() or _fetched_on(cp, cached) >= fresh_after:
                        return cached
```
with
```python
                    if fresh_after is None or filling_only() or _fetched_on(cp, cached) >= fresh_after:
                        SEC_STATS.add(f"cache:{_endpoint(url)}")
                        return cached
```

2. Replace
```python
                if not isinstance(cached, dict):
                    raise
                return {**cached, STALE_KEY: True}
```
with
```python
                if not isinstance(cached, dict):
                    SEC_STATS.degraded("failed_request")
                    raise
                SEC_STATS.degraded("stale_copy")
                return {**cached, STALE_KEY: True}
```

3. Replace `today = date.today().isoformat()` with `today = self.today.isoformat()`.

In `fetch_filing_text` (Task 3), replace

```python
            if cp.exists():
                return cp.read_text(encoding="utf-8")
```
with
```python
            if cp.exists():
                SEC_STATS.add("cache:archives")
                return cp.read_text(encoding="utf-8")
```

and replace the failure branches

```python
            try:
                resp = self._get(url, host="www.sec.gov", accept="text/html,*/*", retry=False)
            except requests.RequestException:
                return ""
            check_response(resp)
            if resp.status_code != 200:
                # Only a 404 is a stable "not found" worth caching as a sticky miss.
                # Caching other non-200s (429/503/etc.) would turn a transient outage
                # into a permanent empty result, so leave the cache untouched (FIX 6).
                if resp.status_code == 404:
                    _write_atomic(cp, "")
                return ""
```
with
```python
            try:
                resp = self._get(url, host="www.sec.gov", accept="text/html,*/*", retry=False)
            except requests.RequestException:
                SEC_STATS.degraded("failed_request")
                return ""
            check_response(resp)
            if resp.status_code != 200:
                # Only a 404 is a stable "not found" worth caching as a sticky miss.
                # Caching other non-200s (429/503/etc.) would turn a transient outage
                # into a permanent empty result, so leave the cache untouched (FIX 6).
                if resp.status_code == 404:
                    _write_atomic(cp, "")
                else:
                    SEC_STATS.degraded("failed_request")
                return ""
```

In `fetch_filing_raw` (Task 3), replace

```python
            if cp.exists():
                return cp.read_text(encoding="utf-8", errors="replace")
```
with
```python
            if cp.exists():
                SEC_STATS.add("cache:archives")
                return cp.read_text(encoding="utf-8", errors="replace")
```

and replace

```python
            except requests.RequestException:
                return ""
            if resp.status_code != 200:
                if resp.status_code == 404:
                    _write_atomic(cp, "")
                return ""
```
with
```python
            except requests.RequestException:
                SEC_STATS.degraded("failed_request")
                return ""
            if resp.status_code != 200:
                if resp.status_code == 404:
                    _write_atomic(cp, "")
                else:
                    SEC_STATS.degraded("failed_request")
                return ""
```

In `company_search_atom`, replace `fresh_after = date.today() - timedelta(days=COMPANY_SEARCH_FRESH_DAYS)` with `fresh_after = self.today - timedelta(days=COMPANY_SEARCH_FRESH_DAYS)`, and `FETCHED_KEY: date.today().isoformat()` with `FETCHED_KEY: self.today.isoformat()`. In `full_text_search`, replace `if hits and hi < date.today():` with `if hits and hi < self.today:`.

- [ ] **Step 4: Implement in the other modules**

In `src/delist_detection/sec_http.py`, change the import to `from .edgar import SEC_STATS, _throttle, resolve_user_agent, retry_request`, and replace `_get` with:

```python
def _get(url: str, session, user_agent: str | None, timeout: int, *, sleep=time.sleep):
    s = session or requests.Session()
    headers = {"User-Agent": user_agent or resolve_user_agent(), "Accept": "*/*", "Host": "www.sec.gov"}

    def make():
        _throttle()
        SEC_STATS.add("request:sec_data")
        started = time.monotonic()
        try:
            return s.get(url, headers=headers, timeout=timeout)
        finally:
            SEC_STATS.timing("sec_data", time.monotonic() - started)

    return retry_request(make, sleep=sleep)   # EdgarBlocked propagates, not retried
```

In `src/delist_detection/ticker_resolver.py`:
- Change `from datetime import datetime, timedelta` to `from datetime import date, datetime, timedelta`.
- In `__init__`, add the keyword-only parameter `today: date | None = None` after `cik_map`, and, after `self.cik_map = ...`, add:

```python
        self.today = today    # the run date bounding submissions freshness (None: the clock, at each read)
```

- Replace `_submissions`:

```python
    def _submissions(self, cik: int, observed_date: str | None) -> dict:
        """The company's submissions, fetched again when the cached copy predates
        the event window (the same freshness the classifier asks for)."""
        on = parse_day(observed_date)
        if on is None:
            return self.edgar.submissions(cik)
        return self.edgar.submissions(cik, fresh_after=submissions_fresh_after(on, self.today))
```

In `src/delist_detection/classifier.py`, change `DelistClassifier.__init__`'s signature to

```python
    def __init__(
        self,
        edgar: EdgarClient,
        resolver: TickerResolver,
        asset_type_lookup: "callable[..., str | None] | None" = None,
        name_hint_lookup: "callable[..., str | None] | None" = None,
        *,
        today: date | None = None,
    ) -> None:
```

add `self.today = today    # the run date bounding submissions freshness (None: the clock)` as its last line, and change the call at line 570 to:

```python
            sub = self.edgar.submissions(resolution.cik, fresh_after=submissions_fresh_after(observed, self.today))
```

(`classifier.py` already imports `date`: `from datetime import date, datetime, timedelta`.)

In `src/delist_detection/nasdaq_halts.py`, change `NasdaqHaltClient.__init__` to

```python
    def __init__(self, cache_dir: str | Path, *, session=None, min_interval: float = 1.0, sleep=None,
                 today: date | None = None) -> None:
        self.dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self.sleep = sleep or time.sleep
        self.today = today          # the run date: that day's list can still grow (None: the clock)
        self._last = 0.0
```

and replace `if day < date.today():` in `halts_on` with `if day < (self.today or date.today()):`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_run_date.py tests/test_request_stats.py tests/test_nasdaq_halts.py tests/test_edgar_threads.py tests/test_sec_http.py tests/test_edgar_submissions_fresh.py tests/test_resolver_cache.py tests/test_classify_event.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/edgar.py src/delist_detection/sec_http.py src/delist_detection/ticker_resolver.py src/delist_detection/classifier.py src/delist_detection/nasdaq_halts.py tests/test_run_date.py tests/test_request_stats.py tests/test_nasdaq_halts.py
```

```bash
git commit -m "feat(edgar): one injected run date for every freshness rule, and per-endpoint request accounting

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/edgar.py src/delist_detection/sec_http.py src/delist_detection/ticker_resolver.py src/delist_detection/classifier.py src/delist_detection/nasdaq_halts.py tests/test_run_date.py tests/test_request_stats.py tests/test_nasdaq_halts.py
```

---

### Task 5: Full-text-search answers cached with a lag-scaled TTL

**Files:**
- Modify: `src/delist_detection/edgar.py`:
  - imports: add `import logging`, plus `log = logging.getLogger(__name__)` after the imports;
  - new constants, `efts_ttl_days` and `_trim_hits`, after `COMPANY_SEARCH_FRESH_DAYS`;
  - `EdgarClient.__init__`: add `search_cache` and `_run_memo`;
  - new `_efts_cached` and `efts_search`;
  - `full_text_search` rewritten on top of `efts_search`.
- Modify: `tests/test_sec_http.py`: replace `test_full_text_search_does_not_cache_an_empty_answer` (`:233-239`) and `test_full_text_search_does_not_cache_a_window_ending_on_or_after_today` (`:242-257`).
- Test: create `tests/test_edgar_efts_cache.py`.

**Interfaces:**
- Consumes: `_get`, `_lock_for`, `_write_atomic`, `filling_only` (Task 3); `today`, `SEC_STATS` (Task 4).
- Produces:
  - `EdgarClient(..., *, today=None, search_cache: bool = True)`.
  - `EdgarClient.efts_search(url: str, *, window_end: date | None) -> list[dict]`:
    - raises `requests.RequestException` when EDGAR could not answer, and `EdgarBlocked` on 403/429;
    - returns `[]` for a 400/404 and for a window ending before 2001.
  - `EdgarClient._run_memo: dict[str, list]` and `EdgarClient.search_cache: bool`.
  - Constants and helpers:
    - `EFTS_SCHEMA = 1`, `EFTS_KEY = "efts_hits"`;
    - `EFTS_MIN_TTL_DAYS = 7`, `EFTS_MAX_TTL_DAYS = 365`;
    - `EFTS_COVERAGE_START = date(2001, 1, 1)`;
    - `EFTS_SOURCE_KEYS = ("ciks", "display_names", "form", "file_date", "adsh")`;
    - `efts_ttl_days(window_end: date, fetched: date) -> int`;
    - `_trim_hits(hits) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_edgar_efts_cache.py
"""EdgarClient.efts_search: every full-text-search answer, hits or empty, is cached
with its fetch date and holds for efts_ttl_days (the gap from its window's end to
the fetch, kept within [7, 365] days). A window ending before 2001 is never sent,
a 400/404 is a non-answer, and a failure raises and is never cached."""
import json
import logging
from datetime import date, timedelta

import pytest
import requests

from delist_detection.edgar import (EFTS_KEY, EFTS_SCHEMA, FETCHED_KEY, SEC_STATS, EdgarBlocked, EdgarClient,
                                    efts_ttl_days, fill_only)

AS_OF = date(2026, 9, 23)
UA = "Test Co test@example.com"
URL = ("https://efts.sec.gov/LATEST/search-index?q=%22X%22&forms=8-K"
       "&dateRange=custom&startdt=2020-01-01&enddt=2020-02-01")
END = date(2020, 2, 1)
HIT = {"_id": "0000000001-20-000001:x.htm",
       "_source": {"ciks": ["0000000001"], "display_names": ["X CO  (X)  (CIK 0000000001)"],
                   "file_date": "2020-01-15"}}


class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code, self.text, self.url = status, text, URL

    def json(self):
        return json.loads(self.text)


def _answer(*hits):
    return _Resp(text=json.dumps({"hits": {"total": {"value": len(hits)}, "hits": list(hits)}}))


class _Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _client(tmp_path, *responses, today=AS_OF, **kw):
    s = _Session(*responses)
    return EdgarClient(cache_dir=tmp_path, user_agent=UA, session=s, sleep=lambda _: None, today=today, **kw), s


def _saved(client):
    return json.loads(client._cache_path(URL).read_text())


@pytest.mark.parametrize("window_end, days", [
    (date(2020, 2, 1), 365),      # fetched years after its window closed
    (date(2026, 6, 1), 114),      # fetched 114 days after
    (date(2026, 9, 20), 7),       # just closed: the floor
    (date(2026, 12, 1), 7),       # still open: the floor
])
def test_the_ttl_scales_with_how_long_after_the_window_the_answer_was_fetched(window_end, days):
    assert efts_ttl_days(window_end, AS_OF) == days


def test_hits_are_cached_with_their_schema_fetch_date_and_window(tmp_path):
    c, s = _client(tmp_path, _answer(HIT))
    assert c.efts_search(URL, window_end=END) == [HIT]
    assert _saved(c) == {"schema": EFTS_SCHEMA, "window_end": "2020-02-01", FETCHED_KEY: "2026-09-23",
                         EFTS_KEY: [HIT]}
    assert s.calls[0][1]["Host"] == "efts.sec.gov" and s.calls[0][1]["User-Agent"] == UA
    later, s2 = _client(tmp_path)
    assert later.efts_search(URL, window_end=END) == [HIT] and s2.calls == []


def test_an_empty_answer_is_cached_like_a_hit(tmp_path):
    c, _ = _client(tmp_path, _answer())
    assert c.efts_search(URL, window_end=END) == []
    assert _saved(c)[EFTS_KEY] == []
    later, s2 = _client(tmp_path)
    assert later.efts_search(URL, window_end=END) == [] and s2.calls == []


def test_an_answer_is_asked_again_once_its_ttl_has_run_out(tmp_path):
    end = date(2026, 8, 30)
    c, _ = _client(tmp_path, _answer(), today=date(2026, 9, 1))      # 2 days after the window: the 7-day floor
    assert c.efts_search(URL, window_end=end) == []
    inside, s1 = _client(tmp_path, today=date(2026, 9, 7))
    assert inside.efts_search(URL, window_end=end) == [] and s1.calls == []
    after, s2 = _client(tmp_path, _answer(HIT), today=date(2026, 9, 8))
    assert after.efts_search(URL, window_end=end) == [HIT] and len(s2.calls) == 1
    assert _saved(after)[FETCHED_KEY] == "2026-09-08"


def test_a_window_still_open_is_cached_for_the_floor_only(tmp_path):
    open_end = AS_OF + timedelta(days=30)
    c, _ = _client(tmp_path, _answer(HIT))
    assert c.efts_search(URL, window_end=open_end) == [HIT]
    later, s = _client(tmp_path, _answer(HIT), today=AS_OF + timedelta(days=7))
    assert later.efts_search(URL, window_end=open_end) == [HIT] and len(s.calls) == 1


def test_a_prefetch_thread_reads_an_expired_answer_without_asking_again(tmp_path):
    c, _ = _client(tmp_path, _answer(), today=date(2026, 9, 1))
    assert c.efts_search(URL, window_end=date(2026, 8, 30)) == []
    later, s = _client(tmp_path, today=date(2026, 9, 30))              # expired
    with fill_only():
        assert later.efts_search(URL, window_end=date(2026, 8, 30)) == []
    assert s.calls == [] and _saved(later)[FETCHED_KEY] == "2026-09-01"


def test_a_window_before_2001_is_not_covered_and_never_sent(tmp_path):
    c, s = _client(tmp_path)
    mark = SEC_STATS.snapshot()
    assert c.efts_search(URL, window_end=date(2000, 12, 31)) == []
    assert s.calls == [] and not c._cache_path(URL).exists()
    assert SEC_STATS.since(mark)[0] == {"not_covered:full_text_search": 1}


def test_an_undated_search_is_kept_for_the_run_only(tmp_path):
    c, s = _client(tmp_path, _answer(HIT))
    assert c.efts_search(URL, window_end=None) == [HIT]
    assert c.efts_search(URL, window_end=None) == [HIT]
    assert len(s.calls) == 1 and not c._cache_path(URL).exists()
    later, s2 = _client(tmp_path, _answer(HIT))
    assert later.efts_search(URL, window_end=None) == [HIT] and len(s2.calls) == 1


@pytest.mark.parametrize("status", [400, 404])
def test_a_rejected_query_is_a_non_answer_logged_and_never_written(tmp_path, caplog, status):
    c, s = _client(tmp_path, _Resp(status))
    mark = SEC_STATS.snapshot()
    with caplog.at_level(logging.WARNING, logger="delist_detection.edgar"):
        assert c.efts_search(URL, window_end=END) == []
    assert c.efts_search(URL, window_end=END) == []                  # asked once per run
    assert len(s.calls) == 1 and not c._cache_path(URL).exists()
    assert str(status) in caplog.text and URL in caplog.text
    counts = SEC_STATS.since(mark)[0]
    assert counts["rejected:full_text_search"] == 1
    assert not any(k.startswith("degraded:") for k in counts)        # not transient: nothing failed


def test_a_failed_search_raises_is_never_cached_and_is_asked_again(tmp_path):
    c, s = _client(tmp_path, _Resp(500), _Resp(500), _Resp(500), _answer(HIT))
    with pytest.raises(requests.HTTPError):
        c.efts_search(URL, window_end=END)
    assert not c._cache_path(URL).exists()
    assert c.efts_search(URL, window_end=END) == [HIT]               # not remembered as empty
    assert len(s.calls) == 4


def test_a_transport_failure_raises(tmp_path):
    down = requests.ConnectionError("down")
    c, _ = _client(tmp_path, down, down, down)
    with pytest.raises(requests.ConnectionError):
        c.efts_search(URL, window_end=END)
    assert not c._cache_path(URL).exists()


def test_a_body_that_is_not_json_raises(tmp_path):
    c, _ = _client(tmp_path, _Resp(text="<html>maintenance</html>"))
    with pytest.raises(requests.RequestException):
        c.efts_search(URL, window_end=END)
    assert not c._cache_path(URL).exists()


@pytest.mark.parametrize("status", [403, 429])
def test_a_refusal_raises_edgar_blocked_and_writes_nothing(tmp_path, status):
    c, s = _client(tmp_path, _Resp(status))
    with pytest.raises(EdgarBlocked):
        c.efts_search(URL, window_end=END)
    assert len(s.calls) == 1 and not c._cache_path(URL).exists()


def test_hits_keep_their_id_and_only_the_fields_the_library_reads(tmp_path):
    wide = {"_id": "a:b", "_score": 3.1, "_source": {**HIT["_source"], "form": "8-K",
                                                     "adsh": "0000000001-20-000001",
                                                     "biz_locations": ["Boston, MA"], "sics": ["1311"]}}
    c, _ = _client(tmp_path, _answer(wide))
    assert c.efts_search(URL, window_end=END) == [{"_id": "a:b", "_source": {
        "ciks": ["0000000001"], "display_names": ["X CO  (X)  (CIK 0000000001)"], "form": "8-K",
        "file_date": "2020-01-15", "adsh": "0000000001-20-000001"}}]


def test_a_file_of_another_schema_is_asked_again_and_replaced(tmp_path):
    c, s = _client(tmp_path, _answer(HIT))
    c._cache_path(URL).write_text(json.dumps([{"_source": {"ciks": ["9"]}}]))   # the old full_text_search's bare list
    assert c.efts_search(URL, window_end=END) == [HIT]
    assert len(s.calls) == 1 and _saved(c)["schema"] == EFTS_SCHEMA


def test_without_the_search_cache_every_search_is_sent_and_nothing_written(tmp_path):
    c, s = _client(tmp_path, _answer(HIT), _answer(HIT), search_cache=False)
    kept = {"schema": EFTS_SCHEMA, "window_end": "2020-02-01", FETCHED_KEY: "2026-09-23", EFTS_KEY: []}
    c._cache_path(URL).write_text(json.dumps(kept))
    assert c.efts_search(URL, window_end=END) == [HIT]
    assert c.efts_search(URL, window_end=END) == [HIT]
    assert len(s.calls) == 2 and _saved(c) == kept


def test_a_search_holds_its_cache_file_lock(tmp_path):
    held = []

    class _Probe(_Session):
        def get(self, url, headers=None, timeout=None):
            held.append(c._lock_for(str(c._cache_path(url))).locked())
            return super().get(url, headers, timeout)

    c = EdgarClient(cache_dir=tmp_path, user_agent=UA, session=_Probe(_answer(HIT)), today=AS_OF)
    c.efts_search(URL, window_end=END)
    assert held == [True]
```

In `tests/test_sec_http.py`, replace `test_full_text_search_does_not_cache_an_empty_answer` and `test_full_text_search_does_not_cache_a_window_ending_on_or_after_today` with:

```python
def test_full_text_search_caches_an_empty_answer(tmp_path, monkeypatch):
    # An empty answer is written like a hit, with its fetch date; it holds for its TTL.
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    s = _Session(_Resp(text=json.dumps({"hits": {"hits": []}})))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s)
    assert ec.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1)) == []
    (saved,) = tmp_path.glob("*.json")
    assert json.loads(saved.read_text())["efts_hits"] == []
    s2 = _Session()
    later = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s2)
    assert later.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1)) == []
    assert s2.calls == []


def test_full_text_search_holds_an_open_windows_answer_for_seven_days_only(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    hit = {"_source": {"ciks": ["1"], "display_names": ["X CO  (X)  (CIK 0000000001)"]}}
    today = date.today()
    lo = today - timedelta(days=30)
    s = _Session(_Resp(text=json.dumps({"hits": {"hits": [hit]}})))
    assert EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s, today=today).full_text_search(
        '"X CO"', "8-K12B", lo, today) == [hit]
    s2 = _Session()
    assert EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s2,
                       today=today + timedelta(days=6)).full_text_search('"X CO"', "8-K12B", lo, today) == [hit]
    assert s2.calls == []
    s3 = _Session(_Resp(text=json.dumps({"hits": {"hits": []}})))
    assert EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s3,
                       today=today + timedelta(days=7)).full_text_search('"X CO"', "8-K12B", lo, today) == []
    assert len(s3.calls) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_edgar_efts_cache.py tests/test_sec_http.py -q`
Expected: collection error `ImportError: cannot import name 'EFTS_KEY'`.

- [ ] **Step 3: Implement**

In `src/delist_detection/edgar.py`, add `import logging` to the imports and `log = logging.getLogger(__name__)` after them. After `COMPANY_SEARCH_FRESH_DAYS`, add:

```python
# EDGAR full-text search (efts.sec.gov). Every answer, hits or empty, is cached
# under the URL's SHA1 with the day it was fetched, and holds for
# efts_ttl_days(window_end, fetched): the time from the end of its date window to
# the fetch, kept within [EFTS_MIN_TTL_DAYS, EFTS_MAX_TTL_DAYS]. An answer fetched
# soon after its window closed (or while it is open) can still change as EDGAR
# indexes late filings, so it is asked again within a week; one fetched long after
# has settled, but SEC re-indexes, so even it is asked again yearly. EDGAR's
# full-text index starts in 2001: a window ending before EFTS_COVERAGE_START is not
# covered and is never sent.
EFTS_SCHEMA = 1
EFTS_KEY = "efts_hits"
EFTS_MIN_TTL_DAYS, EFTS_MAX_TTL_DAYS = 7, 365
EFTS_COVERAGE_START = date(2001, 1, 1)
# The only `_source` fields a caller reads (resolver: ciks, display_names; successor
# search: file_date too); form and adsh keep a cached answer readable, `_id` names
# the document the review loop curls.
EFTS_SOURCE_KEYS = ("ciks", "display_names", "form", "file_date", "adsh")


def efts_ttl_days(window_end: date, fetched: date) -> int:
    """Days a full-text-search answer fetched on `fetched` holds (see above)."""
    return max(EFTS_MIN_TTL_DAYS, min(EFTS_MAX_TTL_DAYS, (fetched - window_end).days))


def _trim_hits(hits: Any) -> list[dict]:
    """EFTS hits with each `_source` cut to EFTS_SOURCE_KEYS and `_id` kept: the
    same dicts whether an answer comes from the network or the cache."""
    out: list[dict] = []
    for h in hits if isinstance(hits, list) else []:
        if not isinstance(h, dict):
            continue
        src = h.get("_source") if isinstance(h.get("_source"), dict) else {}
        hit: dict = {"_source": {k: src[k] for k in EFTS_SOURCE_KEYS if k in src}}
        if "_id" in h:
            hit = {"_id": h["_id"], **hit}
        out.append(hit)
    return out
```

Replace `EdgarClient.__init__` with this final version:

```python
    def __init__(
        self,
        cache_dir: str | Path,
        user_agent: str | None = None,
        session: requests.Session | None = None,
        sleep=time.sleep,
        *,
        today: date | None = None,
        search_cache: bool = True,
    ) -> None:
        """`session`: one HTTP session for every thread (tests inject a fake);
        without it each thread gets its own `requests.Session`. `today`: the run
        date every freshness rule and fetch stamp uses (default: the clock, read
        at each use). `search_cache=False` neither reads nor writes the
        full-text-search and company-search caches: the golden-fixture builder
        must record live answers."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or resolve_user_agent()
        self._session = session
        self._local = threading.local()
        self.sleep = sleep
        self._today = today
        self.search_cache = search_cache
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        # Answers not written to disk (undated full-text searches, rejected
        # queries), kept for the life of this client -- one run -- so a warm
        # worker and the sequential pass send each one once.
        self._run_memo: dict[str, list] = {}
        for d in (self.cache_dir, self.cache_dir / "text", self.cache_dir / "raw"):
            clean_orphan_temps(d)
```

Add these two methods and replace `full_text_search`:

```python
    def _efts_cached(self, cp: Path, window_end: date, *, any_age: bool = False) -> list[dict] | None:
        """The answer cached at `cp` while it holds (efts_ttl_days), or at any age
        with `any_age` (a prefetch thread, `fill_only`). None when there is no
        file, or a file of another schema; the old full_text_search's bare lists
        count as another schema, except to a prefetch thread, which never
        replaces a file. The caller holds the file's lock."""
        if not cp.exists():
            return None
        try:
            data = json.loads(cp.read_text())
        except json.JSONDecodeError:
            cp.unlink(missing_ok=True)
            return None
        if isinstance(data, list):
            return _trim_hits(data) if any_age else None
        if not isinstance(data, dict) or data.get("schema") != EFTS_SCHEMA or not isinstance(data.get(EFTS_KEY), list):
            return None
        fetched = _fetched_on(cp, data)
        if any_age or self.today < fetched + timedelta(days=efts_ttl_days(window_end, fetched)):
            return data[EFTS_KEY]
        return None

    def efts_search(self, url: str, *, window_end: date | None) -> list[dict]:
        """`hits.hits` of an EDGAR full-text-search URL, each hit's `_source` cut to
        EFTS_SOURCE_KEYS and its `_id` kept. `window_end` is the last filing date
        the query covers (None: the query has no date window).

        Every answer, hits or empty, is written under the URL's SHA1 with its
        schema, window end and fetch date, and holds for efts_ttl_days. A window
        ending before EFTS_COVERAGE_START returns [] with no request (EDGAR's
        index does not cover it). An undated answer is kept in memory for this
        client's run only. A 400 or 404 is a rejected query: logged, counted,
        returned as [], never written, and kept in memory so one run sends it
        once; it is not a failure. A transport error or 5xx after the retries, or
        a body that is not JSON, raises `requests.RequestException`, and nothing
        is cached. A 403/429 raises `EdgarBlocked`, never retried. On a prefetch
        thread (`fill_only`) a cached answer is returned whatever its age.
        """
        if window_end is not None and window_end < EFTS_COVERAGE_START:
            SEC_STATS.add("not_covered:full_text_search")
            return []
        cp = self._cache_path(url)
        with self._lock_for(str(cp)):
            if self.search_cache:
                memo = self._run_memo.get(url)
                if memo is not None:
                    SEC_STATS.add("cache:full_text_search")
                    return list(memo)
                if window_end is not None:
                    cached = self._efts_cached(cp, window_end, any_age=filling_only())
                    if cached is not None:
                        SEC_STATS.add("cache:full_text_search")
                        return list(cached)
            try:
                resp = self._get(url, host="efts.sec.gov", accept="application/json")   # EdgarBlocked propagates
            except requests.RequestException:
                SEC_STATS.degraded("failed_request")
                raise
            if resp.status_code in (400, 404):
                log.warning("EDGAR full-text search rejected %s (HTTP %d): no answer, not cached",
                            url, resp.status_code)
                SEC_STATS.add("rejected:full_text_search")
                if self.search_cache:
                    self._run_memo[url] = []
                return []
            if resp.status_code != 200:
                SEC_STATS.degraded("failed_request")
                raise requests.HTTPError(f"EDGAR full-text search answered {resp.status_code} for {url}")
            try:
                data = resp.json()
            except ValueError as exc:                      # requests' JSONDecodeError is a ValueError
                SEC_STATS.degraded("failed_request")
                raise requests.RequestException(f"EDGAR full-text search sent no JSON for {url}") from exc
            outer = data.get("hits") if isinstance(data, dict) else None
            hits = _trim_hits(outer.get("hits") if isinstance(outer, dict) else [])
            if self.search_cache:
                if window_end is None:
                    self._run_memo[url] = hits
                else:
                    _write_atomic(cp, json.dumps({"schema": EFTS_SCHEMA, "window_end": window_end.isoformat(),
                                                  FETCHED_KEY: self.today.isoformat(), EFTS_KEY: hits}))
            return list(hits)

    def full_text_search(self, q: str, forms: str, lo: date, hi: date) -> list[dict]:
        """EDGAR full-text search hits (`hits.hits`, trimmed as `efts_search` trims
        them) for `q` within `forms`, filed in `[lo, hi]`, cached as `efts_search`
        caches them. [] when EDGAR could not answer: the successor search then
        leaves `successor_unknown` set. A 403/429 raises `EdgarBlocked`.
        """
        url = (
            "https://efts.sec.gov/LATEST/search-index?"
            f"q={requests.utils.quote(q)}&forms={requests.utils.quote(forms)}"
            f"&dateRange=custom&startdt={lo.isoformat()}&enddt={hi.isoformat()}"
        )
        try:
            return self.efts_search(url, window_end=hi)
        except requests.RequestException:
            return []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_edgar_efts_cache.py tests/test_sec_http.py tests/test_edgar_threads.py tests/test_pipeline.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/edgar.py tests/test_edgar_efts_cache.py tests/test_sec_http.py
```

```bash
git commit -m "perf(edgar): cache every full-text-search answer with a TTL scaled by how long after its window it was fetched

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/edgar.py tests/test_edgar_efts_cache.py tests/test_sec_http.py
```

---

### Task 6: The resolver's full-text searches go through the client

**Files:**
- Modify: `src/delist_detection/ticker_resolver.py`:
  - the edgar import (`:20`);
  - a new `_efts_hits`;
  - `_efts_pre_delist_frequency_ranked` (`:225-278`) and `_efts_lookup` (`:472-555`).
- Modify: `tests/golden.py`, `tests/test_resolver_member_names.py` (`:1`, `:37-47`), `scripts/build_golden_fixtures.py`, `tests/test_build_golden_fixtures.py`.
- Test: create `tests/test_resolver_efts.py`.

**Interfaces:**
- Consumes: `EdgarClient.efts_search(url, *, window_end)` and `EdgarClient(search_cache=False)` (Task 5); `use_machine_wide_limit` (Task 2).
- Produces:
  - `TickerResolver._efts_hits(url: str, window_end: date | None) -> list[dict]`: the seam tests patch instead of `requests.get`.
  - The resolver no longer imports `DEFAULT_UA`, `_throttle` or `check_response`. The query URLs are unchanged, byte for byte.
  - `build_golden_fixtures._client(cache_dir: Path) -> EdgarClient`: the search caches bypassed, every EFTS answer recorded raw.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_resolver_efts.py
"""The resolver's two EDGAR full-text searches go through EdgarClient.efts_search:
the shared rate limit and User-Agent, and the cache."""
import json
from datetime import date

import pytest
import requests

from delist_detection.edgar import EdgarClient
from delist_detection.ticker_resolver import TickerResolver

# Read at import, before conftest's autouse fixture stubs them for each test.
_REAL = {name: getattr(TickerResolver, name) for name in ("_efts_lookup", "_efts_pre_delist_frequency_ranked")}
AS_OF = date(2026, 9, 23)
UA = "Test Co test@example.com"
NAME = "Bad Co.  (NOPE)  (CIK 0000999001)"
HIT = {"_source": {"ciks": ["0000999001"], "display_names": [NAME]}}


class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code, self.text, self.url = status, text, "u"

    def json(self):
        return json.loads(self.text)


class _Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return self.responses.pop(0)


def _answer(*hits):
    return _Resp(text=json.dumps({"hits": {"hits": list(hits)}}))


def _client(tmp_path, session):
    return EdgarClient(cache_dir=tmp_path, user_agent=UA, session=session, sleep=lambda _: None, today=AS_OF)


@pytest.fixture(autouse=True)
def _real_efts_and_no_network(monkeypatch):
    """The real EFTS methods, and a resolver that must never call requests.get itself
    (it did before this change)."""
    for name, method in _REAL.items():
        monkeypatch.setattr(TickerResolver, name, method)

    def refuse(*a, **k):
        raise AssertionError("network: the resolver must ask through its EdgarClient")

    monkeypatch.setattr(requests, "get", refuse)


def test_the_form25_search_goes_through_the_client_and_its_cache(tmp_path):
    s = _Session(_answer(HIT))
    r = TickerResolver(_client(tmp_path, s))
    assert r._efts_lookup("NOPE", "2020-01-02") == (999001, NAME, False)
    assert "startdt=2019-10-04" in s.calls[0] and "enddt=2020-04-01" in s.calls[0]
    assert r._transient is False
    later = TickerResolver(_client(tmp_path, _Session()))                       # a later run
    assert later._efts_lookup("NOPE", "2020-01-02") == (999001, NAME, False)   # read from disk


def test_the_frequency_search_goes_through_the_client_and_its_cache(tmp_path):
    s = _Session(_answer(HIT, HIT))
    r = TickerResolver(_client(tmp_path, s))
    assert r._efts_pre_delist_frequency_ranked("NOPE", "2020-01-02") == [(999001, NAME)]
    assert "startdt=2019-09-04" in s.calls[0] and "enddt=2020-01-01" in s.calls[0]
    later = TickerResolver(_client(tmp_path, _Session()))
    assert later._efts_pre_delist_frequency_ranked("NOPE", "2020-01-02") == [(999001, NAME)]


def test_a_search_edgar_could_not_answer_marks_the_resolve_transient(tmp_path):
    s = _Session(_Resp(503), _Resp(503), _Resp(503))
    r = TickerResolver(_client(tmp_path, s))
    assert r._efts_lookup("NOPE", "2020-01-02") == (None, None, False)
    assert r._transient is True
    assert not list(tmp_path.glob("*.json"))


def test_a_rejected_search_is_not_transient(tmp_path):
    r = TickerResolver(_client(tmp_path, _Session(_Resp(400))))
    assert r._efts_lookup("NOPE", "2020-01-02") == (None, None, False)
    assert r._transient is False


def test_a_search_without_a_date_is_never_written(tmp_path):
    r = TickerResolver(_client(tmp_path, _Session(_answer(HIT))))
    assert r._efts_lookup("NOPE")[0] == 999001
    assert not list(tmp_path.glob("*.json"))


def test_a_window_before_2001_is_never_sent(tmp_path):
    s = _Session()
    r = TickerResolver(_client(tmp_path, s))
    assert r._efts_lookup("NOPE", "1999-06-01") == (None, None, False)
    assert r._efts_pre_delist_frequency_ranked("NOPE", "1999-06-01") == []
    assert s.calls == []
```

Append to `tests/test_build_golden_fixtures.py`:

```python
def test_the_builder_client_bypasses_the_search_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    assert bgf._client(tmp_path).search_cache is False


def test_recording_keeps_each_efts_answer_as_the_fixtures_store_it():
    class _R:
        status_code = 200

        def json(self):
            return {"hits": {"total": {"value": 1}, "hits": [
                {"_id": "a:b", "_score": 1.0, "_source": {"ciks": ["1"], "display_names": ["X"], "sics": ["1"]}}]}}

    bgf._efts_raw.clear()
    get = bgf._recording(lambda url, **kw: _R())
    get("https://efts.sec.gov/LATEST/search-index?q=x", headers={}, timeout=30)
    get("https://data.sec.gov/submissions/CIK0000000001.json", headers={}, timeout=30)
    assert bgf._efts_raw == {"https://efts.sec.gov/LATEST/search-index?q=x": {"hits": {
        "total": {"value": 1}, "hits": [{"_source": {"ciks": ["1"], "display_names": ["X"]}}]}}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_resolver_efts.py tests/test_build_golden_fixtures.py -q`
Expected: FAIL. The resolver still calls module-level `requests.get`, which the autouse fixture refuses (`AssertionError: network: the resolver must ask through its EdgarClient`), and the builder has no attribute `_client`.

- [ ] **Step 3: Implement the resolver change**

In `src/delist_detection/ticker_resolver.py`, change the edgar import to:

```python
from .edgar import EdgarBlocked, EdgarClient, submissions_fresh_after
```

Add this method just before `_efts_pre_delist_frequency_ranked`:

```python
    def _efts_hits(self, url: str, window_end: date | None) -> list[dict]:
        """EFTS `hits.hits` for one of this resolver's queries, sent through the
        EDGAR client: the shared rate limit, the User-Agent, and the cache
        (`EdgarClient.efts_search`). Raises requests.RequestException when EDGAR
        could not answer; the callers then mark this resolve transient."""
        return self.edgar.efts_search(url, window_end=window_end)
```

In `_efts_pre_delist_frequency_ranked`, replace everything from `try:` / `_throttle()` down to `hits = data.get("hits", {}).get("hits", [])` with:

```python
        try:
            hits = self._efts_hits(url, d - timedelta(days=1))
        except requests.RequestException as e:
            self._note_transient(e)
            return []
```

In `_efts_lookup`, replace everything from `ticker_u = ticker.upper()` through `hits = data.get("hits", {}).get("hits", [])` with:

```python
        ticker_u = ticker.upper()
        forms = "25-NSE,25,15-12G,15-12B,15-15D"
        params = [f"q=%22{ticker_u}%22", f"forms={forms}"]
        window_end: date | None = None
        if observed_date:
            try:
                d = datetime.strptime(observed_date, "%Y-%m-%d").date()
                lo = (d - timedelta(days=90)).isoformat()
                hi = (d + timedelta(days=90)).isoformat()
                params += [f"dateRange=custom", f"startdt={lo}", f"enddt={hi}"]
                window_end = d + timedelta(days=90)
            except ValueError:
                pass
        url = "https://efts.sec.gov/LATEST/search-index?" + "&".join(params)
        try:
            hits = self._efts_hits(url, window_end)
        except requests.RequestException as e:
            self._note_transient(e)          # EDGAR did not answer: never save what this resolve reaches
            return None, None, False
```

The rest of both methods (the `token_re` passes and the counting) is unchanged.

- [ ] **Step 4: Point the offline harnesses at the new seam**

In `tests/golden.py`:
- Delete the imports `from types import SimpleNamespace`, `import requests` and `from delist_detection import ticker_resolver`.
- Delete the class `_EftsAnswer`.
- Replace `patch_efts` with:

```python
def patch_efts(monkeypatch, case: GoldenCase) -> None:
    """Run the real EFTS methods over the captured EFTS answers (efts_raw, keyed by
    URL); a URL that was not captured answers with no hits."""
    raw = case.data["efts_raw"]
    for name, method in _REAL_EFTS.items():
        monkeypatch.setattr(TickerResolver, name, method)
    monkeypatch.setattr(TickerResolver, "_efts_hits",
                        lambda self, url, window_end=None: raw.get(url, {"hits": {"hits": []}})["hits"]["hits"])
```

In `tests/test_resolver_member_names.py`:
- Delete `import delist_detection.ticker_resolver as tr`.
- Replace `_real_efts` with:

```python
def _real_efts(monkeypatch, hits):
    """Run the real _efts_lookup over these EFTS hits (no network)."""
    monkeypatch.setattr(TickerResolver, "_efts_lookup", _REAL_EFTS_LOOKUP)
    monkeypatch.setattr(TickerResolver, "_efts_hits", lambda self, url, window_end=None: hits)
```

In `scripts/build_golden_fixtures.py`:
- Change `from delist_detection.edgar import SEC_HOST, EdgarClient` to `from delist_detection.edgar import EFTS_SOURCE_KEYS, SEC_HOST, EdgarClient, use_machine_wide_limit`.
- Delete the local `EFTS_SOURCE_KEYS` constant and its comment line. Keep `EFTS_PREFIX`.
- In the module docstring, replace "the raw answers to the two EFTS queries the resolver issues (`efts_raw`, keyed by URL, which tests/golden.py serves back to the real EFTS methods)" with "the raw answers to the two EFTS queries the resolver issues (`efts_raw`, keyed by URL, which tests/golden.py serves back to the real EFTS methods), recorded from the live answer: the client's search caches are bypassed, so a cached answer can never be frozen into a fixture".
- Replace `_recording` and add `_client` after it:

```python
def _recording(get):
    """Keep every EFTS answer the client's session receives, keyed by URL, with
    `hits.total` and each `_source` cut to EFTS_SOURCE_KEYS: the shape
    tests/golden.py serves back."""
    def wrapped(*args, **kwargs):
        resp = get(*args, **kwargs)
        url = args[0] if args else kwargs.get("url")
        if url.startswith(EFTS_PREFIX) and resp.status_code == 200:
            hits = resp.json().get("hits", {})
            _efts_raw[url] = {"hits": {"total": hits.get("total"), "hits": [
                {"_source": {k: h["_source"][k] for k in EFTS_SOURCE_KEYS if k in h.get("_source", {})}}
                for h in hits.get("hits", [])]}}
        return resp
    return wrapped


def _client(cache_dir: Path) -> EdgarClient:
    """The live EDGAR client of a capture. The search caches are bypassed, so a
    cached answer is never frozen into a fixture; every request is strict; and
    every EFTS answer is recorded as it arrived. Single-threaded: `session` is
    this thread's session."""
    edgar = EdgarClient(cache_dir=cache_dir, search_cache=False)
    edgar.session.get = _recording(_strict(edgar.session.get))
    return edgar
```

- Replace `_refresh_efts` with:

```python
def _refresh_efts(rows, edgar) -> None:
    """Add efts_raw to the existing fixtures; nothing else is fetched or changed."""
    for row in rows:
        t, d = row["ticker"], row["observed_delist_date"]
        path = OUT / f"{t}_{d}.json"
        case = json.loads(path.read_text())
        case["efts_raw"], _, _ = _capture_efts(_resolver(edgar, row), t, d)
        path.write_text(json.dumps(case, indent=1))
        print(f"{t} {d}: {len(case['efts_raw'])} EFTS answers")
```

- In `main()`, replace

```python
    args = p.parse_args()
    requests.get = _recording(_strict(requests.get))   # EFTS calls in ticker_resolver
```

with

```python
    args = p.parse_args()
    use_machine_wide_limit()    # share the 8 requests/s with every other SEC client on this machine
```

- In `main()`, replace the block from `if args.efts_only:` through `edgar.session.get = _strict(edgar.session.get)` with:

```python
    edgar = _client(ROOT / "cache" / "edgar")
    if args.efts_only:
        _refresh_efts(rows, edgar)
        return
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_resolver_efts.py tests/test_resolver_member_names.py tests/test_golden_events.py tests/test_payout_golden.py tests/test_build_golden_fixtures.py tests/test_resolver_cache.py tests/test_edgar_blocked.py -q`
Expected: all pass (all 31 golden cases green).

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/ticker_resolver.py tests/test_resolver_efts.py tests/golden.py tests/test_resolver_member_names.py scripts/build_golden_fixtures.py tests/test_build_golden_fixtures.py
```

```bash
git commit -m "perf(resolver): send its full-text searches through the EDGAR client and its cache; the golden builder records live answers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/ticker_resolver.py tests/test_resolver_efts.py tests/golden.py tests/test_resolver_member_names.py scripts/build_golden_fixtures.py tests/test_build_golden_fixtures.py
```

---

### Task 7: Company-name search: cached empties, retries, raises when unreachable

**Files:**
- Modify: `src/delist_detection/edgar.py`: a new `_parse_company_atom` before `class EdgarClient`, and `company_search_atom` rewritten.
- Modify: `src/delist_detection/ticker_resolver.py`: the edgar import, `_submissions` (Task 4 code), and `_name_search` (`:359-367`).
- Modify: `tests/test_edgar_company_search_fresh.py`, `tests/test_resolver_cache.py`.

**Interfaces:**
- Consumes: `_get`, `_lock_for`, `_write_atomic`, `filling_only` (Task 3); `today`, `SEC_STATS` (Task 4); `search_cache` (Task 5).
- Produces:
  - `EdgarClient.company_search_atom(company, form_type)` keeps its signature. It now:
    - caches every answer, empties included, for `COMPANY_SEARCH_FRESH_DAYS` (7);
    - retries through `retry_request`;
    - serves a cached hit list after a failed refetch with `STALE_KEY` on each hit;
    - raises `requests.RequestException` when there is nothing to fall back on.
  - `TickerResolver._submissions` and `_name_search` set `self._transient = True` on any `STALE_KEY`.

- [ ] **Step 1: Update and add the tests**

In `tests/test_edgar_company_search_fresh.py`:
- Add `import pytest`, and change the edgar import to `from delist_detection.edgar import EdgarClient, FETCHED_KEY, STALE_KEY, WWW_SEC_HOST, fill_only`.
- Replace the module docstring with:

```python
"""EdgarClient.company_search_atom caching: every answer, hits or empty, is cached
with its fetch date and trusted for 7 days; a failed request is retried, then
serves a cached hit list marked stale, and with nothing to fall back on raises --
an unanswered search is not an empty one."""
```

- Change `_client` so retries never wait:

```python
def _client(tmp_path, **session_kw):
    session = _Session(**session_kw)
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    return client, session
```

- Replace `test_an_empty_answer_is_not_written_to_the_cache`, `test_an_error_answer_is_not_written_to_the_cache`, `test_a_transport_failure_is_not_written_to_the_cache`, `test_an_empty_answer_does_not_overwrite_a_stale_cache_and_is_retried_next_call`, `test_a_5xx_during_a_refetch_serves_the_stale_cached_hit`, `test_a_transport_failure_during_a_refetch_serves_the_stale_cached_hit` and `test_a_failed_refetch_without_any_cached_copy_still_returns_empty` with:

```python
class _FailingSession(_Session):
    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        raise requests.ConnectionError("no route to host")


def test_an_empty_answer_is_cached_for_7_days_like_a_hit(tmp_path):
    client, session = _client(tmp_path, text=ATOM_EMPTY)
    cp = client._cache_path(_url())
    assert client.company_search_atom(COMPANY, form_type=FORM) == []
    assert json.loads(cp.read_text()) == {"hits": [], FETCHED_KEY: date.today().isoformat()}
    later, later_session = _client(tmp_path, text=ATOM_HIT)
    assert later.company_search_atom(COMPANY, form_type=FORM) == []          # within 7 days: no request
    assert later_session.calls == []
    cp.write_text(json.dumps({"hits": [], FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}))
    again, again_session = _client(tmp_path, text=ATOM_HIT)
    assert again.company_search_atom(COMPANY, form_type=FORM) == HIT        # expired: asked again
    assert again_session.calls == [_url()]


def test_an_error_answer_is_retried_then_raises_and_is_not_cached(tmp_path):
    client, session = _client(tmp_path, status=500)
    with pytest.raises(requests.HTTPError):
        client.company_search_atom(COMPANY, form_type=FORM)
    assert session.calls == [_url()] * 3
    assert not client._cache_path(_url()).exists()


def test_a_transport_failure_is_retried_then_raises(tmp_path):
    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    with pytest.raises(requests.ConnectionError):
        client.company_search_atom(COMPANY, form_type=FORM)
    assert session.calls == [_url()] * 3
    assert not client._cache_path(_url()).exists()


def test_an_empty_refetch_replaces_a_stale_hit_and_holds_for_7_days(tmp_path):
    client, session = _client(tmp_path, text=ATOM_EMPTY)
    cp = client._cache_path(_url())
    cp.write_text(json.dumps({"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}))
    assert client.company_search_atom(COMPANY, form_type=FORM) == []
    assert json.loads(cp.read_text())["hits"] == []
    assert session.calls == [_url()]


def test_a_5xx_during_a_refetch_serves_the_stale_hit_marked_stale(tmp_path):
    client, session = _client(tmp_path, status=503)
    cp = client._cache_path(_url())
    stale = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}
    cp.write_text(json.dumps(stale))
    assert client.company_search_atom(COMPANY, form_type=FORM) == [{**HIT[0], STALE_KEY: True}]
    assert session.calls == [_url()] * 3
    assert json.loads(cp.read_text()) == stale        # the failure never touches the cache


def test_a_transport_failure_during_a_refetch_serves_the_stale_hit_marked_stale(tmp_path):
    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    cp = client._cache_path(_url())
    stale = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}
    cp.write_text(json.dumps(stale))
    assert client.company_search_atom(COMPANY, form_type=FORM) == [{**HIT[0], STALE_KEY: True}]
    assert json.loads(cp.read_text()) == stale


def test_a_failed_refetch_of_an_expired_empty_answer_raises(tmp_path):
    client, _ = _client(tmp_path, status=503)
    client._cache_path(_url()).write_text(json.dumps(
        {"hits": [], FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}))
    with pytest.raises(requests.HTTPError):
        client.company_search_atom(COMPANY, form_type=FORM)


def test_a_failed_search_without_any_cached_copy_raises(tmp_path):
    client, _ = _client(tmp_path, status=503)
    with pytest.raises(requests.HTTPError):
        client.company_search_atom(COMPANY, form_type=FORM)
    assert not client._cache_path(_url()).exists()


def test_a_prefetch_thread_reads_an_expired_answer_without_asking_again(tmp_path):
    client, session = _client(tmp_path)
    old = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=30)).isoformat()}
    client._cache_path(_url()).write_text(json.dumps(old))
    with fill_only():
        assert client.company_search_atom(COMPANY, form_type=FORM) == HIT
    assert session.calls == [] and json.loads(client._cache_path(_url()).read_text()) == old


def test_without_the_search_cache_nothing_is_read_or_written(tmp_path):
    session = _Session()
    client = EdgarClient(cache_dir=tmp_path, session=session, search_cache=False)
    cp = client._cache_path(_url())
    cp.write_text(json.dumps({"hits": [], FETCHED_KEY: date.today().isoformat()}))
    assert client.company_search_atom(COMPANY, form_type=FORM) == HIT
    assert session.calls == [_url()] and json.loads(cp.read_text())["hits"] == []


def test_a_search_holds_its_cache_file_lock(tmp_path):
    held = []

    class _Probe(_Session):
        def get(self, url, headers=None, timeout=None):
            held.append(client._lock_for(str(client._cache_path(url))).locked())
            return super().get(url, headers, timeout)

    client = EdgarClient(cache_dir=tmp_path, session=_Probe())
    client.company_search_atom(COMPANY, form_type=FORM)
    assert held == [True]
```

In `tests/test_resolver_cache.py`, add `from delist_detection.edgar import STALE_KEY` and append:

```python
class _StaleEdgar:
    """Wraps FakeEdgar; every submissions read is an older copy served because the refetch failed."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def submissions(self, cik, fresh_after=None):
        return {**self.inner.submissions(cik), STALE_KEY: True}


def test_an_answer_read_from_a_stale_copy_is_not_persisted(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    r = TickerResolver(_StaleEdgar(fake_edgar), cache_path=cache)
    assert r.resolve("ALTR", "2025-03-26").cik == 1701732        # used for this run
    assert r._transient is True
    assert not cache.exists() or KEY not in cache.read_text()   # but not saved


class _StaleSearch:
    """Wraps FakeEdgar; the company search answers with a cached hit served after a failed refetch."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def company_search_atom(self, company, form_type="25-NSE"):
        return [{"cik": 999002, "name": "Liquidating Trust", "form": "25-NSE", "filing_date": "2019-11-06",
                 STALE_KEY: True}]


def test_a_name_search_answered_from_a_stale_hit_is_not_persisted(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    r = TickerResolver(_StaleSearch(fake_edgar), cache_path=cache, member_names=_member("Liquidating Trust"))
    res = r.resolve("NOPE", "2019-11-06")
    assert (res.cik, res.source) == (999002, "name_search")
    assert r._transient is True
    assert not cache.exists() or "NOPE|2019-11-06" not in cache.read_text()


class _SearchDown:
    """Wraps FakeEdgar; EDGAR's company search cannot be reached."""

    def __init__(self, inner):
        self.inner, self.searches = inner, 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def company_search_atom(self, company, form_type="25-NSE"):
        self.searches += 1
        raise requests.ConnectionError("no route to host")


def test_a_company_search_that_could_not_be_sent_marks_the_resolve_transient(fake_edgar):
    e = _SearchDown(fake_edgar)
    r = TickerResolver(e, member_names=_member("Nope Holdings Inc"))
    assert r.resolve("NOPE", "2024-01-01").cik is None
    assert e.searches > 0 and r._transient is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_edgar_company_search_fresh.py tests/test_resolver_cache.py -q`
Expected: FAIL. You should see:
- `DID NOT RAISE <class 'requests.exceptions.HTTPError'>`;
- an empty answer not written;
- `session.calls` with one request where three were expected;
- `held == [False]`;
- `r._transient is False` in the two stale tests.

`test_a_company_search_that_could_not_be_sent_marks_the_resolve_transient` already passes, because `_name_search` treats a raised search as transient. It pins the resolver half the client change relies on.

- [ ] **Step 3: Implement**

In `src/delist_detection/edgar.py`, add before `class EdgarClient`:

```python
def _parse_company_atom(text: str) -> list[dict[str, Any]]:
    """The hits of a cgi-bin/browse-edgar ATOM answer: the top company with each of
    its filings, or the company alone when it lists none; [] when no company matched."""
    import re as _re
    ci_cik = _re.search(r"<cik>\s*(\d+)\s*</cik>", text)
    if not ci_cik:
        return []
    ci_name = _re.search(r"<conformed-name>(.*?)</conformed-name>", text)
    company_cik = int(ci_cik.group(1))
    company_name = ci_name.group(1) if ci_name else None
    entries = _re.findall(r"<entry>(.*?)</entry>", text, flags=_re.DOTALL)
    out: list[dict[str, Any]] = []
    for e in entries:
        fd = _re.search(r"<filing-date>(\d{4}-\d{2}-\d{2})</filing-date>", e)
        ft = _re.search(r"<filing-type>([^<]+)</filing-type>", e)
        out.append({"cik": company_cik, "name": company_name,
                    "form": ft.group(1) if ft else "", "filing_date": fd.group(1) if fd else ""})
    if not entries:
        out.append({"cik": company_cik, "name": company_name, "form": "", "filing_date": ""})
    return out
```

Replace `company_search_atom`:

```python
    def company_search_atom(self, company: str, form_type: str = "25-NSE") -> list[dict[str, Any]]:
        """Search EDGAR by company name; return [{cik, name, form, filing_date}, ...].

        Uses the cgi-bin/browse-edgar ATOM endpoint. The ATOM XML has a single
        <company-info> block (top match) and an <entry> per filing; we return the
        top company's CIK with each matching filing.

        Every answer, hits or empty, is cached with the day it was fetched and
        trusted for COMPANY_SEARCH_FRESH_DAYS (7): EDGAR's index can catch up, so
        no answer is kept longer, and the resolver re-derives any miss from these
        answers on every run. The request is retried like every other SEC call.
        If it still fails, a cached hit list, however old, is served with
        STALE_KEY on each hit (the caller must not save what it builds on it);
        with no hits to fall back on it raises `requests.RequestException` -- an
        unanswered search is not an empty one. A 403/429 raises `EdgarBlocked`.
        With `search_cache` off, the disk cache is neither read nor written. On a
        prefetch thread (`fill_only`) a cached answer is returned whatever its age.
        """
        url = (
            f"{WWW_SEC_HOST}/cgi-bin/browse-edgar?action=getcompany"
            f"&company={requests.utils.quote(company)}&type={form_type}"
            "&dateb=&owner=include&count=10&output=atom"
        )
        cp = self._cache_path(url)
        with self._lock_for(str(cp)):
            cached: Any = None
            if self.search_cache and cp.exists():
                try:
                    cached = json.loads(cp.read_text())
                except json.JSONDecodeError:
                    cp.unlink(missing_ok=True)
                    cached = None
                else:
                    fresh_after = self.today - timedelta(days=COMPANY_SEARCH_FRESH_DAYS)
                    if (isinstance(cached, dict) and isinstance(cached.get("hits"), list)
                            and (filling_only() or _fetched_on(cp, cached) >= fresh_after)):
                        SEC_STATS.add("cache:company_search")
                        return list(cached["hits"])
            try:
                resp = self._get(url, host="www.sec.gov", accept="application/atom+xml,text/xml")
                if resp.status_code != 200:
                    raise requests.HTTPError(f"EDGAR company search answered {resp.status_code} for {url}")
            except requests.RequestException:
                hits = cached.get("hits") if isinstance(cached, dict) else None
                if isinstance(hits, list) and hits:
                    SEC_STATS.degraded("stale_copy")
                    return [{**h, STALE_KEY: True} for h in hits]
                SEC_STATS.degraded("failed_request")
                raise
            out = _parse_company_atom(resp.text)
            if self.search_cache:
                _write_atomic(cp, json.dumps({"hits": out, FETCHED_KEY: self.today.isoformat()}))
            return out
```

In `src/delist_detection/ticker_resolver.py`, change the edgar import to `from .edgar import STALE_KEY, EdgarBlocked, EdgarClient, submissions_fresh_after`, and replace `_submissions`:

```python
    def _submissions(self, cik: int, observed_date: str | None) -> dict:
        """The company's submissions, fetched again when the cached copy predates
        the event window (the same freshness the classifier asks for). An older
        copy served because that refetch failed is used, but marks this resolve
        transient: what it leads to is not saved."""
        on = parse_day(observed_date)
        if on is None:
            sub = self.edgar.submissions(cik)
        else:
            sub = self.edgar.submissions(cik, fresh_after=submissions_fresh_after(on, self.today))
        if isinstance(sub, dict) and sub.get(STALE_KEY):
            self._transient = True
        return sub
```

In `_name_search`, replace

```python
                try:
                    hits = self.edgar.company_search_atom(variant, form_type=form)
                except EdgarBlocked:
                    raise
                except Exception as e:
                    self._note_transient(e)
                    hits = []
```

with

```python
                try:
                    hits = self.edgar.company_search_atom(variant, form_type=form)
                except EdgarBlocked:
                    raise
                except Exception as e:
                    self._note_transient(e)
                    hits = []
                if any(isinstance(h, dict) and h.get(STALE_KEY) for h in hits):
                    self._transient = True       # a hit served after a failed refetch: never saved
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_edgar_company_search_fresh.py tests/test_resolver_cache.py tests/test_edgar_blocked.py tests/test_golden_events.py tests/test_resolver_member_names.py tests/test_edgar_threads.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/edgar.py src/delist_detection/ticker_resolver.py tests/test_edgar_company_search_fresh.py tests/test_resolver_cache.py
```

```bash
git commit -m "fix(edgar): cache every company-search answer for 7 days, retry it, and raise when EDGAR cannot answer; stale reads are transient

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/edgar.py src/delist_detection/ticker_resolver.py tests/test_edgar_company_search_fresh.py tests/test_resolver_cache.py
```

---

### Task 8: Resolver: degraded answers are known, memo writes are batched

**Files:**
- Modify: `src/delist_detection/ticker_resolver.py`:
  - the edgar import;
  - `__init__`;
  - `_remember` (`:183-190`), `_persist` (`:192-200`, becomes `flush`);
  - the memo-hit line in `resolve` (`:587-588`);
  - a new `is_degraded`.
- Test: `tests/test_resolver_cache.py` (append).

**Interfaces:**
- Consumes: `_write_atomic`, `clean_orphan_temps` (Task 3).
- Produces:
  - `TickerResolver(..., *, member_names=None, cik_map=None, today=None, batch_writes: bool = False)`.
  - `TickerResolver.batch_writes: bool`.
  - `TickerResolver.flush() -> None`: writes the memo if an answer was added since the last write; a no-op otherwise.
  - `TickerResolver.is_degraded(ticker: str, observed_date: str | None = None) -> bool`.
  - `TickerResolver._degraded: set[str]`.
  - A memo hit sets `_transient` to whether that key is degraded, so a rename built on it inherits it.
  - `_persist` is removed; `flush` replaces it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resolver_cache.py`:

```python
def test_a_degraded_answer_is_known_for_the_run(tmp_path, fake_edgar, monkeypatch):
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (999002, "Liquidating Trust (ALTR)", False))
    monkeypatch.setattr(TickerResolver, "_validate_cik", lambda self, *a, **kw: True)
    r = TickerResolver(_FlakyEdgar(fake_edgar), cache_path=tmp_path / "res.json")
    assert r.resolve("ALTR", "2025-03-26").cik == 999002
    assert r.is_degraded("ALTR", "2025-03-26") is True
    assert r.resolve("BAD", "2023-05-10").cik == 999001
    assert r.is_degraded("BAD", "2023-05-10") is False
    assert r.is_degraded("altr ", "2025-03-26") is True           # the resolver's own key normalisation


def test_a_rename_built_on_a_degraded_answer_is_degraded_and_not_saved(tmp_path, fake_edgar, monkeypatch):
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (999002, "Liquidating Trust (ALTR)", False))
    monkeypatch.setattr(TickerResolver, "_validate_cik", lambda self, *a, **kw: True)
    cache = tmp_path / "res.json"
    r = TickerResolver(_FlakyEdgar(fake_edgar), cache_path=cache, rename_map={"OLDALTR": "ALTR"})
    assert r.resolve("ALTR", "2025-03-26").cik == 999002          # transient: the flaky date check
    assert r.resolve("OLDALTR", "2025-03-26").cik == 999002       # the rename reads that memo entry
    assert r.is_degraded("OLDALTR", "2025-03-26") is True
    assert not cache.exists() or "OLDALTR" not in cache.read_text()


def test_batched_writes_reach_the_file_only_on_flush(tmp_path, fake_edgar, monkeypatch):
    import delist_detection.ticker_resolver as tr
    writes = []
    real = tr._write_atomic

    def recording(path, text):
        writes.append(path)
        real(path, text)

    monkeypatch.setattr(tr, "_write_atomic", recording)
    cache = tmp_path / "res.json"
    r = TickerResolver(fake_edgar, cache_path=cache, batch_writes=True)
    assert r.resolve("ALTR", "2025-03-26").cik == 1701732
    assert r.resolve("BAD", "2023-05-10").cik == 999001
    assert not cache.exists() and writes == []
    r.flush()
    assert set(json.loads(cache.read_text())["entries"]) == {"ALTR|2025-03-26", "BAD|2023-05-10"}
    r.flush()                                                      # nothing new: no rewrite
    assert writes == [cache]


def test_without_batching_every_new_answer_is_written_at_once(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    r = TickerResolver(fake_edgar, cache_path=cache)
    r.resolve("ALTR", "2025-03-26")
    assert "ALTR|2025-03-26" in json.loads(cache.read_text())["entries"]


def test_a_memo_temp_file_left_by_a_killed_process_is_removed(tmp_path, fake_edgar):
    import subprocess
    import sys
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    orphan = tmp_path / f".res.json.{p.pid}.1.tmp"
    orphan.write_text("{")
    TickerResolver(fake_edgar, cache_path=tmp_path / "res.json")
    assert not orphan.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_resolver_cache.py -q`
Expected: FAIL with `AttributeError: 'TickerResolver' object has no attribute 'is_degraded'`, `TypeError: ... unexpected keyword argument 'batch_writes'`, the OLDALTR key found in the cache, and the orphan still present.

- [ ] **Step 3: Implement**

In `src/delist_detection/ticker_resolver.py`, change the edgar import to:

```python
from .edgar import STALE_KEY, EdgarBlocked, EdgarClient, _write_atomic, clean_orphan_temps, submissions_fresh_after
```

Replace `__init__` with:

```python
    def __init__(
        self,
        edgar: EdgarClient,
        rename_map: dict[str, str] | None = None,
        manual_overrides: dict[str, int] | None = None,
        cache_path: Path | str | None = None,
        name_lookup: "callable[..., str | None] | None" = None,
        *,
        member_names: "callable[..., str | None] | None" = None,
        cik_map: "callable[[str, str | None], int | None] | None" = None,
        today: date | None = None,
        batch_writes: bool = False,
    ) -> None:
        """`today`: the run date bounding submissions freshness (None: the clock).
        `batch_writes`: keep new answers in memory until `flush()` (the pipeline
        flushes after each resolving stage and on the way out of a run) instead
        of rewriting the whole memo file for each one."""
        self.edgar = edgar
        self.rename_map = {k.upper(): v.upper() for k, v in (rename_map or {}).items()}
        self.manual_overrides = {k.upper(): int(v) for k, v in (manual_overrides or {}).items()}
        self.cache_path = Path(cache_path) if cache_path else None
        self.name_lookup = name_lookup or (lambda *a, **kw: None)
        self.member_names = member_names or (lambda *a, **kw: None)  # (ticker, date) -> index-member name
        self.cik_map = cik_map or (lambda *a, **kw: None)  # (ticker, date) -> CIK from the caller's universe
        self.today = today
        self.batch_writes = batch_writes
        self._memo: dict[str, TickerResolution] = {}
        self._memo_member: dict[str, str | None] = {}   # key -> member name the answer was checked with
        self._volatile: set[str] = set()   # misses and transient-error answers: this run only
        self._degraded: set[str] = set()   # keys whose answer rests on a failed request or a stale copy
        self._dirty = False                # an answer was added since the memo file was last written
        self._transient = False            # a check in the current resolve() hit a transient error
        if self.cache_path:
            clean_orphan_temps(self.cache_path.parent)
        if self.cache_path and self.cache_path.exists():
            self._load_cache()
        self._companies: dict[str, dict] | None = None
```

Replace `_remember` and `_persist`:

```python
    def _remember(self, key: str, res: TickerResolution, member: str | None) -> None:
        self._memo[key] = res
        self._memo_member[key] = member
        if self._transient:
            self._degraded.add(key)
        else:
            self._degraded.discard(key)
        if res.cik is None or self._transient:   # retried next run, never persisted
            self._volatile.add(key)
            return
        self._volatile.discard(key)
        self._dirty = True
        if not self.batch_writes:
            self.flush()

    def flush(self) -> None:
        """Write the memo file if an answer was added since it was last written
        (atomically: a crash never leaves a torn memo)."""
        if not self._dirty or not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        entries = {k: {**r.__dict__, "member_name": self._memo_member.get(k)}
                   for k, r in self._memo.items() if k not in self._volatile}
        _write_atomic(self.cache_path, json.dumps({"__version__": CACHE_VERSION, "entries": entries}, indent=2))
        self._dirty = False

    def is_degraded(self, ticker: str, observed_date: str | None = None) -> bool:
        """Whether this run's answer for (ticker, date) rests on a failed EDGAR
        request or a stale copy. Such an answer is used for the run and never
        saved; the pipeline flags it `resolution_degraded`."""
        return f"{ticker.upper().strip()}|{observed_date or ''}" in self._degraded
```

In `resolve`, replace

```python
        if cache_key in self._memo and self._memo_member.get(cache_key) == member:
            return self._memo[cache_key]
```

with

```python
        if cache_key in self._memo and self._memo_member.get(cache_key) == member:
            # A rename built on this answer inherits whether it rests on a failed request.
            self._transient = cache_key in self._degraded
            return self._memo[cache_key]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_resolver_cache.py tests/test_edgar_blocked.py tests/test_resolver_cik_map.py tests/test_resolver_member_names.py tests/test_golden_events.py tests/test_pipeline.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/ticker_resolver.py tests/test_resolver_cache.py
```

```bash
git commit -m "feat(resolver): report answers that rest on a failed request or a stale copy, and batch memo writes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/ticker_resolver.py tests/test_resolver_cache.py
```

---

### Task 9: `prefetch.warm` and `Serialized`

**Model:** most capable (thread pool, cancellation, locks).

**Files:**
- Create: `src/delist_detection/prefetch.py`
- Test: create `tests/test_prefetch.py`

**Interfaces:**
- Consumes: `RateLimiter.cancelled_by`, `PrefetchCancelled`, `SEC_LIMITER` (Task 1); `fill_only` (Task 3); `EdgarBlocked`; `OpenFigiBlocked`.
- Produces:
  - `prefetch.warm(items, task, *, workers: int, state: Callable[[], Any] | None = None, limiter: RateLimiter | None = None) -> int`:
    - calls `task(item)`, or `task(state_obj, item)` when `state` is given, inside `limiter.cancelled_by(stop)` and `edgar.fill_only()`;
    - `limiter=None` means `edgar.SEC_LIMITER`, read at call time;
    - returns the number of items handed to the pool, 0 when `workers <= 1`;
    - re-raises the first `EdgarBlocked`/`OpenFigiBlocked`, or a `KeyboardInterrupt`, after stopping every worker.
  - `prefetch.Serialized(obj)`: every callable attribute of `obj` runs under one lock.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prefetch.py
"""prefetch.warm: runs each item's work on worker threads only to fill the caches;
results are thrown away, ordinary failures ignored, every task is fill-only, and a
refusal or an interrupt stops every worker before its next SEC request.
prefetch.Serialized: one call at a time into a client that is not thread-safe."""
import threading
import time

import pytest

from delist_detection import edgar, prefetch
from delist_detection.edgar import EdgarBlocked, PrefetchCancelled, RateLimiter, filling_only
from delist_detection.openfigi import OpenFigiBlocked
from delist_detection.prefetch import Serialized, warm


def _limiter():
    return RateLimiter(1000.0, sleep=lambda s: None)      # never waits in tests


def _requests_until_cancelled(acquire, outcome):
    """A long chain of SEC requests, as a resolver makes; records how it ended."""
    try:
        for _ in range(5000):
            acquire()
            time.sleep(0.001)
        outcome.append("never stopped")
    except PrefetchCancelled:
        outcome.append("cancelled")
        raise


def test_one_worker_warms_nothing():
    calls = []
    assert warm([1, 2, 3], calls.append, workers=1) == 0
    assert calls == []


def test_every_item_is_warmed_once_and_ordinary_failures_are_ignored():
    seen, guard = [], threading.Lock()

    def task(item):
        with guard:
            seen.append(item)
        if item == 2:
            raise ValueError("a parse error the sequential pass will report")

    assert warm([1, 2, 3, 4], task, workers=3, limiter=_limiter()) == 4
    assert sorted(seen) == [1, 2, 3, 4]


def test_every_task_runs_fill_only():
    seen, guard = [], threading.Lock()

    def task(item):
        with guard:
            seen.append(filling_only())

    warm([1, 2, 3], task, workers=2, limiter=_limiter())
    assert seen == [True, True, True] and filling_only() is False


def test_each_worker_gets_its_own_state_object_built_on_the_calling_thread():
    built_on, used, violations = [], [], []

    class _State:
        def __init__(self):
            built_on.append(threading.current_thread().name)
            self.busy = threading.Lock()

    def task(state, item):
        if not state.busy.acquire(blocking=False):
            violations.append(item)            # two threads held one state object
            return
        try:
            used.append(id(state))
            time.sleep(0.01)
        finally:
            state.busy.release()

    warm(range(12), task, workers=3, state=_State, limiter=_limiter())
    assert built_on == [threading.current_thread().name] * 3
    assert violations == [] and len(used) == 12 and len(set(used)) <= 3


@pytest.mark.parametrize("refusal", [EdgarBlocked("SEC returned 403"), OpenFigiBlocked("OpenFIGI returned 401")])
def test_a_refusal_stops_the_pool_and_is_raised(refusal):
    lim = _limiter()
    started, outcome, later = threading.Event(), [], []

    def task(item):
        if item == "refused":
            if started.wait(5):                # the other worker is mid-chain
                raise refusal
            return
        if item == "slow":
            started.set()
            _requests_until_cancelled(lim.acquire, outcome)
            return
        later.append(item)

    with pytest.raises(type(refusal)):
        warm(["slow", "refused", "later1", "later2"], task, workers=2, limiter=lim)
    assert outcome == ["cancelled"]            # its next request after the refusal never went out
    assert later == []                         # no item started after the refusal


def test_the_process_wide_limiter_is_the_default(monkeypatch):
    monkeypatch.setattr(edgar, "SEC_LIMITER", _limiter())
    started, outcome = threading.Event(), []

    def task(item):
        if item == "refused":
            if started.wait(5):
                raise EdgarBlocked("SEC returned 403")
            return
        started.set()
        _requests_until_cancelled(edgar._throttle, outcome)

    with pytest.raises(EdgarBlocked):
        warm(["slow", "refused"], task, workers=2)
    assert outcome == ["cancelled"]


def test_an_interrupt_stops_the_workers_and_is_raised(monkeypatch):
    lim = _limiter()
    started, outcome = threading.Event(), []

    def task(item):
        started.set()
        _requests_until_cancelled(lim.acquire, outcome)

    def ctrl_c(futures, return_when=None):
        started.wait(5)
        raise KeyboardInterrupt

    monkeypatch.setattr(prefetch, "wait", ctrl_c)
    with pytest.raises(KeyboardInterrupt):
        warm(["a", "b"], task, workers=2, limiter=lim)
    assert outcome and set(outcome) == {"cancelled"}


def test_a_serialized_client_runs_one_call_at_a_time():
    active, peak, guard = [0], [0], threading.Lock()

    class _Client:
        label = "midas"

        def last_trade_day(self, x):
            with guard:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.01)
            with guard:
                active[0] -= 1
            return x

    s = Serialized(_Client())
    out, threads = [], [threading.Thread(target=lambda i=i: out.append(s.last_trade_day(i))) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert peak[0] == 1 and sorted(out) == list(range(8)) and s.label == "midas"


def test_a_serialized_call_that_is_cancelled_releases_the_lock():
    class _Client:
        def fetch(self, cancel):
            if cancel:
                raise PrefetchCancelled()
            return "ok"

    s = Serialized(_Client())
    with pytest.raises(PrefetchCancelled):
        s.fetch(True)
    assert s.fetch(False) == "ok"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_prefetch.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'delist_detection.prefetch'`.

- [ ] **Step 3: Implement**

```python
# src/delist_detection/prefetch.py
"""Fill the SEC caches from a thread pool while the pipeline's own logic stays sequential.

Before a sequential stage, `warm` runs that stage's per-item work on worker threads
only for what it fetches. Every request goes through the shared EdgarClient: one
8 requests/s limiter (machine-wide once `edgar.use_machine_wide_limit` has run),
and one lock and one atomic write per cache file. Each task runs under
`edgar.fill_only()`: it may fetch what is missing from the caches but never
refresh what is there, so the sequential pass that follows reads exactly the
copies a one-thread run would read, and refreshes them itself, in its own order.
Results are thrown away, so the tables never depend on thread timing (spec §11:
same inputs and caches -> byte-identical CSVs).
"""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Any

from . import edgar as _edgar
from .edgar import EdgarBlocked, PrefetchCancelled, RateLimiter, fill_only
from .openfigi import OpenFigiBlocked

FATAL = (EdgarBlocked, OpenFigiBlocked)


class Serialized:
    """`obj` behind one lock: each method call runs alone. The warm pass's MIDAS
    and Nasdaq-halt clients keep unlocked state (MidasClient's summary memo and
    fixed-path ZIP download, NasdaqHaltClient's pacing clock), so every warm finder
    shares one Serialized wrapper per client. Attributes that are not callable
    pass through unlocked. The lock is taken before the SEC limiter's and never
    while an EdgarClient file lock is held (MIDAS and the halt feed never touch
    EdgarClient), so it cannot deadlock; an exception, PrefetchCancelled
    included, releases it."""

    def __init__(self, obj: Any) -> None:
        self._obj = obj
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._obj, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            with self._lock:
                return attr(*args, **kwargs)
        return call


def warm(items: Iterable[Any], task: Callable[..., object], *, workers: int,
         state: Callable[[], Any] | None = None, limiter: RateLimiter | None = None) -> int:
    """Run `task(item)` -- or `task(state_obj, item)` when `state` is given -- for
    every item on up to `workers` threads, and return the number of items handed
    to the pool. `limiter` defaults to `edgar.SEC_LIMITER` at call time.

    `state` is called on this thread once per worker; a worker takes one of those
    objects for each item, so an object is never used by two threads at once (a
    shadow resolver, a finder). Every task runs under `edgar.fill_only()`. A task
    that raises an ordinary exception is ignored: the sequential pass meets the
    same failure and records it as it always has. `workers <= 1` warms nothing:
    the sequential pass fetches everything itself, one request at a time.

    A refusal (EdgarBlocked, OpenFigiBlocked) or an interrupt stops the pool: no
    item starts after it, every running worker's next SEC request raises
    PrefetchCancelled instead of going out, and the refusal or interrupt is
    raised here once the workers have stopped. On a first Ctrl-C this function
    waits for the workers; each finishes the one request it has in flight (at
    most the 30 s request timeout). A second Ctrl-C during that wait interrupts
    the wait itself and propagates at once, but the workers are not daemon
    threads, so the interpreter still waits for each one's in-flight request
    before the process exits. Nothing is torn either way: every cache file is
    written atomically, and the tables are written only at the end of a run.
    """
    items = list(items)
    if workers <= 1 or not items:
        return 0
    lim = limiter if limiter is not None else _edgar.SEC_LIMITER
    n = min(workers, len(items))
    states: queue.SimpleQueue = queue.SimpleQueue()
    for _ in range(n):
        states.put(state() if state is not None else None)
    stop = threading.Event()

    def run(item: Any) -> None:
        if stop.is_set():
            return
        obj = states.get()
        try:
            with lim.cancelled_by(stop), fill_only():
                if state is None:
                    task(item)
                else:
                    task(obj, item)
        except PrefetchCancelled:
            pass
        except FATAL:
            stop.set()                     # before this thread can pick up another item
            raise
        except Exception:                  # noqa: BLE001 -- best effort; the sequential pass reports it
            pass
        finally:
            states.put(obj)

    pool = ThreadPoolExecutor(max_workers=n, thread_name_prefix="sec-warm")
    try:
        futures = [pool.submit(run, item) for item in items]
        wait(futures, return_when=FIRST_EXCEPTION)
        for f in futures:                  # submission order: the same refusal wins every time
            if f.done() and not f.cancelled() and f.exception() is not None:
                raise f.exception()
    except BaseException:
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return len(items)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_prefetch.py tests/test_rate_limiter.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/prefetch.py tests/test_prefetch.py
```

```bash
git commit -m "feat(prefetch): warm the SEC caches on a fill-only thread pool that stops at the first refusal

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/prefetch.py tests/test_prefetch.py
```

---

### Task 10: OpenFIGI listing lookups in batches

**Files:**
- Modify: `src/delist_detection/listing_status.py`: the imports, new `listing_job` and `listing_answers`, and `listed_today` (`:76-99`).
- Modify: `src/delist_detection/pipeline.py`: the listing import (`:24`) and the stage-5 loop head and `listed_today` call (`:482`, `:503-504`).
- Test: `tests/test_listing_status.py`, `tests/test_pipeline.py`.

**Interfaces:**
- Consumes: `OpenFigiClient.map(jobs, use_cache=False)`, which already chunks jobs by `max_jobs`.
- Produces:
  - `listing_status.listing_job(sec_id: str) -> dict`.
  - `listing_status.listing_answers(figi, sec_ids: Iterable[str]) -> dict[str, dict]`.
  - `listed_today(figi, sec_id, *, edgar=None, cik=None, tickers=None, answer: dict | None = None)`.
  - Locals in `pipeline._run`'s stage 5, `ordered: list[Security]` and `listing: dict[str, dict]`, which Task 12 uses.

- [ ] **Step 1: Write the failing tests**

In `tests/test_listing_status.py`, extend the `listing_status` import to `from delist_detection.listing_status import (cover_exchanges, exchanges_around, listed_today, listing_answers, withdrawal_kind,)` and append:

```python
from delist_detection.openfigi import OpenFigiBlocked


class _BatchFigi:
    def __init__(self, answers, fail=None):
        self.answers, self.fail, self.calls = answers, fail, []

    def map(self, jobs, use_cache=True):
        self.calls.append(([j["idValue"] for j in jobs], use_cache))
        if self.fail is not None:
            raise self.fail
        return [self.answers.get(j["idValue"], {"warning": "No identifier found."}) for j in jobs]


def test_listing_answers_asks_openfigi_once_for_every_figi():
    figi = _BatchFigi({"BBG1": {"data": [{"exchCode": "UN"}]}})
    got = listing_answers(figi, ["BBG1", "CIK7-COMMON", "BBG2", "BBG1"])
    assert figi.calls == [(["BBG1", "BBG2"], False)]     # one call; no placeholder, no duplicate, no cache
    assert got == {"BBG1": {"data": [{"exchCode": "UN"}]}, "BBG2": {"warning": "No identifier found."}}


def test_a_prefetched_answer_needs_no_openfigi_call():
    assert listed_today(None, "BBG1", answer={"data": [{"exchCode": "UN"}]}) is True
    assert listed_today(None, "BBG1", answer={"error": "x"}) is None
    assert listed_today(None, "BBG1", answer={"warning": "No identifier found."}) is False


def test_a_failed_batch_leaves_each_security_to_ask_alone():
    assert listing_answers(_BatchFigi({}, fail=RuntimeError("figi down")), ["BBG1"]) == {}


def test_a_refused_batch_aborts():
    with pytest.raises(OpenFigiBlocked):
        listing_answers(_BatchFigi({}, fail=OpenFigiBlocked("401")), ["BBG1"])


def test_no_figi_client_or_only_placeholders_asks_nothing():
    figi = _BatchFigi({})
    assert listing_answers(figi, ["CIK1-COMMON"]) == {} and figi.calls == []
    assert listing_answers(None, ["BBG1"]) == {}
```

Append to `tests/test_pipeline.py`:

```python
def test_the_listing_check_asks_openfigi_once_for_all_securities(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    calls = []
    real_map = clients.figi.map

    def recording(jobs, use_cache=True):
        calls.append([(j["idType"], j["idValue"]) for j in jobs])
        return real_map(jobs, use_cache=use_cache)

    clients.figi.map = recording
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    listing_calls = [c for c in calls if c and c[0][0] == "COMPOSITE_ID_BB_GLOBAL"]
    assert listing_calls == [[("COMPOSITE_ID_BB_GLOBAL", "BBG000FJLFX8"),
                              ("COMPOSITE_ID_BB_GLOBAL", "BBG000LIVE01")]]
```

In `tests/test_pipeline.py`'s `test_listed_today_is_asked_with_each_securitys_own_tickers`, change the spy's signature to accept the new keyword:

```python
    def spy(figi, sec_id, *, edgar=None, cik=None, tickers=None, answer=None):
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_listing_status.py tests/test_pipeline.py::test_the_listing_check_asks_openfigi_once_for_all_securities -q`
Expected: collection error `ImportError: cannot import name 'listing_answers'`.

- [ ] **Step 3: Implement**

In `src/delist_detection/listing_status.py`, add `from .openfigi import OpenFigiBlocked` to the imports, and replace `listed_today` with the two helpers and the new `listed_today`:

```python
def listing_job(sec_id: str) -> dict:
    """The OpenFIGI mapping job listed_today asks about `sec_id`."""
    return {"idType": "COMPOSITE_ID_BB_GLOBAL", "idValue": sec_id}


def listing_answers(figi, sec_ids: Iterable[str]) -> dict[str, dict]:
    """OpenFIGI's current answer for each composite FIGI in `sec_ids` (placeholders
    skipped), sent as batched mapping requests (`OpenFigiClient.map` chunks them)
    instead of one request per security. Never cached, as in listed_today.
    OpenFigiBlocked propagates; any other failure returns {}, so each security
    asks on its own, inside its own error handling."""
    ids = [s for s in dict.fromkeys(sec_ids) if not is_placeholder(s)]
    if figi is None or not ids:
        return {}
    try:
        answers = figi.map([listing_job(s) for s in ids], use_cache=False)
    except OpenFigiBlocked:
        raise
    except Exception:          # noqa: BLE001 -- the per-security path reports it
        return {}
    return dict(zip(ids, answers))


def listed_today(figi, sec_id: str, *, edgar=None, cik: int | None = None,
                 tickers: Iterable[str] | None = None, answer: dict | None = None) -> bool | None:
    """Whether the security trades on a US exchange today.

    A composite FIGI needs an exchange venue in OpenFIGI's answer (`answer` when
    listing_answers already fetched it, else asked here). OpenFIGI keeps venue
    rows for a dead line (Celgene, TSS, old Apache still show UW/UN), so when the
    issuer's CIK is known the issuer's EDGAR submissions JSON must also list one
    of the security's `tickers`, or a ticker OpenFIGI returns, on a major
    exchange. With no CIK, OpenFIGI alone decides. A placeholder has no FIGI:
    EDGAR alone decides, on the security's own tickers."""
    if not is_placeholder(sec_id):
        ans = answer if answer is not None else figi.map([listing_job(sec_id)], use_cache=False)[0]
        if "error" in ans:
            return None
        rows = [r for r in ans.get("data") or [] if r.get("exchCode") in EXCHANGE_VENUES]
        if not rows:
            return False
        if edgar is None or cik is None:
            return True
        names = None if tickers is None else [*tickers, *(str(r.get("ticker") or "").replace("/", "-") for r in rows)]
        return edgar_lists(edgar, cik, names)
    if edgar is None or cik is None:
        return None
    return edgar_lists(edgar, cik, tickers)
```

In `src/delist_detection/pipeline.py`:
- Change the import to `from .listing_status import edgar_lists, listed_today, listing_answers`.
- In stage 5, replace

```python
    for i, s in enumerate(sorted(securities.values(), key=lambda s: s.sec_id), 1):
```

with

```python
    ordered = sorted(securities.values(), key=lambda s: s.sec_id)
    # One batched OpenFIGI ask for every security's listing; a failed batch leaves
    # each security to ask alone inside its own try below.
    listing = listing_answers(clients.figi, [s.sec_id for s in ordered])
    for i, s in enumerate(ordered, 1):
```

- Change the `listed_today(...)` call inside the loop's `try` to:

```python
            listed[s.sec_id] = listed_today(clients.figi, s.sec_id, edgar=clients.edgar, cik=s.issuer_cik,
                                            tickers=sorted({e.ticker for e in s.eras}),
                                            answer=listing.get(s.sec_id))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_listing_status.py tests/test_pipeline.py -q`
Expected: all pass. `test_listed_today_error_for_one_security_does_not_abort_the_run` still passes: its batch raises, so each security asks alone and only LIVE gets its `error` row.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/listing_status.py src/delist_detection/pipeline.py tests/test_listing_status.py tests/test_pipeline.py
```

```bash
git commit -m "perf(listing-status): ask OpenFIGI for every security's listing in batched requests

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/listing_status.py src/delist_detection/pipeline.py tests/test_listing_status.py tests/test_pipeline.py
```

---

### Task 11: Pipeline: run date, `--sec-workers`, stage-2 warm pass, stage meter

**Model:** most capable (the first warm pass inside the run, shadow resolvers).

**Files:**
- Modify: `src/delist_detection/ticker_resolver.py`: a new `TickerResolver.shadow()` after `resolve_many`.
- Modify: `src/delist_detection/pipeline.py`:
  - the imports (`:18-34`) and `Clients` (`:39-49`);
  - new `_StageMeter`, `_flush_memo` and the `run` wrapper; the old `run` becomes `_run` (`:418-419`);
  - the `date.today()` calls in stage 1 and stage 4 (`:432`, `:471`);
  - stage 2 (`:443-450`);
  - meter lines in stages 5, 8 and 9;
  - `default_clients` (`:842-873`).
- Modify: `scripts/classify_universe.py`: the imports (`:15`), `build_parser` (`:98-124`) and `main` (`:127-162`).
- Test: `tests/test_resolver_cache.py`, create `tests/test_pipeline_prefetch.py`, and `tests/test_classify_universe_cli.py`.

**Interfaces:**
- Consumes:
  - `warm` (Task 9);
  - `SEC_STATS` (Task 4);
  - `TickerResolver(today=, batch_writes=)`, `flush()` (Tasks 4, 8);
  - `EdgarClient(today=)`, `DelistClassifier(today=)`, `NasdaqHaltClient(today=)` (Task 4);
  - `use_machine_wide_limit`, `require_user_agent`, `EdgarSetupError` (Task 2).
- Produces:
  - `TickerResolver.shadow() -> TickerResolver`.
  - `pipeline.Clients.as_of: date | None = None`.
  - `pipeline.run(..., sec_workers: int = 1)`: flushes the resolver memo on the way out.
  - `pipeline._run(index, clients, overrides, *, out_dir, tol, limit, log, sec_workers)`.
  - `pipeline._StageMeter(log)`, with `.start() -> StatsMark`, `.done(stage: str, mark) -> None` and `.stages: dict[str, dict[str, int]]`.
  - `pipeline._flush_memo(clients) -> None`.
  - `default_clients(..., as_of: date | None = None)`.
  - In `_run`, the locals `as_of`, `meter` and `last_seen: dict[str, str]` (era key to last sighting), which later tasks use.
  - The CLI flag `--sec-workers N` (default `DEFAULT_SEC_WORKERS = 4`, allowed 1..`MAX_SEC_WORKERS = 8`), and a start-up User-Agent and lock-file check that exits 2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resolver_cache.py`:

```python
def test_a_shadow_starts_from_its_resolver_memo_and_saves_nothing(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    e = _RecordingEdgar(fake_edgar)
    r = TickerResolver(e, cache_path=cache, today=date(2026, 9, 23))
    assert r.resolve("BAD", "2023-05-10").cik == 999001
    saved, reads = cache.read_text(), len(e.log)
    s = r.shadow()
    assert s.today == date(2026, 9, 23) and s.cache_path is None
    assert s.resolve("BAD", "2023-05-10").cik == 999001         # from the copied memo...
    assert len(e.log) == reads                                   # ...with no EDGAR read
    assert s.resolve("ALTR", "2025-03-26").cik == 1701732       # a new answer...
    assert cache.read_text() == saved                            # ...is not saved
    assert "ALTR|2025-03-26" not in r._memo                      # ...nor seen by its resolver
```

Add `from datetime import date` to the imports at the top of `tests/test_resolver_cache.py`.

Create `tests/test_pipeline_prefetch.py`:

```python
# tests/test_pipeline_prefetch.py
"""pipeline.run with --sec-workers: warm passes on worker threads ahead of each
SEC-heavy stage, the stage itself still sequential on the main thread, one run
date, per-stage request counts, and the resolver memo flushed even when a later
stage is refused."""
import json
import threading
from datetime import date

import pytest

import delist_detection.pipeline as pipeline
from delist_detection import edgar
from delist_detection.edgar import EdgarBlocked
from delist_detection.observations import Observation, ObservationIndex
from delist_detection.pipeline import Overrides, run
from delist_detection.ticker_resolver import TickerResolver
from tests.test_pipeline import _clients, _FtdClient, _index_clients


def test_one_worker_starts_no_prefetch(fake_edgar, tmp_path, monkeypatch):
    index, clients = _clients(fake_edgar)
    calls = []
    monkeypatch.setattr(pipeline, "warm", lambda *a, **k: calls.append(a))
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert calls == []


def test_issuer_resolution_is_warmed_on_worker_threads_first(fake_edgar, tmp_path, monkeypatch):
    obs = [Observation("BAD", "2023-05-10", "Bad Co."), Observation("LIQ", "2019-11-06", "Liquidating Trust")]
    index, clients = _index_clients(fake_edgar, obs, [], {})
    calls = []
    real = TickerResolver.resolve

    def recording(self, ticker, observed_date=None, **kw):
        calls.append((ticker, threading.current_thread().name, self is clients.resolver))
        return real(self, ticker, observed_date, **kw)

    monkeypatch.setattr(TickerResolver, "resolve", recording)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    warmed = {t for t, name, own in calls if name.startswith("sec-warm") and not own}
    assert warmed == {"BAD", "LIQ"}                                  # every era, by a shadow, on a worker
    assert all(name == threading.main_thread().name for _, name, own in calls if own)


def test_each_stage_logs_its_edgar_requests_apart_from_data_file_downloads(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    lines = []
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *a: lines.append(" ".join(map(str, a))))
    for stage in ("issuer resolution", "delisting search", "payouts", "successor search"):
        assert any(line.startswith(f"{stage}: ") and "EDGAR requests" in line
                   and "SEC data-file downloads" in line for line in lines), stage


def test_the_fails_to_deliver_window_ends_on_the_run_date(fake_edgar, tmp_path):
    class _DatedFtd(_FtdClient):
        def __init__(self):
            self.windows = []

        def urls_for(self, lo, hi):
            self.windows.append((lo, hi))
            return ["mem"]

    index, clients = _clients(fake_edgar)
    clients.ftd_client = _DatedFtd()
    clients.as_of = date(2019, 1, 31)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert max(hi for _, hi in clients.ftd_client.windows) == date(2019, 1, 31)


def test_resolver_answers_are_saved_even_when_a_later_stage_is_refused(fake_edgar, tmp_path):
    cache = tmp_path / "res.json"
    obs = [Observation("BAD", "2023-05-10", "Bad Co.")]
    index = ObservationIndex(obs)
    _, clients = _index_clients(fake_edgar, obs, [], {})
    clients.resolver = TickerResolver(fake_edgar, cache_path=cache, member_names=index.name_on,
                                      cik_map=index.cik_pin_on, batch_writes=True)

    def blocked(*a, **k):
        raise EdgarBlocked("SEC returned 403")

    fake_edgar.fetch_filing_raw = blocked                 # the Form 25 search is refused
    with pytest.raises(EdgarBlocked):
        run(index, clients, Overrides(), out_dir=tmp_path / "out", log=lambda *_: None)
    assert "BAD|2023-05-10" in json.loads(cache.read_text())["entries"]


def test_default_clients_share_one_run_date_and_a_machine_wide_limit(tmp_path, monkeypatch):
    monkeypatch.setenv(edgar.SEC_RATE_LOCK_ENV, str(tmp_path / "sec_rate.lock"))
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    index = ObservationIndex([Observation("AET", "2018-06-29", "AETNA INC")])
    c = pipeline.default_clients(index, cache_dir=tmp_path / "cache", as_of=date(2026, 9, 23),
                                 extract_payouts=False)
    assert c.as_of == c.edgar.today == c.resolver.today == c.classifier.today == c.halts.today == date(2026, 9, 23)
    assert c.resolver.batch_writes is True
    assert edgar.SEC_LIMITER.gate is not None and edgar.SEC_LIMITER.gate.path == tmp_path / "sec_rate.lock"
```

In `tests/test_classify_universe_cli.py`:
- Add `import pytest` and `from delist_detection import edgar as edgar_mod`.
- Add `assert args.sec_workers == 4` to `test_argument_parser_defaults`.
- Change `_run_main` to:

```python
def _run_main(monkeypatch, review_flags, *argv):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    monkeypatch.setattr(cli, "use_machine_wide_limit", lambda *a, **k: None)
    monkeypatch.setattr(cli, "load_observations", lambda path: [])
    monkeypatch.setattr(cli, "ObservationIndex", lambda obs: obs)
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: object())
    seen = {}
    monkeypatch.setattr(cli, "run", lambda *a, **kw: seen.update(kw) or _FakeSummary(review_flags))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv", *argv])
    rc = cli.main()
    _run_main.seen = seen
    return rc
```

- Append:

```python
def test_main_passes_sec_workers_to_run(monkeypatch):
    assert _run_main(monkeypatch, {}, "--sec-workers", "3") == 0
    assert _run_main.seen["sec_workers"] == 3


@pytest.mark.parametrize("n", ["0", "9"])
def test_sec_workers_outside_1_to_8_is_refused(monkeypatch, n):
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, {}, "--sec-workers", n)
    assert exc.value.code == 2


def test_the_fallback_user_agent_stops_the_run_before_any_request(monkeypatch):
    monkeypatch.setattr(edgar_mod, "resolve_user_agent", lambda: edgar_mod.FALLBACK_UA)
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: pytest.fail("no client may be built"))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_an_unusable_rate_lock_stops_the_run_before_any_request(monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")

    def cannot(*a, **k):
        raise OSError("cannot open the machine-wide SEC rate lock /x (denied); set DELIST_DETECTION_SEC_RATE_LOCK")

    monkeypatch.setattr(cli, "use_machine_wide_limit", cannot)
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: pytest.fail("no client may be built"))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_resolver_cache.py tests/test_pipeline_prefetch.py tests/test_classify_universe_cli.py -q`
Expected: FAIL with:
- `AttributeError: 'TickerResolver' object has no attribute 'shadow'`;
- `TypeError: run() got an unexpected keyword argument 'sec_workers'`;
- `AttributeError: 'Namespace' object has no attribute 'sec_workers'`;
- `AttributeError: ... has no attribute 'use_machine_wide_limit'`.

- [ ] **Step 3: Add `TickerResolver.shadow()`**

In `src/delist_detection/ticker_resolver.py`, after `resolve_many`:

```python
    def shadow(self) -> "TickerResolver":
        """A copy for warming the EDGAR caches on another thread: the same EDGAR
        client, overrides, name callables and run date, and a snapshot of the
        memo (so it skips every era this resolver already answers). It persists
        nothing and its answers are thrown away. Call it on the thread that owns
        this resolver, while that resolver is idle (prefetch.warm does)."""
        s = TickerResolver(self.edgar, rename_map=self.rename_map, manual_overrides=self.manual_overrides,
                           name_lookup=self.name_lookup, member_names=self.member_names, cik_map=self.cik_map,
                           today=self.today)
        s._memo, s._memo_member = dict(self._memo), dict(self._memo_member)
        s._volatile, s._degraded = set(self._volatile), set(self._degraded)
        s._companies = self._ensure_companies()
        return s
```

- [ ] **Step 4: Wire the run date, the meter and the stage-2 warm pass into the pipeline**

In `src/delist_detection/pipeline.py`, change the edgar import to `from .edgar import SEC_STATS, EdgarBlocked` and add `from .prefetch import warm`.

Add the field to `Clients`, after `llm_extractor`:

```python
    as_of: date | None = None       # the run date every client uses (default_clients sets it)
```

Add after `_own_last_seen`:

```python
class _StageMeter:
    """SEC traffic per pipeline stage, from edgar.SEC_STATS: logged as each stage
    ends and kept for run_manifest.json. Counts cover every thread (the warm pass's
    and the stage's own). EDGAR endpoints are counted apart from SEC data-file
    downloads (fails-to-deliver and MIDAS ZIPs and their index pages)."""

    def __init__(self, log: Callable) -> None:
        self.log = log
        self.stages: dict[str, dict[str, int]] = {}

    def start(self):
        return SEC_STATS.snapshot()

    def done(self, stage: str, mark) -> None:
        counts, _ = SEC_STATS.since(mark)
        edgar_n = sum(v for k, v in counts.items() if k.startswith("request:") and k != "request:sec_data")
        data_n = counts.get("request:sec_data", 0)
        self.stages[stage] = {"edgar_requests": edgar_n, "sec_data_downloads": data_n}
        self.log(f"{stage}: {edgar_n} EDGAR requests, {data_n} SEC data-file downloads (all threads)")


def _flush_memo(clients: Clients) -> None:
    """Write the resolver's batched memo now (TickerResolver.flush)."""
    flush = getattr(clients.resolver, "flush", None)
    if flush is not None:
        flush()


def run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path,
        tol: float = DEFAULT_TOL, limit: int | None = None, log: Callable = _stderr,
        sec_workers: int = 1) -> RunSummary:
    """Observations -> the six tables under `out_dir` (spec §8).

    `sec_workers` > 1 fills the SEC caches ahead of each SEC-heavy stage on that
    many threads (`prefetch.warm`: fill-only, every thread under the one limiter).
    Each stage itself still runs one item at a time, in its usual order, on this
    thread, so the same caches and run date (`clients.as_of`) give byte-identical
    tables for any worker count. A refusal on any thread aborts the run before
    anything is written. The resolver's memo is written after issuer resolution,
    after the acquirer lookups, and on the way out, error or not."""
    try:
        return _run(index, clients, overrides, out_dir=out_dir, tol=tol, limit=limit, log=log,
                    sec_workers=sec_workers)
    finally:
        _flush_memo(clients)
```

Replace the old `run` signature (lines 418–419) and its first line (`eras = index.eras()`) with:

```python
def _run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path, tol: float,
         limit: int | None, log: Callable, sec_workers: int) -> RunSummary:
    as_of = clients.as_of or date.today()     # the one run date: every window below ends on it
    meter = _StageMeter(log)
    eras = index.eras()
```

In stage 1, replace `hi = min(date.today(), max(_d(e.last) for e in eras) + timedelta(days=400))` with:

```python
    hi = min(as_of, max(_d(e.last) for e in eras) + timedelta(days=400))
```

In stage 4, replace `ftd.extend(clients.ftd_client, lo, date.today(), cusips={c for v in sec_cusips.values() for c in v})` with:

```python
    ftd.extend(clients.ftd_client, lo, as_of, cusips={c for v in sec_cusips.values() for c in v})
```

In stage 2, replace the line `cik_res = {e.key: clients.resolver.resolve(e.ticker, era_last_seen(e, ftd), pin=e.cik_pin) for e in eras}` with:

```python
    last_seen = {e.key: era_last_seen(e, ftd) for e in eras}
    mark = meter.start()
    if sec_workers > 1:
        # Warm the EDGAR caches: each era resolved on a worker thread by a shadow
        # resolver (a snapshot of this memo that saves nothing), its answer thrown
        # away. The resolve below then runs one era at a time, in order, on this
        # thread, and finds its requests answered.
        warm(eras, lambda shadow, e: shadow.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin),
             workers=sec_workers, state=clients.resolver.shadow)
    cik_res = {e.key: clients.resolver.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin) for e in eras}
    _flush_memo(clients)
    meter.done("issuer resolution", mark)
```

In stage 5 (Task 10 code), insert `mark = meter.start()` on the line before `for i, s in enumerate(ordered, 1):`. After the loop, right after

```python
        if i % 50 == 0:
            log(f"[{i}/{len(securities)}] securities searched; {len(events)} delistings so far")
```

add at the stage's indentation:

```python
    meter.done("delisting search", mark)
```

In stage 8, right after `mergers = [e for e in events if e.record.bucket is CrspBucket.MERGER]`, add `mark = meter.start()`. At the end of the acquirer loop, right before the `# 9. successors after a FIGI change` comment, add:

```python
    _flush_memo(clients)                       # the acquirer lookups resolved tickers
    meter.done("payouts", mark)
```

In stage 9, right after `successor_search = getattr(clients.edgar, "full_text_search", None)`, add `mark = meter.start()`. Right before the `# 10. rows` comment, add:

```python
    meter.done("successor search", mark)
```

Replace `default_clients` with:

```python
def default_clients(index: ObservationIndex, *, cache_dir: Path, rename_map: dict | None = None,
                    manual_overrides: dict | None = None, extract_payouts: bool = True,
                    extract_llm: bool = False, llm_model: str | None = None, use_midas: bool = True,
                    use_halts: bool = True, as_of: date | None = None) -> Clients:
    """The production clients. Every client is dated `as_of` (default: today,
    read once here), the resolver batches its memo writes, and the SEC limit is
    made machine-wide (edgar.use_machine_wide_limit)."""
    from .classifier import DelistClassifier
    from .edgar import EdgarClient, use_machine_wide_limit
    from .ftd import FtdClient
    from .midas import MidasClient
    from .nasdaq_halts import NasdaqHaltClient
    from .openfigi import OpenFigiClient, resolve_api_key
    from .payout_extractor import PayoutExtractor
    from .ticker_resolver import TickerResolver

    as_of = as_of or date.today()
    use_machine_wide_limit()
    edgar = EdgarClient(cache_dir=cache_dir / "edgar", today=as_of)
    resolver = TickerResolver(edgar, rename_map=rename_map,
                              manual_overrides={k: v for k, v in (manual_overrides or {}).items() if v > 0},
                              cache_path=cache_dir / "ticker_resolution.json",
                              member_names=index.name_on, cik_map=index.cik_pin_on, today=as_of,
                              batch_writes=True)
    llm = None
    if extract_llm:
        from .llm_client import default_llm_client
        from .llm_merger_extractor import LLMMergerTermsExtractor
        llm = LLMMergerTermsExtractor(edgar, default_llm_client(llm_model), cache_dir=cache_dir / "llm")
    return Clients(
        edgar=edgar, resolver=resolver, classifier=DelistClassifier(edgar, resolver, today=as_of),
        figi=OpenFigiClient(cache_dir / "openfigi", resolve_api_key()),
        ftd_client=FtdClient(cache_dir / "sec_data" / "ftd"),
        midas=MidasClient(cache_dir / "sec_data" / "midas") if use_midas else None,
        halts=NasdaqHaltClient(cache_dir / "nasdaq_halts", today=as_of) if use_halts else None,
        payout_extractor=PayoutExtractor(edgar) if extract_payouts else None,
        llm_extractor=llm, as_of=as_of,
    )
```

- [ ] **Step 5: Add `--sec-workers` and the start-up checks to the CLI**

In `scripts/classify_universe.py`, change the edgar import to:

```python
from delist_detection.edgar import EdgarBlocked, EdgarSetupError, require_user_agent, use_machine_wide_limit
```

After `MANUAL_OVERRIDES`, add:

```python
DEFAULT_SEC_WORKERS = 4     # threads prefetching SEC data; each stage itself stays sequential
MAX_SEC_WORKERS = 8         # one process's ceiling: all threads share one 8 requests/s limit
```

In `build_parser`, add before `return p`:

```python
    p.add_argument("--sec-workers", type=int, default=DEFAULT_SEC_WORKERS,
                   help=f"Threads that fetch SEC data ahead of each stage (default %(default)s, at most "
                        f"{MAX_SEC_WORKERS}; 1 = one request at a time). Every SEC request from this process, and "
                        "from every other SEC client on this machine through the lock file "
                        "$DELIST_DETECTION_SEC_RATE_LOCK (default ~/.cache/delist_detection/sec_rate.lock), "
                        "shares one 8 requests/s limit, so more threads only fill that limit sooner.")
```

In `main()`, right after `args = p.parse_args()`, add:

```python
    if not 1 <= args.sec_workers <= MAX_SEC_WORKERS:
        p.error(f"--sec-workers must be between 1 and {MAX_SEC_WORKERS}")
    try:
        require_user_agent()           # SEC 403s the fallback: stop before the first request
        use_machine_wide_limit()       # every SEC client on this machine shares the 8 requests/s
    except (EdgarSetupError, OSError) as exc:
        p.error(str(exc))
```

and change the `run(...)` call to:

```python
    summary = run(index, clients, overrides, out_dir=Path(args.output_dir), tol=args.merger_terms_sanity_tol,
                  limit=args.limit, sec_workers=args.sec_workers, **({"log": log} if log else {}))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_resolver_cache.py tests/test_pipeline_prefetch.py tests/test_classify_universe_cli.py tests/test_pipeline.py tests/test_prefetch.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/delist_detection/ticker_resolver.py src/delist_detection/pipeline.py scripts/classify_universe.py tests/test_resolver_cache.py tests/test_pipeline_prefetch.py tests/test_classify_universe_cli.py
```

```bash
git commit -m "perf(pipeline): one run date, --sec-workers with a warm issuer-resolution pass, per-stage SEC request counts

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/ticker_resolver.py src/delist_detection/pipeline.py scripts/classify_universe.py tests/test_resolver_cache.py tests/test_pipeline_prefetch.py tests/test_classify_universe_cli.py
```

---

### Task 12: Stage-5 warm pass with the run's own MIDAS and halt clients

**Model:** most capable (warm finders, shared locks, main-thread-only invariant).

**Files:**
- Modify: `src/delist_detection/pipeline.py`:
  - the imports: `import copy`; `is_placeholder` from `.figi_resolution`; `Serialized` from `.prefetch`;
  - a new `_warm_delisting_search`;
  - stage 5, from `sightings = {sid: _sightings(...)}` through `meter.done("delisting search", mark)` (Task 10 and Task 11 code).
- Test: `tests/test_pipeline_prefetch.py` (append).

**Interfaces:**
- Consumes: `warm`, `Serialized` (Task 9); `listing`, `listing_answers`, `listed_today(answer=)` (Task 10); `shadow()`, `meter` (Task 11); `DelistingFinder(edgar, classifier, *, midas=None, halts=None)`.
- Produces:
  - `pipeline._warm_delisting_search(clients: Clients, ordered: list[Security], listing: dict[str, dict], context: Callable[[Security, bool | None], SecurityContext], workers: int) -> None`.
  - A `security_context(s, listed_now)` closure inside `_run`, which Task 14 does not change.
  - HEAD's `SecurityRef(s.sec_id, s.share_class, s.kind, s.name)` (commit 4cd60a5) is kept.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline_prefetch.py` (add `from delist_detection.prefetch import Serialized` to its imports):

```python
class _Midas:
    def last_trade_day(self, ticker, lo, hi):
        return None


class _Halts:
    def deletion_halt(self, symbol, lo, hi, max_days=7):
        return None


def test_the_warm_finders_are_the_sequential_finders_twins(fake_edgar, tmp_path, monkeypatch):
    index, clients = _clients(fake_edgar)
    clients.midas, clients.halts = _Midas(), _Halts()
    built = []
    real = pipeline.DelistingFinder

    class _Spy(real):
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            built.append((midas, halts, classifier))
            super().__init__(edgar, classifier, midas=midas, halts=halts)

    monkeypatch.setattr(pipeline, "DelistingFinder", _Spy)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    (seq_midas, seq_halts, seq_classifier), *warm_built = built      # the sequential finder is built first
    assert seq_midas is clients.midas and seq_halts is clients.halts and seq_classifier is clients.classifier
    assert warm_built
    for midas, halts, classifier in warm_built:
        assert isinstance(midas, Serialized) and midas._obj is clients.midas
        assert isinstance(halts, Serialized) and halts._obj is clients.halts
        assert classifier.resolver is not clients.resolver and isinstance(classifier.resolver, TickerResolver)
    assert len({id(m) for m, _, _ in warm_built}) == 1                 # one lock shared by every warm finder


def test_prefetch_reads_edgar_on_worker_threads_before_the_sequential_pass(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    seen, real = [], fake_edgar.recent_filings

    def recording(cik):
        seen.append((int(cik), threading.current_thread().name))
        return real(cik)

    fake_edgar.recent_filings = recording
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    names = [name for cik, name in seen if cik == 1122304]
    assert any(n.startswith("sec-warm") for n in names)                # the prefetch read it
    assert names[-1] == threading.main_thread().name                   # and the sequential pass read it after


def test_a_refusal_on_a_worker_thread_aborts_the_run_and_writes_nothing(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    before = {p.name: p.read_text() for p in tmp_path.glob("*.csv")}
    main_calls, real = [], fake_edgar.fetch_filing_raw

    def refused_on_workers(cik, accession):
        if threading.current_thread() is not threading.main_thread():
            raise EdgarBlocked("SEC returned 403")
        main_calls.append(accession)
        return real(cik, accession)

    fake_edgar.fetch_filing_raw = refused_on_workers
    with pytest.raises(EdgarBlocked):
        run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    assert main_calls == []                                            # the sequential pass never began
    assert {p.name: p.read_text() for p in tmp_path.glob("*.csv")} == before


def test_the_runs_own_resolver_only_ever_runs_on_the_main_thread(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    r, seen = clients.resolver, []
    real_resolve, real_fits = r.resolve, r._fits_date

    def resolve(*a, **k):
        seen.append(threading.current_thread().name)
        return real_resolve(*a, **k)

    def fits(*a, **k):
        seen.append(threading.current_thread().name)
        return real_fits(*a, **k)

    r.resolve, r._fits_date = resolve, fits        # its `_transient` flag must never be shared across threads
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    assert seen and set(seen) == {threading.main_thread().name}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline_prefetch.py -q`
Expected: FAIL. `warm_built` is empty (no stage-5 warm pass yet), no `sec-warm` read of CIK 1122304 is recorded, and `EdgarBlocked` is not raised: the refusal only exists on worker threads, and none exist yet.

- [ ] **Step 3: Implement**

In `src/delist_detection/pipeline.py`, add `import copy` to the stdlib imports, change the FIGI import to `from .figi_resolution import FigiCandidate, accept, is_placeholder, share_class_from_name, us_candidates`, and change the prefetch import to `from .prefetch import Serialized, warm`.

Add after `_flush_memo`:

```python
def _warm_delisting_search(clients: Clients, ordered: list[Security], listing: dict[str, dict],
                           context: Callable[[Security, bool | None], SecurityContext], workers: int) -> None:
    """Fill the SEC caches for the Form 25 search: each security's own finder work
    on `workers` threads, fill-only, its answers thrown away. A warm finder is the
    sequential finder's twin: a copy of the run's classifier holding a shadow
    resolver, and the run's own MIDAS and Nasdaq-halt clients, each behind one lock
    shared by every warm finder. It therefore takes the same last-trade anchors
    and asks for what the sequential pass will. A security whose batched OpenFIGI
    answer is missing is skipped: the sequential pass asks OpenFIGI for it alone,
    and its listing status decides what the finder reads."""
    midas = Serialized(clients.midas) if clients.midas is not None else None
    halts = Serialized(clients.halts) if clients.halts is not None else None

    def make_finder() -> DelistingFinder:
        classifier = copy.copy(clients.classifier)
        if getattr(classifier, "resolver", None) is not None:
            classifier.resolver = clients.resolver.shadow()
        return DelistingFinder(clients.edgar, classifier, midas=midas, halts=halts)

    def task(finder: DelistingFinder, s: Security) -> None:
        answer = listing.get(s.sec_id)
        if answer is None and not is_placeholder(s.sec_id):
            return
        now = listed_today(None, s.sec_id, edgar=clients.edgar, cik=s.issuer_cik,
                           tickers=sorted({e.ticker for e in s.eras}), answer=answer)
        finder.find(context(s, now))

    warm(ordered, task, workers=workers, state=make_finder)
```

In stage 5, replace everything from `sightings = {sid: _sightings(s, ftd, sec_cusips[sid]) for sid, s in securities.items()}` through `meter.done("delisting search", mark)` with:

```python
    sightings = {sid: _sightings(s, ftd, sec_cusips[sid]) for sid, s in securities.items()}

    def security_context(s: Security, listed_now: bool | None) -> SecurityContext:
        sig = sightings[s.sec_id]
        sibs = siblings.get(s.issuer_cik) or [SecurityRef(s.sec_id, s.share_class, s.kind, s.name)]
        # sec_id -> (first sighting, last own-ticker sighting) for every security
        # sharing this issuer CIK, from the same sightings built above; a sibling
        # with no sightings gets no entry (the finder treats it as alive at every
        # filing). The end reuses _own_last_seen so a sibling's post-delisting OTC
        # tail under another symbol can't extend its life past its real death.
        spans: dict[str, tuple[str, str]] = {}
        for ref in sibs:
            sib_sig = sightings.get(ref.sec_id)
            if not sib_sig:
                continue
            sib_sec = securities.get(ref.sec_id)
            span_end = _own_last_seen(sib_sec, sib_sig) if sib_sec is not None else sib_sig[-1][0]
            spans[ref.sec_id] = (sib_sig[0][0], span_end)
        return SecurityContext(
            security=s,
            siblings=sibs,
            ticker_on=_ticker_on(sig),
            last_seen=_own_last_seen(s, sig),
            seen_after=lambda day, sig=sig: any(d > day for d, _, _ in sig),
            listed_today=listed_now,
            expected_name=s.eras[-1].name if s.eras else None,
            sibling_spans=spans,
            resolution_source=_resolution_source(s, cik_res),
            ftd_seen_after=lambda day, sig=sig, own={e.ticker for e in s.eras}: any(
                d > day for d, t, src in sig if src == "ftd" and t in own),
            tickers_between=lambda lo, hi, sig=sig: list(dict.fromkeys(t for d, t, _ in sig if lo <= d <= hi)),
        )

    ordered = sorted(securities.values(), key=lambda s: s.sec_id)
    # One batched OpenFIGI ask for every security's listing; a failed batch leaves
    # each security to ask alone inside its own try below.
    listing = listing_answers(clients.figi, [s.sec_id for s in ordered])
    mark = meter.start()
    if sec_workers > 1:
        _warm_delisting_search(clients, ordered, listing, security_context, sec_workers)
    for i, s in enumerate(ordered, 1):
        own_last_seen = _own_last_seen(s, sightings[s.sec_id])
        try:
            # listed_today and the context live inside the try too: a FIGI/EDGAR
            # error there must become a reviewable row for this one security,
            # not abort the whole overnight run.
            listed[s.sec_id] = listed_today(clients.figi, s.sec_id, edgar=clients.edgar, cik=s.issuer_cik,
                                            tickers=sorted({e.ticker for e in s.eras}),
                                            answer=listing.get(s.sec_id))
            evs, rv = finder.find(security_context(s, listed[s.sec_id]))
        except (EdgarBlocked, OpenFigiBlocked):
            raise
        except Exception as exc:  # an overnight run must survive one bad security
            log(f"[{i}/{len(securities)}] {s.sec_id}: ERROR {type(exc).__name__}: {exc}")
            review.append(ReviewItem(s.sec_id, s.eras[-1].ticker if s.eras else "", s.issuer_cik, "error",
                                     f"{type(exc).__name__}: {exc}", last_seen=own_last_seen))
            continue
        events += evs
        review += rv
        if i % 50 == 0:
            log(f"[{i}/{len(securities)}] securities searched; {len(events)} delistings so far")
    meter.done("delisting search", mark)
```

The context fields are exactly as at HEAD. Only the `sibs` and `spans` computation moves inside `security_context`, which the loop calls inside its `try`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline_prefetch.py tests/test_pipeline.py tests/test_delistings.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/pipeline.py tests/test_pipeline_prefetch.py
```

```bash
git commit -m "perf(pipeline): warm the Form 25 search with the sequential finder's twin: shadow resolver, the run's MIDAS and halt clients

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/pipeline.py tests/test_pipeline_prefetch.py
```

---

### Task 13: Stage 8 and 9 warm passes, and the determinism proof

**Model:** most capable (the determinism proof).

**Files:**
- Modify: `src/delist_detection/pipeline.py`:
  - new `SUCCESSOR_FORMS` and `successor_query`, above `successor_from_8k12b` (`:75`);
  - `successor_from_8k12b`'s search line (`:100`);
  - stage 8, after `mark = meter.start()` (Task 11);
  - stage 9, after its `mark = meter.start()` (Task 11) and the `starts[sid] = ...` loop.
- Test: `tests/test_pipeline_prefetch.py` (append).

**Interfaces:**
- Consumes: `warm` (Task 9); `meter` (Task 11); `EdgarClient(today=)` (Task 4); `TickerResolver(today=, batch_writes=)` (Tasks 4, 8); `DelistClassifier(today=)` (Task 4); `Clients.as_of` (Task 11).
- Produces:
  - `pipeline.SUCCESSOR_FORMS = "8-K12B,8-K12G3"`.
  - `pipeline.successor_query(name: str, day: date) -> tuple[str, str, date, date]`.

- [ ] **Step 1: Write the failing tests**

Add these imports to `tests/test_pipeline_prefetch.py`:

```python
import shutil
from datetime import date

from delist_detection.classifier import DelistClassifier, DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import DelistingEvent
from delist_detection.edgar import FETCHED_KEY, EdgarClient
from delist_detection.last_trade import LastTrade
from delist_detection.payout_extractor import PayoutExtractor, PayoutResult
from delist_detection.pipeline import Clients, successor_query
from delist_detection.store import read_table, table_path
from tests.test_pipeline import AET_RAW, _Figi, _figi_answer, _ftd
```

Then append:

```python
# Read at import, before conftest's autouse fixture stubs them for each test.
_REAL_EFTS = {name: getattr(TickerResolver, name) for name in ("_efts_lookup", "_efts_pre_delist_frequency_ranked")}


def test_the_successor_search_query_is_the_one_the_prefetch_sends():
    assert successor_query("GOOGLE INC", date(2015, 10, 2)) == (
        '"GOOGLE INC"', "8-K12B,8-K12G3", date(2015, 9, 2), date(2015, 12, 1))


def test_payout_extraction_is_warmed_on_worker_threads_and_the_llm_is_not(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    regex, llm, guard = [], [], threading.Lock()

    class _Regex:
        def extract(self, record, last_close=None):
            with guard:
                regex.append(threading.current_thread().name)
            return PayoutResult.none()

    class _Llm:
        def extract(self, record):
            with guard:
                llm.append(threading.current_thread().name)
            return None

    clients.payout_extractor, clients.llm_extractor = _Regex(), _Llm()
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    assert any(n.startswith("sec-warm") for n in regex) and regex[-1] == threading.main_thread().name
    assert set(llm) == {threading.main_thread().name}                  # paid calls are never warmed


def test_the_successor_search_is_warmed_with_the_query_the_sequential_pass_sends(fake_edgar, tmp_path,
                                                                                 monkeypatch):
    fake_edgar.company_map["GOOGL"] = {"cik_str": 1288776, "ticker": "GOOGL", "title": "Google Inc."}
    fake_edgar.submissions_by_cik[1288776] = []
    obs = [Observation("GOOGL", d, "GOOGLE INC CLASS A") for d in ("2014-06-30", "2015-06-30")]
    rows = _ftd("GOOGL", "38259P508", "GOOGLE INC;COM USD0.001 CL'A'",
                ["2014-06-02", "2014-12-01", "2015-06-01", "2015-10-02"])
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "38259P508"): _figi_answer("BBGGOOGLEA1", "GOOGL", "GOOGLE INC-CL A"),
        ("TICKER", "GOOGL"): _figi_answer("BBG009S39JX6", "GOOGL", "ALPHABET INC-CL A"),
        ("TICKER", "GOOG"): _figi_answer("BBG009S3NB30", "GOOG", "ALPHABET INC-CL C"),
    })

    def event():
        record = DelistRecord(ticker="GOOGL", cik=1288776, observed_delist_date="2015-10-02", crsp_code=300,
                              bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="high", reason="holdco reorg",
                              evidence={"flags": ["successor_unknown"]}, sec_id="BBGGOOGLEA1",
                              delist_date="2015-10-12")
        return DelistingEvent(sec_id="BBGGOOGLEA1", cik=1288776, ticker="GOOGL", delist_date="2015-10-12",
                              record=record, last_trade=LastTrade(date(2015, 10, 2), "notice_a", ()),
                              form25=None, form25_sub=None, exchange="NASDAQ", flags=["successor_unknown"])

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return [event()], []

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)
    searches, guard = [], threading.Lock()

    def search(q, forms, lo, hi):
        with guard:
            searches.append(((q, forms, lo, hi), threading.current_thread().name))
        return []

    fake_edgar.full_text_search = search
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    queries = {q for q, _ in searches}
    assert queries == {successor_query("Google Inc.", date(2015, 10, 2))}
    names = [n for _, n in searches]
    assert any(n.startswith("sec-warm") for n in names) and names[-1] == threading.main_thread().name


# --- the determinism proof: one worker and N from cloned cache snapshots -----------------

AS_OF = date(2026, 9, 23)
UA = "Test Co test@example.com"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
AET_SUB_URL = "https://data.sec.gov/submissions/CIK0001122304.json"
OLD_SUB_URL = "https://data.sec.gov/submissions/CIK0000002222.json"
_KEYS = ("accessionNumber", "form", "filingDate", "reportDate", "items", "primaryDocument")
AET_FILINGS = [("0000876661-18-001269", "25-NSE", "2018-11-29", "", "", "primary_doc.xml"),
               ("0001122304-18-000178", "8-K", "2018-11-28", "2018-11-28", "2.01,3.01,5.01,9.01", "k.htm"),
               ("0001122304-18-000184", "15-12B", "2018-12-10", "", "", "f.htm")]
OLD_FILINGS = [("0000876661-19-000100", "25-NSE", "2019-02-01", "", "", "primary_doc.xml")]


def _submissions(cik, name, filings):
    return {"cik": str(cik), "name": name, "formerNames": [], "sic": "", "tickers": [], "exchanges": [],
            "filings": {"recent": {k: [f[i] for f in filings] for i, k in enumerate(_KEYS)}}}


class _SecResp:
    def __init__(self, status, text, url):
        self.status_code, self.text, self.url = status, text, url

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class _OfflineSec:
    """A thread-safe stand-in for SEC's servers: canned answers by URL. Any
    full-text search finds nothing, any company-name search matches nothing, and
    any other URL is a 404. Records (url, thread name) of every request."""

    def __init__(self):
        self.answers = {
            TICKERS_URL: json.dumps({"0": {"cik_str": 1122304, "ticker": "AET", "title": "AETNA INC /PA/"}}),
            AET_SUB_URL: json.dumps(_submissions(1122304, "AETNA INC /PA/", AET_FILINGS)),
            OLD_SUB_URL: json.dumps(_submissions(2222, "OLD CO INC", OLD_FILINGS)),
            "https://www.sec.gov/Archives/edgar/data/1122304/000087666118001269/0000876661-18-001269.txt": AET_RAW,
            "https://www.sec.gov/Archives/edgar/data/1122304/000112230418000178/k.htm":
                "<html>Item 3.01 Notice. trading suspended prior to the opening of trading on November 29, 2018 "
                + "x" * 300 + "</html>",
        }
        self.calls, self._lock = [], threading.Lock()

    def get(self, url, headers=None, timeout=None):
        with self._lock:
            self.calls.append((url, threading.current_thread().name))
        if url in self.answers:
            return _SecResp(200, self.answers[url], url)
        if "efts.sec.gov" in url:
            return _SecResp(200, json.dumps({"hits": {"hits": []}}), url)
        if "/cgi-bin/browse-edgar" in url:
            return _SecResp(200, "<feed></feed>", url)
        return _SecResp(404, "", url)


class _OfflineMidas:
    def last_trade_day(self, ticker, lo, hi):
        d = date(2018, 11, 28)
        return d if ticker == "AET" and lo <= d <= hi else None


def _seed(root):
    """The starting cache. OLD's submissions were cached on 2019-01-01, before its
    Form 25 (2019-02-01): the Form 25 scan reads that copy, and the classifier then
    refreshes it. If a warm worker refreshed it first, the sequential pass would
    read a different copy than a one-worker run does, and the tables would differ."""
    client = EdgarClient(cache_dir=root / "edgar", user_agent=UA, session=_OfflineSec(), today=AS_OF)
    stale = {**_submissions(2222, "OLD CO INC", []), FETCHED_KEY: "2019-01-01"}
    client._cache_path(OLD_SUB_URL).write_text(json.dumps(stale))


def _offline_run(root, out, workers):
    sec = _OfflineSec()
    edgar_client = EdgarClient(cache_dir=root / "edgar", user_agent=UA, session=sec, sleep=lambda _: None,
                               today=AS_OF)
    obs = [Observation("AET", "2017-06-30", "AETNA INC", cik=1122304),
           Observation("AET", "2018-06-29", "AETNA INC", cik=1122304),
           Observation("OLD", "2018-06-29", "OLD CO INC", cik=2222),
           Observation("OLD", "2018-12-31", "OLD CO INC", cik=2222),
           Observation("LIVE", "2025-06-30", "LIVE CO")]
    index = ObservationIndex(obs)
    resolver = TickerResolver(edgar_client, cache_path=root / "ticker_resolution.json", member_names=index.name_on,
                              cik_map=index.cik_pin_on, today=AS_OF, batch_writes=True)
    clients = Clients(edgar=edgar_client, resolver=resolver,
                      classifier=DelistClassifier(edgar_client, resolver, today=AS_OF), figi=_Figi(),
                      ftd_client=_FtdClient(), midas=_OfflineMidas(), halts=_Halts(),
                      payout_extractor=PayoutExtractor(edgar_client), as_of=AS_OF)
    run(index, clients, Overrides(), out_dir=out, log=lambda *_: None, sec_workers=workers)
    return sec


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("workers", [2, 4])
def test_one_worker_and_n_give_the_same_bytes_from_the_same_starting_caches(tmp_path, monkeypatch, workers):
    for name, method in _REAL_EFTS.items():        # LIVE's resolver full-text searches go through the cache
        monkeypatch.setattr(TickerResolver, name, method)
    seed = tmp_path / "seed"
    _seed(seed)
    shutil.copytree(seed, tmp_path / "one")
    shutil.copytree(seed, tmp_path / "n")
    sec1 = _offline_run(tmp_path / "one", tmp_path / "out1", 1)
    secn = _offline_run(tmp_path / "n", tmp_path / "outn", workers)
    csv1 = {p.name: p.read_bytes() for p in (tmp_path / "out1").glob("*.csv")}
    csvn = {p.name: p.read_bytes() for p in (tmp_path / "outn").glob("*.csv")}
    assert len(csv1) == 6 and csv1 == csvn
    assert _tree(tmp_path / "one") == _tree(tmp_path / "n")                  # the caches each run leaves behind
    main = threading.main_thread().name
    assert (OLD_SUB_URL, main) in sec1.calls and (OLD_SUB_URL, main) in secn.calls   # refreshed by the stage itself
    assert not any(u == OLD_SUB_URL and t != main for u, t in secn.calls)            # never by a warm worker
    assert any(t.startswith("sec-warm") for _, t in secn.calls)                      # the warm pass did fetch
    (d,) = read_table("delistings", table_path(tmp_path / "out1", "delistings"))
    assert (d["sec_id"], d["bucket"]) == ("BBG000FJLFX8", "merger")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline_prefetch.py -q`
Expected: FAIL. You should see `ImportError: cannot import name 'successor_query'`. Once that name exists, the warm-thread assertions of the payout and successor tests fail until Step 3 wires the warm passes.

To see that the determinism test guards the fill-only rule, temporarily replace `with lim.cancelled_by(stop), fill_only():` with `with lim.cancelled_by(stop):` in `prefetch.warm` and run `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest "tests/test_pipeline_prefetch.py::test_one_worker_and_n_give_the_same_bytes_from_the_same_starting_caches" -q`. Expected: FAIL. OLD's review row differs (`form25_unreadable` against `ended_without_delisting`), and OLD's submissions are fetched on a `sec-warm` thread. Restore the line afterwards.

- [ ] **Step 3: Implement**

In `src/delist_detection/pipeline.py`, add above `successor_from_8k12b`:

```python
SUCCESSOR_FORMS = "8-K12B,8-K12G3"


def successor_query(name: str, day: date) -> tuple[str, str, date, date]:
    """The full-text search successor_from_8k12b sends for `name` around `day`.
    The prefetch sends the same one, so the sequential pass reads it from cache."""
    return f'"{name}"', SUCCESSOR_FORMS, day - timedelta(days=30), day + timedelta(days=60)
```

In `successor_from_8k12b`, replace `hits = search(f'"{name}"', "8-K12B,8-K12G3", day - timedelta(days=30), day + timedelta(days=60))` with:

```python
    hits = search(*successor_query(name, day))
```

In stage 8, right after `mark = meter.start()` (the line after `mergers = [...]`), add:

```python
    if sec_workers > 1 and clients.payout_extractor is not None:
        # The regex payout reader's EDGAR reads, warmed. The LLM extractor is not
        # warmed: its calls are paid, and it has its own cache.
        extractor = clients.payout_extractor
        warm(mergers, lambda e: extractor.extract(e.record, last_close=closes.get((e.sec_id, e.delist_date))),
             workers=sec_workers)
```

In stage 9, right after the `for sid, s in added.items(): ... starts[sid] = (first, s.issuer_cik, {meta["ticker"]})` block and before `for e in events:`, add:

```python
    if sec_workers > 1 and successor_search is not None:
        # The events the loop below searches for: unknown successor, none in the run.
        pending = [e for e in events if "successor_unknown" in e.flags and _successor_in_run(e, starts) is None]
        warm(pending, lambda e: successor_search(*successor_query(
            successor_search_name(clients.edgar, e.cik, securities[e.sec_id].name),
            e.last_trade.day or _d(e.delist_date))), workers=sec_workers)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline_prefetch.py tests/test_pipeline.py -q`
Expected: all pass.

If the determinism test's last assertion (AET is a merger) fails while the equality assertions pass, the offline SEC fixture is missing something the AET path reads. Compare with `tests/test_pipeline.py::test_end_to_end_tables`, which proves the same AET facts through FakeEdgar, and add the missing canned answer to `_OfflineSec.answers`. Do not weaken the equality assertions.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass, the golden set included.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/pipeline.py tests/test_pipeline_prefetch.py
```

```bash
git commit -m "perf(pipeline): warm payout extraction and the successor search; prove 1 vs N workers give the same bytes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/pipeline.py tests/test_pipeline_prefetch.py
```

---

### Task 14: Provenance: `resolution_degraded` and `run_manifest.json`

**Files:**
- Create: `src/delist_detection/manifest.py`
- Modify: `src/delist_detection/pipeline.py`:
  - the imports;
  - `_run`: the snapshot at the top; the era rows after stage 3's review loop; the per-security check in stage 5; the per-merger check in stage 8; the per-search check in stage 9; the manifest after `write_tables`.
- Modify: `scripts/classify_universe.py`: `EXIT_CODES_EPILOG` and the end of `main`.
- Test: create `tests/test_run_provenance.py`; `tests/test_classify_universe_cli.py` (append).

**Interfaces:**
- Consumes: `SEC_STATS` with `snapshot`, `since`, `degraded` and `thread_degraded` (Task 4); `TickerResolver.is_degraded` (Task 8); `meter.stages`, `last_seen`, `as_of` (Task 11); `_write_atomic` (Task 3).
- Produces:
  - `manifest.MANIFEST_NAME = "run_manifest.json"`.
  - `manifest.code_version() -> str` (cached).
  - `manifest.build(*, as_of, sec_workers, counts, timings, stages, review_flags) -> dict`.
  - `manifest.write(out_dir, manifest) -> Path`.
  - The review flag `resolution_degraded`, on era, security, payout and successor rows.
  - CLI exit 3 when `review_flags` holds `error` or `resolution_degraded`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_run_provenance.py
"""What a run rested on: a `resolution_degraded` review row for every era,
security, payout and successor search whose answer rested on a failed request or
a stale copy, and run_manifest.json beside the tables."""
import json
from datetime import date

import pytest
import requests

from delist_detection import edgar, manifest
from delist_detection.edgar import SEC_STATS, EdgarBlocked
from delist_detection.observations import Observation
from delist_detection.payout_extractor import PayoutResult
from delist_detection.pipeline import Overrides, run
from delist_detection.store import read_table, table_path
from tests.test_pipeline import LIVE_FIGI, _clients, _index_clients


@pytest.fixture(autouse=True)
def _pinned_code_version(monkeypatch):
    monkeypatch.setattr(manifest, "code_version", lambda: "test-version")


def _review(out):
    return read_table("review", table_path(out, "review"))


def test_an_era_resolved_through_a_failed_request_is_flagged_resolution_degraded(fake_edgar, tmp_path):
    fake_edgar.company_map["LIVE"] = {"cik_str": 777, "ticker": "LIVE", "title": "LIVE CO"}
    fake_edgar.submissions_by_cik[777] = []            # the ticker map's holder did not exist on the date

    def down(company, form_type="25-NSE"):
        raise requests.ConnectionError("no route to host")

    fake_edgar.company_search_atom = down               # the name search cannot reach EDGAR
    index, clients = _index_clients(fake_edgar, [Observation("LIVE", "2025-06-30", "LIVE CO")], [],
                                    {("TICKER", "LIVE"): LIVE_FIGI})
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    rows = [r for r in _review(tmp_path) if r["review_flags"] == "resolution_degraded"]
    assert [(r["ticker"], r["sec_id"]) for r in rows] == [("LIVE", "BBG000LIVE01")]
    assert "not saved" in rows[0]["reason"]


def test_a_security_searched_through_a_stale_copy_is_flagged_resolution_degraded(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    real = fake_edgar.recent_filings

    def stale_for_aet(cik):
        if int(cik) == 1122304:
            SEC_STATS.degraded("stale_copy")            # what EdgarClient does when it serves a stale copy
        return real(cik)

    fake_edgar.recent_filings = stale_for_aet
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert [r["sec_id"] for r in _review(tmp_path) if r["review_flags"] == "resolution_degraded"] == ["BBG000FJLFX8"]


def test_a_payout_read_through_a_failed_request_is_flagged_with_its_delisting(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)

    class _FailingRead:
        def extract(self, record, last_close=None):
            SEC_STATS.degraded("failed_request")        # a filing text the payout reader could not fetch
            return PayoutResult.none()

    clients.payout_extractor = _FailingRead()
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    rows = [r for r in _review(tmp_path) if r["review_flags"] == "resolution_degraded"]
    assert [(r["sec_id"], r["delist_date"]) for r in rows] == [("BBG000FJLFX8", "2018-12-09")]


def test_a_clean_run_has_no_resolution_degraded_row(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert not any(r["review_flags"] == "resolution_degraded" for r in _review(tmp_path))


def test_the_manifest_records_what_the_run_rested_on(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    clients.as_of = date(2026, 9, 23)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=2)
    m = json.loads((tmp_path / "run_manifest.json").read_text())
    assert (m["as_of"], m["code_version"], m["sec_workers"]) == ("2026-09-23", "test-version", 2)
    assert set(m) == {"as_of", "code_version", "sec_workers", "sec_requests", "cache_answers",
                      "degraded_answers", "rejected_queries", "not_covered", "latency_ms", "stages",
                      "resolution_degraded"}
    assert set(m["stages"]) == {"issuer resolution", "delisting search", "payouts", "successor search"}
    assert m["resolution_degraded"] == 0


def test_a_refused_run_leaves_the_previous_manifest_in_place(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    before = (tmp_path / "run_manifest.json").read_bytes()

    def blocked(*a, **k):
        raise EdgarBlocked("SEC returned 403")

    clients.edgar.fetch_filing_raw = blocked
    with pytest.raises(EdgarBlocked):
        run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=3)
    assert (tmp_path / "run_manifest.json").read_bytes() == before


def test_latency_percentiles_per_endpoint():
    got = manifest.build(as_of=date(2026, 9, 23), sec_workers=1, counts={"request:archives": 4},
                         timings={"archives": [0.1, 0.2, 0.3, 1.0]}, stages={}, review_flags={})
    assert got["latency_ms"] == {"archives": {"n": 4, "p50": 200.0, "p95": 1000.0, "max": 1000.0}}
    assert got["sec_requests"] == {"archives": 4}
```

Append to `tests/test_classify_universe_cli.py`:

```python
def test_main_returns_3_when_an_answer_rested_on_a_failed_request(monkeypatch, capsys):
    rc = _run_main(monkeypatch, {"resolution_degraded": 2})
    assert rc == 3
    err = capsys.readouterr().err
    assert "2" in err and "resolution_degraded" in err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_run_provenance.py tests/test_classify_universe_cli.py -q`
Expected: collection error `ImportError: cannot import name 'manifest' from 'delist_detection'`, and the CLI test returns 0 instead of 3.

- [ ] **Step 3: Implement the manifest module**

```python
# src/delist_detection/manifest.py
"""run_manifest.json: what one run of the pipeline rested on.

Written next to the six tables, and only after them: a run that aborts leaves the
previous manifest in place, like the previous tables. It records:
- the run date every freshness rule used (`as_of`);
- the code that ran and the worker count;
- the SEC traffic behind the tables: requests sent and answers read from cache
  per endpoint, per-endpoint latency, and every answer that rested on a failed
  request or a stale copy.
So two runs over the same observations can be told apart when their tables differ.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date
from functools import lru_cache
from pathlib import Path

from .edgar import _write_atomic

MANIFEST_NAME = "run_manifest.json"
_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def code_version() -> str:
    """`git describe --always --dirty` of the checkout this module runs from, or
    "unknown" when that cannot be read (no git, not a checkout)."""
    try:
        out = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=_ROOT,
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    version = out.stdout.strip()
    return version if out.returncode == 0 and version else "unknown"


def _by_prefix(counts: dict[str, int], prefix: str) -> dict[str, int]:
    return {k[len(prefix):]: v for k, v in sorted(counts.items()) if k.startswith(prefix)}


def _latency(timings: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for endpoint, seconds in sorted(timings.items()):
        ms = sorted(s * 1000.0 for s in seconds)
        out[endpoint] = {"n": len(ms), "p50": round(ms[(len(ms) - 1) // 2], 1),
                         "p95": round(ms[min(len(ms) - 1, int(0.95 * len(ms)))], 1), "max": round(ms[-1], 1)}
    return out


def build(*, as_of: date, sec_workers: int, counts: dict[str, int], timings: dict[str, list[float]],
          stages: dict[str, dict[str, int]], review_flags: dict[str, int]) -> dict:
    """The manifest of one run. `counts` and `timings` are edgar.SEC_STATS.since()
    of the run's start; `stages` is the pipeline's per-stage meter."""
    return {
        "as_of": as_of.isoformat(),
        "code_version": code_version(),
        "sec_workers": sec_workers,
        "sec_requests": _by_prefix(counts, "request:"),
        "cache_answers": _by_prefix(counts, "cache:"),
        "degraded_answers": _by_prefix(counts, "degraded:"),
        "rejected_queries": _by_prefix(counts, "rejected:"),
        "not_covered": _by_prefix(counts, "not_covered:"),
        "latency_ms": _latency(timings),
        "stages": stages,
        "resolution_degraded": review_flags.get("resolution_degraded", 0),
    }


def write(out_dir: str | Path, manifest: dict) -> Path:
    path = Path(out_dir) / MANIFEST_NAME
    _write_atomic(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path
```

- [ ] **Step 4: Wire it into the pipeline**

In `src/delist_detection/pipeline.py`, add `from . import manifest as run_manifest`. Add after `_flush_memo`:

```python
DEGRADED_FLAG = "resolution_degraded"


def _degraded_since(mark: int) -> bool:
    """Whether an EDGAR answer on this thread rested on a failed request or a stale
    copy since `mark` (edgar.SEC_STATS.thread_degraded())."""
    return SEC_STATS.thread_degraded() > mark
```

At the top of `_run`, right after `meter = _StageMeter(log)`, add:

```python
    run_mark = SEC_STATS.snapshot()           # the manifest reports the traffic since here
```

In stage 3, right after the loop that appends the FIGI resolution flags (`for flag in res.flags: review.append(...)`), add:

```python
    for e in eras:
        if clients.resolver.is_degraded(e.ticker, last_seen[e.key]):
            res = resolutions[e.key]
            review.append(ReviewItem(res.sec_id or "", e.ticker, ciks.get(e.key), DEGRADED_FLAG,
                                     f"{e.key} {e.name or ''}: issuer resolution rested on a failed EDGAR request "
                                     "or a stale copy; its answer was used for this run but not saved",
                                     last_seen=e.last))
```

In stage 5's loop (Task 12 code), replace

```python
    for i, s in enumerate(ordered, 1):
        own_last_seen = _own_last_seen(s, sightings[s.sec_id])
        try:
```

with

```python
    for i, s in enumerate(ordered, 1):
        own_last_seen = _own_last_seen(s, sightings[s.sec_id])
        degraded_mark = SEC_STATS.thread_degraded()
        try:
```

and replace

```python
        events += evs
        review += rv
        if i % 50 == 0:
```

with

```python
        events += evs
        review += rv
        if _degraded_since(degraded_mark):
            review.append(ReviewItem(s.sec_id, s.eras[-1].ticker if s.eras else "", s.issuer_cik, DEGRADED_FLAG,
                                     "the delisting search rested on a failed EDGAR request or a stale copy; "
                                     "run again once SEC answers", last_seen=own_last_seen))
        if i % 50 == 0:
```

In stage 8's merger loop, replace

```python
    for e in mergers:
        key = (e.sec_id, e.delist_date)
        try:
            if clients.payout_extractor is not None:
```

with

```python
    for e in mergers:
        key = (e.sec_id, e.delist_date)
        degraded_mark = SEC_STATS.thread_degraded()
        try:
            if clients.payout_extractor is not None:
```

and, right after that loop's `except Exception as exc:` block (at the loop body's indentation, as its last statement), add:

```python
        if _degraded_since(degraded_mark):
            review.append(ReviewItem(e.sec_id, e.ticker, e.cik, DEGRADED_FLAG,
                                     "payout extraction rested on a failed EDGAR request or a stale copy",
                                     delist_date=e.delist_date))
```

In stage 9's loop, replace

```python
        predecessor = securities[e.sec_id]
        day = e.last_trade.day or _d(e.delist_date)
        name = successor_search_name(clients.edgar, e.cik, predecessor.name)
        hit = successor_from_8k12b(successor_search, clients.figi, name=name, day=day,
                                   exclude_cik=e.cik, share_class=predecessor.share_class)
        if hit is None:
            continue
```

with

```python
        predecessor = securities[e.sec_id]
        day = e.last_trade.day or _d(e.delist_date)
        degraded_mark = SEC_STATS.thread_degraded()
        name = successor_search_name(clients.edgar, e.cik, predecessor.name)
        hit = successor_from_8k12b(successor_search, clients.figi, name=name, day=day,
                                   exclude_cik=e.cik, share_class=predecessor.share_class)
        if _degraded_since(degraded_mark):
            review.append(ReviewItem(e.sec_id, e.ticker, e.cik, DEGRADED_FLAG,
                                     "the successor search rested on a failed EDGAR request or a stale copy",
                                     delist_date=e.delist_date))
        if hit is None:
            continue
```

At the end of `_run`, replace

```python
    flags = Counter(f.split(":", 1)[0] for r in review_rows for f in (r.get("review_flags") or "").split(";") if f)
    return RunSummary(counts, dict(Counter(e.record.bucket.value for e in events)),
                      dict(Counter(s.figi_source for s in securities.values())), dict(flags))
```

with

```python
    flags = Counter(f.split(":", 1)[0] for r in review_rows for f in (r.get("review_flags") or "").split(";") if f)
    stat_counts, stat_timings = SEC_STATS.since(run_mark)
    run_manifest.write(out_dir, run_manifest.build(as_of=as_of, sec_workers=sec_workers, counts=stat_counts,
                                                   timings=stat_timings, stages=meter.stages,
                                                   review_flags=dict(flags)))
    return RunSummary(counts, dict(Counter(e.record.bucket.value for e in events)),
                      dict(Counter(s.figi_source for s in securities.values())), dict(flags))
```

- [ ] **Step 5: Exit 3 on degraded answers in the CLI**

In `scripts/classify_universe.py`, replace `EXIT_CODES_EPILOG` with:

```python
EXIT_CODES_EPILOG = """\
Exit codes:
  0  success, no review-row errors
  2  aborted: SEC or OpenFIGI refused the request (EdgarBlocked/OpenFigiBlocked), or the
     start-up checks failed (no EDGAR_USER_AGENT, an unusable SEC rate-lock file)
  3  completed, but review.csv has one or more `error` rows, or `resolution_degraded`
     rows (an answer rested on a failed SEC request or a stale copy; run again once SEC
     answers). Outputs are still written; see the stderr banner for the counts
"""
```

and replace the end of `main()`, from `error_count = summary.review_flags.get("error", 0)` through `return 0`, with:

```python
    error_count = summary.review_flags.get("error", 0)
    degraded_count = summary.review_flags.get("resolution_degraded", 0)
    if error_count:
        print(f"WARNING: {error_count} review row(s) flagged 'error' -- outputs were still written; "
              "see review.csv for the affected (sec_id, delist_date) rows.", file=sys.stderr)
    if degraded_count:
        print(f"WARNING: {degraded_count} review row(s) flagged 'resolution_degraded' -- an answer rested on "
              "a failed SEC request or a stale copy; outputs were still written, run again once SEC answers.",
              file=sys.stderr)
    return 3 if error_count or degraded_count else 0
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_run_provenance.py tests/test_classify_universe_cli.py tests/test_pipeline.py tests/test_pipeline_prefetch.py -q`
Expected: all pass.

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/delist_detection/manifest.py src/delist_detection/pipeline.py scripts/classify_universe.py tests/test_run_provenance.py tests/test_classify_universe_cli.py
```

```bash
git commit -m "feat(pipeline): flag answers that rested on a failed SEC request, and write run_manifest.json beside the tables

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- src/delist_detection/manifest.py src/delist_detection/pipeline.py scripts/classify_universe.py tests/test_run_provenance.py tests/test_classify_universe_cli.py
```

---

### Task 15: Documentation

**Files:**
- Modify: `docs/data-flow.md`: the "## Caching" section (`:112-153`).
- Modify: `docs/superpowers/feature-spec.md`: §9's EFTS table row and its rule line `- A miss is never cached as an answer.`; append to §17.
- Modify: `CLAUDE.md`: the test count (`:31`), the commands block (`:37`), the "**SEC fair access.**" bullet (`:191-202`), the "**OpenFIGI refusals abort too.**" bullet's exit-3 sentence, and the "**The resolver cache is versioned.**" bullet (`:240-242`).
- Modify: `README.md`: "Project layout" (`:622-680`).

**Interfaces:**
- Consumes: the names from Tasks 1–14.
- Produces: docs only.

- [ ] **Step 1: `docs/data-flow.md`**

Replace the first two paragraphs of "## Caching", from "Every EDGAR JSON response is SHA1-keyed" through "…used for the run but never saved.", with:

```markdown
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
cached before a later Form 25 is therefore fetched again. Every cache file is
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
5xx after retries, a transport error or a non-JSON body raises and is never
cached. Each hit keeps `_id` and only the `_source` fields the library reads
(`EFTS_SOURCE_KEYS`). The EDGAR company-name search caches every answer, empties
included, for 7 days, and is retried like every other SEC request. When it
still fails, a cached hit list is served marked stale; with nothing to fall
back on, it raises instead of answering "no match".

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
```

Replace the exit-code paragraph (from "`scripts/classify_universe.py` exits `0`" to the end of the section) with:

```markdown
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
  run date therefore give byte-identical tables for any N.
- **Warm finders.** They use the run's own MIDAS and Nasdaq-halt clients, each
  behind one lock (`prefetch.Serialized`), so they take the same last-trade
  anchors as the sequential pass.
- **What stays on the main thread.** The fails-to-deliver downloads, OpenFIGI
  and the LLM extractor. OpenFIGI's per-security listing check is sent as
  batched mapping requests.
- **The rate limit.** Every thread shares one limiter (`edgar.SEC_LIMITER`:
  request starts at least 1/8 s apart). A 5xx or dropped connection pauses
  every thread together. The limit is machine-wide: each start also takes an
  `flock` on `~/.cache/delist_detection/sec_rate.lock`
  (`$DELIST_DETECTION_SEC_RATE_LOCK` overrides it). That file holds the last
  start time, so every SEC client on the machine that uses the same file (runs
  in any worktree, `verify_against_web.py`, `build_golden_fixtures.py`) stays
  under 8 requests/s together. A library caller that builds its own clients
  instead of using `default_clients` must call `edgar.use_machine_wide_limit()`
  itself.
- **Refusals and Ctrl-C.** A 403/429 on any thread stops the pool: no worker
  starts another SEC request, and the refusal is raised. A first Ctrl-C does
  the same and waits for each worker's in-flight request (at most 30 s). A
  second Ctrl-C stops that wait at once, but Python still waits for those
  requests before the process exits.

Each run writes `run_manifest.json` next to the tables:
- the run date (`as_of`), the code version and the worker count;
- per-endpoint SEC request counts, cache answers and latency (p50, p95, max);
- degraded answers (failed requests, stale copies), rejected and not-covered
  full-text searches;
- per-stage EDGAR requests and SEC data-file downloads.

A run that aborts leaves the previous manifest in place.

`scripts/classify_universe.py` exits:
- `0` on success;
- `2` when SEC or OpenFIGI refuses a request (`EdgarBlocked`/`OpenFigiBlocked`;
  no output written), or when the start-up checks fail (no `EDGAR_USER_AGENT`,
  an unusable rate-lock file);
- `3` when the run completed but `review.csv` has one or more `error` rows (one
  security or payout extraction raised and was logged instead of aborting) or
  `resolution_degraded` rows (an answer rested on a failed SEC request or a
  stale copy). Outputs are still written, and a banner naming the counts goes to
  stderr.
```

- [ ] **Step 2: `docs/superpowers/feature-spec.md`**

In §9's table, replace the EDGAR full-text search row's last cell `same` with `same; `cache/edgar/`, each answer held 7–365 days by how long after its window it was fetched (§17)`. Replace the rule `- A miss is never cached as an answer.` with:

```markdown
- Search evidence may be cached with a TTL; a resolver decision is never cached
  as a miss. EDGAR full-text-search and company-name-search answers, empties
  included, are cached with their fetch date and asked again when their TTL runs
  out (§17); every run re-derives a miss from that evidence with the current code.
```

Append to §17:

```markdown
- **SEC fair access across processes (§9, §11).** The 8 requests/s cap holds for
  the machine, not just the process: every SEC request takes an `flock`-guarded
  lock file outside the repo (`~/.cache/delist_detection/sec_rate.lock`, or
  `$DELIST_DETECTION_SEC_RATE_LOCK`) that holds the last start time, and waits
  1/8 s past it. `classify_universe.py --sec-workers N` (default 4, at most 8)
  prefetches on N threads under that one limit, and a 5xx pauses them all.
- **Determinism includes the run date (§11).** Every freshness rule reads one
  run date (`as_of`), so "same inputs and caches" means the same caches and the
  same `as_of`. For those, the tables are byte-identical for any `--sec-workers`:
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
```

- [ ] **Step 3: `CLAUDE.md`**

Run `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q` and replace `705` in the line `pytest                                    # full suite (705 tests, offline, no network)` with the number of tests it reports as passed.

After the `classify_universe.py --observations obs.csv --limit 20 --no-extract-payouts --no-midas --no-halts` line, add:

```bash
python scripts/classify_universe.py --observations obs.csv --sec-workers 1   # one SEC request at a time (default: 4 prefetch threads, max 8, one machine-wide 8 req/s limit)
```

Append to the "**SEC fair access.**" bullet:

```markdown
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
  never cached.
```

In the "**OpenFIGI refusals abort too.**" bullet, replace "Exit 3 is a completed run whose `review.csv` has one or more `error` rows (outputs still written; a banner goes to stderr with the count)." with "Exit 3 is a completed run whose `review.csv` has one or more `error` or `resolution_degraded` rows (an answer rested on a failed SEC request or a stale copy); outputs are still written, and a banner goes to stderr with the counts."

Replace the "**The resolver cache is versioned.**" bullet with:

```markdown
- **The resolver cache is versioned.** `cache/ticker_resolution.json` carries
  `{"__version__": 3, ...}` (versions 2 and 3 load; an older file is ignored, not
  trusted, and replaced on the next save) and never holds a miss or an answer
  that rested on a failed request or a stale copy. The pipeline writes it after
  each resolving stage and on the way out of a run.
```

- [ ] **Step 4: `README.md`**

In the "Project layout" `src/delist_detection/` list, after the `edgar.py` line, add:

```text
    prefetch.py           warm(): fills the SEC caches on fill-only threads ahead of each sequential stage
    manifest.py           run_manifest.json: run date, code version, workers, SEC traffic, degraded answers
```

In the `output/` list, after the `review.csv` line, add:

```text
    run_manifest.json     What the run rested on: as_of, code version, SEC requests/cache/latency per endpoint
```

In the `cache/` list, change the `edgar/*.json` line to:

```text
    edgar/*.json                 SEC JSON cache (re-runs are free); search answers held by a TTL
```

- [ ] **Step 5: Check and commit**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all pass (docs-only change).

```bash
git add docs/data-flow.md docs/superpowers/feature-spec.md CLAUDE.md README.md
```

```bash
git commit -m "docs: search evidence cached with a TTL, the machine-wide SEC limit, --sec-workers, run_manifest.json

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FAzBpwmveFZ3NvVbzUJzcg" -- docs/data-flow.md docs/superpowers/feature-spec.md CLAUDE.md README.md
```

---

### Task 16: Measure on the real universe (live)

**Model:** most capable (a live run that must respect SEC fair access).

This is the only task allowed network access, and only while no other SEC client runs on the machine. Every Bash call below that touches the network needs `allowed_domains: ["www.sec.gov", "data.sec.gov", "efts.sec.gov", "api.openfigi.com", "www.nasdaqtrader.com"]`.

**Files:** none changed. The results go into the PR description and the SDD ledger (`.superpowers/sdd/2026-09-23-sec-request-speed/progress.md`).

**Interfaces:**
- Consumes: the CLI (Tasks 11 and 14), and `run_manifest.json` with its per-stage lines.
- Produces: measured request counts, latency, wall time and peak memory, which replace the estimates in "Estimated effect", plus the determinism A/B.

- [ ] **Step 1: Make sure SEC is free, and set the shared lock**

Run: `pgrep -fl 'classify_universe|verify_against_web|build_golden_fixtures|regen_payout_fixtures'`
Expected: no output. If any process shows, stop and wait.

Every SEC client on the machine must use one lock file. If `~/.cache` is writable from this shell, use the default. Otherwise (a sandboxed agent shell), set the variable to a path that every SEC client started on this machine also uses, and export it in every shell below:

```bash
export DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -c "import os, time; from delist_detection.edgar import default_rate_lock_path as p; f = p(); print(f, 'idle' if not f.exists() or time.time() - os.path.getmtime(f) > 60 else 'IN USE')"`
Expected: the lock path and `idle`.

- [ ] **Step 2: Snapshot the caches**

Set `OBS=data/observations.csv`. Clone the current cache twice: once whole (the warm snapshot), and once with `edgar/` and the resolver memo removed (the cold snapshot, whose FTD, MIDAS, halt and OpenFIGI caches stay seeded).

```bash
cp -c -R cache "$TMPDIR/snap_warm"
cp -c -R cache "$TMPDIR/snap_cold"
rm -rf "$TMPDIR/snap_cold/edgar" "$TMPDIR/snap_cold/ticker_resolution.json"
```

If `cp -c` reports that cloning is not supported, use `cp -R` (slower; 2.3 GB).

- [ ] **Step 3: Determinism A/B from identical warm snapshots, in alternating order**

```bash
for run in w4a w1 w4b; do cp -c -R "$TMPDIR/snap_warm" "$TMPDIR/c_$run"; done
```

Run each of these as its own call, in this order:

```bash
PYTHONPATH=src /usr/bin/time -l ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations "$OBS" --cache-dir "$TMPDIR/c_w4a" --output-dir "$TMPDIR/o_w4a" --sec-workers 4 2> "$TMPDIR/w4a.log"
```

```bash
PYTHONPATH=src /usr/bin/time -l ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations "$OBS" --cache-dir "$TMPDIR/c_w1" --output-dir "$TMPDIR/o_w1" --sec-workers 1 2> "$TMPDIR/w1.log"
```

```bash
PYTHONPATH=src /usr/bin/time -l ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations "$OBS" --cache-dir "$TMPDIR/c_w4b" --output-dir "$TMPDIR/o_w4b" --sec-workers 4 2> "$TMPDIR/w4b.log"
```

Then compare:

```bash
for f in securities ticker_history cusip_history delistings payouts review; do cmp "$TMPDIR/o_w1/$f.csv" "$TMPDIR/o_w4a/$f.csv"; cmp "$TMPDIR/o_w1/$f.csv" "$TMPDIR/o_w4b/$f.csv"; done
diff -rq "$TMPDIR/c_w1/edgar" "$TMPDIR/c_w4a/edgar"
```

Expected:
- `cmp` prints nothing.
- `diff -rq` prints nothing, or only files whose `__fetched__` date differs if a run crossed midnight. Check that the three `run_manifest.json` files have the same `as_of`. If they differ, rerun within one day.
- Any other difference is a determinism bug. Drill it to root cause before going on.

Record from each `run_manifest.json`:
- wall time and "maximum resident set size" from the `.log`;
- `stages`, `sec_requests`, `cache_answers` and `degraded_answers`.

Also record how many memo keys each run added: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -c "import json,sys; a=json.load(open(sys.argv[1]))['entries']; b=json.load(open(sys.argv[2]))['entries']; print(len(set(b)-set(a)), 'new keys;', len(set(a)-set(b)), 'dropped')" "$TMPDIR/snap_warm/ticker_resolution.json" "$TMPDIR/c_w1/ticker_resolution.json"`. That number sizes the moving-key cost (review M7).

- [ ] **Step 4: Request mix and latency at 1, 4 and 8 workers from identical cold snapshots**

Each run sends ~1–3k SEC requests. Alternate the order so SEC's CDN does not favour one worker count:

```bash
for run in k8 k1 k4; do cp -c -R "$TMPDIR/snap_cold" "$TMPDIR/c_$run"; done
```

Run each as its own call, in the order `k8`, `k1`, `k4`, replacing `N` with 8, 1 and 4:

```bash
PYTHONPATH=src /usr/bin/time -l ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations "$OBS" --cache-dir "$TMPDIR/c_kN" --output-dir "$TMPDIR/o_kN" --limit 150 --sec-workers N 2> "$TMPDIR/kN.log"
```

Record for each run:
- the `issuer resolution` and `delisting search` lines;
- `latency_ms` per endpoint (p50, p95), especially `company_search` and `submissions`;
- any `degraded_answers`, and any 5xx or 403 in the log;
- wall time and peak RSS.

Compare the three `o_k*` directories with `cmp`, as in Step 3. Expected: identical.

- [ ] **Step 5: Report**

Replace the estimated rows of "Estimated effect" in the PR description with the measured numbers:
- the cold issuer-resolution speed-up per worker count (`k1` against `k4` and `k8`);
- the warm rerun time;
- the count of sequential refreshes (the `submissions` requests of the `w1` run);
- the moving-key count;
- peak RSS at 8 workers.

Note any endpoint whose p95 latency rises sharply with more workers. That caps the useful worker count below 8.

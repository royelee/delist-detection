# Perf-1: Faster Runs (fails-to-deliver store, EDGAR row building, LLM calls on their own threads) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A full run on a warm cache takes about 2 minutes, not 9; a full run that must make all 769 LLM merger-terms calls
takes under 7 minutes, not 43; a two-ticker run takes 4 seconds, not 46, once the parsed files exist (the first run on a cache builds them: about
49 s for the two-ticker run, about 45 s more for a full run). The tables do not change by one byte.

**Architecture:** Six changes, each its own commit, each measured against the reference output. (1) `sources/ftd_store.py`
parses each fails-to-deliver ZIP once into a SQLite file under the cache, and `FtdClient.rows` reads keys through its
indexes instead of re-parsing the text on every ask (76 asks per run). (2) `normalize_ticker` and `parse_day` return at once
for the shapes nearly every input has. (3) `EdgarClient.recent_filings` builds its rows from columns fetched once (it
allocated a default list per row: quadratic). (4) `--llm-workers` runs the LLM merger-terms calls on their own threads,
apart from `--sec-workers`: a worker thread only fills the answer file the unchanged sequential pass then reads, the shape
`prefetch.warm` already has. (5) The fails index slices a CUSIP's rows by bisect, `is_backfilled` asks for its 60-day
window only, and the name search starts at its first match by index instead of copying (or walking) a 1.5-million-entry list per query. (6) `FtdRow` keeps no per-row dict
and each date, CUSIP, symbol and description text is held once: peak memory falls by 1.4 GB.

**Tech Stack:** Python ≥3.10, standard library (`sqlite3` included), pandas (already used), pytest (offline).

**Base:** branch `faster-runs`, forked from `worktree-reset-1-scorecard` at `799d1bc` (2026-10-10). The six diffs were first built and measured at `6e43e09`, then rebased onto `c77365a` (hence the folder name `changes-c77365a/`); they apply unchanged at `799d1bc`. A number measured on an older commit is labelled with that commit. Full input (`data/observations.csv`), `--as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm`, one machine, one run at a time.

**Evidence:** `docs/superpowers/plans/research/2026-10-10-faster-runs/RESULTS.md` (every measurement) and
`changes-c77365a/` beside it (the six diffs this plan embeds, as files for `git apply`). The profile that started this
work is `docs/superpowers/plans/research/2026-10-10-faster-runs/run-time-profile.md`.

## Independent check (2026-10-10)

The agent that wrote this plan built and measured the changes. The controller then checked them separately:

1. The six diffs in `changes-c77365a/` apply in order to a clean copy of `c77365a`, and the suite gives 3,793 passed,
   44 xfailed (measured). The branch moved five more commits during the check, to `5fee062`. The same diffs apply
   there unchanged, and the suite gives 3,823 passed, 44 xfailed (that commit's own count plus the 76 new tests).
2. At `6e43e09`, with the six changes as first written: a warm full run took 134.4 s (4,074 MB peak) with all 14
   tables byte-identical to the reference, no SEC request and no LLM call (measured).
3. At `6e43e09`, with the later rework of `ftd.py`, `ftd_store.py` and `cik_lookup.py` (one line parser, the name
   search by index) put on top: warm 128.2 s, and 160.6 s from a cache with no parsed files, which exercises the new
   store build. Tables byte-identical both times (measured). The branch did not change those three files between
   `6e43e09` and `c77365a`.
4. Not shown by any full run: the merge of the per-file lock with the head's answer counting in `_llm_extract`, and the
   new argument lists. Unit tests cover them. Task 7 Step 0 closes this.

## Review (2026-10-10) and what changed because of it

An independent reviewer read this plan and the six diffs at `cf1ee89`. It found no case where a change alters a table
or crashes a run: a fuzz of the store against the old line rule (about 4,000 odd lines, four filters) and of
`normalize_ticker`/`parse_day` (800,000 strings) gave 0 differences, and 8 threads and 12 processes building one store
at once all read the same rows. It found these problems, each now handled as stated:

1. **The reference run came last.** Every task compares with a reference that only the last task made. It is now
   Task 0, with its commands and its pass condition.
2. **The doc steps were not specified.** Task 4 Step 6 and Task 7 now name each file and passage, and Task 7 measures
   before it writes a figure into a doc.
3. **A store could go stale when the line rule changes.** The store holds the rule's output (a normalized symbol),
   and its fingerprint did not cover the rule. Reproduced: change `normalize_ticker`, and the store still answers
   with the old spelling. Task 1 Step 4b puts a digest of the rule in the fingerprint, with a test.
4. **Tests.** The tests of Tasks 2 and 3 and the name-search test of Task 5 pass before the change too: they pin
   behaviour, and the harness measures the speed. That is the right kind of test for a change that must not alter
   behaviour. Task 1 Step 4b adds the missing test for two builders at once.
5. **LLM calls cannot be cancelled.** `prefetch.warm` stops a worker at its next SEC request, and an LLM call is not
   one. `llm_client.py` sets no timeout (the `openai` client's default is 600 s, with 2 retries of its own, inside
   up to 3 attempts of ours), so an abort or Ctrl-C waits for every call in flight. This is true today at the default
   `--sec-workers 4`; this plan raises the number of threads. Ruling: cap `--llm-workers` at 16 (16 was run with the
   stand-in client, 8 live), and say in the docs that an LLM call in flight is waited for (Task 4 Step 6). A client
   timeout changes behaviour this plan cannot prove unchanged, so it is an open point below, not a task.
6. **Stale comments.** `MAX_SEC_WORKERS`'s comment and the `warm` docstring are corrected in Task 4 Step 6.
7. **Smaller points** are fixed in place: the manifest fields a run may differ in include `.seconds`; constraint 4
   says what must not be loaded; the Goal names the first run's cost; a cache older than 7 days refetches the fails
   index page (harness note).

## Open points for the owner

1. **Disk.** The parsed fails files add 1.9 GB to the cache, beside 0.6 GB of ZIPs.
2. **`--sec-workers 1` no longer means one SEC request in flight** when `--extract-merger-terms-llm` is on and a
   candidate filing's text is not cached: the LLM threads fetch it, up to `--llm-workers` at once, inside the shared
   8 requests/s limit. `--sec-workers 1 --llm-workers 1` restores the old behaviour.
3. **`--llm-workers` defaults to 8, at most 16.** Twenty live calls at 8 workers met no rate limit. More than 8 was
   not tried live.
4. **A timeout on the LLM client.** None is set today. A value of 60 to 120 s would bound the wait on an abort and
   the cost of a stalled call. It is a behaviour change (a slow call that succeeds today would fail), so it is left to the owner.
5. **`merger_terms` counts.** `asked` counts an answer only when the sequential pass reads it. A warm thread that
   pays for an answer the sequential pass never reads (an EDGAR read that failed on one thread only) is not counted,
   and a call that fails on both passes counts `degraded:llm_call` twice. No table depends on either.
6. **A long-lived process.** `sys.intern` keeps the fails texts for the life of the process on some Python versions.
   A command-line run ends first. A library caller that builds many indexes in one process keeps those texts.
7. **A read-only cache directory** now stops a run at the first fails read (the store cannot be written).

## Global Constraints

1. **The output must not change.** After every task, a full-input run on a fresh copy of the warm reference cache must
   write tables byte-identical to the reference output: every CSV in the output folder and in `contract/`, and
   `scorecard.json`. `run_manifest.json` may differ only in `code_version`, the `cache_answers.*` counters, the
   `latency_ms.*` and `sec_requests.*` request counters, per-stage `edgar_requests` and per-stage `seconds` (a request
   or a cache answer counted differently, or a time, never a table); it also records `sec_workers`, which differs when the run is given another
   value. A table that differs means the change is wrong: fix it or drop it. Never accept a difference because it looks harmless.
2. **The test suite passes.** `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""` gives the untouched tree's result plus the new
   tests (at `6e43e09` 3,522 passed, 45 xfailed, and 3,592 passed, 45 xfailed after the six tasks; at `c77365a` 3,717 passed, 44 xfailed, and 3,793 passed, 44 xfailed after the six tasks). Tests are offline; add no network.
3. **Output does not depend on the number of workers.** `--sec-workers N` and `--llm-workers N` change timing only: a
   worker thread fills a cache entry the sequential pass would fill itself, and the tables are identical for 1 worker and for many.
4. **Memory.** The peak must not grow: the store must never load every row of the fails files (25 million) as Python
   objects; a run holds only the rows its asks return (about 8 million for the full input). The parsed copy of the
   fails files lives on disk under the cache (`sec_data/ftd/parsed/`), rebuilds itself when a ZIP is new or changed, and is
   written through `atomic_io`. Peak resident memory of the full run is measured before and after (`resource.getrusage`, in the harness below).
5. No new dependencies. Match the surrounding code: its naming and its plain-sentence docstrings.
6. LLM calls cost money: measure the concurrent stage with the stand-in client below, and make one small live check
   (at most 20 calls). Do not send the 769 filings again.
7. Agent sandbox: set `DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock` and allow the seven
   hosts (data.sec.gov, www.sec.gov, efts.sec.gov, api.openfigi.com, api.nasdaq.com, www.nasdaqtrader.com,
   api.anthropic.com or the host in `OPENAI_BASE_URL`). Only one SEC client at a time.

## Verification harness (used by every task's full-run step)

Set once per shell. `REF` is the folder of reference tables written by the untouched code on a warm cache, and
`CACHE_FULL` the warm cache it ran on. **"Warm" here means no SEC request and no LLM call. It does not mean offline:** `listing_status.listed_today` calls `figi.map(..., use_cache=False)`, so every full run asks OpenFIGI for listing status even on a warm cache; `api.openfigi.com` must be reachable (without it the run exits 4) and every time below includes those calls. Never write to either folder.

A cache copy older than 7 days is not warm: `sec_http.get_text` fetches the fails-to-deliver index page again once its copy is a week old, whatever `--as-of` says. Take the reference and make the comparison runs within the same week.

```bash
PY=~/miniconda3/envs/rdagent4qlib/bin/python
CACHE_FULL=<warm cache>            # e.g. scratchpad/cache-full
REF=<reference tables>             # e.g. scratchpad/out-full
```

`timeit.py` runs a command and prints wall time and the child's peak resident memory:

```python
import resource, subprocess, sys, time
t = time.time()
rc = subprocess.call(sys.argv[1:])
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
print(f"WALL {time.time()-t:.1f}s  MAXRSS {ru.ru_maxrss/1e6:.0f} MB  USER {ru.ru_utime:.0f}s SYS {ru.ru_stime:.0f}s", file=sys.stderr)
sys.exit(rc)
```

(`ru_maxrss` is bytes on macOS; divide by 1e3 for MB on Linux.) The full-run command, from the repository root, on a
fresh copy of the cache (`cp -cR` is a copy-on-write copy on macOS; use `cp -a` elsewhere):

```bash
N=<tag>; rm -rf /tmp/run-$N; mkdir /tmp/run-$N; cp -cR $CACHE_FULL /tmp/run-$N/cache      # fresh copy each time
DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src \
  $PY timeit.py $PY scripts/classify_universe.py --observations data/observations.csv --output-dir /tmp/run-$N/out \
  --cache-dir /tmp/run-$N/cache --as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm \
  --id-baseline <the committed output/securities.csv> > /tmp/run-$N/run.log 2>&1; tail -3 /tmp/run-$N/run.log
```

`cmp.py $REF <out dir>` compares the tables with `REF` and lists any manifest field that differs outside the allowed ones:

```python
import json, subprocess, sys
ref, out = sys.argv[1], sys.argv[2]
r = subprocess.run(['diff', '-r', '-q', '-x', 'run_manifest.json', ref, out], capture_output=True, text=True)
print('TABLES', 'IDENTICAL' if r.returncode == 0 else 'DIFFER\n' + r.stdout)
a = json.load(open(ref + '/run_manifest.json')); b = json.load(open(out + '/run_manifest.json'))


def flat(d, p=''):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flat(v, p + k + '.')
        else:
            yield p + k, v


fa, fb = dict(flat(a)), dict(flat(b))
ignore = ('code_version', 'cache_answers.', 'latency_ms.', 'sec_requests.', '.edgar_requests', '.seconds')
for k in sorted(set(fa) | set(fb)):
    if fa.get(k) != fb.get(k) and not any(i in k for i in ignore):
        print('MANIFEST DIFF', k, fa.get(k), fb.get(k))
print('manifest checked')
```

Expected after every task: `TABLES IDENTICAL` and `manifest checked` with no `MANIFEST DIFF` line.

The stand-in LLM client (`standin.py`) runs the same command with every call sleeping 2.7 s and answering from the saved
reference answer of the same cache file name, so the tables stay identical and the timing is realistic. Save the 769
answers (`cp $CACHE_FULL/llm/*_claude-sonnet-5-5_v3_* /tmp/llm-ref/`), run on a cache copy without them:

```python
import atexit, json, os, runpy, sys, threading, time
from pathlib import Path
from delist_detection.terms import llm_merger_extractor as m
from delist_detection.sources import llm_client

REF, SLEEP = Path(os.environ["LLM_REF"]), float(os.environ.get("LLM_SLEEP", "2.7"))
_local, _lock = threading.local(), threading.Lock()
stats = {"calls": 0, "active": 0, "max_active": 0}
orig = m.LLMMergerTermsExtractor.cache_path


def cache_path(self, filing, record):
    p = orig(self, filing, record)
    _local.name = p.name
    return p


class StandIn:
    model = "claude-sonnet-5-5"

    def extract(self, system, user, schema):
        with _lock:
            stats["calls"] += 1
            stats["active"] += 1
            stats["max_active"] = max(stats["max_active"], stats["active"])
        try:
            time.sleep(SLEEP)
            return json.loads((REF / _local.name).read_text())
        finally:
            with _lock:
                stats["active"] -= 1


m.LLMMergerTermsExtractor.cache_path = cache_path
llm_client.default_llm_client = lambda model=None: StandIn()
atexit.register(lambda: print(f"STANDIN calls={stats['calls']} max_concurrent={stats['max_active']}", file=sys.stderr))
sys.argv = ["classify_universe.py", *sys.argv[1:]]
runpy.run_path("scripts/classify_universe.py", run_name="__main__")
```

```bash
rm -f /tmp/run-$N/cache/llm/*_claude-sonnet-5-5_v3_*
LLM_REF=/tmp/llm-ref DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src \
  $PY timeit.py $PY standin.py --observations data/observations.csv --output-dir /tmp/run-$N/out --cache-dir /tmp/run-$N/cache \
  --as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm --id-baseline <the committed output/securities.csv> --llm-workers 8
```

Expected: `STANDIN calls=769 max_concurrent=8` (769 calls: none is paid for twice), `TABLES IDENTICAL`.

## Rulings this plan makes

0. **One reader of a fails line.** `ftd_store.split_line` is the single rule for "one line to fields"; `ftd.parse_ftd_lines` (kept for the fixture scripts and tests) calls it, and the store's build calls it. It lives in `ftd_store` because `ftd` already imports that module (no cycle). Measured: building the store for 30 zips took 2.67–2.73 s before and 2.67–2.69 s after, so the shared function costs nothing measurable. `parse_ftd_lines` now splits every line before it filters (it filtered on symbol and CUSIP first); it is no longer on the run's path. The equivalence tests do not use the shared function as their reference: `tests/test_ftd_store.py` keeps a whole copy of the original line rule (`_reference_lines`) and compares both the store and `parse_ftd_lines` with it, and `ftd_equiv.py` does the same over the real ZIPs.
1. **A SQLite file per ZIP, not one database.** Each ZIP is its own unit of invalidation (size and modification time are
   stored in the file), its own atomic replace, and its own failure (a bad ZIP is downloaded again once, as before). The
   cost is 435 small files (1.9 GB beside 0.6 GB of ZIPs) in `sec_data/ftd/parsed/`; a cache older than this change simply builds them on first use
   (about 45 s of CPU for the whole set, measured once).
2. **Row order is the ZIP's.** `FtdIndex` sorts a key's rows by (date, CUSIP, symbol) with a stable sort, so rows that tie keep the
   order they were added in. The store returns rows in the ZIP's member and line order (SQLite `rowid`), exactly what the parser gave.
3. **NaN and -0.0 prices stay as they were.** SQLite stores NaN as NULL and -0.0 as 0.0; the store keeps those two as text
   and converts back. (None occurs in SEC's files today; the guard costs nothing and the real-ZIP equivalence run covers it.)
4. **LLM workers are a separate knob.** A call waits on the model, not on SEC, so `--llm-workers` (default 8, at most 16)
   does not borrow `--sec-workers`. Library callers that give no `llm_workers` keep the old behaviour (the SEC worker count).
   The warm LLM threads still read EDGAR through the shared 8 requests/s limiter, so SEC's limit holds whatever the count.
5. **No memo of `recent_filings` and no cache of parsed submissions JSON.** Both would save about 15 s more of a 131 s run,
   but they hold large objects across calls whose freshness rules (`fresh_after`, `fill_only`, stale copies) the change would have to mirror. Not worth the risk here.


---

### Task 0: The reference run at the fork commit (the controller runs this; live network)

**Files:** none in the repository. It makes `CACHE_FULL` and `REF`, which Step 5 of every later task reads.

No full run had been made on this code, so no cache was warm for it: at `c77365a` a run of the untouched tree on a copy
of the PR #7 worktree's cache lacked 141 filing texts, 9 full-text searches, 25 Nasdaq halt days and 15 LLM answers
(`docs/superpowers/plans/research/2026-10-10-faster-runs/RESULTS.md`). This task fetches them once and takes the reference from the untouched code.

- [ ] **Step 1: The untouched code and a cache copy.** Outside the repository (`X` is any scratch folder):

```bash
git archive 799d1bc | tar xf - -C $X/base            # the untouched code; link the repo's .env into it
cp -cR <the PR #7 worktree>/cache $X/cache-warm      # a copy: never write to that worktree's cache
mkdir -p $X/id-baseline/contract                     # one fixed id baseline for every run of this plan
cp $X/base/output/securities.csv $X/id-baseline/
cp $X/base/output/contract/security_history.csv $X/id-baseline/contract/
```

- [ ] **Step 2: Warm it, live.** Allow all seven hosts of Global Constraint 7. It may send about 150 SEC requests and
15 LLM calls (`claude-sonnet-5-5`, the model `.env` names). No other SEC client may be running outside the agent
sandbox; agent runs share the one lock file.

```bash
cd $X/base && DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=$X/base/src \
  $PY timeit.py $PY scripts/classify_universe.py --observations data/observations.csv --output-dir $X/out-warm \
  --cache-dir $X/cache-warm --as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm \
  --id-baseline $X/id-baseline/securities.csv > $X/warm.log 2>&1
```

Repeat until a run needs nothing new: exit 0, and in `run_manifest.json` no `sec_requests` entry, `merger_terms`
`asked` 0 and `failed` 0, no `degraded_answers`, `resolution_degraded` 0, no `warm_failed`.

- [ ] **Step 3: The reference.** The first run of Step 2 that meets that condition is the reference: its output
folder is `REF`, and `$X/cache-warm` as that run left it is `CACHE_FULL`. Make one more run on a fresh copy of
`CACHE_FULL` with `api.openfigi.com` alone allowed and compare it with `REF` (`cmp.py`): `TABLES IDENTICAL`. That shows
the untouched code repeats itself, so a later difference is the change's. Record the wall time and peak memory of
that run: they are the "before" figures at `799d1bc`.

- [ ] **Step 4: The stand-in needs its answers.** `cp $X/cache-warm/llm/*_claude-sonnet-5-5_v3_* $X/llm-ref/`
(the harness's `LLM_REF`). Count them: the stand-in runs of Task 4 and Task 7 must report that many calls, whatever the
number is at this commit (it was 769 at `6e43e09`).

---

### Task 1: Parse each fails-to-deliver ZIP once (`sources/ftd_store.py`)

**Files:**
- Create: `src/delist_detection/sources/ftd_store.py`
- Modify: `src/delist_detection/sources/atomic_io.py` (`write_atomic_with`), `src/delist_detection/sources/ftd.py` (`FtdClient.rows`; the `io` import goes)
- Test: `tests/test_ftd_store.py` (new)

**Interfaces:**
- Consumes: `ftd.parse_ftd_lines` (the rule the store must keep), `identifiers.normalize_ticker`, `atomic_io.clean_orphan_temps`.
- Produces: `ftd_store.ensure(zip_path) -> Path` (the parsed copy, built first if missing or out of date), `ftd_store.split_line(line)` (the one reader of a fails line: `(date, CUSIP, symbol, description, price)` or `None`; `ftd.parse_ftd_lines` now uses it too), `ftd_store.select(db, *, symbols=None, cusips=None)` (tuples `(date, cusip, symbol, description, price)` in the ZIP's order), `ftd_store.store_path`, `atomic_io.write_atomic_with(path, write)`.

- [ ] **Step 1: Write the failing tests**

The tests below are the test part of the working diff (`docs/superpowers/plans/research/2026-10-10-faster-runs/changes-c77365a/01-ftd-store.diff`); apply them with `git apply` (they add or extend
the files named), or copy the code.

```diff
diff --git a/tests/test_ftd_store.py b/tests/test_ftd_store.py
new file mode 100644
index 0000000..53a5546
--- /dev/null
+++ b/tests/test_ftd_store.py
@@ -0,0 +1,150 @@
+"""The parsed copy of a fails-to-deliver ZIP gives back what `parse_ftd_lines` reads from it."""
+from __future__ import annotations
+
+import io
+import math
+import os
+import zipfile
+
+import pytest
+
+from delist_detection.sources import ftd_store
+from delist_detection.sources.atomic_io import write_atomic_with
+from delist_detection.sources.ftd import FtdRow, parse_ftd_lines
+from delist_detection.vocabulary.identifiers import normalize_ticker
+
+HEADER = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
+ODD = (HEADER
+       + "20240102|00206R102|T|500|AT&T INC COM|16.78\n"
+       + "20240102|00206r102|brk.b|500|BERKSHIRE | CLASS B |nan\n"        # lower case, separator, a "|" in the text, NaN
+       + "20240103|037833100|AAPL|10|APPLE INC|-0.0\n"
+       + "20240103|037833100|AAPL|10|APPLE INC|\n"                          # no price
+       + "20240103|037833100|AAPL|10|APPLE INC|1e400\n"                     # infinity
+       + "20240104|G0000Z000|ZZ ZZ|1|CAF\xc9 \xb2 LTD|3.5\r\n"              # latin-1 text, a space in the symbol
+       + "2024010|BADDATE|X|1|SHORT DATE|1.0\n"
+       + "20240104|SHORT|X|1\n"
+       + "Trailer record count 7\n"
+       + "20240102|00206R102|T|700|AT&T INC COM|16.78\n")                   # the same row again: kept, as the parser does
+
+
+def _write_zip(path, members: dict[str, str]) -> None:
+    buf = io.BytesIO()
+    with zipfile.ZipFile(buf, "w") as z:
+        for name, text in members.items():
+            z.writestr(name, text.encode("latin-1"))
+    path.write_bytes(buf.getvalue())
+
+
+def _reference_lines(lines, *, symbols=None, cusips=None):
+    """The line rule as `parse_ftd_lines` first wrote it, kept here whole so the store and the shared `split_line`
+    are checked against an independent copy, not against each other."""
+    for line in lines:
+        parts = line.rstrip("\r\n").split("|")
+        if len(parts) < 6:
+            continue
+        d = parts[0].strip()
+        if len(d) != 8 or not d.isdigit():
+            continue
+        cusip = parts[1].strip().upper()
+        symbol = normalize_ticker(parts[2])
+        if symbols is not None or cusips is not None:
+            if not ((symbols is not None and symbol in symbols) or (cusips is not None and cusip in cusips)):
+                continue
+        try:
+            price = float(parts[-1].strip())
+        except ValueError:
+            price = None
+        yield FtdRow(f"{d[:4]}-{d[4:6]}-{d[6:]}", cusip, symbol, "|".join(parts[4:-1]).strip(), price)
+
+
+def _old(path, **filters):
+    rows = []
+    with zipfile.ZipFile(path) as z:
+        for info in z.infolist():
+            if not info.is_dir():
+                with z.open(info) as fh:
+                    rows.extend(_reference_lines(io.TextIOWrapper(fh, encoding="latin-1"), **filters))
+    return rows
+
+
+def _same(got, want) -> bool:
+    """Row lists equal, NaN prices and the sign of a zero price included."""
+    return len(got) == len(want) and all(
+        (g.date, g.cusip, g.symbol, g.description) == (w.date, w.cusip, w.symbol, w.description)
+        and (g.price is None) == (w.price is None)
+        and (g.price is None or (math.isnan(g.price) and math.isnan(w.price))
+             or (g.price == w.price and math.copysign(1, g.price) == math.copysign(1, w.price)))
+        for g, w in zip(got, want))
+
+
+@pytest.mark.parametrize("filters", [
+    {}, {"symbols": {"T"}}, {"symbols": {"BRK-B", "AAPL"}}, {"cusips": {"037833100"}},
+    {"symbols": {"T"}, "cusips": {"037833100"}}, {"symbols": set()}, {"cusips": set(), "symbols": {"ZZ-ZZ"}},
+    {"symbols": {"NOPE"}}])
+def test_store_gives_the_rows_the_parser_gives(tmp_path, filters):
+    zip_path = tmp_path / "cnsfails202401a.zip"
+    _write_zip(zip_path, {"a.txt": ODD, "b.txt": HEADER + "20240105|00206R102|T|5|AT&T INC COM|17.0\n"})
+    got = [FtdRow(*f) for f in ftd_store.select(ftd_store.ensure(zip_path), **filters)]
+    assert _same(got, _old(zip_path, **filters))
+    if not filters:
+        assert len(got) == 8
+
+
+def test_store_is_built_once_and_again_when_the_zip_changes(tmp_path):
+    zip_path = tmp_path / "cnsfails202401a.zip"
+    _write_zip(zip_path, {"a.txt": ODD})
+    db = ftd_store.ensure(zip_path)
+    assert db == tmp_path / "parsed" / "cnsfails202401a.zip.sqlite"
+    built = db.stat().st_mtime_ns
+    assert ftd_store.ensure(zip_path) == db and db.stat().st_mtime_ns == built      # unchanged: not built again
+    _write_zip(zip_path, {"a.txt": HEADER + "20240110|00206R102|T|5|AT&T INC COM|17.0\n"})
+    ftd_store.ensure(zip_path)
+    assert [r[0] for r in ftd_store.select(db)] == ["2024-01-10"]
+
+
+def test_a_cut_off_store_is_built_again(tmp_path):
+    zip_path = tmp_path / "cnsfails202401a.zip"
+    _write_zip(zip_path, {"a.txt": ODD})
+    db = ftd_store.ensure(zip_path)
+    db.write_bytes(db.read_bytes()[:300])
+    assert len(list(ftd_store.select(ftd_store.ensure(zip_path)))) == 7
+
+
+def test_a_bad_zip_raises_and_leaves_no_store(tmp_path):
+    zip_path = tmp_path / "cnsfails202401a.zip"
+    zip_path.write_bytes(b"not a zip")
+    with pytest.raises(zipfile.BadZipFile):
+        ftd_store.ensure(zip_path)
+    assert not (tmp_path / "parsed" / "cnsfails202401a.zip.sqlite").exists()
+    assert not list((tmp_path / "parsed").glob(".*"))
+
+
+def test_write_atomic_with_replaces_only_on_success(tmp_path):
+    target = tmp_path / "x.bin"
+    target.write_bytes(b"old")
+    with pytest.raises(RuntimeError):
+        write_atomic_with(target, lambda tmp: (tmp.write_bytes(b"new, cut"), (_ for _ in ()).throw(RuntimeError()))[0])
+    assert target.read_bytes() == b"old" and os.listdir(tmp_path) == ["x.bin"]
+    write_atomic_with(target, lambda tmp: tmp.write_bytes(b"new"))
+    assert target.read_bytes() == b"new" and os.listdir(tmp_path) == ["x.bin"]
+
+
+def test_a_build_cut_off_by_a_killed_process_is_cleaned_up_by_the_next_one(tmp_path):
+    import subprocess
+    import sys
+    dead = subprocess.Popen([sys.executable, "-c", ""])
+    dead.wait()
+    zip_path = tmp_path / "cnsfails202401a.zip"
+    _write_zip(zip_path, {"a.txt": ODD})
+    (tmp_path / "parsed").mkdir()
+    orphan = tmp_path / "parsed" / f".cnsfails202401a.zip.sqlite.{dead.pid}.1.tmp"
+    orphan.write_bytes(b"SQLite format 3\x00 cut off")
+    ftd_store.ensure(zip_path)
+    assert not orphan.exists()
+
+
+
+@pytest.mark.parametrize("filters", [{}, {"symbols": {"T"}}, {"cusips": {"037833100"}}, {"symbols": {"BRK-B"}, "cusips": {"G0000Z000"}}])
+def test_parse_ftd_lines_and_the_reference_rule_agree(filters):
+    lines = ODD.splitlines(keepends=True)
+    assert _same(list(parse_ftd_lines(lines, **filters)), list(_reference_lines(lines, **filters)))
```

- [ ] **Step 2: Run them and see them fail**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_ftd_store.py tests/test_ftd.py tests/test_atomic_io.py
```

Expected: collection error `ImportError: cannot import name 'ftd_store'` (and `write_atomic_with`) in `tests/test_ftd_store.py`; verified on the untouched tree.

- [ ] **Step 3: Implement**

`write_atomic_with` first (`atomic_io.py`), then the new module, then the change to `FtdClient.rows` and `parse_ftd_lines`:

```diff
diff --git a/src/delist_detection/sources/atomic_io.py b/src/delist_detection/sources/atomic_io.py
index 21b2f00..fac1f53 100644
--- a/src/delist_detection/sources/atomic_io.py
+++ b/src/delist_detection/sources/atomic_io.py
@@ -1,8 +1,10 @@
 """Atomic file writes: a reader sees the old file or the complete new one, never a part.
 
-Two shapes. `write_atomic` replaces one cache file with data it is handed,
+Three shapes. `write_atomic` replaces one cache file with data it is handed,
 durably, through a temp file named for its writer (so `clean_orphan_temps` can
-remove a killed writer's leftover). `replace_on_success`/`replace_all_on_success`
+remove a killed writer's leftover); `write_atomic_with` does the same for a file
+a library writes itself (a SQLite database), handing the writer the temp path.
+`replace_on_success`/`replace_all_on_success`
 yield temp paths for a block to write, and replace their targets only when the
 block finishes -- all of them together, for a group of output tables.
 """
@@ -11,7 +13,7 @@ from __future__ import annotations
 import os
 import re
 import threading
-from collections.abc import Iterator, Sequence
+from collections.abc import Callable, Iterator, Sequence
 from contextlib import contextmanager
 from pathlib import Path
 
@@ -55,6 +57,28 @@ def write_atomic(path: Path, data: str | bytes) -> None:
     _fsync_dir(path.parent)
 
 
+def write_atomic_with(path: Path, write: Callable[[Path], object]) -> None:
+    """Replace `path` with the file `write(tmp)` builds at the temp path it is
+    given: `write_atomic` for a file only a library can write (it must close its
+    handle before it returns). The temp file is named and fsynced as
+    `write_atomic`'s, so a reader sees the old file or the complete new one, and
+    `clean_orphan_temps` removes a killed writer's leftover. Nothing is replaced
+    when `write` raises."""
+    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
+    try:
+        tmp.unlink(missing_ok=True)
+        write(tmp)
+        fd = os.open(tmp, os.O_RDONLY)
+        try:
+            os.fsync(fd)
+        finally:
+            os.close(fd)
+        os.replace(tmp, path)
+    finally:
+        tmp.unlink(missing_ok=True)
+    _fsync_dir(path.parent)
+
+
 def _pid_alive(pid: int) -> bool:
     """False only when no process has `pid`. True when one may: it is running,
     it belongs to another user (EPERM), or `pid` is no number this OS can hold
diff --git a/src/delist_detection/sources/ftd.py b/src/delist_detection/sources/ftd.py
index 120700d..308c751 100644
--- a/src/delist_detection/sources/ftd.py
+++ b/src/delist_detection/sources/ftd.py
@@ -19,7 +19,6 @@ the class ticker (sub-plan 5h).
 from __future__ import annotations
 
 import calendar
-import io
 import logging
 import re
 import threading
@@ -32,6 +31,7 @@ from datetime import date, timedelta
 from pathlib import Path
 from typing import Any, Protocol
 
+from . import ftd_store
 from .atomic_io import clean_orphan_temps
 from ..vocabulary.identifiers import bare_ticker, class_suffix, description_class_letter, normalize_ticker
 from ..vocabulary.names import names_agree
@@ -141,30 +141,21 @@ def parse_ftd_lines(lines: Iterable[str], *, symbols: set[str] | None = None,
     """Rows from FTD text lines; header, trailer and malformed lines are skipped.
     `symbols`/`cusips` each filter independently when given (a row passes if it
     matches either one); both left `None` (the default) means no filtering at
-    all. Filtered on symbol/CUSIP before an `FtdRow` is built (fast path).
+    all. Each line is read by `ftd_store.split_line`.
     `counts["rows"]`, when given, counts every well-formed data line, filtered
     out or not."""
     for line in lines:
-        parts = line.rstrip("\r\n").split("|")
-        if len(parts) < 6:
-            continue
-        d = parts[0].strip()
-        if len(d) != 8 or not d.isdigit():
+        fields = ftd_store.split_line(line)
+        if fields is None:
             continue
         if counts is not None:
             counts["rows"] += 1
-        cusip = parts[1].strip().upper()
-        symbol = normalize_ticker(parts[2])
         if symbols is not None or cusips is not None:
-            sym_hit = symbols is not None and symbol in symbols
-            cus_hit = cusips is not None and cusip in cusips
+            sym_hit = symbols is not None and fields[2] in symbols
+            cus_hit = cusips is not None and fields[1] in cusips
             if not (sym_hit or cus_hit):
                 continue
-        try:
-            price: float | None = float(parts[-1].strip())
-        except ValueError:
-            price = None
-        yield FtdRow(f"{d[:4]}-{d[4:6]}-{d[6:]}", cusip, symbol, "|".join(parts[4:-1]).strip(), price)
+        yield FtdRow(*fields)
 
 
 class FtdClient:
@@ -190,22 +181,12 @@ class FtdClient:
         dest = self.dir / url.rsplit("/", 1)[-1]
         path = download(url, dest, session=self.session, user_agent=self.user_agent)
         try:
-            z = zipfile.ZipFile(path)
+            store = ftd_store.ensure(path)
         except zipfile.BadZipFile:
             path.unlink(missing_ok=True)          # a truncated download: fetch it again once
-            z = zipfile.ZipFile(download(url, dest, session=self.session, user_agent=self.user_agent))
-        with z:
-            # Every file member is read, whatever its name: from 2022-05 on the SEC
-            # ships one member without an extension ("cnsfails202401a").
-            for info in z.infolist():
-                if info.is_dir():
-                    continue
-                counts: Counter = Counter()
-                with z.open(info) as fh:
-                    yield from parse_ftd_lines(io.TextIOWrapper(fh, encoding="latin-1"),
-                                               symbols=symbols, cusips=cusips, counts=counts)
-                if not counts["rows"]:
-                    _log.warning(f"{dest.name}: member {info.filename!r} holds no fails-to-deliver rows; skipped")
+            store = ftd_store.ensure(download(url, dest, session=self.session, user_agent=self.user_agent))
+        for fields in ftd_store.select(store, symbols=symbols, cusips=cusips):
+            yield FtdRow(*fields)
 
 
 class FtdSource(Protocol):
diff --git a/src/delist_detection/sources/ftd_store.py b/src/delist_detection/sources/ftd_store.py
new file mode 100644
index 0000000..858f0fa
--- /dev/null
+++ b/src/delist_detection/sources/ftd_store.py
@@ -0,0 +1,185 @@
+"""A fails-to-deliver ZIP, parsed once into a SQLite file and read by symbol and CUSIP.
+
+`FtdClient.rows` used to read a ZIP's text again for every ask: a run asks 70 times or more, each over
+hundreds of files, and parsing the same 25 million lines each time was most of a warm run. Here a ZIP is
+parsed once, into `parsed/<zip name>.sqlite` beside it, and an ask reads only the rows of the keys it names
+through the file's indexes. A row is read back exactly as `ftd.parse_ftd_lines` returns it, in the order the
+ZIP holds it (the member order, then the line order), which `FtdIndex` depends on when two rows tie on
+(date, CUSIP, symbol).
+
+The file is a cache, never a source: it records the ZIP's size and modification time and the store's version,
+and is built again when any of them differs (a ZIP downloaded again, a change to the parsed form). It is written
+through `atomic_io.write_atomic_with`, so a reader sees the old file or the complete new one, and a killed
+writer's temp file is cleaned up with the others.
+
+One file holds one ZIP: the description, symbol and CUSIP texts once each (`descr`, `sym`, `cus`), and a row
+as small integers into them. A price that SQLite would not give back unchanged (NaN, which it stores as NULL,
+and -0.0, which it stores as 0.0) is kept as text.
+"""
+from __future__ import annotations
+
+import io
+import logging
+import math
+import sqlite3
+import zipfile
+from collections.abc import Iterator
+from pathlib import Path
+
+from .atomic_io import clean_orphan_temps, write_atomic_with
+from ..vocabulary.identifiers import normalize_ticker
+
+_log = logging.getLogger(__name__)
+
+STORE_VERSION = 1
+_CHUNK = 500                  # keys per `IN (...)`: well under SQLite's variable limit
+
+_ROW_SELECT = ("SELECT r.rowid, r.day, c.text, s.text, d.text, r.price FROM rows r "
+               "JOIN cus c ON c.id = r.cus JOIN sym s ON s.id = r.sym JOIN descr d ON d.id = r.descr")
+
+
+def store_path(zip_path: Path) -> Path:
+    """Where the parsed copy of the ZIP at `zip_path` lives."""
+    return zip_path.parent / "parsed" / f"{zip_path.name}.sqlite"
+
+
+def _fingerprint(zip_path: Path) -> str:
+    st = zip_path.stat()
+    return f"{STORE_VERSION}:{st.st_size}:{st.st_mtime_ns}"
+
+
+def _connect(db: Path) -> sqlite3.Connection:
+    return sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
+
+
+def _is_current(db: Path, fingerprint: str) -> bool:
+    """Whether `db` is a complete store built from a ZIP with this fingerprint. A missing, cut-off or foreign file
+    is not."""
+    if not db.is_file():
+        return False
+    try:
+        con = _connect(db)
+        try:
+            got = con.execute("SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
+        finally:
+            con.close()
+    except sqlite3.DatabaseError:
+        return False
+    return got is not None and got[0] == fingerprint
+
+
+def ensure(zip_path: Path) -> Path:
+    """The parsed copy of the ZIP at `zip_path`, built first when there is none or it is out of date. Raises
+    `zipfile.BadZipFile` for a ZIP that cannot be read, leaving any earlier copy as it was."""
+    db = store_path(zip_path)
+    fingerprint = _fingerprint(zip_path)
+    if not _is_current(db, fingerprint):
+        db.parent.mkdir(parents=True, exist_ok=True)
+        clean_orphan_temps(db.parent)         # a killed run's cut-off build
+        write_atomic_with(db, lambda tmp: _build(zip_path, tmp, fingerprint))
+    return db
+
+
+def _price_cell(price: float | None) -> float | str | None:
+    if price is not None and (price != price or (price == 0 and math.copysign(1.0, price) < 0)):
+        return repr(price)
+    return price
+
+
+def split_line(line: str) -> tuple[str, str, str, str, float | None] | None:
+    """One fails-to-deliver text line as its fields, (ISO date, CUSIP, symbol, description, price); None for a header,
+    a trailer or a malformed line (fewer than six fields, or a first field that is not eight digits). The one place
+    the line format is read: `ftd.parse_ftd_lines` and the store's build both use it."""
+    parts = line.rstrip("\r\n").split("|")
+    if len(parts) < 6:
+        return None
+    d = parts[0].strip()
+    if len(d) != 8 or not d.isdigit():
+        return None
+    try:
+        price: float | None = float(parts[-1].strip())
+    except ValueError:
+        price = None
+    return (f"{d[:4]}-{d[4:6]}-{d[6:]}", parts[1].strip().upper(), normalize_ticker(parts[2]),
+            "|".join(parts[4:-1]).strip(), price)
+
+
+def _build(zip_path: Path, dest: Path, fingerprint: str) -> None:
+    """Parse every member of the ZIP into a new store at `dest`, every well-formed line (`split_line`) and no filter."""
+    con = sqlite3.connect(dest)
+    try:
+        con.executescript("""
+            PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
+            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
+            CREATE TABLE descr (id INTEGER PRIMARY KEY, text TEXT);
+            CREATE TABLE sym (id INTEGER PRIMARY KEY, text TEXT);
+            CREATE TABLE cus (id INTEGER PRIMARY KEY, text TEXT);
+            CREATE TABLE rows (day TEXT, cus INTEGER, sym INTEGER, descr INTEGER, price);
+        """)
+        ids: dict[str, dict[str, int]] = {"descr": {}, "sym": {}, "cus": {}}
+
+        def key(table: str, text: str) -> int:
+            known = ids[table]
+            got = known.get(text)
+            if got is None:
+                got = known[text] = len(known) + 1
+            return got
+
+        with zipfile.ZipFile(zip_path) as z:
+            # Every file member is read, whatever its name: from 2022-05 on the SEC
+            # ships one member without an extension ("cnsfails202401a").
+            for info in z.infolist():
+                if info.is_dir():
+                    continue
+                batch: list[tuple] = []
+                with z.open(info) as fh:
+                    for line in io.TextIOWrapper(fh, encoding="latin-1"):
+                        fields = split_line(line)
+                        if fields is None:
+                            continue
+                        day, cusip, symbol, description, price = fields
+                        batch.append((day, key("cus", cusip), key("sym", symbol), key("descr", description),
+                                      _price_cell(price)))
+                if not batch:
+                    _log.warning(f"{zip_path.name}: member {info.filename!r} holds no fails-to-deliver rows; skipped")
+                con.executemany("INSERT INTO rows VALUES (?, ?, ?, ?, ?)", batch)
+        for table, known in ids.items():
+            con.executemany(f"INSERT INTO {table} VALUES (?, ?)", ((i, t) for t, i in known.items()))
+        con.executescript("CREATE INDEX rows_sym ON rows (sym); CREATE INDEX rows_cus ON rows (cus); "
+                          "CREATE UNIQUE INDEX sym_text ON sym (text); CREATE UNIQUE INDEX cus_text ON cus (text);")
+        con.execute("INSERT INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
+        con.commit()
+    finally:
+        con.close()
+
+
+def _row(rec: tuple) -> tuple[str, str, str, str, float | None]:
+    """A stored row as the fields of an `ftd.FtdRow`: (date, CUSIP, symbol, description, price)."""
+    price = rec[5]
+    return rec[1], rec[2], rec[3], rec[4], float(price) if isinstance(price, str) else price
+
+
+def select(db: Path, *, symbols: set[str] | None = None,
+           cusips: set[str] | None = None) -> Iterator[tuple[str, str, str, str, float | None]]:
+    """The rows of the store at `db` (the fields of an `ftd.FtdRow`), as `ftd.parse_ftd_lines` filters them: those whose symbol is in `symbols` or
+    whose CUSIP is in `cusips` (each filter on its own when only one is given), every row when neither is; in the
+    ZIP's order."""
+    con = _connect(db)
+    try:
+        if symbols is None and cusips is None:
+            yield from (_row(rec) for rec in con.execute(f"{_ROW_SELECT} ORDER BY r.rowid"))
+            return
+        hits: dict[int, tuple] = {}
+        for column, table, wanted in (("sym", "sym", symbols), ("cus", "cus", cusips)):
+            keys = sorted(wanted or ())
+            for i in range(0, len(keys), _CHUNK):
+                chunk = keys[i:i + _CHUNK]
+                ids = [r[0] for r in con.execute(
+                    f"SELECT id FROM {table} WHERE text IN ({','.join('?' * len(chunk))})", chunk)]
+                for j in range(0, len(ids), _CHUNK):
+                    part = ids[j:j + _CHUNK]
+                    for rec in con.execute(f"{_ROW_SELECT} WHERE r.{column} IN ({','.join('?' * len(part))})", part):
+                        hits[rec[0]] = rec
+        yield from (_row(hits[rowid]) for rowid in sorted(hits))
+    finally:
+        con.close()
```

The store file is built through `write_atomic_with`: the temp file is named for its writer so `clean_orphan_temps` (called from `ensure` for the `parsed/` folder, which `FtdClient`'s own cleanup does not reach) removes a killed build's leftover. `FtdIndex` is untouched: it still asks `source.rows(url, symbols=, cusips=)` and gets `FtdRow`s.

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_ftd_store.py tests/test_ftd.py tests/test_atomic_io.py
```

Expected: all pass.

- [ ] **Step 4b: The line rule in the fingerprint, and two builders at once (from the review)**

The store holds what the line rule made of each line (a normalized symbol, an upper-cased CUSIP), so a store built
under another rule must be built again. Add these two tests to `tests/test_ftd_store.py`, right after
`test_store_is_built_once_and_again_when_the_zip_changes` (not at the end of the file: Task 6's diff appends there):

```python
def test_a_store_built_under_another_line_rule_is_built_again(tmp_path, monkeypatch):
    """The store holds the rule's output (a normalized symbol), so a change to the rule rebuilds it."""
    zip_path = tmp_path / "cnsfails202401a.zip"
    _write_zip(zip_path, {"a.txt": HEADER + "20240102|084670702|brk.b|5|BERKSHIRE HATHAWAY|400.0\n"})
    assert [r[2] for r in ftd_store.select(ftd_store.ensure(zip_path))] == ["BRK-B"]
    monkeypatch.setattr(ftd_store, "normalize_ticker", lambda raw: raw.strip().upper().replace(".", ""))
    assert [r[2] for r in ftd_store.select(ftd_store.ensure(zip_path))] == ["BRKB"]


def test_threads_building_one_store_at_once_all_read_the_same_rows(tmp_path):
    """Two prefetch threads, or two runs on one cache, can need the same store at once: each builds its own temp
    file, the last replace wins, and every reader sees a whole store."""
    import threading
    zip_path = tmp_path / "cnsfails202401a.zip"
    _write_zip(zip_path, {"a.txt": HEADER + "".join(
        f"2024010{1 + i % 9}|{i % 50:09d}|S{i % 30}|{i}|DESC {i % 7}|{i % 97 + .5}\n" for i in range(20000))})
    got, errors = [], []

    def work():
        try:
            got.append(list(ftd_store.select(ftd_store.ensure(zip_path), symbols={"S5", "S7"})))
        except BaseException as e:      # the test reports whatever a thread met
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(got) == 8 and got[0] and all(g == got[0] for g in got)
    assert sorted(p.name for p in (tmp_path / "parsed").iterdir()) == ["cnsfails202401a.zip.sqlite"]
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_ftd_store.py -q -o addopts="" -k "another_line_rule or at_once"`
Expected: the first FAILS (`['BRK-B'] != ['BRKB']`: the store is not rebuilt); the second passes already (it pins what holds).

In `src/delist_detection/sources/ftd_store.py`, add `import hashlib` as the first import of the block (before
`import io`, away from the lines Task 6's diff reads as context), and replace `_fingerprint` with:

```python
# Lines that exercise each part of the line rule (`split_line`, and `normalize_ticker` inside it): separators and
# case in the symbol, a lower-case CUSIP, a "|" and latin-1 text in the description, every price shape, and the
# lines the rule drops.
_RULE_PROBES = (
    "20240102|00206R102|T|500|AT&T INC COM|16.78",
    "20240102|00206r102| brk.b |500|BERKSHIRE | CLASS B |nan",
    "20240103|037833100|BF/A|10|BROWN FORMAN|-0.0",
    "20240103|037833100|ZZ ZZ|10|CAF\xc9 \xb2 LTD|",
    "20240103|037833100|aapl|10|APPLE INC|1e400",
    "20240104|G0000Z000|A..B|1|X\ty|3.5\r\n",
    "2024010|BADDATE|X|1|SHORT DATE|1.0",
    "20240104|SHORT|X|1",
    "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE",
)


def _rule_digest() -> str:
    """What the line rule makes of `_RULE_PROBES`, as a short digest: a store holds the rule's output, not the text,
    so one built under a rule that reads these lines differently is out of date."""
    return hashlib.sha1(repr([split_line(p) for p in _RULE_PROBES]).encode()).hexdigest()[:12]


def _fingerprint(zip_path: Path) -> str:
    st = zip_path.stat()
    return f"{STORE_VERSION}:{_rule_digest()}:{st.st_size}:{st.st_mtime_ns}"
```

Update the module docstring's second paragraph to say the file also records a digest of the line rule and is built
again when the rule reads the probe lines differently. A change to the rule that the probes do not show still needs
`STORE_VERSION` raised: say that in a comment on `STORE_VERSION`.

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_ftd_store.py -q -o addopts=""`
Expected: all pass. A store built before this step is built again on its next use (its fingerprint has no digest).

- [ ] **Step 5: Full-run check against the reference output**

Run the harness's full-run command on a fresh copy of `CACHE_FULL`, then `python3 cmp.py $REF /tmp/run-<tag>/out`.
Expected: `TABLES IDENTICAL`, `manifest checked`. Measured: warm run 521.9 s → 310.4 s once the store exists; the first run on a cache without it builds the store and takes 334.8 s (the build adds 25 to 45 s, once). Peak memory unchanged (5.5 GB: the index still holds the rows; Task 6 reduces that). Also run the real-ZIP equivalence once (it streams, holds no list): the script below compares, for every ZIP in the cache, the stored rows with `parse_ftd_lines` unfiltered and under a filter of symbols and CUSIPs, prices included (NaN and the sign of zero).

```python
"""Every real FTD zip: the stored rows equal the parser's rows, unfiltered and under two filters. Streams, holds no list.
usage: ftd_equiv.py <ftd dir>   (PYTHONPATH=<tree>/src)"""
import io, itertools, math, sys, zipfile, random
from pathlib import Path
from delist_detection.sources import ftd_store
from delist_detection.sources.ftd import FtdRow, parse_ftd_lines

def reference(lines, symbols=None, cusips=None, counts=None):
    """The line rule as parse_ftd_lines first wrote it (an independent copy)."""
    from delist_detection.vocabulary.identifiers import normalize_ticker
    for line in lines:
        parts = line.rstrip("\r\n").split("|")
        if len(parts) < 6:
            continue
        d = parts[0].strip()
        if len(d) != 8 or not d.isdigit():
            continue
        cusip = parts[1].strip().upper(); symbol = normalize_ticker(parts[2])
        if symbols is not None or cusips is not None:
            if not ((symbols is not None and symbol in symbols) or (cusips is not None and cusip in cusips)):
                continue
        try:
            price = float(parts[-1].strip())
        except ValueError:
            price = None
        yield FtdRow(f"{d[:4]}-{d[4:6]}-{d[6:]}", cusip, symbol, "|".join(parts[4:-1]).strip(), price)

def old(path, **f):
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.is_dir():
                with z.open(info) as fh:
                    yield from reference(io.TextIOWrapper(fh, encoding="latin-1"), **f)

def same(a, b):
    return (a.date, a.cusip, a.symbol, a.description) == (b.date, b.cusip, b.symbol, b.description) and (
        (a.price is None and b.price is None) or (a.price is not None and b.price is not None and (
            (math.isnan(a.price) and math.isnan(b.price)) or (a.price == b.price and math.copysign(1, a.price) == math.copysign(1, b.price)))))

def check(path, **f):
    n = 0
    new = (FtdRow(*t) for t in ftd_store.select(ftd_store.store_path(path), **f))
    for a, b in itertools.zip_longest(old(path, **f), new):
        if a is None or b is None or not same(a, b):
            print("MISMATCH", path.name, f.keys(), a, b); return False
        n += 1
    return n

d = Path(sys.argv[1]); total = 0; bad = 0
for p in sorted(d.glob("*.zip")):
    ftd_store.ensure(p)
    rows = list(itertools.islice(old(p), 0, None, 997))          # a sample of keys to filter on
    syms = {r.symbol for r in rows}; cus = {r.cusip for r in rows}
    for f in ({}, {"symbols": set(sorted(syms)[::3]), "cusips": set(sorted(cus)[1::7])}):
        r = check(p, **f)
        if r is False: bad += 1
        else: total += r
print("rows compared", total, "mismatching zips/filters", bad)
```

```bash
PYTHONPATH=src $PY ftd_equiv.py $CACHE_FULL/sec_data/ftd     # builds the store in $CACHE_FULL: use a copy
```

Expected: `rows compared 28235581 mismatching zips/filters 0` (measured on the ZIPs of the `6e43e09` reference cache).

- [ ] **Step 6: Docs and commit**

CLAUDE.md: add a bullet after `sources/ftd.py` for `sources/ftd_store.py` — "a fails ZIP parsed once into `sec_data/ftd/parsed/<zip>.sqlite` (size and mtime recorded; rebuilt when the ZIP changes; `atomic_io.write_atomic_with`), read by symbol and CUSIP through its indexes, in the ZIP's row order; `FtdClient.rows` reads through it". In *Non-obvious invariants* → SEC fair access add: "the parsed copies are a cache like the rest (1.9 GB; gitignored with `cache/`)". Also add `write_atomic_with` to the `atomic_io.py` bullet.

```bash
git add src/delist_detection/sources/ftd_store.py src/delist_detection/sources/atomic_io.py src/delist_detection/sources/ftd.py tests/test_ftd_store.py CLAUDE.md
git commit -m "Fails-to-deliver files: parse each ZIP once into a SQLite file under the cache and read keys through its indexes"
```

---

### Task 2: `normalize_ticker` and `parse_day` fast paths

**Files:**
- Modify: `src/delist_detection/vocabulary/identifiers.py` (`normalize_ticker`), `src/delist_detection/filings/evidence.py` (`parse_day`)
- Test: `tests/test_identifiers.py`, `tests/test_evidence.py`

**Interfaces:**
- Produces: unchanged signatures. `normalize_ticker(raw)` returns `raw.strip().upper()` at once when that is letters and digits only; `parse_day(s)` reads a text of the exact shape `YYYY-MM-DD` by slicing and leaves every other text to `strptime`.

- [ ] **Step 1: Write the failing tests**

The tests below are the test part of the working diff (`docs/superpowers/plans/research/2026-10-10-faster-runs/changes-c77365a/02-normalize-parse-day.diff`); apply them with `git apply` (they add or extend
the files named), or copy the code.

```diff
diff --git a/tests/test_evidence.py b/tests/test_evidence.py
index e5d0d79..ef9552f 100644
--- a/tests/test_evidence.py
+++ b/tests/test_evidence.py
@@ -1,6 +1,8 @@
-from datetime import date
+from datetime import date, datetime
 
-from delist_detection.filings.evidence import name_at, names_near
+import pytest
+
+from delist_detection.filings.evidence import name_at, names_near, parse_day
 
 SUB = {"name": "SunPower Inc.", "formerNames": [
     {"name": "Complete Solaria, Inc.", "from": "2023-03-10T05:00:00.000Z", "to": "2025-09-26T04:00:00.000Z"},
@@ -262,3 +264,16 @@ def test_a_10k_index_entry_page_number_ends_no_section():
     assert "Item 8. 29 Kodak" in item_text(text, "3.01")
     spaced = "Item 3.01 Notice. " + "y" * 300 + " ITEM 1 .0 3 Bankruptcy " + "z" * 300
     assert "ITEM 1 .0 3" not in item_text(spaced, "3.01")
+
+
+@pytest.mark.parametrize("text", [
+    "2024-01-05", "2024-01-05T10:20:30.000Z", "2024-1-5", "2024-02-30", "2023-02-29", "2024-02-29", "0000-01-01",
+    "2024-13-01", "2024-00-10", "2024-01-00", "2024/01/05", "20240105", "2024-01-0", "", None, "abcd-ef-gh",
+    "\u0662\u0660\u0662\u0664-01-05", " 2024-01-05", "2024-01-05 ", "9999-12-31", "1900-01-01"])
+def test_parse_day_reads_what_strptime_read(text):
+    """Slicing an exactly-shaped day gives the date `strptime` gave, and the same None for anything else."""
+    try:
+        want = datetime.strptime((text or "")[:10], "%Y-%m-%d").date()
+    except ValueError:
+        want = None
+    assert parse_day(text) == want
diff --git a/tests/test_identifiers.py b/tests/test_identifiers.py
index 24f991e..c726b20 100644
--- a/tests/test_identifiers.py
+++ b/tests/test_identifiers.py
@@ -235,3 +235,11 @@ def test_a_class_the_name_does_not_state_fits_the_one_letter_the_issuer_and_its_
     assert not fits_class("CLASS A", "CLASS B", described="B", issuer_letters=("B",))     # its own class is stated
     assert not fits_class("CLASS B", "COMMON", described="B", issuer_letters=("B",))      # only a plain class fits
     assert not fits_class("COMMON", "PREFERRED", described=None, issuer_letters=())
+
+
+@pytest.mark.parametrize("raw", ["AET", "aet", " brk.b ", "BRK B", "BF/A", "..A..", "-A-", "A--B", "UAC-C", "F104PAIROFF",
+                                 "A B", "x\ty", "ÉT", "", "  ", "...", "-", "A-", "-A", "1.5", "ZZ ZZ", None])
+def test_normalize_ticker_is_the_pattern_it_replaced(raw):
+    """The fast path (a ticker of letters and digits is its upper-cased self) gives what the one-line pattern did."""
+    import re
+    assert normalize_ticker(raw) == re.sub(r"[./\s]+", "-", (raw or "").strip().upper()).strip("-")
```

- [ ] **Step 2: Run them and see them fail**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_identifiers.py tests/test_evidence.py
```

Expected: **no failure**: this task keeps behaviour, so the tests pass before and after (verified: 99 passed on the untouched code). They are the equivalence guard: each case is compared with the code it replaces (`re.sub(...)` and `strptime`), including a day with no zeros, impossible days, year 0, non-ASCII digits and a ticker with a no-break space.

- [ ] **Step 3: Implement**

Add the pattern constant and the early return; add the slicing branch in front of the `strptime` call:

```diff
diff --git a/src/delist_detection/filings/evidence.py b/src/delist_detection/filings/evidence.py
index f254705..e8d3f71 100644
--- a/src/delist_detection/filings/evidence.py
+++ b/src/delist_detection/filings/evidence.py
@@ -29,8 +29,19 @@ MERGER_EVIDENCE_FORMS = {"DEFM14A", "DEFM14C", "PREM14A", "SC 14D9", "SC TO-T",
 
 
 def parse_day(s: str | None) -> date | None:
+    """The day an ISO "YYYY-MM-DD" text (or the first ten characters of a longer one) names, None for anything else.
+    A text in exactly that shape is read by slicing; `strptime`, which is slow when run ten million times, reads the
+    rest (a day written without its zeros, a text that is no day)."""
+    text = (s or "")[:10]
+    if len(text) == 10 and text[4] == "-" and text[7] == "-":
+        year, month, day = text[:4], text[5:7], text[8:]
+        if all(part.isascii() and part.isdigit() for part in (year, month, day)):
+            try:
+                return date(int(year), int(month), int(day))
+            except ValueError:
+                return None
     try:
-        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
+        return datetime.strptime(text, "%Y-%m-%d").date()
     except ValueError:
         return None
 
diff --git a/src/delist_detection/vocabulary/identifiers.py b/src/delist_detection/vocabulary/identifiers.py
index c7e7189..6726491 100644
--- a/src/delist_detection/vocabulary/identifiers.py
+++ b/src/delist_detection/vocabulary/identifiers.py
@@ -40,10 +40,17 @@ from collections.abc import Collection, Iterable
 # --- ticker spellings -----------------------------------------------------------------------------------------------
 
 
+_TICKER_SEPARATORS = re.compile(r"[./\s]+")
+
+
 def normalize_ticker(raw: str) -> str:
     """The tables' spelling of a ticker: upper case, each run of ".", "/" and spaces one "-", none at either end
-    (" brk.b " and "BRK B" are BRK-B, "BF/A" is BF-A)."""
-    return re.sub(r"[./\s]+", "-", (raw or "").strip().upper()).strip("-")
+    (" brk.b " and "BRK B" are BRK-B, "BF/A" is BF-A). A ticker of letters and digits only (nearly every one) is
+    its upper-cased self: the pattern has nothing to change in it."""
+    text = (raw or "").strip().upper()
+    if text.isalnum():
+        return text
+    return _TICKER_SEPARATORS.sub("-", text).strip("-")
 
 
 _WHEN_ISSUED = re.compile(r"-W-?I$")       # "EHAB WI", "EHAB.WI", "EHAB-WI", "EHAB/WI", "EHAB W/I"
```

`str.isalnum()` is false for every character the pattern would change (`.`, `/`, whitespace) and for `-`, so a ticker it accepts is unchanged by the substitution and by `strip("-")`. A text that is not exactly ten characters of the shape falls through to `strptime` as before.

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_identifiers.py tests/test_evidence.py
```

Expected: all pass.

- [ ] **Step 5: Full-run check against the reference output**

Run the harness's full-run command on a fresh copy of `CACHE_FULL`, then `python3 cmp.py $REF /tmp/run-<tag>/out`.
Expected: `TABLES IDENTICAL`, `manifest checked`. Measured: 310.4 s → 302.6 s (about 8 s; within a few seconds of run-to-run noise, kept because the equivalence tests are exact and it removes ten million `strptime` calls). Peak memory unchanged.

- [ ] **Step 6: Docs and commit**

No doc change.

```bash
git add src/delist_detection/vocabulary/identifiers.py src/delist_detection/filings/evidence.py tests/test_identifiers.py tests/test_evidence.py
git commit -m "normalize_ticker and parse_day: a fast path for the shapes nearly every input has"
```

---

### Task 3: `recent_filings` builds its rows from columns fetched once

**Files:**
- Modify: `src/delist_detection/sources/edgar.py` (`_submissions_of` new; `EdgarClient.recent_filings`)
- Test: `tests/test_edgar_recent_filings.py` (new)

**Interfaces:**
- Produces: `edgar._submissions_of(block) -> list[EdgarSubmission]` for a submissions JSON's columnar block (the `recent` block or one older file). `recent_filings` returns the same list as before.

- [ ] **Step 1: Write the failing tests**

The tests below are the test part of the working diff (`docs/superpowers/plans/research/2026-10-10-faster-runs/changes-c77365a/03-recent-filings.diff`); apply them with `git apply` (they add or extend
the files named), or copy the code.

```diff
diff --git a/tests/test_edgar_recent_filings.py b/tests/test_edgar_recent_filings.py
new file mode 100644
index 0000000..26f4031
--- /dev/null
+++ b/tests/test_edgar_recent_filings.py
@@ -0,0 +1,40 @@
+"""`EdgarClient.recent_filings`: the rows a submissions JSON's columns list, recent block then older files."""
+from __future__ import annotations
+
+import json
+
+import pytest
+
+from delist_detection.sources.edgar import EdgarClient, EdgarSubmission, _submissions_of
+
+RECENT = {"accessionNumber": ["0001-24-000002", "0001-24-000001"], "form": ["8-K", "25-NSE"],
+          "filingDate": ["2024-03-01", "2024-02-01"], "reportDate": ["2024-02-28", ""],
+          "items": ["2.01,3.01", ""], "primaryDocument": ["a.htm", "b.xml"]}
+
+
+def test_submissions_of_reads_row_i_of_every_column():
+    assert _submissions_of(RECENT) == [
+        EdgarSubmission("0001-24-000002", "8-K", "2024-03-01", "2024-02-28", "2.01,3.01", "a.htm"),
+        EdgarSubmission("0001-24-000001", "25-NSE", "2024-02-01", "", "", "b.xml")]
+
+
+def test_a_column_the_block_lacks_reads_blank_and_an_empty_block_has_no_filings():
+    got = _submissions_of({"accessionNumber": ["x", "y"], "form": ["10-K", "10-Q"]})
+    assert got == [EdgarSubmission("x", "10-K", "", "", "", ""), EdgarSubmission("y", "10-Q", "", "", "", "")]
+    assert _submissions_of({}) == [] and _submissions_of({"accessionNumber": []}) == []
+
+
+def test_a_short_column_raises_as_it_always_has():
+    with pytest.raises(IndexError):
+        _submissions_of({**RECENT, "filingDate": ["2024-03-01"]})
+
+
+def test_recent_filings_lists_the_recent_block_then_each_older_file(tmp_path, monkeypatch):
+    client = EdgarClient(cache_dir=tmp_path, user_agent="test test@example.com")
+    older = {"accessionNumber": ["0001-20-000009"], "form": ["10-K"], "filingDate": ["2020-02-01"],
+             "reportDate": ["2019-12-31"], "items": [""], "primaryDocument": ["k.htm"]}
+    served = {"https://data.sec.gov/submissions/CIK0000000042.json":
+              {"filings": {"recent": RECENT, "files": [{"name": "CIK0000000042-submissions-001.json"}]}},
+              "https://data.sec.gov/submissions/CIK0000000042-submissions-001.json": older}
+    monkeypatch.setattr(client, "_get_json", lambda url, **kw: json.loads(json.dumps(served[url])))
+    assert [f.accession for f in client.recent_filings(42)] == ["0001-24-000002", "0001-24-000001", "0001-20-000009"]
```

- [ ] **Step 2: Run them and see them fail**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_edgar_recent_filings.py
```

Expected: collection error `ImportError: cannot import name '_submissions_of'`; verified on the untouched tree.

- [ ] **Step 3: Implement**

Add the helper after `EdgarSubmission` and make `recent_filings` use it for the recent block and for each older file:

```diff
diff --git a/src/delist_detection/sources/edgar.py b/src/delist_detection/sources/edgar.py
index b7a991b..9e939aa 100644
--- a/src/delist_detection/sources/edgar.py
+++ b/src/delist_detection/sources/edgar.py
@@ -263,6 +263,22 @@ class EdgarSubmission:
         return {x.strip() for x in self.items.split(",") if x.strip()}
 
 
+def _submissions_of(block: dict) -> list[EdgarSubmission]:
+    """The filings a submissions JSON's columnar block lists (its "recent" block, or one of its older files): row `i`
+    of every column is one filing. A column the block lacks reads as blank; a column shorter than the accession
+    column raises IndexError, as it always has."""
+    n = len(block.get("accessionNumber", []))
+    if not n:
+        return []
+    blank = [""] * n
+    accession, form = block["accessionNumber"], block["form"]
+    filed = block.get("filingDate", blank)
+    reported = block.get("reportDate", blank)
+    items = block.get("items", blank)
+    primary = block.get("primaryDocument", blank)
+    return [EdgarSubmission(accession[i], form[i], filed[i], reported[i], items[i], primary[i]) for i in range(n)]
+
+
 # A genuine EDGAR company-search answer, matched or not, is always a complete
 # ATOM feed (see tests/fixtures/company_search/: nomatch.atom is a <feed> with
 # no <cik>, just like onematch.atom and multimatch.atom are <feed>s with one).
@@ -743,36 +759,12 @@ class EdgarClient:
         sub = self.submissions(cik)
         if not isinstance(sub, dict) or sub.get("__not_found__"):
             return []
-        recent = sub.get("filings", {}).get("recent", {})
-        n = len(recent.get("accessionNumber", []))
-        out: list[EdgarSubmission] = []
-        for i in range(n):
-            out.append(
-                EdgarSubmission(
-                    accession=recent["accessionNumber"][i],
-                    form=recent["form"][i],
-                    filing_date=recent.get("filingDate", [""] * n)[i],
-                    report_date=recent.get("reportDate", [""] * n)[i],
-                    items=recent.get("items", [""] * n)[i],
-                    primary_doc=recent.get("primaryDocument", [""] * n)[i],
-                )
-            )
+        out = _submissions_of(sub.get("filings", {}).get("recent", {}))
         # also pull historical files (paginated chunks of older filings)
         for fchunk in sub.get("filings", {}).get("files", []):
             url = f"{SEC_HOST}/submissions/{fchunk['name']}"
             data = self._get_json(url)
             if not isinstance(data, dict) or data.get("__not_found__"):
                 continue
-            n = len(data.get("accessionNumber", []))
-            for i in range(n):
-                out.append(
-                    EdgarSubmission(
-                        accession=data["accessionNumber"][i],
-                        form=data["form"][i],
-                        filing_date=data.get("filingDate", [""] * n)[i],
-                        report_date=data.get("reportDate", [""] * n)[i],
-                        items=data.get("items", [""] * n)[i],
-                        primary_doc=data.get("primaryDocument", [""] * n)[i],
-                    )
-                )
+            out += _submissions_of(data)
         return out
```

The old loop wrote `recent.get("filingDate", [""] * n)[i]` inside the per-row call, so it allocated an `n`-long list for each of five columns for each of `n` rows (quadratic; a large issuer has tens of thousands of rows). The helper keeps the behaviour exactly: a missing optional column reads blank, a missing `form` column raises `KeyError` only when there are rows, and a short column raises `IndexError`.

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_edgar_recent_filings.py
```

Expected: all pass.

- [ ] **Step 5: Full-run check against the reference output**

Run the harness's full-run command on a fresh copy of `CACHE_FULL`, then `python3 cmp.py $REF /tmp/run-<tag>/out`.
Expected: `TABLES IDENTICAL`, `manifest checked`. Measured: 302.6 s → 176.0 s (the largest single saving of the warm run). Peak memory unchanged.

- [ ] **Step 6: Docs and commit**

No doc change.

```bash
git add src/delist_detection/sources/edgar.py tests/test_edgar_recent_filings.py
git commit -m "recent_filings: build each filing row from columns fetched once, not a default list per row"
```

---

### Task 4: `--llm-workers`: the LLM calls on their own threads

**Files:**
- Modify: `scripts/classify_universe.py` (`--llm-workers`, default 8, at most 16), `src/delist_detection/pipeline.py` (`run`, `_run`, `_RunContext.llm_workers`, `_merger_values`), `src/delist_detection/terms/merger_value.py` (`value_mergers`, `_Stage.llm_workers`, `_read_terms`), `src/delist_detection/terms/llm_merger_extractor.py` (`_llm_extract` holds a lock per answer file)
- Test: `tests/test_classify_universe_cli.py`, `tests/test_merger_value.py`, `tests/test_llm_merger_extractor.py`, `tests/test_pipeline_prefetch.py`

**Interfaces:**
- Consumes: `prefetch.warm` (unchanged: its `workers` argument is now the LLM count for the `llm terms` pass).
- Produces: `run(..., llm_workers=None)` and `value_mergers(..., llm_workers=None)` (`None` means the SEC worker count, so existing callers and tests behave as before); `LLMMergerTermsExtractor._cached`, `._path_lock`.

- [ ] **Step 1: Write the failing tests**

The tests below are the test part of the working diff (`docs/superpowers/plans/research/2026-10-10-faster-runs/changes-c77365a/04-llm-workers.diff`); apply them with `git apply` (they add or extend
the files named), or copy the code.

```diff
diff --git a/tests/test_classify_universe_cli.py b/tests/test_classify_universe_cli.py
index d9340dc..4bf4b0e 100644
--- a/tests/test_classify_universe_cli.py
+++ b/tests/test_classify_universe_cli.py
@@ -272,6 +272,20 @@ def test_main_passes_sec_workers_to_run(monkeypatch):
     assert _run_main.seen["sec_workers"] == 3
 
 
+def test_llm_workers_default_to_8_and_are_passed_to_run(monkeypatch):
+    assert _run_main(monkeypatch, {}) == 0
+    assert _run_main.seen["llm_workers"] == 8
+    assert _run_main(monkeypatch, {}, "--sec-workers", "1", "--llm-workers", "16") == 0
+    assert (_run_main.seen["sec_workers"], _run_main.seen["llm_workers"]) == (1, 16)
+
+
+@pytest.mark.parametrize("n", ["0", "17"])
+def test_llm_workers_outside_1_to_16_is_refused(monkeypatch, n):
+    with pytest.raises(SystemExit) as exc:
+        _run_main(monkeypatch, {}, "--llm-workers", n)
+    assert exc.value.code == 2
+
+
 @pytest.mark.parametrize("n", ["0", "9"])
 def test_sec_workers_outside_1_to_8_is_refused(monkeypatch, n):
     with pytest.raises(SystemExit) as exc:
diff --git a/tests/test_llm_merger_extractor.py b/tests/test_llm_merger_extractor.py
index d75e27f..38dc3ba 100644
--- a/tests/test_llm_merger_extractor.py
+++ b/tests/test_llm_merger_extractor.py
@@ -376,3 +376,81 @@ def test_network_error_returns_none(tmp_path):
 
     ext = LLMMergerTermsExtractor(_RaisingEdgar(), _FakeLlm([]), cache_dir=tmp_path)
     assert ext.extract(_merger_rec()) is None
+
+
+def test_threads_asking_for_one_answer_file_pay_for_one_call(tmp_path):
+    """Two mergers can ask for one file (the same filing and target ticker) and the warm threads run them at once:
+    the second waits for the first's call and reads its answer, so the model is called once."""
+    import threading
+    import time
+    resp = {"deal_type": "cash", "cash_per_share": 10.0, "stock_ratio": None, "acquirer_name": "X",
+            "acquirer_ticker": None, "confidence": "high", "quote": "$10.00 in cash", "package_basis": "fixed"}
+
+    class _Slow(_FakeLlm):
+        def extract(self, system, user, schema):
+            time.sleep(0.2)                   # long enough for every thread to be waiting for the answer
+            return super().extract(system, user, schema)
+
+    llm = _Slow([resp])
+    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
+    ext = LLMMergerTermsExtractor(edgar, llm, cache_dir=tmp_path)
+    got: list = []
+    threads = [threading.Thread(target=lambda: got.append(ext.extract(_merger_rec()))) for _ in range(6)]
+    for t in threads:
+        t.start()
+    for t in threads:
+        t.join()
+    assert llm.calls == 1 and len(got) == 6 and all(t == got[0] and t.cash_per_share == 10.0 for t in got)
+
+
+def _concurrent_extract(ext, n, *, warm):
+    import threading
+
+    from delist_detection.sources.sec_stats import fill_only
+
+    def ask():
+        if warm:
+            with fill_only():
+                ext.extract(_merger_rec())
+        else:
+            ext.extract(_merger_rec())
+
+    threads = [threading.Thread(target=ask) for _ in range(n)]
+    for t in threads:
+        t.start()
+    for t in threads:
+        t.join()
+
+
+def _slow_ext(tmp_path):
+    import time
+    resp = {"deal_type": "cash", "cash_per_share": 10.0, "stock_ratio": None, "acquirer_name": "X",
+            "acquirer_ticker": None, "confidence": "high", "quote": "$10.00 in cash", "package_basis": "fixed"}
+
+    class _Slow(_FakeLlm):
+        def extract(self, system, user, schema):
+            time.sleep(0.2)
+            return super().extract(system, user, schema)
+
+    llm = _Slow([resp])
+    return LLMMergerTermsExtractor(_FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT}), llm, cache_dir=tmp_path), llm
+
+
+def test_threads_that_waited_for_one_answer_count_it_as_any_cache_read_is_counted(tmp_path):
+    """Six sequential-pass threads ask for one file: one asked the model (`asked`), the five that waited read its
+    answer (`asked` too, since this run asked for it): the count is that of six cache reads after one call."""
+    ext, llm = _slow_ext(tmp_path)
+    _concurrent_extract(ext, 6, warm=False)
+    u = ext.usage()
+    assert llm.calls == 1 and (u["asked"], u["from_cache"], u["failed"], u["answers"]) == (6, 0, 0, 6)
+
+
+def test_a_warm_pass_counts_nothing_and_the_sequential_read_after_it_counts_asked(tmp_path):
+    """The warm threads' own reads are not counted, however many wait on the lock; the sequential pass then reads the
+    file the warm pass asked for and counts it once as `asked`."""
+    ext, llm = _slow_ext(tmp_path)
+    _concurrent_extract(ext, 6, warm=True)
+    assert llm.calls == 1 and ext.usage()["answers"] == 0 and ext.usage()["asked"] == 0
+    ext.extract(_merger_rec())
+    u = ext.usage()
+    assert (u["asked"], u["from_cache"], u["failed"]) == (1, 0, 0)
diff --git a/tests/test_merger_value.py b/tests/test_merger_value.py
index 63cc054..4a8be74 100644
--- a/tests/test_merger_value.py
+++ b/tests/test_merger_value.py
@@ -57,13 +57,13 @@ class _Terms:
 
 def _value(delistings, *, llm=None, payout=None, edgar=None, resolver=None, name_index=None, ftd_client=None,
            securities=None, closes=None, own_closes=None, caller_terms=None, answers=None, workers=1,
-           log=None) -> MergerValues:
+           llm_workers=None, log=None) -> MergerValues:
     clients = Clients(edgar=edgar, resolver=resolver, classifier=None, figi=None, ftd_client=ftd_client or _NoFtd(),
                       payout_extractor=payout, llm_extractor=llm, issuers=IssuerRecord(edgar, name_index=name_index))
     index = LineIndex(securities or {}, {}, {}, FtdIndex(source=clients.ftd_client))
     return value_mergers(delistings, index, clients=clients, closes=closes or {}, own_closes=own_closes,
                          caller_terms=caller_terms or {}, answers=answers or PriceAnswers(), tol=0.15,
-                         workers=workers, log=log or (lambda *a: None))
+                         workers=workers, llm_workers=llm_workers, log=log or (lambda *a: None))
 
 
 def _stock(ratio, ticker, *, cash=None, value=None, name=None):
@@ -306,3 +306,25 @@ def test_the_contract_inputs_are_the_mergers_records(bucket):
         return
     assert (got[K].llm, got[K].acquirer_sec_id, got[K].price_ticker, got[K].leg_sec_ids) == (
         llm, "BBG0ACQ", "ACQN", {"B": "BBG0B"})
+
+
+def test_the_llm_calls_are_filled_ahead_on_their_own_threads_whatever_the_sec_workers():
+    """`llm_workers` sets the threads that make the LLM calls ahead, apart from the SEC `workers`: one SEC request
+    at a time still gets the LLM calls on many threads, and the terms are the one-thread run's."""
+    import threading
+    threads, cache, guard = [], {}, threading.Lock()
+
+    class Ext:
+        def extract(self, record, security_name=""):
+            with guard:
+                threads.append(threading.current_thread().name)
+                return cache.setdefault(record.ticker, MergerTerms("cash", 10.0 + len(cache), None, None, None, "high",
+                                                                   "8-K:x", "", package_basis="fixed"))
+
+    es = [_merger(t, t, "2016-09-16", date(2016, 9, 15)) for t in ("AAA", "BBB", "CCC")]
+    one = {k: v.llm for k, v in _value(es, llm=Ext(), workers=1, llm_workers=1).records.items()}
+    assert threads == [threading.main_thread().name] * 3
+    threads.clear()
+    many = {k: v.llm for k, v in _value(es, llm=Ext(), workers=1, llm_workers=4).records.items()}
+    assert many == one
+    assert sum(n.startswith("sec-warm") for n in threads) == 3 and threads[-3:] == [threading.main_thread().name] * 3
diff --git a/tests/test_pipeline_prefetch.py b/tests/test_pipeline_prefetch.py
index c4fe2d2..80a6ab4 100644
--- a/tests/test_pipeline_prefetch.py
+++ b/tests/test_pipeline_prefetch.py
@@ -408,6 +408,60 @@ def test_payouts_and_llm_calls_are_filled_ahead_and_no_llm_answer_is_paid_for_tw
     assert len(llm) == len(keys)                   # no answer paid for twice
 
 
+def test_llm_calls_are_filled_ahead_on_llm_workers_while_sec_reads_stay_on_one_thread(fake_edgar, tmp_path):
+    """--llm-workers sets the threads for the LLM calls apart from --sec-workers: with one SEC worker the regex
+    payout reads stay on the main thread and the LLM calls still run on the warm threads, each paid for once."""
+    index, clients = _clients(fake_edgar)
+    regex, llm, guard = [], [], threading.Lock()
+
+    class _Regex:
+        def extract(self, record, last_close=None):
+            with guard:
+                regex.append(threading.current_thread().name)
+            return PayoutResult.none()
+
+    class _Client:
+        model = "m"
+
+        def extract(self, system, user, schema):
+            with guard:
+                llm.append(threading.current_thread().name)
+            return {"deal_type": "cash", "cash_per_share": 212.70, "stock_ratio": None, "acquirer_name": "CVS",
+                    "acquirer_ticker": "CVS", "confidence": "high", "quote": "$212.70 in cash",
+                    "package_basis": "fixed"}
+
+    clients.payout_extractor = _Regex()
+    clients.llm_extractor = LLMMergerTermsExtractor(fake_edgar, _Client(), cache_dir=tmp_path / "llm")
+    run(index, clients, Overrides(), out_dir=tmp_path / "out", log=lambda *_: None, sec_workers=1, llm_workers=4)
+    assert regex and set(regex) == {threading.main_thread().name}
+    assert llm and all(n.startswith("sec-warm") for n in llm)
+    assert len(llm) == len(list((tmp_path / "llm").glob("*.json")))
+
+
+def test_llm_answers_and_tables_do_not_depend_on_the_llm_worker_count(fake_edgar, tmp_path):
+    """One LLM thread and four leave the same answer files and the same tables: a warm thread only fills the cache
+    entry the sequential pass would fill itself."""
+    class _Client:
+        model = "m"
+
+        def extract(self, system, user, schema):
+            return {"deal_type": "cash", "cash_per_share": 212.70, "stock_ratio": None, "acquirer_name": "CVS",
+                    "acquirer_ticker": "CVS", "confidence": "high", "quote": "$212.70 in cash",
+                    "package_basis": "fixed"}
+
+    for n in (1, 4):
+        index, clients = _clients(fake_edgar)
+        clients.llm_extractor = LLMMergerTermsExtractor(fake_edgar, _Client(), cache_dir=tmp_path / f"llm{n}")
+        run(index, clients, Overrides(), out_dir=tmp_path / f"out{n}", log=lambda *_: None, sec_workers=1,
+            llm_workers=n)
+
+    def files(root):
+        return {p.name: p.read_bytes() for p in sorted(root.glob("*.json" if root.name.startswith("llm") else "*.csv"))}
+
+    assert files(tmp_path / "llm1") and files(tmp_path / "llm1") == files(tmp_path / "llm4")
+    assert files(tmp_path / "out1") and files(tmp_path / "out1") == files(tmp_path / "out4")
+
+
 def test_the_successor_search_is_warmed_with_the_query_the_sequential_pass_sends(fake_edgar, tmp_path,
                                                                                  monkeypatch):
     fake_edgar.company_map["GOOGL"] = {"cik_str": 1288776, "ticker": "GOOGL", "title": "Google Inc."}
```

- [ ] **Step 2: Run them and see them fail**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_classify_universe_cli.py tests/test_merger_value.py tests/test_llm_merger_extractor.py tests/test_pipeline_prefetch.py
```

Expected: 16 failures on the untouched code: `TypeError ... unexpected keyword argument 'llm_workers'` in the merger-value tests (`_value(..., llm_workers=)` is passed through to `value_mergers`), the CLI tests (no `--llm-workers`), `test_llm_calls_are_filled_ahead_on_llm_workers_while_sec_reads_stay_on_one_thread`, `test_threads_asking_for_one_answer_file_pay_for_one_call` and `test_llm_answers_and_tables_do_not_depend_on_the_llm_worker_count`.

- [ ] **Step 3: Implement**

The sequential pass already reads a warm cache: only the thread count that fills it changes.

```diff
diff --git a/scripts/classify_universe.py b/scripts/classify_universe.py
index 6c0749a..ec8f463 100644
--- a/scripts/classify_universe.py
+++ b/scripts/classify_universe.py
@@ -101,6 +101,8 @@ MANUAL_OVERRIDES: dict[str, int] = {
 
 DEFAULT_SEC_WORKERS = 4     # threads prefetching SEC data; each stage itself stays sequential
 MAX_SEC_WORKERS = 8         # one process's ceiling: all threads share one 8 requests/s limit
+DEFAULT_LLM_WORKERS = 8     # threads making LLM calls ahead of the merger stage (a call waits on the model, not SEC)
+MAX_LLM_WORKERS = 16
 DEFAULT_REVIEW_DECISIONS = str(ROOT / "data" / "review_decisions.csv")
 DEFAULT_SCORECARD = str(ROOT / "data" / "scorecard.json")
 
@@ -184,6 +186,13 @@ def build_parser() -> argparse.ArgumentParser:
                         "from every other SEC client on this machine through the lock file "
                         "$DELIST_DETECTION_SEC_RATE_LOCK (default ~/.cache/delist_detection/sec_rate.lock), "
                         "shares one 8 requests/s limit, so more threads only fill that limit sooner.")
+    p.add_argument("--llm-workers", type=int, default=DEFAULT_LLM_WORKERS,
+                   help=f"Threads that make the --extract-merger-terms-llm calls ahead of the merger stage (default "
+                        f"%(default)s, at most {MAX_LLM_WORKERS}; 1 = one call at a time). Independent of "
+                        "--sec-workers: a call waits on the model, and the tables are the same for any count. These "
+                        "threads also read a candidate filing's text from EDGAR when it is not cached, so up to this "
+                        "many SEC requests can be in flight (the 8 requests/s limit still holds); for one SEC "
+                        "request at a time give --sec-workers 1 --llm-workers 1.")
     p.add_argument("--as-of", type=run_date, default=None, metavar="YYYY-MM-DD",
                    help="The run date every freshness rule reads (default: today). Pin it to an earlier run's "
                         "date (run_manifest.json's as_of) to reproduce that run's tables from the same caches.")
@@ -275,6 +284,8 @@ def main() -> int:
     args = p.parse_args()
     if not 1 <= args.sec_workers <= MAX_SEC_WORKERS:
         p.error(f"--sec-workers must be between 1 and {MAX_SEC_WORKERS}")
+    if not 1 <= args.llm_workers <= MAX_LLM_WORKERS:
+        p.error(f"--llm-workers must be between 1 and {MAX_LLM_WORKERS}")
     try:
         require_user_agent()           # SEC 403s the fallback: stop before the first request
         use_machine_wide_limit()       # every SEC client on this machine shares the 8 requests/s
@@ -297,7 +308,8 @@ def main() -> int:
     )
     log = (lambda *a: None) if args.quiet else None
     summary = run(index, clients, overrides, out_dir=Path(args.output_dir), tol=args.merger_terms_sanity_tol,
-                  limit=args.limit, sec_workers=args.sec_workers, review_decisions=review_decisions,
+                  limit=args.limit, sec_workers=args.sec_workers, llm_workers=args.llm_workers,
+                  review_decisions=review_decisions,
                   scorecard=scorecard, id_baseline=id_baseline,
                   id_baseline_history=id_baseline_history, **({"log": log} if log else {}))
     print("Rows written:", summary.counts)
diff --git a/src/delist_detection/pipeline.py b/src/delist_detection/pipeline.py
index 440a2af..3386800 100644
--- a/src/delist_detection/pipeline.py
+++ b/src/delist_detection/pipeline.py
@@ -210,7 +210,7 @@ def _warm_delisting_search(clients: Clients, ordered: list[Security], listing: d
 
 def run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path,
         tol: float = DEFAULT_TOL, limit: int | None = None, log: Callable = _stderr,
-        sec_workers: int = 1, review_decisions: Sequence[Decision] = (),
+        sec_workers: int = 1, llm_workers: int | None = None, review_decisions: Sequence[Decision] = (),
         scorecard: run_scorecard.ScorecardConfig = run_scorecard.ScorecardConfig(),
         id_baseline: Sequence[Mapping[str, str]] = (),
         id_baseline_history: Sequence[Mapping[str, str]] = ()) -> RunSummary:
@@ -242,7 +242,11 @@ def run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_
     many threads (`prefetch.warm`: fill-only, every thread under the one limiter).
     Each stage itself still runs one item at a time, in its usual order, on this
     thread, so the same caches and run date (`clients.as_of`) give byte-identical
-    tables for any worker count. A refusal on any thread aborts the run before
+    tables for any worker count. `llm_workers` (default: `sec_workers`) is the same for the LLM merger-terms calls
+    (`merger_value._read_terms`), which wait on the model, so a run with one SEC worker can still make them on many
+    threads. Those threads also read a candidate filing's text from EDGAR when it is not cached, so up to
+    `llm_workers` SEC requests can then be in flight at once (the shared 8 requests/s limit still holds); one SEC
+    request at a time takes `sec_workers=1, llm_workers=1`. A refusal on any thread aborts the run before
     anything is written. The resolver's memo is written after issuer resolution,
     after the acquirer lookups, and on the way out, error or not. On the way out
     of an aborted run, a memo that cannot be written is logged and the abort (a
@@ -250,8 +254,8 @@ def run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_
     still exits with that abort's code (2 for a refusal, 4 for an OpenFIGI outage)."""
     try:
         summary = _run(index, clients, overrides, out_dir=out_dir, tol=tol, limit=limit, log=log,
-                       sec_workers=sec_workers, review_decisions=review_decisions, scorecard=scorecard,
-                       id_baseline=id_baseline, id_baseline_history=id_baseline_history)
+                       sec_workers=sec_workers, llm_workers=llm_workers, review_decisions=review_decisions,
+                       scorecard=scorecard, id_baseline=id_baseline, id_baseline_history=id_baseline_history)
     except BaseException:
         try:
             _flush_memo(clients)
@@ -265,12 +269,17 @@ def run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_
 @dataclass
 class _RunContext:
     """What every stage of one run shares: the clients, the one run date (every
-    window ends on it), the log, the prefetch worker count and the SEC meter."""
+    window ends on it), the log, the prefetch worker counts (SEC reads, LLM calls) and the SEC meter."""
     clients: Clients
     as_of: date
     log: Callable
     sec_workers: int
     meter: run_manifest.StageMeter
+    llm_workers: int | None = None       # None: as many as `sec_workers`
+
+    def __post_init__(self) -> None:
+        if self.llm_workers is None:
+            self.llm_workers = self.sec_workers
 
 
 @dataclass
@@ -506,7 +515,7 @@ def _merger_values(ctx: _RunContext, delistings: list[Delisting], securities: di
     values = value_mergers(delistings, acquirer_line.LineIndex(securities, sightings, sec_cusips, ftd),
                            clients=ctx.clients, closes=closes.closes, own_closes=closes.own,
                            caller_terms=overrides.merger_terms, answers=answers, tol=tol, ftd_lo=ftd_lo,
-                           workers=ctx.sec_workers, log=ctx.log)
+                           workers=ctx.sec_workers, llm_workers=ctx.llm_workers, log=ctx.log)
     _flush_memo(ctx.clients)
     ctx.meter.done("payouts", mark)
     return values
@@ -1477,14 +1486,15 @@ def _merger_terms_usage(extractor) -> dict | None:
 
 
 def _run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path, tol: float,
-         limit: int | None, log: Callable, sec_workers: int,
+         limit: int | None, log: Callable, sec_workers: int, llm_workers: int | None = None,
          review_decisions: Sequence[Decision] = (),
          scorecard: run_scorecard.ScorecardConfig = run_scorecard.ScorecardConfig(),
          id_baseline: Sequence[Mapping[str, str]] = (),
          id_baseline_history: Sequence[Mapping[str, str]] = ()) -> RunSummary:
     """The run's stages in order (each function's docstring says what it does);
     `run` wraps it with the resolver memo's final flush."""
-    ctx = _RunContext(clients, clients.as_of or date.today(), log, sec_workers, run_manifest.StageMeter(log))
+    ctx = _RunContext(clients, clients.as_of or date.today(), log, sec_workers, run_manifest.StageMeter(log),
+                      llm_workers)
     for capability in clients.absent():       # each once, before anything is read (production's offer them all)
         log(f"capability absent: {capability.name}: {capability.without}")
     clients.issuers.forget()                  # one issuer record per run: each issuer is read afresh, once
diff --git a/src/delist_detection/terms/llm_merger_extractor.py b/src/delist_detection/terms/llm_merger_extractor.py
index 01dfdeb..3980bcb 100644
--- a/src/delist_detection/terms/llm_merger_extractor.py
+++ b/src/delist_detection/terms/llm_merger_extractor.py
@@ -526,6 +526,7 @@ class LLMMergerTermsExtractor:
         self.max_filings = max_filings
         clean_orphan_temps(self.cache_dir)    # a killed run's cut-off answer
         self._lock = threading.Lock()
+        self._path_locks: dict[Path, threading.Lock] = {}     # one per answer file asked for on a warm thread
         self._asked: set[Path] = set()        # the answers this run asked the model for, on any thread
         self._usage = {"from_cache": 0, "asked": 0, "failed": 0}
 
@@ -739,41 +740,52 @@ class LLMMergerTermsExtractor:
         (cached or fresh) payload is not a usable dict.
         """
         cache_path = self.cache_path(filing, record)
-
-        raw: object
-        if cache_path.exists():
-            try:
-                raw = json.loads(cache_path.read_text())
-            except (json.JSONDecodeError, OSError):
-                raw = None
-        else:
-            raw = None
-
-        if isinstance(raw, dict):
-            with self._lock:
-                asked = cache_path in self._asked
-            self._count("asked" if asked else "from_cache")
-        else:
-            user_prompt = self._user_prompt(excerpt, record, filing, security_name)
-            try:
-                raw = self.llm.extract(SYSTEM_PROMPT, user_prompt, RESULT_SCHEMA)
-            except Exception:
-                self._count("failed")
-                raise
+        with self._path_lock(cache_path):
+            raw = self._cached(cache_path)
             if isinstance(raw, dict):
-                self.cache_dir.mkdir(parents=True, exist_ok=True)
-                write_atomic(cache_path, json.dumps(raw))
                 with self._lock:
-                    self._asked.add(cache_path)
-                self._count("asked")
+                    asked = cache_path in self._asked
+                self._count("asked" if asked else "from_cache")
             else:
-                # an answer that is no JSON object is never cached, so it is asked again on every run: it counts
-                # itself degraded, like a failed call, and the delisting's row carries `resolution_degraded`
-                SEC_STATS.degraded("llm_call")
-                self._count("failed")
+                user_prompt = self._user_prompt(excerpt, record, filing, security_name)
+                try:
+                    raw = self.llm.extract(SYSTEM_PROMPT, user_prompt, RESULT_SCHEMA)
+                except Exception:
+                    self._count("failed")
+                    raise
+                if isinstance(raw, dict):
+                    self.cache_dir.mkdir(parents=True, exist_ok=True)
+                    write_atomic(cache_path, json.dumps(raw))
+                    with self._lock:
+                        self._asked.add(cache_path)
+                    self._count("asked")
+                else:
+                    # an answer that is no JSON object is never cached, so it is asked again on every run: it counts
+                    # itself degraded, like a failed call, and the delisting's row carries `resolution_degraded`
+                    SEC_STATS.degraded("llm_call")
+                    self._count("failed")
 
         return self._to_terms(raw, filing)
 
+    @staticmethod
+    def _cached(cache_path: Path) -> object:
+        """The answer stored at `cache_path`, None when there is none or it cannot be read."""
+        if not cache_path.exists():
+            return None
+        try:
+            return json.loads(cache_path.read_text())
+        except (json.JSONDecodeError, OSError):
+            return None
+
+    def _path_lock(self, cache_path: Path) -> threading.Lock:
+        """The lock of one answer file. Two mergers can ask for one file (the same filing and target ticker), and
+        the warm threads (`merger_value._read_terms`) run them at once: the second waits for the first's call and
+        reads its answer, so a call is never paid for twice. The answer is read and counted under the lock, so a
+        thread that waited counts what it read as any cache hit is counted (`from_cache`, or `asked` when this run
+        asked for it), and a warm thread's reads are still not counted (`_count`)."""
+        with self._lock:
+            return self._path_locks.setdefault(cache_path, threading.Lock())
+
     @staticmethod
     def _user_prompt(excerpt: str, record: DelistRecord, filing: EdgarSubmission | None = None,
                      security_name: str = "") -> str:
diff --git a/src/delist_detection/terms/merger_value.py b/src/delist_detection/terms/merger_value.py
index 91c6a59..9ad2344 100644
--- a/src/delist_detection/terms/merger_value.py
+++ b/src/delist_detection/terms/merger_value.py
@@ -222,12 +222,13 @@ def _quiet(*_: object) -> None:
 class _Stage:
     """What every step of the stage shares: the run's clients (edgar, resolver, issuers, figi, payout_extractor,
     llm_extractor: `pipeline.Clients`), the run's securities as acquirer lines (with the run's fails index, the only
-    reader of the fails files), the first day the run loaded fails rows from, the prefetch worker count and the
-    log."""
+    reader of the fails files), the first day the run loaded fails rows from, the prefetch worker count, the
+    number of threads that make the LLM calls ahead and the log."""
     clients: Any
     index: acquirer_line.LineIndex
     ftd_lo: date | None
     workers: int
+    llm_workers: int
     log: Callable
 
     @property
@@ -246,16 +247,17 @@ class _Stage:
 def value_mergers(delistings: Sequence[Delisting], index: acquirer_line.LineIndex, *, clients: Any,
                   closes: Mapping[DelistingKey, float], caller_terms: Mapping, answers: PriceAnswers, tol: float,
                   own_closes: Mapping[DelistingKey, float] | None = None, ftd_lo: date | None = None,
-                  workers: int = 1, log: Callable = _quiet) -> MergerValues:
+                  workers: int = 1, llm_workers: int | None = None, log: Callable = _quiet) -> MergerValues:
     """Stage 8 (see the module docstring): every merger-bucket delisting of `delistings`, valued. `index` holds the
     run's securities, their ticker sightings, CUSIPs and the fails index (asked here for the acquirer tickers' rows
     around every merger, `FtdIndex.around`; an early merger's lines are read apart, `FtdIndex.apart`); `clients` the
     run's edgar, resolver, issuers (the issuer record), figi, payout_extractor and llm_extractor (`extract(record,
     security_name=)`). `closes` are the last closes the values read (stage 7's: a caller's answered close in place of
     the run's own); `own_closes` the run's own (a --last-trade-closes row, else the fails close; None: `closes` are
-    the run's own), which the reads and the first gate pass read."""
+    the run's own), which the reads and the first gate pass read. `workers` threads fill the EDGAR caches ahead;
+    `llm_workers` (default: `workers`) threads make the LLM calls ahead, since a call waits on the model, not on SEC."""
     own = closes if own_closes is None else own_closes
-    st = _Stage(clients, index, ftd_lo, workers, log)
+    st = _Stage(clients, index, ftd_lo, workers, workers if llm_workers is None else llm_workers, log)
     mergers = [e for e in delistings if e.record.bucket is CrspBucket.MERGER]
     raw, llm_terms, review = _read_terms(st, mergers, own, {sid: s.name or "" for sid, s in st.securities.items()})
     trade_day = {e.key: e.last_trade.day for e in delistings}
@@ -319,15 +321,15 @@ def _read_terms(st: _Stage, mergers: list[Delisting], closes: Mapping[DelistingK
         extractor = clients.payout_extractor
         warm(mergers, lambda e: extractor.extract(e.record, last_close=closes.get(e.key)),
              workers=st.workers, name="payouts")
-    if st.workers > 1 and clients.llm_extractor is not None:
+    if st.llm_workers > 1 and clients.llm_extractor is not None:
         # The LLM calls the sequential pass makes, filled ahead on the worker threads (sub-plan 5f: a new prompt
-        # version asks every merger again). Each call fills the cache entry the sequential pass then reads: the
-        # same candidates in the same order, and a failed call is never cached, so the tables do not depend on the
-        # worker count. A warm thread pays for a call the sequential pass skips only when an EDGAR text read
-        # fails on one thread and not the other.
+        # version asks every merger again; a call takes seconds, so one at a time is most of such a run). Each call
+        # fills the cache entry the sequential pass then reads: the same candidates in the same order, and a failed
+        # call is never cached, so the tables do not depend on the worker count. A warm thread pays for a call the
+        # sequential pass skips only when an EDGAR text read fails on one thread and not the other.
         llm = clients.llm_extractor
         warm(mergers, lambda e: llm.extract(e.record, security_name=names.get(e.sec_id, "")),
-             workers=st.workers, name="llm terms")
+             workers=st.llm_workers, name="llm terms")
     for e in mergers:
         key = e.key
         watch = DegradedWatch()
```

How it stays correct. The `llm terms` warm pass (already in `_read_terms`, gated on `workers > 1`) runs each merger's `extract` on worker threads under `fill_only()`; each call writes its answer file atomically and the sequential pass then reads the files, asking the same candidates in the same order. A failed call is never cached and counts `warm_degraded`, so the sequential pass redoes it and reports it. Two mergers can ask for the same file (same filing and target ticker): `_llm_extract` now holds one lock per file, re-reads the file under it, and calls the model once. The answer is read and counted under that lock, so a thread that waited counts what it read as any cache read is counted (`asked` when this run asked for the file, else `from_cache`; at `c77365a` `usage()` feeds `run_manifest.json`'s `merger_terms`), and a warm thread's own reads are still not counted. The warm threads also read a candidate filing's text from EDGAR when it is not cached, so with `--sec-workers 1` up to `llm_workers` SEC requests can be in flight at once; the shared limiter (8 requests/s for the process and the machine) still holds. `--sec-workers 1 --llm-workers 1` gives the old one request at a time. (`pipeline.run`'s docstring, the `--llm-workers` help text and CLAUDE.md all say this.)

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_classify_universe_cli.py tests/test_merger_value.py tests/test_llm_merger_extractor.py tests/test_pipeline_prefetch.py
```

Expected: all pass.

- [ ] **Step 5: Full-run check against the reference output**

Run the harness's full-run command on a fresh copy of `CACHE_FULL`, then `python3 cmp.py $REF /tmp/run-<tag>/out`.
Expected: `TABLES IDENTICAL`, `manifest checked`. Measured (stand-in client, 2.7 s per call, 769 calls, otherwise warm; `--sec-workers 1`): 8 workers 392.6 s and 398.2 s (two runs), 16 workers 262.2 s; the sequential figure is 769 × 2.7 s = 34 min on top of the 131 s warm run (the 2026-10-10 slow run: 42 m 42 s). All runs: `STANDIN calls=769` (none paid twice), tables identical, the 769 answer files byte-equal to the reference. A warm run (no call to make) is unchanged: 176.0 s → 173.9 s. **Live check** (20 answers deleted from a cache copy, real client, `--llm-workers 8`): 20 `chat.completions` calls, at most 8 in flight, 20 HTTP 200, no 429, no SDK retry, no error; latency 1.7 s min, 2.9 s median, 5.6 s max; 12 answer files byte-equal to the earlier ones and 8 differ in wording only (a ticker spelled `FCE.A` for `FCEA`, a note's punctuation), tables still identical. Run it as: remove 20 `*_claude-sonnet-5-5_v3_*` files from a cache copy, run the full command with `--llm-workers 8` and the real client, allow `api.anthropic.com`.

- [ ] **Step 6: Docs and commit**

Each of these, in this commit:

1. `CLAUDE.md`, *Commands*: after the `--sec-workers 1` line add a line for `--llm-workers N` ("threads that make
   the `--extract-merger-terms-llm` calls ahead; default 8, max 16; independent of `--sec-workers`; the tables are the
   same for any count"). Change the `--sec-workers 1` line's comment from "one SEC request at a time" to "one SEC
   prefetch thread; with `--extract-merger-terms-llm` add `--llm-workers 1` for one SEC request at a time".
2. `CLAUDE.md`, the `llm_merger_extractor.py` bullet (the sentence "`--sec-workers` > 1 the calls are filled ahead on
   the worker threads"): the calls are filled ahead on `--llm-workers` threads (default 8), one lock per answer file
   so no call is paid for twice.
3. `CLAUDE.md`, *The LLM endpoint* invariant: add "the calls run on `--llm-workers` threads before the sequential
   pass reads their answer files. Those threads also read an uncached candidate filing's text from EDGAR, so up to
   that many SEC requests can be in flight, inside the 8 requests/s limit. An LLM call in flight is not cancelled by
   an abort or Ctrl-C: the run waits for it (the client sets no timeout)."
4. `scripts/classify_universe.py`: the comment on `MAX_SEC_WORKERS` becomes "the ceiling on SEC prefetch threads: all
   threads share one 8 requests/s limit (the LLM threads can hold up to MAX_LLM_WORKERS more requests in flight,
   inside the same limit)".
5. `src/delist_detection/sources/prefetch.py`, the `warm` docstring: where it says a request to another service is
   not cancelled, add the LLM call: it goes through no SEC limiter, has no timeout of its own, and the wait on a
   stop lasts until the model answers or the client gives up.
6. `docs/data-flow.md`: (a) in the paragraph that starts "`classify_universe.py --sec-workers N`", add one sentence
   for `--llm-workers N` (default 8, at most 16; the LLM merger-terms calls, filled ahead the same way; they also
   read uncached filing text from EDGAR inside the same limit); (b) in "What stays on the main thread", take the LLM
   extractor out of the list and say its calls are filled ahead on the `--llm-workers` threads; (c) in the Ctrl-C
   paragraph ("waits for each worker's one in-flight request"), add that an LLM call in flight has no such bound.
7. `README.md`: where `--extract-merger-terms-llm` is described (search for the flag), add one sentence naming
   `--llm-workers` and its default.

```bash
git add scripts/classify_universe.py src/delist_detection/pipeline.py src/delist_detection/sources/prefetch.py src/delist_detection/terms/merger_value.py src/delist_detection/terms/llm_merger_extractor.py tests CLAUDE.md README.md docs/data-flow.md
git commit -m "LLM merger terms: --llm-workers threads make the calls ahead, apart from --sec-workers"
```

---

### Task 5: Cheaper fails-index queries and name search

**Files:**
- Modify: `src/delist_detection/sources/ftd.py` (`FtdIndex._slice`, `FtdIndex.trading_rows`, `_date_of`), `src/delist_detection/identity/history.py` (`is_backfilled`), `src/delist_detection/sources/cik_lookup.py` (`CikNameIndex.split_search`)
- Test: `tests/test_ftd.py`, `tests/test_cik_lookup.py`

**Interfaces:**
- Produces: `FtdIndex.trading_rows(cusips, lo=None, hi=None)` (the rows dated in the inclusive ISO span; no bound means the old behaviour), `FtdIndex._slice` by `bisect` with `key=` (Python 3.10+).

- [ ] **Step 1: Write the failing tests**

The tests below are the test part of the working diff (`docs/superpowers/plans/research/2026-10-10-faster-runs/changes-c77365a/05-fails-index-queries.diff`); apply them with `git apply` (they add or extend
the files named), or copy the code.

```diff
diff --git a/tests/test_cik_lookup.py b/tests/test_cik_lookup.py
index 488fae4..ddf5292 100644
--- a/tests/test_cik_lookup.py
+++ b/tests/test_cik_lookup.py
@@ -6,7 +6,8 @@ from pathlib import Path
 import pytest
 import requests
 
-from delist_detection.sources.cik_lookup import CIK_LOOKUP_URL, CikLookupClient, CikNameIndex, normalize_name
+from delist_detection.sources.cik_lookup import (
+    CIK_LOOKUP_URL, CikLookupClient, CikNameIndex, NameHit, normalize_name)
 from delist_detection.sources.edgar import EdgarBlocked
 from delist_detection.sources.sec_stats import SEC_STATS
 
@@ -136,3 +137,15 @@ def test_a_refusal_raises(tmp_path, _no_throttle):
     with pytest.raises(EdgarBlocked):
         CikLookupClient(tmp_path, session=_Session(_Resp(429)), user_agent="ua").index()
     assert not (tmp_path / "cik-lookup-data.txt").exists()
+
+
+def test_split_search_gives_the_exact_then_prefix_entries_a_plain_scan_gives():
+    """The search walks the sorted entries from the first key that can match, without copying the rest of them."""
+    names = ["ALPHA INC", "ALPHA", "ALPHA HOLDINGS CORP", "ALPHABET INC", "BETA CORP", "ALP", "ZETA", "ALPHA"]
+    index = CikNameIndex.from_text("\n".join(f"{n}:{1000 + i}:" for i, n in enumerate(names)))
+    for q in ["ALPHA", "ALP", "A", "ALPHAB", "BETA", "ZZ", "alpha inc", "", "ZETA"]:
+        key = normalize_name(q)
+        want = [(k, c, n) for k, c, n in index._entries if key and k.startswith(key)]
+        exact, prefix = index.split_search(q)
+        assert exact == [NameHit(c, n) for k, c, n in want if k == key]
+        assert prefix == [NameHit(c, n) for k, c, n in want if k != key]
diff --git a/tests/test_ftd.py b/tests/test_ftd.py
index 6801cfe..515cde4 100644
--- a/tests/test_ftd.py
+++ b/tests/test_ftd.py
@@ -322,6 +322,22 @@ def test_trading_rows_skip_a_deleted_symbol_and_keep_the_cusip_order():
     assert idx.descriptions("a00000001") == {"A CO"}
 
 
+def test_trading_rows_in_a_span_are_the_spans_rows_of_trading_rows():
+    """`trading_rows(cusips, lo, hi)` is `trading_rows(cusips)` cut to the inclusive ISO span, either bound open."""
+    days = ["2020-01-02", "2020-01-02", "2020-01-03", "2020-02-03", "2020-02-03", "2020-03-04"]
+    idx = FtdIndex(_rows(*[(d, c, "AAA" if i != 3 else "AAAXXXX", "A CO", 1.0 + i)
+                           for c in ("A00000001", "B00000001") for i, d in enumerate(days)]))
+    every = idx.trading_rows(["B00000001", "A00000001"])
+    for lo, hi in [(None, None), ("2020-01-03", None), (None, "2020-02-03"), ("2020-01-03", "2020-02-03"),
+                   ("2020-01-04", "2020-02-02"), ("2019-01-01", "2019-12-31"), ("2020-03-04", "2020-03-04"),
+                   ("2020-02-03", "2020-01-03")]:
+        want = [r for r in every if (lo is None or r.date >= lo) and (hi is None or r.date <= hi)]
+        assert idx.trading_rows(["B00000001", "A00000001"], lo, hi) == want, (lo, hi)
+        for c in ("A00000001", "B00000001"):
+            assert idx.by_cusip(c, lo, hi) == [r for r in idx.by_cusip(c)
+                                               if (lo is None or r.date >= lo) and (hi is None or r.date <= hi)]
+
+
 def test_symbol_deleted_needs_the_last_rows_under_a_deleted_symbol_only():
     rows = _rows(("2015-10-01", "428236103", "HPQ", "HP INC", 1.0),
                  ("2015-11-02", "428236103", "HPQXXXX", "HP INC", 1.0))
```

- [ ] **Step 2: Run them and see them fail**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_ftd.py tests/test_cik_lookup.py
```

Expected: 1 failure: `test_trading_rows_in_a_span_are_the_spans_rows_of_trading_rows` (`TypeError: trading_rows() takes 2 positional arguments but 4 were given`). The cik_lookup test passes before and after (it pins the search against a plain scan).

- [ ] **Step 3: Implement**

Three small edits:

```diff
diff --git a/src/delist_detection/identity/history.py b/src/delist_detection/identity/history.py
index b2dc82c..7605762 100644
--- a/src/delist_detection/identity/history.py
+++ b/src/delist_detection/identity/history.py
@@ -284,7 +284,7 @@ def is_backfilled(as_of: str, ticker: str, cusips: Sequence[str], ftd: FtdIndex)
     day = date.fromisoformat(as_of)
     lo = (day - timedelta(days=BACKFILL_WINDOW_DAYS)).isoformat()
     hi = (day + timedelta(days=BACKFILL_WINDOW_DAYS)).isoformat()
-    rows = [r for r in ftd.trading_rows(cusips) if lo <= r.date <= hi]
+    rows = ftd.trading_rows(cusips, lo, hi)
     if not rows:
         return False
     bare = bare_ticker(ticker)
diff --git a/src/delist_detection/sources/cik_lookup.py b/src/delist_detection/sources/cik_lookup.py
index c8af9b2..9d0d5d7 100644
--- a/src/delist_detection/sources/cik_lookup.py
+++ b/src/delist_detection/sources/cik_lookup.py
@@ -79,7 +79,9 @@ class CikNameIndex:
             return [], []
         exact: list[NameHit] = []
         prefix: list[NameHit] = []
-        for key, cik, name in self._entries[bisect_left(self._keys, q):]:
+        entries = self._entries
+        for i in range(bisect_left(self._keys, q), len(entries)):       # starts at the first match, copies nothing
+            key, cik, name = entries[i]
             if not key.startswith(q):
                 break
             (exact if key == q else prefix).append(NameHit(cik, name))
diff --git a/src/delist_detection/sources/ftd.py b/src/delist_detection/sources/ftd.py
index 308c751..a699b02 100644
--- a/src/delist_detection/sources/ftd.py
+++ b/src/delist_detection/sources/ftd.py
@@ -28,6 +28,7 @@ from collections import Counter, defaultdict
 from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
 from dataclasses import dataclass, replace
 from datetime import date, timedelta
+from operator import attrgetter
 from pathlib import Path
 from typing import Any, Protocol
 
@@ -49,6 +50,9 @@ _QTR = re.compile(r"cnsp_sec_fails_(\d{4})q([1-4])\.zip$", re.I)
 FTD_START = date(2004, 1, 1)      # the first day SEC's fails-to-deliver files cover
 
 
+_date_of = attrgetter("date")
+
+
 @dataclass(frozen=True)
 class FtdRow:
     date: str
@@ -477,9 +481,8 @@ class FtdIndex:
 
     @staticmethod
     def _slice(rows: list[FtdRow], lo: str | None, hi: str | None) -> list[FtdRow]:
-        dates = [r.date for r in rows]
-        i = bisect_left(dates, lo) if lo else 0
-        j = bisect_right(dates, hi) if hi else len(rows)
+        i = bisect_left(rows, lo, key=_date_of) if lo else 0
+        j = bisect_right(rows, hi, key=_date_of) if hi else len(rows)
         return rows[i:j]
 
     def by_symbol(self, symbol: str, lo: str | None = None, hi: str | None = None) -> list[FtdRow]:
@@ -539,12 +542,13 @@ class FtdIndex:
         """Every description the fails rows of `cusip` carry."""
         return {r.description for r in self.by_cusip(cusip)}
 
-    def trading_rows(self, cusips: Iterable[str]) -> list[FtdRow]:
+    def trading_rows(self, cusips: Iterable[str], lo: str | None = None, hi: str | None = None) -> list[FtdRow]:
         """The rows of `cusips` (each CUSIP's by date, in the order given) that
         show the security trading: not those under a deleted symbol
         (`is_deleted_symbol`), which record a fail still settling after the
-        delisting."""
-        return [r for c in cusips for r in self.by_cusip(c) if not is_deleted_symbol(r.symbol)]
+        delisting. Only those dated in the ISO span [`lo`, `hi`] when either is
+        given (a bound left out is open)."""
+        return [r for c in cusips for r in self.by_cusip(c, lo, hi) if not is_deleted_symbol(r.symbol)]
 
     def symbol_deleted(self, cusips: Iterable[str]) -> bool:
         """Whether `cusips` last failed under a deleted symbol only: after the
```

`_slice` built `[r.date for r in rows]` on every call (203,000 calls over lists thousands of rows long); `bisect` with a key reads only the log(n) rows it compares. `is_backfilled` (108,000 calls) fetched every trading row of the security's CUSIPs and kept the 60 days around one observation; it now asks for that window. `split_search` took a slice of the 1.5-million-entry sorted list on each of 3,352 queries, copying its tail (1.8 ms per call measured at 1,000,000 entries); `itertools.islice` copies nothing but still walks to the start (0.73 ms); the loop now runs over `range(start, len(entries))` and reads entries by index, which starts at the first match in constant time (0.002 ms).

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_ftd.py tests/test_cik_lookup.py
```

Expected: all pass.

- [ ] **Step 5: Full-run check against the reference output**

Run the harness's full-run command on a fresh copy of `CACHE_FULL`, then `python3 cmp.py $REF /tmp/run-<tag>/out`.
Expected: `TABLES IDENTICAL`, `manifest checked`. Measured: 173.9 s → 146.9 s. Peak memory unchanged.

- [ ] **Step 6: Docs and commit**

No doc change beyond the `trading_rows` signature in CLAUDE.md's `ftd.py` bullet ("`trading_rows(cusips, lo=, hi=)`").

```bash
git add src/delist_detection/sources/ftd.py src/delist_detection/identity/history.py src/delist_detection/sources/cik_lookup.py tests/test_ftd.py tests/test_cik_lookup.py
git commit -m "Fails index: slice by bisect, ask is_backfilled for its window only; name search stops copying the entry list"
```

---

### Task 6: Fails rows without a per-row dict, each text held once

**Files:**
- Modify: `src/delist_detection/sources/ftd.py` (`FtdRow`: `slots=True`), `src/delist_detection/sources/ftd_store.py` (`_row` interns the four texts)
- Test: `tests/test_ftd_store.py`

**Interfaces:**
- Produces: `FtdRow` with `__slots__` (still frozen, hashable, `dataclasses.replace` works); the date, CUSIP, symbol and description of rows read from the store are `sys.intern`ed.

- [ ] **Step 1: Write the failing tests**

The tests below are the test part of the working diff (`docs/superpowers/plans/research/2026-10-10-faster-runs/changes-c77365a/06-fails-row-memory.diff`); apply them with `git apply` (they add or extend
the files named), or copy the code.

```diff
diff --git a/tests/test_ftd_store.py b/tests/test_ftd_store.py
index 53a5546..6a2146f 100644
--- a/tests/test_ftd_store.py
+++ b/tests/test_ftd_store.py
@@ -143,6 +143,19 @@ def test_a_build_cut_off_by_a_killed_process_is_cleaned_up_by_the_next_one(tmp_p
     assert not orphan.exists()
 
 
+def test_rows_carry_no_dict_and_share_their_texts(tmp_path):
+    """A run holds millions of rows: an `FtdRow` has no per-row dict, and the same CUSIP, symbol, date or
+    description read from two files is one string."""
+    from dataclasses import replace
+
+    one, two = tmp_path / "cnsfails202401a.zip", tmp_path / "cnsfails202401b.zip"
+    _write_zip(one, {"a.txt": HEADER + "20240102|00206R102|T|500|AT&T INC COM|16.78\n"})
+    _write_zip(two, {"a.txt": HEADER + "20240102|00206R102|T|700|AT&T INC COM|16.80\n"})
+    a = FtdRow(*next(ftd_store.select(ftd_store.ensure(one))))
+    b = FtdRow(*next(ftd_store.select(ftd_store.ensure(two))))
+    assert not hasattr(a, "__dict__") and replace(a, price=1.0).price == 1.0 and hash(a) == hash(replace(a))
+    assert a.cusip is b.cusip and a.symbol is b.symbol and a.date is b.date and a.description is b.description
+
 
 @pytest.mark.parametrize("filters", [{}, {"symbols": {"T"}}, {"cusips": {"037833100"}}, {"symbols": {"BRK-B"}, "cusips": {"G0000Z000"}}])
 def test_parse_ftd_lines_and_the_reference_rule_agree(filters):
```

- [ ] **Step 2: Run them and see them fail**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_ftd_store.py
```

Expected: 1 failure: `test_rows_carry_no_dict_and_share_their_texts` (`FtdRow` still has a `__dict__`; the same CUSIP read from two files is two strings). Verified on the parent commit.

- [ ] **Step 3: Implement**

Two edits:

```diff
diff --git a/src/delist_detection/sources/ftd.py b/src/delist_detection/sources/ftd.py
index a699b02..5663290 100644
--- a/src/delist_detection/sources/ftd.py
+++ b/src/delist_detection/sources/ftd.py
@@ -53,8 +53,10 @@ FTD_START = date(2004, 1, 1)      # the first day SEC's fails-to-deliver files c
 _date_of = attrgetter("date")
 
 
-@dataclass(frozen=True)
+@dataclass(frozen=True, slots=True)
 class FtdRow:
+    """One fails row. A run holds millions, so it keeps no per-row dict (`slots`), and `ftd_store` hands out each date,
+    CUSIP, symbol and description text once (`sys.intern`) however many rows carry it."""
     date: str
     cusip: str
     symbol: str
diff --git a/src/delist_detection/sources/ftd_store.py b/src/delist_detection/sources/ftd_store.py
index 858f0fa..1385081 100644
--- a/src/delist_detection/sources/ftd_store.py
+++ b/src/delist_detection/sources/ftd_store.py
@@ -25,6 +25,7 @@ import sqlite3
 import zipfile
 from collections.abc import Iterator
 from pathlib import Path
+from sys import intern
 
 from .atomic_io import clean_orphan_temps, write_atomic_with
 from ..vocabulary.identifiers import normalize_ticker
@@ -154,9 +155,12 @@ def _build(zip_path: Path, dest: Path, fingerprint: str) -> None:
 
 
 def _row(rec: tuple) -> tuple[str, str, str, str, float | None]:
-    """A stored row as the fields of an `ftd.FtdRow`: (date, CUSIP, symbol, description, price)."""
+    """A stored row as the fields of an `ftd.FtdRow`: (date, CUSIP, symbol, description, price). Each text is
+    interned: a run holds the same few thousand dates, CUSIPs and symbols and a few hundred thousand descriptions
+    in millions of rows."""
     price = rec[5]
-    return rec[1], rec[2], rec[3], rec[4], float(price) if isinstance(price, str) else price
+    return (intern(rec[1]), intern(rec[2]), intern(rec[3]), intern(rec[4]),
+            float(price) if isinstance(price, str) else price)
 
 
 def select(db: Path, *, symbols: set[str] | None = None,
```

A full run holds about 8 million rows in the index. Each row cost a dict (about 100 bytes) and four fresh strings (about 250 bytes) of which a few thousand dates, CUSIPs and symbols and a few hundred thousand descriptions repeat across millions of rows. No code reads `FtdRow.__dict__`, `vars()` or `asdict` (checked).

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts="" tests/test_ftd_store.py
```

Expected: all pass.

- [ ] **Step 5: Full-run check against the reference output**

Run the harness's full-run command on a fresh copy of `CACHE_FULL`, then `python3 cmp.py $REF /tmp/run-<tag>/out`.
Expected: `TABLES IDENTICAL`, `manifest checked`. Measured: 146.9 s → 131.0 s, peak memory 5,450 MB → 4,101 MB.

- [ ] **Step 6: Docs and commit**

CLAUDE.md: update the memory sentence ("Peak memory is 1.8–4.2 GB") with the measured 4.1 GB for the full input (it was 5.5 GB at `6e43e09`).

```bash
git add src/delist_detection/sources/ftd.py src/delist_detection/sources/ftd_store.py tests/test_ftd_store.py CLAUDE.md
git commit -m "Fails rows: no per-row dict, and each text held once"
```

---

### Task 7: The full acceptance run, then the docs that quote it

**Files:** `CLAUDE.md`, `docs/data-flow.md`, `docs/superpowers/plans/research/2026-10-10-faster-runs/RESULTS.md`. Measure first (Steps 1 to 5); the docs quote what was
measured here, at this branch's head, never a figure from an older commit.

- [ ] **Step 1:** Run the full suite once. Record the count.
- [ ] **Step 2:** Run the harness on a fresh copy of `CACHE_FULL` (the first run builds the store), then again on the
  cache that run left (warm). Both: `TABLES IDENTICAL` against `REF`, `manifest checked` with no `MANIFEST DIFF`.
  Record both wall times and both `MAXRSS`.
- [ ] **Step 3:** Run the warm harness with `--sec-workers 4`: the tables are identical and `sec_workers` is the one
  manifest field that differs. Record the wall time.
- [ ] **Step 4:** Stand-in run (the harness's `standin.py`, the LLM answers removed from the cache copy) with
  `--llm-workers 8`, then `--llm-workers 16`: `STANDIN calls=<the count of Task 0 Step 4>`, tables identical, wall
  time under 10 minutes at 8. Record both times. No live LLM call.
- [ ] **Step 5:** Two-ticker run (rows `NWA` and `DAL` of `output/contract/seeds.csv`, as an observations file) on a
  cache copy with the store built, once with the Task 0 copy of the untouched tree and once with this branch: the
  tables are equal. Record both wall times.
- [ ] **Step 6: `CLAUDE.md`.** (a) *Commands*: the full-suite count becomes Step 1's. (b) *Measured SEC request speed*:
  replace the warm-rerun sentence ("about 3–4 min (2m47s at 1 worker, 4m13s at 4)") with Steps 2 and 3's figures and
  the reason extra threads do not help a warm run; add the first-run cost of the store and the two-ticker figures of
  Step 5; keep the cold-run figures as they are (not measured here). (c) The peak-memory sentence ("Peak memory was
  1.8–4.2 GB in older runs") becomes Step 2's `MAXRSS` for the full input.
- [ ] **Step 7: `docs/data-flow.md`.** (a) *Measured speed*: the same warm figures as Step 6(b). (b) The cache
  paragraph ("SEC fails-to-deliver and MIDAS downloads live under `cache/sec_data/ftd/`"): add that each fails ZIP
  is parsed once into `cache/sec_data/ftd/parsed/<zip>.sqlite` (about 1.9 GB in all), rebuilt when the ZIP or the
  line rule changes.
- [ ] **Step 8:** Append the measured figures of Steps 1 to 5 to `docs/superpowers/plans/research/2026-10-10-faster-runs/RESULTS.md` under a heading
  "At `799d1bc` (branch `faster-runs`)".
- [ ] **Step 9:** Commit:

```bash
git add CLAUDE.md docs/data-flow.md docs/superpowers/plans/research/2026-10-10-faster-runs/RESULTS.md
git commit -m "docs: faster runs (fails store, LLM workers): measured figures"
```

---

## Measured results (2026-10-10, one machine, one run at a time)

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

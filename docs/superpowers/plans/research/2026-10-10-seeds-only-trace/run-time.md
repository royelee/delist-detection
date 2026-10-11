# Why a warm run is slow (measured 2026-10-10, commit 6e43e09)

Measured by an agent on copies of the code and cache. Nothing was changed.

## The 42m42s full run was 80% LLM calls

The cache held gpt-5.4 answers and the run used claude-sonnet-5-5, so it made 769 calls.

| Part | Time | Evidence |
| --- | --- | --- |
| Before the first LLM answer | 7m02s | run started 10:49:44, first answer file 10:56:46 |
| LLM calls | 34m17s | 769 answer files, about 2.7 s apart, one at a time |
| After the last answer | 1m23s | last file 11:31:03, run ended 11:32:26 |

## A truly warm full run takes 8m44s

No SEC request, no LLM call, `--sec-workers 1`. The documented figure is 2m47s (2026-09-24, older code).

| Stage | Seconds |
| --- | --- |
| Start-up and the fails-to-deliver open scan | 33 |
| Issuer resolution | 66 |
| FIGI and securities | 6 |
| Line follow | 105 |
| Delisting search | 79 |
| Dead before first sighting | 123 |
| Acquirer lines and payouts | 54 |
| R1, successors, handoffs | 16 |
| Observation map | 33 |
| The rest and the writes | 9 |

## Where the time goes (profile of the main thread, with profiler overhead)

| Function | Share or seconds | Calls | Kind |
| --- | --- | --- | --- |
| `sources/ftd.py` `_scan`: re-reads and re-parses the 436 fails-to-deliver zips | 66% | 76 scans | parse |
| `sources/ftd.py` `parse_ftd_lines` | 237 s own | 8.16M rows | regex per line |
| `vocabulary/identifiers.py` `normalize_ticker` (`re.sub`) | 217 s | 306M | CPU |
| `pipeline.py` `_dead_before_sighting` (calls `FtdIndex.around`) | 291 s | 68 scans | parse |
| `identity/line_follow.py` `follow_lines` | 174 s | 4 scans | parse |
| `sources/edgar.py` `recent_filings`: rebuilds its lists on every call, with a default list allocated per row | 123 s | 8,679 | CPU |
| `identity/issuer_record.py` `_read` (submissions JSON) | 61 s | 9,278 | disk and JSON |
| `terms/merger_value.py` `_gate` | 55 s | 1 | parse |
| `identity/history.py` `is_backfilled` | 47 s | 108k | CPU |
| `_strptime` through `filings/evidence.py` `parse_day` | 39 s | 10.6M | CPU |

Nothing sleeps or waits on a cache hit.

## The fixed cost of a small run

A two-ticker run takes 52 to 69 s. One pass over the fails-to-deliver zips (602 MB, about 25M
lines) costs about 22 s. `FtdIndex.opened` makes one pass and `_security_cusips` (`follow`) makes
two more.

## Suggested changes (estimates, not measured)

1. Parse the fails-to-deliver zips once per run into one table and filter it, in place of
   re-reading the zips on each ask. About 300 to 400 s of the 524 s; a two-ticker run under 10 s.
2. Precompile the regex in `normalize_ticker` and parse ISO dates by slicing in `parse_day`.
   About 60 to 100 s.
3. Remember `recent_filings(cik)` per CIK and fix the per-row default list. About 50 s.

## What was done about it

The three suggestions above, and three more changes, were built and measured the same day. A warm full run went from
8m44s to 2m11s, and a run that makes all 769 LLM calls from 42m42s to 6m38s at 8 LLM workers. The plan is
`docs/superpowers/plans/2026-10-10-faster-runs.md` and the measurements are in
`docs/superpowers/plans/research/2026-10-10-faster-runs/RESULTS.md`.

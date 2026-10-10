# Reset 1: Scorecard, Golden Set and Accuracy Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the library measure itself on every rebuild before any later reset plan changes a table. Every
run writes `output/scorecard.json` with lifecycle coverage and quality and the spec's R1/R2 gap lines. A floor
in `data/scorecard.json` stops any of those numbers from getting worse. A 51-case lifecycle golden set pins what
is right and what is known to be wrong. The decision-17 audit worksheet is drawn and filled from sources.

**Architecture:** Four new pure modules read the output tables as string rows, as `store.read_table` returns
them. `lifecycle.py` walks each security's chain to a terminal. `truth.py` loads hand-checked truth cases and
judges the tables against them. `scorecard.py` turns the tables into one flat dict of numbers and compares it
to a floor. `audit.py` draws the decision-17 sample. `pipeline._run` builds the scorecard from the rows it is
about to write and writes `scorecard.json` after the tables. Two offline scripts recompute the scorecard and
draw the audit from the committed tables. Two tests gate the committed `output/`: the golden set and the floor.

**Tech Stack:** Python ≥ 3.10 standard library (`csv`, `json`, `math`, `random`), the existing `store` and
`atomic_io` modules, pytest. No new dependency (the Clopper–Pearson bound uses bisection, not scipy).

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md` (a copy of
https://claude.ai/artifact/Y9MT7c869AXSyT4gvYQ852), Part 2 "Requirement vs. today" and Part 3 "Order of work",
step 1. Roadmap: `docs/superpowers/plans/2026-10-02-delist-library-reset.md`.

## Global Constraints

- Target, measured here but not reached here: at least 99% of seeds covered and at most 1% uncertain, which is
  about 22 of 2,219 input tickers today.
- "Nothing later may lower a scorecard number." The floor in `data/scorecard.json` enforces this, together with
  `tests/test_scorecard_floor.py`.
- The train+valid window, 2006-01-02 to 2024-12-29, is the caller's data. It lives in `data/scorecard.json`,
  never in library code. The library stays universe-agnostic: no Russell or qlib constant goes in `src/`.
- Accuracy follows decision 17: a census of every high-impact row plus a random sample of 100 of the rest, with
  a one-sided 95% Clopper–Pearson upper bound.
- The library's own confidence is not the measure. "The old identity table read 'high' on every row."
- Tests stay offline. The two committed-output tests read `output/` and `data/` only.
- Outputs are written only after the whole run succeeds. `scorecard.json` is written after the eight tables,
  like `run_manifest.json`.
- Exit codes do not change, because qlib_practice stops on 2 and 3. A scorecard drop or a failing golden case
  warns on stderr. A bad scorecard config or truth file is a bad input file: exit 2.
- SEC fair access applies to Task 9 (network): `EDGAR_USER_AGENT` must be set, requests go through the library's
  throttled client (8 requests/s, one machine-wide lock), and WebFetch is refused by SEC (403).
- Python ≥ 3.10. Write code like the surrounding modules: module docstrings, short pure functions,
  `from __future__ import annotations`.

## Review Focus

1. **A `--limit` or partial run written into `output/`.** CLAUDE.md's dev commands write to `output/` by
   default. Under `--limit` the run must never compare itself to the floor. The committed-output floor test must
   fail with a message that names `git checkout output/`. Pinned by
   `test_a_limit_subset_is_never_compared_to_the_floor` (Task 6) and the docstring of
   `tests/test_scorecard_floor.py` (Task 7).
2. **Truth files edited by hand or in Excel.** A byte-order mark, CIKs with leading zeros, or an `on` date when no
   single security traded the ticker. The file must load, the zeros must be stripped, and the judge must report
   "no single security" without crashing. Pinned by `test_load_truth_reads_every_field_and_a_bom` and
   `test_judge_reports_a_ticker_no_single_security_traded_that_day` (Task 2).
3. **Successor chains that loop or name a `sec_id` missing from `securities.csv`.** The walk must end in `loop`
   or `no_interval`, never in a recursion error. Pinned by `test_a_successor_loop_stops` and
   `test_a_successor_missing_from_the_tables_ends_the_walk_in_no_interval` (Task 1).
4. **A floor that names a metric the scorecard no longer computes.** This happens when the window is removed, the
   audit file is deleted, or reset-2 retires `review.csv`. The check must fail closed and count it as a drop.
   Pinned by `test_drops_reports_a_bad_move_and_a_missing_metric` (Task 3).
5. **The pipeline's scorecard and the script's scorecard disagreeing.** The pipeline builds from in-memory rows
   and the script builds from the written CSVs. Float, boolean or date formatting could differ. They must be
   equal. Pinned by `test_run_writes_the_scorecard_of_the_tables_it_wrote` (Task 6), which compares the two.

## Decisions taken

From the spec's "Decisions needed", this plan adopts two proposals as written:

- **Decision 5.** The unit is the input ticker (one seed, resolved to one security) for R1 and the ending for
  R2. Both per-ticker and per-security coverage are reported.
- **Decision 17.** A census of every high-impact row plus a random 100 of the rest, with a Clopper–Pearson
  bound.

Decision 17's three hard gates are not built here. Two are qlib_practice gates (zero NaN labels inside
train+valid, no uncertain ending with store rows). The third, no harsh mark on an uncertain identity or date,
needs the verdict, so it lands in reset-2.

## Measured baseline

`scorecard.build` on the committed `output/` (as_of 2026-09-25) gives these numbers. Tasks 1 to 3 check
against them.

| Metric | Value | Metric | Value |
| --- | --- | --- | --- |
| `L1.tickers_covered` / `L1.tickers` | 1970 / 2219 | `L1.securities_covered` / `L1.securities` | 1962 / 2210 |
| `L1.left_view` | 119 | `L1.ended_incomplete` | 51 |
| `L1.closed_no_event` | 46 | `L1.no_interval` | 32 |
| `L2.high` / `medium` / `low` | 1547 / 296 / 127 | `R1.1.mapped` / `sightings` | 35419 / 35955 |
| `R1.2.cusip` / `ticker_only` / `placeholder` | 2060 / 50 / 100 | `R1.2.figi_without_cik` | 14 |
| `R1.3.transfer_no_successor` | 126 | `R1.4.review_rows` | 728 |
| `R2.endings` | 883 | `R2.1.missing_last_trade_date` (in window) | 42 (41) |
| `R2.3.blank_dlret_in_window` | 54 (32 need a close, 22 no value) | `R2.4.assumed_par` (in window) | 59 (51) |
| `R2.5.distress` | 54 | `R2.6.distress_flagged` | 39 |

Where these differ from the spec's hand counts (R2.4, the R2.6 sub-counts, R2.2, R1.4), the roadmap's
"Baseline" section explains why.

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `src/delist_detection/lifecycle.py` | create | `Tables`, plus `LifecycleView`: one lifecycle per security and per input ticker, quality, and the look-ups a truth case needs |
| `src/delist_detection/truth.py` | create | Truth-file format, `load_truth`, `write_truth`, `judge`, Clopper–Pearson bound |
| `src/delist_detection/scorecard.py` | create | `build` (the gap table as numbers), `METRICS` directions, `drops`, `raise_floor`, `load_config`, `write` |
| `src/delist_detection/audit.py` | create | Decision-17 sample: `census`, `random_sample`, `worksheet_rows` |
| `src/delist_detection/store.py` | modify | public `formatted(name, rows)` |
| `src/delist_detection/pipeline.py` | modify | stage 10e `_scorecard`; `run(..., scorecard=)`; `RunSummary.scorecard_drops`, `.golden_failures` |
| `scripts/classify_universe.py` | modify | `--scorecard` (default `data/scorecard.json`), warnings, bad config is exit 2 |
| `scripts/scorecard.py` | create | offline: print, `--check`, `--write`, `--raise-floor`, `--lifecycles` |
| `scripts/draw_audit_sample.py` | create | offline: write the audit worksheet once |
| `data/golden_lifecycles.csv` | create | 51 golden cases |
| `data/scorecard.json` | create | window, truth file names, floor |
| `data/accuracy_audit.csv` | create (Task 9) | 421-row audit worksheet, filled from sources |
| `output/scorecard.json` | create | the committed tables' scorecard |
| `tests/lifecycle_tables.py` | create | row builders for small tables |
| `tests/test_lifecycle.py`, `test_truth.py`, `test_scorecard.py`, `test_audit.py`, `test_scorecard_script.py` | create | unit tests |
| `tests/test_golden_lifecycles.py`, `tests/test_scorecard_floor.py` | create | gates on the committed `output/` |
| `tests/test_pipeline.py`, `tests/test_classify_universe_cli.py` | modify | wiring tests |
| `CLAUDE.md`, `README.md`, `CONTEXT.md`, `docs/data-flow.md` | modify | docs |

All commands below run from the repo root. The project's Python is
`~/miniconda3/envs/rdagent4qlib/bin/python`. In a worktree, prefix every command with `PYTHONPATH=src`, as
CLAUDE.md says, because the editable install points at the main checkout.

---

### Task 1: Lifecycle walk

**Files:**
- Create: `src/delist_detection/lifecycle.py`
- Create: `tests/lifecycle_tables.py`
- Test: `tests/test_lifecycle.py`

**Interfaces:**
- Consumes: `store.read_table(name, path)`, `store.table_path(out_dir, name)`, `store.TABLES`.
- Produces:
  - `Tables(securities, ticker_history, delistings, observation_map, review=())`, each a sequence of
    `dict[str, str]`, and `Tables.read(out_dir) -> Tables`. `review.csv` is optional.
  - `Lifecycle(start: str, kind: str, chain: tuple[str, ...], events: tuple[Mapping[str, str], ...],
    quality: str | None)`, with `.covered -> bool` and `.final -> Mapping | None`.
  - `LifecycleView(tables)`, with `.lifecycle(sec_id) -> Lifecycle`, `.by_security() -> dict[str, Lifecycle]`,
    `.by_input_ticker() -> dict[str, Lifecycle]`, `.security_on(ticker, on) -> str | None`,
    `.issuer_of(sec_id) -> str`, `.figi_source_of(sec_id) -> str`, `.tickers_of(sec_ids) -> set[str]`,
    `.end_of(lc) -> str | None`, `.first_sighting(ticker) -> str | None` and `.observed() -> list[str]`.
  - `event_grade(row) -> str`, `weakest(grades) -> str` and `flag_names(row) -> set[str]`.
  - Constants: `ACTIVE`, `ENDED`, `ENDED_INCOMPLETE`, `LEFT_VIEW`, `CLOSED_NO_EVENT`, `NO_INTERVAL`, `LOOP`,
    `NO_MAPPED_SIGHTING`, `COVERED`, `KINDS`, `HIGH`, `MEDIUM`, `LOW`, `LOW_FLAGS`, `EXIT_KIND_OF_BUCKET` and
    `EXIT_KINDS`.

The walk ports the spec's `lifecycle.py` prototype (its "rule 1" quality), which produced the L1 and L2 numbers
in the spec. A real ending is a delistings row whose `successor_sec_id` is not the security itself. The walk
follows a named successor. An open interval that starts after the last real ending means the security kept
trading. An input ticker takes the lifecycle of the security its earliest mapped sighting resolved to.

- [ ] **Step 1: Write the row builders and the failing tests**

`tests/lifecycle_tables.py`:

```python
"""Small output tables for the lifecycle, truth, scorecard and audit tests. Each
helper returns one row with its table's full column set (blank where a test
does not care), as store.read_table would."""
from __future__ import annotations

from delist_detection.lifecycle import Tables
from delist_detection.store import TABLES


def _row(table: str, **cells) -> dict[str, str]:
    row = dict.fromkeys(TABLES[table].columns, "")
    unknown = set(cells) - set(row)
    assert not unknown, f"{table}: no column(s) {sorted(unknown)}"
    row.update({k: str(v) for k, v in cells.items()})
    return row


def sec(sec_id, cik="100", figi_source="cusip", observed=True):
    return _row("securities", sec_id=sec_id, issuer_cik=cik, share_class="COMMON", name=sec_id,
                observed="true" if observed else "false", figi_source=figi_source)


def iv(sec_id, ticker, start, end=""):
    return _row("ticker_history", sec_id=sec_id, ticker=ticker, valid_from=start, valid_to=end, source="observation")


def ending(sec_id, delist_date, bucket="merger", *, ltd="", dlret="", method="cash_only", successor="",
           confidence="high", dlret_confidence="high", flags="", reason="", source="midas"):
    return _row("delistings", sec_id=sec_id, delist_date=delist_date, bucket=bucket, last_trade_date=ltd,
                dlret=dlret, dlret_method=method, successor_sec_id=successor, confidence=confidence,
                dlret_confidence=dlret_confidence, review_flags=flags, reason=reason,
                last_trade_date_source=source if ltd else "")


def obs(ticker, as_of, sec_id="", status="mapped"):
    return _row("observation_map", ticker=ticker, as_of=as_of, sec_id=sec_id, status=status)


def review(sec_id, flags="no_form25"):
    return _row("review", severity="check", sec_id=sec_id, review_flags=flags)


def tables(securities=(), history=(), delistings=(), observations=(), reviews=()) -> Tables:
    return Tables(list(securities), list(history), list(delistings), list(observations), list(reviews))
```

`tests/test_lifecycle.py`:

```python
import pytest

from delist_detection import store
from delist_detection.lifecycle import (ACTIVE, CLOSED_NO_EVENT, ENDED, ENDED_INCOMPLETE, HIGH, LEFT_VIEW, LOOP, LOW,
                                        MEDIUM, NO_INTERVAL, NO_MAPPED_SIGHTING, LifecycleView, Tables, event_grade)
from tests.lifecycle_tables import ending, iv, obs, sec, tables


def _kind(t, sec_id="A"):
    return LifecycleView(t).lifecycle(sec_id).kind


def test_an_open_interval_with_no_ending_is_active():
    assert _kind(tables([sec("A")], [iv("A", "AAA", "2010-01-04")])) == ACTIVE


def test_an_ending_with_reason_date_and_dlret_is_ended():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")],
               [ending("A", "2015-03-10", ltd="2015-03-02", dlret="0.01")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.covered, lc.final["delist_date"]) == (ENDED, True, "2015-03-10")


@pytest.mark.parametrize("cells", [dict(bucket="unknown", ltd="2015-03-02", dlret="0.0"),
                                   dict(bucket="merger", ltd="", dlret="0.01"),
                                   dict(bucket="merger", ltd="2015-03-02", dlret="")])
def test_an_unknown_reason_or_a_blank_date_or_dlret_leaves_the_ending_incomplete(cells):
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")], [ending("A", "2015-03-10", **cells)])
    assert _kind(t) == ENDED_INCOMPLETE


def test_a_transfer_with_no_successor_has_left_view():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0")])
    assert _kind(t) == LEFT_VIEW


def test_closed_intervals_and_no_ending_is_closed_no_event():
    assert _kind(tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")])) == CLOSED_NO_EVENT


def test_a_security_with_no_interval_is_no_interval():
    assert _kind(tables([sec("A")], [], [ending("A", "2007-01-10", ltd="2007-01-09", dlret="0.0")])) == NO_INTERVAL


def test_a_continuing_move_is_not_an_event():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04")],
               [ending("A", "2012-05-01", "exchange_transfer", successor="A", dlret="0.0")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.events) == (ACTIVE, ())


def test_an_ending_that_names_a_successor_continues_the_walk_there():
    t = tables([sec("A"), sec("B", observed=False)],
               [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2015-03-03")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0", successor="B")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.chain, [e["sec_id"] for e in lc.events]) == (ACTIVE, ("A", "B"), ["A"])
    assert lc.final is None                                    # still trading: no final ending


def test_an_open_interval_after_the_last_ending_means_it_kept_trading():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2013-12-31"), iv("A", "AAA", "2016-01-04")],
               [ending("A", "2014-01-10", ltd="2013-12-31", dlret="0.0")])
    assert _kind(t) == ACTIVE


def test_a_successor_loop_stops():
    t = tables([sec("A"), sec("B")],
               [iv("A", "AAA", "2010-01-04", "2012-01-03"), iv("B", "BBB", "2012-01-04", "2014-01-03")],
               [ending("A", "2012-01-10", "exchange_transfer", successor="B"),
                ending("B", "2014-01-10", "exchange_transfer", successor="A")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.chain) == (LOOP, ("A", "B"))


def test_a_successor_missing_from_the_tables_ends_the_walk_in_no_interval():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2012-01-03")],
               [ending("A", "2012-01-10", "exchange_transfer", successor="GONE")])
    lc = LifecycleView(t).lifecycle("A")
    assert (lc.kind, lc.chain) == (NO_INTERVAL, ("A", "GONE"))


@pytest.mark.parametrize("cells, grade", [
    (dict(method="shumway_nasdaq"), LOW), (dict(method="assumed_par"), LOW),
    (dict(flags="last_trade_date_conflict"), LOW), (dict(flags="resolved_by_current_ticker_map;no_form25"), LOW),
    (dict(confidence="medium"), MEDIUM), (dict(dlret_confidence="low"), MEDIUM),
    (dict(dlret_confidence=""), HIGH), (dict(flags="ftd_close_prior:3"), HIGH)])
def test_event_grade(cells, grade):
    assert event_grade(ending("A", "2015-03-10", **cells)) == grade


def test_quality_is_the_weakest_grade_and_a_ticker_only_figi_on_the_chain_is_medium():
    t = tables([sec("A"), sec("B", figi_source="ticker"), sec("C"), sec("D")],
               [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2015-03-03"),
                iv("C", "CCC", "2010-01-04", "2015-03-02"), iv("D", "DDD", "2010-01-04", "2015-03-02")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0", successor="B"),
                ending("C", "2015-03-10", ltd="2015-03-02", dlret="-0.3", method="shumway_nyse_amex"),
                ending("D", "2015-03-10", ltd="2015-03-02", dlret="0.0", flags="ftd_close_lagged")])
    view = LifecycleView(t)
    assert [view.lifecycle(s).quality for s in "ACD"] == [MEDIUM, LOW, HIGH]


def test_quality_is_set_only_on_a_covered_lifecycle():
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0")])
    assert LifecycleView(t).lifecycle("A").quality is None


def test_by_security_covers_observed_securities_only():
    t = tables([sec("A"), sec("X", observed=False)], [iv("A", "AAA", "2010-01-04"), iv("X", "XXX", "2010-01-04")])
    assert set(LifecycleView(t).by_security()) == {"A"}


def test_an_input_ticker_takes_the_lifecycle_of_its_earliest_mapped_sighting():
    t = tables([sec("A"), sec("B")],
               [iv("A", "AAA", "2010-01-04", "2012-01-03"), iv("B", "AAA", "2013-01-04")],
               [ending("A", "2012-01-10", ltd="2012-01-03", dlret="0.0")],
               [obs("AAA", "2009-06-30", "", "unresolved"), obs("AAA", "2010-06-30", "A"),
                obs("AAA", "2014-06-30", "B"), obs("ZZZ", "2010-06-30", "", "unresolved")])
    by_ticker = LifecycleView(t).by_input_ticker()
    assert (by_ticker["AAA"].start, by_ticker["AAA"].kind) == ("A", ENDED)
    assert by_ticker["ZZZ"].kind == NO_MAPPED_SIGHTING and not by_ticker["ZZZ"].covered
    assert LifecycleView(t).first_sighting("AAA") == "2010-06-30"


def test_security_on_prefers_the_observation_map_then_one_covering_interval():
    t = tables([sec("A"), sec("B")],
               [iv("A", "AAA", "2010-01-04", "2012-06-29"), iv("B", "AAA", "2012-06-01")],
               observations=[obs("AAA", "2012-06-15", "A")])
    view = LifecycleView(t)
    assert view.security_on("AAA", "2012-06-15") == "A"           # the map answers
    assert view.security_on("AAA", "2011-01-03") == "A"           # one interval covers it
    assert view.security_on("AAA", "2012-06-20") is None          # two intervals cover it
    assert view.security_on("AAA", "2009-01-02") is None          # none does


def test_end_of_a_lifecycle():
    t = tables([sec("A"), sec("B"), sec("C"), sec("D")],
               [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2010-01-04", "2015-03-02"),
                iv("C", "CCC", "2010-01-04", "2011-05-31"), iv("D", "DDD", "2010-01-04")],
               [ending("A", "2015-03-10", ltd="2015-03-02", dlret="0.0"), ending("B", "2015-03-10")])
    view = LifecycleView(t)
    assert [view.end_of(view.lifecycle(s)) for s in "ABCD"] == ["2015-03-02", "2015-03-10", "2011-05-31", None]


def test_tables_read_the_written_tables(tmp_path):
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04")], [ending("A", "2015-03-10")], [obs("AAA", "2010-06-30", "A")])
    store.write_tables(tmp_path, {"securities": t.securities, "ticker_history": t.ticker_history,
                                  "delistings": t.delistings, "observation_map": t.observation_map})
    back = Tables.read(tmp_path)
    assert back.securities == t.securities and back.delistings == t.delistings and back.review == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_lifecycle.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'delist_detection.lifecycle'`.

- [ ] **Step 3: Write `src/delist_detection/lifecycle.py`**

```python
"""Lifecycles: what the output tables say happened to each security, from its
first ticker interval to today (spec: Delist Library Reset, "How 99% is
measured").

A walk starts at a security and ends in one of these kinds:
- `active`: an open ticker interval today, or one that opens after its last
  real ending (the security kept trading);
- `ended`: its last real ending has a known reason, a last trade date and a
  dlret;
- `ended_incomplete`: it ended, but the reason is unknown or the last trade
  date or the dlret is blank;
- `left_view`: its last real ending is an exchange transfer with no successor
  (the library stopped following it);
- `closed_no_event`: every interval is closed and no ending explains it;
- `no_interval`: it has no ticker interval at all;
- `loop`: a successor chain that comes back to a security already visited.
A real ending is a delistings.csv row whose `successor_sec_id` is not the
security itself (a continuing exchange move is not an event). An ending that
names a successor continues the walk there.

`active` and `ended` are covered. Quality is the weakest grade along a covered
chain (`event_grade`, plus `medium` for a security whose FIGI came from a
ticker-only lookup).

Pure: reads the tables as `store.read_table` returns them (every cell a string).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import store

ACTIVE, ENDED = "active", "ended"
ENDED_INCOMPLETE, LEFT_VIEW = "ended_incomplete", "left_view"
CLOSED_NO_EVENT, NO_INTERVAL, LOOP = "closed_no_event", "no_interval", "loop"
NO_MAPPED_SIGHTING = "no_mapped_sighting"     # an input ticker none of whose sightings has a sec_id
COVERED = frozenset({ACTIVE, ENDED})
KINDS = (ACTIVE, ENDED, ENDED_INCOMPLETE, LEFT_VIEW, CLOSED_NO_EVENT, NO_INTERVAL, LOOP, NO_MAPPED_SIGHTING)

HIGH, MEDIUM, LOW = "high", "medium", "low"
_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}
LOW_FLAGS = frozenset({"last_trade_date_conflict", "resolved_by_current_ticker_map"})

# Today's bucket -> the contract's exit_kind (spec Part 3, delistings.exit_kind).
# `unknown` has none. The contract's own exit_kind column replaces this map
# once it is published.
EXIT_KIND_OF_BUCKET = {"merger": "merger", "exchange_transfer": "exchange", "liquidation": "liquidation",
                       "compliance_failure": "dropped", "expiration": "expiration"}
EXIT_KINDS = frozenset({"merger", "exchange", "liquidation", "dropped", "lost_source", "expiration"})


def flag_names(row: Mapping[str, str]) -> set[str]:
    """The flag names on a delistings.csv row (the part of each token before `:`)."""
    return {f.split(":")[0] for f in row.get("review_flags", "").split(";") if f}


@dataclass(frozen=True)
class Tables:
    """The output tables one lifecycle walk reads, as string rows."""
    securities: Sequence[Mapping[str, str]]
    ticker_history: Sequence[Mapping[str, str]]
    delistings: Sequence[Mapping[str, str]]
    observation_map: Sequence[Mapping[str, str]]
    review: Sequence[Mapping[str, str]] = ()

    @classmethod
    def read(cls, out_dir: str | Path) -> Tables:
        """The tables under `out_dir` (store.read_table: a column mismatch raises)."""
        def rd(name: str) -> list[dict[str, str]]:
            return store.read_table(name, store.table_path(out_dir, name))
        review_path = store.table_path(out_dir, "review")
        return cls(rd("securities"), rd("ticker_history"), rd("delistings"), rd("observation_map"),
                   rd("review") if review_path.exists() else [])


@dataclass(frozen=True)
class Lifecycle:
    start: str                                   # the sec_id the walk started from
    kind: str
    chain: tuple[str, ...] = ()                  # sec_ids visited, in order
    events: tuple[Mapping[str, str], ...] = ()   # the real endings followed, in order
    quality: str | None = None                   # set on a covered lifecycle only

    @property
    def covered(self) -> bool:
        return self.kind in COVERED

    @property
    def final(self) -> Mapping[str, str] | None:
        """The last real ending of the chain, unless the chain is still trading."""
        return self.events[-1] if self.events and self.kind != ACTIVE else None


def event_grade(row: Mapping[str, str]) -> str:
    """One ending's grade: `low` for a Shumway or assumed-par value, a
    conflicting last trade date, or an identity through today's ticker map;
    `medium` when the ending's or its value's confidence is not high; else `high`."""
    method = row.get("dlret_method", "")
    if method.startswith("shumway") or method == "assumed_par" or flag_names(row) & LOW_FLAGS:
        return LOW
    if row.get("confidence") != HIGH or row.get("dlret_confidence") not in (HIGH, ""):
        return MEDIUM
    return HIGH


def weakest(grades: Sequence[str]) -> str:
    return max(grades, key=_RANK.__getitem__, default=HIGH)


@dataclass
class LifecycleView:
    """Lifecycles over one set of tables: per security, per input ticker, and
    the look-ups a truth case needs (`security_on`, `issuer_of`, `tickers_of`)."""
    tables: Tables
    _intervals: dict[str, list[Mapping[str, str]]] = field(init=False)
    _endings: dict[str, list[Mapping[str, str]]] = field(init=False)
    _securities: dict[str, Mapping[str, str]] = field(init=False)
    _mapped: dict[tuple[str, str], str] = field(init=False)
    _memo: dict[str, Lifecycle] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._intervals = defaultdict(list)
        for r in self.tables.ticker_history:
            self._intervals[r["sec_id"]].append(r)
        self._mapped = {(r["ticker"], r["as_of"]): r["sec_id"] for r in self.tables.observation_map if r["sec_id"]}
        self._endings = defaultdict(list)
        for r in self.tables.delistings:
            self._endings[r["sec_id"]].append(r)
        for rows in self._endings.values():
            rows.sort(key=lambda r: r["delist_date"])
        self._securities = {r["sec_id"]: r for r in self.tables.securities}

    # -- look-ups -------------------------------------------------------------
    def observed(self) -> list[str]:
        return sorted(s for s, r in self._securities.items() if r.get("observed") == "true")

    def issuer_of(self, sec_id: str) -> str:
        return self._securities.get(sec_id, {}).get("issuer_cik", "")

    def figi_source_of(self, sec_id: str) -> str:
        return self._securities.get(sec_id, {}).get("figi_source", "")

    def tickers_of(self, sec_ids: Sequence[str]) -> set[str]:
        return {r["ticker"] for s in sec_ids for r in self._intervals.get(s, ())}

    def security_on(self, ticker: str, on: str) -> str | None:
        """The security observation_map maps (ticker, on) to; else the one
        security whose ticker_history interval covers `on` under `ticker`.
        None when neither answers, or ticker_history gives two."""
        if (ticker, on) in self._mapped:
            return self._mapped[(ticker, on)]
        hits = {r["sec_id"] for rows in self._intervals.values() for r in rows
                if r["ticker"] == ticker and r["valid_from"] <= on and (not r["valid_to"] or on <= r["valid_to"])}
        return hits.pop() if len(hits) == 1 else None

    def end_of(self, lc: Lifecycle) -> str | None:
        """The date a lifecycle that is not active ends: its final ending's last
        trade date (else its delist date); with no ending, the latest interval end."""
        if lc.kind == ACTIVE:
            return None
        if lc.final is not None:
            return lc.final["last_trade_date"] or lc.final["delist_date"]
        ends = [r["valid_to"] for s in lc.chain for r in self._intervals.get(s, ()) if r["valid_to"]]
        return max(ends) if ends else None

    # -- the walk -------------------------------------------------------------
    def lifecycle(self, sec_id: str) -> Lifecycle:
        if sec_id not in self._memo:
            kind, chain, events = self._walk(sec_id, ())
            grade = None
            if kind in COVERED:
                grades = [event_grade(e) for e in events]
                grades += [MEDIUM for s in chain if self.figi_source_of(s) == "ticker"]
                grade = weakest(grades)
            self._memo[sec_id] = Lifecycle(sec_id, kind, chain, tuple(events), grade)
        return self._memo[sec_id]

    def _walk(self, s: str, seen: tuple[str, ...]) -> tuple[str, tuple[str, ...], list[Mapping[str, str]]]:
        if s in seen:
            return LOOP, seen, []
        chain = seen + (s,)
        intervals = self._intervals.get(s, [])
        if not intervals:
            return NO_INTERVAL, chain, []
        real = [e for e in self._endings.get(s, []) if e["successor_sec_id"] != s]
        open_ = [r for r in intervals if not r["valid_to"]]
        if not real:
            return (ACTIVE if open_ else CLOSED_NO_EVENT), chain, []
        e = real[-1]
        if any(r["valid_from"] > e["delist_date"] for r in open_):
            return ACTIVE, chain, [e]                 # an open interval after the ending: it kept trading
        if e["successor_sec_id"]:
            kind, chain2, events = self._walk(e["successor_sec_id"], chain)
            return kind, chain2, [e] + events
        if e["bucket"] == "exchange_transfer":
            return LEFT_VIEW, chain, [e]
        complete = e["bucket"] != "unknown" and e["last_trade_date"] and e["dlret"]
        return (ENDED if complete else ENDED_INCOMPLETE), chain, [e]

    def by_security(self) -> dict[str, Lifecycle]:
        """Every observed security's lifecycle."""
        return {s: self.lifecycle(s) for s in self.observed()}

    def by_input_ticker(self) -> dict[str, Lifecycle]:
        """Every input ticker's lifecycle: the one of the security its earliest
        mapped sighting resolved to."""
        first: dict[str, tuple[str, str]] = {}
        tickers: set[str] = set()
        for r in self.tables.observation_map:
            tickers.add(r["ticker"])
            if r["sec_id"] and (r["ticker"] not in first or r["as_of"] < first[r["ticker"]][0]):
                first[r["ticker"]] = (r["as_of"], r["sec_id"])
        return {t: (self.lifecycle(first[t][1]) if t in first else Lifecycle("", NO_MAPPED_SIGHTING))
                for t in sorted(tickers)}

    def first_sighting(self, ticker: str) -> str | None:
        """The earliest date `ticker` was seen with a sec_id, or None."""
        dates = [d for (t, d) in self._mapped if t == ticker]
        return min(dates) if dates else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_lifecycle.py -q`
Expected: `28 passed`.

- [ ] **Step 5: Check the walk against the spec's numbers on the committed output**

Run:

```bash
~/miniconda3/envs/rdagent4qlib/bin/python - <<'EOF'
from collections import Counter
from delist_detection.lifecycle import LifecycleView, Tables
v = LifecycleView(Tables.read("output"))
print(sorted(Counter(lc.kind for lc in v.by_security().values()).items()))
print(sorted(Counter(lc.kind for lc in v.by_input_ticker().values()).items()))
print(sorted(Counter(lc.quality for lc in v.by_input_ticker().values() if lc.covered).items()))
EOF
```

Expected:

```
[('active', 1335), ('closed_no_event', 46), ('ended', 627), ('ended_incomplete', 51), ('left_view', 119), ('no_interval', 32)]
[('active', 1344), ('closed_no_event', 44), ('ended', 626), ('ended_incomplete', 51), ('left_view', 122), ('no_interval', 32)]
[('high', 1547), ('low', 127), ('medium', 296)]
```

1,335 + 627 = 1,962 of 2,210 securities, and 1,344 + 626 = 1,970 of 2,219 tickers: the spec's L1. The quality
counts are the spec's L2. If any number differs, the walk differs from the prototype. Fix the walk; do not edit
the expected numbers.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/lifecycle.py tests/lifecycle_tables.py tests/test_lifecycle.py
git commit -m "Lifecycle walk over the output tables (reset-1)"
```

---

### Task 2: Truth cases and the judge

**Files:**
- Create: `src/delist_detection/truth.py`
- Test: `tests/test_truth.py`

**Interfaces:**
- Consumes: `LifecycleView`, `ACTIVE`, `ENDED`, `EXIT_KIND_OF_BUCKET` and `EXIT_KINDS` from Task 1, and
  `atomic_io.write_atomic`.
- Produces:
  - Constants: `TRUTH_COLUMNS`, `CHECKED`, `PASS`, `KNOWN_WRONG` and `DEFAULT_DLRET_TOL` (0.005).
  - `TruthFileError(ValueError)`.
  - `TruthCase(case, group, ticker, on, issuer_cik="", tickers=(), terminal="", ends_after="", exit_kind="",
    last_trade_date="", dlret=None, dlret_tol=0.005, successor_ticker="", status="", fixed_by="", source="")`,
    with `.pending -> bool`.
  - `Judgement(case, mismatches: tuple[str, ...])`, with `.ok -> bool`.
  - `load_truth(path, *, allow_pending=False) -> list[TruthCase]`.
  - `write_truth(path, rows) -> None`.
  - `judge(case, view) -> Judgement` and `judge_all(cases, view) -> list[Judgement]`.
  - `binom_cdf(k, n, p) -> float` and `clopper_pearson_upper(errors, n, confidence=0.95) -> float`.

A truth case names a security by a ticker and a date it traded, and lists only what was checked. A blank cell is
not checked. One format serves the golden set (`status` is `pass` or `known_wrong`) and the audit (`group` is
`census:<category>` or `random`). `exit_kind` uses the contract's vocabulary. Until reset-3 publishes that
column, the judge maps today's bucket through `EXIT_KIND_OF_BUCKET`.

- [ ] **Step 1: Write the failing tests**

`tests/test_truth.py`:

```python
import csv

import pytest

from delist_detection.lifecycle import LifecycleView
from delist_detection.truth import (TRUTH_COLUMNS, TruthCase, TruthFileError, clopper_pearson_upper, judge,
                                    load_truth)
from tests.lifecycle_tables import ending, iv, obs, sec, tables


def _write(path, rows, header=TRUTH_COLUMNS, bom=False):
    with path.open("w", newline="", encoding="utf-8-sig" if bom else "utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(c, "") for c in header])
    return path


GOOD = dict(case="AAA", group="golden", ticker="AAA", on="2012-06-29", issuer_cik="0000100", tickers="AAA;BBB",
            terminal="ended", ends_after="2014-01-01", exit_kind="merger", last_trade_date="2015-03-02",
            dlret="0.01", dlret_tol="0.001", successor_ticker="BBB", status="known_wrong", fixed_by="reset-4a",
            source="https://www.sec.gov/x", library_says="whatever", note="n")


def test_load_truth_reads_every_field_and_a_bom(tmp_path):
    (case,) = load_truth(_write(tmp_path / "t.csv", [GOOD], bom=True))
    assert case == TruthCase(case="AAA", group="golden", ticker="AAA", on="2012-06-29", issuer_cik="100",
                             tickers=("AAA", "BBB"), terminal="ended", ends_after="2014-01-01", exit_kind="merger",
                             last_trade_date="2015-03-02", dlret=0.01, dlret_tol=0.001, successor_ticker="BBB",
                             status="known_wrong", fixed_by="reset-4a", source="https://www.sec.gov/x")


@pytest.mark.parametrize("change", [
    dict(case=""), dict(ticker=""), dict(on=""), dict(on="2012-13-01"), dict(ends_after="soon"),
    dict(dlret="ten"), dict(dlret_tol="x"), dict(terminal="gone"), dict(exit_kind="bankrupt"),
    dict(status="maybe"), dict(fixed_by=""),
    dict(issuer_cik="", tickers="", terminal="", ends_after="", exit_kind="", last_trade_date="", dlret="",
         successor_ticker=""),
])
def test_load_truth_refuses_a_bad_row_naming_its_line(tmp_path, change):
    with pytest.raises(TruthFileError, match=r"t\.csv:2"):
        load_truth(_write(tmp_path / "t.csv", [{**GOOD, **change}]))


def test_load_truth_refuses_a_repeated_case_and_a_wrong_header(tmp_path):
    with pytest.raises(TruthFileError, match=r"t\.csv:3"):
        load_truth(_write(tmp_path / "t.csv", [GOOD, GOOD]))
    with pytest.raises(TruthFileError, match="columns"):
        load_truth(_write(tmp_path / "h.csv", [GOOD], header=TRUTH_COLUMNS[:-1]))


def test_an_unfilled_audit_row_loads_as_pending_only_when_allowed(tmp_path):
    row = dict(case="random:AAA", group="random", ticker="AAA", on="2012-06-29", library_says="active")
    path = _write(tmp_path / "a.csv", [row])
    with pytest.raises(TruthFileError, match="checks nothing"):
        load_truth(path)
    (case,) = load_truth(path, allow_pending=True)
    assert case.pending


def _view():
    t = tables([sec("A", cik="100"), sec("B", cik="200", observed=False), sec("C", cik="300")],
               [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2015-03-03", "2018-06-29"),
                iv("C", "CCC", "2010-01-04")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0", successor="B"),
                ending("B", "2018-07-09", ltd="2018-06-29", dlret="0.012")],
               [obs("AAA", "2012-06-29", "A")])
    return LifecycleView(t)


def _case(**cells):
    return TruthCase(**{"case": "c", "group": "golden", "ticker": "AAA", "on": "2012-06-29", **cells})


def test_judge_passes_when_every_checked_field_agrees():
    case = _case(issuer_cik="100", tickers=("AAA", "BBB"), terminal="ended", ends_after="2018-01-02",
                 exit_kind="merger", last_trade_date="2018-06-29", dlret=0.01, dlret_tol=0.005,
                 successor_ticker="BBB")
    assert judge(case, _view()).mismatches == ()


@pytest.mark.parametrize("cells, says", [
    (dict(issuer_cik="999"), "issuer_cik 100 != 999"),
    (dict(tickers=("AAA", "ZZZ")), "tickers missing ZZZ"),
    (dict(terminal="active"), "terminal ended != active"),
    (dict(ends_after="2018-06-29"), "ends 2018-06-29, on or before 2018-06-29"),
    (dict(exit_kind="liquidation"), "exit_kind merger != liquidation"),
    (dict(last_trade_date="2018-06-28"), "last_trade_date 2018-06-29 != 2018-06-28"),
    (dict(dlret=0.05), "dlret 0.012 != 0.05 +/- 0.005"),
    (dict(successor_ticker="AAA"), "no successor traded AAA"),
])
def test_judge_names_each_field_that_disagrees(cells, says):
    assert judge(_case(**cells), _view()).mismatches == (says,)


def test_judge_reports_a_ticker_no_single_security_traded_that_day():
    j = judge(_case(ticker="AAA", on="2001-01-02", issuer_cik="100"), _view())
    assert not j.ok and j.mismatches == ("no single security traded AAA on 2001-01-02",)


def test_an_active_lifecycle_never_fails_ends_after_but_has_no_final_ending():
    view = _view()
    assert judge(_case(ticker="CCC", on="2012-06-29", ends_after="2030-01-01"), view).ok
    assert judge(_case(ticker="CCC", on="2012-06-29", exit_kind="merger"), view).mismatches == (
        "no final ending (active)",)


def test_clopper_pearson_upper_bound():
    assert clopper_pearson_upper(0, 100) == pytest.approx(0.0295, abs=1e-4)      # 1 - 0.05 ** (1/100)
    assert clopper_pearson_upper(1, 100) == pytest.approx(0.0466, abs=1e-4)
    assert clopper_pearson_upper(0, 0) == 1.0 and clopper_pearson_upper(5, 5) == 1.0
    assert clopper_pearson_upper(0, 300) < clopper_pearson_upper(0, 100) < clopper_pearson_upper(1, 100)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_truth.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'delist_detection.truth'`.

- [ ] **Step 3: Write `src/delist_detection/truth.py`**

```python
"""Truth cases: what really happened to a security, checked by hand against a
cited source, and the judge that compares the output tables to it.

One file format serves the golden set (`data/golden_lifecycles.csv`, named
cases every rebuild must keep right) and the accuracy audit
(`data/accuracy_audit.csv`, decision 17: a census of the high-impact rows plus
a random sample). A case names a security by a ticker and a date it traded
(`ticker`, `on`) and lists only what was checked; a blank cell is not checked.

    issuer_cik        the issuer CIK of the security found at (ticker, on)
    tickers           `;`-joined tickers its lifecycle must have traded under
    terminal          active | ended
    ends_after        the lifecycle must not end on or before this date
    exit_kind         merger | exchange | liquidation | dropped | lost_source | expiration
                      (of the lifecycle's final ending)
    last_trade_date   of the final ending
    dlret, dlret_tol  of the final ending (measured, else the fill); tol defaults to 0.005
    successor_ticker  a later security of the chain traded under this ticker

`status` (golden only): `pass` must hold now; `known_wrong` must not hold yet
and names the plan expected to fix it in `fixed_by`. `group` (audit only):
`census:<category>` or `random`. `source` holds the URLs the checker opened;
`library_says` is what the output said when the case was drawn (a reminder
for the checker, never judged).
"""
from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .atomic_io import write_atomic
from .lifecycle import ACTIVE, ENDED, EXIT_KIND_OF_BUCKET, EXIT_KINDS, LifecycleView

TRUTH_COLUMNS = ("case", "group", "ticker", "on", "issuer_cik", "tickers", "terminal", "ends_after", "exit_kind",
                 "last_trade_date", "dlret", "dlret_tol", "successor_ticker", "status", "fixed_by", "source",
                 "library_says", "note")
CHECKED = ("issuer_cik", "tickers", "terminal", "ends_after", "exit_kind", "last_trade_date", "dlret",
           "successor_ticker")
PASS, KNOWN_WRONG = "pass", "known_wrong"
DEFAULT_DLRET_TOL = 0.005


class TruthFileError(ValueError):
    """A truth file that cannot be read; the message names the file and line."""


@dataclass(frozen=True)
class TruthCase:
    case: str
    group: str
    ticker: str
    on: str
    issuer_cik: str = ""
    tickers: tuple[str, ...] = ()
    terminal: str = ""
    ends_after: str = ""
    exit_kind: str = ""
    last_trade_date: str = ""
    dlret: float | None = None
    dlret_tol: float = DEFAULT_DLRET_TOL
    successor_ticker: str = ""
    status: str = ""
    fixed_by: str = ""
    source: str = ""

    @property
    def pending(self) -> bool:
        """Nothing checked yet: an audit row nobody has filled in."""
        return all(getattr(self, c) in ("", (), None) for c in CHECKED)


@dataclass(frozen=True)
class Judgement:
    case: TruthCase
    mismatches: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _date(cell: str, where: str) -> str:
    if cell:
        try:
            date.fromisoformat(cell)
        except ValueError:
            raise TruthFileError(f"{where}: {cell!r} is not a YYYY-MM-DD date") from None
    return cell


def _float(cell: str, where: str) -> float | None:
    if not cell:
        return None
    try:
        return float(cell)
    except ValueError:
        raise TruthFileError(f"{where}: {cell!r} is not a number") from None


def load_truth(path: str | Path, *, allow_pending: bool = False) -> list[TruthCase]:
    """Every case in the truth file at `path`. Raises TruthFileError (file and
    line in the message) on a wrong header, a duplicate case id, a missing
    ticker or date, a bad date or number, an unknown terminal, exit_kind or
    status, a known_wrong case with no fixed_by, or (unless `allow_pending`,
    the audit worksheet) a case that checks nothing."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != TRUTH_COLUMNS:
            raise TruthFileError(f"{path}: columns {reader.fieldnames} are not {list(TRUTH_COLUMNS)}")
        out: list[TruthCase] = []
        seen: set[str] = set()
        for line, r in enumerate(reader, start=2):
            where = f"{path}:{line}"
            if not r["case"] or r["case"] in seen:
                raise TruthFileError(f"{where}: case id {r['case']!r} is blank or repeated")
            seen.add(r["case"])
            if not r["ticker"] or not r["on"]:
                raise TruthFileError(f"{where}: ticker and on are required")
            if r["terminal"] not in ("", ACTIVE, ENDED):
                raise TruthFileError(f"{where}: terminal {r['terminal']!r} is not active or ended")
            if r["exit_kind"] and r["exit_kind"] not in EXIT_KINDS:
                raise TruthFileError(f"{where}: exit_kind {r['exit_kind']!r} is not one of {sorted(EXIT_KINDS)}")
            if r["status"] not in ("", PASS, KNOWN_WRONG):
                raise TruthFileError(f"{where}: status {r['status']!r} is not pass or known_wrong")
            if r["status"] == KNOWN_WRONG and not r["fixed_by"]:
                raise TruthFileError(f"{where}: a known_wrong case needs fixed_by")
            tol = _float(r["dlret_tol"], where)
            case = TruthCase(
                case=r["case"], group=r["group"], ticker=r["ticker"], on=_date(r["on"], where),
                issuer_cik=r["issuer_cik"].lstrip("0"), tickers=tuple(t for t in r["tickers"].split(";") if t),
                terminal=r["terminal"], ends_after=_date(r["ends_after"], where), exit_kind=r["exit_kind"],
                last_trade_date=_date(r["last_trade_date"], where), dlret=_float(r["dlret"], where),
                dlret_tol=DEFAULT_DLRET_TOL if tol is None else tol, successor_ticker=r["successor_ticker"],
                status=r["status"], fixed_by=r["fixed_by"], source=r["source"])
            if case.pending and not allow_pending:
                raise TruthFileError(f"{where}: case {case.case!r} checks nothing")
            out.append(case)
    return out


def write_truth(path: str | Path, rows: Sequence[dict[str, str]]) -> None:
    """Write truth rows (every TRUTH_COLUMNS key) to `path` in one atomic replace."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(TRUTH_COLUMNS), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(path, buf.getvalue())


def judge(case: TruthCase, view: LifecycleView) -> Judgement:
    """Compare one case to the tables behind `view`; every checked field that
    disagrees is one mismatch (an empty list: the output is right)."""
    sec = view.security_on(case.ticker, case.on)
    if sec is None:
        return Judgement(case, (f"no single security traded {case.ticker} on {case.on}",))
    lc = view.lifecycle(sec)
    bad: list[str] = []
    if case.issuer_cik and view.issuer_of(sec).lstrip("0") != case.issuer_cik:
        bad.append(f"issuer_cik {view.issuer_of(sec) or '(blank)'} != {case.issuer_cik}")
    if case.tickers:
        missing = sorted(set(case.tickers) - view.tickers_of(lc.chain))
        if missing:
            bad.append(f"tickers missing {';'.join(missing)}")
    if case.terminal and lc.kind != case.terminal:
        bad.append(f"terminal {lc.kind} != {case.terminal}")
    end = view.end_of(lc)
    if case.ends_after and end is not None and end <= case.ends_after:
        bad.append(f"ends {end}, on or before {case.ends_after}")
    final = lc.final
    if case.exit_kind or case.last_trade_date or case.dlret is not None:
        if final is None:
            bad.append(f"no final ending ({lc.kind})")
        else:
            kind = EXIT_KIND_OF_BUCKET.get(final["bucket"], "")
            if case.exit_kind and kind != case.exit_kind:
                bad.append(f"exit_kind {kind or '(none)'} != {case.exit_kind}")
            if case.last_trade_date and final["last_trade_date"] != case.last_trade_date:
                bad.append(f"last_trade_date {final['last_trade_date'] or '(blank)'} != {case.last_trade_date}")
            if case.dlret is not None:
                got = float(final["dlret"]) if final["dlret"] else None
                if got is None or abs(got - case.dlret) > case.dlret_tol:
                    bad.append(f"dlret {final['dlret'] or '(blank)'} != {case.dlret} +/- {case.dlret_tol}")
    if case.successor_ticker and case.successor_ticker not in view.tickers_of(lc.chain[1:]):
        bad.append(f"no successor traded {case.successor_ticker}")
    return Judgement(case, tuple(bad))


def judge_all(cases: Sequence[TruthCase], view: LifecycleView) -> list[Judgement]:
    return [judge(c, view) for c in cases]


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson_upper(errors: int, n: int, confidence: float = 0.95) -> float:
    """The one-sided Clopper-Pearson upper bound on an error rate after
    `errors` wrong in `n` checked: the p at which seeing `errors` or fewer has
    probability 1 - confidence. 0 wrong in 100 gives about 0.0295."""
    if n <= 0:
        return 1.0
    if errors >= n:
        return 1.0
    alpha = 1.0 - confidence
    lo, hi = errors / n, 1.0
    for _ in range(100):                    # bisection: binom_cdf falls as p rises
        mid = (lo + hi) / 2
        if binom_cdf(errors, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_truth.py tests/test_lifecycle.py -q`
Expected: `55 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/truth.py tests/test_truth.py
git commit -m "Truth cases, the judge and the Clopper-Pearson bound (reset-1)"
```

---

### Task 3: The scorecard

**Files:**
- Create: `src/delist_detection/scorecard.py`
- Test: `tests/test_scorecard.py`

**Interfaces:**
- Consumes: Task 1 (`Tables`, `LifecycleView`, the kind and grade constants, `flag_names`), Task 2
  (`TruthCase`, `TruthFileError`, `load_truth`, `judge_all`, `clopper_pearson_upper`, `PASS`, `KNOWN_WRONG`) and
  `atomic_io.write_atomic`.
- Produces:
  - Constants: `SCORECARD_NAME` (`"scorecard.json"`), `UP`, `DOWN`, `DISTRESS`, `EXCHANGE_PRINT_SOURCES`,
    `CONTINUED_FILINGS`, `CENSUS_GROUPS`, and `METRICS: dict[str, str]` (each floored metric and its good
    direction).
  - `ScorecardConfigError(ValueError)`.
  - `Window(start: str, end: str)`, with `.contains(iso) -> bool`.
  - `ScorecardConfig(window=None, floor={}, golden=(), audit=())` and `load_config(path) -> ScorecardConfig`.
  - `build(tables, *, as_of: date, config=ScorecardConfig()) -> dict`, with keys `as_of`, `window`, `metrics` and
    `golden_failures`.
  - `drops(card, floor) -> list[str]` (each entry `"name: floor -> now"`) and
    `raise_floor(card, floor) -> dict[str, float]`.
  - `write(out_dir, card) -> Path`.

`data/scorecard.json` has the shape `{"window": {"start", "end"} | null, "floor": {metric: number}, "golden":
file, "audit": file}`. The two truth files are named relative to the config's folder. A missing truth file
means no cases. Lines whose names end in `_in_window` exist only when the config names a window. A floored
metric missing from the scorecard counts as a drop.

- [ ] **Step 1: Write the failing tests**

`tests/test_scorecard.py`:

```python
import json
from datetime import date

import pytest

from delist_detection import scorecard as sc
from delist_detection.scorecard import ScorecardConfig, ScorecardConfigError, Window
from delist_detection.truth import TRUTH_COLUMNS, TruthCase
from tests.lifecycle_tables import ending, iv, obs, review, sec, tables

AS_OF = date(2026, 9, 25)


def _tables():
    """A: merger, complete. B: transfer with no successor (left view). C: active, ticker-only FIGI.
    D: liquidation with a blank dlret and a conflicting date. E: placeholder, merger with no last trade date.
    F: a FIGI security with no CIK, active."""
    return tables(
        [sec("A"), sec("B"), sec("C", figi_source="ticker"), sec("D"), sec("CIK5-COMMON", cik="5", figi_source="placeholder"),
         sec("F", cik="")],
        [iv("A", "AAA", "2008-01-02", "2012-03-01"), iv("B", "BBB", "2008-01-02", "2010-05-03"),
         iv("C", "CCC", "2008-01-02"), iv("D", "DDD", "2008-01-02", "2025-02-03"),
         iv("CIK5-COMMON", "EEE", "2008-01-02", "2016-04-01"), iv("F", "FFF", "2008-01-02")],
        [ending("A", "2012-03-10", ltd="2012-03-01", dlret="0.02"),
         ending("B", "2010-05-10", "exchange_transfer", ltd="2010-05-03", dlret="0.0",
                method="exchange_transfer_zero", reason="Continued 10-K/Q filings >180d after delist"),
         ending("D", "2025-02-10", "liquidation", ltd="2025-02-03", method="unknown",
                flags="last_trade_date_conflict"),
         ending("CIK5-COMMON", "2016-04-10", method="needs_last_trade")],
        [obs("AAA", "2010-06-30", "A"), obs("BBB", "2009-06-30", "B"), obs("CCC", "2010-06-30", "C"),
         obs("DDD", "2010-06-30", "D"), obs("EEE", "2010-06-30", "CIK5-COMMON"), obs("FFF", "2010-06-30", "F"),
         obs("FFF", "2011-06-30", "F", "backfilled_ticker"), obs("GGG", "2010-06-30", "", "unresolved")],
        [review("B"), review("B", "successor_unknown"), review("D")])


def test_build_counts_the_lifecycle_identity_and_ending_lines():
    m = sc.build(_tables(), as_of=AS_OF)["metrics"]
    assert {k: m[k] for k in ("L1.tickers", "L1.tickers_covered", "L1.securities", "L1.securities_covered",
                              "L1.left_view", "L1.ended_incomplete", "L1.no_mapped_sighting")} == {
        "L1.tickers": 7, "L1.tickers_covered": 3, "L1.securities": 6, "L1.securities_covered": 3,
        "L1.left_view": 1, "L1.ended_incomplete": 2, "L1.no_mapped_sighting": 1}
    assert m["L1.coverage_tickers"] == round(3 / 7, 6)
    assert (m["L2.high"], m["L2.medium"], m["L2.low"]) == (2, 1, 0)       # C: a ticker-only FIGI
    assert (m["R1.1.sightings"], m["R1.1.mapped"], m["R1.1.status.backfilled_ticker"]) == (8, 6, 1)
    assert (m["R1.2.cusip"], m["R1.2.ticker_only"], m["R1.2.placeholder"], m["R1.2.figi_without_cik"]) == (4, 1, 1, 1)
    assert (m["R1.3.transfer_no_successor"], m["R1.4.review_rows"], m["R1.4.review_securities"]) == (1, 3, 2)
    assert (m["R2.endings"], m["R2.1.missing_last_trade_date"], m["R2.2.continued_filings_rule"]) == (4, 1, 1)
    assert (m["R2.5.distress"], m["R2.5.distress_blank_dlret"], m["R2.6.distress_date_flagged"]) == (1, 1, 1)


def test_window_lines_appear_only_with_a_window():
    assert "R2.3.blank_dlret_in_window" not in sc.build(_tables(), as_of=AS_OF)["metrics"]
    m = sc.build(_tables(), as_of=AS_OF, config=ScorecardConfig(window=Window("2006-01-02", "2024-12-29")))["metrics"]
    assert (m["R2.3.blank_dlret_in_window"], m["R2.3.blank_needs_last_close_in_window"],
            m["R2.3.blank_no_value_in_window"], m["R2.1.missing_last_trade_date_in_window"]) == (1, 1, 0, 1)


def test_empty_tables_give_zero_shares():
    m = sc.build(tables(), as_of=AS_OF)["metrics"]
    assert m["L1.coverage_tickers"] == 0.0 and m["R1.1.mapped_share"] == 0.0 and m["L2.high_share"] == 0.0


def _case(case, status="", group="golden", **cells):
    return TruthCase(case=case, group=group, ticker=cells.pop("ticker", "AAA"), on=cells.pop("on", "2010-06-30"),
                     status=status, fixed_by="reset-4a" if status == "known_wrong" else "", **cells)


def test_golden_and_audit_lines():
    config = ScorecardConfig(
        golden=[_case("ok", "pass", exit_kind="merger"), _case("bad", "pass", exit_kind="liquidation"),
                _case("kw", "known_wrong", ticker="BBB", on="2009-06-30", exit_kind="merger")],
        audit=[_case("r1", group="random", exit_kind="merger"), _case("r2", group="random", exit_kind="liquidation"),
               _case("c1", group="census:left_view", ticker="BBB", on="2009-06-30", exit_kind="merger"),
               _case("p1", group="random")])
    card = sc.build(_tables(), as_of=AS_OF, config=config)
    m = card["metrics"]
    assert (m["G.cases"], m["G.pass"], m["G.pass_failing"], m["G.known_wrong"], m["G.known_wrong_now_right"]) == (
        3, 1, 1, 1, 0)
    assert card["golden_failures"] == ["bad: exit_kind merger != liquidation"]
    assert (m["A.pending"], m["A.random.n"], m["A.random.errors"]) == (1, 2, 1)
    assert (m["A.census.left_view.n"], m["A.census.left_view.errors"], m["A.census.distress.n"]) == (1, 1, 0)
    assert 0.5 < m["A.random.upper95"] < 1.0


def test_drops_reports_a_bad_move_and_a_missing_metric():
    card = {"metrics": {"L1.coverage_tickers": 0.88, "R2.4.assumed_par": 59}}
    assert sc.drops(card, {"L1.coverage_tickers": 0.88, "R2.4.assumed_par": 59}) == []
    assert sc.drops(card, {"L1.coverage_tickers": 0.9, "R2.4.assumed_par": 58, "G.pass": 27}) == [
        "G.pass: 27 -> None", "L1.coverage_tickers: 0.9 -> 0.88", "R2.4.assumed_par: 58 -> 59"]


def test_raise_floor_moves_only_the_good_way_and_adds_new_metrics():
    card = {"metrics": {"L1.coverage_tickers": 0.95, "R2.4.assumed_par": 70, "G.pass": 30, "L1.tickers": 9}}
    floor = sc.raise_floor(card, {"L1.coverage_tickers": 0.9, "R2.4.assumed_par": 59})
    assert floor == {"G.pass": 30, "L1.coverage_tickers": 0.95, "R2.4.assumed_par": 59}   # L1.tickers is not floored


def _config(tmp_path, raw, golden_rows=None):
    path = tmp_path / "scorecard.json"
    path.write_text(json.dumps(raw))
    if golden_rows is not None:
        (tmp_path / "golden.csv").write_text(",".join(TRUTH_COLUMNS) + "\n" + "".join(golden_rows))
    return path


def test_load_config_reads_the_window_floor_and_truth_files(tmp_path):
    row = "AAA,golden,AAA,2010-06-30,,,,,merger,,,,,pass,,,,\n"
    cfg = sc.load_config(_config(tmp_path, {"window": {"start": "2006-01-02", "end": "2024-12-29"},
                                            "floor": {"G.pass": 1}, "golden": "golden.csv",
                                            "audit": "audit.csv"}, [row]))
    assert cfg.window == Window("2006-01-02", "2024-12-29") and cfg.floor == {"G.pass": 1}
    assert [c.case for c in cfg.golden] == ["AAA"] and cfg.audit == []        # a missing audit file: no cases


@pytest.mark.parametrize("raw, says", [
    ({"windw": None}, "unknown key"), ({"window": {"start": "2006-01-02"}}, "window needs"),
    ({"window": {"start": "2024-01-02", "end": "2006-01-02"}}, "starts after"),
    ({"floor": {"L1.tickers": 5}}, "floor entries"), ({"floor": {"G.pass": "many"}}, "floor entries")])
def test_load_config_refuses_a_bad_file(tmp_path, raw, says):
    with pytest.raises(ScorecardConfigError, match=says):
        sc.load_config(_config(tmp_path, raw))


def test_load_config_refuses_text_that_is_not_json(tmp_path):
    (tmp_path / "scorecard.json").write_text("{window")
    with pytest.raises(ScorecardConfigError, match="not JSON"):
        sc.load_config(tmp_path / "scorecard.json")


def test_write_puts_sorted_json_next_to_the_tables(tmp_path):
    path = sc.write(tmp_path, {"metrics": {"b": 1, "a": 2}, "as_of": "2026-09-25"})
    assert path.name == "scorecard.json" and json.loads(path.read_text())["metrics"] == {"a": 2, "b": 1}
    assert path.read_text().index('"a"') < path.read_text().index('"b"')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_scorecard.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'delist_detection.scorecard'`.

- [ ] **Step 3: Write `src/delist_detection/scorecard.py`**

```python
"""The scorecard: how far one run's tables are from the requirement (spec:
Delist Library Reset, Part 2's gap table), as one flat dict of numbers written
to `output/scorecard.json` on every run.

- L1/L2: lifecycle coverage and quality, per input ticker and per security
  (`lifecycle.LifecycleView`).
- R1.x/R2.x: the identity and delisting-return lines of the gap table.
- G.x: the golden set (`data/golden_lifecycles.csv`), A.x: the accuracy audit
  (`data/accuracy_audit.csv`), both judged by `truth.judge`.

`METRICS` gives each floored number its good direction. `drops` compares a
scorecard to the floor in `data/scorecard.json` (a number that moved the bad
way), `raise_floor` moves the floor up to a better scorecard. Window lines
(`*_in_window`) are computed only when the config names the caller's training
window. Pure, apart from `write` and `load_config`.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .atomic_io import write_atomic
from .lifecycle import (CLOSED_NO_EVENT, ENDED_INCOMPLETE, HIGH, LEFT_VIEW, LOW, MEDIUM, NO_INTERVAL,
                        NO_MAPPED_SIGHTING, LifecycleView, Tables, flag_names)
from .truth import KNOWN_WRONG, PASS, TruthCase, TruthFileError, clopper_pearson_upper, judge_all, load_truth

SCORECARD_NAME = "scorecard.json"
UP, DOWN = "up", "down"
DISTRESS = ("liquidation", "compliance_failure")
EXCHANGE_PRINT_SOURCES = ("midas", "ex99_notice", "8k_301", "nasdaq_halt")
CONTINUED_FILINGS = "Continued 10-K/Q filings"
CENSUS_GROUPS = ("distress", "continuation", "left_view", "blank_no_value", "assumed_par")

# Every floored number and the direction that is better. A number not listed
# here is reported but never floored.
METRICS: dict[str, str] = {
    "L1.coverage_tickers": UP, "L1.coverage_securities": UP,
    "L1.left_view": DOWN, "L1.ended_incomplete": DOWN, "L1.closed_no_event": DOWN, "L1.no_interval": DOWN,
    "L1.no_mapped_sighting": DOWN,
    "L2.high_share": UP, "L2.low": DOWN,
    "R1.1.mapped_share": UP,
    "R1.2.cusip_share": UP, "R1.2.ticker_only": DOWN, "R1.2.placeholder": DOWN, "R1.2.figi_without_cik": DOWN,
    "R1.3.transfer_no_successor": DOWN,
    "R1.4.review_rows": DOWN,
    "R2.1.missing_last_trade_date": DOWN, "R2.1.missing_last_trade_date_in_window": DOWN,
    "R2.2.unknown_reason": DOWN, "R2.2.continued_filings_rule": DOWN,
    "R2.3.blank_dlret_in_window": DOWN, "R2.3.blank_no_value_in_window": DOWN,
    "R2.4.assumed_par": DOWN,
    "R2.5.distress_blank_dlret": DOWN, "R2.5.distress_no_last_trade_date": DOWN,
    "R2.6.distress_flagged": DOWN,
    "G.pass": UP,
    "A.random.upper95": DOWN,
    **{f"A.census.{g}.errors": DOWN for g in CENSUS_GROUPS},
}


class ScorecardConfigError(ValueError):
    """data/scorecard.json cannot be read; the message names the file."""


@dataclass(frozen=True)
class Window:
    start: str          # ISO dates, inclusive
    end: str

    def contains(self, iso: str) -> bool:
        return bool(iso) and self.start <= iso <= self.end


@dataclass(frozen=True)
class ScorecardConfig:
    window: Window | None = None
    floor: Mapping[str, float] = field(default_factory=dict)
    golden: Sequence[TruthCase] = ()
    audit: Sequence[TruthCase] = ()


def load_config(path: str | Path) -> ScorecardConfig:
    """data/scorecard.json: {"window": {"start", "end"} | null, "floor": {metric: number},
    "golden": file, "audit": file} (the two truth files relative to the config's
    folder; a missing truth file means no cases). Raises ScorecardConfigError or
    truth.TruthFileError."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScorecardConfigError(f"{path}: not JSON ({exc})") from None
    unknown = set(raw) - {"window", "floor", "golden", "audit"}
    if unknown:
        raise ScorecardConfigError(f"{path}: unknown key(s) {sorted(unknown)}")
    window = None
    if raw.get("window"):
        w = raw["window"]
        try:
            start, end = date.fromisoformat(w["start"]).isoformat(), date.fromisoformat(w["end"]).isoformat()
        except (KeyError, TypeError, ValueError):
            raise ScorecardConfigError(f"{path}: window needs start and end as YYYY-MM-DD") from None
        if start > end:
            raise ScorecardConfigError(f"{path}: window starts after it ends")
        window = Window(start, end)
    floor = raw.get("floor") or {}
    bad = sorted(k for k, v in floor.items() if k not in METRICS or not isinstance(v, (int, float)))
    if bad:
        raise ScorecardConfigError(f"{path}: floor entries {bad} are not floored metrics with a number")

    def cases(key: str) -> list[TruthCase]:
        name = raw.get(key)
        if not name:
            return []
        p = path.parent / name
        return load_truth(p, allow_pending=(key == "audit")) if p.exists() else []
    return ScorecardConfig(window, dict(floor), cases("golden"), cases("audit"))


def _share(n: int, d: int) -> float:
    return round(n / d, 6) if d else 0.0


def _lifecycle_lines(view: LifecycleView) -> dict[str, float]:
    by_ticker, by_security = view.by_input_ticker(), view.by_security()
    kinds_s = Counter(lc.kind for lc in by_security.values())
    kinds_t = Counter(lc.kind for lc in by_ticker.values())
    covered_t = sum(lc.covered for lc in by_ticker.values())
    covered_s = sum(lc.covered for lc in by_security.values())
    grades = Counter(lc.quality for lc in by_ticker.values() if lc.covered)
    out = {
        "L1.tickers": len(by_ticker), "L1.tickers_covered": covered_t,
        "L1.coverage_tickers": _share(covered_t, len(by_ticker)),
        "L1.securities": len(by_security), "L1.securities_covered": covered_s,
        "L1.coverage_securities": _share(covered_s, len(by_security)),
        "L1.left_view": kinds_s[LEFT_VIEW], "L1.ended_incomplete": kinds_s[ENDED_INCOMPLETE],
        "L1.closed_no_event": kinds_s[CLOSED_NO_EVENT], "L1.no_interval": kinds_s[NO_INTERVAL],
        "L1.no_mapped_sighting": kinds_t[NO_MAPPED_SIGHTING],
        "L2.high": grades[HIGH], "L2.medium": grades[MEDIUM], "L2.low": grades[LOW],
        "L2.high_share": _share(grades[HIGH], covered_t),
    }
    return out


def _identity_lines(tables: Tables) -> dict[str, float]:
    statuses = Counter(r["status"] for r in tables.observation_map)
    n_obs = len(tables.observation_map)
    observed = [r for r in tables.securities if r.get("observed") == "true"]
    sources = Counter(r["figi_source"] for r in observed)
    no_cik = sum(1 for r in observed if r["figi_source"] != "placeholder" and not r["issuer_cik"])
    out: dict[str, float] = {
        "R1.1.sightings": n_obs, "R1.1.mapped": statuses["mapped"],
        "R1.1.mapped_share": _share(statuses["mapped"], n_obs),
        **{f"R1.1.status.{s}": n for s, n in sorted(statuses.items())},
        "R1.2.securities": len(observed), "R1.2.cusip": sources["cusip"],
        "R1.2.cusip_share": _share(sources["cusip"], len(observed)),
        "R1.2.ticker_only": sources["ticker"], "R1.2.placeholder": sources["placeholder"],
        "R1.2.figi_without_cik": no_cik,
        "R1.4.review_rows": len(tables.review),
        "R1.4.review_securities": len({r["sec_id"] for r in tables.review if r["sec_id"]}),
    }
    return out


def _ending_lines(tables: Tables, window: Window | None) -> dict[str, float]:
    real = [r for r in tables.delistings if r["successor_sec_id"] != r["sec_id"]]
    inw = (lambda r: window.contains(r["delist_date"])) if window else None
    xfer = [r for r in real if r["bucket"] == "exchange_transfer" and not r["successor_sec_id"]]
    missing_ltd = [r for r in real if not r["last_trade_date"]]
    blank = [r for r in real if not r["dlret"]]
    distress = [r for r in real if r["bucket"] in DISTRESS]
    out: dict[str, float] = {
        "R1.3.transfer_no_successor": len(xfer),
        "R1.3.transfer_no_successor_placeholder": sum(r["sec_id"].startswith("CIK") for r in xfer),
        "R2.endings": len(real),
        "R2.1.with_last_trade_date": len(real) - len(missing_ltd),
        "R2.1.missing_last_trade_date": len(missing_ltd),
        "R2.1.exchange_print_source": sum(r["last_trade_date_source"] in EXCHANGE_PRINT_SOURCES for r in real),
        "R2.2.unknown_reason": sum(r["bucket"] == "unknown" for r in real),
        "R2.2.continued_filings_rule": sum(r["reason"].startswith(CONTINUED_FILINGS) for r in real),
        "R2.4.assumed_par": sum(r["dlret_method"] == "assumed_par" for r in real),
        "R2.5.distress": len(distress),
        "R2.5.distress_blank_dlret": sum(not r["dlret"] for r in distress),
        "R2.5.distress_no_last_trade_date": sum(not r["last_trade_date"] for r in distress),
        "R2.6.distress_flagged": sum(bool(flag_names(r)) for r in distress),
        "R2.6.distress_date_flagged": sum(bool(flag_names(r) & {"last_trade_date_conflict",
                                                                  "last_trade_date_unconfirmed"}) for r in distress),
        "R2.6.distress_ticker_map": sum("resolved_by_current_ticker_map" in flag_names(r) for r in distress),
        "R2.6.distress_normal_price": sum("distress_at_normal_price" in flag_names(r) for r in distress),
    }
    if inw is not None:
        blank_w = [r for r in blank if inw(r)]
        out.update({
            "R2.1.missing_last_trade_date_in_window": sum(inw(r) for r in missing_ltd),
            "R2.3.blank_dlret_in_window": len(blank_w),
            "R2.3.blank_needs_last_close_in_window": sum(r["dlret_method"] == "needs_last_trade" for r in blank_w),
            "R2.3.blank_no_value_in_window": sum(r["dlret_method"] != "needs_last_trade" for r in blank_w),
            "R2.4.assumed_par_in_window": sum(r["dlret_method"] == "assumed_par" and inw(r) for r in real),
            "R2.5.distress_in_window": sum(inw(r) for r in distress),
        })
    return out


def _truth_lines(view: LifecycleView, config: ScorecardConfig) -> dict[str, float]:
    out: dict[str, float] = {}
    golden = judge_all(config.golden, view)
    if golden:
        out["G.cases"] = len(golden)
        out["G.pass"] = sum(j.ok for j in golden if j.case.status == PASS)
        out["G.pass_failing"] = sum(not j.ok for j in golden if j.case.status == PASS)
        out["G.known_wrong"] = sum(j.case.status == KNOWN_WRONG for j in golden)
        out["G.known_wrong_now_right"] = sum(j.ok for j in golden if j.case.status == KNOWN_WRONG)
    if config.audit:
        out["A.pending"] = sum(c.pending for c in config.audit)
    audit = judge_all([c for c in config.audit if not c.pending], view)
    if audit:
        rnd = [j for j in audit if j.case.group == "random"]
        errs = sum(not j.ok for j in rnd)
        out["A.random.n"], out["A.random.errors"] = len(rnd), errs
        out["A.random.upper95"] = round(clopper_pearson_upper(errs, len(rnd)), 6)
        for g in CENSUS_GROUPS:
            rows = [j for j in audit if j.case.group == f"census:{g}"]
            out[f"A.census.{g}.n"] = len(rows)
            out[f"A.census.{g}.errors"] = sum(not j.ok for j in rows)
    return out


def build(tables: Tables, *, as_of: date, config: ScorecardConfig = ScorecardConfig()) -> dict:
    """The scorecard of one run's tables: {"as_of", "window", "metrics", "golden_failures"}."""
    view = LifecycleView(tables)
    metrics = {**_lifecycle_lines(view), **_identity_lines(tables), **_ending_lines(tables, config.window),
               **_truth_lines(view, config)}
    failures = [f"{j.case.case}: {'; '.join(j.mismatches)}" for j in judge_all(config.golden, view)
                if j.case.status == PASS and not j.ok]
    window = None if config.window is None else {"start": config.window.start, "end": config.window.end}
    return {"as_of": as_of.isoformat(), "window": window, "metrics": metrics, "golden_failures": failures}


def drops(card: Mapping, floor: Mapping[str, float]) -> list[str]:
    """Every floored metric that moved the bad way, as `name: floor -> now`
    (a floored metric the scorecard no longer has counts as a drop)."""
    out = []
    for name, bound in sorted(floor.items()):
        now = card["metrics"].get(name)
        if now is None or (METRICS[name] == UP and now < bound) or (METRICS[name] == DOWN and now > bound):
            out.append(f"{name}: {bound} -> {now}")
    return out


def raise_floor(card: Mapping, floor: Mapping[str, float]) -> dict[str, float]:
    """The floor moved to every better number in `card`; a floored metric
    never moves the bad way. Metrics new to the floor enter at their value."""
    out = dict(floor)
    for name, direction in METRICS.items():
        now = card["metrics"].get(name)
        if now is None:
            continue
        if name not in out:
            out[name] = now
        else:
            out[name] = max(out[name], now) if direction == UP else min(out[name], now)
    return dict(sorted(out.items()))


def write(out_dir: str | Path, card: Mapping) -> Path:
    path = Path(out_dir) / SCORECARD_NAME
    write_atomic(path, json.dumps(card, indent=2, sort_keys=True) + "\n")
    return path
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_scorecard.py -q`
Expected: `14 passed`.

- [ ] **Step 5: Check the gap lines on the committed output**

Run:

```bash
~/miniconda3/envs/rdagent4qlib/bin/python - <<'EOF'
from datetime import date
from delist_detection.lifecycle import Tables
from delist_detection.scorecard import ScorecardConfig, Window, build
m = build(Tables.read("output"), as_of=date(2026, 9, 25),
          config=ScorecardConfig(window=Window("2006-01-02", "2024-12-29")))["metrics"]
for k in ("L1.tickers_covered", "L1.securities_covered", "R1.1.mapped", "R1.2.cusip", "R1.2.placeholder",
          "R1.3.transfer_no_successor", "R1.4.review_rows", "R2.endings", "R2.1.missing_last_trade_date_in_window",
          "R2.3.blank_dlret_in_window", "R2.3.blank_no_value_in_window", "R2.4.assumed_par", "R2.6.distress_flagged"):
    print(k, m[k])
EOF
```

Expected, in order: 1970, 1962, 35419, 2060, 100, 126, 728, 883, 41, 54, 22, 59, 39.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/scorecard.py tests/test_scorecard.py
git commit -m "Scorecard: the gap table as numbers, with a floor (reset-1)"
```

---

### Task 4: The audit sample

**Files:**
- Create: `src/delist_detection/audit.py`
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: Task 1 (`LifecycleView`, `LEFT_VIEW`), Task 2 (`TRUTH_COLUMNS`) and Task 3 (`CENSUS_GROUPS`,
  `DISTRESS`, `Window`).
- Produces:
  - `Target(case, group, ticker, on, sec_id)`.
  - `census(view, window) -> tuple[list[Target], list[str]]`. The second list holds the endings that could not
    be anchored.
  - `random_sample(view, exclude: set[str], n: int, seed: int) -> list[Target]`.
  - `library_says(view, sec_id) -> str`.
  - `worksheet_rows(view, targets) -> list[dict[str, str]]`.

Each ending goes into exactly one census group, the first that applies in this order: `distress`,
`continuation`, `left_view`, `blank_no_value` (only with a window), `assumed_par`. A continuing move (successor
= itself) is never an ending. An ending is anchored on a `(ticker, date)` that `security_on` resolves back to its
security. The anchor is tried at each interval's start and then its end, latest interval first. If no interval
works, the security's earliest observation is used, which covers an ending dated before every interval (the
`no_interval` defect). The random sample draws input tickers whose chain touches no census security.

- [ ] **Step 1: Write the failing tests**

`tests/test_audit.py`:

```python
import csv

from delist_detection import audit
from delist_detection.lifecycle import LifecycleView
from delist_detection.scorecard import Window
from delist_detection.truth import TRUTH_COLUMNS, load_truth
from tests.lifecycle_tables import ending, iv, obs, sec, tables

WINDOW = Window("2006-01-02", "2024-12-29")


def _view():
    secs = [sec(s) for s in ("L", "C", "C2", "V", "P", "Q", "N", "R1", "R2", "R3")]
    hist = [iv("L", "LLL", "2008-01-02", "2015-03-02"), iv("C", "CCC", "2008-01-02", "2012-03-01"),
            iv("C2", "CCC", "2012-03-02"), iv("V", "VVV", "2008-01-02", "2011-05-02"),
            iv("P", "PPP", "2008-01-02", "2013-02-01"), iv("Q", "QQQ", "2008-01-02", "2014-02-03"),
            iv("N", "NNN", "2008-01-02"),
            iv("R1", "RA", "2008-01-02"), iv("R2", "RB", "2008-01-02"), iv("R3", "RC", "2008-01-02")]
    ends = [ending("L", "2015-03-10", "liquidation", ltd="2015-03-02", method="assumed_par"),     # distress first
            ending("C", "2012-03-10", "exchange_transfer", ltd="2012-03-01", dlret="0.0", successor="C2"),
            ending("V", "2011-05-10", "exchange_transfer", ltd="2011-05-02", dlret="0.0"),
            ending("P", "2013-02-10", ltd="2013-02-01", dlret="0.0", method="assumed_par"),
            ending("Q", "2014-02-10", method="abstain_no_consideration"),
            ending("N", "2009-01-10", "exchange_transfer", successor="N", dlret="0.0"),      # a continuing move
            ending("Z", "2007-06-01", "merger", method="abstain_no_consideration")]          # before any interval
    secs.append(sec("Z"))
    observations = [obs("ZZZ", "2008-06-30", "Z", "after_delisting"), obs("RA", "2010-06-30", "R1"),
                    obs("RB", "2010-06-30", "R2"), obs("RC", "2010-06-30", "R3"), obs("CCC", "2010-06-30", "C")]
    return LifecycleView(tables(secs, hist, ends, observations))


def test_census_puts_each_ending_in_its_first_group_and_skips_continuing_moves():
    targets, skipped = audit.census(_view(), WINDOW)
    assert {t.sec_id: t.group for t in targets} == {
        "L": "census:distress", "C": "census:continuation", "V": "census:left_view", "P": "census:assumed_par",
        "Q": "census:blank_no_value", "Z": "census:blank_no_value"}
    assert skipped == []
    assert {t.sec_id: (t.ticker, t.on) for t in targets}["V"] == ("VVV", "2008-01-02")


def test_blank_no_value_needs_a_window():
    targets, _ = audit.census(_view(), None)
    assert "Q" not in {t.sec_id for t in targets}


def test_an_ending_before_every_interval_is_anchored_on_its_earliest_observation():
    targets, _ = audit.census(_view(), WINDOW)
    assert {t.sec_id: (t.ticker, t.on) for t in targets}["Z"] == ("ZZZ", "2008-06-30")


def test_the_random_sample_is_repeatable_and_avoids_census_chains():
    view = _view()
    targets, _ = audit.census(view, WINDOW)
    exclude = {t.sec_id for t in targets}
    first = audit.random_sample(view, exclude, 2, seed=7)
    assert first == audit.random_sample(view, exclude, 2, seed=7) and len(first) == 2
    assert {t.ticker for t in first} <= {"RA", "RB", "RC"}                 # CCC's chain starts at census C
    assert all(t.group == "random" and t.on == "2010-06-30" for t in first)


def test_worksheet_rows_load_back_as_pending_truth(tmp_path):
    view = _view()
    targets, _ = audit.census(view, WINDOW)
    rows = audit.worksheet_rows(view, targets)
    path = tmp_path / "audit.csv"
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=TRUTH_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    cases = load_truth(path, allow_pending=True)
    assert len(cases) == len(targets) and all(c.pending for c in cases)
    assert next(r for r in rows if r["case"].startswith("left_view"))["library_says"].startswith("left_view; chain V")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_audit.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'delist_detection.audit'`.

- [ ] **Step 3: Write `src/delist_detection/audit.py`**

```python
"""The accuracy audit's sample (decision 17): a census of every high-impact
ending plus a random sample of the other lifecycles, written as a truth-file
worksheet (`truth.TRUTH_COLUMNS`) for a person to fill in from sources.

Census groups, each ending in exactly one (the first that applies, in
`scorecard.CENSUS_GROUPS` order): `distress` (liquidation or compliance
failure), `continuation` (names a successor other than itself), `left_view`
(the final ending of a left-view lifecycle), `blank_no_value` (blank dlret
inside the window, not just waiting on a last close), `assumed_par`. The
random sample draws input tickers whose lifecycle touches no census security,
with a fixed seed so the draw can be repeated.
"""
from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

from .lifecycle import LEFT_VIEW, LifecycleView
from .scorecard import CENSUS_GROUPS, DISTRESS, Window
from .truth import TRUTH_COLUMNS


@dataclass(frozen=True)
class Target:
    case: str
    group: str
    ticker: str
    on: str
    sec_id: str


def _census_group(row: Mapping[str, str], left_view_rows: set[tuple[str, str]], window: Window | None) -> str | None:
    key = (row["sec_id"], row["delist_date"])
    if row["successor_sec_id"] == row["sec_id"]:
        return None                                     # a continuing move: not an ending
    tests = {
        "distress": row["bucket"] in DISTRESS,
        "continuation": bool(row["successor_sec_id"]),
        "left_view": key in left_view_rows,
        "blank_no_value": (not row["dlret"] and row["dlret_method"] != "needs_last_trade"
                           and window is not None and window.contains(row["delist_date"])),
        "assumed_par": row["dlret_method"] == "assumed_par",
    }
    return next((g for g in CENSUS_GROUPS if tests[g]), None)


def _anchor(view: LifecycleView, sec_id: str, before: str) -> tuple[str, str] | None:
    """A (ticker, date) that `view.security_on` answers with `sec_id`: tried on
    each of its intervals that starts on or before `before`, latest first, at
    the interval's start and then its end; else its earliest observation (an
    ending dated before every interval, the `no_interval` defect)."""
    rows = sorted((r for r in view.tables.ticker_history if r["sec_id"] == sec_id and r["valid_from"] <= before),
                  key=lambda r: r["valid_from"], reverse=True)
    for r in rows:
        for d in (r["valid_from"], r["valid_to"]):
            if d and view.security_on(r["ticker"], d) == sec_id:
                return r["ticker"], d
    seen = sorted((r["as_of"], r["ticker"]) for r in view.tables.observation_map if r["sec_id"] == sec_id)
    return (seen[0][1], seen[0][0]) if seen else None


def census(view: LifecycleView, window: Window | None) -> tuple[list[Target], list[str]]:
    """Every census ending as a Target, and the endings that could not be
    anchored to a (ticker, date) the view resolves back to their security."""
    left_view_rows = {(lc.final["sec_id"], lc.final["delist_date"])
                      for lc in view.by_security().values() if lc.kind == LEFT_VIEW and lc.final is not None}
    out, skipped = [], []
    for row in sorted(view.tables.delistings, key=lambda r: (r["sec_id"], r["delist_date"])):
        group = _census_group(row, left_view_rows, window)
        if group is None:
            continue
        anchor = _anchor(view, row["sec_id"], row["delist_date"])
        if anchor is None:
            skipped.append(f"{row['sec_id']} {row['delist_date']}")
            continue
        out.append(Target(f"{group}:{row['sec_id']}:{row['delist_date']}", f"census:{group}", *anchor, row["sec_id"]))
    return out, skipped


def random_sample(view: LifecycleView, exclude: set[str], n: int, seed: int) -> list[Target]:
    """`n` input tickers drawn with `seed` from those whose lifecycle starts at
    a security and touches none of `exclude`."""
    pool = sorted(t for t, lc in view.by_input_ticker().items() if lc.start and not set(lc.chain) & exclude)
    picked = random.Random(seed).sample(pool, min(n, len(pool)))
    out = []
    for t in sorted(picked):
        lc = view.by_input_ticker()[t]
        out.append(Target(f"random:{t}", "random", t, view.first_sighting(t) or "", lc.start))
    return out


def library_says(view: LifecycleView, sec_id: str) -> str:
    """What the output says about the lifecycle from `sec_id`, for the checker."""
    lc = view.lifecycle(sec_id)
    text = f"{lc.kind}; chain {'>'.join(lc.chain)}; issuer {view.issuer_of(sec_id)}"
    if lc.final is not None:
        f = lc.final
        text += (f"; final {f['bucket']} {f['delist_date']} ltd {f['last_trade_date'] or '-'} "
                 f"dlret {f['dlret'] or '-'} ({f['dlret_method']})")
    return text


def worksheet_rows(view: LifecycleView, targets: list[Target]) -> list[dict[str, str]]:
    """One blank truth row per target (`status` blank: an audit row is counted,
    not pinned)."""
    rows = []
    for t in targets:
        row = dict.fromkeys(TRUTH_COLUMNS, "")
        row.update(case=t.case, group=t.group, ticker=t.ticker, on=t.on, library_says=library_says(view, t.sec_id))
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_audit.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/audit.py tests/test_audit.py
git commit -m "Decision-17 audit sample: census and random draw (reset-1)"
```

---

### Task 5: The two offline scripts

**Files:**
- Create: `scripts/scorecard.py`
- Create: `scripts/draw_audit_sample.py`
- Test: `tests/test_scorecard_script.py`

**Interfaces:**
- Consumes: Tasks 1 to 4, `manifest.MANIFEST_NAME` and `atomic_io.write_atomic`.
- Produces:
  - `scripts/scorecard.py`: `main(argv) -> int`, `LIFECYCLE_COLUMNS`, `lifecycle_rows(view)` and
    `tables_as_of(out_dir)`. Flags: `--output-dir`, `--config`, `--check`, `--write`, `--raise-floor`,
    `--lifecycles PATH`. Exit 0, or 1 with `--check` on a drop or a failing golden `pass` case, or 2 on a bad
    config, truth file or table.
  - `scripts/draw_audit_sample.py`: `main(argv) -> int`. Flags: `--output-dir`, `--config`, `--out`
    (required), `--random` (default 100), `--seed` (default 7). It refuses (exit 2) when `--out` exists.

- [ ] **Step 1: Write the failing tests**

`tests/test_scorecard_script.py`:

```python
"""scripts/scorecard.py and scripts/draw_audit_sample.py over small tables in a temp folder."""
import importlib.util
import json
from pathlib import Path

import pytest

from delist_detection import store
from delist_detection.truth import load_truth
from tests.lifecycle_tables import ending, iv, obs, sec, tables

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scorecard_script, draw_script = _load("scorecard"), _load("draw_audit_sample")


@pytest.fixture
def out(tmp_path):
    t = tables([sec("A"), sec("B"), sec("C")],
               [iv("A", "AAA", "2008-01-02", "2012-03-01"), iv("B", "BBB", "2008-01-02", "2010-05-03"),
                iv("C", "CCC", "2008-01-02")],
               [ending("A", "2012-03-10", ltd="2012-03-01", dlret="0.02"),
                ending("B", "2010-05-10", "exchange_transfer", ltd="2010-05-03", dlret="0.0")],
               [obs("AAA", "2010-06-30", "A"), obs("BBB", "2009-06-30", "B"), obs("CCC", "2010-06-30", "C")])
    out = tmp_path / "output"
    out.mkdir()
    store.write_tables(out, {"securities": t.securities, "ticker_history": t.ticker_history,
                             "delistings": t.delistings, "observation_map": t.observation_map})
    (out / "run_manifest.json").write_text(json.dumps({"as_of": "2026-09-25"}))
    return out


def _config(tmp_path, floor):
    path = tmp_path / "scorecard.json"
    path.write_text(json.dumps({"window": {"start": "2006-01-02", "end": "2024-12-29"}, "floor": floor}))
    return path


def test_check_passes_on_a_held_floor_and_write_puts_the_card_next_to_the_tables(tmp_path, out, capsys):
    cfg = _config(tmp_path, {"L1.left_view": 1})
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--check", "--write"]) == 0
    card = json.loads((out / "scorecard.json").read_text())
    assert card["as_of"] == "2026-09-25" and card["metrics"]["L1.tickers"] == 3 and card["drops"] == []


def test_check_fails_on_a_drop_and_names_it(tmp_path, out, capsys):
    cfg = _config(tmp_path, {"L1.left_view": 0})
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--check"]) == 1
    assert "DROP L1.left_view: 0 -> 1" in capsys.readouterr().out


def test_raise_floor_keeps_the_rest_of_the_config(tmp_path, out):
    cfg = _config(tmp_path, {"L1.coverage_tickers": 0.5})
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--raise-floor"]) == 0
    raw = json.loads(cfg.read_text())
    assert raw["window"] == {"start": "2006-01-02", "end": "2024-12-29"}
    assert raw["floor"]["L1.coverage_tickers"] == round(2 / 3, 6) and raw["floor"]["L1.left_view"] == 1


def test_lifecycles_writes_one_row_per_ticker_and_per_security(tmp_path, out):
    cfg = _config(tmp_path, {})
    path = tmp_path / "lifecycles.csv"
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--lifecycles", str(path)]) == 0
    lines = path.read_text().splitlines()
    assert lines[0] == ",".join(scorecard_script.LIFECYCLE_COLUMNS) and len(lines) == 1 + 3 + 3
    assert "ticker,BBB,B,left_view,,B,2010-05-10,exchange_transfer" in lines


def test_a_bad_config_exits_2(tmp_path, out, capsys):
    cfg = tmp_path / "scorecard.json"
    cfg.write_text('{"floor": {"nope": 1}}')
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg)]) == 2
    assert "ABORTED" in capsys.readouterr().err


def test_draw_writes_a_pending_worksheet_once(tmp_path, out, capsys):
    cfg = _config(tmp_path, {})
    sheet = tmp_path / "audit.csv"
    argv = ["--output-dir", str(out), "--config", str(cfg), "--out", str(sheet), "--random", "5"]
    assert draw_script.main(argv) == 0
    cases = load_truth(sheet, allow_pending=True)
    assert {c.group for c in cases} == {"census:left_view", "random"} and all(c.pending for c in cases)
    assert draw_script.main(argv) == 2 and "exists" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_scorecard_script.py -q`
Expected: collection error `FileNotFoundError` for `scripts/scorecard.py`.

- [ ] **Step 3: Write `scripts/scorecard.py`**

```python
"""Recompute the scorecard from the tables under --output-dir and compare it to
the floor in --config (spec: Delist Library Reset, step 1 "Measure first").

  python scripts/scorecard.py                    # every number, then drops and failing golden cases
  python scripts/scorecard.py --check            # exit 1 if a floored number got worse or a golden pass case fails
  python scripts/scorecard.py --write            # also rewrite <output-dir>/scorecard.json
  python scripts/scorecard.py --raise-floor      # move the config's floor to every better number (never worse)
  python scripts/scorecard.py --lifecycles l.csv # one row per input ticker and per security

Offline. The run date is the tables' own (run_manifest.json's as_of; today
when there is no manifest). Exit 2: a bad config or truth file, or tables
that cannot be read.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.atomic_io import write_atomic
from delist_detection.lifecycle import LifecycleView, Tables
from delist_detection.manifest import MANIFEST_NAME
from delist_detection.scorecard import (ScorecardConfigError, build, drops, load_config, raise_floor, write)
from delist_detection.truth import TruthFileError

LIFECYCLE_COLUMNS = ("unit", "key", "sec_id", "kind", "quality", "chain", "final_delist_date", "final_bucket")


def tables_as_of(out_dir: Path) -> date:
    path = out_dir / MANIFEST_NAME
    return date.fromisoformat(json.loads(path.read_text())["as_of"]) if path.exists() else date.today()


def lifecycle_rows(view: LifecycleView) -> list[dict[str, str]]:
    rows = []
    for unit, lifecycles in (("ticker", view.by_input_ticker()), ("security", view.by_security())):
        for key, lc in sorted(lifecycles.items()):
            final = lc.final or {}
            rows.append({"unit": unit, "key": key, "sec_id": lc.start, "kind": lc.kind, "quality": lc.quality or "",
                         "chain": ";".join(lc.chain), "final_delist_date": final.get("delist_date", ""),
                         "final_bucket": final.get("bucket", "")})
    return rows


def _csv_text(columns, rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--config", type=Path, default=ROOT / "data" / "scorecard.json")
    p.add_argument("--check", action="store_true")
    p.add_argument("--write", action="store_true")
    p.add_argument("--raise-floor", action="store_true")
    p.add_argument("--lifecycles", type=Path)
    args = p.parse_args(argv)
    try:
        config = load_config(args.config)
        tables = Tables.read(args.output_dir)
        as_of = tables_as_of(args.output_dir)
    except (ScorecardConfigError, TruthFileError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    card = build(tables, as_of=as_of, config=config)
    card["drops"] = drops(card, config.floor)
    for name, value in sorted(card["metrics"].items()):
        print(f"{name:48} {value}")
    for line in card["drops"]:
        print(f"DROP {line}")
    for line in card["golden_failures"]:
        print(f"GOLDEN FAILING {line}")
    if args.write:
        print(f"wrote {write(args.output_dir, card)}")
    if args.lifecycles:
        write_atomic(args.lifecycles, _csv_text(LIFECYCLE_COLUMNS, lifecycle_rows(LifecycleView(tables))))
        print(f"wrote {args.lifecycles}")
    if args.raise_floor:
        raw = json.loads(args.config.read_text(encoding="utf-8"))
        raw["floor"] = raise_floor(card, config.floor)
        write_atomic(args.config, json.dumps(raw, indent=2) + "\n")
        print(f"raised the floor in {args.config}")
    if args.check and (card["drops"] or card["golden_failures"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write `scripts/draw_audit_sample.py`**

```python
"""Draw the accuracy audit's sample (decision 17) from the tables under
--output-dir into a truth worksheet for a person to fill in from sources: a
census of every high-impact ending plus --random input tickers drawn with
--seed. Offline. Refuses to overwrite --out.

  python scripts/draw_audit_sample.py --out data/accuracy_audit.csv
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.audit import census, random_sample, worksheet_rows
from delist_detection.lifecycle import LifecycleView, Tables
from delist_detection.scorecard import ScorecardConfigError, load_config
from delist_detection.truth import TruthFileError, write_truth


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--config", type=Path, default=ROOT / "data" / "scorecard.json")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--random", type=int, default=100)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)
    if args.out.exists():
        print(f"ABORTED: {args.out} exists; the audit is drawn once (move it aside to redraw)", file=sys.stderr)
        return 2
    try:
        window = load_config(args.config).window
        view = LifecycleView(Tables.read(args.output_dir))
    except (ScorecardConfigError, TruthFileError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    targets, skipped = census(view, window)
    targets += random_sample(view, {t.sec_id for t in targets}, args.random, args.seed)
    write_truth(args.out, worksheet_rows(view, targets))
    for group, n in sorted(Counter(t.group for t in targets).items()):
        print(f"{group:28} {n}")
    for line in skipped:
        print(f"SKIPPED (no anchor) {line}")
    print(f"wrote {args.out}: {len(targets)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_scorecard_script.py -q`
Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add scripts/scorecard.py scripts/draw_audit_sample.py tests/test_scorecard_script.py
git commit -m "scripts/scorecard.py and scripts/draw_audit_sample.py (reset-1)"
```

---

### Task 6: Every run writes the scorecard

**Files:**
- Modify: `src/delist_detection/store.py` (add `formatted` above `_write_all`)
- Modify: `src/delist_detection/pipeline.py` (imports; `RunSummary`; `run`; new `_scorecard`; `_run` stage 10e
  and step 11)
- Modify: `scripts/classify_universe.py`
- Test: `tests/test_pipeline.py`, `tests/test_classify_universe_cli.py`

**Interfaces:**
- Consumes: `scorecard.ScorecardConfig`, `build`, `drops`, `write`, `load_config`, `ScorecardConfigError`,
  `truth.TruthFileError` and `lifecycle.Tables`.
- Produces:
  - `store.formatted(name, rows) -> list[dict[str, str]]`.
  - `pipeline.run(..., scorecard: ScorecardConfig = ScorecardConfig())`.
  - `RunSummary.scorecard_drops: list[str]` and `RunSummary.golden_failures: list[str]`.
  - `output/scorecard.json` on every run, carrying `drops`.
  - CLI: `--scorecard PATH` and `DEFAULT_SCORECARD`, plus `read_scorecard(path)`. `read_inputs` returns a
    4-tuple. `BAD_INPUT` gains `ScorecardConfigError` and `TruthFileError`.

The scorecard is built from the formatted rows, the rows `read_table` would read back. That way the run and
`scripts/scorecard.py` agree to the digit (Review Focus 5). Under `--limit` the floor is not compared.

- [ ] **Step 1: Write the failing pipeline tests**

In `tests/test_pipeline.py`, add these imports below `from delist_detection.security_master import Security`:

```python
from delist_detection import scorecard as run_scorecard
from delist_detection.lifecycle import Tables
from delist_detection.scorecard import ScorecardConfig, Window
from delist_detection.truth import TruthCase
```

Append at the end of the file:

```python
def test_run_writes_the_scorecard_of_the_tables_it_wrote(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    config = ScorecardConfig(window=Window("2006-01-02", "2024-12-29"))
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, scorecard=config)
    card = json.loads((tmp_path / "scorecard.json").read_text())
    m = card["metrics"]
    assert (m["L1.tickers"], m["L1.securities"], m["R1.1.sightings"], m["R2.endings"]) == (2, 2, 3, 1)
    assert card["window"] == {"start": "2006-01-02", "end": "2024-12-29"} and "R2.3.blank_dlret_in_window" in m
    # the same numbers scripts/scorecard.py computes from the written tables
    again = run_scorecard.build(Tables.read(tmp_path), as_of=date.fromisoformat(card["as_of"]), config=config)
    assert card == {**json.loads(json.dumps(again)), "drops": []}


def test_run_reports_floor_drops_and_failing_golden_cases(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    golden = [TruthCase(case="AET", group="golden", ticker="AET", on="2017-06-30", issuer_cik="999", status="pass")]
    config = ScorecardConfig(floor={"G.pass": 1, "L1.coverage_tickers": 1.0}, golden=golden)
    logged = []
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=logged.append, scorecard=config)
    assert summary.scorecard_drops == ["G.pass: 1 -> 0"]               # coverage holds at 1.0
    assert summary.golden_failures == ["AET: issuer_cik 1122304 != 999"]
    assert "scorecard drop: G.pass: 1 -> 0" in logged


def test_a_limit_subset_is_never_compared_to_the_floor(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    config = ScorecardConfig(floor={"G.pass": 1})
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, limit=1, scorecard=config)
    assert summary.scorecard_drops == []
    assert json.loads((tmp_path / "scorecard.json").read_text())["drops"] == []
```

- [ ] **Step 2: Write the failing CLI tests**

In `tests/test_classify_universe_cli.py`, make these changes:

1. Below `from delist_detection import edgar as edgar_mod`, add:

```python
from delist_detection.scorecard import Window
from delist_detection.truth import TRUTH_COLUMNS
```

2. In `_FakeSummary.__init__`, after `self.review_flags = review_flags`, add:

```python
        self.scorecard_drops, self.golden_failures = [], []
```

3. Replace the head of `_run_main` and its `run` stub so that it isolates the default config path and can
   return a given summary:

```python
def _run_main(monkeypatch, review_flags, *argv, summary=None):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    monkeypatch.setattr(cli, "use_machine_wide_limit", lambda *a, **k: None)
    monkeypatch.setattr(cli, "DEFAULT_SCORECARD", "/nonexistent/scorecard.json")
```

   and

```python
    monkeypatch.setattr(cli, "run", lambda *a, **kw: seen.update(kw) or summary or _FakeSummary(review_flags))
```

4. In `_entry_with_inputs`, after the `DEFAULT_REVIEW_DECISIONS` line, add:

```python
    monkeypatch.setattr(cli, "DEFAULT_SCORECARD", str(tmp_path / "no-scorecard.json"))
```

5. Add `"--scorecard"` to the parametrize list of `test_a_missing_input_file_exits_2_naming_it`:

```python
@pytest.mark.parametrize("flag", ["--merger-terms", "--last-trade-closes", "--recoveries", "--review-decisions",
                                  "--scorecard"])
```

6. Append at the end of the file:

```python
@pytest.mark.parametrize("text, where", [
    ('{"floor": {"nope": 1}}', "floor entries"),
    ('{"golden": "golden.csv"}', "golden.csv:2"),
])
def test_a_bad_scorecard_config_or_truth_file_exits_2_on_one_line(monkeypatch, capsys, tmp_path, text, where):
    cfg = tmp_path / "scorecard.json"
    cfg.write_text(text)
    (tmp_path / "golden.csv").write_text(",".join(TRUTH_COLUMNS) + "\nX,golden,,2010-06-30" + "," * 14 + "\n")
    assert _entry_with_inputs(monkeypatch, tmp_path, "--scorecard", str(cfg)) == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err and where in err


def test_main_passes_the_scorecard_config_to_run(monkeypatch, tmp_path):
    cfg = tmp_path / "scorecard.json"
    cfg.write_text('{"window": {"start": "2006-01-02", "end": "2024-12-29"}}')
    assert _run_main(monkeypatch, {}, "--scorecard", str(cfg)) == 0
    assert _run_main.seen["scorecard"].window == Window("2006-01-02", "2024-12-29")


def test_no_scorecard_config_at_the_default_path_means_an_empty_one(monkeypatch):
    assert _run_main(monkeypatch, {}) == 0
    assert _run_main.seen["scorecard"].window is None and not _run_main.seen["scorecard"].floor


def test_scorecard_drops_and_golden_failures_warn_without_changing_the_exit_code(monkeypatch, capsys):
    summary = _FakeSummary({})
    summary.scorecard_drops = ["L1.coverage_tickers: 0.9 -> 0.8"]
    summary.golden_failures = ["ICPT: last_trade_date 2023-11-08 != 2023-11-07"]
    assert _run_main(monkeypatch, {}, summary=summary) == 0
    err = capsys.readouterr().err
    assert "1 scorecard number(s) got worse" in err and "L1.coverage_tickers: 0.9 -> 0.8" in err
    assert "1 golden case(s) now fail" in err and "ICPT" in err
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_classify_universe_cli.py -q`
Expected: failures. `run()` raises `TypeError: run() got an unexpected keyword argument 'scorecard'`, the CLI
reports `AttributeError` on `DEFAULT_SCORECARD`, and `--scorecard` is an unrecognized argument.

- [ ] **Step 4: Add `store.formatted`**

In `src/delist_detection/store.py`, insert directly above `def _write_all(`:

```python
def formatted(name: str, rows: Iterable[Mapping[str, object]]) -> list[dict[str, str]]:
    """`rows` as table `name` is written: every cell formatted, missing columns
    blank, sorted by key -- the rows `read_table` would read back. An unknown
    column raises ValueError."""
    return _formatted(name, rows)
```

- [ ] **Step 5: Wire stage 10e into `pipeline.py`**

1. Imports. After `from . import manifest as run_manifest`, add `from . import scorecard as run_scorecard`.
   Replace `from .store import DelistingKey, write_tables` with:

```python
from .lifecycle import Tables
from .store import DelistingKey, formatted, write_tables
```

2. `RunSummary`. After the `review_counts` field, add:

```python
    scorecard_drops: list[str] = field(default_factory=list)        # floored scorecard numbers that got worse
    golden_failures: list[str] = field(default_factory=list)        # golden `pass` cases the tables now fail
```

3. `run`. Change the signature's last line and the docstring's first line to:

```python
        sec_workers: int = 1, review_decisions: Sequence[Decision] = (),
        scorecard: run_scorecard.ScorecardConfig = run_scorecard.ScorecardConfig()) -> RunSummary:
    """Observations -> the eight tables under `out_dir` (spec §8), then
    scorecard.json (`scorecard.build` over those tables, `scorecard`'s window,
    floor and truth cases; floor drops are not checked under `limit`): `review_decisions`
```

   Pass it through in the `try:`:

```python
        summary = _run(index, clients, overrides, out_dir=out_dir, tol=tol, limit=limit, log=log,
                       sec_workers=sec_workers, review_decisions=review_decisions, scorecard=scorecard)
```

4. Add this function directly above `def _run(`:

```python
def _scorecard(ctx: _RunContext, tables: dict[str, list[dict]], config: run_scorecard.ScorecardConfig,
               limit: int | None) -> dict:
    """10e. The scorecard of the tables about to be written (read as
    store.read_table would read them back), with `drops`: the floored numbers
    that got worse. A --limit subset sees a fraction of the universe, so its
    numbers are never compared to the floor."""
    def rows(name: str) -> list[dict[str, str]]:
        return formatted(name, tables[name])
    card = run_scorecard.build(Tables(rows("securities"), rows("ticker_history"), rows("delistings"),
                                      rows("observation_map"), rows("review")), as_of=ctx.as_of, config=config)
    card["drops"] = run_scorecard.drops(card, config.floor) if limit is None else []
    for line in card["drops"]:
        ctx.log(f"scorecard drop: {line}")
    for line in card["golden_failures"]:
        ctx.log(f"golden case failing: {line}")
    return card
```

5. `_run`. Add the parameter:

```python
         review_decisions: Sequence[Decision] = (),
         scorecard: run_scorecard.ScorecardConfig = run_scorecard.ScorecardConfig()) -> RunSummary:
```

   Replace the step 11 block, from `# 11. write` through the closing `})` of `write_tables`, with:

```python
    tables = {
        "securities": [s.row() for s in securities.values()] + [a.security.row() for a in added.values()],
        "ticker_history": th_rows,
        "cusip_history": ch_rows,
        "delistings": delisting_rows,
        "payouts": _payout_rows(payouts, delistings),
        "review": triaged.review_rows,
        "review_summary": triaged.summary_rows,
        "observation_map": map_rows,
    }
    card = _scorecard(ctx, tables, scorecard, limit)                                                # 10e

    # 11. write -- every table formatted and written to its temp file first, so
    # a failure in any leaves every previous table; then renamed into place one
    # at a time (store.write_tables). scorecard.json and the manifest follow.
    counts = write_tables(out_dir, tables)
    run_scorecard.write(out_dir, card)
```

   Then end the `return RunSummary(...)` call with:

```python
                      dict(Counter(s.figi_source for s in securities.values())), dict(flags), dict(triaged.counts),
                      scorecard_drops=card["drops"], golden_failures=card["golden_failures"])
```

- [ ] **Step 6: Wire `--scorecard` into `scripts/classify_universe.py`**

1. In the module docstring, change the `Writes:` paragraph's end to:
   `observation_map.csv, then scorecard.json (data/scorecard.json: the training window, the floor and the truth
   files)`.
2. Imports. After the `review_triage` import, add:

```python
from delist_detection.scorecard import ScorecardConfig, ScorecardConfigError, load_config
from delist_detection.truth import TruthFileError
```

3. After `DEFAULT_REVIEW_DECISIONS = ...`, add `DEFAULT_SCORECARD = str(ROOT / "data" / "scorecard.json")`.
4. In `EXIT_CODES_EPILOG`, replace `--review-decisions file that is missing when given explicitly or that fails
   to load);` with:

```
     --review-decisions or --scorecard file that is missing when given explicitly or that
     fails to load, or a truth file the scorecard names that fails to load);
```

5. Change the tuple to
   `BAD_INPUT = (ObservationError, OverrideFileError, ReviewDecisionError, ScorecardConfigError, TruthFileError)`.
6. In `build_parser`, above `--extract-merger-terms-llm`, add:

```python
    p.add_argument("--scorecard", default=None,
                   help="scorecard config: training window, floor and truth files "
                        "(default data/scorecard.json; missing there means no window, no floor, no truth cases)")
```

7. Above `read_inputs`, add:

```python
def read_scorecard(path: str | None) -> ScorecardConfig:
    """The scorecard config: `path` when given (missing is an error), else
    data/scorecard.json when it exists, else no window, floor or truth cases."""
    if path is not None:
        return load_config(path)
    return load_config(DEFAULT_SCORECARD) if Path(DEFAULT_SCORECARD).exists() else ScorecardConfig()
```

   Change `read_inputs` to return `tuple[Overrides, list[Decision], ObservationIndex, ScorecardConfig]`. Its
   docstring lists "the review decisions, the observations and the scorecard config". It ends with:

```python
    return (overrides, review_decisions, ObservationIndex(load_observations(args.observations)),
            read_scorecard(args.scorecard))
```

8. In `main`, unpack four values (`overrides, review_decisions, index, scorecard = read_inputs(args)`), pass
   `scorecard=scorecard` to `run(...)` before the `**({"log": log} ...)` argument, and add these lines directly
   above the final `return 3 if error_count or degraded_count else 0`:

```python
    if summary.scorecard_drops:
        print(f"WARNING: {len(summary.scorecard_drops)} scorecard number(s) got worse than the floor in "
              f"data/scorecard.json: {'; '.join(summary.scorecard_drops)}", file=sys.stderr)
    if summary.golden_failures:
        print(f"WARNING: {len(summary.golden_failures)} golden case(s) now fail: "
              f"{'; '.join(summary.golden_failures)}", file=sys.stderr)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_classify_universe_cli.py -q`
Expected: all pass. That is the existing tests plus 3 new pipeline tests and 6 new CLI tests (5 new test
cases, plus one more case in the missing-file parametrize).

- [ ] **Step 8: Run the full suite**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: `1517 passed`. That is 1,428 existing tests, plus 28, 27, 14, 5 and 6 from Tasks 1 to 5, plus 9 from
this task.

- [ ] **Step 9: Commit**

```bash
git add src/delist_detection/store.py src/delist_detection/pipeline.py scripts/classify_universe.py \
        tests/test_pipeline.py tests/test_classify_universe_cli.py
git commit -m "Every run writes output/scorecard.json; --scorecard config (reset-1)"
```

---

### Task 7: Golden set, config and floor

**Files:**
- Create: `data/golden_lifecycles.csv`
- Create: `data/scorecard.json`
- Create: `tests/test_golden_lifecycles.py`
- Create: `tests/test_scorecard_floor.py`
- Create (generated): `output/scorecard.json`

**Interfaces:**
- Consumes: Tasks 2, 3 and 5.
- Produces:
  - The golden case ids that later plans flip from `known_wrong` to `pass`.
  - The floor every later plan must hold.

The golden set is the spec's list: AABA (the `YHOO` case), PDLI, IMCL, ICPT, XTO, ANAT, CLWR, CTCM, HMA, LEAP,
MON, TIN, BK, CB, JCI, PLD, MRK, FOX/FOXA, COHR, CZR, APTV, ITT, J, and the 20 sampled rows. A case pins only
what was checked:

- A case the spec calls fixed is pinned to today's output. These are the spec's Part 2 "now" values.
- A case the spec calls wrong is pinned to the facts the spec checked at its cited source, with
  `known_wrong` and the roadmap plan that fixes it.
- Later history the spec marks "from general knowledge and was not checked" is left out. Where the spec says
  only that a security kept trading past a date, the case uses `ends_after`.

Five tickers changed hands, so each has two cases split by date: CB, JCI, PLD, COHR and CZR. `MRK-2008` and
`FOXA-2015`/`FOX-2015` are new findings, described in the roadmap.

- [ ] **Step 1: Confirm the CIKs the new golden rows rest on**

```bash
export DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock   # agent sandbox; omit in a terminal
~/miniconda3/envs/rdagent4qlib/bin/python - <<'EOF'
from pathlib import Path
from delist_detection.edgar import EdgarClient
from delist_detection.sec_limiter import use_machine_wide_limit
use_machine_wide_limit()
e = EdgarClient(cache_dir=Path("cache/edgar"))
for cik in (64978, 310158, 1308161, 1754301, 1525221, 73887):
    s = e.submissions(cik)
    print(cik, s.get("name"), [f.get("name") for f in s.get("formerNames", [])][:4])
EOF
```

Expected:
- 64978 is old Merck & Co.
- 310158 is today's Merck, formerly Schering-Plough.
- 1308161 is Twenty-First Century Fox, formerly News Corp.
- 1754301 is Fox Corp.
- 1525221 is Era Group.
- 73887 is Bristow Group.

If any differs, correct that row's `issuer_cik` in Step 2, keep its `status`, and say so in the commit message.

- [ ] **Step 2: Write `data/golden_lifecycles.csv`**

```csv
case,group,ticker,on,issuer_cik,tickers,terminal,ends_after,exit_kind,last_trade_date,dlret,dlret_tol,successor_ticker,status,fixed_by,source,library_says,note
IMCL,golden,IMCL,2008-06-30,765258,,,,merger,,,,,pass,,spec Part 2 (IMCL),,ImClone as its own security; its value waits on a last close
ICPT,golden,ICPT,2020-06-30,1270073,,,,merger,2023-11-07,0.0,,,pass,,spec Part 2 (ICPT),,a flat vendor tail placed it 961 sessions late
XTO,golden,XTO,2009-06-30,868809,,,,merger,2010-06-25,-0.015509,,,pass,,spec Part 2 (XTO),,a flat vendor tail placed it 955 sessions late
ANAT,golden,ANAT,2015-06-30,904163,ANAT,,,merger,2022-05-24,-0.000105,,ANAT,pass,,spec Part 2 (ANAT),,2020 holding-company continuation then the 2022 merger
CLWR,golden,CLWR,2012-06-29,1442505,,,,merger,2013-07-09,0.002004,,,pass,,spec Part 2 (CLWR),,
CTCM,golden,CTCM,2012-06-29,1354513,,,,merger,2016-05-18,0.078049,,,pass,,spec Part 2 (CTCM),,
HMA,golden,HMA,2010-06-30,792985,,,,merger,2014-01-24,0.001036,,,pass,,spec Part 2 (HMA),,
LEAP,golden,LEAP,2010-06-30,1065049,,,,merger,2014-03-13,-0.143836,,,pass,,spec Part 2 (LEAP),,
MON,golden,MON,2012-06-29,1110783,,,,merger,2018-06-06,0.000391,,,pass,,spec Part 2 (MON),,
TIN,golden,TIN,2010-06-30,731939,,,,merger,2012-02-10,0.003764,,,pass,,spec Part 2 (TIN),,
BK,golden,BK,2010-06-30,1390777,BK,active,,,,,,,pass,,spec Part 2 (BK),,reverse merger: one security
CB-2010,golden,CB,2010-06-30,20171,,,,merger,2016-01-15,0.019589,,,pass,,spec Part 2 (CB),,Chubb Corp acquired by ACE; ACE took the CB ticker (a takeover not a successor)
CB-2020,golden,CB,2020-06-30,896159,ACE;CB,active,,,,,,,pass,,spec Part 2 (CB),,ACE renamed Chubb Ltd
JCI-2010,golden,JCI,2010-06-30,53669,,,,merger,2016-09-06,,,,pass,,spec Part 2 (JCI),,value is assumed par after a failed payout gate (decision 4); not pinned
JCI-2020,golden,JCI,2020-06-30,833444,TYC;JCI,active,,,,,,,pass,,spec Part 2 (JCI),,Tyco renamed Johnson Controls International
PLD-2010,golden,PLD,2010-06-30,899881,,,,merger,2011-06-02,-0.000076,,,pass,,spec Part 2 (PLD),,old ProLogis merged into AMB
PLD-2015,golden,PLD,2015-06-30,1045609,AMB;PLD,active,,,,,,,pass,,spec Part 2 (PLD),,AMB renamed Prologis
MRK-2020,golden,MRK,2020-06-30,310158,MRK,active,,,,,,,pass,,spec golden list,,
COHR-2015,golden,COHR,2015-06-30,21510,,,,merger,2022-06-30,0.000543,,,pass,,spec golden list,,Coherent Inc acquired by II-VI; II-VI took the COHR ticker
COHR-2023,golden,COHR,2023-06-30,820318,IIVI;COHR,active,,,,,,,pass,,spec golden list,,
CZR-2015,golden,CZR,2015-06-30,858339,,,,merger,,,,,pass,,spec golden list,,Caesars Entertainment Corp acquired by Eldorado; Eldorado took CZR
CZR-2022,golden,CZR,2022-06-30,1590895,,active,,,,,,,pass,,spec golden list,,
APTV,golden,APTV,2020-06-30,1521332,DLPH;APTV,active,,,,,,APTV,pass,,library PR #6,,2024 holding-company continuation
ITT,golden,ITT,2012-06-29,216228,,active,,,,,,ITT,pass,,library PR #6,,2016 holding-company continuation
J,golden,J,2020-06-30,52988,JEC;J,active,,,,,,J,pass,,library PR #6,,2022 holding-company continuation
FOXA-2020,golden,FOXA,2020-06-30,1754301,,active,,,,,,,pass,,spec golden list,,Fox Corp class A
FOX-2020,golden,FOX,2020-06-30,1754301,,active,,,,,,,pass,,spec golden list,,Fox Corp class B
MRK-2008,golden,MRK,2008-06-30,64978,,,,,,,,,known_wrong,reset-3,,,one composite FIGI across the 2009 Schering-Plough merger; old Merck & Co was the issuer in 2008
FOXA-2015,golden,FOXA,2015-06-30,1308161,,,,merger,,,,,known_wrong,reset-4b,,,Twenty-First Century Fox class A; acquired by Disney 2019; output maps it to Fox Corp's FIGI
FOX-2015,golden,FOX,2015-06-30,1308161,,,,merger,,,,,known_wrong,reset-4b,,,Twenty-First Century Fox class B; as FOXA-2015
YHOO,golden,YHOO,2010-06-30,1011006,YHOO;AABA,,,liquidation,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/1011006/000119312519262790/d794671dex991.htm,,renamed Altaba (AABA) 2017-06-16; dissolved 2019-10-04 after a stockholder-approved liquidation
PDLI,golden,PDLI,2015-06-30,882104,,,,liquidation,,,,,known_wrong,reset-4d,,,voluntary delisting to wind down; paid distributions
EXBD,golden,EXBD,2010-06-30,1066104,EXBD;CEB,,2012-08-31,,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/1066104/000119312512322777/d387593dex991.htm,,ticker changed to CEB 2012-08-13; same company and listing
XON,golden,XON,2015-06-30,1356090,XON;PGEN,,2020-02-01,,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/1356090/000119312520023400/d876809dex991.htm,,renamed Precigen (PGEN) 2020-02-01
WTW,golden,WTW,2010-06-30,105319,WTW;WW,,2013-12-31,,,,,,known_wrong,reset-4a,https://www.streetinsider.com/Corporate+News/Weight+Watchers+(WTW)+Announces+NASDAQ+Stock+Ticker+Symbol+Change+to+WW/15377344.html,,left the index and kept trading as WTW; later WW on Nasdaq
LIZ,golden,LIZ,2010-06-30,352363,LIZ;FNP,,2012-05-16,,,,,,known_wrong,reset-4a,https://streetinsider.com/Corporate+News/Liz+Claiborne+(LIZ)+Completes+Name+and+Ticker+Change;+Is+Now+Fifth+&+Pacific+Companies+(FNP)/7439631.html,,renamed Fifth & Pacific (FNP) 2012-05-15
ACXM,golden,ACXM,2015-06-30,733269,ACXM;RAMP,,2018-10-02,,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/0000733269/000119312518289748/d612393d8k12b.htm,,holding-company reorganization; LiveRamp (RAMP) from 2018-10-02
DF,golden,DF,2010-06-30,931336,DF,,2013-08-27,,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/0000931336/000119312513335750/d583800dex991.htm,,1-for-2 reverse split 2013-08-26: same ticker; new CUSIP
MNI,golden,MNI,2010-06-30,1056087,MNI,,2016-06-08,,,,,,known_wrong,reset-4a,https://www.prnewswire.com/news-releases/mcclatchy-announces-completion-of-reverse-stock-split-300280463.html,,1-for-10 reverse split 2016-06-07: same ticker; new CUSIP
ESV,golden,ESV,2009-06-30,314808,ESV,,2009-12-31,,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/0000314808/000095012309072898/d70526e8vk12b.htm,,redomiciled to the UK 2009-12-23; one share became one ADS; same ticker
DRQ,golden,DRQ,2015-06-30,1042893,DRQ;INVX,,2024-09-07,,,,,,known_wrong,reset-4a,https://www.nasdaq.com/press-release/innovex-and-dril-quip-complete-merger-creating-unique-energy-industrial-platform-0,,Dril-Quip survives the Innovex merger; renamed; ticker INVX
MDC,golden,MDC,2020-06-30,773141,,,,merger,,,,,known_wrong,reset-4a,https://www.sekisuihouse.co.jp/english/company/release/library/2024/20240419/20240419e.pdf,,acquired by Sekisui House 2024-04-19 for $63.00 cash
SGP,golden,SGP,2008-06-30,310158,,,,merger,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/0000310158/000119312509223917/dex991.htm,,merged with Merck 2009-11-03 for 0.5767 MRK + $10.50
ACF,golden,ACF,2008-06-30,804269,,,,merger,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/0001467858/000119312510263635/d424b1.htm,,acquired by General Motors 2010-10-01 for cash
BNI,golden,BNI,2008-06-30,934612,,,,merger,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/0000934612/000093461211000005/d10k.htm,,acquired by Berkshire Hathaway 2010-02-12 for cash and stock
UFS,golden,UFS,2015-06-30,1381531,,,,merger,,,,,known_wrong,reset-4a,https://www.pulpandpapercanada.com/paper-excellence-completes-acquisition-of-domtar/,,acquired by Paper Excellence 2021-11-30 for $55.50 cash
CPN,golden,CPN,2015-06-30,916457,,,,merger,,,,,known_wrong,reset-4a,https://www.sec.gov/Archives/edgar/data/0000916457/000091645718000100/exhibit991-02212018.htm,,taken private 2018-03-08 for $15.25 cash
CPGX,golden,CPGX,2015-12-31,1629995,,,,merger,,,,,known_wrong,reset-4a,https://www.worldpipelines.com/equipment-and-safety/04072016/transcanada-completes-columbia-pipeline-group-acquisition-276/,,acquired by TransCanada 2016-07-01 for $25.50 cash
STN,golden,STN,2008-06-30,898660,,,,merger,,,,,known_wrong,reset-4a,https://lasvegassun.com/news/2009/jul/28/station-casinos/,,bought out 2007-11-07; the 2008 sighting is a stale constituent
LVNTA,golden,LVNTA,2015-06-30,1355096,,,,,,,,GLIBA,known_wrong,reset-4a,https://investors.qvcgrp.com/news-media/press-releases/detail/14/liberty-interactive-and-gci-liberty-announce-completion-of,,split-off: each share redeemed 1:1 for GCI Liberty (GLIBA) 2018-03-09
ERA,golden,ERA,2013-06-28,1525221,,,,,,,,,known_wrong,reset-4b,https://www.bristowgroup.com/news-media/press-releases/detail/324/era-group-inc-begins-trading-on-nyse-as-an-independent,,Era Group sighting attached to the old Bristow Group (CIK 73887)
```

- [ ] **Step 3: Write `tests/test_golden_lifecycles.py`**

```python
"""The golden set (data/golden_lifecycles.csv) against the committed output
tables. A `pass` case must hold. A `known_wrong` case must still fail (strict
xfail) until the plan named in its `fixed_by` lands; that plan flips it to
`pass` and raises the scorecard floor (scripts/scorecard.py --raise-floor)."""
from pathlib import Path

import pytest

from delist_detection.lifecycle import LifecycleView, Tables
from delist_detection.truth import KNOWN_WRONG, judge, load_truth

ROOT = Path(__file__).resolve().parents[1]
CASES = load_truth(ROOT / "data" / "golden_lifecycles.csv")


@pytest.fixture(scope="module")
def view():
    return LifecycleView(Tables.read(ROOT / "output"))


@pytest.mark.parametrize("case", CASES, ids=[c.case for c in CASES])
def test_golden_lifecycle(case, view, request):
    if case.status == KNOWN_WRONG:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"known wrong until {case.fixed_by}"))
    j = judge(case, view)
    assert j.ok, "; ".join(j.mismatches)
```

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_golden_lifecycles.py -q -o addopts=""`
Expected: `27 passed, 24 xfailed`. If a `pass` case fails, the output disagrees with the spec's "now" value.
Read the mismatch and check the row against `output/` before changing anything. If a `known_wrong` case passes
(strict XPASS), the row checks too little. Add the field the spec's evidence supports.

- [ ] **Step 4: Write `data/scorecard.json` and raise the floor from the committed output**

Create `data/scorecard.json`:

```json
{
  "window": {"start": "2006-01-02", "end": "2024-12-29"},
  "golden": "golden_lifecycles.csv",
  "audit": "accuracy_audit.csv",
  "floor": {}
}
```

Run: `~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --raise-floor --write`
Expected: the last lines read `raised the floor in .../data/scorecard.json` and `wrote .../output/scorecard.json`.
`data/scorecard.json` now reads:

```json
{
  "window": {
    "start": "2006-01-02",
    "end": "2024-12-29"
  },
  "golden": "golden_lifecycles.csv",
  "audit": "accuracy_audit.csv",
  "floor": {
    "G.pass": 27,
    "L1.closed_no_event": 46,
    "L1.coverage_securities": 0.887783,
    "L1.coverage_tickers": 0.887787,
    "L1.ended_incomplete": 51,
    "L1.left_view": 119,
    "L1.no_interval": 32,
    "L1.no_mapped_sighting": 0,
    "L2.high_share": 0.785279,
    "L2.low": 127,
    "R1.1.mapped_share": 0.985092,
    "R1.2.cusip_share": 0.932127,
    "R1.2.figi_without_cik": 14,
    "R1.2.placeholder": 100,
    "R1.2.ticker_only": 50,
    "R1.3.transfer_no_successor": 126,
    "R1.4.review_rows": 728,
    "R2.1.missing_last_trade_date": 42,
    "R2.1.missing_last_trade_date_in_window": 41,
    "R2.2.continued_filings_rule": 139,
    "R2.2.unknown_reason": 9,
    "R2.3.blank_dlret_in_window": 54,
    "R2.3.blank_no_value_in_window": 22,
    "R2.4.assumed_par": 59,
    "R2.5.distress_blank_dlret": 1,
    "R2.5.distress_no_last_trade_date": 1,
    "R2.6.distress_flagged": 39
  }
}
```

- [ ] **Step 5: Write `tests/test_scorecard_floor.py`**

```python
"""The committed output tables against the floor in data/scorecard.json: no
floored number may get worse ("Nothing later may lower a scorecard number").

If this fails after a run of classify_universe.py into output/: a --limit or
otherwise partial run there drops every number (restore it with
`git checkout output/`). A real drop is a regression to fix. Lower a floor
entry only on purpose (a changed universe, a retired metric), by hand, and say
why in the commit."""
import json
from datetime import date
from pathlib import Path

from delist_detection.lifecycle import Tables
from delist_detection.scorecard import build, drops, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_the_committed_tables_keep_every_floored_number_and_every_golden_pass_case():
    config = load_config(ROOT / "data" / "scorecard.json")
    as_of = date.fromisoformat(json.loads((ROOT / "output" / "run_manifest.json").read_text())["as_of"])
    card = build(Tables.read(ROOT / "output"), as_of=as_of, config=config)
    assert drops(card, config.floor) == []
    assert card["golden_failures"] == []
```

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_scorecard_floor.py -q -o addopts=""`
Expected: `1 passed`.

Check that the test fails closed. Change `"L1.coverage_tickers"` in `data/scorecard.json` to `0.9` and run the
test again. Expected: it fails with `L1.coverage_tickers: 0.9 -> 0.887787`. Then set the value back to
`0.887787`.

- [ ] **Step 6: Run the full suite**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: `1545 passed, 24 xfailed`.

The classifier-level golden case `AABA_2019-11-06` in `data/golden_events.csv` expects bucket `unknown`. That
is today's classifier answer, not the truth. reset-4a will change it when it fixes `YHOO`. Leave it unchanged
here.

- [ ] **Step 7: Commit**

```bash
git add data/golden_lifecycles.csv data/scorecard.json output/scorecard.json \
        tests/test_golden_lifecycles.py tests/test_scorecard_floor.py
git commit -m "Lifecycle golden set (51 cases) and the scorecard floor (reset-1)"
```

---

### Task 8: Documentation

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `CONTEXT.md`, `docs/data-flow.md`

- [ ] **Step 1: `CLAUDE.md`**

1. Commands block. Change the `pytest` line to
   `pytest   # full suite (1545 tests + 24 known-wrong golden xfails, offline, no network)`. Add after the
   `verify_altair.py` line:

```bash
python scripts/scorecard.py              # offline: recompute output/'s scorecard vs data/scorecard.json; --check (exit 1 on a drop or a failing golden case), --write, --raise-floor, --lifecycles PATH
python scripts/draw_audit_sample.py --out data/accuracy_audit.csv   # offline: draw the decision-17 audit worksheet once (census + 100 random, seed 7)
```

   Change the "(append --limit N ...)" note to: `(append --limit N --output-dir /tmp/sub to classify_universe
   for a fast cached/offline subset; never write a subset into output/, the committed-output tests read it)`.
   In both `classify_universe.py` lines, append `+ scorecard.json` after the eight table names.

2. Architecture. Add a section after the handling layer's list:

```markdown
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
- `scorecard.py` — `build` (the spec's gap table as one flat dict: L1/L2, R1.x,
  R2.x, G.x, A.x), `METRICS` (each floored number's good direction), `drops`,
  `raise_floor`, `load_config` (`data/scorecard.json`: the caller's window, the
  floor, the two truth files), `write` (`output/scorecard.json`).
- `audit.py` — decision 17's sample: `census` (each ending in its first group of
  distress, continuation, left_view, blank_no_value, assumed_par), `random_sample`
  (seeded, avoiding census chains), `worksheet_rows`.
```

3. Non-obvious invariants. Add:

```markdown
- **The scorecard only moves one way.** Every run builds `output/scorecard.json`
  (`pipeline._scorecard`, stage 10e) from the rows it is about to write and
  writes it after the eight tables, before the manifest. `data/scorecard.json`
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
```

- [ ] **Step 2: `README.md`**

In "The eight output tables", after the paragraph that introduces them, add:

```markdown
Next to the tables, every run writes `run_manifest.json` (what the run rested
on) and `scorecard.json`: lifecycle coverage and quality per input ticker and
per security, the gap-table lines (identity, last trade dates, values,
distress), the golden set's result and the accuracy audit's error bound. It is
compared to the floor in `data/scorecard.json`; `scripts/scorecard.py`
recomputes it offline from the committed tables.
```

- [ ] **Step 3: `CONTEXT.md`**

Add to "Language", after **Review decision**:

```markdown
**Lifecycle**:
What the output tables say happened to a security from its first ticker interval to today: it is still trading (`active`), it ended with a known reason, a last trade date and a return (`ended`), or it stops short of that (`ended_incomplete`, `left_view`, `closed_no_event`, `no_interval`). An ending that names a successor continues the lifecycle there. An input ticker's lifecycle is the one of the security its earliest mapped observation resolved to.
_Avoid_: history, chain

**Covered**:
A lifecycle that reaches `active` or `ended` with nothing missing on the way. Coverage, the share of input tickers whose lifecycle is covered, is the reset's headline number.

**Truth case**:
One security's outcome checked by hand at a cited source, naming the security by a ticker and a date it traded and listing only what was checked. The golden set and the accuracy audit are both made of truth cases.
_Avoid_: test case, expectation

**Floor**:
The best value each scorecard number has reached (`data/scorecard.json`). No later change may make a floored number worse.
```

- [ ] **Step 4: `docs/data-flow.md`**

After the paragraph that starts "The manifest is not part of the byte-identical-output guarantee", add:

```markdown
`scorecard.json` is built at stage 10e from the same rows the tables are
written from (`store.formatted`), so it equals what `scripts/scorecard.py`
recomputes from the written CSVs. It is written after the tables and before the
manifest, carries `drops` (floored numbers that got worse; never computed under
`--limit`) and `golden_failures`, and is compared to `data/scorecard.json`'s
floor. It is deterministic for the same tables, config and run date.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md CONTEXT.md docs/data-flow.md
git commit -m "docs: scorecard, golden lifecycles, audit (reset-1)"
```

---

### Task 9: Accuracy audit (network, checked by hand)

**Files:**
- Create: `data/accuracy_audit.csv`
- Modify: `data/scorecard.json` (the floor)
- Modify: `docs/superpowers/plans/2026-10-02-delist-library-reset.md` (the Baseline section)

This task fills 421 truth rows from sources. It is labour, not code. It can run in parallel with reset-2,
because it only adds data and raises the floor. It needs `EDGAR_USER_AGENT`. Only one SEC client may run at a
time across the agent sandbox and a terminal (CLAUDE.md, "SEC fair access").

- [ ] **Step 1: Draw the worksheet**

Run: `~/miniconda3/envs/rdagent4qlib/bin/python scripts/draw_audit_sample.py --out data/accuracy_audit.csv`
Expected:

```
census:assumed_par           59
census:blank_no_value        21
census:continuation          70
census:distress              54
census:left_view             117
random                       100
wrote .../data/accuracy_audit.csv: 421 rows
```

Run `~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py | grep '^A\.'`. Expected: one line,
`A.pending 421`. The `A.random.*` and `A.census.*` lines appear once rows are filled, because pending rows are
not judged. Commit:

```bash
git add data/accuracy_audit.csv
git commit -m "Decision-17 audit worksheet: 321 census + 100 random rows, seed 7 (reset-1)"
```

- [ ] **Step 2: Fill the rows in batches**

Work one group at a time, in batches of about 25 rows. Each batch is one subagent, dispatched with
`model: sonnet`. At most two agents read SEC at once, and both go through the throttled client below. Give each
agent its rows (`case`, `ticker`, `on`, `library_says`) and these rules:

- Fill only what you verified at a source you opened. Put every URL in `source`, space-separated. A search
  snippet is not a source. Never copy a value from `library_says`: it is what the library said, and the audit
  checks it.
- `issuer_cik`: the SEC registrant whose security traded as `ticker` on `on`.
- `terminal`: `active` only if the security still trades today. Read EDGAR's current `tickers` and `exchanges`
  for that registrant. If it does not still trade, leave this blank.
- `ends_after`: if the security kept trading past the library's ending, the latest date you confirmed it
  traded.
- `exit_kind`, using the contract's vocabulary:
  - `merger`: holders received cash or another company's stock.
  - `exchange`: an exchange for another issue.
  - `liquidation`: a plan of dissolution or liquidating distributions.
  - `dropped`: removed by the exchange or moved to OTC, including bankruptcy.
  - `expiration`.
  - A one-for-one continuation (a rename, a holding-company reorganization, a redomicile, a reverse split)
    has no `exit_kind`. Fill `tickers` and `successor_ticker` (or `ends_after`) instead.
- `last_trade_date`: only from an exchange-print source, such as the Form 25 or exchange notice, an 8-K item
  3.01 "suspended before the open on D" (the last trade is the trading day before D), or the company's
  completion release. Otherwise leave it blank.
- `dlret`: only when you hold both the deal terms and an independent last close. Usually leave it blank.
- `note`: one line on what happened, with the date.

The agents read EDGAR through the library's throttled, cached client:

```bash
export DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock   # agent sandbox; omit in a terminal
~/miniconda3/envs/rdagent4qlib/bin/python - <<'EOF'
from pathlib import Path
from delist_detection.edgar import EdgarClient
from delist_detection.sec_limiter import use_machine_wide_limit
use_machine_wide_limit()
e = EdgarClient(cache_dir=Path("cache/edgar"))
CIK = 1011006                                          # the row's issuer
s = e.submissions(CIK)
print(s.get("name"), s.get("tickers"), s.get("exchanges"), [f.get("name") for f in s.get("formerNames", [])])
for f in e.recent_filings(CIK)[:60]:
    print(f.filing_date, f.form, f.items, f.accession, f.primary_doc)
# print(e.fetch_filing_text(CIK, "<accession>", "<primary_doc>")[:4000])
EOF
```

After each batch, run `~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py > /dev/null`. It must
exit 0. Exit 2 names the bad row by file and line. Then commit that batch:

```bash
git add data/accuracy_audit.csv
git commit -m "Accuracy audit: <group> rows <first case>..<last case> (reset-1)"
```

- [ ] **Step 3: Read the result and raise the floor**

When `A.pending` reads 0, run:
`~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py | grep '^A\.'`

Expected: `A.random.n 100`, `A.random.errors` k, `A.random.upper95` (0.0295 when k = 0, 0.0466 when k = 1), and
`A.census.<group>.n` and `.errors` for the five groups. The values are whatever the audit finds; do not tune
them. The spec's 20-row sample found no real transfer among the left-view rows, so expect
`A.census.left_view.errors` near its `n`.

Then run `scripts/scorecard.py --raise-floor --write`, then
`~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`. Expected: `1545 passed, 24 xfailed`.

- [ ] **Step 4: Record the baseline in the roadmap**

In `docs/superpowers/plans/2026-10-02-delist-library-reset.md`, add one row per `A.*` line to the Baseline
table. Under the table, add one sentence per census group naming the reset plan that owns its wrong rows:
left_view goes to reset-4a, distress to reset-4d, blank_no_value and assumed_par to reset-4c, and continuation
to reset-4a or reset-4b. These wrong rows are the test set those plans start from.

```bash
git add data/scorecard.json output/scorecard.json docs/superpowers/plans/2026-10-02-delist-library-reset.md
git commit -m "Accuracy audit baseline and floor (reset-1)"
```

---

## Self-review

- **Spec coverage, step 1 "Measure first".** "Make the scorecard a library output … computed on every rebuild" is
  Tasks 3 and 6. "coverage and quality per lifecycle" is Task 1, plus `--lifecycles` in Task 5. "plus the R1/R2
  lines" is Task 3, for every line computable from the tables. R1.5 (handoffs) has no number of its own, so the
  golden handoff cases APTV, ITT, J, CB, JCI, PLD, COHR and CZR cover it. R1.7 is qlib_practice's measurement.
  R1.6 is the audit (Tasks 4 and 9). "Seed the golden set" is Task 7, every named case plus the 20 sampled rows.
  "Prove accuracy as decision 17 says" is Tasks 4 and 9. Decision 17's hard gates are in reset-2 and
  qlib_practice, as stated above. "Nothing later may lower a scorecard number" is the floor (Tasks 3 and 7) and
  the strict xfail.
- **Placeholders.** Every code and data step carries its full content. Every number in an "Expected" line was
  measured on the committed output or produced by the plan's own code on 2026-10-02.
- **Type consistency.** `Tables`, `LifecycleView`, `TruthCase`, `ScorecardConfig`, `Window` and the
  `card["metrics"]`/`["golden_failures"]`/`["drops"]` keys are named the same in every task.
  `run(..., scorecard=)` matches the CLI's keyword.

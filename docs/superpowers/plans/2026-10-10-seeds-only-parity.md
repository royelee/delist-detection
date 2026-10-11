# Seeds-Only Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A run given one seed per introduction reaches the same securities and endings as a run
given every sighting, because what happens after the seed is read from SEC fails-to-deliver data
and filings and no longer from later sightings.

**Architecture:** Two changes in era building carry most of it. An era's last-seen date follows
the era's own CUSIP in the fails data until those rows stop (fix S1). A line that begins at a
CUSIP change under the same ticker becomes a line of the run even when no observation falls in it
(fix S2). A parity script compares a seeds-only run with a full run and holds a floor, so every
fix is measured the same way (S0). Three smaller causes and one seed-builder gap follow (S3, S4).

**Tech Stack:** Python ≥3.10, standard library, pytest (offline).

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md`: "Every seed resolves to one
security" (output: "its dated ticker history to its real end or to today, not to its last sighting
in the index") and "What crosses the boundary" (In: `seeds.csv`). Evidence for this plan:
`docs/superpowers/plans/research/2026-10-10-seeds-only-trace/findings.md`.

**Where it applies:** branch `seeds-only-parity`, forked on 2026-10-10 from `faster-runs` at
`6bbeb7e`. That commit is `worktree-reset-1-scorecard` at `0a7a345` with the faster-runs work
merged in (a parsed store for the fails files, `--llm-workers`, `CLAUDE.md` as an index whose
long text now lives in `docs/architecture.md`, `docs/invariants.md` and `docs/commands.md`). File
paths, line numbers and every measured number in this plan are as of commit `6e43e09`, so find
each function by name. Tasks 1 and 2 were applied again to a copy of `6bbeb7e`: every "replace
this with that" step still matches, with one more test-helper change (Task 2, Step 4), and the
whole suite gives 3894 passed, 44 xfailed. Task 3 measures the parity numbers again at the commit
it runs on.

**Decisions taken for this execution.** The owner asked on 2026-10-10 for this plan to be
executed. Under the owner's standing instruction for these plans, each decision in "Decisions for
the owner" takes the recommendation in its row when the plan reaches it, and what was decided is
recorded in the "Checkpoints" section with its reason.

## Global Constraints

- Design rule (owner, 2026-10-10): what happens to a security after it enters the universe is
  decided from filings and SEC data, not read off later sightings.
- Tests are offline. Python: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`; pytest
  with `-o addopts=""`.
- The golden events replay (`tests/test_golden_events.py`) stays green. A case that changes stops
  the task.
- The full run may change only where a task says so. Judge it with the project's own gate:
  `scripts/scorecard.py --check --base <commit before the task>`. A regression the truth sets do
  not settle goes through the diagnosis loop before the task is called done.
- Parity runs are two runs on one commit with the same flags. The seeds-only run starts from a
  copy of the cache the full run left, so the same filing gets the same LLM answer in both.
- Parity runs write to a scratch folder, never to `output/`.
- A line the library derives itself never appears in `observation_map.csv` or
  `contract/seeds.csv`. Those tables hold the caller's rows only.
- Network runs from an agent sandbox allow `data.sec.gov`, `www.sec.gov`, `efts.sec.gov`,
  `api.openfigi.com`, `api.nasdaq.com`, `www.nasdaqtrader.com` and the LLM host in `.env`, and set
  `DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock`.

## Review Focus

1. A ticker with a later era of its own (KORS before and after the rename to Capri): following
   the CUSIP must stop before the later era begins. Test in Task 2, Step 1 (fourth test).
2. An era with no CUSIP of its own, whose rows are matched by name only: it must not be followed
   for years along a name. Test in Task 2, Step 1 (third test).
3. A security whose fails rows have a hole longer than 400 days: following stops at the hole and
   the answer is today's. Test in Task 2, Step 1 (second test).
4. Another holder of the ticker right after the security ends (WEN 2008, TCF 2019): S2 must not
   call the new line a continuation on timing alone. Named as a required test in S2.
5. A seed whose ticker has no fails rows near its date (APTV 2012): nothing to follow, today's
   behaviour, and the run says so. Named as a required test in S4.
6. A security whose own CUSIP keeps appearing under the same symbol for years after its Form 25
   (it went on trading over the counter): its lookup date now lands years after the filing, and
   the resolver's Form 25 search covers 90 days around the date. No unit test pins this. Task 3,
   Step 4 compares every era's issuer in the full run before and after S1 and reviews each change.
7. An input whose newest observation is old: the fails index must still reach the run date, or
   the follow is cut short. Test in Task 2, Step 5.

---

## What the trace found

Two runs at `6e43e09`, same flags and starting cache: full (35,955 rows) and seeds-only (2,952).
Seed rows land on the same `sec_id` in both for 2,921 of 2,946. The differences are all after
entry. Counts are cases explained, most of them reproduced by small reruns; the case lists and
code references are in `research/2026-10-10-seeds-only-trace/findings.md`.

| Cause | Code | Cases |
| --- | --- | --- |
| C1. An era's last-seen date stops 400 days after its last observation, and the issuer lookup is asked at that date (so are the name-in-force check and the second pass). With no issuer, or the wrong one, the delisting search has nothing or the wrong filings to read. | `identity/identity.py` `era_last_seen`, used by `_resolve_issuers` | about 35 |
| C2. A line that begins at a CUSIP change is dropped when no observation falls in it. | `identity/identity.py` `_split_era` (`if not obs: continue`) | about 65 |
| C3. The seed's ticker did not trade on the seed date (backfilled or stale). | not traced | APTV, ITT, SUNW, MEL |
| C4. Share class read from the era's latest observed name. | `identity/security_master.py` `group()` | CBS, CBG, WCRX |
| C5. Endings of added successors are created after the valuation stage. | `pipeline.py` `_successor_endings` after `_merger_values` | NRF, NLSN; any added successor |
| C6. A takeover inside a ticker whose name still agrees gets no seed. | `scripts/seeds_from_observations.py` | FOX, FOXA; WEN, TCF, CHTR have the shape |
| C7. Not the input: LLM answers differ between runs; the full run reads old resolver memo entries. | `cache/llm/`, `cache/ticker_resolution.json` | NMX, VSTO, NVRI, PXP; NWA |

## Measured before this plan was written

Row-by-row results are in `research/2026-10-10-seeds-only-trace/subsets/`.

**S1 alone, 44 tickers, 53 seed rows.** Issuers matching the full run: 20, then 46. Endings
matching: 13, then 34. 22 fixed, 1 broken (ANN, which S2 has to fix). The whole test suite passes
with one expected value changed.

**S1 with a rough S2, 60 tickers, 73 seed rows.** Endings matching the full run: 30 on the
original code, 29 with S1 alone, 53 with both. 26 fixed, 2 broken (ANN, EVHC). The rough S2
showed what the real one must do; the points are listed under S2.

**Limits of these two tests.**

- Both subsets were drawn from the failing cases, so they show what the fixes repair and say
  little about what they might disturb.
- In both, the newest seed was 2023-06-30, and the fails index is opened only to the newest
  observation plus 400 days (`identity._refine`, `hi = min(as_of, ...)`). The follow was
  therefore cut at 2024-08-03. DNB 2020 and VIACA, whose endings are in 2025, stayed unfixed in
  the test and may be artifacts of that cut. Task 2 removes the cap. The real seeds file reaches
  2026-06-30, so a full seeds-only run is not affected.

**How much of the full run S1 touches (computed offline on the full input).** The last-seen
date changes for 638 of 2,659 eras: 13 by up to 90 days, 107 by 91 to 400 days, 234 by 401 days
to 3 years, 284 by more than 3 years. Each of those eras is asked for its issuer at a new date.
Only 3 of them have a delisting within 90 days of the old date and not of the new one (CNDT,
EXBD, PBYI, all exchange transfers resolved by today's ticker map or the name search), so few
answers that rested on a Form 25 near the old date are at stake. The other answers can still
move, and Task 3 compares every era's issuer before and after.

## Rulings this plan makes

1. **S1 before S2, measured after each.** They touch different functions and S1 is small.
2. **Only an era with CUSIPs of its own is followed.** An era matched by name keeps today's one
   step of 400 days. `_own_rows` already says why: "FOX CORP" agrees with "TWENTY FIRST CENTURY FOX".
3. **Following stops before the ticker's next era.** The first step stays as today (not bounded),
   so eras that share a CUSIP across a rename keep today's dates.
4. **The step stays 400 days**, the same as `ERA_GAP_DAYS`.
5. **A line the library follows on its own is named by its own fails description**, and its
   issuer is looked up under that name and its CUSIP, never under the predecessor's name.
6. **A line the library follows on its own is not the caller's.** It is `observed=false` and is
   in no echo table. This holds for either S2 design.
8. **The issuer is asked at two dates** (added after checkpoint 1): the capped date, where the observed name was in force, and the end of the era's own fails rows, where its Form 25 is. An answer whose name agrees beats one whose name does not; between two that agree and differ, the end of the line wins unless it is only today's ticker map. A name-mismatch answer stands only when the CUSIP evidence infers nothing. Task 4.
7. **The parity floor only goes down.** `data/seeds_parity.json`, written by
   `scripts/seeds_parity.py --write-floor`.

## Decisions for the owner

| # | Decision | Recommendation |
| --- | --- | --- |
| A | How the caller learns that a ticker passed to another security it still holds (C6, FOX 2019). No filing can say this: it is a fact about the caller's universe. | If the snapshots carry an identifier (CUSIP, ISIN, SEDOL), the seed builder cuts a seed when it changes. That is the clean answer. If they do not, the seed builder reads the previous run's `contract/security_history.csv` and cuts a seed at the first snapshot after the ticker's holder changed. That second route makes the seeds depend on an earlier run, so a first run needs two passes, and it needs the new holder's line to be in that table (S2). |
| B | Whether to rebuild `cache/ticker_resolution.json` from empty for the published output. | Yes, once, in its own commit. The full run reads answers older code computed: NWA's issuer exists only there. Task 3 measures in a scratch folder what moves, before anything is published. |
| C | Whether backfilled seeds (C3) are the library's job or the seed builder's. | Decide after S2's checkpoint, with the list of seeds still wrong. |
| D | When qlib_practice may send seeds only. | When the parity numbers `endings_lost`, `kind_changed`, `securities_lost`, `seeds_placed_differently` and `truth_cases_failing_only_in_seeds` are 0, apart from cases the truth set marks as LLM differences. |
| E (taken: not as first built; see checkpoint 1 and Task 4) | Whether S1 is accepted on its own. It changes the published full run: 638 of 2,659 eras are asked for their issuer at a new date. | Accept it if Task 3's comparison shows no issuer or ending moving away from the truth sets, and publish the full run's rebuilt output with it. |

## The fixes, in order

| ID | Fix | Must move | Status in this document |
| --- | --- | --- | --- |
| S0 | Parity script and floor | nothing; it measures | Task 1, step by step |
| S1 | Last-seen date follows the era's own CUSIP rows; the issuer is asked at the capped date and at that date (reworked after checkpoint 1) | C1 | Tasks 2 to 5, step by step |
| S2 | The line after a CUSIP change is a line of the run | C2 | Specified below; its step-by-step plan is written after Task 3's numbers |
| S3 | A seed at a takeover | C6 | Specified below; needs decision A |
| S4 | Smaller causes: C3, C4, C5, the three unexplained cases | the rest | Specified below |
| S5 | Acceptance: memo rebuild (decision B), full parity run, flip rule, roadmap entry | decision D | Specified below |

## File structure

| File | Responsibility |
| --- | --- |
| `scripts/seeds_parity.py` (new) | Compare a full run's and a seeds-only run's output folders: the parity numbers, the cases behind each, a floor |
| `tests/test_seeds_parity.py` (new) | The script's counts on two tiny runs; the floor; a bad folder |
| `data/seeds_parity.json` (new, Task 3) | The floor |
| `src/delist_detection/identity/identity.py` | `era_last_seen` (follow), `last_sightings` (new), `_resolve_issuers` (call site), `_refine` (fails window); in S2 design B, `_split_era` |
| `tests/test_security_master.py` | New `era_last_seen` tests and the fails-window test |
| `tests/test_resolver_renamed.py` | One expected date and one expected memo key change |

---

### Task 1: The parity script (S0)

**Files:**
- Create: `scripts/seeds_parity.py`
- Test: `tests/test_seeds_parity.py`

**Interfaces:**
- Produces: `parity(full: Path, seeds: Path) -> dict` with keys `numbers` (name to count), `cases`
  (name to list of row dicts) and `scores`; `drops(numbers, floor) -> list[str]`; `main(argv) -> int`
  (0, 1 on `--check` with a number above its floor, 2 on unreadable folders). Number names:
  `endings_lost`, `endings_gained`, `kind_changed`, `value_or_date_changed`, `securities_lost`,
  `securities_gained`, `seeds_placed_differently`, `truth_cases_failing_only_in_seeds`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_seeds_parity.py`:

```python
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seeds_parity.py"
SPEC = importlib.util.spec_from_file_location("seeds_parity", SCRIPT)
seeds_parity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seeds_parity)

END_COLS = "sec_id,last_trade_date,exit_kind,continuation,dlret,verdict"


def _run(folder: Path, endings: list[str], securities: list[str], seeds: list[str], failures: list[str]) -> Path:
    (folder / "contract").mkdir(parents=True)
    (folder / "contract" / "delistings.csv").write_text("\n".join([END_COLS, *endings]) + "\n")
    (folder / "contract" / "seeds.csv").write_text("\n".join(["ticker,as_of,sec_id", *seeds]) + "\n")
    (folder / "securities.csv").write_text("\n".join(["sec_id", *securities]) + "\n")
    (folder / "scorecard.json").write_text(json.dumps({
        "metrics": {"L1": {"coverage_tickers": 1.0, "coverage_securities": 1.0, "left_view": 0, "closed_no_event": 0}},
        "golden_failures": failures, "diagnosis_failures": []}))
    return folder


def _two_runs(tmp_path: Path) -> tuple[Path, Path]:
    full = _run(tmp_path / "full",
                ["A,2008-12-31,merger,,0.07,confirmed",          # lost in seeds: the security is there, no ending
                 "B,2016-01-04,exchange,true,,confirmed",        # a continuation in full, a merger in seeds
                 "C,2012-03-05,merger,,0.0100,confirmed",        # same kind, another dlret
                 "D,2013-05-30,merger,,-0.059263,confirmed",     # same kind, dlret differs in the sixth decimal only
                 "E,2019-07-31,merger,,0.02,confirmed"],         # its security is not in the seeds run at all
                ["A", "B", "C", "D", "E"], ["AAA,2008-01-16,A", "BBB,2014-06-30,B"], [])
    seeds = _run(tmp_path / "seeds",
                 ["B,2016-01-04,merger,,0.0,confirmed",
                  "C,2012-03-05,merger,,,uncertain",
                  "D,2013-05-30,merger,,-0.059264,confirmed",
                  "F,2010-01-04,dropped,,,uncertain"],           # an ending on a security only the seeds run has
                 ["A", "B", "C", "D", "F"], ["AAA,2008-01-16,A", "BBB,2014-06-30,X"],
                 ["CLWR: no single security traded CLWR on 2012-06-29"])
    return full, seeds


def test_parity_counts_each_kind_of_difference(tmp_path):
    full, seeds = _two_runs(tmp_path)
    got = seeds_parity.parity(full, seeds)
    assert got["numbers"] == {
        "endings_lost": 1, "endings_gained": 0, "kind_changed": 1, "value_or_date_changed": 1,
        "securities_lost": 1, "securities_gained": 1, "seeds_placed_differently": 1,
        "truth_cases_failing_only_in_seeds": 1,
    }
    assert [r["sec_id"] for r in got["cases"]["endings_lost"]] == ["A"]
    assert got["cases"]["kind_changed"][0]["full_kind"] == "exchange/continuation"
    assert [r["sec_id"] for r in got["cases"]["value_or_date_changed"]] == ["C"]     # D is within the tolerance
    assert got["cases"]["securities_lost"] == [{"sec_id": "E", "full_ending": "merger"}]


def test_check_fails_only_above_the_floor(tmp_path, capsys):
    full, seeds = _two_runs(tmp_path)
    floor = tmp_path / "floor.json"
    args = ["--full", str(full), "--seeds", str(seeds), "--floor", str(floor)]
    assert seeds_parity.main([*args, "--check"]) == 0            # no floor yet: nothing to be above
    assert seeds_parity.main([*args, "--write-floor"]) == 0
    assert json.loads(floor.read_text())["endings_lost"] == 1
    assert seeds_parity.main([*args, "--check"]) == 0
    floor.write_text(json.dumps({"endings_lost": 0}))
    assert seeds_parity.main([*args, "--check"]) == 1
    assert "parity drop: endings_lost: 0 -> 1" in capsys.readouterr().err


def test_a_folder_that_is_not_a_run_exits_2(tmp_path, capsys):
    assert seeds_parity.main(["--full", str(tmp_path / "nope"), "--seeds", str(tmp_path / "nope")]) == 2
    assert "cannot read the runs" in capsys.readouterr().err
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_seeds_parity.py -q -o addopts=""`
Expected: an error at import, `FileNotFoundError` for `scripts/seeds_parity.py`.

- [ ] **Step 3: Write the script**

Create `scripts/seeds_parity.py`:

```python
"""Compare a seeds-only run with a full run of classify_universe.py made on the same code and cache: what the
seeds-only run loses or changes (docs/superpowers/plans/2026-10-10-seeds-only-parity.md).

  python scripts/seeds_parity.py --full out-full --seeds out-seeds                 # the parity numbers
  python scripts/seeds_parity.py --full out-full --seeds out-seeds --cases cases/  # also one CSV of cases per number
  python scripts/seeds_parity.py --full out-full --seeds out-seeds --check         # exit 1 if a number is above its
                                                                                   # floor in --floor (data/seeds_parity.json)
  python scripts/seeds_parity.py --full out-full --seeds out-seeds --write-floor   # lower the floor to today's numbers

Offline. Reads each folder's contract/delistings.csv, contract/seeds.csv, securities.csv and scorecard.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FLOOR = ROOT / "data" / "seeds_parity.json"
DLRET_TOL = 0.0005          # two runs' LLM answers can differ in the last digit of a ratio (NVRI, PXP)
SCORE_KEYS = ("L1.coverage_tickers", "L1.coverage_securities", "L1.left_view", "L1.closed_no_event")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _kind(row: dict[str, str]) -> str:
    """The contract's exit kind, with a continuation told apart from a plain exchange."""
    cont = (row.get("continuation") or "").strip().lower() not in ("", "0", "false")
    return (row.get("exit_kind") or "blank") + ("/continuation" if cont else "")


def _differs(a: str, b: str) -> bool:
    if not a or not b:
        return a != b
    return abs(float(a) - float(b)) > DLRET_TOL


def _metric(metrics: dict, key: str):
    """`key` is dotted, and so are some of the scorecard's own keys ("R1.1"): try every split."""
    parts = key.split(".")

    def go(node, i):
        if i == len(parts):
            return node
        if not isinstance(node, dict):
            return None
        for j in range(len(parts), i, -1):
            k = ".".join(parts[i:j])
            if k in node:
                found = go(node[k], j)
                if found is not None:
                    return found
        return None
    return go(metrics, 0)


def parity(full: Path, seeds: Path) -> dict:
    """The parity numbers (`numbers`), the cases behind each (`cases`) and the two scorecards' lines (`scores`)."""
    f_end = {r["sec_id"]: r for r in _rows(full / "contract" / "delistings.csv")}
    s_end = {r["sec_id"]: r for r in _rows(seeds / "contract" / "delistings.csv")}
    f_sec = {r["sec_id"] for r in _rows(full / "securities.csv")}
    s_sec = {r["sec_id"] for r in _rows(seeds / "securities.csv")}
    f_seed = {(r["ticker"], r["as_of"]): r["sec_id"] for r in _rows(full / "contract" / "seeds.csv")}
    s_seed = {(r["ticker"], r["as_of"]): r["sec_id"] for r in _rows(seeds / "contract" / "seeds.csv")}
    f_card = json.loads((full / "scorecard.json").read_text())
    s_card = json.loads((seeds / "scorecard.json").read_text())

    def ending(sec_id: str, row: dict[str, str]) -> dict[str, str]:
        return {"sec_id": sec_id, "kind": _kind(row), "last_trade_date": row["last_trade_date"],
                "dlret": row["dlret"], "verdict": row["verdict"]}

    def pair(sec_id: str) -> dict[str, str]:
        a, b = f_end[sec_id], s_end[sec_id]
        return {"sec_id": sec_id, "full_kind": _kind(a), "seeds_kind": _kind(b),
                "full_last_trade_date": a["last_trade_date"], "seeds_last_trade_date": b["last_trade_date"],
                "full_dlret": a["dlret"], "seeds_dlret": b["dlret"],
                "full_verdict": a["verdict"], "seeds_verdict": b["verdict"]}

    both = sorted(set(f_end) & set(s_end))
    f_fail = set(map(str, f_card["golden_failures"] + f_card["diagnosis_failures"]))
    s_fail = set(map(str, s_card["golden_failures"] + s_card["diagnosis_failures"]))
    case_id = lambda line: line.split(":", 1)[0]
    cases = {
        "endings_lost": [ending(k, f_end[k]) for k in sorted(f_end) if k not in s_end and k in s_sec],
        "endings_gained": [ending(k, s_end[k]) for k in sorted(s_end) if k not in f_end and k in f_sec],
        "kind_changed": [pair(k) for k in both if _kind(f_end[k]) != _kind(s_end[k])],
        "value_or_date_changed": [pair(k) for k in both if _kind(f_end[k]) == _kind(s_end[k])
                                  and (_differs(f_end[k]["dlret"], s_end[k]["dlret"])
                                       or f_end[k]["last_trade_date"] != s_end[k]["last_trade_date"]
                                       or f_end[k]["verdict"] != s_end[k]["verdict"])],
        "securities_lost": [{"sec_id": k, "full_ending": _kind(f_end[k]) if k in f_end else ""}
                            for k in sorted(f_sec - s_sec)],
        "securities_gained": [{"sec_id": k, "seeds_ending": _kind(s_end[k]) if k in s_end else ""}
                              for k in sorted(s_sec - f_sec)],
        "seeds_placed_differently": [{"ticker": t, "as_of": d, "full_sec_id": f_seed.get((t, d), ""),
                                      "seeds_sec_id": sid}
                                     for (t, d), sid in sorted(s_seed.items()) if f_seed.get((t, d), "") != sid],
        "truth_cases_failing_only_in_seeds": [{"case": line} for line in sorted(s_fail)
                                              if case_id(line) not in {case_id(x) for x in f_fail}],
    }
    scores = {k: {"full": _metric(f_card["metrics"], k), "seeds": _metric(s_card["metrics"], k)} for k in SCORE_KEYS}
    return {"numbers": {name: len(rows) for name, rows in cases.items()}, "cases": cases, "scores": scores}


def drops(numbers: dict[str, int], floor: dict[str, int]) -> list[str]:
    """The numbers above their floor (a number the floor does not name has none)."""
    return [f"{k}: {floor[k]} -> {v}" for k, v in sorted(numbers.items()) if k in floor and v > floor[k]]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--full", required=True, type=Path, help="the full run's output folder")
    p.add_argument("--seeds", required=True, type=Path, help="the seeds-only run's output folder")
    p.add_argument("--cases", type=Path, help="write one CSV of cases per number into this folder")
    p.add_argument("--floor", type=Path, default=DEFAULT_FLOOR)
    p.add_argument("--check", action="store_true", help="exit 1 if a number is above its floor")
    p.add_argument("--write-floor", action="store_true", help="lower the floor to today's numbers (never raise it)")
    args = p.parse_args(argv)
    try:
        result = parity(args.full, args.seeds)
    except (OSError, KeyError, ValueError) as exc:
        print(f"seeds_parity: cannot read the runs: {exc!r}", file=sys.stderr)
        return 2
    for k, v in result["scores"].items():
        print(f"{k:38} full {v['full']}   seeds {v['seeds']}")
    for k, v in result["numbers"].items():
        print(f"{k:38} {v}")
    if args.cases:
        args.cases.mkdir(parents=True, exist_ok=True)
        for name, rows in result["cases"].items():
            with (args.cases / f"{name}.csv").open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["sec_id"], lineterminator="\n")
                w.writeheader()
                w.writerows(rows)
    floor = json.loads(args.floor.read_text()) if args.floor.exists() else {}
    worse = drops(result["numbers"], floor)
    for line in worse:
        print(f"parity drop: {line}", file=sys.stderr)
    if args.write_floor:
        new = {k: min(v, floor.get(k, v)) for k, v in result["numbers"].items()}
        args.floor.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")
        print(f"Wrote {args.floor}")
    return 1 if args.check and worse else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_seeds_parity.py -q -o addopts=""`
Expected: `3 passed`.

On the two runs of 2026-10-10 this script printed: `endings_lost 26`, `endings_gained 16`,
`kind_changed 29`, `value_or_date_changed 16`, `securities_lost 37`, `securities_gained 14`,
`seeds_placed_differently 25`, `truth_cases_failing_only_in_seeds 39`.

- [ ] **Step 5: Add the command to `docs/commands.md` and `README.md`**

`CLAUDE.md` is an index now; the full command list it points to is `docs/commands.md`. In
`docs/commands.md`, after the `seeds_from_observations.py` command line, add:

```
python scripts/seeds_parity.py --full <full run's output folder> --seeds <seeds-only run's>   # offline: what the seeds-only run loses or changes; --cases DIR writes the case lists, --check fails above the floor in data/seeds_parity.json, --write-floor lowers it
```

In `README.md`, in the `scripts/` listing after `seeds_from_observations.py`, add:

```
    seeds_parity.py                   A seeds-only run against a full run: lost and changed endings, the floor
```

- [ ] **Step 6: Commit**

```bash
git add scripts/seeds_parity.py tests/test_seeds_parity.py docs/commands.md README.md
git commit -m "seeds_parity: what a seeds-only run loses against a full run, with a floor"
```

---

### Task 2: An era's last-seen date follows its own CUSIP rows (S1)

**Files:**
- Modify: `src/delist_detection/identity/identity.py` (`era_last_seen`; new `last_sightings`; the
  `last_seen = {...}` line in `_resolve_issuers`; the `hi = ...` line in `_refine`)
- Modify: `tests/test_security_master.py` (five new tests)
- Modify: `tests/test_resolver_renamed.py` (one expected date in
  `test_the_fixture_eras_and_last_sightings_are_the_real_ones`, one expected memo key in
  `test_the_second_pass_answer_is_used_flagged_and_never_saved`)

**Interfaces:**
- Produces: `era_last_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400, until: str | None = None) -> str`
  and `last_sightings(eras: Sequence[TickerEra], ftd: FtdIndex) -> dict[str, str]` (era key to date).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_security_master.py`, after `test_era_last_seen_extends_past_the_last_snapshot`.
Add `from dataclasses import replace` to the imports at the top of the file.

```python
def _own(symbol, cusip, dates, desc="X CO"):
    return [FtdRow(d, cusip, symbol, desc, 10.0) for d in dates]


def test_era_last_seen_follows_its_own_cusip_to_its_last_row():
    # One seed in 2008; the security's own CUSIP keeps appearing under the ticker until 2016.
    era = replace(_era("HOT", ("2008-01-16", "STARWOOD HOTELS & RESRTS")), ftd_cusips=("85590A401",))
    own = ["2008-06-02", "2009-05-04", "2010-04-05", "2011-03-07", "2012-02-06", "2013-01-07", "2013-12-09",
           "2014-11-10", "2015-10-12", "2016-09-20"]
    ftd = FtdIndex(_own("HOT", "85590A401", own, "STARWOOD HOTELS&RESORTS WRLDWD")
                   + _own("HOT", "99999999X", ["2017-01-03"], "ANOTHER HOLDER INC"))
    assert era_last_seen(era, ftd) == "2016-09-20"


def test_era_last_seen_stops_at_a_gap_longer_than_the_horizon():
    era = replace(_era("X", ("2008-01-16", "X CO")), ftd_cusips=("AAA",))
    ftd = FtdIndex(_own("X", "AAA", ["2008-06-02", "2010-01-04"]))        # 581 days apart
    assert era_last_seen(era, ftd) == "2008-06-02"


def test_era_last_seen_without_its_own_cusips_takes_one_step_only():
    # No CUSIP of its own: rows are matched by name, which is too weak to follow for years.
    era = _era("AET", ("2018-06-29", "AETNA INC"))
    ftd = FtdIndex(_own("AET", "00817Y108", ["2018-11-29", "2019-10-01"], "AETNA INC.(NEW)"))
    assert era_last_seen(era, ftd) == "2018-11-29"


def test_era_last_seen_stops_before_the_tickers_next_era():
    # The same CUSIP runs on under a later era of the ticker (a rename): the earlier era stops before it.
    era = replace(_era("KORS", ("2012-06-29", "MICHAEL KORS HOLDINGS LTD")), ftd_cusips=("G60754101",))
    rows = ["2012-09-04", "2013-06-03", "2014-03-03", "2014-11-03", "2015-08-03", "2016-05-02"]
    ftd = FtdIndex(_own("KORS", "G60754101", rows, "MICHAEL KORS HLDGS LTD"))
    assert era_last_seen(era, ftd, until="2014-12-31") == "2014-11-03"
    assert era_last_seen(era, ftd) == "2016-05-02"
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py -q -o addopts="" -k era_last_seen`
Expected: `test_era_last_seen_follows_its_own_cusip_to_its_last_row` fails with
`'2008-06-02' == '2016-09-20'`, and `test_era_last_seen_stops_before_the_tickers_next_era` fails
with `TypeError: era_last_seen() got an unexpected keyword argument 'until'`. The other two pass.

- [ ] **Step 3: Change `era_last_seen` and add `last_sightings`**

In `src/delist_detection/identity/identity.py`, replace the whole of `era_last_seen` with:

```python
def era_last_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400, until: str | None = None) -> str:
    """The era's last sighting: its last observation, or a later FTD row of its
    own (`_own_rows`) under its ticker within `horizon_days`. An era with FTD
    CUSIPs of its own is then followed along them, each step at most
    `horizon_days` past the row before, to the last row before `until` (the
    day the ticker's next era begins; None: no later era): the security's own
    fails rows say how long it traded, whatever the caller observed (one seed
    in 2008, Starwood's rows to 2016)."""
    def later(after: str, stop: str | None) -> list[str]:
        lo = (date.fromisoformat(after) + timedelta(days=1)).isoformat()
        hi = (date.fromisoformat(after) + timedelta(days=horizon_days)).isoformat()
        return [r.date for r in _own_rows(era, ftd.by_symbol(era.ticker, lo, hi)) if stop is None or r.date < stop]

    last = max([era.last, *later(era.last, None)])
    while era.ftd_cusips:
        more = later(last, until)
        if not more:
            break
        last = max(more)
    return last


def last_sightings(eras: Sequence[TickerEra], ftd: FtdIndex) -> dict[str, str]:
    """Each era's last sighting by era key (`era_last_seen`), an era followed no
    further than the day its ticker's next era begins."""
    starts: dict[str, list[str]] = defaultdict(list)
    for e in eras:
        starts[e.ticker].append(e.first)
    return {e.key: era_last_seen(e, ftd, until=min((f for f in starts[e.ticker] if f > e.first), default=None))
            for e in eras}
```

`defaultdict`, `Sequence`, `date` and `timedelta` are already imported in that module.

In `_resolve_issuers` (same file), replace

```python
    last_seen = {e.key: era_last_seen(e, ftd) for e in eras}
```

with

```python
    last_seen = last_sightings(eras, ftd)
```

- [ ] **Step 4: Update the one existing test whose expected value moves**

In `tests/test_resolver_renamed.py`, add `last_sightings` to the import from
`delist_detection.identity.identity`, and in
`test_the_fixture_eras_and_last_sightings_are_the_real_ones` replace

```python
    seen = {k: era_last_seen(e, ftd) for k, e in eras.items() if e.ticker in {"KORS", "NU", "LUK", "LMCA"}}
```

with

```python
    seen = {k: v for k, v in last_sightings(list(eras.values()), ftd).items()
            if eras[k].ticker in {"KORS", "NU", "LUK", "LMCA"}}
```

and change the expected `"LUK@2008-01-16": "2010-07-13"` to `"LUK@2008-01-16": "2012-06-26"`.
Leucadia's own rows run through the 2009 to 2012 hole in the snapshots to just before the next
LUK era. The other dates in that assertion do not change.

In the same file, the helper `_second_pass` computes the dates it hands the second pass with
`last_seen = {e.key: era_last_seen(e, ftd) for e in chosen}`. Replace that line with

```python
    last_seen = last_sightings(chosen, ftd)
```

The pipeline takes these dates from `last_sightings`, which stops an era's follow before the
ticker's next era, and the helper must do the same. Called bare, `era_last_seen` now follows an
era's own CUSIP with no bound. Rule D of the second pass (`cusip_issuer`, added on the base
branch after this plan was written) reads an era's dates, so with the unbounded dates
`test_an_era_whose_name_names_no_name_of_the_issuer_takes_nothing` fails: TRI@2008 (Triad
Hospitals, a stale snapshot row) runs on over Thomson Reuters' rows into TRI@2012's dates and
takes Thomson Reuters as its issuer. With the helper changed, that test passes unchanged.

- [ ] **Step 5: Open the fails index to the run date**

`identity._refine` opens the fails index only to the newest observation plus 400 days. When the
newest observation is old, the follow is cut there. Add this test to
`tests/test_security_master.py`, and add `_refine` and `last_sightings` to that file's import
from `delist_detection.identity.identity`:

```python
def test_the_fails_window_runs_to_the_run_date_whatever_the_newest_observation():
    # The newest observation of the whole input is from 2010; the security's own rows run to 2015.
    obs = [Observation("HOT", "2010-01-04", "STARWOOD HOTELS & RESRTS")]
    days = ["2010-02-01", "2010-12-01", "2011-10-03", "2012-08-01", "2013-06-03", "2014-04-01", "2015-02-02"]
    rows = [FtdRow(d, "85590A401", "HOT", "STARWOOD HOTELS&RESORTS WRLDWD", 10.0) for d in days]
    eras, _, ftd = _refine(ObservationIndex(obs), _RowsClient(rows), date(2026, 9, 25), None, lambda *a: None)
    assert last_sightings(eras, ftd) == {"HOT@2010-01-04": "2015-02-02"}
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py -q -o addopts="" -k fails_window`
Expected: FAIL with `{'HOT@2010-01-04': '2010-12-01'} != {'HOT@2010-01-04': '2015-02-02'}`.

In `_refine` (`src/delist_detection/identity/identity.py`), replace

```python
    hi = min(as_of, max(date.fromisoformat(e.last) for e in eras) + timedelta(days=400))
```

with

```python
    hi = as_of        # an era is followed along its own fails rows for as long as they run (`era_last_seen`)
```

Run the same command. Expected: PASS.

One existing expectation moves with it. In `tests/test_resolver_renamed.py`,
`test_the_second_pass_answer_is_used_flagged_and_never_saved`, change
`"CPRI|2026-02-04|CAPRI HOLDINGS LTD"` to `"CPRI|2026-08-20|CAPRI HOLDINGS LTD"`. That test runs
KORS and CPRI alone, and Capri's era is now followed to its last fails row before the run date.
For the real input the newest observation is 2026-06-30, the cap was already the run date, and
nothing changes.

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py tests/test_resolver_renamed.py tests/test_observations.py tests/test_figi_handoff.py -q -o addopts=""`
Expected: all pass.

Then the whole suite: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: no failure. With Tasks 1 and 2 applied on a copy of `6bbeb7e`: 3894 passed, 44 xfailed
(3886 before Task 1, three tests from Task 1 and five from Task 2).

- [ ] **Step 7: Update the docs**

In `docs/architecture.md` (where `CLAUDE.md`'s module descriptions now live), in the
`ticker_resolver.py` bullet, after the sentence that ends "its first
sighting (`since=`): every search tier, and a cached answer from one, takes only a company that
had filed by then.", add:

```
The date it asks at is the era's last sighting (`identity.last_sightings`): its last observation, then its own CUSIP's
fails rows under its ticker for as long as they continue, each step at most 400 days, stopping before the ticker's next
era. One seed in 2008 is asked at the security's real end.
```

In the same file, the `identity.py` bullet names `era_last_seen`: add `last_sightings` beside it.

In `docs/data-flow.md`, in the stage diagram, the box labelled `era_last_seen, era_cusips` has
the note "FTD-confirmed true last sighting + CUSIPs". Change the note to "last sighting followed
along the era's own CUSIP rows + CUSIPs", and in the paragraph that names `identity.era_rows` and
`era_last_seen`'s row choice, add the two sentences above.

- [ ] **Step 8: Commit**

```bash
git add src/delist_detection/identity/identity.py tests/test_security_master.py tests/test_resolver_renamed.py docs/architecture.md docs/data-flow.md
git commit -m "An era's last sighting follows its own CUSIP's fails rows to their end"
```

---

### Task 3: Parity checkpoint after S1 (network)

**Files:**
- Create: `data/seeds_parity.json`
- Modify: `docs/superpowers/plans/2026-10-10-seeds-only-parity.md` (record the numbers under "Checkpoints")

**How this task is run on this branch.** The controller runs it, not a subagent: it needs live SEC,
Nasdaq and LLM access and a judgment at Step 4. The commands below are the plan's as written at
`6e43e09`; on this branch they change in four ways, none of which changes what is measured.

1. The worktree has no `cache/` folder. The cache to copy is the warm cache the faster-runs work
   left for this code (`0a7a345`'s full input, every SEC and LLM answer present), with the
   seeds-only run's earlier LLM answers added to it so a filing asked before is not paid for twice.
2. The code before Task 2 is a `git archive` snapshot of that commit in a scratch folder, not a
   second worktree.
3. A warm full run takes about 4 minutes on this code, not 9, and LLM calls run on 8 threads.
4. `--id-baseline` is one fixed copy of this branch's committed `output/securities.csv` for every run.

- [ ] **Step 1: Make sure no other SEC client is running**

Run: `ls -la ~/.cache/delist_detection/sec_rate.lock /tmp/claude/delist_detection/sec_rate.lock`
Neither may have been modified in the last few minutes.

- [ ] **Step 2: The full input before S1, with an empty resolver memo**

The memo file holds answers older code computed (NWA's issuer exists only there), so a run that
reads it cannot tell what S1 changed. This step makes the reference: the code before Task 2, the
same cache, no memo.

```bash
ROOT=$PWD
PY=~/miniconda3/envs/rdagent4qlib/bin/python
OUT=$TMPDIR/seeds-parity-s1; mkdir -p $OUT
export DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock
BASE=<the commit before Task 2>
git worktree add --detach $OUT/before $BASE && ln -s $ROOT/.env $OUT/before/.env
cp -cR cache $OUT/cache-before                   # macOS copy-on-write; elsewhere: cp -a --reflink=auto
rm -f $OUT/cache-before/ticker_resolution.json
(cd $OUT/before && PYTHONPATH=$OUT/before/src $PY scripts/classify_universe.py --observations data/observations.csv \
  --output-dir $OUT/out-before --cache-dir $OUT/cache-before --as-of 2026-09-25 --sec-workers 8 \
  --extract-merger-terms-llm --id-baseline $ROOT/output/securities.csv > $OUT/before.log 2>&1); echo before exit=$?
PYTHONPATH=src $PY scripts/seeds_parity.py --full output --seeds $OUT/out-before --floor $OUT/no-floor.json --cases $OUT/memo-effect
```

Expected: exit 0. Check the tool output for sandbox denials before trusting a table. The last
command compares the published output with this run (the script compares any two runs; here
"full" is the published one, and `--floor` names a file that does not exist so no floor is
read). What it lists is what the old memo entries were holding up. This is the evidence for
decision B. Record the counts.

- [ ] **Step 3: The full input and the seeds at Task 2's commit**

```bash
cp -cR $OUT/cache-before $OUT/cache-full         # its memo now holds only answers the current code computed
PYTHONPATH=src $PY scripts/seeds_from_observations.py --observations data/observations.csv --out $OUT/seeds.csv
PYTHONPATH=src $PY scripts/classify_universe.py --observations data/observations.csv \
  --output-dir $OUT/out-full --cache-dir $OUT/cache-full --as-of 2026-09-25 --sec-workers 8 \
  --extract-merger-terms-llm --id-baseline output/securities.csv > $OUT/full.log 2>&1; echo full exit=$?
cp -cR $OUT/cache-full $OUT/cache-seeds          # after the full run: the seeds run reads the same LLM answers
PYTHONPATH=src $PY scripts/classify_universe.py --observations $OUT/seeds.csv \
  --output-dir $OUT/out-seeds --cache-dir $OUT/cache-seeds --as-of 2026-09-25 --sec-workers 8 \
  --extract-merger-terms-llm > $OUT/seeds.log 2>&1; echo seeds exit=$?
```

Expected: both exit 0. A warm full run takes about 9 minutes; each LLM call for a filing not yet
cached adds about 3 seconds; S1 moves 638 eras' lookup dates in the full run, so expect new SEC
requests in both runs.

- [ ] **Step 4: Judge what S1 did to the full run**

```bash
PYTHONPATH=src $PY scripts/scorecard.py --output-dir $OUT/out-full --check
PYTHONPATH=src $PY scripts/seeds_parity.py --full $OUT/out-before --seeds $OUT/out-full --floor $OUT/no-floor.json --cases $OUT/s1-effect
$PY - $OUT <<'EOF'
import csv, sys
out = sys.argv[1]
def issuers(folder):
    seen = {}
    for r in csv.DictReader(open(f"{out}/{folder}/observation_map.csv", encoding="utf-8-sig")):
        seen.setdefault(r["era"], r["issuer_cik"])
    return seen
before, after = issuers("out-before"), issuers("out-full")
moved = sorted((k, before[k] or "(none)", after.get(k) or "(none)") for k in before if before[k] != after.get(k))
print(len(moved), "eras have another issuer after S1")
for row in moved:
    print(*row)
EOF
```

The second command lists the endings S1 changed in the full run (lost, gained, another kind,
another value or date). The third lists every era whose issuer changed. Review each listed era
and ending against EDGAR and the truth sets: it is either a correction or a regression. Pay
attention to a security that kept trading over the counter under the same symbol after its
Form 25, whose lookup date is now years after the filing. A regression goes through the
diagnosis loop (`scripts/truth_loop_round.py`) or back into Task 2. If the full run gets worse
in a way the loop does not accept, stop and report: do not lower a floor to make it pass.

- [ ] **Step 5: Read the parity numbers, check them, then write the floor**

```bash
PYTHONPATH=src $PY scripts/seeds_parity.py --full $OUT/out-full --seeds $OUT/out-seeds --cases $OUT/cases
```

Before S1 the numbers were `endings_lost 26`, `kind_changed 29`, `securities_lost 37`,
`truth_cases_failing_only_in_seeds 39` (with the old memo in both runs). In the 53-seed test S1
fixed 22 endings, among them AL, BKC, CCE, CST, DISH, FTI, HOT, ITC, LPI, MDR, MER, NSAM, OMX,
PBCT, PPDI, PRE, PS, S (both), SC, VAL and WBA. Look each of those up in `$OUT/cases/`: none may
still be listed under `endings_lost` or `kind_changed`. ANN is expected to be wrong until S2
(merger 2011-03-18 on CIK 34151). CEG 2008 is expected to remain. DNB 2020 and VIACA stayed
unfixed in the subset test, where the fails index was cut at 2024-08-03: see whether they are
fixed here, and note what the log says for each that is not.

Only when that check is done:

```bash
PYTHONPATH=src $PY scripts/seeds_parity.py --full $OUT/out-full --seeds $OUT/out-seeds --write-floor
```

- [ ] **Step 6: Record and commit**

Add a "Checkpoints" section at the end of this file with the date, the commit, the counts from
Step 2 (what the memo held up), the lists from Step 4 with the verdict on each, the eight parity
numbers, the four scorecard lines for both runs, and the cases from Step 5 that did not move as
expected. Then:

```bash
git worktree remove $OUT/before
git add data/seeds_parity.json docs/superpowers/plans/2026-10-10-seeds-only-parity.md
git commit -m "Seeds-only parity after S1: the floor"
```

---

### Task 4: The issuer is asked at two dates (S1, reworked)

Task 3 found that Task 2 alone makes the full run worse: 21 eras got another issuer, 19 of them
wrongly ("Checkpoints", checkpoint 1). Task 2 moved the one lookup date from the capped date (the
last observation, or a later own fails row within 400 days) to the end of the era's own fails
rows. The two dates are good for different things. A Form 25 search belongs at the end of the
line. The name checks read the names in force within 30 days of the lookup date, so years after
the observation a renamed issuer is rejected, and at the end of the line another issuer's
filings mention the ticker. This task asks at both dates and chooses.

The rule ("R9" in the checkpoint's table, scored offline on both inputs before this task was
written):

- A **miss** is an answer with no CIK. A **weak** answer is a CIK from `efts_name_mismatch`,
  `efts_frequency_name_mismatch` or `rename`. Any other CIK is a **strong** answer.
- Both strong, the same CIK: the capped date's answer.
- Both strong, different CIKs: the followed date's answer. The exception: the followed date's
  source is `company_tickers` and the capped date's is not. Then the capped date's answer stands,
  because by the end of the line a successor can hold the ticker and the name (Prologis 2011,
  Merck 2009, Match Group 2020, Spectrum Brands 2018).
- One strong: that one.
- Neither strong: the era has no first-pass answer. The second pass may infer its issuer. A weak
  answer (the capped date's, else the followed date's) stands only when no pass infers one.
- 2b (`check_names`) runs with the followed dates. The second pass (`infer`) runs twice, with the
  capped dates and then with the followed dates, on the same first-pass answers; an era the first
  run answers keeps that answer (Constellation Energy 2008: its 8-K frequency candidate is among
  the top five before the capped date and not before the merger).

**Files:**
- Modify: `src/delist_detection/identity/ticker_resolver.py` (`WEAK_SOURCES`, `TickerResolution.strong`)
- Modify: `src/delist_detection/identity/identity.py` (`era_capped_seen`, `capped_sightings`,
  `FirstPass`, `choose_first_pass`, `_Issuers.capped`, `_resolve_issuers`, the degraded check in
  `_resolve_securities`, the module docstring's stage 2 line)
- Modify: `tests/test_security_master.py`, `tests/test_resolver_renamed.py`, `tests/test_issuer_code.py`
- Modify: `docs/architecture.md`, `docs/data-flow.md`

**Interfaces:**
- Consumes: `era_last_seen`, `last_sightings` (Task 2), `EraIssuers.check_names`, `EraIssuers.infer`,
  `TickerResolver.resolve(ticker, observed_date, *, pin, name, since)`, `TickerResolver.is_degraded`.
- Produces:
  - `ticker_resolver.WEAK_SOURCES: frozenset[str]` and `TickerResolution.strong -> bool`
  - `identity.era_capped_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400) -> str`
  - `identity.capped_sightings(eras: Sequence[TickerEra], ftd: FtdIndex) -> dict[str, str]`
  - `identity.FirstPass(answer: TickerResolution, fallback: TickerResolution | None = None)`
  - `identity.choose_first_pass(capped: TickerResolution, followed: TickerResolution) -> FirstPass`
  - `_Issuers.capped: dict[str, str]` (era key to the capped date), beside `last_seen` (the followed date)

- [ ] **Step 1: Write the failing tests for the two dates and the choice**

Add to `tests/test_security_master.py`, after `test_era_last_seen_stops_before_the_tickers_next_era`.
Add `capped_sightings`, `choose_first_pass`, `era_capped_seen` and `FirstPass` to the import from
`delist_detection.identity.identity`, and `TickerResolution` from
`delist_detection.identity.ticker_resolver` if the file does not import it yet.

```python
def test_the_capped_date_is_one_step_and_the_followed_date_the_end_of_the_rows():
    era = replace(_era("HOT", ("2008-01-16", "STARWOOD HOTELS & RESRTS")), ftd_cusips=("85590A401",))
    own = ["2008-06-02", "2009-05-04", "2010-04-05", "2011-03-07", "2012-02-06"]
    ftd = FtdIndex(_own("HOT", "85590A401", own, "STARWOOD HOTELS&RESORTS WRLDWD"))
    assert era_capped_seen(era, ftd) == "2008-06-02"
    assert era_last_seen(era, ftd) == "2012-02-06"
    assert capped_sightings([era], ftd) == {"HOT@2008-01-16": "2008-06-02"}


def _answer(cik, source):
    return TickerResolution("X", cik, None, source)


@pytest.mark.parametrize("capped, followed, answer, fallback", [
    # both strong, one CIK: the capped date's answer (its source is the one the tables have always shown)
    ((1, "name_search"), (1, "efts"), (1, "name_search"), None),
    # both strong, two CIKs: the end of the line, where the security's own Form 25 is (ITC, Laredo, Sprint)
    ((1, "name_search"), (2, "name_search"), (2, "name_search"), None),
    ((1, "efts"), (2, "efts_frequency"), (2, "efts_frequency"), None),
    # ... unless the end of the line only has today's ticker map: a successor took the ticker and the name (Prologis)
    ((1, "name_search"), (2, "company_tickers"), (1, "name_search"), None),
    ((1, "company_tickers"), (2, "company_tickers"), (2, "company_tickers"), None),
    # one strong: it (a later rename loses nothing; a seed's early miss is repaired at the end of the line)
    ((1, "company_tickers"), (None, "rejected_validation"), (1, "company_tickers"), None),
    ((None, "rejected_validation"), (2, "efts_frequency"), (2, "efts_frequency"), None),
    ((1, "name_search"), (2, "efts_name_mismatch"), (1, "name_search"), None),
    ((1, "efts_frequency_name_mismatch"), (2, "efts"), (2, "efts"), None),
    # neither strong: no first-pass answer; a weak one is kept aside, the capped date's first
    ((1, "efts_name_mismatch"), (None, "rejected_validation"), (None, "rejected_validation"), (1, "efts_name_mismatch")),
    ((None, "rejected_validation"), (2, "rename"), (None, "rejected_validation"), (2, "rename")),
    ((1, "efts_name_mismatch"), (2, "efts_name_mismatch"), (None, "none"), (1, "efts_name_mismatch")),
    ((None, "none"), (None, "rejected_validation"), (None, "none"), None),
])
def test_the_first_pass_answer_of_two_lookups(capped, followed, answer, fallback):
    got = choose_first_pass(_answer(*capped), _answer(*followed))
    assert (got.answer.cik, got.answer.source) == answer
    assert (got.fallback and (got.fallback.cik, got.fallback.source)) == fallback


def test_a_pin_or_an_override_is_strong_and_a_miss_is_not():
    assert _answer(1, "cik_map").strong and _answer(1, "manual").strong
    assert not _answer(None, "rejected_validation").strong and not _answer(1, "rename").strong
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py -q -o addopts="" -k "capped or first_pass or strong"`
Expected: an `ImportError` on `capped_sightings`.

- [ ] **Step 3: The weak sources and the two dates**

In `src/delist_detection/identity/ticker_resolver.py`, directly above `class TickerResolution`'s
`@dataclass`, add:

```python
# A CIK a tier took although its EDGAR names do not agree with the observed name, or one reached through the rename
# map: the lookup's last resort. `identity.choose_first_pass` never prefers it to an answer whose name agrees, and the
# era-level passes may answer in its place.
WEAK_SOURCES = frozenset({"efts_name_mismatch", "efts_frequency_name_mismatch", "rename"})
```

and at the end of `TickerResolution`:

```python
    @property
    def strong(self) -> bool:
        """A CIK from a pin, an override or a tier that checked the name (not one of `WEAK_SOURCES`, not a miss)."""
        return self.cik is not None and self.source not in WEAK_SOURCES
```

In `src/delist_detection/identity/identity.py`, replace `era_last_seen` with these three
functions (its docstring's facts move with them), and add `capped_sightings` after `last_sightings`:

```python
def _later_own_rows(era: TickerEra, ftd: FtdIndex, after: str, horizon_days: int, stop: str | None = None) -> list[str]:
    """The days of the era's own rows (`_own_rows`) under its ticker in the `horizon_days` after `after`, before `stop`."""
    lo = (date.fromisoformat(after) + timedelta(days=1)).isoformat()
    hi = (date.fromisoformat(after) + timedelta(days=horizon_days)).isoformat()
    return [r.date for r in _own_rows(era, ftd.by_symbol(era.ticker, lo, hi)) if stop is None or r.date < stop]


def era_capped_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400) -> str:
    """The era's capped date: its last observation, or a later FTD row of its
    own (`_own_rows`) under its ticker within `horizon_days`. The names the
    caller observed were in force around this date."""
    return max([era.last, *_later_own_rows(era, ftd, era.last, horizon_days)])


def era_last_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400, until: str | None = None) -> str:
    """The era's last sighting: its capped date (`era_capped_seen`); an era with
    FTD CUSIPs of its own is then followed along them, each step at most
    `horizon_days` past the row before, to the last row before `until` (the
    day the ticker's next era begins; None: no later era): the security's own
    fails rows say how long it traded, whatever the caller observed (one seed
    in 2008, Starwood's rows to 2016)."""
    last = era_capped_seen(era, ftd, horizon_days)
    while era.ftd_cusips:
        more = _later_own_rows(era, ftd, last, horizon_days, until)
        if not more:
            break
        last = max(more)
    return last
```

```python
def capped_sightings(eras: Sequence[TickerEra], ftd: FtdIndex) -> dict[str, str]:
    """Each era's capped date by era key (`era_capped_seen`)."""
    return {e.key: era_capped_seen(e, ftd) for e in eras}
```

- [ ] **Step 4: The choice**

In `identity.py`, above `_Issuers`, add (import `WEAK_SOURCES` is not needed here; `strong` is a
property of the answer):

```python
@dataclass(frozen=True)
class FirstPass:
    """One era's first-pass answer out of its two lookups (`choose_first_pass`): `answer`, what the era-level passes
    see (a strong answer, or no CIK), and `fallback`, a weak answer kept aside, which stands only when no pass
    infers an issuer."""
    answer: TickerResolution
    fallback: TickerResolution | None = None


def choose_first_pass(capped: TickerResolution, followed: TickerResolution) -> FirstPass:
    """The first-pass answer of an era asked at its capped date and at the end of its own fails rows
    (`era_capped_seen`, `era_last_seen`; one answer given twice when they are one day).

    The names the caller observed were in force at the capped date; the security's own Form 25 is at the end of the
    rows. So: both strong (`TickerResolution.strong`) and one CIK, the capped date's answer; both strong and two
    CIKs, the followed date's (ITC Holdings 2016, Sprint 2020: another company of the name answers early), unless
    it is today's ticker map and the capped date's is not (by the end of the line a successor holds the ticker and
    the name: Prologis 2011, Merck 2009); one strong, that one (a later rename rejects the right company at the
    end: AMC Networks; a seed's early date finds no Form 25: Coca-Cola Enterprises); neither, no answer, with a
    weak one kept aside (the capped date's first)."""
    if capped.strong and followed.strong:
        successor = followed.source == "company_tickers" and capped.source != "company_tickers"
        return FirstPass(followed if followed.cik != capped.cik and not successor else capped)
    if capped.strong or followed.strong:
        return FirstPass(capped if capped.strong else followed)
    fallback = capped if capped.cik is not None else followed if followed.cik is not None else None
    blank = capped if capped.cik is None else followed if followed.cik is None else \
        TickerResolution(capped.ticker, None, None, "none")
    return FirstPass(blank, fallback)
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py -q -o addopts="" -k "capped or first_pass or strong or era_last_seen"`
Expected: all pass.

- [ ] **Step 5: Write the failing stage tests**

In `tests/test_resolver_renamed.py`. Add a lookup double that answers by era and date, and give
`_identify` optional `rows=` (the fails rows, default the fixture's `_rows()`):

```python
class _DatedLookup(CommittedLookup):
    """The lookup answering by era and date: `dated` maps an era key to {lookup date: (CIK, tier)}; a date it does
    not list is a miss. `asked` records every (era key, date). Other eras answer as `CommittedLookup` does."""

    def __init__(self, dated, answers=None):
        super().__init__(answers or {})
        self.dated, self.asked = dated, []

    def resolve(self, ticker, observed_date=None, *, pin=None, name=None, since=None):
        key = f"{ticker}@{since}"
        self.asked.append((key, observed_date))
        if key not in self.dated:
            return super().resolve(ticker, observed_date, pin=pin, name=name, since=since)
        cik, tier = self.dated[key].get(observed_date, (None, "rejected_validation"))
        return TickerResolution(ticker, cik, None, tier)
```

Each test below runs the identity stage (`_identify`) and reads `identity.issuers[key].cik` and
`identity.tier(key)`. Use CIKs the file's `_Edgar` serves (or an `_Edgar` built with them), so
the issuer's names read does not degrade the era. For the tests that need two different dates,
use one observed ticker with one observation and own-CUSIP rows that run for years, as
`test_the_capped_date_is_one_step_and_the_followed_date_the_end_of_the_rows` does; first assert
the two dates the stage computes for it, so a reader sees them.

| Test name | Lookup | Expected |
| --- | --- | --- |
| `test_an_era_is_asked_at_its_capped_date_and_at_the_end_of_its_rows` | any | `lookup.asked` for the era is the capped date, then the followed date, in that order |
| `test_an_era_whose_two_dates_are_one_day_is_asked_once` | any | one entry in `lookup.asked` for an era with no row after its last observation |
| `test_a_later_rename_does_not_lose_the_issuer` | capped: (A, `company_tickers`); followed: miss | issuer A, tier `company_tickers` |
| `test_the_end_of_the_line_answers_for_a_seed` | capped: miss; followed: (A, `efts_frequency`) | issuer A, tier `efts_frequency` |
| `test_two_strong_answers_take_the_end_of_the_line` | capped: (B, `name_search`); followed: (A, `efts`) | issuer A, tier `efts` |
| `test_todays_ticker_map_at_the_end_does_not_replace_the_named_issuer` | capped: (A, `name_search`); followed: (B, `company_tickers`) | issuer A, tier `name_search` |
| `test_a_weak_answer_gives_way_to_the_second_pass` | the fixture's KORS and CPRI eras through `CommittedLookup`: `KORS@2012-06-29` answers (some other CIK, `efts_name_mismatch`), `KORS@2014-12-31` (1530721, `name_search`), `CPRI@2018-12-31` (1530721, `cik_map`) | `KORS@2012-06-29` has issuer 1530721, tier `shared_cusip`, and an `issuer_inferred` review item; no `issuer_cusip_disagrees` item |
| `test_a_weak_answer_stands_when_nothing_is_inferred` | one era with no CUSIP link and no frequency candidate: (A, `efts_name_mismatch`) at both dates | issuer A, tier `efts_name_mismatch` |
| `test_an_era_degraded_at_either_date_is_flagged` | a lookup whose `is_degraded` is true only for the followed date | one `resolution_degraded` review item for the era |

Add one test for the second pass's two runs, with `_passes()` and the fixture: an era that rule
B answers with the capped dates and not with the followed dates keeps the answer when
`_resolve_issuers` runs both. If the fixture has no such era, script the `frequency` fixture so
the right candidate is listed for the capped day only, and name the test
`test_the_second_pass_runs_with_the_capped_dates_first`.

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_resolver_renamed.py -q -o addopts="" -k "capped or end_of or weak or rename or ticker_map or asked or degraded_at"`
Expected: the new tests fail (one lookup per era today; the weak answer blocks the second pass).

- [ ] **Step 6: `_resolve_issuers` asks twice and chooses**

In `identity.py`:

`_Issuers` gains `capped: dict[str, str]` directly before `last_seen`, and its docstring says:
"the two dates the lookup was asked at (`capped`, and `last_seen`, the end of the era's own
fails rows)".

Replace the body of `_resolve_issuers` from `resolver, record = ...` to the `second = ...` log
line with:

```python
    resolver, record = clients.resolver, clients.issuers
    capped, last_seen = capped_sightings(eras, ftd), last_sightings(eras, ftd)

    def both(lookup, e: TickerEra) -> tuple[TickerResolution, TickerResolution]:
        """The era's answers at its capped date and at the end of its rows (one lookup when they are one day)."""
        at_cap = lookup.resolve(e.ticker, capped[e.key], pin=e.cik_pin, name=e.name, since=e.first)
        if last_seen[e.key] <= capped[e.key]:
            return at_cap, at_cap
        return at_cap, lookup.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin, name=e.name, since=e.first)

    mark = meter.start()
    if workers > 1:
        # Warm the EDGAR caches: each era resolved on a worker thread by a shadow
        # lookup (a snapshot of this memo that saves nothing), its answers thrown
        # away. The resolve below then runs one era at a time, in order, on this
        # thread, and finds its requests answered.
        warm(eras, both, workers=workers, state=resolver.shadow, name="issuer resolution")
    first = {e.key: choose_first_pass(*both(resolver, e)) for e in eras}
    resolver.flush()
    answers = {key: f.answer for key, f in first.items()}
    log(f"issuer lookups: {sum(last_seen[k] > capped[k] for k in first)} eras asked at two dates, "
        f"{sum(f.fallback is not None for f in first.values())} weak answers kept aside")
    passes = EraIssuers(record, resolver.frequency_candidates)
    tickers = {e.key: e.ticker for e in eras}
    checked = passes.check_names(eras, ftd, last_seen, answers)                                          # 2b
    for key, found in checked.items():
        answers[key] = TickerResolution(tickers[key], found.cik, None, found.source)
    log(f"name checks: {len(checked)} name-search answers replaced"
        + (f" ({', '.join(f'{k} -> {v.cik}' for k, v in sorted(checked.items()))})" if checked else ""))
    # The second pass with the capped dates, then with the followed ones, on the same first-pass answers: an era
    # the first run answers keeps that answer (rule B reads the 8-K filers of the 120 days before its date).
    ciks = {k: r.cik for k, r in answers.items()}
    by_cap, by_end = (passes.infer(eras, ftd, dates, ciks, handoffs) for dates in (capped, last_seen))
    inferred = {**by_end.inferred, **by_cap.inferred}
    disagreements = {**by_end.disagreements, **by_cap.disagreements}
    for key, found in inferred.items():
        answers[key] = TickerResolution(tickers[key], found.cik, None, found.source)
    for key, f in first.items():                 # a weak answer stands only where no pass inferred an issuer
        if answers[key].cik is None and f.fallback is not None:
            answers[key] = f.fallback
    log(f"resolver's second pass: {len(inferred)} issuers inferred, "
        f"{len(disagreements)} first-pass answers its CUSIP evidence contradicts")
```

and the rest of the function uses `inferred` and `disagreements` in place of `second.inferred`
and `second.disagreements`, and returns
`_Issuers(answers, issuers_by_era(ciks, issuer_names), capped, last_seen, names_degraded, {**checked, **inferred}, disagreements, set(passes.degraded))`
(the `ciks = {k: r.cik for k, r in answers.items()}` line that feeds `issuers_by_era` stays where
it is today, after the answers are final).

The function's docstring: replace "resolved at the era's last sighting (index snapshots can be
months apart, and the lookup's Form 25 search is anchored on this date)" with "resolved at two
dates, its capped date and the end of its own fails rows, one answer chosen
(`choose_first_pass`)", and say the second pass runs with each.

In `_resolve_securities`, the degraded check reads both dates:

```python
        if any(clients.resolver.is_degraded(e.ticker, day, name=e.name)
               for day in {found.capped[e.key], found.last_seen[e.key]}) or e.key in found.degraded:
```

The module docstring's line "each era's issuer CIK, asked at the era's last sighting
(`era_last_seen`) ..." becomes "each era's issuer CIK, asked at the era's capped date and at the
end of its own fails rows (`era_capped_seen`, `era_last_seen`; `choose_first_pass`) ...".

Any other code that builds an `_Issuers` (search the package and the tests) passes `capped` too.

- [ ] **Step 7: The two tests that call `era_last_seen` bare**

`tests/test_issuer_code.py` lines 47 and 83 build `last_seen` with
`{e.key: era_last_seen(e, ftd) for e in refined}`, which is not bounded by the ticker's next era.
Change both to `last_sightings(refined, ftd)` and the import to match.

- [ ] **Step 8: Run everything**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: every test passes (3,894 passed and 44 xfailed before this task, plus the new ones).
The golden replay (`tests/test_golden_events.py`) stays green; a case that changes stops the
task. An existing test whose expectation changes because an era is now asked twice (a spy that
lists the resolver's calls, a memo file's keys) is updated to the two dates, and the report
lists each such change with its old and new value.

- [ ] **Step 9: Docs**

`docs/architecture.md`, the `identity.py` and `ticker_resolver.py` entries, and
`docs/data-flow.md`, where the issuer lookup's date is described (search both files for "last
sighting" and for the sentences Task 2 added): say that an era is asked at its capped date and
at the end of its own fails rows, give the rule of the choice in the words of
`choose_first_pass`'s docstring, name `WEAK_SOURCES`, and say the second pass runs with each
date. Keep the wording plain and do not restate what the code already says twice.

- [ ] **Step 10: Commit**

```bash
git add src/delist_detection/identity/identity.py src/delist_detection/identity/ticker_resolver.py tests/test_security_master.py tests/test_resolver_renamed.py tests/test_issuer_code.py docs/architecture.md docs/data-flow.md
git commit -m "The issuer is asked at the capped date and at the end of the line, and the answer whose name agrees stands"
```

---

### Task 5: Parity checkpoint after the rework (network)

The controller runs it, as Task 3. The reference for the full run is Task 3's "before" run (the
code before Task 2, no resolver memo): the offline replay of the rule gave the same issuer for
every era but WFT@2009-03-20.

- [x] **Step 1:** make sure no other SEC client is running (Task 3, Step 1).
- [x] **Step 2:** the full input at Task 4's commit on a copy of the cache the earlier full run
  left, then the seeds on a copy of the cache that run leaves (Task 3, Step 3's commands).
- [x] **Step 3:** judge the full run against the "before" run: every era's issuer (expected: only
  WFT@2009-03-20, to 1453090), the parity script's lists between the two, and the scorecard lines
  that differ. Anything else that moved is reviewed against EDGAR and the truth sets before the
  task goes on (Task 3, Step 4's rule).
- [x] **Step 4:** the parity numbers, full against seeds, and the check of the 22 tickers
  (Task 3, Step 5). Then `--write-floor`.
- [x] **Step 5:** record the numbers under "Checkpoints" and commit `data/seeds_parity.json`
  with the plan, message "Seeds-only parity after S1: the floor".

---

### Task 6: A weak answer stands only when the era's own fails rows fit it

Checkpoint 2 found that the resolver's name-mismatch answers are almost always wrong (16 of 16
from the 8-K frequency tier, about 37 of 43 from the Form 25 tier). Task 4 keeps such an answer
aside and lets it stand when no pass infers an issuer, unchecked. A wrong issuer is worse than
none: the delisting search then reads another company's filings (XP's "expiration" ending in
the seeds run; US Bancorp's and C3 AI's blank endings in the full run, whose issuers are Prologis
and an ETF trust). The second pass already has the test for "is this company the issuer of
these rows": guard G's row test (`EraIssuers._fits_rows`). A weak answer must pass it.

This task comes before the derived eras of Task 7: a derived era is looked up under a fails
description, where a name mismatch is likely.

Expected in the full run: AI@2021-06-30 and USB@2008-01-16 lose a wrong issuer (to none);
AZPN's weak answer (AspenTech, right) stands if its rows fit. Expected in the seeds run: XP, TT,
AI, ANN and MEL lose a wrong issuer.

**Files:**
- Modify: `src/delist_detection/identity/identity.py` (`EraIssuers.rows_fit`, the fallback loop in
  `_resolve_issuers`, its log line and docstring)
- Modify: `tests/test_resolver_renamed.py`
- Modify: `docs/architecture.md` (the `identity.py` entry, where Task 4 described the weak answer)

**Interfaces:**
- Consumes: `FirstPass.fallback`, `era_rows`, `EraIssuers._fits_rows`, `ERA_MIN_ROWS` (Task 4 and before).
- Produces: `EraIssuers.rows_fit(era: TickerEra, cik: int, rows: list[FtdRow]) -> bool`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_resolver_renamed.py`, beside `test_a_weak_answer_stands_when_nothing_is_inferred`
(which keeps passing: its era's rows are the answer's own company's):

```python
def test_a_weak_answer_whose_company_the_rows_do_not_fit_does_not_stand(matx_dates):
    """The era's fails rows say MATSON; the weak answer is another company (B). It is no issuer: the delisting
    search would read B's filings."""
    _, identity = _matx({MATX_CAP: (B, "efts_frequency_name_mismatch"), MATX_END: (B, "efts_frequency_name_mismatch")})
    assert MATX not in identity.issuers


def test_a_weak_answer_for_an_era_with_too_few_rows_does_not_stand():
    """An era with fewer than ERA_MIN_ROWS rows of its own has nothing to test a weak answer against."""
```

Write the second test's body with the file's fixtures: one observed ticker with fewer than three
own fails rows (CZN@2008-01-16, the one-day era of the earlier test, if it has fewer than three;
else build one with `_identify(rows=...)`), a lookup that answers a weak source with a CIK the
file's `_Edgar` serves, and the assertion that the era is not in `identity.issuers`. Add a third
test, `test_a_weak_answer_dropped_is_logged`, only if the stage's log is reachable from
`_identify`; otherwise leave the log untested and say so in the report.

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_resolver_renamed.py -q -o addopts="" -k "weak_answer"`
Expected: the two new tests fail (the weak answer stands today); the existing ones pass.

- [ ] **Step 2: The row test, public**

In `identity.py`, in `EraIssuers`, directly above `_guard`:

```python
    def rows_fit(self, era: TickerEra, cik: int, rows: list[FtdRow]) -> bool:
        """Whether the era's own fails rows are this company's: at least `ERA_MIN_ROWS` of them, and guard G's row
        test (`_fits_rows`). A weak first-pass answer must pass it to stand (`_resolve_issuers`): the resolver took
        it although its name does not agree with the observed one, and most such answers are another company's
        (US Bancorp's 8-K frequency answer was Prologis). A read that fails marks the era degraded, as the
        passes' own reads do."""
        self._reset()
        fits = len(rows) >= ERA_MIN_ROWS and self._fits_rows(cik, rows)
        self._mark(era)
        return fits
```

- [ ] **Step 3: The fallback loop**

In `_resolve_issuers`, replace the loop Task 4 added

```python
    for key, f in first.items():                 # a weak answer stands only where no pass inferred an issuer
        if answers[key].cik is None and f.fallback is not None:
            answers[key] = f.fallback
```

with

```python
    by_key = {e.key: e for e in eras}
    dropped = []
    for key, f in first.items():      # a weak answer stands only where no pass inferred an issuer and its rows fit
        if answers[key].cik is not None or f.fallback is None:
            continue
        if passes.rows_fit(by_key[key], f.fallback.cik, era_rows(by_key[key], ftd, last_seen[key])):
            answers[key] = f.fallback
        else:
            dropped.append(key)
    if dropped:
        log(f"weak answers dropped: {len(dropped)} whose company the era's own fails rows do not fit "
            f"({', '.join(sorted(dropped))})")
```

`passes.degraded` is read after this loop where `_Issuers` is built, so a failed read here
reaches the review rows as the passes' do; check that the `set(passes.degraded)` in the return
statement comes after the loop. Update the docstrings of `_resolve_issuers` and
`choose_first_pass` where they say a weak answer "stands only when no pass infers an issuer":
add "and the era's own fails rows fit it (`EraIssuers.rows_fit`)".

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_resolver_renamed.py tests/test_security_master.py tests/test_issuer_code.py -q -o addopts=""`
Expected: all pass.

- [ ] **Step 4: Run everything**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: 3,921 passed and 44 xfailed before this task, plus the new tests. The golden replay
stays green; a case that changes stops the task. An existing test whose era ended on a weak
answer and now has none is reported with its old and new value, not edited to pass, unless the
weak answer in it is plainly another company's.

- [ ] **Step 5: Docs and commit**

`docs/architecture.md`: in the sentence Task 4 added about a weak answer, add that it must also
fit the era's own fails rows.

```bash
git add src/delist_detection/identity/identity.py tests/test_resolver_renamed.py docs/architecture.md
git commit -m "A weak answer stands only when the era's own fails rows fit its company"
```

---

## S2: The line after a CUSIP change is a line of the run

Its step-by-step plan is written after Task 3, from that checkpoint's case lists. The outcome is
settled: the line that the fails rows show after a CUSIP change must exist as a security of the
run, with an issuer and sightings, so the handoff, successor, pricing and issuer-in-force stages
see it. Which code creates it is not settled, and has to be decided first.

**Step zero: why the existing stages miss these lines.** Two stages already follow a line past
the observations, and the trace did not examine either:

- Stage 4b, `identity/line_follow.py` (`follow_lines`), follows a security across a CUSIP or
  ticker change after its observations stop. It checks each step against the issuer's EDGAR
  record and OpenFIGI. It follows a step only when the old registrant carries on, or files its
  own successor registration, and no other registrant's 8-K12B or 8-K12G3 names the step.
- Stage 9 (`endings/successors.py`, `identity/added_securities.py`) adds a successor found by
  an 8-K12B search as an `AddedSuccessor`, a security of the run that no observation names
  (`TradingRecord.added`).

Most C2 cases are holding-company reorganizations and redomiciles, where a new registrant takes
over. That is stage 9's ground, so the first question is why stage 9 finds the successor in the
full run and not in the seeds-only run. For each C2 case still wrong after Task 3, write down
which of the two stages should have produced the line and why it did not. One trace already
says the 8-K12B search returned nothing for ANAT in the seeds-only run and did not find out why.

**Two candidate designs.**

- *A. Extend the existing stages.* Stage 4b or 9 produces the line as an added security. This
  reuses the corroboration those stages already do and the existing notion of an unobserved
  security. It needs C5 fixed first, since an added successor's ending is not valued today.
- *B. A derived era at the fails split.* `identity._split_era` keeps the part after a CUSIP
  change as an era of its own. This is what the rough version measured. It rests on the fails
  description alone, and it needs a marker threaded through every reader of an era's
  observations.

Choose after step zero. Prefer A unless step zero shows the existing stages cannot see these
steps.

**Step zero's outcome (2026-10-10; evidence in the session's scratch folder, summarized here).**

- The full run gets the line after a CUSIP change as an observed era of its own in all but about
  four cases. The old line's ending then becomes a continuation by a handoff (the successor's
  8-K12B or 8-K12G3: 12 cases; timing and the same CIK: 6) or by R1's terms check on the in-run
  line (8). No full-run case rests on `line_followed`.
- In the seeds run stage 4b was asked about 21 of the 22 cases a continuation reads as a merger.
  It refused 14 as `merged_out` (another registrant took over: the refusal is right) and nothing
  after it picks the new line up: the merger row is not searched for a successor
  (`successors.py:166`), and the handoff pairs read observed securities only
  (`pipeline.py:935`). It followed 5 (TEAM, LSXMA, LSXMK, FWONA, FWONK) and the link is skipped
  because the row is a merger (`_line_successor_links`, `pipeline.py:719`). FERG was refused
  `name`, APO `other_registrant`; AMSG's new line trades under another ticker.
- The new line is an added acquirer with no history and no ending in 11 cases and is nowhere in
  8. STE, DTV and AMSG have no 8-K12B: only an in-run line can carry them.
- C5 is confirmed: an added successor's ending is created after the valuation stage, gets no
  value and reads `confirmed` at an assumed par (NLSN, NRF, XL in the seeds run).
- How many eras design B would derive, by what stage 4b decides on the same step today:

  | Stage 4b today | Seeds | Full |
  | --- | --- | --- |
  | followed, the same security | 127 | 57 |
  | followed, a line successor | 21 | 4 |
  | refused `merged_out` | 37 | 8 |
  | refused `name` | 12 | 0 |
  | refused `other_registrant` | 3 | 0 |
  | refused `no_filing`, `bankruptcy`, `unsettled` | 11 | 6 |
  | not asked | 60 | 37 |
  | all | 271 | 112 |

  Design B as written would take over 148 steps stage 4b follows today in a seeds run and 61 in
  the full run (32 passing diagnosis cases and 8 golden cases are on those securities), and would
  add 43 securities to the full run, one of them a reused ticker (SE).

**The design chosen.** Neither A nor B as written. A line is derived only for a step stage 4b
refuses because another registrant took over, and it is made an era-born security so the later
stages treat it as they treat an observed second line in a full run. Stage 4b keeps every step
it follows. In order:

1. Task 6: a weak issuer answer must fit the era's own fails rows (checkpoint 2's finding; a
   derived line is looked up under a fails description).
2. The link of a followed line successor also takes a merger row (TEAM, LSXMA, LSXMK, FWONA, FWONK).
3. C5: the endings of added successors are valued.
4. The derived line for a step refused as `merged_out`, `other_registrant`, or `name` when the
   new line's description names the old issuer by more than a generic word.
5. The parity checkpoint again.

The step-by-step tasks for 2 to 5 follow Task 6 below once written. The text under "The rule, if
B is chosen" and "What the rough version got wrong" still binds the derived line: its own name
and issuer, no pin copied, no echo-table row, `observed=false`, takeover against continuation
(WEN, TCF) tested first, and a parity number for the `observed` flag.

**The rule, if B is chosen.** A part of the ticker's fails rows with no observation in it becomes
an era when all of these hold:

1. it follows a part of the same era that has an observation, with only CUSIP changes between
   them (no gap cut);
2. its kept CUSIP's description names the era's issuer. `description_matches` accepts one shared
   word and, by default, an empty comparison (`empty=True`), so the rule must call it with
   `empty=False` and say how many words must match: "FOX CORP" matches "TWENTY FIRST CENTURY
   FOX" on one word;
3. it is not before the era's first observation;
4. its rows are not inside the window of the ticker's next era. `refine_eras` shows the rows
   between two eras to both, so without this the derived era duplicates the next era's head.

A part that fails any of them is dropped, as today. Chains are followed (an observed part, then a
derived one, then another).

**What a derived era carries, if B is chosen.** One observation marked as derived, dated at the
first row of its CUSIP run, named by the fails description's name part. No pin: `_split_era`
builds eras with `replace(era, ...)`, which would copy the caller's CIK or `sec_id` pin onto a
line the caller never pinned. Its `ftd_cusips` is its own run. Its last-seen date comes from
`last_sightings` (S1), so it runs to the end of its own rows.

**What the rough version got wrong (measured, 73 seed rows).** The step-by-step plan must cover
each with a test:

1. *Issuer.* The followed line was looked up under the predecessor's name. The new Envision line
   (BBG00D3CHRC0) took old Envision's CIK 1578318 in place of 1678531, and old EVHC then read as
   a continuation. The derived line's name and issuer come from its own description and CUSIP.
2. *Name match.* `names_agree` does not read fails abbreviations ("AMERICAN NATL GROUP",
   "MYLAN N V", "ENDO INTL PLC"), so ANAT, MYL, ENDP and FERG were not followed. Use
   `description_matches`.
3. *Echo tables.* The made-up observations appeared in `observation_map.csv` and
   `contract/seeds.csv` (119 rows in place of 74) and their securities counted as observed (99 in
   place of 66). `history.observation_map_rows` iterates `era.observations`, so derived
   observations must be marked (a `derived` field on `Observation`, default False) and skipped
   there, in `observation_conflicts`, and wherever a seed's verdict is computed. A security all of
   whose eras are derived is `observed=false`. `SecurityContexts.observed`, `TradingRecord.observed`
   and `measurement/lifecycle.py` read that flag: check each. Other readers of an era's
   observations to check: the backfill eligibility in `pipeline._dead_before_sighting`, the
   issuer sightings built for the issuers-in-force stage (they take the observation's name, which
   here would be an abbreviated fails description), the ticker sightings in `identity/history.py`,
   and the foreign-ticker check in `identity/security_master.py`.
4. *Takeover against continuation.* A derived line that begins as another security ends is a
   candidate for both. `handoffs.decide_handoff` already returns a takeover when the new line
   traded before under another ticker (`existed`) or its issuer is an older company (`older`),
   and it returns a continuation on timing only when the issuer is the same or there is a
   `cusip_switch`. So WEN (Triarc traded as TRY) and TCF (Chemical traded as CHFC) may already
   come out right, and EVHC went wrong because the followed line had the wrong issuer. Write the
   WEN and TCF tests first, and change `decide_handoff` only if one fails.
5. *The parity script.* Add a number for securities whose `observed` flag differs between the
   two runs, since both designs make the followed line unobserved in the seeds-only run and
   observed in the full run.

**Existing test that changes under design B.** `tests/test_security_master.py`
`test_refine_eras_ignores_short_cusip_runs_and_obs_less_sides` asserts that a CCC run with no
observation after it is not created. Under the rule it is created (same description, follows by
a switch). Its expected eras become three.

**Cost of design B.** In the 73-seed test the eras after the fails split went from 71 to 116. Eras that
resolve to one FIGI merge (`build_securities`), so most of these add no security, but each is
resolved and searched. Measure SEC requests and wall time at S2's checkpoint.

**Acceptance (from `findings.md`, C2).** After S2 none of these is in the parity case lists:
ARRS, STE, CR, BG, AVGO, CI, MRVL, APO, DKNG, NCNO, TEAM, AZPN, FWONA, FWONK, DTV, ATVI, CLWR,
ALEX, SPB, CIT, DOW, MRK, FOXA (the new line exists), ANN, EVHC, AMSG, ANAT, MYL, ENDP, FERG,
WFT, MNST, NE, NRF, NLSN, TCF, WEN, MIR, TWC, LVNTA. The full run must still pass its own gate.

## S2, step by step: Tasks 7 to 15

**The controller's rulings on this section (2026-10-10).**

- *Decision (e), run time.* The loop is built as written here (repeat the identity stage and stage 4b until a
  round derives nothing). Its measured cost is one more stage 4b pass per round: about 100 s on the full input and
  180 s on the seeds input. That is accepted for the checkpoint, so that what the derived lines change is measured
  on the simplest code. After Task 15 a further task makes stage 4b ask again only about the securities a round
  touched (a derived era joined them, or the new CUSIP of one of their steps is now a derived line's), checked by
  the tables being byte-identical to the simple loop's. The hoist in `renamed_cusips` goes into that task too.
- *Decision (b) against the test marked "Must not change (WCN, AAN)".* The test is rewritten as Task 7 says. WCN and
  AAN are refused `merged_out` by stage 4b and have no line successor, so the ruling that a real merger takes no
  line successor still holds for them; a merger whose payout the gate reconciled also stands.
- *The warm fails index (open point 2).* Accepted for the checkpoint: IAC@2012-06-29 and IACI@2008-01-16 move from
  the placeholder to the FIGI line stage 4b folds it into anyway. Task 15 checks that the published ids are the same.
- *The review rows of a derived step (open point 6).* No new flag: the run log names the derived pairs, and
  `securities.csv` shows the line with `observed=false`.
- Task 6 is committed (`0ec338f`), so Task 10 may start when its turn comes.


Written on 2026-10-10 against commit `043f01d` plus Task 6 as the other agent had it in the worktree (uncommitted: `EraIssuers.rows_fit`
and the fallback loop of `_resolve_issuers`; Task 10 below edits other functions of `identity.py`, so it starts after Task 6 is
committed). Every function, field and line named here was opened in the code. Every test below was run on a prototype of the
tasks (a copy of the code at `26eefdb` with these changes, in the session's scratch folder) and passes there; the
prototype's whole suite (with the committed `output/`) failed in exactly the four tests the tasks name (and three
`test_loop_round.py` tests that read the repo's `.claude` workflow files, which the copy lacks); the golden replay, the
diagnosis-truth cases, the import closure and the committed-output tests stayed green.
Line numbers are not given: find each function by name.

| Task | Title |
| --- | --- |
| 7 | A merger row takes the followed line's successor (decision b) |
| 8 | The endings of added successors are valued (C5, decision c) |
| 9 | A derived observation, and the readers of an era's observations that skip it |
| 10 | The identity stage keeps an approved part of the fails rows as a derived era |
| 11 | Stage 4b says which refused steps are lines; the test of a name |
| 12 | The run asks again with the derived lines |
| 13 | A derived line that begins as another security ends: takeover or continuation (WEN, TCF) |
| 14 | The parity script counts securities whose `observed` flag differs |
| 15 | Parity checkpoint after S2 (network) |

### Decision (e): how the derived line is made

**Chosen: (1), repeat the identity stage with the refused steps passed in.** It reuses every stage unchanged, so a derived
line is an ordinary era-born security by construction, and the prototype shows it on both inputs. The measurement does not
meet the brief's bar as stated, and the reason is not the identity stage; both facts follow.

Measured offline with the replay harness (code at `26eefdb` plus the prototype, caches cloned, `--sec-workers 1`, no
network; 3 rounds on the seeds input, 2 on the full):

| Run | Round | Identity stage (1 to 4) | Stage 4b | Round total |
| --- | --- | --- | --- | --- |
| seeds | 0 (as today) | 47.5 s (of which opening the index 12.9) | 63.5 s | 111 s |
| seeds | 1 (50 pairs derive 49 eras) | **15.7 s** | 72.0 s | 87.7 s |
| seeds | 2 (CCE's second step; nothing new) | **15.3 s** | 76.0 s | 91.3 s |
| full | 0 | 62.4 s | 80.3 s | 142.7 s |
| full | 1 (8 eras; nothing new) | **20.0 s** | 77.7 s | 97.7 s |

- **The repeat of the identity stage, with the fails index built once and reused, costs 15 to 20 s**: under the bar. What
  it needs is `identify(..., derive=, ftd=)` (Task 10): `_refine` opens the index only when none is given
  (1.8 s instead of 12.9), the issuer lookups hit the resolver's memo (7.7 s instead of 21.1) and `_security_cusips` finds every CUSIP's rows held.
- **A round must also run stage 4b**, because the refusals that earn the next pairs are 4b's, and 4b costs 72 to 78 s warm, as much as
  cold (its work is per security, not per fails file: 768 lines that stopped each scan the fails rows around their end,
  `line_follow.renamed_cusips`, and every issuer's record is read). A profile of a warm pass put most of its time in that
  scan's `_first_word` regex (28 million calls); hoisting the names' first words out of the row loop (below) is an
  equal-result change that measured only 10 s per pass (round 0: 63.5 to 55.6 s, round 1: 72.0 to 61.3 s), so 4b's warm cost is
  not one loop.
- Total offline cost of (1) as the tasks build it: seeds 290 s against 111 s (+179 s for two repeat rounds), full 242 s against 143 s (+99 s for one
  repeat round). A live run adds the requests of the derived eras' lookups: 98 SEC and up to 4 OpenFIGI requests (seeds), 27 SEC and 2 OpenFIGI (full) in
  the harness's count of misses, about 12 s at 8 requests a second.
- The brief's bar (a repeat of stages 1b to 4c under about 60 s) is therefore met by the identity stage (15 to 20 s) and missed by the
  whole round (88 to 98 s), because of 4b. (2), adding the era after stage 4b to the identity stage's outputs in place, would
  have to resolve its issuer and FIGI outside `identify` (a second path through `_resolve_issuers`, `_resolve_securities`,
  `build_securities` and `_security_cusips`) and would still need a stage 4b pass over the derived lines for chains. I judged that worse than the
  cost; the controller can overrule, and Tasks 9, 10, 11 and 13 serve either design (only Task 12, the loop, differs).

*Equal-result hoist in `renamed_cusips`* (`line_follow.py`; optional, not a task): replace the generator inside the loop by a lookup of the row's
first word in a dict of the names by first word, built once:

```python
    by_first: dict[str, list[str]] = defaultdict(list)        # the names by their first word, computed once
    for n in names:
        by_first[_first_word(n)].append(n)
    rows: dict[str, list[str]] = defaultdict(list)
    for r in ftd.every_row(date.fromisoformat(lo), date.fromisoformat(hi) + timedelta(days=NAME_DAYS)):
        if r.cusip not in cusips and is_line_symbol(r.symbol) \
                and any(description_names(r.description, n) for n in by_first.get(_first_word(r.description), ())):
            rows[r.cusip].append(r.date)
```

With the hoist the seeds rounds measured 104.6 s (round 0) and 77.0 s (round 1: identity stage 15.7 s, stage 4b 61.3 s); the
third round is as the second, so the seeds input costs about 260 s against 105 s, and the full input about 220 s against 135 s. The
whole round stays above the brief's 60 s; the identity stage alone is a quarter of it.

### Condition 2 and the test of a name (decision g)

The brief's four conditions are three structural ones (Task 10: follows an era of its gap group; not before the era's first
observation; not the next era's CUSIP) and condition 2, which Task 11 decides with `names.description_names_issuer`
against `derived_lines.old_line_names` (the old line's observed names and every EDGAR name its issuer carried until the day
before the step). The test is `description_names` (as many issuer words as the shorter side has, up to two) **and at least one of
them a word as spelled**: `description_names` and `description_matches(empty=False)` both read SEA as SPECTRA written short.

| Pair (description / old name) | `description_matches(empty=False)` | `description_names` | `description_names_issuer` |
| --- | --- | --- | --- |
| CIGNA CORP NEW / CIGNA CORP (CI) | yes | yes | yes |
| AMERICAN NATL GROUP / AMERICAN NATIONAL INSURANCE (ANAT) | yes | yes | yes |
| MYLAN N V / MYLAN INC. (MYL); ENDO INTL PLC / ENDO PHARMACEUTICALS (ENDP); ARRIS INTL / ARRIS INTERNATIONAL (ARRS) | yes | yes | yes |
| BUNGE GLOBAL / BUNGE LIMITED (BG); STERIS PLC / STERIS (STE); DIRECTV / DIRECTV GROUP (DTV); FERGUSON ENTERPRISES / FERGUSON PLC (FERG) | yes | yes | yes |
| **SEA LTD ADR / SPECTRA ENERGY CORP (SE 2017, a reused ticker)** | **yes** | **yes** | **no** |
| LIBERTY GLOBAL / TELEWEST GLOBAL (VMED 2013, one generic word) | yes | no | no |

On every refused `merged_out`, `other_registrant` and `name` switch step of both inputs (`Lines.refused` of round 0; the old
line's names are the observed ones plus the issuer's EDGAR names, all of them for the first three columns and those until the step for the last):

| Refusal | Steps (seeds / full) | `description_matches` accepts | `description_names` accepts | `description_names_issuer`, all names | chosen: names until the step |
| --- | --- | --- | --- | --- | --- |
| `merged_out` | 42 / 13 | 42 / 13 | 42 / 13 | 42 / 13 | 42 / 13 |
| `other_registrant` | 5 / 2 | 5 / 2 | 5 / 2 | 5 / 2 | 3 / 0 |
| `name` | 23 / 5 | 13 / 1 | 11 / 0 | 10 / 0 | 10 / 0 |

- **Refused by the chosen test** (seeds unless marked): `name`: CELG (Bristol-Myers CVR), NYX (ICE), ESRX (Cigna), XL (XL-Group: no issuer word), VMED (Liberty Global), COV (Medtronic), TWC (Charter), IPHI (Marvell), TWOU ("2U INC COM STK NEW": no issuer word), GRUB (Just Eat), WW ("WW INTL INC COM": none), ABI ("BIOSSYSTEMS" misspelt), ANN (University Bancorp, a wrong issuer); `other_registrant`: LGFA, LGFB (STARZ ENTMT CORP: the issuer's name until the step was Lions Gate; both inputs). Of these, CELG, NYX, ESRX, COV, TWC, IPHI, GRUB, VMED are the acquirer's line (a takeover: not this line's successor), and XL, TWOU, WW, ABI, LGFA, LGFB are real continuations the test cannot see; they stay as today (Open point 7).
- **Accepted** (seeds): all 42 `merged_out`, `other_registrant` WEC, CHTR, APO, `name` IAC (twice), BLK, IR, ENR, VNOM, FERG, LLYVA, LLYVK, ALEX. Whether a pair is derived also needs the three structural conditions: of the 55 accepted seeds steps, 57 `(ticker, CUSIP)` pairs (one per ticker of the line) earned 49 eras in round 1, one more (CCE's second step) in round 2; of the full run's 13 accepted `merged_out` steps, eight have a part with no observation, and they are the brief's eight (AAN, BXS, CCE 2016, GCI, SDRL, UNIT, WCN, WE).
- **Derived lines the rule gives**: seeds input **50 derived eras forming 34 securities of their own** (16 eras resolve to the FIGI of an era already in the run, among them ACN, CB twice, CFFN, CLWR, ENR, ICE, IR, MDT, MYL, PRGO, UNIT, WE, WEC, IAC); securities 2,153 to 2,187. Full input **8 derived eras, 5 securities of their own** (UNIT and WE join the old line's FIGI); securities 2,201 to 2,206.

### Every reader of an era's observations and of a security's `observed` flag

Decision per reader: **skip** (a derived observation is not the caller's), **honour** (the derived era is an ordinary era to it), **unaffected**.

| Reader | Reads | Decision | Why, and the test |
| --- | --- | --- | --- |
| `TickerEra.names`, `name`, `cusips`, `cik_pin`, `sec_id_pin` (`observations.py`) | every observation | honour | the derived observation carries a name (its fails description), no CUSIP, no pin: the era is looked up under its own name and never takes the old line's pin (Task 9 step 1; Task 10) |
| `_split_era`, `refine_eras` (`seen_on`, `contested`) | the caller's input eras | unaffected | a derived era is made by `_split_era`, never given to it |
| `capped_sightings`, `last_sightings`, `era_rows`, `_own_rows` | `era.first`, `last`, `ftd_cusips`, `names` | honour | the derived era follows its own CUSIP's rows to their end, as a seed does |
| `_resolve_issuers`, `EraIssuers`, stage 2b | `e.name`, `e.cik_pin`, `e.first` | honour | one lookup under its own description and its CUSIP's rows; Task 6's row check holds a weak answer |
| `cusip_handoffs`, `FigiResolver`, `candidate_cusips`, `unconfirmed_eras`, `foreign_ticker_eras` | era CUSIPs, names, span | honour | an ordinary era resolved by its own CUSIP (the whole-run test of Task 12) |
| `build_securities` | the eras | **changed** | `Security.observed` is True when any of its eras is not derived (Task 9) |
| `observation_conflict_review`, the `observation_conflicts` calls in `pipeline._observation_map` and `_other_issuers` | observations of all eras | skip | a conflict is about two names the caller gave one ticker on one day (Task 9) |
| `history.ticker_sightings`, `cusip_sightings` | observations as sightings | skip | else the derived line's ticker range would claim an observation, and a lone sighting (Task 9; the whole-run test: its range's source is `ftd`) |
| `history.observation_map_rows` | observations | skip | `observation_map.csv` is the caller's join surface (invariants), and `contract/seeds.csv` and stage 10c3's issuers-in-force are built from it |
| `pipeline._dead_before_sighting` | the first observation of a dead security | skip | a derived line has no caller sighting to be "dead before" (Task 9, the 5b test) |
| `pipeline._other_issuers` (4c, R5) | sightings with their era's CIK | skip | its one observation is named by the fails description the issuer was found under: it would confirm itself (Task 9) |
| `pipeline._issuers_in_force` (10c3) | `observation_map` rows | unaffected | reads the echo table, so a derived line has no timeline and `contract.security_history_rows` takes `securities.csv`'s CIK for it |
| `TradingRecord.observed`, `SecurityContexts.observed` | `eras[-1].ticker`, `name`, `first`, `last` | honour | like a seed (`known_from` is its first fails row); its expected name is its fails description |
| `handoffs.find_handoffs` (via `ticker_sightings`) | sightings | honour | the derived line's sightings are fails rows, so it pairs with the line before it (Task 13) |
| `Security.row()` (securities.csv), `measurement/scorecard` R1.2, `measurement/lifecycle.observed()`, `outputs/verdict` rules F and the security reason | `observed` | honour (False) | a derived line leaves the "observed" counts, the lifecycle set and rule F (closed with no ending) and the "FIGI without CIK" security reason, and gets its verdicts from its endings; the added successors and acquirers are already `observed=false` in these |
| `Histories` (ticker_history, cusip_history) | all `securities` | honour | the derived line has rows (source `ftd`) |

### Pre-flight: tasks that share a file or an interface

| Pair | One produces | The other consumes |
| --- | --- | --- |
| 7 and 8 (`pipeline.py`, `_run`) | 7: `_find_successors(..., values)`, `_link_successors(..., payouts)` | 8: `values` after the 9d absorb; independent blocks of `_run` (stage 9 call, 9d block) |
| 8 and 12 (`tests/test_pipeline.py`) | 8: `_line_run(..., llm=None)` | 12: the same helper in the whole-run tests |
| 6 and 10 (`identity.py`) | 6: `rows_fit`, the fallback loop in `_resolve_issuers` | 10: `identify`, `_refine`, `_split_era`, `refine_eras`; other functions, but the same file: 10 starts after 6 is committed |
| 9 and 10 | 9: `Observation.derived`, `TickerEra.derived` | 10: builds eras with derived observations |
| 10 and 11 | 10: `identify(derive=, ftd=)`, `refine_eras(derive=)` (pairs `(ticker, cusip)`) | 11: `derivable(...) -> set[tuple[str, str]]` (the same pairs) |
| 11 and 12 | 11: `Lines.refused`, `derivable` | 12: `identify_with_lines` reads both |
| 7, 12 and `tests/test_pipeline.py` | 7 rewrites two tests; 12 rewrites four | each leaves the suite green on its own; both edit different tests |
| 12 and 13 | 12: derived securities in `_run` | 13: tests of the handoff stage on the shapes a derived line gives; no code |
| 9 and 14 | 9: `observed` false on a derived line | 14: reads `securities.csv`'s `observed` column |
| 11 and 12 (`derived_lines.py`) | 11 creates the file with `derivable`; 12 adds `identify_with_lines` | the imports of 12 are listed in its Step 2 |

### Existing tests the tasks change (found by running the prototype's whole suite)

- Task 7: `test_distress_expiration_and_merger_endings_at_the_switch_take_no_line_successor[merger-231]` (its merger case moves out), `test_a_line_successor_is_never_added_for_an_ending_that_does_not_need_it` (replaced by the continuation test).
- Task 12: `test_a_registrant_that_merged_out_at_the_switch_is_not_followed` (UNIT 2025; the new CUSIP's rows are now a derived security), `test_a_same_ticker_acquirer_is_never_the_target_itself` (Ashland; its delistings are now two), and the fixture `_same_ticker_acquirer_run` (the SEC ticker map's holder needs a filing history to have "existed" when the derived era began; this serves `test_a_same_ticker_acquirer_takes_the_sec_ticker_maps_holder_not_the_targets_cik`).
- `test_refine_eras_ignores_short_cusip_runs_and_obs_less_sides` does **not** change (the older text under "Existing test that changes under design B" does not apply to the design chosen: with no approved pair the CCC part is dropped as before).

---
### Task 7: A merger row takes the followed line's successor (decision b)

TEAM, LSXMA, LSXMK, FWONA and FWONK: stage 4b followed the step (the old registrant carries on) to a CUSIP with its
own composite, so `follow_lines` made a `LineSuccessor`, but the classifier called the Form 25 at the switch a merger,
and `_line_successor_links` only takes a row that awaits a successor or is `unknown`. The full run reads the five as
continuations. After this task the link also takes a merger row, as a rewrite (`rewrites.continuation`, which needs the
run's `MergerValues` to drop the merger's value). A merger whose payout the gate reconciled stands, as it stands against
a handoff by timing (`handoffs.apply_handoffs`' `reconciled`). The mergers stage 4b refuses (WCN, AAN: `merged_out`)
have no line successor, so they are untouched.

**Files:**
- Modify: `src/delist_detection/pipeline.py` (`_line_successor_links`, `_find_successors`, `_link_successors`, the
  `_find_successors` call in `_run`)
- Modify: `tests/test_pipeline.py`
- Modify: `docs/architecture.md` (the stage 9 entry in "The run: pipeline.py"), `docs/invariants.md` ("A line is followed
  past its observations")

**Interfaces:**
- Consumes: `LineSuccessor` (stage 4b), `MergerValues.reconciled(key) -> bool`, `rewrites.continuation(..., payouts=)`.
- Produces: `_line_successor_links(delistings, securities, acquirers, line_successors, ftd, found, payouts: MergerValues | None = None) -> None`,
  `_find_successors(..., sec_cusips=None, values: MergerValues | None = None) -> _Successors`,
  `_link_successors(delistings, successors, payouts: MergerValues | None = None) -> None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pipeline.py`, replace the parametrization of the test that pins the old behaviour (its merger case is the
one that changes):

```python
@pytest.mark.parametrize("bucket,code", [(CrspBucket.LIQUIDATION, 450), (CrspBucket.COMPLIANCE_FAILURE, 560),
                                         (CrspBucket.EXPIRATION, 600)])
def test_distress_and_expiration_endings_at_the_switch_take_no_line_successor(bucket, code):
```

(the body is unchanged). Directly below it add:

```python
def _switch_securities():
    return {"BBGRS01": Security("BBGRS01", 4242, "COMMON", "REVERSE SPLIT CO", "", True, "cusip")}


def test_a_merger_at_the_switch_takes_the_line_successor_as_a_continuation():
    """TEAM, LSXMA, LSXMK, FWONA, FWONK (seeds-only parity S2): a Form 25 the classifier read as a merger, at a switch
    stage 4b followed to a CUSIP with its own composite, links to that composite."""
    from delist_detection.sources.ftd import FtdIndex
    d = _unit_delisting("BBGRS01", CrspBucket.MERGER, 231, [])
    found = pipeline._Successors()
    pipeline._line_successor_links([d], _switch_securities(), {}, {"BBGRS01": _line_successor("BBGRS01")},
                                   FtdIndex(), found)
    assert found.links == {d.key: ("BBGRSNEW1", "line_follow")}
    assert d.key in found.rebucketed and "BBGRSNEW1" in found.added


def test_a_merger_made_a_continuation_by_the_line_link_loses_its_value_and_payout_flags():
    from delist_detection.terms.merger_value import MergerValue, MergerValues
    from delist_detection.vocabulary.crsp_codes import CONTINUATION_CODE
    d = _unit_delisting("BBGRS01", CrspBucket.MERGER, 231, ["merger_at_par"])
    values = MergerValues({d.key: MergerValue(d.key)})
    found = pipeline._Successors(links={d.key: ("BBGRSNEW1", "line_follow")},
                                 rebucketed={d.key: "line follow, 8-K 2012-09-24: x"})
    pipeline._link_successors([d], found, values)
    assert (d.record.bucket, d.record.crsp_code, d.record.successor_sec_id) == (
        CrspBucket.EXCHANGE_TRANSFER, CONTINUATION_CODE, "BBGRSNEW1")
    assert "merger_at_par" not in d.flags and "line_continuation" in d.flags
    assert values.get(d.key) is None


def test_a_merger_whose_payout_reconciled_takes_no_line_successor():
    from delist_detection.sources.ftd import FtdIndex
    from delist_detection.terms.merger_value import MergerValue, MergerValues
    d = _unit_delisting("BBGRS01", CrspBucket.MERGER, 231, [])
    values = MergerValues({d.key: MergerValue(d.key, payout=10.0)})
    found = pipeline._Successors()
    pipeline._line_successor_links([d], _switch_securities(), {}, {"BBGRS01": _line_successor("BBGRS01")},
                                   FtdIndex(), found, values)
    assert found.links == {} and found.added == {} and found.rebucketed == {}
```

Then replace the whole-run test `test_a_line_successor_is_never_added_for_an_ending_that_does_not_need_it` (its docstring
says a merger at the switch keeps its kind; the new rule says it does when 4b refuses the step, not when 4b follows it):

```python
def test_a_merger_at_the_switch_whose_registrant_carries_on_is_the_continuation_to_the_line_successor(
        fake_edgar, tmp_path):
    """TEAM, LSXMA, FWONA (seeds-only parity S2): a Form 25 the classifier read as a merger, at a switch stage 4b
    followed (a 10-Q follows it) to a CUSIP with its own composite, is the exchange transfer to that composite. The
    mergers 4b refuses (WCN, AAN: `merged_out`) keep their kind: the same-ticker acquirer tests below."""
    merger_8k = EdgarSubmission("0000004242-12-000040", "8-K", "2012-09-24", "2012-09-24", "2.01,3.01,5.01,9.01",
                                "m.htm")
    merger_f25 = EdgarSubmission("0000876661-12-000300", "25-NSE", "2012-09-24", "", "", "primary_doc.xml")
    fake_edgar.raws["0000876661-12-000300"] = LINE_F25
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, merger_8k, merger_f25, LATER_10Q],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    [d] = t["delistings"]
    assert (d["bucket"], d["successor_sec_id"]) == ("exchange_transfer", "BBGRSNEW1")
    assert "line_continuation" in d["review_flags"].split(";")
    assert {r["sec_id"]: r["observed"] for r in t["securities"]} == {"BBGRS01": "true", "BBGRSNEW1": "false"}
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py -q -o addopts="" -k "switch"`
Expected: the three unit tests fail (the first on `found.links == {}`, the other two with a `TypeError`: the functions
take no `payouts` yet) and the whole-run test fails on `('merger', '')`.

- [ ] **Step 2: Change the three functions**

In `pipeline.py`, `_line_successor_links`: change the signature and the gate, and the `unknown`-only rewrite:

```python
def _line_successor_links(delistings: list[Delisting], securities: dict[str, Security],
                          acquirers: dict[str, AddedSecurity], line_successors: Mapping[str, LineSuccessor],
                          ftd: FtdIndex, found: _Successors, payouts: MergerValues | None = None) -> None:
```

```python
        ls = line_successors.get(e.sec_id)
        if ls is None or not (awaits_successor(e) or e.record.bucket in (CrspBucket.UNKNOWN, CrspBucket.MERGER)):
            continue
        if e.record.bucket is CrspBucket.MERGER and payouts is not None and payouts.reconciled(e.key):
            continue                # a payout the gate reconciled with the last close stands against a timing link
```

```python
        if e.record.bucket in (CrspBucket.UNKNOWN, CrspBucket.MERGER):
            found.rebucketed[e.key] = (
```

and in its docstring replace "(`unknown`: GTES 2026's Form 25 at its redomicile)" by "(`unknown`: GTES 2026's Form 25 at
its redomicile; a merger: TEAM, LSXMA, FWONA, whose registrant carries on, unless its payout reconciled)" and "an
`unknown` row becomes the continuation" by "an `unknown` or merger row becomes the continuation".

`_find_successors`: add the last parameter and pass it on:

```python
                     sec_cusips: dict[str, list[str]] | None = None,
                     values: MergerValues | None = None) -> _Successors:
```

```python
        _line_successor_links(delistings, securities, acquirers, line_successors, ftd or FtdIndex(), found, values)
```

```python
    _link_successors(delistings, found, values)
    return found
```

`_link_successors`: take the payouts and pass them to the rewrite:

```python
def _link_successors(delistings: list[Delisting], successors: _Successors,
                     payouts: MergerValues | None = None) -> None:
```

```python
                continuation(d, sid, rule, reason=reason + note, confidence="medium", flag=LINE_CONTINUATION,
                             how=how or "", payouts=payouts)
```

In `_run`, the stage 9 call gains the values (they exist since stage 8):

```python
    successors = _find_successors(ctx, delistings, securities, search.sightings, {**values.added, **r1.added},
                                  lines.successors, ftd, sec_cusips, values)                        # 9
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py -q -o addopts=""`
Expected: all pass (prototype: 136 passed).

- [ ] **Step 3: Run everything**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: the suite's count before this task plus 2 (three new tests; the parametrization loses its merger case),
44 xfailed, golden replay green (a golden case that changes stops the task).

- [ ] **Step 4: Docs and commit**

`docs/invariants.md`, "A line is followed past its observations", last sentence: after "(an `unknown` row at the switch is
rewritten, `line_continuation`: it drops `no_evidence_default` and gets medium confidence)" add "; so is a merger row at
the switch when stage 4b followed the step (the old registrant carries on: TEAM, LSXMA, FWONA), unless its payout
reconciled with the last close". `docs/architecture.md`, stage 9 in "The run: pipeline.py": the same clause.

```bash
git add src/delist_detection/pipeline.py tests/test_pipeline.py docs/architecture.md docs/invariants.md
git commit -m "A merger row at a followed switch takes the line successor as its continuation"
```

---

### Task 8: The endings of added successors are valued (C5, decision c)

NLSN, NRF and XL in the seeds run: `_successor_endings` (stage 9d) finds the Form 25 of a successor the run added after
`_merger_values` (stage 8) ran, so its merger ending gets a close and no value, and reads `confirmed` at an assumed par:
a silent error. After this task the endings stage 9d adds go through `_merger_values` like any ending.

**Files:**
- Modify: `src/delist_detection/terms/merger_value.py` (`MergerValues.absorb`)
- Modify: `src/delist_detection/pipeline.py` (`_run`, the 9d block)
- Modify: `tests/test_merger_value.py`, `tests/test_pipeline.py` (`_line_run` gains `llm=None`)
- Modify: `docs/architecture.md` (stage 9d entry)

**Interfaces:**
- Consumes: `_successor_endings(...) -> _SuccessorEndings` (`.delistings`, `.securities`, `.cusips`),
  `_last_trade_closes(...) -> _Closes`, `_merger_values(ctx, delistings, securities, sec_cusips, ftd, closes: _Closes, overrides, answers, tol, sightings, ftd_lo) -> MergerValues`.
- Produces: `MergerValues.absorb(other: MergerValues) -> None` (takes `other`'s `records` and `added`; its review items stay the caller's).

- [ ] **Step 1: Write the failing tests**

In `tests/test_merger_value.py` (it imports `MergerValue`, `MergerValues`; add `from delist_detection.outputs.store import DelistingKey` if absent):

```python
def test_absorb_takes_the_records_and_acquirers_of_another_valuation_and_not_its_review_items():
    from delist_detection.outputs.review_triage import ReviewItem
    k1, k2 = DelistingKey("A", "2020-01-02"), DelistingKey("B", "2021-01-02")
    first = MergerValues({k1: MergerValue(k1, payout=1.0)}, review=[ReviewItem("A", "A", 1, "x", "y")])
    second = MergerValues({k2: MergerValue(k2, payout=2.0)}, added={"BBGACQ": object()},
                          review=[ReviewItem("B", "B", 2, "x", "y")])
    first.absorb(second)
    assert set(first.records) == {k1, k2} and set(first.added) == {"BBGACQ"}
    assert [r.sec_id for r in first.review] == ["A"]
```

In `tests/test_pipeline.py`, let `_line_run` carry an LLM double: add `llm=None` to its signature (after
`extra_obs=()`) and, directly after `index, clients = _index_clients(fake_edgar, [*obs, *extra_obs], rows, answers)`, add
`clients.llm_extractor = llm`. Then add (after `test_a_figi_line_whose_new_cusip_has_its_own_figi_ends_as_a_continuation_to_it`):

```python
class _CashLLM:
    """The LLM extractor double: every merger it is asked about was paid $40.90 in cash."""

    def __init__(self):
        self.asked = []

    def extract(self, record, security_name=""):
        self.asked.append((record.ticker, record.sec_id))
        return MergerTerms("cash", 40.9, None, "ACQUIRER CO", None, "high", "8-K:0000004242-14-000020", "")


def test_the_ending_of_a_line_successor_the_run_added_is_valued(fake_edgar, tmp_path):
    """C5 (NLSN, NRF, XL): the reverse split gives the line a CUSIP with its own composite (an added line successor);
    its 2014 merger is found by stage 9d, after the mergers were valued. It is valued all the same: the LLM is asked
    for it and the row carries the cash, not an assumed par."""
    switch_f25 = EdgarSubmission("0000876661-12-000300", "25-NSE", "2012-09-24", "", "", "primary_doc.xml")
    fake_edgar.raws["0000876661-12-000300"] = LINE_F25
    llm = _CashLLM()
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, switch_f25, LATER_10Q, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows(), llm=llm)
    row = next(r for r in t["delistings"] if r["sec_id"] == "BBGRSNEW1")
    assert (row["bucket"], row["delist_date"]) == ("merger", "2014-06-20")
    assert llm.asked == [("RS", "BBGRSNEW1")]
    assert (row["payout_per_share"], row["payout_source"]) == ("40.900000", "llm")
    assert "merger_at_par" not in row["review_flags"].split(";")
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_merger_value.py tests/test_pipeline.py -q -o addopts="" -k "absorb or line_successor_the_run_added"`
Expected: both fail (`AttributeError: ... 'absorb'`; `llm.asked == []`).

- [ ] **Step 2: `MergerValues.absorb`**

In `terms/merger_value.py`, in `MergerValues`, directly above `get`:

```python
    def absorb(self, other: MergerValues) -> None:
        """Take `other`'s records and acquirers (the valuation of endings found after this stage ran: stage 9d's added
        successors); its review items stay the caller's."""
        self.records.update(other.records)
        self.added.update(other.added)
```

- [ ] **Step 3: Value the 9d endings**

In `pipeline._run`, replace

```python
    if ends.delistings:
        delistings += ends.delistings
        closes.update(_last_trade_closes(ctx, ends.delistings, {**securities, **ends.securities},
                                         {**sec_cusips, **ends.cusips}, ftd, ftd_lo, overrides, prices).closes)
```

with

```python
    if ends.delistings:
        delistings += ends.delistings
        run_securities, run_cusips = {**securities, **ends.securities}, {**sec_cusips, **ends.cusips}
        ends_closes = _last_trade_closes(ctx, ends.delistings, run_securities, run_cusips, ftd, ftd_lo, overrides,
                                         prices)
        closes.update(ends_closes.closes)
        ends_values = _merger_values(ctx, ends.delistings, run_securities, run_cusips, ftd, ends_closes, overrides,
                                     prices, tol, search.sightings, ftd_lo)                     # 9d: C5
        values.absorb(ends_values)
        review += ends_values.review
        added.update(ends_values.added)
```

Update the `_run` comment/docstring of `_successor_endings` ("an 8-K12B successor ...") by one sentence: "Its endings are valued
with every other ending (`_run`)."

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_merger_value.py tests/test_pipeline.py tests/test_successor_endings.py -q -o addopts=""`
Expected: all pass (the `_successor_endings` tests call the stage directly and are untouched).

- [ ] **Step 4: Run everything, docs, commit**

Run the whole suite: expected previous count plus 2, golden replay green. `docs/architecture.md`, stage 9d: add "its mergers
are valued by `_merger_values` like any ending (C5)".

```bash
git add src/delist_detection/terms/merger_value.py src/delist_detection/pipeline.py tests/test_merger_value.py tests/test_pipeline.py docs/architecture.md
git commit -m "The endings of added successors are valued like any ending (C5)"
```

---
### Task 9: A derived observation, and the readers of an era's observations that skip it (decision d, the marker)

A line the library derives (Task 10) is an era with one observation that no caller made. This task adds the marker and
makes every reader in the table above decide. Nothing creates a derived era yet, so the suite does not move; the tests
build the eras by hand.

**Files:**
- Modify: `src/delist_detection/identity/observations.py` (`Observation.derived`, `TickerEra.caller_observations`, `TickerEra.derived`)
- Modify: `src/delist_detection/identity/security_master.py` (`build_securities`, `observation_conflict_review`)
- Modify: `src/delist_detection/identity/history.py` (`ticker_sightings`, `cusip_sightings`, `observation_map_rows`)
- Modify: `src/delist_detection/pipeline.py` (`_dead_before_sighting`, `_observation_map`, `_other_issuers`)
- Modify: `tests/test_observations.py`, `tests/test_security_master.py`, `tests/test_history.py`, `tests/test_pipeline.py`
- Modify: `docs/architecture.md` (`identity/observations.py`, `identity/security_master.py`, `identity/history.py`), `CONTEXT.md` ("Observation", new "Derived line"), `docs/invariants.md` ("`observation_map.csv` is the caller's join surface")

**Interfaces:**
- Produces: `Observation(..., sec_id=None, derived: bool = False)`; `TickerEra.caller_observations -> list[Observation]` (those not derived); `TickerEra.derived -> bool` (it has observations and every one is derived); `Security.observed` is True when any of the security's eras is not derived.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests of the marker**

In `tests/test_observations.py`:

```python
def test_an_era_of_derived_observations_is_derived_and_has_no_caller_observation():
    d = TickerEra("X", "2020-09-01", "2020-09-01", [Observation("X", "2020-09-01", "X CO NEW", derived=True)])
    c = TickerEra("X", "2020-01-15", "2020-06-30", [Observation("X", "2020-01-15", "X CO"),
                                                    Observation("X", "2020-06-30", "X CO")])
    assert (d.derived, c.derived) == (True, False)
    assert d.caller_observations == [] and c.caller_observations == c.observations
    assert d.name == "X CO NEW" and d.cusips == [] and d.cik_pin is None and d.sec_id_pin is None
    assert TickerEra("X", "2020-01-01", "2020-01-01").derived is False          # no observation at all: not derived
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_observations.py -q -o addopts="" -k derived`
Expected: `TypeError: Observation.__init__() got an unexpected keyword argument 'derived'`.

- [ ] **Step 2: The marker**

In `observations.py`, `Observation`: after `sec_id`

```python
    derived: bool = False     # made by the library from the fails rows (`identity.refine_eras`), not observed by the caller
```

and in `TickerEra`, above `names`:

```python
    @property
    def caller_observations(self) -> list[Observation]:
        """The observations the caller made: those not derived."""
        return [o for o in self.observations if not o.derived]

    @property
    def derived(self) -> bool:
        """Whether the library made the era from the fails rows (a line after a CUSIP change no caller observation
        names): it has observations and every one is derived."""
        return bool(self.observations) and not self.caller_observations
```

Run the same command. Expected: pass.

- [ ] **Step 3: Write the failing tests of the readers**

`tests/test_security_master.py` (add `TickerEra` to the `observations` import and `observation_conflict_review` to the
`security_master` import):

```python
def _derived_era(ticker="X", first="2020-09-01", name="X CO NEW"):
    return TickerEra(ticker, first, first, [Observation(ticker, first, name, derived=True)])


def test_a_security_is_observed_when_any_of_its_eras_is_the_callers():
    caller = TickerEra("X", "2020-01-15", "2020-06-30", [Observation("X", "2020-01-15", "X CO")])
    derived = _derived_era()
    res = {e.key: EraResolution(e.key, "BBGX", "cusip", None, ()) for e in (caller, derived)}
    eras = {e.key: e for e in (caller, derived)}
    assert build_securities(res, eras, {})["BBGX"].observed is True
    assert build_securities({derived.key: res[derived.key]}, {derived.key: derived}, {})["BBGX"].observed is False


def test_a_derived_observation_is_no_conflict():
    caller = TickerEra("X", "2020-09-01", "2020-09-01", [Observation("X", "2020-09-01", "OTHER CO")])
    derived = _derived_era(first="2020-09-01")                                  # the same ticker and day, another name
    res = {e.key: EraResolution(e.key, "BBGX", "cusip", None, ()) for e in (caller, derived)}
    assert observation_conflict_review([caller, derived], res) == []
```

`tests/test_history.py`:

```python
def test_a_derived_observation_is_no_sighting_and_no_row_of_the_observation_map():
    from delist_detection.identity.security_master import Security
    caller = TickerEra("X", "2020-09-01", "2020-09-01", [Observation("X", "2020-09-01", "X CO")])
    derived = TickerEra("X", "2020-09-01", "2020-09-01", [Observation("X", "2020-09-01", "X CO NEW", derived=True)])
    sec = Security("BBGX", 1, "COMMON", "X", "Common Stock", True, "cusip", eras=[caller, derived])
    assert ticker_sightings(sec, FtdIndex(), []) == [Sighting("2020-09-01", "X", "observation")]
    history = _plain_history({"BBGX": [Sighting("2020-09-01", "X", "ftd")]})
    assert observation_map_rows([derived], {derived.key: "BBGX"}, {derived.key: 1}, history, []) == []
```

`tests/test_pipeline.py`: let `_stage_5b` take `derived=False` (signature `def _stage_5b(rows, specs, endings, sec_cusips=None, loaded=(), derived=False)`; the era
line becomes `Observation(ticker, first, "AETNA INC", derived=derived)` and the security's `observed` argument `not derived`), then add

```python
def test_stage_5b_does_not_back_fill_a_derived_line():
    """A derived line's one observation is dated at its first fails row: no caller sighting, so no 'died before it was
    seen' to repair."""
    loaded = [FtdRow("2018-11-27", "00817Y108", "AET", "AETNA INC COM", 181.0),
              FtdRow("2018-12-05", "00817Y108", "AET", "AETNA INC COM", 212.0),
              FtdRow("2018-12-12", "00817Y108", "AET", "AETNA INC COM", 212.0)]
    kw = dict(sec_cusips={"S1": ["00817Y108"]}, loaded=loaded)
    fixed, *_ = _stage_5b(_aet_rows(), {"S1": ("AET", "2019-06-28")}, [("S1", "2018-11-28", None)], **kw)
    assert fixed == ["S1"]
    fixed, *_ = _stage_5b(_aet_rows(), {"S1": ("AET", "2019-06-28")}, [("S1", "2018-11-28", None)], derived=True, **kw)
    assert fixed == []


def test_the_other_issuer_in_force_reads_no_derived_observation():
    obs = [Observation("SPB", d, "SPECTRUM BRANDS HOLDINGS INC", derived=True) for d in ("2010-06-30", "2014-06-30")]
    s, era, resolutions, issuers = _security_with_era("BBG000P4BQM9", 109177, "SPB", obs)
    ctx = _in_force_run({109177: HRG, 1487730: OLD_SPB}, {"SPECTRUM BRANDS HOLDINGS INC": [109177, 1487730]})
    assert pipeline._other_issuers(ctx, [era], resolutions, issuers, {s.sec_id: s}) == {}
```

(`_observation_map`'s conflict list is the same expression as `_other_issuers`'s and is exercised through the whole-run test of Task 12.)

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py tests/test_history.py tests/test_pipeline.py -q -o addopts="" -k "derived or observed_when"`
Expected: `test_a_security_is_observed_when_any_of_its_eras_is_the_callers` (`observed` is always True today), the conflict, sighting and map tests, the 5b test and the other-issuer test fail.

- [ ] **Step 4: The readers**

`security_master.py`, `build_securities`: the first-created security takes `not era.derived`, and a later era can only turn it on:

```python
            sec = Security(res.sec_id, cik_of(issuers, key), _share_class(res, era), name, stype, not era.derived,
                           res.source, security_kind(stype, name))
            out[res.sec_id] = sec
        elif SOURCE_STRENGTH.index(res.source) < SOURCE_STRENGTH.index(sec.figi_source):
            sec.figi_source, sec.share_class = res.source, _share_class(res, era)
        sec.observed = sec.observed or not era.derived      # observed when any of its eras is the caller's
```

(the `elif` is the existing one; the last line is new, before `classes[res.sec_id].append(...)`.) `observation_conflict_review`:
both `e.observations` become `e.caller_observations`.

`history.py`: `ticker_sightings` (`for o in e.observations` -> `for o in e.caller_observations`), `cusip_sightings` (the same) and
`observation_map_rows` (`for o in era.observations:` -> `for o in era.caller_observations:`). Update `ticker_sightings`'s docstring:
"its observations (the caller's: a derived era has none)".

`pipeline.py`: `_dead_before_sighting` (`for o in era.observations` -> `era.caller_observations`), `_observation_map`
(the `observation_conflicts(...)` generator), `_other_issuers` (the `conflicts` set and the `sightings` comprehension). `total =
sum(len(e.observations) for e in index.eras())` stays: the index holds the caller's eras only.

Run the command of Step 3, then the whole suite. Expected: all pass, the previous count plus 6, golden replay green.

- [ ] **Step 5: Docs and commit**

`CONTEXT.md`, after **Observation**: "**Derived line**: A line after a CUSIP change that stage 4b refused (another registrant took over) and that no observation names, made an era of its own from the fails rows (`identity/derived_lines.py`). Its one observation is derived (`Observation.derived`): it is not the caller's, so it appears in neither `observation_map.csv` nor `contract/seeds.csv`, and a security all of whose eras are derived is `observed=false`. In a full run the caller has observed the same line." `docs/architecture.md`: in the three module entries, the marker and the readers (a sentence each). `docs/invariants.md`, "`observation_map.csv` is the caller's join surface": "A derived era's observation is no row of it."

```bash
git add src/delist_detection/identity/observations.py src/delist_detection/identity/security_master.py src/delist_detection/identity/history.py src/delist_detection/pipeline.py tests CONTEXT.md docs/architecture.md docs/invariants.md
git commit -m "A derived observation: the marker, and the readers that skip it"
```

---

### Task 10: The identity stage keeps an approved part of the fails rows as a derived era (decision d, the creation)

`_split_era` drops a part of a ticker's fails rows that has no observation. With the pairs `(ticker, new CUSIP)` stage 4b's
refusals earn (Task 11), it keeps such a part as an era whose one observation is derived. Four conditions hold, three of
them structural and checked here, the fourth (the new rows name the old issuer) decided by the caller of the stage:

1. the part follows an era of the same gap group (an observed part, or a derived one: a chain), with only CUSIP changes between them;
2. its kept CUSIP is approved for the ticker (Task 11's `derivable`);
3. it is not before the era's first observation (a consequence of 1: nothing precedes the first part);
4. its CUSIP is not one the ticker's next era trades (that era's own rows are its head, not a derived line).

The era is named by the commonest description its CUSIP's rows carry in their first 30 days, has its own CUSIP as
`ftd_cusips`, and carries no pin. The stage also takes the fails index it is to read (`ftd`), so a second pass does not
open it again.

**Files:**
- Modify: `src/delist_detection/vocabulary/names.py` (`description_name`)
- Modify: `src/delist_detection/identity/identity.py` (`identify`, `_refine`, `_split_era`, `_derived_era`, `refine_eras`)
- Modify: `tests/test_names.py`, `tests/test_security_master.py`
- Modify: `docs/architecture.md` (`identity/identity.py`)

**Interfaces:**
- Consumes: `Observation.derived`, `TickerEra.derived` (Task 9).
- Produces: `names.description_name(description: str) -> str`; `refine_eras(eras, ftd, derive: Collection[tuple[str, str]] = ()) -> list[TickerEra]`; `identify(index, clients, *, as_of, limit=None, log=..., workers=1, meter=None, derive: Collection[tuple[str, str]] = (), ftd: FtdIndex | None = None) -> Identity`; `_split_era(era, rows, *, contested, derive: Collection[str] = ())`.

- [ ] **Step 1: Write the failing tests**

`tests/test_names.py`:

```python
def test_description_name_is_the_issuers_name_without_the_securitys_tail():
    from delist_detection.vocabulary.names import description_name
    assert description_name("CYTTA CORP NEW COM STK (NV)") == "CYTTA CORP NEW COM STK"
    assert description_name("  wendy's/arby's group inc cl a ") == "WENDY'S/ARBY'S GROUP INC CL A"
    assert description_name("APPLE INC;COM NPV") == "APPLE INC" and description_name("") == ""
```

`tests/test_security_master.py` (it has `_era`, `_rows`, `refine_eras`, `FtdIndex`, `Observation`):

```python
X_OBS = (("2020-01-15", "X CO"), ("2020-06-30", "X CO"), ("2020-12-31", "X CO"))


def _x_rows():
    return (_rows("X", "AAA", ["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01"])
            + _rows("X", "BBB", ["2020-09-01", "2020-10-01", "2020-11-02", "2021-01-04"], "X CO NEW")
            + _rows("X", "CCC", ["2021-03-01", "2021-04-01", "2021-05-03"], "X CO NEWER, INC (DE)"))


def test_a_derived_part_is_an_era_with_one_derived_observation_and_no_pin():
    era = _era("X", *X_OBS)
    [a, b, c] = refine_eras([era], FtdIndex(_x_rows()), {("X", "CCC")})
    assert (c.key, c.first, c.last, c.derived, c.ftd_cusips) == ("X@2021-03-01", "2021-03-01", "2021-03-01", True,
                                                                 ("CCC",))
    assert c.observations == [Observation("X", "2021-03-01", "X CO NEWER, INC", derived=True)]
    assert (c.cik_pin, c.sec_id_pin, c.cusips) == (None, None, [])
    assert not a.derived and not b.derived


def test_a_part_nobody_approved_or_approved_for_another_ticker_is_dropped_as_before():
    era = _era("X", *X_OBS)
    assert len(refine_eras([era], FtdIndex(_x_rows()))) == 2
    assert len(refine_eras([era], FtdIndex(_x_rows()), {("Y", "CCC"), ("X", "ZZZ")})) == 2


def test_a_chain_of_derived_parts_is_followed_and_a_dropped_part_breaks_it():
    rows = _x_rows() + _rows("X", "DDD", ["2021-07-01", "2021-08-02", "2021-09-01"], "X CO NEWEST")
    era = _era("X", *X_OBS)
    got = refine_eras([era], FtdIndex(rows), {("X", "CCC"), ("X", "DDD")})
    assert [(e.first, e.derived) for e in got] == [("2020-01-15", False), ("2020-12-31", False), ("2021-03-01", True),
                                                   ("2021-07-01", True)]
    broken = refine_eras([era], FtdIndex(rows), {("X", "DDD")})            # CCC is not approved: DDD follows no era
    assert [e.first for e in broken] == ["2020-01-15", "2020-12-31"]


def test_a_part_before_the_first_observation_or_after_a_hole_is_no_derived_line():
    late = _era("X", ("2020-09-15", "X CO"), ("2020-12-31", "X CO"))
    assert all(not e.derived for e in refine_eras([late], FtdIndex(_x_rows()), {("X", "AAA")}))   # AAA precedes it
    hole = _rows("X", "EEE", ["2023-03-01", "2023-04-03", "2023-05-01"])         # more than 400 days after the last row
    got = refine_eras([_era("X", *X_OBS)], FtdIndex(_x_rows() + hole), {("X", "EEE")})
    assert all(not e.derived for e in got)


def test_a_cusip_the_next_era_of_the_ticker_trades_is_that_eras_not_a_derived_line():
    first = _era("X", ("2020-01-15", "X CO"), ("2020-12-31", "X CO"))
    second = _era("X", ("2023-06-30", "Y CORP"), ("2023-12-31", "Y CORP"))      # the name stopped agreeing: a second era
    rows = (_rows("X", "AAA", ["2020-01-02", "2020-02-03", "2020-03-02"])
            + _rows("X", "BBB", ["2021-03-01", "2021-04-01", "2021-05-03", "2023-07-03", "2023-08-01", "2023-09-01"],
                    "Y CORP"))
    got = refine_eras([first, second], FtdIndex(rows), {("X", "BBB")})
    assert [(e.first, e.derived) for e in got] == [("2020-01-15", False), ("2023-06-30", False)]
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_names.py tests/test_security_master.py -q -o addopts="" -k "description_name or derived or next_era"`
Expected: `ImportError` for `description_name`, then (after Step 2) `TypeError: refine_eras() takes 2 positional arguments` for the others.

- [ ] **Step 2: `names.description_name`**

In `vocabulary/names.py`, directly above `_issuer_words`:

```python
def description_name(description: str) -> str:
    """The issuer's name in a fails-to-deliver description: it without its security tail ("CYTTA CORP NEW COM STK
    (NV)" is "CYTTA CORP NEW COM STK"), upper case, single-spaced; empty for a description with none."""
    return " ".join(_name_part(description).split())
```

- [ ] **Step 3: The creation**

`identity.py`: add `description_name` to the `names` import. Replace `_split_era` with (the new pieces are `DERIVED_NAME_DAYS`, `_derived_era`, the `derive` parameter and `follows`):

```python
DERIVED_NAME_DAYS = 30     # a derived era is named by the description its CUSIP's rows carry in their first days


def _derived_era(era: TickerEra, part_rows: Sequence[FtdRow], kept: tuple[str, ...]) -> TickerEra:
    """The era of a line no caller observation names: one derived observation dated at the part's first row and named
    by the commonest description of its CUSIP's rows in their first `DERIVED_NAME_DAYS` days. No pin: the observation
    carries none, and the era's own CUSIPs are the part's."""
    first = part_rows[0].date
    until = (date.fromisoformat(first) + timedelta(days=DERIVED_NAME_DAYS)).isoformat()
    seen = Counter(r.description for r in part_rows if r.cusip == kept[0] and r.date <= until)
    name = description_name(seen.most_common(1)[0][0]) if seen else ""
    return TickerEra(era.ticker, first, first, [Observation(era.ticker, first, name or None, derived=True)],
                     ftd_cusips=kept)


def _split_era(era: TickerEra, rows: list[FtdRow], *, contested: bool,
               derive: Collection[str] = ()) -> list[TickerEra]:
    out: list[TickerEra] = []
    for g_obs, g_rows in _cut(era.observations, rows, _gap_cuts(era.observations, rows)):
        follows = False                   # the part before is an era of this group: a line is derived only after one
        for obs, part_rows in _cut(g_obs, g_rows, _switch_cuts(g_rows)):
            kept = _kept_cusips(part_rows)
            if not obs:                   # an FTD-only side (another holder of the ticker, a tail) is no era ...
                follows = follows and bool(kept) and kept[0] in derive      # ... unless a derived line (`derive`)
                if follows:
                    out.append(_derived_era(era, part_rows, kept))
                continue
            follows = True
            names = [o.name for o in obs if o.name]
            if contested and names:
                # Another era of this ticker has observations on the same dates
                # (a backfilled name): the ticker's rows are only this era's when
                # their description agrees with its names.
                kept = tuple(c for c in kept if _described(c, part_rows, names))
            out.append(replace(era, first=obs[0].as_of, last=obs[-1].as_of, observations=list(obs),
                               ftd_cusips=kept))
    return out
```

`refine_eras(eras, ftd, derive=())`: the signature `def refine_eras(eras: Sequence[TickerEra], ftd: FtdIndex, derive: Collection[tuple[str, str]] = ()) -> list[TickerEra]:`, one paragraph added to its docstring ("`derive`: (ticker, CUSIP) pairs the caller approved (`derived_lines.derivable`): a part of the ticker's rows with no observation whose kept CUSIP is approved, that follows an era of its gap group and whose CUSIP the ticker's next era does not trade, is an era with one derived observation (`_derived_era`)") and the loop body's last two lines become:

```python
        later = {r.cusip for r in ftd.by_symbol(e.ticker, nxt)} if nxt and derive else set()   # the next era's own
        approved = {c for t, c in derive if t == e.ticker and c not in later}
        out += _split_era(e, ftd.by_symbol(e.ticker, lo, hi), contested=contested, derive=approved)
```

`identify` and `_refine` take the pair set and an optional index (the second pass reads the first's, opened once):

```python
def identify(index: ObservationIndex, clients: Sources, *, as_of: date, limit: int | None = None,
             log: Callable[[str], None] = _quiet, workers: int = 1, meter: StageMeter | None = None,
             derive: Collection[tuple[str, str]] = (), ftd: FtdIndex | None = None) -> Identity:
```

```python
    eras, era_by_key, ftd = _refine(index, clients.ftd_client, as_of, limit, log, derive, ftd)          # 1
```

```python
def _refine(index: ObservationIndex, ftd_client: Any, as_of: date, limit: int | None,
            log: Callable[[str], None], derive: Collection[tuple[str, str]] = (),
            ftd: FtdIndex | None = None) -> tuple[list[TickerEra], dict[str, TickerEra], FtdIndex]:
```

```python
    if ftd is None:
        ftd = FtdIndex.opened(ftd_client, lo, hi, through=as_of, symbols={e.ticker for e in eras},
                              cusips={c for e in eras for c in e.cusips}, names=class_names, first_seen=first_seen)
    eras = refine_eras(eras, ftd, derive)
```

Add to `identify`'s docstring: "`derive` and `ftd`: the derived-line pairs (`derived_lines.identify_with_lines`) and the fails index an earlier call opened, which a repeat reads in place of opening its own (the rows `follow_lines` added to it stay)."

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_names.py tests/test_security_master.py tests/test_resolver_renamed.py tests/test_identity_cases.py -q -o addopts=""`
Expected: all pass (prototype: the five derived tests pass in 0.12 s). `test_refine_eras_ignores_short_cusip_runs_and_obs_less_sides` is unchanged: with no approved pair the CCC part is still dropped.

- [ ] **Step 4: Run everything, docs, commit**

Whole suite: previous count plus 6, golden green. `docs/architecture.md`, `identity/identity.py` entry: `refine_eras`' `derive`, `identify`'s `derive` and `ftd`. 

```bash
git add src/delist_detection/vocabulary/names.py src/delist_detection/identity/identity.py tests/test_names.py tests/test_security_master.py docs/architecture.md
git commit -m "The identity stage keeps an approved part of the fails rows as a derived era"
```

---

### Task 11: Stage 4b says which refused steps are lines; the test of a name (decision d, g)

`follow_lines` keeps the steps it refuses only as review items. This task returns them (`Lines.refused`) and adds the pure
function that picks the ones whose line is derived: a switch refused `merged_out`, `other_registrant` or `name` whose new
rows' descriptions name the old line's issuer. "Name" is `names.description_names_issuer`: `description_names` (as many
issuer words as the shorter side has, up to two) and at least one of them a word as spelled, not only a word written
short. The table under "Condition 2 and the test of a name" is its measurement.

**Files:**
- Modify: `src/delist_detection/vocabulary/names.py` (`description_names_issuer`)
- Modify: `src/delist_detection/identity/line_follow.py` (`RefusedStep`, `Lines.refused`, `follow_lines`)
- Create: `src/delist_detection/identity/derived_lines.py` (`DERIVABLE`, `old_line_names`, `derivable`; the loop comes in Task 12)
- Modify: `tests/test_names.py`, `tests/test_line_stage.py`; Create: `tests/test_derived_lines.py`
- Modify: `docs/architecture.md` (`identity/line_follow.py`, new `identity/derived_lines.py`), `CLAUDE.md` (the `identity/` list)

**Interfaces:**
- Produces: `RefusedStep(sec_id: str, step: LineStep, why: str)`; `Lines.refused: list[RefusedStep]` (its `sec_id` follows a fold, like the review items'); `names.description_names_issuer(description: str, name: str) -> bool`; `derived_lines.derivable(refused: Sequence[RefusedStep], securities: Mapping[str, Security], profile: Callable[[int], Mapping | None]) -> set[tuple[str, str]]` (the `(ticker, new CUSIP)` pairs Task 10's `derive` takes).

- [ ] **Step 1: Write the failing tests**

`tests/test_names.py`:

```python
@pytest.mark.parametrize("description,name,expected", [
    ("AMERICAN NATL GROUP INC", "AMERICAN NATIONAL INSURANCE CO", True),      # ANAT 2020
    ("CIGNA CORP NEW COM STK", "CIGNA CORP", True),                            # CI 2018
    ("MYLAN N V SHS EURO", "MYLAN INC.", True),                                # MYL 2015
    ("ENDO INTL PLC ORD SHS", "ENDO PHARMACEUTICALS", True),                   # ENDP 2014
    ("ARRIS INTL LTD ORD SHS", "ARRIS INTERNATIONAL INC", True),               # ARRS 2016
    ("BUNGE GLOBAL SA SHS", "BUNGE LIMITED", True),                            # BG 2023
    ("STERIS PLC ORD SHS", "STERIS", True),                                    # STE 2019
    ("DIRECTV CL A COM STK", "DIRECTV GROUP INC", True),                       # DTV 2009
    ("FERGUSON ENTERPRISES INC COM", "FERGUSON PLC", True),                    # FERG 2024
    ("SEA LTD ADR (CYM)", "SPECTRA ENERGY CORP", False),                       # SE 2017: SEA is SPECTRA with letters left out
    ("LIBERTY GLOBAL PLC SHS CL A", "TELEWEST GLOBAL INC", False),             # VMED 2013: one word, GLOBAL
    ("BRISTOL MYERS SQUIBB CO CONTIN", "CELGENE CORP", False),                 # CELG 2019
    ("WW INTL INC COM", "WEIGHT WATCHERS INTL INC", False),                    # no issuer word left: names nothing
])
def test_a_description_names_the_issuer_by_a_word_as_spelled(description, name, expected):
    from delist_detection.vocabulary.names import description_names_issuer
    assert description_names_issuer(description, name) is expected
```

(`tests/test_names.py` imports `pytest`; add it if it does not.)

`tests/test_line_stage.py`:

```python
def test_a_refused_step_is_returned_with_its_security_and_why():
    """A registrant that merged out (no periodic report after the step) refuses the step; the stage hands it back."""
    rows = _line("AA", ["A1", "A2"])
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=_Edgar([f for f in _stating(rows) if f is not LATER_10Q]))
    [r] = lines.refused
    assert (r.sec_id, r.why, r.step.old_cusip, r.step.new_cusip, r.step.symbol) == ("BBGA", "merged_out", "A1", "A2", "AA")
    assert _flags(lines) == [("BBGA", "line_follow_refused:merged_out")]
```

(`_stating(rows)` ends with the module's `LATER_10Q`; filtering it out removes the periodic report.)

`tests/test_derived_lines.py` (new):

```python
"""Which refused steps of stage 4b are lines of the run (`derived_lines.derivable`), and the rounds that give the run
those lines (`identify_with_lines`)."""
from datetime import date
from types import SimpleNamespace

import delist_detection.identity.derived_lines as derived_lines
from delist_detection.identity.derived_lines import derivable, old_line_names
from delist_detection.identity.line_follow import NEW_SYMBOL, SWITCH, LineStep, RefusedStep
from delist_detection.identity.observations import Observation, TickerEra
from delist_detection.identity.security_master import Security


def _security(sid="BBGOLD", cik=1, eras_name="CIGNA CORP", tickers=("CI",)):
    eras = [TickerEra(t, "2008-01-16", "2008-01-16", [Observation(t, "2008-01-16", eras_name)]) for t in tickers]
    return Security(sid, cik, "COMMON", eras_name, "Common Stock", True, "cusip", eras=eras)


def _step(descs, kind=SWITCH, sid="BBGOLD", new="NEWCUSIP1"):
    return LineStep(sid, kind, "OLDCUSIP1", new, "CI", "2018-12-10", "2018-12-21", tuple(descs))


NO_PROFILE = lambda cik: None


def test_a_refused_switch_whose_new_rows_name_the_old_issuer_is_derived_for_each_of_its_tickers():
    s = _security(tickers=("CI", "CIGNA"))
    got = derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP NEW COM STK"]), "merged_out")], {"BBGOLD": s}, NO_PROFILE)
    assert got == {("CI", "NEWCUSIP1"), ("CIGNA", "NEWCUSIP1")}


def test_each_refusal_of_another_registrant_or_a_name_is_derivable_and_no_other_is():
    s = {"BBGOLD": _security()}
    for why, derived in [("merged_out", True), ("other_registrant", True), ("name", True), ("no_filing", False),
                         ("bankruptcy", False), ("unsettled", False), ("otc_move", False), ("taken", False)]:
        got = derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP NEW COM STK"]), why)], s, NO_PROFILE)
        assert bool(got) is derived, why


def test_a_new_symbol_a_reused_ticker_and_an_unknown_security_are_no_derived_line():
    s = {"BBGOLD": _security(eras_name="SPECTRA ENERGY CORP", tickers=("SE",))}
    assert derivable([RefusedStep("BBGOLD", _step(["SEA LTD ADR (CYM)"]), "name")], s, NO_PROFILE) == set()   # SE 2017
    assert derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP"], kind=NEW_SYMBOL), "merged_out")],
                     {"BBGOLD": _security()}, NO_PROFILE) == set()
    assert derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP"]), "merged_out")], {}, NO_PROFILE) == set()


def test_the_old_lines_names_are_its_observed_names_and_its_issuers_names_until_the_step():
    sub = {"name": "NEW NAME INC", "formerNames": [
        {"name": "OLD NAME INC", "from": "2001-01-01T00:00:00.000Z", "to": "2018-12-22T00:00:00.000Z"}]}
    names = old_line_names(_security(eras_name="OBSERVED CO"), sub, "2018-12-21")
    assert names == ["OBSERVED CO", "OLD NAME INC"]            # NEW NAME INC began after the step: the new line's
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_names.py tests/test_line_stage.py tests/test_derived_lines.py -q -o addopts="" -k "issuer_by_a_word or refused or derived or old_lines"`
Expected: `ImportError` (names, `RefusedStep`, `derived_lines`).

- [ ] **Step 2: `description_names_issuer`**

In `vocabulary/names.py`, directly above `names_an_issuer`:

```python
def description_names_issuer(description: str, name: str) -> bool:
    """Whether a fails-to-deliver `description` is the stock of the company `name`, for a line the library derives:
    `description_names`, and not on words written short alone. At least one issuer word of the description is a word
    of the name as spelled (a plural S aside); the words matched are two when both sides have two or more, else the
    only word the shorter side has. SEA LTD is not SPECTRA ENERGY (SEA is SPECTRA with letters left out), a one-word
    overlap on GLOBAL is not LIBERTY GLOBAL naming TELEWEST GLOBAL, while AMERICAN NATL GROUP is AMERICAN NATIONAL
    INSURANCE (AMERICAN as spelled, NATL written short). With nothing to compare it names nothing."""
    d_words = _without_holding(_issuer_words(_name_part(description)))
    n_words = _without_holding(_issuer_words(name))
    if not d_words or not n_words:
        return False
    exact, short = _word_matches(d_words, n_words, _name_part(description), name, either=False)
    return exact >= 1 and exact + short >= min(2, len(d_words), len(n_words))
```

- [ ] **Step 3: `Lines.refused`**

`line_follow.py`: above `Lines`:

```python
@dataclass(frozen=True)
class RefusedStep:
    """A step `follow_lines` did not follow: the security whose line it was, the step and why (`corroborate`'s or
    R2's refusal word: "merged_out", "name", ...)."""
    sec_id: str
    step: LineStep
    why: str
```

`Lines` gains `refused: list[RefusedStep] = field(default_factory=list)` after `review`, and its docstring "the steps it refused (`refused`: stage 5-onward readers of the line, and `derived_lines`)". In `follow_lines`: `refusals: list[RefusedStep] = []` beside `items`; in the refusal branch, after `counts[f"refused:{refused}"] += 1`: `refusals.append(RefusedStep(sid, step, refused))`; after `out.renames` is final (just before `out.review = ...`): `out.refused = [replace(r, sec_id=out.renames.get(r.sec_id, r.sec_id)) for r in refusals]`.

- [ ] **Step 4: `derived_lines.py` (the pure part)**

Create `src/delist_detection/identity/derived_lines.py` with the module docstring, imports, `MAX_DERIVE_ROUNDS`, `DERIVABLE`, `old_line_names` and `derivable` exactly as in the file of Task 12, Step 3 (this task creates the file with those four names and the imports they use; Task 12 adds `identify_with_lines`):

```python
"""The line after a CUSIP change that stage 4b refuses is a line of the run (seeds-only parity, S2).

Stage 4b (`line_follow.follow_lines`) follows a security past its observations across a CUSIP change when the old
registrant carries on. When another registrant took over (`merged_out`, `other_registrant`), or the new rows do not
name the issuer's name in force after the step (`name`), it refuses the step, and the line after it belongs to
nobody: a full run has it because the caller kept observing it, a seeds-only run has no observation in it.
`identify_with_lines` gives the line to the run as an era of its own: it asks the identity stage again with the
refused steps whose new rows still name the old line's issuer (`derivable`), so `identity.refine_eras` keeps those
parts as eras whose one observation is derived (`Observation.derived`), until a round refuses no further step.
Everything after the stage sees an ordinary era-born security.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Callable

from ..filings.evidence import names_until
from ..vocabulary.names import description_names_issuer
from .line_follow import SWITCH, RefusedStep
from .security_master import Security

MAX_DERIVE_ROUNDS = 3        # rounds that add derived lines: a derived line whose own next step is refused too is a round
DERIVABLE = frozenset({"merged_out", "other_registrant", "name"})     # the refusals a derived line may follow


def old_line_names(security: Security, profile: Mapping | None, step_first: str) -> list[str]:
    """The names the refused step's old line was known by: its eras' observed names, and every EDGAR name its issuer
    carried until the day before the step (`evidence.names_until`: a name it took after the step is the new line's)."""
    day = date.fromisoformat(step_first) - timedelta(days=1)
    edgar = names_until(profile, day) if isinstance(profile, Mapping) else []
    return list(dict.fromkeys([*(n for e in security.eras for n in e.names), *edgar]))


def derivable(refused: Sequence[RefusedStep], securities: Mapping[str, Security],
              profile: Callable[[int], Mapping | None]) -> set[tuple[str, str]]:
    """The (ticker, new CUSIP) pairs of the refused steps whose line is derived: a switch refused for one of
    `DERIVABLE` whose new rows' descriptions name the old line's issuer (`description_names_issuer` against
    `old_line_names`), for each ticker the old line traded under."""
    out: set[tuple[str, str]] = set()
    for r in refused:
        s = securities.get(r.sec_id)
        if s is None or r.why not in DERIVABLE or r.step.kind != SWITCH:
            continue
        names = old_line_names(s, profile(s.issuer_cik) if s.issuer_cik is not None else None, r.step.first)
        if any(description_names_issuer(d, n) for d in r.step.descriptions for n in names):
            out |= {(t, r.step.new_cusip) for t in s.own_tickers()}
    return out
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_names.py tests/test_line_stage.py tests/test_derived_lines.py tests/test_line_follow.py tests/test_line_follow_cases.py tests/test_import_closure.py -q -o addopts=""`
Expected: all pass. (`import_closure` reads the new module's imports: `identity` imports `filings`, `vocabulary` and its own modules only.)

- [ ] **Step 5: Run everything, docs, commit**

Whole suite: previous count plus 18, golden green. `docs/architecture.md`: `line_follow.py` (`RefusedStep`, `Lines.refused`), a new `identity/derived_lines.py` entry (what it does, `derivable`'s definition and the table's result); `CLAUDE.md` identity list: add `derived_lines`.

```bash
git add src/delist_detection/vocabulary/names.py src/delist_detection/identity/line_follow.py src/delist_detection/identity/derived_lines.py tests docs/architecture.md CLAUDE.md
git commit -m "Stage 4b returns its refused steps; which of them are lines of the run"
```

---
### Task 12: The run asks again with the derived lines (decision d, e)

`identify_with_lines` runs the identity stage (1 to 4) and stage 4b, takes the pairs `derivable` earns from 4b's
refusals, runs both again with those pairs and the same fails index, and so on until a round earns no new pair or
`MAX_DERIVE_ROUNDS` rounds have added one. `_run` calls it in place of `identify` and `follow_lines`. From then on a
derived line is a security of the run like any other: the FIGI stage resolves it by its own CUSIP, the issuer lookup asks
under its own fails description (Task 6's row check holds a weak answer to the era's rows), the handoff stage pairs it
with the line before it, the finder searches its Form 25, stage 8 values its ending. The line stage 4b refused is held by
the derived security in the next round, so the step is no longer asked and its `line_follow_refused:<why>` item is gone
(as in a full run, where the observed second line holds the CUSIP).

**Files:**
- Modify: `src/delist_detection/identity/derived_lines.py` (`identify_with_lines`)
- Modify: `src/delist_detection/pipeline.py` (`_run`, two imports)
- Modify: `tests/test_derived_lines.py`, `tests/test_pipeline.py`
- Modify: `docs/architecture.md` ("The run: pipeline.py", `identity/derived_lines.py`), `docs/invariants.md` ("A line is followed past its observations"), `CONTEXT.md`

**Interfaces:**
- Consumes: `identify(..., derive=, ftd=)` (Task 10), `follow_lines(...) -> Lines` with `.refused` (Task 11), `derivable`.
- Produces: `identify_with_lines(index: ObservationIndex, clients, *, as_of: date, limit: int | None = None, log=..., workers: int = 1, meter=None) -> tuple[Identity, Lines]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_derived_lines.py` (append; it imports `date`, `SimpleNamespace` and `derived_lines`):

```python
def _loop(monkeypatch, answers):
    """`identify_with_lines` over scripted stages: round n's `derivable` answer is answers[n]."""
    calls, logs = [], []
    ftd = object()

    def identify(index, clients, **kw):
        calls.append((kw["derive"], kw["ftd"]))
        return SimpleNamespace(ftd=ftd, round=len(calls))

    monkeypatch.setattr(derived_lines, "identify", identify)
    monkeypatch.setattr(derived_lines, "follow_lines",
                        lambda identity, clients, **kw: SimpleNamespace(refused=[], securities={}))
    monkeypatch.setattr(derived_lines, "derivable",
                        lambda refused, securities, profile: answers[min(len(calls), len(answers)) - 1])
    clients = SimpleNamespace(issuers=SimpleNamespace(profile=lambda cik: None))
    identity, lines = derived_lines.identify_with_lines(None, clients, as_of=date(2026, 9, 25), log=logs.append)
    return calls, logs, identity, ftd


def test_the_loop_asks_again_until_a_round_derives_nothing_new_over_one_fails_index(monkeypatch):
    both = {("X", "AAA"), ("X", "BBB")}
    calls, logs, identity, ftd = _loop(monkeypatch, [{("X", "AAA")}, both, both])
    assert [c[0] for c in calls] == [frozenset(), frozenset({("X", "AAA")}), frozenset(both)]
    assert calls[0][1] is None and calls[1][1] is ftd and calls[2][1] is ftd      # the index is opened once
    assert identity.round == 3 and not any("not derived" in line for line in logs)


def test_the_loop_stops_at_the_bound_and_says_so(monkeypatch):
    calls, logs, identity, ftd = _loop(monkeypatch, [{("X", f"C{i}")} for i in range(10)])
    assert len(calls) == derived_lines.MAX_DERIVE_ROUNDS + 1
    assert any("not derived" in line for line in logs)


def test_a_run_with_no_derivable_step_asks_once(monkeypatch):
    calls, logs, identity, ftd = _loop(monkeypatch, [set()])
    assert len(calls) == 1
```

`tests/test_pipeline.py` (new whole-run test beside `test_a_registrant_that_merged_out_at_the_switch_is_not_followed`):

```python
def test_the_line_after_a_registrant_that_merged_out_is_a_derived_security(fake_edgar, tmp_path):
    """S2 (seeds-only parity): RS's observations stop in 2009 and its registrant merged out at the 2012 switch (no 10-Q
    after it), so stage 4b refuses the step; the new CUSIP's rows, named for RS, are a line of the run. It is an
    ordinary security to every later stage -- the old line hands over to it, its own merger is found -- and the
    caller's tables hold the caller's rows only."""
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    secs = {r["sec_id"]: r for r in t["securities"]}
    assert {k: (v["observed"], v["issuer_cik"]) for k, v in secs.items()} == {
        "BBGRS01": ("true", "4242"), "BBGRSNEW1": ("false", "4242")}
    assert secs["BBGRSNEW1"]["name"] == "REVERSE SPLIT CO NEW"            # named by its own fails description
    assert {r["sec_id"]: r["cusip"] for r in t["cusip_history"]} == {"BBGRS01": RS_OLD, "BBGRSNEW1": RS_NEW}
    assert ("BBGRSNEW1", "2012-10-01", "ftd") in {(r["sec_id"], r["valid_from"], r["source"])
                                                  for r in t["ticker_history"]}     # no observation range: a fails row
    caller = [("RS", d, "BBGRS01") for d in ("2008-01-16", "2008-06-30", "2009-06-08")]
    om = read_table("observation_map", table_path(tmp_path, "observation_map"))
    assert sorted((r["ticker"], r["as_of"], r["sec_id"]) for r in om) == caller
    seeds = read_table("seeds", table_path(tmp_path, "seeds"))
    assert sorted((r["ticker"], r["as_of"], r["sec_id"]) for r in seeds) == caller
    assert {(r["sec_id"], r["bucket"], r["successor_sec_id"]) for r in t["delistings"]} == {
        ("BBGRS01", "exchange_transfer", "BBGRSNEW1"), ("BBGRSNEW1", "merger", "")}
```

Then change the four existing tests this task moves (each was run on a prototype; no other test of the suite moves):

1. `test_a_registrant_that_merged_out_at_the_switch_is_not_followed` (UNIT 2025): the new CUSIP's FIGI answer is another
   composite, and the line is now a security of its own. Replace its `figi=` and the two assertions after `t = ...`:

```python
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    # the old security keeps its one CUSIP; the line after the switch is a security of its own, derived from the fails rows
    assert {r["sec_id"]: r["cusip"] for r in t["cusip_history"]} == {"BBGRS01": RS_OLD, "BBGRSNEW1": RS_NEW}
    assert {r["sec_id"]: r["observed"] for r in t["securities"]} == {"BBGRS01": "true", "BBGRSNEW1": "false"}
    assert _flag_count(t, "line_follow_refused") == "0"     # the derived line holds the new CUSIP: no step to refuse
```

2. `_same_ticker_acquirer_run`: the acquirer line is now looked up as an era, and a CIK the SEC ticker map proposes must
   have existed when the era began (`TickerResolver.resolve`'s `since`), so the holder needs a filing history. Replace
   `fake_edgar.submissions_by_cik[holder] = []` by
   `fake_edgar.submissions_by_cik[holder] = [EdgarSubmission("h1", "10-K", "2010-03-01", "2009-12-31", "", "k.htm")]`.
   (This is rough-version point 1, "issuer": `test_a_same_ticker_acquirer_takes_the_sec_ticker_maps_holder_not_the_targets_cik`
   asserts the derived line's CIK is the holder's 1318220, not the target's 1057058, and `..._without_a_ticker_map_holder_has_no_cik` that it has none.)
3. `test_a_same_ticker_acquirer_is_never_the_target_itself` (Ashland): the acquirer line is a security that stops at
   2016-06-09 and is not listed in the fixture, so it has an `unexplained_ending` row of its own. Replace
   `(d,) = read_table(...)` and the two `assert d[...]` lines after it (the `issuer_cik` assertion stays) by

```python
    d = next(r for r in read_table("delistings", table_path(tmp_path, "delistings")) if r["sec_id"] == "BBGWCNOLD01")
    assert d["acquirer_sec_id"] == "BBGWCNNEW01" and d["bucket"] == "merger"      # a merger across two issuers stands
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_derived_lines.py tests/test_pipeline.py -q -o addopts=""`
Expected: the three loop tests fail with `AttributeError: ... has no attribute 'identify'`, the new whole-run test and the four amended ones fail.

- [ ] **Step 2: The loop**

Append to `derived_lines.py`; add `from typing import Any, Callable` (replacing the `Callable` import), `from .identity import Identity, identify`, `from .line_follow import SWITCH, Lines, RefusedStep, follow_lines` and `from .observations import ObservationIndex` to its imports:

```python
def identify_with_lines(index: ObservationIndex, clients: Any, *, as_of: date, limit: int | None = None,
                        log: Callable[[str], None] = lambda *_: None, workers: int = 1,
                        meter: Any = None) -> tuple[Identity, Lines]:
    """Stages 1 to 4b with the derived lines: `identify` and `follow_lines`, again with the lines the last round
    refused that `derivable` gives, over the same fails index (`Identity.ftd`, opened once), until a round adds no
    line or `MAX_DERIVE_ROUNDS` rounds have added one. Returns the last round's identity and lines."""
    derive: set[tuple[str, str]] = set()
    ftd = None
    for round_no in range(MAX_DERIVE_ROUNDS + 1):
        identity = identify(index, clients, as_of=as_of, limit=limit, log=log, workers=workers, meter=meter,
                            derive=frozenset(derive), ftd=ftd)
        lines = follow_lines(identity, clients, as_of=as_of, log=log, meter=meter)
        ftd = identity.ftd
        new = derivable(lines.refused, lines.securities, clients.issuers.profile) - derive
        if not new:
            break
        if round_no == MAX_DERIVE_ROUNDS:
            log(f"derived lines: {len(new)} more steps refused after {MAX_DERIVE_ROUNDS} rounds, not derived")
            break
        derive |= new
        log(f"derived lines: round {round_no + 1} derives {len(new)} (ticker, CUSIP) pairs")
    return identity, lines
```

- [ ] **Step 3: Call it from the run**

In `pipeline.py`: replace `from .identity.identity import identify` by `from .identity.derived_lines import identify_with_lines`
and drop `follow_lines` from the `line_follow` import; in `_run` replace the `identify` call, the `eras, ftd, ftd_lo` line
and the `follow_lines` call by

```python
    identity, lines = identify_with_lines(index, clients, as_of=ctx.as_of, limit=limit, log=log,
                                          workers=sec_workers, meter=ctx.meter)                      # 1-4b
    eras, ftd, ftd_lo = identity.eras, identity.ftd, identity.ftd_lo
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_derived_lines.py tests/test_pipeline.py -q -o addopts=""`
Expected: all pass (prototype: 136 passed in `test_pipeline.py`).

- [ ] **Step 4: Run everything**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: the previous count plus 4 new tests, 44 xfailed. On the prototype exactly the four tests above moved, and the golden
replay, `test_diagnosis_truth_cases.py`, `test_import_closure.py` and the committed-output tests stayed green. A test that
moves and is not one of the four is reported with its old and new value, not edited to pass.

- [ ] **Step 5: Docs and commit**

`docs/architecture.md`, "The run: pipeline.py": stages 1 to 4b are one call, `derived_lines.identify_with_lines` (the
rounds, the bound, the index opened once); the `identity/derived_lines.py` entry gains the loop. `docs/invariants.md`,
"A line is followed past its observations": "A step stage 4b refuses because another registrant took over (`merged_out`,
`other_registrant`), or whose new rows do not name the issuer's name after the step (`name`) but name the old line's, is
a line of the run when it follows an era of the same ticker and its CUSIP is not the ticker's next era's: the identity
stage keeps those fails rows as an era with one derived observation (`Observation.derived`), named by its fails
description, looked up under it and its CUSIP, `observed=false`, in no echo table. A chain is followed up to
`MAX_DERIVE_ROUNDS` rounds." `CONTEXT.md`, **Derived line**: add "(`identify_with_lines`)".

```bash
git add src/delist_detection/identity/derived_lines.py src/delist_detection/pipeline.py tests docs/architecture.md docs/invariants.md CONTEXT.md
git commit -m "The line after a refused CUSIP change is a line of the run"
```

---

### Task 13: A derived line that begins as another security ends: takeover or continuation (decision h)

A derived line begins where the line before it ends, so `find_handoffs` pairs them. `decide_handoff` calls the pair a
continuation on timing only with the same issuer or a CUSIP switch, a takeover when the new line traded before or its
issuer is an older company, and `apply_handoffs` keeps a merger row against timing evidence between two issuers (a
`handoff_conflict` item). The tests below are the real shapes of WEN 2008 (Wendy's International, then Wendy's/Arby's
under the same ticker; Triarc traded as TRY) and TCF 2019 (TCF, then Chemical Financial, which traded as CHFC). They were
written against the code before this task and pass: `handoffs.decide_handoff` and `apply_handoffs` do not change.
If one of them fails when the task is run, the failure is the finding: change `decide_handoff` only for it, and report.

**Files:**
- Modify: `tests/test_handoffs.py`

**Interfaces:** consumes `find_handoffs`, `decide_handoff`, `apply_handoffs`, the test file's `_sig`, `_sec`, `_delisting`.

- [ ] **Step 1: The tests**

Append to `tests/test_handoffs.py`:

```python
def test_a_derived_line_after_wendys_international_is_a_timing_continuation_that_the_merger_row_survives():
    """WEN 2008: Wendy's International's merger into Triarc. The derived line (CUSIP 950587105) has fails rows from
    2008-09-29 only, so it is a new line right after the old one's last row, across two issuers and a CUSIP switch:
    `decide_handoff` says continuation by timing, and the merger row stands against it (`handoff_conflict`)."""
    old = _sig(("2008-03-24", "WEN"), ("2008-09-26", "WEN"))
    new = _sig(("2008-09-29", "WEN"), ("2008-10-01", "WEN"), ("2011-07-08", "WEN"))
    (p,) = find_handoffs({"OLD": old, "NEW": new})
    assert (p.ticker, p.a_last, p.b_first, p.b_first_any) == ("WEN", "2008-09-26", "2008-09-29", "2008-09-29")
    d = decide_handoff(p, filing=None, same_issuer=False, cusip_switch=True, b_issuer_since="1993-01-04")
    assert (d.kind, d.evidence) == ("continuation", "timing:cusip")
    row = _delisting("OLD", "2008-09-29", CrspBucket.MERGER, "2008-09-26", ticker="WEN", cik=105668)
    out = apply_handoffs([d], [row], {"OLD": _sec("OLD", 105668), "NEW": _sec("NEW", 30697)}, [])
    assert row.record.bucket is CrspBucket.MERGER and row.record.successor_sec_id is None
    assert [i.flag for i in out.review] == ["handoff_conflict"]


def test_a_derived_line_whose_issuer_traded_before_under_another_ticker_takes_the_ticker_over():
    """The same pair when the new line's CUSIPs include Triarc's, which traded as TRY until 2008-09-26: B existed."""
    old = _sig(("2008-03-24", "WEN"), ("2008-09-26", "WEN"))
    new = _sig(("2007-12-31", "TRY"), ("2008-09-26", "TRY"), ("2008-09-29", "WEN"), ("2011-07-08", "WEN"))
    (p,) = find_handoffs({"OLD": old, "NEW": new})
    assert (p.b_first, p.b_first_any) == ("2008-09-29", "2007-12-31")
    d = decide_handoff(p, filing=None, same_issuer=False, cusip_switch=True, b_issuer_since="1993-01-04")
    assert (d.kind, d.evidence) == ("takeover", "timing")
    row = _delisting("OLD", "2008-09-29", CrspBucket.MERGER, "2008-09-26", ticker="WEN", cik=105668)
    apply_handoffs([d], [row], {"OLD": _sec("OLD", 105668), "NEW": _sec("NEW", 30697)}, [])
    assert row.record.bucket is CrspBucket.MERGER and row.record.ticker_successor_sec_id == "NEW"


def test_a_derived_line_twenty_days_after_the_old_one_of_an_older_issuer_is_a_takeover():
    """TCF 2019: Chemical Financial (an issuer filing since 1991) took the ticker TCF twenty days after TCF Financial's
    last fails row: no continuation by timing (past `CONTINUATION_DAYS`), a takeover by the older issuer."""
    old = _sig(("2017-05-10", "TCF"), ("2019-07-12", "TCF"))
    new = _sig(("2019-08-01", "TCF"), ("2021-06-11", "TCF"))
    (p,) = find_handoffs({"OLD": old, "NEW": new})
    assert (p.a_last, p.b_first, p.gap) == ("2019-07-12", "2019-08-01", 20)
    d = decide_handoff(p, filing=None, same_issuer=False, cusip_switch=True, b_issuer_since="1991-01-01")
    assert (d.kind, d.evidence) == ("takeover", "timing:issuer")
    row = _delisting("OLD", "2019-08-01", CrspBucket.MERGER, "2019-07-31", ticker="TCF", cik=814184)
    apply_handoffs([d], [row], {"OLD": _sec("OLD", 814184), "NEW": _sec("NEW", 19612)}, [])
    assert row.record.bucket is CrspBucket.MERGER and row.record.ticker_successor_sec_id == "NEW"
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_handoffs.py -q -o addopts=""`
Expected: all pass. Whole suite, then:

```bash
git add tests/test_handoffs.py
git commit -m "WEN and TCF: a derived line that begins as another security ends"
```

---

### Task 14: The parity script counts securities whose `observed` flag differs (decision i)

A line the seeds-only run derives is `observed=false` there and `observed=true` in a full run, where the caller kept
observing it. `scripts/seeds_parity.py` gains `observed_flag_differs`: the securities both runs have whose `observed` column
differs, with its case list. It is reported and printed, never floored: `drops` skips it and `--write-floor` does not
write it.

**Files:**
- Modify: `scripts/seeds_parity.py`, `tests/test_seeds_parity.py`

**Interfaces:** consumes each run's `securities.csv` (`sec_id`, `observed`). Produces the ninth number in `parity(...)["numbers"]`.

- [ ] **Step 1: Write the failing test**

In `tests/test_seeds_parity.py`: `_run` writes `securities.csv` with an `observed` column (`"sec_id,observed"`, and each entry of
`securities` is `"<sec_id>,<observed>"`); `_two_runs` passes `["A,true", "B,true", "C,true", "D,true", "E,true"]` for the full run and
`["A,true", "B,false", "C,true", "D,true", "F,false"]` for the seeds run (B is derived there); the expected `numbers` gain
`"observed_flag_differs": 1`, and after it

```python
    assert got["cases"]["observed_flag_differs"] == [{"sec_id": "B", "full_observed": "true", "seeds_observed": "false"}]
```

In `test_check_fails_only_above_the_floor`, after `assert json.loads(floor.read_text())["endings_lost"] == 1`:

```python
    assert "observed_flag_differs" not in json.loads(floor.read_text())          # reported, never floored
    floor.write_text(json.dumps({"endings_lost": 1, "observed_flag_differs": 0}))
    assert seeds_parity.main([*args, "--check"]) == 0                             # above a floor it was given: still no drop
    assert seeds_parity.main([*args, "--write-floor"]) == 0
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_seeds_parity.py -q -o addopts=""`
Expected: fail on the numbers (the key is missing).

- [ ] **Step 2: The number**

In `scripts/seeds_parity.py`: after `SCORE_KEYS`:

```python
# Reported, never floored: a line the seeds-only run derives from the fails rows is unobserved there and observed in a
# full run (the caller kept observing it), so the number says how many of the full run's lines are derived.
NOT_FLOORED = ("observed_flag_differs",)
```

in `parity`, replace the two `securities.csv` set lines by

```python
    f_obs = {r["sec_id"]: r.get("observed", "") for r in _rows(full / "securities.csv")}
    s_obs = {r["sec_id"]: r.get("observed", "") for r in _rows(seeds / "securities.csv")}
    f_sec, s_sec = set(f_obs), set(s_obs)
```

add to `cases`, before `"seeds_placed_differently"`:

```python
        "observed_flag_differs": [{"sec_id": k, "full_observed": f_obs[k], "seeds_observed": s_obs[k]}
                                  for k in sorted(f_sec & s_sec) if f_obs[k] != s_obs[k]],
```

and in `drops` and `--write-floor`:

```python
    return [f"{k}: {floor[k]} -> {v}" for k, v in sorted(numbers.items())
            if k in floor and k not in NOT_FLOORED and v > floor[k]]
```

```python
        new = {k: min(v, floor.get(k, v)) for k, v in result["numbers"].items() if k not in NOT_FLOORED}
```

Update the module docstring's list of numbers by one line. Run the test file (expected: 3 passed), the whole suite, then:

```bash
git add scripts/seeds_parity.py tests/test_seeds_parity.py
git commit -m "The parity script reports securities whose observed flag differs"
```

---

### Task 15: Parity checkpoint after S2 (network)

**Outcome (2026-10-10):** Steps 1 to 3 were run on `c80928c`. The full run moved away from the truth set, so no
floor was written and S2 went back into Tasks 16 and 17; Task 18 is the checkpoint after them. See "Checkpoint 3".

The controller runs it, as Tasks 3 and 5, on the head after Task 14. The reference for the full run is Checkpoint 2's
full run (`pout-full2`, commit `26eefdb`); the reference for the numbers is `data/seeds_parity.json`.

- [ ] **Step 1:** make sure no other SEC client is running (Task 3, Step 1).
- [ ] **Step 2:** the full input at the head on a copy of the cache the last full run left, then the seeds on a copy of the
  cache that run leaves (Task 3, Step 3's commands). Expected: both exit 0 with no degraded answer. New SEC requests are
  expected in both runs: on the prototype a derived era's issuer and FIGI lookups were 29 requests in the full run and 98 in
  the seeds run (offline misses, `sec` and `figi`).
- [ ] **Step 3:** judge the full run against Checkpoint 2's: `scripts/seeds_parity.py --full output-of-checkpoint-2 --seeds <new full>`
  lists what moved; `scripts/scorecard.py --check --base 26eefdb` must pass (a golden or diagnosis `pass` case that fails
  stops the task). Expected to move: eight derived eras (AAN, BXS, CCE 2016, GCI, SDRL, UNIT, WCN, WE: the last table of
  "Condition 2 and the test of a name"), five new `observed=false` securities of their own (2,201 to 2,206), and one era whose security changed (IACI@2008-01-16
  from its placeholder to the IAC FIGI line, which the warm fails index showed: check it against the line follow's own fold).
  Judge each of the eight against EDGAR and the truth sets: a derived line that merged into the old line's FIGI (UNIT, WE),
  one with no issuer (AAN), one whose old line became a `handoff_continuation` where the full run had a merger (WCN keeps
  its merger: `handoff_conflict`), each is a correction or a regression; a regression goes through the diagnosis loop.
- [ ] **Step 4:** the parity numbers, full against seeds, against the floor: `scripts/seeds_parity.py --full <full> --seeds <seeds> --cases <dir> --check`
  must exit 0 (no number above `data/seeds_parity.json`). Then the acceptance list below, each ticker looked up in the case
  lists. `observed_flag_differs` is reported (expected: about as many as the seeds run derived, 34 securities on the prototype),
  with its case list. Coverage of tickers and securities, `left_view` and `closed_no_event` are compared with Checkpoint 2's.
- [ ] **Step 5:** SEC requests and wall time against Checkpoint 2 (full 262 s, seeds 376 s): on the prototype the repeat
  rounds cost 15 to 20 s (the identity stage) plus stage 4b's pass (see "Decision (e)"); report the run manifest's
  `stages` and request counts for both runs.
- [ ] **Step 6:** only when 3 to 5 are done: `scripts/seeds_parity.py ... --write-floor`; record the date, the commit, the
  numbers before and after, the eight steps' verdicts and the acceptance list under "Checkpoints" ("Checkpoint 3: S2");
  commit `data/seeds_parity.json` with the plan, message "Seeds-only parity after S2: the floor".

Acceptance (S2's list): none of ARRS, STE, CR, BG, AVGO, CI, MRVL, APO, DKNG, NCNO, TEAM, AZPN, FWONA, FWONK, DTV, ATVI,
CLWR, ALEX, SPB, CIT, DOW, MRK, FOXA (the new line exists), ANN, EVHC, AMSG, ANAT, MYL, ENDP, FERG, WFT, MNST, NE, NRF, NLSN,
TCF, WEN, MIR, TWC, LVNTA is in the parity case lists. A name that is: report which stage did not produce the line
(a refusal the rule leaves alone: `no_filing`, `bankruptcy`, `unsettled`; a step stage 4b was not asked about; a new line under another
ticker: AMSG, DISCA, MYL 2020; a description that names nothing: WW, 2U; LGFA/LGFB: Starz).

### Task 16: A continuation by timing across two issuers needs the price to carry over (S2, reworked)

**Why.** Checkpoint 3 (S2 as first built) found the full run worse. Seadrill 2018 (`BBG000BKQ3V3`) was a bankruptcy
drop and became a one-for-one continuation into the derived line of new Seadrill: the old row is `unknown` through
stages 5 to 9, stage 9b (`pipeline._handoffs`) now finds a pair with the derived line, `decide_handoff` rule 2 says
continuation on `timing:cusip` (two issuers, the ticker's fails rows switch CUSIP within `CONTINUATION_DAYS`),
`apply_handoffs` rewrites an `unknown` row, and stage 9e's plan-bankruptcy step skips a row that has a successor. The
same rule wrote a new continuation row from Aaron's Holdings into The Aaron's Company, the spin-off that took the ticker
AAN in 2020. Neither is the holders' shares carried over one for one, and the fails rows already say so: the price went
from 0.10 to 18.50 (Seadrill) and from 62.93 to 18.41 (Aaron's).

Measured over every pair both full runs decided on `timing:cusip` (`E/s2reg/endings/band.csv`): the ratio of B's first
fails price to A's last is 0.89 for GGP 2010 (the one continuation row that is right), 0.99 FTI, 1.03 WCN, 1.01 BXS,
1.14 IGT, 0.71 CCE 2010 and 0.69 GCI (merger rows that stand anyway); outside 0.5 to 2.0 are Seadrill 185, Aaron's 0.29,
EVHC 3.10 (a merger row that stands anyway) and NWS-A 2013 0.46 (a continuation that is wrong today: the old issuer
lived on as Twenty-First Century Fox). One pair has no price (WEN 2009: no fails row on A's side). Same-issuer pairs
(`timing:cik`) are left alone: a one-to-three reclassification (LMCA, LMCK 2016) moves the price and is still the same
issuer's line.

**The rule.** In `decide_handoff` rule 2, a CUSIP switch between two issuers is evidence of a continuation only when
the price carried over: B's first fails price under the ticker is between 0.5 and 2.0 times A's last. When either price
is missing the rule is as before. The rule is the same for an observed line and a derived one. A same-issuer pair
(`same_issuer`) does not read the price.

**Files:**
- Modify: `src/delist_detection/endings/handoffs.py` (`cusip_switch`, a new `switch_price_ratio`, `decide_handoff`)
- Modify: `src/delist_detection/pipeline.py` (`_handoffs`, the `decide_handoff` call near line 983)
- Test: `tests/test_handoffs.py`, `tests/test_pipeline.py`
- Docs: `docs/data-flow.md` (the handoff rules near line 854), `docs/architecture.md` (the `handoffs` entry under
  "endings/"), `README.md` (the `handoff_continuation` flag row, only if its wording becomes untrue)

**Interfaces:**
- Consumes: `FtdRow(date, cusip, symbol, description, price)` with `price: float | None` (the prior trading day's close;
  `sources/ftd.py`), `FtdIndex.by_symbol(ticker)`, `HandoffPair`.
- Produces: `handoffs.CARRIED_PRICE: tuple[float, float] = (0.5, 2.0)`;
  `handoffs.switch_price_ratio(ftd: FtdIndex, pair: HandoffPair, a_cusips: Sequence[str], b_cusips: Sequence[str]) -> float | None`;
  `decide_handoff(..., price_ratio: float | None = None)`. `cusip_switch` keeps its signature and its answers.

- [ ] **Step 1: Write the failing tests** in `tests/test_handoffs.py` (import `switch_price_ratio` and `CARRIED_PRICE`
  beside `cusip_switch`):

```python
def test_the_price_across_a_cusip_switch_is_bs_first_over_as_last():
    """Seadrill 2018: G7945E105 last fails under SDRL at 0.10, G7998G106 first at 18.50."""
    ftd = FtdIndex([FtdRow("2018-06-20", "G7945E105", "SDRL", "SEADRILL LTD", 0.21),
                    FtdRow("2018-07-03", "G7945E105", "SDRL", "SEADRILL LTD", 0.10),
                    FtdRow("2018-07-05", "G7998G106", "SDRL", "SEADRILL LTD NEW SHS", 18.50),
                    FtdRow("2018-07-09", "G7998G106", "SDRL", "SEADRILL LTD NEW SHS", 19.00)])
    p = _pair("2018-07-03", "2018-07-05", ticker="SDRL")
    assert switch_price_ratio(ftd, p, ["G7945E105"], ["G7998G106"]) == pytest.approx(185.0)
    assert switch_price_ratio(ftd, p, ["G7945E105"], ["G7945E105"]) is None       # no switch: no ratio
    assert switch_price_ratio(ftd, p, ["G7945E105"], ["99999Z999"]) is None
    for a_price, b_price in ((None, 18.50), (0.10, None), (0.0, 18.50), (0.10, 0.0)):
        gap = FtdIndex([FtdRow("2018-07-03", "G7945E105", "SDRL", "SEADRILL LTD", a_price),
                        FtdRow("2018-07-05", "G7998G106", "SDRL", "SEADRILL LTD NEW SHS", b_price)])
        assert cusip_switch(gap, p, ["G7945E105"], ["G7998G106"])                 # the switch itself still holds
        assert switch_price_ratio(gap, p, ["G7945E105"], ["G7998G106"]) is None   # a price missing or not above zero
    far = FtdIndex([FtdRow("2018-01-04", "G7945E105", "SDRL", "SEADRILL LTD", 0.30),
                    FtdRow("2018-07-05", "G7998G106", "SDRL", "SEADRILL LTD NEW SHS", 18.50)])
    assert switch_price_ratio(far, p, ["G7945E105"], ["G7998G106"]) is None       # where `cusip_switch` does not hold


@pytest.mark.parametrize("ratio,kind", [
    (185.0, None),            # Seadrill 2018: a bankruptcy plan's new shares
    (0.29, None),             # The Aaron's Company 2020: a spin-off that took the ticker
    (0.46, None),             # NWS-A 2013
    (0.49, None), (2.01, None),
    (0.5, "continuation"), (2.0, "continuation"),
    (0.89, "continuation"),   # GGP 2010
    (None, "continuation"),   # no price on one side (WEN 2009): as before
])
def test_a_cusip_switch_between_two_issuers_is_a_continuation_only_when_the_price_carried_over(ratio, kind):
    d = decide_handoff(_pair("2015-06-12", "2015-06-15"), filing=None, same_issuer=False, cusip_switch=True,
                       price_ratio=ratio)
    assert (d.kind if d else None) == kind
    if d is not None:
        assert d.evidence == "timing:cusip"


def test_the_price_is_not_read_for_one_issuer_or_against_a_filing():
    """LMCA 2016: one share became three of the same issuer's; the price fell to 0.487 and the line is the same."""
    p = _pair("2016-04-15", "2016-04-18")
    d = decide_handoff(p, filing=None, same_issuer=True, cusip_switch=True, price_ratio=0.487)
    assert (d.kind, d.evidence) == ("continuation", "timing:cik")
    d = decide_handoff(p, filing=FILING, same_issuer=False, cusip_switch=True, price_ratio=185.0)
    assert d.kind == "continuation" and d.by_filing


def test_a_switch_whose_price_did_not_carry_over_can_still_be_a_takeover():
    """An older issuer taking the ticker at another price: rule 3 still answers."""
    p = _pair("2015-06-12", "2015-06-15")
    d = decide_handoff(p, filing=None, same_issuer=False, cusip_switch=True, price_ratio=185.0,
                       b_issuer_since="2010-01-04")
    assert (d.kind, d.evidence) == ("takeover", "timing:issuer")
```

  `_pair`, `FILING`, `FtdIndex` and `FtdRow` are the helpers the file already uses. If `_pair`'s signature differs from
  these calls (read it first), keep the dates and adapt the call.

- [ ] **Step 2: Run them and see them fail.** `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_handoffs.py -q`.
  Expected: an ImportError for `switch_price_ratio`, then, once it exists, failures on the ratios outside the band.

- [ ] **Step 3: Implement** in `src/delist_detection/endings/handoffs.py`. One helper finds the two rows, so
  `cusip_switch` and the ratio cannot disagree about which rows they mean:

```python
CARRIED_PRICE = (0.5, 2.0)   # B's first fails price over A's last: a share for a share keeps the price about there


def _switch_rows(ftd: FtdIndex, pair: HandoffPair, a_cusips: Sequence[str],
                 b_cusips: Sequence[str]) -> tuple[FtdRow, FtdRow] | None:
    """A's last fails row and B's first under the pair's ticker, where the ticker switches CUSIP at the handoff
    (both within `CONTINUATION_DAYS` of B's first sighting); None without a switch."""
    rows = ftd.by_symbol(pair.ticker)
    a_rows = [r for r in rows if r.cusip in a_cusips]
    b_rows = [r for r in rows if r.cusip in b_cusips and r.cusip not in a_cusips]
    if not a_rows or not b_rows:
        return None
    last, first = a_rows[-1], b_rows[0]
    if all(abs(_days(pair.b_first, d)) <= CONTINUATION_DAYS for d in (last.date, first.date)):
        return last, first
    return None


def cusip_switch(ftd: FtdIndex, pair: HandoffPair, a_cusips: Sequence[str], b_cusips: Sequence[str]) -> bool:
    """(the docstring it has today)"""
    return _switch_rows(ftd, pair, a_cusips, b_cusips) is not None


def switch_price_ratio(ftd: FtdIndex, pair: HandoffPair, a_cusips: Sequence[str],
                       b_cusips: Sequence[str]) -> float | None:
    """B's first fails price over A's last across the pair's CUSIP switch (`cusip_switch`): each the prior trading
    day's close. None without a switch, or when either row has no price above zero. A share that became one share
    keeps the price about where it was (GGP 2010: 17.39 to 15.40); a bankruptcy plan's new shares (Seadrill 2018:
    0.10 to 18.50) and a spin-off that takes the ticker (The Aaron's Company 2020: 62.93 to 18.41) do not."""
    rows = _switch_rows(ftd, pair, a_cusips, b_cusips)
    if rows is None:
        return None
    a, b = rows[0].price, rows[1].price
    return b / a if a and b and a > 0 and b > 0 else None
```

  In `decide_handoff`: the new keyword `price_ratio: float | None = None`; rule 2 of the docstring says "or the
  ticker's CUSIP switches from A's to B's (`cusip_switch`) at about the same price (`price_ratio` within
  `CARRIED_PRICE`, or unknown)"; and the condition becomes

```python
    carried = price_ratio is None or CARRIED_PRICE[0] <= price_ratio <= CARRIED_PRICE[1]
    if (abs(pair.gap) <= CONTINUATION_DAYS and not existed and not lived_on and not issuer_carries_on
            and (same_issuer or (cusip_switch and carried))):
        return HandoffDecision(pair, "continuation", TIMING_CIK if same_issuer else TIMING_CUSIP, False)
```

  In `pipeline._handoffs`, compute the two CUSIP lists once per pair and pass both answers:

```python
        a_cusips, b_cusips = sec_cusips.get(p.a, []), sec_cusips.get(p.b, [])
        decision = decide_handoff(p, filing=filing, same_issuer=same,
                                  cusip_switch=cusip_switch(ftd, p, a_cusips, b_cusips),
                                  issuer_carries_on=issuer_carries_on(p, securities, first_seen),
                                  b_issuer_since=since.isoformat() if since else None,
                                  price_ratio=switch_price_ratio(ftd, p, a_cusips, b_cusips))
```

- [ ] **Step 4: A whole-run test that the run passes the price** in `tests/test_pipeline.py`. Find the whole-run test
  that today ends in a continuation by `timing:cusip` between two issuers (grep the file for `timing:cusip` and for
  `handoff_continuation`; `test_a_continuation_the_finder_found_no_row_for_clips_the_old_line_at_its_last_sighting`
  and `test_a_handoff_continuation_clips_the_old_line_whose_ticker_the_issuer_still_lists` are the candidates). Add a
  sibling of it in the same fixture world whose fails rows carry a price of 0.10 on the old CUSIP's last row and 18.50
  on the new CUSIP's first: the run writes no `handoff_continuation` row and no successor for the old line. Keep the
  original test green with prices that carry over (or none). If no whole-run test reaches `timing:cusip` between two
  issuers, build one from the nearest (two securities, two issuer CIKs, one ticker, a CUSIP switch a day apart) and say
  so in the report. Prove the wiring by mutation: with `price_ratio=` removed from the call in `_handoffs` the new
  test fails.

- [ ] **Step 5: Run the suite.** `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`. Expected:
  3,977 passed plus the new tests, 44 xfailed. Task 13's three tests (`test_a_derived_line_after_wendys_international...`
  and its two neighbours) pass no `price_ratio` and stay as they are. A golden or committed-output test that fails is a
  finding to report, not something to adjust.

- [ ] **Step 6: The five-ticker run.** `bash E/s2reg/sub_run.sh t16 SDRL CSAL UNIT CCE AAN` with
  `CODE=<a clone of the worktree's tree>` is not possible from the worktree (no `.env` there), so use the snapshot
  recipe: `cp -cR E/psnap-full4 E/s2reg/t16code`, copy the three changed source files over the clone's, and run
  `CODE=E/s2reg/t16code bash E/s2reg/sub_run.sh t16 SDRL CSAL UNIT CCE AAN` with `allowed_domains: ["api.openfigi.com"]`
  (`E` is `/private/tmp/claude-501/-Users-royeli-repo-github-com-delist-detection/a6c3c0f4-120e-40f6-9019-80889ff3e772/scratchpad/exec`).
  Expected, read with `E/rows_of.py E/s2reg/out-t16 BBG000BKQ3V3 BBG00VSH86G4`: Seadrill's row is a `liquidation`
  (code 470, reason "Bankruptcy plan exchange ...") with no successor, as in `E/pout-full3`; Aaron's Holdings
  (`BBG00VSH86G4`) has no continuation row into `BBG00WCNDCZ6`. UNIT, CSAL and CCE are as in `E/s2reg/out-smoke`
  (another task has them). Put the output of `rows_of.py` in the report.

- [ ] **Step 7: Docs and commit.** Update the three docs named above (the rule, the constant, the two examples). Commit
  with the message "A continuation by timing across two issuers needs the price to carry over" and the trailer lines
  the dispatch gives.

**Not in this task:** the issuer of a derived era, the UNIT/CSAL split, stage order (9e stays after 9b), the
`timing:cik` rule, `apply_handoffs`.

### Task 17: A derived era is checked against the step it came from (S2, reworked)

**Why.** Checkpoint 3 (S2 as first built) found two things wrong with a derived era's identity. Both come from one
gap: the era does not know which refused step it came from, so nothing checks its answers against that step.

1. *It joined the line it was refused from although the shares did not carry over one for one.* Uniti 2025: stage 4b
   refuses the step 91325V108 to 912932100 under UNIT (`merged_out`); the derived era resolves to New Uniti (CIK
   2020795) and OpenFIGI gives the new CUSIP the composite `BBG002B67HB2`, which the old UNIT era holds by ticker. The
   era joins the old security, the security takes the new issuer, stage 4b no longer folds the CSAL placeholder into it
   (`line_follow.py`, the fold needs one issuer), and the line runs on, so the 2025-08-01 merger ending is gone. The
   truth set rules this a stock merger at 0.6029 New Uniti share per share, and a continuation is "same holders, same
   claim, one for one". The fails rows show it: 4.91 on the old CUSIP's last row, 8.09 on the new one's first, a ratio
   of 1.65. In the seeds run the same happens to IR 2020 (0.25: Gardner Denver took the name and ticker) and ENR 2015
   (0.26: the spin-off took the ticker), and to CFFN 2010 (0.44) and WE 2023 (32, a 1-for-40 reverse split). The joins
   whose price carried over are right and stay: MDT 0.996, MYL 1.01, WEC 0.996, ICE 0.986, PRGO 0.986, ACN 0.971, and
   CLWR (no price).
2. *It took the old line's issuer under a composite of its own.* Coca-Cola Enterprises 2016: the derived era (CCE,
   G25839104, from 2016-06-01) is Coca-Cola European Partners plc (CIK 1650107), but the name search ranks the old
   registrant 1491675 first because its Form 25 and Form 15 of 2016 lie nearer the lookup dates. Every resolver tier
   looks for the registrant that delisted near the date, and for a derived era that is the old line's issuer. With
   1491675 the Form 25 is ambiguous between two securities, the finder builds no merger row, the handoff writes a
   continuation, and the CCEP line reads as unlisted. Aaron's Holdings 2020 (706688 for 1808834) and, in the seeds run,
   IGT 2015 (353944 for 1619762) are the same. All three steps were refused as `merged_out`, which stage 4b says when
   the old issuer files no periodic report after the step: by stage 4b's own finding that issuer cannot be the issuer
   of the line after the step. CHTR 2016 keeps its issuer on both sides and is rightly left alone: its step is
   `other_registrant`, not `merged_out`.

A prototype of the two rules is at `E/s2reg/identity/proto` (diff against the code of c80928c:
`E/s2reg/identity/proto.diff`; its rule "U" is not wanted, its "X1" and "X2" are the two halves of what follows). Read
the diff for where the origin travels and where the resolver filters candidates; write the real thing with tests.
`E` is `/private/tmp/claude-501/-Users-royeli-repo-github-com-delist-detection/a6c3c0f4-120e-40f6-9019-80889ff3e772/scratchpad/exec`.

**The rules.**

- **Origin.** `derivable` returns, for each `(ticker, new CUSIP)` pair, the step it came from:
  `DerivedFrom(sec_id, issuer_cik, why, old_cusip, first)`: the refused security's id and issuer CIK (as that round's
  securities give them), the refusal (`merged_out`, `other_registrant`, `name`), the step's old CUSIP and the step's
  first day. `identify` gives each derived era its origin (`TickerEra.derived_from`), matched by the era's ticker and
  one of its CUSIPs.
- **Rule J (the join).** A derived era whose security is the one its step was refused from (`resolutions[era].sec_id
  == derived_from.sec_id`) is made only when the price carried over across the step: the ratio of the new CUSIP's first
  fails price under the ticker to the old CUSIP's last one on or before it is within `CARRIED_PRICE`, or either price
  is missing or not above zero. Otherwise the era is not made: the step stays refused, as before S2. The issuers play
  no part in rule J.
- **Rule X (the issuer).** A derived era from a `merged_out` step whose issuer answer is the origin's issuer
  (`derived_from.issuer_cik`, not None) while its security is another one than the origin's, and which has no pin (no
  `cik_pin`, no `sec_id_pin`, answer source neither `manual` nor `cik_map`), is asked again with the origin's issuer
  excluded from every resolver tier's candidates. What that lookup answers stands: another issuer, or none (the era
  then keeps its composite with no issuer, as an era without an issuer does today). A weak answer stands only if the
  era's own fails rows fit it, which `_resolve_issuers` already does for every era. An answer the second pass
  (`EraIssuers.infer`) or `check_names` gives is filtered the same way.
- **One constant.** `CARRIED_PRICE` becomes `(2 / 3, 3 / 2)` and is defined once, in the identity package, and
  `endings/handoffs.py` imports it (endings may import identity; identity may not import endings). Task 16's rule in
  `decide_handoff` reads the same constant. Measured: no pair of either full run or of the seeds run lies between 0.5
  and 2/3 or between 1.5 and 2.0 except the second CI step of the seeds run (1.96, a merger row that stands either way).
- **Verdicts carry over the rounds.** `identify` takes and returns the verdicts on derived pairs:
  `verdicts: Mapping[tuple[str, str], str]`, values `"not_made"` (rule J) and `"without_old_issuer"` (rule X). A pair
  with `"not_made"` is not derived at all; a pair with `"without_old_issuer"` is asked with the exclusion from the
  start. After stage 3 `identify` checks every derived era that has no verdict yet; if the check gives new verdicts it
  computes stages 1 to 3 again with them (the result must equal a fresh `identify` call given the enlarged verdicts)
  and checks again, at most `MAX_VERDICT_PASSES = 3` times, then goes on with what it has and logs it.
  `Identity.verdicts` holds the final mapping. `identify_with_lines` passes each round's verdicts to the next, and a
  pair with `"not_made"` is never counted as new.
- **The memo.** A lookup with an exclusion uses its own memo key (the prototype's suffix `|!<cik>` after the usual
  key), so an answer found without a candidate is never read by a lookup with it, and no memo `__version__` bump is
  needed. Every place that builds a memo key for the degraded check (`is_degraded` and whatever calls it from
  `_resolve_securities`) must build the same key for an excluded lookup.
- **Logs.** One line each when it happens, naming the eras by key:
  `derived eras not made: N whose price did not carry over onto the line they came from (UNIT@2025-08-05, ...)` and
  `derived eras asked without the old line's issuer: N (CCE@2016-06-01, ...)`.

**Files:**
- Modify: `src/delist_detection/identity/observations.py` (`DerivedFrom`, `TickerEra.derived_from`)
- Modify: `src/delist_detection/identity/derived_lines.py` (`derivable` returns the mapping; the loop carries verdicts)
- Modify: `src/delist_detection/identity/identity.py` (`identify`, `_refine`/`refine_eras` take the mapping's keys,
  `_resolve_issuers` takes the exclusions, the check after stage 3, `Identity.verdicts`)
- Modify: `src/delist_detection/identity/ticker_resolver.py` (`resolve(..., exclude=())`, the tiers, the memo key)
- Modify: `src/delist_detection/endings/handoffs.py` (imports `CARRIED_PRICE`; no rule change)
- Create if it helps the import order: one small module in `identity/` for `CARRIED_PRICE`, `step_price_ratio` and
  `price_carried` (identity.py and handoffs.py both import it; `derived_lines.py` imports identity.py, so the helpers
  cannot live there). `tests/test_import_closure.py` must stay green.
- Test: `tests/test_derived_lines.py`, the identity tests Tasks 10 to 12 added (find them by `derive=`), the resolver
  tests (`tests/test_ticker_resolver*.py`), `tests/test_handoffs.py` (the band's edges), `tests/test_pipeline.py`
- Docs: `docs/architecture.md` (the `derived_lines`, `identity` and `ticker_resolver` entries), `docs/invariants.md`
  (the section Task 12 extended for derived lines), `docs/data-flow.md` (the handoff band, and derived lines where it
  describes them), `CONTEXT.md` only if it defines a derived line

**Interfaces:**
- Consumes: `RefusedStep(sec_id, step, why)` and its step's fields (read `line_follow.py` for the names of the old
  CUSIP, the new CUSIP and the first day); `FtdIndex.by_symbol`, `FtdRow.price`; `EraIssuers.rows_fit`;
  `TickerResolver.resolve`; Task 16's `handoffs.CARRIED_PRICE`, `switch_price_ratio`.
- Produces:
  - `observations.DerivedFrom` (frozen dataclass: `sec_id: str`, `issuer_cik: int | None`, `why: str`,
    `old_cusip: str`, `first: str`); `TickerEra.derived_from: DerivedFrom | None = None`.
  - `derivable(refused, securities, profile) -> dict[tuple[str, str], DerivedFrom]` (the keys are the pairs it
    returned before; the first step that names a pair wins).
  - `CARRIED_PRICE: tuple[float, float] = (2 / 3, 3 / 2)`; `price_carried(ratio: float | None) -> bool` (True for
    None); `step_price_ratio(ftd: FtdIndex, ticker: str, old_cusip: str, new_cusip: str) -> float | None`.
  - `identify(..., derive: Mapping[tuple[str, str], DerivedFrom] = {}, verdicts: Mapping[tuple[str, str], str] = {})`
    (an immutable empty default); `Identity.verdicts: Mapping[tuple[str, str], str]`.
  - `TickerResolver.resolve(..., exclude: Collection[int] = ())`.

**What the tests must pin** (write each before the code that makes it pass; name the tests after the behaviour):

1. `derivable` returns the origin of each pair: the security id, its issuer, the refusal, the old CUSIP, the first day;
   two refused steps naming one pair keep the first.
2. `step_price_ratio`: new CUSIP's first price under the ticker over the old CUSIP's last one on or before it; None when
   either side has no row under the ticker, or a price is None or not above zero. `price_carried`: None is True; 2/3
   and 3/2 are inside; 0.66 and 1.51 are outside.
3. Rule J: a derived era that resolves to its origin's security with prices 4.91 then 8.09 is not made (no era, no
   security, the old security exactly as with no `derive` at all, compare the two `Identity` results field by field for
   the old security and for the eras); with 75.59 then 75.26 it is made and joined; with no price on one side it is
   made and joined; an era that resolves to another security is not judged by rule J whatever the prices (185).
4. Rule X: a derived era from a `merged_out` step whose first answer is the origin's issuer under another composite is
   asked again with `exclude` and takes the second answer; when the second lookup finds nothing the era has no issuer
   and its security is still made; an era from an `other_registrant` or `name` step keeps the origin's issuer; an era
   with a `cik_pin`, or whose answer's source is `manual`, keeps it; an era joined to its origin (same security) keeps
   it.
5. The resolver: `resolve(..., exclude={c})` never answers `c` from any tier (one test per tier the prototype diff
   touches: the company-ticker map, the EFTS lookup, the name search, the agreeing-issuer fallback, the frequency
   tier), and the memo holds the two answers under two keys (a lookup without `exclude` after one with it still
   answers `c`, and the other way round).
6. Verdicts: `identify` given `verdicts={pair: "not_made"}` equals `identify` without that pair in `derive`;
   given `{pair: "without_old_issuer"}` it asks with the exclusion at once (the first-pass lookup without it is not
   made: count the resolver calls); `Identity.verdicts` holds what the check found; `identify_with_lines` passes them
   on, and a pair with `"not_made"` does not keep the loop going (the loop ends when no other pair is new).
7. No change without derived eras: with `derive` empty `identify` makes the same calls and returns the same result
   as before this task (the existing no-change tests of Tasks 10 and 12 stay green untouched).
8. The handoff band: in `tests/test_handoffs.py` the parametrized edges move to the new band (0.66 and 1.51 no
   continuation; 0.67 and 1.5 a continuation); 0.46, 0.29, 185, 0.89 and None keep their answers. `handoffs.py`
   defines no band of its own.
9. A whole-run test in `tests/test_pipeline.py`, in the fixture world Task 12's whole-run test uses: the derived era
   joins its origin's composite and the price did not carry over; the run's tables are those of the same run with no
   derived line for that pair (the old security's history and its ending are unchanged), and the log has the
   "not made" line.

Prove by mutation, and restore: rule J's price test removed (test 3 fails); rule X's `why == "merged_out"` widened to
all three refusals (test 4 fails); the memo suffix removed (test 5 fails); the verdicts not passed to the next round
(test 6 fails).

- [ ] **Step 1:** read `E/s2reg/identity/proto.diff`, `identity/derived_lines.py`, the parts of `identity/identity.py`
  the diff touches, and `line_follow.py`'s `RefusedStep` and step types. Read the tests Tasks 10 to 12 added.
- [ ] **Step 2:** tests 1, 2 and 8 with their code (`DerivedFrom`, `derivable`'s mapping, the price helpers, the
  constant's move). Run `tests/test_derived_lines.py tests/test_handoffs.py tests/test_import_closure.py`.
- [ ] **Step 3:** tests 3, 6 and 7 with rule J and the verdicts.
- [ ] **Step 4:** tests 4 and 5 with rule X and the resolver's `exclude`.
- [ ] **Step 5:** test 9, the four mutations, then the whole suite:
  `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -p no:cacheprovider`. Expected: 3,991 passed
  plus the new tests, 44 xfailed. A golden or committed-output test that fails is a finding to report, not to adjust.
- [ ] **Step 6: the five-ticker run.** Clone the snapshot (`cp -cR E/psnap-full4 E/task17/code`), copy the worktree's
  whole `src/delist_detection` tree over the clone's, and run
  `CODE=E/task17/code bash E/s2reg/sub_run.sh t17 SDRL CSAL UNIT CCE AAN`. This run asks SEC for the excluded lookups
  (a handful of requests), so allow these hosts on that one Bash call: `data.sec.gov`, `www.sec.gov`, `efts.sec.gov`,
  `api.openfigi.com`, `api.nasdaq.com`, `www.nasdaqtrader.com`, `api.anthropic.com`. It must exit 0. Expected, read
  with `E/rows_of.py E/s2reg/out-t17 t:UNIT t:CSAL BBG000BF5RY1 BBG00B6BFWH9 BBG000D9V7T4 BBG00VSH86G4 BBG000BKQ3V3`:
  - UNIT: `BBG002B67HB2` has issuer 1620280, history CSAL then UNIT to 2025-08-01, and its merger row at 2025-08-01,
    as `E/pout-full3` has it; no security of CIK 2020795; no `CIK1620280-COMMON`.
  - CCE 2016 (`BBG000BF5RY1`): a merger with `acquirer_sec_id` `BBG00B6BFWH9`, cash 14.50 and stock ratio 1.0;
    `BBG00B6BFWH9` has issuer 1650107, history CCE then CCEP with no end, and no `unexplained_ending`.
  - AAN 2020 (`BBG000D9V7T4`): the 1:1 stock merger with acquirer `BBG00VSH86G4`; `BBG00VSH86G4` has no issuer and
    no row into `BBG00WCNDCZ6`; `BBG00WCNDCZ6` is not in the run.
  - Seadrill (`BBG000BKQ3V3`): a `liquidation`, code 470, no successor (Task 16).
  - the log has the "not made" line naming the UNIT era and the "asked without the old line's issuer" line naming the
    CCE and AAN eras.
  Put the `rows_of.py` output and the two log lines in the report. A result that differs is a finding: report it, do
  not tune the rules to it.
- [ ] **Step 7:** docs, then commit. Message: "A derived era is checked against the step it came from", with a body
  that names rule J, rule X and the one band, and the trailer lines the dispatch gives.

**Not in this task:** stage 4b's refusal reasons, the handoff rules beyond the constant's home, a price test on a
continuation by filing, the run-time cost of the rounds, an observed second era that joins by composite (a full run's
own join stays as it is).

### Task 18: Parity checkpoint after the rework of S2 (network)

**Outcome (2026-10-11):** run on `6395c78` after Task 17's two fix rounds (the second narrowed rule X to two
composites, found by this checkpoint's first seeds run). The floor was written. See "Checkpoint 4".

The controller runs it, as Tasks 3, 5 and 15, on the head after Task 17. The reference for the full run is the full
run before S2 (`pout-full3`, commit `0ec338f`); the reference for the numbers is `data/seeds_parity.json`.

- [ ] **Step 1:** make sure no other SEC client is running (Task 3, Step 1).
- [ ] **Step 2:** the full input at the head on a copy of the cache the last full run left (`pcache-full4`), then the
  seeds on a copy of the cache that run leaves. Expected: both exit 0 with no degraded answer; a few SEC requests for
  the lookups rule X asks without the old line's issuer.
- [ ] **Step 3:** judge the full run against `pout-full3`: `scripts/seeds_parity.py --full pout-full3 --seeds <new full>`
  lists what moved, `scripts/scorecard.py` on both gives `D.mismatches` and the cases. Expected: SDRL 2018 and UNIT 2025
  as before S2 (both `pass` cases pass); CCE 2016 a merger priced through the derived CCEP line (cash 14.50 plus one
  share), its `known_wrong` case better than before S2; AAN 2020 the 1:1 stock merger with one `handoff_conflict`; GCI
  2019 and ODP 2025 priced; WCN and BXS unchanged; WE as before S2 (its derived era is not made). `D.mismatches` at or
  below 149 and no `pass` case failing that passed at `0ec338f`. New rows on derived lines are listed with a verdict
  each (the two `unexplained_ending` rows of BancorpSouth Bank and new Seadrill are expected). No observed era with
  another issuer (`issuers_moved.py`). Anything else that moved is judged against EDGAR and the truth sets; a
  regression goes back into the tasks.
- [ ] **Step 4:** the parity numbers, full against seeds, against the floor:
  `scripts/seeds_parity.py --full <full> --seeds <seeds> --cases <dir> --check` must exit 0. Then Task 15's acceptance
  list, each ticker looked up in the case lists; `observed_flag_differs` with its case list; coverage, `left_view` and
  `closed_no_event` against Checkpoint 2. The verdicts of rules J and X in the seeds run are listed from the log
  (expected not made: UNIT, CFFN, WE, IR, ENR; expected asked without the old issuer: CCE 2016, AAN, IGT) and each
  era rule X touched is compared with the full run's issuer for that line.
- [ ] **Step 5:** SEC requests and wall time against Checkpoint 3's table.
- [ ] **Step 6:** only when 3 to 5 are done: `scripts/seeds_parity.py ... --write-floor`; record the date, the commit,
  the numbers before and after, the verdicts and the acceptance list under "Checkpoints" ("Checkpoint 4: S2
  reworked, the floor"); commit `data/seeds_parity.json` with the plan, message "Seeds-only parity after S2: the floor".

---

### Open points of S2

1. **Stage 4b's cost in a repeat round.** See "Decision (e)".
2. **The warm fails index.** The second pass reads an index stage 4b enlarged (rows by CUSIP and symbol over the whole window).
   On the prototype it left 2,446 of 2,448 eras (seeds) and 2,614 of 2,615 (full) with the same FIGI and issuer; the others are
   IAC@2012-06-29 and IACI@2008-01-16 (seeds), IACI@2008-01-16 (full), each from the placeholder CIK891103-COMMON to
   BBG000BKQG80. What would settle it: the Task 15 comparison of those eras with stage 4b's fold of the placeholder.
3. **A derived line that merges into the old line's FIGI** (UNIT, WE, and in the seeds run ACN, CB, CFFN, CLWR, ENR, ICE, IR, MDT,
   MYL, PRGO, WEC): OpenFIGI says one security, so the era joins it and the refused step is, in effect, followed. This is what a
   full run does with an observed second line. What would settle it: the eight full-run steps' verdicts at Task 15.
4. **A derived line's issuer.** AAN, ENDP and TMA found none in the prototype's seeds run (their descriptions are abbreviated). Task 6's
   row check keeps a wrong weak answer out; an answer that is not found leaves the line without an issuer, so without a Form 25
   search. What would settle it: how many of the 34 derived securities have no CIK at Task 15.
5. **A derived line the fixture world does not list** gets an `unexplained_ending` row (the Ashland test). In a real run a line
   listed today has none. What would settle it: `V.uncertain_securities` at Task 15 against Checkpoint 2.
6. **`line_follow_refused:<why>` items for derived steps are gone** from `review.csv` (the step is held by the derived security in the last
   round); the run log keeps `derived lines: round n derives k (ticker, CUSIP) pairs`. If the review rows are wanted, a
   `derived_line` info flag needs an entry in `review_triage.CATALOG`.
7. **The name test refuses two real continuations**: LGFA/LGFB (Lions Gate to Starz Entertainment: the issuer's name until the step is
   Lions Gate) and WW, 2U (no issuer word in the description). They stay as today.
8. **The wording of Review Focus 4.** The WEN pair is called a continuation by timing and the merger row stands; the pair is not
   called a continuation in any published table. Whether `decide_handoff` should say takeover for it is a change to the handoff
   stage, left alone by decision (h).

## S3: A seed at a takeover (needs decision A)

`scripts/seeds_from_observations.py` gains `--security-history PATH` (a previous run's
`contract/security_history.csv`). A row becomes a seed when the security holding its ticker on
its date differs from the one holding it on the ticker's previous snapshot. Without the option the
script behaves as today. Test with FOXA: holder BBG of Twenty-First Century Fox to 2019-03-19,
the Fox Corp line after; the 2019-06-30 row becomes a seed. This depends on S2, which is what
puts the new holder's line into `security_history`.

### Task 19: A seed where the ticker's holder changed (S3, decision A)

**Why.** `scripts/seeds_from_observations.py` reduces the caller's observations to seeds: a ticker's first snapshot, a
return after a snapshot it was missing from, or a new name. It cannot see a ticker that passed to another security
while the caller kept holding it under a name that still agrees: FOXA 2019 (Twenty-First Century Fox to Fox Corp;
`names_agree` accepts the pair), IR 2020 (Ingersoll-Rand plc to the former Gardner Denver), CFFN 2010. No filing says
this; it is a fact about what the caller holds. Decision A's recommendation, applied here as a ruling: a caller whose
snapshots carry an identifier gets a seed when the identifier changes; a caller without one gives the seed builder a
previous run's `contract/security_history.csv`, and a row becomes a seed when the security holding its ticker on its
date is not the one that held it on the ticker's previous snapshot. The second route needs two passes for a first
run: seeds, a run, seeds again with that run's history.

**The rules.** Both are additions: a row that is a seed today stays one.

1. *An identifier changed.* For each of the columns `cusip`, `cik` and `sec_id` (the caller's pins; a column the file
   lacks is skipped): a row whose value is not blank and differs from the last non-blank value the ticker carried in an
   earlier row is a seed. Blank values never make a seed and never reset the remembered value.
2. *The holder changed* (`--security-history PATH`). The holders of a ticker on a day are the set of `sec_id`s whose
   history row has that ticker and a span containing the day (`start_date <= day`, and `end_date` blank or `>= day`).
   A row is a seed when the ticker's holders on its date differ from the holders on the date of the ticker's previous
   row and the two sets are not both empty. A ticker the history never names gets no seed from this rule. Without the
   option the script reads no history and behaves as today.

**Files:**
- Modify: `scripts/seeds_from_observations.py`
- Test: `tests/test_seeds_from_observations.py`
- Docs: `docs/commands.md` (the script's entry: the option, the two passes), the script's own docstring

**Interfaces:**
- Consumes: `contract/security_history.csv` with the columns `sec_id,issuer_id,start_date,end_date,ticker,security_name,share_class`
  (ISO dates; `end_date` blank for a line that has not ended). Only `sec_id`, `start_date`, `end_date` and `ticker` are read.
- Produces: `seeds(rows, history=None)` where `history` is the list of that file's rows as dicts (None: rule 2 off);
  `holders(history, ticker, day) -> frozenset[str]` (or the same thing behind an index built once; the rule above is
  the contract); the CLI option `--security-history PATH`. The output file keeps the input's columns and row order
  as today (by ticker, then date).

- [ ] **Step 1: Write the failing tests** in `tests/test_seeds_from_observations.py` (the file loads the script as
  `mod`; `_o(ticker, as_of, name)` builds a row with blank pins):

```python
def _h(sec_id, ticker, start, end=""):
    return {"sec_id": sec_id, "issuer_id": "1", "start_date": start, "end_date": end, "ticker": ticker,
            "security_name": "", "share_class": "COMMON"}


def _keys(rows):
    return [(r["ticker"], r["as_of"]) for r in rows]


FOXA = [_o("FOXA", "2018-06-30", "TWENTY FIRST CENTURY FOX INC CLASS"),
        _o("FOXA", "2018-12-31", "TWENTY FIRST CENTURY FOX INC CLASS"),
        _o("FOXA", "2019-06-30", "FOX CORP CLASS A"), _o("FOXA", "2019-12-31", "FOX CORP CLASS A")]


def test_without_a_history_the_fox_rows_give_one_seed():
    assert _keys(mod.seeds(FOXA)) == [("FOXA", "2018-06-30")]
    assert _keys(mod.seeds(FOXA, history=None)) == [("FOXA", "2018-06-30")]


def test_a_row_is_a_seed_when_another_security_holds_its_ticker_than_on_the_previous_snapshot():
    """FOXA 2019: Twenty-First Century Fox to 2019-03-19, the Fox Corp line after."""
    history = [_h("BBGOLD", "FOXA", "2013-07-03", "2019-03-19"), _h("BBGNEW", "FOXA", "2019-03-20")]
    assert _keys(mod.seeds(FOXA, history=history)) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]


def test_a_row_after_its_tickers_line_ended_is_a_seed_once():
    """The previous run ended the line and has no line after it: the first snapshot past the end is a seed, the
    next is not (no holder before, no holder now)."""
    history = [_h("BBGOLD", "FOXA", "2013-07-03", "2019-03-19")]
    assert _keys(mod.seeds(FOXA, history=history)) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]


def test_one_security_under_the_ticker_all_along_gives_no_extra_seed():
    history = [_h("BBGONE", "FOXA", "2013-07-03", "2018-12-31"), _h("BBGONE", "FOXA", "2019-01-01")]
    assert _keys(mod.seeds(FOXA, history=history)) == [("FOXA", "2018-06-30")]
    assert _keys(mod.seeds(FOXA, history=[_h("BBGX", "ZZZ", "2000-01-03")])) == [("FOXA", "2018-06-30")]


def test_the_span_ends_are_inside_and_two_holders_are_a_set():
    rows = [_o("AAA", "2010-06-30", "ALPHA"), _o("AAA", "2010-12-31", "ALPHA"), _o("AAA", "2011-06-30", "ALPHA")]
    exact = [_h("S1", "AAA", "2010-06-30", "2010-12-31"), _h("S2", "AAA", "2011-01-01")]
    assert _keys(mod.seeds(rows, history=exact)) == [("AAA", "2010-06-30"), ("AAA", "2011-06-30")]
    both = [_h("S1", "AAA", "2010-01-04"), _h("S2", "AAA", "2010-01-04")]
    assert _keys(mod.seeds(rows, history=both)) == [("AAA", "2010-06-30")]
    joins = [_h("S1", "AAA", "2010-01-04"), _h("S2", "AAA", "2011-01-03")]
    assert _keys(mod.seeds(rows, history=joins)) == [("AAA", "2010-06-30"), ("AAA", "2011-06-30")]


def test_a_changed_identifier_is_a_seed_and_a_blank_one_is_not():
    def row(as_of, **pins):
        return {**_o("AAA", as_of, "ALPHA"), **pins}
    rows = [row("2010-06-30", cusip="111111111"), row("2010-12-31"), row("2011-06-30", cusip="111111111"),
            row("2011-12-31", cusip="222222222"), row("2012-06-30", cik="5"), row("2012-12-31", cik="6"),
            row("2013-06-30", sec_id="BBG1"), row("2013-12-31", sec_id="BBG1")]
    assert _keys(mod.seeds(rows)) == [("AAA", "2010-06-30"), ("AAA", "2011-12-31"), ("AAA", "2012-12-31")]
    bare = [{"ticker": "AAA", "as_of": d, "name": "ALPHA"} for d in ("2010-06-30", "2010-12-31")]
    assert _keys(mod.seeds(bare)) == [("AAA", "2010-06-30")]            # a file without pin columns


def test_the_cli_reads_the_history_file(tmp_path, monkeypatch, capsys):
    import csv
    obs, hist, out = tmp_path / "obs.csv", tmp_path / "security_history.csv", tmp_path / "seeds.csv"
    with obs.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(FOXA[0]))
        w.writeheader()
        w.writerows(FOXA)
    with hist.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(_h("x", "x", "x")))
        w.writeheader()
        w.writerows([_h("BBGOLD", "FOXA", "2013-07-03", "2019-03-19"), _h("BBGNEW", "FOXA", "2019-03-20")])
    monkeypatch.setattr("sys.argv", ["seeds_from_observations.py", "--observations", str(obs), "--out", str(out),
                                     "--security-history", str(hist)])
    assert mod.main() == 0
    with out.open(newline="") as fh:
        assert _keys(list(csv.DictReader(fh))) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]
    assert "2 seeds from 4 observations" in capsys.readouterr().out
```

- [ ] **Step 2: Run them and see them fail** (`seeds()` takes no `history`; the pin rule does not exist):
  `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_seeds_from_observations.py -q -p no:cacheprovider`.
- [ ] **Step 3: Implement.** Build the history index once (ticker to its spans); keep `seeds()` a pure function of its
  arguments; the existing condition stays as the first test and the two rules are `or`-ed onto it. A history file with
  a missing column is a bad input: exit 2 with one stderr line naming the file and the column, as the project's CLIs do
  for bad input files (add a test for it if the script gains that branch).
- [ ] **Step 4:** the existing test and the new ones pass; run the whole suite once
  (`PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -p no:cacheprovider`; expected 4,042 passed
  plus the new tests, 44 xfailed).
- [ ] **Step 5: Try it on the real files** (offline, no run of the pipeline). `E` is
  `/private/tmp/claude-501/-Users-royeli-repo-github-com-delist-detection/a6c3c0f4-120e-40f6-9019-80889ff3e772/scratchpad/exec`.
  - `PYTHONPATH=src <python> scripts/seeds_from_observations.py --observations data/observations.csv --out E/task19/seeds-plain.csv`:
    2,589 seeds, and the file equals `E/seeds.csv` byte for byte.
  - the same with `--security-history E/pout-seeds5/contract/security_history.csv --out E/task19/seeds-history.csv`:
    report the number of seeds and list every added seed (ticker, date, the holders before and on the date), at most
    80 lines; say how many are "the line ended and nothing holds the ticker" and how many "another security holds it".
  Put both in the report. Do not judge the added seeds; the controller measures them with a run.
- [ ] **Step 6:** docs, then commit: "The seed builder cuts a seed where the ticker's holder changed", with the
  trailer lines the dispatch gives.

**Not in this task:** anything in `src/`, `classify_universe.py`, the parity script, the floor.

### Task 20: Two small follow-ups (stage 4b's rename scan; the seed builder's ticker spelling)

Two unrelated small changes, one commit each, in this order.

#### Part A: the rename scan computes each first word once (equal result)

**Why.** A repeat round of the derived-line loop runs stage 4b again, about 75 s warm. A profile put most of a warm pass
in `line_follow.renamed_cusips`: for every fails row of the window it calls `_first_word` on the row's description and
again on every candidate name (28 million calls of the regex). The names do not change inside the loop. Measured on a
prototype: about 10 s less per stage 4b pass, the same result.

**The change** (`src/delist_detection/identity/line_follow.py`, `renamed_cusips` only): build the names by their first
word once, before the loop, and look the row's first word up in it:

```python
    by_first: dict[str, list[str]] = defaultdict(list)        # the names by their first word, computed once
    for n in names:
        by_first[_first_word(n)].append(n)
    rows: dict[str, list[str]] = defaultdict(list)
    for r in ftd.every_row(date.fromisoformat(lo), date.fromisoformat(hi) + timedelta(days=NAME_DAYS)):
        if r.cusip not in cusips and is_line_symbol(r.symbol) \
                and any(description_names(r.description, n) for n in by_first.get(_first_word(r.description), ())):
            rows[r.cusip].append(r.date)
```

Nothing else in the function changes. The answer must be the same set for every input, including a name or a
description with no word at all (both give the first word `""` and are compared with each other today) and two names
that share a first word.

**Tests** (`tests/test_line_follow*.py`, wherever `renamed_cusips` is tested today; find it by grep):
- the existing tests of `renamed_cusips` stay green untouched;
- one new test that pins equality with the old expression on a constructed index: keep the old expression as a small
  reference function inside the test file (the generator with `_first_word(r.description) == _first_word(n) and
  description_names(r.description, n)`), and assert `renamed_cusips` returns what a reference implementation built on it
  returns for an index whose rows cover: a description that names the new name; one that shares only the first word;
  one that matches only the name's second word; a name beginning with THE; two names with one first word; an empty
  description. If building a reference implementation means copying most of `renamed_cusips`, instead assert the
  expected set for each of those rows by hand and say so in the report.
- Prove the new test bites: break the lookup (for example `by_first.get(_first_word(n), ())` with a wrong key) and see it
  fail; restore.

**Check on real data.** Clone the snapshot and run the five tickers as Tasks 16 and 17 did:
`cp -cR E/psnap-full7 E/task20/code`, copy the worktree's `src/delist_detection` over the clone's, then
`CODE=E/task20/code bash E/s2reg/sub_run.sh t20 SDRL CSAL UNIT CCE AAN` with these hosts allowed on that one call:
`data.sec.gov`, `www.sec.gov`, `efts.sec.gov`, `api.openfigi.com`, `api.nasdaq.com`, `www.nasdaqtrader.com`,
`api.anthropic.com`. Every CSV under `E/s2reg/out-t20` must equal the one under `E/s2reg/out-t17c` byte for byte
(`E/same_tables.py E/s2reg/out-t17c E/s2reg/out-t20` prints "0 differ"). The controller checks the full universe.
`E` is `/private/tmp/claude-501/-Users-royeli-repo-github-com-delist-detection/a6c3c0f4-120e-40f6-9019-80889ff3e772/scratchpad/exec`.

Commit: "The rename scan computes each first word once".

#### Part B: the seed builder compares tickers as the history spells them

**Why.** `contract/security_history.csv` spells a ticker through `normalize_ticker`
(`src/delist_detection/vocabulary/identifiers.py`: `.`, `/` and spaces become `-`, upper case).
`scripts/seeds_from_observations.py` (Task 19) compares the observation's ticker with the history's as raw strings, so a
caller whose file says `BF.B` or `brk b` gets nothing from `--security-history` for those tickers, and no warning.

**The change** (`scripts/seeds_from_observations.py`): the history index is keyed by `normalize_ticker(ticker)` and the
lookup normalizes the observation's ticker the same way. Nothing else changes: the grouping of the observations by
ticker, the output rows and their spelling stay as they are.

**Tests** (`tests/test_seeds_from_observations.py`), written first:

```python
def test_the_history_is_read_through_the_tickers_normal_spelling():
    rows = [_o("BF.B", "2010-06-30", "BROWN FORMAN"), _o("BF.B", "2010-12-31", "BROWN FORMAN"),
            _o("BF.B", "2011-06-30", "BROWN FORMAN")]
    history = [_h("S1", "BF-B", "2010-01-04", "2010-12-31"), _h("S2", "BF-B", "2011-01-03")]
    assert _keys(mod.seeds(rows, history=history)) == [("BF.B", "2010-06-30"), ("BF.B", "2011-06-30")]
    lower = [{**r, "ticker": "bf b"} for r in rows]
    assert _keys(mod.seeds(lower, history=history)) == [("bf b", "2010-06-30"), ("bf b", "2011-06-30")]


def test_two_rows_on_one_date_and_overlapping_spans_of_one_security():
    rows = [_o("AAA", "2010-06-30", "ALPHA"), _o("AAA", "2010-12-31", "ALPHA"), _o("AAA", "2010-12-31", "ALPHA")]
    history = [_h("S1", "AAA", "2010-01-04", "2010-12-31"), _h("S1", "AAA", "2010-06-01")]
    assert _keys(mod.seeds(rows, history=history)) == [("AAA", "2010-06-30")]
```

See the first fail for the missing normalization; the second may already pass (it pins behaviour the review asked to
have pinned): say which.

Commit: "The seed builder reads the history through the ticker's normal spelling".

#### Both parts

Run the whole suite once at the end (`PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -p no:cacheprovider`;
expected 4,050 passed plus the new tests, 44 xfailed). Update `docs/commands.md` if Part B changes what it says about
the option; Part A needs no doc change unless a doc describes the scan's inner loop.

**Not in this task:** any other part of `line_follow.py`; reusing stage 4b's results between rounds; the seed rules.

## S4: Smaller causes

Each needs a short trace before a plan, because none was followed to the deciding line.

- **C5, endings of added successors are never valued.** Run the valuation of stage 8 over
  `_successor_endings`' delistings as well. Independent of seeds; can be done at any time.
- **C4, share class from the latest observed name.** Read the class from the CUSIP's fails
  description or OpenFIGI's row, and fall back to the observed name. Cases: CBS, CBG, WCRX.
- **C3, seeds whose ticker did not trade on the seed date.** APTV, ITT, SUNW, MEL. Needs
  decision C. Required test whichever side fixes it: a seed with no fails rows under its ticker
  within 400 days stays unfollowed and is listed in `uncertain.csv`.
- **A Form 25 outside the security's life.** The delisting finder judges a Form 25 only inside
  the security's span, which it reads from the security's trading record
  (`endings/trading_record.py` `last_seen`, `known_until`), not from `era_last_seen`. S1 does not
  reach it. Cases: SUNW (a placeholder with no CUSIP, so no rows to carry it), VIACA (Form 25 of
  2025-08-07, last seen 2023-09-14 in the seeds-only run).
- **Unexplained.** WLL; CEG 2008 (issuer blank after S1); DNB 2020 (issuer blank in the subset
  test, where the fails index was cut at 2024-08-03: recheck at Task 3).

### Task 21: Three smaller causes (S4): a late Form 25, the seed builder's class words, stage 4b's text sources

Three independent changes, one commit each, in this order. Each cause was traced on real data and its rule tried in an
instrumented clone; read the clone's patch before you write the real thing, and do not copy its environment switches.
`E` is `/private/tmp/claude-501/-Users-royeli-repo-github-com-delist-detection/a6c3c0f4-120e-40f6-9019-80889ff3e772/scratchpad/exec`.
The two reference runs are the full run `E/pout-full8` and the seeds run `E/pout-seeds7h` (seed file
`E/seeds-hist.csv`, cache it left `E/pcache-seeds7h`, code snapshot `E/psnap-seeds7h`).

#### Part A: a Form 25 after the security's last observation

**Why.** `DelistingFinder.find` (`src/delist_detection/endings/delistings.py`) keeps a Form 25 of the issuer only if
the security is alive at it (`_alive_at`: from its first sighting to its last seen plus `SIBLING_ALIVE_AFTER_DAYS`,
400) or traded within 30 days of it. In a seeds run a security with no fails rows of its own ends its span at its last
seed: Sun Microsystems (SUNW, last seed 2008-05-31, Form 25 2010-01-26), Liberty Ventures (LVNTA, history to
2016-12-30, Form 25 2018-03-19), Paramount class A (VIACA/PARAA, sightings to 2023-12-31, Form 25 2025-08-07). The
filing is skipped, the fallback writes a continued-filings or an unexplained row, and the full run, whose
observations reach the end, has the merger. A last observation says the caller held the security then; it does not
say the security ended there.

**The rule.** When no reference date makes the security alive at a Form 25, the filing is still kept if the
security's last sighting is one of the caller's observations (not a fails row) and the filing's date is after it.
Everything else about the scan (`_judge`, the class title, the sibling and tie rules) applies to it as to any kept
filing. The tried patch is `E/s4/endings/patch4.py` (its switch is `S4RULEA`); the trace's account is in the ledger
entry "S4 step zero, endings trace".

**Tests** (in the finder's test file, with its fixtures): a security whose last sighting is an observation 600 days
before its issuer's Form 25, with no fails row after it, gets that Form 25's ending; the same security whose last
sighting is a fails row 600 days before the filing does not (it stopped trading: today's behaviour); a Form 25 before
the last observation is not kept by this rule; a second security of the same issuer that is alive at the filing still
owns it (the rule does not take a filing from a security the existing rules give it to). Prove the first by removing
the rule.

**Check on real data:**
`CODE=<your clone of E/psnap-seeds7h with the worktree's src copied over> OBSFILE=E/seeds-hist.csv SRC_CACHE=E/pcache-seeds7h bash E/s2reg/sub_run.sh t21a SUNW JAVA VIACA PARAA VIAC LVNTA QVCA QRTEA`
(hosts for every `sub_run.sh` call in this task: `data.sec.gov`, `www.sec.gov`, `efts.sec.gov`, `api.openfigi.com`,
`api.nasdaq.com`, `www.nasdaqtrader.com`, `api.anthropic.com`). Expected, read with `E/rows_of.py`: SUNW
`CIK709519-COMMON`, VIACA `BBG000BWDFD4` and LVNTA `BBG0038K9G41` each end as in `E/pout-full8` (a merger; LVNTA's
dlret 0.024523). Put the rows in the report; a difference is a finding to report, not to tune.

Commit: "A Form 25 after the last observation of a security with no later row is kept".

#### Part B: the seed builder keeps a row when the class words change, and the row after an unheld one

**Why.** (1) `scripts/seeds_from_observations.py` cuts a seed on a new name only when `names_agree` fails. "DISCOVERY
HOLDING CO" and "DISCOVERY INC SERIES A" agree, so the seeds run never learns the class, its Discovery security is
class COMMON, and the 2022 successor search ties (DISCA and DISCK end as mergers where the full run has the
continuation into WBD). (2) With `--security-history`, the first snapshot after a ticker changed hands can fall in the
days when nobody holds it (GCI 2015-06-30: old Gannett left the ticker on 06-26, the new Gannett began 07-01). That
row is a seed, but its era cannot tell the two lines apart, and the next snapshot, which sits in the new line, is not
a seed because the holders are "nobody" on both dates.

**The rules,** both additions (`or`-ed on, as the pin and history rules are):
3. A row is a seed when its name and the ticker's previous row's name are both non-blank and give different share
   classes. Use the package's own reader of a class from a name (the function `build_securities` and
   `placeholder_id` rely on; find it by grep for `share_class_from_name`), not a new one.
4. With a history: a row is a seed when the ticker's previous row became a seed by the holder rule (rule 2: its
   holders differed from the row before it) and nobody held the ticker on that previous row's date (its holder set
   was empty). A seed made by rule 4 itself, or by any other rule, does not trigger rule 4: one extra seed per run of
   unheld snapshots, not one per snapshot.

**Tests** (`tests/test_seeds_from_observations.py`, written first):

```python
def test_a_row_whose_name_changes_only_its_class_words_is_a_seed():
    rows = [_o("DISCA", "2008-12-31", "DISCOVERY HOLDING CO"), _o("DISCA", "2009-06-30", "DISCOVERY HOLDING CO"),
            _o("DISCA", "2009-12-31", "DISCOVERY INC SERIES A"), _o("DISCA", "2010-06-30", "DISCOVERY INC SERIES A")]
    assert mod.names_agree(rows[1]["name"], rows[2]["name"])            # the name rule alone does not cut here
    assert _keys(mod.seeds(rows)) == [("DISCA", "2008-12-31"), ("DISCA", "2009-12-31")]
    blank = [_o("AAA", "2010-06-30", "ALPHA CORP CLASS A"), _o("AAA", "2010-12-31", ""),
             _o("AAA", "2011-06-30", "ALPHA CORP CLASS A")]
    assert _keys(mod.seeds(blank)) == [("AAA", "2010-06-30")]            # a blank name is no class change


def test_the_row_after_an_unheld_seed_is_a_seed_once():
    """GCI 2015: old Gannett held the ticker to 2015-06-26 and the previous run has no line after it."""
    rows = [_o("GCI", d, "GANNETT CO INC") for d in ("2014-12-31", "2015-06-30", "2015-12-31", "2016-06-30")]
    history = [_h("BBGOLD", "GCI", "2008-01-02", "2015-06-26")]
    assert _keys(mod.seeds(rows, history=history)) == [("GCI", "2014-12-31"), ("GCI", "2015-06-30"),
                                                       ("GCI", "2015-12-31")]
    held = [_h("BBGOLD", "GCI", "2008-01-02", "2015-06-26"), _h("BBGNEW", "GCI", "2015-06-29")]
    assert _keys(mod.seeds(rows, history=held)) == [("GCI", "2014-12-31"), ("GCI", "2015-06-30")]
    assert _keys(mod.seeds(rows)) == [("GCI", "2014-12-31")]             # no history: rule 4 is off
```

If "DISCOVERY HOLDING CO" and "DISCOVERY INC SERIES A" do not give two classes with the package's reader, or
`names_agree` does not hold for them, stop and report what they give.

**Check on real data** (offline): build `E/task21/seeds-b.csv` with
`--security-history E/pout-seeds7h/contract/security_history.csv` and report how many seeds it has against the 2,742
of `E/seeds-hist.csv` built with the same history by the code before this part (build that one too, as
`E/task21/seeds-before.csv`), how many rows each new rule added, and the added rows of DISCA, DISCK and GCI.

Commit: "The seed builder keeps a class change and the row after an unheld seed".

#### Part C: stage 4b reads the text sources for a line that moved and then stopped

**Why.** `line_follow.follow_lines` reads `text_sources` (the 8-K text that names a new ticker or CUSIP) only in its
first round and only for a line with no step. Reliant Energy (RRI) takes a step in round 1 (75952B105 to 74971X107,
RRI Energy), so the later step to GenOn (GEN, 37244E107) is never looked for; the seeds run lacks `BBG000BDB3H1`'s
later life and Mirant's merger into it is valued at assumed par. The full run observes GEN.

**The rule.** The text sources are read in every round for a line that took a step in an earlier round and has no
further step in this one (once per line and end, so a line is not read twice for the same end). The tried patch is
the `TEXTALL` switch in `E/s4/identity/code3` (diff it against `E/psnap-seeds7h`); the trace's account is in the
ledger entry "S4 step zero, identity trace".

**Tests** (in stage 4b's test file, with its fixtures): a line whose first step is found from the fails rows and whose
second step is named only by an 8-K's text takes both; a line with no text source behaves as today; the text of a
line's end is read once however many rounds follow (count the reads). Prove the first by restoring the
`round_no == 1` condition.

**Check on real data:** `... sub_run.sh t21c RRI GEN MIR` on the seeds side (the same `CODE`, `OBSFILE`,
`SRC_CACHE` as Part A). Expected: the RRI seed's security is `BBG000BDB3H1` with tickers RRI and GEN as in
`E/pout-full8`, and Mirant's merger (`BBG000DQV8M1`) names it as acquirer with the full run's dlret (0.056399). Report
the run's SEC request count for stage 4b from its log (`line follow: N EDGAR requests`).

Commit: "Stage 4b reads the text sources for a line that moved and then stopped".

#### All parts

Run the whole suite once at the end (expected 4,053 passed plus the new tests, 44 xfailed). Update the docs that
describe each rule: `docs/architecture.md` (the `delistings`, `line_follow` entries), `docs/invariants.md` where it
states the finder's alive test or stage 4b's rounds, `docs/commands.md` for the seed builder, the script's docstring.

**Not in this task:** making an unobserved CUSIP run between two seeds an era (the ITT and XRX cause); the tie rule
of the successor search; anything about derived lines; the parity floor.

**Outcome (2026-10-11):** Parts B and C were built (`5f6ebe8`, `84f8637`). Part A was built, checked and not
kept: see "Checkpoint 6".

## S5: Acceptance

1. Decision B: delete `cache/ticker_resolution.json`, rerun the full input, judge it with the
   scorecard gate, commit the rebuilt outputs on their own.
2. Run Task 3's two runs again. `seeds_parity.py --check` passes, and the numbers meet decision D.
3. Apply the flip rule (`scripts/scorecard.py --flip`) to the full run.
4. Add the roadmap entry in `docs/superpowers/plans/2026-10-02-delist-library-reset.md` under
   "Risk to measure first: seeds-only input": the date, the parity numbers before and after, and
   that qlib_practice may send seeds only (reset-3q).

## Self-review

- **Spec coverage.** "Its dated ticker history to its real end or to today, not to its last
  sighting in the index": S1 and S2. "Handoff links (continuation, takeover)": S2 (the line
  exists) and its fourth design point. "Under-seeding is the risk": S3. "Seeds that resolve to
  one security merge": unchanged, and S2 relies on it.
- **Not step by step.** S2 to S5 are specified, not broken into steps. S2's depends on Task 3's
  case lists and on its step zero, which decides between two designs; S3 on decision A; S4 on
  short traces.
- **Reviewed.** An independent review on 2026-10-10 followed Tasks 1 and 2 literally on a copy
  of the code: the tests fail and pass as the steps say, and the whole suite passed. It checked
  the parity numbers and the line references. What changed after it: C1 now says the date feeds
  the issuer lookup only (the delisting finder reads the trading record); Task 2 removes the cap
  on the fails window, which had cut both subset tests at 2024-08-03; Task 3 makes its reference
  run with an empty memo, compares every era's issuer before and after S1, and writes the floor
  only after the check; S2 starts from the two stages that already follow a line (4b and 9) and
  no longer assumes a derived era; decision E was added and decision A reworded.
- **Types.** `era_last_seen(era, ftd, horizon_days=400, until=None) -> str` and
  `last_sightings(eras, ftd) -> dict[str, str]` are used with those names in Task 2's tests, code
  and call site. The parity script's eight number names are the same in its tests, its code and
  Task 3.

## Checkpoints

### Checkpoint 1: S1 as first built (Task 3, 2026-10-10)

Commits: `d999c39` (before Task 2) and `6299c06` (Task 2). All runs: `--as-of 2026-09-25
--extract-merger-terms-llm`, `claude-sonnet-5-5`, 8 SEC workers, no degraded answer, exit 0.

| Run | Code | Input | Cache | Time | SEC requests | LLM asked |
| --- | --- | --- | --- | --- | --- | --- |
| before | `d999c39` | full, no resolver memo | warm copy | 416 s | 1,226 | 0 |
| full | `6299c06` | full | copy of "before"'s | 366 s | 656 | 6 |
| seeds | `6299c06` | 2,589 seeds | copy of "full"'s | 322 s | 321 | 9 |

**What the old memo was holding up (decision B's evidence).** The same code and cache with the
old memo against none: 2 endings gained, 2 of another kind, 4 seeds placed differently, 1 truth
case failing. Northwest Airlines (BBG000RFD341) and WestRock (BBG008NXC572) lose their merger; US
Bancorp (BBG000FFDM15) and C3 AI (BBG00Y6G6X31) gain a blank uncertain ending; WW's four rows of
2012-2013 are unplaced. A rebuilt memo costs these five unless the resolver is fixed first. The
comparison was made against a run of the same code with the memo, not against the committed
`output/`, which older code built on other LLM answers.

**What S1 did to the full run ("before" against "full").** 21 eras got another issuer: 19
regressions, 1 correction (WFT@2009-03-20, to the Swiss parent 1453090), 1 wrong both times (AI).

| Cause | Eras |
| --- | --- |
| The name check reads the names in force within 30 days of the lookup date; a later rename rejects the right company | AMCX, DNOW, KAR, MDRX, ONL, WAFD |
| A stale era holds a later holder's CUSIP and is followed along it to 2026 | CCU 2008-11, STN |
| The Form 25 search at the new date finds another issuer's filing, taken although its name does not agree | AMB, ANN, BGC, MD |
| The 8-K frequency tier answers with a wrong company where the first pass used to miss and the second pass repaired it | COH, HCP, LIZ |
| The name window straddles the day a successor took the name | PLD |
| The old answer was a wrong fallback; now none | AI |
| Follow from the above, or rule B's window moved | PDX, WFSL, CEG |

603 of 2,615 eras were asked at another date. First pass at the new date: 504 the same CIK from
the same source, 58 the same CIK from another source, 6 another CIK, 12 an answer became a miss, 9
a miss became an answer, 14 a miss both times.

Scorecard, "before" to "full": `D.cases_matching` 275 to 271, `D.mismatches` 149 to 163, `G.pass`
45 to 43 (golden PLD-2015 and LIZ fail), `L1.coverage_tickers` 0.976115 to 0.973862,
`L1.coverage_securities` 0.979909 to 0.978568, unresolved observations 8 to 26,
`R1.2.figi_without_cik` 5 to 13, `V.uncertain_securities` 19 to 31.

**Parity at `6299c06`, full against seeds (not a floor).** `endings_lost` 2 (26 before S1),
`endings_gained` 12, `kind_changed` 32 (29), `value_or_date_changed` 17, `securities_lost` 26
(37), `securities_gained` 9, `seeds_placed_differently` 20, `truth_cases_failing_only_in_seeds`
24 (39). Coverage of tickers 0.973862 full and 0.968004 seeds; `left_view` 4 and 9;
`closed_no_event` 0 and 0. None of the 22 tickers S1 fixed in the subset test is under
`endings_lost` or `kind_changed` (CCE's second line is still under `securities_lost`: C2). 22 of
the 32 kind changes are a continuation in the full run and a merger in the seeds run (C2).
VIACA, MEL, MYL and SPB are still under `kind_changed`.

**Decision E: S1 as first built is not accepted.** It moves issuers away from the truth sets in
the full run. The floor was not written. The lookup was reworked (Task 4) after three offline
experiments on a replay of stages 1 and 2 that reproduces both real runs exactly. Each cell is
the number of eras (full) or seed rows (seeds) whose final issuer differs from the "before" run:

| Rule | Full (2,615 eras) | Seeds (2,589 rows) |
| --- | --- | --- |
| R0: the code before Task 2 | 0 | 64 |
| R1: Task 2 as built (one lookup, at the end of the rows) | 21 | 26 |
| R6: two lookups, the capped date's answer first when strong | 1 (CEG) | 26 |
| R7: R6 with the second pass's rule B at the capped date first | 0 | 26 |
| R9: Task 4's rule | 1 (WFT, the correction) | 14 |

R6 fixed 16 seed rows and broke 16: a seed's capped date is only 400 days after the seed, and an
answer there can be wrong although its name agrees (another company of the name: ITC, LENB, LPI,
NSAM, S), a weak answer there blocked the second pass (BKC, DISH, MAN), and a name-agreeing
frequency answer at the end was not taken (CCE, GGP, WRI). R9 answers each of these.

The 14 seed rows R9 leaves different from the "before" run:

- MRK 2008, MTCH 2015, SPB 2014: the seeds run names the company that carried the name on the
  seed date (old Merck 64978, old Match Group 1575189, old Spectrum Brands 1487730); the full run
  names the successor that took the ticker and the name later, because its era runs through the
  event. PLD 2008 is the same event and the full run names the predecessor there. S2 follows the
  line to the successor.
- WW 2012, CTL 2008, WRK 2015, TFC 2012: the seeds run has an issuer where the "before" run has
  none or another (WW 105319, CenturyLink 18926, WestRock 1636023, Truist 92230). To be checked
  against EDGAR at the next checkpoint; the first two are right.
- TT 2012: a weak answer where the "before" run has none.
- GHC 2012 (Graham Corp 716314 for Graham Holdings), ANN 2008, MEL 2008: wrong.
- AI 2021, CEG 2008, DHC 2012: no issuer.

Unknowns in the experiment: 53 seed lookups were not in the cache (AI, BBT, CA, CIT, EMC, IVZ, NU,
ONON, PCG, TWOU, USB, USG, XP). Task 5's real runs settle them.

**Found on the way, not fixed here.**

- The "before" run is not the truth everywhere: it gives US Bancorp the issuer 1045609 (Prologis).
- A stale era can hold only a later holder's CUSIP (CCU@2008-11-18: Cervecerias Unidas; STN:
  Stantec; UAG, ABI@2009, BSC@2008-11: exchange-traded notes). `_split_era` keeps any CUSIP with
  a run of three rows and checks descriptions only when the era is contested, and the follow then
  runs along it. Task 4's rule keeps the capped date's answer for these, so the issuer is not
  lost, but the followed date is wrong.
- BGC: on General Cable's own Form 25 day the full-text query returns BGC Partners' filing, an
  exact ticker-token hit taken without a name check (`ticker_resolver.py:938-940`).

**Decision B** is taken as recommended: the memo is rebuilt once, in its own commit, at S5. The
five securities above are its known cost today.

### Checkpoint 2: S1 reworked, the floor (Task 5, 2026-10-10)

Commit `26eefdb` (Task 4; the two commits after it change tests and docs only). Same flags as
checkpoint 1. Suite at the branch head: 3,921 passed, 44 xfailed.

| Run | Input | Cache | Time | SEC requests | LLM asked |
| --- | --- | --- | --- | --- | --- |
| full | full | copy of checkpoint 1's "full" | 262 s | 31 | 0 |
| seeds | 2,589 seeds | copy of this "full"'s | 376 s | 437 | 8 |

Both exit 0 with no degraded answer.

**The full run holds.** Against checkpoint 1's "before" run, one era has another issuer:
WFT@2009-03-20, from 1170565 (Bermuda, which had filed its Form 25 before the era began) to
1453090 (the Swiss parent). No ending is lost, gained or of another kind; the Bermuda line's
continuation gains its date (2009-02-25); the Swiss line is one new security
(`CIK1453090-COMMON`); no truth case fails that passed. Scorecard lines that differ: securities
2,190 to 2,191, placeholders 50 to 51, endings 891 to 892, `A.census.assumed_par.errors` 4 to 3.
No `D` line and no `G` line differs.

**Parity, full against seeds: the floor (`data/seeds_parity.json`).**

| Number | Before S1 (old memo in both runs) | S1 as first built | Reworked (the floor) |
| --- | --- | --- | --- |
| `endings_lost` | 26 | 2 | 2 |
| `endings_gained` | | 12 | 13 |
| `kind_changed` | 29 | 32 | 35 |
| `value_or_date_changed` | | 17 | 17 |
| `securities_lost` | 37 | 26 | 27 |
| `securities_gained` | | 9 | 8 |
| `seeds_placed_differently` | 25 | 20 | 19 |
| `truth_cases_failing_only_in_seeds` | 39 | 24 | 25 |

Coverage of tickers 0.976115 full, 0.971158 seeds; of securities 0.979918 and 0.972923;
`left_view` 4 and 8; `closed_no_event` 0 and 0.

The reworked numbers are not lower than S1's as first built, because that run hid differences:
both runs were wrong the same way where S1 broke the full run. What entered the lists is the
full run being right again (ANN, CEG 2008) or the seeds run finding more (WRK's merger of
2024-07-05, IAC's of 2020-06-30). What left them: PLD, PDX, IVGN. The seeds run itself is closer
to the truth sets than at checkpoint 1: `D.cases_matching` 253 to 256, `D.mismatches` 221 to 208,
`G.pass` 37 to 39, `R1.2.figi_without_cik` 14 to 5, `V.uncertain_securities` 35 to 21. The full
run stands at `D.cases_matching` 275, `D.mismatches` 149, `G.pass` 45.

Each seed row's issuer, seeds against full: 2,560 of 2,583 the same, 8 with none in both, 15
different (26 at checkpoint 1). MRK, MTCH, SPB: the old company (S2). ANN, GHC, MEL, AI: wrong.
CEG, DHC: none. WW, CTL, WRK, TFC: an issuer where the full run has none or another, to be
checked against EDGAR. TT, XP: a wrong weak answer at the seed's capped date where the full run
has none.

**The 22 tickers S1 fixed in the subset test.** None is under `endings_lost` or `kind_changed`.
CCE's second line is under `securities_lost` (C2). DNB 2020 is in no list. Still listed: ANN
(the seeds run takes a weak answer, University Bancorp, where the full run has Ann Inc), CEG
2008 (no issuer in the seeds run), VIACA, MEL, MYL, SPB (`kind_changed`).

**What the lists hold now.** 24 of the 35 `kind_changed` rows are a continuation in the full run
and a merger or an exchange in the seeds run, and most of `securities_lost` is the line after a
CUSIP change (C2: S2). `endings_lost`: ANAT's and AZPN's second lines (C2).

**Found at this checkpoint: weak answers are almost always wrong.** The resolver memo of the two
runs holds 16 `efts_frequency_name_mismatch` answers, all wrong (US Bancorp to Prologis, Burger
King to America Capital Corp, XP to a blank-check company), and 43 `efts_name_mismatch` answers,
about 37 of them wrong (Alcoa to Pliant Corp, Sprint to Merrill Lynch) and about 6 right (AZPN,
CMCSK, FNFV, MDC). Task 4 keeps a weak answer only when no pass infers an issuer; it still
stands unchecked then (full run: AI, AZPN, USB; seeds run: XP, TT, AI, ANN, MEL). A wrong issuer
makes the delisting search read another company's filings: XP gains an "expiration" ending in
the seeds run, and US Bancorp and C3 AI gained their blank endings when the memo was rebuilt
(checkpoint 1). The rule to add: a weak answer stands only when the era's own fails rows fit
that company (guard G's row test, `EraIssuers._fits_rows`), and never for an era with too few
rows to test. It goes first in S2's plan, because a followed line is looked up under a fails
description, where name mismatches are likely.

### Checkpoint 3: S2 as first built (Task 15, 2026-10-10)

Code `c80928c` (Tasks 7 to 12), run date 2026-09-25, `claude-sonnet-5-5`, `--sec-workers 8`. The full run on a copy of
the cache Task 6's full run left; the seeds run on a copy of the cache the full run left. No floor was written: the full
run moved away from the truth set, so S2 went back into Tasks 16 and 17.

| Run | Wall | SEC requests | Identity rounds | Eras | Securities |
|---|---|---|---|---|---|
| full, `0ec338f` (before S2) | 251 s | 0 | 1 | 2,615 | 2,200 |
| full, `c80928c` | 510 s | 51 | 3 (13 pairs, then 1) | 2,624 | 2,206 |
| seeds, `0ec338f` | 355 s | 390 | 1 | 2,448 | 2,152 |
| seeds, `c80928c` | 556 s | 436 | 3 (55 pairs, then 2) | 2,499 | 2,185 |

**The full run against the run before S2.** No observed era got another issuer (0 of 2,615). The diagnosis truth set got
worse: `D.mismatches` 149 to 166, `D.cases_matching` 275 to 273. Four truth cases moved, thirteen `delistings.csv` rows.

| Step | Before S2 | At `c80928c` | Verdict |
|---|---|---|---|
| GCI 2019 | merger, no value | priced: 6.25 cash plus 0.5427 of the derived acquirer line, dlret 0.022 | better |
| ODP 2025 (an added successor) | merger, no value | cash 28.00, dlret 0 (C5, Task 8) | better |
| WCN 2016, BXS 2017 | merger 1:1 | the same, one `handoff_conflict` each; BXS names the derived bank line as acquirer | same |
| WE 2023 | bankruptcy drop | the same; the derived era joined the old line (a reverse split) | same |
| AAN 2020 | merger 1:1 into Aaron's Holdings | continuation into Aaron's Holdings (derived with the old issuer 706688), which then "continues" into the spin-off The Aaron's Company | first hop the same value, second hop wrong |
| SDRL 2018 | bankruptcy drop (470) | continuation into new Seadrill, dlret 0 | worse, `pass` case fails on 8 fields |
| UNIT 2025 | merger at 2025-08-01; CSAL and UNIT one security | no ending; New Uniti joined the security; CSAL split off to a placeholder | worse, `pass` case fails |
| CCE 2016 | merger at assumed par | continuation into the derived CCEP line (derived with the old issuer 1491675); the CCEP line reads as unlisted | worse, `known_wrong` case 1 to 9 fields |

New `unexplained_ending` rows on derived lines: BancorpSouth Bank 2021-10-28 (it became Cadence Bank; the bank files
with the FDIC), new Seadrill 2022-02-22 (its second bankruptcy), CCEP 2026-09-03 (wrong: the issuer error).

**Causes (two trace agents, evidence `E/s2reg/`).**

- *SDRL.* The old row is `unknown` through stages 5 to 9. Before S2 no pair existed and stage 9e made it a bankruptcy
  plan exchange. Now stage 9b decides the pair with the derived line a continuation on `timing:cusip`, rewrites the
  `unknown` row, and 9e skips a row with a successor. Fails prices across the switch: 0.10 to 18.50. The same rule wrote
  the second AAN hop (62.93 to 18.41). Fixed by Task 16.
- *CCE and AAN Holdings.* The derived era took the old line's issuer: every resolver tier looks for the registrant that
  delisted near the date. With two securities under one CIK the Form 25 is ambiguous, the finder builds no merger row,
  and the handoff writes the continuation. Fixed by Task 17, rule X.
- *UNIT.* OpenFIGI gives New Uniti's CUSIP the composite the old UNIT era holds by ticker, so the derived era joined the
  old security although holders got 0.6029 share (fails prices 4.91 to 8.09). Fixed by Task 17, rule J.

**The price across a switch, measured** (`E/s2reg/endings/band.csv`, `band_filing.csv`, `derived_seeds.csv`).
Continuations on `timing:cusip` in the full runs: GGP 2010 0.89 (right); merger rows that stand anyway: IGT 1.14,
FTI 0.99, CCE 2010 0.71, WCN 1.03, BXS 1.01, GCI 0.69, EVHC 3.10; wrong: NWS-A 2013 0.46, SDRL 185, AAN 0.29; WEN 2009
has no price. Continuations by filing between two issuers: 17 of 20 between 0.918 and 1.106; AVGO 2016 reads 0.0075
because the new CUSIP's first fails row carries 1.00, so a price test on filing pairs would switch off a right
continuation, and none was added. Derived eras joined to their origin in the seeds run: MDT, MYL, WEC, ICE, PRGO, ACN
0.97 to 1.01, CLWR no price; UNIT 1.65, CFFN 0.44, WE 32, IR 0.25, ENR 0.26.

**The seeds run at `c80928c` against the full run at `c80928c`** (evidence only; both before Tasks 16 and 17):
endings_lost 0 (floor 2), endings_gained 6 (13), kind_changed 18 (35), value_or_date_changed 10 (17), securities_lost
17 (27), securities_gained 6 (8), seeds_placed_differently 18 (19), truth cases failing only in seeds 16 (25);
`observed_flag_differs` 40. Of 70 refused switch steps 55 became eras, 12 of them joined to their origin's security.
On almost every one the seeds run has the holder, the issuer and the ending the full run has; the exceptions are IGT
2015 (the old issuer, rule X), IR and ENR (wrong joins, rule J), CI 2018 and SPB 2018 (a merger where the full run has
a continuation by filing; not traced) and TMA 2008.

**Run time.** The identity stage and stage 4b run once per round: about 130 s a round in the full run. The task that
makes a repeat round recompute only what a derived pair touches (decision (e)) is still to do.

### Checkpoint 4: S2 reworked, the floor (Task 18, 2026-10-11)

Code `6395c78` (Tasks 7 to 17), run date 2026-09-25, `claude-sonnet-5-5`, `--sec-workers 8`. The full run on a copy of
the cache the last full run left; the seeds run on a copy of the cache the full run left. Both exit 0 with no degraded
answer.

| Run | Wall | SEC requests | Identity rounds | Eras | Rows of `securities.csv` |
|---|---|---|---|---|---|
| full, `0ec338f` (before S2) | 251 s | 0 | 1 | 2,615 | 2,225 |
| full, `6395c78` | 396 s | 0 | 2 (13 pairs) | 2,621 | 2,229 |
| seeds, `0ec338f` | 355 s | 390 | 1 | 2,448 | 2,205 |
| seeds, `6395c78` | 546 s | 437 | 3 (55 pairs, then 1) | 2,493 | 2,218 |

**The full run against the run before S2** (`pout-full3`). No observed era has another issuer (0 of 2,615). No ending
lost or gained, no seed placed differently, no truth case that fails only in the new run. `D.mismatches` 149 to 148,
`D.cases_matching` 275 to 276, `D.known_wrong_now_right` 2 to 3, `V.audit.confirmed_but_wrong` 21 to 20.

| Step | Before S2 | Now | Verdict |
|---|---|---|---|
| CCE 2016 | merger at assumed par | merger priced through the derived CCEP line (issuer 1650107, rule X): 14.50 cash plus one share, dlret 0.034 | better; its `known_wrong` case is right now |
| GCI 2019 | merger, no value | 6.25 cash plus 0.5427 of the derived acquirer line, dlret 0.022 | better |
| ODP 2025 | merger, no value | cash 28.00, dlret 0 (C5) | better |
| NWS-A 2013 | continuation into the spin-off that took the ticker | a transfer with no successor (the price fell to 0.46, Task 16) | the wrong link is gone; the row is still not the truth set's "no ending" |
| SDRL 2018, UNIT 2025, WE 2023 | | as before S2 (Task 16; rule J leaves UNIT's and WE's derived eras unmade) | same |
| AAN 2020 | merger 1:1 into Aaron's Holdings | the same, one `handoff_conflict`; Aaron's Holdings is a line with no issuer and no ending | same |
| WCN 2016, BXS 2017 | merger 1:1 | the same, one `handoff_conflict` each | same |

Four new securities, all `observed=false`: the GCI acquirer line, the CCEP line, new Seadrill, BancorpSouth Bank. Two
new `unexplained_ending` rows, both honest: BancorpSouth Bank 2021-10-28 (it became Cadence Bank and files with the
FDIC) and new Seadrill 2022-02-22 (its second bankruptcy). Counts that got worse: `R2.2.unknown_reason` 9 to 11 and
review rows 540 to 542 (those two rows); `L1.tickers_covered` 2,168 to 2,167, `left_view` 4 to 5 and
`transfer_no_successor` 4 to 5 (NWS-A).

**The seeds run against the full run.**

| Number | Floor of checkpoint 2 | Now (the new floor) |
|---|---|---|
| endings_lost | 2 | 0 |
| endings_gained | 13 | 8 |
| kind_changed | 35 | 16 |
| value_or_date_changed | 17 | 10 |
| securities_lost | 27 | 17 |
| securities_gained | 8 | 6 |
| seeds_placed_differently | 19 | 18 |
| truth_cases_failing_only_in_seeds | 25 | 16 |
| observed_flag_differs (not floored) | | 40 |

Coverage: tickers 0.9725 (full 0.9766), securities 0.9752 (full 0.9804), `left_view` 8 (full 5), `closed_no_event` 0.

**The rules' verdicts.** Full run: not made UNIT, WE; asked without the old line's issuer AAN Holdings, CCE 2016.
Seeds run: not made CFFN, ENR, IR, UNIT, WE; asked without the old issuer AAN Holdings, IGT 2015, CCE 2016. IGT's
derived era now has IGT plc as issuer and the old IGT row is the merger the full run has. The cost of rule J in the
seeds run: CFFN's old line ends 2010-12-22 at assumed par where the full run joins the 2.26-for-1 conversion; IR's and
ENR's old lines end at the ticker change where the full run follows the rename inside one observed security (before
rule J the seeds run joined each to the company that took the ticker, which was wrong). Rule X first also fired on
Thornburg Mortgage 2008, whose origin is a placeholder; it now needs two composites (`6395c78`).

**Acceptance (Task 15's list, 40 tickers).** In no case list, 23: ARRS, STE, BG, AVGO, MRVL, APO, DKNG, NCNO, AZPN,
DTV, CLWR, DOW, MRK, EVHC, AMSG, ANAT, MYL, ENDP, FERG, WFT, NLSN, WEN, TWC. Still listed, 17: CR (the 2023 Crane
line is not in the seeds run), CI and SPB (a merger in seeds, a continuation by filing in the full run), FWONA and
FWONK (the 2023 reclassification: another kind, and the new lines are missing), ALEX (no kind in seeds), CIT, ANN and
TCF (a security of the full run is missing), FOXA (S3), TEAM, ATVI, NRF, MIR, LVNTA (the same kind with another verdict
or value), MNST and NE (another last trade date). Which stage did not produce each line is not traced; it is S4's
first step, after S3 is measured.

**Other names in the case lists.** kind_changed: NFS, MEL, VIACA, DISCA, CEG, WRK, LSXMA, LSXMK, GDI, QRTEA, SUNW.
securities_lost: RRI, ABI, LMCA 2013, GCI twice (the 2015 Gannett line and, following from it, the derived acquirer
line), HTZ, WLL, LSXMA and LSXMK 2023, Z class A, QRTEA series A. securities_gained (placeholders): UAG, WPO, RRI,
ABI, CBS, DDR. endings_gained: CFFN, GHC, GM, IR, ENR, Z class C, FOXA, FOX.

**Run time.** The derived lines cost the full run 145 s and the seeds run 190 s: one or two repeat rounds of the
identity stage and stage 4b, plus the verdict passes. The equal-result task of decision (e) is still to do.

**Still open from S2.** A price test on a continuation by filing was measured and not added (a new CUSIP's first fails
row can carry a price that is not a close: AVGO 2016); the same bad row could switch off a right continuation by
timing, none known. An observed second era that joins by composite at a price that did not carry over (CFFN in the
full run) is left as it is. The old seed file dropped 26 rows on which the caller pins another issuer (Task 19 found
it): those pins reached every full run and no seeds run, so part of the numbers above is the seed builder's.

### Checkpoint 5: S3, seeds cut where the holder changed, the floor (2026-10-11)

Code `8722066` (Tasks 19 and 20 on top of checkpoint 4). The full run is the one of checkpoint 4 (its tables at
`8722066` are byte-identical to those at `6395c78`; 386 s). The seeds are built by the committed
`scripts/seeds_from_observations.py` from `data/observations.csv` in two passes: the seed file of the plain rules,
a run, and then the seed file with that run's `contract/security_history.csv`.

| Seed file | Seeds | Run | Wall |
|---|---|---|---|
| the old builder (checkpoint 4) | 2,589 | `pout-seeds6` | 546 s |
| the pin rule only | 2,615 | `pout-seeds7p` | 640 s (beside another run) |
| the pin rule and the history of `pout-seeds6` | 2,742 | `pout-seeds7h` | 520 s (beside another run) |

The observation file carries `cik` pins on some rows, and the old builder dropped 26 rows on which the pin changes
(IR 2020, AVGO 2018, JCI 2016 among them). Those pins reached every full run and no seeds run.

| Number | Floor of checkpoint 4 | Pin rule only | With the history (the new floor) |
|---|---|---|---|
| endings_lost | 0 | 0 | 0 |
| endings_gained | 8 | 7 | 1 |
| kind_changed | 16 | 14 | 11 |
| value_or_date_changed | 10 | 9 | 5 |
| securities_lost | 17 | 18 | 8 |
| securities_gained | 6 | 6 | 5 |
| seeds_placed_differently | 18 | 17 | 16 |
| truth_cases_failing_only_in_seeds | 16 | 16 | 13 |
| observed_flag_differs (not floored) | 40 | 22 | 0 |

Coverage with the history: tickers 0.9734 (full 0.9766), securities 0.9776 (full 0.9804), `left_view` 6 (full 5).

**What the history-built seeds fixed.** The endings the seeds run had and the full run lacks: CFFN, GHC, IR, ENR,
Z class C, FOXA, FOX. Kinds: CI, the four 2023 Liberty lines, ALEX, GDI. Securities the seeds run lacked: TCF, ABI,
CIT, LMCA 2013, HTZ, CR, the four 2023 Liberty lines, Z class A. Value or date: TCF, MNST, LVNTA, TEAM, NE. Every
derived line that stood for a line the caller observes is now an observed era, so `observed_flag_differs` is 0.

**What they broke.** ITT 2016 and XRX 2019: the full run has the old line and the new one as two securities; with a
second seed after the switch the seeds run has only the new line's security and the 2008 seed sits on it (one truth
case each). ALEX: two seeds on a placeholder. DISCK 2022 and LVNTA 2018 changed kind. All five are traced below.

**The residue, traced (two agents, evidence `E/s4/`).** About 26 securities still differ.

| Cause | Cases | Rule found | Tested |
|---|---|---|---|
| A CUSIP run between two seeds holds no observation and is dropped (`_split_era`: "an FTD-only side is no era"); the full run's dense observations make it an era, and that era's composite is what puts the first seed's era on the old line | ITT, XRX, ALEX (5 seeds, 2 truth cases) | make such a middle part a derived era, with the pin of the era it follows | on a 69-ticker subset: the three come out as the full run; 76 eras on 68 tickers are added over the seed file, 64 of those tickers agree already, ESV newly differs |
| A Form 25 filed more than 400 days after the last seed is not kept by the finder (`_alive_at`), where the seeds security has no fails rows to carry it | SUNW, VIACA/PARAA, LVNTA (2 truth cases) | keep it when the security's last sighting is an observation and the filing is after it | a one-line patch gives the three the full run's endings; not counted over the universe |
| The seed builder keeps no row when only the class words of the name change, so the seeds run's share class is stale and the successor search ties | DISCA, DISCK 2022 (2 truth cases) | a seed when the class words change; or drop a tie candidate that itself ends that day | not tested |
| Stage 4b reads the 8-K text sources only in its first round and only for a line with no step | RRI/GEN, and MIR's value through it | read them in every round for a line that moved and then stopped | RRI then matches the full run; not counted |
| The snapshot after a ticker changed hands falls in the days when nobody holds it, and the next snapshot is no seed | the two Gannett lines | a seed for a snapshot whose ticker the previous history does not hold | not tested |
| A rename that changes ticker and CUSIP at once, after the last observation | DDR | none (approving every unobserved part fixes it and adds 280 eras) | |
| One case each, no rule | NFS (the fallback's anchor), UAG (a 30-day window for foreign rows), ANN (a weak issuer answer dropped), WLL (a fold of a reverse split), CEG and MEL (issuer blank in seeds), GM, NRF, ATVI, QRTEA, CBS (not finished), CLWR (not traced) | | |

In SPB, MTCH and WRK the two runs take the issuer from different sources; for WRK and the QRTEA/QVCA/WW rows the seeds
run looks like the better one.

**Decision D** (when a caller may send seeds only) asks for `endings_lost`, `kind_changed`, `securities_lost`,
`seeds_placed_differently` and `truth_cases_failing_only_in_seeds` at 0. They are 0, 11, 8, 16 and 13.

### Checkpoint 6: S4, first step, the floor (Task 21, 2026-10-11)

Code `84f8637` (Task 21's Parts B and C on top of checkpoint 5), run date 2026-09-25, `claude-sonnet-5-5`. The seed
file is built by the committed seed builder from `data/observations.csv` with the history of checkpoint 5's seeds run:
2,900 seeds (2,738 by the earlier rules with that history, 95 more by the class-word rule, 67 more by the row after an
unheld seed).

| Run | Wall | SEC requests |
|---|---|---|
| full, `84f8637` | 374 s | 7 |
| seeds, `84f8637`, 2,900 seeds | 444 s | 394 |

**The full run against checkpoint 5's** (`pout-full8`). Stage 4b now reads the 8-K text sources for a line that moved
and then stopped (Part C). No ending lost or gained, no kind or value changed. Two placeholders are gone because their
lines follow through to a composite: Liz Claiborne (LIZ, `CIK352363-COMMON`) onto `BBG000C4WJT9`, the Fifth & Pacific
and Kate Spade line, and YRC Worldwide (YRCW, `CIK716006-COMMON`) onto `BBG000BX6PW7`. `left_view` 5 to 4,
placeholders 51 to 49, uncertain endings 112 to 110. `D.mismatches` 148 to 150: the two truth cases
`CIK352363-COMMON_2012-05-14` and `CIK716006-COMMON_2010-10-04` say "the old event is not the ending, the line ends
later", which is what the run now does, but they are keyed by the placeholder ids the run no longer has
(`contract/id_changes.csv` records both). They have to be re-keyed to the composites before `scorecard.py --check` can
pass.

**The seeds run against the full run.**

| Number | Floor of checkpoint 5 | Now (the new floor) |
|---|---|---|
| endings_lost | 0 | 0 |
| endings_gained | 1 | 1 |
| kind_changed | 11 | 6 |
| value_or_date_changed | 5 | 2 |
| securities_lost | 8 | 3 |
| securities_gained | 5 | 2 |
| seeds_placed_differently | 16 | 10 |
| truth_cases_failing_only_in_seeds | 13 | 5 |
| observed_flag_differs (not floored) | 0 | 1 |

Coverage: tickers 0.9757 (full 0.9770), securities 0.9799 (full 0.9808), `left_view` 4 in both.

**What is left, by name.**

| List | Names |
|---|---|
| kind_changed | NFS, VIACA/PARAA, CEG, SPB, WRK, SUNW |
| value_or_date_changed | NRF, MTCH (the same ending with another verdict) |
| securities_lost | XRX (the old line), ANN, WLL |
| securities_gained | ALEX and DDR placeholders |
| endings_gained | CFFN (rule J leaves the 2.26-for-1 conversion unjoined) |
| seeds_placed_differently | ALEX four times, DDR twice, ANN, WLL, WW, XRX |
| truth cases | ANN 2011, SPB 2018, WLL 2017, SUNW 2010, MRK 2020 |

**Rules that were tried and not kept.** A Form 25 after the last observation of a security with no later row (Task 21
Part A): as stated it has no bound, and five existing case tests fail (in NCRA a Form 25 of 2019 replaces the
security's own 2013 merger ending); in the whole run it does not reach VIACA or LVNTA, because a live sibling of the
issuer takes the filing under the existing tie rule. SUNW and VIACA stay. **Not built yet:** a CUSIP run between two
seeds that holds no observation becomes a derived era (XRX and ALEX; tried on a subset, it adds 76 eras over the seed
file and moved ESV).

**The class-word rule is mostly naming drift** (the review's count: of 119 name pairs it fires on, about 80 are one
security named with and without its class words in turn, 4 are class-to-class changes, 6 are names the file cuts
inside the class words). It is kept: every added seed is one of the caller's own observations, and the numbers above
are with it.

**Decision D** asks for `endings_lost`, `kind_changed`, `securities_lost`, `seeds_placed_differently` and
`truth_cases_failing_only_in_seeds` at 0. They are 0, 6, 3, 10 and 5.

## Status at the end of this run (2026-10-11)

Head `1882cb2`. Suite 4,063 passed, 44 xfailed. The whole-branch review's verdict after one fix round: ready to merge.

**Done.** S0 (Task 1), S1 (Tasks 2 to 6), S2 (Tasks 7 to 18), S3 (Task 19), a first step of S4 (Tasks 20 and 21),
S5's roadmap entry, a cleanup (Task 22) and the final review's fixes (Task 23).

**The measured result.** The seeds run against the full run, at the start of the plan and now (the floor in
`data/seeds_parity.json`): endings lost 2 to 0, endings gained 13 to 1, kind changed 35 to 6, value or date changed 17
to 2, securities lost 27 to 3, securities gained 8 to 2, seeds placed differently 19 to 10, truth cases failing only in
seeds 25 to 5. The full run against itself before S2: `D.mismatches` 149 to 148 at checkpoint 4, then 150 at
checkpoint 6 where two cases fail only on a key that changed for the better; three mergers newly priced (CCE 2016, GCI
2019, ODP 2025); two placeholders replaced by their composites (LIZ, YRCW). Warm run times: full 374 s (251 s before
S2), seeds 444 s on 2,900 seeds (355 s on 2,589 before S2).

**For the owner to decide.**

1. *Decision B and the published output (S5, items 1 and 3).* A full run with the resolver memo rebuilt from empty is
   byte-identical to the run with the memo (checked at `22027dd`), so the memo can be rebuilt at no cost. Rebuilding
   the committed `output/` is another matter: it and `data/scorecard.json` were built on gpt-5.4 answers, every run of
   this plan uses claude-sonnet-5-5, and a rebuilt output fails `scorecard.py --check` against the committed floor for
   that reason (`D.mismatches` 121 committed, 148 to 150 here). Nothing was published.
2. *Two truth cases to re-key:* `CIK352363-COMMON_2012-05-14` (LIZ) and `CIK716006-COMMON_2010-10-04` (YRCW) to the
   composites their lines now end on.
3. *Decision D* (when a caller may send seeds only) is not met: the five numbers it names are 0, 6, 3, 10 and 5.
4. *Decision C* (whose job a seed is whose ticker did not trade on its date) was not needed for what was built and is
   still open for SUNW.
5. *The base branch.* This branch forks from `faster-runs`, which `worktree-reset-1-scorecard` (PR #7) has not taken
   yet.

**Not built, with what is known.**

- An unobserved CUSIP run between two seeds as a derived era (XRX's old line, ALEX's four seeds): traced, tried on a
  subset, 76 eras added over the seed file, ESV moved. Checkpoint 5.
- A late Form 25 for a security whose span ends at its last seed (SUNW, VIACA): the unbounded rule broke five case
  tests and did not reach the two cases with a live sibling. Checkpoint 6.
- Reusing stage 4b's answers between rounds of the derived-line loop: each repeat round costs about 75 s; only the
  rename scan's hoist was done (about 10 s a pass).
- A price test on a continuation by filing: measured and rejected (AVGO 2016's first fails row is not a close).
- Single cases with no rule: NFS, CEG, SPB, WRK, NRF, MTCH, ANN, WLL, DDR, WW, CFFN, MRK 2020.

**Deferred review minors** (each recorded in the execution ledger): the fold mapping of a refused step's id has no
test, and rule J misses an origin that was a placeholder folded into a composite; a pair with a verdict is never judged
again; a derive round reads the fails index stage 4b enlarged in the round before; verdicts found at the last verdict
pass are logged and not applied; `derivable` reads issuer profiles when nothing is derived; `_switch_rows` runs twice
per pair; a new CUSIP's first fails row with a price that is not a close could switch off a right continuation by
timing (none known); `last_sightings`' bound is strictly greater; the degraded path of `rows_fit` is untested; a 9d
merger ending skips stage 8b's R1; the class-share and same-day tests of Task 10 are weak.

## Rulings made while executing

The controller decided these without asking, as the owner's standing instruction allows; each says what was
decided, why, and what it costs if wrong. They are in the order of the execution ledger (newest work last
except the first, which the ledger keeps at its end).

1. Task 2 Step 4 gains one edit: the test helper `_second_pass` in tests/test_resolver_renamed.py takes its dates from `last_sightings(chosen, ftd)`, as the pipeline does — the helper called `era_last_seen` bare, which Task 2 makes unbounded, and rule D then gave TRI@2008 (Triad) Thomson Reuters' issuer; in src only `last_sightings` calls `era_last_seen`, so the pipeline is not affected — if wrong, a real unbounded caller exists somewhere and gets wrong dates.
2. the branch is forked from the merged `faster-runs` head, not from `worktree-reset-1-scorecard` itself, because the base branch cannot be fast-forwarded from this session and 6bbeb7e is what it becomes after the fast-forward — if wrong (the base takes faster-runs some other way, a squash for example), this branch needs a rebase before it merges.
3. Tasks 1 and 2 go to one implementer as a batch, two commits, one review with a verdict per task — if wrong, a finding in one delays the other.
4. Task 3 is run by the controller (live network, judgment at Step 4) — if wrong, nothing: it changes no code.
5. decisions A to E take the plan's recommendation when the plan reaches each (the owner's standing instruction for these plans); each is logged in the plan's Checkpoints section — if wrong, the owner reverses it there.
6. the memo effect is measured against exec/ref2 (the same code and cache with the memo), not against the committed output/ as the plan's Step 2 says — the committed output was built by older code on gpt-5.4 answers, so comparing with it would mix three causes — if wrong, nothing: the committed output is still there to compare.
7. Task 2's rework is rule R9, written into the plan as Task 4, with Task 5 as the checkpoint again (plan commit 2f27793, which also records checkpoint 1 under "Checkpoints") — R9 is the only rule scored that leaves the full run's issuers as they were (bar the WFT correction) and halves the seeds differences; it changes `_resolve_issuers` and adds no resolver tier — if wrong, the real runs of Task 5 show it before any floor is written, and the cost is one more round.
8. the company_tickers exception stays in R9 although it leaves MRK, MTCH and SPB different from the full run in a seeds run — the seed's security was the old company's on the seed date (EDGAR names checked), the full run itself names the predecessor for PLD, and the golden case PLD-2015 needs it — if wrong, three seed rows stay different until S2 follows their lines.
9. decision E is taken as "S1 as first built is not accepted"; decision B as recommended (rebuild the memo once at S5), with its five known costs listed in the plan.
10. the weak-answer row check is not added to Task 4 after the fact; it goes first in S2's plan — Task 5's acceptance is met without it, S2 needs it for followed lines, and one measured change at a time keeps the cause of each number clear — if wrong, XP's wrong ending and TT's wrong issuer stay in the seeds run until S2's first task.
11. S2's design is neither A nor B as written. A line is derived only for a step stage 4b refuses because another registrant took over (merged_out, other_registrant, and name when the new description names the old issuer by more than a generic word); it is made an era-born security so the later stages treat it as an observed second line; stage 4b keeps every step it follows. Plus: the line-successor link takes a merger row (5 cases), C5, and the weak-answer row check first — step zero shows the full run reaches these lines as in-run eras through handoffs and R1, not through the follow stages; B as written would move 61 proven full-run steps and add 43 full-run securities; A cannot carry STE, DTV, AMSG — if wrong, the checkpoint after S2 shows it against the floor and the full run's gate before anything is published.
12. the test marked "Must not change (WCN, AAN)" is rewritten as Task 7 says — the real WCN and AAN are refused `merged_out` by stage 4b, never get a line successor and stay mergers, and a merger whose payout the gate reconciled stands; the five cases it fixes (TEAM, LSXMA, LSXMK, FWONA, FWONK) are continuations in the full run — if wrong, a real merger at a followed step reads as a continuation; the checkpoint's comparison of the full run with pout-full2 shows any row that flips.
13. the loop's run-time cost is accepted for the checkpoint and a later task makes stage 4b ask again only about the securities a round touched, checked by byte-identical tables — measuring the derived lines on the simplest code first keeps the cause of each number clear — if wrong, runs stay about 100 to 180 s slower until that task.
14. the warm fails index's effect (IAC@2012-06-29 and IACI@2008-01-16 move from a placeholder to the FIGI line stage 4b folds it into) is accepted for the checkpoint, which checks the published ids — if wrong, a published id of IAC changes and Task 15 stops on it.
15. `StageMeter.done` is made to add up a stage that runs more than once, as a second commit of Task 8 — Task 12's loop calls the identity and line-follow stages several times a run, so the same overwrite would under-report them; a stage that runs once must report byte-identically — if wrong, the manifest's per-stage numbers are off, never a table.
16. `derivable` returns pairs for the tickers of the security's own eras only, not for the tickers the line-follow stage learned from fails symbols — a pair is matched to an era by its ticker, a fails-spelled ticker matches no era of the security, and it could match another security's era by coincidence — if wrong, a refused step under a ticker no era of the security holds is not derived, which is already the case (there is no era to split).
17. Task 12 is dispatched while Task 11's scoped re-review runs — the fix is one line of library code plus tests, and Task 12 appends to the same module without touching `derivable` — if wrong, a finding on `derivable` is fixed in a commit after Task 12's and both are re-reviewed.
18. Tasks 13 and 14 go to one implementer, two commits, one review with a verdict per task — 13 adds tests only and 14 touches only the parity script and its tests, and two agents committing in one worktree at once can mix their files — if wrong, a finding in one delays the other.
19. S2 goes back before the checkpoint; no floor is written and the seeds run is not started — decision E accepts a step only if the full run does not move away from the truth sets, and two diagnosis cases fail only in the new full run (SDRL 2018, UNIT 2025) with CCE 2016 a third worse row — if wrong, one fix task and one more full run (about 9 minutes) were spent on rows a caller would not have read.
20. the seeds run at c80928c is started after all (pout-seeds4, on a copy of pcache-full4), as evidence for the fix and not as a checkpoint — it lists every derived era of a seeds run with its issuer, composite and handoff decision, which the full run's nine cannot show — if wrong, about ten minutes and a few hundred SEC requests.
21. the handoff fix is the price rule, for every pair and not for derived lines only — the same step is an observed pair in a full run and a derived pair in a seeds run, so a rule that reads `derived` would give the two runs different answers; the measured table shows no right continuation outside 0.5 to 2.0 — if wrong, a one-for-one continuation whose price moved more than twofold across the switch loses its link (none known), and NWS-A 2013 loses a successor link that the truth set calls wrong anyway.
22. stage order stays (9e after 9b) — moving the plan-bankruptcy step before the handoffs would let it reclassify rows the handoffs make continuations today (GGP 2010 is a bankruptcy emergence that is a right continuation) — if wrong, a bankruptcy exchange whose price happens to carry over is still rewritten.
23. the price test is not added to a continuation by filing — AVGO shows a new CUSIP's first fails row can carry a price that is not a close, and a filing is stronger evidence than that row — if wrong, a non-one-for-one exchange under an 8-K12B (Uniti 2025) is read as a continuation wherever its new line is a security of the run, which the identity rule below must therefore prevent for derived lines.
24. a derived era that joins the security it was refused from is made only when the price carried over (rule J), whatever the issuers — OpenFIGI's composite says one security and stage 4b's refusal says another registrant; the fails price across the step is the evidence at hand, and without it the step stays refused as before S2 — if wrong, a join that is right at another price is lost and that ticker is as before S2 (CFFN 2010, a 2.26-for-1 conversion the full run joins, and WE's reverse split, which needed no derived era).
25. rule U (send the era to its issuer's placeholder) is not built — with New Uniti a security of the run the handoff stage makes the old row a continuation by filing, which the truth set refutes, and a price test on filing pairs is unsafe — if wrong, the Uniti merger stays at assumed par where it could have been priced through New Uniti's line.
26. a derived era from a `merged_out` step never keeps the old line's issuer under a composite of its own (rule X: asked again without that issuer) — stage 4b says `merged_out` only when that issuer files no periodic report after the step, and the three cases found (CCE, AAN Holdings, IGT) are all wrong; `other_registrant` and `name` steps are left alone (CHTR) — if wrong, a line that truly kept the old CIK gets another issuer or none; the checkpoint lists every era the rule touched.
27. one band for "the price carried over", two thirds to one and a half, for Task 16's handoff rule and rule J — Uniti's 1.65 must lie outside and GGP's 0.89 inside; nothing measured in either run lies between the old and the new bounds except one merger row that stands either way — if wrong, a one-for-one continuation whose price moved by more than half across the switch loses its link.
28. rule X applies only when the origin's id and the derived era's id are both composites — its premise is two composites under one issuer; a placeholder origin only means the old line never got a composite, and the fold decides whether they are one line — if wrong, a derived era under a placeholder origin keeps a wrong old issuer (none known).
29. decision A is taken as recommended — a seed where an identifier changed, and with a previous run's `contract/security_history.csv` a seed where the ticker's holder changed (Task 19); the observation file of this universe carries no identifier, so the second route is the one measured, and a first run needs two passes — if wrong, the seed builder gained an option nobody uses; the default behaviour is unchanged.
30. of the run-time work only the rename scan's hoist is done now (Task 20, Part A); reusing stage 4b's answers between rounds is left open — the derived lines cost 145 s (full) and 190 s (seeds), both runs stay under ten minutes, and an exact reuse needs every input of a security's scan tracked, including the fails index that stage 4b itself enlarges between rounds; the hoist is a few lines with a measured 10 s a pass — if wrong, each run pays about 75 s per repeat round until someone builds the reuse; reported to the user as an open point.
31. S4 is done in two steps. Task 21 builds the three rules that are small and were tried on their cases (a late Form 25 for a security whose last sighting is an observation; the seed builder's class words and the row after an unheld seed; stage 4b's text sources for a line that moved and stopped). The middle part between two seeds (ITT, XRX, ALEX) is a separate task after Task 21 is measured, because it adds 76 eras and already moved ESV in a subset. DDR, NFS, UAG, ANN, WLL, CEG, MEL, GM, NRF, ATVI, CBS, CLWR stay as single cases with no rule — each rule here was tried on its cases only, so the universe's answer comes from the next pair of runs — if wrong, the checkpoint after Task 21 shows what moved and the offending part is reverted by its own commit.
32. Part A is dropped from Task 21 and left open — "any Form 25 after the last observation" has no bound and takes filings that belong to later securities of the issuer, and the two cases with a sibling need the sibling rule changed, which no trace covered — if wrong, SUNW, VIACA and LVNTA stay as three known differences (two truth cases) until a rule that is bounded and reads the siblings is designed.
33. rule 3 is measured before it is narrowed — every added seed is one of the caller's own observations, which the full run reads too, so the drift seeds can only cost if an extra seed breaks something as ITT's did; the seeds run on E/task21/seeds-b.csv (2,900 seeds) decides: kept with a truncation test if the parity numbers hold, narrowed or dropped if they do not — if wrong, one seeds run was spent on a rule that is then cut back.
34. Part C stands in the full run — both lines now do what their truth cases say (the line ends later, on its composite) and every other count improved; the two cases fail only on their key — if wrong, the two cases must be re-keyed to the composites in the truth set before `scorecard.py --check` can pass (S5 has to do this in any case, with the eight `sec_id` mismatches the scorecard already carries).
35. rule 3 (class words) is kept as built — the run with its 95 extra seeds has every number at or below the floor and fixes DISCA and DISCK — if wrong, a caller's seed file is about 3% larger than it needs to be; the test the review asked for (a name cut inside its class words) goes into the cleanup task.
36. the middle part between two seeds (XRX, ALEX; the traced rule adds 76 eras) is not built in this plan's run — it is the largest change left for two securities, it moved ESV in the subset, and it needs its own checkpoint — if wrong, XRX's old line and ALEX's four seeds stay as known differences; the rule, the clone that tried it (E/s4/identity/code3, switches MIDDLE and INHERIT) and the counts are in Checkpoint 5.
37. S5 items 1 and 3 (rebuild the resolver memo, commit the rebuilt outputs, apply the flip rule) are not done in this run and go to the user — the committed `output/` and `data/scorecard.json` were built on gpt-5.4 answers and every run of this plan uses claude-sonnet-5-5, so a rebuilt output fails `scorecard.py --check` against the committed floor for a reason this plan did not cause (D.mismatches 121 in the committed scorecard against 148 to 150 in every run here), and lowering that floor by hand is a decision about the published tables — if wrong, the published output stays behind the code until the user says which answers it is built on; the scratch run with the memo rebuilt from empty (pout-full10) gives the evidence decision B asks for.
38. Task 3 does not write the floor and S1 goes back into Task 2 — the plan's Step 4 says a regression goes back into Task 2 and decision E accepts S1 only if nothing moves away from the truth sets; two golden cases fail and 19 or 20 issuers got worse — if wrong, the cost is one more round on Task 2 before S2 starts.

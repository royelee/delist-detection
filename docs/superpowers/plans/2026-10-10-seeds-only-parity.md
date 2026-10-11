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
7. **The parity floor only goes down.** `data/seeds_parity.json`, written by
   `scripts/seeds_parity.py --write-floor`.

## Decisions for the owner

| # | Decision | Recommendation |
| --- | --- | --- |
| A | How the caller learns that a ticker passed to another security it still holds (C6, FOX 2019). No filing can say this: it is a fact about the caller's universe. | If the snapshots carry an identifier (CUSIP, ISIN, SEDOL), the seed builder cuts a seed when it changes. That is the clean answer. If they do not, the seed builder reads the previous run's `contract/security_history.csv` and cuts a seed at the first snapshot after the ticker's holder changed. That second route makes the seeds depend on an earlier run, so a first run needs two passes, and it needs the new holder's line to be in that table (S2). |
| B | Whether to rebuild `cache/ticker_resolution.json` from empty for the published output. | Yes, once, in its own commit. The full run reads answers older code computed: NWA's issuer exists only there. Task 3 measures in a scratch folder what moves, before anything is published. |
| C | Whether backfilled seeds (C3) are the library's job or the seed builder's. | Decide after S2's checkpoint, with the list of seeds still wrong. |
| D | When qlib_practice may send seeds only. | When the parity numbers `endings_lost`, `kind_changed`, `securities_lost`, `seeds_placed_differently` and `truth_cases_failing_only_in_seeds` are 0, apart from cases the truth set marks as LLM differences. |
| E | Whether S1 is accepted on its own. It changes the published full run: 638 of 2,659 eras are asked for their issuer at a new date. | Accept it if Task 3's comparison shows no issuer or ending moving away from the truth sets, and publish the full run's rebuilt output with it. |

## The fixes, in order

| ID | Fix | Must move | Status in this document |
| --- | --- | --- | --- |
| S0 | Parity script and floor | nothing; it measures | Task 1, step by step |
| S1 | Last-seen date follows the era's own CUSIP rows | C1 | Tasks 2 and 3, step by step |
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

## S3: A seed at a takeover (needs decision A)

`scripts/seeds_from_observations.py` gains `--security-history PATH` (a previous run's
`contract/security_history.csv`). A row becomes a seed when the security holding its ticker on
its date differs from the one holding it on the ticker's previous snapshot. Without the option the
script behaves as today. Test with FOXA: holder BBG of Twenty-First Century Fox to 2019-03-19,
the Fox Corp line after; the 2019-06-30 row becomes a seed. This depends on S2, which is what
puts the new holder's line into `security_history`.

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

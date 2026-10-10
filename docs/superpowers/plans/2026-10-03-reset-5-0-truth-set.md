# Sub-plan 5-0: Diagnosis Truth Set and Evaluation Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the 282 diagnosis reports into a scored truth file and build the loop (truth, judge and score report,
regression report, diagnose, new truth) that every later fix sub-plan (5a to 5i) must pass.

**Architecture:** Four small pure modules beside the existing truth and scorecard code:
- `diagnosis_truth.py`: the truth file's format, loader and judge against contract rows.
- `regression.py`: the contract diff against a base commit.
- `diagnosis_loop.py`: error keys, the ledger, the case rows the diagnose workflow reads, and placeholder renames.
- `truth_update.py`: the rules for applying diagnoses to the truth file.
- `truth_build.py`: assembles the first truth file from an agent normalization pass.

Thin scripts under `scripts/` do the file IO. Two saved workflows under `.claude/workflows/` run the agent work: the
normalization pass, and the diagnose and verify rounds of the loop. The scorecard gains `D.*` lines and a strict
per-case test, as the golden set has.

**Tech Stack:** Python 3.10+, csv/json from the standard library, pytest (offline), git (subprocess, for the base
commit's contract files), the Claude Code Workflow tool (JavaScript workflow scripts, sonnet agents), the
diagnose-delisting skill's `sec.py` for SEC access.

**Spec:** `docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md` (section 1 is this sub-plan; sections 2
and 4 bind it). Roadmap: `docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md`.

## Global Constraints

- In this worktree prefix every script with `PYTHONPATH=src` and use `~/miniconda3/envs/rdagent4qlib/bin/python`
  (CLAUDE.md: the editable install points at the main checkout).
- Tests are fully offline: no network on the test path (`FakeEdgar` or plain row fixtures only).
- Never write a `--limit` subset into `output/`; the committed-output tests read it.
- SEC access from agents only through `.claude/skills/diagnose-delisting/sec.py`, with
  `DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock` and `allowed_domains` data.sec.gov,
  www.sec.gov, efts.sec.gov. One SEC client at a time across sessions.
- Workflow agents use model `sonnet`; at most 5 agents run at a time (operator's limit), and the workflow logs its speed.
- Do not edit `data/golden_lifecycles.csv` or `data/accuracy_audit.csv`.
- A scorecard floor entry is raised only by `scripts/scorecard.py --raise-floor`; lowering one is by hand with the
  reason in the commit.
- Every data file write goes through `atomic_io.write_atomic`.
- Never merge or push; commits stay on the worktree branch.
- Bash cannot write under `.claude/` (sandbox): create and edit `.claude/skills/...` and `.claude/workflows/...` with
  the Write and Edit tools.
- Commit messages end with the session's attribution lines (Co-Authored-By, Claude-Session).
- Truth semantics (spec 1.1): a scored cell is a value, a blank (must be blank) or `*` (not scored);
  `internal_last_trade_date` blank means not scored; numbers compare at 6 significant figures.
- Truth-change rules (spec 1.6) are fixed: the truth never takes a library value unless a verified, skeptic-upheld
  diagnosis names a filing the earlier report missed or misread.

## Review Focus

1. A truth row keyed by a placeholder that a later run folded into a FIGI line. The loop must rename the row through
   `contract/id_changes.csv` before judging, rather than report "no contract row" (Task 5, test
   `test_rename_truth_follows_id_changes`).
2. The same number written two ways ("1.05" in the truth, "1.050000" in the contract). It must match (Task 2, test
   `test_numbers_compare_at_six_significant_figures`).
3. A base commit that has no contract files, or a git error. `regression_report.py` must exit 2 with one message
   naming the commit and path, not crash (Task 4, test `test_script_exits_2_when_the_base_lacks_the_contract`).
4. A diagnose agent that wrote no record. `update_truth` must change nothing and leave no ledger row, so the next
   round retries it (Task 6, test `test_a_case_with_no_record_changes_nothing_and_is_retried`).
5. `update_truth` or the ledger seed run twice for the same round. Nothing may be duplicated (Task 5, test
   `test_seeding_twice_adds_nothing`; Task 6, test `test_rerunning_a_round_skips_settled_keys`).

## Rulings made in this plan

- The diagnosis truth kind lives in its own module, `diagnosis_truth.py`, beside `truth.py`. The spec says
  "`truth.py` gains a third truth kind". The new judge compares contract rows, not lifecycles, and shares nothing
  with `truth.judge` except the error class (`DiagnosisTruthError` subclasses `truth.TruthFileError`, so every
  existing handler catches it). Cost if this is wrong: one file move.
- `D.unexplained_regressions` is a `--check` gate in `scripts/scorecard.py`, computed when
  `output/regression_report.csv` exists. It is not a floored `METRICS` entry, because the pipeline's own scorecard
  has no regression report and a floored metric it lacks would count as a drop (`scorecard.drops`). The spec's
  "floored at zero" holds through `--check`. Cost if this is wrong: moving one line into `METRICS`.
- The first truth build uses an agent normalization pass (Tasks 7–9), not a script alone. A probe of all 282
  section 4s found 92 that mix print words with "worked out" and 17 that are unclear, so whether a last trade date
  is publishable needs judgement per case. Pending questions go to the operator, as the spec requires.

## File Structure

Create:
- `src/delist_detection/diagnosis_truth.py`: the truth file format (columns, vocabularies, loader, writer) and the
  judge (`LibraryRows`, `judge_case`, `judge_all`).
- `src/delist_detection/regression.py`: `Snapshot`, `read_snapshot`, `snapshot_at` (git), `successor_chain`,
  `diff_contract`, `regression_key`, `unexplained`.
- `src/delist_detection/diagnosis_loop.py`: the ledger, error keys, `new_errors`, `context`, `case_rows`,
  `rename_truth`.
- `src/delist_detection/truth_update.py`: `apply_round`, `flip_statuses`, the change log.
- `src/delist_detection/truth_build.py`: `assemble`, `final_status`, `review_markdown`.
- `scripts/regression_report.py`, `scripts/truth_loop_round.py`, `scripts/update_truth.py`,
  `scripts/build_diagnosis_truth.py`.
- `.claude/skills/diagnose-delisting/truth-rules.md`: the rules the normalization agents follow.
- `.claude/workflows/diagnosis-truth-normalize.js` and `.claude/workflows/diagnosis-truth-loop.js`.
- Tests: `tests/diagnosis_rows.py` (row helpers), `tests/test_diagnosis_truth.py`, `tests/test_diagnosis_truth_cases.py`,
  `tests/test_regression.py`, `tests/test_diagnosis_loop.py`, `tests/test_truth_update.py`, `tests/test_truth_build.py`.
- Data, written by the run tasks: `data/diagnosis_truth.csv`, `data/diagnosis_truth_legs.csv`,
  `data/diagnosis_truth_changes.csv`, `output/diagnose_unknown_report/truth_rows/*.json`,
  `output/diagnose_unknown_report/truth_review.md`, `output/diagnose_unknown_report/loop/diagnosed.csv`.

Modify:
- `src/delist_detection/scorecard.py`: config key `diagnosis`/`diagnosis_legs`, `D.*` lines, `diagnosis_failures`.
- `scripts/scorecard.py`: payout legs, `D.unexplained_regressions`, the `--check` gate.
- `tests/lifecycle_tables.py`: a `contract_row` helper.
- `tests/test_scorecard.py`, `tests/test_scorecard_script.py`, `tests/test_scorecard_floor.py`.
- `.claude/skills/diagnose-delisting/SKILL.md`: a "Modes" section (regression, mismatch).
- `data/scorecard.json`: name the truth files; floor the `D.*` lines.
- `CLAUDE.md`: commands and architecture entries.

---

### Task 1: The truth file format

**Files:**
- Create: `src/delist_detection/diagnosis_truth.py`
- Create: `tests/diagnosis_rows.py`
- Test: `tests/test_diagnosis_truth.py`

**Interfaces:**
- Consumes: `exit_kind.EXIT_KINDS`, `exit_kind.DROP_REASONS`, `payout_rule.VALUE_RULES`, `truth.TruthFileError`,
  `atomic_io.write_atomic`.
- Produces:
  - Constants `SCORED`, `COLUMNS`, `LEG_COLUMNS`, `NOT_SCORED = "*"`, `ENDING`, `NO_ENDING`, `ENDING_MOVED`,
    `SHAPES`, `PASS`, `KNOWN_WRONG`, `RULING_PENDING`, `STATUSES`, `BASKET = "basket"`, `TRUTH_VALUE_RULES`,
    `NUMBERS`, `DATES`, `REGRESSION_PENDING = "regression"`.
  - `class DiagnosisTruthError(TruthFileError)`.
  - `@dataclass(frozen=True) Leg(leg: int, ratio: str, price_sec_id: str, price_ticker: str, price_date: str)`.
  - `@dataclass(frozen=True) DiagnosisCase(case_id, sec_id, ticker, status, fixed_by, shape, fields: Mapping[str, str], internal_last_trade_date="", report="", confidence="", skeptic="", note="", legs: tuple[Leg, ...] = ())`, with property `old_delist_date -> str`.
  - `parse_rows(rows, where="rows", legs=None) -> list[DiagnosisCase]`.
  - `load_diagnosis_truth(path, legs_path=None) -> list[DiagnosisCase]`.
  - `load_legs(path) -> dict[str, tuple[Leg, ...]]`.
  - `write_diagnosis_truth(path, rows)` and `write_legs(path, rows)`.
  - Test helpers `tests.diagnosis_rows.truth_row(case_id, sec_id, **cells) -> dict` and
    `leg_row(case_id, leg, **cells) -> dict`.

- [ ] **Step 1: Write the row helpers**

`tests/diagnosis_rows.py`:

```python
"""Rows of the diagnosis truth files for tests: every column present, every scored field `*` (not scored) unless
a test sets it, status pass and shape ending by default."""
from __future__ import annotations

from delist_detection.diagnosis_truth import COLUMNS, LEG_COLUMNS, SCORED


def truth_row(case_id: str, sec_id: str, **cells) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    row.update({f: "*" for f in SCORED})
    row.update(case_id=case_id, sec_id=sec_id, ticker=sec_id, status="pass", shape="ending")
    unknown = set(cells) - set(row)
    assert not unknown, f"no column(s) {sorted(unknown)}"
    row.update({k: str(v) for k, v in cells.items()})
    return row


def leg_row(case_id: str, leg: int, **cells) -> dict[str, str]:
    row = dict.fromkeys(LEG_COLUMNS, "")
    row.update(case_id=case_id, leg=str(leg), ratio="1")
    row.update({k: str(v) for k, v in cells.items()})
    return row
```

- [ ] **Step 2: Write the failing tests**

`tests/test_diagnosis_truth.py`:

```python
"""diagnosis_truth: the truth file's format and loader (spec 1.1), and the judge (spec 1.3)."""
import pytest

from delist_detection import diagnosis_truth as dt
from tests.diagnosis_rows import leg_row, truth_row


def _write(tmp_path, rows, legs=None):
    path = tmp_path / "truth.csv"
    dt.write_diagnosis_truth(path, rows)
    legs_path = None
    if legs is not None:
        legs_path = tmp_path / "legs.csv"
        dt.write_legs(legs_path, legs)
    return path, legs_path


def test_round_trip_keeps_every_cell(tmp_path):
    row = truth_row("S1_2010-01-04", "S1", exit_kind="merger", stock_ratio="1.05", last_trade_date="",
                    internal_last_trade_date="2010-01-01", note="worked out")
    path, _ = _write(tmp_path, [row])
    [case] = dt.load_diagnosis_truth(path)
    assert case.case_id == "S1_2010-01-04" and case.sec_id == "S1" and case.status == dt.PASS
    assert case.fields["exit_kind"] == "merger" and case.fields["stock_ratio"] == "1.05"
    assert case.fields["last_trade_date"] == "" and case.fields["cash_per_share"] == dt.NOT_SCORED
    assert case.internal_last_trade_date == "2010-01-01" and case.note == "worked out"
    assert case.old_delist_date == "2010-01-04"


def test_a_nodate_case_has_no_old_delist_date(tmp_path):
    path, _ = _write(tmp_path, [truth_row("S1_nodate", "S1")])
    assert dt.load_diagnosis_truth(path)[0].old_delist_date == ""


def test_star_and_blank_and_basket_are_accepted(tmp_path):
    row = truth_row("S1_2010-01-04", "S1", value_rule="basket", drop_reason="", continuation="")
    path, _ = _write(tmp_path, [row])
    assert dt.load_diagnosis_truth(path)[0].fields["value_rule"] == dt.BASKET


@pytest.mark.parametrize("cells, message", [
    ({"shape": "gone"}, "shape"),
    ({"status": "maybe"}, "status"),
    ({"status": "known_wrong"}, "fixed_by"),
    ({"exit_kind": "acquired"}, "exit_kind"),
    ({"drop_reason": "broke"}, "drop_reason"),
    ({"continuation": "yes"}, "continuation"),
    ({"value_rule": "shares"}, "value_rule"),
    ({"last_trade_date": "2010-13-01"}, "last_trade_date"),
    ({"stock_ratio": "1.05x"}, "stock_ratio"),
    ({"internal_last_trade_date": "soon"}, "internal_last_trade_date"),
    ({"sec_id": ""}, "sec_id"),
])
def test_a_bad_cell_names_the_file_line_and_field(tmp_path, cells, message):
    path, _ = _write(tmp_path, [truth_row("S1_2010-01-04", "S1", **cells)])
    with pytest.raises(dt.DiagnosisTruthError, match=rf"truth\.csv:2.*{message}"):
        dt.load_diagnosis_truth(path)


def test_a_repeated_case_id_is_refused(tmp_path):
    path, _ = _write(tmp_path, [truth_row("S1_2010-01-04", "S1"), truth_row("S1_2010-01-04", "S1")])
    with pytest.raises(dt.DiagnosisTruthError, match=r"truth\.csv:3.*repeated"):
        dt.load_diagnosis_truth(path)


def test_a_wrong_header_is_refused(tmp_path):
    path = tmp_path / "truth.csv"
    path.write_text("case_id,sec_id\nS1_2010-01-04,S1\n")
    with pytest.raises(dt.DiagnosisTruthError, match="columns"):
        dt.load_diagnosis_truth(path)


def test_legs_load_onto_their_case_in_leg_order(tmp_path):
    path, legs = _write(tmp_path, [truth_row("S1_2010-01-04", "S1", value_rule="basket")],
                        [leg_row("S1_2010-01-04", 2, ratio="0.0667", price_ticker="STRZ"),
                         leg_row("S1_2010-01-04", 1, ratio="1", price_ticker="LION")])
    [case] = dt.load_diagnosis_truth(path, legs)
    assert [(lg.leg, lg.price_ticker) for lg in case.legs] == [(1, "LION"), (2, "STRZ")]


@pytest.mark.parametrize("legs, message", [
    ([leg_row("NOPE_2010-01-04", 1)], "unknown case"),
    ([leg_row("S1_2010-01-04", 1, ratio="x")], "ratio"),
    ([leg_row("S1_2010-01-04", 1), leg_row("S1_2010-01-04", 1)], "repeated"),
    ([leg_row("S1_2010-01-04", 0)], "leg"),
])
def test_bad_legs_are_refused(tmp_path, legs, message):
    path, legs_path = _write(tmp_path, [truth_row("S1_2010-01-04", "S1")], legs)
    with pytest.raises(dt.DiagnosisTruthError, match=message):
        dt.load_diagnosis_truth(path, legs_path)


def test_a_missing_legs_file_means_no_legs(tmp_path):
    path, _ = _write(tmp_path, [truth_row("S1_2010-01-04", "S1")])
    assert dt.load_diagnosis_truth(path, tmp_path / "absent.csv")[0].legs == ()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_diagnosis_truth.py -q`
Expected: FAIL. The collection error is `ModuleNotFoundError: No module named 'delist_detection.diagnosis_truth'`.

- [ ] **Step 4: Write the format part of the module**

`src/delist_detection/diagnosis_truth.py`:

```python
"""The diagnosis truth set (spec: docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md, section 1):
what each diagnosed security's contract row should say, as the contract would publish it, and the judge that
compares one run's tables to it.

`data/diagnosis_truth.csv` holds one row per case. `shape` says what is checked:

    ending        the security's contract/delistings.csv row must match the scored fields
    no_ending     the security has no real ending: there is no contract row for it
    ending_moved  the ending the report examined is not the security's last real ending: delistings.csv's last
                  real ending must have another delist_date, and the scored fields that are not `*` are checked
                  on the contract row (required only when one is scored)

A scored cell holds the value, a blank (the field must be blank) or `*` (not scored). `internal_last_trade_date`
is the corrected last trade date for delistings.csv when the contract leaves it blank (a worked-out date; decision
12 publishes only exchange prints); blank there means not scored. `status` is pass (must match now), known_wrong
(must not match yet; `fixed_by` names the sub-plan, or `residual`) or ruling_pending (not judged; `fixed_by`
`regression` marks a regressed row the loop could not settle). `data/diagnosis_truth_legs.csv` holds a basket's
legs (ruling R3), judged against contract/payout_legs.csv once the contract has one.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .atomic_io import write_atomic
from .exit_kind import DROP_REASONS, EXIT_KINDS
from .payout_rule import VALUE_RULES
from .truth import TruthFileError

SCORED = ("exit_kind", "drop_reason", "continuation", "successor_sec_id", "last_trade_date", "value_rule",
          "cash_per_share", "cash_currency", "stock_ratio", "price_sec_id", "price_ticker", "price_date",
          "recovery_ratio")
COLUMNS = ("case_id", "sec_id", "ticker", "report", "confidence", "skeptic", "status", "fixed_by", "shape",
           *SCORED, "internal_last_trade_date", "note")
LEG_COLUMNS = ("case_id", "leg", "ratio", "price_sec_id", "price_ticker", "price_date")
NOT_SCORED = "*"
ENDING, NO_ENDING, ENDING_MOVED = "ending", "no_ending", "ending_moved"
SHAPES = (ENDING, NO_ENDING, ENDING_MOVED)
PASS, KNOWN_WRONG, RULING_PENDING = "pass", "known_wrong", "ruling_pending"
STATUSES = (PASS, KNOWN_WRONG, RULING_PENDING)
REGRESSION_PENDING = "regression"            # fixed_by of a ruling_pending row the loop added for a regression
BASKET = "basket"
TRUTH_VALUE_RULES = VALUE_RULES | {BASKET}
NUMBERS = ("cash_per_share", "stock_ratio", "recovery_ratio")
DATES = ("last_trade_date", "price_date")


class DiagnosisTruthError(TruthFileError):
    """A diagnosis truth file that cannot be read; the message names the file and line."""


@dataclass(frozen=True)
class Leg:
    leg: int
    ratio: str
    price_sec_id: str = ""
    price_ticker: str = ""
    price_date: str = ""


@dataclass(frozen=True)
class DiagnosisCase:
    case_id: str
    sec_id: str
    ticker: str
    status: str
    fixed_by: str
    shape: str
    fields: Mapping[str, str]
    internal_last_trade_date: str = ""
    report: str = ""
    confidence: str = ""
    skeptic: str = ""
    note: str = ""
    legs: tuple[Leg, ...] = field(default=())

    @property
    def old_delist_date(self) -> str:
        """The delist_date of the ending the report examined (the case_id's tail; blank for `nodate` or a
        loop-added case, whose tail is not a date)."""
        tail = self.case_id.rsplit("_", 1)[-1]
        try:
            return date.fromisoformat(tail).isoformat()
        except ValueError:
            return ""


def _is_date(cell: str) -> bool:
    try:
        date.fromisoformat(cell)
        return True
    except ValueError:
        return False


def _is_number(cell: str) -> bool:
    try:
        float(cell)
        return True
    except ValueError:
        return False


def _check(name: str, cell: str, where: str) -> None:
    if cell in ("", NOT_SCORED):
        return
    allowed = {"exit_kind": EXIT_KINDS, "drop_reason": DROP_REASONS, "continuation": {"true", "false"},
               "value_rule": TRUTH_VALUE_RULES}.get(name)
    if allowed is not None and cell not in allowed:
        raise DiagnosisTruthError(f"{where}: {name} {cell!r} is not one of {sorted(allowed)}")
    if (name in DATES or name == "internal_last_trade_date") and not _is_date(cell):
        raise DiagnosisTruthError(f"{where}: {name} {cell!r} is not a YYYY-MM-DD date")
    if name in NUMBERS and not _is_number(cell):
        raise DiagnosisTruthError(f"{where}: {name} {cell!r} is not a number")


def parse_rows(rows: Sequence[Mapping[str, str]], where: str = "rows",
               legs: Mapping[str, tuple[Leg, ...]] | None = None) -> list[DiagnosisCase]:
    """Truth rows (every COLUMNS key) as cases. Raises DiagnosisTruthError naming `where` and the line (the header
    is line 1) on a blank or repeated case_id, a blank sec_id, an unknown shape or status, a known_wrong row with no
    fixed_by, or a scored cell outside its vocabulary, date or number format."""
    out: list[DiagnosisCase] = []
    seen: set[str] = set()
    for line, r in enumerate(rows, start=2):
        at = f"{where}:{line}"
        cid = r["case_id"].strip()
        if not cid or cid in seen:
            raise DiagnosisTruthError(f"{at}: case_id {cid!r} is blank or repeated")
        seen.add(cid)
        if not r["sec_id"].strip():
            raise DiagnosisTruthError(f"{at}: sec_id is blank")
        if r["shape"] not in SHAPES:
            raise DiagnosisTruthError(f"{at}: shape {r['shape']!r} is not one of {list(SHAPES)}")
        if r["status"] not in STATUSES:
            raise DiagnosisTruthError(f"{at}: status {r['status']!r} is not one of {list(STATUSES)}")
        if r["status"] == KNOWN_WRONG and not r["fixed_by"].strip():
            raise DiagnosisTruthError(f"{at}: a known_wrong case needs fixed_by")
        cells = {f: r[f].strip() for f in SCORED}
        for name, cell in cells.items():
            _check(name, cell, at)
        internal = r["internal_last_trade_date"].strip()
        _check("internal_last_trade_date", internal, at)
        out.append(DiagnosisCase(
            case_id=cid, sec_id=r["sec_id"].strip(), ticker=r["ticker"], status=r["status"],
            fixed_by=r["fixed_by"].strip(), shape=r["shape"], fields=cells, internal_last_trade_date=internal,
            report=r["report"], confidence=r["confidence"], skeptic=r["skeptic"], note=r["note"],
            legs=(legs or {}).get(cid, ())))
    return out


def _read(path: Path, columns: Sequence[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != tuple(columns):
            raise DiagnosisTruthError(f"{path}: columns {reader.fieldnames} are not {list(columns)}")
        return list(reader)


def load_legs(path: str | Path) -> dict[str, tuple[Leg, ...]]:
    """data/diagnosis_truth_legs.csv by case_id, each case's legs in leg order. Raises DiagnosisTruthError on a
    leg number below 1, a repeated leg, a ratio that is not a number or a bad price_date."""
    path = Path(path)
    by_case: dict[str, dict[int, Leg]] = {}
    for line, r in enumerate(_read(path, LEG_COLUMNS), start=2):
        at = f"{path}:{line}"
        try:
            n = int(r["leg"])
        except ValueError:
            n = 0
        if n < 1:
            raise DiagnosisTruthError(f"{at}: leg {r['leg']!r} is not a number from 1")
        if not _is_number(r["ratio"]):
            raise DiagnosisTruthError(f"{at}: ratio {r['ratio']!r} is not a number")
        if r["price_date"] and not _is_date(r["price_date"]):
            raise DiagnosisTruthError(f"{at}: price_date {r['price_date']!r} is not a YYYY-MM-DD date")
        legs = by_case.setdefault(r["case_id"], {})
        if n in legs:
            raise DiagnosisTruthError(f"{at}: leg {n} of {r['case_id']} is repeated")
        legs[n] = Leg(n, r["ratio"], r["price_sec_id"], r["price_ticker"], r["price_date"])
    return {cid: tuple(legs[n] for n in sorted(legs)) for cid, legs in by_case.items()}


def load_diagnosis_truth(path: str | Path, legs_path: str | Path | None = None) -> list[DiagnosisCase]:
    """Every case of the truth file at `path`, with its legs from `legs_path` (missing: no legs). Raises
    DiagnosisTruthError (file and line in the message), also for legs whose case is not in the truth file."""
    path = Path(path)
    legs = load_legs(legs_path) if legs_path is not None and Path(legs_path).exists() else {}
    cases = parse_rows(_read(path, COLUMNS), str(path), legs)
    unknown = sorted(set(legs) - {c.case_id for c in cases})
    if unknown:
        raise DiagnosisTruthError(f"{legs_path}: legs for unknown case(s) {unknown}")
    return cases


def _write(path: str | Path, columns: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(Path(path), buf.getvalue())


def write_diagnosis_truth(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    """Write truth rows (every COLUMNS key) to `path` in one atomic replace."""
    _write(path, COLUMNS, rows)


def write_legs(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    """Write leg rows (every LEG_COLUMNS key) to `path` in one atomic replace."""
    _write(path, LEG_COLUMNS, rows)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_diagnosis_truth.py -q`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/diagnosis_truth.py tests/diagnosis_rows.py tests/test_diagnosis_truth.py
git commit -m "Diagnosis truth file: columns, vocabularies, loader and writer (sub-plan 5-0)"
```

---

### Task 2: The judge

**Files:**
- Modify: `src/delist_detection/diagnosis_truth.py` (append the judge)
- Modify: `tests/lifecycle_tables.py` (add `contract_row`)
- Test: `tests/test_diagnosis_truth.py` (append)

**Interfaces:**
- Consumes: Task 1's `DiagnosisCase`, `SCORED`, `NUMBERS`, shapes and statuses; `contract.last_endings`;
  `lifecycle.Tables`.
- Produces:
  - `@dataclass(frozen=True) Mismatch(case_id: str, field: str, truth: str, library: str)`, whose `__str__` gives
    `"<field> <library or (blank)> != <truth or (blank)>"`.
  - `@dataclass(frozen=True) CaseJudgement(case, mismatches: tuple[Mismatch, ...])`, with property `ok`.
  - `@dataclass(frozen=True) LibraryRows(contract, last_endings, legs=None)`, with classmethod
    `of(tables, legs_rows=None)`.
  - `judge_case(case, lib) -> CaseJudgement` and `judge_all(cases, lib) -> list[CaseJudgement]` (skips
    ruling_pending).
  - `field_key(name) -> str`, which maps `legN.x` to `legs`.
  - `MISMATCH_FIELDS = (*SCORED, "internal_last_trade_date", "shape", "ending", "legs")`.

- [ ] **Step 1: Add the contract row helper**

Append to `tests/lifecycle_tables.py`:

```python
def contract_row(sec_id, **cells):
    """A contract/delistings.csv row with any of its columns set."""
    return _row("contract_delistings", sec_id=sec_id, **cells)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_diagnosis_truth.py`:

```python
from tests.lifecycle_tables import contract_row, ending, tables


def _lib(contract=(), delistings=(), legs_rows=None):
    return dt.LibraryRows.of(tables(delistings=list(delistings), contract_delistings=list(contract)), legs_rows)


def _case(**cells):
    return dt.parse_rows([truth_row("S1_2010-01-04", "S1", **cells)])[0]


def test_an_ending_that_matches_every_scored_field_is_ok():
    lib = _lib([contract_row("S1", exit_kind="merger", value_rule="cash", cash_per_share="10.000000",
                             cash_currency="")])
    j = dt.judge_case(_case(exit_kind="merger", value_rule="cash", cash_per_share="10", cash_currency=""), lib)
    assert j.ok


def test_numbers_compare_at_six_significant_figures():
    lib = _lib([contract_row("S1", stock_ratio="1.050000")])
    assert dt.judge_case(_case(stock_ratio="1.05"), lib).ok
    assert not dt.judge_case(_case(stock_ratio="1.051"), lib).ok


def test_a_blank_truth_cell_requires_a_blank_and_star_is_never_scored():
    lib = _lib([contract_row("S1", cash_currency="USD", price_ticker="UAUA")])
    j = dt.judge_case(_case(cash_currency="", price_ticker="*"), lib)
    assert [(m.field, m.truth, m.library) for m in j.mismatches] == [("cash_currency", "", "USD")]
    assert str(j.mismatches[0]) == "cash_currency USD != (blank)"


def test_an_ending_with_no_contract_row_is_one_mismatch():
    j = dt.judge_case(_case(exit_kind="merger"), _lib())
    assert [m.field for m in j.mismatches] == ["ending"]


def test_no_ending_wants_no_contract_row():
    assert dt.judge_case(_case(shape="no_ending"), _lib()).ok
    j = dt.judge_case(_case(shape="no_ending"), _lib([contract_row("S1", exit_kind="exchange")]))
    assert [(m.field, m.library) for m in j.mismatches] == [("shape", "ending")]


def test_ending_moved_refuses_the_old_ending_and_scores_the_later_one():
    old = _lib([contract_row("S1", exit_kind="exchange")], [ending("S1", "2010-01-04", "exchange_transfer")])
    assert [m.field for m in dt.judge_case(_case(shape="ending_moved"), old).mismatches] == ["shape"]
    later = _lib([contract_row("S1", exit_kind="merger")], [ending("S1", "2014-04-08")])
    assert dt.judge_case(_case(shape="ending_moved", exit_kind="merger"), later).ok
    assert dt.judge_case(_case(shape="ending_moved"), _lib()).ok          # nothing scored, nothing required


def test_internal_last_trade_date_is_judged_on_delistings_csv():
    lib = _lib([contract_row("S1", last_trade_date="")], [ending("S1", "2010-01-04", ltd="2009-12-31")])
    assert dt.judge_case(_case(last_trade_date="", internal_last_trade_date="2009-12-31"), lib).ok
    j = dt.judge_case(_case(internal_last_trade_date="2010-01-01"), lib)
    assert [(m.field, m.library) for m in j.mismatches] == [("internal_last_trade_date", "2009-12-31")]


def test_legs_need_the_payout_legs_table_and_match_leg_by_leg():
    case = dt.parse_rows([truth_row("S1_2010-01-04", "S1", value_rule="basket")], legs={
        "S1_2010-01-04": (dt.Leg(1, "1", "", "LION", ""), dt.Leg(2, "0.0667", "", "STRZ", ""))})[0]
    contract = [contract_row("S1", value_rule="basket")]
    assert [m.field for m in dt.judge_case(case, _lib(contract)).mismatches] == ["legs"]
    legs = [{"sec_id": "S1", "leg": "1", "ratio": "1.000000", "price_sec_id": "", "price_ticker": "LION",
             "price_date": ""},
            {"sec_id": "S1", "leg": "2", "ratio": "0.066700", "price_sec_id": "", "price_ticker": "STRY",
             "price_date": ""}]
    j = dt.judge_case(case, _lib(contract, legs_rows=legs))
    assert [(m.field, m.truth, m.library) for m in j.mismatches] == [("leg2.price_ticker", "STRZ", "STRY")]
    assert dt.field_key("leg2.price_ticker") == "legs"


def test_judge_all_skips_ruling_pending_cases():
    cases = dt.parse_rows([truth_row("S1_2010-01-04", "S1", exit_kind="merger"),
                           truth_row("S2_2010-01-04", "S2", status="ruling_pending", exit_kind="merger")])
    assert [j.case.case_id for j in dt.judge_all(cases, _lib())] == ["S1_2010-01-04"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_diagnosis_truth.py -q`
Expected: FAIL with `AttributeError: module 'delist_detection.diagnosis_truth' has no attribute 'LibraryRows'`.

- [ ] **Step 4: Append the judge to the module**

Add to the imports of `src/delist_detection/diagnosis_truth.py`:

```python
from collections import defaultdict

from .contract import last_endings
from .lifecycle import Tables
```

Append:

```python
MISMATCH_FIELDS = (*SCORED, "internal_last_trade_date", "shape", "ending", "legs")
LEG_FIELDS = ("ratio", "price_sec_id", "price_ticker", "price_date")


@dataclass(frozen=True)
class Mismatch:
    case_id: str
    field: str
    truth: str
    library: str

    def __str__(self) -> str:
        return f"{self.field} {self.library or '(blank)'} != {self.truth or '(blank)'}"


@dataclass(frozen=True)
class CaseJudgement:
    case: DiagnosisCase
    mismatches: tuple[Mismatch, ...]

    @property
    def ok(self) -> bool:
        return not self.mismatches


@dataclass(frozen=True)
class LibraryRows:
    """What the judge reads from one run: the contract row and the last real ending of each security, and its
    payout legs (None: the run has no contract/payout_legs.csv yet, before sub-plan 5f)."""
    contract: Mapping[str, Mapping[str, str]]
    last_endings: Mapping[str, Mapping[str, str]]
    legs: Mapping[str, Sequence[Mapping[str, str]]] | None = None

    @classmethod
    def of(cls, tables: Tables, legs_rows: Sequence[Mapping[str, str]] | None = None) -> LibraryRows:
        legs = None
        if legs_rows is not None:
            grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
            for r in legs_rows:
                grouped[r["sec_id"]].append(r)
            legs = {k: sorted(v, key=lambda r: int(r["leg"])) for k, v in grouped.items()}
        return cls({r["sec_id"]: r for r in tables.contract_delistings or ()}, last_endings(tables.delistings), legs)


def field_key(name: str) -> str:
    """The MISMATCH_FIELDS entry a mismatch counts under (every `legN.x` is `legs`)."""
    return "legs" if name.startswith("leg") and name != "legs" else name


def _same(name: str, truth: str, library: str) -> bool:
    truth, library = truth.strip(), (library or "").strip()
    if truth == NOT_SCORED:
        return True
    if name in NUMBERS and truth and library:
        try:
            return f"{float(truth):.6g}" == f"{float(library):.6g}"
        except ValueError:
            return False
    if name == "continuation":
        return truth.lower() == library.lower()
    return truth == library


def _judge_legs(case: DiagnosisCase, rows: Sequence[Mapping[str, str]] | None) -> list[Mismatch]:
    if rows is None:
        return [Mismatch(case.case_id, "legs", f"{len(case.legs)} legs", "(no payout_legs table)")]
    out = []
    if len(rows) != len(case.legs):
        out.append(Mismatch(case.case_id, "legs", f"{len(case.legs)} legs", f"{len(rows)} legs"))
    for leg, row in zip(case.legs, rows):
        for name in LEG_FIELDS:
            want = getattr(leg, name)
            if not _same("stock_ratio" if name == "ratio" else name, want, row.get(name, "")):
                out.append(Mismatch(case.case_id, f"leg{leg.leg}.{name}", want, row.get(name, "")))
    return out


def judge_case(case: DiagnosisCase, lib: LibraryRows) -> CaseJudgement:
    """Compare one case to one run; every scored field that disagrees is one Mismatch (spec 1.3)."""
    row, end = lib.contract.get(case.sec_id), lib.last_endings.get(case.sec_id)
    bad: list[Mismatch] = []

    def miss(name: str, truth: str, library: str) -> None:
        bad.append(Mismatch(case.case_id, name, truth, library))

    if case.shape == NO_ENDING:
        if row is not None:
            miss("shape", NO_ENDING, "ending")
        return CaseJudgement(case, tuple(bad))
    if case.shape == ENDING_MOVED and end is not None and end["delist_date"] == case.old_delist_date:
        miss("shape", ENDING_MOVED, f"ending {case.old_delist_date}")
    scored = [f for f in SCORED if case.fields[f] != NOT_SCORED]
    if row is None:
        if case.shape == ENDING or scored:
            miss("ending", "present", "(no contract row)")
        return CaseJudgement(case, tuple(bad))
    for name in scored:
        if not _same(name, case.fields[name], row.get(name, "")):
            miss(name, case.fields[name], row.get(name, ""))
    if case.internal_last_trade_date not in ("", NOT_SCORED):
        got = end["last_trade_date"] if end else ""
        if got != case.internal_last_trade_date:
            miss("internal_last_trade_date", case.internal_last_trade_date, got)
    if case.legs:
        bad.extend(_judge_legs(case, None if lib.legs is None else lib.legs.get(case.sec_id, [])))
    return CaseJudgement(case, tuple(bad))


def judge_all(cases: Sequence[DiagnosisCase], lib: LibraryRows) -> list[CaseJudgement]:
    """Every case that is not ruling_pending, judged."""
    return [judge_case(c, lib) for c in cases if c.status != RULING_PENDING]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_diagnosis_truth.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/diagnosis_truth.py tests/lifecycle_tables.py tests/test_diagnosis_truth.py
git commit -m "Diagnosis truth judge: one mismatch per scored field, by shape and leg (sub-plan 5-0)"
```

---

### Task 3: The scorecard's D lines and the strict per-case test

**Files:**
- Modify: `src/delist_detection/scorecard.py`
- Modify: `scripts/scorecard.py`
- Modify: `tests/test_scorecard.py`, `tests/test_scorecard_script.py`, `tests/test_scorecard_floor.py`
- Create: `tests/test_diagnosis_truth_cases.py`

**Interfaces:**
- Consumes: Task 2's `LibraryRows`, `judge_all`, `field_key`, `MISMATCH_FIELDS`, `load_diagnosis_truth`,
  `DiagnosisCase`, and the statuses.
- Produces:
  - `ScorecardConfig.diagnosis: Sequence[DiagnosisCase]`.
  - Config keys `"diagnosis"` and `"diagnosis_legs"`, file names relative to the config's folder.
  - `build(tables, *, as_of, config=..., legs_rows=None)`, whose card gains `"diagnosis_failures": list[str]` and
    the metrics `D.cases`, `D.ruling_pending`, `D.known_wrong`, `D.known_wrong_now_right`, `D.cases_matching`,
    `D.mismatches` and `D.mismatches.<field>`.
  - METRICS gains `D.mismatches` and `D.mismatches.<field>` (DOWN), and `D.cases_matching` (UP).
  - `scripts/scorecard.py` reads `<output-dir>/contract/payout_legs.csv` when present, prints
    `DIAGNOSIS FAILING <line>`, and `--check` returns 1 on any diagnosis failure.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scorecard.py`:

```python
from delist_detection import diagnosis_truth as dt
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row


def test_diagnosis_lines_count_mismatches_by_field_and_list_failing_pass_cases():
    cases = dt.parse_rows([
        truth_row("A_2012-03-10", "A", exit_kind="merger", value_rule="cash", cash_per_share="10"),
        truth_row("B_2010-05-10", "B", status="known_wrong", fixed_by="5a", shape="no_ending"),
        truth_row("C_2011-01-01", "C", status="ruling_pending", exit_kind="merger"),
    ])
    t = tables(delistings=[ending("A", "2012-03-10", ltd="2012-03-01"),
                           ending("B", "2010-05-10", "exchange_transfer")],
               contract_delistings=[contract_row("A", exit_kind="merger", value_rule="cash",
                                                 cash_per_share="9.000000"),
                                    contract_row("B", exit_kind="exchange", value_rule="transfer")])
    card = sc.build(t, as_of=AS_OF, config=ScorecardConfig(diagnosis=cases))
    m = card["metrics"]
    assert (m["D.cases"], m["D.ruling_pending"], m["D.known_wrong"], m["D.cases_matching"]) == (3, 1, 1, 0)
    assert (m["D.mismatches"], m["D.mismatches.cash_per_share"], m["D.mismatches.shape"]) == (2, 1, 1)
    assert m["D.mismatches.exit_kind"] == 0 and m["D.known_wrong_now_right"] == 0
    assert card["diagnosis_failures"] == ["A_2012-03-10: cash_per_share 9.000000 != 10"]


def test_no_diagnosis_lines_without_a_truth_set_or_a_contract():
    assert not any(k.startswith("D.") for k in sc.build(_tables(), as_of=AS_OF)["metrics"])
    cases = dt.parse_rows([truth_row("A_2012-03-10", "A", exit_kind="merger")])
    card = sc.build(_tables(), as_of=AS_OF, config=ScorecardConfig(diagnosis=cases))
    assert not any(k.startswith("D.") for k in card["metrics"]) and card["diagnosis_failures"] == []


def test_load_config_reads_the_diagnosis_truth_and_its_legs(tmp_path):
    dt.write_diagnosis_truth(tmp_path / "d.csv", [truth_row("A_2012-03-10", "A", value_rule="basket")])
    dt.write_legs(tmp_path / "l.csv", [{"case_id": "A_2012-03-10", "leg": "1", "ratio": "1", "price_sec_id": "",
                                        "price_ticker": "X", "price_date": ""}])
    cfg = tmp_path / "scorecard.json"
    cfg.write_text(json.dumps({"diagnosis": "d.csv", "diagnosis_legs": "l.csv"}))
    [case] = sc.load_config(cfg).diagnosis
    assert case.case_id == "A_2012-03-10" and case.legs[0].price_ticker == "X"
```

Append to `tests/test_scorecard_script.py`:

```python
from delist_detection import diagnosis_truth as dt
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row


def test_check_fails_on_a_failing_diagnosis_pass_case(tmp_path, out, capsys):
    store.write_tables(out, {"contract_delistings": [contract_row("A", exit_kind="merger", value_rule="cash")]})
    dt.write_diagnosis_truth(tmp_path / "d.csv", [truth_row("A_2012-03-10", "A", exit_kind="exchange")])
    cfg = tmp_path / "scorecard.json"
    cfg.write_text(json.dumps({"diagnosis": "d.csv", "floor": {}}))
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--check"]) == 1
    assert "DIAGNOSIS FAILING A_2012-03-10: exit_kind merger != exchange" in capsys.readouterr().out
```

In `tests/test_scorecard_floor.py`, after `assert card["golden_failures"] == []`, add:

```python
    assert card["diagnosis_failures"] == []
```

Create `tests/test_diagnosis_truth_cases.py`:

```python
"""The diagnosis truth set (data/diagnosis_truth.csv) against the committed output tables. A `pass` case must
match. A `known_wrong` case must still mismatch (strict xfail) until the sub-plan in its `fixed_by` lands; then the
loop's update_truth step, or the plan, flips it to `pass`. A `ruling_pending` case is not judged."""
from pathlib import Path

import pytest

from delist_detection.diagnosis_truth import (KNOWN_WRONG, RULING_PENDING, LibraryRows, judge_case,
                                              load_diagnosis_truth)
from delist_detection.lifecycle import Tables

ROOT = Path(__file__).resolve().parents[1]
TRUTH = ROOT / "data" / "diagnosis_truth.csv"
if not TRUTH.exists():
    pytest.skip("no data/diagnosis_truth.csv yet (sub-plan 5-0 builds it)", allow_module_level=True)
CASES = load_diagnosis_truth(TRUTH, ROOT / "data" / "diagnosis_truth_legs.csv")


@pytest.fixture(scope="module")
def lib():
    legs = ROOT / "output" / "contract" / "payout_legs.csv"
    rows = None
    if legs.exists():
        import csv
        with legs.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
    return LibraryRows.of(Tables.read(ROOT / "output"), rows)


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_diagnosis_case(case, lib, request):
    if case.status == RULING_PENDING:
        pytest.skip(f"ruling pending: {case.note}")
    if case.status == KNOWN_WRONG:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"known wrong until {case.fixed_by}"))
    j = judge_case(case, lib)
    assert j.ok, "; ".join(map(str, j.mismatches))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_scorecard.py tests/test_scorecard_script.py -q`
Expected: FAIL. The new tests fail with `TypeError: ScorecardConfig.__init__() got an unexpected keyword argument 'diagnosis'`, and the config test fails with `ScorecardConfigError: ... unknown key(s) ['diagnosis', 'diagnosis_legs']`.

- [ ] **Step 3: Implement the scorecard lines**

In `src/delist_detection/scorecard.py`:

Add to the imports:

```python
from .diagnosis_truth import (KNOWN_WRONG as D_KNOWN_WRONG, MISMATCH_FIELDS, PASS as D_PASS, RULING_PENDING,
                              DiagnosisCase, LibraryRows, field_key, judge_all as judge_diagnosis,
                              load_diagnosis_truth)
```

Extend `METRICS` (inside the dict literal, after the census line):

```python
    "D.mismatches": DOWN, "D.cases_matching": UP,
    **{f"D.mismatches.{f}": DOWN for f in MISMATCH_FIELDS},
```

Extend the module docstring's list with:

```
- D.x: the diagnosis truth set (`data/diagnosis_truth.csv`, spec 2026-10-03-diagnosis-truth-fixes),
  judged by `diagnosis_truth.judge_case` against contract/delistings.csv.
```

Change `ScorecardConfig`:

```python
@dataclass(frozen=True)
class ScorecardConfig:
    window: Window | None = None
    floor: Mapping[str, float] = field(default_factory=dict)
    golden: Sequence[TruthCase] = ()
    audit: Sequence[TruthCase] = ()
    diagnosis: Sequence[DiagnosisCase] = ()
```

In `load_config`: change the docstring's first line to name the new keys:
`"golden": file, "audit": file, "diagnosis": file, "diagnosis_legs": file`.

Change the unknown-key check to:

```python
    unknown = set(raw) - {"window", "floor", "golden", "audit", "diagnosis", "diagnosis_legs"}
```

Replace the final `return` with:

```python
    def diagnosis() -> list[DiagnosisCase]:
        name = raw.get("diagnosis")
        if not name or not (path.parent / name).exists():
            return []
        legs = raw.get("diagnosis_legs")
        return load_diagnosis_truth(path.parent / name, path.parent / legs if legs else None)
    return ScorecardConfig(window, dict(floor), cases("golden"), cases("audit"), diagnosis())
```

Add, before `build`:

```python
def _diagnosis_lines(tables: Tables, config: ScorecardConfig,
                     legs_rows: Sequence[Mapping[str, str]] | None) -> tuple[dict[str, float], list[str]]:
    """The D lines and the failing `pass` cases; none without a truth set or a contract with payout columns."""
    if not config.diagnosis or tables.contract_delistings is None:
        return {}, []
    judged = judge_diagnosis(config.diagnosis, LibraryRows.of(tables, legs_rows))
    counts = Counter(field_key(m.field) for j in judged for m in j.mismatches)
    out: dict[str, float] = {
        "D.cases": len(config.diagnosis),
        "D.ruling_pending": sum(c.status == RULING_PENDING for c in config.diagnosis),
        "D.known_wrong": sum(j.case.status == D_KNOWN_WRONG for j in judged),
        "D.known_wrong_now_right": sum(j.ok for j in judged if j.case.status == D_KNOWN_WRONG),
        "D.cases_matching": sum(j.ok for j in judged),
        "D.mismatches": sum(counts.values()),
        **{f"D.mismatches.{f}": counts.get(f, 0) for f in MISMATCH_FIELDS},
    }
    failures = [f"{j.case.case_id}: {'; '.join(map(str, j.mismatches))}" for j in judged
                if j.case.status == D_PASS and not j.ok]
    return out, failures
```

Change `build`:

```python
def build(tables: Tables, *, as_of: date, config: ScorecardConfig = ScorecardConfig(),
          legs_rows: Sequence[Mapping[str, str]] | None = None) -> dict:
    """The scorecard of one run's tables: {"as_of", "window", "metrics", "golden_failures", "diagnosis_failures"}.
    `legs_rows` are contract/payout_legs.csv's rows when the run has that table."""
    view = LifecycleView(tables)
    unc = None if tables.uncertain is None else _Uncertain.of(tables.uncertain)
    diag, diag_failures = _diagnosis_lines(tables, config, legs_rows)
    metrics = {**_lifecycle_lines(view), **_identity_lines(tables), **_ending_lines(tables, config.window),
               **_verdict_lines(tables, view, config.window, unc), **_truth_lines(view, config, unc), **diag}
    failures = [f"{j.case.case}: {'; '.join(j.mismatches)}" for j in judge_all(config.golden, view)
                if j.case.status == PASS and not j.ok]
    window = None if config.window is None else {"start": config.window.start, "end": config.window.end}
    return {"as_of": as_of.isoformat(), "window": window, "metrics": metrics, "golden_failures": failures,
            "diagnosis_failures": diag_failures}
```

In `scripts/scorecard.py`:

Add `LEGS_FILE = "contract/payout_legs.csv"` near `LIFECYCLE_COLUMNS`, and a reader:

```python
def legs_rows(out_dir: Path) -> list[dict[str, str]] | None:
    """contract/payout_legs.csv's rows, or None when the run has no such table (before sub-plan 5f)."""
    path = out_dir / LEGS_FILE
    if not path.exists():
        return None
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))
```

Replace `card = build(tables, as_of=as_of, config=config)` with
`card = build(tables, as_of=as_of, config=config, legs_rows=legs_rows(args.output_dir))`.

After the `GOLDEN FAILING` loop, add:

```python
    for line in card["diagnosis_failures"]:
        print(f"DIAGNOSIS FAILING {line}")
```

Change the final check to:

```python
    if args.check and (card["drops"] or card["golden_failures"] or card["diagnosis_failures"]):
        return 1
```

Extend the script docstring's `--check` line to say "or a diagnosis pass case fails".

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_scorecard.py tests/test_scorecard_script.py tests/test_scorecard_floor.py tests/test_diagnosis_truth_cases.py -q`
Expected: PASS. `test_diagnosis_truth_cases.py` is skipped, because there is no truth file yet.

- [ ] **Step 5: Run the full suite**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all passed except the 18 known-wrong golden xfails. The pipeline's own `_scorecard` call still works,
because `legs_rows` defaults to None.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/scorecard.py scripts/scorecard.py tests/test_scorecard.py tests/test_scorecard_script.py tests/test_scorecard_floor.py tests/test_diagnosis_truth_cases.py
git commit -m "Scorecard: D lines from the diagnosis truth set, its failing pass cases gate --check (sub-plan 5-0)"
```

---

### Task 4: The regression report

**Files:**
- Create: `src/delist_detection/regression.py`
- Create: `scripts/regression_report.py`
- Test: `tests/test_regression.py`

**Interfaces:**
- Consumes: `store.table_path`, `atomic_io.write_atomic`, and Task 1's `DiagnosisCase` and statuses
  (`PASS`, `KNOWN_WRONG`, `RULING_PENDING`, `REGRESSION_PENDING`).
- Produces:
  - `REPORT_COLUMNS = ("sec_id", "table", "field", "kind", "old", "new")` and `CHANGED, ADDED, REMOVED`.
  - `@dataclass(frozen=True) Snapshot(delistings, security_history, id_changes=())`.
  - `class RegressionInputError(ValueError)`.
  - `read_snapshot(out_dir) -> Snapshot` and `snapshot_at(repo, rev, out_dir) -> Snapshot`.
  - `successor_chain(sec_ids, *delistings) -> set[str]`.
  - `excluded(cases, *delistings) -> set[str]`: truth sec_ids and their chains, leaving out loop-added pending
    rows.
  - `diff_contract(base, new, exclude=()) -> list[dict[str, str]]`.
  - `regression_key(row) -> str` and `write_report(path, rows)`.
  - `unexplained(rows, cases, settled) -> list[dict]`, where `settled` is the set of regression keys the ledger
    holds as `new_right`.
  - Script: `python scripts/regression_report.py --base REV [--output-dir output] [--truth data/diagnosis_truth.csv] [--out output/regression_report.csv]`.
    It exits 2 on a `RegressionInputError` or a truth file error.

- [ ] **Step 1: Write the failing tests**

`tests/test_regression.py`:

```python
"""regression: the contract diff outside the truth set (spec 1.4)."""
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

from delist_detection import diagnosis_truth as dt
from delist_detection import regression as rg
from delist_detection import store
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row, hist

ROOT = Path(__file__).resolve().parents[1]


def _snap(delistings=(), history=(), ids=()):
    return rg.Snapshot(list(delistings), list(history), list(ids))


def test_a_changed_field_is_one_row_and_the_verdict_column_is_ignored():
    base = _snap([contract_row("A", last_trade_date="2010-09-30", verdict="uncertain")])
    new = _snap([contract_row("A", last_trade_date="2010-10-01", verdict="confirmed")])
    assert rg.diff_contract(base, new) == [{"sec_id": "A", "table": "delistings", "field": "last_trade_date",
                                            "kind": "changed", "old": "2010-09-30", "new": "2010-10-01"}]


def test_added_and_removed_rows_and_ticker_ranges_and_id_changes():
    base = _snap([contract_row("A", exit_kind="merger")], [hist("A", "1", "2008-01-02", "2010-01-01")])
    new = _snap([contract_row("B", exit_kind="exchange")],
                [hist("A", "1", "2008-01-02", "2011-01-01"), hist("B", "2", "2011-01-03")],
                [{"old_sec_id": "CIK9-COMMON", "new_sec_id": "BBGX", "changed_on": "", "issuer_cik": "9",
                  "share_class": "COMMON"}])
    rows = rg.diff_contract(base, new)
    assert [(r["sec_id"], r["table"], r["kind"]) for r in rows] == [
        ("A", "delistings", "removed"), ("B", "delistings", "added"), ("A", "security_history", "changed"),
        ("B", "security_history", "added"), ("CIK9-COMMON", "id_changes", "added")]
    assert rows[2]["old"] == "AAA:2008-01-02..2010-01-01:1" and rows[4]["new"] == "BBGX"


def test_excluded_securities_are_left_out():
    base = _snap([contract_row("A", exit_kind="merger"), contract_row("Z", exit_kind="merger")])
    new = _snap([contract_row("A", exit_kind="exchange"), contract_row("Z", exit_kind="exchange")])
    assert [r["sec_id"] for r in rg.diff_contract(base, new, exclude={"A"})] == ["Z"]


def test_successor_chain_follows_every_table_transitively():
    a = [contract_row("A", successor_sec_id="B")]
    b = [contract_row("B", successor_sec_id="C")]
    assert rg.successor_chain({"A"}, a, b) == {"A", "B", "C"}


def test_excluded_keeps_loop_added_pending_rows_in_the_report():
    cases = dt.parse_rows([truth_row("A_2010-01-04", "A"),
                           truth_row("P_5a-r1", "P", status="ruling_pending", fixed_by="regression")])
    assert rg.excluded(cases, [contract_row("A", successor_sec_id="B")]) == {"A", "B"}


def test_unexplained_counts_rows_not_settled_and_pending_regressions():
    rows = [{"sec_id": "Z", "table": "delistings", "field": "exit_kind", "kind": "changed", "old": "a", "new": "b"},
            {"sec_id": "Y", "table": "security_history", "field": "ranges", "kind": "changed", "old": "x",
             "new": "y"}]
    cases = dt.parse_rows([truth_row("P_5a-r1", "P", status="ruling_pending", fixed_by="regression")])
    left = rg.unexplained(rows, cases, settled={rg.regression_key(rows[1])})
    assert [r["sec_id"] for r in left] == ["Z", "P"]


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def _repo(tmp_path, with_contract=True):
    repo = tmp_path / "repo"
    out = repo / "output"
    out.mkdir(parents=True)
    _git(repo, "init", "-q")
    if with_contract:
        store.write_tables(out, {"contract_delistings": [contract_row("Z", exit_kind="merger")],
                                 "security_history": [hist("Z", "1", "2008-01-02", "2010-01-01")]})
    (out / "keep.txt").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, out


def test_snapshot_at_reads_the_base_commit(tmp_path):
    repo, out = _repo(tmp_path)
    store.write_tables(out, {"contract_delistings": [contract_row("Z", exit_kind="exchange")]})
    base = rg.snapshot_at(repo, "HEAD", out)
    assert base.delistings[0]["exit_kind"] == "merger" and base.id_changes == []
    assert rg.read_snapshot(out).delistings[0]["exit_kind"] == "exchange"


def _script():
    spec = importlib.util.spec_from_file_location("regression_report", ROOT / "scripts" / "regression_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_writes_the_report(tmp_path, capsys):
    repo, out = _repo(tmp_path)
    store.write_tables(out, {"contract_delistings": [contract_row("Z", exit_kind="exchange")]})
    report = tmp_path / "report.csv"
    argv = ["--repo", str(repo), "--base", "HEAD", "--output-dir", str(out), "--truth", str(tmp_path / "none.csv"),
            "--out", str(report)]
    assert _script().main(argv) == 0
    assert "Z,delistings,exit_kind,changed,merger,exchange" in report.read_text()


def test_script_exits_2_when_the_base_lacks_the_contract(tmp_path, capsys):
    repo, out = _repo(tmp_path, with_contract=False)
    store.write_tables(out, {"contract_delistings": [contract_row("Z", exit_kind="exchange")],
                             "security_history": []})
    argv = ["--repo", str(repo), "--base", "HEAD", "--output-dir", str(out), "--truth", str(tmp_path / "none.csv"),
            "--out", str(tmp_path / "r.csv")]
    assert _script().main(argv) == 2
    assert "HEAD:output/contract/delistings.csv" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_regression.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'delist_detection.regression'`.

- [ ] **Step 3: Write the module**

`src/delist_detection/regression.py`:

```python
"""The diagnosis loop's regression report (spec 2026-10-03-diagnosis-truth-fixes, section 1.4): every contract
field that changed between a base commit's run and this one, for securities outside the diagnosis truth set and
its successor chains.

A security's contract/delistings.csv row is compared column by column. The verdict column is left out: the loop
judges classification, and sub-plan 5i changes verdicts on purpose. Its contract/security_history.csv rows are
compared as one list of ranges, and a new contract/id_changes.csv row (a placeholder that now holds a FIGI) is
listed too. A report row is explained when the ledger settled that exact change as right (`new_right`); a
regressed row the loop added to the truth file as ruling_pending (fixed_by `regression`) stays unexplained until
the operator settles it."""
from __future__ import annotations

import csv
import io
import subprocess
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import store
from .atomic_io import write_atomic
from .diagnosis_truth import REGRESSION_PENDING, RULING_PENDING, DiagnosisCase

REPORT_COLUMNS = ("sec_id", "table", "field", "kind", "old", "new")
CHANGED, ADDED, REMOVED = "changed", "added", "removed"
SKIPPED_COLUMNS = frozenset({"sec_id", "verdict"})
BRIEF_COLUMNS = ("exit_kind", "drop_reason", "continuation", "successor_sec_id", "last_trade_date", "value_rule")


class RegressionInputError(ValueError):
    """A base commit or output folder that lacks a contract file; the message names it."""


@dataclass(frozen=True)
class Snapshot:
    """One run's contract files, as string rows."""
    delistings: Sequence[Mapping[str, str]]
    security_history: Sequence[Mapping[str, str]]
    id_changes: Sequence[Mapping[str, str]] = field(default=())


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def read_snapshot(out_dir: str | Path) -> Snapshot:
    """The contract files under `out_dir` (contract/id_changes.csv may be missing)."""
    def rows(name: str, required: bool = True) -> list[dict[str, str]]:
        path = store.table_path(out_dir, name)
        if not path.exists():
            if required:
                raise RegressionInputError(f"{path}: missing")
            return []
        return _rows(path.read_text(encoding="utf-8"))
    return Snapshot(rows("contract_delistings"), rows("security_history"), rows("id_changes", required=False))


def snapshot_at(repo: str | Path, rev: str, out_dir: str | Path) -> Snapshot:
    """The contract files as commit `rev` of git repository `repo` holds them (`out_dir` lies inside `repo`)."""
    root = Path(repo).resolve()

    def rows(name: str, required: bool = True) -> list[dict[str, str]]:
        rel = store.table_path(Path(out_dir).resolve(), name).relative_to(root).as_posix()
        done = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{rel}"], capture_output=True, text=True)
        if done.returncode != 0:
            if required:
                raise RegressionInputError(f"{rev}:{rel}: {done.stderr.strip() or 'not in that commit'}")
            return []
        return _rows(done.stdout)
    return Snapshot(rows("contract_delistings"), rows("security_history"), rows("id_changes", required=False))


def successor_chain(sec_ids: Collection[str], *delistings: Sequence[Mapping[str, str]]) -> set[str]:
    """`sec_ids` and every security their contract rows lead to through successor_sec_id, in any of the tables."""
    nxt: dict[str, set[str]] = defaultdict(set)
    for rows in delistings:
        for r in rows:
            if r.get("successor_sec_id"):
                nxt[r["sec_id"]].add(r["successor_sec_id"])
    out: set[str] = set()
    todo = list(sec_ids)
    while todo:
        s = todo.pop()
        if s not in out:
            out.add(s)
            todo.extend(nxt.get(s, ()))
    return out


def _pending_regression(c: DiagnosisCase) -> bool:
    return c.status == RULING_PENDING and c.fixed_by == REGRESSION_PENDING


def excluded(cases: Sequence[DiagnosisCase], *delistings: Sequence[Mapping[str, str]]) -> set[str]:
    """The securities the report leaves out: every truth case's security and its successor chain, except a
    regressed row the loop could not settle (it keeps showing until the operator does)."""
    return successor_chain({c.sec_id for c in cases if not _pending_regression(c)}, *delistings)


def _row(sec: str, table: str, name: str, kind: str, old: str, new: str) -> dict[str, str]:
    return dict(zip(REPORT_COLUMNS, (sec, table, name, kind, old, new)))


def _brief(row: Mapping[str, str]) -> str:
    return ";".join(f"{c}={row.get(c, '')}" for c in BRIEF_COLUMNS)


def _ranges(rows: Sequence[Mapping[str, str]]) -> dict[str, str]:
    by: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by[r["sec_id"]].append(f"{r['ticker']}:{r['start_date']}..{r['end_date']}:{r['issuer_id']}")
    return {k: ";".join(sorted(v)) for k, v in by.items()}


def diff_contract(base: Snapshot, new: Snapshot, exclude: Collection[str] = ()) -> list[dict[str, str]]:
    """Every change from `base` to `new` outside `exclude`: delistings rows first (by sec_id, then column), then
    ticker ranges, then new id_changes rows."""
    skip = set(exclude)
    out: list[dict[str, str]] = []
    old_rows = {r["sec_id"]: r for r in base.delistings}
    new_rows = {r["sec_id"]: r for r in new.delistings}
    for sec in sorted((old_rows.keys() | new_rows.keys()) - skip):
        o, n = old_rows.get(sec), new_rows.get(sec)
        if o is None:
            out.append(_row(sec, "delistings", "", ADDED, "", _brief(n)))
        elif n is None:
            out.append(_row(sec, "delistings", "", REMOVED, _brief(o), ""))
        else:
            for col in dict.fromkeys([*o, *n]):
                if col not in SKIPPED_COLUMNS and o.get(col, "") != n.get(col, ""):
                    out.append(_row(sec, "delistings", col, CHANGED, o.get(col, ""), n.get(col, "")))
    old_r, new_r = _ranges(base.security_history), _ranges(new.security_history)
    for sec in sorted((old_r.keys() | new_r.keys()) - skip):
        if old_r.get(sec, "") != new_r.get(sec, ""):
            kind = ADDED if sec not in old_r else REMOVED if sec not in new_r else CHANGED
            out.append(_row(sec, "security_history", "ranges", kind, old_r.get(sec, ""), new_r.get(sec, "")))
    seen = {(r["old_sec_id"], r["new_sec_id"]) for r in base.id_changes}
    for r in new.id_changes:
        if (r["old_sec_id"], r["new_sec_id"]) not in seen and r["old_sec_id"] not in skip:
            out.append(_row(r["old_sec_id"], "id_changes", "new_sec_id", ADDED, r["old_sec_id"], r["new_sec_id"]))
    return out


def regression_key(row: Mapping[str, str]) -> str:
    """The ledger key of one report row."""
    return "reg|" + "|".join(row[c] for c in REPORT_COLUMNS)


def unexplained(rows: Sequence[Mapping[str, str]], cases: Sequence[DiagnosisCase],
                settled: Collection[str]) -> list[dict[str, str]]:
    """The report rows the ledger has not settled as right, then one row per regressed security the loop added to
    the truth file as ruling_pending."""
    left = [dict(r) for r in rows if regression_key(r) not in settled]
    left += [_row(c.sec_id, "truth", "status", RULING_PENDING, "", c.note) for c in cases if _pending_regression(c)]
    return left


def write_report(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(REPORT_COLUMNS), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(Path(path), buf.getvalue())
```

- [ ] **Step 4: Write the script**

`scripts/regression_report.py`:

```python
"""Compare this run's contract with a base commit's, outside the diagnosis truth set (spec
2026-10-03-diagnosis-truth-fixes, section 1.4).

  python scripts/regression_report.py --base <commit>     # -> output/regression_report.csv

Offline (git only). Exit 2: the base commit or the output folder lacks a contract file, or the truth file is bad.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from delist_detection.diagnosis_truth import load_diagnosis_truth
from delist_detection.regression import (RegressionInputError, diff_contract, excluded, read_snapshot, snapshot_at,
                                         write_report)
from delist_detection.truth import TruthFileError

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", required=True, help="the commit the sub-plan started from")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, default=ROOT / "data" / "diagnosis_truth.csv")
    p.add_argument("--out", type=Path, default=ROOT / "output" / "regression_report.csv")
    args = p.parse_args(argv)
    try:
        base, new = snapshot_at(args.repo, args.base, args.output_dir), read_snapshot(args.output_dir)
        cases = load_diagnosis_truth(args.truth) if args.truth.exists() else []
    except (RegressionInputError, TruthFileError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    rows = diff_contract(base, new, excluded(cases, base.delistings, new.delistings))
    write_report(args.out, rows)
    print(f"{len(rows)} changed field(s) in {len({r['sec_id'] for r in rows})} securities -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_regression.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/regression.py scripts/regression_report.py tests/test_regression.py
git commit -m "Regression report: contract changes against a base commit, outside the truth set (sub-plan 5-0)"
```

---

### Task 5: The loop's ledger, case rows and round script

**Files:**
- Create: `src/delist_detection/diagnosis_loop.py`
- Create: `scripts/truth_loop_round.py`
- Modify: `scripts/scorecard.py` (D.unexplained_regressions)
- Test: `tests/test_diagnosis_loop.py`

**Interfaces:**
- Consumes:
  - Task 2's `Mismatch`, `CaseJudgement` and `judge_all`.
  - Task 4's `regression_key`, `diff_contract`, `excluded`, `snapshot_at`, `read_snapshot`, `unexplained` and
    `write_report`.
  - `contract.last_endings` and `lifecycle.Tables`.
- Produces:
  - `LEDGER_COLUMNS = ("key", "kind", "sec_id", "label", "round", "outcome", "report")`.
  - Outcomes `KNOWN`, `NEW_RIGHT`, `OLD_RIGHT`, `TRUTH_RIGHT`, `LIBRARY_RIGHT` and `PENDING` (lowercase strings).
  - `mismatch_key(m) -> str`.
  - `read_ledger(path) -> list[dict]` and `write_ledger(path, rows)`.
  - `ledger_keys(rows) -> set[str]` and `settled_keys(rows) -> set[str]` (outcome `new_right`).
  - `seed_rows(judgements, keys, label) -> list[dict]`.
  - `CONTEXT_COLUMNS`, and `CASE_COLUMNS = ("case_id", "mode", "sec_id", "ticker", "truth_case_id", "keys", "fields", "side_a", "side_b", *CONTEXT_COLUMNS)`.
  - `context(tables, sec_id) -> dict`.
  - `case_rows(mismatches, regressions, tables, *, label, round_no, truth_sec) -> list[dict]`. `keys`, `fields`,
    `side_a` and `side_b` are JSON lists. Mismatch mode puts truth in `side_a` and the library value in `side_b`;
    regression mode puts the old value in `side_a` and the new value in `side_b`.
  - `rename_truth(rows, id_changes) -> tuple[list[dict], list[dict]]`, returning the rows and the change-log
    entries.
  - Constants `LEDGER = "output/diagnose_unknown_report/loop/diagnosed.csv"` and
    `LOOP_DIR = "output/diagnose_unknown_report/loop"`.
  - Script:
    - `python scripts/truth_loop_round.py --label L --base REV --round N` prints one JSON line:
      `{"label", "round", "mismatches_new", "regressions_new", "cases": [{"case_id", "mode", "ticker"}], "path"}`.
    - `--seed-ledger --label 5-0` records every current mismatch as `known`.
  - `scripts/scorecard.py` adds the metric `D.unexplained_regressions` when `output/regression_report.csv` exists,
    and `--check` returns 1 when it is above 0.

- [ ] **Step 1: Write the failing tests**

`tests/test_diagnosis_loop.py`:

```python
"""diagnosis_loop: error keys, the ledger, case rows and placeholder renames (spec 1.7)."""
import json

from delist_detection import diagnosis_loop as dl
from delist_detection import diagnosis_truth as dt
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row, ending, hist, tables


def _judged(contract):
    cases = dt.parse_rows([truth_row("A_2010-01-04", "A", exit_kind="merger", last_trade_date="2010-01-01")])
    return dt.judge_all(cases, dt.LibraryRows.of(tables(contract_delistings=contract)))


def test_mismatch_key_names_the_case_field_and_both_values():
    [j] = _judged([contract_row("A", exit_kind="exchange", last_trade_date="2010-01-01")])
    assert dl.mismatch_key(j.mismatches[0]) == "mis|A_2010-01-04|exit_kind|merger|exchange"


def test_ledger_round_trip_and_settled_keys(tmp_path):
    path = tmp_path / "loop" / "diagnosed.csv"
    rows = [dict(key="k1", kind="regression", sec_id="Z", label="5a", round="1", outcome="new_right", report="r"),
            dict(key="k2", kind="mismatch", sec_id="A", label="5a", round="1", outcome="pending", report="")]
    dl.write_ledger(path, rows)
    back = dl.read_ledger(path)
    assert back == rows and dl.ledger_keys(back) == {"k1", "k2"} and dl.settled_keys(back) == {"k1"}
    assert dl.read_ledger(tmp_path / "absent.csv") == []


def test_seeding_twice_adds_nothing():
    judged = _judged([contract_row("A", exit_kind="exchange", last_trade_date="2010-01-02")])
    first = dl.seed_rows(judged, set(), "5-0")
    assert [r["outcome"] for r in first] == ["known", "known"]
    assert dl.seed_rows(judged, dl.ledger_keys(first), "5-0") == []


def test_context_collapses_ticker_ranges_and_reads_the_last_real_ending():
    t = tables(delistings=[ending("A", "2010-01-04", ltd="2010-01-01", reason="Merger")],
               security_history=[hist("A", "100", "2008-01-02", "2009-01-01", "OLD"),
                                 hist("A", "100", "2009-01-02", "2010-01-01", "NEW")],
               uncertain=[{"kind": "ending", "ticker": "NEW", "sec_id": "A", "date": "2010-01-04",
                           "reason": "continued_filings_rule", "candidates": ""}])
    c = dl.context(t, "A")
    assert (c["tickers"], c["first_start"], c["last_end"], c["intervals"]) == ("OLD;NEW", "2008-01-02",
                                                                               "2010-01-01", "2")
    assert (c["delist_date"], c["reason"], c["uncertain_reasons"]) == ("2010-01-04", "Merger",
                                                                       "continued_filings_rule")


def test_case_rows_group_errors_by_security_with_json_cells():
    [j] = _judged([contract_row("A", exit_kind="exchange", last_trade_date="2010-01-02")])
    reg = [{"sec_id": "Z", "table": "delistings", "field": "", "kind": "added", "old": "", "new": "exit_kind=merger"}]
    t = tables(security_history=[hist("Z", "9", "2008-01-02", "", "ZZZ")])
    rows = dl.case_rows(list(j.mismatches), reg, t, label="5a", round_no=1, truth_sec={"A_2010-01-04": "A"})
    assert [(r["case_id"], r["mode"], r["truth_case_id"]) for r in rows] == [
        ("A_5a-r1", "mismatch", "A_2010-01-04"), ("Z_5a-r1", "regression", "")]
    assert json.loads(rows[0]["fields"]) == ["exit_kind", "last_trade_date"]
    assert json.loads(rows[0]["side_a"]) == ["merger", "2010-01-01"]
    assert json.loads(rows[0]["side_b"]) == ["exchange", "2010-01-02"]
    assert json.loads(rows[1]["fields"]) == ["delistings.added"] and rows[1]["ticker"] == "ZZZ"
    assert json.loads(rows[1]["keys"])[0].startswith("reg|Z|delistings||added")


def test_rename_truth_follows_id_changes():
    rows = [truth_row("CIK9-COMMON_2010-01-04", "CIK9-COMMON"), truth_row("B_2010-01-04", "B")]
    ids = [{"old_sec_id": "CIK9-COMMON", "new_sec_id": "BBGX", "changed_on": "2026-10-04", "issuer_cik": "9",
            "share_class": "COMMON"}]
    renamed, changes = dl.rename_truth(rows, ids)
    assert [r["sec_id"] for r in renamed] == ["BBGX", "B"]
    assert renamed[0]["case_id"] == "CIK9-COMMON_2010-01-04"
    assert [(c["case_id"], c["field"], c["old"], c["new"]) for c in changes] == [
        ("CIK9-COMMON_2010-01-04", "sec_id", "CIK9-COMMON", "BBGX")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_diagnosis_loop.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'delist_detection.diagnosis_loop'`.

- [ ] **Step 3: Write the module**

`src/delist_detection/diagnosis_loop.py`:

```python
"""The diagnosis loop's bookkeeping (spec 2026-10-03-diagnosis-truth-fixes, section 1.7). It covers which errors
a round must diagnose, the ledger of errors already diagnosed, the case rows the diagnose workflow reads, and
renaming truth rows whose placeholder now holds a FIGI.

An error is a truth mismatch (a scored field the run gets wrong) or a regression report row (a contract field
that changed outside the truth set). Each has a key. The ledger (`LEDGER`) records the keys already diagnosed and
their outcome, so a round diagnoses only new errors. Sub-plan 5-0 seeds it with every mismatch the reports
themselves describe (outcome `known`)."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from .atomic_io import write_atomic
from .contract import last_endings
from .diagnosis_truth import CaseJudgement, Mismatch
from .lifecycle import Tables
from .regression import regression_key

LOOP_DIR = "output/diagnose_unknown_report/loop"
LEDGER = f"{LOOP_DIR}/diagnosed.csv"
LEDGER_COLUMNS = ("key", "kind", "sec_id", "label", "round", "outcome", "report")
KNOWN, NEW_RIGHT, OLD_RIGHT, TRUTH_RIGHT, LIBRARY_RIGHT, PENDING = (
    "known", "new_right", "old_right", "truth_right", "library_right", "pending")
MISMATCH, REGRESSION = "mismatch", "regression"
CONTEXT_COLUMNS = ("tickers", "security_name", "share_class", "issuer_ids", "first_start", "last_end", "intervals",
                   "delist_date", "library_cik", "bucket", "crsp_code", "reason", "last_trade_date_source",
                   "library_last_trade_close", "dlret_method", "delist_filing_form", "delist_filing_accession",
                   "review_flags", "uncertain_reasons")
CASE_COLUMNS = ("case_id", "mode", "sec_id", "ticker", "truth_case_id", "keys", "fields", "side_a", "side_b",
                *CONTEXT_COLUMNS)
CHANGE_COLUMNS = ("case_id", "field", "old", "new", "reason", "report")


def mismatch_key(m: Mismatch) -> str:
    """The ledger key of one truth mismatch."""
    return "|".join(("mis", m.case_id, m.field, m.truth, m.library))


def _write_csv(path: str | Path, columns: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(Path(path), buf.getvalue())


def read_csv(path: str | Path) -> list[dict[str, str]]:
    """A CSV's rows, or [] when the file does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_ledger(path: str | Path) -> list[dict[str, str]]:
    return read_csv(path)


def write_ledger(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _write_csv(path, LEDGER_COLUMNS, rows)


def write_changes(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    """data/diagnosis_truth_changes.csv, rewritten whole (callers pass every old row first)."""
    _write_csv(path, CHANGE_COLUMNS, rows)


def ledger_keys(rows: Sequence[Mapping[str, str]]) -> set[str]:
    return {r["key"] for r in rows}


def settled_keys(rows: Sequence[Mapping[str, str]]) -> set[str]:
    """The regression keys the loop settled as right (the regression report treats them as explained)."""
    return {r["key"] for r in rows if r["outcome"] == NEW_RIGHT}


def seed_rows(judgements: Sequence[CaseJudgement], keys: Collection[str], label: str) -> list[dict[str, str]]:
    """A `known` ledger row for every current mismatch not in `keys`: the reports already describe them, so no
    round diagnoses them again."""
    out = []
    for j in judgements:
        for m in j.mismatches:
            k = mismatch_key(m)
            if k not in keys:
                out.append(dict(key=k, kind=MISMATCH, sec_id=j.case.sec_id, label=label, round="0", outcome=KNOWN,
                                report=j.case.report))
    return out


def context(tables: Tables, sec_id: str) -> dict[str, str]:
    """What a diagnosing agent reads about a security beside the changed fields: its ticker ranges collapsed, its
    last real ending in delistings.csv, and that ending's uncertain reasons (the columns of source.csv)."""
    hist = sorted((r for r in tables.security_history or () if r["sec_id"] == sec_id), key=lambda r: r["start_date"])
    end = last_endings(tables.delistings).get(sec_id) or {}
    reasons = next((r["reason"] for r in tables.uncertain or () if r["kind"] == "ending" and r["sec_id"] == sec_id
                    and r["date"] == end.get("delist_date")), "")
    return {
        "tickers": ";".join(dict.fromkeys(r["ticker"] for r in hist)),
        "security_name": hist[-1]["security_name"] if hist else "",
        "share_class": hist[-1]["share_class"] if hist else "",
        "issuer_ids": ";".join(dict.fromkeys(r["issuer_id"].split(".")[0] for r in hist if r["issuer_id"])),
        "first_start": min((r["start_date"] for r in hist), default=""),
        "last_end": "" if any(not r["end_date"] for r in hist) else max((r["end_date"] for r in hist), default=""),
        "intervals": str(len(hist)),
        "delist_date": end.get("delist_date", ""), "library_cik": end.get("cik", ""), "bucket": end.get("bucket", ""),
        "crsp_code": end.get("crsp_code", ""), "reason": end.get("reason", ""),
        "last_trade_date_source": end.get("last_trade_date_source", ""),
        "library_last_trade_close": end.get("last_trade_close", ""), "dlret_method": end.get("dlret_method", ""),
        "delist_filing_form": end.get("delist_filing_form", ""),
        "delist_filing_accession": end.get("delist_filing_accession", ""),
        "review_flags": end.get("review_flags", ""), "uncertain_reasons": reasons,
    }


def _field_name(r: Mapping[str, str]) -> str:
    if r["table"] == "delistings" and r["field"]:
        return r["field"]
    return f"{r['table']}.{r['field'] if r['table'] != 'delistings' else r['kind']}"


def case_rows(mismatches: Sequence[Mismatch], regressions: Sequence[Mapping[str, str]], tables: Tables, *,
              label: str, round_no: int, truth_sec: Mapping[str, str]) -> list[dict[str, str]]:
    """One case row per security and round. Mode mismatch lists its mismatched truth fields (side_a the truth,
    side_b the library); mode regression lists its report rows (side_a old, side_b new). `truth_sec` maps a truth
    case_id to its sec_id."""
    groups: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
    for m in mismatches:
        groups.setdefault((MISMATCH, m.case_id), []).append((mismatch_key(m), m.field, m.truth, m.library))
    for r in regressions:
        groups.setdefault((REGRESSION, r["sec_id"]), []).append((regression_key(r), _field_name(r), r["old"],
                                                                 r["new"]))
    out = []
    for (mode, key), items in sorted(groups.items(), key=lambda kv: (kv[0][0] != MISMATCH, kv[0][1])):
        sec = truth_sec[key] if mode == MISMATCH else key
        ctx = context(tables, sec)
        ticker = ctx["tickers"].split(";")[-1] if ctx["tickers"] else ""
        out.append({
            "case_id": f"{sec}_{label}-r{round_no}", "mode": mode, "sec_id": sec, "ticker": ticker,
            "truth_case_id": key if mode == MISMATCH else "",
            "keys": json.dumps([i[0] for i in items]), "fields": json.dumps([i[1] for i in items]),
            "side_a": json.dumps([i[2] for i in items]), "side_b": json.dumps([i[3] for i in items]), **ctx})
    return out


def write_cases(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _write_csv(path, CASE_COLUMNS, rows)


def rename_truth(rows: Sequence[Mapping[str, str]],
                 id_changes: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Truth rows whose placeholder sec_id now holds a FIGI (contract/id_changes.csv) take the new sec_id; the
    case_id stays. Returns the rows and one change-log entry per rename."""
    new_id = {r["old_sec_id"]: r["new_sec_id"] for r in id_changes if r.get("new_sec_id")}
    out, changes = [], []
    for r in rows:
        r = dict(r)
        if r["sec_id"] in new_id:
            changes.append(dict(case_id=r["case_id"], field="sec_id", old=r["sec_id"], new=new_id[r["sec_id"]],
                                reason="contract/id_changes.csv: the placeholder now holds a FIGI", report=""))
            r["sec_id"] = new_id[r["sec_id"]]
        out.append(r)
    return out, changes
```

- [ ] **Step 4: Write the round script**

`scripts/truth_loop_round.py`:

```python
"""One diagnosis-loop round's error list, or the ledger's seed (spec 2026-10-03-diagnosis-truth-fixes, 1.7).

  python scripts/truth_loop_round.py --label 5a --base <commit> --round 1
  python scripts/truth_loop_round.py --label 5-0 --seed-ledger

A round does five things:
1. It renames truth rows whose placeholder now holds a FIGI (contract/id_changes.csv).
2. It judges the run under --output-dir against the truth file.
3. It writes output/regression_report.csv against --base.
4. It keeps the errors the ledger has not seen.
5. It writes them as case rows to output/diagnose_unknown_report/loop/<label>/round-<N>/cases.csv.

It prints one JSON line with the counts, the cases and the path. --seed-ledger records every current mismatch as
`known` (the reports already describe them). Offline (git only). Exit 2: a missing or unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection.diagnosis_truth import (COLUMNS, LibraryRows, judge_all, load_legs, parse_rows,
                                              write_diagnosis_truth)
from delist_detection.lifecycle import Tables
from delist_detection.regression import (RegressionInputError, diff_contract, excluded, read_snapshot,
                                         regression_key, snapshot_at, write_report)
from delist_detection.truth import TruthFileError

ROOT = Path(__file__).resolve().parents[1]


def _legs_rows(out_dir: Path):
    path = out_dir / "contract" / "payout_legs.csv"
    return dl.read_csv(path) if path.exists() else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True, help="the sub-plan, e.g. 5a")
    p.add_argument("--base", help="the commit the sub-plan started from (not needed with --seed-ledger)")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--seed-ledger", action="store_true")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, default=ROOT / "data" / "diagnosis_truth.csv")
    p.add_argument("--legs", type=Path, default=ROOT / "data" / "diagnosis_truth_legs.csv")
    p.add_argument("--changes", type=Path, default=ROOT / "data" / "diagnosis_truth_changes.csv")
    p.add_argument("--loop-dir", type=Path, default=ROOT / dl.LOOP_DIR)
    args = p.parse_args(argv)
    if not args.seed_ledger and not args.base:
        p.error("--base is required for a round")
    ledger_path = args.loop_dir / "diagnosed.csv"
    try:
        truth_rows = dl.read_csv(args.truth)
        id_changes = dl.read_csv(args.output_dir / "contract" / "id_changes.csv")
        truth_rows, renames = dl.rename_truth(truth_rows, id_changes)
        legs = load_legs(args.legs) if args.legs.exists() else {}
        cases = parse_rows(truth_rows, str(args.truth), legs)
        tables = Tables.read(args.output_dir)
        judged = judge_all(cases, LibraryRows.of(tables, _legs_rows(args.output_dir)))
        ledger = dl.read_ledger(ledger_path)
    except (TruthFileError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    if renames:
        write_diagnosis_truth(args.truth, [{c: r[c] for c in COLUMNS} for r in truth_rows])
        dl.write_changes(args.changes, dl.read_csv(args.changes) + renames)
    keys = dl.ledger_keys(ledger)
    if args.seed_ledger:
        seeded = dl.seed_rows(judged, keys, args.label)
        dl.write_ledger(ledger_path, ledger + seeded)
        print(json.dumps({"label": args.label, "seeded": len(seeded), "ledger": str(ledger_path)}))
        return 0
    try:
        base, new = snapshot_at(args.repo, args.base, args.output_dir), read_snapshot(args.output_dir)
    except RegressionInputError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    report = diff_contract(base, new, excluded(cases, base.delistings, new.delistings))
    write_report(args.output_dir / "regression_report.csv", report)
    mismatches = [m for j in judged for m in j.mismatches if dl.mismatch_key(m) not in keys]
    regressions = [r for r in report if regression_key(r) not in keys]
    rows = dl.case_rows(mismatches, regressions, tables, label=args.label, round_no=args.round,
                        truth_sec={c.case_id: c.sec_id for c in cases})
    path = args.loop_dir / args.label / f"round-{args.round}" / "cases.csv"
    dl.write_cases(path, rows)
    print(json.dumps({"label": args.label, "round": args.round, "mismatches_new": len(mismatches),
                      "regressions_new": len(regressions), "renamed": len(renames),
                      "cases": [{"case_id": r["case_id"], "mode": r["mode"], "ticker": r["ticker"]} for r in rows],
                      "path": str(path)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Add D.unexplained_regressions to the scorecard script**

In `scripts/scorecard.py`, add the imports:

```python
from delist_detection.diagnosis_loop import LEDGER, read_csv, settled_keys
from delist_detection.regression import unexplained
```

After `card["drops"] = drops(card, config.floor)`, add:

```python
    report = args.output_dir / "regression_report.csv"
    if report.exists():
        left = unexplained(read_csv(report), config.diagnosis, settled_keys(read_csv(ROOT / LEDGER)))
        card["metrics"]["D.unexplained_regressions"] = len({r["sec_id"] for r in left})
```

Change the final check to:

```python
    if args.check and (card["drops"] or card["golden_failures"] or card["diagnosis_failures"]
                       or card["metrics"].get("D.unexplained_regressions", 0) > 0):
        return 1
```

Append to `tests/test_scorecard_script.py`:

```python
def test_check_fails_while_a_regression_is_unexplained(tmp_path, out, capsys):
    (out / "regression_report.csv").write_text("sec_id,table,field,kind,old,new\nZ,delistings,exit_kind,changed,"
                                               "merger,exchange\n")
    cfg = _config(tmp_path, {})
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--check"]) == 1
    assert "D.unexplained_regressions" in capsys.readouterr().out
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_diagnosis_loop.py tests/test_scorecard_script.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/delist_detection/diagnosis_loop.py scripts/truth_loop_round.py scripts/scorecard.py tests/test_diagnosis_loop.py tests/test_scorecard_script.py
git commit -m "Diagnosis loop: ledger, error keys, case rows, round script; unexplained regressions gate --check (sub-plan 5-0)"
```

---

### Task 6: The truth update rules

**Files:**
- Create: `src/delist_detection/truth_update.py`
- Create: `scripts/update_truth.py`
- Test: `tests/test_truth_update.py`

**Interfaces:**
- Consumes:
  - Task 1's `COLUMNS`, `SCORED`, statuses, `REGRESSION_PENDING`, `ENDING` and `NO_ENDING`.
  - Task 5's outcomes, `MISMATCH`, `REGRESSION`, `read_csv`, `write_ledger`, `write_changes`, `LOOP_DIR` and
    `read_ledger`.
  - Task 4's `snapshot_at` and `read_snapshot`.
- Produces:
  - `@dataclass RoundResult(truth_rows, changes, ledger_rows, pending)`.
  - `apply_round(cases, records, truth_rows, base_contract, new_contract, *, label, round_no, report_dir, ledger_keys=frozenset()) -> RoundResult`.
  - `flip_statuses(rows, matching) -> list[dict]`: the change-log rows for known_wrong cases that now match. It
    edits the rows in place.
  - Loop record fields: `mode` (`regression` or `mismatch`) and `field_verdicts`, a list of
    `{"field", "right", "value", "missed_filing"}`. `right` is one of `old`, `new`, `truth`, `library` or
    `neither`.
  - Script: `python scripts/update_truth.py --label L --round N --base REV [--dry-run]` prints one JSON line of
    counts.

- [ ] **Step 1: Write the failing tests**

`tests/test_truth_update.py`:

```python
"""truth_update: what a round's diagnoses may change in the truth file (spec 1.6)."""
import json

from delist_detection import truth_update as tu
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row


def _case(case_id, mode, sec, fields, a, b, truth_case_id="", keys=None):
    return {"case_id": case_id, "mode": mode, "sec_id": sec, "ticker": sec, "truth_case_id": truth_case_id,
            "keys": json.dumps(keys or [f"k-{case_id}-{f}" for f in fields]), "fields": json.dumps(fields),
            "side_a": json.dumps(a), "side_b": json.dumps(b)}


def _record(verdicts, confidence="verified", upheld=True, refuted=()):
    return {"confidence": confidence, "field_verdicts": verdicts,
            "verification": {"upheld": upheld, "fields_refuted": list(refuted), "fields_upheld": [], "notes": ""}}


def _apply(cases, records, truth=(), base=None, new=None, keys=frozenset()):
    return tu.apply_round(cases, records, list(truth), base or {}, new or {}, label="5a", round_no=1,
                          report_dir="loop/5a/round-1/reports", ledger_keys=keys)


BASE = {"Z": contract_row("Z", exit_kind="merger", last_trade_date="2010-09-30", value_rule="cash")}
NEW = {"Z": contract_row("Z", exit_kind="merger", last_trade_date="2010-10-01", value_rule="cash")}
REG = _case("Z_5a-r1", "regression", "Z", ["last_trade_date"], ["2010-09-30"], ["2010-10-01"])


def test_a_verified_upheld_new_value_enters_the_truth_as_pass():
    res = _apply([REG], {"Z_5a-r1": _record([{"field": "last_trade_date", "right": "new", "value": "2010-10-01",
                                               "missed_filing": ""}])}, base=BASE, new=NEW)
    [row] = res.truth_rows
    assert (row["case_id"], row["status"], row["last_trade_date"], row["exit_kind"]) == (
        "Z_5a-r1", "pass", "2010-10-01", "merger")
    assert [r["outcome"] for r in res.ledger_rows] == ["new_right"] and res.changes[0]["field"] == "(row)"


def test_an_old_value_enters_as_known_wrong_for_the_sub_plan():
    res = _apply([REG], {"Z_5a-r1": _record([{"field": "last_trade_date", "right": "old", "value": "2010-09-30",
                                               "missed_filing": ""}])}, base=BASE, new=NEW)
    [row] = res.truth_rows
    assert (row["status"], row["fixed_by"], row["last_trade_date"]) == ("known_wrong", "5a", "2010-09-30")
    assert [r["outcome"] for r in res.ledger_rows] == ["old_right"]


def test_an_unverified_or_refuted_regression_is_ruling_pending():
    for rec in (_record([{"field": "last_trade_date", "right": "new", "value": "", "missed_filing": ""}],
                        confidence="inferred"),
                _record([{"field": "last_trade_date", "right": "new", "value": "", "missed_filing": ""}],
                        upheld=False, refuted=[{"field": "last_trade_date", "why": "x"}])):
        res = _apply([REG], {"Z_5a-r1": rec}, base=BASE, new=NEW)
        [row] = res.truth_rows
        assert (row["status"], row["fixed_by"], row["exit_kind"]) == ("ruling_pending", "regression", "*")
        assert [r["outcome"] for r in res.ledger_rows] == ["pending"]


def test_a_new_contract_row_the_diagnosis_rejects_becomes_no_ending():
    case = _case("N_5a-r1", "regression", "N", ["delistings.added"], [""], ["exit_kind=exchange"])
    res = _apply([case], {"N_5a-r1": _record([{"field": "delistings.added", "right": "old", "value": "",
                                               "missed_filing": ""}])},
                 new={"N": contract_row("N", exit_kind="exchange")})
    assert (res.truth_rows[0]["shape"], res.truth_rows[0]["status"]) == ("no_ending", "known_wrong")


def test_a_ticker_range_change_enters_only_the_ledger():
    case = _case("Y_5a-r1", "regression", "Y", ["security_history.ranges"], ["a"], ["b"])
    res = _apply([case], {"Y_5a-r1": _record([{"field": "security_history.ranges", "right": "new", "value": "b",
                                               "missed_filing": ""}])})
    assert res.truth_rows == [] and [r["outcome"] for r in res.ledger_rows] == ["new_right"]


def test_a_mismatch_changes_the_truth_only_with_a_missed_filing():
    truth = [truth_row("A_2010-01-04", "A", status="known_wrong", fixed_by="5d", last_trade_date="2010-01-01")]
    case = _case("A_5a-r1", "mismatch", "A", ["last_trade_date"], ["2010-01-01"], ["2010-01-02"],
                 truth_case_id="A_2010-01-04")
    without = _apply([case], {"A_5a-r1": _record([{"field": "last_trade_date", "right": "library",
                                                   "value": "2010-01-02", "missed_filing": ""}])}, truth)
    assert without.truth_rows[0]["last_trade_date"] == "2010-01-01" and without.changes == []
    assert [r["outcome"] for r in without.ledger_rows] == ["pending"]
    cited = _apply([case], {"A_5a-r1": _record([{"field": "last_trade_date", "right": "library",
                                                 "value": "2010-01-02", "missed_filing": "0001193125-10-222185"}])},
                   truth)
    assert cited.truth_rows[0]["last_trade_date"] == "2010-01-02"
    assert cited.changes[0]["reason"].endswith("cites 0001193125-10-222185")
    assert [r["outcome"] for r in cited.ledger_rows] == ["library_right"]


def test_a_mismatch_the_diagnosis_upholds_keeps_the_truth():
    truth = [truth_row("A_2010-01-04", "A", last_trade_date="2010-01-01")]
    case = _case("A_5a-r1", "mismatch", "A", ["last_trade_date"], ["2010-01-01"], ["2010-01-02"],
                 truth_case_id="A_2010-01-04")
    res = _apply([case], {"A_5a-r1": _record([{"field": "last_trade_date", "right": "truth", "value": "2010-01-01",
                                               "missed_filing": ""}])}, truth)
    assert res.changes == [] and [r["outcome"] for r in res.ledger_rows] == ["truth_right"]


def test_a_case_with_no_record_changes_nothing_and_is_retried():
    res = _apply([REG], {}, base=BASE, new=NEW)
    assert res.truth_rows == [] and res.ledger_rows == [] and res.pending == ["Z_5a-r1"]


def test_rerunning_a_round_skips_settled_keys():
    rec = {"Z_5a-r1": _record([{"field": "last_trade_date", "right": "new", "value": "", "missed_filing": ""}])}
    first = _apply([REG], rec, base=BASE, new=NEW)
    again = _apply([REG], rec, truth=first.truth_rows, base=BASE, new=NEW,
                   keys={r["key"] for r in first.ledger_rows})
    assert again.truth_rows == first.truth_rows and again.changes == [] and again.ledger_rows == []


def test_flip_statuses_turns_matching_known_wrong_cases_into_pass():
    rows = [truth_row("A_2010-01-04", "A", status="known_wrong", fixed_by="5a"),
            truth_row("B_2010-01-04", "B", status="known_wrong", fixed_by="5a")]
    changes = tu.flip_statuses(rows, {"A_2010-01-04"})
    assert [(r["status"], r["fixed_by"]) for r in rows] == [("pass", ""), ("known_wrong", "5a")]
    assert [(c["case_id"], c["old"], c["new"]) for c in changes] == [("A_2010-01-04", "known_wrong", "pass")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_truth_update.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'delist_detection.truth_update'`.

- [ ] **Step 3: Write the module**

`src/delist_detection/truth_update.py`:

```python
"""Apply one loop round's diagnoses to the diagnosis truth file (spec 2026-10-03-diagnosis-truth-fixes, section
1.6), so the truth never drifts toward whatever the library now outputs.

- A regressed row outside the truth set enters the truth file when its diagnosis is verified and the skeptic
  upheld it. It takes the side the diagnosis found right, field by field. All new values give `pass`. Any old value
  gives `known_wrong`, with `fixed_by` the round's sub-plan, because the rule must be narrowed. A change that
  touches no scored field (a ticker range, a placeholder rename, dlret) enters only the ledger. A record that is
  not verified, or that the skeptic refuted, adds the row as `ruling_pending` with `fixed_by` `regression`; it
  counts as unexplained until the operator settles it.
- A mismatched truth field changes only when the diagnosis is verified and upheld, finds the library's value right,
  and names a filing the earlier report missed or misread (`missed_filing`). A verdict about the shape, the ending
  or a leg sends the case to `ruling_pending` instead: the operator rewrites such rows.
- A case with no record (the agent failed) changes nothing and leaves no ledger row, so the next round retries it.
- `flip_statuses` turns a known_wrong case that now matches into `pass`.

Every truth change is a change-log row, and every settled error a ledger row. Loop records carry `mode` and
`field_verdicts`: [{"field", "right": old | new | truth | library | neither, "value", "missed_filing"}]."""
from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from .diagnosis_loop import LIBRARY_RIGHT, MISMATCH, NEW_RIGHT, OLD_RIGHT, PENDING, REGRESSION, TRUTH_RIGHT
from .diagnosis_truth import (COLUMNS, ENDING, KNOWN_WRONG, NO_ENDING, NOT_SCORED, PASS, REGRESSION_PENDING,
                              RULING_PENDING, SCORED)

OLD, NEW, TRUTH, LIBRARY = "old", "new", "truth", "library"
WHOLE_ROW = ("delistings.added", "delistings.removed")


@dataclass
class RoundResult:
    truth_rows: list[dict[str, str]]
    changes: list[dict[str, str]]
    ledger_rows: list[dict[str, str]]
    pending: list[str]


def _usable(rec: Mapping) -> bool:
    v = rec.get("verification") or {}
    return rec.get("confidence") == "verified" and bool(v.get("upheld")) and not v.get("fields_refuted")


def _change(case_id: str, name: str, old: str, new: str, reason: str, report: str) -> dict[str, str]:
    return dict(case_id=case_id, field=name, old=old, new=new, reason=reason, report=report)


def _ledger(key: str, kind: str, sec: str, label: str, round_no: int, outcome: str, report: str) -> dict[str, str]:
    return dict(key=key, kind=kind, sec_id=sec, label=label, round=str(round_no), outcome=outcome, report=report)


def _blank(case_id: str, sec: str, ticker: str) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    row.update(case_id=case_id, sec_id=sec, ticker=ticker, shape=ENDING)
    return row


def _regression_row(case: Mapping[str, str], right: Mapping[str, str], fields: Sequence[str], old: Sequence[str],
                    new: Sequence[str], base_row: Mapping[str, str] | None,
                    new_row: Mapping[str, str] | None) -> dict[str, str]:
    row = _blank(case["case_id"], case["sec_id"], case["ticker"])
    whole = next((f for f in fields if f in WHOLE_ROW), None)
    if whole is not None:
        side = new_row if right[whole] == NEW else base_row
        row["shape"] = ENDING if side else NO_ENDING
        row.update({f: (side or {}).get(f, "") for f in SCORED})
        return row
    row.update({f: (new_row or base_row or {}).get(f, "") for f in SCORED})
    for f, o, n in zip(fields, old, new):
        if f in SCORED:
            row[f] = n if right[f] == NEW else o
    return row


def apply_round(cases: Sequence[Mapping[str, str]], records: Mapping[str, Mapping],
                truth_rows: Sequence[Mapping[str, str]], base_contract: Mapping[str, Mapping[str, str]],
                new_contract: Mapping[str, Mapping[str, str]], *, label: str, round_no: int, report_dir: str,
                ledger_keys: Collection[str] = frozenset()) -> RoundResult:
    rows = [dict(r) for r in truth_rows]
    by_case = {r["case_id"]: r for r in rows}
    in_truth = {r["sec_id"] for r in rows}
    changes: list[dict[str, str]] = []
    ledger: list[dict[str, str]] = []
    pending: list[str] = []
    for case in cases:
        keys, fields, a, b = (json.loads(case[c]) for c in ("keys", "fields", "side_a", "side_b"))
        if all(k in ledger_keys for k in keys):
            continue
        rec = records.get(case["case_id"])
        if rec is None:
            pending.append(case["case_id"])
            continue
        report = f"{report_dir}/{case['case_id']}.md"
        verdicts = {v["field"]: v for v in rec.get("field_verdicts") or []}
        usable = _usable(rec)
        sec = case["sec_id"]
        if case["mode"] == REGRESSION:
            right = {f: (verdicts.get(f) or {}).get("right", "") for f in fields}
            ok = usable and all(right[f] in (OLD, NEW) for f in fields)
            for f, k in zip(fields, keys):
                outcome = (NEW_RIGHT if right[f] == NEW else OLD_RIGHT) if ok else PENDING
                ledger.append(_ledger(k, REGRESSION, sec, label, round_no, outcome, report))
            if sec in in_truth or not any(f in SCORED or f in WHOLE_ROW for f in fields):
                continue
            if ok:
                row = _regression_row(case, right, fields, a, b, base_contract.get(sec), new_contract.get(sec))
                all_new = all(right[f] == NEW for f in fields)
                row.update(status=PASS if all_new else KNOWN_WRONG, fixed_by="" if all_new else label,
                           confidence=rec.get("confidence", ""), skeptic="upheld",
                           note=f"added by the {label} loop: regression of {', '.join(fields)}")
            else:
                row = _blank(case["case_id"], sec, case["ticker"])
                row.update({f: NOT_SCORED for f in SCORED}, status=RULING_PENDING, fixed_by=REGRESSION_PENDING,
                           confidence=rec.get("confidence", ""),
                           skeptic="upheld" if (rec.get("verification") or {}).get("upheld") else "refuted",
                           note=f"regression of {', '.join(fields)} not settled by the {label} loop")
            row["report"] = report
            rows.append(row)
            in_truth.add(sec)
            changes.append(_change(row["case_id"], "(row)", "", f"added ({row['status']})",
                                   f"{label} loop round {round_no}: regression", report))
        else:
            truth = by_case[case["truth_case_id"]]
            for f, k, t, lib in zip(fields, keys, a, b):
                v = verdicts.get(f) or {}
                if usable and v.get("right") == LIBRARY and v.get("missed_filing"):
                    outcome = LIBRARY_RIGHT
                    if f in SCORED or f == "internal_last_trade_date":
                        changes.append(_change(truth["case_id"], f, truth[f], lib,
                                               f"diagnosis {case['case_id']} cites {v['missed_filing']}", report))
                        truth[f] = lib
                    else:
                        changes.append(_change(truth["case_id"], "status", truth["status"], RULING_PENDING,
                                               f"diagnosis {case['case_id']} found the library's {f} right", report))
                        truth.update(status=RULING_PENDING, fixed_by="",
                                     note=f"{truth['note']}; {f}: the library is right per {case['case_id']}")
                elif usable and v.get("right") == TRUTH:
                    outcome = TRUTH_RIGHT
                else:
                    outcome = PENDING
                ledger.append(_ledger(k, MISMATCH, sec, label, round_no, outcome, report))
    return RoundResult(rows, changes, ledger, pending)


def flip_statuses(rows: Sequence[dict[str, str]], matching: Collection[str]) -> list[dict[str, str]]:
    """Every known_wrong row whose case now matches becomes pass (in place); returns the change-log rows."""
    out = []
    for r in rows:
        if r["status"] == KNOWN_WRONG and r["case_id"] in matching:
            out.append(_change(r["case_id"], "status", KNOWN_WRONG, PASS, "the library now matches", ""))
            r["status"], r["fixed_by"] = PASS, ""
    return out
```

- [ ] **Step 4: Write the script**

`scripts/update_truth.py`:

```python
"""Apply one diagnosis-loop round to data/diagnosis_truth.csv (spec 2026-10-03-diagnosis-truth-fixes, 1.6).

  python scripts/update_truth.py --label 5a --round 1 --base <commit>
  python scripts/update_truth.py --label pilot --round 1 --base HEAD --dry-run   # print the outcome, write nothing

It reads:
- output/diagnose_unknown_report/loop/<label>/round-<N>/cases.csv, and the records/*.json beside it;
- the truth file and its legs;
- the contract at --base and under --output-dir.

It writes the truth file, appends data/diagnosis_truth_changes.csv and the ledger, and writes the round's
summary.md. It prints one JSON line of counts. Offline (git only). Exit 2: a missing or unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection.diagnosis_truth import (COLUMNS, LibraryRows, judge_all, load_legs, parse_rows,
                                              write_diagnosis_truth)
from delist_detection.lifecycle import Tables
from delist_detection.regression import RegressionInputError, read_snapshot, snapshot_at
from delist_detection.truth import TruthFileError
from delist_detection.truth_update import apply_round, flip_statuses

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--truth", type=Path, default=ROOT / "data" / "diagnosis_truth.csv")
    p.add_argument("--legs", type=Path, default=ROOT / "data" / "diagnosis_truth_legs.csv")
    p.add_argument("--changes", type=Path, default=ROOT / "data" / "diagnosis_truth_changes.csv")
    p.add_argument("--loop-dir", type=Path, default=ROOT / dl.LOOP_DIR)
    args = p.parse_args(argv)
    round_dir = args.loop_dir / args.label / f"round-{args.round}"
    try:
        cases = dl.read_csv(round_dir / "cases.csv")
        if not (round_dir / "cases.csv").exists():
            raise ValueError(f"{round_dir / 'cases.csv'}: missing")
        records = {f.stem: json.loads(f.read_text()) for f in sorted((round_dir / "records").glob("*.json"))}
        truth_rows = dl.read_csv(args.truth)
        legs = load_legs(args.legs) if args.legs.exists() else {}
        base, new = snapshot_at(args.repo, args.base, args.output_dir), read_snapshot(args.output_dir)
        ledger = dl.read_ledger(args.loop_dir / "diagnosed.csv")
        tables = Tables.read(args.output_dir)
    except (RegressionInputError, TruthFileError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    rel_reports = (round_dir / "reports").relative_to(args.repo).as_posix() if round_dir.is_relative_to(args.repo) \
        else str(round_dir / "reports")
    res = apply_round(cases, records, truth_rows, {r["sec_id"]: r for r in base.delistings},
                      {r["sec_id"]: r for r in new.delistings}, label=args.label, round_no=args.round,
                      report_dir=rel_reports, ledger_keys=dl.ledger_keys(ledger))
    judged = judge_all(parse_rows(res.truth_rows, "updated truth", legs), LibraryRows.of(tables))
    res.changes += flip_statuses(res.truth_rows, {j.case.case_id for j in judged if j.ok})
    summary = {"label": args.label, "round": args.round, "cases": len(cases), "records": len(records),
               "truth_changes": len(res.changes), "ledger_rows": len(res.ledger_rows), "retry": res.pending,
               "dry_run": args.dry_run}
    if not args.dry_run:
        write_diagnosis_truth(args.truth, [{c: r[c] for c in COLUMNS} for r in res.truth_rows])
        dl.write_changes(args.changes, dl.read_csv(args.changes) + res.changes)
        dl.write_ledger(args.loop_dir / "diagnosed.csv", ledger + res.ledger_rows)
        lines = [f"# Loop {args.label}, round {args.round}", "", f"- cases: {len(cases)}, records: {len(records)}",
                 f"- truth changes: {len(res.changes)}", f"- retried next round (no record): {res.pending or 'none'}",
                 "", "| case | field | old | new | reason |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {c['case_id']} | {c['field']} | {c['old']} | {c['new']} | {c['reason']} |" for c in res.changes]
        (round_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_truth_update.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/truth_update.py scripts/update_truth.py tests/test_truth_update.py
git commit -m "Truth updates: the spec's rules for what a round's diagnoses may change (sub-plan 5-0)"
```

---

### Task 7: The skill's normalization rules, its loop modes, and the two workflows

**Files:**
- Create: `.claude/skills/diagnose-delisting/truth-rules.md` (Write tool)
- Modify: `.claude/skills/diagnose-delisting/SKILL.md` (Edit tool: a "Modes" section)
- Create: `.claude/workflows/diagnosis-truth-normalize.js` (Write tool)
- Create: `.claude/workflows/diagnosis-truth-loop.js` (Write tool)

**Interfaces:**
- Consumes:
  - Task 5's case row columns (`CASE_COLUMNS`) and the round script's JSON line.
  - Task 6's loop record fields (`mode`, `field_verdicts`) and the update script's JSON line.
  - Task 8's normalized row JSON, written by the agents.
- Produces:
  - **Normalized truth rows.** `output/diagnose_unknown_report/truth_rows/<case_id>.json`:
    `{case_id, sec_id, shape, fields: {<every SCORED field>: str}, internal_last_trade_date, legs: [{leg, ratio, price_sec_id, price_ticker, price_date}], identity_check: {old_cusip, new_cusip} | null, residual: str, pending: [{field, question}], notes}`.
  - **Loop reports and records.** `output/diagnose_unknown_report/loop/<label>/round-<N>/reports/<case_id>.md` and
    `.../records/<case_id>.json`.
  - **Workflow `diagnosis-truth-normalize`.** args `{cases: [case_id...], batch: 10}`.
  - **Workflow `diagnosis-truth-loop`.** args `{label, base, maxRounds: 3, dryRun: false, casesPath: ""}`. With
    `casesPath` it runs one diagnose and verify pass on a prepared cases.csv: no round script, and the update runs
    with `--dry-run`.

These files are agent instructions and JavaScript run by the harness. They have no unit tests; Task 9 and Task 10
pilot them on real cases before full runs.

- [ ] **Step 1: Write the normalization rules**

`.claude/skills/diagnose-delisting/truth-rules.md`:

````markdown
# Truth rules: one report into one truth row

You turn one diagnosis report into the row the contract should publish for that security (spec
`docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md`, sections 1.1 and 2). The report is the evidence;
you do not re-diagnose. Read the whole report, including section 9 (the skeptic): a field the skeptic refuted takes
the skeptic's correction, never the report's section 3.

## Output

One JSON file, `output/diagnose_unknown_report/truth_rows/<case_id>.json`:

```json
{"case_id": "...", "sec_id": "...", "shape": "ending | no_ending | ending_moved",
 "fields": {"exit_kind": "", "drop_reason": "", "continuation": "", "successor_sec_id": "", "last_trade_date": "",
            "value_rule": "", "cash_per_share": "", "cash_currency": "", "stock_ratio": "", "price_sec_id": "",
            "price_ticker": "", "price_date": "", "recovery_ratio": ""},
 "internal_last_trade_date": "",
 "legs": [],
 "identity_check": null,
 "residual": "",
 "pending": [],
 "notes": "one line: what the row rests on"}
```

Every field is a string. `""` means the contract must publish a blank; `"*"` means the report leaves it open (not
scored). Use `*` sparingly: a field the report settles gets its value.

## Shape

- `ending`: the security ended here (or later, at an ending the report fully states): one contract row.
- `no_ending`: the security did not end: a rename or ticker change of the same security, a reverse split that kept
  the line (ruling R2 below), a same-FIGI successor (CCO, GTES), a line still trading.
- `ending_moved`: this ending is not real, but the line ended later (JNY's 2014 merger after a 2010 rename). Fill the
  fields only where the report states the later ending; else `*`.

## Fields, as the contract publishes them

- `exit_kind`: merger | exchange | liquidation | dropped | lost_source | expiration; blank for unknown.
- `drop_reason`: on a `dropped` row only: moved_otc | price | capital | went_private | bankruptcy | filings_fees |
  guidelines | sec_order; else blank.
- `continuation`: "true" or "false". When true: `successor_sec_id` is the successor line's sec_id in the run (look
  it up in `output/securities.csv` / `output/ticker_history.csv`; `*` when the run does not hold it yet),
  `value_rule` is `continuation`, and every value field is blank.
- `last_trade_date`: published only when the corrected date rests on an exchange print or a filing's statement about
  trading: MIDAS, a Nasdaq halt, the Form 25 EX-99.25 notice, an 8-K / 8-K12B / 6-K or filed press release that says
  when trading stopped or was suspended ("suspended before the open on D" is the trading day before D; "after the
  close on D" is D), and no later than the Form 25 effective date. A date worked out from a merger effective date or
  closing date alone, from fails rows, from a last sighting or from the web is NOT published: write `""` here and put
  the date in `internal_last_trade_date`. No last trade at all (a continuing line): `""` and no internal date.
- `value_rule`: cash | stock | cash_plus_stock | otc_print | recovery | worthless | transfer | continuation |
  expiration | unknown | basket. Then:
  - cash: `cash_per_share`, `cash_currency` (USD when the filing says "$"; CAD for "C$"; blank if not stated).
  - stock: `stock_ratio`, `price_sec_id` (the acquirer's line in the run, or `*`), `price_ticker` (the acquirer's
    symbol on the price date, as a filing states it), `price_date`.
  - cash_plus_stock: both sets.
  - otc_print (decision 11): `price_sec_id` = the security's own sec_id, `price_ticker` = its own OTC symbol if the
    report knows it, else `*`; `price_date`.
  - recovery: `recovery_ratio`. worthless, transfer, expiration, unknown, continuation: every value field blank.
  - basket (ruling R3: two lines per share, a spin-off leg, a one-to-many reclassification): the cash leg, if any, in
    `cash_per_share`/`cash_currency`; each stock leg in `legs` as {"leg": 1, "ratio", "price_sec_id",
    "price_ticker", "price_date"}; `stock_ratio`, `price_*` blank on the main row.
- `price_date`: the trading day after the published `last_trade_date`; blank when `last_trade_date` is blank.
- Numbers as plain decimals ("1.05", "65.50"); dates YYYY-MM-DD.

## Rulings (spec section 2)

- R1: continuation only when the old holders get exactly one new share per old share and no cash in the exchange,
  even when other holders join (BHI) or the class or issuer changes; any other ratio or cash in the exchange is a
  stock or cash_plus_stock merger.
- R2: a CUSIP or ticker change of one issuer and class (reverse split, rename): write the shape as if it is one
  security (`no_ending` or `ending_moved`) and fill `identity_check` with {"old_cusip", "new_cusip"} from the report;
  the build script checks the FIGI and turns it into a continuation when the new CUSIP has its own composite.
- R4: an election deal publishes the final prorated package a filing states, else the default package; never the sum
  of the elections; a CVR goes in `notes`.
- R5: a non-USD cash leg keeps its currency, unconverted.
- R6: a bankruptcy plan exchanging old equity for new shares is `stock` on the new line when the old line did not
  trade OTC first; `otc_print` when it did.
- R7: EXE (one FIGI over pre- and post-bankruptcy stock): set `residual` to the reason.
- BHI rule: a dividend the successor pays after the exchange is not consideration; cash the deal documents make part
  of the consideration is.

## When you cannot settle a field

Add {"field": "<name>", "question": "<what would settle it>"} to `pending` and write `*` in that field. Set
`residual` (a short reason) when the library cannot reach the right value with any general rule (data it does not
have, such as an OTC ADS with no price source). Never guess.
````

- [ ] **Step 2: Add the loop modes to the skill**

In `.claude/skills/diagnose-delisting/SKILL.md`, insert a section before `## Rules` (find the line `## Rules`
with the Edit tool and insert above it):

````markdown
## Modes (the diagnosis truth loop)

Besides the uncertain rows of `source.csv` (mode `uncertain`, steps 1–5 above), the truth loop (spec
`docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md`, 1.5) sends two other kinds of case. Its case
row is in `output/diagnose_unknown_report/loop/<label>/round-<N>/cases.csv`: `mode`, `sec_id`, `ticker`,
`truth_case_id`, and three JSON lists of the same length: `fields`, `side_a`, `side_b`, plus the context columns of
`source.csv`.

- `regression`: a contract field changed for a security outside the truth set; `side_a` is the old value (the
  sub-plan's base run), `side_b` the new one. Decide, field by field, which one the filings support. A field named
  `delistings.added` / `delistings.removed` means the whole contract row appeared or disappeared;
  `security_history.ranges` compares the ticker ranges.
- `mismatch`: the library disagrees with the truth file; `side_a` is the truth, `side_b` the library. The truth came
  from an earlier report (`truth_case_id`'s report under `output/diagnose_unknown_report/reports/`): read it first.
  Decide, field by field, which value the filings support. If the library is right, name the filing the earlier
  report missed or misread (its accession number) in `missed_filing`; without one, the truth will not change.

Write the report and the record under the round's folder (`reports/<case_id>.md`, `records/<case_id>.json`), not
under `output/diagnose_unknown_report/reports/`. Section 2 of the report shows both values and the evidence for
each field. The record has every key of the uncertain-mode record, plus:

```json
"mode": "regression | mismatch",
"field_verdicts": [{"field": "<as in fields>", "right": "old | new | truth | library | neither",
                    "value": "<the right value>", "missed_filing": "<accession, mismatch mode only, or empty>"}]
```

`confidence` follows the same rule as in uncertain mode. Every loop record gets a skeptic pass, whatever it decides.
````

- [ ] **Step 3: Write the normalization workflow**

`.claude/workflows/diagnosis-truth-normalize.js`:

```javascript
export const meta = {
  name: 'diagnosis-truth-normalize',
  description: 'Turn diagnosis reports into truth rows (truth-rules.md), a batch of cases per agent, at most 5 agents at a time',
  phases: [
    { title: 'Normalize', detail: 'one agent per batch: read each report, write its truth row JSON' },
    { title: 'Check', detail: 'every case has a row (code, no agent)' },
  ],
}

const FIELD = { type: 'string' }
const ROW = {
  type: 'object',
  properties: {
    case_id: FIELD, sec_id: FIELD, shape: { type: 'string', enum: ['ending', 'no_ending', 'ending_moved'] },
    fields: { type: 'object', properties: Object.fromEntries(['exit_kind', 'drop_reason', 'continuation',
      'successor_sec_id', 'last_trade_date', 'value_rule', 'cash_per_share', 'cash_currency', 'stock_ratio',
      'price_sec_id', 'price_ticker', 'price_date', 'recovery_ratio'].map(f => [f, FIELD])),
      required: ['exit_kind', 'drop_reason', 'continuation', 'successor_sec_id', 'last_trade_date', 'value_rule',
        'cash_per_share', 'cash_currency', 'stock_ratio', 'price_sec_id', 'price_ticker', 'price_date',
        'recovery_ratio'] },
    internal_last_trade_date: FIELD,
    legs: { type: 'array', items: { type: 'object', properties: { leg: { type: 'integer' }, ratio: FIELD,
      price_sec_id: FIELD, price_ticker: FIELD, price_date: FIELD }, required: ['leg', 'ratio'] } },
    identity_check: { type: ['object', 'null'], properties: { old_cusip: FIELD, new_cusip: FIELD } },
    residual: FIELD,
    pending: { type: 'array', items: { type: 'object', properties: { field: FIELD, question: FIELD },
      required: ['field', 'question'] } },
    notes: FIELD,
  },
  required: ['case_id', 'sec_id', 'shape', 'fields', 'internal_last_trade_date', 'legs', 'identity_check',
    'residual', 'pending', 'notes'],
}
const BATCH = { type: 'object', properties: { rows: { type: 'array', items: ROW } }, required: ['rows'] }

const LIMIT = 5
let running = 0
const waiting = []
async function limited(fn) {
  if (running >= LIMIT) await new Promise(resolve => waiting.push(resolve))
  running++
  try { return await fn() } finally { running--; const next = waiting.shift(); if (next) next() }
}

function prompt(ids) {
  return `Turn ${ids.length} diagnosis report(s) of the delist_detection library into truth rows.

Read first, in the repo (your working directory): .claude/skills/diagnose-delisting/truth-rules.md (your
instructions; follow them exactly) and .claude/skills/diagnose-delisting/reference.md (the contract's fields and
the spec's decisions).

Cases: ${ids.join(', ')}.
For each case: read output/diagnose_unknown_report/reports/<case_id>.md (all sections, including 9) and
output/diagnose_unknown_report/records/<case_id>.json. To look up a sec_id, grep output/securities.csv and
output/ticker_history.csv. Do not fetch from SEC or the web: the report is the evidence.

Write one file per case with the Write tool, BEFORE you return:
output/diagnose_unknown_report/truth_rows/<case_id>.json. Then return {"rows": [...]} with the same objects.
Do not edit any other file, run the pipeline, commit or dispatch subagents.`
}

const ids = args.cases
const size = args.batch || 10
const batches = []
for (let i = 0; i < ids.length; i += size) batches.push(ids.slice(i, i + size))
log(`${ids.length} cases in ${batches.length} batches, at most ${LIMIT} agents at a time`)

phase('Normalize')
const results = await parallel(batches.map((b, i) => () => limited(() =>
  agent(prompt(b), { label: `normalize:${i + 1}/${batches.length}`, phase: 'Normalize', schema: BATCH,
    model: 'sonnet' }))))

phase('Check')
const got = new Set(results.filter(Boolean).flatMap(r => r.rows.map(x => x.case_id)))
const missing = ids.filter(id => !got.has(id))
const pending = results.filter(Boolean).flatMap(r => r.rows.filter(x => x.pending.length).map(x => x.case_id))
log(`${got.size}/${ids.length} rows; ${missing.length} missing; ${pending.length} with pending fields`)
return { missing, pending }
```

- [ ] **Step 4: Write the loop workflow**

`.claude/workflows/diagnosis-truth-loop.js`:

```javascript
export const meta = {
  name: 'diagnosis-truth-loop',
  description: 'The diagnosis truth loop of one sub-plan: list new errors, diagnose and verify each, update the truth file; up to 3 rounds, at most 5 agents at a time',
  phases: [
    { title: 'Round', detail: 'list the new errors (script, one agent)' },
    { title: 'Diagnose', detail: 'one agent per case (regression or mismatch mode)' },
    { title: 'Verify', detail: 'a skeptic per case' },
    { title: 'Update', detail: 'apply the outcomes to the truth file (script, one agent)' },
  ],
}

const PY = 'PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python'
const LIMIT = 5
let running = 0
const waiting = []
async function limited(fn) {
  if (running >= LIMIT) await new Promise(resolve => waiting.push(resolve))
  running++
  try { return await fn() } finally { running--; const next = waiting.shift(); if (next) next() }
}

const STATUS = { type: 'string', enum: ['agree', 'wrong', 'missing', 'unknown'] }
const RECORD = {
  type: 'object',
  properties: {
    case_id: { type: 'string' }, sec_id: { type: 'string' }, ticker: { type: 'string' }, report: { type: 'string' },
    mode: { type: 'string', enum: ['regression', 'mismatch'] },
    field_verdicts: { type: 'array', items: { type: 'object', properties: { field: { type: 'string' },
      right: { type: 'string', enum: ['old', 'new', 'truth', 'library', 'neither'] }, value: { type: 'string' },
      missed_filing: { type: 'string' } }, required: ['field', 'right', 'value', 'missed_filing'] } },
    confidence: { type: 'string', enum: ['verified', 'inferred', 'unresolved'] },
    status: { type: 'object', properties: { exit_kind: STATUS, last_trade_date: STATUS, successor: STATUS,
      value_rule: STATUS, terms: STATUS, issuer: STATUS, ticker_history: STATUS } },
    confidence_reasons: { type: 'array', items: { type: 'string' } },
    sec_evidence: { type: 'integer' }, web_evidence: { type: 'integer' }, verdict: { type: 'string' },
  },
  required: ['case_id', 'sec_id', 'mode', 'field_verdicts', 'confidence', 'confidence_reasons', 'sec_evidence',
    'web_evidence', 'verdict'],
}
const VERDICT = {
  type: 'object',
  properties: { case_id: { type: 'string' }, upheld: { type: 'boolean' },
    fields_upheld: { type: 'array', items: { type: 'string' } },
    fields_refuted: { type: 'array', items: { type: 'object', properties: { field: { type: 'string' },
      why: { type: 'string' } }, required: ['field', 'why'] } }, notes: { type: 'string' } },
  required: ['case_id', 'upheld', 'fields_upheld', 'fields_refuted', 'notes'],
}
const ROUND = {
  type: 'object',
  properties: { mismatches_new: { type: 'integer' }, regressions_new: { type: 'integer' },
    cases: { type: 'array', items: { type: 'object', properties: { case_id: { type: 'string' },
      mode: { type: 'string' }, ticker: { type: 'string' } }, required: ['case_id', 'mode'] } },
    path: { type: 'string' } },
  required: ['mismatches_new', 'regressions_new', 'cases', 'path'],
}
const UPDATE = { type: 'object', properties: { output: { type: 'string' } }, required: ['output'] }

function runner(cmd) {
  return `Run exactly this one command from the repo root (your working directory) with the Bash tool, then return
its last output line in the structured answer. Do not edit any file, fix anything or run anything else.

${cmd}`
}

function diagnosePrompt(c, dir) {
  return `Diagnose one ${c.mode} case of the delist_detection truth loop: ${c.case_id} (${c.ticker || 'no ticker'}).

Read first: .claude/skills/diagnose-delisting/SKILL.md (your instructions; its "Modes" section is your mode),
.claude/skills/diagnose-delisting/reference.md and .claude/skills/diagnose-delisting/example-THI.md.

Your case is the row of ${dir}/cases.csv whose case_id is ${c.case_id} (grep '^${c.case_id},' ${dir}/cases.csv;
header: head -1). Write exactly two files with the Write tool BEFORE you return:
${dir}/reports/${c.case_id}.md and ${dir}/records/${c.case_id}.json. Then return the record.

Four other agents share SEC's rate limit through the lock in sec.py; use only sec.py for SEC, with allowed_domains
data.sec.gov, www.sec.gov, efts.sec.gov. Do not edit any other file, run the pipeline, commit or dispatch subagents.`
}

function verifyPrompt(c, r, dir) {
  return `You are a skeptic checking one truth-loop diagnosis: ${dir}/reports/${c.case_id}.md (mode ${c.mode}).
Its field verdicts: ${JSON.stringify(r.field_verdicts)}.

Read the report, .claude/skills/diagnose-delisting/reference.md and the case row (grep '^${c.case_id},'
${dir}/cases.csv). For each field verdict, try to REFUTE it: re-open the cited filings through sec.py (SKILL.md
step 2), check dates, numbers, the security class and the rule. For a "library" verdict in mismatch mode, check that
the named missed_filing really shows the earlier report wrong. A verdict survives only if the evidence supports it.

Append "## 9. Verification" to the report and add a "verification" object (your result) to
${dir}/records/${c.case_id}.json. Edit only those two files. Return the result object.`
}

const label = args.label
const maxRounds = args.maxRounds || 3
const summaries = []
for (let round = 1; round <= maxRounds; round++) {
  const dir = args.casesPath ? args.casesPath.replace(/\/cases\.csv$/, '') :
    `output/diagnose_unknown_report/loop/${label}/round-${round}`
  let listed
  if (args.casesPath) {
    listed = await agent(runner(`${PY} -c "import csv,json; print(json.dumps({'mismatches_new': 0, 'regressions_new': 0, 'path': '${args.casesPath}', 'cases': [{'case_id': r['case_id'], 'mode': r['mode'], 'ticker': r['ticker']} for r in csv.DictReader(open('${args.casesPath}'))]}))"`),
      { label: 'round:prepared', phase: 'Round', schema: ROUND, model: 'sonnet', effort: 'low' })
  } else {
    listed = await agent(runner(`${PY} scripts/truth_loop_round.py --label ${label} --base ${args.base} --round ${round}`),
      { label: `round:${round}`, phase: 'Round', schema: ROUND, model: 'sonnet', effort: 'low' })
  }
  if (!listed || !listed.cases.length) { log(`round ${round}: no new errors`); break }
  log(`round ${round}: ${listed.cases.length} case(s) (${listed.mismatches_new} mismatches, ${listed.regressions_new} regressions)`)
  const done = await pipeline(listed.cases,
    c => limited(() => agent(diagnosePrompt(c, dir), { label: `diagnose:${c.ticker || c.case_id}`,
      phase: 'Diagnose', schema: RECORD, model: 'sonnet' })),
    (r, c) => r ? limited(() => agent(verifyPrompt(c, r, dir), { label: `verify:${c.ticker || c.case_id}`,
      phase: 'Verify', schema: VERDICT, model: 'sonnet' })).then(v => ({ record: r, verification: v })) : null)
  const missing = listed.cases.filter((c, i) => !done[i] || !done[i].verification).map(c => c.case_id)
  if (missing.length) log(`round ${round}: no record or no verification for ${missing.join(', ')} (retried next round)`)
  const dry = (args.dryRun || args.casesPath) ? ' --dry-run' : ''
  const upd = await agent(runner(`${PY} scripts/update_truth.py --label ${label} --round ${round} --base ${args.base}${dry}`),
    { label: `update:${round}`, phase: 'Update', schema: UPDATE, model: 'sonnet', effort: 'low' })
  summaries.push({ round, cases: listed.cases.length, missing, update: upd && upd.output })
  if (args.casesPath) break
}
return { label, rounds: summaries }
```

Note for the implementer: the verifier's write-back. In the batch workflow, the verifiers sometimes skipped writing
the verification back into the record. `update_truth.py` reads `verification` from the record file, so if a round
reports a missing verification, write the journal's verdict into the record before rerunning the update. Use the
same approach as `fix_verify.py` in the original diagnosis run: copy the verdict object from the workflow journal
into `records/<case_id>.json` under `verification`.

- [ ] **Step 5: Check the files**

Run: `node --check .claude/workflows/diagnosis-truth-normalize.js 2>&1 | head -3; node --check .claude/workflows/diagnosis-truth-loop.js 2>&1 | head -3`

Expected: either no output, or only a complaint about top-level `await` or `export` (the harness runs these as
modules). Fix any other syntax error it names. If `node` is missing, skip this step.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/diagnose-delisting/truth-rules.md .claude/skills/diagnose-delisting/SKILL.md .claude/workflows/diagnosis-truth-normalize.js .claude/workflows/diagnosis-truth-loop.js
git commit -m "Diagnose skill: truth rules and the loop's regression and mismatch modes; normalize and loop workflows (sub-plan 5-0)"
```

---

### Task 8: Building the truth file from the normalized rows

**Files:**
- Create: `src/delist_detection/truth_build.py`
- Create: `scripts/build_diagnosis_truth.py`
- Test: `tests/test_truth_build.py`

**Interfaces:**
- Consumes: Task 1's columns, shapes and statuses and `parse_rows`; Task 2's `LibraryRows` and `judge_case`;
  `openfigi.OpenFigiClient` and `openfigi.resolve_api_key`; `figi_resolution.us_candidates`.
- Produces:
  - `SUB_PLANS = ("5a", "5b", "5c", "5d", "5e", "5f", "5g", "5h", "5i")` and `RESIDUAL = "residual"`.
  - `assemble(norm, meta, *, composite_of, securities) -> tuple[dict[str, str], list[dict[str, str]]]`, returning
    the truth row and its leg rows. Status is provisional: `ruling_pending`, `known_wrong` with fixed_by residual,
    or `""`.
  - `final_status(row, ok, sub_plan) -> None`, which edits the row in place.
  - `review_markdown(rows, judgements) -> str`.
  - Script:
    `python scripts/build_diagnosis_truth.py [--rows DIR] [--case-map CSV] [--out data/diagnosis_truth.csv] [--legs data/diagnosis_truth_legs.csv] [--review output/diagnose_unknown_report/truth_review.md] [--no-figi]`.
    It contacts OpenFIGI only for CUSIPs not already cached, and needs `allowed_domains` api.openfigi.com.

- [ ] **Step 1: Write the failing tests**

`tests/test_truth_build.py`:

```python
"""truth_build: one normalized JSON row into one truth row (spec 1.2)."""
from delist_detection import diagnosis_truth as dt
from delist_detection import truth_build as tb
from tests.lifecycle_tables import contract_row, tables

FIELDS = {f: "" for f in dt.SCORED}


def _norm(**over):
    norm = {"case_id": "BBGA_2010-01-04", "sec_id": "BBGA", "shape": "ending",
            "fields": {**FIELDS, "exit_kind": "merger", "continuation": "false", "value_rule": "cash",
                       "cash_per_share": "10", "cash_currency": "USD"},
            "internal_last_trade_date": "", "legs": [], "identity_check": None, "residual": "", "pending": [],
            "notes": "8-K 2.01"}
    norm.update(over)
    return norm


META = {"ticker": "AAA", "report": "reports/BBGA_2010-01-04.md", "confidence": "verified", "skeptic": "upheld"}


def _assemble(norm, composite=None, securities=()):
    return tb.assemble(norm, META, composite_of=lambda cusip: composite, securities=set(securities))


def test_a_settled_row_carries_every_field_and_the_report_metadata():
    row, legs = _assemble(_norm())
    assert (row["case_id"], row["ticker"], row["cash_per_share"], row["status"]) == ("BBGA_2010-01-04", "AAA", "10", "")
    assert row["note"] == "8-K 2.01" and legs == []


def test_pending_fields_become_star_and_the_row_ruling_pending():
    row, _ = _assemble(_norm(pending=[{"field": "cash_per_share", "question": "which amendment?"}]))
    assert (row["cash_per_share"], row["status"]) == ("*", "ruling_pending") and "which amendment?" in row["note"]


def test_a_residual_row_is_known_wrong_with_its_reason():
    row, _ = _assemble(_norm(residual="no OTC ADS price source"))
    assert (row["status"], row["fixed_by"]) == ("known_wrong", "residual") and "no OTC ADS" in row["note"]


def test_a_new_cusip_with_its_own_figi_turns_into_a_continuation():
    norm = _norm(shape="no_ending", fields=dict(FIELDS), identity_check={"old_cusip": "1", "new_cusip": "2"})
    row, _ = _assemble(norm, composite="BBGB", securities={"BBGB"})
    assert (row["shape"], row["continuation"], row["successor_sec_id"], row["value_rule"]) == (
        "ending", "true", "BBGB", "continuation")
    unseen, _ = _assemble(norm, composite="BBGC", securities=set())
    assert unseen["successor_sec_id"] == "*"


def test_the_same_figi_or_none_or_a_placeholder_keeps_one_security():
    norm = _norm(shape="no_ending", fields=dict(FIELDS), identity_check={"old_cusip": "1", "new_cusip": "2"})
    assert _assemble(norm, composite="BBGA")[0]["shape"] == "no_ending"
    assert _assemble(norm, composite=None)[0]["shape"] == "no_ending"
    placeholder = {**norm, "case_id": "CIK1-COMMON_2010-01-04", "sec_id": "CIK1-COMMON"}
    assert _assemble(placeholder, composite="BBGB")[0]["shape"] == "no_ending"


def test_legs_come_out_as_leg_rows():
    _, legs = _assemble(_norm(legs=[{"leg": 1, "ratio": "1", "price_sec_id": "", "price_ticker": "LION",
                                     "price_date": ""}]))
    assert legs == [{"case_id": "BBGA_2010-01-04", "leg": "1", "ratio": "1", "price_sec_id": "",
                     "price_ticker": "LION", "price_date": ""}]


def test_final_status_uses_the_judgement_and_the_case_map():
    row, _ = _assemble(_norm())
    tb.final_status(row, ok=True, sub_plan="5e")
    assert (row["status"], row["fixed_by"]) == ("pass", "")
    row, _ = _assemble(_norm())
    tb.final_status(row, ok=False, sub_plan="5e")
    assert (row["status"], row["fixed_by"]) == ("known_wrong", "5e")
    row, _ = _assemble(_norm())
    tb.final_status(row, ok=False, sub_plan="none")
    assert row["status"] == "ruling_pending" and "no sub-plan" in row["note"]
    pending, _ = _assemble(_norm(pending=[{"field": "cash_per_share", "question": "q"}]))
    tb.final_status(pending, ok=True, sub_plan="5e")
    assert pending["status"] == "ruling_pending"


def test_review_markdown_lists_counts_pending_questions_and_residuals():
    a, _ = _assemble(_norm())
    tb.final_status(a, ok=False, sub_plan="5e")
    b, _ = _assemble(_norm(case_id="BBGB_2010-01-04", sec_id="BBGB",
                           pending=[{"field": "stock_ratio", "question": "final proration?"}]))
    cases = dt.parse_rows([a, b])
    lib = dt.LibraryRows.of(tables(contract_delistings=[contract_row("BBGA", exit_kind="merger", value_rule="cash",
                                                                      cash_per_share="9.000000")]))
    text = tb.review_markdown([a, b], dt.judge_all(cases, lib))
    assert "known_wrong" in text and "final proration?" in text and "cash_per_share" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_truth_build.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'delist_detection.truth_build'`.

- [ ] **Step 3: Write the module**

`src/delist_detection/truth_build.py`:

```python
"""The first diagnosis truth file, from the normalization pass (spec 2026-10-03-diagnosis-truth-fixes, 1.2). The
diagnosis-truth-normalize workflow writes one JSON row per case under
output/diagnose_unknown_report/truth_rows/; `assemble` turns each into a data/diagnosis_truth.csv row.

`assemble` applies what the agents could not decide:
- Ruling R2's FIGI check on a CUSIP change. The caller looks up the new CUSIP's composite, and a different
  composite makes two securities linked as a continuation.
- The pending fields, which become `*` with status ruling_pending.
- The residual list: known_wrong, with fixed_by residual.

`final_status` sets the status against the current run: pass, or known_wrong with the case map's sub-plan. A case
the reports found right but the library does not match becomes ruling_pending."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence

from .diagnosis_truth import (COLUMNS, ENDING, KNOWN_WRONG, NOT_SCORED, PASS, RULING_PENDING, SCORED, CaseJudgement,
                              field_key)

SUB_PLANS = ("5a", "5b", "5c", "5d", "5e", "5f", "5g", "5h", "5i")
RESIDUAL = "residual"
CONTINUATION_BLANKS = ("drop_reason", "cash_per_share", "cash_currency", "stock_ratio", "price_sec_id",
                       "price_ticker", "price_date", "recovery_ratio")


def _note(row: dict[str, str], text: str) -> None:
    row["note"] = f"{row['note']}; {text}" if row["note"] else text


def assemble(norm: Mapping, meta: Mapping[str, str], *, composite_of: Callable[[str], str | None],
             securities: Collection[str]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """One truth row (status provisional: ruling_pending, known_wrong residual, or blank) and its leg rows."""
    row = dict.fromkeys(COLUMNS, "")
    row.update(case_id=norm["case_id"], sec_id=norm["sec_id"], shape=norm["shape"], ticker=meta.get("ticker", ""),
               report=meta.get("report", ""), confidence=meta.get("confidence", ""), skeptic=meta.get("skeptic", ""),
               internal_last_trade_date=str(norm.get("internal_last_trade_date") or ""), note=norm.get("notes", ""))
    fields = norm.get("fields") or {}
    row.update({f: "" if fields.get(f) is None else str(fields.get(f, NOT_SCORED)) for f in SCORED})
    check = norm.get("identity_check") or {}
    if check.get("new_cusip") and norm["sec_id"].startswith("BBG"):
        comp = composite_of(check["new_cusip"])
        if comp and comp != norm["sec_id"]:
            row.update(shape=ENDING, exit_kind="exchange", continuation="true", value_rule="continuation",
                       successor_sec_id=comp if comp in securities else NOT_SCORED,
                       **dict.fromkeys(CONTINUATION_BLANKS, ""))
            _note(row, f"R2: the new CUSIP {check['new_cusip']} has its own FIGI {comp}, so two securities")
    for p in norm.get("pending") or []:
        if p.get("field") in SCORED:
            row[p["field"]] = NOT_SCORED
        _note(row, f"pending {p.get('field')}: {p.get('question')}")
    if norm.get("pending"):
        row["status"] = RULING_PENDING
    elif norm.get("residual"):
        row.update(status=KNOWN_WRONG, fixed_by=RESIDUAL)
        _note(row, f"residual: {norm['residual']}")
    legs = [{"case_id": norm["case_id"], "leg": str(lg["leg"]), "ratio": str(lg["ratio"]),
             "price_sec_id": lg.get("price_sec_id", ""), "price_ticker": lg.get("price_ticker", ""),
             "price_date": lg.get("price_date", "")} for lg in norm.get("legs") or []]
    return row, legs


def final_status(row: dict[str, str], ok: bool, sub_plan: str) -> None:
    """The status against the current run, for a row whose status `assemble` left blank."""
    if row["status"]:
        return
    if ok:
        row.update(status=PASS, fixed_by="")
    elif sub_plan in SUB_PLANS:
        row.update(status=KNOWN_WRONG, fixed_by=sub_plan)
    else:
        row["status"] = RULING_PENDING
        _note(row, "the library differs, but the case map gives no sub-plan (the report found it right)")


def review_markdown(rows: Sequence[Mapping[str, str]], judgements: Sequence[CaseJudgement]) -> str:
    """The operator's review page for the built truth file."""
    status = Counter(r["status"] for r in rows)
    shape = Counter(r["shape"] for r in rows)
    fixed = Counter(r["fixed_by"] for r in rows if r["status"] == KNOWN_WRONG)
    fields = Counter(field_key(m.field) for j in judgements for m in j.mismatches)
    out = ["# Diagnosis truth file: review", "",
           f"{len(rows)} cases. Status: {dict(status)}. Shape: {dict(shape)}.", "",
           "## known_wrong by sub-plan", "", *[f"- {k}: {v}" for k, v in sorted(fixed.items())], "",
           "## Mismatches by field (judged cases)", "", *[f"- {k}: {v}" for k, v in fields.most_common()], "",
           "## Pending questions", ""]
    out += [f"- {r['case_id']} ({r['ticker']}): {r['note']}" for r in rows if r["status"] == RULING_PENDING]
    out += ["", "## Residual list", ""]
    out += [f"- {r['case_id']} ({r['ticker']}): {r['note']}" for r in rows if r["fixed_by"] == RESIDUAL]
    return "\n".join(out) + "\n"
```

- [ ] **Step 4: Write the script**

`scripts/build_diagnosis_truth.py`:

```python
"""Build data/diagnosis_truth.csv (and its legs) from the normalization pass (spec
2026-10-03-diagnosis-truth-fixes, 1.2).

  python scripts/build_diagnosis_truth.py             # NETWORK: OpenFIGI for new CUSIPs not yet cached
  python scripts/build_diagnosis_truth.py --no-figi   # offline: no R2 check (lists the unchecked cases)

Reads output/diagnose_unknown_report/truth_rows/*.json, records/*.json (confidence, verification), the case map
(sub-plan per case) and the run's tables. Writes the truth file, the legs file and
output/diagnose_unknown_report/truth_review.md. Exit 2: a missing input or a row the truth loader refuses.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from delist_detection.diagnosis_truth import (COLUMNS, Leg, LibraryRows, judge_case, parse_rows,
                                              write_diagnosis_truth, write_legs)
from delist_detection.figi_resolution import us_candidates
from delist_detection.lifecycle import Tables
from delist_detection.openfigi import OpenFigiClient, resolve_api_key
from delist_detection.truth import TruthFileError
from delist_detection.truth_build import assemble, final_status, review_markdown

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / "output" / "diagnose_unknown_report"


def _figi(no_figi: bool):
    if no_figi:
        return lambda cusip: None
    client = OpenFigiClient(ROOT / "cache" / "openfigi", resolve_api_key())

    def composite_of(cusip: str) -> str | None:
        ans = client.map([{"idType": "ID_CUSIP", "idValue": cusip, "includeUnlistedEquities": True}])[0]
        cands = us_candidates(ans.get("data") or [])
        return cands[0].composite if len(cands) == 1 else None
    return composite_of


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rows", type=Path, default=DIAG / "truth_rows")
    p.add_argument("--records", type=Path, default=DIAG / "records")
    p.add_argument("--case-map", type=Path,
                   default=ROOT / "docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes/case_map.csv")
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "diagnosis_truth.csv")
    p.add_argument("--legs", type=Path, default=ROOT / "data" / "diagnosis_truth_legs.csv")
    p.add_argument("--review", type=Path, default=DIAG / "truth_review.md")
    p.add_argument("--no-figi", action="store_true")
    args = p.parse_args(argv)
    try:
        norms = [json.loads(f.read_text()) for f in sorted(args.rows.glob("*.json"))]
        with args.case_map.open(newline="") as fh:
            sub_plan = {r["case_id"]: r["sub_plan"] for r in csv.DictReader(fh)}
        tables = Tables.read(args.output_dir)
    except (OSError, ValueError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    missing = sorted(set(sub_plan) - {n["case_id"] for n in norms})
    if missing:
        print(f"ABORTED: no truth row for {len(missing)} case(s): {missing[:10]}", file=sys.stderr)
        return 2
    securities = {r["sec_id"] for r in tables.securities}
    composite_of = _figi(args.no_figi)
    rows, legs = [], []
    for n in norms:
        rec_path = args.records / f"{n['case_id']}.json"
        rec = json.loads(rec_path.read_text()) if rec_path.exists() else {}
        v = rec.get("verification")
        meta = {"ticker": rec.get("ticker", ""), "report": rec.get("report", ""),
                "confidence": rec.get("confidence", ""),
                "skeptic": "" if not v else ("upheld" if v.get("upheld") else "refuted")}
        row, leg_rows = assemble(n, meta, composite_of=composite_of, securities=securities)
        rows.append(row)
        legs += leg_rows
    if args.no_figi:
        unchecked = [n["case_id"] for n in norms if (n.get("identity_check") or {}).get("new_cusip")]
        print(f"--no-figi: R2 not checked for {len(unchecked)} case(s): {unchecked[:10]}")
    legs_by_case: dict[str, tuple[Leg, ...]] = {}
    for lg in sorted(legs, key=lambda r: (r["case_id"], int(r["leg"]))):
        legs_by_case[lg["case_id"]] = legs_by_case.get(lg["case_id"], ()) + (
            Leg(int(lg["leg"]), lg["ratio"], lg["price_sec_id"], lg["price_ticker"], lg["price_date"]),)
    try:
        lib = LibraryRows.of(tables)
        for row in rows:
            # A row assemble left without a status is judged as if it were `pass`; final_status then decides.
            [case] = parse_rows([{**row, "status": row["status"] or "pass"}], f"truth row {row['case_id']}",
                                legs_by_case)
            final_status(row, judge_case(case, lib).ok, sub_plan.get(row["case_id"], ""))
        cases = parse_rows(rows, "built truth", legs_by_case)
    except TruthFileError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    rows.sort(key=lambda r: r["case_id"])
    write_diagnosis_truth(args.out, [{c: r[c] for c in COLUMNS} for r in rows])
    write_legs(args.legs, sorted(legs, key=lambda r: (r["case_id"], int(r["leg"]))))
    judged = [judge_case(c, lib) for c in cases if c.status != "ruling_pending"]
    args.review.write_text(review_markdown(rows, judged))
    status = {s: sum(r["status"] == s for r in rows) for s in ("pass", "known_wrong", "ruling_pending")}
    print(f"{len(rows)} truth rows {status}, {len(legs)} legs -> {args.out}, review {args.review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_truth_build.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/truth_build.py scripts/build_diagnosis_truth.py tests/test_truth_build.py
git commit -m "Truth build: normalized rows into data/diagnosis_truth.csv with the R2 FIGI check and statuses (sub-plan 5-0)"
```

---

### Task 9: Run the normalization pass, build the truth file, and get the operator's review

**Files:**
- Create (by the run): `output/diagnose_unknown_report/truth_rows/*.json`, `data/diagnosis_truth.csv`,
  `data/diagnosis_truth_legs.csv` and `output/diagnose_unknown_report/truth_review.md`.
- Modify: `data/scorecard.json`.

**Interfaces:**
- Consumes: Task 7's `diagnosis-truth-normalize` workflow and Task 8's build script.
- Produces: the reviewed truth file that the scorecard names (`"diagnosis"`, `"diagnosis_legs"`), and floors on the
  `D.*` lines.

- [ ] **Step 1: Pilot ten cases**

Pick ten cases that cover each shape and rule: CAL, THI, BHI, LGFB, SDRL, EXE, a reverse split (FMD), a rename
(JNY), an OTC print (WM) and an election (FRK). Get their case ids from `output/diagnose_unknown_report/summary.csv`.
Run the Workflow tool with `name: "diagnosis-truth-normalize"` and `args: {"cases": [<the ten ids>], "batch": 5}`.

Expected: ten JSON files under `output/diagnose_unknown_report/truth_rows/`. Read every one against its report:
- CAL: stock, 1.05, `price_ticker` UAL, `last_trade_date` 2010-09-30 (stated in UAL's 8-K).
- THI: cash_plus_stock, CAD, `price_ticker` QSR.
- BHI: a continuation with successor BBG00GBVBK51.
- LGFB: a basket with two legs.
- EXE: `residual` set.
- FMD: `identity_check` filled.

Fix `truth-rules.md` where an agent misread a rule, and rerun the pilot cases you changed the rule for.

- [ ] **Step 2: Run the rest**

Run the workflow on the other 272 case ids, `batch: 10`. That is about 28 agents, at most 5 at a time. Note the time
it takes and the total tokens, for the operator's speed report. Expected: `missing` is empty. Rerun any missing
cases.

- [ ] **Step 3: Build**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/build_diagnosis_truth.py`
with Bash `allowed_domains: ["api.openfigi.com"]`.

Expected output: `282 truth rows {'pass': ..., 'known_wrong': ..., 'ruling_pending': ...}`. The build's
`parse_rows` validates every row. If it aborts on a row, fix that row's JSON (or its rule) and rebuild.

- [ ] **Step 4: Review gate**

STOP here. Send the operator `output/diagnose_unknown_report/truth_review.md` and a summary:
- the count per status;
- each pending question;
- the residual list;
- known_wrong per sub-plan;
- mismatches per field.

Wait for the operator's rulings on the pending questions. Write each ruling into the case's JSON (replacing `*`
with the value and removing the `pending` entry), then rebuild. Do not continue until the operator approves the
truth file.

- [ ] **Step 5: Name the truth files in the config and set the floors**

Edit `data/scorecard.json` to add, after `"audit"`:

```json
  "diagnosis": "diagnosis_truth.csv",
  "diagnosis_legs": "diagnosis_truth_legs.csv",
```

Then run:
- `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --write --raise-floor`
- `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`

Expected:
- The floor gains `D.mismatches`, `D.cases_matching` and `D.mismatches.<field>`.
- The suite passes, plus one strict xfail per known_wrong truth case and one skip per ruling_pending case in
  `test_diagnosis_truth_cases.py`.
- `diagnosis_failures` is empty, because every `pass` case matches by construction.

- [ ] **Step 6: Commit**

```bash
git add data/diagnosis_truth.csv data/diagnosis_truth_legs.csv data/scorecard.json output/scorecard.json output/diagnose_unknown_report/truth_rows output/diagnose_unknown_report/truth_review.md
git commit -m "Diagnosis truth file: 282 cases built from the reports and reviewed; D lines floored (sub-plan 5-0)"
```

---

### Task 10: Pilot the loop, seed the ledger, dry-run 5-0's own loop, and document

**Files:**
- Create (by the run): `output/diagnose_unknown_report/loop/diagnosed.csv` and
  `output/diagnose_unknown_report/loop/pilot/round-1/...`.
- Modify: `CLAUDE.md`.

**Interfaces:**
- Consumes: everything above.
- Produces: a seeded ledger, a verified loop, and documentation.

- [ ] **Step 1: Seed the ledger**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/truth_loop_round.py --label 5-0 --seed-ledger`

Expected: one JSON line, where `seeded` equals the scorecard's `D.mismatches`. Running it a second time prints
`"seeded": 0`.

- [ ] **Step 2: Pilot both modes on prepared cases**

Write `output/diagnose_unknown_report/loop/pilot/round-1/cases.csv` with two rows, using the Task 5
`case_rows`/`write_cases` code from a short Python snippet:
- **A mismatch on CAL's `price_ticker`.** Take the current library value UAUA against truth UAL. Expected verdict:
  `truth`.
- **A fake regression on a confirmed row.** Pick one contract row with verdict `confirmed` and a MIDAS last trade
  date. Put its real `last_trade_date` in `side_a` and that date plus 7 days in `side_b`. Expected verdict: `old`.

Run the Workflow tool with `name: "diagnosis-truth-loop"` and
`args: {"label": "pilot", "base": "HEAD", "casesPath": "output/diagnose_unknown_report/loop/pilot/round-1/cases.csv"}`.

Expected:
- Two reports and two records under the pilot folder, each with `field_verdicts` and a `verification` object.
- The update step runs with `--dry-run` and prints a JSON line. Its `truth_changes` is 0 for CAL (the truth stands)
  and 1 for the fake regression (a known_wrong row would be added; dry run, nothing written).

If an agent misreads its mode, fix the "Modes" section or the prompts and rerun. Delete the pilot folder afterwards,
so the ledger never holds pilot keys:

```bash
rm -r output/diagnose_unknown_report/loop/pilot
```

- [ ] **Step 3: Dry-run 5-0's own loop**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/truth_loop_round.py --label 5-0 --base HEAD --round 1`

Expected: `"mismatches_new": 0, "regressions_new": 0, "cases": []`. 5-0 changes no library code, and the seeded
ledger holds every mismatch. Then run:

`PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --check`

Expected: exit 0, with `D.unexplained_regressions` at 0.

- [ ] **Step 4: Document**

In `CLAUDE.md`'s Commands block, after the `scorecard.py` line, add:

```bash
python scripts/build_diagnosis_truth.py   # the diagnosis truth file from the normalization pass (OpenFIGI for new CUSIPs; --no-figi offline)
python scripts/regression_report.py --base <commit>    # offline: contract changes outside the truth set -> output/regression_report.csv
python scripts/truth_loop_round.py --label 5a --base <commit> --round 1   # offline: one loop round's new errors -> loop/<label>/round-<N>/cases.csv (--seed-ledger records current mismatches as known)
python scripts/update_truth.py --label 5a --round 1 --base <commit>      # offline: apply the round's diagnoses to data/diagnosis_truth.csv (--dry-run)
# The loop: run the Workflow tool with name "diagnosis-truth-loop", args {"label", "base"} (at most 3 rounds, 5 agents)
```

In the "Measurement (pure)" list, after the `truth.py` entry, add:

```markdown
- `diagnosis_truth.py`: the diagnosis truth set (`data/diagnosis_truth.csv`, spec
  2026-10-03-diagnosis-truth-fixes). It holds one row per diagnosed case. `shape` is ending, no_ending or
  ending_moved. Scored contract fields hold a value, a blank or `*`. `internal_last_trade_date` holds a worked-out
  date, and a side file holds a basket's legs. Its judge (`LibraryRows`, `judge_case`) gives one `Mismatch` per
  scored field. The scorecard's `D.*` lines and `tests/test_diagnosis_truth_cases.py` (strict xfail on known_wrong)
  read it.
- `regression.py`: the contract diff against a base commit (`snapshot_at`, git), outside the truth set and its
  successor chains (`excluded`). `unexplained` gives the rows the ledger has not settled; they become
  `D.unexplained_regressions`, which `scripts/scorecard.py --check` requires to be 0.
- `diagnosis_loop.py`: the loop's ledger (`output/diagnose_unknown_report/loop/diagnosed.csv`), error keys, case
  rows for the diagnose workflow, and placeholder renames through `contract/id_changes.csv`.
- `truth_update.py`: spec 1.6's rules for what a round's diagnoses may change in the truth file. A regression is
  added only when it is verified and upheld. A mismatch changes the truth only when the diagnosis cites a filing the
  earlier report missed. `flip_statuses` turns a known_wrong case that now matches into pass.
- `truth_build.py`: the first truth file, built from the normalization workflow's JSON rows (the R2 FIGI check,
  pending fields, the residual list, statuses).
```

In "Non-obvious invariants", add a bullet:

```markdown
- **Every fix sub-plan passes the diagnosis truth loop (spec 2026-10-03-diagnosis-truth-fixes).** After the cached
  full run, the loop works as follows:
  1. `truth_loop_round.py` judges the run against `data/diagnosis_truth.csv` and writes the regression report
     against the sub-plan's base commit.
  2. It keeps the errors the ledger has not seen.
  3. The `diagnosis-truth-loop` workflow diagnoses each one in regression or mismatch mode, with a skeptic per case.
  4. `update_truth.py` applies the outcomes under fixed rules: the truth never takes a library value unless a
     verified, upheld diagnosis cites a filing the earlier report missed.

  The loop stops after a round with no new error, or after 3 rounds. A sub-plan is accepted only when `D.mismatches`
  fell, `D.unexplained_regressions` is 0 and `--check` passes.
```

Change the Commands block's `pytest` comment from "(1711 tests + 18 known-wrong golden xfails...)" to the count
`pytest -q` now prints, and mention the diagnosis xfails.

- [ ] **Step 5: Full suite and final commit**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
Expected: all green apart from the strict xfails (golden and diagnosis) and the ruling_pending skips.

```bash
git add output/diagnose_unknown_report/loop/diagnosed.csv output/regression_report.csv CLAUDE.md
git commit -m "Diagnosis loop: ledger seeded with the reports' mismatches, modes piloted, 5-0 dry run clean; docs (sub-plan 5-0)"
```

- [ ] **Step 6: Report to the operator**

Send the 5-0 report:
- the truth file's counts per status and shape, and known_wrong per sub-plan;
- `D.mismatches` per field (the real baseline);
- the pilot's outcome;
- the normalization pass's time and tokens;
- the residual list as it stands.

Update the roadmap's 5-0 row to `done`.

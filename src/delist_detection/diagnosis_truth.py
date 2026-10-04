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

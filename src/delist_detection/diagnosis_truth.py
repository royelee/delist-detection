"""The diagnosis truth set (spec: docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md, section 1):
what each diagnosed security's contract row should say, as the contract would publish it, and the judge that
compares one run's tables to it.

`data/diagnosis_truth.csv` holds one row per case. `shape` says what is checked:

    ending        the security's contract/delistings.csv row must match the scored fields
    no_ending     the security has no real ending: there is no contract row for it
    ending_moved  the ending the report examined is not the security's last real ending: delistings.csv's last
                  real ending must have another delist_date than `examined_delist_date`, and the scored fields that
                  are not `*` are checked on the contract row (required only when one is scored)

`examined_delist_date` is the delist_date of the ending the report examined: required for ending_moved, blank when
the case examined no ending (a removed row). It is a column of its own, never read from the case_id (a loop-added
case's id ends in its round, not a date).
A scored cell holds the value, a blank (the field must be blank) or `*` (not scored).

The two last trade dates. The scored `last_trade_date` is the contract's published day of the security's own last
ending (contract/delistings.csv: decision 12 publishes only exchange prints). `internal_last_trade_date` is
delistings.csv's internal day of that same ending, the corrected one when the contract leaves it blank (a worked-out
date); blank there means not scored. The golden set's `last_trade_date` column is neither of these: delistings.csv's
day of the chain's final ending (`truth.TruthCase.final_last_trade_date`).

`status` is pass (must match now) or known_wrong (must not match yet; `fixed_by` names the sub-plan, or `residual`),
both `truth`'s, or ruling_pending (not judged; `fixed_by` `regression` marks a regressed row the loop could not
settle), this set's own. `data/diagnosis_truth_legs.csv` holds a basket's legs (ruling R3), judged against
contract/payout_legs.csv once the contract has one.

This module holds the rows' format (`parse_rows` and `parse_legs` turn rows into validated cases) and the judge,
which gives every truth set's judgement (`truth.Judgement`, a `truth.Mismatch` per scored field that disagrees). The
files are read, changed and written as one truth set (`truth_set.TruthSet`), their only reader and writer.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from .exit_kind import DROP_REASONS, EXIT_KINDS, VALUE_RULES, last_endings
from .run_snapshot import RunSnapshot
from .truth import KNOWN_WRONG, PASS, Judgement, Mismatch, TruthFileError, check_status

SCORED = ("exit_kind", "drop_reason", "continuation", "successor_sec_id", "last_trade_date", "value_rule",
          "cash_per_share", "cash_currency", "stock_ratio", "price_sec_id", "price_ticker", "price_date",
          "recovery_ratio")
COLUMNS = ("case_id", "sec_id", "ticker", "report", "confidence", "skeptic", "status", "fixed_by", "shape",
           "examined_delist_date", *SCORED, "internal_last_trade_date", "note")
LEG_COLUMNS = ("case_id", "leg", "ratio", "price_sec_id", "price_ticker", "price_date")
NOT_SCORED = "*"
ENDING, NO_ENDING, ENDING_MOVED = "ending", "no_ending", "ending_moved"
SHAPES = (ENDING, NO_ENDING, ENDING_MOVED)
RULING_PENDING = "ruling_pending"                 # this set's own status (not judged); pass and known_wrong are truth's
STATUSES = (PASS, KNOWN_WRONG, RULING_PENDING)
REGRESSION_PENDING = "regression"            # fixed_by of a ruling_pending row the loop added for a regression
BASKET = "basket"
TRUTH_VALUE_RULES = VALUE_RULES | {BASKET}
NUMBERS = ("cash_per_share", "stock_ratio", "recovery_ratio")
DATES = ("last_trade_date", "price_date")


@dataclass(frozen=True)
class Leg:
    leg: int
    ratio: str
    price_sec_id: str = ""
    price_ticker: str = ""
    price_date: str = ""


@dataclass(frozen=True)
class DiagnosisCase:
    """One diagnosis case (module docstring). `fields` holds the scored contract cells: its `last_trade_date` is the
    contract's published day; `internal_last_trade_date` is delistings.csv's day of the same ending."""
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
    examined_delist_date: str = ""           # the delist_date of the ending the report examined (module docstring)


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
        raise TruthFileError(f"{where}: {name} {cell!r} is not one of {sorted(allowed)}")
    if (name in DATES or name in ("internal_last_trade_date", "examined_delist_date")) and not _is_date(cell):
        raise TruthFileError(f"{where}: {name} {cell!r} is not a YYYY-MM-DD date")
    if name in NUMBERS and not _is_number(cell):
        raise TruthFileError(f"{where}: {name} {cell!r} is not a number")


def parse_rows(rows: Sequence[Mapping[str, str]], where: str = "rows",
               legs: Mapping[str, tuple[Leg, ...]] | None = None) -> list[DiagnosisCase]:
    """Truth rows (every COLUMNS key) as cases. Raises TruthFileError naming `where` and the line (the header
    is line 1) on a blank or repeated case_id, a blank sec_id, an unknown shape or status, a known_wrong row with no
    fixed_by, an ending_moved row with no examined_delist_date, or a scored cell outside its vocabulary, date or
    number format."""
    out: list[DiagnosisCase] = []
    seen: set[str] = set()
    for line, r in enumerate(rows, start=2):
        at = f"{where}:{line}"
        cid = r["case_id"].strip()
        if not cid or cid in seen:
            raise TruthFileError(f"{at}: case_id {cid!r} is blank or repeated")
        seen.add(cid)
        if not r["sec_id"].strip():
            raise TruthFileError(f"{at}: sec_id is blank")
        if r["shape"] not in SHAPES:
            raise TruthFileError(f"{at}: shape {r['shape']!r} is not one of {list(SHAPES)}")
        check_status(r["status"], r["fixed_by"], at, STATUSES)
        cells = {f: r[f].strip() for f in SCORED}
        for name, cell in cells.items():
            _check(name, cell, at)
        internal = r["internal_last_trade_date"].strip()
        _check("internal_last_trade_date", internal, at)
        examined = r["examined_delist_date"].strip()
        _check("examined_delist_date", examined, at)
        if r["shape"] == ENDING_MOVED and not examined:
            raise TruthFileError(f"{at}: an ending_moved case needs the examined_delist_date it refuses")
        out.append(DiagnosisCase(
            case_id=cid, sec_id=r["sec_id"].strip(), ticker=r["ticker"], status=r["status"],
            fixed_by=r["fixed_by"].strip(), shape=r["shape"], fields=cells, internal_last_trade_date=internal,
            report=r["report"], confidence=r["confidence"], skeptic=r["skeptic"], note=r["note"],
            legs=(legs or {}).get(cid, ()), examined_delist_date=examined))
    return out


def parse_legs(rows: Sequence[Mapping[str, str]], where: str = "legs") -> dict[str, tuple[Leg, ...]]:
    """Leg rows (every LEG_COLUMNS key) by case_id, each case's legs in leg order. Raises TruthFileError naming
    `where` and the line (the header is line 1) on a leg number below 1, a repeated leg, a ratio that is not a number
    or a bad price_date."""
    by_case: dict[str, dict[int, Leg]] = {}
    for line, r in enumerate(rows, start=2):
        at = f"{where}:{line}"
        try:
            n = int(r["leg"])
        except ValueError:
            n = 0
        if n < 1:
            raise TruthFileError(f"{at}: leg {r['leg']!r} is not a number from 1")
        if not _is_number(r["ratio"]):
            raise TruthFileError(f"{at}: ratio {r['ratio']!r} is not a number")
        if r["price_date"] and not _is_date(r["price_date"]):
            raise TruthFileError(f"{at}: price_date {r['price_date']!r} is not a YYYY-MM-DD date")
        legs = by_case.setdefault(r["case_id"], {})
        if n in legs:
            raise TruthFileError(f"{at}: leg {n} of {r['case_id']} is repeated")
        legs[n] = Leg(n, r["ratio"], r["price_sec_id"], r["price_ticker"], r["price_date"])
    return {cid: tuple(legs[n] for n in sorted(legs)) for cid, legs in by_case.items()}


MISMATCH_FIELDS = (*SCORED, "internal_last_trade_date", "shape", "ending", "legs", "sec_id")
LEG_FIELDS = ("ratio", "price_sec_id", "price_ticker", "price_date")
_LEG_FIELD = re.compile(r"leg([1-9][0-9]*)\.(" + "|".join(LEG_FIELDS) + ")")


@dataclass(frozen=True)
class LibraryRows:
    """What the judge reads from one run (`of`, its snapshot): the contract row and the last real ending of each
    security, the run's securities (a case whose sec_id is gone from the run cannot be judged: a `no_ending` row
    would pass on it), and its payout legs (None: the run has no contract/payout_legs.csv yet, before sub-plan
    5f)."""
    contract: Mapping[str, Mapping[str, str]]
    last_endings: Mapping[str, Mapping[str, str]]
    sec_ids: Collection[str]
    legs: Mapping[str, Sequence[Mapping[str, str]]] | None = None

    @classmethod
    def of(cls, tables: RunSnapshot) -> LibraryRows:
        legs = None
        if tables.payout_legs is not None:
            grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
            for r in tables.payout_legs:
                grouped[r["sec_id"]].append(r)
            legs = {k: sorted(v, key=lambda r: int(r["leg"])) for k, v in grouped.items()}
        return cls({r["sec_id"]: r for r in tables.contract_delistings or ()}, last_endings(tables.delistings),
                   frozenset(r["sec_id"] for r in tables.securities), legs)


def leg_field(leg: int, name: str) -> str:
    """The field name of one leg's cell, `leg<N>.<name>` (a LEG_FIELDS name): the judge's mismatch field for it, and
    the change log's (`truth_set.TruthSet.rename`). `field_key` reads it back."""
    if leg < 1 or name not in LEG_FIELDS:
        raise ValueError(f"no leg field {leg}.{name}")
    return f"leg{leg}.{name}"


def field_key(name: str) -> str:
    """The MISMATCH_FIELDS entry a mismatch counts under: a leg field (`leg_field`) is `legs`, any other name is
    itself."""
    return "legs" if _LEG_FIELD.fullmatch(name) else name


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
                out.append(Mismatch(case.case_id, leg_field(leg.leg, name), want, row.get(name, "")))
    return out


def judge_case(case: DiagnosisCase, lib: LibraryRows) -> Judgement:
    """Compare one case to one run; every scored field that disagrees is one Mismatch (spec 1.3). A case whose
    sec_id is not in the run's securities gives one `sec_id` mismatch and nothing else. The scored `last_trade_date`
    is read from the contract row, `internal_last_trade_date` from the last real ending's delistings.csv row."""
    row, end = lib.contract.get(case.sec_id), lib.last_endings.get(case.sec_id)
    bad: list[Mismatch] = []

    def miss(name: str, truth: str, library: str) -> None:
        bad.append(Mismatch(case.case_id, name, truth, library))

    if case.sec_id not in lib.sec_ids:
        # A security folded into another (a placeholder that now holds a FIGI) has no contract row either, which
        # would read as "no ending" and pass a no_ending case; the case must be renamed or ruled on instead.
        miss("sec_id", case.sec_id, "(not in the run)")
        return Judgement(case, tuple(bad))
    if case.shape == NO_ENDING:
        if row is not None:
            miss("shape", NO_ENDING, "ending")
        return Judgement(case, tuple(bad))
    if case.shape == ENDING_MOVED and end is not None and end["delist_date"] == case.examined_delist_date:
        miss("shape", ENDING_MOVED, f"ending {case.examined_delist_date}")
    scored = [f for f in SCORED if case.fields[f] != NOT_SCORED]
    if row is None:
        if case.shape == ENDING or scored:
            miss("ending", "present", "(no contract row)")
        return Judgement(case, tuple(bad))
    for name in scored:
        if not _same(name, case.fields[name], row.get(name, "")):
            miss(name, case.fields[name], row.get(name, ""))
    if case.internal_last_trade_date not in ("", NOT_SCORED):
        internal = end["last_trade_date"] if end else ""          # delistings.csv's day, not the contract's
        if internal != case.internal_last_trade_date:
            miss("internal_last_trade_date", case.internal_last_trade_date, internal)
    if case.legs:
        bad.extend(_judge_legs(case, None if lib.legs is None else lib.legs.get(case.sec_id, [])))
    return Judgement(case, tuple(bad))


def judge_all(cases: Sequence[DiagnosisCase], lib: LibraryRows) -> list[Judgement]:
    """Every case that is not ruling_pending, judged."""
    return [judge_case(c, lib) for c in cases if c.status != RULING_PENDING]

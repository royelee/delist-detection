"""One round of the diagnosis truth loop (spec 2026-10-03-diagnosis-truth-fixes, sections 1.6 and 1.7), and every
token a round's errors are known by.

An error is a truth mismatch (a scored field the run gets wrong: `truth.Mismatch`) or a regression report
row (a contract field that changed outside the truth set since a base commit: `regression.build_report`). A round
of one sub-plan (`Round`, under a loop folder, `Loop`):

- opens (`Round.open`): it renames the truth rows that name a renamed security and commits the truth set, judges the
  run against the truth set, writes the regression report against the base run, keeps the errors the ledger has not
  seen, and writes them as case rows (cases.csv, one per truth case or regressed security) for the diagnose workflow
  (.claude/workflows/diagnosis-truth-loop.js);
- closes (`Round.close`): it reads the round's cases and the agents' records (records/<case_id>.json), applies them
  to the truth set by truth_update's rules (`truth_set.TruthSet.apply_round`), turns every known_wrong case that now
  matches into pass (`TruthSet.flip`), and commits the truth set (the truth file, its change log and the ledger
  together) and writes the round's summary.md, unless it is a dry run.

The ledger (`Loop.ledger`, the one place its path is named) records every error already diagnosed and its outcome,
so a round diagnoses only new errors. Sub-plan 5-0 seeded it with every mismatch the reports already describe
(`Loop.seed`, outcome `known`). A regression the ledger settled as right (`new_right`) is explained. The others, and
every regressed row the loop added to the truth file as ruling_pending (fixed_by `regression`), are unexplained
(`unexplained`): `D.unexplained_regressions` counts their securities, only against a base commit, and a sub-plan
is accepted only when it is 0 (`Unexplained.passes`, the gate of `scripts/scorecard.py --check --base`).

The tokens. Each is built by one function here and read back by its inverse here:
- an error's key: `mismatch_key` (`mis|<case_id>|<field>|<truth>|<library>`) and `regression_key` (`reg|` and the
  report row's columns), read by `parse_key`. A ledger row's kind is its key's (`ledger_row`).
- a regression's field name, as the case rows and the agents' field verdicts name it (`Field`): a changed contract
  delistings column is its name, a whole delistings row `delistings.added` or `delistings.removed`, any other table's
  change `<table>.<field>`. `Field.of` reads a report row, `Field.name` builds the name and `parse_field` reads it.
  A mismatch's field is the judge's own name (`diagnosis_truth.MISMATCH_FIELDS` and `leg_field`), carried as given.
- a case id (`case_id`): `<subject>_<label>-r<N>`, the subject being the truth case_id of a mismatch case and the
  sec_id of a regression case. Nothing reads it back: what a case examined is never read from its id: the case
  carries it (`RoundCase.delist_date`, which a truth row the loop adds keeps as `examined_delist_date`).
The keys a truth row the loop adds produces are the judge's (`new_row_keys` judges the row), so the judge's wording
can change without the ledger losing them.

The record vocabulary the agents write, which the workflow's RECORD schema declares too (tests/test_loop_round.py
reads the workflow and checks it agrees): `MODES`, `RIGHTS` (the side a field verdict found right), `CONFIDENCES`,
`VERDICT_KEYS` (one field verdict's keys) and `RECORD_KEYS` (what a finished record holds)."""
from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..sources.atomic_io import write_atomic
from .diagnosis_truth import RULING_PENDING, SCORED, DiagnosisCase, LibraryRows, judge_all, parse_rows
from ..vocabulary.exit_kind import last_endings
from .regression import (ADDED, REMOVED, REPORT_COLUMNS, build_report, id_changes_since, pending_regression,
                         report_row, write_report)
from ..outputs.run_snapshot import RunSnapshot
from .truth import Judgement, Mismatch
from .truth_set import TruthSet

LOOP_DIR = Path("output/diagnose_unknown_report/loop")          # under a repository
LEDGER_NAME = "diagnosed.csv"
CASES_NAME, RECORDS_NAME, REPORTS_NAME, SUMMARY_NAME = "cases.csv", "records", "reports", "summary.md"

# A ledger row's outcome.
KNOWN, NEW_RIGHT, OLD_RIGHT, TRUTH_RIGHT, LIBRARY_RIGHT, PENDING = (
    "known", "new_right", "old_right", "truth_right", "library_right", "pending")
OUTCOMES = (KNOWN, NEW_RIGHT, OLD_RIGHT, TRUTH_RIGHT, LIBRARY_RIGHT, PENDING)
# An error's kind: a ledger row's kind, and a case's mode.
MISMATCH, REGRESSION = "mismatch", "regression"
MODES = (REGRESSION, MISMATCH)
# The record vocabulary.
OLD, NEW, TRUTH, LIBRARY, NEITHER = "old", "new", "truth", "library", "neither"
RIGHTS = (OLD, NEW, TRUTH, LIBRARY, NEITHER)
VERIFIED = "verified"
CONFIDENCES = (VERIFIED, "inferred", "unresolved")
VERDICT_KEYS = ("field", "right", "value", "missed_filing")
RECORD_KEYS = ("field_verdicts", "confidence", "verification")

UNEXPLAINED = "D.unexplained_regressions"
DELISTINGS = "delistings"
REPORT_TABLES = (DELISTINGS, "security_history", "payout_legs", "id_changes")   # the tables a regression names

CONTEXT_COLUMNS = ("tickers", "security_name", "share_class", "issuer_ids", "first_start", "last_end", "intervals",
                   "delist_date", "library_cik", "bucket", "crsp_code", "reason", "last_trade_date_source",
                   "library_last_trade_close", "dlret_method", "delist_filing_form", "delist_filing_accession",
                   "review_flags", "uncertain_reasons")
CASE_COLUMNS = ("case_id", "mode", "sec_id", "ticker", "truth_case_id", "keys", "fields", "side_a", "side_b",
                *CONTEXT_COLUMNS)
_ERROR_CELLS = ("keys", "fields", "side_a", "side_b")


# -- the tokens ---------------------------------------------------------------------------------------------------
_PREFIX = {MISMATCH: "mis", REGRESSION: "reg"}
_KIND_OF = {p: k for k, p in _PREFIX.items()}


def _key(kind: str, parts: Sequence[str]) -> str:
    bad = next((p for p in parts if "|" in p), None)
    if bad is not None:
        raise ValueError(f"an error key cannot hold '|': {bad!r}")
    return "|".join((_PREFIX[kind], *parts))


def mismatch_key(m: Mismatch) -> str:
    """The ledger key of one truth mismatch. Raises ValueError when a part holds `|`."""
    return _key(MISMATCH, (m.case_id, m.field, m.truth, m.library))


def regression_key(row: Mapping[str, str]) -> str:
    """The ledger key of one regression report row (`regression.REPORT_COLUMNS`). Raises ValueError when a cell holds
    `|`."""
    return _key(REGRESSION, [row[c] for c in REPORT_COLUMNS])


def parse_key(key: str) -> Mismatch | dict[str, str]:
    """The error a key names: the Mismatch of a mismatch key, the report row of a regression key. Raises ValueError
    on any other text."""
    prefix, _, rest = key.partition("|")
    parts = rest.split("|")
    kind = _KIND_OF.get(prefix)
    if kind == MISMATCH and len(parts) == 4:
        return Mismatch(*parts)
    if kind == REGRESSION and len(parts) == len(REPORT_COLUMNS):
        return dict(zip(REPORT_COLUMNS, parts))
    raise ValueError(f"not an error key: {key!r}")


def key_kind(key: str) -> str:
    """MISMATCH or REGRESSION: the kind of error a key names."""
    return MISMATCH if isinstance(parse_key(key), Mismatch) else REGRESSION


@dataclass(frozen=True)
class Field:
    """A regression's field: the contract table, the column (blank for a whole row) and, for a whole delistings row,
    how it changed (`whole`: added or removed)."""
    table: str
    column: str
    whole: str = ""

    @classmethod
    def of(cls, row: Mapping[str, str]) -> Field:
        """The field of a regression report row."""
        if row["table"] == DELISTINGS and not row["field"]:
            return cls(DELISTINGS, "", row["kind"])
        return cls(row["table"], row["field"])

    @property
    def name(self) -> str:
        """The field's name (module docstring); `parse_field` reads it back."""
        if self.table == DELISTINGS:
            return self.column or f"{DELISTINGS}.{self.whole}"
        return f"{self.table}.{self.column}"

    @property
    def scored(self) -> bool:
        """A contract delistings column the truth set scores."""
        return self.table == DELISTINGS and self.column in SCORED


def parse_field(name: str) -> Field:
    """The field a regression's field name names. Raises ValueError on a name no regression has."""
    table, dot, rest = name.partition(".")
    if not dot and name:
        return Field(DELISTINGS, name)
    if table == DELISTINGS and rest in (ADDED, REMOVED):
        return Field(DELISTINGS, "", rest)
    if table in REPORT_TABLES[1:] and rest:
        return Field(table, rest)
    raise ValueError(f"not a regression field name: {name!r}")


_LABEL = r"[A-Za-z0-9][A-Za-z0-9.-]*"


def _check_label(label: str) -> None:
    if not re.fullmatch(_LABEL, label):
        raise ValueError(f"label {label!r}: letters, digits, '.' and '-' only, not starting with '.' or '-'")


def case_id(subject: str, label: str, round_no: int) -> str:
    """A round's case id: `<subject>_<label>-r<N>` (module docstring). Raises ValueError on a blank subject or a
    label that would make the id ambiguous (one holding `_`, or anything but letters, digits, `.` and `-`)."""
    _check_label(label)
    if not subject or round_no < 0:
        raise ValueError(f"no case id for subject {subject!r}, round {round_no}")
    return f"{subject}_{label}-r{round_no}"



# -- the ledger ---------------------------------------------------------------------------------------------------
def ledger_row(key: str, *, sec_id: str, label: str, round_no: int, outcome: str, report: str) -> dict[str, str]:
    """One ledger row: the error `key` settled with `outcome`; its kind is the key's."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome {outcome!r} is not one of {list(OUTCOMES)}")
    return dict(key=key, kind=key_kind(key), sec_id=sec_id, label=label, round=str(round_no), outcome=outcome,
                report=report)


def _explained(ledger_rows: Sequence[Mapping[str, str]]) -> set[str]:
    """The regression keys the loop settled as right: the report treats them as explained."""
    return {r["key"] for r in ledger_rows if r["outcome"] == NEW_RIGHT}


# -- a round's cases ----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CaseError:
    """One error of a case: its key, its field and its two sides (a mismatch: the truth's value, then the library's;
    a regression: the base run's, then this run's)."""
    key: str
    field: str
    side_a: str
    side_b: str


@dataclass(frozen=True)
class RoundCase:
    """One case of a round, as its cases.csv row holds it (`of`). `delist_date` is the security's last real ending
    when the round opened: the ending a regression case examined (blank when there is none)."""
    case_id: str
    mode: str
    sec_id: str
    ticker: str
    truth_case_id: str
    errors: tuple[CaseError, ...]
    delist_date: str = ""

    @classmethod
    def of(cls, row: Mapping[str, str]) -> RoundCase:
        """A case from its row (CASE_COLUMNS; the context columns other than delist_date may be missing). Raises
        ValueError on an unknown mode or error lists that are not JSON lists of one length."""
        if row["mode"] not in MODES:
            raise ValueError(f"case {row['case_id']}: mode {row['mode']!r} is not one of {list(MODES)}")
        try:
            cells = [json.loads(row[c]) for c in _ERROR_CELLS]
        except json.JSONDecodeError as exc:
            raise ValueError(f"case {row['case_id']}: {exc}") from None
        if not all(isinstance(c, list) for c in cells) or len({len(c) for c in cells}) != 1:
            raise ValueError(f"case {row['case_id']}: keys, fields, side_a and side_b are not lists of one length")
        return cls(row["case_id"], row["mode"], row["sec_id"], row["ticker"], row["truth_case_id"],
                   tuple(CaseError(*map(str, e)) for e in zip(*cells)), row.get("delist_date", ""))

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(e.key for e in self.errors)

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(e.field for e in self.errors)


def new_row_keys(case: RoundCase, row: Mapping[str, str], run: LibraryRows) -> list[str]:
    """The keys of the mismatches the truth row `row` (every diagnosis_truth.COLUMNS cell) that `case` adds has
    against the run `run`, as the next round's judge reports them: a field the case names in the case's order, then
    the rest in the judge's. truth_update settles them when the diagnosis found the old side right."""
    order = {}
    for i, f in enumerate(case.fields):
        order.setdefault(f, i)
    judged = judge_all(parse_rows([row], f"the {case.case_id} truth row"), run)
    mismatches = [m for j in judged for m in j.mismatches]
    return [mismatch_key(m) for m in sorted(mismatches, key=lambda m: order.get(m.field, len(order)))]


def _context(tables: RunSnapshot, sec_id: str) -> dict[str, str]:
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


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(path, buf.getvalue())


# -- the loop folder and its rounds -------------------------------------------------------------------------------
@dataclass(frozen=True)
class Loop:
    """A loop folder (by default `LOOP_DIR` under the repository, `of`): the ledger and each round's files. Report
    paths are recorded relative to `repo` when the folder lies inside it."""
    folder: Path
    repo: Path

    @classmethod
    def of(cls, repo: str | Path, folder: str | Path | None = None) -> Loop:
        repo = Path(repo)
        return cls(repo / LOOP_DIR if folder is None else Path(folder), repo)

    @property
    def ledger(self) -> Path:
        """The ledger: the one place its path is named."""
        return self.folder / LEDGER_NAME

    def truth_set(self, truth: str | Path) -> TruthSet:
        """The truth set of the truth file `truth`, with this loop's ledger."""
        return TruthSet.open(truth, ledger=self.ledger)

    def round(self, label: str, number: int) -> Round:
        return Round(self, label, number)

    def seed(self, truth: str | Path, run: RunSnapshot, *, label: str) -> Seeded:
        """Record every mismatch of `run` against the truth file `truth` that the ledger lacks as `known` (round 0),
        after renaming the truth rows by the run's own contract/id_changes.csv; commit the truth set."""
        ts = self.truth_set(truth)
        ts.rename(list(run.id_changes or []))
        judged = judge_all(ts.cases, LibraryRows.of(run))
        ts.commit()
        seen = ts.ledger_keys
        ts.settle(_seed_rows(judged, seen, label))
        ts.commit()
        return Seeded(label, len(ts.settled), self.ledger)


def _seed_rows(judgements: Sequence[Judgement], seen: Collection[str], label: str) -> list[dict[str, str]]:
    return [ledger_row(mismatch_key(m), sec_id=j.case.sec_id, label=label, round_no=0, outcome=KNOWN,
                       report=j.case.report)
            for j in judgements for m in j.mismatches if mismatch_key(m) not in seen]


@dataclass(frozen=True)
class Round:
    """Round `number` (from 1) of the sub-plan `label` under the loop folder `loop`: its files live in
    `<loop>/<label>/round-<N>/` (cases.csv, records/, reports/, summary.md)."""
    loop: Loop
    label: str
    number: int

    def __post_init__(self) -> None:
        _check_label(self.label)
        if self.number < 1:
            raise ValueError(f"round {self.number}: rounds are numbered from 1")

    @property
    def folder(self) -> Path:
        return self.loop.folder / self.label / f"round-{self.number}"

    @property
    def cases_file(self) -> Path:
        return self.folder / CASES_NAME

    @property
    def records_dir(self) -> Path:
        return self.folder / RECORDS_NAME

    @property
    def reports_dir(self) -> Path:
        return self.folder / REPORTS_NAME

    @property
    def summary_file(self) -> Path:
        return self.folder / SUMMARY_NAME

    @property
    def report_dir(self) -> str:
        """The reports folder as the truth file and the ledger record it: relative to the repository when inside it."""
        reports = self.reports_dir
        return reports.relative_to(self.loop.repo).as_posix() if reports.is_relative_to(self.loop.repo) \
            else str(reports)

    def case_id(self, subject: str) -> str:
        return case_id(subject, self.label, self.number)

    def cases(self) -> list[RoundCase]:
        """The round's cases (cases.csv). Raises ValueError when the file is missing or a row is bad."""
        if not self.cases_file.exists():
            raise ValueError(f"{self.cases_file}: missing")
        with self.cases_file.open(newline="", encoding="utf-8") as fh:
            return [RoundCase.of(r) for r in csv.DictReader(fh)]

    def records(self) -> dict[str, object]:
        """The agents' records by case_id (records/<case_id>.json), as parsed. Raises ValueError on a file that is
        not JSON."""
        return {f.stem: json.loads(f.read_text()) for f in sorted(self.records_dir.glob("*.json"))}

    def _case_rows(self, mismatches: Sequence[Mismatch], regressions: Sequence[Mapping[str, str]],
                   tables: RunSnapshot, truth_sec: Mapping[str, str]) -> list[dict[str, str]]:
        """One case row per truth case (mismatch mode) or security (regression mode); mismatch cases first. A
        mismatch case lists its mismatched truth fields (side_a the truth, side_b the library); a regression case
        its report rows (side_a old, side_b new). `truth_sec` maps a truth case_id to its sec_id."""
        groups: dict[tuple[str, str], list[CaseError]] = {}
        for m in mismatches:
            groups.setdefault((MISMATCH, m.case_id), []).append(CaseError(mismatch_key(m), m.field, m.truth,
                                                                          m.library))
        for r in regressions:
            groups.setdefault((REGRESSION, r["sec_id"]), []).append(CaseError(regression_key(r), Field.of(r).name,
                                                                              r["old"], r["new"]))
        out = []
        for (mode, subject), errors in sorted(groups.items(), key=lambda kv: (kv[0][0] != MISMATCH, kv[0][1])):
            sec = truth_sec[subject] if mode == MISMATCH else subject
            ctx = _context(tables, sec)
            out.append({
                "case_id": self.case_id(subject), "mode": mode, "sec_id": sec,
                "ticker": ctx["tickers"].split(";")[-1] if ctx["tickers"] else "",
                "truth_case_id": subject if mode == MISMATCH else "",
                **{c: json.dumps([getattr(e, a) for e in errors])
                   for c, a in zip(_ERROR_CELLS, ("key", "field", "side_a", "side_b"))},
                **ctx})
        return out

    def open(self, truth: str | Path, run: RunSnapshot, base: RunSnapshot, *, report: str | Path) -> Opened:
        """Open the round on `run` against the `base` run (a commit's, `RunSnapshot.at`): rename the truth rows and
        legs that name a renamed security (`regression.id_changes_since`) and commit the truth set; judge the run;
        write the regression report to `report`; keep the errors the ledger has not seen and write them as the
        round's case rows."""
        ts = self.loop.truth_set(truth)
        id_changes = id_changes_since(base, run)
        renamed = ts.rename(id_changes)
        cases = ts.cases
        judged = judge_all(cases, LibraryRows.of(run))
        ts.commit()
        seen = ts.ledger_keys
        rows = build_report(base, run, cases, id_changes)
        write_report(report, rows)
        mismatches = [m for j in judged for m in j.mismatches if mismatch_key(m) not in seen]
        regressions = [r for r in rows if regression_key(r) not in seen]
        case_rows = self._case_rows(mismatches, regressions, run, {c.case_id: c.sec_id for c in cases})
        self.folder.mkdir(parents=True, exist_ok=True)
        _write_csv(self.cases_file, CASE_COLUMNS, case_rows)
        return Opened(self, tuple(mismatches), tuple(regressions), renamed, tuple(case_rows), tuple(rows))

    def close(self, truth: str | Path, run: RunSnapshot, base: RunSnapshot, *, dry_run: bool = False) -> Closed:
        """Close the round: apply its records to the truth set (truth_update's rules; the base run's contract rows,
        the run as the judge reads it, and the placeholders renamed since `base`), turn every known_wrong case that
        now matches the run into pass, and, unless `dry_run`, commit the truth set and write summary.md."""
        cases = self.cases()
        records = self.records()
        ts = self.loop.truth_set(truth)
        renamed = {r["old_sec_id"] for r in id_changes_since(base, run)}
        base_rows = {r["sec_id"]: r for r in base.require("contract_delistings")}
        run.require("contract_delistings")
        lib = LibraryRows.of(run)              # a status flip judges a basket's legs too (sub-plan 5f)
        res = ts.apply_round(cases, records, base_rows, lib, label=self.label, round_no=self.number,
                             report_dir=self.report_dir, renamed=renamed)
        ts.flip(lib)
        closed = Closed(self, len(cases), len(records), tuple(ts.changes), len(ts.settled), tuple(res.pending),
                        dry_run)
        if not dry_run:
            # The truth file, the change log and the ledger move together: all are replaced, or none.
            ts.commit()
            write_atomic(self.summary_file, closed.summary())
        return closed


@dataclass(frozen=True)
class Seeded:
    label: str
    seeded: int
    ledger: Path

    def line(self) -> dict:
        """The script's JSON line."""
        return {"label": self.label, "seeded": self.seeded, "ledger": str(self.ledger)}


@dataclass(frozen=True)
class Opened:
    """An opened round: the new errors, how many truth cells the renames changed, the case rows written and the
    whole regression report."""
    round: Round
    mismatches: tuple[Mismatch, ...]
    regressions: tuple[dict[str, str], ...]
    renamed: int
    cases: tuple[dict[str, str], ...]
    report: tuple[dict[str, str], ...]

    def line(self) -> dict:
        """The script's JSON line, which the workflow reads (`cases`, `mismatches_new`, `regressions_new`)."""
        return {"label": self.round.label, "round": self.round.number, "mismatches_new": len(self.mismatches),
                "regressions_new": len(self.regressions), "renamed": self.renamed,
                "cases": [{"case_id": r["case_id"], "mode": r["mode"], "ticker": r["ticker"]} for r in self.cases],
                "path": str(self.round.cases_file)}


@dataclass(frozen=True)
class Closed:
    """A closed round: its case and record counts, the truth set's change-log rows and ledger rows, and the cases to
    retry (no usable record)."""
    round: Round
    cases: int
    records: int
    changes: tuple[dict[str, str], ...]
    ledger_rows: int
    retry: tuple[str, ...]
    dry_run: bool

    def line(self) -> dict:
        """The script's JSON line."""
        return {"label": self.round.label, "round": self.round.number, "cases": self.cases, "records": self.records,
                "truth_changes": len(self.changes), "ledger_rows": self.ledger_rows, "retry": list(self.retry),
                "dry_run": self.dry_run}

    def summary(self) -> str:
        """The round's summary.md."""
        lines = [f"# Loop {self.round.label}, round {self.round.number}", "",
                 f"- cases: {self.cases}, records: {self.records}", f"- truth changes: {len(self.changes)}",
                 f"- retried next round (no record): {list(self.retry) or 'none'}", "",
                 "| case | field | old | new | reason |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {c['case_id']} | {c['field']} | {c['old']} | {c['new']} | {c['reason']} |" for c in self.changes]
        return "\n".join(lines) + "\n"


# -- the unexplained count ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Unexplained:
    """The regressions the ledger has not settled as right, then one row per regressed security the loop added to
    the truth file as ruling_pending (report rows). `count` is D.unexplained_regressions."""
    rows: tuple[dict[str, str], ...]

    @property
    def count(self) -> int:
        """The securities the rows touch."""
        return len({r["sec_id"] for r in self.rows})

    @property
    def passes(self) -> bool:
        """The sub-plan gate: no unexplained regression."""
        return self.count == 0

    def line(self) -> dict[str, int]:
        """The scorecard line."""
        return {UNEXPLAINED: self.count}


def unexplained(base: RunSnapshot, run: RunSnapshot, cases: Sequence[DiagnosisCase],
                ledger_rows: Sequence[Mapping[str, str]]) -> Unexplained:
    """The regression report of `run` against the `base` run (recomputed, never read from a written report, which can
    be stale), less what the ledger rows explain, plus the truth set's unsettled regressed rows (`cases`)."""
    explained = _explained(ledger_rows)
    left = [dict(r) for r in build_report(base, run, cases) if regression_key(r) not in explained]
    left += [report_row(c.sec_id, "truth", "status", RULING_PENDING, "", c.note) for c in cases
             if pending_regression(c)]
    return Unexplained(tuple(left))

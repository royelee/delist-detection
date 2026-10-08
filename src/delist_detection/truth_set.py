"""The diagnosis truth set as one unit (spec 2026-10-03-diagnosis-truth-fixes, sections 1.1, 1.6 and 1.7): the truth
rows, a basket's legs, the change log and, where a change settles loop errors, the loop's ledger. They are opened
together, validated once, changed through one set of operations and committed together.

Where the files are. data/scorecard.json's "diagnosis" entry names the truth file, relative to the config's folder
(`truth_file_of`; `configured` reads a repository's config). The legs and the change log are named after it
(`legs_path`: `<truth>_legs.csv`; `changes_path`: `<truth>_changes.csv`). The ledger's path is the loop folder's
(`loop_round.Loop.ledger`); its columns (`LEDGER_COLUMNS`) are this module's, like the other files', and what its
keys and outcomes mean is the loop round's (`loop_round`).

Validation, when a set is opened and again before `commit` writes anything:
- each file's header is its columns exactly; a missing file is an empty one;
- every truth row passes `diagnosis_truth.parse_rows`: case ids, sec_ids, shapes, statuses, and the scored cells'
  vocabulary, dates and numbers;
- every leg row passes `diagnosis_truth.parse_legs` and names a case of the truth file;
- a row with a missing or an extra cell is refused. The one exception is a change-log record, which may carry
  cells past its six: the log is history, and each record keeps the bytes it was read with.
Every failure is a DiagnosisTruthError naming the file and line.

The changes:
- `rule(ruling)`: a `Ruling` (a sub-plan's or the controller's) sets cells, and may replace a case's legs, with
  its reason (`tag: why`) and report. It applies to a row its `owner` owns, and it applies once: a cell the change
  log already records this ruling setting is not set again, even after a later change moved it on.
- `correct(correction)`: a reason a ruling stated wrongly, corrected in the case's note and its change-log reasons.
- `rename(id_changes)`: every truth cell and leg that names a renamed security names the security it is now
  (`regression.renamed_to`, the one chain rule).
- `flip(lib)`: every known_wrong case that now matches the run becomes pass.
- `apply_round(...)`: one loop round's diagnoses, by truth_update's rules (`loop_round.Round.close` calls it).
- `settle(ledger_rows)`: ledger rows (a seed).
They are made of four primitives that truth_update's rules also use: `set_cells`, `move_status`, `add_row` and
`settle`.
Every changed cell is one change-log row (case_id, field, old, new, reason, report). A note grows by `; tag: why`,
or takes the text alone when it was empty (`noted`). A change that changes nothing logs nothing.

`commit` writes every file whose content changed, all of them or none (`atomic_io.replace_all_on_success`). A file
nothing changed keeps its bytes. The change log is appended to, and its old records are written back as they were
read."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING

from .atomic_io import replace_all_on_success
from .diagnosis_truth import (COLUMNS, KNOWN_WRONG, LEG_COLUMNS, PASS, DiagnosisCase, DiagnosisTruthError, LibraryRows,
                              judge_all, leg_field, parse_legs, parse_rows)
from .regression import renamed_to

if TYPE_CHECKING:
    from .loop_round import RoundCase
    from .truth_update import RoundResult

CHANGE_COLUMNS = ("case_id", "field", "old", "new", "reason", "report")
LEDGER_COLUMNS = ("key", "kind", "sec_id", "label", "round", "outcome", "report")
CONFIG = Path("data") / "scorecard.json"         # under a repository: names the truth file ("diagnosis")
RENAMED_FIELDS = ("sec_id", "price_sec_id", "successor_sec_id")
RENAME_REASON = "contract/id_changes.csv: the placeholder now holds a FIGI"
NOW_MATCHES = "the library now matches"
_TRUTH, _LEGS, _CHANGES, _LEDGER = "truth", "legs", "changes", "ledger"


def legs_path(truth: str | Path) -> Path:
    """The legs file of the truth file `truth`: `<stem>_legs.csv` beside it."""
    truth = Path(truth)
    return truth.with_name(f"{truth.stem}_legs.csv")


def changes_path(truth: str | Path) -> Path:
    """The change log of the truth file `truth`: `<stem>_changes.csv` beside it."""
    truth = Path(truth)
    return truth.with_name(f"{truth.stem}_changes.csv")


def truth_file_of(config: Mapping, folder: str | Path, where: str = "config") -> Path | None:
    """The truth file a scorecard config names ("diagnosis", relative to `folder`; None when it names none). The
    legs are named after it; a "diagnosis_legs" entry is accepted only when it names that file."""
    name = config.get("diagnosis")
    legs = config.get("diagnosis_legs")
    if not name:
        if legs:
            raise DiagnosisTruthError(f"{where}: diagnosis_legs without a diagnosis truth file")
        return None
    truth = Path(folder) / name
    if legs and Path(folder) / legs != legs_path(truth):
        raise DiagnosisTruthError(f"{where}: diagnosis_legs {legs!r} is not {legs_path(truth).name!r}: the legs are "
                                  "named after the truth file")
    return truth


def configured(repo: str | Path) -> Path:
    """The truth file the repository's data/scorecard.json names. Raises DiagnosisTruthError when the config cannot
    be read or names none."""
    path = Path(repo) / CONFIG
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DiagnosisTruthError(f"{path}: {exc}") from None
    truth = truth_file_of(raw, path.parent, str(path)) if isinstance(raw, dict) else None
    if truth is None:
        raise DiagnosisTruthError(f"{path}: names no diagnosis truth file")
    return truth


def noted(note: str, text: str) -> str:
    """`note` with `text` added: `note; text`, or `text` alone when the note is empty."""
    return f"{note}; {text}" if note else text


def read_ledger(path: str | Path) -> list[dict[str, str]]:
    """The loop's ledger rows (validated: its header, every row whole); a missing file has none."""
    path = Path(path)
    return _read_rows(path, path.read_bytes() if path.exists() else None, LEDGER_COLUMNS)


@dataclass(frozen=True)
class Ruling:
    """One ruling on one truth case: the cells it sets, why, the tag and report its reason cites, and the legs it
    gives the case (None keeps them; a sequence of leg rows without case_id replaces them; empty removes them).
    `owner` is the sub-plan whose rows it applies to: a row whose fixed_by is `owner`, or already the fixed_by the
    ruling sets. None applies to any row. A ruling with no cells and no legs adds its text to the note (a "note"
    change)."""
    case_id: str
    cells: Sequence[tuple[str, str]] = ()
    why: str = ""
    tag: str = ""
    report: str = ""
    legs: Sequence[Mapping[str, str]] | None = None
    owner: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", tuple((str(f), str(v)) for f, v in self.cells))
        if self.legs is not None:
            object.__setattr__(self, "legs", tuple(dict(x) for x in self.legs))

    @property
    def reason(self) -> str:
        return f"{self.tag}: {self.why}"


@dataclass(frozen=True)
class Correction:
    """A reason a ruling stated wrongly: `wrong` becomes `right` in the case's note and in its change-log reasons.
    It adds no change-log row."""
    case_id: str
    wrong: str
    right: str


class _Record:
    """One change-log record: the text it was read with (None once it changed, or for a new row) and its row (None
    for a blank line)."""
    __slots__ = ("raw", "row")

    def __init__(self, raw: str | None, row: dict[str, str] | None):
        self.raw, self.row = raw, row


def _decode(path: Path, data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DiagnosisTruthError(f"{path}: not UTF-8 ({exc})") from None


def _read_rows(path: Path, data: bytes | None, columns: Sequence[str]) -> list[dict[str, str]]:
    if data is None:
        return []
    reader = csv.reader(io.StringIO(_decode(path, data), newline=""))
    header = next(reader, None)
    if tuple(header or ()) != tuple(columns):
        raise DiagnosisTruthError(f"{path}: columns {header} are not {list(columns)}")
    out = []
    for cells in reader:
        if not cells:
            continue                # a blank line holds no row
        if len(cells) != len(columns):
            raise DiagnosisTruthError(f"{path}:{reader.line_num}: {len(cells)} cells, not {len(columns)}")
        out.append(dict(zip(columns, cells)))
    return out


def _read_log(path: Path, data: bytes | None) -> tuple[str, list[_Record]]:
    """The change log's header text and records, each with the text it was read with."""
    if data is None:
        return "", []
    lines: list[str] = []

    def feed() -> Iterable[str]:
        for line in io.StringIO(_decode(path, data), newline=""):
            lines.append(line)
            yield line

    reader = csv.reader(feed())
    header = next(reader, None)
    if tuple(header or ()) != CHANGE_COLUMNS:
        raise DiagnosisTruthError(f"{path}: columns {header} are not {list(CHANGE_COLUMNS)}")
    head, start = "".join(lines), len(lines)
    records = []
    for cells in reader:
        raw = "".join(lines[start:])
        if cells and len(cells) < len(CHANGE_COLUMNS):
            raise DiagnosisTruthError(f"{path}:{start + 1}: {len(cells)} cells, not {len(CHANGE_COLUMNS)}")
        records.append(_Record(raw, dict(zip(CHANGE_COLUMNS, cells)) if cells else None))
        start = len(lines)
    return head, records


def _csv(columns: Sequence[str], rows: Iterable[Mapping[str, str]], header: bool = True) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    if header:
        w.writeheader()
    w.writerows({c: r[c] for c in columns} for r in rows)
    return buf.getvalue()


def _show(legs: Sequence[Mapping[str, str]]) -> str:
    return "; ".join(f"{x['leg']}: {x['ratio']} {x['price_ticker']}" for x in legs)


class TruthSet:
    """The truth rows, legs, change log and (when opened with one) ledger of one truth file (module docstring)."""

    def __init__(self, truth: Path, ledger: Path | None, originals: Mapping[str, bytes | None],
                 rows: list[dict[str, str]], legs: list[dict[str, str]], log_head: str, records: list[_Record],
                 ledger_rows: list[dict[str, str]], force: Collection[str] = ()):
        self.truth, self.ledger = truth, ledger
        self._paths = {_TRUTH: truth, _LEGS: legs_path(truth), _CHANGES: changes_path(truth)}
        if ledger is not None:
            self._paths[_LEDGER] = ledger
        self._originals = dict(originals)
        self._force = set(force)
        self._rows, self._legs, self._log_head, self._records = rows, legs, log_head, records
        self._ledger_rows = ledger_rows
        self._by_case = {r["case_id"]: r for r in rows}
        self._new_log = len(records)                 # records from here on were added since the set was opened
        self._new_ledger = len(ledger_rows)
        self._validate()

    # -- opening ------------------------------------------------------------------------------------------------
    @classmethod
    def open(cls, truth: str | Path, *, ledger: str | Path | None = None) -> TruthSet:
        """The truth set of the truth file `truth`, with the ledger at `ledger` when the changes will settle loop
        errors. A missing file is an empty one. Raises DiagnosisTruthError (module docstring: validation)."""
        truth = Path(truth)
        ledger = None if ledger is None else Path(ledger)
        return cls._read(truth, ledger, None)

    @classmethod
    def new(cls, truth: str | Path, rows: Sequence[Mapping[str, str]] = (), legs: Sequence[Mapping[str, str]] = (),
            *, ledger: str | Path | None = None) -> TruthSet:
        """A truth set whose rows and legs are `rows` and `legs`, not the files': the first truth file (sub-plan
        5-0's build) or a test's. `commit` writes both files whatever they hold; the change log and the ledger are
        read from disk as `open` reads them."""
        truth = Path(truth)

        def whole(given: Sequence[Mapping[str, str]], columns: Sequence[str], where: Path) -> list[dict[str, str]]:
            for r in given:
                missing = [c for c in columns if c not in r]
                if missing:
                    raise DiagnosisTruthError(f"{where}: a row lacks {missing}")
            return [{c: str(r[c]) for c in columns} for r in given]

        return cls._read(truth, None if ledger is None else Path(ledger),
                         (whole(rows, COLUMNS, truth), whole(legs, LEG_COLUMNS, legs_path(truth))))

    @classmethod
    def _read(cls, truth: Path, ledger: Path | None,
              given: tuple[list[dict[str, str]], list[dict[str, str]]] | None) -> TruthSet:
        paths = {_TRUTH: truth, _LEGS: legs_path(truth), _CHANGES: changes_path(truth)}
        if ledger is not None:
            paths[_LEDGER] = ledger
        originals = {k: p.read_bytes() if p.exists() else None for k, p in paths.items()}
        if given is None:
            rows = _read_rows(truth, originals[_TRUTH], COLUMNS)
            legs = _read_rows(paths[_LEGS], originals[_LEGS], LEG_COLUMNS)
            force: tuple[str, ...] = ()
        else:
            (rows, legs), force = given, (_TRUTH, _LEGS)
        head, records = _read_log(paths[_CHANGES], originals[_CHANGES])
        ledger_rows = _read_rows(ledger, originals[_LEDGER], LEDGER_COLUMNS) if ledger is not None else []
        return cls(truth, ledger, originals, rows, legs, head, records, ledger_rows, force)

    def _validate(self) -> list[DiagnosisCase]:
        legs = parse_legs(self._legs, str(self._paths[_LEGS]))
        cases = parse_rows(self._rows, str(self.truth), legs)
        unknown = sorted(set(legs) - {c.case_id for c in cases})
        if unknown:
            raise DiagnosisTruthError(f"{self._paths[_LEGS]}: legs for unknown case(s) {unknown}")
        return cases

    # -- reading ------------------------------------------------------------------------------------------------
    @property
    def cases(self) -> list[DiagnosisCase]:
        """Every case as it stands, with its legs (validated)."""
        return self._validate()

    @property
    def rows(self) -> list[dict[str, str]]:
        """The truth rows as they stand (copies)."""
        return [dict(r) for r in self._rows]

    @property
    def legs(self) -> list[dict[str, str]]:
        """The leg rows as they stand (copies)."""
        return [dict(r) for r in self._legs]

    def row(self, case_id: str) -> dict[str, str] | None:
        """One case's truth row (a copy), or None."""
        r = self._by_case.get(case_id)
        return None if r is None else dict(r)

    @property
    def changes(self) -> list[dict[str, str]]:
        """The change-log rows added since the set was opened."""
        return [dict(rec.row) for rec in self._records[self._new_log:] if rec.row is not None]

    @property
    def ledger_keys(self) -> set[str]:
        """Every ledger key, read or settled since."""
        return {r["key"] for r in self._ledger_rows}

    @property
    def settled(self) -> list[dict[str, str]]:
        """The ledger rows settled since the set was opened."""
        return [dict(r) for r in self._ledger_rows[self._new_ledger:]]

    # -- the primitives -----------------------------------------------------------------------------------------
    def _case(self, case_id: str) -> dict[str, str]:
        r = self._by_case.get(case_id)
        if r is None:
            raise DiagnosisTruthError(f"{self.truth}: no case {case_id!r}")
        return r

    def _log(self, case_id: str, name: str, old: str, new: str, reason: str, report: str) -> None:
        self._records.append(_Record(None, dict(case_id=case_id, field=name, old=old, new=new, reason=reason,
                                                report=report)))

    def set_cells(self, case_id: str, cells: Iterable[tuple[str, str]], *, reason: str, report: str = "") -> int:
        """Set each cell that differs, one change-log row each. Returns how many cells changed."""
        r = self._case(case_id)
        n = 0
        for name, value in cells:
            if name not in r:
                raise DiagnosisTruthError(f"{self.truth}: no column {name!r}")
            if r[name] != value:
                self._log(case_id, name, r[name], value, reason, report)
                r[name] = value
                n += 1
        return n

    def move_status(self, case_id: str, status: str, *, reason: str, report: str = "", note: str | None = None) -> int:
        """Move a case to `status` (pass or ruling_pending, which name no sub-plan: fixed_by is cleared), one
        change-log row for the status; `note` is added to the case's note. Returns 1, or 0 when it is there."""
        if status == KNOWN_WRONG:
            raise ValueError("a known_wrong case needs its fixed_by: set both cells")
        r = self._case(case_id)
        if r["status"] == status:
            return 0
        self._log(case_id, "status", r["status"], status, reason, report)
        r["status"], r["fixed_by"] = status, ""
        if note:
            r["note"] = noted(r["note"], note)
        return 1

    def add_row(self, row: Mapping[str, str], *, reason: str, report: str = "") -> None:
        """Add one truth row (every COLUMNS cell), logged as `(row)` added with its status."""
        missing = [c for c in COLUMNS if c not in row]
        if missing:
            raise DiagnosisTruthError(f"{self.truth}: a new row lacks {missing}")
        if row["case_id"] in self._by_case:
            raise DiagnosisTruthError(f"{self.truth}: case_id {row['case_id']!r} is repeated")
        r = {c: row[c] for c in COLUMNS}
        self._rows.append(r)
        self._by_case[r["case_id"]] = r
        self._log(r["case_id"], "(row)", "", f"added ({r['status']})", reason, report)

    def settle(self, ledger_rows: Iterable[Mapping[str, str]]) -> None:
        """Add ledger rows (every LEDGER_COLUMNS cell)."""
        if self.ledger is None:
            raise ValueError("this truth set was opened without a ledger")
        for r in ledger_rows:
            missing = [c for c in LEDGER_COLUMNS if c not in r]
            if missing:
                raise DiagnosisTruthError(f"{self.ledger}: a new row lacks {missing}")
            self._ledger_rows.append({c: r[c] for c in LEDGER_COLUMNS})

    # -- the changes --------------------------------------------------------------------------------------------
    def rule(self, ruling: Ruling) -> int:
        """Apply one ruling (`Ruling`). Returns how many change-log rows it added: 0 for a row its owner does not
        own, or a ruling already applied."""
        cid = ruling.case_id
        r = self._case(cid)
        owned = ruling.owner is None or r["fixed_by"] == ruling.owner or ("fixed_by", r["fixed_by"]) in ruling.cells
        if not owned:
            return 0                # a later ruling moved the row on: leave it
        reason = ruling.reason
        done = {(rec.row["field"], rec.row["new"]) for rec in self._records
                if rec.row is not None and rec.row["case_id"] == cid and rec.row["reason"] == reason}
        n = self.set_cells(cid, [c for c in ruling.cells if c not in done], reason=reason,
                           report=ruling.report)
        if ruling.legs is not None:
            old = [x for x in self._legs if x["case_id"] == cid]
            want = [{"case_id": cid, **{c: str(x[c]) for c in LEG_COLUMNS if c != "case_id"}} for x in ruling.legs]
            if old != want and ("legs", _show(want)) not in done:
                self._log(cid, "legs", _show(old), _show(want), reason, ruling.report)
                self._legs = [x for x in self._legs if x["case_id"] != cid] + want
                n += 1
        if not ruling.cells and ruling.legs is None and ("note", ruling.why) not in done:
            self._log(cid, "note", "", ruling.why, reason, ruling.report)
            n += 1
        if n:
            r["note"] = noted(r["note"], reason)
        return n

    def correct(self, correction: Correction) -> int:
        """Correct a reason in the case's note and change-log reasons. Returns how many places changed."""
        r = self._case(correction.case_id)
        n = 0
        if correction.wrong in r["note"]:
            r["note"] = r["note"].replace(correction.wrong, correction.right)
            n += 1
        for rec in self._records:
            row = rec.row
            if row is not None and row["case_id"] == correction.case_id and correction.wrong in row["reason"]:
                rec.row["reason"] = rec.row["reason"].replace(correction.wrong, correction.right)
                rec.raw = None
                n += 1
        return n

    def rename(self, id_changes: Sequence[Mapping[str, str]]) -> int:
        """Every truth row's sec_id, price_sec_id and successor_sec_id, and every leg's price_sec_id, that names a
        renamed security (`id_changes`, contract/id_changes.csv rows) names the security it is now: a chain of
        renames is followed to its end (`regression.renamed_to`). Identity follows the FIGI (R2); the case_id stays.
        Returns how many cells changed."""
        moved = renamed_to(id_changes)
        n = 0
        for r in self._rows:
            n += self.set_cells(r["case_id"], [(f, moved[r[f]]) for f in RENAMED_FIELDS if r[f] in moved],
                                reason=RENAME_REASON)
        for leg in self._legs:
            if leg["price_sec_id"] in moved:
                self._log(leg["case_id"], leg_field(int(leg["leg"]), "price_sec_id"), leg["price_sec_id"],
                          moved[leg["price_sec_id"]], RENAME_REASON, "")
                leg["price_sec_id"] = moved[leg["price_sec_id"]]
                n += 1
        return n

    def flip(self, lib: LibraryRows) -> int:
        """Every known_wrong case that now matches the run (`lib`) becomes pass. Returns how many did."""
        matching = {j.case.case_id for j in judge_all(self.cases, lib) if j.ok}
        return sum(self.move_status(r["case_id"], PASS, reason=NOW_MATCHES) for r in list(self._rows)
                   if r["status"] == KNOWN_WRONG and r["case_id"] in matching)

    def apply_round(self, cases: Sequence[RoundCase], records: Mapping[str, Mapping],
                    base_contract: Mapping[str, Mapping[str, str]], run: LibraryRows, *, label: str, round_no: int,
                    report_dir: str, renamed: Collection[str] = ()) -> RoundResult:
        """One loop round's diagnoses (`truth_update.apply_round`'s rules), on this set and its ledger: `cases` the
        round's cases, `records` the agents' records by case_id, `base_contract` the base run's contract rows by
        sec_id, `run` the run as the judge reads it. Returns the rows as they now stand, the round's change-log and
        ledger rows, and the cases to retry."""
        from . import truth_update      # local import: truth_update imports loop_round, which imports this module
        log0, ledger0 = len(self._records), len(self._ledger_rows)
        pending = truth_update.apply_round(self, cases, records, base_contract, run, label=label, round_no=round_no,
                                           report_dir=report_dir, renamed=renamed)
        return truth_update.RoundResult(self.rows,
                                        [dict(rec.row) for rec in self._records[log0:] if rec.row is not None],
                                        [dict(r) for r in self._ledger_rows[ledger0:]], pending)

    # -- committing ---------------------------------------------------------------------------------------------
    def _log_text(self) -> str:
        head = self._log_head or (_csv(CHANGE_COLUMNS, []) if self._records else "")
        out = [head]
        for rec in self._records:
            text = rec.raw if rec.raw is not None else _csv(CHANGE_COLUMNS, [rec.row], header=False)
            if out[-1] and not out[-1].endswith(("\n", "\r")):
                out.append("\n")
            out.append(text)
        return "".join(out)

    def commit(self) -> list[Path]:
        """Validate the set, then write every file whose content changed, all together or none. Returns the paths
        written."""
        self._validate()
        texts = {_TRUTH: _csv(COLUMNS, self._rows), _LEGS: _csv(LEG_COLUMNS, self._legs), _CHANGES: self._log_text()}
        held = {_TRUTH: self._rows, _LEGS: self._legs, _CHANGES: self._records}
        if self.ledger is not None:
            texts[_LEDGER], held[_LEDGER] = _csv(LEDGER_COLUMNS, self._ledger_rows), self._ledger_rows
        data = {k: t.encode("utf-8") for k, t in texts.items()}
        write = [k for k in texts if k in self._force or (
            data[k] != self._originals[k] if self._originals[k] is not None else bool(held[k]))]
        with replace_all_on_success([self._paths[k] for k in write]) as tmps:
            for tmp, k in zip(tmps, write):
                tmp.write_bytes(data[k])
        for k in write:
            self._originals[k] = data[k]
        self._force.clear()
        return [self._paths[k] for k in write]

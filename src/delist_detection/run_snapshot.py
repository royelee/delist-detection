"""The run snapshot: every table one run wrote, read once, and the manifest fields measurement reads (the run date
and stage 9g's continuation readings). The scorecard, both judges (truth.py's golden judge through the lifecycle
view, and diagnosis_truth's), the verdicts, the contract, the regression diff and the diagnosis loop read a run only
through it.

Three adapters fill one interface:

- `RunSnapshot.read(out_dir)`: an output folder;
- `RunSnapshot.at(repo, rev, out_dir)`: that folder as commit `rev` of the git repository `repo` holds it (a
  sub-plan's base run, for the regression report);
- `RunSnapshot.of(tables, as_of=, continuations=)`: the rows the pipeline is about to write (stages 10f to 10h), as
  store.read_table would read them back (every cell formatted, rows sorted by key: `store.formatted`).

Every `store.TABLES` name is an attribute holding that table's string rows. A table is read the first time a reader
asks for it, and only once; `has(name)` asks whether the run wrote it, `require(name)` reads one a reader cannot do
without. A table added to store.TABLES is an attribute here with nothing more to write.

The older-schema rule (the one place it lives):

- A table newer than the library's first eight (`FIRST_TABLES`) reads as None when the run did not write it: a run
  before reset-2 has no uncertain.csv, one before reset-3 no contract, one before schema 3 no
  contract/payout_legs.csv. One of the first eight that is missing raises SnapshotError.
- A file must have its table's columns (store.TABLES), in their order. The one older layout read is
  contract/delistings.csv of contract schema 1, before the payout rule (`CONTRACT_SCHEMA_1`): it reads as None, as
  for a run before schema 2. Any other header raises SnapshotError naming the file and the columns it lacks or adds.

The manifest (run_manifest.json; the in-memory adapter is given its two fields): `as_of` is the run date (today when
the source holds no manifest, as for a folder of tables a test wrote); `continuations` is what stage 9g read for each
continuation, by (sec_id, delist_date), from the manifest's `continuation_filings` entries (none when there is no
manifest or no such entry). `continuation_entries` writes those entries, so their format lives beside its reader:
the verdicts recomputed from a written folder are the run's own.

Pure, apart from reading files and running `git show`."""
from __future__ import annotations

import csv
import io
import json
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path

from . import store
from .exit_kind import ContinuationReading
from .manifest import MANIFEST_NAME

Rows = list[dict[str, str]]
Key = tuple[str, str]                    # a delisting's (sec_id, delist_date)

FIRST_TABLES = frozenset({"securities", "ticker_history", "cusip_history", "delistings", "payouts", "review",
                          "review_summary", "observation_map"})
# contract/delistings.csv as schema 1 wrote it: the columns before the payout rule (schema 2 appended the rest)
CONTRACT_SCHEMA_1 = store.CONTRACT_DELISTINGS_COLUMNS[:store.CONTRACT_DELISTINGS_COLUMNS.index("value_rule")]
_BEFORE_PAYOUT_RULE = "a contract before schema 2 (no payout rule)"


class SnapshotError(ValueError):
    """A run's table or manifest that cannot be read; the message names the file (or the commit and path)."""


class _Absent:
    """Why a source holds no rows for a table: the file is missing, or it has the older layout read as None."""

    def __init__(self, why: str) -> None:
        self.why = why


_MISSING = _Absent("missing")


def _parse(name: str, text: str, where: str) -> Rows | _Absent:
    """One table's rows from its CSV text, under the older-schema rule's column check (module docstring)."""
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = tuple(reader.fieldnames or ())
    columns = store.TABLES[name].columns
    if header == columns:
        return list(reader)
    if name == "contract_delistings" and header == CONTRACT_SCHEMA_1:
        return _Absent(_BEFORE_PAYOUT_RULE)
    missing = [c for c in columns if c not in header]
    unknown = [c for c in header if c not in columns]
    problems = ([f"missing column(s) {', '.join(missing)}"] if missing else []) + \
               ([f"unknown column(s) {', '.join(unknown)}"] if unknown else [])
    raise SnapshotError(f"{where}: {'; '.join(problems) or 'columns out of order'} (table {name!r})")


class _Folder:
    """An output folder."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir

    def where(self, name: str) -> str:
        return str(store.table_path(self.out_dir, name))

    def rows(self, name: str) -> Rows | _Absent:
        path = store.table_path(self.out_dir, name)
        if not path.exists():
            return _MISSING
        return _parse(name, path.read_bytes().decode("utf-8"), str(path))

    def manifest(self) -> tuple[str | None, str]:
        path = self.out_dir / MANIFEST_NAME
        return (path.read_bytes().decode("utf-8") if path.exists() else None), str(path)


class _Commit:
    """An output folder as one commit of a git repository holds it."""

    def __init__(self, repo: str | Path, rev: str, out_dir: str | Path) -> None:
        self.root = Path(repo).resolve()
        try:
            self.rel = Path(out_dir).resolve().relative_to(self.root)
        except ValueError:
            raise SnapshotError(f"{Path(out_dir).resolve()}: not inside the repository {self.root}") from None
        done = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
                              capture_output=True, text=True)
        if done.returncode != 0:
            raise SnapshotError(f"{rev}: not a commit of {self.root}")
        self.rev = rev

    def _path(self, name: str) -> str:
        return (self.rel / store.table_path(Path(), name)).as_posix()

    def where(self, name: str) -> str:
        return f"{self.rev}:{self._path(name)}"

    def _show(self, rel: str) -> str | None:
        done = subprocess.run(["git", "-C", str(self.root), "show", f"{self.rev}:{rel}"], capture_output=True)
        return done.stdout.decode("utf-8") if done.returncode == 0 else None

    def rows(self, name: str) -> Rows | _Absent:
        text = self._show(self._path(name))
        return _MISSING if text is None else _parse(name, text, self.where(name))

    def manifest(self) -> tuple[str | None, str]:
        rel = (self.rel / MANIFEST_NAME).as_posix()
        return self._show(rel), f"{self.rev}:{rel}"


class _Memory:
    """The rows the pipeline is about to write, formatted as they would be read back."""

    def __init__(self, tables: Mapping[str, Iterable[Mapping[str, object]]]) -> None:
        unknown = sorted(set(tables) - set(store.TABLES))
        if unknown:
            raise SnapshotError(f"no such table(s) {unknown}")
        self.tables = {name: list(rows) for name, rows in tables.items()}   # later changes to the run's lists stay out

    def where(self, name: str) -> str:
        return f"the run's {store.table_path(Path(), name).as_posix()}"

    def rows(self, name: str) -> Rows | _Absent:
        return store.formatted(name, self.tables[name]) if name in self.tables else _MISSING

    def manifest(self) -> tuple[str | None, str]:
        return None, "the run's manifest fields"


class RunSnapshot:
    """Every table one run wrote, and its run date and stage 9g's readings (module docstring). Build one with
    `read`, `at` or `of`; each `store.TABLES` name is an attribute."""

    def __init__(self, source, as_of: date | None = None,
                 continuations: Mapping[Key, ContinuationReading] | None = None) -> None:
        self._source = source
        self._tables: dict[str, Rows | _Absent] = {}
        self._as_of = as_of
        self._continuations = None if continuations is None else dict(continuations)
        self._manifest: dict | None = None
        self._manifest_where = ""
        self._manifest_read = False

    # -- the three adapters -----------------------------------------------------------------------------------
    @classmethod
    def read(cls, out_dir: str | Path) -> RunSnapshot:
        """The run written under the output folder `out_dir`."""
        path = Path(out_dir)
        if not path.is_dir():
            raise SnapshotError(f"{path}: no such output folder")
        return cls(_Folder(path))

    @classmethod
    def at(cls, repo: str | Path, rev: str, out_dir: str | Path) -> RunSnapshot:
        """The run under `out_dir` as commit `rev` of the git repository `repo` holds it (`out_dir` lies inside
        `repo`). Raises SnapshotError for a folder outside the repository or a revision that is not a commit."""
        return cls(_Commit(repo, rev, out_dir))

    @classmethod
    def of(cls, tables: Mapping[str, Iterable[Mapping[str, object]]], *, as_of: date | None = None,
           continuations: Mapping[Key, ContinuationReading] | None = None) -> RunSnapshot:
        """The rows the pipeline is about to write (`tables`: store.TABLES name -> rows; a name it lacks is a table
        the run does not write), with the run date and stage 9g's readings (`exit_kind.ContinuationReading` by
        (sec_id, delist_date))."""
        return cls(_Memory(tables), as_of, {} if continuations is None else continuations)

    # -- the tables ---------------------------------------------------------------------------------------------
    def _load(self, name: str) -> Rows | _Absent:
        if name not in store.TABLES:
            raise KeyError(f"no table {name!r}")
        if name not in self._tables:
            self._tables[name] = self._source.rows(name)
        return self._tables[name]

    def table(self, name: str) -> Rows | None:
        """Table `name`'s rows: None for a later table the run did not write; a missing first-eight table raises
        SnapshotError."""
        got = self._load(name)
        if isinstance(got, _Absent):
            if name in FIRST_TABLES:
                raise SnapshotError(f"{self._source.where(name)}: {got.why}")
            return None
        return got

    def has(self, name: str) -> bool:
        """Whether the run wrote table `name` (in a layout the snapshot reads)."""
        return not isinstance(self._load(name), _Absent)

    def require(self, name: str) -> Rows:
        """Table `name`'s rows, for a reader that cannot do without it: SnapshotError (naming the file and why)
        when the run did not write it."""
        got = self._load(name)
        if isinstance(got, _Absent):
            raise SnapshotError(f"{self._source.where(name)}: {got.why}")
        return got

    # -- the manifest -------------------------------------------------------------------------------------------
    def _manifest_fields(self) -> dict | None:
        """run_manifest.json as a dict, read once; None when the source holds none."""
        if not self._manifest_read:
            text, self._manifest_where = self._source.manifest()
            self._manifest_read = True
            if text is not None:
                try:
                    data = json.loads(text)
                except ValueError as exc:
                    raise SnapshotError(f"{self._manifest_where}: not JSON ({exc})") from None
                if not isinstance(data, dict):
                    raise SnapshotError(f"{self._manifest_where}: the top level is not an object")
                self._manifest = data
        return self._manifest

    @property
    def as_of(self) -> date:
        """The run date: the manifest's `as_of` (given to `of`); today when the run recorded none."""
        if self._as_of is None:
            manifest = self._manifest_fields()
            if manifest is None:
                self._as_of = date.today()
            else:
                try:
                    self._as_of = date.fromisoformat(manifest["as_of"])
                except (KeyError, TypeError, ValueError):
                    raise SnapshotError(f"{self._manifest_where}: no as_of date") from None
        return self._as_of

    @property
    def continuations(self) -> Mapping[Key, ContinuationReading]:
        """What stage 9g read for each continuation, by (sec_id, delist_date): the filing that confirms it or the
        doubt its registrant's own filings raise (`exit_kind.ContinuationReading`)."""
        if self._continuations is None:
            entries = (self._manifest_fields() or {}).get("continuation_filings", [])
            self._continuations = continuation_readings(entries, self._manifest_where)
        return self._continuations


class _Table:
    """One store.TABLES table as an attribute of the snapshot (`RunSnapshot.table`)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.__doc__ = f"{name}'s rows (RunSnapshot.table)"

    def __get__(self, snap: RunSnapshot | None, owner: type | None = None):
        return self if snap is None else snap.table(self.name)


for _name in store.TABLES:
    setattr(RunSnapshot, _name, _Table(_name))
del _name


def continuation_entries(readings: Mapping[Key, ContinuationReading]) -> list[dict[str, str]]:
    """Stage 9g's readings as run_manifest.json's `continuation_filings` entries, in key order: a confirmation is
    {sec_id, delist_date, filing}; a reading with a doubt carries `doubt` too (its filing blank)."""
    out = []
    for (sec_id, day), r in sorted(readings.items()):
        if r.filing or r.doubt:
            entry = {"sec_id": sec_id, "delist_date": day, "filing": r.filing}
            if r.doubt:
                entry["doubt"] = r.doubt
            out.append(entry)
    return out


def continuation_readings(entries: Sequence[Mapping[str, str]], where: str = "continuation_filings"
                          ) -> dict[Key, ContinuationReading]:
    """`continuation_entries`' entries read back, by (sec_id, delist_date). Raises SnapshotError on an entry that
    names no delisting."""
    out: dict[Key, ContinuationReading] = {}
    if not isinstance(entries, list):
        raise SnapshotError(f"{where}: continuation_filings is not a list")
    for e in entries:
        if not isinstance(e, Mapping) or not e.get("sec_id") or not e.get("delist_date"):
            raise SnapshotError(f"{where}: a continuation_filings entry names no delisting: {e!r}")
        out[(e["sec_id"], e["delist_date"])] = ContinuationReading(filing=e.get("filing", ""),
                                                                   doubt=e.get("doubt", ""))
    return out

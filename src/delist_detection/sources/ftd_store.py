"""A fails-to-deliver ZIP, parsed once into a SQLite file and read by symbol and CUSIP.

`FtdClient.rows` used to read a ZIP's text again for every ask: a run asks 70 times or more, each over
hundreds of files, and parsing the same 25 million lines each time was most of a warm run. Here a ZIP is
parsed once, into `parsed/<zip name>.sqlite` beside it, and an ask reads only the rows of the keys it names
through the file's indexes. A row is read back exactly as `ftd.parse_ftd_lines` returns it, in the order the
ZIP holds it (the member order, then the line order), which `FtdIndex` depends on when two rows tie on
(date, CUSIP, symbol).

The file is a cache, never a source: it records the ZIP's size and modification time, the store's version and
a digest of what the line rule makes of a set of probe lines, and is built again when any of them differs (a ZIP
downloaded again, a change to the parsed form, a line rule that reads the probe lines differently). It is written
through `atomic_io.write_atomic_with`, so a reader sees the old file or the complete new one, and a killed
writer's temp file is cleaned up with the others.

One file holds one ZIP: the description, symbol and CUSIP texts once each (`descr`, `sym`, `cus`), and a row
as small integers into them. A price that SQLite would not give back unchanged (NaN, which it stores as NULL,
and -0.0, which it stores as 0.0) is kept as text.
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path
from sys import intern

from .atomic_io import clean_orphan_temps, write_atomic_with
from ..vocabulary.identifiers import normalize_ticker

_log = logging.getLogger(__name__)

# Raise this for a change to the parsed form, or to the line rule that `_RULE_PROBES` do not show.
STORE_VERSION = 1
_CHUNK = 500                  # keys per `IN (...)`: well under SQLite's variable limit

_ROW_SELECT = ("SELECT r.rowid, r.day, c.text, s.text, d.text, r.price FROM rows r "
               "JOIN cus c ON c.id = r.cus JOIN sym s ON s.id = r.sym JOIN descr d ON d.id = r.descr")


def store_path(zip_path: Path) -> Path:
    """Where the parsed copy of the ZIP at `zip_path` lives."""
    return zip_path.parent / "parsed" / f"{zip_path.name}.sqlite"


# Lines that exercise each part of the line rule (`split_line`, and `normalize_ticker` inside it): separators and
# case in the symbol, a lower-case CUSIP, a "|" and latin-1 text in the description, every price shape, and the
# lines the rule drops.
_RULE_PROBES = (
    "20240102|00206R102|T|500|AT&T INC COM|16.78",
    "20240102|00206r102| brk.b |500|BERKSHIRE | CLASS B |nan",
    "20240103|037833100|BF/A|10|BROWN FORMAN|-0.0",
    "20240103|037833100|ZZ ZZ|10|CAF\xc9 \xb2 LTD|",
    "20240103|037833100|aapl|10|APPLE INC|1e400",
    "20240104|G0000Z000|A..B|1|X\ty|3.5\r\n",
    "2024010|BADDATE|X|1|SHORT DATE|1.0",
    "20240104|SHORT|X|1",
    "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE",
)


def _rule_digest() -> str:
    """What the line rule makes of `_RULE_PROBES`, as a short digest: a store holds the rule's output, not the text,
    so one built under a rule that reads these lines differently is out of date."""
    return hashlib.sha1(repr([split_line(p) for p in _RULE_PROBES]).encode()).hexdigest()[:12]


def _fingerprint(zip_path: Path) -> str:
    st = zip_path.stat()
    return f"{STORE_VERSION}:{_rule_digest()}:{st.st_size}:{st.st_mtime_ns}"


def _connect(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)


def _is_current(db: Path, fingerprint: str) -> bool:
    """Whether `db` is a complete store built from a ZIP with this fingerprint. A missing, cut-off or foreign file
    is not."""
    if not db.is_file():
        return False
    try:
        con = _connect(db)
        try:
            got = con.execute("SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False
    return got is not None and got[0] == fingerprint


def ensure(zip_path: Path) -> Path:
    """The parsed copy of the ZIP at `zip_path`, built first when there is none or it is out of date. Raises
    `zipfile.BadZipFile` for a ZIP that cannot be read, leaving any earlier copy as it was."""
    db = store_path(zip_path)
    fingerprint = _fingerprint(zip_path)
    if not _is_current(db, fingerprint):
        db.parent.mkdir(parents=True, exist_ok=True)
        clean_orphan_temps(db.parent)         # a killed run's cut-off build
        write_atomic_with(db, lambda tmp: _build(zip_path, tmp, fingerprint))
    return db


def _price_cell(price: float | None) -> float | str | None:
    if price is not None and (price != price or (price == 0 and math.copysign(1.0, price) < 0)):
        return repr(price)
    return price


def split_line(line: str) -> tuple[str, str, str, str, float | None] | None:
    """One fails-to-deliver text line as its fields, (ISO date, CUSIP, symbol, description, price); None for a header,
    a trailer or a malformed line (fewer than six fields, or a first field that is not eight digits). The one place
    the line format is read: `ftd.parse_ftd_lines` and the store's build both use it."""
    parts = line.rstrip("\r\n").split("|")
    if len(parts) < 6:
        return None
    d = parts[0].strip()
    if len(d) != 8 or not d.isdigit():
        return None
    try:
        price: float | None = float(parts[-1].strip())
    except ValueError:
        price = None
    return (f"{d[:4]}-{d[4:6]}-{d[6:]}", parts[1].strip().upper(), normalize_ticker(parts[2]),
            "|".join(parts[4:-1]).strip(), price)


def _build(zip_path: Path, dest: Path, fingerprint: str) -> None:
    """Parse every member of the ZIP into a new store at `dest`, every well-formed line (`split_line`) and no filter."""
    con = sqlite3.connect(dest)
    try:
        con.executescript("""
            PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE descr (id INTEGER PRIMARY KEY, text TEXT);
            CREATE TABLE sym (id INTEGER PRIMARY KEY, text TEXT);
            CREATE TABLE cus (id INTEGER PRIMARY KEY, text TEXT);
            CREATE TABLE rows (day TEXT, cus INTEGER, sym INTEGER, descr INTEGER, price);
        """)
        ids: dict[str, dict[str, int]] = {"descr": {}, "sym": {}, "cus": {}}

        def key(table: str, text: str) -> int:
            known = ids[table]
            got = known.get(text)
            if got is None:
                got = known[text] = len(known) + 1
            return got

        with zipfile.ZipFile(zip_path) as z:
            # Every file member is read, whatever its name: from 2022-05 on the SEC
            # ships one member without an extension ("cnsfails202401a").
            for info in z.infolist():
                if info.is_dir():
                    continue
                batch: list[tuple] = []
                with z.open(info) as fh:
                    for line in io.TextIOWrapper(fh, encoding="latin-1"):
                        fields = split_line(line)
                        if fields is None:
                            continue
                        day, cusip, symbol, description, price = fields
                        batch.append((day, key("cus", cusip), key("sym", symbol), key("descr", description),
                                      _price_cell(price)))
                if not batch:
                    _log.warning(f"{zip_path.name}: member {info.filename!r} holds no fails-to-deliver rows; skipped")
                con.executemany("INSERT INTO rows VALUES (?, ?, ?, ?, ?)", batch)
        for table, known in ids.items():
            con.executemany(f"INSERT INTO {table} VALUES (?, ?)", ((i, t) for t, i in known.items()))
        con.executescript("CREATE INDEX rows_sym ON rows (sym); CREATE INDEX rows_cus ON rows (cus); "
                          "CREATE UNIQUE INDEX sym_text ON sym (text); CREATE UNIQUE INDEX cus_text ON cus (text);")
        con.execute("INSERT INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.commit()
    finally:
        con.close()


def _row(rec: tuple) -> tuple[str, str, str, str, float | None]:
    """A stored row as the fields of an `ftd.FtdRow`: (date, CUSIP, symbol, description, price). Each text is
    interned: a run holds the same few thousand dates, CUSIPs and symbols and a few hundred thousand descriptions
    in millions of rows."""
    price = rec[5]
    return (intern(rec[1]), intern(rec[2]), intern(rec[3]), intern(rec[4]),
            float(price) if isinstance(price, str) else price)


def select(db: Path, *, symbols: set[str] | None = None,
           cusips: set[str] | None = None) -> Iterator[tuple[str, str, str, str, float | None]]:
    """The rows of the store at `db` (the fields of an `ftd.FtdRow`), as `ftd.parse_ftd_lines` filters them: those whose symbol is in `symbols` or
    whose CUSIP is in `cusips` (each filter on its own when only one is given), every row when neither is; in the
    ZIP's order."""
    con = _connect(db)
    try:
        if symbols is None and cusips is None:
            yield from (_row(rec) for rec in con.execute(f"{_ROW_SELECT} ORDER BY r.rowid"))
            return
        hits: dict[int, tuple] = {}
        for column, table, wanted in (("sym", "sym", symbols), ("cus", "cus", cusips)):
            keys = sorted(wanted or ())
            for i in range(0, len(keys), _CHUNK):
                chunk = keys[i:i + _CHUNK]
                ids = [r[0] for r in con.execute(
                    f"SELECT id FROM {table} WHERE text IN ({','.join('?' * len(chunk))})", chunk)]
                for j in range(0, len(ids), _CHUNK):
                    part = ids[j:j + _CHUNK]
                    for rec in con.execute(f"{_ROW_SELECT} WHERE r.{column} IN ({','.join('?' * len(part))})", part):
                        hits[rec[0]] = rec
        yield from (_row(hits[rowid]) for rowid in sorted(hits))
    finally:
        con.close()

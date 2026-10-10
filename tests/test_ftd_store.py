"""The parsed copy of a fails-to-deliver ZIP gives back what `parse_ftd_lines` reads from it."""
from __future__ import annotations

import io
import math
import os
import zipfile

import pytest

from delist_detection.sources import ftd_store
from delist_detection.sources.atomic_io import write_atomic_with
from delist_detection.sources.ftd import FtdRow, parse_ftd_lines
from delist_detection.vocabulary.identifiers import normalize_ticker

HEADER = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
ODD = (HEADER
       + "20240102|00206R102|T|500|AT&T INC COM|16.78\n"
       + "20240102|00206r102|brk.b|500|BERKSHIRE | CLASS B |nan\n"        # lower case, separator, a "|" in the text, NaN
       + "20240103|037833100|AAPL|10|APPLE INC|-0.0\n"
       + "20240103|037833100|AAPL|10|APPLE INC|\n"                          # no price
       + "20240103|037833100|AAPL|10|APPLE INC|1e400\n"                     # infinity
       + "20240104|G0000Z000|ZZ ZZ|1|CAF\xc9 \xb2 LTD|3.5\r\n"              # latin-1 text, a space in the symbol
       + "2024010|BADDATE|X|1|SHORT DATE|1.0\n"
       + "20240104|SHORT|X|1\n"
       + "Trailer record count 7\n"
       + "20240102|00206R102|T|700|AT&T INC COM|16.78\n")                   # the same row again: kept, as the parser does


def _write_zip(path, members: dict[str, str]) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in members.items():
            z.writestr(name, text.encode("latin-1"))
    path.write_bytes(buf.getvalue())


def _reference_lines(lines, *, symbols=None, cusips=None):
    """The line rule as `parse_ftd_lines` first wrote it, kept here whole so the store and the shared `split_line`
    are checked against an independent copy, not against each other."""
    for line in lines:
        parts = line.rstrip("\r\n").split("|")
        if len(parts) < 6:
            continue
        d = parts[0].strip()
        if len(d) != 8 or not d.isdigit():
            continue
        cusip = parts[1].strip().upper()
        symbol = normalize_ticker(parts[2])
        if symbols is not None or cusips is not None:
            if not ((symbols is not None and symbol in symbols) or (cusips is not None and cusip in cusips)):
                continue
        try:
            price = float(parts[-1].strip())
        except ValueError:
            price = None
        yield FtdRow(f"{d[:4]}-{d[4:6]}-{d[6:]}", cusip, symbol, "|".join(parts[4:-1]).strip(), price)


def _old(path, **filters):
    rows = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.is_dir():
                with z.open(info) as fh:
                    rows.extend(_reference_lines(io.TextIOWrapper(fh, encoding="latin-1"), **filters))
    return rows


def _same(got, want) -> bool:
    """Row lists equal, NaN prices and the sign of a zero price included."""
    return len(got) == len(want) and all(
        (g.date, g.cusip, g.symbol, g.description) == (w.date, w.cusip, w.symbol, w.description)
        and (g.price is None) == (w.price is None)
        and (g.price is None or (math.isnan(g.price) and math.isnan(w.price))
             or (g.price == w.price and math.copysign(1, g.price) == math.copysign(1, w.price)))
        for g, w in zip(got, want))


@pytest.mark.parametrize("filters", [
    {}, {"symbols": {"T"}}, {"symbols": {"BRK-B", "AAPL"}}, {"cusips": {"037833100"}},
    {"symbols": {"T"}, "cusips": {"037833100"}}, {"symbols": set()}, {"cusips": set(), "symbols": {"ZZ-ZZ"}},
    {"symbols": {"NOPE"}}])
def test_store_gives_the_rows_the_parser_gives(tmp_path, filters):
    zip_path = tmp_path / "cnsfails202401a.zip"
    _write_zip(zip_path, {"a.txt": ODD, "b.txt": HEADER + "20240105|00206R102|T|5|AT&T INC COM|17.0\n"})
    got = [FtdRow(*f) for f in ftd_store.select(ftd_store.ensure(zip_path), **filters)]
    assert _same(got, _old(zip_path, **filters))
    if not filters:
        assert len(got) == 8


def test_store_is_built_once_and_again_when_the_zip_changes(tmp_path):
    zip_path = tmp_path / "cnsfails202401a.zip"
    _write_zip(zip_path, {"a.txt": ODD})
    db = ftd_store.ensure(zip_path)
    assert db == tmp_path / "parsed" / "cnsfails202401a.zip.sqlite"
    built = db.stat().st_mtime_ns
    assert ftd_store.ensure(zip_path) == db and db.stat().st_mtime_ns == built      # unchanged: not built again
    _write_zip(zip_path, {"a.txt": HEADER + "20240110|00206R102|T|5|AT&T INC COM|17.0\n"})
    ftd_store.ensure(zip_path)
    assert [r[0] for r in ftd_store.select(db)] == ["2024-01-10"]


def test_a_store_built_under_another_line_rule_is_built_again(tmp_path, monkeypatch):
    """The store holds the rule's output (a normalized symbol), so a change to the rule rebuilds it."""
    zip_path = tmp_path / "cnsfails202401a.zip"
    _write_zip(zip_path, {"a.txt": HEADER + "20240102|084670702|brk.b|5|BERKSHIRE HATHAWAY|400.0\n"})
    assert [r[2] for r in ftd_store.select(ftd_store.ensure(zip_path))] == ["BRK-B"]
    monkeypatch.setattr(ftd_store, "normalize_ticker", lambda raw: raw.strip().upper().replace(".", ""))
    assert [r[2] for r in ftd_store.select(ftd_store.ensure(zip_path))] == ["BRKB"]


def test_threads_building_one_store_at_once_all_read_the_same_rows(tmp_path):
    """Two prefetch threads, or two runs on one cache, can need the same store at once: each builds its own temp
    file, the last replace wins, and every reader sees a whole store."""
    import threading
    zip_path = tmp_path / "cnsfails202401a.zip"
    _write_zip(zip_path, {"a.txt": HEADER + "".join(
        f"2024010{1 + i % 9}|{i % 50:09d}|S{i % 30}|{i}|DESC {i % 7}|{i % 97 + .5}\n" for i in range(20000))})
    got, errors = [], []

    def work():
        try:
            got.append(list(ftd_store.select(ftd_store.ensure(zip_path), symbols={"S5", "S7"})))
        except BaseException as e:      # the test reports whatever a thread met
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(got) == 8 and got[0] and all(g == got[0] for g in got)
    assert sorted(p.name for p in (tmp_path / "parsed").iterdir()) == ["cnsfails202401a.zip.sqlite"]


def test_a_cut_off_store_is_built_again(tmp_path):
    zip_path = tmp_path / "cnsfails202401a.zip"
    _write_zip(zip_path, {"a.txt": ODD})
    db = ftd_store.ensure(zip_path)
    db.write_bytes(db.read_bytes()[:300])
    assert len(list(ftd_store.select(ftd_store.ensure(zip_path)))) == 7


def test_a_bad_zip_raises_and_leaves_no_store(tmp_path):
    zip_path = tmp_path / "cnsfails202401a.zip"
    zip_path.write_bytes(b"not a zip")
    with pytest.raises(zipfile.BadZipFile):
        ftd_store.ensure(zip_path)
    assert not (tmp_path / "parsed" / "cnsfails202401a.zip.sqlite").exists()
    assert not list((tmp_path / "parsed").glob(".*"))


def test_write_atomic_with_replaces_only_on_success(tmp_path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError):
        write_atomic_with(target, lambda tmp: (tmp.write_bytes(b"new, cut"), (_ for _ in ()).throw(RuntimeError()))[0])
    assert target.read_bytes() == b"old" and os.listdir(tmp_path) == ["x.bin"]
    write_atomic_with(target, lambda tmp: tmp.write_bytes(b"new"))
    assert target.read_bytes() == b"new" and os.listdir(tmp_path) == ["x.bin"]


def test_a_build_cut_off_by_a_killed_process_is_cleaned_up_by_the_next_one(tmp_path):
    import subprocess
    import sys
    dead = subprocess.Popen([sys.executable, "-c", ""])
    dead.wait()
    zip_path = tmp_path / "cnsfails202401a.zip"
    _write_zip(zip_path, {"a.txt": ODD})
    (tmp_path / "parsed").mkdir()
    orphan = tmp_path / "parsed" / f".cnsfails202401a.zip.sqlite.{dead.pid}.1.tmp"
    orphan.write_bytes(b"SQLite format 3\x00 cut off")
    ftd_store.ensure(zip_path)
    assert not orphan.exists()



@pytest.mark.parametrize("filters", [{}, {"symbols": {"T"}}, {"cusips": {"037833100"}}, {"symbols": {"BRK-B"}, "cusips": {"G0000Z000"}}])
def test_parse_ftd_lines_and_the_reference_rule_agree(filters):
    lines = ODD.splitlines(keepends=True)
    assert _same(list(parse_ftd_lines(lines, **filters)), list(_reference_lines(lines, **filters)))

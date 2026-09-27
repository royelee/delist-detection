"""Atomic writes: replace_on_success / replace_all_on_success (output tables,
the decisions file); write_atomic and the orphan-temp cleanup are covered in
test_edgar_threads.py beside the cache writers that use them."""
import pytest

from delist_detection.atomic_io import replace_all_on_success, replace_on_success


def test_replace_on_success_removes_temp_on_error(tmp_path):
    target = tmp_path / "x.csv"
    with pytest.raises(RuntimeError):
        with replace_on_success(target) as tmp:
            tmp.write_text("partial")
            raise RuntimeError
    assert not target.exists()
    assert not (tmp_path / ".x.csv.tmp").exists()


def test_replace_all_on_success_replaces_every_path_or_none(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "sub" / "b.csv"
    with replace_all_on_success([a, b]) as (ta, tb):
        ta.write_text("A1")
        tb.write_text("B1")
    assert (a.read_text(), b.read_text()) == ("A1", "B1")
    with pytest.raises(RuntimeError):
        with replace_all_on_success([a, b]) as (ta, tb):
            ta.write_text("A2")                   # written, but the block fails before it ends
            raise RuntimeError
    assert (a.read_text(), b.read_text()) == ("A1", "B1")
    assert not list(tmp_path.rglob(".*.tmp"))

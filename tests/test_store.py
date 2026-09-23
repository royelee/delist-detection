from datetime import date

import pytest

from delist_detection.store import (
    DELISTINGS_COLUMNS, TABLES, format_cell, read_table, replace_on_success, table_path, write_table, write_tables,
)


def test_format_cell_rules():
    assert format_cell(None) == ""
    assert format_cell(float("nan")) == ""
    assert format_cell(True) == "true"
    assert format_cell(False) == "false"
    assert format_cell(1.5) == "1.500000"
    assert format_cell(date(2018, 11, 28)) == "2018-11-28"
    assert format_cell(("a", "b")) == "a;b"
    assert format_cell(1122304) == "1122304"


def test_all_tables_have_keys_inside_columns():
    for spec in TABLES.values():
        assert set(spec.key) <= set(spec.columns), spec.name
    assert TABLES["delistings"].columns == DELISTINGS_COLUMNS
    assert TABLES["delistings"].key == ("sec_id", "delist_date")


def test_write_sorts_by_key_and_round_trips(tmp_path):
    p = table_path(tmp_path, "securities")
    rows = [
        {"sec_id": "BBG2", "issuer_cik": 2, "share_class": "COMMON", "name": "B", "security_type": "Common Stock",
         "observed": True, "figi_source": "ticker"},
        {"sec_id": "BBG1", "issuer_cik": 1, "share_class": "COMMON", "name": "A", "security_type": "Common Stock",
         "observed": False, "figi_source": "cusip"},
    ]
    assert write_table("securities", rows, p) == 2
    back = read_table("securities", p)
    assert [r["sec_id"] for r in back] == ["BBG1", "BBG2"]
    assert back[0]["observed"] == "false"
    assert p.read_text().splitlines()[0] == ",".join(TABLES["securities"].columns)


def test_missing_columns_are_blank_and_unknown_columns_raise(tmp_path):
    p = table_path(tmp_path, "cusip_history")
    write_table("cusip_history", [{"sec_id": "BBG1", "cusip": "00817Y108", "valid_from": "2004-01-02"}], p)
    assert read_table("cusip_history", p)[0]["valid_to"] == ""
    with pytest.raises(ValueError, match="unknown column"):
        write_table("cusip_history", [{"sec_id": "x", "bogus": 1}], p)


def test_failed_write_keeps_previous_file(tmp_path):
    p = table_path(tmp_path, "securities")
    write_table("securities", [{"sec_id": "BBG1"}], p)
    before = p.read_text()

    def boom():
        yield {"sec_id": "BBG9"}
        raise RuntimeError("mid-run failure")

    with pytest.raises(RuntimeError):
        write_table("securities", boom(), p)
    assert p.read_text() == before
    assert not list(tmp_path.glob(".*.tmp"))


def test_read_table_rejects_wrong_header(tmp_path):
    p = tmp_path / "securities.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="do not match"):
        read_table("securities", p)


def test_write_tables_writes_every_table(tmp_path):
    counts = write_tables(tmp_path, {
        "securities": [{"sec_id": "BBG1", "issuer_cik": 1, "share_class": "COMMON", "name": "A",
                        "security_type": "Common Stock", "observed": True, "figi_source": "cusip"}],
        "review": [{"sec_id": "BBG1", "delist_date": "2020-01-01", "ticker": "A", "review_flags": "x"}],
    })
    assert counts == {"securities": 1, "review": 1}
    assert read_table("securities", table_path(tmp_path, "securities"))[0]["sec_id"] == "BBG1"
    assert read_table("review", table_path(tmp_path, "review"))[0]["review_flags"] == "x"


def test_write_tables_failure_in_the_last_table_leaves_every_old_file_untouched(tmp_path):
    write_tables(tmp_path, {
        "securities": [{"sec_id": "BBG1"}],
        "review": [{"sec_id": "BBG1", "delist_date": "2020-01-01", "ticker": "A", "review_flags": "x"}],
    })
    before_sec = table_path(tmp_path, "securities").read_text()
    before_rev = table_path(tmp_path, "review").read_text()

    with pytest.raises(ValueError, match="unknown column"):
        write_tables(tmp_path, {
            "securities": [{"sec_id": "BBG2"}],   # would format fine
            "review": [{"sec_id": "BBG2", "bogus": 1}],   # fails formatting: aborts before any write
        })

    assert table_path(tmp_path, "securities").read_text() == before_sec
    assert table_path(tmp_path, "review").read_text() == before_rev
    assert not list(tmp_path.glob(".*.tmp"))


def test_write_tables_a_failing_iterator_on_a_later_table_leaves_earlier_files_untouched(tmp_path):
    write_tables(tmp_path, {
        "securities": [{"sec_id": "BBG1"}],
        "review": [{"sec_id": "BBG1", "delist_date": "2020-01-01", "ticker": "A", "review_flags": "x"}],
    })
    before_sec = table_path(tmp_path, "securities").read_text()
    before_rev = table_path(tmp_path, "review").read_text()

    def boom():
        yield {"sec_id": "BBG9", "delist_date": "2020-02-02", "ticker": "B", "review_flags": "y"}
        raise RuntimeError("mid-run failure")

    with pytest.raises(RuntimeError):
        write_tables(tmp_path, {"securities": [{"sec_id": "BBG2"}], "review": boom()})

    assert table_path(tmp_path, "securities").read_text() == before_sec
    assert table_path(tmp_path, "review").read_text() == before_rev
    assert not list(tmp_path.glob(".*.tmp"))


def test_replace_on_success_removes_temp_on_error(tmp_path):
    target = tmp_path / "x.csv"
    with pytest.raises(RuntimeError):
        with replace_on_success(target) as tmp:
            tmp.write_text("partial")
            raise RuntimeError
    assert not target.exists()
    assert not (tmp_path / ".x.csv.tmp").exists()

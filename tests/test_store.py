import csv
from datetime import date

import pytest

import delist_detection.store as store
from delist_detection.store import (
    DELISTINGS_COLUMNS, TABLES, format_cell, read_table, table_path, write_tables,
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


def test_review_tables_keep_their_given_order_and_every_other_table_sorts():
    assert TABLES["review"].columns == ("severity", "sec_id", "delist_date", "ticker", "cik", "bucket", "dlret",
                                        "review_flags", "reason", "anchor_8k", "last_seen")
    assert TABLES["review"].key == ("sec_id", "delist_date", "ticker", "review_flags")
    assert TABLES["review_summary"].columns == ("severity", "flag", "rows", "in_review", "accepted", "description",
                                                "action", "examples")
    assert TABLES["review_summary"].key == ("flag",)
    assert {n for n, spec in TABLES.items() if not spec.sort} == {"review", "review_summary"}


def _review(sec_id, flags):
    return {"severity": "check", "sec_id": sec_id, "delist_date": "2020-01-01", "ticker": "A", "review_flags": flags}


def test_an_unsorted_table_keeps_its_input_order(tmp_path):
    rows = [_review("S3", "b"), _review("S1", "a"), _review("S2", "c")]
    write_tables(tmp_path, {"review": rows})
    assert [r["sec_id"] for r in read_table("review", table_path(tmp_path, "review"))] == ["S3", "S1", "S2"]
    write_tables(tmp_path / "t", {
        "review": rows,
        "review_summary": [{"severity": "info", "flag": "z", "rows": 3}, {"severity": "fix", "flag": "a", "rows": 1}],
        "securities": [{"sec_id": "BBG2"}, {"sec_id": "BBG1"}],
    })
    assert [r["sec_id"] for r in read_table("review", table_path(tmp_path / "t", "review"))] == ["S3", "S1", "S2"]
    assert [r["flag"] for r in read_table("review_summary", table_path(tmp_path / "t", "review_summary"))] == [
        "z", "a"]
    # a key-sorted table in the same call still sorts
    assert [r["sec_id"] for r in read_table("securities", table_path(tmp_path / "t", "securities"))] == [
        "BBG1", "BBG2"]


def test_write_sorts_by_key_and_round_trips(tmp_path):
    p = table_path(tmp_path, "securities")
    rows = [
        {"sec_id": "BBG2", "issuer_cik": 2, "share_class": "COMMON", "name": "B", "security_type": "Common Stock",
         "observed": True, "figi_source": "ticker"},
        {"sec_id": "BBG1", "issuer_cik": 1, "share_class": "COMMON", "name": "A", "security_type": "Common Stock",
         "observed": False, "figi_source": "cusip"},
    ]
    assert write_tables(p.parent, {"securities": rows}) == {"securities": 2}
    back = read_table("securities", p)
    assert [r["sec_id"] for r in back] == ["BBG1", "BBG2"]
    assert back[0]["observed"] == "false"
    assert p.read_text().splitlines()[0] == ",".join(TABLES["securities"].columns)


def test_missing_columns_are_blank_and_unknown_columns_raise(tmp_path):
    p = table_path(tmp_path, "cusip_history")
    write_tables(p.parent, {"cusip_history": [{"sec_id": "BBG1", "cusip": "00817Y108", "valid_from": "2004-01-02"}]})
    assert read_table("cusip_history", p)[0]["valid_to"] == ""
    with pytest.raises(ValueError, match="unknown column"):
        write_tables(p.parent, {"cusip_history": [{"sec_id": "x", "bogus": 1}]})


def test_failed_write_keeps_previous_file(tmp_path):
    p = table_path(tmp_path, "securities")
    write_tables(p.parent, {"securities": [{"sec_id": "BBG1"}]})
    before = p.read_text()

    def boom():
        yield {"sec_id": "BBG9"}
        raise RuntimeError("mid-run failure")

    with pytest.raises(RuntimeError):
        write_tables(p.parent, {"securities": boom()})
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


def test_write_tables_removes_the_temp_file_of_a_table_that_fails_mid_write(tmp_path, monkeypatch):
    """A table's temp path must be registered for cleanup BEFORE it is opened,
    not after a successful write -- otherwise a failure while writing that
    table's own rows (disk full, etc.) leaves its temp file behind forever."""
    write_tables(tmp_path, {
        "securities": [{"sec_id": "BBG1"}],
        "review": [{"sec_id": "BBG1", "delist_date": "2020-01-01", "ticker": "A", "review_flags": "x"}],
    })
    before_sec = table_path(tmp_path, "securities").read_text()
    before_rev = table_path(tmp_path, "review").read_text()

    real_dict_writer = csv.DictWriter

    class _BoomWriter:
        def __init__(self, fh, fieldnames, **kw):
            self._real = real_dict_writer(fh, fieldnames, **kw)
            self._boom = list(fieldnames) == list(TABLES["review"].columns)

        def writeheader(self):
            self._real.writeheader()

        def writerows(self, rows):
            if self._boom:
                raise RuntimeError("disk full")
            self._real.writerows(rows)

    monkeypatch.setattr(store.csv, "DictWriter", _BoomWriter)

    with pytest.raises(RuntimeError, match="disk full"):
        write_tables(tmp_path, {
            "securities": [{"sec_id": "BBG2"}],
            "review": [{"sec_id": "BBG2", "delist_date": "2020-02-02", "ticker": "B", "review_flags": "y"}],
        })

    assert table_path(tmp_path, "securities").read_text() == before_sec
    assert table_path(tmp_path, "review").read_text() == before_rev
    assert not list(tmp_path.glob(".*.tmp"))


# --- read_delistings_frame: the pandas reader the handling layer uses -----

def _delistings_as_qlib_adapter_read_them(path):
    """qlib_adapter.load_delistings's own recipe before it read through
    store.read_delistings_frame; the frames must stay identical, dtypes included."""
    import pandas as pd
    df = pd.read_csv(path, dtype={"sec_id": str, "ticker": str, "successor_sec_id": str, "acquirer_sec_id": str,
                                  "bucket": str})
    for c in ("delist_date", "last_trade_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ("crsp_code", "last_trade_close", "payout_per_share", "terminal_value", "recovery_ratio", "cik"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def test_read_delistings_frame_types_delistings_exactly_as_before(tmp_path):
    import pandas as pd
    rows = [
        {"sec_id": "BBG000FJLFX8", "delist_date": "2018-12-09", "ticker": "AET", "cik": 1122304,
         "bucket": "merger", "crsp_code": 231, "last_trade_date": "2018-11-28", "last_trade_close": 212.5,
         "payout_per_share": 145.0, "stock_ratio": 0.8378, "acquirer_price": 80.0, "acquirer_ticker": "CVS",
         "terminal_value": 212.02, "dlret": -0.002259, "dlret_method": "cash_plus_stock",
         "review_flags": "ftd_close_lagged;merger_at_par", "successor_sec_id": None, "acquirer_sec_id": "BBG000BGRY34"},
        {"sec_id": "CIK1-COMMON", "delist_date": "2020-01-02", "ticker": "NA", "cik": None, "bucket": "unknown",
         "last_trade_date": "", "dlret": float("nan"), "successor_sec_id": "CIK1-COMMON", "reason": "a, quoted; one"},
        {"sec_id": "Z0012345", "delist_date": "2021-02-30", "ticker": "007", "cik": "x", "bucket": "exchange_transfer",
         "crsp_code": "", "recovery_ratio": 0.25},
    ]
    p = table_path(tmp_path, "delistings")
    write_tables(p.parent, {"delistings": rows})
    pd.testing.assert_frame_equal(store.read_delistings_frame(p), _delistings_as_qlib_adapter_read_them(p),
                                  check_exact=True)


def test_read_delistings_frame_matches_the_committed_delistings_table():
    import pandas as pd
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "output" / "delistings.csv"
    if not p.exists():
        pytest.skip("no committed output/delistings.csv")
    pd.testing.assert_frame_equal(store.read_delistings_frame(p), _delistings_as_qlib_adapter_read_them(p),
                                  check_exact=True)


def test_read_delistings_frame_rejects_a_file_of_another_table(tmp_path):
    p = tmp_path / "delistings.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="do not match"):
        store.read_delistings_frame(p)

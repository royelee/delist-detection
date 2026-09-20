"""Offline tests for RawTiingoPrices.

All tests use tmp_path — no network or real data dir access.
"""

import pytest

from delist_detection.raw_tiingo import RawTiingoPrices

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CSV_HEADER = "date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,adjVolume,divCash,splitFactor\n"


def _write_csv(path, rows):
    """Write a minimal Tiingo-style CSV into path with the given (date, close) rows."""
    lines = [_CSV_HEADER]
    for date, close in rows:
        # Fill remaining columns with dummy values.
        lines.append(f"{date},{close},0,0,0,0,0,0,0,0,0,0,1.0\n")
    path.write_text("".join(lines))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_exact_date_hit(tmp_path):
    """Exact date present in the file → return that row's close."""
    csv_file = tmp_path / "abc.csv"
    _write_csv(csv_file, [
        ("2020-01-02", 100.0),
        ("2020-01-03", 105.0),
        ("2020-01-06", 110.0),
    ])
    prices = RawTiingoPrices(root=tmp_path)
    assert prices.close_on("ABC", "2020-01-03") == pytest.approx(105.0)


def test_date_between_trading_days_returns_prior_close(tmp_path):
    """Date falls on a non-trading day → return the prior trading day's close."""
    csv_file = tmp_path / "abc.csv"
    _write_csv(csv_file, [
        ("2020-01-02", 100.0),
        ("2020-01-03", 105.0),
        # 2020-01-04 and 2020-01-05 are weekend — not in file
        ("2020-01-06", 110.0),
    ])
    prices = RawTiingoPrices(root=tmp_path)
    # Saturday 2020-01-04 → prior trading day is 2020-01-03
    assert prices.close_on("ABC", "2020-01-04") == pytest.approx(105.0)
    # Sunday 2020-01-05 → same result
    assert prices.close_on("ABC", "2020-01-05") == pytest.approx(105.0)


def test_date_before_first_row_returns_none(tmp_path):
    """Date is before all rows in the file → None (no prior trading day)."""
    csv_file = tmp_path / "abc.csv"
    _write_csv(csv_file, [
        ("2020-01-02", 100.0),
        ("2020-01-03", 105.0),
    ])
    prices = RawTiingoPrices(root=tmp_path)
    assert prices.close_on("ABC", "2019-12-31") is None


def test_missing_ticker_file_returns_none(tmp_path):
    """No CSV file for ticker → None without raising."""
    prices = RawTiingoPrices(root=tmp_path)
    assert prices.close_on("ZZZNOTEXIST", "2020-01-02") is None


def test_blank_ticker_returns_none(tmp_path):
    """Blank or whitespace-only ticker → None without raising."""
    prices = RawTiingoPrices(root=tmp_path)
    assert prices.close_on("", "2020-01-02") is None
    assert prices.close_on("   ", "2020-01-02") is None


def test_ticker_lookup_is_case_insensitive(tmp_path):
    """File is lowercase; passing an uppercase ticker still finds it."""
    csv_file = tmp_path / "aet.csv"
    _write_csv(csv_file, [("2018-11-28", 190.0)])
    prices = RawTiingoPrices(root=tmp_path)
    assert prices.close_on("AET", "2018-11-28") == pytest.approx(190.0)
    assert prices.close_on("aet", "2018-11-28") == pytest.approx(190.0)


def test_cache_avoids_double_read(tmp_path, monkeypatch):
    """Second call for the same ticker uses the cached series, not a new file read."""
    import pandas as pd
    import delist_detection.raw_tiingo as rt_module

    csv_file = tmp_path / "abc.csv"
    _write_csv(csv_file, [("2020-01-02", 100.0)])
    prices = RawTiingoPrices(root=tmp_path)

    read_count = 0
    original_read_csv = pd.read_csv

    def counting_read_csv(*args, **kwargs):
        nonlocal read_count
        read_count += 1
        return original_read_csv(*args, **kwargs)

    # Patch read_csv on the module where RawTiingoPrices calls it.
    monkeypatch.setattr(rt_module.pd, "read_csv", counting_read_csv)

    # First call — reads the file once.
    prices.close_on("ABC", "2020-01-02")
    assert read_count == 1

    # Second call for the same ticker — must use the cache, no additional read.
    prices.close_on("ABC", "2020-01-02")
    assert read_count == 1  # still 1: cache was hit


def test_last_date_in_file(tmp_path):
    """The last row's date returns its close exactly."""
    csv_file = tmp_path / "abc.csv"
    _write_csv(csv_file, [
        ("2020-01-02", 100.0),
        ("2020-01-03", 105.0),
    ])
    prices = RawTiingoPrices(root=tmp_path)
    assert prices.close_on("ABC", "2020-01-03") == pytest.approx(105.0)


def test_date_after_last_row_returns_last_close(tmp_path):
    """Date past the last available row → return the last known close."""
    csv_file = tmp_path / "abc.csv"
    _write_csv(csv_file, [
        ("2020-01-02", 100.0),
        ("2020-01-03", 105.0),
    ])
    prices = RawTiingoPrices(root=tmp_path)
    # 2020-06-01 is after all rows — nearest prior is the last row.
    assert prices.close_on("ABC", "2020-06-01") == pytest.approx(105.0)


# ---------------------------------------------------------------------------
# Root resolution order
# ---------------------------------------------------------------------------

def test_root_argument_wins_over_env_var(tmp_path, monkeypatch):
    """An explicit root= argument is used even when RAW_TIINGO_DIR is set."""
    root_dir = tmp_path / "root"
    env_dir = tmp_path / "env"
    root_dir.mkdir()
    env_dir.mkdir()
    _write_csv(root_dir / "abc.csv", [("2020-01-02", 100.0)])
    _write_csv(env_dir / "abc.csv", [("2020-01-02", 999.0)])
    monkeypatch.setenv("RAW_TIINGO_DIR", str(env_dir))

    prices = RawTiingoPrices(root=root_dir)
    assert prices.close_on("ABC", "2020-01-02") == pytest.approx(100.0)


def test_env_var_used_when_root_is_none(tmp_path, monkeypatch):
    """RAW_TIINGO_DIR is used when root= is not passed."""
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    _write_csv(env_dir / "abc.csv", [("2020-01-02", 100.0)])
    monkeypatch.setenv("RAW_TIINGO_DIR", str(env_dir))

    prices = RawTiingoPrices()
    assert prices.close_on("ABC", "2020-01-02") == pytest.approx(100.0)


def test_no_root_no_env_raises_value_error(monkeypatch):
    """Neither root= nor RAW_TIINGO_DIR set → ValueError, no silent default."""
    monkeypatch.delenv("RAW_TIINGO_DIR", raising=False)
    with pytest.raises(ValueError, match="no raw price directory"):
        RawTiingoPrices()

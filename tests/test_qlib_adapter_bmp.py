from pathlib import Path

import pandas as pd
import pytest

from delist_detection.qlib_adapter import apply_bmp_corrections
from delist_detection.store import table_path, write_table


def _row(sec_id: str, **over) -> dict:
    row = {"sec_id": "ALTR_ID", "delist_date": "2025-03-26", "ticker": "ALTR", "cik": 1701732, "bucket": "merger",
           "crsp_code": 231, "confidence": "high", "reason": "M&A", "exchange": "NASDAQ",
           "last_trade_date": "2025-03-25", "last_trade_close": 105.0, "payout_per_share": 113.0}
    row["sec_id"] = sec_id
    row.update(over)
    return row


def _write(tmp_path: Path, rows: list) -> Path:
    p = table_path(tmp_path, "delistings")
    write_table("delistings", rows, p)
    return p


@pytest.fixture
def monthly_panel() -> pd.DataFrame:
    # Month-end panel with two columns: close + monthly_return.
    # ALTR delists 2025-03-26 (March): prior_month_end Feb 2025, last_trade 2025-03-25.
    # RSH  delists 2015-02-09 (Feb):   prior_month_end Jan 2015, last_trade 2015-02-06.
    # ZEXP delists 2020-06-15: should be dropped.
    rows = [
        ("2025-02-28", "ALTR_ID", 100.0, 0.04),
        ("2025-03-31", "ALTR_ID", 105.0, 0.05),   # truncated raw value; will be overwritten
        ("2015-01-31", "RSH_ID",  0.50, -0.10),
        ("2015-02-28", "RSH_ID",  0.40, -0.20),   # truncated; will be overwritten
        ("2020-05-31", "ZEXP_ID", 1.00, 0.00),
        ("2020-06-30", "ZEXP_ID", 1.00, 0.00),    # should be dropped
        ("2025-02-28", "OTHER_ID", 50.0, 0.01),   # untouched
        ("2025-03-31", "OTHER_ID", 52.0, 0.04),   # untouched
    ]
    df = pd.DataFrame(rows, columns=["date", "instrument", "close", "monthly_return"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index(["date", "instrument"]).sort_index()


def test_apply_bmp_corrections_overwrites_merger_month(monthly_panel, tmp_path):
    rows = [
        _row("ALTR_ID", last_trade_close=105.0, payout_per_share=113.0, exchange="NASDAQ"),
        _row("RSH_ID", ticker="RSH", cik=1144980, bucket="compliance_failure", crsp_code=584,
             reason="Form 25 + Form 15", exchange="NYSE", delist_date="2015-02-09",
             last_trade_date="2015-02-06", last_trade_close=0.40, payout_per_share=None),
    ]
    csv_path = _write(tmp_path, rows)
    out = apply_bmp_corrections(monthly_panel, str(csv_path), return_col="monthly_return")
    # ALTR: (1.05)(1.0762) - 1 ≈ 0.13
    altr = out.xs("ALTR_ID", level="instrument")
    assert altr.loc[pd.Timestamp("2025-03-31"), "monthly_return"] == pytest.approx(0.13, rel=1e-3)
    # Prior month untouched
    assert altr.loc[pd.Timestamp("2025-02-28"), "monthly_return"] == pytest.approx(0.04)


def test_apply_bmp_corrections_compliance_uses_shumway_minus30_for_nyse(monthly_panel, tmp_path):
    rows = [
        _row("RSH_ID", ticker="RSH", cik=1144980, bucket="compliance_failure", crsp_code=584,
             reason="Form 25 + Form 15", exchange="NYSE", delist_date="2015-02-09",
             last_trade_date="2015-02-06", last_trade_close=0.40, payout_per_share=None),
    ]
    csv_path = _write(tmp_path, rows)
    out = apply_bmp_corrections(monthly_panel, str(csv_path), return_col="monthly_return")
    # R_partial Jan->Feb close: 0.40/0.50 - 1 = -0.20
    # DLRET (NYSE Shumway) = -0.30
    # R_month = (0.80)(0.70) - 1 = -0.44
    rsh = out.xs("RSH_ID", level="instrument")
    assert rsh.loc[pd.Timestamp("2015-02-28"), "monthly_return"] == pytest.approx(-0.44, rel=1e-3)


def test_apply_bmp_corrections_drops_expiration_month(monthly_panel, tmp_path):
    rows = [
        _row("ZEXP_ID", ticker="ZEXP", cik=9999999, bucket="expiration", crsp_code=600, confidence="medium",
             reason="scheduled", exchange=None, delist_date="2020-06-15", last_trade_date="2020-06-15",
             last_trade_close=1.0, payout_per_share=None),
    ]
    csv_path = _write(tmp_path, rows)
    out = apply_bmp_corrections(monthly_panel, str(csv_path), return_col="monthly_return")
    zexp = out.xs("ZEXP_ID", level="instrument")
    # June 2020 row dropped (expiration); May 2020 still present
    assert pd.Timestamp("2020-06-30") not in zexp.index
    assert pd.Timestamp("2020-05-31") in zexp.index


def test_apply_bmp_corrections_does_not_touch_unrelated_tickers(monthly_panel, tmp_path):
    rows = [
        _row("ALTR_ID", last_trade_close=105.0, payout_per_share=113.0, exchange="NASDAQ"),
    ]
    csv_path = _write(tmp_path, rows)
    out = apply_bmp_corrections(monthly_panel, str(csv_path), return_col="monthly_return")
    other = out.xs("OTHER_ID", level="instrument")
    assert other.loc[pd.Timestamp("2025-03-31"), "monthly_return"] == pytest.approx(0.04)
    assert other.loc[pd.Timestamp("2025-02-28"), "monthly_return"] == pytest.approx(0.01)


def test_apply_bmp_corrections_returns_copy_not_mutation(monthly_panel, tmp_path):
    rows = [
        _row("ALTR_ID", last_trade_close=105.0, payout_per_share=113.0, exchange="NASDAQ"),
    ]
    csv_path = _write(tmp_path, rows)
    before = monthly_panel.copy()
    _ = apply_bmp_corrections(monthly_panel, str(csv_path), return_col="monthly_return")
    pd.testing.assert_frame_equal(monthly_panel, before)


def test_apply_bmp_corrections_warns_for_compliance_fallback(monthly_panel, tmp_path):
    import warnings
    rows = [
        _row("RSH_ID", ticker="RSH", cik=1144980, bucket="compliance_failure", crsp_code=584,
             reason="Form 25 + Form 15", exchange="NYSE", delist_date="2015-02-09",
             last_trade_date=None, last_trade_close=None, payout_per_share=None),  # NOT providing -> falls back
    ]
    csv_path = _write(tmp_path, rows)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ = apply_bmp_corrections(monthly_panel, str(csv_path), return_col="monthly_return")
    msgs = [str(w.message) for w in caught]
    assert any("RSH" in m and "compliance_failure" in m for m in msgs), (
        f"expected a fallback warning mentioning RSH and compliance_failure; got: {msgs}"
    )


def test_apply_bmp_corrections_no_warn_when_last_trade_provided(monthly_panel, tmp_path):
    import warnings
    rows = [
        _row("RSH_ID", ticker="RSH", cik=1144980, bucket="compliance_failure", crsp_code=584,
             reason="Form 25 + Form 15", exchange="NYSE", delist_date="2015-02-09",
             last_trade_date="2015-02-06", last_trade_close=0.40, payout_per_share=None),  # explicit -> no warning
    ]
    csv_path = _write(tmp_path, rows)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ = apply_bmp_corrections(monthly_panel, str(csv_path), return_col="monthly_return")
    msgs = [str(w.message) for w in caught]
    assert not any("RSH" in m for m in msgs), (
        f"did not expect a fallback warning for RSH when last_trade_close provided: {msgs}"
    )


def test_apply_bmp_corrections_no_warn_for_merger_fallback(monthly_panel, tmp_path):
    # M&A panel close usually tracks the deal — fallback is fine, no warning.
    import warnings
    rows = [
        _row("ALTR_ID", last_trade_date=None, last_trade_close=None, payout_per_share=113.0, exchange="NASDAQ"),
    ]
    csv_path = _write(tmp_path, rows)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ = apply_bmp_corrections(monthly_panel, str(csv_path), return_col="monthly_return")
    msgs = [str(w.message) for w in caught]
    assert not any("ALTR" in m for m in msgs), (
        f"did not expect a fallback warning for ALTR (MERGER): {msgs}"
    )

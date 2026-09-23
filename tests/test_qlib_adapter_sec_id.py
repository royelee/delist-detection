import math

import numpy as np
import pandas as pd

from delist_detection.qlib_adapter import apply_backtest_exits, inject_terminal_labels, record_from_row, row_payout
from delist_detection.store import table_path, write_table


def _csv(tmp_path, **over):
    row = {"sec_id": "BBG1", "delist_date": "2025-04-05", "ticker": "ALTR", "cik": 1701732, "bucket": "merger",
           "crsp_code": 231, "confidence": "high", "reason": "M&A", "exchange": "NASDAQ",
           "last_trade_date": "2025-03-25", "last_trade_close": 111.85, "payout_per_share": 113.0,
           "terminal_value": 113.0, "dlret": 113.0 / 111.85 - 1, "dlret_method": "cash_only",
           "dlret_confidence": "high"}
    row.update(over)
    p = table_path(tmp_path, "delistings")
    write_table("delistings", [row], p)
    return p


def _panel():
    idx = pd.MultiIndex.from_product([pd.to_datetime(["2025-03-21", "2025-03-24", "2025-03-25", "2025-03-26"]),
                                      ["BBG1", "ALTR"]], names=["datetime", "instrument"])
    return pd.DataFrame({"close": 111.0, "LABEL": np.nan}, index=idx)


def test_labels_join_on_sec_id_and_stop_at_last_trade(tmp_path):
    out = inject_terminal_labels(_panel(), _csv(tmp_path), horizon_days=2)
    lab = out["LABEL"]
    want = 113.0 / 111.85 - 1
    assert math.isclose(lab[(pd.Timestamp("2025-03-24"), "BBG1")], want)
    assert math.isclose(lab[(pd.Timestamp("2025-03-25"), "BBG1")], want)
    assert np.isnan(lab[(pd.Timestamp("2025-03-26"), "BBG1")])          # vendor filler row after the last trade
    assert lab.xs("ALTR", level="instrument").isna().all()               # the ticker is not the key


def test_backtest_exit_on_last_trade_date(tmp_path):
    pos = pd.DataFrame({"date": pd.to_datetime(["2025-03-24", "2025-03-25"]), "sec_id": ["BBG1", "BBG1"],
                        "price": [111.5, 111.85]})
    out = apply_backtest_exits(pos, _csv(tmp_path))
    assert out.loc[out["date"] == "2025-03-25", "price"].item() == 113.0
    assert out.loc[out["date"] == "2025-03-24", "price"].item() == 111.5


def test_record_and_payout_from_row(tmp_path):
    p = _csv(tmp_path, successor_sec_id="BBG1", terminal_value=212.25, payout_per_share=145.0)
    row = pd.read_csv(p, dtype=str).iloc[0]
    rec = record_from_row(row)
    assert rec.sec_id == "BBG1" and rec.observed_delist_date == "2025-03-25" and rec.successor_sec_id == "BBG1"
    assert row_payout(row) == 212.25

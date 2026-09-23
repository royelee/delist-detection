import pandas as pd
import pytest

from delist_detection.qlib_adapter import inject_terminal_labels, apply_backtest_exits
from delist_detection.store import table_path, write_table


@pytest.fixture
def tmp_delistings(tmp_path):
    """A 3-row delistings.csv: one merger, one compliance, one liquidation."""
    rows = [
        {"sec_id": "ALPHA_ID", "delist_date": "2024-06-28", "ticker": "ALPHA", "cik": 1, "bucket": "merger",
         "crsp_code": 231, "confidence": "high", "reason": "test",
         "last_trade_date": "2024-06-28", "payout_per_share": 113.0},  # 13% premium
        {"sec_id": "BETA_ID", "delist_date": "2024-06-28", "ticker": "BETA", "cik": 2, "bucket": "compliance_failure",
         "crsp_code": 570, "confidence": "high", "reason": "test", "last_trade_date": "2024-06-28"},
        {"sec_id": "GAMMA_ID", "delist_date": "2024-06-28", "ticker": "GAMMA", "cik": 3, "bucket": "liquidation",
         "crsp_code": 400, "confidence": "medium", "reason": "test", "last_trade_date": "2024-06-28"},
    ]
    p = table_path(tmp_path, "delistings")
    write_table("delistings", rows, p)
    return str(p)


@pytest.fixture
def panel():
    dates = pd.date_range("2024-06-24", "2024-06-28")
    rows = []
    for sec_id in ["ALPHA_ID", "BETA_ID", "GAMMA_ID"]:
        for d in dates:
            rows.append({"datetime": d, "instrument": sec_id, "close": 100.0})
    df = pd.DataFrame(rows).set_index(["datetime", "instrument"])
    return df


def test_inject_terminal_labels_writes_bucket_returns(panel, tmp_delistings):
    out = inject_terminal_labels(panel, tmp_delistings, horizon_days=3)
    # ALPHA: last 3 rows have LABEL == 0.13
    alpha = out.xs("ALPHA_ID", level="instrument")["LABEL"].dropna()
    assert len(alpha) == 3
    assert all(abs(v - 0.13) < 1e-9 for v in alpha)
    # BETA: compliance failure -> -1.0
    beta = out.xs("BETA_ID", level="instrument")["LABEL"].dropna()
    assert all(v == -1.0 for v in beta)
    # GAMMA: liquidation -> -0.9 (default recovery 10%)
    gamma = out.xs("GAMMA_ID", level="instrument")["LABEL"].dropna()
    assert all(abs(v - (-0.9)) < 1e-9 for v in gamma)


def test_apply_backtest_exits_rewrites_exit_price(tmp_delistings):
    pos = pd.DataFrame([
        {"date": "2024-06-27", "sec_id": "ALPHA_ID", "price": 100.0},
        {"date": "2024-06-28", "sec_id": "ALPHA_ID", "price": 100.0},
        {"date": "2024-06-27", "sec_id": "BETA_ID",  "price": 50.0},
        {"date": "2024-06-28", "sec_id": "BETA_ID",  "price": 50.0},
    ])
    out = apply_backtest_exits(pos, tmp_delistings)
    # ALPHA exit row → 113
    exit_alpha = out[(out["sec_id"] == "ALPHA_ID") & (out["date"].dt.strftime("%Y-%m-%d") == "2024-06-28")]
    assert exit_alpha["price"].iloc[0] == 113.0
    # BETA exit row → 0
    exit_beta = out[(out["sec_id"] == "BETA_ID") & (out["date"].dt.strftime("%Y-%m-%d") == "2024-06-28")]
    assert exit_beta["price"].iloc[0] == 0.0
    # Non-exit row of ALPHA unchanged
    pre = out[(out["sec_id"] == "ALPHA_ID") & (out["date"].dt.strftime("%Y-%m-%d") == "2024-06-27")]
    assert pre["price"].iloc[0] == 100.0

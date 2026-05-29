import pandas as pd
import pytest

from delist_detection.qlib_adapter import inject_terminal_labels, apply_backtest_exits


@pytest.fixture
def tmp_classifications(tmp_path):
    """A 3-row classification CSV: one merger, one compliance, one liquidation."""
    p = tmp_path / "cls.csv"
    p.write_text(
        "ticker,cik,observed_delist_date,crsp_code,bucket,confidence,reason\n"
        "ALPHA,1,2024-06-28,231,merger,high,test\n"
        "BETA,2,2024-06-28,570,compliance_failure,high,test\n"
        "GAMMA,3,2024-06-28,400,liquidation,medium,test\n"
    )
    return str(p)


@pytest.fixture
def panel():
    dates = pd.date_range("2024-06-24", "2024-06-28")
    rows = []
    for tkr in ["ALPHA", "BETA", "GAMMA"]:
        for d in dates:
            rows.append({"datetime": d, "instrument": tkr, "close": 100.0})
    df = pd.DataFrame(rows).set_index(["datetime", "instrument"])
    return df


def test_inject_terminal_labels_writes_bucket_returns(panel, tmp_classifications):
    out = inject_terminal_labels(
        panel, tmp_classifications, horizon_days=3,
        payouts={"ALPHA": 113.0},  # 13% premium
    )
    # ALPHA: last 3 rows have LABEL == 0.13
    alpha = out.xs("ALPHA", level="instrument")["LABEL"].dropna()
    assert len(alpha) == 3
    assert all(abs(v - 0.13) < 1e-9 for v in alpha)
    # BETA: compliance failure -> -1.0
    beta = out.xs("BETA", level="instrument")["LABEL"].dropna()
    assert all(v == -1.0 for v in beta)
    # GAMMA: liquidation -> -0.9 (default recovery 10%)
    gamma = out.xs("GAMMA", level="instrument")["LABEL"].dropna()
    assert all(abs(v - (-0.9)) < 1e-9 for v in gamma)


def test_apply_backtest_exits_rewrites_exit_price(tmp_classifications):
    pos = pd.DataFrame([
        {"date": "2024-06-27", "ticker": "ALPHA", "price": 100.0},
        {"date": "2024-06-28", "ticker": "ALPHA", "price": 100.0},
        {"date": "2024-06-27", "ticker": "BETA",  "price": 50.0},
        {"date": "2024-06-28", "ticker": "BETA",  "price": 50.0},
    ])
    out = apply_backtest_exits(pos, tmp_classifications, payouts={"ALPHA": 113.0})
    # ALPHA exit row → 113
    exit_alpha = out[(out["ticker"] == "ALPHA") & (out["date"].dt.strftime("%Y-%m-%d") == "2024-06-28")]
    assert exit_alpha["price"].iloc[0] == 113.0
    # BETA exit row → 0
    exit_beta = out[(out["ticker"] == "BETA") & (out["date"].dt.strftime("%Y-%m-%d") == "2024-06-28")]
    assert exit_beta["price"].iloc[0] == 0.0
    # Non-exit row of ALPHA unchanged
    pre = out[(out["ticker"] == "ALPHA") & (out["date"].dt.strftime("%Y-%m-%d") == "2024-06-27")]
    assert pre["price"].iloc[0] == 100.0

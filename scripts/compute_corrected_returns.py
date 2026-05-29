"""Apply BMP 2007 firm-month corrections to a monthly panel.

Usage:
    python scripts/compute_corrected_returns.py \
        --panel data/monthly_panel.parquet \
        --classifications output/delist_classifications.csv \
        --av-csv data/listing_status_delisted.csv \
        --payouts data/payouts.csv \
        --out output/corrected_monthly_panel.parquet

Inputs:
    --panel: parquet/csv with MultiIndex (date, instrument) and columns
             ['close', 'monthly_return']. Dates must be month-ends.
    --classifications: output of scripts/classify_universe.py
    --av-csv: Alpha Vantage delisted listing-status CSV (used for exchange)
    --payouts (optional): CSV with columns 'ticker,payout_per_share'
    --recoveries (optional): CSV with columns 'ticker,recovery_ratio'
    --last-trade-closes (optional): CSV with columns 'ticker,last_trade_close'
                       If absent, uses panel close on delist-month-end.

Output: same shape as input with monthly_return spliced to BMP-corrected
        value at the delisting month; EXPIRATION rows removed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from delist_detection.av_listing import AvListingLoader
from delist_detection.qlib_adapter import apply_bmp_corrections


def _read_panel(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, parse_dates=["date"])
    if not isinstance(df.index, pd.MultiIndex):
        df = df.set_index(["date", "instrument"]).sort_index()
    return df


def _read_map(path: Path | None, value_col: str) -> dict[str, float]:
    if not path:
        return {}
    df = pd.read_csv(path)
    return dict(zip(df["ticker"].astype(str).str.upper(), df[value_col].astype(float)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", type=Path, required=True)
    p.add_argument("--classifications", type=Path, required=True)
    p.add_argument("--av-csv", type=Path, required=True)
    p.add_argument("--payouts", type=Path, default=None)
    p.add_argument("--recoveries", type=Path, default=None)
    p.add_argument("--last-trade-closes", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    panel = _read_panel(args.panel)

    required_cols = {"monthly_return", "close"}
    missing = required_cols - set(panel.columns)
    if missing:
        raise SystemExit(
            f"--panel is missing required columns: {sorted(missing)}. "
            f"Got columns: {list(panel.columns)}"
        )

    av = AvListingLoader(args.av_csv)
    cls_df = pd.read_csv(args.classifications, dtype={"ticker": str})
    exchanges: dict[str, str] = {}
    for _, row in cls_df.dropna(subset=["ticker"]).iterrows():
        ticker = str(row["ticker"])
        observed_date = row.get("observed_delist_date")
        if pd.isna(observed_date):
            observed_date = None
        else:
            observed_date = str(observed_date)[:10]  # YYYY-MM-DD prefix
        ex = av.exchange(ticker, observed_date=observed_date)
        if ex:
            exchanges[ticker.upper()] = ex

    payouts = _read_map(args.payouts, "payout_per_share")
    recoveries = _read_map(args.recoveries, "recovery_ratio")
    last_trades = _read_map(args.last_trade_closes, "last_trade_close")

    corrected = apply_bmp_corrections(
        panel=panel,
        classifications_csv=str(args.classifications),
        payouts=payouts,
        exchanges=exchanges,
        last_trade_closes=last_trades,
        recovery_ratios=recoveries,
        return_col="monthly_return",
        close_col="close",
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.suffix == ".parquet":
        corrected.to_parquet(args.out)
    else:
        corrected.to_csv(args.out)

    n_before = len(panel)
    n_after = len(corrected)
    print(
        f"BMP correction: {n_before} -> {n_after} rows "
        f"({n_before - n_after} dropped, "
        f"{len(cls_df)} delisting events processed)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Glue to apply delisting-aware handling to a qlib-style price panel.

A "qlib panel" here = a DataFrame indexed by (datetime, instrument) with at
least a `close` column. The two public functions emit:

    inject_terminal_labels(panel, classifications_csv, horizon_days=21, label_col='LABEL')
        Adds/overwrites the last `horizon_days` rows of each delisted ticker
        so that the realized forward return matches the bucket's policy.
        Eliminates the most common form of survivorship bias.

    apply_backtest_exits(positions_df, classifications_csv)
        Given a long-format positions/PnL dataframe with columns
        ['date', 'ticker', 'price'], rewrites the exit-day price per ticker
        to match the bucket-specific exit policy.

Both functions are pure: they return new DataFrames; they do not mutate.
"""

from __future__ import annotations

import warnings
from typing import Mapping

import pandas as pd

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .exchanges import normalize_exchange
from .handling import build_train_label_adjustment, build_backtest_exit, build_firm_month_correction


def load_classifications(path: str) -> pd.DataFrame:
    """Load the classifier output CSV. No type coercion beyond what's needed."""
    df = pd.read_csv(path, dtype={"ticker": str})
    df["observed_delist_date"] = pd.to_datetime(
        df["observed_delist_date"], errors="coerce"
    )
    df["crsp_code"] = pd.to_numeric(df["crsp_code"], errors="coerce")
    return df


def _record_from_row(row: pd.Series) -> DelistRecord:
    bucket = CrspBucket(row["bucket"]) if pd.notna(row["bucket"]) else CrspBucket.UNKNOWN
    code = int(row["crsp_code"]) if pd.notna(row["crsp_code"]) else None
    dd = row["observed_delist_date"]
    return DelistRecord(
        ticker=row["ticker"],
        cik=int(row["cik"]) if pd.notna(row["cik"]) else None,
        observed_delist_date=dd.strftime("%Y-%m-%d") if pd.notna(dd) else None,
        crsp_code=code,
        bucket=bucket,
        confidence=str(row.get("confidence", "")),
        reason=str(row.get("reason", "")),
    )


def inject_terminal_labels(
    panel: pd.DataFrame,
    classifications_csv: str,
    horizon_days: int = 21,
    label_col: str = "LABEL",
    close_col: str = "close",
    payouts: Mapping[str, float] | None = None,
    successor_map: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Inject the delist-aware forward-return label for each delisted ticker.

    Expects `panel` to be MultiIndex (datetime, instrument) with a `close`
    column. For each delisted ticker:

      * compute the bucket-policy forward return (e.g. −1.0 for compliance);
      * set `panel[label_col]` for the last `horizon_days` observations of
        that ticker so that the supervised learner sees the realized outcome
        rather than a censored value.

    Returns a new DataFrame; the original is untouched.
    """
    df = panel.copy()
    if label_col not in df.columns:
        df[label_col] = pd.NA
    cls = load_classifications(classifications_csv)

    for _, row in cls.iterrows():
        rec = _record_from_row(row)
        ticker = rec.ticker
        if ticker not in df.index.get_level_values("instrument"):
            continue
        slc = df.xs(ticker, level="instrument", drop_level=False)
        if slc.empty:
            continue
        last_close = float(slc[close_col].iloc[-1])
        po = (payouts or {}).get(ticker)
        adj = build_train_label_adjustment(rec, last_close, po, successor_map)
        if not adj.keep_in_training:
            continue
        idx_for_ticker = slc.index[-horizon_days:]
        df.loc[idx_for_ticker, label_col] = adj.forward_return
    return df


def apply_backtest_exits(
    positions_df: pd.DataFrame,
    classifications_csv: str,
    payouts: Mapping[str, float] | None = None,
    successor_map: Mapping[str, str] | None = None,
    date_col: str = "date",
    ticker_col: str = "ticker",
    price_col: str = "price",
) -> pd.DataFrame:
    """Rewrite the exit-day price per delisted ticker to bucket policy.

    `positions_df` is long-format: (date, ticker, price).
    The exit row is the one with `date == observed_delist_date` for that
    ticker. If no such row exists (e.g. you stopped quoting earlier), no
    change is made.
    """
    df = positions_df.copy()
    cls = load_classifications(classifications_csv)
    df[date_col] = pd.to_datetime(df[date_col])

    for _, row in cls.iterrows():
        rec = _record_from_row(row)
        ticker = rec.ticker
        sub = df[df[ticker_col] == ticker]
        if sub.empty:
            continue
        if rec.observed_delist_date is None:
            continue
        dd = pd.Timestamp(rec.observed_delist_date)
        mask = (df[ticker_col] == ticker) & (df[date_col] == dd)
        if not mask.any():
            continue
        last_close = float(sub.iloc[-1][price_col])
        po = (payouts or {}).get(ticker)
        bx = build_backtest_exit(rec, last_close, po, successor_map)
        df.loc[mask, price_col] = bx.exit_price
    return df


def apply_bmp_corrections(
    panel: pd.DataFrame,
    classifications_csv: str,
    payouts: Mapping[str, float] | None = None,
    exchanges: Mapping[str, str] | None = None,
    last_trade_closes: Mapping[str, float] | None = None,
    recovery_ratios: Mapping[str, float] | None = None,
    return_col: str = "monthly_return",
    close_col: str = "close",
) -> pd.DataFrame:
    """Splice the BMP 2007 corrected R_delisting_month into a monthly panel.

    For each delisted ticker, find the panel row whose date-level value is the
    month-end containing `observed_delist_date`, then overwrite `return_col`
    with `(1 + R_partial) * (1 + DLRET) - 1`. If the firm-month must be
    dropped (EXPIRATION, no delist date, invalid prior close), remove the row.

    Args:
        panel: MultiIndex (date, instrument) DataFrame with month-end dates.
        payouts: ticker -> cash-equivalent payout per share (M&A).
        exchanges: ticker -> raw exchange string (NYSE, NASDAQ, AMEX, ...).
        last_trade_closes: ticker -> the close on the last trading day before
            delist. Required for M&A and for non-month-end delists. Falls back
            to the panel's close on the delist-month-end row if absent.
        recovery_ratios: ticker -> observed liquidation recovery fraction.
    """
    payouts = payouts or {}
    exchanges = exchanges or {}
    last_trade_closes = last_trade_closes or {}
    recovery_ratios = recovery_ratios or {}

    df = panel.copy()
    cls = load_classifications(classifications_csv)

    rows_to_drop: list[tuple] = []

    for _, row in cls.iterrows():
        rec = _record_from_row(row)
        ticker = rec.ticker
        if rec.observed_delist_date is None:
            continue
        if ticker not in df.index.get_level_values("instrument"):
            continue

        slc = df.xs(ticker, level="instrument", drop_level=False)
        if slc.empty:
            continue

        # Find the month-end on or after observed_delist_date that exists in
        # the panel for this ticker.
        delist_ts = pd.Timestamp(rec.observed_delist_date)
        ticker_dates = slc.index.get_level_values("date")
        candidates = ticker_dates[ticker_dates >= delist_ts]
        if len(candidates) == 0:
            # Panel ends before delist; nothing to splice
            continue
        delist_month_end = candidates.min()

        # Prior month-end row (last row strictly before delist_month_end)
        prior_dates = ticker_dates[ticker_dates < delist_month_end]
        if len(prior_dates) == 0:
            continue
        prior_month_end = prior_dates.max()

        prior_close = float(df.loc[(prior_month_end, ticker), close_col])
        provided_last_trade = last_trade_closes.get(ticker)
        if provided_last_trade is None:
            last_trade_close = float(df.loc[(delist_month_end, ticker), close_col])
            bucket = rec.bucket
            recov = recovery_ratios.get(ticker)
            if (
                bucket is CrspBucket.COMPLIANCE_FAILURE
                or (bucket is CrspBucket.LIQUIDATION and recov is None)
            ):
                warnings.warn(
                    f"apply_bmp_corrections: ticker={ticker} bucket={bucket.value} "
                    f"has no observed last_trade_close; falling back to panel "
                    f"close_col={close_col!r} at {delist_month_end.date()}. "
                    f"The panel close for a performance-related delisting is often "
                    f"a stale mark and may understate the price collapse — the very "
                    f"bias BMP 2007 is meant to remove. Provide last_trade_closes[{ticker}!r] "
                    f"or recovery_ratios[{ticker}!r] explicitly to suppress this.",
                    stacklevel=2,
                )
        else:
            last_trade_close = float(provided_last_trade)

        ex = normalize_exchange(exchanges.get(ticker))

        fm = build_firm_month_correction(
            record=rec,
            prior_month_end_close=prior_close,
            last_trade_close=last_trade_close,
            exchange=ex,
            payout_per_share=payouts.get(ticker),
            recovery_ratio=recovery_ratios.get(ticker),
        )

        if fm.drop:
            rows_to_drop.append((delist_month_end, ticker))
        else:
            df.loc[(delist_month_end, ticker), return_col] = fm.firm_month_return

    if rows_to_drop:
        df = df.drop(index=rows_to_drop)

    return df

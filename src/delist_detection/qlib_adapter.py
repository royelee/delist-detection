"""Glue to apply delisting-aware handling to a qlib-style price panel.

A "qlib panel" here = a DataFrame indexed by (datetime, instrument) with at
least a `close` column, where `instrument` is a `sec_id` (see `store.py`).
The three public functions emit:

    inject_terminal_labels(panel, delistings_csv, horizon_days=21, label_col='LABEL')
        Adds/overwrites the last `horizon_days` rows of each delisted security
        (dated on or before its last trade date) so that the realized forward
        return matches the bucket's policy. Eliminates the most common form
        of survivorship bias.

    apply_backtest_exits(positions_df, delistings_csv)
        Given a long-format positions/PnL dataframe with columns
        ['date', 'sec_id', 'price'], rewrites the exit-day price per security
        to match the bucket-specific exit policy.

    apply_bmp_corrections(panel, delistings_csv)
        Splices the BMP 2007 corrected firm-month return into a monthly panel.

All three read every DLRET input (exchange, last trade close, payout,
recovery ratio, successor) straight off the `delistings.csv` row for that
security. Every function is pure: they return new DataFrames; they do not
mutate.
"""

from __future__ import annotations

import warnings

import pandas as pd

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .exchanges import normalize_exchange
from .handling import build_train_label_adjustment, build_backtest_exit, build_firm_month_correction
from .store import read_frame


def load_delistings(path: str) -> pd.DataFrame:
    """Load a `delistings.csv` through `store.read_frame` (see
    `store.FRAME_TYPES`): no type coercion beyond what's needed to key/compute
    on the rows."""
    return read_frame("delistings", path)


def _iso(v) -> str | None:
    if v is None or (isinstance(v, float) and v != v) or v == "" or pd.isna(v):
        return None
    return pd.Timestamp(v).strftime("%Y-%m-%d")


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _str(v) -> str | None:
    """A CSV cell as a string, or None for a blank/NaN cell (pandas represents
    a blank cell in a non-string-dtype column as `float('nan')`)."""
    if isinstance(v, str) and v:
        return v
    return None


def record_from_row(row) -> DelistRecord:
    bucket = CrspBucket(row["bucket"]) if isinstance(row["bucket"], str) and row["bucket"] else CrspBucket.UNKNOWN
    code = _num(row.get("crsp_code"))
    cik = _num(row.get("cik"))
    succ = row.get("successor_sec_id")
    return DelistRecord(
        ticker=_str(row.get("ticker")) or "", cik=int(cik) if cik is not None else None,
        observed_delist_date=_iso(row.get("last_trade_date")) or _iso(row.get("delist_date")),
        crsp_code=int(code) if code is not None else None, bucket=bucket,
        confidence=_str(row.get("confidence")) or "", reason=_str(row.get("reason")) or "",
        sec_id=str(row["sec_id"]), delist_date=_iso(row.get("delist_date")),
        successor_sec_id=succ if isinstance(succ, str) and succ else None,
    )


def row_payout(row) -> float | None:
    """The DLRET table's terminal_value when this is a merger (covers cash +
    stock consideration); otherwise the raw cash payout, if any."""
    if row.get("bucket") == "merger" and _num(row.get("terminal_value")) is not None:
        return _num(row.get("terminal_value"))
    return _num(row.get("payout_per_share"))


def _is_continuing(row) -> bool:
    """True when `successor_sec_id` equals `sec_id`: the security kept
    trading under the same FIGI (e.g. an exchange transfer), so this row is
    not an exit at all. All three panel splicers below skip such rows."""
    succ = _str(row.get("successor_sec_id"))
    return succ is not None and succ == row["sec_id"]


def inject_terminal_labels(
    panel: pd.DataFrame,
    delistings_csv: str,
    horizon_days: int = 21,
    label_col: str = "LABEL",
    close_col: str = "close",
) -> pd.DataFrame:
    """Inject the delist-aware forward-return label for each delisted security.

    Expects `panel` to be MultiIndex (datetime, instrument) with a `close`
    column, where `instrument` is a `sec_id`. For each delisting:

      * compute the bucket-policy forward return (e.g. −1.0 for compliance);
      * set `panel[label_col]` for the last `horizon_days` observations of
        that security dated on or before its last trade date, so the
        supervised learner sees the realized outcome rather than a censored
        value (and never on a vendor filler row quoted after the security
        stopped trading).

    Returns a new DataFrame; the original is untouched.
    """
    df = panel.copy()
    if label_col not in df.columns:
        df[label_col] = pd.NA
    delistings = load_delistings(delistings_csv)

    for _, row in delistings.iterrows():
        sec_id = row["sec_id"]
        if _is_continuing(row):
            continue
        if sec_id not in df.index.get_level_values("instrument"):
            continue
        slc = df.xs(sec_id, level="instrument", drop_level=False)
        if slc.empty:
            continue
        last_trade = row.get("last_trade_date")
        if pd.notna(last_trade):
            eligible = slc[slc.index.get_level_values("datetime") <= last_trade]
        else:
            eligible = slc
        if eligible.empty:
            continue

        rec = record_from_row(row)
        last_close = _num(row.get("last_trade_close"))
        if last_close is None:
            last_close = float(eligible[close_col].iloc[-1])
        payout = row_payout(row)
        recovery = _num(row.get("recovery_ratio"))
        kw = {"recovery_ratio": recovery} if recovery is not None else {}
        adj = build_train_label_adjustment(rec, last_close, payout, **kw)
        if not adj.keep_in_training:
            continue
        idx_for_sec = eligible.index[-horizon_days:]
        df.loc[idx_for_sec, label_col] = adj.forward_return
    return df


def apply_backtest_exits(
    positions_df: pd.DataFrame,
    delistings_csv: str,
    date_col: str = "date",
    id_col: str = "sec_id",
    price_col: str = "price",
) -> pd.DataFrame:
    """Rewrite the exit-day price per delisted security to bucket policy.

    `positions_df` is long-format: (date, sec_id, price). The exit row is
    the one whose date equals the last trade date (falling back to the
    delist date if the last trade date is absent). If no such row exists
    (e.g. you stopped quoting earlier), no change is made.
    """
    df = positions_df.copy()
    delistings = load_delistings(delistings_csv)
    df[date_col] = pd.to_datetime(df[date_col])

    for _, row in delistings.iterrows():
        sec_id = row["sec_id"]
        if _is_continuing(row):
            continue
        sub = df[df[id_col] == sec_id]
        if sub.empty:
            continue
        exit_date = row.get("last_trade_date")
        if pd.isna(exit_date):
            exit_date = row.get("delist_date")
        if pd.isna(exit_date):
            continue
        exit_date = pd.Timestamp(exit_date)
        mask = (df[id_col] == sec_id) & (df[date_col] == exit_date)
        if not mask.any():
            continue

        rec = record_from_row(row)
        last_close = _num(row.get("last_trade_close"))
        if last_close is None:
            last_close = float(sub.iloc[-1][price_col])
        payout = row_payout(row)
        recovery = _num(row.get("recovery_ratio"))
        kw = {"recovery_ratio": recovery} if recovery is not None else {}
        bx = build_backtest_exit(rec, last_close, payout, **kw)
        df.loc[mask, price_col] = bx.exit_price
    return df


def apply_bmp_corrections(
    panel: pd.DataFrame,
    delistings_csv: str,
    return_col: str = "monthly_return",
    close_col: str = "close",
) -> pd.DataFrame:
    """Splice the BMP 2007 corrected R_delisting_month into a monthly panel.

    For each delisting, find the panel row whose date-level value is the
    month-end containing the security's observed delist date (last trade
    date if present, else delist date), then overwrite `return_col` with
    `(1 + R_partial) * (1 + DLRET) - 1`. If the firm-month must be dropped
    (EXPIRATION, no delist date, invalid prior close), remove the row.

    `panel` is a MultiIndex (date, instrument) DataFrame with month-end
    dates, where `instrument` is a `sec_id`. The last trade close, payout,
    recovery ratio and exchange all come from the `delistings.csv` row; the
    last trade close falls back to the panel's close on the delist-month-end
    row if absent.
    """
    df = panel.copy()
    delistings = load_delistings(delistings_csv)

    rows_to_drop: list[tuple] = []

    for _, row in delistings.iterrows():
        sec_id = row["sec_id"]
        if _is_continuing(row):
            continue
        rec = record_from_row(row)
        if rec.observed_delist_date is None:
            continue
        if sec_id not in df.index.get_level_values("instrument"):
            continue

        slc = df.xs(sec_id, level="instrument", drop_level=False)
        if slc.empty:
            continue

        # Find the month-end on or after the observed delist date that
        # exists in the panel for this security.
        delist_ts = pd.Timestamp(rec.observed_delist_date)
        sec_dates = slc.index.get_level_values("date")
        candidates = sec_dates[sec_dates >= delist_ts]
        if len(candidates) == 0:
            # Panel ends before delist; nothing to splice
            continue
        delist_month_end = candidates.min()

        # Prior month-end row (last row strictly before delist_month_end)
        prior_dates = sec_dates[sec_dates < delist_month_end]
        if len(prior_dates) == 0:
            continue
        prior_month_end = prior_dates.max()

        prior_close = float(df.loc[(prior_month_end, sec_id), close_col])
        provided_last_trade = _num(row.get("last_trade_close"))
        recov = _num(row.get("recovery_ratio"))
        if provided_last_trade is None:
            last_trade_close = float(df.loc[(delist_month_end, sec_id), close_col])
            bucket = rec.bucket
            if (
                bucket is CrspBucket.COMPLIANCE_FAILURE
                or (bucket is CrspBucket.LIQUIDATION and recov is None)
            ):
                warnings.warn(
                    f"apply_bmp_corrections: sec_id={sec_id} ticker={rec.ticker} bucket={bucket.value} "
                    f"has no observed last_trade_close; falling back to panel "
                    f"close_col={close_col!r} at {delist_month_end.date()}. "
                    f"The panel close for a performance-related delisting is often "
                    f"a stale mark and may understate the price collapse — the very "
                    f"bias BMP 2007 is meant to remove. Provide last_trade_close for "
                    f"{sec_id!r} in delistings.csv to suppress this.",
                    stacklevel=2,
                )
        else:
            last_trade_close = provided_last_trade

        ex = normalize_exchange(_str(row.get("exchange")))

        fm = build_firm_month_correction(
            record=rec,
            prior_month_end_close=prior_close,
            last_trade_close=last_trade_close,
            exchange=ex,
            payout_per_share=row_payout(row),
            recovery_ratio=recov,
        )

        if fm.drop:
            rows_to_drop.append((delist_month_end, sec_id))
        else:
            df.loc[(delist_month_end, sec_id), return_col] = fm.firm_month_return

    if rows_to_drop:
        df = df.drop(index=rows_to_drop)

    return df

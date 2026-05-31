"""Train- and backtest-time handling for delisting events.

The two callers are different worlds:

    *Training* turns a corporate-action event into a *label* (forward return) for
    the supervised learning task. The wrong choice silently injects survivorship
    bias of one sign or the other.

    *Backtest* turns the same event into an exit cashflow for a strategy. Errors
    here show up as missing returns, look-ahead, or fictitious capital recovery.

We expose two pure functions that take a `DelistRecord` plus the price panel
and emit (a) a forward-return adjustment for training, (b) an exit cashflow
plus universe-exit date for backtesting.

Conventions
-----------
* All returns are simple (decimal), not log.
* "Last price" = last observed close in the price panel for the ticker.
* "Payout" = cash-equivalent value per share at delist.
* "Forward horizon" = the model's prediction horizon (e.g. 21 trading days).

Train handling per bucket
-------------------------
MERGER                  : forward-return label = (payout / price_at_label) - 1.
                          payout defaults to last_price if unknown (neutral mark).
EXCHANGE_TRANSFER       : drop the ticker's delist event; relink to successor
                          ticker if available. If not, treat as MERGER w/ neutral
                          payout (no return shock).
LIQUIDATION             : forward-return label = recovery_ratio - 1
                          (recovery_ratio defaults to 0.10 conservatively).
COMPLIANCE_FAILURE      : forward-return label = -1.0 (-100%). This is the bias
                          you'd otherwise miss by dropping the row.
EXPIRATION              : drop. Not equity universe.
UNKNOWN                 : conservative: -50%. Flag for manual review.

Backtest handling per bucket
----------------------------
MERGER                  : exit at delist date at min(last_close, payout).
                          Reinvest into cash (or rebalance per portfolio policy).
EXCHANGE_TRANSFER       : continue holding the successor; no cashflow.
LIQUIDATION             : exit at delist date at recovery_ratio * last_close.
COMPLIANCE_FAILURE      : exit at delist date at 0 (full loss). The realistic
                          assumption — by the time a 12d2-2 hits, the OTC mark
                          is illusory.
EXPIRATION              : exit at maturity value (default 0 for equity contexts).
UNKNOWN                 : exit at 0.5 * last_close, flag for review.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Mapping

from .bmp_correction import bmp_firm_month_return, compute_dlret
from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .exchanges import Exchange


DEFAULT_RECOVERY_RATIO = 0.10
DEFAULT_UNKNOWN_TRAIN_RETURN = -0.5
DEFAULT_UNKNOWN_EXIT_FRACTION = 0.5


@dataclass
class TrainLabelAdjustment:
    ticker: str
    bucket: CrspBucket
    delist_date: date
    forward_return: float            # the adjusted label value
    keep_in_training: bool           # False = drop this row from supervision
    notes: str = ""


@dataclass
class BacktestExit:
    ticker: str
    bucket: CrspBucket
    exit_date: date                  # last day position is held (T_exit)
    exit_price: float                # per-share exit value applied at T_exit
    successor_ticker: str | None = None
    notes: str = ""


@dataclass
class FirmMonthReturn:
    """BMP 2007 corrected firm-month return for the delisting month."""
    ticker: str
    bucket: CrspBucket
    exchange: Exchange
    delist_date: date
    firm_month_return: float    # the corrected R_month (NaN means drop)
    r_partial: float            # (last_trade / prior_month_end) - 1
    dlret: float                # cash-out return implied by bucket+exchange
    drop: bool                  # True -> remove this firm-month from panel
    notes: str = ""


def _parse(d: str | date | None) -> date | None:
    if d is None:
        return None
    if isinstance(d, date):
        return d
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except ValueError:
        return None


def build_train_label_adjustment(
    record: DelistRecord,
    last_close: float,
    payout_per_share: float | None = None,
    successor_map: Mapping[str, str] | None = None,
    recovery_ratio: float = DEFAULT_RECOVERY_RATIO,
) -> TrainLabelAdjustment:
    """Return the forward-return label to use for the *last* training row of `ticker`."""
    dd = _parse(record.observed_delist_date)
    if dd is None:
        return TrainLabelAdjustment(
            ticker=record.ticker,
            bucket=record.bucket,
            delist_date=date.today(),
            forward_return=0.0,
            keep_in_training=False,
            notes="No delist date; dropping from training",
        )

    bucket = record.bucket
    if bucket is CrspBucket.MERGER:
        payout = payout_per_share if payout_per_share is not None else last_close
        ret = (payout / last_close) - 1.0 if last_close > 0 else 0.0
        return TrainLabelAdjustment(
            ticker=record.ticker, bucket=bucket, delist_date=dd,
            forward_return=ret, keep_in_training=True,
            notes=f"M&A: payout {payout:.4f} vs last_close {last_close:.4f}",
        )

    if bucket is CrspBucket.EXCHANGE_TRANSFER:
        successor = (successor_map or {}).get(record.ticker)
        if successor:
            return TrainLabelAdjustment(
                ticker=record.ticker, bucket=bucket, delist_date=dd,
                forward_return=0.0, keep_in_training=False,
                notes=f"Exchange transfer; re-link to {successor}",
            )
        return TrainLabelAdjustment(
            ticker=record.ticker, bucket=bucket, delist_date=dd,
            forward_return=0.0, keep_in_training=False,
            notes="Exchange transfer; no successor mapping. Dropping.",
        )

    if bucket is CrspBucket.LIQUIDATION:
        ret = (recovery_ratio - 1.0)
        return TrainLabelAdjustment(
            ticker=record.ticker, bucket=bucket, delist_date=dd,
            forward_return=ret, keep_in_training=True,
            notes=f"Liquidation: assumed recovery {recovery_ratio:.0%}",
        )

    if bucket is CrspBucket.COMPLIANCE_FAILURE:
        return TrainLabelAdjustment(
            ticker=record.ticker, bucket=bucket, delist_date=dd,
            forward_return=-1.0, keep_in_training=True,
            notes="Compliance failure: -100% terminal return",
        )

    if bucket is CrspBucket.EXPIRATION:
        return TrainLabelAdjustment(
            ticker=record.ticker, bucket=bucket, delist_date=dd,
            forward_return=0.0, keep_in_training=False,
            notes="Expiration security; not equity universe",
        )

    return TrainLabelAdjustment(
        ticker=record.ticker, bucket=bucket, delist_date=dd,
        forward_return=DEFAULT_UNKNOWN_TRAIN_RETURN, keep_in_training=True,
        notes="Unknown bucket: applying conservative -50% with review flag",
    )


def build_backtest_exit(
    record: DelistRecord,
    last_close: float,
    payout_per_share: float | None = None,
    successor_map: Mapping[str, str] | None = None,
    recovery_ratio: float = DEFAULT_RECOVERY_RATIO,
) -> BacktestExit:
    dd = _parse(record.observed_delist_date) or date.today()
    bucket = record.bucket

    if bucket is CrspBucket.MERGER:
        payout = payout_per_share if payout_per_share is not None else last_close
        return BacktestExit(
            ticker=record.ticker, bucket=bucket, exit_date=dd,
            exit_price=min(last_close, payout) if payout < last_close else payout,
            notes=f"M&A exit at payout {payout:.4f}",
        )

    if bucket is CrspBucket.EXCHANGE_TRANSFER:
        successor = (successor_map or {}).get(record.ticker)
        return BacktestExit(
            ticker=record.ticker, bucket=bucket, exit_date=dd,
            exit_price=last_close, successor_ticker=successor,
            notes="Exchange transfer: hold continues in successor",
        )

    if bucket is CrspBucket.LIQUIDATION:
        return BacktestExit(
            ticker=record.ticker, bucket=bucket, exit_date=dd,
            exit_price=recovery_ratio * last_close,
            notes=f"Liquidation exit at {recovery_ratio:.0%} of last close",
        )

    if bucket is CrspBucket.COMPLIANCE_FAILURE:
        return BacktestExit(
            ticker=record.ticker, bucket=bucket, exit_date=dd,
            exit_price=0.0, notes="Compliance failure: total loss",
        )

    if bucket is CrspBucket.EXPIRATION:
        return BacktestExit(
            ticker=record.ticker, bucket=bucket, exit_date=dd,
            exit_price=0.0, notes="Expiration: zero exit value",
        )

    return BacktestExit(
        ticker=record.ticker, bucket=bucket, exit_date=dd,
        exit_price=DEFAULT_UNKNOWN_EXIT_FRACTION * last_close,
        notes="Unknown: 50% haircut exit with review flag",
    )


def apply_to_panel(
    records: Iterable[DelistRecord],
    last_closes: Mapping[str, float],
    payouts: Mapping[str, float] | None = None,
    successor_map: Mapping[str, str] | None = None,
) -> tuple[list[TrainLabelAdjustment], list[BacktestExit]]:
    payouts = payouts or {}
    train_adj: list[TrainLabelAdjustment] = []
    bt_exits: list[BacktestExit] = []
    for r in records:
        lc = last_closes.get(r.ticker, 0.0)
        po = payouts.get(r.ticker)
        train_adj.append(build_train_label_adjustment(r, lc, po, successor_map))
        bt_exits.append(build_backtest_exit(r, lc, po, successor_map))
    return train_adj, bt_exits


def build_firm_month_correction(
    record: DelistRecord,
    prior_month_end_close: float,
    last_trade_close: float,
    exchange: Exchange | None,
    payout_per_share: float | None = None,
    recovery_ratio: float | None = None,
    stock_ratio: float | None = None,
    acquirer_price: float | None = None,
) -> FirmMonthReturn:
    """Compute the BMP 2007 corrected firm-month return for one delisting.

    Implements `R_month = (1 + R_partial) * (1 + DLRET) - 1`, where
    `R_partial` is the price return from prior month-end close to last
    trade, and `DLRET` is the synthesized cash-out return per bucket
    (see `bmp_correction.compute_dlret`).

    `exchange=None` falls back to `Exchange.OTHER`, which uses the
    conservative Nasdaq Shumway constant for performance delistings.

    The returned `drop` field is the canonical caller signal:
    `drop=True` means the firm-month is unrecoverable (EXPIRATION, no
    delist date, degenerate prices, negative payout/recovery) and the
    row should be removed from the panel. By invariant,
    `drop == math.isnan(firm_month_return)`.
    """
    dd = _parse(record.observed_delist_date)
    ex = exchange if exchange is not None else Exchange.OTHER
    if dd is None:
        return FirmMonthReturn(
            ticker=record.ticker, bucket=record.bucket, exchange=ex,
            delist_date=date.today(),
            firm_month_return=float("nan"), r_partial=float("nan"),
            dlret=float("nan"), drop=True,
            notes="No delist date; dropping from panel",
        )

    dlret = compute_dlret(
        bucket=record.bucket, exchange=ex,
        last_trade_close=last_trade_close,
        payout_per_share=payout_per_share,
        recovery_ratio=recovery_ratio,
        stock_ratio=stock_ratio,
        acquirer_price=acquirer_price,
    )
    r_month = bmp_firm_month_return(
        prior_month_end_close=prior_month_end_close,
        last_trade_close=last_trade_close,
        bucket=record.bucket, exchange=ex,
        payout_per_share=payout_per_share,
        recovery_ratio=recovery_ratio,
        stock_ratio=stock_ratio,
        acquirer_price=acquirer_price,
    )
    drop = math.isnan(r_month)
    assert drop == math.isnan(r_month), "drop must agree with NaN return"

    r_partial = (
        (last_trade_close / prior_month_end_close) - 1.0
        if prior_month_end_close > 0 else float("nan")
    )

    return FirmMonthReturn(
        ticker=record.ticker, bucket=record.bucket, exchange=ex,
        delist_date=dd,
        firm_month_return=r_month, r_partial=r_partial, dlret=dlret,
        drop=drop,
        notes=(
            f"BMP({record.bucket.value}, {ex.value}): "
            f"R_partial={r_partial:.4f}, DLRET={dlret:.4f}"
            if not drop else
            f"Dropped ({record.bucket.value}): NaN firm-month return"
        ),
    )

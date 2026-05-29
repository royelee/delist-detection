"""Delist Detection: classify CRSP-style delisting reasons from SEC EDGAR."""

from .crsp_codes import CrspBucket, DLST_CODE_TO_BUCKET, bucket_for_code
from .edgar import EdgarClient, EdgarSubmission
from .ticker_resolver import TickerResolver
from .classifier import DelistClassifier, DelistRecord
from .exchanges import Exchange, normalize_exchange
from .bmp_correction import (
    SHUMWAY_NYSE_AMEX, SHUMWAY_NASDAQ,
    compute_dlret, bmp_firm_month_return,
)
from .handling import (
    TrainLabelAdjustment, BacktestExit, FirmMonthReturn,
    build_train_label_adjustment, build_backtest_exit, apply_to_panel,
    build_firm_month_correction,
)
from .payout_extractor import PayoutExtractor, PayoutResult

__all__ = [
    "CrspBucket",
    "DLST_CODE_TO_BUCKET",
    "bucket_for_code",
    "EdgarClient",
    "EdgarSubmission",
    "TickerResolver",
    "DelistClassifier",
    "DelistRecord",
    "TrainLabelAdjustment",
    "BacktestExit",
    "build_train_label_adjustment",
    "build_backtest_exit",
    "apply_to_panel",
    "Exchange",
    "normalize_exchange",
    "SHUMWAY_NYSE_AMEX",
    "SHUMWAY_NASDAQ",
    "compute_dlret",
    "bmp_firm_month_return",
    "FirmMonthReturn",
    "build_firm_month_correction",
    "PayoutExtractor",
    "PayoutResult",
]

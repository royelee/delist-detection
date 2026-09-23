from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.handling import (
    adjustments_from_rows,
    build_backtest_exit,
    build_train_label_adjustment,
)


def _rec(bucket: CrspBucket, code: int | None = None, successor_sec_id: str | None = None) -> DelistRecord:
    return DelistRecord(
        ticker="TST", cik=1, observed_delist_date="2024-06-30",
        crsp_code=code, bucket=bucket, confidence="high", reason="test",
        successor_sec_id=successor_sec_id,
    )


def test_merger_uses_payout_for_training_label():
    rec = _rec(CrspBucket.MERGER, 231)
    adj = build_train_label_adjustment(rec, last_close=100.0, payout_per_share=113.0)
    assert adj.keep_in_training is True
    assert abs(adj.forward_return - 0.13) < 1e-9


def test_merger_without_payout_is_neutral():
    rec = _rec(CrspBucket.MERGER, 231)
    adj = build_train_label_adjustment(rec, last_close=100.0)
    assert adj.forward_return == 0.0


def test_compliance_failure_is_minus_100():
    rec = _rec(CrspBucket.COMPLIANCE_FAILURE, 570)
    adj = build_train_label_adjustment(rec, last_close=10.0)
    assert adj.forward_return == -1.0
    assert adj.keep_in_training is True


def test_liquidation_uses_recovery_default():
    rec = _rec(CrspBucket.LIQUIDATION, 470)
    adj = build_train_label_adjustment(rec, last_close=20.0)
    assert abs(adj.forward_return - (-0.9)) < 1e-9


def test_exchange_transfer_drops_when_no_successor():
    rec = _rec(CrspBucket.EXCHANGE_TRANSFER, 304)
    adj = build_train_label_adjustment(rec, last_close=5.0)
    assert adj.keep_in_training is False


def test_exchange_transfer_with_successor_drops_and_notes_relink():
    rec = _rec(CrspBucket.EXCHANGE_TRANSFER, 304, successor_sec_id="TST2")
    adj = build_train_label_adjustment(rec, last_close=5.0)
    assert adj.keep_in_training is False
    assert "TST2" in adj.notes


def test_expiration_is_dropped():
    rec = _rec(CrspBucket.EXPIRATION, 600)
    adj = build_train_label_adjustment(rec, last_close=1.0)
    assert adj.keep_in_training is False


def test_backtest_compliance_exit_is_zero():
    rec = _rec(CrspBucket.COMPLIANCE_FAILURE, 560)
    bx = build_backtest_exit(rec, last_close=2.0)
    assert bx.exit_price == 0.0


def test_backtest_merger_exit_uses_payout():
    rec = _rec(CrspBucket.MERGER, 231)
    bx = build_backtest_exit(rec, last_close=100.0, payout_per_share=113.0)
    assert bx.exit_price == 113.0


def test_backtest_exchange_transfer_continues_position():
    rec = _rec(CrspBucket.EXCHANGE_TRANSFER, 304, successor_sec_id="TST_OTC")
    bx = build_backtest_exit(rec, last_close=50.0)
    assert bx.exit_price == 50.0
    assert bx.successor_sec_id == "TST_OTC"


def test_adjustments_from_rows_skips_rows_without_last_trade_close():
    rows = [
        {"sec_id": "BBG1", "ticker": "ALPHA", "bucket": "merger", "confidence": "high", "reason": "test",
         "last_trade_date": "2024-06-28", "last_trade_close": "100.0", "terminal_value": "113.0"},
        {"sec_id": "BBG2", "ticker": "BETA", "bucket": "compliance_failure", "confidence": "high", "reason": "test",
         "last_trade_date": "2024-06-28"},  # no last_trade_close -> skipped
    ]
    train, exits = adjustments_from_rows(rows)
    assert len(train) == 1 and len(exits) == 1
    assert train[0].ticker == "ALPHA"
    assert abs(train[0].forward_return - 0.13) < 1e-9
    assert exits[0].exit_price == 113.0

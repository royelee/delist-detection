import math
import pytest

from delist_detection.crsp_codes import CrspBucket
from delist_detection.exchanges import Exchange
from delist_detection.dlret import (
    DlretMethod, DlretResult, resolve_dlret, compute_dlret,
    SHUMWAY_NYSE_AMEX, SHUMWAY_NASDAQ,
)


def test_merger_cash_only():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 100.0, payout_per_share=113.0)
    assert r.method is DlretMethod.CASH_ONLY
    assert r.terminal_value == pytest.approx(113.0)
    assert r.value == pytest.approx(0.13)


def test_merger_cash_plus_stock_aet_cvs():
    # AET->CVS: $145 cash + 0.8378 CVS @ $80, last AET $190 -> +11.6%
    r = resolve_dlret(
        CrspBucket.MERGER, Exchange.NYSE, 190.0,
        payout_per_share=145.0, stock_ratio=0.8378, acquirer_price=80.0,
    )
    assert r.method is DlretMethod.CASH_PLUS_STOCK
    assert r.terminal_value == pytest.approx(212.024)
    assert r.value == pytest.approx(0.11592, abs=1e-4)


def test_merger_stock_only():
    r = resolve_dlret(
        CrspBucket.MERGER, Exchange.NYSE, 100.0,
        stock_ratio=1.5, acquirer_price=80.0,
    )
    assert r.method is DlretMethod.STOCK_ONLY
    assert r.terminal_value == pytest.approx(120.0)
    assert r.value == pytest.approx(0.20)


def test_merger_no_consideration_abstains_neutral():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 100.0)
    assert r.method is DlretMethod.ABSTAIN_NO_CONSIDERATION
    assert r.value == 0.0
    assert r.terminal_value is None


def test_merger_consideration_without_price_needs_last_trade():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 0.0, payout_per_share=113.0)
    assert r.method is DlretMethod.NEEDS_LAST_TRADE
    assert math.isnan(r.value)


def test_exchange_transfer_zero():
    r = resolve_dlret(CrspBucket.EXCHANGE_TRANSFER, Exchange.NYSE, 0.0)
    assert r.method is DlretMethod.EXCHANGE_TRANSFER_ZERO
    assert r.value == 0.0


def test_liquidation_recovery():
    r = resolve_dlret(CrspBucket.LIQUIDATION, Exchange.NYSE, 10.0, recovery_ratio=0.20)
    assert r.method is DlretMethod.RECOVERY_RATIO
    assert r.value == pytest.approx(-0.80)
    assert r.terminal_value == pytest.approx(2.0)


def test_liquidation_no_recovery_shumway():
    r = resolve_dlret(CrspBucket.LIQUIDATION, Exchange.NASDAQ, 10.0)
    assert r.method is DlretMethod.SHUMWAY_NASDAQ
    assert r.value == SHUMWAY_NASDAQ


def test_compliance_shumway_by_venue():
    assert resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.NYSE, 10.0).method is DlretMethod.SHUMWAY_NYSE_AMEX
    assert resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.AMEX, 10.0).value == SHUMWAY_NYSE_AMEX
    assert resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.NASDAQ, 10.0).value == SHUMWAY_NASDAQ
    assert resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.OTHER, 10.0).value == SHUMWAY_NASDAQ


def test_expiration_dropped():
    r = resolve_dlret(CrspBucket.EXPIRATION, Exchange.NYSE, 10.0)
    assert r.method is DlretMethod.DROPPED_EXPIRATION
    assert math.isnan(r.value)


def test_worthless_method_exists_but_unused_in_v1():
    # Reserved enum member; resolve_dlret never emits it in v1.
    assert DlretMethod.WORTHLESS.value == "worthless"


def test_compute_dlret_facade_matches_value():
    assert compute_dlret(
        bucket=CrspBucket.MERGER, exchange=Exchange.NYSE,
        last_trade_close=100.0, payout_per_share=113.0,
    ) == pytest.approx(0.13)


def test_negative_payout_is_nan():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 100.0, payout_per_share=-5.0)
    assert math.isnan(r.value)


def test_zero_payout_is_total_wipe():
    r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 100.0, payout_per_share=0.0)
    assert r.value == pytest.approx(-1.0)
    assert r.method is DlretMethod.CASH_ONLY


def test_merger_partial_stock_terms_raises():
    # A dangling stock term (stock_ratio without acquirer_price) must fail loud
    # rather than silently understating DLRET to the cash floor.
    with pytest.raises(ValueError, match="under-specified"):
        resolve_dlret(
            CrspBucket.MERGER, Exchange.NYSE, 190.0,
            payout_per_share=145.0, stock_ratio=0.8378,
            # acquirer_price intentionally omitted
        )


def test_merger_no_consideration_bad_price_stays_nan_drop():
    # Back-compat: MERGER with no consideration AND no valid price is a NaN
    # drop (the original compute_dlret price guard), never a 0.0 neutral mark.
    for bad in (0.0, -5.0, None):
        r = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE,
                          last_trade_close=bad)
        assert math.isnan(r.value)
        assert math.isnan(compute_dlret(CrspBucket.MERGER, Exchange.NYSE, bad))
    # but with a valid price, no consideration is a neutral 0.0 abstain
    ok = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, last_trade_close=10.0)
    assert ok.value == 0.0
    assert ok.method is DlretMethod.ABSTAIN_NO_CONSIDERATION

import math
import pytest

from delist_detection.outputs.reconstruction import DelistRecord
from delist_detection.vocabulary.crsp_codes import CrspBucket
from delist_detection.outputs.dlret import DlretMethod, ValueInputs
from delist_detection.vocabulary.exchanges import Exchange
from delist_detection.outputs.reconstruction import (
    for_delisting, delisting_row, enrich, EnrichedDelistRecord,
    load_float_overrides, load_merger_terms_overrides,
)
from delist_detection.outputs.store import DelistingKey


def _rec(ticker="AET", bucket=CrspBucket.MERGER, code=241, date="2018-11-28"):
    return DelistRecord(
        ticker=ticker, cik=1122304, observed_delist_date=date,
        crsp_code=code, bucket=bucket, confidence="high",
        reason="M&A 2.01+3.01+5.01", evidence={},
    )


def _drec(sec_id, delist_date, ticker="AET", bucket=CrspBucket.MERGER, code=241):
    """A record carrying sec_id/delist_date, for delisting_row tests."""
    return DelistRecord(
        ticker=ticker, cik=1122304, observed_delist_date=delist_date,
        crsp_code=code, bucket=bucket, confidence="high",
        reason="M&A 2.01+3.01+5.01", evidence={},
        sec_id=sec_id, delist_date=delist_date,
    )


_PROVENANCE = ("acquirer_ticker", "payout_source", "extra_flags")


def _enrich(record, *, exchange=Exchange.OTHER, last_trade_close=None, **kw):
    """enrich with the record's own bucket: `kw` holds ValueInputs' fields and enrich's provenance keywords."""
    prov = {k: kw.pop(k) for k in _PROVENANCE if k in kw}
    return enrich(record, ValueInputs(record.bucket, exchange, last_trade_close, deregistered=record.deregistered,
                                      **kw), **prov)


def test_enrich_merger_cash_plus_stock():
    e = _enrich(
        _rec(), exchange=Exchange.NYSE, last_trade_close=190.0,
        payout_per_share=145.0, stock_ratio=0.8378, acquirer_price=80.0,
        acquirer_ticker="CVS", payout_source="manual", payout_confidence="high",
    )
    assert isinstance(e, EnrichedDelistRecord)
    assert e.dlret_method is DlretMethod.CASH_PLUS_STOCK
    assert e.dlret == pytest.approx(0.11592, abs=1e-4)
    assert e.terminal_value == pytest.approx(212.024)
    assert e.acquirer_ticker == "CVS"
    assert e.dlret_confidence == "medium"   # stock leg depends on a market price


def test_enrich_merger_cash_only_inherits_payout_confidence():
    e = _enrich(
        _rec(code=233), exchange=Exchange.NYSE, last_trade_close=100.0,
        payout_per_share=113.0, payout_confidence="high",
    )
    assert e.dlret_method is DlretMethod.CASH_ONLY
    assert e.dlret_confidence == "high"


def test_enrich_needs_last_trade_is_low_confidence_and_nan():
    e = _enrich(_rec(), exchange=Exchange.NYSE, last_trade_close=None, payout_per_share=113.0)
    assert e.dlret_method is DlretMethod.NEEDS_LAST_TRADE
    assert math.isnan(e.dlret)
    assert e.dlret_confidence == "low"


def test_enrich_carries_classification_fields():
    e = _enrich(_rec(ticker="ABMD", code=231), exchange=Exchange.NASDAQ, last_trade_close=300.0,
               payout_per_share=380.0)
    assert e.ticker == "ABMD"
    assert e.crsp_code == 231
    assert e.bucket is CrspBucket.MERGER
    assert e.reason == "M&A 2.01+3.01+5.01"


def test_enrich_copies_sec_id_and_delist_date():
    rec = _drec("BBG000BGRY34", "2018-11-28", ticker="AET")
    e = _enrich(rec, exchange=Exchange.NYSE, last_trade_close=190.0, payout_per_share=145.0)
    assert e.sec_id == "BBG000BGRY34"
    assert e.delist_date == "2018-11-28"




def test_row_blanks_nan_and_none():
    e = _enrich(_drec("BBG_AET", "2018-11-28"), exchange=Exchange.NYSE, last_trade_close=None,
               payout_per_share=113.0)
    row = delisting_row(e)
    assert math.isnan(row["dlret"])          # a raw NaN, not pre-formatted to a string
    assert row["terminal_value"] is None
    assert row["dlret_method"] == "needs_last_trade"






def test_lookup_tuple_wins_over_bare_key():
    # When a map has both a per-event tuple key and a bare-sec_id fallback,
    # the tuple wins; a different date falls back to the bare-sec_id default.
    m = {("BBG_ALTR", "2015-12-28"): 50.0, "BBG_ALTR": 99.0}
    assert for_delisting(m, ("BBG_ALTR", "2015-12-28")) == 50.0   # tuple wins
    assert for_delisting(m, DelistingKey("BBG_ALTR", "2099-01-01")) == 99.0   # fallback to bare sec_id


def test_load_merger_terms_overrides(tmp_path):
    p = tmp_path / "terms.csv"
    p.write_text(
        "sec_id,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker\n"
        "BBG_AET,145,0.8378,80,CVS\n"
        "BBG_ABMD,380,,,\n"
    )
    terms = load_merger_terms_overrides(p)
    assert terms["BBG_AET"] == {"cash_per_share": 145.0, "stock_ratio": 0.8378,
                                "acquirer_price": 80.0, "acquirer_ticker": "CVS"}
    assert terms["BBG_ABMD"] == {"cash_per_share": 380.0}  # blanks omitted


def test_load_float_overrides_reads_values(tmp_path):
    p = tmp_path / "lt.csv"
    p.write_text("sec_id,last_trade_close\nBBG_AET,190\nBBG_FOO,\n")
    assert load_float_overrides(p, "last_trade_close") == {"BBG_AET": 190.0}  # blank-value row skipped


def test_load_float_overrides_raises_on_missing_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("sec_id,close\nBBG_AET,190\n")  # 'close' != 'last_trade_close'
    with pytest.raises(ValueError):
        load_float_overrides(p, "last_trade_close")


def test_merger_no_consideration_valid_price_assumes_par():
    # "No empty DLRET" rule: a completed MERGER with a valid last_trade_close but
    # no computable consideration assumes terminal = last price (arbitrage closed
    # the gap to the deal value), so DLRET = 0 is emitted as ASSUMED_PAR at low
    # confidence — filled, not blank, and self-documenting (not a silent computed 0).
    e = _enrich(_drec("BBG_AET", "2018-11-28"), exchange=Exchange.NYSE, last_trade_close=10.0)
    assert e.dlret_method is DlretMethod.ASSUMED_PAR
    assert e.dlret == 0.0
    assert e.dlret_confidence == "low"
    row = delisting_row(e)
    assert row["dlret"] == 0.0   # filled (was blank under the old abstain rule)


def test_expiration_with_last_price_assumes_par():
    # Non-equity/fund closures (CRSP 6xx) redeem at NAV ≈ last price → DLRET ≈ 0.
    e = _enrich(_drec("BBG_X", "2020-01-02", code=600, bucket=CrspBucket.EXPIRATION), exchange=Exchange.NYSE,
               last_trade_close=25.0)
    assert e.dlret_method is DlretMethod.ASSUMED_PAR
    assert e.dlret == 0.0
    assert delisting_row(e)["dlret"] == 0.0


def test_no_consideration_no_price_stays_blank():
    # Without a last price there is no denominator, so par cannot be assumed —
    # the cell stays a NaN row value that renders blank in the abstain case.
    e = _enrich(_drec("BBG_AET", "2018-11-28"), exchange=Exchange.NYSE, last_trade_close=None)
    assert math.isnan(e.dlret)
    assert delisting_row(e)["dlret"] is None


def test_load_merger_terms_overrides_raises_on_partial_stock_leg(tmp_path):
    p = tmp_path / "bad_terms.csv"
    p.write_text(
        "sec_id,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker\n"
        "BBG_AET,145,0.8378,,CVS\n"  # stock_ratio present but acquirer_price blank
    )
    with pytest.raises(ValueError, match="incomplete stock leg"):
        load_merger_terms_overrides(p)


def test_cash_only_invalid_payout_confidence_yields_medium():
    # An empty or invalid payout_confidence on a CASH_ONLY result must yield
    # "medium" (a valid tier), not propagate junk or silently default "high".
    e_empty = _enrich(
        _rec(code=233), exchange=Exchange.NYSE, last_trade_close=100.0,
        payout_per_share=113.0, payout_confidence="",
    )
    assert e_empty.dlret_method is DlretMethod.CASH_ONLY
    assert e_empty.dlret_confidence == "medium"

    e_junk = _enrich(
        _rec(code=233), exchange=Exchange.NYSE, last_trade_close=100.0,
        payout_per_share=113.0, payout_confidence="unknown_tier",
    )
    assert e_junk.dlret_confidence == "medium"


def test_load_float_overrides_with_date_column_produces_tuple_keys(tmp_path):
    p = tmp_path / "lt.csv"
    p.write_text(
        "sec_id,delist_date,last_trade_close\n"
        "BBG_ALTR,2015-12-28,50.0\n"
        "BBG_ALTR,,90.0\n"   # blank date -> bare sec_id key
    )
    result = load_float_overrides(p, "last_trade_close")
    assert result[("BBG_ALTR", "2015-12-28")] == 50.0
    assert result["BBG_ALTR"] == 90.0


def test_load_merger_terms_overrides_with_date_column_produces_tuple_keys(tmp_path):
    p = tmp_path / "terms.csv"
    p.write_text(
        "sec_id,delist_date,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker\n"
        "BBG_ALTR,2015-12-28,54.0,,,\n"   # per-event key
        "BBG_ALTR,,99.0,,,\n"             # blank date -> bare sec_id key
    )
    result = load_merger_terms_overrides(p)
    assert result[("BBG_ALTR", "2015-12-28")] == {"cash_per_share": 54.0}
    assert result["BBG_ALTR"] == {"cash_per_share": 99.0}


def test_unknown_deregistered_with_a_price_is_assumed_par():
    rec = DelistRecord("LIQ", 1, "2019-11-06", None, CrspBucket.UNKNOWN, "low", "x",
                       {"deregistered": True, "flags": ["no_evidence_default"]})
    e = _enrich(rec, last_trade_close=19.63)
    assert e.dlret == 0.0 and e.dlret_method is DlretMethod.ASSUMED_PAR


def test_unknown_without_deregistration_stays_blank():
    rec = DelistRecord("SKYF", None, "2021-08-24", None, CrspBucket.UNKNOWN, "none", "No CIK", {})
    e = _enrich(rec, last_trade_close=0.001)
    assert e.dlret_method is DlretMethod.UNKNOWN


def test_review_flags_joins_flags():
    rec = DelistRecord("X", 1, "2020-01-02", 570, CrspBucket.COMPLIANCE_FAILURE, "medium", "r",
                       {"flags": ["frozen_tail:120"]})
    e = _enrich(rec, last_trade_close=58.97, extra_flags=("payout_gate_failed:25",))
    row = delisting_row(e)
    assert row["review_flags"] == "frozen_tail:120;payout_gate_failed:25;distress_at_normal_price"


def test_no_flags_is_an_empty_cell():
    rec = DelistRecord("Y", 1, "2020-01-02", 231, CrspBucket.MERGER, "high", "r", {})
    assert delisting_row(_enrich(rec, last_trade_close=10.0, payout_per_share=10.0))["review_flags"] == ""


def test_a_merger_left_at_par_is_flagged_for_review():
    # R1: a payout that is never found lands at par unseen; review.csv must list it.
    rec = DelistRecord("NOPAY", 1, "2020-01-02", 231, CrspBucket.MERGER, "medium", "r", {})
    e = _enrich(rec, last_trade_close=42.0)
    assert e.dlret_method is DlretMethod.ASSUMED_PAR
    assert "merger_at_par" in e.review_flags


def test_a_merger_with_a_payout_is_not_flagged_at_par():
    rec = DelistRecord("PAID", 1, "2020-01-02", 231, CrspBucket.MERGER, "high", "r", {})
    e = _enrich(rec, last_trade_close=42.0, payout_per_share=45.0)
    assert e.dlret_method is not DlretMethod.ASSUMED_PAR
    assert "merger_at_par" not in e.review_flags


def test_a_non_merger_par_row_is_not_flagged_merger_at_par():
    rec = DelistRecord("EXPIRE", 1, "2020-01-02", 600, CrspBucket.EXPIRATION, "high", "r", {})
    e = _enrich(rec, last_trade_close=10.0)
    assert e.dlret_method is DlretMethod.ASSUMED_PAR
    assert "merger_at_par" not in e.review_flags


def test_an_otc_print_values_a_compliance_failure_row():
    rec = _drec("BBG_X", "2020-03-02", ticker="X", bucket=CrspBucket.COMPLIANCE_FAILURE, code=550)
    e = _enrich(rec, last_trade_close=2.0, otc_print=0.5)
    assert e.dlret_method is DlretMethod.OTC_PRINT
    assert round(e.dlret, 6) == -0.75


def test_a_plan_value_row_is_graded_medium():
    """Step 10's declared fix: a plan_stock row's dlret_confidence is medium, like an OTC print's (it was low)."""
    rec = _drec("BBG_W", "2025-09-15", ticker="WOLF", bucket=CrspBucket.LIQUIDATION, code=470)
    e = _enrich(rec, exchange=Exchange.NYSE, last_trade_close=1.85, plan_value=0.5)
    row = delisting_row(e)
    assert (row["dlret_method"], row["dlret_confidence"]) == ("plan_stock", "medium")


def test_enrich_refuses_value_inputs_of_another_bucket():
    with pytest.raises(ValueError, match="bucket"):
        enrich(_rec(), ValueInputs(CrspBucket.LIQUIDATION, Exchange.NYSE, 10.0))

import pytest

from delist_detection.crsp_codes import DLST_CODE_TO_BUCKET
from delist_detection.exit_kind import (DROP_REASONS, EXIT_KINDS, ending_fields, is_continuation, is_distress,
                                        is_real_ending)
from lifecycle_tables import ending


def test_a_bankruptcy_is_dropped_for_bankruptcy_with_its_mark_as_a_fill():
    f = ending_fields(ending("S", "2020-05-11", "liquidation", dlret="-0.550000", method="shumway_nasdaq",
                             crsp_code="470"))
    assert (f.exit_kind, f.drop_reason, f.dlret, f.dlret_fill) == ("dropped", "bankruptcy", "", "-0.550000")


def test_a_liquidation_without_the_bankruptcy_code_stays_a_liquidation():
    f = ending_fields(ending("S", "2020-05-11", "liquidation", crsp_code="400"))
    assert (f.exit_kind, f.drop_reason) == ("liquidation", "")


@pytest.mark.parametrize("code,reason", [("573", "sec_order"), ("580", "filings_fees"), ("570", "guidelines"),
                                         ("520", "moved_otc"), ("500", "")])
def test_a_compliance_failure_is_dropped_for_the_reason_its_code_names(code, reason):
    f = ending_fields(ending("S", "2012-05-01", "compliance_failure", crsp_code=code))
    assert (f.exit_kind, f.drop_reason) == ("dropped", reason)


def test_a_measured_value_stays_dlret_and_assumed_par_is_a_fill():
    cash = ending_fields(ending("S", "2018-11-29", dlret="0.110000", method="cash_only", crsp_code="231"))
    par = ending_fields(ending("S", "2018-11-29", dlret="0.000000", method="assumed_par", crsp_code="231"))
    assert (cash.exit_kind, cash.dlret, cash.dlret_fill) == ("merger", "0.110000", "")
    assert (par.dlret, par.dlret_fill) == ("", "0.000000")


def test_a_continuation_has_no_value_and_a_transfer_keeps_its_zero_as_a_fill():
    cont = ending_fields(ending("S", "2015-10-02", "exchange_transfer", successor="T", dlret="0.000000",
                                method="exchange_transfer_zero", crsp_code="304"))
    xfer = ending_fields(ending("S", "2015-10-02", "exchange_transfer", dlret="0.000000",
                                method="exchange_transfer_zero", crsp_code="304"))
    assert (cont.exit_kind, cont.continuation, cont.dlret, cont.dlret_fill) == ("exchange", True, "", "")
    assert (xfer.exit_kind, xfer.continuation, xfer.dlret, xfer.dlret_fill) == ("exchange", False, "", "0.000000")


def test_a_successor_that_is_the_security_itself_is_not_a_continuation():
    assert not ending_fields(ending("S", "2019-03-20", "merger", successor="S")).continuation


def test_unknown_asserts_no_kind_and_a_blank_value_stays_blank():
    f = ending_fields(ending("S", "2009-03-08", "unknown", method="needs_last_trade"))
    assert (f.exit_kind, f.drop_reason, f.dlret, f.dlret_fill) == ("", "", "", "")


def test_distress_is_a_liquidation_or_a_drop_that_carries_a_harsh_mark():
    assert is_distress(ending("S", "2020-05-11", "liquidation", crsp_code="470"))
    assert is_distress(ending("S", "2020-05-11", "liquidation", crsp_code="400"))
    assert is_distress(ending("S", "2012-05-01", "compliance_failure", crsp_code="580"))
    assert is_distress(ending("S", "2012-05-01", "compliance_failure", crsp_code="500"))
    assert not is_distress(ending("S", "2012-05-01", "compliance_failure", crsp_code="520"))
    assert not is_distress(ending("S", "2018-11-29", "merger", crsp_code="231"))


def test_every_code_maps_into_the_contract_vocabulary():
    for code, bucket in DLST_CODE_TO_BUCKET.items():
        if bucket.value == "active":
            continue
        f = ending_fields(ending("S", "2010-01-04", bucket.value, crsp_code=str(code)))
        assert f.exit_kind in EXIT_KINDS
        assert f.drop_reason == "" or (f.exit_kind == "dropped" and f.drop_reason in DROP_REASONS)


def test_an_otc_print_value_is_a_measured_dlret_not_a_fill():
    f = ending_fields(ending("S", "2012-05-01", "compliance_failure", dlret="-0.750000", method="otc_print",
                             crsp_code="500"))
    assert (f.dlret, f.dlret_fill) == ("-0.750000", "")


def test_a_real_ending_and_a_continuation_are_read_from_the_successor_once():
    """The one definition every reader of delistings.csv asks: a security that went on (its own successor) has no
    real ending; a successor other than itself is a continuation; a blank successor is a real ending, no
    continuation."""
    went_on = ending("S", "2019-03-30", "merger", successor="S")
    moved = ending("S", "2015-10-12", "exchange_transfer", successor="T")
    ended = ending("S", "2018-11-29", "merger")
    assert [is_real_ending(r) for r in (went_on, moved, ended)] == [False, True, True]
    assert [is_continuation(r) for r in (went_on, moved, ended)] == [False, True, False]

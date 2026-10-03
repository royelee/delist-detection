from datetime import date

from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarSubmission
from delist_detection.end_of_era import CONTINUED, EraSignals, resolve, signals

END = date(2020, 11, 20)


def _f(form, day, items=""):
    return EdgarSubmission(f"A-{form}-{day}", form, day, "", items, "d.htm")


def _s(**kw):
    base = dict(trading_after=False, item_filed={}, successor_filing="", merger_filing="", delist_filing="",
                deficiency_notice="")
    return EraSignals(**{**base, **kw})


def test_signals_read_items_successors_and_form25s_inside_their_windows_only():
    s = signals([_f("8-K", "2020-11-02", "2.01,3.01,5.01"), _f("8-K", "2018-06-01", "5.01"),
                 _f("8-K/A", "2020-11-10", "1.03"), _f("8-K12B", "2020-12-01", "8.01"),
                 _f("25-NSE", "2020-11-03"), _f("DEFM14A", "2019-08-01"), _f("10-Q", "2021-08-05")],
                END, trading_after=False)
    assert s.item_filed == {"2.01": "2020-11-02", "3.01": "2020-11-02", "5.01": "2020-11-02", "1.03": "2020-11-10"}
    assert s.successor_filing == "8-K12B 2020-12-01" and s.delist_filing == "25-NSE 2020-11-03"
    assert s.merger_filing == "DEFM14A 2019-08-01"


def test_a_merger_filing_older_than_its_window_does_not_count():
    assert signals([_f("DEFM14A", "2018-01-02")], END, trading_after=False).merger_filing == ""


def test_still_trading_keeps_todays_transfer():
    v = resolve(_s(trading_after=True, item_filed={"5.01": "2020-11-02"}), 231)
    assert (v.branch, v.crsp_code, v.bucket, v.reason) == ("trading", 304, CrspBucket.EXCHANGE_TRANSFER, CONTINUED)


def test_a_successor_registration_is_a_transfer_whose_successor_is_searched():
    v = resolve(_s(successor_filing="8-K12B 2020-12-01", item_filed={"5.01": "2020-11-02"}), 231)
    assert (v.branch, v.bucket) == ("successor", CrspBucket.EXCHANGE_TRANSFER)
    assert v.reason.startswith("Successor registration 8-K12B 2020-12-01")


def test_a_change_in_control_is_a_merger_with_the_items_code():
    v = resolve(_s(item_filed={"2.01": "2020-11-02", "5.01": "2020-11-02"}), 233)
    assert (v.branch, v.crsp_code, v.bucket) == ("change_in_control", 233, CrspBucket.MERGER)
    assert resolve(_s(item_filed={"5.01": "2020-11-02"}), None).crsp_code == 231


def test_a_completed_acquisition_needs_a_merger_filing_or_a_form25():
    with_proxy = resolve(_s(item_filed={"2.01": "2020-11-02"}, merger_filing="DEFM14A 2020-08-01"), None)
    with_25 = resolve(_s(item_filed={"2.01": "2020-11-02"}, delist_filing="25-NSE 2020-11-03"), None)
    bare = resolve(_s(item_filed={"2.01": "2020-11-02"}), None)
    assert (with_proxy.branch, with_proxy.bucket, with_proxy.crsp_code) == ("completed_merger", CrspBucket.MERGER, 231)
    assert with_25.branch == "completed_merger"
    assert (bare.branch, bare.reason) == ("continued_filings", CONTINUED)


def test_a_deficiency_notice_is_a_compliance_failure_and_a_bare_notice_is_not():
    v = resolve(_s(item_filed={"3.01": "2020-11-02"}, deficiency_notice="8-K 2020-11-02"), None)
    assert (v.branch, v.crsp_code, v.bucket) == ("delisting_notice", 570, CrspBucket.COMPLIANCE_FAILURE)
    assert resolve(_s(item_filed={"3.01": "2020-11-02"}), None).branch == "continued_filings"


def test_nothing_else_keeps_todays_continued_filings_transfer():
    v = resolve(_s(), None)
    assert (v.branch, v.crsp_code, v.bucket, v.reason) == ("continued_filings", 304, CrspBucket.EXCHANGE_TRANSFER,
                                                           CONTINUED)
    assert CONTINUED == "Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)"

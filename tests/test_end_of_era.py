from datetime import date

from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarSubmission
from delist_detection.end_of_era import CONTINUED, EraSignals, Filed, registers_successor, resolve, signals
from delist_detection.exchange_terms import OwnExchange

END = date(2020, 11, 20)
_FILINGS = ("successor_filing", "merger_filing", "delist_filing", "deficiency_notice", "bankruptcy_filing",
            "liquidation_notice")


def _f(form, day, items=""):
    return EdgarSubmission(f"A-{form}-{day}", form, day, "", items, "d.htm")


def F(text):
    """A filing the signals name, written as a reason prints it: "8-K 2020-11-09"."""
    form, day = text.rsplit(" ", 1)
    return Filed(form, date.fromisoformat(day))


def _days(items):
    return {k: date.fromisoformat(v) for k, v in items.items()}


def _s(**kw):
    """The signals, typed, from their printed shorthand ("8-K 2020-11-09", {"5.01": "2020-11-02"}; "" is none)."""
    kw = {k: (F(v) if v else None) if k in _FILINGS else v for k, v in kw.items()}
    if "item_filed" in kw:
        kw["item_filed"] = _days(kw["item_filed"])
    return EraSignals(**{"trading_after": False, **kw})


def test_signals_read_items_successors_and_form25s_inside_their_windows_only():
    s = signals([_f("8-K", "2020-11-02", "2.01,3.01,5.01"), _f("8-K", "2018-06-01", "5.01"),
                 _f("8-K/A", "2020-11-10", "1.03"), _f("8-K12B", "2020-12-01", "8.01"),
                 _f("25-NSE", "2020-11-03"), _f("DEFM14A", "2019-08-01"), _f("10-Q", "2021-08-05")],
                END, trading_after=False)
    assert s.item_filed == _days({"2.01": "2020-11-02", "3.01": "2020-11-02", "5.01": "2020-11-02",
                                  "1.03": "2020-11-10"})
    assert s.successor_filing == F("8-K12B 2020-12-01") and s.delist_filing == F("25-NSE 2020-11-03")
    assert s.merger_filing == F("DEFM14A 2019-08-01")
    assert str(s.successor_filing) == "8-K12B 2020-12-01"


def test_a_merger_filing_older_than_its_window_does_not_count():
    assert signals([_f("DEFM14A", "2018-01-02")], END, trading_after=False).merger_filing is None


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


from delist_detection.end_of_era import RESOLVED_FROM_CONTINUED_FILINGS


def test_every_relabelled_ending_says_the_registrant_kept_filing():
    for s in (_s(successor_filing="8-K12B 2020-12-01"), _s(item_filed={"5.01": "2020-11-02"}),
              _s(item_filed={"2.01": "2020-11-02"}, delist_filing="25-NSE 2020-11-03"),
              _s(item_filed={"3.01": "2020-11-02"}, deficiency_notice="8-K 2020-11-02")):
        assert RESOLVED_FROM_CONTINUED_FILINGS in resolve(s, None).reason
    assert RESOLVED_FROM_CONTINUED_FILINGS not in resolve(_s(), None).reason


# --- sub-plan 5b, 5g sub-rule 2: a confirmed bankruptcy before a completed sale ---

def test_a_confirmed_bankruptcy_before_the_completed_sale_is_a_bankruptcy():
    """A Chapter 11 asset sale is no merger: the 8-K item 1.03 the classifier confirmed (`bankruptcy_filing`) on
    or before the item 2.01 beats the completed-acquisition branch."""
    v = resolve(_s(item_filed={"1.03": "2020-09-10", "2.01": "2020-11-24"}, delist_filing="25-NSE 2020-08-11",
                   bankruptcy_filing="8-K 2020-09-10"), 470)
    assert (v.branch, v.crsp_code, v.bucket) == ("bankruptcy", 470, CrspBucket.LIQUIDATION)
    assert v.reason.startswith("Bankruptcy (8-K 2020-09-10, item 1.03) before the completed sale")
    assert RESOLVED_FROM_CONTINUED_FILINGS in v.reason


def test_a_bankruptcy_after_the_sale_or_unconfirmed_leaves_the_completed_merger():
    for bk in ("8-K 2020-12-01", ""):
        v = resolve(_s(item_filed={"1.03": "2020-12-01", "2.01": "2020-11-24"}, delist_filing="25-NSE 2020-08-11",
                       bankruptcy_filing=bk), 470)
        assert (v.branch, v.crsp_code, v.bucket) == ("completed_merger", 231, CrspBucket.MERGER)


def test_a_bankruptcy_and_a_sale_with_no_merger_filing_or_form25_keep_the_continued_filings_default():
    v = resolve(_s(item_filed={"1.03": "2020-09-10", "2.01": "2020-11-24"}, bankruptcy_filing="8-K 2020-09-10"), 470)
    assert v.branch == "continued_filings"


def test_a_change_in_control_still_comes_before_the_bankruptcy_branch():
    v = resolve(_s(item_filed={"1.03": "2020-09-10", "2.01": "2020-11-24", "5.01": "2020-11-24"},
                   bankruptcy_filing="8-K 2020-09-10"), 233)
    assert (v.branch, v.crsp_code) == ("change_in_control", 233)


def test_the_bankruptcy_filing_is_the_classifiers_answer_carried_on_the_signals():
    s = signals([_f("8-K", "2020-12-01", "1.03")], END, trading_after=False, bankruptcy_filing=F("8-K 2020-12-01"))
    assert s.bankruptcy_filing == F("8-K 2020-12-01") and s.item_filed == _days({"1.03": "2020-12-01"})


# --- sub-plan 5c, rule 1: a registrant that survived the transaction ---
from delist_detection.end_of_era import merges  # noqa: E402


def test_a_survivor_takes_no_merger_branch_and_goes_on_to_the_notice_or_the_continued_filings():
    """RRI Energy acquired Mirant (5.01), Forest Oil issued its shares to Sabine (2.01 with a proxy) and was then
    removed for its price: neither is a merger ending."""
    acquirer = "each outstanding share of common stock of Mirant was converted into ... shares of our common stock"
    v = resolve(_s(item_filed={"5.01": "2020-11-02"}, survived=acquirer), 231)
    assert (v.branch, v.crsp_code, v.bucket, v.reason) == ("continued_filings", 304, CrspBucket.EXCHANGE_TRANSFER,
                                                           CONTINUED)
    v = resolve(_s(item_filed={"2.01": "2020-11-02", "3.01": "2020-11-09"}, merger_filing="DEFM14A 2020-10-01",
                   deficiency_notice="8-K 2020-11-09", survived="the Company issued an aggregate of ..."), 200)
    assert (v.branch, v.crsp_code, v.bucket) == ("delisting_notice", 570, CrspBucket.COMPLIANCE_FAILURE)


def test_a_survivor_that_filed_chapter_11_before_the_sale_is_still_a_bankruptcy():
    """A liquidation is not a merger: the bankruptcy sub-rule comes before the survivor guard."""
    v = resolve(_s(item_filed={"1.03": "2020-09-10", "2.01": "2020-11-02"}, merger_filing="DEFM14A 2020-10-01",
                   bankruptcy_filing="8-K 2020-09-10", survived="the Company issued an aggregate of ..."), 470)
    assert (v.branch, v.crsp_code, v.bucket) == ("bankruptcy", 470, CrspBucket.LIQUIDATION)


def test_a_liquidation_notice_is_a_liquidation_after_every_other_branch():
    """Sub-plan 5g (EQC 2025, operator pre-ruling): a registrant that delisted while winding down under a plan of
    liquidation (its 3.01 8-K announces a liquidating distribution or trust) kept filing to wind down; that is a
    liquidation (CRSP 400), not a transfer. A deficiency notice, a merger or a successor still decides first."""
    v = resolve(_s(item_filed={"3.01": "2025-04-01"}, liquidation_notice="8-K 2025-04-01"), None)
    assert (v.branch, v.crsp_code, v.bucket) == ("liquidation", 400, CrspBucket.LIQUIDATION)
    assert v.reason.startswith("Liquidation: delisted while winding down (8-K 2025-04-01")
    assert RESOLVED_FROM_CONTINUED_FILINGS in v.reason
    assert resolve(_s(item_filed={"3.01": "2025-04-01"}, deficiency_notice="8-K 2025-04-01",
                      liquidation_notice="8-K 2025-04-01"), None).branch == "delisting_notice"
    assert resolve(_s(successor_filing="8-K12B 2025-04-02", liquidation_notice="8-K 2025-04-01"), None).branch == \
        "successor"
    assert resolve(_s(item_filed={"5.01": "2025-04-01"}, liquidation_notice="8-K 2025-04-01"), None).branch == \
        "change_in_control"


def test_the_liquidation_notice_is_the_classifiers_answer_carried_on_the_signals():
    s = signals([_f("8-K", "2020-11-02", "3.01")], END, trading_after=False, liquidation_notice=F("8-K 2020-11-02"))
    assert s.liquidation_notice == F("8-K 2020-11-02")
    assert signals([], END, trading_after=False).liquidation_notice is None


def test_merges_says_when_branch_3_or_4_would_decide():
    assert merges(_s(item_filed={"5.01": "2020-11-02"}))
    assert merges(_s(item_filed={"2.01": "2020-11-02"}, delist_filing="25-NSE 2020-11-03"))
    assert not merges(_s(item_filed={"2.01": "2020-11-02"}))
    assert not merges(_s(item_filed={"5.01": "2020-11-02"}, successor_filing="8-K12B 2020-11-03"))
    assert not merges(_s(item_filed={"5.01": "2020-11-02"}, trading_after=True))


# --- spec 5c rule 6 (sub-plan 5f), inside branch 2 (architecture step 7b) ---

def _own(ratio, cash=False, ambiguous=False):
    return OwnExchange(ratio, cash, "of New Charter Class A Common Stock", ("New Charter",), "A", False, "s",
                       ambiguous=ambiguous)


def test_a_successor_registration_whose_statement_changed_the_stake_is_a_merger():
    """CHTR 2016: each share became 0.9042 New Charter shares: a merger (231), whatever files the 8-K12B."""
    v = resolve(_s(successor_filing="8-K12B 2016-05-20", successor_terms=_own(0.9042)), None)
    assert (v.branch, v.crsp_code, v.bucket) == ("successor_merger", 231, CrspBucket.MERGER)
    assert v.reason == ("Successor registration 8-K12B 2016-05-20: each share became 0.9042 shares of New Charter "
                        "Class A Common Stock, a merger (rule 6)")
    cash = resolve(_s(successor_filing="8-K12B 2016-05-20", successor_terms=_own(1.0, cash=True)), None)
    assert cash.branch == "successor_merger" and cash.reason.endswith(" and cash, a merger (rule 6)")


def test_a_split_factor_one_for_one_two_readings_or_no_statement_keep_the_transfer():
    """SIRI 2024's 0.1 New Sirius is a consolidation into the successor: the transfer stands."""
    for terms in (_own(0.1), _own(1.0), _own(0.9042, ambiguous=True), None):
        v = resolve(_s(successor_filing="8-K12B 2024-09-10", successor_terms=terms), None)
        assert (v.branch, v.bucket) == ("successor", CrspBucket.EXCHANGE_TRANSFER)


def test_rule_6_is_read_only_where_branch_2_decides():
    assert registers_successor(_s(successor_filing="8-K12B 2024-09-10"))
    assert not registers_successor(_s(successor_filing="8-K12B 2024-09-10", trading_after=True))
    assert not registers_successor(_s(item_filed={"5.01": "2020-11-02"}))

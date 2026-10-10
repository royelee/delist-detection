"""The row vocabulary (exit_kind, architecture step 8a) at its interface, over rows: the contract's view, real
endings and each security's last one, flag tokens, the evidence a reason names (each writer read back by its reader,
and the producers' own text: the end-of-era resolver's and the handoff stage's), the value rules, and the last
trade's facts over a row."""
from datetime import date

import pytest

from delist_detection.vocabulary.crsp_codes import DLST_CODE_TO_BUCKET
from delist_detection.vocabulary.exit_kind import (
    CHANGE_IN_CONTROL, CLOSING_DAY, COMPLETED_ACQUISITION, CONFLICT, CONTINUED, DROP_REASONS, EX99_NOTICE,
    EXCHANGE_PRINTS, EXIT_KINDS, GATE_FLAGS, LAST_SIGHTING, LLM_GATE_FAILED, MIDAS, NO_DAY, PAYOUT_GATE_FAILED, SOURCES,
    SUCCESSOR_FORMS, TERMS_GATE_FAILED, TERMS_GATE_SKIPPED, TIMING_CIK, TIMING_CUSIP, UNCONFIRMED, UNSOURCED, VALUE_RULES,
    LastTrade, change_in_control_reason, cites_form25, completed_acquisition_reason, continuation_reason,
    effective_date, effective_of, end_day, end_day_of, ending_fields, flag_detail, flag_name, flag_names, flag_tokens,
    is_continuation, is_distress, is_real_ending, last_endings, linked_by_timing, merger_relabel,
    names_successor_registration, of_row, published, relabel, resolved_from_continued_filings,
    rests_on_continued_filings, successor_note, successor_registration_reason,
)
from lifecycle_tables import ending


def test_a_bankruptcy_is_dropped_for_bankruptcy():
    f = ending_fields(ending("S", "2020-05-11", "liquidation", dlret="-0.550000", method="shumway_nasdaq",
                             crsp_code="470"))
    assert (f.exit_kind, f.drop_reason) == ("dropped", "bankruptcy")


def test_a_liquidation_without_the_bankruptcy_code_stays_a_liquidation():
    f = ending_fields(ending("S", "2020-05-11", "liquidation", crsp_code="400"))
    assert (f.exit_kind, f.drop_reason) == ("liquidation", "")


@pytest.mark.parametrize("code,reason", [("573", "sec_order"), ("580", "filings_fees"), ("570", "guidelines"),
                                         ("520", "moved_otc"), ("500", "")])
def test_a_compliance_failure_is_dropped_for_the_reason_its_code_names(code, reason):
    f = ending_fields(ending("S", "2012-05-01", "compliance_failure", crsp_code=code))
    assert (f.exit_kind, f.drop_reason) == ("dropped", reason)


def test_a_merger_is_a_merger_whatever_its_value():
    cash = ending_fields(ending("S", "2018-11-29", dlret="0.110000", method="cash_only", crsp_code="231"))
    par = ending_fields(ending("S", "2018-11-29", dlret="0.000000", method="assumed_par", crsp_code="231"))
    assert (cash.exit_kind, par.exit_kind) == ("merger", "merger")


def test_a_continuation_and_a_transfer_are_both_exchanges():
    cont = ending_fields(ending("S", "2015-10-02", "exchange_transfer", successor="T", dlret="0.000000",
                                method="exchange_transfer_zero", crsp_code="304"))
    xfer = ending_fields(ending("S", "2015-10-02", "exchange_transfer", dlret="0.000000",
                                method="exchange_transfer_zero", crsp_code="304"))
    assert (cont.exit_kind, cont.continuation) == ("exchange", True)
    assert (xfer.exit_kind, xfer.continuation) == ("exchange", False)


def test_a_successor_that_is_the_security_itself_is_not_a_continuation():
    assert not ending_fields(ending("S", "2019-03-20", "merger", successor="S")).continuation


def test_unknown_asserts_no_kind():
    f = ending_fields(ending("S", "2009-03-08", "unknown", method="needs_last_trade"))
    assert (f.exit_kind, f.drop_reason) == ("", "")


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


def test_a_real_ending_and_a_continuation_are_read_from_the_successor_once():
    """The one definition every reader of delistings.csv asks: a security that went on (its own successor) has no
    real ending; a successor other than itself is a continuation; a blank successor is a real ending, no
    continuation."""
    went_on = ending("S", "2019-03-30", "merger", successor="S")
    moved = ending("S", "2015-10-12", "exchange_transfer", successor="T")
    ended = ending("S", "2018-11-29", "merger")
    assert [is_real_ending(r) for r in (went_on, moved, ended)] == [False, True, True]
    assert [is_continuation(r) for r in (went_on, moved, ended)] == [False, True, False]


# -- each security's last ending: one definition, three readers ---------------------------------------------------
def test_the_last_ending_is_the_latest_real_one_and_a_tie_keeps_the_later_row():
    rows = [ending("A", "2015-03-10", "exchange_transfer", successor="B"),
            ending("A", "2019-05-01", "merger", successor="A"),                # went on: not an ending
            ending("A", "2012-01-04", "merger"),
            ending("C", "2010-01-04", "merger", successor="C"),                # only went on: no last ending
            ending("D", "2011-02-01", "merger", reason="first"), ending("D", "2011-02-01", "merger", reason="second")]
    last = last_endings(rows)
    assert set(last) == {"A", "D"}
    assert last["A"] is rows[0] and last["D"] is rows[5]


def test_the_verdict_the_lifecycle_and_the_contract_read_the_same_last_ending():
    """Before step 8a the contract sorted, the verdict took the max date and the lifecycle walk the last of its sorted
    list: the three agreed on the committed output and on 20,000 random tables (ties and went-on rows included).
    Now each asks `last_endings`."""
    from delist_detection.outputs.contract import delisting_rows
    from delist_detection.measurement.lifecycle import LifecycleView
    from delist_detection.outputs.verdict import decide
    from lifecycle_tables import iv, obs, sec, tables

    def good(ltd, filed):
        return dict(ltd=ltd, dlret="0.01", reason="M&A 2.01+3.01+5.01", delist_filing_form="25-NSE",
                    delist_filing_date=filed)
    earlier = ending("A", "2012-05-01", **good("2012-04-20", "2012-04-21"))
    last = ending("A", "2015-03-10", **good("2015-03-02", "2015-03-03"))
    went_on = ending("A", "2016-01-04", "exchange_transfer", successor="A")
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04", "2015-03-02")], [last, went_on, earlier],
               [obs("AAA", "2010-06-30", "A")])
    (held,) = [r for r in t.delistings if r["delist_date"] == "2015-03-10"]       # the snapshot's copy of `last`
    assert held == last and LifecycleView(t).lifecycle("A").final is held
    v = decide(t, {})
    assert v.endings[("A", "2012-05-01")].reasons == ("earlier_ending:2015-03-10",)
    assert v.endings[("A", "2015-03-10")].confirmed and ("A", "2016-01-04") not in v.endings
    assert [r["last_trade_date"] for r in delisting_rows(t, v)] == ["2015-03-02"]


# -- flags --------------------------------------------------------------------------------------------------------
def test_a_rows_flag_tokens_are_read_whole_and_in_order():
    row = {"review_flags": "payout_gate_failed:34.88;;last_trade_date_conflict;ftd_close_prior:4"}
    assert flag_tokens(row) == ["payout_gate_failed:34.88", "last_trade_date_conflict", "ftd_close_prior:4"]
    assert flag_names(row) == {"payout_gate_failed", "last_trade_date_conflict", "ftd_close_prior"}
    assert [flag_detail(t) for t in flag_tokens(row)] == ["34.88", "", "4"]
    assert flag_name("terms_gate_failed:no_acq_price:x") == "terms_gate_failed"
    assert flag_detail("terms_gate_failed:no_acq_price:x") == "no_acq_price:x"
    assert flag_tokens({"review_flags": ""}) == [] and flag_tokens({"review_flags": None}) == [] \
        and flag_tokens({}) == []


def test_the_gate_flags_the_payout_gate_writes_are_the_ones_its_readers_read():
    from delist_detection.terms import payout_gate
    from delist_detection.endings.rewrites import PAYOUT_FLAGS
    written = (payout_gate.GATE_FAILED + "34.88", payout_gate.LLM_GATE_FAILED, payout_gate.GATE_SKIPPED + "CAD",
               f"{TERMS_GATE_FAILED}:no_acq_price")
    assert {flag_name(t) for t in written} == GATE_FLAGS
    assert {PAYOUT_GATE_FAILED, LLM_GATE_FAILED, TERMS_GATE_FAILED, TERMS_GATE_SKIPPED} == GATE_FLAGS
    assert GATE_FLAGS <= PAYOUT_FLAGS                     # a continuation carries none of them


# -- the evidence a reason names: each writer read back by its reader ---------------------------------------------
DAY = date(2015, 2, 20)


def test_the_continued_filings_rule_round_trips():
    assert CONTINUED == "Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)"
    assert rests_on_continued_filings(CONTINUED) and rests_on_continued_filings(CONTINUED + successor_note("same_issuer"))
    assert not resolved_from_continued_filings(CONTINUED)
    assert not rests_on_continued_filings(change_in_control_reason(DAY))


def test_a_relabel_round_trips_and_only_the_two_merger_branches_are_merger_relabels():
    from delist_detection.endings.end_of_era import Filed
    cic, acq = change_in_control_reason(DAY), completed_acquisition_reason(DAY, Filed("25-NSE", date(2015, 3, 3)))
    assert cic == "Change in control (8-K item 5.01 filed 2015-02-20); the registrant kept filing after it"
    assert acq == ("Completed acquisition (8-K item 2.01 filed 2015-02-20, 25-NSE 2015-03-03); the registrant kept "
                   "filing after it")
    assert merger_relabel(cic) and merger_relabel(acq)
    for other in (relabel("Listing deficiency notice (8-K 2015-01-08), no merger evidence"),
                  relabel(successor_registration_reason("8-K12B 2017-07-03", "the security continues under a "
                                                        "successor"))):
        assert resolved_from_continued_filings(other) and not merger_relabel(other)
    assert not merger_relabel(f"{CHANGE_IN_CONTROL} filed 2015-02-20)")      # the branch's text, never relabelled
    assert not merger_relabel(relabel(f"Bankruptcy (8-K 2015-01-02, item 1.03) before the completed sale "
                                      f"({COMPLETED_ACQUISITION} filed 2015-02-27)"))


def test_the_resolvers_reasons_are_read_back_by_the_vocabulary():
    """The producer end to end: every branch of `end_of_era.resolve` writes a reason its reader reads (this replaces
    the test that tied verdict_rules' copy of the prefixes to the resolver's f-strings)."""
    from delist_detection.endings.end_of_era import EraSignals, Filed, resolve
    from delist_detection.endings.exchange_terms import OwnExchange

    def reason(**kw):
        return resolve(EraSignals(**{"trading_after": False, **kw}), None).reason

    f25, defm = Filed("25-NSE", date(2015, 3, 3)), Filed("DEFM14A", date(2014, 12, 1))
    successor = Filed("8-K12B", date(2017, 7, 3))
    stake = OwnExchange(0.9042, False, "of New Charter Class A Common Stock", ("New Charter",), "A", False, "s")
    assert rests_on_continued_filings(reason()) and rests_on_continued_filings(reason(trading_after=True))
    assert merger_relabel(reason(item_filed={"5.01": DAY}))
    assert merger_relabel(reason(item_filed={"2.01": DAY}, merger_filing=defm))
    assert merger_relabel(reason(item_filed={"2.01": DAY}, delist_filing=f25))
    moved = reason(successor_filing=successor)
    assert names_successor_registration(moved) and resolved_from_continued_filings(moved)
    assert not merger_relabel(moved)
    merged = reason(successor_filing=successor, successor_terms=stake)          # rule 6: no relabel suffix
    assert names_successor_registration(merged) and not resolved_from_continued_filings(merged)
    for kw in (dict(item_filed={"2.01": DAY, "1.03": date(2015, 1, 2)}, delist_filing=f25,
                    bankruptcy_filing=Filed("8-K", date(2015, 1, 2))),
               dict(item_filed={"3.01": DAY}, deficiency_notice=Filed("8-K", DAY)),
               dict(liquidation_notice=Filed("8-K", DAY))):
        r = reason(**kw)
        assert resolved_from_continued_filings(r) and not merger_relabel(r) and not names_successor_registration(r)


def test_a_successor_registration_round_trips_for_every_form_and_amendment():
    for form in (*SUCCESSOR_FORMS, *(f"{f}/A" for f in SUCCESSOR_FORMS)):
        assert names_successor_registration(successor_registration_reason(f"{form} 2021-03-02", "x"))
        assert names_successor_registration(continuation_reason(f"{form} 0001-1", "x"))
    assert continuation_reason("8-K12B 0001-1", "x") == "Continuation (8-K12B 0001-1): x"
    for other in (continuation_reason("R1", "each share became one share"), continuation_reason(TIMING_CIK, "x"),
                  continuation_reason("line follow, 8-K 0001-1", "x"), CONTINUED + successor_note("handoff", "8-K12B 1"),
                  successor_registration_reason("8-K 2021-03-02", "x")):
        assert not names_successor_registration(other)


def test_a_timing_link_round_trips_in_a_continuations_reason_and_in_a_successor_note():
    assert successor_note("same_issuer_class") == "; successor by same issuer class"
    assert successor_note("handoff", TIMING_CIK) == "; successor by handoff (timing:cik)"
    assert linked_by_timing(continuation_reason(TIMING_CIK, "A last traded as AAA"))
    assert linked_by_timing(CONTINUED + successor_note("handoff", TIMING_CIK))
    assert not linked_by_timing(continuation_reason(TIMING_CUSIP, "x"))       # a CUSIP switch is evidence of its own
    assert not linked_by_timing(continuation_reason("8-K12B 0001-1", "x"))


def test_the_handoff_stages_reasons_are_read_back_by_the_vocabulary():
    """The producer end to end: a handoff decided by timing and the same CIK, or by a successor issuer's 8-K12B,
    writes a reason (a new row's, or a note on a kept transfer's) the readers read."""
    from delist_detection.outputs.reconstruction import DelistRecord
    from delist_detection.vocabulary.crsp_codes import CrspBucket
    from delist_detection.endings.delistings import Delisting
    from delist_detection.endings.handoffs import HandoffPair, apply_handoffs, decide_handoff
    from delist_detection.identity.security_master import Security

    pair = HandoffPair("AON", "OLD", "NEW", "2020-03-31", "2020-04-01", "2020-04-01")
    secs = {s: Security(s, 315293, "COMMON", "AON PLC", "Common Stock", True, "cusip") for s in ("OLD", "NEW")}
    timing = decide_handoff(pair, filing=None, same_issuer=True, cusip_switch=False)
    filed = decide_handoff(pair, filing=("8-K12B", "0001104659-20-041234", "2020-04-01"), same_issuer=False,
                           cusip_switch=False)
    assert timing.evidence == TIMING_CIK
    (by_timing,) = apply_handoffs([timing], [], secs, []).added
    (by_filing,) = apply_handoffs([filed], [], secs, []).added
    assert linked_by_timing(by_timing.record.reason) and not names_successor_registration(by_timing.record.reason)
    assert names_successor_registration(by_filing.record.reason) and not linked_by_timing(by_filing.record.reason)
    rec = DelistRecord("AON", 315293, "2020-03-31", 304, CrspBucket.EXCHANGE_TRANSFER, "high", CONTINUED,
                       evidence={"flags": ["successor_unknown"]}, sec_id="OLD", delist_date="2020-03-31")
    kept = Delisting("OLD", 315293, "AON", "2020-03-31", rec, LastTrade(date(2020, 3, 31), MIDAS, ()), None, None,
                     "NYSE")
    apply_handoffs([timing], [kept], secs, [])
    assert rests_on_continued_filings(kept.record.reason) and linked_by_timing(kept.record.reason)


# -- the value rules ------------------------------------------------------------------------------------------------
def test_every_value_rule_the_payout_rule_writes_is_one_of_the_value_rules():
    from delist_detection.outputs.dlret import DistressTerms, MergerInputs
    from delist_detection.outputs.payout_rule import value_fields
    rows = [ending("S", "2018-11-29", "merger", payout_per_share="10.0", last_trade_close="9.9"),
            ending("S", "2015-10-02", "exchange_transfer"), ending("S", "2015-10-02", "exchange_transfer",
                                                                    successor="T"),
            ending("S", "2020-05-11", "liquidation", recovery_ratio="0.1"),
            ending("S", "2020-05-11", "liquidation", method="worthless"),
            ending("S", "2012-05-01", "compliance_failure", crsp_code="570"),
            ending("S", "2010-01-04", "expiration"), ending("S", "2009-03-08", "unknown")]
    rules = {value_fields(r, "", MergerInputs(), DistressTerms())["value_rule"] for r in rows}
    assert rules == {"cash", "transfer", "continuation", "recovery", "worthless", "otc_print", "expiration",
                     "unknown"} and rules <= VALUE_RULES
    assert {"stock", "cash_plus_stock", "basket"} <= VALUE_RULES


# -- the last trade: LastTrade's facts and the reading of a row (the last trade module's, step 4) ---------------
def test_confirmed_is_a_day_nothing_flags_unconfirmed():
    assert LastTrade(date(2020, 1, 2), MIDAS, ()).confirmed
    assert LastTrade(date(2020, 1, 2), MIDAS, (CONFLICT,)).confirmed
    assert not LastTrade(date(2020, 1, 2), EX99_NOTICE, (UNCONFIRMED,)).confirmed
    assert not LastTrade(None, UNSOURCED, (NO_DAY,)).confirmed
    assert LastTrade(date(2020, 1, 2), CLOSING_DAY, (UNCONFIRMED,)).worked_out
    assert not LastTrade(date(2020, 1, 2), LAST_SIGHTING, ()).worked_out


def test_publishable_is_confirmed_an_exchange_print_and_no_later_than_the_form25_effective_date():
    eff = date(2018, 12, 9)
    assert LastTrade(date(2018, 11, 28), EX99_NOTICE, ()).publishable(eff)
    assert LastTrade(date(2018, 12, 9), MIDAS, ()).publishable(eff)
    assert LastTrade(date(2018, 11, 28), MIDAS, ()).publishable(None)
    assert not LastTrade(date(2018, 12, 10), MIDAS, ()).publishable(eff)                 # after it takes effect
    assert not LastTrade(date(2018, 11, 28), LAST_SIGHTING, ()).publishable(eff)         # no exchange print
    assert not LastTrade(date(2018, 11, 28), CLOSING_DAY, (UNCONFIRMED,)).publishable(eff)
    # CNB 2009, IMB 2008: an involuntary notice's decision day, "suspended immediately": not confirmed
    assert not LastTrade(date(2009, 8, 17), EX99_NOTICE, (UNCONFIRMED,)).publishable(date(2009, 9, 18))
    assert SOURCES[-1] == UNSOURCED and EXCHANGE_PRINTS < set(SOURCES)


def _row(ltd="2018-11-28", source=EX99_NOTICE, flags="", form="25-NSE", filed="2018-11-29"):
    return {"last_trade_date": ltd, "last_trade_date_source": source, "review_flags": flags,
            "delist_filing_form": form, "delist_filing_date": filed}


def test_a_rows_published_day_reads_the_one_definition():
    """contract/delistings.csv's last_trade_date over a delistings.csv row: the row read back (`of_row`) is
    publishable against its Form 25's effective date (filed + 10 days)."""
    assert published(_row()) == "2018-11-28"
    assert published(_row(ltd="2018-12-10")) == ""                                   # past 2018-12-09
    assert published(_row(ltd="2018-12-10", form="8-K")) == "2018-12-10"             # no Form 25: no cap
    assert published(_row(source=LAST_SIGHTING)) == ""
    assert published(_row(flags=f"ftd_close_lagged;{UNCONFIRMED}")) == ""
    assert published(_row(flags=f"{CONFLICT}")) == "2018-11-28"
    assert published(_row(ltd="", source="")) == ""
    assert of_row(_row(flags=f"x;{CONFLICT};payout_gate_failed:4.5")).flags == (CONFLICT,)
    assert effective_of(_row()) == date(2018, 12, 9) and effective_of(_row(form="", filed="")) is None


def test_the_end_day_is_the_last_trade_else_the_delisting_date_never_the_form25_filing_day():
    """FWLT 2014: no day, the issuer's own Form 25 filed 2014-11-24, effective 2014-12-04: listed until then."""
    assert end_day(LastTrade(None, UNSOURCED, (NO_DAY,)), "2014-12-04") == date(2014, 12, 4)
    assert end_day(LastTrade(date(2014, 11, 21), MIDAS, ()), "2014-12-04") == date(2014, 11, 21)


def test_the_form25_effective_date_and_the_end_day_over_a_row():
    assert effective_date("2018-11-29") == "2018-12-09"
    assert cites_form25(_row()) and cites_form25(_row(form="25")) and not cites_form25(_row(form="8-K"))
    assert not cites_form25(_row(filed=""))
    undated = {**_row(ltd="", source=""), "delist_date": "2014-12-04"}
    assert end_day_of(undated) == date(2014, 12, 4)                       # FWLT 2014: listed until it took effect
    assert end_day_of({**_row(), "delist_date": "2018-12-09"}) == date(2018, 11, 28)

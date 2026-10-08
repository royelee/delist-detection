"""The rewrites module (architecture step 3): the one owner of a delisting's kind and successor after its record is
built. Each rule at the interface, without a run: the kind it sets (code and bucket together), what the new kind
drops (the no-evidence default, the open successor, a merger's payout reads and flags), and the typed provenance it
records."""
from datetime import date

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CONTINUATION_CODE, CrspBucket
from delist_detection.delistings import Delisting
from delist_detection.exit_kind import successor_note
from delist_detection.last_trade import LastTrade
from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.merger_value import MergerValue, MergerValues, TableTerms
from delist_detection.payout_extractor import PayoutResult
from delist_detection.rewrites import (
    HANDOFF_CONTINUATION, LINE_CONTINUATION, NO_EVIDENCE_DEFAULT, R1_CONTINUATION, SUCCESSOR_UNKNOWN, Rewrite, Rule,
    awaits_successor, continuation, is_real_ending, mark_going_on, reclassify, rewrite_by, security_goes_on,
    successor_by,
)


def _row(sec_id="OLD", bucket=CrspBucket.MERGER, code=231, flags=(), successor=None, reason="M&A 2.01+3.01+5.01",
         delist_date="2022-05-26"):
    rec = DelistRecord("TKR", 1, "2022-05-16", code, bucket, "high", reason, {"flags": list(flags)}, sec_id=sec_id,
                       delist_date=delist_date, successor_sec_id=successor)
    return Delisting(sec_id, 1, "TKR", delist_date, rec, LastTrade(date(2022, 5, 16), "midas", ()), None, None,
                     "NASDAQ")


def _merger_value(key, *, flags=(), raw=None):
    """A merger's value as stage 8 leaves it: the LLM's terms, the regex read and the gate's flags."""
    return MergerValue(key, raw=raw, read=raw is not None,
                       llm=MergerTerms("stock", None, 1.0, "NEWCO", "NEWC", "high", "8-K:X", ""),
                       terms={"stock_ratio": 1.0, "acquirer_price": 179.8, "acquirer_ticker": "NEWC"},
                       source="llm", confidence="high", flags=tuple(flags), acquirer_sec_id="NEW")


# --- the declared defect: a continuation carries no stale flag and no payout read -----------------------------

def test_a_merger_made_a_continuation_drops_its_payout_reads_and_flags():
    """AZPN 2022 (gate flags `payout_gate_failed:87.69;terms_gate_failed:no_acq_ticker`), ENDP 2014
    (`acquirer_close_lagged`) and CI 2018 (the regex's $48.75 and the LLM's one-for-one terms): the handoff makes each
    merger a continuation. The row keeps its last close's own flags; the merger value is dropped with one call, so
    neither delistings.csv's payout columns nor payouts.csv carry it."""
    d = _row(flags=("last_trade_date_unconfirmed", "ftd_close_prior:1", "acquirer_close_lagged"))
    values = MergerValues({d.key: _merger_value(d.key, flags=("payout_gate_failed:87.69",
                                                              "terms_gate_failed:no_acq_ticker"),
                                                raw=PayoutResult(87.69, "high", "8K_2.01", "0000000000-22-000001",
                                                                 "$87.69"))})
    rw = continuation(d, "NEW", Rule.HANDOFF, reason="Continuation (8-K12B X): ...", confidence="high",
                      flag=HANDOFF_CONTINUATION, how="handoff", evidence="8-K12B X", payouts=values)
    assert (d.record.crsp_code, d.record.bucket, d.record.successor_sec_id) == (
        CONTINUATION_CODE, CrspBucket.EXCHANGE_TRANSFER, "NEW")
    assert d.flags == ["last_trade_date_unconfirmed", "ftd_close_prior:1", HANDOFF_CONTINUATION]
    assert values.get(d.key) is None and values.payout_rows({d.key: "TKR"}) == []
    assert values.table_terms(d.key) == TableTerms()
    assert rw == Rewrite(Rule.HANDOFF, CrspBucket.MERGER, 231, "NEW", "handoff", "8-K12B X") and d.rewrites == [rw]


def test_an_unknown_made_a_continuation_drops_its_no_evidence_default():
    """GOOGL and GOOG 2015: Alphabet's 8-K12B continuation of an `unknown` Form 25 row."""
    d = _row(bucket=CrspBucket.UNKNOWN, code=None, flags=(NO_EVIDENCE_DEFAULT,))
    continuation(d, "NEW", Rule.HANDOFF, reason="Continuation (8-K12B 0001193125-15-336577): ...",
                 confidence="high", flag=HANDOFF_CONTINUATION, payouts=MergerValues())
    assert d.flags == [HANDOFF_CONTINUATION]


def test_a_merger_made_a_continuation_without_its_payouts_is_refused():
    d = _row()
    with pytest.raises(ValueError, match="payout reads"):
        continuation(d, "NEW", Rule.HANDOFF, reason="r", confidence="high")
    assert d.record.bucket is CrspBucket.MERGER and d.rewrites == []


def test_another_kind_made_a_continuation_needs_its_own_reason_and_confidence():
    with pytest.raises(ValueError, match="reason and confidence"):
        continuation(_row(bucket=CrspBucket.UNKNOWN, code=None), "NEW", Rule.LINE_FOLLOW, reason="r")


# --- each rule ------------------------------------------------------------------------------------------------

def test_r1_makes_a_merger_a_continuation_into_a_new_issuer():
    """DOW 2017: one DowDuPont share and no cash. The reason says how the successor was found (the published
    wording, `successor_note`); the statement is provenance only."""
    d = _row(flags=("acquirer_close_lagged",))
    values = MergerValues({d.key: _merger_value(d.key)})
    continuation(d, "BBG00BN961G4", Rule.R1, confidence="medium", flag=R1_CONTINUATION, how="new_issuer",
                 evidence="each share ... converted into one share of DowDuPont", payouts=values,
                 reason="Continuation (R1): each share became one share of DowDuPont, no cash"
                        + successor_note("new_issuer"))
    assert d.record.reason.endswith("no cash; successor by new issuer") and d.record.confidence == "medium"
    assert d.flags == [R1_CONTINUATION] and values.get(d.key) is None
    assert successor_by(d) == "new_issuer" and rewrite_by(d, Rule.R1).evidence.startswith("each share")


def test_a_successor_link_keeps_the_transfer_and_its_reason_and_closes_the_open_successor():
    """BLK 2024: the in-run link of a transfer awaiting its successor (`same_ticker`); an 8-K12B hit says no how."""
    d = _row(bucket=CrspBucket.EXCHANGE_TRANSFER, code=304, flags=("no_form25", SUCCESSOR_UNKNOWN),
             reason="Continued filings")
    assert awaits_successor(d)
    continuation(d, "BBGBLKNEW01", Rule.SUCCESSOR_LINK, reason=d.record.reason + successor_note("same_ticker"),
                 how="same_ticker")
    assert (d.record.bucket, d.record.confidence, d.record.successor_sec_id) == (
        CrspBucket.EXCHANGE_TRANSFER, "high", "BBGBLKNEW01")
    assert d.record.reason == "Continued filings; successor by same ticker" and d.flags == ["no_form25"]
    assert not awaits_successor(d) and successor_by(d) == "same_ticker"
    other = _row(bucket=CrspBucket.EXCHANGE_TRANSFER, code=304, flags=(SUCCESSOR_UNKNOWN,), reason="r")
    continuation(other, "X", Rule.SUCCESSOR_LINK)
    assert other.record.reason == "r" and successor_by(other) == ""


def test_the_line_continuation_rewrites_an_unknown_row_at_the_switch():
    """GTES 2026: the Form 25 at the redomicile was `unknown`; stage 4b's line successor makes it the continuation."""
    d = _row(bucket=CrspBucket.UNKNOWN, code=None, flags=("last_trade_date_unconfirmed", NO_EVIDENCE_DEFAULT))
    continuation(d, "BBGRSNEW1", Rule.LINE_FOLLOW, reason="Continuation (line follow, 8-K): ..."
                 + successor_note("line_follow"), confidence="medium", flag=LINE_CONTINUATION, how="line_follow")
    assert (d.record.crsp_code, d.record.confidence) == (304, "medium")
    assert d.record.reason.endswith("; successor by line follow")
    assert d.flags == ["last_trade_date_unconfirmed", LINE_CONTINUATION]


def test_the_issuers_own_move_is_a_continuation_into_itself():
    """R7 (Kraft Heinz 2026): the issuer's own Form 25 with its 8-A12B; the security goes on, so no real ending."""
    d = _row(sec_id="KHC", bucket=CrspBucket.UNKNOWN, code=None, flags=(NO_EVIDENCE_DEFAULT,))
    continuation(d, "KHC", Rule.ISSUER_MOVE, reason="Exchange transfer: ...", confidence="high")
    assert (d.record.crsp_code, d.record.successor_sec_id, d.flags) == (304, "KHC", [])
    assert not is_real_ending(d)


def test_a_security_that_goes_on_keeps_its_kind_and_its_value():
    """WRK 2018, DIS 2019: a holding company's merger the security's own CUSIP traded through. The row stays a merger
    with its value; only the open successor goes."""
    d = _row(flags=(SUCCESSOR_UNKNOWN, "acquirer_close_lagged"))
    values = MergerValues({d.key: _merger_value(d.key)})
    rw = security_goes_on(d, Rule.TRADES_ON)
    assert (d.record.bucket, d.record.crsp_code, d.record.successor_sec_id) == (CrspBucket.MERGER, 231, "OLD")
    assert d.flags == ["acquirer_close_lagged"] and values.get(d.key) is not None
    assert rw.rule is Rule.TRADES_ON and not is_real_ending(d)


def test_mark_going_on_fills_only_a_blank_successor_the_clip_check_marks():
    """The clip check's answer (`history.Histories.going_on`) at stage 9b's start: a delisting that does not end its
    security goes on as itself; one that ends it, one with a successor a search already found (MWV to WRK) and one
    the check has no answer for (neither is in the answer) are untouched."""
    goes_on, ends = _row("DIS", delist_date="2019-03-30"), _row("AGN", delist_date="2015-03-27")
    found, unknown = _row("MWV", successor="WRK"), _row("ZZZ")
    marked = mark_going_on([goes_on, ends, found, unknown], frozenset({goes_on.key, found.key}))
    assert marked == 1
    assert [d.record.successor_sec_id for d in (goes_on, ends, found, unknown)] == ["DIS", None, "WRK", None]
    assert rewrite_by(goes_on, Rule.TRADES_ON) is not None and found.rewrites == ends.rewrites == []


def test_a_bankruptcy_plan_makes_an_unknown_a_liquidation_without_its_default():
    d = _row(bucket=CrspBucket.UNKNOWN, code=None, flags=(NO_EVIDENCE_DEFAULT, "no_last_close"))
    reclassify(d, 470, Rule.PLAN_BANKRUPTCY, reason="Bankruptcy plan exchange (...)", confidence="medium")
    assert (d.record.crsp_code, d.record.bucket, d.record.confidence) == (470, CrspBucket.LIQUIDATION, "medium")
    assert d.flags == ["no_last_close"] and rewrite_by(d, Rule.PLAN_BANKRUPTCY).was_bucket is CrspBucket.UNKNOWN


def test_a_price_deficiency_changes_the_code_and_keeps_the_rest():
    d = _row(bucket=CrspBucket.COMPLIANCE_FAILURE, code=570, flags=("distress_at_normal_price",),
             reason="Listing deficiency")
    reclassify(d, 552, Rule.PRICE_DEFICIENCY, reason=d.record.reason + " (its stated reason: a price deficiency)")
    assert (d.record.crsp_code, d.record.bucket, d.record.confidence) == (552, CrspBucket.COMPLIANCE_FAILURE, "high")
    assert d.record.reason.endswith("a price deficiency)") and d.flags == ["distress_at_normal_price"]


def test_a_reclassification_never_makes_a_continuation():
    with pytest.raises(ValueError, match="continuation"):
        reclassify(_row(bucket=CrspBucket.UNKNOWN, code=None), 304, Rule.PLAN_BANKRUPTCY, reason="r")


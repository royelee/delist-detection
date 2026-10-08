"""Sub-plan 5i, stage 9g: the filing that confirms a continuation linked by the continued-filings rule or by timing,
and the ratio that contradicts a successor registration (`continuation_evidence` over the ending's own-share
reading, `pipeline._continuation_filings`), on a small EDGAR double."""
from datetime import date
from types import SimpleNamespace

import pytest

from delist_detection import pipeline
from delist_detection.classifier import DelistRecord
from delist_detection.continuation_evidence import (confirming_filing, needs_doubt_check, needs_filing, ratio_doubt,
                                                    read_continuation, successor_doubt)
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import Delisting
from delist_detection.edgar import EdgarSubmission
from delist_detection.identifiers import share_class_from_name
from delist_detection.issuer_record import IssuerRecord
from delist_detection.last_trade import LastTrade
from delist_detection.manifest import StageMeter
from delist_detection.own_shares import Reader
from delist_detection.sec_stats import SEC_STATS
from delist_detection.exit_kind import ContinuationReading

ONE = ("At the effective time, each share of common stock of Acme Corp issued and outstanding was converted into one "
       "share of common stock, par value $0.01 per share, of Acme Holdings, having the same rights.")
TWO = ("Each share of Series A common stock of Acme Corp was reclassified into one share of Series A New Acme common "
       "stock and 0.25 of a share of Series A Acme Live common stock.")


class Edgar:
    def __init__(self, filings, texts, *, fail=False):
        self.filings, self.texts, self.fail = filings, texts, fail

    def recent_filings(self, cik):
        return self.filings

    def submissions(self, cik, **kw):
        return {"name": "ACME CORP", "formerNames": []}

    def fetch_filing_text(self, cik, accession, primary_doc):
        if self.fail:
            SEC_STATS.degraded("failed_request")
            return ""
        return self.texts.get(accession, "")


def _8k(acc, filed, items="3.03,9.01", form="8-K"):
    return EdgarSubmission(acc, form, filed, "", items, "d.htm")


DAY = date(2021, 3, 1)       # the ending's anchor: its last trade


def _own(edgar, name="ACME CORP", day=DAY):
    """The ending's own-share reading over the double (the security's class as its name gives it)."""
    return Reader(edgar, IssuerRecord(edgar)).ending(6769, share_class=share_class_from_name(name), name=name, day=day)


def test_a_3_03_8k_stating_one_for_one_confirms():
    e = Edgar([_8k("0001-21-1", "2021-03-01")], {"0001-21-1": ONE})
    assert confirming_filing(_own(e)) == "8-K 0001-21-1"


def test_an_8k12b_is_a_confirming_form_too():
    e = Edgar([_8k("0001-21-2", "2021-03-02", items="", form="8-K12B")], {"0001-21-2": ONE})
    assert confirming_filing(_own(e)) == "8-K12B 0001-21-2"


def test_a_second_leg_no_3_03_or_a_filing_outside_the_window_confirms_nothing():
    assert confirming_filing(_own(Edgar([_8k("a", "2021-03-01")], {"a": TWO}), "ACME CORP SERIES A")) == ""
    assert confirming_filing(_own(Edgar([_8k("b", "2021-03-01", items="8.01")], {"b": ONE}))) == ""
    assert confirming_filing(_own(Edgar([_8k("c", "2021-01-04")], {"c": ONE}))) == ""
    assert confirming_filing(_own(Edgar([], {}))) == ""


def test_no_text_is_read_without_a_confirming_form_around_the_day():
    class Counting(Edgar):
        read: list = []

        def fetch_filing_text(self, cik, accession, primary_doc):
            self.read.append(accession)
            return super().fetch_filing_text(cik, accession, primary_doc)

    e = Counting([_8k("b", "2021-03-01", items="8.01")], {"b": ONE})
    assert confirming_filing(_own(e)) == "" and e.read == []


def test_only_a_continuation_linked_by_continued_filings_or_timing_is_read():
    assert needs_filing("Continued 10-K/Q filings >180d after delist (moved to OTC or spun off); successor by same "
                        "issuer", "A", "B")
    assert needs_filing("Continuation (timing:cik): A last traded as AAA", "A", "B")
    assert not needs_filing("Continuation (timing:cusip): A last traded as AAA", "A", "B")
    assert not needs_filing("Continuation (8-K12B 0001-1): A last traded as AAA", "A", "B")
    assert not needs_filing("Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)", "A", "")
    assert not needs_filing("Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)", "A", "A")


def _stage(edgar, reason=None, names=None, carried=None):
    rec = DelistRecord("AAA", 6769, "2021-03-01", 304, CrspBucket.EXCHANGE_TRANSFER, "medium",
                       reason or "Continued 10-K/Q filings >180d after delist (moved to OTC or spun off); successor "
                                 "by same issuer", {"flags": []}, sec_id="A", delist_date="2021-03-14",
                       successor_sec_id="B")
    d = Delisting("A", 6769, "AAA", "2021-03-14", rec, LastTrade(date(2021, 3, 1), "closing_day", ()), None, None, "")
    d.own_shares = carried
    ctx = pipeline._RunContext(pipeline.Clients(edgar, None, None, None, None), date(2026, 9, 25),
                               lambda *a: None, 1, StageMeter(lambda *a: None))
    review: list = []
    securities = {"A": SimpleNamespace(name="ACME CORP", share_class="COMMON"),
                  "B": SimpleNamespace(name=names or "ACME HOLDINGS INC", share_class="COMMON")}
    found = pipeline._continuation_filings(ctx, [d], securities, review)
    return found, review, d


def test_stage_9g_maps_the_delisting_to_its_confirming_filing_and_changes_no_row():
    found, review, d = _stage(Edgar([_8k("0001-21-1", "2021-03-01")], {"0001-21-1": ONE}))
    assert found == {d.key: ContinuationReading(filing="8-K 0001-21-1")} and review == [] and d.flags == []
    assert d.own_shares is not None and d.own_shares.day == DAY        # made at the anchor, kept on the delisting


def test_stage_9g_reports_a_failed_read_without_flagging_the_row():
    found, review, d = _stage(Edgar([_8k("0001-21-1", "2021-03-01")], {}, fail=True))
    assert found == {} and [r.flag for r in review] == ["resolution_degraded"] and d.flags == []


def test_the_reading_names_the_filing_whose_text_states_the_exchange():
    # an earlier 3.03 of the window (a charter amendment) is not the filing that holds the sentence
    e = Edgar([_8k("0001-21-0", "2021-02-27"), _8k("0001-21-1", "2021-03-01")],
              {"0001-21-0": "The Board amended the bylaws.", "0001-21-1": ONE})
    assert confirming_filing(_own(e)) == "8-K 0001-21-1"


def test_a_target_that_is_neither_the_registrant_nor_the_successor_confirms_nothing():
    other = ("At the effective time, each share of common stock of Acme Corp issued and outstanding was converted "
             "into one share of common stock, par value $0.01 per share, of Zenith Industries, having the same rights.")
    e = Edgar([_8k("0001-21-1", "2021-03-01")], {"0001-21-1": other})
    assert confirming_filing(_own(e), ["ACME HOLDINGS INC"]) == ""
    assert confirming_filing(_own(e), ["ZENITH INDUSTRIES INC"]) == "8-K 0001-21-1"
    found, _, d = _stage(Edgar([_8k("0001-21-1", "2021-03-01")], {"0001-21-1": other}))
    assert found == {}


# -- a successor registration contradicted by the registrant's own filings (CHTR 2016, SIRI 2024) ------------------

RATIO = ("As a result of the merger, each share of Acme Corp common stock outstanding immediately prior to the "
         "merger was converted into the right to receive 0.9042 shares of Acme Holdings common stock.")
SPLIT = ("As a result of the merger, each share of Acme Corp common stock outstanding immediately prior to the "
         "merger was converted into 0.1 of a share of Acme Holdings common stock.")
REASON = ("Successor registration 8-K12B 2021-03-02: the security continues under a successor; the registrant kept "
          "filing after it; successor by same issuer")


def test_only_a_continuation_that_names_its_successor_registration_is_checked_for_a_ratio():
    assert needs_doubt_check(REASON, "A", "B")
    assert needs_doubt_check("Continuation (8-K12G3 0001-1): A last traded as AAA", "A", "B")
    assert not needs_doubt_check(REASON, "A", "") and not needs_doubt_check(REASON, "A", "A")
    assert not needs_doubt_check("Continuation (timing:cik): A last traded as AAA", "A", "B")


def test_a_stated_ratio_other_than_one_or_a_plain_split_contradicts_the_registration():
    e = Edgar([_8k("r", "2021-03-02", items="", form="8-K12B")], {"r": RATIO})
    assert successor_doubt(_own(e)) == "ratio:0.9042"
    found, _, d = _stage(e, REASON)
    assert found == {d.key: ContinuationReading(doubt="ratio:0.9042")}
    split = Edgar([_8k("r", "2021-03-02", items="", form="8-K12B")], {"r": SPLIT})
    assert successor_doubt(_own(split)) == ""                      # SIRI: a reverse split of the same class
    assert _stage(split, REASON)[0] == {}


def test_stage_9g_reads_the_reading_the_delisting_carries():
    """CHTR 2016: the reading the classifier's rule 6 read is the one 9g reads; the texts are not read again."""
    carried = _own(Edgar([_8k("r", "2021-03-02", items="", form="8-K12B")], {"r": RATIO}))
    assert carried.statement.ratio == 0.9042
    found, _, d = _stage(Edgar([], {}), REASON, carried=carried)
    assert found == {d.key: ContinuationReading(doubt="ratio:0.9042")} and d.own_shares is carried


def test_the_exchanges_notice_is_not_the_registrants_own_filing():
    """Actavis 2013: the Form 25 notice reads Warner Chilcott's 0.160 as the registrant's; the 9g reading leaves the
    notice out, so it raises no doubt."""
    notice = SimpleNamespace(notice_text=RATIO)
    own = Reader(Edgar([], {}), IssuerRecord(Edgar([], {}))).ending(6769, share_class="COMMON", name="ACME CORP",
                                                                     day=DAY, form25=notice)
    assert own.statement.ratio == 0.9042 and own.registrant_statement is None and successor_doubt(own) == ""


def test_a_missing_reading_vetoes_nothing_and_a_one_for_one_one_confirms_nothing_here():
    assert successor_doubt(_own(Edgar([], {}))) == ""
    one = Edgar([_8k("r", "2021-03-02", items="", form="8-K12B")], {"r": ONE})
    assert read_continuation(_own(one), REASON, "A", "B") == ContinuationReading()


def test_the_reading_of_a_failed_fetch_gives_no_veto_and_a_degraded_row():
    found, review, _ = _stage(Edgar([_8k("r", "2021-03-02", items="", form="8-K12B")], {}, fail=True), REASON)
    assert found == {} and [r.flag for r in review] == ["resolution_degraded"]


def test_a_carried_reading_that_rested_on_a_failed_read_is_reported_too():
    carried = _own(Edgar([_8k("r", "2021-03-02", items="", form="8-K12B")], {}, fail=True))
    assert carried.statement is None and carried.degraded
    found, review, _ = _stage(Edgar([], {}), REASON, carried=carried)
    assert found == {} and [r.flag for r in review] == ["resolution_degraded"]


def test_a_refusal_stops_the_stage_and_an_added_securitys_delisting_is_skipped():
    from delist_detection.edgar import EdgarBlocked

    class Blocked(Edgar):
        def fetch_filing_text(self, cik, accession, primary_doc):
            raise EdgarBlocked("403")

    with pytest.raises(EdgarBlocked):
        _stage(Blocked([_8k("0001-21-1", "2021-03-01")], {}))
    _, _, d = _stage(Edgar([], {}))
    ctx = pipeline._RunContext(pipeline.Clients(Blocked([_8k("x", "2021-03-01")], {}), None, None, None, None),
                               date(2026, 9, 25), lambda *a: None, 1, StageMeter(lambda *a: None))
    assert pipeline._continuation_filings(ctx, [d], {}, []) == {}        # "A" is not an observed security here


def test_a_ratio_that_is_a_plain_split_or_one_is_no_doubt():
    assert ratio_doubt(1.0, False) == "" and ratio_doubt(0.1, False) == "" and ratio_doubt(2.0, False) == ""
    assert ratio_doubt(0.9042, False) == "ratio:0.9042" and ratio_doubt(1.0, True) == "cash"
    assert ratio_doubt(0.05, False) == "" and ratio_doubt(20.0, False) == ""                    # 1-for-20, 20-for-1
    assert ratio_doubt(0.75, False) == "ratio:0.75" and ratio_doubt(1.5, False) == "ratio:1.5"


def test_the_selection_reads_the_reason_through_the_row_vocabulary():
    """Stage 9g reads the continuations the verdict reads, from the text their producers write
    (`exit_kind.continuation_reason`, `successor_note`, `CONTINUED`, `successor_registration_reason`)."""
    from delist_detection.exit_kind import (CONTINUED, TIMING_CIK, TIMING_CUSIP, continuation_reason, successor_note,
                                            successor_registration_reason)
    assert needs_filing(continuation_reason(TIMING_CIK, "x"), "A", "B")
    assert needs_filing(CONTINUED + successor_note("same_issuer"), "A", "B")
    assert needs_filing(CONTINUED + successor_note("handoff", TIMING_CIK), "A", "B")
    assert not needs_filing(continuation_reason(TIMING_CUSIP, "x"), "A", "B")             # a CUSIP switch: evidence
    assert not needs_filing(continuation_reason(TIMING_CIK, "x"), "A", "A")               # not a continuation
    for form in ("8-K12B", "8-K12B/A", "8-K12G3", "8-K12G3/A"):
        assert needs_doubt_check(successor_registration_reason(f"{form} 2021-03-02", "x"), "A", "B")
        assert needs_doubt_check(continuation_reason(f"{form} 0001-1", "x"), "A", "B")
    assert not needs_doubt_check(successor_registration_reason("8-K12B 2021-03-02", "x"), "A", "")

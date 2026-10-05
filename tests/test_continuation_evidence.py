"""Sub-plan 5i, stage 9g: the filing that confirms a continuation linked by the continued-filings rule or by timing,
and the ratio that contradicts a successor registration (`continuation_evidence`, `pipeline._continuation_filings`), on a small EDGAR double."""
from datetime import date
from types import SimpleNamespace

import pytest

from delist_detection import pipeline
from delist_detection.classifier import DelistRecord
from delist_detection.continuation_evidence import (confirming_filing, needs_doubt_check, needs_filing, read_continuation,
                                                    successor_doubt)
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import Delisting
from delist_detection.edgar import EdgarSubmission
from delist_detection.last_trade import LastTrade
from delist_detection.manifest import StageMeter
from delist_detection.sec_stats import SEC_STATS
from delist_detection.verdict_rules import Reading

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


DAYS = [date(2021, 3, 1), date(2021, 3, 14)]


def test_a_3_03_8k_stating_one_for_one_confirms():
    e = Edgar([_8k("0001-21-1", "2021-03-01")], {"0001-21-1": ONE})
    assert confirming_filing(e, 6769, DAYS, "ACME CORP") == "8-K 0001-21-1"


def test_an_8k12b_is_a_confirming_form_too():
    e = Edgar([_8k("0001-21-2", "2021-03-02", items="", form="8-K12B")], {"0001-21-2": ONE})
    assert confirming_filing(e, 6769, DAYS, "ACME CORP") == "8-K12B 0001-21-2"


def test_a_second_leg_no_3_03_or_a_filing_outside_the_window_confirms_nothing():
    assert confirming_filing(Edgar([_8k("a", "2021-03-01")], {"a": TWO}), 6769, DAYS, "ACME CORP SERIES A") == ""
    assert confirming_filing(Edgar([_8k("b", "2021-03-01", items="8.01")], {"b": ONE}), 6769, DAYS, "ACME CORP") == ""
    assert confirming_filing(Edgar([_8k("c", "2021-01-04")], {"c": ONE}), 6769, DAYS, "ACME CORP") == ""
    assert confirming_filing(Edgar([], {}), 6769, [None], "ACME CORP") == ""


def test_only_a_continuation_linked_by_continued_filings_or_timing_is_read():
    assert needs_filing("Continued 10-K/Q filings >180d after delist (moved to OTC or spun off); successor by same "
                        "issuer", "A", "B")
    assert needs_filing("Continuation (timing:cik): A last traded as AAA", "A", "B")
    assert not needs_filing("Continuation (timing:cusip): A last traded as AAA", "A", "B")
    assert not needs_filing("Continuation (8-K12B 0001-1): A last traded as AAA", "A", "B")
    assert not needs_filing("Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)", "A", "")
    assert not needs_filing("Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)", "A", "A")


def _stage(edgar, reason=None, names=None):
    rec = DelistRecord("AAA", 6769, "2021-03-01", 304, CrspBucket.EXCHANGE_TRANSFER, "medium",
                       reason or "Continued 10-K/Q filings >180d after delist (moved to OTC or spun off); successor "
                                 "by same issuer", {"flags": []}, sec_id="A", delist_date="2021-03-14",
                       successor_sec_id="B")
    d = Delisting("A", 6769, "AAA", "2021-03-14", rec, LastTrade(date(2021, 3, 1), "closing_day", ()), None, None, "")
    ctx = pipeline._RunContext(pipeline.Clients(edgar, None, None, None, None), date(2026, 9, 25),
                               lambda *a: None, 1, StageMeter(lambda *a: None))
    review: list = []
    securities = {"A": SimpleNamespace(name="ACME CORP"), "B": SimpleNamespace(name=names or "ACME HOLDINGS INC")}
    found = pipeline._continuation_filings(ctx, [d], securities, review)
    return found, review, d


def test_stage_9g_maps_the_delisting_to_its_confirming_filing_and_changes_no_row():
    found, review, d = _stage(Edgar([_8k("0001-21-1", "2021-03-01")], {"0001-21-1": ONE}))
    assert found == {d.key: Reading(filing="8-K 0001-21-1")} and review == [] and d.flags == []


def test_stage_9g_reports_a_failed_read_without_flagging_the_row():
    found, review, d = _stage(Edgar([_8k("0001-21-1", "2021-03-01")], {}, fail=True))
    assert found == {} and [r.flag for r in review] == ["resolution_degraded"] and d.flags == []


def test_the_reading_names_the_filing_whose_text_states_the_exchange():
    # an earlier 3.03 of the window (a charter amendment) is not the filing that holds the sentence
    e = Edgar([_8k("0001-21-0", "2021-02-27"), _8k("0001-21-1", "2021-03-01")],
              {"0001-21-0": "The Board amended the bylaws.", "0001-21-1": ONE})
    assert confirming_filing(e, 6769, DAYS, "ACME CORP") == "8-K 0001-21-1"


def test_a_target_that_is_neither_the_registrant_nor_the_successor_confirms_nothing():
    other = ("At the effective time, each share of common stock of Acme Corp issued and outstanding was converted "
             "into one share of common stock, par value $0.01 per share, of Zenith Industries, having the same rights.")
    e = Edgar([_8k("0001-21-1", "2021-03-01")], {"0001-21-1": other})
    assert confirming_filing(e, 6769, DAYS, "ACME CORP", ["ACME HOLDINGS INC"]) == ""
    assert confirming_filing(e, 6769, DAYS, "ACME CORP", ["ZENITH INDUSTRIES INC"]) == "8-K 0001-21-1"
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
    assert successor_doubt(e, 6769, DAYS, "ACME CORP") == "ratio:0.9042"
    found, _, d = _stage(e, REASON)
    assert found == {d.key: Reading(doubt="ratio:0.9042")}
    split = Edgar([_8k("r", "2021-03-02", items="", form="8-K12B")], {"r": SPLIT})
    assert successor_doubt(split, 6769, DAYS, "ACME CORP") == ""             # SIRI: a reverse split of the same class
    assert _stage(split, REASON)[0] == {}


def test_a_missing_reading_vetoes_nothing_and_a_one_for_one_one_confirms_nothing_here():
    assert successor_doubt(Edgar([], {}), 6769, DAYS, "ACME CORP") == ""
    one = Edgar([_8k("r", "2021-03-02", items="", form="8-K12B")], {"r": ONE})
    assert read_continuation(one, 6769, DAYS, "ACME CORP", REASON, "A", "B") == Reading()


def test_the_reading_of_a_failed_fetch_gives_no_veto_and_a_degraded_row():
    found, review, _ = _stage(Edgar([_8k("r", "2021-03-02", items="", form="8-K12B")], {}, fail=True), REASON)
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


def test_the_successor_registration_forms_are_all_read():
    from delist_detection.verdict_rules import successor_filing_date, successor_filing_reason
    for form in ("8-K12B", "8-K12B/A", "8-K12G3", "8-K12G3/A"):
        assert successor_filing_reason(f"Successor registration {form} 2021-03-02: x")
        assert successor_filing_reason(f"Continuation ({form} 0001-1): x")
    assert successor_filing_date("Successor registration 8-K12G3/A 2021-03-02: x") == date(2021, 3, 2)
    assert successor_filing_date("Continuation (8-K12B 0001-1): x") is None

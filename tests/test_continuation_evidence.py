"""Sub-plan 5i, stage 9f: the filing that confirms a continuation linked by the continued-filings rule or by timing
(`continuation_evidence`, `pipeline._continuation_filings`), on a small EDGAR double."""
from datetime import date
from types import SimpleNamespace

from delist_detection import pipeline
from delist_detection.classifier import DelistRecord
from delist_detection.continuation_evidence import confirming_filing, needs_filing
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import Delisting
from delist_detection.edgar import EdgarSubmission
from delist_detection.last_trade import LastTrade
from delist_detection.manifest import StageMeter
from delist_detection.sec_stats import SEC_STATS

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


def _stage(edgar):
    rec = DelistRecord("AAA", 6769, "2021-03-01", 304, CrspBucket.EXCHANGE_TRANSFER, "medium",
                       "Continued 10-K/Q filings >180d after delist (moved to OTC or spun off); successor by same "
                       "issuer", {"flags": []}, sec_id="A", delist_date="2021-03-14", successor_sec_id="B")
    d = Delisting("A", 6769, "AAA", "2021-03-14", rec, LastTrade(date(2021, 3, 1), "closing_day", ()), None, None, "")
    ctx = pipeline._RunContext(pipeline.Clients(edgar, None, None, None, None), date(2026, 9, 25),
                               lambda *a: None, 1, StageMeter(lambda *a: None))
    review: list = []
    found = pipeline._continuation_filings(ctx, [d], {"A": SimpleNamespace(name="ACME CORP")}, review)
    return found, review, d


def test_stage_9f_maps_the_delisting_to_its_confirming_filing_and_changes_no_row():
    found, review, d = _stage(Edgar([_8k("0001-21-1", "2021-03-01")], {"0001-21-1": ONE}))
    assert found == {d.key: "8-K 0001-21-1"} and review == [] and d.flags == []


def test_stage_9f_reports_a_failed_read_without_flagging_the_row():
    found, review, d = _stage(Edgar([_8k("0001-21-1", "2021-03-01")], {}, fail=True))
    assert found == {} and [r.flag for r in review] == ["resolution_degraded"] and d.flags == []

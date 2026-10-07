"""The run's issuer record (`issuer_record.IssuerRecord`, architecture step 2) at its interface: each issuer read
once per run, the answers it gives (names over time, first filing, forms), and its one failure policy -- a failed
read is unknown and never remembered, a refusal stops the run, a degraded read is recorded."""
from __future__ import annotations

import threading
from datetime import date

import pytest
import requests

from delist_detection import issuer_record
from delist_detection.cik_lookup import CikNameIndex
from delist_detection.edgar import FETCHED_KEY, STALE_KEY, EdgarBlocked, EdgarSubmission
from delist_detection.issuer_record import IssuerRecord
from delist_detection.sec_stats import SEC_STATS

HALYARD = {"name": "AVANOS MEDICAL, INC.", "tickers": ["AVNS"], "exchanges": ["NYSE"],
           "formerNames": [{"name": "HALYARD HEALTH INC", "from": "2014-06-02T00:00:00.000Z",
                            "to": "2018-06-28T00:00:00.000Z"}],
           "filings": {"recent": {"form": ["8-K", "25-NSE", "10-K"],
                                  "filingDate": ["2018-07-02", "2018-06-29", "2018-02-23"]}}}
FILINGS = [EdgarSubmission("a3", "8-K", "2018-07-02", "", "5.03", "d.htm"),
           EdgarSubmission("a2", "10-K", "2018-02-23", "", "", "k.htm"),
           EdgarSubmission("a1", "10-12B", "2014-06-02", "", "", "f.htm")]


class _Seq(list):
    """A CIK's answers in turn, the last one repeating."""


class _Edgar:
    """A scripted EDGAR client: each CIK's answer (`_Seq`: its answers in turn; an exception is raised); `calls`
    counts every read and `fresh` records each submissions read's fresh_after."""

    def __init__(self, subs=None, filings=None, texts=None):
        self.subs, self.filings, self.texts = subs or {}, filings or {}, texts or {}
        self.calls: list[tuple[str, int]] = []
        self.fresh: list[date | None] = []

    @staticmethod
    def _answer(script, cik):
        got = script.get(cik)
        if isinstance(got, _Seq):
            got = got.pop(0) if len(got) > 1 else got[0]
        if isinstance(got, Exception):
            raise got
        return got

    def submissions(self, cik, fresh_after=None):
        self.calls.append(("submissions", int(cik)))
        self.fresh.append(fresh_after)
        got = self._answer(self.subs, int(cik))
        return got if got is not None else {"__not_found__": True}

    def recent_filings(self, cik):
        self.calls.append(("recent_filings", int(cik)))
        got = self._answer(self.filings, int(cik))
        return list(got or [])

    def fetch_filing_text(self, cik, accession, primary_doc):
        self.calls.append(("text", int(cik)))
        got = self.texts.get(accession, "")
        if isinstance(got, Exception):
            raise got
        return got


def _reads(edgar: _Edgar, what: str, cik: int = 7) -> int:
    return edgar.calls.count((what, cik))


# --- each issuer read once per run --------------------------------------------------------------------------------

def test_each_issuer_is_read_once_and_answers_from_that_read():
    e = _Edgar({7: HALYARD}, {7: FILINGS})
    r = IssuerRecord(e)
    assert r.names(7) == ("AVANOS MEDICAL, INC.", "HALYARD HEALTH INC")
    assert r.names_near(7, date(2018, 6, 29)) == ["HALYARD HEALTH INC", "AVANOS MEDICAL, INC."]
    assert r.names_until(7, date(2016, 1, 1)) == ["HALYARD HEALTH INC"]
    assert r.names_between(7, date(2015, 1, 1), date(2016, 1, 1)) == ["HALYARD HEALTH INC"]
    assert r.recent_form_dates(7, "25") == [date(2018, 6, 29)]
    assert r.submissions(7)["tickers"] == ["AVNS"]
    assert _reads(e, "submissions") == 1
    assert r.first_filed(7) == date(2014, 6, 2) and [f.accession for f in r.filings(7)] == ["a3", "a2", "a1"]
    assert r.existed_by(7, "2014-06-02") and not r.existed_by(7, date(2014, 6, 1)) and r.existed_by(7, None)
    assert _reads(e, "recent_filings") == 1
    r.forget()                                          # a new run reads afresh
    assert r.names(7) and r.first_filed(7) and _reads(e, "submissions") == 2 and _reads(e, "recent_filings") == 2


def test_a_filing_list_handed_out_is_the_callers_own():
    e = _Edgar({7: HALYARD}, {7: FILINGS})
    r = IssuerRecord(e)
    r.filings(7).clear()
    assert len(r.filings(7)) == 3 and _reads(e, "recent_filings") == 1


def test_the_least_recently_asked_copy_is_dropped_past_the_memo_size(monkeypatch):
    monkeypatch.setattr(issuer_record, "MEMO_SIZE", 2)
    e = _Edgar({1: {"name": "A"}, 2: {"name": "B"}, 3: {"name": "C"}})
    r = IssuerRecord(e)
    for cik in (1, 2, 1, 3):                            # 2 is the least recently asked when 3 comes in
        r.names(cik)
    r.names(1)
    r.names(2)
    assert [c for w, c in e.calls] == [1, 2, 3, 2]


# --- freshness: a read about an event -------------------------------------------------------------------------------

def test_a_read_about_an_event_asks_for_a_copy_that_fresh_and_a_held_copy_fetched_by_then_answers():
    old = {"name": "X CO", FETCHED_KEY: "2023-01-10"}
    new = {"name": "X CO", FETCHED_KEY: "2023-06-01"}
    e = _Edgar({7: _Seq([old, new])})
    r = IssuerRecord(e, today=date(2023, 6, 1))
    assert r.submissions(7) is old and e.fresh == [None]               # without `about`, any copy
    assert r.submissions(7, about="2023-05-10") is new                  # held 2023-01-10 < 2023-06-01: read again
    assert e.fresh == [None, date(2023, 6, 1)]                          # min(2023-06-24, the run date)
    assert r.submissions(7, about=date(2023, 5, 10)) is new and r.submissions(7) is new
    assert len(e.fresh) == 2


def test_a_refreshed_copy_drops_the_filing_list_and_first_filing_of_the_old_one():
    old = {"name": "X CO", FETCHED_KEY: "2023-01-10"}
    new = {"name": "X CO", FETCHED_KEY: "2023-06-01"}
    e = _Edgar({7: _Seq([old, new])}, {7: _Seq([[FILINGS[1]], FILINGS])})
    r = IssuerRecord(e, today=date(2023, 6, 1))
    assert r.submissions(7) is old and r.first_filed(7) == date(2018, 2, 23)
    assert r.first_filed(7) == date(2018, 2, 23) and _reads(e, "recent_filings") == 1
    r.submissions(7, about="2023-05-10")                                # the client refreshed the copy
    assert r.first_filed(7) == date(2014, 6, 2) and _reads(e, "recent_filings") == 2


def test_a_copy_that_does_not_say_when_it_was_fetched_is_read_again_for_an_event():
    e = _Edgar({7: {"name": "X CO"}})
    r = IssuerRecord(e, today=date(2023, 6, 1))
    r.submissions(7, about="2023-05-10")
    r.submissions(7, about="2023-05-10")
    r.submissions(7)
    assert _reads(e, "submissions") == 2


# --- the failure policy ---------------------------------------------------------------------------------------------

def test_a_failed_read_is_unknown_never_remembered_and_marks_its_issuer_degraded():
    e = _Edgar({7: _Seq([requests.ConnectionError("down"), {"name": "RS CO"}])})
    r = IssuerRecord(e)
    watch = r.watch()
    assert r.submissions(7) is None and watch.ciks == {7} and watch.failed == {7} and watch.tripped()
    assert r.submissions(7) == {"name": "RS CO"}        # asked again, not remembered as a failure
    assert r.submissions(7) == {"name": "RS CO"} and _reads(e, "submissions") == 2
    assert r.watch().ciks == frozenset()                # a new watch sees only what comes after it


def test_every_answer_is_unknown_when_its_read_fails():
    down = requests.ConnectionError("down")
    e = _Edgar({7: down}, {7: down}, {"a3": requests.Timeout("slow")})
    r = IssuerRecord(e)
    watch = r.watch()
    assert (r.names(7), r.names_near(7, date(2018, 6, 29)), r.names_until(7, date(2018, 1, 1))) == ((), [], [])
    assert (r.recent_form_dates(7, "25"), r.filings(7), r.first_filed(7), r.existed_by(7, "2020-01-01")) == \
        ([], [], None, False)
    assert r.text(7, FILINGS[0]) == ""
    assert watch.failed == {7} and _reads(e, "recent_filings") == 3     # every ask reads again: never remembered


def test_a_refusal_stops_the_run_and_any_other_exception_propagates():
    for exc in (EdgarBlocked("403"), ValueError("a bug")):
        e = _Edgar({7: exc}, {7: exc})
        r = IssuerRecord(e)
        for ask in (lambda: r.submissions(7), lambda: r.filings(7), lambda: r.first_filed(7), lambda: r.names(7)):
            with pytest.raises(type(exc)):
                ask()


def test_a_stale_copy_is_used_recorded_degraded_and_read_again():
    stale = {"name": "X CO", STALE_KEY: True}
    e = _Edgar({7: stale})
    r = IssuerRecord(e)
    watch = r.watch()
    assert r.names(7) == ("X CO",) and watch.ciks == {7} and watch.failed == frozenset()
    r.names(7)
    assert _reads(e, "submissions") == 2                # a stale copy is never remembered


def test_a_read_that_counts_itself_degraded_is_recorded_and_any_degraded_sec_read_trips_the_watch():
    class _Counted(_Edgar):
        def submissions(self, cik, fresh_after=None):
            SEC_STATS.degraded("submissions")           # a retried failure that answered
            return {"name": "X CO"}

    r = IssuerRecord(_Counted())
    watch = r.watch()
    assert r.names(7) == ("X CO",) and watch.ciks == {7}
    other = r.watch()
    assert not other.tripped()
    SEC_STATS.degraded("full_text_search")              # another SEC read on this thread
    assert other.tripped() and other.ciks == frozenset()


def test_the_degraded_log_is_per_thread():
    e = _Edgar({7: requests.ConnectionError("down")})
    r = IssuerRecord(e)
    watch = r.watch()
    t = threading.Thread(target=lambda: r.submissions(7))
    t.start()
    t.join()
    assert not watch.tripped()


# --- SEC's name index -----------------------------------------------------------------------------------------------

def test_the_name_index_is_loaded_once_on_first_use_and_names_its_exact_holders():
    loads = []

    def load():
        loads.append(1)
        return CikNameIndex.from_text("MERCK & CO INC:0000064978:\nMERCK & CO INC:0000310158:\n")

    r = IssuerRecord(_Edgar(), name_index=load)
    assert loads == []
    assert sorted(r.exact_holders("MERCK & CO INC")) == [64978, 310158] and r.exact_holders("NOPE") == []
    assert r.name_index() is r.name_index() and loads == [1]
    index = CikNameIndex.from_text("MERCK & CO INC:0000064978:\n")
    assert IssuerRecord(_Edgar(), name_index=index).name_index() is index
    assert IssuerRecord(_Edgar()).name_index() is None and IssuerRecord(_Edgar()).exact_holders("MERCK") == []


def test_a_name_index_that_cannot_be_loaded_is_none_and_not_asked_again_but_a_refusal_stops_the_run():
    loads = []

    def down():
        loads.append(1)
        raise requests.ConnectionError("down")

    r = IssuerRecord(_Edgar(), name_index=down)
    assert r.name_index() is None and r.name_index() is None and loads == [1]

    def refused():
        raise EdgarBlocked("403")

    with pytest.raises(EdgarBlocked):
        IssuerRecord(_Edgar(), name_index=refused).name_index()


# --- warm passes ----------------------------------------------------------------------------------------------------

def test_a_shadow_starts_from_what_is_remembered_and_keeps_its_own_reads():
    e = _Edgar({1: {"name": "A"}, 2: {"name": "B"}})
    index = CikNameIndex.from_text("A:0000000001:\n")
    r = IssuerRecord(e, today=date(2023, 6, 1), name_index=index)
    r.names(1)
    s = r.shadow()
    assert (s.edgar, s.today, s.name_index()) == (e, date(2023, 6, 1), index)
    assert s.names(1) == ("A",) and _reads(e, "submissions", 1) == 1      # from the snapshot
    s.names(2)
    r.names(2)
    assert _reads(e, "submissions", 2) == 2                                 # the shadow's read stayed its own

"""Pipeline stage 9d (sub-plan 5c): the Form 25 search for the successors the run added -- a line successor (seen
over its new CUSIP's fails rows) and an 8-K12B successor (alive from its 8-K12B until its issuer's Form 25)."""
from __future__ import annotations

from datetime import date

from delist_detection import pipeline
from delist_detection.added_securities import AddedAcquirer, AddedLineSuccessor, AddedSuccessor
from delist_detection.classifier import DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import DelistingFinder
from delist_detection.edgar import EdgarSubmission
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.manifest import StageMeter
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver

CIK, SID = 777001, "BBG000NEWLN1"
NYSE_RAW = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>New York Stock Exchange LLC</entityName>"
            "</exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
            "<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision></notificationOfRemoval>")


def _edgar(fake_edgar):
    fake_edgar.submissions_by_cik[CIK] = [
        EdgarSubmission("F25-1", "25-NSE", "2020-06-01", "", "", "primary_doc.xml"),
        EdgarSubmission("K-1", "8-K", "2020-06-01", "2020-06-01", "2.01,3.01,3.03,5.01,9.01", "k.htm"),
        EdgarSubmission("F15-1", "15-12B", "2020-06-11", "", "", "f.htm"),
        EdgarSubmission("Q-1", "10-Q", "2019-11-01", "", "", "q.htm"),
    ]
    fake_edgar.company_map["NEWC"] = {"cik_str": CIK, "ticker": "NEWC", "title": "Newco Corp"}
    fake_edgar.raws["F25-1"] = NYSE_RAW
    fake_edgar.texts["K-1"] = ("Item 3.01 Notice of Delisting. requested that trading be suspended prior to the "
                               "opening of trading on June 2, 2020 " + "x" * 300)
    return fake_edgar


def _ends(fake_edgar, monkeypatch, added, *, listed=False, form25=True):
    edgar = _edgar(fake_edgar)
    if not form25:
        edgar.submissions_by_cik[CIK] = [f for f in edgar.submissions_by_cik[CIK] if f.form != "25-NSE"]
    clients = pipeline.Clients(edgar=edgar, resolver=None, classifier=DelistClassifier(edgar, TickerResolver(edgar)),
                               figi=None, ftd_client=None, as_of=date(2026, 9, 25))
    monkeypatch.setattr(pipeline, "listed_today", lambda *a, **k: listed)
    ctx = pipeline._RunContext(clients, date(2026, 9, 25), lambda *a: None, 1, StageMeter(lambda *a: None))
    rows = [r for a in added.values() for r in getattr(a, "rows", [])]
    finder = DelistingFinder(edgar, clients.classifier)
    return pipeline._successor_endings(ctx, finder, added, {}, {}, FtdIndex(rows))


def _security():
    return Security(SID, CIK, "COMMON", "NEWCO CORP", "Common Stock", False, "cusip")


def test_a_line_successor_takes_its_own_form25_ending(fake_edgar, monkeypatch):
    rows = [FtdRow(f"2020-0{m}-15", "65249B109", "NEWC", "NEWCO CORP", 10.0 + m) for m in range(1, 6)]
    a = AddedLineSuccessor(_security(), "NEWC", "2019-06-03", rows)
    ends = _ends(fake_edgar, monkeypatch, {SID: a})
    assert [(d.sec_id, d.delist_date, d.record.bucket) for d in ends.delistings] == [
        (SID, "2020-06-11", CrspBucket.MERGER)]
    assert [d.ticker for d in ends.delistings] == ["NEWC"]
    # searched from its own span and CUSIPs: the stage hands back the security as the run added it, no era made up
    assert ends.securities[SID] is a.security and a.security.eras == [] and ends.cusips[SID] == ["65249B109"]


def test_an_8k12b_successor_is_searched_to_the_run_date_and_its_span_runs_to_the_ending(fake_edgar, monkeypatch):
    """TiVo Corp, Rovi's successor (8-K12B 2016-09-08), merged into Xperi in 2020: no fails rows of its own."""
    a = AddedSuccessor(_security(), "NEWC", "2016-09-08")
    ends = _ends(fake_edgar, monkeypatch, {SID: a})
    assert [(d.delist_date, d.last_trade.day) for d in ends.delistings] == [("2020-06-11", date(2020, 6, 1))]
    assert a.span() == ("2016-09-08", "2020-06-01")


def test_a_successor_listed_today_or_an_acquirer_takes_no_ending(fake_edgar, monkeypatch):
    rows = [FtdRow("2020-03-15", "65249B109", "NEWC", "NEWCO CORP", 10.0)]
    assert _ends(fake_edgar, monkeypatch, {SID: AddedLineSuccessor(_security(), "NEWC", "2019-06-03", rows)},
                 listed=True).delistings == []
    assert _ends(fake_edgar, monkeypatch, {SID: AddedAcquirer(_security(), "NEWC", date(2019, 6, 3))}).delistings == []


def test_no_form25_means_no_fallback_ending(fake_edgar, monkeypatch):
    rows = [FtdRow("2020-03-15", "65249B109", "NEWC", "NEWCO CORP", 10.0)]
    ends = _ends(fake_edgar, monkeypatch, {SID: AddedLineSuccessor(_security(), "NEWC", "2019-06-03", rows)},
                 form25=False)
    assert ends.delistings == [] and ends.review == []


def test_the_predecessors_form25_at_the_successors_first_day_is_not_its_ending(fake_edgar, monkeypatch):
    """Clear Channel Outdoor 2019: the old line's 25-NSE is filed the day before the new line's first fails row."""
    rows = [FtdRow("2020-06-02", "65249B109", "NEWC", "NEWCO CORP", 10.0)]
    assert _ends(fake_edgar, monkeypatch, {SID: AddedLineSuccessor(_security(), "NEWC", "2020-05-20", rows)}
                 ).delistings == []


class _FailingHalts:
    """A Nasdaq halt feed whose every day fails to answer."""

    def __init__(self):
        self.failed = []

    def deletion_halt(self, ticker, lo, hi, max_days=5):
        self.failed.append(lo)
        return None

    def failed_days(self):
        return tuple(self.failed)


def _ctx(edgar, monkeypatch):
    clients = pipeline.Clients(edgar=edgar, resolver=None, classifier=DelistClassifier(edgar, TickerResolver(edgar)),
                               figi=None, ftd_client=None, as_of=date(2026, 9, 25))
    monkeypatch.setattr(pipeline, "listed_today", lambda *a, **k: False)
    return clients, pipeline._RunContext(clients, date(2026, 9, 25), lambda *a: None, 1, StageMeter(lambda *a: None))


def test_a_failed_halt_feed_read_makes_the_ending_resolution_degraded(fake_edgar, monkeypatch):
    edgar = _edgar(fake_edgar)
    edgar.texts["K-1"] = "Item 3.01 Notice of Delisting. " + "x" * 300        # no 8-K text date: the feed is asked
    clients, ctx = _ctx(edgar, monkeypatch)
    finder = DelistingFinder(edgar, clients.classifier, halts=_FailingHalts())
    a = AddedSuccessor(_security(), "NEWC", "2016-09-08")
    ends = pipeline._successor_endings(ctx, finder, {SID: a}, {}, {}, FtdIndex([]))
    assert [d.delist_date for d in ends.delistings] == ["2020-06-11"]
    assert "resolution_degraded" in ends.delistings[0].flags
    degraded = [r for r in ends.review if r.flag == "resolution_degraded"]
    assert len(degraded) == 1 and "halt feed" in degraded[0].reason


def test_the_finders_review_rows_are_kept(fake_edgar, monkeypatch):
    from delist_detection.review_triage import ReviewItem
    edgar = _edgar(fake_edgar)
    clients, ctx = _ctx(edgar, monkeypatch)
    item = ReviewItem(SID, "NEWC", CIK, "ticker_unconfirmed", "from the finder")

    class _Finder:
        def find(self, context, fallback=True):
            return [], [item]

    ends = pipeline._successor_endings(ctx, _Finder(), {SID: AddedSuccessor(_security(), "NEWC", "2016-09-08")},
                                       {}, {}, FtdIndex([]))
    assert ends.review == [item]


def test_a_line_successors_span_is_clipped_at_its_own_last_trade(fake_edgar, monkeypatch):
    """California Resources' 2016 line: fails rows run on past the last trade of its own ending."""
    rows = [FtdRow(f"2020-0{m}-15", "65249B109", "NEWC", "NEWCO CORP", 10.0 + m) for m in range(1, 9)]
    a = AddedLineSuccessor(_security(), "NEWC", "2019-06-03", rows)
    ends = _ends(fake_edgar, monkeypatch, {SID: a})
    assert ends.delistings[0].last_trade.day == date(2020, 6, 1)
    assert a.span() == ("2019-06-03", "2020-06-01")


def test_the_role_refusals_are_logged_once_as_one_line(fake_edgar, monkeypatch):
    from types import SimpleNamespace as NS
    lines = []
    ctx = pipeline._RunContext(None, date(2026, 9, 25), lines.append, 1, StageMeter(lambda *a: None))
    rows = [NS(sec_id="B", record=NS(evidence={"survived": "each share of Mirant ..."})),
            NS(sec_id="A", record=NS(evidence={"survived": "the Company issued ..."})),
            NS(sec_id="C", record=NS(evidence={}))]
    pipeline._log_role_refusals(ctx, rows)
    assert lines == ["role refusal: 2 rows (A, B)"]

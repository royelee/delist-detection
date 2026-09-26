"""What a run rested on: a `resolution_degraded` review row for every era,
security, payout and successor search whose answer rested on a failed request or
a stale copy, and run_manifest.json beside the tables."""
import json
from datetime import date

import pytest
import requests

import delist_detection.pipeline as pipeline
from delist_detection import edgar, manifest
from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import Delisting
from delist_detection.edgar import SEC_STATS, EdgarBlocked
from delist_detection.last_trade import LastTrade
from delist_detection.observations import Observation
from delist_detection.payout_extractor import PayoutResult
from delist_detection.pipeline import Overrides, run
from delist_detection.store import read_table, table_path
from tests.test_pipeline import LIVE_FIGI, _clients, _index_clients, _same_ticker_acquirer_run


@pytest.fixture(autouse=True)
def _pinned_code_version(monkeypatch):
    monkeypatch.setattr(manifest, "code_version", lambda: "test-version")


def _review(out):
    return read_table("review", table_path(out, "review"))


def _delistings(out):
    return read_table("delistings", table_path(out, "delistings"))


def test_an_era_resolved_through_a_failed_request_is_flagged_resolution_degraded(fake_edgar, tmp_path):
    fake_edgar.company_map["LIVE"] = {"cik_str": 777, "ticker": "LIVE", "title": "LIVE CO"}
    fake_edgar.submissions_by_cik[777] = []            # the ticker map's holder did not exist on the date

    def down(company, form_type="25-NSE"):
        raise requests.ConnectionError("no route to host")

    fake_edgar.company_search_atom = down               # the name search cannot reach EDGAR
    index, clients = _index_clients(fake_edgar, [Observation("LIVE", "2025-06-30", "LIVE CO")], [],
                                    {("TICKER", "LIVE"): LIVE_FIGI})
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    rows = [r for r in _review(tmp_path) if r["review_flags"] == "resolution_degraded"]
    assert [(r["ticker"], r["sec_id"]) for r in rows] == [("LIVE", "BBG000LIVE01")]
    assert "not saved" in rows[0]["reason"]


def test_a_security_searched_through_a_stale_copy_is_flagged_resolution_degraded(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    real = fake_edgar.recent_filings

    def stale_for_aet(cik):
        if int(cik) == 1122304:
            SEC_STATS.degraded("stale_copy")            # what EdgarClient does when it serves a stale copy
        return real(cik)

    fake_edgar.recent_filings = stale_for_aet
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert [r["sec_id"] for r in _review(tmp_path) if r["review_flags"] == "resolution_degraded"] == ["BBG000FJLFX8"]
    # the delisting search rested on a stale copy, so the delisting's own
    # row (not just review.csv) carries the flag too.
    (d,) = _delistings(tmp_path)
    assert "resolution_degraded" in d["review_flags"].split(";")


def test_a_payout_read_through_a_failed_request_is_flagged_with_its_delisting(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)

    class _FailingRead:
        def extract(self, record, last_close=None):
            SEC_STATS.degraded("failed_request")        # a filing text the payout reader could not fetch
            return PayoutResult.none()

    clients.payout_extractor = _FailingRead()
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    rows = [r for r in _review(tmp_path) if r["review_flags"] == "resolution_degraded"]
    assert [(r["sec_id"], r["delist_date"]) for r in rows] == [("BBG000FJLFX8", "2018-12-09")]
    # the payout read rested on a failed request, so the delisting's own
    # row carries the flag too.
    (d,) = _delistings(tmp_path)
    assert "resolution_degraded" in d["review_flags"].split(";")


class _HaltSession:
    """The Nasdaq halt feed: every day times out, or every day answers 404."""

    def __init__(self, status=None):
        self.status = status

    def get(self, url, headers=None, timeout=None):
        if self.status is None:
            raise requests.Timeout("read timed out")
        resp = requests.models.Response()
        resp.status_code = self.status
        return resp


def _with_halt_feed(fake_edgar, tmp_path, session):
    from delist_detection.nasdaq_halts import NasdaqHaltClient

    index, clients = _clients(fake_edgar)
    clients.halts = NasdaqHaltClient(tmp_path / "halts", session=session, min_interval=0, sleep=lambda _: None)
    out = tmp_path / "out"
    summary = run(index, clients, Overrides(), out_dir=out, log=lambda *_: None)
    return out, summary


def test_a_last_trade_date_that_asked_a_failed_halt_feed_day_is_flagged_resolution_degraded(fake_edgar, tmp_path):
    """AET's last trade has no MIDAS day, so the finder asks the Nasdaq halt feed;
    the feed times out. That is not "no halts": the delisting is flagged like one
    that rested on a failed SEC request, on its own row and in review.csv, with a
    reason naming the halt feed and the days, and the run exits 3."""
    out, summary = _with_halt_feed(fake_edgar, tmp_path, _HaltSession())
    (d,) = _delistings(out)
    assert "resolution_degraded" in d["review_flags"].split(";")
    rows = [r for r in _review(out) if "resolution_degraded" in r["review_flags"].split(";")
            and "Nasdaq halt feed" in r["reason"]]
    assert [(r["sec_id"], r["delist_date"]) for r in rows] == [("BBG000FJLFX8", "2018-12-09")]
    assert "2018-11-" in rows[0]["reason"]                          # the days it could not read
    assert "failed EDGAR request" not in rows[0]["reason"]
    assert summary.review_flags.get("resolution_degraded", 0) >= 1
    m = json.loads((out / "run_manifest.json").read_text())
    assert m["degraded_answers"].get("nasdaq_halt_feed", 0) >= 1 and "failed_request" not in m["degraded_answers"]


def test_a_halt_feed_that_answers_404_flags_nothing(fake_edgar, tmp_path):
    out, summary = _with_halt_feed(fake_edgar, tmp_path, _HaltSession(404))
    (d,) = _delistings(out)
    assert "resolution_degraded" not in d["review_flags"]
    assert summary.review_flags.get("resolution_degraded", 0) == 0


def test_a_successor_search_whose_efts_refetch_failed_is_flagged_resolution_degraded(fake_edgar, tmp_path,
                                                                                      monkeypatch):
    """Task 5's review: a stale EFTS answer whose refetch fails is caught by
    EdgarClient.full_text_search, which returns [] rather than raise (so the
    successor search leaves successor_unknown instead of aborting the run) --
    but only after edgar.py has recorded the failed request as degraded. The
    successor search must be flagged, not silently left unresolved."""
    index, clients = _clients(fake_edgar)
    record = DelistRecord(ticker="AET", cik=1122304, observed_delist_date="2018-11-28", crsp_code=304,
                          bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="high", reason="moved exchanges",
                          evidence={"flags": ["successor_unknown"]}, sec_id="BBG000FJLFX8",
                          delist_date="2018-12-09")
    ev = Delisting(sec_id="BBG000FJLFX8", cik=1122304, ticker="AET", delist_date="2018-12-09", record=record,
                        last_trade=LastTrade(date(2018, 11, 28), "notice_a", ()), form25=None, form25_sub=None,
                        exchange="NYSE")

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return ([ev], []) if ctx.security.sec_id == "BBG000FJLFX8" else ([], [])

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)

    def degraded_search(q, forms, lo, hi):
        # what EdgarClient.full_text_search does when the cached copy is stale
        # and the refetch fails: record the failure, then answer []
        SEC_STATS.degraded("failed_request")
        return []

    fake_edgar.full_text_search = degraded_search

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    rows = [r for r in _review(tmp_path) if r["review_flags"] == "resolution_degraded"]
    assert [(r["sec_id"], r["delist_date"]) for r in rows] == [("BBG000FJLFX8", "2018-12-09")]
    d = read_table("delistings", table_path(tmp_path, "delistings"))[0]
    assert d["successor_sec_id"] == ""     # left unresolved, not guessed
    # the successor search rested on a failed request, so the delisting's
    # own row carries the flag too.
    assert "resolution_degraded" in d["review_flags"].split(";")


def test_an_acquirer_cik_lookup_through_a_stale_copy_is_flagged_naming_the_acquirer(fake_edgar, tmp_path):
    """_acquirer_cik falls through to the SEC ticker-map holder's own
    submissions JSON (edgar_lists) when the acquirer took the target's own
    ticker -- the Waste Connections 2016 scenario. A stale copy served there
    must add a resolution_degraded row naming the acquirer ticker."""
    real = fake_edgar.submissions

    def stale_for_holder(cik, fresh_after=None):
        if int(cik) == 1318220:
            SEC_STATS.degraded("stale_copy")
        return real(cik, fresh_after=fresh_after)

    fake_edgar.submissions = stale_for_holder
    _same_ticker_acquirer_run(fake_edgar, tmp_path, holder=1318220)
    rows = [r for r in _review(tmp_path) if r["review_flags"] == "resolution_degraded"]
    assert any("WCN" in r["reason"] for r in rows)


def test_a_clean_acquirer_cik_lookup_is_not_flagged(fake_edgar, tmp_path):
    _same_ticker_acquirer_run(fake_edgar, tmp_path, holder=1318220)
    assert not any(r["review_flags"] == "resolution_degraded" for r in _review(tmp_path))


def test_a_clean_run_has_no_resolution_degraded_row(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert not any(r["review_flags"] == "resolution_degraded" for r in _review(tmp_path))
    # a clean run's delistings.csv is unaffected too.
    assert not any("resolution_degraded" in d["review_flags"].split(";") for d in _delistings(tmp_path))


def test_the_manifest_records_what_the_run_rested_on(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    clients.as_of = date(2026, 9, 23)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=2)
    m = json.loads((tmp_path / "run_manifest.json").read_text())
    assert (m["as_of"], m["code_version"], m["sec_workers"]) == ("2026-09-23", "test-version", 2)
    # warm_failed is added beyond the brief: SEC_STATS also counts warm_failed:<stage>
    # (Task 9), and the manifest reports every counter group the brief's own
    # _by_prefix helper would otherwise silently drop.
    assert set(m) == {"as_of", "code_version", "sec_workers", "sec_requests", "cache_answers",
                      "degraded_answers", "warm_degraded", "rejected_queries", "not_covered", "warm_failed",
                      "latency_ms", "stages", "resolution_degraded", "review"}
    assert set(m["stages"]) == {"issuer resolution", "delisting search", "payouts", "successor search"}
    assert m["resolution_degraded"] == 0
    assert m["review"] == {"fix": 0, "check": 2, "info_hidden": 0, "accepted": 0, "cleared": 0,
                           "unmatched_decisions": 0}     # review_triage.triage()'s own tally


def test_a_refused_run_leaves_the_previous_manifest_in_place(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    before = (tmp_path / "run_manifest.json").read_bytes()

    def blocked(*a, **k):
        raise EdgarBlocked("SEC returned 403")

    clients.edgar.fetch_filing_raw = blocked
    with pytest.raises(EdgarBlocked):
        run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=3)
    assert (tmp_path / "run_manifest.json").read_bytes() == before


def test_latency_percentiles_per_endpoint():
    got = manifest.build(as_of=date(2026, 9, 23), sec_workers=1, counts={"request:archives": 4},
                         timings={"archives": [0.1, 0.2, 0.3, 1.0]}, stages={}, review_flags={}, review={})
    assert got["latency_ms"] == {"archives": {"n": 4, "p50": 200.0, "p95": 1000.0, "max": 1000.0}}
    assert got["sec_requests"] == {"archives": 4}


def test_the_manifest_reports_warm_failed_and_rejected_by_stage_or_endpoint():
    # SEC_STATS also counts warm_failed:<stage> (Task 9) and rejected:<endpoint>
    # (Task 5/7); the manifest must not silently drop either group.
    got = manifest.build(as_of=date(2026, 9, 23), sec_workers=4,
                         counts={"warm_failed:delisting search": 2, "rejected:company_search": 1,
                                "rejected:full_text_search": 3, "not_covered:full_text_search": 1},
                         timings={}, stages={}, review_flags={}, review={})
    assert got["warm_failed"] == {"delisting search": 2}
    assert got["rejected_queries"] == {"company_search": 1, "full_text_search": 3}
    assert got["not_covered"] == {"full_text_search": 1}


def test_the_manifest_separates_warm_degraded_from_the_sequential_passs_own(tmp_path):
    # a warm thread's degraded reads (edgar.SEC_STATS, filling_only())
    # are counted under warm_degraded:<kind>, apart from degraded_answers, which
    # then reflects only what the sequential pass relied on.
    got = manifest.build(as_of=date(2026, 9, 23), sec_workers=4,
                         counts={"degraded:stale_copy": 1, "warm_degraded:failed_request": 3},
                         timings={}, stages={}, review_flags={}, review={})
    assert got["degraded_answers"] == {"stale_copy": 1}
    assert got["warm_degraded"] == {"failed_request": 3}


def _live_pinned(fake_edgar):
    """LIVE, its issuer pinned on the observation (so the resolver reads nothing):
    the first submissions read of CIK 777 is the issuer-names read."""
    fake_edgar.company_map["LIVE"] = {"cik_str": 777, "ticker": "LIVE", "title": "LIVE CO"}
    fake_edgar.submissions_by_cik[777] = []
    return _index_clients(fake_edgar, [Observation("LIVE", "2025-06-30", "LIVE CO", cik=777)], [],
                          {("TICKER", "LIVE"): LIVE_FIGI})


def test_an_issuer_names_read_that_fails_is_a_degraded_answer_not_an_abort(fake_edgar, tmp_path):
    real = fake_edgar.submissions
    calls = []

    def first_read_fails(cik, fresh_after=None):
        calls.append(int(cik))
        if calls.count(777) == 1:
            SEC_STATS.degraded("failed_request")        # what EdgarClient records before it raises
            raise requests.ConnectionError("no route to host")
        return real(cik, fresh_after=fresh_after)

    index, clients = _live_pinned(fake_edgar)
    fake_edgar.submissions = first_read_fails
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    rows = [r for r in _review(tmp_path) if r["review_flags"] == "resolution_degraded"]
    assert [(r["ticker"], r["sec_id"]) for r in rows] == [("LIVE", "BBG000LIVE01")]
    assert "the issuer's EDGAR names rested on a failed EDGAR request" in rows[0]["reason"]


def test_the_issuer_names_read_is_metered_with_issuer_resolution_and_warmed(fake_edgar, tmp_path):
    import threading
    real = fake_edgar.submissions
    names_reads = []

    def counted(cik, fresh_after=None):
        if fresh_after is None and int(cik) == 777 and not names_reads:
            SEC_STATS.add("request:submissions")        # the one request a cold cache would send
        names_reads.append(threading.current_thread().name)
        return real(cik, fresh_after=fresh_after)

    index, clients = _live_pinned(fake_edgar)
    fake_edgar.submissions = counted
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=2)
    stages = json.loads((tmp_path / "run_manifest.json").read_text())["stages"]
    assert stages["issuer resolution"]["edgar_requests"] == 1
    assert names_reads[0].startswith("sec-warm")                # the warm pass read it first

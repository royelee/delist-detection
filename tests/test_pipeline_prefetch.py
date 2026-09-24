# tests/test_pipeline_prefetch.py
"""pipeline.run with --sec-workers: warm passes on worker threads ahead of each
SEC-heavy stage, the stage itself still sequential on the main thread, one run
date, per-stage request counts, the resolver memo flushed even when a later
stage is refused, and the same bytes from one worker and from N."""
import gzip
import json
import os
import shutil
import threading
import time
from datetime import date
from types import SimpleNamespace

import pytest

import delist_detection.pipeline as pipeline
from delist_detection import edgar
from delist_detection.classifier import DelistClassifier, DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import DelistingEvent
from delist_detection.edgar import EFTS_KEY, EFTS_SCHEMA, FETCHED_KEY, EdgarBlocked, EdgarClient
from delist_detection.last_trade import LastTrade
from delist_detection.midas import MIDAS_INDEX_URL, MidasClient
from delist_detection.observations import Observation, ObservationIndex
from delist_detection.openfigi import OpenFigiBlocked
from delist_detection.payout_extractor import PayoutExtractor, PayoutResult
from delist_detection.pipeline import Clients, Overrides, run, successor_query
from delist_detection.prefetch import Serialized
from delist_detection.store import read_table, table_path
from delist_detection.ticker_resolver import TickerResolver
from tests.test_pipeline import AET_RAW, _clients, _Figi, _figi_answer, _ftd, _FtdClient, _index_clients


def test_one_worker_starts_no_prefetch(fake_edgar, tmp_path, monkeypatch):
    index, clients = _clients(fake_edgar)
    calls = []
    monkeypatch.setattr(pipeline, "warm", lambda *a, **k: calls.append(a))
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert calls == []


def test_issuer_resolution_is_warmed_on_worker_threads_first(fake_edgar, tmp_path, monkeypatch):
    obs = [Observation("BAD", "2023-05-10", "Bad Co."), Observation("LIQ", "2019-11-06", "Liquidating Trust")]
    index, clients = _index_clients(fake_edgar, obs, [], {})
    calls = []
    real = TickerResolver.resolve

    def recording(self, ticker, observed_date=None, **kw):
        calls.append((ticker, threading.current_thread().name, self is clients.resolver))
        return real(self, ticker, observed_date, **kw)

    monkeypatch.setattr(TickerResolver, "resolve", recording)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    warmed = {t for t, name, own in calls if name.startswith("sec-warm") and not own}
    assert warmed == {"BAD", "LIQ"}                                  # every era, by a shadow, on a worker
    assert all(name == threading.main_thread().name for _, name, own in calls if own)


def test_each_stage_logs_its_edgar_requests_apart_from_data_file_downloads(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    lines = []
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *a: lines.append(" ".join(map(str, a))))
    for stage in ("issuer resolution", "delisting search", "payouts", "successor search"):
        assert any(line.startswith(f"{stage}: ") and "EDGAR requests" in line
                   and "SEC data-file downloads" in line for line in lines), stage


def test_the_fails_to_deliver_window_ends_on_the_run_date(fake_edgar, tmp_path):
    class _DatedFtd(_FtdClient):
        def __init__(self):
            self.windows = []

        def urls_for(self, lo, hi):
            self.windows.append((lo, hi))
            return ["mem"]

    index, clients = _clients(fake_edgar)
    clients.ftd_client = _DatedFtd()
    clients.as_of = date(2019, 1, 31)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert max(hi for _, hi in clients.ftd_client.windows) == date(2019, 1, 31)


def test_resolver_answers_are_saved_even_when_a_later_stage_is_refused(fake_edgar, tmp_path):
    cache = tmp_path / "res.json"
    obs = [Observation("BAD", "2023-05-10", "Bad Co.")]
    index = ObservationIndex(obs)
    _, clients = _index_clients(fake_edgar, obs, [], {})
    clients.resolver = TickerResolver(fake_edgar, cache_path=cache, member_names=index.name_on,
                                      cik_map=index.cik_pin_on, batch_writes=True)

    def blocked(*a, **k):
        raise EdgarBlocked("SEC returned 403")

    fake_edgar.fetch_filing_raw = blocked                 # the Form 25 search is refused
    with pytest.raises(EdgarBlocked):
        run(index, clients, Overrides(), out_dir=tmp_path / "out", log=lambda *_: None)
    assert "BAD|2023-05-10" in json.loads(cache.read_text())["entries"]


@pytest.mark.parametrize("exc", [EdgarBlocked("SEC returned 403"), OpenFigiBlocked("OpenFIGI returned 401"),
                                 KeyboardInterrupt(), RuntimeError("boom")],
                         ids=["edgar_refusal", "openfigi_refusal", "ctrl_c", "other_error"])
def test_answers_resolved_before_an_abort_inside_issuer_resolution_are_saved(fake_edgar, tmp_path, monkeypatch,
                                                                             exc):
    """BAD resolves, then LIQ's resolve is cut short: the stage never reaches its
    own flush, so only run()'s way out can write BAD's batched answer."""
    cache = tmp_path / "res.json"
    obs = [Observation("BAD", "2023-05-10", "Bad Co."), Observation("LIQ", "2019-11-06", "Liquidating Trust")]
    index = ObservationIndex(obs)
    _, clients = _index_clients(fake_edgar, obs, [], {})
    clients.resolver = TickerResolver(fake_edgar, cache_path=cache, member_names=index.name_on,
                                      cik_map=index.cik_pin_on, batch_writes=True)
    real = TickerResolver.resolve

    def cut_short(self, ticker, observed_date=None, **kw):
        if ticker == "LIQ":
            raise exc
        return real(self, ticker, observed_date, **kw)

    monkeypatch.setattr(TickerResolver, "resolve", cut_short)
    with pytest.raises(type(exc)):
        run(index, clients, Overrides(), out_dir=tmp_path / "out", log=lambda *_: None)
    assert set(json.loads(cache.read_text())["entries"]) == {"BAD|2023-05-10"}
    assert not (tmp_path / "out").exists()


def test_default_clients_share_one_run_date_and_a_machine_wide_limit(tmp_path, monkeypatch):
    monkeypatch.setenv(edgar.SEC_RATE_LOCK_ENV, str(tmp_path / "sec_rate.lock"))
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    index = ObservationIndex([Observation("AET", "2018-06-29", "AETNA INC")])
    c = pipeline.default_clients(index, cache_dir=tmp_path / "cache", as_of=date(2026, 9, 23),
                                 extract_payouts=False)
    assert c.as_of == c.edgar.today == c.resolver.today == c.classifier.today == c.halts.today == date(2026, 9, 23)
    assert c.resolver.batch_writes is True
    assert edgar.SEC_LIMITER.gate is not None and edgar.SEC_LIMITER.gate.path == tmp_path / "sec_rate.lock"


class _Midas:
    def last_trade_day(self, ticker, lo, hi):
        return None


class _Halts:
    def deletion_halt(self, symbol, lo, hi, max_days=7):
        return None


def test_the_warm_finders_are_the_sequential_finders_twins(fake_edgar, tmp_path, monkeypatch):
    index, clients = _clients(fake_edgar)
    clients.midas, clients.halts = _Midas(), _Halts()
    built = []
    real = pipeline.DelistingFinder

    class _Spy(real):
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            built.append((midas, halts, classifier))
            super().__init__(edgar, classifier, midas=midas, halts=halts)

    monkeypatch.setattr(pipeline, "DelistingFinder", _Spy)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    (seq_midas, seq_halts, seq_classifier), *warm_built = built      # the sequential finder is built first
    assert seq_midas is clients.midas and seq_halts is clients.halts and seq_classifier is clients.classifier
    assert warm_built
    for midas, halts, classifier in warm_built:
        assert isinstance(midas, Serialized) and midas._obj is clients.midas
        assert isinstance(halts, Serialized) and halts._obj is clients.halts
        assert classifier is not clients.classifier                     # a copy of the run's classifier
        assert classifier.resolver is not clients.resolver and isinstance(classifier.resolver, TickerResolver)
    assert len({id(m) for m, _, _ in warm_built}) == 1                 # one lock shared by every warm finder
    assert clients.classifier.resolver is clients.resolver             # the run's own classifier is untouched


def test_prefetch_reads_edgar_on_worker_threads_before_the_sequential_pass(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    seen, real = [], fake_edgar.recent_filings

    def recording(cik):
        seen.append((int(cik), threading.current_thread().name))
        return real(cik)

    fake_edgar.recent_filings = recording
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    names = [name for cik, name in seen if cik == 1122304]
    assert any(n.startswith("sec-warm") for n in names)                # the prefetch read it
    assert names[-1] == threading.main_thread().name                   # and the sequential pass read it after


def test_a_refusal_on_a_worker_thread_aborts_the_run_and_writes_nothing(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    before = {p.name: p.read_text() for p in tmp_path.glob("*.csv")}
    main_calls, real = [], fake_edgar.fetch_filing_raw

    def refused_on_workers(cik, accession):
        if threading.current_thread() is not threading.main_thread():
            raise EdgarBlocked("SEC returned 403")
        main_calls.append(accession)
        return real(cik, accession)

    fake_edgar.fetch_filing_raw = refused_on_workers
    with pytest.raises(EdgarBlocked):
        run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    assert main_calls == []                                            # the sequential pass never began
    assert {p.name: p.read_text() for p in tmp_path.glob("*.csv")} == before


def test_the_runs_own_resolver_only_ever_runs_on_the_main_thread(fake_edgar, tmp_path, monkeypatch):
    index, clients = _clients(fake_edgar)
    r, seen, other = clients.resolver, [], []
    real_resolve, real_fits = r.resolve, r._fits_date
    class_resolve, class_fits = TickerResolver.resolve, TickerResolver._fits_date

    def resolve(*a, **k):
        seen.append(threading.current_thread().name)
        return real_resolve(*a, **k)

    def fits(*a, **k):
        seen.append(threading.current_thread().name)
        return real_fits(*a, **k)

    def any_resolve(self, *a, **k):                 # every other resolver: the warm passes' shadows
        other.append(threading.current_thread().name)
        return class_resolve(self, *a, **k)

    def any_fits(self, *a, **k):
        other.append(threading.current_thread().name)
        return class_fits(self, *a, **k)

    r.resolve, r._fits_date = resolve, fits        # its `_transient` flag must never be shared across threads
    monkeypatch.setattr(TickerResolver, "resolve", any_resolve)
    monkeypatch.setattr(TickerResolver, "_fits_date", any_fits)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    assert seen and set(seen) == {threading.main_thread().name}
    assert any(name.startswith("sec-warm") for name in other)        # the warm passes did reach a resolver


def test_a_failure_only_a_warm_worker_meets_is_counted_under_its_stage(fake_edgar, tmp_path, monkeypatch):
    index, clients = _clients(fake_edgar)
    raised = {"issuer resolution": 0, "form25 scan": 0}
    real_resolve, real_raw = TickerResolver.resolve, fake_edgar.fetch_filing_raw

    def resolve(self, *a, **k):
        if threading.current_thread() is not threading.main_thread():
            raised["issuer resolution"] += 1
            raise RuntimeError("boom")
        return real_resolve(self, *a, **k)

    def raw(cik, accession):
        if threading.current_thread() is not threading.main_thread():
            raised["form25 scan"] += 1
            raise RuntimeError("boom")
        return real_raw(cik, accession)

    monkeypatch.setattr(TickerResolver, "resolve", resolve)
    fake_edgar.fetch_filing_raw = raw
    mark = edgar.SEC_STATS.snapshot()
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    counts, _ = edgar.SEC_STATS.since(mark)
    assert all(raised.values())
    assert {stage: counts.get(f"warm_failed:{stage}", 0) for stage in raised} == raised


def test_a_refusal_of_the_runs_midas_download_on_a_worker_aborts_the_run(fake_edgar, tmp_path):
    """The run's real MidasClient, behind Serialized: none of its handlers (a
    failed download, a bad ZIP), nor the finder's, swallows a 403, so the pool
    stops and the refusal reaches the caller before the sequential pass asks."""
    index, clients = _clients(fake_edgar)
    (tmp_path / "midas").mkdir()
    (tmp_path / "midas" / "index.html").write_text('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>')
    asked = []

    class _Refusing:
        def get(self, url, headers=None, timeout=None):
            asked.append(threading.current_thread().name)
            return SimpleNamespace(status_code=403, url=url)

    clients.midas = MidasClient(tmp_path / "midas", session=_Refusing())
    with pytest.raises(EdgarBlocked):
        run(index, clients, Overrides(), out_dir=tmp_path / "out", log=lambda *_: None, sec_workers=4)
    assert asked and all(name.startswith("sec-warm") for name in asked)
    assert not (tmp_path / "out").exists()


class _UnsavableResolver:
    """A resolver whose memo cannot be written (the disk is full)."""

    def flush(self):
        raise OSError("No space left on device")


def _unsavable_clients():
    return pipeline.Clients(edgar=None, resolver=_UnsavableResolver(), classifier=None, figi=None, ftd_client=None)


@pytest.mark.parametrize("exc", [EdgarBlocked("SEC returned 403"), OpenFigiBlocked("OpenFIGI returned 401"),
                                 KeyboardInterrupt()], ids=["edgar_refusal", "openfigi_refusal", "ctrl_c"])
def test_a_refusal_or_ctrl_c_wins_over_a_memo_that_cannot_be_saved(tmp_path, monkeypatch, exc):
    """The CLI must still exit 2 on a refusal: the failed flush on the way out is
    logged, and the refusal, not the OSError, reaches the caller."""
    def aborted(*a, **k):
        raise exc

    monkeypatch.setattr(pipeline, "_run", aborted)
    lines = []
    with pytest.raises(type(exc)) as raised:
        run(None, _unsavable_clients(), Overrides(), out_dir=tmp_path, log=lines.append)
    assert raised.value is exc
    assert lines == ["could not save the resolver memo while aborting: No space left on device"]


def test_a_memo_that_cannot_be_saved_after_a_complete_run_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_run", lambda *a, **k: "summary")
    with pytest.raises(OSError, match="No space left on device"):
        run(None, _unsavable_clients(), Overrides(), out_dir=tmp_path, log=lambda *_: None)


def test_the_stage_meter_counts_edgar_requests_apart_from_data_file_downloads():
    lines = []
    meter = pipeline._StageMeter(lines.append)
    mark = meter.start()
    edgar.SEC_STATS.add("request:submissions")
    edgar.SEC_STATS.add("request:sec_data")
    edgar.SEC_STATS.add("cache:submissions")          # a cache answer is not a request
    meter.done("issuer resolution", mark)
    assert meter.stages == {"issuer resolution": {"edgar_requests": 1, "sec_data_downloads": 1}}
    assert lines == ["issuer resolution: 1 EDGAR requests, 1 SEC data-file downloads (all threads)"]


# Read at import, before conftest's autouse fixture stubs them for each test.
_REAL_EFTS = {name: getattr(TickerResolver, name) for name in ("_efts_lookup", "_efts_pre_delist_frequency_ranked")}


def test_the_successor_search_query_is_the_one_the_prefetch_sends():
    assert successor_query("GOOGLE INC", date(2015, 10, 2)) == (
        '"GOOGLE INC"', "8-K12B,8-K12G3", date(2015, 9, 2), date(2015, 12, 1))


def test_payout_extraction_is_warmed_on_worker_threads_and_the_llm_is_not(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    regex, llm, guard = [], [], threading.Lock()

    class _Regex:
        def extract(self, record, last_close=None):
            with guard:
                regex.append(threading.current_thread().name)
            return PayoutResult.none()

    class _Llm:
        def extract(self, record):
            with guard:
                llm.append(threading.current_thread().name)
            return None

    clients.payout_extractor, clients.llm_extractor = _Regex(), _Llm()
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    assert any(n.startswith("sec-warm") for n in regex) and regex[-1] == threading.main_thread().name
    assert set(llm) == {threading.main_thread().name}                  # paid calls are never warmed


def test_the_successor_search_is_warmed_with_the_query_the_sequential_pass_sends(fake_edgar, tmp_path,
                                                                                 monkeypatch):
    fake_edgar.company_map["GOOGL"] = {"cik_str": 1288776, "ticker": "GOOGL", "title": "Google Inc."}
    fake_edgar.submissions_by_cik[1288776] = []
    obs = [Observation("GOOGL", d, "GOOGLE INC CLASS A") for d in ("2014-06-30", "2015-06-30")]
    rows = _ftd("GOOGL", "38259P508", "GOOGLE INC;COM USD0.001 CL'A'",
                ["2014-06-02", "2014-12-01", "2015-06-01", "2015-10-02"])
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "38259P508"): _figi_answer("BBGGOOGLEA1", "GOOGL", "GOOGLE INC-CL A"),
        ("TICKER", "GOOGL"): _figi_answer("BBG009S39JX6", "GOOGL", "ALPHABET INC-CL A"),
        ("TICKER", "GOOG"): _figi_answer("BBG009S3NB30", "GOOG", "ALPHABET INC-CL C"),
    })

    def event():
        record = DelistRecord(ticker="GOOGL", cik=1288776, observed_delist_date="2015-10-02", crsp_code=300,
                              bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="high", reason="holdco reorg",
                              evidence={"flags": ["successor_unknown"]}, sec_id="BBGGOOGLEA1",
                              delist_date="2015-10-12")
        return DelistingEvent(sec_id="BBGGOOGLEA1", cik=1288776, ticker="GOOGL", delist_date="2015-10-12",
                              record=record, last_trade=LastTrade(date(2015, 10, 2), "notice_a", ()),
                              form25=None, form25_sub=None, exchange="NASDAQ", flags=["successor_unknown"])

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return [event()], []

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)
    searches, guard = [], threading.Lock()

    def search(q, forms, lo, hi):
        with guard:
            searches.append(((q, forms, lo, hi), threading.current_thread().name))
        return []

    fake_edgar.full_text_search = search
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    queries = {q for q, _ in searches}
    assert queries == {successor_query("Google Inc.", date(2015, 10, 2))}
    names = [n for _, n in searches]
    assert any(n.startswith("sec-warm") for n in names) and names[-1] == threading.main_thread().name


# --- the determinism proof: one worker and N from cloned cache snapshots -----------------

AS_OF = date(2026, 9, 23)
UA = "Test Co test@example.com"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
AET_SUB_URL = "https://data.sec.gov/submissions/CIK0001122304.json"
OLD_SUB_URL = "https://data.sec.gov/submissions/CIK0000002222.json"
XFR_SUB_URL = "https://data.sec.gov/submissions/CIK0000003333.json"
# AET's merger proxy: only the payout reader (stage 8) reads it.
AET_PROXY_URL = "https://www.sec.gov/Archives/edgar/data/1122304/000104746918000999/defm.htm"
_KEYS = ("accessionNumber", "form", "filingDate", "reportDate", "items", "primaryDocument")
AET_FILINGS = [("0000876661-18-001269", "25-NSE", "2018-11-29", "", "", "primary_doc.xml"),
               ("0001122304-18-000178", "8-K", "2018-11-28", "2018-11-28", "2.01,3.01,5.01,9.01", "k.htm"),
               ("0001122304-18-000184", "15-12B", "2018-12-10", "", "", "f.htm"),
               ("0001047469-18-000999", "DEFM14A", "2018-02-08", "", "", "defm.htm")]
OLD_FILINGS = [("0000876661-19-000100", "25-NSE", "2019-02-01", "", "", "primary_doc.xml")]
# XFR files no Form 25 and keeps filing reports long after its last sighting: an
# exchange transfer to an unknown successor, which stage 9 searches for.
XFR_FILINGS = [("0000003333-19-000010", "10-Q", "2019-08-09", "2019-06-30", "", "q.htm"),
               ("0000003333-20-000004", "10-K", "2020-03-02", "2019-12-31", "", "k.htm")]
MIDAS_QUARTERS = ((2018, 3), (2018, 4), (2019, 1))

# The copies _seed leaves stale: each one's stage refreshes it in a one-worker run,
# so a warm worker must read it as it is and never fetch it.
LIVE_FORM25_SEARCH = ("https://efts.sec.gov/LATEST/search-index?q=%22LIVE%22&forms=25-NSE,25,15-12G,15-12B,15-15D"
                      "&dateRange=custom&startdt=2025-04-01&enddt=2025-09-28")
LIVE_8K_SEARCH = ("https://efts.sec.gov/LATEST/search-index?q=%22LIVE%22&forms=8-K"
                  "&dateRange=custom&startdt=2025-03-02&enddt=2025-06-29")
LIVE_NAME_SEARCH = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=LIVE%20CO&type=25-NSE"
                    "&dateb=&owner=include&count=10&output=atom")
XFR_SUCCESSOR_SEARCH = ("https://efts.sec.gov/LATEST/search-index?q=%22XFR%20CORP%22&forms=8-K12B%2C8-K12G3"
                        "&dateRange=custom&startdt=2018-12-01&enddt=2019-03-01")
STALE_URLS = (OLD_SUB_URL, LIVE_FORM25_SEARCH, LIVE_8K_SEARCH, LIVE_NAME_SEARCH, XFR_SUCCESSOR_SEARCH,
              MIDAS_INDEX_URL)


def _midas_index(quarters):
    return "<html>" + "".join(f'<a href="/files/opa/data/market-structure/individual_security_{y}_q{q}.zip">'
                              f"{y} Q{q}</a>" for y, q in quarters) + "</html>"


def _submissions(cik, name, filings):
    return {"cik": str(cik), "name": name, "formerNames": [], "sic": "", "tickers": [], "exchanges": [],
            "filings": {"recent": {k: [f[i] for f in filings] for i, k in enumerate(_KEYS)}}}


class _SecResp:
    def __init__(self, status, text, url):
        self.status_code, self.text, self.url = status, text, url

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class _OfflineSec:
    """A thread-safe stand-in for SEC's servers: canned answers by URL. Any
    full-text search finds nothing, any company-name search matches nothing, and
    any other URL is a 404. Records (url, thread name) of every request."""

    def __init__(self):
        self.answers = {
            TICKERS_URL: json.dumps({"0": {"cik_str": 1122304, "ticker": "AET", "title": "AETNA INC /PA/"}}),
            AET_SUB_URL: json.dumps(_submissions(1122304, "AETNA INC /PA/", AET_FILINGS)),
            OLD_SUB_URL: json.dumps(_submissions(2222, "OLD CO INC", OLD_FILINGS)),
            XFR_SUB_URL: json.dumps(_submissions(3333, "XFR CORP", XFR_FILINGS)),
            "https://www.sec.gov/Archives/edgar/data/1122304/000087666118001269/0000876661-18-001269.txt": AET_RAW,
            "https://www.sec.gov/Archives/edgar/data/1122304/000112230418000178/k.htm":
                "<html>Item 3.01 Notice. trading suspended prior to the opening of trading on November 29, 2018 "
                + "x" * 300 + "</html>",
            AET_PROXY_URL: "<html>Definitive proxy statement. The board recommends a vote FOR the merger.</html>",
            MIDAS_INDEX_URL: _midas_index(MIDAS_QUARTERS),
        }
        self.calls, self._lock = [], threading.Lock()

    def get(self, url, headers=None, timeout=None):
        with self._lock:
            self.calls.append((url, threading.current_thread().name))
        if url in self.answers:
            return _SecResp(200, self.answers[url], url)
        if "efts.sec.gov" in url:
            return _SecResp(200, json.dumps({"hits": {"hits": []}}), url)
        if "/cgi-bin/browse-edgar" in url:
            return _SecResp(200, "<feed></feed>", url)
        return _SecResp(404, "", url)


def _seed(root):
    """The starting cache, with a stale copy on each refresh path the runs reach:
    - OLD's submissions, cached on 2019-01-01, before its Form 25 (2019-02-01): the
      Form 25 scan reads that copy, and the classifier then refreshes it. If a warm
      worker refreshed it first, the sequential pass would read a different copy
      than a one-worker run does, and the tables would differ.
    - Expired full-text-search answers (LIVE's two resolver queries, XFR's successor
      search) and an expired company-name search (LIVE): each is asked again by
      the stage that reads it. They hold today's (empty) answer. A stale answer
      whose hits differ from today's leads a warm worker to fill entries that a
      one-worker run never asks for: the CSVs still agree, the cache trees do not.
    - A 60-day-old MIDAS index that lists only 2018 Q3: read through it, AET's
      last MIDAS trade day would sit too close to the index's coverage end to use,
      so a warm read of it kept for the sequential pass would change AET's row.
    The MIDAS quarter summaries are cached, so no quarter ZIP is ever fetched."""
    client = EdgarClient(cache_dir=root / "edgar", user_agent=UA, session=_OfflineSec(), today=AS_OF)

    def put(url, payload):
        client._cache_path(url).write_text(json.dumps(payload))

    put(OLD_SUB_URL, {**_submissions(2222, "OLD CO INC", []), FETCHED_KEY: "2019-01-01"})
    for url, window_end, fetched in ((LIVE_FORM25_SEARCH, "2025-09-28", "2025-10-01"),
                                     (LIVE_8K_SEARCH, "2025-06-29", "2025-07-02"),
                                     (XFR_SUCCESSOR_SEARCH, "2019-03-01", "2019-03-05")):
        put(url, {"schema": EFTS_SCHEMA, "window_end": window_end, FETCHED_KEY: fetched, EFTS_KEY: []})
    put(LIVE_NAME_SEARCH, {"hits": [], FETCHED_KEY: "2026-09-01"})
    midas = root / "midas"
    midas.mkdir()
    for y, q in MIDAS_QUARTERS:
        (midas / f"{y}_q{q}.json.gz").write_bytes(gzip.compress(json.dumps({"AET": ["2018-11-28"]}).encode()))
    index = midas / "index.html"
    index.write_text(_midas_index(MIDAS_QUARTERS[:1]))
    old = time.time() - 60 * 86400
    os.utime(index, (old, old))


def _offline_run(root, out, workers, *, live_cik=None):
    sec = _OfflineSec()
    edgar_client = EdgarClient(cache_dir=root / "edgar", user_agent=UA, session=sec, sleep=lambda _: None,
                               today=AS_OF)
    obs = [Observation("AET", "2017-06-30", "AETNA INC", cik=1122304),
           Observation("AET", "2018-06-29", "AETNA INC", cik=1122304),
           Observation("OLD", "2018-06-29", "OLD CO INC", cik=2222),
           Observation("OLD", "2018-12-31", "OLD CO INC", cik=2222),
           Observation("XFR", "2018-06-29", "XFR CORP", cik=3333),
           Observation("XFR", "2018-12-31", "XFR CORP", cik=3333),
           Observation("LIVE", "2025-06-30", "LIVE CO", cik=live_cik)]
    index = ObservationIndex(obs)
    resolver = TickerResolver(edgar_client, cache_path=root / "ticker_resolution.json", member_names=index.name_on,
                              cik_map=index.cik_pin_on, today=AS_OF, batch_writes=True)
    clients = Clients(edgar=edgar_client, resolver=resolver,
                      classifier=DelistClassifier(edgar_client, resolver, today=AS_OF), figi=_Figi(),
                      ftd_client=_FtdClient(), midas=MidasClient(root / "midas", session=sec, user_agent=UA),
                      halts=_Halts(), payout_extractor=PayoutExtractor(edgar_client), as_of=AS_OF)
    run(index, clients, Overrides(), out_dir=out, log=lambda *_: None, sec_workers=workers)
    return sec


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _one_and_n(tmp_path, monkeypatch, workers, **universe):
    """One worker and `workers` workers, each run from its own clone of one seeded
    cache: both write the same six CSVs, byte for byte, and leave the same cache
    tree. Returns each run's request log."""
    for name, method in _REAL_EFTS.items():        # LIVE's resolver full-text searches go through the cache
        monkeypatch.setattr(TickerResolver, name, method)
    seed = tmp_path / "seed"
    _seed(seed)
    shutil.copytree(seed, tmp_path / "one")
    shutil.copytree(seed, tmp_path / "n")
    sec1 = _offline_run(tmp_path / "one", tmp_path / "out1", 1, **universe)
    secn = _offline_run(tmp_path / "n", tmp_path / "outn", workers, **universe)
    csv1 = {p.name: p.read_bytes() for p in (tmp_path / "out1").glob("*.csv")}
    csvn = {p.name: p.read_bytes() for p in (tmp_path / "outn").glob("*.csv")}
    assert len(csv1) == 6 and csv1 == csvn
    assert _tree(tmp_path / "one") == _tree(tmp_path / "n")                  # the caches each run leaves behind
    return sec1, secn


@pytest.mark.parametrize("workers", [2, 4])
def test_one_worker_and_n_give_the_same_bytes_from_the_same_starting_caches(tmp_path, monkeypatch, workers):
    sec1, secn = _one_and_n(tmp_path, monkeypatch, workers)
    main = threading.main_thread().name
    for url in STALE_URLS:
        assert (url, main) in sec1.calls and (url, main) in secn.calls, url    # refreshed by the stage itself
        assert not any(u == url and t != main for u, t in secn.calls), url     # never by a warm worker
    proxy = [t for u, t in secn.calls if u == AET_PROXY_URL]
    assert len(proxy) == 1 and proxy[0].startswith("sec-warm")      # the payout warm pass fetched it, stage 8 read it
    assert any(t.startswith("sec-warm") for _, t in secn.calls)                      # the warm pass did fetch
    rows = {d["sec_id"]: d for d in read_table("delistings", table_path(tmp_path / "out1", "delistings"))}
    assert set(rows) == {"BBG000FJLFX8", "CIK3333-COMMON"}
    assert (rows["BBG000FJLFX8"]["bucket"], rows["BBG000FJLFX8"]["last_trade_date_source"]) == ("merger", "midas")
    assert rows["CIK3333-COMMON"]["bucket"] == "exchange_transfer"
    assert "successor_unknown" in rows["CIK3333-COMMON"]["review_flags"].split(";")


@pytest.mark.parametrize("workers", [2, 4])
def test_a_universe_of_pinned_eras_never_reads_the_ticker_map_with_any_worker_count(tmp_path, monkeypatch,
                                                                                    workers):
    """No era needs SEC's ticker map, so a one-worker run never fetches it: the warm
    shadow resolvers load it only when an era needs it, never on their own."""
    sec1, secn = _one_and_n(tmp_path, monkeypatch, workers, live_cik=777)
    assert not any(u == TICKERS_URL for u, _ in sec1.calls + secn.calls)

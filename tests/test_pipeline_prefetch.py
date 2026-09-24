# tests/test_pipeline_prefetch.py
"""pipeline.run with --sec-workers: warm passes on worker threads ahead of each
SEC-heavy stage, the stage itself still sequential on the main thread, one run
date, per-stage request counts, and the resolver memo flushed even when a later
stage is refused."""
import json
import threading
from datetime import date
from types import SimpleNamespace

import pytest

import delist_detection.pipeline as pipeline
from delist_detection import edgar
from delist_detection.edgar import EdgarBlocked
from delist_detection.midas import MidasClient
from delist_detection.observations import Observation, ObservationIndex
from delist_detection.openfigi import OpenFigiBlocked
from delist_detection.pipeline import Overrides, run
from delist_detection.prefetch import Serialized
from delist_detection.ticker_resolver import TickerResolver
from tests.test_pipeline import _clients, _FtdClient, _index_clients


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
        assert classifier.resolver is not clients.resolver and isinstance(classifier.resolver, TickerResolver)
    assert len({id(m) for m, _, _ in warm_built}) == 1                 # one lock shared by every warm finder


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


def test_the_runs_own_resolver_only_ever_runs_on_the_main_thread(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    r, seen = clients.resolver, []
    real_resolve, real_fits = r.resolve, r._fits_date

    def resolve(*a, **k):
        seen.append(threading.current_thread().name)
        return real_resolve(*a, **k)

    def fits(*a, **k):
        seen.append(threading.current_thread().name)
        return real_fits(*a, **k)

    r.resolve, r._fits_date = resolve, fits        # its `_transient` flag must never be shared across threads
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, sec_workers=4)
    assert seen and set(seen) == {threading.main_thread().name}


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

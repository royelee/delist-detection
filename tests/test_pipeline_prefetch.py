# tests/test_pipeline_prefetch.py
"""pipeline.run with --sec-workers: warm passes on worker threads ahead of each
SEC-heavy stage, the stage itself still sequential on the main thread, one run
date, per-stage request counts, and the resolver memo flushed even when a later
stage is refused."""
import json
import threading
from datetime import date

import pytest

import delist_detection.pipeline as pipeline
from delist_detection import edgar
from delist_detection.edgar import EdgarBlocked
from delist_detection.observations import Observation, ObservationIndex
from delist_detection.openfigi import OpenFigiBlocked
from delist_detection.pipeline import Overrides, run
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

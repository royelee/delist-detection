import json

import pytest
import requests

from delist_detection.openfigi import OpenFigiBlocked, OpenFigiClient, resolve_api_key


class _Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    def __init__(self, *responses):
        self.responses, self.posts = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        return self.responses.pop(0)


AET = {"data": [{"figi": "BBG000FJLFX8", "compositeFIGI": "BBG000FJLFX8", "exchCode": "US", "ticker": "AET",
                 "name": "AETNA INC", "securityType": "Common Stock"}]}


def test_map_batches_caches_and_sends_key(tmp_path):
    s = _Session(_Resp(body=[AET, {"warning": "No identifier found."}]))
    c = OpenFigiClient(tmp_path, "k", session=s, sleep=lambda _: None)
    jobs = [{"idType": "TICKER", "idValue": "AET"}, {"idType": "TICKER", "idValue": "ZZZZ"}]
    assert c.map(jobs) == [AET, {"warning": "No identifier found."}]
    assert s.posts[0][0].endswith("/v3/mapping") and s.posts[0][2]["X-OPENFIGI-APIKEY"] == "k"
    assert c.map(jobs) == [AET, {"warning": "No identifier found."}]      # both answers cached
    assert len(s.posts) == 1


def test_map_splits_into_max_jobs_chunks(tmp_path):
    s = _Session(*[_Resp(body=[{"warning": "x"}] * 10), _Resp(body=[{"warning": "x"}] * 2)])
    c = OpenFigiClient(tmp_path, None, session=s, sleep=lambda _: None)
    assert c.max_jobs == 10
    c.map([{"idType": "TICKER", "idValue": f"T{i}"} for i in range(12)])
    assert [len(p[1]) for p in s.posts] == [10, 2]


def test_errors_not_cached_and_no_cache_mode(tmp_path):
    s = _Session(_Resp(body=[{"error": "Invalid idValue"}]), _Resp(body=[AET]), _Resp(body=[AET]))
    c = OpenFigiClient(tmp_path, "k", session=s, sleep=lambda _: None)
    job = [{"idType": "TICKER", "idValue": "AET"}]
    assert c.map(job) == [{"error": "Invalid idValue"}]
    assert c.map(job) == [AET]
    assert c.map(job, use_cache=False) == [AET]
    assert len(s.posts) == 3


def test_429_waits_then_succeeds_and_403_blocks(tmp_path):
    slept = []
    s = _Session(_Resp(429, headers={"retry-after": "7"}), _Resp(body=[AET]))
    c = OpenFigiClient(tmp_path, "k", session=s, sleep=slept.append)
    assert c.map([{"idType": "TICKER", "idValue": "AET"}]) == [AET]
    assert slept == [8]
    c2 = OpenFigiClient(tmp_path / "b", "bad", session=_Session(_Resp(403)), sleep=lambda _: None)
    with pytest.raises(OpenFigiBlocked):
        c2.map([{"idType": "TICKER", "idValue": "X"}])


class _Timeouts:
    def __init__(self):
        self.posts = 0

    def post(self, *a, **k):
        self.posts += 1
        raise requests.Timeout("read timed out")


def test_an_outage_is_unavailable_not_a_refusal_and_nothing_is_cached(tmp_path):
    """Code review 2026-09-25, item 5: timeouts or 5xx answers until the retries
    run out are an outage (OpenFigiUnavailable, the CLI exits 1), not a refusal
    of the key (OpenFigiBlocked, exit 2); nothing is cached either way."""
    from delist_detection.openfigi import OpenFigiUnavailable

    c = OpenFigiClient(tmp_path, "k", session=_Timeouts(), sleep=lambda _: None)
    with pytest.raises(OpenFigiUnavailable) as err:
        c.map([{"idType": "TICKER", "idValue": "AET"}])
    assert not isinstance(err.value, OpenFigiBlocked)
    assert c.session.posts == OpenFigiClient.MAX_RETRIES
    s = _Session(*[_Resp(503)] * OpenFigiClient.MAX_RETRIES)
    with pytest.raises(OpenFigiUnavailable):
        OpenFigiClient(tmp_path, "k", session=s, sleep=lambda _: None).filter("QUESTCOR", exchCode="US")
    assert list(tmp_path.iterdir()) == []


def test_paces_when_budget_is_spent(tmp_path):
    slept = []
    s = _Session(_Resp(body=[AET], headers={"ratelimit-remaining": "0", "ratelimit-reset": "12"}))
    OpenFigiClient(tmp_path, "k", session=s, sleep=slept.append).map([{"idType": "TICKER", "idValue": "AET"}])
    assert slept == [13]


def test_filter_pages_and_caches(tmp_path):
    s = _Session(_Resp(body={"data": [{"figi": "A"}], "next": "p2"}), _Resp(body={"data": [{"figi": "B"}]}))
    c = OpenFigiClient(tmp_path, "k", session=s, sleep=lambda _: None)
    assert c.filter("QUESTCOR", exchCode="US") == [{"figi": "A"}, {"figi": "B"}]
    assert s.posts[1][1]["start"] == "p2"
    assert c.filter("QUESTCOR", exchCode="US") == [{"figi": "A"}, {"figi": "B"}]
    assert len(s.posts) == 2


def test_resolve_api_key(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPEN_FIGI_API_KEY=fromfile\n")
    monkeypatch.delenv("OPEN_FIGI_API_KEY", raising=False)
    assert resolve_api_key(env) == "fromfile"
    monkeypatch.setenv("OPEN_FIGI_API_KEY", "fromenv")
    assert resolve_api_key(env) == "fromenv"
    monkeypatch.delenv("OPEN_FIGI_API_KEY")
    assert resolve_api_key(tmp_path / "missing.env") is None

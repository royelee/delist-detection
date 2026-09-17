"""EdgarClient.submissions(cik, fresh_after): a cached copy fetched before the
date is fetched again, so filings after the cache date are seen."""
import json
import os
from datetime import date, datetime

import pytest
import requests

from delist_detection.edgar import EdgarBlocked, EdgarClient

URL = "https://data.sec.gov/submissions/CIK0000000042.json"
EVENT = date(2026, 8, 20)          # LBRDA's Form 25, after a 2026-05-26 cache


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.url = status, data, URL
        self.text = json.dumps(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self, status=200, data=None):
        self.status, self.data = status, data or {"name": "Fresh Co"}
        self.headers, self.calls = {}, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return _Resp(self.status, dict(self.data))


def _client(tmp_path, cached, **session_kw):
    session = _Session(**session_kw)
    client = EdgarClient(cache_dir=tmp_path, session=session)
    cp = client._cache_path(URL)
    cp.write_text(json.dumps(cached))
    return client, session, cp


def _set_mtime(path, day):
    ts = datetime(day.year, day.month, day.day, 12).timestamp()
    os.utime(path, (ts, ts))


def test_a_copy_fetched_before_fresh_after_is_fetched_again(tmp_path):
    client, session, cp = _client(tmp_path, {"name": "Stale Co", "__fetched__": "2026-05-26"})
    assert client.submissions(42, fresh_after=EVENT)["name"] == "Fresh Co"
    assert session.calls == [URL]
    saved = json.loads(cp.read_text())
    assert saved == {"name": "Fresh Co", "__fetched__": date.today().isoformat()}
    # the rewritten copy is fresh: the next read in the same classification hits the cache
    assert client.submissions(42, fresh_after=EVENT)["name"] == "Fresh Co"
    assert len(session.calls) == 1


def test_a_fresh_copy_is_not_fetched(tmp_path):
    client, session, _ = _client(tmp_path, {"name": "Cached Co", "__fetched__": "2026-09-01"})
    assert client.submissions(42, fresh_after=EVENT)["name"] == "Cached Co"
    assert client.submissions(42)["name"] == "Cached Co"
    assert session.calls == []


def test_without_fresh_after_a_stale_copy_is_served(tmp_path):
    client, session, _ = _client(tmp_path, {"name": "Stale Co", "__fetched__": "2026-05-26"})
    assert client.submissions(42)["name"] == "Stale Co"
    assert session.calls == []


def test_an_unstamped_copy_is_dated_by_its_file_time(tmp_path):
    client, session, cp = _client(tmp_path, {"name": "Old Co"})
    _set_mtime(cp, date(2026, 9, 1))
    assert client.submissions(42, fresh_after=EVENT)["name"] == "Old Co"
    assert session.calls == []
    _set_mtime(cp, date(2026, 5, 26))
    assert client.submissions(42, fresh_after=EVENT)["name"] == "Fresh Co"
    assert session.calls == [URL]


@pytest.mark.parametrize("status", [403, 429])
def test_a_refusal_during_a_refresh_leaves_the_cached_copy(tmp_path, status):
    stale = {"name": "Stale Co", "__fetched__": "2026-05-26"}
    client, _, cp = _client(tmp_path, stale, status=status)
    with pytest.raises(EdgarBlocked):
        client.submissions(42, fresh_after=EVENT)
    assert json.loads(cp.read_text()) == stale


class _FailingSession(_Session):
    """Answers every request with a transport failure."""

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        raise requests.ConnectionError("no route to host")


def test_a_transport_failure_during_a_refresh_serves_the_cached_copy(tmp_path):
    # R2: a ticker with a usable cached copy must not become an error row.
    stale = {"name": "Stale Co", "__fetched__": "2026-05-26"}
    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session)
    cp = client._cache_path(URL)
    cp.write_text(json.dumps(stale))
    got = client.submissions(42, fresh_after=EVENT)
    assert got == {**stale, "__stale__": True}
    assert session.calls == [URL]
    assert json.loads(cp.read_text()) == stale          # the mark is never written to disk


def test_a_transport_failure_without_a_cached_copy_still_raises(tmp_path):
    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session)
    with pytest.raises(requests.RequestException):
        client.submissions(42, fresh_after=EVENT)


def test_a_refusal_during_a_refresh_still_raises_even_with_a_cached_copy(tmp_path):
    stale = {"name": "Stale Co", "__fetched__": "2026-05-26"}
    client, _, _ = _client(tmp_path, stale, status=403)
    with pytest.raises(EdgarBlocked):
        client.submissions(42, fresh_after=EVENT)


class _ServerErrorResp(_Resp):
    def raise_for_status(self):
        raise requests.HTTPError(f"{self.status_code} Server Error", response=self)


class _ServerErrorSession(_Session):
    """Answers every request with a 5xx that raise_for_status turns into HTTPError."""

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return _ServerErrorResp(503, dict(self.data))


def test_a_5xx_during_a_refresh_serves_the_cached_copy(tmp_path):
    """Deliberate: requests.HTTPError is a RequestException, so SEC returning a
    5xx during a freshness refetch is treated like any other failed refresh —
    the cached copy is served, marked stale, rather than the row erroring out."""
    stale = {"name": "Stale Co", "__fetched__": "2026-05-26"}
    session = _ServerErrorSession()
    client = EdgarClient(cache_dir=tmp_path, session=session)
    cp = client._cache_path(URL)
    cp.write_text(json.dumps(stale))
    assert client.submissions(42, fresh_after=EVENT) == {**stale, "__stale__": True}
    assert json.loads(cp.read_text()) == stale          # the 5xx never touches the cache


def test_a_5xx_without_a_cached_copy_still_raises(tmp_path):
    client = EdgarClient(cache_dir=tmp_path, session=_ServerErrorSession())
    with pytest.raises(requests.HTTPError):
        client.submissions(42, fresh_after=EVENT)

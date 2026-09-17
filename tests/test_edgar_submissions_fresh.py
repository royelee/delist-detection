"""EdgarClient.submissions(cik, fresh_after): a cached copy fetched before the
date is fetched again, so filings after the cache date are seen."""
import json
import os
from datetime import date, datetime

import pytest

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

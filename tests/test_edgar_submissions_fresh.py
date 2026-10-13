"""EdgarClient.submissions(cik, fresh_after): a cached copy fetched before the
date is fetched again, so filings after the cache date are seen."""
import json
import os
from datetime import date, datetime

import pytest
import requests

from delist_detection.sources.edgar import FILED_AFTER_RUN_DATE, EdgarBlocked, EdgarClient

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


def test_a_copy_with_no_fetch_date_is_fresh_for_no_caller_whatever_its_file_time(tmp_path):
    """FB-028: Exxon Mobil's filing list was cached in May 2026, before copies kept a fetch date. The cache was
    copied on 2026-10-02, which set every file's time to that day, and the copy counted as fetched a week after the
    run date. Its 8-K of 2026-07-01 and Form 25 of 2026-07-02 were read by no run."""
    client, session, cp = _client(tmp_path, {"name": "Old Co"})
    _set_mtime(cp, date(2026, 10, 2))                          # the file's time says nothing of the fetch
    assert client.submissions(42)["name"] == "Old Co" and session.calls == []       # no day asked: any copy
    assert client.submissions(42, fresh_after=EVENT)["name"] == "Fresh Co"
    assert session.calls == [URL]
    assert client.submissions(42, fresh_after=EVENT)["name"] == "Fresh Co" and session.calls == [URL]   # stamped now


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
    # The transport error is retried 3 times (backoff injected to stay fast)
    # before the refresh gives up and falls back to the cache.
    stale = {"name": "Stale Co", "__fetched__": "2026-05-26"}
    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    cp = client._cache_path(URL)
    cp.write_text(json.dumps(stale))
    got = client.submissions(42, fresh_after=EVENT)
    assert got == {**stale, "__stale__": True}
    assert session.calls == [URL, URL, URL]
    assert json.loads(cp.read_text()) == stale          # the mark is never written to disk


def test_a_transport_failure_without_a_cached_copy_still_raises(tmp_path):
    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    with pytest.raises(requests.RequestException):
        client.submissions(42, fresh_after=EVENT)
    assert session.calls == [URL, URL, URL]


def test_a_transport_failure_then_success_is_not_marked_stale(tmp_path):
    """The retry actually helps: a connection error on the first attempt
    followed by a 200 on the second must return the fresh answer, with no
    STALE_KEY -- not fall back to the cache at all."""
    stale = {"name": "Stale Co", "__fetched__": "2026-05-26"}

    class _FlakyThenGoodSession(_Session):
        def __init__(self):
            super().__init__()
            self.attempt = 0

        def get(self, url, headers=None, timeout=None):
            self.calls.append(url)
            self.attempt += 1
            if self.attempt == 1:
                raise requests.ConnectionError("blip")
            return _Resp(200, {"name": "Fresh Co"})

    slept = []
    session = _FlakyThenGoodSession()
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=slept.append)
    cp = client._cache_path(URL)
    cp.write_text(json.dumps(stale))
    got = client.submissions(42, fresh_after=EVENT)
    assert got == {"name": "Fresh Co", "__fetched__": date.today().isoformat()}
    assert "__stale__" not in got
    assert session.calls == [URL, URL]
    assert slept == [2]


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
    the cached copy is served, marked stale, rather than the row erroring out.
    The 5xx is retried 3 times (backoff injected to stay fast) first."""
    stale = {"name": "Stale Co", "__fetched__": "2026-05-26"}
    session = _ServerErrorSession()
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    cp = client._cache_path(URL)
    cp.write_text(json.dumps(stale))
    assert client.submissions(42, fresh_after=EVENT) == {**stale, "__stale__": True}
    assert json.loads(cp.read_text()) == stale          # the 5xx never touches the cache
    assert session.calls == [URL, URL, URL]


def test_a_5xx_without_a_cached_copy_still_raises(tmp_path):
    session = _ServerErrorSession()
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    with pytest.raises(requests.HTTPError):
        client.submissions(42, fresh_after=EVENT)
    assert session.calls == [URL, URL, URL]


def test_a_run_date_hides_the_filings_made_after_it(tmp_path):
    """An --as-of run reads the issuer as it stood on its run date: a recent filing dated after the run date is not
    seen (WBD's 2026-10 Form 25 in a run as of 2026-09-25), wherever it sits in the list, and the cached copy keeps
    every filing for a later run date."""
    recent = {"accessionNumber": ["a3", "a2", "a1"], "form": ["25-NSE", "8-K", "10-Q"],
              "filingDate": ["2026-10-06", "2026-09-25", "2026-08-05"], "items": ["", "2.01", ""]}
    cached = {"name": "X Co", "__fetched__": "2026-09-25", "filings": {"recent": recent, "files": []}}
    client = EdgarClient(cache_dir=tmp_path, session=_Session(), today=date(2026, 9, 25))
    cp = client._cache_path(URL)
    cp.write_text(json.dumps(cached))
    got = client.submissions(42)
    assert got["filings"]["recent"] == {"accessionNumber": ["a2", "a1"], "form": ["8-K", "10-Q"],
                                        "filingDate": ["2026-09-25", "2026-08-05"], "items": ["2.01", ""]}
    assert [f.accession for f in client.recent_filings(42)] == ["a2", "a1"]
    assert got[FILED_AFTER_RUN_DATE] == ["25-NSE"]          # what was left out: listed on the run date (FB-004)
    assert json.loads(cp.read_text()) == cached
    later = EdgarClient(cache_dir=tmp_path, session=_Session(), today=date(2026, 10, 10))
    assert later.submissions(42)["filings"]["recent"]["accessionNumber"] == ["a3", "a2", "a1"]
    assert FILED_AFTER_RUN_DATE not in later.submissions(42)


def test_a_run_date_hides_a_name_taken_after_it(tmp_path):
    """Matson 2026 (FB-028's runs): the list fetched on 2026-10-13 for a run as of 2026-09-25 carried a former-name
    row SEC added on 2026-10-01, "Matson, Inc." from 2012-07-03 to 2026-10-01, and the row moved the issuer's dates
    of 2012 in a contract table. A former name that outlasts the run date was the name on that day: it is the
    current name again and no former one, as a copy fetched that day held it. One taken after the day is left out.
    The cached copy keeps every name."""
    recent = {"accessionNumber": ["a2", "a1"], "form": ["8-K", "10-Q"], "filingDate": ["2026-10-01", "2026-08-05"]}
    former = [{"name": "Matson, Inc.", "from": "2012-07-03T00:00:00.000Z", "to": "2026-10-01T00:00:00.000Z"},
              {"name": "ALEXANDER & BALDWIN INC", "from": "1994-11-15T00:00:00.000Z", "to": "2012-06-25T00:00:00.000Z"}]
    cached = {"name": "MATSON, INC.", "formerNames": former, "__fetched__": "2026-09-25",
              "filings": {"recent": recent, "files": []}}
    client = EdgarClient(cache_dir=tmp_path, session=_Session(), today=date(2026, 9, 25))
    cp = client._cache_path(URL)
    cp.write_text(json.dumps(cached))
    got = client.submissions(42)
    assert got["name"] == "Matson, Inc." and got["formerNames"] == former[1:]
    assert json.loads(cp.read_text()) == cached
    later = EdgarClient(cache_dir=tmp_path, session=_Session(), today=date(2026, 10, 10))
    assert later.submissions(42)["name"] == "MATSON, INC." and later.submissions(42)["formerNames"] == former
    # a name the issuer took only after the run date: not a name yet, and the name before it still the current one
    renamed = {**cached, "name": "NEWER CO", "formerNames": [
        {"name": "NEW CO", "from": "2026-09-28T00:00:00.000Z", "to": "2026-10-01T00:00:00.000Z"},
        {"name": "OLD CO", "from": "2001-01-01T00:00:00.000Z", "to": "2026-09-27T00:00:00.000Z"}]}
    cp.write_text(json.dumps(renamed))
    got = client.submissions(42)
    assert got["name"] == "OLD CO" and got["formerNames"] == []

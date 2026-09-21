"""EdgarClient.company_search_atom caching: bounded freshness, never negative.

company_search_atom never cached anything before this fix — every call hit
the network directly, unlike submissions() which already goes through
_get_json's freshness-bounded cache. This gives it the same disk cache
(FETCHED_KEY + the stored fetch date), but never persists an empty or error
answer (that would silently and permanently stand in for a real hit once
written), and treats anything older than 7 days as stale."""
import json
import os
from datetime import date, datetime, timedelta

import requests

from delist_detection.edgar import EdgarClient, FETCHED_KEY, WWW_SEC_HOST

COMPANY = "SUNPOWER CORP"
FORM = "25-NSE"

ATOM_HIT = (
    "<feed><company-info><cik>867773</cik>"
    "<conformed-name>SUNPOWER CORP</conformed-name></company-info>"
    "<entry><filing-type>25-NSE</filing-type>"
    "<filing-date>2024-08-15</filing-date></entry></feed>"
)
ATOM_EMPTY = "<feed></feed>"

HIT = [{"cik": 867773, "name": "SUNPOWER CORP", "form": "25-NSE", "filing_date": "2024-08-15"}]


def _url(company=COMPANY, form_type=FORM):
    return (
        f"{WWW_SEC_HOST}/cgi-bin/browse-edgar?action=getcompany"
        f"&company={requests.utils.quote(company)}&type={form_type}"
        "&dateb=&owner=include&count=10&output=atom"
    )


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text, self.url = status, text, _url()


class _Session:
    def __init__(self, text=ATOM_HIT, status=200):
        self.text, self.status = text, status
        self.headers, self.calls = {}, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return _Resp(self.status, self.text)


def _client(tmp_path, **session_kw):
    session = _Session(**session_kw)
    client = EdgarClient(cache_dir=tmp_path, session=session)
    return client, session


def _set_mtime(path, day):
    ts = datetime(day.year, day.month, day.day, 12).timestamp()
    os.utime(path, (ts, ts))


def test_a_fresh_cached_answer_is_served_without_a_request(tmp_path):
    client, session = _client(tmp_path)
    cp = client._cache_path(_url())
    cp.write_text(json.dumps({"hits": HIT, FETCHED_KEY: date.today().isoformat()}))

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert hits == HIT
    assert session.calls == []


def test_a_cached_answer_older_than_7_days_triggers_a_refetch(tmp_path):
    client, session = _client(tmp_path)
    cp = client._cache_path(_url())
    stale = {"hits": [{"cik": 1, "name": "STALE CO", "form": "", "filing_date": ""}],
             FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}
    cp.write_text(json.dumps(stale))

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert session.calls == [_url()]
    assert hits == HIT
    saved = json.loads(cp.read_text())
    assert saved["hits"] == HIT
    assert saved[FETCHED_KEY] == date.today().isoformat()


def test_an_unstamped_stale_cache_is_dated_by_its_file_time(tmp_path):
    client, session = _client(tmp_path)
    cp = client._cache_path(_url())
    cp.write_text(json.dumps({"hits": [{"cik": 1, "name": "OLD CO", "form": "", "filing_date": ""}]}))
    _set_mtime(cp, date.today() - timedelta(days=8))

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert session.calls == [_url()]
    assert hits == HIT


def test_an_empty_answer_is_not_written_to_the_cache(tmp_path):
    client, session = _client(tmp_path, text=ATOM_EMPTY)
    cp = client._cache_path(_url())

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert hits == []
    assert session.calls == [_url()]
    assert not cp.exists()


def test_an_error_answer_is_not_written_to_the_cache(tmp_path):
    client, session = _client(tmp_path, status=500)
    cp = client._cache_path(_url())

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert hits == []
    assert session.calls == [_url()]
    assert not cp.exists()


def test_a_transport_failure_is_not_written_to_the_cache(tmp_path):
    class _FailingSession(_Session):
        def get(self, url, headers=None, timeout=None):
            self.calls.append(url)
            raise requests.ConnectionError("no route to host")

    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session)
    cp = client._cache_path(_url())

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert hits == []
    assert not cp.exists()


def test_an_empty_answer_does_not_overwrite_a_stale_cache_and_is_retried_next_call(tmp_path):
    """An empty refetch must not persist over a stale cached hit: the next
    call retries rather than trusting the empty answer forever."""
    client, session = _client(tmp_path, text=ATOM_EMPTY)
    cp = client._cache_path(_url())
    stale = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}
    cp.write_text(json.dumps(stale))

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert hits == []
    assert json.loads(cp.read_text()) == stale     # untouched, not clobbered with an empty answer
    assert session.calls == [_url()]

    # the next call still sees a stale cache and retries, rather than being stuck
    hits2 = client.company_search_atom(COMPANY, form_type=FORM)
    assert hits2 == []
    assert session.calls == [_url(), _url()]


def test_a_5xx_during_a_refetch_serves_the_stale_cached_hit(tmp_path):
    """Mirrors _get_json: a failed refresh must not turn a company with a
    usable cached copy into an empty result."""
    client, session = _client(tmp_path, status=503)
    cp = client._cache_path(_url())
    stale = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}
    cp.write_text(json.dumps(stale))

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert hits == HIT
    assert session.calls == [_url()]
    assert json.loads(cp.read_text()) == stale     # the 5xx never touches the cache


def test_a_transport_failure_during_a_refetch_serves_the_stale_cached_hit(tmp_path):
    class _FailingSession(_Session):
        def get(self, url, headers=None, timeout=None):
            self.calls.append(url)
            raise requests.ConnectionError("no route to host")

    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session)
    cp = client._cache_path(_url())
    stale = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}
    cp.write_text(json.dumps(stale))

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert hits == HIT
    assert json.loads(cp.read_text()) == stale


def test_a_failed_refetch_without_any_cached_copy_still_returns_empty(tmp_path):
    client, session = _client(tmp_path, status=503)
    cp = client._cache_path(_url())

    hits = client.company_search_atom(COMPANY, form_type=FORM)

    assert hits == []
    assert not cp.exists()

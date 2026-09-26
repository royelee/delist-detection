"""EdgarClient.company_search_atom caching: every answer, hits or empty, is cached
with its fetch date and trusted for 7 days; a failed request is retried, then
serves a cached hit list marked stale, and with nothing to fall back on raises --
an unanswered search is not an empty one."""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import requests

from delist_detection.edgar import FETCHED_KEY, STALE_KEY, WWW_SEC_HOST, EdgarClient
from delist_detection.sec_stats import fill_only

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

# Real EDGAR answers (captured 2026-09-24), so the "is this an ATOM feed" gate is
# exercised against SEC's actual response shapes, not a hand-written stand-in.
FIXTURES = Path(__file__).parent / "fixtures" / "company_search"
NOMATCH = (FIXTURES / "nomatch.atom").read_text()
ONEMATCH = (FIXTURES / "onematch.atom").read_text()
MULTIMATCH = (FIXTURES / "multimatch.atom").read_text()

HTML_BODY = "<html><body>Service Unavailable</body></html>"
TRUNCATED_FEED = "<feed><company-info><cik>867773</cik>"   # cut off mid-response, no </feed>


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
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
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


class _FailingSession(_Session):
    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        raise requests.ConnectionError("no route to host")


def test_an_empty_answer_is_cached_for_7_days_like_a_hit(tmp_path):
    client, session = _client(tmp_path, text=ATOM_EMPTY)
    cp = client._cache_path(_url())
    assert client.company_search_atom(COMPANY, form_type=FORM) == []
    assert json.loads(cp.read_text()) == {"hits": [], FETCHED_KEY: date.today().isoformat()}
    later, later_session = _client(tmp_path, text=ATOM_HIT)
    assert later.company_search_atom(COMPANY, form_type=FORM) == []          # within 7 days: no request
    assert later_session.calls == []
    cp.write_text(json.dumps({"hits": [], FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}))
    again, again_session = _client(tmp_path, text=ATOM_HIT)
    assert again.company_search_atom(COMPANY, form_type=FORM) == HIT        # expired: asked again
    assert again_session.calls == [_url()]


def test_an_error_answer_is_retried_then_raises_and_is_not_cached(tmp_path):
    client, session = _client(tmp_path, status=500)
    with pytest.raises(requests.HTTPError):
        client.company_search_atom(COMPANY, form_type=FORM)
    assert session.calls == [_url()] * 3
    assert not client._cache_path(_url()).exists()


def test_a_transport_failure_is_retried_then_raises(tmp_path):
    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    with pytest.raises(requests.ConnectionError):
        client.company_search_atom(COMPANY, form_type=FORM)
    assert session.calls == [_url()] * 3
    assert not client._cache_path(_url()).exists()


def test_an_empty_refetch_replaces_a_stale_hit_and_holds_for_7_days(tmp_path):
    client, session = _client(tmp_path, text=ATOM_EMPTY)
    cp = client._cache_path(_url())
    cp.write_text(json.dumps({"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}))
    assert client.company_search_atom(COMPANY, form_type=FORM) == []
    assert json.loads(cp.read_text())["hits"] == []
    assert session.calls == [_url()]


def test_a_5xx_during_a_refetch_serves_the_stale_hit_marked_stale(tmp_path):
    client, session = _client(tmp_path, status=503)
    cp = client._cache_path(_url())
    stale = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}
    cp.write_text(json.dumps(stale))
    assert client.company_search_atom(COMPANY, form_type=FORM) == [{**HIT[0], STALE_KEY: True}]
    assert session.calls == [_url()] * 3
    assert json.loads(cp.read_text()) == stale        # the failure never touches the cache


def test_a_transport_failure_during_a_refetch_serves_the_stale_hit_marked_stale(tmp_path):
    session = _FailingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    cp = client._cache_path(_url())
    stale = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}
    cp.write_text(json.dumps(stale))
    assert client.company_search_atom(COMPANY, form_type=FORM) == [{**HIT[0], STALE_KEY: True}]
    assert json.loads(cp.read_text()) == stale


def test_a_failed_refetch_of_an_expired_empty_answer_raises(tmp_path):
    client, _ = _client(tmp_path, status=503)
    client._cache_path(_url()).write_text(json.dumps(
        {"hits": [], FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}))
    with pytest.raises(requests.HTTPError):
        client.company_search_atom(COMPANY, form_type=FORM)


def test_a_failed_search_without_any_cached_copy_raises(tmp_path):
    client, _ = _client(tmp_path, status=503)
    with pytest.raises(requests.HTTPError):
        client.company_search_atom(COMPANY, form_type=FORM)
    assert not client._cache_path(_url()).exists()


def test_a_prefetch_thread_reads_an_expired_answer_without_asking_again(tmp_path):
    client, session = _client(tmp_path)
    old = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=30)).isoformat()}
    client._cache_path(_url()).write_text(json.dumps(old))
    with fill_only():
        assert client.company_search_atom(COMPANY, form_type=FORM) == HIT
    assert session.calls == [] and json.loads(client._cache_path(_url()).read_text()) == old


def test_without_the_search_cache_nothing_is_read_or_written(tmp_path):
    session = _Session()
    client = EdgarClient(cache_dir=tmp_path, session=session, search_cache=False)
    cp = client._cache_path(_url())
    cp.write_text(json.dumps({"hits": [], FETCHED_KEY: date.today().isoformat()}))
    assert client.company_search_atom(COMPANY, form_type=FORM) == HIT
    assert session.calls == [_url()] and json.loads(cp.read_text())["hits"] == []


def test_a_search_holds_its_cache_file_lock(tmp_path):
    held = []

    class _Probe(_Session):
        def get(self, url, headers=None, timeout=None):
            held.append(client._lock_for(str(client._cache_path(url))).locked())
            return super().get(url, headers, timeout)

    client = EdgarClient(cache_dir=tmp_path, session=_Probe())
    client.company_search_atom(COMPANY, form_type=FORM)
    assert held == [True]


# --- Fix round 1: a 200 that is not a real ATOM feed is a failure, not a match ---

def test_a_real_no_match_feed_parses_to_empty_and_is_cached_for_7_days(tmp_path):
    client, session = _client(tmp_path, text=NOMATCH)
    cp = client._cache_path(_url())
    assert client.company_search_atom(COMPANY, form_type=FORM) == []
    assert json.loads(cp.read_text()) == {"hits": [], FETCHED_KEY: date.today().isoformat()}


def test_a_real_one_match_feed_parses_to_one_hit(tmp_path):
    client, session = _client(tmp_path, text=ONEMATCH)
    assert client.company_search_atom(COMPANY, form_type=FORM) == [
        {"cik": 768251, "name": "ALTERA CORP", "form": "25-NSE", "filing_date": "2015-12-28"}]


def test_a_real_multi_match_feed_parses_as_it_does_today(tmp_path):
    """The multi-company feed shape (several top-level <entry title=...> blocks,
    each with its own <company-info>) is not one this parser targets -- it only
    ever reads the first <cik> anywhere in the body. This pins the current
    output; fixing multi-match parsing is not in scope for this fix round."""
    client, session = _client(tmp_path, text=MULTIMATCH)
    assert client.company_search_atom(COMPANY, form_type=FORM) == [
        {"cik": 20171, "name": None, "form": "", "filing_date": ""}]


def test_an_html_200_is_not_an_answer_and_raises_without_caching(tmp_path):
    client, session = _client(tmp_path, text=HTML_BODY)
    cp = client._cache_path(_url())
    with pytest.raises(requests.RequestException):
        client.company_search_atom(COMPANY, form_type=FORM)
    assert not cp.exists()


def test_an_html_200_over_an_expired_hit_list_serves_it_marked_stale(tmp_path):
    client, session = _client(tmp_path, text=HTML_BODY)
    cp = client._cache_path(_url())
    stale = {"hits": HIT, FETCHED_KEY: (date.today() - timedelta(days=8)).isoformat()}
    cp.write_text(json.dumps(stale))
    assert client.company_search_atom(COMPANY, form_type=FORM) == [{**HIT[0], STALE_KEY: True}]
    assert json.loads(cp.read_text()) == stale        # the bad body never touches the cache


def test_a_truncated_feed_is_not_an_answer_and_raises(tmp_path):
    client, session = _client(tmp_path, text=TRUNCATED_FEED)
    cp = client._cache_path(_url())
    with pytest.raises(requests.RequestException):
        client.company_search_atom(COMPANY, form_type=FORM)
    assert not cp.exists()


# --- Fix round 1: fill_only never touches an existing file it cannot use ---

def test_a_prefetch_thread_never_touches_an_unreadable_existing_file(tmp_path):
    client, session = _client(tmp_path)
    cp = client._cache_path(_url())
    cp.write_text("not json")
    with fill_only():
        assert client.company_search_atom(COMPANY, form_type=FORM) == []
    assert session.calls == [] and cp.read_text() == "not json"


def test_a_prefetch_thread_never_touches_a_file_with_no_hits_list(tmp_path):
    client, session = _client(tmp_path)
    cp = client._cache_path(_url())
    odd = {"no_hits_key": True, FETCHED_KEY: date.today().isoformat()}
    cp.write_text(json.dumps(odd))
    with fill_only():
        assert client.company_search_atom(COMPANY, form_type=FORM) == []
    assert session.calls == [] and json.loads(cp.read_text()) == odd


# --- Fix round 1: a 400/404 is a rejected query, not a failure (parity with EFTS) ---

@pytest.mark.parametrize("status", [400, 404])
def test_a_400_or_404_is_a_rejected_query_not_cached_not_transient(tmp_path, status):
    client, session = _client(tmp_path, status=status)
    cp = client._cache_path(_url())
    assert client.company_search_atom(COMPANY, form_type=FORM) == []
    assert session.calls == [_url()]          # a 4xx is not retried
    assert not cp.exists()

"""edgar.SEC_STATS: requests sent and answers read from cache per EDGAR
endpoint, latency, and degraded answers (a stale copy served, a request that
failed), counted across threads and, for degraded answers, on the calling
thread alone."""
import json
import threading
from datetime import date

import pytest
import requests

from delist_detection import sec_http
from delist_detection.edgar import SEC_STATS, STALE_KEY, EdgarClient, FETCHED_KEY, _endpoint, fill_only

UA = "Test Co test@example.com"
SUB_URL = "https://data.sec.gov/submissions/CIK0000000042.json"


class _Resp:
    def __init__(self, status=200, text='{"name": "Co"}', content=b"zip"):
        self.status_code, self.text, self.content, self.url = status, text, content, "u"

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    def __init__(self, status=200):
        self.status = status

    def get(self, url, headers=None, timeout=None):
        return _Resp(self.status)


def _client(tmp_path, status=200):
    return EdgarClient(cache_dir=tmp_path, user_agent=UA, session=_Session(status), sleep=lambda _: None,
                       today=date(2026, 9, 23))


@pytest.mark.parametrize("url, endpoint", [
    ("https://efts.sec.gov/LATEST/search-index?q=%22X%22", "full_text_search"),
    ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=X", "company_search"),
    ("https://data.sec.gov/submissions/CIK0000000042.json", "submissions"),
    ("https://data.sec.gov/submissions/CIK0000000042-submissions-001.json", "submissions_page"),
    ("https://www.sec.gov/Archives/edgar/data/42/000000004224000001/a.htm", "archives"),
    ("https://www.sec.gov/files/company_tickers.json", "company_tickers"),
    ("https://www.sec.gov/files/data/fails-deliver-data/cnsfails202401a.zip", "sec_data"),
])
def test_each_url_is_counted_under_its_endpoint(url, endpoint):
    assert _endpoint(url) == endpoint


def test_requests_and_cache_answers_are_counted_per_endpoint(tmp_path):
    client = _client(tmp_path)
    mark = SEC_STATS.snapshot()
    client.submissions(42)
    client.submissions(42)
    client.fetch_filing_raw(42, "0000000042-24-000002")
    client.fetch_filing_raw(42, "0000000042-24-000002")
    counts, timings = SEC_STATS.since(mark)
    assert counts == {"cache:archives": 1, "cache:submissions": 1,
                      "request:archives": 1, "request:submissions": 1}
    assert sorted(timings) == ["archives", "submissions"]
    assert all(len(v) == 1 and v[0] >= 0 for v in timings.values())


def test_a_stale_copy_counts_as_degraded_on_the_calling_thread_only(tmp_path):
    client = _client(tmp_path, status=503)
    client._cache_path(SUB_URL).write_text(json.dumps({"name": "Co", FETCHED_KEY: "2026-01-01"}))
    mark, mine = SEC_STATS.snapshot(), SEC_STATS.thread_degraded()
    assert client.submissions(42, fresh_after=date(2026, 9, 1))[STALE_KEY] is True
    other = []
    t = threading.Thread(target=lambda: other.append(SEC_STATS.thread_degraded()))
    t.start()
    t.join(5)
    assert SEC_STATS.since(mark)[0]["degraded:stale_copy"] == 1
    assert SEC_STATS.thread_degraded() == mine + 1 and other == [0]


def test_a_failed_filing_text_request_counts_as_degraded(tmp_path):
    client = _client(tmp_path, status=500)
    mark = SEC_STATS.snapshot()
    assert client.fetch_filing_text(42, "0000000042-24-000001", "a.htm") == ""
    assert SEC_STATS.since(mark)[0]["degraded:failed_request"] == 1


def test_a_degraded_read_on_a_fill_only_thread_counts_as_warm_degraded(tmp_path):
    # item 5: a warm thread's degraded read must not be counted with the
    # sequential pass's own -- run_manifest.json's degraded_answers should
    # reflect only what the sequential pass relied on.
    client = _client(tmp_path, status=503)
    mark = SEC_STATS.snapshot()
    with fill_only():
        assert client.fetch_filing_text(42, "0000000042-24-000001", "a.htm") == ""
    counts, _ = SEC_STATS.since(mark)
    assert counts.get("warm_degraded:failed_request") == 1
    assert "degraded:failed_request" not in counts


def test_a_degraded_read_off_a_fill_only_thread_still_counts_as_degraded(tmp_path):
    client = _client(tmp_path, status=503)
    mark = SEC_STATS.snapshot()
    assert client.fetch_filing_text(42, "0000000042-24-000001", "a.htm") == ""
    counts, _ = SEC_STATS.since(mark)
    assert counts.get("degraded:failed_request") == 1
    assert "warm_degraded:failed_request" not in counts


def test_a_sec_data_download_is_counted(tmp_path):
    mark = SEC_STATS.snapshot()
    sec_http.download("https://www.sec.gov/f.zip", tmp_path / "f.zip", session=_Session(), user_agent=UA)
    assert SEC_STATS.since(mark)[0] == {"request:sec_data": 1}

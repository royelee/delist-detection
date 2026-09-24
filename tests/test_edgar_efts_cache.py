"""EdgarClient.efts_search: every full-text-search answer, hits or empty, is cached
with its fetch date and holds for efts_ttl_days (the gap from its window's end to
the fetch, kept within [7, 365] days). A window ending before 2001 is never sent,
a 400/404 is a non-answer, and a failure raises and is never cached."""
import json
import logging
from datetime import date, timedelta

import pytest
import requests

from delist_detection.edgar import (EFTS_KEY, EFTS_SCHEMA, FETCHED_KEY, SEC_STATS, EdgarBlocked, EdgarClient,
                                    efts_ttl_days, fill_only)

AS_OF = date(2026, 9, 23)
UA = "Test Co test@example.com"
URL = ("https://efts.sec.gov/LATEST/search-index?q=%22X%22&forms=8-K"
       "&dateRange=custom&startdt=2020-01-01&enddt=2020-02-01")
END = date(2020, 2, 1)
HIT = {"_id": "0000000001-20-000001:x.htm",
       "_source": {"ciks": ["0000000001"], "display_names": ["X CO  (X)  (CIK 0000000001)"],
                   "file_date": "2020-01-15"}}


class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code, self.text, self.url = status, text, URL

    def json(self):
        return json.loads(self.text)


def _answer(*hits):
    return _Resp(text=json.dumps({"hits": {"total": {"value": len(hits)}, "hits": list(hits)}}))


class _Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _client(tmp_path, *responses, today=AS_OF, **kw):
    s = _Session(*responses)
    return EdgarClient(cache_dir=tmp_path, user_agent=UA, session=s, sleep=lambda _: None, today=today, **kw), s


def _saved(client):
    return json.loads(client._cache_path(URL).read_text())


@pytest.mark.parametrize("window_end, days", [
    (date(2020, 2, 1), 365),      # fetched years after its window closed
    (date(2026, 6, 1), 114),      # fetched 114 days after
    (date(2026, 9, 20), 7),       # just closed: the floor
    (date(2026, 12, 1), 7),       # still open: the floor
])
def test_the_ttl_scales_with_how_long_after_the_window_the_answer_was_fetched(window_end, days):
    assert efts_ttl_days(window_end, AS_OF) == days


def test_hits_are_cached_with_their_schema_fetch_date_and_window(tmp_path):
    c, s = _client(tmp_path, _answer(HIT))
    assert c.efts_search(URL, window_end=END) == [HIT]
    assert _saved(c) == {"schema": EFTS_SCHEMA, "window_end": "2020-02-01", FETCHED_KEY: "2026-09-23",
                         EFTS_KEY: [HIT]}
    assert s.calls[0][1]["Host"] == "efts.sec.gov" and s.calls[0][1]["User-Agent"] == UA
    later, s2 = _client(tmp_path)
    assert later.efts_search(URL, window_end=END) == [HIT] and s2.calls == []


def test_an_empty_answer_is_cached_like_a_hit(tmp_path):
    c, _ = _client(tmp_path, _answer())
    assert c.efts_search(URL, window_end=END) == []
    assert _saved(c)[EFTS_KEY] == []
    later, s2 = _client(tmp_path)
    assert later.efts_search(URL, window_end=END) == [] and s2.calls == []


def test_an_answer_is_asked_again_once_its_ttl_has_run_out(tmp_path):
    end = date(2026, 8, 30)
    c, _ = _client(tmp_path, _answer(), today=date(2026, 9, 1))      # 2 days after the window: the 7-day floor
    assert c.efts_search(URL, window_end=end) == []
    inside, s1 = _client(tmp_path, today=date(2026, 9, 7))
    assert inside.efts_search(URL, window_end=end) == [] and s1.calls == []
    after, s2 = _client(tmp_path, _answer(HIT), today=date(2026, 9, 8))
    assert after.efts_search(URL, window_end=end) == [HIT] and len(s2.calls) == 1
    assert _saved(after)[FETCHED_KEY] == "2026-09-08"


def test_a_window_still_open_is_cached_for_the_floor_only(tmp_path):
    open_end = AS_OF + timedelta(days=30)
    c, _ = _client(tmp_path, _answer(HIT))
    assert c.efts_search(URL, window_end=open_end) == [HIT]
    later, s = _client(tmp_path, _answer(HIT), today=AS_OF + timedelta(days=7))
    assert later.efts_search(URL, window_end=open_end) == [HIT] and len(s.calls) == 1


def test_a_prefetch_thread_reads_an_expired_answer_without_asking_again(tmp_path):
    c, _ = _client(tmp_path, _answer(), today=date(2026, 9, 1))
    assert c.efts_search(URL, window_end=date(2026, 8, 30)) == []
    later, s = _client(tmp_path, today=date(2026, 9, 30))              # expired
    with fill_only():
        assert later.efts_search(URL, window_end=date(2026, 8, 30)) == []
    assert s.calls == [] and _saved(later)[FETCHED_KEY] == "2026-09-01"


def test_a_window_before_2001_is_not_covered_and_never_sent(tmp_path):
    c, s = _client(tmp_path)
    mark = SEC_STATS.snapshot()
    assert c.efts_search(URL, window_end=date(2000, 12, 31)) == []
    assert s.calls == [] and not c._cache_path(URL).exists()
    assert SEC_STATS.since(mark)[0] == {"not_covered:full_text_search": 1}


def test_an_undated_search_is_kept_for_the_run_only(tmp_path):
    c, s = _client(tmp_path, _answer(HIT))
    assert c.efts_search(URL, window_end=None) == [HIT]
    assert c.efts_search(URL, window_end=None) == [HIT]
    assert len(s.calls) == 1 and not c._cache_path(URL).exists()
    later, s2 = _client(tmp_path, _answer(HIT))
    assert later.efts_search(URL, window_end=None) == [HIT] and len(s2.calls) == 1


@pytest.mark.parametrize("status", [400, 404])
def test_a_rejected_query_is_a_non_answer_logged_and_never_written(tmp_path, caplog, status):
    c, s = _client(tmp_path, _Resp(status))
    mark = SEC_STATS.snapshot()
    with caplog.at_level(logging.WARNING, logger="delist_detection.edgar"):
        assert c.efts_search(URL, window_end=END) == []
    assert c.efts_search(URL, window_end=END) == []                  # asked once per run
    assert len(s.calls) == 1 and not c._cache_path(URL).exists()
    assert str(status) in caplog.text and URL in caplog.text
    counts = SEC_STATS.since(mark)[0]
    assert counts["rejected:full_text_search"] == 1
    assert not any(k.startswith("degraded:") for k in counts)        # not transient: nothing failed


def test_a_failed_search_raises_is_never_cached_and_is_asked_again(tmp_path):
    c, s = _client(tmp_path, _Resp(500), _Resp(500), _Resp(500), _answer(HIT))
    with pytest.raises(requests.HTTPError):
        c.efts_search(URL, window_end=END)
    assert not c._cache_path(URL).exists()
    assert c.efts_search(URL, window_end=END) == [HIT]               # not remembered as empty
    assert len(s.calls) == 4


def test_a_transport_failure_raises(tmp_path):
    down = requests.ConnectionError("down")
    c, _ = _client(tmp_path, down, down, down)
    with pytest.raises(requests.ConnectionError):
        c.efts_search(URL, window_end=END)
    assert not c._cache_path(URL).exists()


def test_a_body_that_is_not_json_raises(tmp_path):
    c, _ = _client(tmp_path, _Resp(text="<html>maintenance</html>"))
    with pytest.raises(requests.RequestException):
        c.efts_search(URL, window_end=END)
    assert not c._cache_path(URL).exists()


@pytest.mark.parametrize("status", [403, 429])
def test_a_refusal_raises_edgar_blocked_and_writes_nothing(tmp_path, status):
    c, s = _client(tmp_path, _Resp(status))
    with pytest.raises(EdgarBlocked):
        c.efts_search(URL, window_end=END)
    assert len(s.calls) == 1 and not c._cache_path(URL).exists()


def test_hits_keep_their_id_and_only_the_fields_the_library_reads(tmp_path):
    wide = {"_id": "a:b", "_score": 3.1, "_source": {**HIT["_source"], "form": "8-K",
                                                     "adsh": "0000000001-20-000001",
                                                     "biz_locations": ["Boston, MA"], "sics": ["1311"]}}
    c, _ = _client(tmp_path, _answer(wide))
    assert c.efts_search(URL, window_end=END) == [{"_id": "a:b", "_source": {
        "ciks": ["0000000001"], "display_names": ["X CO  (X)  (CIK 0000000001)"], "form": "8-K",
        "file_date": "2020-01-15", "adsh": "0000000001-20-000001"}}]


def test_a_file_of_another_schema_is_asked_again_and_replaced(tmp_path):
    c, s = _client(tmp_path, _answer(HIT))
    c._cache_path(URL).write_text(json.dumps([{"_source": {"ciks": ["9"]}}]))   # the old full_text_search's bare list
    assert c.efts_search(URL, window_end=END) == [HIT]
    assert len(s.calls) == 1 and _saved(c)["schema"] == EFTS_SCHEMA


def test_without_the_search_cache_every_search_is_sent_and_nothing_written(tmp_path):
    c, s = _client(tmp_path, _answer(HIT), _answer(HIT), search_cache=False)
    kept = {"schema": EFTS_SCHEMA, "window_end": "2020-02-01", FETCHED_KEY: "2026-09-23", EFTS_KEY: []}
    c._cache_path(URL).write_text(json.dumps(kept))
    assert c.efts_search(URL, window_end=END) == [HIT]
    assert c.efts_search(URL, window_end=END) == [HIT]
    assert len(s.calls) == 2 and _saved(c) == kept


def test_a_search_holds_its_cache_file_lock(tmp_path):
    held = []

    class _Probe(_Session):
        def get(self, url, headers=None, timeout=None):
            held.append(c._lock_for(str(c._cache_path(url))).locked())
            return super().get(url, headers, timeout)

    c = EdgarClient(cache_dir=tmp_path, user_agent=UA, session=_Probe(_answer(HIT)), today=AS_OF)
    c.efts_search(URL, window_end=END)
    assert held == [True]

import json
import os
import time
from datetime import date, timedelta

import pytest
import requests

from delist_detection import sec_http
from delist_detection.edgar import EdgarBlocked, EdgarClient


class _Resp:
    def __init__(self, status=200, text="", content=b"", url="u"):
        self.status_code, self.text, self.content, self.url = status, text, content, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return json.loads(self.text)


class _Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.headers = {}

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(sec_http, "_throttle", lambda: None)


def test_download_caches(tmp_path):
    s = _Session(_Resp(content=b"zipbytes"))
    p = sec_http.download("https://www.sec.gov/f.zip", tmp_path / "f.zip", session=s, user_agent="ua")
    assert p.read_bytes() == b"zipbytes"
    sec_http.download("https://www.sec.gov/f.zip", tmp_path / "f.zip", session=s, user_agent="ua")
    assert len(s.calls) == 1


def test_download_404_and_block(tmp_path):
    with pytest.raises(FileNotFoundError):
        sec_http.download("u", tmp_path / "a.zip", session=_Session(_Resp(404)), user_agent="ua")
    with pytest.raises(EdgarBlocked):
        sec_http.download("u", tmp_path / "b.zip", session=_Session(_Resp(429)), user_agent="ua")
    assert not (tmp_path / "a.zip").exists() and not (tmp_path / "b.zip").exists()


def test_get_text_refreshes_and_falls_back(tmp_path):
    cf = tmp_path / "index.html"
    s = _Session(_Resp(text="v1"))
    assert sec_http.get_text("u", cf, session=s, user_agent="ua") == "v1"
    assert sec_http.get_text("u", cf, session=s, user_agent="ua") == "v1"      # fresh cache
    assert len(s.calls) == 1
    old = time.time() - 10 * 86400
    os.utime(cf, (old, old))
    # A persistent connection error is retried 3 times before falling back.
    s2 = _Session(requests.ConnectionError("down"), requests.ConnectionError("down"),
                  requests.ConnectionError("down"))
    assert sec_http.get_text("u", cf, session=s2, user_agent="ua", sleep=lambda _: None) == "v1"  # stale served
    assert len(s2.calls) == 3
    s3 = _Session(requests.ConnectionError("x"), requests.ConnectionError("x"), requests.ConnectionError("x"))
    with pytest.raises(requests.ConnectionError):
        sec_http.get_text("u", tmp_path / "none.html", session=s3, user_agent="ua", sleep=lambda _: None)


def test_get_text_retries_5xx_then_succeeds(tmp_path):
    cf = tmp_path / "index2.html"
    slept = []
    s = _Session(_Resp(503), _Resp(text="v2"))
    assert sec_http.get_text("u", cf, session=s, user_agent="ua", sleep=slept.append) == "v2"
    assert len(s.calls) == 2
    assert slept == [2]


def test_get_text_429_raises_at_once(tmp_path):
    cf = tmp_path / "index3.html"
    s = _Session(_Resp(429))
    with pytest.raises(EdgarBlocked):
        sec_http.get_text("u", cf, session=s, user_agent="ua", sleep=lambda _: None)
    assert len(s.calls) == 1
    assert not cf.exists()


def test_download_retries_503_then_succeeds(tmp_path):
    slept = []
    s = _Session(_Resp(503), _Resp(content=b"zipbytes"))
    p = sec_http.download("https://www.sec.gov/g.zip", tmp_path / "g.zip", session=s, user_agent="ua",
                          sleep=slept.append)
    assert p.read_bytes() == b"zipbytes"
    assert len(s.calls) == 2
    assert slept == [2]


def test_download_three_503s_fails_without_caching(tmp_path):
    s = _Session(_Resp(503), _Resp(503), _Resp(503))
    dest = tmp_path / "h.zip"
    with pytest.raises(requests.HTTPError):
        sec_http.download("https://www.sec.gov/h.zip", dest, session=s, user_agent="ua", sleep=lambda _: None)
    assert len(s.calls) == 3
    assert not dest.exists()


def test_download_429_raises_at_once_no_retry(tmp_path):
    s = _Session(_Resp(429))
    with pytest.raises(EdgarBlocked):
        sec_http.download("u", tmp_path / "i.zip", session=s, user_agent="ua", sleep=lambda _: None)
    assert len(s.calls) == 1


def test_fetch_filing_raw(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    s = _Session(_Resp(text="<TYPE>25-NSE\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>"),
                 _Resp(404))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s)
    raw = ec.fetch_filing_raw(1122304, "0000876661-18-001269")
    assert "Common Stock" in raw
    assert s.calls[0].endswith("/Archives/edgar/data/1122304/000087666118001269/0000876661-18-001269.txt")
    assert ec.fetch_filing_raw(1122304, "0000876661-18-001269") == raw          # cached
    assert ec.fetch_filing_raw(1, "0000000000-00-000001") == ""                 # 404, cached empty
    assert ec.fetch_filing_raw(1, "0000000000-00-000001") == ""
    assert len(s.calls) == 2


def test_fetch_filing_raw_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=_Session(_Resp(403)))
    with pytest.raises(EdgarBlocked):
        ec.fetch_filing_raw(1, "0000000000-00-000002")


def test_fetch_filing_raw_retries_503_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    slept = []
    s = _Session(_Resp(503), _Resp(text="hello"))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s, sleep=slept.append)
    assert ec.fetch_filing_raw(1, "0000000000-00-000003") == "hello"
    assert len(s.calls) == 2
    assert slept == [2]


def test_fetch_filing_raw_three_503s_returns_empty_without_caching(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    s = _Session(_Resp(503), _Resp(503), _Resp(503))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s, sleep=lambda _: None)
    assert ec.fetch_filing_raw(1, "0000000000-00-000004") == ""
    assert len(s.calls) == 3
    assert not list((tmp_path / "raw").glob("*.txt"))


def test_full_text_search_parses_hits(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    hit = {"_source": {"ciks": ["0001652044"], "display_names": ["Alphabet Inc.  (GOOGL, GOOG)  (CIK 0001652044)"]}}
    s = _Session(_Resp(text=json.dumps({"hits": {"hits": [hit]}})))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s)
    got = ec.full_text_search('"GOOGLE INC"', "8-K12B,8-K12G3", date(2015, 9, 2), date(2015, 12, 1))
    assert got == [hit]
    assert "efts.sec.gov" in s.calls[0]
    assert "startdt=2015-09-02" in s.calls[0] and "enddt=2015-12-01" in s.calls[0]


def test_full_text_search_caches_a_successful_answer(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    hit = {"_source": {"ciks": ["1"], "display_names": ["X CO  (X)  (CIK 0000000001)"]}}
    s = _Session(_Resp(text=json.dumps({"hits": {"hits": [hit]}})))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s)
    first = ec.full_text_search('"X CO"', "8-K12B", date(2020, 1, 1), date(2020, 2, 1))
    second = ec.full_text_search('"X CO"', "8-K12B", date(2020, 1, 1), date(2020, 2, 1))
    assert first == second == [hit]
    assert len(s.calls) == 1                       # the second call reads the cache, no request made


@pytest.mark.parametrize("status", [403, 429])
def test_full_text_search_blocked(tmp_path, monkeypatch, status):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=_Session(_Resp(status)))
    with pytest.raises(EdgarBlocked):
        ec.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1))


def test_full_text_search_500_returns_empty_and_is_not_cached(tmp_path, monkeypatch):
    # A 5xx is retried up to 3 attempts; all three fail here, so the result is
    # still empty and never cached, but the session must have been asked 3 times.
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    s = _Session(_Resp(500), _Resp(500), _Resp(500))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s, sleep=lambda _: None)
    assert ec.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1)) == []
    assert not list(tmp_path.glob("*.json"))        # an error answer is never cached
    assert len(s.calls) == 3


def test_full_text_search_network_error_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    s = _Session(requests.ConnectionError("down"), requests.ConnectionError("down"),
                 requests.ConnectionError("down"))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s, sleep=lambda _: None)
    assert ec.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1)) == []
    assert not list(tmp_path.glob("*.json"))
    assert len(s.calls) == 3


def test_full_text_search_retries_503_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    hit = {"_source": {"ciks": ["1"], "display_names": ["X CO  (X)  (CIK 0000000001)"]}}
    slept = []
    s = _Session(_Resp(503), _Resp(text=json.dumps({"hits": {"hits": [hit]}})))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s, sleep=slept.append)
    got = ec.full_text_search('"X CO"', "8-K12B", date(2020, 1, 1), date(2020, 2, 1))
    assert got == [hit]
    assert len(s.calls) == 2
    assert slept == [2]                             # one backoff between the two attempts


def test_full_text_search_429_raises_at_once_no_retry(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    s = _Session(_Resp(429))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s, sleep=lambda _: None)
    with pytest.raises(EdgarBlocked):
        ec.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1))
    assert len(s.calls) == 1                        # not retried


def test_full_text_search_caches_an_empty_answer(tmp_path, monkeypatch):
    # An empty answer is written like a hit, with its fetch date; it holds for its TTL.
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    s = _Session(_Resp(text=json.dumps({"hits": {"hits": []}})))
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s)
    assert ec.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1)) == []
    (saved,) = tmp_path.glob("*.json")
    assert json.loads(saved.read_text())["efts_hits"] == []
    s2 = _Session()
    later = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s2)
    assert later.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1)) == []
    assert s2.calls == []


def test_full_text_search_holds_an_open_windows_answer_for_seven_days_only(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    hit = {"_source": {"ciks": ["1"], "display_names": ["X CO  (X)  (CIK 0000000001)"]}}
    today = date.today()
    lo = today - timedelta(days=30)
    s = _Session(_Resp(text=json.dumps({"hits": {"hits": [hit]}})))
    assert EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s, today=today).full_text_search(
        '"X CO"', "8-K12B", lo, today) == [hit]
    s2 = _Session()
    assert EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s2,
                       today=today + timedelta(days=6)).full_text_search('"X CO"', "8-K12B", lo, today) == [hit]
    assert s2.calls == []
    s3 = _Session(_Resp(text=json.dumps({"hits": {"hits": []}})))
    assert EdgarClient(cache_dir=tmp_path, user_agent="ua", session=s3,
                       today=today + timedelta(days=7)).full_text_search('"X CO"', "8-K12B", lo, today) == []
    assert len(s3.calls) == 1

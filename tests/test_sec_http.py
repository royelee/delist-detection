import json
import os
import time
from datetime import date

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
    s2 = _Session(requests.ConnectionError("down"))
    assert sec_http.get_text("u", cf, session=s2, user_agent="ua") == "v1"     # stale cache served
    with pytest.raises(requests.ConnectionError):
        sec_http.get_text("u", tmp_path / "none.html", session=_Session(requests.ConnectionError("x")),
                          user_agent="ua")


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
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=_Session(_Resp(500)))
    assert ec.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1)) == []
    assert not list(tmp_path.glob("*.json"))        # an error answer is never cached


def test_full_text_search_network_error_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("delist_detection.edgar._throttle", lambda: None)
    ec = EdgarClient(cache_dir=tmp_path, user_agent="ua", session=_Session(requests.ConnectionError("down")))
    assert ec.full_text_search("X", "8-K12B", date(2020, 1, 1), date(2020, 2, 1)) == []
    assert not list(tmp_path.glob("*.json"))

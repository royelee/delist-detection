"""The resolver's two EDGAR full-text searches go through EdgarClient.efts_search:
the shared rate limit and User-Agent, and the cache."""
import json
import re
from datetime import date

import pytest
import requests

from delist_detection.edgar import EdgarClient
from delist_detection.ticker_resolver import TickerResolver

# Read at import, before conftest's autouse fixture stubs them for each test.
_REAL = {name: getattr(TickerResolver, name) for name in ("_efts_lookup", "_efts_pre_delist_frequency_ranked")}
AS_OF = date(2026, 9, 23)
UA = "Test Co test@example.com"
NAME = "Bad Co.  (NOPE)  (CIK 0000999001)"
HIT = {"_source": {"ciks": ["0000999001"], "display_names": [NAME]}}


class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code, self.text, self.url = status, text, "u"

    def json(self):
        return json.loads(self.text)


class _Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return self.responses.pop(0)


def _answer(*hits):
    return _Resp(text=json.dumps({"hits": {"hits": list(hits)}}))


def _client(tmp_path, session):
    return EdgarClient(cache_dir=tmp_path, user_agent=UA, session=session, sleep=lambda _: None, today=AS_OF)


@pytest.fixture(autouse=True)
def _real_efts_and_no_network(monkeypatch):
    """The real EFTS methods, and a resolver that must never call requests.get itself
    (it did before this change)."""
    for name, method in _REAL.items():
        monkeypatch.setattr(TickerResolver, name, method)

    def refuse(*a, **k):
        raise AssertionError("network: the resolver must ask through its EdgarClient")

    monkeypatch.setattr(requests, "get", refuse)


def test_the_form25_search_goes_through_the_client_and_its_cache(tmp_path):
    s = _Session(_answer(HIT))
    r = TickerResolver(_client(tmp_path, s))
    assert r._efts_lookup("NOPE", "2020-01-02") == (999001, NAME, False)
    assert "startdt=2019-10-04" in s.calls[0] and "enddt=2020-04-01" in s.calls[0]
    assert r._transient is False
    later = TickerResolver(_client(tmp_path, _Session()))                       # a later run
    assert later._efts_lookup("NOPE", "2020-01-02") == (999001, NAME, False)   # read from disk


def test_the_frequency_search_goes_through_the_client_and_its_cache(tmp_path):
    s = _Session(_answer(HIT, HIT))
    r = TickerResolver(_client(tmp_path, s))
    assert r._efts_pre_delist_frequency_ranked("NOPE", "2020-01-02") == [(999001, NAME)]
    assert "startdt=2019-09-04" in s.calls[0] and "enddt=2020-01-01" in s.calls[0]
    later = TickerResolver(_client(tmp_path, _Session()))
    assert later._efts_pre_delist_frequency_ranked("NOPE", "2020-01-02") == [(999001, NAME)]


def test_a_search_edgar_could_not_answer_marks_the_resolve_transient(tmp_path):
    s = _Session(_Resp(503), _Resp(503), _Resp(503))
    r = TickerResolver(_client(tmp_path, s))
    assert r._efts_lookup("NOPE", "2020-01-02") == (None, None, False)
    assert r._transient is True
    assert not list(tmp_path.glob("*.json"))


def test_a_rejected_search_is_not_transient(tmp_path):
    r = TickerResolver(_client(tmp_path, _Session(_Resp(400))))
    assert r._efts_lookup("NOPE", "2020-01-02") == (None, None, False)
    assert r._transient is False


def test_a_search_without_a_date_is_never_written(tmp_path):
    r = TickerResolver(_client(tmp_path, _Session(_answer(HIT))))
    assert r._efts_lookup("NOPE")[0] == 999001
    assert not list(tmp_path.glob("*.json"))


def test_a_window_before_2001_is_never_sent(tmp_path):
    s = _Session()
    r = TickerResolver(_client(tmp_path, s))
    assert r._efts_lookup("NOPE", "1999-06-01") == (None, None, False)
    assert r._efts_pre_delist_frequency_ranked("NOPE", "1999-06-01") == []
    assert s.calls == []


def test_the_query_window_end_is_exactly_its_enddt(tmp_path, monkeypatch):
    """efts_search's TTL is computed from window_end, so each call must pass the
    same date its own query's enddt asks for -- not just some date near it."""
    seen: list[tuple[str, date | None]] = []
    real = EdgarClient.efts_search

    def spy(self, url, *, window_end):
        seen.append((url, window_end))
        return real(self, url, window_end=window_end)

    monkeypatch.setattr(EdgarClient, "efts_search", spy)

    s = _Session(_answer(HIT), _answer(HIT, HIT))
    r = TickerResolver(_client(tmp_path, s))
    r._efts_lookup("NOPE", "2020-01-02")
    r._efts_pre_delist_frequency_ranked("NOPE", "2020-01-02")

    assert len(seen) == 2
    for url, window_end in seen:
        m = re.search(r"enddt=(\d{4}-\d{2}-\d{2})", url)
        assert m is not None, url
        assert window_end == date.fromisoformat(m.group(1))

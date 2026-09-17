import json

import pytest

from delist_detection.edgar import EdgarBlocked, EdgarClient
from delist_detection.ticker_resolver import TickerResolver


class _Resp:
    def __init__(self, status, text="blocked"):
        self.status_code, self.text, self.url = status, text, "https://data.sec.gov/x"
    def json(self):
        return json.loads(self.text)
    def raise_for_status(self):
        raise AssertionError("must not be reached for 403/429")


class _Session:
    def __init__(self, status):
        self.status, self.headers = status, {}
    def get(self, *a, **kw):
        return _Resp(self.status)


@pytest.mark.parametrize("status", [403, 429])
def test_get_json_raises_on_refusal(tmp_path, status):
    c = EdgarClient(cache_dir=tmp_path, session=_Session(status))
    with pytest.raises(EdgarBlocked):
        c.submissions(320193)
    assert not list(tmp_path.glob("*.json")), "a refusal must not be cached"


def test_company_search_and_text_raise_on_refusal(tmp_path):
    c = EdgarClient(cache_dir=tmp_path, session=_Session(403))
    with pytest.raises(EdgarBlocked):
        c.company_search_atom("APPLE")
    with pytest.raises(EdgarBlocked):
        c.fetch_filing_text(320193, "0000320193-24-000001", "a.htm")


def test_resolver_propagates_refusal_and_caches_nothing(tmp_path, fake_edgar, monkeypatch):
    def boom(self, *a, **kw):
        raise EdgarBlocked("403")
    monkeypatch.setattr(TickerResolver, "_efts_lookup", boom)
    cache = tmp_path / "res.json"
    r = TickerResolver(fake_edgar, cache_path=cache)
    with pytest.raises(EdgarBlocked):
        r.resolve("NOPE", "2024-01-01")
    assert not cache.exists() or "NOPE" not in cache.read_text()


def test_resolver_does_not_persist_a_miss(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"      # the autouse no-network fixture makes both EFTS tiers empty
    r = TickerResolver(fake_edgar, cache_path=cache)
    assert r.resolve("NOPE", "2024-01-01").cik is None
    assert not cache.exists() or "NOPE|2024-01-01" not in cache.read_text()


def test_resolver_retries_a_cached_miss(tmp_path, fake_edgar, monkeypatch):
    """A miss persisted by an older run must not be trusted: __init__ skips
    loading cache entries with cik=None, so resolve() retries them."""
    cache = tmp_path / "res.json"
    cache.write_text(json.dumps({
        "NOPE|2024-01-01": {"ticker": "NOPE", "cik": None, "name": None, "source": "none"},
    }))
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                         lambda self, t, d=None, **kw: (999001, "Bad Co. (NOPE)"))
    monkeypatch.setattr(TickerResolver, "_validate_cik", lambda self, *a, **kw: True)
    r = TickerResolver(fake_edgar, cache_path=cache)
    assert r.resolve("NOPE", "2024-01-01").cik == 999001

import json

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarBlocked, EdgarClient, EdgarSubmission
from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor
from delist_detection.payout_extractor import PayoutExtractor
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
                         lambda self, t, d=None, **kw: (999001, "Bad Co. (NOPE)", False))
    monkeypatch.setattr(TickerResolver, "_validate_cik", lambda self, *a, **kw: True)
    r = TickerResolver(fake_edgar, cache_path=cache)
    assert r.resolve("NOPE", "2024-01-01").cik == 999001


class _FakeEdgarMergerBlocked:
    """A merger closing 8-K exists (so extraction reaches the text fetch),
    but fetching its text hits a live SEC refusal."""

    def __init__(self, filing):
        self._filing = filing

    def recent_filings(self, cik):
        return [self._filing]

    def fetch_filing_text(self, cik, accession, primary_doc):
        raise EdgarBlocked("403")


def _merger_closing_8k(accession="C1"):
    return EdgarSubmission(
        accession=accession, form="8-K", filing_date="2018-11-30",
        report_date="2018-11-28", items="2.01,3.01,5.01", primary_doc="d.htm",
    )


def _merger_record(cik=1122304):
    return DelistRecord(
        ticker="AET", cik=cik, observed_delist_date="2018-11-28",
        crsp_code=241, bucket=CrspBucket.MERGER, confidence="high",
        reason="M&A 2.01+3.01+5.01", evidence={},
    )


def test_payout_extractor_propagates_refusal():
    edgar = _FakeEdgarMergerBlocked(_merger_closing_8k())
    ext = PayoutExtractor(edgar)
    with pytest.raises(EdgarBlocked):
        ext.extract(_merger_record())


def test_llm_merger_extractor_propagates_refusal(tmp_path):
    class _BoomLlm:
        def extract(self, system, user, schema):
            raise AssertionError("LLM must not be called when EDGAR is blocked")

    edgar = _FakeEdgarMergerBlocked(_merger_closing_8k())
    ext = LLMMergerTermsExtractor(edgar, _BoomLlm(), cache_dir=tmp_path)
    with pytest.raises(EdgarBlocked):
        ext.extract(_merger_record())

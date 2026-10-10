from datetime import date

import pytest

from delist_detection.sources.edgar import EdgarBlocked, EdgarClient
from delist_detection.identity.ticker_evidence import SEARCH_FORMS, EraEvidence, evidence_for, ticker_filing


class _Search:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def __call__(self, q, forms, lo, hi, *, ciks=()):
        self.calls.append((q, forms, lo, hi, tuple(ciks)))
        return self.hits


def _hit(cik, adsh="0001011006-16-000001"):
    return {"_id": f"{adsh}:doc.htm", "_source": {"ciks": [f"{cik:010d}"], "adsh": adsh}}


ERA = EraEvidence("YHOO", "2010-06-30", "2016-06-30", "name_search")


def test_a_resolver_tier_that_names_the_ticker_is_evidence_without_a_search():
    search = _Search([])
    assert evidence_for(1011006, [EraEvidence("YHOO", "2010-06-30", "2016-06-30", "cik_map")], search) == "tier:cik_map"
    assert search.calls == []


def test_a_filing_of_the_cik_naming_the_ticker_is_evidence():
    search = _Search([_hit(1011006)])
    assert evidence_for(1011006, [ERA], search) == "filing:0001011006-16-000001"
    assert search.calls == [('"YHOO"', SEARCH_FORMS, date(2009, 6, 30), date(2017, 6, 30), (1011006,))]


def test_a_hit_from_another_filer_is_not_evidence():
    assert ticker_filing(_Search([_hit(999)]), 1011006, "YHOO", "2010-06-30", "2016-06-30") is None


def test_a_short_ticker_is_never_searched():
    search = _Search([_hit(52988)])
    assert evidence_for(52988, [EraEvidence("J", "2012-06-29", "2014-06-30", "name_search")], search) == ""
    assert search.calls == []


def test_no_cik_or_no_search_means_no_evidence():
    assert evidence_for(None, [ERA], _Search([_hit(1011006)])) == ""
    assert evidence_for(1011006, [ERA], None) == ""


def test_full_text_search_narrows_to_the_given_filers(tmp_path, monkeypatch):
    client = EdgarClient(cache_dir=tmp_path, user_agent="Test Co test@example.com")
    urls = []
    monkeypatch.setattr(client, "efts_search", lambda url, window_end: urls.append(url) or [])
    client.full_text_search('"YHOO"', "8-K", date(2016, 1, 1), date(2016, 12, 31), ciks=(1011006,))
    client.full_text_search('"YHOO"', "8-K", date(2016, 1, 1), date(2016, 12, 31))
    assert urls[0].endswith("&ciks=0001011006") and "ciks=" not in urls[1]


def test_an_sec_refusal_during_the_search_stops_the_run():
    def refuse(*args, **kwargs):
        raise EdgarBlocked("403 from efts.sec.gov")
    with pytest.raises(EdgarBlocked):
        evidence_for(1011006, [ERA], refuse)

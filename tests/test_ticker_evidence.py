from datetime import date

import pytest

from delist_detection.sources.edgar import EdgarBlocked, EdgarClient
from delist_detection.identity.ticker_evidence import (EXCHANGE_PREFIXES, SEARCH_FORMS, EraEvidence, evidence_for,
                                                       ticker_filing)


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


def test_a_short_ticker_is_searched_with_its_exchange_in_front_and_never_bare():
    """FB-003 follow-up (old General Motors, CIK 40730): a bare "GM" matches ordinary text, so it is never the
    phrase; "NYSE: GM", as the company's own releases write it, is in 65 of its 8-Ks of 2007 to 2010."""
    era = EraEvidence("GM", "2008-01-16", "2009-06-08", "name_search")
    search = _Search([_hit(40730, "0000950152-09-000935")])
    assert evidence_for(40730, [era], search) == "filing:0000950152-09-000935"
    assert search.calls == [('"NYSE: GM"', SEARCH_FORMS, date(2007, 1, 16), date(2010, 6, 8), (40730,))]


def test_a_short_ticker_no_exchange_phrase_finds_has_no_evidence():
    search = _Search([])
    assert evidence_for(52988, [EraEvidence("J", "2012-06-29", "2014-06-30", "name_search")], search) == ""
    assert [c[0] for c in search.calls] == [f'"{x}: J"' for x in EXCHANGE_PREFIXES]
    assert '"J"' not in [c[0] for c in search.calls]
    other = _Search([_hit(999)])                           # another filer's release naming the ticker is no evidence
    assert ticker_filing(other, 52988, "J", "2012-06-29", "2014-06-30") is None


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

"""`TickerResolver.resolve(..., exclude=...)`: a lookup that never answers an excluded CIK from any tier (a derived era
asked without the old line's issuer, `identity.identify` rule X), and the memo that keeps its answer apart from the
lookup without the exclusion.

The tiers behind the company-ticker map are replaced by what each one is given to say (the way tests/test_resolver_efts.py
replaces the full-text search): the point is only that an excluded CIK is never taken from any of them."""
from datetime import date

import pytest

from delist_detection.identity.ticker_resolver import TickerResolver

OLD, NEW = 555, 777
DAY = "2016-06-01"


@pytest.fixture
def resolver(fake_edgar, monkeypatch):
    """A resolver whose tiers all say nothing, and for which every candidate existed, agrees by name and passed the
    Form 25 check: each test then gives one tier something to say."""
    r = TickerResolver(fake_edgar, observed_names=lambda t, d=None: "ACME CORP", today=date(2026, 9, 25))
    monkeypatch.setattr(r, "_ensure_companies", lambda: {})
    monkeypatch.setattr(r, "_name_search", lambda d, nm, exclude=(): [])
    monkeypatch.setattr(r, "_agreeing_issuer", lambda nm, d, since: None)
    monkeypatch.setattr(TickerResolver, "_validate_cik", lambda self, *a, **kw: True)
    monkeypatch.setattr(TickerResolver, "_fits_date", lambda self, *a, **kw: (True, True))
    monkeypatch.setattr(r.issuers, "existed_by", lambda cik, since: True, raising=False)
    return r


def test_the_company_ticker_map_does_not_answer_an_excluded_cik(fake_edgar):
    r = TickerResolver(fake_edgar, today=date(2026, 9, 25))
    assert r.resolve("ALTR", "2025-03-26").cik == 1701732
    res = r.resolve("ALTR", "2025-03-26", exclude={1701732})
    assert res.cik != 1701732 and res.source != "company_tickers"


def test_the_full_text_search_does_not_answer_an_excluded_cik(resolver, monkeypatch):
    monkeypatch.setattr(TickerResolver, "_efts_lookup", lambda self, t, d=None, **kw: (OLD, "ACME CORP", False))
    assert (resolver.resolve("ACME", DAY).cik, resolver.resolve("ACME", DAY).source) == (OLD, "efts")
    res = resolver.resolve("ACME", DAY, exclude={OLD})
    assert res.cik is None and res.source == "none"


def test_the_name_search_leaves_out_an_excluded_candidate(resolver, monkeypatch):
    """Its candidates come from the index here, as they do in a run: the excluded one is not among them."""
    monkeypatch.undo()
    r = TickerResolver(resolver.edgar, today=date(2026, 9, 25))
    monkeypatch.setattr(r, "_index", lambda: object())
    monkeypatch.setattr(r, "_index_candidates", lambda index, nm, d: {OLD: ("ACME CORP", 1), NEW: ("ACME CORP II", 5)})
    monkeypatch.setattr(r, "_edgar_name_fit", lambda cik, nm, d=None: (2, True))
    assert [c for c, _ in r._name_search(DAY, "ACME CORP")] == [OLD, NEW]
    assert [c for c, _ in r._name_search(DAY, "ACME CORP", {OLD})] == [NEW]
    assert r._name_search(DAY, "ACME CORP", {OLD, NEW}) == []


def test_the_name_tier_takes_the_next_candidate_when_the_best_is_excluded(resolver, monkeypatch):
    ranked = [(OLD, "ACME CORP"), (NEW, "ACME CORP II")]
    monkeypatch.setattr(resolver, "_name_search",
                        lambda d, nm, exclude=(): [(c, n) for c, n in ranked if c not in exclude])
    monkeypatch.setattr(resolver, "_accept_observed_name_candidate", lambda *a, **kw: True)
    assert resolver.resolve("ACME", DAY).cik == OLD
    assert resolver.resolve("ACME", DAY, exclude={OLD}).cik == NEW


def test_the_agreeing_issuer_fallback_does_not_answer_an_excluded_cik(resolver, monkeypatch):
    monkeypatch.setattr(resolver, "_agreeing_issuer", lambda nm, d, since: (OLD, "ACME CORP"))
    monkeypatch.setattr(resolver, "_accept_observed_name_candidate", lambda *a, **kw: False)
    assert resolver.resolve("ACME", DAY).cik == OLD
    assert resolver.resolve("ACME", DAY, exclude={OLD}).cik is None


def test_the_frequency_tier_does_not_answer_an_excluded_cik(resolver, monkeypatch):
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: [(OLD, "ACME CORP"), (NEW, "ACME CORP II")])
    monkeypatch.setattr(resolver, "_name_match_score", lambda *a, **kw: 1, raising=False)
    assert resolver.resolve("ACME", DAY).cik == OLD
    res = resolver.resolve("ACME", DAY, exclude={OLD})
    assert res.cik == NEW and res.source.startswith("efts_frequency")


def test_a_lookup_with_the_exclusion_and_one_without_keep_their_answers_under_two_keys(fake_edgar):
    r = TickerResolver(fake_edgar, today=date(2026, 9, 25))
    first = r.resolve("ALTR", "2025-03-26", exclude={1701732})      # asked with it first: no memo of the plain answer
    assert first.cik != 1701732
    assert r.resolve("ALTR", "2025-03-26").cik == 1701732           # a lookup without it still answers the CIK
    assert r.resolve("ALTR", "2025-03-26", exclude={1701732}).cik == first.cik
    assert set(r._memo) == {"ALTR|2025-03-26|", "ALTR|2025-03-26||!1701732"}
    second = TickerResolver(fake_edgar, today=date(2026, 9, 25))
    assert second.resolve("ALTR", "2025-03-26").cik == 1701732      # the other way round
    assert second.resolve("ALTR", "2025-03-26", exclude={1701732}).cik != 1701732


def test_the_degraded_check_reads_the_key_of_the_lookup_it_asks_about(fake_edgar):
    r = TickerResolver(fake_edgar, today=date(2026, 9, 25))
    r._degraded.add("ALTR|2025-03-26||!1701732")
    assert r.is_degraded("ALTR", "2025-03-26", exclude={1701732}) is True
    assert r.is_degraded("ALTR", "2025-03-26") is False
    assert r.is_degraded("ALTR", "2025-03-26", exclude={999}) is False


def test_the_memo_file_holds_both_answers_and_a_fresh_resolver_reads_each(fake_edgar, tmp_path):
    cache = tmp_path / "res.json"
    r = TickerResolver(fake_edgar, cache_path=cache, today=date(2026, 9, 25))
    r.resolve("ALTR", "2025-03-26")
    r.resolve("BAD", "2023-05-10", exclude={999001})
    again = TickerResolver(None, cache_path=cache, today=date(2026, 9, 25))
    assert again.resolve("ALTR", "2025-03-26").cik == 1701732

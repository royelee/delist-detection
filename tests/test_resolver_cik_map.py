from delist_detection.ticker_resolver import TickerResolver


def test_the_cik_map_answers_before_any_lookup(monkeypatch):
    resolver = TickerResolver(edgar=None, cik_map=lambda t, d: 859014 if t == "CPWR" else None)

    res = resolver.resolve("CPWR", "2014-12-15")

    assert (res.cik, res.source) == (859014, "cik_map")


def test_the_cik_map_beats_a_manual_override_and_says_so():
    resolver = TickerResolver(
        edgar=None,
        manual_overrides={"CPWR": 827099},
        cik_map=lambda t, d: 859014,
    )

    res = resolver.resolve("CPWR", "2014-12-15")

    assert res.cik == 859014
    assert res.source == "cik_map"


def test_a_ticker_the_map_does_not_cover_falls_through_to_the_manual_override():
    resolver = TickerResolver(edgar=None, manual_overrides={"IMCL": 1520047},
                              cik_map=lambda t, d: None)

    assert resolver.resolve("IMCL", "2018-01-02").cik == 1520047


def test_a_cik_map_answer_is_not_persisted_to_the_resolver_cache(tmp_path, fake_edgar):
    """An operator drops --cik-map to see what the library resolves on its own
    (the exact diagnostic this tier must not break), and a ticker later
    corrected in the map must not keep a stale pin forever. The tier answers
    before the memo read, so persisting it buys nothing."""
    cache = tmp_path / "res.json"

    mapped = TickerResolver(fake_edgar, cache_path=cache, cik_map=lambda t, d: 859014)
    res = mapped.resolve("CPWR", "2014-12-15")
    assert (res.cik, res.source) == (859014, "cik_map")

    # a later run over the same cache_path (same --names), with no --cik-map
    unmapped = TickerResolver(fake_edgar, cache_path=cache)
    res2 = unmapped.resolve("CPWR", "2014-12-15")
    assert res2.source != "cik_map"

import importlib

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


def test_the_cik_map_csv_is_read_by_ticker_and_era(tmp_path):
    m = importlib.import_module("scripts.classify_universe")
    p = tmp_path / "universe_identity.csv"
    p.write_text(
        "ticker,era_start,era_end,cik,name,source,confidence,flags\n"
        "LEAP,2012-06-29,2013-06-28,1065049,LEAP WIRELESS INTERNATIONAL INC,efts,high,\n"
        "LEAP,2021-06-30,2021-12-31,1818605,RIBBIT LEAP LTD,efts,high,\n"
        "CPWR,,,859014,COMPUWARE CORP,efts,high,\n"
    )

    lookup = m.load_cik_map_csv(p)

    assert lookup("LEAP", "2013-03-01") == 1065049
    assert lookup("LEAP", "2021-09-30") == 1818605
    assert lookup("LEAP", "2016-01-01") is None      # between eras: no claim
    assert lookup("CPWR", "2014-12-15") == 859014    # no era bounds: every event
    assert lookup("UNKNOWN", "2014-12-15") is None

import pytest

from delist_detection.observations import (
    Observation, ObservationError, ObservationIndex, load_observations, normalize_ticker,
    observations_from_instruments, observations_from_snapshots, split_eras, write_observations,
)


def test_normalize_ticker():
    assert normalize_ticker(" brk.b ") == "BRK-B"
    assert normalize_ticker("BF/A") == "BF-A"
    assert normalize_ticker("BRK B") == "BRK-B"
    assert normalize_ticker("AET") == "AET"


def test_load_validates_and_dedupes(tmp_path):
    p = tmp_path / "obs.csv"
    p.write_text(
        "ticker,as_of,name,cusip,cik,sec_id\n"
        "aet,2018-06-29,AETNA INC,00817y108,1122304,\n"
        "AET,2018-06-29,AETNA INC,00817Y108,1122304,\n"
        "BF.A,2018-06-29,BROWN FORMAN CORP CLASS A,,,\n"
    )
    obs = load_observations(p)
    assert obs == [
        Observation("AET", "2018-06-29", "AETNA INC", "00817Y108", 1122304, None),
        Observation("BF-A", "2018-06-29", "BROWN FORMAN CORP CLASS A", None, None, None),
    ]


def test_load_reports_bad_rows(tmp_path):
    p = tmp_path / "obs.csv"
    p.write_text("ticker,as_of\n,2018-01-01\nAET,2018-13-01\nAET,2018-01-02\n")
    with pytest.raises(ObservationError, match="line 2.*line 3"):
        load_observations(p)
    q = tmp_path / "noas.csv"
    q.write_text("ticker,name\nAET,x\n")
    with pytest.raises(ObservationError, match="as_of"):
        load_observations(q)


def test_recycled_ticker_splits_into_two_eras():
    obs = [
        Observation("MON", "2016-06-30", "MONSANTO CO"),
        Observation("MON", "2017-12-29", "MONSANTO CO"),
        Observation("MON", "2021-12-31", "MONUMENT CIRCLE ACQUISITION CORP"),
    ]
    eras = split_eras(obs)
    assert [(e.first, e.last, e.name) for e in eras] == [
        ("2016-06-30", "2017-12-29", "MONSANTO CO"),
        ("2021-12-31", "2021-12-31", "MONUMENT CIRCLE ACQUISITION CORP"),
    ]


def test_name_change_without_gap_splits_but_same_name_does_not():
    same = split_eras([Observation("X", "2020-06-30", "FOO INC"), Observation("X", "2020-12-31", "FOO INC")])
    assert len(same) == 1
    changed = split_eras([Observation("X", "2020-06-30", "FOREST OIL CORP"),
                          Observation("X", "2020-12-31", "FAST ACQUISITION CORP")])
    assert len(changed) == 2


def test_pin_change_splits():
    eras = split_eras([Observation("X", "2020-06-30", cik=1), Observation("X", "2020-12-31", cik=2)])
    assert [e.cik_pin for e in eras] == [1, 2]


def test_index_lookups():
    idx = ObservationIndex([
        Observation("ALTR", "2015-06-30", "ALTERA CORP"),
        Observation("ALTR", "2024-06-28", "ALTAIR ENGINEERING INC", cik=1701732),
    ])
    assert len(idx.eras()) == 2
    assert idx.name_on("ALTR", "2015-12-28") == "ALTERA CORP"
    assert idx.name_on("ALTR", "2025-03-26") == "ALTAIR ENGINEERING INC"
    assert idx.name_on("ALTR", "2010-01-01") == "ALTERA CORP"      # nearest after when none before
    assert idx.cik_pin_on("ALTR", "2025-03-26") == 1701732
    assert idx.cik_pin_on("ALTR", "2015-12-28") is None
    assert idx.era_for("ALTR", "2025-03-26").first == "2024-06-28"
    assert idx.name_on("ZZZZ") is None


def test_write_round_trip(tmp_path):
    obs = [Observation("B", "2020-01-02"), Observation("A", "2020-01-02", "A CO", "123456789", 7, "BBG1")]
    p = tmp_path / "o.csv"
    assert write_observations(obs, p) == 2
    assert load_observations(p) == sorted(obs, key=lambda o: (o.ticker, o.as_of))


def test_from_instruments(tmp_path):
    p = tmp_path / "all.txt"
    p.write_text("AABA\t2000-01-03\t2019-11-06\nBRK.B\t2000-01-03\t2026-05-22\n")
    obs = observations_from_instruments(p)
    assert [(o.ticker, o.as_of) for o in obs] == [
        ("AABA", "2000-01-03"), ("AABA", "2019-11-06"), ("BRK-B", "2000-01-03"), ("BRK-B", "2026-05-22")]


def test_from_snapshots(tmp_path):
    (tmp_path / "2018-06-29.csv").write_text(
        "ticker,name,asset_class\nAET,AETNA INC,Equity\nXTSLA,BLK CSH FND,Money Market\n")
    (tmp_path / "russell_20180102.csv").write_text("Ticker,Name\nAET,AETNA INC\n")
    (tmp_path / "2013-06-29.csv").write_text("ticker,name\n")          # header-only placeholder
    (tmp_path / "notes.csv").write_text("ticker,name\nZZZ,no date in name\n")
    obs = observations_from_snapshots(tmp_path, where={"asset_class": "Equity"})
    assert [(o.ticker, o.as_of, o.name) for o in obs] == [
        ("AET", "2018-01-02", "AETNA INC"), ("AET", "2018-06-29", "AETNA INC")]


def test_where_ignored_when_column_blank(tmp_path):
    (tmp_path / "russell_2008-01-16.csv").write_text("ticker,name,asset_class\nAET,AETNA INC,\n")
    obs = observations_from_snapshots(tmp_path, where={"asset_class": "Equity"})
    assert [o.ticker for o in obs] == ["AET"]

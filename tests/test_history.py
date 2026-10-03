"""history.ticker_on: a security's ticker on a day, from its dated sightings.
history.observation_map_rows: observation_map.csv's rows (spec §7.x).
history.filtered_ticker_sightings: Phase 4 rule 2, a backfilled observation
adds no ticker_history range."""
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.history import (Sighting, filtered_ticker_sightings, is_backfilled, observation_map_rows,
                                      ticker_on)
from delist_detection.observations import Observation, TickerEra


def test_the_ticker_on_a_day_is_the_latest_sighting_on_or_before_it():
    on = ticker_on([Sighting("2021-12-31", "FB", "observation"), Sighting("2022-06-09", "META", "ftd")])
    assert on("2022-06-08") == "FB" and on("2022-06-09") == "META" and on("2030-01-01") == "META"


def test_a_day_before_every_sighting_takes_the_first_and_none_without_sightings():
    assert ticker_on([Sighting("2021-12-31", "FB", "observation")])("2000-01-01") == "FB"
    assert ticker_on([])("2021-12-31") is None


# --- observation_map_rows: one row per observation, its sec_id and status ---

def _th(sec_id, ticker, valid_from, valid_to, source="observation"):
    return {"sec_id": sec_id, "ticker": ticker, "exchange": None, "valid_from": valid_from, "valid_to": valid_to,
            "source": source}


def test_a_resolved_and_listed_observation_is_mapped():
    era = TickerEra("X", "2020-01-02", "2020-01-02", [Observation("X", "2020-01-02", "X CORP")])
    th_rows = [_th("BBGX", "X", "2020-01-02", None)]
    rows = observation_map_rows([era], {era.key: "BBGX"}, {era.key: 1}, {"BBGX": []}, FtdIndex(), {"BBGX": None},
                                {"BBGX": False}, {"BBGX": True}, th_rows, [])
    assert rows == [{"ticker": "X", "as_of": "2020-01-02", "name": "X CORP", "cusip": None, "pin_cik": None,
                     "pin_sec_id": None, "era": era.key, "sec_id": "BBGX", "issuer_cik": 1,
                     "history_ticker": "X", "in_ticker_history": True, "status": "mapped"}]


def test_an_era_with_no_sec_id_is_unresolved():
    era = TickerEra("NU", "2020-01-02", "2020-01-02", [Observation("NU", "2020-01-02", "NU HOLDINGS")])
    rows = observation_map_rows([era], {era.key: None}, {era.key: None}, {}, FtdIndex(), {}, {}, {}, [], [])
    assert rows == [{"ticker": "NU", "as_of": "2020-01-02", "name": "NU HOLDINGS", "cusip": None, "pin_cik": None,
                     "pin_sec_id": None, "era": era.key, "sec_id": None, "issuer_cik": None,
                     "history_ticker": None, "in_ticker_history": False, "status": "unresolved"}]


def test_an_observation_after_the_clipped_history_end_of_a_delisted_security_is_after_delisting():
    era = TickerEra("OZRK", "2017-01-02", "2018-06-29", [
        Observation("OZRK", "2017-01-02", "BANK OZK"), Observation("OZRK", "2018-06-29", "BANK OZK")])
    th_rows = [_th("BBGOZRK", "OZRK", "2017-01-02", "2017-12-31")]
    rows = observation_map_rows([era], {era.key: "BBGOZRK"}, {era.key: 5}, {"BBGOZRK": []}, FtdIndex(),
                                {"BBGOZRK": "2017-12-31"}, {"BBGOZRK": True}, {"BBGOZRK": False}, th_rows, [])
    statuses = {r["as_of"]: r["status"] for r in rows}
    assert statuses == {"2017-01-02": "mapped", "2018-06-29": "after_delisting"}
    # after_delisting rows still carry their sec_id
    assert next(r for r in rows if r["as_of"] == "2018-06-29")["sec_id"] == "BBGOZRK"


def test_an_observation_after_a_clip_set_by_an_unconfirmed_last_trade_day_is_after_unconfirmed_delisting():
    """Bank of Ozarks-like: the delisting that set the clip has no confirmed
    last-trade day (`end_confirmed` false for that sec_id), so the caller
    should keep and check this member rather than drop it as after_delisting."""
    era = TickerEra("OZRK", "2017-01-02", "2018-06-29", [
        Observation("OZRK", "2017-01-02", "BANK OZK"), Observation("OZRK", "2018-06-29", "BANK OZK")])
    th_rows = [_th("BBGOZRK", "OZRK", "2017-01-02", "2017-12-31")]
    rows = observation_map_rows([era], {era.key: "BBGOZRK"}, {era.key: 5}, {"BBGOZRK": []}, FtdIndex(),
                                {"BBGOZRK": "2017-12-31"}, {"BBGOZRK": False}, {"BBGOZRK": False}, th_rows, [])
    statuses = {r["as_of"]: r["status"] for r in rows}
    assert statuses == {"2017-01-02": "mapped", "2018-06-29": "after_unconfirmed_delisting"}
    # after_unconfirmed_delisting rows still carry their sec_id
    assert next(r for r in rows if r["as_of"] == "2018-06-29")["sec_id"] == "BBGOZRK"


def test_an_observation_on_a_still_listed_securitys_ticker_is_never_after_delisting_even_past_a_stale_end():
    era = TickerEra("X", "2020-01-02", "2020-06-01", [Observation("X", "2020-06-01", "X CORP")])
    th_rows = [_th("BBGX", "X", "2020-01-02", None)]
    rows = observation_map_rows([era], {era.key: "BBGX"}, {era.key: 1}, {"BBGX": []}, FtdIndex(),
                                {"BBGX": "2020-01-15"}, {"BBGX": True}, {"BBGX": True}, th_rows, [])
    assert rows[0]["status"] == "mapped"


def test_a_ticker_seen_under_two_names_on_one_date_is_conflict():
    era = TickerEra("CB", "2012-06-29", "2012-06-29", [Observation("CB", "2012-06-29", "ACE LTD")])
    th_rows = [_th("BBGCB", "CB", "2012-06-29", None)]
    conflicts = [("CB", "2012-06-29")]
    rows = observation_map_rows([era], {era.key: "BBGCB"}, {era.key: 1}, {"BBGCB": []}, FtdIndex(),
                                {"BBGCB": None}, {"BBGCB": False}, {"BBGCB": True}, th_rows, conflicts)
    assert rows[0]["status"] == "conflict"


def test_backfilled_ticker_when_no_ftd_row_under_the_observed_ticker_but_another_symbol_trades():
    """Yahoo stays YHOO in 2012 fails, but a 2012 snapshot backfilled it as CB
    (Chubb's later ticker): no fails row for CB's CUSIP under CB near that
    date, but the CUSIP fails under YHOO -- backfilled_ticker."""
    era = TickerEra("CB", "2012-06-29", "2012-06-29", [Observation("CB", "2012-06-29", "CHUBB CORP")])
    th_rows = [_th("BBGCHUBB", "CB", "2012-06-29", None)]
    ftd = FtdIndex([FtdRow("2012-06-28", "CUSIP1", "YHOO", "YAHOO INC", 15.0),
                    FtdRow("2012-07-02", "CUSIP1", "YHOO", "YAHOO INC", 16.0)])
    rows = observation_map_rows([era], {era.key: "BBGCHUBB"}, {era.key: 1}, {"BBGCHUBB": ["CUSIP1"]}, ftd,
                                {"BBGCHUBB": None}, {"BBGCHUBB": False}, {"BBGCHUBB": True}, th_rows, [])
    assert rows[0]["status"] == "backfilled_ticker"


def test_an_observed_ticker_with_its_own_ftd_row_nearby_is_not_backfilled():
    era = TickerEra("CB", "2012-06-29", "2012-06-29", [Observation("CB", "2012-06-29", "CHUBB CORP")])
    th_rows = [_th("BBGCHUBB", "CB", "2012-06-29", None)]
    ftd = FtdIndex([FtdRow("2012-06-28", "CUSIP1", "CB", "CHUBB CORP", 70.0)])
    rows = observation_map_rows([era], {era.key: "BBGCHUBB"}, {era.key: 1}, {"BBGCHUBB": ["CUSIP1"]}, ftd,
                                {"BBGCHUBB": None}, {"BBGCHUBB": False}, {"BBGCHUBB": True}, th_rows, [])
    assert rows[0]["status"] == "mapped"


def test_backfilled_ticker_requires_as_of_on_or_after_backfill_start():
    era = TickerEra("CB", "2003-01-02", "2003-01-02", [Observation("CB", "2003-01-02", "CHUBB CORP")])
    th_rows = [_th("BBGCHUBB", "CB", "2003-01-02", None)]
    rows = observation_map_rows([era], {era.key: "BBGCHUBB"}, {era.key: 1}, {"BBGCHUBB": ["CUSIP1"]}, FtdIndex(),
                                {"BBGCHUBB": None}, {"BBGCHUBB": False}, {"BBGCHUBB": True}, th_rows, [])
    assert rows[0]["status"] == "mapped"


def test_history_ticker_gives_the_separator_spelling_for_an_observed_bare_ticker():
    """BFB observed; ticker_history carries BF-B: history_ticker joins on the
    spelling with a separator, and in_ticker_history still matches (bare
    forms compared without the separator)."""
    era = TickerEra("BFB", "2020-01-02", "2020-01-02", [Observation("BFB", "2020-01-02", "BROWN-FORMAN")])
    th_rows = [_th("BBGBF", "BF-B", "2020-01-02", None)]
    rows = observation_map_rows([era], {era.key: "BBGBF"}, {era.key: 1}, {"BBGBF": []}, FtdIndex(),
                                {"BBGBF": None}, {"BBGBF": False}, {"BBGBF": True}, th_rows, [])
    assert rows[0]["history_ticker"] == "BF-B" and rows[0]["in_ticker_history"] is True


def test_row_count_equals_the_number_of_observations_given():
    era1 = TickerEra("X", "2020-01-02", "2020-06-01", [
        Observation("X", "2020-01-02", "X CORP"), Observation("X", "2020-06-01", "X CORP")])
    era2 = TickerEra("Y", "2020-01-02", "2020-01-02", [Observation("Y", "2020-01-02", "Y CORP")])
    th_rows = [_th("BBGX", "X", "2020-01-02", None), _th("BBGY", "Y", "2020-01-02", None)]
    rows = observation_map_rows([era1, era2], {era1.key: "BBGX", era2.key: "BBGY"}, {era1.key: 1, era2.key: 2},
                                {"BBGX": [], "BBGY": []}, FtdIndex(), {"BBGX": None, "BBGY": None},
                                {"BBGX": False, "BBGY": False}, {"BBGX": True, "BBGY": True}, th_rows, [])
    assert len(rows) == 3


def test_a_masked_fails_symbol_is_not_a_ticker_sighting():
    """SEC's 2007 fails files mask some symbols (**********): not a ticker."""
    from delist_detection.history import ticker_sightings
    from delist_detection.security_master import Security
    sec = Security("CIK1-COMMON", 1, "COMMON", "AAA INC", "Common Stock", False, "placeholder")
    ftd = FtdIndex([FtdRow("2007-03-01", "CUSIP1", "AAA", "AAA INC", 5.0),
                    FtdRow("2007-03-02", "CUSIP1", "**********", "AAA INC", 5.0)])
    assert {s.value for s in ticker_sightings(sec, ftd, ["CUSIP1"])} == {"AAA"}


# --- filtered_ticker_sightings: Phase 4 rule 2 ---

def test_filtered_ticker_sightings_drops_a_backfilled_observation_but_keeps_ftd_evidence():
    """A 2012 snapshot backfills CB (Chubb's later ticker) with no fails row
    under CB nearby -- dropped; the real ACE fails evidence on the same day,
    and a later CB observation actually confirmed by its own fails row, are
    both kept."""
    sig = [Sighting("2012-06-29", "CB", "observation"), Sighting("2012-06-29", "ACE", "ftd"),
          Sighting("2016-01-04", "CB", "observation"), Sighting("2016-01-04", "CB", "ftd")]
    ftd = FtdIndex([FtdRow("2012-06-28", "CUSIP1", "ACE", "ACE LTD", 80.0),
                    FtdRow("2016-01-04", "CUSIP1", "CB", "CHUBB LTD", 120.0)])
    out = filtered_ticker_sightings(sig, ["CUSIP1"], ftd)
    assert Sighting("2012-06-29", "CB", "observation") not in out
    assert Sighting("2012-06-29", "ACE", "ftd") in out
    assert Sighting("2016-01-04", "CB", "observation") in out


def test_filtered_ticker_sightings_keeps_everything_with_no_cusips_to_check():
    sig = [Sighting("2012-06-29", "CB", "observation")]
    assert filtered_ticker_sightings(sig, [], FtdIndex()) == sig


def test_pin_columns_carry_the_observations_own_cik_and_sec_id_pins():
    obs = Observation("X", "2020-01-02", "X CORP", cusip="000000000", cik=42, sec_id="BBGPIN")
    era = TickerEra("X", "2020-01-02", "2020-01-02", [obs])
    rows = observation_map_rows([era], {era.key: "BBGPIN"}, {era.key: 42}, {"BBGPIN": []}, FtdIndex(),
                                {"BBGPIN": None}, {"BBGPIN": False}, {"BBGPIN": True}, [], [])
    assert (rows[0]["pin_cik"], rows[0]["pin_sec_id"], rows[0]["cusip"]) == (42, "BBGPIN", "000000000")


# --- is_backfilled: separator-insensitive symbol matching ---

def test_is_backfilled_treats_a_bare_fails_row_symbol_as_the_observed_dashed_tickers_own():
    """The observed ticker is dashed ("BF-B"); the fails row is spelled bare
    ("BFB") -- still the ticker's own row (compared with the separator
    stripped from both sides), so not backfilled."""
    ftd = FtdIndex([FtdRow("2012-06-28", "CUSIP1", "BFB", "BROWN-FORMAN", 70.0)])
    assert is_backfilled("2012-06-29", "BF-B", ["CUSIP1"], ftd) is False


def test_backfill_cusips_names_the_issuers_cusip_before_its_end():
    from delist_detection.history import backfill_cusips
    ftd = FtdIndex([
        FtdRow("2007-10-01", "071707103", "BOL", "BAUSCH & LOMB INC COM", 60.0),
        FtdRow("2007-10-15", "071707103", "BOL", "BAUSCH & LOMB INC COM", 61.0),
        FtdRow("2007-09-01", "999999999", "BOL", "OTHER WIDGETS CO", 5.0),        # another issuer's description
        FtdRow("2007-10-20", "071707103", "BOLXXXX", "BAUSCH & LOMB INC COM", 61.0),  # deleted symbol
        FtdRow("2008-06-01", "888888888", "BOL", "BAUSCH LATER CORP", 9.0),        # after the end
        FtdRow("2007-03-01", "777777777", "BOL", "BAUSCH & LOMB INC COM", 50.0),   # before the window
    ])
    assert backfill_cusips(["BOL"], "2007-11-05", ftd, ["BAUSCH & LOMB INC"]) == ["071707103"]
    assert backfill_cusips(["BOL"], "2007-11-05", ftd, ["SOMEONE ELSE"]) == []


def test_backfill_cusips_with_no_names_matches_nothing():
    from delist_detection.history import backfill_cusips
    ftd = FtdIndex([
        FtdRow("2007-10-01", "071707103", "BOL", "BAUSCH & LOMB INC COM", 60.0),
        FtdRow("2007-09-01", "999999999", "BOL", "OTHER WIDGETS CO", 5.0),
    ])
    assert backfill_cusips(["BOL"], "2007-11-05", ftd, []) == []

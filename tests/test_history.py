"""history.observation_map_rows: observation_map.csv's rows (spec §7.x).
history.filtered_ticker_sightings: Phase 4 rule 2, a backfilled observation
adds no ticker_history range.
history.Histories: where a security's history ends (the clip, a successor's ticker, listed today), at its
interface, without a run. (The ticker on a day and the last own sighting are the trading record's:
tests/test_trading_record.py.)"""
from datetime import date, timedelta

from delist_detection.added_securities import AddedLineSuccessor
from delist_detection.crsp_codes import CrspBucket
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.history import (Ending, Histories, SecurityEnd, Sighting, cusip_sightings,
                                      filtered_ticker_sightings, is_backfilled, observation_map_rows,
                                      ticker_range_review, ticker_sightings)
from delist_detection.last_trade import NO_DAY, UNCONFIRMED, LastTrade
from delist_detection.observations import Observation, TickerEra
from delist_detection.security_master import Security
from delist_detection.store import DelistingKey


# --- observation_map_rows: one row per observation, its sec_id and status, read from the history's own answer ---

def _plain_history(sightings, *, endings=(), listed=None, cusips=None, ftd=None):
    """A history over one plain security per sec_id of `sightings` (no eras), listed today unless `listed` says."""
    secs = {sid: Security(sid, 1, "COMMON", sid, "Common Stock", True, "cusip") for sid in sightings}
    return Histories(secs, sightings, cusips or {}, ftd or FtdIndex(), endings,
                     listed=listed if listed is not None else {sid: True for sid in sightings})


def test_a_resolved_and_listed_observation_is_mapped():
    era = TickerEra("X", "2020-01-02", "2020-01-02", [Observation("X", "2020-01-02", "X CORP")])
    history = _plain_history({"BBGX": [Sighting("2020-01-02", "X", "observation")]})
    rows = observation_map_rows([era], {era.key: "BBGX"}, {era.key: 1}, history, [])
    assert rows == [{"ticker": "X", "as_of": "2020-01-02", "name": "X CORP", "cusip": None, "pin_cik": None,
                     "pin_sec_id": None, "era": era.key, "sec_id": "BBGX", "issuer_cik": 1,
                     "history_ticker": "X", "in_ticker_history": True, "status": "mapped"}]


def test_an_era_with_no_sec_id_is_unresolved():
    era = TickerEra("NU", "2020-01-02", "2020-01-02", [Observation("NU", "2020-01-02", "NU HOLDINGS")])
    rows = observation_map_rows([era], {era.key: None}, {era.key: None}, _plain_history({}), [])
    assert rows == [{"ticker": "NU", "as_of": "2020-01-02", "name": "NU HOLDINGS", "cusip": None, "pin_cik": None,
                     "pin_sec_id": None, "era": era.key, "sec_id": None, "issuer_cik": None,
                     "history_ticker": None, "in_ticker_history": False, "status": "unresolved"}]


def _ozrk(last_trade):
    """Bank of Ozarks-like: OZRK observed 2017-01-02 and 2018-06-29, a liquidation delisted 2017-12-31."""
    era = TickerEra("OZRK", "2017-01-02", "2018-06-29", [
        Observation("OZRK", "2017-01-02", "BANK OZK"), Observation("OZRK", "2018-06-29", "BANK OZK")])
    history = _plain_history(
        {"BBGOZRK": [Sighting("2017-01-02", "OZRK", "observation"), Sighting("2018-06-29", "OZRK", "observation")]},
        endings=[Ending(DelistingKey("BBGOZRK", "2017-12-31"), last_trade, CrspBucket.LIQUIDATION, None, "")],
        listed={"BBGOZRK": False})
    assert [(r["ticker"], r["valid_from"], r["valid_to"]) for r in history.ticker_rows] == [
        ("OZRK", "2017-01-02", "2017-12-31")]
    return observation_map_rows([era], {era.key: "BBGOZRK"}, {era.key: 5}, history, [])


def test_an_observation_after_the_clipped_history_end_of_a_delisted_security_is_after_delisting():
    rows = _ozrk(LastTrade(date(2017, 12, 31), "midas", ()))
    statuses = {r["as_of"]: r["status"] for r in rows}
    assert statuses == {"2017-01-02": "mapped", "2018-06-29": "after_delisting"}
    # after_delisting rows still carry their sec_id
    assert next(r for r in rows if r["as_of"] == "2018-06-29")["sec_id"] == "BBGOZRK"


def test_an_observation_after_a_clip_set_by_an_unconfirmed_last_trade_day_is_after_unconfirmed_delisting():
    """Bank of Ozarks-like: the delisting that set the clip has no confirmed
    last-trade day (the history's end is not confirmed), so the caller
    should keep and check this member rather than drop it as after_delisting."""
    rows = _ozrk(LastTrade(None, "", (NO_DAY,)))
    statuses = {r["as_of"]: r["status"] for r in rows}
    assert statuses == {"2017-01-02": "mapped", "2018-06-29": "after_unconfirmed_delisting"}
    # after_unconfirmed_delisting rows still carry their sec_id
    assert next(r for r in rows if r["as_of"] == "2018-06-29")["sec_id"] == "BBGOZRK"


def test_an_observation_on_a_still_listed_securitys_ticker_is_never_after_delisting_even_past_an_ending():
    era = TickerEra("X", "2020-01-02", "2020-06-01", [Observation("X", "2020-06-01", "X CORP")])
    ending = Ending(DelistingKey("BBGX", "2020-01-15"), LastTrade(date(2020, 1, 14), "midas", ()),
                    CrspBucket.LIQUIDATION, None, "NYSE")
    history = _plain_history({"BBGX": [Sighting("2020-01-02", "X", "observation")]}, endings=[ending])
    assert history.end("BBGX") == SecurityEnd(None, False, True)
    rows = observation_map_rows([era], {era.key: "BBGX"}, {era.key: 1}, history, [])
    assert rows[0]["status"] == "mapped"


def test_a_ticker_seen_under_two_names_on_one_date_is_conflict():
    era = TickerEra("CB", "2012-06-29", "2012-06-29", [Observation("CB", "2012-06-29", "ACE LTD")])
    history = _plain_history({"BBGCB": [Sighting("2012-06-29", "CB", "observation")]})
    rows = observation_map_rows([era], {era.key: "BBGCB"}, {era.key: 1}, history, [("CB", "2012-06-29")])
    assert rows[0]["status"] == "conflict"


def test_backfilled_ticker_when_no_ftd_row_under_the_observed_ticker_but_another_symbol_trades():
    """Yahoo stays YHOO in 2012 fails, but a 2012 snapshot backfilled it as CB
    (Chubb's later ticker): no fails row for CB's CUSIP under CB near that
    date, but the CUSIP fails under YHOO -- backfilled_ticker."""
    era = TickerEra("CB", "2012-06-29", "2012-06-29", [Observation("CB", "2012-06-29", "CHUBB CORP")])
    ftd = FtdIndex([FtdRow("2012-06-28", "CUSIP1", "YHOO", "YAHOO INC", 15.0),
                    FtdRow("2012-07-02", "CUSIP1", "YHOO", "YAHOO INC", 16.0)])
    history = _plain_history({"BBGCHUBB": [Sighting("2012-06-29", "CB", "observation")]},
                             cusips={"BBGCHUBB": ["CUSIP1"]}, ftd=ftd)
    rows = observation_map_rows([era], {era.key: "BBGCHUBB"}, {era.key: 1}, history, [])
    assert rows[0]["status"] == "backfilled_ticker"


def test_an_observed_ticker_with_its_own_ftd_row_nearby_is_not_backfilled():
    era = TickerEra("CB", "2012-06-29", "2012-06-29", [Observation("CB", "2012-06-29", "CHUBB CORP")])
    ftd = FtdIndex([FtdRow("2012-06-28", "CUSIP1", "CB", "CHUBB CORP", 70.0)])
    history = _plain_history({"BBGCHUBB": [Sighting("2012-06-29", "CB", "observation")]},
                             cusips={"BBGCHUBB": ["CUSIP1"]}, ftd=ftd)
    rows = observation_map_rows([era], {era.key: "BBGCHUBB"}, {era.key: 1}, history, [])
    assert rows[0]["status"] == "mapped"


def test_backfilled_ticker_requires_as_of_on_or_after_backfill_start():
    era = TickerEra("CB", "2003-01-02", "2003-01-02", [Observation("CB", "2003-01-02", "CHUBB CORP")])
    history = _plain_history({"BBGCHUBB": [Sighting("2003-01-02", "CB", "observation")]},
                             cusips={"BBGCHUBB": ["CUSIP1"]})
    rows = observation_map_rows([era], {era.key: "BBGCHUBB"}, {era.key: 1}, history, [])
    assert rows[0]["status"] == "mapped"


def test_history_ticker_gives_the_separator_spelling_for_an_observed_bare_ticker():
    """BFB observed; ticker_history carries BF-B: history_ticker joins on the
    spelling with a separator, and in_ticker_history still matches (bare
    forms compared without the separator)."""
    era = TickerEra("BFB", "2020-01-02", "2020-01-02", [Observation("BFB", "2020-01-02", "BROWN-FORMAN")])
    history = _plain_history({"BBGBF": [Sighting("2020-01-02", "BF-B", "observation")]})
    rows = observation_map_rows([era], {era.key: "BBGBF"}, {era.key: 1}, history, [])
    assert rows[0]["history_ticker"] == "BF-B" and rows[0]["in_ticker_history"] is True


def test_row_count_equals_the_number_of_observations_given():
    era1 = TickerEra("X", "2020-01-02", "2020-06-01", [
        Observation("X", "2020-01-02", "X CORP"), Observation("X", "2020-06-01", "X CORP")])
    era2 = TickerEra("Y", "2020-01-02", "2020-01-02", [Observation("Y", "2020-01-02", "Y CORP")])
    history = _plain_history({"BBGX": [Sighting("2020-01-02", "X", "observation")],
                              "BBGY": [Sighting("2020-01-02", "Y", "observation")]})
    rows = observation_map_rows([era1, era2], {era1.key: "BBGX", era2.key: "BBGY"}, {era1.key: 1, era2.key: 2},
                                history, [])
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
    rows = observation_map_rows([era], {era.key: "BBGPIN"}, {era.key: 42}, _plain_history({"BBGPIN": []}), [])
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


# --- sub-plan 5a, U5: a security's own tickers include its line's (Security.line_tickers) ---

def _hsc(line_tickers=frozenset()):
    era = TickerEra("HSC", "2008-01-16", "2023-06-20", [Observation("HSC", "2008-01-16", "HARSCO CORP")])
    return Security("BBG000BLH3P8", 45876, "COMMON", "HARSCO CORP", "Common Stock", True, "cusip", eras=[era],
                    line_tickers=frozenset(line_tickers))


def test_own_tickers_are_the_eras_and_the_lines():
    assert _hsc().own_tickers() == {"HSC"} and _hsc({"NVRI"}).own_tickers() == {"HSC", "NVRI"}


def test_a_first_day_zzzz_row_is_no_ticker_sighting_but_still_a_cusip_sighting():
    """A new CUSIP's first fails row carries the ticker with ZZZZ appended (FMDZZZZ): no ticker range opens under
    it, while the CUSIP's own range starts that day."""
    era = TickerEra("FMD", "2008-01-16", "2008-01-16", [Observation("FMD", "2008-01-16", "FIRST MARBLEHEAD")])
    sec = Security("BBG000BN6349", 1262279, "COMMON", "FIRST MARBLEHEAD", "Common Stock", True, "cusip", eras=[era])
    ftd = FtdIndex([FtdRow("2013-12-03", "320771207", "FMDZZZZ", "FIRST MARBLEHEAD CORP", 0.01),
                    FtdRow("2013-12-04", "320771207", "FMD", "FIRST MARBLEHEAD CORP", 5.41),
                    FtdRow("2013-12-05", "320771207", "FMD", "FIRST MARBLEHEAD CORP", 5.50)])
    assert {s.value for s in ticker_sightings(sec, ftd, ["320771207"]) if s.source == "ftd"} == {"FMD"}
    assert cusip_sightings(sec, ftd, ["320771207"])[0] == Sighting("2013-12-03", "320771207", "ftd")


# --- Histories: where a security's history ends, at its interface (the clip, a successor's ticker, listed today) ---

AET_CUSIP = "00817Y108"
AET_ROWS = [FtdRow("2018-06-29", AET_CUSIP, "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-07-02", AET_CUSIP, "AET", "AETNA INC.(NEW)", 181.0),
            FtdRow("2018-11-29", AET_CUSIP, "AET", "AETNA INC.(NEW)", 212.70)]


def _ending(sid, delist_date, bucket, day, *, flags=(), successor=None, exchange="NYSE", source="notice_a"):
    return Ending(DelistingKey(sid, delist_date), LastTrade(day, source, tuple(flags)), bucket, successor, exchange)


def _history(securities, rows, endings, *, cusips, listed=None, added=None, extra=None, exchange_today=None):
    """The history of `securities` over `endings`, each sighted as the run sights it (`ticker_sightings`: its
    observations and its CUSIPs' fails rows), plus `extra` sightings of securities with no eras."""
    ftd = FtdIndex(rows)
    sightings = {sid: ticker_sightings(s, ftd, cusips.get(sid, [])) for sid, s in securities.items()}
    for sid, sig in (extra or {}).items():
        sightings[sid] = sig
    return Histories(securities, sightings, cusips, ftd, endings, listed=listed or {}, added=added or {},
                     exchange_today=exchange_today or (lambda security, ticker: None))


def _aet():
    era = TickerEra("AET", "2017-06-30", "2018-06-29", [Observation("AET", "2017-06-30", "AETNA INC"),
                                                         Observation("AET", "2018-06-29", "AETNA INC")])
    return {"BBGAET": Security("BBGAET", 1122304, "COMMON", "AETNA INC", "Common Stock", True, "cusip", eras=[era])}


def _aet_history(ending, extra_rows=()):
    """Aetna's history (not listed today) over one ending of its, with `extra_rows` of its CUSIP after the base rows."""
    return _history(_aet(), AET_ROWS + list(extra_rows), [ending], cusips={"BBGAET": [AET_CUSIP]})


def _aet_ranges(history):
    return [(r["ticker"], r["valid_from"], r["valid_to"], r["exchange"]) for r in history.ticker_rows]


def _continuing_rows(symbol, cusip, *, start, count, step_days=3, prices=(200.0, 201.0)):
    out, d = [], date.fromisoformat(start)
    for i in range(count):
        out.append(FtdRow(d.isoformat(), cusip, symbol, "AETNA INC.(NEW)", prices[i % len(prices)]))
        d += timedelta(days=step_days)
    return out


def test_a_merger_the_securitys_own_cusip_trades_past_does_not_end_it_WRK_DIS():
    """WRK, DIS 2019: a merger delisting is recorded, but the security's own CUSIP keeps trading under its own
    ticker afterward -- at least 20 live fails rows over at least 60 days with 2+ distinct prices -- so it was no real
    end: it goes on (`going_on`, the input to `rewrites.mark_going_on`), and the history is not clipped there: it
    extends to the real last sighting."""
    continuing = _continuing_rows("AET", AET_CUSIP, start="2018-12-03", count=25)
    ending = _ending("BBGAET", "2018-12-09", CrspBucket.MERGER, date(2018, 11, 28))
    history = _aet_history(ending, continuing)
    assert history.going_on == {ending.key}
    assert history.end("BBGAET") == SecurityEnd(None, False, False)
    assert _aet_ranges(history) == [("AET", "2017-06-30", continuing[-1].date, None)]


def test_a_cash_merger_after_which_its_cusip_stops_trading_ends_it_at_its_last_trade():
    """No run of fails rows after the confirmed last trade (one settling row): a real exit. The range ends at the
    last trade and carries the exchange the ending left."""
    ending = _ending("BBGAET", "2018-12-09", CrspBucket.MERGER, date(2018, 11, 28))
    history = _aet_history(ending)
    assert history.going_on == frozenset()
    assert history.end("BBGAET") == SecurityEnd("2018-11-28", True, False)
    assert _aet_ranges(history) == [("AET", "2017-06-30", "2018-11-28", "NYSE")]
    assert [(r["cusip"], r["valid_to"]) for r in history.cusip_rows] == [(AET_CUSIP, "2018-11-28")]


def test_a_liquidation_ends_its_security_whatever_otc_tail_follows():
    """RHD, Smurfit-Stone, Idearc, GGP: a bankruptcy delisting followed by years of real, varying-price OTC fails.
    The continues-trading exception applies only to mergers and exchange transfers (ticker_history records exchange
    listings), so a liquidation always clips, however much and however varied the fails evidence that follows."""
    varying = _continuing_rows("AET", AET_CUSIP, start="2018-12-03", count=200, step_days=10,
                               prices=(0.50, 0.75, 1.10, 0.30, 0.90))
    ending = _ending("BBGAET", "2018-12-09", CrspBucket.LIQUIDATION, date(2018, 11, 28), exchange="")
    history = _aet_history(ending, varying)
    assert history.going_on == frozenset()
    assert history.end("BBGAET") == SecurityEnd("2018-11-28", True, False)
    assert _aet_ranges(history)[0][2] == "2018-11-28"


def test_an_ending_with_no_confirmed_last_trade_clips_at_its_end_day_and_is_never_second_guessed():
    """A last trade nothing confirms is too weak to test continued trading against: Bank of Ozarks (no day at all:
    clipped at the delist date), Monster Worldwide and SunPower (the no-Form-25 fallback's guessed last sighting:
    clipped at the guess; MNST traded on for years, the guess was wrong, not the listing), and an undated
    unconfirmed liquidation (the delist date: an unclipped range would run past the security's real end). The end
    is not confirmed (`LastTrade.confirmed`), whatever fails rows follow."""
    continuing = _continuing_rows("AET", AET_CUSIP, start="2018-12-03", count=25)
    cases = [(CrspBucket.MERGER, LastTrade(None, "", (NO_DAY,)), "2018-12-09"),
             (CrspBucket.EXCHANGE_TRANSFER, LastTrade(date(2018, 11, 28), "", (UNCONFIRMED,)), "2018-11-28"),
             (CrspBucket.LIQUIDATION, LastTrade(None, "", (UNCONFIRMED,)), "2018-12-09")]
    for bucket, last_trade, end in cases:
        ending = Ending(DelistingKey("BBGAET", "2018-12-09"), last_trade, bucket, None, "")
        history = _aet_history(ending, continuing)
        assert history.going_on == frozenset()
        assert history.end("BBGAET") == SecurityEnd(end, False, False)
        assert _aet_ranges(history)[0][2] == end


def test_an_ending_whose_successor_is_the_security_itself_does_not_clip_its_history():
    """A continuing exchange transfer keeps the same FIGI (D18): no end of the security, so its history runs to its
    last real sighting, not to the transfer's own date."""
    ending = _ending("BBGAET", "2018-12-09", CrspBucket.EXCHANGE_TRANSFER, date(2018, 11, 28), successor="BBGAET",
                     exchange="NASDAQ")
    history = _aet_history(ending)
    assert history.going_on == {ending.key}
    assert history.end("BBGAET") == SecurityEnd(None, False, False)
    assert _aet_ranges(history) == [("AET", "2017-06-30", "2018-11-29", None)]


def test_the_continues_after_rule_counts_the_tickers_the_line_follow_found():
    """U5 (sub-plan 5a): TEST's own CUSIP keeps trading as TSTN, a rename the line follow found, so the merger record
    is no real exit once TSTN is one of the security's own tickers."""
    era = TickerEra("TEST", "2007-12-01", "2019-03-29", [Observation("TEST", "2007-12-01", "TEST CO")])
    ending = _ending("BBGTEST", "2019-03-30", CrspBucket.MERGER, date(2019, 3, 29), source="ex99_notice")
    rows = _continuing_rows("TSTN", "11111T101", start="2019-04-01", count=20, step_days=4, prices=(110.0, 111.0))
    for line_tickers, going_on in ((frozenset(), frozenset()), (frozenset({"TSTN"}), {ending.key})):
        sec = Security("BBGTEST", 5, "COMMON", "TEST CO", "Common Stock", True, "cusip", eras=[era],
                       line_tickers=line_tickers)
        assert _history({"BBGTEST": sec}, rows, [ending], cusips={"BBGTEST": ["11111T101"]}).going_on == going_on


def test_the_last_ending_that_ends_the_security_sets_its_end_and_another_securitys_ending_is_not_read():
    went_on = _ending("BBGAET", "2016-05-02", CrspBucket.EXCHANGE_TRANSFER, date(2016, 4, 29), successor="BBGAET",
                      exchange="NASDAQ")
    merger = _ending("BBGAET", "2018-12-09", CrspBucket.MERGER, date(2018, 11, 28))
    other = _ending("BBGOTHER", "2019-01-02", CrspBucket.LIQUIDATION, date(2018, 12, 31))
    history = _history(_aet(), AET_ROWS, [merger, other, went_on], cusips={"BBGAET": [AET_CUSIP]})
    assert history.going_on == {went_on.key}
    assert history.end("BBGAET") == SecurityEnd("2018-11-28", True, False)
    assert _aet_ranges(history) == [("AET", "2017-06-30", "2018-11-28", "NYSE")]
    assert history.end("BBGOTHER") == SecurityEnd()


# A successor's ticker is not its predecessor's (Task 13b, sub-plan 5a)

OLD_CUSIP = "11111T101"


def _test_fails(n, start, step_days=10):
    dates = [(start + timedelta(days=i * step_days)).isoformat() for i in range(n)]
    return [FtdRow(d, OLD_CUSIP, "TEST", "TEST CO", 110.0 if i % 2 == 0 else 111.0) for i, d in enumerate(dates)]


def _successor_history(bucket, last_trade_day, successor_first, fails, *, delist_date="2012-03-31",
                       successor="BBGNEW", successor_ticker="TEST", observed_successor=True, listed_old=False):
    """S ("BBGOLD", own ticker TEST) with one ending whose successor X ("BBGNEW") is first sighted under
    `successor_ticker` on `successor_first` (an observed security listed today, else a line successor the run adds);
    `fails` are S's own CUSIP's rows. Returns the history and the ending."""
    era = TickerEra("TEST", "2007-12-01", "2012-03-30", [Observation("TEST", "2007-12-01", "TEST CO")])
    old = Security("BBGOLD", 5, "COMMON", "TEST CO", "Common Stock", True, "cusip", eras=[era],
                   line_tickers=frozenset({"TEST"}))
    new = Security("BBGNEW", 6, "COMMON", "TEST PLC", "Common Stock", True, "cusip")
    ending = _ending("BBGOLD", delist_date, bucket, last_trade_day, successor=successor, source="ex99_notice")
    securities, extra, added = {"BBGOLD": old}, {}, {}
    if observed_successor:
        securities["BBGNEW"] = new
        extra["BBGNEW"] = [Sighting(successor_first, successor_ticker, "observation")]
    else:
        added["BBGNEW"] = AddedLineSuccessor(new, successor_ticker, successor_first, [])
    history = _history(securities, fails, [ending], cusips={"BBGOLD": [OLD_CUSIP]}, extra=extra, added=added,
                       listed={"BBGOLD": listed_old, "BBGNEW": True})
    return history, ending


def _old_ranges(history):
    return [(r["ticker"], r["valid_to"]) for r in history.ticker_rows if r["sec_id"] == "BBGOLD"]


def test_a_successors_ticker_is_not_the_predecessors_AON_shape():
    """AON 2012: the old CUSIP's fails rows keep coming under TEST after the continuation took the ticker, at
    changing prices. They are the successor's: the continuation ends S (without the successor they would read as S
    trading on), its TEST range and its CUSIP's end at the last trade, the successor holds TEST from its first day
    and no ticker is shared."""
    fails = _test_fails(3, date(2012, 3, 1)) + _test_fails(20, date(2012, 4, 3), step_days=4)
    history, ending = _successor_history(CrspBucket.EXCHANGE_TRANSFER, date(2012, 3, 30), "2012-04-03", fails)
    assert history.going_on == frozenset()
    assert history.end("BBGOLD") == SecurityEnd("2012-03-30", True, False)
    assert _old_ranges(history) == [("TEST", "2012-03-30")]
    assert [r["valid_to"] for r in history.cusip_rows] == ["2012-03-30"]
    assert [(r["sec_id"], r["valid_from"], r["valid_to"]) for r in history.ticker_rows if r["sec_id"] == "BBGNEW"] \
        == [("BBGNEW", "2012-04-03", None)]
    assert ticker_range_review(history.ticker_rows) == []
    without, _ = _successor_history(CrspBucket.EXCHANGE_TRANSFER, date(2012, 3, 30), "2012-04-03", fails,
                                    successor=None)
    assert without.going_on == {ending.key}            # the old CUSIP's rows alone read as S trading on


def test_a_successors_ticker_is_not_the_predecessors_STX_shape():
    """STX 2021: a line successor (added) starts its ticker on 2021-05-19, before the predecessor's last sighting
    (the old CUSIP's settling tail under the same ticker), and the predecessor's last trade is undated. The
    predecessor's range ends the day before, beside the successor's own row."""
    tail = [FtdRow(d, OLD_CUSIP, "TEST", "TEST CO", 10.0) for d in ("2021-05-17", "2021-05-18", "2021-05-24",
                                                                    "2021-05-28")]
    history, _ = _successor_history(CrspBucket.EXCHANGE_TRANSFER, None, "2021-05-19", tail,
                                    delist_date="2021-05-28", observed_successor=False)
    assert _old_ranges(history) == [("TEST", "2021-05-18")]
    x = AddedLineSuccessor(Security("BBGNEW", 6, "COMMON", "T", "Common Stock", False, "cusip"), "TEST",
                           "2021-05-19", [])
    assert ticker_range_review(history.ticker_rows + [x.history_row(listed=True, exchange=None)]) == []


def test_a_successor_sighting_before_a_confirmed_last_trade_sets_no_start():
    """With a confirmed last trade day D, a successor's TEST sighting 10 days before D is not the start: the start
    is X's first sighting on or after D, so S's range still reaches D, with the exchange it left."""
    history, _ = _successor_history(CrspBucket.EXCHANGE_TRANSFER, date(2012, 3, 30), "2012-03-20",
                                    _test_fails(3, date(2012, 3, 1)))
    assert [(r["ticker"], r["valid_to"], r["exchange"]) for r in history.ticker_rows if r["sec_id"] == "BBGOLD"] \
        == [("TEST", "2012-03-30", "NYSE")]


def test_a_security_whose_ticker_its_successor_took_is_not_listed_today_AON_2012():
    """AON 2012: the old line's issuer (same CIK) still lists the ticker the new line took, so S reads as listed
    today. A security with an ending that ends it whose ticker a successor took is not listed: the issuer's listing
    is the successor's, and S is clipped at its last trade. A ticker first sighted under X later than the window
    (200 days after a confirmed last trade: a recycled ticker), or an ending with no day to bound it (a blank delist
    date, no last trade: no start, and nothing raised), leaves S listed today."""
    fails = _test_fails(3, date(2012, 3, 1))
    took, _ = _successor_history(CrspBucket.EXCHANGE_TRANSFER, date(2012, 3, 30), "2012-04-03", fails,
                                 listed_old=True)
    assert took.end("BBGOLD") == SecurityEnd("2012-03-30", True, False)
    assert _old_ranges(took) == [("TEST", "2012-03-30")]
    recycled, _ = _successor_history(CrspBucket.EXCHANGE_TRANSFER, date(2012, 3, 30), "2012-10-16", fails,
                                     listed_old=True)
    assert recycled.end("BBGOLD") == SecurityEnd(None, False, True)
    assert _old_ranges(recycled) == [("TEST", None)]
    blank, _ = _successor_history(CrspBucket.EXCHANGE_TRANSFER, None, "2012-04-03", fails, delist_date="",
                                  listed_old=True)
    assert blank.end("BBGOLD") == SecurityEnd(None, False, True)
    stx_window, _ = _successor_history(CrspBucket.EXCHANGE_TRANSFER, None, "2021-05-19", fails,
                                       observed_successor=False, listed_old=True)
    assert stx_window.end("BBGOLD").listed is True          # a 2012 delist date: X's 2021 first day is out of window


def test_a_listed_security_that_goes_on_ends_its_open_range_the_day_before_its_successor_takes_the_ticker():
    """S trades on under its own CUSIP past the transfer (so it goes on and stays listed), and its successor takes
    TEST 94 days after the last trade: S's open TEST range ends the day before."""
    fails = _test_fails(20, date(2012, 4, 3), step_days=4)
    history, ending = _successor_history(CrspBucket.EXCHANGE_TRANSFER, date(2012, 3, 30), "2012-07-02", fails,
                                         listed_old=True)
    assert history.going_on == {ending.key}
    assert history.end("BBGOLD") == SecurityEnd(None, False, True)
    assert _old_ranges(history) == [("TEST", "2012-07-01")]


def test_a_successor_on_another_ticker_changes_nothing_MWV_shape():
    """MWV -> WRK: the successor trades under another ticker, so S's own TEST rows are all S's: they still read as
    S trading on."""
    fails = _test_fails(20, date(2012, 4, 3), step_days=4)
    history, ending = _successor_history(CrspBucket.MERGER, date(2012, 3, 30), "2012-04-03", fails,
                                         successor_ticker="WRK")
    assert history.going_on == {ending.key}


def test_a_security_that_is_its_own_successor_keeps_every_row_WRK_shape():
    """A delisting whose successor is the security itself takes no ticker from it: its rows are all its own, and
    its range runs to its last row."""
    fails = _test_fails(20, date(2012, 4, 3), step_days=4)
    history, ending = _successor_history(CrspBucket.MERGER, date(2012, 3, 30), "2012-04-03", fails,
                                         successor="BBGOLD", observed_successor=False)
    assert history.going_on == {ending.key}
    assert _old_ranges(history) == [("TEST", fails[-1].date)]


def test_ranges_end_at_the_last_ending_or_stay_open_while_listed():
    """The range that ends at the end carries the exchange the ending left; an open range the exchange EDGAR lists
    for its ticker today, asked only for an open range and only when the rows are read."""
    eras = [TickerEra("X", "2020-01-02", "2020-01-02", [Observation("X", "2020-01-02", "X CO", cusip="111111111")]),
            TickerEra("XX", "2020-06-30", "2021-01-04", [Observation("XX", "2020-06-30", "X CO"),
                                                          Observation("XX", "2021-01-04", "X CO",
                                                                      cusip="111111111")])]
    sec = {"BBGX": Security("BBGX", 1, "COMMON", "X CO", "Common Stock", True, "cusip", eras=eras)}
    ending = _ending("BBGX", "2020-12-31", CrspBucket.LIQUIDATION, date(2020, 12, 31))
    asked = []

    def today(security, ticker):
        asked.append((security.sec_id, ticker))
        return "NASDAQ"

    history = _history(sec, [], [ending], cusips={}, listed={"BBGX": False}, exchange_today=today)
    assert [(r["ticker"], r["valid_from"], r["valid_to"], r["exchange"]) for r in history.ticker_rows] == [
        ("X", "2020-01-02", "2020-06-29", None), ("XX", "2020-06-30", "2020-12-31", "NYSE")]
    assert [(r["cusip"], r["valid_to"]) for r in history.cusip_rows] == [("111111111", "2020-12-31")]
    assert asked == []
    listed = _history(sec, [], [ending], cusips={}, listed={"BBGX": True}, exchange_today=today)
    assert asked == []
    assert (listed.ticker_rows[-1]["valid_to"], listed.ticker_rows[-1]["exchange"], asked) == (
        None, "NASDAQ", [("BBGX", "XX")])

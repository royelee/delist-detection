"""A security's trading record (architecture step 14), at its interface: its two constructors (a security of the run
over its observations and its own CUSIPs' fails rows; a successor the run added, over its span), and what it works
out from them -- the ticker on a day, the last own-ticker sighting, sightings after a day, its span as a sibling,
every ticker of a window, trading after a day and near a day under any symbol, its CUSIP switches, the class letter
its descriptions name, rule 3's tenure and the rows' last trading day."""
from datetime import date

from delist_detection.sources.ftd import FtdIndex, FtdRow
from delist_detection.identity.history import Sighting
from delist_detection.identity.observations import Observation, TickerEra
from delist_detection.identity.security_master import Security
from delist_detection.endings.trading_record import TradingRecord, last_row_trade_day, ticker_taken


def _security(ticker="AET", first="2017-06-30", last="2018-06-29", name="AETNA INC", *, sec_id="BBG000FJLFX8",
              share_class="COMMON", line_tickers=frozenset()):
    era = TickerEra(ticker, first, last, [Observation(ticker, first, name), Observation(ticker, last, name)])
    return Security(sec_id, 1122304, share_class, name, "Common Stock", True, "cusip", eras=[era],
                    line_tickers=frozenset(line_tickers))


AET_ROWS = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0),
            FtdRow("2018-11-29", "00817Y108", "AET", "AETNA INC.(NEW)", 212.70),
            FtdRow("2019-06-01", "00817Y108", "AETQ", "AETNA INC OTC PINK", 0.05)]


def _aet(rows=AET_ROWS):
    return TradingRecord.observed(_security(), FtdIndex(rows), ["00817Y108"])


# -- an observed security: its sightings ---------------------------------------------------------------------------
def test_an_observed_securitys_sightings_are_its_observations_and_its_own_cusips_fails_rows():
    rec = _aet()
    assert [(s.day, s.value, s.source) for s in rec.sightings] == [
        ("2017-06-30", "AET", "observation"), ("2018-06-29", "AET", "ftd"), ("2018-06-29", "AET", "observation"),
        ("2018-07-02", "AET", "ftd"), ("2018-11-29", "AET", "ftd"), ("2019-06-01", "AETQ", "ftd")]
    assert (rec.ticker, rec.known_from, rec.known_until, rec.expected_name) == (
        "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    assert rec.cusips == ("00817Y108",) and rec.has_cusips
    assert not TradingRecord.observed(_security(), FtdIndex([]), []).has_cusips


def test_the_last_sighting_is_the_last_under_an_own_ticker_not_the_otc_tail():
    """A bankrupt XYZ's CUSIP keeps failing under XYZQ after the real delisting: the last sighting stays at the last
    one under its own ticker, while a sighting after a day still counts the tail."""
    rec = _aet()
    assert rec.last_seen == "2018-11-29"
    assert rec.seen_after("2019-01-01") and not rec.seen_after("2019-12-31")


def test_the_last_sighting_falls_back_to_its_last_eras_end_with_no_own_ticker_sighting():
    sec = _security("XYZ", "2020-01-01", "2020-06-15", "XYZ CORP")
    rec = TradingRecord(sec, [Sighting("2020-07-01", "XYZQ", "ftd")], known_until="2020-06-15")
    assert rec.last_seen == "2020-06-15"
    assert TradingRecord.observed(sec, FtdIndex([]), [], sightings=[]).last_seen == "2020-06-15"


def test_a_ticker_the_line_follow_found_is_its_own():
    """Harsco renamed itself Enviri (NVRI) in 2023 on the same CUSIP: once the line follow adds NVRI, the
    security's last own sighting is its last NVRI row, not its last HSC one."""
    sig = [Sighting("2023-06-20", "HSC", "ftd"), Sighting("2024-01-02", "NVRI", "ftd")]
    hsc = _security("HSC", "2008-01-16", "2023-06-20", "HARSCO CORP")
    assert TradingRecord.observed(hsc, FtdIndex([]), [], sightings=sig).last_seen == "2023-06-20"
    nvri = _security("HSC", "2008-01-16", "2023-06-20", "HARSCO CORP", line_tickers={"NVRI"})
    rec = TradingRecord.observed(nvri, FtdIndex([]), [], sightings=sig)
    assert rec.last_seen == "2024-01-02" and rec.own_tickers == {"HSC", "NVRI"}


def test_a_fails_row_under_an_own_ticker_shows_trading_an_observation_does_not():
    """Not the OTC tail, not an observation: a stale snapshot can list a security long after it was acquired."""
    rec = _aet()
    assert rec.seen_in_fails_after("2018-11-28") and not rec.seen_in_fails_after("2018-11-29")
    assert rec.seen_in_fails_after("2017-01-01")
    alone = TradingRecord.observed(_security(), FtdIndex([]), [])
    assert alone.seen_after("2018-01-01") and not alone.seen_in_fails_after("2018-01-01")


def test_the_ticker_on_a_day_is_the_latest_sighting_on_or_before_it():
    rec = TradingRecord(_security(), [Sighting("2021-12-31", "FB", "observation"),
                                      Sighting("2022-06-09", "META", "ftd")])
    assert rec.ticker_on("2022-06-08") == "FB" and rec.ticker_on("2022-06-09") == "META"
    assert rec.ticker_on("2030-01-01") == "META"


def test_a_day_before_every_sighting_takes_the_first_and_none_without_sightings():
    assert TradingRecord(_security(), [Sighting("2021-12-31", "FB", "observation")]).ticker_on("2000-01-01") == "FB"
    assert TradingRecord(_security(), []).ticker_on("2021-12-31") is None


def test_the_tickers_of_a_window_are_every_ticker_sighted_in_it_in_order():
    """Spirit Airlines 2024: by its Form 25 the shares traded OTC as SAVEQ."""
    rec = _aet()
    assert rec.tickers("2018-06-01", "2019-12-31") == ["AET", "AETQ"]
    assert rec.tickers("2019-01-01", "2019-12-31") == ["AETQ"]


def test_a_siblings_span_runs_from_its_first_sighting_to_its_last_own_one():
    assert _aet().span == ("2017-06-30", "2018-11-29")        # not the 2019-06-01 OTC tail
    assert TradingRecord(_security(), []).span is None         # no span known: alive at every filing


# -- an observed security: its own CUSIPs' fails rows ----------------------------------------------------------------
def _rhd(rows, cusip="74955W307"):
    return TradingRecord.observed(_security("RHD", "2008-01-16", "2008-12-31", "R H DONNELLEY CORP",
                                            sec_id="BBG_RHD"), FtdIndex(rows), [cusip])


def test_trading_after_a_day_is_read_from_its_own_cusip_under_any_symbol():
    """R.H. Donnelley's CUSIP traded OTC as RHDC: rows over enough days at two prices are trading after a day."""
    days = [f"2009-02-{d:02d}" for d in range(2, 28)]
    rows = [FtdRow(d, "74955W307", "RHDC", "R H DONNELLEY CORP", 1.0 + (i % 2) / 10) for i, d in enumerate(days)]
    rec = _rhd(rows)
    assert rec.trades_after("2009-01-31") and not rec.trades_after("2009-02-10")
    assert not _rhd(rows, cusip="OTHERCUSP").trades_after("2009-01-31")


def test_its_own_cusip_traded_within_the_days_up_to_a_day():
    """Monster Worldwide 2016: the late reach's 30 days up to a Form 25."""
    rows = [FtdRow("2016-10-03", "74955W307", "MWW", "MONSTER WORLDWIDE", 3.3),
            FtdRow("2016-10-31", "74955W307", "MWW", "MONSTER WORLDWIDE", 3.4)]
    rec = _rhd(rows)
    assert rec.traded_within("2016-11-01", 30) and rec.traded_within("2016-10-31", 30)
    assert not rec.traded_within("2016-12-01", 30) and not rec.traded_within("2016-10-02", 30)


def test_unassigned_and_pair_off_rows_are_no_trading_near_a_day():
    """Final review M6: `ZZZZ` and pair-off symbols are no trading (`ftd.is_trading_symbol`)."""
    rows = [FtdRow("2016-10-31", "74955W307", "MWWZZZZ", "MONSTER WORLDWIDE", 3.4),
            FtdRow("2016-10-31", "74955W307", "M104PAIROFF", "MONSTER WORLDWIDE", 3.4)]
    assert not _rhd(rows).traded_within("2016-11-01", 30)


def test_its_cusip_switches_are_each_later_cusips_first_sighting():
    """QGEN 2026: a new CUSIP on its own line, after the first."""
    rows = [FtdRow("2025-12-01", "N72482123", "QGEN", "QIAGEN NV", 45.0),
            FtdRow("2026-01-07", "N72482149", "QGEN", "QIAGEN NV NEW", 46.0),
            FtdRow("2026-01-08", "N72482149", "QGEN", "QIAGEN NV NEW", 46.5)]
    rec = TradingRecord.observed(_security("QGEN", "2025-06-30", "2026-06-30", "QIAGEN NV"), FtdIndex(rows),
                                 ["N72482123", "N72482149"])
    assert rec.cusip_switches == ("2026-01-07",)
    assert TradingRecord(_security(), cusips=("N72482123",)).cusip_switches == ()     # no fails index


def test_a_letterless_class_takes_the_letter_its_own_cusips_fails_descriptions_name():
    """R2: SunPower's class A placeholder, "SUNPOWER CORP CL A"; a lettered class keeps its own letter."""
    ftd = FtdIndex([FtdRow("2011-06-01", "867652109", "SPWRA", "SUNPOWER CORP CL A", 20.0),
                    FtdRow("2011-06-01", "867652307", "SPWRB", "SUNPOWER CORP CL B", 19.0)])
    plain = Security("CIK867773-COMMON", 867773, "COMMON", "SUNPOWER CORP", "", True, "placeholder")
    lettered = Security("BBG_B", 867773, "CLASS B", "SUNPOWER CORP CL B", "", True, "cusip")
    assert TradingRecord.observed(plain, ftd, ["867652109"]).letter_hint == "A"
    assert TradingRecord.observed(lettered, ftd, ["867652307"]).letter_hint is None
    assert TradingRecord.observed(plain, ftd, []).letter_hint is None


# -- rule 3's tenure and the rows' last day --------------------------------------------------------------------------
OWN = {"OWNCUSIP1"}


def _ftd(day, cusip, price, symbol="TKR"):
    return FtdRow(day, cusip, symbol, "SOME CORP", price)


def _taken(rows):
    return ticker_taken(FtdIndex(rows), "TKR", OWN, "2019-03-01", "2019-04-30")


def test_the_ticker_is_taken_the_day_before_another_cusips_first_priced_row_after_the_own_last_row():
    rows = [_ftd("2019-03-04", "OWNCUSIP1", 10.0), _ftd("2019-03-05", "OWNCUSIP1", 10.5),
            _ftd("2019-03-07", "OTHERCUSP", 48.9)]
    assert _taken(rows) == "2019-03-06"          # a row carries the close of the trading day before it
    trading = TradingRecord(_security(), (), tuple(OWN), FtdIndex(rows))
    assert trading.taken("TKR", "2019-03-01", "2019-04-30") == "2019-03-06"
    assert TradingRecord(_security(), (), tuple(OWN)).taken("TKR", "2019-03-01", "2019-04-30") is None   # no index


def test_another_cusips_row_between_the_own_rows_takes_nothing():
    rows = [_ftd("2019-03-04", "OWNCUSIP1", 10.0), _ftd("2019-03-06", "OTHERCUSP", 48.9),
            _ftd("2019-03-08", "OWNCUSIP1", 10.5), _ftd("2019-03-12", "OTHERCUSP", 49.0)]
    assert _taken(rows) == "2019-03-11"


def test_a_row_at_or_below_a_cent_is_no_trade():
    """APA 2021: the new CUSIP's $0.01 first row beside the own row carrying the last close."""
    assert _taken([_ftd("2019-03-04", "OWNCUSIP1", 10.0), _ftd("2019-03-05", "OTHERCUSP", 0.01)]) is None


def test_no_own_row_under_the_ticker_gives_no_bound():
    """BTU 2016, CHK 2020: the own CUSIPs have no row under the ticker in the window."""
    assert _taken([_ftd("2019-03-05", "OTHERCUSP", 48.9)]) is None


def test_the_rows_last_trading_day_is_the_day_before_the_last_one_price_run_of_the_last_cusip():
    """AVGO 2018: the last CUSIP's fails settle at one price from 04-05, so it last traded on 04-04."""
    rows = [_ftd("2018-03-29", "OLDCUSIP1", 250.0), _ftd("2018-04-02", "OWNCUSIP1", 251.0),
            _ftd("2018-04-05", "OWNCUSIP1", 252.5), _ftd("2018-04-09", "OWNCUSIP1", 252.5)]
    assert last_row_trade_day(rows) == "2018-04-04"
    assert TradingRecord(_security(), (), ("OLDCUSIP1", "OWNCUSIP1"), FtdIndex(rows)).trades_until() == "2018-04-04"
    assert last_row_trade_day([]) is None
    assert _aet().trades_until() is not None and TradingRecord(_security()).trades_until() is None


# -- a successor the run added: its span, no era -----------------------------------------------------------------
def test_an_added_successor_is_known_over_its_span_under_its_own_ticker():
    """Stage 9d: TiVo Corp, Rovi's 8-K12B successor, known from its 8-K12B to the run date, no era made up."""
    sec = Security("BBG000NEWLN1", 777001, "COMMON", "NEWCO CORP", "Common Stock", False, "ticker")
    rows = [FtdRow("2020-01-15", "65249B109", "NEWC", "NEWCO CORP", 11.0),
            FtdRow("2020-02-14", "65249B109", "NEWCZZZZ", "NEWCO CORP", 11.0)]
    rec = TradingRecord.added(sec, "NEWC", ("2016-09-08", "2026-09-25"), FtdIndex(rows), ["65249B109"])
    assert [(s.day, s.value, s.source) for s in rec.sightings] == [
        ("2016-09-08", "NEWC", "span"), ("2020-01-15", "NEWC", "ftd"), ("2026-09-25", "NEWC", "span")]
    assert (rec.ticker, rec.known_from, rec.known_until, rec.expected_name) == (
        "NEWC", "2016-09-08", "2026-09-25", "NEWCO CORP")
    assert rec.own_tickers == {"NEWC"} and rec.last_seen == "2026-09-25" and sec.eras == []
    assert rec.span == ("2016-09-08", "2026-09-25") and rec.cusips == ("65249B109",)
    one_day = TradingRecord.added(sec, "NEWC", ("2016-09-08", "2016-09-08"), FtdIndex([]), [])
    assert [s.day for s in one_day.sightings] == ["2016-09-08"] and not one_day.has_cusips
    assert date.fromisoformat(one_day.last_seen) == date(2016, 9, 8)

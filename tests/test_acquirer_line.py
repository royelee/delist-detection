"""acquirer_line: a merger's acquirer as a line of the run, its symbol and its price on the price date (sub-plan 5e).
Synthetic fails rows shaped like the real cases (CAL/UAL 2010, RTN/RTX 2020, ABI/Life Technologies 2008,
GLIBA/Liberty Broadband 2020); the real cases themselves are in tests/test_acquirer_gate_cases.py."""
from datetime import date

from delist_detection.acquirer_line import (
    LineIndex, choose_line, is_placeholder_row, issuer_by_name, issuer_by_ticker, named_class,
)
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.history import Sighting
from delist_detection.security_master import Security

L, P = date(2010, 9, 30), date(2010, 10, 1)     # CAL's last trade and price date


def _sec(sid, cik, share_class="COMMON"):
    return Security(sid, cik, share_class, sid, "Common Stock", True, "cusip")


def _rows(*specs):
    return [FtdRow(d, c, s, "X", p) for d, c, s, p in specs]


def _index(secs, sightings, cusips, rows):
    return LineIndex({s.sec_id: s for s in secs}, sightings, cusips, FtdIndex(rows))


def _cal():
    """UAL Corp: the old line (placeholder) under UAUA on CUSIP 902549807, the new one under UAL on 910047109 from
    the closing day, its first row the $0.01 placeholder."""
    secs = [_sec("CIK100517-COMMON", 100517), _sec("BBG000M65M61", 100517), _sec("TARGET", 319687)]
    sightings = {
        "CIK100517-COMMON": [Sighting("2010-09-20", "UAUA", "ftd"), Sighting("2010-10-12", "UAUA", "ftd")],
        "BBG000M65M61": [Sighting("2010-10-01", "UAL", "ftd"), Sighting("2010-10-12", "UAL", "ftd")],
        "TARGET": [Sighting("2010-09-20", "CAL", "ftd"), Sighting("2010-09-30", "CAL", "ftd")],
    }
    cusips = {"CIK100517-COMMON": ["902549807"], "BBG000M65M61": ["910047109"], "TARGET": ["210795308"]}
    rows = _rows(("2010-09-29", "902549807", "UAUA", 23.02), ("2010-09-30", "902549807", "UAUA", 23.41),
                 ("2010-10-08", "902549807", "UAUA", 25.72), ("2010-10-12", "902549807", "UAUA", 26.04),
                 ("2010-10-01", "910047109", "UAL", 0.01), ("2010-10-04", "910047109", "UAL", 24.70),
                 ("2010-10-05", "910047109", "UAL", 24.10), ("2010-10-12", "910047109", "UAL", 26.04))
    return _index(secs, sightings, cusips, rows)


def test_a_first_row_at_a_penny_or_a_dollar_is_a_placeholder():
    rows = _rows(("2019-06-11", "G0250X107", "AMCR", 1.0), ("2019-06-12", "G0250X107", "AMCR", 11.18))
    assert is_placeholder_row(rows, 0) and not is_placeholder_row(rows, 1)
    rows = _rows(("2010-10-01", "910047109", "UAL", 0.01), ("2010-10-04", "910047109", "UAL", 24.70))
    assert is_placeholder_row(rows, 0)
    # a real dollar stock is no placeholder; neither is a priced row under an unassigned symbol's successor
    rows = _rows(("2020-01-02", "123456789", "PNY", 1.0), ("2020-01-03", "123456789", "PNY", 1.02))
    assert not is_placeholder_row(rows, 0)
    rows = _rows(("2016-09-06", "G51502105", "JCIZZZZ", 47.74), ("2016-09-07", "G51502105", "JCI", 48.90))
    assert is_placeholder_row(rows, 0) and not is_placeholder_row(rows, 1)


def test_the_holder_of_the_terms_ticker_on_the_last_trade_day():
    idx = _cal()
    assert idx.holder("UAUA", L, P, exclude="TARGET") == "CIK100517-COMMON"
    assert idx.holder("CAL", L, P, exclude="TARGET") is None              # the target itself is never the acquirer
    # a new holding company's ticker starts on the price date (JHG 2017-05-30)
    assert idx.holder("UAL", L, P, exclude="TARGET") == "BBG000M65M61"


def test_a_ticker_handed_to_a_new_holder_at_the_closing_is_the_new_holders():
    """WCRX 2013: Actavis Inc held ACT until the last trade day; Actavis plc, the holding company Warner Chilcott's
    holders received shares of, held it from the day after the price date."""
    secs = [_sec("CIK884629-COMMON", 884629), _sec("BBG000FH8PX5", 1578845), _sec("TARGET", 1323854)]
    sightings = {"CIK884629-COMMON": [Sighting("2013-01-25", "ACT", "observation"),
                                      Sighting("2013-09-30", "ACT", "observation")],
                 "BBG000FH8PX5": [Sighting("2013-10-02", "ACT", "observation"),
                                  Sighting("2013-12-31", "ACT", "observation")]}
    idx = _index(secs, sightings, {}, [])
    assert idx.holder("ACT", date(2013, 9, 30), date(2013, 10, 1), exclude="TARGET") == "BBG000FH8PX5"
    # a hold that runs past the price date stands (CAL: UAUA's fails rows to 2010-10-15)
    assert _cal().holder("UAUA", L, P, exclude="TARGET") == "CIK100517-COMMON"


def test_a_holders_issuer_must_have_filed_by_the_last_trade_and_carry_the_acquirer_name():
    """ASD 2008: the run's IR line from 2007 belongs to CIK 1699150 (Ingersoll Rand Inc, first filed in 2017), a
    security-master error the acquirer must not inherit; a name that agrees with none of its EDGAR names fails too."""
    from delist_detection.acquirer_line import issuer_fits
    subs = _subs({1699150: {"name": "Ingersoll Rand Inc.", "formerNames": []},
                  100517: {"name": "United Airlines Holdings, Inc.",
                           "formerNames": [{"name": "UAL CORP /DE/", "from": "1994-01-01", "to": "2019-06-27"}]}})
    first = {1699150: date(2017, 3, 1), 100517: date(1994, 1, 1)}.get
    assert not issuer_fits(subs, first, 1699150, "Ingersoll Rand", date(2008, 6, 5))
    assert issuer_fits(subs, first, 100517, "UAL Corporation", L)
    assert not issuer_fits(subs, first, 100517, "Continental Airlines", L)
    assert issuer_fits(subs, first, 100517, "", L)                   # no name to check
    assert issuer_fits(subs, lambda cik: None, 100517, "UAL Corporation", L)   # an unknown first filing


def test_the_line_whose_cusip_begins_at_the_closing_is_chosen_over_the_tickers_old_line():
    idx = _cal()
    assert idx.closing_cusip("BBG000M65M61", L, P) == "910047109"
    assert idx.closing_cusip("CIK100517-COMMON", L, P) is None
    got = choose_line(idx, 100517, holder="CIK100517-COMMON", letter=None, last=L, price_day=P, exclude="TARGET")
    assert got == "BBG000M65M61"


def test_the_price_of_a_closing_cusip_is_its_close_on_the_price_date_past_the_placeholder():
    idx = _cal()
    assert idx.price("BBG000M65M61", L, P) == (24.70, "2010-10-04", False)
    assert idx.symbol_on("BBG000M65M61", P) == "UAL"


def _rtn():
    """RTX: UTC's line keeps its old CUSIP's fails rows at the pre-spin close after the closing; the new CUSIP
    begins on the price date."""
    secs = [_sec("BBG000BW8S60", 101829), _sec("TARGET", 1047122)]
    sightings = {"BBG000BW8S60": [Sighting("2020-03-20", "UTX", "ftd"), Sighting("2020-04-08", "UTX", "ftd"),
                                  Sighting("2020-04-09", "RTX", "ftd")]}
    cusips = {"BBG000BW8S60": ["913017109", "75513E101"]}
    rows = _rows(("2019-01-02", "913017109", "UTX", 100.0), ("2020-04-02", "913017109", "UTX", 91.37), ("2020-04-03", "913017109", "UTX", 86.01),
                 ("2020-04-06", "913017109", "UTX", 86.01), ("2020-04-07", "913017109", "UTX", 86.01),
                 ("2020-04-03", "75513E101", "RTX", 86.01), ("2020-04-06", "75513E101", "RTX", 49.93),
                 ("2020-04-07", "75513E101", "RTX", 57.56))
    return _index(secs, sightings, cusips, rows)


def test_a_line_that_changes_cusip_at_the_closing_is_priced_and_named_by_the_new_cusip():
    idx = _rtn()
    last, day = date(2020, 4, 2), date(2020, 4, 3)
    assert idx.holder("UTX", last, day, exclude="TARGET") == "BBG000BW8S60"
    assert idx.closing_cusip("BBG000BW8S60", last, day) == "75513E101"
    assert idx.price("BBG000BW8S60", last, day) == (49.93, "2020-04-06", False)
    assert idx.symbol_on("BBG000BW8S60", day) == "RTX"


def test_without_a_closing_cusip_the_price_is_the_close_of_the_last_trade_day():
    rows = _rows(("2012-06-01", "527288104", "LUK", 20.00), ("2013-02-28", "527288104", "LUK", 26.73), ("2013-03-01", "527288104", "LUK", 26.90),
                 ("2013-03-04", "527288104", "LUK", 26.40))
    idx = _index([_sec("BBG000BNHSP9", 96223)], {"BBG000BNHSP9": [Sighting("2007-12-28", "LUK", "observation"),
                                                                  Sighting("2013-03-04", "LUK", "ftd")]},
                 {"BBG000BNHSP9": ["527288104"]}, rows)
    last, day = date(2013, 2, 28), date(2013, 3, 1)
    assert idx.closing_cusip("BBG000BNHSP9", last, day) is None
    assert idx.price("BBG000BNHSP9", last, day) == (26.90, "2013-03-01", False)
    assert idx.symbol_on("BBG000BNHSP9", day) == "LUK"


def test_the_symbol_is_that_of_the_row_the_price_is_read_from():
    """A fails row dated D carries D-1's close, and a CUSIP that began at the closing moves positions on its own day:
    ABI 2008 (Invitrogen renamed Life Technologies): the row dated the price date is the old CUSIP under IVGN, the
    row its price is read from, a day later, the new CUSIP under LIFE. JCI 2016: Tyco's old CUSIP under TYC on the
    price date, the new one under JCI from the next day (its first row under JCIZZZZ is no ticker)."""
    last, day = date(2008, 11, 21), date(2008, 11, 24)
    rows = _rows(("2008-11-20", "46185R100", "IVGN", 21.50), ("2008-11-24", "46185R100", "IVGN", 22.23),
                 ("2008-11-25", "53217V109", "LIFE", 23.89))
    idx = _index([_sec("BBG000CKJ0P3", 1073431)], {}, {"BBG000CKJ0P3": ["46185R100", "53217V109"]}, rows)
    assert idx.closing_cusip("BBG000CKJ0P3", last, day) == "53217V109"
    assert idx.symbol_on("BBG000CKJ0P3", day, last=last) == "LIFE"
    assert idx.price("BBG000CKJ0P3", last, day) == (23.89, "2008-11-25", False)
    last, day = date(2016, 9, 2), date(2016, 9, 6)
    rows = _rows(("2016-08-02", "G91442106", "TYC", 44.00), ("2016-09-02", "G91442106", "TYC", 45.00), ("2016-09-06", "G91442106", "TYC", 45.59),
                 ("2016-09-06", "G51502105", "JCIZZZZ", 47.74), ("2016-09-07", "G51502105", "JCI", 48.90))
    idx = _index([_sec("BBG000BKJCI0", 833444)], {}, {"BBG000BKJCI0": ["G91442106", "G51502105"]}, rows)
    assert idx.symbol_on("BBG000BKJCI0", day, last=last) == "JCI"
    assert idx.price("BBG000BKJCI0", last, day) == (48.90, "2016-09-07", False)


def test_a_line_without_a_closing_cusip_keeps_the_symbol_of_the_row_dated_the_price_date():
    """AVB 2026: the same CUSIP is renamed (Vivmark) only from 08-19, a day after the price date's row."""
    last, day = date(2026, 8, 14), date(2026, 8, 17)
    rows = _rows(("2026-08-03", "26884U109", "EQR", 69.0), ("2026-08-14", "26884U109", "EQR", 70.0), ("2026-08-17", "26884U109", "EQR", 70.5),
                 ("2026-08-18", "26884U109", "EQR", 70.6), ("2026-08-19", "26884U109", "VMRK", 70.7))
    idx = _index([_sec("BBG000BG8M31", 906107)], {}, {"BBG000BG8M31": ["26884U109"]}, rows)
    assert idx.closing_cusip("BBG000BG8M31", last, day) is None
    assert idx.symbol_on("BBG000BG8M31", day, last=last) == "EQR"
    assert idx.symbol_on("BBG000BG8M31", day) == "EQR"


def test_the_class_the_terms_name_picks_among_an_issuers_lines():
    q = ("each share of GCI Liberty Series A common stock... was automatically converted into the right to receive "
         "0.580 of a share of Liberty Broadband Series C common stock")
    assert named_class(q) == "C"
    assert named_class("Continental stockholders will receive 1.05 shares of UAL common stock for each share of "
                       "Continental Class B common stock") is None
    # the quote must be about the target's own class: Viacom class B shares the class A read (VIA-B 2019)
    via = ("each share of Class A common stock of Viacom was converted automatically into 0.59625 shares of "
           "ViacomCBS Class A Common Stock")
    assert named_class(via) == "A" and named_class(via, "A") == "A" and named_class(via, "B") is None
    secs = [_sec("BBG006GNRZ83", 1611983, "SERIES A"), _sec("BBG006GNSZW5", 1611983, "SERIES C")]
    rows = _rows(("2020-12-21", "530307107", "LBRDA", 157.10), ("2020-12-21", "530307305", "LBRDK", 157.88),
                 ("2020-12-22", "530307305", "LBRDK", 159.01))
    idx = _index(secs, {}, {"BBG006GNRZ83": ["530307107"], "BBG006GNSZW5": ["530307305"]}, rows)
    last, day = date(2020, 12, 18), date(2020, 12, 21)
    assert choose_line(idx, 1611983, holder="BBG006GNRZ83", letter="C", last=last, price_day=day,
                       exclude="T") == "BBG006GNSZW5"
    # without a class the ticker's own line stands
    assert choose_line(idx, 1611983, holder="BBG006GNRZ83", letter=None, last=last, price_day=day,
                       exclude="T") == "BBG006GNRZ83"


def test_two_live_lines_and_no_evidence_choose_nothing():
    secs = [_sec("A", 1, "SERIES A"), _sec("C", 1, "SERIES C")]
    rows = _rows(("2020-12-21", "AAAAAAAA1", "XA", 10.0), ("2020-12-21", "CCCCCCCC1", "XC", 10.0))
    idx = _index(secs, {}, {"A": ["AAAAAAAA1"], "C": ["CCCCCCCC1"]}, rows)
    assert choose_line(idx, 1, holder=None, letter=None, last=date(2020, 12, 18), price_day=date(2020, 12, 21),
                       exclude="T") is None


class _Resolver:
    def __init__(self, answers):
        self.answers = answers

    def resolve(self, ticker, observed_date=None, **kw):
        from delist_detection.ticker_resolver import TickerResolution
        return TickerResolution(ticker, self.answers.get(ticker), None, "test")


def _subs(table):
    return lambda cik: table.get(cik)


def test_the_resolvers_issuer_is_taken_when_its_edgar_names_agree_and_it_is_not_the_target():
    subs = _subs({878560: {"name": "CalAtlantic Group, Inc.", "formerNames": [
        {"name": "STANDARD PACIFIC CORP /DE/", "from": "1994-01-01", "to": "2015-10-01"}]}})
    r = _Resolver({"SPF": 878560})
    assert issuer_by_ticker(r, subs, "SPF", "Standard Pacific Corp.", date(2015, 9, 30), target_cik=1) == 878560
    assert issuer_by_ticker(r, subs, "SPF", "Lennar Corporation", date(2015, 9, 30), target_cik=1) is None
    assert issuer_by_ticker(r, subs, "SPF", "Standard Pacific Corp.", date(2015, 9, 30), target_cik=878560) is None


def test_a_name_without_a_ticker_names_the_one_issuer_of_the_run_that_carried_it_then():
    """GXP 2018: the LLM names 'Monarch Energy Holding, Inc.', Evergy's name until the closing; GCI 2019: three
    issuers carried 'Gannett Co., Inc.', the target and TEGNA (until 2015) among them, so none is taken."""
    subs = _subs({
        1711269: {"name": "Evergy, Inc.", "formerNames": [
            {"name": "Monarch Energy Holding, Inc.", "from": "2017-01-01", "to": "2018-06-04"}]},
        1206264: {"name": "Somnigroup International Inc.", "formerNames": []},
        893538: {"name": "SM Energy Co", "formerNames": []},           # agrees on ENERGY alone: a weaker match
        2067876: {"name": "Versant Media Group, Inc.", "formerNames": []},
        1354513: {"name": "CTC Media, Inc.", "formerNames": []},
        39899: {"name": "TEGNA INC", "formerNames": [{"name": "GANNETT CO INC /DE/", "from": "1994-01-01",
                                                      "to": "2015-06-29"}]},
        1635718: {"name": "Gannett Media Corp.", "formerNames": [{"name": "Gannett Co., Inc.", "from": "2015-06-01",
                                                                  "to": "2019-11-19"}]},
    })
    ciks = [1711269, 1206264, 39899, 1635718, 893538, 2067876, 1354513]
    last, day = date(2018, 6, 4), date(2018, 6, 5)
    assert issuer_by_name(ciks, subs, "Monarch Energy Holding, Inc.", last, day, target_cik=1) == 1711269
    last, day = date(2019, 11, 19), date(2019, 11, 20)
    assert issuer_by_name(ciks, subs, "Gannett Co., Inc.", last, day, target_cik=1635718) is None
    # CCU 2008's 'CC Media' shares one word with each of two issuers: no answer
    assert issuer_by_name(ciks, subs, "CC Media", date(2008, 7, 29), date(2008, 7, 30), target_cik=1) is None

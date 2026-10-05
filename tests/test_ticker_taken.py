"""`pipeline._ticker_taken` (sub-plan 5d rule 3), one test per rule, over a hand-built `FtdIndex`."""
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.pipeline import _ticker_taken

OWN = {"OWNCUSIP1"}


def _row(day, cusip, price, symbol="TKR"):
    return FtdRow(day, cusip, symbol, "SOME CORP", price)


def _taken(rows):
    return _ticker_taken(FtdIndex(rows), "TKR", OWN, "2019-03-01", "2019-04-30")


def test_the_day_before_another_cusips_first_priced_row_after_the_own_last_row():
    rows = [_row("2019-03-04", "OWNCUSIP1", 10.0), _row("2019-03-05", "OWNCUSIP1", 10.5),
            _row("2019-03-07", "OTHERCUSP", 48.9)]
    assert _taken(rows) == "2019-03-06"          # a row carries the close of the trading day before it


def test_another_cusips_row_between_the_own_rows_is_skipped():
    rows = [_row("2019-03-04", "OWNCUSIP1", 10.0), _row("2019-03-06", "OTHERCUSP", 48.9),
            _row("2019-03-08", "OWNCUSIP1", 10.5), _row("2019-03-12", "OTHERCUSP", 49.0)]
    assert _taken(rows) == "2019-03-11"


def test_a_row_at_or_below_a_cent_is_no_trade():
    """APA 2021: the new CUSIP's $0.01 first row beside the own row carrying the last close."""
    rows = [_row("2019-03-04", "OWNCUSIP1", 10.0), _row("2019-03-05", "OTHERCUSP", 0.01)]
    assert _taken(rows) is None


def test_no_own_row_under_the_ticker_gives_no_bound():
    """BTU 2016, CHK 2020: the own CUSIPs have no row under the ticker in the window."""
    assert _taken([_row("2019-03-05", "OTHERCUSP", 48.9)]) is None

from datetime import date

from delist_detection.trading_calendar import (
    add_trading_days, is_trading_day, next_trading_day, nyse_holidays, previous_trading_day,
)


def test_known_closures():
    assert date(2015, 4, 3) in nyse_holidays(2015)          # Good Friday
    assert date(2022, 6, 20) in nyse_holidays(2022)         # Juneteenth observed (Sun -> Mon)
    assert date(2021, 12, 31) not in nyse_holidays(2021)    # NY Day on Saturday is not moved back
    assert date(2025, 1, 9) in nyse_holidays(2025)          # national day of mourning (Carter)
    assert date(2012, 10, 29) in nyse_holidays(2012)        # Hurricane Sandy
    assert date(2020, 7, 3) in nyse_holidays(2020)          # July 4 on Saturday -> Friday
    assert date(1997, 1, 20) not in nyse_holidays(1997)     # MLK day only from 1998


def test_is_trading_day():
    assert is_trading_day(date(2018, 11, 28))
    assert not is_trading_day(date(2018, 11, 24))           # Saturday
    assert not is_trading_day(date(2018, 11, 22))           # Thanksgiving


def test_previous_and_next():
    assert previous_trading_day(date(2018, 11, 29)) == date(2018, 11, 28)
    assert previous_trading_day(date(2009, 1, 2)) == date(2008, 12, 31)     # MER
    assert previous_trading_day(date(2024, 11, 18)) == date(2024, 11, 15)   # SAVE (Monday)
    assert previous_trading_day(date(2015, 12, 28)) == date(2015, 12, 24)   # Altera
    assert next_trading_day(date(2018, 11, 28)) == date(2018, 11, 29)
    assert next_trading_day(date(2018, 11, 21)) == date(2018, 11, 23)       # skips Thanksgiving


def test_add_trading_days():
    assert add_trading_days(date(2018, 11, 28), 0) == date(2018, 11, 28)
    assert add_trading_days(date(2018, 11, 28), 2) == date(2018, 11, 30)
    assert add_trading_days(date(2018, 11, 26), -2) == date(2018, 11, 21)

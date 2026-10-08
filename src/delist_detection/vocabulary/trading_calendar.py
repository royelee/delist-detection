"""NYSE trading days: weekends, exchange holidays, and unscheduled closures.

Used to turn "suspended before the open on D" into the last trading day and to
line up SEC fails-to-deliver rows (a row dated D carries the prior day's close).
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# Unscheduled full-day closures since 1990.
_SPECIAL_CLOSURES = frozenset({
    date(1994, 4, 27),                                            # Nixon funeral
    date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),
    date(2004, 6, 11),                                            # Reagan funeral
    date(2007, 1, 2),                                             # Ford funeral
    date(2012, 10, 29), date(2012, 10, 30),                       # Hurricane Sandy
    date(2018, 12, 5),                                            # G.H.W. Bush funeral
    date(2025, 1, 9),                                             # Carter funeral
})


def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def _nth_weekday(y: int, month: int, weekday: int, n: int) -> date:
    first = date(y, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(y: int, month: int, weekday: int) -> date:
    d = (date(y + 1, 1, 1) if month == 12 else date(y, month + 1, 1)) - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> frozenset[date]:
    h: set[date] = set()
    new_year = date(year, 1, 1)
    if new_year.weekday() == 6:
        h.add(new_year + timedelta(days=1))
    elif new_year.weekday() != 5:          # a Saturday New Year's Day is not observed
        h.add(new_year)
    if year >= 1998:
        h.add(_nth_weekday(year, 1, 0, 3))  # Martin Luther King Jr. Day
    h.add(_nth_weekday(year, 2, 0, 3))      # Washington's Birthday
    h.add(_easter(year) - timedelta(days=2))  # Good Friday
    h.add(_last_weekday(year, 5, 0))        # Memorial Day
    if year >= 2022:
        h.add(_observed(date(year, 6, 19)))  # Juneteenth
    h.add(_observed(date(year, 7, 4)))
    h.add(_nth_weekday(year, 9, 0, 1))      # Labor Day
    h.add(_nth_weekday(year, 11, 3, 4))     # Thanksgiving
    h.add(_observed(date(year, 12, 25)))
    h |= {d for d in _SPECIAL_CLOSURES if d.year == year}
    return frozenset(h)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def add_trading_days(d: date, n: int) -> date:
    step = next_trading_day if n > 0 else previous_trading_day
    for _ in range(abs(n)):
        d = step(d)
    return d

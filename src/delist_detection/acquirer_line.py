"""A merger's acquirer as a line of the run, its symbol and its price on the price date (sub-plan 5e, spec section 3
"5e"; the CAL/UAUA decision of 2026-10-03).

A merger's terms are written before the closing and its stock leg is priced after it, and acquirers often change
their ticker, CUSIP or listed entity at the closing: UAL Corp's UAUA became UAL on a new CUSIP, United Technologies
became RTX the day after its spin-offs, Standard Pacific became CalAtlantic after a reverse split, Chemical Financial
took TCF's name and ticker. So the terms' ticker and acquirer name are only evidence for who the acquirer is, never
looked up on a later date:

- the issuer (`issuer_of`): the security of the run that held the terms' ticker on the last trade day (`LineIndex.
  holder`; a ticker that begins at the closing, JHG 2017, from the price date on), else the resolver's issuer of
  that ticker on the last trade day, else, with no ticker, the one issuer of the run that carried the terms'
  acquirer name around the closing (`issuer_by_name`); never the target's own issuer, and a resolver's answer only
  when one of its EDGAR names agrees with the terms' acquirer name;
- the issuer's line that trades on the price date (`choose_line`): the one of the class the terms name (GLIBA into
  Liberty Broadband's Series C), else the one whose CUSIP begins at the closing (UAL's 910047109), else the ticker's
  own line;
- its symbol on the price date (`LineIndex.symbol_on`) and its price (`LineIndex.price`): a CUSIP that begins at the
  closing is priced at its close on the price date, from the next day's fails row past the $0.01 and $1.00
  placeholders a new CUSIP's first rows carry (`is_placeholder_row`), so the old CUSIP's rows repeating a pre-closing
  close are never read; any other line at its close on the last trade day, as the payout gate has always priced it.

Pure over the run's own tables (its securities, their ticker sightings and CUSIPs, the fails index) apart from the
two reads `issuer_by_ticker` and `issuer_by_name` take as arguments (the resolver and EDGAR's submissions)."""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, timedelta

from .evidence import edgar_names, names_between
from .figi_resolution import class_letter
from .ftd import FtdIndex, FtdRow, is_trading_symbol, is_unassigned_symbol
from .history import Range, Sighting, ranges_from_sightings
from .names import _words, names_agree
from .observations import normalize_ticker
from .security_master import Security
from .trading_calendar import add_trading_days, next_trading_day

CLOSING_DAYS = 3        # a CUSIP whose first fails row falls from the last trade day to this many trading days after
                        # the price date began at the closing; a ticker that begins in that span is held from then
TRADING_DAYS = 5        # a line trades on the price date when its CUSIPs fail under a trading symbol this soon after
PRICE_LAG = 3           # how many trading days past the day after a close its fails row may come (`ftd.close_after`)
NAME_BEFORE_DAYS = 400  # an acquirer name counts when the issuer carried it from this long before the last trade...
NAME_AFTER_DAYS = 30    # ...to this long after the price date (Monarch Energy Holding, Evergy's name to the closing)
PENNY = 0.011
EARLY_DAYS = 40         # a merger this close to (or before) the first day the run loaded fails rows from has its
                        # candidate lines' rows read from this long before its last trade (pipeline stage 8a)


def is_placeholder_row(rows: Sequence[FtdRow], i: int) -> bool:
    """Whether `rows[i]` (one CUSIP's date-sorted rows) carries no close: no price, a non-trading symbol (an
    unassigned "...ZZZZ" or a deleted "...XXXX" symbol, ".", a pair-off code), a price of a cent or less, or $1.00
    where the CUSIP's next priced row is more than twice or less than half of it (a new CUSIP's first rows: UAL at
    $0.01 on 2010-10-01, AMCR and JHG at $1.00)."""
    r = rows[i]
    if r.price is None or r.price <= PENNY or not is_trading_symbol(r.symbol):
        return True
    if abs(r.price - 1.0) < 1e-9:
        nxt = next((x.price for x in rows[i + 1:] if x.price and x.price > PENNY), None)
        return nxt is not None and not 0.5 <= nxt <= 2.0
    return False


_CONSIDERATION = re.compile(r"\b(?:receive|into)\b(.*?)(?:\bfor each\b|\bper\b|$)", re.I | re.S)
_CLASS = re.compile(r"\b(?:Series|Class)\s+([A-Z])\b")


def named_class(quote: str | None) -> str | None:
    """The class letter the terms' quote names for the shares the holders receive: the first "Series X" or
    "Class X" after "receive" or "into" and before "for each" or "per" (GLIBA: "0.580 of a share of Liberty
    Broadband Series C common stock"); None when the consideration names no class."""
    m = _CONSIDERATION.search(quote or "")
    k = _CLASS.search(m.group(1)) if m else None
    return k.group(1) if k else None


class LineIndex:
    """The run's securities as acquirer lines: who held a ticker when (from their ticker sightings), each issuer's
    lines, and each line's CUSIPs' fails rows."""

    def __init__(self, securities: Mapping[str, Security], sightings: Mapping[str, Sequence[Sighting]],
                 cusips: Mapping[str, Sequence[str]], ftd: FtdIndex) -> None:
        self.securities, self.cusips, self.ftd = securities, cusips, ftd
        self._held: dict[str, list[tuple[str, Range]]] = defaultdict(list)
        for sid, sig in sightings.items():
            for r in ranges_from_sightings(sig, end=None, open_ended=False):
                self._held[normalize_ticker(r.value)].append((sid, r))
        self._by_cik: dict[int, list[str]] = defaultdict(list)
        for sid, s in sorted(securities.items()):
            if s.issuer_cik:
                self._by_cik[int(s.issuer_cik)].append(sid)
        self._first: dict[str, str | None] = {}

    def issuers(self) -> list[int]:
        return sorted(self._by_cik)

    def holder(self, ticker: str, last: date, price_day: date, *, exclude: str) -> str | None:
        """The one security other than `exclude` (the target) that held `ticker` on the last trade day, else whose
        hold of it began after it and by CLOSING_DAYS after the price date; None when none or several did."""
        t = normalize_ticker(ticker)
        if not t:
            return None
        held = [(sid, r) for sid, r in self._held.get(t, []) if sid != exclude]
        d, hi = last.isoformat(), add_trading_days(price_day, CLOSING_DAYS).isoformat()
        on = {sid for sid, r in held if r.valid_from <= d and (r.valid_to is None or d <= r.valid_to)}
        if not on:
            on = {sid for sid, r in held if d < r.valid_from <= hi}
        return next(iter(on)) if len(on) == 1 else None

    def lines(self, cik: int, *, exclude: str) -> list[str]:
        return [sid for sid in self._by_cik.get(int(cik), []) if sid != exclude]

    def _rows(self, cusip: str, lo: date, hi: date) -> list[FtdRow]:
        return self.ftd.by_cusip(cusip, lo.isoformat(), hi.isoformat())

    def _first_row(self, cusip: str) -> str | None:
        if cusip not in self._first:
            rows = [r for r in self.ftd.by_cusip(cusip) if is_trading_symbol(r.symbol) or is_unassigned_symbol(r.symbol)]
            self._first[cusip] = rows[0].date if rows else None
        return self._first[cusip]

    def closing_cusip(self, sid: str, last: date, price_day: date) -> str | None:
        """The line's one CUSIP whose first fails row falls from the last trade day to CLOSING_DAYS trading days
        after the price date: the CUSIP it began trading on at the closing."""
        lo, hi = last.isoformat(), add_trading_days(price_day, CLOSING_DAYS).isoformat()
        got = [c for c in self.cusips.get(sid, []) if (f := self._first_row(c)) is not None and lo <= f <= hi]
        return got[0] if len(got) == 1 else None

    def trades_on(self, sid: str, day: date) -> bool:
        """Whether the line's CUSIPs fail under a trading symbol within TRADING_DAYS trading days from `day`."""
        hi = add_trading_days(day, TRADING_DAYS)
        return any(is_trading_symbol(r.symbol) for c in self.cusips.get(sid, []) for r in self._rows(c, day, hi))

    def symbol_on(self, sid: str, day: date, *, last: date | None = None) -> str | None:
        """The line's symbol on `day`: that of its CUSIPs' row dated `day` (the CUSIP that began at the closing
        first, when two trade that day: RTX over UTC's old CUSIP), else of its first row in the CLOSING_DAYS trading
        days after (ICE Group's first row on 2013-11-14); None when no row names one."""
        closing = self.closing_cusip(sid, last, day) if last else None
        hi = add_trading_days(day, CLOSING_DAYS)
        rows = sorted((r for c in self.cusips.get(sid, []) for r in self._rows(c, day, hi) if is_trading_symbol(r.symbol)),
                      key=lambda r: (r.date, r.cusip != closing, r.cusip))
        return rows[0].symbol if rows else None

    def close_after(self, cusip: str, day: date) -> tuple[float, str, bool] | None:
        """The close of `day` from `cusip`'s fails rows: the first row past the placeholders dated from the next
        trading day to PRICE_LAG trading days later (lagged when it is not the next trading day's): `(price,
        row_date, lagged)`."""
        first = next_trading_day(day)
        rows = self._rows(cusip, first, add_trading_days(first, PRICE_LAG + 3))
        last = add_trading_days(first, PRICE_LAG).isoformat()
        for i, r in enumerate(rows):
            if r.date > last:
                break
            if not is_placeholder_row(rows, i):
                return r.price, r.date, r.date != first.isoformat()
        return None

    def cusip_on(self, sid: str, day: date) -> str | None:
        """The CUSIP of the line's first row under a trading symbol from `day` on, within CLOSING_DAYS trading
        days."""
        hi = add_trading_days(day, CLOSING_DAYS)
        rows = sorted((r for c in self.cusips.get(sid, []) for r in self._rows(c, day, hi) if is_trading_symbol(r.symbol)),
                      key=lambda r: (r.date, r.cusip))
        return rows[0].cusip if rows else None

    def price(self, sid: str, last: date, price_day: date) -> tuple[float, str, bool] | None:
        """The line's price for a stock leg: a CUSIP that began at the closing at its close on the price date, any
        other line at its close on the last trade day (by its CUSIP on the price date)."""
        closing = self.closing_cusip(sid, last, price_day)
        if closing:
            return self.close_after(closing, price_day)
        cusip = self.cusip_on(sid, price_day) or self.cusip_on(sid, last)
        return self.close_after(cusip, last) if cusip else None


def choose_line(index: LineIndex, cik: int, *, holder: str | None, letter: str | None, last: date, price_day: date,
                exclude: str) -> str | None:
    """The issuer's line a stock leg is priced on: among its lines trading on the price date, the one of the class
    the terms name (`letter`); else its one line whose CUSIP began at the closing; else the ticker's own line
    (`holder`) when it trades then; else its one line trading then. None when that leaves no line or several."""
    lines = index.lines(cik, exclude=exclude)
    live = [sid for sid in lines if index.trades_on(sid, price_day)]
    if letter:
        by_class = [sid for sid in live if class_letter(index.securities[sid].share_class) == letter]
        if len(by_class) == 1:
            return by_class[0]
    closing = [sid for sid in lines if index.closing_cusip(sid, last, price_day)]
    if len(closing) == 1:
        return closing[0]
    if holder in live:
        return holder
    return live[0] if len(live) == 1 else None


Submissions = Callable[[int], object]


def _names(subs: Submissions, cik: int) -> tuple[str, ...]:
    sub = subs(cik)
    return edgar_names(sub) if isinstance(sub, dict) else ()


def issuer_by_ticker(resolver, subs: Submissions, ticker: str, name: str, last: date, *,
                     target_cik: int | None) -> int | None:
    """The resolver's issuer of the terms' ticker on the last trade day, asked with the terms' acquirer name (its
    name tiers find an acquirer outside the caller's universe by it: Standard Pacific, Chemical Financial), when it
    is not the target's and one of its EDGAR names (current or former) agrees with that name (none to check: any)."""
    cik = resolver.resolve(normalize_ticker(ticker), last.isoformat(), name=name or None).cik
    if not cik or cik == target_cik:
        return None
    if name and not any(names_agree(name, n) for n in _names(subs, cik)):
        return None
    return int(cik)


def _shared_words(a: str, b: str) -> int:
    """How many of `a`'s distinctive words (`names_agree`'s words) are in `b`."""
    tb = {f for forms in _words(b) for f in forms}
    return sum(1 for forms in _words(a) if forms & tb)


def issuer_by_name(ciks: Iterable[int], subs: Submissions, name: str, last: date, price_day: date, *,
                   target_cik: int | None) -> int | None:
    """The issuer among `ciks` (the run's), other than the target's, that carried a name agreeing with the terms'
    acquirer name from NAME_BEFORE_DAYS before the last trade to NAME_AFTER_DAYS after the price date, sharing more
    of its words than any other such issuer (Monarch Energy Holding is Evergy's former name, not SM Energy's); None
    when none did or several tie (CC Media: Versant Media, CTC Media). Names are compared only among the issuers
    whose EDGAR names agree at all, so the dated read is a handful of submissions."""
    if not name:
        return None
    lo, hi = last - timedelta(days=NAME_BEFORE_DAYS), price_day + timedelta(days=NAME_AFTER_DAYS)
    scored: list[tuple[int, int]] = []
    for cik in ciks:
        if cik == target_cik or not any(names_agree(name, n) for n in _names(subs, cik)):
            continue
        sub = subs(cik)
        near = [n for n in names_between(sub, lo, hi) if names_agree(name, n)] if isinstance(sub, dict) else []
        if near:
            scored.append((max(_shared_words(name, n) for n in near), cik))
    scored.sort(reverse=True)
    if not scored or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    return scored[0][1]

"""A security's trading record (CONTEXT.md, architecture step 14): what its sightings and its own CUSIPs' fails rows
say of its trading, read by the delisting finder (`delistings.DelistingFinder`) and the last trade module
(`last_trade.Dating`).

The interface:
- two constructors: `TradingRecord.observed` (a security of the run: its eras give the days and the ticker it is
  known by, its sightings `history.ticker_sightings`) and `TradingRecord.added` (a successor the run added, stage 9d:
  its span and ticker, its sightings `history.span_sightings`; no era is made up for it);
- what the record knows it by: `ticker`, `known_from`, `known_until`, `expected_name`, `own_tickers`, `has_cusips`;
- what the sightings say: the ticker on a day (`ticker_on`), the last own-ticker sighting (`last_seen`), whether it
  was sighted after a day (`seen_after`, `seen_in_fails_after`), its first and last day as a sibling (`span`), every
  ticker of a window (`tickers`);
- what its own CUSIPs' fails rows say: trading after a day (`trades_after`), trading near a day (`traded_within`),
  its CUSIP switches (`cusip_switches`), the class letter their descriptions name (`letter_hint`), the ticker's
  tenure (rule 3, `taken`, `ticker_taken`) and the last day the rows show it trading (rule 4's floor,
  `trades_until`, `last_row_trade_day`).

The record holds data, never a closure: each answer is worked out from the sightings, the CUSIPs and the fails index
it was built over, and a query never reads the fails files (`ftd.FtdIndex`). The answers a record caches are read on
the warm pass's threads too, from the same index, so they are the sequential pass's.
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cached_property

from .ftd import FtdIndex, FtdRow, is_trading_symbol, settled_last
from .ftd import trades_after as rows_trade_after
from .history import FTD, Sighting, cusip_sightings, span_sightings, ticker_sightings
from .identifiers import class_letter, descriptions_class_letter
from .security_master import Security
from .trading_calendar import previous_trading_day

PLACEHOLDER_PRICE = 0.01        # a fails row priced at or below this carries no close (a new CUSIP's placeholder)


def ticker_taken(fails: FtdIndex, ticker: str, own: Collection[str], lo: str, hi: str) -> str | None:
    """Rule 3 (5d), the ticker's tenure: the first day another CUSIP traded under `ticker` within the ISO window
    [lo, hi] once the security's own CUSIPs (`own`) stopped: the trading day before that CUSIP's first priced fails
    row there (a row carries the close of the trading day before it), when that row comes on or after the own
    CUSIPs' last row under the ticker -- else None. None too when the own CUSIPs have no row under the ticker in the
    window (the tenure there is not known: Peabody's, Chesapeake's own new CUSIPs). A $0.01 placeholder row is no
    trade (APA Corp's first row, 2021-03-02, beside Apache's own row carrying its March 1 close). CCEP's shares
    under CCE from 2016-05-31, Johnson Controls plc's under JCI from 2016-09-06."""
    rows = [r for r in fails.by_symbol(ticker, lo, hi) if r.price is not None and r.price > PLACEHOLDER_PRICE]
    mine = [r.date for r in rows if r.cusip in own]
    if not mine:
        return None
    other = next((r.date for r in rows if r.cusip not in own and r.date > mine[0] and r.date >= mine[-1]), None)
    return previous_trading_day(date.fromisoformat(other)).isoformat() if other else None


def last_row_trade_day(rows: Sequence[FtdRow]) -> str | None:
    """The last day the fails rows show the security trading: the trading day before the row that opens the
    last one-price run (`ftd.settled_last`, fails still settling after the last trade) of the CUSIP it held
    last, ISO (AVGO 2018: the run opens 04-05, so 04-04); None without rows."""
    if not rows:
        return None
    last = max(r.date for r in rows)
    own = sorted((r for r in rows if r.cusip == next(x.cusip for x in rows if x.date == last)),
                 key=lambda r: r.date)
    return previous_trading_day(date.fromisoformat(settled_last(own).date)).isoformat()


@dataclass(frozen=True)
class TradingRecord:
    """One security's trading record (the module docstring's interface).

    - `security`: the security (its share class, kind, name, issuer CIK, eras and line tickers);
    - `sightings`: its dated ticker sightings, date-sorted (`history.Sighting`: observations, fails rows of its own
      CUSIPs under any symbol, the OTC symbol it moved to included; an added security's span days);
    - `cusips`: its own CUSIPs; `fails`: the fails index their rows and another CUSIP's rows under its tickers come
      from (None: nothing known of the fails, no rows, no tenure bound);
    - `ticker`: the ticker it is known by last (its last era's, an added security's own); `known_from`,
      `known_until`: the days it is known from and until (its eras' first and last observation, an added
      security's span; blank: no day known, so no search); `expected_name`: the name it is known by last.

    Build one with `observed` or `added`; the bare constructor is for the last trade module's tests, which read
    only the sightings, the CUSIPs and the rows."""
    security: Security
    sightings: Sequence[Sighting] = ()
    cusips: tuple[str, ...] = ()
    fails: FtdIndex | None = None
    ticker: str = ""
    known_from: str = ""
    known_until: str = ""
    expected_name: str | None = None

    # -- the two constructors ------------------------------------------------------------
    @classmethod
    def observed(cls, security: Security, fails: FtdIndex, cusips: Sequence[str],
                 sightings: Sequence[Sighting] | None = None) -> TradingRecord:
        """A security of the run, over the fails index and its own CUSIPs: its sightings are its observations and
        its CUSIPs' fails rows (`history.ticker_sightings`) unless given; its eras give its ticker (the last era's),
        the days it is known from and until and its expected name (the last era's)."""
        eras = security.eras
        sig = ticker_sightings(security, fails, cusips) if sightings is None else sightings
        return cls(security, sig, tuple(cusips), fails, ticker=eras[-1].ticker if eras else "",
                   known_from=min(e.first for e in eras) if eras else "",
                   known_until=max(e.last for e in eras) if eras else "",
                   expected_name=eras[-1].name if eras else None)

    @classmethod
    def added(cls, security: Security, ticker: str, span: tuple[str, str], fails: FtdIndex,
              cusips: Sequence[str]) -> TradingRecord:
        """A successor the run added (stage 9d), which no observation names: known under `ticker` from the first
        to the last day of `span`; its sightings are those two days and its CUSIPs' fails rows
        (`history.span_sightings`); its expected name is its own."""
        first, last = span
        return cls(security, span_sightings(ticker, (first, last), fails, cusips), tuple(cusips), fails,
                   ticker=ticker, known_from=first, known_until=last, expected_name=security.name or None)

    # -- what the record knows it by -------------------------------------------------------
    @cached_property
    def own_tickers(self) -> frozenset[str]:
        """Every ticker it is known to have traded under: its eras' and its line's (`Security.own_tickers`), and an
        added security's own."""
        return frozenset(self.security.own_tickers() | ({self.ticker} if self.ticker else set()))

    @property
    def has_cusips(self) -> bool:
        """Whether it has a CUSIP of its own, whose fails rows could show it stop."""
        return bool(self.cusips)

    # -- what the sightings say ----------------------------------------------------------
    def ticker_on(self, day: str) -> str | None:
        """Its ticker on an ISO day: the latest sighting on or before the day, else its first; None without
        sightings."""
        before = [s.value for s in self.sightings if s.day <= day]
        if before:
            return before[-1]
        return self.sightings[0].value if self.sightings else None

    @cached_property
    def last_seen(self) -> str:
        """The latest sighting under one of its own tickers, else `known_until`. The fails rows of its CUSIPs include
        a post-delisting OTC tail under another symbol (a bankrupt XYZ trading as XYZQ), which would otherwise push
        the last sighting past the real delisting and misdate a fallback delisting."""
        own = self.own_tickers
        dates = [s.day for s in self.sightings if s.value in own]
        return dates[-1] if dates else self.known_until

    def seen_after(self, day: str) -> bool:
        """Whether any sighting (an OTC tail's included) is dated after the ISO day."""
        return any(x.day > day for x in self.sightings)

    def seen_in_fails_after(self, day: str) -> bool:
        """Whether a fails row under one of its own tickers is dated after the ISO day: trading an observation alone
        does not show (a stale snapshot can list a security long after it was acquired)."""
        own = self.own_tickers
        return any(x.day > day for x in self.sightings if x.source == FTD and x.value in own)

    @property
    def span(self) -> tuple[str, str] | None:
        """(first sighting, `last_seen`), ISO: the days a sibling is alive around (`delistings.SIBLING_ALIVE_*`);
        the end is its own last sighting, so an OTC tail under another symbol cannot extend its life. None without
        sightings (a sibling whose span is unknown counts as alive at every filing)."""
        return (self.sightings[0].day, self.last_seen) if self.sightings else None

    def tickers(self, lo: str, hi: str) -> list[str]:
        """Every ticker it was sighted under between two ISO days, in sighting order: the ticker on a Form 25's date
        can be the OTC symbol already (SAVE -> SAVEQ), which no exchange source knows."""
        return list(dict.fromkeys(x.value for x in self.sightings if lo <= x.day <= hi))

    # -- what its own CUSIPs' fails rows say ---------------------------------------------
    @cached_property
    def rows(self) -> list[FtdRow]:
        """Its own CUSIPs' fails rows that show it trading (`FtdIndex.trading_rows`: not under a deleted symbol)."""
        return self.fails.trading_rows(self.cusips) if self.fails is not None else []

    def trades_after(self, day: str) -> bool:
        """Whether its own CUSIPs' rows, under any symbol it trades under, show it still trading after the ISO day
        (`ftd.trades_after`: enough rows over enough days at two or more prices)."""
        return rows_trade_after(self.rows, day)

    def traded_within(self, day: str, days: int) -> bool:
        """Whether a trading fails row of its own CUSIPs (`ftd.is_trading_symbol`: no deleted, unassigned or
        pair-off symbol) is dated in the `days` days up to the ISO day."""
        lo = (date.fromisoformat(day) - timedelta(days=days)).isoformat()
        return any(lo <= r.date <= day and is_trading_symbol(r.symbol) for r in self.rows)

    @cached_property
    def cusip_switches(self) -> tuple[str, ...]:
        """The first sighting of each of its CUSIPs after its first (`history.cusip_sightings`), ISO: the days its
        own line switched CUSIP (a reverse split, a redomicile that kept the composite)."""
        if self.fails is None:
            return ()
        first: dict[str, str] = {}
        for x in cusip_sightings(self.security, self.fails, self.cusips):
            first.setdefault(x.value, x.day)
        return tuple(sorted(first.values())[1:])

    @cached_property
    def letter_hint(self) -> str | None:
        """For a share class with no letter, the one letter its own CUSIPs' fails descriptions name
        (`identifiers.descriptions_class_letter`, R2: SunPower's class A placeholder, "SUNPOWER CORP CL A"); None
        for a lettered class, or without a fails index."""
        if class_letter(self.security.share_class) or self.fails is None:
            return None
        return descriptions_class_letter(d for c in self.cusips for d in self.fails.descriptions(c))

    def taken(self, ticker: str, lo: str, hi: str) -> str | None:
        """Rule 3 over its own CUSIPs (`ticker_taken`); None without a fails index."""
        return ticker_taken(self.fails, ticker, frozenset(self.cusips), lo, hi) if self.fails is not None else None

    def trades_until(self) -> str | None:
        """The last day its own fails rows show it trading (`last_row_trade_day`)."""
        return last_row_trade_day(self.rows)

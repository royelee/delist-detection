"""SEC fails-to-deliver data: dated (CUSIP, symbol, description, price) rows.

Two uses: the close on a security's last trading day (a row dated D carries the
close of the prior trading day), and the CUSIP a symbol carried on a date.
Rows exist only on days with fails, so a quiet security has gaps.

FTD writes class tickers without a separator ("BFB", "BRKB") where the output
tables write "BF-B". `FtdIndex` loads a requested ticker under both spellings
and keys the rows by the separator spelling.
"""
from __future__ import annotations

import calendar
import io
import logging
import re
import zipfile
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from .observations import normalize_ticker
from .sec_http import download, get_text
from .trading_calendar import add_trading_days, next_trading_day

_log = logging.getLogger(__name__)

FTD_INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
_SEC = "https://www.sec.gov"
_HALF = re.compile(r"cnsfails(\d{4})(\d{2})([ab])(?:_\d+)?\.zip$", re.I)
_QTR = re.compile(r"cnsp_sec_fails_(\d{4})q([1-4])\.zip$", re.I)


@dataclass(frozen=True)
class FtdRow:
    date: str
    cusip: str
    symbol: str
    description: str
    price: float | None


def period_of(url: str) -> tuple[date, date] | None:
    name = url.rsplit("/", 1)[-1]
    m = _HALF.search(name)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if m.group(3).lower() == "a":
            return date(y, mo, 1), date(y, mo, 15)
        return date(y, mo, 16), date(y, mo, calendar.monthrange(y, mo)[1])
    m = _QTR.search(name)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        end_month = 3 * q
        return date(y, end_month - 2, 1), date(y, end_month, calendar.monthrange(y, end_month)[1])
    return None


def parse_index_links(html: str) -> list[str]:
    out: list[str] = []
    seen: set[tuple[date, date]] = set()
    for href in re.findall(r'href="([^"]+\.zip)"', html, re.I):
        p = period_of(href)
        if p is None or p in seen:
            continue
        seen.add(p)
        out.append(href if href.startswith("http") else _SEC + href)
    return out


def parse_ftd_lines(lines: Iterable[str], *, symbols: set[str] | None = None,
                    cusips: set[str] | None = None, counts: Counter | None = None) -> Iterator[FtdRow]:
    """Rows from FTD text lines; header, trailer and malformed lines are skipped.
    `symbols`/`cusips` each filter independently when given (a row passes if it
    matches either one); both left `None` (the default) means no filtering at
    all. Filtered on symbol/CUSIP before an `FtdRow` is built (fast path).
    `counts["rows"]`, when given, counts every well-formed data line, filtered
    out or not."""
    for line in lines:
        parts = line.rstrip("\r\n").split("|")
        if len(parts) < 6:
            continue
        d = parts[0].strip()
        if len(d) != 8 or not d.isdigit():
            continue
        if counts is not None:
            counts["rows"] += 1
        cusip = parts[1].strip().upper()
        symbol = normalize_ticker(parts[2])
        if symbols is not None or cusips is not None:
            sym_hit = symbols is not None and symbol in symbols
            cus_hit = cusips is not None and cusip in cusips
            if not (sym_hit or cus_hit):
                continue
        try:
            price: float | None = float(parts[-1].strip())
        except ValueError:
            price = None
        yield FtdRow(f"{d[:4]}-{d[4:6]}-{d[6:]}", cusip, symbol, "|".join(parts[4:-1]).strip(), price)


class FtdClient:
    def __init__(self, cache_dir: str | Path, *, session=None, user_agent: str | None = None) -> None:
        self.dir = Path(cache_dir)
        self.session, self.user_agent = session, user_agent
        self._links: list[str] | None = None

    def links(self) -> list[str]:
        if self._links is None:
            html = get_text(FTD_INDEX_URL, self.dir / "index.html", max_age_days=7,
                            session=self.session, user_agent=self.user_agent)
            self._links = parse_index_links(html)
        return self._links

    def urls_for(self, lo: date, hi: date) -> list[str]:
        hits = [(period_of(u), u) for u in self.links()]
        return [u for p, u in sorted(hits) if p and p[0] <= hi and p[1] >= lo]

    def rows(self, url: str, *, symbols: set[str] | None = None,
             cusips: set[str] | None = None) -> Iterator[FtdRow]:
        dest = self.dir / url.rsplit("/", 1)[-1]
        path = download(url, dest, session=self.session, user_agent=self.user_agent)
        try:
            z = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            path.unlink(missing_ok=True)          # a truncated download: fetch it again once
            z = zipfile.ZipFile(download(url, dest, session=self.session, user_agent=self.user_agent))
        with z:
            # Every file member is read, whatever its name: from 2022-05 on the SEC
            # ships one member without an extension ("cnsfails202401a").
            for info in z.infolist():
                if info.is_dir():
                    continue
                counts: Counter = Counter()
                with z.open(info) as fh:
                    yield from parse_ftd_lines(io.TextIOWrapper(fh, encoding="latin-1"),
                                               symbols=symbols, cusips=cusips, counts=counts)
                if not counts["rows"]:
                    _log.warning(f"{dest.name}: member {info.filename!r} holds no fails-to-deliver rows; skipped")


class FtdIndex:
    def __init__(self, rows: Iterable[FtdRow] = ()) -> None:
        self._by_symbol: dict[str, list[FtdRow]] = defaultdict(list)
        self._by_cusip: dict[str, list[FtdRow]] = defaultdict(list)
        self._seen: set[FtdRow] = set()
        self._dirty = False
        # The disjoint [lo, hi] ranges already scanned *as that exact filter
        # key* (not merely a key that happened to show up under the other
        # dimension's filter) — see `extend`. Sorted, non-overlapping,
        # non-adjacent; a key is covered for [lo, hi] only if one of its
        # merged intervals spans the whole range, so two scans with a gap
        # between them (e.g. Jan and Mar) don't falsely cover Feb.
        self._symbol_windows: dict[str, list[tuple[date, date]]] = {}
        self._cusip_windows: dict[str, list[tuple[date, date]]] = {}
        # The separator-free FTD spelling of each requested ticker that has a
        # separator ("BFB" -> "BF-B"); None marks a bare spelling two requested
        # tickers share, which is left unmapped.
        self._aliases: dict[str, str | None] = {}
        for r in rows:
            self.add(r)

    def _learn(self, symbols: set[str]) -> set[str]:
        """Remember the separator spellings among `symbols`; returns the file
        filter: each symbol plus its separator-free spelling."""
        out = set(symbols)
        for s in symbols:
            bare = s.replace("-", "")
            if bare != s:
                out.add(bare)
                self._aliases[bare] = s if self._aliases.get(bare, s) == s else None
        return out

    def _canon(self, symbol: str) -> str:
        """The canonical ticker a symbol stands for: the requested ticker it
        equals without separators, else itself. This holds even when the bare
        spelling was requested too (index snapshots write "BFB" and "BF.B"), so
        both spellings share one list of rows."""
        return self._aliases.get(symbol) or symbol

    def add(self, r: FtdRow) -> None:
        canon = self._canon(r.symbol)
        if canon != r.symbol:
            r = replace(r, symbol=canon)
        if r in self._seen:
            return
        self._seen.add(r)
        self._by_symbol[r.symbol].append(r)
        self._by_cusip[r.cusip].append(r)
        self._dirty = True

    @classmethod
    def load(cls, client: FtdClient, lo: date, hi: date, *, symbols: Iterable[str] | None = None,
             cusips: Iterable[str] | None = None) -> "FtdIndex":
        idx = cls()
        idx._scan(client, lo, hi,
                  None if symbols is None else {normalize_ticker(s) for s in symbols},
                  None if cusips is None else {c.upper() for c in cusips})
        return idx

    def extend(self, client: FtdClient, lo: date, hi: date, *, cusips: Iterable[str] = (),
               symbols: Iterable[str] = ()) -> None:
        """Scan `[lo, hi]` for any of `cusips`/`symbols` not already covered by
        an earlier `load`/`extend` scan filtered on that exact key over at
        least that range. A CUSIP picked up only incidentally through a symbol
        filter (never itself used as a CUSIP filter) has no recorded CUSIP
        window, so it is rescanned here as a CUSIP filter — which is not
        symbol-restricted, so it catches that CUSIP's rows under any symbol
        (e.g. a ticker change). Rows already indexed are deduped via `_seen`."""
        cusips = {c.upper() for c in cusips}
        symbols = {normalize_ticker(s) for s in symbols}
        new_cusips = {c for c in cusips if not self._covered(self._cusip_windows.get(c, []), lo, hi)}
        new_symbols = {s for s in symbols if not self._covered(self._symbol_windows.get(s, []), lo, hi)}
        if new_cusips or new_symbols:
            self._scan(client, lo, hi, new_symbols or None, new_cusips or None)

    @staticmethod
    def _covered(intervals: list[tuple[date, date]], lo: date, hi: date) -> bool:
        """True only when a single already-scanned interval spans all of
        [lo, hi] — two intervals that merely straddle it (e.g. Jan and Mar
        around a Feb gap) must not count as covering it."""
        return any(a <= lo and b >= hi for a, b in intervals)

    @staticmethod
    def _merge(intervals: list[tuple[date, date]], lo: date, hi: date) -> list[tuple[date, date]]:
        """`intervals` (already sorted, merged) with `[lo, hi]` folded in,
        merging any overlapping or adjacent (gap of a single day) intervals."""
        merged: list[tuple[date, date]] = []
        for a, b in sorted(intervals + [(lo, hi)]):
            if merged and a <= merged[-1][1] + timedelta(days=1):
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        return merged

    def _scan(self, client: FtdClient, lo: date, hi: date, symbols: set[str] | None,
              cusips: set[str] | None) -> None:
        lo_s, hi_s = lo.isoformat(), hi.isoformat()
        wanted = None if symbols is None else self._learn(symbols)
        for url in client.urls_for(lo, hi):
            for r in client.rows(url, symbols=wanted, cusips=cusips):
                if lo_s <= r.date <= hi_s:
                    self.add(r)
        for keys, windows in ((symbols, self._symbol_windows), (cusips, self._cusip_windows)):
            for k in keys or ():
                windows[k] = self._merge(windows.get(k, []), lo, hi)

    def _sort(self) -> None:
        if self._dirty:
            for m in (self._by_symbol, self._by_cusip):
                for v in m.values():
                    v.sort(key=lambda r: (r.date, r.cusip, r.symbol))
            self._dirty = False

    @staticmethod
    def _slice(rows: list[FtdRow], lo: str | None, hi: str | None) -> list[FtdRow]:
        dates = [r.date for r in rows]
        i = bisect_left(dates, lo) if lo else 0
        j = bisect_right(dates, hi) if hi else len(rows)
        return rows[i:j]

    def by_symbol(self, symbol: str, lo: str | None = None, hi: str | None = None) -> list[FtdRow]:
        self._sort()
        return self._slice(self._by_symbol.get(self._canon(normalize_ticker(symbol)), []), lo, hi)

    def by_cusip(self, cusip: str, lo: str | None = None, hi: str | None = None) -> list[FtdRow]:
        self._sort()
        return self._slice(self._by_cusip.get(cusip.upper(), []), lo, hi)

    def close_after(self, day: date, *, cusip: str | None = None, symbol: str | None = None,
                    max_lag: int = 3) -> tuple[float, str, bool] | None:
        """The close of `day`: the first priced row dated on the next trading day,
        or up to `max_lag` further trading days later (then `lagged` is True; rows
        after the last trade repeat the last close, but after an OTC move they
        carry OTC prices, so a lagged value is flagged for review)."""
        first = next_trading_day(day)
        last = add_trading_days(first, max_lag)
        rows = (self.by_cusip(cusip, first.isoformat(), last.isoformat()) if cusip
                else self.by_symbol(symbol or "", first.isoformat(), last.isoformat()))
        for r in rows:
            if r.price is not None and r.price > 0:
                return r.price, r.date, r.date != first.isoformat()
        return None

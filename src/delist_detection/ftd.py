"""SEC fails-to-deliver data: dated (CUSIP, symbol, description, price) rows.

Two uses: the close on a security's last trading day (a row dated D carries the
close of the prior trading day), and the CUSIP a symbol carried on a date.
Rows exist only on days with fails, so a quiet security has gaps.

`FtdClient` reads SEC's files; `FtdIndex` holds the rows a run asks about and is
the only reader of its client (its source): a stage asks the index for keys
over a span (`follow`, `around`, `apart`, `every_row`) and never holds the files.

FTD writes class tickers without a separator ("BFB", "BRKB") where the output
tables write "BF-B". `FtdIndex` loads a requested ticker under both spellings
and keys the rows by the separator spelling. A one-letter class suffix can also
sit on the symbol FTD uses whole (a snapshot's "UAC-C" for Under Armour's class C,
which FTD lists as "UAC"): that base spelling is loaded too, and its rows that
name the class letter and agree with the ticker's observed names are keyed by
the class ticker (sub-plan 5h).
"""
from __future__ import annotations

import calendar
import io
import logging
import re
import zipfile
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from .atomic_io import clean_orphan_temps
from .identifiers import bare_ticker, class_suffix, description_class_letter, normalize_ticker
from .names import names_agree
from .sec_http import download, get_text
from .trading_calendar import add_trading_days, next_trading_day, previous_trading_day

_log = logging.getLogger(__name__)

FTD_INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
_SEC = "https://www.sec.gov"
_HALF = re.compile(r"cnsfails(\d{4})(\d{2})([ab])(?:_\d+)?\.zip$", re.I)
_QTR = re.compile(r"cnsp_sec_fails_(\d{4})q([1-4])\.zip$", re.I)


FTD_START = date(2004, 1, 1)      # the first day SEC's fails-to-deliver files cover


@dataclass(frozen=True)
class FtdRow:
    date: str
    cusip: str
    symbol: str
    description: str
    price: float | None


def is_deleted_symbol(symbol: str) -> bool:
    """SEC's fails files keep reporting a delisted security under a deleted
    symbol: its old symbol with "XXXX" appended (ORLYXXXX, LLYVKXXXX; AGRX
    becomes AGRXXXXX). Such a row records a fail still settling, not trading
    under a live symbol. A real ticker may end in X or XX (AVXX), never XXXX."""
    return len(symbol or "") > 4 and symbol.endswith("XXXX")


def is_unassigned_symbol(symbol: str) -> bool:
    """A new CUSIP's first fails rows, before the exchange assigns it a symbol, carry the ticker with "ZZZZ"
    appended (FMDZZZZ, JNYZZZZ, NYCBZZZZ), often at $0.01 or $1.00. Like a deleted "...XXXX" symbol, it is no
    ticker the security traded under."""
    return len(symbol or "") > 4 and symbol.endswith("ZZZZ")


TRADING_MIN_ROWS = 20     # fails rows after a day that show a security still trading: at least this many...
TRADING_MIN_DAYS = 20     # ...spanning at least this many days...
TRADING_MIN_PRICES = 2    # ...at two or more prices (fails still settling at the last close repeat one price)


def is_trading_symbol(symbol: str) -> bool:
    """Whether a fails row's symbol is one a security trades under: not a deleted "…XXXX" or unassigned "…ZZZZ"
    symbol, and no digit (SEC's pair-off placeholders such as "F104PAIROFF" carry part of the CUSIP)."""
    return bool(symbol) and not is_deleted_symbol(symbol) and not is_unassigned_symbol(symbol) \
        and not any(ch.isdigit() for ch in symbol)


def trades_after(rows: Iterable[FtdRow], after: str) -> bool:
    """Whether the fails rows of a security's own CUSIPs (`rows`) show it still trading after the ISO day `after`,
    under any symbol it trades under (`is_trading_symbol`; an OTC symbol counts): at least TRADING_MIN_ROWS rows
    over at least TRADING_MIN_DAYS days, at TRADING_MIN_PRICES or more prices."""
    later = [r for r in rows if r.date > after and is_trading_symbol(r.symbol)]
    if len(later) < TRADING_MIN_ROWS:
        return False
    days = sorted(r.date for r in later)
    if (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days < TRADING_MIN_DAYS:
        return False
    return len({r.price for r in later if r.price is not None}) >= TRADING_MIN_PRICES


def settled_last(rows: Sequence[FtdRow]) -> FtdRow:
    """The row that opens the last run of one price in the date-sorted, non-empty `rows`: fails still settling
    after a security's last trade repeat its last close, so its last trade lies near that row, not the last one
    (Sara Lee's 803111103 fails at 18.50 from 2012-06-29 to 2012-07-13, after its last trade on 2012-06-28)."""
    i = len(rows) - 1
    while i > 0 and rows[i - 1].price == rows[-1].price:
        i -= 1
    return rows[i]


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
        clean_orphan_temps(self.dir)          # a killed run's cut-off download or index page

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


class FtdSource(Protocol):
    """The fails files an index reads: `FtdClient`, or a test's double. `urls_for` lists the files whose period
    meets [lo, hi]; `rows` gives a file's rows, those of `symbols` or `cusips` when either is given, every row when
    neither is."""

    def urls_for(self, lo: date, hi: date) -> list[Any]: ...

    def rows(self, url: Any, *, symbols: set[str] | None = None,
             cusips: set[str] | None = None) -> Iterator[FtdRow]: ...


class FtdIndex:
    """The fails rows a run asks about, keyed by symbol and by CUSIP; the only reader of its source.

    Built two ways:

    - `FtdIndex(rows)`: an index holding the given rows. With no `source`, they are all it has (the tests'
      fixtures); an ask reads nothing.
    - `FtdIndex.opened(source, lo, hi, ...)`: the run's index, opened with the observed tickers' and CUSIPs' rows
      over [lo, hi] (stage 1). Its run's fails window is [lo, `through`]: what `follow` reads.

    What a stage asks, the index reads from its source; no stage holds the files, and none chooses a window but
    by the days it asks about:

    - `follow(cusips=, symbols=)`: these keys' rows over the run's fails window (stages 4 and 4b);
    - `around(days, before=, after=, ...)`: these keys' rows from `before` days before the earliest day to
      `after` days after the latest (stages 5b, 7 and 8's gate);
    - `apart(days, ...)`: a separate index of CUSIPs' rows around days, this one left as it was (stage 8a);
    - `every_row(lo, hi)`: every row of the files in a span, held nowhere (stage 8a').

    An ask reads only the keys it does not hold over its whole span, in one pass over the span's files. A key's
    spans are remembered as that key: a CUSIP whose rows came in under a symbol is read again when asked as a
    CUSIP (so it is found under any symbol). A row already held is never added twice.

    Every query answers from the rows held (`by_symbol`, `by_cusip`, `trading_rows`, the closes): the rows the
    run has asked for so far, with the rows other keys' asks brought in. Coverage is stated:

    - `opened_from`: the first day of the window the index was opened over (rows asked for);
    - `data_covers(lo, hi)` and `data_end()`: the fails data's own coverage, from the source's file index (the
      periods of SEC's files), up to the run date. Neither depends on what was asked.

    The warm passes read the index and never ask it, so a run's asks are the sequential pass's, in its order, for
    any worker count."""

    def __init__(self, rows: Iterable[FtdRow] = (), *, source: FtdSource | None = None,
                 window: tuple[date, date] | None = None) -> None:
        self._source = source
        self._window = window                  # the run's fails window: what `follow` reads
        self._periods: list[tuple[date, date]] | None = None     # the source's file periods, once read
        self._by_symbol: dict[str, list[FtdRow]] = defaultdict(list)
        self._by_cusip: dict[str, list[FtdRow]] = defaultdict(list)
        self._seen: set[FtdRow] = set()
        self._dates: list[str] = []            # every row's date, sorted by `_sort`
        self._dirty = False
        # The disjoint [lo, hi] ranges already scanned *as that exact filter
        # key* (not merely a key that happened to show up under the other
        # dimension's filter) — see `_ask`. Sorted, non-overlapping,
        # non-adjacent; a key is covered for [lo, hi] only if one of its
        # merged intervals spans the whole range, so two scans with a gap
        # between them (e.g. Jan and Mar) don't falsely cover Feb.
        self._symbol_windows: dict[str, list[tuple[date, date]]] = {}
        self._cusip_windows: dict[str, list[tuple[date, date]]] = {}
        # The separator-free FTD spelling of each requested ticker that has a
        # separator ("BFB" -> "BF-B"); None marks a bare spelling two requested
        # tickers share, which is left unmapped.
        self._aliases: dict[str, str | None] = {}
        # A class ticker's observed names: a bare-spelled row is relabelled to it
        # only when its description agrees with one of them.
        self._names: dict[str, list[str]] = {}
        # The class ticker whose one-letter suffix sits on a symbol FTD spells whole ("UAC" -> ("UAC-C", "C"));
        # None marks a base two requested class tickers share.
        self._bases: dict[str, tuple[str, str] | None] = {}
        # The first day each requested ticker was observed: a base-symbol row dated from the base's own first
        # observation is the base's, not the class ticker's (rule A's date bound).
        self._own_from: dict[str, str] = {}
        for r in rows:
            self._add(r)

    def _learn(self, symbols: set[str], names: Mapping[str, Iterable[str]] | None = None,
               first_seen: Mapping[str, str] | None = None) -> set[str]:
        """Remember the separator spellings among `symbols` (and the observed
        names of any of them); returns the file filter: each symbol plus its
        separator-free spelling, and a one-letter class ticker's base ("UAC" of
        "UAC-C")."""
        for t, ns in (names or {}).items():
            t = normalize_ticker(t)
            self._names[t] = list(dict.fromkeys([*self._names.get(t, []), *(n for n in ns if n)]))
        for t, day in (first_seen or {}).items():
            t = normalize_ticker(t)
            self._own_from[t] = min(day, self._own_from.get(t, day))
        out = set(symbols)
        for s in symbols:
            bare = bare_ticker(s)
            if bare != s:
                out.add(bare)
                self._aliases[bare] = s if self._aliases.get(bare, s) == s else None
            suffix = class_suffix(s)
            if suffix:
                base, letter = suffix
                out.add(base)
                got = (s, letter)
                self._bases[base] = got if self._bases.get(base, got) == got else None
        return out

    def _relabel(self, r: FtdRow) -> FtdRow:
        """A row under a class ticker's bare spelling ("BFB"), keyed by the class
        ticker ("BF-B") when its description agrees with the ticker's observed
        names — or when none are known (an acquirer ticker), since there is
        nothing to check against. Another security trading under the bare
        symbol keeps it. This holds even when the bare spelling was requested
        too (index snapshots write "BFB" and "BF.B").

        A row under a class ticker's base ("UAC" of "UAC-C") is keyed by the
        class ticker only when the ticker's observed names are known, its
        description agrees with one of them and names the ticker's class letter
        ("UNDER ARMOUR INC CL C"): the base is usually another security's own
        symbol (HEICO's common HEI beside HEI-A, Lennar's class A LEN beside
        LEN-B, Viacom's class A VIA beside VIA-B), and it is dated before the base symbol's own first observation,
        when the run observes the base as a ticker (a class C spelled "UA-C" whose base "UA" became its own line's
        symbol on 2016-12-08 and was observed from then on)."""
        canon = self._aliases.get(r.symbol)
        if not canon:
            return self._relabel_base(r)
        names = self._names.get(canon)
        if names and not any(names_agree(r.description, n) for n in names):
            return r
        return replace(r, symbol=canon)

    def _relabel_base(self, r: FtdRow) -> FtdRow:
        got = self._bases.get(r.symbol)
        if not got:
            return r
        canon, letter = got
        names = self._names.get(canon)
        if (not names or description_class_letter(r.description) != letter
                or not any(names_agree(r.description, n) for n in names)):
            return r
        if r.date >= self._own_from.get(r.symbol, "~"):
            return r
        return replace(r, symbol=canon)

    def _add(self, r: FtdRow) -> None:
        r = self._relabel(r)
        if r in self._seen:
            return
        self._seen.add(r)
        self._by_symbol[r.symbol].append(r)
        self._by_cusip[r.cusip].append(r)
        self._dates.append(r.date)
        self._dirty = True

    @classmethod
    def opened(cls, source: FtdSource, lo: date, hi: date, *, through: date | None = None,
               symbols: Iterable[str] | None = None, cusips: Iterable[str] | None = None,
               names: Mapping[str, Iterable[str]] | None = None,
               first_seen: Mapping[str, str] | None = None) -> FtdIndex:
        """The run's index over `source`, opened with the rows of `symbols` and `cusips` over [lo, hi] (every row of
        the span when neither is given). Its run's fails window, which `follow` reads, is [lo, `through`] (default
        `hi`). `names`: observed names per class ticker, for the bare-spelling check; `first_seen`: the first day
        each observed ticker was seen, which bounds the base-symbol relabel."""
        idx = cls(source=source, window=(lo, through or hi))
        idx._learn(set(), names, first_seen)
        idx._scan(lo, hi,
                  None if symbols is None else {normalize_ticker(s) for s in symbols},
                  None if cusips is None else {c.upper() for c in cusips})
        return idx

    @property
    def opened_from(self) -> date | None:
        """The first day of the window this index was opened over (`opened`: the run's first fails day): every
        ticker and CUSIP it was opened with, and every key `follow` asked for, has its rows held from that day, so
        a CUSIP first held near it may have rows before it (`security_master.cusip_handoffs`). None for an index
        built from rows. No later ask moves it (`around` can read a key from earlier days)."""
        return self._window[0] if self._window else None

    def follow(self, *, cusips: Iterable[str] = (), symbols: Iterable[str] = ()) -> None:
        """Hold the rows of `cusips` and `symbols` over the run's fails window, [`opened_from`, the run date]: the
        securities' CUSIPs (stage 4), the lines' tickers and their spellings and each step's new CUSIPs (stage 4b).
        Nothing for an index with no source or no window."""
        if self._window is not None:
            self._ask(*self._window, cusips, symbols)

    def around(self, days: Iterable[date], *, before: int = 0, after: int = 0, cusips: Iterable[str] = (),
               symbols: Iterable[str] = ()) -> None:
        """Hold the rows of `cusips` and `symbols` from `before` days before the earliest of `days` to `after`
        days after the latest: a dead-before-sighting security's end (stage 5b), the delistings whose last trade
        came before the run's fails window (stage 7), every merger's last trade day for its acquirer tickers (stage
        8's gate). Nothing for no day, or an index with no source."""
        days = list(days)
        if days:
            self._ask(min(days) - timedelta(days=before), max(days) + timedelta(days=after), cusips, symbols)

    def apart(self, days: Iterable[date], *, before: int = 0, after: int = 0,
              cusips: Collection[str] = ()) -> FtdIndex:
        """A separate index of `cusips`' rows from `before` days before the earliest of `days` to `after` days
        after the latest, read from this index's source, with every row this index holds of them. This index is
        left as it was, so no later reader of it sees rows it did not ask for (stage 8a: the acquirer lines of a
        merger before the run's fails window). The separate index has no spellings of its own (no relabel), and is
        empty for no CUSIP."""
        days = list(days)
        out = FtdIndex(source=self._source)
        if not cusips or not days:
            return out
        if self._source is not None:
            out._scan(min(days) - timedelta(days=before), max(days) + timedelta(days=after), None,
                      {c.upper() for c in cusips})
        for r in (r for c in cusips for r in self.by_cusip(c)):
            out._add(r)
        return out

    def every_row(self, lo: date, hi: date) -> Iterator[FtdRow]:
        """Every row of the fails files dated in [lo, hi], as the files spell it (not relabelled), held nowhere:
        one pass over the span's files (stage 8a' reads a merger's acquirer by the description its first trading
        days carry). Nothing for an index with no source. A failed read raises, as the source's does."""
        if self._source is None:
            return
        lo_s, hi_s = lo.isoformat(), hi.isoformat()
        for url in self._source.urls_for(lo, hi):
            yield from (r for r in self._source.rows(url) if lo_s <= r.date <= hi_s)

    def _ask(self, lo: date, hi: date, cusips: Iterable[str], symbols: Iterable[str]) -> None:
        """Scan `[lo, hi]` for any of `cusips`/`symbols` not already covered by
        an earlier scan filtered on that exact key over at least that range. A
        CUSIP picked up only incidentally through a symbol filter (never itself
        used as a CUSIP filter) has no recorded CUSIP window, so it is rescanned
        here as a CUSIP filter — which is not symbol-restricted, so it catches
        that CUSIP's rows under any symbol (e.g. a ticker change). Rows already
        indexed are deduped via `_seen`."""
        if self._source is None:
            return
        cusips = {c.upper() for c in cusips}
        symbols = {normalize_ticker(s) for s in symbols}
        new_cusips = {c for c in cusips if not self._covered(self._cusip_windows.get(c, []), lo, hi)}
        new_symbols = {s for s in symbols if not self._covered(self._symbol_windows.get(s, []), lo, hi)}
        if new_cusips or new_symbols:
            self._scan(lo, hi, new_symbols or None, new_cusips or None)

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

    def _scan(self, lo: date, hi: date, symbols: set[str] | None, cusips: set[str] | None) -> None:
        lo_s, hi_s = lo.isoformat(), hi.isoformat()
        wanted = None if symbols is None else self._learn(symbols)
        for url in self._source.urls_for(lo, hi):
            for r in self._source.rows(url, symbols=wanted, cusips=cusips):
                if lo_s <= r.date <= hi_s:
                    self._add(r)
        for keys, windows in ((symbols, self._symbol_windows), (cusips, self._cusip_windows)):
            for k in keys or ():
                windows[k] = self._merge(windows.get(k, []), lo, hi)

    def _sort(self) -> None:
        if self._dirty:
            for m in (self._by_symbol, self._by_cusip):
                for v in m.values():
                    v.sort(key=lambda r: (r.date, r.cusip, r.symbol))
            self._dates.sort()
            self._dirty = False

    @staticmethod
    def _slice(rows: list[FtdRow], lo: str | None, hi: str | None) -> list[FtdRow]:
        dates = [r.date for r in rows]
        i = bisect_left(dates, lo) if lo else 0
        j = bisect_right(dates, hi) if hi else len(rows)
        return rows[i:j]

    def by_symbol(self, symbol: str, lo: str | None = None, hi: str | None = None) -> list[FtdRow]:
        """Rows under `symbol`. A class ticker's bare spelling ("BFB") gives every
        row FTD wrote under it: its own and those relabelled to the class ticker.
        A class ticker's base ("UAC" of "UAC-C") gives only the rows left under it:
        it is usually another security's own ticker (VIA beside VIA-B)."""
        self._sort()
        s = normalize_ticker(symbol)
        rows = self._by_symbol.get(s, [])
        canon = self._aliases.get(s)
        if canon:
            rows = sorted(rows + self._by_symbol.get(canon, []), key=lambda r: (r.date, r.cusip, r.symbol))
        return self._slice(rows, lo, hi)

    def by_cusip(self, cusip: str, lo: str | None = None, hi: str | None = None) -> list[FtdRow]:
        self._sort()
        return self._slice(self._by_cusip.get(cusip.upper(), []), lo, hi)

    def _file_periods(self) -> list[tuple[date, date]]:
        """The periods of the source's files (SEC's file names, `period_of`) that begin by the run date, read once:
        the fails data's own coverage. Empty when there is no file index: no source, or a file without a period (a
        test's double)."""
        if self._periods is None:
            hi = self._window[1] if self._window is not None else date.max
            urls = self._source.urls_for(FTD_START, hi) if self._source is not None else []
            got = [period_of(u) if isinstance(u, str) else None for u in urls]
            self._periods = [] if None in got else sorted(p for p in got if p is not None)
        return self._periods

    def data_covers(self, lo: str, hi: str) -> bool:
        """Whether the fails data covers some day of the ISO span [lo, hi], up to the run date: a file of the
        source's index has a period that meets it. Then a ticker this index was asked for over the span, with no
        row in it, did not fail then (`security_master.guarded_eras`). An index with no file index (built from
        rows, or over a double whose files carry no period) answers from the rows it holds, which are then all its
        data: some row held is dated in the span."""
        periods = self._file_periods()
        if not periods:
            self._sort()
            i = bisect_left(self._dates, lo)
            return i < len(self._dates) and self._dates[i] <= hi
        if self._window is not None:
            hi = min(hi, self._window[1].isoformat())
        return lo <= hi and any(a.isoformat() <= hi and b.isoformat() >= lo for a, b in periods)

    def data_end(self) -> str | None:
        """The last day the fails data covers, up to the run date (ISO): the end of the latest file period that
        begins by then, the run date when that period runs past it. The line follow's data edge, and stage 9's
        "after the fails data's last day" (OKE 2026). An index with no file index answers its latest row held;
        None when it holds none."""
        periods = self._file_periods()
        if not periods:
            self._sort()
            return self._dates[-1] if self._dates else None
        end = self._window[1] if self._window is not None else date.max
        ends = [min(b, end) for a, b in periods if a <= end]
        return max(ends).isoformat() if ends else None

    def descriptions(self, cusip: str) -> set[str]:
        """Every description the fails rows of `cusip` carry."""
        return {r.description for r in self.by_cusip(cusip)}

    def trading_rows(self, cusips: Iterable[str]) -> list[FtdRow]:
        """The rows of `cusips` (each CUSIP's by date, in the order given) that
        show the security trading: not those under a deleted symbol
        (`is_deleted_symbol`), which record a fail still settling after the
        delisting."""
        return [r for c in cusips for r in self.by_cusip(c) if not is_deleted_symbol(r.symbol)]

    def symbol_deleted(self, cusips: Iterable[str]) -> bool:
        """Whether `cusips` last failed under a deleted symbol only: after the
        first "…XXXX" row, no row under a live symbol. The security's symbol was
        deleted, so it no longer trades under it (HP's pre-2015 CUSIP fails as
        HPQXXXX after the separation, while EDGAR lists HPQ for today's line)."""
        rows = sorted((r for c in cusips for r in self.by_cusip(c)), key=lambda r: r.date)
        first = next((r.date for r in rows if is_deleted_symbol(r.symbol)), None)
        return first is not None and not any(r.date > first and not is_deleted_symbol(r.symbol) for r in rows)

    def close_after(self, day: date, *, cusip: str | None = None, symbol: str | None = None,
                    max_lag: int = 3, skip: Collection[str] = ()) -> tuple[float, str, bool] | None:
        """The close of `day`: the first priced row dated on the next trading day,
        or up to `max_lag` further trading days later (then `lagged` is True; rows
        after the last trade repeat the last close, but after an OTC move they
        carry OTC prices, so a lagged value is flagged for review). By symbol, a
        row of a CUSIP in `skip` (another security's) is not this one's."""
        first = next_trading_day(day)
        last = add_trading_days(first, max_lag)
        rows = (self.by_cusip(cusip, first.isoformat(), last.isoformat()) if cusip
                else [r for r in self.by_symbol(symbol or "", first.isoformat(), last.isoformat())
                      if r.cusip not in skip])
        for r in rows:
            if r.price is not None and r.price > 0:
                return r.price, r.date, r.date != first.isoformat()
        return None

    def close_through(self, day: date, *, cusip: str | None = None, symbol: str | None = None,
                      max_back: int = 10, skip: Collection[str] = ()) -> tuple[float, str] | None:
        """The latest close known on `day` when no row follows it: the priced row
        dated on `day` or up to `max_back` trading days earlier, whose price is
        the close of the trading day before its date. Fails stop once a security
        stops trading, so a merger's last trade day often has no row after it
        (Dell Inc.'s rows end on 2013-10-29, its last trade); the spec's
        fallback is to look back a few rows. Ten trading days (two weeks) keeps
        the price recent: a pending merger's target trades at a stable spread to
        its deal price. Returns `(price, row_date)`."""
        lo = add_trading_days(day, -max_back).isoformat()
        rows = (self.by_cusip(cusip, lo, day.isoformat()) if cusip
                else [r for r in self.by_symbol(symbol or "", lo, day.isoformat()) if r.cusip not in skip])
        for r in reversed(rows):
            if r.price is not None and r.price > 0:
                return r.price, r.date
        return None

    def close_of(self, day: date, *, cusip: str | None, symbol: str,
                 skip: Collection[str] = ()) -> tuple[float, str, bool] | None:
        """`close_after(day)` by `cusip` (the security's CUSIP on `day`, when
        known), then by `symbol`, never from a row of a CUSIP in `skip` (one
        another security holds: Wendy's/Arby's new CUSIP under WEN, 5d rule 3)."""
        return (self.close_after(day, cusip=cusip) if cusip else None) \
            or self.close_after(day, symbol=symbol, skip=skip)

    def close_known_on(self, day: date, *, cusip: str | None, symbol: str,
                       skip: Collection[str] = ()) -> tuple[float, str] | None:
        """`close_through(day)` -- when no row follows `day`, the latest close
        known on it -- by `cusip` (the security's CUSIP on `day`, when known),
        then by `symbol` (skipping `skip`'s CUSIPs, as `close_of`)."""
        return (self.close_through(day, cusip=cusip) if cusip else None) \
            or self.close_through(day, symbol=symbol, skip=skip)


def close_age(row_date: str, last_trade: date) -> int:
    """Trading days from the close a fails row dated `row_date` carries (that of
    the trading day before it) to `last_trade`: 1 for a row dated the last
    trade day itself."""
    day, n = previous_trading_day(date.fromisoformat(row_date)), 0
    while day < last_trade:
        day, n = next_trading_day(day), n + 1
    return n

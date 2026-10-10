"""A security's dated history: its sightings (observations and SEC
fails-to-deliver rows) under each ticker and CUSIP, turned into the
`ticker_history` and `cusip_history` ranges, and the review of those ranges
(spec §8.5). The security master (`security_master.py`) decides which eras are
one security; this module dates what that security was called when, and where its history ends.

Where a history ends is one module (`Histories`): the caller passes each observed security, its sightings, its
CUSIPs, the fails index, a summary of every ending (`Ending`, built from a delisting by `Delisting.ending`), the
listed-today answers and the securities the run adds. It answers which endings do not end their security
(`going_on`), each security's end (`end`: the day, whether it is a confirmed last trade, whether it is listed today),
its ranges (`ticker_rows`, `cusip_rows`) and observation_map.csv's rows (`observation_map_rows`). Three rules live
behind it: which ending clips the history (`CONTINUATION_BUCKETS`, the continues-after test), from which day a
successor or another security owns a ticker, and whether the security is still listed today (AON 2012)."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import cached_property
from typing import NamedTuple

from .added_securities import AddedSecurity
from ..vocabulary.crsp_codes import CrspBucket
from ..vocabulary.exit_kind import LastTrade, end_day
from ..sources.ftd import FtdIndex, is_deleted_symbol, is_unassigned_symbol
from ..vocabulary.identifiers import bare_ticker
from ..vocabulary.names import description_matches
from .observations import TickerEra
from ..outputs.review_triage import ReviewItem
from .security_master import Security
from ..outputs.store import DelistingKey

BACKFILL_START = "2004-01-31"      # spec §7.x: the earliest as_of the backfilled_ticker check applies to
BACKFILL_WINDOW_DAYS = 30


# A sighting's sources: an observation, a fails row, or a day of an added security's span (stage 9d, which no
# observation names: `span_sightings`)
OBSERVATION, FTD, SPAN = "observation", "ftd", "span"


class Sighting(NamedTuple):
    """One dated sighting of a security's ticker or CUSIP (`value`), from an
    observation, an FTD row or an added security's span (`source`: `OBSERVATION`, `FTD`, `SPAN`)."""
    day: str
    value: str
    source: str


@dataclass(frozen=True)
class Range:
    value: str
    valid_from: str
    valid_to: str | None
    source: str


def value_on(ranges: Iterable[Range], day: date) -> str | None:
    """The value of the range that holds `day`, if any."""
    d = day.isoformat()
    return next((r.value for r in ranges if r.valid_from <= d and (r.valid_to is None or d <= r.valid_to)), None)


def ranges_from_sightings(sightings: Iterable[Sighting], *, end: str | None,
                          open_ended: bool) -> list[Range]:
    """Dated `(day, value, source)` sightings (`Sighting`) -> consecutive ranges of one value.

    Each range runs from its first sighting to the day before the next range's
    first sighting; the last one ends at `end`, or stays open (`open_ended`),
    or ends at its last sighting. A value seen only once, and only in FTD
    rows, is noise and dropped. Sightings after `end` are ignored.

    One day keeps one value: an observation beats an FTD row; then a value the
    caller observed; then the value of the range already running (so a day
    that sighted two tickers doesn't cut the running range); then the spelling
    with a separator ("BF-B" over "BFB"); then the alphabetically first. So
    every range has `valid_to >= valid_from`.
    """
    items = sorted({x for x in sightings if end is None or x[0] <= end})
    ftd_counts = Counter(v for _, v, s in items if s == "ftd")
    obs_values = {v for _, v, s in items if s == "observation"}
    items = [(d, v, s) for d, v, s in items if s == "observation" or ftd_counts[v] > 1 or v in obs_values]
    by_day: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for d, v, s in items:
        by_day[d].append((v, s))
    runs: list[list] = []                        # [value, first, last, sources]
    for d in sorted(by_day):
        running = runs[-1][0] if runs else None
        v, _ = min(by_day[d], key=lambda vs: (vs[1] != "observation", vs[0] not in obs_values, vs[0] != running,
                                              "-" not in vs[0], vs[0]))
        sources = {s for x, s in by_day[d] if x == v}
        if runs and runs[-1][0] == v:
            runs[-1][2] = d
            runs[-1][3] |= sources
        else:
            runs.append([v, d, d, sources])
    out: list[Range] = []
    for i, (v, first, last, sources) in enumerate(runs):
        if i + 1 < len(runs):
            to: str | None = (date.fromisoformat(runs[i + 1][1]) - timedelta(days=1)).isoformat()
        elif end is not None:
            to = end
        elif open_ended:
            to = None
        else:
            to = last
        if to is not None and to < first:
            continue                              # never an inverted range
        out.append(Range(v, first, to, "observation" if "observation" in sources else "ftd"))
    return out


def ticker_sightings(sec: Security, ftd: FtdIndex, cusips: Sequence[str]) -> list[Sighting]:
    """Dated `(day, ticker, source)` sightings of the security: its observations
    (under their era's ticker: a when-issued observation, EHAB-WI, is a sighting
    of its regular-way ticker, EHAB) and the FTD rows of its CUSIPs. A ticker spelled with or without separators
    ("BF-B" / "BFB": snapshots write both, FTD keys rows by the separator form)
    is written one way per security: a spelling it was observed under, the one
    with a separator first. So Hubbell's merged class keeps "HUBB" while class
    B, observed as "HUB-B" and "HUBB", is "HUB-B". A row under a deleted
    symbol ("ORLYXXXX") is a fail still settling after the delisting, not a
    sighting of trading: it opens and extends no range, and counts in no
    `seen_after`, `last_seen` or sibling span (`trading_record.TradingRecord`)."""
    return _sightings([Sighting(o.as_of, e.ticker, OBSERVATION) for e in sec.eras for o in e.observations],
                      {e.ticker for e in sec.eras}, ftd, cusips)


def span_sightings(ticker: str, days: Iterable[str], ftd: FtdIndex, cusips: Sequence[str]) -> list[Sighting]:
    """An added security's sightings (stage 9d: a successor no observation names): the days of its span under its
    ticker (source `SPAN`) and the FTD rows of its CUSIPs, spelled as `ticker_sightings` spells them."""
    return _sightings([Sighting(d, ticker, SPAN) for d in days], {ticker}, ftd, cusips)


def _sightings(seen: list[Sighting], tickers: Iterable[str], ftd: FtdIndex, cusips: Sequence[str]) -> list[Sighting]:
    """`seen` and the FTD rows of `cusips`, each ticker spelled one way: a spelling of `tickers`, the one with a
    separator first (`ticker_sightings`)."""
    # SEC's 2007 fails files mask some symbols (**********), and a new CUSIP's first rows carry the ticker with
    # "ZZZZ" appended (FMDZZZZ): neither is a ticker
    out = seen + [Sighting(r.date, r.symbol, FTD) for r in ftd.trading_rows(cusips)
                  if any(ch.isalpha() for ch in r.symbol) and not is_unassigned_symbol(r.symbol)]
    label: dict[str, str] = {}
    for t in sorted(set(tickers), key=lambda t: ("-" not in t, t)):
        label.setdefault(bare_ticker(t), t)
    return sorted({s._replace(value=label.get(bare_ticker(s.value), s.value)) for s in out})


def cusip_sightings(sec: Security, ftd: FtdIndex, cusips: Sequence[str],
                    successor_starts: Mapping[str, str] = {}) -> list[Sighting]:
    """Dated `(day, cusip, source)` sightings of the security's CUSIPs: the FTD
    rows of each CUSIP that resolved to it (not those under a deleted symbol,
    nor under a ticker a successor security took from `successor_starts`' day on),
    and the CUSIPs its observations carry."""
    rows = ftd.trading_rows(cusips)
    began = {c: min(r.date for r in rows if r.cusip == c) for c in {r.cusip for r in rows}}

    def _settling(r) -> bool:
        """An unassigned-symbol (`…ZZZZ`) row of a CUSIP dated once another CUSIP of the security, begun after it,
        has begun: the old line's fails still settling after the switch (MSG 2015: MSGZZZZ to 10-07, MSGN's CUSIP
        began 10-06), no sighting of the CUSIP."""
        return is_unassigned_symbol(r.symbol) and any(
            began[r.cusip] < b <= r.date for c, b in began.items() if c != r.cusip)

    out = [Sighting(r.date, r.cusip, "ftd") for r in rows
           if r.date < successor_starts.get(r.symbol, "~") and not _settling(r)]
    out += [Sighting(o.as_of, o.cusip, "observation") for e in sec.eras for o in e.observations if o.cusip]
    return sorted(set(out))


def _security_rows(sec: Security, sightings: Sequence[Sighting], cusip_sightings: Sequence[Sighting], *,
                   listed: bool, end: str | None, end_exchange: str | None,
                   exchange_today: Callable[[str], str | None],
                   successor_starts: Mapping[str, str] = {}) -> tuple[list[dict], list[dict]]:
    """The security's ticker_history and cusip_history rows: its sightings, up to
    `end` when it has one (the end day of its last delisting, when it is
    not listed today), as ranges (`ranges_from_sightings`), open-ended while it
    is `listed`. The ticker range that ends at `end` carries that delisting's
    exchange (`end_exchange`); an open range the exchange EDGAR lists for its
    ticker today (`exchange_today(ticker)`); any other range none.

    `successor_starts` (ticker -> the day a successor security took it, `Histories._successor_starts`): sightings
    under that ticker from that day on are the successor's, not this security's, so the ticker's range ends the
    day before (and a range that would start then is dropped)."""
    th_rows, ch_rows = [], []
    clipped = [x for x in sightings if (end is None or x.day <= end) and x.day < successor_starts.get(x.value, "~")]
    for rg in ranges_from_sightings(clipped, end=end, open_ended=listed):
        start = successor_starts.get(rg.value)
        valid_to = rg.valid_to
        if start is not None and (valid_to is None or valid_to >= start):
            valid_to = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
            if valid_to < rg.valid_from:
                continue
        rg = replace(rg, valid_to=valid_to) if valid_to != rg.valid_to else rg
        if end is not None and rg.valid_to == end:
            exch = end_exchange
        elif rg.valid_to is None:
            exch = exchange_today(rg.value)
        else:
            exch = None
        th_rows.append({"sec_id": sec.sec_id, "ticker": rg.value, "exchange": exch, "valid_from": rg.valid_from,
                        "valid_to": rg.valid_to, "source": rg.source})
    cus = [x for x in cusip_sightings if end is None or x.day <= end]
    for rg in ranges_from_sightings(cus, end=end, open_ended=listed):
        ch_rows.append({"sec_id": sec.sec_id, "cusip": rg.value, "valid_from": rg.valid_from,
                        "valid_to": rg.valid_to, "source": rg.source})
    return th_rows, ch_rows


def _clip_at_takeovers(th_rows: list[dict], sightings: Mapping[str, Sequence[Sighting]],
                       ends: Mapping[str, str | None]) -> list[dict]:
    """`th_rows` with a range that runs into another security's first day under its ticker ended the day before it,
    when its own security was last sighted under the ticker before that day and the range does not end at its
    security's end: the range was only carried forward to the security's next ticker (MSG 2015: the old line's MSG
    ran to the day before MSGN's first row, one day into the new MSG's). A ticker a security keeps sighting is never
    clipped (a shared ticker stays `ticker_shared`'s to flag). The second of the two takeover conditions
    (`Histories`): this one reads the built ranges of every security, the successor's reads the endings."""
    first: dict[str, list[tuple[str, str]]] = defaultdict(list)      # ticker -> [(valid_from, sec_id)]
    for r in th_rows:
        first[r["ticker"]].append((r["valid_from"], r["sec_id"]))
    out = []
    for r in th_rows:
        to = r["valid_to"]
        if to is not None and to != ends.get(r["sec_id"]):
            later = sorted(f for f, sid in first[r["ticker"]] if sid != r["sec_id"] and r["valid_from"] < f <= to)
            if later and not any(g.value == r["ticker"] and g.day >= later[0] for g in sightings.get(r["sec_id"], ())):
                r = {**r, "valid_to": (date.fromisoformat(later[0]) - timedelta(days=1)).isoformat()}
        out.append(r)
    return out


def _overlaps(a: dict, b: dict) -> bool:
    a_to = a["valid_to"] or "9999-12-31"
    b_to = b["valid_to"] or "9999-12-31"
    return a["valid_from"] <= b_to and b["valid_from"] <= a_to


def ticker_range_review(th_rows: list[dict]) -> list[ReviewItem]:
    """Flag, without changing, two `ticker_history` problems (spec 8.5):
    (a) one security's own ranges overlapping (`ticker_range_overlap`), and
    (b) one ticker mapping to two different securities on the same day
    (`ticker_shared`). Each violation names both ranges in its reason."""
    out: list[ReviewItem] = []

    by_sec: dict[str, list[dict]] = defaultdict(list)
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in th_rows:
        by_sec[r["sec_id"]].append(r)
        by_ticker[r["ticker"]].append(r)

    def _name(r: dict) -> str:
        return f"{r['ticker']} {r['valid_from']}..{r['valid_to'] or ''}"

    for sid, rows in by_sec.items():
        rs = sorted(rows, key=lambda r: r["valid_from"])
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if _overlaps(rs[i], rs[j]):
                    out.append(ReviewItem(sid, rs[i]["ticker"], None, "ticker_range_overlap",
                                          f"{_name(rs[i])} overlaps {_name(rs[j])}"))

    for ticker, rows in by_ticker.items():
        rs = sorted(rows, key=lambda r: r["valid_from"])
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if rs[i]["sec_id"] == rs[j]["sec_id"] or not _overlaps(rs[i], rs[j]):
                    continue
                out.append(ReviewItem(rs[i]["sec_id"], ticker, None, "ticker_shared",
                                      f"{_name(rs[i])} ({rs[i]['sec_id']}) overlaps "
                                      f"{_name(rs[j])} ({rs[j]['sec_id']})"))
    return out


def is_backfilled(as_of: str, ticker: str, cusips: Sequence[str], ftd: FtdIndex) -> bool:
    """spec §7.x rule 4: `as_of` is on or after `BACKFILL_START`, no fails-to-deliver
    row of `cusips` under `ticker` (either separator spelling) within
    `BACKFILL_WINDOW_DAYS` days of `as_of`, and at least one such row under
    another symbol in that window -- a snapshot source backfilled a ticker the
    security was not actually seen trading under then (Yahoo stays YHOO in
    2012 fails; a 2012 snapshot backfills CB, Chubb's later ticker). Used both
    for `observation_map.csv`'s `backfilled_ticker` status and (Phase 4 rule 2)
    to drop a backfilled observation from `ticker_history`'s own sightings."""
    if as_of < BACKFILL_START or not cusips:
        return False
    day = date.fromisoformat(as_of)
    lo = (day - timedelta(days=BACKFILL_WINDOW_DAYS)).isoformat()
    hi = (day + timedelta(days=BACKFILL_WINDOW_DAYS)).isoformat()
    rows = [r for r in ftd.trading_rows(cusips) if lo <= r.date <= hi]
    if not rows:
        return False
    bare = bare_ticker(ticker)
    own = any(bare_ticker(r.symbol) == bare for r in rows)
    other = any(bare_ticker(r.symbol) != bare for r in rows)
    return not own and other


def filtered_ticker_sightings(sightings: Sequence[Sighting], cusips: Sequence[str],
                              ftd: FtdIndex) -> list[Sighting]:
    """`sightings` (a security's dated ticker sightings, `ticker_sightings`) with
    every observation sighting `is_backfilled` drops (Phase 4 rule 2): a
    caller's snapshot that assigned a ticker to a security before any SEC
    fails-to-deliver row shows it trading that way adds no `ticker_history`
    range under that spelling (Yahoo stays YHOO in 2012; the Chubb line loses
    its backfilled CB 2012-14 ranges). FTD sightings are untouched -- they are
    the evidence a backfilled ticker lacks -- and so is the delisting search's
    own copy of `ticker_sightings`, which never calls this."""
    return [s for s in sightings if not (s.source == "observation" and is_backfilled(s.day, s.value, cusips, ftd))]


# -- where a security's history ends ---------------------------------------------------------------------------------
CONTINUATION_MIN_ROWS = 20    # a WRK-like delisting record's own CUSIP must show at least this many live fails rows...
CONTINUATION_MIN_DAYS = 60    # ...spanning at least this many days...
CONTINUATION_MIN_PRICES = 2   # ...at 2 or more distinct prices, so fails still settling at the last close don't count
# The continues-trading exception only ever questions a delisting whose bucket
# is a reorganization that can plausibly leave the listing itself running (a
# holdco merger, an exchange transfer) -- never a liquidation, compliance
# failure or expiration, whose whole premise is that the exchange listing
# ended: ticker_history records exchange listings (CONTEXT.md "Listing"), and
# OTC pink-sheet fails after a real bankruptcy delisting are not that listing
# continuing (RHD, Smurfit-Stone, Idearc, GGP, SunPower, Endo: real, varied-
# price OTC trading for years, but the exchange listing itself is long gone).
CONTINUATION_BUCKETS = frozenset({CrspBucket.MERGER, CrspBucket.EXCHANGE_TRANSFER})
# A handoff's window (`handoffs.find_handoffs`) and a successor's: another security's first sighting under a ticker at
# most this long after the old one's last (COHR: 74); a later one is a recycled ticker.
TAKEOVER_DAYS = 120
# with no confirmed last trade, a successor's first row may precede the delist date (STX: 9 days)
SUCCESSOR_TICKER_LOOKBACK_DAYS = 30


@dataclass(frozen=True)
class Ending:
    """One ending of a security as its history reads it (`delistings.Delisting.ending` builds it): its key, its last
    trade (`LastTrade.confirmed` and `exit_kind.end_day` are read from it), its bucket, its successor (None: none;
    the security's own sec_id: the security went on) and the exchange it left."""
    key: DelistingKey
    last_trade: LastTrade
    bucket: CrspBucket
    successor: str | None
    exchange: str

    @property
    def sec_id(self) -> str:
        return self.key.sec_id

    @property
    def delist_date(self) -> str:
        return self.key.delist_date

    @property
    def real(self) -> bool:
        """It ended its security: its successor is not the security itself (`rewrites.is_real_ending`)."""
        return self.successor != self.key.sec_id


@dataclass(frozen=True)
class SecurityEnd:
    """Where one security's history ends: `day` (ISO), the end day of the last ending that ends it, or None while it is
    listed today or when nothing ends it; whether that day is a confirmed last trade (`confirmed`, false with no day);
    and whether the security is `listed` today."""
    day: str | None = None
    confirmed: bool = False
    listed: bool = False


class Histories:
    """The observed securities' histories over one set of endings: which endings end their security, where each
    history ends, and its ranges. Pure: every input is data, and the one read it makes, the exchange EDGAR lists today
    for an open range's ticker, goes through `exchange_today(security, ticker)`, asked only when `ticker_rows` is.

    - `securities`: the observed securities, by sec_id. Endings of any other security are not read.
    - `sightings`: their dated ticker sightings (`ticker_sightings`); a backfilled observation is dropped here
      (`filtered_ticker_sightings`).
    - `cusips`, `ftd`: each security's CUSIPs and the fails index their rows come from.
    - `endings`: every ending of the run, in the run's order (the last of two on one delisting date wins).
    - `listed`: the listed-today answers (None: unknown, read as not listed).
    - `added`: the securities the run adds; an added successor is seen under its ticker from its first day.

    The three rules:
    - An ending ends its security unless its successor is the security itself, or it is a merger or exchange transfer
      with a confirmed last trade after which the security's own CUSIPs keep trading under its own tickers
      (`_continues_after`: DIS 2019, WRK 2018). Those that do not are `going_on` (`rewrites.mark_going_on`).
    - A successor's ticker is not its predecessor's (`_successor_starts`: AON 2012, STX 2021, CRC 2016, ODP 2020),
      and a range carried only to the security's next ticker stops before another security's first day under it
      (`_clip_at_takeovers`: MSG 2015). Two conditions, not one: the first reads the endings and bounds the
      predecessor's own sightings, CUSIP rows and listing (the predecessor keeps being sighted under the ticker); the
      second reads the built ranges of any security (the taker is no successor).
    - A security is listed today as `listed` says, except one with an ending that ends it whose ticker a successor
      took: the issuer's listing is the successor's (AON 2012). Its history ends at the end day
      (`exit_kind.end_day`) of its last ending that ends it, unless it is listed today."""

    def __init__(self, securities: Mapping[str, Security], sightings: Mapping[str, Sequence[Sighting]],
                 cusips: Mapping[str, Sequence[str]], ftd: FtdIndex, endings: Iterable[Ending], *,
                 listed: Mapping[str, bool | None], added: Mapping[str, AddedSecurity] = {},
                 exchange_today: Callable[[Security, str], str | None] = lambda security, ticker: None):
        self._securities = securities
        self._sightings = sightings
        self._cusips = cusips
        self._ftd = ftd
        self._exchange_today = exchange_today
        self._own_memo: dict[str, list[Sighting]] = {}
        endings = [e for e in endings if e.sec_id in securities]
        self._starts = self._successor_starts(endings, added)
        ends: dict[DelistingKey, bool] = {}
        for e in endings:
            ends[e.key] = self._ends(e)
        self.going_on: frozenset[DelistingKey] = frozenset(k for k, v in ends.items() if not v)
        self._final: dict[str, Ending] = {}
        for e in sorted(endings, key=lambda e: e.delist_date):
            if ends.get(e.key):
                self._final[e.sec_id] = e
        self._ends_of: dict[str, SecurityEnd] = {}
        for sid in securities:
            last = self._final.get(sid)
            is_listed = bool(listed.get(sid))
            if is_listed and last is not None and sid in self._starts:
                is_listed = False         # AON 2012: the issuer lists the successor's ticker today
            if last is not None and not is_listed:
                # An unconfirmed last trade, or none, still clips the ranges (at the guess, else the delisting
                # date): an unclipped range would run past the security's real end.
                self._ends_of[sid] = SecurityEnd(end_day(last.last_trade, last.delist_date).isoformat(),
                                                 last.last_trade.confirmed, False)
            else:
                self._ends_of[sid] = SecurityEnd(listed=is_listed)

    def end(self, sec_id: str) -> SecurityEnd:
        """Where the security's history ends (a security the history was not built over: open, not listed)."""
        return self._ends_of.get(sec_id, SecurityEnd())

    @property
    def ticker_rows(self) -> list[dict]:
        """The ticker_history rows (kept in memory, contract/security_history.csv is published from them) of the observed securities."""
        return self._rows[0]

    @property
    def cusip_rows(self) -> list[dict]:
        """cusip_history.csv's rows of the observed securities."""
        return self._rows[1]

    @cached_property
    def _rows(self) -> tuple[list[dict], list[dict]]:
        th_rows, ch_rows = [], []
        for sid, s in self._securities.items():
            end = self._ends_of[sid]
            last = self._final.get(sid)
            starts = self._starts.get(sid, {})
            th, ch = _security_rows(
                s, self._own(sid), cusip_sightings(s, self._ftd, self._cusips.get(sid, []), starts),
                listed=end.listed, end=end.day, end_exchange=last.exchange if last else None,
                exchange_today=lambda ticker, s=s: self._exchange_today(s, ticker), successor_starts=starts)
            th_rows += th
            ch_rows += ch
        th_rows = _clip_at_takeovers(th_rows, {sid: self._own(sid) for sid in self._securities},
                                     {sid: e.day for sid, e in self._ends_of.items()})
        return th_rows, ch_rows

    def _own(self, sec_id: str) -> list[Sighting]:
        """The security's ticker sightings the ranges are built from: a backfilled observation dropped (Phase 4 rule
        2); the delisting search's own sightings are untouched."""
        if sec_id not in self._own_memo:
            self._own_memo[sec_id] = filtered_ticker_sightings(self._sightings.get(sec_id, []),
                                                               self._cusips.get(sec_id, []), self._ftd)
        return self._own_memo[sec_id]

    def _successor_starts(self, endings: Sequence[Ending],
                          added: Mapping[str, AddedSecurity]) -> dict[str, dict[str, str]]:
        """A successor's ticker is not its predecessor's: for each security S, the tickers a successor security X
        (an ending's successor, not S itself) took, and from which day: X's first sighting under the ticker on or
        after the ending's confirmed last trade day (`LastTrade.confirmed`; an unconfirmed or missing one: its delist
        date, less `SUCCESSOR_TICKER_LOOKBACK_DAYS`) and within `TAKEOVER_DAYS` after that day; a ticker first seen
        later is a recycled one, no start. S's fails rows and sightings under the ticker from that day on are X's."""
        out: dict[str, dict[str, str]] = {}
        for e in endings:
            x = e.successor
            if not x or x == e.sec_id:
                continue
            confirmed = e.last_trade.confirmed
            try:
                anchor = e.last_trade.day if confirmed else date.fromisoformat(e.delist_date)
            except ValueError:
                continue
            lo = (anchor if confirmed else anchor - timedelta(days=SUCCESSOR_TICKER_LOOKBACK_DAYS)).isoformat()
            hi = (anchor + timedelta(days=TAKEOVER_DAYS)).isoformat()
            if x in self._securities:
                sig = self._own(x)
            elif x in added:
                sig = [Sighting(added[x].span()[0], added[x].ticker, "ftd")]
            else:
                continue
            mine = out.setdefault(e.sec_id, {})
            for g in sorted(sig):
                if lo <= g.day <= hi and g.day < mine.get(g.value, "~"):
                    mine[g.value] = g.day
        return {sid: m for sid, m in out.items() if m}

    def _ends(self, e: Ending) -> bool:
        """Whether ending `e` ends its security: not one whose successor is the security itself (a continuing
        exchange transfer, D18); and, for a merger or exchange transfer whose last trade is confirmed
        (`LastTrade.confirmed`; an unconfirmed day is a guess, the no-Form-25 fallback's last sighting, too weak to
        test continued trading against: Monster Worldwide's and SunPower's 2008-09 rows, Bank of Ozarks with no day),
        not one after which the security's own CUSIPs keep trading under its own tickers (`_continues_after`). A
        liquidation, compliance failure, expiration or unknown ending always ends it, whatever fails rows follow."""
        if not e.real:
            return False
        if e.bucket not in CONTINUATION_BUCKETS or not e.last_trade.confirmed:
            return True
        return not self._continues_after(e.sec_id, e.last_trade.day.isoformat())

    def _continues_after(self, sec_id: str, after: str) -> bool:
        """Whether the security's own CUSIPs keep trading under its own tickers (its eras' and its line's) strictly
        after the ISO day `after` (Phase 4's clip rule): at least `CONTINUATION_MIN_ROWS` live fails rows (never a
        deleted symbol; a fail still settling after the real end) over at least `CONTINUATION_MIN_DAYS` days, with
        `CONTINUATION_MIN_PRICES` or more distinct prices -- so a compliance failure's OTC tail settling at one price is
        not continued trading (WRK stops being clipped; ARD and compliance failures stay clipped). Rows under a ticker
        a successor took (`_successor_starts`) from that day on are the successor's (AON 2012: Aon plc's AON, the old
        CUSIP's lingering fails)."""
        own = self._securities[sec_id].own_tickers()
        starts = self._starts.get(sec_id, {})
        rows = [r for r in self._ftd.trading_rows(self._cusips.get(sec_id, []))
                if r.symbol in own and r.date > after and r.date < starts.get(r.symbol, "~")]
        if len(rows) < CONTINUATION_MIN_ROWS:
            return False
        dates = [r.date for r in rows]
        if (date.fromisoformat(max(dates)) - date.fromisoformat(min(dates))).days < CONTINUATION_MIN_DAYS:
            return False
        return len({r.price for r in rows if r.price is not None}) >= CONTINUATION_MIN_PRICES


def _in_ticker_history(ticker: str, as_of: str, ranges: Sequence[Range]) -> bool:
    bare = bare_ticker(ticker)
    return any(bare_ticker(r.value) == bare and r.valid_from <= as_of and (r.valid_to is None or as_of <= r.valid_to)
              for r in ranges)


def _observation_status(as_of: str, ticker: str, sec_id: str | None, end: SecurityEnd, conflict: bool,
                        cusips: Sequence[str], ftd: FtdIndex) -> str:
    """The first rule that applies (spec §7.x): `unresolved` (no `sec_id`),
    `after_unconfirmed_delisting` (the security is not listed today, `as_of`
    is past its clipped history end, and the delisting that set that clip has
    no confirmed last-trade day -- the clip is a guess, so the caller keeps
    and checks this member rather than dropping it), `after_delisting` (same,
    but the ending delisting's last-trade day is confirmed), `conflict`
    ((ticker, as_of) is a two-name observation conflict), `backfilled_ticker`
    (`is_backfilled`), else `mapped`."""
    if sec_id is None:
        return "unresolved"
    if not end.listed and end.day is not None and as_of > end.day and not end.confirmed:
        return "after_unconfirmed_delisting"
    if not end.listed and end.day is not None and as_of > end.day:
        return "after_delisting"
    if conflict:
        return "conflict"
    if is_backfilled(as_of, ticker, cusips, ftd):
        return "backfilled_ticker"
    return "mapped"


def observation_map_rows(eras: Iterable[TickerEra], sec_id_of: Mapping[str, str | None],
                         issuer_cik_of: Mapping[str, int | None], history: Histories,
                         conflicts: Iterable[tuple[str, str]]) -> list[dict]:
    """observation_map.csv's rows (spec §7.x): one row per observation of `eras`
    (every era of the run, refined; `--limit` already trims which ones), naming
    its era, its sec_id (`sec_id_of`, keyed by era key; None when unresolved)
    and issuer CIK (`issuer_cik_of`), the `ticker_history` spelling and coverage
    on its date (`history_ticker`/`in_ticker_history`, from the history's own ranges), and a `status`
    (`_observation_status`).

    `after_delisting`/`after_unconfirmed_delisting` read the history's own end (`Histories.end`: the day, whether it
    is a confirmed last trade, whether the security is listed today), so they never recompute what the ranges
    decided: an unconfirmed end (a guess, e.g. Bank of Ozarks' no-Form-25 fallback with no day at all) picks the
    second status."""
    ranges_by_sec: dict[str, list[Range]] = defaultdict(list)
    for r in history.ticker_rows:
        ranges_by_sec[r["sec_id"]].append(Range(r["ticker"], r["valid_from"], r["valid_to"], r["source"]))
    conflict_set = set(conflicts)
    out: list[dict] = []
    for era in eras:
        sec_id = sec_id_of.get(era.key)
        issuer_cik = issuer_cik_of.get(era.key)
        ranges = ranges_by_sec.get(sec_id, []) if sec_id is not None else []
        cusips = history._cusips.get(sec_id, []) if sec_id is not None else ()
        end = history.end(sec_id) if sec_id else SecurityEnd()
        for o in era.observations:
            # Status and coverage are read under the era's ticker (a when-issued observation's regular-way one);
            # the row keeps the ticker the caller observed, its join key.
            status = _observation_status(o.as_of, era.ticker, sec_id, end, (o.ticker, o.as_of) in conflict_set,
                                         cusips, history._ftd)
            out.append({
                "ticker": o.ticker, "as_of": o.as_of, "name": o.name, "cusip": o.cusip, "pin_cik": o.cik,
                "pin_sec_id": o.sec_id, "era": era.key, "sec_id": sec_id, "issuer_cik": issuer_cik,
                "history_ticker": value_on(ranges, date.fromisoformat(o.as_of)) if ranges else None,
                "in_ticker_history": _in_ticker_history(era.ticker, o.as_of, ranges),
                "status": status,
            })
    return out


BACKFILL_CUSIP_DAYS = 120     # the days before a dead-before-sighting security's end whose rows name its CUSIP


def backfill_cusips(tickers: Iterable[str], end: str, ftd: FtdIndex, names: Iterable[str]) -> list[str]:
    """The CUSIPs of a security that died before its first sighting: those of the
    fails rows under one of its `tickers` in the BACKFILL_CUSIP_DAYS before its `end`
    (ISO), not under a deleted symbol, whose description names its issuer
    (`names.description_matches` against its observed and EDGAR `names`). Rows
    after the end never count: a later issuer may reuse the ticker. Most rows first."""
    names = list(names)
    lo = (date.fromisoformat(end) - timedelta(days=BACKFILL_CUSIP_DAYS)).isoformat()
    counts: Counter[str] = Counter()
    for t in sorted(set(tickers)):
        for r in ftd.by_symbol(t, lo, end):
            if not is_deleted_symbol(r.symbol) and description_matches(r.description, names, empty=False):
                counts[r.cusip] += 1
    return [c for c, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

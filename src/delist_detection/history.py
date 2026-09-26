"""A security's dated history: its sightings (observations and SEC
fails-to-deliver rows) under each ticker and CUSIP, turned into the
`ticker_history` and `cusip_history` ranges, and the review of those ranges
(spec §8.5). The security master (`security_master.py`) decides which eras are
one security; this module dates what that security was called when."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple

from .ftd import FtdIndex
from .review_triage import ReviewItem
from .security_master import Security


class Sighting(NamedTuple):
    """One dated sighting of a security's ticker or CUSIP (`value`), from an
    observation or an FTD row (`source`: "observation" | "ftd")."""
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
    and the FTD rows of its CUSIPs. A ticker spelled with or without separators
    ("BF-B" / "BFB": snapshots write both, FTD keys rows by the separator form)
    is written one way per security: a spelling it was observed under, the one
    with a separator first. So Hubbell's merged class keeps "HUBB" while class
    B, observed as "HUB-B" and "HUBB", is "HUB-B". A row under a deleted
    symbol ("ORLYXXXX") is a fail still settling after the delisting, not a
    sighting of trading: it opens and extends no range, and counts in no
    `seen_after`, `last_seen` or sibling span."""
    out = [Sighting(o.as_of, o.ticker, "observation") for e in sec.eras for o in e.observations]
    out += [Sighting(r.date, r.symbol, "ftd") for r in ftd.trading_rows(cusips)]
    label: dict[str, str] = {}
    for t in sorted({o.ticker for e in sec.eras for o in e.observations}, key=lambda t: ("-" not in t, t)):
        label.setdefault(t.replace("-", ""), t)
    return sorted({s._replace(value=label.get(s.value.replace("-", ""), s.value)) for s in out})


def cusip_sightings(sec: Security, ftd: FtdIndex, cusips: Sequence[str]) -> list[Sighting]:
    """Dated `(day, cusip, source)` sightings of the security's CUSIPs: the FTD
    rows of each CUSIP that resolved to it (not those under a deleted symbol),
    and the CUSIPs its observations carry."""
    out = [Sighting(r.date, r.cusip, "ftd") for r in ftd.trading_rows(cusips)]
    out += [Sighting(o.as_of, o.cusip, "observation") for e in sec.eras for o in e.observations if o.cusip]
    return sorted(set(out))


def ticker_on(sightings: Sequence[Sighting]) -> Callable[[str], str | None]:
    """The security's ticker on an ISO day, from its date-sorted ticker
    sightings: the latest one on or before the day, else its first."""
    def on(day: str) -> str | None:
        before = [s.value for s in sightings if s.day <= day]
        if before:
            return before[-1]
        return sightings[0].value if sightings else None
    return on


def own_last_seen(sec: Security, sig: Sequence[Sighting]) -> str:
    """The latest sighting under one of the security's own era tickers, else
    the latest era end date.

    FTD rows found by CUSIP include a post-delisting OTC tail under another
    symbol (e.g. a bankrupt XYZ trading as XYZQ), which would otherwise push
    `last_seen` past the real delisting and misdate a fallback delisting.
    """
    own = {e.ticker for e in sec.eras}
    dates = [s.day for s in sig if s.value in own]
    return dates[-1] if dates else max(e.last for e in sec.eras)


def history_rows(sec: Security, sightings: Sequence[Sighting], cusip_sightings: Sequence[Sighting], *,
                 listed: bool, end: str | None, end_exchange: str | None,
                 exchange_today: Callable[[str], str | None]) -> tuple[list[dict], list[dict]]:
    """The security's ticker_history and cusip_history rows: its sightings, up to
    `end` when it has one (the last trade day of its last delisting, when it is
    not listed today), as ranges (`ranges_from_sightings`), open-ended while it
    is `listed`. The ticker range that ends at `end` carries that delisting's
    exchange (`end_exchange`); an open range the exchange EDGAR lists for its
    ticker today (`exchange_today(ticker)`); any other range none."""
    th_rows, ch_rows = [], []
    clipped = [x for x in sightings if end is None or x.day <= end]
    for rg in ranges_from_sightings(clipped, end=end, open_ended=listed):
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

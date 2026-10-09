"""Lifecycles: what the output tables say happened to each security, from its
first ticker interval to today (spec: Delist Library Reset, "How 99% is
measured").

A walk starts at a security and ends in one of these kinds:
- `active`: an open ticker interval today, or one that opens after its last
  real ending (the security kept trading);
- `ended`: its last real ending has a known reason, a last trade date and a
  dlret;
- `ended_incomplete`: it ended, but the reason is unknown or the last trade
  date or the dlret is blank;
- `left_view`: its last real ending is an exchange transfer with no successor
  (the library stopped following it);
- `closed_no_event`: every interval is closed and no ending explains it;
- `no_interval`: it has no ticker interval at all;
- `loop`: a successor chain that comes back to a security already visited.
A real ending is a delistings.csv row whose `successor_sec_id` is not the
security itself (a continuing exchange move is not an event); the walk follows
each security's last one (`exit_kind.last_endings`). An ending that names a
successor continues the walk there.

`active` and `ended` are covered. Quality is the weakest grade along a covered
chain (`event_grade`, plus `medium` for a security whose FIGI came from a
ticker-only lookup).

Pure: reads one run's tables through its snapshot (`run_snapshot.RunSnapshot`: every cell a string), each row
through the row vocabulary (exit_kind).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..vocabulary.exit_kind import CONFLICT, end_day_of, ending_fields, flag_names, last_endings
from ..outputs.run_snapshot import RunSnapshot

ACTIVE, ENDED = "active", "ended"
ENDED_INCOMPLETE, LEFT_VIEW = "ended_incomplete", "left_view"
CLOSED_NO_EVENT, NO_INTERVAL, LOOP = "closed_no_event", "no_interval", "loop"
NO_MAPPED_SIGHTING = "no_mapped_sighting"     # an input ticker none of whose sightings has a sec_id
COVERED = frozenset({ACTIVE, ENDED})
KINDS = (ACTIVE, ENDED, ENDED_INCOMPLETE, LEFT_VIEW, CLOSED_NO_EVENT, NO_INTERVAL, LOOP, NO_MAPPED_SIGHTING)

HIGH, MEDIUM, LOW = "high", "medium", "low"
_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}
LOW_FLAGS = frozenset({CONFLICT, "resolved_by_current_ticker_map"})


@dataclass(frozen=True)
class Lifecycle:
    start: str                                   # the sec_id the walk started from
    kind: str
    chain: tuple[str, ...] = ()                  # sec_ids visited, in order
    events: tuple[Mapping[str, str], ...] = ()   # the real endings followed, in order
    quality: str | None = None                   # set on a covered lifecycle only

    @property
    def covered(self) -> bool:
        return self.kind in COVERED

    @property
    def final(self) -> Mapping[str, str] | None:
        """The last real ending of the chain, unless the chain is still trading."""
        return self.events[-1] if self.events and self.kind != ACTIVE else None


def event_grade(row: Mapping[str, str]) -> str:
    """One ending's grade: `low` for a Shumway or assumed-par value, a
    conflicting last trade date, or an identity through today's ticker map;
    `medium` when the ending's or its value's confidence is not high; else `high`."""
    method = row.get("dlret_method", "")
    if method.startswith("shumway") or method == "assumed_par" or flag_names(row) & LOW_FLAGS:
        return LOW
    if row.get("confidence") != HIGH or row.get("dlret_confidence") not in (HIGH, ""):
        return MEDIUM
    return HIGH


def weakest(grades: Sequence[str]) -> str:
    return max(grades, key=_RANK.__getitem__, default=HIGH)


@dataclass
class LifecycleView:
    """Lifecycles over one run's tables (its snapshot): per security, per input ticker, and
    the look-ups a truth case needs (`security_on`, `issuer_of`, `tickers_of`)."""
    tables: RunSnapshot
    _intervals: dict[str, list[Mapping[str, str]]] = field(init=False)
    _last: dict[str, Mapping[str, str]] = field(init=False)
    _securities: dict[str, Mapping[str, str]] = field(init=False)
    _mapped: dict[tuple[str, str], str] = field(init=False)
    _history: dict[str, list[Mapping[str, str]]] = field(init=False)
    _memo: dict[str, Lifecycle] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._history = defaultdict(list)
        for r in self.tables.security_history or ():
            self._history[r["sec_id"]].append(r)
        self._intervals = defaultdict(list)
        for r in self.tables.ticker_history:
            self._intervals[r["sec_id"]].append(r)
        self._mapped = {(r["ticker"], r["as_of"]): r["sec_id"] for r in self.tables.observation_map if r["sec_id"]}
        self._last = last_endings(self.tables.delistings)
        self._securities = {r["sec_id"]: r for r in self.tables.securities}

    # -- look-ups -------------------------------------------------------------
    def observed(self) -> list[str]:
        return sorted(s for s, r in self._securities.items() if r.get("observed") == "true")

    def issuer_of(self, sec_id: str, on: str = "") -> str:
        """The security's issuer CIK: the contract's issuer in force on `on`
        (security_history.csv) when an interval of it covers that day, else
        securities.csv's."""
        for r in self._history.get(sec_id, ()) if on else ():
            if r["start_date"] <= on and (not r["end_date"] or on <= r["end_date"]):
                return r["issuer_id"]
        return self._securities.get(sec_id, {}).get("issuer_cik", "")

    def figi_source_of(self, sec_id: str) -> str:
        return self._securities.get(sec_id, {}).get("figi_source", "")

    def tickers_of(self, sec_ids: Sequence[str]) -> set[str]:
        return {r["ticker"] for s in sec_ids for r in self._intervals.get(s, ())}

    def security_on(self, ticker: str, on: str) -> str | None:
        """The security observation_map maps (ticker, on) to; else the one
        security whose ticker_history interval covers `on` under `ticker`.
        None when neither answers, or ticker_history gives two."""
        if (ticker, on) in self._mapped:
            return self._mapped[(ticker, on)]
        hits = {r["sec_id"] for rows in self._intervals.values() for r in rows
                if r["ticker"] == ticker and r["valid_from"] <= on and (not r["valid_to"] or on <= r["valid_to"])}
        return hits.pop() if len(hits) == 1 else None

    def end_of(self, lc: Lifecycle) -> str | None:
        """The date a lifecycle that is not active ends: its final ending's end day
        (`exit_kind.end_day_of`: its last trade date, else its delist date); with no
        ending, the latest interval end."""
        if lc.kind == ACTIVE:
            return None
        if lc.final is not None:
            return end_day_of(lc.final).isoformat()
        ends = [r["valid_to"] for s in lc.chain for r in self._intervals.get(s, ()) if r["valid_to"]]
        return max(ends) if ends else None

    # -- the walk -------------------------------------------------------------
    def lifecycle(self, sec_id: str) -> Lifecycle:
        if sec_id not in self._memo:
            kind, chain, events = self._walk(sec_id, ())
            grade = None
            if kind in COVERED:
                grades = [event_grade(e) for e in events]
                grades += [MEDIUM for s in chain if self.figi_source_of(s) == "ticker"]
                grade = weakest(grades)
            self._memo[sec_id] = Lifecycle(sec_id, kind, chain, tuple(events), grade)
        return self._memo[sec_id]

    def _walk(self, s: str, seen: tuple[str, ...]) -> tuple[str, tuple[str, ...], list[Mapping[str, str]]]:
        if s in seen:
            return LOOP, seen, []
        chain = seen + (s,)
        intervals = self._intervals.get(s, [])
        if not intervals:
            return NO_INTERVAL, chain, []
        e = self._last.get(s)
        open_ = [r for r in intervals if not r["valid_to"]]
        if e is None:
            return (ACTIVE if open_ else CLOSED_NO_EVENT), chain, []
        if any(r["valid_from"] > e["delist_date"] for r in open_):
            return ACTIVE, chain, [e]                 # an open interval after the ending: it kept trading
        if e["successor_sec_id"]:
            kind, chain2, events = self._walk(e["successor_sec_id"], chain)
            return kind, chain2, [e] + events
        kind = ending_fields(e).exit_kind
        if kind == "exchange":
            return LEFT_VIEW, chain, [e]
        complete = kind != "" and e["last_trade_date"] and e["dlret"]
        return (ENDED if complete else ENDED_INCOMPLETE), chain, [e]

    def by_security(self) -> dict[str, Lifecycle]:
        """Every observed security's lifecycle."""
        return {s: self.lifecycle(s) for s in self.observed()}

    def by_input_ticker(self) -> dict[str, Lifecycle]:
        """Every input ticker's lifecycle: the one of the security its earliest
        mapped sighting resolved to."""
        first: dict[str, tuple[str, str]] = {}
        tickers: set[str] = set()
        for r in self.tables.observation_map:
            tickers.add(r["ticker"])
            if r["sec_id"] and (r["ticker"] not in first or r["as_of"] < first[r["ticker"]][0]):
                first[r["ticker"]] = (r["as_of"], r["sec_id"])
        return {t: (self.lifecycle(first[t][1]) if t in first else Lifecycle("", NO_MAPPED_SIGHTING))
                for t in sorted(tickers)}

    def first_sighting(self, ticker: str) -> str | None:
        """The earliest date `ticker` was seen with a sec_id, or None."""
        dates = [d for (t, d) in self._mapped if t == ticker]
        return min(dates) if dates else None

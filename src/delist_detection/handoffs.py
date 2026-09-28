"""Ticker handoffs (CONTEXT.md, Handoff): one security of the run stops trading
under a ticker and another security of the run starts trading under it within
days. The pass finds every such pair (`find_handoffs`), decides what each one
is (`decide_handoff`), and acts on it (`apply_handoffs`):

- a continuation (a holding-company reorganization, a redomicile, a rename or a
  share reclassification: the holders' shares became the new security's one
  for one, and the ticker's price series continues) gets a delisting row for
  the predecessor, an `exchange_transfer` with a zero return whose
  `successor_sec_id` is the new security;
- a ticker takeover (an acquirer renamed itself after its target and took over
  its ticker: II-VI as Coherent Corp on COHR, Eldorado as Caesars on CZR)
  leaves the target's row as it is and records the taker in
  `ticker_successor_sec_id`.

The Form 25 matcher and the classifier are not changed: this pass runs after
the delisting search and the successor search, before the ticker history is
built, so a row it adds clips the predecessor's range like any other delisting.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from .history import Sighting

OVERLAP_DAYS = 10         # B's first sighting under the ticker may precede A's last by this much (CZR: 8)
CONTINUATION_DAYS = 10    # a continuation by timing: A's last and B's first sighting this close
TAKEOVER_DAYS = 120       # B's first sighting at most this long after A's last (COHR: 74)


def _bare(ticker: str) -> str:
    return ticker.replace("-", "")


def _days(lo: str, hi: str) -> int:
    return (date.fromisoformat(hi) - date.fromisoformat(lo)).days


@dataclass(frozen=True)
class HandoffPair:
    """Security `a` stops trading under `ticker` (its last sighting under it,
    `a_last`) and security `b` starts under it (`b_first`); `b_first_any` is
    `b`'s first sighting under any ticker (earlier than `b_first` for a taker
    that traded under its own ticker first)."""
    ticker: str
    a: str
    b: str
    a_last: str
    b_first: str
    b_first_any: str

    @property
    def gap(self) -> int:
        """Days from A's last sighting under the ticker to B's first (negative: they overlap)."""
        return _days(self.a_last, self.b_first)


def find_handoffs(sightings: Mapping[str, Sequence[Sighting]]) -> list[HandoffPair]:
    """The candidate handoffs among the run's securities (`sightings`: sec_id ->
    its dated ticker sightings, `history.ticker_sightings`; a ticker spelled
    with or without its separator is one ticker). For each ticker, the
    securities sighted under it, in the order they began under it; each one and
    the next one to begin form a pair when the next one's first sighting under
    the ticker falls within [-OVERLAP_DAYS, TAKEOVER_DAYS] days of the first
    one's last sighting under it. Sorted by ticker, then date."""
    spans: dict[str, dict[str, list[str]]] = defaultdict(dict)       # bare ticker -> sec_id -> [first, last]
    label: dict[tuple[str, str], str] = {}
    first_any: dict[str, str] = {}
    for sid, sig in sightings.items():
        for s in sig:
            t = _bare(s.value)
            span = spans[t].setdefault(sid, [s.day, s.day])
            span[0], span[1] = min(span[0], s.day), max(span[1], s.day)
            label.setdefault((t, sid), s.value)
            first_any[sid] = min(first_any.get(sid, s.day), s.day)
    out: list[HandoffPair] = []
    for t, by_sec in spans.items():
        ordered = sorted(by_sec.items(), key=lambda kv: (kv[1][0], kv[0]))
        for (a, (_, a_last)), (b, (b_first, _)) in zip(ordered, ordered[1:]):
            if -OVERLAP_DAYS <= _days(a_last, b_first) <= TAKEOVER_DAYS:
                out.append(HandoffPair(label[(t, a)], a, b, a_last, b_first, first_any[b]))
    return sorted(out, key=lambda p: (p.ticker, p.a_last, p.a, p.b))

"""The accuracy audit's sample (decision 17): a census of every high-impact
ending plus a random sample of the other lifecycles, written as a truth-file
worksheet (`truth.TRUTH_COLUMNS`) for a person to fill in from sources.

Census groups, each ending in exactly one (the first that applies, in
`scorecard.CENSUS_GROUPS` order): `distress` (liquidation or compliance
failure), `continuation` (names a successor other than itself), `left_view`
(the final ending of a left-view lifecycle), `blank_no_value` (blank dlret
inside the window, not just waiting on a last close), `assumed_par`. The
random sample draws input tickers whose lifecycle touches no census security,
with a fixed seed so the draw can be repeated.
"""
from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

from .lifecycle import LEFT_VIEW, LifecycleView
from .exit_kind import is_continuation, is_distress, is_real_ending
from .scorecard import CENSUS_GROUPS, Window
from .truth import TRUTH_COLUMNS


@dataclass(frozen=True)
class Target:
    case: str
    group: str
    ticker: str
    on: str
    sec_id: str


def _census_group(row: Mapping[str, str], left_view_rows: set[tuple[str, str]], window: Window | None) -> str | None:
    key = (row["sec_id"], row["delist_date"])
    if not is_real_ending(row):
        return None                                     # a continuing move: not an ending
    tests = {
        "distress": is_distress(row),
        "continuation": is_continuation(row),
        "left_view": key in left_view_rows,
        "blank_no_value": (not row["dlret"] and row["dlret_method"] != "needs_last_trade"
                           and window is not None and window.contains(row["delist_date"])),
        "assumed_par": row["dlret_method"] == "assumed_par",
    }
    return next((g for g in CENSUS_GROUPS if tests[g]), None)


def _anchor(view: LifecycleView, sec_id: str, before: str) -> tuple[str, str] | None:
    """A (ticker, date) that `view.security_on` answers with `sec_id`: tried on
    each of its intervals that starts on or before `before`, latest first, at
    the interval's start and then its end; else its earliest observation (an
    ending dated before every interval, the `no_interval` defect)."""
    rows = sorted((r for r in view.tables.ticker_history if r["sec_id"] == sec_id and r["valid_from"] <= before),
                  key=lambda r: r["valid_from"], reverse=True)
    for r in rows:
        for d in (r["valid_from"], r["valid_to"]):
            if d and view.security_on(r["ticker"], d) == sec_id:
                return r["ticker"], d
    seen = sorted((r["as_of"], r["ticker"]) for r in view.tables.observation_map if r["sec_id"] == sec_id)
    return (seen[0][1], seen[0][0]) if seen else None


def census(view: LifecycleView, window: Window | None) -> tuple[list[Target], list[str]]:
    """Every census ending as a Target, and the endings that could not be
    anchored to a (ticker, date) the view resolves back to their security."""
    left_view_rows = {(lc.final["sec_id"], lc.final["delist_date"])
                      for lc in view.by_security().values() if lc.kind == LEFT_VIEW and lc.final is not None}
    out, skipped = [], []
    for row in sorted(view.tables.delistings, key=lambda r: (r["sec_id"], r["delist_date"])):
        group = _census_group(row, left_view_rows, window)
        if group is None:
            continue
        anchor = _anchor(view, row["sec_id"], row["delist_date"])
        if anchor is None:
            skipped.append(f"{row['sec_id']} {row['delist_date']}")
            continue
        out.append(Target(f"{group}:{row['sec_id']}:{row['delist_date']}", f"census:{group}", *anchor, row["sec_id"]))
    return out, skipped


def random_sample(view: LifecycleView, exclude: set[str], n: int, seed: int) -> list[Target]:
    """`n` input tickers drawn with `seed` from those whose lifecycle starts at
    a security and touches none of `exclude`."""
    pool = sorted(t for t, lc in view.by_input_ticker().items() if lc.start and not set(lc.chain) & exclude)
    picked = random.Random(seed).sample(pool, min(n, len(pool)))
    out = []
    for t in sorted(picked):
        lc = view.by_input_ticker()[t]
        out.append(Target(f"random:{t}", "random", t, view.first_sighting(t) or "", lc.start))
    return out


def library_says(view: LifecycleView, sec_id: str) -> str:
    """What the output says about the lifecycle from `sec_id`, for the checker."""
    lc = view.lifecycle(sec_id)
    text = f"{lc.kind}; chain {'>'.join(lc.chain)}; issuer {view.issuer_of(sec_id)}"
    if lc.final is not None:
        f = lc.final
        text += (f"; final {f['bucket']} {f['delist_date']} ltd {f['last_trade_date'] or '-'} "
                 f"dlret {f['dlret'] or '-'} ({f['dlret_method']})")
    return text


def worksheet_rows(view: LifecycleView, targets: list[Target]) -> list[dict[str, str]]:
    """One blank truth row per target (`status` blank: an audit row is counted,
    not pinned)."""
    rows = []
    for t in targets:
        row = dict.fromkeys(TRUTH_COLUMNS, "")
        row.update(case=t.case, group=t.group, ticker=t.ticker, on=t.on, library_says=library_says(view, t.sec_id))
        rows.append(row)
    return rows

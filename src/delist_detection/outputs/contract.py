"""The contract (spec: Delist Library Reset, "The contract"; decisions 6, 7, 9,
10 and 12): the tables qlib_practice will read, built from the run's own tables
and verdicts (read from the run's snapshot, `run_snapshot.RunSnapshot`, as the pipeline is about to write them)
and written under output/contract/ beside today's tables for one release.

- security_history.csv (`security_history_rows`): one row per security per
  interval in which its ticker and its issuer CIK hold;
- delistings.csv (`delisting_rows`): one row per ended security, its last real
  ending; an earlier one is uncertain (`verdict`, `earlier_ending`);
- seeds.csv (`seed_rows`): every input observation with its sec_id and verdict;
- price_requests.csv: `price_requests.request_rows`;
- id_changes.csv (`id_change_rows`): the baseline run's placeholders that now
  hold a FIGI;
- payout_legs.csv (`payout_leg_rows`, schema 3, ruling R3): each security of a
  basket ending per share.

run_manifest.json carries store.CONTRACT_SCHEMA_VERSION. Pure."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from datetime import date, timedelta

from .dlret import DistressTerms, MergerInputs, contract_value
from ..vocabulary.exit_kind import ending_fields, last_endings, published
from ..vocabulary.identifiers import is_placeholder
from .payout_rule import basket_legs, value_fields
from .run_snapshot import RunSnapshot
from .store import RENAME, SPLIT, DelistingKey
from .verdict import Verdicts, seed_key

ECHOED = ("ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id", "sec_id")


def delisting_rows(tables: RunSnapshot, verdicts: Verdicts,
                   inputs: Mapping[DelistingKey, MergerInputs] | None = None,
                   distress: Mapping[DelistingKey, DistressTerms] | None = None) -> list[dict[str, object]]:
    """contract/delistings.csv: one row per ended security, its last real ending (`exit_kind.last_endings`;
    `exit_kind.ending_fields`, `exit_kind.published`, the value cells `dlret.contract_value`, its ending's verdict,
    and the payout rule `payout_rule.value_fields`; `inputs` are the mergers' pre-gate reads, `distress` the drops'
    and bankruptcies' OTC symbols and plan ratios, pipeline stage 9e). A continuation
    carries no value."""
    rows: list[dict[str, object]] = []
    inputs = inputs or {}
    for sid, r in last_endings(tables.delistings).items():
        f = ending_fields(r)
        value = contract_value(r)
        ltd = published(r)
        key = DelistingKey(sid, r["delist_date"])
        rows.append({
            "sec_id": sid, "last_trade_date": ltd, "exit_kind": f.exit_kind,
            "drop_reason": f.drop_reason, "continuation": f.continuation,
            "successor_sec_id": r["successor_sec_id"] if f.continuation else "",
            "ticker_successor_sec_id": r["ticker_successor_sec_id"], "dlret": value.dlret,
            "dlret_fill": value.dlret_fill, "terminal_value": value.terminal_value,
            "verdict": verdicts.endings[(sid, r["delist_date"])].word,
            # no distress map at all: a caller of this pure function, the exchange ticker as before
            **value_fields(r, ltd, inputs.get(key),
                           None if distress is None else distress.get(key, DistressTerms())),
        })
    return rows


def payout_leg_rows(tables: RunSnapshot, inputs: Mapping[DelistingKey, MergerInputs] | None = None
                    ) -> list[dict[str, object]]:
    """contract/payout_legs.csv (ruling R3, schema 3): each security one share of a basket ending (value rule
    `basket`, contract/delistings.csv) became, in leg order, with the security, ticker and date its price is needed
    on (`payout_rule.basket_legs`)."""
    inputs = inputs or {}
    rows: list[dict[str, object]] = []
    for sid, r in last_endings(tables.delistings).items():
        rows += basket_legs(r, published(r), inputs.get(DelistingKey(sid, r["delist_date"])))
    return rows


def seed_rows(tables: RunSnapshot, verdicts: Verdicts) -> list[dict[str, str]]:
    """contract/seeds.csv: every input observation (observation_map's input
    columns), its sec_id (blank when unplaced) and its verdict."""
    return [{**{c: r[c] for c in ECHOED}, "verdict": verdicts.seeds[seed_key(r)].word}
            for r in tables.observation_map]


def _issuer_on(timeline: Sequence[tuple[str, str]], day: str, default: str) -> str:
    if not timeline:
        return default
    cik = timeline[0][1]
    for since, c in timeline:
        if since <= day:
            cik = c
    return cik


def _day_before(iso: str) -> str:
    return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()


def security_history_rows(tables: RunSnapshot, issuers: Mapping[str, Sequence[tuple[str, str]]],
                          leave_out: Collection[str] = ()) -> list[dict[str, str]]:
    """contract/security_history.csv: each ticker_history range, split where the
    issuer CIK in force changes. `issuers` is each security's issuer timeline
    (`issuer_in_force.issuer_changes`: [(from ISO date, CIK)], earliest first); a
    day before its first entry takes that entry's CIK, and a security with no
    timeline takes its securities.csv CIK. `leave_out` names securities not
    published (the merger acquirers the run adds)."""
    secs = {s["sec_id"]: s for s in tables.securities}
    out: list[dict[str, str]] = []
    for r in tables.ticker_history:
        sid = r["sec_id"]
        if sid in leave_out:
            continue
        s, timeline = secs.get(sid, {}), issuers.get(sid, ())
        start, end = r["valid_from"], r["valid_to"]
        bounds = [start, *(d for d, _ in timeline[1:] if start < d and (not end or d <= end))]
        for i, lo in enumerate(bounds):
            hi = _day_before(bounds[i + 1]) if i + 1 < len(bounds) else end
            out.append({"sec_id": sid, "issuer_id": _issuer_on(timeline, lo, s.get("issuer_cik", "")),
                        "start_date": lo, "end_date": hi, "ticker": r["ticker"],
                        "security_name": s.get("name", ""), "share_class": s.get("share_class", "")})
    return out


def baseline_of_history(history: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """A previous run's contract/security_history.csv as `id_change_rows`'s baseline (FB-010: a baseline that does
    not need securities.csv): one row per security, sorted by sec_id, with the issuer of its latest interval that
    names one (a placeholder named on none takes the CIK its id names), its share class, and `figi_source`
    `placeholder` for a placeholder id (`identifiers.is_placeholder`), else `figi`."""
    latest: dict[str, tuple[str, str]] = {}
    issuer: dict[str, str] = {}
    for r in sorted(history, key=lambda r: (r["sec_id"], r["start_date"])):
        latest[r["sec_id"]] = (r["start_date"], r["share_class"])
        if r["issuer_id"]:
            issuer[r["sec_id"]] = r["issuer_id"]
    out = []
    for sid, (_, share_class) in sorted(latest.items()):
        placeholder = is_placeholder(sid)
        cik = issuer.get(sid) or (sid[len("CIK"):].split("-", 1)[0] if placeholder else "")
        out.append({"sec_id": sid, "issuer_cik": cik, "share_class": share_class,
                    "figi_source": "placeholder" if placeholder else "figi"})
    return out


SPLIT_MIN_DAYS = 90         # another id must hold at least this many days of a baseline id's ranges ...
SPLIT_MIN_SHARE = 0.10      # ... and at least this share of all the days the baseline id held


def _span(start: str, end: str, as_of: date) -> tuple[date, date]:
    return date.fromisoformat(start), date.fromisoformat(end) if end else as_of


def split_holders(baseline_history: Sequence[Mapping[str, str]], history: Sequence[Mapping[str, str]],
                  as_of: date) -> dict[str, list[str]]:
    """FB-005, FB-001 (CHK): the baseline ids whose days this run holds under other ids. `baseline_history` is the
    baseline run's contract/security_history.csv rows and `history` this run's. For each baseline sec_id B, the ids
    other than B that hold days of B's baseline ranges *under the same ticker*: an id counts when it holds at least
    `SPLIT_MIN_DAYS` days of them and at least `SPLIT_MIN_SHARE` of the days B held (a ticker handed over at a
    range's edge, or a few days a range's start moved, hold less: Hertz, Herc). Returns B -> those ids, sorted;
    the caller decides which are splits (`id_change_rows`). An open range runs to `as_of`."""
    now: dict[str, list[tuple[str, date, date, str]]] = defaultdict(list)
    for r in history:
        lo, hi = _span(r["start_date"], r["end_date"], as_of)
        now[r["ticker"]].append((r["sec_id"], lo, hi, r["ticker"]))
    held: dict[str, int] = defaultdict(int)
    taken: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in baseline_history:
        lo, hi = _span(r["start_date"], r["end_date"], as_of)
        held[r["sec_id"]] += (hi - lo).days + 1
        for sid, a, b, _ in now.get(r["ticker"], ()):
            days = (min(hi, b) - max(lo, a)).days + 1
            if sid != r["sec_id"] and days > 0:
                taken[r["sec_id"]][sid] += days
    return {b: sorted(sid for sid, d in got.items() if d >= SPLIT_MIN_DAYS and d >= SPLIT_MIN_SHARE * held[b])
            for b, got in sorted(taken.items())}


def id_change_rows(baseline: Sequence[Mapping[str, str]], securities: Sequence[Mapping[str, str]],
                   changed_on: str, renames: Mapping[str, str] = {}, *,
                   baseline_history: Sequence[Mapping[str, str]] = (),
                   history: Sequence[Mapping[str, str]] = ()) -> list[dict[str, str]]:
    """contract/id_changes.csv (decision 7): each placeholder of the baseline run
    (its securities.csv rows) that this run no longer has and that a line
    follow folded into a FIGI security of this run (`renames`: old sec_id -> new,
    pipeline stage 4b; FTR's CIK holds a later FIGI line too), else whose issuer
    and class exactly one FIGI security of this run holds; and each baseline FIGI this run no longer holds that
    `renames` maps to a FIGI of this run (sub-plan 5h, rule F: the ticker tier's composite was the line that took
    the ticker over later, BTU BBG00GBV88T6 to BBG000FW00S1, CRC BBG00Y04KP80 to BBG0060B3M63), so a panel keyed
    on the old FIGI can follow it. Not cumulative: git keeps the earlier files.

    Split rows (`kind` `store.SPLIT`, FB-005 and FB-001; `split_holders` has the threshold): a baseline id B whose
    ranges, under the same ticker, this run holds under other ids (`baseline_history`, the baseline's
    security_history.csv, and `history`, this run's) gets one row per such id, B repeated in `old_sec_id`, when B is
    gone and two or more ids hold them (Liberty's placeholder), or when B is still here and another id holds a part
    (Chesapeake's old eras, now a placeholder). A B that one other id took over alone is a rename, as before, and a
    B with split rows gets no rename row. With no `baseline_history` there are no split rows. A split row's
    `issuer_cik` and `share_class` are the new id's."""
    now = {s["sec_id"] for s in securities}
    figis: dict[tuple[str, str], set[str]] = defaultdict(set)
    for s in securities:
        if s["figi_source"] != "placeholder" and s["issuer_cik"]:
            figis[(s["issuer_cik"], s["share_class"])].add(s["sec_id"])
    splits = {b: ids for b, ids in (split_holders(baseline_history, history, date.fromisoformat(changed_on))
                                    if baseline_history else {}).items() if ids and (b in now or len(ids) >= 2)}
    rows = []
    for b in baseline:
        renamed = renames.get(b["sec_id"]) in now
        if b["sec_id"] in splits or b["sec_id"] in now or (b["figi_source"] != "placeholder" and not renamed):
            continue
        found = {renames[b["sec_id"]]} if renames.get(b["sec_id"]) in now else \
            figis.get((b["issuer_cik"], b["share_class"]), set())
        if len(found) == 1:
            rows.append({"old_sec_id": b["sec_id"], "new_sec_id": next(iter(found)), "changed_on": changed_on,
                         "issuer_cik": b["issuer_cik"], "share_class": b["share_class"], "kind": RENAME})
    by_id = {s["sec_id"]: s for s in securities}
    for b, ids in splits.items():
        for new in ids:
            if new in by_id:
                rows.append({"old_sec_id": b, "new_sec_id": new, "changed_on": changed_on,
                             "issuer_cik": by_id[new]["issuer_cik"], "share_class": by_id[new]["share_class"],
                             "kind": SPLIT})
    return rows

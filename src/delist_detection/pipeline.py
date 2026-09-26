# src/delist_detection/pipeline.py
"""End-to-end run: observations -> security master and delistings (spec §8).

Everything is computed first and written last, so a refusal or a bad override
file never leaves a half-written output over the previous complete one.
"""
from __future__ import annotations

import copy
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, NamedTuple

from .crsp_codes import CrspBucket
from .delistings import DelistingEvent, DelistingFinder, ReviewItem, SecurityContext
from .edgar import SEC_STATS
from .evidence import edgar_names
from .fatal import FATAL
from .figi_resolution import FigiCandidate, accept, is_placeholder, share_class_from_name, us_candidates
from .form25 import SecurityRef
from .ftd import FtdIndex
from .listing_status import edgar_lists, issuer_exchange, listed_today, listing_answers
from . import manifest as run_manifest
from .names import names_agree
from .observations import ObservationIndex, TickerEra, eras_by_key, normalize_ticker, observation_conflicts
from .payout_gate import DEFAULT_TOL, gate_payouts
from .prefetch import Serialized, warm
from .reconstruction import (
    DelistingKey, build_delistings_table, delisting_row, for_delisting, unmatched_override_keys,
)
from .review_triage import Decision, flag_name, is_blank, triage
from .security_master import (
    AddedAcquirer, AddedSecurity, AddedSuccessor, FigiResolver, Security, Sighting, build_securities,
    candidate_cusips, era_last_seen, issuers_by_era, ranges_from_sightings, refine_eras, value_on,
)
from .store import write_tables
from .trading_calendar import next_trading_day, previous_trading_day

FTD_START = date(2004, 1, 1)


@dataclass
class Clients:
    edgar: Any
    resolver: Any
    classifier: Any
    figi: Any
    ftd_client: Any
    midas: Any = None
    halts: Any = None
    payout_extractor: Any = None
    llm_extractor: Any = None
    as_of: date | None = None       # the run date every client uses (default_clients sets it)


@dataclass
class Overrides:
    last_trade_closes: dict = field(default_factory=dict)
    merger_terms: dict = field(default_factory=dict)
    recoveries: dict = field(default_factory=dict)


@dataclass
class RunSummary:
    counts: dict[str, int]
    buckets: dict[str, int]
    figi_sources: dict[str, int]
    review_flags: dict[str, int]
    review_counts: dict[str, int] = field(default_factory=dict)     # review_triage.triage()'s counts


def _stderr(*parts) -> None:
    print(*parts, file=sys.stderr, flush=True)


def _to_date(s: str) -> date:
    return date.fromisoformat(s)


SUCCESSOR_FORMS = "8-K12B,8-K12G3"


def successor_query(name: str, day: date) -> tuple[str, str, date, date]:
    """The full-text search successor_from_8k12b sends for `name` around `day`.
    The prefetch sends the same one, so the sequential pass reads it from cache."""
    return f'"{name}"', SUCCESSOR_FORMS, day - timedelta(days=30), day + timedelta(days=60)


def successor_from_8k12b(search: Callable, figi, *, name: str, day: date, exclude_cik: int,
                         share_class: str = "COMMON", edgar=None,
                         own_tickers: set[str] | frozenset[str] = frozenset()
                         ) -> tuple[int, FigiCandidate, str] | None:
    """The successor issuer that filed an 8-K12B naming `name` around `day`,
    resolved to the US composite FIGI whose share class matches the
    predecessor's `share_class`.

    A display name looks like ``"Alphabet Inc.  (GOOGL, GOOG)  (CIK
    0001652044)"``: the tickers are the parenthetical immediately before the
    trailing ``(CIK ...)`` — never the first parenthetical in the string,
    which can be part of the company's own legal name (``"Banco Santander
    (Brasil) S.A.  (BSBR)  (CIK 0001471119)"`` carries the ticker ``BSBR``,
    not ``Brasil``). Each of those tickers is resolved through OpenFIGI; a
    resolved candidate is kept only when its name agrees
    (`names.names_agree`) with the successor's own EDGAR name — the text
    before that ticker parenthetical, exactly as EDGAR's full-text search
    recorded it, so no extra network call is needed to confirm it. Among the
    agreeing candidates, the one whose share class (`share_class_from_name`)
    equals the predecessor's is picked; if the predecessor is plain common
    and exactly one candidate agrees on name, that one is taken even without
    an exact class match. Otherwise returns None (the caller leaves
    `successor_unknown` set rather than guess). A display name with no
    ticker parenthetical yields no candidates and makes no OpenFIGI request.

    A filer is skipped when it is another company's own, still-listed stock:
    its EDGAR name does not agree with the predecessor's `name`, none of its
    tickers is one of the predecessor's `own_tickers`, and (with `edgar`) its
    EDGAR record lists one of them on a major exchange today. Clear Channel
    Outdoor's 2019 successor filed its 8-K12B under the predecessor's own CIK
    (excluded), which left iHeartMedia's 8-K12G3 for its own emergence, naming
    its subsidiary: IHRT is not Clear Channel Outdoor's successor. Alphabet
    (a new name on Google's own tickers) is.

    Returns `(cik, candidate, filing_date)`.
    """
    own = {normalize_ticker(t) for t in own_tickers if t}
    hits = search(*successor_query(name, day))
    for h in hits:
        src = h.get("_source", h)
        filing_date = src.get("file_date") or src.get("filing_date") or ""
        for cik_s, disp in zip(src.get("ciks") or [], src.get("display_names") or []):
            cik = int(cik_s)
            if cik == exclude_cik:
                continue
            m = re.search(r"\(([^()]*)\)\s*\(CIK\s+\d+\)\s*$", disp)
            if not m:
                continue
            tickers = [normalize_ticker(t) for t in m.group(1).split(",") if t.strip()]
            if not tickers or figi is None:
                continue
            edgar_name = disp[: m.start()].strip()
            if (edgar is not None and not names_agree(name, edgar_name) and not own & set(tickers)
                    and edgar_lists(edgar, cik, tickers)):
                continue
            candidates: list[FigiCandidate] = []
            for t in tickers:
                ans = figi.map([{"idType": "TICKER", "idValue": t.replace("-", "/")}])[0]
                candidates += us_candidates(ans.get("data") or [])
            agreeing = [c for c in candidates if names_agree(c.name, edgar_name)]
            if not agreeing:
                continue
            class_matches = [c for c in agreeing if share_class_from_name(c.name) == share_class]
            if len(class_matches) == 1:
                return cik, class_matches[0], filing_date
            if share_class == "COMMON" and len(agreeing) == 1:
                return cik, agreeing[0], filing_date
    return None


_CLASS_WORDS = re.compile(r"\b(?:CL(?:ASS)?|SER(?:IES)?)\s*-?\s*[A-Z0-9]\b|-[A-Z]$", re.I)
_STATE_TAG = re.compile(r"\s*/[A-Z]+/?\s*$")        # EDGAR's "AETNA INC /PA/", "ALLEGHANY CORP /DE"


def successor_search_name(edgar, cik: int | None, observed_name: str | None) -> str:
    """The predecessor's name as an 8-K12B would print it: the issuer's EDGAR
    name from its submissions JSON without EDGAR's state tag ("Google Inc."),
    else the observation name without its class words ("GOOGLE INC CLASS A"
    -> "GOOGLE INC")."""
    sub = edgar.submissions(cik) if cik is not None else None
    name = (sub.get("name") or "").strip() if isinstance(sub, dict) else ""
    if name:
        return _STATE_TAG.sub("", name).strip()
    return re.sub(r"\s+", " ", _CLASS_WORDS.sub(" ", observed_name or "")).strip(" -")


def _issuer_names(edgar, cik: int | None) -> tuple[str, ...]:
    """Every name EDGAR records for the issuer (`evidence.edgar_names` of the
    submissions JSON the resolver already read)."""
    sub = edgar.submissions(cik) if cik is not None else None
    return edgar_names(sub) if isinstance(sub, dict) else ()


def _overlaps(a: dict, b: dict) -> bool:
    a_to = a["valid_to"] or "9999-12-31"
    b_to = b["valid_to"] or "9999-12-31"
    return a["valid_from"] <= b_to and b["valid_from"] <= a_to


def _ticker_range_review(th_rows: list[dict]) -> list[ReviewItem]:
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


TICKER_CONFIRM_DAYS = 30        # an era's ticker counts as confirmed by an FTD row this close to its span


def _unconfirmed_review(eras: list[TickerEra], ftd: FtdIndex, resolutions: dict,
                        ciks: dict) -> list[ReviewItem]:
    """A `ticker_unconfirmed` review row for each era from 2004 on (the start of
    SEC fails-to-deliver data) with no FTD row under its ticker within
    `TICKER_CONFIRM_DAYS` of its first and last observation: the SEC data never
    shows that ticker then, as when a snapshot carries a ticker adopted later
    (APTV in 2012-2013, when Delphi traded as DLPH)."""
    out: list[ReviewItem] = []
    for e in eras:
        if _to_date(e.last) < FTD_START:
            continue
        lo = max(FTD_START, _to_date(e.first) - timedelta(days=TICKER_CONFIRM_DAYS)).isoformat()
        hi = (_to_date(e.last) + timedelta(days=TICKER_CONFIRM_DAYS)).isoformat()
        if ftd.by_symbol(e.ticker, lo, hi):
            continue
        out.append(ReviewItem(resolutions[e.key].sec_id or "", e.ticker, ciks.get(e.key), "ticker_unconfirmed",
                              f"{e.key} {e.name or ''}: no fails-to-deliver row under {e.ticker} "
                              f"from {lo} to {hi}", last_seen=e.last))
    return out


def _conflict_review(eras: list[TickerEra], resolutions: dict) -> list[ReviewItem]:
    """One `observation_conflict:<date>` review row per ticker seen under two or
    more names on one date (a snapshot source backfilled today's ticker: CB is
    both ACE LTD and CHUBB CORP in 2012-2014). The reason names each name with
    its era and the security that era resolved to. The date is in the flag so
    each (ticker, date) keeps its own row under review.csv's key."""
    out: list[ReviewItem] = []
    for ticker, day, names in observation_conflicts(o for e in eras for o in e.observations):
        seen = [f"{o.name} ({e.key} -> {resolutions[e.key].sec_id or 'unresolved'})"
                for e in eras if e.ticker == ticker for o in e.observations if o.as_of == day and o.name]
        out.append(ReviewItem("", ticker, None, f"observation_conflict:{day}",
                              f"{ticker} seen on {day} under {len(names)} names: " + "; ".join(dict.fromkeys(seen)),
                              last_seen=day))
    return out


def _merge_review_rows(rows: list[dict]) -> list[dict]:
    """Collapse rows that share `(sec_id, delist_date, ticker, review_flags)`
    into one, joining their distinct `reason`s with `"; "`. Every other field
    keeps its first non-empty value."""
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for r in rows:
        key = (r.get("sec_id"), r.get("delist_date"), r.get("ticker"), r.get("review_flags"))
        if key not in merged:
            merged[key] = dict(r)
            order.append(key)
            continue
        existing = merged[key]
        reasons = [x for x in (existing.get("reason") or "").split("; ") if x]
        new_reason = r.get("reason") or ""
        if new_reason and new_reason not in reasons:
            reasons.append(new_reason)
        existing["reason"] = "; ".join(reasons)
        for k, v in r.items():
            if k == "reason":
                continue
            if not existing.get(k) and v:
                existing[k] = v
    return [merged[k] for k in order]


def _sightings(sec: Security, ftd: FtdIndex, cusips: list[str]) -> list[Sighting]:
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


def _cusip_sightings(sec: Security, ftd: FtdIndex, cusips: list[str]) -> list[Sighting]:
    """Dated `(day, cusip, source)` sightings of the security's CUSIPs: the FTD
    rows of each CUSIP that resolved to it (not those under a deleted symbol),
    and the CUSIPs its observations carry."""
    out = [Sighting(r.date, r.cusip, "ftd") for r in ftd.trading_rows(cusips)]
    out += [Sighting(o.as_of, o.cusip, "observation") for e in sec.eras for o in e.observations if o.cusip]
    return sorted(set(out))


SUCCESSOR_BEFORE_DAYS, SUCCESSOR_AFTER_DAYS = 5, 15    # a successor's first sighting around the last trade


class SecurityStart(NamedTuple):
    """How a security of the run (observed or added) first shows up, for the
    in-run successor search: its first sighting, its issuer CIK, and every
    ticker it was sighted under."""
    first_seen: str
    issuer_cik: int | None
    tickers: set[str]


def _successor_in_run(e: DelistingEvent, starts: dict[str, SecurityStart]) -> tuple[str, str] | None:
    """The one security of the run (observed or added; `starts` by sec_id)
    whose first sighting falls within
    [last trade - SUCCESSOR_BEFORE_DAYS, last trade + SUCCESSOR_AFTER_DAYS] and
    that shares the delisted security's issuer CIK or its ticker: the new line
    of a holding-company reorganization or a rename. With no last trade date
    the Form 25's filing date stands in for it (the delisting date is ten days
    later), else the delisting date. Returns (sec_id, "same_issuer" |
    "same_ticker"); None for zero or several candidates."""
    day = e.last_trade.day or (_to_date(e.form25_sub.filing_date) if e.form25_sub is not None else _to_date(e.delist_date))
    lo = (day - timedelta(days=SUCCESSOR_BEFORE_DAYS)).isoformat()
    hi = (day + timedelta(days=SUCCESSOR_AFTER_DAYS)).isoformat()
    # the delisting's ticker can be a deleted-symbol spelling ("APAXXXX"): match
    # on every ticker the delisted security carried
    own = (starts[e.sec_id].tickers if e.sec_id in starts else set()) | {e.ticker}
    found: dict[str, str] = {}
    for sid, start in starts.items():
        if sid == e.sec_id or not lo <= start.first_seen <= hi:
            continue
        if start.issuer_cik is not None and start.issuer_cik == e.cik:
            found[sid] = "same_issuer"
        elif own & start.tickers:
            found[sid] = "same_ticker"
    return next(iter(found.items())) if len(found) == 1 else None


def _successor_search_args(edgar, e: DelistingEvent, starts: dict[str, SecurityStart],
                           securities: dict[str, Security]) -> tuple[str, date] | None:
    """The (name, day) stage 9 sends EDGAR's full-text search for `e`
    (`successor_query` builds the search), or None when it sends none: the
    successor is known, or it is a security of this run (`_successor_in_run`).
    The warm pass and the sequential loop both ask this, so they send the same
    searches. Only an event it searches for reads EDGAR (the issuer's
    submissions, for its name)."""
    if "successor_unknown" not in e.flags or _successor_in_run(e, starts) is not None:
        return None
    return (successor_search_name(edgar, e.cik, securities[e.sec_id].name),
            e.last_trade.day or _to_date(e.delist_date))


def _acquirer_cik(clients: Clients, acq: str, day: date, target: DelistingEvent) -> int | None:
    """The acquirer's issuer CIK. The resolver answers for (ticker, day), so an
    acquirer that took the target's own ticker (Progressive Waste becoming
    Waste Connections under WCN) resolves to the target's CIK, often through the
    target era's pin. Then the SEC ticker map's holder (company_tickers.json)
    stands in when it is a different company whose EDGAR record lists the
    ticker on a major exchange today; otherwise the CIK is left unknown rather
    than copied from the target."""
    cik = clients.resolver.resolve(acq, day.isoformat()).cik
    if normalize_ticker(acq) != normalize_ticker(target.ticker) and (cik is None or cik != target.cik):
        return cik
    companies = clients.edgar.company_tickers() or {}
    row = companies.get(acq.upper()) or companies.get(acq.upper().replace(".", "-")) or {}
    try:
        holder = int(row.get("cik_str"))
    except (TypeError, ValueError):
        return None
    if holder == target.cik or not edgar_lists(clients.edgar, holder, [acq]):
        return None
    return holder


def _close_age(row_date: str, last_trade: date) -> int:
    """Trading days from the close a fails row dated `row_date` carries (that of
    the trading day before it) to `last_trade`: 1 for a row dated the last
    trade day itself."""
    day, n = previous_trading_day(date.fromisoformat(row_date)), 0
    while day < last_trade:
        day, n = next_trading_day(day), n + 1
    return n


def _ticker_on(sig: list[Sighting]) -> Callable[[str], str | None]:
    def f(day: str) -> str | None:
        before = [s.value for s in sig if s.day <= day]
        if before:
            return before[-1]
        return sig[0].value if sig else None
    return f


def _resolution_source(sec: Security, cik_res: dict) -> str:
    """The resolver tier ("cik_map", "manual", "company_tickers", ...) that
    found the security's issuer CIK: that of its latest era with a CIK, the
    same era `build_securities` takes `issuer_cik` from; "security_master"
    when none has one."""
    for e in reversed(sec.eras):
        r = cik_res.get(e.key)
        if r is not None and r.cik is not None:
            return r.source or "security_master"
    return "security_master"


def _own_last_seen(sec: Security, sig: list[Sighting]) -> str:
    """The latest sighting under one of the security's own era tickers, else
    the latest era end date.

    FTD rows found by CUSIP include a post-delisting OTC tail under another
    symbol (e.g. a bankrupt XYZ trading as XYZQ), which would otherwise push
    `last_seen` past the real delisting and misdate a fallback delisting.
    """
    own = {e.ticker for e in sec.eras}
    dates = [s.day for s in sig if s.value in own]
    return dates[-1] if dates else max(e.last for e in sec.eras)


class _StageMeter:
    """SEC traffic per pipeline stage, from edgar.SEC_STATS: logged as each stage
    ends and kept for run_manifest.json. Counts cover every thread (the warm pass's
    and the stage's own). EDGAR endpoints are counted apart from SEC data-file
    downloads (fails-to-deliver and MIDAS ZIPs and their index pages)."""

    def __init__(self, log: Callable) -> None:
        self.log = log
        self.stages: dict[str, dict[str, int]] = {}

    def start(self):
        return SEC_STATS.snapshot()

    def done(self, stage: str, mark) -> None:
        counts, _ = SEC_STATS.since(mark)
        edgar_n = sum(v for k, v in counts.items() if k.startswith("request:") and k != "request:sec_data")
        data_n = counts.get("request:sec_data", 0)
        self.stages[stage] = {"edgar_requests": edgar_n, "sec_data_downloads": data_n}
        self.log(f"{stage}: {edgar_n} EDGAR requests, {data_n} SEC data-file downloads (all threads)")


def _flush_memo(clients: Clients) -> None:
    """Write the resolver's batched memo now (TickerResolver.flush)."""
    flush = getattr(clients.resolver, "flush", None)
    if flush is not None:
        flush()


DEGRADED_FLAG = "resolution_degraded"


def _degraded_item(sec_id: str, ticker: str, cik: int | None, what: str, then: str = "",
                   **where: str) -> ReviewItem:
    """The `resolution_degraded` review row saying `what` rested on a failed EDGAR
    request or a stale copy (`then` appended); `where` is its `delist_date` or
    `last_seen`."""
    return ReviewItem(sec_id, ticker, cik, DEGRADED_FLAG,
                      f"{what} rested on a failed EDGAR request or a stale copy{then}", **where)


class _DegradedWatch:
    """Whether an EDGAR answer on this thread rested on a failed request or a stale
    copy since the watch was made (edgar.SEC_STATS.thread_degraded())."""

    def __init__(self) -> None:
        self._mark = SEC_STATS.thread_degraded()

    def tripped(self) -> bool:
        return SEC_STATS.thread_degraded() > self._mark

    def report(self, review: list[ReviewItem], item: ReviewItem, flag_rows: Sequence[DelistingEvent] = ()) -> None:
        """When tripped: add `item` to `review`, and the flag to each of `flag_rows`'
        own delistings.csv row, so the flag reaches the delisting itself, not only
        review.csv."""
        if not self.tripped():
            return
        review.append(item)
        for ev in flag_rows:
            ev.add_flag(DEGRADED_FLAG)

    def report_event(self, review: list[ReviewItem], e: DelistingEvent, what: str, *, own_row: bool = True) -> None:
        """`report` for one delisting's `what`: its review row, and with `own_row`
        its delistings.csv row too."""
        self.report(review, _degraded_item(e.sec_id, e.ticker, e.cik, what, delist_date=e.delist_date),
                    [e] if own_row else ())


def _review_item_row(item: ReviewItem) -> dict:
    """A review item as a review.csv row (before triage)."""
    return {"sec_id": item.sec_id, "delist_date": item.delist_date, "ticker": item.ticker, "cik": item.cik,
            "review_flags": item.flag, "reason": item.reason, "last_seen": item.last_seen}


def _warm_delisting_search(clients: Clients, ordered: list[Security], listing: dict[str, dict],
                           context: Callable[[Security, bool | None], SecurityContext], workers: int,
                           retired: frozenset[str] = frozenset()) -> None:
    """Fill the SEC caches for the Form 25 search: each security's own finder work
    on `workers` threads, fill-only, its answers thrown away. A warm finder is the
    sequential finder's twin: a copy of the run's classifier holding a shadow
    resolver, and the run's own MIDAS and Nasdaq-halt clients, each behind one lock
    shared by every warm finder. It therefore takes the same last-trade anchors
    and asks for what the sequential pass will. A security whose batched OpenFIGI
    answer is missing is skipped: the sequential pass asks OpenFIGI for it alone,
    and its listing status decides what the finder reads."""
    midas = Serialized(clients.midas) if clients.midas is not None else None
    halts = Serialized(clients.halts) if clients.halts is not None else None

    def make_finder() -> DelistingFinder:
        classifier = copy.copy(clients.classifier)
        if getattr(classifier, "resolver", None) is not None:
            classifier.resolver = clients.resolver.shadow()
        return DelistingFinder(clients.edgar, classifier, midas=midas, halts=halts)

    def task(finder: DelistingFinder, s: Security) -> None:
        answer = listing.get(s.sec_id)
        if answer is None and not is_placeholder(s.sec_id):
            return
        now = False if s.sec_id in retired else listed_today(
            None, s.sec_id, edgar=clients.edgar, cik=s.issuer_cik,
            tickers=sorted({e.ticker for e in s.eras}), answer=answer)
        finder.find(context(s, now))

    warm(ordered, task, workers=workers, state=make_finder, name="delisting search")


def run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path,
        tol: float = DEFAULT_TOL, limit: int | None = None, log: Callable = _stderr,
        sec_workers: int = 1, review_decisions: Sequence[Decision] = ()) -> RunSummary:
    """Observations -> the seven tables under `out_dir` (spec §8): `review_decisions`
    (`review_triage.load_decisions`: "I checked this flag on this row, it is
    fine") is passed straight to `review_triage.triage`, which writes
    review.csv (severity-ordered, info-only rows hidden, accepted tokens
    removed) and review_summary.csv (review.csv's rows by flag). A decision
    that accepts nothing becomes a `review_decision_unmatched:<flag>` row
    instead of being silently dropped, except under `limit`, where most rows
    are out of the subset and unmatched decisions are only counted in the
    log. `RunSummary.review_flags`/the manifest's own
    `review_flags` still count every flag from *before* triage or decisions
    (so exit code 3 always sees every `error`/`resolution_degraded`, decision
    or not); the new `RunSummary.review_counts` (= `triaged.counts`, also under
    the manifest's `"review"` key) reports triage's own tally
    (fix/check/info_hidden/accepted/cleared/unmatched_decisions).

    `sec_workers` > 1 fills the SEC caches ahead of each SEC-heavy stage on that
    many threads (`prefetch.warm`: fill-only, every thread under the one limiter).
    Each stage itself still runs one item at a time, in its usual order, on this
    thread, so the same caches and run date (`clients.as_of`) give byte-identical
    tables for any worker count. A refusal on any thread aborts the run before
    anything is written. The resolver's memo is written after issuer resolution,
    after the acquirer lookups, and on the way out, error or not. On the way out
    of an aborted run, a memo that cannot be written is logged and the abort (a
    refusal, an OpenFIGI outage, Ctrl-C) is what reaches the caller, so the CLI
    still exits with that abort's code (2 for a refusal, 1 for an outage)."""
    try:
        summary = _run(index, clients, overrides, out_dir=out_dir, tol=tol, limit=limit, log=log,
                       sec_workers=sec_workers, review_decisions=review_decisions)
    except BaseException:
        try:
            _flush_memo(clients)
        except OSError as exc:
            log(f"could not save the resolver memo while aborting: {exc}")
        raise
    _flush_memo(clients)
    return summary


def _run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path, tol: float,
         limit: int | None, log: Callable, sec_workers: int,
         review_decisions: Sequence[Decision] = ()) -> RunSummary:
    as_of = clients.as_of or date.today()     # the one run date: every window below ends on it
    meter = _StageMeter(log)
    run_mark = SEC_STATS.snapshot()           # the manifest reports the traffic since here
    eras = index.eras()
    if limit:
        eras = eras[:limit]
    log(f"{len(eras)} ticker eras")

    if not eras:
        raise ValueError("no observations to process")

    # 1. FTD rows for the eras' tickers (first: they date each era's real last sighting),
    # then split the observation eras further on that evidence (a CUSIP switch, or a
    # gap no FTD row bridges). Every later step works on the refined eras.
    lo = max(FTD_START, min(_to_date(e.first) for e in eras) - timedelta(days=30))
    hi = min(as_of, max(_to_date(e.last) for e in eras) + timedelta(days=400))
    class_names: dict[str, list[str]] = defaultdict(list)     # BF-B's names: checks FTD's "BFB" rows
    for e in eras:
        if "-" in e.ticker:
            class_names[e.ticker] += e.names
    ftd = FtdIndex.load(clients.ftd_client, lo, hi, symbols={e.ticker for e in eras},
                        cusips={c for e in eras for c in e.cusips}, names=class_names)
    eras = refine_eras(eras, ftd)
    era_by_key = eras_by_key(eras)               # raises on a duplicate key: an era is never dropped
    log(f"{len(eras)} eras after the FTD split")

    # 2. issuer CIK per era, resolved at the era's last sighting: index snapshots can
    # be months apart, and the resolver's Form 25 search is anchored on this date.
    # The resolver tier that found it (cik_map, manual, company_tickers, ...) is kept
    # for the delisting rows' resolution_source.
    # Each era's own pin: a pin looked up by (ticker, date) can belong to a
    # neighbouring era when the last sighting falls between the two.
    last_seen = {e.key: era_last_seen(e, ftd) for e in eras}
    mark = meter.start()
    if sec_workers > 1:
        # Warm the EDGAR caches: each era resolved on a worker thread by a shadow
        # resolver (a snapshot of this memo that saves nothing), its answer thrown
        # away. The resolve below then runs one era at a time, in order, on this
        # thread, and finds its requests answered.
        warm(eras, lambda shadow, e: shadow.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin),
             workers=sec_workers, state=clients.resolver.shadow, name="issuer resolution")
    cik_res = {e.key: clients.resolver.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin) for e in eras}
    _flush_memo(clients)
    meter.done("issuer resolution", mark)
    ciks = {k: r.cik for k, r in cik_res.items()}

    # 3. FIGI per era -> securities. An era takes only the FTD CUSIPs whose rows
    # describe its issuer, by its observed names or the issuer's EDGAR names (D21),
    # and a ticker or name hit whose name agrees with those same names (§8.3).
    issuer_names = {cik: _issuer_names(clients.edgar, cik) for cik in dict.fromkeys(ciks.values()) if cik}
    issuers = issuers_by_era(ciks, issuer_names)
    cusips = candidate_cusips(eras, ftd, issuers)
    resolutions = FigiResolver(clients.figi).resolve_many(eras, issuers=issuers, cusips=cusips)
    securities = build_securities(resolutions, era_by_key, ciks)
    review: list[ReviewItem] = []
    for key, res in resolutions.items():
        era = era_by_key[key]
        for flag in res.flags:
            review.append(ReviewItem(res.sec_id or "", era.ticker, ciks.get(key), flag,
                                     f"{era.key} {era.name or ''}".strip(), last_seen=era.last))
    for e in eras:
        if clients.resolver.is_degraded(e.ticker, last_seen[e.key]):
            review.append(_degraded_item(resolutions[e.key].sec_id or "", e.ticker, ciks.get(e.key),
                                         f"{e.key} {e.name or ''}: issuer resolution",
                                         "; its answer was used for this run but not saved", last_seen=e.last))
    review += _conflict_review(eras, resolutions)
    review += _unconfirmed_review(eras, ftd, resolutions, ciks)
    log(f"{len(securities)} securities; FIGI sources "
        f"{dict(Counter(s.figi_source for s in securities.values()))}")

    # 4. each security's CUSIPs over its whole life: every CUSIP of each of its eras
    # that resolved to its FIGI (a reverse split's old and new CUSIP both)
    sec_cusips = {sid: list(dict.fromkeys(c for e in s.eras for c in resolutions[e.key].cusips))
                  for sid, s in securities.items()}
    ftd.extend(clients.ftd_client, lo, as_of, cusips={c for v in sec_cusips.values() for c in v})

    # 5. delistings
    siblings: dict[int, list[SecurityRef]] = defaultdict(list)
    for s in securities.values():
        if s.issuer_cik is not None:
            siblings[s.issuer_cik].append(SecurityRef(s.sec_id, s.share_class, s.kind, s.name))
    finder = DelistingFinder(clients.edgar, clients.classifier, midas=clients.midas, halts=clients.halts)
    events: list[DelistingEvent] = []
    listed: dict[str, bool | None] = {}
    sightings = {sid: _sightings(s, ftd, sec_cusips[sid]) for sid, s in securities.items()}

    def security_context(s: Security, listed_now: bool | None) -> SecurityContext:
        sig = sightings[s.sec_id]
        sibs = siblings.get(s.issuer_cik) or [SecurityRef(s.sec_id, s.share_class, s.kind, s.name)]
        # sec_id -> (first sighting, last own-ticker sighting) for every security
        # sharing this issuer CIK, from the same sightings built above; a sibling
        # with no sightings gets no entry (the finder treats it as alive at every
        # filing). The end reuses _own_last_seen so a sibling's post-delisting OTC
        # tail under another symbol can't extend its life past its real death.
        spans: dict[str, tuple[str, str]] = {}
        for ref in sibs:
            sib_sig = sightings.get(ref.sec_id)
            if not sib_sig:
                continue
            sib_sec = securities.get(ref.sec_id)
            span_end = _own_last_seen(sib_sec, sib_sig) if sib_sec is not None else sib_sig[-1].day
            spans[ref.sec_id] = (sib_sig[0].day, span_end)
        return SecurityContext(
            security=s,
            siblings=sibs,
            ticker_on=_ticker_on(sig),
            last_seen=_own_last_seen(s, sig),
            seen_after=lambda day, sig=sig: any(x.day > day for x in sig),
            listed_today=listed_now,
            expected_name=s.eras[-1].name if s.eras else None,
            sibling_spans=spans,
            resolution_source=_resolution_source(s, cik_res),
            ftd_seen_after=lambda day, sig=sig, own={e.ticker for e in s.eras}: any(
                x.day > day for x in sig if x.source == "ftd" and x.value in own),
            tickers_between=lambda lo, hi, sig=sig: list(dict.fromkeys(x.value for x in sig if lo <= x.day <= hi)),
        )

    ordered = sorted(securities.values(), key=lambda s: s.sec_id)
    # One batched OpenFIGI ask for every security's listing; a failed batch leaves
    # each security to ask alone inside its own try below.
    listing = listing_answers(clients.figi, [s.sec_id for s in ordered])
    mark = meter.start()
    # A placeholder has no FIGI to ask; EDGAR answers for its ticker, which a
    # later line of the issuer may hold today. Its own CUSIP failing only under
    # a deleted symbol at the end says it is not the line listed today.
    retired = frozenset(s.sec_id for s in ordered
                        if is_placeholder(s.sec_id) and ftd.symbol_deleted(sec_cusips[s.sec_id]))
    if sec_workers > 1:
        _warm_delisting_search(clients, ordered, listing, security_context, sec_workers, retired)
    for i, s in enumerate(ordered, 1):
        own_last_seen = _own_last_seen(s, sightings[s.sec_id])
        ticker = s.eras[-1].ticker if s.eras else ""
        watch = _DegradedWatch()
        try:
            # listed_today and the context live inside the try too: a FIGI/EDGAR
            # error there must become a reviewable row for this one security,
            # not abort the whole overnight run.
            listed[s.sec_id] = False if s.sec_id in retired else listed_today(
                clients.figi, s.sec_id, edgar=clients.edgar, cik=s.issuer_cik,
                tickers=sorted({e.ticker for e in s.eras}), answer=listing.get(s.sec_id))
            found, found_review = finder.find(security_context(s, listed[s.sec_id]))
        except FATAL:
            raise
        except Exception as exc:  # an overnight run must survive one bad security
            log(f"[{i}/{len(securities)}] {s.sec_id}: ERROR {type(exc).__name__}: {exc}")
            review.append(ReviewItem(s.sec_id, ticker, s.issuer_cik, "error",
                                     f"{type(exc).__name__}: {exc}", last_seen=own_last_seen))
            continue
        events += found
        review += found_review
        watch.report(review, _degraded_item(s.sec_id, ticker, s.issuer_cik, "the delisting search",
                                            "; run again once SEC answers", last_seen=own_last_seen), found)
        if i % 50 == 0:
            log(f"[{i}/{len(securities)}] securities searched; {len(events)} delistings so far")
    meter.done("delisting search", mark)

    # 6. every override must name a delisting
    keys = [e.key for e in events]
    bad = []
    for name, m in (("--last-trade-closes", overrides.last_trade_closes),
                    ("--merger-terms", overrides.merger_terms), ("--recoveries", overrides.recoveries)):
        bad += [f"{name}: {k}" for k in unmatched_override_keys(m, keys)]
    if bad:
        raise ValueError("override rows that match no delisting: " + "; ".join(map(str, bad)))

    # 7. last-trade closes. The FTD rows were loaded from the eras' first sighting
    # on; a delisting whose last trade came earlier (a stale snapshot listed the
    # security after it was gone) needs the rows around that day first.
    early = [e for e in events if e.last_trade.day is not None and FTD_START <= e.last_trade.day < lo]
    if early:
        days = [e.last_trade.day for e in early]
        ftd.extend(clients.ftd_client, min(days) - timedelta(days=20), max(days) + timedelta(days=10),
                   symbols={e.ticker for e in early},
                   cusips={c for e in early for c in sec_cusips.get(e.sec_id, [])})
    closes: dict[DelistingKey, float] = {}
    for e in events:
        key = e.key
        given = for_delisting(overrides.last_trade_closes, e.key)
        if given is not None:
            closes[key] = given
            continue
        if e.last_trade.day is None:
            e.add_flag("no_last_close")
            continue
        sec = securities[e.sec_id]
        cusip_ranges = ranges_from_sightings(_cusip_sightings(sec, ftd, sec_cusips.get(e.sec_id, [])),
                                             end=None, open_ended=True)
        cusip = value_on(cusip_ranges, e.last_trade.day)
        got = ftd.close_of(e.last_trade.day, cusip=cusip, symbol=e.ticker)
        if got is None:
            # Fails stop once trading stops, so no row may follow the last trade
            # day: look back a few rows (spec §16). The flag carries the close's
            # age in trading days (ftd_close_prior:<n>); the evidence the row date.
            back = ftd.close_known_on(e.last_trade.day, cusip=cusip, symbol=e.ticker)
            if back is None:
                e.add_flag("no_last_close")
            else:
                closes[key] = back[0]
                e.record.evidence["ftd_close_row_date"] = back[1]
                e.add_flag(f"ftd_close_prior:{_close_age(back[1], e.last_trade.day)}")
            continue
        price, _, lagged = got
        closes[key] = price
        if lagged:
            e.add_flag("ftd_close_lagged")

    # 8. merger payouts, LLM terms, acquirer prices and securities
    payouts_raw, llm_terms = {}, {}
    mergers = [e for e in events if e.record.bucket is CrspBucket.MERGER]
    mark = meter.start()
    if sec_workers > 1 and clients.payout_extractor is not None:
        # The regex payout reader's EDGAR reads, warmed. The LLM extractor is not
        # warmed: its calls are paid, and it has its own cache.
        extractor = clients.payout_extractor
        warm(mergers, lambda e: extractor.extract(e.record, last_close=closes.get(e.key)),
             workers=sec_workers, name="payouts")
    for e in mergers:
        key = e.key
        watch = _DegradedWatch()
        try:
            if clients.payout_extractor is not None:
                payouts_raw[key] = clients.payout_extractor.extract(e.record, last_close=closes.get(key))
            if clients.llm_extractor is not None:
                t = clients.llm_extractor.extract(e.record)
                if t is not None:
                    llm_terms[key] = t
        except FATAL:
            raise
        except Exception as exc:  # an overnight run must survive one bad extraction
            log(f"{e.sec_id} {e.delist_date}: payout extraction ERROR {type(exc).__name__}: {exc}")
            review.append(ReviewItem(e.sec_id, e.ticker, e.cik, "error", f"{type(exc).__name__}: {exc}",
                                     delist_date=e.delist_date))
        watch.report_event(review, e, "payout extraction")
    trade_day = {e.key: e.last_trade.day for e in events}
    acq_symbols = {normalize_ticker(t.acquirer_ticker) for t in llm_terms.values() if t.acquirer_ticker}
    acq_symbols |= {normalize_ticker(v["acquirer_ticker"]) for v in overrides.merger_terms.values()
                    if v.get("acquirer_ticker")}
    if acq_symbols:
        days = [d for d in trade_day.values() if d]
        if days:
            ftd.extend(clients.ftd_client, min(days) - timedelta(days=10), max(days) + timedelta(days=10),
                       symbols=acq_symbols)

    lagged_acquirer: set[DelistingKey] = set()

    def acquirer_price(ticker: str, key: DelistingKey) -> float | None:
        # Priced on THAT merger's own last-trade day: many mergers can share a
        # delist_date, so a plain date->day map would misprice one with another's.
        day = trade_day.get(key)
        got = ftd.close_after(day, symbol=ticker) if day and ticker else None
        if got is None:
            return None
        if got[2]:
            lagged_acquirer.add(key)
        return got[0]

    regex = {k: pr for k, pr in payouts_raw.items() if pr is not None and pr.value is not None}
    gated = gate_payouts(
        [e.key for e in mergers],
        {k: pr.value for k, pr in regex.items()}, {k: pr.source for k, pr in regex.items()},
        {k: pr.confidence for k, pr in regex.items()}, llm_terms, closes, overrides.merger_terms,
        acquirer_price, tol,
    )
    for e in mergers:
        # A lagged FTD close (no row on the next trading day) may carry an OTC or
        # stale price: flag the delisting when that price made it into its terms.
        terms = for_delisting(gated.merged_terms, e.key)
        if e.key in lagged_acquirer and terms and terms.get("acquirer_price") is not None:
            e.add_flag("acquirer_close_lagged")
    added: dict[str, AddedSecurity] = {}
    acquirer_ids: dict[DelistingKey, str] = {}
    for e in mergers:
        key = e.key
        terms = for_delisting(gated.merged_terms, e.key)
        if not terms:
            continue
        acq = normalize_ticker(terms.get("acquirer_ticker") or "")
        day = trade_day.get(key)
        if not acq or day is None:
            continue
        # An acquirer that took the target's ticker (a holding company, Ashland
        # 2016) shares the fails rows under it with the target, whose own CUSIP
        # keeps failing after the last trade: count only other CUSIPs.
        own_cusips = set(sec_cusips.get(e.sec_id, []))
        rows = [r for r in ftd.by_symbol(acq, (day - timedelta(days=10)).isoformat(),
                                         (day + timedelta(days=10)).isoformat()) if r.cusip not in own_cusips]
        cusip = Counter(r.cusip for r in rows).most_common(1)
        if not cusip:
            continue
        ans = clients.figi.map([{"idType": "ID_CUSIP", "idValue": cusip[0][0], "includeUnlistedEquities": True}])[0]
        cand = accept(us_candidates(ans.get("data") or []), ticker=acq, names=[], via_cusip=True)
        if cand is None or cand.composite == e.sec_id:
            continue
        acquirer_ids[key] = cand.composite
        if cand.composite not in securities:
            if cand.composite not in added:
                watch = _DegradedWatch()
                acq_cik = _acquirer_cik(clients, acq, day, e)
                watch.report_event(review, e, f"the acquirer {acq} CIK lookup", own_row=False)
                added[cand.composite] = AddedAcquirer(
                    Security(cand.composite, acq_cik, share_class_from_name(cand.name), cand.name,
                             cand.security_type, False, "cusip"), acq, day)
            # Union every merger's FTD window for this acquirer: several mergers
            # can name the same acquirer, and its ticker_history row must span
            # all of them, not just the first one processed.
            added[cand.composite].rows += rows
    _flush_memo(clients)                       # the acquirer lookups resolved tickers
    meter.done("payouts", mark)

    # 9. successors after a FIGI change: first a security of this run that starts
    # right after the last trade under the same issuer or ticker (a holdco
    # reorganization's new line, a rename's new FIGI), then the successor
    # issuer's 8-K12B (search: EDGAR full-text search, wired in default_clients).
    successor_search = getattr(clients.edgar, "full_text_search", None)
    mark = meter.start()
    starts: dict[str, SecurityStart] = {
        sid: SecurityStart(sig[0].day, securities[sid].issuer_cik, {x.value for x in sig})
        for sid, sig in sightings.items() if sig}
    for sid, a in added.items():
        starts[sid] = SecurityStart(a.span()[0], a.security.issuer_cik, {a.ticker})
    for e in events:                           # a security of this run
        in_run = _successor_in_run(e, starts) if "successor_unknown" in e.flags else None
        if in_run is None:
            continue
        sid, how = in_run
        e.set_successor(sid)
        e.record.evidence["successor_by"] = how
        e.record.reason = f"{e.record.reason}; successor by {how.replace('_', ' ')}"
    if successor_search is not None:           # else the successor issuer's 8-K12B
        if sec_workers > 1:
            def warm_search(e: DelistingEvent) -> None:
                args = _successor_search_args(clients.edgar, e, starts, securities)
                if args is not None:
                    successor_search(*successor_query(*args))
            warm(events, warm_search, workers=sec_workers, name="successor search")
        for e in events:
            watch = _DegradedWatch()
            args = _successor_search_args(clients.edgar, e, starts, securities)
            if args is None:
                continue
            name, day = args
            predecessor = securities[e.sec_id]
            hit = successor_from_8k12b(successor_search, clients.figi, name=name, day=day,
                                       exclude_cik=e.cik, share_class=predecessor.share_class,
                                       edgar=clients.edgar,
                                       own_tickers={x.ticker for x in predecessor.eras} | {e.ticker})
            watch.report_event(review, e, "the successor search")
            if hit is None:
                continue
            s_cik, cand, filing_date = hit
            e.set_successor(cand.composite)
            if cand.composite not in securities and cand.composite not in added:
                # A same-ticker successor (a holding-company reorg) must not overlap
                # the predecessor's own ticker_history row, even when its 8-K12B was
                # filed before the predecessor's actual last trade: clamp valid_from
                # to no earlier than the day after that last trade (or delist_date
                # when the last trade day is unknown).
                not_before = ((e.last_trade.day or _to_date(e.delist_date)) + timedelta(days=1)).isoformat()
                fd = filing_date or day.isoformat()
                added[cand.composite] = AddedSuccessor(
                    Security(cand.composite, s_cik, share_class_from_name(cand.name), cand.name,
                             cand.security_type, False, "ticker"), cand.ticker, max(fd, not_before))
    meter.done("successor search", mark)

    # 10. rows
    table = build_delistings_table(
        [e.record for e in events], last_trade_closes=closes, payouts=gated.payouts,
        exchanges={e.key: e.exchange for e in events},
        merger_terms=gated.merged_terms, recovery_ratios=overrides.recoveries,
        payout_sources=gated.sources, payout_confidences=gated.confidences, payout_flags=gated.flags,
    )
    ev_by_key = {e.key: e for e in events}
    delisting_rows, review_rows = [], []
    for enriched in table:
        e = ev_by_key[DelistingKey(enriched.sec_id, enriched.delist_date)]
        pr = payouts_raw.get(e.key)
        delisting_rows.append(delisting_row(
            enriched, exchange=e.exchange or None,
            last_trade_date=e.last_trade.day.isoformat() if e.last_trade.day else None,
            last_trade_date_source=e.last_trade.source or None,
            successor_sec_id=e.record.successor_sec_id,
            acquirer_sec_id=acquirer_ids.get(e.key),
            raw_payout_per_share=pr.value if pr else None, raw_payout_source=pr.source if pr else None,
            raw_payout_confidence=pr.confidence if pr else None,
        ))
        # A delisting with a blank DLRET must reach triage even with no flags at
        # all -- resolve_dlret can return NaN with no flag added (e.g. a
        # --last-trade-closes override of 0 or a negative --recoveries/
        # --merger-terms value on a non-merger bucket: the override was "given", so
        # no_last_close is never added). triage() itself drops a flagless row with a
        # real DLRET without counting it, so adding one here is safe either way.
        if enriched.review_flags or is_blank(delisting_rows[-1]["dlret"]):
            anchor_8k = (enriched.evidence or {}).get("anchor_8k") or {}
            review_rows.append({"sec_id": enriched.sec_id, "delist_date": enriched.delist_date,
                                "ticker": enriched.ticker, "cik": enriched.cik, "bucket": enriched.bucket.value,
                                "dlret": delisting_rows[-1]["dlret"], "review_flags": ";".join(enriched.review_flags),
                                "reason": enriched.reason, "anchor_8k": anchor_8k.get("items")})
    review_rows += [_review_item_row(item) for item in review]

    th_rows, ch_rows = [], []
    final = {}
    for e in sorted(events, key=lambda e: e.delist_date):
        final[e.sec_id] = e
    for sid, s in securities.items():
        sig = sightings.get(sid, [])
        last_delisting = final.get(sid)
        is_listed = bool(listed.get(sid))
        end = None
        if last_delisting is not None and not is_listed:
            # A last-trade day we couldn't confirm still clips the ranges at the
            # delisting date -- an unclipped range would otherwise run past a
            # security's real end.
            end = (last_delisting.last_trade.day.isoformat() if last_delisting.last_trade.day is not None
                   else last_delisting.delist_date)
        clipped = [x for x in sig if end is None or x.day <= end]
        for rg in ranges_from_sightings(clipped, end=end, open_ended=is_listed):
            if last_delisting is not None and end is not None and rg.valid_to == end:
                exch = last_delisting.exchange
            elif rg.valid_to is None:
                # An open (listed-today) row: pull the exchange from the issuer's
                # own EDGAR submissions JSON (already cached by the finder).
                exch = issuer_exchange(clients.edgar, s.issuer_cik, rg.value)
            else:
                exch = None
            th_rows.append({"sec_id": sid, "ticker": rg.value, "exchange": exch, "valid_from": rg.valid_from,
                            "valid_to": rg.valid_to, "source": rg.source})
        cus = [x for x in _cusip_sightings(s, ftd, sec_cusips.get(sid, [])) if end is None or x.day <= end]
        for rg in ranges_from_sightings(cus, end=end, open_ended=is_listed):
            ch_rows.append({"sec_id": sid, "cusip": rg.value, "valid_from": rg.valid_from,
                            "valid_to": rg.valid_to, "source": rg.source})

    # Added (acquirer/successor) securities get one row each, built directly:
    # ranges_from_sightings' filter that drops single-value FTD sightings would
    # otherwise silently drop a successor's lone 8-K12B-dated sighting.
    for sid, a in added.items():
        listed[sid] = listed_today(clients.figi, sid, edgar=clients.edgar, cik=a.security.issuer_cik,
                                   tickers=[a.ticker])
        is_listed = bool(listed[sid])
        exch = issuer_exchange(clients.edgar, a.security.issuer_cik, a.ticker) if is_listed else None
        th_rows.append(a.history_row(listed=is_listed, exchange=exch))

    review_rows += [_review_item_row(item) for item in _ticker_range_review(th_rows)]

    payout_rows = []
    for key, pr in payouts_raw.items():
        value = gated.payouts.get(key)
        source = gated.sources.get(key, "none")
        # Restore the old CLI's provenance rule: an LLM-sourced payout cites the
        # LLM filing's accession (its regex accession, if any, is often blank or
        # belongs to a different filing tier).
        if source.startswith("llm"):
            t = llm_terms.get(key)
            accession = t.source.partition(":")[2] if t is not None else None
        else:
            accession = pr.accession if pr and value is not None else None
        payout_rows.append({"sec_id": key.sec_id, "delist_date": key.delist_date, "ticker": ev_by_key[key].ticker,
                            "payout_per_share": value, "confidence": gated.confidences.get(key, "none"),
                            "source": source, "accession": accession})

    review_rows = _merge_review_rows(review_rows)
    # Every flag of the run, counted before triage hides or accepts any: this
    # feeds RunSummary.review_flags and the manifest, so exit code 3 still sees
    # every `error` and `resolution_degraded`.
    flags = Counter(flag_name(f) for r in review_rows for f in (r.get("review_flags") or "").split(";") if f)
    # A --limit dev subset (or a second universe sharing the repo-relative
    # default data/review_decisions.csv) can only see a fraction of the rows a
    # decisions file was written against, so every decision outside it would
    # otherwise turn into review-noise, not a real signal. report_unmatched
    # counts them regardless (triaged.counts["unmatched_decisions"]); only the
    # rows (and their review_summary.csv entry) are suppressed.
    report_unmatched = limit is None
    triaged = triage(review_rows, review_decisions, report_unmatched=report_unmatched)
    if not report_unmatched and triaged.counts["unmatched_decisions"]:
        log(f"{triaged.counts['unmatched_decisions']} decision(s) in data/review_decisions.csv matched no row in "
            f"this --limit {limit} subset; not reported as review_decision_unmatched rows")

    # 11. write -- every table formatted and written to temp files first,
    # renamed into place together, so a later table's failure never leaves an
    # earlier table's new file sitting over the previous complete one.
    counts = write_tables(out_dir, {
        "securities": [s.row() for s in securities.values()] + [a.security.row() for a in added.values()],
        "ticker_history": th_rows,
        "cusip_history": ch_rows,
        "delistings": delisting_rows,
        "payouts": payout_rows,
        "review": triaged.review_rows,
        "review_summary": triaged.summary_rows,
    })
    stat_counts, stat_timings = SEC_STATS.since(run_mark)
    run_manifest.write(out_dir, run_manifest.build(as_of=as_of, sec_workers=sec_workers, counts=stat_counts,
                                                   timings=stat_timings, stages=meter.stages,
                                                   review_flags=dict(flags), review=triaged.counts))
    return RunSummary(counts, dict(Counter(e.record.bucket.value for e in events)),
                      dict(Counter(s.figi_source for s in securities.values())), dict(flags), dict(triaged.counts))


def default_clients(index: ObservationIndex, *, cache_dir: Path, rename_map: dict | None = None,
                    manual_overrides: dict | None = None, extract_payouts: bool = True,
                    extract_llm: bool = False, llm_model: str | None = None, use_midas: bool = True,
                    use_halts: bool = True, as_of: date | None = None) -> Clients:
    """The production clients. Every client is dated `as_of` (default: today,
    read once here), the resolver batches its memo writes, and the SEC limit is
    made machine-wide (edgar.use_machine_wide_limit)."""
    from .classifier import DelistClassifier
    from .edgar import EdgarClient, use_machine_wide_limit
    from .ftd import FtdClient
    from .midas import MidasClient
    from .nasdaq_halts import NasdaqHaltClient
    from .openfigi import OpenFigiClient, resolve_api_key
    from .payout_extractor import PayoutExtractor
    from .ticker_resolver import TickerResolver

    as_of = as_of or date.today()
    use_machine_wide_limit()
    edgar = EdgarClient(cache_dir=cache_dir / "edgar", today=as_of)
    resolver = TickerResolver(edgar, rename_map=rename_map,
                              manual_overrides={k: v for k, v in (manual_overrides or {}).items() if v > 0},
                              cache_path=cache_dir / "ticker_resolution.json",
                              member_names=index.name_on, cik_map=index.cik_pin_on, today=as_of,
                              batch_writes=True)
    llm = None
    if extract_llm:
        from .llm_client import default_llm_client
        from .llm_merger_extractor import LLMMergerTermsExtractor
        llm = LLMMergerTermsExtractor(edgar, default_llm_client(llm_model), cache_dir=cache_dir / "llm")
    return Clients(
        edgar=edgar, resolver=resolver, classifier=DelistClassifier(edgar, resolver, today=as_of),
        figi=OpenFigiClient(cache_dir / "openfigi", resolve_api_key()),
        ftd_client=FtdClient(cache_dir / "sec_data" / "ftd"),
        midas=MidasClient(cache_dir / "sec_data" / "midas") if use_midas else None,
        halts=NasdaqHaltClient(cache_dir / "nasdaq_halts", today=as_of) if use_halts else None,
        payout_extractor=PayoutExtractor(edgar) if extract_payouts else None,
        llm_extractor=llm, as_of=as_of,
    )

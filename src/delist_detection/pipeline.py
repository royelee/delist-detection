# src/delist_detection/pipeline.py
"""End-to-end run: observations -> security master and delistings (spec §8).

Everything is computed first and written last, so a refusal or a bad override
file never leaves a half-written output over the previous complete one.
"""
from __future__ import annotations

import copy
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from .acquirers import acquirer_cik, find_acquirer
from .crsp_codes import CrspBucket
from .delistings import SUCCESSOR_UNKNOWN, Delisting, DelistingFinder, SecurityContext
from .edgar import SEC_STATS
from .evidence import edgar_names
from .fatal import FATAL
from .figi_resolution import is_placeholder, share_class_from_name
from .form25 import SecurityRef
from .ftd import FtdIndex
from .listing_status import issuer_exchange, listed_today, listing_answers
from . import manifest as run_manifest
from .observations import ObservationIndex, TickerEra, eras_by_key, normalize_ticker, observation_conflicts
from .payout_gate import DEFAULT_TOL, GatedPayouts, gate_payouts
from .prefetch import Serialized, warm
from .reconstruction import (
    OverrideFileError, build_delistings_table, delisting_row, for_delisting, override_row_name,
    unmatched_override_keys,
)
from .review_triage import Decision, ReviewItem, Triage, flag_name, is_blank, triage
from .security_master import (
    AddedAcquirer, AddedSecurity, AddedSuccessor, EraResolution, FigiResolver, Issuer, Security, Sighting,
    build_securities, candidate_cusips, cik_of, cusip_sightings, era_last_seen, history_rows, issuers_by_era,
    own_last_seen, ranges_from_sightings, refine_eras, ticker_range_review, ticker_sightings, value_on,
)
from .store import DelistingKey, write_tables
from .successors import (
    SecurityStart, successor_from_8k12b, successor_in_run, successor_query, successor_search_args,
)
from .ticker_resolver import TickerResolution
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


def _issuer_names(edgar, ciks: Iterable[int]) -> tuple[dict[int, tuple[str, ...]], set[int]]:
    """Every name EDGAR records for each issuer (`evidence.edgar_names` of the
    submissions JSON the resolver already read), and the CIKs whose read rested
    on a failed EDGAR request or a stale copy. A read that fails outright
    leaves that issuer with no EDGAR names -- its eras are checked against
    their observed names only -- instead of stopping the run; a refusal
    (EdgarBlocked) still stops it."""
    names: dict[int, tuple[str, ...]] = {}
    degraded: set[int] = set()
    for cik in ciks:
        watch = _DegradedWatch()
        try:
            sub = edgar.submissions(cik)
        except requests.RequestException:
            sub = None
            degraded.add(cik)
        names[cik] = edgar_names(sub) if isinstance(sub, dict) else ()
        if watch.tripped():
            degraded.add(cik)
    return names, degraded


TICKER_CONFIRM_DAYS = 30        # an era's ticker counts as confirmed by an FTD row this close to its span


def _unconfirmed_review(eras: list[TickerEra], ftd: FtdIndex, resolutions: dict,
                        issuers: dict[str, Issuer]) -> list[ReviewItem]:
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
        out.append(ReviewItem(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key), "ticker_unconfirmed",
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


def _resolution_source(sec: Security, issuers: dict[str, Issuer], resolutions: dict[str, TickerResolution]) -> str:
    """The resolver tier ("cik_map", "manual", "company_tickers", ...) that
    found the security's issuer CIK: that of its latest era whose issuer is
    known (`issuers`), the same era `build_securities` takes `issuer_cik` from;
    "security_master" when none has one."""
    for e in reversed(sec.eras):
        if e.key in issuers:
            return resolutions[e.key].source or "security_master"
    return "security_master"


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

    def report(self, review: list[ReviewItem], item: ReviewItem, flag_rows: Sequence[Delisting] = ()) -> None:
        """When tripped: add `item` to `review`, and the flag to each of `flag_rows`'
        own delistings.csv row, so the flag reaches the delisting itself, not only
        review.csv."""
        if not self.tripped():
            return
        review.append(item)
        for delisting in flag_rows:
            _flag_degraded(delisting)

    def report_delisting(self, review: list[ReviewItem], e: Delisting, what: str, *, own_row: bool = True) -> None:
        """`report` for one delisting's `what`: its review row, and with `own_row`
        its delistings.csv row too."""
        self.report(review, _degraded_item(e.sec_id, e.ticker, e.cik, what, delist_date=e.delist_date),
                    [e] if own_row else ())


def _flag_degraded(delisting: Delisting) -> None:
    if DEGRADED_FLAG not in delisting.flags:
        delisting.add_flag(DEGRADED_FLAG)


def _report_halt_feed_failures(review: list[ReviewItem], delistings: Sequence[Delisting]) -> None:
    """Each delisting whose last-trade decision asked the Nasdaq halt feed for a
    day it could not read (`LastTrade.halt_feed_failed`): the same treatment as
    a failed SEC request -- `resolution_degraded` on its own delistings.csv row,
    and a review row naming the feed and the days."""
    for d in delistings:
        if not d.last_trade.halt_feed_failed:
            continue
        days = ", ".join(sorted({day.isoformat() for day in d.last_trade.halt_feed_failed}))
        review.append(ReviewItem(d.sec_id, d.ticker, d.cik, DEGRADED_FLAG,
                                 f"the last-trade date rested on a failed Nasdaq halt feed read ({days}); "
                                 "run again once the feed answers", delist_date=d.delist_date))
        _flag_degraded(d)


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
    still exits with that abort's code (2 for a refusal, 4 for an OpenFIGI outage)."""
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


@dataclass
class _RunContext:
    """What every stage of one run shares: the clients, the one run date (every
    window ends on it), the log, the prefetch worker count and the SEC meter."""
    clients: Clients
    as_of: date
    log: Callable
    sec_workers: int
    meter: _StageMeter


def _refine(ctx: _RunContext, index: ObservationIndex,
            limit: int | None) -> tuple[list[TickerEra], dict[str, TickerEra], FtdIndex, date]:
    """1. The observation eras, refined on SEC fails-to-deliver evidence: FTD rows
    for the eras' tickers are loaded first (they date each era's real last
    sighting), then each era is split further on that evidence (a CUSIP switch,
    or a gap no FTD row bridges). Every later step works on the refined eras.
    Returns them, by key too, the FTD index, and the first day it covers."""
    eras = index.eras()
    if limit:
        eras = eras[:limit]
    ctx.log(f"{len(eras)} ticker eras")

    if not eras:
        raise ValueError("no observations to process")

    lo = max(FTD_START, min(_to_date(e.first) for e in eras) - timedelta(days=30))
    hi = min(ctx.as_of, max(_to_date(e.last) for e in eras) + timedelta(days=400))
    class_names: dict[str, list[str]] = defaultdict(list)     # BF-B's names: checks FTD's "BFB" rows
    for e in eras:
        if "-" in e.ticker:
            class_names[e.ticker] += e.names
    ftd = FtdIndex.load(ctx.clients.ftd_client, lo, hi, symbols={e.ticker for e in eras},
                        cusips={c for e in eras for c in e.cusips}, names=class_names)
    eras = refine_eras(eras, ftd)
    era_by_key = eras_by_key(eras)               # raises on a duplicate key: an era is never dropped
    ctx.log(f"{len(eras)} eras after the FTD split")
    return eras, era_by_key, ftd, lo


@dataclass
class _IssuerAnswers:
    """Stage 2's answer for each era: the resolver's (`resolutions`, by era key:
    the tier that found it), its `Issuer` (`issuers`: CIK and EDGAR names, for
    the eras whose issuer is known -- the one source of an era's CIK), the
    era's last sighting the resolver was asked at, and the issuer CIKs whose
    names read was degraded."""
    resolutions: dict[str, TickerResolution]
    issuers: dict[str, Issuer]
    last_seen: dict[str, str]
    names_degraded: set[int]


def _resolve_issuers(ctx: _RunContext, eras: list[TickerEra], ftd: FtdIndex) -> _IssuerAnswers:
    """2. The issuer CIK of each era, resolved at the era's last sighting (index
    snapshots can be months apart, and the resolver's Form 25 search is anchored
    on this date), with each era's own pin (a pin looked up by (ticker, date) can
    belong to a neighbouring era when the last sighting falls between the two).
    The resolver tier that found it (cik_map, manual, company_tickers, ...) is
    kept for the delisting rows' resolution_source. Then each issuer's EDGAR
    names, which stage 3 checks CUSIPs and FIGI names against."""
    clients, workers = ctx.clients, ctx.sec_workers
    last_seen = {e.key: era_last_seen(e, ftd) for e in eras}
    mark = ctx.meter.start()
    if workers > 1:
        # Warm the EDGAR caches: each era resolved on a worker thread by a shadow
        # resolver (a snapshot of this memo that saves nothing), its answer thrown
        # away. The resolve below then runs one era at a time, in order, on this
        # thread, and finds its requests answered.
        warm(eras, lambda shadow, e: shadow.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin),
             workers=workers, state=clients.resolver.shadow, name="issuer resolution")
    cik_res = {e.key: clients.resolver.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin) for e in eras}
    _flush_memo(clients)
    ciks = {k: r.cik for k, r in cik_res.items()}
    issuer_ciks = [cik for cik in dict.fromkeys(ciks.values()) if cik]
    if workers > 1:
        warm(issuer_ciks, clients.edgar.submissions, workers=workers, name="issuer names")
    issuer_names, names_degraded = _issuer_names(clients.edgar, issuer_ciks)
    ctx.meter.done("issuer resolution", mark)
    return _IssuerAnswers(cik_res, issuers_by_era(ciks, issuer_names), last_seen, names_degraded)


def _resolve_securities(ctx: _RunContext, eras: list[TickerEra], era_by_key: dict[str, TickerEra], ftd: FtdIndex,
                        answers: _IssuerAnswers
                        ) -> tuple[dict[str, EraResolution], dict[str, Security], list[ReviewItem]]:
    """3. FIGI per era -> securities. An era takes only the FTD CUSIPs whose rows
    describe its issuer, by its observed names or the issuer's EDGAR names (D21),
    and a ticker or name hit whose name agrees with those same names (§8.3).
    Returns each era's resolution, the securities, and the review items of
    eras that resolved to no FIGI or rested on a degraded answer."""
    issuers = answers.issuers
    cusips = candidate_cusips(eras, ftd, issuers)
    resolutions = FigiResolver(ctx.clients.figi).resolve_many(eras, issuers=issuers, cusips=cusips)
    securities = build_securities(resolutions, era_by_key, issuers)
    review: list[ReviewItem] = []
    for key, res in resolutions.items():
        era = era_by_key[key]
        for flag in res.flags:
            review.append(ReviewItem(res.sec_id or "", era.ticker, cik_of(issuers, key), flag,
                                     f"{era.key} {era.name or ''}".strip(), last_seen=era.last))
    for e in eras:
        if ctx.clients.resolver.is_degraded(e.ticker, answers.last_seen[e.key]):
            review.append(_degraded_item(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key),
                                         f"{e.key} {e.name or ''}: issuer resolution",
                                         "; its answer was used for this run but not saved", last_seen=e.last))
    for e in eras:
        if cik_of(issuers, e.key) in answers.names_degraded:
            review.append(_degraded_item(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key),
                                         f"{e.key} {e.name or ''}: the issuer's EDGAR names",
                                         "; its CUSIPs and FIGI were checked without what could not be read",
                                         last_seen=e.last))
    review += _conflict_review(eras, resolutions)
    review += _unconfirmed_review(eras, ftd, resolutions, issuers)
    ctx.log(f"{len(securities)} securities; FIGI sources "
            f"{dict(Counter(s.figi_source for s in securities.values()))}")
    return resolutions, securities, review


def _security_cusips(ctx: _RunContext, securities: dict[str, Security], resolutions: dict[str, EraResolution],
                     ftd: FtdIndex, ftd_lo: date) -> dict[str, list[str]]:
    """4. Each security's CUSIPs over its whole life: every CUSIP of each of its
    eras that resolved to its FIGI (a reverse split's old and new CUSIP both),
    with their FTD rows loaded up to the run date."""
    sec_cusips = {sid: list(dict.fromkeys(c for e in s.eras for c in resolutions[e.key].cusips))
                  for sid, s in securities.items()}
    ftd.extend(ctx.clients.ftd_client, ftd_lo, ctx.as_of, cusips={c for v in sec_cusips.values() for c in v})
    return sec_cusips


def _context_builder(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
                     answers: _IssuerAnswers) -> Callable[[Security, bool | None], SecurityContext]:
    """The finder's `SecurityContext` for a security of the run, given whether it
    is listed today."""
    siblings: dict[int, list[SecurityRef]] = defaultdict(list)
    for s in securities.values():
        if s.issuer_cik is not None:
            siblings[s.issuer_cik].append(SecurityRef(s.sec_id, s.share_class, s.kind, s.name))

    def security_context(s: Security, listed_now: bool | None) -> SecurityContext:
        sig = sightings[s.sec_id]
        sibs = siblings.get(s.issuer_cik) or [SecurityRef(s.sec_id, s.share_class, s.kind, s.name)]
        # sec_id -> (first sighting, last own-ticker sighting) for every security
        # sharing this issuer CIK, from the same sightings built above; a sibling
        # with no sightings gets no entry (the finder treats it as alive at every
        # filing). The end reuses own_last_seen so a sibling's post-delisting OTC
        # tail under another symbol can't extend its life past its real death.
        spans: dict[str, tuple[str, str]] = {}
        for ref in sibs:
            sib_sig = sightings.get(ref.sec_id)
            if not sib_sig:
                continue
            sib_sec = securities.get(ref.sec_id)
            span_end = own_last_seen(sib_sec, sib_sig) if sib_sec is not None else sib_sig[-1].day
            spans[ref.sec_id] = (sib_sig[0].day, span_end)
        return SecurityContext(
            security=s,
            siblings=sibs,
            ticker_on=_ticker_on(sig),
            last_seen=own_last_seen(s, sig),
            seen_after=lambda day, sig=sig: any(x.day > day for x in sig),
            listed_today=listed_now,
            expected_name=s.eras[-1].name if s.eras else None,
            sibling_spans=spans,
            resolution_source=_resolution_source(s, answers.issuers, answers.resolutions),
            ftd_seen_after=lambda day, sig=sig, own={e.ticker for e in s.eras}: any(
                x.day > day for x in sig if x.source == "ftd" and x.value in own),
            tickers_between=lambda lo, hi, sig=sig: list(dict.fromkeys(x.value for x in sig if lo <= x.day <= hi)),
        )

    return security_context


@dataclass
class _DelistingSearch:
    """Stage 5's answer: every delisting found, whether each security is listed
    today, each security's dated ticker sightings, and the review items."""
    delistings: list[Delisting]
    listed: dict[str, bool | None]
    sightings: dict[str, list[Sighting]]
    review: list[ReviewItem]


def _find_delistings(ctx: _RunContext, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
                     ftd: FtdIndex, answers: _IssuerAnswers) -> _DelistingSearch:
    """5. Every delisting of every security (`DelistingFinder`), in sec_id order.
    A security whose search fails becomes an `error` review item, not an aborted
    run; only a fatal exception (`fatal.FATAL`) stops it."""
    clients, log = ctx.clients, ctx.log
    finder = DelistingFinder(clients.edgar, clients.classifier, midas=clients.midas, halts=clients.halts)
    delistings: list[Delisting] = []
    listed: dict[str, bool | None] = {}
    review: list[ReviewItem] = []
    sightings = {sid: ticker_sightings(s, ftd, sec_cusips[sid]) for sid, s in securities.items()}
    security_context = _context_builder(securities, sightings, answers)

    ordered = sorted(securities.values(), key=lambda s: s.sec_id)
    # One batched OpenFIGI ask for every security's listing; a failed batch leaves
    # each security to ask alone inside its own try below.
    listing = listing_answers(clients.figi, [s.sec_id for s in ordered])
    mark = ctx.meter.start()
    # A placeholder has no FIGI to ask; EDGAR answers for its ticker, which a
    # later line of the issuer may hold today. Its own CUSIP failing only under
    # a deleted symbol at the end says it is not the line listed today.
    retired = frozenset(s.sec_id for s in ordered
                        if is_placeholder(s.sec_id) and ftd.symbol_deleted(sec_cusips[s.sec_id]))
    if ctx.sec_workers > 1:
        _warm_delisting_search(clients, ordered, listing, security_context, ctx.sec_workers, retired)
    for i, s in enumerate(ordered, 1):
        last_seen = own_last_seen(s, sightings[s.sec_id])
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
                                     f"{type(exc).__name__}: {exc}", last_seen=last_seen))
            continue
        delistings += found
        review += found_review
        watch.report(review, _degraded_item(s.sec_id, ticker, s.issuer_cik, "the delisting search",
                                            "; run again once SEC answers", last_seen=last_seen), found)
        _report_halt_feed_failures(review, found)
        if i % 50 == 0:
            log(f"[{i}/{len(securities)}] securities searched; {len(delistings)} delistings so far")
    ctx.meter.done("delisting search", mark)
    return _DelistingSearch(delistings, listed, sightings, review)


def _check_overrides(overrides: Overrides, delistings: list[Delisting]) -> None:
    """6. Every override row must name a delisting of this run: one that does not
    stops the run before anything is written (OverrideFileError, naming each such
    row's flag, file and line)."""
    keys = [e.key for e in delistings]
    bad = []
    for name, m in (("--last-trade-closes", overrides.last_trade_closes),
                    ("--merger-terms", overrides.merger_terms), ("--recoveries", overrides.recoveries)):
        bad += [f"{name} {override_row_name(m, k)}" for k in unmatched_override_keys(m, keys)]
    if bad:
        raise OverrideFileError("override rows that match no delisting: " + "; ".join(bad))


def _last_trade_closes(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                       sec_cusips: dict[str, list[str]], ftd: FtdIndex, ftd_lo: date,
                       overrides: Overrides) -> dict[DelistingKey, float]:
    """7. Each delisting's last-trade close: a --last-trade-closes row, else the
    FTD close of its last trade day (by the security's CUSIP on that day, then its
    ticker), flagging the delisting where none is found or it is lagged or older.
    The FTD rows were loaded from the eras' first sighting on; a delisting whose
    last trade came earlier (a stale snapshot listed the security after it was
    gone) needs the rows around that day first."""
    early = [e for e in delistings if e.last_trade.day is not None and FTD_START <= e.last_trade.day < ftd_lo]
    if early:
        days = [e.last_trade.day for e in early]
        ftd.extend(ctx.clients.ftd_client, min(days) - timedelta(days=20), max(days) + timedelta(days=10),
                   symbols={e.ticker for e in early},
                   cusips={c for e in early for c in sec_cusips.get(e.sec_id, [])})
    closes: dict[DelistingKey, float] = {}
    for e in delistings:
        key = e.key
        given = for_delisting(overrides.last_trade_closes, e.key)
        if given is not None:
            closes[key] = given
            continue
        if e.last_trade.day is None:
            e.add_flag("no_last_close")
            continue
        sec = securities[e.sec_id]
        cusip_ranges = ranges_from_sightings(cusip_sightings(sec, ftd, sec_cusips.get(e.sec_id, [])),
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
    return closes


@dataclass
class _Payouts:
    """Stage 8's answer: the regex payout reads and the LLM terms (by delisting),
    what the payout gate kept, each merger's acquirer security, the securities
    the run adds for them, and the review items."""
    raw: dict[DelistingKey, Any]
    llm_terms: dict[DelistingKey, Any]
    gated: GatedPayouts
    acquirer_ids: dict[DelistingKey, str]
    added: dict[str, AddedSecurity]
    review: list[ReviewItem]


def _extract_payouts(ctx: _RunContext, mergers: list[Delisting], closes: dict[DelistingKey, float],
                     review: list[ReviewItem]) -> tuple[dict[DelistingKey, Any], dict[DelistingKey, Any]]:
    """The regex payout read and the LLM merger terms of each merger. A failed
    extraction becomes an `error` review item (added to `review`)."""
    clients, raw, llm_terms = ctx.clients, {}, {}
    if ctx.sec_workers > 1 and clients.payout_extractor is not None:
        # The regex payout reader's EDGAR reads, warmed. The LLM extractor is not
        # warmed: its calls are paid, and it has its own cache.
        extractor = clients.payout_extractor
        warm(mergers, lambda e: extractor.extract(e.record, last_close=closes.get(e.key)),
             workers=ctx.sec_workers, name="payouts")
    for e in mergers:
        key = e.key
        watch = _DegradedWatch()
        try:
            if clients.payout_extractor is not None:
                raw[key] = clients.payout_extractor.extract(e.record, last_close=closes.get(key))
            if clients.llm_extractor is not None:
                t = clients.llm_extractor.extract(e.record)
                if t is not None:
                    llm_terms[key] = t
        except FATAL:
            raise
        except Exception as exc:  # an overnight run must survive one bad extraction
            ctx.log(f"{e.sec_id} {e.delist_date}: payout extraction ERROR {type(exc).__name__}: {exc}")
            review.append(ReviewItem(e.sec_id, e.ticker, e.cik, "error", f"{type(exc).__name__}: {exc}",
                                     delist_date=e.delist_date))
        watch.report_delisting(review, e, "payout extraction")
    return raw, llm_terms


def _gate(ctx: _RunContext, mergers: list[Delisting], trade_day: dict[DelistingKey, date | None],
          ftd: FtdIndex, raw: dict[DelistingKey, Any], llm_terms: dict[DelistingKey, Any],
          closes: dict[DelistingKey, float], overrides: Overrides, tol: float) -> GatedPayouts:
    """Every merger payout through the last-close check (`payout_gate`), the
    acquirer's price read from its FTD rows around that merger's own last trade
    day (`trade_day`). A merger whose terms took a lagged acquirer close is flagged."""
    acq_symbols = {normalize_ticker(t.acquirer_ticker) for t in llm_terms.values() if t.acquirer_ticker}
    acq_symbols |= {normalize_ticker(v["acquirer_ticker"]) for v in overrides.merger_terms.values()
                    if v.get("acquirer_ticker")}
    if acq_symbols:
        days = [d for d in trade_day.values() if d]
        if days:
            ftd.extend(ctx.clients.ftd_client, min(days) - timedelta(days=10), max(days) + timedelta(days=10),
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

    regex = {k: pr for k, pr in raw.items() if pr is not None and pr.value is not None}
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
    return gated


def _add_acquirers(ctx: _RunContext, mergers: list[Delisting], trade_day: dict[DelistingKey, date | None],
                   gated: GatedPayouts, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
                   ftd: FtdIndex, review: list[ReviewItem]) -> tuple[dict[DelistingKey, str], dict[str, AddedSecurity]]:
    """Each merger's acquirer security (`acquirers.find_acquirer`), by the
    acquirer ticker its terms name, and the acquirers the run adds as securities
    of their own (`AddedAcquirer`, their issuer CIK from `acquirers.acquirer_cik`).
    A degraded acquirer-CIK lookup is a review item (added to `review`)."""
    acquirer_ids: dict[DelistingKey, str] = {}
    added: dict[str, AddedSecurity] = {}
    for e in mergers:
        key = e.key
        terms = for_delisting(gated.merged_terms, e.key)
        if not terms:
            continue
        acq = normalize_ticker(terms.get("acquirer_ticker") or "")
        day = trade_day.get(key)
        if not acq or day is None:
            continue
        found = find_acquirer(ctx.clients.figi, ftd, acq, day, set(sec_cusips.get(e.sec_id, [])))
        if found is None:
            continue
        cand, rows = found
        if cand.composite == e.sec_id:
            continue
        acquirer_ids[key] = cand.composite
        if cand.composite not in securities:
            if cand.composite not in added:
                watch = _DegradedWatch()
                acq_cik = acquirer_cik(ctx.clients.resolver, ctx.clients.edgar, acq, day, e)
                watch.report_delisting(review, e, f"the acquirer {acq} CIK lookup", own_row=False)
                added[cand.composite] = AddedAcquirer(
                    Security(cand.composite, acq_cik, share_class_from_name(cand.name), cand.name,
                             cand.security_type, False, "cusip"), acq, day)
            # Union every merger's FTD window for this acquirer: several mergers
            # can name the same acquirer, and its ticker_history row must span
            # all of them, not just the first one processed.
            added[cand.composite].rows += rows
    return acquirer_ids, added


def _merger_payouts(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                    sec_cusips: dict[str, list[str]], ftd: FtdIndex, closes: dict[DelistingKey, float],
                    overrides: Overrides, tol: float) -> _Payouts:
    """8. Merger payouts, LLM terms, acquirer prices and acquirer securities."""
    mergers = [e for e in delistings if e.record.bucket is CrspBucket.MERGER]
    review: list[ReviewItem] = []
    mark = ctx.meter.start()
    raw, llm_terms = _extract_payouts(ctx, mergers, closes, review)
    trade_day = {e.key: e.last_trade.day for e in delistings}
    gated = _gate(ctx, mergers, trade_day, ftd, raw, llm_terms, closes, overrides, tol)
    acquirer_ids, added = _add_acquirers(ctx, mergers, trade_day, gated, securities, sec_cusips, ftd, review)
    _flush_memo(ctx.clients)                  # the acquirer lookups resolved tickers
    ctx.meter.done("payouts", mark)
    return _Payouts(raw, llm_terms, gated, acquirer_ids, added, review)


def _find_successors(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                     sightings: dict[str, list[Sighting]], added: dict[str, AddedSecurity]) -> list[ReviewItem]:
    """9. Successors after a FIGI change: first a security of this run that starts
    right after the last trade under the same issuer or ticker (a holdco
    reorganization's new line, a rename's new FIGI), then the successor issuer's
    8-K12B (search: EDGAR full-text search, wired in default_clients). A
    successor that is no security of the run is added to `added`. Returns the
    review items."""
    clients, review = ctx.clients, []
    successor_search = getattr(clients.edgar, "full_text_search", None)
    mark = ctx.meter.start()
    starts: dict[str, SecurityStart] = {
        sid: SecurityStart(sig[0].day, securities[sid].issuer_cik, {x.value for x in sig})
        for sid, sig in sightings.items() if sig}
    for sid, a in added.items():
        starts[sid] = SecurityStart(a.span()[0], a.security.issuer_cik, {a.ticker})
    for e in delistings:                       # a security of this run
        in_run = successor_in_run(e, starts) if SUCCESSOR_UNKNOWN in e.flags else None
        if in_run is None:
            continue
        sid, how = in_run
        e.set_successor(sid)
        e.record.evidence["successor_by"] = how
        e.record.reason = f"{e.record.reason}; successor by {how.replace('_', ' ')}"
    if successor_search is not None:           # else the successor issuer's 8-K12B
        if ctx.sec_workers > 1:
            def warm_search(e: Delisting) -> None:
                args = successor_search_args(clients.edgar, e, starts, securities)
                if args is not None:
                    successor_search(*successor_query(*args))
            warm(delistings, warm_search, workers=ctx.sec_workers, name="successor search")
        for e in delistings:
            watch = _DegradedWatch()
            args = successor_search_args(clients.edgar, e, starts, securities)
            if args is None:
                continue
            name, day = args
            predecessor = securities[e.sec_id]
            hit = successor_from_8k12b(successor_search, clients.figi, name=name, day=day,
                                       exclude_cik=e.cik, share_class=predecessor.share_class,
                                       edgar=clients.edgar,
                                       own_tickers={x.ticker for x in predecessor.eras} | {e.ticker})
            watch.report_delisting(review, e, "the successor search")
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
    ctx.meter.done("successor search", mark)
    return review


def _delisting_rows(delistings: list[Delisting], closes: dict[DelistingKey, float], payouts: _Payouts,
                    overrides: Overrides) -> tuple[list[dict], list[dict]]:
    """10a. The delistings.csv rows, and the review rows of those delistings that
    carry a flag or no DLRET."""
    gated = payouts.gated
    table = build_delistings_table(
        [e.record for e in delistings], last_trade_closes=closes, payouts=gated.payouts,
        exchanges={e.key: e.exchange for e in delistings},
        merger_terms=gated.merged_terms, recovery_ratios=overrides.recoveries,
        payout_sources=gated.sources, payout_confidences=gated.confidences, payout_flags=gated.flags,
    )
    delisting_by_key = {e.key: e for e in delistings}
    delisting_rows, review_rows = [], []
    for enriched in table:
        e = delisting_by_key[DelistingKey(enriched.sec_id, enriched.delist_date)]
        pr = payouts.raw.get(e.key)
        delisting_rows.append(delisting_row(
            enriched, exchange=e.exchange or None,
            last_trade_date=e.last_trade.day.isoformat() if e.last_trade.day else None,
            last_trade_date_source=e.last_trade.source or None,
            successor_sec_id=e.record.successor_sec_id,
            acquirer_sec_id=payouts.acquirer_ids.get(e.key),
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
    return delisting_rows, review_rows


def _history_rows(ctx: _RunContext, securities: dict[str, Security], search: _DelistingSearch,
                  sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                  added: dict[str, AddedSecurity]) -> tuple[list[dict], list[dict]]:
    """10b. The ticker_history and cusip_history rows (`security_master.history_rows`):
    each observed security's ranges end at its last delisting's last trade day
    unless it is listed today. An added (acquirer/successor) security gets one
    ticker row, built directly: `ranges_from_sightings`' filter that drops
    single-value FTD sightings would otherwise silently drop a successor's lone
    8-K12B-dated sighting."""
    clients = ctx.clients
    th_rows, ch_rows = [], []
    final = {}
    for e in sorted(search.delistings, key=lambda e: e.delist_date):
        final[e.sec_id] = e
    for sid, s in securities.items():
        last_delisting = final.get(sid)
        is_listed = bool(search.listed.get(sid))
        end = None
        if last_delisting is not None and not is_listed:
            # A last-trade day we couldn't confirm still clips the ranges at the
            # delisting date -- an unclipped range would otherwise run past a
            # security's real end.
            end = (last_delisting.last_trade.day.isoformat() if last_delisting.last_trade.day is not None
                   else last_delisting.delist_date)
        th, ch = history_rows(
            s, search.sightings.get(sid, []), cusip_sightings(s, ftd, sec_cusips.get(sid, [])),
            listed=is_listed, end=end, end_exchange=last_delisting.exchange if last_delisting else None,
            # An open (listed-today) row: the exchange from the issuer's own EDGAR
            # submissions JSON (already cached by the finder).
            exchange_today=lambda ticker, s=s: issuer_exchange(clients.edgar, s.issuer_cik, ticker))
        th_rows += th
        ch_rows += ch
    for sid, a in added.items():
        search.listed[sid] = listed_today(clients.figi, sid, edgar=clients.edgar, cik=a.security.issuer_cik,
                                          tickers=[a.ticker])
        is_listed = bool(search.listed[sid])
        exch = issuer_exchange(clients.edgar, a.security.issuer_cik, a.ticker) if is_listed else None
        th_rows.append(a.history_row(listed=is_listed, exchange=exch))
    return th_rows, ch_rows


def _payout_rows(payouts: _Payouts, delistings: list[Delisting]) -> list[dict]:
    """10c. The payouts.csv rows: each merger's gated payout and where it came from."""
    delisting_by_key = {e.key: e for e in delistings}
    gated, rows = payouts.gated, []
    for key, pr in payouts.raw.items():
        value = gated.payouts.get(key)
        source = gated.sources.get(key, "none")
        # Restore the old CLI's provenance rule: an LLM-sourced payout cites the
        # LLM filing's accession (its regex accession, if any, is often blank or
        # belongs to a different filing tier).
        if source.startswith("llm"):
            t = payouts.llm_terms.get(key)
            accession = t.source.partition(":")[2] if t is not None else None
        else:
            accession = pr.accession if pr and value is not None else None
        rows.append({"sec_id": key.sec_id, "delist_date": key.delist_date, "ticker": delisting_by_key[key].ticker,
                     "payout_per_share": value, "confidence": gated.confidences.get(key, "none"),
                     "source": source, "accession": accession})
    return rows


def _triage(ctx: _RunContext, review_rows: list[dict], review_decisions: Sequence[Decision],
            limit: int | None) -> tuple[Counter, Triage]:
    """10d. review.csv and review_summary.csv from every review row of the run
    (merged by key), and every flag counted before triage hides or accepts any:
    that tally feeds RunSummary.review_flags and the manifest, so exit code 3
    still sees every `error` and `resolution_degraded`."""
    review_rows = _merge_review_rows(review_rows)
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
        ctx.log(f"{triaged.counts['unmatched_decisions']} decision(s) in data/review_decisions.csv matched no "
                f"row in this --limit {limit} subset; not reported as review_decision_unmatched rows")
    return flags, triaged


def _run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path, tol: float,
         limit: int | None, log: Callable, sec_workers: int,
         review_decisions: Sequence[Decision] = ()) -> RunSummary:
    """The run's stages in order (each function's docstring says what it does);
    `run` wraps it with the resolver memo's final flush."""
    ctx = _RunContext(clients, clients.as_of or date.today(), log, sec_workers, _StageMeter(log))
    run_mark = SEC_STATS.snapshot()           # the manifest reports the traffic since here
    eras, era_by_key, ftd, ftd_lo = _refine(ctx, index, limit)                                      # 1
    answers = _resolve_issuers(ctx, eras, ftd)                                                      # 2
    resolutions, securities, review = _resolve_securities(ctx, eras, era_by_key, ftd, answers)      # 3
    sec_cusips = _security_cusips(ctx, securities, resolutions, ftd, ftd_lo)                        # 4
    search = _find_delistings(ctx, securities, sec_cusips, ftd, answers)                # 5
    delistings = search.delistings
    review += search.review
    _check_overrides(overrides, delistings)                                                         # 6
    closes = _last_trade_closes(ctx, delistings, securities, sec_cusips, ftd, ftd_lo, overrides)    # 7
    payouts = _merger_payouts(ctx, delistings, securities, sec_cusips, ftd, closes, overrides, tol) # 8
    review += payouts.review
    review += _find_successors(ctx, delistings, securities, search.sightings, payouts.added)        # 9

    # 10. rows
    delisting_rows, review_rows = _delisting_rows(delistings, closes, payouts, overrides)
    review_rows += [item.row() for item in review]
    th_rows, ch_rows = _history_rows(ctx, securities, search, sec_cusips, ftd, payouts.added)
    review_rows += [item.row() for item in ticker_range_review(th_rows)]
    flags, triaged = _triage(ctx, review_rows, review_decisions, limit)

    # 11. write -- every table formatted and written to temp files first,
    # renamed into place together, so a later table's failure never leaves an
    # earlier table's new file sitting over the previous complete one.
    counts = write_tables(out_dir, {
        "securities": [s.row() for s in securities.values()] + [a.security.row() for a in payouts.added.values()],
        "ticker_history": th_rows,
        "cusip_history": ch_rows,
        "delistings": delisting_rows,
        "payouts": _payout_rows(payouts, delistings),
        "review": triaged.review_rows,
        "review_summary": triaged.summary_rows,
    })
    stat_counts, stat_timings = SEC_STATS.since(run_mark)
    run_manifest.write(out_dir, run_manifest.build(as_of=ctx.as_of, sec_workers=sec_workers, counts=stat_counts,
                                                   timings=stat_timings, stages=ctx.meter.stages,
                                                   review_flags=dict(flags), review=triaged.counts))
    return RunSummary(counts, dict(Counter(e.record.bucket.value for e in delistings)),
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
                              observed_names=index.name_on, cik_pins=index.cik_pin_on, today=as_of,
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

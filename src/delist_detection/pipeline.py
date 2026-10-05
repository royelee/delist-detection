# src/delist_detection/pipeline.py
"""End-to-end run: observations -> security master and delistings (spec §8).

Everything is computed first and written last, so a refusal or a bad override
file never leaves a half-written output over the previous complete one (the
tables are renamed into place one at a time at the very end; see
`store.write_tables`).
"""
from __future__ import annotations

import copy
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from . import acquirer_line
from . import exchange_terms
from . import manifest as run_manifest
from . import scorecard as run_scorecard
from .acquirers import acquirer_cik, find_acquirer
from .added_securities import AddedAcquirer, AddedLineSuccessor, AddedSecurity, AddedSuccessor
from .crsp_codes import CrspBucket
from .degraded import DegradedWatch, degraded_item, flag_degraded, report_halt_feed_failures
from .delistings import (
    ISSUER_FORM25_FORMS, LATE_ROW_DAYS, SUCCESSOR_UNKNOWN, Delisting, DelistingFinder, SecurityContext,
)
from .distress import (
    BANKRUPTCY_WORDS, OTC_SYMBOL_DAYS, DistressTerms, otc_symbol_from_fails, otc_symbol_from_text, plan_ratio,
    new_cusips as plan_new_cusips, price_only, substitutes_new_shares,
)
from .evidence import edgar_names, item_sections
from .fatal import FATAL
from .handoffs import (
    TAKEOVER_DAYS,
    CONTINUATION_CODE, HandoffDecision, HandoffOutcome, apply_handoffs, continuation_filing, cusip_switch, decide_handoff,
    drop_resolved_shared, find_handoffs, issuer_carries_on, own_continuation_filing, predecessor_names,
)
from .figi_resolution import FigiCandidate, class_letter, is_placeholder, placeholder_id, share_class_from_name
from .form25 import SecurityRef, letter_hint, notice_last_trade, parse_form25
from .last_trade import decide_last_trade
from .ftd import FTD_START, FtdIndex, FtdRow, close_age, is_trading_symbol, settled_last, trades_after
from .trading_calendar import previous_trading_day
from .history import (
    Sighting, backfill_cusips, clip_at_takeovers, cusip_sightings, filtered_ticker_sightings, history_rows, observation_map_rows, own_last_seen,
    ranges_from_sightings, ticker_on, ticker_range_review, ticker_sightings, value_on,
)
from .line_follow import Decision as LineDecision
from .line_follow import (
    ATTACH, FOLD, MAX_ROUNDS, READ_FAILED, REFUSED, SUCCESSOR, SUCCESSOR_FORMS, SWITCH, LineEnd, LineStep,
    LineSuccessor, candidate_steps,
    composites, corroborate, decide, eightks_near, is_line_symbol, line_end, name_on, other_registrant, text_cusips,
    text_symbols,
)
from .listing_status import edgar_lists, issuer_exchange, listed_today, listing_answers
from .observations import (
    Observation, ObservationError, ObservationIndex, TickerEra, eras_by_key, normalize_ticker, observation_conflicts,
)
from .payout_gate import BY_LINE, BY_TICKER, DEFAULT_TOL, GatedPayouts, gate_payouts
from .trading_calendar import next_trading_day
from .prefetch import Serialized, warm
from .reconstruction import (
    OverrideFileError, build_delistings_table, delisting_row, for_delisting, override_row_name,
    unmatched_override_keys,
)
from .review_triage import Decision, ReviewItem, Triage, flag_name, is_blank, merge_review_rows, triage
from .sec_stats import SEC_STATS
from .security_master import (
    EraResolution, FigiResolver, Issuer, Security, build_securities, candidate_cusips, cik_of, cusip_handoffs,
    cusip_job, detached_review, era_last_seen, issuers_by_era, observation_conflict_review, refine_eras,
    resolve_with_identity_guard, superseded_placeholders, ticker_unconfirmed_review, guarded_eras,
    foreign_ticker_eras,
)
from .lifecycle import Tables
from .ticker_evidence import EraEvidence, evidence_for
from .store import DelistingKey, formatted, write_tables
from .successors import (
    NEW_ISSUER_DAYS, SUCCESSOR_AFTER_DAYS, SUCCESSOR_BEFORE_DAYS, SecurityStart, successor_anchor, successor_by_terms,
    _named as successor_named, successor_from_8k12b, successor_in_run, successor_query, successor_search_args, successor_search_name,
)
from .ticker_resolver import InferredIssuer, TickerResolution, TickerResolver
from .verdict import Verdicts
from .verdict import decide as decide_verdicts
from .contract import delisting_rows as contract_delisting_rows
from .contract import id_change_rows, last_endings, security_history_rows, seed_rows
from .payout_rule import merger_inputs
from .issuer_in_force import Sighting as IssuerSighting
from .issuer_in_force import issuer_changes
from .price_requests import LAST_CLOSE, OTC_PRINT, RECEIVED_CLOSE, key_of, request_rows, stock_legs


BACKFILL_DAYS = 1095   # how far before a dead-before-sighting security's end its fails rows are loaded


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
    price_answers: dict = field(default_factory=dict)      # price_requests.PriceKey -> price (--price-answers)
    acquirer_prices: dict = field(default_factory=dict)    # DelistingKey -> (acquirer ticker, price), from price_answers
    otc_prints: dict = field(default_factory=dict)         # DelistingKey -> OTC print, from price_answers


@dataclass
class RunSummary:
    counts: dict[str, int]
    buckets: dict[str, int]
    figi_sources: dict[str, int]
    review_flags: dict[str, int]
    review_counts: dict[str, int] = field(default_factory=dict)     # review_triage.triage()'s counts
    scorecard_drops: list[str] = field(default_factory=list)        # floored scorecard numbers that got worse
    golden_failures: list[str] = field(default_factory=list)        # golden `pass` cases the tables now fail
    uncertain: dict[str, int] = field(default_factory=dict)         # uncertain verdicts per kind (verdict.Verdicts.counts)


def _stderr(*parts) -> None:
    print(*parts, file=sys.stderr, flush=True)


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
        watch = DegradedWatch()
        try:
            sub = edgar.submissions(cik)
        except requests.RequestException:
            sub = None
            degraded.add(cik)
        names[cik] = edgar_names(sub) if isinstance(sub, dict) else ()
        if watch.tripped():
            degraded.add(cik)
    return names, degraded


def _resolution_source(sec: Security, issuers: dict[str, Issuer], resolutions: dict[str, TickerResolution]) -> str:
    """The resolver tier ("cik_map", "manual", "company_tickers", ...) that
    found the security's issuer CIK: that of its latest era whose issuer is
    known (`issuers`), the same era `build_securities` takes `issuer_cik` from;
    "security_master" when none has one."""
    for e in reversed(sec.eras):
        if e.key in issuers:
            return resolutions[e.key].source or "security_master"
    return "security_master"


def _flush_memo(clients: Clients) -> None:
    """Write the resolver's batched memo now (TickerResolver.flush)."""
    flush = getattr(clients.resolver, "flush", None)
    if flush is not None:
        flush()


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
            tickers=sorted(s.own_tickers()), answer=answer)
        finder.find(context(s, now))

    warm(ordered, task, workers=workers, state=make_finder, name="delisting search")


def run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path,
        tol: float = DEFAULT_TOL, limit: int | None = None, log: Callable = _stderr,
        sec_workers: int = 1, review_decisions: Sequence[Decision] = (),
        scorecard: run_scorecard.ScorecardConfig = run_scorecard.ScorecardConfig(),
        id_baseline: Sequence[Mapping[str, str]] = ()) -> RunSummary:
    """Observations -> the nine tables under `out_dir` and the contract under
    `out_dir`/contract/ (contract.py; `id_baseline`: the securities.csv rows
    id_changes.csv compares with) (spec §8), then
    scorecard.json (`scorecard.build` over those tables, `scorecard`'s window,
    floor and truth cases; floor drops are not checked under `limit`): `review_decisions`
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
                       sec_workers=sec_workers, review_decisions=review_decisions, scorecard=scorecard,
                       id_baseline=id_baseline)
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
    meter: run_manifest.StageMeter


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
        raise ObservationError("no observations to process")

    lo = max(FTD_START, min(date.fromisoformat(e.first) for e in eras) - timedelta(days=30))
    hi = min(ctx.as_of, max(date.fromisoformat(e.last) for e in eras) + timedelta(days=400))
    class_names: dict[str, list[str]] = defaultdict(list)     # BF-B's names: checks FTD's "BFB" rows
    first_seen: dict[str, str] = {}                            # each ticker's first day (rule A's base-symbol bound)
    for e in eras:
        first_seen[e.ticker] = min(e.first, first_seen.get(e.ticker, e.first))
        if "-" in e.ticker:
            class_names[e.ticker] += e.names
    ftd = FtdIndex.load(ctx.clients.ftd_client, lo, hi, symbols={e.ticker for e in eras},
                        cusips={c for e in eras for c in e.cusips}, names=class_names, first_seen=first_seen)
    eras = refine_eras(eras, ftd)
    era_by_key = eras_by_key(eras)               # raises on a duplicate key: an era is never dropped
    ctx.log(f"{len(eras)} eras after the FTD split")
    return eras, era_by_key, ftd, lo


@dataclass
class _IssuerAnswers:
    """Stage 2's answer for each era: the resolver's (`resolutions`, by era key:
    the tier that found it), its `Issuer` (`issuers`: CIK and EDGAR names, for
    the eras whose issuer is known -- the one source of an era's CIK), the
    era's last sighting the resolver was asked at, the issuer CIKs whose
    names read was degraded, and the second pass's answers (`inferred`) and
    contradictions of first-pass answers (`disagreements`)."""
    resolutions: dict[str, TickerResolution]
    issuers: dict[str, Issuer]
    last_seen: dict[str, str]
    names_degraded: set[int]
    inferred: dict[str, InferredIssuer] = field(default_factory=dict)
    disagreements: dict[str, InferredIssuer] = field(default_factory=dict)


def _name_period_checks(resolver, eras: list[TickerEra], ftd: FtdIndex, last_seen: dict[str, str],
                        answers: dict[str, TickerResolution]) -> dict[str, InferredIssuer]:
    """2b. The resolver's name-search answers checked against each era's span and its ticker's fails rows
    (`TickerResolver.name_period_checks`, sub-plan 5h); none from a resolver without the check (a test double)."""
    check = getattr(resolver, "name_period_checks", None)
    return check(eras, ftd, last_seen, answers) if callable(check) else {}


def _resolve_issuers(ctx: _RunContext, eras: list[TickerEra], ftd: FtdIndex) -> _IssuerAnswers:
    """2. The issuer CIK of each era, resolved at the era's last sighting (index
    snapshots can be months apart, and the resolver's Form 25 search is anchored
    on this date), with each era's own pin and name (a pin or name looked up by
    (ticker, date) can belong to a neighbouring era when the last sighting falls
    between the two: FTD rows of a shared CUSIP carry KORS@2012's last sighting
    past KORS@2014's first observation). The resolver tier that found it
    (cik_map, manual, company_tickers, ...) is kept for the delisting rows'
    resolution_source. Then the resolver's second pass (`infer_issuers`, never
    saved) for the eras left with no CIK and no pin: a renamed issuer found by
    its 8-K frequency or by a CUSIP handoff. Then each issuer's EDGAR names,
    which stage 3 checks CUSIPs and FIGI names against."""
    clients, workers = ctx.clients, ctx.sec_workers
    last_seen = {e.key: era_last_seen(e, ftd) for e in eras}
    mark = ctx.meter.start()
    if workers > 1:
        # Warm the EDGAR caches: each era resolved on a worker thread by a shadow
        # resolver (a snapshot of this memo that saves nothing), its answer thrown
        # away. The resolve below then runs one era at a time, in order, on this
        # thread, and finds its requests answered.
        warm(eras, lambda shadow, e: shadow.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin, name=e.name,
                                                    since=e.first),
             workers=workers, state=clients.resolver.shadow, name="issuer resolution")
    cik_res = {e.key: clients.resolver.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin, name=e.name,
                                               since=e.first)
               for e in eras}
    _flush_memo(clients)
    tickers = {e.key: e.ticker for e in eras}
    checked = _name_period_checks(clients.resolver, eras, ftd, last_seen, cik_res)                 # 2b
    for key, found in checked.items():
        cik_res[key] = TickerResolution(tickers[key], found.cik, None, found.source)
    ctx.log(f"name checks: {len(checked)} name-search answers replaced"
            + (f" ({', '.join(f'{k} -> {v.cik}' for k, v in sorted(checked.items()))})" if checked else ""))
    second = clients.resolver.infer_issuers(eras, ftd, last_seen, {k: r.cik for k, r in cik_res.items()})
    for key, found in second.inferred.items():
        cik_res[key] = TickerResolution(tickers[key], found.cik, None, found.source)
    ctx.log(f"resolver's second pass: {len(second.inferred)} issuers inferred, "
            f"{len(second.disagreements)} first-pass answers its CUSIP evidence contradicts")
    ciks = {k: r.cik for k, r in cik_res.items()}
    issuer_ciks = [cik for cik in dict.fromkeys(ciks.values()) if cik]
    if workers > 1:
        warm(issuer_ciks, clients.edgar.submissions, workers=workers, name="issuer names")
    issuer_names, names_degraded = _issuer_names(clients.edgar, issuer_ciks)
    ctx.meter.done("issuer resolution", mark)
    # stage 2b's answers are reported as issuer_inferred, as the second pass's are
    return _IssuerAnswers(cik_res, issuers_by_era(ciks, issuer_names), last_seen, names_degraded,
                          {**checked, **second.inferred}, second.disagreements)


def _trading_span(ftd: FtdIndex, cusip: str) -> tuple[str, str] | None:
    """The first and last day a CUSIP's fails rows show it trading (`FtdIndex.trading_rows`), None for none."""
    rows = ftd.trading_rows([cusip])
    return (rows[0].date, rows[-1].date) if rows else None


def _resolve_securities(ctx: _RunContext, eras: list[TickerEra], era_by_key: dict[str, TickerEra], ftd: FtdIndex,
                        answers: _IssuerAnswers
                        ) -> tuple[dict[str, EraResolution], dict[str, Security], list[ReviewItem]]:
    """3. FIGI per era -> securities. An era takes only the FTD CUSIPs whose rows
    describe its issuer, by its observed names or the issuer's EDGAR names (D21),
    and a ticker or name hit whose name agrees with those same names (§8.3). An
    era with no pick of its own still joins a same-issuer, same-class sibling's
    composite through their shared-CUSIP/switch evidence (`cusip_handoffs`,
    spec §17), when that sibling is confirmed by a pin or a CUSIP. An era no
    fails row shows under its ticker takes no ticker or name pick (a backfilled
    ticker: it is placed on its issuer's line then, if there is exactly one),
    and a weak era whose merge would cross another security's confirmed range
    is taken back out (`resolve_with_identity_guard`). Returns each era's
    resolution, the securities, and the review items of eras that resolved to
    no FIGI, were taken back out, or rested on a degraded answer."""
    issuers = answers.issuers
    cusips = candidate_cusips(eras, ftd, issuers)
    handoffs = cusip_handoffs(eras, ftd)
    foreign = foreign_ticker_eras(eras, ftd, issuers)
    resolutions, detached = resolve_with_identity_guard(
        FigiResolver(ctx.clients.figi, log=ctx.log, cusip_span=lambda c: _trading_span(ftd, c), foreign=foreign),
        eras, issuers=issuers, cusips=cusips, handoffs=handoffs, unconfirmed=guarded_eras(eras, ftd) | foreign)
    securities = build_securities(resolutions, era_by_key, issuers)
    review: list[ReviewItem] = detached_review(detached, era_by_key, resolutions, issuers)
    for key, res in resolutions.items():
        era = era_by_key[key]
        for flag in res.flags:
            review.append(ReviewItem(res.sec_id or "", era.ticker, cik_of(issuers, key), flag,
                                     f"{era.key} {era.name or ''}".strip(), last_seen=era.last))
    for e in eras:
        if ctx.clients.resolver.is_degraded(e.ticker, answers.last_seen[e.key], name=e.name):
            review.append(degraded_item(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key),
                                         f"{e.key} {e.name or ''}: issuer resolution",
                                         "; its answer was used for this run but not saved", last_seen=e.last))
    for e in eras:
        found = answers.inferred.get(e.key)
        if found is not None:
            review.append(ReviewItem(resolutions[e.key].sec_id or "", e.ticker, found.cik, "issuer_inferred",
                                     f"{e.key} {e.name or ''}: issuer {found.cik} by {found.source}: {found.via}",
                                     last_seen=e.last))
        other = answers.disagreements.get(e.key)
        if other is not None:
            first = answers.resolutions[e.key]
            review.append(ReviewItem(resolutions[e.key].sec_id or "", e.ticker, first.cik, "issuer_cusip_disagrees",
                                     f"{e.key} {e.name or ''}: the resolver gave issuer {first.cik} ({first.source}); "
                                     f"its CUSIP evidence gives {other.cik} by {other.source}: {other.via}",
                                     last_seen=e.last))
    for e in eras:
        if cik_of(issuers, e.key) in answers.names_degraded:
            review.append(degraded_item(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key),
                                         f"{e.key} {e.name or ''}: the issuer's EDGAR names",
                                         "; its CUSIPs and FIGI were checked without what could not be read",
                                         last_seen=e.last))
    review += observation_conflict_review(eras, resolutions)
    review += ticker_unconfirmed_review(eras, ftd, resolutions, issuers)
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


LINE_FOLLOWED, LINE_REFUSED = "line_followed", "line_follow_refused"


@dataclass
class _Lines:
    """Stage 4b's answer (`_follow_lines`): the securities, each era's resolution and each security's CUSIPs after
    the line follow; the placeholders folded into a FIGI line (old sec_id -> the FIGI); the FIGI lines another
    composite continues (sec_id -> `line_follow.LineSuccessor`); and the review items."""
    securities: dict[str, Security]
    resolutions: dict[str, EraResolution]
    sec_cusips: dict[str, list[str]]
    renames: dict[str, str] = field(default_factory=dict)
    successors: dict[str, LineSuccessor] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)


class _IssuerReads:
    """The EDGAR reads the line follow makes, each issuer's once: its submissions JSON, its filing list and an
    8-K's text. A read that fails is no answer (None, [], "") for the step that asked and is never stored, so a
    later step asks again; a refusal (`fatal.FATAL`) stops the run. `degraded` holds every CIK one of whose reads
    failed or counted itself degraded (a stale copy, a retried failure): each of its steps gets a
    `resolution_degraded` item."""

    def __init__(self, edgar) -> None:
        self.edgar, self._subs, self._filings = edgar, {}, {}
        self.degraded: set[int] = set()

    def _read(self, cik: int, fn, *args, default):
        """`(answer, ok)`: `fn(*args)`, or `default` when the request failed."""
        watch = DegradedWatch()
        try:
            answer = fn(*args)
        except FATAL:
            raise
        except requests.RequestException:
            self.degraded.add(cik)
            return default, False
        if watch.tripped():
            self.degraded.add(cik)
        return answer, True

    def sub(self, cik: int):
        if cik not in self._subs:
            answer, ok = self._read(cik, self.edgar.submissions, cik, default=None)
            if not ok:
                return None
            self._subs[cik] = answer
        return self._subs[cik]

    def filings(self, cik: int) -> list:
        if cik not in self._filings:
            answer, ok = self._read(cik, self.edgar.recent_filings, cik, default=[])
            if not ok:
                return []
            self._filings[cik] = answer
        return self._filings[cik]

    def text(self, cik: int, f) -> str:
        return self._read(cik, self.edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")[0] or ""


def _cusip_holders(sec_cusips: Mapping[str, Sequence[str]]) -> dict[str, set[str]]:
    holders: dict[str, set[str]] = defaultdict(set)
    for sid, cusips in sec_cusips.items():
        for c in cusips:
            holders[c].add(sid)
    return holders


def _text_sources(reads: _IssuerReads, s: Security, end: LineEnd) -> tuple[set[str], set[str]]:
    """The tickers and CUSIPs the issuer's own 8-Ks around a line's end name as the stock's new ones (APY's
    ChampionX "CHX", Liz Claiborne's "316645100" and "FNP"): read only when one of them is an 8-K item 5.03 or
    3.03 or an 8-K12B/8-K12G3, within `line_follow.FILING_DAYS` of the line's settled last row."""
    day = date.fromisoformat(end.settled)
    near = eightks_near(reads.filings(s.issuer_cik), day,
                        lambda f: f.form in SUCCESSOR_FORMS or bool({"5.03", "3.03"} & f.item_set))
    texts = [reads.text(s.issuer_cik, f) for f in near]
    return {t for t in text_symbols(texts) if is_line_symbol(t)} - s.own_tickers(), text_cusips(texts)


def _other_registrant(reads: _IssuerReads, search, edgar, cik: int, name: str, day: date,
                      own_tickers: set[str]) -> int | None:
    """`line_follow.other_registrant`; a failed read marks `cik` degraded (the step is refused `read_failed`)."""
    other = other_registrant(search, edgar, name=name, day=day, cik=cik, own_tickers=own_tickers)
    if other == READ_FAILED:
        reads.degraded.add(cik)
    return other


def _fold(out: _Lines, p: str, x: str, cand: FigiCandidate, step: LineStep, tickers: dict[str, set[str]]) -> None:
    """Fold placeholder `p` into the FIGI line `x` its new CUSIP's composite names: its eras resolve to `x`
    (source `handoff`, as a CUSIP handoff joins a line in stage 3), its CUSIPs and line tickers join `x`'s, and
    every earlier rename to `p` now points at `x`."""
    for e in out.securities[p].eras:
        out.resolutions[e.key] = replace(out.resolutions[e.key], sec_id=x, source="handoff", candidate=cand, flags=())
    out.sec_cusips[x] = list(dict.fromkeys([*out.sec_cusips.get(x, []), *out.sec_cusips.pop(p, []), step.new_cusip]))
    tickers[x] = tickers.get(x, set()) | tickers.pop(p, set()) | {step.symbol}
    for old, now in list(out.renames.items()):
        if now == p:
            out.renames[old] = x
    out.renames[p] = x


def _today_holder_fold(decision: LineDecision | None, s: Security, resolutions: Mapping[str, EraResolution],
                       tickers: Collection[str]) -> LineDecision | None:
    """A SUCCESSOR decision made a FOLD (sub-plan 5h, R2): the line's composite came from the ticker tier alone
    (its CUSIPs have none of their own), that candidate is today's holder of one of the line's tickers, and the
    step's new composite has left them (its ticker today is another): the ticker answered with the line that took
    the ticker over later, and the line's own next CUSIP names its real composite. California Resources' 2014 era
    took CRC's post-2020 line BBG00Y04KP80 by ticker, while its 2016 reverse split's CUSIP is BBG0060B3M63 (CRCQQ
    after the 2020 bankruptcy); Peabody's took BTU's post-2017 line, its 2015 split's being BTUUQ's. A line whose
    ticker candidate left the ticker (an old line OpenFIGI still lists under it) keeps its successor."""
    if decision is None or decision.kind != SUCCESSOR or decision.candidate is None or s.figi_source != "ticker":
        return decision
    picks = [r.candidate for e in s.eras if (r := resolutions.get(e.key)) is not None and r.source == "ticker"
             and r.candidate is not None]
    own = {normalize_ticker(t) for t in tickers}
    if not picks or any(normalize_ticker(c.ticker) not in own for c in picks) \
            or normalize_ticker(decision.candidate.ticker) in own:
        return decision
    return LineDecision(FOLD, decision.composite, candidate=decision.candidate)


def _follow_lines(ctx: _RunContext, securities: dict[str, Security], resolutions: dict[str, EraResolution],
                  era_by_key: dict[str, TickerEra], sec_cusips: dict[str, list[str]], ftd: FtdIndex, ftd_lo: date,
                  answers: _IssuerAnswers) -> _Lines:
    """4b. Each security's line followed past its observations (`line_follow`; spec 2026-10-03-diagnosis-truth-
    fixes 3 "5a", rulings R1 and R2), before the Form 25 search reads its sightings. A round finds each line's
    next step in the fails rows (`candidate_steps`: a new CUSIP under the line's ticker, or a ticker of the issuer
    EDGAR lists today or its 8-K text names; or the same CUSIP under a new ticker), loads the new CUSIPs' rows to
    the run date, asks OpenFIGI for their composites in one batch, checks each step against the issuer's filings
    (`corroborate`) and applies R2 (`decide`): the same security takes the new CUSIP and ticker; a placeholder
    folds into the FIGI line its new CUSIP names (the securities are rebuilt, `build_securities`); a FIGI line
    whose new CUSIP has its own composite keeps its CUSIPs and records that composite as its line successor for
    stage 9. A line that moved is followed again in the next round, up to `MAX_ROUNDS` (WIN's two reverse
    splits). Every step followed or refused is an info review item (`line_followed`, `line_follow_refused:<why>`);
    a read that rested on a failed request or a stale copy, a `resolution_degraded` one."""
    clients, edgar = ctx.clients, ctx.clients.edgar
    search = getattr(edgar, "full_text_search", None)
    reads = _IssuerReads(edgar)
    mark = ctx.meter.start()
    out = _Lines(dict(securities), dict(resolutions), {k: list(v) for k, v in sec_cusips.items()})
    tickers: dict[str, set[str]] = {sid: set(s.line_tickers) for sid, s in securities.items()}

    def own(sid: str) -> set[str]:
        return out.securities[sid].own_tickers() | tickers.get(sid, set())

    todo = sorted(sid for sid, s in out.securities.items() if s.issuer_cik is not None)
    extra: dict[str, set[str]] = {}
    for sid in todo:
        sub = reads.sub(out.securities[sid].issuer_cik)
        listed = [normalize_ticker(t) for t in (sub.get("tickers") or [])] if isinstance(sub, dict) else []
        extra[sid] = {t for t in listed if is_line_symbol(t)} - own(sid)
    # every line's tickers, their first-day ZZZZ and post-split D spellings and the issuers' other tickers, to the
    # run date (stage 1 loaded the eras' tickers only to 400 days past their last observation)
    spellings = {t.replace("-", "") + suffix for sid in todo for t in own(sid) for suffix in ("", "ZZZZ", "D")}
    ftd.extend(clients.ftd_client, ftd_lo, ctx.as_of, symbols=spellings | {t for v in extra.values() for t in v})
    named: dict[str, set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()
    flagged: set[str] = set()            # securities whose step already got a resolution_degraded item
    for round_no in range(1, MAX_ROUNDS + 1):
        holders = _cusip_holders(out.sec_cusips)

        def steps_of(sid: str) -> list[LineStep]:
            return candidate_steps(sid, out.sec_cusips.get(sid, []), own(sid), ftd, holders=holders,
                                   extra_symbols=extra.get(sid, ()), extra_cusips=named.get(sid, ()),
                                   data_end=ftd.last_date())

        steps = {sid: steps_of(sid) for sid in todo}
        new_symbols: set[str] = set()
        if round_no == 1:
            for sid in todo:
                end = line_end(out.sec_cusips.get(sid, []), own(sid), ftd)
                if steps[sid] or end is None or end.last >= (ctx.as_of - timedelta(days=30)).isoformat():
                    continue
                symbols, cusips = _text_sources(reads, out.securities[sid], end)
                extra[sid] |= symbols
                named[sid] |= cusips
                new_symbols |= symbols
        new_cusips = {st.new_cusip for v in steps.values() for st in v if st.kind == SWITCH}
        new_cusips |= {c for v in named.values() for c in v}
        if new_cusips or new_symbols:
            ftd.extend(clients.ftd_client, ftd_lo, ctx.as_of, cusips=new_cusips, symbols=new_symbols)
            steps = {sid: steps_of(sid) for sid in todo}
        switch_cusips = sorted({v[0].new_cusip for v in steps.values() if v and v[0].kind == SWITCH})
        figi_answers = dict(zip(switch_cusips, clients.figi.map([cusip_job(c) for c in switch_cusips]))) \
            if switch_cusips else {}
        moved: set[str] = set()
        taken: dict[str, str] = {}       # a new CUSIP a security attached or folded into this round: its holder
        for sid in todo:
            if not steps[sid] or sid not in out.securities:
                continue
            step, s = steps[sid][0], out.securities[sid]
            cik = s.issuer_cik
            watch = DegradedWatch()
            first = date.fromisoformat(step.first)
            evidence, refused = corroborate(
                step, filings=reads.filings(cik), sub=reads.sub(cik), share_class=s.share_class,
                text_of=lambda f, cik=cik: reads.text(cik, f), as_of=ctx.as_of,
                listed_now=lambda: edgar_lists(edgar, cik, sorted(own(sid) | {step.symbol})),
                other_registrant=lambda: _other_registrant(reads, search, edgar, cik, name_on(reads.sub(cik), first, s.name),
                                                           first, own(sid)))
            what = f"{step.old_cusip} -> {step.new_cusip} under {step.symbol} from {step.first}"
            decision = None if refused else decide(
                step, s, composites(figi_answers[step.new_cusip]) if step.kind == SWITCH else None, out.securities)
            decision = _today_holder_fold(decision, s, out.resolutions, own(sid))
            if decision is not None and decision.kind == REFUSED:
                refused = decision.why
            elif decision is not None and decision.kind in (ATTACH, FOLD) and step.kind == SWITCH \
                    and taken.setdefault(step.new_cusip, decision.composite or sid) != (decision.composite or sid):
                refused = "taken"     # another security of the run took this CUSIP earlier in the round
            elif decision is not None and decision.kind == SUCCESSOR \
                    and taken.setdefault(decision.composite, sid) != sid:
                refused = "taken"     # ... or this successor composite
            if watch.tripped() or cik in reads.degraded:
                flagged.add(sid)
                out.review.append(degraded_item(sid, step.symbol, cik, f"the line follow ({what})",
                                                "; run again once SEC answers", last_seen=step.old_last))
            if refused:
                counts[f"refused:{refused}"] += 1
                out.review.append(ReviewItem(sid, step.symbol, cik, f"{LINE_REFUSED}:{refused}",
                                             f"{what}: not followed ({refused})", last_seen=step.old_last))
                continue
            counts[decision.kind] += 1
            if decision.kind == ATTACH:
                if step.kind == SWITCH:
                    out.sec_cusips.setdefault(sid, []).append(step.new_cusip)
                tickers.setdefault(sid, set()).add(step.symbol)
                moved.add(sid)
                result = "the same security"
            elif decision.kind == FOLD:
                _fold(out, sid, decision.composite, decision.candidate, step, tickers)
                moved.add(decision.composite)
                result = f"folded into {decision.composite}"
            else:
                out.successors[sid] = LineSuccessor(sid, decision.composite, decision.candidate, step, evidence)
                result = f"continued by {decision.composite}"
            out.review.append(ReviewItem(sid, step.symbol, cik, LINE_FOLLOWED, f"{what} ({evidence}): {result}",
                                         last_seen=step.old_last))
        if any(sid in out.renames for sid in out.securities):
            out.securities = build_securities(out.resolutions, era_by_key, answers.issuers)
        for sid, s in out.securities.items():
            s.line_tickers = frozenset(tickers.get(sid, set()) - {e.ticker for e in s.eras})
        todo = sorted(sid for sid in moved if sid in out.securities)
        if not todo:
            break
    for sid, s in sorted(out.securities.items()):       # a failed read that left no step: its answer still rested on it
        if s.issuer_cik in reads.degraded and sid not in flagged:
            out.review.append(degraded_item(sid, min(own(sid), default=""), s.issuer_cik, "the line follow",
                                            "; run again once SEC answers"))
    ctx.log(f"line follow: {dict(sorted(counts.items()))}; {len(out.renames)} placeholders folded, "
            f"{len(out.successors)} line successors")
    ctx.meter.done("line follow", mark)
    return out


def _cusip_switches(s: Security, ftd: FtdIndex, cusips: Sequence[str]) -> tuple[str, ...]:
    """The first sighting of each of the security's CUSIPs after its first (`history.cusip_sightings`): the days
    its own line switched CUSIP."""
    first: dict[str, str] = {}
    for x in cusip_sightings(s, ftd, cusips):
        first.setdefault(x.value, x.day)
    return tuple(sorted(first.values())[1:])


def _security_ref(s: Security, ftd: FtdIndex, cusips: Sequence[str]) -> SecurityRef:
    """The finder's view of a security (`form25.SecurityRef`): its class, kind and name, and for a class with no
    letter the one its own CUSIPs' fails descriptions name (`form25.letter_hint`, R2: SunPower's class A placeholder,
    "SUNPOWER CORP CL A")."""
    hint = None if class_letter(s.share_class) else letter_hint(d for c in cusips for d in ftd.descriptions(c))
    return SecurityRef(s.sec_id, s.share_class, s.kind, s.name, hint)


def _rows_near(rows: Sequence[FtdRow], day: str) -> bool:
    """Whether a trading fails row of the security's own CUSIPs (`rows`) is dated in the LATE_ROW_DAYS up to the
    ISO day `day`."""
    lo = (date.fromisoformat(day) - timedelta(days=LATE_ROW_DAYS)).isoformat()
    return any(lo <= r.date <= day and is_trading_symbol(r.symbol) for r in rows)


def _ticker_taken(ftd: FtdIndex, ticker: str, own: Collection[str], lo: str, hi: str) -> str | None:
    """The first day another CUSIP traded under `ticker` within the ISO window [lo, hi] once the security's own
    CUSIPs (`own`) stopped: the trading day before that CUSIP's first priced fails row there (a row carries the
    close of the trading day before it), when that row comes on or after the own CUSIPs' last row under the ticker
    -- else None. None too when the own CUSIPs have no row under the ticker in the window (the tenure there is not
    known: Peabody's, Chesapeake's own new CUSIPs). A $0.01 placeholder row is no trade (APA Corp's first row,
    2021-03-02, beside Apache's own row carrying its March 1 close). 5d rule 3: CCEP's shares under CCE from
    2016-05-31, Johnson Controls plc's under JCI from 2016-09-06."""
    rows = [r for r in ftd.by_symbol(ticker, lo, hi) if r.price is not None and r.price > PLACEHOLDER_PRICE]
    mine = [r.date for r in rows if r.cusip in own]
    if not mine:
        return None
    other = next((r.date for r in rows if r.cusip not in own and r.date > mine[0] and r.date >= mine[-1]), None)
    return previous_trading_day(date.fromisoformat(other)).isoformat() if other else None


def _last_row_trade_day(rows: Sequence[FtdRow]) -> str | None:
    """The last day the fails rows show the security trading: the trading day before the row that opens the
    last one-price run (`ftd.settled_last`, fails still settling after the last trade) of the CUSIP it held
    last, ISO (AVGO 2018: the run opens 04-05, so 04-04); None without rows."""
    if not rows:
        return None
    last = max(r.date for r in rows)
    own = sorted((r for r in rows if r.cusip == next(x.cusip for x in rows if x.date == last)),
                 key=lambda r: r.date)
    return previous_trading_day(date.fromisoformat(settled_last(own).date)).isoformat()


PLACEHOLDER_PRICE = 0.01        # a fails row priced at or below this carries no close (a new CUSIP's placeholder)


def _context_builder(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
                     answers: _IssuerAnswers, ftd: FtdIndex, sec_cusips: dict[str, list[str]],
                     other_ciks: Mapping[str, int] = {}) -> Callable[[Security, bool | None], SecurityContext]:
    """The finder's `SecurityContext` for a security of the run, given whether it
    is listed today."""
    siblings: dict[int, list[SecurityRef]] = defaultdict(list)
    for s in securities.values():
        if s.issuer_cik is not None:
            siblings[s.issuer_cik].append(_security_ref(s, ftd, sec_cusips.get(s.sec_id, [])))

    def security_context(s: Security, listed_now: bool | None) -> SecurityContext:
        sig = sightings[s.sec_id]
        sibs = siblings.get(s.issuer_cik) or [_security_ref(s, ftd, sec_cusips.get(s.sec_id, []))]
        rows = ftd.trading_rows(sec_cusips.get(s.sec_id, []))
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
            ticker_on=ticker_on(sig),
            last_seen=own_last_seen(s, sig),
            seen_after=lambda day, sig=sig: any(x.day > day for x in sig),
            listed_today=listed_now,
            expected_name=s.eras[-1].name if s.eras else None,
            sibling_spans=spans,
            resolution_source=_resolution_source(s, answers.issuers, answers.resolutions),
            ftd_seen_after=lambda day, sig=sig, own=s.own_tickers(): any(
                x.day > day for x in sig if x.source == "ftd" and x.value in own),
            tickers_between=lambda lo, hi, sig=sig: list(dict.fromkeys(x.value for x in sig if lo <= x.day <= hi)),
            cusip_switches=_cusip_switches(s, ftd, sec_cusips.get(s.sec_id, [])),
            trades_after=lambda day, rows=rows: trades_after(rows, day),
            cusip_rows_near=lambda day, rows=rows: _rows_near(rows, day),
            rows_trade_until=lambda rows=rows: _last_row_trade_day(rows),
            other_cik=other_ciks.get(s.sec_id),
            ticker_taken=lambda ticker, lo, hi, own=frozenset(sec_cusips.get(s.sec_id, [])): _ticker_taken(
                ftd, ticker, own, lo, hi),
            has_cusips=bool(sec_cusips.get(s.sec_id)),
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
    finder: DelistingFinder | None = None      # the sequential finder, which stage 9d reuses


def _find_delistings(ctx: _RunContext, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
                     ftd: FtdIndex, answers: _IssuerAnswers, moved_on: Collection[str] = (),
                     other_ciks: Mapping[str, int] = {}) -> _DelistingSearch:
    """5. Every delisting of every security (`DelistingFinder`), in sec_id order.
    A security whose search fails becomes an `error` review item, not an aborted
    run; only a fatal exception (`fatal.FATAL`) stops it. A FIGI line another
    composite continues (`moved_on`: stage 4b's line successors) is not listed
    today: its line went on under that composite. `other_ciks` (stage 4c, R5): the
    other CIK in force over a security's whole span, whose Form 25s are read too."""
    clients, log = ctx.clients, ctx.log
    finder = DelistingFinder(clients.edgar, clients.classifier, midas=clients.midas, halts=clients.halts)
    delistings: list[Delisting] = []
    listed: dict[str, bool | None] = {}
    review: list[ReviewItem] = []
    sightings = {sid: ticker_sightings(s, ftd, sec_cusips[sid]) for sid, s in securities.items()}
    security_context = _context_builder(securities, sightings, answers, ftd, sec_cusips, other_ciks)

    ordered = sorted(securities.values(), key=lambda s: s.sec_id)
    # One batched OpenFIGI ask for every security's listing; a failed batch leaves
    # each security to ask alone inside its own try below.
    listing = listing_answers(clients.figi, [s.sec_id for s in ordered])
    mark = ctx.meter.start()
    # A placeholder has no FIGI to ask; EDGAR answers for its ticker, which a
    # later line of the issuer may hold today. Its own CUSIP failing only under
    # a deleted symbol at the end says it is not the line listed today, and so
    # does a later FIGI line of its issuer and class under its ticker
    # (`superseded_placeholders`).
    retired = frozenset(s.sec_id for s in ordered
                        if is_placeholder(s.sec_id) and ftd.symbol_deleted(sec_cusips[s.sec_id])) \
        | superseded_placeholders(securities) | frozenset(moved_on)
    if ctx.sec_workers > 1:
        _warm_delisting_search(clients, ordered, listing, security_context, ctx.sec_workers, retired)
    for i, s in enumerate(ordered, 1):
        last_seen = own_last_seen(s, sightings[s.sec_id])
        ticker = s.eras[-1].ticker if s.eras else ""
        watch = DegradedWatch()
        try:
            # listed_today and the context live inside the try too: a FIGI/EDGAR
            # error there must become a reviewable row for this one security,
            # not abort the whole overnight run.
            listed[s.sec_id] = False if s.sec_id in retired else listed_today(
                clients.figi, s.sec_id, edgar=clients.edgar, cik=s.issuer_cik,
                tickers=sorted(s.own_tickers()), answer=listing.get(s.sec_id))
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
        watch.report(review, degraded_item(s.sec_id, ticker, s.issuer_cik, "the delisting search",
                                            "; run again once SEC answers", last_seen=last_seen), found)
        report_halt_feed_failures(review, found)
        if i % 50 == 0:
            log(f"[{i}/{len(securities)}] securities searched; {len(delistings)} delistings so far")
    ctx.meter.done("delisting search", mark)
    return _DelistingSearch(delistings, listed, sightings, review, finder)


def _dead_before_sighting(ctx: _RunContext, securities: dict[str, Security], delistings: list[Delisting],
                          sec_cusips: dict[str, list[str]], ftd: FtdIndex, sightings: dict[str, list[Sighting]],
                          issuers: dict[str, Issuer]) -> list[str]:
    """5b. A security whose last real ending (its successor not itself) came before
    its first observation, and none of whose CUSIPs has a trading fails row, died
    before a stale snapshot listed it: the run's fails window starts after it.
    Eligibility is decided first, on the rows loaded when the stage starts, so one
    security's load cannot change another's. Its rows under its tickers from
    BACKFILL_DAYS before the end are then loaded; the CUSIPs whose rows before the
    end name its issuer (`history.backfill_cusips`) and that no other security holds
    become its CUSIPs, and its sightings are rebuilt, so the close, history and
    contract stages see them. Returns the sec_ids that took CUSIPs."""
    mark = ctx.meter.start()
    ends: dict[str, str] = {}
    for e in delistings:
        if e.record.successor_sec_id == e.sec_id:
            continue
        day = e.last_trade.day.isoformat() if e.last_trade.day else e.delist_date
        ends[e.sec_id] = max(ends.get(e.sec_id, day), day)
    eligible: list[tuple[str, str]] = []
    for sid, end in sorted(ends.items()):
        s = securities.get(sid)
        seen = [o.as_of for era in (s.eras if s else ()) for o in era.observations]
        if s is None or not seen or end >= min(seen) or ftd.trading_rows(sec_cusips.get(sid, [])):
            continue
        eligible.append((sid, end))
    fixed: list[str] = []
    for sid, end in eligible:
        s = securities[sid]
        end_day = date.fromisoformat(end)
        lo, hi = end_day - timedelta(days=BACKFILL_DAYS), end_day + timedelta(days=10)
        tickers = sorted(s.own_tickers())
        ftd.extend(ctx.clients.ftd_client, lo, hi, symbols=tickers)
        names = [n for era in s.eras for n in (era.name, *(issuers[era.key].names if era.key in issuers else ())) if n]
        held = {c for other, cs in sec_cusips.items() if other != sid for c in cs}
        found = [c for c in backfill_cusips(tickers, end, ftd, names) if c not in held]
        if not found:
            continue
        ftd.extend(ctx.clients.ftd_client, lo, hi, cusips=found)
        sec_cusips[sid] = list(dict.fromkeys([*sec_cusips.get(sid, []), *found]))
        sightings[sid] = ticker_sightings(s, ftd, sec_cusips[sid])
        fixed.append(sid)
    ctx.log(f"dead before first sighting: {len(fixed)} securities took CUSIPs from fails rows before their end")
    ctx.meter.done("dead before first sighting", mark)
    return fixed


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


def _apply_price_answers(overrides: Overrides, delistings: list[Delisting]) -> Overrides:
    """6b. The caller's price answers (--price-answers) as this run's overrides: a
    last_close answer is the last-trade close of the delisting of its sec_id
    whose last trade day it names, a received_close answer that delisting's
    acquirer price, an otc_print answer that delisting's first off-exchange
    print. A last close --last-trade-closes also gives stops the run
    (OverrideFileError). An answer whose delisting this run does not have is
    refused at stage 10g with every other answer to no request.

    Always called on the caller's own overrides, never on a result of this
    function: the handoff stage (9b) adds delistings and `_run` applies the
    answers again over all of them, and a second application on an
    already-applied copy would see its own closes as given twice."""
    if not overrides.price_answers:
        return overrides
    by_day = {(e.sec_id, e.last_trade.day.isoformat()): e for e in delistings if e.last_trade.day is not None}
    closes, prices, otc, twice = dict(overrides.last_trade_closes), {}, {}, []
    for k, price in overrides.price_answers.items():
        e = by_day.get((k.sec_id, k.last_trade_date))
        if e is None:
            continue
        if k.kind == LAST_CLOSE:
            if for_delisting(overrides.last_trade_closes, e.key) is not None:
                twice.append(f"{k.sec_id} {k.last_trade_date}")
            closes[e.key] = price
        elif k.kind == RECEIVED_CLOSE:
            prices[e.key] = (k.lookup_ticker, price)
        elif k.kind == OTC_PRINT:
            otc[e.key] = price
    if twice:
        raise OverrideFileError("--price-answers and --last-trade-closes both give the last close of: "
                                + "; ".join(twice))
    return replace(overrides, last_trade_closes=closes, acquirer_prices=prices, otc_prints=otc)


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
    held = {c for cs in sec_cusips.values() for c in cs}
    for e in delistings:
        key = e.key
        # by symbol, a row of a CUSIP another security holds is that security's close (WEN 2008, 5d rule 3)
        skip = held - set(sec_cusips.get(e.sec_id, []))
        if e.form25 is not None:
            skip |= plan_new_cusips(e.form25.notice_text)     # a plan exchange's new line is no price of the old one (WOLF)
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
        got = ftd.close_of(e.last_trade.day, cusip=cusip, symbol=e.ticker, skip=skip)
        if got is None:
            # Fails stop once trading stops, so no row may follow the last trade
            # day: look back a few rows (spec §16). The flag carries the close's
            # age in trading days (ftd_close_prior:<n>); the evidence the row date.
            back = ftd.close_known_on(e.last_trade.day, cusip=cusip, symbol=e.ticker, skip=skip)
            if back is None:
                e.add_flag("no_last_close")
            else:
                closes[key] = back[0]
                e.record.evidence["ftd_close_row_date"] = back[1]
                e.add_flag(f"ftd_close_prior:{close_age(back[1], e.last_trade.day)}")
            continue
        price, _, lagged = got
        closes[key] = price
        if lagged:
            e.add_flag("ftd_close_lagged")
    return closes


@dataclass
class _Payouts:
    """Stage 8's answer: the regex payout reads and the LLM terms (by delisting),
    what the payout gate kept, each merger's acquirer security, the acquirers
    the run adds as securities of their own (`added`), and the review items."""
    raw: dict[DelistingKey, Any]
    llm_terms: dict[DelistingKey, Any]
    gated: GatedPayouts
    acquirer_ids: dict[DelistingKey, str]
    added: dict[str, AddedSecurity]
    review: list[ReviewItem]
    price_tickers: dict[DelistingKey, str] = field(default_factory=dict)   # each stock leg's symbol on its price date


def _extract_payouts(ctx: _RunContext, mergers: list[Delisting], closes: dict[DelistingKey, float]
                     ) -> tuple[dict[DelistingKey, Any], dict[DelistingKey, Any], list[ReviewItem]]:
    """The regex payout read and the LLM merger terms of each merger, and the
    review items: a failed extraction's `error`, and a read that rested on a
    degraded answer (which also flags the merger's own row)."""
    clients, raw, llm_terms = ctx.clients, {}, {}
    review: list[ReviewItem] = []
    if ctx.sec_workers > 1 and clients.payout_extractor is not None:
        # The regex payout reader's EDGAR reads, warmed. The LLM extractor is not
        # warmed: its calls are paid, and it has its own cache.
        extractor = clients.payout_extractor
        warm(mergers, lambda e: extractor.extract(e.record, last_close=closes.get(e.key)),
             workers=ctx.sec_workers, name="payouts")
    for e in mergers:
        key = e.key
        watch = DegradedWatch()
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
    return raw, llm_terms, review


@dataclass(frozen=True)
class _AcquirerLine:
    """Stage 8's acquirer line of one merger's stock leg (`acquirer_line`, sub-plan 5e): the security of the run
    that held the terms' ticker on the last trade day (`holder`), the issuer's line the leg is priced on (`line`),
    its price (`(price, row_date, lagged)`) and its symbol on the price date."""
    holder: str | None
    line: str | None
    price: tuple[float, str, bool] | None
    ticker: str
    last: date
    price_day: date


def _leg_evidence(e: Delisting, llm_terms: Mapping[DelistingKey, Any], overrides: Overrides) -> tuple[str, str, str] | None:
    """(ticker, acquirer name, quote) of a merger's stock leg: its --merger-terms row's, else the LLM's; None when
    it has none. An LLM ticker of "null" is none."""
    given = for_delisting(overrides.merger_terms, e.key)
    if given is not None:
        return (normalize_ticker(given.get("acquirer_ticker") or ""), "", "") if given.get("stock_ratio") else None
    t = llm_terms.get(e.key)
    if t is None or not t.stock_ratio:
        return None
    ticker = normalize_ticker(t.acquirer_ticker or "")
    return ("" if ticker.lower() in ("null", "none", "n-a") else ticker), t.acquirer_name or "", t.quote or ""


def _acquirer_lines(ctx: _RunContext, mergers: list[Delisting], llm_terms: Mapping[DelistingKey, Any],
                    overrides: Overrides, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
                    ftd: FtdIndex, sightings: Mapping[str, Sequence[Sighting]], ftd_lo: date | None
                    ) -> tuple[dict[DelistingKey, _AcquirerLine], list[ReviewItem]]:
    """8a. The acquirer line of every merger's stock leg, before the payout gate and whether or not its terms will
    pass it (sub-plan 5e rules 1-4): the issuer (`acquirer_line`: the holder of the terms' ticker on the last trade
    day, else the resolver's issuer of it whose EDGAR names agree with the acquirer name, else the one issuer of the
    run that carried that name), its line on the price date, that line's symbol then and its price. A merger
    before the fails rows the run loaded (`ftd_lo`) has its candidate lines' rows read for it (a private index:
    the run's own is not extended, so no later stage sees rows it did not load). A lookup that rested on a
    degraded answer is a review item."""
    out: dict[DelistingKey, _AcquirerLine] = {}
    review: list[ReviewItem] = []
    legs = {e.key: (e, leg) for e in mergers if e.last_trade.day is not None
            and (leg := _leg_evidence(e, llm_terms, overrides)) is not None}
    if not legs:
        return out, review
    index = acquirer_line.LineIndex(securities, sightings, sec_cusips, ftd)
    edgar, resolver = ctx.clients.edgar, ctx.clients.resolver
    subs_cache: dict[int, Any] = {}

    def subs(cik: int):
        if cik not in subs_cache:
            try:
                subs_cache[cik] = edgar.submissions(cik)
            except FATAL:
                raise
            except requests.RequestException:
                return None            # never remembered: a failed read is no answer
        return subs_cache[cik]

    ages = _IssuerAge(edgar)

    def first_filed(cik: int) -> date | None:
        since = ages.since(cik)
        return date.fromisoformat(since[:10]) if since else None

    issuers: dict[DelistingKey, tuple[str | None, int | None]] = {}
    for key, (e, (ticker, name, _)) in sorted(legs.items()):
        last = e.last_trade.day
        day = next_trading_day(last)
        watch = DegradedWatch()
        holder = index.holder(ticker, last, day, exclude=e.sec_id) if ticker else None
        cik = securities[holder].issuer_cik if holder else None
        if cik is not None and not acquirer_line.issuer_fits(subs, first_filed, int(cik), name, last):
            holder, cik = None, None
        try:
            if cik is None and ticker and resolver is not None:
                cik = acquirer_line.issuer_by_ticker(resolver, subs, ticker, name, last, target_cik=e.cik)
            elif cik is None and not ticker:
                cik = acquirer_line.issuer_by_name(index.issuers(), subs, name, last, day, target_cik=e.cik)
        except FATAL:
            raise
        except requests.RequestException:
            cik = None
        watch.report_delisting(review, e, "the acquirer issuer lookup", own_row=False)
        issuers[key] = (holder, int(cik) if cik else None)

    view = index
    early = [legs[k][0] for k, (_, c) in issuers.items() if c and ftd_lo and legs[k][0].last_trade.day < ftd_lo
             + timedelta(days=acquirer_line.EARLY_DAYS)]
    if early:
        # the candidate lines' rows around these mergers, read into an index of their own
        cusips = {c for e in early for sid in index.lines(issuers[e.key][1], exclude=e.sec_id)
                  for c in sec_cusips.get(sid, [])}
        lo = min(e.last_trade.day for e in early) - timedelta(days=acquirer_line.EARLY_DAYS)
        hi = max(e.last_trade.day for e in early) + timedelta(days=acquirer_line.EARLY_DAYS)
        own = FtdIndex.load(ctx.clients.ftd_client, lo, hi, cusips=cusips) if cusips else FtdIndex()
        for r in (r for c in cusips for r in ftd.by_cusip(c)):
            own.add(r)
        view = acquirer_line.LineIndex(securities, sightings, sec_cusips, own)

    for key, (holder, cik) in sorted(issuers.items()):
        e, (_, _, quote) = legs[key]
        last = e.last_trade.day
        day = next_trading_day(last)
        idx = view if ftd_lo and last < ftd_lo + timedelta(days=acquirer_line.EARLY_DAYS) else index
        own = securities.get(e.sec_id)
        letter = acquirer_line.named_class(quote, class_letter(own.share_class) if own else None)
        line = acquirer_line.choose_line(idx, cik, holder=holder, letter=letter, last=last, price_day=day,
                                         exclude=e.sec_id) if cik else None
        if holder is None and line is None:
            continue
        shown = line or holder
        out[key] = _AcquirerLine(holder, line, idx.price(line, last, day) if line else None,
                                 idx.symbol_on(shown, day, last=last) or "", last, day)
    ctx.log(f"acquirer lines: {sum(1 for v in out.values() if v.line)} of {len(legs)} stock legs "
            f"({sum(1 for v in out.values() if v.price)} priced)")
    return out, review


def _gate(ctx: _RunContext, mergers: list[Delisting], trade_day: dict[DelistingKey, date | None],
          ftd: FtdIndex, raw: dict[DelistingKey, Any], llm_terms: dict[DelistingKey, Any],
          closes: dict[DelistingKey, float], overrides: Overrides, tol: float,
          lines: Mapping[DelistingKey, _AcquirerLine] = {}, line_first: Collection[DelistingKey] = (),
          answers: Mapping[DelistingKey, tuple[str, float]] = {}, flag: bool = True) -> GatedPayouts:
    """Every merger payout through the last-close check (`payout_gate`), the
    acquirer's price read from its FTD rows around that merger's own last trade
    day (`trade_day`), else from its acquirer line (`lines`, stage 8a; first for
    `line_first`, whose terms' ticker is another line's). `answers` are the
    caller's received closes, each as `(path, price)`: the price of the path
    (BY_TICKER or BY_LINE) the answered request belongs to, so an answer settles
    the gate only through the request it answers (`_merger_payouts` works the path
    out from a first pass that reads no answer). A merger whose terms took a
    lagged acquirer close is flagged (`flag`: not in that first pass)."""
    acq_symbols = {normalize_ticker(t.acquirer_ticker) for t in llm_terms.values() if t.acquirer_ticker}
    acq_symbols |= {normalize_ticker(v["acquirer_ticker"]) for v in overrides.merger_terms.values()
                    if v.get("acquirer_ticker")}
    if acq_symbols:
        days = [d for d in trade_day.values() if d]
        if days:
            ftd.extend(ctx.clients.ftd_client, min(days) - timedelta(days=10), max(days) + timedelta(days=10),
                       symbols=acq_symbols)

    lagged_acquirer: set[DelistingKey] = set()

    def answered(path: str, key: DelistingKey) -> float | None:
        """The caller's received close for this merger, when its request is the one of this price path."""
        got = answers.get(key)
        return got[1] if got is not None and got[0] == path else None

    def line_price(key: DelistingKey) -> tuple[str, float] | None:
        line = lines.get(key)
        if line is None or not line.ticker:
            return None
        given = answered(BY_LINE, key)
        if given is not None:
            return line.ticker, given
        return (line.ticker, line.price[0]) if line.price else None

    def acquirer_price(ticker: str, key: DelistingKey) -> float | None:
        given = answered(BY_TICKER, key)
        if given is not None:
            return given
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
        acquirer_price, tol, line_price=line_price, line_first=line_first,
    )
    for e in mergers:
        # A lagged FTD close (no row on the next trading day) may carry an OTC or
        # stale price: flag the delisting when that price made it into its terms.
        terms = for_delisting(gated.merged_terms, e.key)
        line = lines.get(e.key)
        if gated.priced_by.get(e.key) == BY_LINE:
            lagged = bool(line and line.price and line.price[2] and answered(BY_LINE, e.key) is None)
        else:
            lagged = e.key in lagged_acquirer
        if flag and lagged and terms and terms.get("acquirer_price") is not None:
            e.add_flag("acquirer_close_lagged")
    return gated


class _TickerSecurity:
    """The security of the fails rows under a stock leg's terms' ticker (`acquirers.find_acquirer`), asked once
    for each (ticker, last trade day, target)."""

    def __init__(self, ctx: _RunContext, ftd: FtdIndex, sec_cusips: dict[str, list[str]]) -> None:
        self.ctx, self.ftd, self.sec_cusips = ctx, ftd, sec_cusips
        self._memo: dict[tuple, Any] = {}

    def __call__(self, e: Delisting, ticker: str, day: date | None):
        if not ticker or day is None:
            return None
        k = (ticker, day, e.sec_id)
        if k not in self._memo:
            self._memo[k] = find_acquirer(self.ctx.clients.figi, self.ftd, ticker, day,
                                          set(self.sec_cusips.get(e.sec_id, [])))
        return self._memo[k]


def _stock_ticker(e: Delisting, llm_terms: Mapping[DelistingKey, Any], overrides: Overrides) -> str:
    """The terms' acquirer ticker of a stock leg, as the gate's merged terms carry it: its --merger-terms row's, else
    the LLM's (a leg the line alone priced carries the line's, which no ticker lookup reads)."""
    given = for_delisting(overrides.merger_terms, e.key)
    if given is not None:
        return normalize_ticker(given.get("acquirer_ticker") or "")
    t = llm_terms.get(e.key)
    return normalize_ticker(t.acquirer_ticker or "") if t is not None and t.stock_ratio else ""


def _line_wins(mergers: list[Delisting], lines: Mapping[DelistingKey, _AcquirerLine], llm_terms: Mapping[DelistingKey, Any],
               overrides: Overrides, securities: dict[str, Security], trade_day: dict[DelistingKey, date | None],
               found: _TickerSecurity) -> set[DelistingKey]:
    """The stock legs whose terms' ticker belongs to another line of the acquirer's issuer than the one stage 8a
    chose (sub-plan 5e fix): the ticker's rows are the pre-closing line's (Charter's for New Charter, TWC 2016), the
    class's other line (CBS class B for Viacom class A, VIA 2019) or a placeholder's (Lions Gate's for its class B on
    a new CUSIP, STRZA 2016), and the acquirer's line of that issuer is published and priced instead. Not for a
    ticker whose security is another issuer's (IPHI's new Marvell, an acquirer the run adds) or the line itself, nor
    for a --merger-terms row, whose ticker is the caller's."""
    out: set[DelistingKey] = set()
    for e in mergers:
        line = lines.get(e.key)
        if (line is None or not line.line or not line.holder or line.line == line.holder
                or for_delisting(overrides.merger_terms, e.key) is not None):
            continue                       # no other line of the issuer holds the ticker: nothing to settle
        got = found(e, _stock_ticker(e, llm_terms, overrides), trade_day.get(e.key))
        if got is None:
            out.add(e.key)
        elif got[0].composite not in (line.line, e.sec_id):
            other = securities.get(got[0].composite)
            mine = securities.get(line.line)
            if other is not None and mine is not None and other.issuer_cik and other.issuer_cik == mine.issuer_cik:
                out.add(e.key)
    return out


def _add_acquirers(ctx: _RunContext, mergers: list[Delisting], trade_day: dict[DelistingKey, date | None],
                   gated: GatedPayouts, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
                   ftd: FtdIndex, lines: Mapping[DelistingKey, _AcquirerLine] = {},
                   line_first: Collection[DelistingKey] = (), found: _TickerSecurity | None = None
                   ) -> tuple[dict[DelistingKey, str], dict[str, AddedSecurity], list[ReviewItem]]:
    """Each merger's acquirer security: for terms the payout gate settled on the terms' own ticker, the security
    of the fails rows under it (`acquirers.find_acquirer`), else that ticker's holder; for terms the acquirer line's
    price settled, that line, and for a `line_first` leg (`_line_wins`: the ticker's rows are another line of the
    issuer's) the line whichever price settled it; for every other stock leg, failed or never gated (sub-plan 5e),
    its acquirer line, else the ticker's holder (`lines`, stage 8a). The acquirers the run adds as securities of
    their own (`AddedAcquirer`, their issuer CIK from `acquirers.acquirer_cik`) come from the first kind only, as
    before; and a review item for each acquirer-CIK lookup that rested on a degraded answer."""
    acquirer_ids: dict[DelistingKey, str] = {}
    added: dict[str, AddedSecurity] = {}
    review: list[ReviewItem] = []
    found = found or _TickerSecurity(ctx, ftd, sec_cusips)
    for e in mergers:
        key = e.key
        terms = for_delisting(gated.merged_terms, e.key)
        line = lines.get(key)
        by_line = gated.priced_by.get(key) == BY_LINE or key in line_first
        if terms and not by_line:
            acq = normalize_ticker(terms.get("acquirer_ticker") or "")
            day = trade_day.get(key)
            got = found(e, acq, day)
            if got is not None and got[0].composite != e.sec_id:
                cand, rows = got
                acquirer_ids[key] = cand.composite
                if cand.composite not in securities:
                    if cand.composite not in added:
                        watch = DegradedWatch()
                        acq_cik = acquirer_cik(ctx.clients.resolver, ctx.clients.edgar, acq, day, e)
                        watch.report_delisting(review, e, f"the acquirer {acq} CIK lookup", own_row=False)
                        added[cand.composite] = AddedAcquirer(
                            Security(cand.composite, acq_cik, share_class_from_name(cand.name), cand.name,
                                     cand.security_type, False, "cusip"), acq, day)
                    # Union every merger's FTD window for this acquirer: several mergers
                    # can name the same acquirer, and its ticker_history row must span
                    # all of them, not just the first one processed.
                    added[cand.composite].rows += rows
                continue
            if got is not None:
                continue
        if line is None:
            continue
        sid = line.line if by_line else (line.holder or line.line) if terms else (line.line or line.holder)
        if sid and sid != e.sec_id:
            acquirer_ids[key] = sid
    return acquirer_ids, added, review


def _price_tickers(acquirer_ids: Mapping[DelistingKey, str], lines: Mapping[DelistingKey, _AcquirerLine],
                   index: acquirer_line.LineIndex | None) -> dict[DelistingKey, str]:
    """Each stock leg's price ticker (sub-plan 5e rule 4): its acquirer security's symbol on the price date, from
    that security's own fails rows; none for an acquirer the run added (the terms' ticker stands)."""
    out: dict[DelistingKey, str] = {}
    for key, sid in acquirer_ids.items():
        line = lines.get(key)
        if line is None or index is None or sid not in index.securities:
            continue
        symbol = line.ticker if sid == (line.line or line.holder) else index.symbol_on(sid, line.price_day,
                                                                                        last=line.last)
        if symbol:
            out[key] = symbol
    return out


def _answered_paths(mergers: list[Delisting], overrides: Overrides, llm_terms: Mapping[DelistingKey, Any],
                    lines: Mapping[DelistingKey, _AcquirerLine], first: GatedPayouts,
                    price_tickers: Mapping[DelistingKey, str]) -> dict[DelistingKey, tuple[str, float]]:
    """The caller's received closes (`overrides.acquirer_prices`: the answered request's lookup_ticker and the
    price) that answer a request this run makes, each with the price path its request belongs to: the path the first
    pass (no answers) settled the gate on, else the acquirer line's when the request is for the line's symbol and
    not the terms' ticker, else the ticker's. The request is for the leg's price ticker, else the terms' ticker
    (`price_requests.stock_legs`); an answer to any other ticker answers no request here."""
    out: dict[DelistingKey, tuple[str, float]] = {}
    for e in mergers:
        got = overrides.acquirer_prices.get(e.key)
        t = llm_terms.get(e.key)
        asked = price_tickers.get(e.key) or normalize_ticker(t.acquirer_ticker or "" if t is not None else "")
        if got is None or got[0] != asked:
            continue
        line = lines.get(e.key)
        path = first.priced_by.get(e.key) or (
            BY_LINE if line is not None and line.ticker == asked and asked != _stock_ticker(e, llm_terms, overrides)
            else BY_TICKER)
        out[e.key] = (path, got[1])
    return out


def _merger_payouts(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                    sec_cusips: dict[str, list[str]], ftd: FtdIndex, closes: dict[DelistingKey, float],
                    overrides: Overrides, tol: float, sightings: Mapping[str, Sequence[Sighting]] | None = None,
                    ftd_lo: date | None = None) -> _Payouts:
    """8. Merger payouts, LLM terms, acquirer lines (8a), acquirer prices and acquirer securities."""
    mergers = [e for e in delistings if e.record.bucket is CrspBucket.MERGER]
    mark = ctx.meter.start()
    raw, llm_terms, extraction_review = _extract_payouts(ctx, mergers, closes)
    trade_day = {e.key: e.last_trade.day for e in delistings}
    lines, line_review = (_acquirer_lines(ctx, mergers, llm_terms, overrides, securities, sec_cusips, ftd, sightings,
                                          ftd_lo) if sightings is not None else ({}, []))
    found = _TickerSecurity(ctx, ftd, sec_cusips)
    wins = _line_wins(mergers, lines, llm_terms, overrides, securities, trade_day, found)
    # the first pass reads none of the caller's received closes: the acquirer and the request's ticker depend on
    # what the run reads alone, so a second run with the requests answered keeps both (`--price-answers`)
    gated = _gate(ctx, mergers, trade_day, ftd, raw, llm_terms, closes, overrides, tol, lines, wins,
                  flag=not overrides.acquirer_prices)
    acquirer_ids, added, acquirer_review = _add_acquirers(ctx, mergers, trade_day, gated, securities, sec_cusips,
                                                          ftd, lines, wins, found)
    index = acquirer_line.LineIndex(securities, sightings, sec_cusips, ftd) if lines else None
    price_tickers = _price_tickers(acquirer_ids, lines, index)
    if overrides.acquirer_prices:
        answers = _answered_paths(mergers, overrides, llm_terms, lines, gated, price_tickers)
        gated = _gate(ctx, mergers, trade_day, ftd, raw, llm_terms, closes, overrides, tol, lines, wins, answers)
    _flush_memo(ctx.clients)                  # the acquirer lookups resolved tickers
    ctx.meter.done("payouts", mark)
    return _Payouts(raw, llm_terms, gated, acquirer_ids, added, extraction_review + line_review + acquirer_review,
                    price_tickers)


R1_CONTINUATION, R1_REBUCKETED = "r1_continuation", "r1_rebucketed"
BY_TERMS, BY_OWN_REGISTRATION = "terms", "own_registration"
# the payout flags a merger row carries that a continuation does not
_PAYOUT_FLAGS = frozenset({"terms_gate_failed", "payout_gate_failed", "llm_gate_failed", "merger_at_par",
                           "acquirer_close_lagged"})


def _starts(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
            added: Mapping[str, AddedSecurity]) -> dict[str, SecurityStart]:
    """How each security of the run shows up, for the successor searches (`successors.SecurityStart`): an observed
    one by its sightings, an added one by its span and ticker."""
    starts = {sid: SecurityStart(sig[0].day, securities[sid].issuer_cik, {x.value for x in sig}, sig[-1].day,
                                 securities[sid].share_class)
              for sid, sig in sightings.items() if sig and sid in securities}
    for sid, a in added.items():
        first, last = a.span()
        starts[sid] = SecurityStart(first, a.security.issuer_cik, {a.ticker}, last, a.security.share_class)
    return starts


class _IssuerAge:
    """Each issuer's first EDGAR filing and its EDGAR names, read once (the finder already read most of them)."""

    def __init__(self, edgar) -> None:
        self.edgar = edgar
        self._since: dict[int, str | None] = {}
        self._names: dict[int, tuple[str, ...]] = {}
        self.failures = 0           # reads that failed after the client's retries: the answer is "unknown"

    def since(self, cik: int) -> str | None:
        if cik not in self._since:
            try:
                dates = [f.filing_date for f in self.edgar.recent_filings(cik) if f.filing_date]
            except FATAL:
                raise
            except requests.RequestException:
                self.failures += 1
                return None
            self._since[cik] = min(dates) if dates else None
        return self._since[cik]

    def names(self, cik: int) -> tuple[str, ...]:
        if cik not in self._names:
            try:
                sub = self.edgar.submissions(cik)
            except FATAL:
                raise
            except requests.RequestException:
                self.failures += 1
                return ()
            self._names[cik] = edgar_names(sub) if isinstance(sub, dict) else ()
        return self._names[cik]


def _own_exchange(edgar, e: Delisting, sec: Security) -> tuple[exchange_terms.OwnExchange | None, list[str], date]:
    """What `e`'s security's own shares became (`exchange_terms.own_exchange`), the texts it was read in and the
    day it was read around (`successors.successor_anchor`; the 8-K the classifier anchored on is read too)."""
    day = successor_anchor(e)
    days = [day]
    filed = ((e.record.evidence or {}).get("anchor_8k") or {}).get("filing_date")
    if filed:
        days.append(date.fromisoformat(filed))
    texts = exchange_terms.read_texts(edgar, e.cik, edgar.recent_filings(e.cik), days, e.form25)
    letter, words = exchange_terms.class_of(sec.share_class, sec.name)
    names = exchange_terms.registrant_names(edgar.submissions(e.cik), min(days), sec.name)
    return exchange_terms.own_exchange(texts, names=names, class_letter=letter, class_words=words), texts, day


def _contract_terms(payouts: _Payouts, key: DelistingKey) -> tuple[float | None, float | None] | None:
    """The (cash, stock ratio) the contract publishes for a merger without a --merger-terms row
    (`payout_rule._merger`'s order): the terms the payout gate kept, else the LLM's as read, else the regex cash;
    None with none."""
    gated = payouts.gated
    terms = for_delisting(gated.merged_terms, key) or {}
    cash = gated.payouts.get(key)
    if terms or cash is not None:
        return terms.get("cash_per_share", cash), terms.get("stock_ratio")
    llm = payouts.llm_terms.get(key)
    if llm is not None and (llm.cash_per_share or llm.stock_ratio):
        return llm.cash_per_share, llm.stock_ratio
    pr = payouts.raw.get(key)
    return (pr.value, None) if pr is not None and pr.value is not None else None


@dataclass
class _R1:
    """Stage 8b's answer: the merger rows it rewrote as continuations (by delisting: the successor and how it was
    found), the successors it adds as securities of their own, and its review items."""
    links: dict[DelistingKey, tuple[str, str]] = field(default_factory=dict)
    added: dict[str, AddedSecurity] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)


def _r1_successor(ctx: _RunContext, e: Delisting, sec: Security, own: exchange_terms.OwnExchange, day: date,
                  starts: dict[str, SecurityStart], ages: _IssuerAge, securities: dict[str, Security],
                  added: Mapping[str, AddedSecurity], out: _R1,
                  pending: dict[str, AddedSecurity]) -> tuple[str, str] | None:
    """The successor of a merger row R1 rewrites: a security of the run (`successors.successor_by_terms`), else
    the new issuer whose 8-K12B names the registrant (`successors.successor_from_8k12b`, its filer at most
    NEW_ISSUER_DAYS old and named by the R1 statement's target, the stage-9 name tie), to be added as a security of
    its own (`AddedSuccessor`, seen from the day after `day`) in `pending`: the caller adds it once the reading is
    known not to be degraded."""
    link = successor_by_terms(e, own, day, starts, issuer_since=ages.since, issuer_names=ages.names)
    search = getattr(ctx.clients.edgar, "full_text_search", None)
    if link is not None or search is None:
        return link
    hit = successor_from_8k12b(search, ctx.clients.figi, name=successor_search_name(ctx.clients.edgar, e.cik, sec.name),
                               day=day, exclude_cik=e.cik, share_class=sec.share_class, edgar=ctx.clients.edgar,
                               own_tickers=sec.own_tickers() | {e.ticker})
    if hit is None:
        return None
    s_cik, cand, filed = hit
    since = ages.since(s_cik)
    if since is None or (day - date.fromisoformat(since[:10])).days > NEW_ISSUER_DAYS:
        return None
    if not successor_named(own, {cand.ticker}, ages.names(s_cik)):
        return None
    if cand.composite not in securities and cand.composite not in added:
        not_before = (day + timedelta(days=1)).isoformat()
        pending.setdefault(cand.composite, AddedSuccessor(
            Security(cand.composite, s_cik, share_class_from_name(cand.name), cand.name, cand.security_type, False,
                     "ticker"), cand.ticker, max(filed or not_before, not_before)))
    return cand.composite, BY_TERMS


def _r1_continuations(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                      sightings: dict[str, list[Sighting]], payouts: _Payouts, overrides: Overrides) -> _R1:
    """8b. A merger that ruling R1 makes a continuation (sub-plan 5c): its published terms are one share and no
    cash (a special dividend is no cash: operator ruling 2026-10-04), no --merger-terms row decides it, the
    registrant's own filings say the same of its own shares (`exchange_terms.own_exchange`, one reading: a
    multi-step deal's intermediate one-for-one, Jefferies 2013, has the LLM's 0.81 against it), and the holders'
    new shares are a new issuer's or the same issuer's (`_r1_successor`). The row becomes an exchange transfer
    (304) to that successor, flagged `r1_continuation`, its payout reads dropped (a continuation has no value),
    and an `r1_rebucketed` review item keeps its old bucket. An existing acquirer is never a continuation (LVNTA
    into GCI Liberty, Towers Watson into Willis, Waste Connections into Progressive Waste)."""
    edgar, out = ctx.clients.edgar, _R1()
    mark = ctx.meter.start()
    ages = _IssuerAge(edgar)
    starts = _starts(securities, sightings, payouts.added)
    gated = payouts.gated
    for e in delistings:
        if e.record.bucket is not CrspBucket.MERGER or e.sec_id not in securities \
                or for_delisting(overrides.merger_terms, e.key):
            continue
        terms = _contract_terms(payouts, e.key)
        if terms is None or terms[1] is None or abs(terms[1] - 1.0) > 1e-9:
            continue
        watch, failed = DegradedWatch(), ages.failures
        sec = securities[e.sec_id]
        own, _, day = _own_exchange(edgar, e, sec)
        cash = terms[0]
        link, pending = None, {}
        if own is not None and own.one_for_one and (
                not cash or any(abs(cash - d) < 0.005 for d in own.special_dividends)):
            link = _r1_successor(ctx, e, sec, own, day, starts, ages, securities, payouts.added, out, pending)
        if watch.tripped() or ages.failures > failed:
            watch_item = degraded_item(e.sec_id, e.ticker, e.cik, "the R1 reading", delist_date=e.delist_date)
            out.review.append(watch_item)
            flag_degraded(e)
            continue
        if link is None:
            continue
        out.added.update(pending)
        sid, how = link
        old = (e.record.bucket.value, e.record.crsp_code, e.record.reason)
        e.record.bucket, e.record.crsp_code = CrspBucket.EXCHANGE_TRANSFER, CONTINUATION_CODE
        e.record.confidence = "medium"
        e.record.reason = (f"Continuation (R1): each share became one {own.target[:80].strip(' ,')}, no cash; "
                           f"successor by {how.replace('_', ' ')}")
        e.record.evidence["flags"] = [f for f in e.flags if flag_name(f) not in _PAYOUT_FLAGS] + [R1_CONTINUATION]
        e.record.evidence["r1"] = {"sentence": own.sentence[:300], "was": f"{old[0]} {old[1]}"}
        e.record.evidence["successor_by"] = how
        for m in (payouts.raw, payouts.llm_terms, payouts.acquirer_ids, gated.payouts, gated.sources,
                  gated.confidences, gated.merged_terms, gated.flags):
            m.pop(e.key, None)
        e.set_successor(sid)
        out.links[e.key] = link
        out.review.append(ReviewItem(e.sec_id, e.ticker, e.cik, R1_REBUCKETED,
                                     f"was {old[0]} (CRSP {old[1]}: {old[2]}); R1 makes it a continuation into {sid}",
                                     delist_date=e.delist_date))
    ctx.log(f"R1 continuations: {len(out.links)} merger rows ({', '.join(sorted(k.sec_id for k in out.links))})")
    ctx.meter.done("R1 continuations", mark)
    return out


LINE_FOLLOW, LINE_CONTINUATION = "line_follow", "line_continuation"


@dataclass
class _Successors:
    """Stage 9's answer: each delisting's successor (`links`, by delisting: the
    successor's sec_id and how the run found it -- "line_follow" for stage 4b's
    line successor, "same_issuer" or "same_ticker" for a security of the run,
    None for an 8-K12B hit), the successors the run adds as securities of their
    own, the review items, the delistings whose own row a degraded search answer
    flags, and the `unknown` rows a line successor rewrites as continuations
    (`rebucketed`, by delisting: the new reason)."""
    links: dict[DelistingKey, tuple[str, str | None]] = field(default_factory=dict)
    added: dict[str, AddedSecurity] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)
    degraded: list[DelistingKey] = field(default_factory=list)
    rebucketed: dict[DelistingKey, str] = field(default_factory=dict)


def _line_successor_links(delistings: list[Delisting], securities: dict[str, Security],
                          acquirers: dict[str, AddedSecurity], line_successors: Mapping[str, LineSuccessor],
                          ftd: FtdIndex, found: _Successors) -> None:
    """A FIGI line another composite continues (stage 4b's `line_successors`, R2): each of its delistings that
    still needs a successor (`successor_unknown`) or a kind (`unknown`: GTES 2026's Form 25 at its redomicile),
    whose last trade (else Form 25 filing date, else delisting date) lies within [-SUCCESSOR_BEFORE_DAYS,
    +SUCCESSOR_AFTER_DAYS] days of the step's first row, takes that composite as its successor; an `unknown` row
    becomes the continuation. The composite is added as a security of its own (`AddedLineSuccessor`) when the run
    has none, and only for a delisting that takes it."""
    for e in delistings:
        ls = line_successors.get(e.sec_id)
        if ls is None or not (SUCCESSOR_UNKNOWN in e.flags or e.record.bucket is CrspBucket.UNKNOWN):
            continue
        day = e.last_trade.day or (date.fromisoformat(e.form25_sub.filing_date) if e.form25_sub is not None
                                   else date.fromisoformat(e.delist_date))
        lo = (day - timedelta(days=SUCCESSOR_BEFORE_DAYS)).isoformat()
        hi = (day + timedelta(days=SUCCESSOR_AFTER_DAYS)).isoformat()
        if not lo <= ls.step.first <= hi:
            continue
        found.links[e.key] = (ls.composite, LINE_FOLLOW)
        if e.record.bucket is CrspBucket.UNKNOWN:
            found.rebucketed[e.key] = (
                f"Continuation (line follow, {ls.evidence}): {e.ticker}'s new CUSIP {ls.step.new_cusip} traded from "
                f"{ls.step.first} as {ls.composite}, its own FIGI; holders' shares became {ls.composite}'s")
        x = ls.composite
        if x not in securities and x not in acquirers and x not in found.added:
            rows = [r for r in ftd.trading_rows([ls.step.new_cusip]) if r.symbol == ls.step.symbol]
            found.added[x] = AddedLineSuccessor(
                Security(x, securities[e.sec_id].issuer_cik, share_class_from_name(ls.candidate.name),
                         ls.candidate.name, ls.candidate.security_type, False, "cusip"),
                ls.step.symbol, ls.step.first, rows)


def _own_registration_link(ctx: _RunContext, e: Delisting, texts: list[str], day: date, securities: dict[str, Security],
                           sec_cusips: dict[str, list[str]], ftd: FtdIndex, taken: Collection[str],
                           found: _Successors) -> tuple[str, str] | None:
    """Sub-plan 5c, rule 4 under the same CIK: the registrant's own successor registration (8-K12B/8-K12G3 in its
    filing list, `handoffs.own_continuation_filing`) moved the holders, one for one, to a new CUSIP -- the one the
    texts name that is not the security's own (ONEOK 2026's notice: "ONEOK, Inc. (New, CUSIP: 30609A109)"), else
    the first fails row's under one of its tickers in [day, day + SUCCESSOR_AFTER_DAYS] (Clear Channel Outdoor
    2019's 18453H106). R2 on that CUSIP's one US composite: the security's own is the security going on (it is its
    own successor); another is its successor, added as a security of its own (`AddedLineSuccessor`) when the run
    has none. Several composites or an OpenFIGI error: no link."""
    if own_continuation_filing(ctx.clients.edgar.recent_filings(e.cik), day) is None:
        return None
    mine = set(sec_cusips.get(e.sec_id, []))
    named = sorted(text_cusips(texts) - mine)
    tickers = securities[e.sec_id].own_tickers() | {e.ticker}
    hi = (day + timedelta(days=SUCCESSOR_AFTER_DAYS)).isoformat()
    rows = sorted((r for t in tickers for r in ftd.by_symbol(t, day.isoformat(), hi)
                   if r.cusip not in mine and is_line_symbol(r.symbol)), key=lambda r: (r.date, r.cusip))
    cusip = named[0] if len(named) == 1 else (rows[0].cusip if rows and not named else None)
    if cusip is None:
        return None
    cands = composites(ctx.clients.figi.map([cusip_job(cusip)])[0])
    if cands is None or len(cands) != 1:
        return None
    x = cands[0]
    if x.composite == e.sec_id:
        return e.sec_id, BY_OWN_REGISTRATION
    new_rows = [r for r in ftd.trading_rows([cusip]) if r.symbol in tickers]
    data_end = ftd.last_date()
    if not new_rows and not (named and data_end is not None and data_end < day.isoformat()):
        return None      # (5h) a CUSIP the texts name, after the fails data's last day, has no row to show yet: OKE 2026
    if x.composite not in securities and x.composite not in taken and x.composite not in found.added:
        symbol, first = (new_rows[0].symbol, new_rows[0].date) if new_rows else \
            (e.ticker, next_trading_day(day).isoformat())
        found.added[x.composite] = AddedLineSuccessor(
            Security(x.composite, e.cik, share_class_from_name(x.name), x.name, x.security_type, False, "cusip"),
            symbol, first, new_rows)
    return x.composite, BY_OWN_REGISTRATION


def _terms_links(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                 starts: dict[str, SecurityStart], sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                 taken: Collection[str], found: _Successors) -> None:
    """Sub-plan 5c, rules 3 and 4: an exchange transfer still without a successor whose registrant's filings
    state each share of its class became one share, with no cash (R1, `exchange_terms.own_exchange` around
    `successors.successor_anchor`), takes the security of the run that statement names
    (`successors.successor_by_terms`: the same issuer's other class, CMCSK into CMCSA, HUB-B into HUBB, CWENA
    into CWEN; a new issuer's, BHI into BHGE, HHC into HHH), else the line its own successor registration moved
    the holders to (`_own_registration_link`: CCO 2019, OKE 2026). The link's `how` is "terms" or
    "own_registration"."""
    edgar = ctx.clients.edgar
    ages = _IssuerAge(edgar)
    for e in delistings:
        if e.key in found.links or SUCCESSOR_UNKNOWN not in e.flags or e.sec_id not in securities:
            continue
        watch, failed = DegradedWatch(), ages.failures
        own, texts, day = _own_exchange(edgar, e, securities[e.sec_id])
        link = None
        if own is not None and own.one_for_one:
            link = successor_by_terms(e, own, day, starts, issuer_since=ages.since, issuer_names=ages.names)
            if link is None:
                link = _own_registration_link(ctx, e, texts, day, securities, sec_cusips, ftd, taken, found)
        if watch.tripped() or ages.failures > failed:
            found.review.append(degraded_item(e.sec_id, e.ticker, e.cik, "the successor terms reading",
                                              delist_date=e.delist_date))
            found.degraded.append(e.key)
        if link is not None:
            found.links[e.key] = link


def _find_successors(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                     sightings: dict[str, list[Sighting]], acquirers: dict[str, AddedSecurity],
                     line_successors: Mapping[str, LineSuccessor] = {}, ftd: FtdIndex | None = None,
                     sec_cusips: dict[str, list[str]] | None = None) -> _Successors:
    """9. Successors after a FIGI change: first the line successor stage 4b found
    (`_line_successor_links`), then a security of this run (observed,
    or an acquirer the run adds) that starts right after the last trade under the
    same issuer or ticker (a holdco reorganization's new line, a rename's new
    FIGI), then the successor issuer's 8-K12B (search: EDGAR full-text search,
    wired in default_clients). Before the 8-K12B search, sub-plan 5c's links
    (`_terms_links`): the security or the line the registrant's own filings say
    the shares became, one for one. `_link_successors` records the answer on the
    delistings."""
    clients, found = ctx.clients, _Successors()
    successor_search = getattr(clients.edgar, "full_text_search", None)
    mark = ctx.meter.start()
    if line_successors:
        _line_successor_links(delistings, securities, acquirers, line_successors, ftd or FtdIndex(), found)
    linked = set(found.links)
    starts = _starts(securities, sightings, acquirers)
    for e in delistings:                       # a security of this run
        if e.key in linked:
            continue
        in_run = successor_in_run(e, starts) if SUCCESSOR_UNKNOWN in e.flags else None
        if in_run is not None:
            found.links[e.key] = in_run
    # what the registrant's filings say the shares became, one for one (sub-plan 5c, rules 3 and 4)
    _terms_links(ctx, delistings, securities, starts, sec_cusips or {}, ftd or FtdIndex(), set(acquirers), found)
    linked = set(found.links)
    if successor_search is not None:           # else the successor issuer's 8-K12B
        if ctx.sec_workers > 1:
            def warm_search(e: Delisting) -> None:
                if e.key in linked:
                    return
                args = successor_search_args(clients.edgar, e, starts, securities)
                if args is not None:
                    successor_search(*successor_query(*args))
            warm(delistings, warm_search, workers=ctx.sec_workers, name="successor search")
        for e in delistings:
            if e.key in linked:
                continue
            watch = DegradedWatch()
            args = successor_search_args(clients.edgar, e, starts, securities)
            if args is None:
                continue
            name, day = args
            predecessor = securities[e.sec_id]
            hit = successor_from_8k12b(successor_search, clients.figi, name=name, day=day,
                                       exclude_cik=e.cik, share_class=predecessor.share_class,
                                       edgar=clients.edgar,
                                       own_tickers=predecessor.own_tickers() | {e.ticker})
            if watch.tripped():
                found.review.append(degraded_item(e.sec_id, e.ticker, e.cik, "the successor search",
                                                   delist_date=e.delist_date))
                found.degraded.append(e.key)
            if hit is None:
                continue
            s_cik, cand, filing_date = hit
            found.links[e.key] = (cand.composite, None)
            if cand.composite not in securities and cand.composite not in acquirers \
                    and cand.composite not in found.added:
                # A same-ticker successor (a holding-company reorg) must not overlap
                # the predecessor's own ticker_history row, even when its 8-K12B was
                # filed before the predecessor's actual last trade: clamp valid_from
                # to no earlier than the day after that last trade (or delist_date
                # when the last trade day is unknown).
                not_before = ((e.last_trade.day or date.fromisoformat(e.delist_date)) + timedelta(days=1)).isoformat()
                fd = filing_date or day.isoformat()
                found.added[cand.composite] = AddedSuccessor(
                    Security(cand.composite, s_cik, share_class_from_name(cand.name), cand.name,
                             cand.security_type, False, "ticker"), cand.ticker, max(fd, not_before))
    ctx.meter.done("successor search", mark)
    return found


def _link_successors(delistings: list[Delisting], successors: _Successors) -> None:
    """Record stage 9's answer on the delistings: each one's successor (a
    security of the run also says how it was found, in the evidence and the
    reason), and `resolution_degraded` on the rows whose search was degraded."""
    for d in delistings:
        link = successors.links.get(d.key)
        if link is not None:
            sid, how = link
            reason = successors.rebucketed.get(d.key)
            if reason is not None:                  # an `unknown` row at the line's switch: the continuation
                d.record.bucket, d.record.crsp_code, d.record.reason = (CrspBucket.EXCHANGE_TRANSFER,
                                                                        CONTINUATION_CODE, reason)
                d.record.confidence = "medium"     # as a handoff continuation without a successor filing
                d.record.evidence["flags"] = [f for f in d.flags if f != "no_evidence_default"] + [LINE_CONTINUATION]
            d.set_successor(sid)
            if how is not None:
                d.record.evidence["successor_by"] = how
                d.record.reason = f"{d.record.reason}; successor by {how.replace('_', ' ')}"
        if d.key in successors.degraded:
            flag_degraded(d)


def _handoffs(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
              search: _DelistingSearch, sec_cusips: dict[str, list[str]], ftd: FtdIndex, payouts: _Payouts,
              review: list[ReviewItem]) -> HandoffOutcome:
    """9b. Ticker handoffs (`handoffs.py`): every pair of securities of the run
    where one stops trading under a ticker and the other starts under it within
    days (`find_handoffs`, over the sightings `ticker_history` is built from:
    backfilled observations dropped), decided on the successor issuer's
    8-K12B/8-K12G3 (EDGAR full-text search, else its own filing list), else on timing and identity, else
    as a takeover by a line or an issuer that existed before (`decide_handoff`:
    the issuer's first EDGAR filing dates it), then acted on (`apply_handoffs`): a continuation's
    missing row is added, a successor or a ticker successor set, and the review
    items it resolves dropped. A merger whose payout the gate kept counts as
    reconciled. Returns the outcome; the caller adds its rows."""
    clients, edgar = ctx.clients, ctx.clients.edgar
    fts = getattr(edgar, "full_text_search", None)
    sightings = {sid: filtered_ticker_sightings(sig, sec_cusips.get(sid, []), ftd)
                 for sid, sig in search.sightings.items()}
    pairs = find_handoffs(sightings)
    mark = ctx.meter.start()

    def filing_args(p) -> tuple[list[str], date, int] | None:
        a, b = securities[p.a], securities[p.b]
        if fts is None or b.issuer_cik is None:
            return None
        sub = edgar.submissions(a.issuer_cik) if a.issuer_cik is not None else None
        return predecessor_names(sub, p.a_last, a.name), date.fromisoformat(p.b_first), b.issuer_cik

    def find_filing(p):
        args = filing_args(p)
        if args is not None:
            names, day, cik = args
            hit = next((f for n in names if (f := continuation_filing(fts, name=n, day=day, successor_cik=cik))),
                       None)
            if hit is not None:
                return hit
        b_cik = securities[p.b].issuer_cik
        if b_cik is None or issuer_carries_on(p, securities, first_seen):
            return None     # the filing names no predecessor: not for an A whose issuer went on in another line
        return own_continuation_filing(edgar.recent_filings(b_cik), date.fromisoformat(p.b_first))

    if fts is not None and ctx.sec_workers > 1:
        def warm_search(p) -> None:
            args = filing_args(p)
            if args is not None:
                for n in args[0]:
                    fts(*successor_query(n, args[1]))
        warm(pairs, warm_search, workers=ctx.sec_workers, name="handoff search")
    first_seen = {sid: sig[0].day for sid, sig in sightings.items() if sig}

    def issuer_since(cik: int | None) -> str | None:
        """The issuer's first EDGAR filing (the finder already read its filings)."""
        dates = [f.filing_date for f in edgar.recent_filings(cik) if f.filing_date] if cik is not None else []
        return min(dates) if dates else None

    decisions: list[HandoffDecision] = []
    degraded: list[ReviewItem] = []
    for p in pairs:
        watch = DegradedWatch()
        filing = find_filing(p)
        if watch.tripped():
            a = securities[p.a]
            degraded.append(degraded_item(p.a, p.ticker, a.issuer_cik, f"the handoff search ({p.ticker} to {p.b})",
                                          last_seen=p.a_last))
        a_cik, b_cik = securities[p.a].issuer_cik, securities[p.b].issuer_cik
        same = a_cik is not None and a_cik == b_cik
        decision = decide_handoff(p, filing=filing, same_issuer=same,
                                  cusip_switch=cusip_switch(ftd, p, sec_cusips.get(p.a, []), sec_cusips.get(p.b, [])),
                                  issuer_carries_on=issuer_carries_on(p, securities, first_seen),
                                  b_issuer_since=None if same else issuer_since(b_cik))
        if decision is not None:
            decisions.append(decision)
    ctx.meter.done("handoff search", mark)
    gated = payouts.gated
    reconciled = {e.key for e in delistings if for_delisting(gated.payouts, e.key) is not None
                  or for_delisting(gated.merged_terms, e.key)}
    outcome = apply_handoffs(decisions, delistings, securities, review, reconciled=reconciled)
    for d in outcome.added:
        d.exchange = issuer_exchange(edgar, d.cik, d.ticker) or ""
    outcome.review += degraded
    ctx.log(f"handoffs: {len(pairs)} candidate pairs; {outcome.counts}")
    return outcome


PREDECESSOR_FORM25_DAYS = 30     # stage 9d: a successor's Form 25 this close to its first day is its predecessor's


@dataclass
class _SuccessorEndings:
    """Stage 9d's answer: the endings found for the successors the run added, the securities they were searched
    as (one era over each successor's span) with their CUSIPs, and the degraded-answer review items."""
    delistings: list[Delisting] = field(default_factory=list)
    securities: dict[str, Security] = field(default_factory=dict)
    cusips: dict[str, list[str]] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)


def _successor_endings(ctx: _RunContext, finder: DelistingFinder, added: Mapping[str, AddedSecurity],
                       securities: dict[str, Security], sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                       answers: _IssuerAnswers, delistings: Iterable[Delisting] = ()) -> _SuccessorEndings:
    """9d. The Form 25 search (`DelistingFinder.find`, Form 25 matches only: no fallback ending for a security no
    observation names) for each successor the run added: a line successor (`AddedLineSuccessor`, seen over its new
    CUSIP's fails rows: California Resources' 2016 line, Dynegy's 2010 line, ODP Corp) and an 8-K12B successor
    (`AddedSuccessor`, alive from its 8-K12B until its issuer's own Form 25: TiVo Corp, Rovi's successor). Each is
    searched as a security with one era over that span, beside the run's securities of its issuer; a successor
    listed today keeps no ending. An 8-K12B successor's span then runs to the ending's last trade. A Form 25 that
    already owns one of the run's delistings (the predecessor's own, filed under the shared CIK: OKE 2026) raises no
    unmatched review item here."""
    clients, out = ctx.clients, _SuccessorEndings()
    owned = {d.form25_sub.accession for d in delistings if d.form25_sub is not None}
    mark = ctx.meter.start()
    for sid, a in sorted(added.items()):
        cik = a.security.issuer_cik
        if isinstance(a, AddedAcquirer) or cik is None or sid in securities:
            continue
        rows = list(getattr(a, "rows", []))
        first, last = a.span()
        end = last if rows else ctx.as_of.isoformat()
        era = TickerEra(a.ticker, first, end, [Observation(a.ticker, first, a.security.name),
                                               Observation(a.ticker, end, a.security.name)])
        s = replace(a.security, eras=[era])
        world = {x.sec_id: x for x in securities.values() if x.issuer_cik == cik} | {sid: s}
        cusips = {x: list(sec_cusips.get(x, [])) for x in world} | {sid: sorted({r.cusip for r in rows})}
        sightings = {x: ticker_sightings(world[x], ftd, cusips[x]) for x in world}
        watch = DegradedWatch()
        try:
            listed = listed_today(clients.figi, sid, edgar=clients.edgar, cik=cik, tickers=[a.ticker])
            found, found_review = ([], []) if listed else finder.find(
                _context_builder(world, sightings, answers, ftd, cusips)(s, listed), fallback=False)
        except FATAL:
            raise
        except Exception as exc:  # one added successor must not abort the run
            ctx.log(f"{sid}: successor ending search ERROR {type(exc).__name__}: {exc}")
            out.review.append(ReviewItem(sid, a.ticker, cik, "error", f"{type(exc).__name__}: {exc}"))
            continue
        # a Form 25 filed within PREDECESSOR_FORM25_DAYS of the successor's first day removed its predecessor
        start = (date.fromisoformat(first) + timedelta(days=PREDECESSOR_FORM25_DAYS)).isoformat()
        endings = [d for d in found if d.record.successor_sec_id != sid
                   and not (d.form25_sub is not None and d.form25_sub.filing_date <= start)]
        watch.report(out.review, degraded_item(sid, a.ticker, cik, "the successor ending search",
                                               "; run again once SEC answers"), endings)
        report_halt_feed_failures(out.review, endings)
        out.review += [r for r in found_review if not owned.intersection(r.reason.split())]
        if not endings:
            continue
        out.delistings += endings
        out.securities[sid] = s
        out.cusips[sid] = cusips[sid]
        if isinstance(a, (AddedSuccessor, AddedLineSuccessor)) and endings[-1].last_trade.day is not None:
            a.last = endings[-1].last_trade.day.isoformat()
    ctx.log(f"successor endings: {len(out.delistings)} for {len(out.securities)} added successors "
            f"({', '.join(sorted(out.securities)) or 'none'})")
    ctx.meter.done("successor endings", mark)
    return out


def _log_role_refusals(ctx: _RunContext, delistings: Sequence[Delisting]) -> None:
    """The delistings whose end-of-era reading took the registrant's role into account (sub-plan 5c, rule 1: the
    registrant acquired or distributed, `evidence["survived"]`), as one log line the operator can check after a
    network run."""
    sids = sorted(d.sec_id for d in delistings if (d.record.evidence or {}).get("survived"))
    ctx.log(f"role refusal: {len(sids)} rows ({', '.join(sids)})")


def _date_from_notices(ctx: _RunContext, added: list[Delisting], review: list[ReviewItem]) -> int:
    """9c. A continuation row the handoff stage built from an unmatched Form 25
    carries its last sighting as its last trade day; when that Form 25's notice
    states a confirmed last day of trading (`form25.notice_last_trade`,
    `last_trade.decide_last_trade`), the row takes it (source `ex99_notice`),
    provided the day is before the successor's first sighting
    (`evidence["handoff"]["b_first"]`; the cap is skipped when absent) and no
    later than the Form 25 effective date (`delist_date`); otherwise the
    sighting stays. A read that rested on a failed request or a stale copy keeps
    the sighting and is reported as `resolution_degraded` (row and review item);
    a refusal (`fatal.FATAL`) stops the run."""
    mark = ctx.meter.start()
    redated = 0
    for d in added:
        filing = (d.record.evidence or {}).get("delist_filing")
        if not filing or d.last_trade.source != "last_sighting":
            continue
        watch = DegradedWatch()
        raw = ctx.clients.edgar.fetch_filing_raw(d.cik, filing["accession"])
        if watch.tripped():
            watch.report_delisting(review, d, "the handoff row's Form 25 notice")
            continue
        if not raw:
            continue
        f25 = parse_form25(raw, accession=filing["accession"], form=filing["form"], filing_date=filing["filing_date"])
        lt = decide_last_trade(notice=notice_last_trade(f25), eightk=(None, ""), midas=None, halt=None)
        if lt.day is None or "last_trade_date_unconfirmed" in lt.flags:
            continue
        b_first = (d.record.evidence.get("handoff") or {}).get("b_first")
        if (b_first and lt.day >= date.fromisoformat(b_first)) or lt.day > date.fromisoformat(d.delist_date):
            continue
        d.last_trade = lt
        d.record.observed_delist_date = lt.day.isoformat()   # handoffs.py dates the record the same as the row
        redated += 1
    ctx.log(f"handoff rows dated from their Form 25 notice: {redated}")
    ctx.meter.done("handoff notice dates", mark)
    return redated


NOTICE_BEFORE_DAYS, NOTICE_AFTER_DAYS = 30, 60     # 9e: the 3.01 8-Ks read around a drop's last trade...
REASON_AFTER_DAYS = 30                             # ...those that state its removal's reason, when no Form 25 does
PLAN_BEFORE_DAYS, PLAN_AFTER_DAYS = 5, 10          # a bankruptcy plan's 8-Ks (item 1.03 or 3.03) around its Form 25
PLAN_ITEMS = frozenset({"1.03", "3.03"})
PRICE_CODE = 552                                   # CRSP: price fell below the acceptable level (drop reason price)
DISTRESS_BUCKETS = frozenset({CrspBucket.LIQUIDATION, CrspBucket.COMPLIANCE_FAILURE, CrspBucket.UNKNOWN})


def _eightks(edgar, cik: int, lo: date, hi: date, items: Collection[str]) -> list:
    """The issuer's 8-Ks carrying one of `items`, filed in [lo, hi], earliest first."""
    return [f for f in sorted(edgar.recent_filings(cik), key=lambda f: (f.filing_date, f.accession))
            if f.form.startswith("8-K") and set(items) & f.item_set and lo.isoformat() <= f.filing_date <= hi.isoformat()]


def _distress(ctx: _RunContext, delistings: list[Delisting], sec_cusips: Mapping[str, list[str]], ftd: FtdIndex,
              review: list[ReviewItem]) -> dict[DelistingKey, DistressTerms]:
    """9e. Sub-plan 5g: what a drop or a bankruptcy ending needs beyond its classification (`distress.py`), for each
    delisting in the liquidation, compliance-failure or unknown bucket that names no successor; its last trade day
    (else its delisting date) anchors every read.

    1. A bankruptcy plan exchange (ruling R6): the matched Form 25's notice says the class came to evidence new
       shares, the ending is a bankruptcy (code 470, or the notice says so: an unknown ending then becomes 470), and
       the old line never traded off the exchange (`otc_symbol_from_fails` reads nothing). Its ratio, from the notice
       or the plan's 8-Ks (item 1.03 or 3.03, PLAN_BEFORE_DAYS/PLAN_AFTER_DAYS around the Form 25), makes the stock
       rule on the new line under the same ticker.
    2. The drop reason: a compliance failure (570, 580) whose removal the exchange stated for a price deficiency
       only (`price_only` on the exchange's Form 25 notice, else, without a Form 25, on the 3.01 items in
       [last trade - NOTICE_BEFORE_DAYS, last trade + REASON_AFTER_DAYS]) is CRSP 552. An issuer's own Form 25 (a
       voluntary removal) states no exchange reason: unchanged.
    3. The OTC symbol of a liquidation or a compliance failure: the security's own CUSIPs' fails rows after the
       last trade (stage 4 loaded them to the run date), else the first 3.01 8-K in [last trade -
       NOTICE_BEFORE_DAYS, last trade + NOTICE_AFTER_DAYS] that names one, else "" (published blank).

    A read that rested on a failed request or a stale copy is reported `resolution_degraded` (row and review item);
    a refusal (`fatal.FATAL`) stops the run. Returns each delisting's terms, for the contract (stage 10g)."""
    mark = ctx.meter.start()
    edgar, out, counts = ctx.clients.edgar, {}, Counter()

    def text(d: Delisting, f) -> str:
        return edgar.fetch_filing_text(d.cik, f.accession, f.primary_doc) or ""

    for d in delistings:
        rec = d.record
        if rec.bucket not in DISTRESS_BUCKETS or rec.successor_sec_id:
            continue
        last = d.last_trade.day or date.fromisoformat(d.delist_date)
        rows = [r for c in sec_cusips.get(d.sec_id, ())
                for r in ftd.by_cusip(c, last.isoformat(), (last + timedelta(days=OTC_SYMBOL_DAYS)).isoformat())]
        fails_symbol = otc_symbol_from_fails(rows, d.ticker, last)
        notice = d.form25.notice_text if d.form25 is not None else ""
        terms, watch = DistressTerms(), DegradedWatch()
        bankrupt_notice = bool(BANKRUPTCY_WORDS.search(notice))
        if (fails_symbol is None and substitutes_new_shares(notice) and rec.bucket is not CrspBucket.COMPLIANCE_FAILURE
                and (rec.crsp_code == 470 or bankrupt_notice)):
            plan = plan_ratio(notice, [])
            if plan is None:
                filed = date.fromisoformat(d.form25.filing_date)
                plan = plan_ratio(notice, [text(d, f) for f in _eightks(
                    edgar, d.cik, filed - timedelta(days=PLAN_BEFORE_DAYS), filed + timedelta(days=PLAN_AFTER_DAYS),
                    PLAN_ITEMS)])
            if rec.bucket is CrspBucket.UNKNOWN and bankrupt_notice:
                rec.crsp_code, rec.bucket, rec.confidence = 470, CrspBucket.LIQUIDATION, "medium"
                rec.reason = (f"Bankruptcy plan exchange (Form 25 {d.form25.filing_date} notice: the class came to "
                              f"evidence new shares)")
                rec.evidence["flags"] = [f for f in d.flags if f != "no_evidence_default"]
                counts["plan bankruptcy"] += 1
            if plan is not None and rec.bucket is CrspBucket.LIQUIDATION:
                terms = DistressTerms(plan_ratio=plan[0], plan_ticker=d.ticker, plan_source=plan[1])
                counts["plan ratio"] += 1
        if rec.bucket is CrspBucket.COMPLIANCE_FAILURE and rec.crsp_code in (570, 580):
            if d.form25 is None:
                stated = "\n".join(s for f in _eightks(edgar, d.cik, last - timedelta(days=NOTICE_BEFORE_DAYS),
                                                       last + timedelta(days=REASON_AFTER_DAYS), ("3.01",))
                                   for s in item_sections(text(d, f), "3.01"))
            else:
                stated = "" if d.form25.form in ISSUER_FORM25_FORMS else notice
            if price_only(stated):
                rec.crsp_code = PRICE_CODE
                rec.reason += " (its stated reason: a price deficiency)"
                counts["price"] += 1
        if not terms.plan_ratio and rec.bucket is not CrspBucket.UNKNOWN:
            symbol = fails_symbol
            if symbol is None:
                symbol = next((s for f in _eightks(edgar, d.cik, last - timedelta(days=NOTICE_BEFORE_DAYS),
                                                   last + timedelta(days=NOTICE_AFTER_DAYS), ("3.01",))
                               if (s := otc_symbol_from_text(text(d, f)))), "")
                counts["otc symbol from a notice" if symbol else "otc symbol unknown"] += 1
            else:
                counts["otc symbol from fails"] += 1
            terms = replace(terms, otc_symbol=symbol)
        if watch.tripped():
            watch.report_delisting(review, d, "the drop's or the bankruptcy's notices (stage 9e)")
        out[d.key] = terms
    ctx.log(f"distress endings: {dict(sorted(counts.items()))}")
    ctx.meter.done("distress notices", mark)
    return out


def _plan_values(overrides: Overrides, distress: Mapping[DelistingKey, DistressTerms]) -> Overrides:
    """9f. A bankruptcy plan's received close the caller answered (its ratio x the new line's close, the request
    stage 10g asks) is that ending's value, as an answered print is a drop's: its dlret is value / last close - 1
    instead of the Shumway fill. An answer for another ticker, or an ending with a value of its own, is left."""
    given = dict(overrides.otc_prints)
    for key, t in distress.items():
        got = overrides.acquirer_prices.get(key)
        if t.plan_ratio and got is not None and got[0] == t.plan_ticker and key not in given:
            given[key] = float(t.plan_ratio) * got[1]
    return replace(overrides, otc_prints=given)


def _delisting_rows(delistings: list[Delisting], closes: dict[DelistingKey, float], payouts: _Payouts,
                    overrides: Overrides) -> tuple[list[dict], list[dict]]:
    """10a. The delistings.csv rows, and the review rows of those delistings that
    carry a flag or no DLRET."""
    gated = payouts.gated
    table = build_delistings_table(
        [e.record for e in delistings], last_trade_closes=closes, payouts=gated.payouts,
        exchanges={e.key: e.exchange for e in delistings},
        merger_terms=gated.merged_terms, recovery_ratios=overrides.recoveries, otc_prints=overrides.otc_prints,
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
            ticker_successor_sec_id=e.record.ticker_successor_sec_id,
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


def _continues_after(s: Security, after: str, sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                     successor_starts: Mapping[str, str] = {}) -> bool:
    """Whether security `s`'s own CUSIP keeps trading under its own ticker(s)
    strictly after the ISO date `after` (Phase 4's clip rule): at least
    `CONTINUATION_MIN_ROWS` live fails rows (never a deleted symbol; a fail
    still settling after the real end) over at least `CONTINUATION_MIN_DAYS`
    days, with `CONTINUATION_MIN_PRICES` or more distinct prices -- so a
    compliance failure's OTC tail settling at one price is not mistaken for
    continued trading (WRK stops being clipped; ARD and compliance failures
    stay clipped). Rows under a ticker a successor security took (`successor_starts`, `_successor_starts`) from
    that day on are the successor's, not `s`'s continuing (AON 2012: Aon plc's AON, the old CUSIP's lingering
    fails)."""
    own = s.own_tickers()
    rows = [r for r in ftd.trading_rows(sec_cusips.get(s.sec_id, []))
            if r.symbol in own and r.date > after and r.date < successor_starts.get(r.symbol, "~")]
    if len(rows) < CONTINUATION_MIN_ROWS:
        return False
    dates = [r.date for r in rows]
    if (date.fromisoformat(max(dates)) - date.fromisoformat(min(dates))).days < CONTINUATION_MIN_DAYS:
        return False
    return len({r.price for r in rows if r.price is not None}) >= CONTINUATION_MIN_PRICES


def _ends_the_security(e: Delisting, s: Security, sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                       successor_starts: Mapping[str, str] = {}) -> bool:
    """Whether delisting `e` is the kind that actually ends security `s`
    (Phase 4): not one whose successor is the security itself (a continuing
    exchange transfer, D18); and, for a merger or exchange_transfer whose
    last-trade day is *confirmed* (`e.last_trade.day` set and not flagged
    `last_trade_date_unconfirmed`) -- an unconfirmed day is a guess (the
    no-Form-25 "continued 10-K/Q filings" fallback substitutes the security's
    own last sighting when it has no last-trade evidence at all, e.g. Monster
    Worldwide's and SunPower's 2008-09 fallback rows; Bank of Ozarks has no
    day at all) and too weak a signal to second-guess against fails evidence
    -- there is no established day to test continuation from -- not one
    after which `s`'s own CUSIP keeps trading under its own ticker
    (`_continues_after`: a WRK-like delisting record that did not really end
    trading, confirmed by a real EX-99.25 notice/8-K/MIDAS/halt day). A
    liquidation, compliance_failure, expiration or unknown delisting always
    ends the security, whatever fails rows follow."""
    if e.record.successor_sec_id == e.sec_id:
        return False
    if (e.record.bucket not in CONTINUATION_BUCKETS or e.last_trade.day is None
            or "last_trade_date_unconfirmed" in e.last_trade.flags):
        return True
    return not _continues_after(s, e.last_trade.day.isoformat(), sec_cusips, ftd, successor_starts)


SUCCESSOR_TICKER_LOOKBACK_DAYS = 30   # with no confirmed last trade, a successor's first row may precede the delist date (STX: 9 days)


def _successor_starts(delistings: Iterable[Delisting], securities: dict[str, Security],
                      sightings: dict[str, list[Sighting]], sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                      added: Mapping[str, AddedSecurity]) -> dict[str, dict[str, str]]:
    """A successor's ticker is not its predecessor's: for each security S, the tickers a successor security X
    (a delisting's `successor_sec_id`, not S itself) took, and from which day: X's first sighting under the
    ticker on or after the delisting's confirmed last trade day (an unconfirmed or missing one: its delist date, less
    `SUCCESSOR_TICKER_LOOKBACK_DAYS`) and within `TAKEOVER_DAYS` (the handoff window) after that anchor; a ticker
    first seen later is a recycled one, no start. S's fails rows and sightings under the ticker from that day on are X's. One place, shared by
    the clip check (`_delisting_endings`) and the ranges (`_history_rows`)."""
    out: dict[str, dict[str, str]] = {}
    for e in delistings:
        x = e.record.successor_sec_id
        if not x or x == e.sec_id or e.sec_id not in securities:
            continue
        confirmed = e.last_trade.day is not None and "last_trade_date_unconfirmed" not in e.last_trade.flags
        try:
            anchor = e.last_trade.day if confirmed else date.fromisoformat(e.delist_date)
        except ValueError:
            continue
        lo = (anchor if confirmed else anchor - timedelta(days=SUCCESSOR_TICKER_LOOKBACK_DAYS)).isoformat()
        hi = (anchor + timedelta(days=TAKEOVER_DAYS)).isoformat()
        if x in securities:
            sig = filtered_ticker_sightings(sightings.get(x, []), sec_cusips.get(x, []), ftd)
        elif x in added:
            sig = [Sighting(added[x].span()[0], added[x].ticker, "ftd")]
        else:
            continue
        mine = out.setdefault(e.sec_id, {})
        for g in sorted(sig):
            if lo <= g.day <= hi and g.day < mine.get(g.value, "~"):
                mine[g.value] = g.day
    return {sid: m for sid, m in out.items() if m}


def _delisting_endings(delistings: Iterable[Delisting], securities: dict[str, Security],
                       sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                       successor_starts: Mapping[str, Mapping[str, str]] = {}) -> dict[DelistingKey, bool]:
    """Whether each delisting actually ends its security (`_ends_the_security`),
    computed once and shared by the ticker_history clip (`_history_rows`) and
    the continuing-delisting successor link (`_mark_continuing_delistings`) --
    so the two tables can never disagree on which delistings are real exits.
    A delisting whose security is not in `securities` (no security object to
    test continuation against) has no entry."""
    out: dict[DelistingKey, bool] = {}
    for e in delistings:
        s = securities.get(e.sec_id)
        if s is not None:
            out[e.key] = _ends_the_security(e, s, sec_cusips, ftd, successor_starts.get(e.sec_id, {}))
    return out


def _mark_continuing_delistings(delistings: Iterable[Delisting], endings: dict[DelistingKey, bool]) -> None:
    """A merger or exchange_transfer that `endings` says does not end its
    security (the DIS 2019 holding-company reorg, WRK's 2018 one) gets
    `successor_sec_id` set to its own `sec_id`, via `Delisting.set_successor`
    -- the same treatment `delistings.py` already gives a classification-time
    `continued` exchange_transfer, now also covering a merger and any
    exchange_transfer the *stronger*, FTD-confirmed check (not the weaker
    `listed_today`/`seen_after` one) catches. `handling.py`/`qlib_adapter.py`
    already skip a row whose successor is itself, so this is never a real
    universe exit. Only ever fills a blank successor: a real, different
    successor a search already found (MWV -> WRK) is never overwritten, and a
    liquidation/compliance_failure/expiration/unknown delisting is untouched
    (`endings` is never False for one)."""
    for e in delistings:
        if not e.record.successor_sec_id and endings.get(e.key) is False:
            e.set_successor(e.sec_id)


def _history_rows(ctx: _RunContext, securities: dict[str, Security], search: _DelistingSearch,
                  sec_cusips: dict[str, list[str]], ftd: FtdIndex, added: dict[str, AddedSecurity],
                  endings: dict[DelistingKey, bool], successor_starts: Mapping[str, Mapping[str, str]] = {}
                  ) -> tuple[list[dict], list[dict], dict[str, str | None], dict[str, bool], dict[str, bool | None]]:
    """10b. The ticker_history and cusip_history rows (`history.history_rows`):
    each observed security's ranges end at the last delisting that actually
    ends it (`endings`, `_delisting_endings`/`_ends_the_security`, computed
    once and shared with `_mark_continuing_delistings` so the two tables never
    disagree) -- its last trade day, or its delist_date when the last trade
    day is unconfirmed -- unless it is listed today or no delisting ends it.
    An added (acquirer/successor) security gets one ticker row, built
    directly: `ranges_from_sightings`' filter that drops single-value FTD
    sightings would otherwise silently drop a successor's lone 8-K12B-dated
    sighting. Also returns each observed security's end date (or None) and
    whether that end came from a confirmed last-trade day, so
    `observation_map_rows` can flag `after_delisting`/`after_unconfirmed_delisting`
    without recomputing either. A security that has an ending and whose ticker a successor security took
    (`successor_starts`) is not listed today, whatever its issuer's EDGAR listing says: the issuer's listing is
    the successor's (AON 2012: the same CIK lists AON today). Also returns the listed answers as used."""
    clients = ctx.clients
    th_rows, ch_rows = [], []
    listed: dict[str, bool | None] = dict(search.listed)
    ends: dict[str, str | None] = {}
    end_confirmed: dict[str, bool] = {}
    final: dict[str, Delisting] = {}
    own_of: dict[str, list[Sighting]] = {}
    for e in sorted(search.delistings, key=lambda e: e.delist_date):
        if endings.get(e.key):
            final[e.sec_id] = e
    for sid, s in securities.items():
        last_delisting = final.get(sid)
        is_listed = bool(search.listed.get(sid))
        if is_listed and last_delisting is not None and sid in successor_starts:
            is_listed = listed[sid] = False
        end = None
        confirmed = False
        if last_delisting is not None and not is_listed:
            # A last-trade day we couldn't confirm still clips the ranges at the
            # delisting date -- an unclipped range would otherwise run past a
            # security's real end.
            confirmed = (last_delisting.last_trade.day is not None
                        and "last_trade_date_unconfirmed" not in last_delisting.last_trade.flags)
            end = (last_delisting.last_trade.day.isoformat() if last_delisting.last_trade.day is not None
                   else last_delisting.delist_date)
        ends[sid] = end
        end_confirmed[sid] = confirmed
        # Phase 4 rule 2: a backfilled observation is not a ticker sighting here
        # (this security's own ticker_history ranges) -- the delisting search's
        # own sightings (`search.sightings`, built once in stage 5) are untouched.
        own_sightings = filtered_ticker_sightings(search.sightings.get(sid, []), sec_cusips.get(sid, []), ftd)
        own_of[sid] = own_sightings
        starts_of = successor_starts.get(sid, {})
        th, ch = history_rows(
            s, own_sightings, cusip_sightings(s, ftd, sec_cusips.get(sid, []), starts_of),
            listed=is_listed, end=end, end_exchange=last_delisting.exchange if last_delisting else None,
            # An open (listed-today) row: the exchange from the issuer's own EDGAR
            # submissions JSON (already cached by the finder).
            exchange_today=lambda ticker, s=s: issuer_exchange(clients.edgar, s.issuer_cik, ticker),
            successor_starts=starts_of)
        th_rows += th
        ch_rows += ch
    th_rows = clip_at_takeovers(th_rows, own_of, ends)
    for sid, a in added.items():
        is_listed = bool(listed_today(clients.figi, sid, edgar=clients.edgar, cik=a.security.issuer_cik,
                                      tickers=[a.ticker]))
        exch = issuer_exchange(clients.edgar, a.security.issuer_cik, a.ticker) if is_listed else None
        th_rows.append(a.history_row(listed=is_listed, exchange=exch))
    return th_rows, ch_rows, ends, end_confirmed, listed


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


def _observation_map(ctx: _RunContext, index: ObservationIndex, eras: list[TickerEra],
                     resolutions: dict[str, EraResolution], issuers: dict[str, Issuer],
                     sec_cusips: dict[str, list[str]], ftd: FtdIndex, ends: dict[str, str | None],
                     end_confirmed: dict[str, bool], listed: dict[str, bool | None],
                     th_rows: list[dict]) -> list[dict]:
    """10c2. observation_map.csv's rows (`history.observation_map_rows`): every
    observation of the run's eras (`--limit` already trims which ones), its
    era, sec_id, issuer CIK, `ticker_history` spelling/coverage on its date,
    and status. The log names how many of the input's observations that is,
    so a `--limit` subset's smaller count is not mistaken for a bug."""
    sec_id_of = {k: r.sec_id for k, r in resolutions.items()}
    issuer_cik_of = {k: cik_of(issuers, k) for k in resolutions}
    conflicts = [(t, d) for t, d, _ in observation_conflicts(o for e in eras for o in e.observations)]
    rows = observation_map_rows(eras, sec_id_of, issuer_cik_of, sec_cusips, ftd, ends, end_confirmed, listed,
                                th_rows, conflicts)
    total = sum(len(e.observations) for e in index.eras())
    ctx.log(f"observation_map: {len(rows)} of {total} observations mapped")
    return rows


def _triage(ctx: _RunContext, review_rows: list[dict], review_decisions: Sequence[Decision],
            limit: int | None) -> tuple[Counter, Triage]:
    """10d. review.csv and review_summary.csv from every review row of the run
    (merged by key), and every flag counted before triage hides or accepts any:
    that tally feeds RunSummary.review_flags and the manifest, so exit code 3
    still sees every `error` and `resolution_degraded`."""
    review_rows = merge_review_rows(review_rows)
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


def _era_tier(answers: _IssuerAnswers, era_key: str) -> str:
    """The resolver tier that found an era's CIK: its first-pass answer, else its
    second-pass one, else ""."""
    if era_key in answers.resolutions:
        return answers.resolutions[era_key].source
    if era_key in answers.inferred:
        return answers.inferred[era_key].source
    return ""


def _ticker_evidence(ctx: _RunContext, securities: dict[str, Security], answers: _IssuerAnswers) -> dict[str, str]:
    """10e. What ties each placeholder's ticker to its CIK (decision 1;
    ticker_evidence.evidence_for): a resolver tier that names the ticker, else
    a full-text hit in the CIK's own filings. A client without full-text
    search (a test double) gives every other placeholder no evidence."""
    search = getattr(ctx.clients.edgar, "full_text_search", None)
    mark = ctx.meter.start()
    out = {s.sec_id: evidence_for(s.issuer_cik,
                                  [EraEvidence(e.ticker, e.first, e.last, _era_tier(answers, e.key)) for e in s.eras],
                                  search)
           for s in securities.values() if s.figi_source == "placeholder"}
    ctx.meter.done("ticker evidence", mark)
    return out


def _as_read(tables: dict[str, list[dict]]) -> Tables:
    """The tables about to be written, as store.read_table would read them back."""
    def rows(name: str) -> list[dict[str, str]]:
        return formatted(name, tables[name])
    return Tables(rows("securities"), rows("ticker_history"), rows("delistings"), rows("observation_map"),
                  rows("review"), rows("uncertain") if "uncertain" in tables else None,
                  rows("security_history") if "security_history" in tables else None,
                  rows("contract_delistings") if "contract_delistings" in tables else None)


def _in_force_reads(ctx: _RunContext, failed: set[int] | None = None
                    ) -> tuple[Callable[[int], Any], Callable[[str], list[int]]]:
    """The two EDGAR reads `issuer_in_force` takes: a CIK's submissions (memoized; a read that fails is None, a
    refusal (`fatal.FATAL`) stops the run; `failed` collects each CIK whose answer failed or rested on a stale
    copy) and the CIKs SEC's name index lists under exactly a name (none without an index: a test double's
    resolver)."""
    edgar, memo = ctx.clients.edgar, {}

    def submissions(cik: int):
        if cik not in memo:
            watch = DegradedWatch()
            try:
                memo[cik] = edgar.submissions(cik)
            except FATAL:
                raise
            except requests.RequestException:
                memo[cik] = None
                if failed is not None:
                    failed.add(cik)
            if watch.tripped() and failed is not None:
                failed.add(cik)
        return memo[cik]

    index_of = getattr(ctx.clients.resolver, "name_index", None)
    index = index_of() if callable(index_of) else None

    def exact_names(name: str) -> list[int]:
        return [h.cik for h in index.split_search(name)[0]] if index is not None else []

    return submissions, exact_names


def _other_issuers(ctx: _RunContext, eras: list[TickerEra], resolutions: dict[str, EraResolution],
                   issuers: dict[str, Issuer], securities: dict[str, Security],
                   review: list[ReviewItem] | None = None, rows_decided: Collection[str] = ()) -> dict[str, int]:
    """4c. R5: each security whose issuer in force (`issuer_in_force.issuer_changes`, over its eras' observations
    with their era's CIK, a (ticker, day) seen under two names left out, as stage 10g reads them) was one CIK
    other than its own issuer CIK on every sighting: that CIK, whose Form 25s the finder reads too. Spectrum
    Brands 2010-2018 was the old Spectrum Brands (CIK 1487730) while today's CIK 109177 holds the security. A
    security whose issuer changed in its span has none (Perrigo: CIK 820096 until 2013, then its own). A security
    for whose answer a submissions read failed or was stale gets a `resolution_degraded` row in `review`: the
    other CIK's Form 25s it may have lost are not read until a rerun."""
    failed: set[int] = set()
    read, exact_names = _in_force_reads(ctx, failed)
    touched: set[int] = set()

    def submissions(cik: int):
        touched.add(cik)
        return read(cik)

    conflicts = {(t, d) for t, d, _ in observation_conflicts(o for e in eras for o in e.observations)}
    # an era whose issuer its ticker's fails rows decided (stage 2b) keeps it: its observed name was refuted
    sightings = [IssuerSighting(r.sec_id, o.as_of, "" if e.key in rows_decided else o.name or "",
                                str(cik_of(issuers, e.key) or ""))
                 for e in eras if (r := resolutions.get(e.key)) is not None and r.sec_id
                 for o in e.observations if (o.ticker, o.as_of) not in conflicts]
    mark = ctx.meter.start()
    out: dict[str, int] = {}
    by_sec: dict[str, list[IssuerSighting]] = defaultdict(list)
    for x in sightings:
        by_sec[x.sec_id].append(x)
    for sid, rows in sorted(by_sec.items()):
        touched.clear()
        timeline = issuer_changes(rows, submissions, exact_names).get(sid, [])
        s = securities.get(sid)
        if s is not None and review is not None and touched & failed:
            review.append(degraded_item(sid, s.eras[-1].ticker, s.issuer_cik, "the other issuer in force",
                                        "; run again once SEC answers"))
        if s is not None and s.issuer_cik is not None and len(timeline) == 1 and timeline[0][1] != str(s.issuer_cik):
            out[sid] = int(timeline[0][1])
    ctx.log(f"other issuer in force: {len(out)} securities ({', '.join(sorted(out)[:5])}"
            f"{', ...' if len(out) > 5 else ''})")
    ctx.meter.done("other issuers in force", mark)
    return out


def _issuers_in_force(ctx: _RunContext, observation_map: Sequence[Mapping[str, str]],
                      rows_decided: Collection[str] = ()) -> dict[str, list[tuple[str, str]]]:
    """Each security's issuer timeline (issuer_in_force.issuer_changes) from its
    sightings: every observation_map row with a sec_id, except a conflict (two
    names that day). A submissions read that fails keeps the era's CIK; a refusal
    (`fatal.FATAL`) stops the run. Without a name index (a test double's
    resolver), every sighting keeps its era's CIK. A sighting of an era whose
    issuer its ticker's fails rows decided (`rows_decided`, stage 2b's
    `ticker_rows`) keeps its era's CIK too: its observed name is the one those
    rows refuted (ERA 2013's BRISTOW GROUP INC)."""
    submissions, exact_names = _in_force_reads(ctx)
    mark = ctx.meter.start()
    out = issuer_changes((IssuerSighting(r["sec_id"], r["as_of"], "" if r["era"] in rows_decided else r["name"],
                                         r["issuer_cik"])
                          for r in observation_map if r["sec_id"] and r["status"] != "conflict"),
                         submissions, exact_names)
    ctx.meter.done("issuers in force", mark)
    return out


def _era_renames(eras: Sequence[TickerEra], resolutions: Mapping[str, EraResolution],
                 issuers: Mapping[str, Issuer]) -> dict[str, str]:
    """The placeholder each era of a known issuer would hold (its issuer and its name's class) -> the one FIGI its
    eras hold now, for contract/id_changes.csv: a placeholder stage 3 joined to its issuer's line across a class
    label (sub-plan 5h: MSG's CLASS A eras on MSG Networks' plain-named line) is a rename too. A placeholder whose
    eras now hold two FIGIs, or that an era still holds, is no rename."""
    held: dict[str, set[str]] = defaultdict(set)
    kept = {r.sec_id for r in resolutions.values() if r.sec_id and is_placeholder(r.sec_id)}
    for e in eras:
        cik, r = cik_of(issuers, e.key), resolutions.get(e.key)
        if cik is None or r is None or not r.sec_id or is_placeholder(r.sec_id):
            continue
        held[placeholder_id(cik, share_class_from_name(e.name))].add(r.sec_id)
    return {p: next(iter(f)) for p, f in held.items() if len(f) == 1 and p not in kept}


def _contract(ctx: _RunContext, read: Tables, verdicts: Verdicts, payouts: _Payouts, successor_ids: set[str],
              overrides: Overrides, id_baseline: Sequence[Mapping[str, str]],
              renames: Mapping[str, str] = {}, rows_decided: Collection[str] = (),
              distress: Mapping[DelistingKey, DistressTerms] | None = None) -> dict[str, list[dict]]:
    """10g. The contract (contract.py), written under contract/ beside today's
    tables (decision 6): security_history with each interval's issuer in force
    (`_issuers_in_force`), leaving out the merger acquirers the run adds;
    delistings, one row per ended security (a drop's OTC symbol and a bankruptcy
    plan's ratio from stage 9e, `distress`); the seed echo; the price requests (a
    plan's new line asks a received close); and the placeholders of `id_baseline`
    (a securities.csv) that now hold a FIGI (`renames`: stage 4b's folds, by name,
    whatever other FIGI lines the issuer has)."""
    issuers = _issuers_in_force(ctx, read.observation_map, rows_decided)
    endings = last_endings(read.delistings)
    inputs = merger_inputs(list(endings.values()), payouts.llm_terms, payouts.raw, overrides.merger_terms,
                           payouts.acquirer_ids, payouts.price_tickers)
    ended = contract_delisting_rows(read, verdicts, inputs, distress)
    legs = stock_legs(list(endings.values()), payouts.llm_terms, overrides.merger_terms, payouts.acquirer_ids,
                      payouts.price_tickers)
    legs.update({k: (t.plan_ticker, "") for k, t in (distress or {}).items() if t.plan_ratio and k not in legs})
    requests = request_rows(ended, endings, legs)
    unrequested = sorted(set(overrides.price_answers) - {key_of(r) for r in requests})
    if unrequested:
        raise OverrideFileError("--price-answers rows that answer no request of this run: "
                                + "; ".join(" ".join(k) for k in unrequested[:5])
                                + (f" (and {len(unrequested) - 5} more)" if len(unrequested) > 5 else ""))
    return {
        "security_history": security_history_rows(read, issuers, leave_out=set(payouts.added) - successor_ids),
        "contract_delistings": ended,
        "seeds": seed_rows(read, verdicts),
        "price_requests": requests,
        "id_changes": id_change_rows(id_baseline, read.securities, ctx.as_of.isoformat(), renames),
    }


def _scorecard(ctx: _RunContext, read: Tables, config: run_scorecard.ScorecardConfig, limit: int | None) -> dict:
    """10h. The scorecard of the tables about to be written (`read`), with
    `drops`: the floored numbers that got worse. A --limit subset sees a
    fraction of the universe, so its numbers are never compared to the floor."""
    card = run_scorecard.build(read, as_of=ctx.as_of, config=config)
    card["drops"] = run_scorecard.drops(card, config.floor) if limit is None else []
    for line in card["drops"]:
        ctx.log(f"scorecard drop: {line}")
    for line in card["golden_failures"]:
        ctx.log(f"golden case failing: {line}")
    return card


def _run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path, tol: float,
         limit: int | None, log: Callable, sec_workers: int,
         review_decisions: Sequence[Decision] = (),
         scorecard: run_scorecard.ScorecardConfig = run_scorecard.ScorecardConfig(),
         id_baseline: Sequence[Mapping[str, str]] = ()) -> RunSummary:
    """The run's stages in order (each function's docstring says what it does);
    `run` wraps it with the resolver memo's final flush."""
    ctx = _RunContext(clients, clients.as_of or date.today(), log, sec_workers, run_manifest.StageMeter(log))
    run_mark = SEC_STATS.snapshot()           # the manifest reports the traffic since here
    eras, era_by_key, ftd, ftd_lo = _refine(ctx, index, limit)                                      # 1
    answers = _resolve_issuers(ctx, eras, ftd)                                                      # 2
    resolutions, securities, review = _resolve_securities(ctx, eras, era_by_key, ftd, answers)      # 3
    sec_cusips = _security_cusips(ctx, securities, resolutions, ftd, ftd_lo)                        # 4
    lines = _follow_lines(ctx, securities, resolutions, era_by_key, sec_cusips, ftd, ftd_lo, answers)  # 4b
    securities, resolutions, sec_cusips = lines.securities, lines.resolutions, lines.sec_cusips
    # a folded placeholder's review items follow it to its FIGI line, where it holds a FIGI after all
    review = [replace(r, sec_id=lines.renames.get(r.sec_id, r.sec_id)) for r in review + lines.review
              if not (r.flag == "no_figi" and r.sec_id in lines.renames)]
    rows_decided = {k for k, v in answers.inferred.items() if v.source == TickerResolver.TICKER_ROWS}
    other_ciks = _other_issuers(ctx, eras, resolutions, answers.issuers, securities, review, rows_decided)  # 4c
    search = _find_delistings(ctx, securities, sec_cusips, ftd, answers, set(lines.successors),
                              other_ciks)                                                           # 5
    delistings = search.delistings
    review += search.review
    _dead_before_sighting(ctx, securities, delistings, sec_cusips, ftd, search.sightings, answers.issuers)   # 5b
    _check_overrides(overrides, delistings)                                                         # 6
    given = overrides                                     # the caller's overrides, before the answers join them
    overrides = _apply_price_answers(given, delistings)                                             # 6b
    closes = _last_trade_closes(ctx, delistings, securities, sec_cusips, ftd, ftd_lo, overrides)    # 7
    payouts = _merger_payouts(ctx, delistings, securities, sec_cusips, ftd, closes, overrides, tol,
                              search.sightings, ftd_lo)                                             # 8
    review += payouts.review
    r1 = _r1_continuations(ctx, delistings, securities, search.sightings, payouts, overrides)      # 8b
    review += r1.review
    successors = _find_successors(ctx, delistings, securities, search.sightings, {**payouts.added, **r1.added},
                                  lines.successors, ftd, sec_cusips)                                # 9
    _link_successors(delistings, successors)
    review += successors.review
    added = {**payouts.added, **r1.added, **successors.added}     # the acquirers and successors the run adds

    # Computed once, shared by the delistings.csv successor link and the
    # ticker_history clip below, so the two tables never disagree on which
    # delistings are real exits (a WRK/DIS-like continuing merger or
    # exchange_transfer gets successor_sec_id = itself).
    starts = _successor_starts(delistings, securities, search.sightings, sec_cusips, ftd, added)
    endings = _delisting_endings(delistings, securities, sec_cusips, ftd, starts)
    _mark_continuing_delistings(delistings, endings)

    handoffs = _handoffs(ctx, delistings, securities, search, sec_cusips, ftd, payouts, review)       # 9b
    review = handoffs.review
    _date_from_notices(ctx, handoffs.added, review)       # 9c: before the added rows' closes are read
    if handoffs.added:
        delistings += handoffs.added
        overrides = _apply_price_answers(given, delistings)   # the added delistings take their answers too
        closes.update(_last_trade_closes(ctx, handoffs.added, securities, sec_cusips, ftd, ftd_lo, overrides))
    ends = _successor_endings(ctx, search.finder, added, securities, sec_cusips, ftd, answers, delistings)   # 9d
    review += ends.review
    if ends.delistings:
        delistings += ends.delistings
        overrides = _apply_price_answers(given, delistings)
        closes.update(_last_trade_closes(ctx, ends.delistings, {**securities, **ends.securities},
                                         {**sec_cusips, **ends.cusips}, ftd, ftd_lo, overrides))
    distress = _distress(ctx, delistings, {**sec_cusips, **ends.cusips}, ftd, review)              # 9e
    overrides = _plan_values(overrides, distress)
    _log_role_refusals(ctx, delistings)
    # The handoff stage creates continuation delistings (AON 2012) and sets successors: the clip and the ranges read
    # the starts and endings of the final delistings. (The first pass above only decides which stage-9 delistings
    # are self-successor continuations, before the handoff stage.)
    starts = _successor_starts(delistings, securities, search.sightings, sec_cusips, ftd, added)
    endings = _delisting_endings(delistings, securities, sec_cusips, ftd, starts)

    # 10. rows
    delisting_rows, review_rows = _delisting_rows(delistings, closes, payouts, overrides)
    review_rows += [item.row() for item in review]
    th_rows, ch_rows, ends, end_confirmed, listed = _history_rows(ctx, securities, search, sec_cusips, ftd, added,
                                                                  endings, starts)
    review_rows += [item.row() for item in drop_resolved_shared(ticker_range_review(th_rows), handoffs.resolved_pairs)]
    # 10c2. observation_map rows (the payout rows, 10c, are built with the tables below)
    map_rows = _observation_map(ctx, index, eras, resolutions, answers.issuers, sec_cusips, ftd, ends,
                                end_confirmed, listed, th_rows)
    flags, triaged = _triage(ctx, review_rows, review_decisions, limit)

    tables = {
        "securities": [s.row() for s in securities.values()] + [a.security.row() for a in added.values()],
        "ticker_history": th_rows,
        "cusip_history": ch_rows,
        "delistings": delisting_rows,
        "payouts": _payout_rows(payouts, delistings),
        "review": triaged.review_rows,
        "review_summary": triaged.summary_rows,
        "observation_map": map_rows,
    }
    evidence = _ticker_evidence(ctx, securities, answers)                                          # 10e
    verdicts = decide_verdicts(_as_read(tables), evidence)                                         # 10f
    tables["uncertain"] = verdicts.uncertain_rows()
    # an acquirer the run added that R1 made a merger row's successor is in the contract's history (Sinclair Inc)
    successor_ids = set(successors.added) | set(r1.added) | {sid for sid, _ in r1.links.values()}
    tables.update(_contract(ctx, _as_read(tables), verdicts, payouts, successor_ids, overrides,
                            id_baseline, {**_era_renames(eras, resolutions, answers.issuers), **lines.renames},
                            rows_decided, distress=distress))                                       # 10g
    card = _scorecard(ctx, _as_read(tables), scorecard, limit)                                     # 10h

    # 11. write -- every table formatted and written to its temp file first, so
    # a failure in any leaves every previous table; then renamed into place one
    # at a time (store.write_tables). scorecard.json and the manifest follow.
    counts = write_tables(out_dir, tables)
    run_scorecard.write(out_dir, card)
    stat_counts, stat_timings = SEC_STATS.since(run_mark)
    run_manifest.write(out_dir, run_manifest.build(as_of=ctx.as_of, sec_workers=sec_workers, counts=stat_counts,
                                                   timings=stat_timings, stages=ctx.meter.stages,
                                                   review_flags=dict(flags), review=triaged.counts,
                                                   handoffs=handoffs.counts))
    return RunSummary(counts, dict(Counter(e.record.bucket.value for e in delistings)),
                      dict(Counter(s.figi_source for s in securities.values())), dict(flags), dict(triaged.counts),
                      scorecard_drops=card["drops"], golden_failures=card["golden_failures"],
                      uncertain=verdicts.counts())


def default_clients(index: ObservationIndex, *, cache_dir: Path, rename_map: dict | None = None,
                    manual_overrides: dict | None = None, extract_payouts: bool = True,
                    extract_llm: bool = False, llm_model: str | None = None, use_midas: bool = True,
                    use_halts: bool = True, as_of: date | None = None) -> Clients:
    """The production clients. Every client is dated `as_of` (default: today,
    read once here), the resolver batches its memo writes and finds its name
    candidates in SEC's cik-lookup-data.txt (`cik_lookup.CikLookupClient`, loaded
    on first use), and the SEC limit is made machine-wide
    (sec_limiter.use_machine_wide_limit)."""
    from .cik_lookup import CikLookupClient
    from .classifier import DelistClassifier
    from .edgar import EdgarClient
    from .sec_limiter import use_machine_wide_limit
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
                              batch_writes=True,
                              # the name tier searches SEC's cik-lookup-data.txt, not the live company search
                              name_index=CikLookupClient(cache_dir / "sec_data" / "cik_lookup").index)
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

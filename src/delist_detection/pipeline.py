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

from . import acquirer_line
from . import manifest as run_manifest
from . import scorecard as run_scorecard
from .added_securities import AddedAcquirer, AddedLineSuccessor, AddedSecurity, AddedSuccessor
from .crsp_codes import CrspBucket
from .continuation_evidence import needs_doubt_check, needs_filing, read_continuation
from .degraded import DegradedWatch, degraded_item, flag_degraded, report_halt_feed_failures
from .delistings import LATE_ROW_DAYS, Delisting, DelistingFinder, SecurityContext
from .distress import (
    BANKRUPTCY_WORDS, OTC_SYMBOL_DAYS, DistressTerms, otc_symbol_from_fails, otc_symbol_from_text, plan_ratio,
    new_cusips as plan_new_cusips, price_only, substitutes_new_shares,
)
from .evidence import item_sections
from .fatal import FATAL
from .handoffs import (
    HandoffDecision, HandoffOutcome, apply_handoffs, continuation_filing, cusip_switch, decide_handoff,
    drop_resolved_shared, find_handoffs, issuer_carries_on, own_continuation_filing, predecessor_names,
)
from .figi_resolution import class_letter, is_placeholder, share_class_from_name
from .form25 import ISSUER_FORM25_FORMS, SecurityRef, letter_hint
from .issuer_record import IssuerRecord, ReadWatch
from .last_trade import Dating, OwnTrading, end_day, first_day_after
from .ftd import FTD_START, FtdIndex, FtdRow, close_age, is_trading_symbol, trades_after
from .history import (
    Histories, Sighting, backfill_cusips, cusip_sightings, filtered_ticker_sightings, observation_map_rows,
    own_last_seen, ranges_from_sightings, ticker_on, ticker_range_review, ticker_sightings, value_on,
)
from .line_follow import LineSuccessor, composites, follow_lines, is_line_symbol, text_cusips
from .identity import Identity, identify
from .listing_status import issuer_exchange, listed_today, listing_answers
from .observations import Observation, ObservationIndex, TickerEra, observation_conflicts
from .exchange_terms import one_share_no_cash
from .own_shares import OwnShares, Reader, new_issuer
from .own_shares import of as own_shares_of
from .merger_value import MergerValues, value_mergers
from .payout_gate import DEFAULT_TOL
from .prefetch import Serialized, warm
from .reconstruction import (
    OverrideFileError, build_delistings_table, delisting_row, for_delisting, override_row_name,
    unmatched_override_keys,
)
from .review_triage import Decision, ReviewItem, Triage, flag_name, is_blank, merge_review_rows, triage
from .rewrites import (
    LINE_CONTINUATION, R1_CONTINUATION, Rule, awaits_successor, continuation, is_real_ending, mark_going_on, reclassify,
    rewrite_by, successor_note,
)
from .sec_stats import SEC_STATS
from .security_master import EraResolution, Issuer, Security, cik_of, cusip_job, superseded_placeholders
from .lifecycle import Tables
from .ticker_evidence import EraEvidence, evidence_for
from .store import DelistingKey, formatted, write_tables
from .filing_search import successor_query
from .successors import (
    SUCCESSOR_AFTER_DAYS, SUCCESSOR_BEFORE_DAYS, SecurityStart, successor_by_terms,
    successor_from_8k12b, successor_in_run, successor_search_args, successor_search_name,
)
from .verdict import Verdicts
from .verdict_rules import Reading
from .verdict import decide as decide_verdicts
from .contract import delisting_rows as contract_delisting_rows
from .contract import id_change_rows, last_endings, payout_leg_rows, security_history_rows, seed_rows
from .issuer_in_force import Sighting as IssuerSighting
from .issuer_in_force import issuer_changes
from .price_requests import PriceAnswers, request_rows


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
    issuers: IssuerRecord | None = None     # the run's issuer record (None: the resolver's or classifier's)

    def __post_init__(self) -> None:
        """The run's issuer record: the one the resolver and the classifier read through, so a run reads each
        issuer once and reports every failed read one way; a new one over `edgar` when neither holds one (a test
        double)."""
        if self.issuers is None:
            held = (getattr(self.resolver, "issuers", None), getattr(self.classifier, "issuers", None))
            self.issuers = next((r for r in held if isinstance(r, IssuerRecord)), None) \
                or IssuerRecord(self.edgar, today=self.as_of)


@dataclass
class Overrides:
    """The caller's own input files, as read: nothing a stage derives is written back into them (a price answer
    reaches a stage through the request it answers, `price_requests.PriceAnswers`)."""
    last_trade_closes: dict = field(default_factory=dict)
    merger_terms: dict = field(default_factory=dict)
    recoveries: dict = field(default_factory=dict)
    price_answers: dict = field(default_factory=dict)      # price_requests.PriceKey -> price (--price-answers)


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
    sequential finder's twin: a copy of the run's classifier reading issuers through
    a shadow of its issuer record (`IssuerRecord.shadow`), and the run's own MIDAS
    and Nasdaq-halt clients, each behind one lock shared by every warm finder. It
    therefore takes the same last-trade anchors and asks for what the sequential
    pass will. A security whose batched OpenFIGI answer is missing is skipped: the
    sequential pass asks OpenFIGI for it alone, and its listing status decides what
    the finder reads."""
    midas = Serialized(clients.midas) if clients.midas is not None else None
    halts = Serialized(clients.halts) if clients.halts is not None else None

    def make_finder() -> DelistingFinder:
        classifier = copy.copy(clients.classifier)
        if isinstance(getattr(classifier, "issuers", None), IssuerRecord):
            classifier.issuers = classifier.issuers.shadow()
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


def _context_builder(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
                     ftd: FtdIndex, sec_cusips: dict[str, list[str]], other_ciks: Mapping[str, int] = {}, *,
                     resolution_source: Callable[[Security], str] | None = None
                     ) -> Callable[[Security, bool | None], SecurityContext]:
    """The finder's `SecurityContext` for a security of the run, given whether it
    is listed today; `resolution_source`: the lookup tier that found each security's issuer
    (`identity.Identity.resolution_source`; none: "security_master")."""
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
            resolution_source=resolution_source(s) if resolution_source is not None else "security_master",
            ftd_seen_after=lambda day, sig=sig, own=s.own_tickers(): any(
                x.day > day for x in sig if x.source == "ftd" and x.value in own),
            trading=OwnTrading(sig, frozenset(sec_cusips.get(s.sec_id, [])), rows, ftd),
            cusip_switches=_cusip_switches(s, ftd, sec_cusips.get(s.sec_id, [])),
            trades_after=lambda day, rows=rows: trades_after(rows, day),
            cusip_rows_near=lambda day, rows=rows: _rows_near(rows, day),
            other_cik=other_ciks.get(s.sec_id),
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
                     ftd: FtdIndex, resolution_source: Callable[[Security], str], moved_on: Collection[str] = (),
                     other_ciks: Mapping[str, int] = {}) -> _DelistingSearch:
    """5. Every delisting of every security (`DelistingFinder`), in sec_id order.
    A security whose search fails becomes an `error` review item, not an aborted
    run; only a fatal exception (`fatal.FATAL`) stops it. A FIGI line another
    composite continues (`moved_on`: stage 4b's line successors) is not listed
    today: its line went on under that composite. `other_ciks` (stage 4c, R5): the
    other CIK in force over a security's whole span, whose Form 25s are read too. `resolution_source`: the lookup
    tier that found each security's issuer (`Identity.resolution_source`), for its delistings' rows."""
    clients, log = ctx.clients, ctx.log
    finder = DelistingFinder(clients.edgar, clients.classifier, midas=clients.midas, halts=clients.halts)
    delistings: list[Delisting] = []
    listed: dict[str, bool | None] = {}
    review: list[ReviewItem] = []
    sightings = {sid: ticker_sightings(s, ftd, sec_cusips[sid]) for sid, s in securities.items()}
    security_context = _context_builder(securities, sightings, ftd, sec_cusips, other_ciks,
                                        resolution_source=resolution_source)

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
        if not is_real_ending(e):
            continue
        day = e.anchor.isoformat()
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
        end_on = date.fromisoformat(end)
        lo, hi = end_on - timedelta(days=BACKFILL_DAYS), end_on + timedelta(days=10)
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


def _last_trade_closes(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                       sec_cusips: dict[str, list[str]], ftd: FtdIndex, ftd_lo: date,
                       overrides: Overrides, answers: PriceAnswers = PriceAnswers()) -> dict[DelistingKey, float]:
    """7. Each delisting's last-trade close: a --last-trade-closes row, else the
    caller's answer to its last_close request (`answers`; a close given both ways
    stops the run), else the FTD close of its last trade day (by the security's
    CUSIP on that day, then its ticker), flagging the delisting where none is
    found or it is lagged or older. The FTD rows were loaded from the eras' first
    sighting on; a delisting whose last trade came earlier (a stale snapshot
    listed the security after it was gone) needs the rows around that day first."""
    answered = answers.last_closes(delistings, overrides.last_trade_closes)
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
        if given is None:
            given = answered.get(key)
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


def _merger_values(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                   sec_cusips: dict[str, list[str]], ftd: FtdIndex, closes: dict[DelistingKey, float],
                   overrides: Overrides, answers: PriceAnswers, tol: float,
                   sightings: Mapping[str, Sequence[Sighting]], ftd_lo: date | None) -> MergerValues:
    """8. What one share of each merger ending became (`merger_value.value_mergers`: the payout reads, the acquirer
    lines and names, the payout gate, the acquirer securities and the stock legs' price requests), metered as
    "payouts"; the resolver's memo is written after (the acquirer lookups resolved tickers)."""
    mark = ctx.meter.start()
    values = value_mergers(delistings, acquirer_line.LineIndex(securities, sightings, sec_cusips, ftd),
                           clients=ctx.clients, closes=closes, caller_terms=overrides.merger_terms, answers=answers,
                           tol=tol, ftd_lo=ftd_lo, workers=ctx.sec_workers, log=ctx.log)
    _flush_memo(ctx.clients)
    ctx.meter.done("payouts", mark)
    return values


R1_REBUCKETED = "r1_rebucketed"
BY_TERMS, BY_OWN_REGISTRATION = "terms", "own_registration"


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


def _reader(clients: Clients) -> Reader:
    """The own-share reader over the run's EDGAR client and issuer record (`own_shares.Reader`)."""
    return Reader(clients.edgar, clients.issuers)


@dataclass
class _R1:
    """Stage 8b's answer: the merger rows it rewrote as continuations (by delisting: the successor and how it was
    found), the successors it adds as securities of their own, and its review items."""
    links: dict[DelistingKey, tuple[str, str]] = field(default_factory=dict)
    added: dict[str, AddedSecurity] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)


def _r1_successor(ctx: _RunContext, e: Delisting, sec: Security, own: OwnShares, day: date,
                  starts: dict[str, SecurityStart], securities: dict[str, Security],
                  added: Mapping[str, AddedSecurity], out: _R1,
                  pending: dict[str, AddedSecurity]) -> tuple[str, str] | None:
    """The successor of a merger row R1 rewrites: a security of the run (`successors.successor_by_terms`), else
    the new issuer whose 8-K12B names the registrant (`successors.successor_from_8k12b`, its filer a new issuer,
    `own_shares.new_issuer`, and named by the R1 statement's target, the name tie `OwnShares.names_target`), to be
    added as a security of its own (`AddedSuccessor`, seen from the day after `day`) in `pending`: the caller adds it
    once the reading is known not to be degraded. Issuers' first filings and names come from the run's issuer
    record."""
    issuers = ctx.clients.issuers
    link = successor_by_terms(e, own.statement, day, starts, issuers=issuers)
    search = getattr(ctx.clients.edgar, "full_text_search", None)
    if link is not None or search is None:
        return link
    hit = successor_from_8k12b(search, ctx.clients.figi, name=successor_search_name(ctx.clients.edgar, e.cik, sec.name),
                               day=day, exclude_cik=e.cik, share_class=sec.share_class, edgar=ctx.clients.edgar,
                               own_tickers=sec.own_tickers() | {e.ticker})
    if hit is None:
        return None
    s_cik, cand, filed = hit
    if not new_issuer(issuers.first_filed(s_cik), day):
        return None
    if not own.names_target(issuers.names(s_cik), {cand.ticker}):
        return None
    if cand.composite not in securities and cand.composite not in added:
        not_before = first_day_after(day).isoformat()
        pending.setdefault(cand.composite, AddedSuccessor(
            Security(cand.composite, s_cik, share_class_from_name(cand.name), cand.name, cand.security_type, False,
                     "ticker"), cand.ticker, max(filed or not_before, not_before)))
    return cand.composite, BY_TERMS


def _r1_continuations(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                      sightings: dict[str, list[Sighting]], values: MergerValues) -> _R1:
    """8b. A merger that ruling R1 makes a continuation (sub-plan 5c): its published terms are one share and no
    cash (a special dividend is no cash: operator ruling 2026-10-04, `OwnShares.consideration`), no --merger-terms
    row decides it, the registrant's own filings say the same of its own shares (the ending's own-share reading,
    `own_shares.of`: a multi-step deal's intermediate one-for-one, Jefferies 2013, has the LLM's 0.81 against it),
    and the holders' new shares are a new issuer's or the same issuer's (`_r1_successor`). The row becomes an
    exchange transfer (304) to that successor, flagged `r1_continuation`, its payout reads dropped (a continuation
    has no value):
    `rewrites.continuation`, `Rule.R1`, with the run's merger values; an `r1_rebucketed` review item keeps its old
    bucket. An existing acquirer is never a continuation (LVNTA
    into GCI Liberty, Towers Watson into Willis, Waste Connections into Progressive Waste). The terms are stage 8's
    reading (`MergerValues.read_terms`: none for a merger the caller gave terms for). A reading that rested on a
    failed or stale read (the issuer record's, or any other SEC read's, now or when the reading was made) keeps the
    merger, flagged degraded."""
    out = _R1()
    mark = ctx.meter.start()
    starts = _starts(securities, sightings, values.added)
    for e in delistings:
        if e.record.bucket is not CrspBucket.MERGER or e.sec_id not in securities:
            continue
        terms = values.read_terms(e.key)
        if terms is None or not one_share_no_cash(terms[1], None):
            continue
        watch = ctx.clients.issuers.watch()
        sec = securities[e.sec_id]
        own = own_shares_of(e, _reader(ctx.clients), sec)
        link, pending = None, {}
        if own.one_for_one and one_share_no_cash(terms[1], own.consideration(terms[0])):
            link = _r1_successor(ctx, e, sec, own, e.anchor, starts, securities, values.added, out, pending)
        if watch.tripped() or own.degraded:
            watch_item = degraded_item(e.sec_id, e.ticker, e.cik, "the R1 reading", delist_date=e.delist_date)
            out.review.append(watch_item)
            flag_degraded(e)
            continue
        if link is None:
            continue
        out.added.update(pending)
        sid, how = link
        old = (e.record.bucket.value, e.record.crsp_code, e.record.reason)
        continuation(e, sid, Rule.R1, confidence="medium", flag=R1_CONTINUATION, how=how,
                     evidence=own.statement.sentence[:300], payouts=values,
                     reason=f"Continuation (R1): each share became one {own.statement.target[:80].strip(' ,')}, "
                            "no cash" + successor_note(how))
        out.links[e.key] = link
        out.review.append(ReviewItem(e.sec_id, e.ticker, e.cik, R1_REBUCKETED,
                                     f"was {old[0]} (CRSP {old[1]}: {old[2]}); R1 makes it a continuation into {sid}",
                                     delist_date=e.delist_date))
    ctx.log(f"R1 continuations: {len(out.links)} merger rows ({', '.join(sorted(k.sec_id for k in out.links))})")
    ctx.meter.done("R1 continuations", mark)
    return out


LINE_FOLLOW = "line_follow"


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
    whose anchor (`Delisting.anchor`: its last trade, else its Form 25 filing date) lies within [-SUCCESSOR_BEFORE_DAYS,
    +SUCCESSOR_AFTER_DAYS] days of the step's first row, takes that composite as its successor; an `unknown` row
    becomes the continuation. The composite is added as a security of its own (`AddedLineSuccessor`) when the run
    has none, and only for a delisting that takes it."""
    for e in delistings:
        ls = line_successors.get(e.sec_id)
        if ls is None or not (awaits_successor(e) or e.record.bucket is CrspBucket.UNKNOWN):
            continue
        day = e.anchor
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


def _own_registration_link(ctx: _RunContext, e: Delisting, texts: Sequence[str], day: date,
                           securities: dict[str, Security], sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                           taken: Collection[str], found: _Successors) -> tuple[str, str] | None:
    """Sub-plan 5c, rule 4 under the same CIK: the registrant's own successor registration (8-K12B/8-K12G3 in its
    filing list, `handoffs.own_continuation_filing`) moved the holders, one for one, to a new CUSIP -- the one the
    texts name (the ending's own-share reading's, `OwnShares.texts`) that is not the security's own (ONEOK 2026's
    notice: "ONEOK, Inc. (New, CUSIP: 30609A109)"), else the first fails row's under one of its tickers in [day, day
    + SUCCESSOR_AFTER_DAYS] (Clear Channel Outdoor
    2019's 18453H106). R2 on that CUSIP's one US composite: the security's own is the security going on (it is its
    own successor); another is its successor, added as a security of its own (`AddedLineSuccessor`) when the run
    has none. Several composites or an OpenFIGI error: no link."""
    if own_continuation_filing(ctx.clients.issuers.filings(e.cik), day) is None:
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
            (e.ticker, first_day_after(day).isoformat())
        found.added[x.composite] = AddedLineSuccessor(
            Security(x.composite, e.cik, share_class_from_name(x.name), x.name, x.security_type, False, "cusip"),
            symbol, first, new_rows)
    return x.composite, BY_OWN_REGISTRATION


def _terms_links(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                 starts: dict[str, SecurityStart], sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                 taken: Collection[str], found: _Successors) -> None:
    """Sub-plan 5c, rules 3 and 4: an exchange transfer still without a successor whose registrant's filings
    state each share of its class became one share, with no cash (R1: the ending's own-share reading,
    `own_shares.of`), takes the security of the run that statement names
    (`successors.successor_by_terms`: the same issuer's other class, CMCSK into CMCSA, HUB-B into HUBB, CWENA
    into CWEN; a new issuer's, BHI into BHGE, HHC into HHH), else the line its own successor registration moved
    the holders to (`_own_registration_link`: CCO 2019, OKE 2026). The link's `how` is "terms" or
    "own_registration". A reading that rested on a failed or stale read is flagged degraded."""
    for e in delistings:
        if e.key in found.links or not awaits_successor(e) or e.sec_id not in securities:
            continue
        issuers = ctx.clients.issuers
        watch = issuers.watch()
        own = own_shares_of(e, _reader(ctx.clients), securities[e.sec_id])
        link = None
        if own.one_for_one:
            day = e.anchor
            link = successor_by_terms(e, own.statement, day, starts, issuers=issuers)
            if link is None:
                link = _own_registration_link(ctx, e, own.texts, day, securities, sec_cusips, ftd, taken,
                                              found)
        if watch.tripped() or own.degraded:
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
    the shares became, one for one. Then the answer is recorded on the
    delistings (`_link_successors`): stage 9 is this one call."""
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
        in_run = successor_in_run(e, starts) if awaits_successor(e) else None
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
                # to no earlier than the trading day after the ending's anchor (its last
                # trade, else its Form 25 filing date: `Delisting.anchor`).
                not_before = first_day_after(e.anchor).isoformat()
                fd = filing_date or day.isoformat()
                found.added[cand.composite] = AddedSuccessor(
                    Security(cand.composite, s_cik, share_class_from_name(cand.name), cand.name,
                             cand.security_type, False, "ticker"), cand.ticker, max(fd, not_before))
    ctx.meter.done("successor search", mark)
    _link_successors(delistings, found)
    return found


def _link_successors(delistings: list[Delisting], successors: _Successors) -> None:
    """Record stage 9's answer on the delistings, each link one rewrite (`rewrites.continuation`: `Rule.LINE_FOLLOW`
    for stage 4b's line successor, `Rule.SUCCESSOR_LINK` for the others): its successor (a security of the run also
    says how it was found, in the reason), an `unknown` row at the line's switch made the continuation
    (`line_continuation`, medium confidence as a handoff continuation without a successor filing); then
    `resolution_degraded` on the rows whose search was degraded."""
    for d in delistings:
        link = successors.links.get(d.key)
        if link is not None:
            sid, how = link
            rule = Rule.LINE_FOLLOW if how == LINE_FOLLOW else Rule.SUCCESSOR_LINK
            note = successor_note(how) if how is not None else ""
            reason = successors.rebucketed.get(d.key)
            if reason is not None:                  # an `unknown` row at the line's switch: the continuation
                continuation(d, sid, rule, reason=reason + note, confidence="medium", flag=LINE_CONTINUATION,
                             how=how or "")
            else:
                continuation(d, sid, rule, reason=d.record.reason + note if note else None, how=how or "")
        if d.key in successors.degraded:
            flag_degraded(d)


def _handoffs(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
              search: _DelistingSearch, sec_cusips: dict[str, list[str]], ftd: FtdIndex, values: MergerValues,
              review: list[ReviewItem], added: Mapping[str, AddedSecurity]) -> HandoffOutcome:
    """9b. First, each merger or exchange transfer that does not end its security (`Histories.going_on` over stage 9's
    delistings and successors, `added` the securities the run adds) goes on as itself (`rewrites.mark_going_on`: the
    DIS 2019, WRK 2018 holding-company reorganizations): here, once, so the handoffs see those rows as their own
    successors; the history is read again over the final delistings before the ranges.
    Then ticker handoffs (`handoffs.py`): every pair of securities of the run
    where one stops trading under a ticker and the other starts under it within
    days (`find_handoffs`, over the sightings `ticker_history` is built from:
    backfilled observations dropped), decided on the successor issuer's
    8-K12B/8-K12G3 (EDGAR full-text search, else its own filing list), else on timing and identity, else
    as a takeover by a line or an issuer that existed before (`decide_handoff`:
    the issuer's first EDGAR filing dates it), then acted on (`apply_handoffs`): a continuation's
    missing row is added, a successor or a ticker successor set, and the review
    items it resolves dropped. A merger whose value reconciled counts as reconciled (`MergerValues.reconciled`:
    not one share per share and no cash, R1, sub-plan 5f: SPB 2018); a merger the stage makes a continuation drops
    its value (`values`, through `rewrites.continuation`). The issuers' names, filing lists and first
    filings come from the run's issuer record: a pair whose search or decision rested on a failed or stale read
    (the issuer's first filing included) is decided without what could not be read and gets a
    `resolution_degraded` item. Returns the outcome; the caller adds its rows."""
    clients, edgar, issuers = ctx.clients, ctx.clients.edgar, ctx.clients.issuers
    fts = getattr(edgar, "full_text_search", None)
    sightings = {sid: filtered_ticker_sightings(sig, sec_cusips.get(sid, []), ftd)
                 for sid, sig in search.sightings.items()}
    pairs = find_handoffs(sightings)
    mark = ctx.meter.start()

    def filing_args(p, record: IssuerRecord) -> tuple[list[str], date, int] | None:
        a, b = securities[p.a], securities[p.b]
        if fts is None or b.issuer_cik is None:
            return None
        sub = record.profile(a.issuer_cik) if a.issuer_cik is not None else None
        return predecessor_names(sub, p.a_last, a.name), date.fromisoformat(p.b_first), b.issuer_cik

    def find_filing(p):
        args = filing_args(p, issuers)
        if args is not None:
            names, day, cik = args
            hit = next((f for n in names if (f := continuation_filing(fts, name=n, day=day, successor_cik=cik))),
                       None)
            if hit is not None:
                return hit
        b_cik = securities[p.b].issuer_cik
        if b_cik is None or issuer_carries_on(p, securities, first_seen):
            return None     # the filing names no predecessor: not for an A whose issuer went on in another line
        return own_continuation_filing(issuers.filings(b_cik), date.fromisoformat(p.b_first))

    if fts is not None and ctx.sec_workers > 1:
        def warm_search(record: IssuerRecord, p) -> None:
            args = filing_args(p, record)
            if args is not None:
                for n in args[0]:
                    fts(*successor_query(n, args[1]))
        warm(pairs, warm_search, workers=ctx.sec_workers, state=issuers.shadow, name="handoff search")
    first_seen = {sid: sig[0].day for sid, sig in sightings.items() if sig}

    decisions: list[HandoffDecision] = []
    degraded: list[ReviewItem] = []
    for p in pairs:
        watch = issuers.watch()
        filing = find_filing(p)
        a_cik, b_cik = securities[p.a].issuer_cik, securities[p.b].issuer_cik
        same = a_cik is not None and a_cik == b_cik
        since = None if same or b_cik is None else issuers.first_filed(b_cik)
        if watch.tripped():
            degraded.append(degraded_item(p.a, p.ticker, a_cik, f"the handoff search ({p.ticker} to {p.b})",
                                          last_seen=p.a_last))
        decision = decide_handoff(p, filing=filing, same_issuer=same,
                                  cusip_switch=cusip_switch(ftd, p, sec_cusips.get(p.a, []), sec_cusips.get(p.b, [])),
                                  issuer_carries_on=issuer_carries_on(p, securities, first_seen),
                                  b_issuer_since=since.isoformat() if since else None)
        if decision is not None:
            decisions.append(decision)
    ctx.meter.done("handoff search", mark)
    mark_going_on(delistings, _histories(ctx, delistings, securities, search, sec_cusips, ftd, added).going_on)
    reconciled = {e.key for e in delistings if values.reconciled(e.key)}
    outcome = apply_handoffs(decisions, delistings, securities, review, reconciled=reconciled, payouts=values)
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
                       resolution_source: Callable[[Security], str] | None,
                       delistings: Iterable[Delisting] = ()) -> _SuccessorEndings:
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
                _context_builder(world, sightings, ftd, cusips, resolution_source=resolution_source)(s, listed),
                fallback=False)
        except FATAL:
            raise
        except Exception as exc:  # one added successor must not abort the run
            ctx.log(f"{sid}: successor ending search ERROR {type(exc).__name__}: {exc}")
            out.review.append(ReviewItem(sid, a.ticker, cik, "error", f"{type(exc).__name__}: {exc}"))
            continue
        # a Form 25 filed within PREDECESSOR_FORM25_DAYS of the successor's first day removed its predecessor
        start = (date.fromisoformat(first) + timedelta(days=PREDECESSOR_FORM25_DAYS)).isoformat()
        endings = [d for d in found if is_real_ending(d)
                   and not (d.form25_sub is not None and d.form25_sub.filing_date <= start)]
        watch.report(out.review, degraded_item(sid, a.ticker, cik, "the successor ending search",
                                               "; run again once SEC answers"), endings)
        report_halt_feed_failures(out.review, endings)
        out.review += [r for r in found_review if r.filing is None or r.filing.accession not in owned]
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
    """9c. A continuation row the handoff stage built from an unmatched Form 25 carries its last sighting as its last
    trade day; the last trade module re-dates it from that Form 25's notice (`last_trade.Dating.from_notice`: a
    confirmed day before the successor's first sighting, the handoff rewrite's `successor_from`, and no later than
    the Form 25 effective date, `delist_date`). A read that rested on a failed request or a stale copy keeps the
    sighting and is reported as `resolution_degraded` (row and review item); a refusal (`fatal.FATAL`) stops the
    run."""
    mark = ctx.meter.start()
    dating = Dating(ctx.clients.edgar)
    redated = 0
    for d in added:
        handoff = rewrite_by(d, Rule.HANDOFF)
        watch = DegradedWatch()
        lt = dating.from_notice(d.cik, (d.record.evidence or {}).get("delist_filing"), d.last_trade,
                                before=handoff.successor_from if handoff is not None else "", effective=d.delist_date)
        if watch.tripped():
            watch.report_delisting(review, d, "the handoff row's Form 25 notice")
            continue
        if lt is d.last_trade:
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
       shares, the ending is a bankruptcy (code 470, or the notice says so: an unknown ending then becomes 470,
       `rewrites.reclassify`, `Rule.PLAN_BANKRUPTCY`), and
       the old line never traded off the exchange (`otc_symbol_from_fails` reads nothing). Its ratio, from the notice
       or the plan's 8-Ks (item 1.03 or 3.03, PLAN_BEFORE_DAYS/PLAN_AFTER_DAYS around the Form 25), makes the stock
       rule on the new line under the same ticker.
    2. The drop reason: a compliance failure (570, 580) whose removal the exchange stated for a price deficiency
       only (`price_only` on the exchange's Form 25 notice, else, without a Form 25, on the 3.01 items in
       [last trade - NOTICE_BEFORE_DAYS, last trade + REASON_AFTER_DAYS]) is CRSP 552 (`Rule.PRICE_DEFICIENCY`).
       An issuer's own Form 25 (a
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
        last = end_day(d.last_trade, d.delist_date)
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
                reclassify(d, 470, Rule.PLAN_BANKRUPTCY, confidence="medium",
                           reason=f"Bankruptcy plan exchange (Form 25 {d.form25.filing_date} notice: the class came "
                                  f"to evidence new shares)")
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
                reclassify(d, PRICE_CODE, Rule.PRICE_DEFICIENCY,
                           reason=rec.reason + " (its stated reason: a price deficiency)")
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


def _delisting_rows(delistings: list[Delisting], closes: dict[DelistingKey, float], values: MergerValues,
                    overrides: Overrides, answers: PriceAnswers,
                    distress: Mapping[DelistingKey, DistressTerms]) -> tuple[list[dict], list[dict]]:
    """10a. The delistings.csv rows, and the review rows of those delistings that
    carry a flag or no DLRET. A merger's inputs are stage 8's record
    (`MergerValues.table_inputs`); a drop's first OTC print and a bankruptcy plan's
    value (ruling R6, stage 9e's ratio times the new line's close) are the
    caller's answers to their requests (`PriceAnswers.ending_values`), so a second
    run with the answers changes values only."""
    otc_prints, plan_values = {}, {}
    for e in delistings:
        otc, plan = answers.ending_values(e.sec_id, e.last_trade.day, distress.get(e.key))
        if otc is not None:
            otc_prints[e.key] = otc
        if plan is not None:
            plan_values[e.key] = plan
    table = build_delistings_table(
        [e.record for e in delistings], last_trade_closes=closes, exchanges={e.key: e.exchange for e in delistings},
        recovery_ratios=overrides.recoveries, otc_prints=otc_prints, plan_values=plan_values,
        **values.table_inputs(),
    )
    delisting_by_key = {e.key: e for e in delistings}
    delisting_rows, review_rows = [], []
    for enriched in table:
        e = delisting_by_key[DelistingKey(enriched.sec_id, enriched.delist_date)]
        v = values.get(e.key)
        pr = v.raw if v is not None else None
        delisting_rows.append(delisting_row(
            enriched, exchange=e.exchange or None,
            last_trade_date=e.last_trade.day.isoformat() if e.last_trade.day else None,
            last_trade_date_source=e.last_trade.source or None,
            successor_sec_id=e.record.successor_sec_id,
            ticker_successor_sec_id=e.record.ticker_successor_sec_id,
            acquirer_sec_id=(v.acquirer_sec_id or None) if v is not None else None,
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


def _histories(ctx: _RunContext, delistings: Iterable[Delisting], securities: dict[str, Security],
               search: _DelistingSearch, sec_cusips: dict[str, list[str]], ftd: FtdIndex,
               added: Mapping[str, AddedSecurity]) -> Histories:
    """The observed securities' histories over these delistings (`history.Histories`, over each delisting's
    `Delisting.ending`): the stage 5 sightings and listed-today answers, the securities the run adds, and the
    exchange EDGAR lists today for an open range's ticker (the issuer's submissions JSON, already cached by the
    finder)."""
    edgar = ctx.clients.edgar
    return Histories(securities, search.sightings, sec_cusips, ftd, [d.ending for d in delistings],
                     listed=search.listed, added=added,
                     exchange_today=lambda s, ticker: issuer_exchange(edgar, s.issuer_cik, ticker))


def _history_rows(ctx: _RunContext, history: Histories,
                  added: dict[str, AddedSecurity]) -> tuple[list[dict], list[dict]]:
    """10b. The ticker_history and cusip_history rows: each observed security's ranges as its history answers them
    (`Histories.ticker_rows`/`cusip_rows`: up to the end day of the last delisting that ends it, unless it is listed
    today), then one ticker row for each security the run adds, built directly (`AddedSecurity.history_row`:
    `ranges_from_sightings`' filter that drops single-value FTD sightings would otherwise drop a successor's lone
    8-K12B-dated sighting), open while OpenFIGI and EDGAR list it today."""
    clients = ctx.clients
    th_rows = list(history.ticker_rows)
    for sid, a in added.items():
        is_listed = bool(listed_today(clients.figi, sid, edgar=clients.edgar, cik=a.security.issuer_cik,
                                      tickers=[a.ticker]))
        exch = issuer_exchange(clients.edgar, a.security.issuer_cik, a.ticker) if is_listed else None
        th_rows.append(a.history_row(listed=is_listed, exchange=exch))
    return th_rows, list(history.cusip_rows)


def _observation_map(ctx: _RunContext, index: ObservationIndex, eras: list[TickerEra],
                     resolutions: dict[str, EraResolution], issuers: dict[str, Issuer],
                     history: Histories) -> list[dict]:
    """10c2. observation_map.csv's rows (`history.observation_map_rows`): every
    observation of the run's eras (`--limit` already trims which ones), its
    era, sec_id, issuer CIK, `ticker_history` spelling/coverage on its date,
    and status, read from the history's own answer. The log names how many of the input's observations that is,
    so a `--limit` subset's smaller count is not mistaken for a bug."""
    sec_id_of = {k: r.sec_id for k, r in resolutions.items()}
    issuer_cik_of = {k: cik_of(issuers, k) for k in resolutions}
    conflicts = [(t, d) for t, d, _ in observation_conflicts(o for e in eras for o in e.observations)]
    rows = observation_map_rows(eras, sec_id_of, issuer_cik_of, history, conflicts)
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


def _continuation_filings(ctx: _RunContext, delistings: list[Delisting], securities: Mapping[str, Security],
                          review: list[ReviewItem], added: Mapping[str, AddedSecurity] | None = None
                          ) -> dict[DelistingKey, Reading]:
    """9g. Sub-plan 5i (spec ruling 2.3): what the registrant's own filings say of each continuation, for its
    verdict (10f) only (`continuation_evidence`, over the ending's own-share reading: the one the delisting carries
    when an earlier rule read it, CHTR 2016's and SIRI 2024's rule 6, else one made at its anchor, `own_shares.of`):
    the filing that confirms a continuation the continued-filings rule or the handoff stage's timing linked (an 8-K
    item 3.03 or an 8-K12B/8-K12G3 whose texts state the security's own exchange one for one, its target the
    registrant or the successor), and the ratio or cash that contradicts a successor registration. No row changes.
    A reading that rested on a failed request or a stale copy gives no reading and a `resolution_degraded` review
    item (not a flag on the row: the row itself does not rest on it); a refusal (`fatal.FATAL`) stops the run. Each
    confirmation is logged and recorded in run_manifest.json's `continuation_filings`."""
    mark = ctx.meter.start()
    names = {sid: s.name or "" for sid, s in securities.items()}
    names.update({sid: a.security.name or "" for sid, a in (added or {}).items()})
    out: dict[DelistingKey, Reading] = {}
    for d in delistings:
        rec, sec = d.record, securities.get(d.sec_id)
        reason = rec.reason or ""
        if sec is None or not (needs_filing(reason, d.sec_id, rec.successor_sec_id)
                               or needs_doubt_check(reason, d.sec_id, rec.successor_sec_id)):
            continue
        watch = DegradedWatch()
        own = own_shares_of(d, _reader(ctx.clients), sec)
        found = read_continuation(own, reason, d.sec_id, rec.successor_sec_id,
                                  [names.get(rec.successor_sec_id or "", "")])
        if watch.tripped() or own.degraded:
            review.append(degraded_item(d.sec_id, d.ticker, d.cik, "the continuation's confirming filing (stage 9g)",
                                        delist_date=d.delist_date))
        elif found.filing or found.doubt:
            out[d.key] = found
            ctx.log(f"continuation reading: {d.sec_id} {d.delist_date} "
                    f"{'confirmed by ' + found.filing if found.filing else 'doubted: ' + found.doubt}")
    ctx.log(f"continuation readings: {sum(bool(r.filing) for r in out.values())} confirmed, "
            f"{sum(bool(r.doubt) for r in out.values())} contradicted")
    ctx.meter.done("continuation readings", mark)
    return out


def _ticker_evidence(ctx: _RunContext, securities: dict[str, Security], tier: Callable[[str], str]) -> dict[str, str]:
    """10e. What ties each placeholder's ticker to its CIK (decision 1;
    ticker_evidence.evidence_for): a resolver tier that names the ticker (`tier`: each era's, by era key,
    `Identity.tier`), else
    a full-text hit in the CIK's own filings. A client without full-text
    search (a test double) gives every other placeholder no evidence."""
    search = getattr(ctx.clients.edgar, "full_text_search", None)
    mark = ctx.meter.start()
    out = {s.sec_id: evidence_for(s.issuer_cik,
                                  [EraEvidence(e.ticker, e.first, e.last, tier(e.key)) for e in s.eras],
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


def _in_force_reads(issuers: IssuerRecord) -> tuple[Callable[[int], dict | None], ReadWatch]:
    """The submissions read `issuer_in_force` takes: the issuer's profile in the run's issuer record (None when it
    cannot be read; a CIK whose read failed in this stage is not asked again in it, as the stage reads one per
    sighting), and the watch over the stage's reads (`ciks`: each CIK whose answer failed or rested on a stale
    copy)."""
    reads = issuers.watch()

    def submissions(cik: int) -> dict | None:
        return None if cik in reads.failed else issuers.profile(cik)

    return submissions, reads


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
    read, reads = _in_force_reads(ctx.clients.issuers)
    exact_names = ctx.clients.issuers.exact_holders
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
        if s is not None and review is not None and touched & reads.ciks:
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
    (`fatal.FATAL`) stops the run. Without a name index (the run's issuer record
    holds none), every sighting keeps its era's CIK. A sighting of an era whose
    issuer its ticker's fails rows decided (`rows_decided`, stage 2b's
    `ticker_rows`) keeps its era's CIK too: its observed name is the one those
    rows refuted (ERA 2013's BRISTOW GROUP INC)."""
    submissions, _ = _in_force_reads(ctx.clients.issuers)
    mark = ctx.meter.start()
    out = issuer_changes((IssuerSighting(r["sec_id"], r["as_of"], "" if r["era"] in rows_decided else r["name"],
                                         r["issuer_cik"])
                          for r in observation_map if r["sec_id"] and r["status"] != "conflict"),
                         submissions, ctx.clients.issuers.exact_holders)
    ctx.meter.done("issuers in force", mark)
    return out


def _contract(ctx: _RunContext, read: Tables, verdicts: Verdicts, values: MergerValues, successor_ids: set[str],
              answers: PriceAnswers, id_baseline: Sequence[Mapping[str, str]],
              renames: Mapping[str, str] = {}, rows_decided: Collection[str] = (),
              distress: Mapping[DelistingKey, DistressTerms] | None = None) -> dict[str, list[dict]]:
    """10g. The contract (contract.py), written under contract/ beside today's
    tables (decision 6): security_history with each interval's issuer in force
    (`_issuers_in_force`), leaving out the merger acquirers the run adds;
    delistings, one row per ended security (a drop's OTC symbol and a bankruptcy
    plan's ratio from stage 9e, `distress`); the seed echo; the price requests (a
    merger's stock leg as stage 8 asked it, a plan's new line, a basket's further
    legs; an answer to no request stops the run); and the placeholders of `id_baseline`
    (a securities.csv) that now hold a FIGI (`renames`: stage 4b's folds, by name,
    whatever other FIGI lines the issuer has)."""
    issuers = _issuers_in_force(ctx, read.observation_map, rows_decided)
    endings = last_endings(read.delistings)
    inputs = values.contract_inputs(list(endings.values()))
    ended = contract_delisting_rows(read, verdicts, inputs, distress)
    basket_rows = payout_leg_rows(read, inputs)
    requests = request_rows(ended, endings, values.requests(list(endings.values())), plans=distress,
                            leg_rows=basket_rows)
    answers.refuse_unrequested(requests)
    return {
        "security_history": security_history_rows(read, issuers, leave_out=set(values.added) - successor_ids),
        "contract_delistings": ended,
        "seeds": seed_rows(read, verdicts),
        "price_requests": requests,
        "id_changes": id_change_rows(id_baseline, read.securities, ctx.as_of.isoformat(), renames),
        "payout_legs": basket_rows,
    }


def _scorecard(ctx: _RunContext, read: Tables, config: run_scorecard.ScorecardConfig, limit: int | None,
               legs_rows: Sequence[Mapping[str, str]] | None = None) -> dict:
    """10h. The scorecard of the tables about to be written (`read`; `legs_rows`: contract/payout_legs.csv's rows,
    which the diagnosis judge reads), with
    `drops`: the floored numbers that got worse. A --limit subset sees a
    fraction of the universe, so its numbers are never compared to the floor."""
    card = run_scorecard.build(read, as_of=ctx.as_of, config=config, legs_rows=legs_rows)
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
    clients.issuers.forget()                  # one issuer record per run: each issuer is read afresh, once
    run_mark = SEC_STATS.snapshot()           # the manifest reports the traffic since here
    identity = identify(index, clients, as_of=ctx.as_of, limit=limit, log=log, workers=sec_workers,
                        meter=ctx.meter)                                                            # 1-4
    eras, ftd, ftd_lo = identity.eras, identity.ftd, identity.ftd_lo
    lines = follow_lines(identity, clients, as_of=ctx.as_of, log=log, meter=ctx.meter)              # 4b
    securities, resolutions, sec_cusips = lines.securities, lines.resolutions, lines.cusips
    review = list(lines.review)       # stages 1 to 4b's, a folded placeholder's on its FIGI line
    other_ciks = _other_issuers(ctx, eras, resolutions, identity.issuers, securities, review,
                                identity.rows_decided)                                              # 4c
    search = _find_delistings(ctx, securities, sec_cusips, ftd, identity.resolution_source, set(lines.successors),
                              other_ciks)                                                           # 5
    delistings = search.delistings
    review += search.review
    _dead_before_sighting(ctx, securities, delistings, sec_cusips, ftd, search.sightings, identity.issuers)  # 5b
    _check_overrides(overrides, delistings)                                                         # 6
    prices = PriceAnswers(overrides.price_answers)    # 6b: each stage reads the answer to its own request
    closes = _last_trade_closes(ctx, delistings, securities, sec_cusips, ftd, ftd_lo, overrides, prices)    # 7
    values = _merger_values(ctx, delistings, securities, sec_cusips, ftd, closes, overrides, prices, tol,
                            search.sightings, ftd_lo)                                               # 8
    review += values.review
    r1 = _r1_continuations(ctx, delistings, securities, search.sightings, values)                  # 8b
    review += r1.review
    successors = _find_successors(ctx, delistings, securities, search.sightings, {**values.added, **r1.added},
                                  lines.successors, ftd, sec_cusips)                                # 9
    review += successors.review
    added = {**values.added, **r1.added, **successors.added}     # the acquirers and successors the run adds
    handoffs = _handoffs(ctx, delistings, securities, search, sec_cusips, ftd, values, review, added)   # 9b
    review = handoffs.review
    _date_from_notices(ctx, handoffs.added, review)       # 9c: before the added rows' closes are read
    if handoffs.added:
        delistings += handoffs.added
        closes.update(_last_trade_closes(ctx, handoffs.added, securities, sec_cusips, ftd, ftd_lo, overrides,
                                         prices))
    ends = _successor_endings(ctx, search.finder, added, securities, sec_cusips, ftd, identity.resolution_source,
                              delistings)                                                           # 9d
    review += ends.review
    if ends.delistings:
        delistings += ends.delistings
        closes.update(_last_trade_closes(ctx, ends.delistings, {**securities, **ends.securities},
                                         {**sec_cusips, **ends.cusips}, ftd, ftd_lo, overrides, prices))
    distress = _distress(ctx, delistings, {**sec_cusips, **ends.cusips}, ftd, review)              # 9e
    confirmations = _continuation_filings(ctx, delistings, securities, review, added)             # 9g
    _log_role_refusals(ctx, delistings)
    # The history is read twice, one interface: stage 9b read it over stage 9's delistings, only to mark the ones that
    # go on as themselves before its handoffs; the handoff stage then creates continuations (AON 2012) and sets
    # successors, and 9c to 9e re-date, add and reclassify endings, so the ranges read it over the final delistings.
    history = _histories(ctx, delistings, securities, search, sec_cusips, ftd, added)

    # 10. rows
    delisting_rows, review_rows = _delisting_rows(delistings, closes, values, overrides, prices, distress)
    review_rows += [item.row() for item in review]
    th_rows, ch_rows = _history_rows(ctx, history, added)
    review_rows += [item.row() for item in drop_resolved_shared(ticker_range_review(th_rows), handoffs.resolved_pairs)]
    # 10c2. observation_map rows (the payout rows, 10c, are built with the tables below)
    map_rows = _observation_map(ctx, index, eras, resolutions, identity.issuers, history)
    flags, triaged = _triage(ctx, review_rows, review_decisions, limit)

    tables = {
        "securities": [s.row() for s in securities.values()] + [a.security.row() for a in added.values()],
        "ticker_history": th_rows,
        "cusip_history": ch_rows,
        "delistings": delisting_rows,
        "payouts": values.payout_rows({e.key: e.ticker for e in delistings}),
        "review": triaged.review_rows,
        "review_summary": triaged.summary_rows,
        "observation_map": map_rows,
    }
    evidence = _ticker_evidence(ctx, securities, identity.tier)                                    # 10e
    verdicts = decide_verdicts(_as_read(tables), evidence, confirmations)                          # 10f
    tables["uncertain"] = verdicts.uncertain_rows()
    # an acquirer the run added that R1 made a merger row's successor is in the contract's history (Sinclair Inc)
    successor_ids = set(successors.added) | set(r1.added) | {sid for sid, _ in r1.links.values()}
    tables.update(_contract(ctx, _as_read(tables), verdicts, values, successor_ids, prices,
                            id_baseline, {**identity.renames(resolutions), **lines.renames},
                            identity.rows_decided, distress=distress))                              # 10g
    card = _scorecard(ctx, _as_read(tables), scorecard, limit, formatted("payout_legs", tables["payout_legs"]))  # 10h

    # 11. write -- every table formatted and written to its temp file first, so
    # a failure in any leaves every previous table; then renamed into place one
    # at a time (store.write_tables). scorecard.json and the manifest follow.
    counts = write_tables(out_dir, tables)
    run_scorecard.write(out_dir, card)
    stat_counts, stat_timings = SEC_STATS.since(run_mark)
    run_manifest.write(out_dir, run_manifest.build(as_of=ctx.as_of, sec_workers=sec_workers, counts=stat_counts,
                                                   timings=stat_timings, stages=ctx.meter.stages,
                                                   review_flags=dict(flags), review=triaged.counts,
                                                   handoffs=handoffs.counts,
                                                   continuation_filings=[
                                                       {"sec_id": k.sec_id, "delist_date": k.delist_date,
                                                        "filing": r.filing} for k, r in sorted(confirmations.items())
                                                       if r.filing]))
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

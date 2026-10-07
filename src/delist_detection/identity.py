# src/delist_detection/identity.py
"""A security's identity: the run's stages 1 to 4 behind one interface (architecture step 6).

`identify(index, clients, as_of=...)` turns the caller's observations into the securities the rest of the run works
on, and answers what later stages read about who each one is (`Identity`):

1. the ticker eras (CONTEXT.md), built in one place: `observations.split_eras` splits each ticker's observations,
   then `refine_eras` splits them again on the SEC fails-to-deliver rows under the ticker, which this stage loads
   (`Identity.ftd`; later stages extend it);
2. each era's issuer CIK, asked at the era's last sighting (`era_last_seen`) with its own pin, name and first
   sighting: the issuer lookup's first pass (`IssuerLookup`, the memoized (ticker, date, observed name) -> CIK
   lookup), then stage 2b's check of a name-search answer against the era's span and its ticker's fails rows
   (`EraIssuers.check_names`), then the second pass for the eras left with no CIK and no pin (`EraIssuers.infer`),
   then each issuer's EDGAR names (the run's issuer record);
3. each era's FIGI (`security_master.FigiResolver` with its guards: the CUSIPs whose fails rows name the era's
   issuer, `candidate_cusips`; the CUSIP links between eras, `security_master.cusip_handoffs`, computed once and read
   by the second pass too; the eras whose ticker the fails data never shows, `guarded_eras`, or shows only as another
   security's, `foreign_ticker_eras`; a weak pick taken back out, `resolve_with_identity_guard`), the securities the
   eras resolve to (`build_securities`) and the identity review items;
4. each security's CUSIPs over its whole life, their fails rows loaded to the run date.

Its adapters: the issuer lookup (`ticker_resolver.TickerResolver`, or a double with the same five methods), the
run's issuer record (`issuer_record.IssuerRecord`: every read of an issuer's EDGAR record, one failed-read policy),
OpenFIGI (`map`, `filter`) and the fails client (`ftd.FtdClient`).

What later stages read from the answer: each era's lookup tier (`Identity.tier`) and each security's
(`Identity.resolution_source`), the eras whose ticker's fails rows decided their issuer (`Identity.rows_decided`:
stages 4c and 10g keep their CIK in force), the securities a changed set of resolutions gives
(`Identity.securities_of`: stage 4b's folds) and the placeholders one FIGI now holds (`Identity.renames`:
contract/id_changes.csv).

Invariants: a refusal (`fatal.FATAL`) stops the run; a 2b or second-pass answer is never saved (the lookup's memo
keeps the first pass's only), and each era's second-pass state is its own (`EraIssuers`); an era whose answer rested
on a failed request or a stale copy, or whose issuer's names could not be read, gets a `resolution_degraded` item;
with `workers` > 1 the warm passes only fill caches, so the answer is the same for any worker count."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Protocol

from .degraded import degraded_item
from .evidence import names_between, parse_day, renamed_near
from .figi_resolution import class_letter, is_placeholder, placeholder_id, share_class_from_name
from .ftd import FTD_START, FtdIndex, FtdRow
from .issuer_record import IssuerRecord
from .manifest import StageMeter
from .names import description_matches, description_names, names_agree, names_an_issuer
from .observations import (
    ERA_GAP_DAYS, Observation, ObservationError, ObservationIndex, TickerEra, eras_by_key, number_eras,
)
from .prefetch import warm
from .review_triage import ReviewItem
from .security_master import (
    EraResolution, FigiResolver, Handoff, Issuer, Security, build_securities, cik_of, cusip_handoffs,
    detached_review, foreign_ticker_eras, guarded_eras, issuers_by_era, observation_conflict_review,
    resolve_with_identity_guard, ticker_unconfirmed_review, trades_at_switch,
)
from .ticker_resolver import TickerResolution, TickerResolver

ERA_MIN_RUN = 3          # an FTD CUSIP run shorter than this is noise, not a CUSIP switch
ERA_MIN_ROWS = 3         # an era with fewer fails rows of its own gets no second-pass answer
GUARD_NAME_DAYS = 30     # a name the candidate took up to this long after a row's date can describe it
RENAME_NEAR_DAYS = 90    # a switch's issuer was renamed this close to it
NAME_IN_FORCE = "name_in_force"     # 2b's source: the one other holder of the name that carried it over the era
TICKER_ROWS = "ticker_rows"         # 2b's source: the one other holder of the name its ticker's fails rows describe
OBSERVED_ALIVE_DAYS = TickerResolver.OBSERVED_ALIVE_DAYS    # filed within this of a day: the issuer was operating
EXCHANGE_CIKS = TickerResolver.EXCHANGE_CIKS                # the exchanges' CIKs: never an issuer


class IssuerLookup(Protocol):
    """The memoized (ticker, date, observed name) -> CIK lookup `identify` asks (`ticker_resolver.TickerResolver`).
    `resolve` is its first pass, `is_degraded` whether an answer rested on a failed request or a stale copy,
    `frequency_candidates` its 8-K frequency tier's ranked candidates (CIK, name) for a ticker before a day and
    whether that search failed (the second pass's rule B reads them), `shadow` a copy for a warm pass, and `flush`
    writes its memo."""

    def resolve(self, ticker: str, observed_date: str | None = None, *, pin: Any = ..., name: Any = ...,
                since: str | None = None) -> TickerResolution: ...

    def is_degraded(self, ticker: str, observed_date: str | None = None, *, name: Any = ...) -> bool: ...

    def frequency_candidates(self, ticker: str, day: str) -> tuple[list[tuple[int, str]], bool]: ...

    def shadow(self) -> "IssuerLookup": ...

    def flush(self) -> None: ...


class Sources(Protocol):
    """What `identify` reads through (`pipeline.Clients` has it all)."""
    resolver: IssuerLookup
    issuers: IssuerRecord     # the run's issuer record (the lookup's own, in production)
    figi: Any                 # OpenFIGI: `map(jobs)`, `filter(query, **fields)`
    ftd_client: Any           # SEC's fails-to-deliver files (`ftd.FtdClient`)
    edgar: Any                # the EDGAR client whose cache the warm pass fills with the issuers' submissions


@dataclass
class Identity:
    """What `identify` answers: the refined eras (by key too), the fails index stage 1 loaded and stage 4 extended
    (`ftd`, from `ftd_lo`), each era's issuer (`issuers`, by era key, for the eras whose issuer is known: the one
    source of an era's CIK), each era's FIGI resolution, the securities, each security's CUSIPs over its whole life
    (`cusips`), the identity review items, each era's lookup tier (`tiers`: the first pass's, or the source of the
    2b or second-pass rule that answered it) and the eras whose ticker's fails rows decided their issuer
    (`rows_decided`, 2b's `ticker_rows`: their observed name was refuted, so the issuer in force keeps their CIK)."""
    eras: list[TickerEra]
    era_by_key: dict[str, TickerEra]
    ftd: FtdIndex
    ftd_lo: date
    issuers: dict[str, Issuer] = field(default_factory=dict)
    resolutions: dict[str, EraResolution] = field(default_factory=dict)
    securities: dict[str, Security] = field(default_factory=dict)
    cusips: dict[str, list[str]] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)
    tiers: dict[str, str] = field(default_factory=dict)
    rows_decided: frozenset[str] = frozenset()

    def tier(self, era_key: str) -> str:
        """The lookup tier that found the era's issuer CIK ("cik_map", "manual", "company_tickers", ...; a 2b or
        second-pass rule's source for an era one of them answered); "" for an era it was not asked about."""
        return self.tiers.get(era_key, "")

    def resolution_source(self, sec: Security) -> str:
        """The lookup tier that found the security's issuer CIK: that of its latest era whose issuer is known, the
        era `build_securities` takes `issuer_cik` from; "security_master" when none has one (the delistings'
        resolution_source)."""
        for e in reversed(sec.eras):
            if e.key in self.issuers:
                return self.tier(e.key) or "security_master"
        return "security_master"

    def securities_of(self, resolutions: Mapping[str, EraResolution]) -> dict[str, Security]:
        """The securities the eras' `resolutions` give, built as stage 3 builds them (`build_securities`), for a
        later stage that changed some (stage 4b folds a placeholder's eras into a FIGI line)."""
        return build_securities(resolutions, self.era_by_key, self.issuers)

    def renames(self, resolutions: Mapping[str, EraResolution]) -> dict[str, str]:
        """The placeholder each era of a known issuer would hold (its issuer and its name's class) -> the one FIGI its
        eras hold in `resolutions`, for contract/id_changes.csv: a placeholder stage 3 joined to its issuer's line
        across a class label (sub-plan 5h: MSG's CLASS A eras on MSG Networks' plain-named line) is a rename too. A
        placeholder whose eras hold two FIGIs, or that an era still holds, is no rename."""
        held: dict[str, set[str]] = defaultdict(set)
        kept = {r.sec_id for r in resolutions.values() if r.sec_id and is_placeholder(r.sec_id)}
        for e in self.eras:
            cik, r = cik_of(self.issuers, e.key), resolutions.get(e.key)
            if cik is None or r is None or not r.sec_id or is_placeholder(r.sec_id):
                continue
            held[placeholder_id(cik, share_class_from_name(e.name))].add(r.sec_id)
        return {p: next(iter(f)) for p, f in held.items() if len(f) == 1 and p not in kept}


def _quiet(*_: Any) -> None:
    return None


def identify(index: ObservationIndex, clients: Sources, *, as_of: date, limit: int | None = None,
             log: Callable[[str], None] = _quiet, workers: int = 1, meter: StageMeter | None = None) -> Identity:
    """Stages 1 to 4 over the observations of `index` (its first `limit` eras under `limit`), every window ending on
    the run date `as_of`; `log` takes one line per step, `meter` the SEC traffic of issuer resolution, and `workers`
    > 1 fills the EDGAR caches ahead on that many threads. Raises `ObservationError` when there is no observation;
    a refusal (`fatal.FATAL`) or an OpenFIGI outage stops it."""
    meter = meter if meter is not None else StageMeter(log)
    eras, era_by_key, ftd, ftd_lo = _refine(index, clients.ftd_client, as_of, limit, log)               # 1
    handoffs = cusip_handoffs(eras, ftd)        # the CUSIP links between the eras: the second pass and stage 3 read them
    found = _resolve_issuers(eras, ftd, handoffs, clients, log, workers, meter)                          # 2, 2b
    resolutions, securities, review = _resolve_securities(eras, era_by_key, ftd, handoffs, found, clients, log)  # 3
    cusips = _security_cusips(securities, resolutions, ftd, clients.ftd_client, ftd_lo, as_of)          # 4
    return Identity(eras, era_by_key, ftd, ftd_lo, found.issuers, resolutions, securities, cusips, review,
                    {k: r.source for k, r in found.answers.items()},
                    frozenset(k for k, v in found.inferred.items() if v.source == TICKER_ROWS))


def _refine(index: ObservationIndex, ftd_client: Any, as_of: date, limit: int | None,
            log: Callable[[str], None]) -> tuple[list[TickerEra], dict[str, TickerEra], FtdIndex, date]:
    """1. The observation eras, refined on SEC fails-to-deliver evidence: FTD rows
    for the eras' tickers are loaded first (they date each era's real last
    sighting), then each era is split further on that evidence (a CUSIP switch,
    or a gap no FTD row bridges). Every later step works on the refined eras.
    Returns them, by key too, the FTD index, and the first day it covers."""
    eras = index.eras()
    if limit:
        eras = eras[:limit]
    log(f"{len(eras)} ticker eras")

    if not eras:
        raise ObservationError("no observations to process")

    lo = max(FTD_START, min(date.fromisoformat(e.first) for e in eras) - timedelta(days=30))
    hi = min(as_of, max(date.fromisoformat(e.last) for e in eras) + timedelta(days=400))
    class_names: dict[str, list[str]] = defaultdict(list)     # BF-B's names: checks FTD's "BFB" rows
    first_seen: dict[str, str] = {}                            # each ticker's first day (rule A's base-symbol bound)
    for e in eras:
        first_seen[e.ticker] = min(e.first, first_seen.get(e.ticker, e.first))
        if "-" in e.ticker:
            class_names[e.ticker] += e.names
    ftd = FtdIndex.load(ftd_client, lo, hi, symbols={e.ticker for e in eras},
                        cusips={c for e in eras for c in e.cusips}, names=class_names, first_seen=first_seen)
    eras = refine_eras(eras, ftd)
    era_by_key = eras_by_key(eras)               # raises on a duplicate key: an era is never dropped
    log(f"{len(eras)} eras after the FTD split")
    return eras, era_by_key, ftd, lo


@dataclass
class _Issuers:
    """Stage 2's answer for each era: the lookup's (`answers`, by era key: the first pass's, or the 2b or second-pass
    answer that replaced it), its `Issuer` (`issuers`: CIK and EDGAR names, for the eras whose issuer is known), the
    era's last sighting the lookup was asked at, the issuer CIKs whose names read was degraded, the 2b and
    second-pass answers (`inferred`), the second pass's contradictions of first-pass answers (`disagreements`), and
    the eras whose 2b or second-pass reads rested on a failed request or a stale copy (`degraded`)."""
    answers: dict[str, TickerResolution]
    issuers: dict[str, Issuer]
    last_seen: dict[str, str]
    names_degraded: set[int]
    inferred: dict[str, InferredIssuer]
    disagreements: dict[str, InferredIssuer]
    degraded: set[str]


def _resolve_issuers(eras: list[TickerEra], ftd: FtdIndex, handoffs: Sequence[Handoff], clients: Sources,
                     log: Callable[[str], None], workers: int, meter: StageMeter) -> _Issuers:
    """2. The issuer CIK of each era, resolved at the era's last sighting (index
    snapshots can be months apart, and the lookup's Form 25 search is anchored
    on this date), with each era's own pin and name (a pin or name looked up by
    (ticker, date) can belong to a neighbouring era when the last sighting falls
    between the two: FTD rows of a shared CUSIP carry KORS@2012's last sighting
    past KORS@2014's first observation). The lookup tier that found it
    (cik_map, manual, company_tickers, ...) is kept for the delisting rows'
    resolution_source. Then 2b's check of the name-search answers, and the second pass
    (`EraIssuers.infer`, never saved) for the eras left with no CIK and no pin: a renamed issuer found by
    its 8-K frequency or by a CUSIP handoff. Then each issuer's EDGAR names
    (`IssuerRecord.names`), which stage 3 checks CUSIPs and FIGI names against:
    an issuer whose read failed has none (its eras are checked against their
    observed names only) and is reported degraded."""
    resolver, record = clients.resolver, clients.issuers
    last_seen = {e.key: era_last_seen(e, ftd) for e in eras}
    mark = meter.start()
    if workers > 1:
        # Warm the EDGAR caches: each era resolved on a worker thread by a shadow
        # lookup (a snapshot of this memo that saves nothing), its answer thrown
        # away. The resolve below then runs one era at a time, in order, on this
        # thread, and finds its requests answered.
        warm(eras, lambda shadow, e: shadow.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin, name=e.name,
                                                    since=e.first),
             workers=workers, state=resolver.shadow, name="issuer resolution")
    answers = {e.key: resolver.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin, name=e.name, since=e.first)
               for e in eras}
    resolver.flush()
    passes = EraIssuers(record, resolver.frequency_candidates)
    tickers = {e.key: e.ticker for e in eras}
    checked = passes.check_names(eras, ftd, last_seen, answers)                                          # 2b
    for key, found in checked.items():
        answers[key] = TickerResolution(tickers[key], found.cik, None, found.source)
    log(f"name checks: {len(checked)} name-search answers replaced"
        + (f" ({', '.join(f'{k} -> {v.cik}' for k, v in sorted(checked.items()))})" if checked else ""))
    second = passes.infer(eras, ftd, last_seen, {k: r.cik for k, r in answers.items()}, handoffs)
    for key, found in second.inferred.items():
        answers[key] = TickerResolution(tickers[key], found.cik, None, found.source)
    log(f"resolver's second pass: {len(second.inferred)} issuers inferred, "
        f"{len(second.disagreements)} first-pass answers its CUSIP evidence contradicts")
    ciks = {k: r.cik for k, r in answers.items()}
    issuer_ciks = [cik for cik in dict.fromkeys(ciks.values()) if cik]
    if workers > 1:
        warm(issuer_ciks, clients.edgar.submissions, workers=workers, name="issuer names")
    reads = record.watch()
    issuer_names = {cik: record.names(cik) for cik in issuer_ciks}
    names_degraded = set(reads.ciks)
    meter.done("issuer resolution", mark)
    # stage 2b's answers are reported as issuer_inferred, as the second pass's are
    return _Issuers(answers, issuers_by_era(ciks, issuer_names), last_seen, names_degraded,
                    {**checked, **second.inferred}, second.disagreements, set(passes.degraded))


def _trading_span(ftd: FtdIndex, cusip: str) -> tuple[str, str] | None:
    """The first and last day a CUSIP's fails rows show it trading (`FtdIndex.trading_rows`), None for none."""
    rows = ftd.trading_rows([cusip])
    return (rows[0].date, rows[-1].date) if rows else None


def _resolve_securities(eras: list[TickerEra], era_by_key: dict[str, TickerEra], ftd: FtdIndex,
                        handoffs: Sequence[Handoff], found: _Issuers, clients: Sources, log: Callable[[str], None]
                        ) -> tuple[dict[str, EraResolution], dict[str, Security], list[ReviewItem]]:
    """3. FIGI per era -> securities. An era takes only the FTD CUSIPs whose rows
    describe its issuer, by its observed names or the issuer's EDGAR names (D21),
    and a ticker or name hit whose name agrees with those same names (§8.3). An
    era with no pick of its own still joins a same-issuer, same-class sibling's
    composite through their shared-CUSIP/switch evidence (`handoffs`,
    spec §17), when that sibling is confirmed by a pin or a CUSIP. An era no
    fails row shows under its ticker takes no ticker or name pick (a backfilled
    ticker: it is placed on its issuer's line then, if there is exactly one),
    nor does one whose ticker's rows are all another security's (`foreign_ticker_eras`, placed on the line whose
    confirming CUSIP traded over its dates), and a weak era whose merge would cross another security's confirmed
    range is taken back out (`resolve_with_identity_guard`). Returns each era's
    resolution, the securities, and the review items of eras that resolved to
    no FIGI, were taken back out, or rested on a degraded answer."""
    issuers = found.issuers
    cusips = candidate_cusips(eras, ftd, issuers)
    resolutions, detached = resolve_with_identity_guard(
        FigiResolver(clients.figi, log=log, cusip_span=lambda c: _trading_span(ftd, c),
                     foreign=foreign_ticker_eras(eras, ftd, issuers)),
        eras, issuers=issuers, cusips=cusips, handoffs=handoffs, unconfirmed=guarded_eras(eras, ftd))
    securities = build_securities(resolutions, era_by_key, issuers)
    review: list[ReviewItem] = detached_review(detached, era_by_key, resolutions, issuers)
    for key, res in resolutions.items():
        era = era_by_key[key]
        for flag in res.flags:
            review.append(ReviewItem(res.sec_id or "", era.ticker, cik_of(issuers, key), flag,
                                     f"{era.key} {era.name or ''}".strip(), last_seen=era.last))
    for e in eras:
        if clients.resolver.is_degraded(e.ticker, found.last_seen[e.key], name=e.name) or e.key in found.degraded:
            review.append(degraded_item(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key),
                                         f"{e.key} {e.name or ''}: issuer resolution",
                                         "; its answer was used for this run but not saved", last_seen=e.last))
    for e in eras:
        inferred = found.inferred.get(e.key)
        if inferred is not None:
            review.append(ReviewItem(resolutions[e.key].sec_id or "", e.ticker, inferred.cik, "issuer_inferred",
                                     f"{e.key} {e.name or ''}: issuer {inferred.cik} by {inferred.source}: "
                                     f"{inferred.via}", last_seen=e.last))
        other = found.disagreements.get(e.key)
        if other is not None:
            first = found.answers[e.key]
            review.append(ReviewItem(resolutions[e.key].sec_id or "", e.ticker, first.cik, "issuer_cusip_disagrees",
                                     f"{e.key} {e.name or ''}: the resolver gave issuer {first.cik} ({first.source}); "
                                     f"its CUSIP evidence gives {other.cik} by {other.source}: {other.via}",
                                     last_seen=e.last))
    for e in eras:
        if cik_of(issuers, e.key) in found.names_degraded:
            review.append(degraded_item(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key),
                                         f"{e.key} {e.name or ''}: the issuer's EDGAR names",
                                         "; its CUSIPs and FIGI were checked without what could not be read",
                                         last_seen=e.last))
    review += observation_conflict_review(eras, resolutions)
    review += ticker_unconfirmed_review(eras, ftd, resolutions, issuers)
    log(f"{len(securities)} securities; FIGI sources "
        f"{dict(Counter(s.figi_source for s in securities.values()))}")
    return resolutions, securities, review


def _security_cusips(securities: dict[str, Security], resolutions: dict[str, EraResolution], ftd: FtdIndex,
                     ftd_client: Any, ftd_lo: date, as_of: date) -> dict[str, list[str]]:
    """4. Each security's CUSIPs over its whole life: every CUSIP of each of its
    eras that resolved to its FIGI (a reverse split's old and new CUSIP both),
    with their FTD rows loaded up to the run date."""
    sec_cusips = {sid: list(dict.fromkeys(c for e in s.eras for c in resolutions[e.key].cusips))
                  for sid, s in securities.items()}
    ftd.extend(ftd_client, ftd_lo, as_of, cusips={c for v in sec_cusips.values() for c in v})
    return sec_cusips


# --- Ticker eras: refined on the fails rows, and read against them ------------------------------------------------

def _cusip_runs(rows: Sequence[FtdRow]) -> list[tuple[str, list[FtdRow]]]:
    """Date-sorted `rows` grouped into consecutive runs of one CUSIP."""
    runs: list[tuple[str, list[FtdRow]]] = []
    for r in rows:
        if runs and runs[-1][0] == r.cusip:
            runs[-1][1].append(r)
        else:
            runs.append((r.cusip, [r]))
    return runs


def _cut(obs: Sequence[Observation], rows: Sequence[FtdRow],
         cuts: Sequence[str]) -> list[tuple[list[Observation], list[FtdRow]]]:
    """Observations and rows split at each cut date: a cut date starts the next part."""
    bounds = [None, *sorted(set(cuts)), None]
    return [([o for o in obs if (lo is None or o.as_of >= lo) and (hi is None or o.as_of < hi)],
             [r for r in rows if (lo is None or r.date >= lo) and (hi is None or r.date < hi)])
            for lo, hi in zip(bounds, bounds[1:])]


def _kept_cusips(rows: Sequence[FtdRow]) -> tuple[str, ...]:
    """CUSIPs with at least one run of `ERA_MIN_RUN` rows, most rows first."""
    kept = {c for c, run in _cusip_runs(rows) if len(run) >= ERA_MIN_RUN}
    return tuple(c for c, _ in Counter(r.cusip for r in rows).most_common() if c in kept)


def _gap_cuts(obs: Sequence[Observation], rows: Sequence[FtdRow]) -> list[str]:
    kept = set(_kept_cusips(rows))
    dates = sorted({o.as_of for o in obs} | {r.date for r in rows if r.cusip in kept})
    return [b for a, b in zip(dates, dates[1:])
            if (date.fromisoformat(b) - date.fromisoformat(a)).days > ERA_GAP_DAYS]


def _switch_cuts(rows: Sequence[FtdRow]) -> list[str]:
    kept = [(c, run) for c, run in _cusip_runs(rows) if len(run) >= ERA_MIN_RUN]
    return [run[0].date for (a, _), (b, run) in zip(kept, kept[1:]) if a != b]


def _described(cusip: str, rows: Sequence[FtdRow], names: Sequence[str]) -> bool:
    """True when some FTD row of `cusip` has a description agreeing with a name."""
    return any(names_agree(r.description, n) for r in rows if r.cusip == cusip for n in names)


def _split_era(era: TickerEra, rows: list[FtdRow], *, contested: bool) -> list[TickerEra]:
    out: list[TickerEra] = []
    for g_obs, g_rows in _cut(era.observations, rows, _gap_cuts(era.observations, rows)):
        for obs, part_rows in _cut(g_obs, g_rows, _switch_cuts(g_rows)):
            if not obs:
                continue                  # an FTD-only side (another holder of the ticker, a tail) is no era
            kept = _kept_cusips(part_rows)
            names = [o.name for o in obs if o.name]
            if contested and names:
                # Another era of this ticker has observations on the same dates
                # (a backfilled name): the ticker's rows are only this era's when
                # their description agrees with its names.
                kept = tuple(c for c in kept if _described(c, part_rows, names))
            out.append(replace(era, first=obs[0].as_of, last=obs[-1].as_of, observations=list(obs),
                               ftd_cusips=kept))
    return out


def refine_eras(eras: Sequence[TickerEra], ftd: FtdIndex) -> list[TickerEra]:
    """Stage 2 of era building (stage 1 is `observations.split_eras`): split each
    observation era further on SEC fails-to-deliver evidence under its ticker.

    Each observation era sees the ticker's FTD rows after the previous era's
    last observation and before the next era's first observation (so rows
    between two eras — one security's tail, the next one's head — are seen by
    both, and each drops the side that is not its own). Within that window:

    - Gap: the era's observation dates merged with the dates of its FTD rows of
      the CUSIPs that have a run of at least `ERA_MIN_RUN` rows split where two
      consecutive dates are more than `ERA_GAP_DAYS` apart. FTD rows bridge a
      snapshot gap for a security that kept trading (2009-06-08 -> 2012-06-29);
      nothing bridges DELL's 2013 -> 2018 gap.
    - CUSIP switch: within each gap part, the FTD rows grouped into runs of one
      CUSIP (runs shorter than `ERA_MIN_RUN` ignored as noise); where two kept
      runs have different CUSIPs, split at the first date of the later run
      (FOXA 90130A101 -> 35137L105, GOOG 38259P508 -> 38259P706).

    The gap is applied first so that an observation of the new security dated
    before its CUSIP's first FTD row (DELL Technologies seen 2018-12-31, first
    fails row 2019-01-02) stays with the new security instead of being cut off
    alone. Observations before a cut date stay in the earlier era; a part with
    no observations is not an era, and its rows are dropped (a neighbouring era
    of the same CUSIP already has that CUSIP). Each resulting era records the
    CUSIPs of its own kept runs in `ftd_cusips`.

    Two eras of one ticker with observations on the same date (a snapshot
    source backfilled today's ticker: CB is both "ACE LTD" and "CHUBB CORP" in
    2012-2014) both see the same rows; for them a CUSIP counts only when its
    FTD description agrees with the era's names, so the backfilled name does
    not take the other security's CUSIP and resolves on its own.

    Every era is kept, under a unique key (`observations.number_eras`).
    Over-splitting is cheap: `build_securities` merges eras that resolve to the
    same FIGI.
    """
    spans: dict[str, list[tuple[str, str]]] = defaultdict(list)
    seen_on: Counter[tuple[str, str]] = Counter()
    for e in eras:
        spans[e.ticker].append((e.first, e.last))
        seen_on.update({(e.ticker, o.as_of) for o in e.observations})
    out: list[TickerEra] = []
    for e in eras:
        prev = max((last for first, last in spans[e.ticker] if first < e.first), default=None)
        nxt = min((first for first, _ in spans[e.ticker] if first > e.first), default=None)
        lo = (date.fromisoformat(prev) + timedelta(days=1)).isoformat() if prev else None
        hi = (date.fromisoformat(nxt) - timedelta(days=1)).isoformat() if nxt else None
        contested = any(seen_on[(e.ticker, o.as_of)] > 1 for o in e.observations)
        out += _split_era(e, ftd.by_symbol(e.ticker, lo, hi), contested=contested)
    return number_eras(out)


def era_cusips(era: TickerEra, ftd: FtdIndex, issuer_names: Sequence[str] = (),
               taken_by_known_issuers: Collection[str] = ()) -> list[str]:
    """Candidate CUSIPs for an era: the observed ones, then the FTD ones.

    A refined era takes those of its own FTD CUSIPs whose fails rows describe its
    issuer (spec D21): some row of the CUSIP has a description that
    `names.description_matches` the era's observed names or `issuer_names` (the
    issuer's EDGAR names, current and former, which cover a description that
    lags a rename or a snapshot that backfilled a later name). A CUSIP whose rows
    all name another issuer is not taken, however it came to be the era's: a
    snapshot that kept listing Clear Channel under CCU after it went private in
    2008 sees only Cervecerias Unidas' rows there. With none left the era has no
    FTD CUSIP (and resolves by ticker or name, or to its placeholder).
    `taken_by_known_issuers`: CUSIPs that eras with a known issuer took, taken
    without that check by an era whose issuer is unknown (see `candidate_cusips`).

    An era with no FTD CUSIPs of its own takes the FTD rows under the ticker
    around it whose description agrees with an era name, most rows first."""
    if era.ftd_cusips:
        names = [*era.names, *issuer_names]
        own = [c for c in era.ftd_cusips if c in taken_by_known_issuers
               or any(description_matches(d, names) for d in ftd.descriptions(c))]
        return list(era.cusips) + [c for c in own if c not in era.cusips]
    lo = (date.fromisoformat(era.first) - timedelta(days=10)).isoformat()
    hi = (date.fromisoformat(era.last) + timedelta(days=10)).isoformat()
    counts: Counter[str] = Counter()
    for r in ftd.by_symbol(era.ticker, lo, hi):
        if era.names and not any(names_agree(r.description, n) for n in era.names):
            continue
        counts[r.cusip] += 1
    return list(era.cusips) + [c for c, _ in counts.most_common() if c not in era.cusips]


def candidate_cusips(eras: Sequence[TickerEra], ftd: FtdIndex,
                     issuers: Mapping[str, Issuer]) -> dict[str, list[str]]:
    """`era_cusips` for every era (by key), each checked against its issuer's
    EDGAR names (`issuers`, by era key: the eras whose issuer is known).

    An era whose issuer is unknown (no CIK) has only its observed names, which a
    stale snapshot can leave behind a rename (CME Group is still "CHICAGO
    MERCANTILE HLDGS" in the 2008 snapshots, and no CIK resolves for that name
    then). It also takes a CUSIP that an era with a known issuer took as that
    issuer's: the fails rows tie the CUSIP to that issuer, the ticker and the
    dates tie it to this era. An era with a known issuer is held to its own
    issuer's names, so a stale era (Triad Hospitals on TRI in 2008) never takes
    the CUSIP of the issuer that later holds its ticker (Thomson Reuters)."""
    out = {e.key: era_cusips(e, ftd, issuers[e.key].names) for e in eras if e.key in issuers}
    taken_by_known_issuers = {c for taken in out.values() for c in taken}
    for e in eras:
        if e.key not in issuers:
            out[e.key] = era_cusips(e, ftd, (), taken_by_known_issuers)
    return out


def _own_rows(era: TickerEra, rows: Sequence[FtdRow]) -> list[FtdRow]:
    """Those of `rows` (under the era's ticker) that are the era's own: of its
    own FTD CUSIPs when it has them (a name check is too weak: "FOX CORP" agrees
    with "TWENTY FIRST CENTURY FOX"), else with a description that agrees with
    an era name (every row, for an era with neither)."""
    if era.ftd_cusips:
        return [r for r in rows if r.cusip in era.ftd_cusips]
    if era.names:
        return [r for r in rows if any(names_agree(r.description, n) for n in era.names)]
    return list(rows)


def era_last_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400) -> str:
    """The era's last sighting: its last observation, or a later FTD row of its
    own (`_own_rows`) under its ticker within `horizon_days`."""
    lo = (date.fromisoformat(era.last) + timedelta(days=1)).isoformat()
    hi = (date.fromisoformat(era.last) + timedelta(days=horizon_days)).isoformat()
    return max([era.last, *(r.date for r in _own_rows(era, ftd.by_symbol(era.ticker, lo, hi)))])


def era_rows(era: TickerEra, ftd: FtdIndex, last_seen: str) -> list[FtdRow]:
    """The era's own FTD rows (`era_last_seen`'s choice, `_own_rows`) from its
    first observation to its last sighting `last_seen`, by date."""
    return _own_rows(era, ftd.by_symbol(era.ticker, era.first, last_seen))


# --- The era-level issuer passes: stage 2b and the second pass -------------------------------------------------------

@dataclass(frozen=True)
class InferredIssuer:
    """An era-level answer (`EraIssuers`): its issuer CIK, the rule that found it (`source`), and what linked them
    (`via`, for the review item)."""
    cik: int
    source: str
    via: str


@dataclass(frozen=True)
class SecondPass:
    """`EraIssuers.infer`'s answers, by era key: `inferred`, for the eras the first pass left with no CIK;
    `disagreements`, for the eras whose first-pass CIK their CUSIP evidence (rule C) contradicts -- the first pass's
    answer stands, and the era is flagged `issuer_cusip_disagrees`."""
    inferred: dict[str, InferredIssuer]
    disagreements: dict[str, InferredIssuer]


# The CUSIPs of the eras known to be each issuer's, with the class letter each
# such era's name states (None: none): issuer CIK -> CUSIP -> letters.
IssuerLines = dict[int, dict[str, set[str | None]]]


def _class_letter(era: TickerEra) -> str | None:
    """The share class letter the era's name states ("...CLASS B" -> "B"), or None."""
    return class_letter(share_class_from_name(era.name))


def _other_class(letters: set[str | None], era_class: str | None) -> bool:
    """Whether a CUSIP whose eras state `letters` is of another share class than
    an era of class `era_class`: both known, and every one of them differs."""
    return era_class is not None and bool(letters) and all(x is not None and x != era_class for x in letters)


class EraIssuers:
    """The era-level issuer passes, which read the run's other eras and its fails rows and so are never saved:
    stage 2b's check of the lookup's name-search answers (`check_names`) and the second pass for the eras it left
    with no CIK (`infer`). Every issuer read goes through the run's issuer record (`issuers`); rule B's candidates
    are the lookup's 8-K frequency tier's (`frequency`: (ticker, day) -> (ranked (CIK, name), whether the search
    failed)). The passes keep their own state: an era whose answer rested on a failed search, or on an issuer read
    that failed or was answered from a stale copy, is in `degraded` (by era key), and the stage reports it
    `resolution_degraded` as it does a first-pass answer the lookup says rested on one."""

    def __init__(self, issuers: IssuerRecord,
                 frequency: Callable[[str, str], tuple[list[tuple[int, str]], bool]]) -> None:
        self.issuers = issuers
        self._frequency = frequency
        self.degraded: set[str] = set()
        self._failed = False                 # a search of the current era failed
        self._reads = issuers.watch()        # the issuer reads of the current era (`_reset`)

    def _reset(self) -> None:
        """Start an era: no search has failed yet, and its issuer reads are watched from here."""
        self._failed = False
        self._reads = self.issuers.watch()

    def _mark(self, era: TickerEra) -> None:
        """An era whose reads since `_reset` hit a failed request or a stale copy is degraded."""
        if self._failed or self._reads.ciks:
            self.degraded.add(era.key)

    def _frequency_ranked(self, ticker: str, day: str) -> list[tuple[int, str]]:
        """The 8-K frequency candidates for `ticker` before `day`; a failed search answers none and marks the era."""
        ranked, failed = self._frequency(ticker, day)
        self._failed = self._failed or failed
        return ranked

    # --- Stage 2b: a name-search answer checked against the era's span and its ticker's rows (sub-plan 5h) -----

    def check_names(self, eras: list[TickerEra], ftd: FtdIndex, last_seen: dict[str, str],
                    answers: dict[str, TickerResolution]) -> dict[str, InferredIssuer]:
        """A name-search answer (`answers[k].source` "name_search") replaced by another CIK that SEC's name index
        lists under exactly the era's observed name, never saved (the memo keeps the first pass's answer):

        An era with at least `ERA_MIN_ROWS` fails rows of its own is decided by them alone (`ticker_rows`: an
        observed name the rows refute is no evidence of who held the name over the era, and the answer must not
        depend on which holder the first pass named); an era with fewer takes `name_in_force`:

        - `name_in_force`: the answer's CIK carried no name agreeing with the observed one from the era's first
          sighting to its last (`last_seen`), and exactly one other such CIK, filing by the first sighting, did
          (ABBI 2008-2009: APP Pharmaceuticals dropped "Abraxis BioScience" in 2007; the new Abraxis carried it);
        - `ticker_rows`: the era's own fails rows (`era_rows`, at least `ERA_MIN_ROWS`)
          are not the answer's (guard G's `_fits_rows`) and exactly one other such CIK's they are (ERA 2013: the
          rows under ERA say ERA GROUP INC, the company later renamed Bristow Group Inc; the old Bristow Group
          traded as BRS).

        A pinned era, one with no name or no name index, keeps its answer. Answers keyed by era."""
        index = self.issuers.name_index()
        out: dict[str, InferredIssuer] = {}
        if index is None:
            return out
        for e in sorted(eras, key=lambda e: e.key):
            res = answers.get(e.key)
            if res is None or res.cik is None or res.source != "name_search" or e.cik_pin is not None \
                    or e.sec_id_pin or not e.name:
                continue
            holders = sorted({h.cik for h in index.split_search(e.name)[0]} - {res.cik} - EXCHANGE_CIKS)
            if not holders:
                continue
            self._reset()
            rows = era_rows(e, ftd, last_seen[e.key])
            if len(rows) >= ERA_MIN_ROWS:      # the era's own rows decide, whichever holder the pass named
                got = self._ticker_rows_tie(e, res.cik, holders, rows)
            else:
                got = self._name_in_force(e, res.cik, holders, last_seen[e.key])
            if got is not None:
                out[e.key] = got
            self._mark(e)
        return out

    def _carried_over(self, cik: int, name: str, lo: date, hi: date) -> bool:
        """Whether the CIK carried a name agreeing with `name` at some point in [lo, hi] (its submissions JSON)."""
        return any(names_agree(n, name) for n in self.issuers.names_between(cik, lo, hi, about=hi))

    def _name_in_force(self, era: TickerEra, first: int, holders: list[int], last: str) -> InferredIssuer | None:
        lo, hi = parse_day(era.first), parse_day(last)
        if lo is None or hi is None or self._carried_over(first, era.name, lo, hi):
            return None
        found = [c for c in holders
                 if self.issuers.existed_by(c, era.first) and self._carried_over(c, era.name, lo, hi)]
        if len(found) != 1:
            return None
        return InferredIssuer(found[0], NAME_IN_FORCE,
                              f"{first} did not carry the name from {era.first} to {last}; {found[0]} did")

    def _ticker_rows_tie(self, era: TickerEra, first: int, holders: list[int],
                         rows: list[FtdRow]) -> InferredIssuer | None:
        if len(rows) < ERA_MIN_ROWS or self._fits_rows(first, rows):
            return None
        found = [c for c in holders if self.issuers.existed_by(c, era.first) and self._fits_rows(c, rows)]
        if len(found) != 1:
            return None
        return InferredIssuer(found[0], TICKER_ROWS,
                              f"its fails rows under {era.ticker} ({rows[0].description}) are {found[0]}'s, "
                              f"not {first}'s")

    # --- The second pass: eras the first could not resolve -------------------------

    def infer(self, eras: list[TickerEra], ftd: FtdIndex, last_seen: dict[str, str],
              ciks: dict[str, int | None], handoffs: Sequence[Handoff] | None = None) -> SecondPass:
        """The second pass: an issuer for each era the first pass left with no
        CIK and that has no pin, in era-key order. A renamed issuer files no
        Form 25 and keeps filing 10-Ks, so the first pass's 8-K frequency tier
        rejects it and its company search sees only today's name. The answers
        depend on the run's other eras and on its fails rows, so they are never
        saved (the memo keeps only the first pass's).

        Each era is judged on its own fails rows (`era_rows`,
        from its first observation to its last sighting `last_seen`); one with
        fewer than `ERA_MIN_ROWS` gets no answer. A candidate CIK must pass the
        guard (`_guard`): it existed by the era's first row, every row's
        description matches a name it carried by `GUARD_NAME_DAYS` after the
        row's date (`_fits_rows`), and it is the only candidate that did. Every
        answer also needs one of the era's observed names to match an EDGAR
        name of its issuer (`_named`).

        B (`efts_frequency_renamed`): the first pass's 8-K frequency candidates,
        through the guard, and the one left also carried the era's name at its
        last sighting and filed within `OBSERVED_ALIVE_DAYS` of it (Capri
        Holdings for KORS@2014).

        C (`shared_cusip`, `cusip_handoff`), after B: the issuers of the eras
        linked to this one by a CUSIP (`security_master.cusip_handoffs`: the
        same CUSIP, or a switch from this era's CUSIP to theirs, whose issuer
        must be the old CUSIP's, renamed: `_switch_issuer`), through the guard. Every
        era is judged against the answers known when the sweep began, and
        sweeps repeat until none adds an answer, so a chain of links resolves
        whatever the key order (MHP shares its CUSIP with MHFI, whose CUSIP
        switched to SPGI's). At the fixed point every answer is checked again.

        Rule C also runs over the eras the first pass answered (unpinned, with
        enough rows): where it gives another issuer, the first pass's answer
        stands and the disagreement is returned for review (LSTR@2008's name
        search took LandStar Inc; the CUSIP it shares with LSTR@2012 is Landstar
        System's)."""
        rows = {e.key: era_rows(e, ftd, last_seen[e.key]) for e in eras}
        todo = [e for e in sorted(eras, key=lambda e: e.key)
                if ciks.get(e.key) is None and e.cik_pin is None and not e.sec_id_pin
                and len(rows[e.key]) >= ERA_MIN_ROWS]
        out: dict[str, InferredIssuer] = {}
        for e in todo:
            self._reset()
            got = self._named(e, self._frequency_renamed(e, rows[e.key], last_seen[e.key]), last_seen[e.key])
            if got is not None:
                out[e.key] = got
            self._mark(e)
        links: dict[str, list[Handoff]] = defaultdict(list)
        for h in (cusip_handoffs(eras, ftd) if handoffs is None else handoffs):
            links[h.era_key].append(h)
        first_pass = {k: c for k, c in ciks.items() if c is not None}
        by_key = {e.key: e for e in eras}

        def issuers_now() -> tuple[dict[str, int], dict[int, set[str]]]:
            """Every era's known issuer, and each issuer's CUSIPs (of its eras)."""
            known = first_pass | {k: v.cik for k, v in out.items()}
            issuer_cusips: dict[int, dict[str, set[str | None]]] = defaultdict(lambda: defaultdict(set))
            for k, c in known.items():
                for cusip in {*by_key[k].ftd_cusips, *by_key[k].cusips}:
                    issuer_cusips[c][cusip].add(_class_letter(by_key[k]))
            return known, issuer_cusips

        while True:
            known, issuer_cusips = issuers_now()
            new: dict[str, InferredIssuer] = {}
            for e in todo:
                if e.key in out:
                    continue
                self._reset()
                got = self._named(e, self._handoff(rows[e.key], links[e.key], known, ftd, issuer_cusips,
                                                   _class_letter(e)), last_seen[e.key])
                if got is not None:
                    new[e.key] = got
                self._mark(e)
            if not new:
                break
            out |= new
        # At the fixed point every answer is checked again against all it links
        # to now: one answered before a linked era was, from another issuer, can
        # have become ambiguous. Such answers are dropped, and the check repeats
        # without them until none is dropped.
        while True:
            known, issuer_cusips = issuers_now()
            dropped = []
            for key, got in out.items():
                self._reset()
                found = self._linked_issuers(links[key], known, ftd, issuer_cusips, _class_letter(by_key[key]))
                candidates = [*found, *([got.cik] if got.source == "efts_frequency_renamed" else [])]
                if self._guard(candidates, rows[key]) != got.cik:
                    dropped.append(key)
                self._mark(by_key[key])
            if not dropped:
                break
            for key in dropped:
                del out[key]
        disagreements: dict[str, InferredIssuer] = {}
        for e in sorted(eras, key=lambda e: e.key):
            first = first_pass.get(e.key)
            if first is None or e.cik_pin is not None or e.sec_id_pin or len(rows[e.key]) < ERA_MIN_ROWS:
                continue
            self._reset()
            got = self._named(e, self._handoff(rows[e.key], links[e.key], known, ftd, issuer_cusips,
                                               _class_letter(e)), last_seen[e.key])
            if got is not None and got.cik != first:
                disagreements[e.key] = got
        return SecondPass(out, disagreements)

    def _named(self, era: TickerEra, got: InferredIssuer | None, last_seen: str) -> InferredIssuer | None:
        """`got`, when one of the era's observed names `names.description_matches`
        some EDGAR name of its issuer, current or former (an era with no name,
        or none with a word to compare, is not refuted); else None. The fails
        rows under a stale snapshot's ticker can be the ticker's later holder's:
        TRI@2008, Triad Hospitals, shares Thomson Reuters' CUSIP."""
        if got is None or not era.names:
            return got
        names = self.issuers.names(got.cik, about=last_seen)
        return got if any(description_matches(n, names) for n in era.names) else None

    def _guard(self, candidates: Iterable[int], rows: list[FtdRow]) -> int | None:
        """Guard G: the one candidate (`_fits_rows`) that could be the issuer of
        `rows`; None when none or several are. The fails descriptions are loose
        (one shared word matches), so a second match means the rows cannot tell."""
        passing = [c for c in dict.fromkeys(candidates) if self._fits_rows(c, rows)]
        return passing[0] if len(passing) == 1 else None

    def _fits_rows(self, cik: int, rows: list[FtdRow]) -> bool:
        """Whether the CIK existed by the first of `rows`, and each row's
        description that names an issuer (`names.names_an_issuer`; one that
        leaves no word to compare, F5,INC. COMMON STOCK, says nothing either way,
        and at least one must name it) `names.description_matches` a name it
        carried by `GUARD_NAME_DAYS` after the row's date. An earlier name
        counts: SEC updates a description slowly (HCP INC COM STK until the ticker
        changed on 2019-11-05, EDGAR ending the name HCP, INC. on 2019-10-01). A
        company founded later (LMCA's 2013 spin-off for 2012 rows), never so
        named (Penske Automotive for an ETN's rows under UAG), or so named only
        later, is not the rows' issuer."""
        sub = self.issuers.profile(cik, about=rows[-1].date)
        first = self.issuers.first_filed(cik)
        if first is None or first > parse_day(rows[0].date) or sub is None:
            return False
        since: dict[str, str] = {}                  # description -> its first row's date (names only accumulate)
        for r in rows:
            if names_an_issuer(r.description):
                since.setdefault(r.description, r.date)
        return bool(since) and all(     # the names of the copy just read
            description_matches(d, self.issuers.names_until(cik, parse_day(day) + timedelta(days=GUARD_NAME_DAYS)),
                                empty=False)
            for d, day in since.items())

    def _frequency_renamed(self, era: TickerEra, rows: list[FtdRow], last_seen: str) -> InferredIssuer | None:
        """Fix B: the 8-K frequency candidate that passes the guard, carried the
        era's name at its last sighting, and filed within `OBSERVED_ALIVE_DAYS`
        of it."""
        if not era.name:
            return None
        ranked = self._frequency_ranked(era.ticker, last_seen)
        cik = self._guard([c for c, _ in ranked], rows)
        on = parse_day(last_seen)
        if cik is None or on is None:
            return None
        named = [n for n in self.issuers.names_near(cik, on, about=last_seen) if names_agree(n, era.name)]
        alive = any(abs((d - on).days) <= OBSERVED_ALIVE_DAYS
                    for f in self.issuers.filings(cik) if (d := parse_day(f.filing_date)))
        if not named or not alive:
            return None
        return InferredIssuer(cik, "efts_frequency_renamed",
                              f"the one 8-K frequency candidate whose names match its fails rows; "
                              f"EDGAR names it {named[0]} then")

    def _handoff(self, rows: list[FtdRow], links: list[Handoff], known: dict[str, int], ftd: FtdIndex,
                 issuer_cusips: IssuerLines, era_class: str | None) -> InferredIssuer | None:
        """Fix C: the issuer, through the guard, of the eras `links` leads to
        (`known`: era key -> CIK). A switch counts only when that issuer is the
        old CUSIP's, renamed (`_switch_issuer`). A shared CUSIP is read first, so
        it names the answer's source when both lead to the same issuer."""
        found = self._linked_issuers(links, known, ftd, issuer_cusips, era_class)
        cik = self._guard(found, rows)
        if cik is None:
            return None
        h, former = found[cik]
        if h.kind == "shared_cusip":
            return InferredIssuer(cik, h.kind, f"shares CUSIP {h.cusip} with {h.to_key}")
        return InferredIssuer(cik, h.kind, f"its CUSIP {h.cusip} ended as {h.to_key}'s {h.new_cusip} began on "
                                           f"{h.day}; the issuer was renamed from {former}")

    def _linked_issuers(self, links: list[Handoff], known: dict[str, int], ftd: FtdIndex,
                        issuer_cusips: IssuerLines, era_class: str | None
                        ) -> dict[int, tuple[Handoff, str | None]]:
        """The issuers `links` lead to (`known`: era key -> CIK), each with the
        link that found it first (a shared CUSIP before a switch) and, for a
        switch, the former name it was renamed from."""
        found: dict[int, tuple[Handoff, str | None]] = {}
        for h in sorted(links, key=lambda h: (h.kind != "shared_cusip", h.to_key)):
            cik = known.get(h.to_key)
            if cik is None or cik in found:
                continue
            former = (self._switch_issuer(cik, h, ftd, issuer_cusips, era_class) if h.kind == "cusip_handoff"
                      else None)
            if h.kind == "cusip_handoff" and former is None:
                continue
            found[cik] = (h, former)
        return found

    def _switch_issuer(self, cik: int, h: Handoff, ftd: FtdIndex, issuer_cusips: IssuerLines,
                       era_class: str | None) -> str | None:
        """Whether the new CUSIP's issuer `cik` is the switch `h`'s old CUSIP's,
        renamed: the former name it was renamed from (`_renamed_from`), or None.
        It must have existed when the old CUSIP began failing (Actavis plc,
        formed in 2013, is not Actavis Inc's issuer), and have no other CUSIP of
        its own (`issuer_cusips`: the CUSIPs of the eras known to be its) trading
        at the switch (`security_master.trades_at_switch`: an acquirer that
        renamed itself at the merger, as Wisconsin Energy did for Integrys and
        SXC Health Solutions for Catalyst Health Solutions). A CUSIP of another
        share class than the era's (`era_class`; Discovery's series C for series
        A) does not count, nor does one born at the switch."""
        first = self.issuers.first_filed(cik)
        if first is None or first > parse_day(h.since):
            return None
        others = {c for c, letters in issuer_cusips.get(cik, {}).items()
                  if c not in (h.cusip, h.new_cusip) and not _other_class(letters, era_class)}
        if trades_at_switch(ftd, h, others):
            return None
        return self._renamed_from(cik, h)

    def _renamed_from(self, cik: int, h: Handoff) -> str | None:
        """The CIK's former name that ended within `RENAME_NEAR_DAYS` of the
        switch `h` (`evidence.renamed_near`: it was renamed there), when every
        description of the old CUSIP's rows that names a company (one at least)
        names, word by word (`names.description_names`: CITIZENS COMMUNICATIONS
        is not CLEAR CHANNEL COMMUNICTNS), a name the CIK carried in the
        `GUARD_NAME_DAYS` up to that description's first row (QUINTILES
        TRANSNATIONAL HLDGS, before Quintiles IMS Holdings) or that former name
        (EDGAR records ACE Ltd's names only from 2009, after its rows began);
        None otherwise. A name dropped years before is no evidence (CBS Corp's
        CIK was named VIACOM INC until 2005, TeraWulf's CHROMALINE until 2002),
        nor is one taken after the rows began: A & B II, spun off by Alexander &
        Baldwin Holdings in 2012, took the name Alexander & Baldwin as the
        Holdings CUSIP switched to Matson's and to its own. A spin-off starting
        as its parent's CUSIP ends carries no such name."""
        day = parse_day(h.day)
        sub = self.issuers.profile(cik, about=h.day)
        former = renamed_near(sub, day, RENAME_NEAR_DAYS) if sub is not None and day else None
        named = [(d, parse_day(since)) for d, since in h.descriptions if names_an_issuer(d)]
        if former and named and all(
                any(description_names(d, n)
                    for n in [*names_between(sub, on - timedelta(days=GUARD_NAME_DAYS), on), former])
                for d, on in named):
            return former
        return None

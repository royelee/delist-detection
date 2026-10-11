# src/delist_detection/identity/identity.py
"""A security's identity: the run's stages 1 to 4 behind one interface (architecture step 6).

`identify(index, clients, as_of=...)` turns the caller's observations into the securities the rest of the run works
on, and answers what later stages read about who each one is (`Identity`):

1. the ticker eras (CONTEXT.md), built in one place: `observations.split_eras` splits each ticker's observations,
   then `refine_eras` splits them again on the SEC fails-to-deliver rows under the ticker, which this stage loads
   (`Identity.ftd`; later stages extend it);
2. each era's issuer CIK, asked at the era's capped date and at the end of its own fails rows (`era_capped_seen`,
   `era_last_seen`; `choose_first_pass`) with its own pin, name and first sighting: the issuer lookup's first pass (`IssuerLookup`, the memoized (ticker, date, observed name) -> CIK
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
from types import MappingProxyType
from typing import Any, Protocol

from ..outputs.degraded import degraded_item
from ..filings.evidence import bankruptcy_8ks, names_between, parse_day, renamed_near
from ..sources.ftd import FTD_START, FtdIndex, FtdRow
from ..vocabulary.identifiers import is_placeholder, name_class_letter, placeholder_id, share_class_from_name
from .carried_price import price_carried, step_price_ratio
from .issuer_record import IssuerRecord
from ..outputs.manifest import StageMeter
from ..vocabulary.names import (
    description_matches, description_name, description_names, names_agree, names_an_issuer,
)
from .observations import (
    ERA_GAP_DAYS, DerivedFrom, Observation, ObservationError, ObservationIndex, TickerEra, eras_by_key, number_eras,
)
from ..sources.prefetch import warm
from ..outputs.review_triage import ReviewItem
from .security_master import (
    EraResolution, FigiResolver, Handoff, Issuer, Security, build_securities, cik_of, cusip_handoffs,
    detached_review, foreign_ticker_eras, guarded_eras, issuers_by_era, observation_conflict_review,
    resolve_with_identity_guard, ticker_unconfirmed_review, trades_at_switch,
)
from .ticker_resolver import TickerResolution, TickerResolver

MAX_VERDICT_PASSES = 3   # passes that add a verdict on a derived era: stages 1 to 3 again with the new ones
NOT_MADE = "not_made"                          # a verdict: the derived era is not made (rule J)
WITHOUT_OLD_ISSUER = "without_old_issuer"      # a verdict: the derived era is asked without the old line's issuer (rule X)

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
    writes its memo. A lookup `exclude`s CIKs (rule X: a derived era asked without the old line's issuer) only where
    `identify` passes the argument; `is_degraded` is then asked with the same `exclude`."""

    def resolve(self, ticker: str, observed_date: str | None = None, *, pin: Any = ..., name: Any = ...,
                since: str | None = None, exclude: Collection[int] = ...) -> TickerResolution: ...

    def is_degraded(self, ticker: str, observed_date: str | None = None, *, name: Any = ...,
                    exclude: Collection[int] = ...) -> bool: ...

    def frequency_candidates(self, ticker: str, day: str) -> tuple[list[tuple[int, str]], bool]: ...

    def shadow(self) -> "IssuerLookup": ...

    def flush(self) -> None: ...


class Sources(Protocol):
    """What `identify` reads through (`pipeline.Clients` has it all)."""
    resolver: IssuerLookup
    issuers: IssuerRecord     # the run's issuer record (the lookup's own, in production)
    figi: Any                 # OpenFIGI: `map(jobs)`, `filter(query, **fields)`
    ftd_client: Any           # SEC's fails-to-deliver files (`ftd.FtdClient`): the run's fails index is opened over them
    edgar: Any                # the EDGAR client whose cache the warm pass fills with the issuers' submissions


@dataclass
class Identity:
    """What `identify` answers: the refined eras (by key too), the run's fails index (`ftd`: opened by stage 1,
    asked by stage 4 to follow every security's CUSIPs; `ftd_lo`, its first day), each era's issuer (`issuers`,
    by era key, for the eras whose issuer is known: the one source of an era's CIK), each era's FIGI resolution,
    the securities, each security's CUSIPs over its whole life (`cusips`), the identity review items, each era's
    lookup tier (`tiers`: the first pass's, or the source of the 2b or second-pass rule that answered it) and the
    eras whose ticker's fails rows decided their issuer (`rows_decided`, 2b's `ticker_rows`: their observed name
    was refuted, so the issuer in force keeps their CIK), and `verdicts`, what the check of the derived eras found
    (`identify`): by (ticker, new CUSIP) pair, `NOT_MADE` or `WITHOUT_OLD_ISSUER`."""
    eras: list[TickerEra]
    era_by_key: dict[str, TickerEra]
    ftd: FtdIndex
    issuers: dict[str, Issuer] = field(default_factory=dict)
    resolutions: dict[str, EraResolution] = field(default_factory=dict)
    securities: dict[str, Security] = field(default_factory=dict)
    cusips: dict[str, list[str]] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)
    tiers: dict[str, str] = field(default_factory=dict)
    rows_decided: frozenset[str] = frozenset()
    verdicts: Mapping[tuple[str, str], str] = field(default_factory=dict)

    @property
    def ftd_lo(self) -> date | None:
        """The run's first fails day: the first day of the window the fails index was opened over
        (`FtdIndex.opened_from`; None for an index built from rows)."""
        return self.ftd.opened_from

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
        split = {p for p in held if any(k.startswith(p + "-") for k in kept)}      # lines named by a CUSIP: a split
        return {p: next(iter(f)) for p, f in held.items() if len(f) == 1 and p not in kept and p not in split}


def _quiet(*_: Any) -> None:
    return None


_NO_PAIRS: Mapping[tuple[str, str], Any] = MappingProxyType({})


def identify(index: ObservationIndex, clients: Sources, *, as_of: date, limit: int | None = None,
             log: Callable[[str], None] = _quiet, workers: int = 1, meter: StageMeter | None = None,
             derive: Mapping[tuple[str, str], DerivedFrom] = _NO_PAIRS, ftd: FtdIndex | None = None,
             verdicts: Mapping[tuple[str, str], str] = _NO_PAIRS) -> Identity:
    """Stages 1 to 4 over the observations of `index` (its first `limit` eras under `limit`), every window ending on
    the run date `as_of`; `log` takes one line per step, `meter` the SEC traffic of issuer resolution, and `workers`
    > 1 fills the EDGAR caches ahead on that many threads. Raises `ObservationError` when there is no observation;
    a refusal (`fatal.FATAL`) or an OpenFIGI outage stops it.

    `derive`, `ftd` and `verdicts`: the derived-line pairs with the step each came from
    (`derived_lines.derivable`), the fails index an earlier call opened, which a repeat reads in place of opening its
    own (the rows `follow_lines` added to it stay), and the verdicts an earlier round gave on derived pairs.

    A derived era is checked against its step (`_check_derived`) after stage 3. Rule J: an era on the security its
    step was refused from is made only when the price carried over across the step (`carried_price`); a pair judged
    otherwise is `NOT_MADE`. Rule X: an era from a `merged_out` step that took the origin's issuer under a composite
    of its own is asked again without that issuer in any resolver tier; the pair is `WITHOUT_OLD_ISSUER`. A new verdict
    sends stages 1 to 3 around again with it (at most `MAX_VERDICT_PASSES` times: the result equals a fresh call given
    the verdicts, and a pair with a verdict is not judged again). `Identity.verdicts` holds the final mapping."""
    meter = meter if meter is not None else StageMeter(log)
    verdicts = dict(verdicts)
    found_keys: dict[str, dict[tuple[str, str], str]] = {NOT_MADE: {}, WITHOUT_OLD_ISSUER: {}}     # verdict -> pair -> era key
    for pass_no in range(MAX_VERDICT_PASSES + 1):
        made = [pair for pair in derive if verdicts.get(pair) != NOT_MADE]
        eras, era_by_key, ftd = _refine(index, clients.ftd_client, as_of, limit, log, made, ftd)        # 1
        for e in eras:
            e.derived_from = _origin(e, derive) if e.derived else None
        handoffs = cusip_handoffs(eras, ftd)    # the CUSIP links between the eras: the second pass and stage 3 read them
        excluded = _excluded_issuers(eras, derive, verdicts)
        found = _resolve_issuers(eras, ftd, handoffs, clients, log, workers, meter, excluded)           # 2, 2b
        resolutions, securities, review = _resolve_securities(eras, era_by_key, ftd, handoffs, found, clients, log)  # 3
        new = _check_derived(eras, derive, verdicts, ftd, resolutions, found)
        if not new:
            break
        if pass_no == MAX_VERDICT_PASSES:
            log(f"derived eras: {len(new)} more verdicts after {MAX_VERDICT_PASSES} passes, not applied")
            break
        for pair, (verdict, key) in new.items():
            found_keys[verdict][pair] = key
        verdicts |= {pair: verdict for pair, (verdict, _) in new.items()}
    if found_keys[NOT_MADE]:
        log(f"derived eras not made: {len(found_keys[NOT_MADE])} whose price did not carry over onto the line they "
            f"came from ({', '.join(sorted(found_keys[NOT_MADE].values()))})")
    if found_keys[WITHOUT_OLD_ISSUER]:
        log(f"derived eras asked without the old line's issuer: {len(found_keys[WITHOUT_OLD_ISSUER])} "
            f"({', '.join(sorted(found_keys[WITHOUT_OLD_ISSUER].values()))})")
    cusips = _security_cusips(securities, resolutions, ftd)                                              # 4
    return Identity(eras, era_by_key, ftd, found.issuers, resolutions, securities, cusips, review,
                    {k: r.source for k, r in found.answers.items()},
                    frozenset(k for k, v in found.inferred.items() if v.source == TICKER_ROWS), verdicts)


def _pair_of(era: TickerEra, derive: Mapping[tuple[str, str], DerivedFrom]) -> tuple[str, str] | None:
    """The (ticker, new CUSIP) pair a derived era came from: its ticker and the first of its CUSIPs `derive` names."""
    return next(((era.ticker, c) for c in era.ftd_cusips if (era.ticker, c) in derive), None)


def _origin(era: TickerEra, derive: Mapping[tuple[str, str], DerivedFrom]) -> DerivedFrom | None:
    pair = _pair_of(era, derive)
    return derive[pair] if pair is not None else None


def _excluded_issuers(eras: Sequence[TickerEra], derive: Mapping[tuple[str, str], DerivedFrom],
                      verdicts: Mapping[tuple[str, str], str]) -> dict[str, frozenset[int]]:
    """The issuer each era is asked without (era key -> CIKs): the old line's, for a derived era whose pair has
    `WITHOUT_OLD_ISSUER`."""
    out: dict[str, frozenset[int]] = {}
    for e in eras:
        pair = _pair_of(e, derive) if e.derived_from is not None else None
        if pair is not None and verdicts.get(pair) == WITHOUT_OLD_ISSUER and e.derived_from.issuer_cik is not None:
            out[e.key] = frozenset({e.derived_from.issuer_cik})
    return out


# a source that is a given answer, not a lookup's finding: the caller's own CIK map or a manual override
GIVEN_ANSWERS = ("manual", "cik_map")


def _check_derived(eras: Sequence[TickerEra], derive: Mapping[tuple[str, str], DerivedFrom],
                   verdicts: Mapping[tuple[str, str], str], ftd: FtdIndex, resolutions: Mapping[str, EraResolution],
                   found: "_Issuers") -> dict[tuple[str, str], tuple[str, str]]:
    """The new verdicts on the derived eras that have none yet: (pair -> (verdict, era key)).

    Rule J: an era whose security is the one its step was refused from (`resolutions[era].sec_id ==
    derived_from.sec_id`) is made only when the price carried over across the step (`step_price_ratio`,
    `price_carried`; the issuers play no part): else `NOT_MADE`.

    Rule X: an era from a `merged_out` step whose issuer answer is the origin's issuer (`derived_from.issuer_cik`,
    not None) while its security is another one, and which has no pin and no given answer (`GIVEN_ANSWERS`), is
    `WITHOUT_OLD_ISSUER`: by stage 4b's own finding the old issuer files no periodic report after a `merged_out` step,
    so it cannot be the issuer of the line after it (Coca-Cola Enterprises 2016)."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for e in eras:
        origin = e.derived_from
        pair = _pair_of(e, derive) if origin is not None else None
        if origin is None or pair is None or pair in verdicts:
            continue
        if resolutions[e.key].sec_id == origin.sec_id:
            if not price_carried(step_price_ratio(ftd, e.ticker, origin.old_cusip, pair[1])):
                out[pair] = (NOT_MADE, e.key)
        elif (origin.why == "merged_out" and origin.issuer_cik is not None
              and cik_of(found.issuers, e.key) == origin.issuer_cik
              and e.cik_pin is None and not e.sec_id_pin and found.answers[e.key].source not in GIVEN_ANSWERS):
            out[pair] = (WITHOUT_OLD_ISSUER, e.key)
    return out


def _refine(index: ObservationIndex, ftd_client: Any, as_of: date, limit: int | None,
            log: Callable[[str], None], derive: Collection[tuple[str, str]] = (),
            ftd: FtdIndex | None = None) -> tuple[list[TickerEra], dict[str, TickerEra], FtdIndex]:
    """1. The observation eras, refined on SEC fails-to-deliver evidence: the run's
    fails index is opened over `ftd_client` with the eras' tickers' and CUSIPs' rows
    first (they date each era's real last sighting), then each era is split further
    on that evidence (a CUSIP switch, or a gap no FTD row bridges). Every later step
    works on the refined eras. The index's run's fails window runs from 30 days before
    the first sighting to the run date. Returns the eras, by key too, and the index."""
    eras = index.eras()
    if limit:
        eras = eras[:limit]
    log(f"{len(eras)} ticker eras")

    if not eras:
        raise ObservationError("no observations to process")

    if ftd is None:
        lo = max(FTD_START, min(date.fromisoformat(e.first) for e in eras) - timedelta(days=30))
        hi = as_of        # an era is followed along its own fails rows for as long as they run (`era_last_seen`)
        class_names: dict[str, list[str]] = defaultdict(list)     # BF-B's names: checks FTD's "BFB" rows
        first_seen: dict[str, str] = {}                           # each ticker's first day (rule A's base-symbol bound)
        for e in eras:
            first_seen[e.ticker] = min(e.first, first_seen.get(e.ticker, e.first))
            if "-" in e.ticker:
                class_names[e.ticker] += e.names
        ftd = FtdIndex.opened(ftd_client, lo, hi, through=as_of, symbols={e.ticker for e in eras},
                              cusips={c for e in eras for c in e.cusips}, names=class_names, first_seen=first_seen)
    eras = refine_eras(eras, ftd, derive)
    era_by_key = eras_by_key(eras)               # raises on a duplicate key: an era is never dropped
    log(f"{len(eras)} eras after the FTD split")
    return eras, era_by_key, ftd


@dataclass(frozen=True)
class FirstPass:
    """One era's first-pass answer out of its two lookups (`choose_first_pass`): `answer`, what the era-level passes
    see (a strong answer, or no CIK), and `fallback`, a weak answer kept aside, which stands only when no pass
    infers an issuer and the era's own fails rows fit it (`EraIssuers.rows_fit`)."""
    answer: TickerResolution
    fallback: TickerResolution | None = None


def choose_first_pass(capped: TickerResolution, followed: TickerResolution) -> FirstPass:
    """The first-pass answer of an era asked at its capped date and at the end of its own fails rows
    (`era_capped_seen`, `era_last_seen`; one answer given twice when they are one day).

    The names the caller observed were in force at the capped date; the security's own Form 25 is at the end of the
    rows. So: both strong (`TickerResolution.strong`) and one CIK, the capped date's answer; both strong and two
    CIKs, the followed date's (ITC Holdings 2016, Sprint 2020: another company of the name answers early), unless
    it is today's ticker map and the capped date's is not (by the end of the line a successor holds the ticker and
    the name: Prologis 2011, Merck 2009); one strong, that one (a later rename rejects the right company at the
    end: AMC Networks; a seed's early date finds no Form 25: Coca-Cola Enterprises); neither, no answer, with a
    weak one kept aside (the capped date's first); it stands only when no pass infers an issuer and the era's own
    fails rows fit it (`EraIssuers.rows_fit`)."""
    if capped.strong and followed.strong:
        successor = followed.source == "company_tickers" and capped.source != "company_tickers"
        return FirstPass(followed if followed.cik != capped.cik and not successor else capped)
    if capped.strong or followed.strong:
        return FirstPass(capped if capped.strong else followed)
    fallback = capped if capped.cik is not None else followed if followed.cik is not None else None
    blank = capped if capped.cik is None else followed if followed.cik is None else \
        TickerResolution(capped.ticker, None, None, "none")
    return FirstPass(blank, fallback)


@dataclass
class _Issuers:
    """Stage 2's answer for each era: the lookup's (`answers`, by era key: the first pass's, or the 2b or second-pass
    answer that replaced it), its `Issuer` (`issuers`: CIK and EDGAR names, for the eras whose issuer is known), the
    two dates the lookup was asked at (`capped`, and `last_seen`, the end of the era's own fails rows), the issuer
    CIKs whose names read was degraded, the 2b and second-pass answers (`inferred`), the second pass's contradictions
    of first-pass answers (`disagreements`), and the eras whose 2b or second-pass reads rested on a failed request or
    a stale copy (`degraded`)."""
    answers: dict[str, TickerResolution]
    issuers: dict[str, Issuer]
    capped: dict[str, str]
    last_seen: dict[str, str]
    names_degraded: set[int]
    inferred: dict[str, InferredIssuer]
    disagreements: dict[str, InferredIssuer]
    degraded: set[str]
    excluded: Mapping[str, frozenset[int]] = field(default_factory=dict)


def _resolve_issuers(eras: list[TickerEra], ftd: FtdIndex, handoffs: Sequence[Handoff], clients: Sources,
                     log: Callable[[str], None], workers: int, meter: StageMeter,
                     excluded: Mapping[str, frozenset[int]] = _NO_PAIRS) -> _Issuers:
    """2. The issuer CIK of each era, resolved at two dates, its capped date and the end of its own fails rows, one
    answer chosen (`choose_first_pass`), with each era's own pin and name (a pin or name looked up by
    (ticker, date) can belong to a neighbouring era when the last sighting falls
    between the two: FTD rows of a shared CUSIP carry KORS@2012's last sighting
    past KORS@2014's first observation). The lookup tier that found it
    (cik_map, manual, company_tickers, ...) is kept for the delisting rows'
    resolution_source. Then 2b's check of the name-search answers, and the second pass
    (`EraIssuers.infer`, never saved, run with each date) for the eras left with no CIK and no pin: a renamed issuer
    found by its 8-K frequency or by a CUSIP handoff. Then each issuer's EDGAR names
    (`IssuerRecord.names`), which stage 3 checks CUSIPs and FIGI names against:
    an issuer whose read failed has none (its eras are checked against their
    observed names only) and is reported degraded. A weak first-pass answer (its name does not agree) stands only
    where no pass infers an issuer and the era's own fails rows fit it (`EraIssuers.rows_fit`).

    `excluded`: era key -> the CIKs the era is asked without (rule X: a derived era never takes the old line's issuer):
    every resolver tier leaves them out, and an answer 2b or the second pass gives is dropped when it is one."""
    resolver, record = clients.resolver, clients.issuers
    capped, last_seen = capped_sightings(eras, ftd), last_sightings(eras, ftd)

    def both(lookup, e: TickerEra) -> tuple[TickerResolution, TickerResolution]:
        """The era's answers at its capped date and at the end of its rows (one lookup when they are one day)."""
        ex = {"exclude": excluded[e.key]} if e.key in excluded else {}       # the argument only where it is asked
        at_cap = lookup.resolve(e.ticker, capped[e.key], pin=e.cik_pin, name=e.name, since=e.first, **ex)
        if last_seen[e.key] <= capped[e.key]:
            return at_cap, at_cap
        return at_cap, lookup.resolve(e.ticker, last_seen[e.key], pin=e.cik_pin, name=e.name, since=e.first, **ex)

    mark = meter.start()
    if workers > 1:
        # Warm the EDGAR caches: each era resolved on a worker thread by a shadow
        # lookup (a snapshot of this memo that saves nothing), its answers thrown
        # away. The resolve below then runs one era at a time, in order, on this
        # thread, and finds its requests answered.
        warm(eras, both, workers=workers, state=resolver.shadow, name="issuer resolution")
    first = {e.key: choose_first_pass(*both(resolver, e)) for e in eras}
    resolver.flush()
    answers = {key: f.answer for key, f in first.items()}
    log(f"issuer lookups: {sum(last_seen[k] > capped[k] for k in first)} eras asked at two dates, "
        f"{sum(f.fallback is not None for f in first.values())} weak answers kept aside")
    passes = EraIssuers(record, resolver.frequency_candidates)
    tickers = {e.key: e.ticker for e in eras}
    checked = {k: v for k, v in passes.check_names(eras, ftd, last_seen, answers).items()           # 2b
               if v.cik not in excluded.get(k, ())}
    for key, found in checked.items():
        answers[key] = TickerResolution(tickers[key], found.cik, None, found.source)
    log(f"name checks: {len(checked)} name-search answers replaced"
        + (f" ({', '.join(f'{k} -> {v.cik}' for k, v in sorted(checked.items()))})" if checked else ""))
    # The second pass with the capped dates, then with the followed ones, on the same first-pass answers: an era
    # the first run answers keeps that answer (rule B reads the 8-K filers of the 120 days before its date).
    ciks = {k: r.cik for k, r in answers.items()}
    by_cap, by_end = (passes.infer(eras, ftd, dates, ciks, handoffs) for dates in (capped, last_seen))
    def allowed(found: dict[str, InferredIssuer]) -> dict[str, InferredIssuer]:
        """One pass's answers without those naming an issuer the era is asked without (before the passes merge: the
        capped pass's excluded answer would otherwise win the merge and be dropped, losing the followed pass's)."""
        return {k: v for k, v in found.items() if v.cik not in excluded.get(k, ())}

    inferred = {**allowed(by_end.inferred), **allowed(by_cap.inferred)}
    disagreements = {**allowed(by_end.disagreements), **allowed(by_cap.disagreements)}
    for key, found in inferred.items():
        answers[key] = TickerResolution(tickers[key], found.cik, None, found.source)
    by_key = {e.key: e for e in eras}
    dropped = []
    for key, f in first.items():      # a weak answer stands only where no pass inferred an issuer and its rows fit
        if answers[key].cik is not None or f.fallback is None:
            continue
        if passes.rows_fit(by_key[key], f.fallback.cik, era_rows(by_key[key], ftd, last_seen[key])):
            answers[key] = f.fallback
        else:
            dropped.append(key)
    if dropped:
        log(f"weak answers dropped: {len(dropped)} whose company the era's own fails rows do not fit "
            f"({', '.join(sorted(dropped))})")
    log(f"resolver's second pass: {len(inferred)} issuers inferred, "
        f"{len(disagreements)} first-pass answers its CUSIP evidence contradicts")
    ciks = {k: r.cik for k, r in answers.items()}
    issuer_ciks = [cik for cik in dict.fromkeys(ciks.values()) if cik]
    if workers > 1:
        warm(issuer_ciks, clients.edgar.submissions, workers=workers, name="issuer names")
    reads = record.watch()
    issuer_names = {cik: record.names(cik) for cik in issuer_ciks}
    names_degraded = set(reads.ciks)
    meter.done("issuer resolution", mark)
    # stage 2b's answers are reported as issuer_inferred, as the second pass's are
    return _Issuers(answers, issuers_by_era(ciks, issuer_names), capped, last_seen, names_degraded,
                    {**checked, **inferred}, disagreements, set(passes.degraded), excluded)


def _trading_span(ftd: FtdIndex, cusip: str) -> tuple[str, str] | None:
    """The first and last day a CUSIP's fails rows show it trading (`FtdIndex.trading_rows`), None for none."""
    rows = ftd.trading_rows([cusip])
    return (rows[0].date, rows[-1].date) if rows else None


BANKRUPTCY_LEAD_DAYS = 60      # ... and that 8-K is no more than this many days before the old CUSIP's last fails row
BANKRUPTCY_DAYS = 365          # an issuer's Item 1.03 8-K this many days before a CUSIP's first row: it began in a bankruptcy


class _WentBankrupt:
    """Whether the line went through a bankruptcy between the CUSIP `old` and the CUSIP `new` (decision 9: its equity
    after emerging is a new security, whatever its CUSIP or ticker). Two readings the identity stage can make before
    stage 5 finds the ending: the old CUSIP traded under a bankruptcy symbol (the ticker with a Q, CHKAQ beside CHK,
    in its fails rows), or the old issuer (`cik`) filed an 8-K Item 1.03 within `BANKRUPTCY_DAYS` before the new
    CUSIP's first fails row and no earlier than `BANKRUPTCY_LEAD_DAYS` before the old CUSIP's last (an old line that
    traded on for months after a subsidiary's or a past filing is no bankruptcy: Duke Energy 2011). A filings read
    that failed or was stale counts as no bankruptcy, and its CIK is kept in `degraded` for the review rows."""

    def __init__(self, ftd: FtdIndex, record: IssuerRecord) -> None:
        self.ftd, self.record, self.degraded = ftd, record, set()

    def __call__(self, old: str, new: str, cik: int | None) -> bool:
        symbols = {r.symbol for r in self.ftd.by_cusip(old)}
        if any(s.endswith("Q") and len(s) >= 4 and (s[:-1] in symbols or s[:-2] in symbols) for s in symbols):
            return True
        rows, olds = self.ftd.by_cusip(new), self.ftd.by_cusip(old)
        first = parse_day(rows[0].date) if rows else None
        last = parse_day(olds[-1].date) if olds else None
        if cik is None or first is None or last is None:
            return False
        reads = self.record.watch()
        filings = self.record.filings(cik)
        if reads.tripped():
            self.degraded.add(cik)
        return any((parse_day(f.report_date) or parse_day(f.filing_date)) >= last - timedelta(days=BANKRUPTCY_LEAD_DAYS)
                   for f in bankruptcy_8ks(filings, first, before=BANKRUPTCY_DAYS, after=0))


def _went_bankrupt(ftd: FtdIndex, record: IssuerRecord) -> _WentBankrupt:
    return _WentBankrupt(ftd, record)


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
    went_bankrupt = _went_bankrupt(ftd, clients.issuers)
    resolutions, detached = resolve_with_identity_guard(
        FigiResolver(clients.figi, log=log, cusip_span=lambda c: _trading_span(ftd, c),
                     foreign=foreign_ticker_eras(eras, ftd, issuers)),
        eras, issuers=issuers, cusips=cusips, handoffs=handoffs, unconfirmed=guarded_eras(eras, ftd),
        bankrupt_between=went_bankrupt)
    securities = build_securities(resolutions, era_by_key, issuers)
    review: list[ReviewItem] = detached_review(detached, era_by_key, resolutions, issuers)
    for key, res in resolutions.items():
        era = era_by_key[key]
        for flag in res.flags:
            review.append(ReviewItem(res.sec_id or "", era.ticker, cik_of(issuers, key), flag,
                                     f"{era.key} {era.name or ''}".strip(), last_seen=era.last))
    for e in eras:
        ex = {"exclude": found.excluded[e.key]} if e.key in found.excluded else {}    # the key the lookup was made under
        if any(clients.resolver.is_degraded(e.ticker, day, name=e.name, **ex)
               for day in {found.capped[e.key], found.last_seen[e.key]}) or e.key in found.degraded:
            review.append(degraded_item(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key),
                                         f"{e.key} {e.name or ''}: issuer resolution",
                                         "; its answer was used for this run but not saved", last_seen=e.last))
    for e in eras:        # the composite guard asked this issuer's filings and the read failed: it kept the pick
        if (cik_of(issuers, e.key) in went_bankrupt.degraded
                and resolutions[e.key].source not in ("pin", "cusip")):
            review.append(degraded_item(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key),
                                         f"{e.key} {e.name or ''}: the check for a bankruptcy between its CUSIPs",
                                         "; the era was kept on the composite its pick gave", last_seen=e.last))
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


def _security_cusips(securities: dict[str, Security], resolutions: dict[str, EraResolution],
                     ftd: FtdIndex) -> dict[str, list[str]]:
    """4. Each security's CUSIPs over its whole life: every CUSIP of each of its
    eras that resolved to its FIGI (a reverse split's old and new CUSIP both),
    their rows held over the run's fails window, to the run date (`FtdIndex.follow`)."""
    sec_cusips = {sid: list(dict.fromkeys(c for e in s.eras for c in resolutions[e.key].cusips))
                  for sid, s in securities.items()}
    ftd.follow(cusips={c for v in sec_cusips.values() for c in v})
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


DERIVED_NAME_DAYS = 30     # a derived era is named by the description its CUSIP's rows carry in their first days


def _derived_era(era: TickerEra, part_rows: Sequence[FtdRow], kept: tuple[str, ...]) -> TickerEra:
    """The era of a line no caller observation names: one derived observation dated at the part's first row and named
    by the commonest description of its CUSIP's rows in their first `DERIVED_NAME_DAYS` days. No pin: the observation
    carries none, and the era's own CUSIPs are the part's."""
    first = part_rows[0].date
    until = (date.fromisoformat(first) + timedelta(days=DERIVED_NAME_DAYS)).isoformat()
    seen = Counter(r.description for r in part_rows if r.cusip == kept[0] and r.date <= until)
    name = description_name(seen.most_common(1)[0][0]) if seen else ""
    return TickerEra(era.ticker, first, first, [Observation(era.ticker, first, name or None, derived=True)],
                     ftd_cusips=kept)


def _split_era(era: TickerEra, rows: list[FtdRow], *, contested: bool,
               derive: Collection[str] = ()) -> list[TickerEra]:
    """The era split on its rows. `derive`: CUSIPs approved for the era's ticker (as the era spells it), already
    without any CUSIP that has rows under the ticker from the next era's first day on (`refine_eras`)."""
    out: list[TickerEra] = []
    for g_obs, g_rows in _cut(era.observations, rows, _gap_cuts(era.observations, rows)):
        follows = False                   # the part before is an era of this group: a line is derived only after one
        for obs, part_rows in _cut(g_obs, g_rows, _switch_cuts(g_rows)):
            kept = _kept_cusips(part_rows)
            if not obs:                   # an FTD-only side (another holder of the ticker, a tail) is no era ...
                follows = follows and bool(kept) and kept[0] in derive      # ... unless a derived line (`derive`)
                if follows:
                    out.append(_derived_era(era, part_rows, kept))
                continue
            follows = True
            names = [o.name for o in obs if o.name]
            if contested and names:
                # Another era of this ticker has observations on the same dates
                # (a backfilled name): the ticker's rows are only this era's when
                # their description agrees with its names.
                kept = tuple(c for c in kept if _described(c, part_rows, names))
            out.append(replace(era, first=obs[0].as_of, last=obs[-1].as_of, observations=list(obs),
                               ftd_cusips=kept))
    return out


def refine_eras(eras: Sequence[TickerEra], ftd: FtdIndex,
                derive: Collection[tuple[str, str]] = ()) -> list[TickerEra]:
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

    `derive`: (ticker, CUSIP) pairs the caller approved (`derived_lines.derivable`): a part of the ticker's rows with
    no observation whose kept CUSIP is approved, that follows an era of its gap group and whose CUSIP has no rows
    under the ticker from the next era's first day on, is an era with one derived observation (`_derived_era`). A
    pair names the ticker as the era spells it ("BF-B", as the caller observed it, not the fails way "BFB").
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
        later = {r.cusip for r in ftd.by_symbol(e.ticker, nxt)} if nxt and derive else set()   # the next era's own
        approved = {c for t, c in derive if t == e.ticker and c not in later}
        out += _split_era(e, ftd.by_symbol(e.ticker, lo, hi), contested=contested, derive=approved)
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


def _later_own_rows(era: TickerEra, ftd: FtdIndex, after: str, horizon_days: int, stop: str | None = None) -> list[str]:
    """The days of the era's own rows (`_own_rows`) under its ticker in the `horizon_days` after `after`, before `stop`."""
    lo = (date.fromisoformat(after) + timedelta(days=1)).isoformat()
    hi = (date.fromisoformat(after) + timedelta(days=horizon_days)).isoformat()
    return [r.date for r in _own_rows(era, ftd.by_symbol(era.ticker, lo, hi)) if stop is None or r.date < stop]


def era_capped_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400) -> str:
    """The era's capped date: its last observation, or a later FTD row of its
    own (`_own_rows`) under its ticker within `horizon_days`. The names the
    caller observed were in force around this date."""
    return max([era.last, *_later_own_rows(era, ftd, era.last, horizon_days)])


def era_last_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400, until: str | None = None) -> str:
    """The era's last sighting: its capped date (`era_capped_seen`); an era with
    FTD CUSIPs of its own is then followed along them, each step at most
    `horizon_days` past the row before, to the last row before `until` (the
    day the ticker's next era begins; None: no later era): the security's own
    fails rows say how long it traded, whatever the caller observed (one seed
    in 2008, Starwood's rows to 2016)."""
    last = era_capped_seen(era, ftd, horizon_days)
    while era.ftd_cusips:
        more = _later_own_rows(era, ftd, last, horizon_days, until)
        if not more:
            break
        last = max(more)
    return last


def last_sightings(eras: Sequence[TickerEra], ftd: FtdIndex) -> dict[str, str]:
    """Each era's last sighting by era key (`era_last_seen`), an era followed no
    further than the day its ticker's next era begins."""
    starts: dict[str, list[str]] = defaultdict(list)
    for e in eras:
        starts[e.ticker].append(e.first)
    return {e.key: era_last_seen(e, ftd, until=min((f for f in starts[e.ticker] if f > e.first), default=None))
            for e in eras}


def capped_sightings(eras: Sequence[TickerEra], ftd: FtdIndex) -> dict[str, str]:
    """Each era's capped date by era key (`era_capped_seen`)."""
    return {e.key: era_capped_seen(e, ftd) for e in eras}


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
                    issuer_cusips[c][cusip].add(name_class_letter(by_key[k].name))
            return known, issuer_cusips

        while True:
            known, issuer_cusips = issuers_now()
            new: dict[str, InferredIssuer] = {}
            for e in todo:
                if e.key in out:
                    continue
                self._reset()
                got = self._named(e, self._handoff(rows[e.key], links[e.key], known, ftd, issuer_cusips,
                                                   name_class_letter(e.name)), last_seen[e.key])
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
                found = self._linked_issuers(links[key], known, ftd, issuer_cusips,
                                             name_class_letter(by_key[key].name))
                candidates = [*found, *([got.cik] if got.source == "efts_frequency_renamed" else [])]
                if self._guard(candidates, rows[key]) != got.cik:
                    dropped.append(key)
                self._mark(by_key[key])
            if not dropped:
                break
            for key in dropped:
                del out[key]
        known, issuer_cusips = issuers_now()
        for e in todo:                               # D, after the fixed point: it rests on the answers the others made
            if e.key in out:
                continue
            self._reset()
            got = self._issuer_code(e, eras, known, last_seen)
            if got is not None:
                out[e.key] = got
            self._mark(e)
        disagreements: dict[str, InferredIssuer] = {}
        for e in sorted(eras, key=lambda e: e.key):
            first = first_pass.get(e.key)
            if first is None or e.cik_pin is not None or e.sec_id_pin or len(rows[e.key]) < ERA_MIN_ROWS:
                continue
            self._reset()
            got = self._named(e, self._handoff(rows[e.key], links[e.key], known, ftd, issuer_cusips,
                                               name_class_letter(e.name)), last_seen[e.key])
            if got is not None and got.cik != first:
                disagreements[e.key] = got
        return SecondPass(out, disagreements)

    def _issuer_code(self, era: TickerEra, eras: Sequence[TickerEra], known: dict[str, int],
                     last_seen: dict[str, str]) -> InferredIssuer | None:
        """Rule D (`cusip_issuer`, FB-004 part c, FNFV): a CUSIP's first six characters name its issuer, whatever the
        security is called (FNFV Group, a tracking stock of Fidelity National Financial, 31620R402; the company's own
        31620R105). The one issuer of the other eras that hold a CUSIP of the era's issuer code over the same dates
        (`known`: the first pass's answers and the rules above), when it existed by the era's first sighting. Eras
        of two issuers, none, or no CUSIP: None. The name is no check here, as it is for B and C: the code is the
        evidence, and a tracking stock is named for its group."""
        codes = {c[:6] for c in (*era.ftd_cusips, *era.cusips)}
        if not codes:
            return None
        ciks = {known[o.key] for o in eras
                if o.key != era.key and o.key in known and codes & {c[:6] for c in (*o.ftd_cusips, *o.cusips)}
                and o.first <= last_seen[era.key] and era.first <= last_seen[o.key]}
        if len(ciks) != 1:
            return None
        cik = next(iter(ciks))
        if not self.issuers.existed_by(cik, era.first):
            return None
        return InferredIssuer(cik, "cusip_issuer", f"its CUSIP's issuer code {sorted(codes)[0]} is the issuer's own")

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

    def rows_fit(self, era: TickerEra, cik: int, rows: list[FtdRow]) -> bool:
        """Whether the era's own fails rows are this company's: at least `ERA_MIN_ROWS` of them, and guard G's row
        test (`_fits_rows`). A weak first-pass answer must pass it to stand (`_resolve_issuers`): the resolver took
        it although its name does not agree with the observed one, and most such answers are another company's
        (US Bancorp's 8-K frequency answer was Prologis). A read that fails marks the era degraded, as the
        passes' own reads do."""
        self._reset()
        fits = len(rows) >= ERA_MIN_ROWS and self._fits_rows(cik, rows)
        self._mark(era)
        return fits

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

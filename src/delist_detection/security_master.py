"""The security master: observation eras resolved to US composite FIGIs and
merged into securities (their dated ticker and CUSIP ranges are `history.py`'s).

A security is one share class traded in the US (CONTEXT.md). Eras of different
tickers that resolve to the same FIGI (FB, later META) are one security, and so
are two eras of one ticker that `refine_eras` split apart but that resolve to
the same FIGI (a reverse split's new CUSIP, a gap no FTD row bridged).
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from .figi_resolution import (
    FigiCandidate, accept, bloomberg_ticker, filter_query, is_placeholder, placeholder_id, security_kind,
    share_class_from_name, us_candidates,
)
from .ftd import FTD_START, FtdIndex, FtdRow, is_deleted_symbol
from .trading_calendar import add_trading_days
from .names import description_matches, names_agree
from .observations import (
    ERA_GAP_DAYS, Observation, TickerEra, eras_by_key, number_eras, observation_conflicts,
)
from .review_triage import ReviewItem

ERA_MIN_RUN = 3          # an FTD CUSIP run shorter than this is noise, not a CUSIP switch


@dataclass
class Security:
    sec_id: str
    issuer_cik: int | None
    share_class: str
    name: str
    security_type: str
    observed: bool
    figi_source: str
    kind: str = "common"
    eras: list[TickerEra] = field(default_factory=list)

    def row(self) -> dict:
        return {"sec_id": self.sec_id, "issuer_cik": self.issuer_cik, "share_class": self.share_class,
                "name": self.name, "security_type": self.security_type, "observed": self.observed,
                "figi_source": self.figi_source}


@dataclass(frozen=True)
class EraResolution:
    era_key: str
    sec_id: str | None
    source: str
    candidate: FigiCandidate | None
    flags: tuple[str, ...]
    # The era's CUSIPs that belong to sec_id: every tried CUSIP whose OpenFIGI
    # answer is accepted as that composite, plus, for an era resolved by ticker
    # or name, its own FTD CUSIP when OpenFIGI has no US line for it; for a pin
    # or a placeholder (nothing to check against) the era's first candidate CUSIP.
    cusips: tuple[str, ...] = ()


@dataclass(frozen=True)
class Issuer:
    """The issuer (CONTEXT.md) of an era's security: its CIK, and every name
    EDGAR records for it, current and former (`evidence.edgar_names`)."""
    cik: int
    names: tuple[str, ...] = ()


def issuers_by_era(ciks: Mapping[str, int | None],
                   names: Mapping[int, Sequence[str]] | None = None) -> dict[str, Issuer]:
    """Each era's `Issuer`, by era key, for the eras whose issuer CIK is known
    (`ciks`: era key -> CIK or None), named from `names` (CIK -> EDGAR names)."""
    names = names or {}
    return {k: Issuer(cik, tuple(names.get(cik, ()))) for k, cik in ciks.items() if cik is not None}


def cik_of(issuers: Mapping[str, Issuer], era_key: str) -> int | None:
    """The issuer CIK of the era `era_key`, None when its issuer is unknown."""
    issuer = issuers.get(era_key)
    return issuer.cik if issuer is not None else None


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


SWITCH_DAYS = 5               # trading days between an old CUSIP's last row and a new one's first
SWITCH_TAIL_DAYS = 10         # the old CUSIP trades under no symbol this many trading days past its last row
NEW_CUSIP_MARGIN_DAYS = 30    # a CUSIP first seen closer than this to the scanned window's start may be older


@dataclass(frozen=True)
class Handoff:
    """A CUSIP link from the era `era_key` to the era `to_key`, whose issuer it
    may share (`cusip_handoffs`). `kind` is "shared_cusip" (both eras have
    `cusip`) or "cusip_handoff" (a switch: `cusip`, which first failed on
    `since`, last traded under the era's ticker on `last` as `to_key`'s
    `new_cusip` began, on `day`); `descriptions` are the old CUSIP's fails
    descriptions under the era's ticker, each with the date of its first row,
    which a name the issuer carried by then must match."""
    era_key: str
    to_key: str
    kind: str
    cusip: str
    new_cusip: str = ""
    day: str = ""
    descriptions: tuple[tuple[str, str], ...] = ()
    since: str = ""
    last: str = ""


def trades_at_switch(ftd: FtdIndex, h: Handoff, cusips: Collection[str]) -> bool:
    """Whether any of `cusips` (another line of the switch's issuer) that began
    before the switch trades, not under a deleted symbol, within `SWITCH_DAYS`
    trading days of the switch `h`: then the issuer is an acquirer that renamed
    itself at the merger (Wisconsin Energy, WEC Energy Group from Integrys' last
    day), not the old CUSIP's renamed issuer. A CUSIP whose first row falls
    inside that window was born at the switch itself (ViacomCBS' class A, as
    CBS's class B switched)."""
    days = sorted([date.fromisoformat(h.last), date.fromisoformat(h.day)])
    lo = add_trading_days(days[0], -SWITCH_DAYS).isoformat()
    hi = add_trading_days(days[1], SWITCH_DAYS).isoformat()
    older = [c for c in sorted(cusips) if (rows := ftd.by_cusip(c)) and rows[0].date < lo]
    return any(lo <= r.date <= hi for r in ftd.trading_rows(older))


def cusip_handoffs(eras: Sequence[TickerEra], ftd: FtdIndex) -> list[Handoff]:
    """The CUSIP links between the eras, pure (no issuer is known here; the
    resolver's second pass reads them):

    - shared CUSIP: two eras hold one CUSIP (observed, or of their FTD rows):
      MHP and MHFI, one McGraw-Hill line under two tickers;
    - switch: an era's FTD CUSIP last trades under its ticker (not under a
      deleted "...XXXX" symbol) within `SWITCH_DAYS` trading days of the first
      fails row of another era's FTD CUSIP; that new CUSIP has no earlier row,
      and starts at least `NEW_CUSIP_MARGIN_DAYS` after the fails window scanned
      for its ticker opens (else it may be older than the rows show); the old
      CUSIP trades under no symbol more than `SWITCH_TAIL_DAYS` trading days
      later (a ticker change that kept the CUSIP is a shared CUSIP instead).
      KORS's G60754101 last trades 2019-01-03, CPRI's G1890L107 first fails
      2019-01-02. A merger's acquirer is no switch (its CUSIP is older); a
      spin-off's is, and the resolver refuses it (the rename check)."""
    cusips_of = {e.key: set(e.ftd_cusips) | set(e.cusips) for e in eras}
    holders: dict[str, list[str]] = defaultdict(list)
    for e in eras:
        for c in sorted(cusips_of[e.key]):
            holders[c].append(e.key)
    out = [Handoff(e.key, k, "shared_cusip", c) for e in eras for c in sorted(cusips_of[e.key])
           for k in holders[c] if k != e.key]
    starts: list[tuple[str, str, str]] = []               # (first fails row, era key, CUSIP): the new CUSIPs
    for e in eras:
        opened = ftd.scanned_from(e.ticker)
        for c in e.ftd_cusips:
            rows = ftd.by_cusip(c)
            if rows and opened is not None and \
                    date.fromisoformat(rows[0].date) >= opened + timedelta(days=NEW_CUSIP_MARGIN_DAYS):
                starts.append((rows[0].date, e.key, c))
    starts.sort()
    days = [s[0] for s in starts]
    for e in eras:
        for c in e.ftd_cusips:
            own = [r for r in ftd.by_symbol(e.ticker) if r.cusip == c and not is_deleted_symbol(r.symbol)]
            if not own:
                continue
            last = date.fromisoformat(own[-1].date)
            tail = add_trading_days(last, SWITCH_TAIL_DAYS).isoformat()
            if any(r.date > tail for r in ftd.trading_rows([c])):
                continue
            lo = add_trading_days(last, -SWITCH_DAYS).isoformat()
            hi = add_trading_days(last, SWITCH_DAYS).isoformat()
            first_seen: dict[str, str] = {}
            for r in own:
                first_seen.setdefault(r.description, r.date)
            descriptions = tuple(sorted(first_seen.items()))
            since = ftd.by_cusip(c)[0].date
            for day, key, new in starts[bisect_left(days, lo):bisect_right(days, hi)]:
                if key != e.key and new not in cusips_of[e.key]:
                    out.append(Handoff(e.key, key, "cusip_handoff", c, new, day, descriptions, since,
                                       own[-1].date))
    return out


def _contradicted(era: TickerEra, composite: str, eras: Sequence[TickerEra], issuers: Mapping[str, Issuer],
                  confirmed: Mapping[str, str], *, other_issuers: bool = True) -> bool:
    """Whether another era's pin or CUSIP (`confirmed`: era key -> composite)
    rules out `composite` for `era`, a candidate that only the issuer's EDGAR
    names accept. An issuer's names can outlive its stock and match a later
    line: the bankrupt General Growth Properties (CIK 895648) is now "GGP, Inc.",
    the name of the new issuer's GGP line; Jacobs Engineering's names match
    today's JACOBS SOLUTIONS line, a new composite since the 2022 reorganization.
    So the candidate is ruled out when an era of another known issuer is
    confirmed on it, or when an era of the same issuer and share class is
    confirmed on another composite over overlapping dates. With
    `other_issuers=False` only the second test applies: a pick the era's own
    observed name accepts may well sit on a line another issuer's era is
    confirmed on, since a line keeps its composite through a change of issuer
    (Merck's 2009 reverse merger, Medtronic's and Eaton's redomiciles)."""
    cik, cls = cik_of(issuers, era.key), share_class_from_name(era.name)
    for other in eras:
        comp = confirmed.get(other.key)
        if comp is None or other.key == era.key:
            continue
        other_cik = cik_of(issuers, other.key)
        if comp == composite:
            if other_issuers and other_cik is not None and other_cik != cik:
                return True
        elif (other_cik == cik and share_class_from_name(other.name) == cls
              and other.first <= era.last and era.first <= other.last):
            return True
    return False


def _cusip_job(c: str) -> dict:
    return {"idType": "ID_CINS" if c[:1].isalpha() else "ID_CUSIP", "idValue": c, "includeUnlistedEquities": True}


def _link_text(h: Handoff) -> str:
    if h.kind == "shared_cusip":
        return f"{h.era_key} shares CUSIP {h.cusip} with {h.to_key}"
    return f"{h.era_key}'s CUSIP {h.cusip} ended as {h.to_key}'s {h.new_cusip} began on {h.day}"


def _handoff_joins(eras: Sequence[TickerEra], issuers: Mapping[str, Issuer], handoffs: Sequence[Handoff],
                   unpicked: Collection[str], confirmed: Mapping[str, str]) -> dict[str, tuple[str, str, Handoff]]:
    """The composite each era of `unpicked` (no FIGI pick, a known issuer) takes
    through its CUSIP links (`handoffs`, `cusip_handoffs`'): era key -> (composite,
    the confirmed era it is taken from, the link that reached it).

    Only a link between two eras of one issuer and share class counts. The
    unpicked eras that share a CUSIP form a chain; the chain reaches every
    composite that a link from one of its members leads to an era confirmed
    on (`confirmed`: a pin or a CUSIP), and joins it when it reaches exactly
    one (two composites: none)."""
    by_key = {e.key: e for e in eras}

    def group(key: str) -> tuple[int | None, str]:
        return cik_of(issuers, key), share_class_from_name(by_key[key].name)

    links = sorted((h for h in handoffs if h.era_key in by_key and h.to_key in by_key
                    and group(h.era_key)[0] is not None and group(h.era_key) == group(h.to_key)),
                   key=lambda h: (h.era_key, h.kind != "shared_cusip", h.to_key))
    chain = {k: k for k in unpicked}

    def root(k: str) -> str:
        while chain[k] != k:
            k = chain[k]
        return k

    for h in links:
        if h.kind == "shared_cusip" and h.era_key in chain and h.to_key in chain:
            a, b = sorted((root(h.era_key), root(h.to_key)))
            chain[b] = a
    reach: dict[str, dict[str, tuple[str, Handoff]]] = defaultdict(dict)
    for h in links:
        if h.era_key in chain and h.to_key in confirmed:
            reach[root(h.era_key)].setdefault(confirmed[h.to_key], (h.to_key, h))
    out: dict[str, tuple[str, str, Handoff]] = {}
    for k in chain:
        found = reach.get(root(k), {})
        if len(found) == 1:
            [(composite, (anchor, h))] = found.items()
            out[k] = (composite, anchor, h)
    return out


class FigiResolver:
    MAX_CUSIPS = 3

    def __init__(self, figi, log: Callable[[str], None] | None = None) -> None:
        self.figi = figi
        self.log = log or (lambda msg: None)

    def resolve_many(self, eras: Sequence[TickerEra], *, issuers: Mapping[str, Issuer],
                     cusips: Mapping[str, list[str]], handoffs: Sequence[Handoff] = (),
                     unconfirmed: Collection[str] = (), barred: Collection[str] = ()) -> dict[str, EraResolution]:
        """Each era's FIGI (spec §8.3): a `sec_id` pin; else the first of its
        CUSIPs (`cusips`, at most `MAX_CUSIPS`) that OpenFIGI maps to one US
        composite; else its ticker, then a name search, where a candidate is
        accepted only when its name agrees with the era's observed names or,
        failing that, its issuer's EDGAR names, current and former
        (`issuers`, by era key: Northeast Utilities, seen under ES before its
        rename, is accepted onto Bloomberg's EVERSOURCE ENERGY line because
        EDGAR lists both names for CIK 72741). A dead line Bloomberg renamed to
        its acquirer is still rejected: the acquirer's name is not one of the
        target issuer's names. A candidate taken only through the EDGAR names,
        or through a CUSIP handoff (`handoffs`, spec §17), must also not
        contradict another era's pin or CUSIP (`_contradicted`). A sibling era
        of the same issuer and class left with no pick of its own instead
        follows such a pick onto its composite when `_contradicted` does not
        rule it out there too; if it does, or if the group's picks disagree on
        the composite, the whole group is withdrawn to the placeholder
        together. Else the issuer's placeholder, or unresolved with no
        issuer.

        The ticker and name tiers answer with whoever holds the ticker or name
        today, so neither is asked for an era of `unconfirmed` (no fails row
        shows its ticker then: `unconfirmed_eras`) or of `barred` (a weak pick
        `crossing_weak_eras` took back out). A plain own-name pick is checked
        by `_contradicted`'s same-issuer test (another line of its issuer and
        class confirmed over its dates). An `unconfirmed` era with no pick of its own is
        a ticker a snapshot backfilled: it is placed ("backfill") on the one
        composite an era of its issuer and class is confirmed on (by a pin or
        a CUSIP) over overlapping dates, when there is exactly one."""
        eras_by_key(eras)                                # every era is keyed by era.key below: refuse duplicates
        out: dict[str, EraResolution] = {}
        jobs: list[dict] = []
        plan: dict[str, tuple[list[str], list[int], int]] = {}
        for era in eras:
            tried = cusips.get(era.key, [])[: self.MAX_CUSIPS]
            if era.sec_id_pin:
                out[era.key] = EraResolution(era.key, era.sec_id_pin, "pin", None, (), tuple(tried[:1]))
                continue
            idx = []
            for c in tried:
                idx.append(len(jobs))
                jobs.append(_cusip_job(c))
            t_idx = len(jobs)
            jobs.append({"idType": "TICKER", "idValue": bloomberg_ticker(era.ticker), "includeUnlistedEquities": True})
            plan[era.key] = (tried, idx, t_idx)
        answers = self.figi.map(jobs) if jobs else []
        found_of: dict[str, list[list[FigiCandidate]]] = {}
        by_cusip_of: dict[str, list[FigiCandidate | None]] = {}
        confirmed = {k: r.sec_id for k, r in out.items()}      # era -> composite of its pin or CUSIP
        for era in eras:
            if era.key in out:
                continue
            _, idx, _ = plan[era.key]
            found_of[era.key] = [us_candidates(answers[i].get("data") or []) for i in idx]
            by_cusip_of[era.key] = [accept(f, ticker=era.ticker, names=era.names, via_cusip=True)
                                    for f in found_of[era.key]]
            c = next((got for got in by_cusip_of[era.key] if got), None)
            if c:
                confirmed[era.key] = c.composite

        def named(era: TickerEra, cands: list[FigiCandidate]) -> tuple[FigiCandidate | None, bool]:
            """The accepted candidate, and whether only the EDGAR names accepted it."""
            c = accept(cands, ticker=era.ticker, names=era.names, via_cusip=False)
            issuer = issuers.get(era.key)
            edgar = issuer.names if issuer is not None else ()
            if c is not None:
                if _contradicted(era, c.composite, eras, issuers, confirmed, other_issuers=False):
                    return None, False
                return c, False
            if not edgar:
                return None, False
            c = accept(cands, ticker=era.ticker, names=[*era.names, *edgar], via_cusip=False)
            if c is None or _contradicted(era, c.composite, eras, issuers, confirmed):
                return None, False
            return c, True

        # era -> (source, composite, candidate, weak: guard (c) may withdraw it)
        picks: dict[str, tuple[str, str, FigiCandidate | None, bool]] = {}
        for era in eras:
            if era.key in out:
                continue
            c = next((got for got in by_cusip_of[era.key] if got), None)
            if c:
                picks[era.key] = ("cusip", c.composite, c, False)
                continue
            if era.key in unconfirmed or era.key in barred:
                continue                      # the ticker and name tiers answer with today's holder
            c, edgar_only = named(era, us_candidates(answers[plan[era.key][2]].get("data") or []))
            if c:
                picks[era.key] = ("ticker", c.composite, c, edgar_only)
                continue
            q = filter_query(era.name or "")
            if q:
                rows = self.figi.filter(q, exchCode="US", includeUnlistedEquities=True)
                c, edgar_only = named(era, us_candidates(rows))
                if c:
                    picks[era.key] = ("name", c.composite, c, edgar_only)

        # A renamed ticker's eras (no pick, their old CUSIP unknown to OpenFIGI on
        # any US venue) join the line of their issuer's new CUSIP, when that line is
        # confirmed by a pin or a CUSIP (`_handoff_joins`). The join is weak for
        # guard (c) below, like an EDGAR-names-only pick.
        unpicked = [e.key for e in eras if e.key not in out and e.key not in picks and e.key in issuers]
        by_key = {e.key: e for e in eras}
        for key, (composite, anchor, h) in _handoff_joins(eras, issuers, handoffs, unpicked, confirmed).items():
            if _contradicted(by_key[key], composite, eras, issuers, confirmed):
                continue
            cand = picks[anchor][2] if anchor in picks else None
            picks[key] = ("handoff", composite, cand, True)
            self.log(f"FIGI handoff: {key} joins {composite}, the line {anchor} is confirmed on ({_link_text(h)})")

        def group(era: TickerEra) -> tuple[int | None, str]:
            return cik_of(issuers, era.key), share_class_from_name(era.name)

        # A backfilled ticker (an unconfirmed era: APTV listed in 2012-13, when
        # Delphi traded as DLPH) is the line its issuer and class traded on then.
        for era in eras:
            if era.key not in unconfirmed or era.key in out or era.key in picks or era.key not in issuers:
                continue
            lines = {confirmed[o.key] for o in eras if o.key in confirmed and o.key != era.key
                     and group(o) == group(era) and o.first <= era.last and era.first <= o.last}
            if len(lines) == 1:
                composite = next(iter(lines))
                anchor = next(o.key for o in eras if confirmed.get(o.key) == composite)
                picks[era.key] = ("backfill", composite, picks[anchor][2] if anchor in picks else None, False)
                self.log(f"FIGI backfill: {era.key} joins {composite}, the line its issuer and class traded on "
                         f"over its dates (no fails row under {era.ticker} then)")

        # An issuer's placeholder holds its eras of one class that no FIGI confirms.
        # An era that only the EDGAR names or a CUSIP handoff take off it would leave
        # a sibling there: one stock on two sec_ids, and the placeholder ending in a
        # rename (ACE LTD, backfilled under CB in 2012-14, while its own ACE era finds
        # no FIGI). Such a sibling instead follows the group onto its composite (a
        # "handoff" pick) when the two guards above do not contradict it there
        # (`_contradicted`); if they do, or if the group's picks disagree on the
        # composite (two chains reaching two composites), the whole group is
        # withdrawn to the placeholder instead, all its picks together, never split.
        # Repeated until no group changes.
        while True:
            held: dict[tuple[int | None, str], list[str]] = defaultdict(list)
            for e in eras:
                if e.key not in out and e.key not in picks and e.key in issuers:
                    held[group(e)].append(e.key)
            if not held:
                break
            changed = False
            for grp, siblings in held.items():
                weak_keys = [e.key for e in eras if e.key in picks and picks[e.key][3] and group(e) == grp]
                if not weak_keys:
                    continue
                changed = True
                composites = {picks[k][1] for k in weak_keys}
                if len(composites) > 1:
                    for k in weak_keys:
                        self.log(f"FIGI {picks[k][0]} pick withdrawn: {k} stays on its issuer's placeholder; "
                                 f"its issuer and class reach more than one composite (guard c)")
                        del picks[k]
                    continue
                composite = next(iter(composites))
                blocked_by = next((s for s in siblings
                                   if _contradicted(by_key[s], composite, eras, issuers, confirmed)), None)
                if blocked_by is not None:
                    for k in weak_keys:
                        self.log(f"FIGI {picks[k][0]} pick withdrawn: {k} stays on its issuer's placeholder with "
                                 f"{blocked_by} (guard c)")
                        del picks[k]
                    continue
                for s in siblings:
                    picks[s] = ("handoff", composite, picks[weak_keys[0]][2], True)
                    self.log(f"FIGI handoff: {s} joins {composite} with its issuer and class, "
                            f"held with no pick of its own (guard c)")
            if not changed:
                break

        for era in eras:
            if era.key in out:
                continue
            tried = plan[era.key][0]
            found, by_cusip = found_of[era.key], by_cusip_of[era.key]
            if era.key in picks:
                source, composite, cand, _ = picks[era.key]

                def own(c: str, got: FigiCandidate | None, cands: list[FigiCandidate]) -> bool:
                    if got is not None and got.composite == composite:
                        return True
                    # Resolved by ticker, name or handoff: the era's own FTD CUSIP stays
                    # unless OpenFIGI maps it to another composite (it often has no
                    # record of an old CUSIP at all).
                    return source != "cusip" and c in era.ftd_cusips and not cands
                out[era.key] = EraResolution(era.key, composite, source, cand, (),
                                             tuple(c for c, got, f in zip(tried, by_cusip, found) if own(c, got, f)))
                continue
            cik = cik_of(issuers, era.key)
            if cik is not None:
                out[era.key] = EraResolution(era.key, placeholder_id(cik, share_class_from_name(era.name)),
                                             "placeholder", None, ("no_figi",), tuple(tried[:1]))
            else:
                out[era.key] = EraResolution(era.key, None, "unresolved", None, ("observation_unresolved",))
        return out


# How strongly an era's resolution confirms its FIGI, strongest first: the
# caller's pin, a CUSIP, the ticker, a name search, a CUSIP handoff to another
# era's line, a backfilled ticker placed on its issuer's line then, the
# issuer's placeholder.
SOURCE_STRENGTH = ("pin", "cusip", "ticker", "name", "handoff", "backfill", "placeholder")
CONFIRMED_SOURCES = ("pin", "cusip")          # an era whose own evidence names its line
WEAK_SOURCES = ("ticker", "name")             # an era the ticker or a name answered for, with today's holder


def crossing_weak_eras(resolutions: Mapping[str, EraResolution],
                       eras: Mapping[str, TickerEra]) -> dict[str, tuple[str, str]]:
    """The weak eras (`WEAK_SOURCES`) whose merge into their security would carry
    its range for their ticker across another security's confirmed era of that
    ticker (`CONFIRMED_SOURCES`): era key -> (its sec_id, the crossed sec_id).

    ITT@2008-01-16 reached today's ITT line only by ticker; merged into it, that
    line's ITT range would run 2008..today, across the 2011 line's CUSIP-confirmed
    2012-2015 era. A weak era crosses when another security's confirmed span of
    the ticker lies wholly between it and another era of its own security under
    that ticker. A weak era that merely shares dates with another security's era (a
    backfilled name, `observation_conflict_review`) crosses nothing: the
    confirmed span is the other security's, over all its confirmed eras of the
    ticker (a refined era can be a single observation)."""
    by_ticker: dict[str, list[tuple[TickerEra, EraResolution]]] = defaultdict(list)
    for key, res in resolutions.items():
        if res.sec_id is not None:
            by_ticker[eras[key].ticker].append((eras[key], res))
    out: dict[str, tuple[str, str]] = {}
    for items in by_ticker.values():
        spans: dict[str, tuple[str, str]] = {}           # sec_id -> its confirmed eras' span under the ticker
        for e, r in items:
            if r.source in CONFIRMED_SOURCES:
                lo, hi = spans.get(r.sec_id, (e.first, e.last))
                spans[r.sec_id] = (min(lo, e.first), max(hi, e.last))
        for era, res in items:
            if res.source not in WEAK_SOURCES:
                continue
            own = [e for e, r in items if r.sec_id == res.sec_id and e.key != era.key]
            for other, (first, last) in sorted(spans.items()):
                if other != res.sec_id and any((era.last < first and last < e.first)
                                               or (e.last < first and last < era.first) for e in own):
                    out[era.key] = (res.sec_id, other)
                    break
    return out


def resolve_with_identity_guard(resolver: "FigiResolver", eras: Sequence[TickerEra], *,
                                issuers: Mapping[str, Issuer], cusips: Mapping[str, list[str]],
                                handoffs: Sequence[Handoff] = (), unconfirmed: Collection[str] = ()
                                ) -> tuple[dict[str, EraResolution], dict[str, tuple[str, str]]]:
    """`resolver.resolve_many`, then each weak era whose merge would cross another
    security's confirmed range (`crossing_weak_eras`) taken back out and resolved
    again without its ticker or name pick, until none crosses. Returns the
    resolutions and the detached eras (era key -> (the sec_id its weak pick gave,
    the sec_id it crossed)), for the review."""
    by_key = eras_by_key(eras)
    detached: dict[str, tuple[str, str]] = {}
    while True:
        res = resolver.resolve_many(eras, issuers=issuers, cusips=cusips, handoffs=handoffs,
                                    unconfirmed=unconfirmed, barred=set(detached))
        new = {k: v for k, v in crossing_weak_eras(res, by_key).items() if k not in detached}
        if not new:
            return res, detached
        for k, (sid, crossed) in new.items():
            resolver.log(f"FIGI {res[k].source} pick withdrawn: {k} would carry {sid}'s {by_key[k].ticker} range "
                         f"across {crossed}'s confirmed one")
        detached.update(new)


def detached_review(detached: Mapping[str, tuple[str, str]], eras: Mapping[str, TickerEra],
                    resolutions: Mapping[str, EraResolution], issuers: Mapping[str, Issuer]) -> list[ReviewItem]:
    """One `identity_detached` review row per era `resolve_with_identity_guard`
    took off the security its weak pick gave it."""
    out: list[ReviewItem] = []
    for key, (sid, crossed) in sorted(detached.items()):
        e = eras[key]
        now = resolutions[key].sec_id or "unresolved"
        out.append(ReviewItem(resolutions[key].sec_id or "", e.ticker, cik_of(issuers, key), "identity_detached",
                              f"{key} {e.name or ''}: its ticker or name pick {sid} would carry that security's {e.ticker} range across {crossed}'s "
                              f"confirmed one; resolved again as {now}", last_seen=e.last))
    return out


def superseded_placeholders(securities: Mapping[str, Security]) -> set[str]:
    """The placeholder securities that are not the line listed today under their
    ticker: a FIGI security of the same issuer and class, sharing one of their
    tickers, begins after their last observation. EDGAR's ticker list names
    the issuer's current line (J for CIK 52988 is the 2022 holding company's),
    which would otherwise keep an old placeholder open over every later line."""
    out: set[str] = set()
    for p in securities.values():
        if not is_placeholder(p.sec_id) or p.issuer_cik is None or not p.eras:
            continue
        tickers, last = {e.ticker for e in p.eras}, max(e.last for e in p.eras)
        for s in securities.values():
            if (not is_placeholder(s.sec_id) and s.eras and s.issuer_cik == p.issuer_cik
                    and s.share_class == p.share_class and tickers & {e.ticker for e in s.eras}
                    and min(e.first for e in s.eras) > last):
                out.add(p.sec_id)
                break
    return out


def _share_class(res: EraResolution, era: TickerEra) -> str:
    """The class the OpenFIGI candidate's name gives, else the era's observed name's."""
    cand_class = share_class_from_name(res.candidate.name) if res.candidate else "COMMON"
    return cand_class if cand_class != "COMMON" else share_class_from_name(era.name)


def build_securities(resolutions: Mapping[str, EraResolution], eras: Mapping[str, TickerEra],
                     issuers: Mapping[str, Issuer]) -> dict[str, Security]:
    """The securities the eras resolve to, each with its eras earliest first.
    `figi_source` is the strongest source among its eras (`SOURCE_STRENGTH`; a
    tie keeps the earliest era), and `share_class` comes from that same era; when
    that era names no class, from the earliest other era that does (a name cut
    off before its class letter: SBA's "...REIT CORP CLASS"). The security type
    and kind come from its earliest era's candidate, the name from its latest
    named era, the issuer CIK from its latest era whose issuer is known
    (`issuers`, by era key)."""
    out: dict[str, Security] = {}
    classes: dict[str, list[str]] = defaultdict(list)      # sec_id -> each era's class, earliest first
    for key in sorted(resolutions, key=lambda k: (eras[k].first, k)):
        res = resolutions[key]
        if res.sec_id is None:
            continue
        era, cand = eras[key], res.candidate
        sec = out.get(res.sec_id)
        if sec is None:
            name = era.name or (cand.name if cand else "")
            stype = cand.security_type if cand else ""
            sec = Security(res.sec_id, cik_of(issuers, key), _share_class(res, era), name, stype, True,
                           res.source, security_kind(stype, name))
            out[res.sec_id] = sec
        elif SOURCE_STRENGTH.index(res.source) < SOURCE_STRENGTH.index(sec.figi_source):
            sec.figi_source, sec.share_class = res.source, _share_class(res, era)
        classes[res.sec_id].append(_share_class(res, era))
        sec.eras.append(era)
        if key in issuers:
            sec.issuer_cik = issuers[key].cik
        if era.name:
            sec.name = era.name
    for sec in out.values():
        if sec.share_class == "COMMON":
            sec.share_class = next((c for c in classes[sec.sec_id] if c != "COMMON"), "COMMON")
    return out


TICKER_CONFIRM_DAYS = 30        # an era's ticker counts as confirmed by an FTD row this close to its span


def _confirm_window(e: TickerEra) -> tuple[str, str]:
    lo = max(FTD_START, date.fromisoformat(e.first) - timedelta(days=TICKER_CONFIRM_DAYS)).isoformat()
    return lo, (date.fromisoformat(e.last) + timedelta(days=TICKER_CONFIRM_DAYS)).isoformat()


def unconfirmed_eras(eras: Sequence[TickerEra], ftd: FtdIndex) -> set[str]:
    """The keys of the eras from 2004 on (the start of SEC fails-to-deliver data)
    with no FTD row under their ticker within `TICKER_CONFIRM_DAYS` of their
    first and last observation: the SEC data never shows that ticker then, as
    when a snapshot carries a ticker adopted later (APTV in 2012-2013, when
    Delphi traded as DLPH)."""
    return {e.key for e in eras if date.fromisoformat(e.last) >= FTD_START and not ftd.by_symbol(e.ticker,
                                                                                               *_confirm_window(e))}


def guarded_eras(eras: Sequence[TickerEra], ftd: FtdIndex) -> set[str]:
    """The `unconfirmed_eras` whose window the loaded fails data covers (some row
    of another symbol falls in it): the data shows the ticker was not failing
    then, rather than having nothing to say. Their ticker and name tiers are
    not asked (`FigiResolver.resolve_many`'s `unconfirmed`)."""
    return {k for k in unconfirmed_eras(eras, ftd) if ftd.has_rows(*_confirm_window(eras_by_key(eras)[k]))}


def ticker_unconfirmed_review(eras: list[TickerEra], ftd: FtdIndex, resolutions: dict,
                        issuers: dict[str, Issuer]) -> list[ReviewItem]:
    """A `ticker_unconfirmed` review row for each era of `unconfirmed_eras`."""
    out: list[ReviewItem] = []
    unconfirmed = unconfirmed_eras(eras, ftd)
    for e in eras:
        if e.key not in unconfirmed:
            continue
        lo, hi = _confirm_window(e)
        out.append(ReviewItem(resolutions[e.key].sec_id or "", e.ticker, cik_of(issuers, e.key), "ticker_unconfirmed",
                              f"{e.key} {e.name or ''}: no fails-to-deliver row under {e.ticker} "
                              f"from {lo} to {hi}", last_seen=e.last))
    return out


def observation_conflict_review(eras: list[TickerEra], resolutions: dict) -> list[ReviewItem]:
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

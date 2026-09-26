"""The security master: observation eras resolved to US composite FIGIs and
merged into securities (their dated ticker and CUSIP ranges are `history.py`'s).

A security is one share class traded in the US (CONTEXT.md). Eras of different
tickers that resolve to the same FIGI (FB, later META) are one security, and so
are two eras of one ticker that `refine_eras` split apart but that resolve to
the same FIGI (a reverse split's new CUSIP, a gap no FTD row bridged).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from .figi_resolution import (
    FigiCandidate, accept, bloomberg_ticker, filter_query, placeholder_id, security_kind,
    share_class_from_name, us_candidates,
)
from .ftd import FTD_START, FtdIndex, FtdRow
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


def era_last_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400) -> str:
    """The era's last sighting: its last observation, or a later FTD row under
    its ticker within `horizon_days` — of the era's own FTD CUSIPs when it has
    them (a name check is too weak: "FOX CORP" agrees with "TWENTY FIRST
    CENTURY FOX"), else with a description that agrees with an era name."""
    lo = (date.fromisoformat(era.last) + timedelta(days=1)).isoformat()
    hi = (date.fromisoformat(era.last) + timedelta(days=horizon_days)).isoformat()
    best = era.last
    for r in ftd.by_symbol(era.ticker, lo, hi):
        if era.ftd_cusips:
            if r.cusip not in era.ftd_cusips:
                continue
        elif era.names and not any(names_agree(r.description, n) for n in era.names):
            continue
        best = max(best, r.date)
    return best


def _contradicted(era: TickerEra, composite: str, eras: Sequence[TickerEra], issuers: Mapping[str, Issuer],
                  confirmed: Mapping[str, str]) -> bool:
    """Whether another era's pin or CUSIP (`confirmed`: era key -> composite)
    rules out `composite` for `era`, a candidate that only the issuer's EDGAR
    names accept. An issuer's names can outlive its stock and match a later
    line: the bankrupt General Growth Properties (CIK 895648) is now "GGP, Inc.",
    the name of the new issuer's GGP line; Jacobs Engineering's names match
    today's JACOBS SOLUTIONS line, a new composite since the 2022 reorganization.
    So the candidate is ruled out when an era of another known issuer is
    confirmed on it, or when an era of the same issuer and share class is
    confirmed on another composite over overlapping dates."""
    cik, cls = cik_of(issuers, era.key), share_class_from_name(era.name)
    for other in eras:
        comp = confirmed.get(other.key)
        if comp is None or other.key == era.key:
            continue
        other_cik = cik_of(issuers, other.key)
        if comp == composite:
            if other_cik is not None and other_cik != cik:
                return True
        elif (other_cik == cik and share_class_from_name(other.name) == cls
              and other.first <= era.last and era.first <= other.last):
            return True
    return False


def _cusip_job(c: str) -> dict:
    return {"idType": "ID_CINS" if c[:1].isalpha() else "ID_CUSIP", "idValue": c, "includeUnlistedEquities": True}


class FigiResolver:
    MAX_CUSIPS = 3

    def __init__(self, figi) -> None:
        self.figi = figi

    def resolve_many(self, eras: Sequence[TickerEra], *, issuers: Mapping[str, Issuer],
                     cusips: Mapping[str, list[str]]) -> dict[str, EraResolution]:
        """Each era's FIGI (spec §8.3): a `sec_id` pin; else the first of its
        CUSIPs (`cusips`, at most `MAX_CUSIPS`) that OpenFIGI maps to one US
        composite; else its ticker, then a name search, where a candidate is
        accepted only when its name agrees with the era's observed names or,
        failing that, its issuer's EDGAR names, current and former
        (`issuers`, by era key: Northeast Utilities, seen under ES before its
        rename, is accepted onto Bloomberg's EVERSOURCE ENERGY line because
        EDGAR lists both names for CIK 72741). A dead line Bloomberg renamed to
        its acquirer is still rejected: the acquirer's name is not one of the
        target issuer's names. A candidate taken only through the EDGAR names
        must also not contradict another era's pin or CUSIP (`_contradicted`),
        nor leave a sibling era of the same issuer and class alone on the
        issuer's placeholder. Else the issuer's placeholder, or unresolved with
        no issuer."""
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
            if c is not None or not edgar:
                return c, False
            c = accept(cands, ticker=era.ticker, names=[*era.names, *edgar], via_cusip=False)
            if c is None or _contradicted(era, c.composite, eras, issuers, confirmed):
                return None, False
            return c, True

        picks: dict[str, tuple[str, FigiCandidate, bool]] = {}     # era -> (source, candidate, EDGAR names only)
        for era in eras:
            if era.key in out:
                continue
            c = next((got for got in by_cusip_of[era.key] if got), None)
            if c:
                picks[era.key] = ("cusip", c, False)
                continue
            c, edgar_only = named(era, us_candidates(answers[plan[era.key][2]].get("data") or []))
            if c:
                picks[era.key] = ("ticker", c, edgar_only)
                continue
            q = filter_query(era.name or "")
            if q:
                rows = self.figi.filter(q, exchCode="US", includeUnlistedEquities=True)
                c, edgar_only = named(era, us_candidates(rows))
                if c:
                    picks[era.key] = ("name", c, edgar_only)

        def group(era: TickerEra) -> tuple[int | None, str]:
            return cik_of(issuers, era.key), share_class_from_name(era.name)

        # An issuer's placeholder holds its eras of one class that no FIGI confirms.
        # An era that only the EDGAR names take off it would leave a sibling there:
        # one stock on two sec_ids, and the placeholder ending in a rename (ACE LTD,
        # backfilled under CB in 2012-14, while its own ACE era finds no FIGI). Such
        # an era stays with the group; repeated until no group is split.
        while True:
            held = {group(e) for e in eras
                    if e.key not in out and e.key not in picks and e.key in issuers}
            split = [e.key for e in eras if e.key in picks and picks[e.key][2] and group(e) in held]
            if not split:
                break
            for k in split:
                del picks[k]

        for era in eras:
            if era.key in out:
                continue
            tried = plan[era.key][0]
            found, by_cusip = found_of[era.key], by_cusip_of[era.key]
            if era.key in picks:
                source, cand, _ = picks[era.key]

                def own(c: str, got: FigiCandidate | None, cands: list[FigiCandidate]) -> bool:
                    if got is not None and got.composite == cand.composite:
                        return True
                    # Resolved by ticker or name: the era's own FTD CUSIP stays unless
                    # OpenFIGI maps it to another composite (it often has no record of
                    # an old CUSIP at all).
                    return source != "cusip" and c in era.ftd_cusips and not cands
                out[era.key] = EraResolution(era.key, cand.composite, source, cand, (),
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
# caller's pin, a CUSIP, the ticker, a name search, the issuer's placeholder.
SOURCE_STRENGTH = ("pin", "cusip", "ticker", "name", "placeholder")


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


def ticker_unconfirmed_review(eras: list[TickerEra], ftd: FtdIndex, resolutions: dict,
                        issuers: dict[str, Issuer]) -> list[ReviewItem]:
    """A `ticker_unconfirmed` review row for each era from 2004 on (the start of
    SEC fails-to-deliver data) with no FTD row under its ticker within
    `TICKER_CONFIRM_DAYS` of its first and last observation: the SEC data never
    shows that ticker then, as when a snapshot carries a ticker adopted later
    (APTV in 2012-2013, when Delphi traded as DLPH)."""
    out: list[ReviewItem] = []
    for e in eras:
        if date.fromisoformat(e.last) < FTD_START:
            continue
        lo = max(FTD_START, date.fromisoformat(e.first) - timedelta(days=TICKER_CONFIRM_DAYS)).isoformat()
        hi = (date.fromisoformat(e.last) + timedelta(days=TICKER_CONFIRM_DAYS)).isoformat()
        if ftd.by_symbol(e.ticker, lo, hi):
            continue
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

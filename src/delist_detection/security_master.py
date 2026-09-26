"""The security master: observation eras resolved to US composite FIGIs, merged
into securities, with dated ticker and CUSIP ranges.

A security is one share class traded in the US (CONTEXT.md). Eras of different
tickers that resolve to the same FIGI (FB, later META) are one security, and so
are two eras of one ticker that `refine_eras` split apart but that resolve to
the same FIGI (a reverse split's new CUSIP, a gap no FTD row bridged).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from .figi_resolution import (
    FigiCandidate, accept, bloomberg_ticker, filter_query, placeholder_id, security_kind,
    share_class_from_name, us_candidates,
)
from .ftd import FtdIndex, FtdRow
from .names import description_matches, names_agree
from .observations import ERA_GAP_DAYS, Observation, TickerEra, eras_by_key, number_eras

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
    all name another company is not taken, however it came to be the era's: a
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


def candidate_cusips(eras: Sequence[TickerEra], ftd: FtdIndex, ciks: Mapping[str, int | None],
                     issuer_names: Mapping[int, Sequence[str]]) -> dict[str, list[str]]:
    """`era_cusips` for every era (by key), each checked against its issuer's
    EDGAR names (`issuer_names`, by CIK).

    An era whose issuer is unknown (no CIK) has only its observed names, which a
    stale snapshot can leave behind a rename (CME Group is still "CHICAGO
    MERCANTILE HLDGS" in the 2008 snapshots, and no CIK resolves for that name
    then). It also takes a CUSIP that an era with a known issuer took as that
    issuer's: the fails rows tie the CUSIP to that issuer, the ticker and the
    dates tie it to this era. An era with a known issuer is held to its own
    issuer's names, so a stale era (Triad Hospitals on TRI in 2008) never takes
    the CUSIP of the company that later holds its ticker (Thomson Reuters)."""
    out = {e.key: era_cusips(e, ftd, issuer_names.get(ciks[e.key], ()))
           for e in eras if ciks.get(e.key) is not None}
    taken_by_known_issuers = {c for taken in out.values() for c in taken}
    for e in eras:
        if ciks.get(e.key) is None:
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


def _contradicted(era: TickerEra, composite: str, eras: Sequence[TickerEra], ciks: Mapping[str, int | None],
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
    cik, cls = ciks.get(era.key), share_class_from_name(era.name)
    for other in eras:
        comp = confirmed.get(other.key)
        if comp is None or other.key == era.key:
            continue
        other_cik = ciks.get(other.key)
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

    def resolve_many(self, eras: Sequence[TickerEra], *, ciks: Mapping[str, int | None],
                     cusips: Mapping[str, list[str]],
                     issuer_names: Mapping[int, Sequence[str]] | None = None) -> dict[str, EraResolution]:
        """Each era's FIGI (spec §8.3): a `sec_id` pin; else the first of its
        CUSIPs (`cusips`, at most `MAX_CUSIPS`) that OpenFIGI maps to one US
        composite; else its ticker, then a name search, where a candidate is
        accepted only when its name agrees with the era's observed names or,
        failing that, its issuer's EDGAR names, current and former
        (`issuer_names`, by CIK: Northeast Utilities, seen under ES before its
        rename, is accepted onto Bloomberg's EVERSOURCE ENERGY line because
        EDGAR lists both names for CIK 72741). A dead line Bloomberg renamed to
        its acquirer is still rejected: the acquirer's name is not one of the
        target issuer's names. A candidate taken only through the EDGAR names
        must also not contradict another era's pin or CUSIP (`_contradicted`),
        nor leave a sibling era of the same issuer and class alone on the
        issuer's placeholder. Else the issuer's placeholder, or unresolved with
        no issuer."""
        eras_by_key(eras)                                # every era is keyed by era.key below: refuse duplicates
        issuer_names = issuer_names or {}
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
            edgar = issuer_names.get(ciks.get(era.key), ())
            if c is not None or not edgar:
                return c, False
            c = accept(cands, ticker=era.ticker, names=[*era.names, *edgar], via_cusip=False)
            if c is None or _contradicted(era, c.composite, eras, ciks, confirmed):
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
            return ciks.get(era.key), share_class_from_name(era.name)

        # An issuer's placeholder holds its eras of one class that no FIGI confirms.
        # An era that only the EDGAR names take off it would leave a sibling there:
        # one stock on two sec_ids, and the placeholder ending in a rename (ACE LTD,
        # backfilled under CB in 2012-14, while its own ACE era finds no FIGI). Such
        # an era stays with the group; repeated until no group is split.
        while True:
            held = {group(e) for e in eras
                    if e.key not in out and e.key not in picks and ciks.get(e.key) is not None}
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
            cik = ciks.get(era.key)
            if cik is not None:
                out[era.key] = EraResolution(era.key, placeholder_id(cik, share_class_from_name(era.name)),
                                             "placeholder", None, ("no_figi",), tuple(tried[:1]))
            else:
                out[era.key] = EraResolution(era.key, None, "unresolved", None, ("observation_unresolved",))
        return out


def build_securities(resolutions: Mapping[str, EraResolution], eras: Mapping[str, TickerEra],
                     ciks: Mapping[str, int | None]) -> dict[str, Security]:
    out: dict[str, Security] = {}
    for key in sorted(resolutions, key=lambda k: (eras[k].first, k)):
        res = resolutions[key]
        if res.sec_id is None:
            continue
        era, cand = eras[key], res.candidate
        sec = out.get(res.sec_id)
        if sec is None:
            name = era.name or (cand.name if cand else "")
            cand_class = share_class_from_name(cand.name) if cand else "COMMON"
            share = cand_class if cand_class != "COMMON" else share_class_from_name(era.name)
            stype = cand.security_type if cand else ""
            sec = Security(res.sec_id, ciks.get(key), share, name, stype, True, res.source,
                           security_kind(stype, name))
            out[res.sec_id] = sec
        sec.eras.append(era)
        if ciks.get(key) is not None:
            sec.issuer_cik = ciks[key]
        if era.name:
            sec.name = era.name
    return out


@dataclass(frozen=True)
class Range:
    value: str
    valid_from: str
    valid_to: str | None
    source: str


def value_on(ranges: Iterable[Range], day: date) -> str | None:
    """The value of the range that holds `day`, if any."""
    d = day.isoformat()
    return next((r.value for r in ranges if r.valid_from <= d and (r.valid_to is None or d <= r.valid_to)), None)


def ranges_from_sightings(sightings: Iterable[tuple[str, str, str]], *, end: str | None,
                          open_ended: bool) -> list[Range]:
    """Dated `(day, value, source)` sightings -> consecutive ranges of one value.

    Each range runs from its first sighting to the day before the next range's
    first sighting; the last one ends at `end`, or stays open (`open_ended`),
    or ends at its last sighting. A value seen only once, and only in FTD
    rows, is noise and dropped. Sightings after `end` are ignored.

    One day keeps one value: an observation beats an FTD row; then a value the
    caller observed; then the value of the range already running (so a day
    that sighted two tickers doesn't cut the running range); then the spelling
    with a separator ("BF-B" over "BFB"); then the alphabetically first. So
    every range has `valid_to >= valid_from`.
    """
    items = sorted({x for x in sightings if end is None or x[0] <= end})
    ftd_counts = Counter(v for _, v, s in items if s == "ftd")
    obs_values = {v for _, v, s in items if s == "observation"}
    items = [(d, v, s) for d, v, s in items if s == "observation" or ftd_counts[v] > 1 or v in obs_values]
    by_day: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for d, v, s in items:
        by_day[d].append((v, s))
    runs: list[list] = []                        # [value, first, last, sources]
    for d in sorted(by_day):
        running = runs[-1][0] if runs else None
        v, _ = min(by_day[d], key=lambda vs: (vs[1] != "observation", vs[0] not in obs_values, vs[0] != running,
                                              "-" not in vs[0], vs[0]))
        sources = {s for x, s in by_day[d] if x == v}
        if runs and runs[-1][0] == v:
            runs[-1][2] = d
            runs[-1][3] |= sources
        else:
            runs.append([v, d, d, sources])
    out: list[Range] = []
    for i, (v, first, last, sources) in enumerate(runs):
        if i + 1 < len(runs):
            to: str | None = (date.fromisoformat(runs[i + 1][1]) - timedelta(days=1)).isoformat()
        elif end is not None:
            to = end
        elif open_ended:
            to = None
        else:
            to = last
        if to is not None and to < first:
            continue                              # never an inverted range
        out.append(Range(v, first, to, "observation" if "observation" in sources else "ftd"))
    return out

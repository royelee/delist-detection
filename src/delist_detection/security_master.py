"""The security master: observation eras resolved to US composite FIGIs, merged
into securities, with dated ticker and CUSIP ranges.

A security is one share class traded in the US (CONTEXT.md). Eras of different
tickers that resolve to the same FIGI (FB, later META) are one security.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from .figi_resolution import (
    FigiCandidate, accept, bloomberg_ticker, filter_query, placeholder_id, security_kind,
    share_class_from_name, us_candidates,
)
from .ftd import FtdIndex
from .names import names_agree
from .observations import TickerEra


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


def era_cusips(era: TickerEra, ftd: FtdIndex) -> list[str]:
    lo = (date.fromisoformat(era.first) - timedelta(days=10)).isoformat()
    hi = (date.fromisoformat(era.last) + timedelta(days=10)).isoformat()
    counts: Counter[str] = Counter()
    for r in ftd.by_symbol(era.ticker, lo, hi):
        if era.names and not any(names_agree(r.description, n) for n in era.names):
            continue
        counts[r.cusip] += 1
    return list(era.cusips) + [c for c, _ in counts.most_common() if c not in era.cusips]


def era_last_seen(era: TickerEra, ftd: FtdIndex, horizon_days: int = 400) -> str:
    lo = (date.fromisoformat(era.last) + timedelta(days=1)).isoformat()
    hi = (date.fromisoformat(era.last) + timedelta(days=horizon_days)).isoformat()
    best = era.last
    for r in ftd.by_symbol(era.ticker, lo, hi):
        if era.names and not any(names_agree(r.description, n) for n in era.names):
            continue
        best = max(best, r.date)
    return best


def _cusip_job(c: str) -> dict:
    return {"idType": "ID_CINS" if c[:1].isalpha() else "ID_CUSIP", "idValue": c, "includeUnlistedEquities": True}


class FigiResolver:
    MAX_CUSIPS = 3

    def __init__(self, figi) -> None:
        self.figi = figi

    def resolve_many(self, eras: Sequence[TickerEra], *, ciks: Mapping[str, int | None],
                     cusips: Mapping[str, list[str]]) -> dict[str, EraResolution]:
        out: dict[str, EraResolution] = {}
        jobs: list[dict] = []
        plan: dict[str, tuple[list[int], int]] = {}
        for era in eras:
            if era.sec_id_pin:
                out[era.key] = EraResolution(era.key, era.sec_id_pin, "pin", None, ())
                continue
            idx = []
            for c in cusips.get(era.key, [])[: self.MAX_CUSIPS]:
                idx.append(len(jobs))
                jobs.append(_cusip_job(c))
            t_idx = len(jobs)
            jobs.append({"idType": "TICKER", "idValue": bloomberg_ticker(era.ticker), "includeUnlistedEquities": True})
            plan[era.key] = (idx, t_idx)
        answers = self.figi.map(jobs) if jobs else []
        for era in eras:
            if era.key in out:
                continue
            idx, t_idx = plan[era.key]
            names = era.names
            for i in idx:
                c = accept(us_candidates(answers[i].get("data") or []), ticker=era.ticker, names=names,
                           via_cusip=True)
                if c:
                    out[era.key] = EraResolution(era.key, c.composite, "cusip", c, ())
                    break
            if era.key in out:
                continue
            c = accept(us_candidates(answers[t_idx].get("data") or []), ticker=era.ticker, names=names,
                       via_cusip=False)
            if c:
                out[era.key] = EraResolution(era.key, c.composite, "ticker", c, ())
                continue
            q = filter_query(era.name or "")
            if q:
                rows = self.figi.filter(q, exchCode="US", includeUnlistedEquities=True)
                c = accept(us_candidates(rows), ticker=era.ticker, names=names, via_cusip=False)
                if c:
                    out[era.key] = EraResolution(era.key, c.composite, "name", c, ())
                    continue
            cik = ciks.get(era.key)
            if cik is not None:
                out[era.key] = EraResolution(era.key, placeholder_id(cik, share_class_from_name(era.name)),
                                             "placeholder", None, ("no_figi",))
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


def ranges_from_sightings(sightings: Iterable[tuple[str, str, str]], *, end: str | None,
                          open_ended: bool) -> list[Range]:
    items = sorted(set(sightings))
    ftd_counts = Counter(v for _, v, s in items if s == "ftd")
    obs_values = {v for _, v, s in items if s == "observation"}
    items = [(d, v, s) for d, v, s in items if s == "observation" or ftd_counts[v] > 1 or v in obs_values]
    runs: list[list] = []                        # [value, first, last, sources]
    for d, v, s in items:
        if runs and runs[-1][0] == v:
            runs[-1][2] = d
            runs[-1][3].add(s)
        else:
            runs.append([v, d, d, {s}])
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
        out.append(Range(v, first, to, "observation" if "observation" in sources else "ftd"))
    return out

"""Sub-plan 5h's real cases, replayed offline: tests/fixtures/identity/ (built once from the local caches by
scripts/build_identity_fixtures.py) holds the observations of each case's tickers (and of their issuers' other
tickers), their fails rows, the EDGAR answers (names, former names, filings) and OpenFIGI answers the run's own code
asks for, and SEC's name-index entries of the observed names.

`Cases(backend)` runs the run's code over them: stage 1 (`pipeline._refine`, the eras refined on their fails rows),
stage 2b (`TickerResolver.name_period_checks` over the committed run's first-pass answers) and stage 3
(`pipeline._resolve_securities`, each era's FIGI, with the committed run's issuer of each era). The builder runs the
same code over the local caches with recording doubles, so a fixture holds what the code reads."""
from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from delist_detection import pipeline
from delist_detection.cik_lookup import CikNameIndex, normalize_name
from delist_detection.edgar import EdgarSubmission
from delist_detection.evidence import edgar_names
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.manifest import StageMeter
from delist_detection.observations import Observation, ObservationIndex, TickerEra
from delist_detection.security_master import Issuer, era_last_seen, issuers_by_era
from delist_detection.ticker_resolver import TickerResolution, TickerResolver

FIX = Path(__file__).parent / "fixtures" / "identity"
AS_OF = date(2026, 9, 25)                    # the committed run's date

# Stage 3: one resolve over the eras of these issuers (each case's and its issuer's other eras), as the run
# resolves them all at once: UAC-C (Under Armour), MSG and its new MSG, LMCA and its new Liberty Media, UAG (Penske),
# IAC and its new IAC; the guards' issuers: Google and Alphabet (two class letters), HEICO, Lennar and Viacom (a
# class ticker beside its base symbol), Liberty Interactive (series A tracking stocks sharing a CUSIP), Hubbell
# (HUB-B beside FTD's bare HUBB); and the other renames a CUSIP switch joins across a class label (CB Richard
# Ellis, Washington Post, Warner Chilcott).
STAGE3_CIKS = (1336917, 1469372, 1636519, 1507934, 1560385, 1019849, 891103, 1800227,
               1288776, 1652044, 46619, 920760, 1339947, 1355096, 48898, 1138118, 104889, 1323854)
# Stage 2b: era key -> (its observed name, the committed run's first-pass answer, a name search)
NAME_CASES = {
    "ABBI@2008-01-16": ("ABRAXIS BIOSCIENCE INC", 1141399),   # now 1409012: the new Abraxis carried the name then
    "ERA@2013-06-28": ("BRISTOW GROUP INC", 73887),           # now 1525221: the rows under ERA say ERA GROUP INC
    "TCF@2012-06-29": ("TCF FINANCIAL CORP", 814184),         # guard: Chemical Financial took the name in 2019
    "TGNA@2012-06-29": ("GANNETT CO INC", 39899),             # guard: the spin-offs took the name in 2015
    "NWS-A@2008-01-16": ("NEWS CORP", 1308161),               # guard: the new News Corp took the name in 2013
}


# History cases (the CUSIP ranges of a joined line): (cusip, window lo, window hi) whose fails rows the fixture holds
# whole: MSG's old class A (55826P100: MSGZZZZ rows settle after the switch) and MSG Networks' (553573106)
HISTORY_CUSIPS = (("55826P100", "2015-09-01", "2015-11-30"), ("553573106", "2015-09-01", "2015-11-30"))


def job_key(job: dict) -> str:
    return json.dumps(job, sort_keys=True)


@dataclass
class Backend:
    """What the cases read: observations, a fails client, EDGAR, OpenFIGI and the name index."""
    observations: list[Observation]
    eras_issuer: dict[str, int]          # era key -> the committed run's issuer CIK (stage 3's issuers)
    ftd_client: object
    edgar: object
    figi: object
    index: CikNameIndex


class FixtureFtd:
    """The recorded fails rows, served as `ftd.FtdClient` serves a file (one file: "fixture")."""

    def __init__(self, rows: list[FtdRow]) -> None:
        self._rows = rows

    def urls_for(self, lo, hi):
        return ["fixture"]

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self._rows:
            if (symbols is None and cusips is None) or (symbols and r.symbol in symbols) \
                    or (cusips and r.cusip in cusips):
                yield r


class FixtureEdgar:
    """The recorded EDGAR answers: a CIK's names, tickers and filings."""

    def __init__(self, issuers: dict) -> None:
        self._issuers = issuers

    def submissions(self, cik, fresh_after=None):
        d = self._issuers.get(str(int(cik)))
        if d is None:
            return {"__not_found__": True}
        return {k: d[k] for k in ("name", "formerNames", "tickers", "exchanges")}

    def recent_filings(self, cik):
        d = self._issuers.get(str(int(cik)))
        return [] if d is None else [EdgarSubmission(*f) for f in d["filings"]]

    def company_tickers(self):
        return {}


class FixtureFigi:
    """The recorded OpenFIGI answers; a job the fixture lacks is an error answer, a filter none."""

    def __init__(self, data: dict) -> None:
        self._map, self._filter = data["map"], data["filter"]

    def map(self, jobs):
        return [self._map.get(job_key(j), {"error": "not in the fixture"}) for j in jobs]

    def filter(self, query, **fields):
        return self._filter.get(job_key({"query": query, **fields}), [])


def load_backend() -> Backend:
    data = json.loads((FIX / "cases.json").read_text())
    with gzip.open(FIX / "ftd_rows.csv.gz", "rt", newline="") as fh:
        rows = [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"],
                       float(r["price"]) if r["price"] else None) for r in csv.DictReader(fh)]
    edgar = json.loads(gzip.decompress((FIX / "edgar.json.gz").read_bytes()))
    figi = json.loads((FIX / "figi.json").read_text())
    obs = [Observation(t, d, n or None, None, int(c) if c else None) for t, d, n, c in data["observations"]]
    index = CikNameIndex((normalize_name(n), int(c), n) for n, c in data["index"])
    return Backend(obs, {k: int(v) for k, v in data["eras_issuer"].items()}, FixtureFtd(rows),
                   FixtureEdgar(edgar), FixtureFigi(figi), index)


@dataclass
class Cases:
    backend: Backend
    log: list[str] = field(default_factory=list)

    def _ctx(self):
        clients = SimpleNamespace(ftd_client=self.backend.ftd_client, figi=self.backend.figi,
                                  resolver=SimpleNamespace(is_degraded=lambda *a, **k: False),
                                  edgar=self.backend.edgar)
        return SimpleNamespace(clients=clients, as_of=AS_OF, log=self.log.append, sec_workers=1,
                               meter=StageMeter(lambda *a: None))

    def refine(self, tickers) -> tuple[list[TickerEra], FtdIndex]:
        """Stage 1 over the observations of `tickers`."""
        want = set(tickers)
        index = ObservationIndex([o for o in self.backend.observations if o.ticker in want])
        eras, _, ftd, _ = pipeline._refine(self._ctx(), index, None)
        return eras, ftd

    def issuers(self, eras: list[TickerEra]) -> dict[str, Issuer]:
        ciks = {e.key: self.backend.eras_issuer.get(e.key) for e in eras}
        names = {c: edgar_names(self.backend.edgar.submissions(c)) for c in set(ciks.values()) if c}
        return issuers_by_era(ciks, names)

    def stage3(self, tickers=None):
        """Stage 3 over the eras of `tickers` (default: every stage-3 era): (era key -> its resolution, the eras,
        the fails index)."""
        eras, ftd = self.refine(tickers if tickers is not None else stage3_tickers(self.backend))
        era_by_key = {e.key: e for e in eras}
        answers = pipeline._IssuerAnswers({}, self.issuers(eras), {e.key: era_last_seen(e, ftd) for e in eras},
                                          set())
        resolutions, _, _ = pipeline._resolve_securities(self._ctx(), eras, era_by_key, ftd, answers)
        return resolutions, eras, ftd

    def resolver(self) -> TickerResolver:
        return TickerResolver(self.backend.edgar, today=AS_OF, name_index=self.backend.index)

    def name_checks(self, first_pass: dict[str, int] | None = None):
        """Stage 2b over the NAME_CASES eras, each with its committed first-pass answer (or `first_pass`'s, by era
        key): (era key -> the answer that replaced it, the eras)."""
        eras, ftd = self.refine({k.split("@")[0] for k in NAME_CASES})
        last_seen = {e.key: era_last_seen(e, ftd) for e in eras}
        answers = {k: TickerResolution(k.split("@")[0], (first_pass or {}).get(k, c), None, "name_search")
                   for k, (_, c) in NAME_CASES.items()}
        return self.resolver().name_period_checks(eras, ftd, last_seen, answers), eras


def stage3_tickers(backend: Backend) -> list[str]:
    """The tickers of the stage-3 eras (every era of STAGE3_CIKS in the committed run)."""
    return sorted({k.split("@")[0] for k, c in backend.eras_issuer.items() if c in STAGE3_CIKS})

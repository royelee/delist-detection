"""Sub-plan 5d's real cases, replayed offline: tests/fixtures/last_trade/ (built once from the local caches by
scripts/build_last_trade_fixtures.py, 5c's builder over 5d's cases) holds each case's security, the securities whose
CUSIPs bound its ticker, the other securities of their issuers, their fails rows, and the EDGAR, MIDAS and Nasdaq-halt
answers. `outcome(sec_id)` runs the run's own code over them: stage 5 (`pipeline._context_builder`,
`delistings.DelistingFinder`, which dates each delisting through the last trade module, `last_trade.Dating`, over
the fixture's MIDAS and halt adapters) and stage 7's fails close (`pipeline._last_trade_closes`). The doubles are
5c's (tests/issuer_role_cases.py), reading this fixture."""
from __future__ import annotations

import csv
import gzip
import io
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from delist_detection import pipeline
from delist_detection.classifier import DelistClassifier
from delist_detection.delistings import Delisting, DelistingFinder
from delist_detection.edgar import EdgarSubmission
from delist_detection.figi_resolution import security_kind
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.history import ticker_sightings
from delist_detection.last_trade import UNCONFIRMED
from delist_detection.manifest import StageMeter
from delist_detection.midas import MidasClient
from delist_detection.nasdaq_halts import Halt, NasdaqHaltClient
from delist_detection.observations import Observation, TickerEra
from delist_detection.review_triage import ReviewItem
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver
from tests import issuer_role_cases as ic

FIX = Path(__file__).parent / "fixtures" / "last_trade"
DATA = json.loads((FIX / "cases.json").read_text())
EDGAR = json.loads(gzip.decompress((FIX / "edgar.json.gz").read_bytes()))
MIDAS = json.loads((FIX / "midas.json").read_text())
HALTS = json.loads((FIX / "halts.json").read_text())
AS_OF = date.fromisoformat(DATA["as_of"])


class FixtureEdgar(ic.FixtureEdgar):
    """This fixture's EDGAR answers (5c's double)."""

    def submissions(self, cik, fresh_after=None):
        d = EDGAR["issuers"].get(str(int(cik)))
        return {} if d is None else {k: d[k] for k in ("name", "formerNames", "tickers", "exchanges", "sic")}

    def recent_filings(self, cik):
        return [EdgarSubmission(*f) for f in EDGAR["issuers"].get(str(int(cik)), {}).get("filings", [])]

    def fetch_filing_raw(self, cik, accession):
        return EDGAR["raws"].get(accession, "")

    def fetch_filing_text(self, cik, accession, primary_doc):
        self.texts_read.append(accession)
        return EDGAR["texts"].get(accession, "")


class FixtureMidas(MidasClient):
    def __init__(self) -> None:
        self._summaries = {}
        self._warned_misses = set()

    def links(self):
        return {(int(q[:4]), int(q[-1])): q for q in MIDAS["quarters"]}

    def _summary(self, yq):
        return MIDAS["days"].get(f"{yq[0]}_q{yq[1]}", {})


class FixtureHalts(NasdaqHaltClient):
    def __init__(self) -> None:
        self.today = AS_OF

    def failed_days(self):
        return ()

    def halts_on(self, day):
        return [Halt(s, n, m, r, date.fromisoformat(hd), ht, date.fromisoformat(rd) if rd else None)
                for s, n, m, r, hd, ht, rd in HALTS.get(f"{day:%Y%m%d}", [])]


def _security(sec_id: str) -> Security:
    d = DATA["securities"][sec_id]
    eras = []
    for key, obs in d["eras"].items():
        ticker, _, rest = key.partition("@")
        seq = int(rest.split("#")[1]) if "#" in rest else 0
        observations = [Observation(t, a, n or None, c or None, int(p) if p else None) for t, a, n, c, p in obs]
        eras.append(TickerEra(ticker, observations[0].as_of, observations[-1].as_of, observations, seq=seq))
    eras.sort(key=lambda e: (e.first, e.seq))
    return Security(sec_id, d["issuer_cik"], d["share_class"], d["name"], d["security_type"], d["observed"],
                    d["figi_source"], kind=security_kind(d["security_type"], d["name"]), eras=eras,
                    line_tickers=frozenset(d["line_tickers"]))


@lru_cache(maxsize=1)
def world() -> tuple[dict[str, Security], dict[str, list[str]], FtdIndex]:
    """The fixture's observed securities, every security's CUSIPs, and the fails rows as one index."""
    securities = {sid: _security(sid) for sid, d in DATA["securities"].items() if d["observed"]}
    cusips = {sid: list(d["cusips"]) for sid, d in DATA["securities"].items()}
    with io.TextIOWrapper(gzip.open(FIX / "ftd_rows.csv.gz"), encoding="utf-8", newline="") as fh:
        rows = [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"], float(r["price"]) if r["price"] else None)
                for r in csv.DictReader(fh)]
    return securities, cusips, FtdIndex(rows)


def clients() -> pipeline.Clients:
    edgar = FixtureEdgar()
    return pipeline.Clients(edgar=edgar, resolver=None, classifier=DelistClassifier(edgar, TickerResolver(edgar),
                                                                                      today=AS_OF),
                            figi=ic.FixtureFigi(), ftd_client=None, midas=FixtureMidas(), halts=FixtureHalts(),
                            as_of=AS_OF)


def find(sec_id: str, c: pipeline.Clients | None = None) -> tuple[list[Delisting], list[ReviewItem]]:
    """Stage 5: the finder's delistings and review items for the case."""
    c = c or clients()
    securities, cusips, ftd = world()
    sightings = {sid: ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    build = pipeline._context_builder(securities, sightings, ftd, cusips)
    finder = DelistingFinder(c.edgar, c.classifier, midas=c.midas, halts=c.halts)
    return finder.find(build(securities[sec_id], DATA["securities"][sec_id]["listed"]))


def outcome(sec_id: str) -> list[tuple]:
    """What the run gives the case: each delisting as (delist_date, bucket, last trade day, its source, whether it
    is unconfirmed, the fails close of that day), in order."""
    c = clients()
    found, _ = find(sec_id, c)
    securities, cusips, ftd = world()
    ctx = pipeline._RunContext(c, AS_OF, lambda *a: None, 1, StageMeter(lambda *a: None))
    closes = pipeline._last_trade_closes(ctx, found, securities, cusips, ftd, date(1990, 1, 1), pipeline.Overrides())
    return [(d.delist_date, d.record.bucket.value, d.last_trade.day.isoformat() if d.last_trade.day else "",
             d.last_trade.source, UNCONFIRMED in d.last_trade.flags, closes.get(d.key))
            for d in found]

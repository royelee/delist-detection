"""Sub-plan 5c's real cases, replayed offline: tests/fixtures/issuer_role/ (built once from the local caches by
scripts/build_issuer_role_fixtures.py) holds each case's security, the securities a successor link may name and the
other securities of their issuers, their fails rows, and the EDGAR, OpenFIGI, MIDAS and Nasdaq-halt answers.
`outcome(sec_id)` runs the run's own code over them: stage 5 (`delistings.SecurityContexts`,
`delistings.DelistingFinder`, which makes each ending's own-share reading and keeps the one its classifier read),
stage 8b (`pipeline._r1_continuations`, the terms the committed contract published standing in for the LLM's), and
stage 9 (`pipeline._find_successors`, which records its links as rewrites; no full-text search: the fixture has
none, and its EDGAR double states the capability absent); `later` runs 8b and 9 over delistings `find` gave. How each successor was found is the rewrite's typed provenance
(`rewrites.successor_by`)."""
from __future__ import annotations

import csv
import gzip
import io
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from delist_detection import pipeline
from delist_detection.added_securities import AddedAcquirer, AddedSecurity
from delist_detection.classifier import DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import Delisting, DelistingFinder, SecurityContexts
from delist_detection.edgar import EdgarSubmission
from delist_detection.figi_resolution import security_kind
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.history import ticker_sightings
from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.manifest import StageMeter
from delist_detection.merger_value import MergerValue, MergerValues
from delist_detection.midas import MidasClient
from delist_detection.nasdaq_halts import Halt, NasdaqHaltClient
from delist_detection.observations import Observation, TickerEra
from delist_detection.review_triage import ReviewItem
from delist_detection.rewrites import successor_by
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "issuer_role"
DATA = json.loads((FIX / "cases.json").read_text())
EDGAR = json.loads(gzip.decompress((FIX / "edgar.json.gz").read_bytes()))
FIGI = json.loads((FIX / "figi.json").read_text())
MIDAS = json.loads((FIX / "midas.json").read_text())
HALTS = json.loads((FIX / "halts.json").read_text())
AS_OF = date.fromisoformat(DATA["as_of"])


class FixtureEdgar:
    """The cases' EDGAR answers as the fixture recorded them. A raw or a text the cache lacked reads as "" (as an
    unreadable filing); `texts_read` lists every 8-K text read. The fixture recorded no full-text searches, so it
    states the search absent: stage 8b's 8-K12B candidate and stage 9's 8-K12B search are not run here."""

    full_text_search = None      # the fixture recorded no full-text searches (`capabilities.FULL_TEXT_SEARCH`)

    def __init__(self) -> None:
        self.texts_read: list[str] = []

    def company_tickers(self):
        return {}

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

    def company_search_atom(self, name, form_type="25-NSE"):
        return []


class FixtureFigi:
    """OpenFIGI's cached answers to the CUSIP jobs a successor link may send; any other job is an error answer."""

    def map(self, jobs, *, use_cache=True):
        return [FIGI.get(j.get("idValue", ""), {"error": "not in the fixture"}) for j in jobs]


class FixtureMidas(MidasClient):
    """MIDAS's per-quarter days with exchange volume, as the fixture recorded them for the case tickers."""

    def __init__(self) -> None:
        self._summaries = {}
        self._warned_misses = set()

    def links(self):
        return {(int(q[:4]), int(q[-1])): q for q in MIDAS["quarters"]}

    def _summary(self, yq):
        return MIDAS["days"].get(f"{yq[0]}_q{yq[1]}", {})


class FixtureHalts(NasdaqHaltClient):
    """The Nasdaq code-D halts of the case tickers on the cached halt days; any other day has none."""

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
def world() -> tuple[dict[str, Security], dict[str, AddedSecurity], dict[str, list[str]], FtdIndex]:
    """The fixture's observed securities, the acquirers and successors the committed run added (as acquirers: a
    ticker and a span), every security's CUSIPs, and the fails rows as one index."""
    securities = {sid: _security(sid) for sid, d in DATA["securities"].items() if d["observed"]}
    added: dict[str, AddedSecurity] = {}
    for sid, d in DATA["securities"].items():
        if not d["observed"] and d["history"]:
            ticker, first, _ = d["history"][0]
            added[sid] = AddedAcquirer(Security(sid, d["issuer_cik"], d["share_class"], d["name"], d["security_type"],
                                                False, d["figi_source"]), ticker, date.fromisoformat(first))
    cusips = {sid: list(d["cusips"]) for sid, d in DATA["securities"].items()}
    with io.TextIOWrapper(gzip.open(FIX / "ftd_rows.csv.gz"), encoding="utf-8", newline="") as fh:
        rows = [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"], float(r["price"]) if r["price"] else None)
                for r in csv.DictReader(fh)]
    return securities, added, cusips, FtdIndex(rows)


def clients(edgar: FixtureEdgar | None = None) -> pipeline.Clients:
    edgar = edgar or FixtureEdgar()
    return pipeline.Clients(edgar=edgar, resolver=None, classifier=DelistClassifier(edgar, TickerResolver(edgar),
                                                                                      today=AS_OF),
                            figi=FixtureFigi(), ftd_client=None, midas=FixtureMidas(), halts=FixtureHalts(),
                            as_of=AS_OF)


def find(sec_id: str, c: pipeline.Clients) -> tuple[list[Delisting], list[ReviewItem]]:
    """Stage 5: the finder's delistings and review items for the case."""
    securities, _, cusips, ftd = world()
    contexts = SecurityContexts.observed(securities, cusips, ftd)
    finder = DelistingFinder(c.edgar, c.classifier, midas=c.midas, halts=c.halts)
    return finder.find(contexts(securities[sec_id], DATA["securities"][sec_id]["listed"]))


def _payouts(sec_id: str, found: list[Delisting]) -> MergerValues:
    """Stage 8's answer for the case, the terms the committed contract published for its merger rows standing in
    for the LLM's (none passed the gate: the gate is not replayed)."""
    terms = DATA["cases"][sec_id]["terms"]
    records = {}
    for d in found:
        t = terms.get(d.delist_date)
        if d.record.bucket is CrspBucket.MERGER and t is not None:
            cash, ratio, ticker = (float(t[0]) if t[0] else None), (float(t[1]) if t[1] else None), t[2] or None
            records[d.key] = MergerValue(d.key, llm=MergerTerms(
                "cash_and_stock" if cash and ratio else "stock" if ratio else "cash", cash, ratio, None, ticker,
                "high", "fixture", ""))
    _, added, _, _ = world()
    return MergerValues(records, added=dict(added))


def after(sec_id: str, *, edgar: FixtureEdgar | None = None) -> list[Delisting]:
    """The case's delistings after stage 9: stage 5's, rewritten by stage 8b and linked by stage 9."""
    c = clients(edgar)
    found, _ = find(sec_id, c)
    return later(sec_id, found, c)


def later(sec_id: str, found: list[Delisting], c: pipeline.Clients) -> list[Delisting]:
    """Stages 8b and 9 over the case's stage-5 delistings (`find`), in place: each reads the own-share reading its
    delisting carries, else makes one (`own_shares.of`)."""
    securities, _, cusips, ftd = world()
    sightings = {sid: ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    ctx = pipeline._RunContext(c, AS_OF, lambda *a: None, 1, StageMeter(lambda *a: None))
    payouts = _payouts(sec_id, found)
    acquirers = dict(payouts.added) | pipeline._r1_continuations(ctx, found, securities, sightings, payouts).added
    pipeline._find_successors(ctx, found, securities, sightings, acquirers, {}, ftd, cusips)
    return found


def outcome(sec_id: str, **kw) -> list[tuple]:
    """What the run gives the case: each delisting as (delist_date, bucket, CRSP code, successor sec_id, how the
    successor was found), in order."""
    return [(d.delist_date, d.record.bucket.value, d.record.crsp_code, d.record.successor_sec_id or "",
             successor_by(d)) for d in after(sec_id, **kw)]

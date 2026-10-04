"""Sub-plan 5b's real cases, replayed offline: tests/fixtures/form25_reach/ (built once from the local caches by
scripts/build_form25_fixtures.py) holds each case's security, the other securities of its issuer, their fails
rows, and the EDGAR, MIDAS and Nasdaq-halt answers the finder reads. `find(sec_id)` runs the run's own stage-5
code over them: the pipeline's context builder (`pipeline._context_builder`) and `delistings.DelistingFinder`."""
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
from delist_detection.midas import MidasClient
from delist_detection.nasdaq_halts import Halt, NasdaqHaltClient
from delist_detection.observations import Observation, TickerEra
from delist_detection.review_triage import ReviewItem
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "form25_reach"
DATA = json.loads((FIX / "cases.json").read_text())
EDGAR = json.loads(gzip.decompress((FIX / "edgar.json.gz").read_bytes()))
MIDAS = json.loads((FIX / "midas.json").read_text())
HALTS = json.loads((FIX / "halts.json").read_text())
AS_OF = date.fromisoformat(DATA["as_of"])


class FixtureEdgar:
    """The cases' EDGAR answers as the fixture recorded them. A raw or a text the cache lacked reads as "" (as
    an unreadable filing); `raws_read` lists every Form 25 raw the finder asked for."""

    def __init__(self) -> None:
        self.raws_read: list[str] = []

    def company_tickers(self):
        return {}

    def submissions(self, cik, fresh_after=None):
        d = EDGAR["issuers"].get(str(int(cik)))
        return {} if d is None else {k: d[k] for k in ("name", "formerNames", "tickers", "exchanges", "sic")}

    def recent_filings(self, cik):
        return [EdgarSubmission(*f) for f in EDGAR["issuers"].get(str(int(cik)), {}).get("filings", [])]

    def fetch_filing_raw(self, cik, accession):
        self.raws_read.append(accession)
        return EDGAR["raws"].get(accession, "")

    def fetch_filing_text(self, cik, accession, primary_doc):
        return EDGAR["texts"].get(accession, "")

    def company_search_atom(self, name, form_type="25-NSE"):
        return []


class FixtureMidas(MidasClient):
    """MIDAS's per-quarter days with exchange volume, as the fixture recorded them for the case tickers; the
    real client's `last_trade_day` reads them (the coverage edge included)."""

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
def world() -> tuple[dict[str, Security], dict[str, list[str]], FtdIndex]:
    """Every security of the fixture, its CUSIPs, and the fails rows as one index."""
    securities = {sid: _security(sid) for sid in DATA["securities"]}
    cusips = {sid: list(d["cusips"]) for sid, d in DATA["securities"].items()}
    with io.TextIOWrapper(gzip.open(FIX / "ftd_rows.csv.gz"), encoding="utf-8", newline="") as fh:
        rows = [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"], float(r["price"]) if r["price"] else None)
                for r in csv.DictReader(fh)]
    return securities, cusips, FtdIndex(rows)


def finder(edgar: FixtureEdgar | None = None) -> DelistingFinder:
    edgar = edgar or FixtureEdgar()
    classifier = DelistClassifier(edgar, TickerResolver(edgar), today=AS_OF)
    return DelistingFinder(edgar, classifier, midas=FixtureMidas(), halts=FixtureHalts())


def context(sec_id: str):
    """The case's `SecurityContext`, as stage 5 builds it (`pipeline._context_builder`)."""
    securities, cusips, ftd = world()
    sightings = {sid: ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    build = pipeline._context_builder(securities, sightings, pipeline._IssuerAnswers({}, {}, {}, set()), ftd, cusips)
    return build(securities[sec_id], DATA["securities"][sec_id]["listed"])


def find(sec_id: str, *, edgar: FixtureEdgar | None = None, **kw) -> tuple[list[Delisting], list[ReviewItem]]:
    """The finder's delistings and review items for the case."""
    return finder(edgar).find(context(sec_id, **kw))


def outcome(sec_id: str, **kw) -> tuple[list[tuple], list[str]]:
    """What the finder gives the case: each delisting as (delist_date, bucket, CRSP code, last trade day, whether
    its successor is the security itself, Form 25 accession, filer CIK), in order, and its review items' flags,
    sorted and once each."""
    found, review = find(sec_id, **kw)
    return ([(d.delist_date, d.record.bucket.value, d.record.crsp_code,
              d.last_trade.day.isoformat() if d.last_trade.day else "", d.record.successor_sec_id == sec_id,
              d.form25_sub.accession if d.form25_sub else "", d.cik) for d in found],
            sorted({r.flag for r in review}))

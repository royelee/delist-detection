"""Sub-plan 5e's real cases, replayed offline: tests/fixtures/acquirer_gate/ (built once from the local caches by
scripts/build_acquirer_gate_fixtures.py) holds each case's merger row, the LLM terms the run read, the securities an
acquirer lookup may name with their observations, CUSIPs and fails rows, and the EDGAR, resolver and OpenFIGI answers.
`outcome(sec_id)` runs the run's own stage 8 over them (`pipeline._merger_payouts`: the acquirer lines, the payout
gate, the acquirer securities and the price tickers), the case's own regex read and LLM terms standing in for the
extractors."""
from __future__ import annotations

import csv
import gzip
import io
import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from delist_detection import pipeline
from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import Delisting
from delist_detection.figi_resolution import security_kind
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.history import ticker_sightings
from delist_detection.last_trade import LastTrade
from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.manifest import StageMeter
from delist_detection.observations import Observation, TickerEra
from delist_detection.payout_extractor import PayoutResult
from delist_detection.security_master import Security
from delist_detection.store import DelistingKey
from delist_detection.ticker_resolver import TickerResolution

FIX = Path(__file__).parent / "fixtures" / "acquirer_gate"
DATA = json.loads((FIX / "cases.json").read_text())
EDGAR = json.loads((FIX / "edgar.json").read_text())
FIGI = json.loads((FIX / "figi.json").read_text())
AS_OF = date.fromisoformat(DATA["as_of"])


class FixtureEdgar:
    def submissions(self, cik, fresh_after=None):
        return EDGAR.get(str(int(cik))) or {}

    def company_tickers(self):
        return {}

    def recent_filings(self, cik):
        return []           # the first filing is unknown: the issuer check passes on its names alone


class FixtureFigi:
    def map(self, jobs, *, use_cache=True):
        return [FIGI.get(j.get("idValue", ""), {"error": "not in the fixture"}) for j in jobs]


class FixtureResolver:
    """The resolver's cached answers for the cases' acquirer tickers (asked with the acquirer name); any other
    lookup is no answer."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.answers = {k: v for c in DATA["cases"].values() for k, v in c["resolved"].items()}

    def resolve(self, ticker, observed_date=None, **kw):
        key = f"{ticker}|{observed_date}"
        self.asked.append(key)
        return TickerResolution(ticker, self.answers.get(key), None, "fixture")

    def flush(self):
        pass


class NoFtd:
    """No fails file: an index extension finds nothing beyond the fixture's rows."""

    def urls_for(self, lo, hi):
        return []

    def rows(self, url, **kw):
        return iter(())


class CaseExtractor:
    """The case's own read: its regex payout (`raw`) or its LLM terms (`terms`)."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def extract(self, record, last_close=None):
        case = DATA["cases"][record.sec_id]
        if self.kind == "raw":
            raw = case["raw"]
            return None if raw is None else PayoutResult(raw[0], raw[2], raw[1], "", "")
        t = case["terms"]
        return None if t is None else MergerTerms(*t)


def _security(sec_id: str) -> Security:
    d = DATA["securities"][sec_id]
    eras = []
    for key, obs in d["eras"].items():
        ticker, _, rest = key.partition("@")
        seq = int(rest.split("#")[1]) if "#" in rest else 0
        observations = [Observation(t, a, n or None, c or None, int(p) if p else None) for t, a, n, c, p in obs]
        eras.append(TickerEra(ticker, observations[0].as_of, observations[-1].as_of, observations, seq=seq))
    eras.sort(key=lambda e: (e.first, e.seq))
    return Security(sec_id, int(d["issuer_cik"]) if d["issuer_cik"] else None, d["share_class"], d["name"],
                    d["security_type"], d["observed"] == "true", d["figi_source"],
                    kind=security_kind(d["security_type"], d["name"]), eras=eras)


def _rows() -> list[FtdRow]:
    text = gzip.decompress((FIX / "ftd_rows.csv.gz").read_bytes()).decode()
    return [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"], float(r["price"]) if r["price"] else None)
            for r in csv.DictReader(io.StringIO(text))]


@lru_cache(maxsize=1)
def world() -> tuple[dict[str, Security], dict[str, list[str]], list[FtdRow]]:
    securities = {sid: _security(sid) for sid in DATA["securities"]}
    cusips = {sid: list(d["cusips"]) for sid, d in DATA["securities"].items()}
    return securities, cusips, _rows()


def delisting(sec_id: str) -> Delisting:
    c = DATA["cases"][sec_id]
    rec = DelistRecord(c["ticker"], c["cik"], c["last_trade_date"], 231, CrspBucket.MERGER, "high", "M&A",
                       evidence={"flags": []}, sec_id=sec_id, delist_date=c["delist_date"])
    return Delisting(sec_id, c["cik"], c["ticker"], c["delist_date"], rec,
                     LastTrade(date.fromisoformat(c["last_trade_date"]), c["last_trade_source"], ()), None, None, "")


class Outcome(NamedTuple):
    price_sec_id: str
    price_ticker: str
    gate: str            # passed | failed
    priced_by: str       # ticker | line | ""
    acquirer_price: float | None
    flags: tuple[str, ...]


def payouts(sec_id: str, *, ftd_lo: date = date(2007, 12, 17), answer: tuple[str, float] | None = None
            ) -> tuple[pipeline._Payouts, Delisting, FixtureResolver]:
    """The run's stage 8 over the case; `answer` is the caller's received_close answer (the request's lookup_ticker
    and the price), as `--price-answers` applies it."""
    securities, cusips, rows = world()
    resolver = FixtureResolver()
    clients = pipeline.Clients(edgar=FixtureEdgar(), resolver=resolver, classifier=None, figi=FixtureFigi(),
                               ftd_client=NoFtd(), payout_extractor=CaseExtractor("raw"),
                               llm_extractor=CaseExtractor("terms"), as_of=AS_OF)
    ctx = pipeline._RunContext(clients, AS_OF, lambda *a: None, 1, StageMeter(lambda *a: None))
    ftd = FtdIndex(rows)
    sightings = {sid: ticker_sightings(s, ftd, cusips.get(sid, [])) for sid, s in securities.items()}
    e = delisting(sec_id)
    close = DATA["cases"][sec_id]["last_trade_close"]
    closes = {} if close is None else {e.key: close}
    overrides = pipeline.Overrides()
    if answer is not None:
        overrides.acquirer_prices[e.key] = answer
    got = pipeline._merger_payouts(ctx, [e], securities, cusips, ftd, closes, overrides, 0.15, sightings, ftd_lo)
    return got, e, resolver


def outcome(sec_id: str, answer: tuple[str, float] | None = None) -> Outcome:
    got, e, _ = payouts(sec_id, answer=answer)
    key = DelistingKey(e.sec_id, e.delist_date)
    terms = got.gated.merged_terms.get(key) or {}
    t = DATA["cases"][sec_id]["terms"]
    ticker = got.price_tickers.get(key) or (terms.get("acquirer_ticker") or (t[4] if t else "") or "").upper()
    return Outcome(got.acquirer_ids.get(key, ""), ticker, "passed" if terms or key in got.gated.payouts else "failed",
                   got.gated.priced_by.get(key, ""), terms.get("acquirer_price"), tuple(e.flags))

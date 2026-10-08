"""Sub-plan 5g's real cases, replayed offline: tests/fixtures/distress/ (built once from the local caches by
scripts/build_distress_fixtures.py, which is scripts/build_form25_fixtures.py over this sub-plan's cases) holds each
case's security, the other securities of its issuer, their fails rows, and the EDGAR, MIDAS and Nasdaq-halt answers.
`outcome(sec_id)` runs the run's own code over them: stage 5 (`delistings.SecurityContexts`,
`delistings.DelistingFinder`), then stage 9e (`pipeline._distress`), and the payout rule the contract publishes for
each delisting (`payout_rule.value_fields`)."""
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
from delist_detection.delistings import Delisting, DelistingFinder, SecurityContexts
from delist_detection.edgar import EdgarSubmission
from delist_detection.exit_kind import DROP_REASON_OF_CODE
from delist_detection.figi_resolution import security_kind
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.manifest import StageMeter
from delist_detection.midas import MidasClient
from delist_detection.nasdaq_halts import Halt, NasdaqHaltClient
from delist_detection.observations import Observation, TickerEra
from delist_detection.payout_rule import value_fields
from delist_detection.review_triage import ReviewItem
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "distress"
DATA = json.loads((FIX / "cases.json").read_text())
EDGAR = json.loads(gzip.decompress((FIX / "edgar.json.gz").read_bytes()))
MIDAS = json.loads((FIX / "midas.json").read_text())
HALTS = json.loads((FIX / "halts.json").read_text())
AS_OF = date.fromisoformat(DATA["as_of"])


class FixtureEdgar:
    """The cases' EDGAR answers as the fixture recorded them. A raw or a text the cache lacked reads as "" (as an
    unreadable filing); `texts_read` lists every 8-K text read."""

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
def world() -> tuple[dict[str, Security], dict[str, list[str]], FtdIndex]:
    """Every security of the fixture, its CUSIPs, and the fails rows as one index."""
    securities = {sid: _security(sid) for sid in DATA["securities"]}
    cusips = {sid: list(d["cusips"]) for sid, d in DATA["securities"].items()}
    with io.TextIOWrapper(gzip.open(FIX / "ftd_rows.csv.gz"), encoding="utf-8", newline="") as fh:
        rows = [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"], float(r["price"]) if r["price"] else None)
                for r in csv.DictReader(fh)]
    return securities, cusips, FtdIndex(rows)


def clients(edgar: FixtureEdgar | None = None) -> pipeline.Clients:
    edgar = edgar or FixtureEdgar()
    return pipeline.Clients(edgar=edgar, resolver=None, classifier=DelistClassifier(edgar, TickerResolver(edgar),
                                                                                      today=AS_OF),
                            figi=None, ftd_client=None, midas=FixtureMidas(), halts=FixtureHalts(), as_of=AS_OF)


def find(sec_id: str, c: pipeline.Clients) -> tuple[list[Delisting], list[ReviewItem]]:
    """Stage 5: the finder's delistings and review items for the case (its other CIK in force as the committed run
    had it)."""
    securities, cusips, ftd = world()
    other = DATA["cases"][sec_id]["other_cik"]
    contexts = SecurityContexts.observed(securities, cusips, ftd, other_ciks={sec_id: other} if other else {})
    finder = DelistingFinder(c.edgar, c.classifier, midas=c.midas, halts=c.halts)
    return finder.find(contexts(securities[sec_id], DATA["securities"][sec_id]["listed"]))


def after(sec_id: str, *, edgar: FixtureEdgar | None = None):
    """The case's delistings after stage 9e, with each one's distress terms and the review items."""
    c = clients(edgar)
    found, review = find(sec_id, c)
    _, cusips, ftd = world()
    ctx = pipeline._RunContext(c, AS_OF, lambda *a: None, 1, StageMeter(lambda *a: None))
    terms = pipeline._distress(ctx, found, cusips, ftd, review)
    return found, terms, review


def _row(d: Delisting) -> dict[str, str]:
    """The delistings.csv cells `payout_rule.value_fields` reads, for a delisting with no merger terms."""
    rec = d.record
    return {"sec_id": d.sec_id, "ticker": d.ticker, "bucket": rec.bucket.value,
            "crsp_code": "" if rec.crsp_code is None else str(rec.crsp_code),
            "successor_sec_id": rec.successor_sec_id or "", "dlret_method": "", "dlret": "", "recovery_ratio": "",
            "payout_per_share": "", "stock_ratio": "", "acquirer_ticker": "", "acquirer_sec_id": "",
            "payout_source": "", "last_trade_close": ""}


def outcome(sec_id: str, **kw) -> list[tuple]:
    """What the run gives the case: each delisting as (delist_date, bucket, CRSP code, drop reason, value rule,
    price ticker, stock ratio), in order; the value is what the contract would publish were it the last ending."""
    found, terms, _ = after(sec_id, **kw)
    out = []
    for d in found:
        ltd = d.last_trade.day.isoformat() if d.last_trade.day else ""
        f = value_fields(_row(d), ltd, None, terms.get(d.key))
        reason = DROP_REASON_OF_CODE.get(str(d.record.crsp_code), "")
        out.append((d.delist_date, d.record.bucket.value, d.record.crsp_code, reason, f["value_rule"],
                    f["price_ticker"], f["stock_ratio"] or ""))
    return out

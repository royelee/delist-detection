"""Offline replay of the golden cases captured by scripts/build_golden_fixtures.py."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import requests

from delist_detection import ticker_resolver
from delist_detection.edgar import EdgarSubmission
from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.ticker_resolver import TickerResolver

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "golden"
# Read at import, before the autouse fixture in conftest.py replaces them for each test.
_REAL_EFTS = {name: getattr(TickerResolver, name)
              for name in ("_efts_lookup", "_efts_pre_delist_frequency_ranked")}


@dataclass(frozen=True)
class GoldenCase:
    ticker: str
    observed_delist_date: str
    cik: int
    member_name: str
    last_trade_close: float
    expected_bucket: str
    expected_dlret: float | None
    dlret_tol: float | None
    expected_flags: tuple[str, ...]
    data: dict

    @property
    def id(self) -> str:
        return f"{self.ticker}_{self.observed_delist_date}"

    @property
    def llm_terms(self) -> MergerTerms | None:
        """The LLM merger terms captured for this case, or None when none were captured."""
        terms = self.data.get("llm_terms")
        return MergerTerms(**terms) if terms else None


def load_cases() -> list[GoldenCase]:
    out = []
    for row in csv.DictReader((ROOT / "data" / "golden_events.csv").open()):
        data = json.loads((FIX / f"{row['ticker']}_{row['observed_delist_date']}.json").read_text())
        out.append(GoldenCase(
            ticker=row["ticker"], observed_delist_date=row["observed_delist_date"],
            cik=int(row["cik"]), member_name=row["member_name"],
            last_trade_close=float(row["last_trade_close"]),
            expected_bucket=row["expected_bucket"],
            expected_dlret=float(row["expected_dlret"]) if row["expected_dlret"] else None,
            dlret_tol=float(row["dlret_tol"]) if row["dlret_tol"] else None,
            expected_flags=tuple(f for f in row["expected_flags"].split(";") if f),
            data=data,
        ))
    return out


class GoldenEdgar:
    def __init__(self, case: GoldenCase) -> None:
        self.case = case
        self.data = case.data

    def company_tickers(self):
        return self.data["company_tickers"]

    def submissions(self, cik, fresh_after=None):
        return self.data["submissions"].get(str(int(cik)), {"__not_found__": True})

    def recent_filings(self, cik):
        sub = self.submissions(cik)
        rec = sub.get("filings", {}).get("recent", {})
        return [
            EdgarSubmission(accession=a, form=f, filing_date=fd, report_date=rd, items=it, primary_doc=pd)
            for a, f, fd, rd, it, pd in zip(
                rec.get("accessionNumber", []), rec.get("form", []), rec.get("filingDate", []),
                rec.get("reportDate", []), rec.get("items", []), rec.get("primaryDocument", []))
        ]

    def fetch_filing_text(self, cik, accession, primary_doc):
        p = FIX / "text" / f"{int(cik)}_{accession}.txt"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def fetch_filing_raw(self, cik, accession):
        p = FIX / "raw" / f"{int(cik)}_{accession}.txt"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def company_search_atom(self, company, form_type="25-NSE"):
        return self.data["atom"].get(f"{company}|{form_type}", [])


class _EftsAnswer:
    status_code = 200

    def __init__(self, url: str, payload: dict) -> None:
        self.url, self._payload = url, payload

    def json(self) -> dict:
        return self._payload


def patch_efts(monkeypatch, case: GoldenCase) -> None:
    """Run the real EFTS methods over the captured EFTS answers (efts_raw, keyed by
    URL); a URL that was not captured answers with no hits."""
    raw = case.data["efts_raw"]
    for name, method in _REAL_EFTS.items():
        monkeypatch.setattr(TickerResolver, name, method)
    monkeypatch.setattr(ticker_resolver, "requests", SimpleNamespace(
        get=lambda url, *a, **kw: _EftsAnswer(url, raw.get(url, {"hits": {"hits": []}})),
        RequestException=requests.RequestException))
    monkeypatch.setattr(ticker_resolver, "_throttle", lambda: None)

"""Offline replay of the golden cases captured by scripts/build_golden_fixtures.py."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from delist_detection.edgar import EdgarSubmission

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "golden"


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

    def submissions(self, cik):
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

    def company_search_atom(self, company, form_type="25-NSE"):
        return self.data["atom"].get(f"{company}|{form_type}", [])


def patch_efts(monkeypatch, case: GoldenCase) -> None:
    from delist_detection.names import names_agree
    from delist_detection.ticker_resolver import TickerResolver
    hit = tuple(case.data["efts_lookup"])
    freq = [tuple(x) for x in case.data["efts_frequency"]]
    first_pass = re.compile(rf"\(\s*{re.escape(case.ticker.upper())}\s*\)")

    def efts_lookup(self, t, d=None, expected_name=None, **kw):
        # The fixture holds the answer of the old _efts_lookup. A hit without
        # "(TICKER)" came from its second pass (first non-exchange CIK), which now
        # returns a CIK only when the name agrees with expected_name. Later hits
        # were not captured, so a disagreeing one replays as no hit.
        cik, nm = hit
        if cik is None or first_pass.search((nm or "").upper()) or names_agree(nm, expected_name):
            return hit
        return None, None

    monkeypatch.setattr(TickerResolver, "_efts_lookup", efts_lookup)
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: freq)

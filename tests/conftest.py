"""Test fixtures: a fake EdgarClient that serves canned submissions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from delist_detection.edgar import EdgarSubmission


@dataclass
class _FakeEdgar:
    """Minimal stand-in for EdgarClient used by classifier unit tests."""

    submissions_by_cik: dict[int, list[EdgarSubmission]]
    company_map: dict[str, dict[str, Any]]

    def company_tickers(self) -> dict[str, dict[str, Any]]:
        return self.company_map

    def recent_filings(self, cik: int | str) -> list[EdgarSubmission]:
        return list(self.submissions_by_cik.get(int(cik), []))


@pytest.fixture
def fake_edgar() -> _FakeEdgar:
    """Three companies covering merger, compliance-failure, and liquidation."""

    altair = [
        EdgarSubmission(
            accession="0001354457-25-000243", form="25-NSE",
            filing_date="2025-03-26", report_date="",
            items="", primary_doc="primary_doc.xml",
        ),
        EdgarSubmission(
            accession="0001193125-25-066329", form="8-K",
            filing_date="2025-03-28", report_date="2025-03-26",
            items="1.01,1.02,2.01,2.04,3.01,3.03,5.01,5.02,5.03,9.01",
            primary_doc="d869190d8k.htm",
        ),
        EdgarSubmission(
            accession="0001193125-25-074144", form="15-12G",
            filing_date="2025-04-07", report_date="",
            items="", primary_doc="d924412d1512g.htm",
        ),
    ]

    # Compliance-failure fabrication: Form 25 + 3.01 only.
    compliance = [
        EdgarSubmission(
            accession="A001", form="25-NSE",
            filing_date="2023-05-10", report_date="",
            items="", primary_doc="p.xml",
        ),
        EdgarSubmission(
            accession="A002", form="8-K",
            filing_date="2023-05-08", report_date="2023-05-08",
            items="3.01,8.01", primary_doc="p.htm",
        ),
    ]

    # Liquidation: Form 25 + Form 15 with non-merger 8-K (regulation FD only).
    liquidation = [
        EdgarSubmission(
            accession="B001", form="25-NSE",
            filing_date="2019-11-06", report_date="",
            items="", primary_doc="p.xml",
        ),
        EdgarSubmission(
            accession="B002", form="8-K",
            filing_date="2019-11-04", report_date="2019-11-04",
            items="7.01,9.01", primary_doc="p.htm",
        ),
        EdgarSubmission(
            accession="B003", form="15-12G",
            filing_date="2019-12-15", report_date="",
            items="", primary_doc="p.htm",
        ),
    ]

    return _FakeEdgar(
        submissions_by_cik={1701732: altair, 999001: compliance, 999002: liquidation},
        company_map={
            "ALTR": {"cik_str": 1701732, "ticker": "ALTR", "title": "Altair Engineering Inc."},
            "BAD":  {"cik_str": 999001, "ticker": "BAD",  "title": "Bad Co."},
            "LIQ":  {"cik_str": 999002, "ticker": "LIQ",  "title": "Liquidating Trust"},
        },
    )

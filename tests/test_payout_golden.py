from pathlib import Path

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarSubmission
from delist_detection.payout_extractor import PayoutExtractor

FIX = Path(__file__).parent / "fixtures"


class _FixtureEdgar:
    def __init__(self, filing, text):
        self._filing = filing
        self._text = text
    def recent_filings(self, cik):
        return [self._filing]
    def fetch_filing_text(self, cik, accession, primary_doc):
        return self._text


def _golden(name, cik, accession, doc, observed):
    path = FIX / name
    if not path.exists():
        pytest.skip(f"fixture {name} not generated; run scripts/regen_payout_fixtures.py")
    filing = EdgarSubmission(
        accession=accession, form="8-K", filing_date=observed,
        report_date=observed, items="2.01,5.01,3.01", primary_doc=doc)
    rec = DelistRecord(ticker="T", cik=cik, observed_delist_date=observed,
                       crsp_code=231, bucket=CrspBucket.MERGER,
                       confidence="high", reason="", evidence={})
    ext = PayoutExtractor(_FixtureEdgar(filing, path.read_text()))
    return ext.extract(rec)


def test_golden_altr():
    res = _golden("altr_8k_201.txt", 1701732, "0001193125-25-066329",
                  "d869190d8k.htm", "2025-03-26")
    assert res.value == 113.00
    assert res.confidence == "high"
    assert res.source == "8K_2.01"


def test_golden_atvi():
    res = _golden("atvi_8k_201.txt", 718877, "0001104659-23-108985",
                  "tm2328253d1_8k.htm", "2023-10-13")
    assert res.value == 95.00
    assert res.confidence == "high"

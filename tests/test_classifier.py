from delist_detection.classifier import DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.ticker_resolver import TickerResolver


def test_altair_classifies_as_merger(fake_edgar):
    resolver = TickerResolver(fake_edgar)
    classifier = DelistClassifier(fake_edgar, resolver)
    rec = classifier.classify_ticker("ALTR", "2025-03-26")

    assert rec.cik == 1701732
    assert rec.bucket is CrspBucket.MERGER
    assert rec.crsp_code in (200, 231, 233)
    assert rec.confidence == "high"
    assert "2.01" in rec.evidence["anchor_8k"]["items"]


def test_compliance_failure_classifies_correctly(fake_edgar):
    resolver = TickerResolver(fake_edgar)
    classifier = DelistClassifier(fake_edgar, resolver)
    rec = classifier.classify_ticker("BAD", "2023-05-10")

    assert rec.bucket is CrspBucket.COMPLIANCE_FAILURE
    assert rec.crsp_code == 570
    assert rec.evidence["delist_filing"]["form"] == "25-NSE"


def test_liquidation_fingerprint(fake_edgar):
    """Form 25 + Form 15 + non-merger 8-K should land in LIQUIDATION,
    not COMPLIANCE_FAILURE — the latter would apply -100% in training."""
    resolver = TickerResolver(fake_edgar)
    classifier = DelistClassifier(fake_edgar, resolver)
    rec = classifier.classify_ticker("LIQ", "2019-11-06")

    assert rec.bucket is CrspBucket.LIQUIDATION
    assert rec.crsp_code == 400
    assert rec.evidence["dereg_filing"]["form"] == "15-12G"


def test_unknown_ticker_returns_unknown(fake_edgar):
    resolver = TickerResolver(fake_edgar)
    classifier = DelistClassifier(fake_edgar, resolver)
    rec = classifier.classify_ticker("NOPE", "2024-01-01")
    assert rec.bucket is CrspBucket.UNKNOWN
    assert rec.cik is None


def test_a_current_ticker_map_hit_is_flagged(fake_edgar):
    resolver = TickerResolver(fake_edgar)
    rec = DelistClassifier(fake_edgar, resolver).classify_ticker("ALTR", "2025-03-26")
    assert rec.evidence["resolution_source"] == "company_tickers"
    assert rec.evidence["flags"] == ["resolved_by_current_ticker_map"]


from delist_detection.edgar import EdgarSubmission


class _TextEdgar:
    def __init__(self, filings, texts):
        self.filings, self.texts = filings, texts
    def company_tickers(self):
        return {"REORG": {"cik_str": 5, "ticker": "REORG", "title": "Reorg Co"}}
    def recent_filings(self, cik):
        return list(self.filings)
    def submissions(self, cik):
        return {"name": "Reorg Co", "formerNames": [], "sic": "1311"}
    def fetch_filing_text(self, cik, acc, doc):
        return self.texts.get(acc, "")


def test_bankruptcy_history_beats_continued_filings():
    fs = [
        EdgarSubmission("A1", "8-K", "2020-09-30", "2020-09-29", "1.01,1.03,7.01", "a.htm"),
        EdgarSubmission("A2", "25-NSE", "2020-10-27", "", "", "p.xml"),
        EdgarSubmission("A3", "10-Q", "2021-08-05", "", "", "q.htm"),   # reorganized company keeps filing
    ]
    e = _TextEdgar(fs, {"A1": "the Company filed voluntary petitions under chapter 11"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2020-11-20")
    assert rec.bucket is CrspBucket.LIQUIDATION and rec.crsp_code == 470


def test_a_1_03_tag_without_bankruptcy_text_is_not_a_bankruptcy():
    fs = [
        EdgarSubmission("B1", "8-K", "2024-11-27", "2024-11-27", "1.01,1.03,2.01,3.01,3.03,5.01", "b.htm"),
        EdgarSubmission("B2", "25-NSE", "2024-11-27", "", "", "p.xml"),
        EdgarSubmission("B3", "15-12G", "2024-12-09", "", "", "f.htm"),
    ]
    e = _TextEdgar(fs, {"B1": "completion of the merger; each share converted into the right to receive"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2024-11-27")
    assert rec.bucket is CrspBucket.MERGER
    assert "bankruptcy_tag_unconfirmed" in rec.evidence["flags"]


def test_an_old_form25_from_another_event_is_not_the_anchor():
    # 1,037 days: inside the 1,500-day window, so the operating-filings rule is what rejects it
    fs = [
        EdgarSubmission("C1", "25-NSE", "2021-08-16", "", "", "p.xml"),          # warrant delisting
        EdgarSubmission("C2", "8-K", "2021-08-16", "2021-08-16", "8.01,9.01", "c.htm"),
        EdgarSubmission("C3", "10-Q", "2023-11-05", "", "", "q.htm"),
        EdgarSubmission("C4", "8-K", "2024-06-18", "2024-06-18", "7.01,9.01", "d.htm"),
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2024-06-18")
    assert rec.evidence.get("delist_filing") is None
    assert rec.bucket is not CrspBucket.COMPLIANCE_FAILURE


def test_an_earlier_merger_form25_marks_a_frozen_tail():
    fs = [
        EdgarSubmission("D1", "8-K", "2010-06-25", "2010-06-25", "3.01,3.03,5.01", "a.htm"),
        EdgarSubmission("D2", "25-NSE", "2010-06-28", "", "", "p.xml"),
        EdgarSubmission("D3", "10-K", "2011-02-25", "", "", "k.htm"),              # registered debt
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2013-02-07")
    assert rec.evidence["delist_filing"]["accession"] == "D2"
    assert any(f.startswith("frozen_tail:") for f in rec.evidence["flags"])


import pytest


@pytest.mark.parametrize("items, code", [
    ({"3.01", "3.03", "5.01", "5.02", "5.03"}, 231),        # BCR, GXP, IRF: target 8-K without 2.01
    ({"3.01", "5.01", "9.01"}, 231),                         # FWLT
    ({"3.03", "5.01", "5.02"}, 231),
    ({"1.01", "2.04", "3.01", "3.03", "5.01"}, 231),         # ONXX, SLXP: notes put on change in control
    ({"2.04", "3.01"}, 470),                                 # distress lead-in stays distress
    ({"3.01", "8.01"}, 570),
    ({"1.03", "3.01"}, 470),
])
def test_item_fingerprints(items, code):
    c = DelistClassifier(edgar=None, resolver=None)
    assert c._classify_items(items)[0] == code

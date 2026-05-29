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

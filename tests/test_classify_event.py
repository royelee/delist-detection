from delist_detection.classifier import DelistClassifier, DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.ticker_resolver import TickerResolver


def _clf(fake_edgar):
    return DelistClassifier(fake_edgar, TickerResolver(fake_edgar))


def test_event_with_known_form25_matches_classify_ticker(fake_edgar):
    clf = _clf(fake_edgar)
    f25 = next(f for f in fake_edgar.recent_filings(1701732) if f.form == "25-NSE")
    ev = clf.classify_event(ticker="ALTR", cik=1701732, anchor_date="2025-03-25",
                            name="Altair Engineering Inc.", form25=f25)
    old = clf.classify_ticker("ALTR", "2025-03-26")
    assert ev.bucket is old.bucket is CrspBucket.MERGER
    assert ev.crsp_code == old.crsp_code
    assert ev.cik == 1701732
    assert ev.observed_delist_date == "2025-03-25"
    assert ev.evidence["delist_filing"]["accession"] == f25.accession
    assert ev.evidence["resolution_source"] == "security_master"


def test_event_without_form25_picks_one_like_classify_ticker(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="BAD", cik=999001, anchor_date="2023-05-10")
    assert ev.bucket is CrspBucket.COMPLIANCE_FAILURE and ev.crsp_code == 570


def test_event_non_equity_kind_is_expiration(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="GSF", cik=886982, anchor_date="2021-01-04", kind="debt")
    assert ev.bucket is CrspBucket.EXPIRATION and ev.crsp_code == 600 and ev.cik == 886982
    assert ev.evidence["asset_type"] == "debt"


def test_event_name_mismatch_is_flagged(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="ALTR", cik=1701732, anchor_date="2025-03-25",
                                         expected_name="Monsanto Company")
    assert "member_name_mismatch" in ev.evidence["flags"]


def test_delist_record_new_fields_default_none():
    r = DelistRecord("X", 1, "2020-01-01", 231, CrspBucket.MERGER, "high", "r")
    assert r.sec_id is None and r.delist_date is None and r.successor_sec_id is None
    assert r.to_dict()["sec_id"] is None

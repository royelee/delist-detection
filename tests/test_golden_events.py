import pytest

from delist_detection.classifier import DelistClassifier
from delist_detection.payout_extractor import PayoutExtractor
from delist_detection.payout_gate import DEFAULT_TOL, reconcile
from delist_detection.ticker_resolver import TickerResolver
from tests.golden import GoldenEdgar, load_cases, patch_efts

CASES = load_cases()

# Production pins IMCL in MANUAL_OVERRIDES and there is no automatic path to it (no
# Form 25; a recycled OTC shell), so the golden test pins it too. Every other ticker
# resolves with no overrides: this measures the automatic path.
GOLDEN_MANUAL = {"IMCL": 1520047}

# case id -> the task after which test_golden_bucket_and_flags passes. Delete entries
# as tasks land; if a case still fails only for a later task's rule, move it there.
XFAIL_BUCKET: dict[str, int] = {}


def _classify(case, monkeypatch, names=None):
    edgar = GoldenEdgar(case)
    patch_efts(monkeypatch, case)
    name = names if names is not None else (lambda t, d=None: case.member_name)
    resolver = TickerResolver(edgar, manual_overrides=GOLDEN_MANUAL, observed_names=name)
    return DelistClassifier(edgar, resolver).classify_ticker(case.ticker, case.observed_delist_date)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_golden_bucket_and_flags(case, monkeypatch, request):
    if case.id in XFAIL_BUCKET:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"fixed by Task {XFAIL_BUCKET[case.id]}"))
    rec = _classify(case, monkeypatch)
    assert rec.bucket.value == case.expected_bucket, rec.reason
    flags = rec.evidence.get("flags", [])
    assert set(case.expected_flags) <= {f.split(":")[0] for f in flags}, flags
    assert rec.cik == case.cik


PAYOUT_CASES = [c for c in CASES if c.expected_bucket == "merger" and c.expected_dlret is not None]


@pytest.mark.parametrize("case", PAYOUT_CASES, ids=[c.id for c in PAYOUT_CASES])
def test_golden_payout(case, monkeypatch):
    rec = _classify(case, monkeypatch)
    pr = PayoutExtractor(GoldenEdgar(case)).extract(rec, last_close=case.last_trade_close)
    r = reconcile(pr.value, case.last_trade_close, case.llm_terms, case.data.get("acquirer_price"), DEFAULT_TOL)
    assert r.cash is not None or r.stock_ratio is not None, (pr, r)
    value = r.cash if r.cash is not None else r.stock_ratio * r.acquirer_price
    implied = value / case.last_trade_close - 1
    assert abs(implied - case.expected_dlret) <= case.dlret_tol, (pr, r)


from datetime import date


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_golden_classify_event_matches_classify_ticker(case, monkeypatch):
    """classify_event, given the CIK and the Form 25 classify_ticker anchors on, lands
    in the same bucket with the same code: the new entry point reuses the rules."""
    edgar = GoldenEdgar(case)
    patch_efts(monkeypatch, case)
    resolver = TickerResolver(edgar, manual_overrides=GOLDEN_MANUAL,
                              observed_names=lambda t, d=None: case.member_name)
    clf = DelistClassifier(edgar, resolver)
    old = clf.classify_ticker(case.ticker, case.observed_delist_date)
    assert old.cik is not None
    f25, _ = clf._pick_delist_filing(edgar.recent_filings(old.cik), date.fromisoformat(case.observed_delist_date),
                                     old.cik)
    new = clf.classify_event(ticker=case.ticker, cik=old.cik, anchor_date=case.observed_delist_date,
                             name=old.evidence.get("name"), expected_name=case.member_name, form25=f25)
    assert new.bucket is old.bucket, (old.reason, new.reason)
    assert new.crsp_code == old.crsp_code

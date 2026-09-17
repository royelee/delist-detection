import pytest

from delist_detection.classifier import DelistClassifier
from delist_detection.payout_extractor import PayoutExtractor
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

# case id -> the task after which test_golden_payout passes. Delete entries as tasks
# land; if a case still fails only for a later task's rule, move it there.
XFAIL_PAYOUT: dict[str, int] = {
    # BLD is a cash-or-stock election: _select abstains (mixed=True) by design.
    # Task 11 resolves the election via a price check.
    "BLD_2026-07-01": 11,
}


def _classify(case, monkeypatch, names=None):
    edgar = GoldenEdgar(case)
    patch_efts(monkeypatch, case)
    name = names if names is not None else (lambda t, d=None: case.member_name)
    resolver = TickerResolver(edgar, manual_overrides=GOLDEN_MANUAL, member_names=name)
    return DelistClassifier(edgar, resolver).classify_ticker(case.ticker, case.observed_delist_date)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_golden_bucket_and_flags(case, monkeypatch, request):
    if case.id in XFAIL_BUCKET:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"fixed by Task {XFAIL_BUCKET[case.id]}"))
    rec = _classify(case, monkeypatch)
    assert rec.bucket.value == case.expected_bucket, rec.reason
    flags = rec.evidence.get("flags", [])
    assert set(case.expected_flags) <= {f.split(":")[0] for f in flags}, flags
    if case.expected_bucket not in ("unknown",) and "member_name_mismatch" not in case.expected_flags:
        assert rec.cik == case.cik


PAYOUT_CASES = [c for c in CASES if c.expected_bucket == "merger" and c.expected_dlret is not None]


@pytest.mark.parametrize("case", PAYOUT_CASES, ids=[c.id for c in PAYOUT_CASES])
def test_golden_payout(case, monkeypatch, request):
    if case.id in XFAIL_PAYOUT:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"fixed by Task {XFAIL_PAYOUT[case.id]}"))
    rec = _classify(case, monkeypatch)
    pr = PayoutExtractor(GoldenEdgar(case)).extract(rec, last_close=case.last_trade_close)
    assert pr.value is not None, pr
    implied = pr.value / case.last_trade_close - 1
    assert abs(implied - case.expected_dlret) <= case.dlret_tol, pr

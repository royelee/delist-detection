import pytest

from delist_detection.classifier import DelistClassifier
from delist_detection.ticker_resolver import TickerResolver
from tests.golden import GoldenEdgar, load_cases, patch_efts

CASES = load_cases()

# Production pins IMCL in MANUAL_OVERRIDES and there is no automatic path to it (no
# Form 25; a recycled OTC shell), so the golden test pins it too. Every other ticker
# resolves with no overrides: this measures the automatic path.
GOLDEN_MANUAL = {"IMCL": 1520047}

# case id -> the task after which test_golden_bucket_and_flags passes. Delete entries
# as tasks land; if a case still fails only for a later task's rule, move it there.
XFAIL_BUCKET = {
    # renames / listing transfers
    "LC_2026-06-01": 7,     # 570: the 3.01 notice announces the move to Nasdaq
    "SKLZ_2026-06-18": 7,   # 570 anchored on the 2021-08-16 Form 25 (needs Task 5 too)
    # SPAC (each resolves to the SPAC and already carries member_name_mismatch)
    "FST_2022-08-25": 8,    # 400: Form 25 + Form 15, no merger 8-K
    "BWC_2023-08-11": 8,    # 580: 3.01 + NT 10-K
    "HMA_2023-07-25": 8,    # 580: 3.01 + NT 10-K
    "LEAP_2022-08-16": 8,   # 400: Form 25 + Form 15, 8-K without M&A items
    # no-evidence defaults
    "SIAL_2015-11-18": 9,   # 400: anchor 8-K is 8.01; the proxy (DEFM14A 2014-11-03) is not read
    "UTIW_2016-02-01": 9,   # 400: 2.01 alone is not a fingerprint
    "AABA_2019-11-06": 9,   # 400: Form 25 + a 2011 Form 15, 7.01 8-K; solvent dissolution
    "KCI_2012-11-12": 9,    # 570: the anchor 8-K is the 3.01-only notice (Task 5 flags the tail), and
                            # Task 9 finds the DEFM14A (2011-09-26) 43 days before the Form 25
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

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
    # bankruptcy history
    "HLTH_2019-09-10": 4,   # 580 via the 3.01; flag from Task 3, liquidation from the receivership
                            # 8-K (1.03, 2019-09-24) inside Task 4's after=30 window
    "OAS_2020-11-20": 4,    # unresolved (every EFTS candidate fails strict validation); the member
                            # name resolves it in Task 3, the 1.03 of 2020-09-30 decides in Task 4
    "MDR_2020-01-22": 4,    # unresolved (708819 fails strict validation: 10-Q 107 days later); Task 3
                            # resolves it, then 570 via the 3.01 until Task 4 reads the 1.03
    "WE_2024-06-11": 4,     # EFTS second pass takes Adastra (1891512) -> unknown; the member name
                            # resolves 1813756 in Task 3, Task 4 reads its 1.03s
    "LYLT_2023-06-27": 4,   # 570 from the 3.01+3.03 8-K; the 1.03 8-K of 2023-03-10 is ignored
    "VSTO_2024-11-27": 4,   # 470 from a 1.03 tag with no Item 1.03 section or bankruptcy text
    # takeover without 2.01
    "BCR_2017-12-29": 6,    # 570: closing 8-K has 3.01+3.03+5.01 without 2.01
    "ONXX_2013-10-17": 6,   # 470: 3.01+2.04 (convertible-note make-whole) beats the 5.01
    "XTO_2013-02-07": 6,    # unresolved (Form 25 955 days before the vendor end); Task 3 accepts the
                            # member-name hit (existed, agreeing name, filing near the date), Task 5
                            # anchors on the 2010 Form 25 (frozen_tail), Task 6 reads 3.01+3.03+5.01
    # renames / listing transfers
    "LC_2026-06-01": 7,     # 570: the 3.01 notice announces the move to Nasdaq
    "SKLZ_2026-06-18": 7,   # 570 anchored on the 2021-08-16 Form 25 (needs Task 5 too)
    # SPAC (each also needs Task 3's member_name_mismatch flag)
    "FST_2022-08-25": 8,    # 400: Form 25 + Form 15, no merger 8-K
    "BWC_2023-08-11": 8,    # 580: 3.01 + NT 10-K
    "HMA_2023-07-25": 8,    # 580: 3.01 + NT 10-K
    "LEAP_2022-08-16": 8,   # 400; Task 3's name match ignores the ticker token, so Ribbit LEAP vs
                            # Leap Wireless gets member_name_mismatch
    # no-evidence defaults
    "SIAL_2015-11-18": 9,   # 400: anchor 8-K is 8.01; the proxy (DEFM14A 2014-11-03) is not read
    "UTIW_2016-02-01": 9,   # 400: 2.01 alone is not a fingerprint
    "AABA_2019-11-06": 9,   # 400: Form 25 + a 2011 Form 15, 7.01 8-K; solvent dissolution
    "KCI_2012-11-12": 9,    # unresolved (Task 3 resolves it; Task 5 flags the tail); the anchor 8-K is
                            # the 3.01-only notice, and Task 9 finds the DEFM14A (2011-09-26) 43 days
                            # before the Form 25
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

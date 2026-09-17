import pytest

from delist_detection.classifier import DelistClassifier
from delist_detection.ticker_resolver import TickerResolver
from tests.golden import GoldenEdgar, load_cases, patch_efts

CASES = load_cases()

# case id -> the task after which test_golden_bucket_and_flags passes. Delete entries
# as tasks land; if a case still fails only for a later task's rule, move it there.
# The resolver runs without MANUAL_OVERRIDES: this measures the automatic path.
XFAIL_BUCKET = {
    # member names / date-aware company match
    "PEAK_2023-02-13": 3,   # EFTS second pass takes Far Peak (1829426) -> 570
    "CPWR_2014-12-15": 3,   # company_tickers gives today's CPWR, Ocean Thermal (827099) -> 304
    "IMCL_2018-10-05": 3,   # unresolved; only MANUAL_OVERRIDES finds 1520047 (no Form 25/EFTS/8-K
                            # hit for IMCL, and the member-name search finds ImClone 765258)
    "HLTH_2019-09-10": 3,   # bucket already right (580); member_name_mismatch flag missing
    # bankruptcy history (each also needs Task 3 to resolve first, except LYLT and VSTO)
    "SPWR_2024-08-20": 4,   # company_tickers gives 1838987 (Complete Solaria on the date) -> 304
    "OAS_2020-11-20": 4,    # unresolved: every EFTS candidate fails strict validation
    "MDR_2020-01-22": 4,    # unresolved: 708819 fails strict validation (10-Q 107 days later);
                            # with the CIK it is 570 via the 3.01 of 2020-01-23
    "WE_2024-06-11": 4,     # EFTS second pass takes Adastra (1891512) -> unknown
    "LYLT_2023-06-27": 4,   # 570 from the 3.01+3.03 8-K; the 1.03 8-K of 2023-03-10 is ignored
    "VSTO_2024-11-27": 4,   # 470 from a 1.03 tag with no Item 1.03 section or bankruptcy text
    # Form 25 anchor sanity
    "XTO_2013-02-07": 5,    # unresolved; only MANUAL_OVERRIDES finds 868809: _validate_cik needs a
                            # Form 25/15 within 540 days and XTO's is 955 days before; then 3.01+5.01
                            # needs Task 6
    # takeover without 2.01
    "BCR_2017-12-29": 6,    # 570: closing 8-K has 3.01+3.03+5.01 without 2.01
    "ONXX_2013-10-17": 6,   # 470: 3.01+2.04 (convertible-note make-whole) beats the 5.01
    # renames / listing transfers
    "HYH_2018-06-29": 7,    # unresolved: a rename files no Form 25, so _validate_cik rejects 1606498
                            # in every tier (also after Task 3's member-name search)
    "LC_2026-06-01": 7,     # 570: the 3.01 notice announces the move to Nasdaq
    "SKLZ_2026-06-18": 7,   # 570 anchored on the 2021-08-16 Form 25 (needs Task 5 too)
    # SPAC (each also needs Task 3's member_name_mismatch flag)
    "FST_2022-08-25": 8,    # 400: Form 25 + Form 15, no merger 8-K
    "BWC_2023-08-11": 8,    # 580: 3.01 + NT 10-K
    "HMA_2023-07-25": 8,    # 580: 3.01 + NT 10-K
    "LEAP_2022-08-16": 8,   # 400; Task 3's token match sees LEAP in both names, so no rule yet
                            # raises member_name_mismatch for Ribbit LEAP vs Leap Wireless
    # no-evidence defaults
    "SIAL_2015-11-18": 9,   # 400: anchor 8-K is 8.01; the proxy (DEFM14A 2014-11-03) is not read
    "UTIW_2016-02-01": 9,   # 400: 2.01 alone is not a fingerprint
    "AABA_2019-11-06": 9,   # 400: Form 25 + a 2011 Form 15, 7.01 8-K; solvent dissolution
    "KCI_2012-11-12": 9,    # unresolved (needs Task 3; Task 5 flags the tail); the anchor 8-K is the
                            # 3.01-only notice, and the DEFM14A (2011-09-26) is 413 days before the
                            # vendor end, outside Task 9's 400-day merger-evidence window
}


def _classify(case, monkeypatch, names=None):
    edgar = GoldenEdgar(case)
    patch_efts(monkeypatch, case)
    name = names if names is not None else (lambda t, d=None: case.member_name)
    resolver = TickerResolver(edgar, member_names=name)
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

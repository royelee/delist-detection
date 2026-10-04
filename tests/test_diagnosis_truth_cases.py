"""The diagnosis truth set (data/diagnosis_truth.csv) against the committed output tables. A `pass` case must
match. A `known_wrong` case must still mismatch (strict xfail) until the sub-plan in its `fixed_by` lands; then the
loop's update_truth step, or the plan, flips it to `pass`. A `ruling_pending` case is not judged."""
from pathlib import Path

import pytest

from delist_detection.diagnosis_truth import (KNOWN_WRONG, RULING_PENDING, LibraryRows, judge_case,
                                              load_diagnosis_truth)
from delist_detection.lifecycle import Tables

ROOT = Path(__file__).resolve().parents[1]
TRUTH = ROOT / "data" / "diagnosis_truth.csv"
if not TRUTH.exists():
    pytest.skip("no data/diagnosis_truth.csv yet (sub-plan 5-0 builds it)", allow_module_level=True)
CASES = load_diagnosis_truth(TRUTH, ROOT / "data" / "diagnosis_truth_legs.csv")


@pytest.fixture(scope="module")
def lib():
    legs = ROOT / "output" / "contract" / "payout_legs.csv"
    rows = None
    if legs.exists():
        import csv
        with legs.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
    return LibraryRows.of(Tables.read(ROOT / "output"), rows)


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_diagnosis_case(case, lib, request):
    if case.status == RULING_PENDING:
        pytest.skip(f"ruling pending: {case.note}")
    if case.status == KNOWN_WRONG:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"known wrong until {case.fixed_by}"))
    j = judge_case(case, lib)
    assert j.ok, "; ".join(map(str, j.mismatches))

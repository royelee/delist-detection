"""The diagnosis truth set (the one data/scorecard.json names) against the committed output tables. A `pass` case must
match. A `known_wrong` case must still mismatch (strict xfail) until the sub-plan in its `fixed_by` lands; then the
loop's update_truth step, or the plan (scripts/scorecard.py --flip), flips it to `pass`. A `ruling_pending` case is
not judged."""
from pathlib import Path

import pytest

from delist_detection.measurement.diagnosis_truth import KNOWN_WRONG, RULING_PENDING, LibraryRows, judge_case
from delist_detection.outputs.run_snapshot import RunSnapshot
from delist_detection.measurement.truth_set import TruthSet, configured

ROOT = Path(__file__).resolve().parents[1]
TRUTH = configured(ROOT)
if not TRUTH.exists():
    pytest.skip("no diagnosis truth file yet (sub-plan 5-0 builds it)", allow_module_level=True)
CASES = TruthSet.open(TRUTH).cases


@pytest.fixture(scope="module")
def lib():
    return LibraryRows.of(RunSnapshot.read(ROOT / "output"))       # a basket case is judged on its legs too


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_diagnosis_case(case, lib, request):
    if case.status == RULING_PENDING:
        pytest.skip(f"ruling pending: {case.note}")
    if case.status == KNOWN_WRONG:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"known wrong until {case.fixed_by}"))
    j = judge_case(case, lib)
    assert j.ok, str(j)

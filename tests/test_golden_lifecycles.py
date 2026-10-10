"""The golden set (data/golden_lifecycles.csv) against the committed output
tables. A `pass` case must hold. A `known_wrong` case must still fail (strict
xfail) until the plan named in its `fixed_by` lands; that plan flips it to
`pass` (scripts/scorecard.py --flip, the flip rule both truth sets share) and
raises the scorecard floor (scripts/scorecard.py --raise-floor)."""
from pathlib import Path

import pytest

from delist_detection.measurement.lifecycle import LifecycleView
from delist_detection.outputs.run_snapshot import RunSnapshot
from delist_detection.measurement.truth import KNOWN_WRONG, judge, load_truth

ROOT = Path(__file__).resolve().parents[1]
CASES = load_truth(ROOT / "data" / "golden_lifecycles.csv")


@pytest.fixture(scope="module")
def view():
    return LifecycleView(RunSnapshot.read(ROOT / "output"))


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_golden_lifecycle(case, view, request):
    if case.status == KNOWN_WRONG:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"known wrong until {case.fixed_by}"))
    j = judge(case, view)
    assert j.ok, str(j)

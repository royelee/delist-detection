"""scripts/apply_5f/5h/5i_truth_rulings.py, their rulings as data over the truth set: each applied to copies of the
committed truth files changes nothing, since every ruling has been applied (a ruling applies once), and a second run
changes nothing either. 5f's rulings, before step 9a, would have undone the wave 2 loop's flips of VMED and MHS to
pass on a rerun; and every rewrite through a raw CSV round trip dropped a cell of the change log's last row."""
import importlib.util
import shutil
from pathlib import Path

import pytest

from delist_detection.measurement.diagnosis_truth import KNOWN_WRONG, PASS
from delist_detection.measurement.truth_set import Ruling, TruthSet, changes_path, configured, legs_path

ROOT = Path(__file__).resolve().parents[1]
TRUTH = configured(ROOT)
FILES = (TRUTH.name, legs_path(TRUTH).name, changes_path(TRUTH).name)


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _copies(tmp_path):
    for name in FILES:
        shutil.copy(TRUTH.parent / name, tmp_path / name)
    return tmp_path / FILES[0]


def _bytes(tmp_path):
    return {name: (tmp_path / name).read_bytes() for name in FILES}


@pytest.mark.parametrize("name, extra, said", [
    ("apply_5f_truth_rulings", [], "no change"),
    ("apply_5h_truth_rulings", [], "0 truth change rows"),
    ("apply_5h_truth_rulings", ["--after-run"], "0 truth change rows"),
    ("apply_5i_truth_rulings", [], "0 truth changes"),
])
def test_a_run_on_the_committed_truth_set_changes_nothing(tmp_path, capsys, name, extra, said):
    truth = _copies(tmp_path)
    committed = {f: (TRUTH.parent / f).read_bytes() for f in FILES}
    argv = ["--truth", str(truth), *extra]
    for _ in range(2):
        assert _script(name).main(argv) == 0
        assert capsys.readouterr().out.strip().endswith(said)
        assert _bytes(tmp_path) == committed


def test_5f_rulings_would_still_apply_to_a_row_they_have_not_reached(tmp_path):
    """The rulings are live data, not a record: on a truth set where a 5f row has not been ruled on, the script
    rules on it (SCS's MIDAS day), with 5f's reason and report, and notes it once."""
    mod = _script("apply_5f_truth_rulings")
    [scs] = [r for r in mod.RULINGS if r.case_id == "BBG000BLBGS2_2025-12-20"]
    truth = TruthSet.open(_copies(tmp_path))
    row = truth.row(scs.case_id)
    fresh = TruthSet.new(tmp_path / "fresh.csv", [{**row, "last_trade_date": "2025-12-08", "fixed_by": "5f",
                                                   "status": KNOWN_WRONG}])
    assert fresh.rule(scs) == 1
    [change] = fresh.changes
    assert (change["field"], change["old"], change["new"], change["report"]) == (
        "last_trade_date", "2025-12-08", "2025-12-09", mod.REPORT)
    assert change["reason"].startswith(f"{mod.WHY}: MIDAS dates the last trade")
    assert fresh.row(scs.case_id)["note"].count(mod.WHY) == row["note"].count(mod.WHY) + 1
    assert fresh.rule(scs) == 0


def test_the_carried_rows_stay_flipped(tmp_path):
    truth = TruthSet.open(_copies(tmp_path))
    mod = _script("apply_5f_truth_rulings")
    for cid in ("BBG000D3MB18_wave1-r1", "BBG000MRMY60_wave1-r1"):
        assert truth.row(cid)["status"] == PASS
        [ruling] = [r for r in mod.RULINGS if r.case_id == cid]
        assert isinstance(ruling, Ruling) and ("status", KNOWN_WRONG) in ruling.cells
        assert truth.rule(ruling) == 0 and truth.row(cid)["status"] == PASS

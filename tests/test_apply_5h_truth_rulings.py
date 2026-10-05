"""scripts/apply_5h_truth_rulings.py is idempotent: a second run (either mode) changes no cell and adds no note."""
import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("apply_5h_truth_rulings", ROOT / "scripts" / "apply_5h_truth_rulings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("diagnosis_truth.csv", "diagnosis_truth_legs.csv", "diagnosis_truth_changes.csv"):
        shutil.copy(ROOT / "data" / name, tmp_path / name)
    monkeypatch.setattr(mod, "TRUTH", tmp_path / "diagnosis_truth.csv")
    monkeypatch.setattr(mod, "LEGS", tmp_path / "diagnosis_truth_legs.csv")
    monkeypatch.setattr(mod, "CHANGES", tmp_path / "diagnosis_truth_changes.csv")
    return mod


def test_a_second_run_adds_no_change_and_no_note(tmp_path, monkeypatch, capsys):
    mod = _script(tmp_path, monkeypatch)
    monkeypatch.setattr(mod.sys, "argv", ["apply_5h_truth_rulings.py"])
    assert mod.main() == 0
    once = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert mod.main() == 0
    assert capsys.readouterr().out.strip().endswith("0 truth change rows")
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == once

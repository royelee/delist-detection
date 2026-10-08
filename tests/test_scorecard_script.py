"""scripts/scorecard.py and scripts/draw_audit_sample.py over small tables in a temp folder."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from delist_detection import store
from delist_detection.loop_round import Unexplained
from delist_detection.truth import load_truth
from delist_detection.truth_set import LEDGER_COLUMNS
from tests.diagnosis_rows import truth_row, write_truth
from tests.lifecycle_tables import contract_row, ending, iv, obs, sec, tables

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scorecard_script, draw_script = _load("scorecard"), _load("draw_audit_sample")


@pytest.fixture
def out(tmp_path):
    t = tables([sec("A"), sec("B"), sec("C")],
               [iv("A", "AAA", "2008-01-02", "2012-03-01"), iv("B", "BBB", "2008-01-02", "2010-05-03"),
                iv("C", "CCC", "2008-01-02")],
               [ending("A", "2012-03-10", ltd="2012-03-01", dlret="0.02"),
                ending("B", "2010-05-10", "exchange_transfer", ltd="2010-05-03", dlret="0.0")],
               [obs("AAA", "2010-06-30", "A"), obs("BBB", "2009-06-30", "B"), obs("CCC", "2010-06-30", "C")])
    out = tmp_path / "output"
    out.mkdir()
    store.write_tables(out, {"securities": t.securities, "ticker_history": t.ticker_history,
                             "delistings": t.delistings, "observation_map": t.observation_map, "review": t.review})
    (out / "run_manifest.json").write_text(json.dumps({"as_of": "2026-09-25"}))
    return out


def _config(tmp_path, floor):
    path = tmp_path / "scorecard.json"
    path.write_text(json.dumps({"window": {"start": "2006-01-02", "end": "2024-12-29"}, "floor": floor}))
    return path


def test_check_passes_on_a_held_floor_and_write_puts_the_card_next_to_the_tables(tmp_path, out, capsys):
    cfg = _config(tmp_path, {"L1.left_view": 1})
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--check", "--write"]) == 0
    card = json.loads((out / "scorecard.json").read_text())
    assert card["as_of"] == "2026-09-25" and card["metrics"]["L1.tickers"] == 3 and card["drops"] == []


def test_check_fails_on_a_drop_and_names_it(tmp_path, out, capsys):
    cfg = _config(tmp_path, {"L1.left_view": 0})
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--check"]) == 1
    assert "DROP L1.left_view: 0 -> 1" in capsys.readouterr().out


def test_raise_floor_keeps_the_rest_of_the_config(tmp_path, out):
    cfg = _config(tmp_path, {"L1.coverage_tickers": 0.5})
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--raise-floor"]) == 0
    raw = json.loads(cfg.read_text())
    assert raw["window"] == {"start": "2006-01-02", "end": "2024-12-29"}
    assert raw["floor"]["L1.coverage_tickers"] == round(2 / 3, 6) and raw["floor"]["L1.left_view"] == 1


def test_lifecycles_writes_one_row_per_ticker_and_per_security(tmp_path, out):
    cfg = _config(tmp_path, {})
    path = tmp_path / "lifecycles.csv"
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--lifecycles", str(path)]) == 0
    lines = path.read_text().splitlines()
    assert lines[0] == ",".join(scorecard_script.LIFECYCLE_COLUMNS) and len(lines) == 1 + 3 + 3
    assert "ticker,BBB,B,left_view,,B,2010-05-10,exchange_transfer" in lines


def test_a_bad_config_exits_2(tmp_path, out, capsys):
    cfg = tmp_path / "scorecard.json"
    cfg.write_text('{"floor": {"nope": 1}}')
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg)]) == 2
    assert "ABORTED" in capsys.readouterr().err


def test_a_manifest_without_as_of_exits_2(tmp_path, out, capsys):
    (out / "run_manifest.json").write_text("{}")
    cfg = tmp_path / "scorecard.json"
    cfg.write_text("{}")
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg)]) == 2
    assert "no as_of" in capsys.readouterr().err


def test_draw_writes_a_pending_worksheet_once(tmp_path, out, capsys):
    cfg = _config(tmp_path, {})
    sheet = tmp_path / "audit.csv"
    argv = ["--output-dir", str(out), "--config", str(cfg), "--out", str(sheet), "--random", "5"]
    assert draw_script.main(argv) == 0
    cases = load_truth(sheet, allow_pending=True)
    assert {c.group for c in cases} == {"census:left_view", "random"} and all(c.pending for c in cases)
    assert draw_script.main(argv) == 2 and "exists" in capsys.readouterr().err


def test_check_fails_on_a_failing_diagnosis_pass_case(tmp_path, out, capsys):
    store.write_tables(out, {"contract_delistings": [contract_row("A", exit_kind="merger", value_rule="cash")]})
    write_truth(tmp_path / "d.csv", [truth_row("A_2012-03-10", "A", exit_kind="exchange")])
    cfg = tmp_path / "scorecard.json"
    cfg.write_text(json.dumps({"diagnosis": "d.csv", "floor": {}}))
    assert scorecard_script.main(["--output-dir", str(out), "--config", str(cfg), "--check"]) == 1
    assert "DIAGNOSIS FAILING A_2012-03-10: exit_kind merger != exchange" in capsys.readouterr().out


def test_base_asks_the_loop_round_for_the_unexplained_count_and_check_fails_unless_it_passes(tmp_path, out, capsys,
                                                                                            monkeypatch):
    """The count and its gate are the loop round's (tests/test_loop_round.py); the script asks it only with --base,
    for the base commit's run, this run, the config's truth cases and the --ledger's rows."""
    write_truth(tmp_path / "truth.csv", [truth_row("A_2010-01-04", "A", exit_kind="merger")])
    cfg = tmp_path / "scorecard.json"
    cfg.write_text(json.dumps({"floor": {}, "diagnosis": "truth.csv"}))
    ledger = tmp_path / "diagnosed.csv"
    ledger.write_text(",".join(LEDGER_COLUMNS) + "\nk,mismatch,A,5a,1,known,\n")
    asked = []
    answers = [Unexplained(({"sec_id": "Z", "table": "delistings", "field": "exit_kind", "kind": "changed",
                             "old": "merger", "new": "exchange"},)), Unexplained(())]

    def unexplained(base, run, cases, ledger_rows):
        asked.append((base, run.as_of.isoformat(), [c.case_id for c in cases], [r["key"] for r in ledger_rows]))
        return answers.pop(0)

    monkeypatch.setattr(scorecard_script, "unexplained", unexplained)
    monkeypatch.setattr(scorecard_script.RunSnapshot, "at", staticmethod(lambda repo, rev, out_dir: f"{rev}@{repo}"))
    argv = ["--output-dir", str(out), "--config", str(cfg), "--repo", str(tmp_path), "--ledger", str(ledger),
            "--check"]
    assert scorecard_script.main(argv) == 0                    # no --base: no regression metric, no check
    assert "D.unexplained_regressions" not in capsys.readouterr().out and asked == []
    assert scorecard_script.main([*argv, "--base", "REV"]) == 1
    assert re.search(r"^D\.unexplained_regressions +1$", capsys.readouterr().out, re.M)
    assert scorecard_script.main([*argv, "--base", "REV"]) == 0
    assert re.search(r"^D\.unexplained_regressions +0$", capsys.readouterr().out, re.M)
    assert asked == [(f"REV@{tmp_path}", "2026-09-25", ["A_2010-01-04"], ["k"])] * 2

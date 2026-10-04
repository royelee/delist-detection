"""regression: the contract diff outside the truth set (spec 1.4)."""
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

from delist_detection import diagnosis_truth as dt
from delist_detection import regression as rg
from delist_detection import store
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row, hist

ROOT = Path(__file__).resolve().parents[1]


def _snap(delistings=(), history=(), ids=()):
    return rg.Snapshot(list(delistings), list(history), list(ids))


def test_a_changed_field_is_one_row_and_the_verdict_column_is_ignored():
    base = _snap([contract_row("A", last_trade_date="2010-09-30", verdict="uncertain")])
    new = _snap([contract_row("A", last_trade_date="2010-10-01", verdict="confirmed")])
    assert rg.diff_contract(base, new) == [{"sec_id": "A", "table": "delistings", "field": "last_trade_date",
                                            "kind": "changed", "old": "2010-09-30", "new": "2010-10-01"}]


def test_added_and_removed_rows_and_ticker_ranges_and_id_changes():
    base = _snap([contract_row("A", exit_kind="merger")], [hist("A", "1", "2008-01-02", "2010-01-01")])
    new = _snap([contract_row("B", exit_kind="exchange")],
                [hist("A", "1", "2008-01-02", "2011-01-01"), hist("B", "2", "2011-01-03")],
                [{"old_sec_id": "CIK9-COMMON", "new_sec_id": "BBGX", "changed_on": "", "issuer_cik": "9",
                  "share_class": "COMMON"}])
    rows = rg.diff_contract(base, new)
    assert [(r["sec_id"], r["table"], r["kind"]) for r in rows] == [
        ("A", "delistings", "removed"), ("B", "delistings", "added"), ("A", "security_history", "changed"),
        ("B", "security_history", "added"), ("CIK9-COMMON", "id_changes", "added")]
    assert rows[2]["old"] == "AAA:2008-01-02..2010-01-01:1" and rows[4]["new"] == "BBGX"


def test_excluded_securities_are_left_out():
    base = _snap([contract_row("A", exit_kind="merger"), contract_row("Z", exit_kind="merger")])
    new = _snap([contract_row("A", exit_kind="exchange"), contract_row("Z", exit_kind="exchange")])
    assert [r["sec_id"] for r in rg.diff_contract(base, new, exclude={"A"})] == ["Z"]


def test_successor_chain_follows_every_table_transitively():
    a = [contract_row("A", successor_sec_id="B")]
    b = [contract_row("B", successor_sec_id="C")]
    assert rg.successor_chain({"A"}, a, b) == {"A", "B", "C"}


def test_excluded_keeps_loop_added_pending_rows_in_the_report():
    cases = dt.parse_rows([truth_row("A_2010-01-04", "A"),
                           truth_row("P_5a-r1", "P", status="ruling_pending", fixed_by="regression")])
    assert rg.excluded(cases, [contract_row("A", successor_sec_id="B")]) == {"A", "B"}


def test_unexplained_counts_rows_not_settled_and_pending_regressions():
    rows = [{"sec_id": "Z", "table": "delistings", "field": "exit_kind", "kind": "changed", "old": "a", "new": "b"},
            {"sec_id": "Y", "table": "security_history", "field": "ranges", "kind": "changed", "old": "x",
             "new": "y"}]
    cases = dt.parse_rows([truth_row("P_5a-r1", "P", status="ruling_pending", fixed_by="regression")])
    left = rg.unexplained(rows, cases, settled={rg.regression_key(rows[1])})
    assert [r["sec_id"] for r in left] == ["Z", "P"]


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def _repo(tmp_path, with_contract=True):
    repo = tmp_path / "repo"
    out = repo / "output"
    out.mkdir(parents=True)
    _git(repo, "init", "-q")
    if with_contract:
        store.write_tables(out, {"contract_delistings": [contract_row("Z", exit_kind="merger")],
                                 "security_history": [hist("Z", "1", "2008-01-02", "2010-01-01")]})
    (out / "keep.txt").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, out


def test_snapshot_at_reads_the_base_commit(tmp_path):
    repo, out = _repo(tmp_path)
    store.write_tables(out, {"contract_delistings": [contract_row("Z", exit_kind="exchange")]})
    base = rg.snapshot_at(repo, "HEAD", out)
    assert base.delistings[0]["exit_kind"] == "merger" and base.id_changes == []
    assert rg.read_snapshot(out).delistings[0]["exit_kind"] == "exchange"


def _script():
    spec = importlib.util.spec_from_file_location("regression_report", ROOT / "scripts" / "regression_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_writes_the_report(tmp_path, capsys):
    repo, out = _repo(tmp_path)
    store.write_tables(out, {"contract_delistings": [contract_row("Z", exit_kind="exchange")]})
    report = tmp_path / "report.csv"
    argv = ["--repo", str(repo), "--base", "HEAD", "--output-dir", str(out), "--truth", str(tmp_path / "none.csv"),
            "--out", str(report)]
    assert _script().main(argv) == 0
    assert "Z,delistings,exit_kind,changed,merger,exchange" in report.read_text()


def test_script_exits_2_when_the_base_lacks_the_contract(tmp_path, capsys):
    repo, out = _repo(tmp_path, with_contract=False)
    store.write_tables(out, {"contract_delistings": [contract_row("Z", exit_kind="exchange")],
                             "security_history": []})
    argv = ["--repo", str(repo), "--base", "HEAD", "--output-dir", str(out), "--truth", str(tmp_path / "none.csv"),
            "--out", str(tmp_path / "r.csv")]
    assert _script().main(argv) == 2
    assert "HEAD:output/contract/delistings.csv" in capsys.readouterr().err

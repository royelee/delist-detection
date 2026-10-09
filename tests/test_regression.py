"""regression: the contract diff outside the truth set (spec 1.4)."""
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

from delist_detection.measurement import diagnosis_truth as dt
from delist_detection.measurement import regression as rg
from delist_detection.outputs import store
from delist_detection.outputs.run_snapshot import RunSnapshot, SnapshotError
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row, hist, sec

ROOT = Path(__file__).resolve().parents[1]


def _snap(delistings=(), history=(), ids=()):
    """A run snapshot of contract rows (the in-memory adapter)."""
    return RunSnapshot.of({"contract_delistings": list(delistings), "security_history": list(history),
                           "id_changes": list(ids)})


def test_a_changed_field_is_one_row_and_the_verdict_column_is_ignored():
    base = _snap([contract_row("A", last_trade_date="2010-09-30", verdict="uncertain")])
    new = _snap([contract_row("A", last_trade_date="2010-10-01", verdict="confirmed")])
    assert rg.diff_contract(base, new) == [{"sec_id": "A", "table": "delistings", "field": "last_trade_date",
                                            "kind": "changed", "old": "2010-09-30", "new": "2010-10-01"}]


def test_columns_that_follow_other_columns_and_prices_are_not_reported():
    old = dict(dlret="0.1", dlret_fill="", terminal_value="11", value_formula="cash", terms_source="regex",
               terms_gate="passed")
    new = dict(dlret="0.2", dlret_fill="assumed_par", terminal_value="12", value_formula="cash+stock",
               terms_source="llm", terms_gate="failed")
    base, now = _snap([contract_row("A", **old)]), _snap([contract_row("A", **new)])
    assert rg.diff_contract(base, now) == []


def test_added_and_removed_rows_and_ticker_ranges_and_id_changes():
    base = _snap([contract_row("A", exit_kind="merger")], [hist("A", "1", "2008-01-02", "2010-01-01")])
    new = _snap([contract_row("B", exit_kind="exchange")],
                [hist("A", "1", "2008-01-02", "2011-01-01"), hist("B", "2", "2011-01-03")],
                [{"old_sec_id": "CIK9-COMMON", "new_sec_id": "BBGX", "changed_on": "", "issuer_cik": "9",
                  "share_class": "COMMON"}])
    rows = rg.diff_contract(base, new)
    assert [(r["sec_id"], r["table"], r["kind"]) for r in rows] == [
        ("A", "delistings", "removed"), ("B", "delistings", "added"), ("A", "security_history", "changed"),
        ("B", "security_history", "added"), ("BBGX", "id_changes", "renamed")]
    assert rows[2]["old"] == "AAA:2008-01-02..2010-01-01:1"
    assert (rows[4]["field"], rows[4]["old"], rows[4]["new"]) == ("sec_id", "CIK9-COMMON", "BBGX")


def _rename(old, new):
    return {"old_sec_id": old, "new_sec_id": new, "changed_on": "", "issuer_cik": "9", "share_class": "COMMON"}


def test_a_folded_placeholder_is_one_renamed_row_under_its_figi():
    """N1 (sub-plan 5a): a placeholder a line folded into a FIGI takes its ending and ranges there. Compared under
    the FIGI it holds now, it is one rename, not its own removed row and the FIGI's changed one."""
    base = _snap([contract_row("CIK9-COMMON", exit_kind="merger", last_trade_date="2014-08-28")],
                 [hist("CIK9-COMMON", "9", "2008-01-02", "2012-07-02", ticker="SLE"),
                  hist("BBGF", "9", "2012-07-03", "2014-08-28", ticker="HSH")])
    new = _snap([contract_row("BBGF", exit_kind="merger", last_trade_date="2014-08-28")],
                [hist("BBGF", "9", "2008-01-02", "2012-07-02", ticker="SLE"),
                 hist("BBGF", "9", "2012-07-03", "2014-08-28", ticker="HSH")])
    rows = rg.diff_contract(base, new, renames=[_rename("CIK9-COMMON", "BBGF")])
    assert rows == [{"sec_id": "BBGF", "table": "id_changes", "field": "sec_id", "kind": "renamed",
                     "old": "CIK9-COMMON", "new": "BBGF"}]


def test_a_folded_placeholder_whose_ending_changed_shows_the_change_under_its_figi():
    base = _snap([contract_row("CIK9-COMMON", exit_kind="exchange", successor_sec_id="BBGF")])
    new = _snap([contract_row("BBGF", exit_kind="merger")])
    rows = rg.diff_contract(base, new, renames=[_rename("CIK9-COMMON", "BBGF")])
    assert [(r["sec_id"], r["table"], r["field"], r["kind"]) for r in rows] == [
        ("BBGF", "delistings", "exit_kind", "changed"), ("BBGF", "delistings", "successor_sec_id", "changed"),
        ("BBGF", "id_changes", "sec_id", "renamed")]


def test_the_figis_own_base_row_wins_over_its_folded_placeholders():
    base = _snap([contract_row("CIK9-COMMON", exit_kind="exchange"), contract_row("BBGF", exit_kind="merger")])
    new = _snap([contract_row("BBGF", exit_kind="merger")])
    assert [r["kind"] for r in rg.diff_contract(base, new, renames=[_rename("CIK9-COMMON", "BBGF")])] == ["renamed"]


def test_a_rename_into_an_excluded_security_is_not_reported():
    base = _snap([contract_row("CIK9-COMMON", exit_kind="exchange")])
    new = _snap([contract_row("BBGF", exit_kind="merger")])
    assert rg.diff_contract(base, new, exclude={"BBGF", "CIK9-COMMON"}, renames=[_rename("CIK9-COMMON", "BBGF")]) == []


def test_renamed_to_follows_a_chain_of_renames():
    assert rg.renamed_to([_rename("CIK9-COMMON", "MID"), _rename("MID", "BBGF")]) == {"CIK9-COMMON": "BBGF",
                                                                                     "MID": "BBGF"}


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


def test_excluded_leaves_out_placeholders_renamed_to_a_truth_security():
    cases = dt.parse_rows([truth_row("A_2010-01-04", "A")])
    ids = [{"old_sec_id": "CIK1-COMMON", "new_sec_id": "MID", "changed_on": "", "issuer_cik": "1",
            "share_class": "COMMON"},
           {"old_sec_id": "MID", "new_sec_id": "A", "changed_on": "", "issuer_cik": "1", "share_class": "COMMON"},
           {"old_sec_id": "CIK2-COMMON", "new_sec_id": "OTHER", "changed_on": "", "issuer_cik": "2",
            "share_class": "COMMON"}]
    assert rg.excluded(cases, id_changes=ids) == {"A", "MID", "CIK1-COMMON"}


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


def test_build_report_diffs_the_base_commit_against_the_folder(tmp_path):
    repo, out = _repo(tmp_path)
    store.write_tables(out, {"contract_delistings": [contract_row("Z", exit_kind="exchange")]})
    rows = rg.build_report(RunSnapshot.at(repo, "HEAD", out), RunSnapshot.read(out), [])
    assert [(r["sec_id"], r["field"], r["old"], r["new"]) for r in rows] == [("Z", "exit_kind", "merger", "exchange")]


def test_a_run_without_the_contract_cannot_be_diffed():
    with pytest.raises(SnapshotError, match="contract/delistings.csv: missing"):
        rg.diff_contract(RunSnapshot.of({"security_history": []}), _snap())


def test_id_changes_since_compares_the_base_commits_securities(tmp_path):
    repo, out = _repo(tmp_path)
    store.write_tables(out, {"securities": [sec("CIK9-COMMON", cik="9", figi_source="placeholder")]})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "placeholder")
    store.write_tables(out, {"securities": [sec("BBGF", cik="9")]})
    found = rg.id_changes_since(RunSnapshot.at(repo, "HEAD", out), RunSnapshot.read(out))
    assert [(r["old_sec_id"], r["new_sec_id"]) for r in found] == [("CIK9-COMMON", "BBGF")]
    # a run that wrote no securities.csv (the base, or this run) gives no computed renames
    assert rg.id_changes_since(RunSnapshot.at(repo, "HEAD~1", out), RunSnapshot.read(out)) == []


def _script():
    spec = importlib.util.spec_from_file_location("regression_report", ROOT / "scripts" / "regression_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_writes_the_report(tmp_path):
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


def test_script_exits_2_when_the_base_history_lacks_a_column(tmp_path, capsys):
    repo, out = _repo(tmp_path, with_contract=False)
    store.write_tables(out, {"contract_delistings": [contract_row("Z")]})
    (out / "contract" / "security_history.csv").write_text("sec_id,ticker,start_date,end_date\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old history")
    store.write_tables(out, {"contract_delistings": [contract_row("Z")], "security_history": []})
    argv = ["--repo", str(repo), "--base", "HEAD", "--output-dir", str(out), "--truth", str(tmp_path / "none.csv"),
            "--out", str(tmp_path / "r.csv")]
    assert _script().main(argv) == 2
    err = capsys.readouterr().err
    assert "issuer_id" in err and "HEAD:output/contract/security_history.csv" in err


def test_a_figi_renamed_to_another_figi_is_one_renamed_row_under_the_new_figi():
    """Sub-plan 5h, rule F (BTU BBG00GBV88T6 to BBG000FW00S1): the id_changes row is not restricted to placeholders."""
    base = _snap([contract_row("BBGOLD", exit_kind="merger", last_trade_date="2016-05-14")])
    new = _snap([contract_row("BBGNEW", exit_kind="merger", last_trade_date="2016-05-14")])
    assert rg.renamed_to([_rename("BBGOLD", "BBGNEW")]) == {"BBGOLD": "BBGNEW"}
    assert [r["kind"] for r in rg.diff_contract(base, new, renames=[_rename("BBGOLD", "BBGNEW")])] == ["renamed"]

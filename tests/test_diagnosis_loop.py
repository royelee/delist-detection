"""diagnosis_loop: error keys, the ledger, case rows and placeholder renames (spec 1.7)."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection import diagnosis_truth as dt
from delist_detection import store
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row, ending, hist, sec, tables

ROOT = Path(__file__).resolve().parents[1]


def _judged(contract):
    cases = dt.parse_rows([truth_row("A_2010-01-04", "A", exit_kind="merger", last_trade_date="2010-01-01")])
    return dt.judge_all(cases, dt.LibraryRows.of(tables([sec("A")], contract_delistings=contract)))


def test_mismatch_key_names_the_case_field_and_both_values():
    [j] = _judged([contract_row("A", exit_kind="exchange", last_trade_date="2010-01-01")])
    assert dl.mismatch_key(j.mismatches[0]) == "mis|A_2010-01-04|exit_kind|merger|exchange"


def test_ledger_round_trip_and_settled_keys(tmp_path):
    path = tmp_path / "loop" / "diagnosed.csv"
    rows = [dict(key="k1", kind="regression", sec_id="Z", label="5a", round="1", outcome="new_right", report="r"),
            dict(key="k2", kind="mismatch", sec_id="A", label="5a", round="1", outcome="pending", report="")]
    dl.write_ledger(path, rows)
    back = dl.read_ledger(path)
    assert back == rows and dl.ledger_keys(back) == {"k1", "k2"} and dl.settled_keys(back) == {"k1"}
    assert dl.read_ledger(tmp_path / "absent.csv") == []


def test_seeding_twice_adds_nothing():
    judged = _judged([contract_row("A", exit_kind="exchange", last_trade_date="2010-01-02")])
    first = dl.seed_rows(judged, set(), "5-0")
    assert [r["outcome"] for r in first] == ["known", "known"]
    assert dl.seed_rows(judged, dl.ledger_keys(first), "5-0") == []


def test_context_collapses_ticker_ranges_and_reads_the_last_real_ending():
    t = tables(delistings=[ending("A", "2010-01-04", ltd="2010-01-01", reason="Merger")],
               security_history=[hist("A", "100", "2008-01-02", "2009-01-01", "OLD"),
                                 hist("A", "100", "2009-01-02", "2010-01-01", "NEW")],
               uncertain=[{"kind": "ending", "ticker": "NEW", "sec_id": "A", "date": "2010-01-04",
                           "reason": "continued_filings_rule", "candidates": ""}])
    c = dl.context(t, "A")
    assert (c["tickers"], c["first_start"], c["last_end"], c["intervals"]) == ("OLD;NEW", "2008-01-02",
                                                                               "2010-01-01", "2")
    assert (c["delist_date"], c["reason"], c["uncertain_reasons"]) == ("2010-01-04", "Merger",
                                                                       "continued_filings_rule")


def test_case_rows_group_errors_by_security_with_json_cells():
    [j] = _judged([contract_row("A", exit_kind="exchange", last_trade_date="2010-01-02")])
    reg = [{"sec_id": "Z", "table": "delistings", "field": "", "kind": "added", "old": "", "new": "exit_kind=merger"}]
    t = tables(security_history=[hist("Z", "9", "2008-01-02", "", "ZZZ")])
    rows = dl.case_rows(list(j.mismatches), reg, t, label="5a", round_no=1, truth_sec={"A_2010-01-04": "A"})
    assert [(r["case_id"], r["mode"], r["truth_case_id"]) for r in rows] == [
        ("A_2010-01-04_5a-r1", "mismatch", "A_2010-01-04"), ("Z_5a-r1", "regression", "")]
    assert json.loads(rows[0]["fields"]) == ["exit_kind", "last_trade_date"]
    assert json.loads(rows[0]["side_a"]) == ["merger", "2010-01-01"]
    assert json.loads(rows[0]["side_b"]) == ["exchange", "2010-01-02"]
    assert json.loads(rows[1]["fields"]) == ["delistings.added"] and rows[1]["ticker"] == "ZZZ"
    assert json.loads(rows[1]["keys"])[0].startswith("reg|Z|delistings||added")


def test_rename_truth_follows_id_changes():
    rows = [truth_row("CIK9-COMMON_2010-01-04", "CIK9-COMMON"), truth_row("B_2010-01-04", "B")]
    ids = [{"old_sec_id": "CIK9-COMMON", "new_sec_id": "BBGX", "changed_on": "2026-10-04", "issuer_cik": "9",
            "share_class": "COMMON"}]
    renamed, changes = dl.rename_truth(rows, ids)
    assert [r["sec_id"] for r in renamed] == ["BBGX", "B"]
    assert renamed[0]["case_id"] == "CIK9-COMMON_2010-01-04"
    assert [(c["case_id"], c["field"], c["old"], c["new"]) for c in changes] == [
        ("CIK9-COMMON_2010-01-04", "sec_id", "CIK9-COMMON", "BBGX")]


def test_two_truth_cases_of_one_security_get_distinct_case_ids():
    cases = dt.parse_rows([truth_row("A_2010-01-04", "A", exit_kind="merger"),
                           truth_row("A_2012-02-03", "A", exit_kind="merger")])
    judged = dt.judge_all(cases, dt.LibraryRows.of(tables(contract_delistings=[
        contract_row("A", exit_kind="exchange")])))
    mism = [m for j in judged for m in j.mismatches]
    rows = dl.case_rows(mism, [], tables(), label="5a", round_no=1,
                        truth_sec={c.case_id: c.sec_id for c in cases})
    assert len({r["case_id"] for r in rows}) == len(rows) == 2


# the round script, end to end on temporary paths
_spec = importlib.util.spec_from_file_location("truth_loop_round", ROOT / "scripts" / "truth_loop_round.py")
round_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(round_script)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def _write_out(out, contract, ids=(), securities=None):
    store.write_tables(out, {"securities": [sec(c["sec_id"]) for c in contract] if securities is None else securities,
                             "ticker_history": [], "delistings": [], "observation_map": [],
                             "contract_delistings": contract,
                             "security_history": [hist("Z", "1", "2008-01-02", "2010-01-01", "ZZZ")],
                             "id_changes": list(ids)})


def _argv(tmp_path, repo, *extra):
    return ["--repo", str(repo), "--output-dir", str(repo / "output"), "--truth", str(tmp_path / "truth.csv"),
            "--legs", str(tmp_path / "legs.csv"), "--changes", str(tmp_path / "changes.csv"),
            "--loop-dir", str(tmp_path / "loop"), *extra]


def test_seed_ledger_twice_adds_nothing(tmp_path, capsys):
    repo = tmp_path / "repo"
    _write_out(repo / "output", [contract_row("A", exit_kind="exchange", last_trade_date="2010-01-02")])
    dt.write_diagnosis_truth(tmp_path / "truth.csv", [truth_row("A_2010-01-04", "A", exit_kind="merger",
                                                                last_trade_date="2010-01-01")])
    argv = _argv(tmp_path, repo, "--label", "5-0", "--seed-ledger")
    assert round_script.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["seeded"] == 2
    assert round_script.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["seeded"] == 0
    ledger = dl.read_ledger(tmp_path / "loop" / "diagnosed.csv")
    assert len(ledger) == 2 and len(dl.ledger_keys(ledger)) == 2 and {r["outcome"] for r in ledger} == {"known"}


def test_a_round_renames_truth_and_reports_a_regression(tmp_path, capsys):
    repo = tmp_path / "repo"
    out = repo / "output"
    out.mkdir(parents=True)
    _git(repo, "init", "-q")
    _write_out(out, [contract_row("Z", exit_kind="merger"), contract_row("CIK9-COMMON", exit_kind="merger")])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    ids = [{"old_sec_id": "CIK9-COMMON", "new_sec_id": "BBGX", "changed_on": "2026-10-04", "issuer_cik": "9",
            "share_class": "COMMON"}]
    _write_out(out, [contract_row("Z", exit_kind="exchange"), contract_row("BBGX", exit_kind="merger")], ids)
    dt.write_diagnosis_truth(tmp_path / "truth.csv",
                             [truth_row("CIK9-COMMON_2010-01-04", "CIK9-COMMON", exit_kind="merger")])
    assert round_script.main(_argv(tmp_path, repo, "--label", "5a", "--base", "HEAD", "--round", "1")) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["mismatches_new"], printed["regressions_new"], printed["renamed"]) == (0, 1, 1)
    # the renamed placeholder (removed row, new id change) belongs to its truth case, so only Z shows
    assert [(c["case_id"], c["mode"]) for c in printed["cases"]] == [("Z_5a-r1", "regression")]
    renamed = dl.read_csv(tmp_path / "truth.csv")
    assert [(r["case_id"], r["sec_id"]) for r in renamed] == [("CIK9-COMMON_2010-01-04", "BBGX")]
    [change] = dl.read_csv(tmp_path / "changes.csv")
    assert (change["case_id"], change["old"], change["new"]) == ("CIK9-COMMON_2010-01-04", "CIK9-COMMON", "BBGX")
    assert Path(printed["path"]) == tmp_path / "loop" / "5a" / "round-1" / "cases.csv"
    cases = dl.read_csv(Path(printed["path"]))
    assert [r["case_id"] for r in cases] == ["Z_5a-r1"]


def test_a_round_renames_through_the_base_commits_securities_when_id_changes_is_empty(tmp_path, capsys):
    # id_changes.csv is not cumulative: this run's is empty, yet the placeholder of the base commit now holds a FIGI.
    repo = tmp_path / "repo"
    out = repo / "output"
    out.mkdir(parents=True)
    _git(repo, "init", "-q")
    _write_out(out, [contract_row("Z", exit_kind="merger")],
               securities=[sec("Z"), sec("CIK9-COMMON", cik="9", figi_source="placeholder")])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _write_out(out, [contract_row("Z", exit_kind="merger")], securities=[sec("Z"), sec("BBGX", cik="9")])
    dt.write_diagnosis_truth(tmp_path / "truth.csv", [truth_row("CIK9-COMMON_2010-01-04", "CIK9-COMMON",
                                                                shape="no_ending")])
    assert round_script.main(_argv(tmp_path, repo, "--label", "5a", "--base", "HEAD", "--round", "1")) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["mismatches_new"], printed["renamed"], printed["cases"]) == (0, 1, [])
    assert [(r["case_id"], r["sec_id"]) for r in dl.read_csv(tmp_path / "truth.csv")] == [
        ("CIK9-COMMON_2010-01-04", "BBGX")]
    [change] = dl.read_csv(tmp_path / "changes.csv")
    assert (change["old"], change["new"]) == ("CIK9-COMMON", "BBGX")

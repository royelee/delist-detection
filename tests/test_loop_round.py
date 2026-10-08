"""loop_round: one round of the diagnosis truth loop at its interface (spec 1.6, 1.7). The tokens and their inverses,
the loop folder, the workflow's agreement with the module, seeding, opening and closing a round in a throwaway git
repository (the base commit) with JSON records, the keys a new truth row settles for every branch of the rules, the
unexplained count, and the two scripts' arguments."""
import csv
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from delist_detection.measurement import diagnosis_truth as dt
from delist_detection.measurement import loop_round as lr
from delist_detection.outputs import store
from delist_detection.measurement.regression import report_row
from delist_detection.outputs.run_snapshot import RunSnapshot
from delist_detection.measurement.truth_set import LEDGER_COLUMNS, Ruling, TruthSet, changes_path, read_ledger
from tests.diagnosis_rows import truth_row, write_truth
from tests.lifecycle_tables import contract_row, ending, hist, sec

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".claude" / "workflows" / "diagnosis-truth-loop.js"


def _csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


class _Repo:
    """A throwaway repository whose output/ holds a run: `commit` makes the base commit, `write` the run after it."""

    def __init__(self, root: Path):
        self.root, self.out = root, root / "output"
        self.out.mkdir(parents=True)
        _git(root, "init", "-q")

    def write(self, contract=(), *, securities=None, delistings=(), history=(), ids=(), uncertain=None):
        tables = {"securities": [sec(c["sec_id"]) for c in contract] if securities is None else securities,
                  "ticker_history": [], "delistings": list(delistings), "observation_map": [],
                  "contract_delistings": list(contract), "security_history": list(history), "id_changes": list(ids)}
        if uncertain is not None:
            tables["uncertain"] = uncertain
        store.write_tables(self.out, tables)

    def commit(self):
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "base")

    def run(self):
        return RunSnapshot.read(self.out)

    def base(self):
        return RunSnapshot.at(self.root, "HEAD", self.out)


@pytest.fixture
def repo(tmp_path):
    return _Repo(tmp_path / "repo")


def _loop(tmp_path, repo):
    return lr.Loop.of(repo.root, tmp_path / "loop")


def _open(tmp_path, repo, label="5a", n=1):
    rnd = _loop(tmp_path, repo).round(label, n)
    return rnd, rnd.open(tmp_path / "truth.csv", repo.run(), repo.base(), report=repo.out / "regression_report.csv")


def _record(case, rights, confidence="verified", upheld=True):
    """A finished record (the diagnose agent's verdicts and the skeptic's verification) for each field of `case`."""
    fields = json.loads(case["fields"])
    return {"case_id": case["case_id"], "sec_id": case["sec_id"], "mode": case["mode"], "confidence": confidence,
            "field_verdicts": [{"field": f, "right": r, "value": "", "missed_filing": ""}
                               for f, r in zip(fields, rights)],
            "verification": {"upheld": upheld, "fields_upheld": [], "fields_refuted": [], "notes": ""}}


def _write_records(rnd, records):
    rnd.records_dir.mkdir(parents=True, exist_ok=True)
    for rec in records:
        (rnd.records_dir / f"{rec['case_id']}.json").write_text(json.dumps(rec))


# -- the tokens -------------------------------------------------------------------------------------------------------
def test_a_mismatch_key_reads_back_as_its_mismatch():
    m = dt.Mismatch("A_2010-01-04", "exit_kind", "merger", "exchange")
    key = lr.mismatch_key(m)
    assert key == "mis|A_2010-01-04|exit_kind|merger|exchange"
    assert lr.parse_key(key) == m and lr.key_kind(key) == lr.MISMATCH
    blank = dt.Mismatch("A_2010-01-04", "ending", "present", "")
    assert lr.parse_key(lr.mismatch_key(blank)) == blank


def test_a_regression_key_reads_back_as_its_report_row():
    row = report_row("Z", "delistings", "", "added", "", "exit_kind=merger;drop_reason=")
    key = lr.regression_key(row)
    assert key == "reg|Z|delistings||added||exit_kind=merger;drop_reason="
    assert lr.parse_key(key) == row and lr.key_kind(key) == lr.REGRESSION


def test_a_key_cannot_hold_a_bar_and_other_text_is_no_key():
    with pytest.raises(ValueError, match="cannot hold"):
        lr.mismatch_key(dt.Mismatch("A_2010-01-04", "price_ticker", "A|B", "A"))
    with pytest.raises(ValueError, match="cannot hold"):
        lr.regression_key(report_row("Z", "security_history", "ranges", "changed", "a|b", "a"))
    for text in ("k1", "mis|A|exit_kind|merger", "reg|Z|delistings", "mix|a|b|c|d", ""):
        with pytest.raises(ValueError, match="not an error key"):
            lr.parse_key(text)


@pytest.mark.parametrize("table, field, kind, name, scored", [
    ("delistings", "exit_kind", "changed", "exit_kind", True),
    ("delistings", "ticker_successor_sec_id", "changed", "ticker_successor_sec_id", False),
    ("delistings", "", "added", "delistings.added", False),
    ("delistings", "", "removed", "delistings.removed", False),
    ("security_history", "ranges", "changed", "security_history.ranges", False),
    ("security_history", "ranges", "added", "security_history.ranges", False),
    ("payout_legs", "legs", "removed", "payout_legs.legs", False),
    ("id_changes", "sec_id", "renamed", "id_changes.sec_id", False),
])
def test_every_regression_field_name_reads_back(table, field, kind, name, scored):
    row = report_row("Z", table, field, kind, "a", "b")
    f = lr.Field.of(row)
    assert f.name == name and lr.parse_field(name) == f and lr.parse_field(name).name == name
    assert (f.table, f.column, f.whole) == (table, field, kind if table == "delistings" and not field else "")
    assert f.scored is scored


def test_a_name_no_regression_has_is_refused():
    for name in ("", "delistings.changed", "leg2.ratio", "truth.status", "security_history."):
        with pytest.raises(ValueError, match="not a regression field"):
            lr.parse_field(name)


@pytest.mark.parametrize("subject, label, n", [
    ("A_2010-01-04", "5a", 1), ("CIK1469372-CLASS-A", "wave1", 3), ("A_2010-01-04", "5-0", 2),
    ("BBG000BB2N27_2014-12-25", "5b-preruling", 12), ("Z", "pilot.2", 0)])
def test_a_case_id_reads_back_as_its_subject_label_and_round(subject, label, n):
    assert lr.parse_case_id(lr.case_id(subject, label, n)) == (subject, label, n)


def test_a_label_a_case_id_could_not_read_back_is_refused(tmp_path):
    for label in ("a_b", "", "-x", ".x", "x|y", "x/y"):
        with pytest.raises(ValueError, match="label"):
            lr.case_id("A", label, 1)
        with pytest.raises(ValueError, match="label"):
            lr.Loop.of(tmp_path).round(label, 1)
    with pytest.raises(ValueError, match="from 1"):
        lr.Loop.of(tmp_path).round("5a", 0)
    with pytest.raises(ValueError):
        lr.case_id("", "5a", 1)
    for text in ("A_2010-01-04", "A_5a-rx", "_5a-r1", "A_5a-r01"):
        with pytest.raises(ValueError, match="not a loop case id"):
            lr.parse_case_id(text)


def test_a_ledger_row_takes_its_kind_from_its_key():
    mis = lr.mismatch_key(dt.Mismatch("A_2010-01-04", "exit_kind", "merger", "exchange"))
    reg = lr.regression_key(report_row("Z", "delistings", "exit_kind", "changed", "merger", "exchange"))
    rows = [lr.ledger_row(k, sec_id="A", label="5a", round_no=2, outcome=lr.TRUTH_RIGHT, report="r.md")
            for k in (mis, reg)]
    assert [(r["kind"], r["round"]) for r in rows] == [(lr.MISMATCH, "2"), (lr.REGRESSION, "2")]
    assert all(tuple(r) == LEDGER_COLUMNS for r in rows)
    with pytest.raises(ValueError, match="outcome"):
        lr.ledger_row(mis, sec_id="A", label="5a", round_no=1, outcome="fine", report="")
    with pytest.raises(ValueError, match="not an error key"):
        lr.ledger_row("k1", sec_id="A", label="5a", round_no=1, outcome=lr.KNOWN, report="")


def test_a_case_row_reads_back_as_its_errors():
    row = {"case_id": "Z_5a-r1", "mode": "regression", "sec_id": "Z", "ticker": "ZZZ", "truth_case_id": "",
           "keys": json.dumps(["k1", "k2"]), "fields": json.dumps(["exit_kind", "security_history.ranges"]),
           "side_a": json.dumps(["merger", "a"]), "side_b": json.dumps(["exchange", "b"]), "delist_date": "2010-01-04"}
    case = lr.RoundCase.of(row)
    assert case.errors == (lr.CaseError("k1", "exit_kind", "merger", "exchange"),
                           lr.CaseError("k2", "security_history.ranges", "a", "b"))
    assert (case.keys, case.fields, case.delist_date) == (("k1", "k2"), ("exit_kind", "security_history.ranges"),
                                                          "2010-01-04")
    with pytest.raises(ValueError, match="mode"):
        lr.RoundCase.of({**row, "mode": "other"})
    with pytest.raises(ValueError, match="one length"):
        lr.RoundCase.of({**row, "side_b": json.dumps(["exchange"])})


# -- the loop folder --------------------------------------------------------------------------------------------------
def test_the_loop_folder_names_the_ledger_and_each_rounds_files(tmp_path):
    loop = lr.Loop.of(tmp_path)
    assert loop.folder == tmp_path / "output" / "diagnose_unknown_report" / "loop"
    assert loop.ledger == loop.folder / "diagnosed.csv"
    rnd = loop.round("5a", 2)
    assert rnd.folder == loop.folder / "5a" / "round-2"
    assert (rnd.cases_file, rnd.records_dir, rnd.reports_dir, rnd.summary_file) == (
        rnd.folder / "cases.csv", rnd.folder / "records", rnd.folder / "reports", rnd.folder / "summary.md")
    assert rnd.report_dir == "output/diagnose_unknown_report/loop/5a/round-2/reports"     # relative to the repo
    outside = lr.Loop.of(tmp_path / "repo", tmp_path / "elsewhere").round("5a", 1)
    assert outside.report_dir == str(tmp_path / "elsewhere" / "5a" / "round-1" / "reports")
    assert rnd.case_id("Z") == "Z_5a-r2"


def test_every_script_names_the_one_ledger():
    assert _load("scorecard").parser().parse_args([]).ledger == lr.Loop.of(ROOT).ledger
    for name in ("truth_loop_round", "update_truth"):
        args = _load(name).parser().parse_args(["--label", "5a", "--round", "1", "--base", "HEAD"])
        assert lr.Loop.of(args.repo, args.loop_dir).ledger == lr.Loop.of(ROOT).ledger


# -- the workflow -----------------------------------------------------------------------------------------------------
def _js():
    return WORKFLOW.read_text(encoding="utf-8")


def _enum(js, name):
    m = re.search(rf"{name}: \{{ type: 'string', enum: \[([^\]]*)\] \}}", js)
    assert m, f"the workflow declares no {name} enum"
    return tuple(re.findall(r"'([^']*)'", m.group(1)))


def test_the_workflow_declares_the_record_vocabulary_the_module_reads():
    js = _js()
    assert _enum(js, "mode") == lr.MODES
    assert _enum(js, "right") == lr.RIGHTS
    assert _enum(js, "confidence") == lr.CONFIDENCES
    verdict = re.search(r"missed_filing: \{ type: 'string' \} \}, required: \[([^\]]*)\]", js)
    assert tuple(re.findall(r"'([^']*)'", verdict.group(1))) == lr.VERDICT_KEYS
    complete = re.search(r'has all of the keys "(\w+)", "(\w+)" and "(\w+)"', js)
    assert complete.groups() == lr.RECORD_KEYS


def test_the_workflow_reads_and_writes_the_rounds_files_where_the_module_does():
    js = _js()
    assert f"`{lr.LOOP_DIR.as_posix()}/${{label}}/round-${{round}}`" in js
    for path in (f"${{dir}}/{lr.CASES_NAME}", f"${{dir}}/{lr.REPORTS_NAME}/${{c.case_id}}.md",
                 f"${{dir}}/{lr.RECORDS_NAME}/${{c.case_id}}.json"):
        assert path in js, path


def test_the_workflows_commands_parse_and_it_reads_only_what_the_open_line_holds(tmp_path):
    js = _js()
    fill = {"${label}": "5a", "${args.base}": "abc123", "${round}": "2", "${dry}": " --dry-run"}

    def argv(script):
        cmd = re.search(rf"scripts/{script}\.py ([^`]*)`", js).group(1)
        for k, v in fill.items():
            cmd = cmd.replace(k, v)
        return cmd.split()

    args = _load("truth_loop_round").parser().parse_args(argv("truth_loop_round"))
    assert (args.label, args.base, args.round, args.seed_ledger) == ("5a", "abc123", 2, False)
    args = _load("update_truth").parser().parse_args(argv("update_truth"))
    assert (args.label, args.round, args.base, args.dry_run) == ("5a", 2, "abc123", True)
    rnd = lr.Loop.of(tmp_path).round("5a", 1)
    line = lr.Opened(rnd, (), (), 0, ({"case_id": "Z_5a-r1", "mode": "regression", "ticker": "Z"},), ()).line()
    assert set(re.findall(r"\blisted\.(\w+)", js)) <= set(line)
    assert set(re.findall(r"\bc\.(\w+)", js)) <= set(line["cases"][0])


# -- seeding ----------------------------------------------------------------------------------------------------------
def test_seeding_records_every_current_mismatch_once(tmp_path, repo):
    repo.write([contract_row("A", exit_kind="exchange", last_trade_date="2010-01-02")])
    write_truth(tmp_path / "truth.csv", [truth_row("A_2010-01-04", "A", exit_kind="merger",
                                                    last_trade_date="2010-01-01")])
    loop = _loop(tmp_path, repo)
    first = loop.seed(tmp_path / "truth.csv", repo.run(), label="5-0")
    assert first.line() == {"label": "5-0", "seeded": 2, "ledger": str(loop.ledger)}
    assert loop.seed(tmp_path / "truth.csv", repo.run(), label="5-0").seeded == 0
    ledger = read_ledger(loop.ledger)
    assert [(r["key"], r["kind"], r["round"], r["outcome"]) for r in ledger] == [
        ("mis|A_2010-01-04|exit_kind|merger|exchange", "mismatch", "0", "known"),
        ("mis|A_2010-01-04|last_trade_date|2010-01-01|2010-01-02", "mismatch", "0", "known")]


# -- opening ----------------------------------------------------------------------------------------------------------
def test_opening_renames_the_truth_writes_the_report_and_lists_the_new_regressions(tmp_path, repo):
    repo.write([contract_row("Z", exit_kind="merger"), contract_row("CIK9-COMMON", exit_kind="merger")],
               history=[hist("Z", "1", "2008-01-02", "2010-01-01", "ZZZ")])
    repo.commit()
    ids = [{"old_sec_id": "CIK9-COMMON", "new_sec_id": "BBGX", "changed_on": "2026-10-04", "issuer_cik": "9",
            "share_class": "COMMON"}]
    repo.write([contract_row("Z", exit_kind="exchange"), contract_row("BBGX", exit_kind="merger")], ids=ids,
               history=[hist("Z", "1", "2008-01-02", "2010-01-01", "ZZZ")])
    write_truth(tmp_path / "truth.csv", [truth_row("CIK9-COMMON_2010-01-04", "CIK9-COMMON", exit_kind="merger")])
    rnd, opened = _open(tmp_path, repo)
    line = opened.line()
    assert (line["mismatches_new"], line["regressions_new"], line["renamed"]) == (0, 1, 1)
    # the renamed placeholder (removed row, new id change) belongs to its truth case, so only Z shows
    assert line["cases"] == [{"case_id": "Z_5a-r1", "mode": "regression", "ticker": "ZZZ"}]
    assert line["path"] == str(tmp_path / "loop" / "5a" / "round-1" / "cases.csv")
    assert [(r["case_id"], r["sec_id"]) for r in TruthSet.open(tmp_path / "truth.csv").rows] == [
        ("CIK9-COMMON_2010-01-04", "BBGX")]
    [change] = _csv(changes_path(tmp_path / "truth.csv"))
    assert (change["case_id"], change["old"], change["new"]) == ("CIK9-COMMON_2010-01-04", "CIK9-COMMON", "BBGX")
    assert _csv(repo.out / "regression_report.csv") == [dict(r) for r in opened.report] == [
        {"sec_id": "Z", "table": "delistings", "field": "exit_kind", "kind": "changed", "old": "merger",
         "new": "exchange"}]
    [case] = rnd.cases()
    assert case.errors == (lr.CaseError("reg|Z|delistings|exit_kind|changed|merger|exchange", "exit_kind", "merger",
                                        "exchange"),)


def test_opening_renames_through_the_base_commits_securities_when_id_changes_is_empty(tmp_path, repo):
    # id_changes.csv is not cumulative: this run's is empty, yet the placeholder of the base commit now holds a FIGI.
    repo.write([contract_row("Z", exit_kind="merger")],
               securities=[sec("Z"), sec("CIK9-COMMON", cik="9", figi_source="placeholder")])
    repo.commit()
    repo.write([contract_row("Z", exit_kind="merger")], securities=[sec("Z"), sec("BBGX", cik="9")])
    write_truth(tmp_path / "truth.csv", [truth_row("CIK9-COMMON_2010-01-04", "CIK9-COMMON", shape="no_ending")])
    _, opened = _open(tmp_path, repo)
    assert (len(opened.mismatches), opened.renamed, opened.cases) == (0, 1, ())
    assert [(r["case_id"], r["sec_id"]) for r in TruthSet.open(tmp_path / "truth.csv").rows] == [
        ("CIK9-COMMON_2010-01-04", "BBGX")]
    [change] = _csv(changes_path(tmp_path / "truth.csv"))
    assert (change["old"], change["new"]) == ("CIK9-COMMON", "BBGX")


def test_opening_lists_only_the_errors_the_ledger_has_not_seen(tmp_path, repo):
    repo.write([contract_row("A", exit_kind="merger"), contract_row("Y", exit_kind="merger"),
                contract_row("Z", exit_kind="merger")])
    repo.commit()
    repo.write([contract_row("A", exit_kind="exchange", value_rule="cash"), contract_row("Y", exit_kind="exchange"),
                contract_row("Z", exit_kind="exchange")])
    write_truth(tmp_path / "truth.csv", [truth_row("A_2010-01-04", "A", exit_kind="merger", value_rule="stock")])
    loop = _loop(tmp_path, repo)
    seen = [lr.mismatch_key(dt.Mismatch("A_2010-01-04", "exit_kind", "merger", "exchange")),
            lr.regression_key(report_row("Y", "delistings", "exit_kind", "changed", "merger", "exchange"))]
    loop.ledger.parent.mkdir(parents=True)
    loop.ledger.write_text(",".join(LEDGER_COLUMNS) + "\n" + "".join(f"{k},x,s,5a,1,known,\n" for k in seen))
    _, opened = _open(tmp_path, repo)
    assert [str(m) for m in opened.mismatches] == ["value_rule cash != stock"]
    assert [r["sec_id"] for r in opened.regressions] == ["Z"]
    assert [c["case_id"] for c in opened.cases] == ["A_2010-01-04_5a-r1", "Z_5a-r1"]


def test_case_rows_are_one_per_case_mismatches_first_with_the_securitys_context(tmp_path, repo):
    repo.write([contract_row("A", exit_kind="merger"), contract_row("Z", exit_kind="merger")],
               history=[hist("Z", "9", "2008-01-02", "", "ZZZ")])
    repo.commit()
    repo.write([contract_row("A", exit_kind="exchange", last_trade_date="2010-01-02"),
                contract_row("Z", exit_kind="exchange")],
               delistings=[ending("A", "2010-01-04", ltd="2010-01-02", reason="Merger")],
               history=[hist("A", "100", "2008-01-02", "2009-01-01", "OLD"),
                        hist("A", "100", "2009-01-02", "2010-01-01", "NEW"),
                        hist("Z", "9", "2008-01-02", "", "ZZZ")],
               uncertain=[{"kind": "ending", "ticker": "NEW", "sec_id": "A", "date": "2010-01-04",
                           "reason": "continued_filings_rule", "candidates": ""}])
    write_truth(tmp_path / "truth.csv", [truth_row("A_2010-01-04", "A", exit_kind="merger",
                                                    last_trade_date="2010-01-01")])
    rnd, opened = _open(tmp_path, repo)
    a, z = opened.cases
    assert [(r["case_id"], r["mode"], r["truth_case_id"]) for r in (a, z)] == [
        ("A_2010-01-04_5a-r1", "mismatch", "A_2010-01-04"), ("Z_5a-r1", "regression", "")]
    assert (json.loads(a["fields"]), json.loads(a["side_a"]), json.loads(a["side_b"])) == (
        ["exit_kind", "last_trade_date"], ["merger", "2010-01-01"], ["exchange", "2010-01-02"])
    assert (a["tickers"], a["first_start"], a["last_end"], a["intervals"], a["ticker"]) == (
        "OLD;NEW", "2008-01-02", "2010-01-01", "2", "NEW")
    assert (a["delist_date"], a["reason"], a["uncertain_reasons"]) == ("2010-01-04", "Merger",
                                                                       "continued_filings_rule")
    assert (json.loads(z["fields"]), z["ticker"], z["last_end"]) == (["exit_kind"], "ZZZ", "")
    # cases.csv reads back as the round's cases, each error under its key
    back = rnd.cases()
    assert [c.case_id for c in back] == ["A_2010-01-04_5a-r1", "Z_5a-r1"]
    assert [lr.parse_key(e.key) for e in back[0].errors] == list(opened.mismatches)
    assert [lr.parse_key(e.key) for e in back[1].errors] == list(opened.regressions)
    assert back[0].delist_date == "2010-01-04" and back[1].delist_date == ""


def test_two_truth_cases_of_one_security_get_distinct_case_ids(tmp_path, repo):
    repo.write([contract_row("A", exit_kind="exchange")])
    repo.commit()
    write_truth(tmp_path / "truth.csv", [truth_row("A_2010-01-04", "A", exit_kind="merger"),
                                         truth_row("A_2012-02-03", "A", exit_kind="merger")])
    _, opened = _open(tmp_path, repo)
    assert [c["case_id"] for c in opened.cases] == ["A_2010-01-04_5a-r1", "A_2012-02-03_5a-r1"]


# -- closing ----------------------------------------------------------------------------------------------------------
def _regressed(tmp_path, repo, base, new, *, securities=None, delistings=()):
    """A base commit holding `base` contract rows, a run holding `new`, an empty truth file; round 1 opened."""
    repo.write(base, securities=securities if securities is not None else [sec(r["sec_id"]) for r in [*base, *new]])
    repo.commit()
    repo.write(new, securities=securities if securities is not None else [sec(r["sec_id"]) for r in [*base, *new]],
               delistings=delistings)
    write_truth(tmp_path / "truth.csv", [])
    return _open(tmp_path, repo)


BASE_Z = contract_row("Z", exit_kind="merger", last_trade_date="2010-09-30", value_rule="cash")
NEW_Z = contract_row("Z", exit_kind="merger", last_trade_date="2010-10-01", value_rule="cash")


def test_closing_dry_writes_nothing_and_closing_commits_the_truth_set_and_the_summary(tmp_path, repo):
    rnd, opened = _regressed(tmp_path, repo, [BASE_Z], [NEW_Z])
    [case] = opened.cases
    _write_records(rnd, [_record(case, ["new"])])
    before = {p: p.read_bytes() for p in (tmp_path / "truth.csv", rnd.loop.ledger) if p.exists()}
    dry = rnd.close(tmp_path / "truth.csv", repo.run(), repo.base(), dry_run=True)
    assert dry.line() == {"label": "5a", "round": 1, "cases": 1, "records": 1, "truth_changes": 1, "ledger_rows": 1,
                          "retry": [], "dry_run": True}
    assert {p: p.read_bytes() for p in before} == before and not rnd.loop.ledger.exists()
    assert not changes_path(tmp_path / "truth.csv").exists() and not rnd.summary_file.exists()
    real = rnd.close(tmp_path / "truth.csv", repo.run(), repo.base())
    assert real.line() == {**dry.line(), "dry_run": False}
    [row] = TruthSet.open(tmp_path / "truth.csv").rows
    assert (row["case_id"], row["status"], row["last_trade_date"], row["exit_kind"], row["report"]) == (
        "Z_5a-r1", "pass", "2010-10-01", "merger", f"{rnd.report_dir}/Z_5a-r1.md")
    assert [r["field"] for r in _csv(changes_path(tmp_path / "truth.csv"))] == ["(row)"]
    assert [(r["key"], r["outcome"]) for r in read_ledger(rnd.loop.ledger)] == [
        ("reg|Z|delistings|last_trade_date|changed|2010-09-30|2010-10-01", "new_right")]
    assert rnd.summary_file.read_text() == real.summary()
    assert real.summary().startswith("# Loop 5a, round 1\n\n- cases: 1, records: 1\n- truth changes: 1\n")


def test_closing_without_cases_csv_is_an_error(tmp_path, repo):
    repo.write([BASE_Z])
    repo.commit()
    write_truth(tmp_path / "truth.csv", [])
    with pytest.raises(ValueError, match="cases.csv: missing"):
        _loop(tmp_path, repo).round("5a", 1).close(tmp_path / "truth.csv", repo.run(), repo.base())


def test_closing_retries_a_case_without_a_finished_record(tmp_path, repo):
    rnd, opened = _regressed(tmp_path, repo, [BASE_Z], [NEW_Z])
    rec = _record(opened.cases[0], ["new"])
    del rec["verification"]
    _write_records(rnd, [rec])
    closed = rnd.close(tmp_path / "truth.csv", repo.run(), repo.base())
    assert (closed.retry, closed.changes, closed.ledger_rows) == (("Z_5a-r1",), (), 0)
    assert "retried next round (no record): ['Z_5a-r1']" in rnd.summary_file.read_text()


def test_closing_adds_no_truth_row_for_a_security_the_run_no_longer_holds(tmp_path, repo):
    rnd, opened = _regressed(tmp_path, repo, [BASE_Z], [NEW_Z])
    _write_records(rnd, [_record(opened.cases[0], ["new"])])
    repo.write([NEW_Z], securities=[sec("Y")])
    closed = rnd.close(tmp_path / "truth.csv", repo.run(), repo.base())
    assert TruthSet.open(tmp_path / "truth.csv").rows == [] and closed.changes == ()
    assert [r["outcome"] for r in read_ledger(rnd.loop.ledger)] == ["new_right"]


def test_closing_flips_a_known_wrong_case_the_run_now_matches(tmp_path, repo):
    repo.write([contract_row("A", exit_kind="merger")])
    repo.commit()
    write_truth(tmp_path / "truth.csv", [truth_row("A_2010-01-04", "A", exit_kind="merger", status="known_wrong",
                                                    fixed_by="5a")])
    rnd, opened = _open(tmp_path, repo)
    assert opened.cases == ()
    closed = rnd.close(tmp_path / "truth.csv", repo.run(), repo.base())
    assert [(c["field"], c["old"], c["new"], c["reason"]) for c in closed.changes] == [
        ("status", "known_wrong", "pass", "the library now matches")]
    assert TruthSet.open(tmp_path / "truth.csv").rows[0]["status"] == "pass"


def test_a_row_the_loop_adds_keeps_the_ending_its_case_examined(tmp_path, repo):
    """The defect fix: a loop-added case's id ends in its round. Its truth row keeps the ending the case examined
    (`examined_delist_date`), so the row ruled ending_moved later refuses that ending (CRC 2016 in the real set)."""
    new = contract_row("Z", exit_kind="exchange", continuation="true", value_rule="continuation")
    rnd, opened = _regressed(tmp_path, repo, [], [new], delistings=[ending("Z", "2016-06-01", "exchange_transfer")])
    [case] = opened.cases
    assert case["delist_date"] == "2016-06-01"
    _write_records(rnd, [_record(case, ["new"])])
    rnd.close(tmp_path / "truth.csv", repo.run(), repo.base())
    truth = TruthSet.open(tmp_path / "truth.csv")
    assert truth.row("Z_5a-r1")["examined_delist_date"] == "2016-06-01"
    truth.rule(Ruling("Z_5a-r1", (("shape", "ending_moved"),), "the 2016 event is no ending", tag="t"))
    [judged] = dt.judge_all(truth.cases, dt.LibraryRows.of(repo.run()))
    assert [(m.field, m.library) for m in judged.mismatches] == [("shape", "ending 2016-06-01")]


# -- the keys a new truth row settles: the judge's, for every branch of the rules ------------------------------------
MOVED_Z = contract_row("Z", exit_kind="exchange", last_trade_date="2010-10-01", value_rule="cash")
BRANCHES = {          # base and run contract rows, the case's fields (contract column order), the verdicts
    "a scored field found old": ([BASE_Z], [NEW_Z], ["last_trade_date"], ["old"]),
    "two scored fields found old, in the case's order": (
        [BASE_Z], [MOVED_Z], ["last_trade_date", "exit_kind"], ["old", "old"]),
    "one scored field new, one old": ([BASE_Z], [MOVED_Z], ["last_trade_date", "exit_kind"], ["new", "old"]),
    "an added row found old": ([], [NEW_Z], ["delistings.added"], ["old"]),
    "a removed row found old": ([BASE_Z], [], ["delistings.removed"], ["old"]),
    "every field new": ([BASE_Z], [NEW_Z], ["last_trade_date"], ["new"]),
    "an added row found new": ([], [NEW_Z], ["delistings.added"], ["new"]),
    "a removed row found new": ([BASE_Z], [], ["delistings.removed"], ["new"]),
}


@pytest.mark.parametrize("branch", BRANCHES)
def test_the_keys_a_new_truth_row_settles_are_the_ones_the_next_round_judges(tmp_path, repo, branch):
    base, new, fields, rights = BRANCHES[branch]
    rnd, opened = _regressed(tmp_path, repo, base, new, securities=[sec("Z")])
    [case] = opened.cases
    assert json.loads(case["fields"]) == fields
    _write_records(rnd, [_record(case, rights)])
    rnd.close(tmp_path / "truth.csv", repo.run(), repo.base())
    [row] = TruthSet.open(tmp_path / "truth.csv").cases
    judged = [lr.mismatch_key(m) for j in dt.judge_all([row], dt.LibraryRows.of(repo.run())) for m in j.mismatches]
    settled = [r["key"] for r in read_ledger(rnd.loop.ledger) if r["outcome"] == lr.TRUTH_RIGHT]
    assert sorted(settled) == sorted(judged) and len(settled) == rights.count("old")
    named = [k for k in settled if lr.parse_key(k).field in fields]
    assert named == sorted(named, key=lambda k: fields.index(lr.parse_key(k).field))
    # the next round lists nothing of it: its keys are settled, and the security is in the truth set
    _, again = _open(tmp_path, repo, n=2)
    assert again.cases == ()


# -- the unexplained count --------------------------------------------------------------------------------------------
def test_unexplained_counts_the_regressions_the_ledger_has_not_settled_and_the_pending_rows(tmp_path, repo):
    repo.write([contract_row("A", exit_kind="merger"), contract_row("Y", exit_kind="merger"),
                contract_row("Z", exit_kind="merger")])
    repo.commit()
    repo.write([contract_row("A", exit_kind="exchange"), contract_row("Y", exit_kind="exchange"),
                contract_row("Z", exit_kind="exchange")])
    # a stale written report (an empty one) never decides the count: the report is recomputed
    (repo.out / "regression_report.csv").write_text("sec_id,table,field,kind,old,new\n")
    cases = dt.parse_rows([truth_row("A_2010-01-04", "A", exit_kind="exchange"),
                           truth_row("P_5a-r1", "P", status="ruling_pending", fixed_by="regression")])
    y, z = (lr.regression_key(report_row(s, "delistings", "exit_kind", "changed", "merger", "exchange"))
            for s in ("Y", "Z"))
    ledger = [lr.ledger_row(y, sec_id="Y", label="5a", round_no=1, outcome=lr.NEW_RIGHT, report=""),
              lr.ledger_row(z, sec_id="Z", label="5a", round_no=1, outcome=lr.OLD_RIGHT, report="")]
    left = lr.unexplained(repo.base(), repo.run(), cases, ledger)
    assert [(r["sec_id"], r["table"]) for r in left.rows] == [("Z", "delistings"), ("P", "truth")]
    assert (left.count, left.passes, left.line()) == (2, False, {"D.unexplained_regressions": 2})
    settled = [*ledger, lr.ledger_row(z, sec_id="Z", label="5a", round_no=2, outcome=lr.NEW_RIGHT, report="")]
    none = lr.unexplained(repo.base(), repo.run(), cases[:1], settled)
    assert (none.rows, none.count, none.passes, none.line()) == ((), 0, True, {lr.UNEXPLAINED: 0})


# -- the scripts: argparse over the module ----------------------------------------------------------------------------
def _answer(line):
    return SimpleNamespace(line=lambda: line)


def test_the_round_script_opens_a_round_or_seeds_through_the_module(tmp_path, repo, monkeypatch, capsys):
    repo.write([BASE_Z])
    repo.commit()
    calls = []

    def open_(self, truth, run, base, *, report):
        calls.append(("open", self.label, self.number, self.loop, Path(truth), Path(report)))
        return _answer({"opened": True})

    def seed(self, truth, run, *, label):
        calls.append(("seed", label, self, Path(truth)))
        return _answer({"seeded": 0})

    monkeypatch.setattr(lr.Round, "open", open_)
    monkeypatch.setattr(lr.Loop, "seed", seed)
    script = _load("truth_loop_round")
    common = ["--repo", str(repo.root), "--output-dir", str(repo.out), "--truth", str(tmp_path / "t.csv"),
              "--loop-dir", str(tmp_path / "loop")]
    loop = lr.Loop(tmp_path / "loop", repo.root)
    assert script.main([*common, "--label", "5a", "--base", "HEAD", "--round", "2"]) == 0
    assert json.loads(capsys.readouterr().out) == {"opened": True}
    assert script.main([*common, "--label", "5-0", "--seed-ledger"]) == 0
    assert json.loads(capsys.readouterr().out) == {"seeded": 0}
    assert calls == [("open", "5a", 2, loop, tmp_path / "t.csv", repo.out / "regression_report.csv"),
                     ("seed", "5-0", loop, tmp_path / "t.csv")]
    with pytest.raises(SystemExit):
        script.main([*common, "--label", "5a"])                     # a round needs --base
    assert "--base is required" in capsys.readouterr().err
    assert script.main([*common, "--label", "a_b", "--base", "HEAD"]) == 2
    assert "ABORTED: label 'a_b'" in capsys.readouterr().err


def test_the_update_script_closes_a_round_through_the_module(tmp_path, repo, monkeypatch, capsys):
    repo.write([BASE_Z])
    repo.commit()
    calls = []

    def close(self, truth, run, base, *, dry_run=False):
        calls.append((self.label, self.number, self.loop, Path(truth), dry_run))
        if self.label == "bad":
            raise ValueError("cases.csv: missing")
        return _answer({"closed": dry_run})

    monkeypatch.setattr(lr.Round, "close", close)
    script = _load("update_truth")
    common = ["--repo", str(repo.root), "--output-dir", str(repo.out), "--truth", str(tmp_path / "t.csv"),
              "--loop-dir", str(tmp_path / "loop"), "--round", "1", "--base", "HEAD"]
    assert script.main([*common, "--label", "5a", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out) == {"closed": True}
    assert script.main([*common, "--label", "5a"]) == 0
    assert json.loads(capsys.readouterr().out) == {"closed": False}
    loop = lr.Loop(tmp_path / "loop", repo.root)
    assert calls == [("5a", 1, loop, tmp_path / "t.csv", True), ("5a", 1, loop, tmp_path / "t.csv", False)]
    assert script.main([*common, "--label", "bad"]) == 2
    assert "ABORTED: cases.csv: missing" in capsys.readouterr().err

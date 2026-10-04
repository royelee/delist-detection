"""diagnosis_loop: error keys, the ledger, case rows and placeholder renames (spec 1.7)."""
import json

from delist_detection import diagnosis_loop as dl
from delist_detection import diagnosis_truth as dt
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row, ending, hist, tables


def _judged(contract):
    cases = dt.parse_rows([truth_row("A_2010-01-04", "A", exit_kind="merger", last_trade_date="2010-01-01")])
    return dt.judge_all(cases, dt.LibraryRows.of(tables(contract_delistings=contract)))


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
        ("A_5a-r1", "mismatch", "A_2010-01-04"), ("Z_5a-r1", "regression", "")]
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

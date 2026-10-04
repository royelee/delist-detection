"""truth_update: what a round's diagnoses may change in the truth file (spec 1.6)."""
import json

from delist_detection import truth_update as tu
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row


def _case(case_id, mode, sec, fields, a, b, truth_case_id="", keys=None):
    return {"case_id": case_id, "mode": mode, "sec_id": sec, "ticker": sec, "truth_case_id": truth_case_id,
            "keys": json.dumps(keys or [f"k-{case_id}-{f}" for f in fields]), "fields": json.dumps(fields),
            "side_a": json.dumps(a), "side_b": json.dumps(b)}


def _record(verdicts, confidence="verified", upheld=True, refuted=()):
    return {"confidence": confidence, "field_verdicts": verdicts,
            "verification": {"upheld": upheld, "fields_refuted": list(refuted), "fields_upheld": [], "notes": ""}}


def _apply(cases, records, truth=(), base=None, new=None, keys=frozenset()):
    return tu.apply_round(cases, records, list(truth), base or {}, new or {}, label="5a", round_no=1,
                          report_dir="loop/5a/round-1/reports", ledger_keys=keys)


BASE = {"Z": contract_row("Z", exit_kind="merger", last_trade_date="2010-09-30", value_rule="cash")}
NEW = {"Z": contract_row("Z", exit_kind="merger", last_trade_date="2010-10-01", value_rule="cash")}
REG = _case("Z_5a-r1", "regression", "Z", ["last_trade_date"], ["2010-09-30"], ["2010-10-01"])


def test_a_verified_upheld_new_value_enters_the_truth_as_pass():
    res = _apply([REG], {"Z_5a-r1": _record([{"field": "last_trade_date", "right": "new", "value": "2010-10-01",
                                               "missed_filing": ""}])}, base=BASE, new=NEW)
    [row] = res.truth_rows
    assert (row["case_id"], row["status"], row["last_trade_date"], row["exit_kind"]) == (
        "Z_5a-r1", "pass", "2010-10-01", "merger")
    assert [r["outcome"] for r in res.ledger_rows] == ["new_right"] and res.changes[0]["field"] == "(row)"


def test_an_old_value_enters_as_known_wrong_for_the_sub_plan():
    res = _apply([REG], {"Z_5a-r1": _record([{"field": "last_trade_date", "right": "old", "value": "2010-09-30",
                                               "missed_filing": ""}])}, base=BASE, new=NEW)
    [row] = res.truth_rows
    assert (row["status"], row["fixed_by"], row["last_trade_date"]) == ("known_wrong", "5a", "2010-09-30")
    assert [r["outcome"] for r in res.ledger_rows] == ["old_right"]


def test_an_unverified_or_refuted_regression_is_ruling_pending():
    for rec in (_record([{"field": "last_trade_date", "right": "new", "value": "", "missed_filing": ""}],
                        confidence="inferred"),
                _record([{"field": "last_trade_date", "right": "new", "value": "", "missed_filing": ""}],
                        upheld=False, refuted=[{"field": "last_trade_date", "why": "x"}])):
        res = _apply([REG], {"Z_5a-r1": rec}, base=BASE, new=NEW)
        [row] = res.truth_rows
        assert (row["status"], row["fixed_by"], row["exit_kind"]) == ("ruling_pending", "regression", "*")
        assert [r["outcome"] for r in res.ledger_rows] == ["pending"]


def test_a_new_contract_row_the_diagnosis_rejects_becomes_no_ending():
    case = _case("N_5a-r1", "regression", "N", ["delistings.added"], [""], ["exit_kind=exchange"])
    res = _apply([case], {"N_5a-r1": _record([{"field": "delistings.added", "right": "old", "value": "",
                                               "missed_filing": ""}])},
                 new={"N": contract_row("N", exit_kind="exchange")})
    assert (res.truth_rows[0]["shape"], res.truth_rows[0]["status"]) == ("no_ending", "known_wrong")


def test_a_ticker_range_change_enters_only_the_ledger():
    case = _case("Y_5a-r1", "regression", "Y", ["security_history.ranges"], ["a"], ["b"])
    res = _apply([case], {"Y_5a-r1": _record([{"field": "security_history.ranges", "right": "new", "value": "b",
                                               "missed_filing": ""}])})
    assert res.truth_rows == [] and [r["outcome"] for r in res.ledger_rows] == ["new_right"]


def test_a_mismatch_changes_the_truth_only_with_a_missed_filing():
    truth = [truth_row("A_2010-01-04", "A", status="known_wrong", fixed_by="5d", last_trade_date="2010-01-01")]
    case = _case("A_5a-r1", "mismatch", "A", ["last_trade_date"], ["2010-01-01"], ["2010-01-02"],
                 truth_case_id="A_2010-01-04")
    without = _apply([case], {"A_5a-r1": _record([{"field": "last_trade_date", "right": "library",
                                                   "value": "2010-01-02", "missed_filing": ""}])}, truth)
    assert without.truth_rows[0]["last_trade_date"] == "2010-01-01" and without.changes == []
    assert [r["outcome"] for r in without.ledger_rows] == ["pending"]
    cited = _apply([case], {"A_5a-r1": _record([{"field": "last_trade_date", "right": "library",
                                                 "value": "2010-01-02", "missed_filing": "0001193125-10-222185"}])},
                   truth)
    assert cited.truth_rows[0]["last_trade_date"] == "2010-01-02"
    assert cited.changes[0]["reason"].endswith("cites 0001193125-10-222185")
    assert [r["outcome"] for r in cited.ledger_rows] == ["library_right"]


def test_a_mismatch_the_diagnosis_upholds_keeps_the_truth():
    truth = [truth_row("A_2010-01-04", "A", last_trade_date="2010-01-01")]
    case = _case("A_5a-r1", "mismatch", "A", ["last_trade_date"], ["2010-01-01"], ["2010-01-02"],
                 truth_case_id="A_2010-01-04")
    res = _apply([case], {"A_5a-r1": _record([{"field": "last_trade_date", "right": "truth", "value": "2010-01-01",
                                               "missed_filing": ""}])}, truth)
    assert res.changes == [] and [r["outcome"] for r in res.ledger_rows] == ["truth_right"]


def test_a_case_with_no_record_changes_nothing_and_is_retried():
    res = _apply([REG], {}, base=BASE, new=NEW)
    assert res.truth_rows == [] and res.ledger_rows == [] and res.pending == ["Z_5a-r1"]


def test_rerunning_a_round_skips_settled_keys():
    rec = {"Z_5a-r1": _record([{"field": "last_trade_date", "right": "new", "value": "", "missed_filing": ""}])}
    first = _apply([REG], rec, base=BASE, new=NEW)
    again = _apply([REG], rec, truth=first.truth_rows, base=BASE, new=NEW,
                   keys={r["key"] for r in first.ledger_rows})
    assert again.truth_rows == first.truth_rows and again.changes == [] and again.ledger_rows == []


def test_flip_statuses_turns_matching_known_wrong_cases_into_pass():
    rows = [truth_row("A_2010-01-04", "A", status="known_wrong", fixed_by="5a"),
            truth_row("B_2010-01-04", "B", status="known_wrong", fixed_by="5a")]
    changes = tu.flip_statuses(rows, {"A_2010-01-04"})
    assert [(r["status"], r["fixed_by"]) for r in rows] == [("pass", ""), ("known_wrong", "5a")]
    assert [(c["case_id"], c["old"], c["new"]) for c in changes] == [("A_2010-01-04", "known_wrong", "pass")]

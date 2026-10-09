"""truth_update: what a round's diagnoses may change in the truth file (spec 1.6), applied through the truth set
(`TruthSet.apply_round`) to a round's cases (`loop_round.RoundCase`). A round opened and closed end to end is
tests/test_loop_round.py's."""
import tempfile
from pathlib import Path

import pytest

from delist_detection.measurement import diagnosis_truth as dt
from delist_detection.measurement.loop_round import CaseError, RoundCase, mismatch_key, parse_field, regression_key
from delist_detection.measurement.regression import report_row
from delist_detection.measurement.truth_set import TruthSet
from tests.diagnosis_rows import ledger_row, truth_row
from tests.lifecycle_tables import contract_row


def _key(mode, sec, truth_case_id, field, a, b):
    """The key the loop round gives the error: a mismatch's, or the report row's the field names."""
    if mode == "mismatch":
        return mismatch_key(dt.Mismatch(truth_case_id, field, a, b))
    f = parse_field(field)
    return regression_key(report_row(sec, f.table, f.column, f.whole or "changed", a, b))


def _case(case_id, mode, sec, fields, a, b, truth_case_id="", delist_date=""):
    keys = [_key(mode, sec, truth_case_id, f, x, y) for f, x, y in zip(fields, a, b)]
    return RoundCase(case_id, mode, sec, sec, truth_case_id, tuple(CaseError(*e) for e in zip(keys, fields, a, b)),
                     delist_date)


def _record(verdicts, confidence="verified", upheld=True, refuted=()):
    return {"confidence": confidence, "field_verdicts": verdicts,
            "verification": {"upheld": upheld, "fields_refuted": list(refuted), "fields_upheld": [], "notes": ""}}


def _apply(cases, records, truth=(), base=None, new=None, keys=frozenset(), run_sec_ids=None, **kw):
    """The round applied to a truth set holding `truth` and a ledger holding `keys` (never committed), against a run
    whose contract rows are `new` and whose securities are `run_sec_ids` (default: every security named)."""
    secs = run_sec_ids if run_sec_ids is not None else {c.sec_id for c in cases} | set(new or {}) | set(base or {})
    with tempfile.TemporaryDirectory() as d:
        ts = TruthSet.new(Path(d) / "truth.csv", list(truth), ledger=Path(d) / "diagnosed.csv")
        ts.settle([ledger_row(k) for k in keys])
        return ts.apply_round(cases, records, base or {}, dt.LibraryRows(new or {}, {}, frozenset(secs)),
                              label="5a", round_no=1, report_dir="loop/5a/round-1/reports", **kw)


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


NEW_RIGHT = _record([{"field": "last_trade_date", "right": "new", "value": "2010-10-01", "missed_filing": ""}])


def test_a_regression_of_a_security_the_run_no_longer_holds_adds_no_truth_row():
    """N1 (sub-plan 5a): a truth row under a sec_id the run lacks could only be judged a sec_id mismatch."""
    res = _apply([REG], {"Z_5a-r1": NEW_RIGHT}, base=BASE, new=NEW, run_sec_ids={"Y"})
    assert res.truth_rows == [] and res.changes == []
    assert [(r["key"], r["outcome"]) for r in res.ledger_rows] == [(REG.keys[0], "new_right")]


def test_a_regression_of_a_renamed_placeholder_adds_no_truth_row():
    res = _apply([REG], {"Z_5a-r1": NEW_RIGHT}, base=BASE, new=NEW, run_sec_ids={"Z"}, renamed={"Z"})
    assert res.truth_rows == [] and [r["outcome"] for r in res.ledger_rows] == ["new_right"]


def test_a_new_row_keeps_the_ending_its_case_examined():
    case = _case("Z_5a-r1", "regression", "Z", ["last_trade_date"], ["2010-09-30"], ["2010-10-01"],
                 delist_date="2010-10-04")
    added = _apply([case], {"Z_5a-r1": NEW_RIGHT}, base=BASE, new=NEW)
    pending = _apply([case], {"Z_5a-r1": _record([{"field": "last_trade_date", "right": "new", "value": "",
                                                    "missed_filing": ""}], confidence="inferred")}, base=BASE, new=NEW)
    assert [r.truth_rows[0]["examined_delist_date"] for r in (added, pending)] == ["2010-10-04", "2010-10-04"]
    assert pending.truth_rows[0]["status"] == "ruling_pending"


def test_an_old_value_enters_as_known_wrong_for_the_sub_plan():
    res = _apply([REG], {"Z_5a-r1": _record([{"field": "last_trade_date", "right": "old", "value": "2010-09-30",
                                               "missed_filing": ""}])}, base=BASE, new=NEW)
    [row] = res.truth_rows
    assert (row["status"], row["fixed_by"], row["last_trade_date"]) == ("known_wrong", "5a", "2010-09-30")
    assert [r["outcome"] for r in res.ledger_rows] == ["old_right", "truth_right"]      # the second: the mismatch


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


def test_a_truth_row_takes_the_base_value_for_a_field_the_case_does_not_hold():
    new = {"Z": contract_row("Z", exit_kind="exchange", last_trade_date="2010-10-01", value_rule="cash")}
    res = _apply([REG], {"Z_5a-r1": _record([{"field": "last_trade_date", "right": "new", "value": "2010-10-01",
                                               "missed_filing": ""}])}, base=BASE, new=new)
    [row] = res.truth_rows
    assert (row["exit_kind"], row["last_trade_date"]) == ("merger", "2010-10-01")


def test_a_mixed_case_is_pass_when_the_truth_touching_fields_are_all_new():
    case = _case("N_5a-r1", "regression", "N", ["delistings.added", "security_history.ranges"],
                 ["", "a"], ["exit_kind=merger", "b"])
    verdicts = [{"field": "delistings.added", "right": "new", "value": "", "missed_filing": ""},
                {"field": "security_history.ranges", "right": "old", "value": "a", "missed_filing": ""}]
    res = _apply([case], {"N_5a-r1": _record(verdicts)}, new={"N": contract_row("N", exit_kind="merger")})
    [row] = res.truth_rows
    assert (row["status"], row["fixed_by"], row["exit_kind"]) == ("pass", "", "merger")
    assert sorted(r["outcome"] for r in res.ledger_rows) == ["new_right", "old_right"]


def test_a_mismatch_naming_an_absent_truth_case_is_an_error():
    case = _case("A_5a-r1", "mismatch", "A", ["last_trade_date"], ["x"], ["y"], truth_case_id="A_gone")
    with pytest.raises(ValueError, match="A_5a-r1.*A_gone"):
        _apply([case], {"A_5a-r1": _record([])})


def _verdict(field, right, value="", missed=""):
    return {"field": field, "right": right, "value": value, "missed_filing": missed}


def test_an_added_row_scores_only_the_fields_the_agent_saw():
    case = _case("N_5a-r1", "regression", "N", ["delistings.added"], [""], ["exit_kind=merger"])
    new = {"N": contract_row("N", exit_kind="merger", value_rule="cash", cash_per_share="99.000000",
                             cash_currency="USD", price_ticker="ACQ")}
    res = _apply([case], {"N_5a-r1": _record([_verdict("delistings.added", "new")])}, new=new)
    [row] = res.truth_rows
    assert (row["exit_kind"], row["value_rule"], row["status"]) == ("merger", "cash", "pass")
    assert (row["cash_per_share"], row["cash_currency"], row["price_ticker"], row["stock_ratio"]) == ("*",) * 4
    assert row["drop_reason"] == "" and row["continuation"] == ""       # a brief field, blank as the agent saw it


def test_a_removed_row_found_old_scores_only_the_brief_and_expects_the_row_back():
    case = _case("R_5a-r1", "regression", "R", ["delistings.removed"], ["exit_kind=merger"], [""])
    base = {"R": contract_row("R", exit_kind="merger", cash_per_share="12.000000")}
    res = _apply([case], {"R_5a-r1": _record([_verdict("delistings.removed", "old")])}, base=base)
    [row] = res.truth_rows
    assert (row["shape"], row["status"], row["exit_kind"], row["cash_per_share"]) == ("ending", "known_wrong", "merger",
                                                                                      "*")
    assert "mis|R_5a-r1|ending|present|(no contract row)" in {r["key"] for r in res.ledger_rows}


def test_an_old_right_regression_settles_the_mismatches_it_makes_for_the_new_truth_row():
    res = _apply([REG], {"Z_5a-r1": _record([_verdict("last_trade_date", "old", "2010-09-30")])}, base=BASE, new=NEW)
    by = {r["key"]: r for r in res.ledger_rows}
    assert by["mis|Z_5a-r1|last_trade_date|2010-09-30|2010-10-01"]["outcome"] == "truth_right"
    assert by["mis|Z_5a-r1|last_trade_date|2010-09-30|2010-10-01"]["kind"] == "mismatch"
    # and the judge reports exactly that key for the new truth row
    [row] = res.truth_rows
    case = dt.parse_rows([row])[0]
    lib = dt.LibraryRows(NEW, {}, {"Z"})
    assert [mismatch_key(m) for m in dt.judge_case(case, lib).mismatches] == [
        "mis|Z_5a-r1|last_trade_date|2010-09-30|2010-10-01"]
    again = _apply([REG], {"Z_5a-r1": _record([_verdict("last_trade_date", "old")])}, base=BASE, new=NEW,
                   keys={r["key"] for r in res.ledger_rows})
    assert again.ledger_rows == [] and again.truth_rows == []


def test_a_verdict_on_a_field_the_truth_does_not_score_leaves_the_row_decided_by_the_scored_one():
    case = _case("Z_5a-r1", "regression", "Z", ["last_trade_date", "ticker_successor_sec_id"],
                 ["2010-09-30", ""], ["2010-10-01", "Y"])
    rec = _record([_verdict("last_trade_date", "new"), _verdict("ticker_successor_sec_id", "neither")])
    res = _apply([case], {"Z_5a-r1": rec}, base=BASE, new=NEW)
    [row] = res.truth_rows
    assert (row["status"], row["last_trade_date"]) == ("pass", "2010-10-01")
    assert [(r["key"], r["outcome"]) for r in res.ledger_rows] == [(case.keys[0], "new_right"),
                                                                   (case.keys[1], "pending")]


def test_a_missed_filing_must_be_an_accession_number():
    truth = [truth_row("A_2010-01-04", "A", status="known_wrong", fixed_by="5d", last_trade_date="2010-01-01")]
    case = _case("A_5a-r1", "mismatch", "A", ["last_trade_date"], ["2010-01-01"], ["2010-01-02"],
                 truth_case_id="A_2010-01-04")
    for text in ("none", "N/A", "see report", "0001193125-10-22218"):
        res = _apply([case], {"A_5a-r1": _record([_verdict("last_trade_date", "library", "2010-01-02", text)])}, truth)
        assert res.truth_rows[0]["last_trade_date"] == "2010-01-01" and res.changes == []
        assert [r["outcome"] for r in res.ledger_rows] == ["pending"]


def test_a_record_the_agents_did_not_finish_is_retried():
    done = _record([_verdict("last_trade_date", "new")])
    no_verification = {k: v for k, v in done.items() if k != "verification"}
    no_verdicts = {k: v for k, v in done.items() if k != "field_verdicts"}
    no_confidence = {k: v for k, v in done.items() if k != "confidence"}
    for rec in (no_verification, no_verdicts, no_confidence, [], "oops"):
        res = _apply([REG], {"Z_5a-r1": rec}, base=BASE, new=NEW)
        assert res.truth_rows == [] and res.ledger_rows == [] and res.changes == []
        assert res.pending == ["Z_5a-r1"]


def test_a_cited_library_value_rewrites_the_internal_last_trade_date():
    truth = [truth_row("A_2010-01-04", "A", internal_last_trade_date="2009-12-30")]
    case = _case("A_5a-r1", "mismatch", "A", ["internal_last_trade_date"], ["2009-12-30"], ["2009-12-31"],
                 truth_case_id="A_2010-01-04")
    rec = _record([_verdict("internal_last_trade_date", "library", "2009-12-31", "0001193125-10-222185")])
    res = _apply([case], {"A_5a-r1": rec}, truth)
    assert res.truth_rows[0]["internal_last_trade_date"] == "2009-12-31"
    assert [(c["field"], c["old"], c["new"]) for c in res.changes] == [
        ("internal_last_trade_date", "2009-12-30", "2009-12-31")]
    assert [r["outcome"] for r in res.ledger_rows] == ["library_right"]


def test_a_library_right_verdict_on_the_shape_sends_the_case_to_ruling_pending():
    truth = [truth_row("A_2010-01-04", "A", shape="no_ending", status="known_wrong", fixed_by="5d")]
    case = _case("A_5a-r1", "mismatch", "A", ["shape"], ["no_ending"], ["ending"], truth_case_id="A_2010-01-04")
    rec = _record([_verdict("shape", "library", "ending", "0001193125-10-222185")])
    res = _apply([case], {"A_5a-r1": rec}, truth)
    row = res.truth_rows[0]
    assert (row["status"], row["fixed_by"], row["shape"]) == ("ruling_pending", "", "no_ending")
    assert [(c["field"], c["new"]) for c in res.changes] == [("status", "ruling_pending")]
    assert [r["outcome"] for r in res.ledger_rows] == ["library_right"]

"""truth_set: the diagnosis truth set as one unit. Where its files are, its one validation, each change (ruling,
correction, rename, flip, settle), idempotence, and the commit that writes rows, legs, change log and ledger
together."""
import csv
import io
import json
import shutil
from pathlib import Path

import pytest

from delist_detection.measurement import diagnosis_truth as dt
from delist_detection.measurement import truth_set as ts
from delist_detection.measurement.loop_round import Loop
from delist_detection.measurement.regression import renamed_to
from delist_detection.measurement.truth import TruthFileError
from delist_detection.measurement.truth_set import LEDGER_COLUMNS, Correction, Ruling, TruthSet
from tests.diagnosis_rows import leg_row, ledger_row, truth_row, write_truth
from tests.lifecycle_tables import contract_row, sec, tables

ROOT = Path(__file__).resolve().parents[1]
CHANGE_HEADER = ",".join(ts.CHANGE_COLUMNS) + "\n"


def _set(tmp_path, rows, legs=(), changes=None, ledger=None):
    """A truth set on disk under tmp_path: truth.csv, truth_legs.csv, truth_changes.csv (raw text) and a ledger."""
    path = tmp_path / "truth.csv"
    write_truth(path, rows, legs)
    if changes is not None:
        ts.changes_path(path).write_text(changes)
    if ledger is not None:
        (tmp_path / "ledger.csv").write_text(ledger)
    return path


def _files(tmp_path):
    return {p.name: p.read_bytes() for p in sorted(tmp_path.iterdir()) if p.is_file()}


def _log(path):
    return list(csv.DictReader(io.StringIO(ts.changes_path(path).read_text())))


# -- where the files are ---------------------------------------------------------------------------------------------
def test_the_legs_and_the_change_log_are_named_after_the_truth_file():
    assert ts.legs_path(Path("data/diagnosis_truth.csv")) == Path("data/diagnosis_truth_legs.csv")
    assert ts.changes_path(Path("data/diagnosis_truth.csv")) == Path("data/diagnosis_truth_changes.csv")


def test_the_scorecard_config_names_the_truth_file(tmp_path):
    assert ts.truth_file_of({"diagnosis": "d.csv"}, tmp_path) == tmp_path / "d.csv"
    assert ts.truth_file_of({"diagnosis": "d.csv", "diagnosis_legs": "d_legs.csv"}, tmp_path) == tmp_path / "d.csv"
    assert ts.truth_file_of({}, tmp_path) is None
    with pytest.raises(TruthFileError, match="named after the truth file"):
        ts.truth_file_of({"diagnosis": "d.csv", "diagnosis_legs": "l.csv"}, tmp_path)
    with pytest.raises(TruthFileError, match="without a diagnosis"):
        ts.truth_file_of({"diagnosis_legs": "l.csv"}, tmp_path)


def test_configured_reads_the_repositorys_config(tmp_path):
    assert ts.configured(ROOT) == ROOT / "data" / "diagnosis_truth.csv"
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "scorecard.json").write_text(json.dumps({"floor": {}}))
    with pytest.raises(TruthFileError, match="names no diagnosis truth file"):
        ts.configured(tmp_path)
    with pytest.raises(TruthFileError, match="scorecard.json"):
        ts.configured(tmp_path / "nowhere")


# -- one validation --------------------------------------------------------------------------------------------------
def test_round_trip_keeps_every_cell(tmp_path):
    row = truth_row("S1_2010-01-04", "S1", exit_kind="merger", stock_ratio="1.05", last_trade_date="",
                    internal_last_trade_date="2010-01-01", note="worked out")
    [case] = TruthSet.open(_set(tmp_path, [row])).cases
    assert case.case_id == "S1_2010-01-04" and case.sec_id == "S1" and case.status == dt.PASS
    assert case.fields["exit_kind"] == "merger" and case.fields["stock_ratio"] == "1.05"
    assert case.fields["last_trade_date"] == "" and case.fields["cash_per_share"] == dt.NOT_SCORED
    assert case.internal_last_trade_date == "2010-01-01" and case.note == "worked out"


def test_the_examined_ending_is_the_cases_own_column_never_its_ids_tail(tmp_path):
    rows = [truth_row("S1_2010-01-04", "S1"), truth_row("S2_5a-r2", "S2", examined_delist_date="2016-06-01"),
            truth_row("S3_2012-02-03", "S3", examined_delist_date="2012-02-03", shape="ending_moved")]
    assert [c.examined_delist_date for c in TruthSet.open(_set(tmp_path, rows)).cases] == [
        "", "2016-06-01", "2012-02-03"]


def test_an_ending_moved_case_needs_the_ending_it_refuses(tmp_path):
    with pytest.raises(TruthFileError, match=r"truth\.csv:2.*examined_delist_date"):
        TruthSet.new(tmp_path / "truth.csv", [truth_row("S1_2010-01-04", "S1", shape="ending_moved")])


def test_star_and_blank_and_basket_are_accepted(tmp_path):
    row = truth_row("S1_2010-01-04", "S1", value_rule="basket", drop_reason="", continuation="")
    assert TruthSet.open(_set(tmp_path, [row])).cases[0].fields["value_rule"] == dt.BASKET


@pytest.mark.parametrize("cells, message", [
    ({"shape": "gone"}, "shape"),
    ({"status": "maybe"}, "status"),
    ({"status": "known_wrong"}, "fixed_by"),
    ({"exit_kind": "acquired"}, "exit_kind"),
    ({"drop_reason": "broke"}, "drop_reason"),
    ({"continuation": "yes"}, "continuation"),
    ({"value_rule": "shares"}, "value_rule"),
    ({"last_trade_date": "2010-13-01"}, "last_trade_date"),
    ({"stock_ratio": "1.05x"}, "stock_ratio"),
    ({"internal_last_trade_date": "soon"}, "internal_last_trade_date"),
    ({"examined_delist_date": "2010-02-30"}, "examined_delist_date"),
    ({"sec_id": ""}, "sec_id"),
])
def test_a_bad_cell_names_the_file_line_and_field(tmp_path, cells, message):
    row = truth_row("S1_2010-01-04", "S1")
    row.update(cells)                                  # after the helper: a blank sec_id is also a cell here
    path = tmp_path / "truth.csv"
    path.write_text(",".join(dt.COLUMNS) + "\n" + ",".join(row[c] for c in dt.COLUMNS) + "\n")
    with pytest.raises(TruthFileError, match=rf"truth\.csv:2.*{message}"):
        TruthSet.open(path)
    with pytest.raises(TruthFileError, match=message):      # the same check refuses to write it
        TruthSet.new(tmp_path / "other.csv", [row])


def test_a_repeated_case_id_is_refused(tmp_path):
    with pytest.raises(TruthFileError, match=r"truth\.csv:3.*repeated"):
        TruthSet.new(tmp_path / "truth.csv", [truth_row("S1_2010-01-04", "S1"), truth_row("S1_2010-01-04", "S1")])


def test_a_wrong_header_is_refused(tmp_path):
    path = tmp_path / "truth.csv"
    path.write_text("case_id,sec_id\nS1_2010-01-04,S1\n")
    with pytest.raises(TruthFileError, match="columns"):
        TruthSet.open(path)


def test_a_row_with_a_missing_or_an_extra_cell_is_refused_not_a_key_error(tmp_path):
    path = _set(tmp_path, [truth_row("S1_2010-01-04", "S1")])
    text = path.read_text()
    path.write_text(text.rstrip("\n").rsplit(",", 1)[0] + "\n")              # the note cell gone
    n = len(dt.COLUMNS)
    with pytest.raises(TruthFileError, match=rf"truth\.csv:2: {n - 1} cells, not {n}"):
        TruthSet.open(path)
    path.write_text(text.rstrip("\n") + ",extra\n")
    with pytest.raises(TruthFileError, match=rf"truth\.csv:2: {n + 1} cells, not {n}"):
        TruthSet.open(path)


def test_legs_load_onto_their_case_in_leg_order(tmp_path):
    path = _set(tmp_path, [truth_row("S1_2010-01-04", "S1", value_rule="basket")],
                [leg_row("S1_2010-01-04", 2, ratio="0.0667", price_ticker="STRZ"),
                 leg_row("S1_2010-01-04", 1, ratio="1", price_ticker="LION")])
    [case] = TruthSet.open(path).cases
    assert [(lg.leg, lg.price_ticker) for lg in case.legs] == [(1, "LION"), (2, "STRZ")]


@pytest.mark.parametrize("legs, message", [
    ([leg_row("NOPE_2010-01-04", 1)], "unknown case"),
    ([leg_row("S1_2010-01-04", 1, ratio="x")], "ratio"),
    ([leg_row("S1_2010-01-04", 1), leg_row("S1_2010-01-04", 1)], "repeated"),
    ([leg_row("S1_2010-01-04", 0)], "leg"),
])
def test_bad_legs_are_refused(tmp_path, legs, message):
    path = tmp_path / "truth.csv"
    write_truth(path, [truth_row("S1_2010-01-04", "S1")])
    ts.legs_path(path).write_text(",".join(dt.LEG_COLUMNS) + "\n" + "".join(
        ",".join(r[c] for c in dt.LEG_COLUMNS) + "\n" for r in legs))
    with pytest.raises(TruthFileError, match=message):
        TruthSet.open(path)


def test_missing_files_are_empty(tmp_path):
    assert TruthSet.open(tmp_path / "absent.csv", ledger=tmp_path / "absent_ledger.csv").cases == []
    path = tmp_path / "truth.csv"
    write_truth(path, [truth_row("S1_2010-01-04", "S1")])
    ts.legs_path(path).unlink()
    assert TruthSet.open(path).cases[0].legs == ()


def test_the_change_log_and_the_ledger_are_checked_too(tmp_path):
    path = _set(tmp_path, [truth_row("S1_2010-01-04", "S1")], changes="case_id,field\n")
    with pytest.raises(TruthFileError, match="changes.csv: columns"):
        TruthSet.open(path)
    ts.changes_path(path).write_text(CHANGE_HEADER + "S1_2010-01-04,status,pass\n")
    with pytest.raises(TruthFileError, match=r"changes\.csv:2: 3 cells, not 6"):
        TruthSet.open(path)
    ts.changes_path(path).unlink()
    (tmp_path / "ledger.csv").write_text("key,kind\n")
    with pytest.raises(TruthFileError, match="ledger.csv: columns"):
        TruthSet.open(path, ledger=tmp_path / "ledger.csv")
    with pytest.raises(TruthFileError, match="ledger.csv: columns"):
        ts.read_ledger(tmp_path / "ledger.csv")


# -- a ruling --------------------------------------------------------------------------------------------------------
TAG, REPORT = "5x ruling 2026-10-07", "docs/x.md"


def _ruling(case_id="S1_2010-01-04", cells=(("exit_kind", "merger"),), why="the 8-K says so", **kw):
    return Ruling(case_id, cells, why, tag=TAG, report=REPORT, **kw)


def test_a_ruling_sets_its_cells_with_its_reason_and_report_and_notes_once(tmp_path):
    path = _set(tmp_path, [truth_row("S1_2010-01-04", "S1", note="report note", fixed_by="5x", status="known_wrong")])
    truth = TruthSet.open(path)
    assert truth.rule(_ruling(cells=(("exit_kind", "merger"), ("fixed_by", "5x"), ("cash_per_share", "3.00")))) == 2
    assert [(c["field"], c["old"], c["new"], c["reason"], c["report"]) for c in truth.changes] == [
        ("exit_kind", "*", "merger", f"{TAG}: the 8-K says so", REPORT),
        ("cash_per_share", "*", "3.00", f"{TAG}: the 8-K says so", REPORT)]
    assert truth.row("S1_2010-01-04")["note"] == f"report note; {TAG}: the 8-K says so"
    truth.commit()
    again = TruthSet.open(path)
    assert again.rule(_ruling(cells=(("exit_kind", "merger"), ("fixed_by", "5x"), ("cash_per_share", "3.00")))) == 0
    assert again.changes == [] and again.commit() == []


def test_a_ruling_applies_once_even_after_a_later_change_moved_its_cell_on(tmp_path):
    """5f's carried rows (VMED, MHS): the ruling made them known_wrong for 5f, the wave 2 loop flipped them to pass;
    applying the ruling again must not undo the flip."""
    path = _set(tmp_path, [truth_row("V_wave1-r1", "V")])
    later = _ruling("V_wave1-r1", (("status", "known_wrong"), ("fixed_by", "5f")), "carried to 5f")
    truth = TruthSet.open(path)
    assert truth.rule(later) == 2
    truth.move_status("V_wave1-r1", dt.PASS, reason="the library now matches")
    truth.commit()
    again = TruthSet.open(path)
    assert again.rule(later) == 0 and again.row("V_wave1-r1")["status"] == dt.PASS


def test_a_ruling_leaves_a_row_another_sub_plan_owns(tmp_path):
    rows = [truth_row("A_2010-01-04", "A", status="known_wrong", fixed_by="5d"),
            truth_row("B_2010-01-04", "B", status="known_wrong", fixed_by="5f"),
            truth_row("C_2010-01-04", "C", status="known_wrong", fixed_by="residual")]
    truth = TruthSet.open(_set(tmp_path, rows))
    to_residual = (("fixed_by", "residual"), ("exit_kind", "merger"))
    assert truth.rule(_ruling("A_2010-01-04", to_residual, owner="5f")) == 0           # 5d's row: left alone
    assert truth.rule(_ruling("B_2010-01-04", to_residual, owner="5f")) == 2           # 5f's own row
    assert truth.rule(_ruling("C_2010-01-04", to_residual, owner="5f")) == 1           # already where it sends it
    assert truth.rule(_ruling("A_2010-01-04", to_residual)) == 2                       # no owner: any row
    with pytest.raises(TruthFileError, match="no case 'NOPE'"):
        truth.rule(_ruling("NOPE"))


def test_a_ruling_replaces_or_removes_a_cases_legs(tmp_path):
    path = _set(tmp_path, [truth_row("B_2013-06-07", "B", value_rule="basket"), truth_row("S_2024-12-07", "S")],
                [leg_row("S_2024-12-07", 1, ratio="1", price_ticker="GEAR")])
    legs = ({"leg": "1", "ratio": "0.2582", "price_sec_id": "BBGA", "price_ticker": "LBTYA", "price_date": ""},
            {"leg": "2", "ratio": "0.1928", "price_sec_id": "*", "price_ticker": "LBTYK", "price_date": ""})
    truth = TruthSet.open(path)
    assert truth.rule(_ruling("B_2013-06-07", (), "R3: a basket", legs=legs)) == 1
    assert truth.rule(_ruling("S_2024-12-07", (("value_rule", "cash_plus_stock"),), "R3: one security", legs=())) == 2
    assert [(c["case_id"], c["field"], c["old"], c["new"]) for c in truth.changes] == [
        ("B_2013-06-07", "legs", "", "1: 0.2582 LBTYA; 2: 0.1928 LBTYK"),
        ("S_2024-12-07", "value_rule", "*", "cash_plus_stock"), ("S_2024-12-07", "legs", "1: 1 GEAR", "")]
    truth.commit()
    again = TruthSet.open(path)
    assert [(c.case_id, [lg.price_ticker for lg in c.legs]) for c in again.cases] == [
        ("B_2013-06-07", ["LBTYA", "LBTYK"]), ("S_2024-12-07", [])]
    assert again.rule(_ruling("B_2013-06-07", (), "R3: a basket", legs=legs)) == 0


def test_a_ruling_with_no_cells_is_a_note_logged_once(tmp_path):
    path = _set(tmp_path, [truth_row("L_2023-08-13", "L", note="n")])
    truth = TruthSet.open(path)
    note = _ruling("L_2023-08-13", (), "the truth's last trade stands")
    assert truth.rule(note) == 1 and truth.rule(note) == 0
    assert [(c["field"], c["old"], c["new"]) for c in truth.changes] == [("note", "", "the truth's last trade stands")]
    assert truth.row("L_2023-08-13")["note"] == f"n; {TAG}: the truth's last trade stands"


CNB = "BBG000BF2JS9_2009-09-18"
CNB_TAG = "operator ruling 2026-10-03 applied as for IMB 2008 (architecture step 4)"
CNB_REPORT = "docs/superpowers/plans/2026-10-07-architecture-deepening.md"
CNB_NOTE = ("Colonial BancGroup: bank closed, NYSE suspension 8-K 3.01 on 2009-08-17, Chapter 11 8-K 1.03; skeptic "
            "upheld bankruptcy over sec_order; own OTC symbol unconfirmed")


def test_the_step_4_cnb_rulings_as_data(tmp_path):
    """The controller's two step-4 rulings on CNB 2009 (data/diagnosis_truth_changes.csv's last two rows): each gives
    the row the change log holds, byte for byte. The second's reason has a comma, which the module quotes (the row
    was first written by hand unquoted, seven cells, and quoted after step 9a found it)."""
    before = truth_row(CNB, "BBG000BF2JS9", ticker="CNB", report=f"reports/{CNB}.md", confidence="inferred",
                       skeptic="upheld", exit_kind="dropped", drop_reason="bankruptcy", continuation="false",
                       successor_sec_id="", last_trade_date="2009-08-17", value_rule="otc_print", cash_per_share="",
                       cash_currency="", stock_ratio="", price_sec_id="BBG000BF2JS9", price_ticker="*",
                       price_date="2009-08-18", recovery_ratio="", internal_last_trade_date="2009-08-17", note=CNB_NOTE)
    path = _set(tmp_path, [before])
    truth = TruthSet.open(path)
    truth.rule(Ruling(CNB, (("last_trade_date", "*"),), "suspended immediately on D: the last trade date is not scored",
                      tag=CNB_TAG, report=CNB_REPORT))
    truth.commit()
    real = ts.changes_path(ts.configured(ROOT)).read_text().splitlines()
    assert ts.changes_path(path).read_text().splitlines()[-1] == real[-2]
    assert TruthSet.open(path).row(CNB)["note"] == (
        f"{CNB_NOTE}; {CNB_TAG}: suspended immediately on D: the last trade date is not scored")
    truth = TruthSet.open(path)
    truth.rule(Ruling(CNB, (("price_date", "*"),), "the price date is the session after the last trade date, which "
                      "is not scored", tag=CNB_TAG, report=CNB_REPORT))
    truth.commit()
    last = _log(path)[-1]
    assert (last["field"], last["old"], last["new"], last["report"]) == ("price_date", "2009-08-18", "*", CNB_REPORT)
    assert last["reason"].endswith("the last trade date, which is not scored")
    assert ts.changes_path(path).read_text().splitlines()[-1] == real[-1]


# -- a correction ----------------------------------------------------------------------------------------------------
def test_a_correction_rewrites_the_note_and_the_logged_reasons_and_logs_nothing(tmp_path):
    path = _set(tmp_path, [truth_row("M_2007-07-12", "M", note="n; 5i: the wrong reason")],
                changes=CHANGE_HEADER + "M_2007-07-12,fixed_by,5i,residual,5i: the wrong reason,r\n"
                                        "X_2007-07-12,fixed_by,5i,residual,5i: the wrong reason,r\n")
    truth = TruthSet.open(path)
    fix = Correction("M_2007-07-12", "the wrong reason", "the right reason")
    assert truth.correct(fix) == 2 and truth.correct(fix) == 0 and truth.changes == []
    truth.commit()
    assert [r["reason"] for r in _log(path)] == ["5i: the right reason", "5i: the wrong reason"]
    assert TruthSet.open(path).row("M_2007-07-12")["note"] == "n; 5i: the right reason"


# -- a rename --------------------------------------------------------------------------------------------------------
def _rename(old, new):
    return {"old_sec_id": old, "new_sec_id": new, "changed_on": "2026-10-04", "issuer_cik": "9",
            "share_class": "COMMON"}


def test_a_rename_follows_a_chain_and_renames_every_cell_and_leg_that_names_the_security(tmp_path):
    """Identity follows the FIGI (R2): a truth row that is, prices at or continues into a renamed security names the
    security it is now, legs included; P renamed to M and M to F is F (`regression.renamed_to`, one chain rule)."""
    rows = [truth_row("P_2010-01-04", "P", price_sec_id="P", value_rule="basket"),
            truth_row("C_2011-01-04", "C", successor_sec_id="M"), truth_row("B_2012-01-04", "B")]
    path = _set(tmp_path, rows, [leg_row("P_2010-01-04", 1, price_sec_id="M"),
                                 leg_row("P_2010-01-04", 2, price_sec_id="X")])
    ids = [_rename("P", "M"), _rename("M", "F")]
    assert renamed_to(ids) == {"P": "F", "M": "F"}
    truth = TruthSet.open(path)
    assert truth.rename(ids) == 4
    assert [(r["case_id"], r["sec_id"], r["price_sec_id"], r["successor_sec_id"]) for r in truth.rows] == [
        ("P_2010-01-04", "F", "F", "*"), ("C_2011-01-04", "C", "*", "F"), ("B_2012-01-04", "B", "*", "*")]
    assert [lg["price_sec_id"] for lg in truth.legs] == ["F", "X"]
    assert sorted((c["case_id"], c["field"], c["old"], c["new"]) for c in truth.changes) == [
        ("C_2011-01-04", "successor_sec_id", "M", "F"), ("P_2010-01-04", "leg1.price_sec_id", "M", "F"),
        ("P_2010-01-04", "price_sec_id", "P", "F"), ("P_2010-01-04", "sec_id", "P", "F")]
    assert {c["reason"] for c in truth.changes} == {ts.RENAME_REASON}
    assert truth.rename(ids) == 0


def test_a_rename_follows_a_figi_renamed_to_another_figi(tmp_path):
    """Sub-plan 5h, rule F: id_changes also holds FIGI-to-FIGI rows (CRC BBG00Y04KP80 to BBG0060B3M63)."""
    truth = TruthSet.open(_set(tmp_path, [truth_row("BBG00Y04KP80_2016-06-01", "BBG00Y04KP80")]))
    assert truth.rename([_rename("BBG00Y04KP80", "BBG0060B3M63")]) == 1
    assert truth.rows[0]["sec_id"] == "BBG0060B3M63" and truth.rows[0]["case_id"] == "BBG00Y04KP80_2016-06-01"


# -- a status flip ---------------------------------------------------------------------------------------------------
def test_a_flip_turns_the_known_wrong_cases_that_now_match_into_pass(tmp_path):
    rows = [truth_row("A_2010-01-04", "A", status="known_wrong", fixed_by="5a", exit_kind="merger"),
            truth_row("B_2010-01-04", "B", status="known_wrong", fixed_by="5a", exit_kind="merger")]
    truth = TruthSet.open(_set(tmp_path, rows))
    lib = dt.LibraryRows.of(tables([sec("A"), sec("B")], contract_delistings=[
        contract_row("A", exit_kind="merger"), contract_row("B", exit_kind="exchange")]))
    assert truth.flip(lib) == 1
    assert [(r["status"], r["fixed_by"]) for r in truth.rows] == [("pass", ""), ("known_wrong", "5a")]
    assert [(c["case_id"], c["field"], c["old"], c["new"], c["reason"]) for c in truth.changes] == [
        ("A_2010-01-04", "status", "known_wrong", "pass", "the library now matches")]
    assert truth.flip(lib) == 0


# -- the ledger ------------------------------------------------------------------------------------------------------
def test_settled_ledger_rows_are_committed_with_the_truth_set(tmp_path):
    path = _set(tmp_path, [truth_row("A_2010-01-04", "A")])
    truth = TruthSet.open(path, ledger=tmp_path / "loop" / "diagnosed.csv")
    truth.settle([ledger_row("k1"), ledger_row("k2", outcome="new_right")])
    assert truth.ledger_keys == {"k1", "k2"} and len(truth.settled) == 2
    assert truth.commit() == [tmp_path / "loop" / "diagnosed.csv"]
    back = ts.read_ledger(tmp_path / "loop" / "diagnosed.csv")
    assert [r["key"] for r in back] == ["k1", "k2"] and ts.read_ledger(tmp_path / "absent.csv") == []
    assert TruthSet.open(path, ledger=tmp_path / "loop" / "diagnosed.csv").ledger_keys == {"k1", "k2"}
    with pytest.raises(ValueError, match="without a ledger"):
        TruthSet.open(path).settle([ledger_row("k3")])


# -- the commit ------------------------------------------------------------------------------------------------------
def test_a_commit_writes_only_what_changed_and_appends_to_the_change_log(tmp_path):
    old_log = CHANGE_HEADER + 'Z_2009-01-01,note,,x,"a, b",r\n'
    path = _set(tmp_path, [truth_row("A_2010-01-04", "A"), truth_row("B_2010-01-04", "B")],
                [leg_row("A_2010-01-04", 1)], changes=old_log, ledger=",".join(LEDGER_COLUMNS) + "\n")
    before = _files(tmp_path)
    truth = TruthSet.open(path, ledger=tmp_path / "ledger.csv")
    assert truth.commit() == []
    assert _files(tmp_path) == before
    truth.rule(_ruling("B_2010-01-04"))
    assert truth.commit() == [path, ts.changes_path(path)]
    after = _files(tmp_path)
    assert after["truth_legs.csv"] == before["truth_legs.csv"] and after["ledger.csv"] == before["ledger.csv"]
    assert after["truth_changes.csv"].decode().startswith(old_log)
    old, new = before["truth.csv"].decode().splitlines(), after["truth.csv"].decode().splitlines()
    changed = [(a, b) for a, b in zip(old, new) if a != b]
    assert len(changed) == 1 and changed[0][0].startswith("B_2010-01-04")
    assert truth.commit() == []


def test_a_commit_writes_nothing_when_the_set_is_invalid_or_a_write_fails(tmp_path, monkeypatch):
    path = _set(tmp_path, [truth_row("A_2010-01-04", "A")], changes=CHANGE_HEADER)
    before = _files(tmp_path)
    truth = TruthSet.open(path)
    truth.rule(_ruling("A_2010-01-04", (("exit_kind", "acquired"),)))
    with pytest.raises(TruthFileError, match="exit_kind"):
        truth.commit()
    assert _files(tmp_path) == before
    truth = TruthSet.open(path)
    truth.rule(_ruling("A_2010-01-04"))
    calls = []
    real = Path.write_bytes

    def fail_second(self, data):
        calls.append(self)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", fail_second)
    with pytest.raises(OSError, match="disk full"):
        truth.commit()
    assert _files(tmp_path) == before


def test_a_new_set_writes_its_truth_file_and_legs_and_keeps_the_change_log(tmp_path):
    path = _set(tmp_path, [truth_row("OLD_2010-01-04", "O")], [leg_row("OLD_2010-01-04", 1)],
                changes=CHANGE_HEADER + "OLD_2010-01-04,note,,x,y,r\n")
    log = ts.changes_path(path).read_bytes()
    TruthSet.new(path, [truth_row("A_2010-01-04", "A")]).commit()
    truth = TruthSet.open(path)
    assert [r["case_id"] for r in truth.rows] == ["A_2010-01-04"] and truth.legs == []
    assert ts.changes_path(path).read_bytes() == log


def test_a_round_trip_keeps_every_byte_of_every_file(tmp_path):
    """Open and commit with no change: nothing is written, so every file keeps its bytes. A change-log record keeps
    its own text: a quoted field over two lines, and a record with a cell past its six (as the real log's last row)."""
    log = (CHANGE_HEADER + 'A_2010-01-04,note,,"two\nlines",why,r\n'
           "A_2010-01-04,price_date,2009-08-18,*,ruling: after the last trade, which is not scored,docs/x.md\n")
    path = _set(tmp_path, [truth_row("A_2010-01-04", "A", note='say "hi", twice')], [leg_row("A_2010-01-04", 1)],
                changes=log, ledger=",".join(LEDGER_COLUMNS) + "\nk,mismatch,A,5a,1,known,\n")
    before = _files(tmp_path)
    truth = TruthSet.open(path, ledger=tmp_path / "ledger.csv")
    assert truth.commit() == [] and _files(tmp_path) == before
    truth.rule(_ruling("A_2010-01-04"))
    truth.commit()
    assert ts.changes_path(path).read_text().startswith(log)


def test_a_round_trip_on_the_real_truth_set_keeps_every_byte(tmp_path):
    """The committed truth file, legs, change log and ledger, opened and committed with no change: nothing written,
    every byte kept (the change log's last row, hand-written with an unquoted comma, included)."""
    real = ts.configured(ROOT)
    for path in (real, ts.legs_path(real), ts.changes_path(real)):
        shutil.copy(path, tmp_path / path.name)
    shutil.copy(Loop.of(ROOT).ledger, tmp_path / "diagnosed.csv")
    before = _files(tmp_path)
    truth = TruthSet.open(tmp_path / "diagnosis_truth.csv", ledger=tmp_path / "diagnosed.csv")
    assert len(truth.cases) == len(truth.rows) > 300
    assert truth.commit() == [] and _files(tmp_path) == before
    case = truth.rows[0]["case_id"]
    truth.rule(Ruling(case, (("ticker", "CHANGED"),), "a test", tag="t", report=""))
    truth.commit()
    after = _files(tmp_path)
    assert after["diagnosis_truth_changes.csv"].startswith(before["diagnosis_truth_changes.csv"])
    added = after["diagnosis_truth_changes.csv"][len(before["diagnosis_truth_changes.csv"]):].decode()
    assert added.count("\n") == 1 and added.startswith(f"{case},ticker,")
    assert after["diagnosis_truth_legs.csv"] == before["diagnosis_truth_legs.csv"]
    assert after["diagnosed.csv"] == before["diagnosed.csv"]
    old, new = before["diagnosis_truth.csv"].decode().splitlines(), after["diagnosis_truth.csv"].decode().splitlines()
    assert len(old) == len(new) and sum(a != b for a, b in zip(old, new)) == 1

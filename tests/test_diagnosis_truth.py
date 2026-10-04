"""diagnosis_truth: the truth file's format and loader (spec 1.1), and the judge (spec 1.3)."""
import pytest

from delist_detection import diagnosis_truth as dt
from tests.diagnosis_rows import leg_row, truth_row


def _write(tmp_path, rows, legs=None):
    path = tmp_path / "truth.csv"
    dt.write_diagnosis_truth(path, rows)
    legs_path = None
    if legs is not None:
        legs_path = tmp_path / "legs.csv"
        dt.write_legs(legs_path, legs)
    return path, legs_path


def test_round_trip_keeps_every_cell(tmp_path):
    row = truth_row("S1_2010-01-04", "S1", exit_kind="merger", stock_ratio="1.05", last_trade_date="",
                    internal_last_trade_date="2010-01-01", note="worked out")
    path, _ = _write(tmp_path, [row])
    [case] = dt.load_diagnosis_truth(path)
    assert case.case_id == "S1_2010-01-04" and case.sec_id == "S1" and case.status == dt.PASS
    assert case.fields["exit_kind"] == "merger" and case.fields["stock_ratio"] == "1.05"
    assert case.fields["last_trade_date"] == "" and case.fields["cash_per_share"] == dt.NOT_SCORED
    assert case.internal_last_trade_date == "2010-01-01" and case.note == "worked out"
    assert case.old_delist_date == "2010-01-04"


def test_a_nodate_case_has_no_old_delist_date(tmp_path):
    path, _ = _write(tmp_path, [truth_row("S1_nodate", "S1")])
    assert dt.load_diagnosis_truth(path)[0].old_delist_date == ""


def test_star_and_blank_and_basket_are_accepted(tmp_path):
    row = truth_row("S1_2010-01-04", "S1", value_rule="basket", drop_reason="", continuation="")
    path, _ = _write(tmp_path, [row])
    assert dt.load_diagnosis_truth(path)[0].fields["value_rule"] == dt.BASKET


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
    ({"sec_id": ""}, "sec_id"),
])
def test_a_bad_cell_names_the_file_line_and_field(tmp_path, cells, message):
    row = truth_row("S1_2010-01-04", "S1")
    row.update(cells)                                  # after the helper: a blank sec_id is also a cell here
    path, _ = _write(tmp_path, [row])
    with pytest.raises(dt.DiagnosisTruthError, match=rf"truth\.csv:2.*{message}"):
        dt.load_diagnosis_truth(path)


def test_a_repeated_case_id_is_refused(tmp_path):
    path, _ = _write(tmp_path, [truth_row("S1_2010-01-04", "S1"), truth_row("S1_2010-01-04", "S1")])
    with pytest.raises(dt.DiagnosisTruthError, match=r"truth\.csv:3.*repeated"):
        dt.load_diagnosis_truth(path)


def test_a_wrong_header_is_refused(tmp_path):
    path = tmp_path / "truth.csv"
    path.write_text("case_id,sec_id\nS1_2010-01-04,S1\n")
    with pytest.raises(dt.DiagnosisTruthError, match="columns"):
        dt.load_diagnosis_truth(path)


def test_legs_load_onto_their_case_in_leg_order(tmp_path):
    path, legs = _write(tmp_path, [truth_row("S1_2010-01-04", "S1", value_rule="basket")],
                        [leg_row("S1_2010-01-04", 2, ratio="0.0667", price_ticker="STRZ"),
                         leg_row("S1_2010-01-04", 1, ratio="1", price_ticker="LION")])
    [case] = dt.load_diagnosis_truth(path, legs)
    assert [(lg.leg, lg.price_ticker) for lg in case.legs] == [(1, "LION"), (2, "STRZ")]


@pytest.mark.parametrize("legs, message", [
    ([leg_row("NOPE_2010-01-04", 1)], "unknown case"),
    ([leg_row("S1_2010-01-04", 1, ratio="x")], "ratio"),
    ([leg_row("S1_2010-01-04", 1), leg_row("S1_2010-01-04", 1)], "repeated"),
    ([leg_row("S1_2010-01-04", 0)], "leg"),
])
def test_bad_legs_are_refused(tmp_path, legs, message):
    path, legs_path = _write(tmp_path, [truth_row("S1_2010-01-04", "S1")], legs)
    with pytest.raises(dt.DiagnosisTruthError, match=message):
        dt.load_diagnosis_truth(path, legs_path)


def test_a_missing_legs_file_means_no_legs(tmp_path):
    path, _ = _write(tmp_path, [truth_row("S1_2010-01-04", "S1")])
    assert dt.load_diagnosis_truth(path, tmp_path / "absent.csv")[0].legs == ()

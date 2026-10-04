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


from tests.lifecycle_tables import contract_row, ending, sec, tables


def _lib(contract=(), delistings=(), legs_rows=None, securities=("S1", "S2")):
    return dt.LibraryRows.of(tables([sec(s) for s in securities], delistings=list(delistings),
                                    contract_delistings=list(contract)), legs_rows)


def _case(**cells):
    return dt.parse_rows([truth_row("S1_2010-01-04", "S1", **cells)])[0]


def test_an_ending_that_matches_every_scored_field_is_ok():
    lib = _lib([contract_row("S1", exit_kind="merger", value_rule="cash", cash_per_share="10.000000",
                             cash_currency="")])
    j = dt.judge_case(_case(exit_kind="merger", value_rule="cash", cash_per_share="10", cash_currency=""), lib)
    assert j.ok


def test_numbers_compare_at_six_significant_figures():
    lib = _lib([contract_row("S1", stock_ratio="1.050000")])
    assert dt.judge_case(_case(stock_ratio="1.05"), lib).ok
    assert not dt.judge_case(_case(stock_ratio="1.051"), lib).ok


def test_a_blank_truth_cell_requires_a_blank_and_star_is_never_scored():
    lib = _lib([contract_row("S1", cash_currency="USD", price_ticker="UAUA")])
    j = dt.judge_case(_case(cash_currency="", price_ticker="*"), lib)
    assert [(m.field, m.truth, m.library) for m in j.mismatches] == [("cash_currency", "", "USD")]
    assert str(j.mismatches[0]) == "cash_currency USD != (blank)"


def test_an_ending_with_no_contract_row_is_one_mismatch():
    j = dt.judge_case(_case(exit_kind="merger"), _lib())
    assert [m.field for m in j.mismatches] == ["ending"]


def test_no_ending_wants_no_contract_row():
    assert dt.judge_case(_case(shape="no_ending"), _lib()).ok
    j = dt.judge_case(_case(shape="no_ending"), _lib([contract_row("S1", exit_kind="exchange")]))
    assert [(m.field, m.library) for m in j.mismatches] == [("shape", "ending")]


def test_a_case_whose_security_is_not_in_the_run_is_one_sec_id_mismatch_for_any_shape():
    lib = _lib(securities=("BBGX",))
    for shape in dt.SHAPES:
        case = dt.parse_rows([truth_row("CIK9-COMMON_2010-01-04", "CIK9-COMMON", shape=shape, exit_kind="merger")])[0]
        j = dt.judge_case(case, lib)
        assert [(m.field, m.truth, m.library) for m in j.mismatches] == [
            ("sec_id", "CIK9-COMMON", "(not in the run)")]
    assert "sec_id" in dt.MISMATCH_FIELDS


def test_ending_moved_refuses_the_old_ending_and_scores_the_later_one():
    old = _lib([contract_row("S1", exit_kind="exchange")], [ending("S1", "2010-01-04", "exchange_transfer")])
    assert [m.field for m in dt.judge_case(_case(shape="ending_moved"), old).mismatches] == ["shape"]
    later = _lib([contract_row("S1", exit_kind="merger")], [ending("S1", "2014-04-08")])
    assert dt.judge_case(_case(shape="ending_moved", exit_kind="merger"), later).ok
    assert dt.judge_case(_case(shape="ending_moved"), _lib()).ok          # nothing scored, nothing required


def test_internal_last_trade_date_is_judged_on_delistings_csv():
    lib = _lib([contract_row("S1", last_trade_date="")], [ending("S1", "2010-01-04", ltd="2009-12-31")])
    assert dt.judge_case(_case(last_trade_date="", internal_last_trade_date="2009-12-31"), lib).ok
    j = dt.judge_case(_case(internal_last_trade_date="2010-01-01"), lib)
    assert [(m.field, m.library) for m in j.mismatches] == [("internal_last_trade_date", "2009-12-31")]


def test_legs_need_the_payout_legs_table_and_match_leg_by_leg():
    case = dt.parse_rows([truth_row("S1_2010-01-04", "S1", value_rule="basket")], legs={
        "S1_2010-01-04": (dt.Leg(1, "1", "", "LION", ""), dt.Leg(2, "0.0667", "", "STRZ", ""))})[0]
    contract = [contract_row("S1", value_rule="basket")]
    assert [m.field for m in dt.judge_case(case, _lib(contract)).mismatches] == ["legs"]
    legs = [{"sec_id": "S1", "leg": "1", "ratio": "1.000000", "price_sec_id": "", "price_ticker": "LION",
             "price_date": ""},
            {"sec_id": "S1", "leg": "2", "ratio": "0.066700", "price_sec_id": "", "price_ticker": "STRY",
             "price_date": ""}]
    j = dt.judge_case(case, _lib(contract, legs_rows=legs))
    assert [(m.field, m.truth, m.library) for m in j.mismatches] == [("leg2.price_ticker", "STRZ", "STRY")]
    assert dt.field_key("leg2.price_ticker") == "legs"


def test_judge_all_skips_ruling_pending_cases():
    cases = dt.parse_rows([truth_row("S1_2010-01-04", "S1", exit_kind="merger"),
                           truth_row("S2_2010-01-04", "S2", status="ruling_pending", exit_kind="merger")])
    assert [j.case.case_id for j in dt.judge_all(cases, _lib())] == ["S1_2010-01-04"]

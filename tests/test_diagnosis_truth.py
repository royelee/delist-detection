"""diagnosis_truth: the judge (spec 1.3). The truth files' format and loading are the truth set's
(tests/test_truth_set.py)."""
from delist_detection import diagnosis_truth as dt
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row, ending, sec, tables


def _lib(contract=(), delistings=(), legs_rows=None, securities=("S1", "S2")):
    return dt.LibraryRows.of(tables([sec(s) for s in securities], delistings=list(delistings),
                                    contract_delistings=list(contract), payout_legs=legs_rows))


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

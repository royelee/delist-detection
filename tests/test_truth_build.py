"""truth_build: one normalized JSON row into one truth row (spec 1.2)."""
from delist_detection import diagnosis_truth as dt
from delist_detection import truth_build as tb
from tests.lifecycle_tables import contract_row, sec, tables

FIELDS = {f: "" for f in dt.SCORED}


def _norm(**over):
    norm = {"case_id": "BBGA_2010-01-04", "sec_id": "BBGA", "shape": "ending",
            "fields": {**FIELDS, "exit_kind": "merger", "continuation": "false", "value_rule": "cash",
                       "cash_per_share": "10", "cash_currency": "USD"},
            "internal_last_trade_date": "", "legs": [], "identity_check": None, "residual": "", "pending": [],
            "notes": "8-K 2.01"}
    norm.update(over)
    return norm


META = {"ticker": "AAA", "report": "reports/BBGA_2010-01-04.md", "confidence": "verified", "skeptic": "upheld"}


def _assemble(norm, composite=None, securities=()):
    return tb.assemble(norm, META, composite_of=lambda cusip: composite, securities=set(securities))


def test_a_settled_row_carries_every_field_and_the_report_metadata():
    row, legs = _assemble(_norm())
    assert (row["case_id"], row["ticker"], row["cash_per_share"], row["status"]) == ("BBGA_2010-01-04", "AAA", "10", "")
    assert row["note"] == "8-K 2.01" and legs == []


def test_pending_fields_become_star_and_the_row_ruling_pending():
    row, _ = _assemble(_norm(pending=[{"field": "cash_per_share", "question": "which amendment?"}]))
    assert (row["cash_per_share"], row["status"]) == ("*", "ruling_pending") and "which amendment?" in row["note"]


def test_a_residual_row_is_known_wrong_with_its_reason():
    row, _ = _assemble(_norm(residual="no OTC ADS price source"))
    assert (row["status"], row["fixed_by"]) == ("known_wrong", "residual") and "no OTC ADS" in row["note"]


def test_a_new_cusip_with_its_own_figi_turns_into_a_continuation():
    norm = _norm(shape="no_ending", fields=dict(FIELDS), identity_check={"old_cusip": "1", "new_cusip": "2"})
    row, _ = _assemble(norm, composite="BBGB", securities={"BBGB"})
    assert (row["shape"], row["continuation"], row["successor_sec_id"], row["value_rule"]) == (
        "ending", "true", "BBGB", "continuation")
    unseen, _ = _assemble(norm, composite="BBGC", securities=set())
    assert unseen["successor_sec_id"] == "*"


def test_the_same_figi_or_none_or_a_placeholder_keeps_one_security():
    norm = _norm(shape="no_ending", fields=dict(FIELDS), identity_check={"old_cusip": "1", "new_cusip": "2"})
    assert _assemble(norm, composite="BBGA")[0]["shape"] == "no_ending"
    assert _assemble(norm, composite=None)[0]["shape"] == "no_ending"
    placeholder = {**norm, "case_id": "CIK1-COMMON_2010-01-04", "sec_id": "CIK1-COMMON"}
    assert _assemble(placeholder, composite="BBGB")[0]["shape"] == "no_ending"


def test_an_unsettled_openfigi_answer_leaves_the_shape_and_makes_the_row_ruling_pending():
    norm = _norm(shape="no_ending", fields=dict(FIELDS), identity_check={"old_cusip": "1", "new_cusip": "2"})
    row, _ = _assemble(norm, composite=tb.UNSETTLED, securities={"BBGB"})
    assert (row["shape"], row["continuation"], row["status"]) == ("no_ending", "", "ruling_pending")
    assert "R2: OpenFIGI could not settle the new CUSIP 2 (error or several US lines)" in row["note"]


def test_an_agent_written_ending_keeps_its_fields_despite_an_identity_check():
    norm = _norm(identity_check={"old_cusip": "1", "new_cusip": "2"})
    row, _ = _assemble(norm, composite="BBGB", securities={"BBGB"})
    assert (row["shape"], row["exit_kind"], row["cash_per_share"], row["status"]) == ("ending", "merger", "10", "")
    row, _ = _assemble(norm, composite=tb.UNSETTLED)
    assert (row["shape"], row["status"]) == ("ending", "")


def test_ending_moved_also_takes_the_r2_flip():
    norm = _norm(shape="ending_moved", fields=dict(FIELDS), identity_check={"old_cusip": "1", "new_cusip": "2"})
    row, _ = _assemble(norm, composite="BBGB", securities={"BBGB"})
    assert (row["shape"], row["continuation"]) == ("ending", "true")


def test_the_row_keeps_the_ending_its_report_examined():
    norm = _norm(shape="ending_moved", fields=dict(FIELDS))
    row, _ = tb.assemble(norm, {**META, "examined_delist_date": "2010-01-04"}, composite_of=lambda cusip: None,
                         securities=set())
    assert row["examined_delist_date"] == "2010-01-04"
    assert dt.parse_rows([{**row, "status": "pass"}])[0].examined_delist_date == "2010-01-04"
    assert _assemble(_norm())[0]["examined_delist_date"] == ""            # none given: blank, never the id's tail


def test_legs_come_out_as_leg_rows():
    _, legs = _assemble(_norm(legs=[{"leg": 1, "ratio": "1", "price_sec_id": "", "price_ticker": "LION",
                                     "price_date": ""}]))
    assert legs == [{"case_id": "BBGA_2010-01-04", "leg": "1", "ratio": "1", "price_sec_id": "",
                     "price_ticker": "LION", "price_date": ""}]


def test_final_status_uses_the_judgement_and_the_case_map():
    row, _ = _assemble(_norm())
    tb.final_status(row, ok=True, sub_plan="5e")
    assert (row["status"], row["fixed_by"]) == ("pass", "")
    row, _ = _assemble(_norm())
    tb.final_status(row, ok=False, sub_plan="5e")
    assert (row["status"], row["fixed_by"]) == ("known_wrong", "5e")
    row, _ = _assemble(_norm())
    tb.final_status(row, ok=False, sub_plan="none")
    assert row["status"] == "ruling_pending" and "no sub-plan" in row["note"]
    pending, _ = _assemble(_norm(pending=[{"field": "cash_per_share", "question": "q"}]))
    tb.final_status(pending, ok=True, sub_plan="5e")
    assert pending["status"] == "ruling_pending"


def test_review_markdown_lists_counts_pending_questions_and_residuals():
    a, _ = _assemble(_norm())
    tb.final_status(a, ok=False, sub_plan="5e")
    b, _ = _assemble(_norm(case_id="BBGB_2010-01-04", sec_id="BBGB",
                           pending=[{"field": "stock_ratio", "question": "final proration?"}]))
    cases = dt.parse_rows([a, b])
    lib = dt.LibraryRows.of(tables([sec("BBGA"), sec("BBGB")], contract_delistings=[contract_row("BBGA", exit_kind="merger", value_rule="cash",
                                                                      cash_per_share="9.000000")]))
    text = tb.review_markdown([a, b], dt.judge_all(cases, lib))
    assert "known_wrong" in text and "final proration?" in text and "cash_per_share" in text

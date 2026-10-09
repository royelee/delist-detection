from delist_detection.outputs.contract import (delisting_rows, id_change_rows, last_endings, security_history_rows,
                                       seed_rows)
from delist_detection.outputs.verdict import decide
from lifecycle_tables import ending, iv, obs, sec, tables


def _run_tables():
    return tables(
        [sec("A"), sec("B"), sec("C"), sec("D")],
        [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2015-03-03"), iv("C", "CCC", "2010-01-04"),
         iv("D", "DDD", "2010-01-04", "2018-06-29")],
        [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.000000",
                method="exchange_transfer_zero", successor="B", terminal_value="12.000000"),
         ending("C", "2019-03-20", "merger", ltd="2019-03-19", successor="C"),
         ending("D", "2009-12-01", "exchange_transfer", ltd="2009-11-20", dlret="0.000000",
                method="exchange_transfer_zero"),
         ending("D", "2018-07-09", ltd="2018-06-29", dlret="0.012000", source="last_sighting",
                terminal_value="20.000000")],
        [obs("AAA", "2012-06-29", "A"), obs("CCC", "2012-06-29", "C"), obs("DDD", "2012-06-29", "D")])


def test_one_row_per_ended_security_its_last_and_none_for_a_security_that_continues_itself():
    t = _run_tables()
    rows = {r["sec_id"]: r for r in delisting_rows(t, decide(t, {}))}
    assert set(rows) == {"A", "D"}
    assert set(last_endings(t.delistings)) == {"A", "D"}
    assert rows["D"]["dlret"] == "0.012000" and rows["D"]["last_trade_date"] == ""     # not an exchange print
    assert rows["D"]["verdict"] == "uncertain" and rows["D"]["terminal_value"] == "20.000000"


def test_a_continuation_names_its_successor_and_carries_no_value():
    t = _run_tables()
    a = {r["sec_id"]: r for r in delisting_rows(t, decide(t, {}))}["A"]
    assert (a["exit_kind"], a["continuation"], a["successor_sec_id"]) == ("exchange", True, "B")
    assert (a["dlret"], a["dlret_fill"], a["terminal_value"]) == ("", "", "")
    assert a["last_trade_date"] == "2015-03-02"


def test_an_unknown_bucket_ending_has_a_blank_exit_kind_and_an_uncertain_verdict():
    t = tables([sec("U")], [iv("U", "UUU", "2010-01-04", "2015-03-02")],
               [ending("U", "2015-03-10", "unknown", method="needs_last_trade")],
               [obs("UUU", "2012-06-29", "U")])
    (row,) = delisting_rows(t, decide(t, {}))
    assert row["exit_kind"] == "" and row["verdict"] == "uncertain"


def test_the_seed_echo_keeps_every_observation_with_its_sec_id_and_verdict():
    t = _run_tables()
    rows = seed_rows(t, decide(t, {}))
    assert [(r["ticker"], r["sec_id"]) for r in rows] == [("AAA", "A"), ("CCC", "C"), ("DDD", "D")]
    assert {r["verdict"] for r in rows} <= {"confirmed", "uncertain"}
    assert set(rows[0]) == {"ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id", "sec_id", "verdict"}


def test_security_history_splits_an_interval_where_the_issuer_changes():
    t = tables([sec("S", cik="310158"), sec("Q", cik="5")],
               [iv("S", "MRK", "2008-01-02"), iv("Q", "QQQ", "2010-01-04", "2012-01-03")])
    rows = security_history_rows(t, {"S": [("2008-01-16", "64978"), ("2009-11-04", "310158")]})
    s = [(r["issuer_id"], r["start_date"], r["end_date"]) for r in rows if r["sec_id"] == "S"]
    assert s == [("64978", "2008-01-02", "2009-11-03"), ("310158", "2009-11-04", "")]
    q = [r for r in rows if r["sec_id"] == "Q"]
    assert [(r["issuer_id"], r["start_date"], r["end_date"]) for r in q] == [("5", "2010-01-04", "2012-01-03")]
    assert q[0]["security_name"] == "Q" and q[0]["share_class"] == "COMMON"


def test_security_history_leaves_out_what_it_is_told_to():
    t = tables([sec("S"), sec("X", observed=False)], [iv("S", "AAA", "2010-01-04"), iv("X", "XXX", "2015-01-02")])
    assert {r["sec_id"] for r in security_history_rows(t, {}, leave_out={"X"})} == {"S"}


def _sec_row(sec_id, cik, source, share_class="COMMON"):
    return {"sec_id": sec_id, "issuer_cik": cik, "share_class": share_class, "name": sec_id, "security_type": "",
            "observed": "true", "figi_source": source}


def test_id_changes_name_the_figi_that_now_holds_a_placeholders_issuer_and_class():
    baseline = [_sec_row("CIK100-COMMON", "100", "placeholder"), _sec_row("CIK200-COMMON", "200", "placeholder"),
                _sec_row("CIK300-COMMON", "300", "placeholder"), _sec_row("BBG000OLD001", "400", "cusip")]
    now = [_sec_row("BBG000NEW100", "100", "cusip"), _sec_row("BBG000AAA200", "200", "cusip"),
           _sec_row("BBG000BBB200", "200", "ticker"), _sec_row("CIK300-COMMON", "300", "placeholder")]
    assert id_change_rows(baseline, now, "2026-09-25") == [
        {"old_sec_id": "CIK100-COMMON", "new_sec_id": "BBG000NEW100", "changed_on": "2026-09-25",
         "issuer_cik": "100", "share_class": "COMMON"}]
    assert id_change_rows([], now, "2026-09-25") == []


def test_delisting_rows_carry_the_payout_rule_columns_and_the_inputs_of_a_failed_gate():
    from delist_detection.terms.llm_merger_extractor import MergerTerms
    from delist_detection.outputs.dlret import MergerInputs
    from delist_detection.outputs.store import CONTRACT_DELISTINGS_COLUMNS, DelistingKey
    t = tables([sec("M")], [iv("M", "MMM", "2010-01-04", "2015-03-02")],
               [ending("M", "2015-03-10", ltd="2015-03-02", method="assumed_par", last_trade_close="10")],
               [obs("MMM", "2012-06-29", "M")])
    llm = MergerTerms("cash_and_stock", 65.5, 0.8025, None, "QSR", "high", "8-K:1", "")
    inputs = {DelistingKey("M", "2015-03-10"): MergerInputs(llm=llm, acquirer_sec_id="BBG0QSR")}
    (row,) = delisting_rows(t, decide(t, {}), inputs)
    assert set(row) == set(CONTRACT_DELISTINGS_COLUMNS)
    assert (row["value_rule"], row["terms_gate"], row["price_sec_id"], row["price_date"]) == (
        "cash_plus_stock", "failed", "BBG0QSR", "2015-03-03")


def test_delisting_rows_take_each_endings_distress_terms():
    """Sub-plan 5g: stage 9e's OTC symbol and plan ratio, keyed by the ending's DelistingKey."""
    from delist_detection.outputs.dlret import DistressTerms
    from delist_detection.outputs.store import DelistingKey
    t = tables([sec("H"), sec("S")], [iv("H", "HTZ", "2016-07-05", "2020-10-29"), iv("S", "SDRL", "2010-04-16",
                                                                                   "2018-07-02")],
               [ending("H", "2020-11-09", "liquidation", ltd="2020-10-29", method="shumway_nyse_amex",
                       crsp_code="470", ticker="HTZ"),
                ending("S", "2018-07-13", "liquidation", ltd="2018-07-02", method="shumway_nyse_amex",
                       crsp_code="470", ticker="SDRL")],
               [obs("HTZ", "2019-06-28", "H"), obs("SDRL", "2016-06-30", "S")])
    terms = {DelistingKey("H", "2020-11-09"): DistressTerms(otc_symbol="HTZGQ"),
             DelistingKey("S", "2018-07-13"): DistressTerms(plan_ratio="0.0037345", plan_ticker="SDRL",
                                                            plan_source="form25_notice")}
    rows = {r["sec_id"]: r for r in delisting_rows(t, decide(t, {}), distress=terms)}
    assert (rows["H"]["value_rule"], rows["H"]["price_ticker"]) == ("otc_print", "HTZGQ")
    assert (rows["S"]["value_rule"], rows["S"]["stock_ratio"], rows["S"]["price_ticker"]) == \
        ("stock", "0.0037345", "SDRL")


def test_id_changes_name_the_figi_a_line_follow_folded_a_placeholder_into():
    """Sub-plan 5a (FTR): CIK 20520 holds two FIGI lines, Frontier's and the post-bankruptcy FYBR, so the
    issuer-and-class rule names none; the line follow's own rename names the FIGI."""
    baseline = [_sec_row("CIK20520-COMMON", "20520", "placeholder")]
    now = [_sec_row("BBGFTR00001", "20520", "handoff"), _sec_row("BBG010MVVVW7", "20520", "cusip")]
    assert id_change_rows(baseline, now, "2026-09-25") == []
    assert id_change_rows(baseline, now, "2026-09-25", {"CIK20520-COMMON": "BBGFTR00001"}) == [
        {"old_sec_id": "CIK20520-COMMON", "new_sec_id": "BBGFTR00001", "changed_on": "2026-09-25",
         "issuer_cik": "20520", "share_class": "COMMON"}]
    assert id_change_rows(baseline, now, "2026-09-25", {"CIK20520-COMMON": "BBGGONE0001"}) == []


def test_id_changes_name_the_figi_a_rule_f_line_moved_a_baseline_figi_to():
    """Sub-plan 5h, rule F: Peabody's 2008-2016 line was BBG00GBV88T6 (the ticker tier's composite, the line that
    took BTU over later) and is BBG000FW00S1 now; a baseline FIGI the run no longer holds takes a row only by the
    line renames, and a FIGI the run still holds never does."""
    baseline = [_sec_row("BBG00GBV88T6", "1064728", "ticker"), _sec_row("BBG0KEEP0001", "9", "cusip")]
    now = [_sec_row("BBG000FW00S1", "1064728", "handoff"), _sec_row("BBG0KEEP0001", "9", "cusip")]
    renames = {"BBG00GBV88T6": "BBG000FW00S1", "BBG0KEEP0001": "BBG000FW00S1"}
    assert id_change_rows(baseline, now, "2026-10-04") == []
    assert id_change_rows(baseline, now, "2026-10-04", renames) == [
        {"old_sec_id": "BBG00GBV88T6", "new_sec_id": "BBG000FW00S1", "changed_on": "2026-10-04",
         "issuer_cik": "1064728", "share_class": "COMMON"}]

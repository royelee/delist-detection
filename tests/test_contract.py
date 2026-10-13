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
    # not an exchange print: published as the day the library holds (FB-020), and the verdict doubts it
    assert rows["D"]["dlret"] == "0.012000" and rows["D"]["last_trade_date"] == "2018-06-29"
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
         "issuer_cik": "100", "share_class": "COMMON", "kind": "rename"}]
    assert id_change_rows([], now, "2026-09-25") == []


def _hist_row(sec_id, issuer_id, start, share_class="COMMON"):
    return {"sec_id": sec_id, "issuer_id": issuer_id, "start_date": start, "end_date": "", "ticker": "T",
            "security_name": sec_id, "share_class": share_class}


def test_a_previous_runs_security_history_is_an_id_baseline():
    """FB-010: a contract-native baseline. One row per security, its latest interval's issuer (a placeholder with no
    issuer on any interval takes the CIK its id names), a placeholder known by its id."""
    from delist_detection.outputs.contract import baseline_of_history
    history = [_hist_row("CIK100-COMMON", "100", "2010-01-04"), _hist_row("CIK100-COMMON", "", "2012-01-03"),
               _hist_row("CIK300-CLASS-A", "", "2011-01-03", "CLASS A"),
               _hist_row("BBG000OLD001", "400", "2009-01-02"), _hist_row("BBG000OLD001", "401", "2013-01-02")]
    baseline = baseline_of_history(history)
    assert baseline == [
        {"sec_id": "BBG000OLD001", "issuer_cik": "401", "share_class": "COMMON", "figi_source": "figi"},
        {"sec_id": "CIK100-COMMON", "issuer_cik": "100", "share_class": "COMMON", "figi_source": "placeholder"},
        {"sec_id": "CIK300-CLASS-A", "issuer_cik": "300", "share_class": "CLASS A", "figi_source": "placeholder"}]
    now = [_sec_row("BBG000NEW100", "100", "cusip"), _sec_row("BBG000NEW300", "300", "cusip", "CLASS A")]
    assert [(r["old_sec_id"], r["new_sec_id"]) for r in id_change_rows(baseline, now, "2026-10-10")] == [
        ("CIK100-COMMON", "BBG000NEW100"), ("CIK300-CLASS-A", "BBG000NEW300")]


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
         "issuer_cik": "20520", "share_class": "COMMON", "kind": "rename"}]
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
         "issuer_cik": "1064728", "share_class": "COMMON", "kind": "rename"}]


# --- split rows (FB-005, FB-001's CHK): a baseline id whose days this run holds under other ids -----------------------


def _h(sec_id, ticker, start, end=""):
    return {"sec_id": sec_id, "issuer_id": "1", "start_date": start, "end_date": end, "ticker": ticker,
            "security_name": sec_id, "share_class": "COMMON"}


def _splits(baseline_rows, baseline_history, now_rows, history, renames={}):
    rows = id_change_rows(baseline_rows, now_rows, "2026-10-10", renames, baseline_history=baseline_history,
                          history=history)
    return [(r["old_sec_id"], r["new_sec_id"], r["kind"]) for r in rows]


LIBERTY_BASE = [_h("CIK1-COMMON", "LINTA", "2008-01-02", "2014-12-31"), _h("CIK1-COMMON", "QVCA", "2015-01-02", "2018-04-10"),
                _h("CIK1-COMMON", "LCAPA", "2008-01-02", "2014-12-31")]
LIBERTY_NOW = [_h("CIK1-COMMON-AAA", "LINTA", "2008-01-02", "2014-12-31"),
               _h("CIK1-COMMON-AAA", "QVCA", "2015-01-02", "2018-04-10"),
               _h("CIK1-COMMON-BBB", "LCAPA", "2008-01-02", "2014-12-31")]


def test_a_gone_baseline_id_held_by_two_ids_is_split_into_both():
    """Liberty: CIK1355096-COMMON's days are now two placeholders'. One row per new id, the old id repeated."""
    baseline = [_sec_row("CIK1-COMMON", "1", "placeholder")]
    now = [_sec_row("CIK1-COMMON-AAA", "1", "placeholder"), _sec_row("CIK1-COMMON-BBB", "1", "placeholder")]
    rows = id_change_rows(baseline, now, "2026-10-10", baseline_history=LIBERTY_BASE, history=LIBERTY_NOW)
    assert rows == [
        {"old_sec_id": "CIK1-COMMON", "new_sec_id": "CIK1-COMMON-AAA", "changed_on": "2026-10-10", "issuer_cik": "1",
         "share_class": "COMMON", "kind": "split"},
        {"old_sec_id": "CIK1-COMMON", "new_sec_id": "CIK1-COMMON-BBB", "changed_on": "2026-10-10", "issuer_cik": "1",
         "share_class": "COMMON", "kind": "split"}]


def test_a_kept_baseline_id_whose_part_another_id_holds_is_split():
    """CHK: BBG00Z6DX554 kept its 2020-2024 part; the 2007-2020 part is now the placeholder's."""
    base = [_h("BBGCHK", "CHK", "2007-12-17", "2024-10-02")]
    now_h = [_h("CIK9-COMMON", "CHK", "2007-12-17", "2020-06-26"), _h("BBGCHK", "CHK", "2020-06-27", "2024-10-02")]
    rows = [_sec_row("BBGCHK", "9", "cusip"), _sec_row("CIK9-COMMON", "9", "placeholder")]
    assert _splits([_sec_row("BBGCHK", "9", "cusip")], base, rows, now_h) == [("BBGCHK", "CIK9-COMMON", "split")]


def test_a_baseline_id_one_other_id_fully_took_over_is_a_rename_not_a_split():
    baseline = [_sec_row("CIK1-COMMON", "1", "placeholder")]
    now = [_sec_row("BBGNEW", "1", "cusip")]
    base_h = [_h("CIK1-COMMON", "AAA", "2008-01-02", "2014-12-31")]
    now_h = [_h("BBGNEW", "AAA", "2008-01-02", "2014-12-31")]
    assert _splits(baseline, base_h, now, now_h) == [("CIK1-COMMON", "BBGNEW", "rename")]


def test_a_split_baseline_id_gets_no_rename_row_too():
    baseline = [_sec_row("CIK1-COMMON", "1", "placeholder")]
    now = [_sec_row("CIK1-COMMON-AAA", "1", "placeholder"), _sec_row("CIK1-COMMON-BBB", "1", "placeholder"),
           _sec_row("BBGFIGI", "1", "cusip")]
    out = _splits(baseline, LIBERTY_BASE, now, LIBERTY_NOW, {"CIK1-COMMON": "BBGFIGI"})
    assert out == [("CIK1-COMMON", "CIK1-COMMON-AAA", "split"), ("CIK1-COMMON", "CIK1-COMMON-BBB", "split")]


def test_a_ticker_handed_over_at_a_range_edge_is_no_split():
    """Another id holds ten of B's days under the ticker (a range's edge moved): below the threshold."""
    base = [_h("BBGKEEP", "AAA", "2010-01-04", "2018-12-31")]
    now_h = [_h("BBGKEEP", "AAA", "2010-01-04", "2018-12-20"), _h("BBGNEXT", "AAA", "2018-12-21", "2019-12-31")]
    rows = [_sec_row("BBGKEEP", "1", "cusip"), _sec_row("BBGNEXT", "2", "cusip")]
    assert _splits([_sec_row("BBGKEEP", "1", "cusip")], base, rows, now_h) == []


def test_another_ticker_or_no_baseline_history_gives_no_split():
    baseline = [_sec_row("CIK1-COMMON", "1", "placeholder")]
    now = [_sec_row("CIK1-COMMON-AAA", "1", "placeholder"), _sec_row("CIK1-COMMON-BBB", "1", "placeholder")]
    assert _splits(baseline, [], now, LIBERTY_NOW) == []
    elsewhere = [_h("CIK1-COMMON-AAA", "ZZZ", "2008-01-02", "2018-04-10"), _h("CIK1-COMMON-BBB", "YYY", "2008-01-02", "2018-04-10")]
    assert _splits(baseline, LIBERTY_BASE, now, elsewhere) == []

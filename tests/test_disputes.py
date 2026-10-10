"""disputes.csv (FB-011): one row per checked field a truth case of the config fails on the run."""
from delist_detection.measurement import diagnosis_truth as dt
from delist_detection.measurement.disputes import dispute_rows
from delist_detection.measurement.scorecard import ScorecardConfig
from delist_detection.measurement.truth import TruthCase
from delist_detection.outputs import store
from diagnosis_rows import truth_row
from lifecycle_tables import contract_row, ending, hist, iv, obs, sec, tables


def _case(case, status="", group="golden", **cells):
    return TruthCase(case_id=case, group=group, ticker=cells.pop("ticker", "AAA"), on=cells.pop("on", "2010-06-30"),
                     status=status, fixed_by="reset-4a" if status == "known_wrong" else "", **cells)


def _run():
    return tables([sec("A"), sec("Z")], [iv("A", "AAA", "2010-01-04", "2016-05-18")],
                  [ending("A", "2016-05-18", ltd="2016-05-18")], [obs("AAA", "2010-06-30", "A")],
                  contract_delistings=[contract_row("A", exit_kind="merger", last_trade_date="2016-05-18")],
                  security_history=[hist("A", "100", "2010-01-04", "2016-05-18")])


def _config(**kw):
    return ScorecardConfig(golden_name="golden_lifecycles.csv", audit_name="accuracy_audit.csv",
                           diagnosis_name="diagnosis_truth.csv", **kw)


def test_each_failing_case_of_each_truth_file_gives_a_row_and_a_fixed_case_none():
    diagnosis = dt.parse_rows([
        truth_row("D1", "A", status="known_wrong", fixed_by="5x", exit_kind="liquidation"),
        truth_row("D2", "A", exit_kind="merger"),                                  # fixed: no row
        truth_row("D3", "NOPE", exit_kind="merger")])                              # the run lacks it: blank sec_id
    config = _config(
        golden=[_case("g-bad", "pass", exit_kind="liquidation"), _case("g-ok", "pass", exit_kind="merger")],
        audit=[_case("a-bad", group="random", exit_kind="liquidation", final_last_trade_date="2016-05-17"),
               _case("a-pending", group="random")],
        diagnosis=diagnosis)
    rows = dispute_rows(_run(), config)
    assert [(r["sec_id"], r["truth_file"], r["case"], r["field"], r["truth"], r["library"], r["last_trade_date"])
            for r in rows] == [
        ("", "diagnosis_truth.csv", "D3", "sec_id", "NOPE", "(not in the run)", ""),
        ("A", "accuracy_audit.csv", "a-bad", "exit_kind", "liquidation", "merger", "2016-05-18"),
        ("A", "accuracy_audit.csv", "a-bad", "last_trade_date", "2016-05-17", "2016-05-18", "2016-05-18"),
        ("A", "diagnosis_truth.csv", "D1", "exit_kind", "liquidation", "merger", "2016-05-18"),
        ("A", "golden_lifecycles.csv", "g-bad", "exit_kind", "liquidation", "merger", "2016-05-18")]
    assert list(rows[0]) == list(store.DISPUTES_COLUMNS)


def test_a_case_whose_security_the_judge_finds_keeps_its_row_with_a_blank_sec_id():
    config = _config(golden=[_case("g-none", "pass", ticker="ZZZ", exit_kind="merger")])
    rows = dispute_rows(_run(), config)
    assert [(r["sec_id"], r["last_trade_date"], r["case"], r["field"]) for r in rows] == [("", "", "g-none", "security")]


def test_nothing_disputed_is_an_empty_list_that_writes_a_header(tmp_path):
    config = _config(golden=[_case("g-ok", "pass", exit_kind="merger")])
    assert dispute_rows(_run(), config) == [] == dispute_rows(_run(), ScorecardConfig())
    store.write_tables(tmp_path, {"disputes": []})
    assert (tmp_path / "disputes.csv").read_text() == ",".join(store.DISPUTES_COLUMNS) + "\n"

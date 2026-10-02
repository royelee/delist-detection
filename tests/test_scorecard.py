import json
from datetime import date

import pytest

from delist_detection import scorecard as sc
from delist_detection.scorecard import ScorecardConfig, ScorecardConfigError, Window
from delist_detection.truth import TRUTH_COLUMNS, TruthCase
from tests.lifecycle_tables import ending, iv, obs, review, sec, tables

AS_OF = date(2026, 9, 25)


def _tables():
    """A: merger, complete. B: transfer with no successor (left view). C: active, ticker-only FIGI.
    D: liquidation with a blank dlret and a conflicting date. E: placeholder, merger with no last trade date.
    F: a FIGI security with no CIK, active."""
    return tables(
        [sec("A"), sec("B"), sec("C", figi_source="ticker"), sec("D"), sec("CIK5-COMMON", cik="5", figi_source="placeholder"),
         sec("F", cik="")],
        [iv("A", "AAA", "2008-01-02", "2012-03-01"), iv("B", "BBB", "2008-01-02", "2010-05-03"),
         iv("C", "CCC", "2008-01-02"), iv("D", "DDD", "2008-01-02", "2025-02-03"),
         iv("CIK5-COMMON", "EEE", "2008-01-02", "2016-04-01"), iv("F", "FFF", "2008-01-02")],
        [ending("A", "2012-03-10", ltd="2012-03-01", dlret="0.02"),
         ending("B", "2010-05-10", "exchange_transfer", ltd="2010-05-03", dlret="0.0",
                method="exchange_transfer_zero", reason="Continued 10-K/Q filings >180d after delist"),
         ending("D", "2025-02-10", "liquidation", ltd="2025-02-03", method="unknown",
                flags="last_trade_date_conflict"),
         ending("CIK5-COMMON", "2016-04-10", method="needs_last_trade")],
        [obs("AAA", "2010-06-30", "A"), obs("BBB", "2009-06-30", "B"), obs("CCC", "2010-06-30", "C"),
         obs("DDD", "2010-06-30", "D"), obs("EEE", "2010-06-30", "CIK5-COMMON"), obs("FFF", "2010-06-30", "F"),
         obs("FFF", "2011-06-30", "F", "backfilled_ticker"), obs("GGG", "2010-06-30", "", "unresolved")],
        [review("B"), review("B", "successor_unknown"), review("D")])


def test_build_counts_the_lifecycle_identity_and_ending_lines():
    m = sc.build(_tables(), as_of=AS_OF)["metrics"]
    assert {k: m[k] for k in ("L1.tickers", "L1.tickers_covered", "L1.securities", "L1.securities_covered",
                              "L1.left_view", "L1.ended_incomplete", "L1.no_mapped_sighting")} == {
        "L1.tickers": 7, "L1.tickers_covered": 3, "L1.securities": 6, "L1.securities_covered": 3,
        "L1.left_view": 1, "L1.ended_incomplete": 2, "L1.no_mapped_sighting": 1}
    assert m["L1.coverage_tickers"] == round(3 / 7, 6)
    assert (m["L2.high"], m["L2.medium"], m["L2.low"]) == (2, 1, 0)       # C: a ticker-only FIGI
    assert (m["R1.1.sightings"], m["R1.1.mapped"], m["R1.1.status.backfilled_ticker"]) == (8, 6, 1)
    assert (m["R1.2.cusip"], m["R1.2.ticker_only"], m["R1.2.placeholder"], m["R1.2.figi_without_cik"]) == (4, 1, 1, 1)
    assert (m["R1.3.transfer_no_successor"], m["R1.4.review_rows"], m["R1.4.review_securities"]) == (1, 3, 2)
    assert (m["R2.endings"], m["R2.1.missing_last_trade_date"], m["R2.2.continued_filings_rule"]) == (4, 1, 1)
    assert (m["R2.5.distress"], m["R2.5.distress_blank_dlret"], m["R2.6.distress_date_flagged"]) == (1, 1, 1)


def test_window_lines_appear_only_with_a_window():
    assert "R2.3.blank_dlret_in_window" not in sc.build(_tables(), as_of=AS_OF)["metrics"]
    m = sc.build(_tables(), as_of=AS_OF, config=ScorecardConfig(window=Window("2006-01-02", "2024-12-29")))["metrics"]
    assert (m["R2.3.blank_dlret_in_window"], m["R2.3.blank_needs_last_close_in_window"],
            m["R2.3.blank_no_value_in_window"], m["R2.1.missing_last_trade_date_in_window"]) == (1, 1, 0, 1)


def test_empty_tables_give_zero_shares():
    m = sc.build(tables(), as_of=AS_OF)["metrics"]
    assert m["L1.coverage_tickers"] == 0.0 and m["R1.1.mapped_share"] == 0.0 and m["L2.high_share"] == 0.0


def _case(case, status="", group="golden", **cells):
    return TruthCase(case=case, group=group, ticker=cells.pop("ticker", "AAA"), on=cells.pop("on", "2010-06-30"),
                     status=status, fixed_by="reset-4a" if status == "known_wrong" else "", **cells)


def test_golden_and_audit_lines():
    config = ScorecardConfig(
        golden=[_case("ok", "pass", exit_kind="merger"), _case("bad", "pass", exit_kind="liquidation"),
                _case("kw", "known_wrong", ticker="BBB", on="2009-06-30", exit_kind="merger")],
        audit=[_case("r1", group="random", exit_kind="merger"), _case("r2", group="random", exit_kind="liquidation"),
               _case("c1", group="census:left_view", ticker="BBB", on="2009-06-30", exit_kind="merger"),
               _case("p1", group="random")])
    card = sc.build(_tables(), as_of=AS_OF, config=config)
    m = card["metrics"]
    assert (m["G.cases"], m["G.pass"], m["G.pass_failing"], m["G.known_wrong"], m["G.known_wrong_now_right"]) == (
        3, 1, 1, 1, 0)
    assert card["golden_failures"] == ["bad: exit_kind merger != liquidation"]
    assert (m["A.pending"], m["A.random.n"], m["A.random.errors"]) == (1, 2, 1)
    assert (m["A.census.left_view.n"], m["A.census.left_view.errors"], m["A.census.distress.n"]) == (1, 1, 0)
    assert 0.5 < m["A.random.upper95"] < 1.0


def test_drops_reports_a_bad_move_and_a_missing_metric():
    card = {"metrics": {"L1.coverage_tickers": 0.88, "R2.4.assumed_par": 59}}
    assert sc.drops(card, {"L1.coverage_tickers": 0.88, "R2.4.assumed_par": 59}) == []
    assert sc.drops(card, {"L1.coverage_tickers": 0.9, "R2.4.assumed_par": 58, "G.pass": 27}) == [
        "G.pass: 27 -> None", "L1.coverage_tickers: 0.9 -> 0.88", "R2.4.assumed_par: 58 -> 59"]


def test_raise_floor_moves_only_the_good_way_and_adds_new_metrics():
    card = {"metrics": {"L1.coverage_tickers": 0.95, "R2.4.assumed_par": 70, "G.pass": 30, "L1.tickers": 9}}
    floor = sc.raise_floor(card, {"L1.coverage_tickers": 0.9, "R2.4.assumed_par": 59})
    assert floor == {"G.pass": 30, "L1.coverage_tickers": 0.95, "R2.4.assumed_par": 59}   # L1.tickers is not floored


def _config(tmp_path, raw, golden_rows=None):
    path = tmp_path / "scorecard.json"
    path.write_text(json.dumps(raw))
    if golden_rows is not None:
        (tmp_path / "golden.csv").write_text(",".join(TRUTH_COLUMNS) + "\n" + "".join(golden_rows))
    return path


def test_load_config_reads_the_window_floor_and_truth_files(tmp_path):
    row = "AAA,golden,AAA,2010-06-30,,,,,merger,,,,,pass,,,,\n"
    cfg = sc.load_config(_config(tmp_path, {"window": {"start": "2006-01-02", "end": "2024-12-29"},
                                            "floor": {"G.pass": 1}, "golden": "golden.csv",
                                            "audit": "audit.csv"}, [row]))
    assert cfg.window == Window("2006-01-02", "2024-12-29") and cfg.floor == {"G.pass": 1}
    assert [c.case for c in cfg.golden] == ["AAA"] and cfg.audit == []        # a missing audit file: no cases


@pytest.mark.parametrize("raw, says", [
    ({"windw": None}, "unknown key"), ({"window": {"start": "2006-01-02"}}, "window needs"),
    ({"window": {"start": "2024-01-02", "end": "2006-01-02"}}, "starts after"),
    ({"floor": {"L1.tickers": 5}}, "floor entries"), ({"floor": {"G.pass": "many"}}, "floor entries"),
    ([1, 2], "not an object"), ({"floor": [1]}, "floor must be"), ({"floor": {"G.pass": True}}, "floor entries"),
    ({"window": [1]}, "window must be")])
def test_load_config_refuses_a_bad_file(tmp_path, raw, says):
    with pytest.raises(ScorecardConfigError, match=says):
        sc.load_config(_config(tmp_path, raw))


def test_load_config_refuses_a_file_that_is_not_utf8(tmp_path):
    (tmp_path / "scorecard.json").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ScorecardConfigError, match="not JSON"):
        sc.load_config(tmp_path / "scorecard.json")


def test_load_config_refuses_text_that_is_not_json(tmp_path):
    (tmp_path / "scorecard.json").write_text("{window")
    with pytest.raises(ScorecardConfigError, match="not JSON"):
        sc.load_config(tmp_path / "scorecard.json")


def test_write_puts_sorted_json_next_to_the_tables(tmp_path):
    path = sc.write(tmp_path, {"metrics": {"b": 1, "a": 2}, "as_of": "2026-09-25"})
    assert path.name == "scorecard.json" and json.loads(path.read_text())["metrics"] == {"a": 2, "b": 1}
    assert path.read_text().index('"a"') < path.read_text().index('"b"')

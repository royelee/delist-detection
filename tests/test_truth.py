import csv

import pytest

from delist_detection.lifecycle import LifecycleView
from delist_detection.truth import (TRUTH_COLUMNS, TruthCase, TruthFileError, clopper_pearson_upper, judge,
                                    load_truth)
from tests.lifecycle_tables import ending, iv, obs, sec, tables


def _write(path, rows, header=TRUTH_COLUMNS, bom=False):
    with path.open("w", newline="", encoding="utf-8-sig" if bom else "utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(c, "") for c in header])
    return path


GOOD = dict(case="AAA", group="golden", ticker="AAA", on="2012-06-29", issuer_cik="0000100", tickers="AAA;BBB",
            terminal="ended", ends_after="2014-01-01", exit_kind="merger", last_trade_date="2015-03-02",
            dlret="0.01", dlret_tol="0.001", successor_ticker="BBB", status="known_wrong", fixed_by="reset-4a",
            source="https://www.sec.gov/x", library_says="whatever", note="n")


def test_load_truth_reads_every_field_and_a_bom(tmp_path):
    (case,) = load_truth(_write(tmp_path / "t.csv", [GOOD], bom=True))
    assert case == TruthCase(case="AAA", group="golden", ticker="AAA", on="2012-06-29", issuer_cik="100",
                             tickers=("AAA", "BBB"), terminal="ended", ends_after="2014-01-01", exit_kind="merger",
                             last_trade_date="2015-03-02", dlret=0.01, dlret_tol=0.001, successor_ticker="BBB",
                             status="known_wrong", fixed_by="reset-4a", source="https://www.sec.gov/x")


@pytest.mark.parametrize("change", [
    dict(case=""), dict(ticker=""), dict(on=""), dict(on="2012-13-01"), dict(ends_after="soon"),
    dict(dlret="ten"), dict(dlret_tol="x"), dict(terminal="gone"), dict(exit_kind="bankrupt"),
    dict(status="maybe"), dict(fixed_by=""),
    dict(issuer_cik="", tickers="", terminal="", ends_after="", exit_kind="", last_trade_date="", dlret="",
         successor_ticker=""),
])
def test_load_truth_refuses_a_bad_row_naming_its_line(tmp_path, change):
    with pytest.raises(TruthFileError, match=r"t\.csv:2"):
        load_truth(_write(tmp_path / "t.csv", [{**GOOD, **change}]))


def test_load_truth_refuses_a_repeated_case_and_a_wrong_header(tmp_path):
    with pytest.raises(TruthFileError, match=r"t\.csv:3"):
        load_truth(_write(tmp_path / "t.csv", [GOOD, GOOD]))
    with pytest.raises(TruthFileError, match="columns"):
        load_truth(_write(tmp_path / "h.csv", [GOOD], header=TRUTH_COLUMNS[:-1]))


def test_an_unfilled_audit_row_loads_as_pending_only_when_allowed(tmp_path):
    row = dict(case="random:AAA", group="random", ticker="AAA", on="2012-06-29", library_says="active")
    path = _write(tmp_path / "a.csv", [row])
    with pytest.raises(TruthFileError, match="checks nothing"):
        load_truth(path)
    (case,) = load_truth(path, allow_pending=True)
    assert case.pending


def _view():
    t = tables([sec("A", cik="100"), sec("B", cik="200", observed=False), sec("C", cik="300")],
               [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2015-03-03", "2018-06-29"),
                iv("C", "CCC", "2010-01-04")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0", successor="B"),
                ending("B", "2018-07-09", ltd="2018-06-29", dlret="0.012")],
               [obs("AAA", "2012-06-29", "A")])
    return LifecycleView(t)


def _case(**cells):
    return TruthCase(**{"case": "c", "group": "golden", "ticker": "AAA", "on": "2012-06-29", **cells})


def test_judge_passes_when_every_checked_field_agrees():
    case = _case(issuer_cik="100", tickers=("AAA", "BBB"), terminal="ended", ends_after="2018-01-02",
                 exit_kind="merger", last_trade_date="2018-06-29", dlret=0.01, dlret_tol=0.005,
                 successor_ticker="BBB")
    assert judge(case, _view()).mismatches == ()


@pytest.mark.parametrize("cells, says", [
    (dict(issuer_cik="999"), "issuer_cik 100 != 999"),
    (dict(tickers=("AAA", "ZZZ")), "tickers missing ZZZ"),
    (dict(terminal="active"), "terminal ended != active"),
    (dict(ends_after="2018-06-29"), "ends 2018-06-29, on or before 2018-06-29"),
    (dict(exit_kind="liquidation"), "exit_kind merger != liquidation"),
    (dict(last_trade_date="2018-06-28"), "last_trade_date 2018-06-29 != 2018-06-28"),
    (dict(dlret=0.05), "dlret 0.012 != 0.05 +/- 0.005"),
    (dict(successor_ticker="AAA"), "no successor traded AAA"),
])
def test_judge_names_each_field_that_disagrees(cells, says):
    assert judge(_case(**cells), _view()).mismatches == (says,)


def test_judge_reports_a_ticker_no_single_security_traded_that_day():
    j = judge(_case(ticker="AAA", on="2001-01-02", issuer_cik="100"), _view())
    assert not j.ok and j.mismatches == ("no single security traded AAA on 2001-01-02",)


def test_an_active_lifecycle_never_fails_ends_after_but_has_no_final_ending():
    view = _view()
    assert judge(_case(ticker="CCC", on="2012-06-29", ends_after="2030-01-01"), view).ok
    assert judge(_case(ticker="CCC", on="2012-06-29", exit_kind="merger"), view).mismatches == (
        "no final ending (active)",)


def test_clopper_pearson_upper_bound():
    assert clopper_pearson_upper(0, 100) == pytest.approx(0.0295, abs=1e-4)      # 1 - 0.05 ** (1/100)
    assert clopper_pearson_upper(1, 100) == pytest.approx(0.0466, abs=1e-4)
    assert clopper_pearson_upper(0, 0) == 1.0 and clopper_pearson_upper(5, 5) == 1.0
    assert clopper_pearson_upper(0, 300) < clopper_pearson_upper(0, 100) < clopper_pearson_upper(1, 100)

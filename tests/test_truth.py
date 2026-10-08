"""truth: what every truth set shares (the statuses and their rule, the error, the judgement and its tally, the flip
rule, the note convention), and the golden and audit set's format and judge."""
import csv
import shutil
from pathlib import Path

import pytest

from delist_detection import diagnosis_truth as dt
from delist_detection import truth
from delist_detection.lifecycle import LifecycleView
from delist_detection.run_snapshot import RunSnapshot
from delist_detection.truth import (TRUTH_COLUMNS, Judgement, Mismatch, TruthCase, TruthFileError,
                                    clopper_pearson_upper, judge, load_truth, now_right, tally, write_truth)
from delist_detection.truth_set import TruthSet, changes_path, configured, legs_path
from tests.diagnosis_rows import truth_row
from tests.lifecycle_tables import contract_row, ending, hist, iv, obs, sec, tables

ROOT = Path(__file__).resolve().parents[1]


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
    assert case == TruthCase(case_id="AAA", group="golden", ticker="AAA", on="2012-06-29", issuer_cik="100",
                             tickers=("AAA", "BBB"), terminal="ended", ends_after="2014-01-01", exit_kind="merger",
                             final_last_trade_date="2015-03-02", dlret=0.01, dlret_tol=0.001,
                             successor_ticker="BBB", status="known_wrong", fixed_by="reset-4a",
                             source="https://www.sec.gov/x")


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


# -- what every truth set shares -------------------------------------------------------------------------------------
@pytest.mark.parametrize("status, fixed_by, refused", [
    ("maybe", "", "status 'maybe' is not one of"),
    ("known_wrong", "", "a known_wrong case needs fixed_by"),
    ("known_wrong", " ", "a known_wrong case needs fixed_by"),
])
def test_both_sets_refuse_a_bad_status_by_one_rule_and_one_error(tmp_path, status, fixed_by, refused):
    with pytest.raises(TruthFileError, match=rf"t\.csv:2: {refused}"):
        load_truth(_write(tmp_path / "t.csv", [{**GOOD, "status": status, "fixed_by": fixed_by}]))
    with pytest.raises(TruthFileError, match=rf"rows:2: {refused}"):
        dt.parse_rows([truth_row("S1_2010-01-04", "S1", status=status, fixed_by=fixed_by)])


def test_pass_and_known_wrong_are_every_sets_and_ruling_pending_the_diagnosis_sets_own(tmp_path):
    for status in (truth.PASS, truth.KNOWN_WRONG):
        assert [c.status for c in dt.parse_rows([truth_row("S1_2010-01-04", "S1", status=status, fixed_by="5a")])] \
            == [status]
        assert [c.status for c in load_truth(_write(tmp_path / "t.csv", [{**GOOD, "status": status}]))] == [status]
    assert dt.parse_rows([truth_row("S1_2010-01-04", "S1", status=dt.RULING_PENDING)])[0].status == dt.RULING_PENDING
    with pytest.raises(TruthFileError, match="status 'ruling_pending'"):
        load_truth(_write(tmp_path / "t.csv", [{**GOOD, "status": dt.RULING_PENDING}]))


def test_an_empty_note_takes_the_text_alone():
    assert truth.noted("", "a: b") == "a: b" and truth.noted("x", "a: b") == "x; a: b"


def test_a_mismatch_reads_field_library_and_truth_unless_its_judge_words_it():
    assert str(Mismatch("c", "exit_kind", "merger", "")) == "exit_kind (blank) != merger"
    assert str(Mismatch("c", "cash_currency", "", "USD")) == "cash_currency USD != (blank)"
    assert str(Mismatch("c", "tickers", "AAA;ZZZ", "AAA", "tickers missing ZZZ")) == "tickers missing ZZZ"
    j = Judgement(_case(), (Mismatch("c", "terminal", "active", "ended"), Mismatch("c", "dlret", "0.1", "")))
    assert not j.ok and j.case_id == "c" and str(j) == "c: terminal ended != active; dlret (blank) != 0.1"
    assert Judgement(_case(), ()).ok


def _judged(case_id, status, *fields):
    case = TruthCase(case_id=case_id, group="golden", ticker="AAA", on="2012-06-29", status=status,
                     fixed_by="5a" if status == truth.KNOWN_WRONG else "")
    return Judgement(case, tuple(Mismatch(case_id, f, "t", "l") for f in fields))


def test_a_tally_counts_statuses_holding_cases_failures_and_fields():
    judged = [_judged("ok", "pass"), _judged("bad", "pass", "exit_kind", "dlret"), _judged("kw", "known_wrong"),
              _judged("kw2", "known_wrong", "exit_kind"), _judged("audit", "", "terminal"), _judged("audit2", "")]
    t = tally(judged)
    assert (t.cases, t.matching, t.errors, t.passing, t.pass_failing, t.known_wrong, t.now_right) == (
        6, 3, 3, 1, 1, 2, 1)
    assert t.fields == {"exit_kind": 2, "dlret": 1, "terminal": 1} and t.mismatches == 4
    assert t.failures == ("bad: exit_kind l != t; dlret l != t",)
    assert tally([]).cases == 0 and tally([]).failures == ()


def test_a_tally_counts_a_field_under_its_sets_key():
    judged = [_judged("a", "pass", "leg1.ratio", "leg2.price_ticker", "value_rule")]
    assert tally(judged, key=dt.field_key).fields == {"legs": 2, "value_rule": 1}
    assert tally(judged).fields == {"leg1.ratio": 1, "leg2.price_ticker": 1, "value_rule": 1}


def test_one_tally_reads_the_judgements_of_both_judges():
    golden = judge(_case(exit_kind="liquidation", status="pass"), _view())
    case = dt.parse_rows([truth_row("S1_2010-01-04", "S1", status="known_wrong", fixed_by="5a",
                                    exit_kind="merger")])[0]
    diagnosis = dt.judge_case(case, dt.LibraryRows.of(tables([sec("S1")], contract_delistings=[
        contract_row("S1", exit_kind="merger")])))
    t = tally([golden, diagnosis])
    assert (t.cases, t.pass_failing, t.now_right) == (2, 1, 1)
    assert t.failures == ("c: exit_kind merger != liquidation",)


def test_the_flip_rule_names_each_known_wrong_case_that_now_holds_in_order():
    judged = [_judged("b", "known_wrong"), _judged("a", "pass"), _judged("c", "known_wrong", "x"),
              _judged("a2", "known_wrong")]
    assert now_right(judged) == ["b", "a2"] and tally(judged).now_right == 2


# -- the flip rule on a golden file ----------------------------------------------------------------------------------
def _golden(path, *rows):
    write_truth(path, [{**dict.fromkeys(TRUTH_COLUMNS, ""), "group": "golden", "ticker": "AAA", "on": "2012-06-29",
                        **r} for r in rows])
    return path


def test_the_golden_flip_moves_each_known_wrong_case_the_run_now_matches_to_pass(tmp_path):
    path = _golden(tmp_path / "golden.csv",
                   dict(case="right", exit_kind="merger", status="known_wrong", fixed_by="reset-4a", note="n"),
                   dict(case="wrong", exit_kind="liquidation", status="known_wrong", fixed_by="reset-4b"),
                   dict(case="held", exit_kind="merger", status="pass", note="kept"))
    before = path.read_text().splitlines()
    assert truth.flip(path, _view()) == ["right"]
    after = path.read_text().splitlines()
    assert after[0] == before[0] and after[2:] == before[2:]          # only the flipped row's line changed
    [row] = [r for r in csv.DictReader(path.open()) if r["case"] == "right"]
    assert (row["status"], row["fixed_by"], row["note"]) == (
        "pass", "", "n; the library now matches, was known_wrong until reset-4a")
    flipped = path.read_bytes()
    assert truth.flip(path, _view()) == [] and path.read_bytes() == flipped
    assert [c.status for c in load_truth(path)] == ["pass", "known_wrong", "pass"]


def test_the_golden_flip_writes_nothing_when_no_case_flips(tmp_path, monkeypatch):
    path = _golden(tmp_path / "golden.csv", dict(case="wrong", exit_kind="liquidation", status="known_wrong",
                                                 fixed_by="reset-4b"))
    monkeypatch.setattr(truth, "write_truth", lambda *_: pytest.fail("rewrote a file in which nothing flipped"))
    assert truth.flip(path, _view()) == []


def test_the_flip_rule_on_copies_of_both_real_sets_against_the_committed_tables_flips_nothing(tmp_path):
    """Every known_wrong case of both sets is a strict xfail against output/ (tests/test_golden_lifecycles.py,
    tests/test_diagnosis_truth_cases.py), so the one flip rule moves none of them, and neither copy is rewritten."""
    run = RunSnapshot.read(ROOT / "output")
    golden = tmp_path / "golden_lifecycles.csv"
    shutil.copyfile(ROOT / "data" / "golden_lifecycles.csv", golden)
    real = configured(ROOT)
    copy = tmp_path / real.name
    for src, dst in ((real, copy), (legs_path(real), legs_path(copy)), (changes_path(real), changes_path(copy))):
        shutil.copyfile(src, dst)
    files = {p: p.read_bytes() for p in tmp_path.iterdir()}
    assert truth.flip(golden, LifecycleView(run)) == []
    ts = TruthSet.open(copy)
    assert ts.flip(dt.LibraryRows.of(run)) == 0 and ts.commit() == []
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == files


# -- the golden judge ------------------------------------------------------------------------------------------------
def _view():
    t = tables([sec("A", cik="100"), sec("B", cik="200", observed=False), sec("C", cik="300")],
               [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2015-03-03", "2018-06-29"),
                iv("C", "CCC", "2010-01-04")],
               [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.0", successor="B"),
                ending("B", "2018-07-09", ltd="2018-06-29", dlret="0.012")],
               [obs("AAA", "2012-06-29", "A")])
    return LifecycleView(t)


def _case(**cells):
    return TruthCase(**{"case_id": "c", "group": "golden", "ticker": "AAA", "on": "2012-06-29", **cells})


def _says(j):
    return tuple(map(str, j.mismatches))


def test_judge_passes_when_every_checked_field_agrees():
    case = _case(issuer_cik="100", tickers=("AAA", "BBB"), terminal="ended", ends_after="2018-01-02",
                 exit_kind="merger", final_last_trade_date="2018-06-29", dlret=0.01, dlret_tol=0.005,
                 successor_ticker="BBB")
    assert judge(case, _view()).mismatches == ()


def test_a_lifecycle_ending_on_its_ends_after_day_passes():
    """Operator ruling 2026-10-04: ends_after means the lifecycle must not end *before* the day. The audit puts the
    true last trade there (FMD 2016-08-22), so a lifecycle that ends exactly then is right."""
    assert judge(_case(ends_after="2018-06-29"), _view()).mismatches == ()


def test_judge_reads_a_bankruptcy_as_dropped():
    t = tables([sec("S", cik="100")], [iv("S", "AAA", "2010-01-04", "2020-05-01")],
               [ending("S", "2020-05-11", "liquidation", ltd="2020-05-01", dlret="-0.550000",
                       method="shumway_nasdaq", crsp_code="470")],
               [obs("AAA", "2012-06-29", "S")])
    assert judge(_case(exit_kind="dropped"), LifecycleView(t)).mismatches == ()
    assert _says(judge(_case(exit_kind="liquidation"), LifecycleView(t))) == ("exit_kind dropped != liquidation",)


@pytest.mark.parametrize("cells, field, says", [
    (dict(issuer_cik="999"), "issuer_cik", "issuer_cik 100 != 999"),
    (dict(tickers=("AAA", "ZZZ")), "tickers", "tickers missing ZZZ"),
    (dict(terminal="active"), "terminal", "terminal ended != active"),
    (dict(ends_after="2018-07-02"), "ends_after", "ends 2018-06-29, before 2018-07-02"),
    (dict(exit_kind="liquidation"), "exit_kind", "exit_kind merger != liquidation"),
    (dict(final_last_trade_date="2018-06-28"), "last_trade_date", "last_trade_date 2018-06-29 != 2018-06-28"),
    (dict(dlret=0.05), "dlret", "dlret 0.012 != 0.05 +/- 0.005"),
    (dict(successor_ticker="AAA"), "successor_ticker", "no successor traded AAA"),
])
def test_judge_names_each_field_that_disagrees(cells, field, says):
    j = judge(_case(**cells), _view())
    assert [(m.case_id, m.field, str(m)) for m in j.mismatches] == [("c", field, says)]


def test_the_golden_last_trade_date_is_the_final_endings_internal_day():
    """The golden column reads delistings.csv's last_trade_date of the chain's final ending (B's, the successor's),
    not the security's own ending (A's 2015-03-02) and not a contract row."""
    assert judge(_case(final_last_trade_date="2018-06-29"), _view()).ok
    [m] = judge(_case(final_last_trade_date="2015-03-02"), _view()).mismatches
    assert (m.field, m.truth, m.library) == ("last_trade_date", "2015-03-02", "2018-06-29")


def test_judge_reports_a_ticker_no_single_security_traded_that_day():
    j = judge(_case(ticker="AAA", on="2001-01-02", issuer_cik="100"), _view())
    assert not j.ok and _says(j) == ("no single security traded AAA on 2001-01-02",)
    assert j.mismatches[0].field == "security"


def test_an_active_lifecycle_never_fails_ends_after_but_has_no_final_ending():
    view = _view()
    assert judge(_case(ticker="CCC", on="2012-06-29", ends_after="2030-01-01"), view).ok
    j = judge(_case(ticker="CCC", on="2012-06-29", exit_kind="merger"), view)
    assert _says(j) == ("no final ending (active)",) and j.mismatches[0].field == "ending"


def test_clopper_pearson_upper_bound():
    assert clopper_pearson_upper(0, 100) == pytest.approx(0.0295, abs=1e-4)      # 1 - 0.05 ** (1/100)
    assert clopper_pearson_upper(1, 100) == pytest.approx(0.0466, abs=1e-4)
    assert clopper_pearson_upper(0, 0) == 1.0 and clopper_pearson_upper(5, 5) == 1.0
    assert clopper_pearson_upper(0, 300) < clopper_pearson_upper(0, 100) < clopper_pearson_upper(1, 100)


def test_write_truth_accepts_a_str_path(tmp_path):
    write_truth(str(tmp_path / "t.csv"), [GOOD])
    assert load_truth(tmp_path / "t.csv", allow_pending=True) == load_truth(_write(tmp_path / "s.csv", [GOOD]))


def test_judge_checks_the_issuer_in_force_on_the_case_date():
    t = tables([sec("S", cik="310158")], [iv("S", "AAA", "2008-01-02")], [], [obs("AAA", "2008-06-30", "S")],
               security_history=[hist("S", "64978", "2008-01-02", "2009-11-03"),
                                 hist("S", "310158", "2009-11-04")])
    assert judge(_case(on="2008-06-30", issuer_cik="64978"), LifecycleView(t)).mismatches == ()

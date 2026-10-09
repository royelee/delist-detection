import csv

from delist_detection.measurement import audit
from delist_detection.measurement.lifecycle import LifecycleView
from delist_detection.measurement.scorecard import Window
from delist_detection.measurement.truth import TRUTH_COLUMNS, load_truth
from tests.lifecycle_tables import ending, iv, obs, sec, tables

WINDOW = Window("2006-01-02", "2024-12-29")


def _view():
    secs = [sec(s) for s in ("L", "C", "C2", "V", "P", "Q", "N", "R1", "R2", "R3")]
    hist = [iv("L", "LLL", "2008-01-02", "2015-03-02"), iv("C", "CCC", "2008-01-02", "2012-03-01"),
            iv("C2", "CCC", "2012-03-02"), iv("V", "VVV", "2008-01-02", "2011-05-02"),
            iv("P", "PPP", "2008-01-02", "2013-02-01"), iv("Q", "QQQ", "2008-01-02", "2014-02-03"),
            iv("N", "NNN", "2008-01-02"),
            iv("R1", "RA", "2008-01-02"), iv("R2", "RB", "2008-01-02"), iv("R3", "RC", "2008-01-02")]
    ends = [ending("L", "2015-03-10", "liquidation", ltd="2015-03-02", method="assumed_par"),     # distress first
            ending("C", "2012-03-10", "exchange_transfer", ltd="2012-03-01", dlret="0.0", successor="C2"),
            ending("V", "2011-05-10", "exchange_transfer", ltd="2011-05-02", dlret="0.0"),
            ending("P", "2013-02-10", ltd="2013-02-01", dlret="0.0", method="assumed_par"),
            ending("Q", "2014-02-10", method="abstain_no_consideration"),
            ending("N", "2009-01-10", "exchange_transfer", successor="N", dlret="0.0"),      # a continuing move
            ending("Z", "2007-06-01", "merger", method="abstain_no_consideration")]          # before any interval
    secs.append(sec("Z"))
    observations = [obs("ZZZ", "2008-06-30", "Z", "after_delisting"), obs("RA", "2010-06-30", "R1"),
                    obs("RB", "2010-06-30", "R2"), obs("RC", "2010-06-30", "R3"), obs("CCC", "2010-06-30", "C")]
    return LifecycleView(tables(secs, hist, ends, observations))


def test_census_puts_each_ending_in_its_first_group_and_skips_continuing_moves():
    targets, skipped = audit.census(_view(), WINDOW)
    assert {t.sec_id: t.group for t in targets} == {
        "L": "census:distress", "C": "census:continuation", "V": "census:left_view", "P": "census:assumed_par",
        "Q": "census:blank_no_value", "Z": "census:blank_no_value"}
    assert skipped == []
    assert {t.sec_id: (t.ticker, t.on) for t in targets}["V"] == ("VVV", "2008-01-02")


def test_blank_no_value_needs_a_window():
    targets, _ = audit.census(_view(), None)
    assert "Q" not in {t.sec_id for t in targets}


def test_an_ending_before_every_interval_is_anchored_on_its_earliest_observation():
    targets, _ = audit.census(_view(), WINDOW)
    assert {t.sec_id: (t.ticker, t.on) for t in targets}["Z"] == ("ZZZ", "2008-06-30")


def test_the_random_sample_is_repeatable_and_avoids_census_chains():
    view = _view()
    targets, _ = audit.census(view, WINDOW)
    exclude = {t.sec_id for t in targets}
    first = audit.random_sample(view, exclude, 2, seed=7)
    assert first == audit.random_sample(view, exclude, 2, seed=7) and len(first) == 2
    assert {t.ticker for t in first} <= {"RA", "RB", "RC"}                 # CCC's chain starts at census C
    assert all(t.group == "random" and t.on == "2010-06-30" for t in first)


def test_worksheet_rows_load_back_as_pending_truth(tmp_path):
    view = _view()
    targets, _ = audit.census(view, WINDOW)
    rows = audit.worksheet_rows(view, targets)
    path = tmp_path / "audit.csv"
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=TRUTH_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    cases = load_truth(path, allow_pending=True)
    assert len(cases) == len(targets) and all(c.pending for c in cases)
    assert next(r for r in rows if r["case"].startswith("left_view"))["library_says"].startswith("left_view; chain V")

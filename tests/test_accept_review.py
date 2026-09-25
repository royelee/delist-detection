"""Bulk-accept review.csv rows by flag: review_triage.accept_by_flag /
append_decisions (pure) and scripts/accept_review.py (thin CLI) (plan
2026-09-24-review-triage, Task 2)."""
import csv
import importlib.util
import sys
from pathlib import Path

import pytest

from delist_detection.review_triage import (
    Decision, ReviewDecisionError, accept_by_flag, append_decisions, load_decisions, triage,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("accept_review_cli", ROOT / "scripts" / "accept_review.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

REVIEW_FIELDS = ("sec_id", "delist_date", "ticker", "cik", "bucket", "dlret", "review_flags", "reason", "anchor_8k",
                 "last_seen")


def _row(sec_id, delist_date, ticker, flags, bucket=None, **extra):
    return {"sec_id": sec_id, "delist_date": delist_date, "ticker": ticker, "review_flags": flags,
            "bucket": bucket, **extra}


ROWS = [
    _row("S1", "2020-01-02", "AAA", "terms_gate_failed:no_acq_price;no_figi", bucket="merger"),
    _row("S2", "2020-02-02", "BBB", "terms_gate_failed:fail_sanity", bucket="merger"),
    _row("S3", "2020-03-02", "CCC", "terms_gate_failed:no_acq_price", bucket="exchange_transfer"),
]


def _write_review_csv(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in REVIEW_FIELDS})


# --- accept_by_flag --------------------------------------------------------

def test_accept_by_flag_matches_every_token_with_that_name():
    decisions = accept_by_flag(ROWS, "terms_gate_failed", note="checked the 8-K")
    assert sorted((d.sec_id, d.flag) for d in decisions) == [
        ("S1", "terms_gate_failed:no_acq_price"),
        ("S2", "terms_gate_failed:fail_sanity"),
        ("S3", "terms_gate_failed:no_acq_price"),
    ]
    assert all(d.note == "checked the 8-K" for d in decisions)


def test_bucket_narrows_the_selection():
    decisions = accept_by_flag(ROWS, "terms_gate_failed", note="x", bucket="merger")
    assert {d.sec_id for d in decisions} == {"S1", "S2"}


def test_a_row_whose_bucket_does_not_match_is_skipped():
    decisions = accept_by_flag(ROWS, "terms_gate_failed", note="x", bucket="exchange_transfer")
    assert [d.sec_id for d in decisions] == ["S3"]


@pytest.mark.parametrize("note", ["", "   "])
def test_note_must_be_non_empty(note):
    with pytest.raises(ReviewDecisionError):
        accept_by_flag(ROWS, "terms_gate_failed", note=note)


def test_an_unacceptable_flag_is_refused():
    with pytest.raises(ReviewDecisionError):
        accept_by_flag(ROWS, "error", note="x")


def test_a_flag_no_row_carries_gives_no_decisions():
    assert accept_by_flag(ROWS, "no_form25", note="x") == []


# --- append_decisions -------------------------------------------------------

def test_append_decisions_creates_the_file_with_the_header(tmp_path):
    path = tmp_path / "decisions.csv"
    n = append_decisions(path, [Decision("S1", "2020-01-02", "AAA", "no_figi", "ok")])
    assert n == 1
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows == [{"sec_id": "S1", "delist_date": "2020-01-02", "ticker": "AAA", "flag": "no_figi",
                     "decision": "accept", "note": "ok"}]


def test_append_decisions_skips_an_existing_decision(tmp_path):
    path = tmp_path / "decisions.csv"
    append_decisions(path, [Decision("S1", "2020-01-02", "AAA", "no_figi", "first")])
    n = append_decisions(path, [Decision("S1", "2020-01-02", "AAA", "no_figi", "second")])
    assert n == 0
    rows = load_decisions(path)
    assert len(rows) == 1 and rows[0].note == "first"


def test_append_decisions_keeps_existing_rows_and_adds_new_ones(tmp_path):
    path = tmp_path / "decisions.csv"
    append_decisions(path, [Decision("S1", "2020-01-02", "AAA", "no_figi", "a")])
    n = append_decisions(path, [Decision("S2", "2020-02-02", "BBB", "no_figi", "b")])
    assert n == 1
    rows = {(d.sec_id, d.flag) for d in load_decisions(path)}
    assert rows == {("S1", "no_figi"), ("S2", "no_figi")}


def test_append_decisions_on_a_missing_path_writes_only_the_new_rows(tmp_path):
    path = tmp_path / "sub" / "decisions.csv"
    n = append_decisions(path, [Decision("S1", "2020-01-02", "AAA", "no_figi", "a"),
                                Decision("S1", "2020-01-02", "AAA", "no_figi", "a")])
    assert n == 1                      # duplicates within one call collapse too
    assert path.exists()


def test_a_decision_written_by_append_clears_exactly_its_token_in_triage(tmp_path):
    path = tmp_path / "decisions.csv"
    row = _row("S1", "2020-01-02", "AAA", "terms_gate_failed:no_acq_price;no_figi", bucket="merger", dlret=0.1)
    decisions = accept_by_flag([row], "terms_gate_failed", note="checked")
    append_decisions(path, decisions)
    loaded = load_decisions(path)
    tri = triage([row], loaded)
    assert tri.counts["accepted"] == 1
    # only the info-only no_figi token is left -> the row is info -> hidden
    assert tri.review_rows == []
    assert tri.counts["info_hidden"] == 1


# --- scripts/accept_review.py (thin CLI) ------------------------------------

def test_cli_dry_run_reports_without_writing(tmp_path, capsys, monkeypatch):
    review = tmp_path / "review.csv"
    decisions = tmp_path / "decisions.csv"
    _write_review_csv(review, ROWS)
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "terms_gate_failed", "--note", "checked",
                                      "--bucket", "merger", "--review", str(review), "--decisions", str(decisions),
                                      "--dry-run"])
    rc = cli.main()
    assert rc == 0
    assert not decisions.exists()
    assert "2" in capsys.readouterr().out


def test_cli_writes_decisions_and_creates_the_file_with_the_header(tmp_path, monkeypatch):
    review = tmp_path / "review.csv"
    decisions = tmp_path / "decisions.csv"
    _write_review_csv(review, ROWS)
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "terms_gate_failed", "--note", "checked",
                                      "--review", str(review), "--decisions", str(decisions)])
    rc = cli.main()
    assert rc == 0
    rows = load_decisions(decisions)
    assert len(rows) == 3 and all(r.note == "checked" for r in rows)


def test_cli_run_twice_does_not_duplicate(tmp_path, monkeypatch):
    review = tmp_path / "review.csv"
    decisions = tmp_path / "decisions.csv"
    _write_review_csv(review, ROWS)
    argv = ["accept_review.py", "--flag", "terms_gate_failed", "--note", "checked", "--review", str(review),
            "--decisions", str(decisions)]
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    cli.main()
    assert len(load_decisions(decisions)) == 3


def test_cli_refuses_an_unacceptable_flag(tmp_path, monkeypatch):
    review = tmp_path / "review.csv"
    _write_review_csv(review, [_row("S1", "2020-01-02", "AAA", "error", bucket="merger")])
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "error", "--note", "x", "--review", str(review),
                                      "--decisions", str(tmp_path / "d.csv")])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_cli_requires_a_non_empty_note(tmp_path, monkeypatch):
    review = tmp_path / "review.csv"
    _write_review_csv(review, ROWS)
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "terms_gate_failed", "--note", "   ",
                                      "--review", str(review), "--decisions", str(tmp_path / "d.csv")])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2

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
from delist_detection.store import TABLES

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("accept_review_cli", ROOT / "scripts" / "accept_review.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

REVIEW_FIELDS = TABLES["review"].columns          # the CLI reads review.csv through store.read_table


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


def test_a_full_token_copied_from_review_csv_is_refused_not_silently_zero():
    """--flag payout_gate_failed:45.5 (a token, not a flag
    name) used to silently match nothing and print "added 0 decision(s)"."""
    with pytest.raises(ReviewDecisionError):
        accept_by_flag(ROWS, "terms_gate_failed:no_acq_price", note="x")


def test_a_flag_not_in_the_catalog_is_refused_not_silently_zero():
    """A typo such as --flag no_last_clsoe used to fall
    back to the generic 'not in the flag catalog' entry (itself acceptable)
    and silently match nothing."""
    with pytest.raises(ReviewDecisionError):
        accept_by_flag(ROWS, "no_last_clsoe", note="x")


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


# --- append_decisions must never damage an existing file --

def test_append_decisions_keeps_a_header_with_spaces_after_commas(tmp_path):
    path = tmp_path / "decisions.csv"
    path.write_text("sec_id, delist_date, ticker, flag, decision, note\n"
                    "S1,2020-01-02,AAA,merger_at_par,accept,read the 8-K\n")
    n = append_decisions(path, [Decision("S2", "2020-02-02", "BBB", "no_figi", "ok")])
    assert n == 1
    loaded = {d.sec_id: d for d in load_decisions(path)}
    assert loaded["S1"] == Decision("S1", "2020-01-02", "AAA", "merger_at_par", "read the 8-K")
    assert loaded["S2"] == Decision("S2", "2020-02-02", "BBB", "no_figi", "ok")
    assert "S1,2020-01-02,AAA,merger_at_par,accept,read the 8-K" in path.read_text()


def test_append_decisions_keeps_a_file_with_a_utf8_bom(tmp_path):
    path = tmp_path / "decisions.csv"
    path.write_bytes(("﻿" + "sec_id,delist_date,ticker,flag,decision,note\n"
                      "S1,2020-01-02,AAA,merger_at_par,accept,read the 8-K\n").encode("utf-8"))
    n = append_decisions(path, [Decision("S2", "2020-02-02", "BBB", "no_figi", "ok")])
    assert n == 1
    assert {(d.sec_id, d.flag) for d in load_decisions(path)} == {("S1", "merger_at_par"), ("S2", "no_figi")}


def test_append_decisions_keeps_an_extra_column_on_every_existing_row(tmp_path):
    path = tmp_path / "decisions.csv"
    path.write_text("sec_id,delist_date,ticker,flag,decision,note,reviewer\n"
                    "S1,2020-01-02,AAA,merger_at_par,accept,read the 8-K,roy\n")
    n = append_decisions(path, [Decision("S2", "2020-02-02", "BBB", "no_figi", "ok")])
    assert n == 1
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0] == {"sec_id": "S1", "delist_date": "2020-01-02", "ticker": "AAA", "flag": "merger_at_par",
                       "decision": "accept", "note": "read the 8-K", "reviewer": "roy"}
    assert rows[1]["sec_id"] == "S2" and rows[1]["reviewer"] == ""     # a new row's extra column is blank


def test_append_decisions_refuses_a_file_that_does_not_load_and_changes_nothing(tmp_path):
    path = tmp_path / "decisions.csv"
    path.write_text("sec_id,delist_date,ticker,flag,decision,note\nS1,2020-01-02,AAA,merger_at_par,reject,\n")
    before = path.read_bytes()
    with pytest.raises(ReviewDecisionError):
        append_decisions(path, [Decision("S2", "2020-02-02", "BBB", "no_figi", "ok")])
    assert path.read_bytes() == before


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


def test_cli_prints_a_warning_when_no_rows_match(tmp_path, monkeypatch, capsys):
    """A mistyped or over-specific flag used to print
    'added 0 decision(s)' and exit 0 with no other sign anything went wrong."""
    review = tmp_path / "review.csv"
    _write_review_csv(review, ROWS)
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "no_form25", "--note", "checked",
                                      "--review", str(review), "--decisions", str(tmp_path / "d.csv")])
    rc = cli.main()
    assert rc == 0
    err = capsys.readouterr().err
    assert "no_form25" in err and "no" in err.lower()


def test_cli_refuses_a_flag_containing_a_colon(tmp_path, monkeypatch):
    review = tmp_path / "review.csv"
    _write_review_csv(review, ROWS)
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "terms_gate_failed:no_acq_price", "--note", "x",
                                      "--review", str(review), "--decisions", str(tmp_path / "d.csv")])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_cli_refuses_a_flag_not_in_the_catalog(tmp_path, monkeypatch):
    review = tmp_path / "review.csv"
    _write_review_csv(review, ROWS)
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "no_last_clsoe", "--note", "x",
                                      "--review", str(review), "--decisions", str(tmp_path / "d.csv")])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_cli_prints_the_rerun_message_after_a_real_write(tmp_path, monkeypatch, capsys):
    review = tmp_path / "review.csv"
    decisions = tmp_path / "decisions.csv"
    _write_review_csv(review, ROWS)
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "terms_gate_failed", "--note", "checked",
                                      "--review", str(review), "--decisions", str(decisions)])
    cli.main()
    assert "rerun classify_universe.py to apply them" in capsys.readouterr().out


def test_cli_dry_run_does_not_print_the_rerun_message(tmp_path, monkeypatch, capsys):
    review = tmp_path / "review.csv"
    decisions = tmp_path / "decisions.csv"
    _write_review_csv(review, ROWS)
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "terms_gate_failed", "--note", "checked",
                                      "--review", str(review), "--decisions", str(decisions), "--dry-run"])
    cli.main()
    assert "rerun classify_universe.py" not in capsys.readouterr().out


def test_cli_refuses_a_bulk_accept_of_a_fix_severity_flag_without_yes(tmp_path, monkeypatch):
    """--flag no_dlret with one note would otherwise clear
    every blank-DLRET row at once, reopening the hole the no_dlret fix closed."""
    review = tmp_path / "review.csv"
    decisions = tmp_path / "decisions.csv"
    _write_review_csv(review, [_row("S9", "2020-09-09", "ZZZ", "no_dlret", bucket="merger")])
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "no_dlret", "--note", "checked",
                                      "--review", str(review), "--decisions", str(decisions)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert not decisions.exists()


def test_cli_allows_a_bulk_accept_of_a_fix_severity_flag_with_yes(tmp_path, monkeypatch):
    review = tmp_path / "review.csv"
    decisions = tmp_path / "decisions.csv"
    _write_review_csv(review, [_row("S9", "2020-09-09", "ZZZ", "no_dlret", bucket="merger")])
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "no_dlret", "--note", "checked",
                                      "--review", str(review), "--decisions", str(decisions), "--yes"])
    rc = cli.main()
    assert rc == 0
    assert len(load_decisions(decisions)) == 1


def test_cli_a_non_fix_severity_flag_needs_no_yes(tmp_path, monkeypatch):
    review = tmp_path / "review.csv"
    decisions = tmp_path / "decisions.csv"
    _write_review_csv(review, ROWS)
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "terms_gate_failed", "--note", "checked",
                                      "--review", str(review), "--decisions", str(decisions)])
    assert cli.main() == 0


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


def test_cli_refuses_a_file_that_is_not_a_review_table(tmp_path, capsys, monkeypatch):
    """review.csv is read through store.read_table, which checks its columns: a
    delistings.csv passed as --review is an argument error, not zero matches."""
    review = tmp_path / "delistings.csv"
    review.write_text("sec_id,delist_date,ticker,review_flags\nS1,2020-01-02,AAA,terms_gate_failed:x\n")
    decisions = tmp_path / "decisions.csv"
    monkeypatch.setattr(sys, "argv", ["accept_review.py", "--flag", "terms_gate_failed", "--note", "checked",
                                      "--review", str(review), "--decisions", str(decisions)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert "do not match table 'review'" in capsys.readouterr().err
    assert not decisions.exists()

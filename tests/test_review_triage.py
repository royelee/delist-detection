"""review.csv triage: the flag catalog, row severities, the decisions file and
the ordering / hiding / summary rules (plan 2026-09-24-review-triage, Task 1)."""
import csv
import math
from pathlib import Path

import pytest

from delist_detection.review_triage import (
    CATALOG, DECISION_COLUMNS, SEVERITIES, Decision, FlagInfo, ReviewDecisionError, flag_info, flag_name,
    is_blank, load_decisions, row_severity, triage,
)

OUTPUT = Path(__file__).resolve().parents[1] / "output"


def _row(sec_id, delist_date, ticker, flags, dlret=None, **extra):
    return {"sec_id": sec_id, "delist_date": delist_date, "ticker": ticker, "review_flags": flags, "dlret": dlret,
            **extra}


def _del(sec_id, delist_date, ticker, flags, dlret=None, bucket="merger", **extra):
    """A delisting row: it has a bucket (a Form 25 review item has a date but none)."""
    return _row(sec_id, delist_date, ticker, flags, dlret=dlret, bucket=bucket, **extra)


def _accept(sec_id, delist_date, ticker, flag, note=""):
    return Decision(sec_id, delist_date, ticker, flag, note)


# --- catalog -------------------------------------------------------------

def test_flag_name_is_the_text_before_the_first_colon():
    assert flag_name("terms_gate_failed:no_acq_price") == "terms_gate_failed"
    assert flag_name("observation_conflict:2014-06-30") == "observation_conflict"
    assert flag_name("no_figi") == "no_figi"
    assert flag_info("terms_gate_failed:no_acq_price") is CATALOG["terms_gate_failed"]


def test_an_unknown_flag_is_check():
    assert flag_info("brand_new_flag:x") == FlagInfo("check", "not in the flag catalog",
                                                     "add it to review_triage.CATALOG")
    assert row_severity(_row("S1", None, "AAA", "brand_new_flag")) == "check"


def _committed_tokens(name: str) -> set[str]:
    with (OUTPUT / name).open(newline="") as fh:
        return {t for r in csv.DictReader(fh) for t in (r["review_flags"] or "").split(";") if t}


@pytest.mark.parametrize("name", ["review.csv", "delistings.csv"])
def test_every_flag_in_the_committed_output_is_in_the_catalog(name):
    tokens = _committed_tokens(name)
    assert tokens                                   # the file really carries flags
    assert sorted({flag_name(t) for t in tokens} - set(CATALOG)) == []


def test_every_catalog_entry_is_complete():
    for name, info in CATALOG.items():
        assert info.severity in SEVERITIES, name
        assert info.description.strip() and info.action.strip(), name
        assert ":" not in name and ";" not in name, name


def test_severities_follow_the_rulings():
    info = {"no_figi", "resolved_by_current_ticker_map", "resolved_by_cik_map", "resolved_by_manual_override",
            "ftd_close_prior", "ftd_close_lagged", "acquirer_close_lagged", "last_trade_date_unconfirmed"}
    unacceptable = {"error", "resolution_degraded", "review_decision_unmatched"}
    assert {n for n, i in CATALOG.items() if i.severity == "info"} == info
    assert {n for n, i in CATALOG.items() if not i.acceptable} == unacceptable
    assert {n for n, i in CATALOG.items() if i.severity == "fix"} == (
        unacceptable | {"observation_unresolved", "no_dlret", "ended_without_delisting"})
    for name in ("merger_at_par", "terms_gate_failed", "payout_gate_failed", "llm_gate_failed",
                 "distress_at_normal_price", "bankruptcy_before_merger", "bankruptcy_tag_unconfirmed",
                 "bankruptcy_text_missing", "no_evidence_default", "last_trade_date_conflict", "no_form25",
                 "delist_date_approx", "successor_unknown", "no_last_close", "no_last_trade_date",
                 "form25_unclassified", "form25_unmatched", "form25_unreadable", "listing_status_unknown",
                 "observed_after_delisting", "member_name_mismatch",
                 "ticker_unconfirmed", "ticker_shared", "ticker_range_overlap", "observation_conflict"):
        assert CATALOG[name].severity == "check", name


# --- row_severity -----------------------------------------------------------

def test_row_severity():
    # row_severity is now purely the most severe of the row's own tokens: it no
    # longer looks at bucket/dlret at all -- triage() injects `no_dlret` onto a
    # blank-DLRET delisting row's tokens *before* calling this (see
    # test_a_blank_dlret_delisting_row_gets_no_dlret_injected below).
    assert row_severity(_del("S1", "2020-01-02", "AAA", "ftd_close_prior:3", dlret=None)) == "info"
    assert row_severity(_del("S1", "2020-01-02", "AAA", "ftd_close_prior:3;no_dlret", dlret=None)) == "fix"
    assert row_severity(_del("S1", "2020-01-02", "AAA", "ftd_close_prior:3", dlret=0.1)) == "info"
    assert row_severity(_del("S1", "2020-01-02", "AAA", "merger_at_par;no_figi", dlret=0.0)) == "check"
    assert row_severity(_row("S1", "", "AAA", "error")) == "fix"
    assert row_severity(_row("S1", None, "AAA", "")) == "info"
    # a Form 25 review item carries a date but no bucket: not a delisting row
    assert row_severity(_row("S1", "2020-01-02", "AAA", "form25_unmatched", dlret=None)) == "check"


# --- triage: hiding, decisions ------------------------------------------------

def test_an_info_only_row_leaves_review_but_is_counted():
    tri = triage([_del("S1", "2020-01-02", "AAA", "ftd_close_prior:2", dlret=0.05)], ())
    assert tri.review_rows == []
    (s,) = tri.summary_rows
    assert (s["flag"], s["severity"], s["rows"], s["in_review"], s["accepted"]) == ("ftd_close_prior", "info", 1, 0, 0)
    assert s["examples"] == "AAA@2020-01-02"
    assert tri.counts == {"fix": 0, "check": 0, "info_hidden": 1, "accepted": 0, "cleared": 0,
                          "unmatched_decisions": 0}


def test_a_delisting_with_no_dlret_stays_as_fix_even_with_info_flags_only():
    (r,) = triage([_del("S1", "2020-01-02", "AAA", "ftd_close_prior:2", dlret=None)], ()).review_rows
    assert (r["severity"], r["review_flags"]) == ("fix", "ftd_close_prior:2;no_dlret")


# --- no_dlret injection (Task 2 review ruling) -------------------------------

def test_a_blank_dlret_delisting_row_gets_no_dlret_injected():
    (r,) = triage([_del("S1", "2020-01-02", "AAA", "no_last_close", dlret=None)], ()).review_rows
    assert (r["severity"], r["review_flags"]) == ("fix", "no_last_close;no_dlret")


def test_a_non_blank_zero_dlret_does_not_get_no_dlret():
    (r,) = triage([_del("S1", "2020-01-02", "AAA", "merger_at_par", dlret=0.0)], ()).review_rows
    assert r["review_flags"] == "merger_at_par"    # 0.0 is a real value, not blank


def test_accepting_the_only_other_flag_keeps_the_row_visible_via_no_dlret():
    rows = [_del("S1", "2020-01-02", "AAA", "no_last_close", dlret=None)]
    tri = triage(rows, [_accept("S1", "2020-01-02", "AAA", "no_last_close")])
    (r,) = tri.review_rows
    assert (r["severity"], r["review_flags"]) == ("fix", "no_dlret")
    assert tri.counts == {"fix": 1, "check": 0, "info_hidden": 0, "accepted": 1, "cleared": 0,
                          "unmatched_decisions": 0}


def test_accepting_no_dlret_too_finally_clears_the_row():
    rows = [_del("S1", "2020-01-02", "AAA", "no_last_close", dlret=None)]
    tri = triage(rows, [_accept("S1", "2020-01-02", "AAA", "no_last_close"),
                        _accept("S1", "2020-01-02", "AAA", "no_dlret")])
    assert tri.review_rows == []
    assert tri.counts["cleared"] == 1 and tri.counts["accepted"] == 2


def test_accept_by_flag_on_no_last_close_then_triage_keeps_the_blank_dlret_row():
    from delist_detection.review_triage import accept_by_flag
    rows = [_del("S1", "2020-01-02", "AAA", "no_last_close", dlret=None),         # blank DLRET: must stay
           _del("S2", "2020-02-02", "BBB", "no_last_close", dlret=0.1)]          # real DLRET: clears
    decisions = accept_by_flag(rows, "no_last_close", note="sampled, all fine")
    tri = triage(rows, decisions)
    assert [(r["sec_id"], r["severity"], r["review_flags"]) for r in tri.review_rows] == [
        ("S1", "fix", "no_dlret")]
    assert tri.counts["cleared"] == 1 and tri.counts["accepted"] == 2


def test_the_summary_has_a_no_dlret_row_counting_the_blank_dlret_delisting_rows():
    rows = [_del("S1", "2020-01-02", "AAA", "no_last_close", dlret=None),
           _del("S2", "2020-02-02", "BBB", "merger_at_par", dlret=0.0),      # not blank: no injection
           _del("S3", "2020-03-02", "CCC", "no_form25", dlret="")]
    tri = triage(rows, ())
    summary = {s["flag"]: s for s in tri.summary_rows}
    assert "no_dlret" in summary
    assert (summary["no_dlret"]["severity"], summary["no_dlret"]["rows"], summary["no_dlret"]["in_review"],
           summary["no_dlret"]["accepted"]) == ("fix", 2, 2, 0)
    assert summary["no_dlret"]["examples"] == "AAA@2020-01-02; CCC@2020-03-02"


def test_no_dlret_never_reaches_a_non_delisting_review_item():
    (r,) = triage([_row("S1", "2020-01-02", "AAA", "form25_unmatched", dlret=None)], ()).review_rows
    assert "no_dlret" not in r["review_flags"]


# --- I3: no_last_close / no_last_trade_date are info on exchange_transfer ----

def test_no_last_close_is_info_on_an_exchange_transfer_row_but_check_elsewhere():
    et_row = _del("S1", "2020-01-02", "AAA", "no_last_close", dlret=0.0, bucket="exchange_transfer")
    assert row_severity(et_row) == "info"
    merger_row = _del("S2", "2020-02-02", "BBB", "no_last_close", dlret=0.05)
    assert row_severity(merger_row) == "check"


def test_no_last_close_alone_on_an_exchange_transfer_row_is_hidden_as_info():
    tri = triage([_del("S1", "2020-01-02", "AAA", "no_last_close", dlret=0.0, bucket="exchange_transfer")], ())
    assert tri.review_rows == [] and tri.counts["info_hidden"] == 1


def test_no_last_trade_date_is_also_info_on_exchange_transfer():
    et_row = _del("S1", "2020-01-02", "AAA", "no_last_trade_date", dlret=0.0, bucket="exchange_transfer")
    assert row_severity(et_row) == "info"


def test_the_summary_severity_stays_base_but_in_review_reflects_the_bucket_downgrade():
    rows = [_del("S1", "2020-01-02", "AAA", "no_last_close", dlret=0.0, bucket="exchange_transfer"),
           _del("S2", "2020-02-02", "BBB", "no_last_close", dlret=0.05)]
    tri = triage(rows, ())
    summ = {s["flag"]: s for s in tri.summary_rows}
    assert summ["no_last_close"]["severity"] == "check"       # review_summary.csv shows the base severity
    assert summ["no_last_close"]["rows"] == 2
    assert summ["no_last_close"]["in_review"] == 1             # S1's row was hidden as info


def test_a_downgraded_token_alongside_a_check_token_still_grades_check():
    row = _del("S1", "2020-01-02", "AAA", "no_last_close;successor_unknown", dlret=0.0,
              bucket="exchange_transfer")
    assert row_severity(row) == "check"                        # successor_unknown is still check here


# --- M1: an unmatched decision's token names the flag ------------------------

def test_two_stale_decisions_on_one_row_give_two_distinct_review_keys():
    tri = triage([], [_accept("S1", "2020-01-02", "AAA", "no_figi"),
                      _accept("S1", "2020-01-02", "AAA", "merger_at_par")])
    keys = {(r["sec_id"], r["delist_date"], r["ticker"], r["review_flags"]) for r in tri.review_rows}
    assert keys == {("S1", "2020-01-02", "AAA", "review_decision_unmatched:no_figi"),
                    ("S1", "2020-01-02", "AAA", "review_decision_unmatched:merger_at_par")}


# --- M3: report_unmatched=False (a --limit subset) ----------------------------

def test_report_unmatched_false_makes_no_unmatched_rows_but_still_counts_them():
    tri = triage([], [_accept("S1", "2020-01-02", "AAA", "no_figi")], report_unmatched=False)
    assert tri.review_rows == [] and tri.summary_rows == []
    assert tri.counts["unmatched_decisions"] == 1


def test_report_unmatched_false_does_not_suppress_a_real_match():
    rows = [_del("S1", "2020-01-02", "AAA", "merger_at_par", dlret=0.0)]
    tri = triage(rows, [_accept("S1", "2020-01-02", "AAA", "merger_at_par"),
                        _accept("S2", "2020-02-02", "BBB", "no_figi")], report_unmatched=False)
    assert tri.review_rows == [] and tri.counts["cleared"] == 1 and tri.counts["unmatched_decisions"] == 1


def test_an_accepted_token_leaves_the_row_and_an_info_remainder_is_hidden():
    rows = [_del("S1", "2020-01-02", "AAA", "merger_at_par;no_figi", dlret=0.0)]
    tri = triage(rows, [_accept("S1", "2020-01-02", "AAA", "merger_at_par")])
    assert tri.review_rows == []
    assert tri.counts["accepted"] == 1 and tri.counts["info_hidden"] == 1 and tri.counts["cleared"] == 0
    assert rows[0]["review_flags"] == "merger_at_par;no_figi"          # the input row is not changed


def test_a_row_whose_every_token_is_accepted_is_cleared():
    tri = triage([_del("S1", "2020-01-02", "AAA", "merger_at_par", dlret=0.0)],
                 [_accept("S1", "2020-01-02", "AAA", "merger_at_par")])
    assert tri.review_rows == []
    assert tri.counts["cleared"] == 1 and tri.counts["info_hidden"] == 0 and tri.counts["accepted"] == 1


def test_remaining_tokens_keep_their_info_flags_and_are_graded_without_the_accepted_ones():
    tri = triage([_del("S1", "2020-01-02", "AAA", "observation_unresolved;merger_at_par;no_figi", dlret=0.0)],
                 [_accept("S1", "2020-01-02", "AAA", "observation_unresolved")])
    (r,) = tri.review_rows
    assert (r["severity"], r["review_flags"]) == ("check", "merger_at_par;no_figi")


def test_a_decision_matches_the_exact_token_and_an_unmatched_one_becomes_a_fix_row():
    rows = [_del("S1", "2020-01-02", "AAA", "terms_gate_failed:fail_sanity", dlret=0.0)]
    tri = triage(rows, [_accept("S1", "2020-01-02", "AAA", "terms_gate_failed:no_acq_price", note="checked 8-K")])
    assert [(r["severity"], r["sec_id"], r["review_flags"]) for r in tri.review_rows] == [
        ("fix", "S1", "review_decision_unmatched:terms_gate_failed:no_acq_price"),
        ("check", "S1", "terms_gate_failed:fail_sanity")]
    un = tri.review_rows[0]
    assert (un["delist_date"], un["ticker"]) == ("2020-01-02", "AAA")
    assert un["reason"] == ("decision accepts 'terms_gate_failed:no_acq_price' but no review row carries it; "
                            "remove it from the decisions file (checked 8-K)")
    assert tri.counts["unmatched_decisions"] == 1 and tri.counts["accepted"] == 0 and tri.counts["fix"] == 1
    summary = {s["flag"]: s for s in tri.summary_rows}
    assert summary["review_decision_unmatched"]["severity"] == "fix"
    assert summary["review_decision_unmatched"]["rows"] == 1
    assert summary["review_decision_unmatched"]["in_review"] == 1
    assert summary["review_decision_unmatched"]["examples"] == "AAA@2020-01-02"


def test_an_unmatched_decision_without_a_note_has_no_parenthetical():
    tri = triage([], [_accept("", "", "ZZZ", "ticker_shared")])
    (r,) = tri.review_rows
    assert r["reason"] == "decision accepts 'ticker_shared' but no review row carries it; remove it from the decisions file"
    assert r["severity"] == "fix" and r["review_flags"] == "review_decision_unmatched:ticker_shared"


def test_the_summary_counts_every_unmatched_decision_row_and_sorts_it_by_that_count():
    rows = [_row("", None, "DDD", "observation_unresolved")]
    tri = triage(rows, [_accept("", "", "XXX", "ticker_shared"), _accept("S1", "2020-01-02", "AAA", "no_figi")])
    got = [(s["flag"], s["rows"], s["in_review"], s["accepted"], s["examples"]) for s in tri.summary_rows]
    assert got == [("review_decision_unmatched", 2, 2, 0, "XXX; AAA@2020-01-02"),
                   ("observation_unresolved", 1, 1, 0, "DDD")]


def test_a_decision_on_the_same_token_but_another_row_does_not_match():
    tri = triage([_del("S1", "2020-01-02", "AAA", "merger_at_par", dlret=0.0)],
                 [_accept("S1", "2020-01-03", "AAA", "merger_at_par")])
    assert sorted(r["review_flags"] for r in tri.review_rows) == [
        "merger_at_par", "review_decision_unmatched:merger_at_par"]


def test_blank_key_cells_match_blank_decision_cells():
    rows = [_row("", None, "CB", "observation_conflict:2014-06-30"),
            _row("", None, "CB", "observation_conflict:2013-12-31")]
    tri = triage(rows, [_accept("", "", "CB", "observation_conflict:2014-06-30")])
    assert [r["review_flags"] for r in tri.review_rows] == ["observation_conflict:2013-12-31"]
    assert tri.counts["accepted"] == 1 and tri.counts["cleared"] == 1 and tri.counts["unmatched_decisions"] == 0


def test_duplicate_decisions_accept_once():
    d = _accept("S1", "2020-01-02", "AAA", "merger_at_par")
    tri = triage([_del("S1", "2020-01-02", "AAA", "merger_at_par", dlret=0.0)], [d, d])
    assert tri.review_rows == [] and tri.counts["unmatched_decisions"] == 0 and tri.counts["accepted"] == 1


# --- ordering -------------------------------------------------------------------

def test_rows_are_ordered_by_severity_then_what_they_can_do_to_a_return():
    rows = [
        _row("S7", None, "GGG", "ticker_shared"),                                   # check, no date
        _del("S6", "2020-06-01", "FFF", "merger_at_par", dlret=0.0),                 # check, dlret 0
        _del("S5", "2020-05-01", "EEE", "payout_gate_failed:20", dlret=0.05),        # check, dlret 0.05
        _del("S4", "2020-04-01", "DDD", "distress_at_normal_price", dlret=-0.3),     # check, dlret -0.3
        _row("S3", None, "CCC", "observation_unresolved"),                           # fix, no date
        _del("S2", "2020-02-01", "BBB", "error", dlret=0.1),                         # fix, with a dlret
        _del("S1", "2020-01-01", "AAA", "ftd_close_prior:1", dlret=None),            # fix, blank dlret
        _row("S0", None, "ZZZ", "ticker_shared"),                                    # check, no date
    ]
    tri = triage(rows, ())
    assert [(r["severity"], r["sec_id"]) for r in tri.review_rows] == [
        ("fix", "S1"), ("fix", "S2"), ("fix", "S3"),
        ("check", "S4"), ("check", "S5"), ("check", "S6"), ("check", "S0"), ("check", "S7")]
    assert tri.counts["fix"] == 3 and tri.counts["check"] == 5


def test_a_form25_review_item_with_a_date_but_no_bucket_is_check_and_sorts_with_the_undated_rows():
    rows = [
        _row("S1", "2020-01-02", "AAA", "form25_unmatched", dlret=None),     # Form 25 review item, no bucket
        _row("S0", None, "ZZZ", "ticker_shared"),                            # check, no date
        _del("S9", "2020-09-01", "III", "merger_at_par", dlret=0.0),         # check delisting, dlret 0
        _del("S8", "2020-08-01", "HHH", "merger_at_par", dlret=None),        # fix: a delisting with no DLRET
    ]
    tri = triage(rows, ())
    assert [(r["severity"], r["sec_id"]) for r in tri.review_rows] == [
        ("fix", "S8"), ("check", "S9"), ("check", "S0"), ("check", "S1")]


# --- summary ---------------------------------------------------------------------

def _summary_fixture():
    rows = [
        _del("S1", "2020-01-02", "AAA", "merger_at_par;no_figi", dlret=0.0),
        _del("S2", "2021-03-04", "BBB", "merger_at_par", dlret=0.0),
        _row("S3", None, "CCC", "no_figi"),
        _row("", None, "DDD", "observation_unresolved"),
        _row("S5", None, "", "no_figi"),
        _row("S6", None, "EEE", "ticker_shared"),
        _row("S7", None, "FFF", "ticker_shared"),
        _row("S8", None, "GGG", "member_name_mismatch"),
        _row("S9", None, "HHH", "no_figi"),
    ]
    return rows, [_accept("S2", "2021-03-04", "BBB", "merger_at_par")]


def test_summary_rows_group_by_flag_with_counts_and_examples():
    rows, decisions = _summary_fixture()
    tri = triage(rows, decisions)
    got = [(s["severity"], s["flag"], s["rows"], s["in_review"], s["accepted"], s["examples"])
           for s in tri.summary_rows]
    assert got == [
        ("fix", "observation_unresolved", 1, 1, 0, "DDD"),
        ("check", "merger_at_par", 2, 1, 1, "AAA@2020-01-02; BBB@2021-03-04"),
        ("check", "ticker_shared", 2, 2, 0, "EEE; FFF"),
        ("check", "member_name_mismatch", 1, 1, 0, "GGG"),
        ("info", "no_figi", 4, 1, 0, "AAA@2020-01-02; CCC; S5"),
    ]
    assert tri.summary_rows[0]["description"] == CATALOG["observation_unresolved"].description
    assert tri.summary_rows[0]["action"] == CATALOG["observation_unresolved"].action
    assert tri.counts == {"fix": 1, "check": 4, "info_hidden": 3, "accepted": 1, "cleared": 1,
                          "unmatched_decisions": 0}


def test_triage_is_deterministic_whatever_the_input_order():
    rows, decisions = _summary_fixture()
    rows += [_del("S4", "2020-04-01", "DDD", "distress_at_normal_price", dlret=-0.3),
             _del("S1", "2020-01-01", "AAA", "ftd_close_prior:1", dlret=None)]
    decisions += [_accept("", "", "QQQ", "no_figi")]
    a = triage(rows, decisions)
    b = triage(list(reversed(rows)), list(reversed(decisions)))
    assert a.review_rows == b.review_rows and a.summary_rows == b.summary_rows and a.counts == b.counts


def test_output_rows_carry_the_severity_and_every_input_column():
    (r,) = triage([_del("S1", "2020-01-02", "AAA", "merger_at_par", dlret=0.0, cik=1, bucket="merger",
                        reason="why", anchor_8k="2.01", last_seen=None)], ()).review_rows
    assert r == {"severity": "check", "sec_id": "S1", "delist_date": "2020-01-02", "ticker": "AAA", "cik": 1,
                 "bucket": "merger", "dlret": 0.0, "review_flags": "merger_at_par", "reason": "why",
                 "anchor_8k": "2.01", "last_seen": None}


def test_a_severity_already_on_an_input_row_is_recomputed():
    (r,) = triage([_row("S1", None, "AAA", "observation_unresolved", severity="info")], ()).review_rows
    assert r["severity"] == "fix"


def test_a_nan_dlret_counts_as_blank():
    (r,) = triage([_del("S1", "2020-01-02", "AAA", "merger_at_par", dlret=float("nan"))], ()).review_rows
    assert r["severity"] == "fix" and math.isnan(r["dlret"])


# --- load_decisions --------------------------------------------------------------

HEADER = ",".join(DECISION_COLUMNS)


def _write(tmp_path, text: str) -> Path:
    p = tmp_path / "review_decisions.csv"
    p.write_text(text)
    return p


def test_a_header_only_file_has_no_decisions(tmp_path):
    assert load_decisions(_write(tmp_path, HEADER + "\n")) == []


def test_load_decisions_ignores_a_utf8_bom(tmp_path):
    """A UTF-8 BOM, which Excel writes on a "CSV UTF-8"
    save, must not blank the first header cell (sec_id)."""
    p = tmp_path / "review_decisions.csv"
    p.write_bytes(("﻿" + HEADER + "\nS1,2020-01-02,AAA,merger_at_par,accept,ok\n").encode("utf-8"))
    assert load_decisions(p) == [Decision("S1", "2020-01-02", "AAA", "merger_at_par", "ok")]


def test_is_blank():
    assert is_blank(None) and is_blank("") and is_blank("  ") and is_blank(float("nan"))
    assert not is_blank(0.0) and not is_blank("x")


def test_decisions_are_read_stripped_and_extra_columns_are_ignored(tmp_path):
    p = _write(tmp_path, HEADER + ",reviewer\n"
               " S1 , 2020-01-02 ,AAA, merger_at_par ,accept, 8-K says par ,roy\n"
               ",,CB,observation_conflict:2014-06-30,accept,,roy\n"
               "S1,2020-01-02,AAA,merger_at_par,accept,again,roy\n")      # a duplicate collapses
    assert load_decisions(p) == [Decision("S1", "2020-01-02", "AAA", "merger_at_par", "8-K says par"),
                                 Decision("", "", "CB", "observation_conflict:2014-06-30", "")]


def test_a_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_decisions(tmp_path / "nope.csv")


def test_a_missing_required_column_is_refused(tmp_path):
    p = _write(tmp_path, "sec_id,delist_date,ticker,decision,note\nS1,2020-01-02,AAA,accept,\n")
    with pytest.raises(ReviewDecisionError, match=r"review_decisions\.csv.*flag"):
        load_decisions(p)


@pytest.mark.parametrize("line, why", [
    ("S1,2020-01-02,AAA,merger_at_par,reject,", "decision"),
    ("S1,2020-01-02,AAA,merger_at_par,Accept,", "decision"),
    ("S1,2020-01-02,AAA,,accept,", "flag"),
    ("S1,2020-01-02,AAA,error,accept,", "error"),
    ("S1,2020-01-02,AAA,resolution_degraded,accept,", "resolution_degraded"),
    ("S1,2020-01-02,AAA,review_decision_unmatched,accept,", "review_decision_unmatched"),
])
def test_a_bad_decision_is_refused_naming_the_file_and_line(tmp_path, line, why):
    p = _write(tmp_path, HEADER + "\nS0,2019-01-02,ZZZ,merger_at_par,accept,\n" + line + "\n")
    with pytest.raises(ReviewDecisionError, match=rf"review_decisions\.csv:3\b.*{why}"):
        load_decisions(p)


def test_decision_error_is_a_value_error():
    assert issubclass(ReviewDecisionError, ValueError)

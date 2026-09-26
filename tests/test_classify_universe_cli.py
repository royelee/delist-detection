"""Offline smoke test for scripts/classify_universe.py: it must import cleanly
(no leftover Alpha Vantage / raw-Tiingo names) and its argument parser must
still parse with sane defaults, without touching the network."""
import importlib.util
import sys
from pathlib import Path

import pytest

from delist_detection import edgar as edgar_mod

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("classify_universe_cli", ROOT / "scripts" / "classify_universe.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


class _FakeSummary:
    def __init__(self, review_flags, review_counts=None):
        self.counts, self.buckets, self.figi_sources = {}, {}, {}
        self.review_flags = review_flags
        self.review_counts = review_counts or {"fix": 0, "check": 0, "info_hidden": 0, "accepted": 0,
                                               "cleared": 0, "unmatched_decisions": 0}


def _run_main(monkeypatch, review_flags, *argv):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    monkeypatch.setattr(cli, "use_machine_wide_limit", lambda *a, **k: None)
    monkeypatch.setattr(cli, "load_observations", lambda path: [])
    monkeypatch.setattr(cli, "ObservationIndex", lambda obs: obs)
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: object())
    seen = {}
    monkeypatch.setattr(cli, "run", lambda *a, **kw: seen.update(kw) or _FakeSummary(review_flags))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv", *argv])
    rc = cli.main()
    _run_main.seen = seen
    return rc


def test_manual_overrides_include_kwk():
    assert cli.MANUAL_OVERRIDES["KWK"] == 1060990


def test_known_renames_include_fb_to_meta():
    assert cli.KNOWN_RENAMES["FB"] == "META"


def test_argument_parser_defaults():
    args = cli.build_parser().parse_args(["--observations", "x.csv"])
    assert args.observations == "x.csv"
    assert args.limit is None
    assert args.no_extract_payouts is False
    assert args.no_midas is False and args.no_halts is False
    assert args.extract_merger_terms_llm is False
    assert args.llm_model is None
    assert args.merger_terms_sanity_tol == cli.DEFAULT_TOL
    assert args.output_dir == str(ROOT / "output")
    assert args.cache_dir == str(ROOT / "cache")
    assert args.sec_workers == 4


def test_parser_epilog_documents_exit_codes():
    epilog = cli.build_parser().epilog or ""
    assert "0" in epilog and "2" in epilog and "3" in epilog
    assert "1  aborted: OpenFIGI unavailable" in epilog


def _entry_with_run_raising(monkeypatch, exc):
    def boom(*a, **kw):
        raise exc

    _run_main(monkeypatch, {})                       # sets up the environment and fakes
    monkeypatch.setattr(cli, "run", boom)
    return cli.entry()


def test_an_openfigi_outage_exits_1_with_no_outputs_written(monkeypatch, capsys):
    """OpenFIGI down after its retries is not a
    refusal (exit 2) but an outage: exit 1, and the message says nothing was
    written and to rerun later."""
    from delist_detection.openfigi import OpenFigiUnavailable

    rc = _entry_with_run_raising(monkeypatch, OpenFigiUnavailable("OpenFIGI /mapping kept failing after 6 attempts"))
    assert rc == 1
    err = capsys.readouterr().err
    assert "OpenFIGI unavailable after retries; no outputs written; rerun later" in err


def test_a_refusal_still_exits_2(monkeypatch, capsys):
    from delist_detection.edgar import EdgarBlocked
    from delist_detection.openfigi import OpenFigiBlocked

    rc = _entry_with_run_raising(monkeypatch, OpenFigiBlocked("OpenFIGI returned 403 for /mapping"))
    assert rc == 2 and "ABORTED" in capsys.readouterr().err
    assert _entry_with_run_raising(monkeypatch, EdgarBlocked("SEC returned 403")) == 2


def test_every_fatal_exception_is_an_abort_and_nothing_else_is(monkeypatch):
    """The CLI catches fatal.FATAL, the one list of exceptions that stop a run;
    any other exception is not turned into an abort code."""
    from delist_detection.fatal import FATAL

    for exc_type in FATAL:
        assert _entry_with_run_raising(monkeypatch, exc_type("x")) in (1, 2), exc_type
    with pytest.raises(ValueError):
        _entry_with_run_raising(monkeypatch, ValueError("override rows that match no delisting"))


def test_main_returns_0_when_no_review_errors(monkeypatch, capsys):
    rc = _run_main(monkeypatch, {"member_name_mismatch": 2})
    assert rc == 0
    assert "ABORTED" not in capsys.readouterr().err


def test_main_returns_3_and_prints_banner_when_review_has_errors(monkeypatch, capsys):
    rc = _run_main(monkeypatch, {"error": 3, "member_name_mismatch": 1})
    assert rc == 3
    err = capsys.readouterr().err
    assert "3" in err and "error" in err.lower()


def test_main_passes_sec_workers_to_run(monkeypatch):
    assert _run_main(monkeypatch, {}, "--sec-workers", "3") == 0
    assert _run_main.seen["sec_workers"] == 3


@pytest.mark.parametrize("n", ["0", "9"])
def test_sec_workers_outside_1_to_8_is_refused(monkeypatch, n):
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, {}, "--sec-workers", n)
    assert exc.value.code == 2


def test_the_fallback_user_agent_stops_the_run_before_any_request(monkeypatch):
    monkeypatch.setattr(edgar_mod, "resolve_user_agent", lambda: edgar_mod.FALLBACK_UA)
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: pytest.fail("no client may be built"))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_main_returns_3_when_an_answer_rested_on_a_failed_request(monkeypatch, capsys):
    rc = _run_main(monkeypatch, {"resolution_degraded": 2})
    assert rc == 3
    err = capsys.readouterr().err
    assert "2" in err and "resolution_degraded" in err


def test_no_review_decisions_file_at_the_default_path_means_no_decisions(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DEFAULT_REVIEW_DECISIONS", str(tmp_path / "missing.csv"))
    rc = _run_main(monkeypatch, {})
    assert rc == 0
    assert _run_main.seen["review_decisions"] == []


def test_an_explicit_missing_review_decisions_path_exits_2(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    monkeypatch.setattr(cli, "use_machine_wide_limit", lambda *a, **k: None)
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: pytest.fail("no client may be built"))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv",
                                      "--review-decisions", str(tmp_path / "nope.csv")])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_an_explicit_path_spelling_out_the_default_still_exits_2_when_missing(monkeypatch, tmp_path):
    """Minor 1 (Task 2 review): comparing the raw path string to
    DEFAULT_REVIEW_DECISIONS would wrongly treat an explicitly-given path that
    happens to equal the default as "the default" and silently swallow a
    missing file. The None-sentinel fix must still exit 2 here."""
    same_as_default = str(tmp_path / "review_decisions.csv")
    monkeypatch.setattr(cli, "DEFAULT_REVIEW_DECISIONS", same_as_default)
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    monkeypatch.setattr(cli, "use_machine_wide_limit", lambda *a, **k: None)
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: pytest.fail("no client may be built"))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv",
                                      "--review-decisions", same_as_default])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_a_decisions_file_with_decision_reject_exits_2(monkeypatch, tmp_path):
    path = tmp_path / "decisions.csv"
    path.write_text("sec_id,delist_date,ticker,flag,decision,note\nS1,,X,no_figi,reject,bad\n")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    monkeypatch.setattr(cli, "use_machine_wide_limit", lambda *a, **k: None)
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: pytest.fail("no client may be built"))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv",
                                      "--review-decisions", str(path)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_an_unusable_rate_lock_stops_the_run_before_any_request(monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")

    def cannot(*a, **k):
        raise OSError("cannot open the machine-wide SEC rate lock /x (denied); set DELIST_DETECTION_SEC_RATE_LOCK")

    monkeypatch.setattr(cli, "use_machine_wide_limit", cannot)
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: pytest.fail("no client may be built"))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2

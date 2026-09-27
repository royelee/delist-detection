"""Offline smoke test for scripts/classify_universe.py: it must import cleanly
(no leftover Alpha Vantage / raw-Tiingo names) and its argument parser must
still parse with sane defaults, without touching the network."""
import importlib.util
import sys
from datetime import date
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
    clients_kw = {}
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: clients_kw.update(kw) or object())
    seen = {}
    monkeypatch.setattr(cli, "run", lambda *a, **kw: seen.update(kw) or _FakeSummary(review_flags))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", "x.csv", *argv])
    _run_main.seen, _run_main.clients_kw = seen, clients_kw
    return cli.main()


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
    assert args.as_of is None                        # main() dates the run today


def test_parser_epilog_documents_exit_codes():
    epilog = cli.build_parser().epilog or ""
    for code in ("0  ", "1  ", "2  ", "3  ", "4  "):
        assert code in epilog
    assert "1  unexpected crash" in epilog
    assert "4  aborted: OpenFIGI unavailable" in epilog
    assert "--merger-terms" in epilog and "match no delisting" in epilog


def _entry_with_run_raising(monkeypatch, exc):
    def boom(*a, **kw):
        raise exc

    _run_main(monkeypatch, {})                       # sets up the environment and fakes
    monkeypatch.setattr(cli, "run", boom)
    return cli.entry()


def test_an_openfigi_outage_exits_4_with_no_outputs_written(monkeypatch, capsys):
    """OpenFIGI down after its retries is not a refusal (exit 2) nor a crash
    (exit 1) but an outage: exit 4, and the message says nothing was written
    and to rerun later."""
    from delist_detection.openfigi import OpenFigiUnavailable

    rc = _entry_with_run_raising(monkeypatch, OpenFigiUnavailable("OpenFIGI /mapping kept failing after 6 attempts"))
    assert rc == 4
    err = capsys.readouterr().err
    assert "OpenFIGI unavailable after retries; no outputs written; rerun later" in err


def test_a_refusal_still_exits_2(monkeypatch, capsys):
    from delist_detection.edgar import EdgarBlocked
    from delist_detection.openfigi import OpenFigiBlocked

    rc = _entry_with_run_raising(monkeypatch, OpenFigiBlocked("OpenFIGI returned 403 for /mapping"))
    assert rc == 2 and "ABORTED" in capsys.readouterr().err
    assert _entry_with_run_raising(monkeypatch, EdgarBlocked("SEC returned 403")) == 2


def test_every_fatal_exception_has_its_own_exit_code_and_nothing_else_is_caught(monkeypatch):
    """The CLI catches fatal.FATAL, the one list of exceptions that stop a run,
    each with its exit code: a refusal 2, an OpenFIGI outage 4. Any other
    exception is an unexpected crash: it is not caught, so Python exits 1."""
    from delist_detection.edgar import EdgarBlocked
    from delist_detection.fatal import FATAL
    from delist_detection.openfigi import OpenFigiBlocked, OpenFigiUnavailable

    expected = {EdgarBlocked: 2, OpenFigiBlocked: 2, OpenFigiUnavailable: 4}
    assert set(FATAL) == set(expected)              # a new fatal exception needs its code here
    for exc_type, code in expected.items():
        assert _entry_with_run_raising(monkeypatch, exc_type("x")) == code, exc_type
    with pytest.raises(ValueError):
        _entry_with_run_raising(monkeypatch, ValueError("boom"))
    with pytest.raises(KeyError):
        _entry_with_run_raising(monkeypatch, KeyError("boom"))


def test_an_override_row_that_matches_no_delisting_exits_2_on_one_line(monkeypatch, capsys):
    """The pipeline finds an override row that names no delisting mid-run, before
    anything is written: a bad input file (exit 2), not a crash (exit 1)."""
    from delist_detection.reconstruction import OverrideFileError

    rc = _entry_with_run_raising(monkeypatch, OverrideFileError(
        "override rows that match no delisting: --recoveries rec.csv line 3: BBG999"))
    assert rc == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err and "rec.csv line 3: BBG999" in err and "no outputs written" in err


def test_no_observations_to_process_exits_2(monkeypatch, capsys):
    """An observations file with no rows (or a --limit that leaves none) is bad
    input, like a malformed file: exit 2, not an unexpected crash."""
    from delist_detection.observations import ObservationError

    assert _entry_with_run_raising(monkeypatch, ObservationError("no observations to process")) == 2
    assert "no observations to process" in capsys.readouterr().err


def _entry_with_inputs(monkeypatch, tmp_path, *argv, observations="ticker,as_of\nAET,2018-06-29\n",
                       default_decisions=None):
    """entry() over real input files: observations from `observations`, the rest
    from `argv`; no client may be built."""
    obs = tmp_path / "obs.csv"
    obs.write_text(observations)
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    monkeypatch.setattr(cli, "use_machine_wide_limit", lambda *a, **k: None)
    monkeypatch.setattr(cli, "DEFAULT_REVIEW_DECISIONS", default_decisions or str(tmp_path / "no-decisions.csv"))
    monkeypatch.setattr(cli, "default_clients", lambda *a, **kw: pytest.fail("no client may be built"))
    monkeypatch.setattr(sys, "argv", ["classify_universe.py", "--observations", str(obs), *argv])
    return cli.entry()


@pytest.mark.parametrize("flag,text,where", [
    ("--merger-terms", "sec_id,cash_per_share\nBBG1,1O.5\n", "line 2: cash_per_share '1O.5' is not a number"),
    ("--merger-terms", "sec_id,stock_ratio,acquirer_price\nBBG1,0.5,\n", "line 2: "),
    ("--last-trade-closes", "sec_id,close\nBBG1,1\n", "line 1: missing required column"),
    ("--recoveries", "sec_id,recovery_ratio\nBBG1,abc\n", "line 2: recovery_ratio 'abc' is not a number"),
])
def test_a_malformed_override_file_exits_2_naming_the_file_and_line(monkeypatch, capsys, tmp_path, flag, text, where):
    path = tmp_path / "override.csv"
    path.write_text(text)
    assert _entry_with_inputs(monkeypatch, tmp_path, flag, str(path)) == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err and f"{path} {where}" in err


@pytest.mark.parametrize("flag", ["--merger-terms", "--last-trade-closes", "--recoveries", "--review-decisions"])
def test_a_missing_input_file_exits_2_naming_it(monkeypatch, capsys, tmp_path, flag):
    missing = tmp_path / "nope.csv"
    assert _entry_with_inputs(monkeypatch, tmp_path, flag, str(missing)) == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err and str(missing) in err


def test_a_malformed_observations_file_exits_2_naming_the_file_and_line(monkeypatch, capsys, tmp_path):
    assert _entry_with_inputs(monkeypatch, tmp_path, observations="ticker,as_of\nAET,someday\n") == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err and "obs.csv" in err and "line 2" in err


def test_main_returns_0_when_no_review_errors(monkeypatch, capsys):
    rc = _run_main(monkeypatch, {"member_name_mismatch": 2})
    assert rc == 0
    assert "ABORTED" not in capsys.readouterr().err


def test_main_returns_3_and_prints_banner_when_review_has_errors(monkeypatch, capsys):
    rc = _run_main(monkeypatch, {"error": 3, "member_name_mismatch": 1})
    assert rc == 3
    err = capsys.readouterr().err
    assert "3" in err and "error" in err.lower()


def test_as_of_dates_every_client(monkeypatch):
    """--as-of pins the run date every client's freshness rule reads, so a rerun
    on a later day can reproduce an earlier run's tables."""
    assert _run_main(monkeypatch, {}, "--as-of", "2026-09-25") == 0
    assert _run_main.clients_kw["as_of"] == date(2026, 9, 25)


def test_the_run_date_defaults_to_today(monkeypatch):
    assert _run_main(monkeypatch, {}) == 0
    assert _run_main.clients_kw["as_of"] == date.today()


@pytest.mark.parametrize("bad", ["2026-13-01", "25/09/2026", "yesterday"])
def test_an_unreadable_as_of_is_refused(monkeypatch, capsys, bad):
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, {}, "--as-of", bad)
    assert exc.value.code == 2
    assert "--as-of" in capsys.readouterr().err
    assert _run_main.clients_kw == {}


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


def test_an_explicit_missing_review_decisions_path_exits_2(monkeypatch, capsys, tmp_path):
    missing = tmp_path / "nope.csv"
    assert _entry_with_inputs(monkeypatch, tmp_path, "--review-decisions", str(missing)) == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err and str(missing) in err


def test_an_explicit_path_spelling_out_the_default_still_exits_2_when_missing(monkeypatch, tmp_path):
    """Comparing the raw path string to DEFAULT_REVIEW_DECISIONS would wrongly
    treat an explicitly-given path that happens to equal the default as "the
    default" and silently swallow a missing file: it must still exit 2."""
    same_as_default = str(tmp_path / "review_decisions.csv")
    rc = _entry_with_inputs(monkeypatch, tmp_path, "--review-decisions", same_as_default,
                            default_decisions=same_as_default)
    assert rc == 2


def test_a_decisions_file_with_decision_reject_exits_2_naming_the_line(monkeypatch, capsys, tmp_path):
    path = tmp_path / "decisions.csv"
    path.write_text("sec_id,delist_date,ticker,flag,decision,note\nS1,,X,no_figi,reject,bad\n")
    assert _entry_with_inputs(monkeypatch, tmp_path, "--review-decisions", str(path)) == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err and f"{path}:2" in err


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

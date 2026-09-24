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
    def __init__(self, review_flags):
        self.counts, self.buckets, self.figi_sources = {}, {}, {}
        self.review_flags = review_flags


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

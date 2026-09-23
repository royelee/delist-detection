"""Offline smoke test for scripts/classify_universe.py: it must import cleanly
(no leftover Alpha Vantage / raw-Tiingo names) and its argument parser must
still parse with sane defaults, without touching the network."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("classify_universe_cli", ROOT / "scripts" / "classify_universe.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


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

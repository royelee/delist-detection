import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "seeds_from_observations", Path(__file__).resolve().parents[1] / "scripts" / "seeds_from_observations.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _o(ticker, as_of, name):
    return {"ticker": ticker, "as_of": as_of, "name": name, "cusip": "", "cik": "", "sec_id": ""}


def test_a_seed_is_a_first_sighting_a_return_or_a_new_name():
    rows = [_o("AAA", "2010-06-30", "ALPHA CORP"), _o("AAA", "2010-12-31", "ALPHA CORP"),
            _o("BBB", "2010-06-30", "BETA INC"), _o("BBB", "2011-06-30", "BETA INC"),
            _o("AAA", "2011-06-30", "ZETA HOLDINGS"), _o("CCC", "2010-12-31", "")]
    assert [(r["ticker"], r["as_of"]) for r in mod.seeds(rows)] == [
        ("AAA", "2010-06-30"), ("AAA", "2011-06-30"), ("BBB", "2010-06-30"), ("BBB", "2011-06-30"),
        ("CCC", "2010-12-31")]

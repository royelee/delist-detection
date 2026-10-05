"""The committed output tables against the floor in data/scorecard.json: no
floored number may get worse ("Nothing later may lower a scorecard number").

If this fails after a run of classify_universe.py into output/: a --limit or
otherwise partial run there drops every number (restore it with
`git checkout output/`). A real drop is a regression to fix. Lower a floor
entry only on purpose (a changed universe, a retired metric), by hand, and say
why in the commit."""
import csv
import json
from datetime import date
from pathlib import Path

from delist_detection.lifecycle import Tables
from delist_detection.scorecard import build, drops, load_config

ROOT = Path(__file__).resolve().parents[1]


def _legs_rows(out_dir: Path) -> list[dict[str, str]] | None:
    """contract/payout_legs.csv's rows, as scripts/scorecard.py reads them (a basket case is judged on its legs)."""
    path = out_dir / "contract" / "payout_legs.csv"
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_the_committed_tables_keep_every_floored_number_and_every_golden_pass_case():
    config = load_config(ROOT / "data" / "scorecard.json")
    as_of = date.fromisoformat(json.loads((ROOT / "output" / "run_manifest.json").read_text())["as_of"])
    card = build(Tables.read(ROOT / "output"), as_of=as_of, config=config, legs_rows=_legs_rows(ROOT / "output"))
    assert drops(card, config.floor) == []
    assert card["golden_failures"] == []
    assert card["diagnosis_failures"] == []

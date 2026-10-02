"""Recompute the scorecard from the tables under --output-dir and compare it to
the floor in --config (spec: Delist Library Reset, step 1 "Measure first").

  python scripts/scorecard.py                    # every number, then drops and failing golden cases
  python scripts/scorecard.py --check            # exit 1 if a floored number got worse or a golden pass case fails
  python scripts/scorecard.py --write            # also rewrite <output-dir>/scorecard.json
  python scripts/scorecard.py --raise-floor      # move the config's floor to every better number (never worse)
  python scripts/scorecard.py --lifecycles l.csv # one row per input ticker and per security

Offline. The run date is the tables' own (run_manifest.json's as_of; today
when there is no manifest). Exit 2: a bad config or truth file, or tables
that cannot be read.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.atomic_io import write_atomic
from delist_detection.lifecycle import LifecycleView, Tables
from delist_detection.manifest import MANIFEST_NAME
from delist_detection.scorecard import (ScorecardConfigError, build, drops, load_config, raise_floor, write)
from delist_detection.truth import TruthFileError

LIFECYCLE_COLUMNS = ("unit", "key", "sec_id", "kind", "quality", "chain", "final_delist_date", "final_bucket")


def tables_as_of(out_dir: Path) -> date:
    path = out_dir / MANIFEST_NAME
    if not path.exists():
        return date.today()
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict) or "as_of" not in manifest:
        raise ValueError(f"{path}: no as_of")
    return date.fromisoformat(manifest["as_of"])


def lifecycle_rows(view: LifecycleView) -> list[dict[str, str]]:
    rows = []
    for unit, lifecycles in (("ticker", view.by_input_ticker()), ("security", view.by_security())):
        for key, lc in sorted(lifecycles.items()):
            final = lc.final or {}
            rows.append({"unit": unit, "key": key, "sec_id": lc.start, "kind": lc.kind, "quality": lc.quality or "",
                         "chain": ";".join(lc.chain), "final_delist_date": final.get("delist_date", ""),
                         "final_bucket": final.get("bucket", "")})
    return rows


def _csv_text(columns, rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--config", type=Path, default=ROOT / "data" / "scorecard.json")
    p.add_argument("--check", action="store_true")
    p.add_argument("--write", action="store_true")
    p.add_argument("--raise-floor", action="store_true")
    p.add_argument("--lifecycles", type=Path)
    args = p.parse_args(argv)
    try:
        config = load_config(args.config)
        tables = Tables.read(args.output_dir)
        as_of = tables_as_of(args.output_dir)
    except (ScorecardConfigError, TruthFileError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    card = build(tables, as_of=as_of, config=config)
    card["drops"] = drops(card, config.floor)
    for name, value in sorted(card["metrics"].items()):
        print(f"{name:48} {value}")
    for line in card["drops"]:
        print(f"DROP {line}")
    for line in card["golden_failures"]:
        print(f"GOLDEN FAILING {line}")
    if args.write:
        print(f"wrote {write(args.output_dir, card)}")
    if args.lifecycles:
        write_atomic(args.lifecycles, _csv_text(LIFECYCLE_COLUMNS, lifecycle_rows(LifecycleView(tables))))
        print(f"wrote {args.lifecycles}")
    if args.raise_floor:
        raw = json.loads(args.config.read_text(encoding="utf-8"))
        raw["floor"] = raise_floor(card, config.floor)
        write_atomic(args.config, json.dumps(raw, indent=2) + "\n")
        print(f"raised the floor in {args.config}")
    if args.check and (card["drops"] or card["golden_failures"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

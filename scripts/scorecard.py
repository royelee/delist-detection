"""Recompute the scorecard from the tables under --output-dir and compare it to
the floor in --config (spec: Delist Library Reset, step 1 "Measure first").

  python scripts/scorecard.py                    # every number, then drops and failing golden cases
  python scripts/scorecard.py --check            # exit 1 if a floored number got worse, a golden pass case fails or a
                                                 # diagnosis pass case fails
  python scripts/scorecard.py --check --base REV # also recompute the regression report against commit REV (a sub-plan's
                                                 # base) and fail on a regression the --ledger has not settled
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
from delist_detection.diagnosis_loop import LEDGER, read_csv, settled_keys
from delist_detection.lifecycle import LifecycleView, Tables
from delist_detection.manifest import MANIFEST_NAME
from delist_detection.scorecard import (ScorecardConfigError, build, drops, load_config, raise_floor, write)
from delist_detection.regression import RegressionInputError, build_report, unexplained
from delist_detection.truth import TruthFileError

LEGS_FILE = "contract/payout_legs.csv"
LIFECYCLE_COLUMNS = ("unit", "key", "sec_id", "kind", "quality", "chain", "final_delist_date", "final_bucket")


def tables_as_of(out_dir: Path) -> date:
    path = out_dir / MANIFEST_NAME
    if not path.exists():
        return date.today()
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict) or "as_of" not in manifest:
        raise ValueError(f"{path}: no as_of")
    return date.fromisoformat(manifest["as_of"])


def legs_rows(out_dir: Path) -> list[dict[str, str]] | None:
    """contract/payout_legs.csv's rows, or None when the run has no such table (before sub-plan 5f)."""
    path = out_dir / LEGS_FILE
    if not path.exists():
        return None
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


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
    p.add_argument("--base", help="a commit: recompute the regression report against it and count "
                   "D.unexplained_regressions (without it there is no such metric)")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--ledger", type=Path, default=ROOT / LEDGER, help="the diagnosis loop's diagnosed.csv")
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
    card = build(tables, as_of=as_of, config=config, legs_rows=legs_rows(args.output_dir))
    card["drops"] = drops(card, config.floor)
    if args.base:
        # Recomputed here, never read from output/regression_report.csv, which can be stale.
        try:
            rows = build_report(args.repo, args.base, args.output_dir, config.diagnosis)
        except RegressionInputError as exc:
            print(f"ABORTED: {exc}", file=sys.stderr)
            return 2
        left = unexplained(rows, config.diagnosis, settled_keys(read_csv(args.ledger)))
        card["metrics"]["D.unexplained_regressions"] = len({r["sec_id"] for r in left})
    for name, value in sorted(card["metrics"].items()):
        print(f"{name:48} {value}")
    for line in card["drops"]:
        print(f"DROP {line}")
    for line in card["golden_failures"]:
        print(f"GOLDEN FAILING {line}")
    for line in card["diagnosis_failures"]:
        print(f"DIAGNOSIS FAILING {line}")
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
    if args.check and (card["drops"] or card["golden_failures"] or card["diagnosis_failures"]
                       or card["metrics"].get("D.unexplained_regressions", 0) > 0):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

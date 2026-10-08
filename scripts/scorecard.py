"""Recompute the scorecard from the tables under --output-dir and compare it to
the floor in --config (spec: Delist Library Reset, step 1 "Measure first").

  python scripts/scorecard.py                    # every number, then drops and failing golden cases
  python scripts/scorecard.py --check            # exit 1 if a floored number got worse, a golden pass case fails or a
                                                 # diagnosis pass case fails
  python scripts/scorecard.py --check --base REV # also recompute the regression report against commit REV (a sub-plan's
                                                 # base) and fail on a regression the --ledger has not settled
                                                 # (D.unexplained_regressions, `loop_round.unexplained`)
  python scripts/scorecard.py --write            # also rewrite <output-dir>/scorecard.json
  python scripts/scorecard.py --raise-floor      # move the config's floor to every better number (never worse)
  python scripts/scorecard.py --flip             # the flip rule on both truth sets: every known_wrong golden and
                                                 # diagnosis case these tables now match becomes pass
                                                 # (`scorecard.flip`)
  python scripts/scorecard.py --lifecycles l.csv # one row per input ticker and per security

Offline. The tables, the run date (run_manifest.json's as_of; today when
there is no manifest) and the base commit's contract are read as run snapshots
(`run_snapshot.RunSnapshot`). Exit 2: a bad config or truth file, or tables
that cannot be read.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.atomic_io import write_atomic
from delist_detection.lifecycle import LifecycleView
from delist_detection.loop_round import Loop, unexplained
from delist_detection.scorecard import (ScorecardConfigError, build, drops, flip, load_config, raise_floor, write)
from delist_detection.run_snapshot import RunSnapshot, SnapshotError
from delist_detection.truth import TruthFileError
from delist_detection.truth_set import read_ledger

LIFECYCLE_COLUMNS = ("unit", "key", "sec_id", "kind", "quality", "chain", "final_delist_date", "final_bucket")


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


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--config", type=Path, default=ROOT / "data" / "scorecard.json")
    p.add_argument("--check", action="store_true")
    p.add_argument("--write", action="store_true")
    p.add_argument("--base", help="a commit: recompute the regression report against it and count "
                   "D.unexplained_regressions (without it there is no such metric)")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--ledger", type=Path, default=Loop.of(ROOT).ledger, help="the diagnosis loop's diagnosed.csv")
    p.add_argument("--raise-floor", action="store_true")
    p.add_argument("--flip", action="store_true", help="every known_wrong golden and diagnosis case the tables now "
                   "match becomes pass, its fixed_by cleared (truth.now_right, the one flip rule)")
    p.add_argument("--lifecycles", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        run = RunSnapshot.read(args.output_dir)
        card = build(run, config=config)          # each table is read when a line first asks for it
    except (ScorecardConfigError, TruthFileError, SnapshotError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    card["drops"] = drops(card, config.floor)
    left = None
    if args.base:
        try:
            left = unexplained(RunSnapshot.at(args.repo, args.base, args.output_dir), run, config.diagnosis,
                               read_ledger(args.ledger))
        except (SnapshotError, TruthFileError, ValueError, OSError) as exc:
            print(f"ABORTED: {exc}", file=sys.stderr)
            return 2
        card["metrics"].update(left.line())
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
        write_atomic(args.lifecycles, _csv_text(LIFECYCLE_COLUMNS, lifecycle_rows(LifecycleView(run))))
        print(f"wrote {args.lifecycles}")
    if args.flip:
        try:
            flipped = flip(run, config)
        except (TruthFileError, OSError) as exc:
            print(f"ABORTED: {exc}", file=sys.stderr)
            return 2
        for name, ids in (("golden", flipped.golden), ("diagnosis", flipped.diagnosis)):
            print(f"flipped {len(ids)} {name} case(s) to pass" + (f": {', '.join(ids)}" if ids else ""))
    if args.raise_floor:
        raw = json.loads(args.config.read_text(encoding="utf-8"))
        raw["floor"] = raise_floor(card, config.floor)
        write_atomic(args.config, json.dumps(raw, indent=2) + "\n")
        print(f"raised the floor in {args.config}")
    if args.check and (card["drops"] or card["golden_failures"] or card["diagnosis_failures"]
                       or (left is not None and not left.passes)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

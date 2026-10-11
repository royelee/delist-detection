"""Draw the accuracy audit's sample (decision 17) from the tables under
--output-dir into a truth worksheet for a person to fill in from sources: a
census of every high-impact ending plus --random input tickers drawn with
--seed. Offline. Refuses to overwrite --out.

  python scripts/draw_audit_sample.py --out data/accuracy_audit.csv
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.measurement.audit import census, random_sample, worksheet_rows
from delist_detection.measurement.lifecycle import LifecycleView
from delist_detection.outputs.run_snapshot import RunSnapshot
from delist_detection.measurement.scorecard import ScorecardConfigError, load_config
from delist_detection.measurement.truth import TruthFileError, write_truth


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--config", type=Path, default=ROOT / "data" / "scorecard.json")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--random", type=int, default=100)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)
    if args.out.exists():
        print(f"ABORTED: {args.out} exists; the audit is drawn once (move it aside to redraw)", file=sys.stderr)
        return 2
    try:
        window = load_config(args.config).window
        view = LifecycleView(RunSnapshot.read(args.output_dir))
    except (ScorecardConfigError, TruthFileError, ValueError, OSError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    targets, skipped = census(view, window)
    targets += random_sample(view, {t.sec_id for t in targets}, args.random, args.seed)
    write_truth(args.out, worksheet_rows(view, targets))
    for group, n in sorted(Counter(t.group for t in targets).items()):
        print(f"{group:28} {n}")
    for line in skipped:
        print(f"SKIPPED (no anchor) {line}")
    print(f"wrote {args.out}: {len(targets)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())

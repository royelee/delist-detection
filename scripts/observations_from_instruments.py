"""Turn a `(ticker, start, end)` instruments file into observations (two per row).

    PYTHONPATH=src python scripts/observations_from_instruments.py --instruments all.txt --out obs.csv
"""
from __future__ import annotations

import argparse
import sys

from delist_detection.observations import observations_from_instruments, write_observations


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--instruments", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    n = write_observations(observations_from_instruments(args.instruments), args.out)
    print(f"Wrote {args.out}: {n} observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())

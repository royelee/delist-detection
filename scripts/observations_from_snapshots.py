"""Turn folders of dated snapshot CSVs (ticker, name columns; date in the file
name) into an observations CSV for classify_universe.py.

    PYTHONPATH=src python scripts/observations_from_snapshots.py \
        --dir ../qlib_practice/fetch_data_aplha/data/ishares_russell_1000/raw \
        --dir ../qlib_practice/fetch_data_aplha/data/ishares_russell_1000/wikipedia_russell/raw \
        --where asset_class=Equity --out data/observations.csv
"""
from __future__ import annotations

import argparse
import sys

from delist_detection.observations import observations_from_snapshots, write_observations


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", action="append", required=True, help="folder of dated snapshot CSVs (repeatable)")
    p.add_argument("--where", action="append", default=[], help="COLUMN=VALUE row filter (repeatable); "
                   "a file without that column keeps all rows")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    where = dict(w.split("=", 1) for w in args.where)
    obs = []
    for d in args.dir:
        obs += observations_from_snapshots(d, where=where or None)
    n = write_observations(obs, args.out)
    print(f"Wrote {args.out}: {n} observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())

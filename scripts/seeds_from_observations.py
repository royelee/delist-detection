"""Reduce an observations CSV to seeds (spec: "What crosses the boundary", In:
seeds.csv): one row per introduction of a ticker -- its first snapshot, a return
after a snapshot it was missing from, or a new name (names.names_agree fails
against the name it had in its previous snapshot). The snapshot calendar is the
set of as_of dates in the file. Reset-3 runs classify_universe.py on this file to
measure what passing seeds only would cost (roadmap: "Risk to measure first").

    PYTHONPATH=src python scripts/seeds_from_observations.py --observations data/observations.csv --out seeds.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict

from delist_detection.vocabulary.names import names_agree


def seeds(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    days = sorted({r["as_of"] for r in rows})
    before = {d: days[i - 1] for i, d in enumerate(days) if i}
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_ticker[r["ticker"]].append(r)
    out = []
    for ticker in sorted(by_ticker):
        rs = sorted(by_ticker[ticker], key=lambda r: r["as_of"])
        seen = {r["as_of"] for r in rs}
        prev = None
        for r in rs:
            renamed = prev is not None and r["name"] and prev["name"] and not names_agree(r["name"], prev["name"])
            if prev is None or before.get(r["as_of"]) not in seen or renamed:
                out.append(r)
            prev = r
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--observations", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    with open(args.observations, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields, rows = reader.fieldnames or [], list(reader)
    out = seeds(rows)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {args.out}: {len(out)} seeds from {len(rows)} observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())

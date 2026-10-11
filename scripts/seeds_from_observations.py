"""Reduce an observations CSV to seeds (spec: "What crosses the boundary", In:
seeds.csv): one row per introduction of a ticker -- its first snapshot, a return
after a snapshot it was missing from, or a new name (names.names_agree fails
against the name it had in its previous snapshot). The snapshot calendar is the
set of as_of dates in the file. Two more reasons make a row a seed: an identifier
column (cusip, cik, sec_id) whose non-blank value differs from the last non-blank one the
ticker carried; and, with --security-history (a previous run's
contract/security_history.csv), a change in the set of securities holding the ticker
between the ticker's previous snapshot and this one (not both empty). The second needs
two passes for a first run: seeds, a run, seeds again with that run's history. Reset-3 runs classify_universe.py on this file to
measure what passing seeds only would cost (roadmap: "Risk to measure first").

    PYTHONPATH=src python scripts/seeds_from_observations.py --observations data/observations.csv --out seeds.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict

from delist_detection.vocabulary.identifiers import normalize_ticker
from delist_detection.vocabulary.names import names_agree


PINS = ("cusip", "cik", "sec_id")
HISTORY_COLUMNS = ("sec_id", "start_date", "end_date", "ticker")


def index_history(history: list[dict[str, str]]) -> dict[str, list[tuple[str, str, str]]]:
    """ticker -> [(sec_id, start_date, end_date)], built once."""
    spans: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for h in history:
        spans[normalize_ticker(h["ticker"])].append((h["sec_id"], h["start_date"], h["end_date"]))
    return spans


def holders(history: list[dict[str, str]] | dict, ticker: str, day: str) -> frozenset[str]:
    """The sec_ids whose history row has this ticker and a span containing the day (end blank = open)."""
    spans = history if isinstance(history, dict) else index_history(history)
    return frozenset(s for s, start, end in spans.get(normalize_ticker(ticker), ()) if start <= day and (not end or end >= day))


def seeds(rows: list[dict[str, str]], history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    days = sorted({r["as_of"] for r in rows})
    before = {d: days[i - 1] for i, d in enumerate(days) if i}
    spans = index_history(history) if history is not None else None
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_ticker[r["ticker"]].append(r)
    out = []
    for ticker in sorted(by_ticker):
        rs = sorted(by_ticker[ticker], key=lambda r: r["as_of"])
        seen = {r["as_of"] for r in rs}
        prev = None
        last_pin: dict[str, str] = {}
        for r in rs:
            renamed = prev is not None and r["name"] and prev["name"] and not names_agree(r["name"], prev["name"])
            pin_changed = False
            for col in PINS:
                v = r.get(col) or ""
                if v:
                    pin_changed = pin_changed or (col in last_pin and last_pin[col] != v)
                    last_pin[col] = v
            held_changed = False
            if spans is not None and prev is not None:
                now, then = holders(spans, ticker, r["as_of"]), holders(spans, ticker, prev["as_of"])
                held_changed = now != then
            if prev is None or before.get(r["as_of"]) not in seen or renamed or pin_changed or held_changed:
                out.append(r)
            prev = r
    return out


def read_history(path: str) -> list[dict[str, str]] | None:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in HISTORY_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            print(f"{path}: missing column {', '.join(missing)}", file=sys.stderr)
            return None
        return list(reader)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--observations", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--security-history", default=None,
                   help="a previous run's contract/security_history.csv: a row is also a seed where the "
                        "security holding its ticker changed since the ticker's previous snapshot")
    args = p.parse_args()
    history = None
    if args.security_history:
        history = read_history(args.security_history)
        if history is None:
            return 2
    with open(args.observations, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields, rows = reader.fieldnames or [], list(reader)
    out = seeds(rows, history)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {args.out}: {len(out)} seeds from {len(rows)} observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())

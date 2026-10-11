"""Reduce an observations CSV to seeds (spec: "What crosses the boundary", In:
seeds.csv): one row per introduction of a ticker -- its first snapshot, a return
after a snapshot it was missing from, or a new name (names.names_agree fails
against the name it had in its previous snapshot). The snapshot calendar is the
set of as_of dates in the file. More reasons make a row a seed: an identifier
column (cusip, cik, sec_id) whose non-blank value differs from the last non-blank one the
ticker carried; the share class its name states (identifiers.share_class_from_name) differing
from the class its previous row's name stated, both names non-blank ("DISCOVERY HOLDING CO"
to "DISCOVERY INC SERIES A", which names_agree calls one name); and, with --security-history
(a previous run's contract/security_history.csv), a change in the set of securities holding
the ticker between the ticker's previous snapshot and this one (not both empty), and the row
after a row that was a seed by that rule while nobody held the ticker on its date (the first
snapshot after a ticker changed hands can fall in the days nobody holds it, GCI 2015-06-30;
one extra seed per run of unheld snapshots). Reset-3 runs classify_universe.py on this file to
measure what passing seeds only would cost (roadmap: "Risk to measure first").
A name the observation file cuts inside its class words ("TWENTY FIRST CENTURY FOX INC CLASS") reads as common
stock, so the first snapshot whose name carries the full class words ("FOX CORP CLASS A") is a seed.

The history rules read a run, and a run reads seeds, so a seed file built from one run's history depends on which run
that was. --fixed-point DIR removes that choice: the seeds without a history, a run on them, the seeds with that
run's history added to the ones already chosen, and again, until a pass adds no seed. A seed once chosen stays (it
is one of the caller's own rows), so the loop ends; the file depends only on the observations, the code and the
cache the runs read. Each pass k writes DIR/seeds-k.csv and runs classify_universe.py into DIR/run-k with the
arguments after `--`; the last run is the seeds-only run on the file written to --out.

    PYTHONPATH=src python scripts/seeds_from_observations.py --observations data/observations.csv --out seeds.csv
    PYTHONPATH=src python scripts/seeds_from_observations.py --observations data/observations.csv --out seeds.csv \\
        --fixed-point fp -- --as-of 2026-09-25 --cache-dir cache-seeds --extract-merger-terms-llm
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

from delist_detection.vocabulary.identifiers import normalize_ticker, share_class_from_name
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


def _by_ticker(rows: list[dict[str, str]]) -> list[tuple[str, list[dict[str, str]]]]:
    """(ticker, its rows by date), tickers in sorted order: the order seeds are written in."""
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_ticker[r["ticker"]].append(r)
    return [(t, sorted(by_ticker[t], key=lambda r: r["as_of"])) for t in sorted(by_ticker)]


def seeds(rows: list[dict[str, str]], history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    days = sorted({r["as_of"] for r in rows})
    before = {d: days[i - 1] for i, d in enumerate(days) if i}
    spans = index_history(history) if history is not None else None
    out = []
    for ticker, rs in _by_ticker(rows):
        seen = {r["as_of"] for r in rs}
        prev = None
        last_pin: dict[str, str] = {}
        prev_by_holders = False         # the previous row became a seed by the holder rule
        for r in rs:
            renamed = prev is not None and r["name"] and prev["name"] and not names_agree(r["name"], prev["name"])
            pin_changed = False
            for col in PINS:
                v = r.get(col) or ""
                if v:
                    pin_changed = pin_changed or (col in last_pin and last_pin[col] != v)
                    last_pin[col] = v
            reclassed = (prev is not None and bool(r["name"]) and bool(prev["name"])
                         and share_class_from_name(r["name"]) != share_class_from_name(prev["name"]))
            held_changed = after_unheld = False
            if spans is not None and prev is not None:
                now, then = holders(spans, ticker, r["as_of"]), holders(spans, ticker, prev["as_of"])
                held_changed = now != then
                after_unheld = prev_by_holders and not then
            if (prev is None or before.get(r["as_of"]) not in seen or renamed or pin_changed or held_changed
                    or reclassed or after_unheld):
                out.append(r)
            prev, prev_by_holders = r, held_changed
    return out


class NoFixedPoint(Exception):
    pass


def fixed_point(rows: list[dict[str, str]], run: Callable[[list[dict[str, str]], int], list[dict[str, str]]],
                max_passes: int = 8, on_pass: Callable[[dict[str, int]], None] | None = None,
                ) -> tuple[list[dict[str, str]], list[dict[str, int]]]:
    """Seeds no run's history adds to: pass k runs on the seeds so far and adds the seeds its history calls for.
    run(seed_rows, k) returns that run's security history rows. Returns the seeds (in seeds()' order, the caller's
    own row objects) and one {pass, seeds, added} per pass, each also given to on_pass as it is made; raises
    NoFixedPoint if pass max_passes still added."""
    chosen = {id(r) for r in seeds(rows)}
    passes = []
    for k in range(1, max_passes + 1):
        current = [r for _, rs in _by_ticker(rows) for r in rs if id(r) in chosen]
        history = run(current, k)
        added = [r for r in seeds(rows, history) if id(r) not in chosen]
        passes.append({"pass": k, "seeds": len(current), "added": len(added)})
        if on_pass:
            on_pass(passes[-1])
        if not added:
            return current, passes
        chosen.update(id(r) for r in added)
    raise NoFixedPoint(f"no fixed point after {max_passes} passes: the last pass added {passes[-1]['added']} seeds")


def read_history(path: str) -> list[dict[str, str]] | None:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in HISTORY_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            print(f"{path}: missing column {', '.join(missing)}", file=sys.stderr)
            return None
        return list(reader)


CLASSIFY = Path(__file__).resolve().parent / "classify_universe.py"
RUN_OWNS = ("--observations", "--output-dir")      # set by the fixed point for each pass
COMPLETED = (0, 3)                                 # classify_universe.py exit codes of a run that wrote its tables


def run_classify(seed_path: Path, out_dir: Path, run_args: list[str], log_path: Path) -> int:
    with open(log_path, "w") as log:
        return subprocess.run([sys.executable, str(CLASSIFY), "--observations", str(seed_path),
                               "--output-dir", str(out_dir), *run_args], stdout=log, stderr=subprocess.STDOUT).returncode


class _RunFailed(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _write(path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _run_passes(rows, fields, work: Path, run_args: list[str], max_passes: int):
    work.mkdir(parents=True, exist_ok=True)
    exits: list[int] = []
    done: list[dict] = []

    def on_pass(record):
        done.append({**record, "exit": exits[-1]})
        _write(work / "passes.csv", ["pass", "seeds", "added", "exit"], done)
        print(f"pass {record['pass']}: {record['added']} seeds added", flush=True)

    def run(seed_rows, k):
        seed_path, out_dir, log_path = work / f"seeds-{k}.csv", work / f"run-{k}", work / f"run-{k}.log"
        _write(seed_path, fields, seed_rows)
        print(f"pass {k}: {len(seed_rows)} seeds, running into {out_dir}", flush=True)
        code = run_classify(seed_path, out_dir, run_args, log_path)
        if code not in COMPLETED:
            raise _RunFailed(code, f"pass {k}: classify_universe.py exited {code}; log {log_path} (run-{k})")
        exits.append(code)
        history = read_history(str(out_dir / "contract" / "security_history.csv"))
        if history is None:
            raise _RunFailed(2, f"pass {k}: run-{k} wrote no readable security history")
        return history

    return fixed_point(rows, run, max_passes, on_pass)


def main() -> int:
    argv = sys.argv[1:]
    run_args = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[:argv.index("--")] if "--" in argv else argv
    p = argparse.ArgumentParser()
    p.add_argument("--observations", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--security-history", default=None,
                   help="a previous run's contract/security_history.csv: a row is also a seed where the "
                        "security holding its ticker changed since the ticker's previous snapshot")
    p.add_argument("--fixed-point", type=Path, default=None, metavar="DIR",
                   help="run classify_universe.py on the seeds pass by pass (arguments after --), adding the "
                        "seeds each run's history calls for, until a pass adds none")
    p.add_argument("--max-passes", type=int, default=8)
    args = p.parse_args(argv)
    if args.fixed_point and args.security_history:
        print("--fixed-point starts from no history; drop --security-history", file=sys.stderr)
        return 2
    owned = [a for a in run_args if a.split("=")[0] in RUN_OWNS]
    if owned:
        print(f"--fixed-point sets {', '.join(RUN_OWNS)} for each pass; drop {', '.join(owned)}", file=sys.stderr)
        return 2
    history = None
    if args.security_history:
        history = read_history(args.security_history)
        if history is None:
            return 2
    with open(args.observations, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields, rows = reader.fieldnames or [], list(reader)
    if args.fixed_point:
        try:
            out, passes = _run_passes(rows, fields, args.fixed_point, run_args, args.max_passes)
        except _RunFailed as exc:
            print(exc, file=sys.stderr)
            return exc.code
        except NoFixedPoint as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"fixed point after {len(passes)} passes; the seeds-only run on it is {args.fixed_point / f'run-{len(passes)}'}")
    else:
        out = seeds(rows, history)
    _write(args.out, fields, out)
    print(f"Wrote {args.out}: {len(out)} seeds from {len(rows)} observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())

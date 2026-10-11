"""Compare a seeds-only run with a full run of classify_universe.py made on the same code and cache: what the
seeds-only run loses or changes (docs/superpowers/plans/2026-10-10-seeds-only-parity.md).

  python scripts/seeds_parity.py --full out-full --seeds out-seeds                 # the parity numbers
  python scripts/seeds_parity.py --full out-full --seeds out-seeds --cases cases/  # also one CSV of cases per number
  python scripts/seeds_parity.py --full out-full --seeds out-seeds --check         # exit 1 if a number is above its
                                                                                   # floor in --floor (data/seeds_parity.json)
  python scripts/seeds_parity.py --full out-full --seeds out-seeds --write-floor   # lower the floor to today's numbers

Offline. Reads each folder's contract/delistings.csv, contract/seeds.csv, securities.csv (sec_id, observed) and
scorecard.json. The numbers are the endings and securities one run has and the other lacks, the endings whose kind or
value or date changed, the seeds placed differently, the truth cases failing only in the seeds run, and
observed_flag_differs (the securities both runs have whose `observed` flag differs: reported and printed, never floored).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FLOOR = ROOT / "data" / "seeds_parity.json"
DLRET_TOL = 0.0005          # two runs' LLM answers can differ in the last digit of a ratio (NVRI, PXP)
SCORE_KEYS = ("L1.coverage_tickers", "L1.coverage_securities", "L1.left_view", "L1.closed_no_event")
# Reported, never floored: a line the seeds-only run derives from the fails rows is unobserved there and observed in a
# full run (the caller kept observing it), so the number says how many of the full run's lines are derived.
NOT_FLOORED = ("observed_flag_differs",)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _has_column(path: Path, column: str) -> bool:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return column in (next(csv.reader(fh), None) or [])


def _kind(row: dict[str, str]) -> str:
    """The contract's exit kind, with a continuation told apart from a plain exchange."""
    cont = (row.get("continuation") or "").strip().lower() not in ("", "0", "false")
    return (row.get("exit_kind") or "blank") + ("/continuation" if cont else "")


def _differs(a: str, b: str) -> bool:
    if not a or not b:
        return a != b
    return abs(float(a) - float(b)) > DLRET_TOL


def _metric(metrics: dict, key: str):
    """`key` is dotted, and so are some of the scorecard's own keys ("R1.1"): try every split."""
    parts = key.split(".")

    def go(node, i):
        if i == len(parts):
            return node
        if not isinstance(node, dict):
            return None
        for j in range(len(parts), i, -1):
            k = ".".join(parts[i:j])
            if k in node:
                found = go(node[k], j)
                if found is not None:
                    return found
        return None
    return go(metrics, 0)


def parity(full: Path, seeds: Path) -> dict:
    """The parity numbers (`numbers`), the cases behind each (`cases`) and the two scorecards' lines (`scores`)."""
    f_end = {r["sec_id"]: r for r in _rows(full / "contract" / "delistings.csv")}
    s_end = {r["sec_id"]: r for r in _rows(seeds / "contract" / "delistings.csv")}
    f_obs = {r["sec_id"]: r.get("observed", "") for r in _rows(full / "securities.csv")}
    s_obs = {r["sec_id"]: r.get("observed", "") for r in _rows(seeds / "securities.csv")}
    f_sec, s_sec = set(f_obs), set(s_obs)
    no_flag = [name for name, folder in (("full", full), ("seeds", seeds))
               if not _has_column(folder / "securities.csv", "observed")]
    for name in no_flag:      # the flag cannot be compared: say so, count nothing
        print(f"seeds_parity: the {name} run's securities.csv has no observed column; "
              "observed_flag_differs was not computed", file=sys.stderr)
    f_seed = {(r["ticker"], r["as_of"]): r["sec_id"] for r in _rows(full / "contract" / "seeds.csv")}
    s_seed = {(r["ticker"], r["as_of"]): r["sec_id"] for r in _rows(seeds / "contract" / "seeds.csv")}
    f_card = json.loads((full / "scorecard.json").read_text())
    s_card = json.loads((seeds / "scorecard.json").read_text())

    def ending(sec_id: str, row: dict[str, str]) -> dict[str, str]:
        return {"sec_id": sec_id, "kind": _kind(row), "last_trade_date": row["last_trade_date"],
                "dlret": row["dlret"], "verdict": row["verdict"]}

    def pair(sec_id: str) -> dict[str, str]:
        a, b = f_end[sec_id], s_end[sec_id]
        return {"sec_id": sec_id, "full_kind": _kind(a), "seeds_kind": _kind(b),
                "full_last_trade_date": a["last_trade_date"], "seeds_last_trade_date": b["last_trade_date"],
                "full_dlret": a["dlret"], "seeds_dlret": b["dlret"],
                "full_verdict": a["verdict"], "seeds_verdict": b["verdict"]}

    both = sorted(set(f_end) & set(s_end))
    f_fail = set(map(str, f_card["golden_failures"] + f_card["diagnosis_failures"]))
    s_fail = set(map(str, s_card["golden_failures"] + s_card["diagnosis_failures"]))
    case_id = lambda line: line.split(":", 1)[0]
    cases = {
        "endings_lost": [ending(k, f_end[k]) for k in sorted(f_end) if k not in s_end and k in s_sec],
        "endings_gained": [ending(k, s_end[k]) for k in sorted(s_end) if k not in f_end and k in f_sec],
        "kind_changed": [pair(k) for k in both if _kind(f_end[k]) != _kind(s_end[k])],
        "value_or_date_changed": [pair(k) for k in both if _kind(f_end[k]) == _kind(s_end[k])
                                  and (_differs(f_end[k]["dlret"], s_end[k]["dlret"])
                                       or f_end[k]["last_trade_date"] != s_end[k]["last_trade_date"]
                                       or f_end[k]["verdict"] != s_end[k]["verdict"])],
        "securities_lost": [{"sec_id": k, "full_ending": _kind(f_end[k]) if k in f_end else ""}
                            for k in sorted(f_sec - s_sec)],
        "securities_gained": [{"sec_id": k, "seeds_ending": _kind(s_end[k]) if k in s_end else ""}
                              for k in sorted(s_sec - f_sec)],
        "observed_flag_differs": [{"sec_id": k, "full_observed": f_obs[k], "seeds_observed": s_obs[k]}
                                  for k in sorted(f_sec & s_sec) if not no_flag and f_obs[k] != s_obs[k]],
        "seeds_placed_differently": [{"ticker": t, "as_of": d, "full_sec_id": f_seed.get((t, d), ""),
                                      "seeds_sec_id": sid}
                                     for (t, d), sid in sorted(s_seed.items()) if f_seed.get((t, d), "") != sid],
        "truth_cases_failing_only_in_seeds": [{"case": line} for line in sorted(s_fail)
                                              if case_id(line) not in {case_id(x) for x in f_fail}],
    }
    scores = {k: {"full": _metric(f_card["metrics"], k), "seeds": _metric(s_card["metrics"], k)} for k in SCORE_KEYS}
    return {"numbers": {name: len(rows) for name, rows in cases.items()}, "cases": cases, "scores": scores}


def drops(numbers: dict[str, int], floor: dict[str, int]) -> list[str]:
    """The numbers above their floor (a number the floor does not name has none)."""
    return [f"{k}: {floor[k]} -> {v}" for k, v in sorted(numbers.items())
            if k in floor and k not in NOT_FLOORED and v > floor[k]]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--full", required=True, type=Path, help="the full run's output folder")
    p.add_argument("--seeds", required=True, type=Path, help="the seeds-only run's output folder")
    p.add_argument("--cases", type=Path, help="write one CSV of cases per number into this folder")
    p.add_argument("--floor", type=Path, default=DEFAULT_FLOOR)
    p.add_argument("--check", action="store_true", help="exit 1 if a number is above its floor")
    p.add_argument("--write-floor", action="store_true", help="lower the floor to today's numbers (never raise it)")
    args = p.parse_args(argv)
    try:
        result = parity(args.full, args.seeds)
    except (OSError, KeyError, ValueError) as exc:
        print(f"seeds_parity: cannot read the runs: {exc!r}", file=sys.stderr)
        return 2
    for k, v in result["scores"].items():
        print(f"{k:38} full {v['full']}   seeds {v['seeds']}")
    for k, v in result["numbers"].items():
        print(f"{k:38} {v}")
    if args.cases:
        args.cases.mkdir(parents=True, exist_ok=True)
        for name, rows in result["cases"].items():
            with (args.cases / f"{name}.csv").open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["sec_id"], lineterminator="\n")
                w.writeheader()
                w.writerows(rows)
    floor = json.loads(args.floor.read_text()) if args.floor.exists() else {}
    worse = drops(result["numbers"], floor)
    for line in worse:
        print(f"parity drop: {line}", file=sys.stderr)
    if args.write_floor:
        new = {k: min(v, floor.get(k, v)) for k, v in result["numbers"].items() if k not in NOT_FLOORED}
        args.floor.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")
        print(f"Wrote {args.floor}")
    return 1 if args.check and worse else 0


if __name__ == "__main__":
    sys.exit(main())

# src/delist_detection/manifest.py
"""run_manifest.json: what one run of the pipeline rested on.

Written next to the seven tables, and only after them: a run that aborts leaves the
previous manifest in place, like the previous tables. It records:
- the run date every freshness rule used (`as_of`);
- the code that ran and the worker count;
- the SEC traffic behind the tables: requests sent and answers read from cache
  per endpoint, per-endpoint latency, and every answer that rested on a failed
  request or a stale copy.
So two runs over the same observations can be told apart when their tables differ.

The manifest is not part of the byte-identical-output guarantee: it carries the
run date, the code version and the worker count, so it is expected to differ
between two runs even when their seven tables come out identical.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date
from functools import lru_cache
from pathlib import Path

from .atomic_io import write_atomic

MANIFEST_NAME = "run_manifest.json"
_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def code_version() -> str:
    """`git describe --always --dirty` of the checkout this module runs from, or
    "unknown" when that cannot be read (no git, not a checkout)."""
    try:
        out = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=_ROOT,
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    version = out.stdout.strip()
    return version if out.returncode == 0 and version else "unknown"


def _by_prefix(counts: dict[str, int], prefix: str) -> dict[str, int]:
    return {k[len(prefix):]: v for k, v in sorted(counts.items()) if k.startswith(prefix)}


def _latency(timings: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for endpoint, seconds in sorted(timings.items()):
        ms = sorted(s * 1000.0 for s in seconds)
        out[endpoint] = {"n": len(ms), "p50": round(ms[(len(ms) - 1) // 2], 1),
                         "p95": round(ms[min(len(ms) - 1, int(0.95 * len(ms)))], 1), "max": round(ms[-1], 1)}
    return out


def build(*, as_of: date, sec_workers: int, counts: dict[str, int], timings: dict[str, list[float]],
          stages: dict[str, dict[str, int]], review_flags: dict[str, int], review: dict[str, int]) -> dict:
    """The manifest of one run. `counts` and `timings` are sec_stats.SEC_STATS.since()
    of the run's start; `stages` is the pipeline's per-stage meter. `warm_failed`
    reports, per warm pass, how many items a worker thread failed on (the
    sequential pass meets and records the same failures itself; a nonzero count
    here only flags a concurrency-only failure worth a second look). `degraded_answers`
    counts only the sequential pass's own degraded reads; a warm/fill-only
    thread's degraded reads are counted separately, under `warm_degraded`
    (`sec_stats.RequestStats.degraded`, `sec_stats.filling_only`). `review` is
    `review_triage.triage()`'s own counts (fix/check/info_hidden/accepted/
    cleared/unmatched_decisions); `review_flags` (used only for
    `resolution_degraded` below) is the flag tally from *before* triage or
    decisions, so exit code 3 always sees every `error`/`resolution_degraded`."""
    return {
        "as_of": as_of.isoformat(),
        "code_version": code_version(),
        "sec_workers": sec_workers,
        "sec_requests": _by_prefix(counts, "request:"),
        "cache_answers": _by_prefix(counts, "cache:"),
        "degraded_answers": _by_prefix(counts, "degraded:"),
        "warm_degraded": _by_prefix(counts, "warm_degraded:"),
        "rejected_queries": _by_prefix(counts, "rejected:"),
        "not_covered": _by_prefix(counts, "not_covered:"),
        "warm_failed": _by_prefix(counts, "warm_failed:"),
        "latency_ms": _latency(timings),
        "stages": stages,
        "resolution_degraded": review_flags.get("resolution_degraded", 0),
        "review": review,
    }


def write(out_dir: str | Path, manifest: dict) -> Path:
    path = Path(out_dir) / MANIFEST_NAME
    write_atomic(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path

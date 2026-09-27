"""The counters behind run_manifest.json (`SEC_STATS`, a `RequestStats`): SEC
requests and cache answers per endpoint (`endpoint_of`), latency, and answers
that rested on a failed request or a stale copy; and fill-only mode
(`fill_only`), in which a prefetch thread only fills missing cache entries."""
from __future__ import annotations

import threading
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass


_FILL_ONLY = threading.local()


@contextmanager
def fill_only():
    """On the calling thread, EDGAR reads fill missing cache entries but never
    replace an existing one: a copy older than the caller's `fresh_after`, or an
    expired search answer, is returned as it is, with no request.
    `prefetch.warm` runs every task inside this. A warm pass therefore only adds
    answers the sequential pass would fetch the same way itself, and every
    refresh happens in the sequential pass, in its own order, exactly as in a
    one-thread run (spec §11: same inputs and caches -> byte-identical CSVs)."""
    prev = getattr(_FILL_ONLY, "on", False)
    _FILL_ONLY.on = True
    try:
        yield
    finally:
        _FILL_ONLY.on = prev


def filling_only() -> bool:
    """True inside `fill_only()` on this thread."""
    return getattr(_FILL_ONLY, "on", False)


def endpoint_of(url: str) -> str:
    """The EDGAR endpoint a URL belongs to, as run_manifest.json counts requests.
    Everything that is not an EDGAR endpoint (fails-to-deliver and MIDAS ZIPs and
    their index pages) is `sec_data`."""
    if "efts.sec.gov" in url:
        return "full_text_search"
    if "/cgi-bin/browse-edgar" in url:
        return "company_search"
    if "/submissions/CIK" in url and "-submissions-" not in url:
        return "submissions"
    if "/submissions/" in url:
        return "submissions_page"
    if "/Archives/edgar/" in url:
        return "archives"
    if url.endswith("/company_tickers.json"):
        return "company_tickers"
    return "sec_data"


@dataclass(frozen=True)
class StatsMark:
    counts: dict
    timing_lengths: dict


class RequestStats:
    """The counters behind run_manifest.json, shared by every thread of the
    process: requests sent and answers read from cache, per endpoint
    ("request:<endpoint>", "cache:<endpoint>"); answers that rest on a failed
    request or a stale copy ("degraded:<what>", or "warm_degraded:<what>" on a
    fill-only/warm thread -- see `filling_only()` -- so `degraded_answers`
    reflects only what the sequential pass relied on); and each request's
    latency. A run reports the change since a `snapshot()`. `degraded()` also
    counts on the calling thread alone (`thread_degraded()`), so the pipeline
    can tell which era or security a degraded answer served."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter = Counter()
        self._timings: dict[str, list[float]] = defaultdict(list)
        self._local = threading.local()

    def add(self, key: str) -> None:
        with self._lock:
            self._counts[key] += 1

    def timing(self, endpoint: str, seconds: float) -> None:
        with self._lock:
            self._timings[endpoint].append(seconds)

    def degraded(self, what: str, *, sec: bool = True) -> None:
        """Count an answer that rested on a failed request or a stale copy under
        `what`. With `sec` (an SEC answer) it also counts on the calling thread
        (`thread_degraded`), which the pipeline reads as "a failed SEC request";
        another source's failure (the Nasdaq halt feed) is only counted, and its
        client says itself which read failed."""
        prefix = "warm_degraded" if filling_only() else "degraded"
        self.add(f"{prefix}:{what}")
        if sec:
            self._local.degraded = self.thread_degraded() + 1

    def thread_degraded(self) -> int:
        return getattr(self._local, "degraded", 0)

    def snapshot(self) -> StatsMark:
        with self._lock:
            return StatsMark(dict(self._counts), {k: len(v) for k, v in self._timings.items()})

    def since(self, mark: StatsMark) -> tuple[dict[str, int], dict[str, list[float]]]:
        """(counts, latencies in seconds per endpoint) added since `mark`."""
        with self._lock:
            counts = {k: v - mark.counts.get(k, 0) for k, v in self._counts.items()
                      if v != mark.counts.get(k, 0)}
            timings = {k: list(v[mark.timing_lengths.get(k, 0):]) for k, v in self._timings.items()
                       if len(v) > mark.timing_lengths.get(k, 0)}
        return dict(sorted(counts.items())), dict(sorted(timings.items()))


SEC_STATS = RequestStats()

"""Fill the SEC caches from a thread pool while the pipeline's own logic stays sequential.

Before a sequential stage, `warm` runs that stage's per-item work on worker threads
only for what it fetches. Every request goes through the shared EdgarClient: one
8 requests/s limiter (machine-wide once `edgar.use_machine_wide_limit` has run),
and one lock and one atomic write per cache file. Each task runs under
`edgar.fill_only()`: it may fetch what is missing from the caches but never
refresh what is there, so the sequential pass that follows reads exactly the
copies a one-thread run would read, and refreshes them itself, in its own order.
Results are thrown away, so the tables never depend on thread timing (spec §11:
same inputs and caches -> byte-identical CSVs).
"""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Any

from . import edgar as _edgar
from .edgar import EdgarBlocked, PrefetchCancelled, RateLimiter, fill_only
from .openfigi import OpenFigiBlocked

FATAL = (EdgarBlocked, OpenFigiBlocked)


class Serialized:
    """`obj` behind one lock: each method call runs alone. The warm pass's MIDAS
    and Nasdaq-halt clients keep unlocked state (MidasClient's summary memo and
    fixed-path ZIP download, NasdaqHaltClient's pacing clock), so every warm finder
    shares one Serialized wrapper per client. Attributes that are not callable
    pass through unlocked. The lock is taken before the SEC limiter's and never
    while an EdgarClient file lock is held (MIDAS and the halt feed never touch
    EdgarClient), so it cannot deadlock; an exception, PrefetchCancelled
    included, releases it."""

    def __init__(self, obj: Any) -> None:
        self._obj = obj
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._obj, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            with self._lock:
                return attr(*args, **kwargs)
        return call


def warm(items: Iterable[Any], task: Callable[..., object], *, workers: int,
         state: Callable[[], Any] | None = None, limiter: RateLimiter | None = None) -> int:
    """Run `task(item)` -- or `task(state_obj, item)` when `state` is given -- for
    every item on up to `workers` threads, and return the number of items handed
    to the pool. `limiter` defaults to `edgar.SEC_LIMITER` at call time.

    `state` is called on this thread once per worker; a worker takes one of those
    objects for each item, so an object is never used by two threads at once (a
    shadow resolver, a finder). Every task runs under `edgar.fill_only()`. A task
    that raises an ordinary exception is ignored: the sequential pass meets the
    same failure and records it as it always has. `workers <= 1` warms nothing:
    the sequential pass fetches everything itself, one request at a time.

    A refusal (EdgarBlocked, OpenFigiBlocked) or an interrupt stops the pool: no
    item starts after it, every running worker's next SEC request raises
    PrefetchCancelled instead of going out, and the refusal or interrupt is
    raised here once the workers have stopped. On a first Ctrl-C this function
    waits for the workers; each finishes the one request it has in flight (an
    EDGAR request times out after 30 s without an answer, a SEC data-file
    download such as a MIDAS ZIP after 180 s). A second Ctrl-C during that wait
    interrupts the wait itself and propagates at once, but the workers are not
    daemon threads, so the interpreter still waits for each one's in-flight
    request before the process exits; no queued item starts meanwhile, since the
    stop is set before the wait. Nothing is torn either way: every cache file is
    written atomically, and the tables are written only at the end of a run.
    """
    items = list(items)
    if workers <= 1 or not items:
        return 0
    lim = limiter if limiter is not None else _edgar.SEC_LIMITER
    n = min(workers, len(items))
    states: queue.SimpleQueue = queue.SimpleQueue()
    for _ in range(n):
        states.put(state() if state is not None else None)
    stop = threading.Event()

    def run(item: Any) -> None:
        if stop.is_set():
            return
        obj = states.get()
        try:
            with lim.cancelled_by(stop), fill_only():
                if state is None:
                    task(item)
                else:
                    task(obj, item)
        except PrefetchCancelled:
            pass
        except FATAL:
            stop.set()                     # before this thread can pick up another item
            raise
        except Exception:                  # noqa: BLE001 -- best effort; the sequential pass reports it
            pass
        finally:
            states.put(obj)

    pool = ThreadPoolExecutor(max_workers=n, thread_name_prefix="sec-warm")
    try:
        futures = [pool.submit(run, item) for item in items]
        wait(futures, return_when=FIRST_EXCEPTION)
        for f in futures:                  # the earliest-submitted item's refusal among those raised so far
            if f.done() and not f.cancelled() and f.exception() is not None:
                raise f.exception()
    except BaseException:
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return len(items)

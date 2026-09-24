"""prefetch.warm: runs each item's work on worker threads only to fill the caches;
results are thrown away, ordinary failures ignored, every task is fill-only, and a
refusal or an interrupt stops every worker before its next SEC request.
prefetch.Serialized: one call at a time into a client that is not thread-safe.

The `warm` tests order their threads with barriers and events, never with sleeps,
so a correct `warm` passes whatever the scheduling. Every wait carries HANG as a
timeout only so that a wrong `warm` fails instead of hanging the suite."""
import threading
import time

import pytest

from delist_detection import edgar, prefetch
from delist_detection.edgar import EdgarBlocked, PrefetchCancelled, RateLimiter, filling_only
from delist_detection.openfigi import OpenFigiBlocked
from delist_detection.prefetch import Serialized, warm

HANG = 5.0      # seconds; reached only when the code under test is wrong


class _Clock:
    """Time that passes only when the limiter sleeps on it."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class _Limiter(RateLimiter):
    """An in-process limiter that never waits in real time, and that keeps the stop
    event `warm` hands its workers, so a test can hold a worker until the pool is
    stopping instead of guessing how long that takes."""

    def __init__(self):
        clock = _Clock()
        super().__init__(8.0, clock=clock.now, sleep=clock.sleep)
        self.stop = threading.Event()        # never set: stands in until a worker enters cancelled_by

    def cancelled_by(self, stop):
        self.stop = stop
        return super().cancelled_by(stop)


def _mid_chain(lim, request, outcome, ready):
    """A worker in the middle of a chain of SEC requests, as a resolver makes. One
    request goes out, `ready` is called, and once the pool is stopping the worker
    tries the next request of its chain: that one must never go out."""
    request()
    ready()
    lim.stop.wait(HANG)
    try:
        request()
    except PrefetchCancelled:
        outcome.append("cancelled")
        raise
    outcome.append("sent after the stop")


def test_one_worker_warms_nothing():
    calls = []
    assert warm([1, 2, 3], calls.append, workers=1) == 0
    assert calls == []


def test_every_item_is_warmed_once_and_ordinary_failures_are_ignored():
    seen, guard, after_ran = [], threading.Lock(), threading.Event()

    def task(item):
        with guard:
            seen.append(item)
        if item == "waits":
            after_ran.wait(HANG)     # holds its worker: "after" can only run on the other, once "fails" has failed
        elif item == "fails":
            raise ValueError("a parse error the sequential pass will report")
        else:
            after_ran.set()

    assert warm(["waits", "fails", "after"], task, workers=2, limiter=_Limiter()) == 3
    assert sorted(seen) == ["after", "fails", "waits"]


def test_every_task_runs_fill_only():
    seen, guard = [], threading.Lock()

    def task(item):
        with guard:
            seen.append(filling_only())

    warm([1, 2, 3], task, workers=2, limiter=_Limiter())
    assert seen == [True, True, True] and filling_only() is False


def test_each_worker_gets_its_own_state_object_built_on_the_calling_thread():
    built_on, used, at_once, shared = [], [], {}, []
    together = threading.Barrier(3, timeout=HANG)

    class _State:
        def __init__(self):
            built_on.append(threading.current_thread().name)
            self.busy = threading.Lock()

    def task(state, item):
        if not state.busy.acquire(blocking=False):
            shared.append(item)                # two threads held one state object
            return
        try:
            used.append(id(state))
            if item < 3:                       # the first three items run at once, one per worker
                at_once[item] = id(state)
                together.wait()
        finally:
            state.busy.release()

    warm(range(12), task, workers=3, state=_State, limiter=_Limiter())
    assert built_on == [threading.current_thread().name] * 3
    assert shared == [] and len(used) == 12
    assert len(set(at_once.values())) == 3 and set(used) == set(at_once.values())


@pytest.mark.parametrize("refusal", [EdgarBlocked("SEC returned 403"), OpenFigiBlocked("OpenFIGI returned 401")])
def test_a_refusal_stops_the_pool_and_is_raised(refusal):
    lim = _Limiter()
    in_flight = threading.Barrier(3, timeout=HANG)   # two workers mid-chain, and the one about to be refused
    outcome, refused_on, later = [], [], []

    def task(item):
        if item == "refused":
            in_flight.wait()                   # every other worker has a request out
            refused_on.append(threading.current_thread())
            raise refusal
        if item.startswith("slow"):
            _mid_chain(lim, lim.acquire, outcome, in_flight.wait)
            return
        later.append(item)

    with pytest.raises(type(refusal)) as raised:
        warm(["slow1", "slow2", "refused", "later1", "later2"], task, workers=3, limiter=lim)
    assert raised.value is refusal             # the worker's own refusal reaches the caller, not swallowed
    assert len(refused_on) == 1 and refused_on[0] is not threading.current_thread()   # raised on a worker only
    assert outcome == ["cancelled", "cancelled"]   # every other worker's next request never went out
    assert lim.count == 2                      # only the two requests already out before the refusal
    assert later == []                         # no item started after the refusal


def test_the_process_wide_limiter_is_the_default(monkeypatch):
    lim = _Limiter()
    monkeypatch.setattr(edgar, "SEC_LIMITER", lim)   # swapped after prefetch was imported, as conftest does
    in_flight, outcome = threading.Barrier(2, timeout=HANG), []

    def task(item):
        if item == "refused":
            in_flight.wait()
            raise EdgarBlocked("SEC returned 403")
        _mid_chain(lim, edgar._throttle, outcome, in_flight.wait)

    with pytest.raises(EdgarBlocked):
        warm(["slow", "refused"], task, workers=2)
    assert outcome == ["cancelled"] and lim.count == 1


def test_the_refused_worker_stops_the_pool_before_it_takes_another_item(monkeypatch):
    lim = _Limiter()
    real_wait, queued = prefetch.wait, threading.Event()
    in_flight, outcome, later = threading.Barrier(2, timeout=HANG), [], []

    def until_every_item_is_done(futures, return_when=None):
        queued.set()                           # every item is in the pool's queue
        return real_wait(futures, timeout=HANG)   # the calling thread plays no part in stopping the pool

    def task(item):
        if item == "refused":
            in_flight.wait()
            queued.wait(HANG)
            raise EdgarBlocked("SEC returned 403")
        if item == "slow":
            _mid_chain(lim, lim.acquire, outcome, in_flight.wait)
            return
        later.append(item)

    monkeypatch.setattr(prefetch, "wait", until_every_item_is_done)
    with pytest.raises(EdgarBlocked):
        warm(["slow", "refused", "later1", "later2"], task, workers=2, limiter=lim)
    assert later == []                         # the refused worker's next item never started
    assert outcome == ["cancelled"] and lim.count == 1


def test_an_interrupt_stops_the_workers_and_is_raised(monkeypatch):
    lim = _Limiter()
    in_flight, outcome, later = threading.Barrier(3, timeout=HANG), [], []

    def task(item):
        if item == "later":
            later.append(item)
            return
        _mid_chain(lim, lim.acquire, outcome, in_flight.wait)

    def ctrl_c(futures, return_when=None):
        in_flight.wait()                       # both workers have a request out
        raise KeyboardInterrupt                # Ctrl-C lands on the main thread, in its wait

    monkeypatch.setattr(prefetch, "wait", ctrl_c)
    with pytest.raises(KeyboardInterrupt):
        warm(["a", "b", "later"], task, workers=2, limiter=lim)
    assert outcome == ["cancelled", "cancelled"] and lim.count == 2
    assert later == []


def test_a_serialized_client_runs_one_call_at_a_time():
    active, peak, guard = [0], [0], threading.Lock()

    class _Client:
        label = "midas"

        def last_trade_day(self, x):
            with guard:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.01)                   # widens the window an unlocked call would overlap in
            with guard:
                active[0] -= 1
            return x

    s = Serialized(_Client())
    out, threads = [], [threading.Thread(target=lambda i=i: out.append(s.last_trade_day(i))) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(HANG)
    assert peak[0] == 1 and sorted(out) == list(range(8)) and s.label == "midas"


def test_a_serialized_call_that_is_cancelled_releases_the_lock():
    class _Client:
        def fetch(self, cancel):
            if cancel:
                raise PrefetchCancelled()
            return "ok"

    s = Serialized(_Client())
    with pytest.raises(PrefetchCancelled):
        s.fetch(True)
    assert s.fetch(False) == "ok"

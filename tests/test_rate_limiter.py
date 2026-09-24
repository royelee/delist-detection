"""The process-wide SEC rate limiter: request starts spaced 1/rate apart across
threads, a pause every thread honours while SEC fails, and a stopped prefetch
worker that starts no further request."""
import threading

import pytest
import requests

from delist_detection import edgar
from delist_detection.edgar import PrefetchCancelled, RateLimiter


class _Clock:
    """A clock that only moves when someone sleeps on it."""

    def __init__(self):
        self.t, self.slept = 100.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 9))
        self.t += s


class _Resp:
    def __init__(self, status):
        self.status_code, self.url = status, "https://data.sec.gov/x"


def _limiter(c):
    return RateLimiter(8, clock=c.now, sleep=c.sleep)


def test_starts_are_spaced_by_the_interval():
    c = _Clock()
    lim = _limiter(c)
    starts = []
    for _ in range(3):
        lim.acquire()
        starts.append(c.t)
    assert starts == [100.0, 100.125, 100.25]
    assert c.slept == [0.125, 0.125]
    assert lim.count == 3


def test_a_caller_after_a_quiet_spell_does_not_wait():
    c = _Clock()
    lim = _limiter(c)
    lim.acquire()
    c.t += 1.0
    lim.acquire()
    assert c.slept == []


def test_threads_sharing_a_limiter_never_start_closer_than_the_interval():
    # The clock only moves inside the limiter's own sleeps, so every acquire after the
    # first must sleep one full interval -- whatever order the 16 threads run in.
    c = _Clock()
    lim = _limiter(c)
    threads = [threading.Thread(target=lim.acquire) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert lim.count == 16
    assert c.slept == [0.125] * 15
    assert c.t == pytest.approx(100.0 + 15 * 0.125)


def test_a_pause_holds_the_next_start():
    c = _Clock()
    lim = _limiter(c)
    lim.acquire()
    lim.pause(2.0)
    lim.acquire()
    assert c.slept == [2.0]
    assert c.t == pytest.approx(102.0)


def test_a_shorter_pause_never_cuts_a_longer_one():
    c = _Clock()
    lim = _limiter(c)
    lim.pause(4.0)
    lim.pause(2.0)
    lim.acquire()
    assert c.slept == [4.0]


def test_a_pause_set_on_one_thread_holds_every_other_thread():
    c = _Clock()
    lim = _limiter(c)
    t = threading.Thread(target=lim.pause, args=(2.0,))
    t.start()
    t.join(5)
    lim.acquire()
    assert c.slept == [2.0]


def test_retry_request_pauses_every_thread_on_each_failure(monkeypatch):
    c = _Clock()
    lim = _limiter(c)
    monkeypatch.setattr(edgar, "SEC_LIMITER", lim)
    answers = iter([_Resp(503), requests.ConnectionError("reset"), _Resp(200)])

    def make():
        r = next(answers)
        if isinstance(r, Exception):
            raise r
        return r

    slept = []
    assert edgar.retry_request(make, sleep=slept.append).status_code == 200
    assert slept == [2, 4]                     # this thread backs off as before...
    other = threading.Thread(target=lim.acquire)
    other.start()
    other.join(5)
    assert c.slept == [4.0]                    # ...and another thread's next start waits out the pause


def test_a_request_that_keeps_failing_leaves_the_pool_paused(monkeypatch):
    c = _Clock()
    lim = _limiter(c)
    monkeypatch.setattr(edgar, "SEC_LIMITER", lim)
    assert edgar.retry_request(lambda: _Resp(503), sleep=lambda s: None).status_code == 503
    lim.acquire()
    assert c.slept == [4.0]                    # the last backoff also holds everyone's next start


def test_a_stopped_worker_starts_no_further_request():
    c = _Clock()
    lim = _limiter(c)
    stop = threading.Event()
    with lim.cancelled_by(stop):
        lim.acquire()
        stop.set()
        with pytest.raises(PrefetchCancelled):
            lim.acquire()
    lim.acquire()                              # outside the block the event no longer applies
    assert lim.count == 2


def test_the_stop_event_applies_only_to_the_thread_that_entered_the_block():
    c = _Clock()
    lim = _limiter(c)
    stop = threading.Event()
    stop.set()
    with lim.cancelled_by(stop):
        other = threading.Thread(target=lim.acquire)
        other.start()
        other.join(5)
    assert lim.count == 1


def test_prefetch_cancelled_passes_through_except_exception():
    with pytest.raises(PrefetchCancelled):
        try:
            raise PrefetchCancelled()
        except Exception:                      # the library's broad handlers must not swallow it
            pytest.fail("PrefetchCancelled was caught by `except Exception`")


def test_every_sec_request_goes_through_the_shared_limiter(monkeypatch):
    calls = []

    class _Probe:
        def acquire(self):
            calls.append("acquire")

    monkeypatch.setattr(edgar, "SEC_LIMITER", _Probe())
    edgar._throttle()
    assert calls == ["acquire"]


def test_the_shared_limiter_allows_8_requests_per_second():
    assert edgar.SEC_LIMITER.interval == pytest.approx(0.125)

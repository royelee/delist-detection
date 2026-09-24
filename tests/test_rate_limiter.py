"""The process-wide SEC rate limiter: request starts spaced 1/rate apart across
threads, a pause every thread honours while SEC fails, and a stopped prefetch
worker that starts no further request."""
import fcntl
import os
import threading
from pathlib import Path

import pytest
import requests

from delist_detection import edgar
from delist_detection.edgar import SEC_RATE_LOCK_ENV, MachineGate, PrefetchCancelled, RateLimiter, default_rate_lock_path

# The module's own limiter, read at collection time, before conftest's autouse
# fixture swaps in a per-test one.
_MODULE_SEC_LIMITER = edgar.SEC_LIMITER


class _Clock:
    """A clock that only moves when someone sleeps on it."""

    def __init__(self):
        self.t, self.slept = 100.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 9))
        self.t += s


class _InterruptedClock(_Clock):
    """A _Clock whose sleeps run `hooks` (one per sleep, in order) halfway through:
    another thread acting while this one waits."""

    def __init__(self, *hooks):
        super().__init__()
        self.hooks = list(hooks)

    def sleep(self, s):
        self.slept.append(round(s, 9))
        self.t += s / 2
        if self.hooks:
            self.hooks.pop(0)()
        self.t += s / 2


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


def test_the_second_start_after_a_quiet_spell_still_waits_a_full_interval():
    # No burst credit builds up while idle: only the first start after the spell is free.
    c = _Clock()
    lim = _limiter(c)
    lim.acquire()
    c.t += 1.0
    lim.acquire()
    lim.acquire()
    assert c.slept == [0.125]
    assert c.t == pytest.approx(101.125)


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


def test_a_pause_set_while_a_caller_waits_holds_that_caller():
    # The caller waits 0.125 s for its slot; halfway through, SEC fails on another
    # thread and pauses the pool. The caller must not start before the pause ends.
    c = _InterruptedClock(lambda: lim.pause(2.0))
    lim = _limiter(c)
    lim.acquire()                              # 100.0
    lim.acquire()                              # the pause lands at 100.0625, until 102.0625
    assert lim._resume_at == pytest.approx(102.0625)
    assert lim._last >= lim._resume_at
    assert c.t == pytest.approx(102.0625)
    assert c.slept == [0.125, 1.9375]


def test_a_pause_extended_while_a_caller_waits_holds_it_to_the_new_end():
    # A 2 s pause from 100.0; one second in, a second failure extends it to the 4 s mark.
    c = _InterruptedClock(lambda: lim.pause(3.0))
    lim = _limiter(c)
    lim.pause(2.0)
    lim.acquire()
    assert lim._resume_at == pytest.approx(104.0)
    assert c.t == pytest.approx(104.0)
    assert c.slept == [2.0, 2.0]


def test_retry_request_pauses_every_thread_on_each_failure(monkeypatch):
    c = _Clock()
    lim = _limiter(c)
    monkeypatch.setattr(edgar, "SEC_LIMITER", lim)
    answers = iter([_Resp(503), requests.ConnectionError("reset"), _Resp(200)])
    seen = []                                  # the pool's pause as each attempt starts

    def make():
        seen.append(lim._resume_at)
        r = next(answers)
        if isinstance(r, Exception):
            raise r
        return r

    slept = []
    assert edgar.retry_request(make, sleep=slept.append).status_code == 200
    assert seen == [float("-inf"), 102.0, 104.0]   # the 5xx paused the pool 2 s, the dropped connection 4 s
    assert slept == [2, 4]                     # this thread backs off as before...
    other = threading.Thread(target=lim.acquire)
    other.start()
    other.join(5)
    assert c.slept == [4.0]                    # ...and another thread's next start waits out the pause


def test_a_request_that_keeps_failing_leaves_the_pool_paused(monkeypatch):
    c = _Clock()
    lim = _limiter(c)
    monkeypatch.setattr(edgar, "SEC_LIMITER", lim)
    seen = []

    def make():
        seen.append(lim._resume_at)
        return _Resp(503)

    def backoff(s):                            # this thread's own backoff: time passes outside the limiter
        c.t += s

    assert edgar.retry_request(make, sleep=backoff).status_code == 503
    assert seen == [float("-inf"), 102.0, 106.0]   # each failure paused the pool for its backoff...
    lim.acquire()
    assert c.slept == [4.0]                    # ...and the last one too: everyone's next start waits
    assert c.t == pytest.approx(110.0)


def test_retry_request_with_no_backoff_neither_pauses_nor_sleeps(monkeypatch):
    c = _Clock()
    lim = _limiter(c)
    monkeypatch.setattr(edgar, "SEC_LIMITER", lim)
    slept = []
    assert edgar.retry_request(lambda: _Resp(503), sleep=slept.append, backoff=()).status_code == 503
    assert slept == []
    assert lim._resume_at == float("-inf")


def test_retry_request_with_a_short_backoff_reuses_its_last_value(monkeypatch):
    c = _Clock()
    lim = _limiter(c)
    monkeypatch.setattr(edgar, "SEC_LIMITER", lim)
    seen, slept = [], []

    def make():
        seen.append(lim._resume_at)
        return _Resp(503)

    assert edgar.retry_request(make, sleep=slept.append, max_attempts=3, backoff=(1,)).status_code == 503
    assert slept == [1, 1]
    assert seen == [float("-inf"), 101.0, 101.0]
    assert lim._resume_at == 101.0


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


def test_a_nested_stop_block_restores_the_outer_event_on_exit():
    c = _Clock()
    lim = _limiter(c)
    outer, inner = threading.Event(), threading.Event()
    with lim.cancelled_by(outer):
        with lim.cancelled_by(inner):
            lim.acquire()
        outer.set()
        with pytest.raises(PrefetchCancelled):
            lim.acquire()                      # back in the outer block: the outer event applies again
    lim.acquire()
    assert lim.count == 2


def test_prefetch_cancelled_passes_through_except_exception():
    with pytest.raises(PrefetchCancelled):
        try:
            raise PrefetchCancelled()
        except Exception:                      # the library's broad handlers must not swallow it
            pytest.fail("PrefetchCancelled was caught by `except Exception`")


def test_the_per_test_limiter_costs_no_real_time_after_a_pause():
    # conftest's limiter runs on a virtual clock that its own sleep advances: a pause
    # left by a failing request neither blocks a test nor spins it in a busy-wait.
    edgar.SEC_LIMITER.pause(60.0)
    t = threading.Thread(target=edgar._throttle, daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive()


def test_every_sec_request_goes_through_the_shared_limiter(monkeypatch):
    calls = []

    class _Probe:
        def acquire(self):
            calls.append("acquire")

    monkeypatch.setattr(edgar, "SEC_LIMITER", _Probe())
    edgar._throttle()
    assert calls == ["acquire"]


def test_the_shared_limiter_allows_8_requests_per_second():
    assert _MODULE_SEC_LIMITER is not edgar.SEC_LIMITER   # the module's own, not conftest's per-test one
    assert edgar.SEC_MAX_RATE == 8.0
    assert _MODULE_SEC_LIMITER.interval == pytest.approx(0.125)


def _gate(path, c):
    return MachineGate(path, 0.125, wall=c.now, sleep=c.sleep)


def test_two_limiters_sharing_one_lock_file_space_their_starts(tmp_path):
    # Two processes on one machine: each has its own in-process limiter, and both
    # use the same lock file. Their starts interleave but never come closer than
    # 1/8 s.
    c = _Clock()
    path = tmp_path / "sec_rate.lock"
    a = RateLimiter(8, clock=c.now, sleep=c.sleep, gate=_gate(path, c))
    b = RateLimiter(8, clock=c.now, sleep=c.sleep, gate=_gate(path, c))
    starts = []
    for lim in (a, b, a, b):
        lim.acquire()
        starts.append(c.t)
    assert starts == pytest.approx([100.0, 100.125, 100.25, 100.375])
    assert float(path.read_text()) == pytest.approx(100.375)


def test_a_wall_clock_step_back_waits_at_most_one_interval(tmp_path):
    c = _Clock()
    path = tmp_path / "sec_rate.lock"
    path.write_text("999999.0")                 # a start stamped "in the future": the clock stepped back

    def sleep(s):
        if len(c.slept) >= 3:                   # fail, not hang, if the same stale stamp is waited out forever
            raise AssertionError("waited again for a stamp it had already waited out")
        c.sleep(s)

    MachineGate(path, 0.125, wall=c.now, sleep=sleep).wait_turn()
    assert c.slept == [0.125]
    assert float(path.read_text()) == pytest.approx(100.125)   # the stale stamp is replaced by this start


@pytest.mark.parametrize("content", ["", "garbage", "1.0", "nan"])
def test_an_old_or_unreadable_stamp_does_not_wait(tmp_path, content):
    c = _Clock()
    path = tmp_path / "sec_rate.lock"
    path.write_text(content)
    _gate(path, c).wait_turn()
    assert c.slept == []
    assert float(path.read_text()) == pytest.approx(100.0)


def test_the_lock_file_is_held_while_a_start_is_taken(tmp_path):
    path = tmp_path / "sec_rate.lock"
    gate = MachineGate(path, 0.125)             # real clock; a new file never waits
    holder = os.open(path, os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)          # another process is taking its start
    t = threading.Thread(target=gate.wait_turn)
    t.start()
    t.join(0.2)
    assert t.is_alive()                         # this one waits for the lock
    fcntl.flock(holder, fcntl.LOCK_UN)
    os.close(holder)
    t.join(5)
    assert not t.is_alive()


def test_the_lock_path_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(SEC_RATE_LOCK_ENV, str(tmp_path / "x.lock"))
    assert default_rate_lock_path() == tmp_path / "x.lock"
    monkeypatch.delenv(SEC_RATE_LOCK_ENV)
    assert default_rate_lock_path() == Path.home() / ".cache" / "delist_detection" / "sec_rate.lock"


def test_use_machine_wide_limit_gates_the_shared_limiter(monkeypatch, tmp_path):
    monkeypatch.setenv(SEC_RATE_LOCK_ENV, str(tmp_path / "sec_rate.lock"))
    gate = edgar.use_machine_wide_limit()
    assert edgar.SEC_LIMITER.gate is gate and gate.path == tmp_path / "sec_rate.lock"
    assert edgar.use_machine_wide_limit() is gate          # idempotent
    edgar._throttle()
    assert float((tmp_path / "sec_rate.lock").read_text()) > 0


def test_an_unwritable_lock_path_fails_at_setup_naming_the_variable(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    with pytest.raises(OSError, match=SEC_RATE_LOCK_ENV):
        edgar.use_machine_wide_limit(blocker / "sub" / "sec_rate.lock")   # a file where a directory must be
    assert edgar.SEC_LIMITER.gate is None


def test_require_user_agent_refuses_the_fallback(monkeypatch):
    monkeypatch.setattr(edgar, "resolve_user_agent", lambda: edgar.FALLBACK_UA)
    with pytest.raises(edgar.EdgarSetupError, match="EDGAR_USER_AGENT"):
        edgar.require_user_agent()
    monkeypatch.setattr(edgar, "resolve_user_agent", lambda: "Test Co test@example.com")
    assert edgar.require_user_agent() == "Test Co test@example.com"


def test_a_worker_stopped_while_it_waits_for_the_machine_turn_starts_no_request():
    c = _Clock()
    stop = threading.Event()

    class _Gate:
        def wait_turn(self):
            stop.set()                          # the pool stops while this thread waits on the lock file

    lim = RateLimiter(8, clock=c.now, sleep=c.sleep, gate=_Gate())
    with lim.cancelled_by(stop):
        with pytest.raises(PrefetchCancelled):
            lim.acquire()
    assert lim.count == 0


def test_no_process_sleeps_while_it_holds_the_lock_file(tmp_path):
    # A process suspended mid-sleep (Ctrl-Z, a debugger) must not hold every other SEC
    # client on the machine: the wait for a turn happens with the lock file released.
    c = _Clock()
    path = tmp_path / "sec_rate.lock"
    path.write_text("100.0")                    # another process started just now: this one waits 1/8 s
    probe = os.open(path, os.O_RDWR)
    held_while_sleeping = []

    def sleep(s):
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)   # could another process take the lock now?
        except BlockingIOError:
            held_while_sleeping.append(s)
        else:
            fcntl.flock(probe, fcntl.LOCK_UN)
        c.sleep(s)

    MachineGate(path, 0.125, wall=c.now, sleep=sleep).wait_turn()
    os.close(probe)
    assert c.slept == [0.125]
    assert held_while_sleeping == []
    assert float(path.read_text()) == pytest.approx(100.125)


def test_a_start_another_process_takes_during_the_wait_is_waited_out_too(tmp_path):
    c = _Clock()
    path = tmp_path / "sec_rate.lock"
    path.write_text("100.0")
    other = os.open(path, os.O_RDWR)

    def sleep(s):
        c.sleep(s)
        if len(c.slept) == 1:                   # while this one sleeps, another process takes its turn
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)   # never blocks: the sleeper holds no lock
            os.ftruncate(other, 0)
            os.pwrite(other, f"{c.t:.6f}".encode("ascii"), 0)
            fcntl.flock(other, fcntl.LOCK_UN)

    MachineGate(path, 0.125, wall=c.now, sleep=sleep).wait_turn()
    os.close(other)
    assert c.slept == [0.125, 0.125]            # it looked again, and waited 1/8 s after the other's start
    assert float(path.read_text()) == pytest.approx(100.25)


def test_tests_never_use_the_lock_file_in_the_home_directory():
    # conftest points DELIST_DETECTION_SEC_RATE_LOCK at a per-test temporary file.
    p = default_rate_lock_path()
    assert p != Path.home() / ".cache" / "delist_detection" / "sec_rate.lock"
    assert p.parent.is_dir()

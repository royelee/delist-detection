"""The SEC request rate limit: at most 8 request starts per second across every
thread of the process (`SEC_LIMITER`, a `RateLimiter`), and, once
`use_machine_wide_limit()` has installed a `MachineGate`, across every process on
the machine that shares its lock file. Every SEC request waits in `throttle()`;
a prefetch pool cancels its workers through the limiter (`PrefetchCancelled`)."""
from __future__ import annotations

import fcntl
import math
import os
import threading
import time
import weakref
from contextlib import contextmanager
from pathlib import Path


class PrefetchCancelled(BaseException):
    """Raised at a prefetch worker's next SEC request once its pool is stopping (a
    refusal on another thread, or Ctrl-C). A BaseException, like KeyboardInterrupt,
    so the library's `except Exception` handlers let it through and the worker ends
    without sending another request."""


class RateLimiter:
    """At most `rate` request starts per second across every thread that shares it.

    `acquire()` blocks until the caller may start one request: `interval` after
    the previous start, and not before a pause set by `pause()` has run out --
    including a pause set or extended while the caller is already waiting. The
    lock is held while sleeping, so callers queue behind it and no burst credit
    builds up. `gate` (a MachineGate) extends the spacing to every process on
    the machine that shares its lock file; it is taken after the in-process
    lock, so this process's own threads queue cheaply first. `clock` and `sleep`
    are injectable so tests never wait.
    """

    def __init__(self, rate: float, *, clock=time.monotonic, sleep=time.sleep,
                 gate: "MachineGate | None" = None) -> None:
        self.interval = 1.0 / rate
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()            # held from the wait through the start
        self._pause_lock = threading.Lock()      # guards _resume_at only; taken after _lock, never before
        self._last: float | None = None
        self._resume_at = float("-inf")
        self._local = threading.local()
        self.count = 0                           # requests started through this limiter
        self.gate = gate                         # machine-wide spacing (MachineGate), taken after _lock

    def _raise_if_cancelled(self) -> None:
        stop = getattr(self._local, "stop", None)
        if stop is not None and stop.is_set():
            raise PrefetchCancelled()

    def pause(self, seconds: float) -> None:
        """Hold every caller's next request start until `seconds` from now. SEC is
        failing (a 5xx or a dropped connection), so the whole pool backs off
        together instead of each thread on its own. A longer pause already set is
        kept."""
        with self._pause_lock:
            self._resume_at = max(self._resume_at, self._clock() + seconds)

    def acquire(self) -> None:
        self._raise_if_cancelled()
        with self._lock:
            while True:
                # stopped while queued behind the lock, or while sleeping: the slot goes unused
                self._raise_if_cancelled()
                with self._pause_lock:
                    ready = self._resume_at
                if self._last is not None:
                    ready = max(ready, self._last + self.interval)
                wait = ready - self._clock()
                if wait <= 0:
                    break
                self._sleep(wait)                # then look again: a pause may have been set meanwhile
            if self.gate is not None:
                self.gate.wait_turn()            # every other process sharing the lock file
                self._raise_if_cancelled()       # stopped while waiting for the machine's turn
            self._last = self._clock()
            self.count += 1

    @contextmanager
    def cancelled_by(self, stop: threading.Event):
        """Inside this block, the calling thread's acquire() raises PrefetchCancelled
        once `stop` is set. Other threads are not affected. On exit the event of an
        enclosing block, if any, applies again."""
        outer = getattr(self._local, "stop", None)
        self._local.stop = stop
        try:
            yield
        finally:
            self._local.stop = outer


SEC_MAX_RATE = 8.0      # SEC allows 10 requests/s per client; we stay under it (spec §9, §11)
SEC_LIMITER = RateLimiter(SEC_MAX_RATE)

SEC_RATE_LOCK_ENV = "DELIST_DETECTION_SEC_RATE_LOCK"


def default_rate_lock_path() -> Path:
    """The machine-wide SEC rate lock file: $DELIST_DETECTION_SEC_RATE_LOCK, else
    ~/.cache/delist_detection/sec_rate.lock. Outside the repo on purpose: every
    checkout and worktree on the machine must share it."""
    env = os.environ.get(SEC_RATE_LOCK_ENV, "").strip()
    return Path(env).expanduser() if env else Path.home() / ".cache" / "delist_detection" / "sec_rate.lock"


class MachineGate:
    """Spaces SEC request starts across every process on the machine that uses one
    lock file. The file holds the wall-clock time of the last start. `wait_turn`
    takes the file's exclusive `flock` and reads that time. If its turn is due,
    it writes its own start and releases the lock. Otherwise it releases the
    lock, sleeps until `interval` after that time, and looks again. It never
    sleeps while it holds the lock, so a process suspended mid-wait (Ctrl-Z, a
    debugger) cannot stall every other SEC client on the machine. The wait is
    clamped to [0, interval], and a stamp already waited out is not waited for
    again, so a wall-clock step can neither stall the pool (a stamp "in the
    future") nor let a burst through; an unreadable stamp counts as none. The
    file is opened here, so an unwritable path fails at start-up, not in the
    middle of a run."""

    def __init__(self, path: str | Path, interval: float, *, wall=time.time, sleep=time.sleep) -> None:
        self.path, self.interval = Path(path), interval
        self._wall, self._sleep = wall, sleep
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        weakref.finalize(self, os.close, self._fd)

    def wait_turn(self) -> None:
        waited_out = None                        # the stamp this call has already slept a turn for
        while True:
            fcntl.flock(self._fd, fcntl.LOCK_EX)
            try:
                raw = os.pread(self._fd, 64, 0)
                wait = 0.0 if raw == waited_out else self._wait_after(raw)
                if wait <= 0:
                    stamp = f"{self._wall():.6f}".encode("ascii")
                    os.ftruncate(self._fd, 0)
                    os.pwrite(self._fd, stamp, 0)
                    return
            finally:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._sleep(wait)                    # with the lock released; then look again:
            waited_out = raw                     # another process may have started meanwhile

    def _wait_after(self, raw: bytes) -> float:
        """How long to wait after the start stamped `raw`, clamped to [0, interval]. A
        stamp that is unreadable or not finite (nan, inf, -inf -- `time.sleep` raises
        ValueError on nan) counts as no stamp."""
        try:
            last = float(raw.decode("ascii").strip() or "0")
        except (UnicodeDecodeError, ValueError):
            last = 0.0
        if not math.isfinite(last):
            last = 0.0
        return min(max(last + self.interval - self._wall(), 0.0), self.interval)


def use_machine_wide_limit(path: str | Path | None = None) -> MachineGate:
    """Extend SEC_LIMITER's spacing to every process on this machine that uses the
    same lock file (`path`, default `default_rate_lock_path()`). Call it once at
    start-up, before any SEC request: the CLI, `pipeline.default_clients`,
    `verify_against_web.py` and `build_golden_fixtures.py` do. Idempotent for one
    path. Raises OSError, naming the path and SEC_RATE_LOCK_ENV, when the lock
    file cannot be opened for writing."""
    p = Path(path).expanduser() if path is not None else default_rate_lock_path()
    gate = SEC_LIMITER.gate
    if gate is not None and gate.path == p:
        return gate
    try:
        gate = MachineGate(p, SEC_LIMITER.interval)
    except OSError as exc:
        raise OSError(f"cannot open the machine-wide SEC rate lock {p} ({exc}); set {SEC_RATE_LOCK_ENV} "
                      "to a writable file that every SEC client on this machine uses") from exc
    SEC_LIMITER.gate = gate
    return gate


def throttle() -> None:
    """Wait for the next SEC request slot: this process's, and, once
    `use_machine_wide_limit()` has installed a gate, the machine's across every
    process sharing the lock file. Every SEC request (`sec_get`, which
    EdgarClient, sec_http and verify_against_web share) calls this, from any thread. It
    reads the module's SEC_LIMITER at each call, so a test or the CLI can swap
    or extend the limiter."""
    SEC_LIMITER.acquire()

"""One retry loop for every client that talks to a remote service (SEC, OpenFIGI,
the Nasdaq halt feed). Each client keeps its own policy -- which answers are
retried, how long to wait, what a final failure means -- and hands it to
`retrying` as a callback; the loop itself (attempts, the wait between them,
whether to wait after the last) lives here once."""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import requests

T = TypeVar("T")


def retrying(send: Callable[[], T], *, attempts: int,
             wait: Callable[[int, T | None, requests.RequestException | None], float | None],
             sleep: Callable[[float], object], wait_after_last: bool = False
             ) -> tuple[T | None, requests.RequestException | None]:
    """Call `send()` up to `attempts` times; a `requests.RequestException` it
    raises is caught and handed on like a result. After each attempt,
    `wait(attempt, result, error)` (attempt counts from 0; exactly one of result
    and error is set) decides: None stops and returns that attempt's outcome;
    a number of seconds retries, sleeping that long first when it is positive
    (after the last attempt only with `wait_after_last`). `wait` may raise to
    stop at once (a refusal). Returns the last attempt's `(result, error)`, so
    the caller tells an answer from a failure that outlasted its attempts."""
    result: T | None = None
    error: requests.RequestException | None = None
    for attempt in range(attempts):
        try:
            result, error = send(), None
        except requests.RequestException as exc:
            result, error = None, exc
        seconds = wait(attempt, result, error)
        if seconds is None:
            break
        if seconds > 0 and (wait_after_last or attempt < attempts - 1):
            sleep(seconds)
    return result, error

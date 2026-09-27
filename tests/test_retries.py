"""The one retry loop the SEC, OpenFIGI and Nasdaq clients share."""
import pytest
import requests

from delist_detection.retries import retrying


def _sender(*outcomes):
    """send() that returns or raises each of `outcomes` in turn; `.calls` counts."""
    items = list(outcomes)

    def send():
        send.calls += 1
        item = items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    send.calls = 0
    return send


def test_an_answer_stops_at_once():
    send, slept = _sender("ok"), []
    assert retrying(send, attempts=3, wait=lambda a, r, e: None, sleep=slept.append) == ("ok", None)
    assert send.calls == 1 and slept == []


def test_a_retried_outcome_waits_between_attempts_but_not_after_the_last():
    send, slept = _sender(503, 503, 503), []
    assert retrying(send, attempts=3, wait=lambda a, r, e: [2, 4, 8][a], sleep=slept.append) == (503, None)
    assert send.calls == 3 and slept == [2, 4]


def test_wait_after_last_also_waits_after_the_last_attempt():
    send, slept = _sender(503, 503), []
    retrying(send, attempts=2, wait=lambda a, r, e: a + 1, sleep=slept.append, wait_after_last=True)
    assert slept == [1, 2]


def test_a_transport_error_is_handed_to_the_policy_and_returned_when_it_lasts():
    err = requests.Timeout("t")
    send, seen = _sender(err, err), []
    result, error = retrying(send, attempts=2, wait=lambda a, r, e: seen.append((a, r, e)) or 0, sleep=print)
    assert (result, error) == (None, err) and seen == [(0, None, err), (1, None, err)]


def test_a_later_answer_clears_an_earlier_error():
    send = _sender(requests.ConnectionError("c"), "ok")
    assert retrying(send, attempts=3, wait=lambda a, r, e: 0 if e else None, sleep=print) == ("ok", None)


def test_a_zero_wait_retries_without_sleeping():
    send, slept = _sender(1, 2, 3), []
    assert retrying(send, attempts=3, wait=lambda a, r, e: 0, sleep=slept.append) == (3, None)
    assert slept == []


def test_a_refusal_raised_by_the_policy_stops_the_loop():
    send = _sender(403, "never")

    def policy(attempt, result, error):
        raise PermissionError("refused")

    with pytest.raises(PermissionError):
        retrying(send, attempts=3, wait=policy, sleep=print)
    assert send.calls == 1


def test_other_exceptions_are_not_caught():
    send = _sender(ValueError("bug"))
    with pytest.raises(ValueError):
        retrying(send, attempts=3, wait=lambda a, r, e: 0, sleep=print)

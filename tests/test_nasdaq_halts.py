import logging
from datetime import date
from pathlib import Path

import pytest
import requests

from delist_detection.sec_stats import SEC_STATS
from delist_detection.nasdaq_halts import Halt, NasdaqHaltClient, last_trade_from_halt, parse_halts_rss

RSS = """﻿<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:ndaq="http://www.nasdaqtrader.com/">
  <channel>
    <item>
      <title>ALTR</title>
      <ndaq:IssueSymbol>ALTR</ndaq:IssueSymbol>
      <ndaq:IssueName>Altair Engineering Inc. Class A Common Stock</ndaq:IssueName>
      <ndaq:Mkt>Q</ndaq:Mkt>
      <ndaq:ReasonCode>D</ndaq:ReasonCode>
      <ndaq:HaltDate>03/25/2025</ndaq:HaltDate>
      <ndaq:HaltTime>19:50:00</ndaq:HaltTime>
      <ndaq:ResumptionDate>03/27/2025</ndaq:ResumptionDate>
    </item>
    <item>
      <title>CNSP</title>
      <ndaq:IssueSymbol>CNSP</ndaq:IssueSymbol>
      <ndaq:IssueName>CNS Pharmaceuticals</ndaq:IssueName>
      <ndaq:Mkt>Q</ndaq:Mkt>
      <ndaq:ReasonCode>T3</ndaq:ReasonCode>
      <ndaq:HaltDate>03/25/2025</ndaq:HaltDate>
      <ndaq:HaltTime>07:55:00</ndaq:HaltTime>
      <ndaq:ResumptionDate />
    </item>
  </channel>
</rss>"""


def test_parse():
    halts = parse_halts_rss(RSS)
    assert halts[0] == Halt("ALTR", "Altair Engineering Inc. Class A Common Stock", "Q", "D",
                            date(2025, 3, 25), "19:50:00", date(2025, 3, 27))
    assert halts[1].resumption_date is None


def test_last_trade_from_halt():
    after_close = Halt("ALTR", "", "Q", "D", date(2025, 3, 25), "19:50:00", None)
    before_open = Halt("SAVE", "", "N", "D", date(2024, 11, 18), "04:30:00", None)
    at_boundary = Halt("TEST", "", "Q", "D", date(2025, 3, 25), "09:30:00", None)
    assert last_trade_from_halt(after_close) == date(2025, 3, 25)
    assert last_trade_from_halt(before_open) == date(2024, 11, 15)
    assert last_trade_from_halt(at_boundary) == date(2025, 3, 25)


class _Resp:
    status_code = 200

    def __init__(self, text):
        self.text = text
        self.content = text.encode("utf-8")


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return _Resp(RSS if "03252025" in url else RSS.replace("<item>", "<x>").replace("</item>", "</x>"))


class _Session429Then200:
    """Returns 429 on first call, then 200 with RSS on retry."""
    def __init__(self):
        self.calls = 0
        self.sleep_calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        if self.calls == 1:
            resp = _Resp("")
            resp.status_code = 429
            resp.headers = {"Retry-After": "0.1"}
            return resp
        return _Resp(RSS)


class _Session403:
    """Always returns 403."""
    def get(self, url, headers=None, timeout=None):
        resp = _Resp("")
        resp.status_code = 403
        return resp


def test_client_caches_and_finds_deletion(tmp_path):
    s = _Session()
    c = NasdaqHaltClient(tmp_path, session=s, min_interval=0)
    h = c.deletion_halt("ALTR", date(2025, 3, 24), date(2025, 3, 26))
    assert h is not None and h.halt_date == date(2025, 3, 25)
    assert c.deletion_halt("CNSP", date(2025, 3, 25), date(2025, 3, 25)) is None     # T3, not D
    n = len(s.urls)
    c.halts_on(date(2025, 3, 25))
    assert len(s.urls) == n                                                          # cached
    assert "haltdate=03252025" in s.urls[1] or "haltdate=03252025" in s.urls[0]


def test_a_days_feed_cut_off_mid_write_leaves_no_cache_file(tmp_path, writes_fail_midway):
    """A run that dies while caching a day's feed leaves no cut-off XML, which the
    next run would fail to parse: the feed is written through atomic_io.write_atomic."""
    writes_fail_midway(tmp_path)
    with pytest.raises(OSError):
        NasdaqHaltClient(tmp_path, session=_Session(), min_interval=0).halts_on(date(2025, 3, 25))
    assert list(tmp_path.iterdir()) == []


def test_client_retries_429(tmp_path):
    """Test that 429 response triggers sleep and retry once."""
    s = _Session429Then200()
    sleep_calls = []
    def mock_sleep(duration):
        sleep_calls.append(duration)

    c = NasdaqHaltClient(tmp_path, session=s, min_interval=0, sleep=mock_sleep)
    halts = c.halts_on(date(2025, 3, 25))
    assert len(halts) == 2  # Successfully got RSS after retry
    assert len(sleep_calls) == 1  # Sleep was called once
    assert sleep_calls[0] == 0.1  # Retry-After header was respected
    assert s.calls == 2  # Called twice (429, then 200)


class _SessionMalformed:
    """Always returns a 200 with an unparseable body (a mismatched tag)."""
    def get(self, url, headers=None, timeout=None):
        return _Resp("<rss><channel><item></channel></rss>")


def _read_one_day(tmp_path, session, day=date(2025, 3, 25)):
    """Ask the client for one day's halts through `session`; returns the halts,
    the client, and the SEC_STATS counts the read added."""
    c = NasdaqHaltClient(tmp_path, session=session, min_interval=0, sleep=lambda _: None)
    mark, thread_mark = SEC_STATS.snapshot(), SEC_STATS.thread_degraded()
    halts = c.halts_on(day)
    counts, _ = SEC_STATS.since(mark)
    assert SEC_STATS.thread_degraded() == thread_mark          # never read as a failed SEC request
    return halts, c, counts


def _is_a_failure(tmp_path, halts, c, counts, day=date(2025, 3, 25)):
    assert halts == []
    assert c.failed_days() == (day,)
    assert counts.get("degraded:nasdaq_halt_feed") == 1
    assert "degraded:failed_request" not in counts
    assert not (tmp_path / f"{day:%Y%m%d}.xml").exists()                    # never cached


def test_a_malformed_body_is_a_halt_feed_failure_and_is_not_cached(tmp_path, caplog):
    """A malformed halt-feed answer (sent twice for 2025-05-05, per task-16's live
    measurement) is not "no halts": that would hide a real deletion halt. It
    counts as a Nasdaq halt-feed failure, never as a failed SEC request, is never
    cached, and is logged."""
    caplog.set_level(logging.WARNING)
    day = date(2025, 5, 5)
    halts, c, counts = _read_one_day(tmp_path, _SessionMalformed(), day)
    _is_a_failure(tmp_path, halts, c, counts, day)
    assert "parse error" in caplog.text and "2025-05-05" in caplog.text


class _SessionRaising:
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        raise self.exc


@pytest.mark.parametrize("exc", [requests.Timeout("read timed out"), requests.ConnectionError("reset")])
def test_a_timeout_or_a_connection_error_is_a_halt_feed_failure(tmp_path, exc):
    s = _SessionRaising(exc)
    halts, c, counts = _read_one_day(tmp_path, s)
    _is_a_failure(tmp_path, halts, c, counts)
    assert s.calls == 1                       # not retried, as before


class _SessionStatus:
    def __init__(self, *statuses):
        self.statuses, self.calls = list(statuses), 0

    def get(self, url, headers=None, timeout=None):
        resp = _Resp("")
        resp.status_code = self.statuses[min(self.calls, len(self.statuses) - 1)]
        resp.headers = {}
        self.calls += 1
        return resp


def test_a_5xx_after_the_retry_is_a_halt_feed_failure(tmp_path):
    s = _SessionStatus(503, 502)
    halts, c, counts = _read_one_day(tmp_path, s)
    _is_a_failure(tmp_path, halts, c, counts)
    assert s.calls == 2                       # one retry, as before


def test_a_404_is_an_answer_no_halts_not_a_failure(tmp_path):
    halts, c, counts = _read_one_day(tmp_path, _SessionStatus(404))
    assert halts == [] and c.failed_days() == ()
    assert not any(k.endswith("nasdaq_halt_feed") for k in counts)


def test_a_403_is_a_halt_feed_failure_logged_and_not_cached(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    halts, c, counts = _read_one_day(tmp_path, _Session403())
    _is_a_failure(tmp_path, halts, c, counts)
    assert "HTTP 403" in caplog.text and "2025-03-25" in caplog.text


def test_a_day_read_after_a_retry_is_no_failure(tmp_path):
    s = _Session429Then200()
    s_halts, c, counts = _read_one_day(tmp_path, s)
    assert len(s_halts) == 2 and c.failed_days() == () and not counts.get("degraded:nasdaq_halt_feed")


def test_failed_days_are_kept_per_thread_and_a_warm_thread_counts_apart(tmp_path):
    """A warm (fill-only) thread's failure is counted as warm_degraded and stays
    on that thread: the sequential pass sees only its own failed days."""
    import threading

    from delist_detection.sec_stats import fill_only

    c = NasdaqHaltClient(tmp_path, session=_SessionRaising(requests.Timeout("t")), min_interval=0,
                         sleep=lambda _: None)
    mark = SEC_STATS.snapshot()

    def warm():
        with fill_only():
            c.halts_on(date(2025, 3, 24))

    t = threading.Thread(target=warm)
    t.start()
    t.join()
    assert c.failed_days() == ()
    counts, _ = SEC_STATS.since(mark)
    assert counts.get("warm_degraded:nasdaq_halt_feed") == 1 and "degraded:nasdaq_halt_feed" not in counts
    c.halts_on(date(2025, 3, 25))
    assert c.failed_days() == (date(2025, 3, 25),)


FEED_FIX = Path(__file__).parent / "fixtures" / "nasdaq_halts" / "tradehalts_11022020.xml"


class _RealFeedSession:
    """Serves the real 2020-11-02 feed as `requests` builds it: the body starts
    with a UTF-8 BOM and the header says `text/xml` with no charset, so
    `Response.text` decodes it as ISO-8859-1 (the BOM becomes three letters)."""

    def get(self, url, headers=None, timeout=None):
        r = requests.models.Response()
        r.status_code = 200
        r.headers["Content-Type"] = "text/xml"
        r._content = FEED_FIX.read_bytes()
        return r


def test_real_feed_with_a_bom_and_no_charset_parses(tmp_path):
    c = NasdaqHaltClient(tmp_path, session=_RealFeedSession(), min_interval=0)
    h = c.deletion_halt("CBL", date(2020, 11, 2), date(2020, 11, 2))
    assert h is not None and (h.symbol, h.reason, h.halt_time) == ("CBL", "D", "16:11:11")
    assert last_trade_from_halt(h) == date(2020, 11, 2)
    # the cached copy is the feed's own bytes and parses again
    assert (tmp_path / "20201102.xml").read_bytes() == FEED_FIX.read_bytes()
    assert [x.symbol for x in NasdaqHaltClient(tmp_path, session=None, min_interval=0).halts_on(date(2020, 11, 2))
            if x.reason == "D"] == ["CBL$E", "CBL", "CBL$D"]


def test_the_halt_feed_caches_only_days_before_its_run_date(tmp_path):
    c = NasdaqHaltClient(tmp_path, session=_RealFeedSession(), min_interval=0, today=date(2020, 11, 2))
    c.halts_on(date(2020, 11, 2))
    assert not (tmp_path / "20201102.xml").exists()        # the run's own day can still grow
    later = NasdaqHaltClient(tmp_path, session=_RealFeedSession(), min_interval=0, today=date(2020, 11, 3))
    later.halts_on(date(2020, 11, 2))
    assert (tmp_path / "20201102.xml").exists()


def test_the_retry_waits_are_the_feeds_own(tmp_path):
    """A 5xx or 429 is retried once, after its Retry-After or 2 s, with no wait
    after the second; a transport error is not retried."""
    slept = []
    c = NasdaqHaltClient(tmp_path, session=_SessionStatus(503, 503), min_interval=0, sleep=slept.append)
    assert c.halts_on(date(2025, 3, 25)) == [] and slept == [2.0]
    slept.clear()
    s = _SessionRaising(requests.ConnectionError("reset"))
    NasdaqHaltClient(tmp_path, session=s, min_interval=0, sleep=slept.append).halts_on(date(2025, 3, 25))
    assert slept == [] and s.calls == 1


def test_each_attempt_waits_out_the_pacing_interval(tmp_path, monkeypatch):
    """The feed is paced before every attempt, the retry included."""
    import delist_detection.nasdaq_halts as nh

    clock = iter([100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(nh.time, "monotonic", lambda: next(clock))
    slept = []
    c = NasdaqHaltClient(tmp_path, session=_SessionStatus(503, 503), min_interval=1.0, sleep=slept.append)
    c._last = 100.0
    c.halts_on(date(2025, 3, 25))
    assert slept == [1.0, 2.0, 1.0]

import logging
from datetime import date
from pathlib import Path

import pytest
import requests

from delist_detection.edgar import SEC_STATS
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
    next run would fail to parse: the feed is written through edgar.write_atomic."""
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


def test_a_malformed_body_counts_as_degraded_and_is_not_cached(tmp_path, caplog):
    """A malformed halt-feed answer (SEC sent this twice for
    2025-05-05, per task-16's live measurement) was treated as "no halts" with
    no flag anywhere. It must count SEC_STATS.degraded("failed_request"),
    never cache the day, and log once (already true before this fix)."""
    caplog.set_level(logging.WARNING)
    s = _SessionMalformed()
    c = NasdaqHaltClient(tmp_path, session=s, min_interval=0)
    mark = SEC_STATS.snapshot()
    halts = c.halts_on(date(2025, 5, 5))
    assert halts == []
    assert not (tmp_path / "20250505.xml").exists()
    counts, _ = SEC_STATS.since(mark)
    assert counts.get("degraded:failed_request") == 1
    assert "parse error" in caplog.text and "2025-05-05" in caplog.text


def test_client_403_logs_warning(tmp_path, caplog):
    """Test that 403 response logs a warning and returns empty list without caching."""
    import logging
    caplog.set_level(logging.WARNING)

    s = _Session403()
    c = NasdaqHaltClient(tmp_path, session=s, min_interval=0)
    halts = c.halts_on(date(2025, 3, 25))

    assert halts == []
    assert "HTTP 403" in caplog.text
    assert "2025-03-25" in caplog.text
    # Verify cache file was not created
    assert not (tmp_path / "20250325.xml").exists()


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

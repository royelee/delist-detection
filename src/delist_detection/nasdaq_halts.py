"""Nasdaq Trader's keyless trade-halt feed, one day per request.

A code-D halt ("security deletion from NASDAQ / CQS") timestamps the end of
exchange trading, including some NYSE/CQS names. Many delistings have no entry,
so this only confirms a date; it is not a complete register.

A day's feed is an answer when it parses (cached once the day is past) or when
the feed says 404 (no halts, not cached). Anything else -- a timeout or a
connection error, a 429/5xx after the one retry, another status, a body that
does not parse -- is a failure: the day reads as no halts for this run, is never
cached, is counted under `degraded:nasdaq_halt_feed` (not as a failed SEC
request), and is listed by `failed_days()` on the thread that read it, so the
delisting whose last-trade decision asked for it can be flagged
`resolution_degraded`.
"""
from __future__ import annotations

import logging
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from .atomic_io import clean_orphan_temps, write_atomic
from .sec_stats import SEC_STATS
from .observations import normalize_ticker
from .retries import retrying
from .trading_calendar import is_trading_day, previous_trading_day

HALTS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate={mmddyyyy}"
_NS = {"ndaq": "http://www.nasdaqtrader.com/"}
_UA = "delist_detection research (halt history lookup)"
DEGRADED_KEY = "nasdaq_halt_feed"      # SEC_STATS.degraded key of a failed day read
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Halt:
    symbol: str
    name: str
    market: str
    reason: str
    halt_date: date
    halt_time: str
    resumption_date: date | None


def _mdy(s: str | None) -> date | None:
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_halts_rss(xml: str | bytes) -> list[Halt]:
    """Halts in one day's feed. Give it the response's bytes: the feed starts
    with a UTF-8 BOM and is served as `text/xml` with no charset, so a decoded
    `requests` `.text` (ISO-8859-1) turns the BOM into three letters the XML
    parser rejects; parsing the bytes lets it read the encoding itself."""
    root = ET.fromstring(xml.strip() if isinstance(xml, bytes) else xml.lstrip("﻿").strip())
    out: list[Halt] = []
    for item in root.iter("item"):
        get = lambda tag: (item.findtext(f"ndaq:{tag}", default="", namespaces=_NS) or "").strip()
        hd = _mdy(get("HaltDate"))
        if hd is None:
            continue
        out.append(Halt(get("IssueSymbol"), get("IssueName"), get("Mkt"), get("ReasonCode"), hd,
                        get("HaltTime"), _mdy(get("ResumptionDate"))))
    return out


def _retried(resp) -> bool:
    """A 429 or a 5xx: the feed is retried once for it."""
    return resp.status_code == 429 or 500 <= resp.status_code < 600


def _retry_wait(attempt: int, resp, error) -> float | None:
    """The feed's retry policy (`retries.retrying`): a 429 or 5xx is retried
    after its Retry-After, else 2 s; an answer or a transport error is not."""
    if resp is None or not _retried(resp):
        return None
    try:
        return float(resp.headers.get("Retry-After", 2.0))
    except ValueError:
        return 2.0


def last_trade_from_halt(h: Halt) -> date:
    return previous_trading_day(h.halt_date) if (h.halt_time or "00:00:00") < "09:30:00" else h.halt_date


class NasdaqHaltClient:
    def __init__(self, cache_dir: str | Path, *, session=None, min_interval: float = 1.0, sleep=None,
                 today: date | None = None) -> None:
        self.dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self.sleep = sleep or time.sleep
        self.today = today          # the run date: that day's list can still grow (None: the clock)
        self._last = 0.0
        self._local = threading.local()       # this thread's failed days
        clean_orphan_temps(self.dir)          # a killed run's cut-off day

    def failed_days(self) -> tuple[date, ...]:
        """Every day whose feed this client failed to read on the calling thread,
        in the order asked (a day asked twice and failed twice is listed twice)."""
        return tuple(getattr(self._local, "failed", ()))

    def _failed(self, day: date, why: str) -> list[Halt]:
        """Record `day` as a failed read (see the module docstring); no halts."""
        _log.warning(f"halts_on({day:%Y-%m-%d}): {why}")
        SEC_STATS.degraded(DEGRADED_KEY, sec=False)
        self._local.failed = [*self.failed_days(), day]
        return []

    def halts_on(self, day: date) -> list[Halt]:
        cp = self.dir / f"{day:%Y%m%d}.xml"
        if cp.exists():
            return parse_halts_rss(cp.read_bytes())

        resp, error = retrying(lambda: self._get(day), attempts=2, wait=_retry_wait, sleep=self.sleep)
        if error is not None:
            return self._failed(day, f"network error: {error}")
        if _retried(resp):
            return self._failed(day, f"{resp.status_code} after retry")
        if resp.status_code == 404:
            return []                      # the feed's answer: no halts that day
        if resp.status_code != 200:
            return self._failed(day, f"HTTP {resp.status_code}")
        try:
            halts = parse_halts_rss(resp.content)
        except ET.ParseError as e:
            # A malformed body is not "no halts": that would silently hide a
            # real deletion halt.
            return self._failed(day, f"parse error: {e}")
        if day < (self.today or date.today()):  # today's list can still grow
            cp.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(cp, resp.content)
        return halts

    def _get(self, day: date):
        """One request for `day`'s feed, paced `min_interval` after the last."""
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            self.sleep(wait)
        self._last = time.monotonic()
        return self.session.get(HALTS_URL.format(mmddyyyy=f"{day:%m%d%Y}"), headers={"User-Agent": _UA}, timeout=30)

    def deletion_halt(self, symbol: str, lo: date, hi: date, max_days: int = 7) -> Halt | None:
        want = normalize_ticker(symbol)
        d, looked = lo, 0
        while d <= hi and looked < max_days:
            if is_trading_day(d):
                looked += 1
                for h in self.halts_on(d):
                    if h.reason == "D" and normalize_ticker(h.symbol) == want:
                        return h
            d += timedelta(days=1)
        return None

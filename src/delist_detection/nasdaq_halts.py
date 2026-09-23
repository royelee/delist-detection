"""Nasdaq Trader's keyless trade-halt feed, one day per request.

A code-D halt ("security deletion from NASDAQ / CQS") timestamps the end of
exchange trading, including some NYSE/CQS names. Many delistings have no entry,
so this only confirms a date; it is not a complete register.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from .observations import normalize_ticker
from .trading_calendar import is_trading_day, previous_trading_day

HALTS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate={mmddyyyy}"
_NS = {"ndaq": "http://www.nasdaqtrader.com/"}
_UA = "delist_detection research (halt history lookup)"


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


def parse_halts_rss(xml_text: str) -> list[Halt]:
    root = ET.fromstring(xml_text.lstrip("﻿").strip())
    out: list[Halt] = []
    for item in root.iter("item"):
        get = lambda tag: (item.findtext(f"ndaq:{tag}", default="", namespaces=_NS) or "").strip()
        hd = _mdy(get("HaltDate"))
        if hd is None:
            continue
        out.append(Halt(get("IssueSymbol"), get("IssueName"), get("Mkt"), get("ReasonCode"), hd,
                        get("HaltTime"), _mdy(get("ResumptionDate"))))
    return out


def last_trade_from_halt(h: Halt) -> date:
    return previous_trading_day(h.halt_date) if (h.halt_time or "00:00:00") < "09:30:00" else h.halt_date


class NasdaqHaltClient:
    def __init__(self, cache_dir: str | Path, *, session=None, min_interval: float = 1.0) -> None:
        self.dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self._last = 0.0

    def halts_on(self, day: date) -> list[Halt]:
        cp = self.dir / f"{day:%Y%m%d}.xml"
        if cp.exists():
            return parse_halts_rss(cp.read_text(encoding="utf-8"))
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            resp = self.session.get(HALTS_URL.format(mmddyyyy=f"{day:%m%d%Y}"),
                                    headers={"User-Agent": _UA}, timeout=30)
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        try:
            halts = parse_halts_rss(resp.text)
        except ET.ParseError:
            return []
        if day < date.today():                  # today's list can still grow
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(resp.text, encoding="utf-8")
        return halts

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

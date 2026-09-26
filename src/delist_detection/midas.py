"""SEC MIDAS "Metrics by Individual Security": daily exchange volume per ticker,
2012 onward. The last day with nonzero lit + hidden volume is the last day the
security traded on an exchange. Keyed by ticker only, exchange trades only.

Each quarterly ZIP (~15-25 MB) is summarized once into
`<cache>/<year>_q<q>.json.gz` (ticker -> dates with volume) and then deleted.
"""
from __future__ import annotations

import calendar
import csv
import gzip
import io
import json
import logging
import re
import time
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import requests

from .atomic_io import clean_orphan_temps, write_atomic
from .edgar import SEC_STATS, filling_only
from .observations import normalize_ticker
from .sec_http import download, get_text
from .trading_calendar import add_trading_days

MIDAS_INDEX_URL = ("https://www.sec.gov/opa/data/market-structure/"
                   "marketstructuredownloadshtml-by_security.html")
MIDAS_START = date(2012, 1, 1)
INDEX_MAX_AGE_DAYS = 30        # the index page is fetched again once its cached copy is this old
# A window that runs past MIDAS's coverage end (the latest published quarter)
# always finds nothing in the unpublished part, so a found day sitting within
# this many trading days of the coverage end is too close to the edge to
# trust as the real last trade -- it would otherwise beat the notice/8-K
# purely because the next quarter hasn't been published yet.
MIDAS_COVERAGE_EDGE_TRADING_DAYS = 5
_SEC = "https://www.sec.gov"
_log = logging.getLogger(__name__)
_Q = re.compile(r"individual_security_(\d{4})_q(\d+)\.zip$", re.I)


def _quarter_end(yq: tuple[int, int]) -> date:
    y, q = yq
    month = q * 3
    return date(y, month, calendar.monthrange(y, month)[1])


def quarter_of(url: str) -> tuple[int, int] | None:
    m = _Q.search(url.rsplit("/", 1)[-1])
    if not m:
        return None
    y, q = int(m.group(1)), int(m.group(2))
    if q == 10:
        q = 1
    return (y, q) if 1 <= q <= 4 else None


def _quarter(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def _quarters(lo: date, hi: date) -> list[tuple[int, int]]:
    out, (y, q) = [], _quarter(lo)
    while (y, q) <= _quarter(hi):
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def summarize_midas_csv(lines: Iterable[str]) -> dict[str, list[str]]:
    reader = csv.reader(lines)
    header = next(reader)
    idx = {h.strip(): i for i, h in enumerate(header)}
    i_date, i_tk = idx["Date"], idx["Ticker"]
    i_lit = next(i for h, i in idx.items() if h.startswith("LitVol"))
    i_hid = next(i for h, i in idx.items() if h.startswith("HiddenVol"))
    out: dict[str, set[str]] = defaultdict(set)
    for row in reader:
        if len(row) <= max(i_lit, i_hid):
            continue
        try:
            vol = float(row[i_lit] or 0) + float(row[i_hid] or 0)
        except ValueError:
            continue
        d = row[i_date].strip()
        if d.endswith(".0"):                  # the 2016 quarters write every number as a float
            d = d[:-2]
        if vol > 0 and len(d) == 8 and d.isdigit():
            out[normalize_ticker(row[i_tk])].add(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    return {t: sorted(v) for t, v in out.items()}


def _summarize_zip(z: zipfile.ZipFile, zpath: Path) -> dict[str, list[str]]:
    """The summary of the quarter's CSV in `z`. Some quarters (2014 Q2) ship the
    CSV one level down, inside a zip in the zip; that inner zip is read too."""
    member = next((m for m in z.namelist() if m.lower().endswith(".csv")), None)
    if member is not None:
        with z.open(member) as fh:
            return summarize_midas_csv(io.TextIOWrapper(fh, encoding="latin-1"))
    for m in z.namelist():
        if m.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(z.read(m))) as inner:
                member = next((n for n in inner.namelist() if n.lower().endswith(".csv")), None)
                if member is not None:
                    with inner.open(member) as fh:
                        return summarize_midas_csv(io.TextIOWrapper(fh, encoding="latin-1"))
    raise ValueError(f"No .csv file in {zpath}")


class MidasClient:
    def __init__(self, cache_dir: str | Path, *, session=None, user_agent: str | None = None) -> None:
        self.dir = Path(cache_dir)
        self.session, self.user_agent = session, user_agent
        self._links: dict[tuple[int, int], str] | None = None
        self._summaries: dict[tuple[int, int], dict[str, list[str]] | None] = {}
        # The prefetch threads' own view (edgar.fill_only()), which the sequential
        # pass never reads: the index copy they read, whether it was past
        # INDEX_MAX_AGE_DAYS, and the quarters they found nothing for.
        self._fill_links: dict[tuple[int, int], str] | None = None
        self._fill_index_stale = False
        self._fill_misses: set[tuple[int, int]] = set()
        # Quarters already warned+counted as a miss this run (warm and sequential
        # share this: `prefetch.Serialized` runs every MidasClient call, warm or
        # sequential, one at a time), so each quarter is warned about once a run.
        self._warned_misses: set[tuple[int, int]] = set()
        clean_orphan_temps(self.dir)          # a killed run's cut-off download, index page or summary

    def _warn_miss(self, yq: tuple[int, int], why: str) -> None:
        """Log once and count `midas_miss:<yq>` once per quarter per run: a quarter
        that never yields evidence is otherwise a silent fallback to "no last
        trade day" evidence."""
        if yq in self._warned_misses:
            return
        self._warned_misses.add(yq)
        _log.warning(f"MIDAS {yq[0]} Q{yq[1]}: {why}; no evidence from this quarter for the rest of the run")
        SEC_STATS.add(f"midas_miss:{yq[0]}q{yq[1]}")

    def _read_index(self) -> dict[tuple[int, int], str]:
        html = get_text(MIDAS_INDEX_URL, self.dir / "index.html", max_age_days=INDEX_MAX_AGE_DAYS,
                        session=self.session, user_agent=self.user_agent)
        links: dict[tuple[int, int], str] = {}
        for href in re.findall(r'href="([^"]+\.zip)"', html, re.I):
            q = quarter_of(href)
            if q and q not in links:
                links[q] = href if href.startswith("http") else _SEC + href
        return links

    def links(self) -> dict[tuple[int, int], str]:
        """Each published quarter's ZIP link, from the index page (fetched again
        once INDEX_MAX_AGE_DAYS old), kept for the run. A prefetch thread
        (`edgar.fill_only()`) reads the cached page whatever its age, once, into a
        memo of the prefetch threads' own: the sequential pass reads the page
        itself, and refreshes a stale copy, as a one-thread run does."""
        if self._links is not None:
            return self._links
        if filling_only():
            if self._fill_links is None:
                page = self.dir / "index.html"
                self._fill_index_stale = (page.exists()
                                          and time.time() - page.stat().st_mtime >= INDEX_MAX_AGE_DAYS * 86400)
                self._fill_links = self._read_index()
            return self._fill_links
        self._links = self._read_index()
        return self._links

    def coverage_end(self) -> date | None:
        """The last day of the latest quarter MIDAS has published, or None if
        the index lists no quarter at all."""
        links = self.links()
        if not links:
            return None
        return _quarter_end(max(links))

    def _miss(self, yq: tuple[int, int]) -> None:
        """No evidence from quarter `yq` for the rest of the run. A prefetch thread
        keeps the miss to the prefetch threads: it may rest on a stale index
        copy, or on a download the sequential pass must try itself."""
        if filling_only():
            self._fill_misses.add(yq)
        else:
            self._summaries[yq] = None

    def _summary(self, yq: tuple[int, int]) -> dict[str, list[str]] | None:
        if yq in self._summaries:
            return self._summaries[yq]
        if filling_only() and yq in self._fill_misses:
            return None
        cache = self.dir / f"{yq[0]}_q{yq[1]}.json.gz"
        s = json.loads(gzip.decompress(cache.read_bytes())) if cache.exists() else None
        if not s:                           # none yet, or an empty one an older reader cached
            cache.unlink(missing_ok=True)
            links = self.links()
            if filling_only() and self._links is None and self._fill_index_stale:
                # A one-thread run refreshes this copy before its first download,
                # and the fresh copy may list the quarter under another URL, or
                # not at all: the sequential pass downloads it, if anyone does.
                self._miss(yq)
                return None
            url = links.get(yq)
            if url is None:
                self._miss(yq)
                return None
            zpath = self.dir / url.rsplit("/", 1)[-1]
            try:
                try:
                    zpath = download(url, zpath, session=self.session, user_agent=self.user_agent)
                    z = zipfile.ZipFile(zpath)
                except zipfile.BadZipFile:
                    zpath.unlink(missing_ok=True)  # corrupted: fetch it again once
                    zpath = download(url, zpath, session=self.session, user_agent=self.user_agent)
                    z = zipfile.ZipFile(zpath)
            except (requests.RequestException, FileNotFoundError) as exc:
                # Gave up after retries, or a 404 (the index lists a ZIP SEC no
                # longer serves; nothing is written): remember this quarter as
                # failed for the rest of the run, so the next security doesn't
                # pay the same download+retry cost again.
                self._miss(yq)
                why = "SEC no longer serves this quarter's ZIP" if isinstance(exc, FileNotFoundError) \
                    else f"the download kept failing ({exc})"
                self._warn_miss(yq, why)
                return None
            with z:
                s = _summarize_zip(z, zpath)
            if not s:
                # A quarter read to nothing is a layout this reader does not
                # know, never an answer: keep the zip, cache nothing, and give
                # no evidence from it for the rest of the run.
                _log.warning(f"MIDAS {yq[0]} Q{yq[1]}: {zpath.name} yielded no rows with volume; not cached")
                self._summaries[yq] = None
                return None
            cache.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(cache, gzip.compress(json.dumps(s).encode()))
            zpath.unlink(missing_ok=True)
        self._summaries[yq] = s
        return s

    def last_trade_day(self, ticker: str, lo: date, hi: date) -> date | None:
        if hi < MIDAS_START:
            return None
        t = normalize_ticker(ticker)
        lo_s, hi_s = max(lo, MIDAS_START).isoformat(), hi.isoformat()
        best: str | None = None
        for yq in _quarters(max(lo, MIDAS_START), hi):
            s = self._summary(yq)
            for d in (s or {}).get(t, []):
                if lo_s <= d <= hi_s and (best is None or d > best):
                    best = d
        if best is None:
            return None
        found = date.fromisoformat(best)
        coverage_end = self.coverage_end()
        if coverage_end is not None and hi > coverage_end:
            edge = add_trading_days(coverage_end, -MIDAS_COVERAGE_EDGE_TRADING_DAYS)
            if found >= edge:
                return None       # too close to the unpublished edge to trust
        return found

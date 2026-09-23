"""SEC MIDAS "Metrics by Individual Security": daily exchange volume per ticker,
2012 onward. The last day with nonzero lit + hidden volume is the last day the
security traded on an exchange. Keyed by ticker only, exchange trades only.

Each quarterly ZIP (~15-25 MB) is summarized once into
`<cache>/<year>_q<q>.json.gz` (ticker -> dates with volume) and then deleted.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from .observations import normalize_ticker
from .sec_http import download, get_text

MIDAS_INDEX_URL = ("https://www.sec.gov/opa/data/market-structure/"
                   "marketstructuredownloadshtml-by_security.html")
MIDAS_START = date(2012, 1, 1)
_SEC = "https://www.sec.gov"
_Q = re.compile(r"individual_security_(\d{4})_q(\d+)\.zip$", re.I)


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
        if vol > 0 and len(d) == 8 and d.isdigit():
            out[normalize_ticker(row[i_tk])].add(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    return {t: sorted(v) for t, v in out.items()}


class MidasClient:
    def __init__(self, cache_dir: str | Path, *, session=None, user_agent: str | None = None) -> None:
        self.dir = Path(cache_dir)
        self.session, self.user_agent = session, user_agent
        self._links: dict[tuple[int, int], str] | None = None
        self._summaries: dict[tuple[int, int], dict[str, list[str]] | None] = {}

    def links(self) -> dict[tuple[int, int], str]:
        if self._links is None:
            html = get_text(MIDAS_INDEX_URL, self.dir / "index.html", max_age_days=30,
                            session=self.session, user_agent=self.user_agent)
            links: dict[tuple[int, int], str] = {}
            for href in re.findall(r'href="([^"]+\.zip)"', html, re.I):
                q = quarter_of(href)
                if q and q not in links:
                    links[q] = href if href.startswith("http") else _SEC + href
            self._links = links
        return self._links

    def _summary(self, yq: tuple[int, int]) -> dict[str, list[str]] | None:
        if yq in self._summaries:
            return self._summaries[yq]
        cache = self.dir / f"{yq[0]}_q{yq[1]}.json.gz"
        if cache.exists():
            s = json.loads(gzip.decompress(cache.read_bytes()))
        else:
            url = self.links().get(yq)
            if url is None:
                self._summaries[yq] = None
                return None
            zpath = self.dir / url.rsplit("/", 1)[-1]
            try:
                zpath = download(url, zpath, session=self.session, user_agent=self.user_agent)
                z = zipfile.ZipFile(zpath)
            except zipfile.BadZipFile:
                zpath.unlink(missing_ok=True)  # corrupted: fetch it again once
                zpath = download(url, zpath, session=self.session, user_agent=self.user_agent)
                z = zipfile.ZipFile(zpath)
            with z:
                try:
                    member = next(m for m in z.namelist() if m.lower().endswith(".csv"))
                except StopIteration:
                    raise ValueError(f"No .csv file in {zpath}") from None
                with z.open(member) as fh:
                    s = summarize_midas_csv(io.TextIOWrapper(fh, encoding="latin-1"))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(gzip.compress(json.dumps(s).encode()))
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
        return date.fromisoformat(best) if best else None

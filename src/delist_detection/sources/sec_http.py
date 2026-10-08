"""Throttled, cached downloads of SEC data files (fails-to-deliver ZIPs, MIDAS
ZIPs, their index pages). Same fair-access rules as EdgarClient: one shared
8 req/s throttle, a descriptive User-Agent, and EdgarBlocked on 403/429.

Every download here retries a connection error, a timeout, or a 5xx up to 3
attempts with backoff (`retry_request`, same as `EdgarClient`'s); a 403/429
still raises `EdgarBlocked` at once, and a failure is never cached."""
from __future__ import annotations

import time
from pathlib import Path

import requests

from .atomic_io import write_atomic
from .edgar import resolve_user_agent, sec_get
from .sec_stats import SEC_STATS, filling_only


def _get(url: str, session, user_agent: str | None, timeout: int, *, sleep=time.sleep):
    """`edgar.sec_get` for an SEC data file, counted as `request:sec_data`;
    retried, and EdgarBlocked propagates, never retried."""
    headers = {"User-Agent": user_agent or resolve_user_agent(), "Accept": "*/*", "Host": "www.sec.gov"}
    return sec_get(url, session=session, headers=headers, timeout=timeout, endpoint="sec_data", sleep=sleep)


def download(url: str, dest: str | Path, *, session=None, user_agent: str | None = None,
            sleep=time.sleep) -> Path:
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    resp = _get(url, session, user_agent, timeout=180, sleep=sleep)
    if resp.status_code == 404:
        raise FileNotFoundError(url)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(dest, resp.content)
    return dest


def get_text(url: str, cache_file: str | Path, *, max_age_days: float = 7, session=None,
             user_agent: str | None = None, sleep=time.sleep) -> str:
    """`url`'s text, cached in `cache_file` and fetched again once the copy is
    `max_age_days` old; a failed refetch serves the old copy, counted as
    `SEC_STATS.degraded("stale_copy")` since a possibly-outdated index page is
    otherwise a silent fallback. On a prefetch thread (`sec_stats.fill_only()`) an
    existing copy of any age is returned with no request, so only the
    sequential pass refreshes it, in its own order."""
    cf = Path(cache_file)
    if cf.exists() and (filling_only() or time.time() - cf.stat().st_mtime < max_age_days * 86400):
        return cf.read_text(encoding="utf-8", errors="replace")
    try:
        resp = _get(url, session, user_agent, timeout=60, sleep=sleep)
        resp.raise_for_status()
    except requests.RequestException:
        if cf.exists():
            SEC_STATS.degraded("stale_copy")
            return cf.read_text(encoding="utf-8", errors="replace")
        raise
    cf.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(cf, resp.text)
    return resp.text

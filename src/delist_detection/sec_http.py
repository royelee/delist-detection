"""Throttled, cached downloads of SEC data files (fails-to-deliver ZIPs, MIDAS
ZIPs, their index pages). Same fair-access rules as EdgarClient: one shared
8 req/s throttle, a descriptive User-Agent, and EdgarBlocked on 403/429."""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from .edgar import _throttle, check_response, resolve_user_agent


def _get(url: str, session, user_agent: str | None, timeout: int):
    s = session or requests.Session()
    headers = {"User-Agent": user_agent or resolve_user_agent(), "Accept": "*/*", "Host": "www.sec.gov"}
    _throttle()
    resp = s.get(url, headers=headers, timeout=timeout)
    check_response(resp)
    return resp


def download(url: str, dest: str | Path, *, session=None, user_agent: str | None = None) -> Path:
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    resp = _get(url, session, user_agent, timeout=180)
    if resp.status_code == 404:
        raise FileNotFoundError(url)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(resp.content)
    os.replace(tmp, dest)
    return dest


def get_text(url: str, cache_file: str | Path, *, max_age_days: float = 7, session=None,
             user_agent: str | None = None) -> str:
    cf = Path(cache_file)
    if cf.exists() and time.time() - cf.stat().st_mtime < max_age_days * 86400:
        return cf.read_text(encoding="utf-8", errors="replace")
    try:
        resp = _get(url, session, user_agent, timeout=60)
        resp.raise_for_status()
    except requests.RequestException:
        if cf.exists():
            return cf.read_text(encoding="utf-8", errors="replace")
        raise
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(resp.text, encoding="utf-8")
    return resp.text

"""OpenFIGI v3 client: every mapping job and filter query is cached on disk,
requests are paced on the ratelimit headers, a 429 is waited out, and a
401/403 raises OpenFigiBlocked (the CLI exits 2) instead of reading as a miss.
Timeouts, connection errors, 5xx answers (or 429s) that outlast MAX_RETRIES
attempts raise OpenFigiUnavailable (the CLI exits 1): an outage, not a refusal.
Neither is ever cached, and neither falls back to a placeholder: that would
change sec_ids between runs."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

from .edgar import write_atomic

OPENFIGI_URL = "https://api.openfigi.com/v3"
_REPO_ENV = Path(__file__).resolve().parents[2] / ".env"


class OpenFigiBlocked(RuntimeError):
    """OpenFIGI refused the request (401/403: a bad or missing key)."""


class OpenFigiUnavailable(RuntimeError):
    """OpenFIGI did not answer: timeouts, connection errors or 5xx/429 answers
    until the retries ran out. Not an OpenFigiBlocked: the key is fine, the run
    can simply be repeated later."""


def resolve_api_key(env_file: str | Path = _REPO_ENV) -> str | None:
    key = os.environ.get("OPEN_FIGI_API_KEY", "").strip()
    if key:
        return key
    if not Path(env_file).exists():
        return None
    from dotenv import dotenv_values  # noqa: PLC0415

    return (dotenv_values(env_file).get("OPEN_FIGI_API_KEY") or "").strip() or None


def _wait_seconds(headers, default: int) -> int:
    for k in ("retry-after", "ratelimit-reset"):
        v = str(headers.get(k) or "").strip()
        if v.isdigit():
            return int(v) + 1
    return default


class OpenFigiClient:
    MAX_RETRIES = 6

    def __init__(self, cache_dir: str | Path, api_key: str | None = None, *, session=None,
                 sleep=time.sleep) -> None:
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.session = session or requests.Session()
        self.sleep = sleep
        self.max_jobs = 100 if api_key else 10

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-OPENFIGI-APIKEY"] = self.api_key
        return h

    def _post(self, path: str, payload):
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self.session.post(f"{OPENFIGI_URL}{path}", json=payload, headers=self._headers(),
                                         timeout=60)
            except requests.RequestException:
                self.sleep(min(60, 2 ** attempt))
                continue
            if resp.status_code in (401, 403):
                raise OpenFigiBlocked(f"OpenFIGI returned {resp.status_code} for {path}; check OPEN_FIGI_API_KEY")
            if resp.status_code == 429 or resp.status_code >= 500:
                self.sleep(_wait_seconds(resp.headers, 60 if resp.status_code == 429 else 2 ** attempt))
                continue
            resp.raise_for_status()
            if str(resp.headers.get("ratelimit-remaining", "")).strip() == "0":
                self.sleep(_wait_seconds(resp.headers, 60))
            return resp.json()
        raise OpenFigiUnavailable(f"OpenFIGI {path} kept failing after {self.MAX_RETRIES} attempts")

    def _cache_file(self, kind: str, payload) -> Path:
        h = hashlib.sha1(json.dumps({"kind": kind, "payload": payload}, sort_keys=True).encode()).hexdigest()
        return self.dir / f"{h}.json"

    def map(self, jobs: list[dict], *, use_cache: bool = True) -> list[dict]:
        results: list[dict | None] = [None] * len(jobs)
        todo: list[int] = []
        for i, job in enumerate(jobs):
            cf = self._cache_file("mapping", job)
            if use_cache and cf.exists():
                results[i] = json.loads(cf.read_text())
            else:
                todo.append(i)
        for k in range(0, len(todo), self.max_jobs):
            chunk = todo[k:k + self.max_jobs]
            answers = self._post("/mapping", [jobs[i] for i in chunk])
            for i, ans in zip(chunk, answers):
                results[i] = ans
                if use_cache and "error" not in ans:
                    write_atomic(self._cache_file("mapping", jobs[i]), json.dumps(ans))
        return [r if r is not None else {"error": "no answer"} for r in results]

    def filter(self, query: str, *, max_pages: int = 3, **fields) -> list[dict]:
        payload = {"query": query, **fields}
        cf = self._cache_file("filter", payload)
        if cf.exists():
            return json.loads(cf.read_text())
        data: list[dict] = []
        start = None
        for _ in range(max_pages):
            body = dict(payload)
            if start:
                body["start"] = start
            ans = self._post("/filter", body)
            data += ans.get("data", [])
            start = ans.get("next")
            if not start:
                break
        write_atomic(cf, json.dumps(data))
        return data

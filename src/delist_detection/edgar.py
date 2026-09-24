"""Thin EDGAR client. Handles SEC fair-access throttling and on-disk caching.

SEC requires a descriptive User-Agent and ≤10 req/sec from a single IP. We cap
at 8 req/sec and cache every JSON payload, so repeated runs cost nothing.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests


SEC_HOST = "https://data.sec.gov"
WWW_SEC_HOST = "https://www.sec.gov"
# SEC requires a descriptive User-Agent with a contact, and 403s ones it
# doesn't accept (SEC has rejected this noreply fallback).
FALLBACK_UA = "delist_detection/0.1 (r@users.noreply.github.com)"
_REPO_ENV = Path(__file__).resolve().parents[2] / ".env"


class EdgarBlocked(RuntimeError):
    """SEC refused the request (403/429). Callers must never read this as 'no match':
    from 2026-05-28 to 2026-09-16 every refusal was cached as 'No CIK found'."""


def check_response(resp) -> None:
    if resp.status_code in (403, 429):
        raise EdgarBlocked(
            f"SEC returned {resp.status_code} for {getattr(resp, 'url', '?')}. "
            "Set EDGAR_USER_AGENT to a real contact address (see resolve_user_agent) or slow down."
        )


def resolve_user_agent(env_file: str | Path = _REPO_ENV) -> str:
    """EDGAR_USER_AGENT from the environment, else from ``env_file``, else the fallback.

    Reads only that one key from the file and leaves ``os.environ`` untouched;
    ``llm_client.default_llm_client`` is the only place that calls ``load_dotenv``.
    """
    ua = os.environ.get("EDGAR_USER_AGENT", "").strip()
    if ua:
        return ua
    from dotenv import dotenv_values  # noqa: PLC0415

    ua = (dotenv_values(env_file).get("EDGAR_USER_AGENT") or "").strip()
    return ua or FALLBACK_UA


DEFAULT_UA = resolve_user_agent()

# The day a cached JSON payload was fetched; a payload without it is dated by its file time.
FETCHED_KEY = "__fetched__"
# Marks a payload served from cache because the refetch failed. Added to the
# returned dict only, never written to disk.
STALE_KEY = "__stale__"
SUBMISSIONS_FRESH_DAYS = 45  # filings this long after the last trade must be in the submissions read
COMPANY_SEARCH_FRESH_DAYS = 7  # a company-search answer this old is refetched, never trusted forever


def submissions_fresh_after(on: date) -> date:
    """The `fresh_after` for reading a company's submissions about an event on `on`:
    `min(on + 45 days, today)`. The classifier and the resolver both use it."""
    return min(on + timedelta(days=SUBMISSIONS_FRESH_DAYS), date.today())


def _strip_html(raw: str) -> str:
    """Strip <script>/<style>/tags, unescape entities, collapse whitespace."""
    import html as _html
    import re as _re

    t = _re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    t = _re.sub(r"(?s)<[^>]+>", " ", t)
    t = _html.unescape(t)
    t = _re.sub(r"\s+", " ", t)
    return t.strip()


def _fetched_on(cp: Path, data: Any) -> date:
    if isinstance(data, dict):
        try:
            return date.fromisoformat(data.get(FETCHED_KEY))
        except (TypeError, ValueError):
            pass
    return date.fromtimestamp(cp.stat().st_mtime)


def _fsync_dir(directory: Path) -> None:
    """Make a rename in `directory` durable. Best effort: some filesystems refuse
    to fsync a directory."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_atomic(path: Path, text: str) -> None:
    """Replace `path` with `text` in one step: a reader -- in this process or
    another -- sees the old file or the complete new one, never a part. The temp
    file sits in the same directory (os.replace is atomic only within one
    filesystem) and carries the process and thread id, so two writers never
    share one and `clean_orphan_temps` can tell a dead writer's leftover from a
    live one's. The data is fsynced before the rename and the directory after
    it, so the new file also survives a power loss."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    _fsync_dir(path.parent)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:              # EPERM: the process exists but belongs to another user
        return True
    return True


def clean_orphan_temps(directory: Path) -> None:
    """Delete the `_write_atomic` temp files (`.<name>.<pid>.<thread>.tmp`) in
    `directory` whose writing process has exited: it was killed mid-write. A
    live process's temp file is left alone, since it may still be writing it."""
    if not directory.is_dir():
        return
    for p in directory.glob(".*.tmp"):
        parts = p.name[1:-len(".tmp")].rsplit(".", 2)
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit() and not _pid_alive(int(parts[1])):
            p.unlink(missing_ok=True)


_FILL_ONLY = threading.local()


@contextmanager
def fill_only():
    """On the calling thread, EDGAR reads fill missing cache entries but never
    replace an existing one: a copy older than the caller's `fresh_after`, or an
    expired search answer, is returned as it is, with no request.
    `prefetch.warm` runs every task inside this. A warm pass therefore only adds
    answers the sequential pass would fetch the same way itself, and every
    refresh happens in the sequential pass, in its own order, exactly as in a
    one-thread run (spec §11: same inputs and caches -> byte-identical CSVs)."""
    prev = getattr(_FILL_ONLY, "on", False)
    _FILL_ONLY.on = True
    try:
        yield
    finally:
        _FILL_ONLY.on = prev


def filling_only() -> bool:
    """True inside `fill_only()` on this thread."""
    return getattr(_FILL_ONLY, "on", False)


class PrefetchCancelled(BaseException):
    """Raised at a prefetch worker's next SEC request once its pool is stopping (a
    refusal on another thread, or Ctrl-C). A BaseException, like KeyboardInterrupt,
    so the library's `except Exception` handlers let it through and the worker ends
    without sending another request."""


class RateLimiter:
    """At most `rate` request starts per second across every thread that shares it.

    `acquire()` blocks until the caller may start one request: `interval` after
    the previous start, and not before a pause set by `pause()` has run out --
    including a pause set or extended while the caller is already waiting. The
    lock is held while sleeping, so callers queue behind it and no burst credit
    builds up. `gate` (a MachineGate) extends the spacing to every process on
    the machine that shares its lock file; it is taken after the in-process
    lock, so this process's own threads queue cheaply first. `clock` and `sleep`
    are injectable so tests never wait.
    """

    def __init__(self, rate: float, *, clock=time.monotonic, sleep=time.sleep,
                 gate: "MachineGate | None" = None) -> None:
        self.interval = 1.0 / rate
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()            # held from the wait through the start
        self._pause_lock = threading.Lock()      # guards _resume_at only; taken after _lock, never before
        self._last: float | None = None
        self._resume_at = float("-inf")
        self._local = threading.local()
        self.count = 0                           # requests started through this limiter
        self.gate = gate                         # machine-wide spacing (MachineGate), taken after _lock

    def _raise_if_cancelled(self) -> None:
        stop = getattr(self._local, "stop", None)
        if stop is not None and stop.is_set():
            raise PrefetchCancelled()

    def pause(self, seconds: float) -> None:
        """Hold every caller's next request start until `seconds` from now. SEC is
        failing (a 5xx or a dropped connection), so the whole pool backs off
        together instead of each thread on its own. A longer pause already set is
        kept."""
        with self._pause_lock:
            self._resume_at = max(self._resume_at, self._clock() + seconds)

    def acquire(self) -> None:
        self._raise_if_cancelled()
        with self._lock:
            while True:
                # stopped while queued behind the lock, or while sleeping: the slot goes unused
                self._raise_if_cancelled()
                with self._pause_lock:
                    ready = self._resume_at
                if self._last is not None:
                    ready = max(ready, self._last + self.interval)
                wait = ready - self._clock()
                if wait <= 0:
                    break
                self._sleep(wait)                # then look again: a pause may have been set meanwhile
            if self.gate is not None:
                self.gate.wait_turn()            # every other process sharing the lock file
                self._raise_if_cancelled()       # stopped while waiting for the machine's turn
            self._last = self._clock()
            self.count += 1

    @contextmanager
    def cancelled_by(self, stop: threading.Event):
        """Inside this block, the calling thread's acquire() raises PrefetchCancelled
        once `stop` is set. Other threads are not affected. On exit the event of an
        enclosing block, if any, applies again."""
        outer = getattr(self._local, "stop", None)
        self._local.stop = stop
        try:
            yield
        finally:
            self._local.stop = outer


SEC_MAX_RATE = 8.0      # SEC allows 10 requests/s per client; we stay under it (spec §9, §11)
SEC_LIMITER = RateLimiter(SEC_MAX_RATE)

SEC_RATE_LOCK_ENV = "DELIST_DETECTION_SEC_RATE_LOCK"


def default_rate_lock_path() -> Path:
    """The machine-wide SEC rate lock file: $DELIST_DETECTION_SEC_RATE_LOCK, else
    ~/.cache/delist_detection/sec_rate.lock. Outside the repo on purpose: every
    checkout and worktree on the machine must share it."""
    env = os.environ.get(SEC_RATE_LOCK_ENV, "").strip()
    return Path(env).expanduser() if env else Path.home() / ".cache" / "delist_detection" / "sec_rate.lock"


class MachineGate:
    """Spaces SEC request starts across every process on the machine that uses one
    lock file. The file holds the wall-clock time of the last start. `wait_turn`
    takes the file's exclusive `flock`, waits until `interval` after that time,
    writes its own start and releases the lock. The wait is clamped to
    [0, interval], so a wall-clock step can neither stall the pool (a stamp "in
    the future") nor let a burst through; an unreadable stamp counts as none.
    The file is opened here, so an unwritable path fails at start-up, not in the
    middle of a run."""

    def __init__(self, path: str | Path, interval: float, *, wall=time.time, sleep=time.sleep) -> None:
        self.path, self.interval = Path(path), interval
        self._wall, self._sleep = wall, sleep
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        weakref.finalize(self, os.close, self._fd)

    def wait_turn(self) -> None:
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        try:
            try:
                last = float(os.pread(self._fd, 64, 0).decode("ascii").strip() or "0")
            except (UnicodeDecodeError, ValueError):
                last = 0.0
            wait = min(max(last + self.interval - self._wall(), 0.0), self.interval)
            if wait > 0:
                self._sleep(wait)
            stamp = f"{self._wall():.6f}".encode("ascii")
            os.ftruncate(self._fd, 0)
            os.pwrite(self._fd, stamp, 0)
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)


def use_machine_wide_limit(path: str | Path | None = None) -> MachineGate:
    """Extend SEC_LIMITER's spacing to every process on this machine that uses the
    same lock file (`path`, default `default_rate_lock_path()`). Call it once at
    start-up, before any SEC request: the CLI, `pipeline.default_clients`,
    `verify_against_web.py` and `build_golden_fixtures.py` do. Idempotent for one
    path. Raises OSError, naming the path and SEC_RATE_LOCK_ENV, when the lock
    file cannot be opened for writing."""
    p = Path(path).expanduser() if path is not None else default_rate_lock_path()
    gate = SEC_LIMITER.gate
    if gate is not None and gate.path == p:
        return gate
    try:
        gate = MachineGate(p, SEC_LIMITER.interval)
    except OSError as exc:
        raise OSError(f"cannot open the machine-wide SEC rate lock {p} ({exc}); set {SEC_RATE_LOCK_ENV} "
                      "to a writable file that every SEC client on this machine uses") from exc
    SEC_LIMITER.gate = gate
    return gate


class EdgarSetupError(RuntimeError):
    """The client is not set up to talk to SEC: no User-Agent SEC accepts."""


def require_user_agent() -> str:
    """The configured User-Agent. Raises EdgarSetupError when only the fallback
    is left, which SEC answers with 403, so a run stops before its first request
    instead of after a pool of threads has been refused."""
    ua = resolve_user_agent()
    if ua == FALLBACK_UA:
        raise EdgarSetupError(
            "EDGAR_USER_AGENT is not set (environment or the repo .env); SEC refuses the fallback "
            f"User-Agent {FALLBACK_UA!r}. Set it to a name and a contact address, e.g. 'Jane Doe jane@example.com'.")
    return ua


def _throttle() -> None:
    """Wait for this process's next SEC request slot. Every SEC request in the
    library (EdgarClient, sec_http, verify_against_web) calls this, from any
    thread. It reads the module's SEC_LIMITER at each call, so a test or the
    CLI can swap or extend the limiter."""
    SEC_LIMITER.acquire()


# Backoff between retry attempts, in seconds: 2s after the 1st failure, 4s
# after the 2nd (3 attempts total, like OpenFigiClient._post).
RETRY_BACKOFF = (2, 4)
RETRY_MAX_ATTEMPTS = 3


def retry_request(make_request, *, sleep=time.sleep, max_attempts: int = RETRY_MAX_ATTEMPTS,
                  backoff: tuple[float, ...] = RETRY_BACKOFF):
    """Call `make_request()` (a callable returning a `requests.Response`) up
    to `max_attempts` times, retrying a connection error, a timeout, or a 5xx
    response with `backoff` seconds between attempts (`sleep` is injectable
    for tests). `check_response` runs on every response that comes back, so a
    403/429 raises `EdgarBlocked` immediately -- it is never retried. A 404 or
    any other non-5xx response is returned on the first attempt, unchanged.

    After every failed attempt the shared SEC_LIMITER is paused for that
    attempt's backoff (the last attempt for the last backoff), so every other
    thread's next SEC request waits too: while SEC is failing, the pool backs
    off together instead of sending ~8 mostly failing requests a second. An
    attempt beyond the end of `backoff` reuses its last value; an empty
    `backoff` retries at once, with no pause and no sleep.

    On final failure: if every attempt raised, the last exception is
    re-raised; if the last attempt returned a persistent 5xx response, that
    response is returned (the caller's own `raise_for_status()`/status check
    decides what happens next -- unchanged from before this helper existed).
    """
    last_exc: requests.RequestException | None = None
    resp = None
    for attempt in range(max_attempts):
        try:
            resp = make_request()
        except requests.RequestException as exc:
            last_exc, resp = exc, None
        else:
            check_response(resp)              # 403/429 -> EdgarBlocked, raised at once, never retried
            if resp.status_code < 500:
                return resp
            last_exc = None                   # a 5xx is retryable, not a transport exception
        if not backoff:
            continue
        wait = backoff[min(attempt, len(backoff) - 1)]
        SEC_LIMITER.pause(wait)               # every thread's next SEC request waits too
        if attempt < max_attempts - 1:
            sleep(wait)
    if resp is not None:
        return resp
    raise last_exc


@dataclass
class EdgarSubmission:
    """One row from the recent-filings table on submissions.json."""

    accession: str
    form: str
    filing_date: str       # YYYY-MM-DD
    report_date: str       # YYYY-MM-DD or ''
    items: str             # comma-separated 8-K item codes (may be '')
    primary_doc: str

    @property
    def item_set(self) -> set[str]:
        return {x.strip() for x in self.items.split(",") if x.strip()}


class EdgarClient:
    def __init__(
        self,
        cache_dir: str | Path,
        user_agent: str | None = None,
        session: requests.Session | None = None,
        sleep=time.sleep,
    ) -> None:
        """`session`: one HTTP session for every thread (tests inject a fake);
        without it each thread gets its own `requests.Session`."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or resolve_user_agent()
        self._session = session
        self._local = threading.local()
        self.sleep = sleep
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        for d in (self.cache_dir, self.cache_dir / "text", self.cache_dir / "raw"):
            clean_orphan_temps(d)

    @property
    def session(self) -> requests.Session:
        """The calling thread's HTTP session (requests.Session is not thread-safe:
        its cookie jar changes with every answer), or the session injected at
        construction, which every thread shares."""
        if self._session is not None:
            return self._session
        s = getattr(self._local, "session", None)
        if s is None:
            s = self._local.session = requests.Session()
        return s

    def _headers(self, host: str, accept: str) -> dict[str, str]:
        """Every request's headers, built per call: no session-wide default can
        send a wrong Host."""
        return {"User-Agent": self.user_agent, "Accept": accept, "Host": host}

    def _get(self, url: str, *, host: str, accept: str, retry: bool = True):
        """GET `url` on this thread's session, through the shared limiter, with this
        request's own headers. With `retry`, through `retry_request`: a transport
        error or a 5xx is retried with backoff, every thread pausing with it, and
        a 403/429 raises EdgarBlocked at once. Without it, one attempt, and a 5xx
        or a transport error still pauses every thread for the first backoff."""
        headers = self._headers(host, accept)
        session = self.session

        def make():
            _throttle()
            return session.get(url, headers=headers, timeout=30)

        if retry:
            return retry_request(make, sleep=self.sleep)
        try:
            resp = make()
        except requests.RequestException:
            SEC_LIMITER.pause(RETRY_BACKOFF[0])
            raise
        if resp.status_code >= 500:
            SEC_LIMITER.pause(RETRY_BACKOFF[0])
        return resp

    def _lock_for(self, key: str) -> threading.Lock:
        """The lock of one cache file (`key` = its path). Whoever holds it is the
        only thread checking, fetching or writing that file, so two threads
        needing the same answer make one request: the second waits, then reads
        what the first wrote. No method holds two of these at once."""
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = threading.Lock()
            return lock

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.json"

    def _get_json(self, url: str, *, refresh: bool = False, fresh_after: date | None = None) -> Any:
        """The cached payload, unless `refresh` or it was fetched before `fresh_after`.

        When a refetch fails and a cached dict exists, that copy is returned with
        STALE_KEY added to the returned dict only. "Fails" deliberately covers a
        5xx as well as a transport error: `raise_for_status` raises
        `requests.HTTPError`, which is a `requests.RequestException`, so an SEC
        outage serves the cache instead of erroring the row out. `EdgarBlocked`
        (403/429) is a `RuntimeError` and still propagates, as does any failure
        with no cached copy to fall back on.

        One thread at a time per cache file (`_lock_for`): a second caller for
        the same URL waits, then reads what the first wrote. On a prefetch thread
        (`fill_only`) a cached copy is returned whatever its age.
        """
        cp = self._cache_path(url)
        with self._lock_for(str(cp)):
            cached: Any = None
            if cp.exists() and not refresh:
                try:
                    cached = json.loads(cp.read_text())
                except json.JSONDecodeError:
                    cp.unlink(missing_ok=True)
                else:
                    if fresh_after is None or filling_only() or _fetched_on(cp, cached) >= fresh_after:
                        return cached
            host = "data.sec.gov" if url.startswith(SEC_HOST) else "www.sec.gov"
            try:
                resp = self._get(url, host=host, accept="application/json")   # EdgarBlocked propagates
                if resp.status_code != 404:
                    resp.raise_for_status()
            except requests.RequestException:
                # A failed refresh must not turn a company with a usable cached copy
                # into an error row -- every event newer than SUBMISSIONS_FRESH_DAYS
                # refetches on every run. Serve the cache, marked stale in the
                # returned dict only, so callers can flag the row.
                if not isinstance(cached, dict):
                    raise
                return {**cached, STALE_KEY: True}
            today = date.today().isoformat()
            if resp.status_code == 404:
                data = {"__not_found__": True, "url": url, FETCHED_KEY: today}
                _write_atomic(cp, json.dumps(data))
                return data
            try:
                data = resp.json()
            except json.JSONDecodeError:
                data = {"__raw__": resp.text, "url": url}
            if isinstance(data, dict):
                data[FETCHED_KEY] = today
            _write_atomic(cp, json.dumps(data))
            return data

    def company_tickers(self) -> dict[str, dict[str, Any]]:
        """Master ticker→CIK map. ~10k entries; refresh weekly is enough.

        Returns dict keyed by uppercase ticker.
        """
        url = f"{WWW_SEC_HOST}/files/company_tickers.json"
        raw = self._get_json(url)
        out: dict[str, dict[str, Any]] = {}
        if not isinstance(raw, dict):
            return out
        for v in raw.values():
            if not isinstance(v, dict):
                continue
            t = str(v.get("ticker", "")).upper()
            if t:
                out[t] = v
        return out

    def company_search_atom(self, company: str, form_type: str = "25-NSE") -> list[dict[str, Any]]:
        """Search EDGAR by company name; return [{cik, name, form, date}, ...].

        Uses the cgi-bin/browse-edgar ATOM endpoint. The ATOM XML has a
        single <company-info> block (top match) and an <entry> per filing.
        We return the top company's CIK along with any matching filings.

        Cached on disk like `_get_json` (same `FETCHED_KEY` / stored fetch
        date), but never for an empty or error answer: an empty result would
        otherwise silently and permanently hide a correct hit that only shows
        up once EDGAR's index catches up. A cached hit older than
        `COMPANY_SEARCH_FRESH_DAYS` is refetched — and, like `_get_json`, a
        failed refetch (transport error or non-200) serves the stale cached
        hit rather than erroring the row out, so a transient SEC outage can't
        turn a company with a usable cached answer into an empty result.
        """
        url = (
            f"{WWW_SEC_HOST}/cgi-bin/browse-edgar?action=getcompany"
            f"&company={requests.utils.quote(company)}&type={form_type}"
            "&dateb=&owner=include&count=10&output=atom"
        )
        cp = self._cache_path(url)
        fresh_after = date.today() - timedelta(days=COMPANY_SEARCH_FRESH_DAYS)
        cached: Any = None
        if cp.exists():
            try:
                cached = json.loads(cp.read_text())
            except json.JSONDecodeError:
                cp.unlink(missing_ok=True)
                cached = None
            else:
                if isinstance(cached, dict) and _fetched_on(cp, cached) >= fresh_after:
                    return cached.get("hits", [])

        try:
            resp = self._get(url, host="www.sec.gov", accept="application/atom+xml,text/xml", retry=False)
            check_response(resp)          # EdgarBlocked is not a RequestException: it propagates
            if resp.status_code != 200:
                return cached.get("hits", []) if isinstance(cached, dict) else []
        except requests.RequestException:
            return cached.get("hits", []) if isinstance(cached, dict) else []
        text = resp.text
        # Quick-and-dirty XML extraction; the document is tiny and well-formed.
        import re as _re
        out: list[dict[str, Any]] = []
        ci_cik = _re.search(r"<cik>\s*(\d+)\s*</cik>", text)
        ci_name = _re.search(r"<conformed-name>(.*?)</conformed-name>", text)
        company_cik = int(ci_cik.group(1)) if ci_cik else None
        company_name = ci_name.group(1) if ci_name else None
        if company_cik is None:
            return []
        entries = _re.findall(
            r"<entry>(.*?)</entry>", text, flags=_re.DOTALL
        )
        for e in entries:
            fd = _re.search(r"<filing-date>(\d{4}-\d{2}-\d{2})</filing-date>", e)
            ft = _re.search(r"<filing-type>([^<]+)</filing-type>", e)
            out.append({
                "cik": company_cik,
                "name": company_name,
                "form": ft.group(1) if ft else "",
                "filing_date": fd.group(1) if fd else "",
            })
        if not entries:
            out.append({"cik": company_cik, "name": company_name, "form": "", "filing_date": ""})
        if out:   # never cache an empty or error answer (see docstring)
            _write_atomic(cp, json.dumps({"hits": out, FETCHED_KEY: date.today().isoformat()}))
        return out

    def submissions(self, cik: int | str, fresh_after: date | None = None) -> dict[str, Any]:
        """The company's submissions JSON. A cached copy fetched before
        `fresh_after` is fetched again (and the cache rewritten), so filings
        made after the cache date are seen."""
        cik_str = str(int(cik)).zfill(10)
        url = f"{SEC_HOST}/submissions/CIK{cik_str}.json"
        return self._get_json(url, fresh_after=fresh_after)

    def fetch_filing_text(self, cik: int | str, accession: str, primary_doc: str) -> str:
        """Fetch a filing's primary document, return stripped plain text.

        Cached as utf-8 under cache/edgar/text/{accession_no_dashes}.txt.
        Returns '' on empty primary_doc, 404, or network error so callers can
        fall through to the next tier. A 404 is cached as a sticky miss;
        transient non-200s are not cached so a later run retries.
        """
        # An empty primary_doc would resolve to the directory-listing URL, which
        # returns 200 and a useless file index — never fetch it (FIX 7).
        if not primary_doc:
            return ""
        acc_nodash = accession.replace("-", "")
        text_dir = self.cache_dir / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        cp = text_dir / f"{acc_nodash}.txt"
        with self._lock_for(str(cp)):
            if cp.exists():
                return cp.read_text(encoding="utf-8")
            url = f"{WWW_SEC_HOST}/Archives/edgar/data/{int(cik)}/{acc_nodash}/{primary_doc}"
            try:
                resp = self._get(url, host="www.sec.gov", accept="text/html,*/*", retry=False)
            except requests.RequestException:
                return ""
            check_response(resp)
            if resp.status_code != 200:
                # Only a 404 is a stable "not found" worth caching as a sticky miss.
                # Caching other non-200s (429/503/etc.) would turn a transient outage
                # into a permanent empty result, so leave the cache untouched (FIX 6).
                if resp.status_code == 404:
                    _write_atomic(cp, "")
                return ""
            text = _strip_html(resp.text)
            _write_atomic(cp, text)
            return text

    def fetch_filing_raw(self, cik: int | str, accession: str) -> str:
        """The complete submission text file: every document of the filing with
        its <TYPE> header and raw markup (Form 25 XML plus its EX-99.25 notice).

        Cached under cache/edgar/raw/{accession_no_dashes}.txt. Returns '' on a
        404 (cached as a sticky miss) or a network error (not cached). A 403/429
        raises EdgarBlocked.
        """
        acc_nodash = accession.replace("-", "")
        raw_dir = self.cache_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        cp = raw_dir / f"{acc_nodash}.txt"
        with self._lock_for(str(cp)):
            if cp.exists():
                return cp.read_text(encoding="utf-8", errors="replace")
            url = f"{WWW_SEC_HOST}/Archives/edgar/data/{int(cik)}/{acc_nodash}/{accession}.txt"
            try:
                resp = self._get(url, host="www.sec.gov", accept="text/plain,*/*")   # EdgarBlocked propagates
            except requests.RequestException:
                return ""
            if resp.status_code != 200:
                if resp.status_code == 404:
                    _write_atomic(cp, "")
                return ""
            _write_atomic(cp, resp.text)
            return resp.text

    def full_text_search(self, q: str, forms: str, lo: date, hi: date) -> list[dict]:
        """EDGAR full-text search hits (`hits.hits`) for `q` within `forms`,
        filed in `[lo, hi]`.

        Cached on disk under this client's cache directory, keyed by the
        request URL, the same way `_get_json` caches — a second identical
        call makes no request. Never cached: a network error or non-200
        response (so a miss is retried, and a 5xx never freezes in as an
        empty answer); an empty hit list (EDGAR's index may simply not have
        caught up yet); or an answer for a window that ends on or after
        today (the filing it would find may not exist yet). A 403/429
        raises `EdgarBlocked` like every other EDGAR call.
        """
        url = (
            "https://efts.sec.gov/LATEST/search-index?"
            f"q={requests.utils.quote(q)}&forms={requests.utils.quote(forms)}"
            f"&dateRange=custom&startdt={lo.isoformat()}&enddt={hi.isoformat()}"
        )
        cp = self._cache_path(url)
        if cp.exists():
            try:
                cached = json.loads(cp.read_text())
            except json.JSONDecodeError:
                cp.unlink(missing_ok=True)
            else:
                if isinstance(cached, list):
                    return cached

        try:
            resp = self._get(url, host="efts.sec.gov", accept="application/json")   # EdgarBlocked propagates
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except (ValueError, TypeError):
            return []
        hits = data.get("hits", {}).get("hits", []) if isinstance(data, dict) else []
        if hits and hi < date.today():
            _write_atomic(cp, json.dumps(hits))
        return hits

    def recent_filings(self, cik: int | str) -> list[EdgarSubmission]:
        sub = self.submissions(cik)
        if not isinstance(sub, dict) or sub.get("__not_found__"):
            return []
        recent = sub.get("filings", {}).get("recent", {})
        n = len(recent.get("accessionNumber", []))
        out: list[EdgarSubmission] = []
        for i in range(n):
            out.append(
                EdgarSubmission(
                    accession=recent["accessionNumber"][i],
                    form=recent["form"][i],
                    filing_date=recent.get("filingDate", [""] * n)[i],
                    report_date=recent.get("reportDate", [""] * n)[i],
                    items=recent.get("items", [""] * n)[i],
                    primary_doc=recent.get("primaryDocument", [""] * n)[i],
                )
            )
        # also pull historical files (paginated chunks of older filings)
        for fchunk in sub.get("filings", {}).get("files", []):
            url = f"{SEC_HOST}/submissions/{fchunk['name']}"
            data = self._get_json(url)
            if not isinstance(data, dict) or data.get("__not_found__"):
                continue
            n = len(data.get("accessionNumber", []))
            for i in range(n):
                out.append(
                    EdgarSubmission(
                        accession=data["accessionNumber"][i],
                        form=data["form"][i],
                        filing_date=data.get("filingDate", [""] * n)[i],
                        report_date=data.get("reportDate", [""] * n)[i],
                        items=data.get("items", [""] * n)[i],
                        primary_doc=data.get("primaryDocument", [""] * n)[i],
                    )
                )
        return out

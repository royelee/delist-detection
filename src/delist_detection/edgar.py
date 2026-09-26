"""Thin EDGAR client. Handles SEC fair-access throttling and on-disk caching.

SEC requires a descriptive User-Agent and ≤10 req/sec from a single IP. We cap
at 8 req/sec and cache every JSON payload, so repeated runs cost nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from . import sec_limiter
from .atomic_io import clean_orphan_temps, write_atomic
from .html_text import strip_html
from .retries import retrying
from .sec_stats import SEC_STATS, endpoint_of, filling_only
from .settings import REPO_ENV, env_setting

log = logging.getLogger(__name__)


SEC_HOST = "https://data.sec.gov"
WWW_SEC_HOST = "https://www.sec.gov"
# SEC requires a descriptive User-Agent with a contact, and 403s ones it
# doesn't accept (SEC has rejected this noreply fallback).
FALLBACK_UA = "delist_detection/0.1 (r@users.noreply.github.com)"


class EdgarBlocked(RuntimeError):
    """SEC refused the request (403/429). Callers must never read this as 'no match':
    from 2026-05-28 to 2026-09-16 every refusal was cached as 'No CIK found'."""


def check_response(resp) -> None:
    if resp.status_code in (403, 429):
        raise EdgarBlocked(
            f"SEC returned {resp.status_code} for {getattr(resp, 'url', '?')}. "
            "Set EDGAR_USER_AGENT to a real contact address (see resolve_user_agent) or slow down."
        )


def resolve_user_agent(env_file: str | Path = REPO_ENV) -> str:
    """EDGAR_USER_AGENT from the environment, else from ``env_file``, else the
    fallback (`settings.env_setting`: that one key only; ``os.environ`` untouched)."""
    return env_setting("EDGAR_USER_AGENT", env_file) or FALLBACK_UA


DEFAULT_UA = resolve_user_agent()

# The day a cached JSON payload was fetched; a payload without it is dated by its file time.
FETCHED_KEY = "__fetched__"
# Marks a payload served from cache because the refetch failed. Added to the
# returned dict only, never written to disk.
STALE_KEY = "__stale__"
SUBMISSIONS_FRESH_DAYS = 45  # filings this long after the last trade must be in the submissions read
COMPANY_SEARCH_FRESH_DAYS = 7  # a company-search answer this old is refetched, never trusted forever

# EDGAR full-text search (efts.sec.gov). Every answer, hits or empty, is cached
# under the URL's SHA1 with the day it was fetched, and holds for
# efts_ttl_days(window_end, fetched): the time from the end of its date window to
# the fetch, kept within [EFTS_MIN_TTL_DAYS, EFTS_MAX_TTL_DAYS]. An answer fetched
# soon after its window closed (or while it is open) can still change as EDGAR
# indexes late filings, so it is asked again within a week; one fetched long after
# has settled, but SEC re-indexes, so even it is asked again yearly. EDGAR's
# full-text index starts in 2001: a window ending before EFTS_COVERAGE_START is not
# covered and is never sent.
EFTS_SCHEMA = 1
EFTS_KEY = "efts_hits"
EFTS_MIN_TTL_DAYS, EFTS_MAX_TTL_DAYS = 7, 365
EFTS_COVERAGE_START = date(2001, 1, 1)
# The only `_source` fields a caller reads (resolver: ciks, display_names; successor
# search: file_date too); form and adsh keep a cached answer readable, `_id` names
# the document the review loop curls.
EFTS_SOURCE_KEYS = ("ciks", "display_names", "form", "file_date", "adsh")


def efts_ttl_days(window_end: date, fetched: date) -> int:
    """Days a full-text-search answer fetched on `fetched` holds (see above)."""
    return max(EFTS_MIN_TTL_DAYS, min(EFTS_MAX_TTL_DAYS, (fetched - window_end).days))


def _trim_hits(hits: Any) -> list[dict]:
    """EFTS hits with each `_source` cut to EFTS_SOURCE_KEYS and `_id` kept: the
    same dicts whether an answer comes from the network or the cache."""
    out: list[dict] = []
    for h in hits if isinstance(hits, list) else []:
        if not isinstance(h, dict):
            continue
        src = h.get("_source") if isinstance(h.get("_source"), dict) else {}
        hit: dict = {"_source": {k: src[k] for k in EFTS_SOURCE_KEYS if k in src}}
        if "_id" in h:
            hit = {"_id": h["_id"], **hit}
        out.append(hit)
    return out


def submissions_fresh_after(on: date, today: date | None = None) -> date:
    """The `fresh_after` for reading an issuer's submissions about an event on `on`:
    `min(on + 45 days, today)`, where `today` is the run date (default: the clock).
    The classifier and the resolver both use it."""
    return min(on + timedelta(days=SUBMISSIONS_FRESH_DAYS), today or date.today())


def _fetched_on(cp: Path, data: Any) -> date:
    if isinstance(data, dict):
        try:
            return date.fromisoformat(data.get(FETCHED_KEY))
        except (TypeError, ValueError):
            pass
    return date.fromtimestamp(cp.stat().st_mtime)


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

    After every failed attempt the shared `sec_limiter.SEC_LIMITER` is paused for that
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
    def wait(attempt: int, resp, error) -> float | None:
        if resp is not None:
            check_response(resp)              # 403/429 -> EdgarBlocked, raised at once, never retried
            if resp.status_code < 500:
                return None                   # an answer
        if not backoff:
            return 0                          # a transport error or a 5xx: retry at once
        seconds = backoff[min(attempt, len(backoff) - 1)]
        sec_limiter.SEC_LIMITER.pause(seconds)    # every thread's next SEC request waits too
        return seconds

    resp, error = retrying(make_request, attempts=max_attempts, wait=wait, sleep=sleep)
    if error is not None:
        raise error
    return resp


def sec_get(url: str, *, headers: dict[str, str], timeout: float, session=None, endpoint: str | None = None,
            retry: bool = True, sleep=time.sleep):
    """GET `url` from SEC: the one request path every SEC client shares
    (EdgarClient, sec_http, verify_against_web). Each attempt waits for the
    shared limiter (`sec_limiter.throttle`), is counted as `request:<endpoint>` and timed
    under `endpoint` in `sec_stats.SEC_STATS` (default: `endpoint_of(url)`), and goes out on
    `session` (default: a one-off `requests.get`) with `headers` as given --
    the caller's User-Agent and, where it matters, Host.

    With `retry`, through `retry_request`: a transport error or a 5xx is
    retried with backoff, every thread pausing with it, and a 403/429 raises
    EdgarBlocked at once. Without it, one attempt: a 403/429 still raises
    EdgarBlocked at once, and a 5xx or a transport error still pauses every
    thread for the first backoff (a transport error is then re-raised, a 5xx
    returned)."""
    get = session.get if session is not None else requests.get
    endpoint = endpoint or endpoint_of(url)

    def make():
        sec_limiter.throttle()
        SEC_STATS.add(f"request:{endpoint}")
        started = time.monotonic()
        try:
            return get(url, headers=headers, timeout=timeout)
        finally:
            SEC_STATS.timing(endpoint, time.monotonic() - started)

    if retry:
        return retry_request(make, sleep=sleep)
    try:
        resp = make()
    except requests.RequestException:
        sec_limiter.SEC_LIMITER.pause(RETRY_BACKOFF[0])
        raise
    check_response(resp)              # 403/429 -> EdgarBlocked, as on the retried path
    if resp.status_code >= 500:
        sec_limiter.SEC_LIMITER.pause(RETRY_BACKOFF[0])
    return resp


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


# A genuine EDGAR company-search answer, matched or not, is always a complete
# ATOM feed (see tests/fixtures/company_search/: nomatch.atom is a <feed> with
# no <cik>, just like onematch.atom and multimatch.atom are <feed>s with one).
# Anything else at 200 -- an HTML error or maintenance page, a truncated body --
# is not an answer and must never be read as "no match".
_ATOM_FEED = re.compile(r"\A\s*(?:<\?xml[^>]*\?>\s*)?<feed[\s>].*</feed>\s*\Z", re.DOTALL)


def _parse_company_atom(text: str) -> list[dict[str, Any]]:
    """The hits of a cgi-bin/browse-edgar ATOM answer: the top issuer with each of
    its filings, or the issuer alone when it lists none; [] when no issuer matched."""
    ci_cik = re.search(r"<cik>\s*(\d+)\s*</cik>", text)
    if not ci_cik:
        return []
    ci_name = re.search(r"<conformed-name>(.*?)</conformed-name>", text)
    issuer_cik = int(ci_cik.group(1))
    issuer_name = ci_name.group(1) if ci_name else None
    entries = re.findall(r"<entry>(.*?)</entry>", text, flags=re.DOTALL)
    out: list[dict[str, Any]] = []
    for e in entries:
        fd = re.search(r"<filing-date>(\d{4}-\d{2}-\d{2})</filing-date>", e)
        ft = re.search(r"<filing-type>([^<]+)</filing-type>", e)
        out.append({"cik": issuer_cik, "name": issuer_name,
                    "form": ft.group(1) if ft else "", "filing_date": fd.group(1) if fd else ""})
    if not entries:
        out.append({"cik": issuer_cik, "name": issuer_name, "form": "", "filing_date": ""})
    return out


class EdgarClient:
    """The EDGAR client, one instance shared by every thread of a run: each thread
    sends on its own HTTP session, and each cache file has its own lock
    (`_lock_for`). The lock table grows by one entry per cache file the client
    touches and is never pruned, for the client's lifetime: one small lock per
    file, fine for a CLI run."""

    def __init__(
        self,
        cache_dir: str | Path,
        user_agent: str | None = None,
        session: requests.Session | None = None,
        sleep=time.sleep,
        *,
        today: date | None = None,
        search_cache: bool = True,
    ) -> None:
        """`session`: one HTTP session for every thread (tests inject a fake);
        without it each thread gets its own `requests.Session`. `today`: the run
        date every freshness rule and fetch stamp uses (default: the clock, read
        at each use). `search_cache=False` neither reads nor writes the
        full-text-search and company-search caches: the golden-fixture builder
        must record live answers."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or resolve_user_agent()
        self._session = session
        self._local = threading.local()
        self.sleep = sleep
        self._today = today
        self.search_cache = search_cache
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        # Answers not written to disk (undated full-text searches, rejected
        # queries), kept for the life of this client -- one run -- so a warm
        # worker and the sequential pass send each one once.
        self._run_memo: dict[str, list] = {}
        for d in (self.cache_dir, self.cache_dir / "text", self.cache_dir / "raw"):
            clean_orphan_temps(d)

    @property
    def today(self) -> date:
        """The run date: the one given at construction, else the clock's."""
        return self._today or date.today()

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
        """GET `url` on this thread's session with this request's own headers
        (`sec_get`: the shared limiter, SEC_STATS, and with `retry` the shared
        retries)."""
        return sec_get(url, session=self.session, headers=self._headers(host, accept), timeout=30,
                       retry=retry, sleep=self.sleep)

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
        outage serves the cache instead of erroring the row out. A 200 whose
        body is not JSON (an HTML error/maintenance page) fails the same way --
        it is never written as an answer (no `{"__raw__": ...}` fallback), since
        that could silently overwrite a good submissions copy and hide a Form
        25. `EdgarBlocked` (403/429) is a `RuntimeError` and still propagates,
        as does any failure with no cached copy to fall back on.

        One thread at a time per cache file (`_lock_for`): a second caller for
        the same URL waits, then reads what the first wrote. On a prefetch thread
        (`fill_only`) a cached copy is returned whatever its age, even with
        `refresh`: a warm pass never replaces a copy.
        """
        cp = self._cache_path(url)
        with self._lock_for(str(cp)):
            cached: Any = None
            if cp.exists() and (not refresh or filling_only()):
                try:
                    cached = json.loads(cp.read_text())
                except json.JSONDecodeError:
                    cp.unlink(missing_ok=True)
                else:
                    if fresh_after is None or filling_only() or _fetched_on(cp, cached) >= fresh_after:
                        SEC_STATS.add(f"cache:{endpoint_of(url)}")
                        return cached
            host = "data.sec.gov" if url.startswith(SEC_HOST) else "www.sec.gov"
            try:
                resp = self._get(url, host=host, accept="application/json")   # EdgarBlocked propagates
                if resp.status_code != 404:
                    resp.raise_for_status()
                    try:
                        data = resp.json()
                    except json.JSONDecodeError as exc:
                        # A 200 that is not JSON (an HTML error/maintenance page) is not
                        # an answer. Writing it as {"__raw__": ...} could overwrite a good
                        # submissions copy and silently hide a Form 25, so it is never
                        # written: fall into the same failed-refresh handling as a 5xx or
                        # a transport error, below.
                        raise requests.RequestException(f"EDGAR sent a non-JSON 200 for {url}") from exc
            except requests.RequestException:
                # A failed refresh must not turn an issuer with a usable cached copy
                # into an error row -- every event newer than SUBMISSIONS_FRESH_DAYS
                # refetches on every run. Serve the cache, marked stale in the
                # returned dict only, so callers can flag the row.
                if not isinstance(cached, dict):
                    SEC_STATS.degraded("failed_request")
                    raise
                SEC_STATS.degraded("stale_copy")
                return {**cached, STALE_KEY: True}
            today = self.today.isoformat()
            if resp.status_code == 404:
                data = {"__not_found__": True, "url": url, FETCHED_KEY: today}
                write_atomic(cp, json.dumps(data))
                return data
            if isinstance(data, dict):
                data[FETCHED_KEY] = today
            write_atomic(cp, json.dumps(data))
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
        """Search EDGAR by company name; return [{cik, name, form, filing_date}, ...].

        Uses the cgi-bin/browse-edgar ATOM endpoint. The ATOM XML has a single
        <company-info> block (top match) and an <entry> per filing; we return the
        top issuer's CIK with each matching filing.

        Every answer, hits or empty, is cached with the day it was fetched and
        trusted for COMPANY_SEARCH_FRESH_DAYS (7): EDGAR's index can catch up, so
        no answer is kept longer, and the resolver re-derives any miss from these
        answers on every run. The request is retried like every other SEC call. A
        400 or 404 is a rejected query: logged, counted as `rejected:company_search`,
        returned as [], never cached, and not transient. A 200 body that is not a
        complete ATOM feed (an HTML error or maintenance page, a truncated body --
        see `_ATOM_FEED`) is not an answer either, and is handled like a 5xx: if
        it still fails, a cached hit list, however old, is served with STALE_KEY
        on each hit (the caller must not save what it builds on it); with no hits
        to fall back on it raises `requests.RequestException` -- an unanswered
        search is not an empty one. A 403/429 raises `EdgarBlocked`. With
        `search_cache` off, the disk cache is neither read nor written. On a
        prefetch thread (`fill_only`) a cached answer is returned whatever its
        age; an existing file this client cannot read as a current answer
        (unreadable, or with no `hits` list) is answered as [] instead, with no
        request and the file untouched.
        """
        url = (
            f"{WWW_SEC_HOST}/cgi-bin/browse-edgar?action=getcompany"
            f"&company={requests.utils.quote(company)}&type={form_type}"
            "&dateb=&owner=include&count=10&output=atom"
        )
        cp = self._cache_path(url)
        with self._lock_for(str(cp)):
            cached: Any = None
            if self.search_cache and cp.exists():
                try:
                    cached = json.loads(cp.read_text())
                except json.JSONDecodeError:
                    if filling_only():
                        return []
                    cp.unlink(missing_ok=True)
                    cached = None
                else:
                    if not (isinstance(cached, dict) and isinstance(cached.get("hits"), list)):
                        if filling_only():
                            return []
                    else:
                        fresh_after = self.today - timedelta(days=COMPANY_SEARCH_FRESH_DAYS)
                        if filling_only() or _fetched_on(cp, cached) >= fresh_after:
                            SEC_STATS.add("cache:company_search")
                            return list(cached["hits"])
            try:
                resp = self._get(url, host="www.sec.gov", accept="application/atom+xml,text/xml")
                if resp.status_code in (400, 404):
                    log.warning("EDGAR company search rejected %s (HTTP %d): no answer, not cached",
                                url, resp.status_code)
                    SEC_STATS.add("rejected:company_search")
                    return []
                if resp.status_code != 200:
                    raise requests.HTTPError(f"EDGAR company search answered {resp.status_code} for {url}")
                if not _ATOM_FEED.match(resp.text):
                    raise requests.RequestException(f"EDGAR company search sent a non-ATOM body for {url}")
            except requests.RequestException:
                hits = cached.get("hits") if isinstance(cached, dict) else None
                if isinstance(hits, list) and hits:
                    SEC_STATS.degraded("stale_copy")
                    return [{**h, STALE_KEY: True} for h in hits]
                SEC_STATS.degraded("failed_request")
                raise
            out = _parse_company_atom(resp.text)
            if self.search_cache:
                write_atomic(cp, json.dumps({"hits": out, FETCHED_KEY: self.today.isoformat()}))
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
        transient non-200s are not cached so a later run retries. A connection
        error, a timeout or a 5xx is retried like `fetch_filing_raw` (up to 3
        attempts, `edgar.retry_request`): one transport blip must not turn a
        readable filing into a degraded row.
        """
        # An empty primary_doc would resolve to the directory-listing URL, which
        # returns 200 and a useless file index — never fetch it.
        if not primary_doc:
            return ""
        acc_nodash = accession.replace("-", "")
        text_dir = self.cache_dir / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        cp = text_dir / f"{acc_nodash}.txt"
        with self._lock_for(str(cp)):
            if cp.exists():
                SEC_STATS.add("cache:archives")
                return cp.read_text(encoding="utf-8")
            url = f"{WWW_SEC_HOST}/Archives/edgar/data/{int(cik)}/{acc_nodash}/{primary_doc}"
            try:
                resp = self._get(url, host="www.sec.gov", accept="text/html,*/*")   # EdgarBlocked propagates
            except requests.RequestException:
                SEC_STATS.degraded("failed_request")
                return ""
            check_response(resp)
            if resp.status_code != 200:
                # Only a 404 is a stable "not found" worth caching as a sticky miss.
                # Caching other non-200s (429/503/etc.) would turn a transient outage
                # into a permanent empty result, so leave the cache untouched.
                if resp.status_code == 404:
                    write_atomic(cp, "")
                else:
                    SEC_STATS.degraded("failed_request")
                return ""
            text = strip_html(resp.text)
            write_atomic(cp, text)
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
                SEC_STATS.add("cache:archives")
                return cp.read_text(encoding="utf-8", errors="replace")
            url = f"{WWW_SEC_HOST}/Archives/edgar/data/{int(cik)}/{acc_nodash}/{accession}.txt"
            try:
                resp = self._get(url, host="www.sec.gov", accept="text/plain,*/*")   # EdgarBlocked propagates
            except requests.RequestException:
                SEC_STATS.degraded("failed_request")
                return ""
            if resp.status_code != 200:
                if resp.status_code == 404:
                    write_atomic(cp, "")
                else:
                    SEC_STATS.degraded("failed_request")
                return ""
            write_atomic(cp, resp.text)
            return resp.text

    def _efts_cached(self, cp: Path, window_end: date, *, any_age: bool = False) -> list[dict] | None:
        """The answer cached at `cp` while it holds (efts_ttl_days), or, with
        `any_age` (a prefetch thread, `fill_only`), the file's hits whatever
        their age. None means "no usable answer, go fetch" -- reachable only
        outside `fill_only`: there, an unreadable file, a bare list (the old
        full_text_search's format) or a file of another schema is asked again
        and replaced. A prefetch thread never replaces a file: the same three
        cases instead answer `[]`, with no request and no write, and the file
        is left exactly as it is; the warm pass discards the `[]`, and the
        sequential pass handles the file as it does today. The caller holds
        the file's lock."""
        if not cp.exists():
            return None
        try:
            data = json.loads(cp.read_text())
        except json.JSONDecodeError:
            if any_age:
                return []
            cp.unlink(missing_ok=True)
            return None
        if isinstance(data, list):
            return [] if any_age else None
        if not isinstance(data, dict) or data.get("schema") != EFTS_SCHEMA or not isinstance(data.get(EFTS_KEY), list):
            return [] if any_age else None
        fetched = _fetched_on(cp, data)
        if any_age or self.today < fetched + timedelta(days=efts_ttl_days(window_end, fetched)):
            return data[EFTS_KEY]
        return None

    def efts_search(self, url: str, *, window_end: date | None) -> list[dict]:
        """`hits.hits` of an EDGAR full-text-search URL, each hit's `_source` cut to
        EFTS_SOURCE_KEYS and its `_id` kept. `window_end` is the last filing date
        the query covers (None: the query has no date window).

        Every answer, hits or empty, is written under the URL's SHA1 with its
        schema, window end and fetch date, and holds for efts_ttl_days. A window
        ending before EFTS_COVERAGE_START returns [] with no request (EDGAR's
        index does not cover it). An undated answer is kept in memory for this
        client's run only, as copies: mutating a returned hit never reaches a
        later call. A 400 or 404 is a rejected query: logged, counted, returned
        as [], never written, and kept in memory so one run sends it once; it is
        not a failure. A transport error or 5xx after the retries, a body that
        is not JSON, or a 200 body that is not a search answer (no `hits.hits`
        list -- an EDGAR error body, say) raises `requests.RequestException`,
        and nothing is cached: a malformed answer must never freeze in as an
        empty one. A 403/429 raises `EdgarBlocked`, never retried. On a prefetch
        thread (`fill_only`) a cached answer of any age is returned; an existing
        file this client cannot read as a current answer is answered as `[]`
        instead, with no request and the file untouched (`_efts_cached`).
        """
        if window_end is not None and window_end < EFTS_COVERAGE_START:
            SEC_STATS.add("not_covered:full_text_search")
            return []
        cp = self._cache_path(url)
        with self._lock_for(str(cp)):
            if self.search_cache:
                memo = self._run_memo.get(url)
                if memo is not None:
                    SEC_STATS.add("cache:full_text_search")
                    return [dict(h) for h in memo]
                if window_end is not None:
                    cached = self._efts_cached(cp, window_end, any_age=filling_only())
                    if cached is not None:
                        SEC_STATS.add("cache:full_text_search")
                        return list(cached)
            try:
                resp = self._get(url, host="efts.sec.gov", accept="application/json")   # EdgarBlocked propagates
            except requests.RequestException:
                SEC_STATS.degraded("failed_request")
                raise
            if resp.status_code in (400, 404):
                log.warning("EDGAR full-text search rejected %s (HTTP %d): no answer, not cached",
                            url, resp.status_code)
                SEC_STATS.add("rejected:full_text_search")
                if self.search_cache:
                    self._run_memo[url] = []
                return []
            if resp.status_code != 200:
                SEC_STATS.degraded("failed_request")
                raise requests.HTTPError(f"EDGAR full-text search answered {resp.status_code} for {url}")
            try:
                data = resp.json()
            except ValueError as exc:                      # requests' JSONDecodeError is a ValueError
                SEC_STATS.degraded("failed_request")
                raise requests.RequestException(f"EDGAR full-text search sent no JSON for {url}") from exc
            outer = data.get("hits") if isinstance(data, dict) else None
            raw_hits = outer.get("hits") if isinstance(outer, dict) else None
            if not isinstance(data, dict) or not isinstance(outer, dict) or not isinstance(raw_hits, list):
                # A 200 body that is not a search answer (an EDGAR error body, a
                # maintenance page as JSON, ...) must never be cached as an empty
                # answer: that could hide a real filing for up to a year.
                SEC_STATS.degraded("failed_request")
                raise requests.RequestException(f"EDGAR full-text search sent an unrecognized body for {url}")
            hits = _trim_hits(raw_hits)
            if self.search_cache:
                if window_end is None:
                    self._run_memo[url] = [dict(h) for h in hits]
                else:
                    write_atomic(cp, json.dumps({"schema": EFTS_SCHEMA, "window_end": window_end.isoformat(),
                                                  FETCHED_KEY: self.today.isoformat(), EFTS_KEY: hits}))
            return list(hits)

    def full_text_search(self, q: str, forms: str, lo: date, hi: date) -> list[dict]:
        """EDGAR full-text search hits (`hits.hits`, trimmed as `efts_search` trims
        them) for `q` within `forms`, filed in `[lo, hi]`, cached as `efts_search`
        caches them. [] when EDGAR could not answer: the successor search then
        leaves `successor_unknown` set. A 403/429 raises `EdgarBlocked`.
        """
        url = (
            "https://efts.sec.gov/LATEST/search-index?"
            f"q={requests.utils.quote(q)}&forms={requests.utils.quote(forms)}"
            f"&dateRange=custom&startdt={lo.isoformat()}&enddt={hi.isoformat()}"
        )
        try:
            return self.efts_search(url, window_end=hi)
        except requests.RequestException:
            return []

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

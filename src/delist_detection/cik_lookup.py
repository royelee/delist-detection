"""SEC's company-name index, `cik-lookup-data.txt`, as a local name -> CIK search.

The file lists every name each CIK filed under (it is historically cumulative:
MICHAEL KORS HOLDINGS LTD and CAPRI HOLDINGS LTD are both CIK 1530721), funds
and individuals included, one `NAME:CIK:` line each. One download replaces the
thousands of live company searches (`cgi-bin/browse-edgar`) the ticker
resolver's name tier would otherwise send, an endpoint SEC throttles hard
(docs/superpowers/plans/2026-09-29-cik-lookup-name-index.md).
"""
from __future__ import annotations

import re
import threading
import time
from bisect import bisect_left
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from .sec_http import get_text

CIK_LOOKUP_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
CIK_LOOKUP_MAX_AGE_DAYS = 30      # SEC refreshes the file; a copy this old is fetched again

_PUNCT = re.compile(r"[&.,'’\"()]")
_STATE_TAG = re.compile(r"\s*/[A-Z]{1,3}/?\s*$")      # EDGAR's "/DE/", "/NY", "/TA"
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """`name` as the index compares it: uppercase, EDGAR's trailing state tag
    dropped, `&` and punctuation read as spaces, whitespace collapsed."""
    s = _STATE_TAG.sub("", (name or "").upper().strip())
    return _SPACES.sub(" ", _PUNCT.sub(" ", s)).strip()


class NameHit(NamedTuple):
    """One index entry: a CIK and one name it filed under."""
    cik: int
    name: str


class CikNameIndex:
    """The entries of cik-lookup-data.txt, sorted by normalized name, searched
    the way EDGAR's company search matches: a name equal to the query, or
    starting with it followed by a space (whole words: BARNES finds BARNES &
    NOBLE INC, not BARNESANDNOBLE COM INC)."""

    def __init__(self, entries: Iterable[tuple[str, int, str]]) -> None:
        self._entries = sorted(set(entries))
        self._keys = [e[0] for e in self._entries]

    @classmethod
    def from_text(cls, text: str) -> "CikNameIndex":
        """Parse `NAME:CIK:` lines; a name may itself hold a colon. Lines with no
        name or no numeric CIK are skipped."""
        entries = []
        for line in text.splitlines():
            parts = line.rstrip().rsplit(":", 2)
            if len(parts) != 3 or not parts[1].strip().isdigit():
                continue
            name = parts[0].strip()
            key = normalize_name(name)
            if key:
                entries.append((key, int(parts[1]), name))
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def split_search(self, query: str) -> tuple[list[NameHit], list[NameHit]]:
        """(the entries whose name equals `query`, those that start with it as
        whole words), each sorted by normalized name then CIK."""
        q = normalize_name(query)
        if not q:
            return [], []
        exact: list[NameHit] = []
        prefix: list[NameHit] = []
        for key, cik, name in self._entries[bisect_left(self._keys, q):]:
            if key == q:
                exact.append(NameHit(cik, name))
            elif key.startswith(q + " "):
                prefix.append(NameHit(cik, name))
            elif not key.startswith(q):
                break
        return exact, prefix

    def search(self, query: str) -> list[NameHit]:
        """`split_search`'s exact matches, then its prefix matches."""
        exact, prefix = self.split_search(query)
        return exact + prefix


class CikLookupClient:
    """The index from SEC's file, cached as `cache_dir/cik-lookup-data.txt` and
    fetched again once it is `CIK_LOOKUP_MAX_AGE_DAYS` old, through `sec_http`
    (the one SEC throttle, User-Agent and retries; `EdgarBlocked` on 403/429; a
    failed refetch serves the old copy, counted as degraded). Built once, on the
    first `index()`."""

    def __init__(self, cache_dir: str | Path, *, session=None, user_agent: str | None = None,
                 sleep=time.sleep) -> None:
        self.path = Path(cache_dir) / "cik-lookup-data.txt"
        self.session, self.user_agent, self.sleep = session, user_agent, sleep
        self._index: CikNameIndex | None = None
        self._lock = threading.Lock()         # the warm pass's resolvers share one client

    def index(self) -> CikNameIndex:
        with self._lock:
            if self._index is None:
                text = get_text(CIK_LOOKUP_URL, self.path, max_age_days=CIK_LOOKUP_MAX_AGE_DAYS,
                                session=self.session, user_agent=self.user_agent, sleep=self.sleep)
                self._index = CikNameIndex.from_text(text)
            return self._index

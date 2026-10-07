"""The run's issuer record: what EDGAR records of each issuer, read once, through one failure policy (architecture
step 2).

An issuer's EDGAR record is its submissions JSON (its names over time, its tickers, its latest filings) and its
filing list (every filing, the paginated history included). The ticker resolver, the classifier's name check and the
pipeline's stages all read issuers through one `IssuerRecord`, and ask it what those answer:

- `names(cik)`: every name EDGAR records for the issuer, current then former;
- `names_near(cik, day)`, `names_between(cik, lo, hi)`, `names_until(cik, day)`: the names it carried within 30
  days of a day, at some point in a window, and on or before a day (`evidence.names_near`, `names_between`,
  `names_until`);
- `first_filed(cik)` and `existed_by(cik, day)`: its first filing, and whether it had filed by a day;
- `recent_form_dates(cik, form)`: the days of its latest filings (the submissions JSON's recent block) of a form;
- `submissions(cik)`, `filings(cik)` and `text(cik, filing)`: the raw reads, for the readers that need more;
- `exact_holders(name)`: the CIKs SEC's name index (cik-lookup-data.txt) lists under exactly a name.

The failure policy, the same for every reader:

- a read that fails after the client's retries (`requests.RequestException`) is unknown: None, [], (), "" or False.
  It is never remembered, so the next ask reads again;
- a refusal (`fatal.FATAL`) stops the run, and any other exception is a bug that propagates;
- a read that failed, that was answered from a stale copy (the client's refresh failed, `edgar.STALE_KEY`), or that
  counted itself degraded on its thread (`sec_stats.SEC_STATS.thread_degraded`) records its CIK as degraded. A
  `ReadWatch` (`watch()`) tells a reader which CIKs the answers it made since rested on such a read (`ciks`; `failed`:
  those with no answer at all), and whether any other SEC read on its thread was degraded too (`tripped()`), for the
  `resolution_degraded` review rows.

Freshness: `about` (the day of the event a reader asks about) asks for a copy fetched by
`edgar.submissions_fresh_after(about, today)`, as the resolver and the classifier read an issuer around an event. A
remembered copy fetched by then answers without a read; an older one is read again, and the client refreshes it.
Without `about`, any copy answers. Only a current copy is remembered (a stale or degraded one is used and read again
next time), and every refresh the run makes goes through here, so a remembered copy is the client's cached one.

Memory: at most `MEMO_SIZE` submissions copies and as many filing lists are remembered, the least recently asked
dropped first (asked again, they are read from the client's disk cache); every issuer's first filing is kept. The
record forgets everything when a run starts (`forget`).

Threads: the run's record serves the sequential pass on one thread. A warm pass reads through a `shadow()`, which
starts from a snapshot of what is remembered and keeps what it reads to itself; the degraded log is per thread."""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

import requests

from .edgar import FETCHED_KEY, STALE_KEY, EdgarSubmission, submissions_fresh_after
from .evidence import edgar_names, first_filing, names_between, names_near, names_until, parse_day
from .fatal import FATAL
from .sec_stats import SEC_STATS

if TYPE_CHECKING:
    from .cik_lookup import CikNameIndex

log = logging.getLogger(__name__)

MEMO_SIZE = 512        # submissions copies (and filing lists) remembered at once


class _Log(threading.local):
    """Per thread: (CIK, answered) for every degraded read, in order."""

    def __init__(self) -> None:
        self.entries: list[tuple[int, bool]] = []


class ReadWatch:
    """What the answers made on this thread since the watch began rested on (`IssuerRecord.watch`)."""

    def __init__(self, entries: list[tuple[int, bool]]) -> None:
        self._entries, self._start = entries, len(entries)
        self._sec_mark = SEC_STATS.thread_degraded()

    @property
    def ciks(self) -> frozenset[int]:
        """The CIKs one of whose reads failed or was answered from a stale or degraded copy."""
        return frozenset(cik for cik, _ in self._entries[self._start:])

    @property
    def failed(self) -> frozenset[int]:
        """The CIKs one of whose reads failed outright: no answer."""
        return frozenset(cik for cik, answered in self._entries[self._start:] if not answered)

    def tripped(self) -> bool:
        """Whether an answer made since rested on a failed or stale read: an issuer read (`ciks`), or any other SEC
        read on this thread that counted itself degraded (a full-text search, a filing text)."""
        return bool(self.ciks) or SEC_STATS.thread_degraded() > self._sec_mark


class IssuerRecord:
    """The run's issuer record over an EDGAR client (see the module docstring). `today` bounds the freshness `about`
    asks for (None: the clock); `name_index` is SEC's cik-lookup-data.txt as a `cik_lookup.CikNameIndex`, or a
    callable that loads one on first use (None: no index)."""

    def __init__(self, edgar: Any, *, today: date | None = None,
                 name_index: "CikNameIndex | Callable[[], CikNameIndex] | None" = None) -> None:
        self.edgar, self.today = edgar, today
        self._index_source = name_index
        self._index: CikNameIndex | None = None if callable(name_index) else name_index
        self._index_failed = False
        self._log = _Log()
        self._subs: OrderedDict[int, dict] = OrderedDict()
        self._filings: OrderedDict[int, list[EdgarSubmission]] = OrderedDict()
        self._first: dict[int, date | None] = {}
        self._stamps: dict[int, Any] = {}     # CIK -> the fetch day of the copy its remembered answers came from

    # --- the failure policy ---------------------------------------------------------------------------------------

    def watch(self) -> ReadWatch:
        """A watch over this thread's reads from now on."""
        return ReadWatch(self._log.entries)

    def _read(self, cik: int, fn: Callable, *args: Any, **kwargs: Any) -> tuple[Any, bool]:
        """`(answer, current)`: `fn(*args, **kwargs)`, or `(None, False)` when it failed. `current`: an answer that
        rested on no failed or stale read, and may be remembered."""
        mark = SEC_STATS.thread_degraded()
        try:
            answer = fn(*args, **kwargs)
        except FATAL:
            raise
        except requests.RequestException:
            self._log.entries.append((cik, False))
            return None, False
        if (isinstance(answer, dict) and answer.get(STALE_KEY)) or SEC_STATS.thread_degraded() > mark:
            self._log.entries.append((cik, True))
            return answer, False
        return answer, True

    # --- the reads ------------------------------------------------------------------------------------------------

    def submissions(self, cik: int, *, about: date | str | None = None) -> dict | None:
        """The issuer's submissions JSON, None when it cannot be read. With `about`, a copy fetched by
        `edgar.submissions_fresh_after(about, today)` (see the module docstring)."""
        cik = int(cik)
        on = about if isinstance(about, date) else parse_day(about)
        fresh = submissions_fresh_after(on, self.today) if on is not None else None
        held = self._subs.get(cik)
        if held is not None and (fresh is None or _fetched(held, fresh)):
            self._subs.move_to_end(cik)
            return held
        if fresh is None:
            sub, current = self._read(cik, self.edgar.submissions, cik)
        else:
            sub, current = self._read(cik, self.edgar.submissions, cik, fresh_after=fresh)
        if current and isinstance(sub, dict):
            self._remember(cik, sub, refreshed=fresh is not None)
        return sub if isinstance(sub, dict) else None

    def _remember(self, cik: int, sub: dict, *, refreshed: bool) -> None:
        """Keep a current copy. A copy a refreshing read returned may be newer than the one the issuer's filing
        list and first filing came from: those are read again when they come from another copy, or from one whose
        fetch day is not known."""
        stamp = sub.get(FETCHED_KEY)
        if refreshed and (stamp is None or self._stamps.get(cik) != stamp):
            self._filings.pop(cik, None)
            self._first.pop(cik, None)
        self._stamps[cik] = stamp
        self._subs[cik] = sub
        self._subs.move_to_end(cik)
        while len(self._subs) > MEMO_SIZE:
            self._subs.popitem(last=False)

    def filings(self, cik: int, *, about: date | str | None = None) -> list[EdgarSubmission]:
        """Every filing of the issuer (`EdgarClient.recent_filings`), [] when they cannot be read. With `about`, the
        submissions copy is made current for that day first, so both are read from one copy."""
        cik = int(cik)
        if about is not None:
            self.submissions(cik, about=about)
        held = self._filings.get(cik)
        if held is not None:
            self._filings.move_to_end(cik)
            return list(held)
        found, current = self._read(cik, self.edgar.recent_filings, cik)
        if found is None:
            return []
        found = list(found)
        if current:
            self._filings[cik] = found
            while len(self._filings) > MEMO_SIZE:
                self._filings.popitem(last=False)
        return list(found)

    def text(self, cik: int, filing: EdgarSubmission) -> str:
        """A filing's text (`EdgarClient.fetch_filing_text`), "" when it cannot be read; never remembered here (the
        client caches it on disk)."""
        found, _ = self._read(int(cik), self.edgar.fetch_filing_text, cik, filing.accession, filing.primary_doc)
        return found or ""

    # --- what they answer -----------------------------------------------------------------------------------------

    def names(self, cik: int, *, about: date | str | None = None) -> tuple[str, ...]:
        """Every name EDGAR records for the issuer, current then former (`evidence.edgar_names`); () when unknown."""
        sub = self.submissions(cik, about=about)
        return edgar_names(sub) if sub is not None else ()

    def names_near(self, cik: int, day: date, *, about: date | str | None = None, days: int = 30) -> list[str]:
        """The names the issuer carried within `days` of `day`, former names first; [] when unknown."""
        sub = self.submissions(cik, about=about)
        return names_near(sub, day, days) if sub is not None else []

    def names_between(self, cik: int, lo: date, hi: date, *, about: date | str | None = None) -> list[str]:
        """The names the issuer carried at some point in [lo, hi], former names first; [] when unknown."""
        sub = self.submissions(cik, about=about)
        return names_between(sub, lo, hi) if sub is not None else []

    def names_until(self, cik: int, day: date, *, about: date | str | None = None) -> list[str]:
        """The names the issuer carried on or before `day`, former names first; [] when unknown."""
        sub = self.submissions(cik, about=about)
        return names_until(sub, day) if sub is not None else []

    def first_filed(self, cik: int) -> date | None:
        """The issuer's first EDGAR filing; None for none, or when its filings cannot be read (never remembered)."""
        cik = int(cik)
        if cik not in self._first:
            watch = self.watch()
            first = first_filing(self.filings(cik))
            if watch.ciks:
                return None if cik in watch.failed else first
            self._first[cik] = first
        return self._first[cik]

    def existed_by(self, cik: int, day: date | str | None) -> bool:
        """Whether the issuer had filed by `day` (True without a day; False when its filings cannot be read)."""
        if day is None:
            return True
        on = day if isinstance(day, date) else parse_day(day)
        first = self.first_filed(cik)
        return first is not None and on is not None and first <= on

    def recent_form_dates(self, cik: int, form: str, *, about: date | str | None = None) -> list[date]:
        """The days of the issuer's latest filings (its submissions JSON's recent block: a delisted company's Form 25
        or 15 is among its last) whose form starts with `form`; [] when unknown."""
        sub = self.submissions(cik, about=about)
        recent = ((sub.get("filings") or {}).get("recent") or {}) if sub is not None else {}
        return [d for f, fd in zip(recent.get("form") or [], recent.get("filingDate") or [])
                if f.startswith(form) and (d := parse_day(fd)) is not None]

    # --- SEC's name index -----------------------------------------------------------------------------------------

    def name_index(self) -> "CikNameIndex | None":
        """SEC's name index, loaded on first use; None without one, or when it cannot be loaded (logged once: the
        resolver's live company search stands in for it). A refusal (`fatal.FATAL`) stops the run."""
        if self._index is None and self._index_source is not None and not self._index_failed:
            try:
                self._index = self._index_source()
            except FATAL:
                raise
            except requests.RequestException as exc:
                log.warning("SEC's cik-lookup-data.txt could not be loaded (%s); using the live company search", exc)
                self._index_failed = True
        return self._index

    def exact_holders(self, name: str) -> list[int]:
        """The CIKs SEC's name index lists under exactly `name`; none without an index."""
        index = self.name_index()
        return [h.cik for h in index.split_search(name)[0]] if index is not None else []

    # --- runs and threads -----------------------------------------------------------------------------------------

    def forget(self) -> None:
        """Drop everything remembered (a run starts here): the next ask of each issuer reads the client again."""
        self._subs.clear()
        self._filings.clear()
        self._first.clear()
        self._stamps.clear()

    def shadow(self) -> "IssuerRecord":
        """A record for a warm pass's worker: the same client, run date and name index, a snapshot of what is
        remembered, and its own memory and degraded log. Make it on the thread that owns this record, while that
        record is idle (`prefetch.warm` calls its state factory there)."""
        s = IssuerRecord(self.edgar, today=self.today, name_index=self._index or self._index_source)
        s._index_failed = self._index_failed
        s._subs, s._filings = OrderedDict(self._subs), OrderedDict(self._filings)
        s._first, s._stamps = dict(self._first), dict(self._stamps)
        return s


def _fetched(sub: dict, fresh: date) -> bool:
    """Whether the copy was fetched on or after `fresh` (a copy that does not say when is read again)."""
    stamp = sub.get(FETCHED_KEY)
    try:
        return stamp is not None and date.fromisoformat(stamp) >= fresh
    except (TypeError, ValueError):
        return False

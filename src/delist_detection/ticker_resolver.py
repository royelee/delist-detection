"""Resolve a (ticker, as_of_date) pair to a CIK.

SEC's company_tickers.json only lists *currently* registered tickers, so it
misses anything already deregistered. For those we fall back to EDGAR's
full-text search (efts.sec.gov), which indexes historical filings.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import requests

from .atomic_io import clean_orphan_temps, write_atomic
from .edgar import STALE_KEY, EdgarClient, submissions_fresh_after
from .evidence import edgar_names, first_filing, names_near, parse_day
from .fatal import FATAL
from .names import name_tokens, names_agree

log = logging.getLogger(__name__)
_LOOK_UP_PIN = object()     # resolve(pin=...) default: look the pin up with cik_pins
_LOOK_UP_NAME = object()    # resolve(name=...) default: look the name up with observed_names
# The cache file is {"__version__": N, "entries": {key: {...TickerResolution,
# "member_name"}}} ("member_name": the observed name the answer was checked with,
# under its on-disk key). Version 4 keys an entry `TICKER|date|member name`
# (`TickerResolver._key`); versions 2 and 3 keyed it `TICKER|date` and load
# re-keyed from their member_name. Anything older was written before the date and
# name checks and is not trusted. Version 3 was written while a since-withdrawn
# rule let today's ticker-map holder beat a name-mismatched EFTS candidate; its
# answers (source company_tickers_name_mismatch) are dropped on load and resolved
# again.
CACHE_VERSION = 4
_LOADABLE_VERSIONS = frozenset({2, 3, 4})
_RETIRED_SOURCES = frozenset({"company_tickers_name_mismatch"})
# Version 4's name search ranks its candidates by their EDGAR names and never
# takes a nameless multi-company hit. With this switch on, a version-2/3 file's
# name_search answers (written under the old rule) are dropped on load and
# resolved again, so a warm cache gives what a cold run gives.
RETIRE_OLD_NAME_SEARCH = False


@dataclass
class TickerResolution:
    ticker: str
    cik: int | None
    name: str | None
    # 'cik_map' | 'manual' | 'rename' | 'company_tickers' | 'efts' | 'efts_name_mismatch'
    # | 'name_search' | 'efts_frequency' | 'efts_frequency_name_mismatch'
    # | 'rejected_validation' | 'none'
    source: str


class TickerResolver:
    def __init__(
        self,
        edgar: EdgarClient,
        rename_map: dict[str, str] | None = None,
        manual_overrides: dict[str, int] | None = None,
        cache_path: Path | str | None = None,
        name_lookup: "callable[..., str | None] | None" = None,
        *,
        observed_names: "callable[..., str | None] | None" = None,
        cik_pins: "callable[[str, str | None], int | None] | None" = None,
        today: date | None = None,
        batch_writes: bool = False,
        retire_old_name_search: bool | None = None,
    ) -> None:
        """`today`: the run date bounding submissions freshness (None: the clock).
        `batch_writes`: keep new answers in memory until `flush()` (the pipeline
        flushes after each resolving stage and on the way out of a run) instead
        of rewriting the whole memo file for each one. `retire_old_name_search`:
        drop a version-2/3 memo file's name_search answers on load (None: the
        module's `RETIRE_OLD_NAME_SEARCH`)."""
        self.retire_old_name_search = (RETIRE_OLD_NAME_SEARCH if retire_old_name_search is None
                                       else retire_old_name_search)
        self.edgar = edgar
        self.rename_map = {k.upper(): v.upper() for k, v in (rename_map or {}).items()}
        self.manual_overrides = {k.upper(): int(v) for k, v in (manual_overrides or {}).items()}
        self.cache_path = Path(cache_path) if cache_path else None
        self.name_lookup = name_lookup or (lambda *a, **kw: None)
        self.observed_names = observed_names or (lambda *a, **kw: None)  # (ticker, date) -> the observation's name
        self.cik_pins = cik_pins or (lambda *a, **kw: None)  # (ticker, date) -> CIK from the caller's universe
        self.today = today
        self.batch_writes = batch_writes
        self._memo: dict[str, TickerResolution] = {}
        self._memo_observed: dict[str, str | None] = {}   # key -> observed name the answer was checked with
        self._volatile: set[str] = set()   # misses and transient-error answers: this run only
        self._degraded: set[str] = set()   # keys whose answer rests on a failed request or a stale copy
        self._dirty = False                # an answer was added since the memo file was last written
        self._transient = False            # a check in the current resolve() hit a transient error
        if self.cache_path:
            clean_orphan_temps(self.cache_path.parent)
        if self.cache_path and self.cache_path.exists():
            self._load_cache()
        self._companies: dict[str, dict] | None = None

    def _load_cache(self) -> None:
        try:
            raw = json.loads(self.cache_path.read_text())
        except json.JSONDecodeError:
            raw = None
        version = raw.get("__version__") if isinstance(raw, dict) else None
        if version not in _LOADABLE_VERSIONS:
            log.warning("%s is not a version-%d resolver cache; ignoring it (the next save replaces it)",
                        self.cache_path, CACHE_VERSION)
            return
        for key, d in (raw.get("entries") or {}).items():
            try:
                res = TickerResolution(d["ticker"], d["cik"], d["name"], d["source"])
            except (KeyError, TypeError):
                continue
            if res.cik is None:  # a persisted miss is retried, never trusted
                continue
            if res.source in _RETIRED_SOURCES:   # a withdrawn rule's answer
                continue
            if version < 4:                      # keyed TICKER|date: add the member name
                if self.retire_old_name_search and res.source == "name_search":
                    continue
                key = f"{key}|{d.get('member_name') or ''}"
            self._memo[key] = res
            self._memo_observed[key] = d.get("member_name")

    OBSERVED_ALIVE_DAYS = 400          # filed within ±this of the date: the issuer was operating
    OBSERVED_TAIL_DAYS = 1500          # a Form 25/15 up to this old: a frozen vendor tail (XTO)
    REPLACE_WINDOW_DAYS = 90         # own Form 25/15 this close: a name-search hit replaces an EFTS fallback

    def _observed_name(self, t: str, observed_date: str | None, name: str | None | object = _LOOK_UP_NAME
                       ) -> str | None:
        """The observed name a lookup is checked with: `name` when the caller
        gives one (None: it has none), else the `observed_names` lookup's."""
        if name is _LOOK_UP_NAME:
            return self.observed_names(t, observed_date) or None
        return name or None

    def _expected_name(self, t: str, observed_date: str | None, name: str | None | object = _LOOK_UP_NAME
                       ) -> str | None:
        """The observed name (`_observed_name`), else the AV name: the first
        with a usable word.

        A name with no `name_tokens` word ("AT&T INC.", "3M CO", "HP INC")
        cannot agree with anything, so it counts as no expected name."""
        for n in (self._observed_name(t, observed_date, name), self.name_lookup(t, observed_date)):
            if n and name_tokens(n):
                return n
        return None

    @staticmethod
    def _key(ticker: str, observed_date: str | None, observed_name: str | None) -> str:
        """The memo key: an answer holds for one ticker, date and observed name."""
        return f"{ticker.upper().strip()}|{observed_date or ''}|{observed_name or ''}"

    def _submissions(self, cik: int, observed_date: str | None) -> dict:
        """The company's submissions, fetched again when the cached copy predates
        the event window (the same freshness the classifier asks for). An older
        copy served because that refetch failed is used, but marks this resolve
        transient: what it leads to is not saved."""
        on = parse_day(observed_date)
        if on is None:
            sub = self.edgar.submissions(cik)
        else:
            sub = self.edgar.submissions(cik, fresh_after=submissions_fresh_after(on, self.today))
        if isinstance(sub, dict) and sub.get(STALE_KEY):
            self._transient = True
        return sub

    def _filings(self, cik: int, observed_date: str | None) -> list:
        """recent_filings, read after a fresh submissions read so both see one copy."""
        self._submissions(cik, observed_date)
        return self.edgar.recent_filings(cik)

    def _fits_date(self, cik: int, observed_date: str | None, expected: str | None) -> tuple[bool, bool]:
        """(existed on the date, a name it carried within ±30 days agrees with `expected`).

        A CIK first seen after the delist date is today's holder of a recycled
        ticker (CPWR -> Ocean Thermal, SPWR -> Complete Solaria/SunPower Inc.)."""
        on = parse_day(observed_date)
        if on is None:
            return True, True
        try:
            sub = self._submissions(cik, observed_date)
            filings = self.edgar.recent_filings(cik)
        except FATAL:
            raise
        except Exception as e:
            self._note_transient(e)
            return False, False
        first = first_filing(filings)
        existed = first is not None and first <= on
        agrees = expected is None or (isinstance(sub, dict) and
                                      any(names_agree(n, expected) for n in names_near(sub, on)))
        return existed, agrees

    def _accept_observed_name_candidate(self, cik: int, observed_date: str | None, expected: str) -> bool:
        """Accept a name-search hit found through an observed name.

        A rename files no Form 25 (HYH -> Avanos), and a frozen vendor tail can
        outlast the 540-day window (XTO), so the loose check alone rejects true
        matches. Without that check, the company must have existed on the date,
        carried an agreeing name then, and either been filing within ±400 days
        or filed a Form 25/15 in the 1,500 days before the date. The last two
        conditions keep out a long-dead issuer (ImClone for a 2018 date)."""
        if not observed_date or self._validate_cik(cik, observed_date, strict=False):
            return True
        existed, agrees = self._fits_date(cik, observed_date, expected)
        if not (existed and agrees):
            return False
        on = parse_day(observed_date)
        for f in self._filings(cik, observed_date):
            d = parse_day(f.filing_date)
            if d is None:
                continue
            if abs((d - on).days) <= self.OBSERVED_ALIVE_DAYS:
                return True
            if f.form in {"25", "25-NSE", "15-12G", "15-12B", "15-15D"} and \
                    on - timedelta(days=self.OBSERVED_TAIL_DAYS) <= d <= on + timedelta(days=45):
                return True
        return False

    def _ensure_companies(self) -> dict[str, dict]:
        if self._companies is None:
            self._companies = self.edgar.company_tickers()
        return self._companies

    def _note_transient(self, exc: Exception) -> None:
        """A failed request is not evidence against a candidate: the answer this
        resolve() reaches is used for the run but not saved."""
        if isinstance(exc, requests.RequestException):
            self._transient = True

    def _remember(self, key: str, res: TickerResolution, observed_name: str | None) -> None:
        # A miss or a transient answer is marked volatile (never persisted) before
        # it enters the memo, and a mark is cleared only after a saveable answer
        # has replaced the entry: an interrupt between these lines leaves nothing
        # that the flush on the way out of the run would save wrongly.
        volatile = res.cik is None or self._transient   # retried next run, never persisted
        if self._transient:
            self._degraded.add(key)
        if volatile:
            self._volatile.add(key)
        self._memo[key] = res
        self._memo_observed[key] = observed_name
        if not self._transient:
            self._degraded.discard(key)
        if volatile:
            return
        self._volatile.discard(key)
        self._dirty = True
        if not self.batch_writes:
            self.flush()

    def flush(self) -> None:
        """Write the memo file if an answer was added since it was last written
        (atomically: a crash never leaves a torn memo)."""
        if not self._dirty or not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        entries = {k: {**r.__dict__, "member_name": self._memo_observed.get(k)}
                   for k, r in self._memo.items() if k not in self._volatile}
        write_atomic(self.cache_path, json.dumps({"__version__": CACHE_VERSION, "entries": entries}, indent=2))
        self._dirty = False

    def is_degraded(self, ticker: str, observed_date: str | None = None, *,
                    name: str | None | object = _LOOK_UP_NAME) -> bool:
        """Whether this run's answer for (ticker, date, observed name: as
        `resolve` takes it) rests on a failed EDGAR request or a stale copy. Such
        an answer is used for the run and never saved; the pipeline flags it
        `resolution_degraded`."""
        t = ticker.upper().strip()
        return self._key(t, observed_date, self._observed_name(t, observed_date, name)) in self._degraded

    # CIKs of US exchanges — these file Form 25-NSEs *on behalf of* the issuer,
    # so they appear in every delisting filing's CIK array. Always skip them.
    # Each entry was checked against EDGAR on 2026-09-17 (names as EDGAR gives
    # them); an unchecked CIK here hides a real company (1283699 is T-Mobile US).
    # The set was also checked against the Form 25-NSE filer list: sampling 2018,
    # 2021 and 2024 turns up only Nasdaq, NYSE, NYSE American, NYSE Arca and Cboe
    # BZX, and EDGAR company search finds no 25 filer for IEX, Cboe EDGA, MEMX,
    # MIAX Pearl or LTSE — so none of those is missing here.
    EXCHANGE_CIKS: set[int] = {
        1354457,   # Nasdaq Stock Market LLC
        876661,    # New York Stock Exchange LLC
        1143362,   # NYSE Arca, Inc.
        1143313,   # NYSE American LLC
        876882,    # NYSE Texas, Inc. (formerly NYSE Chicago / Chicago Stock Exchange)
        1131740,   # NYSE National, Inc.
        1417835,   # Cboe BZX Exchange, Inc.
        876663,    # Cboe Exchange, Inc.
        1473845,   # Cboe EDGX Exchange, Inc.
        876798,    # Nasdaq PHLX LLC
        876796,    # Nasdaq Texas, LLC (formerly Nasdaq BX)
        1296945,   # Boston Stock Exchange Inc.
    }

    def _efts_hits(self, url: str, window_end: date | None) -> list[dict]:
        """EFTS `hits.hits` for one of this resolver's queries, sent through the
        EDGAR client: the shared rate limit, the User-Agent, and the cache
        (`EdgarClient.efts_search`). Raises requests.RequestException when EDGAR
        could not answer; the callers then mark this resolve transient."""
        return self.edgar.efts_search(url, window_end=window_end)

    def _efts_pre_delist_frequency_ranked(
        self, ticker: str, observed_date: str, top_n: int = 5
    ) -> list[tuple[int, str]]:
        """Frequency-rank CIKs filing 8-Ks in the 90 days before the delist.

        Useful when Form 25 doesn't contain the ticker text. A target company
        usually files many 8-Ks (and a definitive proxy) in the months leading
        up to its acquisition. The acquirer also files some, but the target
        normally outnumbers it in 8-Ks where the ticker is mentioned.
        """
        try:
            d = datetime.strptime(observed_date, "%Y-%m-%d").date()
        except ValueError:
            return []
        lo = (d - timedelta(days=120)).isoformat()
        hi = (d - timedelta(days=1)).isoformat()
        url = (
            "https://efts.sec.gov/LATEST/search-index"
            f"?q=%22{ticker}%22&forms=8-K"
            f"&dateRange=custom&startdt={lo}&enddt={hi}"
        )
        try:
            hits = self._efts_hits(url, d - timedelta(days=1))
        except requests.RequestException as e:
            self._note_transient(e)
            return []
        counts: dict[int, tuple[int, str]] = {}
        token_re = re.compile(rf"\(\s*{re.escape(ticker.upper())}\s*\)")
        for h in hits:
            src = h.get("_source", {})
            ciks = src.get("ciks") or []
            names = src.get("display_names") or []
            for nm, cik in zip(names, ciks):
                c = int(cik)
                if c in self.EXCHANGE_CIKS:
                    continue
                weight = 3 if token_re.search(nm.upper()) else 1
                cur_count, cur_name = counts.get(c, (0, nm))
                counts[c] = (cur_count + weight, cur_name)
        if not counts:
            return []
        ranked = sorted(counts.items(), key=lambda kv: -kv[1][0])[:top_n]
        return [(c, nm) for c, (_, nm) in ranked]

    @staticmethod
    def _name_variants(name: str) -> list[str]:
        """Generate likely EDGAR-equivalent company-name search variants.

        EDGAR's `cgi-bin/browse-edgar?company=` does prefix-style matching, so
        a name like 'MERRILL LYNCH CO INC' must be queried as just
        'MERRILL LYNCH' to match the registered name 'MERRILL LYNCH & CO INC'.
        We try the full name, several stripped versions, and the leading two
        meaningful tokens.
        """
        if not name:
            return []
        n = name.strip()
        # Normalize punctuation
        cleaned = re.sub(r"[.,'’]", "", n).strip()
        no_amp = cleaned.replace("&", " ").strip()
        no_amp = re.sub(r"\s+", " ", no_amp)
        variants: list[str] = []
        seen: set[str] = set()

        def add(v: str) -> None:
            v = v.strip()
            if v and v.upper() not in seen:
                seen.add(v.upper())
                variants.append(v)

        add(n)
        add(cleaned)
        add(no_amp)
        # Strip trailing suffixes
        suffix_re = re.compile(
            r"\s+(INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|HOLDINGS|"
            r"GROUP|INTERNATIONAL|TRUST|LLC|LP|LLP|HOLDING|HOLDINGS)\.?\s*$",
            re.IGNORECASE,
        )
        cur = no_amp
        for _ in range(3):
            new = suffix_re.sub("", cur).strip()
            if new == cur:
                break
            add(new)
            cur = new
        # Take leading 1-3 tokens, alphabetic only — but skip very-common
        # first tokens that would over-match (THE, NEW, FIRST, etc.).
        tokens = [tok for tok in re.split(r"[\s\-/]+", no_amp)
                  if re.match(r"^[A-Za-z][A-Za-z0-9'’]*$", tok)]
        SHORT_GENERICS = {"THE", "NEW", "FIRST", "SECOND", "GENERAL", "AMERICAN",
                          "NATIONAL", "INTERNATIONAL", "WORLD", "UNITED",
                          "BANK", "TRUST"}
        if len(tokens) >= 2:
            add(" ".join(tokens[:2]))
        if len(tokens) >= 3:
            add(" ".join(tokens[:3]))
        if tokens and len(tokens[0]) >= 5 and tokens[0].upper() not in SHORT_GENERICS:
            add(tokens[0])
        return variants

    NAME_SEARCH_CANDIDATES = 5       # distinct CIKs the name search ranks and checks

    def _name_search(self, ticker: str, observed_date: str | None, nm: str | None) -> list[tuple[int, str]]:
        """Candidates for the expected name `nm` (observed, else AV) from EDGAR's
        company search, best first, as (CIK, the name the search gave).

        Every name variant is searched (one form class per variant). A hit with
        no name is no candidate: EDGAR answers a query that matches several
        companies with a list and no conformed name, and the CIK read from it is
        the list's first, whichever company that is (MICHAEL -> Michael Baker,
        searching for MICHAEL KORS HOLDINGS LTD). The first
        `NAME_SEARCH_CANDIDATES` distinct CIKs found are ranked by the number of
        `name_tokens` words `nm` shares with any of the CIK's EDGAR names,
        current and former (`_edgar_name_fit`: the search matches a former
        name, so MICHAEL KORS HOLDINGS LTD finds Capri Holdings), then by the gap
        between the date and the nearest filing the search listed for it. The
        first is always a candidate; one ranked below it only when one of its
        EDGAR names `names_agree`s with `nm`."""
        if not nm:
            return []
        target_d = parse_day(observed_date)
        found: dict[int, tuple[str, int]] = {}      # CIK -> (its hit name, date penalty), in the order found
        for variant in self._name_variants(nm):
            for form in ("25-NSE", "25", "15-12G", ""):
                try:
                    hits = self.edgar.company_search_atom(variant, form_type=form)
                except FATAL:
                    raise
                except Exception as e:
                    self._note_transient(e)
                    hits = []
                if any(isinstance(h, dict) and h.get(STALE_KEY) for h in hits):
                    self._transient = True       # a hit served after a failed refetch: never saved
                for h in hits:
                    cik, hit_name = int(h["cik"]), h.get("name")
                    if not hit_name or cik in self.EXCHANGE_CIKS:
                        continue
                    filed = parse_day(h.get("filing_date"))
                    penalty = min(abs((filed - target_d).days), 9999) if filed and target_d else 1000
                    if cik in found:
                        found[cik] = (found[cik][0], min(found[cik][1], penalty))
                    elif len(found) < self.NAME_SEARCH_CANDIDATES:
                        found[cik] = (hit_name, penalty)
                if hits:
                    break  # one form-class per variant is enough
        order = list(found)
        fit = {c: self._edgar_name_fit(c, nm, observed_date) for c in order}
        ranked = sorted(order, key=lambda c: (-fit[c][0], found[c][1], order.index(c)))
        # The best candidate is checked as it always was; one below it only when
        # EDGAR records a name for it that agrees with `nm`: Keurig Green Mountain
        # shares KEURIG with KEURIG DR PEPPER INC, and its 2016 Form 25 alone
        # passes the loose check.
        kept = ranked[:1] + [c for c in ranked[1:] if fit[c][1]]
        return [(c, found[c][0]) for c in kept]

    def _edgar_name_fit(self, cik: int, expected: str, observed_date: str | None = None) -> tuple[int, bool]:
        """How the CIK's EDGAR names (current and former) fit the expected name:
        the number of `names.name_tokens` words they share with it, and whether
        one of them `names_agree`s with it. (0, False) when EDGAR cannot answer
        (the resolve is then marked transient)."""
        try:
            sub = self._submissions(cik, observed_date)
        except FATAL:
            raise
        except Exception as e:
            self._note_transient(e)
            return 0, False
        if not isinstance(sub, dict):
            return 0, False
        names = edgar_names(sub)
        candidate_tokens: set[str] = set()
        for n in names:
            candidate_tokens |= name_tokens(n)
        return len(candidate_tokens & name_tokens(expected)), any(names_agree(n, expected) for n in names)

    def _name_match_score(self, cik: int, ticker_name: str, observed_date: str | None = None) -> int:
        """Token-overlap score between the expected name and the CIK's EDGAR names
        (`_edgar_name_fit`'s count). Used to rank frequency candidates; a
        zero-score winner is kept but marked as a name mismatch by the caller
        (impostor vendor series).
        """
        return self._edgar_name_fit(cik, ticker_name, observed_date)[0]

    def _validate_cik(self, cik: int, observed_date: str, strict: bool = True,
                      window: int = 540) -> bool:
        """Confirm the candidate CIK matches a target-of-delisting profile.

        Loose mode: just need a Form 25 or Form 15 within ±window days of delist.
        Strict mode: additionally requires NO 10-K / 10-Q / 20-F filed in the
            window [observed+90, observed+5y]. The strict check rejects the
            *acquirer* (who keeps filing) when the candidate came from a
            frequency rank. It's too aggressive for true targets that keep
            filing because of leftover registered debt (Merrill post-BofA).
        """
        try:
            d = datetime.strptime(observed_date, "%Y-%m-%d").date()
        except ValueError:
            return True
        try:
            subs = self._filings(cik, observed_date)
        except FATAL:
            raise
        except Exception as e:
            self._note_transient(e)
            return False

        has_delist_form = False
        no_post_cutoff = d + timedelta(days=90)
        post_horizon = d + timedelta(days=365 * 5)
        for f in subs:
            try:
                fd = datetime.strptime(f.filing_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if f.form in {"25", "25-NSE", "15-12G", "15-12B", "15-15D"}:
                if abs((fd - d).days) <= window:
                    has_delist_form = True
            if strict and f.form in {"10-K", "10-Q", "20-F", "40-F"}:
                if no_post_cutoff < fd < post_horizon:
                    return False
        return has_delist_form

    def _efts_lookup(
        self, ticker: str, observed_date: str | None = None, *, expected_name: str | None = None
    ) -> tuple[int | None, str | None, bool]:
        """EDGAR full-text search fallback, anchored on the delisting filings.

        Strategy: search for the ticker only within Form 25 / 25-NSE / 15-*
        filings in a ±90 day window around the observed delist date, and
        accept the match only when the *exact* ticker token appears in the
        display_name (e.g. as ``(ACME)``) — never substring-match a longer
        word like ``ACMECORP`` against ``ACME``.

        When ``observed_date`` is None we still issue a delist-form-only
        query without a date range, which is far less ambiguous than the
        original 8-K-included query.

        Returns ``(cik, name, fallback)``. ``fallback`` is True for a
        second-pass candidate whose name disagrees with ``expected_name``:
        an issuer that filed a delisting form in the window under another
        name, which the caller keeps unless the observed name finds an issuer
        with its own delisting form near the date.
        """
        ticker_u = ticker.upper()
        forms = "25-NSE,25,15-12G,15-12B,15-15D"
        params = [f"q=%22{ticker_u}%22", f"forms={forms}"]
        window_end: date | None = None
        if observed_date:
            try:
                d = datetime.strptime(observed_date, "%Y-%m-%d").date()
                lo = (d - timedelta(days=90)).isoformat()
                hi = (d + timedelta(days=90)).isoformat()
                params += [f"dateRange=custom", f"startdt={lo}", f"enddt={hi}"]
                window_end = d + timedelta(days=90)
            except ValueError:
                pass
        url = "https://efts.sec.gov/LATEST/search-index?" + "&".join(params)
        try:
            hits = self._efts_hits(url, window_end)
        except requests.RequestException as e:
            self._note_transient(e)          # EDGAR did not answer: never save what this resolve reaches
            return None, None, False
        token_re = re.compile(rf"\(\s*{re.escape(ticker_u)}\s*\)")

        # First pass: exact (TICKER) match anywhere in display_names.
        for h in hits:
            src = h.get("_source", {})
            ciks = src.get("ciks") or []
            names = src.get("display_names") or []
            for nm, cik in zip(names, ciks):
                if token_re.search(nm.upper()) and int(cik) not in self.EXCHANGE_CIKS:
                    return int(cik), nm, False

        # Second pass: only safe when we narrowed by date AND restricted to
        # delisting forms — then take the first non-exchange CIK whose name
        # agrees with the expected name. The first non-exchange CIK is often
        # an unrelated filer in the window (PEAK -> Far Peak, WE -> Adastra),
        # but it can also be the company that really delisted under another
        # name (BWC -> Blue Whale), so it comes back as a fallback. With no
        # expected name the pass is skipped.
        if observed_date and expected_name:
            fallback: tuple[int, str] | None = None
            for h in hits:
                src = h.get("_source", {})
                ciks = src.get("ciks") or []
                names = src.get("display_names") or []
                for nm, cik in zip(names, ciks):
                    c = int(cik)
                    if c in self.EXCHANGE_CIKS:
                        continue
                    if names_agree(nm, expected_name):
                        return c, nm, False
                    if fallback is None:
                        fallback = (c, nm)
            if fallback is not None:
                return fallback[0], fallback[1], True
        return None, None, False

    def resolve(self, ticker: str, observed_date: str | None = None, *,
                pin: int | None | object = _LOOK_UP_PIN,
                name: str | None | object = _LOOK_UP_NAME) -> TickerResolution:
        """`pin`: the caller's own CIK pin for this lookup (None: none), in place of
        `cik_pins(ticker, observed_date)`. `name`: the observed name to check the
        answer with (None: none), in place of `observed_names(ticker,
        observed_date)`. A caller resolving a known era passes its own pin and
        name: a date lookup can land nearer another era of the ticker than the
        era's own observations (its FTD rows run past its last observation) and
        return that era's pin or name. The answer is remembered under the ticker,
        the date and the observed name its checks used."""
        t = ticker.upper().strip()
        observed_name = self._observed_name(t, observed_date, name)
        cache_key = self._key(t, observed_date, observed_name)
        self._transient = False

        pinned = self.cik_pins(t, observed_date) if pin is _LOOK_UP_PIN else pin
        if pinned:
            # The caller's universe states which issuer this row is: it was
            # resolved once, against the observed name, and reviewed. Nothing this
            # resolver can derive from a symbol beats that. This tier answers
            # before the memo read below, so persisting it buys nothing — and
            # would let a stale pin survive an operator dropping the identity
            # pin from the observations file to see what the library resolves
            # on its own, or a ticker later corrected there. Never written to
            # the on-disk cache.
            return TickerResolution(ticker=t, cik=int(pinned), name=None, source="cik_map")

        # Manual overrides always beat the cache — they're the truth.
        if t in self.manual_overrides:
            res = TickerResolution(ticker=t, cik=self.manual_overrides[t], name=None, source="manual")
            self._remember(cache_key, res, observed_name)
            return res

        if cache_key in self._memo and self._memo_observed.get(cache_key) == observed_name:
            # A rename built on this answer inherits whether it rests on a failed request.
            self._transient = cache_key in self._degraded
            return self._memo[cache_key]

        renamed = self.rename_map.get(t)
        if renamed and renamed != t:
            inner = self.resolve(renamed, observed_date)   # leaves self._transient set for this answer
            res = TickerResolution(ticker=t, cik=inner.cik, name=inner.name, source="rename")
            self._remember(cache_key, res, observed_name)
            return res

        expected = self._expected_name(t, observed_date, observed_name)
        companies = self._ensure_companies()
        if t in companies:
            # SEC's map lists today's holder of the ticker: accept it only if
            # that issuer existed on the date under an agreeing name.
            row = companies[t]
            c = int(row["cik_str"])
            if self._fits_date(c, observed_date, expected) == (True, True):
                res = TickerResolution(
                    ticker=t,
                    cik=c,
                    name=row.get("title"),
                    source="company_tickers",
                )
                self._remember(cache_key, res, observed_name)
                return res

        cik: int | None = None
        name: str | None = None
        source = "none"

        # Tier 1: EFTS Form 25 + date — most precise when it returns a hit.
        # Use loose validation: a name in EFTS Form-25 results is already
        # tightly date-anchored. The company must have existed on the date;
        # a name that disagrees with the expected one is kept (the row
        # describes the company that delisted) and marked as a mismatch.
        # A second-pass hit under another name is held back as a fallback.
        c0, n0, weak = self._efts_lookup(t, observed_date, expected_name=expected)
        fallback: tuple[int, str | None] | None = None
        if c0 is not None:
            if not observed_date or self._validate_cik(c0, observed_date, strict=False):
                existed, agrees = self._fits_date(c0, observed_date, expected)
                if existed and weak:
                    fallback = (c0, n0)
                elif existed:
                    cik, name = c0, n0
                    source = "efts" if agrees else "efts_name_mismatch"

        # Tier 2: expected name → EDGAR company-name search, its candidates
        # checked best first.
        if cik is None:
            ranked = self._name_search(t, observed_date, expected)
            if fallback is not None:
                # The observed name is a check, never a substitute: it replaces
                # the company EFTS found only with its own Form 25/15 near the
                # date (PEAK -> Healthpeak, WE -> WeWork), not with a live
                # issuer of that name (BWC keeps Blue Whale, flagged).
                hit = next(((c, n) for c, n in ranked if self._validate_cik(
                    c, observed_date, strict=False, window=self.REPLACE_WINDOW_DAYS)), None)
                if hit is not None:
                    (cik, name), source = hit, "name_search"
                else:
                    cik, name = fallback
                    source = "efts_name_mismatch"
            else:
                # Loose validation (a real Form 25 in the window), or the
                # observed-name acceptance when the caller supplied a usable
                # observed name.
                if observed_name and name_tokens(observed_name):
                    def ok(c: int) -> bool:
                        return self._accept_observed_name_candidate(c, observed_date, observed_name)
                else:
                    def ok(c: int) -> bool:
                        return not observed_date or self._validate_cik(c, observed_date, strict=False)
                hit = next(((c, n) for c, n in ranked if ok(c)), None)
                if hit is not None:
                    (cik, name), source = hit, "name_search"

        # Tier 3: 8-K frequency rank — strict validation (must reject the
        # acquirer, who keeps filing 10-Qs).
        if cik is None and observed_date:
            ranked = self._efts_pre_delist_frequency_ranked(t, observed_date)
            best: tuple[int, int, int, str] | None = None
            for rank, (cand_cik, cand_name) in enumerate(ranked):
                if not self._validate_cik(cand_cik, observed_date, strict=True):
                    continue
                score = self._name_match_score(cand_cik, expected, observed_date) if expected else 0
                inv_rank = -rank
                cur = (score, inv_rank, cand_cik, cand_name)
                if best is None or cur > best:
                    best = cur
            if best is not None:
                cik, name = best[2], best[3]
                # A zero-score winner is an impostor vendor series (HMA, HLTH).
                source = "efts_frequency_name_mismatch" if expected and best[0] == 0 else "efts_frequency"
            elif ranked:
                source = "rejected_validation"

        res = TickerResolution(ticker=t, cik=cik, name=name, source=source)
        self._remember(cache_key, res, observed_name)
        return res

    def resolve_many(
        self, items: Iterable[tuple[str, str | None]]
    ) -> dict[str, TickerResolution]:
        return {t: self.resolve(t, d) for t, d in items}

    def shadow(self) -> "TickerResolver":
        """A copy for warming the EDGAR caches on another thread: the same EDGAR
        client, overrides, name callables and run date, and a snapshot of the
        memo (so it skips every era this resolver already answers). It persists
        nothing and its answers are thrown away. Call it on the thread that owns
        this resolver, while that resolver is idle (prefetch.warm does). The
        ticker map is shared once this resolver has loaded it; until then the
        shadow loads it itself, only when an era needs it, as a one-worker run
        would."""
        s = TickerResolver(self.edgar, rename_map=self.rename_map, manual_overrides=self.manual_overrides,
                           name_lookup=self.name_lookup, observed_names=self.observed_names, cik_pins=self.cik_pins,
                           today=self.today)
        s._memo, s._memo_observed = dict(self._memo), dict(self._memo_observed)
        s._volatile, s._degraded = set(self._volatile), set(self._degraded)
        s._companies = self._companies
        return s

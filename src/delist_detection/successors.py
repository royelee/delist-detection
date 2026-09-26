"""Successors after a FIGI change (CONTEXT.md, Successor): the security a
holder keeps after an exchange transfer that changed the FIGI.

Two sources, tried in order by the pipeline's successor stage: a security of
this run that starts right after the last trade under the same issuer or
ticker (`successor_in_run`: a holding company's new line, a rename's new
FIGI), then the successor issuer's own 8-K12B/8-K12G3 found by EDGAR
full-text search (`successor_search_args`, `successor_query`,
`successor_from_8k12b`).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import NamedTuple

from .delistings import SUCCESSOR_UNKNOWN, Delisting
from .figi_resolution import FigiCandidate, share_class_from_name, us_candidates
from .listing_status import edgar_lists
from .names import names_agree
from .observations import normalize_ticker
from .security_master import Security


def _to_date(s: str) -> date:
    return date.fromisoformat(s)


SUCCESSOR_FORMS = "8-K12B,8-K12G3"


def successor_query(name: str, day: date) -> tuple[str, str, date, date]:
    """The full-text search successor_from_8k12b sends for `name` around `day`.
    The prefetch sends the same one, so the sequential pass reads it from cache."""
    return f'"{name}"', SUCCESSOR_FORMS, day - timedelta(days=30), day + timedelta(days=60)


def successor_from_8k12b(search: Callable, figi, *, name: str, day: date, exclude_cik: int,
                         share_class: str = "COMMON", edgar=None,
                         own_tickers: set[str] | frozenset[str] = frozenset()
                         ) -> tuple[int, FigiCandidate, str] | None:
    """The successor issuer that filed an 8-K12B naming `name` around `day`,
    resolved to the US composite FIGI whose share class matches the
    predecessor's `share_class`.

    A display name looks like ``"Alphabet Inc.  (GOOGL, GOOG)  (CIK
    0001652044)"``: the tickers are the parenthetical immediately before the
    trailing ``(CIK ...)`` — never the first parenthetical in the string,
    which can be part of the issuer's own legal name (``"Banco Santander
    (Brasil) S.A.  (BSBR)  (CIK 0001471119)"`` carries the ticker ``BSBR``,
    not ``Brasil``). Each of those tickers is resolved through OpenFIGI; a
    resolved candidate is kept only when its name agrees
    (`names.names_agree`) with the successor's own EDGAR name — the text
    before that ticker parenthetical, exactly as EDGAR's full-text search
    recorded it, so no extra network call is needed to confirm it. Among the
    agreeing candidates, the one whose share class (`share_class_from_name`)
    equals the predecessor's is picked; if the predecessor is plain common
    and exactly one candidate agrees on name, that one is taken even without
    an exact class match. Otherwise returns None (the caller leaves
    `successor_unknown` set rather than guess). A display name with no
    ticker parenthetical yields no candidates and makes no OpenFIGI request.

    A filer is skipped when it is another issuer's own, still-listed stock:
    its EDGAR name does not agree with the predecessor's `name`, none of its
    tickers is one of the predecessor's `own_tickers`, and (with `edgar`) its
    EDGAR record lists one of them on a major exchange today. Clear Channel
    Outdoor's 2019 successor filed its 8-K12B under the predecessor's own CIK
    (excluded), which left iHeartMedia's 8-K12G3 for its own emergence, naming
    its subsidiary: IHRT is not Clear Channel Outdoor's successor. Alphabet
    (a new name on Google's own tickers) is.

    Returns `(cik, candidate, filing_date)`.
    """
    own = {normalize_ticker(t) for t in own_tickers if t}
    hits = search(*successor_query(name, day))
    for h in hits:
        src = h.get("_source", h)
        filing_date = src.get("file_date") or src.get("filing_date") or ""
        for cik_s, disp in zip(src.get("ciks") or [], src.get("display_names") or []):
            cik = int(cik_s)
            if cik == exclude_cik:
                continue
            m = re.search(r"\(([^()]*)\)\s*\(CIK\s+\d+\)\s*$", disp)
            if not m:
                continue
            tickers = [normalize_ticker(t) for t in m.group(1).split(",") if t.strip()]
            if not tickers or figi is None:
                continue
            edgar_name = disp[: m.start()].strip()
            if (edgar is not None and not names_agree(name, edgar_name) and not own & set(tickers)
                    and edgar_lists(edgar, cik, tickers)):
                continue
            candidates: list[FigiCandidate] = []
            for t in tickers:
                ans = figi.map([{"idType": "TICKER", "idValue": t.replace("-", "/")}])[0]
                candidates += us_candidates(ans.get("data") or [])
            agreeing = [c for c in candidates if names_agree(c.name, edgar_name)]
            if not agreeing:
                continue
            class_matches = [c for c in agreeing if share_class_from_name(c.name) == share_class]
            if len(class_matches) == 1:
                return cik, class_matches[0], filing_date
            if share_class == "COMMON" and len(agreeing) == 1:
                return cik, agreeing[0], filing_date
    return None


_CLASS_WORDS = re.compile(r"\b(?:CL(?:ASS)?|SER(?:IES)?)\s*-?\s*[A-Z0-9]\b|-[A-Z]$", re.I)
_STATE_TAG = re.compile(r"\s*/[A-Z]+/?\s*$")        # EDGAR's "AETNA INC /PA/", "ALLEGHANY CORP /DE"


def successor_search_name(edgar, cik: int | None, observed_name: str | None) -> str:
    """The predecessor's name as an 8-K12B would print it: the issuer's EDGAR
    name from its submissions JSON without EDGAR's state tag ("Google Inc."),
    else the observation name without its class words ("GOOGLE INC CLASS A"
    -> "GOOGLE INC")."""
    sub = edgar.submissions(cik) if cik is not None else None
    name = (sub.get("name") or "").strip() if isinstance(sub, dict) else ""
    if name:
        return _STATE_TAG.sub("", name).strip()
    return re.sub(r"\s+", " ", _CLASS_WORDS.sub(" ", observed_name or "")).strip(" -")


SUCCESSOR_BEFORE_DAYS, SUCCESSOR_AFTER_DAYS = 5, 15    # a successor's first sighting around the last trade


class SecurityStart(NamedTuple):
    """How a security of the run (observed or added) first shows up, for the
    in-run successor search: its first sighting, its issuer CIK, and every
    ticker it was sighted under."""
    first_seen: str
    issuer_cik: int | None
    tickers: set[str]


def successor_in_run(e: Delisting, starts: dict[str, SecurityStart]) -> tuple[str, str] | None:
    """The one security of the run (observed or added; `starts` by sec_id)
    whose first sighting falls within
    [last trade - SUCCESSOR_BEFORE_DAYS, last trade + SUCCESSOR_AFTER_DAYS] and
    that shares the delisted security's issuer CIK or its ticker: the new line
    of a holding-company reorganization or a rename. With no last trade date
    the Form 25's filing date stands in for it (the delisting date is ten days
    later), else the delisting date. Returns (sec_id, "same_issuer" |
    "same_ticker"); None for zero or several candidates."""
    day = e.last_trade.day or (_to_date(e.form25_sub.filing_date) if e.form25_sub is not None
                               else _to_date(e.delist_date))
    lo = (day - timedelta(days=SUCCESSOR_BEFORE_DAYS)).isoformat()
    hi = (day + timedelta(days=SUCCESSOR_AFTER_DAYS)).isoformat()
    # the delisting's ticker can be a deleted-symbol spelling ("APAXXXX"): match
    # on every ticker the delisted security carried
    own = (starts[e.sec_id].tickers if e.sec_id in starts else set()) | {e.ticker}
    found: dict[str, str] = {}
    for sid, start in starts.items():
        if sid == e.sec_id or not lo <= start.first_seen <= hi:
            continue
        if start.issuer_cik is not None and start.issuer_cik == e.cik:
            found[sid] = "same_issuer"
        elif own & start.tickers:
            found[sid] = "same_ticker"
    return next(iter(found.items())) if len(found) == 1 else None


def successor_search_args(edgar, e: Delisting, starts: dict[str, SecurityStart],
                          securities: dict[str, Security]) -> tuple[str, date] | None:
    """The (name, day) the successor search sends EDGAR's full-text search for `e`
    (`successor_query` builds the search), or None when it sends none: the
    successor is known, or it is a security of this run (`successor_in_run`).
    The warm pass and the sequential loop both ask this, so they send the same
    searches. Only a delisting it searches for reads EDGAR (the issuer's
    submissions, for its name)."""
    if SUCCESSOR_UNKNOWN not in e.flags or successor_in_run(e, starts) is not None:
        return None
    return (successor_search_name(edgar, e.cik, securities[e.sec_id].name),
            e.last_trade.day or _to_date(e.delist_date))

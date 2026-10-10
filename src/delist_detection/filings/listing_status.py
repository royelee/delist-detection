"""Where a security is listed: before and after a Form 25, and today.

A Form 25 that withdraws a secondary listing (Apache from the Chicago Stock
Exchange in 2020 while it stayed on NYSE) is not a delisting (D17). The 10-K
cover page names every exchange a class is registered on, so the covers on
either side of the Form 25 tell the cases apart.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta

from ..sources.edgar import FILED_AFTER_RUN_DATE, EdgarSubmission
from .evidence import parse_day
from ..sources.fatal import FATAL
from .form25 import MAJOR_EXCHANGES, REGIONAL_EXCHANGES, exchange_label, exchanges_named
from ..vocabulary.identifiers import is_placeholder, normalize_ticker

ANNUAL_FORMS = frozenset({"10-K", "10-K405", "10-KSB", "10-KT", "20-F", "40-F"})
EXCHANGE_VENUES = frozenset({"UN", "UW", "UQ", "UR", "UA", "UP", "UF"})
COVER_WINDOW_DAYS = 450


def cover_exchanges(text: str) -> set[str]:
    head = (text or "")[:12000]
    m = re.search(r"name of each exchange on which registered", head, re.I)
    window = head[m.start(): m.start() + 1500] if m else head[:4000]
    return exchanges_named(window) & (MAJOR_EXCHANGES | REGIONAL_EXCHANGES)


def _annual(filings: Iterable[EdgarSubmission]) -> list[tuple[date, EdgarSubmission]]:
    out = [(d, f) for f in filings if f.form in ANNUAL_FORMS and (d := parse_day(f.filing_date))]
    return sorted(out, key=lambda x: x[0])


def exchanges_around(edgar, cik: int, filings: list[EdgarSubmission],
                     day: date) -> tuple[set[str] | None, set[str] | None]:
    reports = _annual(filings)
    window = timedelta(days=COVER_WINDOW_DAYS)
    before = [f for d, f in reports if day - window <= d < day]
    after = [f for d, f in reports if day < d <= day + window]

    def read(f: EdgarSubmission) -> set[str]:
        return cover_exchanges(edgar.fetch_filing_text(cik, f.accession, f.primary_doc))

    return (read(before[-1]) if before else None), (read(after[0]) if after else None)


_COVER_COLUMN = re.compile(r"name of each exchange\s+on which\s+registered", re.I)


def unlisted_cover(edgar, cik: int, filings: list[EdgarSubmission], day: date) -> str | None:
    """The filing date of the first annual report after `day` (within COVER_WINDOW_DAYS) whose cover page names no
    exchange: its "Name of each exchange on which registered" column is there to read and holds none of the exchanges
    (Freddie Mac's and Fannie Mae's 10-Ks after the NYSE left them in 2010). None when there is no such report, its
    text could not be read (an empty read is no cover), or its cover has no such column in its first 12,000
    characters (an inline-XBRL report, whose cover this reading does not find)."""
    window = timedelta(days=COVER_WINDOW_DAYS)
    after = [f for d, f in _annual(filings) if day < d <= day + window]
    if not after:
        return None
    text = edgar.fetch_filing_text(cik, after[0].accession, after[0].primary_doc) or ""
    if not _COVER_COLUMN.search(text[:12000]) or cover_exchanges(text):
        return None
    return after[0].filing_date


def withdrawal_kind(exchange: str, before: set[str] | None, after: set[str] | None) -> str:
    if exchange in REGIONAL_EXCHANGES:
        return "secondary"
    if exchange not in MAJOR_EXCHANGES or after is None:
        return "delisting"
    remaining = (after & MAJOR_EXCHANGES) - {exchange}
    if not remaining:
        return "delisting"
    if before is not None and remaining <= before:
        return "secondary"
    return "delisting"


def edgar_lists(edgar, cik: int, tickers: Iterable[str] | None) -> bool:
    """True when the issuer's EDGAR submissions JSON lists one of `tickers` on a
    major exchange (any of its tickers when `tickers` is None)."""
    return lists_on_major_exchange(edgar.submissions(cik), tickers)


EDGE_DAYS = 31     # a security last sighted this close to the fails data's last day was still trading at its end


def delisted_after_run_date(sub) -> bool:
    """Whether the issuer filed a Form 25 after the run date (a submissions JSON as an --as-of run reads it,
    `edgar.FILED_AFTER_RUN_DATE`)."""
    return isinstance(sub, dict) and any(str(f).startswith("25") for f in sub.get(FILED_AFTER_RUN_DATE) or ())


def listed_on_run_date(listed_now: bool | None, sub, last_seen: date | str | None, data_end: date | str | None, *,
                       tickers: Iterable[str] | None = None, behind_clock: bool = False) -> bool | None:
    """Whether a security was listed on an --as-of run's date. `listed_today` reads today's OpenFIGI answer and
    EDGAR `exchanges`, which an ending after the run date has already changed (in a run as of 2026-09-25 read on
    2026-10-10: WBD and QRVO "No identifier found", LESL on OTC as LESLQ). A security still trading at the end of
    the fails data (`last_seen` within EDGE_DAYS of `data_end`) was listed on the run date when its issuer filed a
    Form 25 after it (`sub`, its submissions JSON, `delisted_after_run_date`), or, in a run behind the clock
    (`behind_clock`), when the issuer's EDGAR copy still lists one of its `tickers` on a major exchange (today's
    OpenFIGI answer postdates the run date). Issuer-level evidence alone says nothing of its other lines: Discovery's
    DISCA and DISCK ended in 2022 under WBD's CIK, long before the data's end."""
    seen, end = (d if isinstance(d, date) else parse_day(d) for d in (last_seen, data_end))
    if listed_now or seen is None or end is None or (end - seen).days > EDGE_DAYS:
        return listed_now
    if _form25_since(sub, seen - timedelta(EDGE_DAYS)):
        # a Form 25 the issuer filed by the run date is the finder's to read, and an ending it confirms wins over any
        # listing evidence: OKE 2026's transfer (effective after the run date), TWO 2026's merger (a later Form 25
        # of its preferred is no listing of the common)
        return listed_now
    if delisted_after_run_date(sub) or (behind_clock and lists_on_major_exchange(sub, tickers)):
        return True
    return listed_now


def _form25_since(sub, day: date) -> bool:
    """Whether the issuer's recent filings (as the run date reads them) hold a Form 25 filed on or after `day`."""
    recent = (sub.get("filings") or {}).get("recent") or {} if isinstance(sub, dict) else {}
    last = day.isoformat()
    return any(str(f).startswith("25") and (d or "") >= last
               for f, d in zip(recent.get("form") or [], recent.get("filingDate") or []))


def lists_on_major_exchange(sub, tickers: Iterable[str] | None) -> bool:
    """`edgar_lists` over a submissions JSON (or its profile, `IssuerRecord.profile`) already read: True when it
    lists one of `tickers` on a major exchange (any of its tickers when `tickers` is None); False for no copy."""
    if not isinstance(sub, dict):
        return False
    want = None if tickers is None else {normalize_ticker(t) for t in tickers if t}
    for t, x in zip(sub.get("tickers") or [], sub.get("exchanges") or []):
        if (want is None or normalize_ticker(t) in want) and exchange_label(x or "") in MAJOR_EXCHANGES:
            return True
    return False


def issuer_exchange(edgar, cik: int | None, ticker: str) -> str | None:
    """The exchange EDGAR's own submissions JSON records for `ticker` (the
    parallel `tickers`/`exchanges` arrays), mapped to the table's exchange
    names; None when the issuer, the ticker, or its exchange entry is missing.
    Reads the submissions JSON the finder already cached -- no new source."""
    if cik is None:
        return None
    sub = edgar.submissions(cik)
    if not isinstance(sub, dict):
        return None
    want = normalize_ticker(ticker)
    for t, x in zip(sub.get("tickers") or [], sub.get("exchanges") or []):
        if normalize_ticker(t) == want and x:
            return exchange_label(x) or None
    return None


def listing_job(sec_id: str) -> dict:
    """The OpenFIGI mapping job listed_today asks about `sec_id`."""
    return {"idType": "COMPOSITE_ID_BB_GLOBAL", "idValue": sec_id}


def listing_answers(figi, sec_ids: Iterable[str]) -> dict[str, dict]:
    """OpenFIGI's current answer for each composite FIGI in `sec_ids` (placeholders
    skipped), sent as batched mapping requests (`OpenFigiClient.map` chunks them)
    instead of one request per security. Never cached, as in listed_today.
    A fatal exception (`fatal.FATAL`: a refusal, or OpenFIGI down after its
    retries) propagates and stops the run; any other failure returns {}, so
    each security asks on its own, inside its own error handling."""
    ids = [s for s in dict.fromkeys(sec_ids) if not is_placeholder(s)]
    if figi is None or not ids:
        return {}
    try:
        answers = figi.map([listing_job(s) for s in ids], use_cache=False)
    except FATAL:
        raise
    except Exception:          # noqa: BLE001 -- the per-security path reports it
        return {}
    return dict(zip(ids, answers))


def listed_today(figi, sec_id: str, *, edgar=None, cik: int | None = None,
                 tickers: Iterable[str] | None = None, answer: dict | None = None) -> bool | None:
    """Whether the security trades on a US exchange today.

    A composite FIGI needs an exchange venue in OpenFIGI's answer (`answer` when
    listing_answers already fetched it, else asked here). OpenFIGI keeps venue
    rows for a dead line (Celgene, TSS, old Apache still show UW/UN), so when the
    issuer's CIK is known the issuer's EDGAR submissions JSON must also list one
    of the security's `tickers`, or a ticker OpenFIGI returns, on a major
    exchange. With no CIK, OpenFIGI alone decides. A placeholder has no FIGI:
    EDGAR alone decides, on the security's own tickers. Both answers are today's (`listed_on_run_date` corrects
    them for an --as-of run)."""
    if not is_placeholder(sec_id):
        ans = answer if answer is not None else figi.map([listing_job(sec_id)], use_cache=False)[0]
        if "error" in ans:
            return None
        rows = [r for r in ans.get("data") or [] if r.get("exchCode") in EXCHANGE_VENUES]
        if not rows:
            return False
        if edgar is None or cik is None:
            return True
        names = None if tickers is None else [*tickers, *(str(r.get("ticker") or "").replace("/", "-") for r in rows)]
        return edgar_lists(edgar, cik, names)
    if edgar is None or cik is None:
        return None
    return edgar_lists(edgar, cik, tickers)

"""A merger's acquirer as a security of the run: its US composite FIGI, found
through the fails rows under the acquirer ticker the merger terms name, and
its issuer CIK."""
from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from datetime import date, timedelta

from .delistings import DelistingEvent
from .figi_resolution import FigiCandidate, accept, us_candidates
from .ftd import FtdIndex, FtdRow
from .listing_status import edgar_lists
from .observations import normalize_ticker

ACQUIRER_WINDOW_DAYS = 10       # the fails rows under the acquirer ticker this close to the last trade


def find_acquirer(figi, ftd: FtdIndex, acq: str, day: date,
                  own_cusips: Collection[str]) -> tuple[FigiCandidate, list[FtdRow]] | None:
    """The acquirer's US composite FIGI: the CUSIP most of the fails rows under
    the acquirer ticker `acq` carry within ACQUIRER_WINDOW_DAYS of the target's
    last trade `day`, mapped through OpenFIGI and accepted on `acq`; with those
    rows (its ticker_history evidence). An acquirer that took the target's
    ticker (a holding company, Ashland 2016) shares the fails rows under it with
    the target, whose own CUSIPs (`own_cusips`) keep failing after the last
    trade: only other CUSIPs count. None when no row or no candidate is left."""
    rows = [r for r in ftd.by_symbol(acq, (day - timedelta(days=ACQUIRER_WINDOW_DAYS)).isoformat(),
                                     (day + timedelta(days=ACQUIRER_WINDOW_DAYS)).isoformat())
            if r.cusip not in own_cusips]
    cusip = Counter(r.cusip for r in rows).most_common(1)
    if not cusip:
        return None
    ans = figi.map([{"idType": "ID_CUSIP", "idValue": cusip[0][0], "includeUnlistedEquities": True}])[0]
    cand = accept(us_candidates(ans.get("data") or []), ticker=acq, names=[], via_cusip=True)
    return (cand, rows) if cand is not None else None


def acquirer_cik(resolver, edgar, acq: str, day: date, target: DelistingEvent) -> int | None:
    """The acquirer's issuer CIK. The resolver answers for (ticker, day), so an
    acquirer that took the target's own ticker (Progressive Waste becoming
    Waste Connections under WCN) resolves to the target's CIK, often through the
    target era's pin. Then the SEC ticker map's holder (company_tickers.json)
    stands in when it is a different company whose EDGAR record lists the
    ticker on a major exchange today; otherwise the CIK is left unknown rather
    than copied from the target."""
    cik = resolver.resolve(acq, day.isoformat()).cik
    if normalize_ticker(acq) != normalize_ticker(target.ticker) and (cik is None or cik != target.cik):
        return cik
    companies = edgar.company_tickers() or {}
    row = companies.get(acq.upper()) or companies.get(acq.upper().replace(".", "-")) or {}
    try:
        holder = int(row.get("cik_str"))
    except (TypeError, ValueError):
        return None
    if holder == target.cik or not edgar_lists(edgar, holder, [acq]):
        return None
    return holder

"""The second pass's rule D (FB-004 part c, FNFV): an era the other rules left with no issuer takes the issuer its CUSIP's
six-character issuer code names, when the other eras that hold that code, over the same dates, are all one issuer's."""
from __future__ import annotations

from datetime import date

from delist_detection.identity.identity import EraIssuers, era_last_seen, refine_eras
from delist_detection.identity.observations import Observation, split_eras
from delist_detection.identity.ticker_resolver import TickerResolver
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.sources.ftd import FtdIndex, FtdRow


class _Edgar:
    def __init__(self, companies):
        self.companies = companies

    def company_tickers(self):
        return {}

    def submissions(self, cik, fresh_after=None):
        c = self.companies.get(int(cik))
        return {"name": c[0], "formerNames": [], "sic": ""} if c else {"__not_found__": True}

    def recent_filings(self, cik):
        c = self.companies.get(int(cik))
        return [EdgarSubmission(f"{cik}-{i}", form, day, "", "", "x.htm") for i, (form, day) in enumerate(c[1])] \
            if c else []


FNF = 1331875
COMPANIES = {FNF: ("Fidelity National Financial, Inc.", [("10-K", "2006-03-01"), ("10-K", "2016-02-26")]),
             999: ("Another Issuer Inc", [("10-K", "2006-03-01")])}


def _rows(symbol, cusip, desc, first="2014-07-01", n=30):
    y, m = int(first[:4]), int(first[5:7])
    return [FtdRow(f"{y + (m - 1 + i) // 12}-{(m - 1 + i) % 12 + 1:02d}-15", cusip, symbol, desc, 10.0) for i in range(n)]


def _pass(fnfv_cusip="31620R402", fnf_cusip="31620R105", fnf_first="2014-12-31", fnf_cik=FNF, companies=COMPANIES):
    eras = split_eras([Observation("FNF", fnf_first, "FIDELITY NATIONAL FINANCIAL INC"),
                       Observation("FNF", "2016-12-30", "FIDELITY NATIONAL FINANCIAL INC")]) \
        + split_eras([Observation("FNFV", "2014-12-31", "FNFV GROUP INC"), Observation("FNFV", "2016-12-30", "FNFV GROUP INC")])
    ftd = FtdIndex(_rows("FNF", fnf_cusip, "FIDELITY NATL FINL INC") + _rows("FNFV", fnfv_cusip, "FNFV GROUP INC"))
    refined = refine_eras(eras, ftd)
    last_seen = {e.key: era_last_seen(e, ftd) for e in refined}
    resolver = TickerResolver(_Edgar(companies))
    ciks ={e.key: (fnf_cik if e.ticker == "FNF" else None) for e in refined}
    got = EraIssuers(resolver.issuers, resolver.frequency_candidates).infer(refined, ftd, last_seen, ciks, [])
    return {k: (v.cik, v.source) for k, v in got.inferred.items()}


def test_an_era_whose_cusip_issuer_code_is_a_known_issuers_takes_it():
    """FNFV (FNFV Group, a tracking stock): its CUSIP 31620R402 shares 31620R with Fidelity National Financial's own
    31620R105, an issuer the first pass found; the name and the rows say FNFV GROUP, which no EDGAR name of 1331875
    does, and the code is the evidence."""
    assert _pass() == {"FNFV@2014-12-31": (FNF, "cusip_issuer")}


def test_another_issuer_code_gives_nothing():
    assert _pass(fnf_cusip="99999Z105") == {}


def test_an_issuer_that_had_not_filed_by_the_era_gives_nothing():
    late = {FNF: ("Fidelity National Financial, Inc.", [("10-K", "2019-03-01")])}
    assert _pass(companies=late) == {}


def test_eras_of_two_issuers_holding_the_code_give_nothing():
    """The code was reused by the issuer's successor (SanDisk before and after its 2016 acquisition): two issuers
    hold it over the era's dates, so the code does not say which."""
    eras = split_eras([Observation("FNF", "2014-12-31", "FIDELITY NATIONAL FINANCIAL INC"),
                       Observation("FNF", "2016-12-30", "FIDELITY NATIONAL FINANCIAL INC")]) \
        + split_eras([Observation("FNFB", "2014-12-31", "OTHER NAME INC"), Observation("FNFB", "2016-12-30", "OTHER NAME INC")]) \
        + split_eras([Observation("FNFV", "2014-12-31", "FNFV GROUP INC"), Observation("FNFV", "2016-12-30", "FNFV GROUP INC")])
    ftd = FtdIndex(_rows("FNF", "31620R105", "FIDELITY NATL FINL INC") + _rows("FNFB", "31620R303", "OTHER NAME INC")
                   + _rows("FNFV", "31620R402", "FNFV GROUP INC"))
    refined = refine_eras(eras, ftd)
    resolver = TickerResolver(_Edgar(COMPANIES))
    ciks = {e.key: {"FNF": FNF, "FNFB": 999}.get(e.ticker) for e in refined}
    got = EraIssuers(resolver.issuers, resolver.frequency_candidates).infer(
        refined, ftd, {e.key: era_last_seen(e, ftd) for e in refined}, ciks, [])
    assert got.inferred == {}

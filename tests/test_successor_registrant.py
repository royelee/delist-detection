"""The second pass's rule E (FB-027): a derived era, the line after a CUSIP change stage 4b refused, takes the company
SEC's name list holds under its own name written out word for word, when that company filed a successor registration
at the change. Exxon Mobil 2026 and Aaron's 2020: the fails files write EXXONMOBIL HLDGS CORPORATION and AARONS HLDGS CO
INC, the name list has EXXONMOBIL HOLDINGS CORP and AARON'S HOLDINGS COMPANY, INC., and a lookup by exact name and by
prefix finds neither."""
from __future__ import annotations

import pytest

from delist_detection.identity.identity import EraIssuers, last_sightings
from delist_detection.identity.observations import DerivedFrom, Observation, TickerEra
from delist_detection.identity.ticker_resolver import TickerResolver
from delist_detection.sources.cik_lookup import CikNameIndex
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.sources.ftd import FtdIndex, FtdRow
from delist_detection.vocabulary.names import written_out

INDEX = CikNameIndex.from_text("\n".join([
    "EXXON MOBIL CORP:0000034088:",
    "EXXONMOBIL CORP:0001226649:",
    "EXXONMOBIL HOLDINGS CORP:0002115436:",
    "EXXONMOBIL INVESTMENT MANAGEMENT INC /TX:0001082970:",
    "AARON'S COMPANY, INC.:0001821393:",
    "AARON'S HOLDINGS COMPANY, INC.:0001808834:",
    "AARON'S INC:0000706688:",
    "AARON'S SPINCO, INC.:0001821393:",
    "AARONS ORVILLE G:0001568757:",
    "AARON SCOTT:0000000077:",
]))

# CIK -> (name, former names, filings as (form, day))
COMPANIES = {
    34088: ("EXXON MOBIL CORP", [], [("10-K", "2000-03-01"), ("25-NSE", "2026-07-02")]),
    2115436: ("ExxonMobil Holdings Corp", [], [("8-K12B", "2026-07-01"), ("10-Q", "2026-08-04")]),
    1226649: ("EXXONMOBIL CORP", [], [("10-K", "2003-03-01")]),
    1082970: ("EXXONMOBIL INVESTMENT MANAGEMENT INC /TX", [], [("13F-HR", "2026-08-14")]),
    706688: ("AARON'S INC", [], [("10-K", "2011-02-14"), ("25-NSE", "2020-10-19")]),
    1808834: ("PROG Holdings, Inc.", [("Aaron's Holdings Company, Inc.", "2020-04-13", "2020-11-23")],
              [("S-4", "2020-04-13"), ("8-K12B", "2020-10-16"), ("10-Q", "2020-11-02")]),
    1821393: ("Aaron's Company, Inc.", [("Aaron's SpinCo, Inc.", "2020-09-08", "2020-11-02")],
              [("DRS", "2020-09-08"), ("10-12B", "2020-11-02")]),
}


class _Edgar:
    def __init__(self, companies=COMPANIES):
        self.companies = companies

    def company_tickers(self):
        return {}

    def submissions(self, cik, fresh_after=None):
        c = self.companies.get(int(cik))
        if c is None:
            return {"__not_found__": True}
        return {"name": c[0], "sic": "", "formerNames": [
            {"name": n, "from": f"{lo}T00:00:00.000Z", "to": f"{hi}T00:00:00.000Z"} for n, lo, hi in c[1]]}

    def recent_filings(self, cik):
        c = self.companies.get(int(cik))
        return [EdgarSubmission(f"{cik}-{i}", form, day, "", "", "x.htm") for i, (form, day) in enumerate(c[2])] \
            if c else []


def _era(ticker, first, name, cusip, origin):
    obs = [Observation(ticker, first, name, derived=True)]
    return TickerEra(ticker, first, first, obs, ftd_cusips=(cusip,), derived_from=origin)


def _pass(ticker, first, name, cusip, origin, days, *, companies=COMPANIES, index=INDEX):
    era = _era(ticker, first, name, cusip, origin)
    ftd = FtdIndex([FtdRow(d, cusip, ticker, name, 100.0) for d in days])
    resolver = TickerResolver(_Edgar(companies), name_index=index)
    last_seen = last_sightings([era], ftd)
    got = EraIssuers(resolver.issuers, resolver.frequency_candidates).infer([era], ftd, last_seen, {era.key: None}, [])
    return {k: (v.cik, v.source) for k, v in got.inferred.items()}


XOM_ORIGIN = DerivedFrom("BBG000GZQ728", 34088, "merged_out", "30231G102", "2026-07-02")
XOM_DAYS = ["2026-07-06", "2026-07-20", "2026-08-03", "2026-09-14"]
AAN_ORIGIN = DerivedFrom("BBG000D9V7T4", 706688, "merged_out", "002535300", "2020-10-19")
AAN_DAYS = ["2020-10-19", "2020-10-26", "2020-11-09", "2020-11-23"]


def _xom(**kw):
    return _pass("XOM", "2026-07-06", "EXXONMOBIL HLDGS CORPORATION", "30233Q108", XOM_ORIGIN, XOM_DAYS, **kw)


def test_a_derived_era_takes_the_successor_registrant_sec_lists_under_its_name_written_out():
    """Exxon Mobil 2026: the new CUSIP's rows say EXXONMOBIL HLDGS CORPORATION, SEC's name list has EXXONMOBIL
    HOLDINGS CORP, CIK 2115436, and that company filed an 8-K12B the day before the change."""
    assert _xom() == {"XOM@2026-07-06": (2115436, "successor_registrant")}


def test_an_apostrophe_and_two_short_words_are_the_same_name():
    """Aaron's 2020: AARONS HLDGS CO INC is AARON'S HOLDINGS COMPANY, INC., CIK 1808834 (PROG Holdings today), which
    filed its 8-K12B on 2020-10-16. AARON'S COMPANY, INC. and AARON'S INC have a word less and are other companies."""
    got = _pass("AAN", "2020-10-19", "AARONS HLDGS CO INC", "00258R109", AAN_ORIGIN, AAN_DAYS)
    assert got == {"AAN@2020-10-19": (1808834, "successor_registrant")}


def test_the_name_alone_is_not_taken():
    """A company the list names so that filed no successor registration at the change is no answer."""
    quiet = {**COMPANIES, 2115436: ("ExxonMobil Holdings Corp", [], [("10-Q", "2026-08-04"), ("8-K", "2026-07-01")])}
    assert _xom(companies=quiet) == {}
    early = {**COMPANIES, 2115436: ("ExxonMobil Holdings Corp", [], [("8-K12B", "2026-03-02"), ("10-Q", "2026-08-04")])}
    assert _xom(companies=early) == {}                                   # a registration months before the change


def test_an_era_the_run_did_not_derive_is_not_asked():
    era_kw = dict(origin=None, days=XOM_DAYS)
    assert _pass("XOM", "2026-07-06", "EXXONMOBIL HLDGS CORPORATION", "30233Q108", **era_kw) == {}


def test_without_a_name_list_nothing_is_found():
    assert _xom(index=None) == {}


def test_two_companies_under_the_name_give_nothing():
    """The rows cannot tell two companies the list names alike that both filed a successor registration."""
    index = CikNameIndex.from_text("EXXONMOBIL HOLDINGS CORP:0002115436:\nEXXONMOBIL HOLDINGS CO:0000000555:")
    twin = {**COMPANIES, 555: ("ExxonMobil Holdings Co", [], [("8-K12B", "2026-07-01")])}
    assert _xom(companies=twin, index=index) == {}


@pytest.mark.parametrize("short, full, same", [
    ("EXXONMOBIL HLDGS CORPORATION", "EXXONMOBIL HOLDINGS CORP", True),
    ("AARONS HLDGS CO INC", "AARON'S HOLDINGS COMPANY, INC.", True),
    ("EXXONMOBIL HLDGS CORPORATION", "EXXONMOBIL CORP", False),                  # a word less
    ("AARONS HLDGS CO INC", "AARON'S COMPANY, INC.", False),
    ("BUNGE LIMITED", "BUNGE LIMITED FINANCE CORP", False),                      # a word more: FB-026's subsidiary
    ("EVEREST RE GROUP LTD", "EVEREST RE CAPITAL TRUST", False),                 # another word
    ("AARONS HLDGS CO INC", "AARONSON HOLDINGS COMPANY INC", False),             # the first word is the same or nothing
    ("X PPTYS TR", "X PROPERTIES TRUST", True),                                  # the vendor's own abbreviation
    ("US BANCORP", "US BANCORP \\DE\\", True),                                   # EDGAR's state tag is no word
    ("FOO A INC", "FOO ACQUISITION INC", False),                                 # one letter is no short form
    ("", "EXXONMOBIL HOLDINGS CORP", False),
])
def test_written_out(short, full, same):
    assert written_out(short, full) is same and written_out(full, short) is same


def test_the_name_list_is_searched_by_a_names_first_word():
    """`CikNameIndex.beginning`: the entries whose name begins with the whole word; a word the list wrote with an
    apostrophe is two words there, so AARONS finds AARON'S and not AARON SCOTT."""
    assert [h.cik for h in INDEX.beginning("EXXONMOBIL")] == [1226649, 2115436, 1082970]
    assert sorted(h.name for h in INDEX.beginning("AARONS")) == [
        "AARON'S COMPANY, INC.", "AARON'S HOLDINGS COMPANY, INC.", "AARON'S INC", "AARON'S SPINCO, INC.",
        "AARONS ORVILLE G"]
    assert INDEX.beginning("EXXON") == [INDEX.beginning("EXXON")[0]] and INDEX.beginning("EXXON")[0].cik == 34088
    assert INDEX.beginning("") == []


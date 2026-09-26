"""Renamed tickers resolve to their issuer (KORS -> Capri Holdings, NU -> Eversource,
LUK -> Jefferies Financial), and a recycled ticker never reaches today's holder
(NU -> Nu Holdings, ALTR -> Altair).

Offline, over real data: tests/fixtures/eras/renamed_observations.csv (the
observations of the tickers involved), renamed_ftd_rows.csv (their SEC
fails-to-deliver rows, thinned), and renamed_edgar.json (each CIK's EDGAR names
and a thinned filing list, the 8-K frequency rank EDGAR full-text search gave at
each era's last sighting, and EDGAR company-search answers)."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from delist_detection import manifest as run_manifest
from delist_detection import pipeline
from delist_detection.edgar import EdgarSubmission
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.observations import ObservationIndex, load_observations
from delist_detection.pipeline import Clients, _RunContext
from delist_detection.security_master import cusip_handoffs, era_last_seen, refine_eras
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "eras"
DATA = json.loads((FIX / "renamed_edgar.json").read_text())
FTD_WINDOW = (date(2007, 12, 17), date(2026, 9, 25))     # the committed run's fails-to-deliver window


class _Edgar:
    """EDGAR as the fixture recorded it: submissions (name and former names),
    the thinned filing list, company-search answers, and SEC's ticker map."""

    def __init__(self, issuers=None, tickers=None, search=None):
        self.issuers = issuers if issuers is not None else DATA["issuers"]
        self.tickers = tickers or {}
        self.search = search if search is not None else DATA["company_search"]

    def company_tickers(self):
        return self.tickers

    def submissions(self, cik, fresh_after=None):
        d = self.issuers.get(str(int(cik)))
        if d is None:
            return {"__not_found__": True}
        return {"name": d["name"], "formerNames": d["formerNames"], "sic": ""}

    def recent_filings(self, cik):
        d = self.issuers.get(str(int(cik))) or {"filings": []}
        return [EdgarSubmission(f"{cik}-{i}", form, day, "", "", "x.htm") for i, (form, day) in
                enumerate(d["filings"])]

    def company_search_atom(self, company, form_type="25-NSE"):
        return [dict(h) for h in self.search.get(f"{company}|{form_type}", [])]


class _RowsClient:
    """An FTD client over in-memory rows, filtered the way the real one filters."""

    def __init__(self, rows):
        self.rows_ = list(rows)

    def urls_for(self, lo, hi):
        return ["mem"]

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self.rows_:
            if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                yield r


def _rows():
    with (FIX / "renamed_ftd_rows.csv").open(newline="") as fh:
        return [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"], float(r["price"]) if r["price"] else None)
                for r in csv.DictReader(fh)]


@pytest.fixture(scope="module")
def index():
    return ObservationIndex(load_observations(FIX / "renamed_observations.csv"))


@pytest.fixture(scope="module")
def ftd(index):
    return FtdIndex.load(_RowsClient(_rows()), *FTD_WINDOW, symbols={e.ticker for e in index.eras()})


@pytest.fixture(scope="module")
def eras(index, ftd):
    return {e.key: e for e in refine_eras(index.eras(), ftd)}


@pytest.fixture
def frequency(monkeypatch):
    """The 8-K frequency tier answers with the rank EDGAR gave (the fixture's),
    or with the rank a test sets for a ticker (`frequency["UAG"] = [...]`)."""
    given: dict[str, list] = {}
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: [tuple(x) for x in given.get(t, DATA["frequency"].get(f"{t}|{d}", []))])
    return given


def _infer(eras, ftd, keys, resolved=None, edgar=None):
    """Pass 2 over the eras `keys`, the others' pass-1 CIKs given in `resolved`:
    {era key: (CIK, source)} for each era it answered."""
    chosen = [eras[k] for k in keys]
    last_seen = {e.key: era_last_seen(e, ftd) for e in chosen}
    ciks = {e.key: (resolved or {}).get(e.key) for e in chosen}
    got = TickerResolver(edgar or _Edgar()).infer_issuers(chosen, ftd, last_seen, ciks)
    return {k: (v.cik, v.source) for k, v in got.items()}


def test_the_fixture_eras_and_last_sightings_are_the_real_ones(eras, ftd):
    seen = {k: era_last_seen(e, ftd) for k, e in eras.items() if e.ticker in {"KORS", "NU", "LUK", "LMCA"}}
    assert seen == {"KORS@2012-06-29": "2015-08-03", "KORS@2014-12-31": "2019-01-03",
                    "LMCA@2012-06-29": "2013-01-16", "LMCA@2013-06-28": "2016-04-18",
                    "LUK@2008-01-16": "2010-07-13", "LUK@2012-06-29": "2015-08-04", "LUK@2014-12-31": "2018-05-25",
                    "NU@2008-01-16": "2015-02-20", "NU@2023-06-30": "2026-08-31", "NU@2026-06-30": "2026-08-31"}


# --- 1a: each era is looked up under its own name --------------------------------

def _ctx(resolver, edgar=None):
    clients = Clients(edgar=edgar or _Edgar(), resolver=resolver, classifier=None, figi=None, ftd_client=None,
                      as_of=FTD_WINDOW[1])
    return _RunContext(clients, FTD_WINDOW[1], lambda *a: None, 1, run_manifest.StageMeter(lambda *a: None))


def test_each_era_is_looked_up_under_its_own_name(index, eras, ftd):
    """KORS@2012's FTD rows (its CUSIP's, shared with KORS@2014) run to
    2015-08-03, past its last observation and after KORS@2014's first: the
    observation lookup would give it KORS@2014's name."""
    calls = []

    class Spy(TickerResolver):
        def resolve(self, ticker, observed_date=None, **kw):
            calls.append((ticker, observed_date, kw.get("name")))
            return super().resolve(ticker, observed_date, **kw)

    spy = Spy(_Edgar(), observed_names=index.name_on)
    pipeline._resolve_issuers(_ctx(spy), [eras["KORS@2012-06-29"], eras["KORS@2014-12-31"]], ftd)
    assert index.name_on("KORS", "2015-08-03") == "MICHAEL KORS HOLDINGS LTD"
    assert calls == [("KORS", "2015-08-03", "CAPRI HOLDINGS LTD"), ("KORS", "2019-01-03", "MICHAEL KORS HOLDINGS LTD")]


ALTAIR_MAP = {"ALTR": {"cik_str": 1701732, "ticker": "ALTR", "title": "Altair Engineering Inc."}}


def test_a_lookup_is_checked_against_the_name_it_is_given_not_the_nearest_observation():
    """The observation lookup can land on another era's name (an era's FTD rows
    run past its last observation, toward the next era's). `name=` is the era's
    own: SEC's ticker map holder Altair is taken for an Altair era, and refused
    when the nearest observation's name is Altera's."""
    r = TickerResolver(_Edgar(tickers=ALTAIR_MAP), observed_names=lambda t, d=None: "ALTERA CORP")
    assert r.resolve("ALTR", "2020-06-30").cik is None
    assert r.resolve("ALTR", "2020-06-30", name="ALTAIR ENGINEERING INC CLASS A").cik == 1701732
    assert r.resolve("ALTR", "2020-06-30", name="ALTERA CORP").cik is None


# --- 1b: the name search ranks its candidates by their EDGAR names -------------------

def test_the_name_search_drops_a_nameless_hit_and_takes_the_company_edgar_names_so():
    """EDGAR's company search matches former names: MICHAEL KORS HOLDINGS LTD
    finds Capri Holdings (1530721, Michael Kors Holdings Ltd until 2018-12-21).
    The variant MICHAEL matches many companies; EDGAR then lists them with no
    name, and the first (Michael Baker, 9263) used to win on its missing date.
    A nameless hit is no candidate."""
    res = TickerResolver(_Edgar()).resolve("KORS", "2019-01-03", name="MICHAEL KORS HOLDINGS LTD")
    assert (res.cik, res.source) == (1530721, "name_search")


def test_the_name_search_ranks_the_company_that_carried_the_name_first():
    """ARCP, American Realty Capital Properties, is VEREIT (1507385) today. The
    variant AMERICAN REALTY CAPITAL answers with a nameless multi-company hit
    whose first CIK (1561032, then American Realty Capital Healthcare Trust II)
    shares three words with the name and passes the date checks: it took ARCP
    (and HTA) before. Ranked by EDGAR names, VEREIT's former name comes first."""
    res = TickerResolver(_Edgar()).resolve("ARCP", "2015-07-31", name="AMERICAN REALTY CAPITAL PROPERTIES")
    assert (res.cik, res.source) == (1507385, "name_search")


def test_a_candidate_below_the_first_needs_an_edgar_name_that_agrees():
    """DPS@2012 carries a name the snapshots backfilled, KEURIG DR PEPPER INC; in
    2015 the company was Dr Pepper Snapple Group (1418135, Keurig Dr Pepper since
    2018), which the date check refuses. The search's next candidate, Keurig
    Green Mountain (909954), shares one word and filed a Form 25 within 540 days
    (its 2016 buyout), which the loose check alone would accept. A candidate
    below the first is checked only when one of its EDGAR names agrees with the
    expected name."""
    assert TickerResolver(_Edgar()).resolve("DPS", "2015-08-03", name="KEURIG DR PEPPER INC").cik is None


NU_MAP = {"NU": {"cik_str": 1691493, "ticker": "NU", "title": "Nu Holdings Ltd."}}


def test_a_recycled_tickers_holder_is_refused_and_the_name_search_finds_the_old_issuer():
    """NU was Northeast Utilities (72741, Eversource Energy since 2015-04-29);
    SEC's ticker map now gives Nu Holdings (1691493, first filing 2016), which
    did not exist then. The company search's nameless NORTHEAST hit (745651)
    no longer beats the named 72741."""
    res = TickerResolver(_Edgar(tickers=NU_MAP)).resolve("NU", "2015-02-20", name="NORTHEAST UTILITIES")
    assert (res.cik, res.source) == (72741, "name_search")


def test_todays_holder_found_by_the_name_search_is_refused_for_an_old_date():
    """ALTR was Altera (768251) until Intel bought it in 2015, Altair (1701732)
    from 2017. A company search answering with Altair never gives it Altera's
    era: it shares no word with ALTERA CORP and did not exist in 2015."""
    altair = {"cik": 1701732, "name": "Altair Engineering Inc.", "form": "25-NSE", "filing_date": "2025-03-26"}
    altera = {"cik": 768251, "name": "ALTERA CORP", "form": "25-NSE", "filing_date": "2015-12-28"}
    both = _Edgar(tickers=ALTAIR_MAP, search={"ALTERA CORP|25-NSE": [altair, altera]})
    assert TickerResolver(both).resolve("ALTR", "2015-12-29", name="ALTERA CORP").cik == 768251
    only_altair = _Edgar(tickers=ALTAIR_MAP, search={"ALTERA CORP|25-NSE": [altair]})
    assert TickerResolver(only_altair).resolve("ALTR", "2015-12-29", name="ALTERA CORP").cik is None


# --- 1c, fix B: the 8-K frequency rank, through guard G --------------------------------

def test_a_renamed_issuer_that_kept_filing_is_found_by_its_8k_frequency(eras, ftd, frequency):
    """KORS@2014: Capri Holdings (1530721) leads the rank of 8-Ks naming KORS
    before 2019-01-03, but kept filing 10-Ks, so the strict check rejects it. It
    existed by the era's first fails row, carried a name matching every row's
    description (MICHAEL KORS HLDGS LTD ORD SHS) then, is the only candidate that
    did, carried the era's name at its last sighting, and filed within 400 days."""
    assert _infer(eras, ftd, ["KORS@2014-12-31"]) == {"KORS@2014-12-31": (1530721, "efts_frequency_renamed")}


def test_two_candidates_passing_the_guard_give_no_answer(eras, ftd, frequency):
    """GGP@2014 (General Growth Properties, 1496048): Seritage Growth Properties
    (1628063, first filing 2014-12-19) also ranks, existed by the era's first row,
    and its name shares GROWTH PROPERTIES with every row's description."""
    assert [c for c, _ in DATA["frequency"]["GGP|2017-01-27"][:2]] == [1496048, 1628063]
    assert _infer(eras, ftd, ["GGP@2014-12-31"]) == {}


def test_a_candidate_founded_after_the_eras_first_row_is_refused(eras, ftd, frequency):
    """BWC@2012 (Babcock & Wilcox Co, now BWX Technologies, 1486957): its 2015
    spin-off Babcock & Wilcox Enterprises (1630805, first filing 2015-03-16) also
    ranks; offered alone, it is refused."""
    assert _infer(eras, ftd, ["BWC@2012-06-29"]) == {"BWC@2012-06-29": (1486957, "efts_frequency_renamed")}
    frequency["BWC"] = [(1630805, "Babcock & Wilcox Enterprises, Inc.")]
    assert _infer(eras, ftd, ["BWC@2012-06-29"]) == {}


def test_rows_of_another_security_under_the_ticker_refuse_the_issuer(eras, ftd, frequency):
    """UAG@2008 (United Auto Group, now Penske Automotive Group, 1019849): the
    fails rows under UAG are an exchange-traded note's (E-TRACS UBS BLOOMBERG
    CMCI AGR), which no name of Penske's matches."""
    frequency["UAG"] = [(1019849, "PENSKE AUTOMOTIVE GROUP, INC.")]
    assert _infer(eras, ftd, ["UAG@2008-01-16"]) == {}


def test_a_candidate_with_no_filing_within_400_days_of_the_last_sighting_is_refused(eras, ftd, frequency):
    issuers = dict(DATA["issuers"])
    capri = issuers["1530721"]
    issuers["1530721"] = {**capri, "filings": [f for f in capri["filings"] if f[1] < "2017-12-01"]}
    assert _infer(eras, ftd, ["KORS@2014-12-31"], edgar=_Edgar(issuers)) == {}


# --- 1c, fix C: CUSIP handoffs -----------------------------------------------------------

def test_cusip_handoffs_link_a_shared_cusip_and_a_cusip_switch(eras, ftd):
    """KORS -> CPRI (Michael Kors Holdings renamed Capri Holdings, 2018-12-31: the
    old CUSIP's last KORS row 2019-01-03, the new one's first row 2019-01-02), NU
    -> ES (Northeast Utilities -> Eversource Energy), LUK -> JEF (Leucadia ->
    Jefferies Financial Group); the two KORS eras share one CUSIP. NU's later
    holder, Nu Holdings, starts trading years after Northeast Utilities' CUSIP
    ended: no link."""
    links = {(h.era_key, h.to_key): h for h in cusip_handoffs(list(eras.values()), ftd)}
    got = {k: (links[k].kind, links[k].cusip, links[k].new_cusip, links[k].day) for k in [
        ("KORS@2014-12-31", "CPRI@2018-12-31"), ("KORS@2012-06-29", "CPRI@2018-12-31"),
        ("KORS@2012-06-29", "KORS@2014-12-31"), ("NU@2008-01-16", "ES@2015-06-30"),
        ("LUK@2014-12-31", "JEF@2018-06-30")] if k in links}
    assert got == {
        ("KORS@2014-12-31", "CPRI@2018-12-31"): ("cusip_handoff", "G60754101", "G1890L107", "2019-01-02"),
        ("KORS@2012-06-29", "CPRI@2018-12-31"): ("cusip_handoff", "G60754101", "G1890L107", "2019-01-02"),
        ("KORS@2012-06-29", "KORS@2014-12-31"): ("shared_cusip", "G60754101", "", ""),
        ("NU@2008-01-16", "ES@2015-06-30"): ("cusip_handoff", "664397106", "30040W108", "2015-02-19"),
        ("LUK@2014-12-31", "JEF@2018-06-30"): ("cusip_handoff", "527288104", "47233W109", "2018-05-24")}
    assert not [k for k in links if k[0] == "NU@2008-01-16" and k[1].startswith("NU@")]


RESOLVED = {"CPRI@2018-12-31": 1530721, "ES@2012-06-29": 72741, "ES@2015-06-30": 72741, "JEF@2008-01-16": 1084580,
            "JEF@2018-06-30": 96223, "NU@2023-06-30": 1691493, "NU@2026-06-30": 1691493, "LMCA@2013-06-28": 1560385,
            "BWXT@2015-12-31": 1486957, "BW@2015-12-31": 1630805, "VIAV@2015-12-31": 912093,
            "LITE@2015-12-31": 1633978}      # the committed run's first-pass answers for these eras


@pytest.fixture
def no_frequency(frequency):
    """No 8-K frequency candidates: fix C alone answers."""
    for t in ("KORS", "NU", "LUK", "LMCA", "BWC", "JDSU", "GGP", "UAG"):
        frequency[t] = []
    return frequency


def test_a_ticker_change_hands_the_new_tickers_issuer_to_the_old_cusips_eras(eras, ftd, no_frequency):
    """The switch needs the issuer of the new CUSIP's era to have carried, within
    90 days of the switch, a former name matching the old CUSIP's rows (Michael
    Kors Holdings Ltd until 2018-12-21, NORTHEAST UTILITIES until 2015-04-29,
    LEUCADIA NATIONAL CORP until 2018-05-15)."""
    got = _infer(eras, ftd, list(eras), RESOLVED)
    assert {k: got.get(k) for k in ["KORS@2012-06-29", "KORS@2014-12-31", "NU@2008-01-16", "LUK@2008-01-16",
                                    "LUK@2012-06-29", "LUK@2014-12-31"]} == {
        "KORS@2012-06-29": (1530721, "cusip_handoff"), "KORS@2014-12-31": (1530721, "cusip_handoff"),
        "NU@2008-01-16": (72741, "cusip_handoff"),      # not Nu Holdings
        "LUK@2008-01-16": (96223, "cusip_handoff"), "LUK@2012-06-29": (96223, "cusip_handoff"),
        "LUK@2014-12-31": (96223, "cusip_handoff")}


def test_an_era_sharing_a_cusip_with_a_resolved_era_takes_its_issuer(eras, ftd, no_frequency):
    """KORS@2012 (named CAPRI HOLDINGS LTD by the snapshots) shares its CUSIP with
    KORS@2014, which the name search resolves to Capri Holdings."""
    got = _infer(eras, ftd, list(eras), {**RESOLVED, "KORS@2014-12-31": 1530721})
    assert got["KORS@2012-06-29"] == (1530721, "shared_cusip")


def test_a_spin_off_starting_as_the_parents_cusip_ends_takes_nothing(eras, ftd, no_frequency):
    """Babcock & Wilcox Co (BWC) became BWX Technologies (BWXT) as it spun off
    Babcock & Wilcox Enterprises (BW); JDS Uniphase (JDSU) became Viavi (VIAV) as
    it spun off Lumentum (LITE). All four new CUSIPs start within a week of the
    old one's end; the spin-offs carried no former name, and were founded after
    the old rows began."""
    got = _infer(eras, ftd, list(eras), RESOLVED)
    assert (got.get("BWC@2012-06-29"), got.get("JDSU@2008-01-16")) == \
        ((1486957, "cusip_handoff"), (912093, "cusip_handoff"))
    spin_offs_only = {k: v for k, v in RESOLVED.items() if k not in ("BWXT@2015-12-31", "VIAV@2015-12-31")}
    got = _infer(eras, ftd, list(eras), spin_offs_only)
    assert "BWC@2012-06-29" not in got and "JDSU@2008-01-16" not in got


def test_a_switch_to_a_company_founded_after_the_eras_rows_is_refused(eras, ftd, no_frequency):
    """LMCA@2012 is the Liberty Media that became Starz in January 2013; LMCA then
    passed to its spin-off Liberty Spinco (1560385, renamed Liberty Media), a new
    CUSIP within a week and a former name (Liberty Spinco) matching LIBERTY MEDIA
    CORP NEW LIBERTY. Its first filing (2012-10-19) postdates LMCA@2012's first row."""
    assert "LMCA@2012-06-29" not in _infer(eras, ftd, list(eras), RESOLVED)


class _NoFigi:
    """OpenFIGI with no US line for anything."""

    def map(self, jobs):
        return [{"data": []} for _ in jobs]

    def filter(self, query, **kw):
        return []


def test_the_second_pass_answer_is_used_flagged_and_never_saved(eras, ftd, tmp_path):
    """KORS@2012 under its own name finds nothing (Capri Holdings was Michael Kors
    Holdings then); the second pass gives it KORS@2014's issuer through their
    shared CUSIP. The answer depends on the run's other eras, so the memo file
    holds only first-pass answers, and the era carries the info flag
    issuer_inferred, which says how."""
    kors = [eras["KORS@2012-06-29"], eras["KORS@2014-12-31"], eras["CPRI@2018-12-31"]]
    edgar = _Edgar(tickers={"CPRI": {"cik_str": 1530721, "ticker": "CPRI", "title": "Capri Holdings Ltd"}})
    resolver = TickerResolver(edgar, cache_path=tmp_path / "res.json", batch_writes=True)
    ctx = _ctx(resolver, edgar)
    answers = pipeline._resolve_issuers(ctx, kors, ftd)
    res = answers.resolutions
    assert {k: (r.cik, r.source) for k, r in res.items()} == {
        "KORS@2012-06-29": (1530721, "shared_cusip"), "KORS@2014-12-31": (1530721, "name_search"),
        "CPRI@2018-12-31": (1530721, "company_tickers")}
    assert answers.issuers["KORS@2012-06-29"].cik == 1530721
    saved = json.loads((tmp_path / "res.json").read_text())["entries"]
    assert sorted(saved) == ["CPRI|2026-02-04|CAPRI HOLDINGS LTD", "KORS|2019-01-03|MICHAEL KORS HOLDINGS LTD"]
    ctx.clients.figi = _NoFigi()
    _, _, review = pipeline._resolve_securities(ctx, kors, {e.key: e for e in kors}, ftd, answers)
    inferred = [(i.ticker, i.cik, i.reason) for i in review if i.flag == "issuer_inferred"]
    assert inferred == [("KORS", 1530721, "KORS@2012-06-29 CAPRI HOLDINGS LTD: issuer 1530721 by shared_cusip: "
                                          "shares CUSIP G60754101 with KORS@2014-12-31")]


def test_fails_rows_with_no_word_to_compare_confirm_no_issuer(eras, ftd, frequency):
    """2U's fails rows read 2U INC COM STK: nothing is left once the security words
    go. Its CUSIP last traded 2024-06-12, days after QXO's new CUSIP began
    (SilverSun Technologies renamed QXO on 2024-06-06), and GoDaddy, founded
    before the rows began, ranks among the 8-Ks naming TWOU. Rows that name no
    issuer confirm none: neither the switch nor the frequency rank answers."""
    got = _infer(eras, ftd, list(eras), {**RESOLVED, "QXO@2025-06-30": 1236275})
    assert "TWOU@2018-06-30" not in got


def test_an_era_linked_to_two_issuers_takes_neither(eras, ftd, no_frequency):
    issuers = {**DATA["issuers"], "999999": DATA["issuers"]["1530721"]}   # a second issuer passing the guard
    got = _infer(eras, ftd, list(eras), {**RESOLVED, "KORS@2014-12-31": 1530721, "CPRI@2018-12-31": 999999},
                 edgar=_Edgar(issuers))
    assert "KORS@2012-06-29" not in got

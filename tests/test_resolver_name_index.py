"""The ticker resolver's name tier over SEC's cik-lookup-data.txt (cik-lookup plan, Task 3):
candidates from the local index instead of the live company search."""
import json

import pytest
import requests

from delist_detection.sources.cik_lookup import CikNameIndex
from delist_detection.sources.edgar import EdgarBlocked, EdgarSubmission
from delist_detection.identity.ticker_resolver import TickerResolver


def _f(acc, form, d):
    return EdgarSubmission(acc, form, d, "", "", "x.htm")


class _Edgar:
    """Companies by CIK; the live company search is counted, answering by prefix."""

    def __init__(self, companies, atom=None):
        self.companies, self.atom, self.searches, self.read = companies, atom or {}, [], []

    def company_tickers(self):
        return {}

    def submissions(self, cik, fresh_after=None):
        c = self.companies.get(int(cik))
        if not c:
            return {"__not_found__": True}
        self.read.append(int(cik))
        recent = {"form": [f.form for f in c[2]], "filingDate": [f.filing_date for f in c[2]]}
        return {"name": c[0], "formerNames": c[1], "sic": "", "filings": {"recent": recent}}

    def recent_filings(self, cik):
        c = self.companies.get(int(cik))
        return list(c[2]) if c else []

    def company_search_atom(self, company, form_type="25-NSE"):
        self.searches.append((company, form_type))
        for prefix, cik in self.atom.items():
            if company.upper().startswith(prefix):
                return [{"cik": cik, "name": self.companies[cik][0], "form": "", "filing_date": ""}]
        return []

    def fetch_filing_text(self, *a):
        return ""


AVANOS = (1606498, ("AVANOS MEDICAL, INC.",
                    [{"name": "Halyard Health, Inc.", "from": "2014-06-02T04:00:00.000Z",
                      "to": "2018-06-28T04:00:00.000Z"}],
                    [_f("K1", "10-K", "2018-02-23"), _f("E1", "8-K", "2018-07-02")]))


def _index(*lines):
    return CikNameIndex.from_text("\n".join(lines) + "\n")


def test_the_name_tier_resolves_through_the_index_and_sends_no_company_search():
    """Halyard Health (HYH), renamed Avanos in 2018: the index lists the former
    name under CIK 1606498."""
    e = _Edgar(dict([AVANOS]))
    idx = _index("AVANOS MEDICAL, INC.:0001606498:", "HALYARD HEALTH, INC.:0001606498:",
                 "HALYARD CAPITAL FUND LP:0001999999:")
    r = TickerResolver(e, observed_names=lambda t, d=None: "HALYARD HEALTH INC", name_index=idx)
    res = r.resolve("HYH", "2018-06-29")
    assert (res.cik, res.source) == (1606498, "name_search") and e.searches == []


def test_the_live_searchs_form_filter_picks_the_one_filer():
    """The file has no forms; the live search asked for Form 25 filers first.
    Of the matches, the one company that filed a 25-NSE is the candidate: not
    the partnership or the individual sharing the name."""
    reit = (1037540, ("BOSTON PROPERTIES INC", [], [_f("R1", "10-K", "2012-02-28"), _f("R2", "25-NSE", "2012-05-01")]))
    lp = (1043121, ("BOSTON PROPERTIES LTD PARTNERSHIP", [], [_f("P1", "10-K", "2012-02-28")]))
    idx = _index("BOSTON PROPERTIES INC:0001037540:", "BOSTON PROPERTIES LTD PARTNERSHIP:0001043121:")
    r = TickerResolver(_Edgar(dict([reit, lp])), name_index=idx)
    assert r._index_candidates(idx, "BOSTON PROPERTIES INC", "2012-06-29") == {
        1037540: ("BOSTON PROPERTIES INC", 59)}                      # its 25-NSE, 59 days before the date


def test_of_two_filers_under_one_form_the_one_named_exactly_the_spelling_is_the_candidate():
    """EDGAR names no company when several match, except the one whose name is
    the query (MOTOROLA INC in 2010, not Motorola Mobility, which filed its own
    Form 25 later)."""
    a = (1, ("ACME CORP", [], [_f("A", "25-NSE", "2012-05-01")]))
    b = (2, ("ACME CORP DEL", [], [_f("B", "25-NSE", "2011-05-01")]))
    idx = _index("ACME CORP:0000000001:", "ACME CORP DEL:0000000002:")
    r = TickerResolver(_Edgar(dict([a, b])), name_index=idx)
    assert r._index_candidates(idx, "ACME CORP", "2012-06-29") == {1: ("ACME CORP", 59)}
    c = (3, ("ACME CORP DELAWARE", [], [_f("C", "25-NSE", "2012-04-01")]))
    idx = _index("ACME CORP DEL:0000000002:", "ACME CORP DELAWARE:0000000003:")
    r = TickerResolver(_Edgar(dict([b, c])), name_index=idx)
    assert r._index_candidates(idx, "ACME CO", "2012-06-29") == {}   # neither is named by the query: no candidate


def test_a_name_exactly_one_companys_is_the_candidate_whatever_it_filed():
    """NORTHEAST UTILITIES (NU, 2008-2015) never filed a Form 25; EDGAR's search
    answered its exact name with the company. A broad spelling of it
    (NORTHEAST) matches dozens of companies and names none: Northeast Bancorp's
    Form 25 must not win (the full run of 2026-09-29 took it)."""
    nu = (72741, ("EVERSOURCE ENERGY", [], [_f("N", "10-K", "2015-02-20")]))
    bank = (811831, ("NORTHEAST BANCORP /ME/", [], [_f("B", "25-NSE", "2014-12-01")]))
    lines = ["NORTHEAST UTILITIES:0000072741:", "NORTHEAST BANCORP /ME/:0000811831:"]
    lines += [f"NORTHEAST FUND {i} LP:{9000 + i:010d}:" for i in range(12)]
    idx = _index(*lines)
    r = TickerResolver(_Edgar(dict([nu, bank])), name_index=idx)
    assert r._index_candidates(idx, "NORTHEAST UTILITIES", "2015-02-20") == {72741: ("NORTHEAST UTILITIES", 0)}


def test_with_no_filer_a_spelling_matching_one_cik_gives_it_and_a_broad_one_reads_nothing():
    solo = (7, ("SOLO WIDGETS INC", [], [_f("S", "10-K", "2012-02-01")]))
    r = TickerResolver(_Edgar(dict([solo])), name_index=_index("SOLO WIDGETS INC:0000000007:"))
    assert r._index_candidates(r._index(), "SOLO WIDGETS", "2012-06-29") == {7: ("SOLO WIDGETS INC", 149)}
    many = [f"MANY THINGS FUND {i} LP:{9000 + i:010d}:" for i in range(15)]
    e = _Edgar({9000 + i: (f"MANY THINGS FUND {i} LP", [], []) for i in range(15)})
    r = TickerResolver(e, name_index=_index(*many))
    assert r._index_candidates(r._index(), "MANY THINGS", "2012-06-29") == {}
    assert r._index_candidates(r._index(), "MANY THINGS UNLIMITED", "2012-06-29") == {}
    assert len(set(e.read)) == 10         # MANY THINGS: the top INDEX_PROBE read, no filer among 15: no candidate
                                          # MANY THINGS UNLIMITED: no match carries every word, nothing read


def test_of_several_companies_under_one_name_the_one_that_carried_it_on_the_date_is_the_candidate():
    """TCF FINANCIAL CORP is two CIKs' name: old TCF (814184) until its 2019
    merger, then Chemical Financial (19612), renamed TCF. Both filed a 25-NSE.
    In 2012 only old TCF carried the name (the full run of 2026-09-29 found no
    issuer for TCF@2012 and lost the era)."""
    old = (814184, ("TCF FINANCIAL CORP", [], [_f("T1", "10-K", "2014-02-14"), _f("T2", "25-NSE", "2019-08-01")]))
    new = (19612, ("TCF FINANCIAL CORP", [{"name": "CHEMICAL FINANCIAL CORP", "from": "1995-08-10T00:00:00.000Z",
                                           "to": "2019-08-01T00:00:00.000Z"}],
                   [_f("C1", "10-K", "2015-06-23"), _f("C2", "25-NSE", "2021-06-09")]))
    idx = _index("TCF FINANCIAL CORP:0000814184:", "TCF FINANCIAL CORP:0000019612:",
                 "CHEMICAL FINANCIAL CORP:0000019612:")
    r = TickerResolver(_Edgar(dict([old, new])), name_index=idx)
    assert list(r._index_candidates(idx, "TCF FINANCIAL CORP", "2014-06-30")) == [814184]


def test_a_dead_holder_of_the_exact_name_loses_to_the_form25_filer_that_matches_it():
    """WACHOVIA CORP is exactly one CIK's name (104019, the pre-2001 Wachovia);
    the live search's Form 25 filter answered it with WACHOVIA CORP NEW (36995,
    First Union renamed), the one that filed. The run took 104019 and lost
    Wachovia's 2008 merger."""
    dead = (104019, ("WACHOVIA CORP", [], [_f("D1", "10-K", "2002-02-19")]))
    live = (36995, ("WACHOVIA CORP NEW", [{"name": "FIRST UNION CORP", "from": "1994-02-11T00:00:00.000Z",
                                          "to": "2001-09-07T00:00:00.000Z"}],
                    [_f("W1", "10-K", "2008-02-28"), _f("W2", "25-NSE", "2008-12-31")]))
    idx = _index("WACHOVIA CORP:0000104019:", "WACHOVIA CORP NEW:0000036995:", "FIRST UNION CORP:0000036995:")
    r = TickerResolver(_Edgar(dict([dead, live])), name_index=idx)
    assert list(r._index_candidates(idx, "WACHOVIA CORP", "2009-06-08")) == [36995]


def test_a_broad_spelling_reads_the_matches_carrying_every_word_of_the_name():
    """MEDCO HEALTH SOLUTIONS matches 17 CIKs, most of them Medco's pharmacy
    subsidiaries; the company is the one that filed a Form 25 (the run found no
    issuer and lost Medco's 2012 merger)."""
    medco = (1170650, ("MEDCO HEALTH SOLUTIONS INC", [], [_f("M1", "10-K", "2008-02-20"), _f("M2", "25", "2012-04-17")]))
    subs = {1556600 + i: (f"MEDCO HEALTH SOLUTIONS OF CITY {i} LLC", [], []) for i in range(16)}
    idx = _index("MEDCO HEALTH SOLUTIONS INC:0001170650:",
                 *(f"{n[0]}:{c:010d}:" for c, n in subs.items()))
    r = TickerResolver(_Edgar({**subs, **dict([medco])}), name_index=idx)
    assert list(r._index_candidates(idx, "MEDCO HEALTH SOLUTIONS", "2009-06-08")) == [1170650]


def test_a_fund_sharing_the_prefix_loses_to_the_company_whose_form25_fits():
    """The file lists funds and individuals too: the checks after the search
    (existed by the date, a Form 25 near it) keep the company."""
    widgets = (777, ("ACME HOLDINGS WIDGETS INC", [], [_f("W1", "10-K", "2012-03-01"),
                                                        _f("W2", "25-NSE", "2012-06-20")]))
    fund = (9001, ("ACME HOLDINGS FUND LP", [], [_f("F1", "D", "2015-01-05")]))
    idx = _index("ACME HOLDINGS FUND LP:0000009001:", "ACME HOLDINGS WIDGETS INC:0000000777:")
    r = TickerResolver(_Edgar(dict([widgets, fund])), name_lookup=lambda t, d=None: "ACME HOLDINGS", name_index=idx)
    assert r.resolve("ACW", "2012-06-29").cik == 777


def test_without_an_index_the_live_company_search_runs_as_before():
    e = _Edgar(dict([AVANOS]), {"HALYARD": 1606498})
    r = TickerResolver(e, observed_names=lambda t, d=None: "HALYARD HEALTH INC")
    assert r.resolve("HYH", "2018-06-29").cik == 1606498 and e.searches


def test_an_index_that_cannot_load_falls_back_to_the_live_search_and_a_refusal_stops():
    e = _Edgar(dict([AVANOS]), {"HALYARD": 1606498})
    calls = []

    def down():
        calls.append(1)
        raise requests.ConnectionError("SEC down")

    r = TickerResolver(e, observed_names=lambda t, d=None: "HALYARD HEALTH INC", name_index=down)
    assert r.resolve("HYH", "2018-06-29").cik == 1606498 and e.searches
    r.resolve("HYH", "2018-12-31")
    assert calls == [1]                                   # tried once per run

    def refused():
        raise EdgarBlocked("403")

    with pytest.raises(EdgarBlocked):
        TickerResolver(e, observed_names=lambda t, d=None: "HALYARD HEALTH INC",
                       name_index=refused).resolve("HYH", "2018-06-29")


def test_a_shadow_shares_the_index():
    idx = _index("HALYARD HEALTH, INC.:0001606498:")
    r = TickerResolver(_Edgar(dict([AVANOS])), observed_names=lambda t, d=None: "HALYARD HEALTH INC",
                       name_index=idx)
    assert r.shadow().resolve("HYH", "2018-06-29").cik == 1606498


def test_a_name_carried_before_the_date_counts_a_snapshot_lags_renames():
    """CHICAGO MERCANTILE HLDGS in 2009: CME Group's name until 2007, while the
    exchange subsidiary still carried CHICAGO MERCANTILE EXCHANGE INC. Both had
    carried the spelling, neither filed a Form 25: no candidate, rather than the
    subsidiary (the run of 2026-09-29 took it and made CME a placeholder)."""
    group = (1156375, ("CME GROUP INC.", [{"name": "CHICAGO MERCANTILE EXCHANGE HOLDINGS INC",
                                           "from": "2001-08-15T00:00:00.000Z", "to": "2007-07-12T00:00:00.000Z"}],
                       [_f("G1", "10-K", "2009-02-27")]))
    sub = (1103945, ("CHICAGO MERCANTILE EXCHANGE INC", [], [_f("S1", "10-K", "2002-03-01")]))
    idx = _index("CHICAGO MERCANTILE EXCHANGE HOLDINGS INC:0001156375:", "CME GROUP INC.:0001156375:",
                 "CHICAGO MERCANTILE EXCHANGE INC:0001103945:")
    r = TickerResolver(_Edgar(dict([group, sub])), name_index=idx)
    assert r._index_candidates(idx, "CHICAGO MERCANTILE HLDGS", "2009-06-08") == {}


def test_a_cut_off_spelling_that_drops_a_word_of_the_name_reads_nothing():
    """S&P GLOBAL INC's spelling S P matches hundreds of S&P funds; one sharing
    GLOBAL filed a Form 25. It is no candidate (the run took an S&P trust for
    MHFI)."""
    trust = (1280936, ("S&P QUALITY RANKINGS GLOBAL EQUITY MANAGED TRUST", [], [_f("T", "25", "2015-01-14")]))
    funds = {9000 + i: (f"S&P FUND {i} TRUST", [], []) for i in range(12)}
    idx = _index("S&P QUALITY RANKINGS GLOBAL EQUITY MANAGED TRUST:0001280936:",
                 *(f"{n[0]}:{c:010d}:" for c, n in funds.items()))
    r = TickerResolver(_Edgar({**funds, **dict([trust])}), name_index=idx)
    assert r._index_candidates(idx, "S&P GLOBAL INC", "2015-08-04") == {}


def test_of_several_filers_the_one_carrying_exactly_the_names_words_then_the_name_on_the_date():
    """ANHEUSER BUSCH COS INC (BUD, 2009): InBev's entities match the spelling
    and filed too, but carry INBEV. ALBERTO CULVER CO (ACV, 2010): the old
    company (renamed New Alberto-Culver in 2006) and the spin-off both carried
    the exact name and filed; the spin-off carried it on the date."""
    bud = (310569, ("ANHEUSER-BUSCH COMPANIES, LLC",
                    [{"name": "ANHEUSER-BUSCH COMPANIES, INC.", "from": "2004-05-07T00:00:00.000Z",
                      "to": "2011-07-12T00:00:00.000Z"}], [_f("B", "25-NSE", "2008-11-20")]))
    abi = (1140467, ("ANHEUSER-BUSCH INBEV S.A.", [], [_f("I", "25", "2009-05-01")]))
    idx = _index("ANHEUSER-BUSCH COMPANIES, INC.:0000310569:", "ANHEUSER-BUSCH INBEV S.A.:0001140467:")
    r = TickerResolver(_Edgar(dict([bud, abi])), name_index=idx)
    assert list(r._index_candidates(idx, "ANHEUSER BUSCH COS INC", "2009-06-08")) == [310569]
    old = (3327, ("New Alberto-Culver LLC", [{"name": "ALBERTO CULVER CO", "from": "1994-01-20T00:00:00.000Z",
                                             "to": "2006-11-29T00:00:00.000Z"}], [_f("O", "25-NSE", "2006-11-17")]))
    new = (1368457, ("ALBERTO CULVER CO", [], [_f("N", "10-K", "2009-11-20"), _f("M", "25-NSE", "2011-05-10")]))
    idx = _index("ALBERTO CULVER CO:0000003327:", "ALBERTO CULVER CO:0001368457:")
    r = TickerResolver(_Edgar(dict([old, new])), name_index=idx)
    assert list(r._index_candidates(idx, "ALBERTO CULVER CO", "2010-07-09")) == [1368457]


def test_of_two_filers_one_the_query_does_not_name_is_no_candidate_whatever_the_date():
    """APTIV PLC in 2013: Delphi (1521332) took the name only in 2017, Aptiv
    Solutions (1193940) is another company; both filed. EDGAR's search named
    neither (the run of 20bdc19 put APTV 2012-13 on Aptiv Solutions)."""
    delphi = (1521332, ("Aptiv PLC", [{"name": "Delphi Automotive PLC", "from": "2011-05-19T00:00:00.000Z",
                                       "to": "2017-12-05T00:00:00.000Z"}], [_f("D", "25-NSE", "2024-12-20")]))
    other = (1193940, ("APTIV SOLUTIONS, INC.", [], [_f("A1", "10-K", "2011-03-01"), _f("A2", "15-12G", "2014-11-01"),
                                                    _f("A3", "25-NSE", "2014-10-20")]))
    idx = _index("APTIV PLC:0001521332:", "DELPHI AUTOMOTIVE PLC:0001521332:", "APTIV SOLUTIONS, INC.:0001193940:")
    r = TickerResolver(_Edgar(dict([delphi, other])), name_index=idx)
    assert 1193940 not in r._index_candidates(idx, "APTIV PLC", "2013-12-31")   # Delphi's: its checks reject it


def test_the_one_active_company_named_exactly_the_spelling_comes_before_the_form_filter():
    """FIRST REPUBLIC BANK (FRC, 2012-22) never filed a Form 25; Republic First
    Bancorp, named FIRST REPUBLIC BANCORP in 1996-97, did in 2023. The bank,
    filing near the date, is the company (the run of 20bdc19 took the other and
    gave First Republic its 2023 delisting), nor the First Republic Bank
    Merrill bought in 2007, which stopped filing then: a holder of the exact
    name that stopped years before is not the company (WACHOVIA CORP, above)."""
    bank = (1132979, ("FIRST REPUBLIC BANK", [], [_f("K1", "8-K", "2012-04-12"), _f("K2", "8-K", "2013-01-15")]))
    merrills = (1097256, ("FIRST REPUBLIC BANK", [], [_f("M1", "10-K", "2007-03-01"), _f("M2", "25", "2007-10-01")]))
    other = (834285, ("REPUBLIC FIRST BANCORP INC", [{"name": "FIRST REPUBLIC BANCORP INC /DE/",
                                                      "from": "1996-08-14T00:00:00.000Z", "to": "1997-03-28T00:00:00.000Z"}],
                      [_f("R1", "10-K", "2012-03-15"), _f("R2", "25-NSE", "2023-10-12")]))
    idx = _index("FIRST REPUBLIC BANK:0001132979:", "FIRST REPUBLIC BANK:0001097256:",
                 "FIRST REPUBLIC BANCORP INC /DE/:0000834285:", "REPUBLIC FIRST BANCORP INC:0000834285:")
    r = TickerResolver(_Edgar(dict([bank, merrills, other])), name_index=idx)
    found = r._index_candidates(idx, "FIRST REPUBLIC BANK", "2012-06-29")
    assert found[1132979] == ("FIRST REPUBLIC BANK", 78) and 834285 not in found
    assert r.resolve("FRC", "2012-06-29", name="FIRST REPUBLIC BANK").cik == 1132979


def test_a_later_name_a_snapshot_carries_back_still_names_its_one_active_holder():
    """DIVERSIFIED HEALTHCARE TRUST (DHC) observed in 2014: Senior Housing
    Properties Trust took that name in 2020. The one company of that exact
    name, filing near the date, is still the answer."""
    dhc = (1075415, ("DIVERSIFIED HEALTHCARE TRUST", [{"name": "SENIOR HOUSING PROPERTIES TRUST",
                                                       "from": "1998-12-01T00:00:00.000Z", "to": "2020-01-02T00:00:00.000Z"}],
                     [_f("S1", "10-K", "2014-02-28"), _f("S2", "10-Q", "2014-05-01")]))
    idx = _index("DIVERSIFIED HEALTHCARE TRUST:0001075415:", "SENIOR HOUSING PROPERTIES TRUST:0001075415:")
    r = TickerResolver(_Edgar(dict([dhc])), name_index=idx)
    assert list(r._index_candidates(idx, "DIVERSIFIED HEALTHCARE TRUST", "2014-06-30")) == [1075415]


# FB-004 part b: a remembered name-tier answer holds only while the name tier still names it
def _realogy(tmp_path, memo_cik):
    holdings = (1398987, ("Anywhere Real Estate Inc.",
                          [{"name": "REALOGY HOLDINGS CORP.", "from": "2013-05-01T00:00:00.000Z",
                            "to": "2022-05-27T00:00:00.000Z"}],
                          [_f("H0", "10-K", "2012-11-29"), _f("H1", "10-K", "2019-02-26"), _f("H2", "10-K", "2020-02-25")]))
    group = (1355001, ("Anywhere Real Estate Group LLC",
                       [{"name": "REALOGY GROUP LLC", "from": "2012-10-16T00:00:00.000Z",
                         "to": "2022-05-04T00:00:00.000Z"}],
                       [_f("G0", "10-K", "2012-02-26"), _f("G1", "10-K", "2019-02-26"), _f("G2", "10-K", "2020-02-25")]))
    idx = _index("REALOGY HOLDINGS CORP.:0001398987:", "REALOGY GROUP LLC:0001355001:",
                 "ANYWHERE REAL ESTATE INC.:0001398987:", "ANYWHERE REAL ESTATE GROUP LLC:0001355001:")
    cache = tmp_path / "res.json"
    cache.write_text(json.dumps({"__version__": 4, "entries": {
        "RLGY|2020-02-03|REALOGY HOLDINGS CORP": {"ticker": "RLGY", "cik": memo_cik, "name": "REALOGY HOLDINGS CORP",
                                                   "source": "name_search", "member_name": "REALOGY HOLDINGS CORP"}}}))
    return TickerResolver(_Edgar(dict([holdings, group])), cache_path=cache, name_index=idx), cache


def test_a_remembered_name_search_answer_the_index_no_longer_names_is_resolved_again(tmp_path):
    """RLGY/HOUS (Realogy Holdings, now Anywhere Real Estate Inc., CIK 1398987): an answer the retired live company
    search remembered, the subsidiary Realogy Group LLC (CIK 1355001, whose name agrees once HOLDINGS and GROUP are
    left out), outlived the rule that chose it and put the listed security's issuer on the LLC. The index names only
    the holding company for this name and date, so the memo is no answer."""
    r, cache = _realogy(tmp_path, 1355001)
    got = r.resolve("RLGY", "2020-02-03", name="REALOGY HOLDINGS CORP", since="2012-12-31", pin=None)
    assert (got.cik, got.source) == (1398987, "name_search")
    saved = json.loads(cache.read_text())["entries"]["RLGY|2020-02-03|REALOGY HOLDINGS CORP"]
    assert saved["cik"] == 1398987


def test_a_remembered_name_search_answer_the_index_still_names_is_kept(tmp_path):
    r, _ = _realogy(tmp_path, 1398987)
    got = r.resolve("RLGY", "2020-02-03", name="REALOGY HOLDINGS CORP", since="2012-12-31", pin=None)
    assert got.cik == 1398987 and r.edgar.searches == []


def test_without_an_index_a_remembered_name_search_answer_stands(tmp_path):
    r, cache = _realogy(tmp_path, 1355001)
    r2 = TickerResolver(r.edgar, cache_path=cache)
    assert r2.resolve("RLGY", "2020-02-03", name="REALOGY HOLDINGS CORP", since="2012-12-31", pin=None).cik == 1355001


# FB-004 part c: a remembered answer for a name two companies carried, and a name with no word of three letters
def _alberto(tmp_path, memo_cik):
    old = (3327, ("New Alberto-Culver LLC", [{"name": "ALBERTO CULVER CO", "from": "1994-01-20T00:00:00.000Z",
                                             "to": "2006-11-29T00:00:00.000Z"}],
                  [_f("O1", "25-NSE", "2006-11-17"), _f("O2", "8-K", "2010-06-01")]))
    new = (1368457, ("ALBERTO CULVER CO", [], [_f("N0", "10-K", "2007-11-20"), _f("N1", "10-K", "2009-11-20"),
                                              _f("N2", "25-NSE", "2011-05-11")]))
    idx = _index("ALBERTO CULVER CO:0000003327:", "NEW ALBERTO-CULVER LLC:0000003327:",
                 "ALBERTO-CULVER CO:0001368457:")
    cache = tmp_path / "res.json"
    cache.write_text(json.dumps({"__version__": 4, "entries": {
        "ACV|2010-07-09|ALBERTO CULVER CO": {"ticker": "ACV", "cik": memo_cik, "name": "New Alberto-Culver LLC",
                                             "source": "name_search", "member_name": "ALBERTO CULVER CO"}}}))
    return TickerResolver(_Edgar(dict([old, new])), cache_path=cache, name_index=idx)


def test_of_two_active_holders_of_a_name_the_one_that_carried_it_on_the_date_is_the_company(tmp_path):
    """ACV (Alberto-Culver, observed 2008-11): the old registrant, renamed New Alberto-Culver LLC in 2006, still filed
    in 2010 and had carried the name within CARRIED_YEARS; the 2006 spin-off carried it on the date. A remembered
    answer of the retired live search, the old registrant, no longer stands, and the 25-NSE of 2011 is the spin-off's."""
    r = _alberto(tmp_path, 3327)
    got = r.resolve("ACV", "2010-07-09", name="ALBERTO CULVER CO", since="2008-01-16", pin=None)
    assert (got.cik, got.source) == (1368457, "name_search")


def test_a_remembered_answer_of_the_holder_that_carried_the_name_on_the_date_is_kept(tmp_path):
    r = _alberto(tmp_path, 1368457)
    got = r.resolve("ACV", "2010-07-09", name="ALBERTO CULVER CO", since="2008-01-16", pin=None)
    assert got.cik == 1368457 and r.edgar.searches == []


def test_a_name_with_no_word_of_three_letters_is_looked_up_by_the_name_tier():
    """TWOU (2U INC, observed to 2020, delisted 2024): `name_tokens` is empty, but 2U, Inc. and 2U INC are one name
    (`names_agree`), so the name is an expected name, and the tier's observed-name acceptance applies to it: 2U, LLC
    (formerly 2U, Inc.) filed a 10-K within the year of the date."""
    twou = (1459417, ("2U, LLC", [{"name": "2U, Inc.", "from": "2008-03-14T00:00:00.000Z",
                                   "to": "2024-09-30T00:00:00.000Z"}],
                      [_f("K0", "S-1", "2014-03-01"), _f("K", "10-K", "2021-02-24"), _f("F", "25-NSE", "2024-09-06")]))
    other = (1689537, ("2U LAUNDRY, INC.", [], [_f("L", "10-K", "2021-03-01")]))
    idx = _index("2U, INC.:0001459417:", "2U, LLC:0001459417:", "2U LAUNDRY, INC.:0001689537:")
    r = TickerResolver(_Edgar(dict([twou, other])), name_index=idx)
    assert r.expected_name("TWOU", "2020-12-31", "2U INC") == "2U INC"
    got = r.resolve("TWOU", "2020-12-31", name="2U INC", since="2014-05-15", pin=None)
    assert (got.cik, got.source) == (1459417, "name_search")


def _dupont(*extra):
    eidp = (30554, ("EIDP, Inc.", [{"name": "DUPONT E I DE NEMOURS & CO", "from": "1994-01-01T00:00:00.000Z",
                                   "to": "2019-05-31T00:00:00.000Z"}],
                    [_f("D00", "10-K", "2005-02-10"), _f("D0", "10-K", "2016-02-10"), _f("D1", "25-NSE", "2017-09-01")]))
    dead = (1137191, ("EI DU PONT DE NEMOURS & CO", [], [_f("X0", "10-K", "2001-03-01")]))
    foundation = (1243868, ("NEMOURS FOUNDATION", [], [_f("N0", "10-K", "2016-03-01")]))
    new = (1666700, ("DuPont de Nemours, Inc.", [], [_f("N1", "10-K", "2019-03-01")]))
    idx = _index("DUPONT E I DE NEMOURS & CO:0000030554:", "EIDP, INC.:0000030554:",
                 "EI DU PONT DE NEMOURS & CO:0001137191:", "NEMOURS FOUNDATION:0001243868:",
                 "DUPONT DE NEMOURS, INC.:0001666700:", *extra)
    return TickerResolver(_Edgar(dict([eidp, dead, foundation, new])), name_index=idx), idx


def test_a_name_the_index_spells_with_words_run_together_is_reached_when_the_prefix_search_finds_no_company():
    """DD (E I DU PONT DE NEMOURS, observed to 2017, 25-NSE 2017-09-01): EDGAR lists the company as DUPONT E I DE NEMOURS
    & CO (CIK 30554), which the observed spelling is not a character prefix of (`names_agree` reads DU PONT as DUPONT).
    The prefix search offers only a dead holder of EI DU PONT DE NEMOURS & CO, so the index's entries sharing the
    name's longest word and agreeing with it are the last resort: the one that filed a Form 25 near the date, existed by
    the era's first sighting and agrees on the date. A company founded after the era's first sighting (DuPont de
    Nemours, Inc., 2019) and a foundation sharing one word are not."""
    r, _ = _dupont()
    got = r.resolve("DD", "2017-09-05", name="E I DU PONT DE NEMOURS", since="2007-12-18", pin=None)
    assert (got.cik, got.source) == (30554, "name_search")


def test_the_last_resort_by_agreeing_names_needs_exactly_one_company():
    """Two agreeing companies that both filed a Form 25 near the date leave nothing to choose by: no answer."""
    twin = (1555555, ("NEMOURS DUPONT E I DE CO", [], [_f("T00", "10-K", "2005-02-10"), _f("T1", "25-NSE", "2017-08-01")]))
    r, idx = _dupont("NEMOURS DUPONT E I DE CO:0001555555:")
    r.edgar.companies[1555555] = twin[1]
    got = r.resolve("DD", "2017-09-05", name="E I DU PONT DE NEMOURS", since="2007-12-18", pin=None)
    assert got.cik is None


def test_the_last_resort_is_not_asked_when_the_prefix_search_already_has_an_answer():
    """APTIV-like: an exact holder that filed near the date is the answer; an agreeing spelling elsewhere in the
    index is never read."""
    r, idx = _dupont("E I DU PONT DE NEMOURS & CO:0001999999:")
    r.edgar.companies[1999999] = ("E I DU PONT DE NEMOURS & CO", [], [_f("Y0", "10-K", "2007-02-10"),
                                                                      _f("Y1", "25-NSE", "2017-08-20")])
    got = r.resolve("DD", "2017-09-05", name="E I DU PONT DE NEMOURS & CO", since="2007-12-18", pin=None)
    assert got.cik == 1999999


def test_a_word_the_snapshot_abbreviates_is_searched_by_its_stem_when_nothing_else_finds_a_company():
    """NWA (2008-09): the snapshot spells NORTHWEST AIRLS CORP, EDGAR NORTHWEST AIRLINES CORP, and no character
    prefix of the first reaches the second. With no candidate from any spelling, the last word is cut to its first
    four letters and searched again; the Form 25 filer among the matches is the company."""
    nwa = (1058033, ("NORTHWEST AIRLINES CORP", [], [_f("N1", "10-K", "2007-02-20"), _f("N2", "25-NSE", "2008-10-30")]))
    old = (917678, ("NORTHWEST AIRLINES HOLDINGS CORP/PRED", [], [_f("O1", "10-K", "1998-02-20")]))
    banks = {9000 + i: (f"NORTHWEST BANCORP {i}", [], []) for i in range(12)}      # the first word alone is too broad
    idx = _index("NORTHWEST AIRLINES CORP:0001058033:", "NORTHWEST AIRLINES HOLDINGS CORP/PRED:0000917678:",
                 *(f"{n[0]}:{c:010d}:" for c, n in banks.items()))
    r = TickerResolver(_Edgar({**banks, **dict([nwa, old])}), name_index=idx)
    assert r._index_candidates(idx, "NORTHWEST AIRLS CORP", "2009-06-08") == {
        1058033: ("NORTHWEST AIRLINES CORP", 221)}
    assert r.resolve("NWA", "2009-06-08", name="NORTHWEST AIRLS CORP", since="2008-01-16", pin=None).cik == 1058033


def test_a_single_word_name_has_no_stem():
    ok = (1, ("ACMEWIDGETS INC", [], [_f("A", "25-NSE", "2012-05-01")]))
    others = {9000 + i: (f"ACMEWIDGETS FUND {i}", [], []) for i in range(12)}
    idx = _index("ACMEWIDGETS INC:0000000001:", *(f"{n[0]}:{c:010d}:" for c, n in others.items()))
    r = TickerResolver(_Edgar({**others, **dict([ok])}), name_index=idx)
    assert r._index_candidates(idx, "ACMEWIDGS", "2012-06-29") == {}

"""The ticker resolver's name tier over SEC's cik-lookup-data.txt (cik-lookup plan, Task 3):
candidates from the local index instead of the live company search."""
import pytest
import requests

from delist_detection.cik_lookup import CikNameIndex
from delist_detection.edgar import EdgarBlocked, EdgarSubmission
from delist_detection.ticker_resolver import TickerResolver


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

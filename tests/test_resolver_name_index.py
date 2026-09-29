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


def test_two_filers_under_one_form_name_no_candidate_as_edgar_did():
    a = (1, ("ACME CORP", [], [_f("A", "25-NSE", "2012-05-01")]))
    b = (2, ("ACME CORP DEL", [], [_f("B", "25-NSE", "2011-05-01")]))
    idx = _index("ACME CORP:0000000001:", "ACME CORP DEL:0000000002:")
    r = TickerResolver(_Edgar(dict([a, b])), name_index=idx)
    assert r._index_candidates(idx, "ACME CO", "2012-06-29") == {}


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
    assert r._index_candidates(idx, "NORTHEAST UTILITIES", "2015-02-20") == {72741: ("NORTHEAST UTILITIES", 1000)}


def test_with_no_filer_a_spelling_matching_one_cik_gives_it_and_a_broad_one_reads_nothing():
    solo = (7, ("SOLO WIDGETS INC", [], [_f("S", "10-K", "2012-02-01")]))
    r = TickerResolver(_Edgar(dict([solo])), name_index=_index("SOLO WIDGETS INC:0000000007:"))
    assert r._index_candidates(r._index(), "SOLO WIDGETS", "2012-06-29") == {7: ("SOLO WIDGETS INC", 1000)}
    many = [f"MANY THINGS FUND {i} LP:{9000 + i:010d}:" for i in range(15)]
    e = _Edgar({9000 + i: (f"MANY THINGS FUND {i} LP", [], []) for i in range(15)})
    r = TickerResolver(e, name_index=_index(*many))
    assert r._index_candidates(r._index(), "MANY THINGS", "2012-06-29") == {}
    assert e.read == []                   # more matches than INDEX_PROBE: EDGAR's unnamed list, nothing read


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

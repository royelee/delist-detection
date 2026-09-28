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
        self.companies, self.atom, self.searches = companies, atom or {}, []

    def company_tickers(self):
        return {}

    def submissions(self, cik, fresh_after=None):
        c = self.companies.get(int(cik))
        return {"name": c[0], "formerNames": c[1], "sic": ""} if c else {"__not_found__": True}

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


def test_exact_names_are_the_only_candidates_when_there_are_any():
    idx = _index("AMERICREDIT CORP:0000804269:", "AMERICREDIT CORP OF CALIFORNIA:0001037688:")
    e = _Edgar({804269: ("AMERICREDIT CORP", [], []), 1037688: ("AMERICREDIT CORP OF CALIFORNIA", [], [])})
    r = TickerResolver(e, name_index=idx)
    assert [c for c, _ in r._name_search("ACF", "2010-09-30", "AMERICREDIT CORP")] == [804269]


def test_prefix_candidates_are_ranked_by_shared_words_and_capped():
    """No exact name: the prefix matches of each spelling, most words shared with
    the observed name first, at most NAME_SEARCH_CANDIDATES CIKs looked at."""
    lines = [f"ACME HOLDINGS FUND {i} LP:{9000 + i:010d}:" for i in range(8)]
    lines.append("ACME HOLDINGS WIDGETS INC:0000000777:")
    idx = _index(*lines)
    looked: list[int] = []
    e = _Edgar({})
    r = TickerResolver(e, name_index=idx)
    r._edgar_name_fit = lambda cik, expected, observed_date=None: (looked.append(cik) or (0, False))
    r._name_search("ACW", "2012-06-29", "ACME HOLDINGS WIDGETS CORP")
    assert looked[0] == 777 and len(looked) == TickerResolver.NAME_SEARCH_CANDIDATES


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

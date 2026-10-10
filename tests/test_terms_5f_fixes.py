"""The review fixes of sub-plan 5f (docs/superpowers/plans/research/2026-10-04-5f-terms.md, "Review fixes"): an election
that states no default (WSC, THE, TRH, NMX), a stock leg named by a defined term (SHAW, HBI, CLP), the gate's answer
shapes, a basket leg's class (CAA, BPYU), the regression report's legs, a bare "$", an unusable LLM answer and the
completion rule's role check. Each case in a docstring is the real case the rule was built for; the real-case replay is
tests/test_terms_cases.py. Offline."""
from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import date
from types import SimpleNamespace

import pytest
import requests

from delist_detection.terms import acquirer_ticker as at
from delist_detection.terms import currency
from delist_detection.measurement import regression
from delist_detection.endings.classifier import DelistClassifier
from delist_detection.sources.cik_lookup import CikNameIndex
from delist_detection.sources.ftd import FtdRow
from delist_detection.terms.llm_merger_extractor import (LEGACY_VERSION, PROMPT_VERSION, LLMMergerTermsExtractor,
                                                         MergerTerms, StockLeg, electors_only)
from delist_detection.terms.payout_gate import (DEFAULT_TOL, GATE_SKIPPED, NO_DEFAULT, PACKAGE, gate_payouts,
                                          reconcile)
from delist_detection.outputs.dlret import MergerInputs
from delist_detection.outputs.payout_rule import basket_legs, value_fields
from delist_detection.outputs.price_requests import RECEIVED_CLOSE, request_rows
from delist_detection.outputs.run_snapshot import RunSnapshot
from delist_detection.sources.sec_stats import SEC_STATS
from delist_detection.outputs.store import DelistingKey
from lifecycle_tables import ending
from test_terms_5f import K, V3_JCI, _Edgar, _f, _Llm, _rec, _v3


# --- an election with no stated default ---------------------------------------------------------------------------

V3_WSC = {**V3_JCI, "deal_type": "election", "package_basis": "none", "cash_per_share": None, "stock_ratio": None,
          "acquirer_name": "Berkshire Hathaway Inc.", "acquirer_ticker": "BRK.B", "cash_currency": None,
          "election_note": "$385.00 in cash or Berkshire Class B common stock equal to $385.00; ratio 5.0611",
          "quote": "converted into the right to receive an amount, either in cash or Berkshire Class B common stock"}
V2_WSC = {"deal_type": "election", "cash_per_share": 385.0, "stock_ratio": 5.0611, "acquirer_name": "Berkshire",
          "acquirer_ticker": "BRK.B", "confidence": "high", "quote": "$385.00 in cash or 5.0611 shares"}


def _wsc(tmp_path, *, v2=True):
    """WSC 2011: the closing 8-K's v3 answer states no leg; the earlier prompt's cached answer for the same filing
    reads the alternatives."""
    (tmp_path / f"C1_m_{PROMPT_VERSION}_WSC.json").write_text(json.dumps(V3_WSC))
    if v2:
        (tmp_path / f"C1_m_{LEGACY_VERSION}.json").write_text(json.dumps(V2_WSC))
    return LLMMergerTermsExtractor(_Edgar([_f("C1", items="2.01,3.01", filed="2011-07-07")], {"C1": "text"}),
                                   _Llm(V3_WSC), model="m", cache_dir=tmp_path)


def test_an_election_that_states_no_default_keeps_the_either_or_reading_of_the_earlier_prompt(tmp_path):
    t = _wsc(tmp_path).extract(_rec("WSC", "2011-07-07"))
    assert (t.cash_per_share, t.stock_ratio, t.acquirer_ticker, t.no_default) == (385.0, 5.0611, "BRK.B", True)
    assert not t.is_package and t.election_note.startswith("$385.00 in cash")
    # the gate reads it as sub-plan 5e did: the stock alternative (a tie goes to stock) settles the row, flagged
    g = gate_payouts([K], {}, {}, {}, {K: t}, {"ABC": 390.0}, {}, lambda ticker, key: 76.5, DEFAULT_TOL)
    assert g.merged_terms[K]["stock_ratio"] == 5.0611 and NO_DEFAULT in g.flags[K]


def test_a_v3_election_with_no_legs_and_no_cached_earlier_answer_is_a_miss(tmp_path):
    assert _wsc(tmp_path, v2=False).extract(_rec("WSC", "2011-07-07")) is None


def test_a_later_candidate_with_legs_never_beats_the_completion_filings_no_default(tmp_path):
    """The completion filing states no default: its base reading is published and later candidates are not read (the
    live run: TRH's later filing was another deal's 0.88 AWH, NMX's the headline 36.00 + 0.1323 CME)."""
    (tmp_path / f"C1_m_{PROMPT_VERSION}_WSC.json").write_text(json.dumps(V3_WSC))
    (tmp_path / f"C1_m_{LEGACY_VERSION}.json").write_text(json.dumps(V2_WSC))
    (tmp_path / f"P_m_{PROMPT_VERSION}_WSC.json").write_text(json.dumps(
        {**V3_JCI, "package_basis": "default", "cash_per_share": 385.0, "stock_ratio": None, "acquirer_ticker": None}))
    filings = [_f("C1", items="2.01", filed="2011-07-07"), _f("P", "DEFM14A", "2011-05-01")]
    t = LLMMergerTermsExtractor(_Edgar(filings, {"C1": "t", "P": "t"}), _Llm(), model="m",
                                cache_dir=tmp_path).extract(_rec("WSC", "2011-07-07"))
    assert (t.cash_per_share, t.stock_ratio, t.no_default) == (385.0, 5.0611, True)


def test_a_cash_or_stock_election_with_no_default_is_gated_as_the_default_package_when_the_sum_fits():
    """THE 2007: $16.00 cash or 0.979 Hercules shares per share with equalization, no stated package: the earlier
    prompt's cash and ratio together are near the close (the package), neither alone."""
    t = MergerTerms("election", 16.0, 0.979, "Hercules", "HERO", "high", "8-K:x", "", no_default=True)
    g = gate_payouts([K], {}, {}, {}, {K: t}, {"ABC": 33.4}, {}, lambda ticker, key: 17.8, DEFAULT_TOL)
    assert (g.merged_terms[K]["cash_per_share"], g.merged_terms[K]["stock_ratio"], g.sources[K]) == (
        16.0, 0.979, PACKAGE) and NO_DEFAULT in g.flags[K]


def test_a_result_for_the_holders_who_elected_is_flagged_not_the_package():
    """R4 (controller ruling 2026-10-04): the package is what the non-electors received. NMX 2008's closing 8-K
    states the stock electors' result ($7.29 and 0.2164 CME) and the cash electors', not the non-electors': the
    elector result stands, flagged. EP 2012's states the non-electors' (the mixed consideration), the package."""
    nmx = ("Because the mandatory cash component was undersubscribed, NYMEX Holdings stockholders who elected to "
           "receive stock consideration ... will receive ... approximately $7.29 in cash and 0.2164 shares")
    ep = "14.9% ... made no election. These holders will receive the Mixed Consideration."
    assert electors_only("election", "final_prorated", nmx)
    assert not electors_only("election", "default", ep)
    assert not electors_only("election", "final_prorated", ep)
    assert not electors_only("cash_and_stock", "final_prorated", nmx)
    assert not electors_only("election", "final_prorated", "became entitled to receive $5.7293 and 0.8357 shares")
    raw = {**V3_JCI, "package_basis": "final_prorated", "quote": nmx, "cash_per_share": 7.29, "stock_ratio": 0.2164}
    t = LLMMergerTermsExtractor._to_terms(raw, _f("C1"))
    assert t.is_package and t.no_default and (t.cash_per_share, t.stock_ratio) == (7.29, 0.2164)


def test_an_election_alternative_is_never_the_published_package():
    """TRH 2012: "shares of Alleghany or cash ... a value equal to $61.14", no default: the v3 answer's stock
    alternative (a dollar value over the average price) is no package, so the contract publishes none of it."""
    r = ending("TRH", "2012-03-16", method="assumed_par", last_trade_close="")
    t = _v3("election", None, None, "Y", basis="none", value=61.14)
    f = value_fields(r, "2012-03-02", MergerInputs(llm=t))
    assert (f["value_rule"], f["cash_per_share"], f["stock_ratio"], f["price_ticker"]) == ("unknown", None, None, "")


# --- a stock leg named by a defined term ------------------------------------------------------------------------

SHAW_TEXT = ('Chicago Bridge & Iron Company N.V., a limited liability company ( naamloze vennootschap ) with '
             'corporate seat in Amsterdam, the Netherlands (“CB&I”) completed its previously announced acquisition of '
             'The Shaw Group Inc. (“Shaw”) ... 0.12883 shares of CB&I common stock')


class _Index:
    """SEC's name index: normalized-name prefix search over (cik, name)."""

    def __init__(self, entries):
        self.idx = CikNameIndex((at_key(n), cik, n) for cik, n in entries)

    def split_search(self, q):
        return self.idx.split_search(q)


def at_key(name):
    from delist_detection.sources.cik_lookup import normalize_name
    return normalize_name(name)


def _subs(books):
    return lambda cik: books.get(cik)


CB_I = {"name": "CHICAGO BRIDGE & IRON CO N V", "tickers": [], "formerNames": []}
CB_I_DE = {"name": "CHICAGO BRIDGE & IRON CO (DELAWARE)", "tickers": [], "formerNames": []}
INDEX = _Index([(1027884, "CHICAGO BRIDGE & IRON CO N V"), (1566458, "CHICAGO BRIDGE & IRON CO (DELAWARE)"),
                (1061894, "GILDAN ACTIVEWEAR INC"), (1038143, "ORANGE")])


def test_the_defined_term_is_expanded_and_a_bare_one_word_name_is_no_name():
    assert at.names_to_search("CB&I", SHAW_TEXT) == ["Chicago Bridge & Iron Company N.V.", "CB&I"]
    assert at.names_to_search("Orange", "the combined company (“Orange”)") == []
    assert at.names_to_search("Amec Foster Wheeler plc", "") == ["Amec Foster Wheeler plc"]
    assert at.queries(["Chicago Bridge & Iron Company N.V."])[-1] == "Chicago Bridge & Iron"


def test_the_issuer_is_the_one_company_that_existed_and_the_ticker_is_the_symbol_its_fails_rows_carry():
    """SHAW 2013: the v3 answer says "CB&I" with no ticker; EDGAR lists no ticker for the issuer any more (it was
    acquired in 2018), so the fails rows of the price date name it: CBI. The other "Chicago Bridge & Iron" (a
    Delaware subsidiary, first filing 2013-03) is not the acquirer of 2013-02-22."""
    books = {1027884: CB_I, 1566458: CB_I_DE}
    first = {1027884: date(1996, 1, 1), 1566458: date(2013, 3, 1)}
    rows = [FtdRow("2013-02-25", "167250109", "CBI", "CHICAGO BRIDGE & IRON CO N V", 49.0),
            FtdRow("2013-02-25", "820280105", "SHAW", "SHAW GROUP INC", 45.0)]
    ticker = at.acquirer_ticker("CB&I", SHAW_TEXT, index=INDEX, subs=_subs(books), first_filed=first.get,
                                rows=lambda: iter(rows), last=date(2013, 2, 22), target_cik=820280)
    assert ticker == "CBI"


def test_the_issuers_listed_ticker_is_used_when_it_has_one():
    """HBI 2025: "Gildan" is defined as Gildan Activewear Inc., EDGAR lists GIL; no fails rows are read."""
    text = 'Gildan Activewear Inc., a corporation ... (“Gildan”)'
    books = {1061894: {"name": "GILDAN ACTIVEWEAR INC", "tickers": ["GIL"], "formerNames": []}}

    def no_rows():
        raise AssertionError("EDGAR lists a ticker")
    assert at.acquirer_ticker("Gildan", text, index=INDEX, subs=_subs(books), first_filed=lambda c: date(1998, 1, 1),
                              rows=no_rows, last=date(2025, 12, 10), target_cik=1) == "GIL"


def test_several_issuers_of_the_name_or_none_give_no_ticker():
    twin = {**CB_I, "tickers": ["CBI"]}
    books = {1027884: twin, 1566458: {**twin, "name": "CHICAGO BRIDGE & IRON CO N V"}}
    old = {1027884: date(1996, 1, 1), 1566458: date(2000, 1, 1)}
    assert at.acquirer_ticker("CB&I", SHAW_TEXT, index=INDEX, subs=_subs(books), first_filed=old.get,
                              rows=lambda: iter(()), last=date(2013, 2, 22), target_cik=1) == ""
    # the nearer name wins over a Delaware namesake that also existed
    books = {1027884: {**CB_I, "tickers": ["CBI"]}, 1566458: CB_I_DE}
    assert at.acquirer_ticker("CB&I", SHAW_TEXT, index=INDEX, subs=_subs(books), first_filed=old.get,
                              rows=lambda: iter(()), last=date(2013, 2, 22), target_cik=1) == "CBI"
    # "Orange" is no name: France's Orange SA is not Coca-Cola European Partners
    assert at.acquirer_ticker("Orange", "", index=INDEX, subs=_subs({1038143: {"name": "ORANGE"}}),
                              first_filed=lambda c: date(1997, 1, 1), rows=lambda: iter(()),
                              last=date(2016, 6, 10), target_cik=1) == ""


class _EdgarShaw:
    def __init__(self, fail=False):
        self.fail = fail

    def recent_filings(self, cik):
        if cik == 820280:
            return [_f("0001193125-13-054117")]
        return [SimpleNamespace(filing_date="1996-01-01"), SimpleNamespace(filing_date="2013-02-01")] \
            if cik == 1027884 else [SimpleNamespace(filing_date="2013-03-01")]

    def fetch_filing_text(self, cik, accession, primary_doc):
        return SHAW_TEXT

    def submissions(self, cik):
        if self.fail:
            SEC_STATS.degraded("submissions")
            raise requests.ConnectionError("down")
        return {1027884: CB_I, 1566458: CB_I_DE}[cik]


class _Ftd:
    def urls_for(self, lo, hi):
        return ["u"]

    def rows(self, url, **kw):
        yield FtdRow("2013-02-25", "167250109", "CBI", "CHICAGO BRIDGE & IRON CO N V", 49.0)


# --- the gate's answer shapes -----------------------------------------------------------------------------------

def _g(terms, close=100.0, price=50.0, payout=None):
    return gate_payouts([K], {K: payout} if payout is not None else {}, {K: "8K_2.01"} if payout is not None else {},
                        {}, {K: terms}, {"ABC": close}, {}, lambda ticker, key: price, DEFAULT_TOL)


def test_a_dollar_valued_leg_with_no_ratio_is_skipped_not_a_crash():
    """A v3 answer stating no package (basis none), not an election, with a stock leg stated as a dollar value."""
    g = _g(_v3("cash_and_stock", 50.0, None, "X", basis="none", value=50.0))
    assert g.flags[K] == (f"{GATE_SKIPPED}stock_value",) and K not in g.merged_terms and g.dropped["skipped"] == 1


def test_a_further_leg_with_no_main_ratio_is_skipped_not_a_crash():
    g = _g(_v3("stock", None, None, "X", basis="none", legs=[StockLeg(0.5, "Y", "Y")]))
    assert g.flags[K] == (f"{GATE_SKIPPED}basket",) and K not in g.merged_terms


def test_a_basket_that_states_no_package_is_not_published_on_its_main_leg_alone():
    """Two securities per share (0.99 + 0.01) with basis none: the main leg alone would be published as the terms."""
    g = _g(_v3("stock", None, 0.99, "QSR", basis="none", legs=[StockLeg(0.01, "Partnership", "QSP")]), close=50.0,
           price=50.5)
    assert g.flags[K] == (f"{GATE_SKIPPED}basket",) and K not in g.merged_terms


def test_cad_cash_that_states_no_package_is_skipped_against_the_usd_close():
    """R5: C$65.00 and 0.5 shares at US$50 sum within 15% of a US$100 close; a sum across currencies is no check."""
    g = _g(_v3("cash_and_stock", 65.0, 0.5, "X", basis="none", currency_code="CAD"), close=100.0, price=70.0)
    assert g.flags[K] == (f"{GATE_SKIPPED}CAD",) and K not in g.merged_terms
    g = _g(_v3("cash", 98.0, None, "X", basis="none", currency_code="CAD"), close=100.0)
    assert g.flags[K] == (f"{GATE_SKIPPED}CAD",) and K not in g.payouts


def test_a_stock_leg_with_no_ratio_that_names_no_skip_is_dropped_with_a_flag():
    """The guard behind every shape: a stock leg that reaches the cash+stock check with no number of shares."""
    class _NoSkip(MergerTerms):             # ...an answer whose shape names no skip reason
        @property
        def skip_reason(self) -> str:
            return ""

    t = replace(_v3("stock", None, None, "X", basis="fixed"), cash_currency="")
    t = _NoSkip(**{f.name: getattr(t, f.name) for f in fields(t)})
    object.__setattr__(t, "stock_value", 1.0)       # has_stock, but a ratio-less leg that skip_reason would name...
    object.__setattr__(t, "stock_ratio", None)
    g = _g(t)
    assert g.flags[K] == ("terms_gate_failed:no_ratio",) and g.dropped["no_ratio"] == 1


def test_reconcile_skips_a_non_package_answer_the_gate_cannot_price():
    t = _v3("cash", 90.0, None, "X", basis="none", currency_code="CAD")
    assert reconcile(None, 100.0, t, None, DEFAULT_TOL).flags == (f"{GATE_SKIPPED}CAD",)


# --- a basket leg keeps its class -------------------------------------------------------------------------------

def test_a_second_class_under_the_main_legs_ticker_takes_its_class_ticker():
    """CAA 2018: 0.885 Lennar class A and 0.0177 class B, both under LEN in the answer: class B is LEN-B, as the
    fails rows spell it; the class A's price request is not asked twice."""
    t = MergerTerms("stock", None, 0.885, "Lennar", "LEN", "high", "8-K:x", "", acquirer_share_class="A",
                    extra_legs=(StockLeg(0.0177, "Lennar", "LEN", "B"),), package_basis="fixed")
    assert t.legs("LEN") == [(0.885, "LEN", "A"), (0.0177, "LEN-B", "B")]
    r = ending("CAA", "2018-02-20", ltd="2018-02-09", method="assumed_par", last_trade_close="40")
    rows = basket_legs(r, "2018-02-09", MergerInputs(llm=t, acquirer_sec_id="BBG0LEN", leg_sec_ids={"LEN-B": "BBG0LENB"}))
    assert [(x["leg"], x["share_class"], x["price_ticker"], x["price_sec_id"]) for x in rows] == [
        (1, "A", "LEN", "BBG0LEN"), (2, "B", "LEN-B", "BBG0LENB")]
    f = value_fields(r, "2018-02-09", MergerInputs(llm=t))
    assert "0.0177 × price(LEN-B, 2018-02-12)" in f["value_formula"]


def test_a_preferred_unit_leg_is_not_priced_as_the_common_units():
    """BPYU 2021: 0.0657 "BPY preferred unit" is not BPY, the common units: no ticker, no request."""
    t = MergerTerms("cash_and_stock", 12.38, 0.0913, "Brookfield Asset Management", "BAM", "high", "8-K:x", "",
                    acquirer_share_class="A", package_basis="fixed",
                    extra_legs=(StockLeg(0.0657, "Brookfield Property Partners L.P.", "BPY", "preferred unit"),))
    assert [x[1] for x in t.legs("BAM")] == ["BAM", ""]


def test_two_legs_never_share_a_price_request_key():
    contract = [{"sec_id": "CAA", "last_trade_date": "2018-02-09", "continuation": False, "exit_kind": "merger",
                 "value_rule": "basket"}]
    endings = {"CAA": ending("CAA", "2018-02-20", ltd="2018-02-09")}
    rows = request_rows(contract, endings, {DelistingKey("CAA", "2018-02-20"): ("LEN", "BBG0LEN")},
                        leg_rows=[{"sec_id": "CAA", "leg": 2, "price_ticker": "LEN", "price_sec_id": "BBG0LEN"},
                                  {"sec_id": "CAA", "leg": 3, "price_ticker": "LEN-B", "price_sec_id": ""}])
    asked = [(r["lookup_ticker"]) for r in rows if r["kind"] == RECEIVED_CLOSE]
    assert asked == ["LEN", "LEN-B"]
    assert len({(r["sec_id"], r["last_trade_date"], r["kind"], r["lookup_ticker"], r["date"]) for r in rows}) == len(rows)


# --- the regression report reads the legs ------------------------------------------------------------------------

def test_a_basket_leg_change_is_a_contract_change():
    d = [{"sec_id": "CAA", "successor_sec_id": "", "value_rule": "basket"}]
    def run(legs=None):
        tables = {"contract_delistings": d, "security_history": [], "id_changes": []}
        return RunSnapshot.of(tables if legs is None else {**tables, "payout_legs": legs})
    base = run([{"sec_id": "CAA", "leg": "2", "ratio": "0.0177", "price_sec_id": "", "price_ticker": "LEN"},
                {"sec_id": "CAA", "leg": "1", "ratio": "0.885", "price_sec_id": "B", "price_ticker": "LEN"}])
    new = run([{"sec_id": "CAA", "leg": "1", "ratio": "0.885", "price_sec_id": "B", "price_ticker": "LEN"},
               {"sec_id": "CAA", "leg": "2", "ratio": "0.0177", "price_sec_id": "", "price_ticker": "LEN-B"}])
    rows = regression.diff_contract(base, new)
    assert [(r["table"], r["field"], r["kind"]) for r in rows] == [("payout_legs", "legs", "changed")]
    assert regression.diff_contract(base, base) == [] and regression.diff_contract(new, new, exclude={"CAA"}) == []
    # a run with no legs file reads as no legs: a first run's baskets are added
    added = regression.diff_contract(run(), new)
    assert [(r["table"], r["kind"]) for r in added] == [("payout_legs", "added")]


# --- a bare "$" never overrides a stated currency ----------------------------------------------------------------

@pytest.mark.parametrize("quote", ["CAD $65.50 in cash", "Cdn. $65.50 per share", "C $65.50", "$65.50 (Canadian)"])
def test_a_bare_dollar_sign_keeps_the_answers_canadian_currency(quote):
    raw = {**V3_JCI, "cash_per_share": 65.5, "cash_currency": "CAD", "quote": quote}
    assert LLMMergerTermsExtractor._to_terms(raw, _f("C1")).cash_currency == "CAD"


def test_an_explicit_prefix_still_overrides_the_answers_currency():
    raw = {**V3_JCI, "cash_per_share": 65.5, "cash_currency": "CAD", "quote": "US$65.50 in cash"}
    assert LLMMergerTermsExtractor._to_terms(raw, _f("C1")).cash_currency == "USD"
    raw = {**V3_JCI, "cash_per_share": 65.5, "cash_currency": "USD", "quote": "C$65.50 in cash"}
    assert LLMMergerTermsExtractor._to_terms(raw, _f("C1")).cash_currency == "CAD"
    assert currency.stated_currency("CAD $65.50", 65.5, explicit_only=True) == ""
    assert currency.stated_currency("CAD $65.50", 65.5) == "USD"          # the old reading, for the regex's own use


# --- an unusable LLM answer is degraded, not a silent miss -------------------------------------------------------

def test_an_answer_that_is_no_json_object_counts_degraded_and_is_not_cached(tmp_path):
    ext = LLMMergerTermsExtractor(_Edgar([_f("C1", items="2.01")], {"C1": "text"}), _Llm(["not", "a", "dict"]),
                                  model="m", cache_dir=tmp_path)
    before = SEC_STATS.thread_degraded()
    assert ext.extract(_rec()) is None
    assert SEC_STATS.thread_degraded() == before + 1 and list(tmp_path.glob("*.json")) == []


def test_package_basis_none_is_kept_as_none():
    t = LLMMergerTermsExtractor._to_terms({**V3_JCI, "package_basis": "none"}, _f("C1"))
    assert t.package_basis == "none" and not t.is_package


# --- the completion rule's role check ----------------------------------------------------------------------------

class _ClsEdgar:
    def __init__(self, texts, sub=None):
        self.texts, self.sub = texts, sub

    def fetch_filing_text(self, cik, accession, primary_doc):
        return self.texts.get(accession, "")

    def submissions(self, cik):
        return self.sub


def test_an_acquirers_own_completed_acquisition_is_not_the_registrants_completion():
    """The no-evidence default reads a 6-K or 8-K for "completed its acquisition": the registrant's own acquisition
    of another company (Enerplus completes acquisition of Y) says nothing of its own ending; an acquirer's report of
    the registrant's acquisition (Pan American Silver completes acquisition of Tahoe) does."""
    sub = {"name": "ENERPLUS CORP", "formerNames": []}
    f25 = _f("F25", "25-NSE", "2016-02-23")
    own = _f("OWN", "8-K", "2016-02-20")
    other = _f("OTH", "8-K", "2016-02-21")
    texts = {"OWN": "Enerplus Corporation completed its acquisition of Bakken assets from Y",
             "OTH": "Pan American Silver Completes Acquisition of Enerplus Corporation"}
    cls = DelistClassifier(_ClsEdgar(texts, sub), None)
    assert cls._completion_report(1, [f25, own], f25, "ENERPLUS CORP") == ""
    assert cls._completion_report(1, [f25, own, other], f25, "ENERPLUS CORP") == "8-K 2016-02-21"
    assert cls._completion_report(1, [f25, _f("CO", "8-K", "2016-02-20")], f25, "ENERPLUS CORP") == ""


# --- PCYC's averaging window -------------------------------------------------------------------------------------

PCYC = ("a number of shares of AbbVie common stock equal to $109.00 divided by the volume weighted average sale price "
        "per share of AbbVie common stock as reported on the New York Stock Exchange for the ten consecutive trading "
        "days ending on and including the second trading day prior to the final expiration date of the offer, as "
        "calculated by Bloomberg Financial LP")


def test_the_averaging_window_of_a_dollar_valued_leg_is_named_in_the_formula(tmp_path):
    from delist_detection.terms.llm_merger_extractor import averaging_window
    window = averaging_window(PCYC)
    assert window == ("ten consecutive trading days ending on and including the second trading day prior to the "
                      "final expiration date of the offer")
    assert averaging_window("no average here") == ""
    raw = {**V3_JCI, "package_basis": "default", "cash_per_share": 152.25, "stock_ratio": None,
           "stock_value_per_share": 109.0, "acquirer_ticker": "ABBV", "quote": "$152.25 in cash"}
    (tmp_path / f"C1_m_{PROMPT_VERSION}_PCYC.json").write_text(json.dumps(raw))
    ext = LLMMergerTermsExtractor(_Edgar([_f("C1", items="2.01", filed="2015-06-05")], {"C1": PCYC}), _Llm(), model="m",
                                  cache_dir=tmp_path)
    t = ext.extract(_rec("PCYC", "2015-06-05"))
    assert t.value_window == window
    r = ending("PCYC", "2015-06-05", ltd="2015-05-22", method="assumed_par", last_trade_close="0.01",
               flags="terms_gate_skipped:stock_value")
    f = value_fields(r, "2015-05-22", MergerInputs(llm=t))
    assert f["value_formula"] == (f"(152.25 + 109.00 × price(ABBV, 2015-05-26) / avg_price(ABBV: {window})) "
                                  "/ last_close − 1")


# --- an election whose filing states no package for the holders who made no election keeps the base reading -----------

V2_TRH = {"deal_type": "election", "cash_per_share": 14.22, "stock_ratio": 0.145, "acquirer_name": "Alleghany",
          "acquirer_ticker": "Y", "confidence": "high", "quote": "the sum of (i) 0.145 shares ... and (ii) $14.22"}
V3_TRH = {**V3_JCI, "deal_type": "election", "package_basis": "none", "cash_per_share": None, "stock_ratio": None,
          "stock_value_per_share": 61.14, "acquirer_ticker": "Y", "cash_currency": None, "election_note": "shares or cash"}
NMX_QUOTE = ("NYMEX Holdings stockholders who elected to receive stock consideration ... will receive approximately "
             "$7.29 in cash and 0.2164 shares")
V3_NMX = {**V3_JCI, "deal_type": "election", "package_basis": "final_prorated", "cash_per_share": 7.29,
          "stock_ratio": 0.2164, "acquirer_ticker": "CME", "quote": NMX_QUOTE}
V2_NMX = {"deal_type": "election", "cash_per_share": 81.16, "stock_ratio": 0.2378, "acquirer_name": "CME",
          "acquirer_ticker": "CME", "confidence": "high", "quote": "$81.16 ... 0.2378 shares"}


def _extract(tmp_path, v3, v2):
    (tmp_path / f"C1_m_{PROMPT_VERSION}_X.json").write_text(json.dumps(v3))
    if v2:
        (tmp_path / f"C1_m_{LEGACY_VERSION}.json").write_text(json.dumps(v2))
    return LLMMergerTermsExtractor(_Edgar([_f("C1", items="2.01,3.01", filed="2012-03-05")], {"C1": "text"}),
                                   _Llm(v3), model="m", cache_dir=tmp_path).extract(_rec("X", "2012-03-05"))


def test_trh_a_value_with_no_package_keeps_the_earlier_prompts_two_legs_published_as_read(tmp_path):
    t = _extract(tmp_path, V3_TRH, V2_TRH)
    assert (t.cash_per_share, t.stock_ratio, t.acquirer_ticker, t.no_default) == (14.22, 0.145, "Y", True)
    r = ending("TRH", "2012-03-16", method="assumed_par", last_trade_close="")
    f = value_fields(r, "2012-03-05", MergerInputs(llm=t))
    assert (f["value_rule"], f["cash_per_share"], f["stock_ratio"]) == ("cash_plus_stock", 14.22, 0.145)


def test_nmx_the_stock_electors_result_is_never_the_package_the_gate_reads_the_base_reading(tmp_path):
    t = _extract(tmp_path, V3_NMX, V2_NMX)
    assert (t.cash_per_share, t.stock_ratio, t.no_default) == (81.16, 0.2378, True)
    g = gate_payouts([K], {}, {}, {}, {K: t}, {"ABC": 80.14}, {}, lambda ticker, key: 342.11, DEFAULT_TOL)
    assert g.payouts[K] == 81.16 and K not in g.merged_terms and NO_DEFAULT in g.flags[K]


def test_an_electors_result_with_no_cached_earlier_answer_is_a_miss_not_the_package(tmp_path):
    assert _extract(tmp_path, V3_NMX, None) is None


V3_TRH_OTHER_DEAL = {**V3_JCI, "deal_type": "stock", "package_basis": "fixed", "cash_per_share": None,
                     "stock_ratio": 0.88, "acquirer_ticker": "AWH", "quote": "0.88 Allied World shares"}
V3_NMX_HEADLINE = {**V3_JCI, "deal_type": "cash_and_stock", "package_basis": "fixed", "cash_per_share": 36.0,
                   "stock_ratio": 0.1323, "acquirer_ticker": "CME", "quote": "the exchange ratio ... unchanged"}


@pytest.mark.parametrize("v3, v2, later, want", [
    (V3_TRH, V2_TRH, V3_TRH_OTHER_DEAL, (14.22, 0.145, "Y")),
    (V3_NMX, V2_NMX, V3_NMX_HEADLINE, (81.16, 0.2378, "CME"))])
def test_trh_and_nmx_later_candidates_answers_are_never_read(tmp_path, v3, v2, later, want):
    (tmp_path / f"C1_m_{PROMPT_VERSION}_X.json").write_text(json.dumps(v3))
    (tmp_path / f"C1_m_{LEGACY_VERSION}.json").write_text(json.dumps(v2))
    (tmp_path / f"P_m_{PROMPT_VERSION}_X.json").write_text(json.dumps(later))
    filings = [_f("C1", items="2.01,3.01", filed="2012-03-05"), _f("P", "DEFM14A", "2011-05-01")]
    t = LLMMergerTermsExtractor(_Edgar(filings, {"C1": "t", "P": "t"}), _Llm(), model="m",
                                cache_dir=tmp_path).extract(_rec("X", "2012-03-05"))
    assert (t.cash_per_share, t.stock_ratio, t.acquirer_ticker, t.no_default) == (*want[:2], want[2], True)

"""Sub-plan 5f (terms extraction): the cash's currency (ruling R5), the LLM's package (prompt v3, ruling R4), the
gate's reading of a package, baskets and payout_legs.csv (ruling R3, contract schema 3), a stock leg stated as a
dollar value (PCYC), rule 6 of spec 5c (CHTR) and a completion reported in a 6-K or a press-release 8-K (TAHO,
KING, BPYU). Each case in a docstring is the real case the rule was built for; the real-case replay is
tests/test_terms_cases.py."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from delist_detection import currency
from delist_detection.classifier import COMPLETION, DelistClassifier
from delist_detection.contract import payout_leg_rows
from delist_detection.edgar import EdgarSubmission
from delist_detection.exchange_terms import OwnExchange, split_factor
from delist_detection.llm_merger_extractor import (PROMPT_VERSION, LLMMergerTermsExtractor, MergerTerms,
                                                    StockLeg)
from delist_detection.payout_extractor import _collect
from delist_detection.payout_gate import (DEFAULT_TOL, ELECTION_CASH, GATE_SKIPPED, PACKAGE, gate_payouts,
                                          reconcile)
from delist_detection.dlret import MergerInputs
from delist_detection.payout_rule import basket_legs, value_fields
from delist_detection.price_requests import RECEIVED_CLOSE, request_rows
from delist_detection.sec_stats import SEC_STATS
from delist_detection.store import DelistingKey
from lifecycle_tables import ending, tables

LTD = "2014-12-12"       # a Friday: price_date is Monday the 15th
K = DelistingKey("ABC", "2014-12-20")


def _v3(deal_type="cash_and_stock", cash=None, ratio=None, ticker=None, *, basis="fixed", currency_code="USD",
        value=None, legs=(), name=None):
    """A prompt-v3 answer: its legs are the package (ruling R4)."""
    return MergerTerms(deal_type, cash, ratio, name, ticker, "high", "8-K:x", "", cash_currency=currency_code if cash
                       else "", stock_value=value, extra_legs=tuple(legs), package_basis=basis)


# --- R5: the currency a filing states -------------------------------------------------------------------------------

def test_a_dollar_sign_is_usd_and_a_c_dollar_is_cad():
    assert currency.prefix_currency("receive $23.00 in cash", 8) == "USD"
    assert currency.prefix_currency("entitled to receive C$65.50 in cash", 21) == "CAD"
    assert currency.prefix_currency("US$25.00 cash", 2) == "USD"
    assert currency.prefix_currency("Cdn$1.00", 3) == "CAD"


def test_the_currency_written_next_to_an_amount():
    """THI 2014: the LLM's quote writes "C$65.50"; AWH 2017's "$23.00"; a code before the amount counts too."""
    assert currency.stated_currency("each holder was entitled to receive C$65.50 in cash and 0.8025", 65.5) == "CAD"
    assert currency.stated_currency("(i) cash consideration of $23.00 ... and (ii) 0.057937", 23.0) == "USD"
    assert currency.stated_currency("a payment of EUR 12.00 per share", 12.0) == "EUR"
    assert currency.stated_currency("the price is 12.00 per share", 12.0) == ""          # no sign: not stated
    assert currency.stated_currency("$123.00 in cash", 23.0) == ""                       # never a part of a number


def test_an_llm_currency_answer_is_an_iso_code_or_blank():
    assert [currency.normalize(c) for c in ("USD", "usd", "$", "US$", "C$", "€", "null", None, "dollars")] == [
        "USD", "USD", "USD", "USD", "CAD", "EUR", "", "", ""]


def test_the_regex_read_carries_its_currency():
    cur: dict = {}
    counts, _, _ = _collect("each Share was converted into the right to receive C$65.50 in cash", None, True, cur)
    assert counts == {65.5: 1} and cur == {65.5: "CAD"}
    cur = {}
    _collect("each Share was converted into the right to receive $25.00 in cash, without interest", None, True, cur)
    assert cur == {25.0: "USD"}


# --- prompt v3: the package --------------------------------------------------------------------------------------

def _f(acc, form="8-K", filed="2016-09-06", items="", report=""):
    return EdgarSubmission(accession=acc, form=form, filing_date=filed, report_date=report or filed, items=items,
                           primary_doc="d.htm")


class _Edgar:
    def __init__(self, filings, texts=None):
        self.filings, self.texts = filings, texts or {}

    def recent_filings(self, cik):
        return list(self.filings)

    def fetch_filing_text(self, cik, accession, primary_doc):
        return self.texts.get(accession, "")


class _Llm:
    def __init__(self, answer=None, raises=False):
        self.answer, self.raises, self.users = answer, raises, []

    def extract(self, system, user, schema):
        self.users.append(user)
        if self.raises:
            raise RuntimeError("down")
        return self.answer


def _rec(ticker="JCI", day="2016-09-02"):
    from delist_detection.classifier import DelistRecord
    from delist_detection.crsp_codes import CrspBucket
    return DelistRecord(ticker=ticker, cik=53669, observed_delist_date=day, crsp_code=231,
                        bucket=CrspBucket.MERGER, confidence="high", reason="", evidence={})


V3_JCI = {"deal_type": "election", "package_basis": "final_prorated", "cash_per_share": 5.7293,
          "cash_currency": "USD", "stock_ratio": 0.8357, "stock_value_per_share": None,
          "acquirer_name": "Johnson Controls International plc", "acquirer_ticker": "JCI",
          "acquirer_share_class": None, "other_stock_legs": [], "election_note": "$34.88 cash or shares",
          "contingent_note": "", "confidence": "high",
          "quote": "became entitled to receive $5.7293 in cash and 0.8357 Johnson Controls ordinary shares"}


def test_a_v3_answer_is_the_package_with_its_currency_and_legs(tmp_path):
    ext = LLMMergerTermsExtractor(_Edgar([_f("C1", items="2.01,3.01")], {"C1": "text"}), _Llm(V3_JCI),
                                  model="m", cache_dir=tmp_path)
    t = ext.extract(_rec(), security_name="JOHNSON CONTROLS INC")
    assert (t.cash_per_share, t.cash_currency, t.stock_ratio, t.package_basis, t.deal_type) == (
        5.7293, "USD", 0.8357, "final_prorated", "election")
    assert not t.is_basket and t.has_stock
    # the quote's currency wins over the answer's: THI's "C$65.50" read as USD would be CAD
    raw = {**V3_JCI, "cash_per_share": 65.5, "cash_currency": "USD", "quote": "receive C$65.50 in cash and 0.8025"}
    assert LLMMergerTermsExtractor._to_terms(raw, _f("C1")).cash_currency == "CAD"
    # a basket's further legs, and a stock leg stated as a dollar value (PCYC)
    raw = {**V3_JCI, "cash_per_share": None, "stock_ratio": 1.0, "other_stock_legs": [
        {"ratio": 0.0666667, "issuer_name": "Starz", "ticker": "STRZ", "share_class": None},
        {"ratio": None, "issuer_name": "x", "ticker": None, "share_class": None}]}
    t = LLMMergerTermsExtractor._to_terms(raw, _f("C1"))
    assert t.extra_legs == (StockLeg(0.0666667, "Starz", "STRZ", ""),) and t.is_basket and t.cash_currency == ""
    t = LLMMergerTermsExtractor._to_terms({**V3_JCI, "cash_per_share": 152.25, "stock_ratio": None,
                                           "stock_value_per_share": 109.0}, _f("C1"))
    assert (t.stock_value, t.stock_ratio, t.has_stock) == (109.0, None, True)


def test_the_user_prompt_names_the_target_security_and_the_cache_key_its_ticker(tmp_path):
    """PARA 2025: class A and class B holders got different terms, so the prompt names the class and the answer is
    cached per target ticker."""
    llm = _Llm(V3_JCI)
    ext = LLMMergerTermsExtractor(_Edgar([_f("C1", items="2.01")], {"C1": "text"}), llm, model="m",
                                  cache_dir=tmp_path)
    ext.extract(_rec("PARA"), security_name="PARAMOUNT GLOBAL CLASS B")
    assert "Target security: PARAMOUNT GLOBAL CLASS B (ticker PARA)" in llm.users[0]
    assert "Filing: 8-K filed 2016-09-06" in llm.users[0]
    assert [p.name for p in tmp_path.glob("*.json")] == [f"C1_m_{PROMPT_VERSION}_PARA.json"]
    ext.extract(_rec("PARAA"), security_name="PARAMOUNT GLOBAL CLASS A")
    assert len(llm.users) == 2                    # the other class is asked again


def test_the_latest_completion_documents_come_first():
    """BOT 2007: the 8-K amending the ratio to 0.375 (after the June proxy) is read before the proxy's 0.35; FWLT
    2014: an 8-K reporting the closing without item 2.01; TAHO 2019: a foreign issuer's 6-K comes last."""
    filings = [_f("PROXY", "DEFM14A", "2007-06-07"), _f("AMEND", "8-K", "2007-07-06", "1.01,8.01,9.01"),
               _f("OLD", "8-K", "2007-05-11", "1.01,9.01"), _f("CLOSE", "8-K", "2007-07-13", "3.01,5.01"),
               _f("SIX", "6-K", "2007-07-12"), _f("FAR", "8-K", "2007-03-01", "3.01")]
    got = [f.accession for f in LLMMergerTermsExtractor(None, None)._candidates(filings, date(2007, 7, 12))]
    assert got == ["CLOSE", "AMEND", "PROXY", "OLD", "SIX"]


def test_a_failed_llm_call_is_a_degraded_miss_never_cached(tmp_path):
    ext = LLMMergerTermsExtractor(_Edgar([_f("C1", items="2.01")], {"C1": "text"}), _Llm(raises=True),
                                  model="m", cache_dir=tmp_path)
    before = SEC_STATS.thread_degraded()
    assert ext.extract(_rec()) is None
    assert SEC_STATS.thread_degraded() == before + 1 and list(tmp_path.glob("*.json")) == []


# --- R4 and R5 in the gate ---------------------------------------------------------------------------------------

def _gate(terms, *, payout=None, close=None, price=None):
    payouts = {K: payout} if payout is not None else {}
    return gate_payouts([K], payouts, {K: "8K_2.01"} if payout is not None else {}, {}, {K: terms},
                        {"ABC": close} if close is not None else {}, {}, lambda ticker, key: price, DEFAULT_TOL)


def test_an_election_package_is_gated_whole_and_published_whole():
    """JCI 2016: the package $5.7293 + 0.8357 (a holder who elected nothing) settles the row, never the stock
    alternative alone (the old either-or reading took 0.8357 at 9% off the close)."""
    g = _gate(_v3("election", 5.7293, 0.8357, "JCI"), close=45.04, price=48.90)
    assert g.merged_terms[K] == {"cash_per_share": 5.7293, "stock_ratio": 0.8357, "acquirer_price": 48.90,
                                 "acquirer_ticker": "JCI"}
    assert (g.sources[K], g.priced_by[K]) == (PACKAGE, "ticker")


def test_an_election_package_of_stock_drops_the_regex_cash_alternative():
    """SUG 2012: the regex read the $44.25 cash alternative and it fits the close; non-electors got 1.0 ETE unit,
    the package the row publishes (R4)."""
    g = _gate(_v3("election", None, 1.0, "ETE", basis="default"), payout=44.25, close=41.10, price=44.0)
    assert K not in g.payouts and g.merged_terms[K]["stock_ratio"] == 1.0 and g.sources[K] == PACKAGE
    # and when the package cannot be priced the cash alternative is still never the row's terms
    g = _gate(_v3("election", None, 1.0, "ETE", basis="default"), payout=44.25, close=41.10, price=None)
    assert K not in g.payouts and K not in g.merged_terms
    assert g.flags[K] == ("terms_gate_failed:no_acq_price",)


def test_a_fixed_mix_package_that_fails_keeps_a_regex_cash_that_fits():
    """A cash-and-stock answer the gate refuses leaves a fitting regex read as it was (not an election)."""
    g = _gate(_v3("cash_and_stock", 10.0, 0.5, "XYZ"), payout=12.0, close=12.0, price=40.0)
    assert g.payouts[K] == 12.0 and K not in g.merged_terms


def test_an_answer_that_states_no_package_keeps_the_either_or_reading():
    """CBSS 2007: "$71.82 in cash or 2.8 BBVA ADSs, subject to proration", no default and no final result: the two
    alternatives are never summed into a package; the one nearest the close settles the row, as before v3."""
    t = _v3("election", 71.82, 2.8, "BBV", basis="none")
    r = reconcile(None, 64.36, t, 30.0, DEFAULT_TOL)          # 2.8 x 30 is 30% off: the cash is nearer
    assert (r.cash, r.stock_ratio, r.source) == (71.82, None, ELECTION_CASH)
    assert _gate(t, close=64.36, price=30.0).merged_terms == {}


def test_a_cash_only_election_package_is_the_election_cash():
    """CZR 2020: the no-election default was cash, $12.41."""
    r = reconcile(None, 12.37, _v3("election", 12.41, basis="default"), None, DEFAULT_TOL)
    assert (r.cash, r.source) == (12.41, ELECTION_CASH)
    r = reconcile(None, 4.97, _v3("election", 3.0, basis="default"), None, DEFAULT_TOL)
    assert (r.cash, r.flags) == (None, ("llm_gate_failed",))


def test_without_a_last_close_a_package_of_stock_replaces_the_regex_cash():
    """FWLT 2014: no last trade, so no close; the regex read the $32.00 headline, the package is $16.00 + 0.8998
    Amec Foster Wheeler; AWH 2017: $23.00 + 0.057937 Fairfax."""
    g = _gate(_v3("election", 16.0, 0.8998, None, basis="default"), payout=32.0, close=None)
    assert K not in g.payouts and K not in g.merged_terms
    assert g.flags[K] == ("no_last_close", "terms_gate_failed:no_last_close")


def test_a_non_usd_cash_leg_is_skipped_by_the_gate_with_a_flag():
    """THI 2014: C$65.50 + 0.8025 QSR against a USD close; the library has no FX source (R5)."""
    t = _v3("election", 65.5, 0.8025, "QSR", basis="default", currency_code="CAD")
    assert t.skip_reason == "CAD"
    g = _gate(t, close=85.92, price=35.46)
    assert K not in g.merged_terms and g.flags[K] == (f"{GATE_SKIPPED}CAD",) and g.dropped["skipped"] == 1
    r = reconcile(None, 85.92, _v3("cash", 65.5, currency_code="CAD"), None, DEFAULT_TOL)
    assert (r.cash, r.flags) == (None, (f"{GATE_SKIPPED}CAD",))


def test_a_basket_and_a_dollar_valued_leg_are_skipped_by_the_gate():
    """LGFB 2025: 1 LION + 1/15 STRZ (two securities); PCYC 2015: $152.25 + $109.00 of AbbVie over its averaging
    price, which the library does not have."""
    basket = _v3("other", None, 1.0, "LION", legs=[StockLeg(0.0666667, "Starz", "STRZ")])
    assert _gate(basket, close=7.69, price=7.0).flags[K] == (f"{GATE_SKIPPED}basket",)
    value = _v3("election", 152.25, None, "ABBV", value=109.0, basis="default")
    assert _gate(value, close=260.0, price=60.0).flags[K] == (f"{GATE_SKIPPED}stock_value",)


# --- the published rule ------------------------------------------------------------------------------------------

def test_the_cash_currency_comes_from_the_read_that_supplied_the_cash():
    r = ending("A", "2014-12-20", last_trade_close="10", payout_per_share="12.5", payout_source="8K_2.01")
    assert value_fields(r, LTD, MergerInputs(raw_currency="USD"))["cash_currency"] == "USD"
    r = ending("A", "2014-12-20", last_trade_close="10", payout_per_share="5.7293", stock_ratio="0.8357",
               acquirer_ticker="JCI", payout_source=PACKAGE)
    assert value_fields(r, LTD, MergerInputs(llm=_v3("election", 5.7293, 0.8357, "JCI"), raw_currency="CAD")
                        )["cash_currency"] == "USD"
    # a --merger-terms row states none; a stock-only rule has no cash and so no currency
    r = ending("A", "2014-12-20", last_trade_close="10")
    assert value_fields(r, LTD, MergerInputs(override={"cash_per_share": 3.0}))["cash_currency"] == ""
    assert value_fields(r, LTD, MergerInputs(llm=_v3("stock", None, 1.0, "ETE")))["cash_currency"] == ""


def test_terms_the_gate_skipped_are_published_with_their_currency_and_gate_skipped():
    r = ending("THI", "2014-12-20", method="assumed_par", last_trade_close="85.92",
               flags="terms_gate_skipped:CAD;merger_at_par")
    f = value_fields(r, LTD, MergerInputs(llm=_v3("election", 65.5, 0.8025, "QSR", currency_code="CAD"),
                                          acquirer_sec_id="BBG0QSR"))
    assert (f["value_rule"], f["cash_per_share"], f["cash_currency"], f["stock_ratio"], f["terms_gate"]) == (
        "cash_plus_stock", 65.5, "CAD", 0.8025, "skipped")
    # with no last close the gate never ran: no verdict
    r = ending("FWLT", "2014-12-20", method="needs_last_trade", flags="terms_gate_failed:no_last_close")
    f = value_fields(r, LTD, MergerInputs(llm=_v3("election", 16.0, 0.8998, "AMFW")))
    assert (f["value_rule"], f["cash_per_share"], f["terms_gate"]) == ("cash_plus_stock", 16.0, "")


def test_a_basket_publishes_its_cash_and_its_legs_in_payout_legs():
    """R3: the main row keeps the cash (BPYU's $12.38) and blank stock columns; payout_legs.csv one row per
    security, the main one's security the acquirer stage 8 found and the others the run's holder of their
    ticker."""
    t = _v3("cash_and_stock", 12.38, 0.0913, "BAM", legs=[StockLeg(0.0657, "BPY", "BPYPP")])
    r = ending("BPYU", "2021-08-05", method="assumed_par", last_trade_close="20",
               flags="terms_gate_skipped:basket")
    inputs = MergerInputs(llm=t, acquirer_sec_id="BBG0BAM", leg_sec_ids={"BPYPP": "BBG0BPY"})
    f = value_fields(r, "2021-07-26", inputs)
    assert (f["value_rule"], f["cash_per_share"], f["cash_currency"], f["stock_ratio"], f["price_ticker"],
            f["terms_gate"]) == ("basket", 12.38, "USD", None, "", "skipped")
    assert f["value_formula"] == ("(12.38 + 0.0913 × price(BAM, 2021-07-27) + 0.0657 × price(BPYPP, 2021-07-27)) "
                                  "/ last_close − 1")
    assert basket_legs(r, "2021-07-26", inputs) == [
        {"sec_id": "BPYU", "leg": 1, "ratio": 0.0913, "share_class": "", "price_sec_id": "BBG0BAM",
         "price_ticker": "BAM", "price_date": "2021-07-27"},
        {"sec_id": "BPYU", "leg": 2, "ratio": 0.0657, "share_class": "", "price_sec_id": "BBG0BPY",
         "price_ticker": "BPYPP", "price_date": "2021-07-27"}]
    assert basket_legs(r, "2021-07-26", MergerInputs(llm=_v3("stock", None, 1.0, "X"))) == []


def test_payout_leg_rows_are_the_last_endings_baskets():
    t = _v3("other", None, 1.0, "LION", legs=[StockLeg(0.0666667, "Starz", "STRZ")])
    r = ending("LGFB", "2025-05-17", ltd="2025-05-06", method="assumed_par", last_trade_close="7.69")
    rows = payout_leg_rows(tables(delistings=[r]), {DelistingKey("LGFB", "2025-05-17"): MergerInputs(llm=t)})
    assert [(x["leg"], x["ratio"], x["price_ticker"], x["price_date"]) for x in rows] == [
        (1, 1.0, "LION", "2025-05-07"), (2, 0.0666667, "STRZ", "2025-05-07")]


def test_a_dollar_valued_stock_leg_is_carried_in_the_formula_with_a_price_request():
    """PCYC 2015: $152.25 + $109.00 of AbbVie at its averaging price: no ratio, the acquirer priced the day after
    the last trade (its received close is asked: tests/test_merger_value.py)."""
    t = _v3("election", 152.25, None, "ABBV", value=109.0, basis="default")
    r = ending("PCYC", "2015-06-05", ltd="2015-05-22", method="assumed_par", last_trade_close="0.01",
               flags="terms_gate_skipped:stock_value")
    f = value_fields(r, "2015-05-22", MergerInputs(llm=t, acquirer_sec_id="BBG0025Y4RY4"))
    assert (f["value_rule"], f["cash_per_share"], f["stock_ratio"], f["price_sec_id"], f["price_ticker"],
            f["price_date"]) == ("cash_plus_stock", 152.25, None, "BBG0025Y4RY4", "ABBV", "2015-05-26")
    assert f["value_formula"] == ("(152.25 + 109.00 × price(ABBV, 2015-05-26) / avg_price(ABBV)) "
                                  "/ last_close − 1")


def _leg(sec_id, n, ticker, price_sec_id):
    return {"sec_id": sec_id, "leg": n, "price_ticker": ticker, "price_sec_id": price_sec_id}


def test_a_baskets_further_legs_ask_their_received_close():
    contract = [{"sec_id": "LGFB", "last_trade_date": "2025-05-06", "continuation": False, "exit_kind": "merger",
                 "value_rule": "basket"}]
    endings = {"LGFB": ending("LGFB", "2025-05-17", ltd="2025-05-06")}
    rows = request_rows(contract, endings, {DelistingKey("LGFB", "2025-05-17"): ("LION", "")},
                        leg_rows=[_leg("LGFB", 2, "STRZ", ""), _leg("LGFB", 3, "", "")])
    assert [(r["kind"], r["lookup_ticker"], r["date"]) for r in rows if r["kind"] == RECEIVED_CLOSE] == [
        (RECEIVED_CLOSE, "LION", "2025-05-07"), (RECEIVED_CLOSE, "STRZ", "2025-05-07")]


# --- rule 6 and a completion reported in a 6-K -------------------------------------------------------------------

def test_a_split_factor_keeps_the_stake_and_another_ratio_does_not():
    """SIRI 2024's 0.1 New Sirius (a one-for-ten consolidation) is no merger; CHTR 2016's 0.9042 is (the one split
    factor rule, `exchange_terms.split_factor`, which the verdict's ratio doubt reads too)."""
    assert split_factor(0.1) and split_factor(1.0) and split_factor(2.0) and split_factor(0.25)
    assert not split_factor(0.9042) and not split_factor(0.6029) and not split_factor(1.5)
    assert split_factor(0.01) and not split_factor(1 / 150) and not split_factor(0.0)       # n up to SPLIT_FACTOR_MAX

    def own(ratio, cash=False, ambiguous=False):
        return OwnExchange(ratio, cash, "of New Charter", ("New Charter",), "", False, "s", ambiguous=ambiguous)
    assert own(0.9042).stake_changed and own(1.0, cash=True).stake_changed               # rule 6: a merger
    assert not own(0.1).stake_changed and not own(1.0).stake_changed and not own(0.9042, ambiguous=True).stake_changed


@pytest.mark.parametrize("text", [
    "News Release “Pan American Silver Completes Acquisition of Tahoe Resources”",
    "Completion of Acquisition On February 23, 2016, King Digital Entertainment plc",
    "announcing that BAM has completed its previously announced acquisition of all of the units",
    "the completion of the arrangement under the plan of arrangement"])
def test_a_completion_statement(text):
    assert COMPLETION.search(text)


@pytest.mark.parametrize("text", ["the merger is expected to be completed in the second quarter",
                                  "upon completion, holders will receive", "completed a private placement"])
def test_no_completion_statement(text):
    assert not COMPLETION.search(text)


class _ClsEdgar:
    def __init__(self, filings, texts):
        self.filings, self.texts = filings, texts

    def fetch_filing_text(self, cik, accession, primary_doc):
        return self.texts.get(accession, "")


def test_a_6k_near_the_form_25_that_reports_the_completion_is_found():
    """KING 2016: the Form 25 day's 6-K says "Completion of Acquisition"; a 6-K 31 days before, or after the
    window, is not read."""
    f25 = _f("F25", "25-NSE", "2016-02-23")
    filings = [f25, _f("K1", "6-K", "2016-02-23"), _f("OLD", "6-K", "2016-01-20"), _f("LATE", "6-K", "2016-03-10")]
    texts = {"K1": "Completion of Acquisition On February 23, 2016", "OLD": "completed the acquisition of X",
             "LATE": "completed the acquisition of X"}
    cls = DelistClassifier(_ClsEdgar(filings, texts), None)
    assert cls._completion_report(1580732, filings, f25) == "6-K 2016-02-23"
    assert cls._completion_report(1580732, [f25, filings[2], filings[3]], f25) == ""


def test_an_unsure_one_for_one_answer_with_no_share_count_is_passed_over(tmp_path):
    """ATH 2022: the 5.01 8-K says only that Athene became a subsidiary of AGM; the model guessed one share
    (medium confidence) where holders got 1.149 AGM shares, so the proxy, the next candidate, is read."""
    from delist_detection.llm_merger_extractor import unsupported_one_for_one
    guess = {**V3_JCI, "deal_type": "stock", "package_basis": "fixed", "cash_per_share": None, "stock_ratio": 1,
             "confidence": "medium", "quote": "As a result of the Mergers, AAM and AHL became direct subsidiaries"}
    proxy = {**guess, "stock_ratio": 1.149, "confidence": "high", "quote": "1.149 AGM Shares"}

    class Two(_Llm):
        def extract(self, system, user, schema):
            self.users.append(user)
            return guess if len(self.users) == 1 else proxy

    filings = [_f("C1", items="1.01,5.01", filed="2022-01-03"), _f("P", "DEFM14A", "2021-11-05")]
    ext = LLMMergerTermsExtractor(_Edgar(filings, {"C1": "t", "P": "t"}), Two(), model="m", cache_dir=tmp_path)
    t = ext.extract(_rec("ATH", "2021-12-31"))
    assert t.stock_ratio == 1.149 and t.source == "DEFM14A:P"
    sure = LLMMergerTermsExtractor._to_terms({**guess, "confidence": "high"}, _f("C1"))
    said = LLMMergerTermsExtractor._to_terms({**guess, "quote": "converted into one share of Holdco common stock"},
                                             _f("C1"))
    assert not unsupported_one_for_one(sure) and not unsupported_one_for_one(said)


@pytest.mark.parametrize("spelled", ["NULL", "None", "N/A", "null", "-", " "])
def test_a_spelled_out_null_ticker_is_no_ticker(spelled):
    """GRUB 2021: the terms' acquirer ticker "NULL" is no ticker: the gate reports `no_acq_ticker`, never a price
    missing for a symbol called NULL, and the extractor reads it as none."""
    from delist_detection.llm_merger_extractor import clean_ticker
    asked = []
    t = MergerTerms("stock", None, 0.35, "Just Eat Takeaway.com", spelled, "high", "8-K:x", "")
    g = gate_payouts([K], {}, {}, {}, {K: t}, {"ABC": 10.0}, {}, lambda ticker, key: asked.append(ticker),
                     DEFAULT_TOL)
    assert g.flags[K] == ("terms_gate_failed:no_acq_ticker",) and asked == [] and clean_ticker(spelled) == ""
    assert t.acquirer_ticker is None and t.ticker == ""          # the answer itself holds no ticker
    assert LLMMergerTermsExtractor._to_terms({**V3_JCI, "acquirer_ticker": spelled}, _f("C1")).acquirer_ticker is None
    assert clean_ticker(" JET ") == "JET"


def test_a_regex_read_of_the_packages_cash_leg_never_stands_for_the_package():
    """SHAW 2013: the regex read $41.00, the cash leg of $41.00 and 0.12883 CB&I shares; with no ticker for the
    stock leg the package fails the gate, and the regex's one leg is not published as the terms."""
    g = _gate(_v3("cash_and_stock", 41.0, 0.12883, None), payout=41.0, close=47.62, price=None)
    assert K not in g.payouts and g.flags[K] == ("terms_gate_failed:no_acq_ticker",)

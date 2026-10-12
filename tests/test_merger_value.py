"""Stage 8 at its interface (`merger_value.value_mergers` and `MergerValues`): the reads, an unnamed stock leg's
ticker, the received close each stock leg asks and the answer that reaches the gate only through it, and what the
later stages read from the records. The real cases of the acquirer lines and the gate are
tests/test_acquirer_gate_cases.py. Offline."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from delist_detection.terms.acquirer_line import LineIndex
from delist_detection.outputs.reconstruction import DelistRecord
from delist_detection.vocabulary.crsp_codes import CrspBucket
from delist_detection.endings.delistings import Delisting
from delist_detection.sources.ftd import FtdIndex
from delist_detection.identity.issuer_record import IssuerRecord
from delist_detection.endings.last_trade import LastTrade
from delist_detection.terms.llm_merger_extractor import ClosingDividend, MergerTerms
from delist_detection.terms.merger_value import MergerValue, MergerValues, TableTerms, value_mergers
from delist_detection.terms.payout_extractor import PayoutResult
from delist_detection.pipeline import Clients
from delist_detection.outputs.price_requests import RECEIVED_CLOSE, PriceAnswers, PriceKey
from delist_detection.identity.security_master import Security
from delist_detection.outputs.store import DelistingKey
from lifecycle_tables import ending
from test_terms_5f_fixes import INDEX, SHAW_TEXT, _EdgarShaw, _Ftd


def _merger(sec_id: str, ticker: str, delist: str, last: date | None, cik: int = 1,
            bucket: CrspBucket = CrspBucket.MERGER) -> Delisting:
    rec = DelistRecord(ticker, cik, delist, 231, bucket, "high", "M&A", evidence={"flags": []}, sec_id=sec_id,
                       delist_date=delist)
    return Delisting(sec_id, cik, ticker, delist, rec, LastTrade(last, "midas", ()), None, None, "")


class _NoFtd:
    def urls_for(self, lo, hi):
        return []

    def rows(self, url, **kw):
        return iter(())


class _Terms:
    """An LLM extractor that answers each target from a map (by ticker); `seen` records the names it was told, and
    `offers` the targets whose offer documents it was asked for (answered from `offer_answers`)."""

    def __init__(self, answers: dict, calls: list | None = None, offer_answers: dict | None = None,
                 dividends: dict | None = None, earlier: dict | None = None) -> None:
        self.answers, self.calls, self.seen = answers, calls if calls is not None else [], []
        self.offer_answers, self.offers = offer_answers or {}, []
        self.dividends, self.dividend_asks = dividends or {}, []
        self.earlier, self.earlier_asks = earlier or {}, []      # FB-023: the 8-Ks before the closing one

    def closing_dividend(self, record, security_name=""):
        self.dividend_asks.append(record.ticker)
        amount = self.dividends.get(record.ticker)
        return None if amount is None else ClosingDividend(amount, "8-K:D1", "a special dividend")

    def earlier_dividend(self, record, security_name=""):
        self.earlier_asks.append(record.ticker)
        amount = self.earlier.get(record.ticker)
        return None if amount is None else ClosingDividend(amount, "8-K:E1", "a special one-time cash dividend")

    def extract(self, record, security_name=""):
        self.calls.append(record.ticker)
        self.seen.append((record.ticker, security_name))
        return self.answers.get(record.ticker)

    def extract_offer_terms(self, record, security_name=""):
        self.offers.append(record.ticker)
        return self.offer_answers.get(record.ticker)


def _value(delistings, *, llm=None, payout=None, edgar=None, resolver=None, name_index=None, ftd_client=None,
           securities=None, closes=None, own_closes=None, caller_terms=None, answers=None, workers=1,
           llm_workers=None, log=None) -> MergerValues:
    clients = Clients(edgar=edgar, resolver=resolver, classifier=None, figi=None, ftd_client=ftd_client or _NoFtd(),
                      payout_extractor=payout, llm_extractor=llm, issuers=IssuerRecord(edgar, name_index=name_index))
    index = LineIndex(securities or {}, {}, {}, FtdIndex(source=clients.ftd_client))
    return value_mergers(delistings, index, clients=clients, closes=closes or {}, own_closes=own_closes,
                         caller_terms=caller_terms or {}, answers=answers or PriceAnswers(), tol=0.15,
                         workers=workers, llm_workers=llm_workers, log=log or (lambda *a: None))


def _stock(ratio, ticker, *, cash=None, value=None, name=None):
    return MergerTerms("stock" if cash is None else "cash_and_stock", cash, ratio, name, ticker, "high", "8-K:0001",
                       "", stock_value=value, package_basis="fixed")


# --- the reads ----------------------------------------------------------------------------------------------------

def test_the_llm_is_told_the_target_security():
    """The LLM extractor is asked with the security's name (its class: PARA's class B) when it takes one."""
    llm = _Terms({})
    para = Security("BBG000C496P7", 813828, "CLASS B", "PARAMOUNT GLOBAL CLASS B", "Common Stock", True, "cusip")
    _value([_merger("BBG000C496P7", "PARA", "2025-08-07", date(2025, 8, 6), cik=813828)], llm=llm,
           securities={para.sec_id: para})
    assert llm.seen == [("PARA", "PARAMOUNT GLOBAL CLASS B")]


def test_the_offers_own_documents_are_asked_only_when_neither_reader_found_terms():
    """FB-016 (CureVac 2026): a merger whose first-choice filings give the LLM nothing and the regex nothing is asked
    again over the offer's own documents, and their answer is its terms. A merger either reader answered is not
    asked, so the answers already read stand."""
    class Payout:
        def extract(self, record, last_close=None):
            hit = replace(PayoutResult.none(), value=38.25, confidence="high", source="8K_2.01")
            return hit if record.ticker == "CXG" else PayoutResult.none()

    ratio = _stock(0.05363, "BNTX")
    llm = _Terms({"AAA": _stock(1.5, "ZZZ")}, offer_answers={"CVAC": ratio})
    es = [_merger(t, t, "2026-01-16", date(2026, 1, 5)) for t in ("AAA", "CXG", "CVAC", "CNH")]
    values = _value(es, llm=llm, payout=Payout())
    assert llm.calls == ["AAA", "CXG", "CVAC", "CNH"] and llm.offers == ["CVAC", "CNH"]
    assert values.get(es[2].key).llm == ratio and values.get(es[3].key).llm is None
    assert values.terms_read(es[2].key) and values.terms_read(es[1].key) and not values.terms_read(es[3].key)


def test_the_llm_calls_are_filled_ahead_on_worker_threads_with_the_same_answers():
    """With --sec-workers > 1 the LLM extractor runs on the worker threads first (a new prompt version asks every
    merger again); the sequential pass then reads what they cached, so its terms are the one-worker run's."""
    calls, cache = [], {}

    class Ext:                          # caches its answer per target, as LLMMergerTermsExtractor does on disk
        def extract(self, record, security_name=""):
            calls.append(record.ticker)
            return cache.setdefault(record.ticker, MergerTerms("cash", 10.0 + len(cache), None, None, None, "high",
                                                               "8-K:x", "", package_basis="fixed"))

        def closing_dividend(self, record, security_name=""):
            return None

        def earlier_dividend(self, record, security_name=""):
            return None

    es = [_merger(t, t, "2016-09-16", date(2016, 9, 15)) for t in ("AAA", "BBB", "CCC")]

    def run(workers):
        values = _value(es, llm=Ext(), workers=workers)
        return {k: v.llm for k, v in values.records.items()}

    one = run(1)
    assert calls == ["AAA", "BBB", "CCC"]
    calls.clear()
    assert run(4) == one and sorted(calls) == ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC"]



@pytest.mark.parametrize("workers", [1, 4])
def test_the_regex_read_is_bounded_by_the_runs_own_close(workers):
    """The regex reader's sanity bound decides what it reads, and what it reads can move the first gate pass: it is
    the run's own last close (here 100.00), never the caller's answered one (50.00), on the warm threads too."""
    asked = []

    class Regex:
        def extract(self, record, last_close=None):
            asked.append(last_close)
            return replace(PayoutResult.none(), source="")

    e = _merger("T", "TGT", "2018-12-10", date(2018, 11, 28))
    _value([e], payout=Regex(), closes={e.key: 50.0}, own_closes={e.key: 100.0}, workers=workers)
    assert asked and set(asked) == {100.0}


def test_a_failed_acquirer_ticker_lookup_is_reported_even_when_the_client_counted_nothing():
    """Final review M8: stage 8a's one read outside the issuer record, the resolver's (its SEC ticker-map tier
    raises on a failed read with no cached copy), gives no issuer and a resolution_degraded item of its own, whether
    or not the client counted the failure; no issuer is then looked for by name."""
    import requests

    class Down:
        def resolve(self, *a, **k):
            raise requests.ConnectionError("down")

    e = _merger("T", "TGT", "2018-12-10", date(2018, 11, 28))
    values = _value([e], llm=_Terms({"TGT": _stock(0.5, "ACQ", name="ACQUIRER CO")}), resolver=Down())
    assert values.get(e.key).acquirer_sec_id == ""
    assert [(r.flag, r.reason.split(" rested")[0]) for r in values.review] == [
        ("resolution_degraded", "the acquirer issuer lookup")]


# --- 8a': an unnamed stock leg's ticker -----------------------------------------------------------------------------

def _shaw(terms: MergerTerms):
    return _merger("SHAW", "SHAW", "2013-02-28", date(2013, 2, 22), cik=820280), {"SHAW": terms}


def test_an_unnamed_stock_leg_takes_its_ticker_and_keeps_its_other_terms():
    """SHAW 2013's $41.00 + 0.12883 CB&I with no ticker takes CBI (price_ticker blank before: the leg failed the gate
    `no_acq_ticker`), and asks CBI's received close."""
    e, answers = _shaw(MergerTerms("cash_and_stock", 41.0, 0.12883, "CB&I", None, "high", "8-K:0001193125-13-054117",
                                   "", package_basis="fixed"))
    values = _value([e], llm=_Terms(answers), edgar=_EdgarShaw(), resolver=SimpleNamespace(resolve=None),
                    name_index=lambda: INDEX, ftd_client=_Ftd())
    v = values.get(e.key)
    assert (v.llm.acquirer_ticker, v.llm.cash_per_share, v.llm.stock_ratio) == ("CBI", 41.0, 0.12883)
    assert v.request == ("CBI", "") and not values.review
    assert SHAW_TEXT       # the filing the defined term "CB&I" is read in


def test_a_stock_leg_with_its_own_ticker_is_never_named_again():
    def never():
        raise AssertionError("the name index is asked only for a leg with no ticker")

    e, answers = _shaw(MergerTerms("cash_and_stock", 41.0, 0.12883, "CB&I", "XYZ", "high", "8-K:1", ""))
    values = _value([e], llm=_Terms(answers), edgar=_EdgarShaw(), name_index=never,
                    resolver=SimpleNamespace(resolve=lambda *a, **k: SimpleNamespace(cik=None)))
    assert values.get(e.key).llm.acquirer_ticker == "XYZ"


def test_a_failed_name_read_gives_no_ticker_and_a_degraded_review_item():
    e, answers = _shaw(MergerTerms("cash_and_stock", 41.0, 0.12883, "CB&I", None, "high", "8-K:0001193125-13-054117",
                                   ""))
    values = _value([e], llm=_Terms(answers), edgar=_EdgarShaw(fail=True), resolver=SimpleNamespace(),
                    name_index=lambda: INDEX, ftd_client=_Ftd())
    assert values.get(e.key).llm.acquirer_ticker is None and values.get(e.key).request is None
    assert [r.flag for r in values.review] == ["resolution_degraded"]


# --- the requests and their answers --------------------------------------------------------------------------------

def test_a_stock_leg_asks_its_received_close_unless_the_caller_gave_terms():
    a = _merger("A", "AET", "2018-12-10", date(2018, 11, 28))
    b = _merger("B", "BBB", "2019-01-10", date(2019, 1, 3))
    given = {"B": {"cash_per_share": 10.0, "stock_ratio": 0.5, "acquirer_price": 20.0, "acquirer_ticker": "XYZ"}}
    values = _value([a, b], llm=_Terms({"AET": _stock(0.8378, "cvs"), "BBB": _stock(0.5, "XYZ")}),
                    caller_terms=given)
    assert values.get(a.key).request == ("CVS", "") and values.get(b.key).request is None
    assert values.requests([ending("A", "2018-12-10"), ending("B", "2019-01-10")]) == {a.key: ("CVS", "", "")}


def test_a_dollar_valued_leg_asks_its_acquirers_close_too():
    """PCYC 2015: $152.25 + $109.00 of AbbVie at its averaging price: no ratio, a received close asked for it."""
    e = _merger("PCYC", "PCYC", "2015-06-05", date(2015, 5, 22))
    t = MergerTerms("election", 152.25, None, None, "ABBV", "high", "8-K:x", "", stock_value=109.0,
                    package_basis="default")
    assert _value([e], llm=_Terms({"PCYC": t})).get(e.key).request == ("ABBV", "")


def test_an_answer_reaches_the_gate_only_through_the_request_it_answers():
    """A second run with the request answered changes values only: the answered received close is the acquirer price
    of the leg that asked it, and an answer under another ticker answers no request here."""
    e = _merger("T", "TGT", "2018-12-10", date(2018, 11, 28))
    llm = _Terms({"TGT": _stock(0.5, "ACQ")})
    closes = {e.key: 10.0}
    first = _value([e], llm=llm, closes=closes).get(e.key)
    assert first.terms is None and first.request == ("ACQ", "") and "terms_gate_failed:no_acq_price" in first.flags

    def asked(ticker, price):
        return PriceAnswers({PriceKey("T", "2018-11-28", RECEIVED_CLOSE, ticker, "2018-11-29"): price})

    second = _value([e], llm=llm, closes=closes, answers=asked("ACQ", 20.0)).get(e.key)
    assert (second.terms["acquirer_price"], second.terms["stock_ratio"], second.priced_by) == (20.0, 0.5, "ticker")
    assert (second.request, second.acquirer_sec_id) == (first.request, first.acquirer_sec_id)
    assert _value([e], llm=llm, closes=closes, answers=asked("OTHER", 20.0)).get(e.key).terms is None


def test_an_answered_last_close_moves_the_gates_values_only():
    """The values pass reads the answers: 0.5 ACQ at the answered 40.00 reconciles with the run's own close (20.00)
    and fails against an answered 30.00. The request and the run's decisions (8b's R1 reading, 9b's reconciled) are
    the first pass's, on the run's own close and no answer (no ACQ close: no leg priced), in both runs."""
    e = _merger("T", "TGT", "2018-12-10", date(2018, 11, 28))
    llm = _Terms({"TGT": _stock(0.5, "ACQ")})
    leg = PriceAnswers({PriceKey("T", "2018-11-28", RECEIVED_CLOSE, "ACQ", "2018-11-29"): 40.0})
    own = _value([e], llm=llm, closes={e.key: 20.0}, answers=leg)
    moved = _value([e], llm=llm, closes={e.key: 30.0}, own_closes={e.key: 20.0}, answers=leg)
    a, b = own.get(e.key), moved.get(e.key)
    assert a.terms["acquirer_price"] == 40.0 and b.terms is None and "terms_gate_failed" in " ".join(b.flags)
    assert (b.request, b.acquirer_sec_id, b.price_ticker) == (a.request, a.acquirer_sec_id, a.price_ticker)
    assert moved.read_terms(e.key) == own.read_terms(e.key) == (None, 0.5)         # the LLM's, as read
    assert moved.reconciled(e.key) is own.reconciled(e.key) is False
    assert _value([e], llm=llm, closes={e.key: 20.0}).get(e.key).own_verdict is None   # nothing answered: one pass


# --- FB-021: a closing dividend -----------------------------------------------------------------------------------------

class _Cash:
    """The regex payout reader's double: `values` by ticker."""

    def __init__(self, values: dict) -> None:
        self.values = values

    def extract(self, record, last_close=None):
        v = self.values.get(record.ticker)
        return PayoutResult.none() if v is None else replace(PayoutResult.none(), value=v, confidence="high",
                                                             source="8K_2.01")


def test_a_closing_dividend_is_in_the_tables_cash_and_never_in_what_the_runs_decisions_read():
    """Extended Stay 2021: $18.75 from the merger and a $1.75 dividend paid before the effective time, against a
    20.46 close. The value reads all the cash (20.50); the package the run's decisions read stays 18.75 (operator
    ruling 2026-10-04: a special dividend is never consideration), and the contract's inputs name the dividend."""
    e = _merger("S", "STAY", "2021-06-26", date(2021, 6, 15))
    llm = _Terms({}, dividends={"STAY": 1.75})
    logged = []
    values = _value([e], llm=llm, payout=_Cash({"STAY": 18.75}), closes={e.key: 20.46}, log=logged.append)
    v = values.get(e.key)
    assert (v.payout, v.dividend, v.flags) == (18.75, 1.75, ())
    assert values.table_terms(e.key).payout_per_share == 20.50
    assert values.read_terms(e.key) == (18.75, None) and values.reconciled(e.key)
    assert values.contract_inputs([ending("S", "2021-06-26")])[e.key].dividend == 1.75
    assert logged == ["S 2021-06-26: closing dividend 1.75 read from 8-K:D1"]


def test_a_dividend_the_last_close_does_not_carry_changes_nothing():
    # USG 2019: the $0.50 was paid months before the closing
    e = _merger("U", "USG", "2019-05-04", date(2019, 4, 23))
    values = _value([e], llm=_Terms({}, dividends={"USG": 0.5}), payout=_Cash({"USG": 43.5}), closes={e.key: 43.48})
    assert values.get(e.key).dividend is None and values.table_terms(e.key).payout_per_share == 43.5


def test_a_closing_dividend_beside_a_stock_leg_is_the_tables_cash():
    # Six Flags 2024: 0.58 of a share and a $1.53 dividend; the answered close prices the leg
    e = _merger("X", "SIX", "2024-07-12", date(2024, 7, 1))
    leg = PriceAnswers({PriceKey("X", "2024-07-01", RECEIVED_CLOSE, "FUN", "2024-07-02"): 52.11})
    values = _value([e], llm=_Terms({"SIX": _stock(0.58, "FUN")}, dividends={"SIX": 1.53}), closes={e.key: 32.0},
                    answers=leg)
    terms = values.table_terms(e.key)
    assert (terms.payout_per_share, terms.stock_ratio, terms.acquirer_price) == (1.53, 0.58, 52.11)
    assert values.read_terms(e.key) == (None, 0.58)        # the first pass priced no leg: the LLM's terms, no dividend


def test_the_dividend_is_asked_only_of_a_merger_with_terms_and_never_counts_beside_a_callers_row():
    es = [_merger("A", "AAA", "2021-06-26", date(2021, 6, 15)), _merger("B", "BBB", "2021-06-26", date(2021, 6, 15)),
          _merger("C", "CCC", "2021-06-26", date(2021, 6, 15), bucket=CrspBucket.LIQUIDATION)]
    llm = _Terms({}, dividends={"AAA": 1.75, "BBB": 1.75})
    values = _value(es, llm=llm, payout=_Cash({"AAA": 18.75}), closes={e.key: 20.46 for e in es},
                    caller_terms={"A": {"cash_per_share": 18.75}})
    assert llm.dividend_asks == ["AAA"]                    # BBB has no terms read; CCC is no merger
    assert values.get(es[0].key).dividend is None and values.table_terms(es[0].key).payout_per_share == 18.75


def test_a_restated_merger_keeps_no_dividend():
    from delist_detection.outputs.dlret import StatementTerms
    values = _values(payout=18.75, dividend=1.75)
    values.restate(K, StatementTerms(1.0, "CNNE", "CANNAE HOLDINGS"), PriceAnswers(), date(2017, 11, 17))
    assert values.get(K).dividend is None and values.table_terms(K).payout_per_share is None


# --- FB-023: a closing dividend declared in an earlier 8-K -----------------------------------------------------------

def test_a_merger_valued_under_its_close_with_no_dividend_read_has_its_earlier_8ks_asked():
    """Plains Exploration 2013: the kept value is 46.00 against a 48.90 close, and the closing filings name no
    dividend. The 8-K of a week before declares $3.00, and with it the value is 49.00, nearer the close."""
    e = _merger("P", "PXP", "2013-06-10", date(2013, 5, 30))
    llm = _Terms({}, earlier={"PXP": 3.0})
    logged = []
    values = _value([e], llm=llm, payout=_Cash({"PXP": 46.0}), closes={e.key: 48.90}, log=logged.append)
    v = values.get(e.key)
    assert (v.payout, v.dividend, v.flags) == (46.0, 3.0, ())
    assert values.table_terms(e.key).payout_per_share == 49.0
    assert values.read_terms(e.key) == (46.0, None)             # the package the run's decisions read: no dividend
    assert llm.dividend_asks == ["PXP"] and llm.earlier_asks == ["PXP"]
    assert logged == ["P 2013-06-10: closing dividend 3 read from 8-K:E1, an 8-K before the closing",
                      "earlier 8-Ks: 1 mergers valued more than 1% under their last close and with no dividend read "
                      "were asked, 1 closing dividends read"]


def test_the_earlier_8ks_are_asked_only_past_one_percent_under_the_close_and_only_with_no_dividend_read():
    es = [_merger("A", "NEAR", "2013-06-10", date(2013, 5, 30)),     # 0.9% under its close
          _merger("B", "OVER", "2013-06-10", date(2013, 5, 30)),     # above its close
          _merger("C", "READ", "2013-06-10", date(2013, 5, 30)),     # 6% under, and a closing dividend was read
          _merger("D", "GIVEN", "2013-06-10", date(2013, 5, 30)),    # 6% under, the caller's own terms
          _merger("E", "NONE", "2013-06-10", date(2013, 5, 30)),     # no terms read
          _merger("F", "REFUSED", "2013-06-10", date(2013, 5, 30)),  # the gate refused its cash: no kept value
          _merger("G", "FAR", "2013-06-10", date(2013, 5, 30)),      # 1.1% under
          _merger("H", "BLIND", "2013-06-10", date(2013, 5, 30))]    # no close
    cash = {"NEAR": 48.46, "OVER": 49.5, "READ": 46.0, "GIVEN": 46.0, "REFUSED": 20.0, "FAR": 48.36, "BLIND": 46.0}
    closes = {e.key: 48.90 for e in es if e.ticker != "BLIND"}
    llm = _Terms({}, dividends={"READ": 0.01}, earlier={t: 3.0 for t in cash})
    values = _value(es, llm=llm, payout=_Cash(cash), closes=closes, caller_terms={"D": {"cash_per_share": 46.0}})
    assert llm.earlier_asks == ["FAR"]
    assert values.get(es[6].key).dividend is None        # asked, read, and 51.36 is no nearer 48.90 than 48.36 is
    assert values.get(es[2].key).dividend == 0.01


def test_an_earlier_dividend_is_decided_again_on_each_pass():
    """The consumer's condition: the trigger runs on the run's own closes, and the dividend it reads is offered to
    the gate on the pass that reads the answered closes too, which decides on those."""
    e = _merger("P", "PXP", "2013-06-10", date(2013, 5, 30))

    def run(answered_close):
        return _value([e], llm=_Terms({}, earlier={"PXP": 3.0}), payout=_Cash({"PXP": 46.0}),
                      closes={e.key: answered_close}, own_closes={e.key: 48.90})
    kept = run(48.97)
    assert kept.get(e.key).dividend == 3.0 and kept.table_terms(e.key).payout_per_share == 49.0
    ex = run(46.10)                                        # the answered close no longer carries the dividend
    assert ex.get(e.key).dividend is None and ex.table_terms(e.key).payout_per_share == 46.0
    assert ex.get(e.key).own_verdict == kept.get(e.key).own_verdict == (46.0, None)   # the first pass, both runs


def test_a_leg_only_an_answer_prices_has_its_earlier_8ks_asked_on_the_answered_pass():
    """A stock merger whose acquirer has no price in the run's own rows has no value on the first pass, so nothing
    triggers there; the answered pass values it 6% under its close, asks, and counts the dividend. The first pass
    is the same with and without the answer."""
    e = _merger("X", "TGT", "2013-06-10", date(2013, 5, 30))
    leg = PriceAnswers({PriceKey("X", "2013-05-30", RECEIVED_CLOSE, "ACQ", "2013-05-31"): 92.0})
    llm = _Terms({"TGT": _stock(0.5, "ACQ")}, earlier={"TGT": 3.0})
    values = _value([e], llm=llm, closes={e.key: 48.90}, answers=leg)
    v = values.get(e.key)
    assert llm.earlier_asks == ["TGT"] and v.dividend == 3.0
    terms = values.table_terms(e.key)
    assert (terms.payout_per_share, terms.stock_ratio, terms.acquirer_price) == (3.0, 0.5, 92.0)
    alone = _Terms({"TGT": _stock(0.5, "ACQ")}, earlier={"TGT": 3.0})
    assert _value([e], llm=alone, closes={e.key: 48.90}).get(e.key).dividend is None and alone.earlier_asks == []


def test_a_failed_earlier_read_is_an_error_row_and_the_merger_keeps_its_value():
    class Broken(_Terms):
        def earlier_dividend(self, record, security_name=""):
            raise ValueError("bad answer")
    e = _merger("P", "PXP", "2013-06-10", date(2013, 5, 30))
    values = _value([e], llm=Broken({}), payout=_Cash({"PXP": 46.0}), closes={e.key: 48.90})
    assert values.get(e.key).payout == 46.0 and values.get(e.key).dividend is None
    assert [(r.sec_id, r.flag) for r in values.review] == [("P", "error")]


# --- what the later stages read --------------------------------------------------------------------------------------

K = DelistingKey("M", "2018-06-01")


def _values(**fields) -> MergerValues:
    return MergerValues({K: MergerValue(K, **fields)})


def test_read_terms_takes_the_gates_terms_then_the_llms_then_the_regex_cash():
    gated = {"stock_ratio": 1.0, "acquirer_price": 20.0, "acquirer_ticker": "X"}
    assert _values(terms=gated, llm=_stock(0.5, "Y")).read_terms(K) == (None, 1.0)
    assert _values(payout=12.0).read_terms(K) == (12.0, None)
    assert _values(llm=_stock(1.0, "Y", cash=2.0)).read_terms(K) == (2.0, 1.0)
    assert _values(raw=replace(PayoutResult.none(), value=9.5, confidence="high", source="8K_2.01")).read_terms(K) == (9.5, None)
    assert _values().read_terms(K) is None
    given = MergerValues({K: MergerValue(K, llm=_stock(1.0, "Y"))}, caller_terms={"M": {"stock_ratio": 1.0}})
    assert given.read_terms(K) is None             # the caller's terms decide the row


def test_the_runs_decisions_read_the_gate_on_its_own_closes():
    """`own_verdict` is the first pass's (payout, terms) when an answer moved the values: R1's reading and
    reconciled read it, the table the values."""
    moved = _values(payout=12.0, source="8K_2.01", own_verdict=(None, None), llm=_stock(1.0, "Y"))
    assert moved.read_terms(K) == (None, 1.0) and not moved.reconciled(K)
    assert moved.table_terms(K).payout_per_share == 12.0
    kept = _values(own_verdict=(12.0, None))
    assert kept.read_terms(K) == (12.0, None) and kept.reconciled(K) and kept.table_terms(K).payout_per_share is None


def test_one_share_and_no_cash_never_reconciles():
    """SPB 2018: one HRG share, the old line's close under the ticker the successor took, proves nothing against a
    continuation; cash, or a kept payout, does."""
    one = {"stock_ratio": 1.0, "acquirer_price": 20.0, "acquirer_ticker": "HRG"}
    assert not _values(terms=one).reconciled(K)
    assert _values(terms={**one, "cash_per_share": 2.0}).reconciled(K)
    assert _values(payout=12.0).reconciled(K)
    assert not _values(llm=_stock(0.5, "Y")).reconciled(K)          # read, never kept


def test_the_callers_terms_reach_every_delisting_of_the_security():
    other = DelistingKey("M", "2012-01-05")                          # an earlier, non-merger delisting
    values = MergerValues({K: MergerValue(K, payout=3.0, source="8K_2.01", confidence="high", flags=("x",))},
                          caller_terms={"M": {"cash_per_share": 5.0}})
    assert values.reconciled(other) and values.read_terms(other) is None
    # delistings.csv: the caller's cash reaches the earlier delisting too; the merger's own record keeps its gate's
    # source, confidence and flags (the caller's row, by sec_id, gives the cash over the gate's payout)
    assert values.table_terms(other) == TableTerms(payout_per_share=5.0)
    assert values.table_terms(K) == TableTerms(5.0, None, None, None, "8K_2.01", "high", ("x",))
    # without the caller's row, the gate's payout is the cash
    gated = MergerValues({K: MergerValue(K, payout=3.0, source="8K_2.01", confidence="high", flags=("x",))})
    assert gated.table_terms(K) == TableTerms(3.0, None, None, None, "8K_2.01", "high", ("x",))
    assert gated.table_terms(other) == TableTerms()


def test_a_dropped_merger_has_no_reads_left():
    """Stage 8b's R1 continuation: a continuation has no value, so nothing of the merger's reads is published."""
    values = _values(raw=replace(PayoutResult.none(), value=9.5, confidence="high", source="8K_2.01"), payout=9.5, flags=("x",))
    values.drop(K)
    assert values.get(K) is None and values.read_terms(K) is None
    assert values.table_terms(K) == TableTerms()


@pytest.mark.parametrize("bucket", ["merger", "exchange_transfer"])
def test_the_contract_inputs_are_the_mergers_records(bucket):
    llm = _stock(0.5, "ACQ")
    values = MergerValues({K: MergerValue(K, llm=llm, acquirer_sec_id="BBG0ACQ", price_ticker="ACQN",
                                          leg_sec_ids={"B": "BBG0B"})})
    got = values.contract_inputs([ending("M", "2018-06-01", bucket)])
    if bucket != "merger":
        assert got == {}
        return
    assert (got[K].llm, got[K].acquirer_sec_id, got[K].price_ticker, got[K].leg_sec_ids) == (
        llm, "BBG0ACQ", "ACQN", {"B": "BBG0B"})


def test_the_llm_calls_are_filled_ahead_on_their_own_threads_whatever_the_sec_workers():
    """`llm_workers` sets the threads that make the LLM calls ahead, apart from the SEC `workers`: one SEC request
    at a time still gets the LLM calls on many threads, and the terms are the one-thread run's."""
    import threading
    threads, guard = [], threading.Lock()
    cash = {"AAA": 10.0, "BBB": 11.0, "CCC": 12.0}      # each ticker's value, whichever thread asks first

    class Ext:
        def extract(self, record, security_name=""):
            with guard:
                threads.append(threading.current_thread().name)
            return MergerTerms("cash", cash[record.ticker], None, None, None, "high", "8-K:x", "",
                               package_basis="fixed")

        def closing_dividend(self, record, security_name=""):
            return None

        def earlier_dividend(self, record, security_name=""):
            return None

    es = [_merger(t, t, "2016-09-16", date(2016, 9, 15)) for t in ("AAA", "BBB", "CCC")]
    one = {k: v.llm for k, v in _value(es, llm=Ext(), workers=1, llm_workers=1).records.items()}
    assert threads == [threading.main_thread().name] * 3
    threads.clear()
    many = {k: v.llm for k, v in _value(es, llm=Ext(), workers=1, llm_workers=4).records.items()}
    assert many == one
    assert sum(n.startswith("sec-warm") for n in threads) == 3 and threads[-3:] == [threading.main_thread().name] * 3


def test_absorb_takes_the_records_and_acquirers_of_another_valuation_and_not_its_review_items():
    from delist_detection.outputs.review_triage import ReviewItem
    k1, k2 = DelistingKey("A", "2020-01-02"), DelistingKey("B", "2021-01-02")
    first = MergerValues({k1: MergerValue(k1, payout=1.0)}, review=[ReviewItem("A", "A", 1, "x", "y")])
    second = MergerValues({k2: MergerValue(k2, payout=2.0)}, added={"BBGACQ": object()},
                          review=[ReviewItem("B", "B", 2, "x", "y")])
    first.absorb(second)
    assert set(first.records) == {k1, k2} and set(first.added) == {"BBGACQ"}
    assert [r.sec_id for r in first.review] == ["A"]


def _acquirer(rows, ticker="ACQ"):
    from delist_detection.identity.added_securities import AddedAcquirer
    from delist_detection.sources.ftd import FtdRow
    sec = Security("BBGACQ", 99, "COMMON", "ACQUIRER CO", "Common Stock", False, "cusip")
    return AddedAcquirer(sec, ticker, date(2020, 1, 2), [FtdRow(d, "C", ticker, "ACQUIRER CO", 10.0) for d in rows])


def test_absorb_keeps_the_first_entry_of_an_acquirer_added_twice_and_extends_its_rows():
    """Stage 8 added acquirer X from its fails rows around one merger; the stage 9d valuation names X again, from the
    rows around another merger. The run has one entry for X: the first, holding the rows of both (its ticker_history
    span runs over every merger that names it, as inside one valuation)."""
    first_entry, again = _acquirer(["2020-01-02", "2020-01-03"]), _acquirer(["2021-05-03"])
    first = MergerValues(added={"BBGACQ": first_entry})
    first.absorb(MergerValues(added={"BBGACQ": again}))
    assert first.added["BBGACQ"] is first_entry
    assert first_entry.span() == ("2020-01-02", "2021-05-03")


def test_absorb_never_replaces_a_security_that_is_not_an_acquirer():
    """An added successor under the same composite stays as it is; the acquirer's rows are not put on it."""
    from delist_detection.identity.added_securities import AddedSuccessor
    sec = Security("BBGACQ", 99, "COMMON", "ACQUIRER CO", "Common Stock", False, "cusip")
    successor = AddedSuccessor(sec, "ACQ", "2020-02-03")
    first = MergerValues(added={"BBGACQ": successor})
    first.absorb(MergerValues(added={"BBGACQ": _acquirer(["2021-05-03"])}))
    assert first.added["BBGACQ"] is successor
    assert successor.span() == ("2020-02-03", "2020-02-03")

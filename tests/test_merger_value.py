"""Stage 8 at its interface (`merger_value.value_mergers` and `MergerValues`): the reads, an unnamed stock leg's
ticker, the received close each stock leg asks and the answer that reaches the gate only through it, and what the
later stages read from the records. The real cases of the acquirer lines and the gate are
tests/test_acquirer_gate_cases.py. Offline."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from delist_detection.acquirer_line import LineIndex
from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import Delisting
from delist_detection.ftd import FtdIndex
from delist_detection.last_trade import LastTrade
from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.merger_value import MergerValue, MergerValues, value_mergers
from delist_detection.payout_extractor import PayoutResult
from delist_detection.price_requests import RECEIVED_CLOSE, PriceAnswers, PriceKey
from delist_detection.security_master import Security
from delist_detection.store import DelistingKey
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
    """An LLM extractor that answers each target from a map (by ticker); `seen` records the names it was told."""

    def __init__(self, answers: dict, calls: list | None = None) -> None:
        self.answers, self.calls, self.seen = answers, calls if calls is not None else [], []

    def extract(self, record, security_name=""):
        self.calls.append(record.ticker)
        self.seen.append((record.ticker, security_name))
        return self.answers.get(record.ticker)


def _value(delistings, *, llm=None, payout=None, edgar=None, resolver=None, ftd_client=None, securities=None,
           closes=None, caller_terms=None, answers=None, workers=1, log=None) -> MergerValues:
    clients = SimpleNamespace(edgar=edgar, resolver=resolver, figi=None, ftd_client=ftd_client or _NoFtd(),
                              payout_extractor=payout, llm_extractor=llm)
    index = LineIndex(securities or {}, {}, {}, FtdIndex())
    return value_mergers(delistings, index, clients=clients, closes=closes or {}, caller_terms=caller_terms or {},
                         answers=answers or PriceAnswers(), tol=0.15, workers=workers, log=log or (lambda *a: None))


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


def test_the_llm_calls_are_filled_ahead_on_worker_threads_with_the_same_answers():
    """With --sec-workers > 1 the LLM extractor runs on the worker threads first (a new prompt version asks every
    merger again); the sequential pass then reads what they cached, so its terms are the one-worker run's."""
    calls, cache = [], {}

    class Ext:                          # caches its answer per target, as LLMMergerTermsExtractor does on disk
        def extract(self, record, security_name=""):
            calls.append(record.ticker)
            return cache.setdefault(record.ticker, MergerTerms("cash", 10.0 + len(cache), None, None, None, "high",
                                                               "8-K:x", "", package_basis="fixed"))

    es = [_merger(t, t, "2016-09-16", date(2016, 9, 15)) for t in ("AAA", "BBB", "CCC")]

    def run(workers):
        values = _value(es, llm=Ext(), workers=workers)
        return {k: v.llm for k, v in values.records.items()}

    one = run(1)
    assert calls == ["AAA", "BBB", "CCC"]
    calls.clear()
    assert run(4) == one and sorted(calls) == ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC"]


# --- 8a': an unnamed stock leg's ticker -----------------------------------------------------------------------------

def _shaw(terms: MergerTerms):
    return _merger("SHAW", "SHAW", "2013-02-28", date(2013, 2, 22), cik=820280), {"SHAW": terms}


def test_an_unnamed_stock_leg_takes_its_ticker_and_keeps_its_other_terms():
    """SHAW 2013's $41.00 + 0.12883 CB&I with no ticker takes CBI (price_ticker blank before: the leg failed the gate
    `no_acq_ticker`), and asks CBI's received close."""
    e, answers = _shaw(MergerTerms("cash_and_stock", 41.0, 0.12883, "CB&I", None, "high", "8-K:0001193125-13-054117",
                                   "", package_basis="fixed"))
    values = _value([e], llm=_Terms(answers), edgar=_EdgarShaw(),
                    resolver=SimpleNamespace(name_index=lambda: INDEX, resolve=None), ftd_client=_Ftd())
    v = values.get(e.key)
    assert (v.llm.acquirer_ticker, v.llm.cash_per_share, v.llm.stock_ratio) == ("CBI", 41.0, 0.12883)
    assert v.request == ("CBI", "") and not values.review
    assert SHAW_TEXT       # the filing the defined term "CB&I" is read in


def test_a_stock_leg_with_its_own_ticker_is_never_named_again():
    def never():
        raise AssertionError("the name index is asked only for a leg with no ticker")

    e, answers = _shaw(MergerTerms("cash_and_stock", 41.0, 0.12883, "CB&I", "XYZ", "high", "8-K:1", ""))
    values = _value([e], llm=_Terms(answers), edgar=_EdgarShaw(),
                    resolver=SimpleNamespace(name_index=never, resolve=lambda *a, **k: SimpleNamespace(cik=None)))
    assert values.get(e.key).llm.acquirer_ticker == "XYZ"


def test_a_failed_name_read_gives_no_ticker_and_a_degraded_review_item():
    e, answers = _shaw(MergerTerms("cash_and_stock", 41.0, 0.12883, "CB&I", None, "high", "8-K:0001193125-13-054117",
                                   ""))
    values = _value([e], llm=_Terms(answers), edgar=_EdgarShaw(fail=True),
                    resolver=SimpleNamespace(name_index=lambda: INDEX), ftd_client=_Ftd())
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
    assert values.requests([ending("A", "2018-12-10"), ending("B", "2019-01-10")]) == {a.key: ("CVS", "")}


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


# --- what the later stages read --------------------------------------------------------------------------------------

K = DelistingKey("M", "2018-06-01")


def _values(**fields) -> MergerValues:
    return MergerValues({K: MergerValue(K, **fields)})


def test_read_terms_takes_the_gates_terms_then_the_llms_then_the_regex_cash():
    gated = {"stock_ratio": 1.0, "acquirer_price": 20.0, "acquirer_ticker": "X"}
    assert _values(terms=gated, llm=_stock(0.5, "Y")).read_terms(K) == (None, 1.0)
    assert _values(payout=12.0).read_terms(K) == (12.0, None)
    assert _values(llm=_stock(1.0, "Y", cash=2.0)).read_terms(K) == (2.0, 1.0)
    assert _values(raw=PayoutResult(9.5, "high", "8K_2.01", "", "")).read_terms(K) == (9.5, None)
    assert _values().read_terms(K) is None
    given = MergerValues({K: MergerValue(K, llm=_stock(1.0, "Y"))}, caller_terms={"M": {"stock_ratio": 1.0}})
    assert given.read_terms(K) is None             # the caller's terms decide the row


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
    t = values.table_inputs()
    assert t["merger_terms"]["M"] == {"cash_per_share": 5.0} and t["payouts"] == {K: 3.0}
    assert (t["payout_sources"], t["payout_confidences"], t["payout_flags"]) == ({K: "8K_2.01"}, {K: "high"},
                                                                                 {K: ("x",)})


def test_a_dropped_merger_has_no_reads_left():
    """Stage 8b's R1 continuation: a continuation has no value, so nothing of the merger's reads is published."""
    values = _values(raw=PayoutResult(9.5, "high", "8K_2.01", "0001", ""), read=True, payout=9.5, flags=("x",))
    assert len(values.payout_rows({K: "MMM"})) == 1
    values.drop(K)
    assert values.get(K) is None and values.payout_rows({K: "MMM"}) == [] and values.read_terms(K) is None
    assert values.table_inputs()["payout_flags"] == {}


def test_a_payout_row_cites_the_filing_its_value_came_from():
    llm = replace(_stock(None, None, cash=12.0), deal_type="cash", source="8-K:0002")
    regex = PayoutResult(11.0, "high", "8K_2.01", "0001", "")
    rows = _values(raw=regex, read=True, llm=llm, payout=12.0, source="llm", confidence="high").payout_rows(
        {K: "MMM"})
    assert rows == [{"sec_id": "M", "delist_date": "2018-06-01", "ticker": "MMM", "payout_per_share": 12.0,
                     "confidence": "high", "source": "llm", "accession": "0002"}]
    unread = _values(raw=None, read=True).payout_rows({K: "MMM"})
    assert unread[0]["source"] == "none" and unread[0]["accession"] is None


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

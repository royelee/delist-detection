"""Offline tests for the LLM merger-terms extractor.

The LLM and EDGAR clients are injected and faked — no network, and caching is
redirected to ``tmp_path`` so nothing is written outside the test sandbox.
"""

from pathlib import Path

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarSubmission
from delist_detection.llm_merger_extractor import (
    LLMMergerTermsExtractor,
    MergerTerms,
    PROMPT_VERSION,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class _FakeLlm:
    """Returns canned dicts from a queue and records calls.

    ``responses`` is consumed in order; once exhausted the last entry repeats.
    Set ``raises=True`` to make every ``extract`` call raise.
    """

    def __init__(self, responses, *, raises=False):
        self._responses = list(responses)
        self._raises = raises
        self.calls = 0
        self.users = []

    def extract(self, system, user, schema):
        self.calls += 1
        self.users.append(user)
        if self._raises:
            raise RuntimeError("LLM hard failure")
        if not self._responses:
            raise AssertionError("no canned response left")
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


class _FakeEdgarText:
    """recent_filings + fetch_filing_text keyed by accession (no network)."""

    def __init__(self, filings, texts):
        self._filings = filings
        self._texts = texts

    def recent_filings(self, cik):
        return list(self._filings)

    def fetch_filing_text(self, cik, accession, primary_doc):
        return self._texts.get(accession, "")


def _merger_rec(cik=1122304, bucket=CrspBucket.MERGER):
    return DelistRecord(
        ticker="AET", cik=cik, observed_delist_date="2018-11-28",
        crsp_code=241, bucket=bucket, confidence="high",
        reason="M&A 2.01+3.01+5.01", evidence={},
    )


def _closing_8k(accession="C1"):
    return EdgarSubmission(
        accession=accession, form="8-K", filing_date="2018-11-30",
        report_date="2018-11-28", items="2.01,3.01,5.01", primary_doc="d.htm",
    )


def _announce_8k(accession="A1"):
    return EdgarSubmission(
        accession=accession, form="8-K", filing_date="2017-12-04",
        report_date="2017-12-03", items="1.01,9.01", primary_doc="d.htm",
    )


_USABLE_TEXT = (
    "each share of Aetna common stock was converted into the right to receive "
    "$145.00 in cash and 0.8378 of a share of CVS Health Corporation common stock"
)


# --------------------------------------------------------------------------- #
# cash + stock
# --------------------------------------------------------------------------- #

def test_cash_and_stock(tmp_path):
    resp = {
        "deal_type": "cash_and_stock", "cash_per_share": 145, "stock_ratio": 0.8378,
        "acquirer_name": "CVS Health", "acquirer_ticker": "CVS",
        "confidence": "high", "quote": "$145.00 in cash and 0.8378 of a share",
    }
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    ext = LLMMergerTermsExtractor(edgar, _FakeLlm([resp]), cache_dir=tmp_path)
    terms = ext.extract(_merger_rec())
    assert isinstance(terms, MergerTerms)
    assert terms.deal_type == "cash_and_stock"
    assert terms.cash_per_share == 145.0
    assert terms.stock_ratio == 0.8378
    assert terms.acquirer_name == "CVS Health"
    assert terms.acquirer_ticker == "CVS"
    assert terms.confidence == "high"
    assert terms.source == "8-K:C1"
    assert terms.to_merger_terms_dict() == {
        "cash_per_share": 145.0, "stock_ratio": 0.8378, "acquirer_ticker": "CVS",
    }


def test_stock_only_omits_cash(tmp_path):
    resp = {
        "deal_type": "stock", "cash_per_share": None, "stock_ratio": 1.05,
        "acquirer_name": "Buyer Inc", "acquirer_ticker": "BUY",
        "confidence": "high", "quote": "1.05 shares",
    }
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    ext = LLMMergerTermsExtractor(edgar, _FakeLlm([resp]), cache_dir=tmp_path)
    terms = ext.extract(_merger_rec())
    assert terms.cash_per_share is None
    assert terms.to_merger_terms_dict() == {
        "stock_ratio": 1.05, "acquirer_ticker": "BUY",
    }
    assert "cash_per_share" not in terms.to_merger_terms_dict()


def test_cash_only_omits_stock_and_ticker(tmp_path):
    resp = {
        "deal_type": "cash", "cash_per_share": 113.0, "stock_ratio": None,
        "acquirer_name": "Buyer Inc", "acquirer_ticker": None,
        "confidence": "high", "quote": "$113.00 in cash",
    }
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    ext = LLMMergerTermsExtractor(edgar, _FakeLlm([resp]), cache_dir=tmp_path)
    terms = ext.extract(_merger_rec())
    assert terms.to_merger_terms_dict() == {"cash_per_share": 113.0}
    assert "stock_ratio" not in terms.to_merger_terms_dict()
    assert "acquirer_ticker" not in terms.to_merger_terms_dict()


def test_no_consideration_returns_none(tmp_path):
    resp = {
        "deal_type": "other", "cash_per_share": None, "stock_ratio": None,
        "acquirer_name": None, "acquirer_ticker": None,
        "confidence": "low", "quote": "",
    }
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    ext = LLMMergerTermsExtractor(edgar, _FakeLlm([resp]), cache_dir=tmp_path)
    assert ext.extract(_merger_rec()) is None


def test_llm_raises_returns_none(tmp_path):
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    ext = LLMMergerTermsExtractor(edgar, _FakeLlm([], raises=True), cache_dir=tmp_path)
    assert ext.extract(_merger_rec()) is None


def test_non_merger_bucket_skips_clients(tmp_path):
    llm = _FakeLlm([])

    class _Boom:
        def recent_filings(self, cik):
            raise AssertionError("edgar must not be called")
        def fetch_filing_text(self, cik, acc, doc):
            raise AssertionError("edgar must not be called")

    ext = LLMMergerTermsExtractor(_Boom(), llm, cache_dir=tmp_path)
    assert ext.extract(_merger_rec(bucket=CrspBucket.COMPLIANCE_FAILURE)) is None
    assert llm.calls == 0


def test_cik_none_skips_clients(tmp_path):
    llm = _FakeLlm([])

    class _Boom:
        def recent_filings(self, cik):
            raise AssertionError("edgar must not be called")
        def fetch_filing_text(self, cik, acc, doc):
            raise AssertionError("edgar must not be called")

    ext = LLMMergerTermsExtractor(_Boom(), llm, cache_dir=tmp_path)
    assert ext.extract(_merger_rec(cik=None)) is None
    assert llm.calls == 0


def test_cache_hit_second_call_served_from_disk(tmp_path):
    resp = {
        "deal_type": "cash", "cash_per_share": 113.0, "stock_ratio": None,
        "acquirer_name": None, "acquirer_ticker": None,
        "confidence": "high", "quote": "$113.00 in cash",
    }
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    llm = _FakeLlm([resp])
    ext = LLMMergerTermsExtractor(edgar, llm, model="m1", cache_dir=tmp_path)
    first = ext.extract(_merger_rec())
    second = ext.extract(_merger_rec())
    assert first.cash_per_share == second.cash_per_share == 113.0
    assert llm.calls == 1                       # second served from cache
    cache_files = list(Path(tmp_path).glob("*.json"))
    assert cache_files, "cache file should have been written"
    assert any(PROMPT_VERSION in p.name for p in cache_files)  # prompt version tags the cache key


def test_tolerant_float_parse(tmp_path):
    resp = {
        "deal_type": "cash", "cash_per_share": "$145.00", "stock_ratio": None,
        "acquirer_name": None, "acquirer_ticker": None,
        "confidence": "high", "quote": "$145.00 in cash",
    }
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    ext = LLMMergerTermsExtractor(edgar, _FakeLlm([resp]), cache_dir=tmp_path)
    terms = ext.extract(_merger_rec())
    assert terms.cash_per_share == 145.0


def test_filing_preference_closing_before_announcement(tmp_path):
    # Closing 8-K (C1) carries usable terms; it must be tried before the
    # announcement 8-K (A1), so its accession ends up in the source.
    closing = _closing_8k("C1")
    announce = _announce_8k("A1")
    resp = {
        "deal_type": "cash_and_stock", "cash_per_share": 145.0, "stock_ratio": 0.8378,
        "acquirer_name": "CVS Health", "acquirer_ticker": "CVS",
        "confidence": "high", "quote": "...",
    }
    # Both filings have usable text; whichever is tried first wins.
    edgar = _FakeEdgarText(
        [announce, closing],     # deliberately out of preference order
        {"C1": _USABLE_TEXT, "A1": _USABLE_TEXT},
    )
    ext = LLMMergerTermsExtractor(edgar, _FakeLlm([resp]), cache_dir=tmp_path)
    terms = ext.extract(_merger_rec())
    assert terms.source == "8-K:C1"


def test_user_prompt_includes_framing(tmp_path):
    resp = {
        "deal_type": "cash", "cash_per_share": 113.0, "stock_ratio": None,
        "acquirer_name": None, "acquirer_ticker": None,
        "confidence": "high", "quote": "$113.00 in cash",
    }
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    llm = _FakeLlm([resp])
    ext = LLMMergerTermsExtractor(edgar, llm, cache_dir=tmp_path)
    ext.extract(_merger_rec())
    assert llm.users, "LLM should have been called"
    user = llm.users[0]
    assert "AET" in user
    assert "2018-11-28" in user


def test_max_filings_caps_llm_calls(tmp_path):
    # Three closing-8-K candidates, none usable; max_filings=2 caps LLM calls.
    f1 = _closing_8k("C1")
    f2 = EdgarSubmission(accession="C2", form="8-K", filing_date="2018-11-29",
                         report_date="2018-11-27", items="2.01", primary_doc="d.htm")
    f3 = EdgarSubmission(accession="C3", form="8-K", filing_date="2018-11-26",
                         report_date="2018-11-25", items="2.01", primary_doc="d.htm")
    null_resp = {
        "deal_type": "other", "cash_per_share": None, "stock_ratio": None,
        "acquirer_name": None, "acquirer_ticker": None, "confidence": "low", "quote": "",
    }
    edgar = _FakeEdgarText(
        [f1, f2, f3],
        {"C1": _USABLE_TEXT, "C2": _USABLE_TEXT, "C3": _USABLE_TEXT},
    )
    llm = _FakeLlm([null_resp])
    ext = LLMMergerTermsExtractor(edgar, llm, max_filings=2, cache_dir=tmp_path)
    assert ext.extract(_merger_rec()) is None
    assert llm.calls == 2


def test_empty_text_skipped_does_not_count(tmp_path):
    # First candidate has empty text (skipped, not counted toward max_filings);
    # the second has usable text and yields terms.
    f1 = _closing_8k("C1")
    f2 = EdgarSubmission(accession="C2", form="8-K", filing_date="2018-11-29",
                         report_date="2018-11-27", items="2.01", primary_doc="d.htm")
    resp = {
        "deal_type": "cash", "cash_per_share": 145.0, "stock_ratio": None,
        "acquirer_name": None, "acquirer_ticker": None, "confidence": "high", "quote": "x",
    }
    edgar = _FakeEdgarText([f1, f2], {"C1": "", "C2": _USABLE_TEXT})
    llm = _FakeLlm([resp])
    ext = LLMMergerTermsExtractor(edgar, llm, max_filings=1, cache_dir=tmp_path)
    terms = ext.extract(_merger_rec())
    assert terms is not None
    assert terms.source == "8-K:C2"
    assert llm.calls == 1


from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor as _Ext


def test_relevant_excerpts_windows_keywords(tmp_path):
    edgar = _FakeEdgarText([], {})
    ext = LLMMergerTermsExtractor(edgar, _FakeLlm([]), cache_dir=tmp_path)
    text = "x" * 5000 + " right to receive $145.00 in cash " + "y" * 5000
    exc = ext._relevant_excerpts(text)
    assert "right to receive $145.00 in cash" in exc
    assert len(exc) < len(text)


def test_relevant_excerpts_fallback_no_keywords(tmp_path):
    edgar = _FakeEdgarText([], {})
    ext = LLMMergerTermsExtractor(edgar, _FakeLlm([]), cache_dir=tmp_path)
    text = "z" * 40000
    exc = ext._relevant_excerpts(text)
    assert len(exc) == 30000


def test_dedup_by_accession(tmp_path):
    # The same accession appears as both a closing 8-K and (hypothetically) in a
    # later selection bucket; it must only be tried once.
    f = _closing_8k("C1")
    null_resp = {
        "deal_type": "other", "cash_per_share": None, "stock_ratio": None,
        "acquirer_name": None, "acquirer_ticker": None, "confidence": "low", "quote": "",
    }
    edgar = _FakeEdgarText([f, f], {"C1": _USABLE_TEXT})
    llm = _FakeLlm([null_resp])
    ext = LLMMergerTermsExtractor(edgar, llm, cache_dir=tmp_path)
    assert ext.extract(_merger_rec()) is None
    assert llm.calls == 1


def test_network_error_returns_none(tmp_path):
    import requests

    class _RaisingEdgar:
        def recent_filings(self, cik):
            raise requests.ConnectionError("dropped")
        def fetch_filing_text(self, cik, acc, doc):
            raise requests.ConnectionError("dropped")

    ext = LLMMergerTermsExtractor(_RaisingEdgar(), _FakeLlm([]), cache_dir=tmp_path)
    assert ext.extract(_merger_rec()) is None

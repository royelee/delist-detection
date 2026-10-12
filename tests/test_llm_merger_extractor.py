"""Offline tests for the LLM merger-terms extractor.

The LLM and EDGAR clients are injected and faked — no network, and caching is
redirected to ``tmp_path`` so nothing is written outside the test sandbox.
"""

from pathlib import Path

import pytest
import requests

from delist_detection.outputs.reconstruction import DelistRecord
from delist_detection.vocabulary.crsp_codes import CrspBucket
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.terms.llm_merger_extractor import (
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
    Set ``raises=True`` to make every ``extract`` call raise. It names no
    model (``model``).
    """

    model = None

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


def test_usage_counts_the_runs_answers_by_where_they_came_from(tmp_path):
    """run_manifest.json's `merger_terms` (FB-004's model provenance): the sequential pass's answers, each from the
    cache as the run found it, asked of the model this run (a warm thread's fill included), or failed."""
    from delist_detection.sources.sec_stats import fill_only
    resp = {"deal_type": "cash", "cash_per_share": 113.0, "stock_ratio": None, "acquirer_name": None,
            "acquirer_ticker": None, "confidence": "high", "quote": "$113.00 in cash"}
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    LLMMergerTermsExtractor(edgar, _FakeLlm([resp]), model="m1", cache_dir=tmp_path).extract(_merger_rec())
    cached = LLMMergerTermsExtractor(edgar, _FakeLlm([]), model="m1", cache_dir=tmp_path)   # a later run
    cached.extract(_merger_rec())
    assert cached.usage() == {"model": "m1", "answers": 1, "from_cache": 1, "asked": 0, "failed": 0}

    warm = LLMMergerTermsExtractor(edgar, _FakeLlm([resp]), model="m2", cache_dir=tmp_path)
    with fill_only():
        warm.extract(_merger_rec())             # the warm pass asks; it is not the run's answer
    warm.extract(_merger_rec())                 # the sequential pass reads what the warm pass cached
    assert warm.usage() == {"model": "m2", "answers": 1, "from_cache": 0, "asked": 1, "failed": 0}

    failing = LLMMergerTermsExtractor(edgar, _FakeLlm([], raises=True), model="m3", cache_dir=tmp_path)
    failing.extract(_merger_rec())
    assert failing.usage() == {"model": "m3", "answers": 0, "from_cache": 0, "asked": 0, "failed": 1}


def test_cache_is_labelled_with_the_clients_own_model(tmp_path, monkeypatch):
    """The cache label is the model the injected client calls, ahead of
    $CHAT_MODEL: an answer cached for another model is not reused."""
    monkeypatch.setenv("CHAT_MODEL", "m1")
    resp = {"deal_type": "cash", "cash_per_share": 113.0, "stock_ratio": None, "acquirer_name": None,
            "acquirer_ticker": None, "confidence": "high", "quote": "$113.00 in cash"}
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    other = _FakeLlm([dict(resp, cash_per_share=1.0)])           # states no model (None): labelled $CHAT_MODEL
    LLMMergerTermsExtractor(edgar, other, cache_dir=tmp_path).extract(_merger_rec())
    llm = _FakeLlm([resp])
    llm.model = "m2"
    terms = LLMMergerTermsExtractor(edgar, llm, cache_dir=tmp_path).extract(_merger_rec())
    assert llm.calls == 1
    assert terms.cash_per_share == 113.0
    assert sorted(p.name for p in tmp_path.glob("*.json")) == [
        f"C1_m1_{PROMPT_VERSION}_AET.json", f"C1_m2_{PROMPT_VERSION}_AET.json"]


def test_an_llm_client_that_states_no_model_at_all_is_refused(tmp_path):
    """`llm_client`'s interface: a client states the model it calls, or None; one that states nothing is never
    labelled by a default."""
    class Silent:
        def extract(self, system, user, schema):
            return {}

    with pytest.raises(AttributeError):
        LLMMergerTermsExtractor(_FakeEdgarText([], {}), Silent(), cache_dir=tmp_path)
    assert LLMMergerTermsExtractor(_FakeEdgarText([], {}), Silent(), model="m", cache_dir=tmp_path).model == "m"


def test_an_answer_cut_off_mid_write_leaves_no_cache_file(tmp_path, writes_fail_midway):
    """A run that dies while caching the LLM's answer leaves no cut-off JSON
    file: the answer is written through atomic_io.write_atomic."""
    resp = {"deal_type": "cash", "cash_per_share": 113.0, "stock_ratio": None, "acquirer_name": None,
            "acquirer_ticker": None, "confidence": "high", "quote": "$113.00 in cash"}
    ext = LLMMergerTermsExtractor(_FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT}), _FakeLlm([resp]),
                                  model="m1", cache_dir=tmp_path)
    writes_fail_midway(tmp_path)
    ext.extract(_merger_rec())
    assert list(tmp_path.iterdir()) == []


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


def _offer_doc(accession, form, day):
    return EdgarSubmission(accession=accession, form=form, filing_date=day, report_date="", items="",
                           primary_doc="d.htm")


_NO_TERMS = {"deal_type": "other", "cash_per_share": None, "stock_ratio": None, "acquirer_name": None,
             "acquirer_ticker": None, "confidence": "low", "quote": ""}
_RATIO = {"deal_type": "stock", "cash_per_share": None, "stock_ratio": 0.05363, "acquirer_name": "BioNTech SE",
          "acquirer_ticker": "BNTX", "confidence": "high", "quote": "0.05363 of a BioNTech ADS per CureVac share"}


def test_the_offers_own_documents_are_read_newest_first_by_form(tmp_path):
    """FB-016 (CureVac 2026): the offer's documents EDGAR lists under the target, on or before the delisting: the
    SC TO-T and its amendments newest first (CureVac's ratio is in the third newest), then the Rule 425 filings, then
    the SC 14D9, `max_filings` of each at most, and the first that states a leg answers. An amendment of the SC 14D9
    and a document filed after the delisting are not read. `extract` reads none of them."""
    filings = [_offer_doc("T0", "SC TO-T", "2018-10-21"), _offer_doc("T1", "SC TO-T/A", "2018-11-20"),
               _offer_doc("T9", "SC TO-T/A", "2018-12-03"),              # after the delisting of 2018-11-28
               _offer_doc("R0", "425", "2018-11-01"), _offer_doc("R1", "425", "2018-11-26"),
               _offer_doc("D0", "SC 14D9", "2018-10-21"), _offer_doc("D1", "SC 14D9/A", "2018-11-27")]
    texts = {f.accession: "the exchange ratio per share is stated here " + f.accession for f in filings}
    edgar = _FakeEdgarText(filings, texts)
    llm = _FakeLlm([_NO_TERMS, _NO_TERMS, _RATIO])
    ext = LLMMergerTermsExtractor(edgar, llm, cache_dir=tmp_path)
    assert ext.extract(_merger_rec()) is None and llm.calls == 0          # no first-choice filing at all
    terms = ext.extract_offer_terms(_merger_rec())
    assert (terms.stock_ratio, terms.acquirer_ticker, terms.source) == (0.05363, "BNTX", "425:R1")
    assert [u.rsplit(" ", 1)[-1] for u in llm.users] == ["T1", "T0", "R1"]   # the bidder's statements, then the 425s
    llm2 = _FakeLlm([_NO_TERMS])
    ext2 = LLMMergerTermsExtractor(edgar, llm2, cache_dir=tmp_path / "none")
    assert ext2.extract_offer_terms(_merger_rec()) is None
    assert [u.rsplit(" ", 1)[-1] for u in llm2.users] == ["T1", "T0", "R1", "R0", "D0"]
    llm3 = _FakeLlm([_NO_TERMS])
    ext3 = LLMMergerTermsExtractor(edgar, llm3, max_filings=1, cache_dir=tmp_path / "one")
    assert ext3.extract_offer_terms(_merger_rec()) is None
    assert [u.rsplit(" ", 1)[-1] for u in llm3.users] == ["T1", "R1", "D0"]


def test_offer_documents_are_a_mergers_only_and_a_network_error_is_a_miss(tmp_path):
    class _Down(_FakeEdgarText):
        def fetch_filing_text(self, cik, accession, primary_doc):
            raise requests.ConnectionError("down")
    filings = [_offer_doc("T1", "SC TO-T/A", "2018-11-20")]
    llm = _FakeLlm([_RATIO])
    ext = LLMMergerTermsExtractor(_Down(filings, {}), llm, cache_dir=tmp_path)
    assert ext.extract_offer_terms(_merger_rec()) is None and llm.calls == 0
    ok = LLMMergerTermsExtractor(_FakeEdgarText(filings, {"T1": "ratio T1"}), llm, cache_dir=tmp_path)
    assert ok.extract_offer_terms(_merger_rec(bucket=CrspBucket.LIQUIDATION)) is None and llm.calls == 0
    assert ok.extract_offer_terms(_merger_rec(cik=None)) is None and llm.calls == 0


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


def test_threads_asking_for_one_answer_file_pay_for_one_call(tmp_path):
    """Two mergers can ask for one file (the same filing and target ticker) and the warm threads run them at once:
    the second waits for the first's call and reads its answer, so the model is called once."""
    import threading
    import time
    resp = {"deal_type": "cash", "cash_per_share": 10.0, "stock_ratio": None, "acquirer_name": "X",
            "acquirer_ticker": None, "confidence": "high", "quote": "$10.00 in cash", "package_basis": "fixed"}

    class _Slow(_FakeLlm):
        def extract(self, system, user, schema):
            time.sleep(0.2)                   # long enough for every thread to be waiting for the answer
            return super().extract(system, user, schema)

    llm = _Slow([resp])
    edgar = _FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT})
    ext = LLMMergerTermsExtractor(edgar, llm, cache_dir=tmp_path)
    got: list = []
    threads = [threading.Thread(target=lambda: got.append(ext.extract(_merger_rec()))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert llm.calls == 1 and len(got) == 6 and all(t == got[0] and t.cash_per_share == 10.0 for t in got)


def _concurrent_extract(ext, n, *, warm):
    import threading

    from delist_detection.sources.sec_stats import fill_only

    def ask():
        if warm:
            with fill_only():
                ext.extract(_merger_rec())
        else:
            ext.extract(_merger_rec())

    threads = [threading.Thread(target=ask) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _slow_ext(tmp_path):
    import time
    resp = {"deal_type": "cash", "cash_per_share": 10.0, "stock_ratio": None, "acquirer_name": "X",
            "acquirer_ticker": None, "confidence": "high", "quote": "$10.00 in cash", "package_basis": "fixed"}

    class _Slow(_FakeLlm):
        def extract(self, system, user, schema):
            time.sleep(0.2)
            return super().extract(system, user, schema)

    llm = _Slow([resp])
    return LLMMergerTermsExtractor(_FakeEdgarText([_closing_8k()], {"C1": _USABLE_TEXT}), llm, cache_dir=tmp_path), llm


def test_threads_that_waited_for_one_answer_count_it_as_any_cache_read_is_counted(tmp_path):
    """Six sequential-pass threads ask for one file: one asked the model (`asked`), the five that waited read its
    answer (`asked` too, since this run asked for it): the count is that of six cache reads after one call."""
    ext, llm = _slow_ext(tmp_path)
    _concurrent_extract(ext, 6, warm=False)
    u = ext.usage()
    assert llm.calls == 1 and (u["asked"], u["from_cache"], u["failed"], u["answers"]) == (6, 0, 0, 6)


def test_a_warm_pass_counts_nothing_and_the_sequential_read_after_it_counts_asked(tmp_path):
    """The warm threads' own reads are not counted, however many wait on the lock; the sequential pass then reads the
    file the warm pass asked for and counts it once as `asked`."""
    ext, llm = _slow_ext(tmp_path)
    _concurrent_extract(ext, 6, warm=True)
    assert llm.calls == 1 and ext.usage()["answers"] == 0 and ext.usage()["asked"] == 0
    ext.extract(_merger_rec())
    u = ext.usage()
    assert (u["asked"], u["from_cache"], u["failed"]) == (1, 0, 0)

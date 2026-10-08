"""The clients' optional capabilities at the `Clients` seam (`capabilities`, `pipeline.Clients`): each adapter
states a capability offered or absent, an adapter that states nothing is refused, a run logs each absent one once,
and production's adapters offer them all."""
from __future__ import annotations

from datetime import date

import pytest

from delist_detection import pipeline, sec_limiter
from delist_detection.capabilities import CAPABILITIES, FULL_TEXT_SEARCH, NAMED_LLM_CALL, Undeclared, offers, stated
from delist_detection.classifier import DelistClassifier
from delist_detection.issuer_record import IssuerRecord
from delist_detection.observations import Observation, ObservationIndex
from delist_detection.pipeline import Clients, Overrides, run
from test_pipeline import _clients


class _Searching:
    """EDGAR offering full-text search."""

    def full_text_search(self, q, forms, lo, hi, *, ciks=()):
        return []


class _NoSearch:
    """EDGAR stating full-text search absent."""

    full_text_search = None


class _Silent:
    """An adapter that states nothing."""


class _Named:
    names_security = True

    def extract(self, record, security_name=""):
        return None


class _Unnamed:
    names_security = False

    def extract(self, record):
        return None


def _seam(edgar=None, llm=None, **kw) -> Clients:
    return Clients(edgar=edgar, resolver=None, classifier=None, figi=None, ftd_client=None, llm_extractor=llm, **kw)


def test_every_capability_names_its_client_and_what_the_run_goes_without():
    assert CAPABILITIES == (FULL_TEXT_SEARCH, NAMED_LLM_CALL)
    assert [c.name for c in CAPABILITIES] == ["edgar.full_text_search", "llm_extractor.names_security"]
    assert all(c.client in Clients.__dataclass_fields__ and c.without for c in CAPABILITIES)


def test_an_offered_full_text_search_is_the_adapters_own():
    edgar = _Searching()
    c = _seam(edgar)
    assert c.full_text_search == edgar.full_text_search and c.absent() == ()


def test_a_full_text_search_stated_absent_is_none_and_listed_absent():
    c = _seam(_NoSearch())
    assert c.full_text_search is None and c.absent() == (FULL_TEXT_SEARCH,)


def test_the_named_llm_call_offered_or_stated_absent():
    assert _seam(llm=_Named()).names_security is True and _seam(llm=_Named()).absent() == ()
    c = _seam(llm=_Unnamed())
    assert c.names_security is False and c.absent() == (NAMED_LLM_CALL,)


def test_a_client_left_out_offers_nothing_and_is_no_absent_capability():
    """`--no-midas`-like: a client the caller left out (None) is the caller's choice, not a capability the run goes
    without."""
    c = _seam()
    assert (c.full_text_search, c.names_security, c.absent()) == (None, False, ())
    assert not offers(None, FULL_TEXT_SEARCH)


@pytest.mark.parametrize("seam", [lambda: _seam(_Silent()), lambda: _seam(llm=_Silent())], ids=["edgar", "llm"])
def test_an_adapter_that_states_nothing_is_refused(seam):
    c = seam()
    with pytest.raises(Undeclared, match="_Silent states nothing about"):
        c.absent()


def test_the_refusal_names_the_capability_and_how_to_state_it():
    with pytest.raises(Undeclared, match=r"edgar\.full_text_search: give it `full_text_search`, or set "
                                         r"`full_text_search` to None"):
        _seam(_Silent()).full_text_search
    with pytest.raises(Undeclared, match=r"llm_extractor\.names_security"):
        _seam(llm=_Silent()).names_security
    assert stated(_NoSearch(), FULL_TEXT_SEARCH) is None


def test_a_run_logs_each_absent_capability_once_before_anything_is_read(fake_edgar, tmp_path):
    """conftest's EDGAR double states the search absent; an extractor states its named call absent."""
    index, clients = _clients(fake_edgar)
    clients.llm_extractor = _Unnamed()
    lines: list[str] = []
    run(index, clients, Overrides(), out_dir=tmp_path, log=lines.append)
    absent = [i for i, line in enumerate(lines) if line.startswith("capability absent")]
    assert [lines[i] for i in absent] == [
        f"capability absent: edgar.full_text_search: {FULL_TEXT_SEARCH.without}",
        f"capability absent: llm_extractor.names_security: {NAMED_LLM_CALL.without}"]
    assert absent == [0, 1]


def test_a_run_whose_adapters_offer_every_capability_logs_none(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    fake_edgar.full_text_search = lambda q, forms, lo, hi, *, ciks=(): []
    clients.llm_extractor = _Named()
    lines: list[str] = []
    run(index, clients, Overrides(), out_dir=tmp_path, log=lines.append)
    assert not [line for line in lines if "capability absent" in line]


def test_a_run_with_an_adapter_that_states_nothing_stops_before_writing(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    clients.llm_extractor = _Silent()
    with pytest.raises(Undeclared):
        run(index, clients, Overrides(), out_dir=tmp_path / "out", log=lambda *_: None)
    assert not (tmp_path / "out").exists()


def test_default_clients_offer_every_capability(tmp_path, monkeypatch):
    """Production's adapters offer every capability, and the required reads the stages make of them."""
    monkeypatch.setenv(sec_limiter.SEC_RATE_LOCK_ENV, str(tmp_path / "sec_rate.lock"))
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: False)   # the repo .env stays out of os.environ
    index = ObservationIndex([Observation("AET", "2018-06-29", "AETNA INC")])
    c = pipeline.default_clients(index, cache_dir=tmp_path / "cache", as_of=date(2026, 9, 23), extract_llm=True,
                                 llm_model="model-b")
    assert c.absent() == ()
    assert c.full_text_search == c.edgar.full_text_search and c.names_security is True
    assert c.llm_extractor.llm.model == "model-b"                          # the LLM client states its model
    for read in (c.edgar.submissions, c.edgar.recent_filings, c.edgar.fetch_filing_text, c.edgar.fetch_filing_raw,
                 c.edgar.company_tickers, c.resolver.flush, c.resolver.shadow, c.classifier.shadow,
                 c.halts.failed_days):
        assert callable(read)
    assert c.issuers is c.resolver.issuers is c.classifier.issuers


def test_the_run_reads_the_issuer_record_its_resolver_or_classifier_states(fake_edgar):
    class Lookup:
        def __init__(self, issuers):
            self.issuers = issuers

    held = IssuerRecord(fake_edgar)
    assert Clients(fake_edgar, Lookup(held), None, None, None).issuers is held
    cls = DelistClassifier(fake_edgar, None)
    assert Clients(fake_edgar, Lookup(None), cls, None, None).issuers is cls.issuers
    fresh = Clients(fake_edgar, Lookup(None), None, None, None, as_of=date(2026, 9, 23)).issuers
    assert fresh is not held and fresh.edgar is fake_edgar and fresh.today == date(2026, 9, 23)
    assert Clients(fake_edgar, Lookup(held), cls, None, None, issuers=fresh).issuers is fresh
    with pytest.raises(AttributeError):          # a resolver must state its record, None included
        Clients(fake_edgar, _Silent(), None, None, None)


def test_the_classifiers_shadow_reads_through_a_shadow_of_its_issuer_record(fake_edgar):
    """The delisting search's warm finders read through it (`pipeline._warm_delisting_search`)."""
    cls = DelistClassifier(fake_edgar, None)
    cls.issuers.profile(1701732)
    twin = cls.shadow()
    assert twin is not cls and (twin.edgar, twin.resolver, twin.today) == (cls.edgar, cls.resolver, cls.today)
    assert twin.issuers is not cls.issuers and twin.issuers.edgar is cls.issuers.edgar
    assert twin.reader.issuers is twin.issuers                   # its own-share reads go through the shadow too
    twin.issuers.profile(999001)
    assert 999001 not in cls.issuers._profiles and 1701732 in twin.issuers._profiles

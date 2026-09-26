"""The resolver's on-disk memo: versioned, keyed by the member name, and never
holding an answer reached through a transient EDGAR error."""
import json
import logging
from datetime import date

import pytest
import requests

from delist_detection.edgar import STALE_KEY
from delist_detection.ticker_resolver import TickerResolver

KEY = "ALTR|2025-03-26"
STALE = {"ticker": "ALTR", "cik": 999999, "name": "Altera Corp", "source": "efts"}


def _member(name):
    return lambda t, d=None: name


def test_an_old_flat_cache_is_ignored_and_replaced(tmp_path, fake_edgar, caplog):
    cache = tmp_path / "res.json"
    cache.write_text(json.dumps({KEY: STALE}))
    with caplog.at_level(logging.WARNING):
        r = TickerResolver(fake_edgar, cache_path=cache)
    assert sum("ignor" in m for m in caplog.messages) == 1
    assert r.resolve("ALTR", "2025-03-26").cik == 1701732      # company_tickers, not the stale 999999
    saved = json.loads(cache.read_text())
    assert saved["__version__"] == 3
    assert saved["entries"][KEY]["cik"] == 1701732


def test_a_v3_cache_round_trips(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    r = TickerResolver(fake_edgar, cache_path=cache, observed_names=_member("Altair Engineering Inc"))
    assert r.resolve("ALTR", "2025-03-26").cik == 1701732
    saved = json.loads(cache.read_text())
    assert saved == {"__version__": 3, "entries": {KEY: {
        "ticker": "ALTR", "cik": 1701732, "name": "Altair Engineering Inc.",
        "source": "company_tickers", "member_name": "Altair Engineering Inc"}}}
    # a fresh resolver answers from the file, with no EDGAR reads
    r2 = TickerResolver(None, cache_path=cache, observed_names=_member("Altair Engineering Inc"))
    assert r2.resolve("ALTR", "2025-03-26").cik == 1701732


def test_a_different_member_name_misses_the_cache(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    cache.write_text(json.dumps({"__version__": 3, "entries": {KEY: {**STALE, "member_name": "Altera Corp"}}}))
    same = TickerResolver(fake_edgar, cache_path=cache, observed_names=_member("Altera Corp"))
    assert same.resolve("ALTR", "2025-03-26").cik == 999999
    other = TickerResolver(fake_edgar, cache_path=cache, observed_names=_member("Altair Engineering Inc"))
    assert other.resolve("ALTR", "2025-03-26").cik == 1701732
    # an entry saved without a member name misses a lookup that has one
    cache.write_text(json.dumps({"__version__": 3, "entries": {KEY: {**STALE, "member_name": None}}}))
    named = TickerResolver(fake_edgar, cache_path=cache, observed_names=_member("Altair Engineering Inc"))
    assert named.resolve("ALTR", "2025-03-26").cik == 1701732


class _FlakyEdgar:
    """Wraps FakeEdgar; the first recent_filings() call raises a transient error."""

    def __init__(self, inner):
        self.inner, self.failed = inner, False

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def recent_filings(self, cik):
        if not self.failed:
            self.failed = True
            raise requests.ConnectionError("connection reset")
        return self.inner.recent_filings(cik)


def test_an_answer_reached_through_a_transient_error_is_not_persisted(tmp_path, fake_edgar, monkeypatch):
    # company_tickers holds the right CIK, but its date check hits a transient
    # error; the EFTS tier then answers with another company, which is returned
    # for this run but never written to the cache.
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (999002, "Liquidating Trust (ALTR)", False))
    monkeypatch.setattr(TickerResolver, "_validate_cik", lambda self, *a, **kw: True)
    cache = tmp_path / "res.json"
    r = TickerResolver(_FlakyEdgar(fake_edgar), cache_path=cache)
    assert r.resolve("ALTR", "2025-03-26").cik == 999002
    assert not cache.exists() or KEY not in cache.read_text()
    # a later answer with no transient error is persisted as usual
    assert r.resolve("BAD", "2023-05-10").cik == 999001
    saved = json.loads(cache.read_text())["entries"]
    assert set(saved) == {"BAD|2023-05-10"}
    # the next run retries and finds the right company
    assert TickerResolver(fake_edgar, cache_path=cache).resolve("ALTR", "2025-03-26").cik == 1701732


# --- F16: the resolver's own submissions reads are fresh past the event ---

class _RecordingEdgar:
    """Wraps FakeEdgar; logs the resolver's submissions and recent_filings reads."""

    def __init__(self, inner):
        self.inner, self.log = inner, []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def submissions(self, cik, fresh_after=None):
        self.log.append(("sub", int(cik), fresh_after))
        return self.inner.submissions(cik)

    def recent_filings(self, cik):
        self.log.append(("filings", int(cik)))
        return self.inner.recent_filings(cik)


def test_every_resolver_read_is_fresh_past_the_event(fake_edgar, monkeypatch):
    from datetime import date
    # tier 3 runs: the strict check reads filings, the name score reads submissions
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: [(999001, "Bad Co.")])
    e = _RecordingEdgar(fake_edgar)
    r = TickerResolver(e, observed_names=_member("Bad Company Holdings"))
    assert r.resolve("ZZZ", "2023-05-12").cik == 999001
    want = date(2023, 6, 26)                      # observed + 45 days (before today)
    assert e.log and {x[2] for x in e.log if x[0] == "sub"} == {want}
    fresh = set()
    for x in e.log:
        if x[0] == "sub":
            fresh.add(x[1])
        else:
            assert x[1] in fresh, f"filings of {x[1]} read before a fresh submissions read: {e.log}"


def test_a_stale_cached_copy_is_refetched_before_the_resolver_checks_it(tmp_path, monkeypatch):
    # LBRDA: the cache (2026-05-26) holds only the 2015 Form 25; the 2026-08-20 one is live
    from delist_detection.edgar import EdgarClient

    def recent(*rows):
        keys = ("accessionNumber", "form", "filingDate", "reportDate", "items", "primaryDocument")
        return {"recent": {k: [row[i] for row in rows] for i, k in enumerate(keys)}}
    old = [("A1", "10-K", "2014-11-01", "", "", "k.htm"), ("A2", "25-NSE", "2015-06-01", "", "", "p.xml")]
    stale = {"name": "Liberty Broadband Corp", "formerNames": [], "filings": recent(*old),
             "__fetched__": "2026-05-26"}
    live = {**stale, "filings": recent(*old, ("A3", "25-NSE", "2026-08-20", "", "", "p.xml"))}
    live.pop("__fetched__")

    class _Resp:
        status_code, url = 200, "https://data.sec.gov/submissions/CIK0001611983.json"

        def json(self):
            return json.loads(json.dumps(live))

        def raise_for_status(self):
            pass

    class _Session:
        headers, calls = {}, []

        def get(self, url, headers=None, timeout=None):
            self.calls.append(url)
            return _Resp()

    client = EdgarClient(cache_dir=tmp_path, session=_Session())
    client._cache_path(_Resp.url).write_text(json.dumps(stale))
    client._cache_path("https://www.sec.gov/files/company_tickers.json").write_text(
        json.dumps({"__fetched__": "2026-09-17"}))
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (1611983, "Liberty Broadband Corp  (LBRDA)", False))
    res = TickerResolver(client).resolve("LBRDA", "2026-08-21")
    assert (res.cik, res.source) == (1611983, "efts")
    assert _Session.calls == [_Resp.url]          # fetched once; every later read hit the fresh copy
    assert json.loads(client._cache_path(_Resp.url).read_text())["filings"]["recent"]["filingDate"][-1] == "2026-08-20"


def test_a_cache_drops_only_the_answers_of_a_retired_rule(tmp_path, fake_edgar):
    """Version 3 was written while the resolver let the ticker map's holder beat
    a name-mismatched EFTS candidate (company_tickers_name_mismatch); that rule
    is withdrawn, so those answers are dropped and resolved again. Every other
    answer of a version-2 or version-3 file loads."""
    cache = tmp_path / "res.json"
    kept = {**STALE, "member_name": "Altera Corp"}
    for version in (2, 3):
        cache.write_text(json.dumps({"__version__": version, "entries": {
            KEY: kept,
            "M|2026-06-30": {"ticker": "M", "cik": 1771146, "name": "ETF Opportunities Trust",
                             "source": "efts_name_mismatch", "member_name": "MACYS INC"},
            "DDS|2026-08-24": {"ticker": "DDS", "cik": 28917, "name": "DILLARD'S, INC.",
                               "source": "company_tickers_name_mismatch", "member_name": "DILLARDS INC CLASS A"}}}))
        r = TickerResolver(fake_edgar, cache_path=cache, observed_names=_member("Altera Corp"))
        assert set(r._memo) == {KEY, "M|2026-06-30"}


class _StaleEdgar:
    """Wraps FakeEdgar; every submissions read is an older copy served because the refetch failed."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def submissions(self, cik, fresh_after=None):
        return {**self.inner.submissions(cik), STALE_KEY: True}


def test_an_answer_read_from_a_stale_copy_is_not_persisted(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    r = TickerResolver(_StaleEdgar(fake_edgar), cache_path=cache)
    assert r.resolve("ALTR", "2025-03-26").cik == 1701732        # used for this run
    assert r._transient is True
    assert not cache.exists() or KEY not in cache.read_text()   # but not saved


class _StaleSearch:
    """Wraps FakeEdgar; the company search answers with a cached hit served after a failed refetch."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def company_search_atom(self, company, form_type="25-NSE"):
        return [{"cik": 999002, "name": "Liquidating Trust", "form": "25-NSE", "filing_date": "2019-11-06",
                 STALE_KEY: True}]


def test_a_name_search_answered_from_a_stale_hit_is_not_persisted(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    r = TickerResolver(_StaleSearch(fake_edgar), cache_path=cache, observed_names=_member("Liquidating Trust"))
    res = r.resolve("NOPE", "2019-11-06")
    assert (res.cik, res.source) == (999002, "name_search")
    assert r._transient is True
    assert not cache.exists() or "NOPE|2019-11-06" not in cache.read_text()


class _SearchDown:
    """Wraps FakeEdgar; EDGAR's company search cannot be reached."""

    def __init__(self, inner):
        self.inner, self.searches = inner, 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def company_search_atom(self, company, form_type="25-NSE"):
        self.searches += 1
        raise requests.ConnectionError("no route to host")


def test_a_company_search_that_could_not_be_sent_marks_the_resolve_transient(fake_edgar):
    e = _SearchDown(fake_edgar)
    r = TickerResolver(e, observed_names=_member("Nope Holdings Inc"))
    assert r.resolve("NOPE", "2024-01-01").cik is None
    assert e.searches > 0 and r._transient is True


def test_a_degraded_answer_is_known_for_the_run(tmp_path, fake_edgar, monkeypatch):
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (999002, "Liquidating Trust (ALTR)", False))
    monkeypatch.setattr(TickerResolver, "_validate_cik", lambda self, *a, **kw: True)
    r = TickerResolver(_FlakyEdgar(fake_edgar), cache_path=tmp_path / "res.json")
    assert r.resolve("ALTR", "2025-03-26").cik == 999002
    assert r.is_degraded("ALTR", "2025-03-26") is True
    assert r.resolve("BAD", "2023-05-10").cik == 999001
    assert r.is_degraded("BAD", "2023-05-10") is False
    assert r.is_degraded("altr ", "2025-03-26") is True           # the resolver's own key normalisation


def test_a_rename_built_on_a_degraded_answer_is_degraded_and_not_saved(tmp_path, fake_edgar, monkeypatch):
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (999002, "Liquidating Trust (ALTR)", False))
    monkeypatch.setattr(TickerResolver, "_validate_cik", lambda self, *a, **kw: True)
    cache = tmp_path / "res.json"
    r = TickerResolver(_FlakyEdgar(fake_edgar), cache_path=cache, rename_map={"OLDALTR": "ALTR"})
    assert r.resolve("ALTR", "2025-03-26").cik == 999002          # transient: the flaky date check
    assert r.resolve("OLDALTR", "2025-03-26").cik == 999002       # the rename reads that memo entry
    assert r.is_degraded("OLDALTR", "2025-03-26") is True
    assert not cache.exists() or "OLDALTR" not in cache.read_text()


def test_batched_writes_reach_the_file_only_on_flush(tmp_path, fake_edgar, monkeypatch):
    import delist_detection.ticker_resolver as tr
    writes = []
    real = tr.write_atomic

    def recording(path, text):
        writes.append(path)
        real(path, text)

    monkeypatch.setattr(tr, "write_atomic", recording)
    cache = tmp_path / "res.json"
    r = TickerResolver(fake_edgar, cache_path=cache, batch_writes=True)
    assert r.resolve("ALTR", "2025-03-26").cik == 1701732
    assert r.resolve("BAD", "2023-05-10").cik == 999001
    assert not cache.exists() and writes == []
    r.flush()
    assert set(json.loads(cache.read_text())["entries"]) == {"ALTR|2025-03-26", "BAD|2023-05-10"}
    r.flush()                                                      # nothing new: no rewrite
    assert writes == [cache]


def test_without_batching_every_new_answer_is_written_at_once(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    r = TickerResolver(fake_edgar, cache_path=cache)
    r.resolve("ALTR", "2025-03-26")
    assert "ALTR|2025-03-26" in json.loads(cache.read_text())["entries"]


def test_a_memo_temp_file_left_by_a_killed_process_is_removed(tmp_path, fake_edgar):
    import subprocess
    import sys
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    orphan = tmp_path / f".res.json.{p.pid}.1.tmp"
    orphan.write_text("{")
    TickerResolver(fake_edgar, cache_path=tmp_path / "res.json")
    assert not orphan.exists()


def test_a_shadow_starts_from_its_resolver_memo_and_saves_nothing(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    e = _RecordingEdgar(fake_edgar)
    r = TickerResolver(e, cache_path=cache, today=date(2026, 9, 23))
    assert r.resolve("BAD", "2023-05-10").cik == 999001
    saved, reads = cache.read_text(), len(e.log)
    s = r.shadow()
    assert s.today == date(2026, 9, 23) and s.cache_path is None
    assert s.resolve("BAD", "2023-05-10").cik == 999001         # from the copied memo...
    assert len(e.log) == reads                                   # ...with no EDGAR read
    assert s.resolve("ALTR", "2025-03-26").cik == 1701732       # a new answer...
    assert cache.read_text() == saved                            # ...is not saved
    assert "ALTR|2025-03-26" not in r._memo                      # ...nor seen by its resolver


class _CountingTickers:
    """Wraps FakeEdgar; counts company_tickers() reads."""

    def __init__(self, inner):
        self.inner, self.ticker_reads = inner, 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def company_tickers(self):
        self.ticker_reads += 1
        return self.inner.company_tickers()


def test_a_shadow_reads_the_ticker_map_only_when_an_era_needs_it(fake_edgar):
    """A one-worker run reads company_tickers.json only when an era gets past its
    pin, manual override and memo; a shadow built before that must not read it
    sooner, and once its resolver has the map it shares it."""
    e = _CountingTickers(fake_edgar)
    r = TickerResolver(e, cik_pins=lambda t, d=None: 999001 if t == "BAD" else None)
    s = r.shadow()
    assert e.ticker_reads == 0
    assert s.resolve("BAD", "2023-05-10").cik == 999001          # pinned: no map needed
    assert e.ticker_reads == 0
    assert s.resolve("ALTR", "2025-03-26").cik == 1701732        # the first era that needs it
    assert e.ticker_reads == 1
    assert r.resolve("LIQ", "2019-11-06").cik == 999002
    assert r.shadow()._companies is r._companies and e.ticker_reads == 2


class _InterruptAfterWrite(dict):
    """A memo whose next write lands and then is interrupted (Ctrl-C) before the
    rest of `_remember` runs."""

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        raise KeyboardInterrupt


def test_an_interrupt_right_after_a_transient_answer_enters_the_memo_saves_nothing(tmp_path, fake_edgar,
                                                                                   monkeypatch):
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (999002, "Liquidating Trust (ALTR)", False))
    monkeypatch.setattr(TickerResolver, "_validate_cik", lambda self, *a, **kw: True)
    cache = tmp_path / "res.json"
    e = _FlakyEdgar(fake_edgar)
    e.failed = True                                               # no failure yet
    r = TickerResolver(e, cache_path=cache, batch_writes=True)
    assert r.resolve("BAD", "2023-05-10").cik == 999001          # a saveable answer, not yet flushed
    e.failed = False                                              # ALTR's date check now fails: transient
    r._memo = _InterruptAfterWrite(r._memo)
    with pytest.raises(KeyboardInterrupt):
        r.resolve("ALTR", "2025-03-26")
    r.flush()                                                     # run()'s way out
    assert set(json.loads(cache.read_text())["entries"]) == {"BAD|2023-05-10"}

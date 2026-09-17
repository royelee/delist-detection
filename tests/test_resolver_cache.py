"""The resolver's on-disk memo: versioned, keyed by the member name, and never
holding an answer reached through a transient EDGAR error."""
import json
import logging

import requests

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
    assert saved["__version__"] == 2
    assert saved["entries"][KEY]["cik"] == 1701732


def test_a_v2_cache_round_trips(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    r = TickerResolver(fake_edgar, cache_path=cache, member_names=_member("Altair Engineering Inc"))
    assert r.resolve("ALTR", "2025-03-26").cik == 1701732
    saved = json.loads(cache.read_text())
    assert saved == {"__version__": 2, "entries": {KEY: {
        "ticker": "ALTR", "cik": 1701732, "name": "Altair Engineering Inc.",
        "source": "company_tickers", "member_name": "Altair Engineering Inc"}}}
    # a fresh resolver answers from the file, with no EDGAR reads
    r2 = TickerResolver(None, cache_path=cache, member_names=_member("Altair Engineering Inc"))
    assert r2.resolve("ALTR", "2025-03-26").cik == 1701732


def test_a_different_member_name_misses_the_cache(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"
    cache.write_text(json.dumps({"__version__": 2, "entries": {KEY: {**STALE, "member_name": "Altera Corp"}}}))
    same = TickerResolver(fake_edgar, cache_path=cache, member_names=_member("Altera Corp"))
    assert same.resolve("ALTR", "2025-03-26").cik == 999999
    other = TickerResolver(fake_edgar, cache_path=cache, member_names=_member("Altair Engineering Inc"))
    assert other.resolve("ALTR", "2025-03-26").cik == 1701732
    # an entry saved without a member name misses a lookup that has one
    cache.write_text(json.dumps({"__version__": 2, "entries": {KEY: {**STALE, "member_name": None}}}))
    named = TickerResolver(fake_edgar, cache_path=cache, member_names=_member("Altair Engineering Inc"))
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
    r = TickerResolver(e, member_names=_member("Bad Company Holdings"))
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

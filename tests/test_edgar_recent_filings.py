"""`EdgarClient.recent_filings`: the rows a submissions JSON's columns list, recent block then older files."""
from __future__ import annotations

import json

import pytest
import requests

from delist_detection.sources.edgar import EdgarClient, EdgarSubmission, _submissions_of
from delist_detection.sources.sec_stats import SEC_STATS, fill_only

RECENT = {"accessionNumber": ["0001-24-000002", "0001-24-000001"], "form": ["8-K", "25-NSE"],
          "filingDate": ["2024-03-01", "2024-02-01"], "reportDate": ["2024-02-28", ""],
          "items": ["2.01,3.01", ""], "primaryDocument": ["a.htm", "b.xml"]}


def test_submissions_of_reads_row_i_of_every_column():
    assert _submissions_of(RECENT) == [
        EdgarSubmission("0001-24-000002", "8-K", "2024-03-01", "2024-02-28", "2.01,3.01", "a.htm"),
        EdgarSubmission("0001-24-000001", "25-NSE", "2024-02-01", "", "", "b.xml")]


def test_a_column_the_block_lacks_reads_blank_and_an_empty_block_has_no_filings():
    got = _submissions_of({"accessionNumber": ["x", "y"], "form": ["10-K", "10-Q"]})
    assert got == [EdgarSubmission("x", "10-K", "", "", "", ""), EdgarSubmission("y", "10-Q", "", "", "", "")]
    assert _submissions_of({}) == [] and _submissions_of({"accessionNumber": []}) == []


def test_a_short_column_raises_as_it_always_has():
    with pytest.raises(IndexError):
        _submissions_of({**RECENT, "filingDate": ["2024-03-01"]})


def test_recent_filings_lists_the_recent_block_then_each_older_file(tmp_path, monkeypatch):
    client = EdgarClient(cache_dir=tmp_path, user_agent="test test@example.com")
    older = {"accessionNumber": ["0001-20-000009"], "form": ["10-K"], "filingDate": ["2020-02-01"],
             "reportDate": ["2019-12-31"], "items": [""], "primaryDocument": ["k.htm"]}
    served = {"https://data.sec.gov/submissions/CIK0000000042.json":
              {"filings": {"recent": RECENT, "files": [{"name": "CIK0000000042-submissions-001.json"}]}},
              "https://data.sec.gov/submissions/CIK0000000042-submissions-001.json": older}
    monkeypatch.setattr(client, "_get_json", lambda url, **kw: json.loads(json.dumps(served[url])))
    assert [f.accession for f in client.recent_filings(42)] == ["0001-24-000002", "0001-24-000001", "0001-20-000009"]


# --- FB-025: an older page is read as the main file lists it -----------------------------------------------------------

MAIN = "https://data.sec.gov/submissions/CIK0000000042.json"
PAGE1 = "https://data.sec.gov/submissions/CIK0000000042-submissions-001.json"
PAGE2 = "https://data.sec.gov/submissions/CIK0000000042-submissions-002.json"


def _block(*rows):
    """A columnar block of (accession, form, filing date) rows."""
    return {"accessionNumber": [r[0] for r in rows], "form": [r[1] for r in rows], "filingDate": [r[2] for r in rows]}


def _listed(name, count, last):
    return {"name": name.rsplit("/", 1)[1], "filingCount": count, "filingFrom": "2018-05-16", "filingTo": last}


class _Resp:
    def __init__(self, data):
        self.status_code, self._data, self.text = 200, data, json.dumps(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _Session:
    """Serves `pages` by URL and records each request; a URL it does not hold fails as a dropped connection."""
    def __init__(self, pages):
        self.pages, self.headers, self.calls = pages, {}, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if url not in self.pages:
            raise requests.ConnectionError(url)
        return _Resp(json.loads(json.dumps(self.pages[url])))


def _cached(tmp_path, served, **cached):
    """A client over `served` whose cache holds `cached` (URL constant name, lower case, to its payload)."""
    session = _Session(served)
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    for name, data in cached.items():
        client._cache_path({"main": MAIN, "page1": PAGE1, "page2": PAGE2}[name]).write_text(json.dumps(data))
    return client, session


OLD_PAGE = _block(("a-18-2", "10-Q", "2018-09-21"), ("a-18-1", "S-4", "2018-05-16"))
NEW_PAGE = _block(("a-18-3", "8-K12B", "2018-12-20"), ("a-18-2", "10-Q", "2018-09-21"), ("a-18-1", "S-4", "2018-05-16"))


def test_a_cached_page_with_fewer_rows_than_the_main_file_lists_is_fetched_again(tmp_path):
    """New Cigna 2018 (FB-025): the main file was fetched again after its 8-K12B of 2018-12-20 had moved from the
    recent block into the older page, and the page cached before that did not hold it. The filing was in neither."""
    main = {"filings": {"recent": _block(("a-26-1", "8-K", "2026-10-09")), "files": [_listed(PAGE1, 3, "2018-12-24")]}}
    client, session = _cached(tmp_path, {PAGE1: NEW_PAGE}, main=main, page1=OLD_PAGE)
    assert [f.accession for f in client.recent_filings(42)] == ["a-26-1", "a-18-3", "a-18-2", "a-18-1"]
    assert session.calls == [PAGE1]
    assert [f.form for f in client.recent_filings(42)][1] == "8-K12B" and session.calls == [PAGE1]   # once


def test_the_oldest_page_with_the_listed_row_count_is_read_from_the_cache(tmp_path):
    """Rows only enter the oldest page, so the listed count says it is whole. Nothing is fetched, now or later."""
    main = {"filings": {"recent": _block(("a-26-1", "8-K", "2026-10-09")), "files": [_listed(PAGE1, 2, "2018-09-21")]}}
    client, session = _cached(tmp_path, {}, main=main, page1=OLD_PAGE)
    assert [f.accession for f in client.recent_filings(42)] == ["a-26-1", "a-18-2", "a-18-1"]
    assert [f.accession for f in client.recent_filings(42)] == ["a-26-1", "a-18-2", "a-18-1"]
    assert session.calls == []


def test_a_page_that_is_not_the_oldest_is_fetched_again_once_whatever_its_row_count(tmp_path):
    """A page between the recent block and an older page takes rows in at one end and hands rows on at the other, so
    its count can stay while its rows change. A copy never checked against a listing is fetched again, once."""
    older = _block(("a-10-1", "10-K", "2010-02-01"))
    main = {"filings": {"recent": _block(("a-26-1", "8-K", "2026-10-09")),
                        "files": [_listed(PAGE1, 2, "2018-12-24"), _listed(PAGE2, 1, "2010-02-01")]}}
    moved = _block(("a-18-3", "8-K12B", "2018-12-20"), ("a-18-2", "10-Q", "2018-09-21"))
    client, session = _cached(tmp_path, {PAGE1: moved}, main=main, page1=OLD_PAGE, page2=older)
    want = ["a-26-1", "a-18-3", "a-18-2", "a-10-1"]
    assert [f.accession for f in client.recent_filings(42)] == want
    assert [f.accession for f in client.recent_filings(42)] == want
    assert session.calls == [PAGE1]


def test_a_page_is_fetched_again_when_the_main_file_lists_it_differently(tmp_path):
    main = {"filings": {"recent": _block(("a-26-1", "8-K", "2026-10-09")), "files": [_listed(PAGE1, 2, "2018-09-21")]}}
    client, session = _cached(tmp_path, {PAGE1: NEW_PAGE}, main=main, page1=OLD_PAGE)
    client.recent_filings(42)
    assert session.calls == []
    main["filings"]["files"] = [_listed(PAGE1, 3, "2018-12-24")]
    client._cache_path(MAIN).write_text(json.dumps(main))
    assert [f.accession for f in client.recent_filings(42)] == ["a-26-1", "a-18-3", "a-18-2", "a-18-1"]
    assert session.calls == [PAGE1]


def test_a_page_that_cannot_be_fetched_again_is_served_from_the_cache_as_a_stale_copy(tmp_path):
    """The rows it holds are read, the failure counts as a stale copy (the run flags what rested on it), and the next
    read asks again."""
    main = {"filings": {"recent": _block(("a-26-1", "8-K", "2026-10-09")), "files": [_listed(PAGE1, 3, "2018-12-24")]}}
    client, session = _cached(tmp_path, {}, main=main, page1=OLD_PAGE)
    before = SEC_STATS.snapshot().counts.get("degraded:stale_copy", 0)
    assert [f.accession for f in client.recent_filings(42)] == ["a-26-1", "a-18-2", "a-18-1"]
    assert SEC_STATS.snapshot().counts.get("degraded:stale_copy", 0) == before + 1
    session.pages[PAGE1] = NEW_PAGE
    assert [f.accession for f in client.recent_filings(42)] == ["a-26-1", "a-18-3", "a-18-2", "a-18-1"]


def test_a_filing_listed_in_two_blocks_is_read_once(tmp_path):
    """A main file older than its page still lists the rows that have since moved into the page."""
    main = {"filings": {"recent": _block(("a-26-1", "8-K", "2026-10-09"), ("a-18-3", "8-K12B", "2018-12-20")),
                        "files": [_listed(PAGE1, 2, "2018-09-21")]}}
    client, session = _cached(tmp_path, {PAGE1: NEW_PAGE}, main=main, page1=NEW_PAGE)
    assert [f.accession for f in client.recent_filings(42)] == ["a-26-1", "a-18-3", "a-18-2", "a-18-1"]


def test_a_prefetch_thread_reads_the_cached_page_as_it_is(tmp_path):
    main = {"filings": {"recent": _block(("a-26-1", "8-K", "2026-10-09")), "files": [_listed(PAGE1, 3, "2018-12-24")]}}
    client, session = _cached(tmp_path, {PAGE1: NEW_PAGE}, main=main, page1=OLD_PAGE)
    with fill_only():
        assert [f.accession for f in client.recent_filings(42)] == ["a-26-1", "a-18-2", "a-18-1"]
    assert session.calls == []
    assert len(client.recent_filings(42)) == 4 and session.calls == [PAGE1]     # the sequential pass checks it

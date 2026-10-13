"""`EdgarClient.recent_filings`: the rows a submissions JSON's columns list, recent block then older files."""
from __future__ import annotations

import json
from datetime import date

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


# --- FB-025: the copies of a filing list are read as one list ---------------------------------------------------------

MAIN = "https://data.sec.gov/submissions/CIK0000000042.json"
PAGE1 = "https://data.sec.gov/submissions/CIK0000000042-submissions-001.json"
PAGE2 = "https://data.sec.gov/submissions/CIK0000000042-submissions-002.json"
URLS = {"main": MAIN, "page1": PAGE1, "page2": PAGE2}


def _block(*accessions):
    """A columnar block: one 8-K per accession."""
    return {"accessionNumber": list(accessions), "form": ["8-K"] * len(accessions),
            "filingDate": ["2020-01-01"] * len(accessions)}


def _main(recent, *pages):
    """A main file: its recent block and, per older page, (URL, listed row count)."""
    files = [{"name": url.rsplit("/", 1)[1], "filingCount": n, "filingFrom": "2018-05-16", "filingTo": "2018-12-24"}
             for url, n in pages]
    return {"filings": {"recent": _block(*recent), "files": files}}


class _Resp:
    def __init__(self, data):
        self.status_code, self._data, self.text = 200, data, json.dumps(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _Session:
    """Serves `pages` by URL and records each request. A list is served one answer per request, the last one from
    then on; a URL it does not hold fails as a dropped connection."""
    def __init__(self, pages):
        self.pages, self.headers, self.calls = pages, {}, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if url not in self.pages:
            raise requests.ConnectionError(url)
        answer = self.pages[url]
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        return _Resp(json.loads(json.dumps(answer)))


def _client(tmp_path, served, **cached):
    """A client over `served` whose cache holds `cached` (main, page1, page2)."""
    session = _Session(served)
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    for name, data in cached.items():
        client._cache_path(URLS[name]).write_text(json.dumps(data))
    return client, session


def _read(client):
    return [f.accession for f in client.recent_filings(42)]


def test_a_page_cached_before_its_main_file_was_fetched_again_is_read_again_with_it(tmp_path):
    """New Cigna 2018 (FB-025): the main file was fetched again after its 8-K12B of 2018-12-20 had moved from the
    recent block into page 001, and the page cached before that did not hold it. The filing was in neither."""
    torn = _main(["n1"], (PAGE1, 3))                           # a later run's copy; the page is older: 2 rows of 3
    today = _main(["n2", "n1"], (PAGE1, 3))
    client, session = _client(tmp_path, {MAIN: today, PAGE1: _block("k12b", "q", "s4")},
                              main=torn, page1=_block("q", "s4"))
    assert _read(client) == ["n2", "n1", "k12b", "q", "s4"]
    assert session.calls == [MAIN, PAGE1]
    assert _read(client) == ["n2", "n1", "k12b", "q", "s4"] and session.calls == [MAIN, PAGE1]     # once


def test_a_main_file_this_client_fetched_itself_is_not_fetched_twice(tmp_path):
    """A stage asks for a fresh copy of the main file, and a later stage reads the filings: the pages are fetched
    under the copy the client already holds."""
    old = {**_main(["n1"], (PAGE1, 2)), "__fetched__": "2026-01-01"}
    client, session = _client(tmp_path, {MAIN: _main(["n2", "n1"], (PAGE1, 3)), PAGE1: _block("k12b", "q", "s4")},
                              main=old, page1=_block("q", "s4"))
    client.submissions(42, fresh_after=date(2026, 9, 1))
    assert _read(client) == ["n2", "n1", "k12b", "q", "s4"]
    assert session.calls == [MAIN, PAGE1]


def test_a_main_file_fetched_again_for_its_profile_takes_its_cached_pages_with_it(tmp_path):
    """McEwen 2026 (FB-028's runs): a stage asked for a fresh copy of the main file and no later stage read the
    filings, so the run left the new main file beside the page of May: 23 filings of 2012 were in neither copy until
    the next read. The pages the cache holds are fetched with the main file, so the cache is one list between runs."""
    old = {**_main(["n1"], (PAGE1, 2)), "__fetched__": "2026-01-01"}
    client, session = _client(tmp_path, {MAIN: _main(["n2", "n1"], (PAGE1, 3)), PAGE1: _block("k12b", "q", "s4")},
                              main=old, page1=_block("q", "s4"))
    client.submissions(42, fresh_after=date(2026, 9, 1))
    assert session.calls == [MAIN, PAGE1]
    assert json.loads(client._cache_path(PAGE1).read_text())["accessionNumber"] == ["k12b", "q", "s4"]
    later, session2 = _client(tmp_path, {})                               # the next run reads it with no request
    assert _read(later) == ["n2", "n1", "k12b", "q", "s4"] and session2.calls == []


def test_a_main_file_fetched_for_its_profile_with_no_page_cached_is_fetched_alone(tmp_path):
    """A profile read of an issuer whose pages the cache does not hold costs one request: nothing is torn."""
    client, session = _client(tmp_path, {MAIN: _main(["n1"], (PAGE1, 2)), PAGE1: _block("q", "s4")})
    assert client.submissions(42)["filings"]["recent"]["accessionNumber"] == ["n1"]
    assert session.calls == [MAIN]


def test_a_main_file_fetched_again_and_found_unchanged_keeps_its_pages(tmp_path):
    """No filing arrived between the two copies, so no row moved: the pages fetched under the first are the second's."""
    served = {MAIN: _main(["n1"], (PAGE1, 2), (PAGE2, 1)), PAGE1: _block("q", "s4"), PAGE2: _block("z")}
    client, session = _client(tmp_path, served)
    assert _read(client) == ["n1", "q", "s4", "z"] and session.calls == [MAIN, PAGE1, PAGE2]
    other, session2 = _client(tmp_path, served)                           # a later run on the same cache
    cp = other._cache_path(MAIN)
    cp.write_text(json.dumps({**json.loads(cp.read_text()), "__fetched__": "2026-01-01"}))
    other.submissions(42, fresh_after=date(2026, 9, 1))
    assert _read(other) == ["n1", "q", "s4", "z"] and session2.calls == [MAIN]


def test_pages_cached_before_they_were_tied_to_a_main_file_are_whole_as_one_page_of_the_listed_row_count(tmp_path):
    client, session = _client(tmp_path, {}, main=_main(["n1"], (PAGE1, 2)), page1=_block("q", "s4"))
    assert _read(client) == ["n1", "q", "s4"] and _read(client) == ["n1", "q", "s4"]
    assert session.calls == []


def test_a_page_fetched_again_takes_every_older_page_with_it(tmp_path):
    """The consumer's follow-up (American Express): page 001 was fetched again beside the copies of 2026-10-02. By
    then it had handed its oldest rows to page 002, whose old copy was kept, and those rows were in neither. A list
    of such copies with a second page cannot be told whole, so the whole list is fetched, in order."""
    cached = {"main": _main(["n1"], (PAGE1, 3), (PAGE2, 1)), "page1": _block("c", "b", "a"), "page2": _block("z")}
    served = {MAIN: _main(["n2"], (PAGE1, 3), (PAGE2, 3)), PAGE1: _block("n1", "d", "c"), PAGE2: _block("b", "a", "z")}
    client, session = _client(tmp_path, served, **cached)
    got = _read(client)
    assert {"n1", "c", "b", "a", "z"} <= set(got) and got == ["n2", "n1", "d", "c", "b", "a", "z"]
    assert session.calls == [MAIN, PAGE1, PAGE2]
    assert _read(client) == got and session.calls == [MAIN, PAGE1, PAGE2]


def test_a_main_file_that_lists_fewer_pages_than_edgar_has_is_fetched_again_first(tmp_path):
    """Pages fetched today beside an old main file have handed rows to a page that file does not list."""
    cached = {"main": _main(["n1"], (PAGE1, 3)), "page1": _block("b", "a")}                 # torn: 2 rows of 3
    served = {MAIN: _main(["n2"], (PAGE1, 2), (PAGE2, 3)), PAGE1: _block("n1", "d"), PAGE2: _block("c", "b", "a")}
    client, session = _client(tmp_path, served, **cached)
    assert _read(client) == ["n2", "n1", "d", "c", "b", "a"]
    assert session.calls == [MAIN, PAGE1, PAGE2]


def test_an_oldest_page_shorter_than_listed_has_the_list_fetched_once_more(tmp_path):
    """Between the main file's fetch and the page's, the page handed rows to a new page the main file did not list."""
    cached = {"main": _main(["n1"], (PAGE1, 3)), "page1": _block("b", "a")}
    served = {MAIN: [_main(["n2"], (PAGE1, 3)), _main(["n2"], (PAGE1, 2), (PAGE2, 2))],
              PAGE1: _block("n1", "c"), PAGE2: _block("b", "a")}
    client, session = _client(tmp_path, served, **cached)
    assert _read(client) == ["n2", "n1", "c", "b", "a"]
    assert session.calls == [MAIN, PAGE1, MAIN, PAGE1, PAGE2]
    assert _read(client) == ["n2", "n1", "c", "b", "a"] and len(session.calls) == 5


def test_a_cold_cache_fetches_each_copy_once_and_a_prefetch_thread_may_do_it(tmp_path):
    served = {MAIN: _main(["n1"], (PAGE1, 2)), PAGE1: _block("q", "s4")}
    client, session = _client(tmp_path, served)
    with fill_only():
        assert _read(client) == ["n1", "q", "s4"]
    assert _read(client) == ["n1", "q", "s4"]
    assert session.calls == [MAIN, PAGE1]


def test_a_page_the_cache_lacks_beside_another_runs_main_file_is_fetched_once(tmp_path):
    main = _main(["n1"], (PAGE1, 2))
    client, session = _client(tmp_path, {MAIN: main, PAGE1: _block("q", "s4")}, main=main)
    assert _read(client) == ["n1", "q", "s4"]
    assert session.calls == [MAIN, PAGE1]


def test_a_list_that_cannot_be_fetched_again_is_read_from_the_cache_as_a_stale_copy(tmp_path):
    """The rows the copies hold are read, the failure counts as a stale copy (the run flags what rested on it), and
    the next read asks again."""
    torn = _main(["n1"], (PAGE1, 3))
    client, session = _client(tmp_path, {}, main=torn, page1=_block("q", "s4"))
    before = SEC_STATS.snapshot().counts.get("degraded:stale_copy", 0)
    assert _read(client) == ["n1", "q", "s4"]
    assert SEC_STATS.snapshot().counts.get("degraded:stale_copy", 0) == before + 1
    session.pages.update({MAIN: _main(["n1"], (PAGE1, 3)), PAGE1: _block("k12b", "q", "s4")})
    assert _read(client) == ["n1", "k12b", "q", "s4"]


def test_a_filing_two_copies_hold_is_read_once(tmp_path):
    """It moved from the main file into the page between the two fetches."""
    served = {MAIN: _main(["n1", "k12b"], (PAGE1, 2)), PAGE1: _block("k12b", "q", "s4")}
    client, session = _client(tmp_path, served)
    assert _read(client) == ["n1", "k12b", "q", "s4"]


def test_a_prefetch_thread_reads_the_cached_copies_as_they_are(tmp_path):
    torn = _main(["n1"], (PAGE1, 3))
    served = {MAIN: torn, PAGE1: _block("k12b", "q", "s4")}
    client, session = _client(tmp_path, served, main=torn, page1=_block("q", "s4"))
    with fill_only():
        assert _read(client) == ["n1", "q", "s4"]
    assert session.calls == []
    assert _read(client) == ["n1", "k12b", "q", "s4"] and session.calls == [MAIN, PAGE1]   # the sequential pass

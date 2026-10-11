"""`EdgarClient.recent_filings`: the rows a submissions JSON's columns list, recent block then older files."""
from __future__ import annotations

import json

import pytest

from delist_detection.sources.edgar import EdgarClient, EdgarSubmission, _submissions_of

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

"""EdgarClient._get_json: a 200 whose body is not JSON must never be cached as
an answer (final-fix item 1). It is treated exactly like a 5xx or a transport
error: with a usable cached copy, that copy is served marked stale and the
file on disk is left untouched; with none, it raises and writes nothing. It
must never be written as `{"__raw__": ...}` -- that could silently overwrite a
good submissions copy and hide a Form 25."""
import json
from datetime import date

import pytest
import requests

from delist_detection.edgar import EdgarClient

URL = "https://data.sec.gov/submissions/CIK0000000042.json"


class _NonJSONResp:
    status_code = 200

    def __init__(self, text="<html>SEC is temporarily unavailable</html>"):
        self.text, self.url = text, URL

    def json(self):
        raise json.JSONDecodeError("Expecting value", self.text, 0)

    def raise_for_status(self):
        pass


class _NonJSONSession:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return _NonJSONResp()


class _GoodResp:
    status_code = 200
    url = URL

    def __init__(self, data):
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _GoodSession:
    def __init__(self, data):
        self.data, self.calls = data, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return _GoodResp(self.data)


def _client(tmp_path, session, cached=None):
    client = EdgarClient(cache_dir=tmp_path, session=session, sleep=lambda _: None)
    cp = client._cache_path(URL)
    if cached is not None:
        cp.write_text(json.dumps(cached))
    return client, cp


def test_a_non_json_200_with_a_cached_copy_is_served_stale_and_the_file_is_unchanged(tmp_path):
    good = {"name": "Good Co", "__fetched__": "2026-05-26"}
    client, cp = _client(tmp_path, _NonJSONSession(), cached=good)
    got = client.submissions(42, fresh_after=date(2026, 9, 1))
    assert got == {**good, "__stale__": True}
    assert json.loads(cp.read_text()) == good          # never overwritten, never __raw__


def test_a_non_json_200_with_no_cached_copy_raises_and_writes_nothing(tmp_path):
    client, cp = _client(tmp_path, _NonJSONSession())
    with pytest.raises(requests.RequestException):
        client.submissions(42)
    assert not cp.exists()


def test_a_real_json_answer_is_unchanged(tmp_path):
    session = _GoodSession({"name": "Fresh Co"})
    client, cp = _client(tmp_path, session)
    got = client.submissions(42)
    assert got["name"] == "Fresh Co"
    assert json.loads(cp.read_text())["name"] == "Fresh Co"
    assert session.calls == [URL]

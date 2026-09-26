from delist_detection.edgar import EdgarClient
from delist_detection.html_text import strip_html


def test_strip_html_removes_tags_and_scripts():
    raw = (
        "<html><head><style>.x{color:red}</style>"
        "<script>var a=1;</script></head>"
        "<body><p>right to receive&nbsp;$113.00 in&#160;cash</p>"
        "<div>without   interest</div></body></html>"
    )
    out = strip_html(raw)
    assert "var a" not in out
    assert "color:red" not in out
    assert "right to receive $113.00 in cash without interest" in out


class _Resp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _StubSession:
    """Minimal requests.Session stand-in: records .get calls, returns queued responses."""

    def __init__(self, responses):
        # responses: list of _Resp returned in order on successive .get calls
        self._responses = list(responses)
        self.headers = {}
        self.calls = []  # list of (url, headers, timeout)

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers, timeout))
        if not self._responses:
            raise AssertionError("unexpected extra .get call")
        return self._responses.pop(0)


def _client(tmp_path, responses, sleep=None):
    session = _StubSession(responses)
    kw = {"sleep": sleep} if sleep is not None else {}
    client = EdgarClient(cache_dir=tmp_path, session=session, **kw)
    return client, session


def test_empty_primary_doc_no_fetch_no_cache(tmp_path):
    # empty primary_doc returns "" with no network and no cache file.
    client, session = _client(tmp_path, [])
    acc = "0001234567-21-000123"
    out = client.fetch_filing_text(cik=320193, accession=acc, primary_doc="")
    assert out == ""
    assert session.calls == []
    cp = client.cache_dir / "text" / f"{acc.replace('-', '')}.txt"
    assert not cp.exists()


def test_404_is_cached_empty(tmp_path):
    # a 404 caches "" so the second call does not re-fetch.
    client, session = _client(tmp_path, [_Resp(404, "not found")])
    acc = "0001234567-21-000404"
    out = client.fetch_filing_text(cik=320193, accession=acc, primary_doc="doc.htm")
    assert out == ""
    cp = client.cache_dir / "text" / f"{acc.replace('-', '')}.txt"
    assert cp.exists()
    assert cp.read_text(encoding="utf-8") == ""
    assert len(session.calls) == 1
    # Second call: served from cache, no new .get.
    out2 = client.fetch_filing_text(cik=320193, accession=acc, primary_doc="doc.htm")
    assert out2 == ""
    assert len(session.calls) == 1


def test_503_is_not_cached(tmp_path):
    # a persistent 503 is retried (like fetch_filing_raw,
    # up to 3 attempts) and, once every attempt fails, returns "" without caching;
    # a later call retries again because nothing was cached.
    client, session = _client(tmp_path, [_Resp(503, "busy")] * 3, sleep=lambda _: None)
    acc = "0001234567-21-000503"
    out = client.fetch_filing_text(cik=320193, accession=acc, primary_doc="doc.htm")
    assert out == ""
    cp = client.cache_dir / "text" / f"{acc.replace('-', '')}.txt"
    assert not cp.exists()
    assert len(session.calls) == 3
    # Second call: must hit the network again because nothing was cached.
    client2, session2 = _client(tmp_path, [_Resp(503, "busy")] * 3, sleep=lambda _: None)
    out2 = client2.fetch_filing_text(cik=320193, accession=acc, primary_doc="doc.htm")
    assert out2 == ""
    assert len(session2.calls) == 3


def test_503_then_200_succeeds(tmp_path):
    # Item 2: one transport blip must not become a permanent "" -- the retry
    # that fetch_filing_raw already gets (edgar.retry_request) now covers
    # fetch_filing_text too.
    client, session = _client(tmp_path, [_Resp(503, "busy"), _Resp(200, "<p>the filing text</p>")],
                              sleep=lambda _: None)
    acc = "0001234567-21-000599"
    out = client.fetch_filing_text(cik=320193, accession=acc, primary_doc="doc.htm")
    assert "the filing text" in out
    assert len(session.calls) == 2
    cp = client.cache_dir / "text" / f"{acc.replace('-', '')}.txt"
    assert cp.exists() and "the filing text" in cp.read_text(encoding="utf-8")


def test_200_nonascii_roundtrips_utf8(tmp_path):
    # non-ASCII body round-trips through the utf-8 text cache.
    body = "<p>cash equal to $113.00’s value § ®</p>"
    client, session = _client(tmp_path, [_Resp(200, body)])
    acc = "0001234567-21-000200"
    out = client.fetch_filing_text(cik=320193, accession=acc, primary_doc="doc.htm")
    assert "$113.00’s value § ®" in out
    cp = client.cache_dir / "text" / f"{acc.replace('-', '')}.txt"
    assert cp.exists()
    # Re-reads as utf-8 without error and matches what fetch returned.
    assert cp.read_text(encoding="utf-8") == out
    assert len(session.calls) == 1
    # Second call served from cache (utf-8 read), no new .get.
    out2 = client.fetch_filing_text(cik=320193, accession=acc, primary_doc="doc.htm")
    assert out2 == out
    assert len(session.calls) == 1

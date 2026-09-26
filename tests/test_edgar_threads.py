"""EdgarClient shared by threads: one session per thread, each request's own
headers, one lock per cache file (one request per URL however many threads ask),
atomic and durable cache writes, a dead writer's temp files removed, and
fill-only reads for prefetch threads."""
import json
import os
import subprocess
import sys
import threading
from datetime import date

import pytest
import requests

from delist_detection import atomic_io, edgar
from delist_detection.edgar import EdgarClient, fill_only, filling_only

UA = "Test Co test@example.com"
SUB_URL = "https://data.sec.gov/submissions/CIK0000000042.json"


class _Resp:
    def __init__(self, status=200, text='{"name": "Co"}'):
        self.status_code, self.text, self.url = status, text, "u"

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    """Answers every GET with one status. Records each request's URL and headers
    and, given the client, which cache-file locks were held at that moment."""

    def __init__(self, status=200, client_box=None):
        self.status, self.client_box = status, client_box
        self.calls, self.seen, self.held = [], [], []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        self.seen.append((url, headers))
        if self.client_box:
            client = self.client_box[0]
            self.held.append(sorted(k for k, lock in client._locks.items() if lock.locked()))
        # company_search_atom now requires a real ATOM feed body;
        # every other call in this file reads the default JSON body.
        if "browse-edgar" in url:
            return _Resp(self.status, "<feed></feed>")
        return _Resp(self.status)


def _client(tmp_path, session):
    return EdgarClient(cache_dir=tmp_path, user_agent=UA, session=session, sleep=lambda _: None)


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    return p.pid


def test_each_fetch_holds_the_lock_of_the_file_it_writes(tmp_path):
    box = []
    session = _Session(client_box=box)
    client = _client(tmp_path, session)
    box.append(client)
    client.submissions(42)
    client.fetch_filing_text(42, "0000000042-24-000001", "a.htm")
    client.fetch_filing_raw(42, "0000000042-24-000002")
    assert session.held == [
        [str(client._cache_path(SUB_URL))],
        [str(tmp_path / "text" / "000000004224000001.txt")],
        [str(tmp_path / "raw" / "000000004224000002.txt")],
    ]


def test_a_second_caller_waits_for_the_first_and_reads_its_answer(tmp_path):
    session = _Session()
    client = _client(tmp_path, session)
    cp = client._cache_path(SUB_URL)
    lock = client._lock_for(str(cp))
    lock.acquire()                                    # a first thread is mid-fetch of this URL
    out = []
    # daemon, and the lock released in `finally`: a failed assertion ends the
    # test instead of leaving a worker blocked on the lock and the suite hanging
    t = threading.Thread(target=lambda: out.append(client.submissions(42)), daemon=True)
    try:
        t.start()
        t.join(0.2)
        assert t.is_alive()                           # the second caller waits on the file's lock...
        assert session.calls == []                    # ...without sending a request of its own
        cp.write_text(json.dumps({"name": "First Co", "__fetched__": "2026-09-23"}))   # the first finishes
    finally:
        lock.release()
    t.join(5)
    assert out == [{"name": "First Co", "__fetched__": "2026-09-23"}]
    assert session.calls == []


def test_an_interrupted_write_leaves_the_old_file_whole(tmp_path, monkeypatch):
    path = tmp_path / "x.json"
    path.write_text('{"old": 1}')

    def disk_full(src, dst):
        raise OSError("No space left on device")

    monkeypatch.setattr(atomic_io.os, "replace", disk_full)
    with pytest.raises(OSError):
        atomic_io.write_atomic(path, '{"new": 2}')
    assert path.read_text() == '{"old": 1}'
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]      # no temp file left behind


def test_a_write_replaces_the_file_in_one_step(tmp_path):
    path = tmp_path / "x.json"
    atomic_io.write_atomic(path, '{"new": 2}')
    assert path.read_text() == '{"new": 2}'
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_a_write_reaches_the_disk_before_it_replaces_the_file(tmp_path, monkeypatch):
    events = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        events.append("fsync")
        real_fsync(fd)

    def replace(src, dst):
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(atomic_io.os, "fsync", fsync)
    monkeypatch.setattr(atomic_io.os, "replace", replace)
    atomic_io.write_atomic(tmp_path / "x.json", "{}")
    assert events == ["fsync", "replace", "fsync"]    # the data, the rename, then the directory


def test_temp_files_left_by_a_killed_process_are_removed_at_start(tmp_path):
    (tmp_path / "text").mkdir()
    dead = tmp_path / "text" / f".a.txt.{_dead_pid()}.1.tmp"
    live = tmp_path / f".b.json.{os.getpid()}.1.tmp"          # this process: it may still be writing it
    other = tmp_path / ".c.json.tmp"                          # not a write_atomic name
    for p in (dead, live, other):
        p.write_text("x")
    EdgarClient(cache_dir=tmp_path, user_agent=UA)
    assert not dead.exists() and live.exists() and other.exists()


def _cache_writers():
    from delist_detection.ftd import FtdClient
    from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor
    from delist_detection.midas import MidasClient
    from delist_detection.nasdaq_halts import NasdaqHaltClient
    from delist_detection.openfigi import OpenFigiClient
    return {"ftd": FtdClient, "midas": MidasClient, "halts": NasdaqHaltClient, "openfigi": OpenFigiClient,
            "llm": lambda d: LLMMergerTermsExtractor(None, None, cache_dir=d)}


@pytest.mark.parametrize("writer", ["ftd", "midas", "halts", "openfigi", "llm"])
def test_every_cache_writer_removes_a_killed_runs_leftovers_at_start(tmp_path, writer):
    """Every client that writes its cache through write_atomic cleans its own
    directory at start, as EdgarClient does: a dead process's temp file goes,
    and so does a `.part` file, which only the download code before write_atomic
    wrote (a run killed mid-download). A live process's temp file stays."""
    dead = tmp_path / f".f.zip.{_dead_pid()}.1.tmp"
    live = tmp_path / f".g.zip.{os.getpid()}.1.tmp"
    part = tmp_path / "individual_security_2018_q4.zip.part"
    for p in (dead, live, part):
        p.write_text("x")
    _cache_writers()[writer](tmp_path)
    assert (dead.exists(), part.exists(), live.exists()) == (False, False, True)


def test_a_stray_temp_file_name_neither_breaks_the_client_nor_is_removed(tmp_path):
    superscript = tmp_path / ".x.²2.1.tmp"                  # "²2": str.isdigit() says yes, int() says no
    huge_pid = tmp_path / f".y.json.{'9' * 20}.1.tmp"             # no OS has such a pid: os.kill overflows
    for p in (superscript, huge_pid):
        p.write_text("x")
    EdgarClient(cache_dir=tmp_path, user_agent=UA)
    assert superscript.exists() and huge_pid.exists()


def test_each_thread_gets_its_own_session(tmp_path):
    client = EdgarClient(cache_dir=tmp_path, user_agent=UA)
    mine = client.session
    assert client.session is mine and isinstance(mine, requests.Session)
    theirs = []
    t = threading.Thread(target=lambda: theirs.append(client.session))
    t.start()
    t.join(5)
    assert theirs[0] is not mine and isinstance(theirs[0], requests.Session)
    assert "Host" not in mine.headers                  # no session-wide Host: every request names its own


def test_an_injected_session_is_shared_by_every_thread(tmp_path):
    session = _Session()
    client = _client(tmp_path, session)
    theirs = []
    t = threading.Thread(target=lambda: theirs.append(client.session))
    t.start()
    t.join(5)
    assert client.session is session and theirs == [session]


def test_every_request_names_its_own_host_and_the_user_agent(tmp_path):
    session = _Session()
    client = _client(tmp_path, session)
    client.submissions(42)
    client.fetch_filing_text(42, "0000000042-24-000001", "a.htm")
    client.fetch_filing_raw(42, "0000000042-24-000002")
    client.company_search_atom("X CO")
    client.full_text_search("X", "8-K", date(2020, 1, 1), date(2020, 2, 1))
    assert [h["Host"] for _, h in session.seen] == [
        "data.sec.gov", "www.sec.gov", "www.sec.gov", "www.sec.gov", "efts.sec.gov"]
    assert {h["User-Agent"] for _, h in session.seen} == {UA}


def test_a_failed_filing_text_request_pauses_every_thread(tmp_path, monkeypatch):
    # Item 2: fetch_filing_text is retried like fetch_filing_raw (edgar.retry_request,
    # up to 3 attempts), so a persistent 5xx pauses the shared limiter after each
    # attempt -- the last attempt's backoff (4s) is reused past the table's end.
    pauses = []

    class _Probe:
        def acquire(self):
            pass

        def pause(self, seconds):
            pauses.append(seconds)

    monkeypatch.setattr(edgar, "SEC_LIMITER", _Probe())
    client = _client(tmp_path, _Session(status=503))
    assert client.fetch_filing_text(42, "0000000042-24-000001", "a.htm") == ""
    assert pauses == [edgar.RETRY_BACKOFF[0], edgar.RETRY_BACKOFF[1], edgar.RETRY_BACKOFF[1]]


@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.parametrize("retry", [False, True])
def test_a_refusal_raises_at_once_with_or_without_retries(tmp_path, status, retry):
    session = _Session(status=status)
    client = _client(tmp_path, session)
    with pytest.raises(edgar.EdgarBlocked):
        client._get("https://www.sec.gov/x", host="www.sec.gov", accept="*/*", retry=retry)
    assert session.calls == ["https://www.sec.gov/x"]                 # one request, never retried


def test_a_prefetch_thread_fills_a_missing_copy_but_never_replaces_one(tmp_path):
    session = _Session()
    client = _client(tmp_path, session)
    cp = client._cache_path(SUB_URL)
    old = {"name": "Old Co", "__fetched__": "2020-01-01"}
    cp.write_text(json.dumps(old))
    with fill_only():
        assert client.submissions(42, fresh_after=date(2026, 9, 1)) == old   # older than asked: kept as is
        client.submissions(43)                                              # missing: filled
    assert json.loads(cp.read_text()) == old
    assert session.calls == ["https://data.sec.gov/submissions/CIK0000000043.json"]
    assert client.submissions(42, fresh_after=date(2026, 9, 1))["name"] == "Co"   # outside: refreshed


def test_a_prefetch_thread_keeps_an_existing_copy_even_when_asked_to_refresh(tmp_path):
    session = _Session()
    client = _client(tmp_path, session)
    cp = client._cache_path(SUB_URL)
    old = {"name": "Old Co", "__fetched__": "2020-01-01"}
    cp.write_text(json.dumps(old))
    with fill_only():
        assert client._get_json(SUB_URL, refresh=True) == old          # fill-only wins over refresh
    assert session.calls == [] and json.loads(cp.read_text()) == old
    assert client._get_json(SUB_URL, refresh=True)["name"] == "Co"      # outside: refreshed


def test_fill_only_applies_to_the_calling_thread_alone():
    seen = []
    with fill_only():
        t = threading.Thread(target=lambda: seen.append(filling_only()))
        t.start()
        t.join(5)
        assert filling_only() is True
    assert seen == [False] and filling_only() is False

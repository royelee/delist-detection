"""SEC's cik-lookup-data.txt as a local name -> CIK index (cik-lookup plan)."""
import os
import time
from pathlib import Path

import pytest
import requests

from delist_detection.cik_lookup import CIK_LOOKUP_URL, CikLookupClient, CikNameIndex, normalize_name
from delist_detection.edgar import EdgarBlocked
from delist_detection.sec_stats import SEC_STATS

EXCERPT = (Path(__file__).parent / "fixtures" / "cik_lookup" / "excerpt.txt").read_text(encoding="latin-1")


def _index():
    return CikNameIndex.from_text(EXCERPT)


def _ciks(hits):
    return [h.cik for h in hits]


def test_normalize_name_drops_case_punctuation_ampersands_and_the_state_tag():
    assert normalize_name("Merrill Lynch & Co., Inc.") == "MERRILL LYNCH CO INC"
    assert normalize_name("JACOBS ENGINEERING GROUP INC /DE/") == "JACOBS ENGINEERING GROUP INC"
    assert normalize_name("MERRILL LYNCH PIERCE FENNER & SMITH INC /NY") == "MERRILL LYNCH PIERCE FENNER SMITH INC"
    assert normalize_name("  'MKTG,   INC.' ") == "MKTG INC"
    assert normalize_name("") == ""
    assert normalize_name("NIELSEN N.V.") == normalize_name("NIELSEN NV") == "NIELSEN NV"   # NLSN, live check
    assert normalize_name("U.S. STEEL CORP") == "US STEEL CORP"
    assert normalize_name("ANHEUSER-BUSCH COMPANIES, INC.") == "ANHEUSER BUSCH COMPANIES INC"   # BUD, full run


def test_the_excerpt_parses_every_named_line_and_skips_nameless_ones():
    idx = _index()
    assert len(idx) == 27                       # 29 lines, 2 with no name
    (hit,) = idx.search("2I CAPITAL PCC: STRATEGIC FUND I")      # a colon inside the name survives
    assert (hit.cik, hit.name) == (1508295, "2I CAPITAL PCC: STRATEGIC FUND I")


def test_exact_matches_come_before_prefix_matches():
    hits = _index().search("BARNES & NOBLE INC")
    assert _ciks(hits) == [890491]
    exact, prefix = _index().split_search("AMERICREDIT CORP")
    assert (_ciks(exact), _ciks(prefix)) == ([804269], [1037688])


def test_a_prefix_matches_by_character_as_edgar_does():
    """EDGAR's company search matches a prefix by character: a snapshot's name
    cut off mid-word still finds the company (COCA COLA ENTERPRISE, 2008)."""
    idx = CikNameIndex.from_text("COCA COLA ENTERPRISES INC:0000804055:\nCOCA COLA CO:0000021344:\n")
    assert [h.cik for h in idx.search("COCA COLA ENTERPRISE")] == [804055]
    ciks = set(_ciks(_index().search("BARNES")))
    assert {890491, 1634117, 1222169, 2150699, 1069665} <= ciks


def test_a_former_name_finds_the_current_cik():
    """The file is cumulative: Michael Kors' 2018 rename to Capri Holdings keeps
    CIK 1530721 under both names."""
    assert _ciks(_index().search("MICHAEL KORS HOLDINGS LTD")) == [1530721]
    assert _ciks(_index().search("CAPRI HOLDINGS LTD")) == [1530721]


def test_punctuation_and_state_tags_do_not_block_a_match():
    idx = _index()
    assert sorted(set(_ciks(idx.search("Anheuser-Busch Companies Inc")))) == [310569]
    assert sorted(set(_ciks(idx.search("MERRILL LYNCH CO INC")))) == [65100, 735164]
    assert sorted(set(_ciks(idx.search("JACOBS ENGINEERING GROUP")))) == [52988, 878737, 1963960]


def test_an_unknown_or_blank_query_finds_nothing():
    assert _index().search("NO SUCH COMPANY") == [] and _index().search("  ") == []


# --- CikLookupClient (Task 2) --------------------------------------------------------------


class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code, self.text, self.content, self.url = status, text, text.encode(), CIK_LOOKUP_URL

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    def __init__(self, *responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def _no_throttle(monkeypatch):
    monkeypatch.setattr("delist_detection.sec_limiter.throttle", lambda: None)


def test_the_client_downloads_once_and_reads_the_cache_after(tmp_path, _no_throttle):
    s = _Session(_Resp(text=EXCERPT))
    idx = CikLookupClient(tmp_path, session=s, user_agent="ua").index()
    assert len(idx) == 27 and s.calls == [CIK_LOOKUP_URL]
    assert (tmp_path / "cik-lookup-data.txt").read_text(encoding="latin-1") == EXCERPT
    again = _Session()
    assert len(CikLookupClient(tmp_path, session=again, user_agent="ua").index()) == 27 and again.calls == []


def test_a_copy_older_than_30_days_is_fetched_again(tmp_path, _no_throttle):
    (tmp_path / "cik-lookup-data.txt").write_text("OLD CO:0000000001:\n")
    old = time.time() - 31 * 86400
    os.utime(tmp_path / "cik-lookup-data.txt", (old, old))
    s = _Session(_Resp(text="NEW CO:0000000002:\n"))
    assert [h.cik for h in CikLookupClient(tmp_path, session=s, user_agent="ua").index().search("NEW CO")] == [2]
    assert len(s.calls) == 1


def test_a_failed_refetch_serves_the_old_copy_as_degraded(tmp_path, _no_throttle):
    (tmp_path / "cik-lookup-data.txt").write_text("OLD CO:0000000001:\n")
    old = time.time() - 31 * 86400
    os.utime(tmp_path / "cik-lookup-data.txt", (old, old))
    mark = SEC_STATS.snapshot()
    failing = _Session(*[requests.ConnectionError("down")] * 3)
    assert [h.cik for h in CikLookupClient(tmp_path, session=failing, user_agent="ua",
                                                           sleep=lambda _: None).index().search("OLD CO")] == [1]
    counts, _ = SEC_STATS.since(mark)
    assert counts.get("degraded:stale_copy") == 1


def test_a_refusal_raises(tmp_path, _no_throttle):
    with pytest.raises(EdgarBlocked):
        CikLookupClient(tmp_path, session=_Session(_Resp(429)), user_agent="ua").index()
    assert not (tmp_path / "cik-lookup-data.txt").exists()

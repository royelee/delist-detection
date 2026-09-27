"""build_golden_fixtures.py: a filing with an empty filingDate must not abort a
capture after the network work is already spent."""
import importlib.util
from datetime import date
from pathlib import Path

from delist_detection.edgar import EdgarSubmission

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_golden_fixtures_under_test",
                                               ROOT / "scripts" / "build_golden_fixtures.py")
bgf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bgf)

ON = date(2023, 6, 1)


def _f(day):
    return EdgarSubmission(accession=f"A{day}", form="8-K", filing_date=day,
                           report_date=day, items="", primary_doc="a.htm")


def test_near_event_skips_a_filing_with_an_empty_date():
    fs = [_f("2023-05-30"), _f(""), _f("2023-06-10")]
    assert [f.filing_date for f in bgf._near_event(fs, ON)] == ["2023-05-30", "2023-06-10"]


def test_near_event_keeps_only_the_window_around_the_event():
    fs = [
        _f((ON - bgf.timedelta(days=bgf.BEFORE_DAYS + 1)).isoformat()),   # too old
        _f((ON - bgf.timedelta(days=bgf.BEFORE_DAYS)).isoformat()),
        _f((ON + bgf.timedelta(days=bgf.AFTER_DAYS)).isoformat()),
        _f((ON + bgf.timedelta(days=bgf.AFTER_DAYS + 1)).isoformat()),    # too new
    ]
    assert len(bgf._near_event(fs, ON)) == 2


def test_the_builder_client_bypasses_the_search_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Co test@example.com")
    assert bgf._client(tmp_path).search_cache is False


def test_recording_keeps_each_efts_answer_as_the_fixtures_store_it():
    class _R:
        status_code = 200

        def json(self):
            return {"hits": {"total": {"value": 1}, "hits": [
                {"_id": "a:b", "_score": 1.0, "_source": {"ciks": ["1"], "display_names": ["X"], "sics": ["1"]}}]}}

    bgf._efts_raw.clear()
    get = bgf._recording(lambda url, **kw: _R())
    get("https://efts.sec.gov/LATEST/search-index?q=x", headers={}, timeout=30)
    get("https://data.sec.gov/submissions/CIK0000000001.json", headers={}, timeout=30)
    assert bgf._efts_raw == {"https://efts.sec.gov/LATEST/search-index?q=x": {"hits": {
        "total": {"value": 1}, "hits": [{"_source": {"ciks": ["1"], "display_names": ["X"]}}]}}}

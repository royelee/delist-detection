"""Offline test for scripts/verify_against_web.py: every EDGAR request it makes
goes through the library's shared SEC pacing (8 requests/s), like EdgarClient."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_against_web", ROOT / "scripts" / "verify_against_web.py")
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class _Resp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"name": "ACME CORP", "formerNames": [], "tickers": [], "filings": {"recent": {}}}


def test_a_refusal_aborts_instead_of_becoming_a_verdict(monkeypatch):
    import pytest
    from delist_detection.edgar import EdgarBlocked

    class _Refused(_Resp):
        status_code = 403

    monkeypatch.setattr(verify, "_throttle", lambda: None)
    monkeypatch.setattr(verify.requests, "get", lambda *a, **kw: _Refused())
    with pytest.raises(EdgarBlocked):
        verify.fetch_edgar_entity_landing(320193)
    with pytest.raises(EdgarBlocked):
        verify._get("https://www.sec.gov/cgi-bin/browse-edgar")


def test_every_edgar_request_is_paced(monkeypatch):
    events = []
    monkeypatch.setattr(verify, "_throttle", lambda: events.append("throttle"))
    monkeypatch.setattr(verify.requests, "get", lambda *a, **kw: events.append("get") or _Resp())
    verify.fetch_edgar_entity_landing(320193)
    verify._get("https://www.sec.gov/cgi-bin/browse-edgar")
    assert events == ["throttle", "get", "throttle", "get"]

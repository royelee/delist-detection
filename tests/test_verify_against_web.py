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

    monkeypatch.setattr(verify, "throttle", lambda: None)
    monkeypatch.setattr(verify.requests, "get", lambda *a, **kw: _Refused())
    with pytest.raises(EdgarBlocked):
        verify.fetch_edgar_entity_landing(320193)
    with pytest.raises(EdgarBlocked):
        verify._get("https://www.sec.gov/cgi-bin/browse-edgar")


def test_every_edgar_request_is_paced(monkeypatch):
    events = []
    monkeypatch.setattr(verify, "throttle", lambda: events.append("throttle"))
    monkeypatch.setattr(verify.requests, "get", lambda *a, **kw: events.append("get") or _Resp())
    verify.fetch_edgar_entity_landing(320193)
    verify._get("https://www.sec.gov/cgi-bin/browse-edgar")
    assert events == ["throttle", "get", "throttle", "get"]


def _sub(name, rows, former=(), files=()):
    keys = ("form", "filingDate", "items")
    return {"name": name, "formerNames": [{"name": n} for n in former], "tickers": [],
            "filings": {"recent": {k: [r[i] for r in rows] for i, k in enumerate(keys)},
                        "files": list(files)}}


class _JsonResp:
    status_code = 200

    def __init__(self, d):
        self.d = d

    def json(self):
        return self.d


def _serve(monkeypatch, by_url):
    monkeypatch.setattr(verify, "throttle", lambda: None)
    monkeypatch.setattr(verify.requests, "get", lambda url, **kw: _JsonResp(by_url[url]))


def _row(ticker, bucket, cik, name, day):
    return {"sec_id": "BBG", "ticker": ticker, "bucket": bucket, "cik": str(cik), "resolved_name": name,
            "crsp_code": "", "reason": "", "last_trade_date": day, "delist_date": day}


def test_camel_case_edgar_names_match_run_together_names(monkeypatch):
    """EDGAR writes "BlackRock, Inc.", the snapshots "BLACKROCK INC": the camelCase
    split alone made them share no word (MISMATCH_name)."""
    url = "https://data.sec.gov/submissions/CIK0002012383.json"
    _serve(monkeypatch, {url: _sub("BlackRock, Inc.", [("8-K12B", "2024-10-01", "")])})
    v = verify.verify_one(_row("BLK", "exchange_transfer", 2012383, "BLACKROCK INC", "2024-10-02"))
    assert v["verdict"] != "MISMATCH_name" and v["name_match"] == "1/1"


def test_a_merger_is_confirmed_by_merger_documents_in_older_filings(monkeypatch):
    """Genentech (Roche, 2009) filed no 8-K 2.01/5.01; its SC 14D9 and Form 25 sit in
    an older submissions file, past the `recent` block the verifier read."""
    base = "https://data.sec.gov/submissions/"
    _serve(monkeypatch, {
        base + "CIK0000318771.json": _sub("GENENTECH INC", [("10-K", "2010-02-01", "")],
                                          files=[{"name": "CIK0000318771-submissions-001.json",
                                                  "filingFrom": "2004-01-01", "filingTo": "2009-12-31"}]),
        base + "CIK0000318771-submissions-001.json": {
            "form": ["25-NSE", "15-12B", "SC 14D9", "8-K"], "filingDate": ["2009-03-26", "2009-04-06",
                                                                         "2009-02-23", "2006-05-01"],
            "items": ["", "", "", "2.01"]},
    })
    v = verify.verify_one(_row("DNA", "merger", 318771, "GENENTECH INC", "2009-03-25"))
    assert v["verdict"] == "OK" and v["delist_form_present"] == "25=Y,15=Y"


def test_a_bankruptcy_8k_confirms_a_liquidation_without_form15(monkeypatch):
    url = "https://data.sec.gov/submissions/CIK0000768835.json"
    _serve(monkeypatch, {url: _sub("BIG LOTS INC", [("25-NSE", "2024-09-10", ""), ("8-K", "2024-09-10", "1.03,7.01")])})
    v = verify.verify_one(_row("BIG", "liquidation", 768835, "BIG LOTS INC", "2024-09-10"))
    assert v["verdict"] == "OK"


def test_an_old_unrelated_8k_does_not_confirm_a_merger(monkeypatch):
    # a 2.01 years before the delisting is some other deal, not this one
    url = "https://data.sec.gov/submissions/CIK0000000001.json"
    _serve(monkeypatch, {url: _sub("ACME CORP", [("25-NSE", "2020-06-01", ""), ("8-K", "2012-01-05", "2.01")])})
    v = verify.verify_one(_row("ACME", "merger", 1, "ACME CORP", "2020-05-29"))
    assert v["verdict"] == "WEAK_no_ma_items"


def test_main_installs_the_machine_wide_limit_and_checks_the_user_agent_before_any_request(
        monkeypatch, tmp_path):
    import csv
    import sys

    events = []
    monkeypatch.setattr(verify, "use_machine_wide_limit", lambda: events.append("machine-wide limit"))
    monkeypatch.setattr(verify, "require_user_agent", lambda: events.append("user agent") or "Test Co t@example.com")
    monkeypatch.setattr(verify, "throttle", lambda: events.append("throttle"))
    url = "https://data.sec.gov/submissions/CIK0000768835.json"
    body = _sub("BIG LOTS INC", [("25-NSE", "2024-09-10", ""), ("8-K", "2024-09-10", "1.03,7.01")])
    monkeypatch.setattr(verify.requests, "get", lambda u, **kw: events.append("get") or _JsonResp(body))
    row = _row("BIG", "liquidation", 768835, "BIG LOTS INC", "2024-09-10")
    src, out = tmp_path / "delistings.csv", tmp_path / "web_verification.csv"
    with src.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    monkeypatch.setattr(sys, "argv", ["verify_against_web.py", "--input", str(src), "--output", str(out)])
    assert verify.main() == 0
    assert events[:2] == ["user agent", "machine-wide limit"]
    assert "get" in events[2:] and events.count("get") == events.count("throttle")

"""Pipeline stage 9's links from the registrant's own filings (sub-plan 5c, rules 3 and 4), on the real cases of
tests/fixtures/issuer_role/: what the shares became one for one, and the line a same-CIK successor registration
moved the holders to."""
from __future__ import annotations

import pytest

from tests import issuer_role_cases as ic

CCO, NEW_CUSIP = "BBG000J453J8", "18453H106"


def _rows(composite):
    return {"data": [dict(r, compositeFIGI=composite) for r in ic.FIGI[NEW_CUSIP]["data"]]}


def test_a_same_cik_registrations_new_cusip_with_its_own_composite_is_the_successor():
    """CCO 2019: Clear Channel Outdoor's 8-K12B under its own CIK; its new CUSIP 18453H106 first fails under CCO on
    2019-05-03, OpenFIGI's BBG000SSC5C9 (R2: two securities)."""
    assert ic.outcome(CCO) == [("2019-05-12", "exchange_transfer", 304, "BBG000SSC5C9", "own_registration")]


def test_a_new_cusip_on_the_securitys_own_composite_is_the_security_going_on(monkeypatch):
    monkeypatch.setitem(ic.FIGI, NEW_CUSIP, _rows(CCO))
    assert ic.outcome(CCO) == [("2019-05-12", "exchange_transfer", 304, CCO, "own_registration")]


@pytest.mark.parametrize("answer", [{"error": "No identifier found."}, "two"], ids=["error", "several"])
def test_an_unsettled_new_cusip_links_nothing(monkeypatch, answer):
    """OKE 2026's new CUSIP is not in the cache (an error answer); several composites settle nothing either: the
    row keeps successor_unknown."""
    if answer == "two":
        answer = {"data": _rows("BBG000SSC5C9")["data"] + _rows("BBG000SSC5C0")["data"]}
    monkeypatch.setitem(ic.FIGI, NEW_CUSIP, answer)
    assert ic.outcome(CCO) == [("2019-05-12", "exchange_transfer", 304, "", "")]
    assert ic.outcome("BBG000BQHGR6") == [("2026-09-28", "exchange_transfer", 304, "", "")]       # OKE 2026


def test_the_new_issuer_link_reads_the_registrants_own_conversion_sentence():
    """HHC 2023: "each outstanding share of the Company's common stock ... was automatically converted into one
    share of common stock ... of Holdco", Holdco being Howard Hughes Holdings Inc., first filed 2023-08-11."""
    edgar = ic.FixtureEdgar()
    assert ic.outcome("BBG000MJRJJ2", edgar=edgar) == [
        ("2023-08-24", "exchange_transfer", 304, "BBG01HTMDZ54", "new_issuer")]
    assert "0001104659-23-090461" in edgar.texts_read

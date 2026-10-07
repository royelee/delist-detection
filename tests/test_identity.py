"""The identity stage at its interface: `identity.identify` (stages 1 to 4) and its answer, `identity.Identity`.

The real cases run through the same interface in tests/test_identity_cases.py (sub-plan 5h's fixture) and
tests/test_resolver_renamed.py (the renamed tickers: the second pass's degraded reads, the CUSIP handoffs reaching the
FIGI stage, each era's own name). These take small doubles: the issuer lookup answering by era
(`identity_cases.CommittedLookup`), an EDGAR client, a fails client and OpenFIGI with nothing to say."""
from __future__ import annotations

from datetime import date

import pytest
import requests

from delist_detection.ftd import FtdIndex
from delist_detection.identity import Identity, identify
from delist_detection.observations import Observation, ObservationError, ObservationIndex, TickerEra
from delist_detection.pipeline import Clients
from delist_detection.security_master import EraResolution, Issuer, Security
from tests.identity_cases import CommittedLookup

AS_OF = date(2026, 9, 25)


class _Edgar:
    """Each CIK's submissions: its name, no former names."""

    def __init__(self, names: dict[int, str]) -> None:
        self.names = names

    def submissions(self, cik, fresh_after=None):
        name = self.names.get(int(cik))
        return {"name": name, "formerNames": []} if name else {"__not_found__": True}

    def recent_filings(self, cik):
        return []


class _NoRows:
    """SEC's fails files with no row for anything."""

    def urls_for(self, lo, hi):
        return ["none"]

    def rows(self, url, *, symbols=None, cusips=None):
        return iter(())


class _NoFigi:
    """OpenFIGI with no US line for anything."""

    def map(self, jobs):
        return [{"data": []} for _ in jobs]

    def filter(self, query, **fields):
        return []


class _DegradedLookup(CommittedLookup):
    """A lookup whose every answer rested on a failed request or a stale copy."""

    def is_degraded(self, ticker, observed_date=None, *, name=None) -> bool:
        return True


def _identify(observations, lookup, names=None):
    clients = Clients(edgar=_Edgar(names or {}), resolver=lookup, classifier=None, figi=_NoFigi(),
                      ftd_client=_NoRows(), as_of=AS_OF)
    return identify(ObservationIndex(observations), clients, as_of=AS_OF)


AAA = [Observation("AAA", "2015-06-30", "AAA CORP"), Observation("AAA", "2016-06-30", "AAA CORP")]


def test_no_observation_is_an_error():
    with pytest.raises(ObservationError, match="no observations to process"):
        _identify([], CommittedLookup({}))


def test_an_era_its_lookup_answered_is_its_issuers_placeholder_with_that_tier():
    """No FIGI confirms the era: it holds its issuer's placeholder (`no_figi`), its issuer is the lookup's answer and
    named from EDGAR, and its tier is the one the lookup found it by; nothing is degraded or decided by rows. No fails
    row shows its ticker (`ticker_unconfirmed`)."""
    identity = _identify(AAA, CommittedLookup({"AAA@2015-06-30": (101, "company_tickers")}), {101: "AAA CORP"})
    assert [e.key for e in identity.eras] == ["AAA@2015-06-30"]
    assert identity.issuers == {"AAA@2015-06-30": Issuer(101, ("AAA CORP",))}
    assert identity.tier("AAA@2015-06-30") == "company_tickers"
    assert set(identity.securities) == {"CIK101-COMMON"} and identity.cusips == {"CIK101-COMMON": []}
    assert identity.resolution_source(identity.securities["CIK101-COMMON"]) == "company_tickers"
    assert identity.rows_decided == frozenset()
    assert [(r.sec_id, r.flag) for r in identity.review] == [("CIK101-COMMON", "no_figi"),
                                                              ("CIK101-COMMON", "ticker_unconfirmed")]


def test_an_answer_the_lookup_says_rested_on_a_failed_read_is_reported_degraded():
    """The lookup's own answer rested on a failed request: the era's `resolution_degraded` item says so (the answer
    is used for this run, never saved)."""
    identity = _identify(AAA, _DegradedLookup({"AAA@2015-06-30": (101, "efts")}), {101: "AAA CORP"})
    degraded = [r for r in identity.review if r.flag == "resolution_degraded"]
    assert [(r.sec_id, r.ticker, r.cik) for r in degraded] == [("CIK101-COMMON", "AAA", 101)]
    assert "AAA@2015-06-30 AAA CORP: issuer resolution" in degraded[0].reason


def test_an_issuer_whose_names_cannot_be_read_is_reported_degraded():
    """The issuer's EDGAR names could not be read: its eras are checked without them, and say so."""
    class _Down(_Edgar):
        def submissions(self, cik, fresh_after=None):
            raise requests.ConnectionError("down")

    clients = Clients(edgar=_Down({}), resolver=CommittedLookup({"AAA@2015-06-30": (101, "manual")}),
                      classifier=None, figi=_NoFigi(), ftd_client=_NoRows(), as_of=AS_OF)
    identity = identify(ObservationIndex(AAA), clients, as_of=AS_OF)
    assert identity.issuers == {"AAA@2015-06-30": Issuer(101, ())}
    assert [r.reason for r in identity.review if r.flag == "resolution_degraded"] == [
        "AAA@2015-06-30 AAA CORP: the issuer's EDGAR names rested on a failed EDGAR request or a stale copy; "
        "its CUSIPs and FIGI were checked without what could not be read"]


def test_an_era_with_no_issuer_is_unresolved():
    identity = _identify(AAA, CommittedLookup({}))
    assert identity.resolutions["AAA@2015-06-30"].sec_id is None and identity.securities == {}
    assert identity.tier("AAA@2015-06-30") == "none"
    assert [r.flag for r in identity.review] == ["observation_unresolved", "ticker_unconfirmed"]


# --- the answer's facts ---------------------------------------------------------------------------------------------

OLD, NEW = TickerEra("X", "2010-01-04", "2012-06-29", []), TickerEra("X", "2014-06-30", "2016-06-30", [])


def _answer(issuers: dict, tiers: dict, resolutions: dict | None = None) -> Identity:
    eras = {e.key: e for e in (OLD, NEW)}
    return Identity(list(eras.values()), eras, FtdIndex(), date(2004, 1, 1), issuers, resolutions or {},
                    tiers=tiers)


def test_resolution_source_comes_from_the_latest_era_that_has_a_cik():
    sec = Security("BBGX", 5, "COMMON", "X CO", "Common Stock", True, "cusip", eras=[OLD, NEW])
    tiers = {OLD.key: "manual", NEW.key: "none"}
    assert _answer({OLD.key: Issuer(5)}, tiers).resolution_source(sec) == "manual"   # the era issuer_cik came from
    tiers[NEW.key] = "company_tickers"
    assert _answer({OLD.key: Issuer(5), NEW.key: Issuer(5)}, tiers).resolution_source(sec) == "company_tickers"
    assert _answer({}, tiers).resolution_source(sec) == "security_master"


def test_an_era_the_lookup_was_not_asked_about_has_no_tier():
    assert _answer({}, {OLD.key: "cik_map"}).tier(NEW.key) == ""


def _res(era, sec_id, source="cusip"):
    return EraResolution(era.key, sec_id, source, None, ())


def test_the_securities_a_changed_set_of_resolutions_gives():
    """Stage 4b folds a placeholder's era into a FIGI line: the securities are built again from the identity's eras
    and issuers, the FIGI line holding both eras and its issuer from its latest one."""
    before = {OLD.key: _res(OLD, "CIK5-COMMON", "placeholder"), NEW.key: _res(NEW, "BBGX")}
    identity = _answer({OLD.key: Issuer(5), NEW.key: Issuer(6)}, {}, before)
    after = identity.securities_of({**before, OLD.key: _res(OLD, "BBGX", "handoff")})
    assert set(after) == {"BBGX"}
    assert ([e.key for e in after["BBGX"].eras], after["BBGX"].issuer_cik) == ([OLD.key, NEW.key], 6)


def test_a_placeholder_is_renamed_to_the_one_figi_its_eras_hold_and_never_otherwise():
    """CIK5's eras hold BBGX: its placeholder is renamed to it. Two FIGIs, or an era still on the placeholder, is no
    rename."""
    issuers = {OLD.key: Issuer(5), NEW.key: Issuer(5)}
    identity = _answer(issuers, {})
    assert identity.renames({OLD.key: _res(OLD, "BBGX"), NEW.key: _res(NEW, "BBGX")}) == {"CIK5-COMMON": "BBGX"}
    assert identity.renames({OLD.key: _res(OLD, "BBGX"), NEW.key: _res(NEW, "BBGY")}) == {}
    assert identity.renames({OLD.key: _res(OLD, "BBGX"), NEW.key: _res(NEW, "CIK5-COMMON", "placeholder")}) == {}

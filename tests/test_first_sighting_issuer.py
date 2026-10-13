"""An era no lookup answers at its capped date or at the end of its own fails rows is asked once more at its first
sighting (`identity._resolve_issuers`): WestRock (WRK, observed 2015 to 2024) has two issuers, the company of 2015 and
the holding company formed in 2018 that holds the name at the end, which the era-began-by rule refuses."""
from __future__ import annotations

from datetime import date

from test_derived_origin import _Edgar, _Fails, _Figi, _rows
from delist_detection.identity.identity import identify
from delist_detection.identity.observations import Observation, ObservationIndex
from delist_detection.identity.ticker_resolver import TickerResolution
from delist_detection.pipeline import Clients

AS_OF = date(2026, 9, 25)
HALVES = [f"{y}-{md}" for y in range(2016, 2025) for md in ("06-30", "12-31")][:-1]
OBS = [Observation("W", d, "W CO") for d in ["2015-12-31", *HALVES]]


class _ByDate:
    """The lookup answers by the date it is asked at: `answers` maps a date to (CIK, tier); any other date is a miss."""

    issuers = None

    def __init__(self, answers, otherwise=(None, "rejected_validation")):
        self.answers, self.otherwise, self.dates = answers, otherwise, []

    def resolve(self, ticker, observed_date=None, *, pin=None, name=None, since=None, exclude=()):
        self.dates.append(observed_date)
        cik, tier = self.answers.get(observed_date, self.otherwise)
        return TickerResolution(ticker, cik, None, tier)

    def is_degraded(self, *a, **kw):
        return False

    def frequency_candidates(self, ticker, day):
        return [], False

    def shadow(self):
        return self

    def flush(self):
        pass


def _identify(lookup):
    rows = _rows("W", "11111A101", ["2015-12-02", "2018-07-02", "2024-07-01"], "W CO", 10.0)
    figi = _Figi({"11111A101": ("BBGW", "W CO")})
    clients = Clients(edgar=_Edgar({101: "W CO"}), resolver=lookup, classifier=None, figi=figi,
                      ftd_client=_Fails(rows), as_of=AS_OF)
    return identify(ObservationIndex(OBS), clients, as_of=AS_OF)


def test_an_era_with_no_answer_at_its_last_sighting_takes_the_issuer_found_at_its_first():
    lookup = _ByDate({"2015-12-31": (101, "name_search")})
    got = _identify(lookup)
    assert got.issuers["W@2015-12-31"].cik == 101 and got.tier("W@2015-12-31") == "name_search"
    assert "2015-12-31" in lookup.dates


def test_an_era_answered_at_its_last_sighting_is_not_asked_at_its_first():
    lookup = _ByDate({"2015-12-31": (101, "name_search")}, otherwise=(202, "name_search"))
    got = _identify(lookup)
    assert got.issuers["W@2015-12-31"].cik == 202 and "2015-12-31" not in lookup.dates


def test_a_weak_answer_at_the_first_sighting_is_no_answer():
    lookup = _ByDate({"2015-12-31": (101, "efts_name_mismatch")})
    got = _identify(lookup)
    assert "W@2015-12-31" not in got.issuers or got.issuers["W@2015-12-31"].cik != 101 or got.tier("W@2015-12-31") != "name_search"


def test_an_era_with_only_weak_answers_is_asked_at_its_first_sighting_too():
    """Triad Hospitals (TRI, FB-026): bought in July 2007 and still named by the snapshots of 2008. At the era's two
    later dates full-text search finds other companies, weakly (TRI-S Security, Tri-Valley), and the fails rows
    under TRI are Thomson Reuters', so the weak answer is dropped and the seeds were not placed. At the first
    sighting the name search answers Triad."""
    lookup = _ByDate({"2015-12-31": (101, "name_search")}, otherwise=(303, "efts_name_mismatch"))
    got = _identify(lookup)
    assert got.issuers["W@2015-12-31"].cik == 101 and got.tier("W@2015-12-31") == "name_search"


def test_a_weak_answer_at_the_first_sighting_leaves_the_weak_answer_of_the_later_dates():
    lookup = _ByDate({"2015-12-31": (101, "efts_name_mismatch")}, otherwise=(303, "efts_name_mismatch"))
    got = _identify(lookup)
    assert "2015-12-31" in lookup.dates
    assert "W@2015-12-31" not in got.issuers or got.issuers["W@2015-12-31"].cik != 101

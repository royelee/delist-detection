"""Renamed tickers resolve to their issuer (KORS -> Capri Holdings, NU -> Eversource,
LUK -> Jefferies Financial), and a recycled ticker never reaches today's holder
(NU -> Nu Holdings, ALTR -> Altair).

Offline, over real data: tests/fixtures/eras/renamed_observations.csv (the
observations of the tickers involved), renamed_ftd_rows.csv (their SEC
fails-to-deliver rows, thinned), and renamed_edgar.json (each CIK's EDGAR names
and a thinned filing list, the 8-K frequency rank EDGAR full-text search gave at
each era's last sighting, and EDGAR company-search answers)."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from delist_detection import manifest as run_manifest
from delist_detection import pipeline
from delist_detection.edgar import EdgarSubmission
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.observations import ObservationIndex, load_observations
from delist_detection.pipeline import Clients, _RunContext
from delist_detection.security_master import era_last_seen, refine_eras
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "eras"
DATA = json.loads((FIX / "renamed_edgar.json").read_text())
FTD_WINDOW = (date(2007, 12, 17), date(2026, 9, 25))     # the committed run's fails-to-deliver window


class _Edgar:
    """EDGAR as the fixture recorded it: submissions (name and former names),
    the thinned filing list, company-search answers, and SEC's ticker map."""

    def __init__(self, issuers=None, tickers=None):
        self.issuers = issuers if issuers is not None else DATA["issuers"]
        self.tickers = tickers or {}

    def company_tickers(self):
        return self.tickers

    def submissions(self, cik, fresh_after=None):
        d = self.issuers.get(str(int(cik)))
        if d is None:
            return {"__not_found__": True}
        return {"name": d["name"], "formerNames": d["formerNames"], "sic": ""}

    def recent_filings(self, cik):
        d = self.issuers.get(str(int(cik))) or {"filings": []}
        return [EdgarSubmission(f"{cik}-{i}", form, day, "", "", "x.htm") for i, (form, day) in
                enumerate(d["filings"])]

    def company_search_atom(self, company, form_type="25-NSE"):
        return [dict(h) for h in DATA["company_search"].get(f"{company}|{form_type}", [])]


class _RowsClient:
    """An FTD client over in-memory rows, filtered the way the real one filters."""

    def __init__(self, rows):
        self.rows_ = list(rows)

    def urls_for(self, lo, hi):
        return ["mem"]

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self.rows_:
            if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                yield r


def _rows():
    with (FIX / "renamed_ftd_rows.csv").open(newline="") as fh:
        return [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"], float(r["price"]) if r["price"] else None)
                for r in csv.DictReader(fh)]


@pytest.fixture(scope="module")
def index():
    return ObservationIndex(load_observations(FIX / "renamed_observations.csv"))


@pytest.fixture(scope="module")
def ftd(index):
    return FtdIndex.load(_RowsClient(_rows()), *FTD_WINDOW, symbols={e.ticker for e in index.eras()})


@pytest.fixture(scope="module")
def eras(index, ftd):
    return {e.key: e for e in refine_eras(index.eras(), ftd)}


@pytest.fixture
def frequency(monkeypatch):
    """The 8-K frequency tier answers with the rank EDGAR gave (the fixture's)."""
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: [tuple(x) for x in DATA["frequency"].get(f"{t}|{d}", [])])


def test_the_fixture_eras_and_last_sightings_are_the_real_ones(eras, ftd):
    seen = {k: era_last_seen(e, ftd) for k, e in eras.items() if e.ticker in {"KORS", "NU", "LUK", "LMCA"}}
    assert seen == {"KORS@2012-06-29": "2015-08-03", "KORS@2014-12-31": "2019-01-03",
                    "LMCA@2012-06-29": "2013-01-16", "LMCA@2013-06-28": "2016-04-18",
                    "LUK@2008-01-16": "2010-07-13", "LUK@2012-06-29": "2015-08-04", "LUK@2014-12-31": "2018-05-25",
                    "NU@2008-01-16": "2015-02-20", "NU@2023-06-30": "2026-08-31", "NU@2026-06-30": "2026-08-31"}


# --- 1a: each era is looked up under its own name --------------------------------

def _ctx(resolver, edgar=None):
    clients = Clients(edgar=edgar or _Edgar(), resolver=resolver, classifier=None, figi=None, ftd_client=None,
                      as_of=FTD_WINDOW[1])
    return _RunContext(clients, FTD_WINDOW[1], lambda *a: None, 1, run_manifest.StageMeter(lambda *a: None))


def test_each_era_is_looked_up_under_its_own_name(index, eras, ftd):
    """KORS@2012's FTD rows (its CUSIP's, shared with KORS@2014) run to
    2015-08-03, past its last observation and after KORS@2014's first: the
    observation lookup would give it KORS@2014's name."""
    calls = []

    class Spy(TickerResolver):
        def resolve(self, ticker, observed_date=None, **kw):
            calls.append((ticker, observed_date, kw.get("name")))
            return super().resolve(ticker, observed_date, **kw)

    spy = Spy(_Edgar(), observed_names=index.name_on)
    pipeline._resolve_issuers(_ctx(spy), [eras["KORS@2012-06-29"], eras["KORS@2014-12-31"]], ftd)
    assert index.name_on("KORS", "2015-08-03") == "MICHAEL KORS HOLDINGS LTD"
    assert calls == [("KORS", "2015-08-03", "CAPRI HOLDINGS LTD"), ("KORS", "2019-01-03", "MICHAEL KORS HOLDINGS LTD")]


ALTAIR_MAP = {"ALTR": {"cik_str": 1701732, "ticker": "ALTR", "title": "Altair Engineering Inc."}}


def test_a_lookup_is_checked_against_the_name_it_is_given_not_the_nearest_observation():
    """The observation lookup can land on another era's name (an era's FTD rows
    run past its last observation, toward the next era's). `name=` is the era's
    own: SEC's ticker map holder Altair is taken for an Altair era, and refused
    when the nearest observation's name is Altera's."""
    r = TickerResolver(_Edgar(tickers=ALTAIR_MAP), observed_names=lambda t, d=None: "ALTERA CORP")
    assert r.resolve("ALTR", "2020-06-30").cik is None
    assert r.resolve("ALTR", "2020-06-30", name="ALTAIR ENGINEERING INC CLASS A").cik == 1701732
    assert r.resolve("ALTR", "2020-06-30", name="ALTERA CORP").cik is None

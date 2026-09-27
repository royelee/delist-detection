"""A renamed ticker's eras join the new ticker's FIGI (spec §17, "A CUSIP handoff
joins the new line"): KORS's eras reach Capri Holdings' BBG0029SNR63 through
Michael Kors' CUSIP, which ended as CPRI's began; Northeast Utilities' NU era
reaches Eversource's BBG000BQ87N0 the same way.

Offline, over real data: tests/fixtures/eras/renamed_observations.csv and
renamed_ftd_rows.csv (the eras and their fails rows, as in
test_resolver_renamed.py), renamed_edgar.json (each issuer's EDGAR names), and
renamed_openfigi.json: OpenFIGI's cached answers to every mapping job and name
search these eras make (thinned to the composites with a US venue row, and a
name search to those carrying the asking era's ticker), and the issuer CIK each
era resolved to in the cache-only replay of the committed run ("ciks")."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from delist_detection.evidence import edgar_names
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.observations import ObservationIndex, load_observations
from delist_detection.security_master import (
    FigiResolver, candidate_cusips, cusip_handoffs, issuers_by_era, refine_eras,
)

FIX = Path(__file__).parent / "fixtures" / "eras"
EDGAR = json.loads((FIX / "renamed_edgar.json").read_text())
FIGI = json.loads((FIX / "renamed_openfigi.json").read_text())
FTD_WINDOW = (date(2007, 12, 17), date(2026, 9, 25))     # the committed run's fails-to-deliver window
NAMES = {int(c): edgar_names({"name": d["name"], "formerNames": d["formerNames"]})
         for c, d in EDGAR["issuers"].items()}


class _Figi:
    """OpenFIGI as the fixture recorded it."""

    def map(self, jobs, use_cache=True):
        return [{"data": FIGI["mapping"][f"{j['idType']}|{j['idValue']}"]} for j in jobs]

    def filter(self, query, **fields):
        return FIGI["filter"].get(query, [])


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
def ftd():
    index = ObservationIndex(load_observations(FIX / "renamed_observations.csv"))
    return FtdIndex.load(_RowsClient(_rows()), *FTD_WINDOW, symbols={e.ticker for e in index.eras()})


@pytest.fixture(scope="module")
def eras(ftd):
    index = ObservationIndex(load_observations(FIX / "renamed_observations.csv"))
    return {e.key: e for e in refine_eras(index.eras(), ftd)}


def _resolve(eras, ftd, keys, *, ciks=None, handoffs=None, cusips=None, log=None):
    """Stage 3 over the eras `keys`: their issuers the replay's (`ciks` overrides
    some), their candidate CUSIPs (`cusips` overrides some), and the CUSIP links
    between them (`handoffs`, else `cusip_handoffs`'s)."""
    chosen = [eras[k] for k in keys]
    issuers = issuers_by_era({k: {**FIGI["ciks"], **(ciks or {})}.get(k) for k in keys}, NAMES)
    tried = {**candidate_cusips(chosen, ftd, issuers), **(cusips or {})}
    links = cusip_handoffs(chosen, ftd) if handoffs is None else handoffs
    return FigiResolver(_Figi(), log=log).resolve_many(chosen, issuers=issuers, cusips=tried, handoffs=links)


def _placed(res):
    return {k: (r.sec_id, r.source) for k, r in res.items()}


KORS = ["KORS@2012-06-29", "KORS@2014-12-31", "CPRI@2018-12-31"]


def test_a_renamed_tickers_eras_join_the_new_tickers_figi(eras, ftd):
    """Michael Kors Holdings renamed itself Capri Holdings (2018-12-31): its CUSIP
    G60754101 last traded under KORS on 2019-01-03, CPRI's G1890L107 first failed
    on 2019-01-02, and OpenFIGI knows the old CUSIP on no US venue. The two KORS
    eras (sharing that CUSIP) join the line CPRI's CUSIP confirms, and keep their
    CUSIP; with no CUSIP links they stay on the issuer's placeholder."""
    res = _resolve(eras, ftd, KORS)
    assert _placed(res) == {"KORS@2012-06-29": ("BBG0029SNR63", "handoff"),
                            "KORS@2014-12-31": ("BBG0029SNR63", "handoff"),
                            "CPRI@2018-12-31": ("BBG0029SNR63", "cusip")}
    assert [res[k].cusips for k in KORS] == [("G60754101",), ("G60754101",), ("G1890L107",)]
    assert set(_placed(_resolve(eras, ftd, KORS, handoffs=[])).values()) == {
        ("CIK1530721-COMMON", "placeholder"), ("BBG0029SNR63", "cusip")}


NU_ES = ["NU@2008-01-16", "ES@2012-06-29", "ES@2015-06-30"]


def test_nu_2008_joins_es_2015s_line_and_frees_es_2012_from_guard_c(eras, ftd):
    """Northeast Utilities traded as NU (664397106) until Eversource Energy's
    2015 rename gave it a new CUSIP (30040W108, first failed 2015-02-19, ES's
    own since); NU's old CUSIP is unknown to OpenFIGI on any US venue, so NU@2008
    has no pick of its own and joins ES@2015's line through the switch. ES@2012
    (also Northeast Utilities, before the ticker itself moved to Eversource) has
    no CUSIP of its own either (its FTD CUSIP 292756202 describes a different,
    unrelated company, EnergySolutions, that held the ES ticker earlier): it
    reaches BBG000BQ87N0 only through the EDGAR names on its ticker job, a weak
    pick. NU@2008 either takes it directly through the switch, or -- with no
    switch link at all -- follows ES@2012's weak pick onto the same composite
    anyway (guard (c)'s "held sibling follows the chain" rule): nothing here
    contradicts it. Only stripped of every same-issuer, same-class weak pick to
    follow (no ES@2012 in the run at all) does NU@2008 stay on the placeholder."""
    res = _resolve(eras, ftd, NU_ES)
    assert _placed(res) == {"NU@2008-01-16": ("BBG000BQ87N0", "handoff"),
                            "ES@2012-06-29": ("BBG000BQ87N0", "ticker"),
                            "ES@2015-06-30": ("BBG000BQ87N0", "cusip")}
    assert res["NU@2008-01-16"].cusips == ("664397106",)

    without_link = _resolve(eras, ftd, NU_ES, handoffs=[])
    assert _placed(without_link) == {"NU@2008-01-16": ("BBG000BQ87N0", "handoff"),
                                     "ES@2012-06-29": ("BBG000BQ87N0", "ticker"),
                                     "ES@2015-06-30": ("BBG000BQ87N0", "cusip")}

    without_es2012 = _resolve(eras, ftd, ["NU@2008-01-16", "ES@2015-06-30"], handoffs=[])
    assert _placed(without_es2012) == {"NU@2008-01-16": ("CIK72741-COMMON", "placeholder"),
                                       "ES@2015-06-30": ("BBG000BQ87N0", "cusip")}

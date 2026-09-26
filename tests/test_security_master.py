import csv
from datetime import date
from pathlib import Path

import pytest

from delist_detection.figi_resolution import FigiCandidate
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.observations import Observation, ObservationIndex, load_observations, split_eras
from delist_detection.security_master import (
    AddedAcquirer, AddedSuccessor, EraResolution, FigiResolver, Issuer, Range, Security, Sighting, build_securities,
    era_cusips, era_last_seen, issuers_by_era, ranges_from_sightings, refine_eras,
)

ERAS_FIX = Path(__file__).parent / "fixtures" / "eras"


def _era(ticker, *obs):
    return split_eras([Observation(ticker, d, n) for d, n in obs])[0]


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


def _fixture_ftd_rows():
    with (ERAS_FIX / "ftd_rows.csv").open(newline="") as fh:
        return [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"],
                       float(r["price"]) if r["price"] not in ("", "None") else None)
                for r in csv.DictReader(fh)]


@pytest.fixture(scope="module")
def real_ftd():
    obs = load_observations(ERAS_FIX / "observations.csv")
    return FtdIndex.load(_RowsClient(_fixture_ftd_rows()), date(2004, 1, 1), date(2026, 9, 1),
                         symbols={o.ticker for o in obs})


@pytest.fixture(scope="module")
def real_eras(real_ftd):
    """Real observations (index snapshots 2008-01-16 .. 2009-06-08, then every six
    months 2012-06-29 .. 2026-06-30) and thinned real SEC fails-to-deliver rows for
    tickers that two different securities used, refined into eras."""
    index = ObservationIndex(load_observations(ERAS_FIX / "observations.csv"))
    out: dict[str, list] = {}
    for e in refine_eras(index.eras(), real_ftd):
        out.setdefault(e.ticker, []).append(e)
    return out


@pytest.mark.parametrize("ticker, spans", [
    ("DELL", [("2008-01-16", "2013-06-28"), ("2018-12-31", "2026-06-30")]),   # Dell Inc. LBO; Dell Technologies C
    ("DOW", [("2008-01-16", "2017-06-30"), ("2019-06-30", "2026-06-30")]),    # Dow Chemical; Dow Inc
    ("JEF", [("2008-01-16", "2012-12-31"), ("2018-06-30", "2026-06-30")]),    # Jefferies Group; Jefferies Financial
    ("ADT", [("2012-12-31", "2015-12-31"), ("2018-06-30", "2026-06-30")]),    # ADT Corp; ADT Inc
    ("FOX", [("2015-06-30", "2018-12-31"), ("2019-06-30", "2026-06-30")]),    # 21st Century Fox B; Fox Corp B
    ("FOXA", [("2013-12-31", "2018-12-31"), ("2019-06-30", "2026-06-30")]),   # 21st Century Fox A; Fox Corp A
    ("GOOG", [("2008-01-16", "2009-06-08"), ("2014-06-30", "2015-06-30"),     # Google A; Google C; Alphabet C
              ("2015-12-31", "2026-06-30")]),
    ("UA", [("2014-12-31", "2016-06-30"), ("2016-12-30", "2025-12-31")]),     # Under Armour A; then C
    ("Z", [("2014-06-30", "2014-12-31"), ("2015-06-30", "2015-06-30"),        # Zillow Inc A; Zillow Group A; C
           ("2015-12-31", "2026-06-30")]),
    # Continuing securities: FTD rows bridge the 2009-06-08 -> 2012-06-29 snapshot gap
    ("MON", [("2008-01-16", "2017-12-31")]),
    ("BF-B", [("2008-01-16", "2016-12-30")]),          # FTD writes it "BFB": those rows bridge the gap too
])
def test_refine_eras_splits_securities_that_shared_a_ticker(real_eras, ticker, spans):
    assert [(e.first, e.last) for e in real_eras[ticker]] == spans


def test_real_cb_and_agn_keep_every_observation_under_unique_keys(real_eras):
    """CB is both ACE LTD and CHUBB CORP on five dates (2012-06-29 .. 2014-06-30),
    AGN both ALLERGAN INC and ALLERGAN PLC on 2014-06-30: a snapshot source
    backfilled today's ticker. No era, and so no observation, may be lost."""
    obs = [o for o in load_observations(ERAS_FIX / "observations.csv") if o.ticker in ("CB", "AGN")]
    eras = real_eras["CB"] + real_eras["AGN"]
    assert sorted((o.ticker, o.as_of, o.name) for e in eras for o in e.observations) == \
        sorted((o.ticker, o.as_of, o.name) for o in obs)
    keys = [e.key for e in real_eras["CB"]]
    assert len(set(keys)) == len(keys)
    assert keys[:3] == ["CB@2008-01-16", "CB@2012-06-29", "CB@2012-06-29#1"]
    assert keys[-1] == "CB@2016-06-30"                  # a suffix only where a key would collide
    all_keys = [e.key for v in real_eras.values() for e in v]
    assert len(set(all_keys)) == len(all_keys)


def test_a_backfilled_name_does_not_take_the_tickers_fails_cusip(real_eras):
    """CB's fails rows in 2012-2014 are Chubb Corp's (CHUBB CORPORATION,
    171232101); ACE traded as ACE then. The ACE LTD eras sharing those dates
    must not take that CUSIP, so they resolve on their own (by name) instead of
    as Chubb Corp; the CHUBB CORP eras keep it."""
    for e in real_eras["CB"]:
        if e.name == "ACE LTD":
            assert e.ftd_cusips == (), e.key
        elif e.name == "CHUBB CORP" and e.ftd_cusips:
            assert e.ftd_cusips == ("171232101",), e.key
    assert real_eras["CB"][-1].ftd_cusips == ("H1467J104",)          # Chubb Ltd (formerly ACE) from 2016


def test_refine_eras_splits_at_the_cusip_switch(real_eras):
    # FOXA: 21st Century Fox 90130A101 to 2019-01-23, Fox Corp 35137L105 from 2019-03-21
    # (Fox Corp began regular-way trading on 2019-03-19; its first fails row is 03-21)
    assert [e.ftd_cusips for e in real_eras["FOXA"]] == [("90130A101",), ("35137L105",)]
    assert [e.ftd_cusips for e in real_eras["FOX"]] == [("90130A200",), ("35137L204",)]
    # GOOG: class A 38259P508 until the 2014-04-03 class C distribution, then 38259P706,
    # then Alphabet's 02079K107 (a name change that also splits the observations)
    assert [e.ftd_cusips for e in real_eras["GOOG"]] == [("38259P508",), ("38259P706",), ("02079K107",)]
    assert [e.ftd_cusips for e in real_eras["UA"]] == [("904311107",), ("904311206",)]
    assert [e.ftd_cusips for e in real_eras["DELL"]] == [("24702R101",), ("24703L202",)]


def test_refine_eras_keeps_observations_on_their_side_of_the_split(real_eras, real_ftd):
    foxa_old, foxa_new = real_eras["FOXA"]
    assert {o.name for o in foxa_old.observations} == {"TWENTY FIRST CENTURY FOX INC CLASS"}
    assert {o.name for o in foxa_new.observations} == {"FOX CORP CLASS A"}
    assert foxa_old.key != foxa_new.key
    # "FOX CORP CL A" agrees with "TWENTY FIRST CENTURY FOX" on the one word FOX:
    # the old era's CUSIPs and last sighting must stay on 21st Century Fox's rows
    assert era_cusips(foxa_old, real_ftd) == ["90130A101"]
    assert era_last_seen(foxa_old, real_ftd) == "2019-01-23"
    assert era_cusips(foxa_new, real_ftd) == ["35137L105"]


def test_every_real_era_keeps_its_own_ftd_cusips(real_eras, real_ftd):
    """Spec D21's description check must not cost
    a real security its CUSIP: DELL, DOW, JEF, ADT, FOX/FOXA, GOOG, UA, Z, MON,
    BF-B and CB's Chubb eras all keep every FTD CUSIP their rows describe."""
    for eras in real_eras.values():
        for e in eras:
            if e.ftd_cusips:
                assert era_cusips(e, real_ftd) == list(e.ftd_cusips), e.key


def test_a_stale_era_takes_no_cusip_whose_rows_name_another_company():
    """Station Casinos went private in 2007; snapshots still list it under STN in
    2008-2009, when STN's fails rows are Stantec's. Its EDGAR names don't cover
    Stantec either, so the era takes no FTD CUSIP; an era whose EDGAR names do
    cover the description (a later name backfilled: TAPESTRY on Coach's COH rows)
    keeps it."""
    stn = _era("STN", ("2008-01-16", "STATION CASINOS INC"), ("2008-05-31", "STATION CASINOS INC"),
               ("2009-06-08", "STATION CASINOS INC"))
    ftd = FtdIndex(_rows("STN", "85472N109", ["2008-02-22", "2008-06-02", "2008-09-02", "2009-06-01"],
                         "STANTEC INC. COM"))
    (stn,) = refine_eras([stn], ftd)
    assert stn.ftd_cusips == ("85472N109",)                       # the ticker's rows ...
    assert era_cusips(stn, ftd, ["STATION CASINOS INC"]) == []    # ... are not the era's
    coh = _era("COH", ("2012-06-29", "TAPESTRY INC"), ("2012-12-31", "TAPESTRY INC"))
    ftd = FtdIndex(_rows("COH", "189754104", ["2012-06-01", "2012-09-04", "2012-12-03"], "COACH INC."))
    (coh,) = refine_eras([coh], ftd)
    assert era_cusips(coh, ftd) == []
    assert era_cusips(coh, ftd, ["TAPESTRY, INC.", "COACH INC"]) == ["189754104"]


def _rows(symbol, cusip, dates, desc="X CO"):
    return [FtdRow(d, cusip, symbol, desc, 10.0) for d in dates]


def test_refine_eras_ignores_short_cusip_runs_and_obs_less_sides():
    era = _era("X", ("2020-01-15", "X CO"), ("2020-06-30", "X CO"), ("2020-12-31", "X CO"))
    rows = (_rows("X", "AAA", ["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01"])
            + _rows("X", "NOISE", ["2020-04-15", "2020-04-16", "2020-05-15"])   # 3 rows, but no run of 3: noise
            + _rows("X", "AAA", ["2020-05-01", "2020-06-01", "2020-07-01"])
            + _rows("X", "BBB", ["2020-09-01", "2020-10-01", "2020-11-02", "2021-01-04"])
            + _rows("X", "CCC", ["2021-03-01", "2021-04-01", "2021-05-03"]))  # no observation after: not created
    (a, b) = refine_eras([era], FtdIndex(rows))
    assert [(a.first, a.last), (b.first, b.last)] == [("2020-01-15", "2020-06-30"), ("2020-12-31", "2020-12-31")]
    assert a.ftd_cusips == ("AAA",) and b.ftd_cusips == ("BBB",)


def test_another_security_under_the_bare_symbol_does_not_split_a_class_tickers_era():
    """Brown-Forman B is observed as BF-B; FTD writes it BFB. Rows of an unrelated
    security trading as "BFB" in between must stay out of BF-B's rows, or they
    read as a CUSIP switch and cut the era."""
    obs = [Observation("BF-B", d, "BROWN FORMAN CORP CLASS B") for d in ("2015-06-30", "2016-06-30")]
    rows = (_rows("BFB", "115637209", ["2015-06-01", "2015-09-01", "2015-12-01"], "BROWN-FORMAN CORP CL-B")
            + _rows("BFB", "999999999", ["2016-01-04", "2016-02-01", "2016-03-01", "2016-04-01"], "BIG FAKE BANCORP")
            + _rows("BFB", "115637209", ["2016-05-02", "2016-06-01", "2016-07-01"], "BROWN-FORMAN CORP CL-B"))
    client = _RowsClient(rows)
    guarded = FtdIndex.load(client, date(2015, 1, 1), date(2016, 12, 31), symbols={"BF-B"},
                            names={"BF-B": ["BROWN FORMAN CORP CLASS B"]})
    assert [(e.first, e.last, e.ftd_cusips) for e in refine_eras(split_eras(obs), guarded)] == [
        ("2015-06-30", "2016-06-30", ("115637209",))]
    unguarded = FtdIndex.load(client, date(2015, 1, 1), date(2016, 12, 31), symbols={"BF-B"})
    assert len(refine_eras(split_eras(obs), unguarded)) == 2


def test_refine_eras_splits_on_a_gap_that_no_ftd_row_bridges():
    era = _era("X", ("2009-06-08", "X CO"), ("2012-06-29", "X CO"), ("2012-12-31", "X CO"))
    bridged = _rows("X", "AAA", ["2009-06-01", "2010-03-01", "2011-01-03", "2011-11-01", "2012-07-02"])
    assert len(refine_eras([era], FtdIndex(bridged))) == 1
    unbridged = _rows("X", "AAA", ["2009-06-01", "2009-06-02", "2009-06-03", "2012-07-02"])
    parts = refine_eras([era], FtdIndex(unbridged))
    assert [(e.first, e.last) for e in parts] == [("2009-06-08", "2009-06-08"), ("2012-06-29", "2012-12-31")]
    # a row of another CUSIP (a run of three) does not bridge the era's own gap
    other = unbridged + _rows("X", "ZZZ", ["2010-06-01", "2010-06-02", "2010-06-03"])
    assert [(e.first, e.last) for e in refine_eras([era], FtdIndex(other))] == \
        [("2009-06-08", "2009-06-08"), ("2012-06-29", "2012-12-31")]


def test_refine_eras_gives_each_observation_era_only_its_own_rows():
    # MON: Monsanto, then (name change) Monument Circle; Monument's rows never
    # split or feed Monsanto's era
    mon, circle = split_eras([Observation("MON", "2017-06-30", "MONSANTO CO"),
                              Observation("MON", "2017-12-29", "MONSANTO CO"),
                              Observation("MON", "2021-12-31", "MONUMENT CIRCLE ACQUISITION CORP")])
    rows = (_rows("MON", "61166W101", ["2017-06-01", "2017-09-01", "2018-01-02", "2018-06-15"], "MONSANTO COMPANY")
            + _rows("MON", "61531M101", ["2021-03-18", "2021-09-01", "2022-01-03"], "MONUMENT CIRCLE ACQ"))
    eras = refine_eras([mon, circle], FtdIndex(rows))
    assert [(e.first, e.last, e.ftd_cusips) for e in eras] == [
        ("2017-06-30", "2017-12-29", ("61166W101",)), ("2021-12-31", "2021-12-31", ("61531M101",))]
    ftd = FtdIndex(rows)
    assert era_last_seen(eras[0], ftd) == "2018-06-15"
    assert era_cusips(eras[0], ftd) == ["61166W101"]


def _row(comp, exch, ticker, name, st="Common Stock"):
    return {"figi": comp if exch == "US" else comp + exch, "compositeFIGI": comp, "exchCode": exch,
            "ticker": ticker, "name": name, "securityType": st, "securityType2": "Common Stock"}


class _Figi:
    def __init__(self, answers, filters=None):
        self.answers, self.filters, self.jobs, self.filter_calls = answers, filters or {}, [], []

    def map(self, jobs, use_cache=True):
        self.jobs += jobs
        return [self.answers.get((j["idType"], j["idValue"]), {"warning": "No identifier found."}) for j in jobs]

    def filter(self, query, **fields):
        self.filter_calls.append(query)
        return self.filters.get(query, [])


def test_era_cusips_prefers_matching_description():
    era = _era("AET", ("2018-06-29", "AETNA INC"))
    ftd = FtdIndex([
        FtdRow("2018-06-28", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
        FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0),
        FtdRow("2018-06-29", "999999999", "AET", "SOMETHING ELSE ETF", 10.0),
    ])
    assert era_cusips(era, ftd) == ["00817Y108"]


def test_era_last_seen_extends_past_the_last_snapshot():
    era = _era("AET", ("2018-06-29", "AETNA INC"))
    ftd = FtdIndex([
        FtdRow("2018-11-29", "00817Y108", "AET", "AETNA INC.(NEW)", 212.7),
        FtdRow("2021-01-04", "11111111X", "AET", "SOME ETF TRUST", 20.0),       # a later holder, past the horizon
        FtdRow("2019-03-01", "22222222X", "AET", "UNRELATED CORP", 5.0),       # name does not agree
    ])
    assert era_last_seen(era, ftd) == "2018-11-29"
    assert era_last_seen(_era("ZZZ", ("2018-06-29", "Z CO")), ftd) == "2018-06-29"


def test_resolve_many_orders_routes():
    aet = _era("AET", ("2018-06-29", "AETNA INC"))
    qcor = _era("QCOR", ("2014-06-30", "QUESTCOR PHARMACEUTICALS INC"))
    goog = _era("GOOG", ("2020-06-30", "ALPHABET INC CLASS C"))
    fb = _era("FB", ("2021-06-30", "FACEBOOK INC CLASS A"))
    figi = _Figi({
        ("ID_CUSIP", "00817Y108"): {"data": [_row("BBG000FJLFX8", "US", "AET", "AETNA INC")]},
        ("ID_CUSIP", "74835Y101"): {"data": [_row("BBG000BPVCR1", "US", "QCOR", "MALLINCKRODT ARD LLC")]},
        ("TICKER", "GOOG"): {"data": [_row("BBG009S3NB30", "US", "GOOG", "ALPHABET INC-CL C")]},
        ("TICKER", "FB"): {"data": [_row("BBG01VRMNFB1", "US", "FB", "PROSHARES S&P DYNAMIC BUFFER ETP", "ETP")]},
    })
    res = FigiResolver(figi).resolve_many(
        [aet, qcor, goog, fb],
        issuers=issuers_by_era({aet.key: 1122304, qcor.key: 1034842, goog.key: 1652044, fb.key: 1326801}),
        cusips={aet.key: ["00817Y108"], qcor.key: ["74835Y101"], goog.key: [], fb.key: []},
    )
    assert res[aet.key] == EraResolution(aet.key, "BBG000FJLFX8", "cusip", res[aet.key].candidate, (),
                                         ("00817Y108",))
    assert res[qcor.key].sec_id == "BBG000BPVCR1" and res[qcor.key].source == "cusip"
    assert res[goog.key].sec_id == "BBG009S3NB30" and res[goog.key].source == "ticker"
    assert res[fb.key].sec_id == "CIK1326801-CLASS-A" and res[fb.key].flags == ("no_figi",)
    assert figi.filter_calls == ["FACEBOOK CLASS A"]          # only the unresolved era searched by name


def test_resolve_many_reports_every_cusip_of_the_era_that_maps_to_its_figi():
    # A reverse split: the observation carries the new CUSIP, FTD rows the old one;
    # both map to the same composite, a third maps to another security.
    era = split_eras([Observation("RS", "2020-06-30", "REVERSE SPLIT CO", cusip="11111A200")])[0]
    figi = _Figi({
        ("ID_CUSIP", "11111A200"): {"data": [_row("BBGRSPLIT01", "US", "RS", "REVERSE SPLIT CO")]},
        ("ID_CUSIP", "11111A101"): {"data": [_row("BBGRSPLIT01", "US", "RS", "REVERSE SPLIT CO")]},
        ("ID_CUSIP", "99999Z999"): {"data": [_row("BBGOTHER001", "US", "OTH", "OTHER CO")]},
    })
    res = FigiResolver(figi).resolve_many([era], issuers=issuers_by_era({era.key: 1}),
                                          cusips={era.key: ["11111A200", "11111A101", "99999Z999"]})
    assert res[era.key].sec_id == "BBGRSPLIT01" and res[era.key].cusips == ("11111A200", "11111A101")
    assert len(figi.jobs) == 4                    # the 3 CUSIP jobs + the ticker job: no extra OpenFIGI call


def test_a_ticker_resolved_era_keeps_its_ftd_cusip_unless_openfigi_maps_it_elsewhere():
    """An era resolved by ticker keeps its own FTD CUSIP when OpenFIGI simply
    has no record of it ("No identifier found": old CUSIPs often aren't in
    OpenFIGI), and drops it only when OpenFIGI maps it to another composite."""
    from dataclasses import replace
    quiet = replace(_era("QQ", ("2016-06-30", "QUIET CO")), ftd_cusips=("12345A101",))
    moved = replace(_era("MM", ("2016-06-30", "MOVED CO")), ftd_cusips=("67890B202",))
    figi = _Figi({
        ("TICKER", "QQ"): {"data": [_row("BBGQUIET001", "US", "QQ", "QUIET CO")]},
        ("TICKER", "MM"): {"data": [_row("BBGMOVED001", "US", "MM", "MOVED CO")]},
        # two other lines, neither carrying MM: not accepted, but it does map elsewhere
        ("ID_CUSIP", "67890B202"): {"data": [_row("BBGELSEWHR1", "US", "XX", "ELSEWHERE INC"),
                                             _row("BBGELSEWHR2", "US", "YY", "ELSEWHERE INC")]},
    })
    res = FigiResolver(figi).resolve_many([quiet, moved], issuers=issuers_by_era({quiet.key: 1, moved.key: 2}),
                                          cusips={quiet.key: ["12345A101"], moved.key: ["67890B202"]})
    assert (res[quiet.key].source, res[quiet.key].cusips) == ("ticker", ("12345A101",))
    assert (res[moved.key].source, res[moved.key].cusips) == ("ticker", ())
    # a CUSIP the era did not get from its own FTD rows still needs OpenFIGI's confirmation
    obs_only = split_eras([Observation("QQ", "2016-06-30", "QUIET CO", cusip="24680C303")])[0]
    res2 = FigiResolver(figi).resolve_many([obs_only], issuers=issuers_by_era({obs_only.key: 1}),
                                           cusips={obs_only.key: ["24680C303"]})
    assert res2[obs_only.key].cusips == ()


def test_resolve_many_keeps_the_first_cusip_when_nothing_can_verify_it():
    pinned = split_eras([Observation("X", "2020-01-02", "X CORP", sec_id="BBG000PIN001")])[0]
    placeholder = _era("Y", ("2020-01-02", "Y CORP"))
    res = FigiResolver(_Figi({})).resolve_many(
        [pinned, placeholder], issuers=issuers_by_era({pinned.key: None, placeholder.key: 5}),
        cusips={pinned.key: ["PINCUSIP1", "PINCUSIP2"], placeholder.key: ["YCUSIP001"]})
    assert res[pinned.key].cusips == ("PINCUSIP1",)
    assert res[placeholder.key].sec_id == "CIK5-COMMON" and res[placeholder.key].cusips == ("YCUSIP001",)


def test_pin_and_unresolved():
    pinned = split_eras([Observation("X", "2020-01-02", "X CORP", sec_id="BBG000PIN001")])[0]
    orphan = _era("Y", ("2020-01-02", "Y CORP"))
    res = FigiResolver(_Figi({})).resolve_many([pinned, orphan],
                                               issuers=issuers_by_era({pinned.key: None, orphan.key: None}),
                                               cusips={pinned.key: [], orphan.key: []})
    assert res[pinned.key].sec_id == "BBG000PIN001" and res[pinned.key].source == "pin"
    assert res[orphan.key].sec_id is None and res[orphan.key].flags == ("observation_unresolved",)


def test_the_ticker_route_accepts_on_the_issuers_edgar_names_but_never_on_an_acquirers_name():
    """Spec §8.3: a ticker hit's name must agree with the observation or EDGAR
    name. Northeast Utilities, seen under ES before its 2015 rename, is accepted
    onto Bloomberg's EVERSOURCE ENERGY line because EDGAR lists both names for
    CIK 72741. Questcor's dead QCOR line, which Bloomberg renamed to its
    acquirer, stays rejected: the acquirer's name is not one of Questcor's."""
    nu = _era("ES", ("2012-06-29", "NORTHEAST UTILITIES"), ("2014-06-30", "NORTHEAST UTILITIES"))
    qcor = _era("QCOR", ("2014-06-30", "QUESTCOR PHARMACEUTICALS INC"))
    figi = _Figi({
        ("TICKER", "ES"): {"data": [_row("BBG000BQ87N0", "US", "ES", "EVERSOURCE ENERGY")]},
        ("TICKER", "QCOR"): {"data": [_row("BBG000BPVCR1", "US", "QCOR", "MALLINCKRODT ARD LLC")]},
    })
    ciks, cusips = {nu.key: 72741, qcor.key: 1034842}, {nu.key: [], qcor.key: []}
    names = {72741: ("EVERSOURCE ENERGY", "NORTHEAST UTILITIES", "NORTHEAST UTILITIES SYSTEM"),
             1034842: ("QUESTCOR PHARMACEUTICALS INC",)}
    alone = FigiResolver(figi).resolve_many([nu], issuers=issuers_by_era(ciks), cusips=cusips)
    assert alone[nu.key].sec_id == "CIK72741-COMMON"
    res = FigiResolver(figi).resolve_many([nu, qcor], issuers=issuers_by_era(ciks, names), cusips=cusips)
    assert (res[nu.key].sec_id, res[nu.key].source) == ("BBG000BQ87N0", "ticker")
    assert (res[qcor.key].sec_id, res[qcor.key].flags) == ("CIK1034842-COMMON", ("no_figi",))


def test_edgar_names_do_not_hand_an_era_a_figi_another_issuers_cusip_confirms():
    """Real case: General Growth Properties (CIK 895648) went bankrupt in 2009 and
    a new issuer (CIK 1496048) took the business and the GGP ticker in 2010. The
    old issuer's EDGAR name is now "GGP, Inc. (fka General Growth Properties ...)",
    which agrees with Bloomberg's GGP INC line; but CUSIP 36174X101 confirms that
    line as the new issuer's, so the old era keeps its placeholder."""
    old = _era("GGP", ("2008-01-16", "GENERAL GROWTH PPTYS INC"), ("2009-06-08", "GENERAL GROWTH PPTYS INC"))
    new = _era("GGP", ("2017-06-30", "GGP INC"), ("2018-06-30", "GGP INC"))
    ggp = {"data": [_row("BBG000BG3HG3", "US", "GGP", "GGP INC", "REIT")]}
    figi = _Figi({("ID_CUSIP", "36174X101"): ggp, ("TICKER", "GGP"): ggp})
    names = {895648: ("GGP, Inc. (fka General Growth Properties Inc. & predecessor to General Growth "
                      "Properties, Inc.)", "GENERAL GROWTH PROPERTIES INC"),
             1496048: ("Brookfield Property REIT Inc.", "GGP Inc.", "General Growth Properties, Inc.",
                       "New GGP, Inc.")}
    res = FigiResolver(figi).resolve_many([old, new],
                                          issuers=issuers_by_era({old.key: 895648, new.key: 1496048}, names),
                                          cusips={old.key: ["370021107"], new.key: ["36174X101"]})
    assert (res[new.key].sec_id, res[new.key].source) == ("BBG000BG3HG3", "cusip")
    assert res[old.key].sec_id == "CIK895648-COMMON"


def test_edgar_names_do_not_move_an_era_off_the_line_its_issuers_cusip_confirms_for_those_dates():
    """Real case: the snapshots list Jacobs Engineering under J in 2012-2014 as well
    as under JEC, its ticker then. OpenFIGI's J answer is today's JACOBS SOLUTIONS
    INC line (CUSIP 46982L108, since the 2022 holding-company reorganization),
    which agrees with an EDGAR name of CIK 52988; but over those dates the JEC era
    of the same issuer and class is confirmed on BBG000BMFFQ0 by CUSIP 469814107,
    so the J era does not take the later line. Wyndham, also backfilled (WYND for
    2012-2014), is taken: its ticker hit is the line WYN's CUSIP confirms."""
    jec = _era("JEC", ("2008-01-16", "JACOBS ENGINEERING GROUP INC"), ("2019-06-30", "JACOBS ENGINEERING GROUP INC"))
    j12 = _era("J", ("2012-06-29", "JACOBS ENGINEERING GROUP INC"), ("2014-06-30", "JACOBS ENGINEERING GROUP INC"))
    j22 = _era("J", ("2022-12-31", "JACOBS SOLUTIONS INC"), ("2026-06-30", "JACOBS SOLUTIONS INC"))
    wyn = _era("WYN", ("2008-01-16", "WYNDHAM WORLDWIDE CORP"), ("2017-12-31", "WYNDHAM WORLDWIDE CORP"))
    wynd = _era("WYND", ("2012-06-29", "TRAVEL LEISURE INC"), ("2014-06-30", "TRAVEL LEISURE INC"))
    solutions = {"data": [_row("BBG019C1BQR4", "US", "J", "JACOBS SOLUTIONS INC")]}
    wyndham = {"data": [_row("BBG000PV2L86", "US", "WYND", "WYNDHAM DESTINATIONS INC")]}
    figi = _Figi({
        ("ID_CUSIP", "469814107"): {"data": [_row("BBG000BMFFQ0", "US", "9990213D", "JACOBS ENGINEERING GROUP INC")]},
        ("ID_CUSIP", "46982L108"): solutions, ("TICKER", "J"): solutions,
        ("ID_CUSIP", "98310W108"): wyndham, ("TICKER", "WYND"): wyndham,
    })
    eras = [jec, j12, j22, wyn, wynd]
    ciks = {jec.key: 52988, j12.key: 52988, j22.key: 52988, wyn.key: 1361658, wynd.key: 1361658}
    cusips = {jec.key: ["469814107"], j12.key: [], j22.key: ["46982L108"], wyn.key: ["98310W108"], wynd.key: []}
    names = {52988: ("JACOBS SOLUTIONS INC.", "JACOBS ENGINEERING GROUP INC /DE/"),
             1361658: ("Travel & Leisure Co.", "Wyndham Destinations, Inc.", "WYNDHAM WORLDWIDE CORP")}
    res = FigiResolver(figi).resolve_many(eras, issuers=issuers_by_era(ciks, names), cusips=cusips)
    assert {k: r.sec_id for k, r in res.items()} == {
        jec.key: "BBG000BMFFQ0", j12.key: "CIK52988-COMMON", j22.key: "BBG019C1BQR4",
        wyn.key: "BBG000PV2L86", wynd.key: "BBG000PV2L86"}


def test_edgar_names_do_not_split_an_issuers_placeholder():
    """Real case: the snapshots list ACE Ltd under ACE from 2008 and, backfilled,
    under CB in 2012-2014. CB's ticker hit is Bloomberg's CHUBB LTD line, which
    ACE's EDGAR names accept; but the ACE era itself finds no FIGI (OpenFIGI knows
    neither its old CUSIP nor its old ticker) and stays on the issuer placeholder.
    Taking only the CB era off it would put one stock on two sec_ids on the same
    dates (and end the placeholder in a rename row), so the CB era stays with it.
    Wisconsin Energy's two eras both reach WEC ENERGY GROUP only through EDGAR's
    names, so both go, and no era is left on the placeholder."""
    ace = _era("ACE", ("2008-07-25", "ACE LTD"), ("2015-12-31", "ACE LTD"))
    cb = _era("CB", ("2012-06-29", "ACE LTD"), ("2014-06-30", "ACE LTD"))
    wec08 = _era("WEC", ("2008-01-16", "WISCONSIN ENERGY CORP"), ("2009-06-08", "WISCONSIN ENERGY CORP"))
    wec14 = _era("WEC", ("2014-12-31", "WISCONSIN ENERGY CORP"))
    wec = {"data": [_row("BBG000BWP7D9", "US", "WEC", "WEC ENERGY GROUP INC")]}
    figi = _Figi({("TICKER", "CB"): {"data": [_row("BBG000BR14K5", "US", "CB", "CHUBB LTD")]},
                  ("TICKER", "WEC"): wec})
    eras = [ace, cb, wec08, wec14]
    res = FigiResolver(figi).resolve_many(
        eras, issuers=issuers_by_era({ace.key: 896159, cb.key: 896159, wec08.key: 783325, wec14.key: 783325},
                                     {896159: ("Chubb Ltd", "ACE LTD", "ACE Ltd"),
                                      783325: ("WEC ENERGY GROUP, INC.", "WISCONSIN ENERGY CORP")}),
        cusips={ace.key: ["H0023R105"], cb.key: [], wec08.key: ["976657106"], wec14.key: ["976657106"]})
    assert {k: r.sec_id for k, r in res.items()} == {ace.key: "CIK896159-COMMON", cb.key: "CIK896159-COMMON",
                                                    wec08.key: "BBG000BWP7D9", wec14.key: "BBG000BWP7D9"}


def test_the_same_issuer_guard_weighs_only_the_same_class_over_overlapping_dates():
    """The guard above is about one share class at one time: an issuer's class A
    line confirmed over the same dates says nothing about its class C era, and a
    line it had years before says nothing about a later era."""
    a = _era("AAA", ("2012-06-29", "ALPHA CO CLASS A"), ("2014-06-30", "ALPHA CO CLASS A"))
    c = _era("AAC", ("2012-06-29", "BETA HOLDINGS CLASS C"), ("2014-06-30", "BETA HOLDINGS CLASS C"))
    old = _era("GMA", ("2008-01-16", "GAMMA CORP"), ("2010-06-30", "GAMMA CORP"))
    new = _era("GMB", ("2014-06-30", "DELTA INC"), ("2016-06-30", "DELTA INC"))
    figi = _Figi({
        ("ID_CUSIP", "11111A101"): {"data": [_row("BBGCLASSA01", "US", "AAA", "ALPHA CO-CL A")]},
        ("TICKER", "AAC"): {"data": [_row("BBGCLASSC01", "US", "AAC", "ALPHA CO-CL C")]},
        ("ID_CUSIP", "22222B101"): {"data": [_row("BBGOLDLINE1", "US", "GMA", "GAMMA CORP")]},
        ("TICKER", "GMB"): {"data": [_row("BBGNEWLINE1", "US", "GMB", "GAMMA CORP")]},
    })
    res = FigiResolver(figi).resolve_many(
        [a, c, old, new], issuers=issuers_by_era({a.key: 1, c.key: 1, old.key: 2, new.key: 2},
                                                 {1: ("ALPHA CO", "BETA HOLDINGS"), 2: ("GAMMA CORP", "DELTA INC")}),
        cusips={a.key: ["11111A101"], c.key: [], old.key: ["22222B101"], new.key: []})
    assert {k: r.sec_id for k, r in res.items()} == {a.key: "BBGCLASSA01", c.key: "BBGCLASSC01",
                                                    old.key: "BBGOLDLINE1", new.key: "BBGNEWLINE1"}


def test_build_securities_merges_eras_of_one_figi():
    fb = _era("FB", ("2021-12-31", "FACEBOOK INC CLASS A"))
    meta = _era("META", ("2022-06-30", "META PLATFORMS INC CLASS A"))
    from delist_detection.figi_resolution import FigiCandidate
    cand = FigiCandidate("BBG000MM2P62", "META PLATFORMS INC-CLASS A", "META", "Common Stock", ())
    secs = build_securities(
        {fb.key: EraResolution(fb.key, "BBG000MM2P62", "cusip", cand, ()),
         meta.key: EraResolution(meta.key, "BBG000MM2P62", "ticker", cand, ())},
        {fb.key: fb, meta.key: meta}, {fb.key: 1326801, meta.key: 1326801})
    s = secs["BBG000MM2P62"]
    assert [e.ticker for e in s.eras] == ["FB", "META"]
    assert s.share_class == "CLASS A" and s.issuer_cik == 1326801 and s.kind == "common" and s.observed
    assert s.row() == {"sec_id": "BBG000MM2P62", "issuer_cik": 1326801, "share_class": "CLASS A",
                       "name": "META PLATFORMS INC CLASS A", "security_type": "Common Stock",
                       "observed": True, "figi_source": "cusip"}


def test_monsanto_gap_eras_still_form_one_security():
    """MONSANTO CO seen 2016-06-30 and 2017-12-29 (547 days) with no FTD row in
    between: the gap splits the era, but both halves resolve to Monsanto's FIGI
    and build_securities merges them back into one security."""
    obs = [Observation("MON", "2016-06-30", "MONSANTO CO"), Observation("MON", "2017-12-29", "MONSANTO CO"),
           Observation("MON", "2021-12-31", "MONUMENT CIRCLE ACQUISITION CORP")]
    eras = refine_eras(split_eras(obs), FtdIndex())
    assert [(e.first, e.last) for e in eras] == [("2016-06-30", "2016-06-30"), ("2017-12-29", "2017-12-29"),
                                                 ("2021-12-31", "2021-12-31")]
    mon = FigiCandidate("BBG000BGSB57", "MONSANTO CO", "MON", "Common Stock", ())
    res = {eras[0].key: EraResolution(eras[0].key, "BBG000BGSB57", "cusip", mon, ()),
           eras[1].key: EraResolution(eras[1].key, "BBG000BGSB57", "cusip", mon, ()),
           eras[2].key: EraResolution(eras[2].key, None, "unresolved", None, ("observation_unresolved",))}
    secs = build_securities(res, {e.key: e for e in eras}, {e.key: 1110783 for e in eras[:2]})
    assert list(secs) == ["BBG000BGSB57"]
    assert [(e.first, e.last) for e in secs["BBG000BGSB57"].eras] == [("2016-06-30", "2016-06-30"),
                                                                     ("2017-12-29", "2017-12-29")]


def test_ranges_from_sightings():
    s = [("2021-12-31", "FB", "observation"), ("2022-06-08", "FB", "ftd"), ("2022-06-09", "META", "ftd"),
         ("2022-06-10", "META", "ftd"), ("2022-06-30", "META", "observation"), ("2022-07-01", "MVRS", "ftd")]
    assert ranges_from_sightings(s, end=None, open_ended=True) == [
        Range("FB", "2021-12-31", "2022-06-08", "observation"),
        Range("META", "2022-06-09", None, "observation"),
    ]
    assert ranges_from_sightings(s, end="2022-12-30", open_ended=False)[-1] == \
        Range("META", "2022-06-09", "2022-12-30", "observation")
    assert ranges_from_sightings([("2020-01-02", "X", "ftd"), ("2020-01-03", "X", "ftd")], end=None,
                                 open_ended=False) == [Range("X", "2020-01-02", "2020-01-03", "ftd")]
    assert ranges_from_sightings([], end=None, open_ended=True) == []


def test_ranges_from_sightings_takes_one_ticker_per_day_and_never_inverts():
    # The review's reproduction: GOOG and GOOGL both sighted on 2014-12-31 for one
    # security gave Range('GOOG', valid_from='2014-12-31', valid_to='2014-12-30').
    s = [("2014-06-30", "GOOGL", "observation"), ("2014-12-31", "GOOG", "observation"),
         ("2014-12-31", "GOOGL", "observation"), ("2015-06-30", "GOOGL", "observation")]
    got = ranges_from_sightings(s, end=None, open_ended=True)
    assert all(r.valid_to is None or r.valid_to >= r.valid_from for r in got)
    assert got == [Range("GOOGL", "2014-06-30", None, "observation")]      # the running ticker keeps the day
    # an observation beats an FTD row on the same day
    s2 = [("2020-01-02", "X", "ftd"), ("2020-01-03", "X", "ftd"), ("2020-01-03", "Y", "observation"),
          ("2020-01-06", "Y", "ftd"), ("2020-01-07", "Y", "ftd")]
    assert ranges_from_sightings(s2, end=None, open_ended=False) == [
        Range("X", "2020-01-02", "2020-01-02", "ftd"), Range("Y", "2020-01-03", "2020-01-07", "observation")]
    # then the canonical spelling: the observed one, else the one with a separator
    s3 = [("2020-01-02", "BFB", "ftd"), ("2020-01-02", "BF-B", "ftd"), ("2020-01-03", "BFB", "ftd"),
          ("2020-01-03", "BF-B", "ftd")]
    assert ranges_from_sightings(s3, end=None, open_ended=False) == [Range("BF-B", "2020-01-02", "2020-01-03", "ftd")]
    # a sighting after `end` never starts a range that would end before it begins
    s4 = [("2020-01-02", "X", "observation"), ("2020-02-03", "Y", "observation")]
    assert ranges_from_sightings(s4, end="2020-01-15", open_ended=False) == [
        Range("X", "2020-01-02", "2020-01-15", "observation")]


def test_issuers_by_era_names_each_known_issuer_and_skips_the_unknown():
    issuers = issuers_by_era({"A": 1, "B": None, "C": 2, "D": 1}, {1: ["ALPHA CO", "OLD ALPHA"]})
    assert issuers == {"A": Issuer(1, ("ALPHA CO", "OLD ALPHA")), "C": Issuer(2, ()),
                       "D": Issuer(1, ("ALPHA CO", "OLD ALPHA"))}


def test_an_added_acquirers_row_spans_its_fails_rows_or_its_fallback_day():
    from datetime import date

    from delist_detection.ftd import FtdRow
    sec = Security("BBGACQ00001", 7, "COMMON", "ACQ CORP", "Common Stock", False, "cusip")
    acq = AddedAcquirer(sec, "ACQ", date(2018, 11, 28))
    assert acq.span() == ("2018-11-28", "2018-11-28")
    acq.rows += [FtdRow("2019-03-05", "C1", "ACQ", "ACQ CORP", 1.0), FtdRow("2018-11-20", "C1", "ACQ", "ACQ CORP", 1.0)]
    assert acq.history_row(listed=False, exchange=None) == {
        "sec_id": "BBGACQ00001", "ticker": "ACQ", "exchange": None, "valid_from": "2018-11-20",
        "valid_to": "2019-03-05", "source": "ftd"}
    assert acq.history_row(listed=True, exchange="NYSE")["valid_to"] is None


def test_an_added_successors_row_starts_on_its_filing_date():
    sec = Security("BBG009S39JX6", 1652044, "CLASS A", "ALPHABET INC-CL A", "Common Stock", False, "ticker")
    succ = AddedSuccessor(sec, "GOOGL", "2015-10-05")
    assert succ.history_row(listed=False, exchange=None) == {
        "sec_id": "BBG009S39JX6", "ticker": "GOOGL", "exchange": None, "valid_from": "2015-10-05",
        "valid_to": "2015-10-05", "source": "edgar_8k"}


def test_ranges_from_sightings_takes_named_sightings():
    got = ranges_from_sightings([Sighting("2020-01-02", "AAA", "observation"),
                                 Sighting("2020-06-30", "AAB", "observation")], end=None, open_ended=True)
    assert [(r.value, r.valid_from, r.valid_to) for r in got] == [("AAA", "2020-01-02", "2020-06-29"),
                                                                 ("AAB", "2020-06-30", None)]

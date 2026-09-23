import csv
from datetime import date
from pathlib import Path

import pytest

from delist_detection.figi_resolution import FigiCandidate
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.observations import Observation, ObservationIndex, load_observations, split_eras
from delist_detection.security_master import (
    EraResolution, FigiResolver, Range, build_securities, era_cusips, era_last_seen, ranges_from_sightings,
    refine_eras,
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
        ciks={aet.key: 1122304, qcor.key: 1034842, goog.key: 1652044, fb.key: 1326801},
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
    res = FigiResolver(figi).resolve_many([era], ciks={era.key: 1},
                                          cusips={era.key: ["11111A200", "11111A101", "99999Z999"]})
    assert res[era.key].sec_id == "BBGRSPLIT01" and res[era.key].cusips == ("11111A200", "11111A101")
    assert len(figi.jobs) == 4                    # the 3 CUSIP jobs + the ticker job: no extra OpenFIGI call


def test_resolve_many_keeps_the_first_cusip_when_nothing_can_verify_it():
    pinned = split_eras([Observation("X", "2020-01-02", "X CORP", sec_id="BBG000PIN001")])[0]
    placeholder = _era("Y", ("2020-01-02", "Y CORP"))
    res = FigiResolver(_Figi({})).resolve_many(
        [pinned, placeholder], ciks={pinned.key: None, placeholder.key: 5},
        cusips={pinned.key: ["PINCUSIP1", "PINCUSIP2"], placeholder.key: ["YCUSIP001"]})
    assert res[pinned.key].cusips == ("PINCUSIP1",)
    assert res[placeholder.key].sec_id == "CIK5-COMMON" and res[placeholder.key].cusips == ("YCUSIP001",)


def test_pin_and_unresolved():
    pinned = split_eras([Observation("X", "2020-01-02", "X CORP", sec_id="BBG000PIN001")])[0]
    orphan = _era("Y", ("2020-01-02", "Y CORP"))
    res = FigiResolver(_Figi({})).resolve_many([pinned, orphan], ciks={pinned.key: None, orphan.key: None},
                                               cusips={pinned.key: [], orphan.key: []})
    assert res[pinned.key].sec_id == "BBG000PIN001" and res[pinned.key].source == "pin"
    assert res[orphan.key].sec_id is None and res[orphan.key].flags == ("observation_unresolved",)


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

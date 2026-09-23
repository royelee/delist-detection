from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.observations import Observation, split_eras
from delist_detection.security_master import (
    EraResolution, FigiResolver, Range, build_securities, era_cusips, era_last_seen, ranges_from_sightings,
)


def _era(ticker, *obs):
    return split_eras([Observation(ticker, d, n) for d, n in obs])[0]


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
    assert res[aet.key] == EraResolution(aet.key, "BBG000FJLFX8", "cusip", res[aet.key].candidate, ())
    assert res[qcor.key].sec_id == "BBG000BPVCR1" and res[qcor.key].source == "cusip"
    assert res[goog.key].sec_id == "BBG009S3NB30" and res[goog.key].source == "ticker"
    assert res[fb.key].sec_id == "CIK1326801-CLASS-A" and res[fb.key].flags == ("no_figi",)
    assert figi.filter_calls == ["FACEBOOK CLASS A"]          # only the unresolved era searched by name


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

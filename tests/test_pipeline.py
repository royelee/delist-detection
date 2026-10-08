import csv
import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

import delist_detection.pipeline as pipeline
from delist_detection.endings.classifier import DelistClassifier
from delist_detection.outputs.reconstruction import DelistRecord
from delist_detection.vocabulary.crsp_codes import CrspBucket
from delist_detection.endings.delistings import Delisting, DelistingFinder
from delist_detection.sources.edgar import EdgarBlocked, EdgarSubmission
from delist_detection.sources.ftd import FtdRow
from delist_detection.endings.last_trade import LastTrade
from delist_detection.terms.llm_merger_extractor import MergerTerms
from delist_detection.identity.observations import Observation, ObservationIndex
from delist_detection.terms.payout_extractor import PayoutResult
from delist_detection.terms.acquirers import acquirer_cik
from delist_detection.pipeline import Clients, Overrides, run
from delist_detection.outputs.review_triage import merge_review_rows
from delist_detection.identity.history import ticker_range_review
from delist_detection.endings.successors import (SecurityStart, successor_from_8k12b, successor_in_run,
                                                 successor_search_name)
from delist_detection.outputs.review_triage import Decision
from delist_detection.identity.security_master import Security
from delist_detection.measurement import scorecard as run_scorecard
from delist_detection.outputs.run_snapshot import RunSnapshot
from delist_detection.measurement.scorecard import ScorecardConfig, Window
from delist_detection.measurement.truth import TruthCase
from delist_detection.outputs.store import formatted, read_table, table_path
from delist_detection.outputs.verdict import decide as decide_verdicts
from delist_detection.identity.ticker_resolver import TickerResolution, TickerResolver

FIX = Path(__file__).parent / "fixtures" / "form25"
AET_RAW = (FIX / "aet_25nse.txt").read_text(encoding="utf-8", errors="replace")

AET_FIGI = {"data": [{"figi": "BBG000FJLFX8", "compositeFIGI": "BBG000FJLFX8", "exchCode": "US", "ticker": "AET",
                      "name": "AETNA INC", "securityType": "Common Stock", "securityType2": "Common Stock"}]}
LIVE_FIGI = {"data": [{"figi": "BBG000LIVE01", "compositeFIGI": "BBG000LIVE01", "exchCode": "US", "ticker": "LIVE",
                       "name": "LIVE CO", "securityType": "Common Stock", "securityType2": "Common Stock"},
                      {"figi": "BBG000LIVE02", "compositeFIGI": "BBG000LIVE01", "exchCode": "UN", "ticker": "LIVE",
                       "name": "LIVE CO", "securityType": "Common Stock", "securityType2": "Common Stock"}]}


class _Figi:
    def __init__(self):
        self.answers = {("ID_CUSIP", "00817Y108"): AET_FIGI, ("TICKER", "LIVE"): LIVE_FIGI,
                        ("COMPOSITE_ID_BB_GLOBAL", "BBG000LIVE01"): LIVE_FIGI}

    def map(self, jobs, use_cache=True):
        return [self.answers.get((j["idType"], j["idValue"]), {"warning": "No identifier found."}) for j in jobs]

    def filter(self, query, **fields):
        return []


class _FtdClient:
    ROWS = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0),
            FtdRow("2018-11-29", "00817Y108", "AET", "AETNA INC.(NEW)", 212.70)]

    def urls_for(self, lo, hi):
        return ["mem"]

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self.ROWS:
            if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                yield r


def _clients(fake_edgar, ftd_rows=None, extra_obs=()):
    fake_edgar.submissions_by_cik[1122304] = [
        EdgarSubmission("0000876661-18-001269", "25-NSE", "2018-11-29", "", "", "primary_doc.xml"),
        EdgarSubmission("0001122304-18-000178", "8-K", "2018-11-28", "2018-11-28", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("0001122304-18-000184", "15-12B", "2018-12-10", "", "", "f.htm"),
    ]
    fake_edgar.submissions_by_cik[777] = []
    fake_edgar.company_map["AET"] = {"cik_str": 1122304, "ticker": "AET", "title": "AETNA INC /PA/"}
    fake_edgar.company_map["LIVE"] = {"cik_str": 777, "ticker": "LIVE", "title": "LIVE CO"}
    fake_edgar.listings[777] = [("LIVE", "NYSE")]
    fake_edgar.raws["0000876661-18-001269"] = AET_RAW
    fake_edgar.texts["0001122304-18-000178"] = ("Item 3.01 Notice. trading suspended prior to the opening of trading "
                                                "on November 29, 2018 " + "x" * 300)
    ftd = _FtdClient()
    if ftd_rows is not None:
        ftd.ROWS = ftd_rows
    obs = [Observation("AET", "2017-06-30", "AETNA INC", cik=1122304),
           Observation("AET", "2018-06-29", "AETNA INC", cik=1122304),
           Observation("LIVE", "2025-06-30", "LIVE CO", cik=777), *extra_obs]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, observed_names=index.name_on, cik_pins=index.cik_pin_on)
    return index, Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                          figi=_Figi(), ftd_client=ftd)


def test_end_to_end_tables(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    secs = {r["sec_id"]: r for r in read_table("securities", table_path(tmp_path, "securities"))}
    assert set(secs) == {"BBG000FJLFX8", "BBG000LIVE01"}
    assert secs["BBG000FJLFX8"]["figi_source"] == "cusip" and secs["BBG000LIVE01"]["figi_source"] == "ticker"
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert (d["sec_id"], d["delist_date"], d["bucket"]) == ("BBG000FJLFX8", "2018-12-09", "merger")
    assert d["last_trade_date"] == "2018-11-28" and d["last_trade_close"] == "212.700000"
    assert d["exchange"] == "NYSE"
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    aet = [r for r in th if r["sec_id"] == "BBG000FJLFX8"]
    assert aet == [{"sec_id": "BBG000FJLFX8", "ticker": "AET", "exchange": "NYSE", "valid_from": "2017-06-30",
                    "valid_to": "2018-11-28", "source": "observation"}]
    live = [r for r in th if r["sec_id"] == "BBG000LIVE01"]
    assert live[0]["valid_to"] == ""                                  # listed today: open range
    ch = read_table("cusip_history", table_path(tmp_path, "cusip_history"))
    assert [(r["cusip"], r["valid_from"], r["valid_to"]) for r in ch] == [("00817Y108", "2018-06-29", "2018-11-28")]
    assert summary.counts["delistings"] == 1 and summary.buckets == {"merger": 1}
    om = {(r["ticker"], r["as_of"]): r for r in read_table("observation_map", table_path(tmp_path, "observation_map"))}
    assert summary.counts["observation_map"] == 3 and len(om) == 3          # one row per distinct observation
    assert om[("AET", "2017-06-30")]["sec_id"] == "BBG000FJLFX8"
    assert om[("AET", "2017-06-30")]["status"] == "mapped"
    assert om[("AET", "2017-06-30")]["history_ticker"] == "AET"
    assert om[("AET", "2017-06-30")]["in_ticker_history"] == "true"
    assert om[("LIVE", "2025-06-30")]["sec_id"] == "BBG000LIVE01"
    assert om[("LIVE", "2025-06-30")]["status"] == "mapped"
    assert om[("LIVE", "2025-06-30")]["history_ticker"] == "LIVE"
    assert om[("LIVE", "2025-06-30")]["in_ticker_history"] == "true"


def test_observation_map_under_limit_only_covers_the_runs_own_eras(fake_edgar, tmp_path):
    """--limit trims which eras run at all (stage 1); observation_map.csv only
    ever gets rows for those, and the log says how many of the input's
    observations that is."""
    index, clients = _clients(fake_edgar)
    logged = []
    run(index, clients, Overrides(), out_dir=tmp_path, log=logged.append, limit=1)
    om = read_table("observation_map", table_path(tmp_path, "observation_map"))
    assert len(om) == 2 and {r["ticker"] for r in om} == {"AET"}             # AET's era only (LIVE's is dropped)
    assert any("2 of 3 observations mapped" in line for line in logged)


def test_a_ticker_seen_under_two_names_on_one_date_is_a_conflict_in_the_map(fake_edgar, tmp_path):
    """CB on 2012-06-29 as both ACE LTD and CHUBB CORP (a snapshot backfilled
    today's ticker): observations.split_eras gives them two eras, and both
    rows in observation_map.csv carry `conflict`."""
    fake_edgar.submissions_by_cik[9001] = []
    obs = [Observation("CB", "2012-06-29", "ACE LTD", cik=9001, sec_id="BBGCB0000001"),
           Observation("CB", "2012-06-29", "CHUBB CORP", cik=9001, sec_id="BBGCB0000001")]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, observed_names=index.name_on, cik_pins=index.cik_pin_on)
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=_Figi(), ftd_client=_FtdClient())

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    om = read_table("observation_map", table_path(tmp_path, "observation_map"))
    statuses = {r["name"]: r["status"] for r in om}
    assert statuses == {"ACE LTD": "conflict", "CHUBB CORP": "conflict"}
    assert {r["sec_id"] for r in om} == {"BBGCB0000001"}


def test_bf_b_spelling_joins_through_history_ticker_for_an_observed_bfb(fake_edgar, tmp_path):
    """A security observed once as BF-B and once (a different snapshot's
    spelling) as BFB: ticker_sightings's canonical label is the dashed
    spelling (BF-B), so ticker_history carries one BF-B row and the BFB
    observation's history_ticker joins on that spelling."""
    fake_edgar.submissions_by_cik[8001] = []
    obs = [Observation("BF-B", "2020-01-02", "BROWN-FORMAN CORP", cik=8001, sec_id="BBGBFB0001"),
           Observation("BFB", "2020-06-30", "BROWN-FORMAN CORP", cik=8001, sec_id="BBGBFB0001")]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, observed_names=index.name_on, cik_pins=index.cik_pin_on)
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=_Figi(), ftd_client=_FtdClient())

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    th = [r for r in read_table("ticker_history", table_path(tmp_path, "ticker_history"))
         if r["sec_id"] == "BBGBFB0001"]
    assert [r["ticker"] for r in th] == ["BF-B"]
    om = {r["as_of"]: r for r in read_table("observation_map", table_path(tmp_path, "observation_map"))}
    assert om["2020-06-30"]["history_ticker"] == "BF-B"
    assert om["2020-06-30"]["in_ticker_history"] == "true"
    assert om["2020-01-02"]["history_ticker"] == "BF-B"


def test_a_backfilled_observation_adds_no_ticker_history_range(fake_edgar, tmp_path):
    """ACE Limited renamed itself Chubb Limited in 2016 and took CB, the ticker
    the old Chubb Corp traded under until then; a join that projects today's
    CB back onto the one continuous security's 2012 rows (while its CUSIP's
    fails still show it trading as ACE then) is a backfilled observation:
    observation_map.csv marks it backfilled_ticker, and it opens no CB range
    in ticker_history before CB is actually confirmed -- the real ACE range
    from the fails evidence is untouched."""
    fake_edgar.submissions_by_cik[8002] = []
    obs = [Observation("CB", "2012-06-29", "ACE LTD", cusip="CUSIP0001", cik=8002, sec_id="BBGCHUBB01"),
           Observation("CB", "2016-01-04", "CHUBB LTD", cusip="CUSIP0001", cik=8002, sec_id="BBGCHUBB01")]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, observed_names=index.name_on, cik_pins=index.cik_pin_on)
    ftd_client = _FtdClient()
    ftd_client.ROWS = [FtdRow("2012-06-28", "CUSIP0001", "ACE", "ACE LTD", 80.0),
                       FtdRow("2012-07-02", "CUSIP0001", "ACE", "ACE LTD", 81.0),
                       FtdRow("2016-01-04", "CUSIP0001", "CB", "CHUBB LTD", 120.0),
                       FtdRow("2016-01-05", "CUSIP0001", "CB", "CHUBB LTD", 121.0)]
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=_Figi(), ftd_client=ftd_client)

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    om = {r["as_of"]: r for r in read_table("observation_map", table_path(tmp_path, "observation_map"))}
    assert om["2012-06-29"]["status"] == "backfilled_ticker"
    assert om["2016-01-04"]["status"] == "mapped"
    th = [r for r in read_table("ticker_history", table_path(tmp_path, "ticker_history"))
         if r["sec_id"] == "BBGCHUBB01"]
    # no CB range opened before CB is actually confirmed by its own fails rows
    assert not any(r["ticker"] == "CB" and r["valid_from"] < "2016-01-04" for r in th)
    assert any(r["ticker"] == "ACE" for r in th)          # the real 2012 evidence is untouched


class _WindowedFtdClient:
    """An FTD double that answers only rows inside the window asked for."""

    def __init__(self, rows):
        self.all_rows = rows

    def urls_for(self, lo, hi):
        return [(lo.isoformat(), hi.isoformat())]

    def rows(self, url, *, symbols=None, cusips=None):
        lo, hi = url
        for r in self.all_rows:
            if lo <= r.date <= hi and ((symbols and r.symbol in symbols) or (cusips and r.cusip in cusips)):
                yield r


def _dead_before_sighting_universe(fake_edgar, observed):
    fake_edgar.submissions_by_cik[1122304] = [
        EdgarSubmission("0000876661-18-001269", "25-NSE", "2018-11-29", "", "", "primary_doc.xml"),
        EdgarSubmission("0001122304-18-000178", "8-K", "2018-11-28", "2018-11-28", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("0001122304-18-000184", "15-12B", "2018-12-10", "", "", "f.htm"),
    ]
    fake_edgar.submissions_by_cik[777] = []
    fake_edgar.company_map["AET"] = {"cik_str": 1122304, "ticker": "AET", "title": "AETNA INC /PA/"}
    fake_edgar.company_map["LIVE"] = {"cik_str": 777, "ticker": "LIVE", "title": "LIVE CO"}
    fake_edgar.listings[777] = [("LIVE", "NYSE")]
    fake_edgar.raws["0000876661-18-001269"] = AET_RAW
    fake_edgar.texts["0001122304-18-000178"] = ("Item 3.01 Notice. trading suspended prior to the opening of trading "
                                                "on November 29, 2018 " + "x" * 300)
    rows = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC COM", 180.0),
            FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC COM", 181.0),
            FtdRow("2018-11-28", "00817Y108", "AET", "AETNA INC COM", 212.70)]
    obs = [*(Observation("AET", d, "AETNA INC", cik=1122304) for d in observed),
           Observation("LIVE", "2025-06-30", "LIVE CO", cik=777)]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, observed_names=index.name_on, cik_pins=index.cik_pin_on)
    return index, Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                          figi=_Figi(), ftd_client=_WindowedFtdClient(rows))


def test_a_security_dead_before_its_first_sighting_takes_its_cusips_from_earlier_fails_rows(fake_edgar, tmp_path):
    index, clients = _dead_before_sighting_universe(fake_edgar, ["2019-06-28"])
    logged = []
    run(index, clients, Overrides(), out_dir=tmp_path, log=logged.append)
    assert any("dead before first sighting: 1" in str(m) for m in logged)
    th = [r for r in read_table("ticker_history", table_path(tmp_path, "ticker_history"))
          if r["ticker"] == "AET"]
    assert th and th[0]["valid_to"] == "2018-11-28" and th[0]["valid_from"].startswith("2018")
    ch = read_table("cusip_history", table_path(tmp_path, "cusip_history"))
    assert "00817Y108" in {r["cusip"] for r in ch}


def test_a_security_observed_before_its_ending_is_not_dead_before_its_first_sighting(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    logged = []
    run(index, clients, Overrides(), out_dir=tmp_path, log=logged.append)
    assert any("dead before first sighting: 0" in str(m) for m in logged)


class _RecordingFtdClient(_WindowedFtdClient):
    def __init__(self, rows):
        super().__init__(rows)
        self.asked = []

    def rows(self, url, *, symbols=None, cusips=None):
        self.asked.append((set(symbols or ()), set(cusips or ())))
        yield from super().rows(url, symbols=symbols, cusips=cusips)


def _stage_5b(rows, specs, endings, sec_cusips=None, loaded=()):
    """Run stage 5b directly. specs: sid -> (ticker, first observation day);
    endings: (sid, last trade day, successor sid or None); loaded: rows already in the index."""
    from types import SimpleNamespace
    from delist_detection.sources.ftd import FtdIndex
    from delist_detection.outputs.manifest import StageMeter
    from delist_detection.identity.observations import TickerEra
    securities = {}
    for sid, (ticker, first) in specs.items():
        era = TickerEra(ticker, first, first, [Observation(ticker, first, "AETNA INC")])
        securities[sid] = Security(sid, 1, "", "AETNA INC", "Common Stock", True, "ticker", eras=[era])
    delistings = [SimpleNamespace(sec_id=sid, delist_date=day, last_trade=SimpleNamespace(day=date.fromisoformat(day)),
                                  anchor=date.fromisoformat(day), record=SimpleNamespace(successor_sec_id=succ))
                  for sid, day, succ in endings]
    client = _RecordingFtdClient(rows)
    ctx = SimpleNamespace(log=lambda *_: None, meter=StageMeter(lambda *_: None))
    ftd = FtdIndex(loaded, source=client)          # the index reads the fails files; the stage only asks it
    held = {sid: list((sec_cusips or {}).get(sid, [])) for sid in specs}
    sightings = {sid: [] for sid in specs}
    before = {sid: list(v) for sid, v in held.items()}
    back = pipeline._dead_before_sighting(ctx, securities, delistings, held, ftd, {})
    assert held == before                          # the stage returns its CUSIPs and sightings; `_run` merges them
    return back.fixed, {**held, **back.cusips}, {**sightings, **back.sightings}, securities, client, ctx


def _aet_rows(ticker="AET", cusip="00817Y108"):
    return [FtdRow("2018-11-20", cusip, ticker, "AETNA INC COM", 180.0),
            FtdRow("2018-11-27", cusip, ticker, "AETNA INC COM", 181.0)]


def test_stage_5b_reads_the_last_real_ending_not_the_first():
    # ended 2018-11-28, seen from 2019-06-28, ended again 2020-03-02: not dead before its sighting
    fixed, held, sightings, *_ = _stage_5b(
        _aet_rows(), {"S1": ("AET", "2019-06-28")},
        [("S1", "2018-11-28", None), ("S1", "2020-03-02", None)])
    assert fixed == [] and held["S1"] == [] and sightings["S1"] == []


def test_stage_5b_decides_eligibility_before_loading_any_rows():
    # both die before they are seen and share a ticker; SB already holds CUSIP_B, whose rows SA's load brings in
    rows = _aet_rows(cusip="CUSIP_A") + [FtdRow("2018-11-26", "CUSIP_B", "AET", "AETNA INC COM", 182.0)]
    fixed, held, *_ = _stage_5b(
        rows, {"SA": ("AET", "2019-06-28"), "SB": ("AET", "2019-06-29")},
        [("SA", "2018-11-28", None), ("SB", "2018-11-28", None)], sec_cusips={"SB": ["CUSIP_B"]})
    assert sorted(fixed) == ["SA", "SB"]
    assert held["SA"] == ["CUSIP_A"] and held["SB"] == ["CUSIP_B"]


def test_stage_5b_drops_a_cusip_another_security_holds():
    fixed, held, *_ = _stage_5b(
        _aet_rows(), {"S1": ("AET", "2019-06-28"), "S2": ("ZZZ", "2019-06-28")},
        [("S1", "2018-11-28", None)], sec_cusips={"S2": ["00817Y108"]})
    assert fixed == [] and held["S1"] == [] and held["S2"] == ["00817Y108"]


def test_stage_5b_keeps_identity_and_is_metered():
    fixed, held, sightings, securities, _, ctx = _stage_5b(
        _aet_rows(), {"S1": ("AET", "2019-06-28")}, [("S1", "2018-11-28", None)])
    assert fixed == ["S1"] and held["S1"] == ["00817Y108"]
    assert securities["S1"].sec_id == "S1" and securities["S1"].issuer_cik == 1
    assert "dead before first sighting" in ctx.meter.stages


def test_stage_5b_skips_a_security_whose_cusip_already_trades_and_asks_for_no_rows():
    live = [FtdRow("2019-07-01", "00817Y108", "AET", "AETNA INC COM", 190.0)]
    fixed, held, _, _, client, _ = _stage_5b(
        _aet_rows(), {"S1": ("AET", "2019-06-28")}, [("S1", "2018-11-28", None)],
        sec_cusips={"S1": ["00817Y108"]}, loaded=live)
    assert fixed == [] and client.asked == [] and held["S1"] == ["00817Y108"]


def test_missing_close_leaves_blank_dlret_and_review(fake_edgar, tmp_path):
    rows = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0)]    # nothing after the last trade
    index, clients = _clients(fake_edgar, ftd_rows=rows)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["last_trade_close"] == "" and d["dlret"] == ""
    assert "no_last_close" in d["review_flags"]
    review = read_table("review", table_path(tmp_path, "review"))
    assert any(r["sec_id"] == "BBG000FJLFX8" and "no_last_close" in r["review_flags"] and r["severity"] == "fix"
               for r in review)


def test_review_csv_hides_info_only_rows_that_the_run_summary_still_counts(fake_edgar, tmp_path):
    """A delisting whose only flag is `ftd_close_prior:1` (info) and that has a
    DLRET leaves review.csv; the flag stays on delistings.csv, review_summary.csv
    counts it, and the run summary (which feeds the manifest and exit code 3)
    still counts every flag."""
    rows = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0),
            FtdRow("2018-11-28", "00817Y108", "AET", "AETNA INC.(NEW)", 210.10)]
    index, clients = _clients(fake_edgar, ftd_rows=rows)
    overrides = Overrides(merger_terms={("BBG000FJLFX8", "2018-12-09"): {"cash_per_share": 210.10}})
    summary = run(index, clients, overrides, out_dir=tmp_path, log=lambda *_: None)
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["review_flags"] == "ftd_close_prior:1" and d["dlret"] == "0.000000"
    review = read_table("review", table_path(tmp_path, "review"))
    assert [(r["severity"], r["sec_id"], r["review_flags"]) for r in review] == [
        ("check", "BBG000LIVE01", "ticker_unconfirmed")]
    summ = {r["flag"]: r for r in read_table("review_summary", table_path(tmp_path, "review_summary"))}
    assert [summ["ftd_close_prior"][c] for c in ("severity", "rows", "in_review", "accepted", "examples")] == [
        "info", "1", "0", "0", "AET@2018-12-09"]
    assert summary.review_flags == {"ftd_close_prior": 1, "ticker_unconfirmed": 1}
    assert summary.counts["review"] == 1 and summary.counts["review_summary"] == 2


def test_close_looks_back_when_no_row_follows_the_last_trade(fake_edgar, tmp_path):
    """The fails rows end on the last trade day itself (2018-11-28, carrying the
    close of 11-27): the close comes from that row and is flagged with its age
    in trading days, ftd_close_prior:1, instead of no close at all; the
    evidence keeps the row's date."""
    rows = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0),
            FtdRow("2018-11-26", "00817Y108", "AET", "AETNA INC.(NEW)", 205.36),
            FtdRow("2018-11-28", "00817Y108", "AET", "AETNA INC.(NEW)", 210.10)]
    index, clients = _clients(fake_edgar, ftd_rows=rows)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["last_trade_date"] == "2018-11-28" and d["last_trade_close"] == "210.100000"
    assert "ftd_close_prior:1" in d["review_flags"].split(";") and "no_last_close" not in d["review_flags"]


def test_unmatched_override_stops_before_writing(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    with pytest.raises(ValueError, match="BBG999"):
        run(index, clients, Overrides(last_trade_closes={"BBG999": 1.0}), out_dir=tmp_path, log=lambda *_: None)
    assert not list(tmp_path.glob("*.csv"))


def test_an_override_row_that_matches_no_delisting_names_its_file_and_line(fake_edgar, tmp_path):
    """A loaded override file remembers where each row came from, so the refusal
    names the flag, the file and the line of every row that matches nothing."""
    from delist_detection.outputs.reconstruction import OverrideFileError, load_float_overrides

    lt = tmp_path / "lt.csv"
    lt.write_text("sec_id,delist_date,last_trade_close\nBBG000FJLFX8,2018-12-09,212.7\nBBG999,,1\n"
                  "BBG000FJLFX8,2020-01-01,5\n")
    out = tmp_path / "out"
    index, clients = _clients(fake_edgar)
    overrides = Overrides(last_trade_closes=load_float_overrides(lt, "last_trade_close"))
    with pytest.raises(OverrideFileError) as exc:
        run(index, clients, overrides, out_dir=out, log=lambda *_: None)
    msg = str(exc.value)
    assert "\n" not in msg
    assert f"--last-trade-closes {lt} line 3: BBG999" in msg
    assert f"--last-trade-closes {lt} line 4: BBG000FJLFX8 2020-01-01" in msg
    assert "line 2" not in msg
    assert not list(out.glob("*.csv"))


def test_refusal_mid_run_keeps_previous_outputs(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    before = {p.name: p.read_text() for p in tmp_path.glob("*.csv")}

    def blocked(*a, **k):
        raise EdgarBlocked("SEC returned 403")

    clients.edgar.fetch_filing_raw = blocked
    with pytest.raises(EdgarBlocked):
        run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert {p.name: p.read_text() for p in tmp_path.glob("*.csv")} == before


@pytest.mark.parametrize("where", ["listing batch", "one security"])
def test_an_openfigi_outage_stops_the_run_and_keeps_previous_outputs(fake_edgar, tmp_path, where):
    """OpenFIGI unavailable after its retries
    stops the run like a refusal -- no error row, no placeholder in its place
    (that would change sec_ids between runs), nothing written over the
    previous complete outputs -- whether the batched listing ask or one
    security's own ask meets it."""
    from delist_detection.sources.openfigi import OpenFigiUnavailable

    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    before = {p.name: p.read_text() for p in tmp_path.glob("*.csv")}
    real_map = clients.figi.map

    def down(jobs, use_cache=True):
        if not use_cache and where == "one security" and len(jobs) > 1:
            raise RuntimeError("a glitch in the batch: each security asks alone")
        if not use_cache:
            raise OpenFigiUnavailable("OpenFIGI /mapping kept failing after 6 attempts")
        return real_map(jobs, use_cache=use_cache)

    clients.figi.map = down
    with pytest.raises(OpenFigiUnavailable):
        run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert {p.name: p.read_text() for p in tmp_path.glob("*.csv")} == before


# --- successor_from_8k12b resolves the matching-share-class candidate ---

def _alphabet_hit(a_ticker="GOOGL", c_ticker="GOOG", a_name="Alphabet Inc Class A", c_name="Alphabet Inc Class C",
                  edgar_name="Alphabet Inc"):
    return {"_source": {"ciks": ["1652044"],
                        "display_names": [f"{edgar_name}.  ({a_ticker}, {c_ticker})  (CIK 0001652044)"],
                        "file_date": "2015-10-02"}}


class _SuccessorFigi:
    def __init__(self, answers):
        self.answers = answers

    def map(self, jobs, use_cache=True):
        return [self.answers.get(j["idValue"], {"warning": "No identifier found."}) for j in jobs]


def _figi_answer(composite, ticker, name):
    return {"data": [{"figi": composite, "compositeFIGI": composite, "exchCode": "US", "ticker": ticker,
                      "name": name, "securityType": "Common Stock", "securityType2": "Common Stock"}]}


def test_successor_from_8k12b_picks_the_candidate_matching_the_predecessor_class():
    hit = _alphabet_hit()
    figi = _SuccessorFigi({
        "GOOGL": _figi_answer("BBGGOOGL01", "GOOGL", "Alphabet Inc Class A"),
        "GOOG": _figi_answer("BBGGOOG001", "GOOG", "Alphabet Inc Class C"),
    })
    got_c = successor_from_8k12b(lambda *a: [hit], figi, name="GOOGLE INC", day=date(2015, 10, 2),
                                 exclude_cik=1288776, share_class="CLASS C")
    assert got_c[0] == 1652044 and got_c[1].composite == "BBGGOOG001" and got_c[2] == "2015-10-02"

    got_a = successor_from_8k12b(lambda *a: [hit], figi, name="GOOGLE INC", day=date(2015, 10, 2),
                                 exclude_cik=1288776, share_class="CLASS A")
    assert got_a[1].composite == "BBGGOOGL01"


def test_successor_from_8k12b_refuses_a_candidate_whose_name_disagrees():
    hit = _alphabet_hit()
    figi = _SuccessorFigi({
        "GOOGL": _figi_answer("BBGGOOGL01", "GOOGL", "Alphabet Inc Class A"),
        "GOOG": _figi_answer("BBGUNREL01", "GOOG", "Unrelated Fishing Company"),   # name disagrees
    })
    # only GOOGL agrees on name; the predecessor is plain common and exactly one
    # candidate agrees, so it is taken even though its own class label is "CLASS A"
    got = successor_from_8k12b(lambda *a: [hit], figi, name="GOOGLE INC", day=date(2015, 10, 2),
                               exclude_cik=1288776, share_class="COMMON")
    assert got[1].composite == "BBGGOOGL01"

    # neither candidate agrees: nothing resolves
    figi_none = _SuccessorFigi({
        "GOOGL": _figi_answer("BBGX", "GOOGL", "Unrelated Co One"),
        "GOOG": _figi_answer("BBGY", "GOOG", "Unrelated Co Two"),
    })
    assert successor_from_8k12b(lambda *a: [hit], figi_none, name="GOOGLE INC", day=date(2015, 10, 2),
                                exclude_cik=1288776, share_class="COMMON") is None


def test_successor_from_8k12b_returns_none_without_a_figi_client():
    hit = _alphabet_hit()
    assert successor_from_8k12b(lambda *a: [hit], None, name="GOOGLE INC", day=date(2015, 10, 2),
                                exclude_cik=1288776) is None
    assert successor_from_8k12b(lambda *a: [], None, name="X", day=date(2015, 10, 2), exclude_cik=1) is None


# --- the ticker(s) come from the parenthetical right before (CIK ...) ---

class _RecordingFigi:
    """Like _SuccessorFigi, but remembers every idValue it was asked to map."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def map(self, jobs, use_cache=True):
        self.calls += [j["idValue"] for j in jobs]
        return [self.answers.get(j["idValue"], {"warning": "No identifier found."}) for j in jobs]


def test_successor_ticker_skips_a_parenthetical_that_is_part_of_the_company_name():
    # "(Brasil)" is part of the legal name, not a ticker; BSBR is the real one
    hit = {"_source": {"ciks": ["1471119"],
                       "display_names": ["Banco Santander (Brasil) S.A.  (BSBR)  (CIK 0001471119)"],
                       "file_date": "2020-01-01"}}
    figi = _RecordingFigi({"BSBR": _figi_answer("BBGBSBR0001", "BSBR", "Banco Santander (Brasil) S.A.")})
    got = successor_from_8k12b(lambda *a: [hit], figi, name="X", day=date(2020, 1, 1), exclude_cik=1)
    assert figi.calls == ["BSBR"]
    assert got[0] == 1471119 and got[1].composite == "BBGBSBR0001" and got[2] == "2020-01-01"


def test_successor_ticker_requests_every_ticker_before_cik():
    hit = _alphabet_hit()
    figi = _RecordingFigi({
        "GOOGL": _figi_answer("BBGGOOGL01", "GOOGL", "Alphabet Inc"),
        "GOOG": _figi_answer("BBGGOOG001", "GOOG", "Alphabet Inc"),
    })
    successor_from_8k12b(lambda *a: [hit], figi, name="X", day=date(2015, 10, 2), exclude_cik=1)
    assert figi.calls == ["GOOGL", "GOOG"]


def test_successor_with_no_ticker_parenthetical_makes_no_figi_request():
    hit = {"_source": {"ciks": ["1"], "display_names": ["SOME COMPANY  (CIK 0000000001)"],
                       "file_date": "2020-01-01"}}
    figi = _RecordingFigi({})
    got = successor_from_8k12b(lambda *a: [hit], figi, name="X", day=date(2020, 1, 1), exclude_cik=999)
    assert got is None
    assert figi.calls == []


# --- added (acquirer/successor) securities get a real ticker_history row ---

def test_run_writes_an_open_acquirer_ticker_history_row(fake_edgar, tmp_path):
    """A cash+stock merger term resolves an acquirer that is listed today; its
    ticker_history row must be built directly (ranges_from_sightings would
    otherwise silently drop it as a single-value FTD sighting)."""
    index, clients = _clients(fake_edgar)
    fake_edgar.company_map["ACQ"] = {"cik_str": 9999, "ticker": "ACQ", "title": "ACQUIRER INC"}
    fake_edgar.submissions_by_cik[9999] = [EdgarSubmission("X1", "10-K", "2010-01-01", "", "", "x.htm")]
    fake_edgar.listings[9999] = [("ACQ", "NYSE")]
    clients.figi.answers[("ID_CUSIP", "ACQCUSIP1")] = _figi_answer("BBGACQ00001", "ACQ", "ACQUIRER INC")
    clients.figi.answers[("COMPOSITE_ID_BB_GLOBAL", "BBGACQ00001")] = {
        "data": [{"figi": "BBGACQ00001", "compositeFIGI": "BBGACQ00001", "exchCode": "UN", "ticker": "ACQ",
                  "name": "ACQUIRER INC"}]}
    clients.ftd_client.ROWS = clients.ftd_client.ROWS + [
        FtdRow("2018-11-20", "ACQCUSIP1", "ACQ", "ACQUIRER INC", 50.0)]
    overrides = Overrides(merger_terms={("BBG000FJLFX8", "2018-12-09"):
                                        {"stock_ratio": 0.5, "acquirer_price": 100.0, "acquirer_ticker": "ACQ"}})

    run(index, clients, overrides, out_dir=tmp_path, log=lambda *_: None)

    secs = {r["sec_id"]: r for r in read_table("securities", table_path(tmp_path, "securities"))}
    assert secs["BBGACQ00001"]["observed"] == "false"
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    acq_rows = [r for r in th if r["sec_id"] == "BBGACQ00001"]
    assert len(acq_rows) == 1
    assert acq_rows[0]["ticker"] == "ACQ" and acq_rows[0]["source"] == "ftd" and acq_rows[0]["valid_to"] == ""
    assert acq_rows[0]["valid_from"] == "2018-11-20"
    d = read_table("delistings", table_path(tmp_path, "delistings"))[0]
    assert d["acquirer_sec_id"] == "BBGACQ00001"


def test_run_writes_an_open_successor_ticker_history_row(fake_edgar, tmp_path, monkeypatch):
    """An exchange_transfer delisting flagged successor_unknown resolves to a
    successor security via an 8-K12B hit; its ticker_history row's source is
    'edgar_8k' and its valid_from is the 8-K12B's filing date."""
    index, clients = _clients(fake_edgar)

    record = DelistRecord(ticker="AET", cik=1122304, observed_delist_date="2018-11-28", crsp_code=304,
                          bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="high", reason="moved exchanges",
                          evidence={"flags": ["successor_unknown"]}, sec_id="BBG000FJLFX8",
                          delist_date="2018-12-09")
    ev = Delisting(sec_id="BBG000FJLFX8", cik=1122304, ticker="AET", delist_date="2018-12-09", record=record,
                        last_trade=LastTrade(date(2018, 11, 28), "notice_a", ()), form25=None, form25_sub=None,
                        exchange="NYSE")

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return ([ev], []) if ctx.security.sec_id == "BBG000FJLFX8" else ([], [])

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)

    hit = {"_source": {"ciks": ["8888"], "display_names": ["AETNA HOLDINGS INC  (SUX)  (CIK 0000008888)"],
                       "file_date": "2018-12-15"}}
    fake_edgar.full_text_search = lambda q, forms, lo, hi: [hit]
    fake_edgar.listings[8888] = [("SUX", "NYSE")]
    clients.figi.answers[("TICKER", "SUX")] = _figi_answer("BBGSUX00001", "SUX", "AETNA HOLDINGS INC")
    clients.figi.answers[("COMPOSITE_ID_BB_GLOBAL", "BBGSUX00001")] = {
        "data": [{"figi": "BBGSUX00001", "compositeFIGI": "BBGSUX00001", "exchCode": "UN", "ticker": "SUX",
                  "name": "AETNA HOLDINGS INC"}]}

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    suc = [r for r in th if r["sec_id"] == "BBGSUX00001"]
    assert len(suc) == 1
    assert suc[0]["ticker"] == "SUX" and suc[0]["source"] == "edgar_8k"
    assert suc[0]["valid_from"] == "2018-12-15" and suc[0]["valid_to"] == ""
    d = read_table("delistings", table_path(tmp_path, "delistings"))[0]
    assert d["successor_sec_id"] == "BBGSUX00001"


# --- an open ticker_history row's exchange comes from EDGAR's own submissions ---

def test_open_ticker_history_row_gets_its_exchange_from_issuer_submissions(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)

    def _submissions(cik, fresh_after=None):
        if cik == 777:
            return {"tickers": ["LIVE"], "exchanges": ["Nasdaq"], "name": "LIVE CO", "formerNames": [], "sic": ""}
        title = next((r["title"] for r in fake_edgar.company_map.values() if int(r["cik_str"]) == int(cik)), "")
        return {"name": title, "formerNames": [], "sic": ""}

    fake_edgar.submissions = _submissions
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    live = [r for r in th if r["sec_id"] == "BBG000LIVE01"]
    assert live[0]["valid_to"] == "" and live[0]["exchange"] == "NASDAQ"


# --- a per-security failure that isn't EdgarBlocked/OpenFigiBlocked is logged, not fatal ---

def test_finder_error_for_one_security_does_not_abort_the_run(fake_edgar, tmp_path, monkeypatch):
    index, clients = _clients(fake_edgar)
    real = DelistingFinder(clients.edgar, clients.classifier)

    class _FlakyFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            if ctx.security.sec_id == "BBG000LIVE01":
                raise ValueError("boom")
            return real.find(ctx)

    monkeypatch.setattr(pipeline, "DelistingFinder", _FlakyFinder)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["sec_id"] == "BBG000FJLFX8"           # AET's row still made it through
    review = read_table("review", table_path(tmp_path, "review"))
    assert any(r["sec_id"] == "BBG000LIVE01" and r["review_flags"] == "error" and "ValueError" in r["reason"]
              and "boom" in r["reason"] for r in review)


# --- ticker_history overlap review, without changing the ranges ---

def test_ticker_range_review_flags_overlap_within_one_security():
    rows = [
        {"sec_id": "S1", "ticker": "AAA", "valid_from": "2020-01-01", "valid_to": "2020-06-01"},
        {"sec_id": "S1", "ticker": "BBB", "valid_from": "2020-03-01", "valid_to": None},
    ]
    items = ticker_range_review(rows)
    assert len(items) == 1
    assert items[0].flag == "ticker_range_overlap" and items[0].sec_id == "S1"
    assert "AAA" in items[0].reason and "BBB" in items[0].reason


def test_ticker_range_review_flags_a_ticker_shared_by_two_securities():
    rows = [
        {"sec_id": "S1", "ticker": "AAA", "valid_from": "2020-01-01", "valid_to": "2020-06-01"},
        {"sec_id": "S2", "ticker": "AAA", "valid_from": "2020-03-01", "valid_to": None},
    ]
    items = ticker_range_review(rows)
    assert len(items) == 1
    assert items[0].flag == "ticker_shared"
    assert "S1" in items[0].reason and "S2" in items[0].reason


def test_ticker_range_review_ignores_non_overlapping_ranges():
    rows = [
        {"sec_id": "S1", "ticker": "AAA", "valid_from": "2020-01-01", "valid_to": "2020-06-01"},
        {"sec_id": "S1", "ticker": "BBB", "valid_from": "2020-06-02", "valid_to": None},
    ]
    assert ticker_range_review(rows) == []


# --- item 13b: duplicate review rows are merged, joining reasons ---

def test_merge_review_rows_joins_reasons_for_the_same_key():
    rows = [
        {"sec_id": "S1", "delist_date": "2020-01-01", "ticker": "AAA", "review_flags": "error", "reason": "boom",
         "cik": 1},
        {"sec_id": "S1", "delist_date": "2020-01-01", "ticker": "AAA", "review_flags": "error", "reason": "bang",
         "cik": None},
    ]
    merged = merge_review_rows(rows)
    assert len(merged) == 1
    assert merged[0]["reason"] == "boom; bang"
    assert merged[0]["cik"] == 1                    # the first non-empty value is kept


def test_merge_review_rows_leaves_distinct_keys_alone():
    rows = [
        {"sec_id": "S1", "delist_date": "2020-01-01", "ticker": "AAA", "review_flags": "error", "reason": "boom"},
        {"sec_id": "S2", "delist_date": "2020-01-01", "ticker": "BBB", "review_flags": "error", "reason": "bang"},
    ]
    assert merge_review_rows(rows) == rows


# --- item 10 helper, unit-level ---

def test_issuer_exchange_for_ticker_reads_the_parallel_arrays(fake_edgar):
    fake_edgar.company_map["X"] = {"cik_str": 1, "ticker": "X", "title": "X CO"}
    fake_edgar.submissions_by_cik[1] = []
    fake_edgar.submissions = lambda cik, fresh_after=None: (
        {"tickers": ["X"], "exchanges": ["NYSE"]} if cik == 1 else {"tickers": [], "exchanges": []}
    )
    from delist_detection.filings.listing_status import issuer_exchange
    assert issuer_exchange(fake_edgar, 1, "X") == "NYSE"
    assert issuer_exchange(fake_edgar, 1, "Y") is None
    assert issuer_exchange(fake_edgar, None, "X") is None


# --- payouts.csv cites the right accession, at the run() level ---

class _FakePayoutExtractor:
    def __init__(self, result):
        self.result = result

    def extract(self, record, last_close=None):
        return self.result


class _FakeLLMExtractor:
    def __init__(self, terms):
        self.terms = terms

    def extract(self, record, security_name=""):
        return self.terms


def test_payouts_csv_cites_the_llm_accession_for_an_llm_sourced_payout(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    clients.payout_extractor = _FakePayoutExtractor(PayoutResult.none())   # regex finds nothing
    clients.llm_extractor = _FakeLLMExtractor(
        MergerTerms("cash", 212.70, None, "ACQUIRER INC", "ACQ", "high", "8-K:0001-23-456789", "quote"))

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    (row,) = read_table("payouts", table_path(tmp_path, "payouts"))
    assert row["source"] == "llm"
    assert row["accession"] == "0001-23-456789"   # not "8-K:0001-23-456789"


def test_payouts_csv_cites_the_regex_accession_for_a_regex_sourced_payout(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    clients.payout_extractor = _FakePayoutExtractor(
        PayoutResult(212.70, "high", "8K_2.01", "0000123456-18-000001", "quote"))
    clients.llm_extractor = _FakeLLMExtractor(None)   # present, but finds nothing -- regex must still win

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    (row,) = read_table("payouts", table_path(tmp_path, "payouts"))
    assert row["source"] == "8K_2.01"
    assert row["accession"] == "0000123456-18-000001"


# --- gate_payouts' acquirer_price is keyed by the merger, at the run() level ---

def _two_stock_mergers(fake_edgar, monkeypatch):
    """Two merger events sharing a delist_date, both with LLM stock terms naming
    acquirer ACQ (FTD closes 100.0 on 2020-06-02, 150.0 on 2020-06-08); the
    targets' last trade days are 2020-06-01 and 2020-06-05."""
    fake_edgar.company_map["S1"] = {"cik_str": 7001, "ticker": "S1", "title": "TARGET ONE INC"}
    fake_edgar.company_map["S2"] = {"cik_str": 7002, "ticker": "S2", "title": "TARGET TWO INC"}
    fake_edgar.submissions_by_cik[7001] = []
    fake_edgar.submissions_by_cik[7002] = []

    figi = _RecordingFigi({
        "S1": _figi_answer("BBGSEC001", "S1", "TARGET ONE INC"),
        "S2": _figi_answer("BBGSEC002", "S2", "TARGET TWO INC"),
    })

    class _FtdWithAcquirer:
        ROWS = [FtdRow("2020-06-02", "ACQCUSIP", "ACQ", "ACQUIRER CO", 100.0),
                FtdRow("2020-06-08", "ACQCUSIP", "ACQ", "ACQUIRER CO", 150.0)]

        def urls_for(self, lo, hi):
            return ["mem"]

        def rows(self, url, *, symbols=None, cusips=None):
            for r in self.ROWS:
                if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                    yield r

    obs = [Observation("S1", "2020-01-01", "TARGET ONE INC", cik=7001),
           Observation("S1", "2020-06-01", "TARGET ONE INC", cik=7001),
           Observation("S2", "2020-01-01", "TARGET TWO INC", cik=7002),
           Observation("S2", "2020-06-05", "TARGET TWO INC", cik=7002)]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, observed_names=index.name_on, cik_pins=index.cik_pin_on)
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=figi, ftd_client=_FtdWithAcquirer())

    def _merger_record(sec_id, ticker, cik, delist_date):
        return DelistRecord(ticker=ticker, cik=cik, observed_delist_date=delist_date, crsp_code=231,
                            bucket=CrspBucket.MERGER, confidence="high", reason="x", evidence={"flags": []},
                            sec_id=sec_id, delist_date=delist_date)

    ev1 = Delisting(sec_id="BBGSEC001", cik=7001, ticker="S1", delist_date="2020-06-15",
                         record=_merger_record("BBGSEC001", "S1", 7001, "2020-06-15"),
                         last_trade=LastTrade(date(2020, 6, 1), "midas", ()), form25=None, form25_sub=None,
                         exchange="NYSE")
    ev2 = Delisting(sec_id="BBGSEC002", cik=7002, ticker="S2", delist_date="2020-06-15",
                         record=_merger_record("BBGSEC002", "S2", 7002, "2020-06-15"),
                         last_trade=LastTrade(date(2020, 6, 5), "midas", ()), form25=None, form25_sub=None,
                         exchange="NYSE")

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            if ctx.security.sec_id == "BBGSEC001":
                return [ev1], []
            if ctx.security.sec_id == "BBGSEC002":
                return [ev2], []
            return [], []

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)

    terms1 = MergerTerms("stock", None, 1.0, "ACQUIRER CO", "ACQ", "high", "8-K:X1", "")
    terms2 = MergerTerms("stock", None, 1.0, "ACQUIRER CO", "ACQ", "high", "8-K:X2", "")

    class _LLMByKey:
        def __init__(self, mapping):
            self.mapping = mapping

        def extract(self, record, security_name=""):
            return self.mapping.get((record.sec_id, record.delist_date))

    clients.llm_extractor = _LLMByKey({
        ("BBGSEC001", "2020-06-15"): terms1,
        ("BBGSEC002", "2020-06-15"): terms2,
    })
    return index, clients


def test_run_level_acquirer_price_uses_each_mergers_own_last_trade_day(fake_edgar, tmp_path, monkeypatch):
    """Each merger gets the acquirer's close on THEIR OWN last trade day -- not
    whichever day a shared-by-date map happened to hold."""
    index, clients = _two_stock_mergers(fake_edgar, monkeypatch)
    overrides = Overrides(last_trade_closes={"BBGSEC001": 100.0, "BBGSEC002": 150.0})

    run(index, clients, overrides, out_dir=tmp_path, log=lambda *_: None)

    d = {r["sec_id"]: r for r in read_table("delistings", table_path(tmp_path, "delistings"))}
    assert d["BBGSEC001"]["acquirer_price"] == "100.000000"
    assert d["BBGSEC002"]["acquirer_price"] == "150.000000"


def test_an_answered_received_close_is_the_acquirer_price(fake_edgar, tmp_path, monkeypatch):
    from delist_detection.outputs.price_requests import key_of
    index, clients = _two_stock_mergers(fake_edgar, monkeypatch)
    first = tmp_path / "first"
    run(index, clients, Overrides(), out_dir=first, log=lambda *_: None)
    ask = next(r for r in read_table("price_requests", table_path(first, "price_requests"))
               if r["sec_id"] == "BBGSEC001" and r["kind"] == "received_close")
    index, clients = _two_stock_mergers(fake_edgar, monkeypatch)
    second = tmp_path / "second"
    run(index, clients, Overrides(last_trade_closes={"BBGSEC001": 100.0, "BBGSEC002": 150.0},
                                  price_answers={key_of(ask): 105.0}), out_dir=second, log=lambda *_: None)
    d = {r["sec_id"]: r for r in read_table("delistings", table_path(second, "delistings"))}
    assert d["BBGSEC001"]["acquirer_price"] == "105.000000"
    assert d["BBGSEC002"]["acquirer_price"] == "150.000000"


# --- a same-ticker successor does not overlap its predecessor ---

def test_same_ticker_successor_does_not_overlap_its_predecessor(fake_edgar, tmp_path, monkeypatch):
    """A holding-company reorganization that keeps the ticker must not get a
    ticker_shared flag: the successor's valid_from is clamped to the day
    after the predecessor's last trade date, even when its 8-K12B was filed
    earlier."""
    index, clients = _clients(fake_edgar)

    record = DelistRecord(ticker="AET", cik=1122304, observed_delist_date="2018-11-28", crsp_code=304,
                          bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="high", reason="holdco reorg",
                          evidence={"flags": ["successor_unknown"]}, sec_id="BBG000FJLFX8",
                          delist_date="2018-12-09")
    ev = Delisting(sec_id="BBG000FJLFX8", cik=1122304, ticker="AET", delist_date="2018-12-09", record=record,
                        last_trade=LastTrade(date(2018, 11, 28), "notice_a", ()), form25=None, form25_sub=None,
                        exchange="NYSE")

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return ([ev], []) if ctx.security.sec_id == "BBG000FJLFX8" else ([], [])

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)

    # the 8-K12B was filed BEFORE the predecessor's last trade -- without the
    # clamp its ticker_history row would start before the predecessor's ends
    hit = {"_source": {"ciks": ["8888"], "display_names": ["AET HOLDCO INC  (AET)  (CIK 0000008888)"],
                       "file_date": "2018-11-01"}}
    fake_edgar.full_text_search = lambda q, forms, lo, hi: [hit]
    clients.figi.answers[("TICKER", "AET")] = _figi_answer("BBGAETNEW1", "AET", "AET HOLDCO INC")
    clients.figi.answers[("COMPOSITE_ID_BB_GLOBAL", "BBGAETNEW1")] = {
        "data": [{"figi": "BBGAETNEW1", "compositeFIGI": "BBGAETNEW1", "exchCode": "UN", "ticker": "AET",
                  "name": "AET HOLDCO INC"}]}

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    new_rows = [r for r in th if r["sec_id"] == "BBGAETNEW1"]
    assert len(new_rows) == 1
    assert new_rows[0]["valid_from"] == "2018-11-29"     # day after 2018-11-28, not the earlier 8-K12B date
    review = read_table("review", table_path(tmp_path, "review"))
    assert not any(r["review_flags"] == "ticker_shared" for r in review)


# --- one ticker_history range per acquirer, across all its mergers ---

def test_run_writes_one_acquirer_range_spanning_all_its_mergers(fake_edgar, tmp_path, monkeypatch):
    fake_edgar.company_map["S1"] = {"cik_str": 7101, "ticker": "S1", "title": "TARGET ONE INC"}
    fake_edgar.company_map["S2"] = {"cik_str": 7102, "ticker": "S2", "title": "TARGET TWO INC"}
    fake_edgar.company_map["ACQ"] = {"cik_str": 7777, "ticker": "ACQ", "title": "ACQUIRER CO"}
    fake_edgar.submissions_by_cik[7101] = []
    fake_edgar.submissions_by_cik[7102] = []
    fake_edgar.submissions_by_cik[7777] = [EdgarSubmission("X1", "10-K", "2010-01-01", "", "", "x.htm")]

    figi = _RecordingFigi({
        "S1": _figi_answer("BBGSEC101", "S1", "TARGET ONE INC"),
        "S2": _figi_answer("BBGSEC102", "S2", "TARGET TWO INC"),
        "ACQCUSIP": _figi_answer("BBGACQ0001", "ACQ", "ACQUIRER CO"),
    })

    class _FtdTwoWindows:
        ROWS = [FtdRow("2020-03-05", "ACQCUSIP", "ACQ", "ACQUIRER CO", 40.0),
                FtdRow("2020-09-10", "ACQCUSIP", "ACQ", "ACQUIRER CO", 60.0)]

        def urls_for(self, lo, hi):
            return ["mem"]

        def rows(self, url, *, symbols=None, cusips=None):
            for r in self.ROWS:
                if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                    yield r

    obs = [Observation("S1", "2019-01-01", "TARGET ONE INC", cik=7101),
           Observation("S1", "2020-02-20", "TARGET ONE INC", cik=7101),
           Observation("S2", "2019-01-01", "TARGET TWO INC", cik=7102),
           Observation("S2", "2020-08-25", "TARGET TWO INC", cik=7102)]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, observed_names=index.name_on, cik_pins=index.cik_pin_on)
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=figi, ftd_client=_FtdTwoWindows())

    def _merger_ev(sec_id, ticker, cik, last_trade_day, delist_date):
        rec = DelistRecord(ticker=ticker, cik=cik, observed_delist_date=delist_date, crsp_code=231,
                           bucket=CrspBucket.MERGER, confidence="high", reason="x", evidence={"flags": []},
                           sec_id=sec_id, delist_date=delist_date)
        return Delisting(sec_id=sec_id, cik=cik, ticker=ticker, delist_date=delist_date, record=rec,
                              last_trade=LastTrade(last_trade_day, "notice_a", ()), form25=None, form25_sub=None,
                              exchange="NYSE")

    ev1 = _merger_ev("BBGSEC101", "S1", 7101, date(2020, 2, 28), "2020-03-15")
    ev2 = _merger_ev("BBGSEC102", "S2", 7102, date(2020, 9, 2), "2020-09-20")

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            if ctx.security.sec_id == "BBGSEC101":
                return [ev1], []
            if ctx.security.sec_id == "BBGSEC102":
                return [ev2], []
            return [], []

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)

    overrides = Overrides(merger_terms={
        ("BBGSEC101", "2020-03-15"): {"stock_ratio": 1.0, "acquirer_price": 40.0, "acquirer_ticker": "ACQ"},
        ("BBGSEC102", "2020-09-20"): {"stock_ratio": 1.0, "acquirer_price": 60.0, "acquirer_ticker": "ACQ"},
    }, last_trade_closes={"BBGSEC101": 40.0, "BBGSEC102": 60.0})

    run(index, clients, overrides, out_dir=tmp_path, log=lambda *_: None)

    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    acq_rows = [r for r in th if r["sec_id"] == "BBGACQ0001"]
    assert len(acq_rows) == 1
    assert acq_rows[0]["valid_from"] == "2020-03-05" and acq_rows[0]["valid_to"] == "2020-09-10"


# --- a listed_today error for one observed security does not abort the run ---

def test_listed_today_error_for_one_security_does_not_abort_the_run(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    real_map = clients.figi.map

    def _boom_map(jobs, use_cache=True):
        for j in jobs:
            if j.get("idValue") == "BBG000LIVE01":
                raise RuntimeError("figi boom")
        return real_map(jobs, use_cache=use_cache)

    clients.figi.map = _boom_map

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["sec_id"] == "BBG000FJLFX8"       # AET's row still made it through
    review = read_table("review", table_path(tmp_path, "review"))
    assert any(r["sec_id"] == "BBG000LIVE01" and r["review_flags"] == "error" and "figi boom" in r["reason"]
              for r in review)


# ===================== final fix wave A =====================

class _RowsFtdClient:
    """An FTD client over in-memory rows, filtered like the real one."""

    def __init__(self, rows):
        self.ROWS = list(rows)

    def urls_for(self, lo, hi):
        return ["mem"]

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self.ROWS:
            if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                yield r


class _MapFigi:
    """OpenFIGI fake keyed by (idType, idValue)."""

    def __init__(self, answers):
        self.answers = answers

    def map(self, jobs, use_cache=True):
        return [self.answers.get((j["idType"], j["idValue"]), {"warning": "No identifier found."}) for j in jobs]

    def filter(self, query, **fields):
        return []


def _index_clients(fake_edgar, obs, rows, figi_answers):
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, observed_names=index.name_on, cik_pins=index.cik_pin_on)
    return index, Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                          figi=_MapFigi(figi_answers), ftd_client=_RowsFtdClient(rows))


def _ftd(symbol, cusip, desc, dates, price=10.0):
    return [FtdRow(d, cusip, symbol, desc, price) for d in dates]


def test_run_splits_two_securities_that_shared_a_ticker(fake_edgar, tmp_path):
    """DELL: Dell Inc. (taken private 2013) and Dell Technologies class C (listed
    2018) agree on the one name word DELL; the observations form one era, and the
    FTD gap and CUSIP switch must split it into two securities."""
    fake_edgar.company_map["DELL"] = {"cik_str": 1571996, "ticker": "DELL", "title": "Dell Technologies Inc."}
    fake_edgar.submissions_by_cik[1571996] = []
    obs = [Observation("DELL", d, "DELL INC.") for d in ("2012-06-29", "2012-12-31", "2013-06-28")] + \
          [Observation("DELL", d, "DELL TECHNOLOGIES INC CLASS C") for d in ("2018-12-31", "2019-06-30")]
    rows = (_ftd("DELL", "24702R101", "DELL INC", ["2012-06-01", "2012-09-04", "2013-01-02", "2013-06-03",
                                                  "2013-10-29"])
            + _ftd("DELL", "24703L202", "DELL TECHNOLOGIES INC COM CL C",
                   ["2019-01-02", "2019-03-01", "2019-06-03", "2019-09-03"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "24702R101"): _figi_answer("BBGDELLINC1", "DELL", "DELL INC"),
        ("ID_CUSIP", "24703L202"): _figi_answer("BBGDELLTEC1", "DELL", "DELL TECHNOLOGIES -C"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    secs = {r["sec_id"] for r in read_table("securities", table_path(tmp_path, "securities"))}
    assert secs == {"BBGDELLINC1", "BBGDELLTEC1"}
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    assert [(r["sec_id"], r["valid_from"], r["valid_to"]) for r in th] == [
        ("BBGDELLINC1", "2012-06-01", "2013-10-29"), ("BBGDELLTEC1", "2018-12-31", "2019-09-03")]


def test_two_eras_of_one_security_give_one_security_and_one_ticker_range(fake_edgar, tmp_path):
    """A reverse split changes the CUSIP (refine_eras splits the era there), and
    the snapshot gap is bridged by FTD rows; both eras resolve to one FIGI and
    must come back together as one security with one ticker range."""
    fake_edgar.company_map["RS"] = {"cik_str": 4242, "ticker": "RS", "title": "REVERSE SPLIT CO"}
    fake_edgar.submissions_by_cik[4242] = []
    obs = [Observation("RS", d, "REVERSE SPLIT CO") for d in ("2009-06-08", "2012-06-29", "2012-12-31",
                                                               "2013-06-28")]
    rows = (_ftd("RS", "11111A101", "REVERSE SPLIT CO", ["2009-06-01", "2010-03-01", "2011-01-03", "2011-11-01",
                                                          "2012-07-02", "2012-10-01"])
            + _ftd("RS", "11111A200", "REVERSE SPLIT CO NEW", ["2012-10-02", "2013-01-02", "2013-04-01",
                                                               "2013-07-01"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "11111A101"): _figi_answer("BBGRSPLIT01", "RS", "REVERSE SPLIT CO"),
        ("ID_CUSIP", "11111A200"): _figi_answer("BBGRSPLIT01", "RS", "REVERSE SPLIT CO"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    assert [r["sec_id"] for r in read_table("securities", table_path(tmp_path, "securities"))] == ["BBGRSPLIT01"]
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    assert [(r["ticker"], r["valid_from"], r["valid_to"]) for r in th] == [("RS", "2009-06-01", "2013-07-01")]


def test_cusip_history_keeps_a_retired_cusip_closed_and_the_current_one_open(fake_edgar, tmp_path):
    """A reverse split: FTD rows carry the old CUSIP, the latest observation the
    new one (its own FTD rows are too few to split the era). Both map to the
    security's FIGI, so both are kept: the retired one ends the day before the
    new one's first sighting, and only the new one is open (listed today)."""
    fake_edgar.company_map["RS"] = {"cik_str": 4343, "ticker": "RS", "title": "REVERSE SPLIT CO"}
    fake_edgar.submissions_by_cik[4343] = []
    obs = [Observation("RS", "2019-06-28", "REVERSE SPLIT CO"), Observation("RS", "2019-12-31", "REVERSE SPLIT CO"),
           Observation("RS", "2020-06-30", "REVERSE SPLIT CO", cusip="11111A200")]
    rows = (_ftd("RS", "11111A101", "REVERSE SPLIT CO", ["2019-06-03", "2019-09-03", "2019-12-02"])
            + _ftd("RS", "11111A200", "REVERSE SPLIT CO NEW", ["2020-01-02", "2020-03-02"]))
    listed = {"data": [{"figi": "BBGRSPLIT02", "compositeFIGI": "BBGRSPLIT01", "exchCode": "UN", "ticker": "RS",
                        "name": "REVERSE SPLIT CO"}]}
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "11111A101"): _figi_answer("BBGRSPLIT01", "RS", "REVERSE SPLIT CO"),
        ("ID_CUSIP", "11111A200"): _figi_answer("BBGRSPLIT01", "RS", "REVERSE SPLIT CO"),
        ("COMPOSITE_ID_BB_GLOBAL", "BBGRSPLIT01"): listed,
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    ch = read_table("cusip_history", table_path(tmp_path, "cusip_history"))
    assert [(r["cusip"], r["valid_from"], r["valid_to"]) for r in ch] == [
        ("11111A101", "2019-06-03", "2020-01-01"), ("11111A200", "2020-01-02", "")]
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    assert [(r["ticker"], r["valid_from"], r["valid_to"]) for r in th] == [("RS", "2019-06-03", "")]


def test_last_trade_close_uses_the_cusip_whose_range_holds_the_last_trade_day():
    """`_last_trade_closes` prices each last trade day by the security's CUSIP whose
    range holds that day (from its fails rows), then by its ticker: by symbol
    alone, another CUSIP's rows under RS (99.0) would come first on both days."""
    from delist_detection.sources.ftd import FtdIndex
    from delist_detection.outputs.manifest import StageMeter
    from delist_detection.identity.observations import TickerEra

    ftd = FtdIndex(_ftd("RS", "11111A101", "REVERSE SPLIT CO", ["2019-06-03", "2019-09-04"], price=2.0)
                   + _ftd("RS", "00000X000", "SOMETHING ELSE", ["2019-09-04", "2020-03-03"], price=99.0)
                   + _ftd("RS", "11111A200", "REVERSE SPLIT CO NEW", ["2020-01-02", "2020-03-03"], price=20.0)
                   + _ftd("RSQ", "22222B200", "OTHER", ["2021-01-05"], price=7.0))
    era = TickerEra("RS", "2019-06-03", "2020-12-31", [Observation("RS", "2019-06-03", "REVERSE SPLIT CO")])
    sec = Security("BBGRS", 5, "COMMON", "REVERSE SPLIT CO", "Common Stock", True, "cusip", eras=[era])

    def delisting(ticker, delist_date, last_trade):
        record = DelistRecord(ticker=ticker, cik=5, observed_delist_date=delist_date, crsp_code=231,
                              bucket=CrspBucket.MERGER, confidence="high", reason="x", evidence={},
                              sec_id="BBGRS", delist_date=delist_date)
        return Delisting("BBGRS", 5, ticker, delist_date, record, LastTrade(last_trade, "midas", ()), None, None, "")

    first, second, otc = (delisting("RS", "2019-09-13", date(2019, 9, 3)),
                          delisting("RS", "2020-03-12", date(2020, 3, 2)),
                          delisting("RSQ", "2021-01-14", date(2021, 1, 4)))
    ctx = pipeline._RunContext(None, date(2026, 9, 25), lambda *_: None, 1, StageMeter(lambda *_: None))
    closes = pipeline._last_trade_closes(ctx, [first, second, otc], {"BBGRS": sec},
                                         {"BBGRS": ["11111A101", "11111A200"]}, ftd, date(2004, 1, 1), Overrides())
    assert closes[first.key] == 2.0                  # 11111A101's range holds 2019-09-03
    assert closes[second.key] == 20.0                # 11111A200's range holds 2020-03-02
    assert closes[otc.key] == 7.0                    # the range's CUSIP has no row that day: the ticker's
    assert first.flags == second.flags == otc.flags == []


def test_a_lagged_acquirer_close_flags_the_delisting(fake_edgar, tmp_path, monkeypatch):
    """The acquirer's price is its FTD close on the merger's last trade day; when
    no row sits on the next trading day and a later row is used, the delisting
    carries acquirer_close_lagged (a merger priced on time does not)."""
    fake_edgar.company_map["S1"] = {"cik_str": 7201, "ticker": "S1", "title": "TARGET ONE INC"}
    fake_edgar.company_map["S2"] = {"cik_str": 7202, "ticker": "S2", "title": "TARGET TWO INC"}
    fake_edgar.submissions_by_cik[7201] = []
    fake_edgar.submissions_by_cik[7202] = []
    obs = [Observation("S1", "2020-01-02", "TARGET ONE INC"), Observation("S1", "2020-05-29", "TARGET ONE INC"),
           Observation("S2", "2020-01-02", "TARGET TWO INC"), Observation("S2", "2020-08-31", "TARGET TWO INC")]
    rows = (_ftd("ACQ", "ACQCUSIP1", "ACQUIRER CO", ["2020-06-04"], price=100.0)        # 06-01 trade: 2 days late
            + _ftd("ACQ", "ACQCUSIP1", "ACQUIRER CO", ["2020-09-02"], price=150.0))     # 09-01 trade: on time
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("TICKER", "S1"): _figi_answer("BBGSEC201", "S1", "TARGET ONE INC"),
        ("TICKER", "S2"): _figi_answer("BBGSEC202", "S2", "TARGET TWO INC"),
    })

    def _merger(sec_id, ticker, cik, last_trade_day, delist_date):
        rec = DelistRecord(ticker=ticker, cik=cik, observed_delist_date=delist_date, crsp_code=231,
                           bucket=CrspBucket.MERGER, confidence="high", reason="x", evidence={"flags": []},
                           sec_id=sec_id, delist_date=delist_date)
        return Delisting(sec_id=sec_id, cik=cik, ticker=ticker, delist_date=delist_date, record=rec,
                              last_trade=LastTrade(last_trade_day, "notice_a", ()), form25=None, form25_sub=None,
                              exchange="NYSE")

    events = {"BBGSEC201": _merger("BBGSEC201", "S1", 7201, date(2020, 6, 1), "2020-06-12"),
              "BBGSEC202": _merger("BBGSEC202", "S2", 7202, date(2020, 9, 1), "2020-09-11")}

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            ev = events.get(ctx.security.sec_id)
            return ([ev] if ev else []), []

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)

    class _LLM:
        def extract(self, record, security_name=""):
            return MergerTerms("stock", None, 1.0, "ACQUIRER CO", "ACQ", "high", "8-K:X", "")

    clients.llm_extractor = _LLM()
    run(index, clients, Overrides(last_trade_closes={"BBGSEC201": 100.0, "BBGSEC202": 150.0}), out_dir=tmp_path,
        log=lambda *_: None)

    d = {r["sec_id"]: r for r in read_table("delistings", table_path(tmp_path, "delistings"))}
    assert d["BBGSEC201"]["acquirer_price"] == "100.000000"
    assert "acquirer_close_lagged" in d["BBGSEC201"]["review_flags"].split(";")
    assert d["BBGSEC202"]["acquirer_price"] == "150.000000"
    assert "acquirer_close_lagged" not in d["BBGSEC202"]["review_flags"].split(";")


def test_run_is_deterministic(fake_edgar, tmp_path):
    """Spec §11: the same inputs and caches give byte-identical CSVs."""
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path / "a", log=lambda *_: None)
    run(index, clients, Overrides(), out_dir=tmp_path / "b", log=lambda *_: None)
    names = ["securities", "ticker_history", "cusip_history", "delistings", "payouts", "review", "review_summary",
             "observation_map", "uncertain"]
    contract = ["security_history", "contract_delistings", "seeds", "price_requests", "id_changes"]
    for name in names + contract:
        assert table_path(tmp_path / "a", name).read_bytes() == table_path(tmp_path / "b", name).read_bytes(), name
    assert sorted(p.name for p in (tmp_path / "a").glob("*.csv")) == sorted(f"{n}.csv" for n in names)


def test_every_run_writes_the_contract_beside_todays_tables(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    for name in ("security_history", "contract_delistings", "seeds", "price_requests", "id_changes"):
        assert table_path(tmp_path, name).exists() and name in summary.counts
    ended = {r["sec_id"]: r for r in read_table("contract_delistings", table_path(tmp_path, "contract_delistings"))}
    assert ended["BBG000FJLFX8"]["exit_kind"] == "merger"
    assert ended["BBG000FJLFX8"]["verdict"] in ("confirmed", "uncertain")
    seeds = read_table("seeds", table_path(tmp_path, "seeds"))
    assert len(seeds) == len(read_table("observation_map", table_path(tmp_path, "observation_map")))
    hist = read_table("security_history", table_path(tmp_path, "security_history"))
    assert {r["sec_id"] for r in hist} >= {"BBG000FJLFX8", "BBG000LIVE01"}
    assert {r["issuer_id"] for r in hist if r["sec_id"] == "BBG000FJLFX8"} == {"1122304"}
    assert json.loads((tmp_path / "run_manifest.json").read_text())["schema_version"] == 3
    assert (tmp_path / "contract" / "payout_legs.csv").exists()          # schema 3 (ruling R3)


def test_id_changes_compare_the_run_with_a_baseline(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    baseline = [{"sec_id": "CIK1122304-COMMON", "issuer_cik": "1122304", "share_class": "COMMON",
                 "name": "AETNA INC", "security_type": "", "observed": "true", "figi_source": "placeholder"}]
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, id_baseline=baseline)
    rows = read_table("id_changes", table_path(tmp_path, "id_changes"))
    assert [(r["old_sec_id"], r["new_sec_id"]) for r in rows] == [("CIK1122304-COMMON", "BBG000FJLFX8")]


def test_review_decisions_accept_a_flag_and_are_counted_in_the_manifest(fake_edgar, tmp_path):
    """A decision matching the run's own `ticker_unconfirmed` row on LIVE (its
    only token) clears it from review.csv and is counted `accepted` in both
    RunSummary.review_counts and the manifest's new "review" field."""
    index, clients = _clients(fake_edgar)
    decisions = [Decision("BBG000LIVE01", "", "LIVE", "ticker_unconfirmed", "checked, fine")]
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, review_decisions=decisions)
    review = read_table("review", table_path(tmp_path, "review"))
    assert not any(r["sec_id"] == "BBG000LIVE01" for r in review)
    assert summary.review_counts["accepted"] == 1
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["review"] == summary.review_counts


def test_a_stale_review_decision_becomes_a_review_decision_unmatched_row(fake_edgar, tmp_path):
    """A decision naming a flag no row carries (a typo, or a line written
    against an older run) never disappears silently: it becomes a `fix`
    `review_decision_unmatched` row."""
    index, clients = _clients(fake_edgar)
    decisions = [Decision("NOPE", "2020-01-01", "ZZZ", "no_figi", "typo")]
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, review_decisions=decisions)
    review = read_table("review", table_path(tmp_path, "review"))
    assert any(r["review_flags"] == "review_decision_unmatched:no_figi" and r["severity"] == "fix"
              for r in review)
    assert summary.review_counts["unmatched_decisions"] == 1


def test_a_blank_dlret_with_no_flags_still_reaches_review_as_fix_no_dlret(fake_edgar, tmp_path, monkeypatch):
    """dlret.decide can return NaN with an *empty* flags
    list -- a --last-trade-closes override of 0 on a non-merger bucket, since
    the override was "given" so no_last_close is never added (SEC
    fails-to-deliver data never itself yields a close <= 0). Such a delisting
    must still reach review.csv as `fix` with `no_dlret`, not be silently
    skipped because enr.review_flags is empty."""
    index, clients = _clients(fake_edgar)
    record = DelistRecord(ticker="AET", cik=1122304, observed_delist_date="2018-11-28", crsp_code=470,
                          bucket=CrspBucket.LIQUIDATION, confidence="high", reason="bankruptcy",
                          evidence={"flags": []}, sec_id="BBG000FJLFX8", delist_date="2018-12-09")
    ev = Delisting(sec_id="BBG000FJLFX8", cik=1122304, ticker="AET", delist_date="2018-12-09", record=record,
                        last_trade=LastTrade(date(2018, 11, 28), "notice_a", ()), form25=None, form25_sub=None,
                        exchange="NYSE")

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return ([ev], []) if ctx.security.sec_id == "BBG000FJLFX8" else ([], [])

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)
    overrides = Overrides(last_trade_closes={("BBG000FJLFX8", "2018-12-09"): 0.0})
    run(index, clients, overrides, out_dir=tmp_path, log=lambda *_: None)
    (d,) = [d for d in read_table("delistings", table_path(tmp_path, "delistings")) if d["sec_id"] == "BBG000FJLFX8"]
    assert d["dlret"] == "" and d["review_flags"] == ""     # confirms the gap: no flag, blank DLRET
    review = read_table("review", table_path(tmp_path, "review"))
    (r,) = [r for r in review if r["sec_id"] == "BBG000FJLFX8"]
    assert (r["severity"], r["review_flags"]) == ("fix", "no_dlret")


def test_delistings_csv_is_byte_identical_with_and_without_review_decisions(fake_edgar, tmp_path):
    """Decisions only ever touch review.csv/review_summary.csv."""
    index, clients = _clients(fake_edgar)
    decisions = [Decision("BBG000LIVE01", "", "LIVE", "ticker_unconfirmed", "checked, fine")]
    run(index, clients, Overrides(), out_dir=tmp_path / "no_decisions", log=lambda *_: None)
    run(index, clients, Overrides(), out_dir=tmp_path / "with_decisions", log=lambda *_: None,
        review_decisions=decisions)
    assert (table_path(tmp_path / "no_decisions", "delistings").read_bytes()
            == table_path(tmp_path / "with_decisions", "delistings").read_bytes())


def test_limit_suppresses_unmatched_decision_rows_but_still_counts_and_logs_them(fake_edgar, tmp_path):
    """A --limit dev subset can only see a fraction of the
    rows a decisions file was written against; every decision outside it must
    not flood review.csv with review_decision_unmatched rows, but must still
    be counted and logged."""
    index, clients = _clients(fake_edgar)
    decisions = [Decision("BBG000LIVE01", "", "LIVE", "ticker_unconfirmed", "checked, fine")]
    logged = []
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=logged.append, limit=1,
                  review_decisions=decisions)
    review = read_table("review", table_path(tmp_path, "review"))
    assert not any("review_decision_unmatched" in r["review_flags"] for r in review)
    assert summary.review_counts["unmatched_decisions"] == 1
    assert any("1 decision(s)" in line and "--limit 1" in line for line in logged)


def test_review_csv_first_column_is_severity_and_holds_only_fix_or_check(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    with table_path(tmp_path, "review").open(newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames[0] == "severity"
        rows = list(reader)
    assert rows and all(r["severity"] in ("fix", "check") for r in rows)


def test_successor_search_quotes_the_predecessor_issuers_edgar_name(fake_edgar, tmp_path, monkeypatch):
    """The 8-K12B names the predecessor as EDGAR does ("Google Inc."), never as
    an index snapshot does ("GOOGLE INC CLASS A"): full-text search must quote
    the issuer's EDGAR name from its submissions JSON."""
    fake_edgar.company_map["GOOGL"] = {"cik_str": 1288776, "ticker": "GOOGL", "title": "Google Inc."}
    fake_edgar.submissions_by_cik[1288776] = []
    obs = [Observation("GOOGL", d, "GOOGLE INC CLASS A") for d in ("2014-06-30", "2015-06-30")]
    rows = _ftd("GOOGL", "38259P508", "GOOGLE INC;COM USD0.001 CL'A'",
                ["2014-06-02", "2014-12-01", "2015-06-01", "2015-10-02"])
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "38259P508"): _figi_answer("BBGGOOGLEA1", "GOOGL", "GOOGLE INC-CL A"),
        ("TICKER", "GOOGL"): _figi_answer("BBG009S39JX6", "GOOGL", "ALPHABET INC-CL A"),
        ("TICKER", "GOOG"): _figi_answer("BBG009S3NB30", "GOOG", "ALPHABET INC-CL C"),
    })
    record = DelistRecord(ticker="GOOGL", cik=1288776, observed_delist_date="2015-10-02", crsp_code=300,
                          bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="high", reason="holdco reorg",
                          evidence={"flags": ["successor_unknown"]}, sec_id="BBGGOOGLEA1", delist_date="2015-10-12")
    ev = Delisting(sec_id="BBGGOOGLEA1", cik=1288776, ticker="GOOGL", delist_date="2015-10-12", record=record,
                        last_trade=LastTrade(date(2015, 10, 2), "notice_a", ()), form25=None, form25_sub=None,
                        exchange="NASDAQ")

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return [ev], []

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)
    filing_text = ("Alphabet Inc. became the successor issuer to Google Inc. pursuant to Rule 12g-3(a); "
                   "each share of Google Class A Capital Stock converted into Alphabet Class A Common Stock.")
    queries = []

    def _search(q, forms, lo, hi):              # EDGAR full-text search: the quoted phrase must appear
        queries.append(q)
        if q.strip('"') not in filing_text:
            return []
        return [{"_source": {"ciks": ["1652044"], "display_names": ["Alphabet Inc.  (GOOGL, GOOG)  (CIK 0001652044)"],
                             "file_date": "2015-10-02"}}]

    fake_edgar.full_text_search = _search

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    assert queries == ['"Google Inc."']
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["successor_sec_id"] == "BBG009S39JX6"                     # Alphabet class A, the matching class
    assert "successor_unknown" not in d["review_flags"]


def test_successor_search_name_falls_back_to_the_observation_name_without_class_words(fake_edgar):
    fake_edgar.company_map["AET"] = {"cik_str": 1122304, "ticker": "AET", "title": "AETNA INC /PA/"}
    assert successor_search_name(fake_edgar, 1122304, "AETNA INC") == "AETNA INC"       # EDGAR's state tag dropped
    fake_edgar.submissions = lambda cik, fresh_after=None: {"name": "", "formerNames": []}
    assert successor_search_name(fake_edgar, 1288776, "GOOGLE INC CLASS A") == "GOOGLE INC"
    assert successor_search_name(fake_edgar, 1288776, "ALPHABET INC-CL C") == "ALPHABET INC"
    assert successor_search_name(fake_edgar, None, "LIBERTY MEDIA CORP SERIES A") == "LIBERTY MEDIA CORP"


@pytest.mark.parametrize("pinned, source", [(False, "manual"), (True, "cik_map")])
def test_the_resolver_tier_reaches_the_delisting_row(fake_edgar, tmp_path, pinned, source):
    """The CIK's resolver tier (a MANUAL_OVERRIDES entry, or the caller's cik
    pin) is recorded as the delisting's resolution_source, from the security's
    latest era, instead of the generic "security_master"."""
    index, clients = _clients(fake_edgar)
    if not pinned:
        obs = [Observation("AET", "2017-06-30", "AETNA INC"), Observation("AET", "2018-06-29", "AETNA INC")]
        index = ObservationIndex(obs)
        clients.resolver = TickerResolver(fake_edgar, manual_overrides={"AET": 1122304},
                                          observed_names=index.name_on, cik_pins=index.cik_pin_on)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["sec_id"] == "BBG000FJLFX8" and d["resolution_source"] == source


def test_an_era_whose_ticker_the_sec_data_never_shows_is_reviewed(fake_edgar, tmp_path):
    """APTV as the snapshots record it: "APTIV PLC" under APTV in 2012-2013 (a
    backfilled ticker: Delphi traded as DLPH then) and again from 2017-12-31.
    The 2012-2013 era has no fails row under APTV within 30 days of its span, so
    it gets a ticker_unconfirmed review row; the later era, confirmed by FTD
    rows, and an era before 2004 (no FTD data then) do not."""
    fake_edgar.company_map["APTV"] = {"cik_str": 1521332, "ticker": "APTV", "title": "Aptiv PLC"}
    fake_edgar.company_map["OLD"] = {"cik_str": 4444, "ticker": "OLD", "title": "OLD CO"}
    fake_edgar.submissions_by_cik[1521332] = []
    fake_edgar.submissions_by_cik[4444] = []
    obs = ([Observation("APTV", d, "APTIV PLC") for d in ("2012-06-29", "2012-12-31", "2013-06-28", "2013-12-31",
                                                         "2017-12-31", "2018-06-30")]
           + [Observation("OLD", d, "OLD CO") for d in ("2002-06-28", "2003-06-30")])
    rows = _ftd("APTV", "G6095L109", "APTIV PLC", ["2017-12-05", "2018-01-02", "2018-03-01", "2018-06-01", "2018-07-02"])
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CINS", "G6095L109"): _figi_answer("BBGAPTIV001", "APTV", "APTIV PLC"),
        ("TICKER", "APTV"): _figi_answer("BBGAPTIV001", "APTV", "APTIV PLC"),
        ("TICKER", "OLD"): _figi_answer("BBGOLDCO001", "OLD", "OLD CO"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    review = read_table("review", table_path(tmp_path, "review"))
    flagged = [(r["sec_id"], r["ticker"], r["last_seen"]) for r in review if r["review_flags"] == "ticker_unconfirmed"]
    assert flagged == [("BBGAPTIV001", "APTV", "2013-12-31")]
    (row,) = [r for r in review if r["review_flags"] == "ticker_unconfirmed"]
    assert "APTV@2012-06-29" in row["reason"] and "2012-05-30" in row["reason"] and "2014-01-30" in row["reason"]


ERAS_FIX = Path(__file__).parent / "fixtures" / "eras"


def _eras_fixture(tickers):
    import csv
    from delist_detection.identity.observations import load_observations
    obs = [o for o in load_observations(ERAS_FIX / "observations.csv") if o.ticker in tickers]
    with (ERAS_FIX / "ftd_rows.csv").open(newline="") as fh:
        rows = [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"],
                       float(r["price"]) if r["price"] not in ("", "None") else None)
                for r in csv.DictReader(fh) if r["symbol"] in tickers]
    return obs, rows


@pytest.mark.parametrize("name_hit", [True, False])
def test_backfilled_names_lose_no_observation_and_are_reviewed(fake_edgar, tmp_path, monkeypatch, name_hit):
    """Real CB and AGN rows: CB is both ACE LTD and CHUBB CORP on five dates and
    AGN both ALLERGAN INC and ALLERGAN PLC on one. Every observation must reach a
    security, each (ticker, date) gets one observation_conflict review row, the
    CHUBB CORP eras join Chubb Corp by its CUSIP, and the ACE LTD eras never do:
    they resolve on their own — to ACE's line (now Chubb Ltd, merging with CB's
    2016+ era) when the name search finds it, else to an issuer placeholder."""
    obs, rows = _eras_fixture({"CB", "AGN"})
    # Chubb Corp is its own issuer (CIK 20171), pinned as a caller would: the
    # ticker-level override below names ACE/Chubb Ltd's CIK for every CB era.
    obs = [replace(o, cik=20171) if o.name == "CHUBB CORP" else o for o in obs]
    fake_edgar.company_map["CBCORP"] = {"cik_str": 20171, "ticker": "CBCORP", "title": "CHUBB CORP"}
    fake_edgar.submissions_by_cik[20171] = []
    # Without the name hit, nothing names ACE's line either: not even the issuer's
    # EDGAR title (Chubb Ltd's would place it there through the EDGAR names).
    fake_edgar.company_map["CB"] = {"cik_str": 896159, "ticker": "CB",
                                    "title": "Chubb Ltd" if name_hit else "ACE INA HOLDINGS"}
    fake_edgar.company_map["AGN"] = {"cik_str": 1578845, "ticker": "AGN", "title": "Allergan plc"}
    fake_edgar.submissions_by_cik[896159] = []
    fake_edgar.submissions_by_cik[1578845] = []
    chubb_ltd = [{"figi": "BBGCHUBBLTD", "compositeFIGI": "BBGCHUBBLTD", "exchCode": "US", "ticker": "CB",
                  "name": "CHUBB LTD", "securityType": "Common Stock", "securityType2": "Common Stock"},
                 {"figi": "BBGCHUBBLT2", "compositeFIGI": "BBGCHUBBLTD", "exchCode": "UN", "ticker": "CB",
                  "name": "ACE LTD", "securityType": "Common Stock", "securityType2": "Common Stock"}]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, manual_overrides={"CB": 896159, "AGN": 1578845},
                              observed_names=index.name_on, cik_pins=index.cik_pin_on)
    figi = _MapFigi({
        ("ID_CUSIP", "171232101"): _figi_answer("BBGCHUBBCRP", "CB", "CHUBB CORP"),
        ("ID_CINS", "H1467J104"): _figi_answer("BBGCHUBBLTD", "CB", "CHUBB LTD"),
        ("TICKER", "CB"): _figi_answer("BBGCHUBBLTD", "CB", "CHUBB LTD"),
        ("ID_CUSIP", "018490102"): _figi_answer("BBGALLERGAN", "AGN", "ALLERGAN INC"),
        ("ID_CINS", "G0177J108"): _figi_answer("BBGALLERPLC", "AGN", "ALLERGAN PLC"),
    })
    figi.filter = lambda query, **fields: chubb_ltd if name_hit and query == "ACE" else []
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=figi, ftd_client=_RowsFtdClient(rows))
    contexts = {}

    class _Recorder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            contexts[ctx.security.sec_id] = ctx
            return [], []

    monkeypatch.setattr(pipeline, "DelistingFinder", _Recorder)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    reached = sorted((o.ticker, o.as_of, o.name) for c in contexts.values() for e in c.security.eras
                     for o in e.observations)
    assert reached == sorted((o.ticker, o.as_of, o.name) for o in obs)          # no observation lost
    review = read_table("review", table_path(tmp_path, "review"))
    conflicts = sorted((r["ticker"], r["review_flags"]) for r in review
                       if r["review_flags"].startswith("observation_conflict"))
    assert conflicts == [("AGN", "observation_conflict:2014-06-30")] + [
        ("CB", f"observation_conflict:{d}") for d in ("2012-06-29", "2012-12-31", "2013-06-28", "2013-12-31",
                                                      "2014-06-30")]
    for r in review:
        if r["review_flags"].startswith("observation_conflict:") and r["ticker"] == "CB":
            assert "ACE LTD" in r["reason"] and "CHUBB CORP" in r["reason"]
    names_of = {sid: {o.name for e in c.security.eras for o in e.observations} for sid, c in contexts.items()}
    assert names_of["BBGCHUBBCRP"] == {"CHUBB CORP"}                        # ACE LTD never lands on Chubb Corp
    ace = "BBGCHUBBLTD" if name_hit else "CIK896159-COMMON"
    assert "ACE LTD" in names_of[ace]
    if name_hit:
        assert names_of["BBGCHUBBLTD"] == {"ACE LTD", "CHUBB LTD", "CHUBB"}   # merged with CB's 2016+ era
    else:
        assert names_of["CIK896159-COMMON"] == {"ACE LTD"}


def test_ftd_rows_spelled_without_a_separator_are_sightings_of_the_observed_ticker(fake_edgar, tmp_path):
    """FTD writes Brown-Forman class B as "BFB"; the caller writes "BF-B". The
    rows must find the CUSIP and appear in ticker_history as BF-B only."""
    fake_edgar.company_map["BF-B"] = {"cik_str": 14693, "ticker": "BF-B", "title": "BROWN FORMAN CORP"}
    fake_edgar.submissions_by_cik[14693] = []
    obs = [Observation("BF-B", d, "BROWN FORMAN CORP CLASS B") for d in ("2015-06-30", "2015-12-31")]
    rows = _ftd("BFB", "115637209", "BROWN-FORMAN CORP CL-B",
                ["2015-06-01", "2015-08-03", "2015-10-01", "2016-01-04"])
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "115637209"): _figi_answer("BBG000BYNJ81", "BF/B", "BROWN-FORMAN CORP-CLASS B"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    secs = read_table("securities", table_path(tmp_path, "securities"))
    assert [(r["sec_id"], r["figi_source"]) for r in secs] == [("BBG000BYNJ81", "cusip")]
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    assert [(r["ticker"], r["valid_from"], r["valid_to"]) for r in th] == [("BF-B", "2015-06-01", "2016-01-04")]


def test_another_security_under_the_bare_symbol_never_becomes_the_class_ticker(fake_edgar, tmp_path):
    """BF-B is seen once, in the middle of a run of an unrelated security that
    FTD lists as "BFB" too. Its rows must not be relabelled BF-B (their
    description does not agree with BF-B's observed name), or BF-B would take
    that security's CUSIP and resolve to it."""
    fake_edgar.company_map["BF-B"] = {"cik_str": 14693, "ticker": "BF-B", "title": "BROWN FORMAN CORP"}
    fake_edgar.submissions_by_cik[14693] = []
    obs = [Observation("BF-B", "2016-02-15", "BROWN FORMAN CORP CLASS B")]
    rows = (_ftd("BFB", "115637209", "BROWN-FORMAN CORP CL-B", ["2015-06-01", "2015-09-01", "2015-12-01"])
            + _ftd("BFB", "999999999", "BIG FAKE BANCORP", ["2016-01-04", "2016-02-01", "2016-03-01", "2016-04-01"])
            + _ftd("BFB", "115637209", "BROWN-FORMAN CORP CL-B", ["2016-05-02", "2016-06-01", "2016-07-01"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "115637209"): _figi_answer("BBG000BYNJ81", "BF/B", "BROWN-FORMAN CORP-CLASS B"),
        ("ID_CUSIP", "999999999"): _figi_answer("BBGBIGFAKE1", "BFB", "BIG FAKE BANCORP"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    secs = read_table("securities", table_path(tmp_path, "securities"))
    assert [(r["sec_id"], r["figi_source"]) for r in secs] == [("BBG000BYNJ81", "cusip")]


def test_a_ticker_observed_in_both_spellings_keeps_each_securitys_own_spelling(fake_edgar, tmp_path):
    """Hubbell, as the snapshots record it: class B seen as "HUB-B" (Wikipedia)
    and "HUBB" (iShares) until the 2015 class merger, then the merged class under
    its real ticker HUBB. FTD writes "HUBB" throughout. The class B eras must all
    reach the old CUSIP (one security, labelled HUB-B); the merged class keeps
    HUBB even though its FTD rows are keyed by the canonical HUB-B."""
    for t in ("HUB-B", "HUBB"):
        fake_edgar.company_map[t] = {"cik_str": 48898, "ticker": t, "title": "HUBBELL INC"}
    fake_edgar.submissions_by_cik[48898] = []
    obs = ([Observation("HUBB", d, "HUBBELL INC") for d in ("2013-06-28", "2013-12-31", "2016-06-30", "2016-12-30")]
           + [Observation("HUB-B", d, "HUBBELL INC. CL B") for d in ("2014-12-31", "2015-06-30")])
    rows = (_ftd("HUBB", "443510201", "HUBBELL INC CL B", ["2013-06-03", "2013-12-02", "2014-06-02", "2014-12-01",
                                                          "2015-06-01", "2015-12-18"])
            + _ftd("HUBB", "443510607", "HUBBELL INC", ["2015-12-21", "2016-06-01", "2016-12-01", "2017-01-03"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "443510201"): _figi_answer("BBGHUBBOLD1", "HUB/B", "HUBBELL INC -CL B"),
        ("ID_CUSIP", "443510607"): _figi_answer("BBGHUBBNEW1", "HUBB", "HUBBELL INC"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    secs = {r["sec_id"] for r in read_table("securities", table_path(tmp_path, "securities"))}
    assert secs == {"BBGHUBBOLD1", "BBGHUBBNEW1"}
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    assert [(r["sec_id"], r["ticker"], r["valid_from"], r["valid_to"]) for r in th] == [
        ("BBGHUBBNEW1", "HUBB", "2015-12-21", "2017-01-03"),
        ("BBGHUBBOLD1", "HUB-B", "2013-06-03", "2015-12-18")]


STALE_F25_RAW = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>New York Stock Exchange LLC"
                 "</entityName></exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
                 "<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision></notificationOfRemoval>")


def test_a_delisting_before_the_ftd_window_still_gets_its_close(fake_edgar, tmp_path):
    """A.G. Edwards as a stale snapshot records it: acquired 2007-10-01, still
    listed under AGE from 2008-01-16 to 2009-06-08. The FTD rows are first
    loaded from the eras' first sighting on (2007-12-17), so the rows that
    carry the 2007-09-28 close are outside that window; the close lookup must
    reach them all the same."""
    fake_edgar.submissions_by_cik[21000] = [
        EdgarSubmission("w1", "8-K", "2007-10-01", "2007-10-01", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("w2", "25-NSE", "2007-10-02", "", "", "p.xml"),
        EdgarSubmission("w3", "15-12B", "2007-10-12", "", "", "f.htm"),
    ]
    fake_edgar.raws["w2"] = STALE_F25_RAW
    fake_edgar.texts["w1"] = ("Item 3.01 Notice of Delisting. trading was suspended prior to the opening of "
                              "trading on October 1, 2007 " + "x" * 300)
    obs = [Observation("AGE", d, "EDWARDS AG INC", cik=21000, sec_id="BBGAGE00001")
           for d in ("2008-01-16", "2008-07-25", "2009-06-08")]
    rows = _ftd("AGE", "281760108", "EDWARDS A G INC", ["2007-09-04", "2007-09-28"], price=63.5) + \
        _ftd("AGE", "281760108", "EDWARDS A G INC", ["2007-10-01"], price=64.0)
    index, clients = _index_clients(fake_edgar, obs, rows, {})

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert (d["sec_id"], d["delist_date"], d["bucket"]) == ("BBGAGE00001", "2007-10-12", "merger")
    assert d["last_trade_date"] == "2007-09-28" and d["last_trade_close"] == "64.000000"
    assert "observed_after_delisting" in d["review_flags"] and "no_last_close" not in d["review_flags"]


def test_the_early_ftd_extension_covers_the_whole_look_back(fake_edgar, tmp_path):
    """The only fails row before A.G. Edwards' 2007-09-28 last trade is ten
    trading days earlier (2007-09-14): the rows loaded for a delisting before
    the eras' FTD window must reach that far back for the look-back close."""
    fake_edgar.submissions_by_cik[21000] = [
        EdgarSubmission("w1", "8-K", "2007-10-01", "2007-10-01", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("w2", "25-NSE", "2007-10-02", "", "", "p.xml"),
        EdgarSubmission("w3", "15-12B", "2007-10-12", "", "", "f.htm"),
    ]
    fake_edgar.raws["w2"] = STALE_F25_RAW
    fake_edgar.texts["w1"] = ("Item 3.01 Notice of Delisting. trading was suspended prior to the opening of "
                              "trading on October 1, 2007 " + "x" * 300)
    obs = [Observation("AGE", d, "EDWARDS AG INC", cik=21000, sec_id="BBGAGE00001")
           for d in ("2008-01-16", "2008-07-25", "2009-06-08")]
    rows = _ftd("AGE", "281760108", "EDWARDS A G INC", ["2007-09-14"], price=62.0)
    index, clients = _index_clients(fake_edgar, obs, rows, {})

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["last_trade_date"] == "2007-09-28" and d["last_trade_close"] == "62.000000"
    # the 2007-09-14 row carries the close of 2007-09-13, eleven trading days before the last trade
    assert "ftd_close_prior:11" in d["review_flags"].split(";")


def test_each_era_is_resolved_with_its_own_pin(fake_edgar, tmp_path):
    """BlackRock's 2024 holding-company reorganization: the old line is pinned to
    the old issuer, the new line (observed from 2024-12-31) to the new holdco.
    The old era is resolved at its FTD-extended last sighting (2024-10-01), which
    is nearer the new era's first observation than its own last one; the pin
    must still be the old era's own, not the nearest era's."""
    fake_edgar.submissions_by_cik[1364742] = []
    fake_edgar.submissions_by_cik[2012383] = []
    obs = ([Observation("BLK", d, "BLACKROCK INC", cik=1364742) for d in ("2024-01-02", "2024-06-28")]
           + [Observation("BLK", d, "BLACKROCK INC", cik=2012383) for d in ("2024-12-31", "2025-06-30")])
    rows = (_ftd("BLK", "09247X101", "BLACKROCK INC", ["2024-01-02", "2024-04-01", "2024-06-28", "2024-08-01",
                                                      "2024-10-01"])
            + _ftd("BLK", "09290D101", "BLACKROCK INC", ["2024-10-02", "2024-12-02", "2024-12-31", "2025-06-30"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "09247X101"): _figi_answer("BBGBLKOLD01", "BLK", "BLACKROCK INC"),
        ("ID_CUSIP", "09290D101"): _figi_answer("BBGBLKNEW01", "BLK", "BLACKROCK INC"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    secs = {r["sec_id"]: r["issuer_cik"] for r in read_table("securities", table_path(tmp_path, "securities"))}
    assert secs == {"BBGBLKOLD01": "1364742", "BBGBLKNEW01": "2012383"}


def test_a_look_back_close_keeps_its_row_date_in_the_evidence(fake_edgar, tmp_path, monkeypatch):
    rows = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-11-21", "00817Y108", "AET", "AETNA INC.(NEW)", 205.00)]
    index, clients = _clients(fake_edgar, ftd_rows=rows)
    seen = {}
    real = pipeline.enrich

    def spy(record, value, **kw):
        seen[record.sec_id] = record.evidence
        return real(record, value, **kw)

    monkeypatch.setattr(pipeline, "enrich", spy)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert seen["BBG000FJLFX8"]["ftd_close_row_date"] == "2018-11-21"
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert "ftd_close_prior:5" in d["review_flags"].split(";")      # close of 11-20 -> 11-28 (22nd a holiday): 5


def test_listed_today_is_asked_with_each_securitys_own_tickers(fake_edgar, tmp_path, monkeypatch):
    seen = {}

    def spy(figi, sec_id, *, edgar=None, cik=None, tickers=None, answer=None):
        seen[sec_id] = sorted(tickers or [])
        return sec_id == "BBG000LIVE01"

    monkeypatch.setattr(pipeline, "listed_today", spy)
    index, clients = _clients(fake_edgar)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert seen == {"BBG000FJLFX8": ["AET"], "BBG000LIVE01": ["LIVE"]}


def _reorg_run(fake_edgar, tmp_path, monkeypatch, new_dates=("2024-10-02", "2024-12-02", "2024-12-31", "2025-06-30"),
               extra_obs=(), extra_rows=(), extra_figi=None):
    """BlackRock's 2024 holdco reorganization as the finder's fallback reports it:
    the old line (pinned to the old issuer) ends 2024-10-01 with an
    exchange_transfer flagged successor_unknown; the new line (the new holdco,
    same ticker) is first seen in the fails rows on `new_dates[0]`."""
    fake_edgar.submissions_by_cik[1364742] = []
    fake_edgar.submissions_by_cik[2012383] = []
    obs = ([Observation("BLK", d, "BLACKROCK INC", cik=1364742) for d in ("2024-01-02", "2024-06-28")]
           + [Observation("BLK", d, "BLACKROCK INC", cik=2012383) for d in ("2024-12-31", "2025-06-30")]
           + list(extra_obs))
    rows = (_ftd("BLK", "09247X101", "BLACKROCK INC", ["2024-01-02", "2024-04-01", "2024-06-28", "2024-08-01",
                                                      "2024-10-01"])
            + _ftd("BLK", "09290D101", "BLACKROCK INC", list(new_dates)) + list(extra_rows))
    answers = {("ID_CUSIP", "09247X101"): _figi_answer("BBGBLKOLD01", "BLK", "BLACKROCK INC"),
               ("ID_CUSIP", "09290D101"): _figi_answer("BBGBLKNEW01", "BLK", "BLACKROCK INC")}
    answers.update(extra_figi or {})
    index, clients = _index_clients(fake_edgar, obs, rows, answers)
    record = DelistRecord(ticker="BLK", cik=1364742, observed_delist_date="2024-10-01", crsp_code=304,
                          bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="medium", reason="Continued filings",
                          evidence={"flags": ["no_form25", "successor_unknown"]}, sec_id="BBGBLKOLD01",
                          delist_date="2024-10-01")
    ev = Delisting(sec_id="BBGBLKOLD01", cik=1364742, ticker="BLK", delist_date="2024-10-01", record=record,
                        last_trade=LastTrade(date(2024, 10, 1), "", ()), form25=None, form25_sub=None,
                        exchange="NYSE")

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return ([ev], []) if ctx.security.sec_id == "BBGBLKOLD01" else ([], [])

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)
    fake_edgar.full_text_search = lambda q, forms, lo, hi: []
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    return {r["sec_id"]: r for r in read_table("delistings", table_path(tmp_path, "delistings"))}


def test_a_transfer_successor_is_the_runs_new_line_under_the_same_ticker(fake_edgar, tmp_path, monkeypatch):
    d = _reorg_run(fake_edgar, tmp_path, monkeypatch)["BBGBLKOLD01"]
    assert d["successor_sec_id"] == "BBGBLKNEW01"
    assert "successor_unknown" not in d["review_flags"] and d["reason"].endswith("; successor by same ticker")


def test_no_successor_is_linked_when_nothing_starts_near_the_last_trade(fake_edgar, tmp_path, monkeypatch):
    # the new line's fails rows start only on 2024-12-02: nothing starts within 15 days
    d = _reorg_run(fake_edgar, tmp_path, monkeypatch, new_dates=("2024-12-02", "2024-12-31", "2025-06-30"))
    assert d["BBGBLKOLD01"]["successor_sec_id"] == "" and "successor_unknown" in d["BBGBLKOLD01"]["review_flags"]


def test_two_candidates_leave_the_successor_unknown(fake_edgar, tmp_path, monkeypatch):
    """A second security of the old issuer also starts on 2024-10-03: the in-run
    successor search is ambiguous, and the handoff pass does not guess either:
    with no 8-K12B, the old issuer carrying on in a line of its own while
    another issuer's line takes BLK is a spin-off's shape, not a continuation."""
    extra_obs = [Observation("BLKX", "2024-12-31", "BLACKROCK INC SERIES X", cik=1364742)]
    extra_rows = _ftd("BLKX", "09247X999", "BLACKROCK INC SERIES X", ["2024-10-03", "2024-11-01", "2024-12-31"])
    extra = {("ID_CUSIP", "09247X999"): _figi_answer("BBGBLKX0001", "BLKX", "BLACKROCK INC SERIES X")}
    d = _reorg_run(fake_edgar, tmp_path, monkeypatch, extra_obs=extra_obs, extra_rows=extra_rows, extra_figi=extra)
    assert d["BBGBLKOLD01"]["successor_sec_id"] == "" and "successor_unknown" in d["BBGBLKOLD01"]["review_flags"]


def test_with_no_last_trade_date_the_window_is_anchored_on_the_form25_filing():
    """APA Corp's 2021 holdco reorganization: Apache's Form 25 was filed 2021-03-04
    (effective 2021-03-14) and no source dated the last trade; the new line is
    first seen 2021-03-01. Anchored on the effective date the window
    [03-09, 03-29] misses it; the Form 25 filing date is the better proxy."""
    record = DelistRecord(ticker="APA", cik=6769, observed_delist_date="2021-03-04", crsp_code=304,
                          bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="medium", reason="Continued filings",
                          evidence={"flags": ["successor_unknown"]}, sec_id="BBGAPAOLD01", delist_date="2021-03-14")
    sub = EdgarSubmission("0001354457-21-000304", "25-NSE", "2021-03-04", "", "", "p.xml")
    # the delisting's ticker is the fails rows' deleted-symbol spelling; the old line's own ticker is APA
    ev = Delisting(sec_id="BBGAPAOLD01", cik=6769, ticker="APAXXXX", delist_date="2021-03-14", record=record,
                        last_trade=LastTrade(None, "", ("no_last_trade_date",)), form25=None, form25_sub=sub,
                        exchange="NASDAQ")
    starts = {"BBGAPAOLD01": SecurityStart("2007-12-17", 6769, {"APA"}),
              "BBGAPANEW01": SecurityStart("2021-03-01", 1841666, {"APA"})}
    assert successor_in_run(ev, starts) == ("BBGAPANEW01", "same_ticker")


def _same_ticker_acquirer_run(fake_edgar, tmp_path, holder=None, old_tail=()):
    """Waste Connections 2016 as the run sees it: the target (old WCN, pinned to
    its own issuer) is acquired by a company that takes the same ticker WCN; the
    fails rows under WCN around the last trade are mostly the acquirer's CUSIP.
    The resolver's pin lookup for WCN on that day answers with the target's CIK."""
    fake_edgar.submissions_by_cik[1057058] = [
        EdgarSubmission("w1", "8-K", "2016-06-01", "2016-06-01", "2.01,3.01,5.01", "k.htm"),
        EdgarSubmission("w2", "25-NSE", "2016-06-01", "", "", "p.xml")]
    fake_edgar.raws["w2"] = STALE_F25_RAW
    fake_edgar.texts["w1"] = ("Item 3.01 Notice. trading suspended prior to the opening of trading on June 1, 2016 "
                              + "x" * 300)
    if holder:
        fake_edgar.company_map["WCN"] = {"cik_str": holder, "ticker": "WCN", "title": "Waste Connections, Inc."}
        fake_edgar.submissions_by_cik[holder] = []
        fake_edgar.listings[holder] = [("WCN", "NYSE")]
    obs = [Observation("WCN", d, "WASTE CONNECTIONS INC.", cik=1057058) for d in ("2015-06-30", "2015-12-31")]
    rows = (_ftd("WCN", "941053100", "WASTE CONNECTIONS INC",
                 ["2015-06-30", "2015-08-31", "2015-10-30", "2015-12-31", "2016-02-29", "2016-04-29", "2016-05-27",
                  "2016-05-31", *old_tail])
            + _ftd("WCN", "94106B101", "WASTE CONNECTIONS INC",
                   ["2016-06-02", "2016-06-03", "2016-06-06", "2016-06-08", "2016-06-09"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "941053100"): _figi_answer("BBGWCNOLD01", "WCN", "WASTE CONNECTIONS INC"),
        ("ID_CUSIP", "94106B101"): _figi_answer("BBGWCNNEW01", "WCN", "WASTE CONNECTIONS INC")})
    overrides = Overrides(merger_terms={("BBGWCNOLD01", "2016-06-11"):
                                        {"stock_ratio": 2.076, "acquirer_price": 30.0, "acquirer_ticker": "WCN"}})
    run(index, clients, overrides, out_dir=tmp_path, log=lambda *_: None)
    return {r["sec_id"]: r for r in read_table("securities", table_path(tmp_path, "securities"))}


def test_a_same_ticker_acquirer_takes_the_sec_ticker_maps_holder_not_the_targets_cik(fake_edgar, tmp_path):
    secs = _same_ticker_acquirer_run(fake_edgar, tmp_path, holder=1318220)
    assert secs["BBGWCNNEW01"]["observed"] == "false"
    assert secs["BBGWCNNEW01"]["issuer_cik"] == "1318220"


def test_a_same_ticker_acquirer_without_a_ticker_map_holder_has_no_cik(fake_edgar, tmp_path):
    secs = _same_ticker_acquirer_run(fake_edgar, tmp_path)
    assert secs["BBGWCNNEW01"]["issuer_cik"] == ""


def test_the_listing_check_asks_openfigi_once_for_all_securities(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    calls = []
    real_map = clients.figi.map

    def recording(jobs, use_cache=True):
        calls.append([(j["idType"], j["idValue"]) for j in jobs])
        return real_map(jobs, use_cache=use_cache)

    clients.figi.map = recording
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    listing_calls = [c for c in calls if c and c[0][0] == "COMPOSITE_ID_BB_GLOBAL"]
    assert listing_calls == [[("COMPOSITE_ID_BB_GLOBAL", "BBG000FJLFX8"),
                              ("COMPOSITE_ID_BB_GLOBAL", "BBG000LIVE01")]]


# --- another listed company's own stock is not a successor ---

def _cco_hits():
    """EDGAR full-text search for "Clear Channel Outdoor Holdings, Inc." around
    its 2019-05-01 last trade: the new CCOH's 8-K12B is filed under the old
    one's own CIK, and iHeartMedia's 8-K12G3 (its own emergence) names the
    subsidiary."""
    return [{"_source": {"ciks": ["0001334978"], "file_date": "2019-05-02",
                         "display_names": ["Clear Channel Outdoor Holdings, Inc.  (CCO)  (CIK 0001334978)"]}},
            {"_source": {"ciks": ["0001400891"], "file_date": "2019-05-02",
                         "display_names": ["iHeartMedia, Inc.  (IHRT, IHETW, IHRTB)  (CIK 0001400891)"]}}]


def test_successor_8k12b_refuses_another_listed_companys_own_stock(fake_edgar):
    """IHRT is iHeartMedia's own stock, not one of Clear Channel Outdoor's
    tickers; iHeartMedia is listed today and its name shares nothing with
    the predecessor's: it is not the successor, and the delisting keeps
    successor_unknown."""
    fake_edgar.submissions_by_cik[1400891] = []
    fake_edgar.listings[1400891] = [("IHRT", "Nasdaq")]
    figi = _RecordingFigi({"IHRT": _figi_answer("BBG00P2FSNZ9", "IHRT", "IHEARTMEDIA INC - CLASS A")})
    got = successor_from_8k12b(lambda *a: _cco_hits(), figi, name="Clear Channel Outdoor Holdings, Inc.",
                               day=date(2019, 5, 1), exclude_cik=1334978, share_class="CLASS A",
                               edgar=fake_edgar, own_tickers={"CCO"})
    assert got is None
    assert figi.calls == []


def test_successor_8k12b_keeps_a_new_issuer_on_the_predecessors_ticker(fake_edgar):
    """Alphabet shares no name word with Google and is listed today, but it
    carries Google's own tickers: the predecessor's line under a new issuer."""
    fake_edgar.submissions_by_cik[1652044] = []
    fake_edgar.listings[1652044] = [("GOOGL", "Nasdaq"), ("GOOG", "Nasdaq")]
    figi = _SuccessorFigi({"GOOGL": _figi_answer("BBGGOOGL01", "GOOGL", "Alphabet Inc Class A"),
                           "GOOG": _figi_answer("BBGGOOG001", "GOOG", "Alphabet Inc Class C")})
    got = successor_from_8k12b(lambda *a: [_alphabet_hit()], figi, name="Google Inc.", day=date(2015, 10, 2),
                               exclude_cik=1288776, share_class="CLASS C", edgar=fake_edgar,
                               own_tickers={"GOOG", "GOOGL"})
    assert got[0] == 1652044 and got[1].composite == "BBGGOOG001"


def test_successor_8k12b_keeps_a_renamed_issuer_whose_name_agrees(fake_edgar):
    """A new ticker is fine when the successor's EDGAR name agrees with the
    predecessor's (a holding company named after the old issuer)."""
    fake_edgar.submissions_by_cik[7777] = []
    fake_edgar.listings[7777] = [("ACMH", "NYSE")]
    hit = {"_source": {"ciks": ["7777"], "file_date": "2020-01-02",
                       "display_names": ["Acme Widget Holdings Inc.  (ACMH)  (CIK 0000007777)"]}}
    figi = _SuccessorFigi({"ACMH": _figi_answer("BBGACMH0001", "ACMH", "ACME WIDGET HOLDINGS INC")})
    got = successor_from_8k12b(lambda *a: [hit], figi, name="Acme Widget Corp", day=date(2020, 1, 1),
                               exclude_cik=1, edgar=fake_edgar, own_tickers={"ACW"})
    assert got[1].composite == "BBGACMH0001"


def test_a_same_ticker_acquirer_is_never_the_target_itself(fake_edgar, tmp_path):
    """Ashland 2016: most fails rows under ASH around the reorganization carry
    the old line's own CUSIP (fails keep settling after the last trade), so the
    most common CUSIP under the acquirer's ticker was the delisted security
    itself. The acquirer is the new line on that ticker."""
    secs = _same_ticker_acquirer_run(fake_edgar, tmp_path, holder=1318220, old_tail=[
        "2016-05-23", "2016-05-24", "2016-05-25", "2016-05-26", "2016-06-02", "2016-06-03", "2016-06-06"])
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["sec_id"] == "BBGWCNOLD01"
    assert d["acquirer_sec_id"] == "BBGWCNNEW01"
    assert secs["BBGWCNNEW01"]["issuer_cik"] == "1318220"


# --- a deleted symbol's fails rows are not trading ---

_NASDAQ_F25 = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>The Nasdaq Stock Market LLC"
               "</entityName></exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
               "<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision></notificationOfRemoval>")


def _retired_cusip_run(fake_edgar, tmp_path, tail_symbol, tail_dates=("2025-12-31", "2026-01-15", "2026-02-02"),
                       tail_prices=(10.0,)):
    """Liberty Live's 2025 split-off as the fails files show it: the old line's
    CUSIP keeps failing after its Form 25 (2025-12-15, effective 12-25) under
    the deleted symbol LLYKXXXX, while the new line trades LLYK under a new
    CUSIP from 2025-12-17. The old issuer keeps filing 10-Qs, so the
    classifier reads an exchange transfer. The old CUSIP's rows after the Form
    25 are dated `tail_dates`, priced in turn from `tail_prices`."""
    fake_edgar.submissions_by_cik[5555] = [
        EdgarSubmission("f1", "25-NSE", "2025-12-15", "", "", "p.xml"),
        EdgarSubmission("q1", "10-Q", "2026-08-05", "2026-06-30", "", "q.htm")]
    fake_edgar.submissions_by_cik[6666] = []
    fake_edgar.raws["f1"] = _NASDAQ_F25
    obs = ([Observation("LLYK", d, "LIBERTY LIVE CORP", cik=5555) for d in ("2024-06-28", "2024-12-31", "2025-06-30")]
           + [Observation("LLYK", "2026-06-30", "LIBERTY LIVE HOLDINGS INC", cik=6666)])
    rows = (_ftd("LLYK", "53229D101", "LIBERTY LIVE CORP",
                 ["2024-06-28", "2024-12-31", "2025-06-30", "2025-10-01", "2025-12-12"])
            + [FtdRow(d, "53229D101", tail_symbol, "LIBERTY LIVE CORP", tail_prices[i % len(tail_prices)])
               for i, d in enumerate(tail_dates)]
            + _ftd("LLYK", "53230X101", "LIBERTY LIVE HOLDINGS INC", ["2025-12-17", "2026-01-15", "2026-06-30"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "53229D101"): _figi_answer("BBGLLYKOLD1", "LLYK", "LIBERTY LIVE CORP"),
        ("ID_CUSIP", "53230X101"): _figi_answer("BBGLLYKNEW1", "LLYK", "LIBERTY LIVE HOLDINGS INC")})
    fake_edgar.full_text_search = lambda q, forms, lo, hi: []
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    d = {r["sec_id"]: r for r in read_table("delistings", table_path(tmp_path, "delistings"))}
    return d, read_table("ticker_history", table_path(tmp_path, "ticker_history"))


def test_deleted_symbol_fails_after_the_delisting_are_not_continued_trading(fake_edgar, tmp_path):
    d, th = _retired_cusip_run(fake_edgar, tmp_path, "LLYKXXXX")
    old = d["BBGLLYKOLD1"]
    assert old["bucket"] == "exchange_transfer"
    assert old["successor_sec_id"] == "BBGLLYKNEW1"
    assert not [r for r in th if r["ticker"].endswith("XXXX")]


def test_live_symbol_trading_after_the_delisting_still_reads_as_continued(fake_edgar, tmp_path):
    """Sub-plan 5b (C): the old CUSIP trading on under a live symbol (LLYKV), 22 rows over 31 days at two prices,
    is the security going on after its Form 25 (`ftd.trades_after`)."""
    days = [f"2026-01-{d:02d}" for d in (2, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 20, 21, 22, 23, 26, 27, 28, 29, 30)] \
        + ["2026-02-02", "2026-02-03"]
    d, _ = _retired_cusip_run(fake_edgar, tmp_path, "LLYKV", tail_dates=days, tail_prices=(10.0, 10.5))
    assert d["BBGLLYKOLD1"]["successor_sec_id"] == "BBGLLYKOLD1"


def test_a_few_live_symbol_fails_after_the_delisting_are_no_continued_trading(fake_edgar, tmp_path):
    """Sub-plan 5b (C): three fails rows under the live symbol after the Form 25 are fails still settling, not the
    security trading on: the new line is its successor, as with the deleted symbol."""
    d, _ = _retired_cusip_run(fake_edgar, tmp_path, "LLYK")
    assert d["BBGLLYKOLD1"]["successor_sec_id"] == "BBGLLYKNEW1"


def test_a_placeholder_whose_late_rows_are_a_deleted_symbol_is_not_listed_today(fake_edgar, tmp_path):
    """HP's pre-2015 line has no FIGI (a placeholder). Its CUSIP fails under HPQ
    until the November 2015 separation, then only under HPQXXXX. EDGAR still
    lists HPQ for the issuer (today's HP Inc. line), so the placeholder read as
    listed today, with an open HPQXXXX range."""
    fake_edgar.submissions_by_cik[47217] = []
    fake_edgar.listings[47217] = [("HPQ", "NYSE")]
    obs = [Observation("HPQ", d, "HEWLETT PACKARD", cik=47217) for d in ("2014-06-30", "2014-12-31", "2015-06-30")]
    rows = (_ftd("HPQ", "428236103", "HEWLETT PACKARD CO", ["2014-06-30", "2015-01-02", "2015-06-30", "2015-11-02"])
            + _ftd("HPQXXXX", "428236103", "HEWLETT PACKARD CO", ["2015-11-03", "2015-11-20", "2016-01-04"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {})
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    th = [r for r in read_table("ticker_history", table_path(tmp_path, "ticker_history"))
          if r["sec_id"] == "CIK47217-COMMON"]
    assert th and all(r["valid_to"] for r in th)
    assert not [r for r in th if r["ticker"].endswith("XXXX")]
    ch = [r for r in read_table("cusip_history", table_path(tmp_path, "cusip_history"))
          if r["sec_id"] == "CIK47217-COMMON"]
    assert ch and all(r["valid_to"] for r in ch)


# --- an acquirer on another ticker that resolves to the target's CIK ---

class _OneAnswerResolver:
    issuers = None        # no issuer record of its own

    def __init__(self, cik):
        self.cik = cik

    def resolve(self, ticker, observed_date=None, **kw):
        return TickerResolution(ticker=ticker, cik=self.cik, name=None, source="efts")


def _nutrisystem_event():
    record = DelistRecord(ticker="NTRI", cik=1096376, observed_delist_date="2019-03-07", crsp_code=231,
                          bucket=CrspBucket.MERGER, confidence="high", reason="x", evidence={"flags": []},
                          sec_id="BBGNTRI0001", delist_date="2019-03-17")
    return Delisting(sec_id="BBGNTRI0001", cik=1096376, ticker="NTRI", delist_date="2019-03-17",
                          record=record, last_trade=LastTrade(date(2019, 3, 7), "midas", ()), form25=None,
                          form25_sub=None, exchange="NASDAQ")


def test_an_acquirer_on_another_ticker_resolved_to_the_targets_cik_does_not_take_it(fake_edgar):
    """Tivity bought Nutrisystem in 2019, and the resolver answered TVTY with
    Nutrisystem's own CIK. The acquirer must not carry the target's CIK: the SEC
    ticker map's holder of TVTY stands in when EDGAR lists it today, else the
    CIK is left empty."""
    ev = _nutrisystem_event()
    clients = Clients(edgar=fake_edgar, resolver=_OneAnswerResolver(1096376), classifier=None, figi=None,
                      ftd_client=None)
    assert acquirer_cik(clients.resolver, clients.edgar, "TVTY", date(2019, 3, 7), ev) is None

    fake_edgar.company_map["TVTY"] = {"cik_str": 704415, "ticker": "TVTY", "title": "Tivity Health, Inc."}
    fake_edgar.submissions_by_cik[704415] = []
    fake_edgar.listings[704415] = [("TVTY", "Nasdaq")]
    assert acquirer_cik(clients.resolver, clients.edgar, "TVTY", date(2019, 3, 7), ev) == 704415


def test_an_acquirer_on_another_ticker_keeps_the_cik_the_resolver_gives(fake_edgar):
    clients = Clients(edgar=fake_edgar, resolver=_OneAnswerResolver(704415), classifier=None, figi=None,
                      ftd_client=None)
    assert acquirer_cik(clients.resolver, clients.edgar, "TVTY", date(2019, 3, 7), _nutrisystem_event()) == 704415


# --- a stale era must not take another company's CUSIP (spec D21) ---

CCU_DATES = ("2008-01-16", "2008-05-31", "2008-07-25", "2008-11-18", "2009-01-23", "2009-03-20", "2009-06-08")


def test_a_stale_era_does_not_take_the_cusip_of_the_next_company_on_its_ticker(fake_edgar, tmp_path):
    """Real case: Clear Channel (CIK 739708) went private in July 2008, but the
    snapshots list it under CCU until 2009-06-08. From 2008-09-05 SEC's fails
    rows under CCU are Cervecerias Unidas' ADR (204429104), so the CUSIP switch
    splits off a stale Clear Channel era whose only FTD CUSIP is Cervecerias'.
    That era must not take it (its description names another company), so it
    never resolves to Cervecerias' FIGI and no range runs on into 2010."""
    fake_edgar.company_map["CCU"] = {"cik_str": 739708, "ticker": "CCU",
                                     "title": "CLEAR CHANNEL COMMUNICATIONS INC"}
    fake_edgar.submissions_by_cik[739708] = []
    obs = [Observation("CCU", d, "CLEAR CHANNEL COMM INC") for d in CCU_DATES]
    rows = (_ftd("CCU", "184502102", "CLEAR CHANNEL COMMUNICTNS INC",
                 ["2007-12-17", "2008-02-01", "2008-04-01", "2008-06-02", "2008-07-31"], 34.75)
            + _ftd("CCU", "204429104", "COMPANIA CERVECER UNIDAS ADS(5",
                   ["2008-09-05", "2008-12-01", "2009-03-02", "2009-06-01", "2009-09-01", "2010-06-01"], 34.64))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "184502102"): _figi_answer("BBG000BF8BH2", "CCMO", "IHEARTCOMMUNICATIONS INC"),
        ("ID_CUSIP", "204429104"): _figi_answer("BBG000BBCT50", "CCU", "CIA CERVECERIAS UNI-SPON ADR"),
        ("TICKER", "CCU"): _figi_answer("BBG000BBCT50", "CCU", "CIA CERVECERIAS UNI-SPON ADR"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    secs = {r["sec_id"] for r in read_table("securities", table_path(tmp_path, "securities"))}
    assert "BBG000BBCT50" not in secs
    ch = read_table("cusip_history", table_path(tmp_path, "cusip_history"))
    assert "204429104" not in {r["cusip"] for r in ch}
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    assert max(r["valid_to"] or "9999" for r in th) <= "2009-06-08"


def test_an_era_with_no_issuer_takes_a_cusip_another_era_shows_is_its_issuers(fake_edgar, tmp_path):
    """Real case: the snapshots call CME "CHICAGO MERCANTILE HLDGS" in 2008-2009,
    after its 2007 rename to CME Group, and the resolver finds no CIK for that
    name then. Its fails rows (12572Q105, "CME GROUP, INC") share no word with
    that name, but the later CME era, whose issuer is known, shows the CUSIP is
    CME Group's: the old era keeps it and both eras are one security."""
    fake_edgar.company_map["CME"] = {"cik_str": 1156375, "ticker": "CME", "title": "CME GROUP INC."}
    fake_edgar.submissions_by_cik[1156375] = [EdgarSubmission("0001156375-02-000001", "10-K", "2002-03-01", "",
                                                              "", "k.htm")]
    obs = ([Observation("CME", d, "CHICAGO MERCANTILE HLDGS") for d in ("2008-01-16", "2008-07-25", "2009-06-08")]
           + [Observation("CME", d, "CME GROUP INC CLASS A") for d in ("2014-06-30", "2015-06-30")])
    rows = _ftd("CME", "12572Q105", "CME GROUP, INC", ["2008-02-01", "2008-10-01", "2009-06-01", "2010-03-01",
                                                      "2011-01-03", "2011-11-01", "2012-09-04", "2013-07-01",
                                                      "2014-05-01", "2015-07-01"], 500.0)
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "12572Q105"): _figi_answer("BBG000BHLYP4", "CME", "CME GROUP INC"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    assert [r["sec_id"] for r in read_table("securities", table_path(tmp_path, "securities"))] == ["BBG000BHLYP4"]
    flags = {r["review_flags"] for r in read_table("review", table_path(tmp_path, "review"))}
    assert "observation_unresolved" not in flags


# --- FIGI acceptance by ticker/name also takes the issuer's EDGAR names (spec §8.3) ---

def test_an_era_under_its_issuers_old_name_is_accepted_on_the_ticker_by_the_edgar_names(fake_edgar, tmp_path):
    """Real case: the snapshots list Northeast Utilities under ES from 2012 (a
    backfilled ticker; it traded as NU until its 2015 rename to Eversource), so
    SEC's fails rows under ES then are EnergySolutions' and the era has no FTD
    CUSIP of its own. OpenFIGI's ES answer is Bloomberg's line under today's
    name, EVERSOURCE ENERGY, which the observation name does not match; EDGAR
    lists NORTHEAST UTILITIES among the issuer's former names, so the era is
    accepted onto Eversource's FIGI: one security, no placeholder, and no
    rename delisting."""
    fake_edgar.company_map["ES"] = {"cik_str": 72741, "ticker": "ES", "title": "EVERSOURCE ENERGY"}
    fake_edgar.former_names[72741] = [("NORTHEAST UTILITIES", "1994-07-28", "2015-04-29"),
                                      ("NORTHEAST UTILITIES SYSTEM", "1996-11-27", "2004-11-30")]
    fake_edgar.submissions_by_cik[72741] = [EdgarSubmission("0000072741-02-000001", "10-K", "2002-03-01", "",
                                                            "", "k.htm")]
    obs = ([Observation("ES", d, "NORTHEAST UTILITIES") for d in ("2012-06-29", "2012-12-31", "2013-06-28",
                                                                   "2013-12-31", "2014-06-30")]
           + [Observation("ES", d, "EVERSOURCE ENERGY") for d in ("2015-06-30", "2015-12-31", "2016-06-30")])
    rows = (_ftd("ES", "292756202", "ENERGYSOLUTIONS INC. COM",
                 ["2012-06-01", "2012-09-04", "2012-12-03", "2013-03-01", "2013-05-21"], 3.9)
            + _ftd("ES", "30040W108", "EVERSOURCE ENERGY COM SHS",
                   ["2015-02-19", "2015-06-01", "2015-09-01", "2015-12-31", "2016-06-01"], 50.0))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "292756202"): _figi_answer("BBG000MTJYV2", "ES", "ENERGYSOLUTIONS INC"),
        ("ID_CUSIP", "30040W108"): _figi_answer("BBG000BQ87N0", "ES", "EVERSOURCE ENERGY"),
        ("TICKER", "ES"): _figi_answer("BBG000BQ87N0", "ES", "EVERSOURCE ENERGY"),
    })

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    secs = read_table("securities", table_path(tmp_path, "securities"))
    assert [(r["sec_id"], r["issuer_cik"]) for r in secs] == [("BBG000BQ87N0", "72741")]
    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    assert [(r["sec_id"], r["ticker"], r["valid_from"]) for r in th] == [("BBG000BQ87N0", "ES", "2012-06-29")]
    assert read_table("delistings", table_path(tmp_path, "delistings")) == []


def _holdco_run(fake_edgar, tmp_path, search=None, filings=()):
    """The HC holding-company reorganization below, run end to end."""
    fake_edgar.company_map["HC"] = {"cik_str": 999, "ticker": "HC", "title": "HOLDCO INC"}
    fake_edgar.submissions_by_cik[999] = list(filings)
    fake_edgar.listings[999] = [("HC", "NYSE")]
    if search is not None:
        fake_edgar.full_text_search = search
    obs = [Observation("HC", d, "HOLDCO INC", cik=999) for d in ("2014-06-30", "2014-12-31", "2015-12-31",
                                                                  "2016-06-30")]
    rows = (_ftd("HC", "111111101", "HOLDCO INC", ["2014-06-02", "2014-10-01", "2015-01-02", "2015-04-01",
                                                   "2015-06-12"])
            + _ftd("HC", "222222202", "HOLDCO INC NEW", ["2015-06-15", "2015-09-01", "2016-01-04", "2016-06-01"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "111111101"): _figi_answer("BBGHCOLD001", "HC", "HOLDCO INC"),
        ("ID_CUSIP", "222222202"): _figi_answer("BBGHCNEW001", "HC", "HOLDCO INC"),
        ("COMPOSITE_ID_BB_GLOBAL", "BBGHCNEW001"): {"data": [{"figi": "BBGHCNEW002", "compositeFIGI": "BBGHCNEW001",
                                                              "exchCode": "UN", "ticker": "HC", "name": "HOLDCO INC",
                                                              "securityType": "Common Stock"}]},
    })
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    return read_table("delistings", table_path(tmp_path, "delistings"))


def test_a_continuation_by_the_successor_issuers_8k12b_is_high_confidence(fake_edgar, tmp_path):
    hit = {"_source": {"ciks": ["0000000999"], "form": "8-K12B", "file_date": "2015-06-15",
                       "adsh": "0000000999-15-000042", "display_names": ["Holdco Inc (HC) (CIK 0000000999)"]}}
    asked = []

    def search(q, forms, lo, hi):
        asked.append((q, forms))
        return [hit]

    (d,) = _holdco_run(fake_edgar, tmp_path, search)
    assert ('"HOLDCO INC"', "8-K12B,8-K12G3") in asked
    assert (d["successor_sec_id"], d["confidence"]) == ("BBGHCNEW001", "high")
    assert "8-K12B 0000000999-15-000042" in d["reason"]


def test_a_continuation_by_the_successors_own_8k12b_when_the_search_finds_none(fake_edgar, tmp_path):
    filing = EdgarSubmission("0000000999-15-000042", "8-K12B", "2015-06-15", "", "", "x.htm")
    (d,) = _holdco_run(fake_edgar, tmp_path, lambda q, forms, lo, hi: [], filings=[filing])
    assert (d["successor_sec_id"], d["confidence"]) == ("BBGHCNEW001", "high")
    assert "8-K12B 0000000999-15-000042" in d["reason"]


def test_a_search_hit_means_the_filing_list_is_not_read_for_the_continuation(fake_edgar, tmp_path, monkeypatch):
    hit = {"_source": {"ciks": ["0000000999"], "form": "8-K12B", "file_date": "2015-06-15",
                       "adsh": "0000000999-15-000042", "display_names": ["Holdco Inc (HC) (CIK 0000000999)"]}}
    calls = []
    real = pipeline.own_continuation_filing
    monkeypatch.setattr(pipeline, "own_continuation_filing", lambda *a, **k: calls.append(a) or real(*a, **k))
    (d,) = _holdco_run(fake_edgar, tmp_path, lambda q, forms, lo, hi: [hit])
    assert calls == [] and d["successor_sec_id"] == "BBGHCNEW001"


def test_the_successors_own_8k12b_settles_a_continuation_with_no_full_text_search_at_all(fake_edgar, tmp_path):
    assert fake_edgar.full_text_search is None          # the fixture states the search absent
    filing = EdgarSubmission("0000000999-15-000042", "8-K12B", "2015-06-15", "", "", "x.htm")
    (d,) = _holdco_run(fake_edgar, tmp_path, filings=[filing])
    assert (d["successor_sec_id"], d["confidence"]) == ("BBGHCNEW001", "high")
    assert "8-K12B 0000000999-15-000042" in d["reason"]


def test_the_successors_filing_list_is_not_asked_when_the_old_issuer_carries_on(fake_edgar, tmp_path):
    """A (issuer 999) stops under HC and goes on as HX; B, another issuer's line (888) with an 8-K12B of its
    own, takes HC. The filing list must not make B a continuation of A."""
    fake_edgar.company_map["HC"] = {"cik_str": 999, "ticker": "HC", "title": "HOLDCO INC"}
    fake_edgar.company_map["HX"] = {"cik_str": 999, "ticker": "HX", "title": "HOLDCO INC"}
    fake_edgar.submissions_by_cik[999] = []
    fake_edgar.submissions_by_cik[888] = [EdgarSubmission("0000000888-15-000042", "8-K12B", "2015-06-15", "", "",
                                                          "x.htm")]
    fake_edgar.listings[999] = [("HC", "NYSE")]
    fake_edgar.listings[888] = [("HC", "NYSE")]
    obs = ([Observation("HC", d, "HOLDCO INC", cik=999) for d in ("2014-06-30", "2014-12-31")]
           + [Observation("HC", d, "NEWCO INC", cik=888) for d in ("2015-12-31", "2016-06-30")]
           + [Observation("HX", d, "HOLDCO INC", cik=999) for d in ("2015-12-31", "2016-06-30")])
    rows = (_ftd("HC", "111111101", "HOLDCO INC", ["2014-06-02", "2014-10-01", "2015-01-02", "2015-04-01",
                                                   "2015-06-12"])
            + _ftd("HC", "222222202", "NEWCO INC", ["2015-06-15", "2015-09-01", "2016-01-04", "2016-06-01"])
            + _ftd("HX", "333333303", "HOLDCO INC", ["2015-06-18", "2015-09-01", "2016-01-04", "2016-06-01"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "111111101"): _figi_answer("BBGHCOLD001", "HC", "HOLDCO INC"),
        ("ID_CUSIP", "222222202"): _figi_answer("BBGHCNEW001", "HC", "NEWCO INC"),
        ("ID_CUSIP", "333333303"): _figi_answer("BBGHXHOL001", "HX", "HOLDCO INC"),
    })
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    rows_out = read_table("delistings", table_path(tmp_path, "delistings"))
    assert not [r for r in rows_out if r["successor_sec_id"] == "BBGHCNEW001" or "8-K12B" in r["reason"]]


def test_a_continuation_the_finder_found_no_row_for_clips_the_old_line_at_its_last_sighting(fake_edgar, tmp_path):
    """Handoff plan, Task 6: a holding-company reorganization (MNST 2015's shape)
    that left no delisting row (no Form 25 the finder could place). The handoff
    pass writes the old line's exchange_transfer row with the new line as its
    successor and a zero return; the old line's HC range ends at its last
    sighting, the new line's range is untouched, and neither its
    ended_without_delisting nor a ticker_shared row is left."""
    fake_edgar.company_map["HC"] = {"cik_str": 999, "ticker": "HC", "title": "HOLDCO INC"}
    fake_edgar.submissions_by_cik[999] = []
    fake_edgar.listings[999] = [("HC", "NYSE")]
    obs = [Observation("HC", d, "HOLDCO INC", cik=999) for d in ("2014-06-30", "2014-12-31", "2015-12-31",
                                                                  "2016-06-30")]
    rows = (_ftd("HC", "111111101", "HOLDCO INC", ["2014-06-02", "2014-10-01", "2015-01-02", "2015-04-01",
                                                   "2015-06-12"])
            + _ftd("HC", "222222202", "HOLDCO INC NEW", ["2015-06-15", "2015-09-01", "2016-01-04", "2016-06-01"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "111111101"): _figi_answer("BBGHCOLD001", "HC", "HOLDCO INC"),
        ("ID_CUSIP", "222222202"): _figi_answer("BBGHCNEW001", "HC", "HOLDCO INC"),
        ("COMPOSITE_ID_BB_GLOBAL", "BBGHCNEW001"): {"data": [{"figi": "BBGHCNEW002", "compositeFIGI": "BBGHCNEW001",
                                                              "exchCode": "UN", "ticker": "HC", "name": "HOLDCO INC",
                                                              "securityType": "Common Stock"}]},
    })
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert (d["sec_id"], d["delist_date"], d["ticker"], d["bucket"], d["crsp_code"]) == (
        "BBGHCOLD001", "2015-06-13", "HC", "exchange_transfer", "304")
    assert (d["last_trade_date"], d["successor_sec_id"], d["ticker_successor_sec_id"]) == (
        "2015-06-12", "BBGHCNEW001", "")
    assert d["dlret"] == "0.000000" and d["confidence"] == "medium" and "timing:cik" in d["reason"]
    assert d["review_flags"].split(";")[0] == "handoff_continuation" and d["exchange"] == "NYSE"
    th = {(r["sec_id"], r["ticker"]): (r["valid_from"], r["valid_to"])
          for r in read_table("ticker_history", table_path(tmp_path, "ticker_history"))}
    assert th == {("BBGHCOLD001", "HC"): ("2014-06-02", "2015-06-12"), ("BBGHCNEW001", "HC"): ("2015-06-15", "")}
    review = read_table("review", table_path(tmp_path, "review"))
    assert not [r for r in review if r["review_flags"] in ("ended_without_delisting", "ticker_shared")]
    m = json.loads((tmp_path / "run_manifest.json").read_text())
    assert m["handoffs"] == {"handoffs": 1, "continuations_by_filing": 0, "continuations_by_timing": 1,
                             "takeovers": 0, "conflicts": 0, "rows_added": 1}


def test_a_handoff_continuation_clips_the_old_line_whose_ticker_the_issuer_still_lists(fake_edgar, tmp_path):
    """Task 13b (AON 2012): the old line's issuer (same CIK) still lists the ticker the new line took, so stage 5
    reads the old line as listed today and nothing clipped it (open TEST range, ticker_shared with the new line).
    The continuation row is created by the handoff stage; the successor starts are taken from the final
    delistings, and a security whose ticker its successor took is not listed under it: it is clipped at its last
    trade."""
    fake_edgar.company_map["HC"] = {"cik_str": 999, "ticker": "HC", "title": "HOLDCO INC"}
    fake_edgar.submissions_by_cik[999] = []
    fake_edgar.listings[999] = [("HC", "NYSE")]
    obs = [Observation("HC", d, "HOLDCO INC", cik=999) for d in ("2014-06-30", "2014-12-31", "2015-12-31",
                                                                  "2016-06-30")]
    rows = (_ftd("HC", "111111101", "HOLDCO INC", ["2014-06-02", "2014-10-01", "2015-01-02", "2015-04-01",
                                                   "2015-06-12"])
            + _ftd("HC", "222222202", "HOLDCO INC NEW", ["2015-06-15", "2015-09-01", "2016-01-04", "2016-06-01"]))
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "111111101"): _figi_answer("BBGHCOLD001", "HC", "HOLDCO INC"),
        ("ID_CUSIP", "222222202"): _figi_answer("BBGHCNEW001", "HC", "HOLDCO INC"),
        ("COMPOSITE_ID_BB_GLOBAL", "BBGHCOLD001"): {"data": [{"figi": "BBGHCOLD002", "compositeFIGI": "BBGHCOLD001",
                                                              "exchCode": "UN", "ticker": "HC", "name": "HOLDCO INC",
                                                              "securityType": "Common Stock"}]},
        ("COMPOSITE_ID_BB_GLOBAL", "BBGHCNEW001"): {"data": [{"figi": "BBGHCNEW002", "compositeFIGI": "BBGHCNEW001",
                                                              "exchCode": "UN", "ticker": "HC", "name": "HOLDCO INC",
                                                              "securityType": "Common Stock"}]},
    })
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["review_flags"].split(";")[0] == "handoff_continuation" and d["successor_sec_id"] == "BBGHCNEW001"
    th = {(r["sec_id"], r["ticker"]): (r["valid_from"], r["valid_to"])
          for r in read_table("ticker_history", table_path(tmp_path, "ticker_history"))}
    assert th == {("BBGHCOLD001", "HC"): ("2014-06-02", "2015-06-12"), ("BBGHCNEW001", "HC"): ("2015-06-15", "")}
    review = read_table("review", table_path(tmp_path, "review"))
    assert not [r for r in review if r["review_flags"] in ("ended_without_delisting", "ticker_shared")]


def test_run_writes_the_scorecard_of_the_tables_it_wrote(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    config = ScorecardConfig(window=Window("2006-01-02", "2024-12-29"))
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, scorecard=config)
    card = json.loads((tmp_path / "scorecard.json").read_text())
    m = card["metrics"]
    assert (m["L1.tickers"], m["L1.securities"], m["R1.1.sightings"], m["R2.endings"]) == (2, 2, 3, 1)
    assert card["window"] == {"start": "2006-01-02", "end": "2024-12-29"} and "R2.3.blank_dlret_in_window" in m
    # the same numbers scripts/scorecard.py computes from the written tables
    again = run_scorecard.build(RunSnapshot.read(tmp_path), config=config)
    assert card == {**json.loads(json.dumps(again)), "drops": []}


def test_the_verdicts_recomputed_from_the_written_folder_are_the_runs(fake_edgar, tmp_path):
    """Stage 10f's verdicts are a function of the run snapshot: the folder's (its tables and run_manifest.json's stage
    9g readings) gives the uncertain.csv the run wrote (the run has no placeholder, so no ticker evidence)."""
    index, clients = _clients(fake_edgar, extra_obs=[Observation("ZZZ", "2020-06-30", "ZED CO")])   # unresolved
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    written = RunSnapshot.read(tmp_path)
    assert written.uncertain
    assert formatted("uncertain", decide_verdicts(written, {}).uncertain_rows()) == written.uncertain


def test_run_reports_floor_drops_and_failing_golden_cases(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    golden = [TruthCase(case_id="AET", group="golden", ticker="AET", on="2017-06-30", issuer_cik="999", status="pass")]
    config = ScorecardConfig(floor={"G.pass": 1, "L1.coverage_tickers": 1.0}, golden=golden)
    logged = []
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=logged.append, scorecard=config)
    assert summary.scorecard_drops == ["G.pass: 1 -> 0"]               # coverage holds at 1.0
    assert summary.golden_failures == ["AET: issuer_cik 1122304 != 999"]
    assert "scorecard drop: G.pass: 1 -> 0" in logged


def test_a_limit_subset_is_never_compared_to_the_floor(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    config = ScorecardConfig(floor={"G.pass": 1})
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, limit=1, scorecard=config)
    assert summary.scorecard_drops == []
    assert json.loads((tmp_path / "scorecard.json").read_text())["drops"] == []


def test_every_run_writes_uncertain_csv(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert read_table("uncertain", table_path(tmp_path, "uncertain")) == []
    assert summary.uncertain == {"seed": 0, "security": 0, "ending": 0}


def test_a_sighting_after_the_ending_is_an_uncertain_seed_but_not_an_uncertain_security(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar, extra_obs=(Observation("AET", "2019-06-28", "AETNA INC", cik=1122304),))
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    rows = read_table("uncertain", table_path(tmp_path, "uncertain"))
    assert rows == [{"kind": "seed", "ticker": "AET", "sec_id": "BBG000FJLFX8", "date": "2019-06-28",
                     "reason": "outside_security_history", "candidates": ""}]
    assert summary.uncertain == {"seed": 1, "security": 0, "ending": 0}


class _SearchEdgar:
    """EDGAR whose full-text search answers `hits` (and records each query)."""

    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def full_text_search(self, q, forms, lo, hi, *, ciks=()):
        self.calls.append((q, tuple(ciks)))
        return self.hits


def test_ticker_evidence_asks_the_search_only_for_a_placeholder_without_a_ticker_tier():
    from delist_detection.outputs import manifest as run_manifest
    from delist_detection.identity.observations import TickerEra
    edgar = _SearchEdgar([{"_id": "a:d", "_source": {"ciks": ["0000000555"], "adsh": "0000000555-16-000001"}}])
    ctx = pipeline._RunContext(Clients(edgar=edgar, resolver=None, classifier=None, figi=None, ftd_client=None),
                               date(2026, 9, 25), lambda *_: None, 1, run_manifest.StageMeter(lambda *_: None))
    securities = {
        "CIK555-COMMON": Security("CIK555-COMMON", 555, "COMMON", "PHX CO", "", True, "placeholder",
                                  eras=[TickerEra("PHX", "2015-06-30", "2016-06-30")]),
        "CIK777-COMMON": Security("CIK777-COMMON", 777, "COMMON", "PIN CO", "", True, "placeholder",
                                  eras=[TickerEra("PIN", "2015-06-30", "2016-06-30")]),
        "BBGFIGI": Security("BBGFIGI", 888, "COMMON", "FIGI CO", "", True, "cusip",
                            eras=[TickerEra("FIG", "2015-06-30", "2016-06-30")]),
    }
    tiers = {"PHX@2015-06-30": "name_search", "PIN@2015-06-30": "cik_map"}
    assert pipeline._ticker_evidence(ctx, securities, lambda key: tiers.get(key, "")) == {
        "CIK555-COMMON": "filing:0000000555-16-000001", "CIK777-COMMON": "tier:cik_map"}
    assert edgar.calls == [('"PHX"', (555,))]


def test_price_answers_change_value_columns_only(fake_edgar, tmp_path):
    from delist_detection.outputs.price_requests import key_of
    index, clients = _clients(fake_edgar)
    first = tmp_path / "first"
    run(index, clients, Overrides(), out_dir=first, log=lambda *_: None)
    requests = read_table("price_requests", table_path(first, "price_requests"))
    ask = next(r for r in requests if r["sec_id"] == "BBG000FJLFX8" and r["kind"] == "last_close")
    answered = {key_of(ask): 191.32}
    index, clients = _clients(fake_edgar)
    second = tmp_path / "second"
    run(index, clients, Overrides(price_answers=answered), out_dir=second, log=lambda *_: None)
    aet = next(r for r in read_table("delistings", table_path(second, "delistings")) if r["sec_id"] == "BBG000FJLFX8")
    assert aet["last_trade_close"] == "191.320000"
    for name in ("securities", "ticker_history", "observation_map", "security_history", "seeds", "price_requests"):
        assert table_path(first, name).read_bytes() == table_path(second, name).read_bytes(), name


def test_an_answer_to_no_request_stops_the_run_before_anything_is_written(fake_edgar, tmp_path):
    from delist_detection.outputs.price_requests import PriceKey
    from delist_detection.outputs.reconstruction import OverrideFileError
    index, clients = _clients(fake_edgar)
    stray = {PriceKey("BBG000FJLFX8", "2001-01-02", "last_close", "AET", "2001-01-02"): 10.0}
    with pytest.raises(OverrideFileError, match="answer no request"):
        run(index, clients, Overrides(price_answers=stray), out_dir=tmp_path, log=lambda *_: None)
    assert not list(tmp_path.rglob("*.csv"))


def test_a_last_close_given_twice_stops_the_run(fake_edgar, tmp_path):
    from delist_detection.outputs.price_requests import key_of
    from delist_detection.outputs.reconstruction import OverrideFileError
    index, clients = _clients(fake_edgar)
    first = tmp_path / "first"
    run(index, clients, Overrides(), out_dir=first, log=lambda *_: None)
    ask = next(r for r in read_table("price_requests", table_path(first, "price_requests"))
               if r["sec_id"] == "BBG000FJLFX8" and r["kind"] == "last_close")
    index, clients = _clients(fake_edgar)
    with pytest.raises(OverrideFileError, match="both give the last close"):
        run(index, clients, Overrides(last_trade_closes={"BBG000FJLFX8": 190.0}, price_answers={key_of(ask): 191.32}),
            out_dir=tmp_path / "second", log=lambda *_: None)


def test_a_when_issued_observation_joins_its_regular_way_security(fake_edgar, tmp_path):
    """U8 (sub-plan 5a): EHAB-WI, seen once before the spin-off, is Enhabit's regular-way line: one security on
    EHAB's FIGI, no placeholder, and the caller's EHAB-WI observation mapped onto it."""
    fake_edgar.company_map["EHAB"] = {"cik_str": 1803737, "ticker": "EHAB", "title": "Enhabit, Inc."}
    fake_edgar.submissions_by_cik[1803737] = []
    fake_edgar.listings[1803737] = [("EHAB", "NYSE")]
    obs = [Observation("EHAB-WI", "2022-06-30", "ENHABIT INC WHEN ISSUED"),
           Observation("EHAB", "2022-12-31", "ENHABIT INC")]
    rows = _ftd("EHAB", "29332G102", "ENHABIT INC", ["2022-07-06", "2022-08-01", "2022-09-01", "2022-12-01"])
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "29332G102"): _figi_answer("BBG014QJ5BV6", "EHAB", "ENHABIT INC"),
        ("COMPOSITE_ID_BB_GLOBAL", "BBG014QJ5BV6"): {"data": [{"figi": "BBG014QJ5BV7", "compositeFIGI": "BBG014QJ5BV6",
                                                               "exchCode": "UN", "ticker": "EHAB",
                                                               "name": "ENHABIT INC"}]},
    })
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert [r["sec_id"] for r in read_table("securities", table_path(tmp_path, "securities"))] == ["BBG014QJ5BV6"]
    wi = next(r for r in read_table("observation_map", table_path(tmp_path, "observation_map"))
              if r["ticker"] == "EHAB-WI")
    assert (wi["sec_id"], wi["history_ticker"], wi["in_ticker_history"], wi["status"]) == (
        "BBG014QJ5BV6", "EHAB", "true", "mapped")


# --- sub-plan 5a, stage 4b: a line followed past the observations (line_follow.follow_lines, in a whole run) ---

LINE_F25 = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>New York Stock Exchange LLC</entityName>"
            "</exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
            "<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision></notificationOfRemoval>")
RS_OLD, RS_NEW = "11111A101", "11111A200"


def _weekly(start, n):
    """`n` Mondays from the Monday ISO `start`."""
    day = date.fromisoformat(start)
    return [(day + timedelta(weeks=i)).isoformat() for i in range(n)]


def _priced(symbol, cusip, desc, dates, first_price=10.0):
    return [FtdRow(d, cusip, symbol, desc, round(first_price + i * 0.01, 2)) for i, d in enumerate(dates)]


def _rs_new_rows(symbol="RS", until=91, desc="REVERSE SPLIT CO NEW"):
    """RS's new CUSIP: its first-day RSZZZZ row on 2012-09-25, then weekly rows from 2012-10-01 (91 weeks: to
    2014-06-16)."""
    return [FtdRow("2012-09-25", RS_NEW, "RSZZZZ", desc, 0.01),
            *_priced(symbol, RS_NEW, desc, _weekly("2012-10-01", until), 40.0)]


SPLIT_8K = EdgarSubmission("0000004242-12-000031", "8-K", "2012-09-24", "2012-09-24", "5.03,9.01", "k.htm")
LATER_10Q = EdgarSubmission("0000004242-13-000004", "10-Q", "2013-02-08", "2012-12-31", "", "q.htm")
MERGER_8K = EdgarSubmission("0000004242-14-000020", "8-K", "2014-06-10", "2014-06-10", "2.01,3.01,5.01,9.01", "m.htm")
MERGER_F25 = EdgarSubmission("0000876661-14-000300", "25-NSE", "2014-06-10", "", "", "primary_doc.xml")


def _line_run(fake_edgar, tmp_path, *, filings, figi, new_rows, old_figi=True, listings=(), id_baseline=(),
              extra_obs=()):
    """RS (CIK 4242), observed 2008-2009, its old CUSIP failing weekly under RS until 2012-09-17, then `new_rows`;
    `figi`: OpenFIGI's answers beyond the old CUSIP's (BBGRS01 unless `old_figi` is False)."""
    fake_edgar.company_map["RS"] = {"cik_str": 4242, "ticker": "RS", "title": "REVERSE SPLIT CO"}
    fake_edgar.submissions_by_cik[4242] = list(filings)
    fake_edgar.listings[4242] = list(listings)
    fake_edgar.raws["0000876661-14-000300"] = LINE_F25
    fake_edgar.texts["0000004242-14-000020"] = ("Item 3.01. trading suspended prior to the opening of trading on "
                                                "June 20, 2014 " + "x" * 300)
    obs = [Observation("RS", d, "REVERSE SPLIT CO", cik=4242) for d in ("2008-01-16", "2008-06-30", "2009-06-08")]
    rows = _priced("RS", RS_OLD, "REVERSE SPLIT CO", _weekly("2008-01-07", 247)) + list(new_rows)
    answers = dict(figi)
    if old_figi:
        answers[("ID_CUSIP", RS_OLD)] = _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO")
    index, clients = _index_clients(fake_edgar, [*obs, *extra_obs], rows, answers)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, id_baseline=id_baseline)
    return {name: read_table(name, table_path(tmp_path, name)) for name in (
        "securities", "cusip_history", "ticker_history", "delistings", "contract_delistings", "id_changes",
        "review_summary", "uncertain")}


def _flag_count(t, flag):
    return next((r["rows"] for r in t["review_summary"] if r["flag"] == flag), "0")


def test_a_reverse_split_after_the_observations_stop_is_followed_to_the_lines_real_ending(fake_edgar, tmp_path):
    """RS's observations stop in 2009; in 2012 a reverse split (8-K 5.03) gives it a new CUSIP under the same
    ticker, with the same composite; it merges in 2014, a Form 25 more than 400 days after the old CUSIP's last
    row. Followed, the line is one security with both CUSIPs, and its one delisting is the 2014 merger."""
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, LATER_10Q, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    assert [r["sec_id"] for r in t["securities"]] == ["BBGRS01"]
    assert [r["cusip"] for r in t["cusip_history"]] == [RS_OLD, RS_NEW]
    assert [(r["sec_id"], r["delist_date"], r["bucket"]) for r in t["delistings"]] == [
        ("BBGRS01", "2014-06-20", "merger")]
    assert [(r["ticker"], r["valid_from"], r["valid_to"]) for r in t["ticker_history"]] == [
        ("RS", "2008-01-07", "2014-06-19")]
    assert _flag_count(t, "line_followed") == "1"


def test_a_bankruptcy_before_the_switch_keeps_the_line_where_it_was(fake_edgar, tmp_path):
    """Must not change (UAL 2006): an 8-K item 1.03 within 180 days before the new CUSIP's first row means the
    plan cancelled the old shares; the new CUSIP is not the old line's."""
    bankrupt = EdgarSubmission("0000004242-12-000020", "8-K", "2012-06-01", "2012-06-01", "1.03", "b.htm")
    t = _line_run(fake_edgar, tmp_path, filings=[bankrupt, SPLIT_8K, LATER_10Q, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    assert [r["cusip"] for r in t["cusip_history"]] == [RS_OLD]
    assert "2014-06-20" not in {r["delist_date"] for r in t["delistings"]}
    assert _flag_count(t, "line_follow_refused") == "1"


def test_a_registrant_that_merged_out_at_the_switch_is_not_followed(fake_edgar, tmp_path):
    """Must not change (UNIT 2025, R1 before R2): no periodic report for a period after the switch."""
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    assert [r["cusip"] for r in t["cusip_history"]] == [RS_OLD]
    assert _flag_count(t, "line_follow_refused") == "1"


def test_a_new_cusip_another_issuers_security_holds_is_never_followed(fake_edgar, tmp_path):
    """Must not change (new LMCA 2013): another issuer's observed line holds the new CUSIP under the ticker."""
    fake_edgar.company_map["RSX"] = {"cik_str": 5353, "ticker": "RSX", "title": "OTHER CO"}
    fake_edgar.submissions_by_cik[5353] = []
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, LATER_10Q, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGOTHER1", "RS", "OTHER CO")},
                  new_rows=_rs_new_rows(desc="OTHER CO"),
                  extra_obs=[Observation("RS", d, "OTHER CO", cik=5353) for d in ("2013-06-28", "2013-12-31")])
    assert {r["sec_id"]: r["cusip"] for r in t["cusip_history"]} == {"BBGRS01": RS_OLD, "BBGOTHER1": RS_NEW}
    assert _flag_count(t, "line_followed") == "0"


def test_a_rename_on_the_same_cusip_keeps_a_placeholder_listed_under_its_new_ticker(fake_edgar, tmp_path):
    """A placeholder renamed on the same CUSIP (RS -> RSNW, as HSC became NVRI): its line ticker makes it listed
    today (EDGAR lists RSNW), so it has no ending and an open RSNW range."""
    rows = _priced("RSNW", RS_OLD, "REVERSE SPLIT CO", _weekly("2012-10-01", 700), 40.0)
    t = _line_run(fake_edgar, tmp_path, filings=[LATER_10Q], figi={}, new_rows=rows, old_figi=False,
                  listings=[("RSNW", "NYSE")])
    assert [r["sec_id"] for r in t["securities"]] == ["CIK4242-COMMON"]
    assert t["contract_delistings"] == []
    assert [(r["ticker"], r["valid_to"]) for r in t["ticker_history"]] == [("RS", "2012-09-30"), ("RSNW", "")]


LATER_10K = EdgarSubmission("0000004242-13-000011", "10-K", "2013-06-14", "2013-03-31", "", "k10.htm")


def test_a_figi_line_whose_new_cusip_has_its_own_figi_ends_as_a_continuation_to_it(fake_edgar, tmp_path):
    """U7 (DYN 2010, R2): the reverse split's new CUSIP has its own composite, so the old FIGI line ends at the
    switch, an exchange transfer whose successor is the new line, which the run adds as a security of its own."""
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, LATER_10Q, LATER_10K],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    assert {(r["sec_id"], r["observed"]) for r in t["securities"]} == {("BBGRS01", "true"), ("BBGRSNEW1", "false")}
    [d] = t["delistings"]
    assert (d["sec_id"], d["bucket"], d["successor_sec_id"]) == ("BBGRS01", "exchange_transfer", "BBGRSNEW1")
    assert "successor by line follow" in d["reason"]
    [c] = t["contract_delistings"]
    assert (c["sec_id"], c["continuation"], c["successor_sec_id"]) == ("BBGRS01", "true", "BBGRSNEW1")
    assert ("BBGRSNEW1", "RS", "2012-09-25") in {(r["sec_id"], r["ticker"], r["valid_from"])
                                                 for r in t["ticker_history"]}


def test_an_unknown_form25_at_the_lines_switch_becomes_the_continuation(fake_edgar, tmp_path):
    """U7 (GTES 2026): the Form 25 filed at a redomicile that gave the line a CUSIP with its own composite was
    classified `unknown`; with the line successor it is the exchange transfer to it."""
    switch_f25 = EdgarSubmission("0000876661-12-000300", "25-NSE", "2012-09-24", "", "", "primary_doc.xml")
    fake_edgar.raws["0000876661-12-000300"] = LINE_F25
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, switch_f25, LATER_10Q],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    [d] = t["delistings"]
    assert (d["bucket"], d["crsp_code"], d["successor_sec_id"]) == ("exchange_transfer", "304", "BBGRSNEW1")
    # no_evidence_default went with the `unknown` kind; the others are info on an exchange transfer. Nothing states
    # the last trade, so the exchange's Form 25 day is the worked-out one (5d rule 4: closing_day, unconfirmed)
    assert d["review_flags"].split(";") == ["last_trade_date_unconfirmed", "ftd_close_prior:1", "line_continuation"]
    assert (d["last_trade_date"], d["last_trade_date_source"]) == ("2012-09-24", "closing_day")
    assert d["confidence"] == "medium"
    assert t["contract_delistings"][0]["continuation"] == "true"
    assert not [u for u in t["uncertain"] if u["kind"] == "ending"]


def _unit_delisting(sec_id, bucket, code, flags):
    from types import SimpleNamespace
    record = DelistRecord(ticker="RS", cik=4242, observed_delist_date="2012-09-24", crsp_code=code, bucket=bucket,
                          confidence="high", reason="r", evidence={"flags": list(flags)}, sec_id=sec_id,
                          delist_date="2012-10-04")
    return Delisting(sec_id, 4242, "RS", "2012-10-04", record, LastTrade(date(2012, 9, 24), "notice_a", ()),
                     None, None, "NYSE")


def _line_successor(sec_id):
    from delist_detection.identity.figi_resolution import FigiCandidate
    from delist_detection.identity.line_follow import LineStep, LineSuccessor
    step = LineStep(sec_id, "switch", RS_OLD, RS_NEW, "RS", "2012-09-17", "2012-09-25")
    return LineSuccessor(sec_id, "BBGRSNEW1", FigiCandidate("BBGRSNEW1", "REVERSE SPLIT CO", "RS", "Common Stock", ()),
                         step, "8-K 2012-09-24")


@pytest.mark.parametrize("bucket,code", [(CrspBucket.LIQUIDATION, 450), (CrspBucket.COMPLIANCE_FAILURE, 560),
                                         (CrspBucket.EXPIRATION, 600), (CrspBucket.MERGER, 231)])
def test_distress_expiration_and_merger_endings_at_the_switch_take_no_line_successor(bucket, code):
    from delist_detection.sources.ftd import FtdIndex
    d = _unit_delisting("BBGRS01", bucket, code, [])
    securities = {"BBGRS01": Security("BBGRS01", 4242, "COMMON", "REVERSE SPLIT CO", "", True, "cusip")}
    found = pipeline._Successors()
    pipeline._line_successor_links([d], securities, {}, {"BBGRS01": _line_successor("BBGRS01")}, FtdIndex(), found)
    assert found.links == {} and found.added == {} and found.rebucketed == {}


def test_a_delisting_without_a_line_link_still_gets_the_in_run_successor_search():
    from types import SimpleNamespace
    from delist_detection.outputs import manifest as run_manifest
    from delist_detection.identity.history import Sighting
    no_search = SimpleNamespace(full_text_search=None)          # EDGAR stating its full-text search absent
    ctx = pipeline._RunContext(Clients(edgar=no_search, resolver=None, classifier=None, figi=None, ftd_client=None),
                               date(2026, 9, 25), lambda *_: None, 1, run_manifest.StageMeter(lambda *_: None))
    on_line = _unit_delisting("BBGRS01", CrspBucket.EXCHANGE_TRANSFER, 304, ["successor_unknown"])
    other = _unit_delisting("BBGOTH1", CrspBucket.EXCHANGE_TRANSFER, 304, ["successor_unknown"])
    securities = {sid: Security(sid, 4242, "COMMON", "CO", "", True, "cusip") for sid in ("BBGRS01", "BBGOTH1")}
    securities["BBGNEW2"] = Security("BBGNEW2", 4242, "COMMON", "CO", "", True, "cusip")
    sightings = {"BBGNEW2": [Sighting("2012-09-26", "RS", "observation")]}
    found = pipeline._find_successors(ctx, [on_line, other], securities, sightings, {},
                                      {"BBGRS01": _line_successor("BBGRS01")})
    assert found.links == {on_line.key: ("BBGRSNEW1", "line_follow"), other.key: ("BBGNEW2", "same_issuer")}


def test_a_line_successor_is_never_added_for_an_ending_that_does_not_need_it(fake_edgar, tmp_path):
    """Must not change (WCN, AAN): a merger at the switch keeps its kind and takes no line successor, and the
    composite is not added to the run."""
    merger_8k = EdgarSubmission("0000004242-12-000040", "8-K", "2012-09-24", "2012-09-24", "2.01,3.01,5.01,9.01",
                                "m.htm")
    merger_f25 = EdgarSubmission("0000876661-12-000300", "25-NSE", "2012-09-24", "", "", "primary_doc.xml")
    fake_edgar.raws["0000876661-12-000300"] = LINE_F25
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, merger_8k, merger_f25, LATER_10Q],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    [d] = t["delistings"]
    assert (d["bucket"], d["successor_sec_id"]) == ("merger", "")
    assert "BBGRSNEW1" not in {r["sec_id"] for r in t["securities"]}


def test_a_placeholder_folds_into_the_figi_line_its_new_cusip_names(fake_edgar, tmp_path):
    """R2 for a placeholder: OpenFIGI knows no US line for the old CUSIP but names one for the new: the
    placeholder becomes that FIGI line, and contract/id_changes.csv says so by name."""
    baseline = [{"sec_id": "CIK4242-COMMON", "issuer_cik": "4242", "share_class": "COMMON", "name": "RS",
                 "security_type": "", "observed": "true", "figi_source": "placeholder"}]
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, LATER_10Q, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows(), old_figi=False, id_baseline=baseline)
    assert [(r["sec_id"], r["figi_source"]) for r in t["securities"]] == [("BBGRSNEW1", "handoff")]
    assert [(r["old_sec_id"], r["new_sec_id"]) for r in t["id_changes"]] == [("CIK4242-COMMON", "BBGRSNEW1")]
    assert [(r["sec_id"], r["delist_date"]) for r in t["delistings"]] == [("BBGRSNEW1", "2014-06-20")]
    assert (_flag_count(t, "no_figi"), _flag_count(t, "line_followed")) == ("0", "1")    # its items moved with it


def test_a_form25_at_the_lines_own_switch_while_it_trades_on_leaves_no_ending(fake_edgar, tmp_path):
    """QGEN 2026 / Acxiom 2018 (U6): the line, listed today, switched to a new CUSIP of the same composite as a
    25-NSE removed the old one; that Form 25 is no delisting."""
    switch_f25 = EdgarSubmission("0000876661-12-000300", "25-NSE", "2012-09-24", "", "", "primary_doc.xml")
    fake_edgar.raws["0000876661-12-000300"] = LINE_F25
    listed = {"data": [{"figi": "BBGRS02", "compositeFIGI": "BBGRS01", "exchCode": "UN", "ticker": "RS",
                        "name": "REVERSE SPLIT CO"}]}
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, switch_f25, LATER_10Q],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO"),
                        ("COMPOSITE_ID_BB_GLOBAL", "BBGRS01"): listed},
                  new_rows=_rs_new_rows(until=700), listings=[("RS", "NYSE")])
    assert t["delistings"] == [] and t["contract_delistings"] == []


def test_openfigi_unavailable_in_stage_4b_stops_the_run_and_writes_nothing(fake_edgar, tmp_path):
    """The new CUSIP's OpenFIGI answer is first asked by the line follow; no placeholder stands in for it."""
    from delist_detection.sources.openfigi import OpenFigiUnavailable

    class _Down(_MapFigi):
        def map(self, jobs, use_cache=True):
            if any(j["idValue"] == RS_NEW for j in jobs):
                raise OpenFigiUnavailable("down")
            return super().map(jobs, use_cache)

    fake_edgar.company_map["RS"] = {"cik_str": 4242, "ticker": "RS", "title": "REVERSE SPLIT CO"}
    fake_edgar.submissions_by_cik[4242] = [SPLIT_8K, LATER_10Q, MERGER_8K, MERGER_F25]
    obs = [Observation("RS", d, "REVERSE SPLIT CO", cik=4242) for d in ("2008-01-16", "2008-06-30", "2009-06-08")]
    rows = _priced("RS", RS_OLD, "REVERSE SPLIT CO", _weekly("2008-01-07", 247)) + _rs_new_rows()
    answers = {("ID_CUSIP", RS_OLD): _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO")}
    index, clients = _index_clients(fake_edgar, obs, rows, answers)
    clients.figi = _Down(answers)
    with pytest.raises(OpenFigiUnavailable):
        run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert not list(tmp_path.glob("*.csv"))


# --- sub-plan 5b, R5: the one other CIK in force over a security's whole span ---

def _in_force_run(subs, exact):
    """A run context whose EDGAR answers `subs` (CIK -> submissions JSON) and whose issuer record's name index
    lists `exact` (name -> CIKs)."""
    from types import SimpleNamespace
    from delist_detection.outputs import manifest as run_manifest
    from delist_detection.identity.issuer_record import IssuerRecord
    index = SimpleNamespace(split_search=lambda name: ([SimpleNamespace(cik=c) for c in exact.get(name, [])], []))
    edgar = SimpleNamespace(submissions=lambda cik: subs.get(cik))
    clients = SimpleNamespace(edgar=edgar, issuers=IssuerRecord(edgar, name_index=index))
    return pipeline._RunContext(clients, date(2026, 9, 25), lambda *_: None, 1, run_manifest.StageMeter(lambda *_: None))


def _security_with_era(sec_id, cik, ticker, observations):
    from delist_detection.identity.observations import TickerEra
    from delist_detection.identity.security_master import EraResolution, Issuer
    era = TickerEra(ticker, observations[0].as_of, observations[-1].as_of, observations)
    s = Security(sec_id, cik, "COMMON", observations[-1].name, "Common Stock", True, "cusip", eras=[era])
    return s, era, {era.key: EraResolution(era.key, sec_id, "cusip", None, ())}, {era.key: Issuer(cik, ())}


HRG = {"name": "SPECTRUM BRANDS HOLDINGS, INC.",
       "formerNames": [{"name": "HRG GROUP, INC.", "from": "2014-01-01T00:00:00.000Z", "to": "2018-07-13T00:00:00.000Z"},
                       {"name": "HARBINGER GROUP INC.", "from": "2009-12-14T00:00:00.000Z",
                        "to": "2014-01-01T00:00:00.000Z"}]}
OLD_SPB = {"name": "SB/RH HOLDINGS, LLC",
           "formerNames": [{"name": "SPECTRUM BRANDS HOLDINGS, INC.", "from": "2010-06-16T00:00:00.000Z",
                            "to": "2018-07-13T00:00:00.000Z"}]}


def test_the_one_other_cik_in_force_on_every_sighting_is_read_too():
    """Spectrum Brands 2010-2018: today's CIK 109177 was Harbinger/HRG Group then; the old Spectrum Brands (CIK
    1487730) carried the observed name on every sighting."""
    obs = [Observation("SPB", d, "SPECTRUM BRANDS HOLDINGS INC") for d in ("2010-06-30", "2014-06-30", "2018-06-29")]
    s, era, resolutions, issuers = _security_with_era("BBG000P4BQM9", 109177, "SPB", obs)
    ctx = _in_force_run({109177: HRG, 1487730: OLD_SPB}, {"SPECTRUM BRANDS HOLDINGS INC": [109177, 1487730]})
    assert pipeline._other_issuers(ctx, [era], resolutions, issuers, {s.sec_id: s}) == {"BBG000P4BQM9": 1487730}


def test_an_issuer_that_changed_within_the_span_or_never_changed_gives_no_other_cik():
    """Perrigo: the old Perrigo Company (CIK 820096) until 2013, then Perrigo plc (its own CIK 1585364): two CIKs in
    force, so none is read (reading 820096 would give listed PRGO a 2013 row). A security whose own CIK carried
    the name throughout has none either."""
    plc = {"name": "Perrigo Co plc",
           "formerNames": [{"name": "BLISFIELD LTD", "from": "2012-01-01T00:00:00.000Z",
                            "to": "2013-08-27T00:00:00.000Z"}]}
    obs = [Observation("PRGO", "2012-06-29", "PERRIGO CO"), Observation("PRGO", "2015-06-30", "PERRIGO CO PLC")]
    s, era, resolutions, issuers = _security_with_era("BBG000CNFQW6", 1585364, "PRGO", obs)
    ctx = _in_force_run({1585364: plc, 820096: {"name": "PERRIGO CO", "formerNames": []}},
                        {"PERRIGO CO": [820096, 1585364]})
    assert pipeline._other_issuers(ctx, [era], resolutions, issuers, {s.sec_id: s}) == {}
    s, era, resolutions, issuers = _security_with_era("BBG_PLAIN", 777, "PLN", [Observation("PLN", "2015-06-30",
                                                                                             "PLAIN CO")])
    ctx = _in_force_run({777: {"name": "PLAIN CO"}}, {"PLAIN CO": [777]})
    assert pipeline._other_issuers(ctx, [era], resolutions, issuers, {s.sec_id: s}) == {}


def test_a_failed_read_of_a_submissions_file_in_the_other_issuer_stage_degrades_the_security():
    """Final review M4: the other CIK's failed read dropped R5 with no row; it is now a `resolution_degraded` row."""
    import requests
    obs = [Observation("SPB", d, "SPECTRUM BRANDS HOLDINGS INC") for d in ("2010-06-30", "2014-06-30", "2018-06-29")]
    s, era, resolutions, issuers = _security_with_era("BBG000P4BQM9", 109177, "SPB", obs)
    ctx = _in_force_run({109177: HRG, 1487730: OLD_SPB}, {"SPECTRUM BRANDS HOLDINGS INC": [109177, 1487730]})

    def submissions(cik):
        if cik == 1487730:
            raise requests.ConnectionError("down")
        return HRG
    ctx.clients.edgar.submissions = submissions
    review = []
    assert pipeline._other_issuers(ctx, [era], resolutions, issuers, {s.sec_id: s}, review) == {}
    assert [(r.sec_id, r.flag) for r in review] == [("BBG000P4BQM9", "resolution_degraded")]

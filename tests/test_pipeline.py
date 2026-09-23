import csv
from datetime import date
from pathlib import Path

import pytest

from delist_detection.classifier import DelistClassifier
from delist_detection.edgar import EdgarBlocked, EdgarSubmission
from delist_detection.ftd import FtdRow
from delist_detection.observations import Observation, ObservationIndex
from delist_detection.pipeline import Clients, Overrides, _own_last_seen, run, successor_from_8k12b
from delist_detection.security_master import Security
from delist_detection.store import read_table, table_path
from delist_detection.ticker_resolver import TickerResolver

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


def _clients(fake_edgar, ftd_rows=None):
    fake_edgar.submissions_by_cik[1122304] = [
        EdgarSubmission("0000876661-18-001269", "25-NSE", "2018-11-29", "", "", "primary_doc.xml"),
        EdgarSubmission("0001122304-18-000178", "8-K", "2018-11-28", "2018-11-28", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("0001122304-18-000184", "15-12B", "2018-12-10", "", "", "f.htm"),
    ]
    fake_edgar.submissions_by_cik[777] = []
    fake_edgar.company_map["AET"] = {"cik_str": 1122304, "ticker": "AET", "title": "AETNA INC /PA/"}
    fake_edgar.company_map["LIVE"] = {"cik_str": 777, "ticker": "LIVE", "title": "LIVE CO"}
    fake_edgar.raws["0000876661-18-001269"] = AET_RAW
    fake_edgar.texts["0001122304-18-000178"] = ("Item 3.01 Notice. trading suspended prior to the opening of trading "
                                                "on November 29, 2018 " + "x" * 300)
    ftd = _FtdClient()
    if ftd_rows is not None:
        ftd.ROWS = ftd_rows
    obs = [Observation("AET", "2017-06-30", "AETNA INC", cik=1122304),
           Observation("AET", "2018-06-29", "AETNA INC", cik=1122304),
           Observation("LIVE", "2025-06-30", "LIVE CO", cik=777)]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, member_names=index.name_on, cik_map=index.cik_pin_on)
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


def test_missing_close_leaves_blank_dlret_and_review(fake_edgar, tmp_path):
    rows = [FtdRow("2018-06-29", "00817Y108", "AET", "AETNA INC.(NEW)", 180.0),
            FtdRow("2018-07-02", "00817Y108", "AET", "AETNA INC.(NEW)", 181.0)]    # nothing after the last trade
    index, clients = _clients(fake_edgar, ftd_rows=rows)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["last_trade_close"] == "" and d["dlret"] == ""
    assert "no_last_close" in d["review_flags"]
    review = read_table("review", table_path(tmp_path, "review"))
    assert any(r["sec_id"] == "BBG000FJLFX8" and "no_last_close" in r["review_flags"] for r in review)


def test_unmatched_override_stops_before_writing(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    with pytest.raises(ValueError, match="BBG999"):
        run(index, clients, Overrides(last_trade_closes={"BBG999": 1.0}), out_dir=tmp_path, log=lambda *_: None)
    assert not list(tmp_path.glob("*.csv"))


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


def test_successor_from_8k12b():
    hits = [{"_source": {"ciks": ["0001288776"], "display_names": ["GOOGLE INC.  (GOOG)  (CIK 0001288776)"]}},
            {"_source": {"ciks": ["0001652044"], "display_names": ["Alphabet Inc.  (GOOGL, GOOG)  (CIK 0001652044)"]}}]
    got = successor_from_8k12b(lambda q, forms, lo, hi: hits, None, name="GOOGLE INC", day=date(2015, 10, 2),
                               exclude_cik=1288776)
    assert got == (1652044, "GOOGL")
    assert successor_from_8k12b(lambda *a: [], None, name="X", day=date(2015, 10, 2), exclude_cik=1) is None


def test_own_last_seen_ignores_an_otc_tail_under_another_symbol():
    """A bankrupt XYZ's CUSIP keeps showing up in FTD data under the OTC symbol
    XYZQ after the real delisting; last_seen must stay at the last sighting
    under the security's own era ticker(s), not the later OTC-tail date."""
    from delist_detection.observations import TickerEra

    era = TickerEra("XYZ", "2020-01-01", "2020-06-15", [])
    sec = Security("BBGXYZ", 555, "COMMON", "XYZ CORP", "Common Stock", True, "cusip", eras=[era])
    sig = [
        ("2020-01-01", "XYZ", "observation"),
        ("2020-06-15", "XYZ", "observation"),
        ("2020-07-01", "XYZQ", "ftd"),        # post-delisting OTC tail, later than the real last sighting
        ("2020-09-01", "XYZQ", "ftd"),
    ]
    assert _own_last_seen(sec, sig) == "2020-06-15"


def test_own_last_seen_falls_back_to_era_end_with_no_own_ticker_sighting():
    from delist_detection.observations import TickerEra

    era = TickerEra("XYZ", "2020-01-01", "2020-06-15", [])
    sec = Security("BBGXYZ", 555, "COMMON", "XYZ CORP", "Common Stock", True, "cusip", eras=[era])
    assert _own_last_seen(sec, []) == "2020-06-15"

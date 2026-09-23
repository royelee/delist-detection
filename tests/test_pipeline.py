from datetime import date
from pathlib import Path

import pytest

import delist_detection.pipeline as pipeline
from delist_detection.classifier import DelistClassifier, DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import DelistingEvent, DelistingFinder
from delist_detection.edgar import EdgarBlocked, EdgarSubmission
from delist_detection.ftd import FtdRow
from delist_detection.last_trade import LastTrade
from delist_detection.observations import Observation, ObservationIndex
from delist_detection.pipeline import (
    Clients, Overrides, _issuer_exchange_for_ticker, _merge_review_rows, _own_last_seen,
    _ticker_range_review, run, successor_from_8k12b,
)
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


# --- item 3: successor_from_8k12b resolves the matching-share-class candidate ---

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


# --- item 2: added (acquirer/successor) securities get a real ticker_history row ---

def test_run_writes_an_open_acquirer_ticker_history_row(fake_edgar, tmp_path):
    """A cash+stock merger term resolves an acquirer that is listed today; its
    ticker_history row must be built directly (ranges_from_sightings would
    otherwise silently drop it as a single-value FTD sighting)."""
    index, clients = _clients(fake_edgar)
    fake_edgar.company_map["ACQ"] = {"cik_str": 9999, "ticker": "ACQ", "title": "ACQUIRER INC"}
    fake_edgar.submissions_by_cik[9999] = [EdgarSubmission("X1", "10-K", "2010-01-01", "", "", "x.htm")]
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
    ev = DelistingEvent(sec_id="BBG000FJLFX8", cik=1122304, ticker="AET", delist_date="2018-12-09", record=record,
                        last_trade=LastTrade(date(2018, 11, 28), "notice_a", ()), form25=None, form25_sub=None,
                        exchange="NYSE", flags=["successor_unknown"])

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return ([ev], []) if ctx.security.sec_id == "BBG000FJLFX8" else ([], [])

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)

    hit = {"_source": {"ciks": ["8888"], "display_names": ["SUCCESSOR CO  (SUX)  (CIK 0000008888)"],
                       "file_date": "2018-12-15"}}
    fake_edgar.full_text_search = lambda q, forms, lo, hi: [hit]
    clients.figi.answers[("TICKER", "SUX")] = _figi_answer("BBGSUX00001", "SUX", "SUCCESSOR CO")
    clients.figi.answers[("COMPOSITE_ID_BB_GLOBAL", "BBGSUX00001")] = {
        "data": [{"figi": "BBGSUX00001", "compositeFIGI": "BBGSUX00001", "exchCode": "UN", "ticker": "SUX",
                  "name": "SUCCESSOR CO"}]}

    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    suc = [r for r in th if r["sec_id"] == "BBGSUX00001"]
    assert len(suc) == 1
    assert suc[0]["ticker"] == "SUX" and suc[0]["source"] == "edgar_8k"
    assert suc[0]["valid_from"] == "2018-12-15" and suc[0]["valid_to"] == ""
    d = read_table("delistings", table_path(tmp_path, "delistings"))[0]
    assert d["successor_sec_id"] == "BBGSUX00001"


# --- item 9: an unconfirmed last trade day still clips the ranges at delist_date ---

def test_ticker_history_clips_at_delist_date_when_last_trade_day_is_unconfirmed(fake_edgar, tmp_path, monkeypatch):
    index, clients = _clients(fake_edgar)
    record = DelistRecord(ticker="AET", cik=1122304, observed_delist_date="2018-11-28", crsp_code=470,
                          bucket=CrspBucket.LIQUIDATION, confidence="low", reason="x",
                          evidence={"flags": []}, sec_id="BBG000FJLFX8", delist_date="2018-12-09")
    ev = DelistingEvent(sec_id="BBG000FJLFX8", cik=1122304, ticker="AET", delist_date="2018-12-09", record=record,
                        last_trade=LastTrade(None, "", ("last_trade_date_unconfirmed",)), form25=None,
                        form25_sub=None, exchange="", flags=[])

    class _CannedFinder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            return ([ev], []) if ctx.security.sec_id == "BBG000FJLFX8" else ([], [])

    monkeypatch.setattr(pipeline, "DelistingFinder", _CannedFinder)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    th = read_table("ticker_history", table_path(tmp_path, "ticker_history"))
    aet = [r for r in th if r["sec_id"] == "BBG000FJLFX8"]
    assert aet[0]["valid_to"] == "2018-12-09"      # clipped at delist_date, not left at a raw last sighting


# --- item 6: run() builds the SecurityContext correctly ---

def test_run_builds_last_seen_and_seen_after_from_the_right_sightings(fake_edgar, tmp_path, monkeypatch):
    rows = list(_FtdClient.ROWS) + [FtdRow("2019-06-01", "00817Y108", "AETQ", "AETNA INC OTC PINK", 0.05)]
    index, clients = _clients(fake_edgar, ftd_rows=rows)

    contexts = {}

    class _Recorder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            contexts[ctx.security.sec_id] = ctx
            return [], []

    monkeypatch.setattr(pipeline, "DelistingFinder", _Recorder)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    ctx = contexts["BBG000FJLFX8"]
    assert ctx.last_seen == "2018-11-29"           # last AET-labeled sighting, not the later OTC row
    assert ctx.seen_after("2019-01-01") is True    # the OTC row is still visible to seen_after
    assert ctx.seen_after("2019-12-31") is False


def test_run_builds_sibling_spans_for_every_security_of_the_issuer(fake_edgar, tmp_path, monkeypatch):
    """Two share classes of one issuer must each see the other's sighting span
    in SecurityContext.sibling_spans, keyed by sec_id."""
    fake_edgar.company_map["AAA"] = {"cik_str": 9001, "ticker": "AAA", "title": "DUAL CLASS CO"}
    fake_edgar.company_map["BBB"] = {"cik_str": 9001, "ticker": "BBB", "title": "DUAL CLASS CO"}
    fake_edgar.submissions_by_cik[9001] = []

    figi = _SuccessorFigi({
        "AAA": _figi_answer("BBGAAA00001", "AAA", "DUAL CLASS CO"),
        "BBB": _figi_answer("BBGBBB00001", "BBB", "DUAL CLASS CO"),
        "BBGAAA00001": {"data": [{"figi": "BBGAAA00001", "compositeFIGI": "BBGAAA00001", "exchCode": "UN",
                                  "ticker": "AAA", "name": "DUAL CLASS CO"}]},
        "BBGBBB00001": {"data": [{"figi": "BBGBBB00001", "compositeFIGI": "BBGBBB00001", "exchCode": "UN",
                                  "ticker": "BBB", "name": "DUAL CLASS CO"}]},
    })

    class _FtdEmpty:
        def urls_for(self, lo, hi):
            return []

        def rows(self, url, *, symbols=None, cusips=None):
            return iter(())

    obs = [Observation("AAA", "2020-01-01", "DUAL CLASS CO", cik=9001),
           Observation("AAA", "2020-06-01", "DUAL CLASS CO", cik=9001),
           Observation("BBB", "2020-02-01", "DUAL CLASS CO", cik=9001),
           Observation("BBB", "2020-07-01", "DUAL CLASS CO", cik=9001)]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, member_names=index.name_on, cik_map=index.cik_pin_on)
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=figi, ftd_client=_FtdEmpty())

    contexts = {}

    class _Recorder:
        def __init__(self, edgar, classifier, *, midas=None, halts=None):
            pass

        def find(self, ctx):
            contexts[ctx.security.sec_id] = ctx
            return [], []

    monkeypatch.setattr(pipeline, "DelistingFinder", _Recorder)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)

    aaa_ctx = contexts["BBGAAA00001"]
    assert set(aaa_ctx.sibling_spans) == {"BBGAAA00001", "BBGBBB00001"}
    assert aaa_ctx.sibling_spans["BBGAAA00001"] == ("2020-01-01", "2020-06-01")
    assert aaa_ctx.sibling_spans["BBGBBB00001"] == ("2020-02-01", "2020-07-01")


# --- item 10: an open ticker_history row's exchange comes from EDGAR's own submissions ---

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


# --- item 11: a per-security failure that isn't EdgarBlocked/OpenFigiBlocked is logged, not fatal ---

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


# --- item 8: ticker_history overlap review, without changing the ranges ---

def test_ticker_range_review_flags_overlap_within_one_security():
    rows = [
        {"sec_id": "S1", "ticker": "AAA", "valid_from": "2020-01-01", "valid_to": "2020-06-01"},
        {"sec_id": "S1", "ticker": "BBB", "valid_from": "2020-03-01", "valid_to": None},
    ]
    items = _ticker_range_review(rows)
    assert len(items) == 1
    assert items[0].flag == "ticker_range_overlap" and items[0].sec_id == "S1"
    assert "AAA" in items[0].reason and "BBB" in items[0].reason


def test_ticker_range_review_flags_a_ticker_shared_by_two_securities():
    rows = [
        {"sec_id": "S1", "ticker": "AAA", "valid_from": "2020-01-01", "valid_to": "2020-06-01"},
        {"sec_id": "S2", "ticker": "AAA", "valid_from": "2020-03-01", "valid_to": None},
    ]
    items = _ticker_range_review(rows)
    assert len(items) == 1
    assert items[0].flag == "ticker_shared"
    assert "S1" in items[0].reason and "S2" in items[0].reason


def test_ticker_range_review_ignores_non_overlapping_ranges():
    rows = [
        {"sec_id": "S1", "ticker": "AAA", "valid_from": "2020-01-01", "valid_to": "2020-06-01"},
        {"sec_id": "S1", "ticker": "BBB", "valid_from": "2020-06-02", "valid_to": None},
    ]
    assert _ticker_range_review(rows) == []


# --- item 13b: duplicate review rows are merged, joining reasons ---

def test_merge_review_rows_joins_reasons_for_the_same_key():
    rows = [
        {"sec_id": "S1", "delist_date": "2020-01-01", "ticker": "AAA", "review_flags": "error", "reason": "boom",
         "cik": 1},
        {"sec_id": "S1", "delist_date": "2020-01-01", "ticker": "AAA", "review_flags": "error", "reason": "bang",
         "cik": None},
    ]
    merged = _merge_review_rows(rows)
    assert len(merged) == 1
    assert merged[0]["reason"] == "boom; bang"
    assert merged[0]["cik"] == 1                    # the first non-empty value is kept


def test_merge_review_rows_leaves_distinct_keys_alone():
    rows = [
        {"sec_id": "S1", "delist_date": "2020-01-01", "ticker": "AAA", "review_flags": "error", "reason": "boom"},
        {"sec_id": "S2", "delist_date": "2020-01-01", "ticker": "BBB", "review_flags": "error", "reason": "bang"},
    ]
    assert _merge_review_rows(rows) == rows


# --- item 10 helper, unit-level ---

def test_issuer_exchange_for_ticker_reads_the_parallel_arrays(fake_edgar):
    fake_edgar.company_map["X"] = {"cik_str": 1, "ticker": "X", "title": "X CO"}
    fake_edgar.submissions_by_cik[1] = []
    fake_edgar.submissions = lambda cik, fresh_after=None: (
        {"tickers": ["X"], "exchanges": ["NYSE"]} if cik == 1 else {"tickers": [], "exchanges": []}
    )
    assert _issuer_exchange_for_ticker(fake_edgar, 1, "X") == "NYSE"
    assert _issuer_exchange_for_ticker(fake_edgar, 1, "Y") is None
    assert _issuer_exchange_for_ticker(fake_edgar, None, "X") is None

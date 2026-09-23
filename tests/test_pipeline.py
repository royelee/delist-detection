from datetime import date, timedelta
from pathlib import Path

import pytest

import delist_detection.pipeline as pipeline
from delist_detection.classifier import DelistClassifier, DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import DelistingEvent, DelistingFinder
from delist_detection.edgar import EdgarBlocked, EdgarSubmission
from delist_detection.ftd import FtdRow
from delist_detection.last_trade import LastTrade
from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.observations import Observation, ObservationIndex
from delist_detection.payout_extractor import PayoutResult
from delist_detection.pipeline import (
    Clients, Overrides, _issuer_exchange_for_ticker, _merge_review_rows, _own_last_seen,
    _ticker_range_review, run, successor_from_8k12b, successor_search_name,
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


# --- fix round 2, item 4: the ticker(s) come from the parenthetical right before (CIK ...) ---

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
    in SecurityContext.sibling_spans, keyed by sec_id. BBB's CUSIP also shows
    an OTC tail under another symbol after its last own-ticker sighting: the
    span's end must stay at that own-ticker sighting -- this fails under the
    old `sib_sig[-1][0]`, which would pick up the later OTC-tail date."""
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

    class _FtdOtcTail:
        ROWS = [FtdRow("2020-08-01", "BBBCUSIP1", "BBBQ", "DUAL CLASS CO OTC", 0.01)]

        def urls_for(self, lo, hi):
            return ["mem"]

        def rows(self, url, *, symbols=None, cusips=None):
            for r in self.ROWS:
                if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                    yield r

    obs = [Observation("AAA", "2020-01-01", "DUAL CLASS CO", cik=9001),
           Observation("AAA", "2020-06-01", "DUAL CLASS CO", cik=9001),
           Observation("BBB", "2020-02-01", "DUAL CLASS CO", cusip="BBBCUSIP1", cik=9001),
           Observation("BBB", "2020-07-01", "DUAL CLASS CO", cusip="BBBCUSIP1", cik=9001)]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, member_names=index.name_on, cik_map=index.cik_pin_on)
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=figi, ftd_client=_FtdOtcTail())

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
    assert aaa_ctx.sibling_spans["BBGBBB00001"] == ("2020-02-01", "2020-07-01")   # not the 2020-08-01 OTC tail


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


# ===================== fix round 2 =====================

# --- item 1: payouts.csv cites the right accession, at the run() level ---

class _FakePayoutExtractor:
    def __init__(self, result):
        self.result = result

    def extract(self, record, last_close=None):
        return self.result


class _FakeLLMExtractor:
    def __init__(self, terms):
        self.terms = terms

    def extract(self, record):
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


# --- item 2: gate_payouts' acquirer_price is keyed by the merger, at the run() level ---

def test_run_level_acquirer_price_uses_each_mergers_own_last_trade_day(fake_edgar, tmp_path, monkeypatch):
    """Two merger events sharing a delist_date, both with LLM cash+stock terms
    naming the same acquirer, must each get the acquirer's close on THEIR OWN
    last trade day -- not whichever day a shared-by-date map happened to hold."""
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
    resolver = TickerResolver(fake_edgar, member_names=index.name_on, cik_map=index.cik_pin_on)
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=figi, ftd_client=_FtdWithAcquirer())

    def _merger_record(sec_id, ticker, cik, delist_date):
        return DelistRecord(ticker=ticker, cik=cik, observed_delist_date=delist_date, crsp_code=231,
                            bucket=CrspBucket.MERGER, confidence="high", reason="x", evidence={"flags": []},
                            sec_id=sec_id, delist_date=delist_date)

    ev1 = DelistingEvent(sec_id="BBGSEC001", cik=7001, ticker="S1", delist_date="2020-06-15",
                         record=_merger_record("BBGSEC001", "S1", 7001, "2020-06-15"),
                         last_trade=LastTrade(date(2020, 6, 1), "notice_a", ()), form25=None, form25_sub=None,
                         exchange="NYSE", flags=[])
    ev2 = DelistingEvent(sec_id="BBGSEC002", cik=7002, ticker="S2", delist_date="2020-06-15",
                         record=_merger_record("BBGSEC002", "S2", 7002, "2020-06-15"),
                         last_trade=LastTrade(date(2020, 6, 5), "notice_a", ()), form25=None, form25_sub=None,
                         exchange="NYSE", flags=[])

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

        def extract(self, record):
            return self.mapping.get((record.sec_id, record.delist_date))

    clients.llm_extractor = _LLMByKey({
        ("BBGSEC001", "2020-06-15"): terms1,
        ("BBGSEC002", "2020-06-15"): terms2,
    })
    overrides = Overrides(last_trade_closes={"BBGSEC001": 100.0, "BBGSEC002": 150.0})

    run(index, clients, overrides, out_dir=tmp_path, log=lambda *_: None)

    d = {r["sec_id"]: r for r in read_table("delistings", table_path(tmp_path, "delistings"))}
    assert d["BBGSEC001"]["acquirer_price"] == "100.000000"
    assert d["BBGSEC002"]["acquirer_price"] == "150.000000"


# --- item 6: a same-ticker successor does not overlap its predecessor ---

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
    ev = DelistingEvent(sec_id="BBG000FJLFX8", cik=1122304, ticker="AET", delist_date="2018-12-09", record=record,
                        last_trade=LastTrade(date(2018, 11, 28), "notice_a", ()), form25=None, form25_sub=None,
                        exchange="NYSE", flags=["successor_unknown"])

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


# --- item 7: one ticker_history range per acquirer, across all its mergers ---

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
    resolver = TickerResolver(fake_edgar, member_names=index.name_on, cik_map=index.cik_pin_on)
    clients = Clients(edgar=fake_edgar, resolver=resolver, classifier=DelistClassifier(fake_edgar, resolver),
                      figi=figi, ftd_client=_FtdTwoWindows())

    def _merger_ev(sec_id, ticker, cik, last_trade_day, delist_date):
        rec = DelistRecord(ticker=ticker, cik=cik, observed_delist_date=delist_date, crsp_code=231,
                           bucket=CrspBucket.MERGER, confidence="high", reason="x", evidence={"flags": []},
                           sec_id=sec_id, delist_date=delist_date)
        return DelistingEvent(sec_id=sec_id, cik=cik, ticker=ticker, delist_date=delist_date, record=rec,
                              last_trade=LastTrade(last_trade_day, "notice_a", ()), form25=None, form25_sub=None,
                              exchange="NYSE", flags=[])

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


# --- item 8: a listed_today error for one observed security does not abort the run ---

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
    resolver = TickerResolver(fake_edgar, member_names=index.name_on, cik_map=index.cik_pin_on)
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
    from delist_detection.ftd import FtdIndex
    from delist_detection.security_master import Range
    ranges = [Range("11111A101", "2019-06-03", "2020-01-01", "ftd"), Range("11111A200", "2020-01-02", None, "ftd")]
    ftd = FtdIndex(_ftd("RS", "11111A101", "REVERSE SPLIT CO", ["2019-09-04"], price=2.0)
                   + _ftd("RS", "00000X000", "SOMETHING ELSE", ["2019-09-04", "2020-03-03"], price=99.0)
                   + _ftd("RS", "11111A200", "REVERSE SPLIT CO NEW", ["2020-03-03"], price=20.0)
                   + _ftd("RSQ", "22222B200", "OTHER", ["2021-01-05"], price=7.0))
    # by symbol alone, 00000X000 (99.0) would come first on both days
    assert pipeline._close_on(ftd, ranges, date(2019, 9, 3), "RS") == (2.0, "2019-09-04", False)     # first range
    assert pipeline._close_on(ftd, ranges, date(2020, 3, 2), "RS") == (20.0, "2020-03-03", False)    # second range
    # the range's CUSIP has no row, or no range holds the day: the symbol
    assert pipeline._close_on(ftd, ranges, date(2021, 1, 4), "RSQ") == (7.0, "2021-01-05", False)
    assert pipeline._close_on(ftd, [], date(2021, 1, 4), "RSQ") == (7.0, "2021-01-05", False)


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
        return DelistingEvent(sec_id=sec_id, cik=cik, ticker=ticker, delist_date=delist_date, record=rec,
                              last_trade=LastTrade(last_trade_day, "notice_a", ()), form25=None, form25_sub=None,
                              exchange="NYSE", flags=[])

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
        def extract(self, record):
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
    names = ["securities", "ticker_history", "cusip_history", "delistings", "payouts", "review"]
    for name in names:
        assert table_path(tmp_path / "a", name).read_bytes() == table_path(tmp_path / "b", name).read_bytes(), name
    assert sorted(p.name for p in (tmp_path / "a").glob("*.csv")) == sorted(f"{n}.csv" for n in names)


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
    ev = DelistingEvent(sec_id="BBGGOOGLEA1", cik=1288776, ticker="GOOGL", delist_date="2015-10-12", record=record,
                        last_trade=LastTrade(date(2015, 10, 2), "notice_a", ()), form25=None, form25_sub=None,
                        exchange="NASDAQ", flags=["successor_unknown"])

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
                                          member_names=index.name_on, cik_map=index.cik_pin_on)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    (d,) = read_table("delistings", table_path(tmp_path, "delistings"))
    assert d["sec_id"] == "BBG000FJLFX8" and d["resolution_source"] == source


def test_resolution_source_comes_from_the_latest_era_that_has_a_cik():
    from delist_detection.observations import TickerEra
    from delist_detection.ticker_resolver import TickerResolution
    old, new = TickerEra("X", "2010-01-04", "2012-06-29", []), TickerEra("X", "2014-06-30", "2016-06-30", [])
    sec = Security("BBGX", 5, "COMMON", "X CO", "Common Stock", True, "cusip", eras=[old, new])
    res = {old.key: TickerResolution("X", 5, None, "manual"), new.key: TickerResolution("X", None, None, "none")}
    assert pipeline._resolution_source(sec, res) == "manual"          # the era issuer_cik came from
    res[new.key] = TickerResolution("X", 5, None, "company_tickers")
    assert pipeline._resolution_source(sec, res) == "company_tickers"
    assert pipeline._resolution_source(sec, {}) == "security_master"


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
    from delist_detection.observations import load_observations
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
    fake_edgar.company_map["CB"] = {"cik_str": 896159, "ticker": "CB", "title": "Chubb Ltd"}
    fake_edgar.company_map["AGN"] = {"cik_str": 1578845, "ticker": "AGN", "title": "Allergan plc"}
    fake_edgar.submissions_by_cik[896159] = []
    fake_edgar.submissions_by_cik[1578845] = []
    chubb_ltd = [{"figi": "BBGCHUBBLTD", "compositeFIGI": "BBGCHUBBLTD", "exchCode": "US", "ticker": "CB",
                  "name": "CHUBB LTD", "securityType": "Common Stock", "securityType2": "Common Stock"},
                 {"figi": "BBGCHUBBLT2", "compositeFIGI": "BBGCHUBBLTD", "exchCode": "UN", "ticker": "CB",
                  "name": "ACE LTD", "securityType": "Common Stock", "securityType2": "Common Stock"}]
    index = ObservationIndex(obs)
    resolver = TickerResolver(fake_edgar, manual_overrides={"CB": 896159, "AGN": 1578845},
                              member_names=index.name_on, cik_map=index.cik_pin_on)
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

import gzip
import io
import json
import os
import time
import zipfile
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import requests

from delist_detection.edgar import fill_only
from delist_detection.midas import MIDAS_INDEX_URL, MidasClient, quarter_of, summarize_midas_csv

CSV = """Date,Security,Ticker,McapRank,TurnRank,VolatilityRank,PriceRank,LitVol('000),OrderVol('000),Hidden,TradesForHidden,HiddenVol('000),TradeVolForHidden('000),Cancels,LitTrades,OddLots,TradesForOddLots,OddLotVol('000),TradeVolForOddLots('000)
20181127,Stock,AET,10,4,1,10,400.1,500,1,1,20.0,1,1,1,1,1,1,1
20181128,Stock,AET,10,4,1,10,300.0,500,1,1,0,1,1,1,1,1,1,1
20181129,Stock,AET,10,4,1,10,0,120.5,0,0,0,0,1,0,0,0,0,0
20181128,Stock,BRK.B,10,4,1,10,1.0,5,0,0,0,0,1,1,0,0,0,0
"""


def test_quarter_of():
    assert quarter_of("x/individual_security_2018_q4.zip") == (2018, 4)
    assert quarter_of("x/individual_security_2012_q10.zip") == (2012, 1)
    assert quarter_of("x/other.zip") is None


def test_summarize_filters_on_volume():
    s = summarize_midas_csv(CSV.splitlines())
    assert s["AET"] == ["2018-11-27", "2018-11-28"]      # 11-29 had orders but no trades
    assert s["BRK-B"] == ["2018-11-28"]


def test_client_last_trade_day_from_zip(tmp_path):
    (tmp_path / "index.html").write_text('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("README.txt", "readme")
        z.writestr("q4_2018_all.csv", CSV)
    (tmp_path / "individual_security_2018_q4.zip").write_bytes(buf.getvalue())
    c = MidasClient(tmp_path)
    assert c.last_trade_day("AET", date(2018, 10, 1), date(2018, 12, 10)) == date(2018, 11, 28)
    assert c.last_trade_day("AET", date(2018, 10, 1), date(2018, 11, 27)) == date(2018, 11, 27)
    assert c.last_trade_day("ZZZ", date(2018, 10, 1), date(2018, 12, 10)) is None
    assert c.last_trade_day("AET", date(2011, 1, 1), date(2011, 3, 1)) is None     # before MIDAS
    summary = tmp_path / "2018_q4.json.gz"
    assert json.loads(gzip.decompress(summary.read_bytes()))["AET"] == ["2018-11-27", "2018-11-28"]
    assert not (tmp_path / "individual_security_2018_q4.zip").exists()           # summary replaces the zip


def test_last_trade_day_near_coverage_end_is_suppressed(tmp_path):
    """The requested window runs past MIDAS's coverage end (only Q4 2018 is
    published) and the found day sits in the last 5 trading days of that
    quarter -- too close to the edge to trust as a real last trade, since an
    unpublished quarter always yields nothing and would otherwise let this
    stale-looking day beat the notice/8-K."""
    (tmp_path / "index.html").write_text('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>')
    csv_near_end = (
        "Date,Security,Ticker,McapRank,TurnRank,VolatilityRank,PriceRank,LitVol('000),OrderVol('000),"
        "Hidden,TradesForHidden,HiddenVol('000),TradeVolForHidden('000),Cancels,LitTrades,OddLots,"
        "TradesForOddLots,OddLotVol('000),TradeVolForOddLots('000)\n"
        "20181228,Stock,AET,10,4,1,10,400.1,500,1,1,20.0,1,1,1,1,1,1,1\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("q4_2018_all.csv", csv_near_end)
    (tmp_path / "individual_security_2018_q4.zip").write_bytes(buf.getvalue())
    c = MidasClient(tmp_path)
    assert c.coverage_end() == date(2018, 12, 31)
    # window extends into Q1 2019, which is not published -> no evidence
    assert c.last_trade_day("AET", date(2018, 10, 1), date(2019, 1, 15)) is None


def test_last_trade_day_past_coverage_end_but_not_near_edge_still_returns(tmp_path):
    """Same unpublished-quarter window, but the found day is well clear of the
    coverage end -- still trustworthy."""
    (tmp_path / "index.html").write_text('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("q4_2018_all.csv", CSV)
    (tmp_path / "individual_security_2018_q4.zip").write_bytes(buf.getvalue())
    c = MidasClient(tmp_path)
    assert c.last_trade_day("AET", date(2018, 10, 1), date(2019, 1, 15)) == date(2018, 11, 28)


def test_last_trade_day_within_coverage_ignores_the_rule(tmp_path):
    """The window never extends past coverage end, so the near-edge rule
    never applies even though the found day is the last day of the quarter."""
    (tmp_path / "index.html").write_text('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>')
    csv_near_end = (
        "Date,Security,Ticker,McapRank,TurnRank,VolatilityRank,PriceRank,LitVol('000),OrderVol('000),"
        "Hidden,TradesForHidden,HiddenVol('000),TradeVolForHidden('000),Cancels,LitTrades,OddLots,"
        "TradesForOddLots,OddLotVol('000),TradeVolForOddLots('000)\n"
        "20181228,Stock,AET,10,4,1,10,400.1,500,1,1,20.0,1,1,1,1,1,1,1\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("q4_2018_all.csv", csv_near_end)
    (tmp_path / "individual_security_2018_q4.zip").write_bytes(buf.getvalue())
    c = MidasClient(tmp_path)
    assert c.last_trade_day("AET", date(2018, 10, 1), date(2018, 12, 31)) == date(2018, 12, 28)


def test_coverage_end_none_when_no_links(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    c = MidasClient(tmp_path)
    assert c.coverage_end() is None


def test_client_recovers_from_corrupt_zip(tmp_path):
    """Test that a corrupt cached ZIP is deleted and re-downloaded."""
    (tmp_path / "index.html").write_text('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>')

    # Create the good ZIP data
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("README.txt", "readme")
        z.writestr("q4_2018_all.csv", CSV)
    good_zip = buf.getvalue()

    # Seed a corrupt file (not a valid ZIP)
    zip_path = tmp_path / "individual_security_2018_q4.zip"
    zip_path.write_bytes(b"not a zip file")

    # Mock download to return the good ZIP on retry (second call)
    call_count = [0]

    def mock_download(url, dest, **kwargs):
        call_count[0] += 1
        dest = tmp_path / dest.name  # normalize path to tmp_path
        if call_count[0] == 1:
            # First call: download tries the corrupt file, which will raise BadZipFile
            return dest  # return existing corrupt file
        else:
            # Second call: after corruption deleted, write good zip
            dest.write_bytes(good_zip)
            return dest

    with patch("delist_detection.midas.download", side_effect=mock_download):
        c = MidasClient(tmp_path)
        result = c.last_trade_day("AET", date(2018, 10, 1), date(2018, 12, 10))

    assert result == date(2018, 11, 28)
    # Verify summary was cached
    summary = tmp_path / "2018_q4.json.gz"
    assert json.loads(gzip.decompress(summary.read_bytes()))["AET"] == ["2018-11-27", "2018-11-28"]


def test_failed_quarter_download_is_remembered_for_the_rest_of_the_run(tmp_path):
    """A quarter whose ZIP keeps failing to download is fetched once per run,
    not once per security: later calls for the same quarter must not
    re-download it."""
    (tmp_path / "index.html").write_text('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>')
    calls = [0]

    def fail_download(url, dest, **kwargs):
        calls[0] += 1
        raise requests.ConnectionError("down")

    with patch("delist_detection.midas.download", side_effect=fail_download):
        c = MidasClient(tmp_path)
        assert c.last_trade_day("AET", date(2018, 10, 1), date(2018, 12, 10)) is None
        assert c.last_trade_day("ZZZ", date(2018, 10, 1), date(2018, 12, 10)) is None
    assert calls[0] == 1
    assert not (tmp_path / "2018_q4.json.gz").exists()


def test_client_reads_a_csv_inside_a_nested_zip(tmp_path):
    """SEC ships some quarters (2014 Q2) as a zip holding a folder with another
    zip, which holds the README and the CSV: the CSV is read from the inner zip."""
    (tmp_path / "index.html").write_text('<a href="/files/opa/x/individual_security_2014_q2.zip">z</a>')
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("README2_q.txt", "readme")
        z.writestr("q2_2014_all.csv", CSV.replace("201811", "201405"))
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("Market Activity by Individual Security 2014 Q2/individual_security_2014_q2.zip",
                   inner.getvalue())
    (tmp_path / "individual_security_2014_q2.zip").write_bytes(outer.getvalue())
    c = MidasClient(tmp_path)
    assert c.last_trade_day("AET", date(2014, 4, 1), date(2014, 6, 10)) == date(2014, 5, 28)
    assert json.loads(gzip.decompress((tmp_path / "2014_q2.json.gz").read_bytes()))["BRK-B"] == ["2014-05-28"]


CSV_2016 = """Date,Security,Ticker,McapRank,TurnRank,VolatilityRank,PriceRank,LitVol('000),OrderVol('000),Hidden,TradesForHidden,HiddenVol('000),TradeVolForHidden('000),Cancels,LitTrades,OddLots,TradesForOddLots,OddLotVol('000),TradeVolForOddLots('000)
20160104.0,Stock,A,10.0,7.0,1.0,8.0,2146.9069999999997,105397.22100000002,1552.0,19804.0,260.172,2407.0789999999997,312569.0,14066.0,3774.0,15289.0,159.05800000000002,1639.151
20160105.0,Stock,A,10.0,7.0,1.0,8.0,0.0,105397.22100000002,0.0,0.0,0.0,0.0,312569.0,0.0,0.0,0.0,0.0,0.0
"""


def test_summarize_reads_2016_float_formatted_dates():
    """The 2016 quarters write every number as a float, the date too
    ("20160104.0", real first rows of q1_2016_all.csv)."""
    assert summarize_midas_csv(CSV_2016.splitlines()) == {"A": ["2016-01-04"]}


def _zip_with(tmp_path, yq, csv_text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"q{yq[1]}_{yq[0]}_all.csv", csv_text)
    (tmp_path / f"individual_security_{yq[0]}_q{yq[1]}.zip").write_bytes(buf.getvalue())
    (tmp_path / "index.html").write_text(
        f'<a href="/files/opa/x/individual_security_{yq[0]}_q{yq[1]}.zip">z</a>')


def test_a_quarter_that_yields_no_rows_is_not_cached(tmp_path, caplog):
    """A quarter file read to an empty summary is a format the reader does not
    know, never an answer: nothing is cached, a warning is logged, and the
    quarter gives no evidence for the rest of the run."""
    import logging
    caplog.set_level(logging.WARNING)
    _zip_with(tmp_path, (2016, 1), CSV_2016.replace("20160104.0", "01/04/2016"))
    c = MidasClient(tmp_path)
    assert c.last_trade_day("A", date(2016, 1, 1), date(2016, 3, 1)) is None
    assert not (tmp_path / "2016_q1.json.gz").exists()
    assert "2016 Q1" in caplog.text


def test_an_empty_cached_summary_is_read_again(tmp_path):
    """A summary cached empty by an older reader is not trusted: the quarter is
    summarized again from its zip."""
    _zip_with(tmp_path, (2016, 1), CSV_2016)
    (tmp_path / "2016_q1.json.gz").write_bytes(gzip.compress(b"{}"))
    c = MidasClient(tmp_path)
    assert c.last_trade_day("A", date(2016, 1, 1), date(2016, 3, 1)) == date(2016, 1, 4)
    assert json.loads(gzip.decompress((tmp_path / "2016_q1.json.gz").read_bytes())) == {"A": ["2016-01-04"]}


def test_what_a_warm_thread_reads_from_a_stale_index_is_not_kept_for_the_sequential_pass(tmp_path):
    """The warm finders share the run's own client. A warm thread (edgar.fill_only)
    reads the cached index whatever its age and never refreshes it, so neither
    that read nor a miss drawn from it may outlive the warm pass: the sequential
    pass reads the index itself, refreshes the stale copy and finds the new
    quarter, exactly as a one-thread run does."""
    q4, q1 = ('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>',
              '<a href="/files/opa/x/individual_security_2019_q1.zip">z</a>')
    index = tmp_path / "index.html"
    index.write_text(q4)
    stale = time.time() - 40 * 86400
    os.utime(index, (stale, stale))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("q1_2019_all.csv", CSV.replace("20181128", "20190215"))
    q1_url = "https://www.sec.gov/files/opa/x/individual_security_2019_q1.zip"
    served = {MIDAS_INDEX_URL: (q4 + q1).encode(), q1_url: buf.getvalue()}
    asked = []

    class _Session:
        def get(self, url, headers=None, timeout=None):
            asked.append(url)
            body = served[url]
            return SimpleNamespace(status_code=200, url=url, content=body, text=body.decode("latin-1"),
                                   raise_for_status=lambda: None)

    c = MidasClient(tmp_path, session=_Session())
    with fill_only():
        assert c.last_trade_day("AET", date(2019, 1, 2), date(2019, 3, 29)) is None     # not in the stale copy
        assert c.coverage_end() == date(2018, 12, 31)
    assert asked == []
    assert c.last_trade_day("AET", date(2019, 1, 2), date(2019, 3, 29)) == date(2019, 2, 15)
    assert asked == [MIDAS_INDEX_URL, q1_url]
    assert c.coverage_end() == date(2019, 3, 31)


def test_a_download_the_warm_threads_gave_up_on_is_tried_again_by_the_sequential_pass(tmp_path):
    (tmp_path / "index.html").write_text('<a href="/files/opa/x/individual_security_2018_q4.zip">z</a>')
    calls = [0]

    def fail_download(url, dest, **kwargs):
        calls[0] += 1
        raise requests.ConnectionError("down")

    with patch("delist_detection.midas.download", side_effect=fail_download):
        c = MidasClient(tmp_path)
        with fill_only():
            assert c.last_trade_day("AET", date(2018, 10, 1), date(2018, 12, 10)) is None
            assert c.last_trade_day("ZZZ", date(2018, 10, 1), date(2018, 12, 10)) is None
        assert calls[0] == 1                               # once for every warm thread
        assert c.last_trade_day("AET", date(2018, 10, 1), date(2018, 12, 10)) is None
        assert c.last_trade_day("ZZZ", date(2018, 10, 1), date(2018, 12, 10)) is None
    assert calls[0] == 2                                   # and once more by the sequential pass itself

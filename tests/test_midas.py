import gzip
import io
import json
import zipfile
from datetime import date
from unittest.mock import patch

from delist_detection.midas import MidasClient, quarter_of, summarize_midas_csv

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

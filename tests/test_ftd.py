import io
import zipfile
from datetime import date

from delist_detection.ftd import (
    FtdClient, FtdIndex, FtdRow, parse_ftd_lines, parse_index_links, period_of,
)

SAMPLE = """SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE
20181126|00817Y108|AET|89|AETNA INC.(NEW)|205.36
20181128|00817Y108|AET|1948|AETNA INC.(NEW)|210.10
20181129|00817Y108|AET|300|AETNA INC.(NEW)|212.70
20181130|00817Y108|AET|100|AETNA INC.(NEW)|212.70
20181129|126650100|CVS|5000|CVS HEALTH CORP|80.27
20040322|000375204|ABB|529463|ABB LTD ADS ( 1 REG SHS)|.
20181129|084670702|BRK/B|10|BERKSHIRE HATHAWAY INC|A|210.00
Trailer record count 7
Trailer total quantity of shares 5000
"""


def test_period_of():
    assert period_of("/files/data/fails-deliver-data/cnsfails201811b.zip") == (date(2018, 11, 16), date(2018, 11, 30))
    assert period_of("x/cnsfails201910a_0.zip") == (date(2019, 10, 1), date(2019, 10, 15))
    assert period_of("x/cnsp_sec_fails_2008q4.zip") == (date(2008, 10, 1), date(2008, 12, 31))
    assert period_of("x/readme.zip") is None


def test_parse_index_links_absolute_and_deduped():
    html = ('<a href="/files/data/fails-deliver-data/cnsfails201910a.zip">a</a>'
            '<a href="/files/data/fails-deliver-data/cnsfails201910a_0.zip">b</a>'
            '<a href="https://www.sec.gov/files/data/other/fails-deliver-data/cnsfails202308b_0.zip">c</a>'
            '<a href="/files/other.pdf">d</a>')
    assert parse_index_links(html) == [
        "https://www.sec.gov/files/data/fails-deliver-data/cnsfails201910a.zip",
        "https://www.sec.gov/files/data/other/fails-deliver-data/cnsfails202308b_0.zip",
    ]


def test_parse_lines_filters_and_handles_odd_rows():
    rows = list(parse_ftd_lines(SAMPLE.splitlines()))
    assert rows[0] == FtdRow("2018-11-26", "00817Y108", "AET", "AETNA INC.(NEW)", 205.36)
    abb = next(r for r in rows if r.symbol == "ABB")
    assert abb.price is None
    brk = next(r for r in rows if r.cusip == "084670702")
    assert brk.symbol == "BRK-B" and brk.description == "BERKSHIRE HATHAWAY INC|A" and brk.price == 210.0
    only = list(parse_ftd_lines(SAMPLE.splitlines(), symbols={"CVS"}))
    assert [r.symbol for r in only] == ["CVS"]
    by_cusip = list(parse_ftd_lines(SAMPLE.splitlines(), cusips={"00817Y108"}))
    assert len(by_cusip) == 4


def test_close_after_uses_next_trading_day_row():
    idx = FtdIndex(parse_ftd_lines(SAMPLE.splitlines()))
    assert idx.close_after(date(2018, 11, 28), cusip="00817Y108") == (212.70, "2018-11-29", False)
    assert idx.close_after(date(2018, 11, 28), symbol="CVS") == (80.27, "2018-11-29", False)
    # no row on the next trading day: the first later row within max_lag, flagged lagged
    assert idx.close_after(date(2018, 11, 27), cusip="00817Y108") == (210.10, "2018-11-28", False)
    assert idx.close_after(date(2018, 11, 23), cusip="00817Y108") == (205.36, "2018-11-26", False)
    assert idx.close_after(date(2018, 11, 21), cusip="00817Y108", max_lag=0) is None
    assert idx.close_after(date(2018, 11, 21), cusip="00817Y108", max_lag=3) == (205.36, "2018-11-26", True)


def test_by_symbol_and_cusip_ranges():
    idx = FtdIndex(parse_ftd_lines(SAMPLE.splitlines()))
    assert [r.date for r in idx.by_cusip("00817Y108", "2018-11-28", "2018-11-29")] == ["2018-11-28", "2018-11-29"]
    assert [r.date for r in idx.by_symbol("aet", hi="2018-11-26")] == ["2018-11-26"]


def _zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in members.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_client_reads_quarterly_zip(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(
        '<a href="/files/data/x/cnsp_sec_fails_2008q4.zip">q</a><a href="/files/data/x/cnsfails201811b.zip">b</a>')
    (tmp_path / "cnsp_sec_fails_2008q4.zip").write_bytes(_zip_bytes({
        "cnsp_sec_fails_200812.txt": "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
                                     "20081230|590188108|MER|10|MERRILL LYNCH & CO INC|11.07\n",
        "README.txt": "ignore me",
    }))
    c = FtdClient(tmp_path)
    assert c.urls_for(date(2008, 12, 1), date(2008, 12, 31)) == [
        "https://www.sec.gov/files/data/x/cnsp_sec_fails_2008q4.zip"]
    rows = list(c.rows(c.urls_for(date(2008, 12, 1), date(2008, 12, 31))[0]))
    assert rows == [FtdRow("2008-12-30", "590188108", "MER", "MERRILL LYNCH & CO INC", 11.07)]
    idx = FtdIndex.load(c, date(2008, 12, 1), date(2008, 12, 31), symbols={"MER"})
    assert idx.close_after(date(2008, 12, 29), symbol="MER") == (11.07, "2008-12-30", False)


def test_load_with_no_filters_returns_every_row(tmp_path):
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": SAMPLE}))
    c = FtdClient(tmp_path)
    idx = FtdIndex.load(c, date(2018, 11, 16), date(2018, 11, 30))
    assert len(idx.by_symbol("AET")) == 4
    assert idx.by_symbol("CVS")[0].price == 80.27
    assert idx.by_symbol("BRK-B")[0].price == 210.0
    # 2004-03-22 (ABB) is outside the requested range, so it's excluded.
    assert idx.by_symbol("ABB") == []


def test_extend_with_symbols(tmp_path):
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": SAMPLE}))
    c = FtdClient(tmp_path)
    idx = FtdIndex.load(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"AET"})
    assert idx.by_symbol("CVS") == []
    idx.extend(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"CVS"})
    assert idx.close_after(date(2018, 11, 28), symbol="CVS") == (80.27, "2018-11-29", False)


def test_extend_with_cusip_picks_up_rows_under_a_different_symbol(tmp_path):
    # Simulates a ticker rename (e.g. FB -> META): same CUSIP, different symbol.
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    text = ("SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
            "20181126|30303M102|FB|10|FACEBOOK INC|140.00\n"
            "20181128|30303M102|META|20|META PLATFORMS INC|141.00\n")
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": text}))
    c = FtdClient(tmp_path)
    idx = FtdIndex.load(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"FB"})
    assert [r.symbol for r in idx.by_cusip("30303M102")] == ["FB"]
    # Already having rows for this CUSIP (via the symbol filter) must not stop
    # a subsequent CUSIP-filtered extend from scanning it: that CUSIP has never
    # itself been used as a scan filter, so its window is unrecorded.
    idx.extend(c, date(2018, 11, 16), date(2018, 11, 30), cusips={"30303M102"})
    assert [r.symbol for r in idx.by_cusip("30303M102")] == ["FB", "META"]

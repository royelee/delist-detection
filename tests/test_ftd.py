import io
import zipfile
from datetime import date

from delist_detection.ftd import (
    FtdClient, FtdIndex, FtdRow, is_deleted_symbol, parse_ftd_lines, parse_index_links, period_of,
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


class _CountingClient:
    """Wraps a real `FtdClient`, counting `.rows()` calls, so a test can
    assert `extend()` skipped rescanning an already-covered range."""
    def __init__(self, real: FtdClient) -> None:
        self._real = real
        self.rows_calls = 0

    def urls_for(self, lo, hi):
        return self._real.urls_for(lo, hi)

    def rows(self, url, *, symbols=None, cusips=None):
        self.rows_calls += 1
        yield from self._real.rows(url, symbols=symbols, cusips=cusips)


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


def test_client_reads_a_member_without_an_extension(tmp_path, caplog):
    """89 of the SEC's zips (2022-05 on, e.g. cnsfails202401a.zip) hold one
    member named without ".txt" ("cnsfails202401a"): it is data all the same.
    A member with no FTD rows at all is logged and skipped; directories too."""
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails202401a.zip">a</a>')
    (tmp_path / "cnsfails202401a.zip").write_bytes(_zip_bytes({
        "cnsfails202401a": "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
                           "20240102|00206R102|T|500|AT&T INC COM|16.78\n"
                           "Trailer record count 1\n",
        "notes/": "",
        "readme": "no fails rows in here\n",
    }))
    c = FtdClient(tmp_path)
    with caplog.at_level("WARNING", logger="delist_detection.ftd"):
        rows = list(c.rows(c.urls_for(date(2024, 1, 1), date(2024, 1, 15))[0]))
    assert rows == [FtdRow("2024-01-02", "00206R102", "T", "AT&T INC COM", 16.78)]
    assert "readme" in caplog.text and "cnsfails202401a.zip" in caplog.text
    assert "cnsfails202401a:" not in caplog.text          # the data member is not reported
    idx = FtdIndex.load(c, date(2024, 1, 1), date(2024, 1, 15), symbols={"T"})
    assert idx.close_after(date(2023, 12, 29), symbol="T") == (16.78, "2024-01-02", False)


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


def test_extend_disjoint_scans_do_not_falsely_cover_a_gap(tmp_path):
    (tmp_path / "index.html").write_text(
        '<a href="/files/data/x/cnsfails201901a.zip">jan</a>'
        '<a href="/files/data/x/cnsfails201902a.zip">feb</a>'
        '<a href="/files/data/x/cnsfails201903a.zip">mar</a>')
    header = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
    (tmp_path / "cnsfails201901a.zip").write_bytes(
        _zip_bytes({"a.txt": header + "20190110|00817Y108|AET|10|AETNA INC|100.00\n"}))
    (tmp_path / "cnsfails201902a.zip").write_bytes(
        _zip_bytes({"a.txt": header + "20190210|00817Y108|AET|10|AETNA INC|101.00\n"}))
    (tmp_path / "cnsfails201903a.zip").write_bytes(
        _zip_bytes({"a.txt": header + "20190310|00817Y108|AET|10|AETNA INC|102.00\n"}))
    c = FtdClient(tmp_path)
    idx = FtdIndex()
    idx.extend(c, date(2019, 1, 1), date(2019, 1, 15), cusips={"00817Y108"})
    idx.extend(c, date(2019, 3, 1), date(2019, 3, 15), cusips={"00817Y108"})
    assert [r.date for r in idx.by_cusip("00817Y108")] == ["2019-01-10", "2019-03-10"]
    # A naive min/max envelope over Jan..Mar would wrongly treat Feb as
    # already covered; with merged disjoint intervals it is not, so this
    # extend must still find the Feb row.
    idx.extend(c, date(2019, 2, 1), date(2019, 2, 15), cusips={"00817Y108"})
    assert [r.date for r in idx.by_cusip("00817Y108")] == ["2019-01-10", "2019-02-10", "2019-03-10"]


def test_load_maps_separatorless_class_symbols_to_the_observed_ticker(tmp_path):
    # FTD writes class tickers without a separator ("BFB", "BRKB"); observations
    # and the tables use "BF-B". Rows load under both spellings and are keyed by
    # the observed one; a symbol the caller did not spell with a separator stays.
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    text = ("SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
            "20181126|115637209|BFB|10|BROWN-FORMAN CORP CL-B|48.00\n"
            "20181127|115637209|BF/B|10|BROWN-FORMAN CORP CL-B|48.50\n"
            "20181126|115637100|BFA|10|BROWN-FORMAN CORP CL-A|47.00\n"
            "20181126|084670702|BRKB|10|BERKSHIRE HATHWY INC(HLDG CO)B|200.00\n")
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": text}))
    c = FtdClient(tmp_path)
    idx = FtdIndex.load(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"BF-B", "BFA"})
    assert [(r.date, r.symbol) for r in idx.by_symbol("BF-B")] == [("2018-11-26", "BF-B"), ("2018-11-27", "BF-B")]
    assert idx.by_symbol("BFB") == idx.by_symbol("BF-B")
    assert [r.symbol for r in idx.by_symbol("BFA")] == ["BFA"]
    assert [r.symbol for r in idx.by_cusip("115637209")] == ["BF-B", "BF-B"]
    assert idx.close_after(date(2018, 11, 23), symbol="BF-B") == (48.0, "2018-11-26", False)
    # a later extend (an acquirer ticker) maps its own spelling too
    idx.extend(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"BRK-B"})
    assert [r.symbol for r in idx.by_symbol("BRK-B")] == ["BRK-B"]


def test_a_bare_symbol_row_is_relabelled_only_when_its_description_fits_the_class_ticker():
    """With the class ticker's observed names known, a "BFB" row becomes "BF-B"
    only when its description agrees with them: another security trading under
    the bare symbol stays "BFB". The bare spelling still finds all its rows.
    With no names known (an acquirer ticker) there is nothing to check against,
    and every bare row is relabelled."""
    rows = [FtdRow("2018-11-26", "115637209", "BFB", "BROWN-FORMAN CORP CL-B", 48.0),
            FtdRow("2018-11-27", "999999999", "BFB", "BIG FAKE BANCORP", 3.0)]

    class _Client:
        def urls_for(self, lo, hi):
            return ["mem"]

        def rows(self, url, *, symbols=None, cusips=None):
            yield from (r for r in rows if symbols and r.symbol in symbols)

    idx = FtdIndex.load(_Client(), date(2018, 11, 16), date(2018, 11, 30), symbols={"BF-B"},
                        names={"BF-B": ["BROWN FORMAN CORP CLASS B"]})
    assert [(r.cusip, r.symbol) for r in idx.by_symbol("BF-B")] == [("115637209", "BF-B")]
    assert [(r.cusip, r.symbol) for r in idx.by_symbol("BFB")] == [("115637209", "BF-B"), ("999999999", "BFB")]
    unnamed = FtdIndex.load(_Client(), date(2018, 11, 16), date(2018, 11, 30), symbols={"BF-B"})
    assert [r.cusip for r in unnamed.by_symbol("BF-B")] == ["115637209", "999999999"]


def test_rows_map_to_the_separator_spelling_even_when_the_bare_one_is_observed_too(tmp_path):
    # Index snapshots spell one ticker both ways (Wikipedia "BF.B", iShares "BFB"):
    # the rows are keyed by the canonical "BF-B" and found under either spelling.
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    text = ("SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
            "20181126|115637209|BFB|10|BROWN-FORMAN CORP CL-B|48.00\n")
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": text}))
    idx = FtdIndex.load(FtdClient(tmp_path), date(2018, 11, 16), date(2018, 11, 30), symbols={"BF-B", "BFB"})
    assert [r.symbol for r in idx.by_symbol("BF-B")] == ["BF-B"]
    assert idx.by_symbol("BFB") == idx.by_symbol("BF-B")


def test_extend_adjacent_scans_merge_and_skip_rescan(tmp_path):
    (tmp_path / "index.html").write_text(
        '<a href="/files/data/x/cnsfails201901a.zip">a</a>'
        '<a href="/files/data/x/cnsfails201901b.zip">b</a>')
    header = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
    (tmp_path / "cnsfails201901a.zip").write_bytes(
        _zip_bytes({"a.txt": header + "20190105|00817Y108|AET|10|AETNA INC|100.00\n"}))
    (tmp_path / "cnsfails201901b.zip").write_bytes(
        _zip_bytes({"b.txt": header + "20190120|00817Y108|AET|10|AETNA INC|101.00\n"}))
    c = _CountingClient(FtdClient(tmp_path))
    idx = FtdIndex()
    idx.extend(c, date(2019, 1, 1), date(2019, 1, 15), cusips={"00817Y108"})
    idx.extend(c, date(2019, 1, 16), date(2019, 1, 31), cusips={"00817Y108"})
    calls_before = c.rows_calls
    # Jan 10-20 falls entirely inside the union of the two adjacent scans
    # (Jan 1-15 and Jan 16-31): this must not rescan at all.
    idx.extend(c, date(2019, 1, 10), date(2019, 1, 20), cusips={"00817Y108"})
    assert c.rows_calls == calls_before
    assert len(idx.by_cusip("00817Y108")) == 2


# Dell Inc.'s last fails rows (cnsfails201310b.zip): its last trade was 2013-10-29
# and no row is dated after it.
DELL_ROWS = """SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE
20131021|24702R101|DELL|3773|DELL INC|13.83
20131022|24702R101|DELL|4324|DELL INC|13.85
20131023|24702R101|DELL|21330|DELL INC|13.84
20131024|24702R101|DELL|2776|DELL INC|13.85
20131025|24702R101|DELL|282|DELL INC|13.85
20131028|24702R101|DELL|197|DELL INC|13.84
20131029|24702R101|DELL|57118|DELL INC|13.82
"""


def test_close_through_reads_the_latest_row_on_or_before_the_day():
    """With no row after the last trade, the latest row dated on or before it
    (within `max_back` trading days) gives the close of the day before its date."""
    idx = FtdIndex(parse_ftd_lines(DELL_ROWS.splitlines()))
    assert idx.close_after(date(2013, 10, 29), cusip="24702R101") is None
    assert idx.close_through(date(2013, 10, 29), cusip="24702R101") == (13.82, "2013-10-29")
    assert idx.close_through(date(2013, 10, 29), symbol="DELL") == (13.82, "2013-10-29")
    # the rows end 2013-10-29: a day ten trading days later still reaches it (two weeks)...
    assert idx.close_through(date(2013, 11, 12), cusip="24702R101") == (13.82, "2013-10-29")
    # ...a day eleven trading days later does not
    assert idx.close_through(date(2013, 11, 13), cusip="24702R101") is None


def test_a_deleted_symbol_is_the_old_symbol_plus_xxxx():
    """SEC's fails files keep reporting a delisted security under its deleted
    symbol: the old symbol with XXXX appended (ORLYXXXX, LLYVKXXXX, AGRX ->
    AGRXXXXX). A real ticker may end in X or XX (AVXX)."""
    for s in ("ORLYXXXX", "LLYVKXXXX", "AGRXXXXX", "BXXXXX", "BRK-BXXXX"):
        assert is_deleted_symbol(s), s
    for s in ("ORLY", "AVXX", "XXX", "XXXX", "", "BXXX"):
        assert not is_deleted_symbol(s), s

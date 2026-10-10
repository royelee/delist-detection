import io
import zipfile
from datetime import date

from delist_detection.sources.ftd import (
    FtdClient, FtdIndex, FtdRow, close_age, is_deleted_symbol, parse_ftd_lines, parse_index_links, period_of,
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
    assert an ask skipped rescanning an already-covered range."""
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
    idx = FtdIndex.opened(c, date(2008, 12, 1), date(2008, 12, 31), symbols={"MER"})
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
    with caplog.at_level("WARNING", logger="delist_detection.sources.ftd"):
        rows = list(c.rows(c.urls_for(date(2024, 1, 1), date(2024, 1, 15))[0]))
    assert rows == [FtdRow("2024-01-02", "00206R102", "T", "AT&T INC COM", 16.78)]
    assert "readme" in caplog.text and "cnsfails202401a.zip" in caplog.text
    assert "cnsfails202401a:" not in caplog.text          # the data member is not reported
    idx = FtdIndex.opened(c, date(2024, 1, 1), date(2024, 1, 15), symbols={"T"})
    assert idx.close_after(date(2023, 12, 29), symbol="T") == (16.78, "2024-01-02", False)


def test_load_with_no_filters_returns_every_row(tmp_path):
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": SAMPLE}))
    c = FtdClient(tmp_path)
    idx = FtdIndex.opened(c, date(2018, 11, 16), date(2018, 11, 30))
    assert len(idx.by_symbol("AET")) == 4
    assert idx.by_symbol("CVS")[0].price == 80.27
    assert idx.by_symbol("BRK-B")[0].price == 210.0
    # 2004-03-22 (ABB) is outside the requested range, so it's excluded.
    assert idx.by_symbol("ABB") == []


def test_follow_with_symbols(tmp_path):
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": SAMPLE}))
    c = FtdClient(tmp_path)
    idx = FtdIndex.opened(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"AET"})
    assert idx.by_symbol("CVS") == []
    idx.follow(symbols={"CVS"})
    assert idx.close_after(date(2018, 11, 28), symbol="CVS") == (80.27, "2018-11-29", False)


def test_follow_with_cusip_picks_up_rows_under_a_different_symbol(tmp_path):
    # Simulates a ticker rename (e.g. FB -> META): same CUSIP, different symbol.
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    text = ("SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
            "20181126|30303M102|FB|10|FACEBOOK INC|140.00\n"
            "20181128|30303M102|META|20|META PLATFORMS INC|141.00\n")
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": text}))
    c = FtdClient(tmp_path)
    idx = FtdIndex.opened(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"FB"})
    assert [r.symbol for r in idx.by_cusip("30303M102")] == ["FB"]
    # Already having rows for this CUSIP (via the symbol filter) must not stop
    # a subsequent CUSIP-filtered ask from scanning it: that CUSIP has never
    # itself been used as a scan filter, so its window is unrecorded.
    idx.follow(cusips={"30303M102"})
    assert [r.symbol for r in idx.by_cusip("30303M102")] == ["FB", "META"]


def test_disjoint_asks_do_not_falsely_cover_a_gap(tmp_path):
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
    idx = FtdIndex(source=c)
    idx.around([date(2019, 1, 1)], after=14, cusips={"00817Y108"})
    idx.around([date(2019, 3, 1)], after=14, cusips={"00817Y108"})
    assert [r.date for r in idx.by_cusip("00817Y108")] == ["2019-01-10", "2019-03-10"]
    # A naive min/max envelope over Jan..Mar would wrongly treat Feb as
    # already covered; with merged disjoint intervals it is not, so this
    # ask must still find the Feb row.
    idx.around([date(2019, 2, 1), date(2019, 2, 15)], cusips={"00817Y108"})
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
    idx = FtdIndex.opened(c, date(2018, 11, 16), date(2018, 11, 30), symbols={"BF-B", "BFA"})
    assert [(r.date, r.symbol) for r in idx.by_symbol("BF-B")] == [("2018-11-26", "BF-B"), ("2018-11-27", "BF-B")]
    assert idx.by_symbol("BFB") == idx.by_symbol("BF-B")
    assert [r.symbol for r in idx.by_symbol("BFA")] == ["BFA"]
    assert [r.symbol for r in idx.by_cusip("115637209")] == ["BF-B", "BF-B"]
    assert idx.close_after(date(2018, 11, 23), symbol="BF-B") == (48.0, "2018-11-26", False)
    # a later ask (an acquirer ticker) maps its own spelling too
    idx.around([date(2018, 11, 16), date(2018, 11, 30)], symbols={"BRK-B"})
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

    idx = FtdIndex.opened(_Client(), date(2018, 11, 16), date(2018, 11, 30), symbols={"BF-B"},
                          names={"BF-B": ["BROWN FORMAN CORP CLASS B"]})
    assert [(r.cusip, r.symbol) for r in idx.by_symbol("BF-B")] == [("115637209", "BF-B")]
    assert [(r.cusip, r.symbol) for r in idx.by_symbol("BFB")] == [("115637209", "BF-B"), ("999999999", "BFB")]
    unnamed = FtdIndex.opened(_Client(), date(2018, 11, 16), date(2018, 11, 30), symbols={"BF-B"})
    assert [r.cusip for r in unnamed.by_symbol("BF-B")] == ["115637209", "999999999"]


def test_rows_map_to_the_separator_spelling_even_when_the_bare_one_is_observed_too(tmp_path):
    # Index snapshots spell one ticker both ways (Wikipedia "BF.B", iShares "BFB"):
    # the rows are keyed by the canonical "BF-B" and found under either spelling.
    (tmp_path / "index.html").write_text('<a href="/files/data/x/cnsfails201811b.zip">b</a>')
    text = ("SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
            "20181126|115637209|BFB|10|BROWN-FORMAN CORP CL-B|48.00\n")
    (tmp_path / "cnsfails201811b.zip").write_bytes(_zip_bytes({"a.txt": text}))
    idx = FtdIndex.opened(FtdClient(tmp_path), date(2018, 11, 16), date(2018, 11, 30), symbols={"BF-B", "BFB"})
    assert [r.symbol for r in idx.by_symbol("BF-B")] == ["BF-B"]
    assert idx.by_symbol("BFB") == idx.by_symbol("BF-B")


def test_adjacent_asks_merge_and_skip_rescan(tmp_path):
    (tmp_path / "index.html").write_text(
        '<a href="/files/data/x/cnsfails201901a.zip">a</a>'
        '<a href="/files/data/x/cnsfails201901b.zip">b</a>')
    header = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
    (tmp_path / "cnsfails201901a.zip").write_bytes(
        _zip_bytes({"a.txt": header + "20190105|00817Y108|AET|10|AETNA INC|100.00\n"}))
    (tmp_path / "cnsfails201901b.zip").write_bytes(
        _zip_bytes({"b.txt": header + "20190120|00817Y108|AET|10|AETNA INC|101.00\n"}))
    c = _CountingClient(FtdClient(tmp_path))
    idx = FtdIndex(source=c)
    idx.around([date(2019, 1, 1), date(2019, 1, 15)], cusips={"00817Y108"})
    idx.around([date(2019, 1, 16), date(2019, 1, 31)], cusips={"00817Y108"})
    calls_before = c.rows_calls
    # Jan 10-20 falls entirely inside the union of the two adjacent scans
    # (Jan 1-15 and Jan 16-31): this must not rescan at all.
    idx.around([date(2019, 1, 10)], after=10, cusips={"00817Y108"})
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


def _rows(*spec):
    return [FtdRow(d, c, s, desc, p) for d, c, s, desc, p in spec]


def test_trading_rows_skip_a_deleted_symbol_and_keep_the_cusip_order():
    idx = FtdIndex(_rows(("2020-01-02", "B00000001", "BBB", "B CO", 2.0),
                         ("2020-01-03", "A00000001", "AAA", "A CO", 1.0),
                         ("2020-02-03", "A00000001", "AAAXXXX", "A CO", 1.0),
                         ("2020-01-02", "A00000001", "AAA", "A CO", 1.0)))
    assert [(r.date, r.cusip) for r in idx.trading_rows(["A00000001", "B00000001"])] == [
        ("2020-01-02", "A00000001"), ("2020-01-03", "A00000001"), ("2020-01-02", "B00000001")]
    assert idx.descriptions("a00000001") == {"A CO"}


def test_symbol_deleted_needs_the_last_rows_under_a_deleted_symbol_only():
    rows = _rows(("2015-10-01", "428236103", "HPQ", "HP INC", 1.0),
                 ("2015-11-02", "428236103", "HPQXXXX", "HP INC", 1.0))
    assert FtdIndex(rows).symbol_deleted(["428236103"])
    back = rows + _rows(("2015-12-01", "428236103", "HPQ", "HP INC", 1.0))
    assert not FtdIndex(back).symbol_deleted(["428236103"])
    assert not FtdIndex(rows).symbol_deleted([])


def test_close_of_and_close_known_on_try_the_cusip_then_the_symbol():
    idx = FtdIndex(_rows(("2019-09-04", "11111A101", "RS", "RS CO", 2.0),
                         ("2019-09-04", "00000X000", "RS", "OTHER", 99.0),
                         ("2019-09-03", "11111A101", "RS", "RS CO", 3.0)))
    assert idx.close_of(date(2019, 9, 3), cusip="11111A101", symbol="RS") == (2.0, "2019-09-04", False)
    assert idx.close_of(date(2019, 9, 3), cusip="22222B200", symbol="RS") == (99.0, "2019-09-04", False)
    assert idx.close_known_on(date(2019, 9, 3), cusip="11111A101", symbol="RS") == (3.0, "2019-09-03")
    assert idx.close_known_on(date(2019, 9, 3), cusip=None, symbol="RS") == (3.0, "2019-09-03")


def test_the_symbol_fallback_skips_another_securitys_cusip():
    """WEN 2008 (5d rule 3): no row of Wendy's own CUSIP follows its last trade (2008-09-29); the symbol's next row
    is Wendy's/Arby's new CUSIP ($5.26), another security of the run, so the close is Wendy's own last one."""
    idx = FtdIndex(_rows(("2008-09-26", "950590109", "WEN", "WENDYS INTERNATIONAL", 22.15),
                         ("2008-10-01", "950587105", "WEN", "WENDY'S/ARBY'S GROUP INC CL A", 5.26)))
    assert idx.close_of(date(2008, 9, 29), cusip="950590109", symbol="WEN") == (5.26, "2008-10-01", True)
    assert idx.close_of(date(2008, 9, 29), cusip="950590109", symbol="WEN", skip={"950587105"}) is None
    assert idx.close_known_on(date(2008, 9, 29), cusip="950590109", symbol="WEN", skip={"950587105"}) \
        == (22.15, "2008-09-26")
    assert idx.close_known_on(date(2008, 10, 2), cusip=None, symbol="WEN", skip={"950587105"}) == (22.15, "2008-09-26")


def test_a_fails_rows_close_is_a_trading_day_older_than_its_date():
    """A row dated D carries the close of the trading day before D: dated the
    last trade day itself, its close is 1 trading day old; a Monday row after a
    Friday last trade carries that Friday's close (0); holidays are skipped."""
    assert close_age("2018-11-28", date(2018, 11, 28)) == 1
    assert close_age("2018-11-26", date(2018, 11, 28)) == 3
    assert close_age("2018-12-03", date(2018, 11, 30)) == 0
    assert close_age("2018-11-23", date(2018, 11, 26)) == 2          # the day before is Thanksgiving


# --- sub-plan 5b, C: whether a security's own CUSIPs trade on after a day ---

from delist_detection.sources.ftd import is_trading_symbol, trades_after  # noqa: E402


def _tail_rows(symbol, days, prices=(10.0, 10.5)):
    return [FtdRow(d, "74955W307", symbol, "R H DONNELLEY CORP", prices[i % len(prices)]) for i, d in enumerate(days)]


JANUARY = [f"2020-01-{d:02d}" for d in range(2, 23)]       # 21 rows, 2020-01-02 .. 2020-01-22: 20 days apart


def test_twenty_rows_over_twenty_days_at_two_prices_show_trading_after_the_day():
    assert trades_after(_tail_rows("RHDC", JANUARY), "2020-01-01")
    assert not trades_after(_tail_rows("RHDC", JANUARY[:-1]), "2020-01-01")     # 19 days apart
    assert not trades_after(_tail_rows("RHDC", JANUARY), "2020-01-02")          # 20 rows after the day, 19 days apart


def test_fails_settling_at_one_price_are_no_trading():
    assert not trades_after(_tail_rows("RHDC", JANUARY, prices=(1.28,)), "2020-01-01")


def test_an_otc_symbol_counts_and_a_deleted_unassigned_or_pair_off_symbol_does_not():
    for symbol in ("RHDC", "RHDCQ", "**********"):
        assert is_trading_symbol(symbol) and trades_after(_tail_rows(symbol, JANUARY), "2020-01-01")
    for symbol in ("RHDXXXX", "RHDZZZZ", "F104PAIROFF", ""):
        assert not is_trading_symbol(symbol) and not trades_after(_tail_rows(symbol, JANUARY), "2020-01-01")


def test_a_base_symbol_row_is_a_class_tickers_only_before_the_bases_own_first_observation():
    """Rule A's bound: Under Armour's class C was FTD's "UAC" in 2016 and "UA", the base symbol of its own line, from
    2016-12-08. A run that spells class C "UA-C" and observes UA from 2016-12-30 takes the 2016 rows by the
    description, not the 2017 "UA ... CL C" rows."""
    rows = [FtdRow("2016-06-15", "904311206", "UA", "UNDER ARMOUR INC CL C", 20.0),
            FtdRow("2017-03-01", "904311206", "UA", "UNDER ARMOUR INC CL C", 30.0)]

    class _Client:
        def urls_for(self, lo, hi):
            return ["mem"]

        def rows(self, url, *, symbols=None, cusips=None):
            yield from (r for r in rows if symbols and r.symbol in symbols)

    names = {"UA-C": ["UNDER ARMOUR INC CLASS C"]}
    bound = FtdIndex.opened(_Client(), date(2016, 6, 1), date(2017, 3, 31), symbols={"UA-C"}, names=names,
                            first_seen={"UA-C": "2016-06-30", "UA": "2016-12-30"})
    assert [r.date for r in bound.by_symbol("UA-C")] == ["2016-06-15"]
    assert [r.date for r in bound.by_symbol("UA")] == ["2017-03-01"]
    unbound = FtdIndex.opened(_Client(), date(2016, 6, 1), date(2017, 3, 31), symbols={"UA-C"}, names=names)
    assert [r.date for r in unbound.by_symbol("UA-C")] == ["2016-06-15", "2017-03-01"]


# --- the index's asks and its coverage (step 12: the index is the only reader of the fails files) ----------------

HEADER = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"


class _AskedClient(_CountingClient):
    """A real `FtdClient` over the test's files, counting the files read and recording the filters given."""

    def __init__(self, real: FtdClient) -> None:
        super().__init__(real)
        self.asked: list[tuple[set, set]] = []

    def rows(self, url, *, symbols=None, cusips=None):
        self.asked.append((set(symbols or ()), set(cusips or ())))
        yield from super().rows(url, symbols=symbols, cusips=cusips)


def _files(tmp_path, files: dict[str, list[str]]) -> _AskedClient:
    """SEC's fails files in `tmp_path`: each name (cnsfails201901a, ...) with its data lines, and the index page
    listing them."""
    (tmp_path / "index.html").write_text("".join(f'<a href="/files/data/x/{n}.zip">{n}</a>' for n in files))
    for name, lines in files.items():
        (tmp_path / f"{name}.zip").write_bytes(_zip_bytes({f"{name}.txt": HEADER + "".join(f"{x}\n" for x in lines)}))
    return _AskedClient(FtdClient(tmp_path))


JAN = {"cnsfails201901a": ["20190102|00817Y108|AET|10|AETNA INC|100.00",
                           "20190110|126650100|CVS|10|CVS HEALTH CORP|60.00",
                           "20190114|00817Y108|AET|10|AETNA INC|101.00"],
       "cnsfails201901b": ["20190116|00817Y108|AET|10|AETNA INC|102.00",
                           "20190117|00817Y108|AETX|10|AETNA INC|102.50",
                           "20190130|126650100|CVS|10|CVS HEALTH CORP|61.00"]}


def test_an_opened_index_holds_its_keys_over_the_opening_span_and_follows_them_to_the_run_date(tmp_path):
    """Stage 1 opens the index over [lo, hi]; `follow` reads a key over the run's fails window [lo, through], past
    `hi` (stage 4's CUSIPs, stage 4b's tickers). The window's first day is `opened_from`."""
    c = _files(tmp_path, JAN)
    idx = FtdIndex.opened(c, date(2019, 1, 1), date(2019, 1, 15), through=date(2019, 1, 31), symbols={"AET"})
    assert idx.opened_from == date(2019, 1, 1)
    assert [r.date for r in idx.by_symbol("AET")] == ["2019-01-02", "2019-01-14"]
    idx.follow(symbols={"AET"})
    assert [r.date for r in idx.by_symbol("AET")] == ["2019-01-02", "2019-01-14", "2019-01-16"]
    idx.follow(cusips={"00817Y108"})                 # a CUSIP asked as a CUSIP is found under any symbol
    assert [r.symbol for r in idx.by_cusip("00817Y108")] == ["AET", "AET", "AET", "AETX"]
    assert c.asked[-1] == (set(), {"00817Y108"})


def test_a_query_answers_from_the_rows_held_and_never_reads_the_files(tmp_path):
    """A query asks nothing: a key no ask named has no row, and the files are not read for it (the warm passes
    read the index on worker threads, so a read that loaded would make the output depend on the worker count)."""
    c = _files(tmp_path, JAN)
    idx = FtdIndex.opened(c, date(2019, 1, 1), date(2019, 1, 31), symbols={"AET"})
    calls = c.rows_calls
    assert idx.by_symbol("CVS") == [] and idx.by_cusip("126650100") == []
    assert idx.close_after(date(2019, 1, 9), symbol="CVS") is None
    assert idx.trading_rows(["126650100"]) == [] and idx.descriptions("126650100") == set()
    assert c.rows_calls == calls


def test_around_holds_the_span_from_before_the_earliest_day_to_after_the_latest(tmp_path):
    c = _files(tmp_path, JAN)
    idx = FtdIndex(source=c)
    idx.around([date(2019, 1, 12), date(2019, 1, 14)], before=2, after=2, cusips={"00817Y108"})
    assert [r.date for r in idx.by_cusip("00817Y108")] == ["2019-01-14", "2019-01-16"]     # 01-10 to 01-16
    calls = c.rows_calls
    idx.around([], before=30, after=30, cusips={"00817Y108"})                              # no day: no ask
    idx.around([date(2019, 1, 13)], before=1, after=1, cusips={"00817Y108"})               # held over its span
    assert c.rows_calls == calls


def test_an_index_with_no_source_reads_nothing():
    """An index built from rows holds them; its asks read nothing, it streams nothing, and a separate index of its
    CUSIPs holds only its rows of them."""
    rows = [FtdRow("2019-01-02", "00817Y108", "AET", "AETNA INC", 100.0)]
    idx = FtdIndex(rows)
    idx.follow(cusips={"126650100"})
    idx.around([date(2019, 1, 2)], before=10, after=10, symbols={"CVS"})
    assert idx.by_symbol("CVS") == [] and list(idx.every_row(date(2019, 1, 1), date(2019, 1, 31))) == []
    assert idx.apart([date(2019, 1, 2)], before=5, after=5, cusips={"00817Y108"}).by_cusip("00817Y108") == rows
    assert idx.opened_from is None


def test_apart_reads_cusips_into_a_separate_index_and_leaves_this_one_as_it_was(tmp_path):
    """Stage 8a: an early merger's acquirer lines are read around its days into an index of their own, with the
    rows this index holds of them; this index gains no row, so no later reader of it sees them."""
    c = _files(tmp_path, JAN)
    idx = FtdIndex.opened(c, date(2019, 1, 16), date(2019, 1, 31), cusips={"00817Y108"})
    held = idx.by_cusip("00817Y108")
    own = idx.apart([date(2019, 1, 10)], before=10, after=4, cusips={"00817Y108"})
    assert [r.date for r in own.by_cusip("00817Y108")] == ["2019-01-02", "2019-01-14", "2019-01-16", "2019-01-17"]
    assert idx.by_cusip("00817Y108") == held and idx.apart([], cusips={"00817Y108"}).by_cusip("00817Y108") == []


def test_every_row_streams_the_files_rows_in_the_span_as_spelled_and_holds_none(tmp_path):
    """Stage 8a': every security's rows of a span, as the files spell them (no relabel), held nowhere."""
    c = _files(tmp_path, {"cnsfails201901a": ["20190102|115637209|BFB|10|BROWN-FORMAN CORP CL-B|48.00",
                                              "20190110|126650100|CVS|10|CVS HEALTH CORP|60.00"]})
    idx = FtdIndex.opened(c, date(2019, 1, 1), date(2019, 1, 15), symbols={"BF-B"})
    assert [(r.date, r.symbol) for r in idx.every_row(date(2019, 1, 5), date(2019, 1, 15))] == [("2019-01-10", "CVS")]
    assert [r.symbol for r in idx.every_row(date(2019, 1, 1), date(2019, 1, 3))] == ["BFB"]
    assert idx.by_symbol("CVS") == [] and [r.symbol for r in idx.by_symbol("BF-B")] == ["BF-B"]


def test_a_windowed_query_answers_the_same_whatever_order_the_asks_came_in(tmp_path):
    """The point of step 12: within the spans asked for a key, its rows are every row of the data, so the answer
    does not depend on which ask came first, nor do the coverage statements."""
    def run(order):
        idx = FtdIndex.opened(_files(tmp_path, JAN), date(2019, 1, 1), date(2019, 1, 15), through=date(2019, 1, 31))
        asks = {"follow": lambda: idx.follow(symbols={"AET"}),
                "around": lambda: idx.around([date(2019, 1, 9)], before=8, after=8, cusips={"126650100"})}
        for name in order:
            asks[name]()
        return (idx.by_symbol("AET", "2019-01-01", "2019-01-31"),
                idx.by_cusip("126650100", "2019-01-01", "2019-01-17"),
                idx.opened_from, idx.data_covers("2019-01-20", "2019-01-25"), idx.data_end())

    one = run(["follow", "around"])
    assert one == run(["around", "follow"])
    assert [r.date for r in one[0]] == ["2019-01-02", "2019-01-14", "2019-01-16"] and len(one[1]) == 1


def test_the_opened_window_does_not_move_with_a_later_ask_from_earlier_days(tmp_path):
    """cusip_handoffs' margin reads the window the index was opened over; an ask from earlier days (stages 5b, 7)
    does not move it, so the margin test answers the same wherever it runs."""
    files = {"cnsfails201812b": ["20181220|00817Y108|AET|10|AETNA INC|99.00"], **JAN}
    idx = FtdIndex.opened(_files(tmp_path, files), date(2019, 1, 1), date(2019, 1, 31), symbols={"AET"})
    idx.around([date(2018, 12, 20)], before=5, after=5, symbols={"AET"})
    assert idx.opened_from == date(2019, 1, 1) and idx.by_symbol("AET")[0].date == "2018-12-20"


def test_the_fails_datas_coverage_is_its_file_index_up_to_the_run_date_not_the_rows_held(tmp_path):
    """`data_covers` and `data_end` read the periods of SEC's files, up to the run date: a span with no row held
    (no key failed then, or none was asked) is still covered, and the data ends on the last period's end, or on the
    run date inside a period."""
    c = _files(tmp_path, JAN)
    idx = FtdIndex.opened(c, date(2019, 1, 1), date(2019, 1, 31), symbols={"ZZZ"})          # holds no row
    assert idx.data_covers("2019-01-03", "2019-01-04") and idx.data_end() == "2019-01-31"
    assert not idx.data_covers("2019-02-01", "2019-02-28") and not idx.data_covers("2018-12-01", "2018-12-31")
    early = FtdIndex.opened(c, date(2019, 1, 1), date(2019, 1, 20), symbols={"AET"})       # the run date 2019-01-20
    assert early.data_end() == "2019-01-20" and not early.data_covers("2019-01-21", "2019-01-31")


def test_an_index_with_no_file_index_states_its_rows_held_as_its_coverage():
    """An index built from rows, or over a double whose files carry no period, has no file index: its rows held are
    all its data, so `data_covers` asks whether one is dated in the span and `data_end` is the latest."""
    rows = [FtdRow("2019-01-02", "00817Y108", "AET", "AETNA INC", 100.0),
            FtdRow("2019-01-14", "00817Y108", "AET", "AETNA INC", 101.0)]

    class _Double:
        def urls_for(self, lo, hi):
            return ["mem"]

        def rows(self, url, *, symbols=None, cusips=None):
            yield from (r for r in rows if cusips and r.cusip in cusips)

    for idx in (FtdIndex(rows), FtdIndex.opened(_Double(), date(2019, 1, 1), date(2019, 1, 31), cusips={"00817Y108"})):
        assert idx.data_end() == "2019-01-14"
        assert idx.data_covers("2019-01-10", "2019-01-14") and not idx.data_covers("2019-01-03", "2019-01-13")
    assert FtdIndex().data_end() is None and not FtdIndex().data_covers("2019-01-01", "2019-12-31")


def test_a_windowless_query_answers_every_row_held_so_its_answer_depends_on_what_was_asked_before_it(tmp_path):
    """Kept as it was (step 12's log): `by_cusip(c)` with no span gives every row held of `c`, those another key's
    ask brought in too: a CUSIP's rows under a symbol asked for earlier days join it."""
    files = {"cnsfails201812b": ["20181220|00817Y108|AET|10|AETNA INC|99.00"], **JAN}
    idx = FtdIndex.opened(_files(tmp_path, files), date(2019, 1, 1), date(2019, 1, 31), cusips={"00817Y108"})
    before = [r.date for r in idx.by_cusip("00817Y108")]
    idx.around([date(2018, 12, 20)], before=5, after=5, symbols={"AET"})
    assert before == ["2019-01-02", "2019-01-14", "2019-01-16", "2019-01-17"]
    assert [r.date for r in idx.by_cusip("00817Y108")] == ["2018-12-20", *before]


def test_a_bare_spelled_row_held_before_its_class_ticker_was_asked_is_held_again_relabelled(tmp_path):
    """Kept as it was (step 12's log): a row is relabelled when it is added, with the spellings learned by then. A
    CUSIP asked first holds Brown-Forman's "BFB" row as "BFB"; a later ask for "BF-B" reads it again as "BF-B", a
    second row. Asked the other way round, the CUSIP's row is the relabelled one, once."""
    files = {"cnsfails201901a": ["20190102|115637209|BFB|10|BROWN-FORMAN CORP CL-B|48.00"]}

    def held(order):
        idx = FtdIndex(source=_files(tmp_path, files))
        for kind in order:
            idx.around([date(2019, 1, 1), date(2019, 1, 15)],
                       **({"cusips": {"115637209"}} if kind == "cusip" else {"symbols": {"BF-B"}}))
        return [r.symbol for r in idx.by_cusip("115637209")]

    assert held(["cusip", "symbol"]) == ["BF-B", "BFB"]
    assert held(["symbol", "cusip"]) == ["BF-B"]


def test_a_query_only_reads_so_threads_querying_at_once_see_the_asked_rows():
    """Final review M1: every ask leaves its rows sorted, so a query never sorts a list another thread is reading
    (CPython empties a list while it sorts it). Eight threads querying the keys of an ask at once, switching as
    often as the interpreter can, each see every row, in order."""
    import sys
    import threading
    rows = [FtdRow(f"2019-01-{d:02d}", f"C{k:04d}", f"S{k:04d}", "X CO", 1.0) for k in range(400)
            for d in (17, 3, 28, 9, 22, 14, 2, 30, 5, 11, 19, 25)]

    class _Client:
        def urls_for(self, lo, hi):
            return ["mem"]

        def rows(self, url, *, symbols=None, cusips=None):
            yield from rows

    idx = FtdIndex(source=_Client())
    idx.around([date(2019, 1, 15)], before=20, after=20, cusips={r.cusip for r in rows})
    want = {c: sorted(r.date for r in rows if r.cusip == c) for c in {r.cusip for r in rows}}
    seen, start = [], threading.Barrier(8)

    def query():
        start.wait()
        seen.append({c: [r.date for r in idx.by_cusip(c)] for c in want})
    threads = [threading.Thread(target=query) for _ in range(8)]
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(interval)
    assert len(seen) == 8 and all(got == want for got in seen)

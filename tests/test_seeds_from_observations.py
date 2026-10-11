import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "seeds_from_observations", Path(__file__).resolve().parents[1] / "scripts" / "seeds_from_observations.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _o(ticker, as_of, name):
    return {"ticker": ticker, "as_of": as_of, "name": name, "cusip": "", "cik": "", "sec_id": ""}


def test_a_seed_is_a_first_sighting_a_return_or_a_new_name():
    rows = [_o("AAA", "2010-06-30", "ALPHA CORP"), _o("AAA", "2010-12-31", "ALPHA CORP"),
            _o("BBB", "2010-06-30", "BETA INC"), _o("BBB", "2011-06-30", "BETA INC"),
            _o("AAA", "2011-06-30", "ZETA HOLDINGS"), _o("CCC", "2010-12-31", "")]
    assert [(r["ticker"], r["as_of"]) for r in mod.seeds(rows)] == [
        ("AAA", "2010-06-30"), ("AAA", "2011-06-30"), ("BBB", "2010-06-30"), ("BBB", "2011-06-30"),
        ("CCC", "2010-12-31")]


def _h(sec_id, ticker, start, end=""):
    return {"sec_id": sec_id, "issuer_id": "1", "start_date": start, "end_date": end, "ticker": ticker,
            "security_name": "", "share_class": "COMMON"}


def _keys(rows):
    return [(r["ticker"], r["as_of"]) for r in rows]


FOXA = [_o("FOXA", "2018-06-30", "TWENTY FIRST CENTURY FOX INC CLASS A"),      # the same class on both sides:
        _o("FOXA", "2018-12-31", "TWENTY FIRST CENTURY FOX INC CLASS A"),      # only the holder rule is under test
        _o("FOXA", "2019-06-30", "FOX CORP CLASS A"), _o("FOXA", "2019-12-31", "FOX CORP CLASS A")]


def test_without_a_history_the_fox_rows_give_one_seed():
    assert _keys(mod.seeds(FOXA)) == [("FOXA", "2018-06-30")]
    assert _keys(mod.seeds(FOXA, history=None)) == [("FOXA", "2018-06-30")]


def test_a_row_is_a_seed_when_another_security_holds_its_ticker_than_on_the_previous_snapshot():
    """FOXA 2019: Twenty-First Century Fox to 2019-03-19, the Fox Corp line after."""
    history = [_h("BBGOLD", "FOXA", "2013-07-03", "2019-03-19"), _h("BBGNEW", "FOXA", "2019-03-20")]
    assert _keys(mod.seeds(FOXA, history=history)) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]


def test_a_row_after_its_tickers_line_ended_is_a_seed_once():
    """The previous run ended the line and has no line after it: the first snapshot past the end is a seed, and
    so is the next (nobody held the ticker on the first one: it cannot tell the two lines apart), but only
    that one (rule 4 is not triggered by its own seed)."""
    history = [_h("BBGOLD", "FOXA", "2013-07-03", "2019-03-19")]
    assert _keys(mod.seeds(FOXA, history=history)) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30"),
                                                       ("FOXA", "2019-12-31")]
    longer = [*FOXA, _o("FOXA", "2020-06-30", "FOX CORP CLASS A")]
    assert _keys(mod.seeds(longer, history=history))[-2:] == [("FOXA", "2019-06-30"), ("FOXA", "2019-12-31")]


def test_one_security_under_the_ticker_all_along_gives_no_extra_seed():
    history = [_h("BBGONE", "FOXA", "2013-07-03", "2018-12-31"), _h("BBGONE", "FOXA", "2019-01-01")]
    assert _keys(mod.seeds(FOXA, history=history)) == [("FOXA", "2018-06-30")]
    assert _keys(mod.seeds(FOXA, history=[_h("BBGX", "ZZZ", "2000-01-03")])) == [("FOXA", "2018-06-30")]


def test_the_span_ends_are_inside_and_two_holders_are_a_set():
    rows = [_o("AAA", "2010-06-30", "ALPHA"), _o("AAA", "2010-12-31", "ALPHA"), _o("AAA", "2011-06-30", "ALPHA")]
    exact = [_h("S1", "AAA", "2010-06-30", "2010-12-31"), _h("S2", "AAA", "2011-01-01")]
    assert _keys(mod.seeds(rows, history=exact)) == [("AAA", "2010-06-30"), ("AAA", "2011-06-30")]
    both = [_h("S1", "AAA", "2010-01-04"), _h("S2", "AAA", "2010-01-04")]
    assert _keys(mod.seeds(rows, history=both)) == [("AAA", "2010-06-30")]
    joins = [_h("S1", "AAA", "2010-01-04"), _h("S2", "AAA", "2011-01-03")]
    assert _keys(mod.seeds(rows, history=joins)) == [("AAA", "2010-06-30"), ("AAA", "2011-06-30")]


def test_a_changed_identifier_is_a_seed_and_a_blank_one_is_not():
    def row(as_of, **pins):
        return {**_o("AAA", as_of, "ALPHA"), **pins}
    rows = [row("2010-06-30", cusip="111111111"), row("2010-12-31"), row("2011-06-30", cusip="111111111"),
            row("2011-12-31", cusip="222222222"), row("2012-06-30", cik="5"), row("2012-12-31", cik="6"),
            row("2013-06-30", sec_id="BBG1"), row("2013-12-31", sec_id="BBG1")]
    assert _keys(mod.seeds(rows)) == [("AAA", "2010-06-30"), ("AAA", "2011-12-31"), ("AAA", "2012-12-31")]
    bare = [{"ticker": "AAA", "as_of": d, "name": "ALPHA"} for d in ("2010-06-30", "2010-12-31")]
    assert _keys(mod.seeds(bare)) == [("AAA", "2010-06-30")]            # a file without pin columns


def _write_obs(path):
    import csv
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(FOXA[0]))
        w.writeheader()
        w.writerows(FOXA)


def test_the_cli_reads_the_history_file(tmp_path, monkeypatch, capsys):
    import csv
    obs, hist, out = tmp_path / "obs.csv", tmp_path / "security_history.csv", tmp_path / "seeds.csv"
    _write_obs(obs)
    with hist.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(_h("x", "x", "x")))
        w.writeheader()
        w.writerows([_h("BBGOLD", "FOXA", "2013-07-03", "2019-03-19"), _h("BBGNEW", "FOXA", "2019-03-20")])
    monkeypatch.setattr("sys.argv", ["seeds_from_observations.py", "--observations", str(obs), "--out", str(out),
                                     "--security-history", str(hist)])
    assert mod.main() == 0
    with out.open(newline="") as fh:
        assert _keys(list(csv.DictReader(fh))) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]
    assert "2 seeds from 4 observations" in capsys.readouterr().out


def test_a_history_file_missing_a_column_exits_2_naming_file_and_column(tmp_path, monkeypatch, capsys):
    obs, hist, out = tmp_path / "obs.csv", tmp_path / "security_history.csv", tmp_path / "seeds.csv"
    _write_obs(obs)
    hist.write_text("sec_id,start_date,end_date\nBBG1,2013-07-03,\n")
    monkeypatch.setattr("sys.argv", ["seeds_from_observations.py", "--observations", str(obs), "--out", str(out),
                                     "--security-history", str(hist)])
    assert mod.main() == 2
    err = capsys.readouterr().err
    assert str(hist) in err and "ticker" in err
    assert not out.exists()


def test_the_history_is_read_through_the_tickers_normal_spelling():
    rows = [_o("BF.B", "2010-06-30", "BROWN FORMAN"), _o("BF.B", "2010-12-31", "BROWN FORMAN"),
            _o("BF.B", "2011-06-30", "BROWN FORMAN")]
    history = [_h("S1", "BF-B", "2010-01-04", "2010-12-31"), _h("S2", "BF-B", "2011-01-03")]
    assert _keys(mod.seeds(rows, history=history)) == [("BF.B", "2010-06-30"), ("BF.B", "2011-06-30")]
    lower = [{**r, "ticker": "bf b"} for r in rows]
    assert _keys(mod.seeds(lower, history=history)) == [("bf b", "2010-06-30"), ("bf b", "2011-06-30")]


def test_two_rows_on_one_date_and_overlapping_spans_of_one_security():
    rows = [_o("AAA", "2010-06-30", "ALPHA"), _o("AAA", "2010-12-31", "ALPHA"), _o("AAA", "2010-12-31", "ALPHA")]
    history = [_h("S1", "AAA", "2010-01-04", "2010-12-31"), _h("S1", "AAA", "2010-06-01")]
    assert _keys(mod.seeds(rows, history=history)) == [("AAA", "2010-06-30")]


def test_a_row_whose_name_changes_only_its_class_words_is_a_seed():
    rows = [_o("DISCA", "2008-12-31", "DISCOVERY HOLDING CO"), _o("DISCA", "2009-06-30", "DISCOVERY HOLDING CO"),
            _o("DISCA", "2009-12-31", "DISCOVERY INC SERIES A"), _o("DISCA", "2010-06-30", "DISCOVERY INC SERIES A")]
    assert mod.names_agree(rows[1]["name"], rows[2]["name"])            # the name rule alone does not cut here
    assert _keys(mod.seeds(rows)) == [("DISCA", "2008-12-31"), ("DISCA", "2009-12-31")]
    blank = [_o("AAA", "2010-06-30", "ALPHA CORP CLASS A"), _o("AAA", "2010-12-31", ""),
             _o("AAA", "2011-06-30", "ALPHA CORP CLASS A")]
    assert _keys(mod.seeds(blank)) == [("AAA", "2010-06-30")]            # a blank name is no class change


def test_the_row_after_an_unheld_seed_is_a_seed_once():
    """GCI 2015: old Gannett held the ticker to 2015-06-26 and the previous run has no line after it."""
    rows = [_o("GCI", d, "GANNETT CO INC") for d in ("2014-12-31", "2015-06-30", "2015-12-31", "2016-06-30")]
    history = [_h("BBGOLD", "GCI", "2008-01-02", "2015-06-26")]
    assert _keys(mod.seeds(rows, history=history)) == [("GCI", "2014-12-31"), ("GCI", "2015-06-30"),
                                                       ("GCI", "2015-12-31")]
    held = [_h("BBGOLD", "GCI", "2008-01-02", "2015-06-26"), _h("BBGNEW", "GCI", "2015-06-29")]
    assert _keys(mod.seeds(rows, history=held)) == [("GCI", "2014-12-31"), ("GCI", "2015-06-30")]
    assert _keys(mod.seeds(rows)) == [("GCI", "2014-12-31")]             # no history: rule 4 is off


def test_a_name_cut_inside_its_class_words_reads_as_common_stock_and_the_full_class_words_cut():
    """The observation file cuts long names ("... INC CLASS"); the class reader gives such a name common stock, so the
    class rule fires at the first snapshot whose name carries the full class words ("FOX CORP CLASS A"). Accepted: the
    row is one of the caller's own observations."""
    rows = [_o("FOXA", "2018-06-30", "TWENTY FIRST CENTURY FOX INC CLASS"),
            _o("FOXA", "2018-12-31", "TWENTY FIRST CENTURY FOX INC CLASS"),
            _o("FOXA", "2019-06-30", "FOX CORP CLASS A"), _o("FOXA", "2019-12-31", "FOX CORP CLASS A")]
    assert _keys(mod.seeds(rows)) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]

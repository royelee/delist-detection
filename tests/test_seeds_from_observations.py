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


# The fixed point: seeds without a history, a run, then seeds again with each run's history, adding seeds until a
# pass adds none. Here the run is a function; the CLI's run is classify_universe.py.

SWITCH = [_h("BBGOLD", "FOXA", "2013-07-03", "2019-03-19"), _h("BBGNEW", "FOXA", "2019-03-20")]
ONE = [_h("BBGOLD", "FOXA", "2013-07-03")]


def test_the_fixed_point_adds_holder_seeds_until_a_pass_adds_none():
    seen = []

    def run(seed_rows, k):
        seen.append((k, _keys(seed_rows)))
        return SWITCH
    out, passes = mod.fixed_point(FOXA, run)
    assert _keys(out) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]
    assert seen == [(1, [("FOXA", "2018-06-30")]), (2, [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")])]
    assert passes == [{"pass": 1, "seeds": 1, "added": 1}, {"pass": 2, "seeds": 2, "added": 0}]


def test_a_seed_a_pass_added_stays_when_a_later_history_no_longer_calls_for_it():
    histories = {1: SWITCH, 2: ONE}
    out, passes = mod.fixed_point(FOXA, lambda seed_rows, k: histories[k])
    assert _keys(out) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]
    assert [p["added"] for p in passes] == [1, 0]


def test_no_holder_change_means_one_run_and_the_plain_seeds():
    out, passes = mod.fixed_point(FOXA, lambda seed_rows, k: ONE)
    assert _keys(out) == _keys(mod.seeds(FOXA))
    assert passes == [{"pass": 1, "seeds": 1, "added": 0}]


def test_the_fixed_point_keeps_the_seed_order_and_the_callers_rows():
    rows = FOXA + [_o("BBB", "2010-06-30", "BETA INC")]
    out, _ = mod.fixed_point(rows, lambda seed_rows, k: SWITCH)
    assert _keys(out) == [("BBB", "2010-06-30"), ("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]
    assert all(any(r is o for o in rows) for r in out)


def _one_more_each_pass(seed_rows, k):
    """Each seed held for its own day only, and a new holder from the day after the last seed: the run after a pass
    always finds the next row's holder changed."""
    from datetime import date, timedelta
    last = date.fromisoformat(seed_rows[-1]["as_of"]) + timedelta(days=1)
    return ([_h(f"BBG{i}", "AAA", r["as_of"], r["as_of"]) for i, r in enumerate(seed_rows)]
            + [_h("BBGNEXT", "AAA", last.isoformat())])


def test_a_loop_still_adding_at_the_cap_raises_and_one_given_room_ends():
    rows = [_o("AAA", d, "ALPHA CORP") for d in ("2010-06-30", "2010-12-31", "2011-06-30", "2011-12-31")]
    try:
        mod.fixed_point(rows, _one_more_each_pass, max_passes=2)
    except mod.NoFixedPoint as exc:
        assert "2 passes" in str(exc)
    else:
        raise AssertionError("expected NoFixedPoint")
    out, passes = mod.fixed_point(rows, _one_more_each_pass, max_passes=4)
    assert _keys(out) == _keys(rows)
    assert [p["added"] for p in passes] == [1, 1, 1, 0]


def _fake_classify(histories, calls):
    """A stand-in for classify_universe.py: writes the pass's history where a run writes it."""
    def run_classify(seed_path, out_dir, run_args, log_path):
        import csv
        calls.append((Path(seed_path).name, Path(out_dir).name, list(run_args)))
        k = len(calls)
        (Path(out_dir) / "contract").mkdir(parents=True, exist_ok=True)
        with (Path(out_dir) / "contract" / "security_history.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(_h("x", "x", "x")))
            w.writeheader()
            w.writerows(histories[k])
        Path(log_path).write_text("ok\n")
        return 3 if k == 1 else 0                       # a completed run with review rows counts as a run
    return run_classify


def test_the_cli_fixed_point_runs_each_pass_and_writes_the_last_seed_file(tmp_path, monkeypatch, capsys):
    import csv
    obs, out, work = tmp_path / "obs.csv", tmp_path / "seeds.csv", tmp_path / "fp"
    _write_obs(obs)
    calls = []
    monkeypatch.setattr(mod, "run_classify", _fake_classify({1: SWITCH, 2: SWITCH}, calls))
    monkeypatch.setattr("sys.argv", ["seeds_from_observations.py", "--observations", str(obs), "--out", str(out),
                                     "--fixed-point", str(work), "--", "--as-of", "2026-09-25", "--sec-workers", "1"])
    assert mod.main() == 0
    assert calls == [("seeds-1.csv", "run-1", ["--as-of", "2026-09-25", "--sec-workers", "1"]),
                     ("seeds-2.csv", "run-2", ["--as-of", "2026-09-25", "--sec-workers", "1"])]
    with out.open(newline="") as fh:
        assert _keys(list(csv.DictReader(fh))) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]
    assert out.read_text() == (work / "seeds-2.csv").read_text()
    with (work / "passes.csv").open(newline="") as fh:
        assert list(csv.DictReader(fh)) == [{"pass": "1", "seeds": "1", "added": "1", "exit": "3"},
                                            {"pass": "2", "seeds": "2", "added": "0", "exit": "0"}]
    assert "run-2" in capsys.readouterr().out          # the last run is the seeds run on the fixed point


def test_the_cli_stops_at_a_failed_run_and_writes_no_seed_file(tmp_path, monkeypatch, capsys):
    obs, out, work = tmp_path / "obs.csv", tmp_path / "seeds.csv", tmp_path / "fp"
    _write_obs(obs)
    monkeypatch.setattr(mod, "run_classify", lambda seed_path, out_dir, run_args, log_path: 4)
    monkeypatch.setattr("sys.argv", ["seeds_from_observations.py", "--observations", str(obs), "--out", str(out),
                                     "--fixed-point", str(work)])
    assert mod.main() == 4
    assert not out.exists()
    assert "run-1" in capsys.readouterr().err


def test_the_cli_refuses_a_fixed_point_with_a_history_or_with_the_runs_own_paths(tmp_path, monkeypatch):
    obs, out, work = tmp_path / "obs.csv", tmp_path / "seeds.csv", tmp_path / "fp"
    _write_obs(obs)

    def no_run(*args):
        raise AssertionError("no run expected")
    monkeypatch.setattr(mod, "run_classify", no_run)
    base = ["seeds_from_observations.py", "--observations", str(obs), "--out", str(out), "--fixed-point", str(work)]
    for argv in (base + ["--security-history", str(obs)], base + ["--", "--output-dir", "x"],
                 base + ["--", "--observations", "x"]):
        monkeypatch.setattr("sys.argv", argv)
        assert mod.main() == 2
    assert not out.exists()


# The warm start: pass 1 also starts with the rows of an earlier fixed point's seed file.

def _warm_cli(tmp_path, monkeypatch, warm_rows, histories):
    import csv
    obs, out, work, warm = tmp_path / "obs.csv", tmp_path / "seeds.csv", tmp_path / "fp", tmp_path / "warm.csv"
    _write_obs(obs)
    with warm.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(FOXA[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(warm_rows)
    calls = []
    monkeypatch.setattr(mod, "run_classify", _fake_classify(histories, calls))
    monkeypatch.setattr("sys.argv", ["seeds_from_observations.py", "--observations", str(obs), "--out", str(out),
                                     "--fixed-point", str(work), "--warm-start", str(warm)])
    return out, work, warm, calls


WARM_ROWS = [FOXA[0], FOXA[2]]


def test_a_warm_start_from_a_fixed_points_file_stops_after_one_pass(tmp_path, monkeypatch, capsys):
    import csv
    out, work, warm, calls = _warm_cli(tmp_path, monkeypatch, WARM_ROWS, {1: SWITCH})
    assert mod.main() == 0
    assert [c[1] for c in calls] == ["run-1"]
    with (work / "passes.csv").open(newline="") as fh:
        assert list(csv.DictReader(fh)) == [{"pass": "1", "seeds": "2", "added": "0", "exit": "3",
                                             "warm_start": str(warm)}]
    said = capsys.readouterr().out
    assert f"fixed point after 1 passes (WARM-STARTED from {warm}" in said and "not an acceptance one" in said


def test_the_warm_starts_rows_are_kept_when_the_history_does_not_call_for_them(tmp_path, monkeypatch):
    import csv
    out, work, warm, calls = _warm_cli(tmp_path, monkeypatch, WARM_ROWS, {1: ONE})
    assert mod.main() == 0
    with out.open(newline="") as fh:
        assert _keys(list(csv.DictReader(fh))) == [("FOXA", "2018-06-30"), ("FOXA", "2019-06-30")]
    cold, _ = mod.fixed_point(FOXA, lambda seed_rows, k: ONE)
    assert _keys(cold) == [("FOXA", "2018-06-30")]          # the cold start would not have kept the second row


def test_a_warm_start_row_that_is_not_an_observation_exits_2_naming_file_and_line(tmp_path, monkeypatch, capsys):
    other = {**FOXA[2], "name": "FOX CORP CLASS B"}
    out, work, warm, calls = _warm_cli(tmp_path, monkeypatch, [FOXA[0], other], {1: ONE})
    assert mod.main() == 2
    assert capsys.readouterr().err.strip().splitlines() == [f"{warm}:3: not a row of the observations"]
    assert calls == [] and not out.exists()


def test_the_cold_start_is_unchanged(tmp_path, monkeypatch, capsys):
    import csv
    obs, out, work, calls = tmp_path / "obs.csv", tmp_path / "seeds.csv", tmp_path / "fp", []
    _write_obs(obs)
    monkeypatch.setattr(mod, "run_classify", _fake_classify({1: SWITCH, 2: SWITCH}, calls))
    monkeypatch.setattr("sys.argv", ["seeds_from_observations.py", "--observations", str(obs), "--out", str(out),
                                     "--fixed-point", str(work)])
    assert mod.main() == 0
    assert [c[1] for c in calls] == ["run-1", "run-2"]
    with (work / "passes.csv").open(newline="") as fh:
        assert list(csv.DictReader(fh)) == [{"pass": "1", "seeds": "1", "added": "1", "exit": "3"},
                                            {"pass": "2", "seeds": "2", "added": "0", "exit": "0"}]
    assert "WARM" not in capsys.readouterr().out

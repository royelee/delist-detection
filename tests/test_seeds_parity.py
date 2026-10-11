import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seeds_parity.py"
SPEC = importlib.util.spec_from_file_location("seeds_parity", SCRIPT)
seeds_parity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seeds_parity)

END_COLS = "sec_id,last_trade_date,exit_kind,continuation,dlret,verdict"


def _run(folder: Path, endings: list[str], securities: list[str], seeds: list[str], failures: list[str]) -> Path:
    (folder / "contract").mkdir(parents=True)
    (folder / "contract" / "delistings.csv").write_text("\n".join([END_COLS, *endings]) + "\n")
    (folder / "contract" / "seeds.csv").write_text("\n".join(["ticker,as_of,sec_id", *seeds]) + "\n")
    (folder / "securities.csv").write_text("\n".join(["sec_id,observed", *securities]) + "\n")
    (folder / "scorecard.json").write_text(json.dumps({
        "metrics": {"L1": {"coverage_tickers": 1.0, "coverage_securities": 1.0, "left_view": 0, "closed_no_event": 0}},
        "golden_failures": failures, "diagnosis_failures": []}))
    return folder


def _two_runs(tmp_path: Path) -> tuple[Path, Path]:
    full = _run(tmp_path / "full",
                ["A,2008-12-31,merger,,0.07,confirmed",          # lost in seeds: the security is there, no ending
                 "B,2016-01-04,exchange,true,,confirmed",        # a continuation in full, a merger in seeds
                 "C,2012-03-05,merger,,0.0100,confirmed",        # same kind, another dlret
                 "D,2013-05-30,merger,,-0.059263,confirmed",     # same kind, dlret differs in the sixth decimal only
                 "E,2019-07-31,merger,,0.02,confirmed"],         # its security is not in the seeds run at all
                ["A,true", "B,true", "C,true", "D,true", "E,true"], ["AAA,2008-01-16,A", "BBB,2014-06-30,B"], [])
    seeds = _run(tmp_path / "seeds",
                 ["B,2016-01-04,merger,,0.0,confirmed",
                  "C,2012-03-05,merger,,,uncertain",
                  "D,2013-05-30,merger,,-0.059264,confirmed",
                  "F,2010-01-04,dropped,,,uncertain"],           # an ending on a security only the seeds run has
                 ["A,true", "B,false", "C,true", "D,true", "F,false"], ["AAA,2008-01-16,A", "BBB,2014-06-30,X"],
                 ["CLWR: no single security traded CLWR on 2012-06-29"])
    return full, seeds


def test_parity_counts_each_kind_of_difference(tmp_path):
    full, seeds = _two_runs(tmp_path)
    got = seeds_parity.parity(full, seeds)
    assert got["numbers"] == {
        "endings_lost": 1, "endings_gained": 0, "kind_changed": 1, "value_or_date_changed": 1,
        "securities_lost": 1, "securities_gained": 1, "seeds_placed_differently": 1,
        "truth_cases_failing_only_in_seeds": 1, "observed_flag_differs": 1,
    }
    assert [r["sec_id"] for r in got["cases"]["endings_lost"]] == ["A"]
    assert got["cases"]["kind_changed"][0]["full_kind"] == "exchange/continuation"
    assert [r["sec_id"] for r in got["cases"]["value_or_date_changed"]] == ["C"]     # D is within the tolerance
    assert got["cases"]["securities_lost"] == [{"sec_id": "E", "full_ending": "merger"}]
    # E (only in full) and F (only in seeds) are counted by securities_lost / securities_gained, not here
    assert got["cases"]["observed_flag_differs"] == [{"sec_id": "B", "full_observed": "true", "seeds_observed": "false"}]


def test_check_fails_only_above_the_floor(tmp_path, capsys):
    full, seeds = _two_runs(tmp_path)
    floor = tmp_path / "floor.json"
    args = ["--full", str(full), "--seeds", str(seeds), "--floor", str(floor)]
    assert seeds_parity.main([*args, "--check"]) == 0            # no floor yet: nothing to be above
    assert seeds_parity.main([*args, "--write-floor"]) == 0
    assert json.loads(floor.read_text())["endings_lost"] == 1
    assert "observed_flag_differs" not in json.loads(floor.read_text())          # reported, never floored
    floor.write_text(json.dumps({"endings_lost": 1, "observed_flag_differs": 0}))
    assert seeds_parity.main([*args, "--check"]) == 0                             # above a floor it was given: still no drop
    assert seeds_parity.main([*args, "--write-floor"]) == 0
    assert seeds_parity.main([*args, "--check"]) == 0
    floor.write_text(json.dumps({"endings_lost": 0}))
    assert seeds_parity.main([*args, "--check"]) == 1
    assert "parity drop: endings_lost: 0 -> 1" in capsys.readouterr().err


def test_a_folder_that_is_not_a_run_exits_2(tmp_path, capsys):
    assert seeds_parity.main(["--full", str(tmp_path / "nope"), "--seeds", str(tmp_path / "nope")]) == 2
    assert "cannot read the runs" in capsys.readouterr().err


def test_a_security_file_without_an_observed_column_counts_no_difference(tmp_path):
    full, seeds = _two_runs(tmp_path)
    (seeds / "securities.csv").write_text("\n".join(["sec_id", "A", "B", "C", "D", "F"]) + "\n")
    got = seeds_parity.parity(full, seeds)
    assert got["numbers"]["observed_flag_differs"] == 4          # "true" in full against "" in seeds, A to D
    (full / "securities.csv").write_text("\n".join(["sec_id", "A", "B", "C", "D", "E"]) + "\n")
    got = seeds_parity.parity(full, seeds)
    assert got["numbers"]["observed_flag_differs"] == 0          # neither run has the column: nothing differs


def test_write_floor_writes_the_committed_floors_eight_keys_and_check_still_holds_them(tmp_path):
    committed = Path(seeds_parity.DEFAULT_FLOOR)
    keys = list(json.loads(committed.read_text()))
    full, seeds = _two_runs(tmp_path)
    floor = tmp_path / "floor.json"
    args = ["--full", str(full), "--seeds", str(seeds), "--floor", str(floor)]
    assert seeds_parity.main([*args, "--write-floor"]) == 0
    written = json.loads(floor.read_text())
    assert list(written) == keys and len(keys) == 8                       # the same keys, the same order
    assert floor.read_text() == json.dumps(written, indent=2, sort_keys=True) + "\n"    # the same format
    floor.write_text(json.dumps({k: 99 for k in keys}))
    assert seeds_parity.main([*args, "--check"]) == 0                     # the ninth number cannot fail it
    floor.write_text(json.dumps({**{k: 99 for k in keys}, "kind_changed": 0}))
    assert seeds_parity.main([*args, "--check"]) == 1                     # a floored number still does

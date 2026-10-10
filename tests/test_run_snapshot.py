"""run_snapshot: every table one run wrote, read once, through three adapters (an output folder, a git commit's copy
of it, the rows the pipeline is about to write), with the older-schema rule and the manifest's two fields."""
import json
import os
import subprocess
from datetime import date

import pytest

from delist_detection.outputs import manifest, store
from delist_detection.vocabulary.exit_kind import ContinuationReading
from delist_detection.outputs.run_snapshot import (CONTRACT_SCHEMA_1, FIRST_TABLES, RunSnapshot, SnapshotError,
                                           continuation_entries, continuation_readings, ticker_ranges)
from tests.lifecycle_tables import contract_row, ending, hist, iv, obs, sec

WRITTEN = [n for n, spec in store.TABLES.items() if spec.written]


def _range(sec_id, ticker, start, end):
    """A ticker_history row as a snapshot of a written folder rebuilds it: no exchange, no source."""
    return {"sec_id": sec_id, "ticker": ticker, "exchange": "", "valid_from": start, "valid_to": end, "source": ""}


READINGS = {("A", "2016-05-18"): ContinuationReading(doubt="ratio:0.9042"),
            ("B", "2021-03-14"): ContinuationReading(filing="8-K 0001193125-21-063792")}


def _rows():
    """One run's tables, unformatted as the pipeline holds them (a float, a bool, a date, a None)."""
    return {
        "securities": [sec("B"), {**sec("A"), "observed": True}],
        "ticker_history": [iv("A", "AAA", date(2010, 1, 4), "2016-05-18")],
        "cusip_history": [{"sec_id": "A", "cusip": "000000001", "valid_from": "2010-01-04", "valid_to": None,
                           "source": "ftd"}],
        "delistings": [ending("A", "2016-05-18", dlret=0.25, ltd="2016-05-18")],
        "review": [{"severity": "check", "sec_id": "B"}, {"severity": "fix", "sec_id": "A"}],
        "review_summary": [],
        "observation_map": [obs("AAA", "2010-06-30", "A")],
        "uncertain": [],
        "security_history": [hist("A", "100", "2010-01-04", "2016-05-18")],
        "contract_delistings": [contract_row("A", exit_kind="merger", value_rule="cash", cash_per_share=12.5)],
        "seeds": [],
        "price_requests": [],
        "id_changes": [],
        "payout_legs": [{"sec_id": "A", "leg": 1, "ratio": 0.5, "price_ticker": "X"}],
    }


def _write_run(out, tables=None, readings=READINGS, as_of=date(2026, 9, 25)):
    store.write_tables(out, _rows() if tables is None else tables)
    manifest.write(out, manifest.build(as_of=as_of, sec_workers=1, counts={}, timings={}, stages={},
                                       review_flags={}, review={}, continuation_filings=continuation_entries(readings)))


# -- the interface ------------------------------------------------------------------------------------------------
def test_every_store_table_is_an_attribute():
    snap = RunSnapshot.of(_rows())
    for name in store.TABLES:
        assert getattr(snap, name) == snap.table(name) == store.formatted(name, _rows()[name])
    with pytest.raises(KeyError):
        snap.table("prices")


# -- the folder adapter -------------------------------------------------------------------------------------------
def test_the_folder_reads_every_table_the_run_wrote_and_its_manifest(tmp_path):
    _write_run(tmp_path)
    snap = RunSnapshot.read(tmp_path)
    for name in WRITTEN:
        assert snap.table(name) == store.read_table(name, store.table_path(tmp_path, name))
    assert not store.table_path(tmp_path, "ticker_history").exists()      # never written; rebuilt from the contract
    assert snap.ticker_history == [_range("A", "AAA", "2010-01-04", "2016-05-18")]
    assert snap.as_of == date(2026, 9, 25)
    assert snap.continuations == READINGS
    assert snap.review[0]["severity"] == "check"                # review.csv keeps the order it was written in


def test_the_folder_reads_a_table_once(tmp_path):
    _write_run(tmp_path)
    snap = RunSnapshot.read(tmp_path)
    first = snap.delistings
    store.table_path(tmp_path, "delistings").unlink()
    assert snap.delistings is first


def test_a_folder_that_is_not_there_is_refused(tmp_path):
    with pytest.raises(SnapshotError, match="no such output folder"):
        RunSnapshot.read(tmp_path / "missing")


def test_a_folder_without_a_manifest_is_dated_today_with_no_readings(tmp_path):
    store.write_tables(tmp_path, _rows())
    snap = RunSnapshot.read(tmp_path)
    assert snap.as_of == date.today() and snap.continuations == {}


@pytest.mark.parametrize("text, why", [("{", "not JSON"), ("[]", "not an object"), ('{"stages": {}}', "no as_of"),
                                      ('{"as_of": "2026-13-01"}', "no as_of")])
def test_a_manifest_that_cannot_be_read_is_refused(tmp_path, text, why):
    store.write_tables(tmp_path, _rows())
    (tmp_path / manifest.MANIFEST_NAME).write_text(text)
    with pytest.raises(SnapshotError, match=why):
        RunSnapshot.read(tmp_path).as_of


# -- the older-schema rule ----------------------------------------------------------------------------------------
def test_a_later_table_the_run_did_not_write_is_none(tmp_path):
    _write_run(tmp_path, {k: v for k, v in _rows().items() if k in FIRST_TABLES}, readings={})
    snap = RunSnapshot.read(tmp_path)
    for name in set(store.TABLES) - FIRST_TABLES:
        assert snap.table(name) is None and not snap.has(name)
    with pytest.raises(SnapshotError, match="contract/security_history.csv: missing"):
        snap.require("security_history")
    assert snap.continuations == {}


def test_a_missing_first_table_is_refused(tmp_path):
    _write_run(tmp_path)
    store.table_path(tmp_path, "review").unlink()
    snap = RunSnapshot.read(tmp_path)
    assert not snap.has("review") and snap.securities
    with pytest.raises(SnapshotError, match=r"review\.csv: missing"):
        snap.review


def test_a_contract_before_schema_2_has_no_payout_rule(tmp_path):
    _write_run(tmp_path)
    path = store.table_path(tmp_path, "contract_delistings")
    path.write_text(",".join(CONTRACT_SCHEMA_1) + "\n" + ",".join(["A"] + [""] * (len(CONTRACT_SCHEMA_1) - 1)) + "\n")
    snap = RunSnapshot.read(tmp_path)
    assert snap.contract_delistings is None and not snap.has("contract_delistings")
    with pytest.raises(SnapshotError, match="before schema 2"):
        snap.require("contract_delistings")


@pytest.mark.parametrize("header, why", [
    ("sec_id,ticker,start_date,end_date", "missing column.s. issuer_id, security_name, share_class"),
    (",".join(store.SECURITY_HISTORY_COLUMNS) + ",note", "unknown column.s. note"),
    (",".join(reversed(store.SECURITY_HISTORY_COLUMNS)), "columns out of order"),
])
def test_any_other_layout_is_refused_naming_the_file_and_the_columns(tmp_path, header, why):
    _write_run(tmp_path)
    store.table_path(tmp_path, "security_history").write_text(header + "\n")
    with pytest.raises(SnapshotError, match=f"contract/security_history.csv: {why}"):
        RunSnapshot.read(tmp_path).security_history


# -- the commit adapter -------------------------------------------------------------------------------------------
def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def _repo(tmp_path, tables=None):
    repo = tmp_path / "repo"
    out = repo / "output"
    out.mkdir(parents=True)
    _git(repo, "init", "-q")
    _write_run(out, tables)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, out


def test_the_commit_reads_the_folder_as_the_commit_holds_it(tmp_path):
    repo, out = _repo(tmp_path)
    _write_run(out, {**_rows(), "contract_delistings": [contract_row("A", exit_kind="exchange")]}, readings={},
               as_of=date(2026, 10, 7))
    base, now = RunSnapshot.at(repo, "HEAD", out), RunSnapshot.read(out)
    assert base.contract_delistings[0]["exit_kind"] == "merger" and now.contract_delistings[0]["exit_kind"] == "exchange"
    assert (base.as_of, base.continuations) == (date(2026, 9, 25), READINGS)
    assert (now.as_of, now.continuations) == (date(2026, 10, 7), {})
    for name in WRITTEN:
        assert base.table(name) == store.formatted(name, _rows()[name])
    assert base.ticker_history == [_range("A", "AAA", "2010-01-04", "2016-05-18")]


def test_a_commit_without_a_table_follows_the_older_schema_rule(tmp_path):
    repo, out = _repo(tmp_path, {"contract_delistings": [contract_row("A")]})
    base = RunSnapshot.at(repo, "HEAD", out)
    assert base.payout_legs is None and base.contract_delistings == [store.formatted("contract_delistings",
                                                                                      [contract_row("A")])[0]]
    with pytest.raises(SnapshotError, match="HEAD:output/contract/security_history.csv: missing"):
        base.require("security_history")
    with pytest.raises(SnapshotError, match="HEAD:output/securities.csv: missing"):
        base.securities


def test_a_commit_layout_is_checked_like_a_folders(tmp_path):
    repo, out = _repo(tmp_path)
    store.table_path(out, "security_history").write_text("sec_id,ticker,start_date,end_date\n")
    _git(repo, "commit", "-q", "-am", "old history")
    with pytest.raises(SnapshotError, match="HEAD:output/contract/security_history.csv: missing column.s. issuer_id"):
        RunSnapshot.at(repo, "HEAD", out).security_history


def test_the_commit_adapter_refuses_a_folder_outside_the_repo_and_a_revision_that_is_no_commit(tmp_path):
    repo, _ = _repo(tmp_path)
    with pytest.raises(SnapshotError, match="not inside"):
        RunSnapshot.at(repo, "HEAD", tmp_path / "elsewhere")
    with pytest.raises(SnapshotError, match="nosuchrev: not a commit"):
        RunSnapshot.at(repo, "nosuchrev", repo / "output")


def test_a_commit_that_still_holds_ticker_history_csv_is_read_from_its_contract(tmp_path):
    repo, out = _repo(tmp_path)
    (out / "ticker_history.csv").write_text("sec_id,ticker,exchange,valid_from,valid_to,source\n"
                                            "A,OLD,NYSE,2001-01-01,2002-02-02,ftd\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "an older run's file")
    assert RunSnapshot.at(repo, "HEAD", out).ticker_history == [_range("A", "AAA", "2010-01-04", "2016-05-18")]


def test_a_folder_without_the_contract_cannot_give_ticker_history(tmp_path):
    store.write_tables(tmp_path, {k: v for k, v in _rows().items() if k in FIRST_TABLES})
    with pytest.raises(SnapshotError, match="contract/security_history.csv.*missing"):
        RunSnapshot.read(tmp_path).ticker_history


def test_ticker_ranges_put_issuer_splits_back_together_and_keep_separate_ranges_apart():
    rows = [hist("A", "100", "2010-01-04", "2012-03-31"), hist("A", "200", "2012-04-01", "2014-06-30"),
            hist("A", "100", "2014-07-01", ""),
            hist("A", "100", "2001-01-01", "2002-01-31", ticker="OLD"),
            hist("A", "100", "2002-02-01", "2003-01-01", ticker="OLD"),        # same issuer: two ranges, no split
            hist("B", "300", "2011-01-03", "2011-12-30")]
    got = ticker_ranges(store.formatted("security_history", rows))
    assert [(r["sec_id"], r["ticker"], r["valid_from"], r["valid_to"]) for r in got] == [
        ("A", "OLD", "2001-01-01", "2002-01-31"), ("A", "OLD", "2002-02-01", "2003-01-01"), ("A", "AAA", "2010-01-04", ""),
        ("B", "AAA", "2011-01-03", "2011-12-30")]


# -- the in-memory adapter ----------------------------------------------------------------------------------------
def test_the_rows_about_to_be_written_read_as_the_written_folder(tmp_path):
    _write_run(tmp_path)
    written, held = RunSnapshot.read(tmp_path), RunSnapshot.of(_rows(), as_of=date(2026, 9, 25),
                                                                   continuations=READINGS)
    for name in WRITTEN:
        assert held.table(name) == written.table(name)
    assert held.ticker_history == store.formatted("ticker_history", _rows()["ticker_history"])   # the run's own
    assert [(r["sec_id"], r["ticker"], r["valid_from"], r["valid_to"]) for r in held.ticker_history] == \
        [(r["sec_id"], r["ticker"], r["valid_from"], r["valid_to"]) for r in written.ticker_history]
    assert (held.as_of, held.continuations) == (written.as_of, written.continuations)


def test_the_in_memory_adapter_refuses_an_unknown_table_and_lacks_what_it_was_not_given():
    with pytest.raises(SnapshotError, match="no such table"):
        RunSnapshot.of({"prices": []})
    snap = RunSnapshot.of({"securities": []})
    assert snap.uncertain is None and snap.continuations == {}
    with pytest.raises(SnapshotError, match="the run's delistings.csv: missing"):
        snap.delistings


# -- stage 9g's entries -------------------------------------------------------------------------------------------
def test_continuation_entries_keep_a_confirmations_shape_and_carry_a_doubt():
    entries = continuation_entries({**READINGS, ("C", "2020-01-02"): ContinuationReading()})
    assert entries == [{"sec_id": "A", "delist_date": "2016-05-18", "filing": "", "doubt": "ratio:0.9042"},
                       {"sec_id": "B", "delist_date": "2021-03-14", "filing": "8-K 0001193125-21-063792"}]
    assert continuation_readings(entries) == READINGS
    assert continuation_readings(json.loads(json.dumps(entries))) == READINGS


@pytest.mark.parametrize("entries", [{"sec_id": "A"}, [{"sec_id": "A"}], ["x"]])
def test_an_entry_that_names_no_delisting_is_refused(entries):
    with pytest.raises(SnapshotError):
        continuation_readings(entries)

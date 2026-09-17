"""classify_universe.py replaces each output only when it is written in full:
an abort leaves the files of the last complete run in place."""
import importlib.util
import sys
from pathlib import Path

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarBlocked

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("classify_universe_under_test",
                                               ROOT / "scripts" / "classify_universe.py")
cu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cu)

OLD = "old,complete,run\n"


class _Av:
    def __init__(self, *a, **kw):
        pass

    def name(self, *a, **kw):
        return None

    asset_type = name

    def exchange(self, *a, **kw):
        return "NYSE"


class _Resolver:
    def __init__(self, *a, **kw):
        pass


def _classifier(block_on):
    class _Classifier:
        def __init__(self, *a, **kw):
            pass

        def classify_ticker(self, ticker, observed):
            if ticker == block_on:
                raise EdgarBlocked("SEC returned 403")
            return DelistRecord(ticker, 1, observed, None, CrspBucket.UNKNOWN, "low", "no evidence", {})
    return _Classifier


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(cu, "EdgarClient", lambda *a, **kw: object())
    monkeypatch.setattr(cu, "AvListingLoader", _Av)
    monkeypatch.setattr(cu, "TickerResolver", _Resolver)
    inp = tmp_path / "delisted.tsv"
    inp.write_text("AAA\t2000-01-01\t2020-01-02\nBBB\t2000-01-01\t2020-01-03\n")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    paths = {n: out_dir / f"{n}.csv" for n in ("delist_classifications", "dlret", "payouts", "review")}
    for p in paths.values():
        p.write_text(OLD)
    monkeypatch.setattr(sys, "argv", [
        "classify_universe.py", "--input", str(inp), "--quiet",
        "--output", str(paths["delist_classifications"]),
        "--dlret-output", str(paths["dlret"]), "--payouts-output", str(paths["payouts"])])
    return paths


def _names(paths):
    return sorted(p.name for p in paths["dlret"].parent.iterdir())


def test_an_abort_in_the_loop_leaves_every_old_output(outputs, monkeypatch):
    monkeypatch.setattr(cu, "DelistClassifier", _classifier(block_on="BBB"))   # AAA is written first
    with pytest.raises(EdgarBlocked):
        cu.main()
    assert {n: p.read_text() for n, p in outputs.items()} == dict.fromkeys(outputs, OLD)
    assert _names(outputs) == sorted(p.name for p in outputs.values())         # no temp file left


def test_a_failed_dlret_write_leaves_the_old_dlret(outputs, monkeypatch):
    monkeypatch.setattr(cu, "DelistClassifier", _classifier(block_on=None))

    def half_written(table, path):
        Path(path).write_text("ticker,partial\n")
        raise OSError("disk full")
    monkeypatch.setattr(cu, "write_dlret_csv", half_written)
    with pytest.raises(OSError):
        cu.main()
    assert outputs["dlret"].read_text() == OLD
    assert outputs["review"].read_text() == OLD
    assert "AAA" in outputs["delist_classifications"].read_text()               # finished before the failure
    assert outputs["payouts"].read_text().startswith("ticker,observed_delist_date")
    assert _names(outputs) == sorted(p.name for p in outputs.values())


def test_a_complete_run_replaces_every_output(outputs, monkeypatch):
    monkeypatch.setattr(cu, "DelistClassifier", _classifier(block_on=None))
    assert cu.main() == 0
    for p in outputs.values():
        assert p.read_text() != OLD
    assert "BBB" in outputs["delist_classifications"].read_text()
    assert "BBB" in outputs["dlret"].read_text()
    assert _names(outputs) == sorted(p.name for p in outputs.values())

"""The measurement modules and the contract read the run's tables without loading a network client, and the
classification modules read the row vocabulary without loading measurement (architecture step 8a). Each module is
imported in a fresh interpreter and the package modules it loaded are listed.

The package root (`delist_detection/__init__.py`) imports the EDGAR client, the ticker resolver and the classifier
eagerly, so any import through it loads them: that is step 16's move (a lazy package root). Until then the closures
are measured with the root's own imports left out, and `test_the_package_root_loads_no_client` is a strict xfail that
step 16 turns into a pass."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import delist_detection

SRC = str(Path(delist_detection.__file__).resolve().parent.parent)
NETWORK_CLIENTS = frozenset({"sources.edgar", "sources.sec_http", "sources.openfigi", "sources.ftd", "sources.midas",
                             "sources.nasdaq_halts", "sources.llm_client", "sources.cik_lookup"})
# run_snapshot: every reader's one input; truth_set: the diagnosis truth files' one reader and writer; loop_round:
# one round of the diagnosis loop and its tokens
MEASUREMENT = ("outputs.run_snapshot", "measurement.lifecycle", "outputs.verdict", "measurement.scorecard",
               "measurement.truth", "measurement.diagnosis_truth", "measurement.truth_set", "measurement.regression",
               "measurement.loop_round", "measurement.truth_update", "measurement.audit", "measurement.truth_build")
CONTRACT = ("outputs.contract", "outputs.payout_rule", "outputs.dlret")  # the contract's rows and an ending's value
VOCABULARY = ("vocabulary.exit_kind",)           # the row vocabulary: imports nothing of the package
# The leaves: the row vocabulary, and the spellings of a security's identifiers with the readers of its share class
# (architecture step 13)
LEAVES = ("vocabulary.exit_kind", "vocabulary.identifiers")
# The data clients read the ticker spelling only, never the observations (step 13)
DATA_CLIENTS = ("sources.ftd", "sources.midas", "sources.nasdaq_halts")
CLASSIFICATION = ("endings.end_of_era", "endings.handoffs", "endings.delistings", "endings.continuation_evidence",
                  "endings.classifier", "endings.rewrites", "endings.last_trade", "terms.payout_gate",
                  "outputs.review_triage", "identity.history", "endings.trading_record")
# A module that cannot get there yet, with the step whose move it waits on. None today: the package root is the one
# exception, and every closure below leaves it out (module docstring).
KNOWN_EXCEPTIONS: dict[str, str] = {}

_CLOSURE = """
import importlib, importlib.util, json, sys, types
if sys.argv[2] == "bare":       # the package root's eager imports left out (step 16 makes the root lazy)
    root = types.ModuleType("delist_detection")
    root.__path__ = list(importlib.util.find_spec("delist_detection").submodule_search_locations)
    sys.modules["delist_detection"] = root
importlib.import_module("delist_detection." + sys.argv[1])
print(json.dumps(sorted(m.split(".", 1)[1] for m, v in sys.modules.items()
                        if m.startswith("delist_detection.") and not hasattr(v, "__path__"))))
"""


def _closure(module: str, root: str = "bare") -> set[str]:
    out = subprocess.run([sys.executable, "-c", _CLOSURE, module, root], capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONPATH": SRC})
    return set(json.loads(out.stdout))


@pytest.mark.parametrize("module", [m for m in (*MEASUREMENT, *CONTRACT, *VOCABULARY) if m not in KNOWN_EXCEPTIONS])
def test_a_reader_of_the_tables_loads_no_network_client(module):
    assert not _closure(module) & NETWORK_CLIENTS


@pytest.mark.parametrize("module", LEAVES)
def test_a_leaf_imports_nothing_of_the_package(module):
    assert _closure(module) == {module}


def test_an_endings_value_loads_only_the_row_vocabulary_and_the_leaf_enums():
    """dlret (architecture step 10) is read by the table, the contract and the firm month alike: it loads the row
    vocabulary, the bucket and exchange enums and the ticker spelling, nothing that classifies."""
    assert _closure("outputs.dlret") == {"outputs.dlret", "vocabulary.exit_kind", "vocabulary.crsp_codes",
                                         "vocabulary.exchanges", "vocabulary.identifiers"}


@pytest.mark.parametrize("module", DATA_CLIENTS)
def test_a_data_client_reads_the_ticker_spelling_not_the_observations(module):
    closure = _closure(module)
    assert "vocabulary.identifiers" in closure and not closure & {"identity.observations", "identity.figi_resolution"}


def test_the_observations_and_the_figi_rules_import_neither_of_each_other():
    """Their one cycle (`observations._class_letter` imported figi_resolution inside the function) is gone: both read
    the class and the ticker spelling from the leaf."""
    assert ("identity.figi_resolution" not in _closure("identity.observations")
            and "identity.observations" not in _closure("identity.figi_resolution"))


@pytest.mark.parametrize("module", CLASSIFICATION)
def test_a_classification_module_loads_no_measurement_module(module):
    assert not _closure(module) & set(MEASUREMENT)


@pytest.mark.xfail(strict=True, reason="step 16: the package root imports the EDGAR client, the ticker resolver and "
                                       "the classifier eagerly")
def test_the_package_root_loads_no_client():
    assert not _closure("outputs.verdict", root="package") & NETWORK_CLIENTS

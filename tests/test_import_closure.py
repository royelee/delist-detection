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
NETWORK_CLIENTS = frozenset({"edgar", "sec_http", "openfigi", "ftd", "midas", "nasdaq_halts", "llm_client",
                             "cik_lookup"})
MEASUREMENT = ("lifecycle", "verdict", "scorecard", "truth", "diagnosis_truth", "regression", "diagnosis_loop",
               "truth_update", "audit", "truth_build")
CONTRACT = ("contract", "payout_rule")           # the contract's rows, pure over the tables and stage 8's inputs
VOCABULARY = ("exit_kind",)                      # the row vocabulary: imports nothing of the package
CLASSIFICATION = ("end_of_era", "handoffs", "delistings", "continuation_evidence", "classifier", "rewrites",
                  "last_trade", "payout_gate", "review_triage", "history")
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
print(json.dumps(sorted(m.split(".", 1)[1] for m in sys.modules if m.startswith("delist_detection."))))
"""


def _closure(module: str, root: str = "bare") -> set[str]:
    out = subprocess.run([sys.executable, "-c", _CLOSURE, module, root], capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONPATH": SRC})
    return set(json.loads(out.stdout))


@pytest.mark.parametrize("module", [m for m in (*MEASUREMENT, *CONTRACT, *VOCABULARY) if m not in KNOWN_EXCEPTIONS])
def test_a_reader_of_the_tables_loads_no_network_client(module):
    assert not _closure(module) & NETWORK_CLIENTS


def test_the_row_vocabulary_imports_nothing_of_the_package():
    assert _closure("exit_kind") == {"exit_kind"}


@pytest.mark.parametrize("module", CLASSIFICATION)
def test_a_classification_module_loads_no_measurement_module(module):
    assert not _closure(module) & set(MEASUREMENT)


@pytest.mark.xfail(strict=True, reason="step 16: the package root imports the EDGAR client, the ticker resolver and "
                                       "the classifier eagerly")
def test_the_package_root_loads_no_client():
    assert not _closure("verdict", root="package") & NETWORK_CLIENTS

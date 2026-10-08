"""Imports run one way between the package's subpackages, and the readers of the tables load no network client
(architecture steps 8a and 16).

The direction is read from the real import graph: every import of a package module in the source, at the top of a
module, inside a function or under `TYPE_CHECKING` (`_edges`). A subpackage imports only the subpackages its concept
rests on (`DIRECTION`); the pure subpackages read only the sources' plumbing (`PLUMBING`); an import that breaks the
direction is a named exception with its reason (`EXCEPTIONS`), and stays type only.

The closures are measured at run time: each module is imported in a fresh interpreter, through the package root,
which loads none of the package's modules (step 16), and the package modules it loaded are listed."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import NamedTuple

import pytest

import delist_detection

PKG = Path(delist_detection.__file__).resolve().parent
SRC = str(PKG.parent)

# Each subpackage: the subpackages it may import, the ones its concept rests on (CLAUDE.md, "Architecture").
DIRECTION: dict[str, set[str]] = {
    "vocabulary": set(),                         # the leaves: identifier spelling, names, the calendar, codes, rows
    "sources": {"vocabulary"},                   # the clients and their plumbing
    "filings": {"sources", "vocabulary"},        # what SEC filings say, read by several stages
    "outputs": {"sources", "vocabulary"},        # what a run publishes, as rows: every stage writes into it
    "identity": {"outputs", "filings", "sources", "vocabulary"},
    "endings": {"identity", "outputs", "filings", "sources", "vocabulary"},
    "terms": {"endings", "identity", "outputs", "filings", "sources", "vocabulary"},
    "measurement": {"outputs", "sources", "vocabulary"},
    "handling": {"outputs", "vocabulary"},
}
# The pure subpackages read no client: of the sources, only the plumbing that loads none
PURE = ("outputs", "measurement", "handling")
PLUMBING = frozenset({"sources.atomic_io", "sources.sec_stats"})
# An import that breaks the direction: (importer, imported) and why. Each is type only, so it loads nothing.
EXCEPTIONS: dict[tuple[str, str], str] = {
    ("outputs.dlret", "terms.llm_merger_extractor"):
        "a MergerInputs carries the LLM's answer (MergerTerms), whose published legs the value rule reads; the type "
        "is the extractor's, which builds it",
    ("outputs.degraded", "endings.delistings"):
        "the resolution_degraded flag goes on a Delisting's own row; the type is the finder's, which builds it",
}

NETWORK_CLIENTS = frozenset({"sources.edgar", "sources.sec_http", "sources.openfigi", "sources.ftd", "sources.midas",
                             "sources.nasdaq_halts", "sources.llm_client", "sources.cik_lookup"})
# run_snapshot: every reader's one input; truth_set: the diagnosis truth files' one reader and writer; loop_round:
# one round of the diagnosis loop and its tokens
MEASUREMENT = ("outputs.run_snapshot", "measurement.lifecycle", "outputs.verdict", "measurement.scorecard",
               "measurement.truth", "measurement.diagnosis_truth", "measurement.truth_set", "measurement.regression",
               "measurement.loop_round", "measurement.truth_update", "measurement.audit", "measurement.truth_build")
CONTRACT = ("outputs.contract", "outputs.payout_rule", "outputs.dlret")  # the contract's rows and an ending's value
# The data clients read the ticker spelling only, never the observations (step 13)
DATA_CLIENTS = ("sources.ftd", "sources.midas", "sources.nasdaq_halts")
CLASSIFICATION = ("endings.end_of_era", "endings.handoffs", "endings.delistings", "endings.continuation_evidence",
                  "endings.classifier", "endings.rewrites", "endings.last_trade", "terms.payout_gate",
                  "outputs.review_triage", "identity.history", "endings.trading_record")
# The names the README and the scripts import from the package root, each loaded on first use
ROOT_NAMES = {"EdgarClient": "sources.edgar", "TickerResolver": "identity.ticker_resolver",
              "DelistClassifier": "endings.classifier", "PayoutExtractor": "terms.payout_extractor",
              "Exchange": "vocabulary.exchanges", "build_train_label_adjustment": "handling.handling",
              "build_backtest_exit": "handling.handling", "build_firm_month_correction": "handling.handling"}


class Edge(NamedTuple):
    importer: str
    imported: str
    kind: str          # "top", "local" (inside a function) or "type" (under TYPE_CHECKING)


def _modules() -> dict[str, Path]:
    """Every module of the package by its dotted name under the package ('' is the root, a subpackage its name)."""
    out = {}
    for p in sorted(PKG.rglob("*.py")):
        parts = list(p.relative_to(PKG).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        out[".".join(parts)] = p
    return out


def _targets(mods: dict[str, Path], name: str, node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.name.split(".", 1)[1] for a in node.names
                if a.name.startswith("delist_detection.") and a.name.split(".", 1)[1] in mods]
    if not isinstance(node, ast.ImportFrom):
        return []
    if node.level:
        base = name.split(".") if mods[name].name == "__init__.py" else name.split(".")[:-1]
        base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
        module = ".".join([*([b for b in base if b]), *([node.module] if node.module else [])])
    elif node.module == "delist_detection" or (node.module or "").startswith("delist_detection."):
        module = node.module[len("delist_detection"):].lstrip(".")
    else:
        return []
    out = []
    for a in node.names:
        sub = f"{module}.{a.name}" if module else a.name
        out.append(sub if sub in mods else module)
    return [t for t in out if t in mods and t != name]


def _edges() -> list[Edge]:
    """Every import of a package module by a package module, with where it sits."""
    mods = _modules()
    edges = set()
    for name, path in mods.items():
        tree = ast.parse(path.read_text())
        typed, local = set(), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.If) and "TYPE_CHECKING" in ast.unparse(n.test):
                typed.update(id(m) for m in ast.walk(n))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local.update(id(m) for m in ast.walk(n) if m is not n)
        for n in ast.walk(tree):
            kind = "type" if id(n) in typed else "local" if id(n) in local else "top"
            edges.update(Edge(name, t, kind) for t in _targets(mods, name, n))
    return sorted(edges)


def _subpackage(module: str) -> str:
    return module.split(".")[0] if "." in module else ""


EDGES = _edges()


def test_the_root_holds_only_the_run_and_every_subpackage_has_a_direction():
    mods = _modules()
    assert sorted(m for m in mods if "." not in m and m not in DIRECTION) == ["", "pipeline"]
    assert {_subpackage(m) for m in mods if "." in m} == set(DIRECTION)


def test_the_directions_have_no_cycle():
    try:
        order = list(TopologicalSorter(DIRECTION).static_order())
    except CycleError as e:               # pragma: no cover - the failure message
        pytest.fail(f"the directions loop: {e.args[1]}")
    assert order[0] == "vocabulary"


@pytest.mark.parametrize("subpackage", DIRECTION)
def test_a_subpackage_imports_only_those_its_concept_rests_on(subpackage):
    wrong = [e for e in EDGES if _subpackage(e.importer) == subpackage
             and _subpackage(e.imported) not in DIRECTION[subpackage] | {subpackage}
             and (e.importer, e.imported) not in EXCEPTIONS]
    assert not wrong


def test_nothing_imports_the_run():
    assert not [e for e in EDGES if e.imported in ("", "pipeline")]


@pytest.mark.parametrize("pair", EXCEPTIONS)
def test_an_exception_is_real_and_type_only(pair):
    """Each named exception is an import the graph has, and loads nothing: once it goes, or becomes a runtime import,
    the list is wrong."""
    kinds = {e.kind for e in EDGES if (e.importer, e.imported) == pair}
    assert kinds == {"type"}


@pytest.mark.parametrize("subpackage", PURE)
def test_a_pure_subpackage_reads_only_the_plumbing_of_the_sources(subpackage):
    read = {e.imported for e in EDGES if _subpackage(e.importer) == subpackage and _subpackage(e.imported) == "sources"}
    assert read <= PLUMBING


_CLOSURE = """
import importlib, json, sys
if sys.argv[1]:
    importlib.import_module("delist_detection." + sys.argv[1])
else:
    import delist_detection
print(json.dumps(sorted(m.split(".", 1)[1] for m, v in sys.modules.items()
                        if m.startswith("delist_detection.") and not hasattr(v, "__path__"))))
"""


def _closure(module: str) -> set[str]:
    """The package modules (subpackages left out) one import of `module` loads, through the package root."""
    out = subprocess.run([sys.executable, "-c", _CLOSURE, module], capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONPATH": SRC})
    return set(json.loads(out.stdout))


@pytest.mark.parametrize("module", (*MEASUREMENT, *CONTRACT))
def test_a_reader_of_the_tables_loads_no_network_client(module):
    assert not _closure(module) & NETWORK_CLIENTS


@pytest.mark.parametrize("module", sorted(m for m in _modules() if _subpackage(m) == "vocabulary"))
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


@pytest.mark.parametrize("module", ("handling.handling", "handling.qlib_adapter"))
def test_the_handling_loads_no_network_client(module):
    """The handling reads a delistings.csv row and the record the classifier hands over (`DelistRecord`, defined
    with the table), never the classifier."""
    assert not _closure(module) & NETWORK_CLIENTS


def test_the_package_root_loads_no_client():
    assert not _closure("outputs.verdict") & NETWORK_CLIENTS


def test_importing_the_package_loads_none_of_its_modules():
    assert _closure("") == set()


@pytest.mark.parametrize("name", ROOT_NAMES)
def test_a_root_name_loads_its_module_on_first_use(name):
    """The root's names are the defining modules' own objects, loaded when first asked for."""
    from importlib import import_module
    assert getattr(delist_detection, name) is getattr(import_module(f"delist_detection.{ROOT_NAMES[name]}"), name)
    assert name in delist_detection.__all__ and name in dir(delist_detection)


def test_the_root_has_no_other_name():
    assert sorted(delist_detection.__all__) == sorted(ROOT_NAMES)
    with pytest.raises(AttributeError):
        delist_detection.DelistRecord          # noqa: B018 - a name the root no longer gives

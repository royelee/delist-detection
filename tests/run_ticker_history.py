"""ticker_history is no longer written (store.TABLES: `written=False`); a pipeline test that asserts on a run's ranges
(their exchange, source, a merger acquirer's) reads the run's own, which conftest's autouse fixture takes off
`pipeline.write_tables` as the run hands its tables to be written."""
from __future__ import annotations

from pathlib import Path

from delist_detection.outputs import store

_BY_FOLDER: dict[Path, list[dict[str, str]]] = {}


def capturing(real):
    """`pipeline.write_tables` wrapped to keep the run's ticker_history rows by output folder."""
    def write_tables(out_dir, tables):
        if "ticker_history" in tables:
            _BY_FOLDER[Path(out_dir).resolve()] = store.formatted("ticker_history", tables["ticker_history"])
        return real(out_dir, tables)
    return write_tables


def ticker_history(out_dir) -> list[dict[str, str]]:
    """The ticker_history rows of the run that wrote `out_dir` (as `store.read_table` read them back when the file
    was written)."""
    return list(_BY_FOLDER[Path(out_dir).resolve()])

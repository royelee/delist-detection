"""Rows of the diagnosis truth files for tests: every column present, every scored field `*` (not scored) unless
a test sets it, status pass and shape ending by default; `write_truth` writes a truth file (and its legs) as a new
truth set."""
from __future__ import annotations

from delist_detection.diagnosis_loop import LEDGER_COLUMNS
from delist_detection.diagnosis_truth import COLUMNS, LEG_COLUMNS, SCORED
from delist_detection.truth_set import TruthSet


def truth_row(case_id: str, sec_id: str, **cells) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    row.update({f: "*" for f in SCORED})
    row.update(case_id=case_id, sec_id=sec_id, ticker=sec_id, status="pass", shape="ending")
    unknown = set(cells) - set(row)
    assert not unknown, f"no column(s) {sorted(unknown)}"
    row.update({k: str(v) for k, v in cells.items()})
    return row


def leg_row(case_id: str, leg: int, **cells) -> dict[str, str]:
    row = dict.fromkeys(LEG_COLUMNS, "")
    row.update(case_id=case_id, leg=str(leg), ratio="1")
    row.update({k: str(v) for k, v in cells.items()})
    return row


def ledger_row(key: str, **cells) -> dict[str, str]:
    row = dict.fromkeys(LEDGER_COLUMNS, "")
    row.update(key=key, kind="mismatch", outcome="known")
    row.update({k: str(v) for k, v in cells.items()})
    return row


def write_truth(path, rows, legs=()) -> None:
    """The truth file at `path` and its legs file, written as a new truth set."""
    TruthSet.new(path, rows, legs).commit()

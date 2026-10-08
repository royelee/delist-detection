"""Apply one loop round's diagnoses to the diagnosis truth file (spec 2026-10-03-diagnosis-truth-fixes, section
1.6), so the truth never drifts toward whatever the library now outputs.

- A regressed row outside the truth set enters the truth file when its diagnosis is verified and the skeptic
  upheld it. It takes the side the diagnosis found right, field by field. All new values give `pass`. Any old value
  gives `known_wrong`, with `fixed_by` the round's sub-plan, because the rule must be narrowed. Whether the row is
  added, and its status, follow the truth-touching fields only (a scored field or a whole row); each key's ledger
  outcome follows its own field's verdict. A change that touches no scored field (a ticker range, a placeholder
  rename) enters only the ledger. A whole-row regression (an added or removed row) gives a truth row that scores
  only the fields the diagnosing agent saw (`regression.BRIEF_COLUMNS`) and `*` elsewhere; a changed field keeps
  the base run's values for the scored fields it did not change (the regression guard presumes them right). The
  mismatches an `old` verdict makes for the new row get `truth_right` ledger rows, so the next round does not
  diagnose them again. A record that is not verified, or that the skeptic refuted, adds the row as
  `ruling_pending` with `fixed_by` `regression`; it counts as unexplained until the operator settles it.
- A mismatched truth field changes only when the diagnosis is verified and upheld, finds the library's value right,
  and names a filing the earlier report missed or misread (`missed_filing`, an SEC accession number: anything else
  is no citation). A verdict about the shape, the ending or a leg sends the case to `ruling_pending` instead: the
  operator rewrites such rows.
- A regression of a sec_id the run no longer holds, or of a placeholder renamed since the base commit, enters
  only the ledger (sub-plan 5a: a placeholder a line folds into a FIGI is not a truth row of its own).
- A `pending` ledger row is never re-diagnosed automatically: the operator settles it, or deletes the ledger row
  to retry (spec 1.6).
- A case with no usable record (the agent failed: none, not a JSON object, or without `field_verdicts`,
  `confidence` or `verification`) changes nothing and leaves no ledger row, so the next round retries it.
- A known_wrong case that now matches turns `pass` (`TruthSet.flip`, after the round).

The truth set (`truth_set.TruthSet`) holds the truth file, its change log and the ledger, and logs every change these
rules make through its primitives: every truth change is a change-log row, and every settled error a ledger row. Loop
records carry `mode` and `field_verdicts`: [{"field", "right": old | new | truth | library | neither, "value",
"missed_filing"}]."""
from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .diagnosis_loop import LIBRARY_RIGHT, MISMATCH, NEW_RIGHT, OLD_RIGHT, PENDING, REGRESSION, TRUTH_RIGHT
from .diagnosis_truth import (COLUMNS, ENDING, KNOWN_WRONG, NO_ENDING, NOT_SCORED, PASS, REGRESSION_PENDING,
                              RULING_PENDING, SCORED)
from .regression import BRIEF_COLUMNS

if TYPE_CHECKING:                   # the truth set calls these rules (TruthSet.apply_round); no import at run time
    from .truth_set import TruthSet

OLD, NEW, TRUTH, LIBRARY = "old", "new", "truth", "library"
WHOLE_ROW = ("delistings.added", "delistings.removed")
ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
REQUIRED_KEYS = ("field_verdicts", "confidence", "verification")


@dataclass
class RoundResult:
    """What `TruthSet.apply_round` gives back: the truth rows as they now stand, the round's change-log and ledger
    rows, and the cases to retry."""
    truth_rows: list[dict[str, str]]
    changes: list[dict[str, str]]
    ledger_rows: list[dict[str, str]]
    pending: list[str]


def _complete(rec) -> bool:
    """A record both the diagnose and the verify agent finished; anything else is a failed agent, retried."""
    return isinstance(rec, dict) and all(k in rec for k in REQUIRED_KEYS) and isinstance(rec["verification"], dict)


def _cites(verdict: Mapping) -> bool:
    """`missed_filing` names an SEC accession number (0001193125-10-222185); any other text is no citation."""
    return bool(ACCESSION.fullmatch(str(verdict.get("missed_filing") or "").strip()))


def _usable(rec: Mapping) -> bool:
    v = rec.get("verification") or {}
    return rec.get("confidence") == "verified" and bool(v.get("upheld")) and not v.get("fields_refuted")


def _ledger(key: str, kind: str, sec: str, label: str, round_no: int, outcome: str, report: str) -> dict[str, str]:
    return dict(key=key, kind=kind, sec_id=sec, label=label, round=str(round_no), outcome=outcome, report=report)


def _blank(case_id: str, sec: str, ticker: str) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    row.update(case_id=case_id, sec_id=sec, ticker=ticker, shape=ENDING)
    return row


def _regression_row(case: Mapping[str, str], right: Mapping[str, str], fields: Sequence[str], old: Sequence[str],
                    new: Sequence[str], base_row: Mapping[str, str] | None,
                    new_row: Mapping[str, str] | None) -> dict[str, str]:
    row = _blank(case["case_id"], case["sec_id"], case["ticker"])
    whole = next((f for f in fields if f in WHOLE_ROW), None)
    if whole is not None:
        # The agent saw only the brief of the row, so only the brief is scored; the rest is not judged.
        side = new_row if right[whole] == NEW else base_row
        row["shape"] = ENDING if side else NO_ENDING
        row.update({f: NOT_SCORED for f in SCORED})
        if side:
            row.update({f: side.get(f, "") for f in BRIEF_COLUMNS})
        return row
    # A changed-field case: the scored fields it did not change keep the base run's values, which the regression
    # guard presumes right (that run was accepted); each changed field takes the side the diagnosis found right.
    row.update({f: base_row.get(f, "") if base_row else NOT_SCORED for f in SCORED})
    for f, o, n in zip(fields, old, new):
        if f in SCORED:
            row[f] = n if right[f] == NEW else o
    return row


def _truth_right_keys(case_id: str, right: Mapping[str, str], fields: Sequence[str], old: Sequence[str],
                      new: Sequence[str], row: Mapping[str, str]) -> list[str]:
    """The mismatch keys the new truth row has against the run for every field the diagnosis found `old`: the
    keys `diagnosis_loop.mismatch_key` gives what the judge will report, which the ledger settles as the truth
    being right."""
    out = []
    for f, o, n in zip(fields, old, new):
        if right[f] != OLD:
            continue
        if f in SCORED:
            out.append(f"mis|{case_id}|{f}|{o}|{n}")
        elif f == "delistings.added":
            out.append(f"mis|{case_id}|shape|{NO_ENDING}|{ENDING}")
        elif f == "delistings.removed" and row["shape"] == ENDING:
            out.append(f"mis|{case_id}|ending|present|(no contract row)")
    return out


def apply_round(truth: TruthSet, cases: Sequence[Mapping[str, str]], records: Mapping[str, Mapping],
                base_contract: Mapping[str, Mapping[str, str]], new_contract: Mapping[str, Mapping[str, str]], *,
                label: str, round_no: int, report_dir: str, run_sec_ids: Collection[str] | None = None,
                renamed: Collection[str] = ()) -> list[str]:
    """One round's diagnoses applied to the truth set `truth` and its ledger (the module docstring's rules), through
    the set's primitives (`TruthSet.set_cells`, `move_status`, `add_row`, `settle`), which log each change. Called
    by `TruthSet.apply_round`. A regression of a security the run no longer holds (`run_sec_ids`: the run's
    securities, None for no check) or of a placeholder renamed since the base commit (`renamed`: the old sec_ids)
    settles its ledger keys and adds no truth row: a truth row under an id the run lacks could only ever be judged a
    `sec_id` mismatch. Returns the cases to retry (no usable record)."""
    ledger_keys = truth.ledger_keys             # the keys settled before this round
    in_truth = {r["sec_id"] for r in truth.rows}
    pending: list[str] = []
    for case in cases:
        keys, fields, a, b = (json.loads(case[c]) for c in ("keys", "fields", "side_a", "side_b"))
        if all(k in ledger_keys for k in keys):
            continue
        rec = records.get(case["case_id"])
        if not _complete(rec):
            pending.append(case["case_id"])
            continue
        report = f"{report_dir}/{case['case_id']}.md"
        verdicts = {v["field"]: v for v in rec.get("field_verdicts") or []}
        usable = _usable(rec)
        sec = case["sec_id"]
        if case["mode"] == REGRESSION:
            right = {f: (verdicts.get(f) or {}).get("right", "") for f in fields}
            for f, k in zip(fields, keys):
                outcome = (NEW_RIGHT if right[f] == NEW else OLD_RIGHT if right[f] == OLD else PENDING) \
                    if usable else PENDING
                truth.settle([_ledger(k, REGRESSION, sec, label, round_no, outcome, report)])
            touching = [f for f in fields if f in SCORED or f in WHOLE_ROW]
            gone = (run_sec_ids is not None and sec not in run_sec_ids) or sec in renamed
            if sec in in_truth or not touching or gone:
                continue
            if usable and all(right[f] in (OLD, NEW) for f in touching):
                row = _regression_row(case, right, fields, a, b, base_contract.get(sec), new_contract.get(sec))
                all_new = all(right[f] == NEW for f in touching)
                row.update(status=PASS if all_new else KNOWN_WRONG, fixed_by="" if all_new else label,
                           confidence=rec.get("confidence", ""), skeptic="upheld",
                           note=f"added by the {label} loop: regression of {', '.join(fields)}")
                settled = truth.ledger_keys
                for k in _truth_right_keys(row["case_id"], right, fields, a, b, row):
                    if k not in settled:
                        truth.settle([_ledger(k, MISMATCH, sec, label, round_no, TRUTH_RIGHT, report)])
                        settled.add(k)
            else:
                row = _blank(case["case_id"], sec, case["ticker"])
                row.update({f: NOT_SCORED for f in SCORED}, status=RULING_PENDING, fixed_by=REGRESSION_PENDING,
                           confidence=rec.get("confidence", ""),
                           skeptic="upheld" if (rec.get("verification") or {}).get("upheld") else "refuted",
                           note=f"regression of {', '.join(fields)} not settled by the {label} loop")
            row["report"] = report
            truth.add_row(row, reason=f"{label} loop round {round_no}: regression", report=report)
            in_truth.add(sec)
        else:
            t = truth.row(case["truth_case_id"])
            if t is None:
                raise ValueError(
                    f"case {case['case_id']}: truth case {case['truth_case_id']!r} is not in the truth rows")
            for f, k, lib in zip(fields, keys, b):
                v = verdicts.get(f) or {}
                if usable and v.get("right") == LIBRARY and _cites(v):
                    outcome = LIBRARY_RIGHT
                    if f in SCORED or f == "internal_last_trade_date":
                        truth.set_cells(t["case_id"], [(f, lib)],
                                        reason=f"diagnosis {case['case_id']} cites {v['missed_filing']}", report=report)
                    else:
                        truth.move_status(t["case_id"], RULING_PENDING,
                                          reason=f"diagnosis {case['case_id']} found the library's {f} right",
                                          report=report, note=f"{f}: the library is right per {case['case_id']}")
                elif usable and v.get("right") == TRUTH:
                    outcome = TRUTH_RIGHT
                else:
                    outcome = PENDING
                truth.settle([_ledger(k, MISMATCH, sec, label, round_no, outcome, report)])
    return pending

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
  mismatches the new row has against the run get `truth_right` ledger rows, so the next round does not diagnose
  them again: they are the fields the diagnosis found `old`, since every other scored cell is the run's own value.
  The judge gives their keys (`loop_round.new_row_keys`). The row keeps the delist_date of the ending the case
  examined (`examined_delist_date`). A record that is not verified, or that the skeptic refuted, adds the row as
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
rules make through its primitives: every truth change is a change-log row, and every settled error a ledger row. The
round's cases (`loop_round.RoundCase`), the record vocabulary (`loop_round.RIGHTS` and the rest), the field names
(`loop_round.parse_field`) and the ledger rows (`loop_round.ledger_row`) are the loop round's; these rules only read
them. A record carries `field_verdicts`: [{"field", "right", "value", "missed_filing"}], `confidence` and the
skeptic's `verification`."""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .diagnosis_truth import (COLUMNS, ENDING, NO_ENDING, NOT_SCORED, REGRESSION_PENDING, RULING_PENDING, SCORED,
                              LibraryRows)
from .loop_round import (LIBRARY, LIBRARY_RIGHT, NEW, NEW_RIGHT, OLD, OLD_RIGHT, PENDING, RECORD_KEYS, REGRESSION,
                         TRUTH, TRUTH_RIGHT, VERIFIED, RoundCase, ledger_row, new_row_keys, parse_field)
from .regression import BRIEF_COLUMNS
from .truth import KNOWN_WRONG, PASS

if TYPE_CHECKING:                   # the truth set calls these rules (TruthSet.apply_round); no import at run time
    from .truth_set import TruthSet

ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")


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
    return isinstance(rec, dict) and all(k in rec for k in RECORD_KEYS) and isinstance(rec["verification"], dict)


def _cites(verdict: Mapping) -> bool:
    """`missed_filing` names an SEC accession number (0001193125-10-222185); any other text is no citation."""
    return bool(ACCESSION.fullmatch(str(verdict.get("missed_filing") or "").strip()))


def _usable(rec: Mapping) -> bool:
    v = rec.get("verification") or {}
    return rec.get("confidence") == VERIFIED and bool(v.get("upheld")) and not v.get("fields_refuted")


def _blank(case: RoundCase) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    row.update(case_id=case.case_id, sec_id=case.sec_id, ticker=case.ticker, shape=ENDING,
               examined_delist_date=case.delist_date)
    return row


def _regression_row(case: RoundCase, right: Mapping[str, str], base_row: Mapping[str, str] | None,
                    new_row: Mapping[str, str] | None) -> dict[str, str]:
    row = _blank(case)
    whole = next((e.field for e in case.errors if parse_field(e.field).whole), None)
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
    for e in case.errors:
        if parse_field(e.field).scored:
            row[e.field] = e.side_b if right[e.field] == NEW else e.side_a
    return row


def apply_round(truth: TruthSet, cases: Sequence[RoundCase], records: Mapping[str, Mapping],
                base_contract: Mapping[str, Mapping[str, str]], run: LibraryRows, *, label: str, round_no: int,
                report_dir: str, renamed: Collection[str] = ()) -> list[str]:
    """One round's diagnoses applied to the truth set `truth` and its ledger (the module docstring's rules), through
    the set's primitives (`TruthSet.set_cells`, `move_status`, `add_row`, `settle`), which log each change. Called
    by `TruthSet.apply_round`. `run` is the run as the judge reads it: its contract rows give a new row's fields, its
    securities say which it still holds, and the judge gives the new row's mismatch keys. A regression of a security
    the run no longer holds or of a placeholder renamed since the base commit (`renamed`: the old sec_ids) settles
    its ledger keys and adds no truth row: a truth row under an id the run lacks could only ever be judged a `sec_id`
    mismatch. Returns the cases to retry (no usable record)."""
    ledger_keys = truth.ledger_keys             # the keys settled before this round
    in_truth = {r["sec_id"] for r in truth.rows}
    pending: list[str] = []
    for case in cases:
        if all(e.key in ledger_keys for e in case.errors):
            continue
        rec = records.get(case.case_id)
        if not _complete(rec):
            pending.append(case.case_id)
            continue
        report = f"{report_dir}/{case.case_id}.md"
        verdicts = {v["field"]: v for v in rec.get("field_verdicts") or []}
        usable = _usable(rec)
        sec = case.sec_id

        def settle(key: str, outcome: str) -> None:
            truth.settle([ledger_row(key, sec_id=sec, label=label, round_no=round_no, outcome=outcome,
                                     report=report)])

        if case.mode == REGRESSION:
            right = {e.field: (verdicts.get(e.field) or {}).get("right", "") for e in case.errors}
            for e in case.errors:
                settle(e.key, (NEW_RIGHT if right[e.field] == NEW else OLD_RIGHT if right[e.field] == OLD
                               else PENDING) if usable else PENDING)
            touching = [e.field for e in case.errors if parse_field(e.field).scored or parse_field(e.field).whole]
            gone = sec not in run.sec_ids or sec in renamed
            if sec in in_truth or not touching or gone:
                continue
            if usable and all(right[f] in (OLD, NEW) for f in touching):
                row = _regression_row(case, right, base_contract.get(sec), run.contract.get(sec))
                all_new = all(right[f] == NEW for f in touching)
                row.update(status=PASS if all_new else KNOWN_WRONG, fixed_by="" if all_new else label,
                           confidence=rec.get("confidence", ""), skeptic="upheld",
                           note=f"added by the {label} loop: regression of {', '.join(case.fields)}")
                settled = truth.ledger_keys
                for k in new_row_keys(case, row, run):
                    if k not in settled:
                        settle(k, TRUTH_RIGHT)
                        settled.add(k)
            else:
                row = _blank(case)
                row.update({f: NOT_SCORED for f in SCORED}, status=RULING_PENDING, fixed_by=REGRESSION_PENDING,
                           confidence=rec.get("confidence", ""),
                           skeptic="upheld" if (rec.get("verification") or {}).get("upheld") else "refuted",
                           note=f"regression of {', '.join(case.fields)} not settled by the {label} loop")
            row["report"] = report
            truth.add_row(row, reason=f"{label} loop round {round_no}: regression", report=report)
            in_truth.add(sec)
        else:
            t = truth.row(case.truth_case_id)
            if t is None:
                raise ValueError(f"case {case.case_id}: truth case {case.truth_case_id!r} is not in the truth rows")
            for e in case.errors:
                f = e.field
                v = verdicts.get(f) or {}
                if usable and v.get("right") == LIBRARY and _cites(v):
                    outcome = LIBRARY_RIGHT
                    if f in SCORED or f == "internal_last_trade_date":
                        truth.set_cells(t["case_id"], [(f, e.side_b)],
                                        reason=f"diagnosis {case.case_id} cites {v['missed_filing']}", report=report)
                    else:
                        truth.move_status(t["case_id"], RULING_PENDING,
                                          reason=f"diagnosis {case.case_id} found the library's {f} right",
                                          report=report, note=f"{f}: the library is right per {case.case_id}")
                elif usable and v.get("right") == TRUTH:
                    outcome = TRUTH_RIGHT
                else:
                    outcome = PENDING
                settle(e.key, outcome)
    return pending

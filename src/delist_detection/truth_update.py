"""Apply one loop round's diagnoses to the diagnosis truth file (spec 2026-10-03-diagnosis-truth-fixes, section
1.6), so the truth never drifts toward whatever the library now outputs.

- A regressed row outside the truth set enters the truth file when its diagnosis is verified and the skeptic
  upheld it. It takes the side the diagnosis found right, field by field. All new values give `pass`. Any old value
  gives `known_wrong`, with `fixed_by` the round's sub-plan, because the rule must be narrowed. A change that
  touches no scored field (a ticker range, a placeholder rename, dlret) enters only the ledger. A record that is
  not verified, or that the skeptic refuted, adds the row as `ruling_pending` with `fixed_by` `regression`; it
  counts as unexplained until the operator settles it.
- A mismatched truth field changes only when the diagnosis is verified and upheld, finds the library's value right,
  and names a filing the earlier report missed or misread (`missed_filing`). A verdict about the shape, the ending
  or a leg sends the case to `ruling_pending` instead: the operator rewrites such rows.
- A `pending` ledger row is never re-diagnosed automatically: the operator settles it, or deletes the ledger row
  to retry (spec 1.6).
- A case with no record (the agent failed) changes nothing and leaves no ledger row, so the next round retries it.
- `flip_statuses` turns a known_wrong case that now matches into `pass`.

Every truth change is a change-log row, and every settled error a ledger row. Loop records carry `mode` and
`field_verdicts`: [{"field", "right": old | new | truth | library | neither, "value", "missed_filing"}]."""
from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from .diagnosis_loop import LIBRARY_RIGHT, MISMATCH, NEW_RIGHT, OLD_RIGHT, PENDING, REGRESSION, TRUTH_RIGHT
from .diagnosis_truth import (COLUMNS, ENDING, KNOWN_WRONG, NO_ENDING, NOT_SCORED, PASS, REGRESSION_PENDING,
                              RULING_PENDING, SCORED)

OLD, NEW, TRUTH, LIBRARY = "old", "new", "truth", "library"
WHOLE_ROW = ("delistings.added", "delistings.removed")


@dataclass
class RoundResult:
    truth_rows: list[dict[str, str]]
    changes: list[dict[str, str]]
    ledger_rows: list[dict[str, str]]
    pending: list[str]


def _usable(rec: Mapping) -> bool:
    v = rec.get("verification") or {}
    return rec.get("confidence") == "verified" and bool(v.get("upheld")) and not v.get("fields_refuted")


def _change(case_id: str, name: str, old: str, new: str, reason: str, report: str) -> dict[str, str]:
    return dict(case_id=case_id, field=name, old=old, new=new, reason=reason, report=report)


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
        side = new_row if right[whole] == NEW else base_row
        row["shape"] = ENDING if side else NO_ENDING
        row.update({f: (side or {}).get(f, "") for f in SCORED})
        return row
    # Seed from the base row, then take the diagnosed side per field: a truth row never takes an undiagnosed value.
    row.update({f: (base_row or new_row or {}).get(f, "") for f in SCORED})
    for f, o, n in zip(fields, old, new):
        if f in SCORED:
            row[f] = n if right[f] == NEW else o
    return row


def apply_round(cases: Sequence[Mapping[str, str]], records: Mapping[str, Mapping],
                truth_rows: Sequence[Mapping[str, str]], base_contract: Mapping[str, Mapping[str, str]],
                new_contract: Mapping[str, Mapping[str, str]], *, label: str, round_no: int, report_dir: str,
                ledger_keys: Collection[str] = frozenset()) -> RoundResult:
    rows = [dict(r) for r in truth_rows]
    by_case = {r["case_id"]: r for r in rows}
    in_truth = {r["sec_id"] for r in rows}
    changes: list[dict[str, str]] = []
    ledger: list[dict[str, str]] = []
    pending: list[str] = []
    for case in cases:
        keys, fields, a, b = (json.loads(case[c]) for c in ("keys", "fields", "side_a", "side_b"))
        if all(k in ledger_keys for k in keys):
            continue
        rec = records.get(case["case_id"])
        if rec is None:
            pending.append(case["case_id"])
            continue
        report = f"{report_dir}/{case['case_id']}.md"
        verdicts = {v["field"]: v for v in rec.get("field_verdicts") or []}
        usable = _usable(rec)
        sec = case["sec_id"]
        if case["mode"] == REGRESSION:
            right = {f: (verdicts.get(f) or {}).get("right", "") for f in fields}
            ok = usable and all(right[f] in (OLD, NEW) for f in fields)
            for f, k in zip(fields, keys):
                outcome = (NEW_RIGHT if right[f] == NEW else OLD_RIGHT) if ok else PENDING
                ledger.append(_ledger(k, REGRESSION, sec, label, round_no, outcome, report))
            if sec in in_truth or not any(f in SCORED or f in WHOLE_ROW for f in fields):
                continue
            if ok:
                row = _regression_row(case, right, fields, a, b, base_contract.get(sec), new_contract.get(sec))
                all_new = all(right[f] == NEW for f in fields if f in SCORED or f in WHOLE_ROW)
                row.update(status=PASS if all_new else KNOWN_WRONG, fixed_by="" if all_new else label,
                           confidence=rec.get("confidence", ""), skeptic="upheld",
                           note=f"added by the {label} loop: regression of {', '.join(fields)}")
            else:
                row = _blank(case["case_id"], sec, case["ticker"])
                row.update({f: NOT_SCORED for f in SCORED}, status=RULING_PENDING, fixed_by=REGRESSION_PENDING,
                           confidence=rec.get("confidence", ""),
                           skeptic="upheld" if (rec.get("verification") or {}).get("upheld") else "refuted",
                           note=f"regression of {', '.join(fields)} not settled by the {label} loop")
            row["report"] = report
            rows.append(row)
            in_truth.add(sec)
            changes.append(_change(row["case_id"], "(row)", "", f"added ({row['status']})",
                                   f"{label} loop round {round_no}: regression", report))
        else:
            truth = by_case.get(case["truth_case_id"])
            if truth is None:
                raise ValueError(
                    f"case {case['case_id']}: truth case {case['truth_case_id']!r} is not in the truth rows")
            for f, k, t, lib in zip(fields, keys, a, b):
                v = verdicts.get(f) or {}
                if usable and v.get("right") == LIBRARY and v.get("missed_filing"):
                    outcome = LIBRARY_RIGHT
                    if f in SCORED or f == "internal_last_trade_date":
                        changes.append(_change(truth["case_id"], f, truth[f], lib,
                                               f"diagnosis {case['case_id']} cites {v['missed_filing']}", report))
                        truth[f] = lib
                    else:
                        changes.append(_change(truth["case_id"], "status", truth["status"], RULING_PENDING,
                                               f"diagnosis {case['case_id']} found the library's {f} right", report))
                        truth.update(status=RULING_PENDING, fixed_by="",
                                     note=f"{truth['note']}; {f}: the library is right per {case['case_id']}")
                elif usable and v.get("right") == TRUTH:
                    outcome = TRUTH_RIGHT
                else:
                    outcome = PENDING
                ledger.append(_ledger(k, MISMATCH, sec, label, round_no, outcome, report))
    return RoundResult(rows, changes, ledger, pending)


def flip_statuses(rows: Sequence[dict[str, str]], matching: Collection[str]) -> list[dict[str, str]]:
    """Every known_wrong row whose case now matches becomes pass (in place); returns the change-log rows."""
    out = []
    for r in rows:
        if r["status"] == KNOWN_WRONG and r["case_id"] in matching:
            out.append(_change(r["case_id"], "status", KNOWN_WRONG, PASS, "the library now matches", ""))
            r["status"], r["fixed_by"] = PASS, ""
    return out

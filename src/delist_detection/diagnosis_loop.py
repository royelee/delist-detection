"""The diagnosis loop's bookkeeping (spec 2026-10-03-diagnosis-truth-fixes, section 1.7). It covers which errors
a round must diagnose, the ledger of errors already diagnosed, the case rows the diagnose workflow reads, and
renaming truth rows whose placeholder now holds a FIGI.

An error is a truth mismatch (a scored field the run gets wrong) or a regression report row (a contract field
that changed outside the truth set). Each has a key. The ledger (`LEDGER`) records the keys already diagnosed and
their outcome, so a round diagnoses only new errors. Sub-plan 5-0 seeds it with every mismatch the reports
themselves describe (outcome `known`)."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from .atomic_io import write_atomic
from .contract import last_endings
from .diagnosis_truth import CaseJudgement, Mismatch
from .lifecycle import Tables
from .regression import regression_key

LOOP_DIR = "output/diagnose_unknown_report/loop"
LEDGER = f"{LOOP_DIR}/diagnosed.csv"
LEDGER_COLUMNS = ("key", "kind", "sec_id", "label", "round", "outcome", "report")
KNOWN, NEW_RIGHT, OLD_RIGHT, TRUTH_RIGHT, LIBRARY_RIGHT, PENDING = (
    "known", "new_right", "old_right", "truth_right", "library_right", "pending")
MISMATCH, REGRESSION = "mismatch", "regression"
CONTEXT_COLUMNS = ("tickers", "security_name", "share_class", "issuer_ids", "first_start", "last_end", "intervals",
                   "delist_date", "library_cik", "bucket", "crsp_code", "reason", "last_trade_date_source",
                   "library_last_trade_close", "dlret_method", "delist_filing_form", "delist_filing_accession",
                   "review_flags", "uncertain_reasons")
CASE_COLUMNS = ("case_id", "mode", "sec_id", "ticker", "truth_case_id", "keys", "fields", "side_a", "side_b",
                *CONTEXT_COLUMNS)
CHANGE_COLUMNS = ("case_id", "field", "old", "new", "reason", "report")


def mismatch_key(m: Mismatch) -> str:
    """The ledger key of one truth mismatch."""
    return "|".join(("mis", m.case_id, m.field, m.truth, m.library))


def _write_csv(path: str | Path, columns: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(Path(path), buf.getvalue())


def read_csv(path: str | Path) -> list[dict[str, str]]:
    """A CSV's rows, or [] when the file does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_ledger(path: str | Path) -> list[dict[str, str]]:
    return read_csv(path)


def write_ledger(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _write_csv(path, LEDGER_COLUMNS, rows)


def write_changes(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    """data/diagnosis_truth_changes.csv, rewritten whole (callers pass every old row first)."""
    _write_csv(path, CHANGE_COLUMNS, rows)


def ledger_keys(rows: Sequence[Mapping[str, str]]) -> set[str]:
    return {r["key"] for r in rows}


def settled_keys(rows: Sequence[Mapping[str, str]]) -> set[str]:
    """The regression keys the loop settled as right (the regression report treats them as explained)."""
    return {r["key"] for r in rows if r["outcome"] == NEW_RIGHT}


def seed_rows(judgements: Sequence[CaseJudgement], keys: Collection[str], label: str) -> list[dict[str, str]]:
    """A `known` ledger row for every current mismatch not in `keys`: the reports already describe them, so no
    round diagnoses them again."""
    out = []
    for j in judgements:
        for m in j.mismatches:
            k = mismatch_key(m)
            if k not in keys:
                out.append(dict(key=k, kind=MISMATCH, sec_id=j.case.sec_id, label=label, round="0", outcome=KNOWN,
                                report=j.case.report))
    return out


def context(tables: Tables, sec_id: str) -> dict[str, str]:
    """What a diagnosing agent reads about a security beside the changed fields: its ticker ranges collapsed, its
    last real ending in delistings.csv, and that ending's uncertain reasons (the columns of source.csv)."""
    hist = sorted((r for r in tables.security_history or () if r["sec_id"] == sec_id), key=lambda r: r["start_date"])
    end = last_endings(tables.delistings).get(sec_id) or {}
    reasons = next((r["reason"] for r in tables.uncertain or () if r["kind"] == "ending" and r["sec_id"] == sec_id
                    and r["date"] == end.get("delist_date")), "")
    return {
        "tickers": ";".join(dict.fromkeys(r["ticker"] for r in hist)),
        "security_name": hist[-1]["security_name"] if hist else "",
        "share_class": hist[-1]["share_class"] if hist else "",
        "issuer_ids": ";".join(dict.fromkeys(r["issuer_id"].split(".")[0] for r in hist if r["issuer_id"])),
        "first_start": min((r["start_date"] for r in hist), default=""),
        "last_end": "" if any(not r["end_date"] for r in hist) else max((r["end_date"] for r in hist), default=""),
        "intervals": str(len(hist)),
        "delist_date": end.get("delist_date", ""), "library_cik": end.get("cik", ""), "bucket": end.get("bucket", ""),
        "crsp_code": end.get("crsp_code", ""), "reason": end.get("reason", ""),
        "last_trade_date_source": end.get("last_trade_date_source", ""),
        "library_last_trade_close": end.get("last_trade_close", ""), "dlret_method": end.get("dlret_method", ""),
        "delist_filing_form": end.get("delist_filing_form", ""),
        "delist_filing_accession": end.get("delist_filing_accession", ""),
        "review_flags": end.get("review_flags", ""), "uncertain_reasons": reasons,
    }


def _field_name(r: Mapping[str, str]) -> str:
    if r["table"] == "delistings" and r["field"]:
        return r["field"]
    return f"{r['table']}.{r['field'] if r['table'] != 'delistings' else r['kind']}"


def case_rows(mismatches: Sequence[Mismatch], regressions: Sequence[Mapping[str, str]], tables: Tables, *,
              label: str, round_no: int, truth_sec: Mapping[str, str]) -> list[dict[str, str]]:
    """One case row per security and round. Mode mismatch lists its mismatched truth fields (side_a the truth,
    side_b the library); mode regression lists its report rows (side_a old, side_b new). `truth_sec` maps a truth
    case_id to its sec_id."""
    groups: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
    for m in mismatches:
        groups.setdefault((MISMATCH, m.case_id), []).append((mismatch_key(m), m.field, m.truth, m.library))
    for r in regressions:
        groups.setdefault((REGRESSION, r["sec_id"]), []).append((regression_key(r), _field_name(r), r["old"],
                                                                 r["new"]))
    out = []
    for (mode, key), items in sorted(groups.items(), key=lambda kv: (kv[0][0] != MISMATCH, kv[0][1])):
        sec = truth_sec[key] if mode == MISMATCH else key
        ctx = context(tables, sec)
        ticker = ctx["tickers"].split(";")[-1] if ctx["tickers"] else ""
        out.append({
            "case_id": f"{sec}_{label}-r{round_no}", "mode": mode, "sec_id": sec, "ticker": ticker,
            "truth_case_id": key if mode == MISMATCH else "",
            "keys": json.dumps([i[0] for i in items]), "fields": json.dumps([i[1] for i in items]),
            "side_a": json.dumps([i[2] for i in items]), "side_b": json.dumps([i[3] for i in items]), **ctx})
    return out


def write_cases(path: str | Path, rows: Sequence[Mapping[str, str]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _write_csv(path, CASE_COLUMNS, rows)


def rename_truth(rows: Sequence[Mapping[str, str]],
                 id_changes: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Truth rows whose placeholder sec_id now holds a FIGI (contract/id_changes.csv) take the new sec_id; the
    case_id stays. Returns the rows and one change-log entry per rename."""
    new_id = {r["old_sec_id"]: r["new_sec_id"] for r in id_changes if r.get("new_sec_id")}
    out, changes = [], []
    for r in rows:
        r = dict(r)
        if r["sec_id"] in new_id:
            changes.append(dict(case_id=r["case_id"], field="sec_id", old=r["sec_id"], new=new_id[r["sec_id"]],
                                reason="contract/id_changes.csv: the placeholder now holds a FIGI", report=""))
            r["sec_id"] = new_id[r["sec_id"]]
        out.append(r)
    return out, changes

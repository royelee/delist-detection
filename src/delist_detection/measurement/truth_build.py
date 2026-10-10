"""The first diagnosis truth file, from the normalization pass (spec 2026-10-03-diagnosis-truth-fixes, 1.2). The
diagnosis-truth-normalize workflow writes one JSON row per case under
data/diagnosis/truth_rows/; `assemble` turns each into a data/diagnosis_truth.csv row.

`assemble` applies what the agents could not decide:
- Ruling R2's FIGI check on a CUSIP change. The caller looks up the new CUSIP's composite, and a different
  composite makes two securities linked as a continuation.
- The pending fields, which become `*` with status ruling_pending.
- The residual list: known_wrong, with fixed_by residual.

`final_status` sets the status against the current run: pass, or known_wrong with the case map's sub-plan. A case
the reports found right but the library does not match becomes ruling_pending."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence

from .diagnosis_truth import COLUMNS, ENDING, ENDING_MOVED, NO_ENDING, NOT_SCORED, RULING_PENDING, SCORED, field_key
from .truth import KNOWN_WRONG, PASS, Judgement, noted

# What `composite_of` returns for an OpenFIGI answer that cannot settle R2 (an error, or several US lines), as
# against None (no US line: one security).
UNSETTLED = "unsettled"
SUB_PLANS = ("5a", "5b", "5c", "5d", "5e", "5f", "5g", "5h", "5i")
RESIDUAL = "residual"
CONTINUATION_BLANKS = ("drop_reason", "cash_per_share", "cash_currency", "stock_ratio", "price_sec_id",
                       "price_ticker", "price_date", "recovery_ratio")


def _note(row: dict[str, str], text: str) -> None:
    row["note"] = noted(row["note"], text)


def assemble(norm: Mapping, meta: Mapping[str, str], *, composite_of: Callable[[str], str | None],
             securities: Collection[str]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """One truth row (status provisional: ruling_pending, known_wrong residual, or blank) and its leg rows. `meta`
    gives the report's ticker, report, confidence and skeptic, and the delist_date of the ending it examined
    (`examined_delist_date`, from the diagnosis's source row)."""
    row = dict.fromkeys(COLUMNS, "")
    row.update(case_id=norm["case_id"], sec_id=norm["sec_id"], shape=norm["shape"], ticker=meta.get("ticker", ""),
               report=meta.get("report", ""), confidence=meta.get("confidence", ""), skeptic=meta.get("skeptic", ""),
               examined_delist_date=meta.get("examined_delist_date", ""),
               internal_last_trade_date=str(norm.get("internal_last_trade_date") or ""), note=norm.get("notes", ""))
    fields = norm.get("fields") or {}
    row.update({f: "" if fields.get(f) is None else str(fields.get(f, NOT_SCORED)) for f in SCORED})
    check = norm.get("identity_check") or {}
    if (check.get("new_cusip") and norm["sec_id"].startswith("BBG")
            and norm["shape"] in (NO_ENDING, ENDING_MOVED)):
        comp = composite_of(check["new_cusip"])
        if comp == UNSETTLED:
            # Nothing is guessed: an OpenFIGI error or several US lines cannot say one security or two.
            row["status"] = RULING_PENDING
            _note(row, f"R2: OpenFIGI could not settle the new CUSIP {check['new_cusip']} "
                       "(error or several US lines)")
        elif comp and comp != norm["sec_id"]:
            row.update(shape=ENDING, exit_kind="exchange", continuation="true", value_rule="continuation",
                       successor_sec_id=comp if comp in securities else NOT_SCORED,
                       **dict.fromkeys(CONTINUATION_BLANKS, ""))
            _note(row, f"R2: the new CUSIP {check['new_cusip']} has its own FIGI {comp}, so two securities")
    for p in norm.get("pending") or []:
        if p.get("field") in SCORED:
            row[p["field"]] = NOT_SCORED
        _note(row, f"pending {p.get('field')}: {p.get('question')}")
    if norm.get("pending"):
        row["status"] = RULING_PENDING
    elif norm.get("residual"):
        row.update(status=KNOWN_WRONG, fixed_by=RESIDUAL)
        _note(row, f"residual: {norm['residual']}")
    legs = [{"case_id": norm["case_id"], "leg": str(lg["leg"]), "ratio": str(lg["ratio"]),
             "price_sec_id": lg.get("price_sec_id", ""), "price_ticker": lg.get("price_ticker", ""),
             "price_date": lg.get("price_date", "")} for lg in norm.get("legs") or []]
    return row, legs


def final_status(row: dict[str, str], ok: bool, sub_plan: str) -> None:
    """The status against the current run, for a row whose status `assemble` left blank."""
    if row["status"]:
        return
    if ok:
        row.update(status=PASS, fixed_by="")
    elif sub_plan in SUB_PLANS:
        row.update(status=KNOWN_WRONG, fixed_by=sub_plan)
    else:
        row["status"] = RULING_PENDING
        _note(row, "the library differs, but the case map gives no sub-plan (the report found it right)")


def review_markdown(rows: Sequence[Mapping[str, str]], judgements: Sequence[Judgement]) -> str:
    """The operator's review page for the built truth file."""
    status = Counter(r["status"] for r in rows)
    shape = Counter(r["shape"] for r in rows)
    fixed = Counter(r["fixed_by"] for r in rows if r["status"] == KNOWN_WRONG)
    fields = Counter(field_key(m.field) for j in judgements for m in j.mismatches)
    out = ["# Diagnosis truth file: review", "",
           f"{len(rows)} cases. Status: {dict(status)}. Shape: {dict(shape)}.", "",
           "## known_wrong by sub-plan", "", *[f"- {k}: {v}" for k, v in sorted(fixed.items())], "",
           "## Mismatches by field (judged cases)", "", *[f"- {k}: {v}" for k, v in fields.most_common()], "",
           "## Pending questions", ""]
    out += [f"- {r['case_id']} ({r['ticker']}): {r['note']}" for r in rows if r["status"] == RULING_PENDING]
    out += ["", "## Residual list", ""]
    out += [f"- {r['case_id']} ({r['ticker']}): {r['note']}" for r in rows if r["fixed_by"] == RESIDUAL]
    return "\n".join(out) + "\n"

"""Assemble output/diagnose_unknown_report/summary.csv from records/*.json, and print the counts.

Run from the repo root: python .claude/skills/diagnose-delisting/summarize.py
The summary is the batch's index and its resume checkpoint: a case with a record is done.
"""
import csv
import json
from collections import Counter
from pathlib import Path

OUT = Path("output/diagnose_unknown_report")
COLUMNS = ["case_id", "sec_id", "ticker", "report", "event_type", "consideration", "confidence", "exit_kind",
           "drop_reason", "continuation", "successor_ticker", "last_trade_date", "value_rule", "cash_per_share",
           "cash_currency", "stock_ratio", "price_ticker", "price_date", "value_formula",
           "status_exit_kind", "status_last_trade_date", "status_successor", "status_value_rule", "status_terms",
           "status_issuer", "status_ticker_history", "confidence_reasons", "library_wrong", "cause", "cause_group",
           "golden_worthy", "sec_evidence", "web_evidence", "open_checks", "verdict",
           "verification", "verification_refuted"]

# The end-of-run merge of `other:` tags into named groups (the record keeps the agent's own tag).
OTHER_GROUPS = {
    "reverse_split": "reverse_split_read_as_ending",
    "last_trade_off_by_one": "last_trade_date_misread", "suspension_date_taken": "last_trade_date_misread",
    "ex99_notice_date_is_bankruptcy": "last_trade_date_misread", "bankruptcy_ending_dated_at_filing": "last_trade_date_misread",
    "midas_date_from_reused_ticker": "reused_ticker_data", "midas_ticker_reuse": "reused_ticker_data",
    "last_close_from_reused_symbol": "reused_ticker_data",
    "otc_price_ticker": "price_security_wrong", "price_ticker_not_otc_symbol": "price_security_wrong",
    "new_equity_valued_as_otc_print": "price_security_wrong", "acquirer_price_security_null": "price_security_wrong",
    "form25": "form25_matching", "rights_only_form25": "form25_matching",
    "one_to_many_reclassification": "reclassification_not_linked", "tracking_stock_reclassification": "reclassification_not_linked",
    "class_conversion_not_linked": "reclassification_not_linked", "Class B": "reclassification_not_linked",
    "acquirer_read_as_target": "wrong_exit_kind", "when_issued_ticker": "identity_wrong",
}


def cause_group(cause: str) -> str:
    if not cause.startswith("other:"):
        return cause
    note = cause[len("other:"):]
    return next((g for k, g in OTHER_GROUPS.items() if note.startswith(k)), cause)


rows = []
for p in sorted((OUT / "records").glob("*.json")):
    r = json.loads(p.read_text())
    flat = {k: r.get(k, "") for k in COLUMNS if not k.startswith("status_")}
    for k, v in (r.get("status") or {}).items():
        flat[f"status_{k}"] = v
    flat["open_checks"] = " | ".join(r.get("open_checks") or [])
    flat["confidence_reasons"] = " | ".join(r.get("confidence_reasons") or [])
    flat["cause_group"] = cause_group(r.get("cause", ""))
    v = r.get("verification")
    flat["verification"] = "" if not v else ("upheld" if v.get("upheld") else "refuted")
    flat["verification_refuted"] = " | ".join(
        f"{f['field']}: {f['why']}" if isinstance(f, dict) else str(f) for f in (v or {}).get("fields_refuted") or [])
    rows.append(flat)
with open(OUT / "summary.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)

source = list(csv.DictReader(open(OUT / "source.csv")))
done = {r["case_id"] for r in rows}
print(f"{len(rows)} of {len(source)} cases have a record; {len(source) - len(done & {s['case_id'] for s in source})} to go")
print("library wrong:", sum(str(r["library_wrong"]).lower() == "true" for r in rows),
      "| skeptic upheld:", sum(r["verification"] == "upheld" for r in rows),
      "refuted:", sum(r["verification"] == "refuted" for r in rows))
print("confidence:", dict(Counter(r["confidence"] for r in rows)))
print("cause group:", dict(Counter(r["cause_group"] for r in rows).most_common()))
wrong = [r for r in rows if str(r["library_wrong"]).lower() == "true"]
print("cause group, library wrong only:", dict(Counter(r["cause_group"] for r in wrong).most_common()))

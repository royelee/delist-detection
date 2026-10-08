"""Build data/diagnosis_truth.csv (and its legs) from the normalization pass (spec
2026-10-03-diagnosis-truth-fixes, 1.2).

  python scripts/build_diagnosis_truth.py             # NETWORK: OpenFIGI for new CUSIPs not yet cached
  python scripts/build_diagnosis_truth.py --no-figi   # offline: no R2 check (lists the unchecked cases)

Reads output/diagnose_unknown_report/truth_rows/*.json, records/*.json (confidence, verification), source.csv (the
delist_date each case examined), the case map (sub-plan per case) and the run's tables. Writes the truth file (--out,
by default the one data/scorecard.json names) and its legs file as one new truth set (`truth_set.TruthSet.new`; the
legs are named after the truth file), and output/diagnose_unknown_report/truth_review.md. Exit 2: a missing input or
a row the truth set refuses.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from delist_detection.atomic_io import write_atomic
from delist_detection.diagnosis_truth import LibraryRows, judge_case, parse_legs, parse_rows
from delist_detection.figi_resolution import us_candidates
from delist_detection.openfigi import OpenFigiClient, resolve_api_key
from delist_detection.run_snapshot import RunSnapshot
from delist_detection.truth import TruthFileError
from delist_detection.truth_build import UNSETTLED, assemble, final_status, review_markdown
from delist_detection.truth_set import TruthSet, configured

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / "output" / "diagnose_unknown_report"


def _figi(no_figi: bool):
    if no_figi:
        return lambda cusip: None
    client = OpenFigiClient(ROOT / "cache" / "openfigi", resolve_api_key())

    def composite_of(cusip: str) -> str | None:
        ans = client.map([{"idType": "ID_CUSIP", "idValue": cusip, "includeUnlistedEquities": True}])[0]
        if ans.get("error") and not ans.get("data"):
            return UNSETTLED
        cands = us_candidates(ans.get("data") or [])
        if len(cands) > 1:
            return UNSETTLED
        return cands[0].composite if cands else None
    return composite_of


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rows", type=Path, default=DIAG / "truth_rows")
    p.add_argument("--records", type=Path, default=DIAG / "records")
    p.add_argument("--source", type=Path, default=DIAG / "source.csv", help="the cases the reports examined")
    p.add_argument("--case-map", type=Path,
                   default=ROOT / "docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes/case_map.csv")
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--out", type=Path, help="the truth file (default: the one data/scorecard.json names)")
    p.add_argument("--review", type=Path, default=DIAG / "truth_review.md")
    p.add_argument("--no-figi", action="store_true")
    args = p.parse_args(argv)
    try:
        norms = [json.loads(f.read_text()) for f in sorted(args.rows.glob("*.json"))]
        with args.case_map.open(newline="") as fh:
            sub_plan = {r["case_id"]: r["sub_plan"] for r in csv.DictReader(fh)}
        with args.source.open(newline="") as fh:
            examined = {r["case_id"]: r["delist_date"] for r in csv.DictReader(fh)}
        tables = RunSnapshot.read(args.output_dir)
        records = {}
        for n in norms:
            rec_path = args.records / f"{n['case_id']}.json"
            try:
                records[n["case_id"]] = json.loads(rec_path.read_text()) if rec_path.exists() else {}
            except ValueError as exc:
                raise ValueError(f"{rec_path}: {exc}") from exc
    except (OSError, ValueError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    missing = sorted(set(sub_plan) - {n["case_id"] for n in norms})
    if missing:
        print(f"ABORTED: no truth row for {len(missing)} case(s): {missing[:10]}", file=sys.stderr)
        return 2
    securities = {r["sec_id"] for r in tables.securities}
    composite_of = _figi(args.no_figi)
    rows, legs = [], []
    for n in norms:
        rec = records[n["case_id"]]
        v = rec.get("verification")
        meta = {"ticker": rec.get("ticker", ""), "report": rec.get("report", ""),
                "confidence": rec.get("confidence", ""),
                "skeptic": "" if not v else ("upheld" if v.get("upheld") else "refuted"),
                "examined_delist_date": examined.get(n["case_id"], "")}
        row, leg_rows = assemble(n, meta, composite_of=composite_of, securities=securities)
        rows.append(row)
        legs += leg_rows
    if args.no_figi:
        unchecked = [n["case_id"] for n in norms if (n.get("identity_check") or {}).get("new_cusip")]
        print(f"--no-figi: R2 not checked for {len(unchecked)} case(s): {unchecked[:10]}")
    legs.sort(key=lambda r: (r["case_id"], int(r["leg"])))
    try:
        out = args.out or configured(ROOT)
        legs_by_case = parse_legs(legs, "built legs")
        lib = LibraryRows.of(tables)
        for row in rows:
            # A row assemble left without a status is judged as if it were `pass`; final_status then decides.
            [case] = parse_rows([{**row, "status": row["status"] or "pass"}], f"truth row {row['case_id']}",
                                legs_by_case)
            final_status(row, judge_case(case, lib).ok, sub_plan.get(row["case_id"], ""))
        cases = parse_rows(rows, "built truth", legs_by_case)
        rows.sort(key=lambda r: r["case_id"])
        TruthSet.new(out, rows, legs).commit()
    except TruthFileError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    judged = [judge_case(c, lib) for c in cases if c.status != "ruling_pending"]
    args.review.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(args.review, review_markdown(rows, judged))
    status = {s: sum(r["status"] == s for r in rows) for s in ("pass", "known_wrong", "ruling_pending")}
    print(f"{len(rows)} truth rows {status}, {len(legs)} legs -> {out}, review {args.review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

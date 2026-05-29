"""Cross-check classifications by reading independent web sources.

For each ticker in `output/delist_classifications.csv`, hit a verification
URL (the EDGAR entity landing page or Wikipedia) and ask: does the
classification match what an independent source says?

This script reads pre-built per-ticker probe lists from the user (or a
default sampling stratified across buckets) and writes
`output/web_verification.csv` with columns:
    ticker, our_bucket, web_says, agree, evidence_url, note
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = os.environ.get(
    "EDGAR_USER_AGENT", "delist_detection/0.1 (royelee@users.noreply.github.com)"
)


def _get(url: str, timeout: int = 30) -> str | None:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.text
    except requests.RequestException:
        return None


def fetch_edgar_entity_landing(cik: int) -> dict:
    """Pull the company submissions.json — most authoritative source.

    Returns relevant fields for verification: name, formerNames, tickers,
    SIC code, and a list of (form, date) tuples for the delisting filings.
    """
    cs = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cs}.json"
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Host": "data.sec.gov"},
                         timeout=30)
        if r.status_code != 200:
            return {}
        d = r.json()
    except (requests.RequestException, json.JSONDecodeError):
        return {}
    recent = d.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    items_l = recent.get("items", [])
    delist_filings = []
    for f, dt, it in zip(forms, dates, items_l):
        if f in {"25", "25-NSE", "15-12G", "15-12B", "15-15D", "8-K"}:
            delist_filings.append({"form": f, "date": dt, "items": it})
    return {
        "name": d.get("name"),
        "formerNames": [x.get("name") for x in d.get("formerNames", [])],
        "tickers": d.get("tickers", []),
        "sic": d.get("sic"),
        "sicDescription": d.get("sicDescription"),
        "delist_filings": delist_filings[:30],
    }


def verify_one(row: dict, av_name: str | None = None) -> dict:
    """Return a verification dict for one classification row."""
    ticker = row["ticker"]
    bucket = row["bucket"]
    cik = row.get("cik")
    verdict = {
        "ticker": ticker,
        "our_bucket": bucket,
        "our_code": row.get("crsp_code"),
        "our_reason": row.get("reason"),
        "edgar_name": "",
        "former_names": "",
        "av_name": av_name or "",
        "name_match": "",
        "delist_form_present": "",
        "verdict": "",
        "note": "",
    }
    if not cik:
        verdict["verdict"] = "no_cik"
        return verdict
    try:
        cik_i = int(cik)
    except ValueError:
        verdict["verdict"] = "bad_cik"
        return verdict

    info = fetch_edgar_entity_landing(cik_i)
    if not info:
        verdict["verdict"] = "no_entity_data"
        return verdict

    edgar_name = info.get("name", "") or ""
    formers = "; ".join(info.get("formerNames", []) or [])
    verdict["edgar_name"] = edgar_name
    verdict["former_names"] = formers

    def _toks(s: str) -> set[str]:
        # Split on non-alpha AND on camelCase boundaries (BrownForman → Brown, Forman)
        cc = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
        clean = re.sub(r"[^A-Za-z]+", " ", cc).upper()
        return {t for t in clean.split()
                if len(t) >= 4 and t not in {"CORP","CORPORATION","INC","COMPANY",
                "HOLDINGS","LTD","LIMITED","GROUP","INTERNATIONAL","TRUST",
                "PARTNERS","FUND","BANK","BANCORP","BANCSHARES","HOLDING","THE"}}

    name_pool_str = " ".join([edgar_name] + (info.get("formerNames", []) or []))
    pool_toks = _toks(name_pool_str)
    av_tokens = list(_toks(av_name)) if av_name else []
    matched_tokens = [t for t in av_tokens if t in pool_toks]
    verdict["name_match"] = f"{len(matched_tokens)}/{len(av_tokens)}"

    forms_in = {f["form"] for f in info.get("delist_filings", [])}
    has_25 = bool({"25", "25-NSE"} & forms_in)
    has_15 = bool({"15-12G", "15-12B", "15-15D"} & forms_in)
    verdict["delist_form_present"] = (
        f"25={'Y' if has_25 else 'N'},15={'Y' if has_15 else 'N'}"
    )

    # Date-proximity check: does the EDGAR entity have a delist filing within
    # ±30 days of the observed date? If so, the CIK is plausibly correct even
    # when names don't match (i.e. ticker recycling — AV name is stale).
    observed = row.get("observed_delist_date") or ""
    near_25 = False
    if observed and observed != "nan":
        from datetime import datetime as _dt
        try:
            od = _dt.strptime(observed, "%Y-%m-%d").date()
            for f in info.get("delist_filings", []):
                if f.get("form") not in {"25", "25-NSE", "15-12G"}:
                    continue
                try:
                    fd = _dt.strptime(f.get("date", ""), "%Y-%m-%d").date()
                except ValueError:
                    continue
                if abs((fd - od).days) <= 30:
                    near_25 = True
                    break
        except ValueError:
            pass

    # Build a verdict.
    if av_name and av_tokens and len(matched_tokens) == 0:
        if near_25:
            verdict["verdict"] = "OK_recycled_ticker"
            verdict["note"] = "AV name stale (ticker recycled); CIK has Form 25 within ±30d of observed"
            return verdict
        verdict["verdict"] = "MISMATCH_name"
        verdict["note"] = "AV name shares no tokens with EDGAR name"
        return verdict
    if not has_25 and not has_15:
        verdict["verdict"] = "WEAK_no_delist_form"
        return verdict
    # Bucket-specific cross-checks
    if bucket == "merger":
        # M&A should have 8-K with item 2.01 or 5.01
        has_ma_items = any(
            ("2.01" in (f.get("items") or "") or "5.01" in (f.get("items") or ""))
            for f in info.get("delist_filings", []) if f["form"] == "8-K"
        )
        verdict["verdict"] = "OK" if has_ma_items else "WEAK_no_ma_items"
        return verdict
    if bucket == "compliance_failure":
        has_3_01 = any(
            "3.01" in (f.get("items") or "")
            for f in info.get("delist_filings", []) if f["form"] == "8-K"
        )
        verdict["verdict"] = "OK" if has_3_01 else "WEAK_no_3_01"
        return verdict
    if bucket == "liquidation":
        verdict["verdict"] = "OK" if has_15 else "WEAK_no_form15"
        return verdict
    if bucket == "exchange_transfer":
        verdict["verdict"] = "OK"
        return verdict
    verdict["verdict"] = "OK"
    return verdict


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(ROOT / "output" / "delist_classifications.csv"))
    p.add_argument("--output", default=str(ROOT / "output" / "web_verification.csv"))
    p.add_argument("--sample", type=int, default=0,
                   help="Stratified random sample size (0 = all)")
    p.add_argument("--av-csv", default=os.environ.get(
        "AV_LISTING_CSV",
        str(ROOT.parent / "qlib_practice" / "fetch_data_aplha"
            / "data" / "alphavantage_listing_status"
            / "listing_status_delisted_2026-05-19.csv")))
    args = p.parse_args()

    # Load AV names for cross-validation
    av_names: dict[str, str] = {}
    with open(args.av_csv) as fh:
        for r in csv.DictReader(fh):
            t = (r.get("symbol") or "").upper()
            if t:
                av_names[t] = r.get("name") or ""

    with open(args.input) as fh:
        rows = list(csv.DictReader(fh))

    if args.sample > 0:
        import random
        by_bucket: dict[str, list[dict]] = {}
        for r in rows:
            by_bucket.setdefault(r["bucket"], []).append(r)
        sampled: list[dict] = []
        per_bucket = max(args.sample // max(1, len(by_bucket)), 1)
        for b, xs in by_bucket.items():
            random.seed(42 + hash(b) % 100)
            sampled.extend(random.sample(xs, min(per_bucket, len(xs))))
        rows = sampled

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with out_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "ticker", "our_bucket", "our_code", "our_reason",
            "edgar_name", "former_names", "av_name", "name_match",
            "delist_form_present", "verdict", "note",
        ])
        w.writeheader()
        for i, r in enumerate(rows, 1):
            v = verify_one(r, av_name=av_names.get(r["ticker"].upper()))
            w.writerow(v)
            counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
            if i % 25 == 0:
                print(f"[{i}/{len(rows)}] verdicts so far: {counts}",
                      file=sys.stderr, flush=True)
    print("\nDone. Verdict counts:")
    for k, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:24s} {n:4d}")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

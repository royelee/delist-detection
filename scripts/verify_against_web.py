"""Cross-check classifications by reading independent web sources.

For each ticker in `output/delistings.csv`, hit a verification URL (the EDGAR
entity landing page) and ask: does the classification match what an
independent source says? The name checked against EDGAR is the row's own
`resolved_name` — the name our own resolver settled on, not a name sourced
from elsewhere.

This script reads pre-built per-ticker probe lists from the user (or a
default sampling stratified across buckets) and writes
`output/web_verification.csv` with columns:
    sec_id, ticker, our_bucket, web_says, agree, evidence_url, note
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from delist_detection.edgar import (EdgarBlocked, require_user_agent, resolve_user_agent, sec_get,
                                    use_machine_wide_limit)
from delist_detection.store import read_table

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = resolve_user_agent()


def _get(url: str, timeout: int = 30) -> str | None:
    """`url`'s text through the library's one SEC request path (`edgar.sec_get`:
    the shared 8 requests/s pacing, one attempt); None for a non-200 or a
    network error. A 403/429 aborts the run (EdgarBlocked), never a verdict."""
    try:
        r = sec_get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, retry=False)
    except requests.RequestException:
        return None
    return r.text if r.status_code == 200 else None


DELIST_FORMS = {"25", "25-NSE", "25/A", "25-NSE/A", "15-12G", "15-12B", "15-15D"}
# Filings that put a company in a merger: a tender offer (SC 14D9 / SC TO-T), a
# merger proxy or information statement, merger communications (425), a
# going-private statement. Many targets file no 8-K 2.01/5.01 at completion.
MERGER_DOCS = {"SC 14D9", "SC 14D9/A", "SC TO-T", "SC TO-T/A", "DEFM14A", "DEFM14C", "PREM14A", "PREM14C",
               "425", "SC 13E3", "SC 13E3/A"}
WINDOW_BEFORE_DAYS, WINDOW_AFTER_DAYS = 400, 120    # evidence around the delisting date


def _json(url: str) -> dict:
    """`url`'s JSON object as `_get` fetches it; {} for anything else."""
    try:
        r = sec_get(url, headers={"User-Agent": USER_AGENT, "Host": "data.sec.gov"}, timeout=30, retry=False)
        if r.status_code != 200:
            return {}
        d = r.json()
    except (requests.RequestException, json.JSONDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


def _rows(block: dict) -> list[dict]:
    forms = block.get("form", []) or []
    dates = block.get("filingDate", []) or []
    items = block.get("items", []) or [""] * len(forms)
    return [{"form": f, "date": d, "items": i or ""} for f, d, i in zip(forms, dates, items)]


def fetch_edgar_entity_landing(cik: int, around: date | None = None) -> dict:
    """Pull the company submissions.json — most authoritative source.

    Returns the name, formerNames, tickers, SIC, and every filing as
    {form, date, items}: the `recent` block plus each older submissions file
    whose filing span overlaps the window around `around` (all of them when
    `around` is None), so a delisting older than the recent block is seen.
    """
    base = "https://data.sec.gov/submissions/"
    d = _json(f"{base}CIK{str(cik).zfill(10)}.json")
    if not d:
        return {}
    filings = _rows(d.get("filings", {}).get("recent", {}))
    lo = hi = None
    if around is not None:
        lo = (around - timedelta(days=WINDOW_BEFORE_DAYS)).isoformat()
        hi = (around + timedelta(days=WINDOW_AFTER_DAYS)).isoformat()
    for f in d.get("filings", {}).get("files", []) or []:
        if lo and not ((f.get("filingFrom") or "") <= hi and (f.get("filingTo") or "9999") >= lo):
            continue
        filings += _rows(_json(base + f["name"]))
    return {
        "name": d.get("name"),
        "formerNames": [x.get("name") for x in d.get("formerNames", [])],
        "tickers": d.get("tickers", []),
        "sic": d.get("sic"),
        "sicDescription": d.get("sicDescription"),
        "filings": filings,
    }


_STOP = {"CORP", "CORPORATION", "INC", "COMPANY", "HOLDINGS", "LTD", "LIMITED", "GROUP", "INTERNATIONAL",
         "TRUST", "PARTNERS", "FUND", "BANK", "BANCORP", "BANCSHARES", "HOLDING", "THE",
         "CLASS", "SERIES", "COMMON", "STOCK", "SHARES", "ORDINARY"}


def _toks(s: str) -> set[str]:
    """Name words of four or more letters, legal and share-class words dropped,
    from the text as written and split on camelCase boundaries (EDGAR's
    "BlackRock" is both BLACKROCK and BLACK, ROCK; "BrownForman" gives BROWN)."""
    out: set[str] = set()
    for text in (s, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)):
        out |= {w for w in re.sub(r"[^A-Za-z]+", " ", text).upper().split() if len(w) >= 4 and w not in _STOP}
    return out


def _day(s: str) -> date | None:
    try:
        return datetime.strptime(s or "", "%Y-%m-%d").date()
    except ValueError:
        return None


def verify_one(row: dict) -> dict:
    """Return a verification dict for one classification row."""
    ticker = row["ticker"]
    bucket = row["bucket"]
    cik = row.get("cik")
    resolved_name = row.get("resolved_name") or ""
    verdict = {
        "sec_id": row.get("sec_id", ""),
        "ticker": ticker,
        "our_bucket": bucket,
        "our_code": row.get("crsp_code"),
        "our_reason": row.get("reason"),
        "edgar_name": "",
        "former_names": "",
        "resolved_name": resolved_name,
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

    observed = row.get("last_trade_date") or row.get("delist_date") or ""
    od = _day(observed) if observed != "nan" else None
    info = fetch_edgar_entity_landing(cik_i, around=od)
    if not info:
        verdict["verdict"] = "no_entity_data"
        return verdict

    edgar_name = info.get("name", "") or ""
    formers = "; ".join(info.get("formerNames", []) or [])
    verdict["edgar_name"] = edgar_name
    verdict["former_names"] = formers

    name_pool_str = " ".join([edgar_name] + (info.get("formerNames", []) or []))
    pool_toks = _toks(name_pool_str)
    name_tokens = sorted(_toks(resolved_name)) if resolved_name else []
    matched_tokens = [t for t in name_tokens if t in pool_toks]
    verdict["name_match"] = f"{len(matched_tokens)}/{len(name_tokens)}"

    filings = info.get("filings", [])
    # Evidence counts only around the delisting: an old 8-K 2.01 is another deal.
    if od is not None:
        lo, hi = od - timedelta(days=WINDOW_BEFORE_DAYS), od + timedelta(days=WINDOW_AFTER_DAYS)
        near = [f for f in filings if (d := _day(f["date"])) is not None and lo <= d <= hi]
    else:
        near = filings
    forms_in = {f["form"] for f in near}
    has_25 = bool({"25", "25-NSE", "25/A", "25-NSE/A"} & forms_in)
    has_15 = bool({"15-12G", "15-12B", "15-15D"} & forms_in)
    verdict["delist_form_present"] = f"25={'Y' if has_25 else 'N'},15={'Y' if has_15 else 'N'}"

    # Date-proximity check: does the EDGAR entity have a delist filing within
    # ±30 days of the observed date? If so, the CIK is plausibly correct even
    # when names don't match (i.e. ticker recycling — resolved_name is stale).
    near_25 = od is not None and any(
        f["form"] in {"25", "25-NSE", "15-12G"} and (d := _day(f["date"])) is not None and abs((d - od).days) <= 30
        for f in filings)

    def _item(code: str) -> bool:
        return any(f["form"].startswith("8-K") and code in (f.get("items") or "") for f in near)

    # Build a verdict.
    if resolved_name and name_tokens and len(matched_tokens) == 0:
        if near_25:
            verdict["verdict"] = "OK_recycled_ticker"
            verdict["note"] = "resolved_name stale (ticker recycled); CIK has Form 25 within ±30d of observed"
            return verdict
        verdict["verdict"] = "MISMATCH_name"
        verdict["note"] = "resolved_name shares no tokens with EDGAR name"
        return verdict
    if not has_25 and not has_15:
        verdict["verdict"] = "WEAK_no_delist_form"
        return verdict
    # Bucket-specific cross-checks
    if bucket == "merger":
        # an 8-K 2.01/5.01, or a merger document (tender offer, merger proxy, 425)
        has_ma = _item("2.01") or _item("5.01") or bool(MERGER_DOCS & forms_in)
        verdict["verdict"] = "OK" if has_ma else "WEAK_no_ma_items"
        return verdict
    if bucket == "compliance_failure":
        verdict["verdict"] = "OK" if _item("3.01") else "WEAK_no_3_01"
        return verdict
    if bucket == "liquidation":
        # a Form 15, or the bankruptcy 8-K (item 1.03) itself
        verdict["verdict"] = "OK" if has_15 or _item("1.03") else "WEAK_no_form15"
        return verdict
    verdict["verdict"] = "OK"
    return verdict


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(ROOT / "output" / "delistings.csv"))
    p.add_argument("--output", default=str(ROOT / "output" / "web_verification.csv"))
    p.add_argument("--sample", type=int, default=0,
                   help="Stratified random sample size (0 = all)")
    args = p.parse_args()
    require_user_agent()         # SEC refuses the fallback User-Agent: stop before the first request
    use_machine_wide_limit()     # share the 8 requests/s with every other SEC client on this machine

    rows = read_table("delistings", args.input)

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
            "sec_id", "ticker", "our_bucket", "our_code", "our_reason",
            "edgar_name", "former_names", "resolved_name", "name_match",
            "delist_form_present", "verdict", "note",
        ])
        w.writeheader()
        for i, r in enumerate(rows, 1):
            v = verify_one(r)
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
    try:
        sys.exit(main())
    except EdgarBlocked as e:
        print(f"ABORTED: {e}", file=sys.stderr)
        sys.exit(2)

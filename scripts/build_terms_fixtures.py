"""Build tests/fixtures/terms/ (sub-plan 5f's real terms cases) from the local caches and one run's tables.

For each case of CASES: the merger ending the run published (its delistings.csv row: last trade, last close,
acquirer price, acquirer security and the contract's price ticker), the prompt-v3 LLM answer the run read for it
(cache/llm, the filing it came from), and the regex payout read (payout_extractor over the cached filing texts).
tests/terms_cases.py replays the payout gate and the payout rule over them.

  PYTHONPATH=src python scripts/build_terms_fixtures.py --run /tmp/claude/delist_detection/5f/out

Offline: every filing text and LLM answer must be cached (a missing one is an error, never a fetch). Rerun only to
add a case.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.classifier import DelistRecord          # noqa: E402
from delist_detection.crsp_codes import CrspBucket             # noqa: E402
from delist_detection.edgar import EdgarClient                 # noqa: E402
from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor   # noqa: E402
from delist_detection.payout_extractor import PayoutExtractor  # noqa: E402

# case_id -> what it pins: a rule that moves it (R5, R4, R3, the stock value leg) or a guard that keeps it
CASES = {
    "BBG000BB2N27_2014-12-25": "THI: C$65.50 + 0.8025 QSR, CAD; the gate skips the CAD leg (R5)",
    "BBG000BMDV41_2016-09-16": "JCI: the default package $5.7293 + 0.8357, not the stock alternative (R4)",
    "BBG000BPQVR5_2015-07-12": "RKT: the default package 1 WRK, not the cash electors' (R4)",
    "BBG000BTMDX4_2012-04-06": "SUG: non-electors got 1.0 ETE unit; the regex's $44.25 alternative is dropped (R4)",
    "BBG000G61VB6_2007-07-23": "BOT: the amended 0.375 CME, the 8-K after the proxy",
    "BBG000BNVNY4_2021-12-12": "MDP: $16.99 + $42.18 = $59.17 total cash",
    "BBG000C11MQ5_2015-06-05": "PCYC: $152.25 + $109.00 of AbbVie, a dollar-valued leg",
    "BBG000N8Y8W6_2017-07-27": "AWH: $23.00 + 0.057937 Fairfax with no last close: the package over the regex cash",
    "BBG000BK1FD3_2014-12-04": "FWLT: $16.00 + 0.8998 with no last close: the package over the $32.00 headline",
    "CIK804055-COMMON_2010-10-15": "CCE 2010: $10.00 + 1 New CCE (CCE), not KO",
    "BBG000BB5HV5_2010-12-19": "ADCT: a regex cash read, USD (R5)",
    "BBG000BGFLL5_2013-11-23": "NYX (guard): the default package 11.27 + 0.1703 ICE passes",
    "BBG000PTXBV3_2016-07-22": "HTS (guard): 5.55 + 0.9894 NLY passes",
    "BBG000BTN971_2012-10-20": "SUN (guard): 25.00 + 0.5245 ETP passes",
    "BBG0017T9998_2020-07-30": "CZR (guard): the no-election cash default, 12.41",
    "BBG0077VS2C0_2026-07-11": "BLD (guard): the prorated aggregate 249.67 + 10.212 QXO, never 505 or 20.2 summed",
    "BBG00LT2PDY4_2021-08-05": "BPYU: $12.38 + 0.0913 BAM + 0.0657 BPY preferred, a basket (R3)",
    "BBG00FFJY867_2025-05-17": "LGFB: 1 LION + 1 STRZ, a basket (R3; the truth's 1/15 is Starz's later consolidation)",
}
VALUE_FIELDS = ("value_rule", "cash_per_share", "cash_currency", "stock_ratio", "price_ticker")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", type=Path, required=True, help="the run folder whose tables the cases come from")
    p.add_argument("--model", default="gpt-5.4")
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "terms")
    args = p.parse_args(argv)

    truth = {r["case_id"]: r for r in csv.DictReader(open(ROOT / "data" / "diagnosis_truth.csv"))}
    truth_legs: dict[str, list[dict]] = {}
    for r in csv.DictReader(open(ROOT / "data" / "diagnosis_truth_legs.csv")):
        truth_legs.setdefault(r["case_id"], []).append({k: r[k] for k in ("leg", "ratio", "price_ticker")})
    rows: dict[str, list[dict]] = {}
    for r in csv.DictReader(open(args.run / "delistings.csv")):
        rows.setdefault(r["sec_id"], []).append(r)
    contract = {r["sec_id"]: r for r in csv.DictReader(open(args.run / "contract" / "delistings.csv"))}
    names = {r["sec_id"]: r["name"] for r in csv.DictReader(open(args.run / "securities.csv"))}

    edgar = EdgarClient(cache_dir=ROOT / "cache" / "edgar", sleep=lambda s: None, today=date(2026, 9, 25))
    llm = LLMMergerTermsExtractor(edgar, None, model=args.model, cache_dir=ROOT / "cache" / "llm")
    regex = PayoutExtractor(edgar)
    out = {}
    for cid, note in CASES.items():
        t = truth[cid]
        merger = [r for r in rows.get(t["sec_id"], []) if r["bucket"] == "merger"]
        if not merger:
            raise SystemExit(f"{cid}: no merger ending in {args.run}")
        r = max(merger, key=lambda x: x["delist_date"])
        anchor = r["last_trade_date"] or r["delist_filing_date"] or r["delist_date"]
        rec = DelistRecord(ticker=r["ticker"], cik=int(r["cik"]), observed_delist_date=anchor, crsp_code=231,
                           bucket=CrspBucket.MERGER, confidence="high", reason="", evidence={})
        answer, filing = None, None
        for f in llm._candidates(edgar.recent_filings(rec.cik), date.fromisoformat(anchor))[:6]:
            path = llm.cache_path(f, rec)
            if path.exists():
                answer, filing = json.loads(path.read_text()), {"form": f.form, "accession": f.accession}
                terms = llm._to_terms(answer, f)
                if terms is not None and (terms.cash_per_share is not None or terms.has_stock):
                    break
        close = float(r["last_trade_close"]) if r["last_trade_close"] else None
        read = regex.extract(rec, last_close=close)
        c = contract.get(t["sec_id"], {})
        out[cid] = {
            "note": note, "sec_id": t["sec_id"], "ticker": r["ticker"], "delist_date": r["delist_date"],
            "last_trade_date": r["last_trade_date"], "published_last_trade_date": c.get("last_trade_date", ""),
            "last_close": close, "name": names.get(t["sec_id"], ""),
            "acquirer_price": float(r["acquirer_price"]) if r["acquirer_price"] else None,
            "acquirer_sec_id": r["acquirer_sec_id"], "price_ticker": c.get("price_ticker", ""),
            "llm": answer, "filing": filing,
            "regex": None if read.value is None else {"value": read.value, "source": read.source,
                                                      "confidence": read.confidence, "currency": read.currency},
            "truth": {k: t[k] for k in VALUE_FIELDS}, "truth_legs": truth_legs.get(cid, []),
        }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "cases.json").write_text(json.dumps({"model": args.model, "cases": out}, indent=1, sort_keys=True)
                                         + "\n")
    print(f"{len(out)} cases -> {args.out / 'cases.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

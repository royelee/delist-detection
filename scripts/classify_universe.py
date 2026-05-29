"""Run the EDGAR-based classifier over the full Tiingo delisted set.

Reads:  data/delisted_tickers.tsv  (ticker\tstart\tend)
Writes: output/delist_classifications.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "delisted_tickers.tsv"
DEFAULT_OUTPUT = ROOT / "output" / "delist_classifications.csv"

from delist_detection import EdgarClient, TickerResolver, DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.av_listing import AvListingLoader
from delist_detection.payout_extractor import PayoutExtractor, PayoutResult


# Alpha Vantage LISTING_STATUS CSVs from the companion qlib_practice pipeline.
# Override with the AV_LISTING_CSV / AV_ACTIVE_CSV env vars; the defaults assume
# qlib_practice is checked out as a sibling of this repo.
_AV_DIR = ROOT.parent / "qlib_practice" / "fetch_data_aplha" / "data" / "alphavantage_listing_status"
AV_LISTING_CSV = os.environ.get(
    "AV_LISTING_CSV", str(_AV_DIR / "listing_status_delisted_2026-05-19.csv"))
AV_ACTIVE_CSV = os.environ.get(
    "AV_ACTIVE_CSV", str(_AV_DIR / "listing_status_active_2026-05-19.csv"))


KNOWN_RENAMES = {
    # Tiingo ticker -> SEC-current ticker (only when SEC has a different one)
    "FB": "META",
    "TWTR": "X",
    "COH": "TPR",
    "BHGE": "BKR",
    "CTL": "LUMN",
    "CREE": "WOLF",
}

# Manual ticker -> CIK overrides for short or ambiguous tickers where EDGAR
# full-text search picks the wrong issuer. Keep this list short — only add
# entries when web verification proves the resolver chose wrong.
# Verified via SEC EDGAR submissions JSON.
MANUAL_OVERRIDES: dict[str, int] = {
    "AET":   1122304,   # Aetna — CVS 2018
    "MER":   65100,     # Merrill Lynch — BofA 2008
    "HNZ":   46640,     # H.J. Heinz — 3G/Berkshire 2013
    "TWX":   1105705,   # Time Warner — AT&T 2018
    "MON":   1110783,   # Monsanto — Bayer 2018
    "KLG":   1959348,   # WK Kellogg — Ferraro 2025
    "RAI":   1275283,   # Reynolds American — BAT 2017
    "ALEX":  1545654,   # Alexander & Baldwin REIT — 2026
    "WYN":   1361658,   # Wyndham Worldwide → spun 2018 (continuing entity)
    "OCR":   353230,    # Omnicare — CVS 2015
    "VNTV":  1467373,   # Vantiv — Worldpay 2018
    "CONE":  1553023,   # CyrusOne — KKR 2022
    "DATA":  1303652,   # Tableau Software — Salesforce 2019
    "MNI":   1056087,   # McClatchy — Ch.11 2020
    "CNW":   23675,     # Con-way (Conway) — XPO 2015
    "GAS":   1004155,   # AGL Resources — Southern Co Gas 2016
    "SPW":   88205,     # SPX Corp — refiled/restructured 2015
    "BFA":   14693,     # Brown-Forman Class A (share class delist; co continues)
    "CWENA": 1567683,   # Clearway Energy Class A (share class change)
    "RICE":  1604665,   # Rice Energy — EQT 2017
    "IMCL":  1520047,   # ImmunoClin Corp (recycled ticker; SEC revoked 2019)
    # Tickers missing from AV — explicit knowledge of the rename
    "XTO":   868809,    # XTO Energy — ExxonMobil 2010; subsidiary dereg 2013
    "AH":    1472595,   # Accretive Health → R1 RCM (rename + ticker move)
    "KWK":   1283699,   # Quicksilver Resources — Ch.11 2015
    "PGN":   1094093,   # Progress Energy — Duke acquired 2012
    "WE":    1813756,   # WeWork (The We Company) — Ch.11 2023
    "SAVE":  1498710,   # Spirit Airlines — Ch.11 Nov 2024
    "CBH":   1018272,   # Commerce Bancshares (NJ) — TD Bank acquired 2007
    "FPL":   753308,    # FPL Group → NextEra Energy rename 2010
    "LGF-B": 929351,    # Lions Gate / Starz Class B — Starz spin 2024
    # Verified-wrong CIK corrections (frequency-search picked unrelated cos)
    "DAY":   1725057,   # Dayforce (Ceridian HCM) — Thoma Bravo 2026
    "IM":    1018003,   # Ingram Micro — HNA Group 2016
    "PLAN":  1540755,   # Anaplan — Thoma Bravo 2022 (verified via EFTS)
    "SEE":   1012100,   # Sealed Air — original CIK (verified)
    "STR":   751652,    # Questar Corp — Dominion 2016
    "TIN":   731939,    # Temple-Inland — IP 2012 (verified via EFTS)
    "TWTR":  1418091,   # Twitter — Musk 2022 (verified)
    "X":     1163302,   # United States Steel — Nippon 2024-25
    "XLS":   1524471,   # Exelis — Harris 2015 (verified via EFTS)
    "THOR":  350907,    # Thoratec — St. Jude 2015 (verified via EFTS)
    "THRX":  1080014,   # Theravance Inc — split 2014
    # (duplicate IMCL line removed; see above)
    "VNTV":  1533932,   # Vantiv → Worldpay merger 2018 (verified)
    "RICE":  1588238,   # Rice Energy — EQT 2017 (verified)
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(DEFAULT_INPUT))
    p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    p.add_argument("--limit", type=int, default=None,
                   help="Process only first N tickers (for smoke testing)")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--no-extract-payouts", action="store_true",
                   help="Skip per-share payout extraction (faster dev re-run)")
    p.add_argument("--payouts-output",
                   default=str(ROOT / "output" / "payouts.csv"))
    args = p.parse_args()

    edgar = EdgarClient(cache_dir=ROOT / "cache" / "edgar")
    av = AvListingLoader(AV_LISTING_CSV, active_csv_path=AV_ACTIVE_CSV)
    resolver = TickerResolver(
        edgar,
        rename_map=KNOWN_RENAMES,
        manual_overrides={k: v for k, v in MANUAL_OVERRIDES.items() if v > 0},
        cache_path=ROOT / "cache" / "ticker_resolution.json",
        name_lookup=av.name,
    )
    classifier = DelistClassifier(
        edgar, resolver,
        asset_type_lookup=av.asset_type,
        name_hint_lookup=av.name,
    )

    rows: list[tuple[str, str | None]] = []
    with open(args.input) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            ticker, _start, end = parts[0], parts[1], parts[2]
            rows.append((ticker, end))
    if args.limit:
        rows = rows[: args.limit]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    bucket_counts: dict[str, int] = {}
    extractor = None if args.no_extract_payouts else PayoutExtractor(edgar)
    payout_by_ticker: dict[str, PayoutResult] = {}

    HEADER = [
        "ticker", "cik", "observed_delist_date", "crsp_code", "bucket",
        "confidence", "reason", "delist_filing_form", "delist_filing_date",
        "anchor_8k_items", "dereg_form", "resolved_name", "resolution_source",
        "payout_per_share", "payout_source", "payout_confidence",
    ]
    with out_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for i, (ticker, observed) in enumerate(rows, start=1):
            try:
                rec = classifier.classify_ticker(ticker, observed)
            except Exception as e:  # network or parse failures should not abort
                rec = None
                err = f"{type(e).__name__}: {e}"
                if not args.quiet:
                    print(f"[{i:4d}/{len(rows)}] {ticker}: ERROR {err}", file=sys.stderr)
                # Derive the trailing empties from HEADER so a future column
                # change can't silently desync the error row from the header.
                err_prefix = [ticker, "", observed, "", "unknown", "none", err]
                writer.writerow(err_prefix + [""] * (len(HEADER) - len(err_prefix)))
                continue
            ev = rec.evidence or {}
            df = ev.get("delist_filing") or {}
            ak = ev.get("anchor_8k") or {}
            dr = ev.get("dereg_filing") or {}
            if extractor is not None and rec.bucket == CrspBucket.MERGER:
                try:
                    # No last_close available in this classification pass, so
                    # PayoutExtractor's relative sanity band (0.05x-20x of
                    # last_close) is inert here and only the absolute band
                    # [0.01, 10000] applies. The price-aware relative band is
                    # exercised by the downstream BMP path
                    # (scripts/compute_corrected_returns.py), which has
                    # last-trade closes.
                    payout_by_ticker[rec.ticker] = extractor.extract(rec)
                except Exception as e:  # extraction must never abort the run
                    if not args.quiet:
                        print(f"[{i:4d}/{len(rows)}] {ticker}: payout ERROR {e}",
                              file=sys.stderr)
            pr = payout_by_ticker.get(rec.ticker)
            writer.writerow([
                rec.ticker,
                rec.cik or "",
                rec.observed_delist_date or "",
                rec.crsp_code if rec.crsp_code is not None else "",
                rec.bucket.value,
                rec.confidence,
                rec.reason,
                df.get("form", ""),
                df.get("filing_date", ""),
                ak.get("items", ""),
                dr.get("form", ""),
                ev.get("name", ""),
                ev.get("resolution_source", ""),
                "" if pr is None or pr.value is None else f"{pr.value:.2f}",
                "" if pr is None else pr.source,
                "" if pr is None else pr.confidence,
            ])
            bucket_counts[rec.bucket.value] = bucket_counts.get(rec.bucket.value, 0) + 1
            fh.flush()
            if not args.quiet and i % 25 == 0:
                elapsed = time.time() - t0
                print(f"[{i:4d}/{len(rows)}] {elapsed:6.1f}s — running totals: "
                      f"{bucket_counts}", file=sys.stderr, flush=True)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. Counts by bucket:")
    for b, c in sorted(bucket_counts.items(), key=lambda x: -x[1]):
        print(f"  {b:22s} {c:4d}")
    print(f"\nWrote {out_path}")

    if extractor is not None:
        payouts_path = Path(args.payouts_output)
        payouts_path.parent.mkdir(parents=True, exist_ok=True)
        with payouts_path.open("w", newline="") as pf:
            pw = csv.writer(pf)
            pw.writerow(["ticker", "payout_per_share", "confidence", "source", "accession"])
            for tkr, pr in sorted(payout_by_ticker.items()):
                pw.writerow([
                    tkr,
                    "" if pr.value is None else f"{pr.value:.2f}",
                    pr.confidence, pr.source, pr.accession,
                ])
        n_hit = sum(1 for pr in payout_by_ticker.values() if pr.value is not None)
        print(f"Wrote {payouts_path}: {n_hit}/{len(payout_by_ticker)} merger payouts extracted")
    return 0


if __name__ == "__main__":
    sys.exit(main())

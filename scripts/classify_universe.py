"""Build the security master and the delisting table from caller observations.

Reads:  an observations CSV (ticker, as_of[, name, cusip, cik, sec_id])
Writes: output/securities.csv, ticker_history.csv, cusip_history.csv,
        delistings.csv, payouts.csv, review.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.edgar import EdgarBlocked
from delist_detection.observations import ObservationIndex, load_observations
from delist_detection.openfigi import OpenFigiBlocked
from delist_detection.payout_gate import DEFAULT_TOL
from delist_detection.pipeline import Overrides, default_clients, run
from delist_detection.reconstruction import load_float_overrides, load_merger_terms_overrides

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
    "CONE":  1553023,   # CyrusOne — KKR 2022
    "DATA":  1303652,   # Tableau Software — Salesforce 2019
    "MNI":   1056087,   # McClatchy — Ch.11 2020
    "CNW":   23675,     # Con-way (Conway) — XPO 2015
    "GAS":   1004155,   # AGL Resources — Southern Co Gas 2016
    "SPW":   88205,     # SPX Corp — refiled/restructured 2015
    "BFA":   14693,     # Brown-Forman Class A (share class delist; co continues)
    "CWENA": 1567683,   # Clearway Energy Class A (share class change)
    "IMCL":  1520047,   # ImmunoClin Corp (recycled ticker; SEC revoked 2019)
    # Tickers missing from AV — explicit knowledge of the rename
    "XTO":   868809,    # XTO Energy — ExxonMobil 2010; subsidiary dereg 2013
    "AH":    1472595,   # Accretive Health → R1 RCM (rename + ticker move)
    "KWK":   1060990,   # Quicksilver Resources Inc — Ch.11 2015 (1283699 is T-Mobile US)
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
    "ONNN":  1097864,   # ON Semiconductor — ticker change ONNN → ON 2015, not a delisting
    "UPL":   1022646,   # Ultra Petroleum — Nasdaq → OTC Aug 2019, kept filing until Form 15 in 2020
    "ICPT":  1270073,   # Intercept — Alfasigma 2023 (Form 25 2023-11-08); vendor end date 2026-06-26 is a frozen tail
    "HLX":   866829,    # Helix Energy — merged 2026, now Hornbeck Offshore (HOS); pinned so resolution survives HLX leaving company_tickers.json
    "SBNY":  1288784,   # Signature Bank — failed Mar 2023; EDGAR holds only 13D/13G and Form D, no 10-K/8-K/Form 25, so it still classifies unknown
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--observations", required=True, help="CSV ticker,as_of[,name,cusip,cik,sec_id]")
    p.add_argument("--output-dir", default=str(ROOT / "output"))
    p.add_argument("--cache-dir", default=str(ROOT / "cache"))
    p.add_argument("--limit", type=int, default=None, help="process only the first N ticker eras")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--no-extract-payouts", action="store_true",
                   help="Skip per-share payout extraction (faster dev re-run)")
    p.add_argument("--no-midas", action="store_true", help="skip SEC MIDAS last-trade confirmation")
    p.add_argument("--no-halts", action="store_true", help="skip the Nasdaq halt feed")
    p.add_argument("--last-trade-closes", help="CSV sec_id,last_trade_close[,delist_date]")
    p.add_argument("--merger-terms", help="CSV sec_id,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker[,delist_date]")
    p.add_argument("--recoveries", help="CSV sec_id,recovery_ratio[,delist_date]")
    p.add_argument("--extract-merger-terms-llm", action="store_true",
                   help="Use the LLM extractor to read cash+stock merger terms from EDGAR filings; "
                        "acquirer_price is joined from the SEC fails-to-deliver panel and a sanity gate "
                        "(|terminal/last_close-1| <= --merger-terms-sanity-tol) rejects mis-resolutions.")
    p.add_argument("--llm-model", default=None, help="Override the chat model (default $CHAT_MODEL from .env).")
    p.add_argument("--merger-terms-sanity-tol", type=float, default=DEFAULT_TOL,
                   help="Max |payout/last_close - 1| for any merger payout (regex cash, LLM cash, election leg, "
                        "or LLM cash+stock terminal value) to be emitted (default %(default)s). Completed deals "
                        "reconcile tightly.")
    return p


def main() -> int:
    p = build_parser()
    args = p.parse_args()

    overrides = Overrides(
        last_trade_closes=load_float_overrides(args.last_trade_closes, "last_trade_close") if args.last_trade_closes else {},
        merger_terms=load_merger_terms_overrides(args.merger_terms) if args.merger_terms else {},
        recoveries=load_float_overrides(args.recoveries, "recovery_ratio") if args.recoveries else {},
    )
    index = ObservationIndex(load_observations(args.observations))
    clients = default_clients(
        index, cache_dir=Path(args.cache_dir), rename_map=KNOWN_RENAMES, manual_overrides=MANUAL_OVERRIDES,
        extract_payouts=not args.no_extract_payouts, extract_llm=args.extract_merger_terms_llm,
        llm_model=args.llm_model, use_midas=not args.no_midas, use_halts=not args.no_halts,
    )
    log = (lambda *a: None) if args.quiet else None
    summary = run(index, clients, overrides, out_dir=Path(args.output_dir), tol=args.merger_terms_sanity_tol,
                  limit=args.limit, **({"log": log} if log else {}))
    print("Rows written:", summary.counts)
    print("Delistings by bucket:", summary.buckets)
    print("FIGI sources:", summary.figi_sources)
    print("Review flags:", summary.review_flags)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EdgarBlocked, OpenFigiBlocked) as e:
        print(f"ABORTED: {e}", file=sys.stderr)
        sys.exit(2)

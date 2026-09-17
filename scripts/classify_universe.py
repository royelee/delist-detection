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
DEFAULT_DLRET_OUTPUT = ROOT / "output" / "dlret.csv"

from delist_detection import EdgarClient, TickerResolver, DelistClassifier
from delist_detection.edgar import EdgarBlocked
from delist_detection.crsp_codes import CrspBucket
from delist_detection.av_listing import AvListingLoader
from delist_detection.names import MemberNames
from delist_detection.payout_extractor import PayoutExtractor, PayoutResult
from delist_detection.payout_gate import DEFAULT_TOL, gate_payouts
from delist_detection.reconstruction import (
    build_dlret_table, write_dlret_csv, load_merger_terms_csv, load_float_map_csv,
    _lookup, enriched_to_row,
)


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
    "ONNN":  1097864,   # ON Semiconductor — ticker change ONNN → ON 2015, not a delisting
    "UPL":   1022646,   # Ultra Petroleum — Nasdaq → OTC Aug 2019, kept filing until Form 15 in 2020
    "ICPT":  1270073,   # Intercept — Alfasigma 2023 (Form 25 2023-11-08); vendor end date 2026-06-26 is a frozen tail
    "HLX":   866829,    # Helix Energy — merged 2026, now Hornbeck Offshore (HOS); pinned so resolution survives HLX leaving company_tickers.json
    "SBNY":  1288784,   # Signature Bank — failed Mar 2023; EDGAR holds only 13D/13G and Form D, no 10-K/8-K/Form 25, so it still classifies unknown
}

# Deal-era acquirer ticker -> the symbol the raw Tiingo panel files its price
# history under. The panel is a 2026 snapshot keyed by each issuer's CURRENT
# ticker, so an acquirer that was later renamed/merged won't resolve a price
# file under its deal-era symbol though the history is present under the new one.
# Each entry verified to return a deal-era nominal close (e.g. rtx.csv carries
# UTC's 2018-11-26 close of $127.98). The sanity gate still backstops every use.
ACQUIRER_RENAMES: dict[str, str] = {
    "UTX":  "RTX",   # United Technologies -> Raytheon Technologies -> RTX
    "ECA":  "OVV",   # Encana -> Ovintiv
    "COG":  "CTRA",  # Cabot Oil & Gas -> Coterra
    "HRS":  "LHX",   # Harris -> L3Harris
    "Q":    "IQV",   # Quintiles -> IQVIA
    "SXCI": "CTRX",  # SXC Health -> Catamaran
    "SPF":  "CAA",   # Standard Pacific -> CalAtlantic
    "ESV":  "VAL",   # Ensco -> Valaris
}


def _acquirer_price(prices, ticker: str | None, date: str | None) -> float | None:
    """The acquirer's nominal close on `date`: the deal-era ticker first, then its
    current-symbol rename. None without a price panel or an acquirer ticker."""
    acq = (ticker or "").strip()
    if prices is None or not acq:
        return None
    price = prices.close_on(acq, date)
    if price is None and acq.upper() in ACQUIRER_RENAMES:
        price = prices.close_on(ACQUIRER_RENAMES[acq.upper()], date)
    return price


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
    p.add_argument("--dlret-output", default=str(DEFAULT_DLRET_OUTPUT),
                   help="primary DLRET reconstruction table")
    p.add_argument("--last-trade-closes", default=None,
                   help="CSV: ticker,last_trade_close (merger DLRET needs this)")
    p.add_argument("--merger-terms", default=None,
                   help="CSV: ticker,cash_per_share,stock_ratio,acquirer_price,acquirer_ticker")
    p.add_argument("--recoveries", default=None,
                   help="CSV: ticker,recovery_ratio")
    p.add_argument("--extract-merger-terms-llm", action="store_true",
                   help="Use the LLM extractor to read cash+stock merger terms from "
                        "EDGAR filings; acquirer_price + target last_trade_close are "
                        "joined from the raw Tiingo price panel and a sanity gate "
                        "(|terminal/last_close-1| <= tol) rejects mis-resolutions.")
    p.add_argument("--raw-tiingo-dir", default=None,
                   help="Directory of raw Tiingo per-ticker CSVs (nominal close). "
                        "Defaults to $RAW_TIINGO_DIR or the qlib_practice path. "
                        "Used for acquirer_price and to fill missing last_trade_close.")
    p.add_argument("--merger-terms-sanity-tol", type=float, default=DEFAULT_TOL,
                   help="Max |payout/last_close - 1| for any merger payout (regex cash, "
                        "LLM cash, election leg, or LLM cash+stock terminal value) to be "
                        "emitted (default %(default)s). Completed deals reconcile tightly.")
    p.add_argument("--llm-model", default=None,
                   help="Override the chat model (default $CHAT_MODEL from .env).")
    p.add_argument("--names", default=None,
                   help="CSV ticker,as_of,name: index-member names (qlib_practice exports them "
                        "from iShares/Wikipedia holdings)")
    args = p.parse_args()

    edgar = EdgarClient(cache_dir=ROOT / "cache" / "edgar")
    av = AvListingLoader(AV_LISTING_CSV, active_csv_path=AV_ACTIVE_CSV)
    resolver = TickerResolver(
        edgar,
        rename_map=KNOWN_RENAMES,
        manual_overrides={k: v for k, v in MANUAL_OVERRIDES.items() if v > 0},
        cache_path=ROOT / "cache" / "ticker_resolution.json",
        name_lookup=av.name,
        member_names=MemberNames.from_csv(args.names) if args.names else None,
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

    # Load and validate override CSVs BEFORE the network loop so a malformed
    # file raises in <1s instead of after the ~2-min classification pass.
    # Override CSVs accept an optional ``observed_delist_date`` column: when a
    # row's date is non-blank it is keyed by (ticker, date) for per-event
    # precision; a blank/absent date applies to all events of that ticker.
    # Exchange and payout maps are derived per delisting event internally, so
    # recycled tickers (e.g. ALTR = Altera 2015 + Altair 2025) are handled
    # correctly without any special casing in the override files.
    last_trades = load_float_map_csv(args.last_trade_closes, "last_trade_close") if args.last_trade_closes else {}
    recoveries = load_float_map_csv(args.recoveries, "recovery_ratio") if args.recoveries else {}
    merger_terms = load_merger_terms_csv(args.merger_terms) if args.merger_terms else {}

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    bucket_counts: dict[str, int] = {}
    extractor = None if args.no_extract_payouts else PayoutExtractor(edgar)
    payout_by_ticker: dict[tuple[str, str | None], PayoutResult] = {}
    all_records: list = []

    # Optional LLM merger-terms extractor (cash + stock leg from EDGAR filings).
    # The acquirer's price and the target's last_trade_close are NOT parsed from
    # the filing — they're joined from the raw Tiingo panel below, then a sanity
    # gate rejects any term whose terminal value doesn't reconcile with the last
    # close (i.e. a mis-resolved acquirer ticker). Constructed up front so a
    # missing OPENAI_API_KEY / unreadable price dir fails fast, before the loop.
    llm_ext = None
    prices = None
    llm_terms_raw: dict = {}
    if args.extract_merger_terms_llm:
        from delist_detection.llm_client import default_llm_client
        from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor
        from delist_detection.raw_tiingo import RawTiingoPrices
        prices = RawTiingoPrices(args.raw_tiingo_dir)
        llm_ext = LLMMergerTermsExtractor(
            edgar, default_llm_client(args.llm_model), cache_dir=ROOT / "cache" / "llm",
        )

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
            except EdgarBlocked:
                raise
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
            if rec is not None:
                all_records.append(rec)
            ev = rec.evidence or {}
            df = ev.get("delist_filing") or {}
            ak = ev.get("anchor_8k") or {}
            dr = ev.get("dereg_filing") or {}
            if extractor is not None and rec.bucket == CrspBucket.MERGER:
                try:
                    payout_by_ticker[(rec.ticker, rec.observed_delist_date)] = extractor.extract(
                        rec, last_close=_lookup(last_trades, rec.ticker.upper(), rec.observed_delist_date))
                except EdgarBlocked:
                    raise
                except Exception as e:  # extraction must never abort the run
                    if not args.quiet:
                        print(f"[{i:4d}/{len(rows)}] {ticker}: payout ERROR {e}",
                              file=sys.stderr)
            if llm_ext is not None and rec.bucket == CrspBucket.MERGER:
                try:
                    terms = llm_ext.extract(rec)
                    if terms is not None:
                        llm_terms_raw[(rec.ticker, rec.observed_delist_date)] = terms
                except EdgarBlocked:
                    raise
                except Exception as e:  # LLM extraction must never abort the run
                    if not args.quiet:
                        print(f"[{i:4d}/{len(rows)}] {ticker}: llm-terms ERROR {e}",
                              file=sys.stderr)
            pr = payout_by_ticker.get((rec.ticker, rec.observed_delist_date))
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
                "" if pr is None or pr.value is None else f"{pr.value:.10g}",
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

    # --- PRIMARY OUTPUT: DLRET reconstruction table ---
    exchanges = {
        (r.ticker.upper(), r.observed_delist_date): (av.exchange(r.ticker, observed_date=r.observed_delist_date) or "")
        for r in all_records
    }
    # last_trade_close and acquirer_price are joined from the raw Tiingo panel,
    # never parsed from filings.
    if prices is not None:
        # Fill last_trade_close from the raw panel for any record the CSV did not
        # already cover, so BOTH cash-only payouts and LLM cash+stock terms have
        # the denominator DLRET needs. CSV-provided closes win (skipped here).
        for r in all_records:
            if _lookup(last_trades, r.ticker.upper(), r.observed_delist_date) is None:
                c = prices.close_on(r.ticker, r.observed_delist_date)
                if c is not None:
                    last_trades[(r.ticker.upper(), r.observed_delist_date)] = c

    # Every merger payout must reconcile with the last close before it becomes a
    # return; an explicit --merger-terms CSV row always wins over the LLM.
    # gated.flags (key -> flags) feeds the review_flags column.
    regex = {(t.upper(), d): pr for (t, d), pr in payout_by_ticker.items() if pr.value is not None}
    terms_by_key = {(t.upper(), d): terms for (t, d), terms in llm_terms_raw.items()}
    gated = gate_payouts(
        [(r.ticker.upper(), r.observed_delist_date) for r in all_records if r.bucket == CrspBucket.MERGER],
        {k: pr.value for k, pr in regex.items()},
        {k: pr.source for k, pr in regex.items()},
        {k: pr.confidence for k, pr in regex.items()},
        terms_by_key,
        last_trades,
        merger_terms,
        lambda ticker, date: _acquirer_price(prices, ticker, date),
        args.merger_terms_sanity_tol,
    )
    print(f"\nPayout gate: {gated.gate_failed} merger rows unsettled: flagged payout_gate_failed, "
          f"with no gated payout and no merged terms (rows the LLM cash or full terms settled "
          f"are not counted)")
    if llm_ext is not None:
        print(f"LLM merger terms: {gated.emitted} cash+stock/stock-only emitted "
              f"({len(llm_terms_raw)} mergers extracted); dropped {gated.dropped}; "
              f"plus {gated.llm_cash} cash payouts taken from LLM terms")

    if extractor is not None:
        # The gated values, so a consumer never reads a payout the gate dropped;
        # delist_classifications.csv keeps the raw extraction.
        payouts_path = Path(args.payouts_output)
        payouts_path.parent.mkdir(parents=True, exist_ok=True)
        with payouts_path.open("w", newline="") as pf:
            pw = csv.writer(pf)
            pw.writerow(["ticker", "observed_delist_date", "payout_per_share", "confidence", "source", "accession"])
            for (tkr, date), pr in sorted(
                payout_by_ticker.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
            ):
                k = (tkr.upper(), date)
                value = gated.payouts.get(k)
                source = gated.sources.get(k, "none")
                if source.startswith("llm"):
                    accession = terms_by_key[k].source.partition(":")[2]   # "{form}:{accession}"
                else:
                    accession = pr.accession if value is not None else ""
                pw.writerow([
                    tkr,
                    date or "",
                    "" if value is None else f"{value:.10g}",
                    gated.confidences.get(k, "none"), source, accession,
                ])
        n_hit = sum(1 for (t, d) in payout_by_ticker if (t.upper(), d) in gated.payouts)
        print(f"Wrote {payouts_path}: {n_hit}/{len(payout_by_ticker)} merger payouts after the last-close gate")

    table = build_dlret_table(
        all_records,
        last_trade_closes=last_trades,
        payouts=gated.payouts,
        exchanges=exchanges,
        merger_terms=gated.merged_terms,
        recovery_ratios=recoveries,
        payout_sources=gated.sources,
        payout_confidences=gated.confidences,
        payout_flags=gated.flags,
    )
    write_dlret_csv(table, args.dlret_output)
    print(f"Wrote {args.dlret_output}: {len(table)} DLRET rows (PRIMARY OUTPUT)")

    # --- review.csv: every row the rules could not settle on their own ---
    records_by_key = {(r.ticker.upper(), r.observed_delist_date): r for r in all_records}
    review_cols = ["ticker", "observed_delist_date", "bucket", "dlret", "review_flags",
                   "reason", "cik", "anchor_8k"]
    review_rows = []
    flag_counts: dict[str, int] = {}
    for e in table:
        if not e.review_flags:
            continue
        row = enriched_to_row(e)
        rec = records_by_key.get((e.ticker.upper(), e.observed_delist_date))
        anchor_8k = (((rec.evidence or {}).get("anchor_8k") or {}).get("items", "")
                     if rec is not None else "")
        review_rows.append({
            "ticker": row["ticker"],
            "observed_delist_date": row["observed_delist_date"],
            "bucket": row["bucket"],
            "dlret": row["dlret"],
            "review_flags": row["review_flags"],
            "reason": row["reason"],
            "cik": "" if rec is None or rec.cik is None else rec.cik,
            "anchor_8k": anchor_8k,
        })
        for f in e.review_flags:
            name = f.split(":", 1)[0]
            flag_counts[name] = flag_counts.get(name, 0) + 1

    review_path = Path(args.dlret_output).with_name("review.csv")
    review_path.parent.mkdir(parents=True, exist_ok=True)
    with review_path.open("w", newline="") as rf:
        rw = csv.DictWriter(rf, fieldnames=review_cols)
        rw.writeheader()
        rw.writerows(review_rows)
    print(f"Wrote {review_path}: {len(review_rows)} rows need review")
    for name, count in sorted(flag_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {name:28s} {count:4d}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except EdgarBlocked as e:
        print(f"ABORTED: {e}", file=sys.stderr)
        sys.exit(2)

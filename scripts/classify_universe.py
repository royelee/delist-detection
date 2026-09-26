"""Build the security master and the delisting table from caller observations.

Reads:  an observations CSV (ticker, as_of[, name, cusip, cik, sec_id]), and
        data/review_decisions.csv (accepted review flags; default path, so a
        missing file there means no decisions)
Writes: output/securities.csv, ticker_history.csv, cusip_history.csv,
        delistings.csv, payouts.csv, review.csv, review_summary.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from delist_detection.edgar import EdgarSetupError, require_user_agent
from delist_detection.sec_limiter import use_machine_wide_limit
from delist_detection.fatal import FATAL
from delist_detection.observations import ObservationError, ObservationIndex, load_observations
from delist_detection.openfigi import OpenFigiUnavailable
from delist_detection.payout_gate import DEFAULT_TOL
from delist_detection.pipeline import Overrides, default_clients, run
from delist_detection.reconstruction import OverrideFileError, load_float_overrides, load_merger_terms_overrides
from delist_detection.review_triage import Decision, ReviewDecisionError, load_decisions

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

DEFAULT_SEC_WORKERS = 4     # threads prefetching SEC data; each stage itself stays sequential
MAX_SEC_WORKERS = 8         # one process's ceiling: all threads share one 8 requests/s limit
DEFAULT_REVIEW_DECISIONS = str(ROOT / "data" / "review_decisions.csv")


EXIT_CODES_EPILOG = """\
Exit codes:
  0  success, no review-row errors
  1  unexpected crash: an uncaught exception (Python's own exit code, with its traceback)
  2  aborted, no outputs written: SEC or OpenFIGI refused the request (EdgarBlocked/
     OpenFigiBlocked); or a bad input file, named with its line on one stderr line (an
     --observations, --last-trade-closes, --merger-terms or --recoveries file that is
     missing or malformed, override rows that match no delisting of the run, a
     --review-decisions file that is missing when given explicitly or that fails to load);
     or a start-up check failed (no EDGAR_USER_AGENT, an unusable SEC rate-lock file, a
     bad argument such as --sec-workers or --as-of)
  3  completed, but review.csv has one or more `error` rows, or `resolution_degraded`
     rows (an answer rested on a failed SEC or Nasdaq halt-feed request or a stale copy;
     run again once they answer). Outputs are still written; see the stderr banner for the counts
  4  aborted: OpenFIGI unavailable after its retries (timeouts, connection errors or 5xx
     answers, OpenFigiUnavailable); no outputs written, the previous ones are kept whole; rerun later
"""

EXIT_REFUSED = 2          # SEC or OpenFIGI refused a request
EXIT_BAD_INPUT = 2        # a bad input file
EXIT_OPENFIGI_DOWN = 4    # OpenFIGI unavailable after its retries

# The exceptions that name a bad input file (exit 2): each message is one line
# naming the file and line.
BAD_INPUT = (ObservationError, OverrideFileError, ReviewDecisionError)


def run_date(text: str) -> date:
    """--as-of's value: a YYYY-MM-DD date."""
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}") from None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(epilog=EXIT_CODES_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    p.add_argument("--review-decisions", default=None,
                   help="CSV of accepted review flags: sec_id,delist_date,ticker,flag,decision,note "
                        f"(default {DEFAULT_REVIEW_DECISIONS}; missing at the default path means no decisions, "
                        "missing at an explicitly given path -- even one that happens to spell out the default "
                        "-- is an error)")
    p.add_argument("--extract-merger-terms-llm", action="store_true",
                   help="Use the LLM extractor to read cash+stock merger terms from EDGAR filings; "
                        "acquirer_price is joined from the SEC fails-to-deliver panel and a sanity gate "
                        "(|terminal/last_close-1| <= --merger-terms-sanity-tol) rejects mis-resolutions.")
    p.add_argument("--llm-model", default=None, help="Override the chat model (default $CHAT_MODEL from .env).")
    p.add_argument("--merger-terms-sanity-tol", type=float, default=DEFAULT_TOL,
                   help="Max |payout/last_close - 1| for any merger payout (regex cash, LLM cash, election leg, "
                        "or LLM cash+stock terminal value) to be emitted (default %(default)s). Completed deals "
                        "reconcile tightly.")
    p.add_argument("--sec-workers", type=int, default=DEFAULT_SEC_WORKERS,
                   help=f"Threads that fetch SEC data ahead of each stage (default %(default)s, at most "
                        f"{MAX_SEC_WORKERS}; 1 = one request at a time). Every SEC request from this process, and "
                        "from every other SEC client on this machine through the lock file "
                        "$DELIST_DETECTION_SEC_RATE_LOCK (default ~/.cache/delist_detection/sec_rate.lock), "
                        "shares one 8 requests/s limit, so more threads only fill that limit sooner.")
    p.add_argument("--as-of", type=run_date, default=None, metavar="YYYY-MM-DD",
                   help="The run date every freshness rule reads (default: today). Pin it to an earlier run's "
                        "date (run_manifest.json's as_of) to reproduce that run's tables from the same caches.")
    return p


def bad_input(problem: object) -> int:
    """Report a bad input file on one stderr line; its exit code."""
    print(f"ABORTED: bad input file; no outputs written: {problem}", file=sys.stderr)
    return EXIT_BAD_INPUT


def read_inputs(args: argparse.Namespace) -> tuple[Overrides, list[Decision], ObservationIndex]:
    """Every input file, read before any client is built: the override files, the
    review decisions and the observations. A malformed file raises one of
    BAD_INPUT; a missing one, OSError."""
    overrides = Overrides(
        last_trade_closes=load_float_overrides(args.last_trade_closes, "last_trade_close") if args.last_trade_closes else {},
        merger_terms=load_merger_terms_overrides(args.merger_terms) if args.merger_terms else {},
        recoveries=load_float_overrides(args.recoveries, "recovery_ratio") if args.recoveries else {},
    )
    # None (the argparse default) means the caller didn't pass --review-decisions
    # at all: a missing file at the default path is fine. Once the flag is given
    # explicitly -- even spelling out the same path as the default -- a missing
    # file is an error, so a typo'd path is never silently read as "no decisions".
    if args.review_decisions is not None:
        review_decisions = load_decisions(args.review_decisions)
    else:
        try:
            review_decisions = load_decisions(DEFAULT_REVIEW_DECISIONS)
        except FileNotFoundError:
            review_decisions = []          # no decisions file at the default path: nothing accepted yet
    return overrides, review_decisions, ObservationIndex(load_observations(args.observations))


def main() -> int:
    p = build_parser()
    args = p.parse_args()
    if not 1 <= args.sec_workers <= MAX_SEC_WORKERS:
        p.error(f"--sec-workers must be between 1 and {MAX_SEC_WORKERS}")
    try:
        require_user_agent()           # SEC 403s the fallback: stop before the first request
        use_machine_wide_limit()       # every SEC client on this machine shares the 8 requests/s
    except (EdgarSetupError, OSError) as exc:
        p.error(str(exc))

    try:
        overrides, review_decisions, index = read_inputs(args)
    except BAD_INPUT as exc:
        return bad_input(exc)
    except OSError as exc:                 # a missing or unreadable input file
        return bad_input(f"{exc.filename}: {exc.strerror or exc}")
    clients = default_clients(
        index, cache_dir=Path(args.cache_dir), rename_map=KNOWN_RENAMES, manual_overrides=MANUAL_OVERRIDES,
        extract_payouts=not args.no_extract_payouts, extract_llm=args.extract_merger_terms_llm,
        llm_model=args.llm_model, use_midas=not args.no_midas, use_halts=not args.no_halts,
        as_of=args.as_of or date.today(),
    )
    log = (lambda *a: None) if args.quiet else None
    summary = run(index, clients, overrides, out_dir=Path(args.output_dir), tol=args.merger_terms_sanity_tol,
                  limit=args.limit, sec_workers=args.sec_workers, review_decisions=review_decisions,
                  **({"log": log} if log else {}))
    print("Rows written:", summary.counts)
    print("Delistings by bucket:", summary.buckets)
    print("FIGI sources:", summary.figi_sources)
    print("Review flags:", summary.review_flags)
    rc = summary.review_counts
    print(f"Review: {rc.get('fix', 0)} fix, {rc.get('check', 0)} check "
          f"({rc.get('info_hidden', 0)} info-only rows hidden, {rc.get('accepted', 0)} accepted, "
          f"{rc.get('unmatched_decisions', 0)} unmatched decisions)")
    error_count = summary.review_flags.get("error", 0)
    degraded_count = summary.review_flags.get("resolution_degraded", 0)
    if error_count:
        print(f"WARNING: {error_count} review row(s) flagged 'error' -- outputs were still written; "
              "see review.csv for the affected (sec_id, delist_date) rows.", file=sys.stderr)
    if degraded_count:
        print(f"WARNING: {degraded_count} review row(s) flagged 'resolution_degraded' -- an answer rested on "
              "a failed SEC or Nasdaq halt-feed request or a stale copy; outputs were still written, run again "
              "once they answer.",
              file=sys.stderr)
    return 3 if error_count or degraded_count else 0


def entry() -> int:
    """`main()` with an abort turned into its exit code (see EXIT_CODES_EPILOG): a
    refusal, or override rows that match no delisting (found mid-run, before
    anything is written), exit 2; an OpenFIGI outage exits 4. Every abort leaves
    every output table as the previous run wrote it. Any other exception is an
    unexpected crash: it propagates, and Python exits 1."""
    try:
        return main()
    except BAD_INPUT as e:
        return bad_input(e)
    except FATAL as e:                  # fatal.FATAL: every exception that stops a run
        if isinstance(e, OpenFigiUnavailable):
            print(f"ABORTED: OpenFIGI unavailable after retries; no outputs written; rerun later ({e})",
                  file=sys.stderr)
            return EXIT_OPENFIGI_DOWN
        print(f"ABORTED: {e}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(entry())

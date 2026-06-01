"""Dev harness: calibrate the LLM merger-terms extractor against labeled deals.

NOT a CI test (it makes live SEC + OpenAI calls). It runs
``LLMMergerTermsExtractor`` over a small hand-labeled ground-truth set of real
cash+stock and all-stock mergers and prints extracted-vs-expected per field, so
the prompt in ``llm_merger_extractor.py`` can be iterated until it clears the set.

Usage:
    python scripts/eval_merger_extractor.py --n 1          # first case (AET) only
    python scripts/eval_merger_extractor.py --n 4          # first 4
    python scripts/eval_merger_extractor.py                # all 10
    python scripts/eval_merger_extractor.py --tickers AET,AGN

The EDGAR text cache (cache/edgar) and the LLM cache (cache/llm) make re-runs
free, so iterating the prompt (bump PROMPT_VERSION on edit) is cheap.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarClient
from delist_detection.llm_client import default_llm_client
from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor

ROOT = Path(__file__).resolve().parents[1]

# Labeled ground truth — the 10 deals verified in the prototype run.
# (cash is None for all-stock deals.)
GROUND_TRUTH = [
    # ticker, cik,       date,         cash,    ratio,   acquirer
    ("AET",  1122304, "2018-11-28", 145.00, 0.8378, "CVS"),
    ("AGN",  1578845, "2020-05-08", 120.30, 0.8660, "ABBV"),
    ("FDO",    34408, "2015-07-13",  59.60, 0.2484, "DLTR"),
    ("WORK", 1764925, "2021-07-27",  26.79, 0.0776, "CRM"),
    ("CIVI", 1509589, "2026-01-29",   None, 1.4500, "SM"),
    ("MRC",  1439095, "2025-11-05",   None, 0.9489, "DNOW"),
    ("SCG",   754737, "2018-12-31",   None, 0.6690, "D"),
    ("NBL",    72207, "2020-10-06",   None, 0.1191, "CVX"),
    ("SIRO", 1014507, "2016-03-08",   None, 1.8142, "XRAY"),
    ("WPX",  1518832, "2021-01-14",   None, 0.5165, "DVN"),
]


def _rec(ticker: str, cik: int, date: str) -> DelistRecord:
    return DelistRecord(
        ticker=ticker, cik=cik, observed_delist_date=date,
        crsp_code=231, bucket=CrspBucket.MERGER, confidence="high",
        reason="eval", evidence={},
    )


def _cash_match(got: float | None, exp: float | None) -> bool:
    if exp is None:
        return got is None or abs(got) < 0.01      # all-stock: null or ~0 both OK
    return got is not None and abs(got - exp) < 0.02


def _ratio_match(got: float | None, exp: float | None) -> bool:
    if exp is None:
        return got is None
    return got is not None and abs(got - exp) < 0.001


def _acq_match(got: str | None, exp: str | None) -> bool:
    if exp is None:
        return True
    return bool(got) and got.strip().upper() == exp.upper()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=None, help="run only the first N labeled cases")
    p.add_argument("--tickers", type=str, default=None, help="comma-separated subset")
    args = p.parse_args(argv)

    cases = GROUND_TRUTH
    if args.tickers:
        want = {t.strip().upper() for t in args.tickers.split(",")}
        cases = [c for c in cases if c[0] in want]
    elif args.n is not None:
        cases = cases[: args.n]

    edgar = EdgarClient(cache_dir=ROOT / "cache" / "edgar")
    llm = default_llm_client()
    ext = LLMMergerTermsExtractor(edgar, llm, cache_dir=ROOT / "cache" / "llm")

    n_pass = 0
    for ticker, cik, date, exp_cash, exp_ratio, exp_acq in cases:
        terms = ext.extract(_rec(ticker, cik, date))
        if terms is None:
            print(f"\n{ticker:5s} {date}  ->  MISS (extractor returned None)")
            print(f"      expected: cash={exp_cash} ratio={exp_ratio} acq={exp_acq}")
            continue

        cm = _cash_match(terms.cash_per_share, exp_cash)
        rm = _ratio_match(terms.stock_ratio, exp_ratio)
        am = _acq_match(terms.acquirer_ticker, exp_acq)
        ok = cm and rm and am
        n_pass += int(ok)

        mark = "PASS" if ok else "FAIL"
        print(f"\n{ticker:5s} {date}  ->  {mark}   [{terms.deal_type}, conf={terms.confidence}, {terms.source}]")
        print(f"      cash : {terms.cash_per_share!s:>10}  exp {exp_cash!s:>8}  {'ok' if cm else 'X'}")
        print(f"      ratio: {terms.stock_ratio!s:>10}  exp {exp_ratio!s:>8}  {'ok' if rm else 'X'}")
        print(f"      acq  : {str(terms.acquirer_ticker):>10}  exp {str(exp_acq):>8}  {'ok' if am else 'X'}"
              f"   (name={terms.acquirer_name})")
        if not ok:
            print(f"      quote: {terms.quote[:160]}")

    print(f"\n==== {n_pass}/{len(cases)} passed ====")
    return 0 if n_pass == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())

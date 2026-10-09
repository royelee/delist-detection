"""Dev harness: calibrate the LLM merger-terms extractor against labeled deals.

NOT a CI test (it makes live SEC + OpenAI calls). It runs
``LLMMergerTermsExtractor`` over a small hand-labeled ground-truth set of real
cash+stock and all-stock mergers and prints extracted-vs-expected per field, so
the prompt in ``llm_merger_extractor.py`` can be iterated until it clears the set.

Two sets:
- the 10 deals verified in the prototype run (cash, ratio, acquirer; and USD for a cash leg, ruling R5);
- with ``--truth``, the diagnosis truth set's terms cases (sub-plan 5f: currency, the election package R4, the
  basket legs R3, a dollar-valued stock leg, the latest completion document), read from
  data/diagnosis_truth.csv and its legs with each case's delisting from output/ (cik, delist date, the security's
  name, which the prompt names).

Usage:
    python scripts/eval_merger_extractor.py --n 1          # first case (AET) only
    python scripts/eval_merger_extractor.py --n 4          # first 4
    python scripts/eval_merger_extractor.py                # all 10
    python scripts/eval_merger_extractor.py --tickers AET,AGN
    python scripts/eval_merger_extractor.py --truth        # the 10, then the truth cases of TRUTH_CASES
    python scripts/eval_merger_extractor.py --truth --tickers JCI,RKT

The EDGAR text cache (cache/edgar) and the LLM cache (cache/llm) make re-runs
free, so iterating the prompt (bump PROMPT_VERSION on edit) is cheap.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from delist_detection.outputs.reconstruction import DelistRecord
from delist_detection.vocabulary.crsp_codes import CrspBucket
from delist_detection.sources.edgar import EdgarClient
from delist_detection.sources.llm_client import default_llm_client
from delist_detection.terms.llm_merger_extractor import LLMMergerTermsExtractor
from delist_detection.measurement.truth_set import TruthSet, configured

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

# sub-plan 5f's calibration cases from the diagnosis truth set, by case_id: each rule of the v3 prompt and the
# election packages that already pass (their guards)
TRUTH_CASES = [
    "BBG000BB2N27_2014-12-25",   # THI: C$65.50 + 0.8025 QSR (R5: CAD)
    "BBG000BMDV41_2016-09-16",   # JCI: the default package $5.7293 + 0.8357 (R4)
    "BBG000BPQVR5_2015-07-12",   # RKT: the default package 1 WRK, not the cash electors' (R4)
    "BBG000BTMDX4_2012-04-06",   # SUG: non-electors got 1.0 ETE unit (R4)
    "BBG000H89QJ6_2016-05-28",   # TWC: 0.48908178 New Charter issued, not 0.5409 "equivalent"
    "BBG000BBB3K1_2017-08-04",   # RAI: 0.5260 BAT ADSs, not 1
    "BBG000G61VB6_2007-07-23",   # BOT: the amended 0.375 (an 8-K after the proxy)
    "BBG000BNVNY4_2021-12-12",   # MDP: 16.99 + 42.18 = 59.17 total cash
    "BBG000C11MQ5_2015-06-05",   # PCYC: $152.25 + $109.00 of AbbVie (a dollar-valued leg)
    "BBG006F8QZK4_2024-12-07",   # VSTO: $25.75 + 1 Revelyst (GEAR)
    "BBG00FFJY867_2025-05-17",   # LGFB: 1 LION + 1/15 STRZ (R3 basket)
    "CIK804055-COMMON_2010-10-15",   # CCE 2010: $10 + 1 New CCE (CCE), not KO
    "BBG000BF5RY1_2016-06-10",   # CCE 2016: $14.50 + 1 CCEP (CCE)
    "BBG006XVD9G0_2019-11-30",   # GCI: $6.25 + 0.5427 New Media, renamed Gannett (GCI)
    "BBG000N8Y8W6_2017-07-27",   # AWH: $23.00 + 0.057937 FFH; the $5.00 special dividend is not consideration
    "BBG000QGWY50_2025-06-12",   # BLUE: no default: the all-cash $5.00 alternative (R4)
    "BBG000C496P7_2025-08-17",   # PARA (class B): 1 PSKY (R4), not the class A terms
    "BBG000BK1FD3_2014-12-04",   # FWLT: $16.00 + 0.8998 AMFW
    "BBG000BGFLL5_2013-11-23",   # NYX: 11.27 + 0.1703 ICE (guard: a default package that passes)
    "BBG000PTXBV3_2016-07-22",   # HTS: 5.55 + 0.9894 NLY (guard)
    "BBG0077VS2C0_2026-07-11",   # BLD: the prorated aggregate 249.67 + 10.212 QXO (guard)
    "BBG000BTN971_2012-10-20",   # SUN: 25.00 + 0.5245 ETP (guard)
    "BBG0017T9998_2020-07-30",   # CZR: the no-election default, cash 12.41 (guard)
]


def _rec(ticker: str, cik: int, date: str) -> DelistRecord:
    return DelistRecord(
        ticker=ticker, cik=cik, observed_delist_date=date,
        crsp_code=231, bucket=CrspBucket.MERGER, confidence="high",
        reason="eval", evidence={},
    )


def _num(cell: str) -> float | None:
    return float(cell) if cell not in ("", "*", None) else None


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


def _truth_cases(wanted: set[str] | None) -> list[dict]:
    """The TRUTH_CASES rows with their delisting's cik and date and the security's name."""
    truth_set = TruthSet.open(configured(ROOT))
    truth = {r["case_id"]: r for r in truth_set.rows}
    legs: dict[str, list[dict]] = {}
    for r in truth_set.legs:
        legs.setdefault(r["case_id"], []).append(r)
    names = {r["sec_id"]: r["name"] for r in csv.DictReader(open(ROOT / "output" / "securities.csv"))}
    ends: dict[str, dict] = {}
    for r in csv.DictReader(open(ROOT / "output" / "delistings.csv")):
        if r["bucket"] == "merger":
            ends[r["sec_id"]] = r if r["sec_id"] not in ends or r["delist_date"] > ends[r["sec_id"]]["delist_date"] \
                else ends[r["sec_id"]]
    out = []
    for cid in TRUTH_CASES:
        t = truth[cid]
        e = ends.get(t["sec_id"])
        if e is None or not e["cik"] or (wanted and t["ticker"] not in wanted):
            continue
        # the date the pipeline gives the extractor: the classification anchor (the last trade, else the Form 25 day)
        anchor = e["last_trade_date"] or e["delist_filing_date"] or e["delist_date"]
        out.append({"case": cid, "ticker": e["ticker"], "cik": int(e["cik"]), "date": anchor,
                    "name": names.get(t["sec_id"], ""), "truth": t, "legs": legs.get(cid, [])})
    return out


def _show_truth(ext: LLMMergerTermsExtractor, c: dict) -> bool:
    t = c["truth"]
    terms = ext.extract(_rec(c["ticker"], c["cik"], c["date"]), security_name=c["name"])
    if terms is None:
        print(f"\n{c['ticker']:5s} {c['case']}  ->  MISS")
        return False
    legs = c["legs"]
    exp_cash, exp_cur = _num(t["cash_per_share"]), t["cash_currency"]
    exp_ratio = _num(legs[0]["ratio"]) if t["value_rule"] == "basket" and legs else _num(t["stock_ratio"])
    exp_ticker = (legs[0]["price_ticker"] if t["value_rule"] == "basket" and legs else t["price_ticker"]) or None
    checks = {
        "cash": t["cash_per_share"] == "*" or _cash_match(terms.cash_per_share, exp_cash),
        "currency": t["cash_currency"] in ("*",) or (terms.cash_currency or "") == (exp_cur or ""),
        "ratio": t["stock_ratio"] == "*" or _ratio_match(terms.stock_ratio, exp_ratio),
        "ticker": exp_ticker in (None, "*") or _acq_match(terms.acquirer_ticker, exp_ticker),
        "legs": len(terms.extra_legs) == max(0, len(legs) - 1) if t["value_rule"] == "basket" else
        not terms.extra_legs,
    }
    ok = all(checks.values())
    print(f"\n{c['ticker']:5s} {c['case']}  ->  {'PASS' if ok else 'FAIL'}   [{terms.deal_type}/{terms.package_basis}, "
          f"conf={terms.confidence}, {terms.source}]")
    print(f"      cash : {terms.cash_per_share!s:>10} {terms.cash_currency or '-':4s} exp {t['cash_per_share'] or '-':>8} "
          f"{t['cash_currency'] or '-':4s} {'ok' if checks['cash'] and checks['currency'] else 'X'}")
    print(f"      ratio: {terms.stock_ratio!s:>10} value {terms.stock_value!s:>8}  exp {exp_ratio!s:>8}  "
          f"{'ok' if checks['ratio'] else 'X'}")
    print(f"      acq  : {str(terms.acquirer_ticker):>10} ({terms.acquirer_name}, class {terms.acquirer_share_class or '-'})"
          f"  exp {exp_ticker}  {'ok' if checks['ticker'] else 'X'}")
    if terms.extra_legs or legs:
        print(f"      legs : {[(l.ratio, l.ticker) for l in terms.extra_legs]}  exp "
              f"{[(r['ratio'], r['price_ticker']) for r in legs[1:]]}  {'ok' if checks['legs'] else 'X'}")
    if terms.election_note or terms.contingent_note:
        print(f"      notes: {terms.election_note} | {terms.contingent_note}")
    if not ok:
        print(f"      quote: {terms.quote[:200]}")
    return ok


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=None, help="run only the first N labeled cases")
    p.add_argument("--tickers", type=str, default=None, help="comma-separated subset")
    p.add_argument("--truth", action="store_true", help="also run the diagnosis truth set's terms cases")
    args = p.parse_args(argv)

    cases = GROUND_TRUTH
    want = {t.strip().upper() for t in args.tickers.split(",")} if args.tickers else None
    if want:
        cases = [c for c in cases if c[0] in want]
    elif args.n is not None:
        cases = cases[: args.n]

    edgar = EdgarClient(cache_dir=ROOT / "cache" / "edgar")
    llm = default_llm_client()
    ext = LLMMergerTermsExtractor(edgar, llm, cache_dir=ROOT / "cache" / "llm")

    n_pass, n_all = 0, 0
    for ticker, cik, date, exp_cash, exp_ratio, exp_acq in cases:
        n_all += 1
        terms = ext.extract(_rec(ticker, cik, date))
        if terms is None:
            print(f"\n{ticker:5s} {date}  ->  MISS (extractor returned None)")
            print(f"      expected: cash={exp_cash} ratio={exp_ratio} acq={exp_acq}")
            continue

        cm = _cash_match(terms.cash_per_share, exp_cash)
        cur = exp_cash is None or terms.cash_currency == "USD"
        rm = _ratio_match(terms.stock_ratio, exp_ratio)
        am = _acq_match(terms.acquirer_ticker, exp_acq)
        ok = cm and cur and rm and am
        n_pass += int(ok)

        mark = "PASS" if ok else "FAIL"
        print(f"\n{ticker:5s} {date}  ->  {mark}   [{terms.deal_type}, conf={terms.confidence}, {terms.source}]")
        print(f"      cash : {terms.cash_per_share!s:>10} {terms.cash_currency or '-':4s} exp {exp_cash!s:>8}  "
              f"{'ok' if cm and cur else 'X'}")
        print(f"      ratio: {terms.stock_ratio!s:>10}  exp {exp_ratio!s:>8}  {'ok' if rm else 'X'}")
        print(f"      acq  : {str(terms.acquirer_ticker):>10}  exp {str(exp_acq):>8}  {'ok' if am else 'X'}"
              f"   (name={terms.acquirer_name})")
        if not ok:
            print(f"      quote: {terms.quote[:160]}")

    if args.truth:
        for c in _truth_cases(want):
            n_all += 1
            n_pass += int(_show_truth(ext, c))

    print(f"\n==== {n_pass}/{n_all} passed ====")
    return 0 if n_pass == n_all else 1


if __name__ == "__main__":
    sys.exit(main())

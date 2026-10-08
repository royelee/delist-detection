"""Build tests/fixtures/acquirer_gate/ from the local caches, once (sub-plan 5e): the real merger endings whose
acquirer line (pipeline stage 8a), payout gate and acquirer security tests/test_acquirer_gate_cases.py replays offline
through the run's own stage 8 (`merger_value.value_mergers`, tests/acquirer_gate_cases.py).

  PYTHONPATH=src python scripts/build_acquirer_gate_fixtures.py          # -> tests/fixtures/acquirer_gate/

Offline, as scripts/build_form25_fixtures.py (whose helpers it reuses; every SEC request is refused): it reads the
committed output/ (each case's merger row, its last trade, last close and the regex payout read; the securities an
acquirer lookup may name, with their observations and CUSIPs), the cached LLM answers (the terms the run read, through
the run's own extractor with an LLM that refuses every call), the cached fails zips, EDGAR submissions, the
resolver's cached answers and OpenFIGI's cached CUSIP answers. It writes:

- cases.json: each case (its note, the target's row, the LLM terms, the resolver's answer for the terms' ticker)
  and every security the cases need: the target, every security whose ticker history holds the terms' ticker (or
  the truth's or the committed run's price ticker) within a year of the last trade, every line of their issuers and
  of the resolver's, and, for terms with no ticker, every issuer of the run whose EDGAR names agree with the terms'
  acquirer name and its lines (CIK, class, name, eras with their observations, CUSIPs);
- ftd_rows.csv.gz: every fails row of those securities' CUSIPs, and under the cases' tickers, from 60 days before
  each case's last trade to 20 days after its price date, and each CUSIP's first row;
- edgar.json: the submissions (name, former names, tickers) of every CIK above;
- figi.json: the cached OpenFIGI answer of every CUSIP under a case's ticker near its last trade (US venues only).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import importlib.util
import io
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_form25_fixtures as b5  # noqa: E402  (refuses every SEC request on import)
from delist_detection.measurement.truth_set import TruthSet, configured  # noqa: E402
import requests  # noqa: E402
import delist_detection.sources.edgar as edgar_mod  # noqa: E402


def _unreachable(*args, **kwargs):
    # refused as a failed request, so the resolver goes on to its next tier, as in an offline run
    raise requests.ConnectionError("build_acquirer_gate_fixtures is offline")


edgar_mod.sec_get = _unreachable
from delist_detection.sources.atomic_io import write_atomic  # noqa: E402
from delist_detection.sources.cik_lookup import CikLookupClient  # noqa: E402
from delist_detection.outputs.reconstruction import DelistRecord  # noqa: E402
from delist_detection.filings.evidence import edgar_names  # noqa: E402
from delist_detection.vocabulary.crsp_codes import CrspBucket  # noqa: E402
from delist_detection.sources.edgar import EdgarClient  # noqa: E402
from delist_detection.identity.figi_resolution import US_EXCH  # noqa: E402
from delist_detection.sources.ftd import FtdIndex  # noqa: E402
from delist_detection.vocabulary.identifiers import normalize_ticker  # noqa: E402
from delist_detection.terms.llm_merger_extractor import LLMMergerTermsExtractor  # noqa: E402
from delist_detection.vocabulary.names import names_agree  # noqa: E402
from delist_detection.identity.observations import ObservationIndex, load_observations  # noqa: E402
from delist_detection.sources.openfigi import OpenFigiClient  # noqa: E402
from delist_detection.identity.ticker_resolver import TickerResolver  # noqa: E402
from delist_detection.vocabulary.trading_calendar import next_trading_day  # noqa: E402

AS_OF = b5.AS_OF
BEFORE, AFTER = 60, 20          # fails rows kept from this long before a case's last trade to this long after its price date
HELD_DAYS = 400                 # a security holding a case's ticker this close to the last trade is kept

# The cases: merger endings of the committed run, by sec_id, each with what it pins
CASES = {
    "BBG000BDXVW8": "CAL 2010: UAUA's UAL Corp began trading as UAL on a new CUSIP on the price date (closing CUSIP)",
    "BBG000BSD7C2": "RTN 2020: UTX's close on the last trade day held Carrier and Otis; RTX's new CUSIP (line price)",
    "BBG000BSGQN5": "RYL 2015: SPF is no holder; the resolver's CalAtlantic, after its reverse split (issuer)",
    "BBG000C0NY96": "TCF 2019: CHFC's Chemical Financial took TCF's name; the gate still fails on the target's close",
    "BBG000BJCFP1": "JEF 2013: LUK's holder; OpenFIGI has no answer for its CUSIP (holder)",
    "BBG000C070N2": "XMSR 2008: SIRI's holder; OpenFIGI has no answer for its 2008 CUSIP (holder)",
    "BBG000BGFLL5": "NYX 2013: an election's default package; ICE Group's new CUSIP after the old ICE",
    "BBG000BJVZF7": "FRX 2014: an election's default package, priced by ACT's ticker",
    "BBG000DBVBY4": "EV 2021: an election's default package after a stale close",
    "BBG000C3HNW5": "URS 2014: an election's default package",
    "BBG000PTXBV3": "HTS 2016: an election's default package",
    "CIK230463-COMMON": "PPP 2007: an election's default package before the run's fails window (early merger)",
    "BBG000FJJW82": "ABI 2008: an election's default package; IVGN on the price date though renamed LIFE",
    "BBG000BTN971": "SUN 2012: an election's default package whose regex read the cash leg",
    "BBG000BLPBL5": "AVB 2026: EQR traded as EQR on the price date, Vivmark only later (price ticker)",
    "BBG000BN53G7": "LEG 2026: no ticker; Somnigroup by name (issuer by name)",
    "BBG000K3T8L8": "GXP 2018: no ticker; Monarch Energy Holding, Evergy's name until the closing (issuer by name)",
    "BBG01HLM8W28": "LSXMA 2024: no ticker; New Sirius's line under old Sirius's CIK (issuer by name, closing CUSIP)",
    "BBG000DQV8M1": "MIR 2010: RRI's holder became GEN on a new CUSIP at the closing",
    "BBG00K7K2XZ0": "GLIBA 2020: LBRDA in the terms, Series C in the filing (class)",
    "BBG000BYD720": "JNS 2017: JHG's first row at $1.00 is a placeholder",
    "BBG000FVQ434": "IHS 2016: INFO's first row at $0.01 is a placeholder",
    "BBG0069FL5L5": "MRD 2016: the line found; the stale close still fails the gate (the gate does its job)",
    "BBG0077VS2C0": "BLD 2026: the line found; a prorated package still fails the gate",
    "BBG000BRZBT3": "RDC 2019: ESV's pre-consolidation close reconciles; never repriced on the new CUSIP (guard)",
    "BBG000BWMX63": "WBS 2018: SAN's acquirer from the fails rows (an acquirer the run adds), unchanged (guard)",
    "BBG000R23VW8": "IPHI 2021: new Marvell from the fails rows, not old Marvell's holder (guard)",
    "BBG000JXRXK2": "SOV 2009: SAN was Santander Chile's ticker in 2009; no line, the gate still fails (guard)",
    "BBG000BJ27C4": "PGN 2012: DUK passes and its acquirer stands (guard)",
    "BBG000H89QJ6": "TWC 2016: CHTR's rows are old Charter's; stage 8a's New Charter (closing CUSIP) stands",
    "BBG000DHM3H8": "VIA 2019: the quote names ViacomCBS Class A; CBS's Class B is another line of the issuer",
    "BBG000DHSPT0": "VIA-B 2019: the same quote, the target's own class B: ViacomCBS Class B",
    "BBG000PCNTM2": "STRZA 2016: Lions Gate's class B non-voting (LGFB) on a new CUSIP, not the holder's placeholder",
}


class NoLlm:
    def extract(self, *a, **k):
        raise RuntimeError("offline: no LLM call")


def _anchor(r: dict) -> str:
    return r["last_trade_date"] or r["delist_filing_date"] or r["delist_date"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "acquirer_gate")
    p.add_argument("--repo", type=Path, default=ROOT)
    args = p.parse_args(argv)
    repo, out = args.repo, args.out
    secs, eras, cusips, history, _ = b5._securities(repo)
    truth = {r["sec_id"]: r for r in TruthSet.open(configured(repo)).rows}
    contract = {r["sec_id"]: r for r in b5._read(repo / "output/contract/delistings.csv")}
    merger_rows = defaultdict(list)
    for r in b5._read(repo / "output/delistings.csv"):
        if r["bucket"] == "merger":
            merger_rows[r["sec_id"]].append(r)
    by_cik: dict[str, list[str]] = defaultdict(list)
    for sid, s in secs.items():
        if s["issuer_cik"]:
            by_cik[s["issuer_cik"]].append(sid)
    held: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for sid, rows in history.items():
        for r in rows:
            held[normalize_ticker(r["ticker"])].append((sid, r["valid_from"], r["valid_to"] or AS_OF.isoformat()))

    cache = repo / "cache"
    edgar = EdgarClient(cache_dir=cache / "edgar", sleep=lambda s: None, today=AS_OF)
    llm = LLMMergerTermsExtractor(edgar, NoLlm(), model="gpt-5.4", cache_dir=cache / "llm")
    figi = OpenFigiClient(cache / "openfigi", "offline-key", sleep=lambda s: None)
    figi._post = lambda path, payload: [{"error": "offline"} for _ in payload]
    # the run's own resolver (its renames, overrides, observed names and pins), answering from its cache only
    spec = importlib.util.spec_from_file_location("cu", repo / "scripts" / "classify_universe.py")
    cu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cu)
    index = ObservationIndex(load_observations(repo / "data" / "observations.csv"))
    resolver = TickerResolver(edgar, rename_map=cu.KNOWN_RENAMES,
                              manual_overrides={k: v for k, v in cu.MANUAL_OVERRIDES.items() if v > 0},
                              cache_path=cache / "ticker_resolution.json", observed_names=index.name_on,
                              cik_pins=index.cik_pin_on, today=AS_OF, batch_writes=True,
                              name_index=CikLookupClient(cache / "sec_data" / "cik_lookup").index)

    def subs(cik: int) -> dict:
        got = b5._cached(edgar.submissions, int(cik), default=None)
        return got if isinstance(got, dict) else {}

    cases, needed, windows, tickers_of = {}, set(), [], {}
    run_ciks = sorted({int(c) for c in by_cik})
    for sid, note in CASES.items():
        row = merger_rows[sid][-1]
        rec = DelistRecord(row["ticker"], int(row["cik"]), _anchor(row), int(row["crsp_code"] or 0), CrspBucket.MERGER,
                           "", "", sec_id=sid, delist_date=row["delist_date"])
        t = b5._cached(llm.extract, rec)
        last = date.fromisoformat(row["last_trade_date"])
        day = next_trading_day(last)
        ticker = normalize_ticker(t.acquirer_ticker or "") if t and t.acquirer_ticker else ""
        tickers = {x for x in (ticker, normalize_ticker((truth.get(sid) or {}).get("price_ticker", "")),
                               normalize_ticker(contract.get(sid, {}).get("price_ticker", ""))) if x and x != "*"}
        resolved = b5._cached(lambda: resolver.resolve(ticker, last.isoformat(),
                                                       name=(t.acquirer_name or None)).cik) if ticker else None
        lo, hi = (last - timedelta(days=HELD_DAYS)).isoformat(), (day + timedelta(days=HELD_DAYS)).isoformat()
        holders = {h for tk in tickers for h, a, b in held.get(tk, []) if a <= hi and b >= lo}
        ciks = {secs[h]["issuer_cik"] for h in holders if secs[h]["issuer_cik"]}
        if resolved:
            ciks.add(str(resolved))
        for x in ((truth.get(sid) or {}).get("price_sec_id"), contract.get(sid, {}).get("price_sec_id")):
            if x in secs and secs[x]["issuer_cik"]:
                ciks.add(secs[x]["issuer_cik"])
        if not ticker and t and t.acquirer_name:
            ciks |= {str(c) for c in run_ciks
                     if any(names_agree(t.acquirer_name, n) for n in edgar_names(subs(c)))}
        group = {sid} | holders | {x for c in ciks for x in by_cik.get(c, [])}
        needed |= group
        windows.append((last - timedelta(days=BEFORE), day + timedelta(days=AFTER), group, tickers))
        tickers_of[sid] = tickers
        cases[sid] = {
            "note": note, "ticker": row["ticker"], "cik": int(row["cik"]), "delist_date": row["delist_date"],
            "last_trade_date": row["last_trade_date"], "last_trade_source": row["last_trade_date_source"],
            "last_trade_close": float(row["last_trade_close"]) if row["last_trade_close"] else None,
            "raw": [float(row["raw_payout_per_share"]), row["raw_payout_source"], row["raw_payout_confidence"]]
            if row["raw_payout_per_share"] else None,
            "terms": None if t is None else [t.deal_type, t.cash_per_share, t.stock_ratio, t.acquirer_name,
                                             t.acquirer_ticker, t.confidence, t.source, t.quote],
            "resolved": {f"{ticker}|{last.isoformat()}": resolved} if ticker else {},
            "committed": {k: contract.get(sid, {}).get(k, "") for k in ("price_sec_id", "price_ticker", "terms_gate")},
        }

    local = b5.LocalFtd(repo / "cache/sec_data/ftd")
    rows = set()
    for lo, hi, group, tickers in windows:
        idx = FtdIndex.opened(local, lo, min(hi, AS_OF), cusips={c for s in group for c in cusips.get(s, [])},
                              symbols=tickers)
        rows.update(r for c in {c for s in group for c in cusips.get(s, [])} for r in idx.by_cusip(c))
        rows.update(r for tk in tickers for r in idx.by_symbol(tk))
    firsts = defaultdict(lambda: "~")
    for r in b5._read(repo / "output/cusip_history.csv"):
        if r["sec_id"] in needed:
            firsts[r["cusip"]] = min(firsts[r["cusip"]], r["valid_from"])
    for c, d in sorted(firsts.items()):
        day = date.fromisoformat(d)
        idx = FtdIndex.opened(local, day - timedelta(days=5), day + timedelta(days=5), cusips={c})
        rows.update(idx.by_cusip(c)[:3])

    figi_answers = {}
    for sid, case in cases.items():
        last = date.fromisoformat(case["last_trade_date"])
        near = {r.cusip for r in rows if r.symbol in tickers_of[sid]
                and abs((date.fromisoformat(r.date) - last).days) <= 12}
        for c in sorted(near):
            ans = figi.map([{"idType": "ID_CUSIP", "idValue": c, "includeUnlistedEquities": True}])[0]
            if "error" in ans:
                continue
            figi_answers[c] = {"data": [d for d in ans.get("data") or [] if d.get("exchCode") in US_EXCH]}

    ciks = sorted({int(secs[s]["issuer_cik"]) for s in needed if secs[s]["issuer_cik"]}
                  | {c["cik"] for c in cases.values()}
                  | {int(v) for c in cases.values() for v in c["resolved"].values() if v})
    issuers = {str(c): {k: subs(c).get(k) for k in ("name", "formerNames", "tickers")} for c in ciks if subs(c)}
    data = {"as_of": AS_OF.isoformat(), "cases": cases,
            "securities": {sid: {**secs[sid], "eras": eras.get(sid, {}), "cusips": cusips.get(sid, [])}
                           for sid in sorted(needed)}}
    out.mkdir(parents=True, exist_ok=True)
    write_atomic(out / "cases.json", json.dumps(data, indent=1, sort_keys=True))
    write_atomic(out / "edgar.json", json.dumps(issuers, indent=1, sort_keys=True))
    write_atomic(out / "figi.json", json.dumps(figi_answers, indent=1, sort_keys=True))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "cusip", "symbol", "description", "price"])
    for r in sorted(rows, key=lambda r: (r.date, r.cusip, r.symbol)):
        w.writerow([r.date, r.cusip, r.symbol, r.description, "" if r.price is None else r.price])
    write_atomic(out / "ftd_rows.csv.gz", gzip.compress(buf.getvalue().encode(), mtime=0))
    print(f"{len(cases)} cases, {len(needed)} securities, {len(rows)} fails rows, {len(issuers)} issuers, "
          f"{len(figi_answers)} OpenFIGI answers -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

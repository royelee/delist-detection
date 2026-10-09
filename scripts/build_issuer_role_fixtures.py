"""Build tests/fixtures/issuer_role/ from the local caches, once (sub-plan 5c): the real cases whose ending kind
(stage 5), R1 rewrite (stage 8b) and successor link (stage 9) tests/test_issuer_role_cases.py replays offline
through the run's own code (tests/issuer_role_cases.py).

  PYTHONPATH=src python scripts/build_issuer_role_fixtures.py          # -> tests/fixtures/issuer_role/

Offline, as scripts/build_form25_fixtures.py (whose helpers it reuses): it reads the committed output/ (each case's
security, its eras and observations, CUSIPs, listed today, its delistings and the contract's terms; and the
securities a link may name), the cached fails zips, EDGAR answers (every SEC request refused: a missing answer is
left out), OpenFIGI answers, MIDAS summaries and Nasdaq halt days. It writes:

- cases.json: each case (its note, its delistings' anchors, the terms the contract published for its merger rows)
  and every security the cases need (the cases, the securities a successor link may name, and the other
  securities of their issuers: CIK, class, name, kind, eras with their observations, CUSIPs, line tickers, listed
  today; an acquirer the run added: its ticker and span);
- ftd_rows.csv.gz: every fails row of a case's CUSIPs in the run's window and every row under a case's tickers
  within 40 days of a delisting's anchor; for the other securities, the first and last row per (CUSIP, symbol)
  and the first per (CUSIP, description);
- edgar.json.gz: each CIK's EDGAR names, tickers and filings (every Form 25, 8-K, periodic report, Form 15,
  revocation, 8-A12B and merger filing, and its first filing of any form, in EDGAR's order), every cached Form 25
  raw, every cached 8-K text filed within TEXT_DAYS of a case's anchor, and those 5b's builder keeps;
- figi.json: the cached OpenFIGI answer of every CUSIP job a successor link may send (a CUSIP a case's texts name,
  or a new CUSIP under its tickers after its anchor), its US venues' rows only; an uncached one is an error answer;
- midas.json, halts.json: as scripts/build_form25_fixtures.py.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_form25_fixtures as b5  # noqa: E402  (refuses every SEC request on import)
from delist_detection.sources.atomic_io import write_atomic  # noqa: E402
from delist_detection.sources.edgar import EdgarClient  # noqa: E402
from delist_detection.filings.form25 import FORM25_FORMS  # noqa: E402
from delist_detection.identity.figi_resolution import US_EXCH  # noqa: E402
from delist_detection.sources.ftd import FtdIndex  # noqa: E402
from delist_detection.identity.line_follow import text_cusips  # noqa: E402
from delist_detection.filings.listing_status import ANNUAL_FORMS  # noqa: E402
from delist_detection.sources.nasdaq_halts import parse_halts_rss  # noqa: E402
from delist_detection.identity.security_master import cusip_job  # noqa: E402

AS_OF, FTD_WINDOW, COVER_DAYS = b5.AS_OF, b5.FTD_WINDOW, b5.COVER_DAYS
TEXT_DAYS = (40, 70)            # 8-K texts kept from this long before a case's anchor to this long after
ROWS_DAYS = 40                  # fails rows under a case's tickers kept this close to its anchor

# The cases: securities of the committed run, each with what it pins
CASES = {
    "BBG000BD4VG8": "BHI 2017: one share of BHGE's Class A, a special dividend; a new issuer (rule 4)",
    "BBG000MJRJJ2": "HHC 2023: one share of Holdco's common; a new issuer (rule 4)",
    "BBG000BFTJ91": "CMCSK 2015: Class A Special reclassified into Class A (rule 3)",
    "CIK48898-CLASS-B": "HUB-B 2015: Class B reclassified into the new common, cash only for Class A (rule 3)",
    "BBG000J453J8": "CCO 2019: the same CIK's 8-K12B, a new CUSIP with its own composite (rule 4, own registration)",
    "BBG004P33PN3": "CWENA 2026: Class A converted into Class C, no 8-K item code (R1 in stage 5, rule 3)",
    "BBG000BQHGR6": "OKE 2026: a holding company's formation, no 8-K item code (R1 in stage 5)",
    "BBG000BHBK84": "DOW 2017: one DowDuPont share, DuPont's 1.282 beside it (8b)",
    "BBG000BPQD31": "MYL 2020: one Viatris share (8b)",
    "BBG000F2XXP2": "SBGI 2023: one New Sinclair share; the successor an acquirer the run added (8b)",
    "BBG000VMWHH5": "DISCK 2022: Series C reclassified into WBD, the same CIK (8b)",
    "BBG000CHWP52": "DISCA 2022: Series A reclassified into WBD, the same CIK (8b)",
    "BBG01HMFL081": "LLYVA 2025: a split-off into the corresponding series (8b)",
    "BBG01HMFLTN1": "LLYVK 2025: a split-off into the corresponding series (8b)",
    "CIK104207-COMMON": "WAG 2014: one WBA share (8b)",
    "CIK944868-COMMON": "DTV 2009: one new DIRECTV share; LEI's 1.1113 beside it (8b)",
    "BBG000BJ9D07": "ROVI 2016: one Parent share; the successor not in the run (8b needs the 8-K12B search)",
    "BBG001YMS0B8": "KRFT 2015: one Kraft Heinz share and a special dividend (8b)",
    "BBG000CGQ6M4": "PX 2018: one Linde plc share (8b; truth 5e)",
    "BBG000G0PPW3": "AMSG 2016: one new Envision share (8b; truth 5e)",
    "CIK1126294-COMMON": "RRI 2010: the legal acquirer of Mirant (rule 1)",
    "CIK1363851-COMMON": "SXCI 2012: the acquirer of Catalyst (rule 1)",
    "CIK1308161-COMMON": "NWS-A 2013: the distributor of new News Corp (rule 1)",
    "CIK1308161-CLASS-A": "NCRA 2013: the distributor of new News Corp (rule 1)",
    "CIK38079-COMMON": "FST 2014: issued its shares to Sabine; the NYSE price deficiency (rule 1, branch 5)",
    "BBG0038K9G41": "LVNTA 2018: one GLIBA share, an existing issuer (stays a merger)",
    "BBG000BJCFP1": "JEF 2013: an intermediate one-for-one, then 0.81 LUK (stays a merger)",
    "BBG000BSVZM9": "SGP 2009: $10.50 and 0.5767 New Merck; renamed Merck after (stays a merger)",
    "BBG000BM1RP0": "FCL 2009: 1.084 New Alpha, renamed Alpha after (stays a merger)",
    "BBG000BBLK04": "TW 2016: LLM 1.0 WLTW, an existing issuer (stays a merger)",
    "BBG000BHW628": "WCN 2016: one share after a consolidation, an existing issuer (stays a merger)",
    "BBG003444577": "BKW 2014: 0.99 QSR and $3.00 (stays a merger)",
    "BBG000K1T0M8": "LGFA 2025: a separation, the target of New Lionsgate (stays a merger)",
    "BBG000BDKN87": "BNI 2010: renamed after its acquisition (stays a merger)",
    "BBG000BDXVW8": "CAL 2010: 1.05 UAL, renamed (stays a merger)",
    "BBG000BVW841": "TXU 2007: an LBO, renamed (stays a merger)",
    "CIK1011006-COMMON": "AABA 2017: a rename, no statement; BHGE first sighted near it (no link)",
    "CIK1469372-CLASS-A": "MSG 2015: a spin-off distribution (no link)",
    "BBG000BT0093": "SIRI 2024: 0.1 New Sirius, a continuation already (unchanged)",
    "BBG000PYZSR8": "CHTR 2016: 0.9042 New Charter, a transfer with a successor (unchanged: rule 6 is 5f's)",
}

# The securities a successor link may name (and the guards' existing acquirers), with what each one is
SUPPORT = {
    "BBG00GBVBK51": "BHGE", "BBG01HTMDZ54": "HHH", "BBG000BFT2L4": "CMCSA", "BBG000BLK267": "HUBB",
    "BBG008LJ4TF3": "CWEN", "BBG00BN961G4": "DWDP", "BBG00Y4RQNH4": "VTRS", "BBG01GJ3NY88": "Sinclair Inc (added)",
    "BBG011386VF4": "WBD", "BBG01YY256K1": "LLYVA (Liberty Live Holdings)", "BBG01YYX1Z14": "LLYVK (Liberty Live "
    "Holdings)", "BBG000BWLMJ4": "WBA", "BBG000FL1TC8": "DTV (new DIRECTV)", "BBG005CPNTQ2": "KHC",
    "BBG00GVR8YQ9": "LIN (Linde plc)", "BBG00D3CHRC0": "EVHC (new Envision)", "BBG00K7K2XZ0": "GLIBA",
    "BBG000DB3KT1": "WLTW", "BBG000FLHZZ2": "WCN (Progressive Waste)", "BBG0076WG2V1": "QSR",
    "BBG01KJQM3Y8": "SIRI (New Sirius)", "BBG000VPGNR2": "CHTR (New Charter)",
}


def _anchor(r: dict) -> date:
    return date.fromisoformat(r["last_trade_date"] or r["delist_filing_date"] or r["delist_date"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "issuer_role")
    p.add_argument("--repo", type=Path, default=ROOT)
    args = p.parse_args(argv)
    repo, out = args.repo, args.out
    secs, eras, cusips, history, _ = b5._securities(repo)
    dl = defaultdict(list)
    for r in b5._read(repo / "output/delistings.csv"):
        dl[r["sec_id"]].append(r)
    contract = {r["sec_id"]: r for r in b5._read(repo / "output/contract/delistings.csv")}
    by_cik: dict[str, list[str]] = defaultdict(list)
    for sid, s in secs.items():
        if s["issuer_cik"]:
            by_cik[s["issuer_cik"]].append(sid)
    core = set(CASES) | set(SUPPORT)
    needed = core | {x for sid in core for x in by_cik.get(secs[sid]["issuer_cik"], [])}
    ciks = sorted({int(secs[sid]["issuer_cik"]) for sid in needed if secs[sid]["issuer_cik"]})
    anchors = {sid: [_anchor(r) for r in dl.get(sid, [])] for sid in CASES}

    # fails rows: a case's CUSIPs, and its tickers' rows near its anchors; the others' span and descriptions
    local = b5.LocalFtd(repo / "cache/sec_data/ftd")
    ftd = FtdIndex.opened(local, *FTD_WINDOW, cusips={c for sid in needed for c in cusips.get(sid, [])})
    rows = set()
    for sid in needed:
        for c in cusips.get(sid, []):
            got = ftd.by_cusip(c)
            if sid in CASES:
                rows.update(got)
                continue
            ends, descs = {}, {}
            for r in got:
                ends.setdefault((r.cusip, r.symbol), [r, r])[1] = r
                descs.setdefault((r.cusip, r.description), r)
            rows.update(x for pair in ends.values() for x in pair)
            rows.update(descs.values())
    for sid in CASES:
        tickers = {k.split("@")[0] for k in eras[sid]} | set(b5._line_tickers(eras[sid], history[sid]))
        for day in anchors[sid]:
            lo, hi = day - timedelta(days=ROWS_DAYS), day + timedelta(days=ROWS_DAYS)
            near = FtdIndex.opened(local, lo, min(hi, AS_OF), symbols=tickers)
            rows.update(r for t in tickers for r in near.by_symbol(t))

    # EDGAR
    edgar = EdgarClient(repo / "cache/edgar", user_agent="build_issuer_role_fixtures fixtures@example.com",
                        today=AS_OF)
    case_ciks = {int(secs[sid]["issuer_cik"]) for sid in CASES if secs[sid]["issuer_cik"]}
    windows = defaultdict(list)
    for sid in CASES:
        for day in anchors[sid]:
            windows[int(secs[sid]["issuer_cik"])].append((day - timedelta(days=TEXT_DAYS[0]),
                                                           day + timedelta(days=TEXT_DAYS[1])))
    issuers, raws, texts = {}, {}, {}
    for cik in ciks:
        sub = b5._cached(edgar.submissions, cik, default={}) or {}
        every = b5._cached(edgar.recent_filings, cik, default=[]) or []
        first = min((f for f in every if f.filing_date), key=lambda f: f.filing_date, default=None)
        filings = [f for f in every if b5.KEPT_FORMS.match(f.form or "") or f is first]
        issuers[str(cik)] = {"name": sub.get("name", ""), "formerNames": sub.get("formerNames") or [],
                             "tickers": sub.get("tickers") or [], "exchanges": sub.get("exchanges") or [],
                             "sic": str(sub.get("sic") or ""),
                             "filings": [[f.accession, f.form, f.filing_date, f.report_date, f.items, f.primary_doc]
                                         for f in filings]}
        if cik not in case_ciks:
            continue
        f25 = [f for f in filings if f.form in FORM25_FORMS]
        for f in f25:
            raw = b5._cached(edgar.fetch_filing_raw, cik, f.accession, default="")
            if raw:
                raws[f.accession] = raw
        for f in filings:
            day = b5._day(f.filing_date)
            near = any(lo <= day <= hi for lo, hi in windows[cik])
            if f.form.startswith("8-K") and (near or {"1.03", "3.01"} & f.item_set):
                text = b5._cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                if text:
                    texts[f.accession] = text
            elif f.form in ANNUAL_FORMS and any(abs((day - b5._day(g.filing_date)).days) <= COVER_DAYS for g in f25):
                text = b5._cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                if text:
                    texts[f.accession] = text[:12000]

    # OpenFIGI: every CUSIP job a successor link may send
    jobs = set()
    for sid in CASES:
        own = set(cusips.get(sid, []))
        cik = secs[sid]["issuer_cik"]
        named = {c for acc, t in texts.items() if any(acc == f[0] for f in issuers.get(cik, {}).get("filings", []))
                 for c in text_cusips([t])}
        named |= {c for acc, raw in raws.items() for c in text_cusips([raw])
                  if any(acc == f[0] for f in issuers.get(cik, {}).get("filings", []))}
        tickers = {k.split("@")[0] for k in eras[sid]}
        later = {r.cusip for r in rows if r.symbol in tickers and r.cusip not in own
                 and any(day.isoformat() <= r.date <= (day + timedelta(days=15)).isoformat() for day in anchors[sid])}
        jobs |= (named | later) - own
    figi = {}
    for c in sorted(jobs):
        job = cusip_job(c)
        h = hashlib.sha1(json.dumps({"kind": "mapping", "payload": job}, sort_keys=True).encode()).hexdigest()
        path = repo / "cache/openfigi" / f"{h}.json"
        ans = json.loads(path.read_text()) if path.exists() else {"error": "not cached"}
        # the US venues' rows only: all that `figi_resolution.us_candidates` reads
        figi[c] = ans if "error" in ans else {"data": [r for r in ans.get("data") or [] if r.get("exchCode") in US_EXCH]}

    # MIDAS and halts, for every symbol the cases' sightings carry, around their anchors
    symbols = {sid: {k.split("@")[0] for k in eras[sid]} | {r.symbol for c in cusips.get(sid, [])
                                                              for r in ftd.by_cusip(c)} for sid in CASES}
    midas: dict[str, dict[str, list[str]]] = {}
    midas_dir = repo / "cache/sec_data/midas"
    quarters = sorted(p.name[:7] for p in midas_dir.glob("*_q*.json.gz"))
    for path in sorted(midas_dir.glob("*_q*.json.gz")):
        summary = json.loads(gzip.decompress(path.read_bytes()))
        for sid in CASES:
            for t in symbols[sid]:
                for d in summary.get(t, []):
                    if any(abs((b5._day(d) - a).days) <= 120 for a in anchors[sid]):
                        midas.setdefault(path.name[:7], {}).setdefault(t, []).append(d)
    halts: dict[str, list[list[str]]] = {}
    wanted = {t for v in symbols.values() for t in v}
    for path in sorted((repo / "cache/nasdaq_halts").glob("*.xml")):
        for h in b5._cached(parse_halts_rss, path.read_bytes(), default=[]):
            if h.reason == "D" and h.symbol in wanted:
                halts.setdefault(path.stem, []).append([h.symbol, h.name, h.market, h.reason, h.halt_date.isoformat(),
                                                        h.halt_time, h.resumption_date.isoformat()
                                                        if h.resumption_date else ""])

    out.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "cusip", "symbol", "description", "price"])
    for r in sorted(rows, key=lambda r: (r.date, r.cusip, r.symbol, r.description, r.price or 0)):
        w.writerow([r.date, r.cusip, r.symbol, r.description, "" if r.price is None else r.price])
    write_atomic(out / "ftd_rows.csv.gz", gzip.compress(buf.getvalue().encode(), mtime=0))
    securities = {}
    for sid in sorted(needed):
        s = secs[sid]
        securities[sid] = {"issuer_cik": int(s["issuer_cik"]) if s["issuer_cik"] else None,
                           "share_class": s["share_class"], "name": s["name"], "security_type": s["security_type"],
                           "observed": s["observed"] == "true", "figi_source": s["figi_source"],
                           "cusips": cusips.get(sid, []), "line_tickers": b5._line_tickers(eras[sid], history[sid]),
                           "listed": any(r["valid_to"] == "" for r in history.get(sid, [])),
                           "eras": {k: sorted(v, key=lambda o: o[1]) for k, v in sorted(eras[sid].items())},
                           "history": [[r["ticker"], r["valid_from"], r["valid_to"]] for r in history.get(sid, [])]}
    cases = {}
    for sid, note in CASES.items():
        c = contract.get(sid, {})
        terms = {}
        for r in dl.get(sid, []):
            if r["bucket"] == "merger" and c.get("value_rule") in ("stock", "cash", "cash_plus_stock"):
                terms[r["delist_date"]] = [c["cash_per_share"], c["stock_ratio"], c["price_ticker"]]
        cases[sid] = {"note": note, "terms": terms}
    data = {"as_of": AS_OF.isoformat(), "cases": cases, "support": SUPPORT, "securities": securities}
    for name, payload in (("cases.json", data), ("figi.json", figi), ("midas.json", {"quarters": quarters,
                                                                                      "days": midas}),
                          ("halts.json", halts)):
        write_atomic(out / name, json.dumps(payload, indent=1, sort_keys=True) + "\n")
    edgar_json = json.dumps({"issuers": issuers, "raws": raws, "texts": texts}, sort_keys=True) + "\n"
    write_atomic(out / "edgar.json.gz", gzip.compress(edgar_json.encode(), mtime=0))
    print(f"{len(cases)} cases, {len(securities)} securities, {len(rows)} fails rows, {len(ciks)} CIKs, "
          f"{len(raws)} Form 25 raws, {len(texts)} texts, {len(figi)} FIGI answers, "
          f"{sum(len(v) for q in midas.values() for v in q.values())} MIDAS days, "
          f"{sum(len(v) for v in halts.values())} halts -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

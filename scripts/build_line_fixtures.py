"""Build tests/fixtures/lines/ from the local caches, once (sub-plan 5a): the real cases the line follow's tests
replay offline (tests/test_line_follow_cases.py).

  PYTHONPATH=src python scripts/build_line_fixtures.py          # -> tests/fixtures/lines/

Offline: it reads the cached SEC fails-to-deliver zips (cache/sec_data/ftd), the cached EDGAR answers
(cache/edgar; every SEC request is refused, so a missing answer is left out, never fetched), the cached OpenFIGI
answers (cache/openfigi) and the committed output/ (each case's tickers, CUSIPs and the run's CUSIP holders). It
writes:

- cases.json: each case's security (sec_id, issuer CIK, share class, FIGI source, name, tickers, CUSIPs, the
  issuer's other tickers EDGAR lists, the CUSIPs and tickers its 8-K text names), the CUSIP holders of the run the
  steps meet, and the run's securities `decide` must know;
- ftd_rows.csv: the fails rows around each case's line end (and its second step's, for a two-step case);
- edgar.json: each issuer's EDGAR names, tickers and filings around the step, and the 8-K texts a step reads;
- openfigi.json: the cached OpenFIGI answer for each new CUSIP (its US-venue rows; absent when not cached);
- searches.json: the cached successor search of each step (absent when not cached).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import delist_detection.edgar as edgar_mod  # noqa: E402


def _refuse(*args, **kwargs):
    raise RuntimeError("build_line_fixtures is offline: a missing cache entry is left out")


edgar_mod.sec_get = _refuse
from delist_detection.atomic_io import write_atomic  # noqa: E402
from delist_detection.edgar import EdgarClient  # noqa: E402
from delist_detection.figi_resolution import US_EXCH  # noqa: E402
from delist_detection.ftd import FtdIndex, parse_ftd_lines, period_of  # noqa: E402
from delist_detection.line_follow import (  # noqa: E402
    SUCCESSOR_FORMS, SWITCH, candidate_steps, eightks_near, is_line_symbol, line_end, name_on, text_cusips,
    text_symbols,
)
from delist_detection.observations import normalize_ticker  # noqa: E402
from delist_detection.security_master import cusip_job  # noqa: E402
from delist_detection.filing_search import successor_query  # noqa: E402

AS_OF = date(2026, 9, 25)                 # the committed run's date
FTD_WINDOW = (date(2007, 12, 17), AS_OF)  # the committed run's fails window
ROUNDS = 2                                # a two-step case follows its attached step once more
# The cases: securities of the committed run, each with what it pins
CASES = {
    "BBG000BN6349": "FMD 2013: a reverse split under the same ticker, the same composite",
    "BBG000BLH3P8": "HSC 2023: Harsco renamed Enviri (NVRI) on the same CUSIP",
    "CIK1075415-COMMON": "SNH 2020: Senior Housing renamed Diversified Healthcare (DHC), new CUSIP, beside notes",
    "BBG001D9S707": "DYN 2010: a reverse split stated only in the 8-K text; the new CUSIP has its own composite",
    "BBG00JM9V731": "GTES 2026: a redomicile at a Form 25; the new CUSIP has its own composite",
    "BBG009NGKQ45": "VRM 2024: a reverse split; then bankruptcy (VRMMQ) and a 2025 relist that is no step",
    "BBG000BRWGG9": "RAD 2019: a reverse split; then the OTC RADCQ that is no step",
    "BBG002B67HB2": "UNIT 2025: the old registrant merged out (R1 before R2)",
    "BBG000F2XXP2": "SBGI 2023: a new holding company of another CIK",
    "BBG00WYYC600": "WLL 2017: the new CUSIP is another security's of the run",
    "BBG000BBG3P1": "TMA 2008: the same CUSIP under THMR after a delisting, an OTC move",
    "BBG000D9V7T4": "AAN 2020: the old registrant stopped filing at its reorganization",
    "BBG000FC9SM1": "BXS 2017: a 10-Q filed after the step for the quarter before it",
    "CIK1507934-CLASS-A": "LMCA 2013: the ticker passed to another issuer",
    "CIK1469372-CLASS-A": "MSG 2015: the ticker passed to another issuer",
    "BBG00D30HGP6": "CLNY 2021: Colony renamed DigitalBridge (DBRG), new CUSIP, no US line for it",
    "CIK1115836-COMMON": "OEH 2014: a placeholder whose new CUSIP names Belmond's FIGI line",
    "CIK1066104-COMMON": "EXBD 2012: Corporate Executive Board renamed CEB on the same CUSIP",
}
EXTRA_RUN = ("BBG01GJ3NY88", "BBG000BKZ5F6", "BBG000PX3XC0", "BBG003P9ZSL3", "BBG007FG0C23")


class LocalFtd:
    """The cached fails zips, read as `ftd.FtdClient` reads downloaded ones."""

    def __init__(self, folder: Path):
        self.files = sorted(folder.glob("cnsfails*.zip")) + sorted(folder.glob("cnsp_sec_fails_*.zip"))

    def urls_for(self, lo, hi):
        return [str(p) for p in self.files if (per := period_of(p.name)) and per[0] <= hi and per[1] >= lo]

    def rows(self, url, *, symbols=None, cusips=None):
        with zipfile.ZipFile(url) as z:
            for info in z.infolist():
                if not info.is_dir():
                    with z.open(info) as fh:
                        yield from parse_ftd_lines(io.TextIOWrapper(fh, encoding="latin-1"), symbols=symbols,
                                                   cusips=cusips)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _cached(fn, *args, default=None):
    try:
        return fn(*args)
    except Exception:          # noqa: BLE001 -- an uncached answer: left out
        return default


def _figi(cache: Path, cusip: str):
    job = cusip_job(cusip)
    h = hashlib.sha1(json.dumps({"kind": "mapping", "payload": job}, sort_keys=True).encode()).hexdigest()
    p = cache / f"{h}.json"
    return json.loads(p.read_text()) if p.exists() else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "lines")
    p.add_argument("--repo", type=Path, default=ROOT)
    args = p.parse_args(argv)
    repo, out = args.repo, args.out
    secs = {r["sec_id"]: r for r in _read(repo / "output/securities.csv")}
    tickers: dict[str, set[str]] = defaultdict(set)
    for r in _read(repo / "output/observation_map.csv"):
        if r["sec_id"]:
            tickers[r["sec_id"]].add(r["era"].split("@")[0])
    cusips: dict[str, list[str]] = defaultdict(list)
    holders: dict[str, set[str]] = defaultdict(set)
    for r in sorted(_read(repo / "output/cusip_history.csv"), key=lambda r: (r["valid_from"], r["cusip"])):
        if r["cusip"] not in cusips[r["sec_id"]]:
            cusips[r["sec_id"]].append(r["cusip"])
        holders[r["cusip"]].add(r["sec_id"])
    edgar = EdgarClient(repo / "cache/edgar", user_agent="build_line_fixtures fixtures@example.com", today=AS_OF)
    subs = {sid: _cached(edgar.submissions, int(secs[sid]["issuer_cik"])) for sid in CASES}
    extra = {sid: {normalize_ticker(t) for t in (subs[sid] or {}).get("tickers") or []
                   if is_line_symbol(normalize_ticker(t))} - tickers[sid] for sid in CASES}
    symbols = {t for sid in CASES for t in tickers[sid]} | {t for v in extra.values() for t in v}
    symbols |= {t.replace("-", "") + s for sid in CASES for t in tickers[sid] for s in ("ZZZZ", "D")}
    ftd = FtdIndex.load(LocalFtd(repo / "cache/sec_data/ftd"), *FTD_WINDOW, symbols=symbols,
                        cusips={c for sid in CASES for c in cusips[sid]})
    named: dict[str, set[str]] = defaultdict(set)
    filings = {sid: _cached(edgar.recent_filings, int(secs[sid]["issuer_cik"]), default=[]) for sid in CASES}
    for sid in CASES:                       # the 8-K text sources, as the stage reads them (line_follow)
        end = line_end(cusips[sid], tickers[sid], ftd)
        if end is None or candidate_steps(sid, cusips[sid], tickers[sid], ftd, holders=holders,
                                          extra_symbols=extra[sid]):
            continue
        cik = int(secs[sid]["issuer_cik"])
        near = [f for f in eightks_near(filings[sid], date.fromisoformat(end.settled))
                if f.form in SUCCESSOR_FORMS or {"5.03", "3.03"} & f.item_set]
        texts = [_cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="") or "" for f in near]
        extra[sid] |= {t for t in text_symbols(texts) if is_line_symbol(t)} - tickers[sid]
        named[sid] |= text_cusips(texts)
    ftd.extend(LocalFtd(repo / "cache/sec_data/ftd"), *FTD_WINDOW, symbols={t for v in extra.values() for t in v},
               cusips={c for v in named.values() for c in v})
    windows: dict[str, list[tuple[str, str, set[str], set[str]]]] = defaultdict(list)
    steps_of: dict[str, list] = {}
    for sid in CASES:
        own, cus = set(tickers[sid]), list(cusips[sid])
        for _ in range(ROUNDS):
            end = line_end(cus, own, ftd)
            if end is None:
                break
            steps = candidate_steps(sid, cus, own, ftd, holders=holders, extra_symbols=extra[sid],
                                    extra_cusips=named[sid])
            new = {st.new_cusip for st in steps if st.kind == SWITCH}
            if new:
                ftd.extend(LocalFtd(repo / "cache/sec_data/ftd"), *FTD_WINDOW, cusips=new)
                steps = candidate_steps(sid, cus, own, ftd, holders=holders, extra_symbols=extra[sid],
                                        extra_cusips=named[sid])
            lo = (date.fromisoformat(end.settled) - timedelta(days=200)).isoformat()
            hi = (date.fromisoformat(end.last) + timedelta(days=260)).isoformat()
            keep_symbols = own | extra[sid] | {t.replace("-", "") + s for t in own for s in ("ZZZZ", "D")}
            windows[sid].append((lo, hi, set(cus) | named[sid] | {st.new_cusip for st in steps}, keep_symbols))
            steps_of.setdefault(sid, steps)
            if not steps:
                break
            st = steps[0]                     # the next round follows the step as an attach would
            cus = cus + ([st.new_cusip] if st.kind == SWITCH and st.new_cusip not in cus else [])
            own = own | {st.symbol}
    rows = set()
    for sid, wins in windows.items():
        for lo, hi, cus, syms in wins:
            for c in cus:
                rows.update(ftd.by_cusip(c, lo, hi))
            for s in syms:
                rows.update(ftd.by_symbol(s, lo, hi))
    out.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "cusip", "symbol", "description", "price"])
    for r in sorted(rows, key=lambda r: (r.date, r.cusip, r.symbol, r.description, r.price or 0)):
        w.writerow([r.date, r.cusip, r.symbol, r.description, "" if r.price is None else r.price])
    write_atomic(out / "ftd_rows.csv", buf.getvalue())
    issuers, texts_out, figi_out, searches = {}, {}, {}, {}
    for sid in CASES:
        cik = int(secs[sid]["issuer_cik"])
        sub = subs[sid] or {}
        steps = steps_of.get(sid, [])
        end = line_end(cusips[sid], tickers[sid], ftd)
        anchor = date.fromisoformat(steps[0].first if steps else end.last if end else AS_OF.isoformat())
        lo, hi = (anchor - timedelta(days=200)).isoformat(), (anchor + timedelta(days=500)).isoformat()
        kept = [f for f in filings[sid] if lo <= (f.filing_date or "") <= hi]
        issuers[str(cik)] = {"name": sub.get("name", ""), "formerNames": sub.get("formerNames") or [],
                             "tickers": sub.get("tickers") or [], "exchanges": sub.get("exchanges") or [],
                             "filings": [[f.accession, f.form, f.filing_date, f.report_date, f.items, f.primary_doc]
                                         for f in sorted(kept, key=lambda f: (f.filing_date, f.accession))]}
        for st in steps[:1]:
            near = eightks_near(kept, date.fromisoformat(st.first))
            if not any({"5.03", "3.03"} & f.item_set for f in near):     # else corroborate reads no text
                for f in near:
                    text = _cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                    if text:
                        texts_out[f.accession] = text
            if st.kind == SWITCH and (ans := _figi(repo / "cache/openfigi", st.new_cusip)) is not None:
                # only the rows on a US venue, the ones `figi_resolution.us_candidates` reads
                figi_out[st.new_cusip] = {**ans, "data": [r for r in ans.get("data") or []
                                                          if r.get("exchCode") in US_EXCH]}
            name = name_on(sub, date.fromisoformat(st.first), secs[sid]["name"])
            q = successor_query(name, date.fromisoformat(st.first)) if name else None
            hits = _cached(edgar.full_text_search, *q, default=None) if q else None
            if hits is not None:
                searches[sid] = {"query": [q[0], q[1], q[2].isoformat(), q[3].isoformat()], "hits": hits}
    run = {k: {"issuer_cik": int(secs[k]["issuer_cik"]) if secs[k]["issuer_cik"] else None,
               "share_class": secs[k]["share_class"], "name": secs[k]["name"], "figi_source": secs[k]["figi_source"]}
           for k in (*CASES, *EXTRA_RUN) if k in secs}
    cases = {sid: {"note": note, "issuer_cik": int(secs[sid]["issuer_cik"]), "share_class": secs[sid]["share_class"],
                   "name": secs[sid]["name"], "figi_source": secs[sid]["figi_source"],
                   "tickers": sorted(tickers[sid]), "cusips": cusips[sid], "extra_symbols": sorted(extra[sid]),
                   "extra_cusips": sorted(named[sid])} for sid, note in CASES.items()}
    near_cusips = {r.cusip for r in rows}
    json_out = {"as_of": AS_OF.isoformat(), "cases": cases, "run": run,
                "holders": {c: sorted(holders[c]) for c in sorted(near_cusips) if holders.get(c)}}
    for name, data in (("cases.json", json_out), ("edgar.json", {"issuers": issuers, "texts": texts_out}),
                       ("openfigi.json", figi_out), ("searches.json", searches)):
        write_atomic(out / name, json.dumps(data, indent=1, sort_keys=True) + "\n")
    print(f"{len(cases)} cases, {len(rows)} fails rows, {len(texts_out)} 8-K texts, {len(figi_out)} OpenFIGI "
          f"answers, {len(searches)} searches -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

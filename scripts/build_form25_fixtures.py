"""Build tests/fixtures/form25_reach/ from the local caches, once (sub-plan 5b): the real cases whose Form 25
search, matching and ownership tests/test_form25_reach_cases.py replays offline through the finder
(`delistings.DelistingFinder`) and the pipeline's own context builder (`pipeline._context_builder`).

  PYTHONPATH=src python scripts/build_form25_fixtures.py          # -> tests/fixtures/form25_reach/

Offline: it reads the committed output/ (each case's securities, eras and observations, CUSIPs, whether it is
listed today, its issuer in force), the cached SEC fails-to-deliver zips (cache/sec_data/ftd), the cached EDGAR
answers (cache/edgar: every SEC request is refused, so a missing answer is left out, never fetched), the cached
MIDAS quarter summaries (cache/sec_data/midas) and Nasdaq halt days (cache/nasdaq_halts). It writes:

- cases.json: each case (its note, its other CIK in force) and every security the cases need (the cases and the
  other securities of their issuers: CIK, class, name, kind, eras with their observations, CUSIPs, line tickers,
  whether it is listed today);
- ftd_rows.csv.gz: every fails row of a case's CUSIPs in the run's window, and for each other security of its
  issuer the first and last row per (CUSIP, symbol) and the first per (CUSIP, description): what its span and
  its class letter read;
- edgar.json.gz: each CIK's EDGAR names, tickers and the filings the finder and the classifier read (every Form 25,
  8-K, periodic report, Form 15, revocation, 8-A12B and merger filing, in EDGAR's order), every cached Form 25
  raw, every cached 8-K text with item 1.03 or 3.01, and the first 12,000 characters (the cover page) of every
  annual report filed within COVER_DAYS of a Form 25;
- midas.json: the MIDAS quarters cached, and each case ticker's days with exchange volume near its Form 25s and
  its last sighting;
- halts.json: the Nasdaq code-D halts of the case tickers on the cached halt days.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import delist_detection.edgar as edgar_mod  # noqa: E402


def _refuse(*args, **kwargs):
    raise RuntimeError("build_form25_fixtures is offline: a missing cache entry is left out")


edgar_mod.sec_get = _refuse
from delist_detection.atomic_io import write_atomic  # noqa: E402
from delist_detection.edgar import EdgarClient  # noqa: E402
from delist_detection.form25 import FORM25_FORMS  # noqa: E402
from delist_detection.ftd import FtdIndex, parse_ftd_lines, period_of  # noqa: E402
from delist_detection.listing_status import ANNUAL_FORMS  # noqa: E402
from delist_detection.nasdaq_halts import parse_halts_rss  # noqa: E402

AS_OF = date(2026, 9, 25)                       # the committed run's date
FTD_WINDOW = (date(2007, 12, 17), AS_OF)        # the committed run's fails window
COVER_DAYS = 460                                # annual reports kept this close to a Form 25 (their cover page)
MIDAS_BEFORE, MIDAS_AFTER = 80, 25              # MIDAS days kept around each Form 25...
SEEN_BEFORE, SEEN_AFTER = 620, 140              # ...and around the last sighting (the fallback's anchors)
KEPT_FORMS = re.compile(r"^(?:25|25-NSE|25/A|25-NSE/A|8-K.*|10-K.*|10-Q.*|20-F.*|40-F.*|15-.*|REVOKED|NT .*"
                        r"|8-A12B.*|DEFM14A|DEFM14C|PREM14A|SC 14D9.*|SC TO-T.*|SC TO-I.*|SC 13E3.*|425|S-4.*)$")
OTC_LIKE = re.compile(r"^[A-Z]{4}[QFEY]$|ZZZZ$|XXXX$")

# The cases: securities of the committed run, each with what it pins
CASES = {
    "BBG000C070N2": "XMSR 2008: a 25-NSE a stale observation continued (C)",
    "BBG000JXRXK2": "SOV 2009: a 25-NSE a stale observation and a cover continued (C)",
    "BBG000BVW841": "TXU 2007: a 25-NSE before the first sighting (E)",
    "CIK898660-COMMON": "STN 2007: a 25-NSE before the first sighting (E)",
    "CIK351346-COMMON": "BMET 2007: a rights-only Form 25 (R3), the 25-NSE before the first sighting (E), "
                        "the notice's 'acquired by' (R6b)",
    "BBG000DGZ1B6": "MWW 2016: a 25-NSE after the alive window (L); the 2008 transfer stays",
    "BBG000BPTDN6": "NTY 2010: the notice's cash conversion owns the row (R6b)",
    "BBG000BRF6B5": "RHD 2009: a removal under (b) the OTC tail continued (C), a market-cap 3.01 (wording)",
    "BBG000PSSG77": "IAR 2008: a removal under (b) the OTC tail continued (C)",
    "BBG009R0CVG1": "LKSD 2020: a removal under (b), OTC under the same symbol (C)",
    "BBG005CPNTQ2": "KHC 2026: the issuer's Form 25 with its 8-A12B (R7)",
    "CIK1355096-SERIES-A": "Liberty Series A 2011: a 25-NSE of the Capital and Starz groups (R3)",
    "CIK867773-COMMON": "SPWRA 2011: a Class A & Class B 25-NSE, two letterless commons (R2)",
    "BBG0038K9G41": "LVNTA 2018: a Series A 25-NSE its own Series A takes, beside a duplicate placeholder whose "
                    "fails say SER A (R2 must not tie them)",
    "BBG000P4BQM9": "SPB 2018: the old Spectrum Brands' 25-NSE under its own CIK (R5)",
    "BBG00B6WH9G3": "MTCH 2020: the old Match Group's 25-NSE under its own CIK (R5)",
    "BBG000BF2JS9": "CNB 2009: a revocation after the 25-NSE (R6a)",
    "BBG000BLY636": "IMB 2008: a revocation after the 25-NSE (R6a)",
    "BBG000BBG3P1": "TMA 2008: a revocation after the 25-NSE (R6a)",
    "BBG000BGZ9V9": "ASNA 2020: a bankruptcy 8-K whose first Item 1.03 is a cross-reference (5g sub-rule 2)",
    "BBG000BP62Y3": "MNI 2020: a removal under (b) the OTC tail continued (C)",
    "BBG005DKMJ67": "LTRPA 2023: a Nasdaq removal under (b), then an OTC merger (C, ruling G4)",
    "BBG000BC2C10": "APA: the Chicago withdrawal of 2020 (regional) and the 2021 holdco (R6b refuses)",
    "CIK48898-CLASS-B": "HUB-B 2015: a reclassification (R6b refuses)",
    "BBG000BFTJ91": "CMCSK 2015: a reclassification, no notice text (R6b refuses)",
    "BBG000MJRJJ2": "HHC 2023: a holding company's formation (R6b refuses)",
    "CIK1469372-CLASS-A": "MSG 2015: the issuer's Form 25 with its 8-A12B ten days earlier (continued)",
    "BBG00GVR8YQ9": "LIN: an old redomiciled line the sibling slack keeps from a false ending",
    "BBG001QD41M9": "APTV: an old redomiciled line the sibling slack keeps from a false ending",
    "BBG000D9DMK0": "LH: an old holdco line the sibling slack keeps from a false ending",
    "BBG00B4Z2YX0": "LAUR: listed today, so no early reach",
    "BBG000CNFQW6": "PRGO: two CIKs in force, so no other CIK (R5) and no 2013 ending",
    "BBG000CS7CB8": "JNC 2007: an early group the fallback finds today",
    "CIK65873-COMMON": "AT 2007: an early group the fallback finds today",
    "BBG000VMWHH5": "DISCK 2022: an exchange's 25-NSE beside an 8-A12B for the new class (no R7)",
    "BBG004P33PN3": "CWENA 2026: an exchange's 25-NSE beside an 8-A12B/A (no R7)",
}


# CIKs whose filings are kept though no case reads them: Perrigo Company's (in force for PRGO until 2013), to show
# what reading it would do
EXTRA_CIKS = (820096,)
# CUSIPs no case security holds whose fails rows are kept: a plan exchange's new line (WOLF's 97785W106, sub-plan 5g)
EXTRA_CUSIPS: tuple[str, ...] = ()


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


def _day(s: str) -> date:
    return date.fromisoformat(s[:10])


def _securities(repo: Path) -> tuple[dict, dict, dict, dict, dict]:
    """The committed run's securities, eras (with observations), CUSIPs, ticker ranges and issuers in force."""
    secs = {r["sec_id"]: r for r in _read(repo / "output/securities.csv")}
    eras: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in _read(repo / "output/observation_map.csv"):
        if r["sec_id"]:
            eras[r["sec_id"]][r["era"]].append([r["ticker"], r["as_of"], r["name"], r["cusip"], r["pin_cik"]])
    cusips: dict[str, list[str]] = defaultdict(list)
    for r in sorted(_read(repo / "output/cusip_history.csv"), key=lambda r: (r["valid_from"], r["cusip"])):
        if r["cusip"] not in cusips[r["sec_id"]]:
            cusips[r["sec_id"]].append(r["cusip"])
    history: dict[str, list[dict]] = defaultdict(list)
    for r in _read(repo / "output/ticker_history.csv"):
        history[r["sec_id"]].append(r)
    inforce: dict[str, set[str]] = defaultdict(set)
    for r in _read(repo / "output/contract/security_history.csv"):
        if r["issuer_id"]:
            inforce[r["sec_id"]].add(r["issuer_id"])
    return secs, eras, cusips, history, inforce


def _line_tickers(eras: dict[str, list], history: list[dict]) -> list[str]:
    """The tickers stage 4b's line follow found (not stored in output/): ticker_history tickers from fails rows
    that the security was never observed under, not OTC-like, running past its last observation."""
    seen = {k.split("@")[0] for k in eras}
    last = max((o[1] for obs in eras.values() for o in obs), default="")
    return sorted({r["ticker"] for r in history if r["ticker"] not in seen and r["source"] == "ftd"
                   and not OTC_LIKE.search(r["ticker"]) and (r["valid_to"] == "" or r["valid_to"] > last)})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "form25_reach")
    p.add_argument("--repo", type=Path, default=ROOT)
    args = p.parse_args(argv)
    repo, out = args.repo, args.out
    secs, eras, cusips, history, inforce = _securities(repo)
    by_cik: dict[str, list[str]] = defaultdict(list)
    for sid, s in secs.items():
        if s["issuer_cik"]:
            by_cik[s["issuer_cik"]].append(sid)
    needed = set(CASES) | {x for sid in CASES for x in by_cik.get(secs[sid]["issuer_cik"], [])}
    others = {sid: int(next(iter(inforce[sid]))) for sid in CASES
              if len(inforce.get(sid, ())) == 1 and next(iter(inforce[sid])) != secs[sid]["issuer_cik"]}
    ciks = sorted({int(secs[sid]["issuer_cik"]) for sid in needed if secs[sid]["issuer_cik"]} | set(others.values())
                  | set(EXTRA_CIKS))

    # fails rows: every row of a case's CUSIPs; a sibling's span and descriptions
    ftd = FtdIndex.opened(LocalFtd(repo / "cache/sec_data/ftd"), *FTD_WINDOW,
                          cusips={c for sid in needed for c in cusips.get(sid, [])} | set(EXTRA_CUSIPS))
    rows = {r for c in EXTRA_CUSIPS for r in ftd.by_cusip(c)}
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

    # EDGAR
    edgar = EdgarClient(repo / "cache/edgar", user_agent="build_form25_fixtures fixtures@example.com", today=AS_OF)
    issuers, raws, texts = {}, {}, {}
    form25_days: dict[int, list[date]] = {}
    for cik in ciks:
        sub = _cached(edgar.submissions, cik, default={}) or {}
        filings = [f for f in _cached(edgar.recent_filings, cik, default=[]) if KEPT_FORMS.match(f.form or "")]
        issuers[str(cik)] = {"name": sub.get("name", ""), "formerNames": sub.get("formerNames") or [],
                             "tickers": sub.get("tickers") or [], "exchanges": sub.get("exchanges") or [],
                             "sic": str(sub.get("sic") or ""),
                             # in EDGAR's own order, which breaks the classifier's ties between filings
                             "filings": [[f.accession, f.form, f.filing_date, f.report_date, f.items, f.primary_doc]
                                         for f in filings]}
        f25 = [f for f in filings if f.form in FORM25_FORMS]
        form25_days[cik] = [_day(f.filing_date) for f in f25]
        for f in f25:
            raw = _cached(edgar.fetch_filing_raw, cik, f.accession, default="")
            if raw:
                raws[f.accession] = raw
        for f in filings:
            if f.form.startswith("8-K") and {"1.03", "3.01"} & f.item_set:
                text = _cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                if text:
                    texts[f.accession] = text
            elif f.form in ANNUAL_FORMS and any(abs((_day(f.filing_date) - d).days) <= COVER_DAYS
                                                for d in form25_days[cik]):
                text = _cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                if text:
                    texts[f.accession] = text[:12000]

    # MIDAS and halts, for every symbol a case's sightings carry
    symbols: dict[str, set[str]] = {}
    windows: dict[str, list[tuple[date, date]]] = {}
    for sid in CASES:
        s = secs[sid]
        own = {k.split("@")[0] for k in eras[sid]} | set(_line_tickers(eras[sid], history[sid]))
        syms = own | {r.symbol for c in cusips.get(sid, []) for r in ftd.by_cusip(c)}
        symbols[sid] = {x for x in syms if x and any(ch.isalpha() for ch in x)}
        days = [d for cik in {int(s["issuer_cik"])} | ({others[sid]} if sid in others else set())
                for d in form25_days.get(cik, [])]
        last = max([o[1] for obs in eras[sid].values() for o in obs]
                   + [r.date for c in cusips.get(sid, []) for r in ftd.by_cusip(c) if r.symbol in own])
        windows[sid] = ([(d - timedelta(days=MIDAS_BEFORE), d + timedelta(days=MIDAS_AFTER)) for d in days]
                        + [(_day(last) - timedelta(days=SEEN_BEFORE), _day(last) + timedelta(days=SEEN_AFTER))])
    midas_dir = repo / "cache/sec_data/midas"
    quarters = sorted(p.name[:7] for p in midas_dir.glob("*_q*.json.gz"))
    midas: dict[str, dict[str, list[str]]] = {}
    for p in sorted(midas_dir.glob("*_q*.json.gz")):
        summary = json.loads(gzip.decompress(p.read_bytes()))
        for sid in CASES:
            for t in symbols[sid]:
                for d in summary.get(t, []):
                    if any(lo <= _day(d) <= hi for lo, hi in windows[sid]):
                        midas.setdefault(p.name[:7], {}).setdefault(t, []).append(d)
    halts: dict[str, list[list[str]]] = {}
    wanted = {t for v in symbols.values() for t in v}
    for p in sorted((repo / "cache/nasdaq_halts").glob("*.xml")):
        for h in _cached(parse_halts_rss, p.read_bytes(), default=[]):
            if h.reason == "D" and h.symbol in wanted:
                halts.setdefault(p.stem, []).append([h.symbol, h.name, h.market, h.reason, h.halt_date.isoformat(),
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
                           "cusips": cusips.get(sid, []), "line_tickers": _line_tickers(eras[sid], history[sid]),
                           "listed": any(r["valid_to"] == "" for r in history.get(sid, [])),
                           "eras": {k: sorted(v, key=lambda o: o[1]) for k, v in sorted(eras[sid].items())}}
    cases = {sid: {"note": note, "other_cik": others.get(sid)} for sid, note in CASES.items()}
    json_out = {"as_of": AS_OF.isoformat(), "ftd_from": FTD_WINDOW[0].isoformat(), "cases": cases,
                "securities": securities}
    for name, data in (("cases.json", json_out),
                       ("midas.json", {"quarters": quarters, "days": midas}),
                       ("halts.json", halts)):
        write_atomic(out / name, json.dumps(data, indent=1, sort_keys=True) + "\n")
    edgar_json = json.dumps({"issuers": issuers, "raws": raws, "texts": texts}, sort_keys=True) + "\n"
    write_atomic(out / "edgar.json.gz", gzip.compress(edgar_json.encode(), mtime=0))
    print(f"{len(cases)} cases, {len(securities)} securities, {len(rows)} fails rows, {len(ciks)} CIKs, "
          f"{len(raws)} Form 25 raws, {len(texts)} texts, {sum(len(v) for q in midas.values() for v in q.values())} "
          f"MIDAS days, {sum(len(v) for v in halts.values())} halts -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

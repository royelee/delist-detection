"""SEC evidence for one delisting diagnosis, through the library's own cached, rate-limited client.

Run from the repo root:

    DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock \
    PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python .claude/skills/diagnose-delisting/sec.py <command> ...

Commands (every SEC answer is read from cache/edgar first and cached when fetched):

    filings CIK [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--forms 8-K,25-NSE,...]
        the issuer's filings: date, form, accession, 8-K items, primary document, URL
    grep CIK ACCESSION PATTERN [--context 300] [--max 8] [--all]
        snippets matching a regex: the primary document first, every document (exhibits, a Form 25's
        EX-99.25 notice) when it has no match or with --all
    text CIK ACCESSION [--chars 6000]
        the start of the primary document as plain text
    search "QUOTED PHRASE" [--forms 8-K12B,8-K] [--from ...] [--to ...] [--cik N]
        EDGAR full-text search (2001+ text is indexed from 2001; hits: form, date, CIKs, accession)
    fails [--cusip C] [--symbol S] [--name WORDS] --from YYYYMM --to YYYYMM
        cached SEC fails-to-deliver rows grouped by (CUSIP, symbol, description): first/last day and price.
        Offline only (cache/sec_data/ftd). A row dated D carries D-1's close. Not an exchange print.

Network hosts a live fetch needs: data.sec.gov, www.sec.gov, efts.sec.gov.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

from delist_detection.edgar import EdgarClient
from delist_detection.html_text import strip_html
from delist_detection.sec_limiter import use_machine_wide_limit

FTD_DIR = Path("cache/sec_data/ftd")


def _client() -> EdgarClient:
    use_machine_wide_limit(os.environ.get("DELIST_DETECTION_SEC_RATE_LOCK"))
    return EdgarClient("cache/edgar")


def _url(cik: int, accession: str, doc: str = "") -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{doc}"


def cmd_filings(a) -> None:
    forms = {f.strip() for f in a.forms.split(",")} if a.forms else None
    rows = sorted(_client().recent_filings(a.cik), key=lambda f: f.filing_date)
    for f in rows:
        if a.from_ and f.filing_date < a.from_ or a.to and f.filing_date > a.to:
            continue
        if forms and f.form not in forms:
            continue
        items = f" items={f.items}" if f.items else ""
        print(f"{f.filing_date} {f.form:9s} {f.accession}{items}  {_url(a.cik, f.accession, f.primary_doc)}")


def cmd_grep(a) -> None:
    """The primary document first (usually cached as text); the whole submission (exhibits, a Form 25's
    EX-99.25 notice) when it has no match or --all is given."""
    edgar = _client()
    flat, where = "", ""
    if not a.all:
        sub = next((f for f in edgar.recent_filings(a.cik) if f.accession == a.accession), None)
        if sub is not None and sub.primary_doc:
            flat = re.sub(r"\s+", " ", edgar.fetch_filing_text(a.cik, a.accession, sub.primary_doc) or "")
            where = _url(a.cik, a.accession, sub.primary_doc)
    hits = list(re.finditer(a.pattern, flat, re.I)) if flat else []
    if not hits:
        raw = edgar.fetch_filing_raw(a.cik, a.accession)
        if not raw:
            print("(no text: not found, or the request failed)")
            return
        flat, where = re.sub(r"\s+", " ", strip_html(raw)), _url(a.cik, a.accession) + " (all documents)"
        hits = list(re.finditer(a.pattern, flat, re.I))
    print(f"{len(hits)} match(es) in {where}")
    for m in hits[: a.max]:
        lo, hi = max(0, m.start() - a.context), min(len(flat), m.end() + a.context)
        print("...", flat[lo:hi], "...\n")


def cmd_text(a) -> None:
    edgar = _client()
    sub = next((f for f in edgar.recent_filings(a.cik) if f.accession == a.accession), None)
    if sub is None or not sub.primary_doc:
        raw = edgar.fetch_filing_raw(a.cik, a.accession)
        print(re.sub(r"\s+", " ", strip_html(raw))[: a.chars] if raw else "(no text)")
        return
    text = edgar.fetch_filing_text(a.cik, a.accession, sub.primary_doc)
    print(_url(a.cik, a.accession, sub.primary_doc))
    print(re.sub(r"\s+", " ", text or "")[: a.chars] or "(no text)")


def cmd_search(a) -> None:
    lo = date.fromisoformat(a.from_) if a.from_ else date(2001, 1, 1)
    hi = date.fromisoformat(a.to) if a.to else date.today()
    ciks = [a.cik] if a.cik else ()
    hits = _client().full_text_search(a.query, a.forms, lo, hi, ciks=ciks)
    print(f"{len(hits)} hit(s)")
    for h in hits[:40]:
        s = h.get("_source", h)
        print(s.get("file_date"), s.get("form"), s.get("adsh"), "ciks=" + ",".join(s.get("ciks") or []),
              "|", ";".join(s.get("display_names") or [])[:120])


def cmd_fails(a) -> None:
    seen = defaultdict(list)
    name = a.name.upper() if a.name else None
    files = sorted(FTD_DIR.glob("cnsfails*.zip")) + sorted(FTD_DIR.glob("cnsp_sec_fails_*.zip"))
    for p in files:
        half = re.search(r"cnsfails(\d{6})", p.name)            # half-month files, 2009 on: cnsfailsYYYYMMa
        quarter = re.search(r"(\d{4})q(\d)", p.name)            # quarterly files, 2004-2008: cnsp_sec_fails_YYYYqN
        if half and not (a.from_ <= half.group(1) <= a.to):
            continue
        if quarter and not (a.from_[:4] <= quarter.group(1) <= a.to[:4]):
            continue
        if not half and not quarter:
            continue
        with zipfile.ZipFile(p) as z:
            for member in z.namelist():
                for line in io.TextIOWrapper(z.open(member), encoding="latin-1"):
                    q = line.rstrip("\n").split("|")
                    if len(q) < 6 or not q[0][:1].isdigit():
                        continue
                    cusip, sym, desc = q[1].strip().upper(), q[2].strip().upper(), q[4].strip().upper()
                    if (a.cusip and cusip == a.cusip.upper()) or (a.symbol and sym == a.symbol.upper()) \
                            or (name and name in desc):
                        seen[(cusip, sym, desc)].append((q[0], q[5].strip()))
    for (cusip, sym, desc), rows in sorted(seen.items(), key=lambda kv: min(r[0] for r in kv[1])):
        rows.sort()
        print(f"{cusip} {sym:8s} {desc[:42]:42s} {len(rows):4d} rows {rows[0][0]}..{rows[-1][0]} "
              f"first ${rows[0][1]} last ${rows[-1][1]}")
    if not seen:
        print("(no rows)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("filings")
    p.add_argument("cik", type=int)
    p.add_argument("--from", dest="from_")
    p.add_argument("--to")
    p.add_argument("--forms")
    p.set_defaults(fn=cmd_filings)
    p = sp.add_parser("grep")
    p.add_argument("cik", type=int)
    p.add_argument("accession")
    p.add_argument("pattern")
    p.add_argument("--context", type=int, default=300)
    p.add_argument("--max", type=int, default=8)
    p.add_argument("--all", action="store_true", help="search every document of the submission")
    p.set_defaults(fn=cmd_grep)
    p = sp.add_parser("text")
    p.add_argument("cik", type=int)
    p.add_argument("accession")
    p.add_argument("--chars", type=int, default=6000)
    p.set_defaults(fn=cmd_text)
    p = sp.add_parser("search")
    p.add_argument("query")
    p.add_argument("--forms", default="8-K,8-K12B,8-K12G3,25-NSE,25,DEFM14A,425,S-4")
    p.add_argument("--from", dest="from_")
    p.add_argument("--to")
    p.add_argument("--cik", type=int)
    p.set_defaults(fn=cmd_search)
    p = sp.add_parser("fails")
    p.add_argument("--cusip")
    p.add_argument("--symbol")
    p.add_argument("--name")
    p.add_argument("--from", dest="from_", required=True)
    p.add_argument("--to", required=True)
    p.set_defaults(fn=cmd_fails)
    a = ap.parse_args(argv)
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())

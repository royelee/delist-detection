"""Build tests/fixtures/identity/ from the local caches, once (sub-plan 5h): the real cases whose eras, issuer
checks (stage 2b) and FIGIs (stage 3) tests/test_identity_cases.py replays offline through the run's own code
(tests/identity_cases.py).

  PYTHONPATH=src python scripts/build_identity_fixtures.py          # -> tests/fixtures/identity/

Offline, as scripts/build_form25_fixtures.py (whose helpers it reuses; every SEC request is refused): it reads the
committed output/observation_map.csv (each era's issuer), data/observations.csv, the cached fails zips, EDGAR
submissions, OpenFIGI answers and SEC's name index, and runs the harness's stages over them with recording doubles.
It writes:

- cases.json: the observations of the cases' tickers, each era's committed issuer, and the name-index entries the
  checks read;
- ftd_rows.csv.gz: every fails row stage 1 loads for those tickers, and every row of `HISTORY_CUSIPS` (the MSG
  history case: the old line's MSGZZZZ settle rows);
- edgar.json.gz: each CIK's EDGAR names, tickers and first filing, as the code read them;
- figi.json: every OpenFIGI mapping job and filter query stage 3 sends, with the cached answer (an uncached one is
  an error answer).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import build_form25_fixtures as b5  # noqa: E402  (refuses every SEC request on import)
import identity_cases as ic  # noqa: E402
from delist_detection.sources.atomic_io import write_atomic  # noqa: E402
from delist_detection.sources.cik_lookup import CikLookupClient  # noqa: E402
from delist_detection.sources.edgar import EdgarClient  # noqa: E402
from delist_detection.identity.observations import Observation  # noqa: E402
from delist_detection.sources.openfigi import OpenFigiClient  # noqa: E402

# offline: an OpenFIGI job the cache lacks is an error answer, never a request
OpenFigiClient._post = lambda self, path, payload: ([{"error": "offline"} for _ in payload] if path == "/mapping"
                                                    else {"data": []})


class RecordingFtd:
    def __init__(self, inner) -> None:
        self.inner, self.rows_seen = inner, set()

    def urls_for(self, lo, hi):
        return self.inner.urls_for(lo, hi)

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self.inner.rows(url, symbols=symbols, cusips=cusips):
            self.rows_seen.add(r)
            yield r


class RecordingEdgar:
    def __init__(self, inner: EdgarClient) -> None:
        self.inner, self.issuers = inner, {}

    def _record(self, cik: int) -> None:
        key = str(int(cik))
        if key in self.issuers:
            return
        sub = b5._cached(self.inner.submissions, cik, default=None)
        if not isinstance(sub, dict) or not sub.get("name"):
            return
        filings = b5._cached(self.inner.recent_filings, cik, default=[]) or []
        first = min((f for f in filings if f.filing_date), key=lambda f: f.filing_date, default=None)
        self.issuers[key] = {"name": sub.get("name", ""), "formerNames": sub.get("formerNames") or [],
                             "tickers": sub.get("tickers") or [], "exchanges": sub.get("exchanges") or [],
                             "filings": [[first.accession, first.form, first.filing_date, first.report_date,
                                          first.items, first.primary_doc]] if first else []}

    def submissions(self, cik, fresh_after=None):
        self._record(cik)
        return ic.FixtureEdgar(self.issuers).submissions(cik)

    def recent_filings(self, cik):
        self._record(cik)
        return ic.FixtureEdgar(self.issuers).recent_filings(cik)

    def company_tickers(self):
        return {}


KEYS = ("figi", "compositeFIGI", "name", "ticker", "exchCode", "securityType", "securityType2", "marketSector",
        "securityDescription")


def _thin(rows: list[dict]) -> list[dict]:
    """The US venues' rows, one per (composite, ticker), the US composite row first (as `us_candidates` picks
    its representative), with the fields the resolver reads."""
    us = sorted((r for r in rows if r.get("exchCode") in b5_us()), key=lambda r: r.get("exchCode") != "US")
    seen, out = set(), []
    for r in us:
        k = (r.get("compositeFIGI"), r.get("ticker"))
        if k not in seen:
            seen.add(k)
            out.append({x: r[x] for x in KEYS if x in r})
    return out


class RecordingFigi:
    def __init__(self, inner: OpenFigiClient) -> None:
        self.inner, self.maps, self.filters = inner, {}, {}

    def map(self, jobs):
        out = []
        for job in jobs:
            try:
                ans = self.inner.map([job])[0]
            except Exception:  # noqa: BLE001 -- not cached: an error answer, as offline
                ans = {"error": "not cached"}
            if "error" not in ans:
                ans = {"data": _thin(ans.get("data") or [])}
            self.maps[ic.job_key(job)] = ans
            out.append(ans)
        return out

    def filter(self, query, **fields):
        try:
            rows = self.inner.filter(query, **fields)
        except Exception:  # noqa: BLE001
            rows = []
        rows = _thin(rows)
        self.filters[ic.job_key({"query": query, **fields})] = rows
        return rows


def b5_us():
    from delist_detection.identity.figi_resolution import US_EXCH
    return US_EXCH


class RecordingIndex:
    def __init__(self, inner) -> None:
        self.inner, self.entries = inner, set()

    def split_search(self, query):
        exact, prefix = self.inner.split_search(query)
        self.entries.update((h.name, h.cik) for h in exact)
        return exact, prefix

    def search(self, query):
        return self.inner.search(query)

    def __call__(self):              # the resolver takes an index, or a callable that loads one
        return self


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "identity")
    p.add_argument("--repo", type=Path, default=ROOT)
    args = p.parse_args(argv)
    repo, out = args.repo, args.out

    eras_issuer: dict[str, int] = {}
    for r in b5._read(repo / "output/observation_map.csv"):
        if r["issuer_cik"]:
            eras_issuer.setdefault(r["era"], int(r["issuer_cik"]))
    stage3 = {k for k, c in eras_issuer.items() if c in ic.STAGE3_CIKS}
    tickers = {k.split("@")[0] for k in stage3} | {k.split("@")[0] for k in ic.NAME_CASES}
    observations = [[r["ticker"], r["as_of"], r["name"], r["cik"]] for r in b5._read(repo / "data/observations.csv")
                    if r["ticker"] in tickers]
    keep = {k: c for k, c in eras_issuer.items() if k.split("@")[0] in tickers}

    ftd = RecordingFtd(b5.LocalFtd(repo / "cache/sec_data/ftd"))
    edgar = RecordingEdgar(EdgarClient(repo / "cache/edgar", user_agent="build_identity_fixtures fx@example.com",
                                       today=ic.AS_OF))
    figi = RecordingFigi(OpenFigiClient(repo / "cache/openfigi", "offline-key", sleep=lambda s: None))
    index = RecordingIndex(CikLookupClient(repo / "cache/sec_data/cik_lookup").index())
    backend = ic.Backend([Observation(t, d, n or None, None, int(c) if c else None) for t, d, n, c in observations],
                         keep, ftd, edgar, figi, index)
    cases = ic.Cases(backend)
    cases.stage3()
    cases.name_checks()
    for cusip, lo, hi in ic.HISTORY_CUSIPS:      # the history cases: every row of a CUSIP in its window
        for url in ftd.urls_for(date.fromisoformat(lo), date.fromisoformat(hi)):
            for _ in ftd.rows(url, cusips={cusip}):
                pass
    for _, (_, cik) in ic.NAME_CASES.items():
        edgar.submissions(cik)

    out.mkdir(parents=True, exist_ok=True)
    write_atomic(out / "cases.json", json.dumps({
        "as_of": ic.AS_OF.isoformat(), "observations": observations, "eras_issuer": keep,
        "index": sorted([n, c] for n, c in index.entries)}, indent=1, sort_keys=True))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "cusip", "symbol", "description", "price"])
    for r in sorted(ftd.rows_seen, key=lambda r: (r.date, r.cusip, r.symbol)):
        w.writerow([r.date, r.cusip, r.symbol, r.description, "" if r.price is None else repr(r.price)])
    write_atomic(out / "ftd_rows.csv.gz", gzip.compress(buf.getvalue().encode(), mtime=0))
    write_atomic(out / "edgar.json.gz", gzip.compress(json.dumps(edgar.issuers, sort_keys=True).encode(), mtime=0))
    write_atomic(out / "figi.json", json.dumps({"map": figi.maps, "filter": figi.filters}, indent=1,
                                               sort_keys=True))
    print(f"{len(observations)} observations, {len(keep)} eras, {len(ftd.rows_seen)} fails rows, "
          f"{len(edgar.issuers)} CIKs, {len(figi.maps)} OpenFIGI jobs, {len(figi.filters)} filters, "
          f"{len(index.entries)} index entries -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

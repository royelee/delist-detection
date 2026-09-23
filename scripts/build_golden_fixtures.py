"""Capture the golden cases from live EDGAR into tests/fixtures/golden/ (NETWORK).

Run from the repo root as `PYTHONPATH=src python scripts/build_golden_fixtures.py`.

For each row of data/golden_events.csv this stores everything the resolver,
classifier and payout reader read for that case, so tests replay it offline:
submissions (trimmed to -1650/+400 days) for the true CIK, the wrong CIK and
every candidate CIK a resolver tier can return, the company_tickers row,
company_search_atom hits for every name variant the resolver issues, the raw
answers to the two EFTS queries the resolver issues (`efts_raw`, keyed by URL,
which tests/golden.py serves back to the real EFTS methods), and the text of
every 8-K carrying items 1.03/2.01/3.01/5.01 plus the closing/announcement
filings the payout reader would open. `efts_lookup` and `efts_frequency` are
the resolver's answers at capture time, kept for reading only.
Re-run after changing data/golden_events.csv. `--efts-only` re-captures just
`efts_raw` into the existing fixtures and leaves every other key untouched.

With OPENAI_API_KEY set (environment or the repo .env), each merger case also
stores `llm_terms` (the LLM merger terms for the classified record, read
through cache/llm) and `acquirer_price` (the acquirer's close on
observed_delist_date itself, read from the fails-to-deliver row dated the
next trading day via FtdIndex.close_after). Without it, a full run skips
that capture and keeps the terms an earlier run captured. `--llm-only`
re-captures just those two keys into the existing fixtures and needs
OPENAI_API_KEY.
`--only ID` (repeatable, ID = TICKER_DATE) limits any run to the named cases.

Submissions are re-fetched, not read from cache/: a cached copy older than the
event would hide its Form 25. company_tickers.json is read from cache/ on
purpose: it is the 2026-05-26 map the 2026-09-16 evidence run used, and SEC's
current map has already dropped LC, SKLZ, TWO, BLD, LBRDA and LBRDK.
A refusal or a failed request aborts the run instead of becoming "no match".
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import dotenv_values

from delist_detection.classifier import DelistClassifier
from delist_detection.edgar import SEC_HOST, EdgarClient
from delist_detection.filing_selection import announcement_8k, closing_8k, form_filings
from delist_detection.ftd import FtdClient, FtdIndex
from delist_detection.llm_client import default_llm_client
from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor
from delist_detection.ticker_resolver import TickerResolver

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "golden"
TEXT_ITEMS = {"1.03", "2.01", "3.01", "5.01"}
# A frozen vendor tail can end up to 1,500 days after its Form 25, and the
# classifier backscans 120 days before that Form 25 for the anchor 8-K.
BEFORE_DAYS, AFTER_DAYS = 1650, 400
ANY_DISTANCE_FORMS = {"25", "25-NSE", "15-12G", "15-12B", "15-15D", "REVOKED"}
EFTS_PREFIX = "https://efts.sec.gov/"
# The resolver reads ciks and display_names; form, file_date and adsh make a fixture readable.
EFTS_SOURCE_KEYS = ("ciks", "display_names", "form", "file_date", "adsh")
LLM_KEYS = ("llm_terms", "acquirer_price")
_efts_raw: dict[str, dict] = {}


def _strict(get):
    """The library turns any failed request into "no match". Here a 403/429
    aborts the run, and any other failure is retried, then aborts, so a
    transient error is never captured as a fixture."""
    def wrapped(*args, **kwargs):
        url = args[0] if args else kwargs.get("url")
        problem = ""
        for attempt in range(3):
            try:
                resp = get(*args, **kwargs)
            except requests.RequestException as exc:
                problem = repr(exc)
            else:
                if resp.status_code in (403, 429):
                    raise SystemExit(f"BLOCKED: SEC answered HTTP {resp.status_code} for {url}")
                if resp.status_code in (200, 404):
                    return resp
                problem = f"HTTP {resp.status_code}"
            time.sleep(2 ** attempt)
        raise SystemExit(f"FAILED: {problem} for {url}")
    return wrapped


def _recording(get):
    """Keep every EFTS answer, keyed by URL and trimmed to EFTS_SOURCE_KEYS."""
    def wrapped(*args, **kwargs):
        resp = get(*args, **kwargs)
        url = args[0] if args else kwargs.get("url")
        if url.startswith(EFTS_PREFIX) and resp.status_code == 200:
            hits = resp.json().get("hits", {})
            _efts_raw[url] = {"hits": {"total": hits.get("total"), "hits": [
                {"_source": {k: h["_source"][k] for k in EFTS_SOURCE_KEYS if k in h.get("_source", {})}}
                for h in hits.get("hits", [])]}}
        return resp
    return wrapped


def _resolver(edgar, row) -> TickerResolver:
    return TickerResolver(edgar, member_names=lambda *_a, _n=row["member_name"], **_k: _n)


def _capture_efts(resolver: TickerResolver, t: str, d: str) -> tuple[dict, list, list]:
    """Issue both EFTS queries for (t, d): (efts_raw, efts_lookup, efts_frequency)."""
    _efts_raw.clear()
    lookup = list(resolver._efts_lookup(t, d, expected_name=resolver._expected_name(t, d)))
    frequency = [list(x) for x in resolver._efts_pre_delist_frequency_ranked(t, d)]
    return dict(_efts_raw), lookup, frequency


def _refresh_efts(rows) -> None:
    """Add efts_raw to the existing fixtures; nothing else is fetched or changed."""
    for row in rows:
        t, d = row["ticker"], row["observed_delist_date"]
        path = OUT / f"{t}_{d}.json"
        case = json.loads(path.read_text())
        case["efts_raw"], _, _ = _capture_efts(_resolver(None, row), t, d)
        path.write_text(json.dumps(case, indent=1))
        print(f"{t} {d}: {len(case['efts_raw'])} EFTS answers")


def _openai_key_set() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY") or dotenv_values(ROOT / ".env").get("OPENAI_API_KEY"))


def _acquirer_price(acquirer: str | None, on: date) -> float | None:
    """The acquirer's close on `on` itself -- read from the SEC fails-to-deliver
    row dated the next trading day (FtdIndex.close_after). None without an
    acquirer ticker or a priced row."""
    if not acquirer:
        return None
    ftd = FtdIndex.load(FtdClient(ROOT / "cache" / "sec_data" / "ftd"),
                        on - timedelta(days=10), on + timedelta(days=10),
                        symbols={acquirer})
    close = ftd.close_after(on, symbol=acquirer)
    return close[0] if close else None


def _capture_llm(edgar, llm, row) -> dict:
    """The LLM_KEYS for a merger case, read for the record the classifier returns."""
    t, d = row["ticker"], row["observed_delist_date"]
    rec = DelistClassifier(edgar, _resolver(edgar, row)).classify_ticker(t, d)
    if rec.bucket.value != "merger" or rec.cik != int(row["cik"]):
        raise SystemExit(f"FAILED: {t} {d} classified as {rec.bucket.value} CIK {rec.cik}, "
                         f"expected merger CIK {row['cik']}")
    terms = llm.extract(rec)
    price = _acquirer_price(terms.acquirer_ticker, date.fromisoformat(d)) if terms else None
    shown = "none" if terms is None else (
        f"{terms.deal_type} cash={terms.cash_per_share} ratio={terms.stock_ratio} "
        f"acquirer={terms.acquirer_ticker} ({terms.source})")
    print(f"{t} {d}: llm_terms {shown}; acquirer_price {price}")
    return {"llm_terms": asdict(terms) if terms else None, "acquirer_price": price}


def _near_event(filings, on: date):
    """The filings within [-BEFORE_DAYS, +AFTER_DAYS] of `on`.

    A filing with an empty filingDate is skipped, as in `_trim`: EDGAR emits a
    few, and `date.fromisoformat("")` used to abort a capture after all the
    network work was already spent.
    """
    out = []
    for f in filings:
        if not f.filing_date:
            continue
        if -BEFORE_DAYS <= (date.fromisoformat(f.filing_date) - on).days <= AFTER_DAYS:
            out.append(f)
    return out


def _trim(sub: dict, filings, on: date) -> dict:
    """Name history + the filings near the event. `filings` must come from
    edgar.recent_filings(), which also walks the older paginated chunks — an
    event before ~2015 is usually not in submissions["filings"]["recent"]."""
    lo = (on - timedelta(days=BEFORE_DAYS)).isoformat()
    hi = (on + timedelta(days=AFTER_DAYS)).isoformat()
    earliest = min((f.filing_date for f in filings if f.filing_date), default="")
    # keep the earliest filing too (the resolver's date check reads it), and every
    # delisting/deregistration/revocation form (the classifier reads them at any distance)
    near = [f for f in filings if lo <= f.filing_date <= hi
            or f.filing_date == earliest or f.form in ANY_DISTANCE_FORMS]
    return {
        "name": sub.get("name"), "sic": sub.get("sic"), "tickers": sub.get("tickers"),
        "formerNames": sub.get("formerNames", []),
        "filings": {"recent": {
            "accessionNumber": [f.accession for f in near], "form": [f.form for f in near],
            "filingDate": [f.filing_date for f in near], "reportDate": [f.report_date for f in near],
            "items": [f.items for f in near], "primaryDocument": [f.primary_doc for f in near],
        }},
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Capture the golden cases from live EDGAR (NETWORK).")
    p.add_argument("--efts-only", action="store_true",
                   help="only re-capture efts_raw into the existing fixtures")
    p.add_argument("--llm-only", action="store_true",
                   help="only re-capture llm_terms and acquirer_price into the existing fixtures")
    p.add_argument("--only", action="append", metavar="ID",
                   help="capture only this case (TICKER_DATE, e.g. BLD_2026-07-01); repeatable")
    args = p.parse_args()
    requests.get = _recording(_strict(requests.get))   # EFTS calls in ticker_resolver
    rows = list(csv.DictReader((ROOT / "data" / "golden_events.csv").open()))
    if args.only:
        rows = [r for r in rows if f"{r['ticker']}_{r['observed_delist_date']}" in args.only]
        if len(rows) != len(set(args.only)):
            p.error(f"--only names a case that is not in data/golden_events.csv: {args.only}")
    if args.efts_only:
        _refresh_efts(rows)
        return
    edgar = EdgarClient(cache_dir=ROOT / "cache" / "edgar")
    edgar.session.get = _strict(edgar.session.get)
    llm = None
    if _openai_key_set():
        llm = LLMMergerTermsExtractor(edgar, default_llm_client(), cache_dir=ROOT / "cache" / "llm")
    elif args.llm_only:
        p.error("--llm-only needs OPENAI_API_KEY")
    else:
        print("notice: LLM terms not captured (needs OPENAI_API_KEY); existing ones are kept")
    if args.llm_only:
        for row in rows:
            if row["expected_bucket"] != "merger":
                continue
            path = OUT / f"{row['ticker']}_{row['observed_delist_date']}.json"
            case = json.loads(path.read_text())
            case.update(_capture_llm(edgar, llm, row))
            path.write_text(json.dumps(case, indent=1))
        return
    companies = edgar.company_tickers()
    (OUT / "text").mkdir(parents=True, exist_ok=True)
    refreshed: set[int] = set()
    for row in rows:
        t, d = row["ticker"], row["observed_delist_date"]
        on = date.fromisoformat(d)
        resolver = _resolver(edgar, row)
        atom = {}
        for v in TickerResolver._name_variants(row["member_name"]):
            for form in ("25-NSE", "25", "15-12G", ""):
                atom[f"{v}|{form}"] = edgar.company_search_atom(v, form_type=form)
        efts_raw, efts_lookup, efts_frequency = _capture_efts(resolver, t, d)

        text_ciks = {int(row["cik"])} | ({int(row["wrong_cik"])} if row.get("wrong_cik") else set())
        # every CIK a resolver tier can return is validated against its filings
        candidates = {int(h["cik"]) for hits in atom.values() for h in hits}
        candidates |= {int(c) for c, _ in efts_frequency}
        candidates |= {int(efts_lookup[0])} if efts_lookup[0] is not None else set()   # hit or fallback
        candidates |= {int(companies[t]["cik_str"])} if t in companies else set()
        candidates -= TickerResolver.EXCHANGE_CIKS

        subs, texts = {}, {}
        for cik in sorted(text_ciks | candidates):
            if cik not in refreshed:
                edgar._get_json(f"{SEC_HOST}/submissions/CIK{str(cik).zfill(10)}.json", refresh=True)
                refreshed.add(cik)
            sub = edgar.submissions(cik)
            all_filings = edgar.recent_filings(cik)
            subs[str(cik)] = _trim(sub, all_filings, on)
            if cik not in text_ciks:
                continue
            filings = _near_event(all_filings, on)
            wanted = [f for f in filings if f.form.startswith("8-K") and f.item_set & TEXT_ITEMS]
            wanted += closing_8k(filings, on)[:2] + announcement_8k(filings, on)[:2]
            wanted += form_filings(filings, "DEFM14A", on)[:1]
            for f in wanted:
                key = f"{cik}_{f.accession}"
                if key not in texts:
                    txt = edgar.fetch_filing_text(cik, f.accession, f.primary_doc)
                    (OUT / "text" / f"{key}.txt").write_text(txt, encoding="utf-8")
                    texts[key] = True
        case = {
            "row": row,
            "company_tickers": {t: companies[t]} if t in companies else {},
            "submissions": subs,
            "atom": atom,
            "efts_lookup": efts_lookup,
            "efts_frequency": efts_frequency,
            "efts_raw": efts_raw,
        }
        path = OUT / f"{t}_{d}.json"
        if llm is not None and row["expected_bucket"] == "merger":
            case.update(_capture_llm(edgar, llm, row))
        elif path.exists():   # keep the terms an earlier run captured
            old = json.loads(path.read_text())
            case.update({k: old[k] for k in LLM_KEYS if k in old})
        path.write_text(json.dumps(case, indent=1))
        print(f"{t} {d}: {len(subs)} companies, {len(texts)} texts")


if __name__ == "__main__":
    main()

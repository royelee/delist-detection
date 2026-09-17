# Classify Delistings Right the First Time — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The classifier and the DLRET table produce the right bucket and return for every error class found on 2026-09-16 without hand-written overrides, and flag each row they cannot settle.

**Architecture:** Five changes, each driven by real cases stored as offline fixtures:
1. An SEC refusal becomes an error instead of "no match".
2. Company matching checks the name a company had on the delist date against a caller-supplied index-member name.
3. A distress bucket needs positive evidence. Renames, takeovers without item 2.01, SPAC trust liquidations and earlier bankruptcies are recognized.
4. The payout reader handles whole-dollar amounts, preferred redemptions, award payouts and election deals, and every payout is checked against the last close.
5. The table gains a `review_flags` column.

**Tech Stack:** Python ≥ 3.10, pytest (offline), requests, pandas. Run everything under `conda run -n rdagent4qlib` from the repo root.

**Spec:** this plan's "Evidence" section. Source reports in the companion repo:
- `qlib_practice/docs/validation/2026-09-16_panel_full_feature_panel.delist.parquet.md` (F7, F8, F9)
- `qlib_practice/fetch_data_aplha/data/dlret_overrides.csv`, the 10 hand corrections this plan should make unnecessary

Companion plan in qlib_practice: `docs/superpowers/plans/2026-09-16-dlret-and-member-identity.md` (member-names export, build-dlret wiring, stage-1 identity check).

## Global Constraints

- Tests stay offline: `FakeEdgar`-style fakes and committed fixtures. The network is used only by `scripts/build_golden_fixtures.py` and the acceptance run (Task 13).
- SEC fair access is unchanged: at most 8 requests/s, User-Agent from `EDGAR_USER_AGENT` (`edgar.resolve_user_agent()`).
- `output/dlret.csv` keeps every existing column name and order. Exactly one column is appended: `review_flags` (semicolon-separated, empty when clean).
- No new `CrspBucket` member and no change to `DLST_CODE_TO_BUCKET`.
- The consumer (qlib_practice) writes −1.00 for every `compliance_failure` row and −0.90 for every `liquidation` row, whatever `dlret` says. A distress bucket is therefore a −100%/−90% training label and must rest on positive evidence: item 1.03 confirmed by text, item 2.04 without a change in control, NT 10-K/10-Q, SEC revocation, or a 3.01 notice citing a listing deficiency.
- The DLRET row describes the security whose prices the caller supplied: the vendor series ending on `observed_delist_date`. A member name is a check, never a substitute. If the company that delisted on that date is not the named member, emit that company's classification with the flag `member_name_mismatch`.
- `MANUAL_OVERRIDES` stays authoritative, and so does the rule "extend it instead of patching the resolver when web verification proves a wrong CIK". This plan fixes classes of error, not single tickers.

---

## Evidence (2026-09-16, qlib universe `tiingo_2026_09_11`, 495 delisted tickers, library `5e53294`)

**The 10 rows corrected by hand.** Each was checked against EDGAR.

| Ticker | Classifier output | Truth | Failing rule |
|---|---|---|---|
| HYH | liquidation (CIK 829281 "Lehman Abs Corp") | Halyard Health → Avanos (1606498), rename July 2018 | name tier used AV's wrong name; no rename check |
| PEAK | compliance 570 (1829426 Far Peak Acquisition) | Healthpeak (765880), 2-session stub | EFTS second pass: "first non-exchange CIK" |
| LC | compliance 570 | LendingClub → Happen (HAPN), NYSE → Nasdaq | "3.01 alone → 570"; 3.01 text says "transfer the listing" |
| SKLZ | compliance 570 (anchor Form 25 from 2021-08-16) | Skillz → Firy (FIRY) | Form 25 picked at any distance; no rename check |
| SPWR | exchange_transfer (1838987, named Complete Solaria on the date) | SunPower Corp (867773), 1.03 on 2024-08-06 | company_tickers accepted with no date check |
| OAS | exchange_transfer | 1.03 on 2020-09-30; old equity cancelled | "continued filings" runs before bankruptcy |
| VRTV | merger, payout $1.00 | $170 cash | regex needs cents; "$1.00 multiplied by … PBU award" matched |
| TWO | merger, payout $25.00 | $12.00 cash | preferred redemption "$25.00 in cash" tied 1–1; tie-break takes the larger value |
| BLD | merger, payout $505 | $505 cash **or** 20.2 QXO, prorated; post-deadline shares got stock | election ("or (ii) 20.200 shares") not seen as mixed |
| CPWR | exchange_transfer (827099 Ocean Thermal) | Compuware (859014), $10.389188 cash | company_tickers accepted with no date check |

**Distress marks on normal prices.** 41 of the 60 compliance/liquidation rows have a last close ≥ $5. By rule:

| Rule that fired | Rows ≥ $5 | Examples |
|---|---|---|
| "3.01 alone → 570" (+ NT → 580) | 19 | BCR, ROH, MHS, PBG, HNZ, XTO, ATHL, AYE, GXP, IRF, JAH, KCI, CXG, FWLT, BPYU (items 3.01 + 3.03 + 5.01, no 2.01) |
| "Form 25 + Form 15, no merger 8-K → 400" | 15 | SIAL, KING, UTIW (items 1.01, 2.01, 9.01), AMSG, EVHC, FCE-A, TEG, NSR, VMED, BRL, AABA; SPACs FST, LEAP |
| "3.01 + 2.04 → 470" or "1.03 → 470" beating M&A | 4 | ONXX, SLXP, FTO (all carry 5.01), VSTO (1.03 tag + 2.01 + 5.01) |
| "8-K without conclusive items → 570" | 3 | SKLZ, LBRDA, LBRDK (anchor Form 25s 1,767 and 4,242 days old) |

**Name checks.**
- EDGAR company search on the iShares member name returns the right CIK for HALYARD HEALTH (1606498), SUNPOWER CORP (867773), COMPUWARE (859014) and HEALTHPEAK PROPERTIES (765880).
- `formerNames` carries `from`/`to` dates. On 2024-08-20, CIK 1838987 was "Complete Solaria, Inc.".
- SIC `6770` ("Blank Checks") marks most SPACs. Far Peak is filed under 6199, so "Acquisition Corp" in the name at the date is the second signal.
- For FST, BWC, HMA, LEAP, CHAP, HCR, HLTH and IMCL, the vendor series belongs to a different company than the member (Forest Oil, Babcock & Wilcox, Health Management Associates, Leap Wireless, Chaparral Steel, Manor Care, HLTH Corp, ImClone). These are the `member_name_mismatch` cases.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/delist_detection/edgar.py` | modify | `EdgarBlocked`, `check_response()`; raise on 403/429 |
| `src/delist_detection/names.py` | create | `name_tokens`, `names_agree`, `MemberNames` (CSV loader) |
| `src/delist_detection/evidence.py` | create | pure predicates over one company's EDGAR record: `name_at`, `renamed_near`, `still_operating`, `is_spac`, `bankruptcy_8ks`, `merger_evidence`, `item_text`, text predicates |
| `src/delist_detection/ticker_resolver.py` | modify | member-name precedence, date-fit check on every tier, no cached failures, re-raise `EdgarBlocked` |
| `src/delist_detection/classifier.py` | modify | rule order, fingerprints, anchor sanity, evidence-based defaults, `evidence["flags"]` |
| `src/delist_detection/payout_extractor.py` | modify | amount regex, class/award/redemption guards, election detection, tie abstain |
| `src/delist_detection/payout_gate.py` | create | `reconcile_payouts()`: price gate, LLM precedence, election resolution |
| `src/delist_detection/reconstruction.py` | modify | `review_flags` column, `distress_at_normal_price`, UNKNOWN-deregistered → assumed par |
| `scripts/classify_universe.py` | modify | `--names`, last close into the extractor, `reconcile_payouts`, abort on `EdgarBlocked`, `output/review.csv` |
| `scripts/build_golden_fixtures.py` | create | capture the golden cases from live EDGAR (out-of-band, like `regen_payout_fixtures.py`) |
| `data/golden_events.csv` | create | the verified truth table |
| `tests/golden.py` | create | `GoldenEdgar` fake + loaders |
| `tests/fixtures/golden/` | create | captured JSON + filing text per case |
| `tests/test_golden_events.py` | create | resolver, classifier and payout assertions per case |
| `tests/test_edgar_blocked.py`, `tests/test_names.py`, `tests/test_evidence.py`, `tests/test_payout_gate.py` | create | unit tests |
| `README.md`, `docs/data-flow.md`, `CLAUDE.md` | modify | bucket policy, trigger table, test count, `--names` |

Each task that adds a predicate to `evidence.py` also adds it to the `from .evidence import …` line at the top of `classifier.py`:
- Task 3: `parse_day`, `name_at`, `first_filing`
- Task 4: `bankruptcy_8ks`, `mentions_bankruptcy`
- Task 5: `filed_operating_between`
- Task 7: `renamed_near`, `still_operating`, `item_text`, `says_listing_transfer`
- Task 8: `is_spac`
- Task 9: `merger_evidence`, `cites_listing_deficiency`

Rule order in `DelistClassifier.classify_ticker` after this plan (tasks in brackets):

1. Non-equity short-circuit (unchanged)
2. Resolve [3]
3. No CIK → UNKNOWN
4. REVOKED → 573
5. Bankruptcy history → 470 [4]
6. Rename or listing transfer → 304 [7]
7. SPAC → 600 [8]
8. Continued periodic filings for more than 180 days → 304 (unchanged)
9. Anchor Form 25 with sanity checks [5], then item fingerprint [6]
10. Evidence-based defaults [9]

---

### Task 1: Golden truth set, fixture builder, offline fake

**Files:**
- Create: `data/golden_events.csv`, `scripts/build_golden_fixtures.py`, `tests/golden.py`, `tests/test_golden_events.py`, `tests/fixtures/golden/*.json`, `tests/fixtures/golden/text/*.txt`

**Interfaces:**
- Produces:
  - `tests.golden.load_cases() -> list[GoldenCase]`
  - `GoldenCase(ticker, observed_delist_date, cik, member_name, last_trade_close, expected_bucket, expected_dlret, dlret_tol, expected_flags, xfail_task)`
  - `tests.golden.GoldenEdgar(case)`, which implements `company_tickers()`, `submissions(cik)`, `recent_filings(cik)`, `fetch_filing_text(cik, accession, primary_doc)`, `company_search_atom(name, form_type)`
  - `tests.golden.patch_efts(monkeypatch, case)`

- [ ] **Step 1: Write the truth table.** Create `data/golden_events.csv`:

```csv
ticker,observed_delist_date,cik,wrong_cik,member_name,last_trade_close,expected_bucket,expected_dlret,dlret_tol,expected_flags,verified,note
HYH,2018-06-29,1606498,829281,HALYARD HEALTH INC,57.25,exchange_transfer,0.0,0.0001,,edgar:1606498 formerNames Halyard Health,rename to Avanos (AVNS)
PEAK,2023-02-13,765880,1829426,HEALTHPEAK PROPERTIES INC,26.49,exchange_transfer,0.0,0.0001,,edgar:765880,2-session vendor stub of Healthpeak
LC,2026-06-01,1409970,,LENDINGCLUB CORP,18.39,exchange_transfer,0.0,0.0001,,edgar:1409970 8-K 2026-06-02 and 2026-06-22,NYSE -> Nasdaq + rename to Happen
SKLZ,2026-06-18,1801661,,SKILLZ INC CLASS A,8.84,exchange_transfer,0.0,0.0001,,edgar:1801661 8-K 2026-06-22,rename to Firy (FIRY)
SPWR,2024-08-20,867773,1838987,SUNPOWER CORP.,1.78,liquidation,,,,edgar:867773 8-K 2024-08-06 item 1.03,Chapter 11
OAS,2020-11-20,1486159,,OASIS PETROLEUM INC.,0.1214,liquidation,,,,edgar:1486159 8-K 2020-09-30 item 1.03; 8-K 2020-11-20,old equity cancelled at emergence
VRTV,2023-11-30,1599489,,VERITIV CORP,169.99,merger,0.0000588,0.0005,,edgar:1599489 8-K 2023-11-30,$170 cash
TWO,2026-08-25,1465740,,TWO HARBORS INVESTMENT REIT CORP,12.18,merger,-0.0147783,0.0005,,edgar:1465740 8-K 2026-08-25,$12.00 cash; $25.00 is the preferred redemption
BLD,2026-07-01,1633931,,TOPBUILD CORP,354.53,merger,-0.057603,0.002,,edgar:1633931 8-K 2026-07-01,election prorated; post-deadline shares took 20.2 QXO @ 16.54
CPWR,2014-12-15,859014,827099,COMPUWARE CORP.,10.35,merger,0.0037863,0.0005,,edgar:859014 8-K 2014-12-17,$10.389188 cash
SIVB,2023-07-14,719739,,SVB FINANCIAL GROUP,0.56,liquidation,,,,edgar:719739 item 1.03,control: bankruptcy
CIE,2017-12-14,1471261,,COBALT INTERNATIONAL ENERGY INC,0.38,liquidation,,,,edgar:1471261 item 1.03,control: bankruptcy
MDR,2020-01-22,708819,,MCDERMOTT INTERNATIONAL INC,0.70,liquidation,,,,edgar:708819,control: Chapter 11 Jan 2020 (today 570 via 3.01)
WE,2024-06-11,1813756,,WEWORK INC CLASS A,0.06,liquidation,,,,edgar:1813756,control: Chapter 11 Nov 2023 (today 580)
LYLT,2023-06-27,1870997,,LOYALTY VENTURES INC,0.011,liquidation,,,,edgar:1870997,control: Chapter 11 Mar 2023 (today 570)
IMCL,2018-10-05,1520047,,IMCLONE SYSTEMS INC,0.159277,compliance_failure,,,member_name_mismatch,edgar:1520047 REVOKED,control: SEC revocation; vendor series is ImmunoClin not ImClone
```

- [ ] **Step 2: Verify each candidate and append the ones that hold.** For each row below, open the named filing on EDGAR (`curl -A "$(python -c 'from delist_detection.edgar import resolve_user_agent as r; print(r())')"`). Append the row only if the filing states what the note says. Rewrite `expected_*` if it states something else, and delete the row if it can't be verified. Record the accession in `verified`.

```csv
BCR,2017-12-29,9892,,C R BARD INC,331.24,merger,,,,,closing 8-K 2017-12-29 (BD cash+stock)
ONXX,2013-10-17,1012140,,ONYX PHARMACEUTICALS INC.,124.92,merger,0.00064,0.001,,,Amgen tender $125.00 cash
SIAL,2015-11-18,90185,,SIGMA ALDRICH CORP,139.76,merger,0.00172,0.001,,,Merck KGaA $140.00 cash
UTIW,2016-02-01,1124827,,UTI WORLDWIDE INC,7.09,merger,0.00141,0.001,,,DSV $7.10 cash
KCI,2012-11-12,831967,,KINETIC CONCEPTS INC,68.47,merger,0.00044,0.001,frozen_tail,,Apax $68.50 cash Nov 2011; vendor tail to 2012-11-12
XTO,2013-02-07,868809,,XTO ENERGY INC,41.81,merger,,,frozen_tail,,ExxonMobil all-stock June 2010; subsidiary filings to 2013
VSTO,2024-11-27,1616318,,VISTA OUTDOOR INC,44.63,merger,,,,,CSG closing 8-K 2024-11-27; check whether the 1.03 tag is backed by text
LBRDA,2026-08-21,1611983,,LIBERTY BROADBAND CORP SERIES A,35.99,merger,,,,,Charter merger closing 8-K; confirm date and terms
LBRDK,2026-08-21,1611983,,LIBERTY BROADBAND CORP SERIES C,36.02,merger,,,,,same event as LBRDA
AABA,2019-11-06,1011006,,ALTABA INC,19.63,unknown,0.0,0.0001,no_evidence_default,,solvent fund liquidation; no bankruptcy or deficiency
FST,2022-08-25,1815737,,FOREST OIL CORP,10.18,expiration,0.0,0.0001,spac;member_name_mismatch,,FAST Acquisition Corp trust liquidation
BWC,2023-08-11,1854863,,BABCOCK AND WILCOX,10.15,expiration,0.0,0.0001,spac;member_name_mismatch,,Blue Whale Acquisition Corp I trust liquidation
HMA,2023-07-25,1850529,,HEALTH MANAGEMENT ASSOCIATES INC C,10.54,expiration,0.0,0.0001,spac;member_name_mismatch,,Heartland Media Acquisition trust liquidation
LEAP,2022-08-16,1818346,,LEAP WIRELESS INTL INC,10.02,expiration,0.0,0.0001,spac;member_name_mismatch,,Ribbit LEAP trust liquidation
HLTH,2019-09-10,1409916,,HLTH CORP,0.12,compliance_failure,,,member_name_mismatch,,Nobilis Health failed to file; not HLTH Corp
```

- [ ] **Step 3: Write the fixture builder.** Create `scripts/build_golden_fixtures.py`:

```python
"""Capture the golden cases from live EDGAR into tests/fixtures/golden/ (NETWORK).

For each row of data/golden_events.csv this stores everything the resolver,
classifier and payout reader read for that case, so tests replay it offline:
submissions (trimmed to ±800/+400 days) for the true CIK and the wrong CIK,
the company_tickers row, company_search_atom hits for every name variant the
resolver issues, the two EFTS answers, and the text of every 8-K carrying
items 1.03/2.01/3.01/5.01 plus the closing/announcement filings the payout
reader would open. Re-run after changing data/golden_events.csv.
"""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from delist_detection.edgar import EdgarClient
from delist_detection.filing_selection import announcement_8k, closing_8k, form_filings
from delist_detection.ticker_resolver import TickerResolver

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "golden"
TEXT_ITEMS = {"1.03", "2.01", "3.01", "5.01"}


def _trim(sub: dict, filings, on: date) -> dict:
    """Name history + the filings near the event. `filings` must come from
    edgar.recent_filings(), which also walks the older paginated chunks — an
    event before ~2015 is usually not in submissions["filings"]["recent"]."""
    lo, hi = (on - timedelta(days=800)).isoformat(), (on + timedelta(days=400)).isoformat()
    near = [f for f in filings if lo <= f.filing_date <= hi]
    earliest = min((f.filing_date for f in filings if f.filing_date), default="")
    # keep the earliest filing too: the resolver's date check reads it
    near += [f for f in filings if f.filing_date == earliest and f not in near]
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
    edgar = EdgarClient(cache_dir=ROOT / "cache" / "edgar")
    companies = edgar.company_tickers()
    (OUT / "text").mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader((ROOT / "data" / "golden_events.csv").open()))
    for row in rows:
        t, d = row["ticker"], row["observed_delist_date"]
        on = date.fromisoformat(d)
        ciks = {int(row["cik"])} | ({int(row["wrong_cik"])} if row.get("wrong_cik") else set())
        subs, texts = {}, {}
        for cik in ciks:
            sub = edgar.submissions(cik)
            all_filings = edgar.recent_filings(cik)
            subs[str(cik)] = _trim(sub, all_filings, on)
            filings = [f for f in all_filings
                       if abs((date.fromisoformat(f.filing_date) - on).days) <= 800]
            wanted = [f for f in filings if f.form.startswith("8-K") and f.item_set & TEXT_ITEMS]
            wanted += closing_8k(filings, on)[:2] + announcement_8k(filings, on)[:2]
            wanted += form_filings(filings, "DEFM14A", on)[:1]
            for f in wanted:
                key = f"{cik}_{f.accession}"
                if key not in texts:
                    txt = edgar.fetch_filing_text(cik, f.accession, f.primary_doc)
                    (OUT / "text" / f"{key}.txt").write_text(txt, encoding="utf-8")
                    texts[key] = True
        resolver = TickerResolver(edgar, name_lookup=lambda *_a, _n=row["member_name"], **_k: _n)
        atom = {}
        for v in TickerResolver._name_variants(row["member_name"]):
            for form in ("25-NSE", "25", "15-12G", ""):
                atom[f"{v}|{form}"] = edgar.company_search_atom(v, form_type=form)
        case = {
            "row": row,
            "company_tickers": {t: companies[t]} if t in companies else {},
            "submissions": subs,
            "atom": atom,
            "efts_lookup": list(resolver._efts_lookup(t, d)),
            "efts_frequency": [list(x) for x in resolver._efts_pre_delist_frequency_ranked(t, d)],
        }
        (OUT / f"{t}_{d}.json").write_text(json.dumps(case, indent=1))
        print(f"{t} {d}: {len(texts)} texts")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run it.**

Run (network): `conda run -n rdagent4qlib python scripts/build_golden_fixtures.py`
Expected: one line per case and no traceback. `ls tests/fixtures/golden/*.json | wc -l` equals the number of CSV rows.

- [ ] **Step 5: Write the offline fake.** Create `tests/golden.py`:

```python
"""Offline replay of the golden cases captured by scripts/build_golden_fixtures.py."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from delist_detection.edgar import EdgarSubmission

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "golden"


@dataclass(frozen=True)
class GoldenCase:
    ticker: str
    observed_delist_date: str
    cik: int
    member_name: str
    last_trade_close: float
    expected_bucket: str
    expected_dlret: float | None
    dlret_tol: float | None
    expected_flags: tuple[str, ...]
    data: dict

    @property
    def id(self) -> str:
        return f"{self.ticker}_{self.observed_delist_date}"


def load_cases() -> list[GoldenCase]:
    out = []
    for row in csv.DictReader((ROOT / "data" / "golden_events.csv").open()):
        data = json.loads((FIX / f"{row['ticker']}_{row['observed_delist_date']}.json").read_text())
        out.append(GoldenCase(
            ticker=row["ticker"], observed_delist_date=row["observed_delist_date"],
            cik=int(row["cik"]), member_name=row["member_name"],
            last_trade_close=float(row["last_trade_close"]),
            expected_bucket=row["expected_bucket"],
            expected_dlret=float(row["expected_dlret"]) if row["expected_dlret"] else None,
            dlret_tol=float(row["dlret_tol"]) if row["dlret_tol"] else None,
            expected_flags=tuple(f for f in row["expected_flags"].split(";") if f),
            data=data,
        ))
    return out


class GoldenEdgar:
    def __init__(self, case: GoldenCase) -> None:
        self.case = case
        self.data = case.data

    def company_tickers(self):
        return self.data["company_tickers"]

    def submissions(self, cik):
        return self.data["submissions"].get(str(int(cik)), {"__not_found__": True})

    def recent_filings(self, cik):
        sub = self.submissions(cik)
        rec = sub.get("filings", {}).get("recent", {})
        return [
            EdgarSubmission(accession=a, form=f, filing_date=fd, report_date=rd, items=it, primary_doc=pd)
            for a, f, fd, rd, it, pd in zip(
                rec.get("accessionNumber", []), rec.get("form", []), rec.get("filingDate", []),
                rec.get("reportDate", []), rec.get("items", []), rec.get("primaryDocument", []))
        ]

    def fetch_filing_text(self, cik, accession, primary_doc):
        p = FIX / "text" / f"{int(cik)}_{accession}.txt"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def company_search_atom(self, company, form_type="25-NSE"):
        return self.data["atom"].get(f"{company}|{form_type}", [])


def patch_efts(monkeypatch, case: GoldenCase) -> None:
    from delist_detection.ticker_resolver import TickerResolver
    hit = case.data["efts_lookup"]
    freq = [tuple(x) for x in case.data["efts_frequency"]]
    monkeypatch.setattr(TickerResolver, "_efts_lookup", lambda self, t, d=None, **kw: tuple(hit))
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: freq)
```

- [ ] **Step 6: Write the golden test.** Create `tests/test_golden_events.py`. `XFAIL` maps each case that fails today to the task that fixes it. Each task deletes its entries.

```python
import math

import pytest

from delist_detection.classifier import DelistClassifier
from delist_detection.ticker_resolver import TickerResolver
from tests.golden import GoldenEdgar, load_cases, patch_efts

CASES = load_cases()

# case id -> the task that makes it pass. Delete entries as tasks land.
XFAIL = {
    "HYH_2018-06-29": 3, "PEAK_2023-02-13": 3, "CPWR_2014-12-15": 3, "SPWR_2024-08-20": 3,
    "IMCL_2018-10-05": 3,
    "OAS_2020-11-20": 4, "MDR_2020-01-22": 4, "WE_2024-06-11": 4, "LYLT_2023-06-27": 4,
    "SKLZ_2026-06-18": 7, "LC_2026-06-01": 7,
    "VRTV_2023-11-30": 10, "TWO_2026-08-25": 10, "BLD_2026-07-01": 11,
}
# Step 2 appends verified candidates; add their ids here with the task that fixes them
# (BCR/ONXX/VSTO -> 6, UTIW/SIAL/AABA -> 9, KCI/XTO/LBRDA/LBRDK -> 5, FST/BWC/HMA/LEAP -> 8,
# HLTH/IMCL member_name_mismatch -> 3).


def _classify(case, monkeypatch, names=None):
    edgar = GoldenEdgar(case)
    patch_efts(monkeypatch, case)
    name = names if names is not None else (lambda t, d=None: case.member_name)
    resolver = TickerResolver(edgar, member_names=name)
    return DelistClassifier(edgar, resolver).classify_ticker(case.ticker, case.observed_delist_date)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_golden_bucket_and_flags(case, monkeypatch, request):
    if case.id in XFAIL:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"fixed by Task {XFAIL[case.id]}"))
    rec = _classify(case, monkeypatch)
    assert rec.bucket.value == case.expected_bucket, rec.reason
    assert set(case.expected_flags) <= set(rec.evidence.get("flags", [])), rec.evidence.get("flags")
    if case.expected_bucket not in ("unknown",) and "member_name_mismatch" not in case.expected_flags:
        assert rec.cik == case.cik
```

`member_names=` does not exist until Task 3, so for now every case fails with `TypeError`. Step 7 adds a temporary shim to prevent that.

**Rule for every later task.** When a task deletes its `XFAIL` entries and a case still fails, check why. If it fails only because a later task's rule is missing, move the entry to that task instead of deleting it. SKLZ, for example, needs Task 5's anchor check and Task 7's rename rule. Any other failure is a bug in the current task.

- [ ] **Step 7: Make the harness run against today's code.** Add a keyword-only `member_names=None` parameter to `TickerResolver.__init__`. It is stored as `self.member_names = member_names or (lambda *a, **kw: None)` and not used yet; Task 3 uses it.

Run: `conda run -n rdagent4qlib pytest tests/test_golden_events.py -v`
Expected:
- Every `XFAIL` id is reported XFAIL.
- Every other id PASSES (SIVB, CIE, plus whatever Step 2 added and did not list).
- An unexpected pass fails the run. Fix the table, not the code.

- [ ] **Step 8: Commit.**

```bash
git add data/golden_events.csv scripts/build_golden_fixtures.py tests/golden.py tests/test_golden_events.py tests/fixtures/golden src/delist_detection/ticker_resolver.py
git commit -m "test: golden delisting cases replayed offline (renames, recycled tickers, bankruptcies, payouts)"
```

---

### Task 2: An SEC refusal is an error, never "no match"

**Files:**
- Modify: `src/delist_detection/edgar.py`, `src/delist_detection/ticker_resolver.py`, `scripts/classify_universe.py`
- Test: `tests/test_edgar_blocked.py`

**Interfaces:**
- Produces:
  - `delist_detection.edgar.EdgarBlocked(RuntimeError)`
  - `delist_detection.edgar.check_response(resp) -> None`, which raises `EdgarBlocked` on status 403 or 429

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_edgar_blocked.py
import json

import pytest

from delist_detection.edgar import EdgarBlocked, EdgarClient
from delist_detection.ticker_resolver import TickerResolver


class _Resp:
    def __init__(self, status, text="blocked"):
        self.status_code, self.text, self.url = status, text, "https://data.sec.gov/x"
    def json(self):
        return json.loads(self.text)
    def raise_for_status(self):
        raise AssertionError("must not be reached for 403/429")


class _Session:
    def __init__(self, status):
        self.status, self.headers = status, {}
    def get(self, *a, **kw):
        return _Resp(self.status)


@pytest.mark.parametrize("status", [403, 429])
def test_get_json_raises_on_refusal(tmp_path, status):
    c = EdgarClient(cache_dir=tmp_path, session=_Session(status))
    with pytest.raises(EdgarBlocked):
        c.submissions(320193)
    assert not list(tmp_path.glob("*.json")), "a refusal must not be cached"


def test_company_search_and_text_raise_on_refusal(tmp_path):
    c = EdgarClient(cache_dir=tmp_path, session=_Session(403))
    with pytest.raises(EdgarBlocked):
        c.company_search_atom("APPLE")
    with pytest.raises(EdgarBlocked):
        c.fetch_filing_text(320193, "0000320193-24-000001", "a.htm")


def test_resolver_propagates_refusal_and_caches_nothing(tmp_path, fake_edgar, monkeypatch):
    def boom(self, *a, **kw):
        raise EdgarBlocked("403")
    monkeypatch.setattr(TickerResolver, "_efts_lookup", boom)
    cache = tmp_path / "res.json"
    r = TickerResolver(fake_edgar, cache_path=cache)
    with pytest.raises(EdgarBlocked):
        r.resolve("NOPE", "2024-01-01")
    assert not cache.exists() or "NOPE" not in cache.read_text()


def test_resolver_does_not_persist_a_miss(tmp_path, fake_edgar):
    cache = tmp_path / "res.json"      # the autouse no-network fixture makes both EFTS tiers empty
    r = TickerResolver(fake_edgar, cache_path=cache)
    assert r.resolve("NOPE", "2024-01-01").cik is None
    assert not cache.exists() or "NOPE|2024-01-01" not in cache.read_text()
```

Also add an autouse fixture to `tests/conftest.py`. The suite is **not** offline today: on 2026-09-16 it made two live `efts.sec.gov` calls, through `test_unknown_ticker_returns_unknown` falling through the resolver tiers. They failed, were swallowed, and the suite still passed (199 tests). That is the same silent-failure pattern as the SEC block, and Task 3 adds more fall-throughs. A test that needs EFTS answers patches them again (`patch_efts`, `boom`), and the later patch wins.

```python
@pytest.fixture(autouse=True)
def _no_efts_network(monkeypatch):
    from delist_detection.ticker_resolver import TickerResolver
    monkeypatch.setattr(TickerResolver, "_efts_lookup", lambda self, t, d=None, **kw: (None, None))
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: [])
```

- [ ] **Step 2: Run it.** `conda run -n rdagent4qlib pytest tests/test_edgar_blocked.py -v`. Expected: FAIL with `ImportError: cannot import name 'EdgarBlocked'`.

- [ ] **Step 3: Implement.** In `edgar.py`, after `FALLBACK_UA`:

```python
class EdgarBlocked(RuntimeError):
    """SEC refused the request (403/429). Callers must never read this as 'no match':
    from 2026-05-28 to 2026-09-16 every refusal was cached as 'No CIK found'."""


def check_response(resp) -> None:
    if resp.status_code in (403, 429):
        raise EdgarBlocked(
            f"SEC returned {resp.status_code} for {getattr(resp, 'url', '?')}. "
            "Set EDGAR_USER_AGENT to a real contact address (see resolve_user_agent) or slow down."
        )
```

Call `check_response(resp)` right after every `session.get` / `requests.get`:
- `_get_json` (before the 404 branch)
- `company_search_atom` (before `if resp.status_code != 200`)
- `fetch_filing_text` (before `if resp.status_code != 200`)
- `TickerResolver._efts_lookup` and `_efts_pre_delist_frequency_ranked` (before `if resp.status_code != 200`, importing `check_response` from `.edgar`)

In `ticker_resolver.py`, three `except Exception` blocks (`_name_search`, `_name_match_score`, `_validate_cik`) each get a clause in front:

```python
        except EdgarBlocked:
            raise
```

In `resolve()`, replace the final three lines with:

```python
        res = TickerResolution(ticker=t, cik=cik, name=name, source=source)
        self._memo[cache_key] = res
        if cik is not None:          # a miss is retried next run, never persisted
            self._persist()
        return res
```

In `scripts/classify_universe.py`, the per-ticker `except Exception as e:` gets a clause in front:

```python
            except EdgarBlocked:
                raise
```

Import `EdgarBlocked` from `delist_detection.edgar`. Also wrap `main()` so the process exits 2 with the message:

```python
if __name__ == "__main__":
    try:
        sys.exit(main())
    except EdgarBlocked as e:
        print(f"ABORTED: {e}", file=sys.stderr)
        sys.exit(2)
```

- [ ] **Step 4: Run the tests.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS (the golden xfails are unchanged).

- [ ] **Step 5: Commit.** `git commit -am "fix(edgar): a 403/429 is an error, not 'no match'; misses are not cached"`

---

### Task 3: Member names and a date-aware company match

**Revised after the Task 1 review.** The first version put the member-name search ahead of EFTS, ignored the ticker in name matching, and skipped zero-score frequency candidates. Checked against the golden fixtures, that design:
- matched FST to Forest City ("FOREST" is shared);
- rejected HYH, whose EDGAR name "Halyard Health" ends 2018-06-28, one day before the vendor's last date;
- left the impostor cases HMA and HLTH unresolved.

This version fixes all three. The DLRET row must describe the security that delisted on the date (Global Constraints), so the date-anchored EFTS search stays ahead of the member-name search. The member name decides only when nothing date-anchored found the company, and it always sets the mismatch flag.

**Files:**
- Create: `src/delist_detection/names.py`, `src/delist_detection/evidence.py` (first part)
- Modify: `src/delist_detection/ticker_resolver.py`, `src/delist_detection/classifier.py`, `scripts/classify_universe.py`, `tests/conftest.py`
- Test: `tests/test_names.py`, `tests/test_evidence.py`, `tests/test_resolver_member_names.py`, `tests/test_golden_events.py`

**Interfaces:**
- Produces:
  - `names.name_tokens(name: str) -> set[str]`
  - `names.names_agree(a: str, b: str) -> bool`
  - `names.MemberNames.from_csv(path) -> MemberNames`, with `__call__(ticker, observed_date=None) -> str | None`
  - `evidence.parse_day(s) -> date | None`
  - `evidence.name_at(sub: dict, on: date) -> str`
  - `evidence.names_near(sub: dict, on: date, days: int = 30) -> list[str]`
  - `evidence.first_filing(filings) -> date | None`
  - `TickerResolver(..., member_names=callable)`
  - `TickerResolver._expected_name(ticker, observed_date) -> str | None`
  - `TickerResolver._fits_date(cik, observed_date, expected_name) -> tuple[bool, bool]`, returning (existed on the date, a name held within ±30 days agrees)
  - `TickerResolver._accept_member_candidate(cik, observed_date, expected_name) -> bool`
  - The classifier adds `"member_name_mismatch"` and `"resolved_by_current_ticker_map"` to `evidence["flags"]`.

- [ ] **Step 1: Write the failing unit tests.**

```python
# tests/test_names.py
from delist_detection.names import MemberNames, name_tokens, names_agree


def test_tokens_keep_three_letter_words_and_drop_legal_suffixes():
    assert name_tokens("SUNPOWER CORP.") == {"SUNPOWER"}
    assert name_tokens("Far Peak Acquisition Corp") == {"FAR", "PEAK", "ACQUISITION"}
    assert name_tokens("FOREST OIL CORP") == {"FOREST", "OIL"}
    assert name_tokens("BABCOCK AND WILCOX") == {"BABCOCK", "WILCOX"}
    assert name_tokens("LEAP WIRELESS INTL INC") == {"LEAP", "WIRELESS"}


def test_agreement_needs_two_shared_words_unless_a_name_has_one():
    assert names_agree("HALYARD HEALTH INC", "Halyard Health, Inc.")
    assert names_agree("SUNPOWER CORP.", "SunPower Inc.")               # one-word names: one shared word
    assert names_agree("XTO ENERGY INC", "XTO ENERGY INC")
    assert not names_agree("HEALTHPEAK PROPERTIES INC", "Far Peak Acquisition Corp")
    assert not names_agree("SUNPOWER CORP.", "Complete Solaria, Inc.")
    assert not names_agree("FOREST OIL CORP", "Forest City Enterprises Inc")   # FST
    assert not names_agree("LEAP WIRELESS INTL INC", "Ribbit LEAP, Ltd.")      # LEAP
    assert not names_agree("XTO ENERGY INC", "ABC Energy Inc")
    assert not names_agree("", "Anything")


def test_member_names_picks_the_latest_row_on_or_before_the_date(tmp_path):
    p = tmp_path / "names.csv"
    p.write_text("ticker,as_of,name\nFST,2008-01-16,FOREST OIL CORP\nX,2020-01-01,OLD X\nX,2024-01-01,NEW X\n")
    m = MemberNames.from_csv(p)
    assert m("FST", "2022-08-25") == "FOREST OIL CORP"
    assert m("X", "2023-06-01") == "OLD X"
    assert m("X", None) == "NEW X"
    assert m("NOPE", "2020-01-01") is None
```

```python
# tests/test_evidence.py
from datetime import date

from delist_detection.evidence import name_at, names_near

SUB = {"name": "SunPower Inc.", "formerNames": [
    {"name": "Complete Solaria, Inc.", "from": "2023-03-10T05:00:00.000Z", "to": "2025-09-26T04:00:00.000Z"},
    {"name": "Freedom Acquisition I Corp.", "from": "2021-01-08T05:00:00.000Z", "to": "2023-07-20T04:00:00.000Z"},
]}
AVANOS = {"name": "AVANOS MEDICAL, INC.", "formerNames": [
    {"name": "Halyard Health, Inc.", "from": "2014-06-02T04:00:00.000Z", "to": "2018-06-28T04:00:00.000Z"}]}


def test_name_at_uses_the_former_name_covering_the_date():
    assert name_at(SUB, date(2024, 8, 20)) == "Complete Solaria, Inc."
    assert name_at(SUB, date(2026, 1, 1)) == "SunPower Inc."


def test_names_near_includes_a_name_that_ended_just_before_the_date():
    # EDGAR ends "Halyard Health" on 2018-06-28; the vendor's last HYH row is 2018-06-29.
    assert names_near(AVANOS, date(2018, 6, 29)) == ["Halyard Health, Inc.", "AVANOS MEDICAL, INC."]
    assert names_near(SUB, date(2024, 8, 20)) == ["Complete Solaria, Inc."]
    assert names_near({"name": "Solo Co", "formerNames": []}, date(2020, 1, 1)) == ["Solo Co"]
```

```python
# tests/test_resolver_member_names.py
from delist_detection.edgar import EdgarSubmission
from delist_detection.ticker_resolver import TickerResolver


class _Edgar:
    """Companies by CIK; name search answers by name prefix."""
    def __init__(self, companies, atom):
        self.companies = companies      # cik -> (name, formerNames, filings)
        self.atom = atom                # name prefix -> cik
    def company_tickers(self):
        return {}
    def submissions(self, cik):
        c = self.companies.get(int(cik))
        return {"name": c[0], "formerNames": c[1], "sic": ""} if c else {"__not_found__": True}
    def recent_filings(self, cik):
        c = self.companies.get(int(cik))
        return list(c[2]) if c else []
    def company_search_atom(self, company, form_type="25-NSE"):
        for prefix, cik in self.atom.items():
            if company.upper().startswith(prefix):
                return [{"cik": cik, "name": None, "form": "", "filing_date": ""}]
        return []
    def fetch_filing_text(self, *a):
        return ""


def _f(acc, form, d):
    return EdgarSubmission(acc, form, d, "", "", "x.htm")


AVANOS = (1606498, ("AVANOS MEDICAL, INC.",
                    [{"name": "Halyard Health, Inc.", "from": "2014-06-02T04:00:00.000Z",
                      "to": "2018-06-28T04:00:00.000Z"}],
                    [_f("K1", "10-K", "2018-02-23"), _f("E1", "8-K", "2018-07-02")]))


def test_a_member_name_finds_a_renamed_company_that_filed_no_form25():
    e = _Edgar(dict([AVANOS]), {"HALYARD": 1606498})
    r = TickerResolver(e, member_names=lambda t, d=None: "HALYARD HEALTH INC")
    assert r.resolve("HYH", "2018-06-29").cik == 1606498


def test_without_a_member_name_the_loose_form25_check_still_applies():
    e = _Edgar(dict([AVANOS]), {"HALYARD": 1606498})
    r = TickerResolver(e, name_lookup=lambda t, d=None: "HALYARD HEALTH INC")
    assert r.resolve("HYH", "2018-06-29").cik is None


def test_a_frozen_tail_member_is_accepted_through_its_old_form25():
    xto = (868809, ("XTO ENERGY INC", [], [_f("X1", "8-K", "2010-06-25"), _f("X2", "25-NSE", "2010-06-28"),
                                          _f("X3", "15-12B", "2010-07-08")]))
    r = TickerResolver(_Edgar(dict([xto]), {"XTO": 868809}), member_names=lambda t, d=None: "XTO ENERGY INC")
    assert r.resolve("XTO", "2013-02-07").cik == 868809


def test_a_long_dead_member_is_not_accepted_for_a_later_event():
    dead = (765258, ("IMCLONE SYSTEMS INC", [], [_f("I1", "10-K", "2008-03-01")]))
    r = TickerResolver(_Edgar(dict([dead]), {"IMCLONE": 765258}),
                       member_names=lambda t, d=None: "IMCLONE SYSTEMS INC")
    assert r.resolve("IMCL", "2018-10-05").cik is None


def test_the_date_anchored_efts_hit_beats_the_member_name(monkeypatch):
    # FST: the vendor series is FAST Acquisition Corp; the member was Forest Oil.
    fast = (1815737, ("FAST Acquisition Corp.", [], [_f("S1", "S-1", "2020-08-01"), _f("F1", "25-NSE", "2022-08-26")]))
    city = (38067, ("FOREST CITY REALTY TRUST", [], [_f("C1", "10-K", "2018-02-27"), _f("C2", "25-NSE", "2018-12-10")]))
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (1815737, "FAST Acquisition Corp. (FST)"))
    r = TickerResolver(_Edgar(dict([fast, city]), {"FOREST": 38067}),
                       member_names=lambda t, d=None: "FOREST OIL CORP")
    assert r.resolve("FST", "2022-08-25").cik == 1815737


def test_the_member_name_tier_runs_before_the_frequency_rank(monkeypatch):
    # LC with SEC's current ticker map: EFTS finds nothing; frequency rank would pick Comstock.
    lc = (1409970, ("Happen, Inc.", [{"name": "LendingClub Corp", "from": "2007-08-15T04:00:00.000Z",
                                      "to": "2026-06-18T04:00:00.000Z"}],
                    [_f("L1", "10-Q", "2026-05-05"), _f("L2", "25", "2026-06-18")]))
    comstock = (1299969, ("COMSTOCK INC", [], [_f("M1", "10-K", "2026-03-01")]))
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: [(1299969, "Comstock Inc"), (1409970, "LendingClub")])
    r = TickerResolver(_Edgar(dict([lc, comstock]), {"LENDINGCLUB": 1409970}),
                       member_names=lambda t, d=None: "LENDINGCLUB CORP")
    assert r.resolve("LC", "2026-06-01").cik == 1409970
```

In `tests/test_golden_events.py`, delete the Task 3 entries from `XFAIL_BUCKET` (CPWR, PEAK, IMCL). Apply the general rule for any that still fail.

- [ ] **Step 2: Run them.** `PYTHONPATH=src:. conda run -n rdagent4qlib --no-capture-output python -m pytest tests/test_names.py tests/test_evidence.py tests/test_resolver_member_names.py tests/test_golden_events.py -v`. Expected: the new files FAIL (ImportError or wrong CIK), and the Task 3 golden ids FAIL.

- [ ] **Step 3: Implement `names.py`.**

```python
"""Company-name tokens and the caller-supplied index-member names."""
from __future__ import annotations

import csv
import re
from bisect import bisect_right
from pathlib import Path

_STOP = {"CORP", "CORPORATION", "INC", "INCORPORATED", "COMPANY", "COS", "HOLDINGS", "HOLDING",
         "LTD", "LIMITED", "LLC", "PLC", "GROUP", "INTERNATIONAL", "INTL", "TRUST", "PARTNERS",
         "FUND", "BANK", "BANCORP", "BANCSHARES", "CLASS", "SERIES", "COMMON", "STOCK", "SHARES",
         "THE", "AND", "NEW"}


def name_tokens(name: str) -> set[str]:
    """Words of three or more letters, minus legal suffixes and fillers. Three-letter
    words stay because they are often the distinctive part (XTO, OIL, SVB, UTI)."""
    return {t for t in re.findall(r"[A-Z]{3,}", (name or "").upper()) if t not in _STOP}


def names_agree(a: str, b: str) -> bool:
    """Two names agree when they share min(2, |A|, |B|) words, and at least one.
    One shared word is not enough when both names have two or more: Forest Oil is
    not Forest City (FST), Leap Wireless is not Ribbit LEAP (LEAP)."""
    ta, tb = name_tokens(a), name_tokens(b)
    need = min(2, len(ta), len(tb))
    return need >= 1 and len(ta & tb) >= need


class MemberNames:
    """(ticker, date) -> the index member's name as the index recorded it.

    CSV columns: ticker, as_of, name. The row used is the latest one with
    as_of <= date (the member the index held before the delisting)."""

    def __init__(self, rows: dict[str, list[tuple[str, str]]]) -> None:
        self._rows = {t: sorted(v) for t, v in rows.items()}

    @classmethod
    def from_csv(cls, path: str | Path) -> "MemberNames":
        rows: dict[str, list[tuple[str, str]]] = {}
        with Path(path).open(newline="") as fh:
            for r in csv.DictReader(fh):
                rows.setdefault(r["ticker"].strip().upper(), []).append((r["as_of"], r["name"]))
        return cls(rows)

    def __call__(self, ticker: str, observed_date: str | None = None) -> str | None:
        rows = self._rows.get(ticker.upper())
        if not rows:
            return None
        if observed_date is None:
            return rows[-1][1]
        i = bisect_right([d for d, _ in rows], observed_date)
        return rows[i - 1][1] if i else None
```

- [ ] **Step 4: Implement `evidence.py`.**

```python
"""Pure evidence predicates over one company's EDGAR record. No network."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .edgar import EdgarSubmission


def parse_day(s: str | None) -> date | None:
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def name_at(sub: dict, on: date) -> str:
    """The EDGAR name on `on`: the formerNames entry whose [from, to] covers it, else the current name."""
    for fn in sub.get("formerNames") or []:
        lo, hi = parse_day(fn.get("from")), parse_day(fn.get("to"))
        if lo and hi and lo <= on <= hi:
            return fn.get("name") or ""
    return sub.get("name") or ""


def names_near(sub: dict, on: date, days: int = 30) -> list[str]:
    """Every name the company carried within ±days of `on`, former names first.

    A delisting date and a rename date are often a day apart (EDGAR ends
    "Halyard Health" on 2018-06-28; HYH's last vendor row is 2018-06-29), so a
    single-day lookup misses the name the index used."""
    lo, hi = on - timedelta(days=days), on + timedelta(days=days)
    out: list[str] = []
    last_end: date | None = None
    for fn in sub.get("formerNames") or []:
        f_lo, f_hi = parse_day(fn.get("from")), parse_day(fn.get("to"))
        if f_hi and (last_end is None or f_hi > last_end):
            last_end = f_hi
        if f_lo and f_hi and f_lo <= hi and f_hi >= lo and fn.get("name"):
            out.append(fn["name"])
    if (last_end is None or last_end <= hi) and sub.get("name"):
        out.append(sub["name"])      # the current name runs from the last rename on
    return out


def first_filing(filings: list[EdgarSubmission]) -> date | None:
    days = [d for f in filings if (d := parse_day(f.filing_date))]
    return min(days) if days else None
```

- [ ] **Step 5: Wire the resolver.**

In `TickerResolver.__init__`, store `member_names` (the Task 1 shim already accepts it). Add:

```python
    MEMBER_ALIVE_DAYS = 400          # filed within ±this of the date: the company was operating
    MEMBER_TAIL_DAYS = 1500          # a Form 25/15 up to this old: a frozen vendor tail (XTO)

    def _expected_name(self, t: str, observed_date: str | None) -> str | None:
        return self.member_names(t, observed_date) or self.name_lookup(t, observed_date)

    def _fits_date(self, cik: int, observed_date: str | None, expected: str | None) -> tuple[bool, bool]:
        """(existed on the date, a name it carried within ±30 days agrees with `expected`).

        A CIK first seen after the delist date is today's holder of a recycled
        ticker (CPWR -> Ocean Thermal, SPWR -> Complete Solaria/SunPower Inc.)."""
        on = parse_day(observed_date)
        if on is None:
            return True, True
        try:
            sub = self.edgar.submissions(cik)
            filings = self.edgar.recent_filings(cik)
        except EdgarBlocked:
            raise
        except Exception:
            return False, False
        first = first_filing(filings)
        existed = first is not None and first <= on
        agrees = expected is None or (isinstance(sub, dict) and
                                      any(names_agree(n, expected) for n in names_near(sub, on)))
        return existed, agrees

    def _accept_member_candidate(self, cik: int, observed_date: str | None, expected: str) -> bool:
        """Accept a name-search hit found through a member name.

        A rename files no Form 25 (HYH -> Avanos), and a frozen vendor tail can
        outlast the 540-day window (XTO), so the loose check alone rejects true
        matches. Without that check, the company must have existed on the date,
        carried an agreeing name then, and either been filing within ±400 days
        or filed a Form 25/15 in the 1,500 days before the date. The last two
        conditions keep out a long-dead member (ImClone for a 2018 date)."""
        if not observed_date or self._validate_cik(cik, observed_date, strict=False):
            return True
        existed, agrees = self._fits_date(cik, observed_date, expected)
        if not (existed and agrees):
            return False
        on = parse_day(observed_date)
        for f in self.edgar.recent_filings(cik):
            d = parse_day(f.filing_date)
            if d is None:
                continue
            if abs((d - on).days) <= self.MEMBER_ALIVE_DAYS:
                return True
            if f.form in {"25", "25-NSE", "15-12G", "15-12B", "15-15D"} and \
                    on - timedelta(days=self.MEMBER_TAIL_DAYS) <= d <= on + timedelta(days=45):
                return True
        return False
```

Import `parse_day`, `names_near` and `first_filing` from `.evidence`, `names_agree` and `name_tokens` from `.names`, and `EdgarBlocked` from `.edgar`.

In `resolve()`, the tier order stays as today. Only the checks change:
1. Manual overrides.
2. Cache.
3. Rename map.
4. `company_tickers`: accept the hit only if `_fits_date(cik, observed_date, expected) == (True, True)`, where `expected = self._expected_name(t, observed_date)`, with source `"company_tickers"`. Otherwise fall through.
5. Tier 1 (EFTS): after `_validate_cik(strict=False)`, also require `existed` from `_fits_date`. If the name does not agree, keep the CIK and set `source = "efts_name_mismatch"`. The row describes the company that delisted on the date, and the classifier flags the mismatch.
   - `_efts_lookup` gains a keyword argument `expected_name=None`.
   - Its second pass ("first non-exchange CIK in any hit") returns a candidate only if `names_agree(nm, expected_name)`. With no expected name it skips the second pass.
6. Tier 2 (name search): `_name_search` uses `self._expected_name(ticker, observed_date)` instead of `self.name_lookup(...)`.
   - When `self.member_names(t, observed_date)` is not None, validate the hit with `_accept_member_candidate`. Otherwise keep today's `_validate_cik(..., strict=False)`.
7. Tier 3 (frequency rank): unchanged selection, except that `_name_match_score` compares `name_tokens` sets (the shared tokenizer) against `self._expected_name(...)`.
   - A score of 0 is allowed; the impostor series HMA and HLTH resolve only here.
   - When the winner's score is 0 and an expected name exists, set `source = "efts_frequency_name_mismatch"`.

In `DelistClassifier.classify_ticker`, right after `resolution` is known and a CIK exists:

```python
        flags: list[str] = []
        if resolution.source == "company_tickers":
            flags.append("resolved_by_current_ticker_map")
        expected = self.resolver._expected_name(ticker.upper(), observed_delist_date)
        if expected and observed:
            _, agrees = self.resolver._fits_date(resolution.cik, observed_delist_date, expected)
            if not agrees:
                flags.append("member_name_mismatch")
```

Put `flags` into every `evidence` dict created after this point (`evidence["flags"] = flags`). Build the base `evidence` before the REVOKED check so every return path carries it.

The company-tickers tier now reads `submissions()` for every hit. So in `tests/conftest.py`, give `_FakeEdgar` the three methods the new code calls:
- `submissions(cik)`, which returns `{"name": <title of the company-map row with that cik_str>, "formerNames": [], "sic": ""}`;
- `fetch_filing_text(cik, accession, primary_doc)`, which returns `self.texts.get(accession, "")` from a new `texts: dict` field (default empty);
- `company_search_atom(name, form_type="25-NSE")`, which returns `[]`.

Give the `BAD` fixture `texts={"A002": "Item 3.01 Notice of Delisting ... has not regained compliance with the minimum bid price requirement"}`; Task 9 relies on it. Every fixture company's earliest filing must be on or before its test date, or the date check rejects it. That already holds for ALTR, BAD and LIQ.

In `scripts/classify_universe.py`, add `p.add_argument("--names", default=None, help="CSV ticker,as_of,name: index-member names (qlib_practice exports them from iShares/Wikipedia holdings)")`. Pass `member_names=MemberNames.from_csv(args.names) if args.names else None` to `TickerResolver`.

- [ ] **Step 6: Run the tests.** `PYTHONPATH=src:. conda run -n rdagent4qlib --no-capture-output python -m pytest -q`. Expected: PASS.
  - Golden cases: the resolution parts of HYH, SPWR, OAS, MDR, WE, XTO and KCI are now right, while their buckets wait for later tasks (their `XFAIL_BUCKET` entries stay).
  - CPWR, PEAK and IMCL pass.
  - HLTH, FST, BWC, HMA and LEAP carry `member_name_mismatch` and wait for their bucket task.
  - Apply the general rule to anything else.

- [ ] **Step 7: Commit.** `git commit -am "feat(resolver): member names and a date-aware company match; flag a member/company mismatch"`

---

### Task 4: A bankruptcy on record beats "kept filing", and a 1.03 tag needs text

**Files:**
- Modify: `src/delist_detection/evidence.py`, `src/delist_detection/classifier.py`
- Test: `tests/test_evidence.py`, `tests/test_classifier.py`, `tests/test_golden_events.py`

**Interfaces:**
- Produces:
  - `evidence.bankruptcy_8ks(filings, on, before=540, after=30) -> list[EdgarSubmission]`
  - `evidence.mentions_bankruptcy(text) -> bool`
  - `DelistClassifier._confirmed_bankruptcy(cik, filings, on) -> EdgarSubmission | None`

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_evidence.py (append)
from delist_detection.edgar import EdgarSubmission
from delist_detection.evidence import bankruptcy_8ks, mentions_bankruptcy


def _8k(d, items, acc="A"):
    return EdgarSubmission(accession=acc, form="8-K", filing_date=d, report_date=d, items=items, primary_doc="x.htm")


def test_bankruptcy_8ks_window():
    fs = [_8k("2020-09-30", "1.01,1.03"), _8k("2018-01-01", "1.03", "B"), _8k("2020-11-20", "3.03,5.01", "C")]
    assert [f.accession for f in bankruptcy_8ks(fs, date(2020, 11, 20))] == ["A"]


def test_mentions_bankruptcy():
    assert mentions_bankruptcy("filed voluntary petitions under chapter 11 of title 11")
    assert not mentions_bankruptcy("completion of the merger with CSG")
```

```python
# tests/test_classifier.py (append)
from delist_detection.edgar import EdgarSubmission


class _TextEdgar:
    def __init__(self, filings, texts):
        self.filings, self.texts = filings, texts
    def company_tickers(self):
        return {"REORG": {"cik_str": 5, "ticker": "REORG", "title": "Reorg Co"}}
    def recent_filings(self, cik):
        return list(self.filings)
    def submissions(self, cik):
        return {"name": "Reorg Co", "formerNames": [], "sic": "1311"}
    def fetch_filing_text(self, cik, acc, doc):
        return self.texts.get(acc, "")


def test_bankruptcy_history_beats_continued_filings():
    fs = [
        EdgarSubmission("A1", "8-K", "2020-09-30", "2020-09-29", "1.01,1.03,7.01", "a.htm"),
        EdgarSubmission("A2", "25-NSE", "2020-10-27", "", "", "p.xml"),
        EdgarSubmission("A3", "10-Q", "2021-08-05", "", "", "q.htm"),   # reorganized company keeps filing
    ]
    e = _TextEdgar(fs, {"A1": "the Company filed voluntary petitions under chapter 11"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2020-11-20")
    assert rec.bucket is CrspBucket.LIQUIDATION and rec.crsp_code == 470


def test_a_1_03_tag_without_bankruptcy_text_is_not_a_bankruptcy():
    fs = [
        EdgarSubmission("B1", "8-K", "2024-11-27", "2024-11-27", "1.01,1.03,2.01,3.01,3.03,5.01", "b.htm"),
        EdgarSubmission("B2", "25-NSE", "2024-11-27", "", "", "p.xml"),
        EdgarSubmission("B3", "15-12G", "2024-12-09", "", "", "f.htm"),
    ]
    e = _TextEdgar(fs, {"B1": "completion of the merger; each share converted into the right to receive"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2024-11-27")
    assert rec.bucket is CrspBucket.MERGER
    assert "bankruptcy_tag_unconfirmed" in rec.evidence["flags"]
```

In `tests/test_golden_events.py`, delete the Task 4 `XFAIL` entries.

- [ ] **Step 2: Run them.** Expected: FAIL. `bankruptcy_8ks` doesn't exist, the first classifier test returns EXCHANGE_TRANSFER, and the second returns LIQUIDATION.

- [ ] **Step 3: Implement.** In `evidence.py`:

```python
import re
from datetime import timedelta

_BANKRUPTCY_TEXT = re.compile(r"bankruptcy|chapter\s+(?:11|7)\b|receivership", re.I)


def bankruptcy_8ks(filings, on: date, before: int = 540, after: int = 30):
    lo, hi = on - timedelta(days=before), on + timedelta(days=after)
    out = []
    for f in filings:
        d = parse_day(f.report_date) or parse_day(f.filing_date)
        if f.form.startswith("8-K") and "1.03" in f.item_set and d and lo <= d <= hi:
            out.append(f)
    return sorted(out, key=lambda f: f.filing_date)


def mentions_bankruptcy(text: str) -> bool:
    return bool(_BANKRUPTCY_TEXT.search(text or ""))
```

In `classifier.py`:

```python
    def _confirmed_bankruptcy(self, cik, filings, on):
        """First 1.03 8-K in the window whose text mentions a bankruptcy. An empty
        text (fetch miss) counts as confirmed: the tag is SEC's own metadata."""
        for f in bankruptcy_8ks(filings, on):
            text = self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc)
            if not text or mentions_bankruptcy(text):
                return f
        return None
```

In `classify_ticker`, after the REVOKED loop and before the continued-filings override:

```python
        if observed:
            bk = self._confirmed_bankruptcy(resolution.cik, filings, observed)
            if bk is not None:
                return DelistRecord(
                    ticker=ticker.upper(), cik=resolution.cik,
                    observed_delist_date=observed_delist_date, crsp_code=470,
                    bucket=CrspBucket.LIQUIDATION, confidence="high",
                    reason=f"Bankruptcy (8-K item 1.03 filed {bk.filing_date})",
                    evidence={**evidence, "bankruptcy_8k": asdict(bk)},
                )
```

In `_classify_items` callers, strip an unconfirmed 1.03 before classifying. Add:

```python
    def _effective_items(self, cik, f, flags):
        items = set(f.item_set)
        if "1.03" in items:
            text = self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc)
            if text and not mentions_bankruptcy(text):
                items.discard("1.03")
                flags.append("bankruptcy_tag_unconfirmed")
        return items
```

Then replace each `self._classify_items(eightk.item_set)` with `self._classify_items(self._effective_items(resolution.cik, eightk, flags))`. `_FakeEdgar` in `tests/conftest.py` already has `fetch_filing_text` and `submissions` (Task 3).

- [ ] **Step 4: Run.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -am "fix(classifier): a confirmed 1.03 wins over continued filings; an unconfirmed 1.03 tag is ignored"`

---

### Task 5: Anchor sanity: no Form 25 from another event, and frozen tails flagged

**Files:**
- Modify: `src/delist_detection/classifier.py`, `src/delist_detection/evidence.py`
- Test: `tests/test_classifier.py`, `tests/test_golden_events.py`

**Interfaces:**
- Produces:
  - `evidence.filed_operating_between(filings, lo, hi) -> bool`
  - `DelistClassifier._pick_delist_filing(filings, observed, cik)`, which returns `(filing | None, gap_days | None)`
  - `evidence["flags"]` gains `frozen_tail:<days>`

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_classifier.py (append)
def test_an_old_form25_from_another_event_is_not_the_anchor():
    # 1,037 days: inside the 1,500-day window, so the operating-filings rule is what rejects it
    fs = [
        EdgarSubmission("C1", "25-NSE", "2021-08-16", "", "", "p.xml"),          # warrant delisting
        EdgarSubmission("C2", "8-K", "2021-08-16", "2021-08-16", "8.01,9.01", "c.htm"),
        EdgarSubmission("C3", "10-Q", "2023-11-05", "", "", "q.htm"),
        EdgarSubmission("C4", "8-K", "2024-06-18", "2024-06-18", "7.01,9.01", "d.htm"),
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2024-06-18")
    assert rec.evidence.get("delist_filing") is None
    assert rec.bucket is not CrspBucket.COMPLIANCE_FAILURE


def test_an_earlier_merger_form25_marks_a_frozen_tail():
    fs = [
        EdgarSubmission("D1", "8-K", "2010-06-25", "2010-06-25", "3.01,3.03,5.01", "a.htm"),
        EdgarSubmission("D2", "25-NSE", "2010-06-28", "", "", "p.xml"),
        EdgarSubmission("D3", "10-K", "2011-02-25", "", "", "k.htm"),              # registered debt
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2013-02-07")
    assert rec.evidence["delist_filing"]["accession"] == "D2"
    assert any(f.startswith("frozen_tail:") for f in rec.evidence["flags"])
```

The second test also needs Task 6 (3.01 + 5.01 → merger) for its bucket, so it asserts only the anchor and the flag. In `tests/test_golden_events.py`, delete the Task 5 `XFAIL` entries.

- [ ] **Step 2: Run.** Expected: FAIL. The 2021 Form 25 is picked, and no flag is set.

- [ ] **Step 3: Implement.** In `evidence.py`:

```python
OPERATING_FORMS = {"10-K", "10-Q", "20-F", "40-F"}


def filed_operating_between(filings, lo: date, hi: date) -> bool:
    for f in filings:
        d = parse_day(f.filing_date)
        if d and lo < d < hi and (f.form in OPERATING_FORMS or (f.form == "8-K" and "2.02" in f.item_set)):
            return True
    return False
```

In `classifier.py`:

```python
FORM25_AFTER_DAYS = 45       # a Form 25 filed after the vendor's last trade
FORM25_TAIL_DAYS = 45        # beyond this, an earlier Form 25 means a frozen vendor tail
FORM25_MAX_BEFORE_DAYS = 1500
M_A_ITEMS = {"2.01", "5.01", "3.03"}

    def _pick_delist_filing(self, filings, observed, cik=None):
        cands = [f for f in filings if f.form in DELIST_FORMS]
        if not cands:
            return None, None
        if observed is None:
            return max(cands, key=lambda f: f.filing_date), None
        best = None
        for c in cands:
            fd = _parse_date(c.filing_date)
            if fd is None:
                continue
            gap = (observed - fd).days            # > 0: Form 25 before the last trade
            if gap < -FORM25_AFTER_DAYS or gap > FORM25_MAX_BEFORE_DAYS:
                continue
            if gap > FORM25_TAIL_DAYS:
                near = self._pick_8k_near(filings, fd) or self._backscan_for_fingerprint_8k(filings, fd)
                merger_anchor = near is not None and bool(near.item_set & M_A_ITEMS)
                if not merger_anchor and filed_operating_between(filings, fd, observed):
                    continue                      # an older, different event (SKLZ 2021, LBRDA 2015)
            if best is None or abs(gap) < abs(best[1]):
                best = (c, gap)
        return (best[0], best[1]) if best else (None, None)
```

In `classify_ticker`, change `delist_filing = self._pick_delist_filing(filings, observed)` to:

```python
        delist_filing, gap = self._pick_delist_filing(filings, observed, resolution.cik)
        if gap is not None and gap > FORM25_TAIL_DAYS:
            flags.append(f"frozen_tail:{gap}")
        evidence["anchor_gap_days"] = gap
```

Keep `evidence["delist_filing"]` as today. When the anchor 8-K search runs on a frozen tail, it uses the Form 25 date (unchanged).

- [ ] **Step 4: Run.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -am "fix(classifier): an old Form 25 from another event is not the anchor; flag frozen vendor tails"`

---

### Task 6: Takeover fingerprints without item 2.01; a change in control beats 2.04

**Files:**
- Modify: `src/delist_detection/classifier.py`
- Test: `tests/test_classifier.py`, `tests/test_golden_events.py`

**Interfaces:**
- Produces: `_classify_items(items)` with the new table below. Same signature.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_classifier.py (append)
import pytest


@pytest.mark.parametrize("items, code", [
    ({"3.01", "3.03", "5.01", "5.02", "5.03"}, 231),        # BCR, GXP, IRF: target 8-K without 2.01
    ({"3.01", "5.01", "9.01"}, 231),                         # FWLT
    ({"3.03", "5.01", "5.02"}, 231),
    ({"1.01", "2.04", "3.01", "3.03", "5.01"}, 231),         # ONXX, SLXP: notes put on change in control
    ({"2.04", "3.01"}, 470),                                 # distress lead-in stays distress
    ({"3.01", "8.01"}, 570),
    ({"1.03", "3.01"}, 470),
])
def test_item_fingerprints(items, code):
    c = DelistClassifier(edgar=None, resolver=None)
    assert c._classify_items(items)[0] == code
```

In `tests/test_golden_events.py`, delete the Task 6 `XFAIL` entries.

- [ ] **Step 2: Run.** Expected: FAIL on the first four parameter sets (570, 570, None, 470).

- [ ] **Step 3: Implement.** Replace the body of `_classify_items` after the `has_*` assignments:

```python
        has_303 = "3.03" in items
        control = has_501 and (has_201 or has_301 or has_303)

        if has_103:
            return 470, "Bankruptcy (8-K item 1.03)"
        if has_201 and has_301 and has_501:
            return 231, "M&A 2.01+3.01+5.01 (acquired by external acquirer)"
        if has_201 and has_501:
            return 233, "M&A 2.01+5.01 (subsidiary buyback / parent acquisition)"
        if control:
            return 231, "M&A change in control (5.01) with delisting/rights change, closing 8-K without 2.01"
        if has_201 and has_301:
            return 200, "M&A 2.01+3.01 (acquisition with delisting)"
        if has_204 and has_301:
            return 470, "3.01 + 2.04 without a change in control (distress/Ch.11 lead-in)"
        if has_301:
            return 570, "Compliance failure (3.01 alone, no M&A indicators)"
        return None, "No conclusive 8-K items"
```

Item 1.03 still comes first. Task 4 has already removed any unconfirmed 1.03 before this runs, which is how VSTO reaches the change-in-control rule.

- [ ] **Step 4: Run.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS. `test_compliance_failure_classifies_correctly` (3.01, 8.01) still returns 570.

- [ ] **Step 5: Commit.** `git commit -am "fix(classifier): a change in control is a takeover even without item 2.01, and beats 2.04"`

---

### Task 7: Renames and listing transfers

**Files:**
- Modify: `src/delist_detection/evidence.py`, `src/delist_detection/classifier.py`
- Test: `tests/test_evidence.py`, `tests/test_classifier.py`, `tests/test_golden_events.py`

**Interfaces:**
- Produces:
  - `evidence.renamed_near(sub, on, days=60) -> str | None`
  - `evidence.still_operating(filings, on, days=15) -> bool`
  - `evidence.item_text(text, item, width=1500) -> str`
  - `evidence.says_listing_transfer(text) -> bool`

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_evidence.py (append)
from delist_detection.evidence import item_text, renamed_near, says_listing_transfer, still_operating

LC_SUB = {"name": "Happen, Inc.", "formerNames": [
    {"name": "LendingClub Corp", "from": "2007-08-15T04:00:00.000Z", "to": "2026-06-18T04:00:00.000Z"}]}


def test_renamed_near():
    assert renamed_near(LC_SUB, date(2026, 6, 1)) == "LendingClub Corp"
    assert renamed_near(LC_SUB, date(2025, 1, 1)) is None


def test_still_operating_needs_results_and_no_form15():
    fs = [_8k("2026-07-27", "2.02,9.01")]
    assert still_operating(fs, date(2026, 6, 1))
    fs.append(EdgarSubmission("F", "15-12G", "2026-07-13", "", "", "f.htm"))
    assert not still_operating(fs, date(2026, 6, 1))


def test_listing_transfer_text():
    t = ("Item 3.01 Notice of Delisting ... notified the NYSE of its intention to voluntarily "
         "withdraw the listing of its common stock from the NYSE and transfer the listing to Nasdaq")
    assert says_listing_transfer(item_text(t, "3.01"))
    assert not says_listing_transfer("Item 3.01 ... did not regain compliance with the minimum bid price")
```

```python
# tests/test_classifier.py (append)
class _RenameEdgar(_TextEdgar):
    def submissions(self, cik):
        return LC_LIKE


LC_LIKE = {"name": "Happen, Inc.", "sic": "6141", "formerNames": [
    {"name": "Reorg Co", "from": "2007-08-15T04:00:00.000Z", "to": "2026-06-18T04:00:00.000Z"}]}


def test_rename_while_still_operating_is_an_exchange_transfer():
    fs = [
        EdgarSubmission("E0", "10-K", "2026-02-20", "", "", "k.htm"),   # existed before the date
        EdgarSubmission("E1", "8-K", "2026-06-02", "2026-06-02", "3.01,7.01,9.01", "a.htm"),
        EdgarSubmission("E2", "25", "2026-06-18", "", "", "p.xml"),
        EdgarSubmission("E3", "8-K", "2026-07-27", "2026-07-27", "2.02,9.01", "b.htm"),
    ]
    e = _RenameEdgar(fs, {"E1": "Item 3.01 ... transfer the listing to The Nasdaq Stock Market"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2026-06-01")
    assert rec.bucket is CrspBucket.EXCHANGE_TRANSFER and rec.crsp_code == 304
```

In `tests/test_golden_events.py`, delete the Task 7 `XFAIL` entries.

- [ ] **Step 2: Run.** Expected: FAIL (ImportError; LC → 570).

- [ ] **Step 3: Implement.** In `evidence.py`:

```python
_TRANSFER_TEXT = re.compile(r"transfer\s+(?:the|its|of\s+(?:the|its))\s+listing", re.I)


def renamed_near(sub: dict, on: date, days: int = 60) -> str | None:
    for fn in sub.get("formerNames") or []:
        hi = parse_day(fn.get("to"))
        if hi and abs((hi - on).days) <= days:
            return fn.get("name")
    return None


def still_operating(filings, on: date, days: int = 15) -> bool:
    """Reported results (10-K/10-Q or an 8-K item 2.02) after on+days and filed no Form 15 after on."""
    cutoff = on + timedelta(days=days)
    operating = deregistered = False
    for f in filings:
        d = parse_day(f.filing_date)
        if d is None or d <= on:
            continue
        if f.form.startswith("15-"):
            deregistered = True
        if d > cutoff and (f.form in OPERATING_FORMS or (f.form == "8-K" and "2.02" in f.item_set)):
            operating = True
    return operating and not deregistered


def item_text(text: str, item: str, width: int = 1500) -> str:
    i = (text or "").find(f"Item {item}")
    return text[i:i + width] if i >= 0 else ""


def says_listing_transfer(text: str) -> bool:
    return bool(_TRANSFER_TEXT.search(text or ""))
```

In `classifier.py`, add a method and call it after the bankruptcy check and before the continued-filings override:

```python
    def _rename_or_transfer(self, cik, filings, observed):
        sub = self.edgar.submissions(cik)
        if not isinstance(sub, dict):
            return None
        old = renamed_near(sub, observed)
        transfer = False
        for f in filings:
            d = _parse_date(f.filing_date)
            if f.form.startswith("8-K") and "3.01" in f.item_set and d and abs((d - observed).days) <= 30:
                text = self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc)
                transfer = transfer or says_listing_transfer(item_text(text, "3.01"))
        if (old or transfer) and still_operating(filings, observed):
            why = f"renamed from {old!r}" if old else "3.01 notice announces a listing transfer"
            return f"Ticker change / listing transfer: {why}; company still reports results"
        return None
```

```python
        if observed:
            why = self._rename_or_transfer(resolution.cik, filings, observed)
            if why:
                return DelistRecord(
                    ticker=ticker.upper(), cik=resolution.cik,
                    observed_delist_date=observed_delist_date, crsp_code=304,
                    bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="high",
                    reason=why, evidence=evidence,
                )
```

`still_operating` is what keeps BLD, which was renamed "QXO Insulation, LLC" at its merger, out of this rule: it filed a Form 15 on 2026-07-13 and reported no results afterwards.

- [ ] **Step 4: Run.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS, including the golden cases LC, SKLZ and HYH.

- [ ] **Step 5: Commit.** `git commit -am "feat(classifier): renames and listing transfers are exchange transfers, not compliance failures"`

---

### Task 8: SPAC trust liquidations are scheduled ends

**Files:**
- Modify: `src/delist_detection/evidence.py`, `src/delist_detection/classifier.py`
- Test: `tests/test_evidence.py`, `tests/test_classifier.py`, `tests/test_golden_events.py`

**Interfaces:**
- Produces: `evidence.is_spac(sub, on) -> bool`. The classifier adds flag `spac` and emits code 600 with bucket `EXPIRATION`.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_evidence.py (append)
from delist_detection.evidence import is_spac


def test_is_spac_by_sic_or_name_at_the_date():
    assert is_spac({"sic": "6770", "name": "Blue Whale Acquisition Corp I"}, date(2023, 8, 11))
    assert is_spac({"sic": "6199", "name": "Far Peak Acquisition Corp"}, date(2023, 2, 1))
    desp = {"sic": "3711", "name": "Lucid Group", "formerNames": [
        {"name": "Churchill Capital Corp IV", "from": "2020-04-30T00:00:00.000Z", "to": "2021-07-23T00:00:00.000Z"}]}
    assert not is_spac(desp, date(2024, 1, 1))
```

```python
# tests/test_classifier.py (append)
class _SpacEdgar(_TextEdgar):
    def submissions(self, cik):
        return {"name": "Blue Whale Acquisition Corp I", "sic": "6770", "formerNames": []}


def test_spac_liquidation_is_expiration_even_with_a_late_filing_notice():
    fs = [
        EdgarSubmission("S1", "8-K", "2023-04-25", "2023-04-25", "3.01,9.01", "a.htm"),
        EdgarSubmission("S2", "NT 10-K", "2023-03-31", "", "", "n.htm"),
        EdgarSubmission("S3", "25-NSE", "2023-08-04", "", "", "p.xml"),
        EdgarSubmission("S4", "15-12G", "2023-08-14", "", "", "f.htm"),
    ]
    e = _SpacEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2023-08-11")
    assert rec.bucket is CrspBucket.EXPIRATION and rec.crsp_code == 600
    assert "spac" in rec.evidence["flags"]
```

In `tests/test_golden_events.py`, delete the Task 8 `XFAIL` entries.

- [ ] **Step 2: Run.** Expected: FAIL (ImportError; SPAC → 580).

- [ ] **Step 3: Implement.** In `evidence.py`:

```python
SPAC_SIC = "6770"
_SPAC_NAME = re.compile(r"\bacquisition\s+corp", re.I)


def is_spac(sub: dict, on: date) -> bool:
    return str(sub.get("sic") or "") == SPAC_SIC or bool(_SPAC_NAME.search(name_at(sub, on)))
```

The SIC check applies only while the name at the date also isn't an operating name. A de-SPACed company keeps its new SIC (for example 3711), so the SIC test alone is safe. For the name test, `name_at` returns the post-merger name after the rename date.

In `classify_ticker`, after the rename check:

```python
        if observed:
            sub = self.edgar.submissions(resolution.cik)
            if isinstance(sub, dict) and is_spac(sub, observed) and (delist_filing or dereg):
                flags.append("spac")
                return DelistRecord(
                    ticker=ticker.upper(), cik=resolution.cik,
                    observed_delist_date=observed_delist_date, crsp_code=600,
                    bucket=CrspBucket.EXPIRATION, confidence="high",
                    reason="SPAC trust liquidation (blank-check company, redeemed at trust value)",
                    evidence=evidence,
                )
```

Move `delist_filing`/`dereg` selection above this block if it isn't there already. `enrich` already turns EXPIRATION with a valid last close into `ASSUMED_PAR` (dlret 0).

- [ ] **Step 4: Run.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -am "feat(classifier): SPAC trust liquidations are scheduled ends (600), not distress"`

---

### Task 9: No evidence is not distress

**Files:**
- Modify: `src/delist_detection/evidence.py`, `src/delist_detection/classifier.py`, `src/delist_detection/reconstruction.py`
- Test: `tests/test_classifier.py`, `tests/test_reconstruction.py`, `tests/test_golden_events.py`

**Interfaces:**
- Produces:
  - `evidence.merger_evidence(filings, on, before=400, after=30) -> EdgarSubmission | None`
  - `evidence.cites_listing_deficiency(text) -> bool`
  - UNKNOWN records carry `evidence["deregistered"] = True` when a Form 25 or Form 15 exists.
  - `enrich` maps UNKNOWN + deregistered + valid last close to `ASSUMED_PAR`.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_classifier.py (append)
def test_form25_form15_with_a_merger_proxy_is_a_merger():
    fs = [
        EdgarSubmission("M1", "DEFM14A", "2015-08-20", "", "", "d.htm"),
        EdgarSubmission("M2", "25-NSE", "2015-11-18", "", "", "p.xml"),
        EdgarSubmission("M3", "8-K", "2015-11-18", "2015-11-18", "8.01,9.01", "a.htm"),
        EdgarSubmission("M4", "15-12G", "2015-11-30", "", "", "f.htm"),
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2015-11-18")
    assert rec.bucket is CrspBucket.MERGER


def test_form25_form15_with_2_01_alone_is_a_merger():
    fs = [
        EdgarSubmission("U1", "8-K", "2016-01-22", "2016-01-22", "1.01,2.01,9.01", "a.htm"),
        EdgarSubmission("U2", "25-NSE", "2016-01-22", "", "", "p.xml"),
        EdgarSubmission("U3", "15-12G", "2016-02-01", "", "", "f.htm"),
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2016-02-01")
    assert rec.bucket is CrspBucket.MERGER


def test_deregistration_without_any_evidence_is_unknown_not_liquidation(fake_edgar):
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(fake_edgar, TickerResolver(fake_edgar)).classify_ticker("LIQ", "2019-11-06")
    assert rec.bucket is CrspBucket.UNKNOWN
    assert rec.evidence["deregistered"] is True
    assert "no_evidence_default" in rec.evidence["flags"]


def test_a_3_01_notice_citing_a_deficiency_stays_compliance():
    fs = [
        EdgarSubmission("N1", "8-K", "2023-05-08", "2023-05-08", "3.01,8.01", "a.htm"),
        EdgarSubmission("N2", "25-NSE", "2023-05-10", "", "", "p.xml"),
    ]
    e = _TextEdgar(fs, {"N1": "Item 3.01 ... has not regained compliance with the minimum bid price requirement"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2023-05-10")
    assert rec.bucket is CrspBucket.COMPLIANCE_FAILURE
```

`test_liquidation_fingerprint` in `tests/test_classifier.py` asserts the old default (LIQ → 400). Replace its body with the `test_deregistration_without_any_evidence_is_unknown_not_liquidation` assertions and rename it. The docstring's reason ("-100% in training") applies to −90% too.

```python
# tests/test_reconstruction.py (append)
from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.dlret import DlretMethod
from delist_detection.reconstruction import enrich


def test_unknown_deregistered_with_a_price_is_assumed_par():
    rec = DelistRecord("LIQ", 1, "2019-11-06", None, CrspBucket.UNKNOWN, "low", "x",
                       {"deregistered": True, "flags": ["no_evidence_default"]})
    e = enrich(rec, last_trade_close=19.63)
    assert e.dlret == 0.0 and e.dlret_method is DlretMethod.ASSUMED_PAR


def test_unknown_without_deregistration_stays_blank():
    rec = DelistRecord("SKYF", None, "2021-08-24", None, CrspBucket.UNKNOWN, "none", "No CIK", {})
    e = enrich(rec, last_trade_close=0.001)
    assert e.dlret_method is DlretMethod.UNKNOWN
```

In `tests/test_golden_events.py`, delete the Task 9 `XFAIL` entries.

- [ ] **Step 2: Run.** Expected: FAIL.

- [ ] **Step 3: Implement.** In `evidence.py`:

```python
MERGER_EVIDENCE_FORMS = {"DEFM14A", "DEFM14C", "PREM14A", "SC 14D9", "SC TO-T", "425"}
_DEFICIENCY_TEXT = re.compile(
    r"minimum\s+bid\s+price|stockholders[’']?\s+equity\s+requirement|"
    r"market\s+value\s+of\s+(?:listed|publicly\s+held)|regain(?:ed)?\s+compliance|"
    r"not\s+in\s+compliance|failure\s+to\s+(?:timely\s+)?file|delinquen", re.I)


def merger_evidence(filings, on: date, before: int = 400, after: int = 30):
    lo, hi = on - timedelta(days=before), on + timedelta(days=after)
    hits = [f for f in filings if f.form in MERGER_EVIDENCE_FORMS
            and (d := parse_day(f.filing_date)) and lo <= d <= hi]
    return max(hits, key=lambda f: f.filing_date) if hits else None


def cites_listing_deficiency(text: str) -> bool:
    return bool(_DEFICIENCY_TEXT.search(text or ""))
```

In `classifier.py`, add one helper and route every "no conclusive fingerprint" return through it. Those returns are the four blocks today: "Form 15 deregistration without merger 8-K" (573), "Form 25 + Form 15, no merger 8-K" (400), "Form 25 present, no 8-K within window" (570), "Form 25 + Form 15, 8-K without M&A items" (400) and "8-K having no conclusive items; default compliance" (570).

```python
    def _default_without_fingerprint(self, ticker, cik, observed_delist_date, observed,
                                     filings, eightk, dereg, delist_filing, evidence, flags):
        def rec(code, bucket, conf, reason, **extra):
            return DelistRecord(ticker=ticker.upper(), cik=cik, observed_delist_date=observed_delist_date,
                                crsp_code=code, bucket=bucket, confidence=conf, reason=reason,
                                evidence={**evidence, **extra})
        # Ruling (Task 1 review): measure from the Form 25 when there is one. A frozen
        # vendor tail pushes `observed` past the deal (KCI: proxy 43 days before its
        # Form 25, 413 days before the vendor's last row).
        anchor = (_parse_date(delist_filing.filing_date) if delist_filing else None) or observed
        if eightk is not None and "2.01" in eightk.item_set and dereg is not None:
            return rec(233, CrspBucket.MERGER, "medium", "2.01 with Form 25 + Form 15 (acquisition completed)")
        proxy = merger_evidence(filings, anchor) if anchor else None
        if proxy is not None:
            return rec(231, CrspBucket.MERGER, "medium",
                       f"Merger filing {proxy.form} {proxy.filing_date} before the delisting")
        notice = ""
        if eightk is not None and "3.01" in eightk.item_set:
            notice = item_text(self.edgar.fetch_filing_text(cik, eightk.accession, eightk.primary_doc), "3.01")
        if cites_listing_deficiency(notice) or (anchor and self._detect_delinquent_filer(filings, anchor)):
            code = 580 if anchor and self._detect_delinquent_filer(filings, anchor) else 570
            return rec(code, CrspBucket.COMPLIANCE_FAILURE, "medium",
                       "Listing deficiency (3.01 notice text or NT 10-K/Q in the prior year)")
        flags.append("no_evidence_default")
        return rec(None, CrspBucket.UNKNOWN, "low",
                   "Delisted/deregistered without merger or distress evidence",
                   deregistered=bool(delist_filing or dereg))
```

In the main fingerprint branch, a `code == 570` from `_classify_items` (3.01 alone) must also pass the deficiency/delinquency test. Otherwise route it through `_default_without_fingerprint`. The existing `580` upgrade is folded into that helper.

In `reconstruction.enrich`, before the existing ASSUMED_PAR block:

```python
    if (record.bucket is CrspBucket.UNKNOWN and (record.evidence or {}).get("deregistered")
            and last_trade_close is not None and last_trade_close > 0):
        res = DlretResult(0.0, DlretMethod.ASSUMED_PAR, last_trade_close)
```

- [ ] **Step 4: Run.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS. `test_compliance_failure_classifies_correctly` needs its fixture to carry a deficiency: give `A002` a text in the conftest fake (`fetch_filing_text` returns "Item 3.01 ... minimum bid price" for `A002`).

- [ ] **Step 5: Commit.** `git commit -am "fix(classifier): a distress bucket needs evidence; takeovers without a closing 8-K are found by their proxy/tender filings"`

---

### Task 10: Payout reader: whole dollars, preferred redemptions, award payouts, elections, ties

**Files:**
- Modify: `src/delist_detection/payout_extractor.py`
- Test: `tests/test_payout_extractor.py`, `tests/test_golden_events.py`

**Interfaces:**
- Produces: `_collect(text, last_close, allow_weak)` and `_select(counts, mixed)` with the same signatures. `_select` returns `(None, False)` on a tie.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_payout_extractor.py (append)
def test_whole_dollar_cash_is_read():
    t = "each share was cancelled and converted into the right to receive $170 in cash, without interest"
    assert _match_payout(t)[0] == 170.0


def test_award_payout_multiplied_by_units_is_ignored():
    t = ("Veritiv paid each holder an amount in cash equal to $1.00 multiplied by the target number "
         "of performance-based units subject to such Company PBU Award")
    assert _match_payout(t)[0] is None


def test_preferred_redemption_is_ignored():
    t = ("converted into the right to receive an amount in cash equal to $12.00 per share. "
         "Following consummation, each outstanding share of TWO Preferred Stock will be redeemed "
         "on the applicable redemption date for $25.00 in cash, plus accumulated dividends")
    assert _match_payout(t)[0] == 12.0


def test_cash_or_stock_election_is_mixed():
    t = ("(i) an amount in cash equal to $505.00 per TopBuild Share (the Cash Consideration) or "
         "(ii) 20.200 shares of QXO common stock per TopBuild Share (the Stock Consideration)")
    counts, mixed, _ = _collect(t, None, True)
    assert _select(counts, mixed) == (None, True)


def test_a_tie_between_two_figures_abstains():
    assert _select({12.0: 1, 25.0: 1}, {}) == (None, False)


def test_six_decimal_cash_is_read_whole():
    t = "shareholders received a net cash payment of $10.389188 per share of common stock"
    assert _match_payout(t)[0] == 10.389188
```

The last case needs the long-decimal "cash payment of $X" pattern from Step 3. `test_match_in_cash_family_altr` (existing) must keep returning 113.00, because `_AMT` still refuses "$1,618.7928". In `tests/test_golden_events.py`, add a payout test and delete the Task 10 `XFAIL` entries:

```python
from delist_detection.payout_extractor import PayoutExtractor

PAYOUT_CASES = [c for c in CASES if c.expected_bucket == "merger" and c.expected_dlret is not None]


@pytest.mark.parametrize("case", PAYOUT_CASES, ids=[c.id for c in PAYOUT_CASES])
def test_golden_payout(case, monkeypatch, request):
    if case.id in XFAIL:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"fixed by Task {XFAIL[case.id]}"))
    rec = _classify(case, monkeypatch)
    pr = PayoutExtractor(GoldenEdgar(case)).extract(rec, last_close=case.last_trade_close)
    implied = (pr.value / case.last_trade_close - 1) if pr.value is not None else 0.0
    assert abs(implied - case.expected_dlret) <= case.dlret_tol, pr
```

For cases where the extractor abstains and the expected value is 0 within tolerance (assumed par), `implied` falls back to 0.0.

- [ ] **Step 2: Run.** Expected: FAIL on all six unit tests and on the VRTV, TWO and CPWR payouts.

- [ ] **Step 3: Implement.** In `payout_extractor.py`:

```python
# Whole dollars ("$170 in cash") or exactly two decimals. The lookahead still
# refuses a truncated "$1,618.79" out of "$1,618.7928" (ALTR's per-unit figure,
# which must not compete with the $113.00 consideration). Longer decimals are
# read only after "cash payment of", where they are the consideration itself
# (CPWR "net cash payment of $10.389188 per share").
_AMT = r"\$\s*([\d,]+(?:\.\d{2})?)(?!\.?\d)"
_AMT_LONG = r"\$\s*([\d,]+\.\d{2,6})(?!\d)"
_PATTERNS = [
    (re.compile(r"(?:right to receive|receive)\s+" + _AMT + r"\s+in\s+cash", re.I), False),
    (re.compile(r"in\s+cash\s+equal\s+to\s+" + _AMT, re.I), False),
    (re.compile(_AMT + r"\s+in\s+cash(?:,?\s+without\s+interest)?", re.I), False),
    (re.compile(r"cash\s+consideration\s+of\s+" + _AMT, re.I), False),
    (re.compile(r"cash\s+payment\s+of\s+" + _AMT_LONG, re.I), False),
    (re.compile(r"merger\s+consideration\s+of\s+" + _AMT, re.I), True),
    (re.compile(r"(?:purchase\s+price|price\s+per\s+share)\s+of\s+" + _AMT, re.I), True),
    (re.compile(_AMT + r"\s+(?:net\s+)?per\s+(?:[A-Za-z]+\s+){0,2}share", re.I), True),
]
# A figure that belongs to another security or to an award is not the common-share payout.
_CLASS_CONTEXT = re.compile(r"preferred\s+(?:stock|shares?)|depositary\s+shares|warrants?\b|redeem|redemption", re.I)
_CLASS_WINDOW = 120
_AWARD_AFTER = re.compile(r"^\s*(?:\([^)]*\)\s*)?multiplied\s+by|^[^.]{0,40}\b(?:PSU|RSU|PBU|option)s?\b", re.I)
_AWARD_WINDOW = 60
```

Also:
- Add the join word `or` for elections: `_MIXED_AFTER = re.compile(r"\b(?:and|plus|or)\b[^.;:]{0,30}?\b(?:\((?:[a-z]|[ivx]+)\)\s*)?" + _MIXED_RATIO + r"(?:\.\d+)?\b(?:\s+[\w,'’\-]+){0,7}?\s+" + _MIXED_EQUITY + r"\b", re.I)`. `_MIXED_RATIO` already accepts "20" and the new `(?:\.\d+)?` accepts "20.200".
- Raise `_MIXED_WINDOW` to 120 so BLD's "(the Cash Consideration) or (ii) 20.200 shares" lies inside it.

In `_collect`, after the `_NOTE_CONTEXT` check:

```python
            if _CLASS_CONTEXT.search(text[max(0, m.start() - _CLASS_WINDOW):m.start()]):
                continue
            if _AWARD_AFTER.search(text[m.end():m.end() + _AWARD_WINDOW]):
                continue
```

In `_select`, replace the modal pick:

Replace the whole body of `_select` after `if not counts:`:

```python
    top_n = max(counts.values())
    tied = sorted((v for v, n in counts.items() if n == top_n), reverse=True)
    # A mixed/election deal settles the ticker first: BLD's closing 8-K ties $505 with
    # the prorated $249.67, and both sit next to a stock leg.
    if any(mixed.get(v, 0) and 2 * mixed[v] >= counts[v] for v in tied) or \
       any(mc >= 2 for mc in mixed.values()):
        return None, True
    if len(tied) > 1 and tied[1] >= 0.25 * tied[0]:
        return None, False           # two comparable figures equally supported (TWO $25 vs $12): abstain
    return tied[0], False            # a lone winner, or the consideration beside a small contingent leg (CVR cap)
```

This keeps the existing rule "on a tie, the per-share consideration beats a small contingent leg" (APLS $41.00 + CVR). It abstains only when the tied figures are of comparable size.

Checked on 2026-09-16 against the real texts with these exact definitions:
- VRTV → 170.0
- TWO → 12.0
- CPWR → 10.389188
- BLD → mixed (abstain)
- the `altr_8k_201.txt` and `atvi_8k_201.txt` fixtures are unchanged (113.0, 95.0)

In the tier loop in `_extract`, a mixed deal still returns `_NONE` (unchanged). The value is written with `f"{pr.value:.2f}"` in `classify_universe.py`; change that to `f"{pr.value:.6g}"` so $10.389188 survives.

- [ ] **Step 4: Run.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS, including `tests/test_payout_golden.py` (the committed 8-K fixtures). If a golden fixture there changes value, read its text. Accept the change only if the new value is the per-common-share consideration.

- [ ] **Step 5: Commit.** `git commit -am "fix(payout): whole-dollar amounts, preferred/award/redemption guards, elections are mixed, ties abstain"`

---

### Task 11: Every payout is checked against the last close

**Files:**
- Create: `src/delist_detection/payout_gate.py`
- Modify: `scripts/classify_universe.py`
- Test: `tests/test_payout_gate.py`, `tests/test_golden_events.py`

**Interfaces:**
- Consumes: `MergerTerms` (`deal_type`, `cash_per_share`, `stock_ratio`, `acquirer_ticker`) and the `prices.close_on(ticker, date)` callable.
- Produces: `payout_gate.reconcile(regex_value, last_close, llm_terms, acquirer_price, tol) -> Reconciled`, where `Reconciled(cash, stock_ratio, acquirer_price, source, flags: tuple[str, ...])`.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_payout_gate.py
from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.payout_gate import reconcile


def _terms(deal_type, cash=None, ratio=None, ticker=None):
    return MergerTerms(deal_type, cash, ratio, None, ticker, "high", "8-K:x", "")


def test_a_payout_that_reconciles_is_kept():
    r = reconcile(170.0, 169.99, None, None, 0.15)
    assert (r.cash, r.source, r.flags) == (170.0, "regex", ())


def test_a_payout_far_from_the_last_close_is_dropped_for_the_llm_cash():
    r = reconcile(25.0, 12.18, _terms("cash", 12.0), None, 0.15)
    assert (r.cash, r.source) == (12.0, "llm")
    assert "payout_gate_failed:25" in r.flags


def test_no_reconciling_value_leaves_par():
    r = reconcile(61.5, 0.03, None, None, 0.15)
    assert r.cash is None and r.source == "none"
    assert "payout_gate_failed:61.5" in r.flags


def test_an_election_takes_the_leg_the_last_close_reconciles_with():
    # BLD: after the election deadline the stock traded at 20.2 x QXO
    r = reconcile(None, 354.53, _terms("election", 505.0, 20.2, "QXO"), 17.28, 0.15)
    assert (r.cash, r.stock_ratio, r.acquirer_price, r.source) == (None, 20.2, 17.28, "llm_election_stock")
```

- [ ] **Step 2: Run.** Expected: FAIL (ImportError).

- [ ] **Step 3: Implement.**

```python
# src/delist_detection/payout_gate.py
"""Check every merger payout against the last trade before it reaches the table.

A completed deal trades at its consideration, so a payout far from the last
close is a misread (VRTV $1.00 vs $169.99, TWO $25 vs $12.18) or a stale
vendor price (CAB $0.03). Either way the number must not become a return."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reconciled:
    cash: float | None
    stock_ratio: float | None
    acquirer_price: float | None
    source: str
    flags: tuple[str, ...]


def _fits(value: float | None, last_close: float, tol: float) -> bool:
    return value is not None and value > 0 and abs(value / last_close - 1.0) <= tol


def reconcile(regex_value, last_close, llm_terms, acquirer_price, tol) -> Reconciled:
    if last_close is None or last_close <= 0:
        return Reconciled(regex_value, None, None, "regex" if regex_value is not None else "none",
                          ("no_last_close",))
    flags: list[str] = []
    if regex_value is not None:
        if _fits(regex_value, last_close, tol):
            return Reconciled(regex_value, None, None, "regex", ())
        flags.append(f"payout_gate_failed:{regex_value:g}")
    if llm_terms is not None:
        cash, ratio = llm_terms.cash_per_share, llm_terms.stock_ratio
        stock = ratio * acquirer_price if ratio is not None and acquirer_price is not None else None
        if llm_terms.deal_type == "election":
            if _fits(stock, last_close, tol):
                return Reconciled(None, ratio, acquirer_price, "llm_election_stock", tuple(flags))
            if _fits(cash, last_close, tol):
                return Reconciled(cash, None, None, "llm_election_cash", tuple(flags))
        elif llm_terms.deal_type == "cash" and _fits(cash, last_close, tol):
            return Reconciled(cash, None, None, "llm", tuple(flags))
    return Reconciled(None, None, None, "none", tuple(flags))
```

In `scripts/classify_universe.py`:
1. Load `--last-trade-closes` before the loop (already done). Pass the close into the extractor: `extractor.extract(rec, last_close=_lookup(last_trades, rec.ticker.upper(), rec.observed_delist_date))`. Delete the comment claiming no last close is available.
2. After the loop, for every merger record, call `reconcile(...)`. Use the regex value, the last close (filled from `prices` as today), the LLM terms for the key, and `acquirer_price = prices.close_on(terms.acquirer_ticker or ACQUIRER_RENAMES..., date)` when the terms name one. Also:
   - Write `r.cash` into `payouts_map`, or delete the key when it is None.
   - For stock legs, write `merged_terms[key] = {"stock_ratio": r.stock_ratio, "acquirer_price": r.acquirer_price, "acquirer_ticker": terms.acquirer_ticker}`.
   - Keep `r.flags` in a dict `payout_flags[key]` for Task 12.
3. The existing "pure-cash recovered from LLM only when the regex found nothing" branch is replaced by `reconcile`. The existing cash+stock gate for `deal_type == "cash_and_stock"` / `"stock"` stays as it is.

In `tests/test_golden_events.py`, change `test_golden_payout` to run `reconcile` on the extractor's value, with the case's captured LLM terms when the fixture has them. Otherwise pass `None`. Assert on the reconciled cash or stock value. Delete the Task 11 `XFAIL` entry (BLD). BLD needs its LLM terms captured: extend `build_golden_fixtures.py` to store `LLMMergerTermsExtractor(...).extract(rec)` as `case["llm_terms"]` when `OPENAI_API_KEY` is set, and re-run it for BLD.

- [ ] **Step 4: Run.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -am "feat(payout): gate every payout on the last close; resolve elections by the leg the price reconciles with"`

---

### Task 12: `review_flags` column and `output/review.csv`

**Files:**
- Modify: `src/delist_detection/reconstruction.py`, `scripts/classify_universe.py`
- Test: `tests/test_reconstruction.py`

**Interfaces:**
- Produces:
  - `EnrichedDelistRecord.review_flags: tuple[str, ...]`
  - `enrich(..., extra_flags=())`
  - `build_dlret_table(..., payout_flags=None)`
  - `DLRET_TABLE_COLUMNS[-1] == "review_flags"`

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_reconstruction.py (append)
from delist_detection.reconstruction import DLRET_TABLE_COLUMNS, enriched_to_row


def test_review_flags_is_the_last_column_and_joins_flags():
    assert DLRET_TABLE_COLUMNS[-1] == "review_flags"
    rec = DelistRecord("X", 1, "2020-01-02", 570, CrspBucket.COMPLIANCE_FAILURE, "medium", "r",
                       {"flags": ["frozen_tail:120"]})
    e = enrich(rec, last_trade_close=58.97, extra_flags=("payout_gate_failed:25",))
    row = enriched_to_row(e)
    assert row["review_flags"] == "frozen_tail:120;payout_gate_failed:25;distress_at_normal_price"


def test_no_flags_is_an_empty_cell():
    rec = DelistRecord("Y", 1, "2020-01-02", 231, CrspBucket.MERGER, "high", "r", {})
    assert enriched_to_row(enrich(rec, last_trade_close=10.0, payout_per_share=10.0))["review_flags"] == ""
```

Update any existing test that asserts the exact `DLRET_TABLE_COLUMNS` list so it expects the appended column.

- [ ] **Step 2: Run.** Expected: FAIL.

- [ ] **Step 3: Implement.** In `reconstruction.py`:
- Add `review_flags: tuple[str, ...] = ()` as the last field of `EnrichedDelistRecord`.
- `DLRET_TABLE_COLUMNS.append("review_flags")`, written into the list literal.
- `enrich(..., extra_flags: Iterable[str] = ())`:

```python
    flags = list((record.evidence or {}).get("flags", [])) + list(extra_flags)
    if (record.bucket in (CrspBucket.COMPLIANCE_FAILURE, CrspBucket.LIQUIDATION)
            and last_trade_close is not None and last_trade_close >= 5.0):
        flags.append("distress_at_normal_price")
```

  Pass `review_flags=tuple(dict.fromkeys(flags))` to the constructor.
- `build_dlret_table(..., payout_flags=None)` passes `extra_flags=_lookup(payout_flags or {}, key, date) or ()`.
- `enriched_to_row` adds `"review_flags": ";".join(e.review_flags)`.

In `scripts/classify_universe.py`:
- Pass `payout_flags=payout_flags` to `build_dlret_table`.
- After writing the table, write `Path(args.dlret_output).with_name("review.csv")` with columns `ticker, observed_delist_date, bucket, dlret, review_flags, reason, cik, anchor_8k` for every row whose `review_flags` is non-empty.
- Print one count line per flag.

- [ ] **Step 4: Run.** `conda run -n rdagent4qlib pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit.** `git commit -am "feat(table): review_flags column and output/review.csv list every row the rules could not settle"`

---

### Task 13: Acceptance run on the qlib universe, then docs

Needs the companion plan's Task Q1 (`member_names.csv`) and Task Q2 (`--dlret-overrides none`).

- [ ] **Step 1: Rerun without hand corrections.** From qlib_practice, in the worktree of the companion plan:

```bash
PYTHONPATH=fetch_data_aplha/src conda run -n rdagent4qlib --no-capture-output \
  python fetch_data_aplha/cli.py build-dlret --extract-merger-terms-llm --dlret-overrides none
```

Expected: exit 0 and no `ABORTED`.

- [ ] **Step 2: Check the success criteria.** Record each result in the plan's Results section.
  1. Offline golden suite: 100% pass, and `XFAIL` is empty.
  2. Each of the 10 rows in `fetch_data_aplha/data/dlret_overrides.csv` matches the new output: same bucket, and `|dlret − override| ≤ 0.002`. BLD may instead carry `payout_gate_failed` with dlret 0.
  3. Compliance/liquidation rows with last close ≥ $5: down from 41. Each one left has a reason naming its evidence (1.03 text, 2.04 without 5.01, deficiency text, NT filing, revocation).
  4. No row has `|dlret| > 10`.
  5. Every row that differs from the committed `data/delist/dlret.csv` is listed in the run report (old → new bucket, reason, flags) and read by a person. Expected size: 60–100 rows.
  6. The rows flagged `member_name_mismatch` agree with the companion plan's identity check (Q3): every flagged ticker is on its list.

- [ ] **Step 3: Update the docs.**
  - `README.md` bucket-policy section: "A compliance or liquidation bucket needs positive evidence; without it a completed deregistration is `unknown` at par."
  - `docs/data-flow.md` trigger table: the new rule order from this plan's File Structure section.
  - `CLAUDE.md`: the test count, `--names`, `EdgarBlocked`, `output/review.csv`, and the golden fixtures builder.

- [ ] **Step 4: Commit.** `git commit -am "docs: evidence-based delisting rules, review flags, golden set"`

## Results

(filled in by Task 13)

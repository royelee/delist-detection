# Reset-4a: End-of-Era Resolver (first step) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A security whose registrant kept filing after it stopped trading is no longer called an exchange transfer by
default: the resolver reads the security-level evidence around the end first (a successor filing, a change in
control, a completed acquisition, a delisting notice) and only then falls back to today's transfer.

**Architecture:** A pure module, `end_of_era.py`, turns an issuer's EDGAR filings around a security's end into
`EraSignals` and decides an `EraVerdict` by trying the spec's branches in order. The classifier calls it where today's
continued-filings rule fires (and only there), and the delisting finder tells it whether the security still traded
after the end (branch 1). Everything else in the classifier, and the clip logic, is unchanged in this first step.

**Tech Stack:** Python ≥3.10, standard library, pytest (offline).

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md` ("The end-of-era resolver (the R1.3 fix)";
decisions 9 and 11). Roadmap: `docs/superpowers/plans/2026-10-02-delist-library-reset.md`, "reset-4a".

## Global Constraints

- Decisions 9 (adopted with reset-3) and 11 (adopted as proposed, 2026-10-02, overnight ruling) hold.
- The resolver is tried only where today's continued-filings rule fires (`classifier._detect_continued_filings`
  true); every other classification path is unchanged.
- Branch order: (1) still trading after the end → today's transfer; (2) a successor registration (8-K12B, 8-K12G3)
  → a transfer whose successor stage 9 finds; (3) a change in control (8-K item 5.01) → a merger; (4) a completed
  acquisition (8-K item 2.01) with a merger filing or a Form 25 → a merger; (5) a delisting notice (8-K item 3.01)
  whose text cites a listing deficiency → a compliance failure; (6) else today's continued-filings transfer.
- Windows around the end date: 8-K items, successor filings and Form 25s in [end − 30 d, end + 120 d]; merger
  filings (DEFM14A, DEFM14C, PREM14A, SC 14D9, SC TO-T, SC TO-I, SC 13E3, 425, S-4) in [end − 540 d, end + 30 d].
- The continued-filings reason string stays byte-for-byte as today for branch 6 (`lifecycle.CONTINUED_FILINGS` is
  its prefix and the scorecard and verdict read it).
- The golden events replay (`tests/test_golden_events.py`, 31 cases) stays green; a case that changes stops the task.
- Tests are offline. Python: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`; pytest with `-o addopts=""`.

## Rulings this plan makes

1. **Scope: the classifier's continued-filings step first.** The audit's left-view truth (117 rows) and the
   evidence study (2026-10-02) show 106 of the 116 left-view endings come from the continued-filings rule, which
   fires before the 8-K fingerprint is read: a merger target keeps filing for its debt, a bankrupt company from
   the OTC. Replacing that one step with the resolver's order fixes most of them. Consolidating the clip logic
   (`pipeline._ends_the_security`, `_continues_after`, `listing_status`) into the resolver, OpenFIGI's later
   ticker, new-CUSIP-in-fails evidence and closed-with-no-event securities that have no delisting row are left to
   a later step (reset-4a2).
2. **EDGAR-only evidence.** Measured on the 117 truths, this order with EDGAR evidence only is right on 77 (today:
   about 32); adding fails-to-deliver and OpenFIGI evidence reaches 81, not worth the extra machinery now.
3. **No bankruptcy branch.** A confirmed bankruptcy already wins earlier in the classifier (rule 5); an 8-K 1.03 tag
   whose text does not confirm a bankruptcy is deliberately not one (`test_a_1_03_tag_without_bankruptcy_text_is_not_a_bankruptcy`).
4. **A notice needs deficiency text.** Branch 5 reads the 3.01 text (`evidence.cites_listing_deficiency`), as the
   classifier's no-fingerprint default does, so a merger or transfer notice is not marked as distress (a harsh
   −1.0 label in qlib_practice).
5. **Branch 1 from the finder.** "Still trading after the end" is the finder's own `continued` (listed today, or a
   sighting more than 5 days after the Form 25 took effect); the no-Form-25 fallback runs only for securities not
   listed today, so it passes false.
6. **Expected floor drops.** Turning a false 0.0 transfer into a merger whose value is not yet found adds blank
   DLRETs and assumed-par fills (reset-4c's work) and may move endings to `ended_incomplete`. Task 5 may lower by
   hand only `R2.*`, `L1.ended_incomplete` and `L2.*` floor entries, with this reason; any other drop, and any golden
   `pass` case that breaks, stops the task.

## Measured (2026-10-02, the committed output `10119b1`)

- L1.left_view 120, L1.closed_no_event 49, R2.2.continued_filings_rule 136, R1.3.transfer_no_successor 126.
- Golden reset-4a cases (19, known_wrong): YHOO, EXBD, XON, WTW, LIZ, ACXM, DF, MNI, ESV, DRQ, MDC, SGP, ACF, BNI,
  UFS, CPN, CPGX, STN, LVNTA. Continuation cases also need successor links, which this step does not add.

## Review Focus

1. A security still trading after its Form 25 (a holding-company reorganization filing 8-K 5.01) must keep today's
   transfer, not become a merger (Task 2 and 3 tests).
2. A 3.01 notice that announces a merger or a listing transfer must not become a compliance failure (Task 2 test).
3. Filings outside the windows (a 5.01 two years earlier) must not count (Task 1 test).
4. An 8-K/A or 8-K12B must not leak its items into the 8-K item set (Task 1 test).
5. Branch 6 keeps today's exact reason, code and bucket (Task 2 test).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/delist_detection/end_of_era.py` (new) | `EraSignals` from filings around the end; `resolve` in branch order. Pure. |
| `src/delist_detection/classifier.py` | Rule 8 calls the resolver; `classify_event(..., trading_after=)`; `_deficiency_notice`. |
| `src/delist_detection/delistings.py` | The Form 25 path passes `trading_after=continued`. |

---

### Task 1: `end_of_era` — signals and the branch order

**Files:**
- Create: `src/delist_detection/end_of_era.py`
- Test: `tests/test_end_of_era.py` (new)

**Interfaces:**
- Consumes: `edgar.EdgarSubmission(accession, form, filing_date, report_date, items, primary_doc)` with `.item_set`;
  `crsp_codes.CrspBucket`.
- Produces: `end_of_era.EraSignals(trading_after, item_filed, successor_filing, merger_filing, delist_filing,
  deficiency_notice)`, `signals(filings, on, *, trading_after, deficiency_notice="") -> EraSignals`,
  `EraVerdict(branch, crsp_code, bucket, reason)`, `resolve(s, items_code) -> EraVerdict`, `CONTINUED`,
  `ITEMS_BEFORE_DAYS`, `ITEMS_AFTER_DAYS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_end_of_era.py`:

```python
from datetime import date

from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarSubmission
from delist_detection.end_of_era import CONTINUED, EraSignals, resolve, signals

END = date(2020, 11, 20)


def _f(form, day, items=""):
    return EdgarSubmission(f"A-{form}-{day}", form, day, "", items, "d.htm")


def _s(**kw):
    base = dict(trading_after=False, item_filed={}, successor_filing="", merger_filing="", delist_filing="",
                deficiency_notice="")
    return EraSignals(**{**base, **kw})


def test_signals_read_items_successors_and_form25s_inside_their_windows_only():
    s = signals([_f("8-K", "2020-11-02", "2.01,3.01,5.01"), _f("8-K", "2018-06-01", "5.01"),
                 _f("8-K/A", "2020-11-10", "1.03"), _f("8-K12B", "2020-12-01", "8.01"),
                 _f("25-NSE", "2020-11-03"), _f("DEFM14A", "2019-08-01"), _f("10-Q", "2021-08-05")],
                END, trading_after=False)
    assert s.item_filed == {"2.01": "2020-11-02", "3.01": "2020-11-02", "5.01": "2020-11-02", "1.03": "2020-11-10"}
    assert s.successor_filing == "8-K12B 2020-12-01" and s.delist_filing == "25-NSE 2020-11-03"
    assert s.merger_filing == "DEFM14A 2019-08-01"


def test_a_merger_filing_older_than_its_window_does_not_count():
    assert signals([_f("DEFM14A", "2018-01-02")], END, trading_after=False).merger_filing == ""


def test_still_trading_keeps_todays_transfer():
    v = resolve(_s(trading_after=True, item_filed={"5.01": "2020-11-02"}), 231)
    assert (v.branch, v.crsp_code, v.bucket, v.reason) == ("trading", 304, CrspBucket.EXCHANGE_TRANSFER, CONTINUED)


def test_a_successor_registration_is_a_transfer_whose_successor_is_searched():
    v = resolve(_s(successor_filing="8-K12B 2020-12-01", item_filed={"5.01": "2020-11-02"}), 231)
    assert (v.branch, v.bucket) == ("successor", CrspBucket.EXCHANGE_TRANSFER)
    assert v.reason.startswith("Successor registration 8-K12B 2020-12-01")


def test_a_change_in_control_is_a_merger_with_the_items_code():
    v = resolve(_s(item_filed={"2.01": "2020-11-02", "5.01": "2020-11-02"}), 233)
    assert (v.branch, v.crsp_code, v.bucket) == ("change_in_control", 233, CrspBucket.MERGER)
    assert resolve(_s(item_filed={"5.01": "2020-11-02"}), None).crsp_code == 231


def test_a_completed_acquisition_needs_a_merger_filing_or_a_form25():
    with_proxy = resolve(_s(item_filed={"2.01": "2020-11-02"}, merger_filing="DEFM14A 2020-08-01"), None)
    with_25 = resolve(_s(item_filed={"2.01": "2020-11-02"}, delist_filing="25-NSE 2020-11-03"), None)
    bare = resolve(_s(item_filed={"2.01": "2020-11-02"}), None)
    assert (with_proxy.branch, with_proxy.bucket, with_proxy.crsp_code) == ("completed_merger", CrspBucket.MERGER, 231)
    assert with_25.branch == "completed_merger"
    assert (bare.branch, bare.reason) == ("continued_filings", CONTINUED)


def test_a_deficiency_notice_is_a_compliance_failure_and_a_bare_notice_is_not():
    v = resolve(_s(item_filed={"3.01": "2020-11-02"}, deficiency_notice="8-K 2020-11-02"), None)
    assert (v.branch, v.crsp_code, v.bucket) == ("delisting_notice", 570, CrspBucket.COMPLIANCE_FAILURE)
    assert resolve(_s(item_filed={"3.01": "2020-11-02"}), None).branch == "continued_filings"


def test_nothing_else_keeps_todays_continued_filings_transfer():
    v = resolve(_s(), None)
    assert (v.branch, v.crsp_code, v.bucket, v.reason) == ("continued_filings", 304, CrspBucket.EXCHANGE_TRANSFER,
                                                           CONTINUED)
    assert CONTINUED == "Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)"
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_end_of_era.py -q -o addopts=""`
Expected: `No module named 'delist_detection.end_of_era'`.

- [ ] **Step 3: Write the module**

Create `src/delist_detection/end_of_era.py`:

```python
"""The end-of-era resolver, first step (spec: Delist Library Reset, "The end-of-era
resolver (the R1.3 fix)"): what happened to a security whose registrant kept filing
periodic reports after the security stopped trading. The classifier used to call
every such case an exchange transfer (its continued-filings rule), and the reset-1
accuracy audit found most of them false: a merger target keeps filing for its debt,
a delisted company keeps filing from the OTC. The resolver reads the evidence
around the end first, in the spec's order:

1. still trading after the end (the delisting finder knows): today's transfer;
2. a successor registration (8-K12B, 8-K12G3): a transfer, its successor found later;
3. a change in control (8-K item 5.01): a merger;
4. a completed acquisition (8-K item 2.01) with a merger filing or a Form 25: a merger;
5. a delisting notice (8-K item 3.01) whose text cites a listing deficiency: a
   compliance failure;
6. otherwise the continued filings stand: today's transfer, reason unchanged.

Measured on the audit's 117 left-view truths (2026-10-02), today's rule is right on
the continuations only (about 32); this order is right on about 77. Pure, on EDGAR
filing lists; the classifier supplies the 3.01 text check."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from .crsp_codes import CrspBucket
from .edgar import EdgarSubmission

ITEMS_BEFORE_DAYS, ITEMS_AFTER_DAYS = 30, 120          # 8-K items, successor filings, Form 25s around the end
MERGER_FILING_BEFORE_DAYS, MERGER_FILING_AFTER_DAYS = 540, 30
SUCCESSOR_FORMS = frozenset({"8-K12B", "8-K12G3"})
MERGER_FILING_FORMS = frozenset({"DEFM14A", "DEFM14C", "PREM14A", "SC 14D9", "SC TO-T", "SC TO-I", "SC 13E3",
                                 "425", "S-4"})
DELIST_FORMS = frozenset({"25-NSE", "25"})
MERGER_CODES = frozenset({200, 231, 233})
CONTINUED = "Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)"


@dataclass(frozen=True)
class EraSignals:
    trading_after: bool
    item_filed: Mapping[str, str] = field(default_factory=dict)   # 8-K item -> its first filing date in the window
    successor_filing: str = ""        # "<form> <date>" of the first 8-K12B/8-K12G3 in the window
    merger_filing: str = ""           # "<form> <date>" of the latest merger filing in its window
    delist_filing: str = ""           # "<form> <date>" of the first Form 25 in the window
    deficiency_notice: str = ""       # "8-K <date>" of the first 3.01 notice citing a listing deficiency


@dataclass(frozen=True)
class EraVerdict:
    branch: str                       # trading, successor, change_in_control, completed_merger, delisting_notice,
    crsp_code: int                    # or continued_filings
    bucket: CrspBucket
    reason: str


def _day(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def signals(filings: Iterable[EdgarSubmission], on: date, *, trading_after: bool,
            deficiency_notice: str = "") -> EraSignals:
    """The evidence around a security's end date `on`: the items of every 8-K (not
    an 8-K12B/8-K12G3) filed in [on − ITEMS_BEFORE_DAYS, on + ITEMS_AFTER_DAYS], the
    first successor registration and Form 25 in that window, and the latest merger
    filing in [on − MERGER_FILING_BEFORE_DAYS, on + MERGER_FILING_AFTER_DAYS]."""
    lo, hi = on - timedelta(days=ITEMS_BEFORE_DAYS), on + timedelta(days=ITEMS_AFTER_DAYS)
    mlo, mhi = on - timedelta(days=MERGER_FILING_BEFORE_DAYS), on + timedelta(days=MERGER_FILING_AFTER_DAYS)
    item_filed: dict[str, str] = {}
    successor = merger = delist = ""
    for f in sorted(filings, key=lambda f: f.filing_date):
        d = _day(f.filing_date)
        if d is None:
            continue
        if lo <= d <= hi:
            if f.form in SUCCESSOR_FORMS:
                successor = successor or f"{f.form} {f.filing_date}"
            elif f.form.startswith("8-K"):
                for item in sorted(f.item_set):
                    item_filed.setdefault(item, f.filing_date)
            if f.form in DELIST_FORMS:
                delist = delist or f"{f.form} {f.filing_date}"
        if mlo <= d <= mhi and f.form in MERGER_FILING_FORMS:
            merger = f"{f.form} {f.filing_date}"
    return EraSignals(trading_after, item_filed, successor, merger, delist, deficiency_notice)


def resolve(s: EraSignals, items_code: int | None) -> EraVerdict:
    """The branch that decides (module docstring). `items_code` is the classifier's
    code for the window's 8-K item set (`_classify_items`); a merger keeps it when it
    is a merger code, else 231."""
    merger_code = items_code if items_code in MERGER_CODES else 231
    kept = "; the registrant kept filing after it"
    if s.trading_after:
        return EraVerdict("trading", 304, CrspBucket.EXCHANGE_TRANSFER, CONTINUED)
    if s.successor_filing:
        return EraVerdict("successor", 304, CrspBucket.EXCHANGE_TRANSFER,
                          f"Successor registration {s.successor_filing}: the security continues under a successor")
    if "5.01" in s.item_filed:
        return EraVerdict("change_in_control", merger_code, CrspBucket.MERGER,
                          f"Change in control (8-K item 5.01 filed {s.item_filed['5.01']}){kept}")
    if "2.01" in s.item_filed and (s.merger_filing or s.delist_filing):
        return EraVerdict("completed_merger", merger_code, CrspBucket.MERGER,
                          f"Completed acquisition (8-K item 2.01 filed {s.item_filed['2.01']}, "
                          f"{s.merger_filing or s.delist_filing}){kept}")
    if "3.01" in s.item_filed and s.deficiency_notice:
        return EraVerdict("delisting_notice", 570, CrspBucket.COMPLIANCE_FAILURE,
                          f"Listing deficiency notice ({s.deficiency_notice}), no merger evidence{kept}")
    return EraVerdict("continued_filings", 304, CrspBucket.EXCHANGE_TRANSFER, CONTINUED)
```

- [ ] **Step 4: Run the tests**

Run the file — all pass. Full suite: expected `1656 passed, 24 xfailed` (1648 + 8).

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/end_of_era.py tests/test_end_of_era.py
git commit -m "end_of_era: the resolver's branch order over EDGAR evidence (reset-4a)"
```

---

### Task 2: The classifier asks the resolver where the continued-filings rule fired

**Files:**
- Modify: `src/delist_detection/classifier.py` (`classify_event`, `_classify_resolved`, rule 8, a new `_deficiency_notice`)
- Test: `tests/test_classifier.py`

**Interfaces:**
- Consumes: `end_of_era.signals`, `resolve`, `ITEMS_BEFORE_DAYS`, `ITEMS_AFTER_DAYS`.
- Produces: `DelistClassifier.classify_event(..., trading_after: bool = False)`; the record's
  `evidence["end_of_era"]` (the branch).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_classifier.py` (it already defines `_TextEdgar` and imports `EdgarSubmission`):

```python
def _era_classify(filings, texts=None, *, trading_after=False):
    e = _TextEdgar(filings, texts or {})
    from delist_detection.ticker_resolver import TickerResolver
    return DelistClassifier(e, TickerResolver(e)).classify_event(
        ticker="REORG", cik=5, anchor_date="2020-11-20", trading_after=trading_after)


_KEPT_FILING = EdgarSubmission("Q1", "10-Q", "2021-08-05", "", "", "q.htm")     # > 180 days after the end


def test_a_change_in_control_beats_the_continued_filings_rule():
    rec = _era_classify([EdgarSubmission("K1", "8-K", "2020-11-02", "", "2.01,3.01,5.01", "k.htm"),
                         EdgarSubmission("F1", "25-NSE", "2020-11-03", "", "", "p.xml"), _KEPT_FILING])
    assert (rec.bucket, rec.crsp_code) == (CrspBucket.MERGER, 231)
    assert rec.reason.startswith("Change in control") and rec.evidence["end_of_era"] == "change_in_control"


def test_a_completed_acquisition_with_a_proxy_is_a_merger():
    rec = _era_classify([EdgarSubmission("P1", "DEFM14A", "2020-08-01", "", "", "p.htm"),
                         EdgarSubmission("K1", "8-K", "2020-11-02", "", "2.01,9.01", "k.htm"), _KEPT_FILING])
    assert (rec.bucket, rec.crsp_code) == (CrspBucket.MERGER, 231) and rec.reason.startswith("Completed acquisition")


def test_a_deficiency_notice_is_a_compliance_failure_and_a_merger_notice_is_not():
    k = EdgarSubmission("K1", "8-K", "2020-11-02", "", "3.01", "k.htm")
    bad = _era_classify([k, _KEPT_FILING], {"K1": "Item 3.01 Notice of Delisting. The Company is not in compliance "
                                                   "with the minimum bid price requirement."})
    other = _era_classify([k, _KEPT_FILING], {"K1": "Item 3.01 Notice of Delisting. In connection with the merger, "
                                                     "the Company notified the exchange."})
    assert (bad.bucket, bad.crsp_code) == (CrspBucket.COMPLIANCE_FAILURE, 570)
    assert (other.bucket, other.crsp_code) == (CrspBucket.EXCHANGE_TRANSFER, 304)
    assert other.reason.startswith("Continued 10-K/Q filings")


def test_a_security_still_trading_keeps_todays_transfer():
    rec = _era_classify([EdgarSubmission("K1", "8-K", "2020-11-02", "", "5.01", "k.htm"), _KEPT_FILING],
                        trading_after=True)
    assert (rec.bucket, rec.crsp_code) == (CrspBucket.EXCHANGE_TRANSFER, 304)
    assert rec.reason == "Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)"


def test_continued_filings_alone_keep_todays_reason():
    rec = _era_classify([_KEPT_FILING])
    assert (rec.bucket, rec.crsp_code, rec.confidence) == (CrspBucket.EXCHANGE_TRANSFER, 304, "medium")
    assert rec.reason == "Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)"
    assert rec.evidence["end_of_era"] == "continued_filings"
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_classifier.py -q -o addopts=""`
Expected: `classify_event() got an unexpected keyword argument 'trading_after'`.

- [ ] **Step 3: Implement**

In `src/delist_detection/classifier.py`:

1. Add `from . import end_of_era` with the other relative imports.
2. `classify_event`: add the keyword parameter `trading_after: bool = False` (after `resolution_source`), say in its
   docstring "`trading_after`: the security still traded after the end (the delisting finder's `continued`); the
   end-of-era resolver then keeps today's transfer", and pass `trading_after=trading_after` to `_classify_resolved`.
3. `_classify_resolved`: add the keyword parameter `trading_after: bool = False` after `delist_filing_override`.
4. Add, after `_detect_delinquent_filer`:

```python
    def _deficiency_notice(self, cik: int, filings: list[EdgarSubmission], on: date) -> str:
        """`"8-K <date>"` of the first 8-K with item 3.01 in the resolver's window
        around `on` whose 3.01 text cites a listing deficiency, else ""."""
        lo = on - timedelta(days=end_of_era.ITEMS_BEFORE_DAYS)
        hi = on + timedelta(days=end_of_era.ITEMS_AFTER_DAYS)
        for f in sorted(filings, key=lambda f: f.filing_date):
            if not f.form.startswith("8-K") or "3.01" not in f.item_set:
                continue
            d = _parse_date(f.filing_date)
            if d is None or not lo <= d <= hi:
                continue
            text = self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc)
            if cites_listing_deficiency(item_text(text, "3.01")):
                return f"8-K {f.filing_date}"
        return ""
```

   (`_parse_date` is the module's existing date helper; if its name differs, use the helper `_classify_resolved`
   uses to parse `observed_delist_date`, and say so in the report.)
5. Replace rule 8:

```python
        # Exchange-transfer override is the strongest single signal —
        # check it BEFORE the Form-25-or-not branches.
        if observed and self._detect_continued_filings(filings, observed):
            return DelistRecord(
                ticker=ticker.upper(),
                cik=resolution.cik,
                observed_delist_date=observed_delist_date,
                crsp_code=304,
                bucket=CrspBucket.EXCHANGE_TRANSFER,
                confidence="medium",
                reason="Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)",
                evidence=evidence,
            )
```

   with

```python
        # The registrant kept filing after the end: the end-of-era resolver reads the
        # evidence around the end (a successor filing, a change in control, a completed
        # acquisition, a deficiency notice) before calling it an exchange transfer.
        if observed and self._detect_continued_filings(filings, observed):
            era = end_of_era.signals(filings, observed, trading_after=trading_after,
                                     deficiency_notice=self._deficiency_notice(resolution.cik, filings, observed))
            items_code, _ = self._classify_items(set(era.item_filed))
            verdict = end_of_era.resolve(era, items_code)
            evidence["end_of_era"] = verdict.branch
            return DelistRecord(
                ticker=ticker.upper(),
                cik=resolution.cik,
                observed_delist_date=observed_delist_date,
                crsp_code=verdict.crsp_code,
                bucket=verdict.bucket,
                confidence="medium",
                reason=verdict.reason,
                evidence=evidence,
            )
```

- [ ] **Step 4: Run the tests**

Run `tests/test_classifier.py`, `tests/test_golden_events.py` and `tests/test_delistings.py` — all pass. If a golden
events case or an existing classifier test changes outcome, stop and report NEEDS_CONTEXT with the case and both
outcomes; do not edit its expectation. Full suite: expected `1661 passed, 24 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/classifier.py tests/test_classifier.py
git commit -m "classifier: the end-of-era resolver decides where filings continued (reset-4a)"
```

---

### Task 3: The finder says whether the security still traded

**Files:**
- Modify: `src/delist_detection/delistings.py` (`_build_delisting`)
- Test: `tests/test_delistings.py`

**Interfaces:**
- Consumes: `classify_event(..., trading_after=)` (Task 2).

- [ ] **Step 1: Write the failing test**

In `tests/test_delistings.py`, find the test `test_successor_is_itself_when_continued` and write beside it a test
that uses the same fixture with a classifier double that records the keyword arguments `classify_event` receives:
the Form 25 path must pass `trading_after=True` when the security is listed today (`continued`), `False` when it is
not, and the no-Form-25 fallback must pass `False` (or omit it). Reuse the file's own fixtures and doubles; if no
classifier double exists, wrap the file's classifier in one that delegates and records `kwargs`.

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py -q -o addopts=""`
Expected: the recorded `trading_after` is missing.

- [ ] **Step 3: Implement**

In `_build_delisting`, add `trading_after=continued` to the `self.classifier.classify_event(...)` call. Leave the
fallback call unchanged (it runs only for a security not listed today). Any classifier double in the tests whose
`classify_event` does not accept `**kwargs` must take the new keyword; update those doubles, and name them in the
report.

- [ ] **Step 4: Run the tests**

Run `tests/test_delistings.py` and `tests/test_pipeline.py` — all pass. Full suite: expected `1662 passed, 24 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/delistings.py tests/test_delistings.py
git commit -m "delistings: the finder tells the resolver whether the security still traded (reset-4a)"
```

---

### Task 4: Docs

**Files:** `CLAUDE.md`, `README.md`, `docs/data-flow.md`, `CONTEXT.md` (docs only).

- [ ] **Step 1:** CLAUDE.md: in the Classification list, after the `classifier.py` bullet, add a bullet for
  `end_of_era.py` (the resolver's first step: where the registrant kept filing after the end, the branch order of
  Global Constraints, and that branch 6 keeps today's continued-filings transfer). In the `classifier.py` bullet,
  say the continued-filings rule now asks the resolver. Update the pytest count to the suite's real numbers.
- [ ] **Step 2:** README.md and docs/data-flow.md: wherever the classifier's rules or trigger table list the
  continued-filings rule, replace its one line with the resolver's six branches and their outcomes (code, bucket).
- [ ] **Step 3:** CONTEXT.md: add **End of era** — the last date a security's history is known, and what happened
  next (still trading, a new exchange, a new ticker or CUSIP, a merger, a liquidation, or unknown).
- [ ] **Step 4:** Run the full suite once, then commit:

```bash
git add CLAUDE.md README.md docs/data-flow.md CONTEXT.md
git commit -m "docs: the end-of-era resolver's first step (reset-4a)"
```

---

### Task 5: Acceptance rebuild (network)

**Files:** `output/**`, `data/scorecard.json`, `data/golden_lifecycles.csv`,
`docs/superpowers/plans/2026-10-02-delist-library-reset.md`.

- [ ] **Step 1:** Check no other SEC client runs (`ls -la /tmp/claude/delist_detection/sec_rate.lock
  ~/.cache/delist_detection/sec_rate.lock`: neither modified in the last few minutes).
- [ ] **Step 2:** Rebuild into `.superpowers/sdd/reset4a-acceptance` with
  `--as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm --id-baseline output/securities.csv` and
  `DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock`, allowing all seven hosts
  (data.sec.gov, www.sec.gov, efts.sec.gov, api.openfigi.com, api.nasdaq.com, www.nasdaqtrader.com, api.openai.com).
  Stop on any sandbox denial, a non-zero exit, or a refusal.
- [ ] **Step 3:** Compare with the committed output: count changed rows per table and the endings whose bucket
  changed (from → to, by resolver branch, from `delistings.csv` reasons). Compare the scorecard: `L1.left_view`,
  `R2.2.continued_filings_rule` and `R1.3.transfer_no_successor` must fall. Run the golden tests: a `pass` case that
  now fails is a stop; flip every `known_wrong` case that now passes to `pass` (clear `fixed_by`, `library_says`).
- [ ] **Step 4:** The run's stderr lists floor drops. Lower by hand only `R2.*`, `L1.ended_incomplete` and `L2.*`
  entries, to today's values, with the reason "reset-4a turns false transfers into mergers and distress endings
  whose values reset-4c and reset-4d still have to find". Any other drop is a stop. Then publish (every table,
  `contract/*.csv`, scorecard.json, run_manifest.json, the stderr as run.log after a secrets check),
  `scripts/scorecard.py --raise-floor --write`, the full suite.
- [ ] **Step 5:** Under "reset-4a" in the roadmap add a "Done (first step)" bullet: the plan file, decision 11's
  overnight ruling, the moved numbers (left view, continued-filings rule, coverage, the golden flips), the floor
  entries lowered and why, and what is left for reset-4a2 (Ruling 1). Commit:

```bash
git add output data/scorecard.json data/golden_lifecycles.csv docs/superpowers/plans/2026-10-02-delist-library-reset.md
git commit -m "Acceptance: the end-of-era resolver's first step (reset-4a)"
```

---

### Task 6 (added during execution, 2026-10-02): resolver endings stay uncertain

Task 5's first rebuild (left view 120 → 63, audit left-view errors 114 → 76) showed 13 audit rows becoming
confirmed but wrong: they were wrong before, under the continued-filings rule's uncertain reason, and lost that
reason when the resolver relabelled them. Until reset-4a2 adds security-level checks (a later sighting of the same
issuer, a new CUSIP, OpenFIGI's later ticker), an ending the resolver relabelled stays uncertain.

**Files:**
- Modify: `src/delist_detection/lifecycle.py` (a constant), `src/delist_detection/end_of_era.py`, `src/delist_detection/verdict.py`
- Test: `tests/test_end_of_era.py`, `tests/test_verdict.py`

**Interfaces:**
- Produces: `lifecycle.RESOLVED_FROM_CONTINUED_FILINGS = "; the registrant kept filing after it"`; every resolver
  reason except branch 1 and branch 6 contains it; `verdict._ending_reasons` adds `resolved_from_continued_filings`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_end_of_era.py`:

```python
from delist_detection.lifecycle import RESOLVED_FROM_CONTINUED_FILINGS


def test_every_relabelled_ending_says_the_registrant_kept_filing():
    for s in (_s(successor_filing="8-K12B 2020-12-01"), _s(item_filed={"5.01": "2020-11-02"}),
              _s(item_filed={"2.01": "2020-11-02"}, delist_filing="25-NSE 2020-11-03"),
              _s(item_filed={"3.01": "2020-11-02"}, deficiency_notice="8-K 2020-11-02")):
        assert RESOLVED_FROM_CONTINUED_FILINGS in resolve(s, None).reason
    assert RESOLVED_FROM_CONTINUED_FILINGS not in resolve(_s(), None).reason
```

Add to `tests/test_verdict.py`:

```python
def test_an_ending_the_resolver_relabelled_stays_uncertain():
    t = tables([sec("S")], [iv("S", "AAA", "2010-01-04", "2020-11-19")],
               [ending("S", "2020-11-30", ltd="2020-11-19", dlret="0.100000",
                       reason="Change in control (8-K item 5.01 filed 2020-11-02); the registrant kept filing after it")],
               [obs("AAA", "2010-01-04", "S")])
    assert "resolved_from_continued_filings" in decide(t, {}).endings[("S", "2020-11-30")].reasons
```

- [ ] **Step 2:** Run both files; expect an ImportError on `RESOLVED_FROM_CONTINUED_FILINGS` and the verdict test
  failing.
- [ ] **Step 3: Implement.** In `lifecycle.py`, after `CONTINUED_FILINGS`, add
  `RESOLVED_FROM_CONTINUED_FILINGS = "; the registrant kept filing after it"   # end_of_era's relabelled endings`.
  In `end_of_era.py`, import it, replace the local `kept` with it, and end the successor branch's reason with it
  too (`f"Successor registration {s.successor_filing}: the security continues under a successor{RESOLVED_FROM_CONTINUED_FILINGS}"`);
  update the existing successor test's `startswith` if needed (it checks only the start). In `verdict.py`, import it
  and in `_ending_reasons`, after the `continued_filings_rule` check, add
  `if RESOLVED_FROM_CONTINUED_FILINGS in row["reason"]: reasons.append("resolved_from_continued_filings")`; list the
  new reason in the module docstring's ending paragraph ("an ending the end-of-era resolver relabelled from the
  continued-filings rule stays uncertain until its security-level checks exist").
- [ ] **Step 4:** Run `tests/test_end_of_era.py`, `tests/test_verdict.py`, `tests/test_classifier.py`, then the full
  suite (expect 1665 passed, 24 xfailed).
- [ ] **Step 5: Commit** — `git commit -m "verdict: endings the resolver relabelled stay uncertain (reset-4a)"`

## Self-review

- **Spec coverage.** Branch order 1–6 of the spec's resolver table, restricted to the continued-filings case
  (Ruling 1); branch 1 from the finder (Ruling 5); branch 3's new-ticker evidence and branch 2 (new exchange) are
  not here (reset-4a2); branch 6's "uncertain" stays the existing verdict (`continued_filings_rule`).
- **Types.** `EraSignals`/`signals`/`resolve`/`EraVerdict` (Task 1) are what Task 2 calls; `trading_after` is the
  same keyword in Tasks 2 and 3.
- **Counts.** 8, 5 and 1 new tests (1656, 1661, 1662).
</content>
</invoke>

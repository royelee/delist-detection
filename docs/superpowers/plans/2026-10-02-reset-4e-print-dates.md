# Reset-4e (first step): Exchange-Print Dates the Caches Already Hold — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a last trade date for the endings whose exchange-print evidence is already cached but unread: the
8-K item 3.01 wordings the parser does not know, and the continuation rows the handoff stage adds from an unmatched
Form 25 without reading that Form 25's notice.

**Architecture:** Widen `last_trade._OPEN` to the four wordings found; date each continuation row the handoff stage
adds from its own Form 25's notice (`form25.parse_form25`, `notice_last_trade`, `last_trade.decide_last_trade`) in a
small pipeline step right after the handoff stage.

**Tech Stack:** Python ≥3.10, pytest (offline).

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md` ("delistings": `last_trade_date` only from an
exchange-print source, never after the Form 25 effective date; decision 12). Roadmap: "reset-4e: Missing last trade dates".

## Global Constraints

- Decision 12 adopted (reset-3). Only exchange-print sources count (MIDAS, the Form 25's EX-99 notice, 8-K item 3.01,
  a Nasdaq halt); a fails-to-deliver row is not a print.
- "Suspended before the open on D" means the last trade day is the trading day before D (`previous_trading_day`).
- A continuation row keeps its `last_sighting` day unless its Form 25's notice gives a confirmed day
  (`decide_last_trade` returns no `last_trade_date_unconfirmed` flag).
- Tests are offline. Python: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`; pytest with `-o addopts=""`.

## Rulings this plan makes

1. **Scope.** The reset-4e research (2026-10-02, offline, 148 endings with a blank published date) found 19 datable
   from the caches: 10 continuation rows built by the handoff stage from an unmatched Form 25 whose cached EX-99.25
   notice states a date (S, NLSN, XL, ST, AON 2020, CR, J, LIN, LH, APTV); 6 8-K 3.01 texts in wordings the parser lacks
   ("suspended prior to the market opening on D" GOOGL, GOOG, XRX; "prior to the commencement of trading on D" WTNY;
   "as of the open of business on D" ANAT; "suspended at the opening of business on D" ENDPQ); MTCH 2020 (already
   parsed), PHLY (a cached halt outside the ±2-day halt window) and AON 2012 (MIDAS equals the sighting). This step
   takes the first two groups. 129 endings have no exchange-print source in the cache: 52 still trade in MIDAS after
   the effective date (probably not endings: reset-4a2), 33 predate MIDAS, 17 have only an event-day sentence.
2. **Permitted floor drops.** New dates can change closes and values: `R2.*` and `L2.*` may be lowered by hand with the
   reason "reset-4e dates more endings from exchange prints, which moves their closes". Any other drop, or a golden
   `pass` case that breaks, stops the acceptance.

## Review Focus

1. A 3.01 sentence saying "on D" about something other than suspension (a notice received on D) must not match
   (Task 1 test).
2. A continuation row whose Form 25 notice is unconfirmed keeps its `last_sighting` day (Task 2 test).

---

### Task 1: The 8-K wordings

**Files:** Modify `src/delist_detection/last_trade.py`; Test `tests/test_last_trade.py`.

- [ ] **Step 1: Write the failing test.** Append to `tests/test_last_trade.py` (it has `_k(item301, extra="")`, which
  wraps text as an 8-K's item 3.01; add `import pytest` at the top):

```python
@pytest.mark.parametrize("sentence, last_day", [
    ("trading in the shares will be suspended prior to the market opening on October 2, 2015", date(2015, 10, 1)),
    ("the common stock will be suspended prior to the commencement of trading on July 2, 2018", date(2018, 6, 29)),
    ("the listing will be suspended as of the open of business on July 1, 2020", date(2020, 6, 30)),
    ("trading was suspended at the opening of business on August 18, 2022", date(2022, 8, 17)),
])
def test_eightk_suspension_before_the_open_in_other_words(sentence, last_day):
    """GOOGL/GOOG/XRX, WTNY, ANAT and ENDPQ's 8-K wordings: the last trade day
    is the trading day before D (July 2, 2018 is a Monday)."""
    assert eightk_last_trade(_k(sentence)) == (last_day, "8k_open")


def test_a_notice_received_on_a_day_is_not_a_suspension():
    assert eightk_last_trade(_k("On August 18, 2022, the Company received a notice from the Exchange")) == (None, "")
```
- [ ] **Step 2:** Run the file: the new cases fail.
- [ ] **Step 3: Implement.** In `src/delist_detection/last_trade.py`, replace `_OPEN` with:

```python
_OPEN = (r"(?:(?:prior to|before) (?:the )?(?:(?:market )?open(?:ing)?|commencement of trading)"
         r"(?: of (?:the )?(?:trading|market|business))?"
         r"|(?:as of|at) the open(?:ing)? of business)")
```

  (the old wordings stay matched: "prior to the opening of trading", "before the open"). Keep `test_eightk_phrases`
  green.
- [ ] **Step 4:** Run `tests/test_last_trade.py`, `tests/test_golden_events.py`, `tests/test_classifier.py`, then the full
  suite. A golden events case that changes outcome stops the task (report NEEDS_CONTEXT).
- [ ] **Step 5: Commit** — `git commit -m "last_trade: four more ways of saying suspended before the open (reset-4e)"`

---

### Task 2: Date the handoff stage's continuation rows from their Form 25 notice

**Files:** Modify `src/delist_detection/pipeline.py`; Test `tests/test_pipeline.py`.

**Interfaces:** Consumes `form25.parse_form25(raw, *, accession, form, filing_date)`, `form25.notice_last_trade(f25)`,
`last_trade.decide_last_trade(*, notice, eightk, midas, halt)`, `edgar.fetch_filing_raw(cik, accession)`. Produces
`pipeline._date_from_notices(ctx, added: list[Delisting]) -> int` (rows re-dated).

- [ ] **Step 1: Write the failing test.** No pipeline test builds a continuation from an unmatched Form 25, so test
  the step directly. `tests/fixtures/form25/leg_25nse_before_market_open.txt` is a raw Form 25 whose EX-99.25 notice
  `notice_last_trade` dates `(date(2026, 8, 26), "notice_open")` (tests/test_form25.py). Append to
  `tests/test_pipeline.py` (reuse its imports; `Delisting` from `delist_detection.delistings`, `DelistRecord` from
  `delist_detection.classifier`, `CrspBucket` from `delist_detection.crsp_codes`, `LastTrade` from
  `delist_detection.last_trade`, `StageMeter` from `delist_detection.manifest`):

```python
class _RawEdgar:
    def __init__(self, raw):
        self.raw, self.asked = raw, []

    def fetch_filing_raw(self, cik, accession):
        self.asked.append((cik, accession))
        return self.raw


def _continuation(source="last_sighting"):
    evidence = {"flags": ["handoff_continuation"],
                "delist_filing": {"form": "25-NSE", "filing_date": "2026-08-27", "accession": "0000876661-26-000712"}}
    rec = DelistRecord("LEG", 58492, "2026-08-25", 304, CrspBucket.EXCHANGE_TRANSFER, "high", "Continuation", evidence,
                       sec_id="OLD", delist_date="2026-09-06", successor_sec_id="NEW")
    return Delisting("OLD", 58492, "LEG", "2026-09-06", rec, LastTrade(date(2026, 8, 25), source, ()), None, None, "")


def _notice_ctx(edgar):
    return pipeline._RunContext(SimpleNamespace(edgar=edgar), date(2026, 9, 25), lambda *_: None, 1,
                                StageMeter(lambda *_: None))


def test_a_handoff_continuation_takes_its_form25_notice_day():
    raw = (Path(__file__).parent / "fixtures" / "form25" / "leg_25nse_before_market_open.txt").read_text(
        encoding="utf-8", errors="replace")
    d = _continuation()
    assert pipeline._date_from_notices(_notice_ctx(_RawEdgar(raw)), [d]) == 1
    assert (d.last_trade.day, d.last_trade.source) == (date(2026, 8, 26), "ex99_notice")
    assert d.record.observed_delist_date == "2026-08-26"


def test_a_handoff_continuation_without_a_dated_notice_keeps_its_sighting():
    d, edgar = _continuation(), _RawEdgar("<TYPE>25-NSE no notice here")
    assert pipeline._date_from_notices(_notice_ctx(edgar), [d]) == 0
    assert (d.last_trade.day, d.last_trade.source) == (date(2026, 8, 25), "last_sighting")
    other = _continuation(source="midas")
    pipeline._date_from_notices(_notice_ctx(edgar), [other])
    assert edgar.asked == [(58492, "0000876661-26-000712")]    # a row dated another way is never re-read
```

  (Fix the imports to what the file already has, e.g. `SimpleNamespace`, `Path`. If the LEG notice's rule makes the
  answer unconfirmed in this path, pick another fixture under tests/fixtures/form25 that tests/test_form25.py dates
  with a confirmed kind, and say which in the report.)
- [ ] **Step 2:** Run the two tests: they fail (`_date_from_notices` does not exist).
- [ ] **Step 3: Implement.** Add after `_handoffs` in `src/delist_detection/pipeline.py` (importing `parse_form25`,
  `notice_last_trade` from `.form25` and `decide_last_trade` from `.last_trade` if not imported):

```python
def _date_from_notices(ctx: _RunContext, added: list[Delisting]) -> int:
    """9c. A continuation row the handoff stage built from an unmatched Form 25
    carries its last sighting as its last trade day; when that Form 25's notice
    states a confirmed last day of trading (`form25.notice_last_trade`,
    `last_trade.decide_last_trade`), the row takes it (source `ex99_notice`). A
    read that fails keeps the sighting; a refusal (`fatal.FATAL`) stops the run."""
    redated = 0
    for d in added:
        filing = (d.record.evidence or {}).get("delist_filing")
        if not filing or d.last_trade.source != "last_sighting":
            continue
        try:
            raw = ctx.clients.edgar.fetch_filing_raw(d.cik, filing["accession"])
        except FATAL:
            raise
        except requests.RequestException:
            continue
        if not raw:
            continue
        f25 = parse_form25(raw, accession=filing["accession"], form=filing["form"], filing_date=filing["filing_date"])
        lt = decide_last_trade(notice=notice_last_trade(f25), eightk=(None, ""), midas=None, halt=None)
        if lt.day is not None and "last_trade_date_unconfirmed" not in lt.flags:
            d.last_trade = lt
            d.record.observed_delist_date = lt.day.isoformat()   # handoffs.py dates the record the same as the row
            redated += 1
    ctx.log(f"handoff rows dated from their Form 25 notice: {redated}")
    return redated
```

  In `_run`, inside `if handoffs.added:`, right after `delistings += handoffs.added`, add
  `_date_from_notices(ctx, handoffs.added)   # 9c`. It must run before that block's `_last_trade_closes` call, so the
  added rows' closes are read on the new day. (`Delisting` is a plain dataclass; `form25.parse_form25` and
  `form25.notice_last_trade` are imported next to `SecurityRef`, `decide_last_trade` from `.last_trade`.)
- [ ] **Step 4:** Run `tests/test_pipeline.py`, `tests/test_handoffs.py`, then the full suite.
- [ ] **Step 5: Commit** — `git commit -m "pipeline: date the handoff stage's continuation rows from their Form 25 notice (reset-4e)"`

---

### Task 3: Docs

- [ ] CLAUDE.md (`last_trade.py` bullet: the wordings; the stage list: 9c), docs/data-flow.md (stage 9c). Update the
  pytest count. Commit `docs: reset-4e's dated prints`.

---

### Task 4: Acceptance rebuild (network)

As in the earlier acceptance tasks (lock check, `.superpowers/sdd/reset4e-acceptance`, the usual flags and seven
hosts, stop on a denial or a non-zero exit). Report the log's "handoff rows dated from their Form 25 notice: N"
(expect about 10) and how many contract endings gained a published `last_trade_date` (expect about 16). Golden `pass`
cases must stay; flip `known_wrong` cases that now pass. Lower by hand only Ruling 2's entries, with its reason. Publish,
`scripts/scorecard.py --check`, `--raise-floor --write`, the full suite, a "Done (first step)" bullet under reset-4e in
the roadmap (the counts and Ruling 1's remaining groups). Commit `Acceptance: exchange-print dates the caches held (reset-4e)`.

## Self-review

- Spec coverage: the two cached groups of Ruling 1; PHLY's halt window, the event-day sentences and the 52
  still-trading endings are left (Ruling 1).
</content>
</invoke>

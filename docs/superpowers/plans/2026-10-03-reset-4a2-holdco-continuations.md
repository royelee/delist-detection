# Reset-4a2 (first step): A Successor's Own 8-K12B Settles a Holding-Company Continuation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 1:1 holding-company reorganization under the same ticker (Xerox 2019, Cigna 2018, Broadcom 2016 and
2018, QuidelOrtho 2022) is a continuation with a successor link (decision 9). Today these stay merger endings
with a `handoff_conflict` review row, because the full-text search for the successor's 8-K12B finds nothing and
"only timing across two issuers" cannot overrule a merger row. The successor issuer's own filing list holds that
8-K12B; read it there.

**Architecture:** `handoffs.own_continuation_filing(filings, day)` picks the successor issuer's 8-K12B/8-K12G3 in
the same window the full-text search uses (30 days before B's first sighting to 60 after). `pipeline._handoffs`'
`find_filing` falls back to it when the search finds none. `decide_handoff` and `apply_handoffs` are unchanged: a
filing already settles a continuation and lets a merger row be rebucketed.

**Tech Stack:** Python ≥3.10, pytest (offline).

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md`, decision 9 ("A 1:1 holding-company
reorganization (Alphabet 2015, ANAT 2020) is a continuation row with a successor link"). Roadmap: reset-4a's
parked items ("the 4 continuation regressions (XRX, WBD, LLYVA, LLYVK), holdco reorganizations").

## Global Constraints

- Decision 9 adopted (reset-3).
- The fallback reads only the successor issuer's own filing list (`edgar.recent_filings(b.issuer_cik)`), which the
  run has already fetched for the issuer-name and handoff stages; it asks nothing new of SEC on a warm run.
- The window is `successors.successor_query`'s: [B's first sighting − 30 days, + 60 days].
- A full-text-search hit still wins; the fallback runs only when the search finds none (or no search exists).
- Tests are offline. Python: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`; pytest with `-o addopts=""`.

## Rulings this plan makes

1. **Evidence.** A controller check of the cached filing lists (2026-10-03,
   `.superpowers/sdd/reset-4a2-research/k12b.py`) found the 8-K12B for 5 of the 7 `handoff_conflict` pairs: CI
   (Cigna, CIK 1739940, 2018-12-20), XRX (Xerox Holdings, 1770450, 2019-07-31), AVGO (Broadcom Ltd, 1649338,
   2016-02-02), AVGO (Broadcom Inc, 1730168, 2018-04-04), QDEL (QuidelOrtho, 1906324, 2022-05-27). LLYVA and LLYVK
   (Liberty Live Holdings, 2078416) have none: a split-off registered another way; they stay for a later step.
2. **Not checking the 8-K12B's text.** The filing is the successor's own registration under Rule 12g-3, filed within
   days of the same ticker moving to it; that is the "filing says the holders' shares carried over" the merger guard
   asks for. Its text is not read for the predecessor's name.
3. **Permitted changes.** Only the pairs' own rows may change: their delistings rows (merger -> exchange transfer
   with a successor, `handoff_rebucketed`), their review rows, their lifecycles, the contract rows of those
   securities, and the scorecard lines those move (lowered by hand only with the reason "decision 9: a 1:1 holdco
   reorganization is a continuation (successor's own 8-K12B)"). A change to any other security stops the acceptance.
4. **Not in this step.** The 15 no-Form-25 fallback endings MIDAS shows still trading (the reset-4a2 research's
   rule 1) conflict with CLAUDE.md's invariant that an unconfirmed fallback day is not second-guessed; that is the
   operator's call. Successor lines not in the run (ODP, UNIT) and LLYVA/LLYVK wait.

## Review Focus

1. A pair whose search finds a filing never reads the filing list (Task 1 test).
2. An 8-K12B outside the window, or another form, is no continuation filing (Task 1 test).
3. A pair that was a takeover (B existed before) and whose B filed an 8-K12B: `decide_handoff` gives a filing
   precedence unless A lived on — the acceptance lists every decision that changed, not only the five.

---

### Task 1: The successor's own 8-K12B

**Files:** Modify `src/delist_detection/handoffs.py`, `src/delist_detection/pipeline.py`; Test
`tests/test_handoffs.py`, `tests/test_pipeline.py`.

**Interfaces:** Produces `handoffs.own_continuation_filing(filings: Sequence[EdgarSubmission], day: date) ->
tuple[str, str, str] | None` — (form, accession, filing date), the same shape `continuation_filing` returns.

- [ ] **Step 1: Write the failing tests.** In tests/test_handoffs.py (use `EdgarSubmission` from
  `delist_detection.edgar`; grep its fields — accession, form, filing_date and others — and build it with keywords):

```python
def _sub(form, day, acc="0000000001-19-000001"):
    return EdgarSubmission(accession=acc, form=form, filing_date=day, report_date="", items="", primary_doc="")


def test_own_continuation_filing_reads_the_successors_filing_list():
    filings = [_sub("8-K", "2019-07-31", "a"), _sub("8-K12B", "2019-07-31", "b"), _sub("10-Q", "2019-08-02", "c")]
    assert own_continuation_filing(filings, date(2019, 8, 1)) == ("8-K12B", "b", "2019-07-31")
    assert own_continuation_filing([_sub("8-K12G3", "2019-09-20", "d")], date(2019, 8, 1)) == ("8-K12G3", "d", "2019-09-20")


def test_own_continuation_filing_keeps_to_the_search_window():
    assert own_continuation_filing([_sub("8-K12B", "2019-06-30")], date(2019, 8, 1)) is None    # 32 days before
    assert own_continuation_filing([_sub("8-K12B", "2019-10-01")], date(2019, 8, 1)) is None    # 61 days after
    assert own_continuation_filing([_sub("8-K", "2019-07-31")], date(2019, 8, 1)) is None
```

  (`successors.SUCCESSOR_FORMS` is the string "8-K12B,8-K12G3", so the new tuple constant is needed.) In tests/test_pipeline.py, find the existing `_handoffs`
  test that decides a continuation by the full-text search (grep `continuation_filing`, `8-K12B`, `handoff` in that
  file) and add a test next to it: the search finds nothing, B's issuer's `recent_filings` lists an 8-K12B on B's
  first sighting, and A's row is a merger. The outcome rebucketing A's row to a continuation with successor B (the
  decision's evidence is "8-K12B <accession>", `by_filing` True). Add a second assertion or test: when the search
  finds a filing, `recent_filings` of B's issuer is not asked for the continuation (record the calls in the fake).
  If no such pipeline test exists, test `_handoffs` with the smallest fake the file's other handoff tests use, or
  report NEEDS_CONTEXT naming what you found.
- [ ] **Step 2:** Run them: they fail.
- [ ] **Step 3: Implement.** In `handoffs.py`, next to `continuation_filing`:

```python
SUCCESSOR_FORMS_12G3 = ("8-K12B", "8-K12G3")


def own_continuation_filing(filings: Sequence[EdgarSubmission], day: date) -> tuple[str, str, str] | None:
    """The successor issuer's own 8-K12B/8-K12G3 (Rule 12g-3) in its filing list,
    in the window `continuation_filing`'s search uses (30 days before `day`, B's
    first sighting, to 60 after), as (form, accession, filing date); the first
    by filing date. Where the full-text search for the predecessor's name finds
    nothing, the successor's own registration is the filing that says the
    holders' shares carried over (Xerox Holdings 2019, Cigna 2018)."""
    lo, hi = day - timedelta(days=30), day + timedelta(days=60)
    hits = sorted((f.filing_date, f.form, f.accession) for f in filings
                  if f.form in SUCCESSOR_FORMS_12G3 and f.filing_date
                  and lo <= date.fromisoformat(f.filing_date) <= hi)
    return (hits[0][1], hits[0][2], hits[0][0]) if hits else None
```

  (Import `timedelta` and `EdgarSubmission` as the module needs.) Existing pipeline tests whose fake EDGAR lists an
  8-K12B for B's issuer may now decide differently; if one changes, report it rather than editing its expectation.
  In `pipeline._handoffs`, change `find_filing` so that after the
  search (or when `filing_args` returns None because there is no search) it falls back to B's issuer's list:

```python
    def find_filing(p):
        args = filing_args(p)
        if args is not None:
            names, day, cik = args
            hit = next((f for n in names if (f := continuation_filing(fts, name=n, day=day, successor_cik=cik))),
                       None)
            if hit is not None:
                return hit
        b_cik = securities[p.b].issuer_cik
        if b_cik is None:
            return None
        return own_continuation_filing(edgar.recent_filings(b_cik), date.fromisoformat(p.b_first))
```

  Update `_handoffs`' docstring ("decided on the successor issuer's 8-K12B/8-K12G3 (EDGAR full-text search, else
  its own filing list)"). The read is inside the existing `DegradedWatch` bracket around `find_filing(p)`.
- [ ] **Step 4:** Run tests/test_handoffs.py, tests/test_pipeline.py, then the full suite.
- [ ] **Step 5: Commit** — `git commit -m "handoffs: the successor's own 8-K12B settles a continuation the search missed (reset-4a2)"`

---

### Task 2: Docs

- [ ] CLAUDE.md (`handoffs.py` bullet: `decide_handoff`'s continuation by filing now names the successor issuer's own
  filing list as the fallback), docs/data-flow.md (the handoff stage). Update the pytest count. Commit
  `docs: a successor's own 8-K12B (reset-4a2)`.

---

### Task 3: Acceptance rebuild (network)

As in the earlier acceptance tasks (lock check, `.superpowers/sdd/reset4a2-acceptance`, the usual flags and seven
hosts; stop on a denial or a non-zero exit; a Nasdaq halt-feed parse error alone is retried once). Report every
handoff decision that changed (run_manifest.json `handoffs` counts and review rows `handoff_conflict` /
`handoff_rebucketed` before and after) and every delistings.csv row that changed, by ticker. Expect CI 2018, XRX
2019, AVGO 2016, AVGO 2018 and QDEL 2022 to become continuations with their successors. Run the audit diff
(`.superpowers/sdd/2026-10-02-reset-4e-print-dates/auditdiff.py` with the new folder) and list each case that
changed. Apply Ruling 3: stop on a change to any other security. Lower by hand only entries those pairs move, with
Ruling 3's reason; publish; `scripts/scorecard.py --check`, `--raise-floor --write`; flip any golden case that now
passes; the full suite; a "Done (second step)" bullet under reset-4a in the roadmap (the five, and what waits: the
15 still-trading fallback endings as an operator decision, LLYVA/LLYVK, ODP, UNIT). Commit `Acceptance: holdco
continuations by the successor's own 8-K12B (reset-4a2)`.

## Self-review

- Spec coverage: decision 9's holdco continuation for the five with a cached 8-K12B; the others are listed in Ruling 4.
- Types: `own_continuation_filing` returns `continuation_filing`'s tuple shape, so `decide_handoff` needs no change.
</content>
</invoke>

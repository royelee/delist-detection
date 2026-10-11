# Reset-4b (first step): Securities Dead Before Their First Sighting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A security whose delisting came before its first sighting (a stale snapshot listed it after it was
gone) gets its CUSIPs and its ticker interval from the fails-to-deliver rows before the delisting, so it stops being
a lifecycle with no interval.

**Architecture:** A pure helper, `history.backfill_cusips`, picks the CUSIPs of fails rows under a security's tickers
in the 120 days before its end whose descriptions name its issuer. A new pipeline stage, 5b, runs after the
delisting search: for each such security it loads the fails rows back three years before the end, takes the CUSIPs,
and rebuilds the security's sightings, so the existing close, history and contract stages use them.

**Tech Stack:** Python ≥3.10, standard library, pytest (offline).

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md` ("A · Identity": "the security's history traced
back to its first listing"; "Every seed resolves to one security whose security_history covers the seed date, or is
listed in uncertain.csv"). Roadmap: "reset-4b: Identity evidence" ("The 32 securities with no interval").

## Global Constraints

- Decisions 1 and 7 hold (adopted); this step changes no `sec_id` and no issuer CIK.
- A security is "dead before its first sighting" when it has a real ending (successor not itself) whose last trade
  day, or delist date when that is unknown, is earlier than its first observation, and none of its CUSIPs has a
  trading fails row loaded.
- CUSIP evidence: fails rows under one of the security's tickers in [end − 120 d, end], not under a deleted symbol
  (`ftd.is_deleted_symbol`), whose description `names.description_matches` one of the security's observed names or its
  issuer's EDGAR names. Rows after the end never count (a later issuer reusing the ticker).
- Rows are loaded for [end − 1095 d, end + 10 d].
- Tests are offline. Python: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`; pytest with `-o addopts=""`.

## Rulings this plan makes

1. **Scope.** The reset-4b research (2026-10-02, offline) found all 32 no-interval securities delisted from 2006-12 to
   2008-02 before the 2008-01-16 snapshot that sighted them; the pipeline's fails window starts 2007-12-17, so their
   rows were never loaded, and every one has rows under its ticker naming its issuer in the cached 2004–2007 files.
   The other reset-4b groups (ticker-tier FIGIs, placeholders, FIGI rows with no CIK, FOX/FOXA share-class
   contradictions, ERA, LVNTA) are later steps.
2. **No identity change.** The new CUSIPs are not sent to OpenFIGI here: a placeholder stays a placeholder.
3. **Three years back.** The interval starts at the first fails row within 1095 days before the end, not at the
   security's listing date (unknown here); the consumer's membership never reached these securities alive.
4. **Permitted floor drops.** New closes and intervals can move `R2.*`, `L2.*`, `L1.ended_incomplete` and
   `V.uncertain_securities` (a seed after the end is now measured as outside the history); Task 4 may lower those by
   hand, with the reason. `L1.no_interval` must fall; any other drop, or a golden `pass` case that breaks, stops it.

## Review Focus

1. A later issuer reusing the ticker after the end must not lend its CUSIP (Task 1 test).
2. A row under a deleted symbol must not count (Task 1 test).
3. A security that already has fails rows, or whose ending is after its first sighting, is left alone (Task 2 test).
4. A continuation row (successor itself) is not an ending for this purpose (Task 2 test).

---

### Task 1: `history.backfill_cusips`

**Files:**
- Modify: `src/delist_detection/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- Produces: `history.BACKFILL_CUSIP_DAYS = 120`, `backfill_cusips(tickers, end, ftd, names) -> list[str]`
  (CUSIPs, most rows first, then by CUSIP).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_history.py`:

```python
def test_backfill_cusips_names_the_issuers_cusip_before_its_end():
    from delist_detection.ftd import FtdIndex, FtdRow
    from delist_detection.history import backfill_cusips
    ftd = FtdIndex([
        FtdRow("2007-10-01", "071707103", "BOL", "BAUSCH & LOMB INC COM", 60.0),
        FtdRow("2007-10-15", "071707103", "BOL", "BAUSCH & LOMB INC COM", 61.0),
        FtdRow("2007-09-01", "999999999", "BOL", "OTHER WIDGETS CO", 5.0),        # another issuer's description
        FtdRow("2007-10-20", "071707103", "BOLXXXX", "BAUSCH & LOMB INC COM", 61.0),  # deleted symbol
        FtdRow("2008-06-01", "888888888", "BOL", "BAUSCH LATER CORP", 9.0),        # after the end
        FtdRow("2007-03-01", "777777777", "BOL", "BAUSCH & LOMB INC COM", 50.0),   # before the window
    ])
    assert backfill_cusips(["BOL"], "2007-11-05", ftd, ["BAUSCH & LOMB INC"]) == ["071707103"]
    assert backfill_cusips(["BOL"], "2007-11-05", ftd, ["SOMEONE ELSE"]) == []
```

(If `FtdIndex`'s constructor or `FtdRow`'s field order differs from `FtdIndex(rows)` and `FtdRow(date, cusip,
symbol, description, price)`, build the index the way tests/test_ftd.py does and say so in the report.)

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_history.py -q -o addopts=""`
Expected: `ImportError: cannot import name 'backfill_cusips'`.

- [ ] **Step 3: Implement**

In `src/delist_detection/history.py` add (importing `Counter`, `date`, `timedelta`, `is_deleted_symbol` from `.ftd`
and `description_matches` from `.names` if not already imported):

```python
BACKFILL_CUSIP_DAYS = 120     # the days before a dead-before-sighting security's end whose rows name its CUSIP


def backfill_cusips(tickers: Iterable[str], end: str, ftd: FtdIndex, names: Iterable[str]) -> list[str]:
    """The CUSIPs of a security that died before its first sighting: those of the
    fails rows under one of its `tickers` in the BACKFILL_CUSIP_DAYS before its `end`
    (ISO), not under a deleted symbol, whose description names its issuer
    (`names.description_matches` against its observed and EDGAR `names`). Rows
    after the end never count: a later issuer may reuse the ticker. Most rows first."""
    names = list(names)
    lo = (date.fromisoformat(end) - timedelta(days=BACKFILL_CUSIP_DAYS)).isoformat()
    counts: Counter[str] = Counter()
    for t in sorted(set(tickers)):
        for r in ftd.by_symbol(t, lo, end):
            if not is_deleted_symbol(r.symbol) and description_matches(r.description, names):
                counts[r.cusip] += 1
    return [c for c, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
```

(If `ftd.by_symbol` returns rows under a deleted symbol for a bare ticker query, the `is_deleted_symbol` test drops
them; keep it.)

- [ ] **Step 4:** Run the file — passes. Full suite: expected the previous count + 1, 24 xfailed (state the numbers).
- [ ] **Step 5: Commit** — `git commit -m "history: backfill_cusips for a security dead before its first sighting (reset-4b)"`

---

### Task 2: Pipeline stage 5b

**Files:**
- Modify: `src/delist_detection/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `history.backfill_cusips`, `FtdIndex.extend(client, lo, hi, *, cusips=, symbols=)`, `ticker_sightings`.
- Produces: `pipeline.BACKFILL_DAYS = 1095`, `_dead_before_sighting(ctx, securities, delistings, sec_cusips, ftd,
  sightings, issuers) -> list[str]` (the sec_ids that took CUSIPs); it updates `sec_cusips` and `sightings` in place.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pipeline.py`, write a test that runs the pipeline on a universe where AET is observed only on
2019-06-28 (after its 2018-11-29 Form 25, so it died before its first sighting) and the FTD double holds AET rows
under symbol `AET` from 2018-06 to 2018-11-28 with description `AETNA INC COM` and a CUSIP. Build it like `_clients`
(copy what you need into a new helper rather than changing `_clients`; the FTD double is `_FtdClient` with `ROWS`).
Assert: ticker_history has an AET row whose `valid_to` is AET's last trade day (2018-11-28) and that starts in 2018;
cusip_history has the CUSIP; the run log contains "dead before first sighting: 1". Write a second test with the
standard `_clients` universe (AET observed 2017 and 2018, before its delisting) asserting the log says
"dead before first sighting: 0". If the FTD double cannot serve an `extend` over an earlier window, report
NEEDS_CONTEXT with what it does.

- [ ] **Step 2:** Run them to see them fail (no such stage, log line missing).

- [ ] **Step 3: Implement**

In `src/delist_detection/pipeline.py`, import `backfill_cusips` with the other `history` imports, add
`BACKFILL_DAYS = 1095   # how far before a dead-before-sighting security's end its fails rows are loaded` near the
other module constants, and add after `_find_delistings`:

```python
def _dead_before_sighting(ctx: _RunContext, securities: dict[str, Security], delistings: list[Delisting],
                          sec_cusips: dict[str, list[str]], ftd: FtdIndex, sightings: dict[str, list[Sighting]],
                          issuers: dict[str, Issuer]) -> list[str]:
    """5b. A security whose real ending (its successor not itself) came before its
    first observation, and none of whose CUSIPs has a trading fails row, died
    before a stale snapshot listed it: the run's fails window starts after it. Its
    rows under its tickers from BACKFILL_DAYS before the end are loaded; the CUSIPs
    whose rows before the end name its issuer (`history.backfill_cusips`) become
    its CUSIPs, and its sightings are rebuilt, so the close, history and contract
    stages see them. Returns the sec_ids that took CUSIPs."""
    ends: dict[str, str] = {}
    for e in delistings:
        if e.record.successor_sec_id == e.sec_id:
            continue
        day = e.last_trade.day.isoformat() if e.last_trade.day else e.delist_date
        ends[e.sec_id] = min(ends.get(e.sec_id, day), day)
    fixed: list[str] = []
    for sid, end in sorted(ends.items()):
        s = securities.get(sid)
        seen = [o.as_of for era in (s.eras if s else ()) for o in era.observations]
        if s is None or not seen or end >= min(seen) or ftd.trading_rows(sec_cusips.get(sid, [])):
            continue
        end_day = date.fromisoformat(end)
        lo, hi = end_day - timedelta(days=BACKFILL_DAYS), end_day + timedelta(days=10)
        tickers = sorted({era.ticker for era in s.eras})
        ftd.extend(ctx.clients.ftd_client, lo, hi, symbols=tickers)
        names = [n for era in s.eras for n in (era.name, *(issuers[era.key].names if era.key in issuers else ())) if n]
        found = backfill_cusips(tickers, end, ftd, names)
        if not found:
            continue
        ftd.extend(ctx.clients.ftd_client, lo, hi, cusips=found)
        sec_cusips[sid] = list(dict.fromkeys([*sec_cusips.get(sid, []), *found]))
        sightings[sid] = ticker_sightings(s, ftd, sec_cusips[sid])
        fixed.append(sid)
    ctx.log(f"dead before first sighting: {len(fixed)} securities took CUSIPs from fails rows before their end")
    return fixed
```

(`TickerEra` carries `.name`, `.ticker`, `.key` and `.observations`; if a name differs, use what the era has and
say so.) In `_run`, after `review += search.review` (stage 5), add
`_dead_before_sighting(ctx, securities, delistings, sec_cusips, ftd, search.sightings, answers.issuers)   # 5b`.

- [ ] **Step 4:** Run `tests/test_pipeline.py`, `tests/test_pipeline_prefetch.py`, then the full suite (expected the
  previous count + 2). The prefetch test compares outputs for 1 and N workers; the stage runs on the main thread
  only, so outputs stay byte-identical.
- [ ] **Step 5: Commit** — `git commit -m "pipeline: a security dead before its first sighting takes its CUSIPs from fails rows before its end (reset-4b)"`

---

### Task 3: Docs

**Files:** `CLAUDE.md`, `docs/data-flow.md` (docs only).

- [ ] CLAUDE.md: in the `history.py` bullet, add `backfill_cusips`; in the architecture paragraph's stage list, add
  stage 5b `_dead_before_sighting` (one sentence: why, the windows of Global Constraints). Update the pytest count.
- [ ] docs/data-flow.md: add stage 5b to the pipeline stages, same sentence.
- [ ] Run the suite once; commit `docs: stage 5b, securities dead before their first sighting (reset-4b)`.

---

### Task 4: Acceptance rebuild (network)

Same procedure as reset-4a's acceptance: check no SEC client runs; rebuild into `.superpowers/sdd/reset4b-acceptance`
with `--as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm --id-baseline output/securities.csv`, the lock
variable, and all seven hosts allowed; stop on a sandbox denial, a non-zero exit or a refusal. Check the log's
"dead before first sighting: N" (expect about 31). Compare the scorecard: `L1.no_interval` must fall; a golden `pass`
case that fails is a stop; flip every `known_wrong` case that now passes. Lower by hand only the entries Ruling 4
permits, with its reason; any other drop is a stop. Publish (every table, contract/*.csv, scorecard.json,
run_manifest.json, stderr as run.log after a secrets check), `scripts/scorecard.py --check`, `--raise-floor --write`,
the full suite. Add a "Done (first step)" bullet under reset-4b in the roadmap (the numbers that moved, the floor
entries lowered and why, what is left: ticker-tier FIGIs, placeholders, no-CIK FIGI rows, FOX/FOXA share-class
contradictions, ERA, LVNTA). Commit `Acceptance: securities dead before their first sighting (reset-4b)`.

## Self-review

- Spec coverage: the no-interval group only (Ruling 1). Types: `backfill_cusips(tickers, end, ftd, names)` (Task 1) is
  what Task 2 calls; `sec_cusips` and `sightings` are the dicts stage 5 already built.
</content>
</invoke>

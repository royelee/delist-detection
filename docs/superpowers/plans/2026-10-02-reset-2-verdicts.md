# Reset 2: One Verdict Per Row Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every seed, security and ending one verdict, `confirmed` or `uncertain`, under the spec's
invariants. Write every uncertain one, with its reasons, to `output/uncertain.csv`. Make the scorecard count
uncertain verdicts and measure how often a `confirmed` verdict is wrong against the accuracy audit.

**Architecture:** `verdict.py` is a pure module. It reads the output tables as string rows, like `lifecycle.py`
and `scorecard.py`, and decides each verdict from evidence the tables already hold: the FIGI source, ticker
intervals, the observation map, and each ending's reason, flags, last-trade source and Form 25 date. One
input does not come from the tables: what ties a placeholder's ticker to its CIK (decision 1).
`ticker_evidence.py` computes it inside the pipeline. It takes the resolver tier that found the CIK or, failing
that, one EDGAR full-text search of that CIK's own filings for the ticker. The pipeline gathers this evidence
(stage 10e), decides the verdicts (10f), adds `uncertain` to the group of tables written together, and builds
the scorecard from those tables (10g). The scorecard reads `uncertain.csv` and adds V lines. `review.csv` stays
until the cleanup removes it after reset-3.

**Tech Stack:** Python ≥ 3.10 standard library, the existing `store`, `lifecycle`, `scorecard` and `edgar`
modules, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md`: Part 3 "Invariants the library's build
enforces", the `uncertain.csv` row of "What crosses the boundary", "Order of work" step 2, and decisions 1, 4
and 9. Roadmap: `docs/superpowers/plans/2026-10-02-delist-library-reset.md` (reset-2). This plan builds on
reset-1 (`docs/superpowers/plans/2026-10-02-reset-1-scorecard-golden-audit.md`), which must already be in the
branch.

## Global Constraints

- Verdicts are `confirmed` or `uncertain`, per seed, per security and per ending. "One verdict per seed and one
  per ending. The ending's verdict covers identity, exit kind and the last trade date, never the value."
- "`last_trade_date` comes only from an exchange-print source and is never after the Form 25 effective date;
  otherwise blank and uncertain." The exchange-print sources are MIDAS, a Nasdaq halt, the exchange's notice and
  8-K item 3.01 (`midas`, `nasdaq_halt`, `ex99_notice`, `8k_301`).
- "Confirmed requires a FIGI or a unique CIK + class, dated intervals covering every seed that resolved to the
  security, and, for an ending, a filing-backed exit kind and a dated last exchange price."
- "For one ticker on one date, at most one `sec_id` per share class."
- **Decision 1**, answered by the operator on 2026-10-02: a placeholder is confirmed only when a filing ties its
  ticker to its CIK. That is a resolver tier that already does so (`cik_map`, `manual`, `rename`, `efts`,
  `company_tickers`), or else an EDGAR full-text search of that CIK's own filings for the ticker.
- **Decision 4**, adopted as proposed ("Reviewers agree"): assumed par after a failed payout gate is uncertain.
- **Decision 9:** "a timing-only link with no filing or CUSIP evidence is uncertain, never a continuation."
- `uncertain.csv` has the columns `kind` (seed, security or ending), `ticker`, `sec_id`, `date`, `reason` and
  `candidates`. "Holds every seed the library could not place, every uncertain security and ending."
- Every output is written only after the whole run succeeds. `uncertain.csv` joins the group of tables
  `store.write_tables` writes together.
- Exit codes do not change. `review.csv` and `review_summary.csv` stay.
- Tests stay offline. The last task (the acceptance rebuild) uses the network under SEC fair access:
  `EDGAR_USER_AGENT` must be set, requests go through the library's throttled client, and only one SEC client
  runs at a time.
- The library stays universe-agnostic. The training window lives in `data/scorecard.json`.

## Rulings this plan makes

These interpretations go beyond what the spec states. Each is pinned by a test, so changing one is a deliberate
edit.

1. **A seed is an era's first sighting.** Today's input holds every snapshot row, while the spec's seed is "one
   row per introduction". So the security-level coverage rule applies to each era's first sighting. A later
   sighting outside the security's history is listed as an uncertain seed, but the security stays confirmed.
   Without this, stale snapshot rows would condemn correct endings: Genentech's acquisition closed 2009-03-26,
   yet a June 2009 snapshot still lists DNA. Pinned by
   `test_a_later_sighting_outside_the_history_is_an_uncertain_seed_only`.
2. **A measured print beats contrary text.** A `last_trade_date_conflict` where MIDAS or a Nasdaq halt measured
   the date stays confirmed; that is `last_trade.decide_last_trade`'s own rule. This covers 36 of today's 43
   conflicts. Pinned by `test_a_measured_print_beats_contrary_text_and_par_after_a_passed_gate_stands`.
3. **A continuation needs a filing or a CUSIP switch, not an exchange print.** Its date is the handoff day.
   Pinned by `test_a_continuation_needs_filing_or_cusip_evidence_but_no_last_trade_print`.
4. **A FIGI is confirmed identity whatever tier found it.** The spec says "a FIGI". Ticker-only FIGIs are already
   graded medium by L2, and reset-4b owns them.
5. **A ticker shorter than 3 characters is never searched.** The phrase would match ordinary words in the
   issuer's own filings. None of today's 69 searched placeholders has one.

## Measured on the committed output

`verdict.decide` on the committed `output/` (as_of 2026-09-25), with placeholder evidence approximated from the
tables:

| Verdict | No search hits | Every searched placeholder hits |
| --- | --- | --- |
| Uncertain securities | 111 (69 placeholders without evidence, 34 with an introduction outside history, 18 ticker overlaps) | 52 |
| Uncertain endings | 271 (254 in the window) | 251 (234 in the window) |
| Uncertain distress endings | 24 of 54 | 19 |
| Listed seeds | 386 (371 outside history, 11 seen under two names, 4 not placed) | 386 |
| Input tickers touched by an uncertainty | 11.7% | 10.0% |

Against the accuracy audit, the verdict flags 113 of the 114 wrong left-view rows. The audited rows it still
calls confirmed although they are wrong are mostly distress rows that differ only in the bankruptcy
vocabulary, which reset-3 fixes. That count becomes the floored line `V.audit.confirmed_but_wrong`.

## Review Focus

1. **EDGAR cannot answer a placeholder's search.** A timeout or 5xx makes `full_text_search` return `[]`, so the
   placeholder is uncertain this run. Nothing is cached, and the next run asks again. An SEC refusal (403/429)
   must stop the run. Pinned by `test_an_sec_refusal_during_the_search_stops_the_run` (Task 3).
2. **One security seen under two names on a day must give one `uncertain.csv` row, not two.** The table's key
   is `(kind, sec_id, date, ticker)`. Pinned by
   `test_one_security_seen_under_two_names_on_a_day_is_one_uncertain_row` (Task 2).
3. **A committed `output/` from before reset-2 has no `uncertain.csv`.** The V lines must be absent, not zero,
   so the floor never reads "no uncertainty". Pinned by
   `test_verdict_lines_count_uncertain_csv_and_appear_only_with_it` (Task 4) and
   `test_tables_read_takes_uncertain_csv_when_it_is_there` (Task 1).
4. **An era key with a `#n` suffix** (two names on one first day) must still be read as an introduction. Pinned
   by `test_is_introduction_reads_the_era_key` (Task 2).
5. **A `--limit` run writes `uncertain.csv` for its subset.** It must never be compared to the floor. reset-1's
   `test_a_limit_subset_is_never_compared_to_the_floor` keeps covering this, because the V lines go through the
   same `drops` path.

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `src/delist_detection/lifecycle.py` | modify | gains `DISTRESS`, `EXCHANGE_PRINT_SOURCES`, `CONTINUED_FILINGS` (moved from scorecard) and `Tables.uncertain` |
| `src/delist_detection/store.py` | modify | `UNCERTAIN_COLUMNS`, plus the `uncertain` TableSpec |
| `src/delist_detection/verdict.py` | create | `decide`, `Verdicts`, `Verdict`, `is_introduction`: the rules |
| `src/delist_detection/ticker_evidence.py` | create | `EraEvidence`, `evidence_for`, `ticker_filing`: decision 1's check |
| `src/delist_detection/edgar.py` | modify | `full_text_search(..., ciks=)` |
| `src/delist_detection/scorecard.py` | modify | V lines, `V.audit.confirmed_but_wrong`, METRICS entries |
| `src/delist_detection/pipeline.py` | modify | stages 10e (`_ticker_evidence`), 10f (verdicts) and 10g (`_scorecard` on `_as_read`); `RunSummary.uncertain` |
| `scripts/classify_universe.py` | modify | prints the uncertain counts |
| `tests/lifecycle_tables.py` | modify | `ending(**cells)`; `obs(era=, name=)` |
| `tests/test_verdict.py`, `tests/test_ticker_evidence.py` | create | unit tests |
| `tests/test_lifecycle.py`, `test_scorecard.py`, `test_pipeline.py`, `test_classify_universe_cli.py`, `test_pipeline_prefetch.py`, `test_run_provenance.py` | modify | new and updated tests |
| `CLAUDE.md`, `README.md`, `CONTEXT.md`, `docs/data-flow.md` | modify | docs |
| `output/uncertain.csv`, `output/scorecard.json`, `output/run_manifest.json`, `data/scorecard.json`, roadmap | create/modify (Task 7) | the acceptance rebuild's results and floor |

All commands below run from the repo root with `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`. The
tests use `-o addopts=""` so that pytest prints its summary line.

---

### Task 1: Groundwork: shared constants, the `uncertain` table, `Tables.uncertain`

**Files:**
- Modify: `src/delist_detection/lifecycle.py`, `src/delist_detection/store.py`, `src/delist_detection/scorecard.py`
- Modify: `tests/lifecycle_tables.py`
- Test: `tests/test_lifecycle.py`

**Interfaces:**
- Produces:
  - `lifecycle.DISTRESS`, `lifecycle.EXCHANGE_PRINT_SOURCES` and `lifecycle.CONTINUED_FILINGS`. `scorecard`
    imports them from here, so the names stay importable from `scorecard`; `audit.py` imports `DISTRESS` from
    `scorecard` and is unchanged.
  - `store.UNCERTAIN_COLUMNS = ("kind", "ticker", "sec_id", "date", "reason", "candidates")`, with
    `TABLES["uncertain"]` keyed `("kind", "sec_id", "date", "ticker")`.
  - `Tables.uncertain: Sequence[Mapping[str, str]] | None` (default None). `Tables.read` sets it to None when
    `uncertain.csv` is missing.
  - Test helpers: `ending(..., **cells)` takes any delistings column, and `obs(ticker, as_of, sec_id="",
    status="mapped", *, era=None, name="")` defaults the era to `f"{ticker}@{as_of}"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lifecycle.py`:

```python
def test_tables_read_takes_uncertain_csv_when_it_is_there(tmp_path):
    t = tables([sec("A")], [iv("A", "AAA", "2010-01-04")], [], [obs("AAA", "2010-06-30", "A")])
    store.write_tables(tmp_path, {"securities": t.securities, "ticker_history": t.ticker_history,
                                  "delistings": t.delistings, "observation_map": t.observation_map})
    assert Tables.read(tmp_path).uncertain is None
    store.write_tables(tmp_path, {"uncertain": []})
    assert Tables.read(tmp_path).uncertain == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_lifecycle.py -q -o addopts=""`
Expected: 1 failed, `AttributeError: 'Tables' object has no attribute 'uncertain'`.

- [ ] **Step 3: Add the table and the constants**

In `src/delist_detection/store.py`, insert directly above `TABLES: dict[str, TableSpec] = {t.name: t for t in (`:

```python
# uncertain.csv (verdict.Verdicts.uncertain_rows): one row per uncertain seed,
# security or ending. `kind` is seed | security | ending; `reason` holds
# `;`-joined `code` or `code:detail` items; `candidates` the other sec_ids involved.
UNCERTAIN_COLUMNS: tuple[str, ...] = ("kind", "ticker", "sec_id", "date", "reason", "candidates")
```

Then add this as the last TableSpec, after `observation_map`'s:

```python
    TableSpec("uncertain", UNCERTAIN_COLUMNS, ("kind", "sec_id", "date", "ticker")),
```

In `src/delist_detection/lifecycle.py`, directly after the `EXIT_KINDS = ...` line, add:

```python
DISTRESS = ("liquidation", "compliance_failure")                         # today's distress buckets
EXCHANGE_PRINT_SOURCES = ("midas", "ex99_notice", "8k_301", "nasdaq_halt")  # last trade dates from an exchange print
CONTINUED_FILINGS = "Continued 10-K/Q filings"                           # the continued-filings rule's reason
```

In `Tables`, replace the `review` field and the whole `read` classmethod with:

```python
    review: Sequence[Mapping[str, str]] = ()
    uncertain: Sequence[Mapping[str, str]] | None = None     # None: no uncertain.csv (a run before reset-2)

    @classmethod
    def read(cls, out_dir: str | Path) -> Tables:
        """The tables under `out_dir` (store.read_table: a column mismatch raises).
        review.csv may be missing (no rows); uncertain.csv may be missing (None)."""
        def rd(name: str) -> list[dict[str, str]]:
            return store.read_table(name, store.table_path(out_dir, name))

        def optional(name: str) -> list[dict[str, str]] | None:
            return rd(name) if store.table_path(out_dir, name).exists() else None
        return cls(rd("securities"), rd("ticker_history"), rd("delistings"), rd("observation_map"),
                   optional("review") or [], optional("uncertain"))
```

In `src/delist_detection/scorecard.py`, delete the three lines that define `DISTRESS`,
`EXCHANGE_PRINT_SOURCES` and `CONTINUED_FILINGS`, and change the lifecycle import to:

```python
from .lifecycle import (CLOSED_NO_EVENT, CONTINUED_FILINGS, DISTRESS, ENDED_INCOMPLETE, EXCHANGE_PRINT_SOURCES,
                        HIGH, LEFT_VIEW, LOW, MEDIUM, NO_INTERVAL,
                        NO_MAPPED_SIGHTING, LifecycleView, Tables, flag_names)
```

- [ ] **Step 4: Extend the test helpers**

In `tests/lifecycle_tables.py`, replace `ending` and `obs` with:

```python
def ending(sec_id, delist_date, bucket="merger", *, ltd="", dlret="", method="cash_only", successor="",
           confidence="high", dlret_confidence="high", flags="", reason="", source="midas", **cells):
    return _row("delistings", sec_id=sec_id, delist_date=delist_date, bucket=bucket, last_trade_date=ltd,
                dlret=dlret, dlret_method=method, successor_sec_id=successor, confidence=confidence,
                dlret_confidence=dlret_confidence, review_flags=flags, reason=reason,
                last_trade_date_source=source if ltd else "", **cells)


def obs(ticker, as_of, sec_id="", status="mapped", *, era=None, name=""):
    """An observation_map row; its era starts on its own date unless `era` says otherwise."""
    return _row("observation_map", ticker=ticker, as_of=as_of, sec_id=sec_id, status=status,
                era=era or f"{ticker}@{as_of}", name=name)
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: `1553 passed, 24 xfailed`.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/lifecycle.py src/delist_detection/store.py src/delist_detection/scorecard.py \
        tests/lifecycle_tables.py tests/test_lifecycle.py
git commit -m "The uncertain table and shared constants (reset-2)"
```

---

### Task 2: The verdict rules

**Files:**
- Create: `src/delist_detection/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Consumes: `lifecycle.Tables`, `flag_names`, `CONTINUED_FILINGS` and `EXCHANGE_PRINT_SOURCES` (Task 1); the
  `uncertain` table (Task 1).
- Produces:
  - Constants: `SEED`, `SECURITY` and `ENDING` (`"seed"`, `"security"`, `"ending"`), `SECURITY_UNCERTAIN`,
    `FORM25_EFFECTIVE_DAYS` (10) and `MEASURED_SOURCES`.
  - `Verdict(reasons: tuple[str, ...] = (), candidates: tuple[str, ...] = ())`, with `.confirmed`.
  - `Verdicts(tables, securities: Mapping[str, Verdict], endings: Mapping[(sec_id, delist_date), Verdict],
    seeds: Mapping[observation_map key, Verdict])`, with `.counts() -> {"seed", "security", "ending": int}` and
    `.uncertain_rows() -> list[dict[str, str]]`.
  - `decide(tables, evidence: Mapping[sec_id, str]) -> Verdicts` and `is_introduction(row) -> bool`.

Reason codes (the `reason` column joins them with `;`, as `code` or `code:detail`):

- Security: `placeholder_without_ticker_filing:CIK n`, `seeds_outside_history:k from D`,
  `ticker_overlap:TICKER`.
- Ending: `security_uncertain`, `issuer_from_todays_ticker_map`, `continued_filings_rule`,
  `no_evidence_default`, `unknown_exit_kind`, `assumed_par_after_failed_gate`, `continuation_by_timing_only`,
  `no_last_trade_date`, `last_trade_not_exchange_print:<source>`, `last_trade_date_unconfirmed`,
  `last_trade_date_text_conflict`, `last_trade_after_form25_effective:D`.
- Seed: `not_placed`, `seen_under_two_names`, `outside_security_history`. A seed whose only reason is
  `security_uncertain` is counted but not listed.

- [ ] **Step 1: Write the failing tests**

`tests/test_verdict.py`:

```python
import pytest

from delist_detection import store
from delist_detection.verdict import ENDING, SECURITY, SEED, decide, is_introduction
from tests.lifecycle_tables import ending, iv, obs, sec, tables

GOOD = dict(ltd="2015-03-02", dlret="0.01", reason="M&A 2.01+3.01+5.01", delist_filing_form="25-NSE",
            delist_filing_date="2015-03-03")


def _one(*endings, securities=None, history=None, observations=None, evidence=None):
    t = tables(securities or [sec("A")], history or [iv("A", "AAA", "2010-01-04", "2015-03-02")], list(endings),
               observations if observations is not None else [obs("AAA", "2010-06-30", "A")])
    return decide(t, evidence or {})


def test_a_figi_security_with_a_covered_introduction_and_a_printed_ending_is_confirmed():
    v = _one(ending("A", "2015-03-10", **GOOD))
    assert v.securities["A"].confirmed and v.endings[("A", "2015-03-10")].confirmed
    assert v.counts() == {SEED: 0, SECURITY: 0, ENDING: 0} and v.uncertain_rows() == []


def test_a_placeholder_needs_ticker_evidence():
    p = sec("CIK5-COMMON", cik="5", figi_source="placeholder")
    h = [iv("CIK5-COMMON", "PPP", "2010-01-04")]
    o = [obs("PPP", "2010-06-30", "CIK5-COMMON")]
    without = _one(securities=[p], history=h, observations=o)
    assert without.securities["CIK5-COMMON"].reasons == ("placeholder_without_ticker_filing:CIK 5",)
    assert without.counts()[SEED] == 1 and [r["kind"] for r in without.uncertain_rows()] == [SECURITY]
    assert _one(securities=[p], history=h, observations=o,
                evidence={"CIK5-COMMON": "filing:0001-1"}).securities["CIK5-COMMON"].confirmed


def test_an_introduction_outside_the_history_makes_the_security_uncertain():
    v = _one(ending("A", "2015-03-10", **GOOD), observations=[obs("AAA", "2016-06-30", "A", "after_delisting")])
    assert v.securities["A"].reasons == ("seeds_outside_history:1 from 2016-06-30",)
    assert v.endings[("A", "2015-03-10")].reasons == ("security_uncertain",)


def test_a_later_sighting_outside_the_history_is_an_uncertain_seed_only():
    o = [obs("AAA", "2010-06-30", "A"), obs("AAA", "2015-06-30", "A", "after_delisting", era="AAA@2010-06-30")]
    v = _one(ending("A", "2015-03-10", **GOOD), observations=o)
    assert v.securities["A"].confirmed and v.endings[("A", "2015-03-10")].confirmed
    assert v.uncertain_rows() == [{"kind": SEED, "ticker": "AAA", "sec_id": "A", "date": "2015-06-30",
                                   "reason": "outside_security_history", "candidates": ""}]


def test_is_introduction_reads_the_era_key():
    assert is_introduction(obs("AAA", "2010-06-30", era="AAA@2010-06-30#1"))
    assert not is_introduction(obs("AAA", "2011-06-30", era="AAA@2010-06-30"))


def test_two_securities_holding_one_ticker_at_once_are_both_uncertain_unless_an_ending_links_them():
    secs = [sec("A"), sec("B")]
    h = [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "AAA", "2015-01-05")]
    o = [obs("AAA", "2010-06-30", "A"), obs("AAA", "2015-06-30", "B")]
    v = _one(ending("A", "2015-03-10", **GOOD), securities=secs, history=h, observations=o)
    assert v.securities["A"].reasons == ("ticker_overlap:AAA",) and v.securities["B"].candidates == ("A",)
    linked = _one(ending("A", "2015-03-10", ticker_successor_sec_id="B", **GOOD), securities=secs, history=h,
                  observations=o)
    assert linked.securities["A"].confirmed and linked.securities["B"].confirmed


@pytest.mark.parametrize("cells, reason", [
    (dict(ltd=""), "no_last_trade_date"),
    (dict(source="last_sighting"), "last_trade_not_exchange_print:last_sighting"),
    (dict(flags="last_trade_date_unconfirmed"), "last_trade_date_unconfirmed"),
    (dict(source="ex99_notice", flags="last_trade_date_conflict"), "last_trade_date_text_conflict"),
    (dict(ltd="2015-03-16"), "last_trade_after_form25_effective:2015-03-13"),
    (dict(reason="Continued 10-K/Q filings >180d after delist"), "continued_filings_rule"),
    (dict(flags="no_evidence_default"), "no_evidence_default"),
    (dict(bucket="unknown"), "unknown_exit_kind"),
    (dict(flags="resolved_by_current_ticker_map"), "issuer_from_todays_ticker_map"),
    (dict(method="assumed_par", flags="payout_gate_failed:34.88"), "assumed_par_after_failed_gate"),
])
def test_each_ending_rule(cells, reason):
    row = ending("A", "2015-03-10", **{**GOOD, **cells})
    assert reason in _one(row).endings[("A", "2015-03-10")].reasons


@pytest.mark.parametrize("cells", [dict(source="midas", flags="last_trade_date_conflict"),
                                   dict(method="assumed_par", flags="merger_at_par")])
def test_a_measured_print_beats_contrary_text_and_par_after_a_passed_gate_stands(cells):
    assert _one(ending("A", "2015-03-10", **{**GOOD, **cells})).endings[("A", "2015-03-10")].confirmed


def test_a_continuation_needs_filing_or_cusip_evidence_but_no_last_trade_print():
    secs = [sec("A"), sec("B", observed=False)]
    h = [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "AAA", "2015-03-03")]
    by_filing = ending("A", "2015-03-10", "exchange_transfer", successor="B", ltd="2015-03-02", source="last_sighting",
                       reason="Continuation (8-K12B 0001-1): A last traded as AAA")
    assert _one(by_filing, securities=secs, history=h).endings[("A", "2015-03-10")].confirmed
    by_timing = ending("A", "2015-03-10", "exchange_transfer", successor="B", ltd="2015-03-02",
                       source="last_sighting", reason="Continuation (timing:cik): A last traded as AAA")
    assert _one(by_timing, securities=secs, history=h).endings[("A", "2015-03-10")].reasons == (
        "continuation_by_timing_only",)


def test_a_continuing_move_gets_no_ending_verdict():
    v = _one(ending("A", "2012-05-01", "exchange_transfer", successor="A"))
    assert v.endings == {}


def test_seeds_not_placed_or_seen_under_two_names_are_listed_with_candidates():
    secs = [sec("A"), sec("B")]
    h = [iv("A", "AAA", "2010-01-04"), iv("B", "BBB", "2010-01-04")]
    o = [obs("AAA", "2010-06-30", "A", "conflict", name="ALPHA"), obs("AAA", "2010-06-30", "B", "conflict", name="BETA"),
         obs("ZZZ", "2010-06-30", "", "unresolved"), obs("BBB", "2010-06-30", "B")]
    rows = {(r["ticker"], r["sec_id"]): r for r in _one(securities=secs, history=h, observations=o).uncertain_rows()}
    assert rows[("ZZZ", "")]["reason"] == "not_placed"
    assert rows[("AAA", "A")]["reason"].startswith("seen_under_two_names") and rows[("AAA", "A")]["candidates"] == "B"


def test_uncertain_rows_round_trip_through_the_uncertain_table(tmp_path):
    rows = _one(ending("A", "2015-03-10", **{**GOOD, "ltd": ""})).uncertain_rows()
    store.write_tables(tmp_path, {"uncertain": rows})
    assert store.read_table("uncertain", store.table_path(tmp_path, "uncertain")) == rows == [
        {"kind": ENDING, "ticker": "AAA", "sec_id": "A", "date": "2015-03-10", "reason": "no_last_trade_date",
         "candidates": ""}]


def test_one_security_seen_under_two_names_on_a_day_is_one_uncertain_row():
    o = [obs("AAA", "2010-06-30", "A", "conflict", name="ALPHA"), obs("AAA", "2010-06-30", "A", "conflict", name="ALFA")]
    rows = _one(observations=o).uncertain_rows()
    assert [(r["kind"], r["ticker"], r["date"], r["reason"]) for r in rows] == [
        ("seed", "AAA", "2010-06-30", "seen_under_two_names")]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_verdict.py -q -o addopts=""`
Expected: collection error `ModuleNotFoundError: No module named 'delist_detection.verdict'`.

- [ ] **Step 3: Write `src/delist_detection/verdict.py`**

```python
"""One verdict per seed, security and ending: confirmed, or uncertain with its
reasons (spec: Delist Library Reset, Part 3 "Invariants the library's build
enforces"; decisions 1, 4 and 9).

- A security is confirmed when its identity rests on a FIGI, or, for a
  placeholder (a CIK and class with no FIGI), on a filing that ties its
  ticker to that CIK (decision 1; `ticker_evidence`); when every seed
  resolved to it falls inside its ticker history; and when no other security
  holds one of its tickers over an overlapping date range, unless an ending
  of one hands the ticker to the other.
- An ending (a delistings.csv row whose successor is not the security itself)
  is confirmed when its security is confirmed, its issuer CIK did not come
  from today's ticker map, and its exit kind rests on a filing: not the
  continued-filings rule, not the no-evidence default, not unknown. A
  continuation (a successor other than itself) must rest on a successor
  filing or a CUSIP switch, not on timing alone. Any other ending needs a
  last trade date from an exchange print (MIDAS, a Nasdaq halt, the
  exchange's notice, 8-K item 3.01) that is confirmed, that no other text
  source contradicts unless MIDAS or a halt measured it, and that falls no
  later than the Form 25's effective date. The value never decides the
  verdict, except assumed par after a failed payout gate (decision 4).
- A seed (an observation_map row) is confirmed when it has a sec_id, was
  seen under one name that day, falls inside one of its security's ticker
  intervals, and its security is confirmed.

`uncertain_rows` is uncertain.csv: every uncertain security and ending, and
every seed uncertain for a reason of its own; a seed whose only problem is
its security is counted, not listed. Each reason is `code` or `code:detail`.
Pure: reads the tables as store.read_table returns them.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from .lifecycle import CONTINUED_FILINGS, EXCHANGE_PRINT_SOURCES, Tables, flag_names

SEED, SECURITY, ENDING = "seed", "security", "ending"
FORM25_EFFECTIVE_DAYS = 10               # a Form 25 takes effect 10 days after it is filed
MEASURED_SOURCES = frozenset({"midas", "nasdaq_halt"})
SECURITY_UNCERTAIN = "security_uncertain"


@dataclass(frozen=True)
class Verdict:
    reasons: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()

    @property
    def confirmed(self) -> bool:
        return not self.reasons


def _is_continuation(row: Mapping[str, str]) -> bool:
    return bool(row["successor_sec_id"]) and row["successor_sec_id"] != row["sec_id"]


def is_introduction(row: Mapping[str, str]) -> bool:
    """An observation_map row that is its era's first sighting: the spec's
    seed (one row per introduction). An era key reads `TICKER@DATE[#n]`."""
    return row["as_of"] == row["era"].split("@", 1)[-1].split("#", 1)[0]


def _covered(intervals: list[Mapping[str, str]], day: str) -> bool:
    return any(r["valid_from"] <= day and (not r["valid_to"] or day <= r["valid_to"]) for r in intervals)


def _security_verdicts(tables: Tables, evidence: Mapping[str, str]) -> dict[str, Verdict]:
    intervals: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for r in tables.ticker_history:
        intervals[r["sec_id"]].append(r)
    linked = {frozenset((r["sec_id"], other)) for r in tables.delistings
              for other in (r["successor_sec_id"], r["ticker_successor_sec_id"]) if other and other != r["sec_id"]}
    overlaps: dict[str, dict[str, str]] = defaultdict(dict)          # sec_id -> {other sec_id: ticker}
    by_ticker: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for r in tables.ticker_history:
        by_ticker[r["ticker"]].append(r)
    for ticker, rows in by_ticker.items():
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a["sec_id"] == b["sec_id"] or frozenset((a["sec_id"], b["sec_id"])) in linked:
                    continue
                if a["valid_from"] <= (b["valid_to"] or "9999-12-31") and b["valid_from"] <= (a["valid_to"] or "9999-12-31"):
                    overlaps[a["sec_id"]][b["sec_id"]] = ticker
                    overlaps[b["sec_id"]][a["sec_id"]] = ticker
    outside: dict[str, list[str]] = defaultdict(list)       # introductions outside the security's history
    for r in tables.observation_map:
        if r["sec_id"] and is_introduction(r) and not _covered(intervals[r["sec_id"]], r["as_of"]):
            outside[r["sec_id"]].append(r["as_of"])
    out: dict[str, Verdict] = {}
    for s in tables.securities:
        sid, reasons = s["sec_id"], []
        if s["figi_source"] == "placeholder" and not evidence.get(sid):
            reasons.append(f"placeholder_without_ticker_filing:CIK {s['issuer_cik']}")
        if outside[sid]:
            reasons.append(f"seeds_outside_history:{len(outside[sid])} from {min(outside[sid])}")
        reasons += [f"ticker_overlap:{ticker}" for ticker in sorted(set(overlaps[sid].values()))]
        out[sid] = Verdict(tuple(reasons), tuple(sorted(overlaps[sid])))
    return out


def _ending_reasons(row: Mapping[str, str], security: Verdict | None) -> list[str]:
    flags = flag_names(row)
    reasons = []
    if security is None or not security.confirmed:
        reasons.append(SECURITY_UNCERTAIN)
    if "resolved_by_current_ticker_map" in flags:
        reasons.append("issuer_from_todays_ticker_map")
    if row["reason"].startswith(CONTINUED_FILINGS):
        reasons.append("continued_filings_rule")
    if "no_evidence_default" in flags:
        reasons.append("no_evidence_default")
    if row["bucket"] == "unknown":
        reasons.append("unknown_exit_kind")
    if row["dlret_method"] == "assumed_par" and "payout_gate_failed" in flags:
        reasons.append("assumed_par_after_failed_gate")
    if _is_continuation(row):
        if "(timing:cik)" in row["reason"]:
            reasons.append("continuation_by_timing_only")
        return reasons
    ltd, source = row["last_trade_date"], row["last_trade_date_source"]
    if not ltd:
        reasons.append("no_last_trade_date")
        return reasons
    if source not in EXCHANGE_PRINT_SOURCES:
        reasons.append(f"last_trade_not_exchange_print:{source or 'none'}")
    if "last_trade_date_unconfirmed" in flags:
        reasons.append("last_trade_date_unconfirmed")
    if "last_trade_date_conflict" in flags and source not in MEASURED_SOURCES:
        reasons.append("last_trade_date_text_conflict")
    if row["delist_filing_date"] and row["delist_filing_form"].startswith("25"):
        effective = date.fromisoformat(row["delist_filing_date"]) + timedelta(days=FORM25_EFFECTIVE_DAYS)
        if date.fromisoformat(ltd) > effective:
            reasons.append(f"last_trade_after_form25_effective:{effective.isoformat()}")
    return reasons


def _seed_reasons(row: Mapping[str, str], covered: bool, names_on_day: int,
                  security: Verdict | None) -> list[str]:
    if not row["sec_id"]:
        return ["not_placed"]
    reasons = []
    if names_on_day > 1:
        reasons.append("seen_under_two_names")
    if not covered:
        reasons.append("outside_security_history")
    if security is None or not security.confirmed:
        reasons.append(SECURITY_UNCERTAIN)
    return reasons


@dataclass(frozen=True)
class Verdicts:
    tables: Tables
    securities: Mapping[str, Verdict]
    endings: Mapping[tuple[str, str], Verdict]          # (sec_id, delist_date)
    seeds: Mapping[tuple[str, str, str, str, str, str], Verdict]   # observation_map's key

    def counts(self) -> dict[str, int]:
        """Uncertain verdicts per kind, the listed and the unlisted alike."""
        return {kind: sum(not v.confirmed for v in verdicts.values())
                for kind, verdicts in ((SEED, self.seeds), (SECURITY, self.securities), (ENDING, self.endings))}

    def uncertain_rows(self) -> list[dict[str, str]]:
        """uncertain.csv's rows (UNCERTAIN_COLUMNS), one per uncertain security
        and ending and per seed with a reason of its own; seeds that share a
        (ticker, date, sec_id) are one row."""
        latest: dict[str, str] = {}
        first: dict[str, str] = {}
        for r in sorted(self.tables.ticker_history, key=lambda r: r["valid_from"]):
            latest[r["sec_id"]] = r["ticker"]
            first.setdefault(r["sec_id"], r["valid_from"])
        rows: dict[tuple[str, str, str, str], dict[str, str]] = {}

        def add(kind: str, ticker: str, sec_id: str, day: str, v: Verdict) -> None:
            key = (kind, sec_id, day, ticker)
            row = rows.setdefault(key, {"kind": kind, "ticker": ticker, "sec_id": sec_id, "date": day,
                                        "reason": "", "candidates": ""})
            reasons = [x for x in row["reason"].split(";") if x] + [x for x in v.reasons if x not in row["reason"]]
            cands = [x for x in row["candidates"].split(";") if x] + [x for x in v.candidates if x not in row["candidates"]]
            row["reason"], row["candidates"] = ";".join(reasons), ";".join(cands)

        for sid, v in self.securities.items():
            if not v.confirmed:
                add(SECURITY, latest.get(sid, ""), sid, first.get(sid, ""), v)
        rows_by_key = {(r["sec_id"], r["delist_date"]): r for r in self.tables.delistings}
        for key, v in self.endings.items():
            if not v.confirmed:
                add(ENDING, rows_by_key[key]["ticker"] or latest.get(key[0], ""), key[0], key[1], v)
        seed_sec = {_seed_key(r): r["sec_id"] for r in self.tables.observation_map}
        for key, v in self.seeds.items():
            own = tuple(x for x in v.reasons if x != SECURITY_UNCERTAIN)
            if own:
                add(SEED, key[0], seed_sec[key], key[1], Verdict(own, v.candidates))
        return [rows[k] for k in sorted(rows)]


def _seed_key(r: Mapping[str, str]) -> tuple[str, str, str, str, str, str]:
    return (r["ticker"], r["as_of"], r["name"], r["cusip"], r["pin_cik"], r["pin_sec_id"])


def decide(tables: Tables, evidence: Mapping[str, str]) -> Verdicts:
    """Every verdict of one run's tables. `evidence` maps a placeholder's sec_id
    to what ties its ticker to its CIK (`ticker_evidence.evidence_for`); a
    placeholder missing from it, or mapped to "", has none."""
    securities = _security_verdicts(tables, evidence)
    endings = {(r["sec_id"], r["delist_date"]): Verdict(tuple(_ending_reasons(r, securities.get(r["sec_id"]))))
               for r in tables.delistings if r["successor_sec_id"] != r["sec_id"]}
    intervals: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for r in tables.ticker_history:
        intervals[r["sec_id"]].append(r)
    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    secs_on_day: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in tables.observation_map:
        names[(r["ticker"], r["as_of"])].add(r["name"])
        if r["sec_id"]:
            secs_on_day[(r["ticker"], r["as_of"])].add(r["sec_id"])
    seeds = {}
    for r in tables.observation_map:
        day = (r["ticker"], r["as_of"])
        reasons = _seed_reasons(r, _covered(intervals[r["sec_id"]], r["as_of"]) if r["sec_id"] else False,
                                len(names[day]), securities.get(r["sec_id"]))
        others = tuple(sorted(secs_on_day[day] - {r["sec_id"]})) if len(names[day]) > 1 else ()
        seeds[_seed_key(r)] = Verdict(tuple(reasons), others)
    return Verdicts(tables, securities, endings, seeds)
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_verdict.py -q -o addopts=""`
Expected: `23 passed`.

- [ ] **Step 5: Check the rules on the committed output**

Run:

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python - <<'EOF'
from collections import Counter
from delist_detection.lifecycle import Tables
from delist_detection.verdict import decide
v = decide(Tables.read("output"), {})
print(v.counts())
print(Counter(x.split(":")[0] for r in v.uncertain_rows() if r["kind"] == "security" for x in r["reason"].split(";")))
EOF
```

Expected: `{'seed': 1114, 'security': 130, 'ending': 279}`, and the security reasons
`placeholder_without_ticker_filing` 100, `seeds_outside_history` 34 and `ticker_overlap` 18. With no evidence
passed in, all 100 placeholders count as uncertain; the pipeline's evidence stage (Task 5) clears those with
ticker evidence.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/verdict.py tests/test_verdict.py
git commit -m "One verdict per seed, security and ending (reset-2)"
```

---

### Task 3: Decision 1's ticker check

**Files:**
- Create: `src/delist_detection/ticker_evidence.py`
- Modify: `src/delist_detection/edgar.py` (`full_text_search`)
- Test: `tests/test_ticker_evidence.py`

**Interfaces:**
- Produces:
  - Constants: `TICKER_TIERS`, `SEARCH_FORMS`, `SEARCH_PAD_DAYS` (365) and `MIN_SEARCH_TICKER` (3).
  - `EraEvidence(ticker, first, last, tier)`.
  - `ticker_filing(search, cik, ticker, first, last) -> str | None`.
  - `evidence_for(cik, eras, search) -> str`, which returns `"tier:<tier>"`, `"filing:<accession>"` or `""`.
  - `EdgarClient.full_text_search(q, forms, lo, hi, *, ciks=())`.

A live probe on 2026-10-02 confirmed that EDGAR's full-text search honours the filter. `q="YHOO"`, forms 8-K, in
2016 returned 9 hits from 2 filers without the filter, and 8 hits from CIK 1011006 alone with
`&ciks=0001011006`. `ticker_filing` also checks each hit's own `ciks`, so a server that ignores the filter can
never produce a false hit.

- [ ] **Step 1: Write the failing tests**

`tests/test_ticker_evidence.py`:

```python
from datetime import date

import pytest

from delist_detection.edgar import EdgarBlocked, EdgarClient
from delist_detection.ticker_evidence import SEARCH_FORMS, EraEvidence, evidence_for, ticker_filing


class _Search:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def __call__(self, q, forms, lo, hi, *, ciks=()):
        self.calls.append((q, forms, lo, hi, tuple(ciks)))
        return self.hits


def _hit(cik, adsh="0001011006-16-000001"):
    return {"_id": f"{adsh}:doc.htm", "_source": {"ciks": [f"{cik:010d}"], "adsh": adsh}}


ERA = EraEvidence("YHOO", "2010-06-30", "2016-06-30", "name_search")


def test_a_resolver_tier_that_names_the_ticker_is_evidence_without_a_search():
    search = _Search([])
    assert evidence_for(1011006, [EraEvidence("YHOO", "2010-06-30", "2016-06-30", "cik_map")], search) == "tier:cik_map"
    assert search.calls == []


def test_a_filing_of_the_cik_naming_the_ticker_is_evidence():
    search = _Search([_hit(1011006)])
    assert evidence_for(1011006, [ERA], search) == "filing:0001011006-16-000001"
    assert search.calls == [('"YHOO"', SEARCH_FORMS, date(2009, 6, 30), date(2017, 6, 30), (1011006,))]


def test_a_hit_from_another_filer_is_not_evidence():
    assert ticker_filing(_Search([_hit(999)]), 1011006, "YHOO", "2010-06-30", "2016-06-30") is None


def test_a_short_ticker_is_never_searched():
    search = _Search([_hit(52988)])
    assert evidence_for(52988, [EraEvidence("J", "2012-06-29", "2014-06-30", "name_search")], search) == ""
    assert search.calls == []


def test_no_cik_or_no_search_means_no_evidence():
    assert evidence_for(None, [ERA], _Search([_hit(1011006)])) == ""
    assert evidence_for(1011006, [ERA], None) == ""


def test_full_text_search_narrows_to_the_given_filers(tmp_path, monkeypatch):
    client = EdgarClient(cache_dir=tmp_path, user_agent="Test Co test@example.com")
    urls = []
    monkeypatch.setattr(client, "efts_search", lambda url, window_end: urls.append(url) or [])
    client.full_text_search('"YHOO"', "8-K", date(2016, 1, 1), date(2016, 12, 31), ciks=(1011006,))
    client.full_text_search('"YHOO"', "8-K", date(2016, 1, 1), date(2016, 12, 31))
    assert urls[0].endswith("&ciks=0001011006") and "ciks=" not in urls[1]


def test_an_sec_refusal_during_the_search_stops_the_run():
    def refuse(*args, **kwargs):
        raise EdgarBlocked("403 from efts.sec.gov")
    with pytest.raises(EdgarBlocked):
        evidence_for(1011006, [ERA], refuse)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_ticker_evidence.py -q -o addopts=""`
Expected: collection error `ModuleNotFoundError: No module named 'delist_detection.ticker_evidence'`.

- [ ] **Step 3: Write `src/delist_detection/ticker_evidence.py`**

```python
"""What ties a placeholder's ticker to its CIK (decision 1 of the Delist Library
Reset: a placeholder counts as confirmed only when a filing check finds the
ticker under that CIK).

A placeholder is a security with no FIGI, known only by its issuer CIK and
share class. Its identity is confirmed when:
- the resolver tier that found the CIK of one of its eras already ties the
  ticker to it: a caller's pin or hand override (`cik_map`, `manual`,
  `rename`), the Form 25/15 full-text tier that matched the ticker's own
  `(TICKER)` token (`efts`), or EDGAR's current ticker map (`company_tickers`);
- or else EDGAR's full-text search finds the ticker in one of that CIK's own
  filings dated within a year of the era's sightings (`ticker_filing`).
A ticker shorter than MIN_SEARCH_TICKER is never searched: the phrase would
match ordinary words in the issuer's own filings.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

TICKER_TIERS = frozenset({"cik_map", "manual", "rename", "efts", "company_tickers"})
SEARCH_FORMS = "8-K,10-K,10-Q,DEF 14A,25-NSE,20-F,6-K,40-F"
SEARCH_PAD_DAYS = 365
MIN_SEARCH_TICKER = 3


@dataclass(frozen=True)
class EraEvidence:
    ticker: str
    first: str               # the era's first and last sightings, ISO dates
    last: str
    tier: str                # the resolver tier that found the era's CIK ("" when unknown)


def ticker_filing(search: Callable, cik: int, ticker: str, first: str, last: str) -> str | None:
    """The accession of a filing by `cik` whose text names `ticker`, filed within
    SEARCH_PAD_DAYS of [first, last], or None. `search` is
    EdgarClient.full_text_search; a hit counts only when its own `ciks` list
    holds `cik`."""
    if len(ticker) < MIN_SEARCH_TICKER:
        return None
    lo = date.fromisoformat(first) - timedelta(days=SEARCH_PAD_DAYS)
    hi = date.fromisoformat(last) + timedelta(days=SEARCH_PAD_DAYS)
    for hit in search(f'"{ticker}"', SEARCH_FORMS, lo, hi, ciks=(cik,)):
        src = hit.get("_source", {})
        if any(int(c) == cik for c in src.get("ciks") or []):
            return src.get("adsh") or hit.get("_id", "")
    return None


def evidence_for(cik: int | None, eras: Sequence[EraEvidence], search: Callable | None) -> str:
    """`tier:<tier>` when a resolver tier ties an era's ticker to `cik`, else
    `filing:<accession>` when `search` finds a filing, else "" (no evidence:
    no CIK, no search, or no hit)."""
    for era in eras:
        if era.tier in TICKER_TIERS:
            return f"tier:{era.tier}"
    if cik is None or search is None:
        return ""
    for era in eras:
        accession = ticker_filing(search, cik, era.ticker, era.first, era.last)
        if accession:
            return f"filing:{accession}"
    return ""
```

- [ ] **Step 4: Add the filer filter to `full_text_search`**

In `src/delist_detection/edgar.py`, add `from collections.abc import Sequence` above
`from dataclasses import dataclass`, and replace `full_text_search`'s signature, docstring and URL build with:

```python
    def full_text_search(self, q: str, forms: str, lo: date, hi: date, *,
                         ciks: Sequence[int] = ()) -> list[dict]:
        """EDGAR full-text search hits (`hits.hits`, trimmed as `efts_search` trims
        them) for `q` within `forms`, filed in `[lo, hi]`, cached as `efts_search`
        caches them; `ciks` limits the search to those filers' own filings. []
        when EDGAR could not answer: the successor search then leaves
        `successor_unknown` set. A 403/429 raises `EdgarBlocked`.
        """
        url = (
            "https://efts.sec.gov/LATEST/search-index?"
            f"q={requests.utils.quote(q)}&forms={requests.utils.quote(forms)}"
            f"&dateRange=custom&startdt={lo.isoformat()}&enddt={hi.isoformat()}"
        )
        if ciks:
            url += "&ciks=" + ",".join(f"{int(c):010d}" for c in ciks)
```

Leave the `try:` block that follows unchanged.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_ticker_evidence.py -q -o addopts=""`
Expected: `7 passed`. Then run the full suite. Expected: `1583 passed, 24 xfailed`.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/ticker_evidence.py src/delist_detection/edgar.py tests/test_ticker_evidence.py
git commit -m "Decision 1: a filing must tie a placeholder's ticker to its CIK (reset-2)"
```

---

### Task 4: The scorecard counts verdicts

**Files:**
- Modify: `src/delist_detection/scorecard.py`
- Test: `tests/test_scorecard.py`

**Interfaces:**
- Consumes: `verdict.SEED`, `SECURITY` and `ENDING` (Task 2); `lifecycle.Lifecycle`; `Tables.uncertain`
  (Task 1).
- Produces: the metrics `V.uncertain_seeds`, `V.uncertain_securities`, `V.uncertain_endings`,
  `V.uncertain_endings_in_window`, `V.uncertain_distress`, `V.uncertain_input_tickers`,
  `V.uncertain_input_tickers_share` and `V.audit.confirmed_but_wrong`. All of them except
  `V.uncertain_input_tickers` are floored DOWN. They are present only when `tables.uncertain` is not None.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scorecard.py`:

```python
def _uncertain(kind, sec_id, day, reason="x"):
    return {"kind": kind, "ticker": "", "sec_id": sec_id, "date": day, "reason": reason, "candidates": ""}


def _with_uncertain(rows):
    t = _tables()
    return type(t)(t.securities, t.ticker_history, t.delistings, t.observation_map, t.review, rows)


def test_verdict_lines_count_uncertain_csv_and_appear_only_with_it():
    assert not any(k.startswith("V.") for k in sc.build(_tables(), as_of=AS_OF)["metrics"])
    rows = [_uncertain("security", "C", "2008-01-02"), _uncertain("ending", "D", "2025-02-10"),
            _uncertain("ending", "A", "2012-03-10"), _uncertain("seed", "", "2010-06-30")]
    m = sc.build(_with_uncertain(rows), as_of=AS_OF,
                 config=ScorecardConfig(window=Window("2006-01-02", "2024-12-29")))["metrics"]
    assert (m["V.uncertain_seeds"], m["V.uncertain_securities"], m["V.uncertain_endings"]) == (1, 1, 2)
    assert (m["V.uncertain_distress"], m["V.uncertain_endings_in_window"]) == (1, 1)      # D is a 2025 liquidation
    # AAA (A's ending), CCC (security C), DDD (D's ending), GGG (no mapped sighting)
    assert m["V.uncertain_input_tickers"] == 4 and m["V.uncertain_input_tickers_share"] == round(4 / 7, 6)


def test_an_audited_wrong_row_counts_as_confirmed_but_wrong_unless_listed():
    audit = [_case("r1", group="random", exit_kind="liquidation"),
             _case("r2", group="random", ticker="CCC", on="2010-06-30", terminal="ended")]
    config = ScorecardConfig(audit=audit)
    assert sc.build(_with_uncertain([]), as_of=AS_OF, config=config)["metrics"]["V.audit.confirmed_but_wrong"] == 2
    listed = _with_uncertain([_uncertain("ending", "A", "2012-03-10")])
    assert sc.build(listed, as_of=AS_OF, config=config)["metrics"]["V.audit.confirmed_but_wrong"] == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_scorecard.py -q -o addopts=""`
Expected: 2 failed with `KeyError: 'V.uncertain_seeds'` and `KeyError: 'V.audit.confirmed_but_wrong'`.

- [ ] **Step 3: Add the V lines**

In `src/delist_detection/scorecard.py`:

1. Add `Lifecycle` to the lifecycle import (`NO_MAPPED_SIGHTING, Lifecycle, LifecycleView, Tables,
   flag_names`), and below the `.truth` import add `from .verdict import ENDING, SECURITY, SEED`.
2. In `METRICS`, after `"A.random.upper95": DOWN,`, add:

```python
    "V.uncertain_seeds": DOWN, "V.uncertain_securities": DOWN, "V.uncertain_endings": DOWN,
    "V.uncertain_endings_in_window": DOWN, "V.uncertain_distress": DOWN, "V.uncertain_input_tickers_share": DOWN,
    "V.audit.confirmed_but_wrong": DOWN,
```

3. Directly above `def _truth_lines`, add:

```python
@dataclass(frozen=True)
class _Uncertain:
    """uncertain.csv's rows as look-ups."""
    seeds: int
    securities: frozenset[str]
    endings: frozenset[tuple[str, str]]          # (sec_id, delist_date)

    @classmethod
    def of(cls, rows: Sequence[Mapping[str, str]]) -> _Uncertain:
        return cls(sum(r["kind"] == SEED for r in rows),
                   frozenset(r["sec_id"] for r in rows if r["kind"] == SECURITY),
                   frozenset((r["sec_id"], r["date"]) for r in rows if r["kind"] == ENDING))

    def touches(self, lc: Lifecycle) -> bool:
        """A lifecycle whose chain holds an uncertain security, or whose final
        ending is uncertain."""
        if set(lc.chain) & self.securities:
            return True
        return lc.final is not None and (lc.final["sec_id"], lc.final["delist_date"]) in self.endings


def _verdict_lines(tables: Tables, view: LifecycleView, window: Window | None,
                   unc: _Uncertain | None) -> dict[str, float]:
    """The V lines, from uncertain.csv; none when the run wrote no uncertain.csv."""
    if unc is None:
        return {}
    distress = {(r["sec_id"], r["delist_date"]) for r in tables.delistings if r["bucket"] in DISTRESS}
    by_ticker = view.by_input_ticker()
    tickers = sum(lc.kind == NO_MAPPED_SIGHTING or unc.touches(lc) for lc in by_ticker.values())
    out: dict[str, float] = {
        "V.uncertain_seeds": unc.seeds, "V.uncertain_securities": len(unc.securities),
        "V.uncertain_endings": len(unc.endings), "V.uncertain_distress": len(unc.endings & distress),
        "V.uncertain_input_tickers": tickers, "V.uncertain_input_tickers_share": _share(tickers, len(by_ticker)),
    }
    if window is not None:
        out["V.uncertain_endings_in_window"] = sum(window.contains(day) for _, day in unc.endings)
    return out


def _audited_uncertain(case: TruthCase, view: LifecycleView, unc: _Uncertain) -> bool:
    sec = view.security_on(case.ticker, case.on)
    return sec is None or unc.touches(view.lifecycle(sec))
```

4. Change `_truth_lines`'s signature to
   `def _truth_lines(view: LifecycleView, config: ScorecardConfig, unc: _Uncertain | None = None)
   -> dict[str, float]:`. Inside `if audit:`, after the census loop, add:

```python
        if unc is not None:
            out["V.audit.confirmed_but_wrong"] = sum(not j.ok and not _audited_uncertain(j.case, view, unc)
                                                     for j in audit)
```

5. In `build`, replace the `metrics = ...` statement with:

```python
    unc = None if tables.uncertain is None else _Uncertain.of(tables.uncertain)
    metrics = {**_lifecycle_lines(view), **_identity_lines(tables), **_ending_lines(tables, config.window),
               **_verdict_lines(tables, view, config.window, unc), **_truth_lines(view, config, unc)}
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: `1585 passed, 24 xfailed`. The committed-output floor test still passes, because the committed
`output/` has no `uncertain.csv` and so no V lines.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/scorecard.py tests/test_scorecard.py
git commit -m "Scorecard: uncertain verdicts and confirmed-but-wrong audit rows (reset-2)"
```

---

### Task 5: Every run writes `uncertain.csv`

**Files:**
- Modify: `src/delist_detection/pipeline.py`, `scripts/classify_universe.py`
- Modify: `tests/test_pipeline.py`, `tests/test_classify_universe_cli.py`, `tests/test_pipeline_prefetch.py`,
  `tests/test_run_provenance.py`

**Interfaces:**
- Consumes: `verdict.decide` (Task 2); `ticker_evidence.EraEvidence` and `evidence_for` (Task 3); the scorecard
  (Task 4).
- Produces:
  - `pipeline._era_tier(answers, era_key) -> str`.
  - `pipeline._ticker_evidence(ctx, securities, answers) -> dict[sec_id, str]`, stage 10e, metered as
    `"ticker evidence"`.
  - `pipeline._as_read(tables) -> Tables`.
  - `pipeline._scorecard(ctx, read: Tables, config, limit)`, stage 10g.
  - `RunSummary.uncertain: dict[str, int]`.
  - `output/uncertain.csv` on every run.
  - The CLI line `Uncertain (uncertain.csv): S securities, E endings, N seeds`.

- [ ] **Step 1: Write the failing tests**

1. In `tests/test_pipeline.py`, change `def _clients(fake_edgar, ftd_rows=None):` to
   `def _clients(fake_edgar, ftd_rows=None, extra_obs=()):`. In its `obs = [...]` list, end the last entry with
   `, *extra_obs]` so that it reads `Observation("LIVE", "2025-06-30", "LIVE CO", cik=777), *extra_obs]`.
2. Append to `tests/test_pipeline.py`:

```python
def test_every_run_writes_uncertain_csv(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert read_table("uncertain", table_path(tmp_path, "uncertain")) == []
    assert summary.uncertain == {"seed": 0, "security": 0, "ending": 0}


def test_a_sighting_after_the_ending_is_an_uncertain_seed_but_not_an_uncertain_security(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar, extra_obs=(Observation("AET", "2019-06-28", "AETNA INC", cik=1122304),))
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    rows = read_table("uncertain", table_path(tmp_path, "uncertain"))
    assert rows == [{"kind": "seed", "ticker": "AET", "sec_id": "BBG000FJLFX8", "date": "2019-06-28",
                     "reason": "outside_security_history", "candidates": ""}]
    assert summary.uncertain == {"seed": 1, "security": 0, "ending": 0}


class _SearchEdgar:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def full_text_search(self, q, forms, lo, hi, *, ciks=()):
        self.calls.append((q, tuple(ciks)))
        return self.hits


def test_ticker_evidence_asks_the_search_only_for_a_placeholder_without_a_ticker_tier():
    from types import SimpleNamespace
    from delist_detection import manifest as run_manifest
    from delist_detection.observations import TickerEra
    edgar = _SearchEdgar([{"_id": "a:d", "_source": {"ciks": ["0000000555"], "adsh": "0000000555-16-000001"}}])
    ctx = pipeline._RunContext(SimpleNamespace(edgar=edgar), date(2026, 9, 25), lambda *_: None, 1,
                               run_manifest.StageMeter(lambda *_: None))
    securities = {
        "CIK555-COMMON": Security("CIK555-COMMON", 555, "COMMON", "PHX CO", "", True, "placeholder",
                                  eras=[TickerEra("PHX", "2015-06-30", "2016-06-30")]),
        "CIK777-COMMON": Security("CIK777-COMMON", 777, "COMMON", "PIN CO", "", True, "placeholder",
                                  eras=[TickerEra("PIN", "2015-06-30", "2016-06-30")]),
        "BBGFIGI": Security("BBGFIGI", 888, "COMMON", "FIGI CO", "", True, "cusip",
                            eras=[TickerEra("FIG", "2015-06-30", "2016-06-30")]),
    }
    answers = pipeline._IssuerAnswers(
        resolutions={"PHX@2015-06-30": TickerResolution("PHX", 555, None, "name_search"),
                     "PIN@2015-06-30": TickerResolution("PIN", 777, None, "cik_map")},
        issuers={}, last_seen={}, names_degraded=set())
    assert pipeline._ticker_evidence(ctx, securities, answers) == {
        "CIK555-COMMON": "filing:0000000555-16-000001", "CIK777-COMMON": "tier:cik_map"}
    assert edgar.calls == [('"PHX"', (555,))]
```

3. Append to `tests/test_classify_universe_cli.py`:

```python
def test_main_prints_the_uncertain_counts(monkeypatch, capsys):
    summary = _FakeSummary({})
    summary.uncertain = {"seed": 3, "security": 1, "ending": 2}
    assert _run_main(monkeypatch, {}, summary=summary) == 0
    assert "Uncertain (uncertain.csv): 1 securities, 2 endings, 3 seeds" in capsys.readouterr().out
```

4. Update the existing tests that count tables or stages:
   - `tests/test_classify_universe_cli.py`: in `_FakeSummary.__init__`, after
     `self.scorecard_drops, self.golden_failures = [], []`, add `self.uncertain = {}`.
   - `tests/test_pipeline.py`, `test_run_is_deterministic`: add `"uncertain"` to `names` (after
     `"observation_map"`).
   - `tests/test_pipeline_prefetch.py`: the line `assert len(csv1) == 8 and csv1 == csvn  # ...` becomes
     `assert len(csv1) == 9 and csv1 == csvn         # the six tables, review_summary, observation_map and uncertain`,
     and the docstring's "both write the same eight CSVs" becomes "nine".
   - `tests/test_run_provenance.py`: add `"ticker evidence"` to the expected `m["stages"]` set.

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_classify_universe_cli.py tests/test_pipeline_prefetch.py tests/test_run_provenance.py -q -o addopts=""`
Expected: failures. `uncertain.csv` does not exist, `RunSummary` has no attribute `uncertain`, and
`pipeline._ticker_evidence` is missing.

- [ ] **Step 3: Wire stages 10e to 10g into `pipeline.py`**

1. Imports. After `from .lifecycle import Tables`, add
   `from .ticker_evidence import EraEvidence, evidence_for`. After the `.ticker_resolver` import, add
   `from .verdict import decide as decide_verdicts`.
2. `RunSummary`: after `golden_failures`, add:

```python
    uncertain: dict[str, int] = field(default_factory=dict)         # uncertain verdicts per kind (verdict.Verdicts.counts)
```

3. Replace the whole `_scorecard` function, from its `def` line to the line
   `card = run_scorecard.build(...)`, with:

```python
def _era_tier(answers: _IssuerAnswers, era_key: str) -> str:
    """The resolver tier that found an era's CIK: its first-pass answer, else its
    second-pass one, else ""."""
    if era_key in answers.resolutions:
        return answers.resolutions[era_key].source
    if era_key in answers.inferred:
        return answers.inferred[era_key].source
    return ""


def _ticker_evidence(ctx: _RunContext, securities: dict[str, Security], answers: _IssuerAnswers) -> dict[str, str]:
    """10e. What ties each placeholder's ticker to its CIK (decision 1;
    ticker_evidence.evidence_for): a resolver tier that names the ticker, else
    a full-text hit in the CIK's own filings. A client without full-text
    search (a test double) gives every other placeholder no evidence."""
    search = getattr(ctx.clients.edgar, "full_text_search", None)
    mark = ctx.meter.start()
    out = {s.sec_id: evidence_for(s.issuer_cik,
                                  [EraEvidence(e.ticker, e.first, e.last, _era_tier(answers, e.key)) for e in s.eras],
                                  search)
           for s in securities.values() if s.figi_source == "placeholder"}
    ctx.meter.done("ticker evidence", mark)
    return out


def _as_read(tables: dict[str, list[dict]]) -> Tables:
    """The tables about to be written, as store.read_table would read them back."""
    def rows(name: str) -> list[dict[str, str]]:
        return formatted(name, tables[name])
    return Tables(rows("securities"), rows("ticker_history"), rows("delistings"), rows("observation_map"),
                  rows("review"), rows("uncertain") if "uncertain" in tables else None)


def _scorecard(ctx: _RunContext, read: Tables, config: run_scorecard.ScorecardConfig, limit: int | None) -> dict:
    """10g. The scorecard of the tables about to be written (`read`), with
    `drops`: the floored numbers that got worse. A --limit subset sees a
    fraction of the universe, so its numbers are never compared to the floor."""
    card = run_scorecard.build(read, as_of=ctx.as_of, config=config)
```

   Keep the rest of `_scorecard`'s body (the `card["drops"]` and logging lines and `return card`) unchanged.

4. In `_run`, replace `card = _scorecard(ctx, tables, scorecard, limit)  # 10e` with:

```python
    evidence = _ticker_evidence(ctx, securities, answers)                                          # 10e
    verdicts = decide_verdicts(_as_read(tables), evidence)                                         # 10f
    tables["uncertain"] = verdicts.uncertain_rows()
    card = _scorecard(ctx, _as_read(tables), scorecard, limit)                                     # 10g
```

   and end the `return RunSummary(...)` call with:

```python
                      scorecard_drops=card["drops"], golden_failures=card["golden_failures"],
                      uncertain=verdicts.counts())
```

- [ ] **Step 4: Print the counts in `scripts/classify_universe.py`**

In the module docstring's `Writes:` paragraph, change `observation_map.csv, then scorecard.json` to
`observation_map.csv, uncertain.csv, then scorecard.json`. In `main`, directly above
`error_count = summary.review_flags.get("error", 0)`, add:

```python
    u = summary.uncertain
    print(f"Uncertain (uncertain.csv): {u.get('security', 0)} securities, {u.get('ending', 0)} endings, "
          f"{u.get('seed', 0)} seeds")
```

- [ ] **Step 5: Run the full suite**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`
Expected: `1589 passed, 24 xfailed`.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/pipeline.py scripts/classify_universe.py tests/test_pipeline.py \
        tests/test_classify_universe_cli.py tests/test_pipeline_prefetch.py tests/test_run_provenance.py
git commit -m "Every run writes uncertain.csv: ticker evidence, verdicts, scorecard (reset-2)"
```

---

### Task 6: Documentation

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `CONTEXT.md`, `docs/data-flow.md`

- [ ] **Step 1: `CLAUDE.md`**

1. Change the `pytest` line's count to `1589 tests + 24 known-wrong golden xfails`.
2. Wherever CLAUDE.md says the run writes "eight" tables (the Architecture paragraph on `pipeline.run()`, the
   "Every output is written only after the whole run succeeds" invariant, and "Configurable input paths"), make
   it nine and add `uncertain` to any list of the tables. Add `uncertain` to the `classify_universe.py` output
   lists in the Commands block.
3. In the "Measurement (pure)" architecture section, add:

```markdown
- `verdict.py` — one verdict per seed (an observation_map row), security and
  ending (a delistings.csv row whose successor is not itself): `decide`
  returns `Verdicts`; `uncertain_rows()` is `uncertain.csv`. The rules are the
  spec's invariants, read from the tables (FIGI source, intervals, each
  ending's reason, flags, last-trade source and Form 25 date) plus each
  placeholder's ticker evidence. A seed is an era's first sighting for the
  security's coverage rule; later sightings outside the history are listed
  seeds only.
- `ticker_evidence.py` — decision 1: what ties a placeholder's ticker to its
  CIK. A resolver tier that names the ticker (`TICKER_TIERS`), else one
  EDGAR full-text search of the CIK's own filings (`full_text_search(...,
  ciks=)`), cached like every search.
```

4. In "Non-obvious invariants", add:

```markdown
- **Every seed, security and ending has a verdict, and every uncertain one is
  in `uncertain.csv`.** `kind` is seed | security | ending; `reason` holds
  `code` or `code:detail` items (verdict.py's docstring lists them). The
  verdict covers identity, exit kind and the last trade date, never the value
  (except assumed par after a failed payout gate, decision 4). A seed whose
  only problem is its security is counted, not listed. Pipeline stages 10e
  (ticker evidence: about one cached EDGAR search per placeholder without a
  ticker tier), 10f (verdicts) and 10g (scorecard) run before the write;
  `uncertain.csv` is written with the other tables. The scorecard's V lines
  read it; a committed output without it has no V lines.
```

- [ ] **Step 2: `README.md`**

Make the "The eight output tables" heading and its introduction say nine. After the `observation_map.csv`
section, add:

```markdown
### `uncertain.csv` — key `(kind, sec_id, date, ticker)`

One row per uncertain verdict a person must act on: `kind` is `security`
(identity not confirmed: a placeholder no filing ties to its ticker, an era's
first sighting outside its history, a ticker another security holds at the
same time), `ending` (not filing-backed, no exchange-printed last trade date,
identity through today's ticker map, a timing-only continuation, assumed par
after a failed payout gate, or its security uncertain) or `seed` (a sighting
not placed, seen under two names, or outside its security's history).
`reason` lists the codes; `candidates` the other `sec_id`s involved. A person
answers a row with a pin, an override or a drop-list row; a security or ending
not listed is confirmed.
```

- [ ] **Step 3: `CONTEXT.md`**

Add to "Language", after **Floor**:

```markdown
**Verdict**:
`confirmed` or `uncertain`, one per seed, security and ending. Confirmed means the evidence the spec requires is in hand: a FIGI or a filing tying a placeholder's ticker to its CIK, a history covering every introduction, a filing-backed exit kind and an exchange-printed last trade date. Uncertain rows go to `uncertain.csv` for a person to pin, override or drop.
_Avoid_: confidence, review
```

- [ ] **Step 4: `docs/data-flow.md`**

After the `scorecard.json` paragraph that reset-1 added, add:

```markdown
Before the write, stage 10e gathers each placeholder's ticker evidence
(`ticker_evidence.evidence_for`: a resolver tier that names the ticker, else
one full-text search of the CIK's own filings), 10f decides every verdict
(`verdict.decide` over the rows about to be written) and adds `uncertain.csv`
to the group, and 10g builds the scorecard from the same rows, so its V lines
count exactly what `uncertain.csv` lists.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md CONTEXT.md docs/data-flow.md
git commit -m "docs: verdicts and uncertain.csv (reset-2)"
```

---

### Task 7: Acceptance rebuild (network)

**Files:**
- Create: `output/uncertain.csv`
- Modify: `output/scorecard.json`, `output/run_manifest.json`, `data/scorecard.json`,
  `docs/superpowers/plans/2026-10-02-delist-library-reset.md`

This task reruns the pipeline over the committed inputs with the caches that produced the committed output.
Reset-2 adds tables and changes none, so the eight existing tables must come out byte-identical. Only then is
`uncertain.csv` committed.

- [ ] **Step 1: Make sure no other SEC client is running**

Run: `ls -la ~/.cache/delist_detection/sec_rate.lock /tmp/claude/delist_detection/sec_rate.lock`. Neither file
should have been modified in the last few minutes; if one has, wait. The committed run's caches are in the
`feat-security-master` worktree (`.claude/worktrees/feat-security-master/cache`: `edgar`, `sec_data`,
`openfigi`, `nasdaq_halts`, `llm`, `ticker_resolution.json`). Copy them into this worktree's gitignored
`cache/`, merging over what is there:

```bash
mkdir -p cache
cp -R ../feat-security-master/cache/. cache/
```

- [ ] **Step 2: Rebuild into a scratch folder**

```bash
DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src \
  ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations data/observations.csv \
  --output-dir .superpowers/sdd/reset2-acceptance --as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm
```

`EDGAR_USER_AGENT`, `OPEN_FIGI_API_KEY` and the LLM settings come from the repo's `.env`. In an agent sandbox,
allow the hosts `data.sec.gov`, `www.sec.gov`, `efts.sec.gov`, `api.openfigi.com` and `api.nasdaq.com` (and the
OpenAI host only if the LLM cache misses). Expected: exit 0, the line `Uncertain (uncertain.csv): S
securities, E endings, N seeds` with S between 52 and 111 and E between 251 and 271, and a "ticker evidence"
stage in the log with about 69 EDGAR requests on the first run.

- [ ] **Step 3: Confirm that the eight tables did not change**

For each of `securities`, `ticker_history`, `cusip_history`, `delistings`, `payouts`, `review`,
`review_summary` and `observation_map`, run `cmp output/<name>.csv .superpowers/sdd/reset2-acceptance/<name>.csv`.
Expected: no output for all eight.

If any differs, stop. Do not copy anything into `output/`. Report which tables differ and
`git diff --no-index --stat output/<name>.csv .superpowers/sdd/reset2-acceptance/<name>.csv` for each. The likely
cause is an SEC answer refreshed after its cache TTL expired. The operator decides whether to accept new tables.

- [ ] **Step 4: Publish `uncertain.csv` and raise the floor**

```bash
cp .superpowers/sdd/reset2-acceptance/uncertain.csv .superpowers/sdd/reset2-acceptance/run_manifest.json output/
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --raise-floor --write | grep '^V\.'
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""
```

Expected:
- The V lines print, with `V.uncertain_seeds 386` and `V.uncertain_input_tickers_share` between 0.100496 and
  0.116719.
- `data/scorecard.json` gains seven V floor entries.
- The suite reads `1589 passed, 24 xfailed`.

- [ ] **Step 5: Record the baseline**

In `docs/superpowers/plans/2026-10-02-delist-library-reset.md`, under "reset-2", record that decision 1 was
answered on 2026-10-02 (an EDGAR check) and decision 4 was adopted as proposed. Add one row per V line to the
Baseline table, and one sentence on how many placeholders the search confirmed (S below 111 means some did).

```bash
git add output/uncertain.csv output/scorecard.json output/run_manifest.json data/scorecard.json \
        docs/superpowers/plans/2026-10-02-delist-library-reset.md
git commit -m "Acceptance: uncertain.csv on the committed output, V floor (reset-2)"
```

---

## Self-review

- **Spec coverage.**
  - "One verdict per row": Task 2 gives a verdict to each seed, security and ending.
  - "write uncertain.csv": Tasks 1, 2 and 5. Its columns are the spec's.
  - "every seed the library could not place, every uncertain security and ending": Task 2.
  - "the earlier ending of a security that ended more than once": deferred to reset-3, which introduces one
    ending per security; until then every ending gets its own verdict.
  - Invariants "at most one sec_id per ticker per date" (ticker overlap), "every seed resolves … or is listed",
    "one verdict per seed and one per ending", "last_trade_date only from an exchange print … never after the
    Form 25 effective date" and "confirmed requires …": Task 2.
  - "At most one delistings row per sec_id", "continuation implies …" and "dlret and dlret_fill never both
    set": these concern the reset-3 contract columns.
  - Decisions 1 and 4: Tasks 3 and 2. Decision 9's timing-only rule: Task 2.
  - Decision 17's library-side gate (no harsh mark on an uncertain identity or date): `V.uncertain_distress`
    lists the distress endings qlib_practice must drop or override. qlib_practice applies the marks.
- **Placeholders.** Every code step carries its code. Expected numbers were measured on 2026-10-02 against the
  committed output, or on a scratch copy of this branch where these exact tests pass (1589 passed, 24 xfailed).
- **Type consistency.** `Verdict`, `Verdicts.counts()` keys (`seed`, `security`, `ending`), the `uncertain`
  table and `Tables.uncertain`, `EraEvidence(ticker, first, last, tier)`, and `full_text_search(..., ciks=)`
  are named the same in every task.

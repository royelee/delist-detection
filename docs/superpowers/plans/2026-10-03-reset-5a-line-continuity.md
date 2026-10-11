# Sub-plan 5a: One Line Across a CUSIP or Ticker Change Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Follow each security's line past the caller's last observation, across a reverse split (a new CUSIP under
the same ticker), a rename (the same CUSIP under a new ticker) or both, so the line ends at its real ending and not
at a guess anchored on the old ticker's last fails row; identity across the step follows rulings R1 and R2.

**Architecture:** A new pure module, `line_follow.py`, finds a line's next step in the SEC fails-to-deliver rows
(`candidate_steps`), checks it against the issuer's EDGAR record (`corroborate`, R1) and applies R2 to the new
CUSIP's OpenFIGI composite (`decide`). A new pipeline stage 4b, `_follow_lines`, runs it before the Form 25 search:
the same security takes the new CUSIP and ticker, a placeholder folds into the FIGI line its new CUSIP names, and a
FIGI line whose new CUSIP has its own composite records that composite as its line successor, which stage 9 links.
Smaller units: a when-issued ticker joins its regular-way era (U8), a CUSIP switch is timed from the old CUSIP's
settling tail (U2), a shared CUSIP reaches a sibling the ticker tier picked (U3), a security's own tickers include
its line's (U5), a Form 25 at the line's own CUSIP switch is no delisting (U6), the line successor is linked in
stage 9 (U7), and the regression report folds a renamed placeholder into its FIGI (N1).

**Tech Stack:** Python 3.10+, pytest (offline, FakeEdgar and row doubles), the SEC fails-to-deliver zips, OpenFIGI,
the Claude Code Workflow tool for the truth loop (sonnet agents).

**Spec:** `docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md` (section 1, the truth loop and
acceptance; section 2.1, rulings R1 and R2; section 3 "5a"). Roadmap:
`docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md`. Design source (read it first):
`docs/superpowers/plans/research/2026-10-03-5a-line-continuity.md` (code map, per-case table, guards, blast
radius, units U1 to U8, N1). The format exemplar is `docs/superpowers/plans/2026-10-03-reset-5-0-truth-set.md`.

## Global Constraints

- In this worktree run every command from the repo root with `PYTHONPATH=src` and
  `~/miniconda3/envs/rdagent4qlib/bin/python` (the editable install points at the main checkout). Run pytest as
  `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest` with no extra `-q` (addopts has it).
- Tests are fully offline: `FakeEdgar` (tests/conftest.py), the `_RowsFtdClient`/`_MapFigi` doubles in
  tests/test_pipeline.py, plain row fixtures. The one real-case fixture set, `tests/fixtures/lines/`, is built once
  from the local cache by the committed offline builder `scripts/build_line_fixtures.py`. Never add network to a
  test.
- `output/` is regenerated only in Task 13. Every earlier task keeps the full suite green against the committed
  output (the golden replay, the floor test and the strict diagnosis xfails read it).
- The windows (operator decision, 2026-10-03): the new rows' first row falls within **±10 trading days** of the old
  CUSIP's last live row with its settling tail of one-price rows dropped; a refusing 8-K item 1.03 window is
  **[first − 180, first + 30] days**.
- R1 over R2: a line is followed only when the old registrant carries on: it files a 10-K/10-Q/20-F/40-F after the
  switch, or the evidence is its own 8-K12B/8-K12G3; and no 8-K12B/8-K12G3 by another CIK names the old issuer in
  [−30, +60] days. A switch within 120 days of the run date counts as carrying on when the security is listed today.
- R2: one security when OpenFIGI gives the new CUSIP the same composite or none; a placeholder folds into the FIGI
  line of its new CUSIP (the `_handoff_joins` behaviour); a FIGI line whose new CUSIP has another composite is two
  securities linked as a continuation.
- Out of scope: U3b (the class wildcard: MSG and LMCA are 5h), GOCO, EXE, update_truth's payout legs, the malformed
  record retry, `casesPath`.
- Must not change, pinned by tests: UAL 2006 emergence (8-K 1.03), post-bankruptcy relists (VRM 2025, DYN 2012,
  FTR to FYBR), a ticker passed to another issuer (new LMCA 2013, new MSG 2015), a spin-off on a new CUSIP (AAN,
  GOOG), two classes of one issuer, UNIT 2025 (merged out, kept composite), WLL (held CUSIP), EXE.
- Do not edit or commit `data/golden_lifecycles.csv` or `data/accuracy_audit.csv`. A golden `known_wrong` case that
  starts passing is the operator's to flip (Task 15).
- A scorecard floor entry is raised only by `scripts/scorecard.py --raise-floor`; lowering one is by hand with the
  reason in the commit, and only after the operator approves it.
- Implementers and reviewers run on model `sonnet`. Tasks 13, 14 and 15 are run by the controller, not an
  implementer (5-0 ruling R-1). The truth loop runs at most 3 rounds and at most 5 agents at a time.
- SEC access for the network run: `DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock`, one
  SEC client at a time across sessions; Bash `allowed_domains`: data.sec.gov, www.sec.gov, efts.sec.gov,
  api.openfigi.com, api.nasdaq.com, www.nasdaqtrader.com, api.openai.com.
- Every data file a script writes goes through `atomic_io.write_atomic`.
- Never merge or push; commits stay on the worktree branch. Commit messages end with the session's attribution lines
  (Co-Authored-By, Claude-Session).

## Review Focus

1. A placeholder that folds into a FIGI line whose issuer has other FIGI lines (FTR's CIK 20520 also holds FYBR):
   the issuer-and-class rule of `contract.id_change_rows` names none, so the truth row would be judged a `sec_id`
   mismatch. Stage 4b's exact rename must reach contract/id_changes.csv (Task 10, test
   `test_id_changes_name_the_figi_a_line_follow_folded_a_placeholder_into`).
2. A rename that gives the issuer's notes new CUSIPs the same day as the common (SNH: DHC, DHCNI, DHCNL). Two new
   CUSIPs would refuse the step; the common is the one under the shortest ticker (Task 7, test
   `test_of_several_new_cusips_under_the_issuers_tickers_the_shortest_symbol_is_the_common`; Task 8 real case).
3. The same CUSIP under a new, non-Q symbol after a delisting (an OTC symbol of four letters). It must not become
   the line's ticker: a 3.01, a Form 25 or a Form 15 within 30 days refuses it (Task 7, test
   `test_a_new_symbol_near_a_suspension_or_form_25_is_an_otc_move`).
4. A switch within 120 days of the run date, with no periodic report after it yet (GTES 2026). It carries on only
   when the line is listed today (Task 7, test
   `test_a_recent_step_of_a_line_listed_today_carries_on_before_its_next_report`).
5. A FIGI line whose new CUSIP has its own composite but whose ending at the switch is a merger (WCN, AAN). The
   merger stands and the composite is not added to the run (Task 11, test
   `test_a_line_successor_is_never_added_for_an_ending_that_does_not_need_it`).

## Rulings made in this plan

Each is a choice the research or the binding decisions left open; the cost if wrong is named.

- **U2's window is [settled − 5, last + 5] trading days**, the union of today's window and the one the research
  proposed. The research's [settled − 5, settled + 5] would drop an existing link whose new CUSIP starts after a
  settling tail (cost: a few links SLE-like cases need anyway; none lost).
- **`…ZZZZ` rows are no ticker sighting** (`history.ticker_sightings`), but still a CUSIP sighting and the first
  date of the new CUSIP in the line follow. Treating them exactly like `…XXXX` in `FtdIndex.trading_rows` would also
  shift every new CUSIP's cusip_history start by a day. It removes 12 one-day `XXXZZZZ` ranges from today's
  ticker_history (CLFZZZZ, DDRZZZZ, TYCZZZZ, …): regression rows the loop diagnoses.
- **The line follow's review flags are `info`** (`line_followed`, `line_follow_refused:<why>`,
  `line_continuation`). A refusal keeps the answer the security had without the step, and `check` rows would raise
  the floored `R1.4.review_rows`. Cost: a person reads them in review_summary.csv, not review.csv.
- **R1's periodic report must cover a period that ends after the step** (`report_date` > first). A 10-Q filed days
  after the step for the quarter before it is no sign the registrant carried on (BXS 2017, which the literal rule
  would follow).
- **A class letter conflicts only when the line states one too.** A COMMON line (no letter in its name) takes a new
  CUSIP whose description says "CL A" (MNI 2016); a class-A line refuses a "CL C" one (GOOG 2014).
- **A same-CUSIP new symbol is refused when another security of the run holds the CUSIP** (SPW and SPXC hold
  784635104 both; U3 joins them in stage 3 instead).
- **Of several new CUSIPs, the one under the line's own ticker, else the shortest symbol, is the switch** (SNH).
- **The other-registrant search names the issuer by its EDGAR name on the step's date** (`line_follow.name_on`),
  not today's name (`successors.successor_search_name`): an 8-K12B names the issuer as it was called then.
- **U7 also rewrites an `unknown` ending at the line's switch as the continuation** (flag `line_continuation`).
  The operator's GTES ruling makes GTES R2-differs: its Form 25 at the redomicile is classified `unknown`, and only
  linking `successor_unknown` rows (the research's U7) would leave it unmatched. A merger or a distress row at the
  switch is never rewritten.
- **A FIGI line with a line successor is not listed today** (stage 5's `retired`): its old CUSIP stopped trading
  (the tail rule) and its line goes on under the successor's composite.
- **U4 is expected to be dropped.** A pre-measurement while planning (offline, the committed run) found 13 eras
  other than UAG@2008 whose guard changes (ABI@2009, BSC@2008, CCU@2008, CYTC@2008, ERA@2013, ES@2012, FNM@2008,
  FRE@2008, NCRA@2012, STN@2008, SVM@2008, TRI@2008, UHALB@2023): more than 10. Task 5 measures again on the
  implemented rule and applies the decision rule.

## Expected outcome (from the research and an offline replay of this design)

An offline replay of `line_follow` over the committed run (cached fails zips, EDGAR and OpenFIGI only) finds about
130 candidate steps run-wide: 39 followed on cached OpenFIGI answers, about 55 waiting on an OpenFIGI answer the
cache lacks (the run asks it), the rest refused (OTC moves, bankruptcies, merged-out registrants, names, classes).
Of the 43 case-map rows of 5a:

- **About 23 should match after 5a alone.** Near-certain (14): HSC, CLI, LPI, MGI, WPG, EXBD, SFI, OEH, EHAB-WI,
  SLE, QGEN, SPW, DYN, GTES. Likely (9), each waiting only on OpenFIGI's first answer for its new CUSIP (a
  placeholder folds or attaches either way; only "several US lines" refuses it): WIN, HYH, APY, MDR, YRCW, NYCB,
  LIZ, SNH, ACXM. Possible (2): BGCP (if 088929104 has its own composite) and CLNY (if the 2021-08-16 25-NSE is not
  the common's).
- **Fewer mismatches, no match (11):** FMD, RAD, SVU, JNY, ANN, TERP, VRM, CWTR, MNI, FTR, DF move to their later
  ending; their value and date fields wait on 5d to 5g.
- **Not reached:** CCO (its old CUSIP's last live row is 13 trading days before the new one's first), UAG (U4
  dropped: 5h), MSG and LMCA (5h), GOCO and EXE (residual); WLL stays pass.
- **Outside the truth set** the replay attaches about 24 same-CUSIP renames (ADS to BFH, RLGY to HOUS, OFC to CDP,
  …), a dozen switches, and folds or renames placeholders (CBG, WCRX, AON 2012, DSW, CECO, XON, …): the loop
  diagnoses each contract change.

## File Structure

Create:
- `src/delist_detection/line_follow.py`: the pure line follow (`LineStep`, `LineEnd`, `LineSuccessor`,
  `Decision`, `candidate_steps`, `line_end`, `corroborate`, `other_registrant`, `decide`, `composites`,
  `text_symbols`, `text_cusips`, `name_on`).
- `scripts/build_line_fixtures.py`: the offline builder of `tests/fixtures/lines/`.
- `tests/fixtures/lines/{cases.json,ftd_rows.csv,edgar.json,openfigi.json,searches.json}` (built, committed).
- `tests/test_line_follow.py`, `tests/test_line_follow_cases.py`.

Modify:
- `src/delist_detection/regression.py` (N1), `truth_update.py` (N1), `scripts/update_truth.py` (N1).
- `src/delist_detection/observations.py` (U8), `history.py` (U8, U5).
- `src/delist_detection/ftd.py` (`settled_last`, `is_unassigned_symbol`).
- `src/delist_detection/security_master.py` (U2, U3, U5, `cusip_job`; U4 only if kept).
- `src/delist_detection/delistings.py` (U5, U6), `pipeline.py` (U5, U6, stage 4b, U7), `contract.py`,
  `added_securities.py` (U7), `review_triage.py` (flags).
- Tests: `test_regression.py`, `test_truth_update.py`, `test_observations.py`, `test_history.py`,
  `test_security_master.py`, `test_delistings.py`, `test_pipeline.py`, `test_contract.py`, `test_review_triage.py`,
  `test_run_provenance.py`.
- `CLAUDE.md`, the roadmap.
- Data, by Tasks 13 to 15: `output/` (the run), `data/diagnosis_truth.csv`, `data/diagnosis_truth_changes.csv`,
  `data/scorecard.json`, `output/diagnose_unknown_report/loop/` (the ledger, rounds, report).

---

### Task 1: N1, a folded placeholder is one rename in the regression report and no truth row of its own

Tier: cheap (the code is complete below).

**Files:**
- Modify: `src/delist_detection/regression.py`, `src/delist_detection/truth_update.py`, `scripts/update_truth.py`
- Test: `tests/test_regression.py`, `tests/test_truth_update.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `regression.RENAMED = "renamed"`; `regression.renamed_to(renames) -> dict[str, str]` (a chain followed to its
    end).
  - `regression.diff_contract(base, new, exclude=(), renames=None)`: `renames` are id_changes rows (default: the
    run's `new.id_changes`). A renamed placeholder's base rows are compared under its sec_id now, and each rename is
    one row `(new_sec_id, "id_changes", "sec_id", "renamed", old_sec_id, new_sec_id)`, replacing the old
    `(old_sec_id, "id_changes", "new_sec_id", "added", …)` row.
  - `regression.build_report` passes its `id_changes` to `diff_contract` as `renames`.
  - `truth_update.apply_round(..., run_sec_ids: Collection[str] | None = None, renamed: Collection[str] = ())`.
  - `scripts/update_truth.py` passes the run's securities and the old sec_ids of `regression.id_changes_since`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_regression.py`, replace the end of `test_added_and_removed_rows_and_ticker_ranges_and_id_changes`:

```python
        ("B", "security_history", "added"), ("CIK9-COMMON", "id_changes", "added")]
    assert rows[2]["old"] == "AAA:2008-01-02..2010-01-01:1" and rows[4]["new"] == "BBGX"
```

with:

```python
        ("B", "security_history", "added"), ("BBGX", "id_changes", "renamed")]
    assert rows[2]["old"] == "AAA:2008-01-02..2010-01-01:1"
    assert (rows[4]["field"], rows[4]["old"], rows[4]["new"]) == ("sec_id", "CIK9-COMMON", "BBGX")
```

and insert, just before `def test_excluded_securities_are_left_out():`:

```python
def _rename(old, new):
    return {"old_sec_id": old, "new_sec_id": new, "changed_on": "", "issuer_cik": "9", "share_class": "COMMON"}


def test_a_folded_placeholder_is_one_renamed_row_under_its_figi():
    """N1 (sub-plan 5a): a placeholder a line folded into a FIGI takes its ending and ranges there. Compared under
    the FIGI it holds now, it is one rename, not its own removed row and the FIGI's changed one."""
    base = _snap([contract_row("CIK9-COMMON", exit_kind="merger", last_trade_date="2014-08-28")],
                 [hist("CIK9-COMMON", "9", "2008-01-02", "2012-07-02", ticker="SLE"),
                  hist("BBGF", "9", "2012-07-03", "2014-08-28", ticker="HSH")])
    new = _snap([contract_row("BBGF", exit_kind="merger", last_trade_date="2014-08-28")],
                [hist("BBGF", "9", "2008-01-02", "2012-07-02", ticker="SLE"),
                 hist("BBGF", "9", "2012-07-03", "2014-08-28", ticker="HSH")])
    rows = rg.diff_contract(base, new, renames=[_rename("CIK9-COMMON", "BBGF")])
    assert rows == [{"sec_id": "BBGF", "table": "id_changes", "field": "sec_id", "kind": "renamed",
                     "old": "CIK9-COMMON", "new": "BBGF"}]


def test_a_folded_placeholder_whose_ending_changed_shows_the_change_under_its_figi():
    base = _snap([contract_row("CIK9-COMMON", exit_kind="exchange", successor_sec_id="BBGF")])
    new = _snap([contract_row("BBGF", exit_kind="merger")])
    rows = rg.diff_contract(base, new, renames=[_rename("CIK9-COMMON", "BBGF")])
    assert [(r["sec_id"], r["table"], r["field"], r["kind"]) for r in rows] == [
        ("BBGF", "delistings", "exit_kind", "changed"), ("BBGF", "delistings", "successor_sec_id", "changed"),
        ("BBGF", "id_changes", "sec_id", "renamed")]


def test_the_figis_own_base_row_wins_over_its_folded_placeholders():
    base = _snap([contract_row("CIK9-COMMON", exit_kind="exchange"), contract_row("BBGF", exit_kind="merger")])
    new = _snap([contract_row("BBGF", exit_kind="merger")])
    assert [r["kind"] for r in rg.diff_contract(base, new, renames=[_rename("CIK9-COMMON", "BBGF")])] == ["renamed"]


def test_a_rename_into_an_excluded_security_is_not_reported():
    base = _snap([contract_row("CIK9-COMMON", exit_kind="exchange")])
    new = _snap([contract_row("BBGF", exit_kind="merger")])
    assert rg.diff_contract(base, new, exclude={"BBGF", "CIK9-COMMON"}, renames=[_rename("CIK9-COMMON", "BBGF")]) == []


def test_renamed_to_follows_a_chain_of_renames():
    assert rg.renamed_to([_rename("CIK9-COMMON", "MID"), _rename("MID", "BBGF")]) == {"CIK9-COMMON": "BBGF",
                                                                                     "MID": "BBGF"}


```

In `tests/test_truth_update.py`, change the import `from tests.lifecycle_tables import contract_row` to
`from tests.lifecycle_tables import contract_row, sec`, and replace `_apply` with:

```python
def _apply(cases, records, truth=(), base=None, new=None, keys=frozenset(), **kw):
    return tu.apply_round(cases, records, list(truth), base or {}, new or {}, label="5a", round_no=1,
                          report_dir="loop/5a/round-1/reports", ledger_keys=keys, **kw)
```

Insert, just before `def test_an_old_value_enters_as_known_wrong_for_the_sub_plan():`:

```python
NEW_RIGHT = _record([{"field": "last_trade_date", "right": "new", "value": "2010-10-01", "missed_filing": ""}])


def test_a_regression_of_a_security_the_run_no_longer_holds_adds_no_truth_row():
    """N1 (sub-plan 5a): a truth row under a sec_id the run lacks could only be judged a sec_id mismatch."""
    res = _apply([REG], {"Z_5a-r1": NEW_RIGHT}, base=BASE, new=NEW, run_sec_ids={"Y"})
    assert res.truth_rows == [] and res.changes == []
    assert [(r["key"], r["outcome"]) for r in res.ledger_rows] == [("k-Z_5a-r1-last_trade_date", "new_right")]


def test_a_regression_of_a_renamed_placeholder_adds_no_truth_row():
    res = _apply([REG], {"Z_5a-r1": NEW_RIGHT}, base=BASE, new=NEW, run_sec_ids={"Z"}, renamed={"Z"})
    assert res.truth_rows == [] and [r["outcome"] for r in res.ledger_rows] == ["new_right"]


```

In `_round(tmp_path)`, replace

```python
    store.write_tables(out, {"contract_delistings": [NEW["Z"]]})
```

with (the run under test must hold Z, or the existing dry-run test would now add no truth row):

```python
    store.write_tables(out, {"contract_delistings": [NEW["Z"]], "securities": [sec("Z")]})
```

and append to the file:

```python


def test_script_adds_no_truth_row_for_a_security_the_run_no_longer_holds(tmp_path, capsys):
    rdir, argv = _round(tmp_path)
    repo_out = Path(argv[argv.index("--output-dir") + 1])
    store.write_tables(repo_out, {"securities": [sec("Y")]})
    case = _case("Z_5a-r1", "regression", "Z", ["last_trade_date"], ["2010-09-30"], ["2010-10-01"])
    with (rdir / "cases.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(case), lineterminator="\n")
        w.writeheader()
        w.writerow(case)
    (rdir / "records" / "Z_5a-r1.json").write_text(json.dumps(NEW_RIGHT))
    dt.write_diagnosis_truth(tmp_path / "truth.csv", [])
    assert _script().main(argv) == 0
    assert dl.read_csv(tmp_path / "truth.csv") == []
    assert [r["outcome"] for r in dl.read_ledger(tmp_path / "loop" / "diagnosed.csv")] == ["new_right"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_regression.py tests/test_truth_update.py`
Expected: FAIL (`diff_contract() got an unexpected keyword argument 'renames'`, `apply_round() got an unexpected
keyword argument 'run_sec_ids'`, `no attribute 'renamed_to'`).

- [ ] **Step 3: Implement the regression report's renames**

In `src/delist_detection/regression.py`, replace `CHANGED, ADDED, REMOVED = "changed", "added", "removed"` with
`CHANGED, ADDED, REMOVED, RENAMED = "changed", "added", "removed", "renamed"`. In `build_report`, replace

```python
    return diff_contract(base, new, excluded(cases, base.delistings, new.delistings, id_changes=id_changes))
```

with

```python
    return diff_contract(base, new, excluded(cases, base.delistings, new.delistings, id_changes=id_changes),
                         renames=id_changes)
```

Replace the whole `diff_contract` function with:

```python
def renamed_to(renames: Sequence[Mapping[str, str]]) -> dict[str, str]:
    """Each renamed placeholder's sec_id now (`renames`: id_changes rows), a chain of renames followed to its end
    (P renamed to M, M to F: P is F now)."""
    step = {r["old_sec_id"]: r["new_sec_id"] for r in renames if r.get("old_sec_id") and r.get("new_sec_id")}
    out: dict[str, str] = {}
    for old in step:
        now, seen = step[old], {old}
        while now in step and now not in seen:
            seen.add(now)
            now = step[now]
        out[old] = now
    return out


def _rekeyed(base: Snapshot, moved: Mapping[str, str]) -> Snapshot:
    """`base` with each renamed placeholder's rows under its sec_id now: its contract/delistings.csv row becomes
    that security's when the security had none of its own (its own row wins otherwise; of several placeholders the
    first in sec_id order wins), and its ticker ranges join that security's."""
    rows = {r["sec_id"]: r for r in base.delistings}
    out = [r for r in base.delistings if r["sec_id"] not in moved]
    taken = {r["sec_id"] for r in out}
    for old in sorted(moved):
        r, new_id = rows.get(old), moved[old]
        if r is not None and new_id not in taken:
            out.append({**r, "sec_id": new_id})
            taken.add(new_id)
    history = [{**r, "sec_id": moved.get(r["sec_id"], r["sec_id"])} for r in base.security_history]
    return Snapshot(out, history, base.id_changes)


def diff_contract(base: Snapshot, new: Snapshot, exclude: Collection[str] = (),
                  renames: Sequence[Mapping[str, str]] | None = None) -> list[dict[str, str]]:
    """Every change from `base` to `new` outside `exclude`: delistings rows first (by sec_id, then column), then
    ticker ranges, then the placeholder renames. A renamed placeholder (`renames`, id_changes rows; default the
    run's own contract/id_changes.csv) is compared under the sec_id it holds now (`_rekeyed`), so a placeholder a
    line folded into a FIGI shows as one `renamed` row under that FIGI, plus whatever of the FIGI's own row and
    ranges really changed, never as its own removed row and the FIGI's added one. A rename the base run already
    listed in its own contract/id_changes.csv is not reported again."""
    skip = set(exclude)
    moved = renamed_to(new.id_changes if renames is None else renames)
    base = _rekeyed(base, moved)
    out: list[dict[str, str]] = []
    old_rows = {r["sec_id"]: r for r in base.delistings}
    new_rows = {r["sec_id"]: r for r in new.delistings}
    for sec in sorted((old_rows.keys() | new_rows.keys()) - skip):
        o, n = old_rows.get(sec), new_rows.get(sec)
        if o is None:
            out.append(_row(sec, "delistings", "", ADDED, "", _brief(n)))
        elif n is None:
            out.append(_row(sec, "delistings", "", REMOVED, _brief(o), ""))
        else:
            for col in dict.fromkeys([*o, *n]):
                if col not in SKIPPED_COLUMNS and o.get(col, "") != n.get(col, ""):
                    out.append(_row(sec, "delistings", col, CHANGED, o.get(col, ""), n.get(col, "")))
    old_r, new_r = _ranges(base.security_history), _ranges(new.security_history)
    for sec in sorted((old_r.keys() | new_r.keys()) - skip):
        if old_r.get(sec, "") != new_r.get(sec, ""):
            kind = ADDED if sec not in old_r else REMOVED if sec not in new_r else CHANGED
            out.append(_row(sec, "security_history", "ranges", kind, old_r.get(sec, ""), new_r.get(sec, "")))
    seen = {(r["old_sec_id"], r["new_sec_id"]) for r in base.id_changes}
    for old, now in sorted(moved.items(), key=lambda kv: (kv[1], kv[0])):
        if (old, now) not in seen and old not in skip and now not in skip:
            out.append(_row(now, "id_changes", "sec_id", RENAMED, old, now))
    return out
```

- [ ] **Step 4: Implement the truth update's guard**

In `src/delist_detection/truth_update.py`, in the module docstring, insert before the line
`- A \`pending\` ledger row is never re-diagnosed automatically`:

```
- A regression of a sec_id the run no longer holds, or of a placeholder renamed since the base commit, enters
  only the ledger (sub-plan 5a: a placeholder a line folds into a FIGI is not a truth row of its own).
```

Replace the `apply_round` signature line block

```python
                new_contract: Mapping[str, Mapping[str, str]], *, label: str, round_no: int, report_dir: str,
                ledger_keys: Collection[str] = frozenset()) -> RoundResult:
```

with

```python
                new_contract: Mapping[str, Mapping[str, str]], *, label: str, round_no: int, report_dir: str,
                ledger_keys: Collection[str] = frozenset(), run_sec_ids: Collection[str] | None = None,
                renamed: Collection[str] = ()) -> RoundResult:
    """One round's diagnoses applied (the module docstring's rules). A regression of a security the run no longer
    holds (`run_sec_ids`: the run's securities, None for no check) or of a placeholder renamed since the base
    commit (`renamed`: the old sec_ids) settles its ledger keys and adds no truth row: a truth row under an id
    the run lacks could only ever be judged a `sec_id` mismatch."""
```

and in the regression branch replace

```python
            touching = [f for f in fields if f in SCORED or f in WHOLE_ROW]
            if sec in in_truth or not touching:
                continue
```

with

```python
            touching = [f for f in fields if f in SCORED or f in WHOLE_ROW]
            gone = (run_sec_ids is not None and sec not in run_sec_ids) or sec in renamed
            if sec in in_truth or not touching or gone:
                continue
```

- [ ] **Step 5: Pass the run's securities and renames from the script**

In `scripts/update_truth.py`: replace the docstring line `- the contract at --base and under --output-dir.` with

```
- the contract at --base and under --output-dir, the run's securities and the placeholders renamed since --base
  (a regression of a sec_id the run lacks, or of a renamed placeholder, adds no truth row).
```

Replace the import `from delist_detection.regression import RegressionInputError, read_snapshot, snapshot_at` with
`from delist_detection.regression import RegressionInputError, id_changes_since, read_snapshot, snapshot_at`.
Replace

```python
        base, new = snapshot_at(args.repo, args.base, args.output_dir), read_snapshot(args.output_dir)
        ledger = dl.read_ledger(args.loop_dir / "diagnosed.csv")
```

with

```python
        base, new = snapshot_at(args.repo, args.base, args.output_dir), read_snapshot(args.output_dir)
        renamed = {r["old_sec_id"] for r in id_changes_since(args.repo, args.base, args.output_dir, new.id_changes)}
        ledger = dl.read_ledger(args.loop_dir / "diagnosed.csv")
```

and replace `report_dir=rel_reports, ledger_keys=dl.ledger_keys(ledger))` with

```python
                          report_dir=rel_reports, ledger_keys=dl.ledger_keys(ledger),
                          run_sec_ids={r["sec_id"] for r in tables.securities}, renamed=renamed)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_regression.py tests/test_truth_update.py tests/test_diagnosis_loop.py tests/test_scorecard_script.py`
Expected: PASS. Then the full suite: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass, 281 xfailed.

- [ ] **Step 7: Commit**

```bash
git add src/delist_detection/regression.py src/delist_detection/truth_update.py scripts/update_truth.py tests/test_regression.py tests/test_truth_update.py
git commit -m "Regression report: a folded placeholder is one rename under its FIGI, and adds no truth row of its own (sub-plan 5a, N1)"
```

---

### Task 2: U8, a when-issued ticker joins its regular-way era

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/observations.py`, `src/delist_detection/history.py`
- Test: `tests/test_observations.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces: `observations.regular_way(ticker: str) -> str`. `ObservationIndex` groups observations by
  `regular_way(o.ticker)`; `split_eras` gives each era the regular-way ticker; each `Observation` keeps the
  caller's ticker. `history.ticker_sightings` dates an observation under its era's ticker;
  `history.observation_map_rows` reads status and coverage under the era's ticker (the row's `ticker` column stays
  the caller's).
- Note: this also merges RXO-WI@2022-12-31 into RXO (its truth case is `no_ending`, fixed_by 5h): expect it to
  start matching after Task 13; the loop flips it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_observations.py`:

```python


def test_regular_way_strips_a_when_issued_suffix_and_nothing_else():
    from delist_detection.observations import regular_way
    assert [regular_way(t) for t in ("EHAB-WI", "EHAB WI", "ehab.wi", "EHAB W/I", "AWI", "BF-B", "WI")] == [
        "EHAB", "EHAB", "EHAB", "EHAB", "AWI", "BF-B", "WI"]


def test_a_when_issued_ticker_joins_its_regular_way_era():
    """U8 (sub-plan 5a): Enhabit traded when-issued as EHAB-WI before its 2022 spin-off, then as EHAB. The two are
    one era under EHAB; each observation keeps the ticker the caller saw."""
    index = ObservationIndex([Observation("EHAB-WI", "2022-06-30", "ENHABIT INC WHEN ISSUED"),
                              Observation("EHAB", "2022-12-31", "ENHABIT INC")])
    [era] = index.eras()
    assert (era.key, era.ticker, [o.ticker for o in era.observations]) == (
        "EHAB@2022-06-30", "EHAB", ["EHAB-WI", "EHAB"])
    assert index.name_on("EHAB-WI", "2022-07-01") == "ENHABIT INC WHEN ISSUED"
    assert index.era_for("EHAB", "2022-07-01") is era
```

(`Observation` and `ObservationIndex` are already imported at the top of that file.)

Append to `tests/test_pipeline.py`:

```python


def test_a_when_issued_observation_joins_its_regular_way_security(fake_edgar, tmp_path):
    """U8 (sub-plan 5a): EHAB-WI, seen once before the spin-off, is Enhabit's regular-way line: one security on
    EHAB's FIGI, no placeholder, and the caller's EHAB-WI observation mapped onto it."""
    fake_edgar.company_map["EHAB"] = {"cik_str": 1803737, "ticker": "EHAB", "title": "Enhabit, Inc."}
    fake_edgar.submissions_by_cik[1803737] = []
    fake_edgar.listings[1803737] = [("EHAB", "NYSE")]
    obs = [Observation("EHAB-WI", "2022-06-30", "ENHABIT INC WHEN ISSUED"),
           Observation("EHAB", "2022-12-31", "ENHABIT INC")]
    rows = _ftd("EHAB", "29332G102", "ENHABIT INC", ["2022-07-06", "2022-08-01", "2022-09-01", "2022-12-01"])
    index, clients = _index_clients(fake_edgar, obs, rows, {
        ("ID_CUSIP", "29332G102"): _figi_answer("BBG014QJ5BV6", "EHAB", "ENHABIT INC"),
        ("COMPOSITE_ID_BB_GLOBAL", "BBG014QJ5BV6"): {"data": [{"figi": "BBG014QJ5BV7", "compositeFIGI": "BBG014QJ5BV6",
                                                               "exchCode": "UN", "ticker": "EHAB",
                                                               "name": "ENHABIT INC"}]},
    })
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    assert [r["sec_id"] for r in read_table("securities", table_path(tmp_path, "securities"))] == ["BBG014QJ5BV6"]
    wi = next(r for r in read_table("observation_map", table_path(tmp_path, "observation_map"))
              if r["ticker"] == "EHAB-WI")
    assert (wi["sec_id"], wi["history_ticker"], wi["in_ticker_history"], wi["status"]) == (
        "BBG014QJ5BV6", "EHAB", "true", "mapped")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_observations.py tests/test_pipeline.py -k "when_issued or regular_way"`
Expected: FAIL (`cannot import name 'regular_way'`; the pipeline test finds two securities).

- [ ] **Step 3: Implement**

In `src/delist_detection/observations.py`, after `normalize_ticker`, add:

```python


_WHEN_ISSUED = re.compile(r"-W-?I$")       # "EHAB WI", "EHAB.WI", "EHAB-WI", "EHAB/WI", "EHAB W/I"


def regular_way(ticker: str) -> str:
    """The regular-way line a when-issued ticker trades ahead of: "EHAB-WI" (or "EHAB WI", "EHAB.WI", "EHAB W/I")
    is EHAB, which the shares trade under once they are issued (Enhabit's 2022 spin-off). Any other ticker,
    normalized, is its own."""
    t = normalize_ticker(ticker)
    stripped = _WHEN_ISSUED.sub("", t)
    return stripped or t
```

In the module docstring, replace `1. Here, from observations alone: a new era starts when a pin changes, when the`
with the two lines:

```
1. Here, from observations alone (a when-issued ticker's observations join its
   regular-way ticker's, `regular_way`): a new era starts when a pin changes, when the
```

In `split_eras`, replace `eras.append(TickerEra(o.ticker, o.as_of, o.as_of, [o]))` with
`eras.append(TickerEra(regular_way(o.ticker), o.as_of, o.as_of, [o]))`.

Replace the head of `ObservationIndex`:

```python
class ObservationIndex:
    def __init__(self, observations: Iterable[Observation]) -> None:
        by: dict[str, list[Observation]] = defaultdict(list)
        for o in observations:
            by[o.ticker].append(o)
```

with

```python
class ObservationIndex:
    """The observations by ticker, split into eras (`split_eras`). A when-issued ticker's observations join its
    regular-way ticker's (`regular_way`): they are one security, and the era carries the regular-way ticker while
    each observation keeps the ticker the caller saw."""

    def __init__(self, observations: Iterable[Observation]) -> None:
        by: dict[str, list[Observation]] = defaultdict(list)
        for o in observations:
            by[regular_way(o.ticker)].append(o)
```

and in `era_for`, `name_on` and `cik_pin_on`, replace each `normalize_ticker(ticker)` lookup into `self._eras` or
`self._by` with `regular_way(ticker)` (three places: `self._eras.get(normalize_ticker(ticker), [])` twice and
`self._by.get(normalize_ticker(ticker), [])` once).

In `src/delist_detection/history.py`, `ticker_sightings`: replace the docstring's first sentence

```
    """Dated `(day, ticker, source)` sightings of the security: its observations
    and the FTD rows of its CUSIPs.
```

with

```
    """Dated `(day, ticker, source)` sightings of the security: its observations
    (under their era's ticker: a when-issued observation, EHAB-WI, is a sighting
    of its regular-way ticker, EHAB) and the FTD rows of its CUSIPs.
```

and replace

```python
    out = [Sighting(o.as_of, o.ticker, "observation") for e in sec.eras for o in e.observations]
```

with

```python
    out = [Sighting(o.as_of, e.ticker, "observation") for e in sec.eras for o in e.observations]
```

and `for t in sorted({o.ticker for e in sec.eras for o in e.observations}, key=lambda t: ("-" not in t, t)):` with
`for t in sorted({e.ticker for e in sec.eras}, key=lambda t: ("-" not in t, t)):`.

In `observation_map_rows`, replace

```python
        for o in era.observations:
            status = _observation_status(o.as_of, o.ticker, sec_id, ends.get(sec_id) if sec_id else None,
```

with

```python
        for o in era.observations:
            # Status and coverage are read under the era's ticker (a when-issued observation's regular-way one);
            # the row keeps the ticker the caller observed, its join key.
            status = _observation_status(o.as_of, era.ticker, sec_id, ends.get(sec_id) if sec_id else None,
```

and `"in_ticker_history": _in_ticker_history(o.ticker, o.as_of, ranges),` with
`"in_ticker_history": _in_ticker_history(era.ticker, o.as_of, ranges),`.

(Every era's observations share one normalized ticker today, so for every other ticker `e.ticker == o.ticker`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass, 281 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/observations.py src/delist_detection/history.py tests/test_observations.py tests/test_pipeline.py
git commit -m "A when-issued ticker joins its regular-way era (sub-plan 5a, U8)"
```

---

### Task 3: U2, a CUSIP switch is timed from the old CUSIP's settling tail

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/ftd.py`, `src/delist_detection/security_master.py`
- Test: `tests/test_security_master.py`

**Interfaces:**
- Produces: `ftd.settled_last(rows: Sequence[FtdRow]) -> FtdRow` (the row that opens the last one-price run of
  date-sorted, non-empty rows). `security_master.cusip_handoffs` looks for a switch's new first row in
  [settled − `SWITCH_DAYS`, last + `SWITCH_DAYS`] trading days (it was [last − 5, last + 5]); `Handoff.last` is
  still the last row, and the tail rule still counts from it.
- Also read by `ticker_resolver.infer_issuers`: the KORS/CPRI, NU/ES and LUK/JEF links in
  `tests/test_resolver_renamed.py::test_cusip_handoffs_link_a_shared_cusip_and_a_cusip_switch` and the joins in
  `tests/test_figi_handoff.py` must stay as they are (the suite run in Step 4 checks them).

- [ ] **Step 1: Write the failing tests**

In `tests/test_security_master.py`, add `cusip_handoffs` to the `from delist_detection.security_master import (`
list (keep it sorted: `..., build_securities, cusip_handoffs, era_cusips, era_last_seen, ...`), and append:

```python


def _sle_hsh(settling=True):
    """Sara Lee (SLE, 803111103) renamed Hillshire Brands (HSH, 432589109) in 2012: SLE's last trade 2012-06-28,
    its fails still settling at 18.50 until 2012-07-13; HSH's first row 2012-07-03. With `settling` False, SLE's
    rows after 2012-06-28 carry changing prices: it kept trading beside HSH."""
    tail = [18.50] * 4 if settling else [18.50, 18.61, 18.40, 18.72]
    sle = [("2012-05-01", 20.1), ("2012-05-15", 19.9), ("2012-06-01", 19.2), ("2012-06-15", 18.9),
           ("2012-06-27", 18.78), ("2012-06-28", 18.63),
           *zip(("2012-06-29", "2012-07-02", "2012-07-03", "2012-07-13"), tail)]
    hsh = [("2012-07-03", 29.75), ("2012-07-05", 29.99), ("2012-07-06", 29.73), ("2012-07-09", 29.56),
           ("2012-08-01", 30.10), ("2012-09-04", 31.00)]
    rows = ([FtdRow(d, "803111103", "SLE", "SARA LEE CORP", p) for d, p in sle]
            + [FtdRow(d, "432589109", "HSH", "HILLSHIRE BRANDS CO", p) for d, p in hsh])
    index = ObservationIndex([Observation("SLE", "2012-03-30", "SARA LEE CORP"),
                              Observation("SLE", "2012-06-29", "SARA LEE CORP"),
                              Observation("HSH", "2012-07-31", "HILLSHIRE BRANDS CO"),
                              Observation("HSH", "2012-12-31", "HILLSHIRE BRANDS CO")])
    ftd = FtdIndex.load(_RowsClient(rows), date(2012, 1, 3), date(2013, 1, 31), symbols={"SLE", "HSH"})
    return refine_eras(index.eras(), ftd), ftd


def test_a_switch_is_timed_from_the_old_cusips_last_price_change_not_its_settling_tail():
    """U2 (sub-plan 5a, SLE 2012): HSH's first row is eight trading days before SLE's last fails row, but three
    after the row that opens SLE's one-price settling tail; the switch is timed from that row."""
    eras, ftd = _sle_hsh()
    links = [(h.era_key, h.to_key, h.kind, h.cusip, h.new_cusip, h.day, h.last) for h in cusip_handoffs(eras, ftd)]
    assert links == [("SLE@2012-03-30", "HSH@2012-07-31", "cusip_handoff", "803111103", "432589109", "2012-07-03",
                      "2012-07-13")]


def test_an_old_cusip_still_trading_beside_the_new_one_is_no_switch():
    """Must not change: SLE's rows keep changing price for eight trading days after HSH's first row (two lines
    trading side by side, as a spin-off's), so nothing settles and no switch is read."""
    eras, ftd = _sle_hsh(settling=False)
    assert [h for h in cusip_handoffs(eras, ftd) if h.kind == "cusip_handoff"] == []


def test_settled_last_is_the_row_that_opens_the_last_one_price_run():
    from delist_detection.ftd import settled_last
    rows = [FtdRow(d, "1", "X", "X", p) for d, p in (("2012-06-28", 18.63), ("2012-06-29", 18.5),
                                                     ("2012-07-02", 18.5), ("2012-07-13", 18.5))]
    assert settled_last(rows).date == "2012-06-29" and settled_last(rows[:1]).date == "2012-06-28"
    assert settled_last(rows[:2]).date == "2012-06-29"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py -k "switch or settled"`
Expected: FAIL (`cannot import name 'settled_last'`; the SLE link is missing).

- [ ] **Step 3: Implement**

In `src/delist_detection/ftd.py`, change `from collections.abc import Iterable, Iterator, Mapping` to
`from collections.abc import Iterable, Iterator, Mapping, Sequence`, and insert after `is_deleted_symbol`:

```python


def settled_last(rows: Sequence[FtdRow]) -> FtdRow:
    """The row that opens the last run of one price in the date-sorted, non-empty `rows`: fails still settling
    after a security's last trade repeat its last close, so its last trade lies near that row, not the last one
    (Sara Lee's 803111103 fails at 18.50 from 2012-06-29 to 2012-07-13, after its last trade on 2012-06-28)."""
    i = len(rows) - 1
    while i > 0 and rows[i - 1].price == rows[-1].price:
        i -= 1
    return rows[i]
```

In `src/delist_detection/security_master.py`, change the ftd import to
`from .ftd import FTD_START, FtdIndex, FtdRow, is_deleted_symbol, settled_last`. In `cusip_handoffs`' docstring
replace

```
    - switch: an era's FTD CUSIP last trades under its ticker (not under a
      deleted "...XXXX" symbol) within `SWITCH_DAYS` trading days of the first
      fails row of another era's FTD CUSIP;
```

with

```
    - switch: an era's FTD CUSIP last trades under its ticker (not under a
      deleted "...XXXX" symbol) within `SWITCH_DAYS` trading days of the first
      fails row of another era's FTD CUSIP (from `SWITCH_DAYS` before the row
      that opens the old CUSIP's last one-price run, `ftd.settled_last`, to
      `SWITCH_DAYS` after its last row);
```

and in its body replace

```python
            lo = add_trading_days(last, -SWITCH_DAYS).isoformat()
            hi = add_trading_days(last, SWITCH_DAYS).isoformat()
```

with

```python
            # From the row that opens the old CUSIP's last one-price run: a fail still settling at the last close
            # can outlast the switch by days (SLE's rows run to 2012-07-13; HSH's begin 2012-07-03).
            lo = add_trading_days(date.fromisoformat(settled_last(own).date), -SWITCH_DAYS).isoformat()
            hi = add_trading_days(last, SWITCH_DAYS).isoformat()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass (including tests/test_resolver_renamed.py and tests/test_figi_handoff.py), 281 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/ftd.py src/delist_detection/security_master.py tests/test_security_master.py
git commit -m "A CUSIP switch is timed from the old CUSIP's settling tail (sub-plan 5a, U2: SLE to HSH)"
```

---

### Task 4: U3, a shared CUSIP reaches a sibling the ticker tier picked

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/security_master.py`
- Test: `tests/test_security_master.py`

**Interfaces:**
- Produces: `_handoff_joins(eras, issuers, handoffs, unpicked, confirmed, picked=None)`: a `shared_cusip` link also
  reaches an era in `picked` (era key → composite: the ticker and name picks that are not weak). `resolve_many`
  passes those picks. `_contradicted` still applies to every join.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_security_master.py`:

```python


def _spw_spxc(spxc_name="SPX CORP"):
    """SPX's one CUSIP 784635104 under SPW (2008-2015) and SPXC (from 2015-09-29). OpenFIGI knows the CUSIP on no
    US venue; SPXC's ticker gives BBG000BTGCV5."""
    spw = _era("SPW", ("2008-01-16", "SPX CORP"), ("2015-06-30", "SPX CORP"))
    spxc = _era("SPXC", ("2015-12-31", spxc_name))
    figi = _Figi({("TICKER", "SPXC"): {"data": [_row("BBG000BTGCV5", "US", "SPXC", "SPX CORP")]}})
    handoffs = [Handoff(spw.key, spxc.key, "shared_cusip", "784635104"),
                Handoff(spxc.key, spw.key, "shared_cusip", "784635104")]
    return spw, spxc, figi, handoffs


def test_a_shared_cusip_reaches_a_sibling_the_ticker_tier_picked_on_its_own_name():
    """U3 (sub-plan 5a, SPW 2015): SPW shares its CUSIP with SPXC, an era of its issuer and class the ticker tier
    picked on its observed name. One CUSIP under two tickers of one issuer is one line: SPW joins that composite
    instead of keeping a placeholder beside it."""
    spw, spxc, figi, handoffs = _spw_spxc()
    res = FigiResolver(figi).resolve_many([spw, spxc], issuers=issuers_by_era({spw.key: 88205, spxc.key: 88205}),
                                          cusips={spw.key: ["784635104"], spxc.key: ["784635104"]},
                                          handoffs=handoffs)
    assert (res[spxc.key].sec_id, res[spxc.key].source) == ("BBG000BTGCV5", "ticker")
    assert (res[spw.key].sec_id, res[spw.key].source) == ("BBG000BTGCV5", "handoff")


def test_a_shared_cusip_does_not_carry_a_class_onto_another_classes_ticker_pick():
    """Must not change: the reach still needs one issuer and one class (two classes of one issuer, MSG A and B)."""
    a = _era("AA", ("2012-06-29", "SPLIT CO CLASS A"))
    b = _era("BB", ("2015-06-30", "SPLIT CO CLASS B"))
    figi = _Figi({("TICKER", "BB"): {"data": [_row("BBGCLASSB01", "US", "BB", "SPLIT CO CLASS B")]}})
    handoffs = [Handoff(a.key, b.key, "shared_cusip", "SHAREDXCLASS")]
    res = FigiResolver(figi).resolve_many([a, b], issuers=issuers_by_era({a.key: 4, b.key: 4}),
                                          cusips={a.key: [], b.key: []}, handoffs=handoffs)
    assert (res[b.key].sec_id, res[b.key].source) == ("BBGCLASSB01", "ticker")
    assert res[a.key].sec_id == "CIK4-CLASS-A"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py -k shared_cusip`
Expected: the first test FAILS (SPW stays on `CIK88205-COMMON`); the second passes.

- [ ] **Step 3: Implement**

In `src/delist_detection/security_master.py`, replace the head of `_handoff_joins`:

```python
def _handoff_joins(eras: Sequence[TickerEra], issuers: Mapping[str, Issuer], handoffs: Sequence[Handoff],
                   unpicked: Collection[str], confirmed: Mapping[str, str]) -> dict[str, tuple[str, str, Handoff]]:
```

with

```python
def _handoff_joins(eras: Sequence[TickerEra], issuers: Mapping[str, Issuer], handoffs: Sequence[Handoff],
                   unpicked: Collection[str], confirmed: Mapping[str, str],
                   picked: Mapping[str, str] | None = None) -> dict[str, tuple[str, str, Handoff]]:
```

and, at the end of its docstring (after `one (two composites: none).`), add before the closing quotes:

```
    A shared CUSIP also reaches an era the ticker
    or name tier picked on its own observed name (`picked`: era key ->
    composite, the picks guard (c) cannot withdraw): one CUSIP under two
    tickers of one issuer is one line, so SPW (2008-2015) joins the composite
    SPXC's ticker gives, with OpenFIGI knowing that CUSIP on no US venue.
```

Replace

```python
    reach: dict[str, dict[str, tuple[str, Handoff]]] = defaultdict(dict)
    for h in links:
        if h.era_key in chain and h.to_key in confirmed:
            reach[root(h.era_key)].setdefault(confirmed[h.to_key], (h.to_key, h))
```

with

```python
    picked = picked or {}
    reach: dict[str, dict[str, tuple[str, Handoff]]] = defaultdict(dict)
    for h in links:
        if h.era_key not in chain:
            continue
        if h.to_key in confirmed:
            reach[root(h.era_key)].setdefault(confirmed[h.to_key], (h.to_key, h))
        elif h.kind == "shared_cusip" and h.to_key in picked:
            reach[root(h.era_key)].setdefault(picked[h.to_key], (h.to_key, h))
```

In `FigiResolver.resolve_many`, replace

```python
        for key, (composite, anchor, h) in _handoff_joins(eras, issuers, handoffs, unpicked, confirmed).items():
```

with

```python
        strong = {k: p[1] for k, p in picks.items() if p[0] in ("ticker", "name") and not p[3]}
        for key, (composite, anchor, h) in _handoff_joins(eras, issuers, handoffs, unpicked, confirmed,
                                                          strong).items():
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass, 281 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/security_master.py tests/test_security_master.py
git commit -m "A shared CUSIP reaches a sibling the ticker tier picked on its own name (sub-plan 5a, U3: SPW)"
```

---

### Task 5: U4 (conditional), a row confirms a ticker only when it can name the issuer

Tier: standard (a measurement decides whether the code stays).

**Files:**
- Modify: `src/delist_detection/security_master.py`, `src/delist_detection/pipeline.py`
- Test: `tests/test_security_master.py`
- Create (not committed): `$TMPDIR/u4_measure.py`
- If dropped: modify `data/diagnosis_truth.csv`, `data/diagnosis_truth_changes.csv`, the roadmap

**Interfaces:**
- Produces, if kept: `unconfirmed_eras(eras, ftd, issuers=None)` and `guarded_eras(eras, ftd, issuers=None)`;
  `pipeline._resolve_securities` passes `issuers`. If dropped: no code change survives.

**The decision rule (operator, 2026-10-03):** implement U4, then measure on the committed run, offline, how many
eras `guarded_eras` holds differently with the stricter rule. **If more than 10 eras other than UAG@2008-01-16
change, drop U4 (revert its code and test) and record that UAG moves to 5h; otherwise keep it.** A pre-measurement
while planning gave 13 other eras, so expect the drop branch.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_security_master.py`:

```python


def _uag():
    """United Auto Group, seen as UAG in 2008-2009 while it traded as PAG (70959W103, BBG000H6K1B0); the fails rows
    under UAG then are UBS's E-TRACS ETN's."""
    uag = _era("UAG", ("2008-01-16", "UNITED AUTO GROUP INC"), ("2009-06-08", "UNITED AUTO GROUP INC"))
    pag = _era("PAG", ("2008-01-16", "PENSKE AUTOMOTIVE GROUP INC"), ("2009-06-08", "PENSKE AUTOMOTIVE GROUP INC"))
    rows = [FtdRow(d, "902641760", "UAG", "UBS AG JERSEY BRH E-TRACS UBS", 20.0)
            for d in ("2008-09-02", "2008-12-01", "2009-03-02", "2009-06-01")]
    rows += [FtdRow(d, "70959W103", "PAG", "PENSKE AUTOMOTIVE GROUP INC", 15.0)
             for d in ("2008-01-02", "2008-06-02", "2009-01-02", "2009-06-01")]
    names = ("Penske Automotive Group, Inc.", "UNITED AUTO GROUP INC")
    return uag, pag, FtdIndex(rows), {uag.key: Issuer(1019849, names), pag.key: Issuer(1019849, names)}


def test_a_ticker_another_securitys_rows_fill_confirms_nothing_once_the_issuer_is_known():
    """U4 (sub-plan 5a, UAG 2009): the E-TRACS rows under UAG name no name of United Auto Group's, so the era is
    unconfirmed and is placed on the line its issuer and class traded on then."""
    from delist_detection.security_master import guarded_eras
    uag, pag, ftd, issuers = _uag()
    assert guarded_eras([uag, pag], ftd) == set()
    assert guarded_eras([uag, pag], ftd, issuers) == {uag.key}
    figi = _Figi({("ID_CUSIP", "70959W103"): {"data": [_row("BBG000H6K1B0", "US", "PAG", "PENSKE AUTOMOTIVE GROUP")]}})
    res = FigiResolver(figi).resolve_many([uag, pag], issuers=issuers, cusips={uag.key: [], pag.key: ["70959W103"]},
                                          unconfirmed=guarded_eras([uag, pag], ftd, issuers))
    assert (res[uag.key].sec_id, res[uag.key].source) == ("BBG000H6K1B0", "backfill")
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_security_master.py -k another_securitys_rows`
Expected: FAIL (`guarded_eras() takes 2 positional arguments but 3 were given`).

- [ ] **Step 2: Implement**

In `src/delist_detection/security_master.py`, replace `unconfirmed_eras` and `guarded_eras` with:

```python
def unconfirmed_eras(eras: Sequence[TickerEra], ftd: FtdIndex,
                     issuers: Mapping[str, Issuer] | None = None) -> set[str]:
    """The keys of the eras from 2004 on (the start of SEC fails-to-deliver data)
    with no FTD row under their ticker within `TICKER_CONFIRM_DAYS` of their
    first and last observation: the SEC data never shows that ticker then, as
    when a snapshot carries a ticker adopted later (APTV in 2012-2013, when
    Delphi traded as DLPH). With `issuers` (by era key), a row confirms the
    ticker only when its description can name the era's issuer
    (`names.description_matches` against the era's observed names and its
    issuer's EDGAR names): another security's rows under the ticker confirm
    nothing (UAG in 2008-2009: UBS's E-TRACS rows, while United Auto Group
    traded as PAG)."""
    out: set[str] = set()
    for e in eras:
        if date.fromisoformat(e.last) < FTD_START:
            continue
        rows = ftd.by_symbol(e.ticker, *_confirm_window(e))
        if issuers is not None:
            known = [*e.names, *(issuers[e.key].names if e.key in issuers else ())]
            if known:
                rows = [r for r in rows if description_matches(r.description, known)]
        if not rows:
            out.add(e.key)
    return out


def guarded_eras(eras: Sequence[TickerEra], ftd: FtdIndex,
                 issuers: Mapping[str, Issuer] | None = None) -> set[str]:
    """The `unconfirmed_eras` (by `issuers` too, when given) whose window the
    loaded fails data covers (some row of another symbol falls in it): the data
    shows the ticker was not failing then, rather than having nothing to say.
    Their ticker and name tiers are not asked (`FigiResolver.resolve_many`'s
    `unconfirmed`)."""
    by_key = eras_by_key(eras)
    return {k for k in unconfirmed_eras(eras, ftd, issuers) if ftd.has_rows(*_confirm_window(by_key[k]))}
```

In `src/delist_detection/pipeline.py`, `_resolve_securities`, replace `unconfirmed=guarded_eras(eras, ftd))` with
`unconfirmed=guarded_eras(eras, ftd, issuers))`.

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass, 281 xfailed.

- [ ] **Step 3: Measure**

Write `$TMPDIR/u4_measure.py`:

```python
"""Sub-plan 5a, U4's blast, measured offline over the committed run: the eras `guarded_eras` holds differently when
a fails row confirms an era's ticker only if its description can name the era's issuer (`issuers`). Reads
output/observation_map.csv (the refined eras and their issuer CIKs), output/run_manifest.json (the run date), the
cached fails zips and the cached EDGAR submissions (every SEC request refused). Prints one line per era that
changes, then one JSON line.

  PYTHONPATH=src python $TMPDIR/u4_measure.py
"""
import csv
import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

REPO = Path.cwd()
import delist_detection.edgar as edgar_mod  # noqa: E402

edgar_mod.sec_get = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))
from delist_detection.edgar import EdgarClient  # noqa: E402
from delist_detection.evidence import edgar_names  # noqa: E402
from delist_detection.ftd import FTD_START, FtdIndex, parse_ftd_lines, period_of  # noqa: E402
from delist_detection.observations import Observation, ObservationIndex  # noqa: E402
from delist_detection.security_master import guarded_eras, issuers_by_era, refine_eras  # noqa: E402


class LocalFtd:
    def __init__(self, folder):
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


with (REPO / "output/observation_map.csv").open(newline="") as fh:
    rows = list(csv.DictReader(fh))
obs = [Observation(r["ticker"], r["as_of"], r["name"] or None, r["cusip"] or None,
                   int(r["pin_cik"]) if r["pin_cik"] else None, r["pin_sec_id"] or None) for r in rows]
eras = ObservationIndex(obs).eras()
as_of = date.fromisoformat(json.loads((REPO / "output/run_manifest.json").read_text())["as_of"])
lo = max(FTD_START, min(date.fromisoformat(e.first) for e in eras) - timedelta(days=30))
hi = min(as_of, max(date.fromisoformat(e.last) for e in eras) + timedelta(days=400))
ftd = FtdIndex.load(LocalFtd(REPO / "cache/sec_data/ftd"), lo, hi, symbols={e.ticker for e in eras},
                    cusips={c for e in eras for c in e.cusips})
eras = refine_eras(eras, ftd)
ciks = {r["era"]: int(r["issuer_cik"]) for r in rows if r["issuer_cik"]}
edgar = EdgarClient(REPO / "cache/edgar", user_agent="u4 measure u4@example.com", today=as_of)
names = {}
for cik in set(ciks.values()):
    try:
        names[cik] = edgar_names(edgar.submissions(cik))
    except Exception:          # noqa: BLE001 -- not cached: no EDGAR names, as a failed read in the run
        names[cik] = ()
issuers = issuers_by_era({e.key: ciks.get(e.key) for e in eras}, names)
before, after = guarded_eras(eras, ftd), guarded_eras(eras, ftd, issuers)
changed = sorted(before ^ after)
for k in changed:
    print(("now guarded " if k in after else "no longer guarded ") + k)
others = [k for k in changed if not k.startswith("UAG@")]
print(json.dumps({"eras": len(eras), "guarded_before": len(before), "guarded_after": len(after),
                  "changed": len(changed), "changed_other_than_uag": len(others), "keep_u4": len(others) <= 10}))
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/u4_measure.py`
Expected: about a minute; the last line is JSON. The planning pre-measurement printed
`"changed_other_than_uag": 13, "keep_u4": false`.

- [ ] **Step 4a: If `keep_u4` is true, commit U4**

```bash
git add src/delist_detection/security_master.py src/delist_detection/pipeline.py tests/test_security_master.py
git commit -m "A fails row confirms an era's ticker only when it can name the issuer (sub-plan 5a, U4: UAG; N other eras change)"
```

(Write the measured count in place of N.) Skip Step 4b.

- [ ] **Step 4b: If `keep_u4` is false, drop U4 and record UAG for 5h**

Revert the code and the test: `git checkout -- src/delist_detection/security_master.py src/delist_detection/pipeline.py tests/test_security_master.py`
(nothing else is uncommitted at this point). Then move UAG's truth case to 5h with a change-log row, writing both
files together:

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -c "
from delist_detection import diagnosis_loop as dl
from delist_detection.diagnosis_truth import COLUMNS
rows = dl.read_csv('data/diagnosis_truth.csv')
case = 'CIK1019849-COMMON_2009-06-08'
[r] = [r for r in rows if r['case_id'] == case]
assert r['fixed_by'] == '5a', r['fixed_by']
r['fixed_by'] = '5h'
change = dict(case_id=case, field='fixed_by', old='5a', new='5h', report='',
              reason='sub-plan 5a dropped U4: the stricter ticker confirmation changed N other eras (more than 10)')
dl.write_together([('data/diagnosis_truth.csv', COLUMNS, rows),
                   ('data/diagnosis_truth_changes.csv', dl.CHANGE_COLUMNS,
                    dl.read_csv('data/diagnosis_truth_changes.csv') + [change])])
print('UAG moved to 5h')
"
```

(Write the measured count in place of N in the reason.) In the roadmap
(`docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md`), add to the list of carried items, after the line
`- a prepared \`casesPath\` must sit at \`loop/<label>/round-<N>/cases.csv\`.`:

```
- for 5h: UAG 2009 (CIK1019849-COMMON, United Auto Group seen as UAG while it traded as PAG). 5a's U4 (a fails row
  confirms a ticker only when its description can name the issuer) would place it on PAG's line, but it changed N
  other eras' guard (more than 10), so 5a dropped it.
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass, 281 xfailed (UAG's case is still known_wrong; its `fixed_by` changed only).

```bash
git add data/diagnosis_truth.csv data/diagnosis_truth_changes.csv docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md
git commit -m "Sub-plan 5a drops U4 (N other eras' ticker guard changed); UAG moves to 5h"
```

---

### Task 6: U5, a security's own tickers include its line's; a first-day ZZZZ row is no ticker

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/security_master.py`, `src/delist_detection/history.py`, `src/delist_detection/ftd.py`,
  `src/delist_detection/delistings.py`, `src/delist_detection/pipeline.py`
- Test: `tests/test_history.py`, `tests/test_security_master.py`, `tests/test_pipeline.py`, `tests/test_delistings.py`

**Interfaces:**
- Produces:
  - `Security.line_tickers: frozenset[str] = frozenset()` (set by stage 4b, Task 10) and
    `Security.own_tickers() -> set[str]` (era tickers ∪ line tickers).
  - `ftd.is_unassigned_symbol(symbol: str) -> bool` (`…ZZZZ`).
  - Every "own tickers" site reads `own_tickers()`: `history.own_last_seen`, `superseded_placeholders`,
    `pipeline._warm_delisting_search`/`_find_delistings` (listed_today's tickers), `_context_builder`
    (`ftd_seen_after`), `_dead_before_sighting`, `_find_successors` (the 8-K12B search's `own_tickers`),
    `_continues_after`, and `DelistingFinder.find`'s review ticker (the line's latest own ticker when it has line
    tickers).
  - `history.ticker_sightings` drops `…ZZZZ` rows (they stay cusip sightings).
- With no line tickers anywhere yet, every output is unchanged except the 12 `XXXZZZZ` one-day ticker ranges,
  which are not in any test.

- [ ] **Step 1: Write the failing tests**

In `tests/test_history.py`, replace the imports

```python
from delist_detection.history import (Sighting, filtered_ticker_sightings, is_backfilled, observation_map_rows,
                                      ticker_on)
from delist_detection.observations import Observation, TickerEra
```

with

```python
from delist_detection.history import (Sighting, cusip_sightings, filtered_ticker_sightings, is_backfilled,
                                      observation_map_rows, own_last_seen, ticker_on, ticker_sightings)
from delist_detection.observations import Observation, TickerEra
from delist_detection.security_master import Security
```

and append:

```python


# --- sub-plan 5a, U5: a security's own tickers include its line's (Security.line_tickers) ---

def _hsc(line_tickers=frozenset()):
    era = TickerEra("HSC", "2008-01-16", "2023-06-20", [Observation("HSC", "2008-01-16", "HARSCO CORP")])
    return Security("BBG000BLH3P8", 45876, "COMMON", "HARSCO CORP", "Common Stock", True, "cusip", eras=[era],
                    line_tickers=frozenset(line_tickers))


def test_own_tickers_are_the_eras_and_the_lines():
    assert _hsc().own_tickers() == {"HSC"} and _hsc({"NVRI"}).own_tickers() == {"HSC", "NVRI"}


def test_own_last_seen_counts_a_ticker_the_line_follow_found():
    """Harsco renamed itself Enviri (NVRI) in 2023 on the same CUSIP: once the line follow adds NVRI, the
    security's last own sighting is its last NVRI row, not its last HSC one."""
    sig = [Sighting("2023-06-20", "HSC", "ftd"), Sighting("2024-01-02", "NVRI", "ftd")]
    assert own_last_seen(_hsc(), sig) == "2023-06-20"
    assert own_last_seen(_hsc({"NVRI"}), sig) == "2024-01-02"


def test_a_first_day_zzzz_row_is_no_ticker_sighting_but_still_a_cusip_sighting():
    """A new CUSIP's first fails row carries the ticker with ZZZZ appended (FMDZZZZ): no ticker range opens under
    it, while the CUSIP's own range starts that day."""
    era = TickerEra("FMD", "2008-01-16", "2008-01-16", [Observation("FMD", "2008-01-16", "FIRST MARBLEHEAD")])
    sec = Security("BBG000BN6349", 1262279, "COMMON", "FIRST MARBLEHEAD", "Common Stock", True, "cusip", eras=[era])
    ftd = FtdIndex([FtdRow("2013-12-03", "320771207", "FMDZZZZ", "FIRST MARBLEHEAD CORP", 0.01),
                    FtdRow("2013-12-04", "320771207", "FMD", "FIRST MARBLEHEAD CORP", 5.41),
                    FtdRow("2013-12-05", "320771207", "FMD", "FIRST MARBLEHEAD CORP", 5.50)])
    assert {s.value for s in ticker_sightings(sec, ftd, ["320771207"]) if s.source == "ftd"} == {"FMD"}
    assert cusip_sightings(sec, ftd, ["320771207"])[0] == Sighting("2013-12-03", "320771207", "ftd")
```

Append to `tests/test_security_master.py`:

```python


def test_a_placeholder_whose_line_ticker_a_later_figi_line_holds_is_superseded():
    """U5 (sub-plan 5a): Aon's placeholder traded as AOC, then (the line follow found) as AON; Aon plc's later FIGI
    line of the same issuer and class holds AON. The placeholder is not the line listed today."""
    from delist_detection.security_master import superseded_placeholders
    aoc = _era("AOC", ("2008-01-16", "AON CORP"), ("2009-06-08", "AON CORP"))
    aon = _era("AON", ("2012-06-29", "AON PLC"))
    p = Security("CIK315293-COMMON", 315293, "COMMON", "AON CORP", "", True, "placeholder", eras=[aoc],
                 line_tickers=frozenset({"AON"}))
    s = Security("BBG00AONPLC1", 315293, "COMMON", "AON PLC", "Common Stock", True, "cusip", eras=[aon])
    assert superseded_placeholders({p.sec_id: p, s.sec_id: s}) == {"CIK315293-COMMON"}
    p.line_tickers = frozenset()
    assert superseded_placeholders({p.sec_id: p, s.sec_id: s}) == set()
```

Append to `tests/test_pipeline.py`:

```python


def test_a_merger_whose_cusip_goes_on_under_a_line_ticker_does_not_end_the_security():
    """U5 (sub-plan 5a): the continues-after rule counts the tickers the line follow added: TEST's own CUSIP keeps
    trading as TSTN (a rename the line follow found), so the merger record is no real exit."""
    from delist_detection.ftd import FtdIndex
    from delist_detection.observations import TickerEra
    era = TickerEra("TEST", "2007-12-01", "2019-03-29", [Observation("TEST", "2007-12-01", "TEST CO")])
    sec = Security("BBGTEST", 5, "COMMON", "TEST CO", "Common Stock", True, "cusip", eras=[era])
    record = DelistRecord(ticker="TEST", cik=5, observed_delist_date="2019-03-30", crsp_code=231,
                          bucket=CrspBucket.MERGER, confidence="high", reason="x", evidence={"flags": []},
                          sec_id="BBGTEST", delist_date="2019-03-30")
    d = Delisting("BBGTEST", 5, "TEST", "2019-03-30", record, LastTrade(date(2019, 3, 29), "ex99_notice", ()),
                  None, None, "NYSE")
    ftd = FtdIndex(_continuing_fails("TSTN", "11111T101"))
    assert pipeline._ends_the_security(d, sec, {"BBGTEST": ["11111T101"]}, ftd) is True
    sec.line_tickers = frozenset({"TSTN"})
    assert pipeline._ends_the_security(d, sec, {"BBGTEST": ["11111T101"]}, ftd) is False
```

In `tests/test_delistings.py`, add `from dataclasses import replace` as the first import, and append:

```python


def test_a_line_the_line_follow_moved_to_a_new_ticker_is_reviewed_under_it(fake_edgar):
    """U5 (sub-plan 5a): with no Form 25 and no fallback filing, a line that went on as NVRI is reviewed under
    its latest own ticker, NVRI, not its last era's."""
    fake_edgar.submissions_by_cik[45876] = []
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG000BLH3P8", 45876, "HSC", "2008-01-16", "2023-06-20", "HARSCO CORP")
    sec.line_tickers = frozenset({"NVRI"})
    ctx = replace(_ctx(sec, last_seen="2026-05-29"), ticker_on=lambda d: "NVRI" if d >= "2023-06-21" else "HSC")
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert events == [] and [(r.flag, r.ticker) for r in review] == [("ended_without_delisting", "NVRI")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_history.py tests/test_security_master.py tests/test_pipeline.py tests/test_delistings.py -k "own_tickers or line_follow or zzzz or superseded or line_ticker or reviewed_under"`
Expected: FAIL (`Security.__init__() got an unexpected keyword argument 'line_tickers'`).

- [ ] **Step 3: Implement**

In `src/delist_detection/security_master.py`, in `class Security`, after `eras: list[TickerEra] = field(default_factory=list)`, add:

```python
    # The tickers the line follow (pipeline stage 4b, `line_follow`) found the security trading under after its
    # observations stopped (HSC's NVRI, Senior Housing's DHC).
    line_tickers: frozenset[str] = frozenset()

    def own_tickers(self) -> set[str]:
        """Every ticker the security is known to have traded under: its eras' and its line's."""
        return {e.ticker for e in self.eras} | set(self.line_tickers)
```

In `superseded_placeholders`, replace

```python
        tickers, last = {e.ticker for e in p.eras}, max(e.last for e in p.eras)
        for s in securities.values():
            if (not is_placeholder(s.sec_id) and s.eras and s.issuer_cik == p.issuer_cik
                    and s.share_class == p.share_class and tickers & {e.ticker for e in s.eras}
```

with

```python
        tickers, last = p.own_tickers(), max(e.last for e in p.eras)
        for s in securities.values():
            if (not is_placeholder(s.sec_id) and s.eras and s.issuer_cik == p.issuer_cik
                    and s.share_class == p.share_class and tickers & s.own_tickers()
```

In `src/delist_detection/ftd.py`, insert after `is_deleted_symbol`:

```python


def is_unassigned_symbol(symbol: str) -> bool:
    """A new CUSIP's first fails rows, before the exchange assigns it a symbol, carry the ticker with "ZZZZ"
    appended (FMDZZZZ, JNYZZZZ, NYCBZZZZ), often at $0.01 or $1.00. Like a deleted "...XXXX" symbol, it is no
    ticker the security traded under."""
    return len(symbol or "") > 4 and symbol.endswith("ZZZZ")
```

In `src/delist_detection/history.py`, change the import to
`from .ftd import FtdIndex, is_deleted_symbol, is_unassigned_symbol`; in `ticker_sightings` replace

```python
    # SEC's 2007 fails files mask some symbols (**********): not a ticker
    out += [Sighting(r.date, r.symbol, "ftd") for r in ftd.trading_rows(cusips)
            if any(ch.isalpha() for ch in r.symbol)]
```

with

```python
    # SEC's 2007 fails files mask some symbols (**********), and a new CUSIP's first rows carry the ticker with
    # "ZZZZ" appended (FMDZZZZ): neither is a ticker
    out += [Sighting(r.date, r.symbol, "ftd") for r in ftd.trading_rows(cusips)
            if any(ch.isalpha() for ch in r.symbol) and not is_unassigned_symbol(r.symbol)]
```

and in `own_last_seen` replace

```python
    """The latest sighting under one of the security's own era tickers, else
    the latest era end date.
```

with

```python
    """The latest sighting under one of the security's own tickers (its eras'
    and its line's, `Security.own_tickers`), else the latest era end date.
```

and `own = {e.ticker for e in sec.eras}` with `own = sec.own_tickers()`.

In `src/delist_detection/pipeline.py` make these six replacements:

1. In `_warm_delisting_search`: `tickers=sorted({e.ticker for e in s.eras}), answer=answer)` →
   `tickers=sorted(s.own_tickers()), answer=answer)`.
2. In `_context_builder`: `ftd_seen_after=lambda day, sig=sig, own={e.ticker for e in s.eras}: any(` →
   `ftd_seen_after=lambda day, sig=sig, own=s.own_tickers(): any(`.
3. In `_find_delistings`: `tickers=sorted({e.ticker for e in s.eras}), answer=listing.get(s.sec_id))` →
   `tickers=sorted(s.own_tickers()), answer=listing.get(s.sec_id))`.
4. In `_dead_before_sighting`: `tickers = sorted({era.ticker for era in s.eras})` → `tickers = sorted(s.own_tickers())`.
5. In `_find_successors`: `own_tickers={x.ticker for x in predecessor.eras} | {e.ticker})` →
   `own_tickers=predecessor.own_tickers() | {e.ticker})`.
6. In `_continues_after`: `own = {e.ticker for e in s.eras}` → `own = s.own_tickers()`.

In `src/delist_detection/delistings.py`, `DelistingFinder.find`, replace

```python
        cik = sec.issuer_cik
        ticker_last = sec.eras[-1].ticker
        if cik is None:
```

with

```python
        cik = sec.issuer_cik
        ticker_last = sec.eras[-1].ticker
        if sec.line_tickers:            # the line went on under a ticker the line follow found: its latest one
            latest = ctx.ticker_on(ctx.last_seen)
            ticker_last = latest if latest in sec.own_tickers() else ticker_last
        if cik is None:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass, 281 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/security_master.py src/delist_detection/history.py src/delist_detection/ftd.py src/delist_detection/delistings.py src/delist_detection/pipeline.py tests/test_history.py tests/test_security_master.py tests/test_pipeline.py tests/test_delistings.py
git commit -m "A security's own tickers include its line's; a first-day ZZZZ row is no ticker sighting (sub-plan 5a, U5)"
```

---

### Task 7: The line follow, a pure module

Tier: cheap (the module and its tests are complete below).

**Files:**
- Create: `src/delist_detection/line_follow.py`
- Test: `tests/test_line_follow.py`

**Interfaces:**
- Consumes: `ftd.settled_last`, `ftd.is_unassigned_symbol` (Tasks 3, 6), `Security` (Task 6),
  `security_master.SWITCH_TAIL_DAYS`, `successors.successor_query`, `listing_status.edgar_lists`,
  `names.description_names`/`names_agree`, `evidence.names_between`/`name_at`, `figi_resolution`.
- Produces (every later task uses these exact names):
  - Constants `SWITCH = "cusip_switch"`, `NEW_SYMBOL = "new_symbol"`, `ATTACH`, `FOLD`, `SUCCESSOR`, `REFUSED`,
    `LINE_DAYS = 10`, `MIN_NEW_ROWS = 3`, `FILING_DAYS = 30`, `RENAME_DAYS = 90`, `BANKRUPTCY_BEFORE_DAYS = 180`,
    `BANKRUPTCY_AFTER_DAYS = 30`, `NAME_DAYS = 30`, `RECENT_DAYS = 120`, `MAX_ROUNDS = 3`, `MAX_TEXTS = 5`,
    `PERIODIC_FORMS`, `SUCCESSOR_FORMS`.
  - `@dataclass(frozen=True) LineStep(sec_id, kind, old_cusip, new_cusip, symbol, old_last, first, descriptions=())`.
  - `@dataclass(frozen=True) LineEnd(cusip, last, settled)`; `line_end(cusips, tickers, ftd) -> LineEnd | None`.
  - `@dataclass(frozen=True) LineSuccessor(sec_id, composite, candidate: FigiCandidate, step: LineStep, evidence)`.
  - `@dataclass(frozen=True) Decision(kind, composite="", why="", candidate=None)`.
  - `candidate_steps(sec_id, cusips, tickers, ftd, *, holders: Mapping[str, Collection[str]] = {},
    extra_symbols=(), extra_cusips=(), days=LINE_DAYS) -> list[LineStep]`.
  - `corroborate(step, *, filings, sub, share_class, text_of: Callable[[EdgarSubmission], str],
    listed_now: Callable[[], bool], as_of: date, other_registrant: Callable[[], int | None] = lambda: None)
    -> tuple[str, str]` (evidence, refusal).
  - `other_registrant(search, edgar, *, name, day, cik, own_tickers) -> int | None`.
  - `decide(step, sec, cands: list[FigiCandidate] | None, securities) -> Decision`;
    `composites(answer) -> list[FigiCandidate] | None`.
  - `is_line_symbol`, `is_otc_symbol`, `text_symbols`, `text_cusips`, `cusip_check_digit_ok`, `eightks_near`,
    `name_on(sub, day, fallback="") -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_line_follow.py`:

```python
"""line_follow: a security's line across a CUSIP or ticker change (sub-plan 5a; rulings R1, R2). Pure, synthetic
rows; tests/test_line_follow_cases.py runs the same functions over real cached cases."""
from datetime import date, timedelta

import pytest

from delist_detection import line_follow as lf
from delist_detection.edgar import EdgarSubmission
from delist_detection.figi_resolution import us_candidates
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.observations import TickerEra
from delist_detection.security_master import Security


def _rows(symbol, cusip, desc, start, n, *, step=1, prices=None):
    """`n` fails rows from ISO `start`, one every `step` calendar days on weekdays, prices changing each row."""
    out, day = [], date.fromisoformat(start)
    while len(out) < n:
        if day.weekday() < 5:
            p = prices[len(out)] if prices else 10.0 + len(out) * 0.1
            out.append(FtdRow(day.isoformat(), cusip, symbol, desc, p))
        day += timedelta(days=step)
    return out


OLD = _rows("RS", "11111A101", "REVERSE SPLIT CO", "2012-08-01", 40)      # last row 2012-09-25


def _steps(rows, cusips=("11111A101",), tickers=("RS",), **kw):
    return lf.candidate_steps("BBGRS", list(cusips), set(tickers), FtdIndex(rows), **kw)


def test_a_reverse_split_is_a_switch_dated_by_its_first_day_zzzz_row():
    new = [FtdRow("2012-09-26", "11111A200", "RSZZZZ", "REVERSE SPLIT CO NEW", 0.01),
           *_rows("RS", "11111A200", "REVERSE SPLIT CO NEW", "2012-09-27", 5)]
    [st] = _steps(OLD + new)
    assert (st.kind, st.old_cusip, st.new_cusip, st.symbol, st.old_last, st.first) == (
        lf.SWITCH, "11111A101", "11111A200", "RS", "2012-09-25", "2012-09-26")
    assert st.descriptions == ("REVERSE SPLIT CO NEW",)


def test_a_rename_on_the_same_cusip_is_a_new_symbol():
    [st] = _steps(OLD + _rows("RSNW", "11111A101", "REVERSE SPLIT CO", "2012-09-26", 5))
    assert (st.kind, st.new_cusip, st.symbol, st.first) == (lf.NEW_SYMBOL, "11111A101", "RSNW", "2012-09-26")


def test_a_post_split_d_spelling_finds_the_switch_and_the_plain_ticker_names_it():
    """YRCW 2010: the new CUSIP trades as YRCWD for its first weeks, then as YRCW."""
    new = _rows("RSD", "11111A200", "REVERSE SPLIT CO", "2012-09-26", 12) + \
        _rows("RS", "11111A200", "REVERSE SPLIT CO", "2012-10-15", 5)
    [st] = _steps(OLD + new)
    assert (st.kind, st.symbol, st.first) == (lf.SWITCH, "RS", "2012-09-26")


def test_a_switch_is_timed_from_the_settling_tail_not_the_last_row():
    """SLE 2012: the old CUSIP fails at one price for 13 trading days after its last trade."""
    tail = [FtdRow(d, "11111A101", "RS", "REVERSE SPLIT CO", 9.0) for d in
            ("2012-09-26", "2012-09-27", "2012-09-28", "2012-10-01", "2012-10-02", "2012-10-03", "2012-10-04",
             "2012-10-05", "2012-10-08", "2012-10-09", "2012-10-10", "2012-10-11", "2012-10-12")]
    new = _rows("RSB", "22222B101", "REVERSE SPLIT CO", "2012-09-27", 5)
    [st] = _steps(OLD + tail + new, extra_symbols={"RSB"})
    assert (st.old_last, st.first, st.symbol) == ("2012-09-26", "2012-09-27", "RSB")


def test_a_new_cusip_too_long_after_the_old_line_is_no_step():
    """GOCO 2023: eight months between the old CUSIP's last row and the new one's first."""
    assert _steps(OLD + _rows("RS", "11111A200", "REVERSE SPLIT CO", "2013-05-01", 5)) == []


def test_an_old_cusip_that_trades_on_under_an_otc_symbol_takes_no_later_switch_or_symbol():
    """VRM 2025: after the bankruptcy the old CUSIP trades as VRMMQ, and the reorganized company's new CUSIP takes
    the ticker; neither is a step of the old line."""
    otc = _rows("RSXYQ", "11111A101", "REVERSE SPLIT CO", "2012-09-26", 30)
    relist = _rows("RS", "11111A200", "REVERSE SPLIT CO", "2012-10-01", 5)
    assert _steps(OLD + otc + relist) == []


@pytest.mark.parametrize("symbol", ["RSCOQ", "RSCOF", "RSQ", "RSXXXX", "RSZZZZ", "P105PS", "RS-WI"])
def test_no_otc_deleted_unassigned_or_cusip_tail_symbol_is_a_new_symbol(symbol):
    assert _steps(OLD + _rows(symbol, "11111A101", "REVERSE SPLIT CO", "2012-09-26", 5)) == []


def test_a_cusip_another_security_holds_is_never_a_step():
    """WLL 2017: the new CUSIP is already another security's line of the run."""
    new = _rows("RS", "11111A200", "REVERSE SPLIT CO NEW", "2012-09-26", 5)
    assert _steps(OLD + new, holders={"11111A200": {"BBGOTHER"}}) == []
    assert len(_steps(OLD + new, holders={"11111A200": {"BBGRS"}})) == 1


def test_a_shared_cusip_takes_no_new_symbol():
    """SPW 2015: another security of the run holds the same CUSIP; a new symbol of it is that security's."""
    assert _steps(OLD + _rows("RSNW", "11111A101", "REVERSE SPLIT CO", "2012-09-26", 5),
                  holders={"11111A101": {"BBGRS", "BBGSPXC"}}) == []


def test_a_spin_off_on_a_new_cusip_while_the_old_one_trades_on_is_only_a_new_symbol():
    """GOOG 2014: the class C CUSIP takes GOOG while the old CUSIP goes on as GOOGL."""
    on = _rows("RSL", "11111A101", "REVERSE SPLIT CO", "2012-09-26", 30)
    spun = _rows("RS", "11111A706", "REVERSE SPLIT CO CL C", "2012-09-26", 5)
    [st] = _steps(OLD + on + spun)
    assert (st.kind, st.symbol) == (lf.NEW_SYMBOL, "RSL")


def test_of_several_new_cusips_under_the_issuers_tickers_the_shortest_symbol_is_the_common():
    """SNH 2020: DHC's common, and its notes DHCNI and DHCNL, all began on the rename."""
    new = (_rows("DHC", "25525P107", "DIVERSIFIED HEALTHCARE TRUST C", "2012-09-26", 5)
           + _rows("DHCNI", "25525P206", "DIVERSIFIED HEALTHCARE TRUST 5", "2012-09-26", 5)
           + _rows("DHCNL", "25525P305", "DIVERSIFIED HEALTHCARE TRUST 6", "2012-09-26", 5))
    [st] = _steps(OLD + new, extra_symbols={"DHC", "DHCNI", "DHCNL"})
    assert (st.new_cusip, st.symbol) == ("25525P107", "DHC")


def test_two_new_cusips_under_equal_symbols_are_no_step():
    new = (_rows("RSA", "11111A200", "REVERSE SPLIT CO", "2012-09-26", 5)
           + _rows("RSB", "11111A309", "REVERSE SPLIT CO", "2012-09-26", 5))
    assert _steps(OLD + new, extra_symbols={"RSA", "RSB"}) == []


def test_a_cusip_the_8k_text_names_is_a_switch_under_whatever_symbol_it_trades():
    """LIZ 2012: "the CUSIP number changed to 316645100 and the new trading symbol ... is FNP"."""
    [st] = _steps(OLD + _rows("FNP", "316645100", "FIFTH & PACIFIC COMPANIES, INC", "2012-09-26", 5),
                  extra_cusips={"316645100"})
    assert (st.kind, st.new_cusip, st.symbol) == (lf.SWITCH, "316645100", "FNP")


def test_the_8k_text_sources():
    text = ("the CUSIP number changed to 316645100 and the new trading symbol for the common stock is FNP. "
            "Separately, the company will trade under the ticker symbol “CHX”. Old CUSIP No. 53815P108.")
    assert lf.text_symbols([text]) == {"FNP", "CHX"}
    assert lf.text_cusips([text]) == {"316645100", "53815P108"}
    assert lf.text_cusips(["CUSIP number 123456789"]) == set()           # its check digit fails
    assert lf.text_symbols(["Trading Symbol(s) Name of each exchange on which registered"]) == set()
    assert lf.cusip_check_digit_ok("037833100") and not lf.cusip_check_digit_ok("037833101")


# --- corroborate: what the issuer's filings say about a step (R1) ---

def _f(form, filed, items="", report="", acc=None):
    return EdgarSubmission(acc or f"{form}-{filed}", form, filed, report, items, "d.htm")


STEP = lf.LineStep("BBGRS", lf.SWITCH, "11111A101", "11111A200", "RS", "2012-09-25", "2012-09-26",
                   ("REVERSE SPLIT CO NEW",))
SUB = {"name": "Reverse Split Co", "formerNames": []}
LATER_10Q = _f("10-Q", "2012-11-08", report="2012-09-30")


def _corr(step=STEP, filings=(), sub=SUB, share_class="COMMON", texts=None, listed=False, as_of=date(2026, 9, 25),
          other=None):
    texts = texts or {}
    return lf.corroborate(step, filings=list(filings), sub=sub, share_class=share_class,
                          text_of=lambda f: texts.get(f.accession, ""), listed_now=lambda: listed, as_of=as_of,
                          other_registrant=lambda: other)


def test_an_8k_item_5_03_states_a_switch():
    assert _corr(filings=[_f("8-K", "2012-09-24", "5.03,9.01"), LATER_10Q]) == ("8-K 5.03,9.01 2012-09-24", "")


def test_an_edgar_rename_states_a_switch():
    sub = {"name": "Reverse Split Co", "formerNames": [{"name": "Old Split Co", "from": "2001-01-01T00:00:00.000Z",
                                                       "to": "2012-09-20T00:00:00.000Z"}]}
    assert _corr(filings=[LATER_10Q], sub=sub) == ("renamed from Old Split Co 2012-09-20", "")


def test_an_8k_text_stating_a_reverse_split_states_a_switch():
    """DYN 2010: no item 5.03; the 8-K text says the reverse split took effect."""
    k = _f("8-K", "2012-09-25", "8.01", acc="K1")
    assert _corr(filings=[k, LATER_10Q], texts={"K1": "a one-for-eight reverse stock split"}) == (
        "8-K text 2012-09-25", "")


def test_no_filing_stating_the_switch_refuses_it():
    assert _corr(filings=[LATER_10Q]) == ("", "no_filing")


def test_a_bankruptcy_8k_refuses_the_step():
    """UAL 2006: the plan cancelled the old shares; the new CUSIP is the reorganized company's."""
    assert _corr(filings=[_f("8-K", "2012-05-01", "1.03"), _f("8-K", "2012-09-24", "5.03"), LATER_10Q]) == (
        "", "bankruptcy")


def test_a_registrant_that_merged_out_refuses_the_step():
    """UNIT 2025: the old registrant filed a Form 15 and no periodic report for a later period. BXS 2017: a 10-Q
    filed after the step, for the quarter before it, is no sign the registrant carried on."""
    assert _corr(filings=[_f("8-K", "2012-09-24", "5.03"), _f("15-12G", "2012-09-27")]) == ("", "merged_out")
    assert _corr(filings=[_f("8-K", "2012-09-24", "5.03"), _f("10-Q", "2012-10-10", report="2012-06-30")]) == (
        "", "merged_out")


def test_the_registrants_own_successor_registration_carries_it_on():
    assert _corr(filings=[_f("8-K12B", "2012-09-26")]) == ("8-K12B 2012-09-26", "")


def test_a_recent_step_of_a_line_listed_today_carries_on_before_its_next_report():
    recent = lf.LineStep("BBGRS", lf.SWITCH, "11111A101", "11111A200", "RS", "2026-07-17", "2026-07-20",
                         ("REVERSE SPLIT CO NEW",))
    f = [_f("8-K", "2026-07-20", "5.03")]
    assert _corr(recent, filings=f, listed=True) == ("8-K 5.03 2026-07-20", "")
    assert _corr(recent, filings=f, listed=False) == ("", "merged_out")


def test_another_registrants_successor_filing_refuses_the_step():
    """SBGI 2023: a new holding company (another CIK) registered as the old registrant's successor."""
    assert _corr(filings=[_f("8-K", "2012-09-24", "5.03"), LATER_10Q], other=999) == ("", "other_registrant")


def test_new_rows_named_only_by_a_name_the_issuer_left_behind_refuse_a_switch():
    """New LMCA 2013: the new CUSIP under the ticker is another issuer's; its description matches the old
    issuer's former name only. The names in force from the first new row decide."""
    sub = {"name": "Starz", "formerNames": [{"name": "Liberty Media Corp", "from": "2011-09-01T00:00:00.000Z",
                                             "to": "2012-09-20T00:00:00.000Z"}]}
    step = lf.LineStep("BBGRS", lf.SWITCH, "11111A101", "11111A200", "RS", "2012-09-25", "2012-09-26",
                       ("LIBERTY MEDIA CORP DELAWARE CL",))
    assert _corr(step, filings=[_f("8-K", "2012-09-24", "5.03"), LATER_10Q], sub=sub) == ("", "name")


def test_a_class_letter_other_than_the_lines_refuses_a_switch():
    step = lf.LineStep("BBGRS", lf.SWITCH, "11111A101", "11111A706", "RS", "2012-09-25", "2012-09-26",
                       ("REVERSE SPLIT CO CL C",))
    f = [_f("8-K", "2012-09-24", "5.03"), LATER_10Q]
    assert _corr(step, filings=f, share_class="CLASS A") == ("", "class")
    assert _corr(step, filings=f, share_class="COMMON")[1] == ""          # a line with no class letter takes it


def test_a_new_symbol_near_a_suspension_or_form_25_is_an_otc_move():
    """TMA 2008, FST 2014: the same CUSIP under a new symbol after a delisting is the OTC tail, not the line."""
    step = lf.LineStep("BBGRS", lf.NEW_SYMBOL, "11111A101", "11111A101", "RSNW", "2012-09-25", "2012-09-26")
    for filing in (_f("8-K", "2012-09-20", "3.01"), _f("25-NSE", "2012-09-15"), _f("15-12B", "2012-10-05")):
        assert _corr(step, filings=[filing, LATER_10Q]) == ("", "otc_move")
    assert _corr(step, filings=[LATER_10Q]) == ("same CUSIP", "")


def test_name_on_is_the_edgar_name_on_the_day_without_its_state_tag():
    sub = {"name": "Starz", "formerNames": [{"name": "LIBERTY MEDIA CORP /DE/", "from": "2011-09-01T00:00:00.000Z",
                                             "to": "2013-01-11T00:00:00.000Z"}]}
    assert lf.name_on(sub, date(2012, 6, 1)) == "LIBERTY MEDIA CORP"
    assert lf.name_on(sub, date(2014, 1, 1)) == "Starz"
    assert lf.name_on(None, date(2014, 1, 1), "OBSERVED CO") == "OBSERVED CO"


# --- other_registrant: another CIK's 8-K12B/8-K12G3 naming the issuer ---

class _Edgar:
    def __init__(self, listed):
        self.listed = listed

    def submissions(self, cik):
        return {"tickers": self.listed.get(int(cik), []), "exchanges": ["NYSE"] * len(self.listed.get(int(cik), []))}


def _hit(cik, display):
    return {"_source": {"ciks": [f"{cik:010d}"], "display_names": [display], "form": "8-K12B",
                        "file_date": "2012-09-27"}}


def test_another_ciks_successor_filing_naming_the_issuer_is_found():
    asked = []

    def search(q, forms, lo, hi):
        asked.append((q, forms, lo, hi))
        return [_hit(1, "Reverse Split Co (RS) (CIK 0000000001)"),
                _hit(2, "Reverse Split Holdings Inc (RSH) (CIK 0000000002)")]
    got = lf.other_registrant(search, _Edgar({}), name="Reverse Split Co", day=date(2012, 9, 26), cik=1,
                              own_tickers={"RS"})
    assert got == 2 and asked == [('"Reverse Split Co"', "8-K12B,8-K12G3", date(2012, 8, 27), date(2012, 11, 25))]


def test_another_listed_issuers_own_filing_that_names_the_issuer_is_not_its_successor():
    """iHeartMedia's 8-K12G3 names its subsidiary Clear Channel Outdoor; IHRT is iHeart's own listed stock."""
    def search(q, forms, lo, hi):
        return [_hit(7, "iHeartMedia, Inc. (IHRT) (CIK 0000000007)")]
    assert lf.other_registrant(search, _Edgar({7: ["IHRT"]}), name="Clear Channel Outdoor Holdings",
                               day=date(2019, 5, 2), cik=1, own_tickers={"CCO"}) is None
    assert lf.other_registrant(None, _Edgar({}), name="X", day=date(2019, 5, 2), cik=1, own_tickers=()) is None


# --- decide: R2 ---

def _cand(composite, name="REVERSE SPLIT CO", ticker="RS"):
    return us_candidates([{"figi": composite, "compositeFIGI": composite, "exchCode": "US", "ticker": ticker,
                           "name": name, "securityType": "Common Stock"}])


def _sec(sec_id, cik=1, share_class="COMMON"):
    return Security(sec_id, cik, share_class, "REVERSE SPLIT CO", "Common Stock", True,
                    "placeholder" if sec_id.startswith("CIK") else "cusip",
                    eras=[TickerEra("RS", "2008-01-16", "2010-06-30")])


def test_decide_follows_r2():
    figi_line, placeholder = _sec("BBGRS"), _sec("CIK1-COMMON")
    new_symbol = lf.LineStep("BBGRS", lf.NEW_SYMBOL, "11111A101", "11111A101", "RSNW", "2012-09-25", "2012-09-26")
    assert lf.decide(new_symbol, figi_line, None, {}).kind == lf.ATTACH
    assert lf.decide(STEP, figi_line, [], {}).kind == lf.ATTACH                              # no US line
    assert lf.decide(STEP, figi_line, _cand("BBGRS"), {}).kind == lf.ATTACH                  # the same composite
    assert lf.decide(STEP, figi_line, None, {}) == lf.Decision(lf.REFUSED, why="unsettled")  # an OpenFIGI error
    assert lf.decide(STEP, figi_line, _cand("BBGX1") + _cand("BBGX2"), {}).why == "unsettled"
    d = lf.decide(STEP, figi_line, _cand("BBGNEW"), {})
    assert (d.kind, d.composite) == (lf.SUCCESSOR, "BBGNEW")
    d = lf.decide(STEP, placeholder, _cand("BBGNEW"), {"BBGNEW": _sec("BBGNEW")})
    assert (d.kind, d.composite) == (lf.FOLD, "BBGNEW")
    assert lf.decide(STEP, placeholder, _cand("BBGNEW"), {"BBGNEW": _sec("BBGNEW", cik=2)}).why == "other_issuer"
    assert lf.decide(STEP, placeholder, _cand("BBGNEW"), {"BBGNEW": _sec("BBGNEW", share_class="CLASS A")}).why == \
        "class"


def test_composites_reads_an_answer():
    assert lf.composites({"error": "Invalid idValue"}) is None
    assert lf.composites({"warning": "No identifier found."}) == []
    assert [c.composite for c in lf.composites({"data": [{"compositeFIGI": "BBGX", "exchCode": "US", "ticker": "X",
                                                          "name": "X CO"}]})] == ["BBGX"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_line_follow.py`
Expected: FAIL (`No module named 'delist_detection.line_follow'`).

- [ ] **Step 3: Write the module**

Create `src/delist_detection/line_follow.py`:

```python
"""Follow a security's line across a CUSIP or ticker change (sub-plan 5a, spec 2026-10-03-diagnosis-truth-fixes,
section 3 "5a", rulings R1 and R2).

The caller's observations of a security can stop years before its line ends: the issuer reverse-split (a new CUSIP
under the same ticker), renamed itself (the same CUSIP under a new ticker), or did both. The fails-to-deliver rows
show the line going on. `candidate_steps` finds, for one security, the next step of its line in those rows (pure);
`corroborate` checks the step against the issuer's EDGAR record (pure, over what the caller read); `decide` applies
R2 (the new CUSIP's OpenFIGI composite) to the step. The pipeline's stage 4b (`pipeline._follow_lines`) runs them,
up to `MAX_ROUNDS` steps a line, before the Form 25 search.

A step is followed only when the old registrant carries on (R1): it files a periodic report after the step, or the
step is its own successor registration (8-K12B/8-K12G3), and no other registrant's 8-K12B/8-K12G3 names it then.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .edgar import EdgarSubmission
from .evidence import name_at, names_between
from .figi_resolution import FigiCandidate, class_letter, is_placeholder, share_class_from_name, us_candidates
from .ftd import FtdIndex, FtdRow, is_deleted_symbol, is_unassigned_symbol, settled_last
from .listing_status import edgar_lists
from .names import description_names, names_agree
from .observations import normalize_ticker
from .security_master import SWITCH_TAIL_DAYS, Security
from .successors import successor_query
from .trading_calendar import add_trading_days

SWITCH, NEW_SYMBOL = "cusip_switch", "new_symbol"
ATTACH, FOLD, SUCCESSOR, REFUSED = "attach", "fold", "successor", "refused"
LINE_DAYS = 10                # trading days either side of the old CUSIP's settled last row
MIN_NEW_ROWS = 3              # fewer fails rows than this under the new CUSIP or symbol are noise
FILING_DAYS = 30              # an 8-K 5.03/3.03, an 8-K text or an 8-K12B this close to the first new row states it
RENAME_DAYS = 90              # an EDGAR rename this close to the first new row states it
BANKRUPTCY_BEFORE_DAYS, BANKRUPTCY_AFTER_DAYS = 180, 30    # an 8-K item 1.03 in this window refuses the step
NAME_DAYS = 30                # the new rows' descriptions must name a name in force this long from the first row
RECENT_DAYS = 120             # a step this close to the run date may have no periodic report after it yet
MAX_ROUNDS = 3                # steps followed per line (WIN's two reverse splits, LPI's switch then rename)
MAX_TEXTS = 5                 # 8-K texts read per step for a reverse split or the new CUSIP
PERIODIC_FORMS = frozenset({"10-K", "10-Q", "20-F", "40-F", "10-KT", "10-QT"})
SUCCESSOR_FORMS = frozenset({"8-K12B", "8-K12G3"})
_REVERSE_SPLIT = re.compile(r"reverse\s+(?:stock\s+)?split|share\s+consolidation", re.I)
_SYMBOL = re.compile(r"[A-Z]{1,5}(?:-[A-Z])?")
# "under the ticker symbol “CHX”", "the new trading symbol for the common stock is FNP"; the ticker is upper case
_TEXT_SYMBOL = re.compile(r"(?i:symbol)[^.;]{0,60}?(?:\b(?i:is|to|of|under)\b\s*|[\"“'(])\s*[\"“'(]?([A-Z]{1,5})\b(?![a-z])")
_STATE_TAG = re.compile(r"\s*/[A-Z]+/?\s*$")          # EDGAR's "AETNA INC /PA/"
# "the CUSIP number changed to 316645100": a nine-character CUSIP within 60 characters of the word
_TEXT_CUSIP = re.compile(r"(?i:CUSIP)(?:\s*(?i:No)\.)?[^.;]{0,60}?\b([0-9A-Za-z]{8}[0-9])\b")


@dataclass(frozen=True)
class LineStep:
    """One step of a security's line in the fails rows: `kind` SWITCH (a new CUSIP under the line's ticker, its
    first-day "...ZZZZ" symbol, its post-split "...D" symbol, or a new ticker of the issuer) or NEW_SYMBOL (the same
    CUSIP under a new ticker). `old_last` is the old CUSIP's last row under the line's tickers once a fail still
    settling at the last close is set aside (`ftd.settled_last`); `first` is the new rows' first row; `symbol` the
    ticker they trade under; `descriptions` the new rows' descriptions in their first `NAME_DAYS` days."""
    sec_id: str
    kind: str
    old_cusip: str
    new_cusip: str
    symbol: str
    old_last: str
    first: str
    descriptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class LineSuccessor:
    """A FIGI line whose new CUSIP has its own composite (R2: two securities, the new one a continuation): the
    composite, the OpenFIGI candidate it came from, the step and the filing that states it."""
    sec_id: str
    composite: str
    candidate: FigiCandidate
    step: LineStep
    evidence: str


@dataclass(frozen=True)
class Decision:
    """What R2 makes of a step: ATTACH (one security), FOLD (a placeholder into `composite`), SUCCESSOR (a FIGI
    line continued by `composite`) or REFUSED (`why`)."""
    kind: str
    composite: str = ""
    why: str = ""
    candidate: FigiCandidate | None = None


def is_line_symbol(symbol: str) -> bool:
    """A symbol a listed line can trade under: letters, and a class letter after a dash (BF-B). Never a deleted
    "...XXXX" or first-day "...ZZZZ" symbol, a masked or CUSIP-tail one (P105PS), or a when-issued one."""
    return bool(_SYMBOL.fullmatch(symbol or "")) and not is_deleted_symbol(symbol) \
        and not is_unassigned_symbol(symbol)


def is_otc_symbol(symbol: str, tickers: Iterable[str]) -> bool:
    """An over-the-counter symbol after a delisting: five letters ending in Q (bankruptcy), F (foreign) or Y
    (ADR) -- RADCQ, WFTIF -- or one of the line's own tickers with a Q appended (DFQ)."""
    bare = symbol.replace("-", "")
    return (len(bare) == 5 and bare[-1] in "QFY") or any(bare == t.replace("-", "") + "Q" for t in tickers)


def _days(day: str, n: int) -> str:
    return add_trading_days(date.fromisoformat(day), n).isoformat()


def _line_symbol_of(rows: Sequence[FtdRow], tickers: Collection[str], fallback: str) -> str:
    """The ticker a new CUSIP's rows trade under: the first line symbol that is not a post-split "...D" spelling
    of one of the line's tickers (YRCWD for 20 days, then YRCW), else the scanned spelling stripped."""
    post_split = {t.replace("-", "") + "D" for t in tickers}
    for r in rows:
        if is_line_symbol(r.symbol) and r.symbol not in post_split:
            return r.symbol
    for t in tickers:
        if fallback in (t.replace("-", "") + "ZZZZ", t.replace("-", "") + "D"):
            return t
    return fallback


@dataclass(frozen=True)
class LineEnd:
    """Where a security's line stands in the fails rows: the CUSIP of its latest live row under one of its
    tickers (`cusip`), that CUSIP's last such row (`last`) and the row that opens its final run of one price
    (`settled`, `ftd.settled_last`)."""
    cusip: str
    last: str
    settled: str


def line_end(cusips: Sequence[str], tickers: Collection[str], ftd: FtdIndex) -> LineEnd | None:
    """The `LineEnd` of a security with `cusips` and `tickers`; None when no live row of its CUSIPs is under one
    of its tickers."""
    own = set(tickers)
    rows = sorted((r for r in ftd.trading_rows(cusips) if r.symbol in own), key=lambda r: (r.date, r.cusip))
    if not rows:
        return None
    old = [r for r in rows if r.cusip == rows[-1].cusip]
    return LineEnd(old[-1].cusip, old[-1].date, settled_last(old).date)


def _others(holders: Mapping[str, Collection[str]], cusip: str, sec_id: str) -> bool:
    return any(h != sec_id for h in holders.get(cusip, ()))


def _one_switch(switches: Mapping[str, LineStep], tickers: Collection[str]) -> list[LineStep]:
    """The one switch among several candidates: the one under the line's own ticker, else the one with the
    shortest symbol (an issuer's common trades under its shortest ticker: DHC beside its notes DHCNI and DHCNL);
    none when that leaves more than one."""
    picks = list(switches.values())
    if len(picks) > 1:
        picks = [s for s in picks if s.symbol in tickers] or picks
    if len(picks) > 1:
        short = min(len(s.symbol) for s in picks)
        picks = [s for s in picks if len(s.symbol) == short]
    return picks if len(picks) == 1 else []


def candidate_steps(sec_id: str, cusips: Sequence[str], tickers: Collection[str], ftd: FtdIndex, *,
                    holders: Mapping[str, Collection[str]] = {}, extra_symbols: Collection[str] = (),
                    extra_cusips: Collection[str] = (), days: int = LINE_DAYS) -> list[LineStep]:
    """The next steps of a security's line in the fails rows (pure). Its `line_end` opens a window of `days`
    trading days either side of the settled last row. `holders` maps a CUSIP to the securities of the run that
    hold it.

    - SWITCH: a CUSIP not among `cusips` and held by no other security, whose first row (under any symbol) falls in
      the window and that has at least `MIN_NEW_ROWS` rows, found under one of `tickers`, its "...ZZZZ" or "...D"
      spelling, one of `extra_symbols` (the issuer's other tickers), or among `extra_cusips` (CUSIPs its 8-K text
      names). None when the old CUSIP trades on past `SWITCH_TAIL_DAYS` after its last row under the tickers (a
      spin-off took the ticker while the old line went on: GOOG, AAN).
    - NEW_SYMBOL: the old CUSIP's first row under a line symbol that is not one of `tickers` and not an OTC
      symbol (`is_otc_symbol`), in the window, with at least `MIN_NEW_ROWS` rows under it. None when another
      security of the run holds the old CUSIP too, or when two symbols qualify.

    Of several switches, the one under the line's own ticker is taken, else the one with the shortest symbol
    (`_one_switch`)."""
    end = line_end(cusips, tickers, ftd)
    if end is None:
        return []
    own = set(tickers)
    lo, hi = _days(end.settled, -days), _days(end.settled, days)
    steps: list[LineStep] = []

    tail = _days(end.last, SWITCH_TAIL_DAYS)
    if not any(r.date > tail for r in ftd.trading_rows([end.cusip])):
        scan = {s for t in own for s in (t, t.replace("-", "") + "ZZZZ", t.replace("-", "") + "D")}
        found = {r.cusip: s for s in sorted(scan | set(extra_symbols)) for r in ftd.by_symbol(s, lo, hi)}
        found.update({c: "" for c in extra_cusips if c not in found})
        switches: dict[str, LineStep] = {}
        for c, s in sorted(found.items()):
            if c in cusips or _others(holders, c, sec_id):
                continue
            new_rows = ftd.by_cusip(c)
            if not new_rows or not lo <= new_rows[0].date <= hi or len(new_rows) < MIN_NEW_ROWS:
                continue
            first = new_rows[0].date
            until = (date.fromisoformat(first) + timedelta(days=NAME_DAYS)).isoformat()
            descs = tuple(sorted({x.description for x in new_rows if x.date <= until}))
            switches[c] = LineStep(sec_id, SWITCH, end.cusip, c, _line_symbol_of(new_rows, own, s), end.settled,
                                   first, descs)
        steps += _one_switch(switches, own)

    if not _others(holders, end.cusip, sec_id):
        renamed: dict[str, list[FtdRow]] = {}
        for r in ftd.trading_rows([end.cusip]):
            if r.symbol not in own and is_line_symbol(r.symbol) and not is_otc_symbol(r.symbol, own):
                renamed.setdefault(r.symbol, []).append(r)
        symbols = {s: rs for s, rs in renamed.items() if lo <= rs[0].date <= hi and len(rs) >= MIN_NEW_ROWS}
        if len(symbols) == 1:
            [(s, rs)] = symbols.items()
            steps.append(LineStep(sec_id, NEW_SYMBOL, end.cusip, end.cusip, s, end.settled, rs[0].date,
                                  tuple(sorted({x.description for x in rs[:MIN_NEW_ROWS]}))))
    return sorted(steps, key=lambda st: (st.first, st.kind))


def text_symbols(texts: Iterable[str]) -> set[str]:
    """The ticker symbols an 8-K's text names as the stock's new one ("under the ticker symbol "CHX""),
    upper-case."""
    return {m.group(1) for t in texts for m in _TEXT_SYMBOL.finditer(t or "")}


def cusip_check_digit_ok(cusip: str) -> bool:
    """Whether the ninth character of `cusip` is its check digit (the CUSIP modulus-10 double-add-double rule)."""
    if len(cusip) != 9 or not cusip[8].isdigit():
        return False
    total = 0
    for i, ch in enumerate(cusip[:8]):
        v = int(ch) if ch.isdigit() else ord(ch) - ord("A") + 10 if ch.isalpha() else None
        if v is None:
            return False
        if i % 2:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10 == int(cusip[8])


def text_cusips(texts: Iterable[str]) -> set[str]:
    """The CUSIP numbers an 8-K's text names (each passing its check digit)."""
    return {c for t in texts for m in _TEXT_CUSIP.finditer(t or "") if cusip_check_digit_ok(c := m.group(1).upper())}


def _filed(f: EdgarSubmission) -> date | None:
    try:
        return date.fromisoformat(f.filing_date[:10])
    except ValueError:
        return None


def _near(filings: Sequence[EdgarSubmission], day: date, before: int, after: int,
          keep: Callable[[EdgarSubmission], bool]) -> list[EdgarSubmission]:
    lo, hi = day - timedelta(days=before), day + timedelta(days=after)
    return [f for f in filings if keep(f) and (d := _filed(f)) is not None and lo <= d <= hi]


def eightks_near(filings: Sequence[EdgarSubmission], day: date) -> list[EdgarSubmission]:
    """The issuer's 8-Ks within `FILING_DAYS` of `day`, nearest first, at most `MAX_TEXTS`: the ones whose text
    may state a reverse split or name the new CUSIP or ticker."""
    near = _near(filings, day, FILING_DAYS, FILING_DAYS, lambda f: f.form.startswith("8-K"))
    return sorted(near, key=lambda f: (abs((_filed(f) - day).days), f.filing_date))[:MAX_TEXTS]


def corroborate(step: LineStep, *, filings: Sequence[EdgarSubmission], sub: Mapping | None, share_class: str,
                text_of: Callable[[EdgarSubmission], str], listed_now: Callable[[], bool], as_of: date,
                other_registrant: Callable[[], int | None] = lambda: None) -> tuple[str, str]:
    """(evidence, refusal) for `step` of a line (exactly one is non-empty), from its issuer's filings (`filings`),
    its EDGAR submissions JSON (`sub`), the 8-K texts `text_of` reads (only when no filing code states the change),
    whether its ticker is listed today (`listed_now`, asked only for a recent step), the run date and another CIK
    that filed an 8-K12B/8-K12G3 naming the issuer (`other_registrant`, asked only for a step nothing else
    refused; see `other_registrant()`). Refusals, in order:

    - "bankruptcy": an 8-K item 1.03 in [first - 180, first + 30] days (UAL's 2006 emergence: old shares cancelled);
    - "otc_move" (a new symbol only): an 8-K item 3.01, a Form 25 or a Form 15 within `FILING_DAYS`;
    - "name" (a switch only): no new row's description names (`names.description_names`) a name the issuer
      carried from the first new row on (`evidence.names_between`, `NAME_DAYS`): a ticker passed to another issuer
      (new LMCA 2013, new MSG 2015) carries the old name only as a former one;
    - "class" (a switch only): a new row's description states a class letter other than the line's;
    - "merged_out" (R1): no 10-K/10-Q/20-F/40-F for a period that ends after the first new row (a 10-Q filed
      days after the step reports on the old registrant's past: BXS 2017), the step is not the issuer's own
      8-K12B/8-K12G3 within `FILING_DAYS`, and it is not a step within `RECENT_DAYS` of the run date of a line
      listed today (UNIT 2025: Uniti Group LLC filed a 15-12G and no 10-Q);
    - "other_registrant" (R1): another CIK's 8-K12B/8-K12G3 names the issuer (SBGI 2023's new holding company);
    - "no_filing" (a switch only): no 8-K item 5.03 or 3.03, own 8-K12B/8-K12G3 or 8-K text stating a reverse
      split or naming the new CUSIP within `FILING_DAYS`, and no EDGAR rename within `RENAME_DAYS`.

    The evidence names the filing (a new symbol of the same CUSIP needs none: "same CUSIP")."""
    first = date.fromisoformat(step.first)
    if _near(filings, first, BANKRUPTCY_BEFORE_DAYS, BANKRUPTCY_AFTER_DAYS,
             lambda f: f.form.startswith("8-K") and "1.03" in f.item_set):
        return "", "bankruptcy"
    if step.kind == NEW_SYMBOL and _near(filings, first, FILING_DAYS, FILING_DAYS, lambda f: (
            (f.form.startswith("8-K") and "3.01" in f.item_set) or f.form.startswith("25") or f.form.startswith("15"))):
        return "", "otc_move"
    if step.kind == SWITCH:
        lo = first
        names = names_between(sub, lo, lo + timedelta(days=NAME_DAYS)) if isinstance(sub, Mapping) else []
        if not any(description_names(d, n) for d in step.descriptions for n in names):
            return "", "name"
        own = class_letter(share_class)
        if own and any((letter := class_letter(share_class_from_name(d))) and letter != own
                       for d in step.descriptions):
            return "", "class"
    own_successor = _near(filings, first, FILING_DAYS, FILING_DAYS, lambda f: f.form in SUCCESSOR_FORMS)
    periodic = any(f.form.split("/")[0] in PERIODIC_FORMS and (f.report_date or "")[:10] > step.first
                   for f in filings)
    if not (periodic or own_successor or ((as_of - first).days <= RECENT_DAYS and listed_now())):
        return "", "merged_out"
    if other_registrant() is not None:
        return "", "other_registrant"
    if step.kind == NEW_SYMBOL:
        return "same CUSIP", ""
    coded = _near(filings, first, FILING_DAYS, FILING_DAYS,
                  lambda f: f.form.startswith("8-K") and bool({"5.03", "3.03"} & f.item_set))
    if coded:
        f = min(coded, key=lambda f: abs((_filed(f) - first).days))
        return f"8-K {f.items} {f.filing_date}", ""
    if own_successor:
        f = min(own_successor, key=lambda f: abs((_filed(f) - first).days))
        return f"{f.form} {f.filing_date}", ""
    for fn in (sub.get("formerNames") or []) if isinstance(sub, Mapping) else ():
        to = (fn.get("to") or "")[:10]
        if to and abs((date.fromisoformat(to) - first).days) <= RENAME_DAYS:
            return f"renamed from {fn.get('name')} {to}", ""
    for f in eightks_near(filings, first):
        text = text_of(f) or ""
        if _REVERSE_SPLIT.search(text) or step.new_cusip in re.sub(r"\s+", "", text).upper():
            return f"8-K text {f.filing_date}", ""
    return "", "no_filing"


def name_on(sub: Mapping | None, day: date, fallback: str = "") -> str:
    """The issuer's EDGAR name on `day` (`evidence.name_at`) without EDGAR's state tag, else `fallback`: what
    another registrant's 8-K12B would have called it then."""
    name = name_at(sub, day) if isinstance(sub, Mapping) else ""
    return _STATE_TAG.sub("", name or "").strip() or fallback


def other_registrant(search: Callable | None, edgar, *, name: str, day: date, cik: int,
                     own_tickers: Collection[str]) -> int | None:
    """Another CIK whose 8-K12B/8-K12G3 names `name` in the successor search's window around `day`
    (`successors.successor_query`): a new registrant took the old one's place (R1). A filer that is another
    issuer's own, still-listed stock is skipped, as `successors.successor_from_8k12b` skips it: its EDGAR name
    does not agree with `name`, none of its tickers is one of `own_tickers`, and EDGAR lists one of them on a major
    exchange today (iHeartMedia's 8-K12G3 names its subsidiary Clear Channel Outdoor). None without a search."""
    if search is None or not name:
        return None
    own = {normalize_ticker(t) for t in own_tickers}
    for h in search(*successor_query(name, day)):
        src = h.get("_source", h)
        for cik_s, disp in zip(src.get("ciks") or [], src.get("display_names") or []):
            other = int(cik_s)
            if other == cik:
                continue
            m = re.search(r"\(([^()]*)\)\s*\(CIK\s+\d+\)\s*$", disp)
            tickers = [normalize_ticker(t) for t in m.group(1).split(",") if t.strip()] if m else []
            edgar_name = disp[: m.start()].strip() if m else re.sub(r"\s*\(CIK\s+\d+\)\s*$", "", disp).strip()
            if (tickers and not names_agree(name, edgar_name) and not own & set(tickers)
                    and edgar_lists(edgar, other, tickers)):
                continue
            return other
    return None


def composites(answer: Mapping) -> list[FigiCandidate] | None:
    """The US composites OpenFIGI gives a CUSIP job's `answer`; None for an error answer (nothing settled)."""
    if "error" in answer:
        return None
    return us_candidates(answer.get("data") or [])


def decide(step: LineStep, sec: Security, cands: list[FigiCandidate] | None,
           securities: Mapping[str, Security]) -> Decision:
    """R2 for `step` of security `sec`: a new symbol of the same CUSIP is the same security (ATTACH). A switch
    follows its new CUSIP's US composites (`cands`): none, or `sec`'s own, ATTACH; several, or an OpenFIGI error,
    REFUSED "unsettled"; one other composite X: REFUSED "other_issuer" when a security of the run of another
    issuer holds X, REFUSED "class" when one of another share class does, else FOLD into X for a placeholder (the
    truth set's reading of R2 for a line with no composite) and SUCCESSOR X for a FIGI line."""
    if step.kind == NEW_SYMBOL:
        return Decision(ATTACH)
    if cands is None or len(cands) > 1:
        return Decision(REFUSED, why="unsettled")
    if not cands or cands[0].composite == sec.sec_id:
        return Decision(ATTACH, cands[0].composite if cands else "", candidate=cands[0] if cands else None)
    x = cands[0]
    holder = securities.get(x.composite)
    if holder is not None and holder.issuer_cik is not None and holder.issuer_cik != sec.issuer_cik:
        return Decision(REFUSED, x.composite, "other_issuer", x)
    if holder is not None and holder.share_class != sec.share_class:
        return Decision(REFUSED, x.composite, "class", x)
    return Decision(FOLD if is_placeholder(sec.sec_id) else SUCCESSOR, x.composite, candidate=x)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_line_follow.py`
Expected: PASS (37 tests). Then the full suite: all pass, 281 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/line_follow.py tests/test_line_follow.py
git commit -m "The line follow: a line's next step in the fails rows, checked against R1 and decided by R2 (sub-plan 5a, U1)"
```

---

### Task 8: Real-case fixtures for the line follow

Tier: standard (the builder reads the local caches; its output is committed).

**Files:**
- Modify: `src/delist_detection/security_master.py` (`_cusip_job` becomes public `cusip_job`)
- Create: `scripts/build_line_fixtures.py`, `tests/test_line_follow_cases.py`
- Create (by the builder): `tests/fixtures/lines/{cases.json,ftd_rows.csv,edgar.json,openfigi.json,searches.json}`

**Interfaces:**
- Consumes: Task 7's `line_follow`.
- Produces: `security_master.cusip_job(c: str) -> dict` (the one OpenFIGI CUSIP job shape; Task 10 uses it). The
  fixture set and its test.

- [ ] **Step 1: Make the CUSIP job public**

In `src/delist_detection/security_master.py`, replace

```python
def _cusip_job(c: str) -> dict:
    return {"idType": "ID_CINS" if c[:1].isalpha() else "ID_CUSIP", "idValue": c, "includeUnlistedEquities": True}
```

with

```python
def cusip_job(c: str) -> dict:
    """The OpenFIGI mapping job for a CUSIP (a letter-first one is a CINS): every caller asks it the same way, so
    they share OpenFIGI's cache."""
    return {"idType": "ID_CINS" if c[:1].isalpha() else "ID_CUSIP", "idValue": c, "includeUnlistedEquities": True}
```

and in `resolve_many` replace `jobs.append(_cusip_job(c))` with `jobs.append(cusip_job(c))`.

- [ ] **Step 2: Write the builder**

Create `scripts/build_line_fixtures.py`:

```python
"""Build tests/fixtures/lines/ from the local caches, once (sub-plan 5a): the real cases the line follow's tests
replay offline (tests/test_line_follow_cases.py).

  PYTHONPATH=src python scripts/build_line_fixtures.py          # -> tests/fixtures/lines/

Offline: it reads the cached SEC fails-to-deliver zips (cache/sec_data/ftd), the cached EDGAR answers
(cache/edgar; every SEC request is refused, so a missing answer is left out, never fetched), the cached OpenFIGI
answers (cache/openfigi) and the committed output/ (each case's tickers, CUSIPs and the run's CUSIP holders). It
writes:

- cases.json: each case's security (sec_id, issuer CIK, share class, FIGI source, name, tickers, CUSIPs, the
  issuer's other tickers EDGAR lists, the CUSIPs and tickers its 8-K text names), the CUSIP holders of the run the
  steps meet, and the run's securities `decide` must know;
- ftd_rows.csv: the fails rows around each case's line end (and its second step's, for a two-step case);
- edgar.json: each issuer's EDGAR names, tickers and filings around the step, and the 8-K texts a step reads;
- openfigi.json: the cached OpenFIGI answer for each new CUSIP (its US-venue rows; absent when not cached);
- searches.json: the cached successor search of each step (absent when not cached).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import delist_detection.edgar as edgar_mod  # noqa: E402


def _refuse(*args, **kwargs):
    raise RuntimeError("build_line_fixtures is offline: a missing cache entry is left out")


edgar_mod.sec_get = _refuse
from delist_detection.atomic_io import write_atomic  # noqa: E402
from delist_detection.edgar import EdgarClient  # noqa: E402
from delist_detection.figi_resolution import US_EXCH  # noqa: E402
from delist_detection.ftd import FtdIndex, parse_ftd_lines, period_of  # noqa: E402
from delist_detection.line_follow import (  # noqa: E402
    SUCCESSOR_FORMS, SWITCH, candidate_steps, eightks_near, is_line_symbol, line_end, name_on, text_cusips,
    text_symbols,
)
from delist_detection.observations import normalize_ticker  # noqa: E402
from delist_detection.security_master import cusip_job  # noqa: E402
from delist_detection.successors import successor_query  # noqa: E402

AS_OF = date(2026, 9, 25)                 # the committed run's date
FTD_WINDOW = (date(2007, 12, 17), AS_OF)  # the committed run's fails window
ROUNDS = 2                                # a two-step case follows its attached step once more
# The cases: securities of the committed run, each with what it pins
CASES = {
    "BBG000BN6349": "FMD 2013: a reverse split under the same ticker, the same composite",
    "BBG000BLH3P8": "HSC 2023: Harsco renamed Enviri (NVRI) on the same CUSIP",
    "CIK1075415-COMMON": "SNH 2020: Senior Housing renamed Diversified Healthcare (DHC), new CUSIP, beside notes",
    "BBG001D9S707": "DYN 2010: a reverse split stated only in the 8-K text; the new CUSIP has its own composite",
    "BBG00JM9V731": "GTES 2026: a redomicile at a Form 25; the new CUSIP has its own composite",
    "BBG009NGKQ45": "VRM 2024: a reverse split; then bankruptcy (VRMMQ) and a 2025 relist that is no step",
    "BBG000BRWGG9": "RAD 2019: a reverse split; then the OTC RADCQ that is no step",
    "BBG002B67HB2": "UNIT 2025: the old registrant merged out (R1 before R2)",
    "BBG000F2XXP2": "SBGI 2023: a new holding company of another CIK",
    "BBG00WYYC600": "WLL 2017: the new CUSIP is another security's of the run",
    "BBG000BBG3P1": "TMA 2008: the same CUSIP under THMR after a delisting, an OTC move",
    "BBG000D9V7T4": "AAN 2020: the old registrant stopped filing at its reorganization",
    "BBG000FC9SM1": "BXS 2017: a 10-Q filed after the step for the quarter before it",
    "CIK1507934-CLASS-A": "LMCA 2013: the ticker passed to another issuer",
    "CIK1469372-CLASS-A": "MSG 2015: the ticker passed to another issuer",
    "BBG00D30HGP6": "CLNY 2021: Colony renamed DigitalBridge (DBRG), new CUSIP, no US line for it",
    "CIK1115836-COMMON": "OEH 2014: a placeholder whose new CUSIP names Belmond's FIGI line",
    "CIK1066104-COMMON": "EXBD 2012: Corporate Executive Board renamed CEB on the same CUSIP",
}
EXTRA_RUN = ("BBG01GJ3NY88", "BBG000BKZ5F6", "BBG000PX3XC0", "BBG003P9ZSL3", "BBG007FG0C23")


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


def _figi(cache: Path, cusip: str):
    job = cusip_job(cusip)
    h = hashlib.sha1(json.dumps({"kind": "mapping", "payload": job}, sort_keys=True).encode()).hexdigest()
    p = cache / f"{h}.json"
    return json.loads(p.read_text()) if p.exists() else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "lines")
    p.add_argument("--repo", type=Path, default=ROOT)
    args = p.parse_args(argv)
    repo, out = args.repo, args.out
    secs = {r["sec_id"]: r for r in _read(repo / "output/securities.csv")}
    tickers: dict[str, set[str]] = defaultdict(set)
    for r in _read(repo / "output/observation_map.csv"):
        if r["sec_id"]:
            tickers[r["sec_id"]].add(r["era"].split("@")[0])
    cusips: dict[str, list[str]] = defaultdict(list)
    holders: dict[str, set[str]] = defaultdict(set)
    for r in sorted(_read(repo / "output/cusip_history.csv"), key=lambda r: (r["valid_from"], r["cusip"])):
        if r["cusip"] not in cusips[r["sec_id"]]:
            cusips[r["sec_id"]].append(r["cusip"])
        holders[r["cusip"]].add(r["sec_id"])
    edgar = EdgarClient(repo / "cache/edgar", user_agent="build_line_fixtures fixtures@example.com", today=AS_OF)
    subs = {sid: _cached(edgar.submissions, int(secs[sid]["issuer_cik"])) for sid in CASES}
    extra = {sid: {normalize_ticker(t) for t in (subs[sid] or {}).get("tickers") or []
                   if is_line_symbol(normalize_ticker(t))} - tickers[sid] for sid in CASES}
    symbols = {t for sid in CASES for t in tickers[sid]} | {t for v in extra.values() for t in v}
    symbols |= {t.replace("-", "") + s for sid in CASES for t in tickers[sid] for s in ("ZZZZ", "D")}
    ftd = FtdIndex.load(LocalFtd(repo / "cache/sec_data/ftd"), *FTD_WINDOW, symbols=symbols,
                        cusips={c for sid in CASES for c in cusips[sid]})
    named: dict[str, set[str]] = defaultdict(set)
    filings = {sid: _cached(edgar.recent_filings, int(secs[sid]["issuer_cik"]), default=[]) for sid in CASES}
    for sid in CASES:                       # the 8-K text sources, as pipeline._text_sources reads them
        end = line_end(cusips[sid], tickers[sid], ftd)
        if end is None or candidate_steps(sid, cusips[sid], tickers[sid], ftd, holders=holders,
                                          extra_symbols=extra[sid]):
            continue
        cik = int(secs[sid]["issuer_cik"])
        near = [f for f in eightks_near(filings[sid], date.fromisoformat(end.settled))
                if f.form in SUCCESSOR_FORMS or {"5.03", "3.03"} & f.item_set]
        texts = [_cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="") or "" for f in near]
        extra[sid] |= {t for t in text_symbols(texts) if is_line_symbol(t)} - tickers[sid]
        named[sid] |= text_cusips(texts)
    ftd.extend(LocalFtd(repo / "cache/sec_data/ftd"), *FTD_WINDOW, symbols={t for v in extra.values() for t in v},
               cusips={c for v in named.values() for c in v})
    windows: dict[str, list[tuple[str, str, set[str], set[str]]]] = defaultdict(list)
    steps_of: dict[str, list] = {}
    for sid in CASES:
        own, cus = set(tickers[sid]), list(cusips[sid])
        for _ in range(ROUNDS):
            end = line_end(cus, own, ftd)
            if end is None:
                break
            steps = candidate_steps(sid, cus, own, ftd, holders=holders, extra_symbols=extra[sid],
                                    extra_cusips=named[sid])
            new = {st.new_cusip for st in steps if st.kind == SWITCH}
            if new:
                ftd.extend(LocalFtd(repo / "cache/sec_data/ftd"), *FTD_WINDOW, cusips=new)
                steps = candidate_steps(sid, cus, own, ftd, holders=holders, extra_symbols=extra[sid],
                                        extra_cusips=named[sid])
            lo = (date.fromisoformat(end.settled) - timedelta(days=200)).isoformat()
            hi = (date.fromisoformat(end.last) + timedelta(days=260)).isoformat()
            keep_symbols = own | extra[sid] | {t.replace("-", "") + s for t in own for s in ("ZZZZ", "D")}
            windows[sid].append((lo, hi, set(cus) | named[sid] | {st.new_cusip for st in steps}, keep_symbols))
            steps_of.setdefault(sid, steps)
            if not steps:
                break
            st = steps[0]                     # the next round follows the step as an attach would
            cus = cus + ([st.new_cusip] if st.kind == SWITCH and st.new_cusip not in cus else [])
            own = own | {st.symbol}
    rows = set()
    for sid, wins in windows.items():
        for lo, hi, cus, syms in wins:
            for c in cus:
                rows.update(ftd.by_cusip(c, lo, hi))
            for s in syms:
                rows.update(ftd.by_symbol(s, lo, hi))
    out.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "cusip", "symbol", "description", "price"])
    for r in sorted(rows, key=lambda r: (r.date, r.cusip, r.symbol, r.description, r.price or 0)):
        w.writerow([r.date, r.cusip, r.symbol, r.description, "" if r.price is None else r.price])
    write_atomic(out / "ftd_rows.csv", buf.getvalue())
    issuers, texts_out, figi_out, searches = {}, {}, {}, {}
    for sid in CASES:
        cik = int(secs[sid]["issuer_cik"])
        sub = subs[sid] or {}
        steps = steps_of.get(sid, [])
        end = line_end(cusips[sid], tickers[sid], ftd)
        anchor = date.fromisoformat(steps[0].first if steps else end.last if end else AS_OF.isoformat())
        lo, hi = (anchor - timedelta(days=200)).isoformat(), (anchor + timedelta(days=500)).isoformat()
        kept = [f for f in filings[sid] if lo <= (f.filing_date or "") <= hi]
        issuers[str(cik)] = {"name": sub.get("name", ""), "formerNames": sub.get("formerNames") or [],
                             "tickers": sub.get("tickers") or [], "exchanges": sub.get("exchanges") or [],
                             "filings": [[f.accession, f.form, f.filing_date, f.report_date, f.items, f.primary_doc]
                                         for f in sorted(kept, key=lambda f: (f.filing_date, f.accession))]}
        for st in steps[:1]:
            near = eightks_near(kept, date.fromisoformat(st.first))
            if not any({"5.03", "3.03"} & f.item_set for f in near):     # else corroborate reads no text
                for f in near:
                    text = _cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                    if text:
                        texts_out[f.accession] = text
            if st.kind == SWITCH and (ans := _figi(repo / "cache/openfigi", st.new_cusip)) is not None:
                # only the rows on a US venue, the ones `figi_resolution.us_candidates` reads
                figi_out[st.new_cusip] = {**ans, "data": [r for r in ans.get("data") or []
                                                          if r.get("exchCode") in US_EXCH]}
            name = name_on(sub, date.fromisoformat(st.first), secs[sid]["name"])
            q = successor_query(name, date.fromisoformat(st.first)) if name else None
            hits = _cached(edgar.full_text_search, *q, default=None) if q else None
            if hits is not None:
                searches[sid] = {"query": [q[0], q[1], q[2].isoformat(), q[3].isoformat()], "hits": hits}
    run = {k: {"issuer_cik": int(secs[k]["issuer_cik"]) if secs[k]["issuer_cik"] else None,
               "share_class": secs[k]["share_class"], "name": secs[k]["name"], "figi_source": secs[k]["figi_source"]}
           for k in (*CASES, *EXTRA_RUN) if k in secs}
    cases = {sid: {"note": note, "issuer_cik": int(secs[sid]["issuer_cik"]), "share_class": secs[sid]["share_class"],
                   "name": secs[sid]["name"], "figi_source": secs[sid]["figi_source"],
                   "tickers": sorted(tickers[sid]), "cusips": cusips[sid], "extra_symbols": sorted(extra[sid]),
                   "extra_cusips": sorted(named[sid])} for sid, note in CASES.items()}
    near_cusips = {r.cusip for r in rows}
    json_out = {"as_of": AS_OF.isoformat(), "cases": cases, "run": run,
                "holders": {c: sorted(holders[c]) for c in sorted(near_cusips) if holders.get(c)}}
    for name, data in (("cases.json", json_out), ("edgar.json", {"issuers": issuers, "texts": texts_out}),
                       ("openfigi.json", figi_out), ("searches.json", searches)):
        write_atomic(out / name, json.dumps(data, indent=1, sort_keys=True) + "\n")
    print(f"{len(cases)} cases, {len(rows)} fails rows, {len(texts_out)} 8-K texts, {len(figi_out)} OpenFIGI "
          f"answers, {len(searches)} searches -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Build the fixtures**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/build_line_fixtures.py`
Expected: about two minutes (three fails scans), then
`18 cases, 4341 fails rows, 2 8-K texts, 11 OpenFIGI answers, 1 searches -> .../tests/fixtures/lines` (the counts
the planning run printed; small differences mean the cache changed since, which Step 5 shows). Five files, about
650 KB together.

- [ ] **Step 4: Write the case tests**

Create `tests/test_line_follow_cases.py`:

```python
"""line_follow over real cases (sub-plan 5a): the cached fails rows, EDGAR answers and OpenFIGI answers of the
committed run's securities in tests/fixtures/lines/ (built once, offline, by scripts/build_line_fixtures.py), each
case's first step found, checked and decided as the pipeline's stage 4b does, and, for a two-step case, the next."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from delist_detection import line_follow as lf
from delist_detection.edgar import EdgarSubmission
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.listing_status import edgar_lists
from delist_detection.observations import TickerEra
from delist_detection.security_master import Security

FIX = Path(__file__).parent / "fixtures" / "lines"
DATA = json.loads((FIX / "cases.json").read_text())
EDGAR = json.loads((FIX / "edgar.json").read_text())
FIGI = json.loads((FIX / "openfigi.json").read_text())
SEARCHES = json.loads((FIX / "searches.json").read_text())
AS_OF = date.fromisoformat(DATA["as_of"])


@pytest.fixture(scope="module")
def ftd():
    with (FIX / "ftd_rows.csv").open(newline="") as fh:
        return FtdIndex(FtdRow(r["date"], r["cusip"], r["symbol"], r["description"],
                               float(r["price"]) if r["price"] else None) for r in csv.DictReader(fh))


class _Edgar:
    """The issuers' EDGAR answers as the fixture recorded them."""

    def submissions(self, cik):
        d = EDGAR["issuers"].get(str(int(cik)), {})
        return {"name": d.get("name", ""), "formerNames": d.get("formerNames", []), "tickers": d.get("tickers", []),
                "exchanges": d.get("exchanges", [])}

    def filings(self, cik):
        return [EdgarSubmission(a, form, fd, rd, items, doc)
                for a, form, fd, rd, items, doc in EDGAR["issuers"].get(str(int(cik)), {}).get("filings", [])]


EDGAR_FIX = _Edgar()


def _security(sec_id):
    d = DATA["run"][sec_id]
    return Security(sec_id, d["issuer_cik"], d["share_class"], d["name"], "Common Stock", True, d["figi_source"],
                    eras=[TickerEra(t, "2008-01-16", "2008-01-16") for t in DATA["cases"].get(sec_id, {}).get("tickers", [])])


RUN = {k: _security(k) for k in DATA["run"]}


def _search(sec_id):
    """The case's cached successor search, answered only for the query the case asks."""
    saved = SEARCHES.get(sec_id)

    def search(q, forms, lo, hi):
        if saved and saved["query"] == [q, forms, lo.isoformat(), hi.isoformat()]:
            return saved["hits"]
        return []
    return search


def follow(sec_id, ftd, *, cusips=None, tickers=None):
    """(step, evidence, refusal, decision) for the case's next step, as stage 4b reaches them; None, no step."""
    case = DATA["cases"][sec_id]
    cusips = cusips or case["cusips"]
    tickers = tickers or set(case["tickers"])
    steps = lf.candidate_steps(sec_id, cusips, tickers, ftd, holders=DATA["holders"],
                               extra_symbols=case["extra_symbols"], extra_cusips=case["extra_cusips"])
    if not steps:
        return None
    step, cik = steps[0], case["issuer_cik"]
    first = date.fromisoformat(step.first)
    evidence, refused = lf.corroborate(
        step, filings=EDGAR_FIX.filings(cik), sub=EDGAR_FIX.submissions(cik), share_class=case["share_class"],
        text_of=lambda f: EDGAR["texts"].get(f.accession, ""), as_of=AS_OF,
        listed_now=lambda: edgar_lists(EDGAR_FIX, cik, [*tickers, step.symbol]),
        other_registrant=lambda: lf.other_registrant(
            _search(sec_id), EDGAR_FIX, name=lf.name_on(EDGAR_FIX.submissions(cik), first, case["name"]), day=first,
            cik=cik, own_tickers=tickers))
    decision = None
    if not refused and (step.kind == lf.NEW_SYMBOL or step.new_cusip in FIGI):
        cands = lf.composites(FIGI[step.new_cusip]) if step.kind == lf.SWITCH else None
        decision = lf.decide(step, RUN[sec_id], cands, RUN)
    return step, evidence, refused, decision


# sec_id -> (kind, new CUSIP, symbol, first, refusal, decision kind, composite); decision None: OpenFIGI's answer
# for the new CUSIP is not cached, so the case stops at corroborate
EXPECTED = {
    "BBG000BN6349": (lf.SWITCH, "320771207", "FMD", "2013-12-03", "", lf.ATTACH, "BBG000BN6349"),
    "BBG000BLH3P8": (lf.NEW_SYMBOL, "415864107", "NVRI", "2023-06-21", "", lf.ATTACH, ""),
    "CIK1075415-COMMON": (lf.SWITCH, "25525P107", "DHC", "2020-01-03", "", None, None),
    "BBG001D9S707": (lf.SWITCH, "26817G300", "DYN", "2010-05-26", "", lf.SUCCESSOR, "BBG000BNLX91"),
    "BBG00JM9V731": (lf.SWITCH, "G39104107", "GTES", "2026-07-20", "", lf.SUCCESSOR, "BBG023G9VDF5"),
    "BBG009NGKQ45": (lf.SWITCH, "92918V208", "VRM", "2024-02-16", "", lf.ATTACH, "BBG009NGKQ45"),
    "BBG000BRWGG9": (lf.SWITCH, "767754872", "RAD", "2019-04-22", "", lf.ATTACH, "BBG000BRWGG9"),
    "BBG002B67HB2": (lf.SWITCH, "912932100", "UNIT", "2025-08-04", "merged_out", None, None),
    "BBG000BBG3P1": (lf.NEW_SYMBOL, "885218800", "THMR", "2008-12-11", "otc_move", None, None),
    "BBG000D9V7T4": (lf.SWITCH, "00258R109", "AAN", "2020-10-19", "merged_out", None, None),
    "BBG000FC9SM1": (lf.SWITCH, "05971J102", "BXS", "2017-11-01", "merged_out", None, None),
    "BBG00D30HGP6": (lf.SWITCH, "25401T108", "DBRG", "2021-06-22", "", lf.ATTACH, ""),
    "CIK1115836-COMMON": (lf.SWITCH, "G1154H107", "OEH", "2014-07-01", "", lf.FOLD, "BBG000BKZ5F6"),
    "CIK1066104-COMMON": (lf.NEW_SYMBOL, "21988R102", "CEB", "2012-08-14", "", lf.ATTACH, ""),
}
NO_STEP = ("BBG00WYYC600", "CIK1507934-CLASS-A", "CIK1469372-CLASS-A")


@pytest.mark.parametrize("sec_id", sorted(EXPECTED), ids=lambda s: DATA["cases"][s]["note"].split(":")[0])
def test_a_real_lines_next_step(sec_id, ftd):
    step, evidence, refused, decision = follow(sec_id, ftd)
    kind, new_cusip, symbol, first, why, decided, composite = EXPECTED[sec_id]
    assert (step.kind, step.new_cusip, step.symbol, step.first, refused) == (kind, new_cusip, symbol, first, why)
    assert bool(evidence) != bool(refused)
    if decided is None:
        assert decision is None
    else:
        assert (decision.kind, decision.composite) == (decided, composite)


@pytest.mark.parametrize("sec_id", NO_STEP, ids=lambda s: DATA["cases"][s]["note"].split(":")[0])
def test_a_line_whose_next_cusip_is_another_securitys_takes_no_step(sec_id, ftd):
    """Must not change: WLL 2017 (its new CUSIP is BBG000PX3XC0's), new LMCA 2013 and new MSG 2015 (the ticker
    passed to another issuer, whose line of the run holds the new CUSIP)."""
    assert follow(sec_id, ftd) is None


def test_sbgis_new_holding_company_is_never_its_line(ftd):
    """Must not change (SBGI 2023): the new holding company, another CIK, holds the new CUSIP's composite."""
    step, evidence, refused, decision = follow("BBG000F2XXP2", ftd)
    assert (step.new_cusip, refused or decision.why) == ("829242106", refused or "other_issuer")


@pytest.mark.parametrize("sec_id,otc", [("BBG009NGKQ45", "VRMMQ"), ("BBG000BRWGG9", "RADCQ")])
def test_after_a_reverse_split_the_bankrupt_lines_otc_tail_and_relist_are_no_step(sec_id, otc, ftd):
    """Must not change (VRM 2025, RAD 2023): once the reverse split is followed, the line's next rows are its
    OTC symbol after the bankruptcy (and, for VRM, the reorganized company's 2025 CUSIP under VRM): no step."""
    step, *_ = follow(sec_id, ftd)
    case = DATA["cases"][sec_id]
    assert follow(sec_id, ftd, cusips=[*case["cusips"], step.new_cusip], tickers={*case["tickers"]}) is None
    assert otc in {r.symbol for r in ftd.by_cusip(step.new_cusip)}
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_line_follow_cases.py`
Expected: PASS (20 tests; the planning build passed all of them). If a case's row differs, the local cache changed
since planning: read the case's rows in the fixture, and change `EXPECTED` only when the new answer is right by the
module's rules; say so in the commit message. Never weaken a NO_STEP or must-not-change case.

Then the full suite: all pass, 281 xfailed.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/security_master.py scripts/build_line_fixtures.py tests/test_line_follow_cases.py tests/fixtures/lines
git commit -m "Real-case fixtures for the line follow, built offline from the caches (sub-plan 5a)"
```

---

### Task 9: U6, a Form 25 at the security's own CUSIP switch is no delisting while it trades on

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/delistings.py`, `src/delist_detection/pipeline.py`
- Test: `tests/test_delistings.py`

**Interfaces:**
- Produces: `SecurityContext.cusip_switches: tuple[str, ...] = ()` (the first sighting of each of the security's
  CUSIPs after its first); `delistings.OWN_SWITCH_DAYS = 5`; `DelistingFinder._at_own_switch(ctx, filing_date)`;
  `pipeline._cusip_switches(s, ftd, cusips)`; `pipeline._context_builder(securities, sightings, answers, ftd,
  sec_cusips)`.
- The skip applies only to a Form 25 the security traded through (`continued`), and only for a CUSIP switch (a
  same-CUSIP symbol change at a Form 25 is never skipped: TSP).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_delistings.py` (`replace` is imported since Task 6):

```python


# --- sub-plan 5a, U6: a Form 25 at the security's own CUSIP switch ---

def _switch_case(fake_edgar):
    fake_edgar.submissions_by_cik[1015820] = [EdgarSubmission("q1", "25-NSE", "2026-01-08", "", "", "p.xml")]
    fake_edgar.raws["q1"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    return DelistingFinder(fake_edgar, clf), _sec("BBG000GTYWL7", 1015820, "QGEN", "2010-01-01", "2026-06-30",
                                                  "QIAGEN NV")


def test_a_form25_at_the_securitys_own_cusip_switch_is_no_delisting_while_it_trades_on(fake_edgar):
    """QGEN 2026: a capital repayment gave the same line a new CUSIP (N72482206 -> N72482156, first row
    2026-01-07); the 25-NSE of 2026-01-08 removed the old CUSIP while QGEN went on trading."""
    finder, sec = _switch_case(fake_edgar)
    ctx = replace(_ctx(sec, listed=True, seen_after=True), cusip_switches=("2026-01-07",))
    events, review = finder.find(ctx)
    assert events == [] and review == []


def test_a_form25_far_from_any_own_switch_still_counts(fake_edgar):
    finder, sec = _switch_case(fake_edgar)
    for switches in ((), ("2025-06-02",)):
        events, _ = finder.find(replace(_ctx(sec, listed=True, seen_after=True), cusip_switches=switches))
        assert [e.delist_date for e in events] == ["2026-01-18"]


def test_a_form25_at_an_own_switch_of_a_security_that_stopped_trading_still_counts(fake_edgar):
    """The switch only explains a Form 25 the security traded through (`continued`)."""
    finder, sec = _switch_case(fake_edgar)
    events, _ = finder.find(replace(_ctx(sec, listed=False, seen_after=False), cusip_switches=("2026-01-07",)))
    assert [e.delist_date for e in events] == ["2026-01-18"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py -k switch`
Expected: FAIL (`SecurityContext.__init__() got an unexpected keyword argument 'cusip_switches'`).

- [ ] **Step 3: Implement**

In `src/delist_detection/delistings.py`: change the import to
`from .trading_calendar import add_trading_days, previous_trading_day`; after
`DEREG_FALLBACK_AFTER_DAYS = 120 ...` add

```python
OWN_SWITCH_DAYS = 5                 # trading days between a Form 25 and the security's own CUSIP switch it removed
```

In `SecurityContext`, after the `tickers_between` field, add:

```python
    # The first fails row of each of the security's own CUSIPs after its first, ISO: a CUSIP switch on its own
    # line (a reverse split, a redomicile that kept the composite). A Form 25 filed at one while the security
    # trades on removed the old CUSIP, not the security (QGEN 2026, Acxiom/LiveRamp 2018).
    cusip_switches: tuple[str, ...] = ()
```

In `DelistingFinder`, before `def _class_conflict`, add:

```python
    @staticmethod
    def _at_own_switch(ctx: SecurityContext, filing_date: str) -> bool:
        """Whether one of the security's own CUSIP switches (`SecurityContext.cusip_switches`) lies within
        `OWN_SWITCH_DAYS` trading days of a Form 25's filing date."""
        day = date.fromisoformat(filing_date)
        lo = add_trading_days(day, -OWN_SWITCH_DAYS).isoformat()
        hi = add_trading_days(day, OWN_SWITCH_DAYS).isoformat()
        return any(lo <= d <= hi for d in ctx.cusip_switches)

```

In `find`'s main loop replace

```python
            if continued:
                before, after = exchanges_around(self.edgar, cik, filings, date.fromisoformat(sub.filing_date))
```

with

```python
            if continued:
                if self._at_own_switch(ctx, sub.filing_date):
                    continue        # the old CUSIP left the exchange as the security went on under its new one
                before, after = exchanges_around(self.edgar, cik, filings, date.fromisoformat(sub.filing_date))
```

In `src/delist_detection/pipeline.py`, replace the head of `_context_builder`:

```python
def _context_builder(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
                     answers: _IssuerAnswers) -> Callable[[Security, bool | None], SecurityContext]:
```

with

```python
def _cusip_switches(s: Security, ftd: FtdIndex, cusips: Sequence[str]) -> tuple[str, ...]:
    """The first sighting of each of the security's CUSIPs after its first (`history.cusip_sightings`): the days
    its own line switched CUSIP."""
    first: dict[str, str] = {}
    for x in cusip_sightings(s, ftd, cusips):
        first.setdefault(x.value, x.day)
    return tuple(sorted(first.values())[1:])


def _context_builder(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
                     answers: _IssuerAnswers, ftd: FtdIndex, sec_cusips: dict[str, list[str]]
                     ) -> Callable[[Security, bool | None], SecurityContext]:
```

In the `SecurityContext(...)` it builds, after the `tickers_between=...` argument, add
`cusip_switches=_cusip_switches(s, ftd, sec_cusips.get(s.sec_id, [])),`. In `_find_delistings`, replace
`security_context = _context_builder(securities, sightings, answers)` with
`security_context = _context_builder(securities, sightings, answers, ftd, sec_cusips)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass, 281 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/delistings.py src/delist_detection/pipeline.py tests/test_delistings.py
git commit -m "A Form 25 at the security's own CUSIP switch is no delisting while it trades on (sub-plan 5a, U6: QGEN, ACXM)"
```

---

### Task 10: Stage 4b, the line follow in the pipeline

Tier: standard (integration).

**Files:**
- Modify: `src/delist_detection/pipeline.py`, `src/delist_detection/contract.py`,
  `src/delist_detection/review_triage.py`
- Test: `tests/test_pipeline.py`, `tests/test_contract.py`, `tests/test_review_triage.py`,
  `tests/test_run_provenance.py`

**Interfaces:**
- Consumes: Task 7's `line_follow` names, Task 6's `Security.line_tickers`/`own_tickers`, Task 8's `cusip_job`,
  Task 9's `_context_builder`.
- Produces:
  - `pipeline._Lines(securities, resolutions, sec_cusips, renames={}, successors={}, review=[])`;
    `pipeline._follow_lines(ctx, securities, resolutions, era_by_key, sec_cusips, ftd, ftd_lo, answers) -> _Lines`;
    `pipeline.LINE_FOLLOWED = "line_followed"`, `pipeline.LINE_REFUSED = "line_follow_refused"`.
  - `pipeline._find_delistings(..., moved_on: Collection[str] = ())` (the FIGI lines with a line successor are not
    listed today).
  - `pipeline._contract(..., renames: Mapping[str, str] = {})`;
    `contract.id_change_rows(baseline, securities, changed_on, renames: Mapping[str, str] = {})`.
  - Review flags `line_followed` and `line_follow_refused` (info) in `review_triage.CATALOG`.
  - The manifest gains the stage "line follow".
  - Task 11 reads `lines.successors` (sec_id → `LineSuccessor`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_contract.py`:

```python


def test_id_changes_name_the_figi_a_line_follow_folded_a_placeholder_into():
    """Sub-plan 5a (FTR): CIK 20520 holds two FIGI lines, Frontier's and the post-bankruptcy FYBR, so the
    issuer-and-class rule names none; the line follow's own rename names the FIGI."""
    baseline = [_sec_row("CIK20520-COMMON", "20520", "placeholder")]
    now = [_sec_row("BBGFTR00001", "20520", "handoff"), _sec_row("BBG010MVVVW7", "20520", "cusip")]
    assert id_change_rows(baseline, now, "2026-09-25") == []
    assert id_change_rows(baseline, now, "2026-09-25", {"CIK20520-COMMON": "BBGFTR00001"}) == [
        {"old_sec_id": "CIK20520-COMMON", "new_sec_id": "BBGFTR00001", "changed_on": "2026-09-25",
         "issuer_cik": "20520", "share_class": "COMMON"}]
    assert id_change_rows(baseline, now, "2026-09-25", {"CIK20520-COMMON": "BBGGONE0001"}) == []
```

In `tests/test_review_triage.py`, `test_severities_follow_the_rulings`, replace `"handoff_continuation"}` with
`"handoff_continuation", "line_followed", "line_follow_refused"}`.

In `tests/test_run_provenance.py`, replace `"dead before first sighting", "handoff notice dates"}` with
`"dead before first sighting", "handoff notice dates", "line follow"}`.

Append to `tests/test_pipeline.py`:

```python


# --- sub-plan 5a, stage 4b: a line followed past the observations (pipeline._follow_lines) ---

LINE_F25 = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>New York Stock Exchange LLC</entityName>"
            "</exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
            "<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision></notificationOfRemoval>")
RS_OLD, RS_NEW = "11111A101", "11111A200"


def _weekly(start, n):
    """`n` Mondays from the Monday ISO `start`."""
    day = date.fromisoformat(start)
    return [(day + timedelta(weeks=i)).isoformat() for i in range(n)]


def _priced(symbol, cusip, desc, dates, first_price=10.0):
    return [FtdRow(d, cusip, symbol, desc, round(first_price + i * 0.01, 2)) for i, d in enumerate(dates)]


def _rs_new_rows(symbol="RS", until=91, desc="REVERSE SPLIT CO NEW"):
    """RS's new CUSIP: its first-day RSZZZZ row on 2012-09-25, then weekly rows from 2012-10-01 (91 weeks: to
    2014-06-16)."""
    return [FtdRow("2012-09-25", RS_NEW, "RSZZZZ", desc, 0.01),
            *_priced(symbol, RS_NEW, desc, _weekly("2012-10-01", until), 40.0)]


SPLIT_8K = EdgarSubmission("0000004242-12-000031", "8-K", "2012-09-24", "2012-09-24", "5.03,9.01", "k.htm")
LATER_10Q = EdgarSubmission("0000004242-13-000004", "10-Q", "2013-02-08", "2012-12-31", "", "q.htm")
MERGER_8K = EdgarSubmission("0000004242-14-000020", "8-K", "2014-06-10", "2014-06-10", "2.01,3.01,5.01,9.01", "m.htm")
MERGER_F25 = EdgarSubmission("0000876661-14-000300", "25-NSE", "2014-06-10", "", "", "primary_doc.xml")


def _line_run(fake_edgar, tmp_path, *, filings, figi, new_rows, old_figi=True, listings=(), id_baseline=(),
              extra_obs=()):
    """RS (CIK 4242), observed 2008-2009, its old CUSIP failing weekly under RS until 2012-09-17, then `new_rows`;
    `figi`: OpenFIGI's answers beyond the old CUSIP's (BBGRS01 unless `old_figi` is False)."""
    fake_edgar.company_map["RS"] = {"cik_str": 4242, "ticker": "RS", "title": "REVERSE SPLIT CO"}
    fake_edgar.submissions_by_cik[4242] = list(filings)
    fake_edgar.listings[4242] = list(listings)
    fake_edgar.raws["0000876661-14-000300"] = LINE_F25
    fake_edgar.texts["0000004242-14-000020"] = ("Item 3.01. trading suspended prior to the opening of trading on "
                                                "June 20, 2014 " + "x" * 300)
    obs = [Observation("RS", d, "REVERSE SPLIT CO", cik=4242) for d in ("2008-01-16", "2008-06-30", "2009-06-08")]
    rows = _priced("RS", RS_OLD, "REVERSE SPLIT CO", _weekly("2008-01-07", 247)) + list(new_rows)
    answers = dict(figi)
    if old_figi:
        answers[("ID_CUSIP", RS_OLD)] = _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO")
    index, clients = _index_clients(fake_edgar, [*obs, *extra_obs], rows, answers)
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, id_baseline=id_baseline)
    return {name: read_table(name, table_path(tmp_path, name)) for name in (
        "securities", "cusip_history", "ticker_history", "delistings", "contract_delistings", "id_changes",
        "review_summary")}


def _flag_count(t, flag):
    return next((r["rows"] for r in t["review_summary"] if r["flag"] == flag), "0")


def test_a_reverse_split_after_the_observations_stop_is_followed_to_the_lines_real_ending(fake_edgar, tmp_path):
    """RS's observations stop in 2009; in 2012 a reverse split (8-K 5.03) gives it a new CUSIP under the same
    ticker, with the same composite; it merges in 2014, a Form 25 more than 400 days after the old CUSIP's last
    row. Followed, the line is one security with both CUSIPs, and its one delisting is the 2014 merger."""
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, LATER_10Q, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    assert [r["sec_id"] for r in t["securities"]] == ["BBGRS01"]
    assert [r["cusip"] for r in t["cusip_history"]] == [RS_OLD, RS_NEW]
    assert [(r["sec_id"], r["delist_date"], r["bucket"]) for r in t["delistings"]] == [
        ("BBGRS01", "2014-06-20", "merger")]
    assert [(r["ticker"], r["valid_from"], r["valid_to"]) for r in t["ticker_history"]] == [
        ("RS", "2008-01-07", "2014-06-19")]
    assert _flag_count(t, "line_followed") == "1"


def test_a_bankruptcy_before_the_switch_keeps_the_line_where_it_was(fake_edgar, tmp_path):
    """Must not change (UAL 2006): an 8-K item 1.03 within 180 days before the new CUSIP's first row means the
    plan cancelled the old shares; the new CUSIP is not the old line's."""
    bankrupt = EdgarSubmission("0000004242-12-000020", "8-K", "2012-06-01", "2012-06-01", "1.03", "b.htm")
    t = _line_run(fake_edgar, tmp_path, filings=[bankrupt, SPLIT_8K, LATER_10Q, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    assert [r["cusip"] for r in t["cusip_history"]] == [RS_OLD]
    assert "2014-06-20" not in {r["delist_date"] for r in t["delistings"]}
    assert _flag_count(t, "line_follow_refused") == "1"


def test_a_registrant_that_merged_out_at_the_switch_is_not_followed(fake_edgar, tmp_path):
    """Must not change (UNIT 2025, R1 before R2): no periodic report for a period after the switch."""
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    assert [r["cusip"] for r in t["cusip_history"]] == [RS_OLD]
    assert _flag_count(t, "line_follow_refused") == "1"


def test_a_new_cusip_another_issuers_security_holds_is_never_followed(fake_edgar, tmp_path):
    """Must not change (new LMCA 2013): another issuer's observed line holds the new CUSIP under the ticker."""
    fake_edgar.company_map["RSX"] = {"cik_str": 5353, "ticker": "RSX", "title": "OTHER CO"}
    fake_edgar.submissions_by_cik[5353] = []
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, LATER_10Q, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGOTHER1", "RS", "OTHER CO")},
                  new_rows=_rs_new_rows(desc="OTHER CO"),
                  extra_obs=[Observation("RS", d, "OTHER CO", cik=5353) for d in ("2013-06-28", "2013-12-31")])
    assert {r["sec_id"]: r["cusip"] for r in t["cusip_history"]} == {"BBGRS01": RS_OLD, "BBGOTHER1": RS_NEW}
    assert _flag_count(t, "line_followed") == "0"


def test_a_rename_on_the_same_cusip_keeps_a_placeholder_listed_under_its_new_ticker(fake_edgar, tmp_path):
    """A placeholder renamed on the same CUSIP (RS -> RSNW, as HSC became NVRI): its line ticker makes it listed
    today (EDGAR lists RSNW), so it has no ending and an open RSNW range."""
    rows = _priced("RSNW", RS_OLD, "REVERSE SPLIT CO", _weekly("2012-10-01", 700), 40.0)
    t = _line_run(fake_edgar, tmp_path, filings=[LATER_10Q], figi={}, new_rows=rows, old_figi=False,
                  listings=[("RSNW", "NYSE")])
    assert [r["sec_id"] for r in t["securities"]] == ["CIK4242-COMMON"]
    assert t["contract_delistings"] == []
    assert [(r["ticker"], r["valid_to"]) for r in t["ticker_history"]] == [("RS", "2012-09-30"), ("RSNW", "")]


def test_a_placeholder_folds_into_the_figi_line_its_new_cusip_names(fake_edgar, tmp_path):
    """R2 for a placeholder: OpenFIGI knows no US line for the old CUSIP but names one for the new: the
    placeholder becomes that FIGI line, and contract/id_changes.csv says so by name."""
    baseline = [{"sec_id": "CIK4242-COMMON", "issuer_cik": "4242", "share_class": "COMMON", "name": "RS",
                 "security_type": "", "observed": "true", "figi_source": "placeholder"}]
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, LATER_10Q, MERGER_8K, MERGER_F25],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows(), old_figi=False, id_baseline=baseline)
    assert [(r["sec_id"], r["figi_source"]) for r in t["securities"]] == [("BBGRSNEW1", "handoff")]
    assert [(r["old_sec_id"], r["new_sec_id"]) for r in t["id_changes"]] == [("CIK4242-COMMON", "BBGRSNEW1")]
    assert [(r["sec_id"], r["delist_date"]) for r in t["delistings"]] == [("BBGRSNEW1", "2014-06-20")]
    assert (_flag_count(t, "no_figi"), _flag_count(t, "line_followed")) == ("0", "1")    # its items moved with it


def test_a_form25_at_the_lines_own_switch_while_it_trades_on_leaves_no_ending(fake_edgar, tmp_path):
    """QGEN 2026 / Acxiom 2018 (U6): the line, listed today, switched to a new CUSIP of the same composite as a
    25-NSE removed the old one; that Form 25 is no delisting."""
    switch_f25 = EdgarSubmission("0000876661-12-000300", "25-NSE", "2012-09-24", "", "", "primary_doc.xml")
    fake_edgar.raws["0000876661-12-000300"] = LINE_F25
    listed = {"data": [{"figi": "BBGRS02", "compositeFIGI": "BBGRS01", "exchCode": "UN", "ticker": "RS",
                        "name": "REVERSE SPLIT CO"}]}
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, switch_f25, LATER_10Q],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRS01", "RS", "REVERSE SPLIT CO"),
                        ("COMPOSITE_ID_BB_GLOBAL", "BBGRS01"): listed},
                  new_rows=_rs_new_rows(until=700), listings=[("RS", "NYSE")])
    assert t["delistings"] == [] and t["contract_delistings"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_contract.py tests/test_review_triage.py tests/test_run_provenance.py`
Expected: FAIL: the six stage tests that need the stage (the "another issuer holds" test passes either way), the
contract test (`id_change_rows() takes 3 positional arguments`), the severity and the manifest-stage tests.

- [ ] **Step 3: The id_changes rename by name, and the catalog**

In `src/delist_detection/contract.py`, replace `id_change_rows`' signature and docstring head

```python
def id_change_rows(baseline: Sequence[Mapping[str, str]], securities: Sequence[Mapping[str, str]],
                   changed_on: str) -> list[dict[str, str]]:
    """contract/id_changes.csv (decision 7): each placeholder of the baseline run
    (its securities.csv rows) that this run no longer has and whose issuer and
    class exactly one FIGI security of this run holds. Not cumulative: git keeps
    the earlier files."""
```

with

```python
def id_change_rows(baseline: Sequence[Mapping[str, str]], securities: Sequence[Mapping[str, str]],
                   changed_on: str, renames: Mapping[str, str] = {}) -> list[dict[str, str]]:
    """contract/id_changes.csv (decision 7): each placeholder of the baseline run
    (its securities.csv rows) that this run no longer has and that a line
    follow folded into a FIGI security of this run (`renames`: old sec_id -> new,
    pipeline stage 4b; FTR's CIK holds a later FIGI line too), else whose issuer
    and class exactly one FIGI security of this run holds. Not cumulative: git
    keeps the earlier files."""
```

and replace

```python
        found = figis.get((b["issuer_cik"], b["share_class"]), set())
        if len(found) == 1:
```

with

```python
        found = {renames[b["sec_id"]]} if renames.get(b["sec_id"]) in now else \
            figis.get((b["issuer_cik"], b["share_class"]), set())
        if len(found) == 1:
```

In `src/delist_detection/review_triage.py`, insert after the line
`    # --- info: a less precise source, nothing suggests it is wrong ---`:

```python
    "line_followed": FlagInfo(
        "info", "The line follow (pipeline stage 4b) found the security trading on past its observations under a "
                "new CUSIP or ticker; the reason names the step, the filing that states it and what R2 made of it "
                "(the same security, a placeholder folded into a FIGI line, or a line continued by another FIGI).",
        "Nothing unless the step looks wrong; read the filing the reason names, and pin the observations' sec_id "
        "if the new rows are another security's."),
    "line_follow_refused": FlagInfo(
        "info", "A step of the security's line in the fails rows was not followed; after the colon, why "
                "(bankruptcy, otc_move, name, class, merged_out, other_registrant, no_filing, unsettled, "
                "other_issuer). The security's answer is the one it had without the step.",
        "Nothing unless the security did go on under the new CUSIP or ticker as the same line; then pin the "
        "observations' sec_id."),
```

- [ ] **Step 4: The stage**

In `src/delist_detection/pipeline.py`:

Change the imports:
- `from collections.abc import Callable, Iterable, Mapping, Sequence` →
  `from collections.abc import Callable, Collection, Iterable, Mapping, Sequence`;
- `from .figi_resolution import is_placeholder, share_class_from_name` →
  `from .figi_resolution import FigiCandidate, is_placeholder, share_class_from_name`;
- replace `from .listing_status import issuer_exchange, listed_today, listing_answers` with

```python
from .line_follow import (
    ATTACH, FOLD, MAX_ROUNDS, REFUSED, SUCCESSOR_FORMS, SWITCH, LineEnd, LineStep, LineSuccessor, candidate_steps,
    composites, corroborate, decide, eightks_near, is_line_symbol, line_end, name_on, other_registrant, text_cusips,
    text_symbols,
)
from .listing_status import edgar_lists, issuer_exchange, listed_today, listing_answers
```

- in the `from .security_master import (` list, add `cusip_job` after `cusip_handoffs`.

Insert after the `_security_cusips` function (before `def _cusip_switches`):

```python
LINE_FOLLOWED, LINE_REFUSED = "line_followed", "line_follow_refused"


@dataclass
class _Lines:
    """Stage 4b's answer (`_follow_lines`): the securities, each era's resolution and each security's CUSIPs after
    the line follow; the placeholders folded into a FIGI line (old sec_id -> the FIGI); the FIGI lines another
    composite continues (sec_id -> `line_follow.LineSuccessor`); and the review items."""
    securities: dict[str, Security]
    resolutions: dict[str, EraResolution]
    sec_cusips: dict[str, list[str]]
    renames: dict[str, str] = field(default_factory=dict)
    successors: dict[str, LineSuccessor] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)


class _IssuerReads:
    """The EDGAR reads the line follow makes, each issuer's once: its submissions JSON, its filing list and an
    8-K's text. A read that fails is no answer (None, [], ""); a refusal (`fatal.FATAL`) stops the run."""

    def __init__(self, edgar) -> None:
        self.edgar, self._subs, self._filings = edgar, {}, {}

    @staticmethod
    def _safe(fn, *args, default):
        try:
            return fn(*args)
        except FATAL:
            raise
        except requests.RequestException:
            return default

    def sub(self, cik: int):
        if cik not in self._subs:
            self._subs[cik] = self._safe(self.edgar.submissions, cik, default=None)
        return self._subs[cik]

    def filings(self, cik: int) -> list:
        if cik not in self._filings:
            self._filings[cik] = self._safe(self.edgar.recent_filings, cik, default=[])
        return self._filings[cik]

    def text(self, cik: int, f) -> str:
        return self._safe(self.edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="") or ""


def _cusip_holders(sec_cusips: Mapping[str, Sequence[str]]) -> dict[str, set[str]]:
    holders: dict[str, set[str]] = defaultdict(set)
    for sid, cusips in sec_cusips.items():
        for c in cusips:
            holders[c].add(sid)
    return holders


def _text_sources(reads: _IssuerReads, s: Security, end: LineEnd) -> tuple[set[str], set[str]]:
    """The tickers and CUSIPs the issuer's own 8-Ks around a line's end name as the stock's new ones (APY's
    ChampionX "CHX", Liz Claiborne's "316645100" and "FNP"): read only when one of them is an 8-K item 5.03 or
    3.03 or an 8-K12B/8-K12G3, within `line_follow.FILING_DAYS` of the line's settled last row."""
    day = date.fromisoformat(end.settled)
    near = [f for f in eightks_near(reads.filings(s.issuer_cik), day)
            if f.form in SUCCESSOR_FORMS or {"5.03", "3.03"} & f.item_set]
    texts = [reads.text(s.issuer_cik, f) for f in near]
    return {t for t in text_symbols(texts) if is_line_symbol(t)} - s.own_tickers(), text_cusips(texts)


def _fold(out: _Lines, p: str, x: str, cand: FigiCandidate, step: LineStep, tickers: dict[str, set[str]]) -> None:
    """Fold placeholder `p` into the FIGI line `x` its new CUSIP's composite names: its eras resolve to `x`
    (source `handoff`, as a CUSIP handoff joins a line in stage 3), its CUSIPs and line tickers join `x`'s, and
    every earlier rename to `p` now points at `x`."""
    for e in out.securities[p].eras:
        out.resolutions[e.key] = replace(out.resolutions[e.key], sec_id=x, source="handoff", candidate=cand, flags=())
    out.sec_cusips[x] = list(dict.fromkeys([*out.sec_cusips.get(x, []), *out.sec_cusips.pop(p, []), step.new_cusip]))
    tickers[x] = tickers.get(x, set()) | tickers.pop(p, set()) | {step.symbol}
    for old, now in list(out.renames.items()):
        if now == p:
            out.renames[old] = x
    out.renames[p] = x


def _follow_lines(ctx: _RunContext, securities: dict[str, Security], resolutions: dict[str, EraResolution],
                  era_by_key: dict[str, TickerEra], sec_cusips: dict[str, list[str]], ftd: FtdIndex, ftd_lo: date,
                  answers: _IssuerAnswers) -> _Lines:
    """4b. Each security's line followed past its observations (`line_follow`; spec 2026-10-03-diagnosis-truth-
    fixes 3 "5a", rulings R1 and R2), before the Form 25 search reads its sightings. A round finds each line's
    next step in the fails rows (`candidate_steps`: a new CUSIP under the line's ticker, or a ticker of the issuer
    EDGAR lists today or its 8-K text names; or the same CUSIP under a new ticker), loads the new CUSIPs' rows to
    the run date, asks OpenFIGI for their composites in one batch, checks each step against the issuer's filings
    (`corroborate`) and applies R2 (`decide`): the same security takes the new CUSIP and ticker; a placeholder
    folds into the FIGI line its new CUSIP names (the securities are rebuilt, `build_securities`); a FIGI line
    whose new CUSIP has its own composite keeps its CUSIPs and records that composite as its line successor for
    stage 9. A line that moved is followed again in the next round, up to `MAX_ROUNDS` (WIN's two reverse
    splits). Every step followed or refused is an info review item (`line_followed`, `line_follow_refused:<why>`);
    a read that rested on a failed request or a stale copy, a `resolution_degraded` one."""
    clients, edgar = ctx.clients, ctx.clients.edgar
    search = getattr(edgar, "full_text_search", None)
    reads = _IssuerReads(edgar)
    mark = ctx.meter.start()
    out = _Lines(dict(securities), dict(resolutions), {k: list(v) for k, v in sec_cusips.items()})
    tickers: dict[str, set[str]] = {sid: set(s.line_tickers) for sid, s in securities.items()}

    def own(sid: str) -> set[str]:
        return out.securities[sid].own_tickers() | tickers.get(sid, set())

    todo = sorted(sid for sid, s in out.securities.items() if s.issuer_cik is not None)
    extra: dict[str, set[str]] = {}
    for sid in todo:
        sub = reads.sub(out.securities[sid].issuer_cik)
        listed = [normalize_ticker(t) for t in (sub.get("tickers") or [])] if isinstance(sub, dict) else []
        extra[sid] = {t for t in listed if is_line_symbol(t)} - own(sid)
    # every line's tickers, their first-day ZZZZ and post-split D spellings and the issuers' other tickers, to the
    # run date (stage 1 loaded the eras' tickers only to 400 days past their last observation)
    spellings = {t.replace("-", "") + suffix for sid in todo for t in own(sid) for suffix in ("", "ZZZZ", "D")}
    ftd.extend(clients.ftd_client, ftd_lo, ctx.as_of, symbols=spellings | {t for v in extra.values() for t in v})
    named: dict[str, set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()
    for round_no in range(1, MAX_ROUNDS + 1):
        holders = _cusip_holders(out.sec_cusips)

        def steps_of(sid: str) -> list[LineStep]:
            return candidate_steps(sid, out.sec_cusips.get(sid, []), own(sid), ftd, holders=holders,
                                   extra_symbols=extra.get(sid, ()), extra_cusips=named.get(sid, ()))

        steps = {sid: steps_of(sid) for sid in todo}
        new_symbols: set[str] = set()
        if round_no == 1:
            for sid in todo:
                end = line_end(out.sec_cusips.get(sid, []), own(sid), ftd)
                if steps[sid] or end is None or end.last >= (ctx.as_of - timedelta(days=30)).isoformat():
                    continue
                symbols, cusips = _text_sources(reads, out.securities[sid], end)
                extra[sid] |= symbols
                named[sid] |= cusips
                new_symbols |= symbols
        new_cusips = {st.new_cusip for v in steps.values() for st in v if st.kind == SWITCH}
        new_cusips |= {c for v in named.values() for c in v}
        if new_cusips or new_symbols:
            ftd.extend(clients.ftd_client, ftd_lo, ctx.as_of, cusips=new_cusips, symbols=new_symbols)
            steps = {sid: steps_of(sid) for sid in todo}
        switch_cusips = sorted({v[0].new_cusip for v in steps.values() if v and v[0].kind == SWITCH})
        figi_answers = dict(zip(switch_cusips, clients.figi.map([cusip_job(c) for c in switch_cusips]))) \
            if switch_cusips else {}
        moved: set[str] = set()
        for sid in todo:
            if not steps[sid] or sid not in out.securities:
                continue
            step, s = steps[sid][0], out.securities[sid]
            cik = s.issuer_cik
            watch = DegradedWatch()
            first = date.fromisoformat(step.first)
            evidence, refused = corroborate(
                step, filings=reads.filings(cik), sub=reads.sub(cik), share_class=s.share_class,
                text_of=lambda f, cik=cik: reads.text(cik, f), as_of=ctx.as_of,
                listed_now=lambda: edgar_lists(edgar, cik, sorted(own(sid) | {step.symbol})),
                other_registrant=lambda: other_registrant(search, edgar, name=name_on(reads.sub(cik), first, s.name),
                                                          day=first, cik=cik, own_tickers=own(sid)))
            what = f"{step.old_cusip} -> {step.new_cusip} under {step.symbol} from {step.first}"
            decision = None if refused else decide(
                step, s, composites(figi_answers[step.new_cusip]) if step.kind == SWITCH else None, out.securities)
            if decision is not None and decision.kind == REFUSED:
                refused = decision.why
            if watch.tripped():
                out.review.append(degraded_item(sid, step.symbol, cik, f"the line follow ({what})",
                                                "; run again once SEC answers", last_seen=step.old_last))
            if refused:
                counts[f"refused:{refused}"] += 1
                out.review.append(ReviewItem(sid, step.symbol, cik, f"{LINE_REFUSED}:{refused}",
                                             f"{what}: not followed ({refused})", last_seen=step.old_last))
                continue
            counts[decision.kind] += 1
            if decision.kind == ATTACH:
                if step.kind == SWITCH:
                    out.sec_cusips.setdefault(sid, []).append(step.new_cusip)
                tickers.setdefault(sid, set()).add(step.symbol)
                moved.add(sid)
                result = "the same security"
            elif decision.kind == FOLD:
                _fold(out, sid, decision.composite, decision.candidate, step, tickers)
                moved.add(decision.composite)
                result = f"folded into {decision.composite}"
            else:
                out.successors[sid] = LineSuccessor(sid, decision.composite, decision.candidate, step, evidence)
                result = f"continued by {decision.composite}"
            out.review.append(ReviewItem(sid, step.symbol, cik, LINE_FOLLOWED, f"{what} ({evidence}): {result}",
                                         last_seen=step.old_last))
        if any(sid in out.renames for sid in out.securities):
            out.securities = build_securities(out.resolutions, era_by_key, answers.issuers)
        for sid, s in out.securities.items():
            s.line_tickers = frozenset(tickers.get(sid, set()) - {e.ticker for e in s.eras})
        todo = sorted(sid for sid in moved if sid in out.securities)
        if not todo:
            break
    ctx.log(f"line follow: {dict(sorted(counts.items()))}; {len(out.renames)} placeholders folded, "
            f"{len(out.successors)} line successors")
    ctx.meter.done("line follow", mark)
    return out


```

In `_find_delistings`, replace its signature and docstring head

```python
def _find_delistings(ctx: _RunContext, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
                     ftd: FtdIndex, answers: _IssuerAnswers) -> _DelistingSearch:
    """5. Every delisting of every security (`DelistingFinder`), in sec_id order.
    A security whose search fails becomes an `error` review item, not an aborted
    run; only a fatal exception (`fatal.FATAL`) stops it."""
```

with

```python
def _find_delistings(ctx: _RunContext, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
                     ftd: FtdIndex, answers: _IssuerAnswers, moved_on: Collection[str] = ()) -> _DelistingSearch:
    """5. Every delisting of every security (`DelistingFinder`), in sec_id order.
    A security whose search fails becomes an `error` review item, not an aborted
    run; only a fatal exception (`fatal.FATAL`) stops it. A FIGI line another
    composite continues (`moved_on`: stage 4b's line successors) is not listed
    today: its line went on under that composite."""
```

and replace `        | superseded_placeholders(securities)` with
`        | superseded_placeholders(securities) | frozenset(moved_on)`.

In `_contract`, replace its signature

```python
def _contract(ctx: _RunContext, read: Tables, verdicts: Verdicts, payouts: _Payouts, successor_ids: set[str],
              overrides: Overrides, id_baseline: Sequence[Mapping[str, str]]) -> dict[str, list[dict]]:
```

with

```python
def _contract(ctx: _RunContext, read: Tables, verdicts: Verdicts, payouts: _Payouts, successor_ids: set[str],
              overrides: Overrides, id_baseline: Sequence[Mapping[str, str]],
              renames: Mapping[str, str] = {}) -> dict[str, list[dict]]:
```

its docstring's last line `and the placeholders of \`id_baseline\` (a securities.csv) that now hold a FIGI."""` with

```
    and the placeholders of `id_baseline` (a securities.csv) that now hold a FIGI
    (`renames`: stage 4b's folds, by name, whatever other FIGI lines the issuer has)."""
```

and `"id_changes": id_change_rows(id_baseline, read.securities, ctx.as_of.isoformat()),` with
`"id_changes": id_change_rows(id_baseline, read.securities, ctx.as_of.isoformat(), renames),`.

In `_run`, replace

```python
    sec_cusips = _security_cusips(ctx, securities, resolutions, ftd, ftd_lo)                        # 4
    search = _find_delistings(ctx, securities, sec_cusips, ftd, answers)                            # 5
```

with

```python
    sec_cusips = _security_cusips(ctx, securities, resolutions, ftd, ftd_lo)                        # 4
    lines = _follow_lines(ctx, securities, resolutions, era_by_key, sec_cusips, ftd, ftd_lo, answers)  # 4b
    securities, resolutions, sec_cusips = lines.securities, lines.resolutions, lines.sec_cusips
    # a folded placeholder's review items follow it to its FIGI line, where it holds a FIGI after all
    review = [replace(r, sec_id=lines.renames.get(r.sec_id, r.sec_id)) for r in review + lines.review
              if not (r.flag == "no_figi" and r.sec_id in lines.renames)]
    search = _find_delistings(ctx, securities, sec_cusips, ftd, answers, set(lines.successors))      # 5
```

and

```python
    tables.update(_contract(ctx, _as_read(tables), verdicts, payouts, set(successors.added), overrides,
                            id_baseline))                                                          # 10g
```

with

```python
    tables.update(_contract(ctx, _as_read(tables), verdicts, payouts, set(successors.added), overrides,
                            id_baseline, lines.renames))                                           # 10g
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass, 281 xfailed. Every existing pipeline test runs the stage too (FakeEdgar has no
`full_text_search`; the fake OpenFIGI answers "No identifier found." for a CUSIP it does not know): none may change.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/pipeline.py src/delist_detection/contract.py src/delist_detection/review_triage.py tests/test_pipeline.py tests/test_contract.py tests/test_review_triage.py tests/test_run_provenance.py
git commit -m "Stage 4b: each security's line followed past its observations; folds named in id_changes (sub-plan 5a, U1)"
```

---

### Task 11: U7, a line successor in stage 9

Tier: standard (integration).

**Files:**
- Modify: `src/delist_detection/added_securities.py`, `src/delist_detection/pipeline.py`,
  `src/delist_detection/review_triage.py`
- Test: `tests/test_pipeline.py`, `tests/test_review_triage.py`

**Interfaces:**
- Consumes: Task 10's `_Lines.successors` (sec_id → `LineSuccessor`).
- Produces:
  - `added_securities.AddedLineSuccessor(security, ticker, first: str, rows: list[FtdRow] = [])`, source "ftd",
    span = first to the last of `rows`.
  - `pipeline.LINE_FOLLOW = "line_follow"`, `pipeline.LINE_CONTINUATION = "line_continuation"`;
    `_Successors.rebucketed: dict[DelistingKey, str]`; `pipeline._line_successor_links(delistings, securities,
    acquirers, line_successors, ftd, found)`.
  - `pipeline._find_successors(ctx, delistings, securities, sightings, acquirers, line_successors={}, ftd=None)`:
    line successors first, then the in-run and 8-K12B searches for the delistings still without one.
  - `_link_successors` rewrites a rebucketed row as an exchange transfer (code 304, flag `line_continuation`).
  - Review flag `line_continuation` (info).

- [ ] **Step 1: Write the failing tests**

In `tests/test_review_triage.py`, `test_severities_follow_the_rulings`, replace
`"handoff_continuation", "line_followed", "line_follow_refused"}` with
`"handoff_continuation", "line_followed", "line_follow_refused", "line_continuation"}`.

Append to `tests/test_pipeline.py` (after Task 10's tests, whose helpers these use):

```python


LATER_10K = EdgarSubmission("0000004242-13-000011", "10-K", "2013-06-14", "2013-03-31", "", "k10.htm")


def test_a_figi_line_whose_new_cusip_has_its_own_figi_ends_as_a_continuation_to_it(fake_edgar, tmp_path):
    """U7 (DYN 2010, R2): the reverse split's new CUSIP has its own composite, so the old FIGI line ends at the
    switch, an exchange transfer whose successor is the new line, which the run adds as a security of its own."""
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, LATER_10Q, LATER_10K],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    assert {(r["sec_id"], r["observed"]) for r in t["securities"]} == {("BBGRS01", "true"), ("BBGRSNEW1", "false")}
    [d] = t["delistings"]
    assert (d["sec_id"], d["bucket"], d["successor_sec_id"]) == ("BBGRS01", "exchange_transfer", "BBGRSNEW1")
    assert "successor by line follow" in d["reason"]
    [c] = t["contract_delistings"]
    assert (c["sec_id"], c["continuation"], c["successor_sec_id"]) == ("BBGRS01", "true", "BBGRSNEW1")
    assert ("BBGRSNEW1", "RS", "2012-09-25") in {(r["sec_id"], r["ticker"], r["valid_from"])
                                                 for r in t["ticker_history"]}


def test_an_unknown_form25_at_the_lines_switch_becomes_the_continuation(fake_edgar, tmp_path):
    """U7 (GTES 2026): the Form 25 filed at a redomicile that gave the line a CUSIP with its own composite was
    classified `unknown`; with the line successor it is the exchange transfer to it."""
    switch_f25 = EdgarSubmission("0000876661-12-000300", "25-NSE", "2012-09-24", "", "", "primary_doc.xml")
    fake_edgar.raws["0000876661-12-000300"] = LINE_F25
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, switch_f25, LATER_10Q],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    [d] = t["delistings"]
    assert (d["bucket"], d["crsp_code"], d["successor_sec_id"]) == ("exchange_transfer", "304", "BBGRSNEW1")
    assert "line_continuation" in d["review_flags"].split(";")
    assert t["contract_delistings"][0]["continuation"] == "true"


def test_a_line_successor_is_never_added_for_an_ending_that_does_not_need_it(fake_edgar, tmp_path):
    """Must not change (WCN, AAN): a merger at the switch keeps its kind and takes no line successor, and the
    composite is not added to the run."""
    merger_8k = EdgarSubmission("0000004242-12-000040", "8-K", "2012-09-24", "2012-09-24", "2.01,3.01,5.01,9.01",
                                "m.htm")
    merger_f25 = EdgarSubmission("0000876661-12-000300", "25-NSE", "2012-09-24", "", "", "primary_doc.xml")
    fake_edgar.raws["0000876661-12-000300"] = LINE_F25
    t = _line_run(fake_edgar, tmp_path, filings=[SPLIT_8K, merger_8k, merger_f25, LATER_10Q],
                  figi={("ID_CUSIP", RS_NEW): _figi_answer("BBGRSNEW1", "RS", "REVERSE SPLIT CO")},
                  new_rows=_rs_new_rows())
    [d] = t["delistings"]
    assert (d["bucket"], d["successor_sec_id"]) == ("merger", "")
    assert "BBGRSNEW1" not in {r["sec_id"] for r in t["securities"]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_review_triage.py -k "own_figi or unknown_form25_at or never_added or severities"`
Expected: FAIL (no successor on the old line; the GTES-like row stays `unknown`; `line_continuation` is not in the
catalog). The third test may already pass; it pins behaviour.

- [ ] **Step 3: Implement**

In `src/delist_detection/added_securities.py`, replace the module docstring with

```python
"""The securities a run adds that no observation names -- a merger's acquirer
(`acquirers.find_acquirer`), an exchange transfer's successor
(`successors.successor_from_8k12b`) and a FIGI line's successor the line follow
found (`line_follow`) -- each with the one ticker_history row the run can give it."""
```

and insert before `@dataclass\nclass AddedSuccessor(AddedSecurity):`:

```python
@dataclass
class AddedLineSuccessor(AddedSecurity):
    """A FIGI line's successor the line follow found (pipeline stage 4b; R2: the line's new CUSIP has its own
    composite): seen from the step's first row (`first`) through that CUSIP's fails rows under the line's new
    ticker (`rows`)."""
    first: str
    rows: list[FtdRow] = field(default_factory=list)
    source: ClassVar[str] = "ftd"

    def span(self) -> tuple[str, str]:
        dates = sorted({self.first, *(r.date for r in self.rows)})
        return dates[0], dates[-1]


```

In `src/delist_detection/review_triage.py`, insert before `    "line_follow_refused": FlagInfo(`:

```python
    "line_continuation": FlagInfo(
        "info", "An unknown delisting at the security's own CUSIP switch is an exchange transfer to its line "
                "successor: the line follow (stage 4b) found the new CUSIP trading on as a FIGI of its own (R2), "
                "and the reason names the filing that states the step.",
        "Nothing unless the filing says holders were paid or got another ratio; then the row is a merger."),
```

In `src/delist_detection/pipeline.py`:

- imports: `from .added_securities import AddedAcquirer, AddedSecurity, AddedSuccessor` →
  `from .added_securities import AddedAcquirer, AddedLineSuccessor, AddedSecurity, AddedSuccessor`; in the
  `from .handoffs import (` list add `CONTINUATION_CODE` first; replace the `from .successors import (` block with

```python
from .successors import (
    SUCCESSOR_AFTER_DAYS, SUCCESSOR_BEFORE_DAYS, SecurityStart, successor_from_8k12b, successor_in_run,
    successor_query, successor_search_args,
)
```

- replace the `_Successors` dataclass with:

```python
LINE_FOLLOW, LINE_CONTINUATION = "line_follow", "line_continuation"


@dataclass
class _Successors:
    """Stage 9's answer: each delisting's successor (`links`, by delisting: the
    successor's sec_id and how the run found it -- "line_follow" for stage 4b's
    line successor, "same_issuer" or "same_ticker" for a security of the run,
    None for an 8-K12B hit), the successors the run adds as securities of their
    own, the review items, the delistings whose own row a degraded search answer
    flags, and the `unknown` rows a line successor rewrites as continuations
    (`rebucketed`, by delisting: the new reason)."""
    links: dict[DelistingKey, tuple[str, str | None]] = field(default_factory=dict)
    added: dict[str, AddedSecurity] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)
    degraded: list[DelistingKey] = field(default_factory=list)
    rebucketed: dict[DelistingKey, str] = field(default_factory=dict)


def _line_successor_links(delistings: list[Delisting], securities: dict[str, Security],
                          acquirers: dict[str, AddedSecurity], line_successors: Mapping[str, LineSuccessor],
                          ftd: FtdIndex, found: _Successors) -> None:
    """A FIGI line another composite continues (stage 4b's `line_successors`, R2): each of its delistings that
    still needs a successor (`successor_unknown`) or a kind (`unknown`: GTES 2026's Form 25 at its redomicile),
    whose last trade (else Form 25 filing date, else delisting date) lies within [-SUCCESSOR_BEFORE_DAYS,
    +SUCCESSOR_AFTER_DAYS] days of the step's first row, takes that composite as its successor; an `unknown` row
    becomes the continuation. The composite is added as a security of its own (`AddedLineSuccessor`) when the run
    has none, and only for a delisting that takes it."""
    for e in delistings:
        ls = line_successors.get(e.sec_id)
        if ls is None or not (SUCCESSOR_UNKNOWN in e.flags or e.record.bucket is CrspBucket.UNKNOWN):
            continue
        day = e.last_trade.day or (date.fromisoformat(e.form25_sub.filing_date) if e.form25_sub is not None
                                   else date.fromisoformat(e.delist_date))
        lo = (day - timedelta(days=SUCCESSOR_BEFORE_DAYS)).isoformat()
        hi = (day + timedelta(days=SUCCESSOR_AFTER_DAYS)).isoformat()
        if not lo <= ls.step.first <= hi:
            continue
        found.links[e.key] = (ls.composite, LINE_FOLLOW)
        if e.record.bucket is CrspBucket.UNKNOWN:
            found.rebucketed[e.key] = (
                f"Continuation (line follow, {ls.evidence}): {e.ticker}'s new CUSIP {ls.step.new_cusip} traded from "
                f"{ls.step.first} as {ls.composite}, its own FIGI; holders' shares became {ls.composite}'s")
        x = ls.composite
        if x not in securities and x not in acquirers and x not in found.added:
            rows = [r for r in ftd.trading_rows([ls.step.new_cusip]) if r.symbol == ls.step.symbol]
            found.added[x] = AddedLineSuccessor(
                Security(x, securities[e.sec_id].issuer_cik, share_class_from_name(ls.candidate.name),
                         ls.candidate.name, ls.candidate.security_type, False, "cusip"),
                ls.step.symbol, ls.step.first, rows)
```

- replace `_find_successors`' signature, docstring and its first lines

```python
def _find_successors(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                     sightings: dict[str, list[Sighting]], acquirers: dict[str, AddedSecurity]) -> _Successors:
    """9. Successors after a FIGI change: first a security of this run (observed,
    or an acquirer the run adds) that starts right after the last trade under the
    same issuer or ticker (a holdco reorganization's new line, a rename's new
    FIGI), then the successor issuer's 8-K12B (search: EDGAR full-text search,
    wired in default_clients). `_link_successors` records the answer on the
    delistings."""
    clients, found = ctx.clients, _Successors()
    successor_search = getattr(clients.edgar, "full_text_search", None)
    mark = ctx.meter.start()
```

with

```python
def _find_successors(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                     sightings: dict[str, list[Sighting]], acquirers: dict[str, AddedSecurity],
                     line_successors: Mapping[str, LineSuccessor] = {}, ftd: FtdIndex | None = None) -> _Successors:
    """9. Successors after a FIGI change: first the line successor stage 4b found
    (`_line_successor_links`), then a security of this run (observed, or an
    acquirer the run adds) that starts right after the last trade under the same
    issuer or ticker (a holdco reorganization's new line, a rename's new FIGI),
    then the successor issuer's 8-K12B (search: EDGAR full-text search, wired in
    default_clients). `_link_successors` records the answer on the delistings."""
    clients, found = ctx.clients, _Successors()
    successor_search = getattr(clients.edgar, "full_text_search", None)
    mark = ctx.meter.start()
    if line_successors:
        _line_successor_links(delistings, securities, acquirers, line_successors, ftd or FtdIndex(), found)
    linked = set(found.links)
```

- in the same function, skip the delistings the line successors linked, in three places:

```python
    for e in delistings:                       # a security of this run
        in_run = successor_in_run(e, starts) if SUCCESSOR_UNKNOWN in e.flags else None
```

becomes

```python
    for e in delistings:                       # a security of this run
        if e.key in linked:
            continue
        in_run = successor_in_run(e, starts) if SUCCESSOR_UNKNOWN in e.flags else None
```

```python
            def warm_search(e: Delisting) -> None:
                args = successor_search_args(clients.edgar, e, starts, securities)
```

becomes

```python
            def warm_search(e: Delisting) -> None:
                if e.key in linked:
                    return
                args = successor_search_args(clients.edgar, e, starts, securities)
```

and

```python
        for e in delistings:
            watch = DegradedWatch()
            args = successor_search_args(clients.edgar, e, starts, securities)
```

becomes

```python
        for e in delistings:
            if e.key in linked:
                continue
            watch = DegradedWatch()
            args = successor_search_args(clients.edgar, e, starts, securities)
```

- in `_link_successors`, replace

```python
        if link is not None:
            sid, how = link
            d.set_successor(sid)
```

with

```python
        if link is not None:
            sid, how = link
            reason = successors.rebucketed.get(d.key)
            if reason is not None:                  # an `unknown` row at the line's switch: the continuation
                d.record.bucket, d.record.crsp_code, d.record.reason = (CrspBucket.EXCHANGE_TRANSFER,
                                                                        CONTINUATION_CODE, reason)
                d.add_flag(LINE_CONTINUATION)
            d.set_successor(sid)
```

- in `_run`, replace
  `    successors = _find_successors(ctx, delistings, securities, search.sightings, payouts.added)     # 9` with

```python
    successors = _find_successors(ctx, delistings, securities, search.sightings, payouts.added,
                                  lines.successors, ftd)                                            # 9
```

(`_contract` keeps the line successors in contract/security_history.csv already: they are in `successors.added`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: all pass, 281 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/added_securities.py src/delist_detection/pipeline.py src/delist_detection/review_triage.py tests/test_pipeline.py tests/test_review_triage.py
git commit -m "Stage 9 links a FIGI line to the line successor stage 4b found (sub-plan 5a, U7: DYN 2010, GTES 2026)"
```

---

### Task 12: Docs

Tier: cheap.

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none.

- [ ] **Step 1: Commands**

In `CLAUDE.md`'s Commands block, after the line starting `python scripts/draw_audit_sample.py`, add:

```bash
python scripts/build_line_fixtures.py    # offline: tests/fixtures/lines/ (the line follow's real cases) from the local caches; rerun only to add a case
```

Run `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest` and replace `1842 passed` in the
`pytest   # full suite (...)` comment with the count it prints.

- [ ] **Step 2: The stage list**

In the paragraph that lists `_run`'s stages, replace `` `_resolve_securities`, `_security_cusips`, `_find_delistings`, `` with

```
`_resolve_securities`, `_security_cusips`, `_follow_lines` (stage 4b: each security's line followed past its
observations across a CUSIP or ticker change, `line_follow.py`; the same security takes the new CUSIP and ticker,
a placeholder folds into the FIGI line its new CUSIP names, a FIGI line with another composite records a line
successor for stage 9; metered as "line follow"), `_find_delistings`,
```

- [ ] **Step 3: The module entries**

Make these additions (each a sentence appended to the named bullet, or a new bullet):

- `observations.py`: append "`regular_way` maps a when-issued ticker to its regular-way one (EHAB-WI is EHAB):
  `ObservationIndex` groups by it and each era carries it, while each observation keeps the caller's ticker."
- `ftd.py`: append "`is_unassigned_symbol` (a new CUSIP's first-day `…ZZZZ` rows, no ticker) and `settled_last`
  (the row that opens a CUSIP's last one-price run: the fails still settling after its last trade)."
- `security_master.py`: append "`Security.line_tickers`/`own_tickers()` (the era tickers and the ones stage 4b
  found; every own-ticker check reads it); `cusip_handoffs` times a switch from `ftd.settled_last` (SLE to HSH);
  `_handoff_joins` lets a shared CUSIP reach an era the ticker or name tier picked on its own name (SPW to SPXC);
  `cusip_job` is the one OpenFIGI CUSIP job."
- `history.py`: append "A first-day `…ZZZZ` row is no ticker sighting; an observation is a sighting of its era's
  ticker."
- After the `handoffs.py` bullet, add a new bullet:

```markdown
- `line_follow.py` — sub-plan 5a, pure: a security's line across a CUSIP or ticker change. `candidate_steps` (the
  next step in the fails rows within ±`LINE_DAYS` (10) trading days of the old CUSIP's settled last row: a new
  CUSIP under the line's ticker, its `…ZZZZ`/`…D` spellings, a ticker of the issuer EDGAR lists or its 8-K text
  names (`text_symbols`, `text_cusips`), or the same CUSIP under a new non-OTC ticker; never a CUSIP another
  security holds, nor a switch while the old CUSIP trades on); `corroborate` (R1: refused for an 8-K 1.03 in
  [first − 180, first + 30] d, an OTC move, a description that names no name in force, a class conflict, a
  registrant that merged out or that another CIK's 8-K12B/12G3 replaces (`other_registrant`), or no filing stating
  the change); `decide` (R2: attach, fold a placeholder, a line successor, or refused). Run by
  `pipeline._follow_lines` (stage 4b), up to `MAX_ROUNDS` steps a line; review flags `line_followed`,
  `line_follow_refused:<why>` (info). Its real cases replay offline from `tests/fixtures/lines/`
  (`scripts/build_line_fixtures.py`).
```

- `added_securities.py`: replace `` `AddedAcquirer`/`AddedSuccessor` (`AddedSecurity`) `` with
  `` `AddedAcquirer`/`AddedSuccessor`/`AddedLineSuccessor` (`AddedSecurity`; the last a FIGI line's successor stage
  4b found, linked in stage 9 and added only for an ending that takes it) ``.
- `delistings.py`: append "`SecurityContext.cusip_switches`: a Form 25 within `OWN_SWITCH_DAYS` (5) trading days of
  the security's own CUSIP switch, while it trades on, is no delisting (QGEN 2026)."
- `contract.py`: append to the `id_change_rows` mention "(stage 4b's folds by name, `renames`)".
- `regression.py`: append "A renamed placeholder is compared under its FIGI (`renamed_to`), one `renamed`
  id_changes row instead of its removed row and the FIGI's added one."
- `truth_update.py`: append "A regression of a sec_id the run lacks, or of a renamed placeholder, adds no truth
  row (`run_sec_ids`, `renamed`)."

- [ ] **Step 4: The invariant**

In "Non-obvious invariants", after the bullet that starts `- **A delisting is a Form 25 removal`, add:

```markdown
- **A line is followed past its observations (sub-plan 5a, rulings R1 and R2).** Stage 4b follows each security
  across a reverse split or a rename the fails rows show after the caller's last observation, before the Form 25
  search: so a later real ending is found instead of a guess anchored on the old ticker's last row. A step needs a
  filing that states it (an 8-K 5.03/3.03, an own 8-K12B/12G3, an EDGAR rename, or 8-K text) and an old registrant
  that carries on (a periodic report for a period after the step, or its own 8-K12B; listed today for a step
  within 120 days of the run date; no other CIK's 8-K12B/12G3 naming it). R2 decides identity: the same composite
  or none is one security; a placeholder folds into the FIGI line its new CUSIP names (contract/id_changes.csv
  names it); another composite is a line successor, linked by stage 9 as a continuation (an `unknown` row at the
  switch is rewritten, `line_continuation`).
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: the line follow (sub-plan 5a) in CLAUDE.md"
```

---

### Task 13: The full network run (controller)

Run by the controller, not an implementer. **BASE** below is `794ef8d`, the commit 5a started from: its
`output/` is the run before 5a (no earlier task changes `output/`).

**Files:**
- Modify (by the run): `output/` (the nine tables, `output/contract/`, `scorecard.json`, `run_manifest.json`,
  `run.log`).
- Create: `output/diagnose_unknown_report/loop/5a/scorecard_before.txt`, `.../loop/5a/cases_before.md`;
  `$TMPDIR/cases_5a.py` (not committed).

- [ ] **Step 1: Record the numbers before**

Write `$TMPDIR/cases_5a.py` (Task 15 runs it again for "after"):

```python
"""Each case of the case map's 5a rows: its truth status and its mismatches against the run under output/, as
markdown table rows."""
import csv
from pathlib import Path

from delist_detection.diagnosis_truth import LibraryRows, judge_case, load_diagnosis_truth
from delist_detection.lifecycle import Tables

ROOT = Path.cwd()
CASE_MAP = ROOT / "docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes/case_map.csv"
ids = {r["case_id"] for r in csv.DictReader(CASE_MAP.open()) if r["sub_plan"] == "5a"}
cases = load_diagnosis_truth(ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_legs.csv")
lib = LibraryRows.of(Tables.read(ROOT / "output"))
print("| ticker | case | status | fixed_by | mismatches | which |")
print("| --- | --- | --- | --- | --- | --- |")
for c in sorted((c for c in cases if c.case_id in ids), key=lambda c: c.ticker):
    j = judge_case(c, lib)
    print(f"| {c.ticker} | {c.case_id} | {c.status} | {c.fixed_by} | {len(j.mismatches)} | "
          f"{'; '.join(str(m) for m in j.mismatches)} |")
```

Then, before the run changes `output/`:

```bash
mkdir -p output/diagnose_unknown_report/loop/5a
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py > output/diagnose_unknown_report/loop/5a/scorecard_before.txt
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/cases_5a.py > output/diagnose_unknown_report/loop/5a/cases_before.md
```

Expected: exit 0 both; the metric lines include `D.mismatches 755`; the cases table has 43 rows (the 38 with
fixed_by 5a, or 37 and UAG under 5h after Task 5, plus MSG, LMCA, GOCO, EXE and WLL). The case map keeps a
placeholder's old case id while the truth row may be renamed later: a case whose sec_id the loop renames keeps its
case_id, so the rows line up.

- [ ] **Step 2: Make sure no other SEC client runs**

Ask the operator whether a terminal run is going (it uses another lock file), and check
`ps aux | grep -c classify_universe` shows none but the grep. Do not start while one runs.

- [ ] **Step 3: Run**

With Bash `run_in_background: true`, `timeout: 7200000` and `allowed_domains`: `data.sec.gov`, `www.sec.gov`,
`efts.sec.gov`, `api.openfigi.com`, `api.nasdaq.com`, `www.nasdaqtrader.com`, `api.openai.com`:

```bash
DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations data/observations.csv --extract-merger-terms-llm --as-of 2026-09-25 --sec-workers 4 > output/run.log 2>&1
```

Expected: a warm rerun takes 4 to 5 minutes; the line follow adds about 2 minutes of fails scans and, on this
first run, roughly 100 OpenFIGI jobs, 100 full-text searches and several hundred 8-K texts that are not cached yet.

- [ ] **Step 4: Check the run before trusting it**

- The tool output has no `<sandbox_violations>` block. A denied host means some answers rested on failures: add
  the host and rerun.
- The exit code is 0, or 3 with only `resolution_degraded` rows the banner names (then rerun once SEC answers; a
  run is accepted only with no `error` or `resolution_degraded` row).
- `grep -n "line follow:" output/run.log` prints one line with the counts (attach, fold, successor and the
  refusals). The planning replay's order of magnitude: about 130 steps; 39 followed on cached OpenFIGI answers,
  about 55 more decided by the run's new OpenFIGI answers.
- `grep -c "OpenFIGI unavailable" output/run.log` is 0.

- [ ] **Step 5: The numbers after**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py`
Expected: `D.mismatches` below 755. Note any `DROP`, `GOLDEN FAILING` and `DIAGNOSIS FAILING` line for Task 15.

- [ ] **Step 6: Commit the run**

```bash
git add output
git commit -m "Sub-plan 5a: full run with the line follow (before the truth loop)"
```

---

### Task 14: The truth loop (controller)

Run by the controller. At most 3 rounds, at most 5 agents at a time (the workflow enforces both).

**Files:**
- Modify (by the loop): `data/diagnosis_truth.csv`, `data/diagnosis_truth_changes.csv`,
  `output/diagnose_unknown_report/loop/diagnosed.csv`, `output/regression_report.csv`.
- Create (by the loop): `output/diagnose_unknown_report/loop/5a/round-<N>/{cases.csv,reports/,records/,summary.md}`.

- [ ] **Step 1: Look at round 1's errors before spending agents**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/truth_loop_round.py --label 5a --base 794ef8d --round 1`
Expected: one JSON line: `renamed` (truth rows renamed to their placeholder's FIGI), `mismatches_new`,
`regressions_new` and the cases. Read `output/regression_report.csv`: each regression should be one of the
changes the plan expects (a line followed to a later ending, a same-CUSIP rename's new ticker range, a fold's
`renamed` row, a junk `…ZZZZ` range gone, a line successor's continuation). A regression of any other kind is a
bug: stop and report it with the row before running agents.

(The workflow runs this same round script itself; running it here first only writes the same round-1 files.)

- [ ] **Step 2: Run the loop**

Run the Workflow tool with `scriptPath: ".claude/workflows/diagnosis-truth-loop.js"` and
`args: {"label": "5a", "base": "794ef8d"}`.

Expected: up to 3 rounds; each round diagnoses and verifies its cases, writes the records back, and runs
`update_truth.py` (which flips every known_wrong truth case the run now matches to `pass`). The result lists, per
round, the cases, the missing records and the update's JSON line. Note the wall time and tokens for the report.

- [ ] **Step 3: Settle what the loop could not**

- A case with no record after round 3 is retried by hand only with the operator's agreement.
- A regression the loop settled `old_right` means a rule of 5a is wrong for that case: stop, and report the case
  and the rule to the operator. A fix is a new task the operator approves (a failing test from the case, then
  Task 13 and this task again, moving the round folders aside first).
- A `ruling_pending` truth row (an unverified or refuted diagnosis, or a shape verdict) is the operator's to rule.

- [ ] **Step 4: Commit the loop**

```bash
git add data/diagnosis_truth.csv data/diagnosis_truth_changes.csv output/diagnose_unknown_report/loop output/regression_report.csv
git commit -m "Sub-plan 5a: the truth loop's rounds, diagnoses and truth updates"
```

---

### Task 15: Acceptance and the operator report (controller)

Run by the controller.

**Files:**
- Create: `output/diagnose_unknown_report/loop/5a/report.md`
- Modify: `data/scorecard.json` (the floor), `output/scorecard.json`, the roadmap

- [ ] **Step 1: The checks**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --check --base 794ef8d`
Expected: exit 0: no `DROP`, no `GOLDEN FAILING`, no `DIAGNOSIS FAILING`, and `D.unexplained_regressions 0`. For
each line that fails it:
- `D.unexplained_regressions` above 0: a regression the ledger has not settled `new_right` (Task 14 Step 3).
- `DROP <metric>`: if the loop showed the drop is right (more endings found are uncertain, say), ask the operator;
  a floor is lowered by hand only with the operator's approval and the reason in the commit.
- `DIAGNOSIS FAILING`: a `pass` truth case the run now fails: a regression in the truth set: report it.

- [ ] **Step 2: Raise the floor**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --write --raise-floor`
Expected: `D.mismatches` and its fields move down in `data/scorecard.json`'s floor (never up).

- [ ] **Step 3: The suite**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: green apart from golden `known_wrong` cases the run now passes (strict XPASS in
tests/test_golden_lifecycles.py; EXBD, LIZ, ACXM, DF, MNI, XON and ESV are line cases that may). Do not edit
`data/golden_lifecycles.csv`: list each XPASS case for the operator to flip, and wait. A diagnosis truth XPASS
should not remain (the loop flips them); if one does, rerun the last round's update:
`PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/update_truth.py --label 5a --round <last> --base 794ef8d`.

- [ ] **Step 4: The 43 cases, after**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/cases_5a.py > output/diagnose_unknown_report/loop/5a/cases_after.md`
(the script Task 13 Step 1 wrote; if `$TMPDIR` was cleared, write it again from there). Compare it row by row with
`cases_before.md`.

- [ ] **Step 5: The report**

Write `output/diagnose_unknown_report/loop/5a/report.md` with these sections, every number from the commands
above:

1. **Result**: accepted or not; `D.mismatches` before (755) and after; the floor raised; `--check --base` result;
   pytest result (and the golden XPASS cases waiting for the operator).
2. **Mismatches per field**: one row per `D.mismatches.<field>` from `scorecard_before.txt` and the scorecard
   now.
3. **The 43 cases**: the table from Step 4, before and after, with the expected outcome of this plan's "Expected
   outcome" section beside each, and why each one that still mismatches does (the sub-plan its `fixed_by` names).
4. **The line follow**: the `line follow:` log line; folds, line successors and refusals by reason.
5. **Regressions**: how many, by kind, and how the loop settled each (new_right, old_right, pending), with the
   reports' paths.
6. **Truth changes**: every row of `data/diagnosis_truth_changes.csv` that 5a's loop or Task 5 added.
7. **Uncertain endings and coverage**: `V.uncertain_endings`, `V.uncertain_securities`, `L1.coverage_securities`
   and `L1.coverage_tickers`, before and after.
8. **For the operator**: rulings needed (pending rows, old_right regressions, floor drops), golden cases to flip,
   the loop's time and tokens, and whether U4 was kept.

- [ ] **Step 6: Roadmap and commit**

In `docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md`, set the 5a row's Status to
`done (D.mismatches 755 -> <after>; <n> of 43 cases now pass)` once the operator accepts the report (until then:
`run, awaiting the operator`).

```bash
git add data/scorecard.json output/scorecard.json output/diagnose_unknown_report/loop/5a docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md
git commit -m "Sub-plan 5a accepted: D.mismatches 755 -> <after>, floor raised; the operator report"
```

Send the operator the report's path and its sections 1, 3 and 8.

---

## Self-review

- **Spec coverage.** Section 3 "5a": follow the issuer's line before the fallback (Tasks 7, 10); same CIK and class
  (`corroborate`'s name and class checks, `decide`'s other_issuer and class); the windows (Task 7's `LINE_DAYS`,
  the 1.03 window); a filing that states the change (`corroborate`); R2 (`decide`, Tasks 10 and 11); attach
  forward (Task 10); fold a duplicate placeholder (Tasks 3 and 4 in stage 3, Task 10 in 4b); `-WI` (Task 2). The
  "where" list: `cusip_handoffs` (Task 3), `_handoff_joins` (Task 4), `superseded_placeholders` (Task 6), the
  finder (Tasks 6, 9), the 8-K12B search's own tickers (Task 6), `_find_successors` (Task 11);
  `candidate_cusips`/`era_cusips`, `resolve_with_identity_guard` and `classifier._detect_continued_filings` need no
  change (research 1.2: the fallback is no longer reached for a followed line). Must-not-change cases: UAL 2006
  (Tasks 7, 10), VRM 2025 and RAD (Tasks 7, 8), DYN 2012 (Task 8: DYN's 2010 step is a successor, the line is not
  followed further), FTR to FYBR (held CUSIP, Task 7), new LMCA/MSG (Tasks 7, 8, 10), AAN/GOOG (Tasks 7, 8), two
  classes (Task 4), UNIT (Tasks 7, 8, 10), WLL (Tasks 7, 8), EXE (no step: Task 8's replay finds none). Section 1:
  the loop and acceptance (Tasks 13 to 15). The roadmap's carried item N1 is Task 1.
- **Placeholders.** None: every code step is complete; the counts the controller fills in (N in Task 5, the
  after-numbers in Task 15) are measurements, not code.
- **Type consistency.** `candidate_steps(..., holders=Mapping[str, Collection[str]])` in Tasks 7, 8 and 10;
  `corroborate(..., listed_now=callable, other_registrant=callable)` in Tasks 7, 8 and 10; `LineSuccessor` (Task 7)
  in Tasks 10 and 11; `cusip_job` (Task 8) in Task 10; `Security.line_tickers`/`own_tickers()` (Task 6) in Tasks 7,
  10 and 11; `_context_builder(..., ftd, sec_cusips)` (Task 9) is unchanged by Task 10; `_find_delistings(...,
  moved_on)` and `_find_successors(..., line_successors, ftd)` match their `_run` calls.
- **Review Focus.** Each line has its test in the owning task (Tasks 7, 10, 11).

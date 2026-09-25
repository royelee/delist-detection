# Review triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `output/review.csv` a list a person can finish: every row carries a severity, rows are ordered by what they can do to a return, rows that only record where an answer came from leave the file, a summary groups rows by cause, and a person's "checked, it's fine" decisions persist across runs.

**Architecture:** A new pure module `review_triage.py` owns a catalog of every review flag (severity, description, action), turns the pipeline's merged review rows plus a decisions list into the final `review.csv` rows and a new `review_summary.csv`, and loads/validates the decisions file. `pipeline.run()` calls it just before writing; the CLI loads `data/review_decisions.csv` by default. `delistings.csv` is not changed by triage or decisions.

**Tech Stack:** Python ≥3.10, pandas-free stdlib code (csv, dataclasses), pytest, offline.

**Spec:** No separate spec document. The user asked (2026-09-24, PR #5) for the four changes below; this section is the binding spec. Rulings the controller made are marked **Ruling**.

1. A `severity` for every review row: `fix`, `check` or `info`; rows sorted by how much they can move a return.
2. Rows whose flags are all `info` leave `review.csv` (their flags stay on `delistings.csv`).
3. A short summary by cause (flag), with counts and a few examples each: `output/review_summary.csv`.
4. A decisions file keyed by `(sec_id, delist_date, ticker, flag)` that the pipeline reads, so accepted rows stay accepted on later runs.

## Global Constraints

- Tests are fully offline (`FakeEdgar` and committed fixtures); never add network to the test path.
- Frozen: `CrspBucket`, `DLST_CODE_TO_BUCKET`, classifier rule order, `dlret.py` formulas, the payout gate. Triage never changes `delistings.csv`, `payouts.csv` or any other table's content.
- Run code in this worktree with `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`.
- Never `git stash`. Commit with an explicit pathspec. Do not push.
- Never print or store an API key value. `.env` is gitignored.
- One SEC client at a time; set `DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock` inline on every live run.
- Output is deterministic: the same inputs, caches and decisions give byte-identical `review.csv` and `review_summary.csv`.

## Review Focus

- A decisions file with a typo'd flag token, or one written against an older run: it must show up as a `review_decision_unmatched` row, never be silently ignored.
- A decision trying to accept `error` or `resolution_degraded`: loading must refuse it (these mean the run failed a request; the fix is a rerun), so exit code 3 still fires.
- Flags with a detail after `:` (`terms_gate_failed:no_acq_price`, `observation_conflict:2014-06-30`, `ftd_close_prior:3`): a decision matches the exact token; the catalog looks up the name before `:`.
- Rows with a blank `sec_id` (observation-level rows such as `observation_unresolved`, `observation_conflict:<date>`): blank key cells match blank decision cells.
- A delisting with no DLRET whose only flags are `info`: it must stay in `review.csv` as `fix`.

---

### Task 1: Flag catalog and triage module

**Files:**
- Create: `src/delist_detection/review_triage.py`
- Modify: `src/delist_detection/store.py` (the `review` table spec, a new `review_summary` table spec, a `sort` switch on `TableSpec`), `src/delist_detection/pipeline.py` (call `triage(review_rows, ())` before the write)
- Test: `tests/test_review_triage.py` (new), `tests/test_store.py` (extend)

**Interfaces:**
- Consumes: the merged review rows `pipeline.run()` builds today (`_merge_review_rows` output): dicts with keys `sec_id, delist_date, ticker, cik, bucket, dlret, review_flags, reason, anchor_8k, last_seen`; `review_flags` is `;`-joined tokens; `dlret` is a float, `None`, NaN or `""`.
- Produces:
  - `SEVERITIES = ("fix", "check", "info")` (this order is the sort order).
  - `@dataclass(frozen=True) class FlagInfo: severity: str; description: str; action: str; acceptable: bool = True`
  - `CATALOG: dict[str, FlagInfo]` keyed by flag name.
  - `flag_name(token: str) -> str` — the text before the first `:`.
  - `flag_info(token: str) -> FlagInfo` — catalog entry; an unknown name gives `FlagInfo("check", "not in the flag catalog", "add it to review_triage.CATALOG")`.
  - `row_severity(row: Mapping) -> str`
  - `@dataclass(frozen=True) class Decision: sec_id: str; delist_date: str; ticker: str; flag: str; note: str`
  - `class ReviewDecisionError(ValueError)`
  - `DECISION_COLUMNS = ("sec_id", "delist_date", "ticker", "flag", "decision", "note")`
  - `load_decisions(path: str | Path) -> list[Decision]` — raises `FileNotFoundError` for a missing file (the caller decides whether that is fine).
  - `@dataclass(frozen=True) class Triage: review_rows: list[dict]; summary_rows: list[dict]; counts: dict[str, int]`
  - `triage(rows: list[Mapping], decisions: Sequence[Decision]) -> Triage`
  - `store.TableSpec` gains `sort: bool = True`; `write_table`/`write_tables` keep the given row order when `sort` is False.
  - `store.TABLES["review"]` columns: `("severity", "sec_id", "delist_date", "ticker", "cik", "bucket", "dlret", "review_flags", "reason", "anchor_8k", "last_seen")`, key unchanged `("sec_id", "delist_date", "ticker", "review_flags")`, `sort=False`.
  - `store.TABLES["review_summary"]` columns: `("severity", "flag", "rows", "in_review", "accepted", "description", "action", "examples")`, key `("flag",)`, `sort=False`.

**Catalog.** Enumerate every flag the code can emit (search `src/` for every review flag and every `ReviewItem(...)` flag, including f-string flags such as `ftd_close_prior:{n}`, `terms_gate_failed:{why}`, `payout_gate_failed:{n}`, `observation_conflict:{day}`) plus `review_decision_unmatched`. Give each a one-sentence `description` (what it means, in plain words) and a one-sentence `action` (what a person does: which filing to read, which override CSV or observation pin fixes it, or "accept it in data/review_decisions.csv if right"). Severities:

- `info` — the answer came from a less precise source but nothing suggests it is wrong: `no_figi`, `resolved_by_current_ticker_map`, `resolved_by_cik_map`, `resolved_by_manual_override`, `ftd_close_prior`, `ftd_close_lagged`, `acquirer_close_lagged`, `last_trade_date_unconfirmed`.
- `fix`, `acceptable=False` — the run itself failed or the decisions file is stale: `error`, `resolution_degraded`, `review_decision_unmatched`.
- `fix` — a security could not be identified: `observation_unresolved`.
- `check` — every other flag (e.g. `merger_at_par`, `terms_gate_failed`, `payout_gate_failed`, `llm_gate_failed`, `distress_at_normal_price`, `bankruptcy_*`, `no_evidence_default`, `last_trade_date_conflict`, `no_form25`, `delist_date_approx`, `successor_unknown`, `no_last_close`, `no_last_trade_date`, `form25_unclassified`, `form25_unmatched`, `form25_unreadable`, `listing_status_unknown`, `ended_without_delisting`, `observed_after_delisting`, `member_name_mismatch`, `ticker_unconfirmed`, `ticker_shared`, `ticker_range_overlap`, `observation_conflict`).
- **Ruling:** if you find a flag not listed here, give it `check` and say so in your report.

**`row_severity(row)`:** `fix` when the row is a delisting row (non-blank `bucket`; Form 25 review items such as `form25_unmatched` carry a `delist_date` but no bucket and are not delisting rows) and its DLRET is blank (None, NaN or `""`) — a delisting with no delisting return always needs a person, whatever its flags. Otherwise the most severe of its tokens' catalog severities (`fix` > `check` > `info`). A row with no tokens is `info`.

**`load_decisions(path)`:** reads a CSV whose header contains every column of `DECISION_COLUMNS` (extra columns are ignored). Cells are stripped. Raise `ReviewDecisionError` naming the file and line for: a missing required column; an empty `flag`; a `decision` other than `accept` (case-sensitive); a flag whose catalog entry has `acceptable=False`. A header-only file gives `[]`. Duplicate rows are allowed (they collapse to one decision).

**`triage(rows, decisions)`:**
1. For each row, split `review_flags` on `;` (drop empty tokens). A token is accepted when a decision has the same `sec_id`, `delist_date`, `ticker` (each compared as stripped strings, `None` as `""`) and `flag == token` exactly. Remove accepted tokens from the row.
2. Each decision that accepted no token anywhere becomes a new row: `sec_id`, `delist_date`, `ticker` from the decision, `review_flags = "review_decision_unmatched"`, `reason = f"decision accepts {flag!r} but no review row carries it; remove it from the decisions file"` plus `f" ({note})"` when the note is non-empty; other columns blank.
3. Every row with at least one remaining token gets `severity = row_severity(row)` computed on its remaining tokens, and keeps all remaining tokens (info tokens included) in `review_flags`. Rows whose severity is `info`, and rows with no remaining tokens, leave `review.csv`.
4. Order `review_rows` by: severity (`fix` before `check`); then group 0 = delisting row (non-blank `bucket`) with blank DLRET, 1 = delisting row with a DLRET, 2 = every other row; then, in group 1, larger `abs(dlret)` first; then `(sec_id, delist_date, ticker, review_flags)` as strings.
5. `summary_rows`: one row per flag name that appears on any input row (before step 1) or in a `review_decision_unmatched` row. `rows` = input rows carrying that name (before decisions), and for `review_decision_unmatched` the number of such rows; `accepted` = tokens with that name removed by decisions; `in_review` = rows in the final `review_rows` carrying that name; `severity`, `description`, `action` from the catalog; `examples` = up to three distinct labels joined by `"; "` — label is `f"{ticker}@{delist_date}"`, or `ticker` when there is no `delist_date`, or `sec_id` when there is no ticker — taken first from the final `review_rows` in order, then from the remaining input rows ordered by `(sec_id, delist_date, ticker, review_flags)`. Order summary rows by severity, then `rows` descending, then flag name.
6. `counts = {"fix": n, "check": n, "info_hidden": rows dropped as info, "accepted": tokens accepted, "cleared": rows dropped because every token was accepted, "unmatched_decisions": n}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_triage.py`:
  - `flag_name("terms_gate_failed:no_acq_price") == "terms_gate_failed"`; unknown name → `check`.
  - Catalog coverage: every token in the committed `output/review.csv` and in `output/delistings.csv`'s `review_flags` column has a catalog entry by name (read with `csv`, offline).
  - Every catalog entry has a non-empty description and action and a severity in `SEVERITIES`.
  - `row_severity`: a delisting row with blank DLRET and only `ftd_close_prior:3` → `fix`; the same row with `dlret=0.1` → `info`; `merger_at_par;no_figi` with a DLRET → `check`; `error` → `fix`.
  - `triage` drops an info-only row from `review_rows`, counts it in the summary (`rows` 1, `in_review` 0) and in `counts["info_hidden"]`.
  - A decision accepting `merger_at_par` on `(S1, 2020-01-02, AAA)` removes that token; a row left with only `no_figi` is hidden; `counts["accepted"] == 1`.
  - A decision for `terms_gate_failed:no_acq_price` does not accept `terms_gate_failed:fail_sanity`, and becomes a `review_decision_unmatched` row with severity `fix`.
  - A decision with blank `sec_id`/`delist_date` and ticker `CB` accepts `observation_conflict:2014-06-30` on a row whose `sec_id` is `""` and whose `delist_date` is `None`.
  - Ordering: build fix/check rows with blank DLRET, DLRETs 0.0, −0.3 and 0.05, and a no-date row; assert the exact order.
  - Summary: order, `examples` labels and the three counts on a small fixture.
  - `load_decisions`: header-only → `[]`; `decision=reject` → `ReviewDecisionError`; flag `error` → `ReviewDecisionError`; flag `resolution_degraded` → `ReviewDecisionError`; missing `flag` column → `ReviewDecisionError`; extra column ignored; missing file → `FileNotFoundError`.
  - Determinism: `triage` on the same rows given in two different input orders returns identical `review_rows` and `summary_rows`.
  - In `tests/test_store.py`: a `sort=False` table keeps input order; the existing key-sorted tables still sort.
- [ ] **Step 2: Run the tests to see them fail.** `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_review_triage.py tests/test_store.py -q`
- [ ] **Step 3: Implement** `review_triage.py` and the `store.py` changes. In `pipeline.run()`, keep the Counter of flags computed from the merged rows before triage (it feeds `RunSummary.review_flags` and the manifest, so exit code 3 is unchanged), then call `triage(review_rows, ())` and write `review` = `tri.review_rows` and `review_summary` = `tri.summary_rows` in the existing `write_tables` call. Decisions, the manifest's new field and the CLI are Task 2's. Update any existing test or script that reads or writes the `review` table for the new `severity` column, the hidden info rows and the new order (search `tests/` and `scripts/` for `"review"` and `review.csv`); never loosen an assertion about `delistings.csv`.
- [ ] **Step 4: Run the full suite.** `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q` — all pass.
- [ ] **Step 5: Commit** `src/delist_detection/review_triage.py src/delist_detection/store.py src/delist_detection/pipeline.py tests/test_review_triage.py tests/test_store.py` (plus any test you had to update) with message `feat(review): flag catalog, severities, decisions and triage for review.csv`.

---

### Task 2: Wire triage into the run, the CLI and the docs; rerun

**Files:**
- Modify: `src/delist_detection/pipeline.py` (`run()`), `src/delist_detection/manifest.py`, `scripts/classify_universe.py`, `src/delist_detection/review_triage.py` (`accept_by_flag`, `append_decisions`)
- Create: `data/review_decisions.csv` (header only: `sec_id,delist_date,ticker,flag,decision,note`)
- Create: `scripts/accept_review.py` (bulk accept by flag; see below), test `tests/test_accept_review.py`
- Modify docs: `README.md`, `CLAUDE.md`, `docs/data-flow.md`, `CONTEXT.md` (glossary entries for *severity* and *review decision* only), `docs/validation/2026-09-23-acceptance.md`
- Test: the existing pipeline and CLI test files (find them with `grep -l "run(" tests/test_pipeline*.py` and `grep -l classify_universe tests/`)
- Outputs: `output/review.csv`, `output/review_summary.csv`, `output/run_manifest.json`, `output/run.log`

**Interfaces:**
- Consumes: Task 1's `review_triage.triage`, `load_decisions`, `Decision`, `ReviewDecisionError`, the new `store.TABLES` specs.
- Produces:
  - `pipeline.run(..., review_decisions: Sequence[Decision] = ())` — passes them to the `triage(...)` call Task 1 added (which already writes `review` and `review_summary` and keeps `RunSummary.review_flags`/the manifest's `review_flags` counted before triage).
  - The manifest gains `"review": tri.counts`.
  - `RunSummary` gains `review_counts: dict[str, int]` (= `tri.counts`); the CLI prints one line, e.g. `Review: 41 fix, 390 check (512 info-only rows hidden, 0 accepted, 0 unmatched decisions)`.
  - CLI `--review-decisions PATH`, default `data/review_decisions.csv`. **Ruling:** a missing file at the default path means no decisions; a missing file at an explicitly given path, or a `ReviewDecisionError`, is reported and exits 2, the same way the CLI treats other bad input files (follow how it handles a bad `--merger-terms` file; if that path exits differently, match it and say so in your report).

**Bulk accept (Ruling, 2026-09-24):** after Task 1, 752 `check` rows remain, and many share one cause; a person who has sampled a cause needs to accept its rows without typing one decision per row. `scripts/accept_review.py --flag NAME --note TEXT [--bucket BUCKET] [--review output/review.csv] [--decisions data/review_decisions.csv] [--dry-run]` appends one `accept` decision for every row in the current `review.csv` that carries a token whose name (before `:`) is `NAME` (and whose `bucket` equals `BUCKET` when given), one decision per matching token, with that row's `sec_id`, `delist_date`, `ticker` and the exact token. `--note` is required and non-empty (the person records what they checked). It skips decisions already in the file, refuses flags whose catalog entry is not acceptable (exit 2), writes the file atomically (`store.replace_on_success`), creates it with the header when missing, and prints how many decisions it added (`--dry-run` prints without writing). Decisions stay per row, so a new row with the same flag on a later run still shows up. Put the reusable part (select rows, build `Decision`s, append) in `review_triage.py` as `accept_by_flag(review_rows, flag, *, note, bucket=None) -> list[Decision]` and `append_decisions(path, decisions) -> int`, and keep the script a thin CLI.

- [ ] **Step 1: Write the failing tests.** In `tests/test_accept_review.py`: selecting by flag name matches `terms_gate_failed:no_acq_price` and `terms_gate_failed:fail_sanity`; `--bucket` narrows; an existing decision is not duplicated; `error` is refused; a missing decisions file is created with the header; the decisions it writes load with `load_decisions` and, fed to `triage`, clear exactly those tokens. In the pipeline tests: a run writes `review_summary.csv`; `review.csv`'s first column is `severity` and holds only `fix`/`check`; a run given a `Decision` for one of its flagged rows no longer lists that token and reports `accepted == 1` in the manifest; a stale decision produces a `review_decision_unmatched` row; `delistings.csv` is byte-identical with and without decisions. In the CLI tests: no `data/review_decisions.csv` → runs; an explicit missing path → exit 2; a file with `decision=reject` → exit 2.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** the wiring, the header-only `data/review_decisions.csv`, and the manifest field.
- [ ] **Step 4: Full suite passes.** `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q`
- [ ] **Step 5: Docs.** "six tables" → "seven tables" wherever it counts outputs (also in `pipeline.py`'s comments and `scripts/classify_universe.py`'s help text); document `review_summary.csv`, the `severity` column and its order, the decisions file (columns, exact-token matching, blank matches blank, `error`/`resolution_degraded` not acceptable, stale decisions become `review_decision_unmatched` rows, decisions never change `delistings.csv`), `--review-decisions`, and `scripts/accept_review.py` (add it to CLAUDE.md's Commands block). Replace CLAUDE.md's validation-loop wording "start from `output/review.csv` (every row with a non-empty `review_flags`)" with: start from `output/review_summary.csv`, work `review.csv` top down, record each accepted row in `data/review_decisions.csv`. Update the test count in `CLAUDE.md` and `README.md` to the new total.
- [ ] **Step 6: Commit** code, tests, `data/review_decisions.csv`, `scripts/accept_review.py` and docs with an explicit pathspec: `feat(review): write severity-sorted review.csv, review_summary.csv; read data/review_decisions.csv`.
- [ ] **Step 7: Warm rerun.** First confirm no other SEC client is running (`ps aux | grep -E "classify_universe|verify_against_web|build_golden" | grep -v grep` is empty). Then:
  ```bash
  DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations data/observations.csv --extract-merger-terms-llm --sec-workers 1 > output/run.log 2>&1
  ```
  Caches are warm; expect a few minutes and few SEC requests. If the sandbox refuses a host, rerun with that host allowed (SEC, OpenFIGI, Nasdaq, OpenAI hosts only).
- [ ] **Step 8: Check what changed.** `git diff --stat -- output/`. Expected: `review.csv`, `review_summary.csv` (new), `run_manifest.json`, `run.log`. For any other output table that changed, report the rows and why (a live answer such as `listed_today` can move between runs); do not commit a change you cannot explain.
- [ ] **Step 9: Validation note.** Add a short "Review triage" section to `docs/validation/2026-09-23-acceptance.md`: rows before (1,220) and after, counts by severity, info-only rows hidden, and the top five causes from `review_summary.csv` with their row counts.
- [ ] **Step 10: Commit** `output/review.csv output/review_summary.csv output/run_manifest.json output/run.log docs/validation/2026-09-23-acceptance.md` (plus any other output you explained): `data: review triage outputs`.

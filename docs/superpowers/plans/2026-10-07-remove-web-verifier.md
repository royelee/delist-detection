# Remove the Web Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete `scripts/verify_against_web.py`, its test and its output file, and name the scorecard in its place in the documented validation loop.

**Architecture:** A deletion. No pipeline code reads the script or `output/web_verification.csv`, so no table the pipeline writes changes. The docs and three docstrings that name the script are edited. Historical records keep their text.

**Tech Stack:** Python, pytest, git.

**Spec:** none. The reasons are in "Why" below.

**Start condition:** the `arch-deepening` branch is finished: every row of the Order table in `docs/superpowers/plans/2026-10-07-architecture-deepening.md` is done and the branch is merged, or the operator says to start. Work on a new branch, `remove-web-verifier`, cut from wherever `arch-deepening` ended up.

**Where this file is:** untracked in the main checkout, written on 2026-10-07 while `arch-deepening` was still in progress in its own worktree. If the work runs in a worktree, copy this file into that worktree's `docs/superpowers/plans/` first, so Task 3 can commit it.

**About the quoted text:** every passage below was read on `arch-deepening` at 6f28882 on 2026-10-07. Line numbers will have moved. Find each passage by its quoted text, and if a passage reads differently, make the same change to the text that is there.

## Why

Written 2026-10-07, from the code and `docs/validation/2026-09-23-acceptance.md`.

- **Nothing reads its output.** No file under `src/`, `scripts/` or `tests/` reads `output/web_verification.csv` except the script's own test.
- **It is no longer independent.** The first version (2026-05-29) compared Alpha Vantage's company name with EDGAR's names for the resolved CIK. PR #5 removed Alpha Vantage. The script now compares `resolved_name`, which is the observation's name (or the OpenFIGI name), with EDGAR's names. The resolver already uses the observed name to pick and validate the CIK.
- **The pipeline makes both main checks itself.** `member_name_mismatch` compares EDGAR's issuer name on the delisting date with the observed name. `no_form25` marks a delisting found without a Form 25.
- **Its last output found nothing new.** `output/web_verification.csv` (2026-09-28, 982 rows): 904 `OK`, 75 `WEAK_no_delist_form`, 3 `OK_recycled_ticker`, 0 `MISMATCH_name`. All 75 `WEAK` rows carry `no_form25` and are in `review.csv`. The 3 `OK_recycled_ticker` rows (Wendy's 2012, Aaron's 2020, Dun & Bradstreet 2025) have the right CIK. The script splits their names badly.
- **Its record.** One real class of finding during the September refactor: holdco reorganizations whose era carried the new holding company's CIK, fixed by pinning the CIK per era. The other non-OK verdicts were the script's own gaps (33 `WEAK` rows, fixed in the script at d6021c6) or word-splitting errors (BlackRock, IAC).
- **It costs live requests.** At least one uncached SEC request per row on every run, and no other SEC client may run at the same time.
- **A better measure exists.** `scripts/scorecard.py --check` grades every rebuild against the golden lifecycles and the diagnosis truth set, which were checked by hand at a cited source.

## Global Constraints

- No table the pipeline writes changes. Under `output/`, only `web_verification.csv` is removed.
- Under `src/`, only docstring text changes: one docstring in `edgar.py`, two in `sec_limiter.py`.
- Tests stay offline. Only Task 1 uses the network.
- Only one SEC client may run at a time on the machine. Confirm none is running before Task 1's live run.
- There is no lint or format command. Do not run one.
- In a worktree the editable install points at the main checkout. Prefix every script with `PYTHONPATH=src`.
- These historical records keep their text, even though they name the script:
  - `docs/validation/2026-09-23-acceptance.md`
  - `docs/2026-09-28-handoff-validation.md`
  - `docs/superpowers/plans/2026-09-23-sec-request-speed.md`
  - `docs/superpowers/plans/2026-09-23-security-master-and-delistings.md`
  - `docs/superpowers/plans/2026-09-24-review-triage.md`
  - `docs/superpowers/plans/2026-09-26-observation-map.md`
  - `docs/superpowers/plans/2026-10-07-architecture-deepening.md`

## Review Focus

1. **The last run finds a real mismatch that nothing else flags.** Expected: the work stops and the rows go to the operator. Checked by Task 1 Step 4's exit code.
2. **A doc still tells the reader to run the deleted script.** Expected: no current doc names it. Checked by Task 3 Step 6's file list.
3. **The README points at a deleted section** ("*Verifying the output* below"). Expected: the sentence ends at the section that still exists. Checked by Task 3 Step 2 and Step 6.
4. **The test count in `CLAUDE.md` is wrong after the test file goes.** Expected: it equals what `pytest` prints. Checked by Task 2 Steps 4 and 5.
5. **A historical record is edited by mistake.** Expected: `git diff` shows none of the files listed under Global Constraints. Checked by Task 3 Step 7.

## Not in this plan

- **`sec_get`'s `retry=False` mode.** The script is its only caller outside `tests/test_sec_http.py`. The parameter stays. Removing it is a separate change to `edgar.py`.
- **Moving the script onto `EdgarClient`.** Dropped, since the script is deleted.

---

### Task 1: Last run, to confirm deleting loses nothing (NETWORK)

This task needs the operator's go-ahead for a live SEC run. It commits nothing.

**Files:**
- Create (scratch, not committed): `$TMPDIR/web_verification_last.csv`, `$TMPDIR/check_last_verifier_run.py`

**Interfaces:**
- Consumes: `output/delistings.csv` and `output/review.csv` from the latest full `classify_universe.py` run.
- Produces: a go or stop decision for Tasks 2 and 3.

- [ ] **Step 1: Confirm no other SEC client is running**

Run: `ps aux | grep -E "classify_universe|verify_against_web|build_golden" | grep -v grep`
Expected: no output.

- [ ] **Step 2: Run the verifier once more, into a scratch file**

In an agent sandbox, allow the host `data.sec.gov` and set the shared lock path first:

```bash
export DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock
PYTHONPATH=src python scripts/verify_against_web.py --output "$TMPDIR/web_verification_last.csv"
```

Expected: progress lines on stderr every 25 rows, then `Done. Verdict counts:` and exit 0. It sends at least one request per delisting row, so allow several minutes. Exit 2 with `ABORTED:` means SEC refused the client (403/429). Wait 20 minutes and run it again.

- [ ] **Step 3: Write the check script**

Save as `$TMPDIR/check_last_verifier_run.py`:

```python
"""Does the verifier's last run report anything the pipeline does not already flag?

Usage: python check_last_verifier_run.py <web_verification.csv>
Run from the repo root. Exit 0: nothing new. Exit 1: rows to look at.
"""
import collections
import csv
import sys

DISAGREE = {"WEAK_no_ma_items", "WEAK_no_3_01", "WEAK_no_form15"}
KNOWN_RECYCLED = {"WEN", "AAN", "DNB"}   # right CIK, names split badly (acceptance report)


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


verdicts = read(sys.argv[1])
flags = collections.defaultdict(set)
for row in read("output/delistings.csv"):
    for token in (row.get("review_flags") or "").replace(";", "|").split("|"):
        if token.strip():
            flags[(row["sec_id"], row["ticker"])].add(token.strip().split(":")[0])
in_review = {(row["sec_id"], row["ticker"]) for row in read("output/review.csv")}

print("verdicts:", collections.Counter(v["verdict"] for v in verdicts).most_common())

disagree, unflagged, recycled, unfetched = [], [], [], []
for v in verdicts:
    key, verdict = (v["sec_id"], v["ticker"]), v["verdict"]
    if verdict == "OK":
        continue
    if verdict == "no_entity_data":
        unfetched.append(v)
    elif verdict == "OK_recycled_ticker":
        if v["ticker"] not in KNOWN_RECYCLED:
            recycled.append(v)
    elif verdict.startswith("MISMATCH") or verdict in DISAGREE:
        disagree.append(v)
    elif not flags[key] and key not in in_review:
        unflagged.append(v)


def show(title, rows):
    print(f"{title}: {len(rows)}")
    for v in rows:
        print("  ", v["sec_id"], v["ticker"], v["our_bucket"], v["verdict"], "|",
              v["resolved_name"], "|", v["edgar_name"], "|", v["former_names"][:80])


show("disagreements", disagree)
show("non-OK rows with no pipeline flag", unflagged)
show("new OK_recycled_ticker rows", recycled)
show("rows EDGAR did not answer for (no_entity_data)", unfetched)
sys.exit(1 if disagree or unflagged or recycled or unfetched else 0)
```

- [ ] **Step 4: Run the check**

Run: `python "$TMPDIR/check_last_verifier_run.py" "$TMPDIR/web_verification_last.csv"; echo "exit $?"`

Expected:

```
disagreements: 0
non-OK rows with no pipeline flag: 0
new OK_recycled_ticker rows: 0
rows EDGAR did not answer for (no_entity_data): 0
exit 0
```

- [ ] **Step 5: Decide**

- Exit 0: go on to Task 2.
- Only `no_entity_data` rows: the script does not retry a failed request. Rerun Step 2 and Step 4 once. If the same rows come back, treat them as below.
- Only new `OK_recycled_ticker` rows: read each row's `resolved_name` against `edgar_name` and `former_names`. The same company spelled differently (an apostrophe, an abbreviation) is fine. Go on when all are.
- Anything else: stop. Give the operator the printed rows and wait for a ruling. Do not delete the script.

---

### Task 2: Delete the script, its test and its output file

**Files:**
- Delete: `scripts/verify_against_web.py`
- Delete: `tests/test_verify_against_web.py`
- Delete: `output/web_verification.csv`
- Modify: `CLAUDE.md` (the `pytest   # full suite (...` line under Commands)

**Interfaces:**
- Consumes: Task 1's go decision.
- Produces: a tree with no importer of the script. Task 3 removes the remaining mentions.

- [ ] **Step 1: Record the suite's baseline**

Run: `pytest -q 2>&1 | tail -1`
Expected: one line such as `3318 passed, 46 xfailed in …`. Write down both numbers as N passed and X xfailed.

- [ ] **Step 2: Confirm nothing else uses the script**

Run: `grep -rn "verify_against_web\|web_verification" src scripts tests --include='*.py'`

Expected: hits only in `scripts/verify_against_web.py`, `tests/test_verify_against_web.py`, one docstring line in `src/delist_detection/edgar.py` and two in `src/delist_detection/sec_limiter.py`. Any other file: stop and report it.

- [ ] **Step 3: Count the tests that will go**

Run: `grep -c "^def test_" tests/test_verify_against_web.py; grep -c "parametrize" tests/test_verify_against_web.py`
Expected: `8` and `0` (as of 2026-10-07). Call the first number T. If the second is not 0, T is the number of cases `pytest tests/test_verify_against_web.py -q` reports.

- [ ] **Step 4: Delete the three files and run the suite**

```bash
git rm scripts/verify_against_web.py tests/test_verify_against_web.py output/web_verification.csv
pytest -q 2>&1 | tail -1
```

Expected: `N−T passed, X xfailed`, with no failure and no error.

- [ ] **Step 5: Update the test count in `CLAUDE.md`**

In the line that begins `pytest   # full suite (`, replace the passed count with N−T. Leave the rest of the line as it is.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "Remove the web verifier: the script, its test and its output file"
```

---

### Task 3: Remove it from the docs and docstrings

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `docs/data-flow.md`
- Modify: `docs/superpowers/feature-spec.md`
- Modify: `src/delist_detection/edgar.py` (docstring of `sec_get`)
- Modify: `src/delist_detection/sec_limiter.py` (two docstrings)

**Interfaces:**
- Consumes: Task 2's tree.
- Produces: no current doc or docstring names the script.

- [ ] **Step 1: `CLAUDE.md`, five passages**

Delete this whole line under Commands:

```
python scripts/verify_against_web.py     # independent EDGAR cross-check on output/delistings.csv → output/web_verification.csv
```

In the `edgar.py` entry, replace

```
  `EdgarClient`, `sec_http.py` and `verify_against_web.py` share.
```

with

```
  `EdgarClient` and `sec_http.py` share.
```

In the `store.py` entry, replace

```
Every table read — `qlib_adapter`, `accept_review.py`,
  `verify_against_web.py`, and `run_snapshot` for every measurement reader — goes through this module's specs, so
```

with

```
Every table read — `qlib_adapter`, `accept_review.py`,
  and `run_snapshot` for every measurement reader — goes through this module's specs, so
```

Under *SEC fair access*, replace

```
  (`sec_limiter.use_machine_wide_limit()`, installed by the CLI, `default_clients`,
  `verify_against_web.py` and `build_golden_fixtures.py`). `--sec-workers N`
```

with

```
  (`sec_limiter.use_machine_wide_limit()`, installed by the CLI, `default_clients`
  and `build_golden_fixtures.py`). `--sec-workers N`
```

Replace the validation invariant

```
- **Validation is the EDGAR-cross-check loop**, not eyeballing: start from
  `output/review_summary.csv`, work `review.csv` top down, record each
  accepted row in `data/review_decisions.csv`, then re-run
  `classify_universe.py`, then `verify_against_web.py` on
  `output/delistings.csv` (and curl the cited accession) to confirm output
  against an independent path. Drill mismatches to root cause and re-run.
```

with

```
- **Validation is the review loop and the scorecard**, not eyeballing: start
  from `output/review_summary.csv`, work `review.csv` top down, record each
  accepted row in `data/review_decisions.csv`, then re-run
  `classify_universe.py`, then `python scripts/scorecard.py --check` (exit 1
  on a drop or a failing golden or diagnosis `pass` case). To confirm one row
  against an independent path, curl the accession it cites. Drill mismatches
  to root cause and re-run.
```

- [ ] **Step 2: `README.md`, four passages**

Replace

```
see *Severities and accepting a review row* above and *Verifying the output*
below for the independent EDGAR cross-check.
```

with

```
see *Severities and accepting a review row* above.
```

Delete this line from the `scripts/` listing:

```
    verify_against_web.py             Independent EDGAR cross-check → output/web_verification.csv
```

Delete this line from the `output/` listing:

```
    web_verification.csv  Per-row independent cross-check verdict
```

Delete the whole section that starts at `## Verifying the output` and ends with the line `stratified spot-check across buckets rather than the whole table.`, and the `---` line and blank line that follow it. One `---` line must remain between the section before it and `## Known limitations`.

- [ ] **Step 3: `docs/data-flow.md`, three passages**

Replace

```
`edgar.sec_get`, the one request path `EdgarClient`, `sec_http.py` and
`verify_against_web.py` share; `verify_against_web.py` asks it for a single
attempt) before giving up; a 403/429 still raises `EdgarBlocked`
```

with

```
`edgar.sec_get`, the one request path `EdgarClient` and `sec_http.py`
share) before giving up; a 403/429 still raises `EdgarBlocked`
```

Replace

```
  in any worktree, `verify_against_web.py`, `build_golden_fixtures.py`) stays
```

with

```
  in any worktree, `build_golden_fixtures.py`) stays
```

Delete everything from the line

```
`output/web_verification.csv` — independent EDGAR cross-check produced by
```

through the line

```
evidence either way.
```

and one of the blank lines around it, so that a single blank line separates the paragraph before it from `## Downstream integration`.

- [ ] **Step 4: `docs/superpowers/feature-spec.md`, two passages**

Use the day's date as `YYYY-MM-DD`. Replace

```
`sec_id`. `verify_against_web.py` reads `delistings.csv`.
```

with

```
`sec_id`. `verify_against_web.py` read `delistings.csv` until it was removed (YYYY-MM-DD).
```

Replace

```
5. `verify_against_web.py` agreement on the delisting rows is at least the current
   98.9%.
```

with

```
5. `verify_against_web.py` agreement on the delisting rows is at least the current
   98.9%. *(Retired YYYY-MM-DD: the script was removed. `scripts/scorecard.py --check`
   and the truth sets measure this now.)*
```

- [ ] **Step 5: Three docstring lines under `src/`**

In `src/delist_detection/edgar.py`, in `sec_get`'s docstring, replace

```
    (EdgarClient, sec_http, verify_against_web). Each attempt waits for the
```

with

```
    (EdgarClient, sec_http). Each attempt waits for the
```

In `src/delist_detection/sec_limiter.py`, replace

```
    start-up, before any SEC request: the CLI, `pipeline.default_clients`,
    `verify_against_web.py` and `build_golden_fixtures.py` do. Idempotent for one
```

with

```
    start-up, before any SEC request: the CLI, `pipeline.default_clients`
    and `build_golden_fixtures.py` do. Idempotent for one
```

and replace

```
    EdgarClient, sec_http and verify_against_web share) calls this, from any thread. It
```

with

```
    EdgarClient and sec_http share) calls this, from any thread. It
```

- [ ] **Step 6: Check that only historical records still name it**

Run:

```bash
grep -n "Verifying the output\|cross-check" README.md CLAUDE.md
grep -rln "verify_against_web\|web_verification" \
  --include='*.py' --include='*.md' . | grep -v '^./.claude/' | sort
```

Expected: the first command prints nothing. The second prints exactly these nine files:

```
./docs/2026-09-28-handoff-validation.md
./docs/superpowers/feature-spec.md
./docs/superpowers/plans/2026-09-23-sec-request-speed.md
./docs/superpowers/plans/2026-09-23-security-master-and-delistings.md
./docs/superpowers/plans/2026-09-24-review-triage.md
./docs/superpowers/plans/2026-09-26-observation-map.md
./docs/superpowers/plans/2026-10-07-architecture-deepening.md
./docs/superpowers/plans/2026-10-07-remove-web-verifier.md
./docs/validation/2026-09-23-acceptance.md
```

Any other file: open it, remove the mention, and run the command again. A plan or validation report written after 2026-10-07 that records a past run of the script is a historical record. Leave it and say so in the commit message.

- [ ] **Step 7: Check the constraints**

Run each and compare:

```bash
pytest -q 2>&1 | tail -1                         # N−T passed, X xfailed, as in Task 2
PYTHONPATH=src python scripts/scorecard.py --check; echo "exit $?"    # exit 0
git diff --stat HEAD~1 -- src                    # edgar.py 1 line changed, sec_limiter.py 3
git diff --name-only HEAD~1 -- output docs/validation docs/2026-09-28-handoff-validation.md   # only output/web_verification.csv
git diff HEAD~1 -- src | grep '^[-+][^-+]'       # every changed line is docstring text
```

`HEAD~1` is the commit this branch was cut from as long as Task 2's commit is the only one on the branch. Otherwise name that commit.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md README.md docs/data-flow.md docs/superpowers/feature-spec.md \
  src/delist_detection/edgar.py src/delist_detection/sec_limiter.py \
  docs/superpowers/plans/2026-10-07-remove-web-verifier.md
git commit -m "Docs without the web verifier: validation is the review loop and the scorecard"
```

- [ ] **Step 9: Clear the reminder**

Delete the memory file `remove_web_verifier_reminder.md` and its line in `MEMORY.md`, both under `/Users/royeli/.claude/projects/-Users-royeli-repo-github-com-delist-detection/memory/`. The work it reminds about is done.

---

## Log

Carried out 2026-10-08 on branch `remove-web-verifier`, cut from `arch-deepening` at 359f6f9 (PR #9, not yet merged),
with the operator's go-ahead.

- **Task 1.** The last run checked 998 rows: 960 `OK`, 32 `WEAK_no_delist_form`, 3 `OK_recycled_ticker` (WEN, AAN,
  DNB) and 3 `WEAK_no_ma_items`. The check exited 1 on the three `WEAK_no_ma_items` rows: TAHO 2019-03-04, KING
  2016-03-04 and BPYU 2021-08-05. The pipeline classifies each as a merger (231) from a completion report near the
  Form 25 that carries no 8-K item code: a 6-K for TAHO and KING, an item-less 8-K for BPYU (sub-plan 5f,
  `classifier._completion_report`). The verifier looks for 8-K items 2.01 or 5.01 and merger proxies, which these
  filers did not file. The diagnosis truth set records each as a merger, checked at the cited filing. Every
  `WEAK_no_delist_form` row carries a pipeline flag, and EDGAR answered for every row. Ruling (operator,
  2026-10-08): nothing new, go on.
- **Task 2.** The suite went from 3527 passed, 45 xfailed to 3519 passed, 45 xfailed (the script's 8 tests).
  CLAUDE.md's count was 3478, out of date since the architecture program's fix pass. It now reads 3519.
- **Task 3.** Line numbers and module paths had moved (`src/delist_detection/sources/edgar.py` and
  `sources/sec_limiter.py` after architecture step 16, `sources/sec_http.py` in the docs' text). The same changes
  were made to the text as found. Step 6 listed exactly the nine expected files.

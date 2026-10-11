# Sub-plan 5b: Form 25 Reach, Matching and Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every security's real Form 25 is found, matched to the right class and allowed to own its row: a stale
observation or an OTC tail no longer "continues" a security past its removal, a Form 25 shortly before a stale first
sighting or long after the last one is reached, a Form 25 about another class (rights, another tracking group) is
refused, a letterless class takes its letter from its own fails descriptions, the one other CIK in force is read,
and the matched Form 25's notice and dates outrank the continued-filings default and a later SEC revocation.

**Architecture:** The finder (`delistings.DelistingFinder`) gets one test of whether a security went on after a Form
25 (`_continued`: listed today, the issuer's own exchange move with an 8-A12B, or its own CUSIPs trading on, never
after a removal under rule 12d2-2(b)), one judgement of a Form 25 against the security (`_judge`), an early window
before the floor, a late reach past the alive window, and the other CIK's Form 25s. Its context
(`pipeline._context_builder`) gains the fails-row tests and a letter hint per security; a new stage 4c computes the
other CIK in force. The classifier reads every Item 1.03 section, lets a matched Form 25's notice decide a
continued-filings row, ignores a revocation filed after the matched Form 25, and the end-of-era resolver puts a
confirmed bankruptcy before a completed sale. A real-case fixture set replays stage 5 offline for 36 securities.

**Tech Stack:** Python 3.10+, pytest (offline: `FakeEdgar`, the doubles, a fixture set built once from the local
caches), the SEC fails-to-deliver zips, EDGAR, MIDAS, the Nasdaq halt feed, OpenFIGI, the Claude Code Workflow tool
for the truth loop (sonnet agents).

**Spec:** `docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md` (section 1, the truth loop and
acceptance; section 2.1, rulings R1 and R2; section 3 "5b"). Roadmap:
`docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md`. Design source (read it first):
`docs/superpowers/plans/research/2026-10-04-5b-form25-reach.md` (section 7 is the design; sections 4 to 6 its
guards, blast radius and truth conflicts). The format exemplar is
`docs/superpowers/plans/2026-10-03-reset-5a-line-continuity.md`; 5a's operator report is
`output/diagnose_unknown_report/loop/5a/report.md`. **Base commit: `cc631e1`.**

## Global Constraints

- In this worktree run every command from the repo root with `PYTHONPATH=src` and
  `~/miniconda3/envs/rdagent4qlib/bin/python` (the editable install points at the main checkout). Run pytest as
  `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest` with no extra `-q` (addopts has it).
- Tests are fully offline: `FakeEdgar` (tests/conftest.py), the doubles in tests/test_pipeline.py, plain row
  fixtures, and one real-case set, `tests/fixtures/form25_reach/`, built once from the local cache by the committed
  offline builder `scripts/build_form25_fixtures.py` (Task 1). Never add network to a test.
- `output/` is regenerated only in Task 15. Every earlier task keeps the full suite green against the committed
  output: 2053 passed and 245 xfailed at `cc631e1`, plus each task's new tests (2161 passed, 245 xfailed after
  Task 12; each task names its count).
- "Append to `<file>`" means: at the end of the file, after two blank lines. A block's own imports (marked
  `# noqa: E402`) stay inside the block. "Replace X with Y" quotes X exactly as the file holds it after the
  earlier tasks; when X is not found once, stop and report rather than adapt it.
- The rules are research section 7 with its measured narrowings (operator, 2026-10-04, binding):
  - **C**: an observation never continues a security; listed today, the issuer's exchange move (R7), or its own
    CUSIPs' fails rows under any trading symbol (at least 20 rows over at least 20 days at 2 or more prices after
    the effective date plus 5 days) do, and nothing but listed today continues a removal under rule 12d2-2(b).
  - **R7**: only the issuer's own Form 25 (form `25` or `25/A`, not under (b)) with its 8-A12B within 10 days.
  - **E**: Form 25s in [floor − 365 d, floor) are judged only when `listed_today is False`, only when no group from
    the floor on is definitive, only when the security does not trade after them, and only the latest early group.
  - **L**: a Form 25 after every sibling's alive window reaches the security only when its own CUSIP has a trading
    fails row in the 30 days before the filing.
  - **R3**: a Form 25 that "relates solely to" a non-common class, or whose lettered tracking-stock segments name no
    word of the security's name, is not the security's.
  - **R2**: a letterless class takes the one letter its own fails descriptions name, only for a letter no sibling's
    share class carries (Ruling 2 below).
  - **R5**: the other CIK is read only when it was the issuer in force on every sighting (PRGO: none).
  - **R6a**: a revocation filed after a matched Form 25 the security did not trade past never decides the row.
  - **R6b**: the continued-filings default (end-of-era branch `continued_filings`) gives way to the matched Form 25
    only when its EX-99.25 notice says "acquired by" or "converted into ... $X / cash" and says nothing of a
    reclassification, a holding company or a reorganization (APA, CMCSK, HHC and HUB-B stay continuations).
  - **5g sub-rule 2, pulled into 5b**: a confirmed 8-K item 1.03 beats a 2.01 (ASNA 2020 is a bankruptcy).
  - The sibling-alive slack stays (`SIBLING_ALIVE_BEFORE_DAYS` 30): LIN, APTV and LH keep no false ending.
  - The deficiency wording of research section 7's adjuncts.
- Must not change, pinned by tests with real tickers (Task 1's fixture set, `STAY`): APA (the Chicago withdrawal of
  2020 and the 2021 holdco), HUB-B, CMCSK, HHC, MSG 2015, LIN, APTV, LH, LAUR, PRGO, JNC, AT, DISCK, CWENA and LVNTA
  (a `pass` truth case); MWW 2008's transfer is kept beside its new 2016 ending.
- Truth: the conflicts G1 to G4 and the re-routes are already applied (`cc631e1`); no task edits them. DISCA 2022
  and EQC 2025 are pre-ruled (Task 16). The loop judges MDRX, EPE, KWK, EK and ABK by the G4 reading: the exchange
  removal is the ending, not a later OTC merger.
- Do not edit or commit `data/golden_lifecycles.csv` or `data/accuracy_audit.csv`. A golden `known_wrong` case that
  starts passing is the operator's to flip: list it and ask (Task 17).
- A scorecard floor entry is raised only by `scripts/scorecard.py --raise-floor`. It is lowered by hand only when the
  drop is traced to a truth correction or to a change the loop settled as right, with the reason in the commit.
- Implementers and reviewers run on model `sonnet`; each task names its tier. Tasks 14 to 17 are run by the
  controller; Task 14's whole-branch review runs on `opus`. The truth loop runs at most 3 rounds and at most 5
  agents at a time.
- SEC access for the network run: `DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock`, one
  SEC client at a time across sessions; Bash `allowed_domains`: data.sec.gov, www.sec.gov, efts.sec.gov,
  api.openfigi.com, api.nasdaq.com, www.nasdaqtrader.com, api.openai.com.
- Every data file a script writes goes through `atomic_io.write_atomic`.
- Never merge or push; commits stay on the worktree branch. Commit messages end with the session's attribution lines
  (Co-Authored-By, Claude-Session).
- Out of scope: the line successors' Form 25 search (CRC, DYN, ODP), the cover-page hardening for "12(b): None",
  dropping A theme 1's suffix (5i), RLGY to HOUS (5h), CLNY to DBRG (needs a live check), update_truth's payout legs,
  the malformed-record retry and the `casesPath` location (Ruling 9).

## Review Focus

1. A security not listed today whose Form 25 sits at its own CUSIP switch (Acxiom/LiveRamp 2018): C must let the
   new CUSIP's fails rows continue it, so the own-switch skip still applies and no false ending appears (Task 6, test
   `test_a_form25_at_the_own_cusip_switch_of_a_security_not_listed_today_still_removed_the_old_cusip`).
2. A Form 25 group that holds the exchange's 25-NSE first and the issuer's own Form 25 with its 8-A12B a day later:
   the move must be found on the issuer's filing of the group, not only on the earliest (Task 7, test
   `test_the_issuers_own_form25_in_a_group_with_the_exchanges_moves_the_class`).
3. An early-window Form 25 whose text is not cached (the run fetches about 303): it must raise no
   `form25_unreadable` row (the window is the fallback's territory) and stay available to the fallback (Task 8, test
   `test_an_early_form25_whose_text_cannot_be_read_raises_no_review_row`).
4. Two letterless siblings whose fails both say "CL A" (a FIGI line and its duplicate placeholder): the hint must
   not pick one; the Form 25 stays ambiguous as before (Task 11, test
   `test_two_letterless_siblings_both_hinted_the_letter_stay_tied`).
5. The other CIK in force removing another class of its own (a preferred stock): matched against the security alone,
   it must still be refused by kind and letter (Task 12, test
   `test_the_other_cik_in_forces_form25_of_another_class_is_no_delisting`).

## Rulings made in this plan

Each is a choice the research or the binding decisions left open; the cost if wrong is named.

1. **R7's window is 10 days, on the issuer's own Form 25 only, in both places it acts** (`_continued` and the
   rebucket of an `unknown` row). The research text says 10 days; its probe used 30 in `_continued`. MSG 2015's
   8-A12B is exactly 10 days before its Form 25, MWW 2008's 4, KHC's 0. Cost: an issuer move with its 8-A12B 11 to 30
   days off is not continued by R7 (it still is when its CUSIP trades on).
2. **R2 fills only a letter no sibling's share class carries.** As the research wrote it (a letterless sibling takes
   its hint everywhere), the prototype broke LVNTA 2018, a `pass` truth case: the duplicate placeholder
   CIK1355096-COMMON's fails say "SER A", so it tied with LVNTA's own Series A. Narrowed, SPWRA still matches, LGFA
   still moves (2025 merger), LVNTA is unchanged. Cost: a letterless class whose letter another sibling's class
   also carries is not helped.
3. **R3 is a check on the security itself before matching** (`form25.other_class`), as the research measured it, not
   a filter inside `match_securities`. The group words drop the issuer's EDGAR name words and SPECIAL, NON, VOTING,
   NONVOTING, NEW, OLD and ORDINARY.
4. **5g sub-rule 2 is two changes.** ASNA's 1.03 8-K failed confirmation because its first "Item 1.03" is a
   cross-reference long enough to read as the section (research section 5 says only "the 1.03 is not confirmed").
   `_confirms_bankruptcy` now reads every Item 1.03 section (5 cached texts change, all genuine Chapter 11 8-Ks:
   ASNA, GNC, Rite Aid twice, Avaya), and the classifier's existing bankruptcy branch then decides ASNA. The
   resolver also gets the sub-rule itself: a confirmed 1.03 8-K in its item window, on or before a completed sale
   that would be branch 4, is a liquidation (470). No real case of the run reaches that branch; synthetic tests pin
   it.
5. **E's refused filings are not handed to the fallback**, except one whose text could not be read. An early filing
   E refused (another class, traded after) is not revived by `_early_group`. The early delisting carries
   `observed_after_delisting`, as the fallback's early group does.
6. **R5 reads the other CIK's Form 25s from the floor on only, matched against the security alone** (no early or
   late reach under it), and the delisting carries the filer CIK (`Delisting.cik`), which the classifier, the
   payout extraction and the successor search then read.
7. **R6b keeps a merger answer of the Form 25 path** (NTY's "Merger filing DEFM14A 2010-08-24", BMET's DEFM14A)
   and turns any other answer into 231 with the reason "Form 25 <date> notice: the class was acquired", dropping
   `no_evidence_default`. `evidence["end_of_era"]` reads `form25_notice`.
8. **No new review flag.** R3's and L's refusals are silent, as the measured design; R5 rows show their filer CIK.
9. **Deferred**: the line successors' Form 25 search (research adjunct). No truth case needs it (DYN 2010 passes, ODP
   is 5c's, CRC 5h's), it would add endings to securities stage 4b adds with no target behind them, and it was not
   measured. The cover hardening ("12(b): None") is moot: under C a removal under (b) is never continued, so the
   cover skip is not reached for RHD.

## Expected outcome (an offline replay of this plan's code over the cached data)

A prototype of every task, replayed over stage 5 for all 2,233 securities with network refused (Task 14's replay),
changes **42 securities: 22 in the truth set, 20 outside it**. The fixture harness reproduces the replay exactly
for its 36 cases. Stage 5 only: stages 5b to 10 (payouts, successors, handoffs, the clip, the contract) run in Task
15.

**Truth cases (22).** The rule that moves each, and what is left after 5b:

| case | after 5b (stage 5) | left for |
| --- | --- | --- |
| XMSR | merger 231, last trade 2008-07-28 (halt) | stock 4.6 SIRI (5e, 5f) |
| SOV | merger 231, 2009-01-29 (notice) | stock 0.3206 STD (5e, 5f) |
| TXU | merger 231, delisted 2007-11-02, 2007-10-10 (E) | $69.25 if extracted; USD (5f) |
| STN | merger 231, 2007-11-18, 2007-11-07 (E) | $90.00; USD (5f); golden STN may XPASS |
| BMET | merger 231, 2007-10-05 (E, R3, R6b) | last trade from the 8-K 3.01 (5d); $46.00; USD |
| MWW | 2016-11-11 merger 231, 2016-10-31 (L); the 2008 transfer kept | $3.40; USD |
| NTY | merger 231 (R6b) | $55.00; USD |
| RHDC | 570, 2008-12-31 (C, wording) | otc_print ticker RHDC (5g) |
| IDARQ | 570, 2008-11-19 (C) | drop reason `price` (5g); 11-20 (5d) |
| LKSD | 570, 2019-12-27 (C) | internal 2019-12-26 (5d); otc_print LKSD (5g) |
| KHC | 304, itself (R7): no ending | **should pass** |
| Liberty Series A | no delisting (R3) | **should pass** |
| SPWRA | 2011-11-26 304, successor found in stage 9 (R2) | continuation (5c); passes if stage 9 links BBG000FVQ185 |
| SPB | merger 200, 2018-07-13 under CIK 1487730 (R5) | **passes** if the handoff rebuckets it to the continuation; a reconciled stock leg keeps the merger (5c, R1) |
| MTCH | merger 200, 2020-06-30 under CIK 1575189 (R5) | stock 1.0337 (5f) if the handoff keeps the merger |
| CNB | 470 (R6a) | **should pass** (its one mismatch is the drop reason) |
| IMB | 470 (R6a, C) | otc_print ticker IDMC (5g) |
| TMA | 580 (R6a, C) | drop reason `price` (5g) |
| RAD | 470 (the 1.03 sections) | 5d and 5g fields |
| MNI | 2020-03-02 470 (C) | 5g fields |
| ASNA | 470 (the 1.03 sections) | 5g fields |
| LTRPA | 570 at the 2023-11-30 Nasdaq removal (C, ruling G4) | drop reason `price` (5g) |

The other 5b case-map rows do not move: the "merger relabelled" cases of group A1 (research section 2) already have
the right exit kind (their cash_currency is 5f's, their suffix 5i's; PRE, CCU and DPL need only USD since the G1
ruling), and DOW (5c), SUG (5f), TMUSR (5d), WFT (5g) and JEF (5e) keep their sub-plans. Of the 18 truth rows
with fixed_by 5b, KHC, Liberty Series A and probably SPB pass; Task 17 relabels the rest.

**Outside the truth set (20), the regressions the loop diagnoses:**
- New merger endings where a stale observation or a cover continued the Form 25 (C): MER 2009 (the 2008 transfer
  row stays), PSD, SIE, TRB, LYO, HET, UB, BKC, NWA; and DISCA 2022 (pre-ruled, Task 16).
- Early reach (E): SKYF 2007.
- Exchange removals under (b) that now end the security (C; the G4 reading): EK 2012, ABK 2010, KWK 2015, MDRX 2024,
  EPE 2019 (moves from the 2019-10 bankruptcy to the 2019-06 removal).
- SSCC 2009: re-dated to its 2009-02-17 Form 25 (C).
- GNC 2020: 580 becomes 470 (the 1.03 sections).
- LGFA 2025: a merger at the separation (R2).
- EQC 2025: a transfer with no successor (pre-ruled, Task 16).
- Possibly KSE, PPP and SLR: their early-window Form 25 raws are not cached; E may re-date their merger.

Each brings its contract row and its security_history ranges (clipped at the new ending; for an E ending, stage 5b's
backfilled CUSIPs before the first observation).

## File Structure

Create:
- `scripts/build_form25_fixtures.py`: the offline builder of `tests/fixtures/form25_reach/`.
- `tests/fixtures/form25_reach/{cases.json,ftd_rows.csv.gz,edgar.json.gz,midas.json,halts.json}` (built, committed,
  about 0.9 MB).
- `tests/form25_cases.py`: the replay harness (the stage-5 code over the fixture).
- `tests/test_form25_reach_cases.py`: the real cases (`MOVES`, `STAY`, `RULES_DONE`).

Modify:
- `src/delist_detection/evidence.py` (Tasks 2, 3), `classifier.py` (Tasks 2, 4, 5), `end_of_era.py` (Task 2),
  `form25.py` (Tasks 5, 6, 9, 11), `ftd.py` (Task 6), `delistings.py` (Tasks 6 to 10, 12), `pipeline.py` (Tasks 6, 10,
  11, 12).
- Tests: `test_evidence.py`, `test_classify_event.py`, `test_end_of_era.py`, `test_form25.py`, `test_ftd.py`,
  `test_delistings.py`, `test_pipeline.py`, `test_run_provenance.py`.
- `CLAUDE.md`, the roadmap.
- Data, by Tasks 15 to 17: `output/`, `data/diagnosis_truth.csv`, `data/diagnosis_truth_changes.csv`,
  `data/scorecard.json`, `output/diagnose_unknown_report/loop/` (the ledger, rounds, report).

---

### Task 1: Real-case fixtures and the stage-5 replay harness

Tier: standard (the builder reads the local caches; its output is committed).

This task pins today's behaviour; every later task moves its own cases by adding its rule to `RULES_DONE`. Its tests
pass on the first run: they characterize the code before 5b.

**Files:**
- Create: `scripts/build_form25_fixtures.py`, `tests/form25_cases.py`, `tests/test_form25_reach_cases.py`
- Create (by the builder): `tests/fixtures/form25_reach/{cases.json,ftd_rows.csv.gz,edgar.json.gz,midas.json,halts.json}`

**Interfaces:**
- Consumes: today's `pipeline._context_builder(securities, sightings, answers, ftd, sec_cusips)` and
  `pipeline._IssuerAnswers`, `DelistingFinder`, `DelistClassifier`, `MidasClient`, `NasdaqHaltClient`.
- Produces (tests/form25_cases.py): `DATA`, `EDGAR`, `FixtureEdgar` (with `raws_read`), `FixtureMidas`,
  `FixtureHalts`, `world() -> (securities, cusips, FtdIndex)`, `finder(edgar=None)`, `context(sec_id)`,
  `find(sec_id, edgar=None, **kw)`, `outcome(sec_id, **kw) -> (list[tuple], list[str])`. Task 12 adds
  `context(sec_id, *, other_cik=...)`. tests/test_form25_reach_cases.py: `RULES_DONE`, `MOVES`, `STAY`.

- [ ] **Step 1: Write the builder**

Create `scripts/build_form25_fixtures.py`:

```python
"""Build tests/fixtures/form25_reach/ from the local caches, once (sub-plan 5b): the real cases whose Form 25
search, matching and ownership tests/test_form25_reach_cases.py replays offline through the finder
(`delistings.DelistingFinder`) and the pipeline's own context builder (`pipeline._context_builder`).

  PYTHONPATH=src python scripts/build_form25_fixtures.py          # -> tests/fixtures/form25_reach/

Offline: it reads the committed output/ (each case's securities, eras and observations, CUSIPs, whether it is
listed today, its issuer in force), the cached SEC fails-to-deliver zips (cache/sec_data/ftd), the cached EDGAR
answers (cache/edgar: every SEC request is refused, so a missing answer is left out, never fetched), the cached
MIDAS quarter summaries (cache/sec_data/midas) and Nasdaq halt days (cache/nasdaq_halts). It writes:

- cases.json: each case (its note, its other CIK in force) and every security the cases need (the cases and the
  other securities of their issuers: CIK, class, name, kind, eras with their observations, CUSIPs, line tickers,
  whether it is listed today);
- ftd_rows.csv.gz: every fails row of a case's CUSIPs in the run's window, and for each other security of its
  issuer the first and last row per (CUSIP, symbol) and the first per (CUSIP, description): what its span and
  its class letter read;
- edgar.json.gz: each CIK's EDGAR names, tickers and the filings the finder and the classifier read (every Form 25,
  8-K, periodic report, Form 15, revocation, 8-A12B and merger filing, in EDGAR's order), every cached Form 25
  raw, every cached 8-K text with item 1.03 or 3.01, and the first 12,000 characters (the cover page) of every
  annual report filed within COVER_DAYS of a Form 25;
- midas.json: the MIDAS quarters cached, and each case ticker's days with exchange volume near its Form 25s and
  its last sighting;
- halts.json: the Nasdaq code-D halts of the case tickers on the cached halt days.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import delist_detection.edgar as edgar_mod  # noqa: E402


def _refuse(*args, **kwargs):
    raise RuntimeError("build_form25_fixtures is offline: a missing cache entry is left out")


edgar_mod.sec_get = _refuse
from delist_detection.atomic_io import write_atomic  # noqa: E402
from delist_detection.edgar import EdgarClient  # noqa: E402
from delist_detection.form25 import FORM25_FORMS  # noqa: E402
from delist_detection.ftd import FtdIndex, parse_ftd_lines, period_of  # noqa: E402
from delist_detection.listing_status import ANNUAL_FORMS  # noqa: E402
from delist_detection.nasdaq_halts import parse_halts_rss  # noqa: E402

AS_OF = date(2026, 9, 25)                       # the committed run's date
FTD_WINDOW = (date(2007, 12, 17), AS_OF)        # the committed run's fails window
COVER_DAYS = 460                                # annual reports kept this close to a Form 25 (their cover page)
MIDAS_BEFORE, MIDAS_AFTER = 80, 25              # MIDAS days kept around each Form 25...
SEEN_BEFORE, SEEN_AFTER = 620, 140              # ...and around the last sighting (the fallback's anchors)
KEPT_FORMS = re.compile(r"^(?:25|25-NSE|25/A|25-NSE/A|8-K.*|10-K.*|10-Q.*|20-F.*|40-F.*|15-.*|REVOKED|NT .*"
                        r"|8-A12B.*|DEFM14A|DEFM14C|PREM14A|SC 14D9.*|SC TO-T.*|SC TO-I.*|SC 13E3.*|425|S-4.*)$")
OTC_LIKE = re.compile(r"^[A-Z]{4}[QFEY]$|ZZZZ$|XXXX$")

# The cases: securities of the committed run, each with what it pins
CASES = {
    "BBG000C070N2": "XMSR 2008: a 25-NSE a stale observation continued (C)",
    "BBG000JXRXK2": "SOV 2009: a 25-NSE a stale observation and a cover continued (C)",
    "BBG000BVW841": "TXU 2007: a 25-NSE before the first sighting (E)",
    "CIK898660-COMMON": "STN 2007: a 25-NSE before the first sighting (E)",
    "CIK351346-COMMON": "BMET 2007: a rights-only Form 25 (R3), the 25-NSE before the first sighting (E), "
                        "the notice's 'acquired by' (R6b)",
    "BBG000DGZ1B6": "MWW 2016: a 25-NSE after the alive window (L); the 2008 transfer stays",
    "BBG000BPTDN6": "NTY 2010: the notice's cash conversion owns the row (R6b)",
    "BBG000BRF6B5": "RHD 2009: a removal under (b) the OTC tail continued (C), a market-cap 3.01 (wording)",
    "BBG000PSSG77": "IAR 2008: a removal under (b) the OTC tail continued (C)",
    "BBG009R0CVG1": "LKSD 2020: a removal under (b), OTC under the same symbol (C)",
    "BBG005CPNTQ2": "KHC 2026: the issuer's Form 25 with its 8-A12B (R7)",
    "CIK1355096-SERIES-A": "Liberty Series A 2011: a 25-NSE of the Capital and Starz groups (R3)",
    "CIK867773-COMMON": "SPWRA 2011: a Class A & Class B 25-NSE, two letterless commons (R2)",
    "BBG0038K9G41": "LVNTA 2018: a Series A 25-NSE its own Series A takes, beside a duplicate placeholder whose "
                    "fails say SER A (R2 must not tie them)",
    "BBG000P4BQM9": "SPB 2018: the old Spectrum Brands' 25-NSE under its own CIK (R5)",
    "BBG00B6WH9G3": "MTCH 2020: the old Match Group's 25-NSE under its own CIK (R5)",
    "BBG000BF2JS9": "CNB 2009: a revocation after the 25-NSE (R6a)",
    "BBG000BLY636": "IMB 2008: a revocation after the 25-NSE (R6a)",
    "BBG000BBG3P1": "TMA 2008: a revocation after the 25-NSE (R6a)",
    "BBG000BGZ9V9": "ASNA 2020: a bankruptcy 8-K whose first Item 1.03 is a cross-reference (5g sub-rule 2)",
    "BBG000BP62Y3": "MNI 2020: a removal under (b) the OTC tail continued (C)",
    "BBG005DKMJ67": "LTRPA 2023: a Nasdaq removal under (b), then an OTC merger (C, ruling G4)",
    "BBG000BC2C10": "APA: the Chicago withdrawal of 2020 (regional) and the 2021 holdco (R6b refuses)",
    "CIK48898-CLASS-B": "HUB-B 2015: a reclassification (R6b refuses)",
    "BBG000BFTJ91": "CMCSK 2015: a reclassification, no notice text (R6b refuses)",
    "BBG000MJRJJ2": "HHC 2023: a holding company's formation (R6b refuses)",
    "CIK1469372-CLASS-A": "MSG 2015: the issuer's Form 25 with its 8-A12B ten days earlier (continued)",
    "BBG00GVR8YQ9": "LIN: an old redomiciled line the sibling slack keeps from a false ending",
    "BBG001QD41M9": "APTV: an old redomiciled line the sibling slack keeps from a false ending",
    "BBG000D9DMK0": "LH: an old holdco line the sibling slack keeps from a false ending",
    "BBG00B4Z2YX0": "LAUR: listed today, so no early reach",
    "BBG000CNFQW6": "PRGO: two CIKs in force, so no other CIK (R5) and no 2013 ending",
    "BBG000CS7CB8": "JNC 2007: an early group the fallback finds today",
    "CIK65873-COMMON": "AT 2007: an early group the fallback finds today",
    "BBG000VMWHH5": "DISCK 2022: an exchange's 25-NSE beside an 8-A12B for the new class (no R7)",
    "BBG004P33PN3": "CWENA 2026: an exchange's 25-NSE beside an 8-A12B/A (no R7)",
}


# CIKs whose filings are kept though no case reads them: Perrigo Company's (in force for PRGO until 2013), to show
# what reading it would do
EXTRA_CIKS = (820096,)


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


def _day(s: str) -> date:
    return date.fromisoformat(s[:10])


def _securities(repo: Path) -> tuple[dict, dict, dict, dict, dict]:
    """The committed run's securities, eras (with observations), CUSIPs, ticker ranges and issuers in force."""
    secs = {r["sec_id"]: r for r in _read(repo / "output/securities.csv")}
    eras: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in _read(repo / "output/observation_map.csv"):
        if r["sec_id"]:
            eras[r["sec_id"]][r["era"]].append([r["ticker"], r["as_of"], r["name"], r["cusip"], r["pin_cik"]])
    cusips: dict[str, list[str]] = defaultdict(list)
    for r in sorted(_read(repo / "output/cusip_history.csv"), key=lambda r: (r["valid_from"], r["cusip"])):
        if r["cusip"] not in cusips[r["sec_id"]]:
            cusips[r["sec_id"]].append(r["cusip"])
    history: dict[str, list[dict]] = defaultdict(list)
    for r in _read(repo / "output/ticker_history.csv"):
        history[r["sec_id"]].append(r)
    inforce: dict[str, set[str]] = defaultdict(set)
    for r in _read(repo / "output/contract/security_history.csv"):
        if r["issuer_id"]:
            inforce[r["sec_id"]].add(r["issuer_id"])
    return secs, eras, cusips, history, inforce


def _line_tickers(eras: dict[str, list], history: list[dict]) -> list[str]:
    """The tickers stage 4b's line follow found (not stored in output/): ticker_history tickers from fails rows
    that the security was never observed under, not OTC-like, running past its last observation."""
    seen = {k.split("@")[0] for k in eras}
    last = max((o[1] for obs in eras.values() for o in obs), default="")
    return sorted({r["ticker"] for r in history if r["ticker"] not in seen and r["source"] == "ftd"
                   and not OTC_LIKE.search(r["ticker"]) and (r["valid_to"] == "" or r["valid_to"] > last)})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "form25_reach")
    p.add_argument("--repo", type=Path, default=ROOT)
    args = p.parse_args(argv)
    repo, out = args.repo, args.out
    secs, eras, cusips, history, inforce = _securities(repo)
    by_cik: dict[str, list[str]] = defaultdict(list)
    for sid, s in secs.items():
        if s["issuer_cik"]:
            by_cik[s["issuer_cik"]].append(sid)
    needed = set(CASES) | {x for sid in CASES for x in by_cik.get(secs[sid]["issuer_cik"], [])}
    others = {sid: int(next(iter(inforce[sid]))) for sid in CASES
              if len(inforce.get(sid, ())) == 1 and next(iter(inforce[sid])) != secs[sid]["issuer_cik"]}
    ciks = sorted({int(secs[sid]["issuer_cik"]) for sid in needed if secs[sid]["issuer_cik"]} | set(others.values())
                  | set(EXTRA_CIKS))

    # fails rows: every row of a case's CUSIPs; a sibling's span and descriptions
    ftd = FtdIndex.load(LocalFtd(repo / "cache/sec_data/ftd"), *FTD_WINDOW,
                        cusips={c for sid in needed for c in cusips.get(sid, [])})
    rows = set()
    for sid in needed:
        for c in cusips.get(sid, []):
            got = ftd.by_cusip(c)
            if sid in CASES:
                rows.update(got)
                continue
            ends, descs = {}, {}
            for r in got:
                ends.setdefault((r.cusip, r.symbol), [r, r])[1] = r
                descs.setdefault((r.cusip, r.description), r)
            rows.update(x for pair in ends.values() for x in pair)
            rows.update(descs.values())

    # EDGAR
    edgar = EdgarClient(repo / "cache/edgar", user_agent="build_form25_fixtures fixtures@example.com", today=AS_OF)
    issuers, raws, texts = {}, {}, {}
    form25_days: dict[int, list[date]] = {}
    for cik in ciks:
        sub = _cached(edgar.submissions, cik, default={}) or {}
        filings = [f for f in _cached(edgar.recent_filings, cik, default=[]) if KEPT_FORMS.match(f.form or "")]
        issuers[str(cik)] = {"name": sub.get("name", ""), "formerNames": sub.get("formerNames") or [],
                             "tickers": sub.get("tickers") or [], "exchanges": sub.get("exchanges") or [],
                             "sic": str(sub.get("sic") or ""),
                             # in EDGAR's own order, which breaks the classifier's ties between filings
                             "filings": [[f.accession, f.form, f.filing_date, f.report_date, f.items, f.primary_doc]
                                         for f in filings]}
        f25 = [f for f in filings if f.form in FORM25_FORMS]
        form25_days[cik] = [_day(f.filing_date) for f in f25]
        for f in f25:
            raw = _cached(edgar.fetch_filing_raw, cik, f.accession, default="")
            if raw:
                raws[f.accession] = raw
        for f in filings:
            if f.form.startswith("8-K") and {"1.03", "3.01"} & f.item_set:
                text = _cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                if text:
                    texts[f.accession] = text
            elif f.form in ANNUAL_FORMS and any(abs((_day(f.filing_date) - d).days) <= COVER_DAYS
                                                for d in form25_days[cik]):
                text = _cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                if text:
                    texts[f.accession] = text[:12000]

    # MIDAS and halts, for every symbol a case's sightings carry
    symbols: dict[str, set[str]] = {}
    windows: dict[str, list[tuple[date, date]]] = {}
    for sid in CASES:
        s = secs[sid]
        own = {k.split("@")[0] for k in eras[sid]} | set(_line_tickers(eras[sid], history[sid]))
        syms = own | {r.symbol for c in cusips.get(sid, []) for r in ftd.by_cusip(c)}
        symbols[sid] = {x for x in syms if x and any(ch.isalpha() for ch in x)}
        days = [d for cik in {int(s["issuer_cik"])} | ({others[sid]} if sid in others else set())
                for d in form25_days.get(cik, [])]
        last = max([o[1] for obs in eras[sid].values() for o in obs]
                   + [r.date for c in cusips.get(sid, []) for r in ftd.by_cusip(c) if r.symbol in own])
        windows[sid] = ([(d - timedelta(days=MIDAS_BEFORE), d + timedelta(days=MIDAS_AFTER)) for d in days]
                        + [(_day(last) - timedelta(days=SEEN_BEFORE), _day(last) + timedelta(days=SEEN_AFTER))])
    midas_dir = repo / "cache/sec_data/midas"
    quarters = sorted(p.name[:7] for p in midas_dir.glob("*_q*.json.gz"))
    midas: dict[str, dict[str, list[str]]] = {}
    for p in sorted(midas_dir.glob("*_q*.json.gz")):
        summary = json.loads(gzip.decompress(p.read_bytes()))
        for sid in CASES:
            for t in symbols[sid]:
                for d in summary.get(t, []):
                    if any(lo <= _day(d) <= hi for lo, hi in windows[sid]):
                        midas.setdefault(p.name[:7], {}).setdefault(t, []).append(d)
    halts: dict[str, list[list[str]]] = {}
    wanted = {t for v in symbols.values() for t in v}
    for p in sorted((repo / "cache/nasdaq_halts").glob("*.xml")):
        for h in _cached(parse_halts_rss, p.read_bytes(), default=[]):
            if h.reason == "D" and h.symbol in wanted:
                halts.setdefault(p.stem, []).append([h.symbol, h.name, h.market, h.reason, h.halt_date.isoformat(),
                                                     h.halt_time, h.resumption_date.isoformat()
                                                     if h.resumption_date else ""])

    out.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "cusip", "symbol", "description", "price"])
    for r in sorted(rows, key=lambda r: (r.date, r.cusip, r.symbol, r.description, r.price or 0)):
        w.writerow([r.date, r.cusip, r.symbol, r.description, "" if r.price is None else r.price])
    write_atomic(out / "ftd_rows.csv.gz", gzip.compress(buf.getvalue().encode(), mtime=0))
    securities = {}
    for sid in sorted(needed):
        s = secs[sid]
        securities[sid] = {"issuer_cik": int(s["issuer_cik"]) if s["issuer_cik"] else None,
                           "share_class": s["share_class"], "name": s["name"], "security_type": s["security_type"],
                           "observed": s["observed"] == "true", "figi_source": s["figi_source"],
                           "cusips": cusips.get(sid, []), "line_tickers": _line_tickers(eras[sid], history[sid]),
                           "listed": any(r["valid_to"] == "" for r in history.get(sid, [])),
                           "eras": {k: sorted(v, key=lambda o: o[1]) for k, v in sorted(eras[sid].items())}}
    cases = {sid: {"note": note, "other_cik": others.get(sid)} for sid, note in CASES.items()}
    json_out = {"as_of": AS_OF.isoformat(), "ftd_from": FTD_WINDOW[0].isoformat(), "cases": cases,
                "securities": securities}
    for name, data in (("cases.json", json_out),
                       ("midas.json", {"quarters": quarters, "days": midas}),
                       ("halts.json", halts)):
        write_atomic(out / name, json.dumps(data, indent=1, sort_keys=True) + "\n")
    edgar_json = json.dumps({"issuers": issuers, "raws": raws, "texts": texts}, sort_keys=True) + "\n"
    write_atomic(out / "edgar.json.gz", gzip.compress(edgar_json.encode(), mtime=0))
    print(f"{len(cases)} cases, {len(securities)} securities, {len(rows)} fails rows, {len(ciks)} CIKs, "
          f"{len(raws)} Form 25 raws, {len(texts)} texts, {sum(len(v) for q in midas.values() for v in q.values())} "
          f"MIDAS days, {sum(len(v) for v in halts.values())} halts -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Build the fixtures**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/build_form25_fixtures.py`
Expected: about 20 seconds, then
`36 cases, 52 securities, 30910 fails rows, 38 CIKs, 81 Form 25 raws, 91 texts, 7184 MIDAS days, 4 halts -> .../tests/fixtures/form25_reach`.
The planning build gave these sha1 sums (`shasum tests/fixtures/form25_reach/*`); the build is deterministic and
does not depend on the code under change, so a difference means the local cache changed since planning (stop and
report it):

```
3e60e4767d341d6a67c24f7565579e8906100f7a  cases.json
6ac7806bbb6e7bb08bd1cccc828bec41c6341e19  edgar.json.gz
cad586a6f3877d78abbe5daeffafce590fa12323  ftd_rows.csv.gz
06f71a46e7a4ff34a17db7ecfa1f553472cc21bf  halts.json
403521d5f64ab8275c45e2c7e930c3025fb340b6  midas.json
```

- [ ] **Step 3: Write the harness**

Create `tests/form25_cases.py`:

```python
"""Sub-plan 5b's real cases, replayed offline: tests/fixtures/form25_reach/ (built once from the local caches by
scripts/build_form25_fixtures.py) holds each case's security, the other securities of its issuer, their fails
rows, and the EDGAR, MIDAS and Nasdaq-halt answers the finder reads. `find(sec_id)` runs the run's own stage-5
code over them: the pipeline's context builder (`pipeline._context_builder`) and `delistings.DelistingFinder`."""
from __future__ import annotations

import csv
import gzip
import io
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from delist_detection import pipeline
from delist_detection.classifier import DelistClassifier
from delist_detection.delistings import Delisting, DelistingFinder
from delist_detection.edgar import EdgarSubmission
from delist_detection.figi_resolution import security_kind
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.history import ticker_sightings
from delist_detection.midas import MidasClient
from delist_detection.nasdaq_halts import Halt, NasdaqHaltClient
from delist_detection.observations import Observation, TickerEra
from delist_detection.review_triage import ReviewItem
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "form25_reach"
DATA = json.loads((FIX / "cases.json").read_text())
EDGAR = json.loads(gzip.decompress((FIX / "edgar.json.gz").read_bytes()))
MIDAS = json.loads((FIX / "midas.json").read_text())
HALTS = json.loads((FIX / "halts.json").read_text())
AS_OF = date.fromisoformat(DATA["as_of"])


class FixtureEdgar:
    """The cases' EDGAR answers as the fixture recorded them. A raw or a text the cache lacked reads as "" (as
    an unreadable filing); `raws_read` lists every Form 25 raw the finder asked for."""

    def __init__(self) -> None:
        self.raws_read: list[str] = []

    def company_tickers(self):
        return {}

    def submissions(self, cik, fresh_after=None):
        d = EDGAR["issuers"].get(str(int(cik)))
        return {} if d is None else {k: d[k] for k in ("name", "formerNames", "tickers", "exchanges", "sic")}

    def recent_filings(self, cik):
        return [EdgarSubmission(*f) for f in EDGAR["issuers"].get(str(int(cik)), {}).get("filings", [])]

    def fetch_filing_raw(self, cik, accession):
        self.raws_read.append(accession)
        return EDGAR["raws"].get(accession, "")

    def fetch_filing_text(self, cik, accession, primary_doc):
        return EDGAR["texts"].get(accession, "")

    def company_search_atom(self, name, form_type="25-NSE"):
        return []


class FixtureMidas(MidasClient):
    """MIDAS's per-quarter days with exchange volume, as the fixture recorded them for the case tickers; the
    real client's `last_trade_day` reads them (the coverage edge included)."""

    def __init__(self) -> None:
        self._summaries = {}
        self._warned_misses = set()

    def links(self):
        return {(int(q[:4]), int(q[-1])): q for q in MIDAS["quarters"]}

    def _summary(self, yq):
        return MIDAS["days"].get(f"{yq[0]}_q{yq[1]}", {})


class FixtureHalts(NasdaqHaltClient):
    """The Nasdaq code-D halts of the case tickers on the cached halt days; any other day has none."""

    def __init__(self) -> None:
        self.today = AS_OF

    def failed_days(self):
        return ()

    def halts_on(self, day):
        return [Halt(s, n, m, r, date.fromisoformat(hd), ht, date.fromisoformat(rd) if rd else None)
                for s, n, m, r, hd, ht, rd in HALTS.get(f"{day:%Y%m%d}", [])]


def _security(sec_id: str) -> Security:
    d = DATA["securities"][sec_id]
    eras = []
    for key, obs in d["eras"].items():
        ticker, _, rest = key.partition("@")
        seq = int(rest.split("#")[1]) if "#" in rest else 0
        observations = [Observation(t, a, n or None, c or None, int(p) if p else None) for t, a, n, c, p in obs]
        eras.append(TickerEra(ticker, observations[0].as_of, observations[-1].as_of, observations, seq=seq))
    eras.sort(key=lambda e: (e.first, e.seq))
    return Security(sec_id, d["issuer_cik"], d["share_class"], d["name"], d["security_type"], d["observed"],
                    d["figi_source"], kind=security_kind(d["security_type"], d["name"]), eras=eras,
                    line_tickers=frozenset(d["line_tickers"]))


@lru_cache(maxsize=1)
def world() -> tuple[dict[str, Security], dict[str, list[str]], FtdIndex]:
    """Every security of the fixture, its CUSIPs, and the fails rows as one index."""
    securities = {sid: _security(sid) for sid in DATA["securities"]}
    cusips = {sid: list(d["cusips"]) for sid, d in DATA["securities"].items()}
    with io.TextIOWrapper(gzip.open(FIX / "ftd_rows.csv.gz"), encoding="utf-8", newline="") as fh:
        rows = [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"], float(r["price"]) if r["price"] else None)
                for r in csv.DictReader(fh)]
    return securities, cusips, FtdIndex(rows)


def finder(edgar: FixtureEdgar | None = None) -> DelistingFinder:
    edgar = edgar or FixtureEdgar()
    classifier = DelistClassifier(edgar, TickerResolver(edgar), today=AS_OF)
    return DelistingFinder(edgar, classifier, midas=FixtureMidas(), halts=FixtureHalts())


def context(sec_id: str):
    """The case's `SecurityContext`, as stage 5 builds it (`pipeline._context_builder`)."""
    securities, cusips, ftd = world()
    sightings = {sid: ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    build = pipeline._context_builder(securities, sightings, pipeline._IssuerAnswers({}, {}, {}, set()), ftd, cusips)
    return build(securities[sec_id], DATA["securities"][sec_id]["listed"])


def find(sec_id: str, *, edgar: FixtureEdgar | None = None, **kw) -> tuple[list[Delisting], list[ReviewItem]]:
    """The finder's delistings and review items for the case."""
    return finder(edgar).find(context(sec_id, **kw))


def outcome(sec_id: str, **kw) -> tuple[list[tuple], list[str]]:
    """What the finder gives the case: each delisting as (delist_date, bucket, CRSP code, last trade day, whether
    its successor is the security itself, Form 25 accession, filer CIK), in order, and its review items' flags,
    sorted and once each."""
    found, review = find(sec_id, **kw)
    return ([(d.delist_date, d.record.bucket.value, d.record.crsp_code,
              d.last_trade.day.isoformat() if d.last_trade.day else "", d.record.successor_sec_id == sec_id,
              d.form25_sub.accession if d.form25_sub else "", d.cik) for d in found],
            sorted({r.flag for r in review}))
```

- [ ] **Step 4: Write the real-case test**

Create `tests/test_form25_reach_cases.py` (every outcome below is what the planning prototype gave on this
fixture; "after" is the outcome once every rule of 5b is built):

```python
"""Sub-plan 5b's real cases: what the finder gives each security of tests/fixtures/form25_reach/ (built once,
offline, from the local caches by scripts/build_form25_fixtures.py), through the run's own stage-5 code
(tests/form25_cases.py). A case the sub-plan moves (MOVES) keeps its outcome from before 5b until the task that
builds its rule adds the rule to RULES_DONE; a guard (STAY) keeps its outcome throughout. An outcome is the
finder's delistings, each (delist_date, bucket, CRSP code, last trade day, successor is the security itself, Form
25 accession, filer CIK), and the flags of its review items."""
from __future__ import annotations

import pytest

import delist_detection.delistings as delistings
from tests import form25_cases as fc

# The rules of sub-plan 5b built so far; each task adds its own (the cases it moves change then, and only then)
RULES_DONE: set[str] = set()

# sec_id -> (the rule that moves it, its outcome before 5b, its outcome after)
MOVES = {
    # ASNA 2020
    'BBG000BGZ9V9': ('1.03',
        ([('2020-08-21', 'exchange_transfer', 304, '2020-08-03', True, '0001354457-20-000408', 1498301)], ['ended_without_delisting']),
        ([('2020-08-21', 'liquidation', 470, '2020-08-03', False, '0001354457-20-000408', 1498301)], [])),
    # CNB 2009
    'BBG000BF2JS9': ('R6a',
        ([('2009-09-18', 'compliance_failure', 573, '2009-08-17', False, '0000876661-09-000352', 92339)], []),
        ([('2009-09-18', 'liquidation', 470, '2009-08-17', False, '0000876661-09-000352', 92339)], [])),
    # NTY 2010
    'BBG000BPTDN6': ('R6b',
        ([('2010-10-11', 'exchange_transfer', 304, '2010-09-30', False, '0000876661-10-000366', 70793)], []),
        ([('2010-10-11', 'merger', 231, '2010-09-30', False, '0000876661-10-000366', 70793)], [])),
    # TMA 2008 (R6a; it moves once C stops its OTC tail from continuing it)
    'BBG000BBG3P1': ('C',
        ([('2009-01-25', 'compliance_failure', 573, '2008-12-01', False, '0000876661-09-000070', 892535)], []),
        ([('2009-01-25', 'compliance_failure', 580, '2008-12-01', False, '0000876661-09-000070', 892535)], [])),
    # IMB 2008 (likewise)
    'BBG000BLY636': ('C',
        ([('2008-08-17', 'compliance_failure', 573, '2008-07-14', False, '0000876661-08-000315', 773468)], []),
        ([('2008-08-17', 'liquidation', 470, '2008-07-14', False, '0000876661-08-000315', 773468)], [])),
    # MNI 2020
    'BBG000BP62Y3': ('C',
        ([('2017-09-28', 'exchange_transfer', 304, '', True, '0001104659-17-057627', 1056087)], ['ended_without_delisting']),
        ([('2017-09-28', 'exchange_transfer', 304, '', True, '0001104659-17-057627', 1056087), ('2020-03-02', 'liquidation', 470, '2020-02-12', False, '0001143313-20-000012', 1056087)], [])),
    # RHD 2009 (the deficiency wording of Task 3 decides its code)
    'BBG000BRF6B5': ('C',
        ([('2009-05-29', 'liquidation', 470, '2009-06-08', False, '', 30419)], []),
        ([('2009-01-26', 'compliance_failure', 570, '2008-12-31', False, '0000876661-09-000078', 30419)], [])),
    # XMSR 2008
    'BBG000C070N2': ('C',
        ([('2008-08-08', 'exchange_transfer', 304, '2008-07-28', True, '0001354457-08-000198', 1091530), ('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 1091530)], []),
        ([('2008-08-08', 'merger', 231, '2008-07-28', False, '0001354457-08-000198', 1091530)], [])),
    # SOV 2009
    'BBG000JXRXK2': ('C',
        ([('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 811830)], []),
        ([('2009-02-12', 'merger', 231, '2009-01-29', False, '0000876661-09-000094', 811830)], [])),
    # IAR 2008
    'BBG000PSSG77': ('C',
        ([('2009-01-01', 'exchange_transfer', 304, '2008-11-19', True, '0000876661-08-000579', 1367396), ('2009-03-31', 'liquidation', 470, '2009-06-08', False, '', 1367396)], []),
        ([('2009-01-01', 'compliance_failure', 570, '2008-11-19', False, '0000876661-08-000579', 1367396)], [])),
    # LTRPA 2023
    'BBG005DKMJ67': ('C',
        ([('2023-11-30', 'exchange_transfer', 304, '2023-10-27', True, '0001354457-23-000874', 1606745), ('2025-04-29', 'merger', 231, '2025-04-30', False, '', 1606745)], []),
        ([('2023-11-30', 'compliance_failure', 570, '2023-10-27', False, '0001354457-23-000874', 1606745)], [])),
    # LKSD 2020
    'BBG009R0CVG1': ('C',
        ([('2020-01-24', 'exchange_transfer', 304, '2019-12-27', True, '0000876661-20-000026', 1669812), ('2020-04-13', 'liquidation', 470, '2020-04-09', False, '', 1669812)], []),
        ([('2020-01-24', 'compliance_failure', 570, '2019-12-27', False, '0000876661-20-000026', 1669812)], [])),
    # KHC 2026
    'BBG005CPNTQ2': ('R7',
        ([('2026-09-18', 'unknown', None, '', False, '0001637459-26-000062', 1637459)], []),
        ([('2026-09-18', 'exchange_transfer', 304, '', True, '0001637459-26-000062', 1637459)], [])),
    # TXU 2007
    'BBG000BVW841': ('E',
        ([('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 1023291)], []),
        ([('2007-11-02', 'merger', 231, '2007-10-10', False, '0000876661-07-000841', 1023291)], [])),
    # BMET 2007 (Task 5's notice reading decides its code)
    'CIK351346-COMMON': ('E',
        ([('2006-12-28', 'compliance_failure', 570, '', False, '0001104659-06-082100', 351346)], []),
        ([('2007-10-05', 'merger', 231, '', False, '0001354457-07-000287', 351346)], [])),
    # STN 2007
    'CIK898660-COMMON': ('E',
        ([('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 898660)], []),
        ([('2007-11-18', 'merger', 231, '2007-11-07', False, '0000876661-07-000873', 898660)], [])),
    # Liberty Series A 2011
    'CIK1355096-SERIES-A': ('R3',
        ([('2011-10-03', 'merger', 200, '', False, '0001354457-11-000196', 1355096)], []),
        ([], ['ended_without_delisting'])),
    # MWW 2016
    'BBG000DGZ1B6': ('L',
        ([('2008-11-20', 'exchange_transfer', 304, '', True, '0001362310-08-006919', 1020416), ('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 1020416)], []),
        ([('2008-11-20', 'exchange_transfer', 304, '', True, '0001362310-08-006919', 1020416), ('2016-11-11', 'merger', 231, '2016-10-31', False, '0000876661-16-001386', 1020416)], [])),
    # SPWRA 2011
    'CIK867773-COMMON': ('R2',
        ([], ['ended_without_delisting', 'form25_unmatched']),
        ([('2011-11-26', 'exchange_transfer', 304, '', False, '0001354457-11-000248', 867773)], [])),
    # SPB 2018
    'BBG000P4BQM9': ('R5',
        ([('2018-07-16', 'merger', 231, '2018-07-16', False, '', 109177)], []),
        ([('2018-07-26', 'merger', 200, '2018-07-13', False, '0000876661-18-000794', 1487730)], [])),
    # MTCH 2020
    'BBG00B6WH9G3': ('R5',
        ([], ['ended_without_delisting', 'form25_unmatched']),
        ([('2020-07-11', 'merger', 200, '2020-06-30', False, '0001354457-20-000292', 1575189)], ['form25_unmatched'])),
}

# the guards: securities whose outcome no rule of 5b changes
STAY = {
    'BBG000BC2C10': ([('2021-03-14', 'exchange_transfer', 304, '', False, '0001354457-21-000304', 6769)], []),   # APA
    'BBG000BFTJ91': ([('2015-12-21', 'exchange_transfer', 304, '2015-12-11', False, '0001354457-15-000245', 1166691)], []),   # CMCSK 2015
    'BBG000CNFQW6': ([], []),   # PRGO
    'BBG000CS7CB8': ([('2007-11-25', 'merger', 231, '2007-11-13', False, '0000876661-07-000879', 885708)], []),   # JNC 2007
    'BBG000D9DMK0': ([], ['ended_without_delisting', 'form25_unmatched']),   # LH
    'BBG000MJRJJ2': ([('2023-08-24', 'exchange_transfer', 304, '2023-08-11', False, '0000876661-23-000651', 1498828)], []),   # HHC 2023
    'BBG000VMWHH5': ([('2022-04-18', 'merger', 200, '2022-04-08', False, '0001354457-22-000231', 1437107)], ['form25_unmatched']),   # DISCK 2022
    'BBG001QD41M9': ([], ['ended_without_delisting', 'form25_unmatched']),   # APTV
    'BBG0038K9G41': ([('2018-03-19', 'merger', 200, '2018-03-09', False, '0001354457-18-000053', 1355096)], []),   # LVNTA 2018
    'BBG004P33PN3': ([('2026-05-11', 'unknown', None, '2026-04-30', False, '0000876661-26-000380', 1567683)], []),   # CWENA 2026
    'BBG00B4Z2YX0': ([], []),   # LAUR
    'BBG00GVR8YQ9': ([], ['ended_without_delisting', 'form25_unmatched']),   # LIN
    'CIK1469372-CLASS-A': ([('2015-08-03', 'exchange_transfer', 304, '', True, '0001193125-15-262759', 1469372), ('2015-10-02', 'exchange_transfer', 304, '2015-10-02', False, '', 1469372)], []),   # MSG 2015
    'CIK48898-CLASS-B': ([('2016-01-03', 'exchange_transfer', 304, '2015-12-23', False, '0000876661-15-000665', 48898)], ['form25_unmatched']),   # HUB-B 2015
    'CIK65873-COMMON': ([('2007-11-30', 'merger', 231, '2007-11-16', False, '0000876661-07-000891', 65873)], []),   # AT 2007
}


@pytest.mark.parametrize("sec_id", sorted(MOVES), ids=lambda s: fc.DATA["cases"][s]["note"].split(":")[0])
def test_a_case_moves_when_its_rule_is_built(sec_id):
    rule, before, after = MOVES[sec_id]
    assert fc.outcome(sec_id) == (after if rule in RULES_DONE else before)


@pytest.mark.parametrize("sec_id", sorted(STAY), ids=lambda s: fc.DATA["cases"][s]["note"].split(":")[0])
def test_a_guard_keeps_its_outcome(sec_id):
    assert fc.outcome(sec_id) == STAY[sec_id]


def test_every_case_of_the_fixture_is_a_move_or_a_guard():
    assert set(MOVES) | set(STAY) == set(fc.DATA["cases"]) and not set(MOVES) & set(STAY)


def test_a_security_listed_today_reads_no_form25_from_before_its_first_sighting():
    """LAUR: listed today, its observations from 2008 are of the old Laureate, and its one Form 25 (2007-08-17,
    not cached) lies before them: the finder never reads it (early reach needs `listed_today is False`)."""
    edgar = fc.FixtureEdgar()
    assert fc.find("BBG00B4Z2YX0", edgar=edgar) == ([], []) and edgar.raws_read == []


@pytest.mark.parametrize("sec_id,day", [("BBG00GVR8YQ9", "2023-03-12"), ("BBG001QD41M9", "2024-12-28"),
                                         ("BBG000D9DMK0", "2024-05-30")], ids=["LIN", "APTV", "LH"])
def test_the_sibling_slack_keeps_an_old_redomiciled_line_from_a_false_ending(sec_id, day, monkeypatch):
    """Must not change (binding, 2026-10-04): the old lines of Linde, Aptiv and Labcorp. The 30-day slack keeps the
    new line alive at its Form 25, so the filing stays ambiguous between the two lines and the old line takes no
    ending of its own; with a sibling alive only from its own first sighting, the old line would end there."""
    assert fc.outcome(sec_id)[0] == []
    monkeypatch.setattr(delistings, "SIBLING_ALIVE_BEFORE_DAYS", 0)
    assert [r[0] for r in fc.outcome(sec_id)[0]] == [day]
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_form25_reach_cases.py`
Expected: PASS (41 tests, about 2 seconds). A failing case means the fixture or the harness differs from the
planning build: compare the case's `fc.outcome(...)` with its table row, and report; never change a row to make it
pass.

Then the full suite: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: 2094 passed, 245 xfailed.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_form25_fixtures.py tests/form25_cases.py tests/test_form25_reach_cases.py tests/fixtures/form25_reach
git commit -m "Real-case fixtures for the Form 25 search, built offline from the caches, and their stage-5 replay (sub-plan 5b)"
```

---

### Task 2: Every Item 1.03 section, and a confirmed bankruptcy before a completed sale (5g sub-rule 2)

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/evidence.py`, `src/delist_detection/classifier.py`, `src/delist_detection/end_of_era.py`
- Test: `tests/test_evidence.py`, `tests/test_end_of_era.py`, `tests/test_classify_event.py`,
  `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: Task 1's `tests/form25_cases.py` (`fc.EDGAR["texts"]`).
- Produces: `evidence.item_sections(text, item, width=1500) -> list[str]` (`item_text` is its first);
  `classifier._confirms_bankruptcy` reads every section; `DelistClassifier._confirmed_bankruptcy(..., before=540,
  after=30)`; `DelistClassifier._bankruptcy_in_window(cik, filings, on, flags) -> str` ("8-K <date>" or "");
  `end_of_era.EraSignals.bankruptcy_filing: str = ""`; `end_of_era.signals(..., bankruptcy_filing="")`; the
  resolver branch `"bankruptcy"` (470, liquidation). Tasks 4 and 5 reuse this task's test helpers in
  tests/test_classify_event.py (`NASDAQ_REMOVAL`, `CHAPTER_11`, `EdgarSubmission`, `fc`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_evidence.py`:

```python


# --- sub-plan 5b: every Item section ---

from delist_detection.evidence import item_sections, item_text  # noqa: E402

# Ascena's 2020 bankruptcy 8-K, shortened: its first "Item 1.03" is a cross-reference long enough to read as the
# section; the item's own section, which reports the Chapter 11 cases, comes next.
CROSS_REFERENCED_103 = (
    "Item 1.01 Entry into a Material Definitive Agreement. The information set forth below in Item 1.03 in this "
    "Current Report on Form 8-K under the captions “Restructuring Support Agreement” and “Backstop Commitment "
    "Letter for the DIP Term Facility” is hereby incorporated by reference in this Item 1.01. Item 1.03 "
    "Bankruptcy or Receivership. Voluntary Petition for Reorganization On July 23, 2020, Ascena Retail Group, Inc. "
    "and certain of its subsidiaries commenced voluntary cases under chapter 11 of title 11 of the United States "
    "Code in the United States Bankruptcy Court for the Eastern District of Virginia. " + "x" * 300
    + " Item 2.04 Triggering Events.")


def test_item_sections_are_every_section_of_the_item_and_item_text_the_first():
    sections = item_sections(CROSS_REFERENCED_103, "1.03")
    assert len(sections) == 2
    assert sections[0].startswith("Item 1.03 in this Current Report") and "chapter 11" not in sections[0]
    assert sections[1].startswith("Item 1.03 Bankruptcy or Receivership") and "chapter 11" in sections[1]
    assert item_text(CROSS_REFERENCED_103, "1.03") == sections[0]


def test_a_short_filing_has_one_section_and_a_filing_without_the_item_none():
    assert item_sections("Item 1.03 Bankruptcy. Chapter 11.", "1.03") == ["Item 1.03 Bankruptcy. Chapter 11."]
    assert item_sections("Item 8.01 Other Events.", "1.03") == [] and item_text("Item 8.01", "1.03") == ""
```

Append to `tests/test_end_of_era.py`:

```python


# --- sub-plan 5b, 5g sub-rule 2: a confirmed bankruptcy before a completed sale ---

def test_a_confirmed_bankruptcy_before_the_completed_sale_is_a_bankruptcy():
    """A Chapter 11 asset sale is no merger: the 8-K item 1.03 the classifier confirmed (`bankruptcy_filing`) on
    or before the item 2.01 beats the completed-acquisition branch."""
    v = resolve(_s(item_filed={"1.03": "2020-09-10", "2.01": "2020-11-24"}, delist_filing="25-NSE 2020-08-11",
                   bankruptcy_filing="8-K 2020-09-10"), 470)
    assert (v.branch, v.crsp_code, v.bucket) == ("bankruptcy", 470, CrspBucket.LIQUIDATION)
    assert v.reason.startswith("Bankruptcy (8-K 2020-09-10, item 1.03) before the completed sale")
    assert RESOLVED_FROM_CONTINUED_FILINGS in v.reason


def test_a_bankruptcy_after_the_sale_or_unconfirmed_leaves_the_completed_merger():
    for bk in ("8-K 2020-12-01", ""):
        v = resolve(_s(item_filed={"1.03": "2020-12-01", "2.01": "2020-11-24"}, delist_filing="25-NSE 2020-08-11",
                       bankruptcy_filing=bk), 470)
        assert (v.branch, v.crsp_code, v.bucket) == ("completed_merger", 231, CrspBucket.MERGER)


def test_a_bankruptcy_and_a_sale_with_no_merger_filing_or_form25_keep_the_continued_filings_default():
    v = resolve(_s(item_filed={"1.03": "2020-09-10", "2.01": "2020-11-24"}, bankruptcy_filing="8-K 2020-09-10"), 470)
    assert v.branch == "continued_filings"


def test_a_change_in_control_still_comes_before_the_bankruptcy_branch():
    v = resolve(_s(item_filed={"1.03": "2020-09-10", "2.01": "2020-11-24", "5.01": "2020-11-24"},
                   bankruptcy_filing="8-K 2020-09-10"), 233)
    assert (v.branch, v.crsp_code) == ("change_in_control", 233)


def test_the_bankruptcy_filing_is_the_classifiers_answer_carried_on_the_signals():
    s = signals([_f("8-K", "2020-12-01", "1.03")], END, trading_after=False, bankruptcy_filing="8-K 2020-12-01")
    assert s.bankruptcy_filing == "8-K 2020-12-01" and s.item_filed == {"1.03": "2020-12-01"}
```

Append to `tests/test_classify_event.py`:

```python


# --- sub-plan 5b: the Item 1.03 sections, and 5g sub-rule 2 ---

from delist_detection.classifier import _confirms_bankruptcy  # noqa: E402
from delist_detection.edgar import EdgarSubmission  # noqa: E402
from tests import form25_cases as fc  # noqa: E402

NASDAQ_REMOVAL = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>The Nasdaq Stock Market LLC"
                  "</entityName></exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
                  "<ruleProvision>17 CFR 240.12d2-2(b)</ruleProvision></notificationOfRemoval>")
CHAPTER_11 = ("Item 1.03 Bankruptcy or Receivership. On the petition date the Company commenced voluntary cases "
              "under chapter 11 of title 11 of the United States Code. " + "x" * 300)


def test_ascenas_real_8k_with_a_cross_referenced_item_103_confirms_its_bankruptcy():
    """Ascena 2020 (CIK 1498301, 8-K 0001104659-20-085810): its first 'Item 1.03' is a cross-reference in Item
    1.01; the item's own section reports the Chapter 11 cases."""
    assert _confirms_bankruptcy(fc.EDGAR["texts"]["0001104659-20-085810"])


def _ascena_like(fake_edgar):
    """A Nasdaq removal (2020-08-11, last trade 2020-08-03) 11 days after a Chapter 11 8-K whose first 'Item
    1.03' is a cross-reference, an asset sale (item 2.01) in November, and a 10-Q filed in March."""
    fake_edgar.submissions_by_cik[30001] = [
        EdgarSubmission("bk1", "8-K", "2020-07-23", "2020-07-23", "1.01,1.03,2.04,7.01", "k.htm"),
        EdgarSubmission("f25", "25-NSE", "2020-08-11", "", "", "p.xml"),
        EdgarSubmission("sale", "8-K", "2020-11-24", "2020-11-23", "2.01,9.01", "s.htm"),
        EdgarSubmission("q", "10-Q", "2021-03-03", "2020-10-31", "", "q.htm")]
    fake_edgar.raws["f25"] = NASDAQ_REMOVAL
    fake_edgar.texts["bk1"] = (
        "Item 1.01 Entry into a Material Definitive Agreement. The information set forth below in Item 1.03 in this "
        "Current Report on Form 8-K under the captions Restructuring Support Agreement and Backstop Commitment "
        "Letter for the DIP Term Facility is hereby incorporated by reference in this Item 1.01. " + CHAPTER_11)
    return fake_edgar


def test_a_bankruptcy_whose_first_item_103_is_a_cross_reference_is_the_ending_not_the_asset_sale(fake_edgar):
    """Ascena 2020 (sub-plan 5b pulls in 5g sub-rule 2): the confirmed Chapter 11 8-K decides the Form 25's row,
    not the end-of-era resolver's completed sale."""
    edgar = _ascena_like(fake_edgar)
    sub = next(f for f in edgar.recent_filings(30001) if f.form == "25-NSE")
    rec = _clf(edgar).classify_event(ticker="ASNA", cik=30001, anchor_date="2020-08-03", form25=sub)
    assert (rec.crsp_code, rec.bucket) == (470, CrspBucket.LIQUIDATION)
    assert rec.reason == "Bankruptcy (8-K item 1.03 filed 2020-07-23)"


def test_a_bankruptcy_filed_within_the_resolvers_window_beats_the_completed_sale(fake_edgar):
    """5g sub-rule 2: the confirmed 1.03 8-K comes 53 days after the last trade (outside the bankruptcy branch's
    [-540, +30] days) and before the asset sale: the resolver's bankruptcy branch, not a merger."""
    fake_edgar.submissions_by_cik[30002] = [
        EdgarSubmission("f25", "25-NSE", "2020-01-10", "", "", "p.xml"),
        EdgarSubmission("bk2", "8-K", "2020-03-02", "2020-03-02", "1.03", "k.htm"),
        EdgarSubmission("sale2", "8-K", "2020-04-01", "2020-04-01", "2.01", "s.htm"),
        EdgarSubmission("q2", "10-Q", "2020-10-01", "2020-06-30", "", "q.htm")]
    fake_edgar.raws["f25"] = NASDAQ_REMOVAL
    fake_edgar.texts["bk2"] = CHAPTER_11
    sub = next(f for f in fake_edgar.recent_filings(30002) if f.form == "25-NSE")
    rec = _clf(fake_edgar).classify_event(ticker="SALE", cik=30002, anchor_date="2020-01-09", form25=sub)
    assert (rec.crsp_code, rec.bucket, rec.evidence["end_of_era"]) == (470, CrspBucket.LIQUIDATION, "bankruptcy")
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = set()` with
`RULES_DONE: set[str] = {"1.03"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_evidence.py tests/test_end_of_era.py tests/test_classify_event.py tests/test_form25_reach_cases.py`
Expected: FAIL (`cannot import name 'item_sections'`; `unexpected keyword argument 'bankruptcy_filing'`; the
Ascena cases give 231; the reach case ASNA).

- [ ] **Step 3: Every Item section**

In `src/delist_detection/evidence.py`, replace the whole `item_text` function with:

```python
def item_sections(text: str, item: str, width: int = 1500) -> list[str]:
    """Every `Item {item}` section of `text` (any case), in order.

    A section runs from a mention of the item to the next `Item N.NN` heading or
    `width` characters, whichever comes first. An 8-K's cover page indexes every
    item it carries, and the body cross-references items too, so a mention is
    often a one-line entry that says nothing: only sections of at least
    ITEM_MIN_SECTION characters count. If every one is shorter (a short filing
    with one heading), the first mention and `width` characters is the one
    section. A cross-reference long enough to count ("The information set forth
    below in Item 1.03 ... is incorporated by reference in this Item 1.01":
    Ascena 2020) can come before the item's own section, so a reader that looks
    for wording reads every section, not only the first.
    """
    text = text or ""
    matches = list(re.finditer(rf"item\s*{re.escape(item)}", text, re.I))
    if not matches:
        return []
    out = []
    for m in matches:
        end = min(len(text), m.start() + width)
        nxt = _ITEM_HEAD.search(text, m.end())
        if nxt and nxt.start() < end:
            end = nxt.start()
        if end - m.start() >= ITEM_MIN_SECTION:
            out.append(text[m.start():end])
    return out or [text[matches[0].start():matches[0].start() + width]]


def item_text(text: str, item: str, width: int = 1500) -> str:
    """The first `Item {item}` section of `text` (`item_sections`), else ""."""
    sections = item_sections(text, item, width)
    return sections[0] if sections else ""
```

- [ ] **Step 4: The classifier reads every Item 1.03 section, and finds the resolver's bankruptcy**

In `src/delist_detection/classifier.py`:

In the `from .evidence import (` block, replace `    item_text,` with:

```python
    item_sections,
    item_text,
```

Replace the whole `_confirms_bankruptcy` function with:

```python
def _confirms_bankruptcy(text: str) -> bool:
    """An Item 1.03 section of the filing reports a bankruptcy. Every section is
    read (`evidence.item_sections`): a cross-reference to Item 1.03 can come
    first (Ascena 2020). Wording elsewhere (credit-agreement boilerplate in a
    takeover 8-K) confirms nothing, and neither does the standard heading on its
    own."""
    return any(bool(_BANKRUPTCY_BODY.search(section)) or mentions_bankruptcy(_drop_heading(section))
               for section in item_sections(text, "1.03"))
```

Replace

```python
    def _confirmed_bankruptcy(self, cik, filings, on, flags, before: int = 540):
        """First 1.03 8-K in the window whose Item 1.03 section mentions a
        bankruptcy. An empty text (fetch miss) counts as confirmed, since the tag
        is SEC's own metadata, and adds the flag `bankruptcy_text_missing`."""
        for f in bankruptcy_8ks(filings, on, before=before):
```

with

```python
    def _confirmed_bankruptcy(self, cik, filings, on, flags, before: int = 540, after: int = 30):
        """First 1.03 8-K in [on - before, on + after] whose Item 1.03 section
        mentions a bankruptcy. An empty text (fetch miss) counts as confirmed,
        since the tag is SEC's own metadata, and adds the flag
        `bankruptcy_text_missing`."""
        for f in bankruptcy_8ks(filings, on, before=before, after=after):
```

Directly after the `_confirmed_bankruptcy` method (before `def _emerged_before_merger`), add:

```python
    def _bankruptcy_in_window(self, cik: int, filings: list[EdgarSubmission], on: date, flags: list[str]) -> str:
        """`"8-K <date>"` of the first 8-K in the end-of-era resolver's item window around `on` whose Item 1.03
        text confirms a bankruptcy (`_confirmed_bankruptcy`), else "" (5g sub-rule 2)."""
        bk = self._confirmed_bankruptcy(cik, filings, on, flags, before=end_of_era.ITEMS_BEFORE_DAYS,
                                        after=end_of_era.ITEMS_AFTER_DAYS)
        return f"8-K {bk.filing_date}" if bk is not None else ""

```

In `_classify_resolved`, replace

```python
            era = end_of_era.signals(filings, observed, trading_after=trading_after,
                                     deficiency_notice=self._deficiency_notice(resolution.cik, filings, observed))
```

with

```python
            era = end_of_era.signals(filings, observed, trading_after=trading_after,
                                     deficiency_notice=self._deficiency_notice(resolution.cik, filings, observed),
                                     bankruptcy_filing=self._bankruptcy_in_window(resolution.cik, filings, observed,
                                                                                  flags))
```

- [ ] **Step 5: The resolver's bankruptcy branch**

In `src/delist_detection/end_of_era.py`:

In the module docstring, replace

```
4. a completed acquisition (8-K item 2.01) with a merger filing or a Form 25: a merger;
```

with

```
4. a completed acquisition (8-K item 2.01) with a merger filing or a Form 25: a merger,
   unless a bankruptcy 8-K (item 1.03, its text confirmed by the classifier) came on
   or before it: a Chapter 11 asset sale is a liquidation (470; 5g sub-rule 2, built
   in sub-plan 5b);
```

In `EraSignals`, after the `deficiency_notice` field add:

```python
    bankruptcy_filing: str = ""       # "8-K <date>" of the first 8-K in the window whose item 1.03 text confirms
```

In `EraVerdict`, replace the comment `# trading, successor, change_in_control, completed_merger, delisting_notice,`
with `# trading, successor, change_in_control, bankruptcy, completed_merger, delisting_notice,`.

Replace the `signals` signature and docstring:

```python
def signals(filings: Iterable[EdgarSubmission], on: date, *, trading_after: bool,
            deficiency_notice: str = "") -> EraSignals:
    """The evidence around a security's end date `on`: the items of every 8-K (not
    an 8-K12B/8-K12G3) filed in [on − ITEMS_BEFORE_DAYS, on + ITEMS_AFTER_DAYS], the
    first successor registration and Form 25 in that window, and the latest merger
    filing in [on − MERGER_FILING_BEFORE_DAYS, on + MERGER_FILING_AFTER_DAYS]."""
```

with

```python
def signals(filings: Iterable[EdgarSubmission], on: date, *, trading_after: bool,
            deficiency_notice: str = "", bankruptcy_filing: str = "") -> EraSignals:
    """The evidence around a security's end date `on`: the items of every 8-K (not
    an 8-K12B/8-K12G3) filed in [on − ITEMS_BEFORE_DAYS, on + ITEMS_AFTER_DAYS], the
    first successor registration and Form 25 in that window, and the latest merger
    filing in [on − MERGER_FILING_BEFORE_DAYS, on + MERGER_FILING_AFTER_DAYS]. The
    classifier supplies the text checks: the deficiency notice, and the confirmed
    bankruptcy 8-K in the item window."""
```

and its last line `    return EraSignals(trading_after, item_filed, successor, merger, delist, deficiency_notice)` with
`    return EraSignals(trading_after, item_filed, successor, merger, delist, deficiency_notice, bankruptcy_filing)`.

In `resolve`, replace

```python
    if "2.01" in s.item_filed and (s.merger_filing or s.delist_filing):
        return EraVerdict("completed_merger", merger_code, CrspBucket.MERGER,
```

with

```python
    if "2.01" in s.item_filed and (s.merger_filing or s.delist_filing):
        if s.bankruptcy_filing and s.bankruptcy_filing[-10:] <= s.item_filed["2.01"]:
            return EraVerdict("bankruptcy", 470, CrspBucket.LIQUIDATION,
                              f"Bankruptcy ({s.bankruptcy_filing}, item 1.03) before the completed sale "
                              f"(8-K item 2.01 filed {s.item_filed['2.01']}){kept}")
        return EraVerdict("completed_merger", merger_code, CrspBucket.MERGER,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_evidence.py tests/test_end_of_era.py tests/test_classify_event.py tests/test_form25_reach_cases.py`
Expected: PASS. Then the full suite: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: 2104 passed, 245 xfailed (the golden replay included). Only ASNA moves among the reach cases; if another
case moves, stop and report it.

- [ ] **Step 7: Commit**

```bash
git add src/delist_detection/evidence.py src/delist_detection/classifier.py src/delist_detection/end_of_era.py tests/test_evidence.py tests/test_end_of_era.py tests/test_classify_event.py tests/test_form25_reach_cases.py
git commit -m "A bankruptcy 8-K whose first Item 1.03 is a cross-reference is confirmed; a confirmed bankruptcy before a completed sale is a liquidation (sub-plan 5b, 5g sub-rule 2: ASNA)"
```

---

### Task 3: NYSE's market-capitalization wording is a listing deficiency

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/evidence.py`
- Test: `tests/test_evidence.py`

**Interfaces:**
- Consumes: Task 2's `item_text` import at the end of tests/test_evidence.py; `tests/form25_cases.py`.
- Produces: `evidence._DEFICIENCY_TEXT` reads four more phrasings. No case of the fixture moves on its own (R.H.
  Donnelley's 570 needs Task 6 too).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_evidence.py`:

```python


# --- sub-plan 5b: NYSE's market-capitalization wording is a listing deficiency ---

import pytest  # noqa: E402

from delist_detection.evidence import cites_listing_deficiency  # noqa: E402
from tests import form25_cases as fc  # noqa: E402

# R.H. Donnelley's 8-K of 2009-01-02, Item 3.01: NYSE's market-capitalization standard (Rule 802.01B)
RHD_301 = ("Item 3.01. Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard; Transfer of "
           "Listing. (a) On December 31, 2008, R.H. Donnelley Corporation (the “Company”) was notified by the New "
           "York Stock Exchange (“NYSE”) that it no longer complies with NYSE continued listing requirements. "
           "Specifically, the Company no longer complies with Rule 802.01B, which requires that the Company's "
           "average market capitalization over a consecutive 30-day trading period not be less than $25 million.")


def test_nyses_market_capitalization_notice_cites_a_listing_deficiency():
    assert cites_listing_deficiency(RHD_301)
    assert cites_listing_deficiency(item_text(fc.EDGAR["texts"]["0001144204-08-071879"], "3.01"))


@pytest.mark.parametrize("text", [
    "the Company no longer complies with the NYSE's continued listing standards",
    "the Company had fallen below two of the NYSE’s continued listing standards",
    "its stockholders' equity was below the Exchange's continued listing standards",
    "requires that the Company’s average total market capitalization over 30 trading days exceed $75 million",
])
def test_each_new_wording_cites_a_listing_deficiency(text):
    assert cites_listing_deficiency(text)


@pytest.mark.parametrize("text", [
    "Following the merger, the common stock will no longer be listed on the New York Stock Exchange.",
    "The Company requested that the NYSE suspend trading before the open on the closing date.",
])
def test_a_merger_notice_cites_no_listing_deficiency(text):
    assert not cites_listing_deficiency(text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_evidence.py`
Expected: FAIL (the R.H. Donnelley notice and three of the four wordings read as no deficiency).

- [ ] **Step 3: Implement**

In `src/delist_detection/evidence.py`, replace

```python
    r"abnormally\s+low|average\s+global\s+market\s+capitali[sz]ation|"
    r"no\s+longer\s+suitable\s+for\s+(?:continued\s+)?listing|commence(?:d)?\s+proceedings\s+to\s+delist", re.I)
```

with

```python
    r"abnormally\s+low|average\s+global\s+market\s+capitali[sz]ation|"
    r"no\s+longer\s+suitable\s+for\s+(?:continued\s+)?listing|commence(?:d)?\s+proceedings\s+to\s+delist|"
    # sub-plan 5b: NYSE's market-capitalization removals (R.H. Donnelley 2008: "no longer complies with NYSE
    # continued listing requirements ... average market capitalization")
    r"no\s+longer\s+compl(?:ies|y)\s+with|below\s+(?:the\s+)?(?:NYSE|Exchange|Nasdaq)['’]?s?\s+continued\s+listing|"
    r"fallen\s+below\s+.{0,40}continued\s+listing|average\s+(?:total\s+)?market\s+capitali[sz]ation", re.I)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_evidence.py`
Expected: PASS. Then the full suite: 2111 passed, 245 xfailed (no reach case moves).

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/evidence.py tests/test_evidence.py
git commit -m "NYSE's market-capitalization wording cites a listing deficiency (sub-plan 5b: R.H. Donnelley)"
```

---

### Task 4: R6a, a revocation filed after a matched Form 25 does not decide it

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/classifier.py`
- Test: `tests/test_classify_event.py`, `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: Task 2's test helpers in tests/test_classify_event.py (`NASDAQ_REMOVAL`, `CHAPTER_11`,
  `EdgarSubmission`).
- Produces: a local `owned` in `_classify_resolved` (a matched Form 25, `delist_filing_override`, the security did
  not trade past: `not trading_after`), which Task 5 reuses.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_classify_event.py`:

```python


# --- sub-plan 5b, R6a: a revocation after a matched Form 25 does not decide it ---

def _revoked_case(fake_edgar, revoked_on):
    """Colonial BancGroup-like: the exchange removed the common (2009-09-08, last trade 2009-08-17) after a
    Chapter 11 8-K (2009-08-20); SEC revoked the registration on `revoked_on`."""
    fake_edgar.submissions_by_cik[30003] = [
        EdgarSubmission("cb25", "25-NSE", "2009-09-08", "", "", "p.xml"),
        EdgarSubmission("cbbk", "8-K", "2009-08-20", "2009-08-20", "1.03", "k.htm"),
        EdgarSubmission("cbrv", "REVOKED", revoked_on, "", "", "")]
    fake_edgar.raws["cb25"] = NASDAQ_REMOVAL
    fake_edgar.texts["cbbk"] = CHAPTER_11
    return next(f for f in fake_edgar.recent_filings(30003) if f.form == "25-NSE")


def test_a_revocation_filed_after_the_matched_form25_does_not_decide_its_row(fake_edgar):
    sub = _revoked_case(fake_edgar, "2010-06-01")
    rec = _clf(fake_edgar).classify_event(ticker="CNB", cik=30003, anchor_date="2009-08-17", form25=sub)
    assert (rec.crsp_code, rec.bucket) == (470, CrspBucket.LIQUIDATION)


def test_a_revocation_still_decides_when_it_came_first_or_no_form25_owns_the_row(fake_edgar):
    """A revocation before the Form 25, a row with no matched Form 25 (the fallback's), and a Form 25 the
    security traded past (`trading_after`) keep today's revocation branch (573)."""
    sub = _revoked_case(fake_edgar, "2009-09-01")
    clf = _clf(fake_edgar)
    assert clf.classify_event(ticker="CNB", cik=30003, anchor_date="2009-08-17", form25=sub).crsp_code == 573
    sub = _revoked_case(fake_edgar, "2010-06-01")
    assert clf.classify_event(ticker="CNB", cik=30003, anchor_date="2009-08-17").crsp_code == 573
    assert clf.classify_event(ticker="CNB", cik=30003, anchor_date="2009-08-17", form25=sub,
                              trading_after=True).crsp_code == 573
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = {"1.03"}` with
`RULES_DONE: set[str] = {"1.03", "R6a"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_classify_event.py tests/test_form25_reach_cases.py`
Expected: FAIL (573 for the late revocation; the reach case CNB).

- [ ] **Step 3: Implement**

In `src/delist_detection/classifier.py`, `_classify_resolved`, replace

```python
        # SEC-revoked: explicit Order of Suspension/Revocation by the SEC.
        # The submissions JSON marks these with form code 'REVOKED'.
        for f in filings:
            if f.form == "REVOKED":
```

with

```python
        # SEC-revoked: explicit Order of Suspension/Revocation by the SEC.
        # The submissions JSON marks these with form code 'REVOKED'. A matched
        # Form 25 the security did not trade past owns its row: a revocation filed
        # after it never decides it (sub-plan 5b, R6a: Colonial BancGroup, IndyMac
        # and Thornburg were removed from the exchange first).
        owned = delist_filing_override is not None and not trading_after
        for f in filings:
            if f.form == "REVOKED" and not (owned and f.filing_date > delist_filing_override.filing_date):
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_classify_event.py tests/test_form25_reach_cases.py`
Expected: PASS (CNB moves; IndyMac and Thornburg move with Task 6, once their OTC tails no longer count as trading
after). Then the full suite: 2113 passed, 245 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/classifier.py tests/test_classify_event.py tests/test_form25_reach_cases.py
git commit -m "A revocation filed after a matched Form 25 does not decide its row (sub-plan 5b, R6a: CNB)"
```

---

### Task 5: R6b, the matched Form 25's notice owns a continued-filings row

Tier: standard (a refactor of the classifier's tail).

**Files:**
- Modify: `src/delist_detection/form25.py`, `src/delist_detection/classifier.py`
- Test: `tests/test_form25.py`, `tests/test_classify_event.py`, `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: Task 4's `owned`; Task 2's test helpers in tests/test_classify_event.py.
- Produces: `form25.notice_says_acquired(f25: Form25) -> bool`; `DelistClassifier._notice_says_acquired(cik, sub)`;
  `DelistClassifier._classify_filings(ticker, resolution, observed_delist_date, observed, filings, delist_filing,
  dereg, evidence, flags) -> DelistRecord` (the Form 25 and 8-K branches, moved out of `_classify_resolved`);
  `evidence["end_of_era"] == "form25_notice"` on a row R6b decided.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_form25.py`:

```python


# --- sub-plan 5b, R6b: a notice that says the class was acquired ---

import pytest  # noqa: E402

from delist_detection.form25 import notice_says_acquired  # noqa: E402
from tests import form25_cases as fc  # noqa: E402


@pytest.mark.parametrize("accession,acquired", [
    ("0000876661-10-000366", True),    # NTY 2010: "converted into the right to receive $55.00 in cash"
    ("0001354457-07-000287", True),    # BMET 2007: "Acquired by LVB Acquisition Inc"
    ("0000876661-15-000665", False),   # HUB-B 2015: "the reclassification of ... dual-class common stock"
    ("0000876661-23-000651", False),   # HHC 2023: "the formation of a holding company ... one share"
    ("0001354457-21-000304", False),   # APA 2021: "APACHE CORPORATION REORGANIZED AS APA CORPORATION"
    ("0001354457-15-000245", False),   # CMCSK 2015: no notice text
], ids=["NTY", "BMET", "HUB-B", "HHC", "APA", "CMCSK"])
def test_a_real_notice_says_the_class_was_acquired_only_without_a_reorganization(accession, acquired):
    f = parse_form25(fc.EDGAR["raws"][accession], accession=accession, form="25-NSE", filing_date="2000-01-01")
    assert notice_says_acquired(f) is acquired
```

Append to `tests/test_classify_event.py`:

```python


# --- sub-plan 5b, R6b: the matched Form 25's notice owns a continued-filings row ---

def _notice_raw(text):
    return ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>New York Stock Exchange LLC</entityName>"
            "</exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
            "<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision></notificationOfRemoval>\n"
            f"<TYPE>EX-99.25\n<TEXT>\n{text}\n</TEXT>")


def _continued_filer(fake_edgar, notice):
    """NBTY-like: the 25-NSE of 2010-10-01 and a 10-Q seven months later (the issuer kept filing for its debt),
    no 8-K near it: the continued-filings rule's default branch (304) unless the notice decides."""
    fake_edgar.submissions_by_cik[30004] = [
        EdgarSubmission("nt25", "25-NSE", "2010-10-01", "", "", "p.xml"),
        EdgarSubmission("ntq", "10-Q", "2011-05-01", "2011-03-31", "", "q.htm")]
    fake_edgar.raws["nt25"] = _notice_raw(notice)
    return next(f for f in fake_edgar.recent_filings(30004) if f.form == "25-NSE")


CASH_NOTICE = ("Pursuant to the merger, which became effective before the open on October 1, 2010, each outstanding "
               "share of Common Stock was converted into the right to receive $55.00 in cash.")


def test_a_notice_that_says_cash_turns_the_continued_filings_default_into_a_merger(fake_edgar):
    sub = _continued_filer(fake_edgar, CASH_NOTICE)
    rec = _clf(fake_edgar).classify_event(ticker="NTY", cik=30004, anchor_date="2010-09-30", form25=sub)
    assert (rec.crsp_code, rec.bucket, rec.evidence["end_of_era"]) == (231, CrspBucket.MERGER, "form25_notice")
    assert rec.reason == "Form 25 2010-10-01 notice: the class was acquired"
    assert "no_evidence_default" not in rec.evidence["flags"]


def test_a_reorganization_a_security_trading_on_or_no_notice_keeps_the_continued_filings_transfer(fake_edgar):
    clf = _clf(fake_edgar)
    for notice in ("Pursuant to the reclassification of the dual-class common stock, each share of Class B was "
                   "converted into one (1) share of Common Stock.", ""):
        sub = _continued_filer(fake_edgar, notice)
        rec = clf.classify_event(ticker="NTY", cik=30004, anchor_date="2010-09-30", form25=sub)
        assert (rec.crsp_code, rec.evidence["end_of_era"]) == (304, "continued_filings")
    sub = _continued_filer(fake_edgar, CASH_NOTICE)
    rec = clf.classify_event(ticker="NTY", cik=30004, anchor_date="2010-09-30", form25=sub, trading_after=True)
    assert (rec.crsp_code, rec.evidence["end_of_era"]) == (304, "trading")
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = {"1.03", "R6a"}` with
`RULES_DONE: set[str] = {"1.03", "R6a", "R6b"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_form25.py tests/test_classify_event.py tests/test_form25_reach_cases.py`
Expected: FAIL (`cannot import name 'notice_says_acquired'`; 304 for the cash notice; the reach case NTY).

- [ ] **Step 3: Read the notice**

In `src/delist_detection/form25.py`, directly before `def effective_date(filing_date: str) -> str:` add:

```python
# R6b: the EX-99.25 notice says holders were paid ("acquired by", "converted into the right to receive $55.00 in
# cash"), and nothing of a reclassification, a holding company or a reorganization.
_ACQUIRED = re.compile(r"\bacquired\s+by\b|converted\s+into\s+(?:the\s+right\s+to\s+receive\s+)?(?:[^.]{0,120}?)"
                       r"(?:\$\s?[\d,.]+|\bcash\b)", re.I)
_REORGANIZED = re.compile(r"reclassif|formation\s+of\s+a\s+holding\s+company|holding\s+company\s+reorgani"
                          r"|reorganized\s+as|reorganization", re.I)


def notice_says_acquired(f25: Form25) -> bool:
    """Whether the exchange's EX-99.25 notice says the class was acquired or converted into cash (NTY 2010,
    "converted into the right to receive $55.00 in cash"; BMET 2007, "Acquired by LVB"), and nothing of a
    reclassification, a holding company's formation or a reorganization (HUB-B, HHC and APA 2021 stay
    continuations)."""
    t = re.sub(r"\s+", " ", f25.notice_text or "")
    return bool(_ACQUIRED.search(t)) and not _REORGANIZED.search(t)


```

- [ ] **Step 4: The notice owns a continued-filings row**

In `src/delist_detection/classifier.py`:

Directly before `from .ticker_resolver import TickerResolution, TickerResolver` add
`from .form25 import notice_says_acquired, parse_form25`.

In `_classify_resolved`, replace

```python
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

        if delist_filing is None:
            # No Form 25 found. Use 8-K-only logic centered on observed date.
```

with

```python
            items_code, _ = self._classify_items(set(era.item_filed))
            verdict = end_of_era.resolve(era, items_code)
            evidence["end_of_era"] = verdict.branch
            if (owned and verdict.branch == "continued_filings"
                    and self._notice_says_acquired(resolution.cik, delist_filing_override)):
                # Sub-plan 5b, R6b: the matched Form 25's own notice says the class was acquired or paid in cash
                # (NBTY 2010, Biomet 2007): its path decides, and any answer but a merger is 231.
                evidence["end_of_era"] = "form25_notice"
                rec = self._classify_filings(ticker, resolution, observed_delist_date, observed, filings,
                                             delist_filing, dereg, evidence, flags)
                if rec.bucket is CrspBucket.MERGER:
                    return rec
                return DelistRecord(ticker=ticker.upper(), cik=resolution.cik,
                                    observed_delist_date=observed_delist_date, crsp_code=231,
                                    bucket=CrspBucket.MERGER, confidence="medium",
                                    reason=f"Form 25 {delist_filing.filing_date} notice: the class was acquired",
                                    evidence={**rec.evidence, "flags": [f for f in flags
                                                                         if f != "no_evidence_default"]})
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
        return self._classify_filings(ticker, resolution, observed_delist_date, observed, filings, delist_filing,
                                      dereg, evidence, flags)

    def _notice_says_acquired(self, cik: int, sub: EdgarSubmission) -> bool:
        """Whether the matched Form 25's EX-99.25 notice says its class was acquired or converted into cash
        (`form25.notice_says_acquired`); False when its text cannot be read."""
        raw = self.edgar.fetch_filing_raw(cik, sub.accession)
        if not raw:
            return False
        return notice_says_acquired(parse_form25(raw, accession=sub.accession, form=sub.form,
                                                 filing_date=sub.filing_date))

    def _classify_filings(self, ticker: str, resolution: TickerResolution, observed_delist_date: str | None,
                          observed: date | None, filings: list[EdgarSubmission],
                          delist_filing: EdgarSubmission | None, dereg: EdgarSubmission | None, evidence: dict,
                          flags: list[str]) -> DelistRecord:
        """The Form 25 and 8-K branches of `_classify_resolved`: no Form 25, an 8-K near the observed date; else
        the 8-K near the Form 25 (or the backscan's), its items' code, the default without a fingerprint."""
        if delist_filing is None:
            # No Form 25 found. Use 8-K-only logic centered on observed date.
```

Everything from that `if delist_filing is None:` to the end of the old `_classify_resolved` now is the body of
`_classify_filings`: its indentation is already right and it reads only the method's parameters. Check that
`classify_event` (which follows) still calls `self._classify_resolved(...)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_form25.py tests/test_classify_event.py tests/test_classifier.py tests/test_golden_events.py tests/test_form25_reach_cases.py`
Expected: PASS (NTY moves; HUB-B, CMCSK, HHC and APA stay). Then the full suite: 2121 passed, 245 xfailed.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/form25.py src/delist_detection/classifier.py tests/test_form25.py tests/test_classify_event.py tests/test_form25_reach_cases.py
git commit -m "A matched Form 25 whose notice says the class was acquired owns its continued-filings row (sub-plan 5b, R6b: NTY)"
```

---

### Task 6: C, a security's own CUSIPs decide whether it went on after a Form 25

Tier: standard (the finder's scan is restructured).

**Files:**
- Modify: `src/delist_detection/ftd.py`, `src/delist_detection/form25.py`, `src/delist_detection/delistings.py`,
  `src/delist_detection/pipeline.py`
- Test: `tests/test_ftd.py`, `tests/test_delistings.py`, `tests/test_pipeline.py`, `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `ftd.TRADING_MIN_ROWS = 20`, `TRADING_MIN_DAYS = 20`, `TRADING_MIN_PRICES = 2`;
    `ftd.is_trading_symbol(symbol) -> bool`; `ftd.trades_after(rows, after: str) -> bool`.
  - `form25.is_involuntary(f25) -> bool` (rule 12d2-2(b)); `notice_last_trade` reads it.
  - `SecurityContext.trades_after: Callable[[str], bool]` (default: never).
  - `delistings._Scan` (`ticker`, `review`, `seen`, `had_unmatched`, `older`); `DelistingFinder._continued(ctx, sub,
    f25) -> bool`, `_not_this_removal(ctx, filer, filings, sub, f25) -> bool`, `_judge(ctx, scan, filer, sub, refs) ->
    Form25 | None`. Later tasks extend each: Task 7 gives `_continued` a `filings` parameter, Task 8 `_judge` a
    `quiet` keyword and `_Scan` an `unreadable` list, Task 9 `_judge` an `issuer_names` parameter.
  - `pipeline._context_builder` fills `trades_after` from `ftd.trading_rows` of the security's own CUSIPs.
- Behaviour: `continued` is listed today, or, for a Form 25 not under (b), the security's own CUSIPs trading on
  after its effective date plus 5 days. `seen_after` stays, only for the gate after a definitive delisting
  (`IGNORE_AFTER_DEFINITIVE_DAYS`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ftd.py`:

```python
# --- sub-plan 5b, C: whether a security's own CUSIPs trade on after a day ---

from delist_detection.ftd import is_trading_symbol, trades_after  # noqa: E402


def _tail_rows(symbol, days, prices=(10.0, 10.5)):
    return [FtdRow(d, "74955W307", symbol, "R H DONNELLEY CORP", prices[i % len(prices)]) for i, d in enumerate(days)]


JANUARY = [f"2020-01-{d:02d}" for d in range(2, 23)]       # 21 rows, 2020-01-02 .. 2020-01-22: 20 days apart


def test_twenty_rows_over_twenty_days_at_two_prices_show_trading_after_the_day():
    assert trades_after(_tail_rows("RHDC", JANUARY), "2020-01-01")
    assert not trades_after(_tail_rows("RHDC", JANUARY[:-1]), "2020-01-01")     # 19 days apart
    assert not trades_after(_tail_rows("RHDC", JANUARY), "2020-01-02")          # 20 rows after the day, 19 days apart


def test_fails_settling_at_one_price_are_no_trading():
    assert not trades_after(_tail_rows("RHDC", JANUARY, prices=(1.28,)), "2020-01-01")


def test_an_otc_symbol_counts_and_a_deleted_unassigned_or_pair_off_symbol_does_not():
    for symbol in ("RHDC", "RHDCQ", "**********"):
        assert is_trading_symbol(symbol) and trades_after(_tail_rows(symbol, JANUARY), "2020-01-01")
    for symbol in ("RHDXXXX", "RHDZZZZ", "F104PAIROFF", ""):
        assert not is_trading_symbol(symbol) and not trades_after(_tail_rows(symbol, JANUARY), "2020-01-01")
```

Append to `tests/test_delistings.py`:

```python
# --- sub-plan 5b, C: what continues a security after a Form 25 ---

def _stale_merger(fake_edgar, rule="17 CFR 240.12d2-2(a)(3)"):
    """XM Satellite-like: Nasdaq removed the class A (25-NSE 2008-07-29) at the merger (8-K item 5.01 the next
    day); the issuer kept filing for its debt; a stale snapshot lists the security until 2009-06-08."""
    fake_edgar.submissions_by_cik[30101] = [
        EdgarSubmission("x25", "25-NSE", "2008-07-29", "", "", "p.xml"),
        EdgarSubmission("x8k", "8-K", "2008-07-30", "2008-07-30", "2.01,5.01", "k.htm"),
        EdgarSubmission("xq", "10-Q", "2009-05-01", "2009-03-31", "", "q.htm")]
    fake_edgar.raws["x25"] = _f25_raw("The Nasdaq Stock Market LLC", rule=rule)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_XMSR", 30101, "XMSR", "2008-01-16", "2009-06-08", "XM SATELLITE RADIO HLDGS")
    return DelistingFinder(fake_edgar, clf), sec


def test_a_stale_observation_after_the_form25_no_longer_continues_the_security(fake_edgar):
    finder, sec = _stale_merger(fake_edgar)
    events, _ = finder.find(_ctx(sec, listed=False, seen_after=True, last_seen="2009-06-08"))
    assert [(e.delist_date, e.record.bucket, e.record.successor_sec_id) for e in events] == [
        ("2008-08-08", CrspBucket.MERGER, None)]


def test_the_securitys_own_cusip_trading_on_after_the_form25_continues_it(fake_edgar):
    finder, sec = _stale_merger(fake_edgar)
    events, _ = finder.find(_ctx(sec, listed=False, trades_after=True, last_seen="2009-06-08"))
    assert (events[0].record.bucket, events[0].record.successor_sec_id) == (CrspBucket.EXCHANGE_TRANSFER, "BBG_XMSR")


def test_trading_on_after_a_removal_under_rule_b_is_the_otc_tail_not_the_listing(fake_edgar):
    """R.H. Donnelley, Idearc, LSC Communications: an exchange's removal under 12d2-2(b), then OTC trading under
    the same CUSIP; only a listing today continues such a security."""
    finder, sec = _stale_merger(fake_edgar, rule="17 CFR 240.12d2-2(b)")
    events, _ = finder.find(_ctx(sec, listed=False, trades_after=True, last_seen="2009-06-08"))
    assert [(e.record.bucket, e.record.successor_sec_id) for e in events] == [(CrspBucket.MERGER, None)]
    events, _ = finder.find(_ctx(sec, listed=True, trades_after=False, last_seen="2009-06-08"))
    assert [(e.record.bucket, e.record.successor_sec_id) for e in events] == [
        (CrspBucket.EXCHANGE_TRANSFER, "BBG_XMSR")]
```

Append to `tests/test_pipeline.py`:

```python
# --- sub-plan 5b, C: the finder's context reads trading from the security's own CUSIPs ---

def _one_security_context(rows, cusip="74955W307"):
    from delist_detection.ftd import FtdIndex
    from delist_detection.history import ticker_sightings
    from delist_detection.observations import TickerEra
    s = Security("BBG_RHD", 30419, "COMMON", "R H DONNELLEY CORP", "Common Stock", True, "cusip",
                 eras=[TickerEra("RHD", "2008-01-16", "2008-12-31", [Observation("RHD", "2008-01-16", "R H DONNELLEY"),
                                                                    Observation("RHD", "2008-12-31", "R H DONNELLEY")])])
    ftd = FtdIndex(rows)
    cusips = {s.sec_id: [cusip]}
    build = pipeline._context_builder({s.sec_id: s}, {s.sec_id: ticker_sightings(s, ftd, cusips[s.sec_id])},
                                      pipeline._IssuerAnswers({}, {}, {}, set()), ftd, cusips)
    return build(s, False)


def test_the_finders_context_reads_trading_from_the_securitys_own_cusip_under_any_symbol():
    days = [f"2009-02-{d:02d}" for d in range(2, 28)]
    rows = [FtdRow(d, "74955W307", "RHDC", "R H DONNELLEY CORP", 1.0 + (i % 2) / 10) for i, d in enumerate(days)]
    ctx = _one_security_context(rows)
    assert ctx.trades_after("2009-01-31") and not ctx.trades_after("2009-02-10")
```

Append to `tests/test_delistings.py`:

```python
def test_a_form25_at_the_own_cusip_switch_of_a_security_not_listed_today_still_removed_the_old_cusip(fake_edgar):
    """Review Focus (C with U6): Acxiom/LiveRamp 2018-like, not listed today: the new CUSIP's fails rows continue
    the security (`trades_after`), so the Form 25 at its own CUSIP switch is no delisting."""
    finder, sec = _switch_case(fake_edgar)
    ctx = replace(_ctx(sec, listed=False, trades_after=True), cusip_switches=("2026-01-07",))
    events, review = finder.find(ctx)
    assert all(e.form25_sub is None for e in events)
```

Change the existing tests the rule changes:

In `tests/test_delistings.py`, replace

```python
def _ctx(sec, *, listed=False, seen_after=False, last_seen="2018-11-28"):
    return SecurityContext(security=sec, siblings=[SecurityRef(sec.sec_id, sec.share_class, sec.kind)],
                           ticker_on=lambda d: sec.eras[-1].ticker, last_seen=last_seen,
                           seen_after=lambda d: seen_after, listed_today=listed, expected_name=sec.name)
```

with

```python
def _ctx(sec, *, listed=False, seen_after=False, last_seen="2018-11-28", trades_after=False):
    return SecurityContext(security=sec, siblings=[SecurityRef(sec.sec_id, sec.share_class, sec.kind)],
                           ticker_on=lambda d: sec.eras[-1].ticker, last_seen=last_seen,
                           seen_after=lambda d: seen_after, listed_today=listed, expected_name=sec.name,
                           trades_after=lambda d: trades_after)
```

In `tests/test_delistings.py`, replace

```python
    ctx = _ctx(sec, listed=False, seen_after=True, last_seen="2015-06-01")
```

with

```python
    ctx = _ctx(sec, listed=False, seen_after=True, trades_after=True, last_seen="2015-06-01")
```

In `tests/test_delistings.py`, replace

```python
    ctx = _ctx(sec, listed=False, seen_after=True, last_seen="2018-03-15")
```

with

```python
    ctx = _ctx(sec, listed=False, seen_after=True, trades_after=True, last_seen="2018-03-15")
```

In `tests/test_pipeline.py`, replace

```python
def _retired_cusip_run(fake_edgar, tmp_path, tail_symbol):
    """Liberty Live's 2025 split-off as the fails files show it: the old line's
    CUSIP keeps failing after its Form 25 (2025-12-15, effective 12-25) under
    the deleted symbol LLYKXXXX, while the new line trades LLYK under a new
    CUSIP from 2025-12-17. The old issuer keeps filing 10-Qs, so the
    classifier reads an exchange transfer."""
```

with

```python
def _retired_cusip_run(fake_edgar, tmp_path, tail_symbol, tail_dates=("2025-12-31", "2026-01-15", "2026-02-02"),
                       tail_prices=(10.0,)):
    """Liberty Live's 2025 split-off as the fails files show it: the old line's
    CUSIP keeps failing after its Form 25 (2025-12-15, effective 12-25) under
    the deleted symbol LLYKXXXX, while the new line trades LLYK under a new
    CUSIP from 2025-12-17. The old issuer keeps filing 10-Qs, so the
    classifier reads an exchange transfer. The old CUSIP's rows after the Form
    25 are dated `tail_dates`, priced in turn from `tail_prices`."""
```

In `tests/test_pipeline.py`, replace

```python
            + _ftd(tail_symbol, "53229D101", "LIBERTY LIVE CORP", ["2025-12-31", "2026-01-15", "2026-02-02"])
```

with

```python
            + [FtdRow(d, "53229D101", tail_symbol, "LIBERTY LIVE CORP", tail_prices[i % len(tail_prices)])
               for i, d in enumerate(tail_dates)]
```

In `tests/test_pipeline.py`, replace

```python
def test_live_symbol_fails_after_the_delisting_still_read_as_continued(fake_edgar, tmp_path):
    d, _ = _retired_cusip_run(fake_edgar, tmp_path, "LLYK")
    assert d["BBGLLYKOLD1"]["successor_sec_id"] == "BBGLLYKOLD1"
```

with

```python
def test_live_symbol_trading_after_the_delisting_still_reads_as_continued(fake_edgar, tmp_path):
    """Sub-plan 5b (C): the old CUSIP trading on under a live symbol (LLYKV), 22 rows over 31 days at two prices,
    is the security going on after its Form 25 (`ftd.trades_after`)."""
    days = [f"2026-01-{d:02d}" for d in (2, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 20, 21, 22, 23, 26, 27, 28, 29, 30)] \
        + ["2026-02-02", "2026-02-03"]
    d, _ = _retired_cusip_run(fake_edgar, tmp_path, "LLYKV", tail_dates=days, tail_prices=(10.0, 10.5))
    assert d["BBGLLYKOLD1"]["successor_sec_id"] == "BBGLLYKOLD1"


def test_a_few_live_symbol_fails_after_the_delisting_are_no_continued_trading(fake_edgar, tmp_path):
    """Sub-plan 5b (C): three fails rows under the live symbol after the Form 25 are fails still settling, not the
    security trading on: the new line is its successor, as with the deleted symbol."""
    d, _ = _retired_cusip_run(fake_edgar, tmp_path, "LLYK")
    assert d["BBGLLYKOLD1"]["successor_sec_id"] == "BBGLLYKNEW1"
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = {"1.03", "R6a", "R6b"}` with `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_ftd.py tests/test_delistings.py tests/test_pipeline.py tests/test_form25_reach_cases.py`
Expected: FAIL (`cannot import name 'is_trading_symbol'`; `unexpected keyword argument 'trades_after'`; the
reach cases TMA, IMB, MNI, RHD, XMSR, SOV, IAR, LTRPA, LKSD).

- [ ] **Step 3: Whether a security's CUSIPs trade on, and a removal under (b)**

In `src/delist_detection/ftd.py`, directly before `def settled_last(rows: Sequence[FtdRow]) -> FtdRow:` add (this
block ends with that line, unchanged):

```python
TRADING_MIN_ROWS = 20     # fails rows after a day that show a security still trading: at least this many...
TRADING_MIN_DAYS = 20     # ...spanning at least this many days...
TRADING_MIN_PRICES = 2    # ...at two or more prices (fails still settling at the last close repeat one price)


def is_trading_symbol(symbol: str) -> bool:
    """Whether a fails row's symbol is one a security trades under: not a deleted "…XXXX" or unassigned "…ZZZZ"
    symbol, and no digit (SEC's pair-off placeholders such as "F104PAIROFF" carry part of the CUSIP)."""
    return bool(symbol) and not is_deleted_symbol(symbol) and not is_unassigned_symbol(symbol) \
        and not any(ch.isdigit() for ch in symbol)


def trades_after(rows: Iterable[FtdRow], after: str) -> bool:
    """Whether the fails rows of a security's own CUSIPs (`rows`) show it still trading after the ISO day `after`,
    under any symbol it trades under (`is_trading_symbol`; an OTC symbol counts): at least TRADING_MIN_ROWS rows
    over at least TRADING_MIN_DAYS days, at TRADING_MIN_PRICES or more prices."""
    later = [r for r in rows if r.date > after and is_trading_symbol(r.symbol)]
    if len(later) < TRADING_MIN_ROWS:
        return False
    days = sorted(r.date for r in later)
    if (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days < TRADING_MIN_DAYS:
        return False
    return len({r.price for r in later if r.price is not None}) >= TRADING_MIN_PRICES


def settled_last(rows: Sequence[FtdRow]) -> FtdRow:
```

In `src/delist_detection/form25.py`, replace

```python
    rule: str
    notice_text: str


def _tag(
```

with

```python
    rule: str
    notice_text: str


def is_involuntary(f25: Form25) -> bool:
    """An exchange's removal under rule 12d2-2(b) (a listing deficiency, a price, a market value), not a
    voluntary withdrawal or a merger's (a) filing: the class went to no other exchange."""
    return "(b)" in (f25.rule or "")


def _tag(
```

In `src/delist_detection/form25.py`, replace

```python
    involuntary = "(b)" in (f25.rule or "")
```

with

```python
    involuntary = is_involuntary(f25)
```

- [ ] **Step 4: The finder's continued test, scan and judgement**

In `src/delist_detection/delistings.py`, replace

```python
    REGIONAL_EXCHANGES, Form25, SecurityRef, class_kind, class_letters, effective_date, list_form25,
    match_securities, notice_last_trade, parse_form25, tied_securities,
```

with

```python
    REGIONAL_EXCHANGES, Form25, SecurityRef, class_kind, class_letters, effective_date, is_involuntary,
    list_form25, match_securities, notice_last_trade, parse_form25, tied_securities,
```

In `src/delist_detection/delistings.py`, replace

```python
    # The first fails row of each of the security's own CUSIPs after its first, ISO: a CUSIP switch on its own
    # line (a reverse split, a redomicile that kept the composite). A Form 25 filed at one while the security
    # trades on removed the old CUSIP, not the security (QGEN 2026, Acxiom/LiveRamp 2018).
    cusip_switches: tuple[str, ...] = ()
```

with

```python
    # The first fails row of each of the security's own CUSIPs after its first, ISO: a CUSIP switch on its own
    # line (a reverse split, a redomicile that kept the composite). A Form 25 filed at one while the security
    # trades on removed the old CUSIP, not the security (QGEN 2026, Acxiom/LiveRamp 2018).
    cusip_switches: tuple[str, ...] = ()
    # True when the fails rows of the security's own CUSIPs, under any symbol it trades under, show it still
    # trading after the given ISO day (`ftd.trades_after`). With `listed_today`, the one sign that a security went
    # on after a Form 25 (`DelistingFinder._continued`): an observation can be a stale snapshot (XMSR 2008, SOV
    # 2009). Unknown (the default) counts as no.
    trades_after: Callable[[str], bool] = lambda day: False
```

In `src/delist_detection/delistings.py`, replace

```python
class DelistingFinder:
```

with

```python
@dataclass
class _Scan:
    """The finder's working state for one security: the ticker its review rows carry, the review items and the
    keys already raised, whether some Form 25 could not be placed, and the Form 25s from before the floor (the
    fallback's to judge)."""
    ticker: str
    review: list[ReviewItem] = field(default_factory=list)
    seen: set[tuple[str, str]] = field(default_factory=set)
    had_unmatched: bool = False
    older: list[EdgarSubmission] = field(default_factory=list)


class DelistingFinder:
```

In `src/delist_detection/delistings.py`, replace everything from the line `    # -- main ---...` (just after
`_review`) up to, not including, `    def _build_delisting(` with:

```python
    # -- whether the security went on after a Form 25 ------------------------
    def _continued(self, ctx: SecurityContext, sub: EdgarSubmission, f25: Form25) -> bool:
        """Whether the security went on trading after this Form 25: it is listed today; or the Form 25 is not an
        exchange's removal under rule 12d2-2(b) (`form25.is_involuntary`) and the security's own CUSIPs trade on
        after its effective date plus SEEN_AFTER_DAYS (`SecurityContext.trades_after`). An observation alone never
        continues a security: a stale snapshot lists one long after it was acquired (XMSR 2008, SOV 2009), and the
        OTC tail after a removal under (b) is not the listing going on (R.H. Donnelley, Idearc, LSC
        Communications)."""
        if ctx.listed_today:
            return True
        if is_involuntary(f25):
            return False
        after = date.fromisoformat(effective_date(sub.filing_date)) + timedelta(days=SEEN_AFTER_DAYS)
        return ctx.trades_after(after.isoformat())

    def _not_this_removal(self, ctx: SecurityContext, filer: int, filings: list[EdgarSubmission],
                          sub: EdgarSubmission, f25: Form25) -> bool:
        """A Form 25 the security traded through that removed something else: the old CUSIP at the security's own
        CUSIP switch (U6), a secondary listing while the main one went on (Apache/Chicago 2020), or another class
        when the next 10-K cover still names the exchange."""
        if self._at_own_switch(ctx, sub.filing_date):
            return True             # the old CUSIP left the exchange as the security went on under its new one
        before, after = exchanges_around(self.edgar, filer, filings, date.fromisoformat(sub.filing_date))
        if withdrawal_kind(f25.exchange, before, after) == "secondary":
            return True
        return after is not None and f25.exchange in after   # another class left, not this one

    # -- one Form 25 against the security --------------------------------------
    def _judge(self, ctx: SecurityContext, scan: _Scan, filer: int, sub: EdgarSubmission,
               refs: list[SecurityRef]) -> Form25 | None:
        """The Form 25 `sub` of CIK `filer`, parsed, when it removed this security: readable, not a regional
        exchange's, of a recognized class, matched to this security among `refs` (`match_securities`) with no
        class-letter conflict. Else None, and a filing that could not be placed gets its review row."""
        sec, ticker = ctx.security, scan.ticker
        raw = self.edgar.fetch_filing_raw(filer, sub.accession)
        if not raw:
            scan.had_unmatched = True
            self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unreadable",
                         f"no filing text for {sub.form} {sub.accession}", sub)
            return None
        f25 = parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date)
        if f25.exchange in REGIONAL_EXCHANGES:
            return None
        if class_kind(f25.class_text) == "other":
            scan.had_unmatched = True
            self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unclassified",
                         f"{sub.form} {sub.accession} ({f25.class_text!r}) has no recognized class", sub)
            return None
        matched, why = match_securities(f25, refs)
        if not matched:
            if why == "ambiguous class":
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unmatched",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}): {why}", sub)
            return None
        if sec.sec_id not in matched:
            if sec.sec_id in tied_securities(f25, refs):
                # another class of this Form 25 matched; this one shares its
                # letter with a sibling no name word tells apart, or has none
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unmatched",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}): ambiguous class", sub)
            return None
        ref = next((r for r in refs if r.sec_id == sec.sec_id), None)
        if ref is not None and self._class_conflict(f25, ref):
            return None
        return f25

    # -- main ------------------------------------------------------------
    def find(self, ctx: SecurityContext) -> tuple[list[Delisting], list[ReviewItem]]:
        sec = ctx.security
        if not sec.eras:
            return [], []
        cik = sec.issuer_cik
        ticker_last = sec.eras[-1].ticker
        if sec.line_tickers:            # the line went on under a ticker the line follow found: its latest one
            latest = ctx.ticker_on(ctx.last_seen)
            ticker_last = latest if latest in sec.own_tickers() else ticker_last
        if cik is None:
            if ctx.listed_today is False:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "ended_without_delisting",
                                       "no issuer CIK to search for a Form 25", last_seen=ctx.last_seen)]
            if ctx.listed_today is None:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "listing_status_unknown",
                                       "no issuer CIK and listing status unknown", last_seen=ctx.last_seen)]
            return [], []

        filings = self.edgar.recent_filings(cik)
        first_seen = min(e.first for e in sec.eras)
        floor = (date.fromisoformat(first_seen) - timedelta(days=FORM25_LOOKBACK_DAYS)).isoformat()
        scan = _Scan(ticker_last)
        candidates: list[tuple[EdgarSubmission, Form25]] = []
        for sub in list_form25(filings):
            if sub.filing_date < floor:
                scan.older.append(sub)          # before the floor: only the fallback may take one
                continue
            # Filings that plainly aren't about any security of this issuer
            # (none of the observed securities were even alive on this date)
            # get no review item at all, so these checks come before the
            # readability/classification ones below.
            alive = [r for r in ctx.siblings if self._alive_at(ctx, r.sec_id, sub.filing_date)]
            if not alive:
                continue
            f25 = self._judge(ctx, scan, cik, sub, alive)
            if f25 is None:
                continue
            if self._continued(ctx, sub, f25) and self._not_this_removal(ctx, cik, filings, sub, f25):
                continue
            candidates.append((sub, f25))

        delistings: list[Delisting] = []
        last_definitive: Delisting | None = None
        for group in self._group(candidates):
            earliest_sub, earliest_f25 = min(group, key=lambda item: item[0].filing_date)
            if last_definitive is not None:
                gap = (date.fromisoformat(earliest_sub.filing_date) - date.fromisoformat(last_definitive.delist_date)).days
                if gap > IGNORE_AFTER_DEFINITIVE_DAYS and not ctx.seen_after(earliest_sub.filing_date):
                    continue        # a security truly gone can't have a later Form 25 of its own
            eff = effective_date(earliest_sub.filing_date)
            continued = self._continued(ctx, earliest_sub, earliest_f25)
            delisting = self._build_delisting(ctx, cik, filings, group, eff, continued)
            delistings.append(delisting)
            # Only an exchange transfer (or a delisting not classified) that the
            # security traded through continues it. A merger, liquidation,
            # compliance failure or expiration ends the security's exchange life.
            if not continued or delisting.record.bucket in ENDING_BUCKETS:
                last_definitive = delisting

        # spec 8.10: run the fallback / ended_without_delisting logic whenever
        # no delisting found is a genuine end (every one is `continued`, e.g. an
        # exchange transfer the security kept trading through) -- not only
        # when `delistings` is empty. Otherwise a security whose only delistings
        # are continued ones gets neither a real delisting nor a review row.
        review = scan.review
        if last_definitive is None:
            if ctx.listed_today is False:
                fb = self._fallback(ctx, cik, filings, ticker_last, scan.older)
                if fb is not None:
                    delistings.append(fb)
                else:
                    # Also next to form25_* rows: those say a filing could not be
                    # placed; accepting one as "not about this security" must not
                    # drop the security itself from review (spec 8.10, G6).
                    why = ("no Form 25 matched it (see its form25_* rows) and no other delisting filing found"
                           if scan.had_unmatched else "no Form 25 or delisting filing found")
                    review.append(ReviewItem(sec.sec_id, ticker_last, cik, "ended_without_delisting",
                                             f"not listed today and {why}", last_seen=ctx.last_seen))
            elif ctx.listed_today is None:
                review.append(ReviewItem(sec.sec_id, ticker_last, cik, "listing_status_unknown",
                                         "listing status unknown and no delisting found",
                                         last_seen=ctx.last_seen))
        return delistings, review
```

- [ ] **Step 5: The context reads the fails rows**

In `src/delist_detection/pipeline.py`, replace

```python
from .ftd import FTD_START, FtdIndex, close_age
```

with

```python
from .ftd import FTD_START, FtdIndex, close_age, trades_after
```

In `src/delist_detection/pipeline.py`, replace

```python
        sibs = siblings.get(s.issuer_cik) or [SecurityRef(s.sec_id, s.share_class, s.kind, s.name)]
```

with

```python
        sibs = siblings.get(s.issuer_cik) or [SecurityRef(s.sec_id, s.share_class, s.kind, s.name)]
        rows = ftd.trading_rows(sec_cusips.get(s.sec_id, []))
```

In `src/delist_detection/pipeline.py`, replace

```python
            cusip_switches=_cusip_switches(s, ftd, sec_cusips.get(s.sec_id, [])),
        )
```

with

```python
            cusip_switches=_cusip_switches(s, ftd, sec_cusips.get(s.sec_id, [])),
            trades_after=lambda day, rows=rows: trades_after(rows, day),
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_ftd.py tests/test_delistings.py tests/test_pipeline.py tests/test_form25_reach_cases.py`
Expected: PASS. Then the full suite: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: 2130 passed, 245 xfailed. The reach cases that move are exactly TMA, IMB, MNI, RHD, XMSR, SOV, IAR, LTRPA
and LKSD (IMB and TMA need Task 4's rule too; RHD's 570 needs Task 3's wording); if another case moves, stop and
report it.

- [ ] **Step 7: Commit**

```bash
git add src/delist_detection/ftd.py src/delist_detection/form25.py src/delist_detection/delistings.py src/delist_detection/pipeline.py tests/test_ftd.py tests/test_delistings.py tests/test_pipeline.py tests/test_form25_reach_cases.py
git commit -m "A security goes on after a Form 25 only when listed today or its own CUSIPs trade on, never after a removal under (b) (sub-plan 5b, C: XMSR, SOV, RHD, IAR, LKSD)"
```

---

### Task 7: R7, the issuer's own Form 25 with its 8-A12B moves the class

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/delistings.py`
- Test: `tests/test_delistings.py`, `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: Task 6's `_continued`, `_build_delisting`'s classification.
- Produces: `delistings.EIGHT_A_DAYS = 10`, `EIGHT_A_FORMS`, `ISSUER_FORM25_FORMS`;
  `DelistingFinder._eight_a(sub, f25, filings) -> EdgarSubmission | None`; `_continued(ctx, sub, f25, filings)`; an
  `unknown` row of a continued group with such an 8-A12B becomes 304 with the security as its own successor.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_delistings.py`:

```python
# --- sub-plan 5b, R7: the issuer's own Form 25 with its 8-A12B moves the class ---

def _exchange_move(fake_edgar, *, form="25", eight_a="2026-09-08", rule=""):
    """Kraft Heinz 2026: the issuer filed its own Form 25 (Nasdaq) and an 8-A12B (NYSE) the same day; no 8-K
    near it, so the classifier alone leaves the row `unknown`."""
    fake_edgar.submissions_by_cik[30201] = [
        EdgarSubmission("k25", form, "2026-09-08", "", "", "p.xml"),
        EdgarSubmission("k8a", "8-A12B", eight_a, "", "", "a.htm")]
    fake_edgar.raws["k25"] = _f25_raw("The Nasdaq Stock Market LLC", rule=rule, form_tag=form)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_KHC", 30201, "KHC", "2015-07-06", "2026-06-30", "KRAFT HEINZ CO")
    return DelistingFinder(fake_edgar, clf), sec


def test_the_issuers_form25_with_its_8a12b_is_an_exchange_transfer_of_the_security_itself(fake_edgar):
    finder, sec = _exchange_move(fake_edgar)
    (ev,), review = finder.find(_ctx(sec, listed=True, last_seen="2026-09-04"))
    assert (ev.record.crsp_code, ev.record.bucket, ev.record.successor_sec_id) == (
        304, CrspBucket.EXCHANGE_TRANSFER, "BBG_KHC")
    assert ev.record.reason == "Exchange transfer: the issuer's Form 25 2026-09-08 with its 8-A12B 2026-09-08"
    assert "no_evidence_default" not in ev.flags and review == []


def test_an_exchanges_form25_an_8a12b_eleven_days_off_or_a_removal_under_b_moves_nothing(fake_edgar):
    """DISCK and CWENA: an exchange's 25-NSE beside an 8-A12B for the replacement class is a real ending."""
    for kw in ({"form": "25-NSE"}, {"eight_a": "2026-08-28"}, {"rule": "17 CFR 240.12d2-2(b)"}):
        finder, sec = _exchange_move(fake_edgar, **kw)
        (ev,), _ = finder.find(_ctx(sec, listed=True, last_seen="2026-09-04"))
        assert ev.record.bucket is CrspBucket.UNKNOWN, kw


def test_the_issuers_exchange_move_continues_a_security_not_listed_today(fake_edgar):
    """Monster Worldwide 2008, MSG 2015: the move continues the security even with no fails rows after it."""
    finder, sec = _exchange_move(fake_edgar, eight_a="2026-08-29")
    events, _ = finder.find(_ctx(sec, listed=False, last_seen="2026-09-04"))
    assert events[0].record.successor_sec_id == "BBG_KHC"
```

Append to `tests/test_delistings.py`:

```python
def test_the_issuers_own_form25_in_a_group_with_the_exchanges_moves_the_class(fake_edgar):
    """Review Focus (R7): the exchange's 25-NSE first, the issuer's own Form 25 with its 8-A12B a day later: one
    group, and the move found on the issuer's filing."""
    finder, sec = _exchange_move(fake_edgar)
    fake_edgar.submissions_by_cik[30201] = [
        EdgarSubmission("kn", "25-NSE", "2026-09-07", "", "", "p.xml"),
        EdgarSubmission("k25", "25", "2026-09-08", "", "", "p.xml"),
        EdgarSubmission("k8a", "8-A12B", "2026-09-08", "", "", "a.htm")]
    fake_edgar.raws["kn"] = _f25_raw("The Nasdaq Stock Market LLC", form_tag="25-NSE")
    (ev,), _ = finder.find(_ctx(sec, listed=True, last_seen="2026-09-04"))
    assert (ev.record.crsp_code, ev.record.successor_sec_id) == (304, "BBG_KHC")
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C"}` with `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py tests/test_form25_reach_cases.py`
Expected: FAIL (the Kraft Heinz-like rows stay `unknown`; a security not listed today is not continued; the reach
case KHC).

- [ ] **Step 3: Implement**

In `src/delist_detection/delistings.py`, replace

```python
DEREG_FALLBACK_AFTER_DAYS = 120     # [last_seen - this, last_seen + this] to date the delisting
```

with

```python
DEREG_FALLBACK_AFTER_DAYS = 120     # [last_seen - this, last_seen + this] to date the delisting
EIGHT_A_DAYS = 10                   # the issuer's own Form 25 and its 8-A12B this close together: an exchange move
EIGHT_A_FORMS = frozenset({"8-A12B", "8-A12B/A"})
ISSUER_FORM25_FORMS = frozenset({"25", "25/A"})      # filed by the issuer, not by the exchange (25-NSE)
```

In `src/delist_detection/delistings.py`, replace

```python
    # -- whether the security went on after a Form 25 ------------------------
    def _continued(self, ctx: SecurityContext, sub: EdgarSubmission, f25: Form25) -> bool:
        """Whether the security went on trading after this Form 25: it is listed today; or the Form 25 is not an
        exchange's removal under rule 12d2-2(b) (`form25.is_involuntary`) and the security's own CUSIPs trade on
        after its effective date plus SEEN_AFTER_DAYS (`SecurityContext.trades_after`). An observation alone never
        continues a security: a stale snapshot lists one long after it was acquired (XMSR 2008, SOV 2009), and the
        OTC tail after a removal under (b) is not the listing going on (R.H. Donnelley, Idearc, LSC
        Communications)."""
        if ctx.listed_today:
            return True
        if is_involuntary(f25):
```

with

```python
    # -- whether the security went on after a Form 25 ------------------------
    @staticmethod
    def _eight_a(sub: EdgarSubmission, f25: Form25, filings: list[EdgarSubmission]) -> EdgarSubmission | None:
        """The issuer's 8-A12B filed within EIGHT_A_DAYS of its own Form 25 (form 25 or 25/A, not an exchange's
        25-NSE, and not a removal under rule 12d2-2(b)), nearest first: the class registered on the exchange it
        moved to as it left the old one (R7: Kraft Heinz 2026, Monster Worldwide 2008, MSG 2015). None for any
        other Form 25: an exchange's 25-NSE beside an 8-A12B for a replacement class is a real ending (DISCK
        2022, CWENA 2026)."""
        if sub.form not in ISSUER_FORM25_FORMS or is_involuntary(f25):
            return None
        day = date.fromisoformat(sub.filing_date)
        near = [(abs((date.fromisoformat(f.filing_date) - day).days), f.filing_date, f) for f in filings
                if f.form in EIGHT_A_FORMS and f.filing_date
                and abs((date.fromisoformat(f.filing_date) - day).days) <= EIGHT_A_DAYS]
        return min(near, key=lambda x: (x[0], x[1]))[2] if near else None

    def _continued(self, ctx: SecurityContext, sub: EdgarSubmission, f25: Form25,
                   filings: list[EdgarSubmission]) -> bool:
        """Whether the security went on trading after this Form 25: it is listed today; or the issuer moved the
        class to another exchange (`_eight_a`, R7); or the Form 25 is not an exchange's removal under rule
        12d2-2(b) (`form25.is_involuntary`) and the security's own CUSIPs trade on after its effective date plus
        SEEN_AFTER_DAYS (`SecurityContext.trades_after`). An observation alone never continues a security: a
        stale snapshot lists one long after it was acquired (XMSR 2008, SOV 2009), and the OTC tail after a
        removal under (b) is not the listing going on (R.H. Donnelley, Idearc, LSC Communications)."""
        if ctx.listed_today:
            return True
        if self._eight_a(sub, f25, filings) is not None:
            return True
        if is_involuntary(f25):
```

In `src/delist_detection/delistings.py`, replace

```python
            if self._continued(ctx, sub, f25) and self._not_this_removal(ctx, cik, filings, sub, f25):
```

with

```python
            if self._continued(ctx, sub, f25, filings) and self._not_this_removal(ctx, cik, filings, sub, f25):
```

In `src/delist_detection/delistings.py`, replace

```python
            continued = self._continued(ctx, earliest_sub, earliest_f25)
```

with

```python
            continued = self._continued(ctx, earliest_sub, earliest_f25, filings)
```

In `src/delist_detection/delistings.py`, replace

```python
                                             trading_after=continued)
        return self._delisting(sec, cik, ticker, eff, rec, lt, winner_f25, winner_sub, continued, extra_flags)
```

with

```python
                                             trading_after=continued)
        if continued and rec.bucket is CrspBucket.UNKNOWN:
            moved = next(((s, a) for s, f in sorted(group, key=lambda i: i[0].filing_date)
                          if (a := self._eight_a(s, f, filings)) is not None), None)
            if moved is not None:          # R7: the issuer moved the class (Kraft Heinz 2026, Nasdaq to NYSE)
                s, a = moved
                rec.crsp_code, rec.bucket, rec.confidence = 304, CrspBucket.EXCHANGE_TRANSFER, "high"
                rec.reason = f"Exchange transfer: the issuer's Form 25 {s.filing_date} with its 8-A12B {a.filing_date}"
                rec.evidence["flags"] = [f for f in rec.evidence.get("flags", []) if f != "no_evidence_default"]
        return self._delisting(sec, cik, ticker, eff, rec, lt, winner_f25, winner_sub, continued, extra_flags)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py tests/test_form25_reach_cases.py`
Expected: PASS (KHC moves; MSG, DISCK and CWENA stay). Then the full suite: 2134 passed, 245 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/delistings.py tests/test_delistings.py tests/test_form25_reach_cases.py
git commit -m "The issuer's own Form 25 with its 8-A12B within 10 days is an exchange move of the security itself (sub-plan 5b, R7: KHC)"
```

---

### Task 8: E, early reach for a security gone today

Tier: standard.

**Files:**
- Modify: `src/delist_detection/delistings.py`
- Test: `tests/test_delistings.py`, `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: Task 6's `_Scan`, `_judge`, `SecurityContext.trades_after`; Task 7's `_continued(..., filings)`.
- Produces: `delistings.EARLY_REACH_DAYS = 365`; `_Scan.unreadable`; `DelistingFinder._own_ref(ctx) ->
  SecurityRef`; `_judge(..., refs, *, quiet=False)`. Form 25s in [floor − 365 d, floor) of a security with
  `listed_today is False` are judged with the security itself alive and no review rows; when no group from the
  floor on is definitive, the latest early group whose security does not trade after it is the delisting (flagged
  `observed_after_delisting`); only older filings, and early ones whose text could not be read, go to the fallback.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_delistings.py`:

```python
# --- sub-plan 5b, E: early reach ---

def _two_early_groups(fake_edgar):
    """TXU 2007: an older Form 25 (January 2007, another event) and the merger's 25-NSE (2007-10-23), both in the
    year before the floor of a security a stale snapshot first lists on 2008-01-16. The 8-K nearest the 25-NSE is
    an earnings release (item 2.02) and the issuer kept filing for its debt, so the classifier's own pick drops it
    (its frozen-tail rule) and the fallback reads a continued-filings transfer at the last sighting."""
    fake_edgar.submissions_by_cik[30301] = [
        EdgarSubmission("t1", "25-NSE", "2007-01-10", "", "", "p.xml"),
        EdgarSubmission("t8", "8-K", "2007-10-11", "2007-10-11", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("t2", "25-NSE", "2007-10-23", "", "", "p.xml"),
        EdgarSubmission("te", "8-K", "2007-10-23", "2007-10-23", "2.02,9.01", "e.htm"),
        EdgarSubmission("tq", "10-Q", "2008-05-15", "2008-03-31", "", "q.htm"),
        EdgarSubmission("tk", "10-K", "2010-03-01", "2009-12-31", "", "k10.htm")]
    fake_edgar.raws["t1"] = NYSE_COMMON_RAW
    fake_edgar.raws["t2"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_TXU", 30301, "TXU", "2008-01-16", "2009-06-08", "TXU CORP")
    return DelistingFinder(fake_edgar, clf), sec


def test_the_latest_early_group_is_the_delisting_of_a_security_gone_today(fake_edgar):
    finder, sec = _two_early_groups(fake_edgar)
    (ev,), review = finder.find(_ctx(sec, listed=False, last_seen="2009-06-08"))
    assert (ev.delist_date, ev.form25_sub.accession, ev.record.bucket) == ("2007-11-02", "t2", CrspBucket.MERGER)
    assert "observed_after_delisting" in ev.flags and review == []


def test_early_reach_needs_the_security_gone_today(fake_edgar):
    """Laureate (listed today; its 2008 observations are of the old Laureate): a Form 25 before the floor of a
    security listed today, or whose listing is unknown, is never judged."""
    finder, sec = _two_early_groups(fake_edgar)
    assert finder.find(_ctx(sec, listed=True, last_seen="2009-06-08")) == ([], [])
    events, review = finder.find(_ctx(sec, listed=None, last_seen="2009-06-08"))
    assert events == [] and [r.flag for r in review] == ["listing_status_unknown"]


def test_an_early_form25_waits_for_no_definitive_delisting_from_the_floor_on(fake_edgar):
    finder, sec = _two_early_groups(fake_edgar)
    fake_edgar.submissions_by_cik[30301].append(EdgarSubmission("t3", "25-NSE", "2009-06-01", "", "", "p.xml"))
    fake_edgar.raws["t3"] = NYSE_COMMON_RAW
    events, _ = finder.find(_ctx(sec, listed=False, last_seen="2009-06-08"))
    assert [e.form25_sub.accession for e in events] == ["t3"]
```

Append to `tests/test_delistings.py`:

```python
def test_an_early_form25_whose_text_cannot_be_read_raises_no_review_row(fake_edgar):
    """Review Focus (E): about 300 early-window Form 25s are not cached; one that cannot be read is left to the
    fallback, with no `form25_unreadable` row (the floor's own filings keep that row)."""
    finder, sec = _two_early_groups(fake_edgar)
    del fake_edgar.raws["t2"]
    events, review = finder.find(_ctx(sec, listed=False, last_seen="2009-06-08"))
    assert not any(r.flag == "form25_unreadable" for r in review)
    assert all(e.form25_sub is None or e.form25_sub.accession != "t2" for e in events)
```

The fallback's own early test now meets E first; change it to the trading test E reads, and pin the fallback on a
filing older than the early window:

In `tests/test_delistings.py`, replace

```python
def test_form25_before_first_sighting_is_not_taken_when_ftd_shows_trading_after_it(fake_edgar):
    # Fails-to-deliver rows under the security's own ticker after the early
    # Form 25 show it kept trading: that filing ended something else (an old
    # exchange move), so it is not revived.
    edgar = _stale_snapshot_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG_AGE", 21000, "AGE", "2008-01-16", "2009-06-08", "EDWARDS AG INC")
    ctx = _ctx(sec, listed=False, last_seen="2009-06-08")
    ctx.ftd_seen_after = lambda d: d < "2009-06-01"
    events, review = DelistingFinder(edgar, clf).find(ctx)
    assert events == []
    assert [r.flag for r in review] == ["ended_without_delisting"]
```

with

```python
def test_form25_before_first_sighting_is_not_taken_when_ftd_shows_trading_after_it(fake_edgar):
    # Fails-to-deliver rows of the security's own CUSIPs after the early Form 25
    # show it kept trading: that filing ended something else (an old exchange
    # move), so it is not taken (sub-plan 5b, E: `trades_after`).
    edgar = _stale_snapshot_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG_AGE", 21000, "AGE", "2008-01-16", "2009-06-08", "EDWARDS AG INC")
    ctx = _ctx(sec, listed=False, last_seen="2009-06-08")
    ctx.trades_after = lambda d: d < "2009-06-01"
    events, review = DelistingFinder(edgar, clf).find(ctx)
    assert events == []
    assert [r.flag for r in review] == ["ended_without_delisting"]


def test_a_form25_older_than_the_early_window_is_still_the_fallbacks(fake_edgar):
    """The fallback still judges a Form 25 from before the early window (more than EARLY_REACH_DAYS before the
    floor): the classifier picks it, `_early_group` matches it, and fails rows under the security's own tickers
    after it refuse it."""
    edgar = _stale_snapshot_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG_AGE", 21000, "AGE", "2009-01-16", "2009-06-08", "EDWARDS AG INC")   # floor 2008-12-17
    (ev,), review = DelistingFinder(edgar, clf).find(_ctx(sec, listed=False, last_seen="2009-06-08"))
    assert ev.form25_sub.accession == "w2" and "observed_after_delisting" in ev.flags
    ctx = _ctx(sec, listed=False, last_seen="2009-06-08")
    ctx.ftd_seen_after = lambda d: d < "2009-06-01"
    events, review = DelistingFinder(edgar, clf).find(ctx)
    assert events == [] and [r.flag for r in review] == ["ended_without_delisting"]
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7"}` with `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py tests/test_form25_reach_cases.py`
Expected: FAIL (the TXU-like case gives the fallback's 304 at the last sighting; the early test with `trades_after`
takes the Form 25; the reach cases TXU, BMET and STN).

- [ ] **Step 3: Implement**

In `src/delist_detection/delistings.py`, replace

```python
ISSUER_FORM25_FORMS = frozenset({"25", "25/A"})      # filed by the issuer, not by the exchange (25-NSE)
```

with

```python
ISSUER_FORM25_FORMS = frozenset({"25", "25/A"})      # filed by the issuer, not by the exchange (25-NSE)
EARLY_REACH_DAYS = 365              # gone today: Form 25s this far before the floor are judged in the main scan
```

In `src/delist_detection/delistings.py`, replace

```python
    """The finder's working state for one security: the ticker its review rows carry, the review items and the
    keys already raised, whether some Form 25 could not be placed, and the Form 25s from before the floor (the
    fallback's to judge)."""
    ticker: str
    review: list[ReviewItem] = field(default_factory=list)
    seen: set[tuple[str, str]] = field(default_factory=set)
    had_unmatched: bool = False
    older: list[EdgarSubmission] = field(default_factory=list)
```

with

```python
    """The finder's working state for one security: the ticker its review rows carry, the review items and the
    keys already raised, whether some Form 25 could not be placed, the Form 25s from before the early window (the
    fallback's to judge), and those whose text could not be read."""
    ticker: str
    review: list[ReviewItem] = field(default_factory=list)
    seen: set[tuple[str, str]] = field(default_factory=set)
    had_unmatched: bool = False
    older: list[EdgarSubmission] = field(default_factory=list)
    unreadable: list[EdgarSubmission] = field(default_factory=list)
```

In `src/delist_detection/delistings.py`, replace

```python
    # -- one Form 25 against the security --------------------------------------
    def _judge(self, ctx: SecurityContext, scan: _Scan, filer: int, sub: EdgarSubmission,
               refs: list[SecurityRef]) -> Form25 | None:
        """The Form 25 `sub` of CIK `filer`, parsed, when it removed this security: readable, not a regional
        exchange's, of a recognized class, matched to this security among `refs` (`match_securities`) with no
        class-letter conflict. Else None, and a filing that could not be placed gets its review row."""
        sec, ticker = ctx.security, scan.ticker
        raw = self.edgar.fetch_filing_raw(filer, sub.accession)
        if not raw:
            scan.had_unmatched = True
            self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unreadable",
                         f"no filing text for {sub.form} {sub.accession}", sub)
            return None
        f25 = parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date)
        if f25.exchange in REGIONAL_EXCHANGES:
            return None
        if class_kind(f25.class_text) == "other":
            scan.had_unmatched = True
            self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unclassified",
                         f"{sub.form} {sub.accession} ({f25.class_text!r}) has no recognized class", sub)
            return None
        matched, why = match_securities(f25, refs)
        if not matched:
            if why == "ambiguous class":
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unmatched",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}): {why}", sub)
            return None
        if sec.sec_id not in matched:
            if sec.sec_id in tied_securities(f25, refs):
```

with

```python
    # -- one Form 25 against the security --------------------------------------
    @staticmethod
    def _own_ref(ctx: SecurityContext) -> SecurityRef:
        sec = ctx.security
        return next((r for r in ctx.siblings if r.sec_id == sec.sec_id),
                    SecurityRef(sec.sec_id, sec.share_class, sec.kind, sec.name))

    def _judge(self, ctx: SecurityContext, scan: _Scan, filer: int, sub: EdgarSubmission,
               refs: list[SecurityRef], *, quiet: bool = False) -> Form25 | None:
        """The Form 25 `sub` of CIK `filer`, parsed, when it removed this security: readable, not a regional
        exchange's, of a recognized class, matched to this security among `refs` (`match_securities`) with no
        class-letter conflict. Else None; a filing that could not be placed gets its review row unless `quiet`
        (the early window's filings)."""
        sec, ticker = ctx.security, scan.ticker
        raw = self.edgar.fetch_filing_raw(filer, sub.accession)
        if not raw:
            scan.unreadable.append(sub)
            if not quiet:
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unreadable",
                             f"no filing text for {sub.form} {sub.accession}", sub)
            return None
        f25 = parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date)
        if f25.exchange in REGIONAL_EXCHANGES:
            return None
        if class_kind(f25.class_text) == "other":
            if not quiet:
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unclassified",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}) has no recognized class", sub)
            return None
        matched, why = match_securities(f25, refs)
        if not matched:
            if why == "ambiguous class" and not quiet:
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unmatched",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}): {why}", sub)
            return None
        if sec.sec_id not in matched:
            if sec.sec_id in tied_securities(f25, refs) and not quiet:
```

In `src/delist_detection/delistings.py`, replace

```python
        floor = (date.fromisoformat(first_seen) - timedelta(days=FORM25_LOOKBACK_DAYS)).isoformat()
        scan = _Scan(ticker_last)
        candidates: list[tuple[EdgarSubmission, Form25]] = []
        for sub in list_form25(filings):
            if sub.filing_date < floor:
                scan.older.append(sub)          # before the floor: only the fallback may take one
                continue
```

with

```python
        floor = (date.fromisoformat(first_seen) - timedelta(days=FORM25_LOOKBACK_DAYS)).isoformat()
        # E: a security gone today also judges the Form 25s of the year before the floor, as when a stale
        # snapshot first listed it months after its merger (TXU, Station Casinos, Biomet 2007)
        early_floor = (date.fromisoformat(floor) - timedelta(days=EARLY_REACH_DAYS)).isoformat() \
            if ctx.listed_today is False else floor
        own = self._own_ref(ctx)
        scan = _Scan(ticker_last)
        early: list[tuple[EdgarSubmission, Form25]] = []
        candidates: list[tuple[EdgarSubmission, Form25]] = []
        for sub in list_form25(filings):
            if sub.filing_date < floor:
                if sub.filing_date < early_floor:
                    scan.older.append(sub)      # before the early window: only the fallback may take one
                    continue
                refs = [own] + [r for r in ctx.siblings
                                if r.sec_id != sec.sec_id and self._alive_at(ctx, r.sec_id, sub.filing_date)]
                f25 = self._judge(ctx, scan, cik, sub, refs, quiet=True)
                after = date.fromisoformat(effective_date(sub.filing_date)) + timedelta(days=SEEN_AFTER_DAYS)
                if f25 is not None and not ctx.trades_after(after.isoformat()):
                    early.append((sub, f25))
                elif f25 is None and sub in scan.unreadable:
                    scan.older.append(sub)          # never read: the fallback may still take it
                continue
```

In `src/delist_detection/delistings.py`, replace

```python
            if not continued or delisting.record.bucket in ENDING_BUCKETS:
                last_definitive = delisting

        # spec 8.10:
```

with

```python
            if not continued or delisting.record.bucket in ENDING_BUCKETS:
                last_definitive = delisting

        # E: with no definitive delisting from the floor on, the latest early
        # group is the delisting (an older group must not pre-empt it: TXU's
        # Form 25s of January 2007); the observations after it are flagged.
        if last_definitive is None and early:
            group = self._group(early)[-1]
            eff = effective_date(min(s.filing_date for s, _ in group))
            last_definitive = self._build_delisting(ctx, cik, filings, group, eff, False,
                                                    ("observed_after_delisting",))
            delistings.insert(0, last_definitive)

        # spec 8.10:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py tests/test_form25_reach_cases.py`
Expected: PASS (TXU, BMET and STN move; LAUR reads no early raw; JNC and AT stay). Then the full suite: 2139
passed, 245 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/delistings.py tests/test_delistings.py tests/test_form25_reach_cases.py
git commit -m "A security gone today takes the latest Form 25 group of the year before its first sighting (sub-plan 5b, E: TXU, STN, BMET)"
```

---

### Task 9: R3, a Form 25 about another class matches no security

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/form25.py`, `src/delist_detection/delistings.py`
- Test: `tests/test_form25.py`, `tests/test_delistings.py`, `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: Task 5's `pytest` and `fc` imports in tests/test_form25.py; Task 8's `_own_ref`, `_judge`.
- Produces: `Form25.solely: str = ""`; `form25.other_class(f25, ref, issuer_names=()) -> str` (a reason, or "");
  `DelistingFinder._issuer_names(cik) -> tuple[str, ...]`; `_judge(ctx, scan, filer, sub, refs, issuer_names, *,
  quiet=False)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_form25.py`:

```python
# --- sub-plan 5b, R3: a Form 25 about another class ---

from delist_detection.form25 import other_class  # noqa: E402

LIBERTY_2011 = ("Series A Liberty Capital Common Stock, Series B Liberty Capital Common Stock, Liberty Starz Ser A "
                "Common Stock, Liberty Starz Ser B Common Stock")
LIBERTY_NAMES = ("QVC Group, Inc.", "Qurate Retail, Inc.", "Liberty Interactive Corp", "LIBERTY MEDIA CORP",
                 "Liberty Media Holding CORP")


def test_a_form25_of_other_tracking_groups_is_not_about_the_series_a_of_another():
    """Liberty Media's 2011 25-NSE removed the Liberty Capital and Liberty Starz groups; the Series A placeholder
    of Liberty Interactive (later Qurate) kept trading."""
    f = Form25("a", "25-NSE", "2011-09-23", "NASDAQ", LIBERTY_2011, "", "")
    ref = SecurityRef("CIK1355096-SERIES-A", "SERIES A", "common", "QURATE RETAIL GROUP CORP SERIES A")
    assert other_class(f, ref, LIBERTY_NAMES) == "names another group (CAPITAL)"


@pytest.mark.parametrize("class_text,name", [
    ("Series A Liberty Ventures Common Stock & Series B Liberty Ventures Common Stock",
     "LIBERTY INTERACTIVE VENTURE CORP S"),                                      # LVNTA 2018: VENTURE, VENTURES
    ("Class A Special Common Stock", "COMCAST SPECIAL CORP CLASS A"),             # CMCSK 2015: SPECIAL is no group
    ("Series N Non-Voting Common Stock", "U HAUL NON VOTING SERIES N"),           # U-Haul 2022
    ("Series A Liberty SiriusXM Common Stock", "LIBERTY MEDIA LIBERTY SIRIUSXM COR"),
    ("Common Stock", "BIOMET INC"),
], ids=["LVNTA", "CMCSK", "UHALB", "LSXMA", "plain"])
def test_a_form25_of_the_securitys_own_group_or_of_no_group_is_its_own(class_text, name):
    f = Form25("a", "25-NSE", "2018-03-09", "NASDAQ", class_text, "", "")
    assert other_class(f, SecurityRef("S", "SERIES A", "common", name), LIBERTY_NAMES) == ""


def test_a_form25_that_relates_solely_to_the_rights_is_not_about_the_common():
    """Biomet 2006 (0001104659-06-082100): "Common Shares; Preferred Share Purchase Rights", and the notification
    "relates solely to the withdrawal from listing of the Preferred Share Purchase Rights"."""
    raw = fc.EDGAR["raws"]["0001104659-06-082100"]
    f = parse_form25(raw, accession="0001104659-06-082100", form="25", filing_date="2006-12-18")
    assert (f.class_text, f.solely) == ("Common Shares; Preferred Share Purchase Rights",
                                        "Preferred Share Purchase Rights")
    assert other_class(f, SecurityRef("CIK351346-COMMON", "COMMON", "common", "BIOMET INC")) == \
        "relates solely to Preferred Share Purchase Rights"
```

Append to `tests/test_delistings.py`:

```python
# --- sub-plan 5b, R3: a Form 25 about another class matches no security ---

def test_a_form25_of_other_tracking_groups_is_no_delisting_of_the_series_a(fake_edgar):
    """Liberty 2011: the 25-NSE of the Capital and Starz groups is not the Series A placeholder's (it matched by
    elimination before: the issuer's only common of the run alive then)."""
    fake_edgar.submissions_by_cik[30401] = [EdgarSubmission("l25", "25-NSE", "2011-09-23", "", "", "p.xml")]
    fake_edgar.company_map["LINTA"] = {"cik_str": 30401, "ticker": "LINTA", "title": "Liberty Interactive Corp"}
    fake_edgar.raws["l25"] = _f25_raw("The Nasdaq Stock Market LLC", class_text=(
        "Series A Liberty Capital Common Stock, Series B Liberty Capital Common Stock, Liberty Starz Ser A Common "
        "Stock, Liberty Starz Ser B Common Stock"))
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("CIK30401-SERIES-A", 30401, "LINTA", "2008-01-16", "2011-06-30", "QURATE RETAIL GROUP CORP SERIES A")
    sec.share_class = "SERIES A"
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=False, last_seen="2011-06-30"))
    assert events == [] and [r.flag for r in review] == ["ended_without_delisting"]
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E"}` with `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E", "R3"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_form25.py tests/test_delistings.py tests/test_form25_reach_cases.py`
Expected: FAIL (`cannot import name 'other_class'`; the Liberty-like 25-NSE gives a delisting; the reach case
Liberty Series A).

- [ ] **Step 3: Read the class a Form 25 is solely about, and its tracking groups**

In `src/delist_detection/form25.py`, replace

```python
    rule: str
    notice_text: str


def is_involuntary(
```

with

```python
    rule: str
    notice_text: str
    # The class a "This Notification relates solely to ..." sentence names ("Preferred Share Purchase Rights": BMET
    # 2006), else "".
    solely: str = ""


def is_involuntary(
```

In `src/delist_detection/form25.py`, replace

```python
def parse_form25(raw: str, *, accession: str, form: str, filing_date: str) -> Form25:
```

with

```python
_SOLELY = re.compile(r"relates\s+solely\s+to\s+(?:the\s+)?(?:withdrawal\s+from\s+listing\s+of\s+(?:the\s+|our\s+)?)?"
                     r"(.{3,80}?)\s+from", re.I)


def _solely(raw: str) -> str:
    """The class a "This Notification relates solely to the withdrawal from listing of <class> from ..." sentence
    names, anywhere in the filing, else ""."""
    m = _SOLELY.search(re.sub(r"\s+", " ", strip_html(raw)))
    return m.group(1).strip() if m else ""


def parse_form25(raw: str, *, accession: str, form: str, filing_date: str) -> Form25:
```

In `src/delist_detection/form25.py`, replace

```python
    return Form25(accession, form, filing_date, exchange_label(exch_name) or exch_name.upper(),
                  class_text, rule, _notice(raw))
```

with

```python
    return Form25(accession, form, filing_date, exchange_label(exch_name) or exch_name.upper(),
                  class_text, rule, _notice(raw), _solely(raw))
```

In `src/delist_detection/form25.py`, replace

```python
def class_letters(class_text: str) -> set[str]:
    """Every class letter the Form 25's text names."""
    return {class_letter(label) for label, _ in _lettered_segments(class_text)} - {None}
```

with

```python
def class_letters(class_text: str) -> set[str]:
    """Every class letter the Form 25's text names."""
    return {class_letter(label) for label, _ in _lettered_segments(class_text)} - {None}


# R3: a lettered tracking-stock segment ("Series A Liberty Capital Common Stock"). Its group words are the words
# between the letter and COMMON STOCK, less the issuer's own EDGAR name words and these.
_GROUP = re.compile(r"^\W*(?:SERIES|CLASS)\s+[A-Z]\s+(.+?)\s+COMMON\s+STOCK", re.I)
_GROUP_STOP = frozenset({"SPECIAL", "NON", "VOTING", "NONVOTING", "NEW", "OLD", "ORDINARY"})


def _meets(word: str, words: set[str]) -> bool:
    """`word` is one of `words`, or one is a prefix of the other and both have five or more letters (VENTURE,
    VENTURES)."""
    return any(word == w or (min(len(word), len(w)) >= 5 and (word.startswith(w) or w.startswith(word)))
               for w in words)


def other_class(f25: Form25, ref: SecurityRef, issuer_names: Iterable[str] = ()) -> str:
    """Why a common-class Form 25 of the security's issuer is about another class than `ref` (R3), else "": it
    "relates solely to" a class that is not common (BMET 2006: "Common Shares; Preferred Share Purchase Rights",
    solely the rights), or it has lettered tracking-stock segments and none of their group words (less the
    issuer's EDGAR name words, `issuer_names`) is a word of the security's name ("Series A Liberty Capital Common
    Stock, Series A Liberty Starz Common Stock" is not Liberty Interactive's Series A)."""
    if class_kind(f25.class_text) != "common":
        return ""
    if f25.solely and class_kind(f25.solely) not in ("common", "other"):
        return f"relates solely to {f25.solely}"
    issuer_words = {w for n in issuer_names for w in name_tokens(n)}
    groups = []
    for _, seg in _lettered_segments(f25.class_text):
        m = _GROUP.search(seg.strip())
        if m:
            words = name_tokens(m.group(1)) - issuer_words - _GROUP_STOP
            if words:
                groups.append(words)
    mine = name_tokens(ref.name)
    if groups and not any(_meets(w, mine) for g in groups for w in g):
        return "names another group (" + ", ".join(sorted(set().union(*groups))) + ")"
    return ""
```

- [ ] **Step 4: The finder refuses a Form 25 about another class**

In `src/delist_detection/delistings.py`, replace

```python
from .edgar import EdgarSubmission
from .figi_resolution import class_letter
```

with

```python
from .edgar import EdgarSubmission
from .evidence import edgar_names
from .figi_resolution import class_letter
```

In `src/delist_detection/delistings.py`, replace

```python
    list_form25, match_securities, notice_last_trade, parse_form25, tied_securities,
```

with

```python
    list_form25, match_securities, notice_last_trade, other_class, parse_form25, tied_securities,
```

In `src/delist_detection/delistings.py`, replace

```python
    def _judge(self, ctx: SecurityContext, scan: _Scan, filer: int, sub: EdgarSubmission,
               refs: list[SecurityRef], *, quiet: bool = False) -> Form25 | None:
        """The Form 25 `sub` of CIK `filer`, parsed, when it removed this security: readable, not a regional
        exchange's, of a recognized class, matched to this security among `refs` (`match_securities`) with no
        class-letter conflict. Else None; a filing that could not be placed gets its review row unless `quiet`
        (the early window's filings)."""
```

with

```python
    def _issuer_names(self, cik: int) -> tuple[str, ...]:
        """The issuer's EDGAR names (current and former), for R3's group words; () when they cannot be read."""
        sub = self.edgar.submissions(cik)
        return edgar_names(sub) if isinstance(sub, dict) else ()

    def _judge(self, ctx: SecurityContext, scan: _Scan, filer: int, sub: EdgarSubmission,
               refs: list[SecurityRef], issuer_names: tuple[str, ...], *, quiet: bool = False) -> Form25 | None:
        """The Form 25 `sub` of CIK `filer`, parsed, when it removed this security: readable, not a regional
        exchange's, of a recognized class, not about another class (`form25.other_class`, R3, against the filer's
        EDGAR names `issuer_names`), matched to this security among `refs` (`match_securities`) with no
        class-letter conflict. Else None; a filing that could not be placed gets its review row unless `quiet`
        (the early window's filings)."""
```

In `src/delist_detection/delistings.py`, replace

```python
                             f"{sub.form} {sub.accession} ({f25.class_text!r}) has no recognized class", sub)
            return None
        matched, why = match_securities(f25, refs)
```

with

```python
                             f"{sub.form} {sub.accession} ({f25.class_text!r}) has no recognized class", sub)
            return None
        if other_class(f25, self._own_ref(ctx), issuer_names):
            return None
        matched, why = match_securities(f25, refs)
```

In `src/delist_detection/delistings.py`, replace

```python
        own = self._own_ref(ctx)
        scan = _Scan(ticker_last)
```

with

```python
        own = self._own_ref(ctx)
        scan = _Scan(ticker_last)
        names = self._issuer_names(cik)
```

In `src/delist_detection/delistings.py`, replace

```python
                f25 = self._judge(ctx, scan, cik, sub, refs, quiet=True)
```

with

```python
                f25 = self._judge(ctx, scan, cik, sub, refs, names, quiet=True)
```

In `src/delist_detection/delistings.py`, replace

```python
            f25 = self._judge(ctx, scan, cik, sub, alive)
```

with

```python
            f25 = self._judge(ctx, scan, cik, sub, alive, names)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_form25.py tests/test_delistings.py tests/test_form25_reach_cases.py`
Expected: PASS (Liberty Series A moves; LVNTA, CMCSK and the Liberty Live and SiriusXM unit tests stay). Then the full
suite: 2147 passed, 245 xfailed.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/form25.py src/delist_detection/delistings.py tests/test_form25.py tests/test_delistings.py tests/test_form25_reach_cases.py
git commit -m "A Form 25 solely about rights, or about other tracking groups, is not the common's (sub-plan 5b, R3: Liberty Series A, BMET 2006)"
```

---

### Task 10: L, late reach past the alive window

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/delistings.py`, `src/delist_detection/pipeline.py`
- Test: `tests/test_delistings.py`, `tests/test_pipeline.py`, `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: Task 6's `_one_security_context` in tests/test_pipeline.py and the context's `rows`; Task 8's `own`.
- Produces: `delistings.LATE_ROW_DAYS = 30`; `SecurityContext.cusip_rows_near: Callable[[str], bool]`;
  `pipeline._rows_near(rows, day) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_delistings.py`:

```python
# --- sub-plan 5b, L: late reach ---

def _late_merger(fake_edgar):
    """Monster Worldwide 2016: NYSE removed the common at the Randstad merger (25-NSE 2016-11-01), years after the
    caller's last observation (2009-06-08) and the security's own alive window (+400 days)."""
    fake_edgar.submissions_by_cik[30501] = [
        EdgarSubmission("m8", "8-K", "2016-11-01", "2016-11-01", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("m25", "25-NSE", "2016-11-01", "", "", "p.xml")]
    fake_edgar.raws["m25"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_MWW", 30501, "MNST", "2008-01-16", "2009-06-08", "MONSTER WORLDWIDE INC")
    ctx = _ctx(sec, listed=False, last_seen="2009-06-08")
    ctx.sibling_spans = {"BBG_MWW": ("2008-01-16", "2009-06-08")}
    return DelistingFinder(fake_edgar, clf), ctx


def test_a_form25_after_the_alive_window_reaches_a_security_whose_cusip_traded_up_to_it(fake_edgar):
    finder, ctx = _late_merger(fake_edgar)
    ctx.cusip_rows_near = lambda day: day == "2016-11-01"
    (ev,), review = finder.find(ctx)
    assert (ev.delist_date, ev.form25_sub.accession, ev.record.bucket) == ("2016-11-11", "m25", CrspBucket.MERGER)


def test_a_late_form25_with_no_fails_row_of_the_security_near_it_is_still_ignored(fake_edgar):
    finder, ctx = _late_merger(fake_edgar)
    events, _ = finder.find(ctx)
    assert all(e.form25_sub is None for e in events)
```

Append to `tests/test_pipeline.py`:

```python
# --- sub-plan 5b, L: a fails row of the security's own CUSIP near a day ---

def test_the_finders_context_sees_its_own_cusip_trading_in_the_30_days_up_to_a_day():
    rows = [FtdRow("2016-10-03", "74955W307", "MWW", "MONSTER WORLDWIDE", 3.3),
            FtdRow("2016-10-31", "74955W307", "MWW", "MONSTER WORLDWIDE", 3.4)]
    ctx = _one_security_context(rows)
    assert ctx.cusip_rows_near("2016-11-01") and ctx.cusip_rows_near("2016-10-31")
    assert not ctx.cusip_rows_near("2016-12-01") and not ctx.cusip_rows_near("2016-10-02")
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E", "R3"}` with `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E", "R3", "L"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py tests/test_pipeline.py tests/test_form25_reach_cases.py`
Expected: FAIL (the late 25-NSE is ignored; `no attribute 'cusip_rows_near'`; the reach case MWW).

- [ ] **Step 3: Implement**

In `src/delist_detection/delistings.py`, replace

```python
EARLY_REACH_DAYS = 365              # gone today: Form 25s this far before the floor are judged in the main scan
```

with

```python
EARLY_REACH_DAYS = 365              # gone today: Form 25s this far before the floor are judged in the main scan
LATE_ROW_DAYS = 30                  # no sibling alive: the security's own CUSIP traded this close before the Form 25
```

In `src/delist_detection/delistings.py`, replace

```python
    trades_after: Callable[[str], bool] = lambda day: False
```

with

```python
    trades_after: Callable[[str], bool] = lambda day: False
    # True when the security's own CUSIPs have a trading fails row in the LATE_ROW_DAYS up to the given ISO day:
    # a Form 25 filed long after the security's last sighting still reaches it (Monster Worldwide 2016, L).
    cusip_rows_near: Callable[[str], bool] = lambda day: False
```

In `src/delist_detection/delistings.py`, replace

```python
            # readability/classification ones below.
            alive = [r for r in ctx.siblings if self._alive_at(ctx, r.sec_id, sub.filing_date)]
            if not alive:
                continue
```

with

```python
            # readability/classification ones below. L: the security itself
            # still counts when its own CUSIP traded within LATE_ROW_DAYS before
            # the filing (a line that went on under a ticker it was never seen
            # under: Monster Worldwide's NYSE MWW, 2016).
            alive = [r for r in ctx.siblings if self._alive_at(ctx, r.sec_id, sub.filing_date)]
            if not alive:
                if not ctx.cusip_rows_near(sub.filing_date):
                    continue
                alive = [own]
```

In `src/delist_detection/pipeline.py`, replace

```python
from .delistings import SUCCESSOR_UNKNOWN, Delisting, DelistingFinder, SecurityContext
```

with

```python
from .delistings import LATE_ROW_DAYS, SUCCESSOR_UNKNOWN, Delisting, DelistingFinder, SecurityContext
```

In `src/delist_detection/pipeline.py`, replace

```python
from .ftd import FTD_START, FtdIndex, close_age, trades_after
```

with

```python
from .ftd import FTD_START, FtdIndex, FtdRow, close_age, trades_after
```

In `src/delist_detection/pipeline.py`, replace

```python
def _context_builder(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
```

with

```python
def _rows_near(rows: Sequence[FtdRow], day: str) -> bool:
    """Whether a trading fails row of the security's own CUSIPs (`rows`) is dated in the LATE_ROW_DAYS up to the
    ISO day `day`."""
    lo = (date.fromisoformat(day) - timedelta(days=LATE_ROW_DAYS)).isoformat()
    return any(lo <= r.date <= day for r in rows)


def _context_builder(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
```

In `src/delist_detection/pipeline.py`, replace

```python
            trades_after=lambda day, rows=rows: trades_after(rows, day),
        )
```

with

```python
            trades_after=lambda day, rows=rows: trades_after(rows, day),
            cusip_rows_near=lambda day, rows=rows: _rows_near(rows, day),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_delistings.py tests/test_pipeline.py tests/test_form25_reach_cases.py`
Expected: PASS (MWW gains its 2016 merger and keeps its 2008 transfer). Then the full suite: 2150 passed, 245
xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/delistings.py src/delist_detection/pipeline.py tests/test_delistings.py tests/test_pipeline.py tests/test_form25_reach_cases.py
git commit -m "A Form 25 after the alive window still reaches a security whose own CUSIP traded up to it (sub-plan 5b, L: Monster Worldwide 2016)"
```

---

### Task 11: R2, a letterless class takes the letter its own fails descriptions name

Tier: cheap.

**Files:**
- Modify: `src/delist_detection/form25.py`, `src/delist_detection/pipeline.py`
- Test: `tests/test_form25.py`, `tests/test_pipeline.py`, `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SecurityRef.letter_hint: str | None = None`; `form25.letter_hint(descriptions) -> str | None`;
  `pipeline._security_ref(s, ftd, cusips) -> SecurityRef`. A hint fills only a letter no sibling's share class
  carries (Ruling 2: LVNTA).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_form25.py`:

```python
# --- sub-plan 5b, R2: a letterless common takes the letter its own fails descriptions name ---

from delist_detection.form25 import letter_hint  # noqa: E402


def test_the_letter_a_securitys_fails_descriptions_name():
    assert letter_hint(["SUNPOWER CORP CL A"]) == "A"
    assert letter_hint(["LIBERTY INTERACTIVE CORP SER A", "LIBERTY INTERACTIVE CORP"]) == "A"
    assert letter_hint(["X CORP CLASS A", "X CORP CL B"]) is None
    assert letter_hint(["SUNPOWER CORP", ""]) is None


SUNPOWER_2011 = Form25("a", "25-NSE", "2011-11-16", "NASDAQ", "Common Stock Class A & Common Stock Class B", "", "")


def test_a_class_no_siblings_share_class_carries_goes_to_the_letterless_one_its_fails_name():
    """SunPower 2011: the class A placeholder ("SUNPOWER CORP CL A") and the recombined SPWR line, both letterless;
    without the hint the 25-NSE ties them."""
    refs = [SecurityRef("CIK867773-COMMON", "COMMON", "common", "SUNPOWER CORP", "A"),
            SecurityRef("BBG000FVQ185", "COMMON", "common", "SUNPOWER CORP.")]
    assert match_securities(SUNPOWER_2011, refs) == (["CIK867773-COMMON"], "class A")
    no_hint = [SecurityRef(r.sec_id, r.share_class, r.kind, r.name) for r in refs]
    assert match_securities(SUNPOWER_2011, no_hint) == ([], "ambiguous class")


def test_a_hint_never_competes_with_a_share_class_that_carries_the_letter():
    """LVNTA 2018: the duplicate placeholder's fails say SER A too; LVNTA's own Series A takes the Form 25."""
    f = Form25("a", "25-NSE", "2018-03-09", "NASDAQ",
               "Series A Liberty Ventures Common Stock & Series B Liberty Ventures Common Stock", "", "")
    refs = [SecurityRef("BBG0038K9G41", "SERIES A", "common", "LIBERTY INTERACTIVE VENTURE CORP S"),
            SecurityRef("CIK1355096-COMMON", "COMMON", "common", "LIBERTY INTERACTIVE VENTURE CORP S", "A"),
            SecurityRef("BBG000PCQQL6", "SERIES A", "common", "QURATE RETAIL INC SERIES A")]
    assert match_securities(f, refs)[0] == ["BBG0038K9G41"]
```

Append to `tests/test_pipeline.py`:

```python
# --- sub-plan 5b, R2: the finder's view of a letterless class ---

def test_a_letterless_security_takes_the_letter_of_its_own_cusips_fails_descriptions():
    from delist_detection.ftd import FtdIndex
    ftd = FtdIndex([FtdRow("2011-06-01", "867652109", "SPWRA", "SUNPOWER CORP CL A", 20.0),
                    FtdRow("2011-06-01", "867652307", "SPWRB", "SUNPOWER CORP CL B", 19.0)])
    plain = Security("CIK867773-COMMON", 867773, "COMMON", "SUNPOWER CORP", "", True, "placeholder")
    lettered = Security("BBG_B", 867773, "CLASS B", "SUNPOWER CORP CL B", "", True, "cusip")
    assert pipeline._security_ref(plain, ftd, ["867652109"]).letter_hint == "A"
    assert pipeline._security_ref(lettered, ftd, ["867652307"]).letter_hint is None
    assert pipeline._security_ref(plain, ftd, []).letter_hint is None
```

Append to `tests/test_form25.py`:

```python
def test_two_letterless_siblings_both_hinted_the_letter_stay_tied():
    """Review Focus (R2): a FIGI line and a placeholder of one class A, both letterless and both "CL A" in their
    fails: the hint cannot tell them apart, so the Form 25 stays ambiguous, as before."""
    refs = [SecurityRef("BBG_A", "COMMON", "common", "SUNPOWER CORP", "A"),
            SecurityRef("CIK_A", "COMMON", "common", "SUNPOWER CORP", "A")]
    assert match_securities(SUNPOWER_2011, refs) == ([], "ambiguous class")
    assert tied_securities(SUNPOWER_2011, refs) == {"BBG_A", "CIK_A"}
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E", "R3", "L"}` with `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E", "R3", "L", "R2"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_form25.py tests/test_pipeline.py tests/test_form25_reach_cases.py`
Expected: FAIL (`cannot import name 'letter_hint'`; the reach case SPWRA).

- [ ] **Step 3: Implement**

In `src/delist_detection/form25.py`, replace

```python
class SecurityRef:
    sec_id: str
    share_class: str
    kind: str
    name: str = ""
```

with

```python
class SecurityRef:
    sec_id: str
    share_class: str
    kind: str
    name: str = ""
    # The class letter the security's own CUSIP fails descriptions name ("SUNPOWER CORP CL A"), for a share
    # class without a letter of its own (`letter_hint`); None when they name none, or two.
    letter_hint: str | None = None


_DESCRIPTION_LETTER = re.compile(r"\b(?:CL|CLASS|SER|SERIES)\s+([A-Z])\b")


def letter_hint(descriptions: Iterable[str]) -> str | None:
    """The one class letter a security's own CUSIP fails descriptions name ("CL A", "CLASS A", "SER A"); None
    when they name none, or more than one."""
    letters = {m.group(1) for d in descriptions for m in _DESCRIPTION_LETTER.finditer((d or "").upper())}
    return letters.pop() if len(letters) == 1 else None
```

In `src/delist_detection/form25.py`, replace

```python
        letter = class_letter(label)
        hits = [r for r in same if class_letter(r.share_class) == letter]
```

with

```python
        letter = class_letter(label)
        hits = [r for r in same if class_letter(r.share_class) == letter]
        if not hits:
            # R2: no sibling's class carries the letter; a letterless one whose own CUSIP's fails descriptions
            # name it does (SunPower's "Class A & Class B" 25-NSE, 2011: the class A placeholder, "CL A")
            hits = [r for r in same if class_letter(r.share_class) is None and r.letter_hint == letter]
```

In `src/delist_detection/pipeline.py`, replace

```python
from .figi_resolution import FigiCandidate, is_placeholder, share_class_from_name
```

with

```python
from .figi_resolution import FigiCandidate, class_letter, is_placeholder, share_class_from_name
```

In `src/delist_detection/pipeline.py`, replace

```python
from .form25 import SecurityRef, notice_last_trade, parse_form25
```

with

```python
from .form25 import SecurityRef, letter_hint, notice_last_trade, parse_form25
```

In `src/delist_detection/pipeline.py`, replace

```python
def _rows_near(rows: Sequence[FtdRow], day: str) -> bool:
```

with

```python
def _security_ref(s: Security, ftd: FtdIndex, cusips: Sequence[str]) -> SecurityRef:
    """The finder's view of a security (`form25.SecurityRef`): its class, kind and name, and for a class with no
    letter the one its own CUSIPs' fails descriptions name (`form25.letter_hint`, R2: SunPower's class A placeholder,
    "SUNPOWER CORP CL A")."""
    hint = None if class_letter(s.share_class) else letter_hint(d for c in cusips for d in ftd.descriptions(c))
    return SecurityRef(s.sec_id, s.share_class, s.kind, s.name, hint)


def _rows_near(rows: Sequence[FtdRow], day: str) -> bool:
```

In `src/delist_detection/pipeline.py`, replace

```python
            siblings[s.issuer_cik].append(SecurityRef(s.sec_id, s.share_class, s.kind, s.name))
```

with

```python
            siblings[s.issuer_cik].append(_security_ref(s, ftd, sec_cusips.get(s.sec_id, [])))
```

In `src/delist_detection/pipeline.py`, replace

```python
        sibs = siblings.get(s.issuer_cik) or [SecurityRef(s.sec_id, s.share_class, s.kind, s.name)]
```

with

```python
        sibs = siblings.get(s.issuer_cik) or [_security_ref(s, ftd, sec_cusips.get(s.sec_id, []))]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_form25.py tests/test_pipeline.py tests/test_form25_reach_cases.py`
Expected: PASS (SPWRA moves; LVNTA stays). Then the full suite: 2155 passed, 245 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/form25.py src/delist_detection/pipeline.py tests/test_form25.py tests/test_pipeline.py tests/test_form25_reach_cases.py
git commit -m "A letterless class takes the one letter its own fails descriptions name, where no sibling's class carries it (sub-plan 5b, R2: SPWRA)"
```

---

### Task 12: R5, the one other CIK in force

Tier: standard (a new stage and the finder's filer CIK).

**Files:**
- Modify: `src/delist_detection/delistings.py`, `src/delist_detection/pipeline.py`, `tests/form25_cases.py`
- Test: `tests/test_pipeline.py`, `tests/test_delistings.py`, `tests/test_run_provenance.py`,
  `tests/test_form25_reach_cases.py`

**Interfaces:**
- Consumes: Task 9's `_judge(..., issuer_names)` and `_issuer_names`; Task 7's `_continued(..., filings)`;
  `issuer_in_force.issuer_changes`; Task 8's `own`.
- Produces: `SecurityContext.other_cik: int | None = None`; `DelistingFinder._other_issuer_groups(ctx, scan, floor,
  own)`; the finder's groups carry their filer CIK and filing list, and a delisting from the other CIK has
  `Delisting.cik` (and `record.cik`) = that CIK; `pipeline._in_force_reads(ctx)`, `pipeline._other_issuers(ctx,
  eras, resolutions, issuers, securities) -> dict[str, int]` (stage 4c, metered "other issuers in force", logged
  `other issuer in force: N securities (...)`); `_context_builder(..., other_ciks={})`;
  `_find_delistings(..., other_ciks={})`. tests/form25_cases.py: `context(sec_id, *, other_cik="fixture")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
# --- sub-plan 5b, R5: the one other CIK in force over a security's whole span ---

def _in_force_run(subs, exact):
    """A run context whose EDGAR answers `subs` (CIK -> submissions JSON) and whose resolver's name index lists
    `exact` (name -> CIKs)."""
    from types import SimpleNamespace
    from delist_detection import manifest as run_manifest
    index = SimpleNamespace(split_search=lambda name: ([SimpleNamespace(cik=c) for c in exact.get(name, [])], []))
    clients = SimpleNamespace(edgar=SimpleNamespace(submissions=lambda cik: subs.get(cik)),
                              resolver=SimpleNamespace(name_index=lambda: index))
    return pipeline._RunContext(clients, date(2026, 9, 25), lambda *_: None, 1, run_manifest.StageMeter(lambda *_: None))


def _security_with_era(sec_id, cik, ticker, observations):
    from delist_detection.observations import TickerEra
    from delist_detection.security_master import EraResolution, Issuer
    era = TickerEra(ticker, observations[0].as_of, observations[-1].as_of, observations)
    s = Security(sec_id, cik, "COMMON", observations[-1].name, "Common Stock", True, "cusip", eras=[era])
    return s, era, {era.key: EraResolution(era.key, sec_id, "cusip", None, ())}, {era.key: Issuer(cik, ())}


HRG = {"name": "SPECTRUM BRANDS HOLDINGS, INC.",
       "formerNames": [{"name": "HRG GROUP, INC.", "from": "2014-01-01T00:00:00.000Z", "to": "2018-07-13T00:00:00.000Z"},
                       {"name": "HARBINGER GROUP INC.", "from": "2009-12-14T00:00:00.000Z",
                        "to": "2014-01-01T00:00:00.000Z"}]}
OLD_SPB = {"name": "SB/RH HOLDINGS, LLC",
           "formerNames": [{"name": "SPECTRUM BRANDS HOLDINGS, INC.", "from": "2010-06-16T00:00:00.000Z",
                            "to": "2018-07-13T00:00:00.000Z"}]}


def test_the_one_other_cik_in_force_on_every_sighting_is_read_too():
    """Spectrum Brands 2010-2018: today's CIK 109177 was Harbinger/HRG Group then; the old Spectrum Brands (CIK
    1487730) carried the observed name on every sighting."""
    obs = [Observation("SPB", d, "SPECTRUM BRANDS HOLDINGS INC") for d in ("2010-06-30", "2014-06-30", "2018-06-29")]
    s, era, resolutions, issuers = _security_with_era("BBG000P4BQM9", 109177, "SPB", obs)
    ctx = _in_force_run({109177: HRG, 1487730: OLD_SPB}, {"SPECTRUM BRANDS HOLDINGS INC": [109177, 1487730]})
    assert pipeline._other_issuers(ctx, [era], resolutions, issuers, {s.sec_id: s}) == {"BBG000P4BQM9": 1487730}


def test_an_issuer_that_changed_within_the_span_or_never_changed_gives_no_other_cik():
    """Perrigo: the old Perrigo Company (CIK 820096) until 2013, then Perrigo plc (its own CIK 1585364): two CIKs in
    force, so none is read (reading 820096 would give listed PRGO a 2013 row). A security whose own CIK carried
    the name throughout has none either."""
    plc = {"name": "Perrigo Co plc",
           "formerNames": [{"name": "BLISFIELD LTD", "from": "2012-01-01T00:00:00.000Z",
                            "to": "2013-08-27T00:00:00.000Z"}]}
    obs = [Observation("PRGO", "2012-06-29", "PERRIGO CO"), Observation("PRGO", "2015-06-30", "PERRIGO CO PLC")]
    s, era, resolutions, issuers = _security_with_era("BBG000CNFQW6", 1585364, "PRGO", obs)
    ctx = _in_force_run({1585364: plc, 820096: {"name": "PERRIGO CO", "formerNames": []}},
                        {"PERRIGO CO": [820096, 1585364]})
    assert pipeline._other_issuers(ctx, [era], resolutions, issuers, {s.sec_id: s}) == {}
    s, era, resolutions, issuers = _security_with_era("BBG_PLAIN", 777, "PLN", [Observation("PLN", "2015-06-30",
                                                                                             "PLAIN CO")])
    ctx = _in_force_run({777: {"name": "PLAIN CO"}}, {"PLAIN CO": [777]})
    assert pipeline._other_issuers(ctx, [era], resolutions, issuers, {s.sec_id: s}) == {}
```

Append to `tests/test_delistings.py`:

```python
# --- sub-plan 5b, R5: the other CIK in force ---

def _old_issuers_removal(fake_edgar):
    """Spectrum Brands 2018: NYSE filed the 25-NSE under the old Spectrum Brands (CIK 1487730), the issuer in force
    over the whole span; today's CIK (109177) filed none."""
    fake_edgar.submissions_by_cik[109177] = []
    fake_edgar.submissions_by_cik[1487730] = [
        EdgarSubmission("s8", "8-K", "2018-07-13", "2018-07-13", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("s25", "25-NSE", "2018-07-16", "", "", "p.xml")]
    fake_edgar.raws["s25"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG000P4BQM9", 109177, "SPB", "2010-06-30", "2018-06-29", "SPECTRUM BRANDS HOLDINGS INC")
    return DelistingFinder(fake_edgar, clf), sec


def test_the_other_cik_in_forces_form25_is_read_and_dates_and_classifies_the_delisting(fake_edgar):
    finder, sec = _old_issuers_removal(fake_edgar)
    (ev,), _ = finder.find(replace(_ctx(sec, listed=False, last_seen="2018-07-16"), other_cik=1487730))
    assert (ev.cik, ev.form25_sub.accession, ev.delist_date) == (1487730, "s25", "2018-07-26")
    assert (ev.record.cik, ev.record.bucket) == (1487730, CrspBucket.MERGER)


def test_without_an_other_cik_the_old_issuers_form25_is_never_seen(fake_edgar):
    finder, sec = _old_issuers_removal(fake_edgar)
    events, _ = finder.find(_ctx(sec, listed=False, last_seen="2018-07-16"))
    assert all(e.cik == 109177 and e.form25_sub is None for e in events)
```

Append to `tests/test_delistings.py`:

```python
def test_the_other_cik_in_forces_form25_of_another_class_is_no_delisting(fake_edgar):
    """Review Focus (R5): the old issuer's Form 25s are matched against the security alone, by kind and letter:
    its preferred stock's removal is not the common's."""
    finder, sec = _old_issuers_removal(fake_edgar)
    fake_edgar.raws["s25"] = _f25_raw("New York Stock Exchange LLC", class_text="6.25% Preferred Stock, Series A")
    events, _ = finder.find(replace(_ctx(sec, listed=False, last_seen="2018-07-16"), other_cik=1487730))
    assert all(e.form25_sub is None for e in events)
```

Append to `tests/test_form25_reach_cases.py`:

```python
def test_reading_a_cik_in_force_over_part_of_the_span_would_give_perrigo_a_2013_row():
    """PRGO (binding: no 2013 ending): the old Perrigo Company (CIK 820096) was in force only until 2013, so R5
    reads no other CIK for it; reading that CIK would give the listed PRGO a 2013 row."""
    assert fc.outcome("BBG000CNFQW6") == ([], [])
    assert [r[0] for r in fc.outcome("BBG000CNFQW6", other_cik=820096)[0]] == ["2013-06-15"]
```

In `tests/test_run_provenance.py`, replace

```python
                                "dead before first sighting", "handoff notice dates", "line follow"}
```

with

```python
                                "dead before first sighting", "handoff notice dates", "line follow",
                                "other issuers in force"}
```

In `tests/form25_cases.py`, replace

```python
def context(sec_id: str):
    """The case's `SecurityContext`, as stage 5 builds it (`pipeline._context_builder`)."""
    securities, cusips, ftd = world()
    sightings = {sid: ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    build = pipeline._context_builder(securities, sightings, pipeline._IssuerAnswers({}, {}, {}, set()), ftd, cusips)
    return build(securities[sec_id], DATA["securities"][sec_id]["listed"])
```

with

```python
def context(sec_id: str, *, other_cik: int | None | str = "fixture"):
    """The case's `SecurityContext`, as stage 5 builds it (`pipeline._context_builder`); its other CIK in force
    (R5) is the fixture's (from the committed run's contract/security_history.csv) unless `other_cik` says
    otherwise."""
    securities, cusips, ftd = world()
    sightings = {sid: ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    other = DATA["cases"][sec_id]["other_cik"] if other_cik == "fixture" else other_cik
    build = pipeline._context_builder(securities, sightings, pipeline._IssuerAnswers({}, {}, {}, set()), ftd, cusips,
                                      {sec_id: other} if other else {})
    return build(securities[sec_id], DATA["securities"][sec_id]["listed"])
```

In `tests/test_form25_reach_cases.py`, replace `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E", "R3", "L", "R2"}` with `RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E", "R3", "L", "R2", "R5"}`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_delistings.py tests/test_run_provenance.py tests/test_form25_reach_cases.py`
Expected: FAIL (`no attribute '_other_issuers'`; `unexpected keyword argument 'other_cik'`; the manifest's stage
list; the reach cases SPB and MTCH, and the Perrigo demonstration).

- [ ] **Step 3: The finder reads the other CIK's Form 25s**

In `src/delist_detection/delistings.py`, replace

```python
    cusip_rows_near: Callable[[str], bool] = lambda day: False
```

with

```python
    cusip_rows_near: Callable[[str], bool] = lambda day: False
    # The one CIK other than `security.issuer_cik` that was the issuer in force over the security's whole span
    # (`pipeline._other_issuers`), whose Form 25s are read too (R5: the old Spectrum Brands, the old Match Group).
    other_cik: int | None = None
```

In `src/delist_detection/delistings.py`, replace

```python
            candidates.append((sub, f25))

        delistings: list[Delisting] = []
        last_definitive: Delisting | None = None
        for group in self._group(candidates):
            earliest_sub, earliest_f25 = min(group, key=lambda item: item[0].filing_date)
```

with

```python
            candidates.append((sub, f25))
        groups = [(cik, filings, g) for g in self._group(candidates)]
        if ctx.other_cik is not None and ctx.other_cik != cik:
            groups += self._other_issuer_groups(ctx, scan, floor, own)
        groups.sort(key=lambda x: min(s.filing_date for s, _ in x[2]))

        delistings: list[Delisting] = []
        last_definitive: Delisting | None = None
        for filer, filer_filings, group in groups:
            earliest_sub, earliest_f25 = min(group, key=lambda item: item[0].filing_date)
```

In `src/delist_detection/delistings.py`, replace

```python
            continued = self._continued(ctx, earliest_sub, earliest_f25, filings)
            delisting = self._build_delisting(ctx, cik, filings, group, eff, continued)
```

with

```python
            continued = self._continued(ctx, earliest_sub, earliest_f25, filer_filings)
            delisting = self._build_delisting(ctx, filer, filer_filings, group, eff, continued)
```

In `src/delist_detection/delistings.py`, replace

```python
    def _build_delisting(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
```

with

```python
    def _other_issuer_groups(self, ctx: SecurityContext, scan: _Scan, floor: str, own: SecurityRef
                             ) -> list[tuple[int, list[EdgarSubmission], list[tuple[EdgarSubmission, Form25]]]]:
        """R5: the Form 25s, from the floor on, of the one other CIK in force over the security's whole span
        (`SecurityContext.other_cik`), matched against this security alone, grouped; each group carries its
        filer CIK and filing list, which date and classify it (old Spectrum Brands 2018, old Match Group 2020)."""
        other = ctx.other_cik
        filings = self.edgar.recent_filings(other)
        names = self._issuer_names(other)
        found = []
        for sub in list_form25(filings):
            if sub.filing_date < floor:
                continue
            f25 = self._judge(ctx, scan, other, sub, [own], names)
            if f25 is None:
                continue
            if self._continued(ctx, sub, f25, filings) and self._not_this_removal(ctx, other, filings, sub, f25):
                continue
            found.append((sub, f25))
        return [(other, filings, g) for g in self._group(found)]

    def _build_delisting(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
```

- [ ] **Step 4: Stage 4c, the other CIK in force**

In `src/delist_detection/pipeline.py`, replace

```python
def _context_builder(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
                     answers: _IssuerAnswers, ftd: FtdIndex, sec_cusips: dict[str, list[str]]
                     ) -> Callable[[Security, bool | None], SecurityContext]:
```

with

```python
def _context_builder(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
                     answers: _IssuerAnswers, ftd: FtdIndex, sec_cusips: dict[str, list[str]],
                     other_ciks: Mapping[str, int] = {}) -> Callable[[Security, bool | None], SecurityContext]:
```

In `src/delist_detection/pipeline.py`, replace

```python
            cusip_rows_near=lambda day, rows=rows: _rows_near(rows, day),
        )
```

with

```python
            cusip_rows_near=lambda day, rows=rows: _rows_near(rows, day),
            other_cik=other_ciks.get(s.sec_id),
        )
```

In `src/delist_detection/pipeline.py`, replace

```python
def _find_delistings(ctx: _RunContext, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
                     ftd: FtdIndex, answers: _IssuerAnswers, moved_on: Collection[str] = ()) -> _DelistingSearch:
    """5. Every delisting of every security (`DelistingFinder`), in sec_id order.
    A security whose search fails becomes an `error` review item, not an aborted
    run; only a fatal exception (`fatal.FATAL`) stops it. A FIGI line another
    composite continues (`moved_on`: stage 4b's line successors) is not listed
    today: its line went on under that composite."""
```

with

```python
def _find_delistings(ctx: _RunContext, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
                     ftd: FtdIndex, answers: _IssuerAnswers, moved_on: Collection[str] = (),
                     other_ciks: Mapping[str, int] = {}) -> _DelistingSearch:
    """5. Every delisting of every security (`DelistingFinder`), in sec_id order.
    A security whose search fails becomes an `error` review item, not an aborted
    run; only a fatal exception (`fatal.FATAL`) stops it. A FIGI line another
    composite continues (`moved_on`: stage 4b's line successors) is not listed
    today: its line went on under that composite. `other_ciks` (stage 4c, R5): the
    other CIK in force over a security's whole span, whose Form 25s are read too."""
```

In `src/delist_detection/pipeline.py`, replace

```python
    security_context = _context_builder(securities, sightings, answers, ftd, sec_cusips)
```

with

```python
    security_context = _context_builder(securities, sightings, answers, ftd, sec_cusips, other_ciks)
```

In `src/delist_detection/pipeline.py`, replace

```python
def _issuers_in_force(ctx: _RunContext, observation_map: Sequence[Mapping[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Each security's issuer timeline (issuer_in_force.issuer_changes) from its
    sightings: every observation_map row with a sec_id, except a conflict (two
    names that day). A submissions read that fails keeps the era's CIK; a refusal
    (`fatal.FATAL`) stops the run. Without a name index (a test double's
    resolver), every sighting keeps its era's CIK."""
    edgar, memo = ctx.clients.edgar, {}
```

with

```python
def _in_force_reads(ctx: _RunContext) -> tuple[Callable[[int], Any], Callable[[str], list[int]]]:
    """The two EDGAR reads `issuer_in_force` takes: a CIK's submissions (memoized; a read that fails is None, a
    refusal (`fatal.FATAL`) stops the run) and the CIKs SEC's name index lists under exactly a name (none without
    an index: a test double's resolver)."""
    edgar, memo = ctx.clients.edgar, {}
```

In `src/delist_detection/pipeline.py`, replace

```python
    def exact_names(name: str) -> list[int]:
        return [h.cik for h in index.split_search(name)[0]] if index is not None else []

    mark = ctx.meter.start()
    out = issuer_changes((IssuerSighting(r["sec_id"], r["as_of"], r["name"], r["issuer_cik"])
```

with

```python
    def exact_names(name: str) -> list[int]:
        return [h.cik for h in index.split_search(name)[0]] if index is not None else []

    return submissions, exact_names


def _other_issuers(ctx: _RunContext, eras: list[TickerEra], resolutions: dict[str, EraResolution],
                   issuers: dict[str, Issuer], securities: dict[str, Security]) -> dict[str, int]:
    """4c. R5: each security whose issuer in force (`issuer_in_force.issuer_changes`, over its eras' observations
    with their era's CIK, a (ticker, day) seen under two names left out, as stage 10g reads them) was one CIK
    other than its own issuer CIK on every sighting: that CIK, whose Form 25s the finder reads too. Spectrum
    Brands 2010-2018 was the old Spectrum Brands (CIK 1487730) while today's CIK 109177 holds the security. A
    security whose issuer changed in its span has none (Perrigo: CIK 820096 until 2013, then its own)."""
    submissions, exact_names = _in_force_reads(ctx)
    conflicts = {(t, d) for t, d, _ in observation_conflicts(o for e in eras for o in e.observations)}
    sightings = [IssuerSighting(r.sec_id, o.as_of, o.name or "", str(cik_of(issuers, e.key) or ""))
                 for e in eras if (r := resolutions.get(e.key)) is not None and r.sec_id
                 for o in e.observations if (o.ticker, o.as_of) not in conflicts]
    mark = ctx.meter.start()
    out: dict[str, int] = {}
    for sid, timeline in issuer_changes(sightings, submissions, exact_names).items():
        s = securities.get(sid)
        if s is not None and s.issuer_cik is not None and len(timeline) == 1 and timeline[0][1] != str(s.issuer_cik):
            out[sid] = int(timeline[0][1])
    ctx.log(f"other issuer in force: {len(out)} securities ({', '.join(sorted(out)[:5])}"
            f"{', ...' if len(out) > 5 else ''})")
    ctx.meter.done("other issuers in force", mark)
    return out


def _issuers_in_force(ctx: _RunContext, observation_map: Sequence[Mapping[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Each security's issuer timeline (issuer_in_force.issuer_changes) from its
    sightings: every observation_map row with a sec_id, except a conflict (two
    names that day). A submissions read that fails keeps the era's CIK; a refusal
    (`fatal.FATAL`) stops the run. Without a name index (a test double's
    resolver), every sighting keeps its era's CIK."""
    submissions, exact_names = _in_force_reads(ctx)
    mark = ctx.meter.start()
    out = issuer_changes((IssuerSighting(r["sec_id"], r["as_of"], r["name"], r["issuer_cik"])
```

In `src/delist_detection/pipeline.py`, replace

```python
    search = _find_delistings(ctx, securities, sec_cusips, ftd, answers, set(lines.successors))      # 5
```

with

```python
    other_ciks = _other_issuers(ctx, eras, resolutions, answers.issuers, securities)                # 4c
    search = _find_delistings(ctx, securities, sec_cusips, ftd, answers, set(lines.successors),
                              other_ciks)                                                           # 5
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_delistings.py tests/test_run_provenance.py tests/test_form25_reach_cases.py`
Expected: PASS (SPB and MTCH move; PRGO stays). Then the full suite: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: 2161 passed, 245 xfailed.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/delistings.py src/delist_detection/pipeline.py tests/form25_cases.py tests/test_pipeline.py tests/test_delistings.py tests/test_run_provenance.py tests/test_form25_reach_cases.py
git commit -m "The one other CIK in force over a security's whole span has its Form 25s read (sub-plan 5b, R5: SPB, MTCH)"
```

---

### Task 13: Docs

Tier: cheap.

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none.

- [ ] **Step 1: Commands**

In `CLAUDE.md`'s Commands block, after the line starting `python scripts/build_line_fixtures.py`, add:

```bash
python scripts/build_form25_fixtures.py  # offline: tests/fixtures/form25_reach/ (sub-plan 5b's real Form 25 cases) from the local caches; rerun only to add a case
```

Run `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest` and in the line
`pytest   # full suite (2052 passed, 246 xfailed: 10 known-wrong golden + ...` put the passed and xfailed counts it
prints, and the number of known-wrong golden cases `grep -c ',known_wrong,' data/golden_lifecycles.csv` gives.

- [ ] **Step 2: The stage list**

Replace

```
successor for stage 9; metered as "line follow"), `_find_delistings`,
```

with

```
successor for stage 9; metered as "line follow"), `_other_issuers` (stage 4c: the one CIK other than a
security's own that was its issuer in force on every sighting, `issuer_in_force.issuer_changes`; stage 5 reads its
Form 25s too; metered as "other issuers in force"), `_find_delistings`,
```

- [ ] **Step 3: The module entries**

Append one sentence to each named bullet:

- `ftd.py`: "`trades_after` (sub-plan 5b): whether a security's own CUSIPs, under any symbol it trades under
  (`is_trading_symbol`: no deleted, unassigned or digit-bearing symbol), have at least 20 fails rows over at least
  20 days at two or more prices after a day; the finder's test of whether it went on after a Form 25."
- `form25.py`: "Sub-plan 5b: `is_involuntary` (a removal under rule 12d2-2(b)); `Form25.solely` and `other_class`
  (R3: a Form 25 that relates solely to a non-common class, or whose lettered tracking-stock segments name no word
  of the security's name, is not its own); `notice_says_acquired` (R6b: the EX-99.25 notice says acquired or paid
  in cash, and nothing of a reclassification, a holding company or a reorganization); `SecurityRef.letter_hint`
  and `letter_hint` (R2: a letterless class takes the one letter its own CUSIP's fails descriptions name, only for
  a letter no sibling's class carries)."
- `delistings.py`: "Sub-plan 5b: `_continued` (listed today; the issuer's own Form 25 with its 8-A12B within
  `EIGHT_A_DAYS`, 10, R7; or, not under (b), `SecurityContext.trades_after`; an observation alone never continues a
  security), `_judge` (one Form 25 against the security), early reach (Form 25s up to `EARLY_REACH_DAYS`, 365,
  before the floor, for a security gone today, the latest early group, flagged `observed_after_delisting`), late
  reach (`SecurityContext.cusip_rows_near`, `LATE_ROW_DAYS` 30), and the other CIK in force
  (`SecurityContext.other_cik`, R5; the delisting carries the filer CIK). An `unknown` row of a continued group
  with the issuer's 8-A12B becomes 304 with the security as its own successor."
- `classifier.py`: "Sub-plan 5b: a revocation filed after a matched Form 25 the security did not trade past never
  decides its row (R6a); the continued-filings default (`continued_filings`) gives way to that Form 25's path when
  its notice says the class was acquired (R6b, `_classify_filings`; any answer but a merger is 231,
  `evidence["end_of_era"] == "form25_notice"`); `_confirms_bankruptcy` reads every Item 1.03 section
  (`evidence.item_sections`)."

In the `end_of_era.py` bullet, replace

```
  successor stage 9 finds; (3) a change in control (8-K 5.01) → merger; (4) a
  completed acquisition (8-K 2.01) with a merger filing or a Form 25 → merger;
```

with

```
  successor stage 9 finds; (3) a change in control (8-K 5.01) → merger; (4) a
  completed acquisition (8-K 2.01) with a merger filing or a Form 25 → merger,
  unless a bankruptcy 8-K the classifier confirmed (`bankruptcy_filing`) came on
  or before it → liquidation 470 (5g sub-rule 2, built in sub-plan 5b);
```

- [ ] **Step 4: The invariant**

In "Non-obvious invariants", after the bullet that starts `- **A delisting is a Form 25 removal`, add:

```markdown
- **A Form 25 is reached, matched and owns its row (sub-plan 5b).** A security goes on after a Form 25 only when it
  is listed today, when the issuer moved the class itself (its own Form 25 with an 8-A12B within 10 days), or, for
  a Form 25 not under rule 12d2-2(b), when its own CUSIPs keep trading (`ftd.trades_after`): never on an
  observation alone (a stale snapshot), never on the OTC tail after a removal under (b). A security gone today also
  takes the latest Form 25 group of the year before its first sighting, and a Form 25 after its alive window when
  its own CUSIP traded within 30 days before it; the one other CIK in force over its whole span is searched too. A
  Form 25 solely about rights or about another tracking group is not the common's. The matched Form 25's notice
  outranks the continued-filings default when it says the class was acquired, and a later SEC revocation never
  decides its row.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: the Form 25 reach, matching and ownership rules (sub-plan 5b) in CLAUDE.md"
```

---

### Task 14: The whole-branch review, one fix wave and the offline replay (controller)

Run by the controller. The review runs on model `opus`; fixes on `sonnet`, test first. Nothing here touches the
network or `output/`. **BASE** is `cc631e1`.

**Files:**
- Create: `$TMPDIR/replay_5b.py`, `$TMPDIR/base5b/` (the base commit's `src`), `$TMPDIR/replay_5b_*.jsonl` (none
  committed).
- Modify: only what a finding's fix needs.

- [ ] **Step 1: The review**

Dispatch one reviewer (model `opus`) over `git diff cc631e1..HEAD -- src tests scripts CLAUDE.md`, with this plan,
the spec's section 3 "5b" and the research note. Ask for defects only, each with the file, the line and an input
that breaks it, and in particular: the five Review Focus items; whether any code path still continues a security
on an observation (`seen_after` may remain only for the `IGNORE_AFTER_DEFINITIVE_DAYS` gate); whether a filing E
refuses can still reach the fallback (Ruling 5); whether R5's filer CIK reaches every reader of `Delisting.cik`
(payouts, successors, handoffs, the contract); whether the prefetch pass (`_warm_delisting_search`) builds the same
contexts as the sequential pass.

- [ ] **Step 2: The offline replay over the real caches**

Write `$TMPDIR/replay_5b.py`:

```python
"""Offline replay of stage 5 (the delisting search) over every security of the committed run (sub-plan 5b's
review check). Read-only: every network request is refused and every cache write is a no-op.

  python replay_5b.py rows OUT.pkl                    # once: the run's fails rows from cache/sec_data/ftd
  PYTHONPATH=<src> python replay_5b.py run ROWS.pkl OUT.jsonl   # stage 5 with that source tree
  python replay_5b.py diff BASE.jsonl NEW.jsonl       # the securities whose delistings changed

Run from the repo root. Securities, eras, CUSIPs and listed-today come from output/ (an open ticker_history range
means listed today); the other CIK in force (R5) from output/contract/security_history.csv; EDGAR, MIDAS and the
Nasdaq halt feed from cache/. Contexts are built by the source tree's own `pipeline._context_builder`. Line
tickers (stage 4b's, not stored) are approximated: ticker_history tickers from fails rows the security was never
observed under, not OTC-like, running past its last observation."""
from __future__ import annotations

import csv
import inspect
import io
import json
import os
import pickle
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / "output"
os.environ.setdefault("EDGAR_USER_AGENT", "offline replay replay@example.com")
FTD_FROM = "2007-12-17"          # the committed run's fails window at stage 5
AS_OF = date(2026, 9, 25)
OTC = re.compile(r"^[A-Z]{4}[QFEY]$|ZZZZ$|XXXX$")


def rows_csv(name):
    with open(OUT / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_rows(dest: str) -> None:
    from multiprocessing import Pool
    files = sorted((ROOT / "cache/sec_data/ftd").glob("cnsfails*.zip")) + \
        sorted((ROOT / "cache/sec_data/ftd").glob("cnsp_sec_fails_*.zip"))
    with Pool(8) as pool:
        parts = pool.map(_zip_rows, files, chunksize=4)
    rows = sorted({r for part in parts for r in part})
    Path(dest).write_bytes(pickle.dumps(rows))
    print("fails rows", len(rows))


def _zip_rows(path):
    from delist_detection.ftd import parse_ftd_lines
    cusips = {r["cusip"].upper() for r in rows_csv("cusip_history.csv")}
    out = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.is_dir():
                with z.open(info) as fh:
                    for r in parse_ftd_lines(io.TextIOWrapper(fh, encoding="latin-1"), cusips=cusips):
                        out.append((r.date, r.cusip, r.symbol, r.description, r.price))
    return out


def offline():
    """The run's clients over cache/, every request refused and every cache write a no-op."""
    import requests
    import delist_detection.atomic_io as aio

    def no_write(*a, **k):
        return None
    aio.write_atomic = aio.clean_orphan_temps = no_write
    for mod in ("edgar", "sec_http", "midas", "nasdaq_halts", "openfigi", "ticker_resolver", "cik_lookup", "ftd"):
        m = __import__(f"delist_detection.{mod}", fromlist=["x"])
        for name in ("write_atomic", "clean_orphan_temps"):
            if hasattr(m, name):
                setattr(m, name, no_write)

    class Refuse:
        def get(self, url, *a, **k):
            raise requests.ConnectionError(f"offline: {url}")
        post = get

        def mount(self, *a, **k):
            pass
    import delist_detection.sec_limiter as lim
    lim.throttle = lambda *a, **k: None
    from delist_detection.classifier import DelistClassifier
    from delist_detection.edgar import EdgarClient
    from delist_detection.midas import MidasClient
    from delist_detection.nasdaq_halts import NasdaqHaltClient
    from delist_detection.ticker_resolver import TickerResolver
    cache = ROOT / "cache"
    e = EdgarClient(cache_dir=cache / "edgar", session=Refuse(), sleep=lambda s: None, today=AS_OF)
    res = TickerResolver(e, cache_path=Path(os.environ.get("TMPDIR", "/tmp")) / "replay_5b_resolver.json", today=AS_OF)
    return (e, DelistClassifier(e, res, today=AS_OF), MidasClient(cache / "sec_data/midas", session=Refuse()),
            NasdaqHaltClient(cache / "nasdaq_halts", session=Refuse(), sleep=lambda s: None, today=AS_OF))


def world(rows_pkl: str):
    from delist_detection.figi_resolution import security_kind
    from delist_detection.ftd import FtdIndex, FtdRow
    from delist_detection.observations import Observation, TickerEra
    from delist_detection.security_master import Security
    obs = defaultdict(lambda: defaultdict(list))
    for r in rows_csv("observation_map.csv"):
        if r["sec_id"]:
            obs[r["sec_id"]][r["era"]].append(Observation(r["ticker"], r["as_of"], r["name"] or None,
                                                          r["cusip"] or None, int(r["pin_cik"]) if r["pin_cik"] else None))
    cusips = defaultdict(list)
    for r in rows_csv("cusip_history.csv"):
        if r["cusip"] not in cusips[r["sec_id"]]:
            cusips[r["sec_id"]].append(r["cusip"])
    th = defaultdict(list)
    for r in rows_csv("ticker_history.csv"):
        th[r["sec_id"]].append(r)
    secs, listed = {}, {}
    for r in rows_csv("securities.csv"):
        sid = r["sec_id"]
        eras = []
        for key, os_ in sorted(obs.get(sid, {}).items(), key=lambda kv: min(o.as_of for o in kv[1])):
            os_ = sorted(os_, key=lambda o: o.as_of)
            eras.append(TickerEra(key.split("@")[0], os_[0].as_of, os_[-1].as_of, os_,
                                  seq=int(key.split("#")[1]) if "#" in key else 0))
        s = Security(sid, int(r["issuer_cik"]) if r["issuer_cik"] else None, r["share_class"], r["name"],
                     r["security_type"], r["observed"] == "true", r["figi_source"],
                     kind=security_kind(r["security_type"], r["name"]), eras=eras)
        if eras:
            seen, last = {e.ticker for e in eras}, max(e.last for e in eras)
            s.line_tickers = frozenset(x["ticker"] for x in th.get(sid, []) if x["ticker"] not in seen
                                       and x["source"] == "ftd" and not OTC.search(x["ticker"])
                                       and (x["valid_to"] == "" or x["valid_to"] > last))
        secs[sid] = s
        listed[sid] = any(x["valid_to"] == "" for x in th.get(sid, []))
    ftd = FtdIndex(FtdRow(*t) for t in pickle.loads(Path(rows_pkl).read_bytes()) if t[0] >= FTD_FROM)
    inforce = defaultdict(set)
    for r in rows_csv("contract/security_history.csv"):
        if r["issuer_id"]:
            inforce[r["sec_id"]].add(r["issuer_id"])
    others = {sid: int(next(iter(ids))) for sid, ids in inforce.items()
              if sid in secs and secs[sid].issuer_cik and len(ids) == 1 and next(iter(ids)) != str(secs[sid].issuer_cik)}
    return secs, dict(cusips), listed, ftd, others


def run(rows_pkl: str, dest: str) -> None:
    from delist_detection import pipeline as P
    from delist_detection.delistings import DelistingFinder
    from delist_detection.history import ticker_sightings
    edgar, classifier, midas, halts = offline()
    secs, cusips, listed, ftd, others = world(rows_pkl)
    sightings = {sid: ticker_sightings(s, ftd, cusips.get(sid, [])) for sid, s in secs.items()}
    args = [secs, sightings, P._IssuerAnswers({}, {}, {}, set()), ftd, defaultdict(list, cusips)]
    if "other_ciks" in inspect.signature(P._context_builder).parameters:
        args.append(others)
    build = P._context_builder(*args)
    finder = DelistingFinder(edgar, classifier, midas=midas, halts=halts)
    with open(dest, "w") as fh:
        for sid in sorted(secs):
            s = secs[sid]
            if not s.eras:
                continue
            try:
                found, review = finder.find(build(s, listed[sid]))
            except Exception as exc:  # noqa: BLE001
                fh.write(json.dumps({"sid": sid, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
                continue
            fh.write(json.dumps({"sid": sid, "delistings": [
                {"date": d.delist_date, "bucket": d.record.bucket.value, "code": d.record.crsp_code,
                 "lt": d.last_trade.day.isoformat() if d.last_trade.day else "", "self": d.record.successor_sec_id == sid,
                 "f25": d.form25_sub.accession if d.form25_sub else "", "cik": d.cik, "reason": d.record.reason[:90]}
                for d in found], "review": sorted({x.flag for x in review})}) + "\n")
    print("replayed", len(secs), "securities ->", dest)


# the securities the plan's prototype changed (22 in the truth set, 20 outside it)
EXPECTED = {
    "BBG000BBG3P1", "BBG000BF2JS9", "BBG000BGZ9V9", "BBG000BLY636", "BBG000BP62Y3", "BBG000BPTDN6", "BBG000BRF6B5",
    "BBG000BRWGG9", "BBG000BVW841", "BBG000C070N2", "BBG000DGZ1B6", "BBG000JXRXK2", "BBG000P4BQM9", "BBG000PSSG77",
    "BBG005CPNTQ2", "BBG005DKMJ67", "BBG009R0CVG1", "BBG00B6WH9G3", "CIK1355096-SERIES-A", "CIK351346-COMMON",
    "CIK867773-COMMON", "CIK898660-COMMON",
    "BBG000BHRRV6", "BBG000BLDXH5", "BBG000BLG1L7", "BBG000BMLYZ2", "BBG000BNY0W3", "BBG000BRMVZ6", "BBG000BSYVD5",
    "BBG000BVK2W6", "BBG000C0ZL64", "BBG000C1TTV4", "BBG000C4ZNF2", "BBG000CHWP52", "BBG000CNNMD7", "BBG000G8M3Q5",
    "BBG000K1T0M8", "BBG000K1X873", "BBG000R3BYX0", "BBG000RFD341", "BBG0016WLQ18", "BBG0057K5Y79",
}


def diff(base: str, new: str) -> None:
    truth = {r["sec_id"] for r in csv.DictReader(open(ROOT / "data/diagnosis_truth.csv"))}
    a = {x["sid"]: x for x in map(json.loads, open(base))}
    b = {x["sid"]: x for x in map(json.loads, open(new))}
    key = lambda x: [(d["date"], d["bucket"], d["code"], d["lt"], d["self"], d["f25"]) for d in x.get("delistings", [])]
    changed = {sid for sid in a if key(a[sid]) != key(b.get(sid, {}))}
    errors = Counter("error" in x for x in b.values())
    print(f"changed {len(changed)}: {len(changed & truth)} in the truth set, {len(changed - truth)} outside; "
          f"replay errors base {sum('error' in x for x in a.values())}, new {errors[True]}")
    for sid in sorted(changed):
        tag = "" if sid in EXPECTED else "  << NOT EXPECTED"
        print(("T " if sid in truth else "  ") + sid + tag)
        print("   base:", key(a[sid]))
        print("   new :", key(b.get(sid, {})))
    print("expected but unchanged:", sorted(EXPECTED - changed) or "none")
    print("changed but not expected:", sorted(changed - EXPECTED) or "none")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    {"rows": build_rows, "run": run, "diff": diff}[cmd](*rest)
```

Then, from the repo root (about 3 minutes for the rows, 2 for each replay):

```bash
mkdir -p $TMPDIR/base5b && git archive cc631e1 src | tar -x -C $TMPDIR/base5b
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/replay_5b.py rows $TMPDIR/replay_5b_rows.pkl
PYTHONPATH=$TMPDIR/base5b/src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/replay_5b.py run $TMPDIR/replay_5b_rows.pkl $TMPDIR/replay_5b_base.jsonl
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/replay_5b.py run $TMPDIR/replay_5b_rows.pkl $TMPDIR/replay_5b_new.jsonl
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/replay_5b.py diff $TMPDIR/replay_5b_base.jsonl $TMPDIR/replay_5b_new.jsonl
```

Expected: `fails rows 3588360`, then `changed 42: 22 in the truth set, 20 outside; replay errors base 0, new 0`,
`expected but unchanged: none` and `changed but not expected: none` (the planning prototype's result). Any other
security in either list is a defect, or a change of the local cache since planning: read its rows before the fix
wave.

- [ ] **Step 3: One fix wave**

Each finding of Steps 1 and 2 that the controller accepts becomes one fix (sonnet): a failing test first (on
`FakeEdgar`, the doubles, or a new case in `tests/fixtures/form25_reach/` by adding it to the builder's `CASES` and
rebuilding), then the fix, then the full suite green. Rerun Step 2 after the wave; its result must be the expected
one, or each difference explained in the commit message. Record the findings that were not fixed, and why, for
Task 17's report.

- [ ] **Step 4: Commit**

```bash
git add -A src tests scripts CLAUDE.md
git commit -m "Sub-plan 5b: the whole-branch review's fixes"
```

(Skip when the wave changed nothing.)

---

### Task 15: The full network run (controller)

Run by the controller, not an implementer. **BASE** below is `cc631e1`, the commit 5b started from: its `output/`
is the run before 5b (no earlier task changes `output/`).

**Files:**
- Modify (by the run): `output/` (the nine tables, `output/contract/`, `scorecard.json`, `run_manifest.json`,
  `run.log`).
- Create: `output/diagnose_unknown_report/loop/5b/scorecard_before.txt`, `.../loop/5b/cases_before.md`;
  `$TMPDIR/cases_5b.py`, `$TMPDIR/base_securities_5b.csv` (not committed).

- [ ] **Step 1: Record the numbers before**

Write `$TMPDIR/cases_5b.py` (Task 17 runs it again for "after"):

```python
"""The truth cases 5b moves (the case map's 5b rows, and the other truth cases its rules move): each one's status
and its mismatches against the run under output/, as markdown table rows. Run from the repo root."""
import csv
from pathlib import Path

from delist_detection.diagnosis_truth import LibraryRows, judge_case, load_diagnosis_truth
from delist_detection.lifecycle import Tables

ROOT = Path.cwd()
CASE_MAP = ROOT / "docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes/case_map.csv"
ids = {r["case_id"] for r in csv.DictReader(CASE_MAP.open()) if r["sub_plan"] == "5b"}
OTHER = {"BBG000BF2JS9", "BBG000BLY636", "BBG000BBG3P1", "BBG000BRWGG9", "BBG000BP62Y3", "BBG000BGZ9V9",
         "BBG005DKMJ67", "BBG00B6WH9G3", "BBG0038K9G41"}      # CNB, IMB, TMA, RAD, MNI, ASNA, LTRPA, MTCH, LVNTA
cases = load_diagnosis_truth(ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_legs.csv")
lib = LibraryRows.of(Tables.read(ROOT / "output"))
print("| ticker | case | status | fixed_by | mismatches | which |")
print("| --- | --- | --- | --- | --- | --- |")
for c in sorted((c for c in cases if c.case_id in ids or c.sec_id in OTHER), key=lambda c: (c.ticker, c.case_id)):
    j = judge_case(c, lib)
    print(f"| {c.ticker} | {c.case_id} | {c.status} | {c.fixed_by} | {len(j.mismatches)} | "
          f"{'; '.join(str(m) for m in j.mismatches)} |")
```

Then, before the run changes `output/`:

```bash
mkdir -p output/diagnose_unknown_report/loop/5b
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py > output/diagnose_unknown_report/loop/5b/scorecard_before.txt
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/cases_5b.py > output/diagnose_unknown_report/loop/5b/cases_before.md
git show cc631e1:output/securities.csv > $TMPDIR/base_securities_5b.csv
```

Expected: exit 0 each; the metric lines include `D.mismatches 646`; the cases table has 59 rows (the case map's 50
5b rows and the 9 other truth cases 5b's rules move).

- [ ] **Step 2: Make sure no other SEC client runs**

Ask the operator whether a terminal run is going (it uses another lock file), and check
`ps aux | grep -c classify_universe` shows none but the grep. Do not start while one runs.

- [ ] **Step 3: Run**

With Bash `run_in_background: true`, `timeout: 7200000` and `allowed_domains`: `data.sec.gov`, `www.sec.gov`,
`efts.sec.gov`, `api.openfigi.com`, `api.nasdaq.com`, `www.nasdaqtrader.com`, `api.openai.com`:

```bash
DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations data/observations.csv --extract-merger-terms-llm --as-of 2026-09-25 --sec-workers 4 --id-baseline $TMPDIR/base_securities_5b.csv > output/run.log 2>&1
```

Expected: this run is not warm. It fetches about 303 early-window Form 25 raws, the two other CIKs' filing lists
and raws, a few 8-K texts and Nasdaq halt days, and, for about 20 new mergers (TXU, STN, BMET, MWW, NTY, XMSR, SOV,
MER, PSD, SIE, TRB, LYO, HET, SKYF, UB, BKC, NWA, LGFA, DISCA, SPB, MTCH), filing texts and LLM calls. Every rerun
of this task passes the same `--id-baseline`.

- [ ] **Step 4: Check the run before trusting it**

- The tool output has no `<sandbox_violations>` block. A denied host means some answers rested on failures (a
  blocked api.openai.com fails silently: the LLM terms are missing): add the host and rerun.
- The exit code is 0, or 3 with only `resolution_degraded` rows the banner names (then rerun once SEC answers; a
  run is accepted only with no `error` or `resolution_degraded` row in `output/review.csv`).
- `grep -n "other issuer in force:" output/run.log` prints
  `other issuer in force: 2 securities (BBG000P4BQM9, BBG00B6WH9G3)`. Another count means stage 4c reads the
  observations differently from stage 10g: stop and compare with `output/contract/security_history.csv`.
- `grep -c "OpenFIGI unavailable" output/run.log` is 0.

- [ ] **Step 5: The numbers after**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py`
Expected: `D.mismatches` below 646. Note any `DROP`, `GOLDEN FAILING` and `DIAGNOSIS FAILING` line for Task 17
(LVNTA, a `pass` truth case, must not fail).

- [ ] **Step 6: Commit the run**

```bash
git add output
git commit -m "Sub-plan 5b: full run with the Form 25 reach, matching and ownership rules (before the truth loop)"
```

---

### Task 16: The truth loop (controller)

Run by the controller. At most 3 rounds, at most 5 agents at a time (the workflow enforces both).

**Files:**
- Modify (by the loop and the controller): `data/diagnosis_truth.csv`, `data/diagnosis_truth_changes.csv`,
  `output/diagnose_unknown_report/loop/diagnosed.csv`, `output/regression_report.csv`.
- Create (by the loop): `output/diagnose_unknown_report/loop/5b/round-<N>/{cases.csv,reports/,records/,summary.md}`;
  `$TMPDIR/regression_kinds_5b.py`, `$TMPDIR/preruling_5b.py` (not committed).

- [ ] **Step 1: Read round 1's regressions by kind before spending agents**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/truth_loop_round.py --label 5b --base cc631e1 --round 1`
Expected: one JSON line with `renamed`, `mismatches_new`, `regressions_new` and the cases.

Write `$TMPDIR/regression_kinds_5b.py`:

```python
"""Round 1's regression report (output/regression_report.csv) by security: what changed, and whether the plan's
offline replay expected the security to move. Run from the repo root after scripts/truth_loop_round.py."""
import csv
from collections import defaultdict
from pathlib import Path

EXPECTED = {
    "BBG000BNY0W3": "MER 2009 merger (C; the 2008 transfer stays)",
    "BBG000BRMVZ6": "PSD 2009 merger (C)", "BBG000BSYVD5": "SIE 2008 merger (C)",
    "BBG000BVK2W6": "TRB 2007 merger (C)", "BBG000C0ZL64": "LYO 2007 merger (C)",
    "BBG000C1TTV4": "HET 2008 merger (C)", "BBG000G8M3Q5": "UB 2008 merger (C)",
    "BBG000R3BYX0": "BKC 2010 merger (C)", "BBG000RFD341": "NWA 2008 merger (C)",
    "BBG000CHWP52": "DISCA 2022 merger (C; pre-ruled, Task 16)",
    "BBG000CNNMD7": "SKYF 2007 merger (E)",
    "BBG000BHRRV6": "EK 2012 removal under (b) (C; G4 reading)",
    "BBG000C4ZNF2": "ABK 2010 removal under (b) (C; G4 reading)",
    "BBG000BMLYZ2": "KWK 2015 removal under (b) (C; G4 reading)",
    "BBG000BLDXH5": "MDRX 2024 removal under (b) (C; G4 reading)",
    "BBG0057K5Y79": "EPE 2019 removal under (b), moved from the bankruptcy (C; G4 reading)",
    "BBG000K1X873": "SSCC 2009 re-dated to its Form 25 (C)",
    "BBG0016WLQ18": "GNC 2020 580 to 470 (the Item 1.03 sections)",
    "BBG000K1T0M8": "LGFA 2025 merger (R2)",
    "BBG000BLG1L7": "EQC 2025 transfer without a successor (pre-ruled, Task 16)",
}
POSSIBLE = {"BBG000BV52H0": "KSE (E on an uncached early raw)", "CIK230463-COMMON": "PPP (E on an uncached early raw)",
            "CIK835541-COMMON": "SLR (E on an uncached early raw)"}
rows = list(csv.DictReader(open(Path.cwd() / "output/regression_report.csv", newline="", encoding="utf-8")))
by = defaultdict(list)
for r in rows:
    by[r["sec_id"]].append(r)
unexpected = []
for sid in sorted(by):
    tag = ("expected: " + EXPECTED[sid] if sid in EXPECTED else
           "possible: " + POSSIBLE[sid] if sid in POSSIBLE else "UNEXPECTED")
    if tag == "UNEXPECTED":
        unexpected.append(sid)
    print(f"{sid}  {tag}")
    for r in by[sid]:
        print(f"    {r['table']}.{r['field'] or '(row)'} {r['kind']}: {r['old'][:80]!r} -> {r['new'][:80]!r}")
missing = sorted(set(EXPECTED) - set(by))
print(f"\n{len(by)} securities regressed: {len(by) - len(unexpected)} expected or possible, "
      f"{len(unexpected)} UNEXPECTED {unexpected}; expected but absent: {missing}")
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/regression_kinds_5b.py`
Expected: every regressed security is `expected` or `possible`; each has its contract row (a new or moved ending,
its value fields) and its security_history ranges (clipped at the new ending; for an E ending, the CUSIPs stage 5b
backfills before the first observation). An `UNEXPECTED` security, or an expected one whose change is of another
kind than its tag says, is a bug: write its failing test, fix it as a new task (test first, sonnet), rerun Task
15 (its `--id-baseline` too), move `loop/5b/round-1` aside and redo this step. That happened twice in 5a.

- [ ] **Step 2: The operator's pre-rulings (DISCA 2022, EQC 2025)**

Write `$TMPDIR/preruling_5b.py`:

```python
"""The operator's pre-rulings of 2026-10-04 for sub-plan 5b: DISCA 2022 and EQC 2025 enter the truth file as
known_wrong rows (with change-log rows), and their mismatches against the run go to the ledger as `known` (label
5b-preruling), so the loop's agents do not diagnose them. Run from the repo root after round 1's script and before
the workflow; --dry-run prints the rows only.

- DISCA (BBG000CHWP52): fixed_by 5c; the truth is a continuation into WBD (BBG011386VF4), mirroring DISCK's row.
- EQC (BBG000BLG1L7): fixed_by 5g; exit_kind liquidation, every other scored field `*`."""
import argparse
import csv
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection.diagnosis_truth import COLUMNS, SCORED, LibraryRows, judge_all, load_legs, parse_rows
from delist_detection.lifecycle import Tables

ROOT = Path.cwd()
DOC = "docs/superpowers/plans/research/2026-10-04-5b-form25-reach.md"
REASON = "operator pre-ruling 2026-10-04 (5b plan): {}"
p = argparse.ArgumentParser()
p.add_argument("--dry-run", action="store_true")
args = p.parse_args()


def last_ending(sec_id: str) -> dict[str, str]:
    rows = [r for r in csv.DictReader(open(ROOT / "output/delistings.csv", newline="", encoding="utf-8"))
            if r["sec_id"] == sec_id and r["successor_sec_id"] != sec_id]
    if not rows:
        raise SystemExit(f"{sec_id} has no ending in output/delistings.csv: run Task 15 first")
    return max(rows, key=lambda r: r["delist_date"])


def row(sec_id, ticker, fixed_by, note, fields, internal):
    end = last_ending(sec_id)
    r = {c: "" for c in COLUMNS}
    r.update(case_id=f"{sec_id}_{end['delist_date']}", sec_id=sec_id, ticker=ticker, report=DOC,
             confidence="inferred", skeptic="n/a", status="known_wrong", fixed_by=fixed_by, shape="ending",
             internal_last_trade_date=internal, note=REASON.format(note))
    r.update({f: "*" for f in SCORED})
    r.update(fields)
    return r


new = [row("BBG000CHWP52", "DISCA", "5c", "Series A reclassified one for one into WBD with DISCB and DISCK; "
           "mirrors DISCK's row; not a 5b regression to narrow",
           {"exit_kind": "exchange", "drop_reason": "", "continuation": "true", "successor_sec_id": "BBG011386VF4",
            "last_trade_date": "2022-04-08", "value_rule": "continuation", "cash_per_share": "",
            "cash_currency": "", "stock_ratio": "", "price_sec_id": "", "price_ticker": "", "price_date": "",
            "recovery_ratio": ""}, "2022-04-08"),
       row("BBG000BLG1L7", "EQC", "5g", "a voluntary delisting during the liquidation; exit_kind liquidation, the "
           "rest open; not a 5b regression to narrow", {"exit_kind": "liquidation"}, "*")]
truth_path, changes_path = ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_changes.csv"
truth = dl.read_csv(truth_path)
have = {r["sec_id"] for r in truth}
new = [r for r in new if r["sec_id"] not in have]
legs = load_legs(ROOT / "data/diagnosis_truth_legs.csv")
cases = parse_rows(new, "pre-rulings", legs)                     # validates the new rows
judged = judge_all(cases, LibraryRows.of(Tables.read(ROOT / "output")))
ledger_path = ROOT / dl.LEDGER
ledger = dl.read_ledger(ledger_path)
seeded = dl.seed_rows(judged, dl.ledger_keys(ledger), "5b-preruling")
changes = [{"case_id": r["case_id"], "field": "case", "old": "", "new": "added", "reason": r["note"], "report": DOC}
           for r in new]
for r in new:
    print({k: v for k, v in r.items() if v not in ("", "*")})
print(f"{len(new)} truth rows, {len(seeded)} ledger rows")
if not args.dry_run and new:
    dl.write_together([(truth_path, COLUMNS, truth + new),
                       (changes_path, dl.CHANGE_COLUMNS, dl.read_csv(changes_path) + changes),
                       (ledger_path, dl.LEDGER_COLUMNS, ledger + seeded)])
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/preruling_5b.py --dry-run`, check the two
rows, then the same without `--dry-run`. Then rerun round 1's script (the Step 1 command): DISCA and EQC are now in
the truth set, so they leave the regression report, and their mismatches are in the ledger as `known`; neither may
appear among the round's cases.

- [ ] **Step 3: Run the loop**

Run the Workflow tool with `scriptPath: ".claude/workflows/diagnosis-truth-loop.js"` and
`args: {"label": "5b", "base": "cc631e1"}`.

Expected: up to 3 rounds; each diagnoses and verifies its cases (regression mode for rows outside the truth set,
mismatch mode for truth rows), writes the records back, and runs `update_truth.py`, which flips every
`known_wrong` truth case the run now matches to `pass` (KHC, Liberty Series A and CNB should; SPB too if the
handoff kept its continuation). The agents judge MDRX, EPE, KWK, EK and ABK by the G4 reading: the exchange
removal is the ending, not a later OTC merger. Note the wall time and tokens for the report.

- [ ] **Step 4: Settle what the loop could not**

- A `pending` ledger row, or a regression with no record or no skeptic: settle it from the record's own text and
  the filings it cites, under the operator's delegated autonomy. The agents sometimes label old and new against
  their own text (HON in 5a); read the text, not the label. Record each ruling as a change-log row (`reason`
  starting `controller ruling (5b):`) and in the ledger (outcome `new_right` or `old_right`).
- A malformed record JSON: rerun that case's agent once; then settle it as above.
- A regression settled `old_right`: a 5b rule is wrong for that case. If one narrowing fixes it without moving a
  guard (`STAY`) or a truth case, make it a new task (its failing test from the case, then the fix), rerun Task 15
  and this task (moving the round folders aside first); otherwise keep the row as a truth row `known_wrong` with
  the sub-plan that owns it, and list it for the operator.
- A `ruling_pending` truth row left after round 3 is the operator's: list it in Task 17's report.

- [ ] **Step 5: Commit the loop**

```bash
git add data/diagnosis_truth.csv data/diagnosis_truth_changes.csv output/diagnose_unknown_report/loop output/regression_report.csv
git commit -m "Sub-plan 5b: the truth loop's rounds, diagnoses, pre-rulings and truth updates"
```

---

### Task 17: Acceptance and the operator report (controller)

Run by the controller.

**Files:**
- Create: `output/diagnose_unknown_report/loop/5b/report.md`, `.../loop/5b/cases_after.md`; `$TMPDIR/relabel_5b.py`
  (not committed).
- Modify: `data/scorecard.json` (the floor), `output/scorecard.json`, `data/diagnosis_truth.csv`,
  `data/diagnosis_truth_changes.csv` (the relabels), the roadmap.

- [ ] **Step 1: Relabel the 5b truth rows that still mismatch**

Write `$TMPDIR/relabel_5b.py`:

```python
"""After 5b's loop: each known_wrong truth row with fixed_by 5b that still mismatches gets the sub-plan that owns
its remaining fields (the last of them in roadmap order), with a change-log row. A row whose remaining mismatch is
its shape, its ending, its exit kind or its sec_id is a 5b miss: it keeps 5b and is printed for the report. Run
from the repo root; --dry-run prints only."""
import argparse
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection.diagnosis_truth import COLUMNS, LibraryRows, judge_case, load_legs, parse_rows
from delist_detection.lifecycle import Tables

ROOT = Path.cwd()
ORDER = ["5c", "5d", "5e", "5f", "5g", "5h", "5i"]
OWNER = {"continuation": "5c", "successor_sec_id": "5c", "last_trade_date": "5d", "internal_last_trade_date": "5d",
         "price_sec_id": "5e", "price_ticker": "5e", "price_date": "5e", "value_rule": "5f",
         "cash_per_share": "5f", "cash_currency": "5f", "stock_ratio": "5f", "recovery_ratio": "5f",
         "drop_reason": "5g"}
p = argparse.ArgumentParser()
p.add_argument("--dry-run", action="store_true")
args = p.parse_args()
truth_path, changes_path = ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_changes.csv"
rows = dl.read_csv(truth_path)
cases = {c.case_id: c for c in parse_rows(rows, str(truth_path), load_legs(ROOT / "data/diagnosis_truth_legs.csv"))}
lib = LibraryRows.of(Tables.read(ROOT / "output"))
changes, misses = [], []
for r in rows:
    if r["status"] != "known_wrong" or r["fixed_by"] != "5b":
        continue
    fields = [m.field for m in judge_case(cases[r["case_id"]], lib).mismatches]
    owners = set()
    for f in fields:
        if f in ("price_sec_id", "price_ticker", "price_date") and r["value_rule"] == "otc_print":
            owners.add("5g")                    # the OTC print's symbol and date are 5g's
        elif f in OWNER:
            owners.add(OWNER[f])
        else:
            owners.add("5b")
    if not fields or "5b" in owners:
        misses.append((r["case_id"], r["ticker"], fields))
        continue
    new = max(owners, key=ORDER.index)
    changes.append({"case_id": r["case_id"], "field": "fixed_by", "old": "5b", "new": new,
                    "reason": f"relabel after 5b's loop: remaining {', '.join(fields)}", "report": r["report"]})
    r["fixed_by"] = new
for c in changes:
    print(c["case_id"], "->", c["new"], "|", c["reason"])
for m in misses:
    print("5b MISS (keeps 5b):", *m)
if not args.dry_run and changes:
    dl.write_together([(truth_path, COLUMNS, rows), (changes_path, dl.CHANGE_COLUMNS,
                                                     dl.read_csv(changes_path) + changes)])
```

Run it with `--dry-run`, then without. Likely relabels (the run decides): PRE, CCU, DPL, NTY, TXU, STN,
BMET and MWW to 5f (cash_currency and amounts), XMSR and SOV to 5f (the stock legs), JEF to 5e, RHDC, IDARQ, LKSD
and LTRPA to 5g, SPB to 5c or 5d (whichever field remains). A `5b MISS` line is a case 5b's rules should have moved
and did not: list it in the report with its remaining fields.

- [ ] **Step 2: The checks**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --check --base cc631e1`
Expected: exit 0: no `DROP`, no `GOLDEN FAILING`, no `DIAGNOSIS FAILING`, and `D.unexplained_regressions 0`. For
each line that fails it:
- `D.unexplained_regressions` above 0: a regression the ledger has not settled (Task 16 Step 4).
- `DROP <metric>`: lower that floor entry by hand only when the drop is traced to a truth correction or to a change
  the loop settled as right (new endings that are uncertain, review rows of new endings, `L1.closed_no_event` +1
  for Liberty Series A, ...), with the reason in the commit message; otherwise it is a defect to report.
- `DIAGNOSIS FAILING`: a `pass` truth case the run now fails (LVNTA must not): report it.

- [ ] **Step 3: Raise the floor**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --write --raise-floor`
Expected: `D.mismatches` and its fields move down in `data/scorecard.json`'s floor (never up).

- [ ] **Step 4: The suite**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: green apart from golden `known_wrong` cases the run now passes (strict XPASS in
tests/test_golden_lifecycles.py; STN, "bought out 2007-11-07", is likely). Do not edit
`data/golden_lifecycles.csv`: list each XPASS case for the operator to flip, and wait. A diagnosis truth XPASS should
not remain (the loop flips them); if one does, rerun the last round's update:
`PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/update_truth.py --label 5b --round <last> --base cc631e1`.

- [ ] **Step 5: The cases, after**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python $TMPDIR/cases_5b.py > output/diagnose_unknown_report/loop/5b/cases_after.md`
(the script Task 15 Step 1 wrote; if `$TMPDIR` was cleared, write it again from there). Compare it row by row with
`cases_before.md`.

- [ ] **Step 6: The report**

Write `output/diagnose_unknown_report/loop/5b/report.md` with these sections, every number from the commands above:

1. **Result**: accepted or not; `D.mismatches` before (646: 649 after 5a, 646 after the pre-check rulings of
   cc631e1) and after; the floor raised; `--check --base` result; pytest result (and the golden XPASS cases waiting
   for the operator).
2. **Mismatches per field**: one row per `D.mismatches.<field>` from `scorecard_before.txt` and the scorecard now.
3. **The cases**: the table of Step 5, before and after, with this plan's Expected outcome beside each, and why each
   one that still mismatches does (the sub-plan its `fixed_by` now names).
4. **The rules**: per rule, the securities it moved in the run (`other issuer in force:` line; E, L, R3, R2, R7, R6a,
   R6b), and the Task 14 review's findings and fixes.
5. **Regressions**: how many, by kind (`regression_kinds_5b.py`), and how each was settled (new_right, old_right,
   pending, pre-ruled), with the reports' paths.
6. **Truth changes**: every row of `data/diagnosis_truth_changes.csv` 5b added (the pre-rulings, the loop's updates,
   the controller's rulings, the relabels).
7. **Uncertain endings and coverage**: `V.uncertain_endings`, `V.uncertain_securities`, `L1.coverage_securities` and
   `L1.coverage_tickers`, before and after.
8. **For the operator**: rulings needed (pending rows, old_right regressions kept, floor drops lowered and why),
   golden cases to flip, `5b MISS` rows, the loop's time and tokens, and what was deferred (Ruling 9).

- [ ] **Step 7: Roadmap and commit**

In `docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md`, set the 5b row's Status to
`done (D.mismatches 646 -> <after>; <n> of 50 cases now pass)` once the operator accepts the report (until then:
`run, awaiting the operator`).

```bash
git add data/scorecard.json output/scorecard.json data/diagnosis_truth.csv data/diagnosis_truth_changes.csv output/diagnose_unknown_report/loop/5b docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md
git commit -m "Sub-plan 5b accepted: D.mismatches 646 -> <after>, floor raised; the operator report"
```

Send the operator the report's path and its sections 1, 3 and 8.

---

## Self-review

- **Spec coverage.** Section 3 "5b", rule by rule: (1) search from before the first sighting to today, refusing
  only a sibling alive on the filing date: E (Task 8), L (Task 10), C makes `continued` honest (Task 6), the
  sibling slack is kept (binding; pinned in Task 1); (2) one multi-class 25-NSE to each class it names: today's
  `_class_matches`, plus R2's letter hint for letterless classes (Task 11); (3) a Form 25 only about rights or
  another tracking group: R3 (Task 9); (4) class-label noise such as "(New)": `class_kind` already reads "Common
  Stock (New)" as common (RHD's 2009 25-NSE matches in the fixture), so no task; (5) the CIK that holds the
  security: R5, narrowed to the one other CIK in force over the whole span (Task 12); (6) a matched Form 25's path
  owns the row: R6a (Task 4) and R6b (Task 5), narrowed as measured; the continued-filings rule keeps the
  continuations APA, CMCSK, HHC and HUB-B; (7) a same-day 8-A12B: R7, the issuer's own Form 25 within 10 days
  (Task 7). The "where" list: `DelistingFinder.find` (`_alive_at` and `SIBLING_ALIVE_AFTER_DAYS` kept,
  `FORM25_LOOKBACK_DAYS` kept with the early window beside it, `early`, `SAME_EVENT_DAYS` kept),
  `form25.match_security`/`class_kind` (Tasks 9, 11), `listing_status.withdrawal_kind` (unchanged; Apache pinned),
  `classifier.classify_event` (Tasks 4, 5), `end_of_era.resolve` (Task 2). Must-not-change: Apache/Chicago 2020
  (`STAY`), APA (`STAY`), a transfer Form 25 that continued the same security (MWW 2008, MSG 2015, KHC). The six
  "unconfirmed mechanism" cases were replayed in the research and again here (the fixture reproduces them). The
  binding pull-in of 5g sub-rule 2 is Task 2 (ASNA). The deficiency wording is Task 3. Section 1 (the loop,
  acceptance) is Tasks 15 to 17; the 5a lessons are in Tasks 14 to 17.
- **Placeholders.** None: every code step is complete. The counts the controller fills in (the after-numbers in
  Task 17) are measurements, not code.
- **Type consistency.** `_continued(ctx, sub, f25)` in Task 6 gains `filings` in Task 7 (both call sites edited
  there), and Task 12's groups pass `filer_filings`; `_judge(ctx, scan, filer, sub, refs)` gains `quiet` in Task 8
  and `issuer_names` in Task 9 (every call site edited, and Task 12 calls it with both); `_Scan.unreadable` comes
  in Task 8, `older` in Task 6; `SecurityContext.trades_after` (6), `cusip_rows_near` (10), `other_cik` (12) are
  filled by `_context_builder` in the same tasks; `pipeline._context_builder(..., other_ciks={})` (12) is called
  with five arguments by tests/form25_cases.py before Task 12 and six after. The whole sequence was applied
  mechanically to a fresh copy of `cc631e1` while planning, task by task: each task's new tests fail before its
  code and the suite is green after it (2094, 2104, 2111, 2113, 2121, 2130, 2134, 2139, 2147, 2150, 2155, 2161
  passed; 245 xfailed throughout).
- **Review Focus.** Each line has its test in the owning task (Tasks 6, 7, 8, 11, 12).

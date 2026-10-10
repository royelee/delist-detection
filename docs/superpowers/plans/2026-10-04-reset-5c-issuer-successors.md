# Sub-plan 5c: Issuer Role and Successor Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An ending's kind follows the registrant's role and ruling R1: a registrant that acquired another company or
distributed another company's shares gets no merger ending; a one-for-one exchange with no cash into a new issuer or
another class of the same issuer is a continuation linked to its successor, whether the 8-K items said merger, said
nothing, or the row was already a transfer without a successor; and the successors the run adds have their own
Form 25 endings.

**Architecture:** One new pure reader, `exchange_terms.py`, reads what a filing says the registrant's own shares
became (ratio, cash, the target clause and the names it carries, special dividends set aside), and the registrant's
two other roles (an acquirer; a distributor). The classifier asks it twice in stage 5: before end-of-era branches 3
and 4 (the role refusal, rule 1) and before the no-evidence default (R1 with no item code). A new stage 8b rewrites a
merger whose published terms are one share and no cash, when the registrant's filings agree and the successor is a
new issuer or the same issuer (`successors.successor_by_terms`). Stage 9 links an exchange transfer without a
successor through the same reading, or through its own same-CIK successor registration's new CUSIP (R2). A new
stage 9d runs the Form 25 search for the successors the run added. A real-case fixture set replays stages 5, 8b and
9 offline for 40 securities; a whole-run offline replay over the caches is the review's check.

**Tech Stack:** Python 3.10+, pytest (offline: `FakeEdgar`, the doubles, a fixture set built once from the local
caches), the SEC fails-to-deliver zips, EDGAR, OpenFIGI, MIDAS, the Nasdaq halt feed, the Claude Code Workflow tool
for the truth loop (sonnet agents).

**Spec:** `docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md` (section 1, the truth loop and
acceptance; section 2.1, rulings R1 and R2; section 3 "5c"). Roadmap:
`docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md`. Design source (read it first):
`docs/superpowers/plans/research/2026-10-04-5c-issuer-successors.md` (section 6 is the design; sections 3 to 5 its
guards, blast radius and truth conflicts, which the operator ruled on 2026-10-04). The format exemplar is
`docs/superpowers/plans/2026-10-04-reset-5b-form25-reach.md`; 5b's operator report is
`output/diagnose_unknown_report/loop/5b/report.md`. **Base commit: `77d69c3`** (D.mismatches 588).

## Global Constraints

- In this worktree run every command from the repo root with `PYTHONPATH=src` and
  `~/miniconda3/envs/rdagent4qlib/bin/python` (the editable install points at the main checkout). Run pytest as
  `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest` with no extra `-q` (addopts has it).
- The worktree's shell guard refuses a pipe with git, `cd`, a heredoc, and `PYTHONPATH` set to a variable. Every
  command below is a plain command with literal paths; scratch files go to `/tmp/claude/delist_detection/5c/`
  (create it with `mkdir -p /tmp/claude/delist_detection/5c`), never committed.
- Tests are fully offline: `FakeEdgar` (tests/conftest.py), the doubles in tests/test_pipeline.py, plain row
  fixtures, and one real-case set, `tests/fixtures/issuer_role/`, built once from the local cache by the committed
  offline builder `scripts/build_issuer_role_fixtures.py` (Task 1). Never add network to a test.
- `output/` is regenerated only in Task 10. Every earlier task keeps the full suite green against the committed
  output: 2201 passed and 240 xfailed at `77d69c3`, plus each task's new tests (2310 passed, 240 xfailed after Task 7;
  each task names its count).
- "Append to `<file>`" means: at the end of the file, after two blank lines. A block's own imports (marked
  `# noqa: E402`) stay inside the block. "Replace X with Y" quotes X exactly as the file holds it after the
  earlier tasks; when X is not found once, stop and report rather than adapt it.
- The rules are research section 6 with its measured narrowings (operator, 2026-10-04, binding):
  - **Rule 1 (the role)**: before end-of-era branches 3 and 4 only, never on rename or separation words: a
    registrant whose filings state no exchange of its own shares (`exchange_terms.own_exchange` finds none, a cash
    one included), and that acquired another party (another party's shares became its own, or it issued its shares
    to the other party under the merger agreement) or distributed another company's shares to its holders ("for
    every four shares"), gets no merger; the resolver goes on to branch 5 or 6.
  - **R1**: a one-for-one exchange with no cash is a continuation only into a new issuer (its first EDGAR filing at
    most `NEW_ISSUER_DAYS` = 1095 days before the event: new holdcos measured 0–548 days, existing acquirers
    4,125–8,442) or the same CIK. A deal's special dividend is never consideration, paid before or after the
    closing (BHI, EGL, SBGI, KRFT). LVNTA (into an existing GCI Liberty) stays a merger.
  - **Merger rows (stage 8b)**: the published terms must be one share and no cash (or cash equal to a special
    dividend the filings name), and the registrant's own filings must say the same of its own shares in one
    reading (JEF and SGP: the LLM's final terms decide against the text's intermediate one-for-one).
  - **Rule 4 (a new issuer)**: needs a name tie: the R1 statement's target names the successor (one of its tickers
    or EDGAR names, current or former; a defined term expanded: "Holdco" is "Howard Hughes Holdings Inc."). Without
    it AABA would link to BHGE, MSG to Alphabet and HUB-B to two unrelated registrants (measured).
  - **Rule 4 under the same CIK (own registration)**: the registrant's own 8-K12B/8-K12G3 and the new CUSIP its
    texts name (else the first new CUSIP under its tickers within 15 days), resolved by OpenFIGI's CUSIP job and R2;
    never the TICKER job.
  - **Stage 9d**: the added successors' Form 25 search, Form 25 matches only, no fallback ending.
  - **RRI's line-follow fix**: `line_follow.text_symbols` reads "changed from “RRI” to “GEN”" as GEN.
- Must not change, pinned by tests with real tickers (Task 1's fixture set, `STAY`; Task 2's reader cases): TW, WCN,
  LVNTA, JEF, SGP, FCL, BKW, BNI, CAL, TXU, LGFA, AABA, MSG 2015, SIRI 2024, CHTR 2016, and the new-issuer ages of
  DowDuPont (548 days), Linde (517) and Viatris (388), which count as new (Task 5). 5a's and 5b's real-case tests
  (`tests/test_line_follow_cases.py`, `tests/test_form25_reach_cases.py`) stay green.
- Truth: the operator's 5c rulings are applied (`77d69c3`); no task edits the truth before Task 11. The loop's
  pre-ruling (Task 11 Step 2): RRI, SXCI, NWS-A and NCRA are re-shaped to `ending_moved` (every scored field `*`) by
  script when the run follows their line to a real later ending.
- Do not edit or commit `data/golden_lifecycles.csv` or `data/accuracy_audit.csv`. A golden `known_wrong` case that
  starts passing is the operator's to flip: list it and ask (Task 12).
- A scorecard floor entry is raised only by `scripts/scorecard.py --raise-floor`. It is lowered by hand only when the
  drop is traced to a truth correction or to a change the loop settled as right, with the reason in the commit.
- Implementers and reviewers run on model `sonnet`; each task names its tier. Tasks 9 to 12 are run by the
  controller; Task 9's whole-branch review runs on `opus`. The truth loop runs at most 3 rounds and at most 5 agents
  at a time.
- SEC access for the network run: `DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock`, one
  SEC client at a time across sessions; Bash `allowed_domains`: data.sec.gov, www.sec.gov, efts.sec.gov,
  api.openfigi.com, api.nasdaq.com, www.nasdaqtrader.com, api.openai.com. Every run and rerun passes
  `--id-baseline` with `77d69c3`'s `output/securities.csv`.
- Every data file a script writes goes through `atomic_io.write_atomic`.
- Never merge or push; commits stay on the worktree branch. Commit messages end with the session's attribution lines
  (Co-Authored-By, Claude-Session).
- Out of scope (Rulings 9 and 10 below): spec rule 6 (another ratio or an election is a merger: 5f), the
  successor-search names (`handoffs.predecessor_names` in `successor_search_args`), a fails-description step
  source for SXCI, NWS-A and NCRA, LMCA 2016 and LMCK under R3 (5f), last trade dates (5d), update_truth's payout
  legs and the malformed-record retry.

## Review Focus

1. A cash take-private whose 8-K also converts insiders' rollover shares into the surviving company's
   (Continental Resources 2022): the registrant is a target, so the role refusal must not fire; its own exchange is
   a cash one (Task 2, test `test_a_cash_take_private_whose_insiders_rolled_over_is_a_target_not_an_acquirer`).
2. A merger whose terms are one share plus cash: the cash is no consideration only when it equals a special
   dividend the filings name (KRFT's $16.50); any other cash keeps the merger (Task 5, test
   `test_a_special_dividend_is_no_cash_but_other_cash_keeps_the_merger`).
3. Two new lines of one new issuer first sighted in the window (Liberty Live Holdings' Series A and C): the class
   letter the target names picks one; two of the same class tie and link nothing (Task 5, test
   `test_two_new_lines_of_one_issuer_are_told_apart_by_the_class_letter_and_two_of_one_class_tie`).
4. A same-CIK successor registration whose new CUSIP's OpenFIGI answer is an error (not cached, OKE 2026) or names
   several composites: no link, the row keeps `successor_unknown` (Task 6, test
   `test_an_unsettled_new_cusip_links_nothing`).
5. An added successor listed today, or whose issuer's Form 25 at its own first day removed its predecessor (Clear
   Channel Outdoor 2019): stage 9d gives it no ending (Task 7, tests
   `test_a_successor_listed_today_or_an_acquirer_takes_no_ending` and
   `test_the_predecessors_form25_at_the_successors_first_day_is_not_its_ending`).

## Rulings made in this plan

Each is a choice the research or the binding decisions left open; the cost if wrong is named.

1. **The reader is clause-based and conservative.** A statement is "each share of S … converted / exchanged /
   reclassified / redeemed … into / for N shares of T", "received N shares of T for each share of S", "on a
   one-for-one basis for an equivalent share", "an equal (like, identical) number of shares", or a cash one
   ("into the right to receive $74.28"). Sentences split at their ends and clauses at their enumerators ("(i)",
   "(2)"); parentheticals are set aside after the defined terms are read. The subject is the registrant's when its
   first named party is (an EDGAR name's first word, or its first two joined, in the year up to two days before the
   earliest day read; a defined term standing for one, also without "Old"/"Legacy"; "the Company", "its", "our"),
   and is not an award, another security, a merger subsidiary's or rollover shares. A record date, "for every", "the
   Distribution" make it a distribution. Measured over the run's 1,005 delisting rows (offline): the role refusal
   fires on exactly RRI, SXCI, NWS-A, NCRA and FST among the 69 branch-3/4 rows, and every reading the replay acts
   on is one the Expected outcome lists. Cost: a statement worded otherwise is not read (the row keeps today's
   answer: FTI's own one-for-one is misattributed, NSAM's two own readings disagree, so neither moves).
2. **Read windows.** The registrant's 8-Ks (8-K12B, 8-K12G3 included) filed in [day − 3, day + 10] of each day read:
   the ending's anchor (last trade, else the Form 25 filing date, else the 8-K the classifier anchored on, else the
   delisting date) and, for the role refusal, the 5.01 and 2.01 8-Ks' dates; plus the matched Form 25's notice.
   SXCI's and FCL's deciding 8-Ks fall outside the anchor's window. Cost: about 130 cold texts in the network run.
3. **Rule 6 is deferred to 5f.** As written ("a successor registration with another ratio is a stock merger"),
   the measured reader would also make SIRI 2024 a merger (0.1 New Sirius per share inside its reverse split; a
   `pass` continuation) and misreads ACT's garbled notice (0.160). CHTR's truth row is 5f's already.
4. **Stage 8b links the successor itself** (and adds an 8-K12B successor the run does not hold, ROVI's TiVo Corp,
   when its filer is new), so research U5 (lifting the handoff's `timing:cusip` conflict) needs no code: a rewritten
   row already names the handoff's successor. Measured: LLYVA, LLYVK and DTV leave their conflicts; XRX, PNFP, VNOM
   and ANAT, merger rows the handoff used to rewrite, take the same successor in 8b. The 8-K12B search runs only for
   a merger row R1 rewrites with no successor in the run.
5. **The same-CIK link requires exactly one composite.** None (OpenFIGI not caught up), several or an error link
   nothing; the security's own composite makes the security its own successor (R2: it goes on).
6. **Stage 9d** searches line successors and 8-K12B successors (never an added acquirer), skips one listed today,
   and ignores a Form 25 filed within `PREDECESSOR_FORM25_DAYS` (30) of the successor's first day (its
   predecessor's). An 8-K12B successor with no fails rows is alive to the run date; its span then runs to the
   ending's last trade (`AddedSuccessor.last`). 9d reuses stage 5's sequential finder.
7. **Flags.** `r1_continuation` (info) on every row R1 makes a continuation (stage 5 or 8b); `r1_rebucketed`
   (check) review item on a merger row 8b rewrote, keeping its old bucket and code. A survived row carries
   `evidence["survived"]`, no flag.
8. **The contract's history** keeps an acquirer the run added (Sinclair Inc) when 8b made it a merger row's
   successor (`_contract`'s `successor_ids`).
9. **No step source for SXCI, NWS-A and NCRA.** The role refusal turns their mergers into transfers (SXCI and NWS-A
   then link to CTRX and FOXA through today's `successor_in_run`); their `no_ending` shape stays, residual for the
   operator (research section 6, last item).
10. **Search names unchanged.** Research U4's search-name change (`predecessor_names`) is not needed: BHI links
    through its own conversion sentence. Changing it would send new full-text searches for every unlinked
    transfer, unmeasured.
11. **Five of the seven new-holdco deals outside the truth set move, not seven.** ASH, CSC, HFC, WWE and STE become
    continuations; NSAM (its 8-Ks state two different own-share terms: ambiguous) and FTI (its own one-for-one is
    misattributed to Technip's 2.0 through a defined term) stay mergers, as today. Widening the reader for them was
    not measured against the guards; the cost is two rows the operator's R1 reading would make continuations, left
    for the loop's next sub-plan touching the reader (5f).

## Expected outcome (an offline replay of this plan's code over the cached data)

A prototype of every task, replayed over the whole run with network refused (Task 9's replay: `pipeline.run` over
the committed observations; an uncached filing text reads as blank, an uncached OpenFIGI job as an error), changes
**34 securities: 25 in the truth set, 9 outside it**, and moves D.mismatches **from 588 to 479**. The fixture
harness moves its 40 cases as the replay does (its smaller world gives MSG 2015 a `same_issuer` link both before and
after 5c; the full run has none).

**Truth cases (25).** What the offline replay gives each, and what is left:

| case | after 5c (offline) | left for |
| --- | --- | --- |
| BHI, HHC | 304 linked to BHGE, HHH (new issuer) | **pass** |
| CMCSK, HUB-B, CWENA | 304 linked to CMCSA, HUBB, CWEN (same issuer's class) | **pass** (CWENA: stage 5 R1 first) |
| CCO | 304 linked to BBG000SSC5C9 (own registration, R2) | **pass** |
| DOW, MYL, WAG, DTV, KRFT | 8b: 304 into DWDP, VTRS, WBA, new DIRECTV, KHC | **pass**; MYL internal ltd (5d) |
| DISCA, DISCK | 8b: 304 into WBD (same issuer) | **pass** |
| SBGI | 8b: 304 into Sinclair Inc (an acquirer the run added) | **pass** |
| LLYVA, LLYVK | 8b: 304 into Liberty Live Holdings A, C | last_trade_date 2025-12-15 (5d) |
| PX, AMSG, WR | 8b: 304 into Linde plc, new Envision, Evergy | **pass** (truth fixed_by 5e: the loop flips them) |
| OKE | stage 5 R1: 304; no successor offline (30609A109 not cached) | network: own registration, then ltd (5d) |
| FST | rule 1: 570 compliance failure | otc_print ticker FSTO (5g) |
| RRI | rule 1: 304, no successor | network: the GEN line follow; re-shape if it ends later (Task 11) |
| SXCI, NWS-A | rule 1: 304 into CTRX, FOXA (same issuer) | shape `no_ending` (residual, Ruling 9) |
| NCRA | rule 1: 304 | shape `no_ending` (residual, Ruling 9) |

ROVI does not move offline: its successor TiVo Corp is found only by the 8-K12B search (network); then it passes.
ODP and SPWRA keep their last-trade fields (5d). Expected after the network run: D.mismatches about 470 before the
loop.

**Outside the truth set (9), the regressions the loop diagnoses:**
- R1 continuations of new-holdco deals (research section 4: all expected new_right): ASH (Ashland Global), CSC
  (DXC), HFC (HF Sinclair), WWE (TKO), STE (STERIS plc). FTI, NSAM and AAN do not move (the reader misattributes
  FTI's 2.0, NSAM reads two terms, AAN's successor has no CIK).
- Stage 9d endings on truth chains (left out of the regression report): DYN's 2010 line (2012 bankruptcy), CRC's
  2016 line (2020 bankruptcy).
- Successors on truth chains: BBG000SSC5C9 (CCO's new line, added), BBG01GJ3NY88 (Sinclair Inc's history).
- Network-only: TiVo Corp (ROVI's chain) and its 2020 ending; ODP Corp's 2025 ending (its Form 25 is not cached);
  any branch-3/4 row whose uncached 8-K text (about 130) reads as an acquirer's or a distributor's.

## File Structure

Create:
- `scripts/build_issuer_role_fixtures.py`: the offline builder of `tests/fixtures/issuer_role/` (reuses
  `scripts/build_form25_fixtures.py`'s helpers).
- `tests/fixtures/issuer_role/{cases.json,edgar.json.gz,figi.json,ftd_rows.csv.gz,midas.json,halts.json}` (built,
  committed, about 1.2 MB).
- `tests/issuer_role_cases.py`: the replay harness (stages 5, 8b and 9 over the fixture).
- `tests/test_issuer_role_cases.py`: the real cases (`MOVES`, `STAY`, `RULES_DONE`).
- `src/delist_detection/exchange_terms.py`: the own-share conversion reader (pure, and `read_texts`).
- Tests: `tests/test_exchange_terms.py`, `tests/test_successor_terms.py`, `tests/test_successor_links.py`,
  `tests/test_successor_endings.py`.

Modify:
- `src/delist_detection/line_follow.py` (Task 3), `end_of_era.py` and `classifier.py` (Task 4), `successors.py`
  (Task 5), `pipeline.py` (Tasks 5, 6, 7), `review_triage.py` (Tasks 4, 5), `delistings.py` and
  `added_securities.py` (Task 7).
- Tests: `test_line_follow.py`, `test_end_of_era.py`, `test_review_triage.py`, `test_run_provenance.py`.
- `CLAUDE.md`, the roadmap.
- Data, by Tasks 10 to 12: `output/`, `data/diagnosis_truth.csv`, `data/diagnosis_truth_changes.csv`,
  `data/scorecard.json`, `output/diagnose_unknown_report/loop/` (the ledger, rounds, report).

---

### Task 1: Real-case fixtures and the stage 5, 8b and 9 replay harness

Tier: standard (the builder reads the local caches; its output is committed).

This task pins today's behaviour; every later task moves its own cases by adding its rule to `RULES_DONE`. Its tests
pass on the first run: they characterize the code before 5c.

**Files:**
- Create: `scripts/build_issuer_role_fixtures.py`, `tests/issuer_role_cases.py`, `tests/test_issuer_role_cases.py`
- Create (by the builder): `tests/fixtures/issuer_role/{cases.json,edgar.json.gz,figi.json,ftd_rows.csv.gz,midas.json,halts.json}`

**Interfaces:**
- Consumes: today's `pipeline._context_builder(securities, sightings, answers, ftd, sec_cusips)`,
  `pipeline._IssuerAnswers`, `pipeline._Payouts(raw, llm_terms, gated, acquirer_ids, added, review)`,
  `pipeline._RunContext(clients, as_of, log, sec_workers, meter)`, `pipeline._find_successors(ctx, delistings,
  securities, sightings, acquirers, line_successors, ftd)`, `pipeline._link_successors`, `DelistingFinder`,
  `DelistClassifier`, `MergerTerms`, `GatedPayouts`; `scripts/build_form25_fixtures.py`'s `LocalFtd`, `_securities`,
  `_read`, `_cached`, `_day`, `_line_tickers`, `KEPT_FORMS`, `AS_OF`, `FTD_WINDOW`, `COVER_DAYS`.
- Produces (tests/issuer_role_cases.py): `DATA`, `EDGAR`, `FIGI`, `FixtureEdgar` (with `texts_read`), `FixtureFigi`,
  `FixtureMidas`, `FixtureHalts`, `world() -> (securities, added, cusips, FtdIndex)`, `clients(edgar=None)`,
  `find(sec_id, clients) -> (delistings, review)`, `_payouts(sec_id, found) -> pipeline._Payouts`,
  `after(sec_id, edgar=None) -> list[Delisting]`, `outcome(sec_id, **kw) -> list[tuple]`. It calls
  `pipeline._r1_continuations` when it exists (Task 5) and passes `_find_successors` its `sec_cusips` when it takes
  them (Task 6). tests/test_issuer_role_cases.py: `RULES_DONE`, `ORDER`, `MOVES`, `STAY`, `_expected`.

- [ ] **Step 1: Write the builder**

Create `scripts/build_issuer_role_fixtures.py`:

```python
"""Build tests/fixtures/issuer_role/ from the local caches, once (sub-plan 5c): the real cases whose ending kind
(stage 5), R1 rewrite (stage 8b) and successor link (stage 9) tests/test_issuer_role_cases.py replays offline
through the run's own code (tests/issuer_role_cases.py).

  PYTHONPATH=src python scripts/build_issuer_role_fixtures.py          # -> tests/fixtures/issuer_role/

Offline, as scripts/build_form25_fixtures.py (whose helpers it reuses): it reads the committed output/ (each case's
security, its eras and observations, CUSIPs, listed today, its delistings and the contract's terms; and the
securities a link may name), the cached fails zips, EDGAR answers (every SEC request refused: a missing answer is
left out), OpenFIGI answers, MIDAS summaries and Nasdaq halt days. It writes:

- cases.json: each case (its note, its delistings' anchors, the terms the contract published for its merger rows)
  and every security the cases need (the cases, the securities a successor link may name, and the other
  securities of their issuers: CIK, class, name, kind, eras with their observations, CUSIPs, line tickers, listed
  today; an acquirer the run added: its ticker and span);
- ftd_rows.csv.gz: every fails row of a case's CUSIPs in the run's window and every row under a case's tickers
  within 40 days of a delisting's anchor; for the other securities, the first and last row per (CUSIP, symbol)
  and the first per (CUSIP, description);
- edgar.json.gz: each CIK's EDGAR names, tickers and filings (every Form 25, 8-K, periodic report, Form 15,
  revocation, 8-A12B and merger filing, and its first filing of any form, in EDGAR's order), every cached Form 25
  raw, every cached 8-K text filed within TEXT_DAYS of a case's anchor, and those 5b's builder keeps;
- figi.json: the cached OpenFIGI answer of every CUSIP job a successor link may send (a CUSIP a case's texts name,
  or a new CUSIP under its tickers after its anchor), its US venues' rows only; an uncached one is an error answer;
- midas.json, halts.json: as scripts/build_form25_fixtures.py.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_form25_fixtures as b5  # noqa: E402  (refuses every SEC request on import)
from delist_detection.atomic_io import write_atomic  # noqa: E402
from delist_detection.edgar import EdgarClient  # noqa: E402
from delist_detection.form25 import FORM25_FORMS  # noqa: E402
from delist_detection.figi_resolution import US_EXCH  # noqa: E402
from delist_detection.ftd import FtdIndex  # noqa: E402
from delist_detection.line_follow import text_cusips  # noqa: E402
from delist_detection.listing_status import ANNUAL_FORMS  # noqa: E402
from delist_detection.nasdaq_halts import parse_halts_rss  # noqa: E402
from delist_detection.security_master import cusip_job  # noqa: E402

AS_OF, FTD_WINDOW, COVER_DAYS = b5.AS_OF, b5.FTD_WINDOW, b5.COVER_DAYS
TEXT_DAYS = (40, 70)            # 8-K texts kept from this long before a case's anchor to this long after
ROWS_DAYS = 40                  # fails rows under a case's tickers kept this close to its anchor

# The cases: securities of the committed run, each with what it pins
CASES = {
    "BBG000BD4VG8": "BHI 2017: one share of BHGE's Class A, a special dividend; a new issuer (rule 4)",
    "BBG000MJRJJ2": "HHC 2023: one share of Holdco's common; a new issuer (rule 4)",
    "BBG000BFTJ91": "CMCSK 2015: Class A Special reclassified into Class A (rule 3)",
    "CIK48898-CLASS-B": "HUB-B 2015: Class B reclassified into the new common, cash only for Class A (rule 3)",
    "BBG000J453J8": "CCO 2019: the same CIK's 8-K12B, a new CUSIP with its own composite (rule 4, own registration)",
    "BBG004P33PN3": "CWENA 2026: Class A converted into Class C, no 8-K item code (R1 in stage 5, rule 3)",
    "BBG000BQHGR6": "OKE 2026: a holding company's formation, no 8-K item code (R1 in stage 5)",
    "BBG000BHBK84": "DOW 2017: one DowDuPont share, DuPont's 1.282 beside it (8b)",
    "BBG000BPQD31": "MYL 2020: one Viatris share (8b)",
    "BBG000F2XXP2": "SBGI 2023: one New Sinclair share; the successor an acquirer the run added (8b)",
    "BBG000VMWHH5": "DISCK 2022: Series C reclassified into WBD, the same CIK (8b)",
    "BBG000CHWP52": "DISCA 2022: Series A reclassified into WBD, the same CIK (8b)",
    "BBG01HMFL081": "LLYVA 2025: a split-off into the corresponding series (8b)",
    "BBG01HMFLTN1": "LLYVK 2025: a split-off into the corresponding series (8b)",
    "CIK104207-COMMON": "WAG 2014: one WBA share (8b)",
    "CIK944868-COMMON": "DTV 2009: one new DIRECTV share; LEI's 1.1113 beside it (8b)",
    "BBG000BJ9D07": "ROVI 2016: one Parent share; the successor not in the run (8b needs the 8-K12B search)",
    "BBG001YMS0B8": "KRFT 2015: one Kraft Heinz share and a special dividend (8b)",
    "BBG000CGQ6M4": "PX 2018: one Linde plc share (8b; truth 5e)",
    "BBG000G0PPW3": "AMSG 2016: one new Envision share (8b; truth 5e)",
    "CIK1126294-COMMON": "RRI 2010: the legal acquirer of Mirant (rule 1)",
    "CIK1363851-COMMON": "SXCI 2012: the acquirer of Catalyst (rule 1)",
    "CIK1308161-COMMON": "NWS-A 2013: the distributor of new News Corp (rule 1)",
    "CIK1308161-CLASS-A": "NCRA 2013: the distributor of new News Corp (rule 1)",
    "CIK38079-COMMON": "FST 2014: issued its shares to Sabine; the NYSE price deficiency (rule 1, branch 5)",
    "BBG0038K9G41": "LVNTA 2018: one GLIBA share, an existing issuer (stays a merger)",
    "BBG000BJCFP1": "JEF 2013: an intermediate one-for-one, then 0.81 LUK (stays a merger)",
    "BBG000BSVZM9": "SGP 2009: $10.50 and 0.5767 New Merck; renamed Merck after (stays a merger)",
    "BBG000BM1RP0": "FCL 2009: 1.084 New Alpha, renamed Alpha after (stays a merger)",
    "BBG000BBLK04": "TW 2016: LLM 1.0 WLTW, an existing issuer (stays a merger)",
    "BBG000BHW628": "WCN 2016: one share after a consolidation, an existing issuer (stays a merger)",
    "BBG003444577": "BKW 2014: 0.99 QSR and $3.00 (stays a merger)",
    "BBG000K1T0M8": "LGFA 2025: a separation, the target of New Lionsgate (stays a merger)",
    "BBG000BDKN87": "BNI 2010: renamed after its acquisition (stays a merger)",
    "BBG000BDXVW8": "CAL 2010: 1.05 UAL, renamed (stays a merger)",
    "BBG000BVW841": "TXU 2007: an LBO, renamed (stays a merger)",
    "CIK1011006-COMMON": "AABA 2017: a rename, no statement; BHGE first sighted near it (no link)",
    "CIK1469372-CLASS-A": "MSG 2015: a spin-off distribution (no link)",
    "BBG000BT0093": "SIRI 2024: 0.1 New Sirius, a continuation already (unchanged)",
    "BBG000PYZSR8": "CHTR 2016: 0.9042 New Charter, a transfer with a successor (unchanged: rule 6 is 5f's)",
}

# The securities a successor link may name (and the guards' existing acquirers), with what each one is
SUPPORT = {
    "BBG00GBVBK51": "BHGE", "BBG01HTMDZ54": "HHH", "BBG000BFT2L4": "CMCSA", "BBG000BLK267": "HUBB",
    "BBG008LJ4TF3": "CWEN", "BBG00BN961G4": "DWDP", "BBG00Y4RQNH4": "VTRS", "BBG01GJ3NY88": "Sinclair Inc (added)",
    "BBG011386VF4": "WBD", "BBG01YY256K1": "LLYVA (Liberty Live Holdings)", "BBG01YYX1Z14": "LLYVK (Liberty Live "
    "Holdings)", "BBG000BWLMJ4": "WBA", "BBG000FL1TC8": "DTV (new DIRECTV)", "BBG005CPNTQ2": "KHC",
    "BBG00GVR8YQ9": "LIN (Linde plc)", "BBG00D3CHRC0": "EVHC (new Envision)", "BBG00K7K2XZ0": "GLIBA",
    "BBG000DB3KT1": "WLTW", "BBG000FLHZZ2": "WCN (Progressive Waste)", "BBG0076WG2V1": "QSR",
    "BBG01KJQM3Y8": "SIRI (New Sirius)", "BBG000VPGNR2": "CHTR (New Charter)",
}


def _anchor(r: dict) -> date:
    return date.fromisoformat(r["last_trade_date"] or r["delist_filing_date"] or r["delist_date"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "issuer_role")
    p.add_argument("--repo", type=Path, default=ROOT)
    args = p.parse_args(argv)
    repo, out = args.repo, args.out
    secs, eras, cusips, history, _ = b5._securities(repo)
    dl = defaultdict(list)
    for r in b5._read(repo / "output/delistings.csv"):
        dl[r["sec_id"]].append(r)
    contract = {r["sec_id"]: r for r in b5._read(repo / "output/contract/delistings.csv")}
    by_cik: dict[str, list[str]] = defaultdict(list)
    for sid, s in secs.items():
        if s["issuer_cik"]:
            by_cik[s["issuer_cik"]].append(sid)
    core = set(CASES) | set(SUPPORT)
    needed = core | {x for sid in core for x in by_cik.get(secs[sid]["issuer_cik"], [])}
    ciks = sorted({int(secs[sid]["issuer_cik"]) for sid in needed if secs[sid]["issuer_cik"]})
    anchors = {sid: [_anchor(r) for r in dl.get(sid, [])] for sid in CASES}

    # fails rows: a case's CUSIPs, and its tickers' rows near its anchors; the others' span and descriptions
    local = b5.LocalFtd(repo / "cache/sec_data/ftd")
    ftd = FtdIndex.load(local, *FTD_WINDOW, cusips={c for sid in needed for c in cusips.get(sid, [])})
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
    for sid in CASES:
        tickers = {k.split("@")[0] for k in eras[sid]} | set(b5._line_tickers(eras[sid], history[sid]))
        for day in anchors[sid]:
            lo, hi = day - timedelta(days=ROWS_DAYS), day + timedelta(days=ROWS_DAYS)
            near = FtdIndex.load(local, lo, min(hi, AS_OF), symbols=tickers)
            rows.update(r for t in tickers for r in near.by_symbol(t))

    # EDGAR
    edgar = EdgarClient(repo / "cache/edgar", user_agent="build_issuer_role_fixtures fixtures@example.com",
                        today=AS_OF)
    case_ciks = {int(secs[sid]["issuer_cik"]) for sid in CASES if secs[sid]["issuer_cik"]}
    windows = defaultdict(list)
    for sid in CASES:
        for day in anchors[sid]:
            windows[int(secs[sid]["issuer_cik"])].append((day - timedelta(days=TEXT_DAYS[0]),
                                                           day + timedelta(days=TEXT_DAYS[1])))
    issuers, raws, texts = {}, {}, {}
    for cik in ciks:
        sub = b5._cached(edgar.submissions, cik, default={}) or {}
        every = b5._cached(edgar.recent_filings, cik, default=[]) or []
        first = min((f for f in every if f.filing_date), key=lambda f: f.filing_date, default=None)
        filings = [f for f in every if b5.KEPT_FORMS.match(f.form or "") or f is first]
        issuers[str(cik)] = {"name": sub.get("name", ""), "formerNames": sub.get("formerNames") or [],
                             "tickers": sub.get("tickers") or [], "exchanges": sub.get("exchanges") or [],
                             "sic": str(sub.get("sic") or ""),
                             "filings": [[f.accession, f.form, f.filing_date, f.report_date, f.items, f.primary_doc]
                                         for f in filings]}
        if cik not in case_ciks:
            continue
        f25 = [f for f in filings if f.form in FORM25_FORMS]
        for f in f25:
            raw = b5._cached(edgar.fetch_filing_raw, cik, f.accession, default="")
            if raw:
                raws[f.accession] = raw
        for f in filings:
            day = b5._day(f.filing_date)
            near = any(lo <= day <= hi for lo, hi in windows[cik])
            if f.form.startswith("8-K") and (near or {"1.03", "3.01"} & f.item_set):
                text = b5._cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                if text:
                    texts[f.accession] = text
            elif f.form in ANNUAL_FORMS and any(abs((day - b5._day(g.filing_date)).days) <= COVER_DAYS for g in f25):
                text = b5._cached(edgar.fetch_filing_text, cik, f.accession, f.primary_doc, default="")
                if text:
                    texts[f.accession] = text[:12000]

    # OpenFIGI: every CUSIP job a successor link may send
    jobs = set()
    for sid in CASES:
        own = set(cusips.get(sid, []))
        cik = secs[sid]["issuer_cik"]
        named = {c for acc, t in texts.items() if any(acc == f[0] for f in issuers.get(cik, {}).get("filings", []))
                 for c in text_cusips([t])}
        named |= {c for acc, raw in raws.items() for c in text_cusips([raw])
                  if any(acc == f[0] for f in issuers.get(cik, {}).get("filings", []))}
        tickers = {k.split("@")[0] for k in eras[sid]}
        later = {r.cusip for r in rows if r.symbol in tickers and r.cusip not in own
                 and any(day.isoformat() <= r.date <= (day + timedelta(days=15)).isoformat() for day in anchors[sid])}
        jobs |= (named | later) - own
    figi = {}
    for c in sorted(jobs):
        job = cusip_job(c)
        h = hashlib.sha1(json.dumps({"kind": "mapping", "payload": job}, sort_keys=True).encode()).hexdigest()
        path = repo / "cache/openfigi" / f"{h}.json"
        ans = json.loads(path.read_text()) if path.exists() else {"error": "not cached"}
        # the US venues' rows only: all that `figi_resolution.us_candidates` reads
        figi[c] = ans if "error" in ans else {"data": [r for r in ans.get("data") or [] if r.get("exchCode") in US_EXCH]}

    # MIDAS and halts, for every symbol the cases' sightings carry, around their anchors
    symbols = {sid: {k.split("@")[0] for k in eras[sid]} | {r.symbol for c in cusips.get(sid, [])
                                                              for r in ftd.by_cusip(c)} for sid in CASES}
    midas: dict[str, dict[str, list[str]]] = {}
    midas_dir = repo / "cache/sec_data/midas"
    quarters = sorted(p.name[:7] for p in midas_dir.glob("*_q*.json.gz"))
    for path in sorted(midas_dir.glob("*_q*.json.gz")):
        summary = json.loads(gzip.decompress(path.read_bytes()))
        for sid in CASES:
            for t in symbols[sid]:
                for d in summary.get(t, []):
                    if any(abs((b5._day(d) - a).days) <= 120 for a in anchors[sid]):
                        midas.setdefault(path.name[:7], {}).setdefault(t, []).append(d)
    halts: dict[str, list[list[str]]] = {}
    wanted = {t for v in symbols.values() for t in v}
    for path in sorted((repo / "cache/nasdaq_halts").glob("*.xml")):
        for h in b5._cached(parse_halts_rss, path.read_bytes(), default=[]):
            if h.reason == "D" and h.symbol in wanted:
                halts.setdefault(path.stem, []).append([h.symbol, h.name, h.market, h.reason, h.halt_date.isoformat(),
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
                           "cusips": cusips.get(sid, []), "line_tickers": b5._line_tickers(eras[sid], history[sid]),
                           "listed": any(r["valid_to"] == "" for r in history.get(sid, [])),
                           "eras": {k: sorted(v, key=lambda o: o[1]) for k, v in sorted(eras[sid].items())},
                           "history": [[r["ticker"], r["valid_from"], r["valid_to"]] for r in history.get(sid, [])]}
    cases = {}
    for sid, note in CASES.items():
        c = contract.get(sid, {})
        terms = {}
        for r in dl.get(sid, []):
            if r["bucket"] == "merger" and c.get("value_rule") in ("stock", "cash", "cash_plus_stock"):
                terms[r["delist_date"]] = [c["cash_per_share"], c["stock_ratio"], c["price_ticker"]]
        cases[sid] = {"note": note, "terms": terms}
    data = {"as_of": AS_OF.isoformat(), "cases": cases, "support": SUPPORT, "securities": securities}
    for name, payload in (("cases.json", data), ("figi.json", figi), ("midas.json", {"quarters": quarters,
                                                                                      "days": midas}),
                          ("halts.json", halts)):
        write_atomic(out / name, json.dumps(payload, indent=1, sort_keys=True) + "\n")
    edgar_json = json.dumps({"issuers": issuers, "raws": raws, "texts": texts}, sort_keys=True) + "\n"
    write_atomic(out / "edgar.json.gz", gzip.compress(edgar_json.encode(), mtime=0))
    print(f"{len(cases)} cases, {len(securities)} securities, {len(rows)} fails rows, {len(ciks)} CIKs, "
          f"{len(raws)} Form 25 raws, {len(texts)} texts, {len(figi)} FIGI answers, "
          f"{sum(len(v) for q in midas.values() for v in q.values())} MIDAS days, "
          f"{sum(len(v) for v in halts.values())} halts -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Build the fixtures**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/build_issuer_role_fixtures.py`
Expected: about 40 seconds, then
`40 cases, 81 securities, 45032 fails rows, 51 CIKs, 74 Form 25 raws, 104 texts, 20 FIGI answers, 3171 MIDAS days, 2 halts -> .../tests/fixtures/issuer_role`.
The planning build gave these sha1 sums (`shasum tests/fixtures/issuer_role/*`); the build is deterministic and does
not depend on the code under change, so a difference means the local cache changed since planning (stop and report
it):

```
0485837119fce1efd5a063d53ea0e88e6ca53ab3  cases.json
7b5e5750091b7c7790217674cb81ffb87b9cd576  edgar.json.gz
89136a04d08aee249e679a2bcfa8da75a80e68ba  figi.json
47d4cdf90c088d2fd942de42dca479738e73ea3c  ftd_rows.csv.gz
61f05fbd4c572861e496326d0c6acb24c8f9cb58  halts.json
d211f1badec4b0fe57918ad35c62875c4cb784df  midas.json
```

- [ ] **Step 3: Write the harness**

Create `tests/issuer_role_cases.py`:

```python
"""Sub-plan 5c's real cases, replayed offline: tests/fixtures/issuer_role/ (built once from the local caches by
scripts/build_issuer_role_fixtures.py) holds each case's security, the securities a successor link may name and the
other securities of their issuers, their fails rows, and the EDGAR, OpenFIGI, MIDAS and Nasdaq-halt answers.
`outcome(sec_id)` runs the run's own code over them: stage 5 (`pipeline._context_builder`,
`delistings.DelistingFinder`), stage 8b when it exists (`pipeline._r1_continuations`, the terms the committed
contract published standing in for the LLM's), and stage 9 (`pipeline._find_successors`,
`pipeline._link_successors`; no full-text search: the fixture has none)."""
from __future__ import annotations

import csv
import gzip
import inspect
import io
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from delist_detection import pipeline
from delist_detection.added_securities import AddedAcquirer, AddedSecurity
from delist_detection.classifier import DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import Delisting, DelistingFinder
from delist_detection.edgar import EdgarSubmission
from delist_detection.figi_resolution import security_kind
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.history import ticker_sightings
from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.manifest import StageMeter
from delist_detection.midas import MidasClient
from delist_detection.nasdaq_halts import Halt, NasdaqHaltClient
from delist_detection.observations import Observation, TickerEra
from delist_detection.payout_gate import GatedPayouts
from delist_detection.review_triage import ReviewItem
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "issuer_role"
DATA = json.loads((FIX / "cases.json").read_text())
EDGAR = json.loads(gzip.decompress((FIX / "edgar.json.gz").read_bytes()))
FIGI = json.loads((FIX / "figi.json").read_text())
MIDAS = json.loads((FIX / "midas.json").read_text())
HALTS = json.loads((FIX / "halts.json").read_text())
AS_OF = date.fromisoformat(DATA["as_of"])


class FixtureEdgar:
    """The cases' EDGAR answers as the fixture recorded them. A raw or a text the cache lacked reads as "" (as an
    unreadable filing); `texts_read` lists every 8-K text read."""

    def __init__(self) -> None:
        self.texts_read: list[str] = []

    def company_tickers(self):
        return {}

    def submissions(self, cik, fresh_after=None):
        d = EDGAR["issuers"].get(str(int(cik)))
        return {} if d is None else {k: d[k] for k in ("name", "formerNames", "tickers", "exchanges", "sic")}

    def recent_filings(self, cik):
        return [EdgarSubmission(*f) for f in EDGAR["issuers"].get(str(int(cik)), {}).get("filings", [])]

    def fetch_filing_raw(self, cik, accession):
        return EDGAR["raws"].get(accession, "")

    def fetch_filing_text(self, cik, accession, primary_doc):
        self.texts_read.append(accession)
        return EDGAR["texts"].get(accession, "")

    def company_search_atom(self, name, form_type="25-NSE"):
        return []


class FixtureFigi:
    """OpenFIGI's cached answers to the CUSIP jobs a successor link may send; any other job is an error answer."""

    def map(self, jobs, *, use_cache=True):
        return [FIGI.get(j.get("idValue", ""), {"error": "not in the fixture"}) for j in jobs]


class FixtureMidas(MidasClient):
    """MIDAS's per-quarter days with exchange volume, as the fixture recorded them for the case tickers."""

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
def world() -> tuple[dict[str, Security], dict[str, AddedSecurity], dict[str, list[str]], FtdIndex]:
    """The fixture's observed securities, the acquirers and successors the committed run added (as acquirers: a
    ticker and a span), every security's CUSIPs, and the fails rows as one index."""
    securities = {sid: _security(sid) for sid, d in DATA["securities"].items() if d["observed"]}
    added: dict[str, AddedSecurity] = {}
    for sid, d in DATA["securities"].items():
        if not d["observed"] and d["history"]:
            ticker, first, _ = d["history"][0]
            added[sid] = AddedAcquirer(Security(sid, d["issuer_cik"], d["share_class"], d["name"], d["security_type"],
                                                False, d["figi_source"]), ticker, date.fromisoformat(first))
    cusips = {sid: list(d["cusips"]) for sid, d in DATA["securities"].items()}
    with io.TextIOWrapper(gzip.open(FIX / "ftd_rows.csv.gz"), encoding="utf-8", newline="") as fh:
        rows = [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"], float(r["price"]) if r["price"] else None)
                for r in csv.DictReader(fh)]
    return securities, added, cusips, FtdIndex(rows)


def clients(edgar: FixtureEdgar | None = None) -> pipeline.Clients:
    edgar = edgar or FixtureEdgar()
    return pipeline.Clients(edgar=edgar, resolver=None, classifier=DelistClassifier(edgar, TickerResolver(edgar),
                                                                                      today=AS_OF),
                            figi=FixtureFigi(), ftd_client=None, midas=FixtureMidas(), halts=FixtureHalts(),
                            as_of=AS_OF)


def find(sec_id: str, c: pipeline.Clients) -> tuple[list[Delisting], list[ReviewItem]]:
    """Stage 5: the finder's delistings and review items for the case."""
    securities, _, cusips, ftd = world()
    sightings = {sid: ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    build = pipeline._context_builder(securities, sightings, pipeline._IssuerAnswers({}, {}, {}, set()), ftd, cusips)
    finder = DelistingFinder(c.edgar, c.classifier, midas=c.midas, halts=c.halts)
    return finder.find(build(securities[sec_id], DATA["securities"][sec_id]["listed"]))


def _payouts(sec_id: str, found: list[Delisting]) -> pipeline._Payouts:
    """Stage 8's answer for the case, the terms the committed contract published for its merger rows standing in
    for the LLM's (none passed the gate: the gate is not replayed)."""
    terms = DATA["cases"][sec_id]["terms"]
    llm = {}
    for d in found:
        t = terms.get(d.delist_date)
        if d.record.bucket is CrspBucket.MERGER and t is not None:
            cash, ratio, ticker = (float(t[0]) if t[0] else None), (float(t[1]) if t[1] else None), t[2] or None
            llm[d.key] = MergerTerms("cash_and_stock" if cash and ratio else "stock" if ratio else "cash", cash,
                                     ratio, None, ticker, "high", "fixture", "")
    _, added, _, _ = world()
    return pipeline._Payouts({}, llm, GatedPayouts({}, {}, {}, {}, {}), {}, dict(added), [])


def after(sec_id: str, *, edgar: FixtureEdgar | None = None) -> list[Delisting]:
    """The case's delistings after stage 9: stage 5's, rewritten by stage 8b (when it exists) and linked by stage 9."""
    c = clients(edgar)
    found, _ = find(sec_id, c)
    securities, _, cusips, ftd = world()
    sightings = {sid: ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    ctx = pipeline._RunContext(c, AS_OF, lambda *a: None, 1, StageMeter(lambda *a: None))
    payouts = _payouts(sec_id, found)
    acquirers = dict(payouts.added)
    r1 = getattr(pipeline, "_r1_continuations", None)
    if r1 is not None:
        acquirers |= r1(ctx, found, securities, sightings, payouts, pipeline.Overrides()).added
    kw = {"sec_cusips": cusips} if "sec_cusips" in inspect.signature(pipeline._find_successors).parameters else {}
    pipeline._link_successors(found, pipeline._find_successors(ctx, found, securities, sightings, acquirers, {}, ftd,
                                                               **kw))
    return found


def outcome(sec_id: str, **kw) -> list[tuple]:
    """What the run gives the case: each delisting as (delist_date, bucket, CRSP code, successor sec_id, how the
    successor was found), in order."""
    return [(d.delist_date, d.record.bucket.value, d.record.crsp_code, d.record.successor_sec_id or "",
             (d.record.evidence or {}).get("successor_by", "")) for d in after(sec_id, **kw)]
```

- [ ] **Step 4: Write the real-case test**

Create `tests/test_issuer_role_cases.py` (every outcome below is what the planning prototype gave on this fixture:
"before" today's code, each rule's outcome once that task's rule is built):

```python
"""Sub-plan 5c's real cases: what the run gives each security of tests/fixtures/issuer_role/ (built once, offline,
from the local caches by scripts/build_issuer_role_fixtures.py), through the run's own stage-5, stage-8b and
stage-9 code (tests/issuer_role_cases.py). A case the sub-plan moves (MOVES) keeps its outcome from before 5c until
the task that builds a rule of its sequence adds the rule to RULES_DONE; it then has that rule's outcome (CWENA
moves twice: stage 5 makes it an exchange transfer, stage 9 links it). A guard (STAY) keeps its outcome throughout.
An outcome is the case's delistings after stage 9, each (delist_date, bucket, CRSP code, successor sec_id, how the
successor was found). The fixture's world holds only the cases' and their successors' issuers, so a link needing
a unique candidate can find one the full run does not (MSG 2015's same_issuer link): the full run is Task 9's
replay."""
from __future__ import annotations

import pytest

from tests import issuer_role_cases as ic

# The rules of sub-plan 5c built so far, in task order; each task adds its own
RULES_DONE: set[str] = set()
ORDER = ("stage5", "r1", "links")

# sec_id -> (its outcome before 5c, [(rule, its outcome once the rule is built), ...] in ORDER)
MOVES = {
    'CIK1126294-COMMON': ([('2010-12-03', 'merger', 231, '', '')], [('stage5', [('2010-12-03', 'exchange_transfer', 304, '', '')])]),   # RRI 2010
    'CIK1363851-COMMON': ([('2012-07-24', 'merger', 231, '', '')], [('stage5', [('2012-07-24', 'exchange_transfer', 304, 'BBG000KBQZ88', 'same_issuer')])]),   # SXCI 2012
    'CIK1308161-COMMON': ([('2009-01-08', 'exchange_transfer', 304, 'CIK1308161-COMMON', ''), ('2013-07-01', 'merger', 231, '', '')], [('stage5', [('2009-01-08', 'exchange_transfer', 304, 'CIK1308161-COMMON', ''), ('2013-07-01', 'exchange_transfer', 304, '', '')])]),   # NWS-A 2013
    'CIK1308161-CLASS-A': ([('2013-06-28', 'merger', 231, '', '')], [('stage5', [('2013-06-28', 'exchange_transfer', 304, '', '')])]),   # NCRA 2013
    'CIK38079-COMMON': ([('2015-01-25', 'merger', 200, '', '')], [('stage5', [('2015-01-25', 'compliance_failure', 570, '', '')])]),   # FST 2014
    'BBG000BQHGR6': ([('2026-09-28', 'unknown', None, '', '')], [('stage5', [('2026-09-28', 'exchange_transfer', 304, '', '')])]),   # OKE 2026
    'BBG000BHBK84': ([('2017-09-11', 'merger', 231, '', '')], [('r1', [('2017-09-11', 'exchange_transfer', 304, 'BBG00BN961G4', 'new_issuer')])]),   # DOW 2017
    'BBG000BPQD31': ([('2020-11-26', 'merger', 231, '', '')], [('r1', [('2020-11-26', 'exchange_transfer', 304, 'BBG00Y4RQNH4', 'new_issuer')])]),   # MYL 2020
    'BBG000CGQ6M4': ([('2018-11-10', 'merger', 231, '', '')], [('r1', [('2018-11-10', 'exchange_transfer', 304, 'BBG00GVR8YQ9', 'new_issuer')])]),   # PX 2018
    'BBG000CHWP52': ([('2022-04-18', 'merger', 200, '', '')], [('r1', [('2022-04-18', 'exchange_transfer', 304, 'BBG011386VF4', 'same_issuer_class')])]),   # DISCA 2022
    'BBG000F2XXP2': ([('2023-05-31', 'merger', 231, '', '')], [('r1', [('2023-05-31', 'exchange_transfer', 304, 'BBG01GJ3NY88', 'new_issuer')])]),   # SBGI 2023
    'BBG000G0PPW3': ([('2016-12-11', 'merger', 231, '', '')], [('r1', [('2016-12-11', 'exchange_transfer', 304, 'BBG00D3CHRC0', 'new_issuer')])]),   # AMSG 2016
    'BBG000VMWHH5': ([('2022-04-18', 'merger', 200, '', '')], [('r1', [('2022-04-18', 'exchange_transfer', 304, 'BBG011386VF4', 'same_issuer_class')])]),   # DISCK 2022
    'BBG001YMS0B8': ([('2015-07-12', 'merger', 231, '', '')], [('r1', [('2015-07-12', 'exchange_transfer', 304, 'BBG005CPNTQ2', 'new_issuer')])]),   # KRFT 2015
    'BBG01HMFL081': ([('2025-12-25', 'merger', 200, '', '')], [('r1', [('2025-12-25', 'exchange_transfer', 304, 'BBG01YY256K1', 'new_issuer')])]),   # LLYVA 2025
    'BBG01HMFLTN1': ([('2025-12-25', 'merger', 200, '', '')], [('r1', [('2025-12-25', 'exchange_transfer', 304, 'BBG01YYX1Z14', 'new_issuer')])]),   # LLYVK 2025
    'CIK104207-COMMON': ([('2015-01-09', 'merger', 231, '', '')], [('r1', [('2015-01-09', 'exchange_transfer', 304, 'BBG000BWLMJ4', 'new_issuer')])]),   # WAG 2014
    'CIK944868-COMMON': ([('2009-11-29', 'merger', 231, '', '')], [('r1', [('2009-11-29', 'exchange_transfer', 304, 'BBG000FL1TC8', 'new_issuer')])]),   # DTV 2009
    'BBG000BD4VG8': ([('2017-07-15', 'exchange_transfer', 304, '', '')], [('links', [('2017-07-15', 'exchange_transfer', 304, 'BBG00GBVBK51', 'new_issuer')])]),   # BHI 2017
    'BBG000BFTJ91': ([('2015-12-21', 'exchange_transfer', 304, '', '')], [('links', [('2015-12-21', 'exchange_transfer', 304, 'BBG000BFT2L4', 'same_issuer_class')])]),   # CMCSK 2015
    'BBG000J453J8': ([('2019-05-12', 'exchange_transfer', 304, '', '')], [('links', [('2019-05-12', 'exchange_transfer', 304, 'BBG000SSC5C9', 'own_registration')])]),   # CCO 2019
    'BBG000MJRJJ2': ([('2023-08-24', 'exchange_transfer', 304, '', '')], [('links', [('2023-08-24', 'exchange_transfer', 304, 'BBG01HTMDZ54', 'new_issuer')])]),   # HHC 2023
    'CIK48898-CLASS-B': ([('2016-01-03', 'exchange_transfer', 304, '', '')], [('links', [('2016-01-03', 'exchange_transfer', 304, 'BBG000BLK267', 'same_issuer_class')])]),   # HUB-B 2015
    'BBG004P33PN3': ([('2026-05-11', 'unknown', None, '', '')], [('stage5', [('2026-05-11', 'exchange_transfer', 304, '', '')]), ('links', [('2026-05-11', 'exchange_transfer', 304, 'BBG008LJ4TF3', 'same_issuer_class')])]),   # CWENA 2026
}

# the guards: securities whose outcome no rule of 5c changes
STAY = {
    'BBG000BBLK04': [('2016-01-14', 'merger', 233, '', '')],   # TW 2016: Willis existed (5,347 days)
    'BBG000BDKN87': [('2010-02-26', 'merger', 231, '', '')],   # BNI 2010: renamed after its acquisition
    'BBG000BDXVW8': [('2010-10-14', 'merger', 231, '', '')],   # CAL 2010: 1.05 UAL
    'BBG000BHW628': [('2016-06-11', 'merger', 231, '', '')],   # WCN 2016: Progressive Waste existed (4,125 days)
    'BBG000BJ9D07': [('2016-09-08', 'merger', 233, '', '')],   # ROVI 2016: TiVo Corp is not in the run, no search here
    'BBG000BJCFP1': [('2013-03-11', 'merger', 231, '', '')],   # JEF 2013: the LLM's 0.81 LUK
    'BBG000BM1RP0': [('2009-08-14', 'merger', 233, '', '')],   # FCL 2009: 1.084 New Alpha
    'BBG000BSVZM9': [('2009-11-04', 'merger', 231, '', '')],   # SGP 2009: $10.50 and 0.5767 New Merck
    'BBG000BT0093': [('2024-09-10', 'exchange_transfer', 304, 'BBG01KJQM3Y8', 'same_issuer')],   # SIRI 2024
    'BBG000BVW841': [('2007-11-02', 'merger', 231, '', '')],   # TXU 2007: an LBO, renamed after
    'BBG000K1T0M8': [('2025-05-17', 'merger', 231, '', '')],   # LGFA 2025: the target of New Lionsgate
    'BBG000PYZSR8': [('2016-05-18', 'exchange_transfer', 304, 'BBG000VPGNR2', 'same_issuer')],   # CHTR 2016
    'BBG003444577': [('2014-12-25', 'merger', 231, '', '')],   # BKW 2014: 0.99 QSR and $3.00
    'BBG0038K9G41': [('2018-03-19', 'merger', 200, '', '')],   # LVNTA 2018: GCI Liberty existed (8,442 days)
    'CIK1011006-COMMON': [('2017-06-12', 'exchange_transfer', 304, '', '')],   # AABA 2017: no statement, no link
    'CIK1469372-CLASS-A': [('2015-08-03', 'exchange_transfer', 304, 'CIK1469372-CLASS-A', ''), ('2015-10-02', 'exchange_transfer', 304, 'BBG000NS03H7', 'same_issuer')],   # MSG 2015
}


def _expected(sec_id: str) -> list[tuple]:
    before, steps = MOVES[sec_id]
    done = [o for rule, o in steps if rule in RULES_DONE]
    return done[-1] if done else before


@pytest.mark.parametrize("sec_id", sorted(MOVES), ids=lambda s: ic.DATA["cases"][s]["note"].split(":")[0])
def test_a_case_moves_when_its_rule_is_built(sec_id):
    assert ic.outcome(sec_id) == _expected(sec_id)


@pytest.mark.parametrize("sec_id", sorted(STAY), ids=lambda s: ic.DATA["cases"][s]["note"].split(":")[0])
def test_a_guard_keeps_its_outcome(sec_id):
    assert ic.outcome(sec_id) == STAY[sec_id]


def test_every_case_of_the_fixture_is_a_move_or_a_guard():
    assert set(MOVES) | set(STAY) == set(ic.DATA["cases"]) and not set(MOVES) & set(STAY)
    assert all(rule in ORDER for _, steps in MOVES.values() for rule, _ in steps)
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_issuer_role_cases.py`
Expected: PASS (41 tests, about 6 seconds). A failing case means the fixture or the harness differs from the
planning build: compare the case's `ic.outcome(...)` with its table row, and report; never change a row to make it
pass.

Then the full suite: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: 2242 passed, 240 xfailed.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_issuer_role_fixtures.py tests/issuer_role_cases.py tests/test_issuer_role_cases.py tests/fixtures/issuer_role
git commit -m "Real-case fixtures for the issuer role and successor links, built offline from the caches, and their stage 5, 8b and 9 replay (sub-plan 5c)"
```

---

### Task 2: `exchange_terms`, what a filing says the registrant's own shares became

Tier: standard.

**Files:**
- Create: `src/delist_detection/exchange_terms.py`, `tests/test_exchange_terms.py`

**Interfaces:**
- Consumes: `evidence.names_between(sub, lo, hi)`, `figi_resolution.class_letter(share_class)`; in the tests,
  Task 1's `tests.issuer_role_cases.EDGAR` and `FixtureEdgar`.
- Produces: `exchange_terms.Statement(ratio, cash, subject, target, sentence, subject_letters, target_letter,
  distribution)`; `exchange_terms.OwnExchange(ratio, cash, target, target_names, target_letter, target_own, sentence,
  ambiguous=False, special_dividends=())` with property `one_for_one`; `statements(text) -> list[Statement]`;
  `own_statements(texts, *, names, class_letter="", class_words=()) -> list[Statement]`;
  `own_exchange(texts, *, names, class_letter="", class_words=()) -> OwnExchange | None` (`class_letter=None`: any
  class); `acquires(texts, *, names) -> str`; `distributes(texts, *, names) -> str`; `defined_terms(text) -> dict`;
  `own_words(names) -> set[str]`; `parties(phrase) -> list[str]`; `normalize(text) -> str`;
  `registrant_names(sub, before: date, security_name="") -> list[str]`;
  `class_of(share_class, name) -> (letter, words)`; `read_texts(edgar, cik, filings, days, form25=None) -> list[str]`;
  constants `TEXT_BEFORE_DAYS` 3, `TEXT_AFTER_DAYS` 10, `NAMES_BEFORE_DAYS` 365.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_exchange_terms.py`:

```python
"""exchange_terms: what a filing says the registrant's own shares became (sub-plan 5c, ruling R1). The real cases
read their texts from tests/fixtures/issuer_role/ (built once from the local caches)."""
from __future__ import annotations

from datetime import date

import pytest

from delist_detection import exchange_terms as X
from delist_detection.form25 import parse_form25
from tests import issuer_role_cases as ic


def _text(acc: str) -> str:
    if acc in ic.EDGAR["raws"]:
        return parse_form25(ic.EDGAR["raws"][acc], accession=acc, form="25-NSE", filing_date="2000-01-01").notice_text
    return ic.EDGAR["texts"][acc]


# case -> (texts, the registrant's names before the event, class letter, class words) and what own_exchange reads:
# (ratio, cash, ambiguous, target letter, target names the registrant, a name the target carries, special dividends)
REAL = {
    "BHI": ((["0001193125-17-220863", "0000876661-17-000381"], ["BAKER HUGHES INC"], "", ()),
            (1.0, False, False, "A", False, "BHGE", (17.5,))),
    "HHC": ((["0001104659-23-090461"], ["Howard Hughes Corp"], "", ()),
            (1.0, False, False, "", False, "Howard Hughes Holdings Inc.", ())),
    "CMCSK": ((["0000950103-15-009516"], ["COMCAST CORP", "COMCAST SPECIAL CORP CLASS A"], "A", ("SPECIAL",)),
              (1.0, False, False, "A", True, None, ())),
    "HUB-B": ((["0001193125-15-412174"], ["HUBBELL INC", "HUBBELL INC. CL B"], "B", ()),
              (1.0, False, False, "", True, None, ())),
    "CWENA": ((["0001104659-26-053557"], ["Clearway Energy, Inc."], "A", ()),
              (1.0, False, False, "C", True, None, ())),
    "DISCA": ((["0001193125-22-103051"], ["Discovery, Inc."], "A", ()), (1.0, False, False, "", False, "WBD", ())),
    "DISCK": ((["0001193125-22-103051"], ["Discovery, Inc."], "C", ()), (1.0, False, False, "", False, "WBD", ())),
    "MYL": ((["0001193125-20-298224"], ["Mylan N.V."], "", ()), (1.0, False, False, "", False, "Viatris", ())),
    "SBGI": ((["0001193125-23-158935"], ["SINCLAIR BROADCAST GROUP INC"], "A", ()),
             (1.0, False, False, "A", False, "Sinclair, Inc.", ())),
    "WAG": ((["0001193125-14-457669"], ["WALGREEN CO"], "", ()), (1.0, False, False, "", False, "WBA", ())),
    "DTV": ((["0001104659-09-066017"], ["DIRECTV GROUP INC"], "", ()), (1.0, False, False, "A", False, "DIRECTV", ())),
    "ROVI": ((["0001193125-16-704222"], ["Rovi Corp"], "", ()),
             (1.0, False, False, "", False, "Titan Technologies Corporation", ())),
    "OKE": ((["0000876661-26-000770"], ["ONEOK INC /NEW/"], "", ()), (1.0, False, False, "", False, None, ())),
    "LLYVA": ((["0001104659-25-121236"], ["Liberty Media Corp"], "A", ()),
              (1.0, False, False, "A", False, "Liberty Live Holdings", ())),
    "DOW": ((["0001193125-17-274845"], ["DOW CHEMICAL CO /DE/"], "", ()),
            (1.0, False, False, "", False, "DowDuPont", ())),
    "KRFT": ((["0001193125-15-244355"], ["Kraft Foods Group, Inc."], "", ()),
             (1.0, False, False, "", False, "The Kraft Heinz Company", (16.5,))),
    "CCO": ((["0001193125-19-135029"], ["Clear Channel Outdoor Holdings, Inc."], "A", ()),
            (1.0, False, False, "", True, None, ())),
    "FCL": ((["0000950123-09-028243"], ["Foundation Coal Holdings, Inc."], "", ()),
            (1.084, False, False, "", False, None, ())),
    "CHTR": ((["0001193125-16-596195"], ["CHARTER COMMUNICATIONS, INC. /MO/"], "A", ()),
             (0.9042, False, False, "A", False, None, ())),
    "SIRI": ((["0001104659-24-098260"], ["SIRIUS XM HOLDINGS INC."], "", ()), (0.1, False, False, "", False, None, ())),
}


@pytest.mark.parametrize("case", sorted(REAL))
def test_a_real_filing_says_what_the_securitys_own_shares_became(case):
    (accs, names, letter, words), (ratio, cash, ambiguous, target_letter, target_own, name, dividends) = REAL[case]
    own = X.own_exchange([_text(a) for a in accs], names=names, class_letter=letter, class_words=words)
    assert own is not None
    assert (own.ratio, own.cash, own.ambiguous, own.target_letter, own.target_own, own.special_dividends) == (
        ratio, cash, ambiguous, target_letter, target_own, dividends)
    if name is not None:
        assert name in own.target_names
    assert own.one_for_one is (ratio == 1.0 and not cash and not ambiguous)


def test_another_partys_ratio_beside_the_own_one_is_not_read_as_the_securitys():
    """DOW 2017: DuPont's 1.2820 is in the same 8-K; DTV 2009: LEI's 1.11130; SIRI 2024: Liberty Media's 0.8375."""
    for acc, names in (("0001193125-17-274845", ["DOW CHEMICAL CO /DE/"]), ("0001104659-09-066017", ["DIRECTV GROUP INC"]),
                       ("0001104659-24-098260", ["SIRIUS XM HOLDINGS INC."])):
        ratios = {st.ratio for st in X.own_statements([_text(acc)], names=names, class_letter="")}
        assert ratios <= {1.0, 0.1}, (acc, ratios)


def test_a_multi_step_deals_intermediate_one_for_one_is_read_but_the_llm_decides():
    """JEF 2013: Jefferies became New Jefferies one for one before the 0.81 Leucadia exchange; the reader reads the
    one-for-one (stage 8b needs the LLM's terms to agree, and they say 0.81)."""
    own = X.own_exchange([_text("0001193125-13-087969")], names=["JEFFERIES GROUP INC /DE/"], class_letter="")
    assert own is not None and own.one_for_one


@pytest.mark.parametrize("acc,names,expected", [
    ("0000950123-10-111604", ["RRI ENERGY INC"], "Mirant"),
    ("0001193125-12-296100", ["SXC Health Solutions Corp."], "Catalyst"),
    ("0001193125-14-450724", ["FOREST OIL CORP"], "issued an aggregate of 79,241,916"),
], ids=["RRI", "SXCI", "FST"])
def test_an_acquirer_whose_own_shares_were_not_exchanged(acc, names, expected):
    texts = [_text(acc)]
    assert X.own_exchange(texts, names=names, class_letter=None) is None
    assert expected in X.acquires(texts, names=names)


def test_a_distributor_whose_holders_kept_their_shares():
    """News Corp 2013: one new News Corp share for every four of the Company's, kept: a distribution, no exchange."""
    texts = [_text("0001193125-13-281456")]
    assert X.own_exchange(texts, names=["NEWS CORP"], class_letter=None) is None
    assert "for every four shares" in X.distributes(texts, names=["NEWS CORP"])


def test_a_target_is_no_acquirer_and_a_new_company_named_like_it_is_another():
    """'New Lionsgate' is another company than the registrant 'Old Lionsgate'; a target's own exchange stops the
    role reading (CCO's 'Old CCOH' is the registrant)."""
    text = ('Legacy LG Studios shareholders received, in exchange for each LG Studios common share they held, '
            'one New Lionsgate Common Share.')
    assert X.acquires([text], names=["LIONS GATE ENTERTAINMENT CORP"]) == ""
    cco = [_text("0001193125-19-135029")]
    assert X.own_exchange(cco, names=["Clear Channel Outdoor Holdings, Inc."], class_letter=None) is not None


@pytest.mark.parametrize("sentence,ratio,cash", [
    ("Each outstanding share of the Company's common stock was converted into the right to receive one share of "
     "common stock of Holdco and $10.00 in cash.", 1.0, True),
    ("Each outstanding share of the Company's common stock was converted into one share of Holdco common stock, "
     "par value $0.01 per share, with cash paid in lieu of fractional shares.", 1.0, False),
    ("Each share of the Company's common stock was converted into one (1) share of Holdco common stock and a "
     "special cash dividend of $2.50 per share.", 1.0, False),
    ("Each share of the Company's common stock was converted into 1.2500 shares of Parent common stock.", 1.25, False),
    ("Each share of the Company's common stock was exchanged on a one-for-one basis for an equivalent share of "
     "Holdco common stock.", 1.0, False),
    ("Each share of the Company's common stock converted into an equal number of shares of Holdco common stock.",
     1.0, False),
], ids=["cash", "par-and-lieu", "special-dividend", "ratio", "basis", "equal-number"])
def test_the_consideration_of_a_sentence(sentence, ratio, cash):
    own = X.own_exchange([sentence], names=["Acme Corp"], class_letter="")
    assert own is not None and (own.ratio, own.cash) == (ratio, cash)


def test_another_class_or_a_merger_subs_shares_are_not_the_securitys():
    text = ("Each share of Merger Sub common stock was converted into one share of the surviving corporation. Each "
            "share of the Company's Class B common stock was converted into one share of Holdco Class B common stock.")
    assert X.own_exchange([text], names=["Acme Corp"], class_letter="A") is None
    assert X.own_exchange([text], names=["Acme Corp"], class_letter="B").target_letter == "B"


def test_two_own_readings_that_disagree_are_ambiguous():
    texts = ["Each share of the Company's common stock was converted into one share of Holdco common stock.",
             "Each share of the Company's common stock was converted into 0.81 shares of Parent common stock."]
    own = X.own_exchange(texts, names=["Acme Corp"], class_letter="")
    assert own is not None and own.ambiguous and not own.one_for_one


def test_cash_paid_only_for_another_class_is_not_the_securitys():
    """Hubbell 2015: $28.00 for each Class A share; Class B got one new share and no cash."""
    hub = [_text("0001193125-15-412174")]
    assert X.own_exchange(hub, names=["HUBBELL INC"], class_letter="B").cash is False
    assert X.own_exchange(hub, names=["HUBBELL INC"], class_letter="A").cash is True


def test_the_registrants_names_are_read_from_before_the_event():
    """Schering-Plough became "Merck & Co." the day of the merger: before it, it is read by its old name."""
    sub = {"name": "MERCK & CO., INC.", "formerNames": [{"name": "SCHERING PLOUGH CORP", "from": "1994-01-01",
                                                          "to": "2009-11-03"}]}
    assert X.registrant_names(sub, date(2009, 11, 4), "SCHERING PLOUGH CORP") == ["SCHERING PLOUGH CORP",
                                                                                  "SCHERING PLOUGH CORP"]
    assert X.class_of("CLASS A", "COMCAST SPECIAL CORP CLASS A") == ("A", ("SPECIAL",))
    assert X.class_of("COMMON", "ONEOK INC") == ("", ())


def test_read_texts_reads_the_8ks_around_each_day_and_the_notice():
    edgar = ic.FixtureEdgar()
    filings = edgar.recent_filings(1039684)
    raw = ic.EDGAR["raws"]["0000876661-26-000770"]
    f25 = parse_form25(raw, accession="0000876661-26-000770", form="25-NSE", filing_date="2026-09-18")
    texts = X.read_texts(edgar, 1039684, filings, [date(2026, 9, 9)], f25)
    assert "0001193125-26-387972" in edgar.texts_read and texts[-1] == f25.notice_text


def test_a_cash_take_private_whose_insiders_rolled_over_is_a_target_not_an_acquirer():
    """Continental Resources 2022: the public shares got $74.28 in cash; the Hamm family's rollover shares became
    the surviving company's. Its own exchange is a cash one, and no other party's shares became the registrant's."""
    text = ("Each share of common stock of the Company issued and outstanding (other than the Rollover Shares) was "
            "converted into the right to receive $74.28 in cash. Also at the Effective Time, the Rollover Shares "
            "owned by the Hamm Family were converted into an identical number of newly issued shares of the Company, "
            "as the surviving corporation.")
    own = X.own_exchange([text], names=["CONTINENTAL RESOURCES INC"], class_letter=None)
    assert own is not None and (own.ratio, own.cash, own.one_for_one) == (0.0, True, False)
    assert X.acquires([text], names=["CONTINENTAL RESOURCES INC"]) == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_exchange_terms.py`
Expected: FAIL at collection: `ImportError: cannot import name 'exchange_terms' from 'delist_detection'`.

- [ ] **Step 3: Write the reader**

Create `src/delist_detection/exchange_terms.py`:

```python
"""What a filing says the registrant's own shares became (sub-plan 5c; spec 2026-10-03-diagnosis-truth-fixes, ruling
R1: a continuation is one new share per old share and no cash in the exchange).

An 8-K that reports a merger, a holding-company reorganization, a reclassification or a split-off states the
conversion: "each outstanding share of Baker Hughes common stock was converted into the right to receive one share
of BHGE's Class A common stock", "each share of SBG's Class A common stock ... was exchanged on a one-for-one basis
for an equivalent share of New Sinclair's Class A common stock", "the holders of outstanding shares of DIRECTV Group
common stock received one share of DIRECTV Class A common stock for each share". `statements` reads every such
statement of one filing (pure); `own_exchange` keeps those about the security's own shares -- the subject's first
party is the registrant (an EDGAR name it carried before the event, a defined term that stands for one, "Old"/
"Legacy" before it, "the Company", "its", "our") and the class is the security's -- and says what they became: the
ratio, whether cash was paid in the exchange (par values, cash in lieu of fractional shares and a special dividend
are not consideration: operator ruling 2026-10-04), the target clause, the names it carries and the class letter it
names. A distribution (the holders kept their shares: a record date, "for every four shares") is no exchange.

Two other roles a registrant can have in such a filing, for the end-of-era resolver's rule 1: `acquires` (another
party's shares became the registrant's -- Mirant into RRI Energy, Catalyst into SXC -- or the registrant issued its
shares to the other party under the merger agreement: Forest Oil to Sabine) and `distributes` (its holders received
another company's shares and kept theirs: News Corp's 2013 separation). `read_texts` gathers the filings one ending's
reading uses; `registrant_names` and `class_of` give the names and the class it is read against.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .evidence import names_between
from .figi_resolution import class_letter

TEXT_BEFORE_DAYS, TEXT_AFTER_DAYS = 3, 10       # the registrant's 8-Ks filed this close to the ending's anchor
NAMES_BEFORE_DAYS = 365                          # the registrant's EDGAR names in force this long before the anchor

_QUOTES = str.maketrans({"“": '"', "”": '"', "’": "'", "‘": "'", " ": " "})
_NUMBER_WORDS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}
# "one (1) share", "one-tenth (0.1) of a share": the number in parentheses is the reading
_WORD_NUMBER = re.compile(r"\b(?:one|two|three|four|five|one-(?:half|third|quarter|tenth))\s*\((\d*\.?\d+)\)", re.I)
_SAME_NUMBER = re.compile(r"^(?:an?\s+(?:equal|like|equivalent|identical)\s+number\s+of|the\s+same\s+number\s+of"
                          r"|an?\s+equivalent|an?)$", re.I)
_ENUMERATOR = re.compile(r"\(\s*(?:[ivx]{1,4}|\d{1,2}|[a-h])\s*\)")       # "(i)", "(ii)", "(1)", "(a)"
_SENTENCE_END = re.compile(r"(?<!\bInc)(?<!\bCorp)(?<!\bCo)(?<!\bLtd)(?<!\bNo)(?<!\bU\.S)(?<!\bN\.V)(?<!\bS\.A)"
                           r"(?<!\bL\.P)(?<!\bplc)(?<!\bMr)(?<!\bMs)(?<!\bJr)[.;]\s+(?=[A-Z•\"])|\s•\s")
_PAREN = re.compile(r"\((?:[^()]|\([^()]*\))*\)")
_DEFINED = re.compile(r'\(\s*(?:the\s+|each,?\s+an?\s+)?"\s*([^"()]{1,40}?)\s*"\s*(?:,[^()]{0,40})?\)')
# 'Howard Hughes Holdings Inc., a Delaware corporation and direct wholly owned subsidiary of the Company ("Holdco")':
# the appositive between a name and its defined term
_APPOSITIVE = re.compile(r",\s+an?\s+(?:(?:newly[- ]formed|direct|indirect|wholly[- ]owned|[A-Z][a-z]+)\s+){0,4}"
                         r"(?:corporation|company|limited\s+liability\s+company|public\s+limited|subsidiary|entity|"
                         r"holding)", re.I)
_QTY = (r"(?P<qty>one|two|three|1(?:\.0+)?|\d*\.\d+|\d+|an?\s+(?:equal|like|equivalent|identical)\s+number\s+of"
        r"|the\s+same\s+number\s+of|an?\s+equivalent|an?)")
_SHARE = (r"(?:\s+of\s+an?)?(?:\s+(?:validly[- ]issued|fully[- ]paid|non-?assessable|newly[- ]issued|new|and|,))*"
          r"\s*(?:(?:common|ordinary)\s+)?(?:shares?|ADSs?|American\s+Depositary\s+Shares?)\b")
# the consideration: "into one share", "for an equivalent share", "received 1.11130 shares", "receiving one share"
_CONSIDERATION = re.compile(r"\b(?P<lead>into|for|receiv(?:e|ed|es|ing))\s+(?:the\s+right\s+to\s+receive\s+)?"
                            + _QTY + _SHARE, re.I)
_BASIS = re.compile(r"on\s+a\s+one[- ](?:for|to)[- ]one\s+basis|share[- ]for[- ]share", re.I)
_VERB = re.compile(r"convert|exchang|reclassif|redeem|redemption|receiv", re.I)
_FOR_EACH = re.compile(r"\bfor\s+each\s+(?:outstanding\s+|issued\s+and\s+outstanding\s+)?(?:share|shares)\s+of\s+",
                       re.I)
_FOR_EVERY = re.compile(r"\bfor\s+every\s+\w+\s+shares?\s+of\s+(?P<subj>[^;.]{0,160})", re.I)
_DISTRIBUTION = re.compile(r"\bRecord\s+Date\b|\bholders?\s+of\s+record\b|\bof\s+record\s+(?:as\s+of|on|at)\b"
                           r"|\b(?:the\s+)?Distribution\b|\bdistributed\b|\bpro\s+rata\b|\bfor\s+every\b")
_SHARES_OF = re.compile(r"\b(?:shares?|stock)\s+of\s+", re.I)
_EACH = re.compile(r"\beach\s+", re.I)
_LETTER = re.compile(r"\b(?:Class|Series)\s+([A-Z])(?![\w-])")
# a subject that is not the class's public shares: an award, another security, a merger subsidiary's shares, the
# shares an insider rolled over (Continental Resources 2022: "the Rollover Shares owned by the Hamm Family")
_NOT_SHARES = re.compile(r"\b(?:options?|restricted|awards?|warrants?|preferred|RSUs?|units?|debentures?|notes?|"
                         r"convertible|rights?|exchangeable|Merger\s+Sub\w*|Purchaser|Rollover)\b", re.I)
# a cash consideration: "converted into the right to receive $74.28 in cash"
_CASH_CONSIDERATION = re.compile(r"\b(?:into|for)\s+(?:the\s+right\s+to\s+receive\s+)?(?:an\s+amount\s+(?:in\s+cash\s+)?"
                                 r"equal\s+to\s+)?(?:US)?\$\s?\d[\d.,]*", re.I)
_PAR = re.compile(r"(?:,\s*)?(?:with(?:out)?\s+)?(?:no\s+)?(?:a\s+)?(?:par|nominal)\s+value(?:\s+of)?"
                  r"(?:\s+(?:US)?\$\s?[\d.,]+(?:\s+\d/\d)?)?(?:\s+per\s+share)?"
                  r"|(?:US)?\$\s?[\d.,]+\s+(?:par|nominal)\s+value(?:\s+per\s+share)?", re.I)
_LIEU = re.compile(r"(?:with\s+|and\s+|plus\s+)?(?:any\s+)?cash\s+(?:being\s+)?(?:paid\s+|payment\s+|payable\s+)?"
                   r"(?:to\s+[^;]{0,60}?)?in\s+lieu\s+of\s+(?:any\s+|issuing\s+)?fraction\w*(?:\s+(?:of\s+a\s+)?shares?)?"
                   r"|in\s+lieu\s+of\s+(?:any\s+)?fraction\w*(?:\s+shares?)?", re.I)
# "and a special one-time cash dividend of $17.50": a dividend, never consideration (operator ruling 2026-10-04)
_DIVIDEND_LEG = re.compile(r"(?:,?\s*(?:and|plus)\s+)?an?\s+special\s+(?:one-time\s+)?(?:cash\s+)?dividend"
                           r"(?:\s+(?:of|in\s+the\s+amount\s+of|equal\s+to))?\s+(?:US)?\$\s?[\d.,]+(?:\s+per\s+share)?",
                           re.I)
_CASH = re.compile(r"\$\s?\d|\bin\s+cash\b|\bcash\s+(?:consideration|payment|amount)\b|\b(?:and|plus)\s+cash\b", re.I)
_CASH_FOR_SHARE = re.compile(r"\breceiv\w*\s+(?:cash\s+in\s+the\s+amount\s+of\s+)?(?:an\s+amount\s+in\s+cash\s+"
                             r"(?:equal\s+to\s+)?)?\$\s?[\d.,]+[^;]{0,80}?\bfor\s+each\s+share\s+of\s+"
                             r"(?P<subj>[^;]{0,120})", re.I)
_SPECIAL_DIVIDEND = re.compile(r"special\s+(?:one-time\s+)?(?:cash\s+)?dividend[^.;]{0,80}?\$\s?(\d[\d,]*(?:\.\d+)?)"
                               r"|\$\s?(\d[\d,]*(?:\.\d+)?)\s+per\s+share[^.;]{0,40}?special\s+(?:one-time\s+)?"
                               r"(?:cash\s+)?dividend", re.I)
# Forest Oil 2014: "the Company issued an aggregate of 79,241,916 Common Shares ... to Sabine Investor Holdings ...
# pursuant to the Amended Merger Agreement"
_ISSUED = re.compile(r"\bthe\s+Company\s+issued\s+(?:an\s+aggregate\s+of\s+)?[\d,]+\s+(?:\w+\s+){0,3}shares\b[^.;]{0,240}?"
                     r"\b(?:Merger|Combination|Contribution|Exchange)\s+Agreement\b", re.I)
# A target clause ends where the sentence goes on to something else
_TARGET_END = re.compile(r",?\s+(?:having|effective|which|that|with|subject|pursuant|and|plus|as|in\s+accordance)\b|;",
                         re.I)
_CAP_RUN = re.compile(r"[A-Z][A-Za-z0-9&'.-]*(?:\s+(?:of\s+|&\s+)?[A-Z][A-Za-z0-9&'.-]*)*")
_CLASS_WORDS = {"CLASS", "SERIES", "COMMON", "STOCK", "SHARE", "SHARES", "ORDINARY", "PREFERRED", "VOTING",
                "NON-VOTING", "CAPITAL", "SPECIAL", "ADS", "ADSS", "AMERICAN", "DEPOSITARY", "EFFECTIVE", "TIME",
                "UNITS", "UNIT"}
_NOT_PARTIES = {"THE", "THE COMPANY", "COMPANY", "EACH", "UPON", "AT", "PURSUANT", "IN", "AS", "ON", "ALL", "ANY"}
_NEW_TERM = re.compile(r"^(?:New|Holdco|Parent|Successor)\b")
_OLD_TERM = re.compile(r"^(?:Old|Legacy|Former|Predecessor)\s+")
_OWN_PRONOUN = re.compile(r"\b(?:the\s+Company|Company's|our|its|we)\b", re.I)
_OWN_SKIP = {"THE", "NEW", "OLD", "INC", "CORP", "CO", "COMPANY", "HOLDINGS", "GROUP", "LTD", "PLC", "NV", "LLC",
             "SA", "AG", "SE", "LP", "TRUST", "INTERNATIONAL", "AMERICAN", "UNITED", "NATIONAL", "FIRST", "GENERAL",
             "ENERGY", "FINANCIAL", "CLASS", "COMMON", "SERIES", "STOCK"}
_CLASS_MODIFIERS = ("SPECIAL", "NON-VOTING", "LIMITED VOTING")


@dataclass(frozen=True)
class Statement:
    """One conversion statement of a filing: each share of `subject` became `ratio` shares of `target`, with cash
    or not; `distribution` when its holders kept their shares (a record date, "for every", "the Distribution")."""
    ratio: float
    cash: bool
    subject: str
    target: str
    sentence: str
    subject_letters: frozenset[str] = frozenset()
    target_letter: str = ""
    distribution: bool = False


@dataclass(frozen=True)
class OwnExchange:
    """What the security's own shares became (module docstring): `ratio` shares per share, cash in the exchange or
    not, the target clause, the names it carries (defined terms expanded: "Holdco" is "Howard Hughes Holdings
    Inc."), the class letter it names (the security's own for "the corresponding series"), whether it names the
    registrant itself (a reclassification into another class of the same issuer), the sentence, whether several
    own-share statements disagree (`ambiguous`) and the special dividends the filings name (never consideration)."""
    ratio: float
    cash: bool
    target: str
    target_names: tuple[str, ...]
    target_letter: str
    target_own: bool
    sentence: str
    ambiguous: bool = False
    special_dividends: tuple[float, ...] = ()

    @property
    def one_for_one(self) -> bool:
        """One share per share, no cash, one reading (R1)."""
        return self.ratio == 1.0 and not self.cash and not self.ambiguous


def normalize(text: str) -> str:
    """One line, straight quotes, "one (1)" as "1" and "one-tenth (0.1)" as "0.1"."""
    t = re.sub(r"\s+", " ", (text or "").translate(_QUOTES))
    return _WORD_NUMBER.sub(r"\1", t)


def defined_terms(text: str) -> dict[str, str]:
    """A filing's defined terms and the names they stand for: 'Howard Hughes Holdings Inc., a Delaware corporation
    ... ("Holdco")' gives {"Holdco": "Howard Hughes Holdings Inc."}; the name is the run of capitalized words right
    before the parenthesis (or before its appositive), with a legal suffix after a comma ("Sinclair Broadcast
    Group, Inc.")."""
    out: dict[str, str] = {}
    t = normalize(text)
    for m in _DEFINED.finditer(t):
        alias = m.group(1).strip()
        before = t[max(0, m.start() - 200):m.start()].rstrip(" ,")
        appositive = list(_APPOSITIVE.finditer(before))
        if appositive:
            before = before[:appositive[-1].start()].rstrip(" ,")
        runs = list(_CAP_RUN.finditer(before))
        if not runs or runs[-1].end() < len(before) - 2:
            continue
        name = runs[-1].group(0).strip()
        if len(runs) > 1 and re.fullmatch(r"(?:Inc|Corp|Co|Ltd|LLC|L\.P|N\.V|plc|S\.A)\.?", name):
            name = before[runs[-2].start():].strip()
        if name and alias.upper() != "COMPANY" and name != alias:
            out.setdefault(alias, name)
    return out


def _qty(s: str) -> float | None:
    s = s.strip().lower()
    if s in _NUMBER_WORDS:
        return _NUMBER_WORDS[s]
    if _SAME_NUMBER.match(s):
        return 1.0
    try:
        return float(s)
    except ValueError:
        return None


def _clauses(text: str) -> list[tuple[str, str]]:
    """(clause, its sentence) for every clause of a normalized text: sentences split at their ends, then at their
    enumerators ("(i)", "(2)")."""
    return [(c, s) for s in _SENTENCE_END.split(text) for c in _ENUMERATOR.split(s) if c.strip()]


def _subject_phrase(before: str) -> str:
    """The subject phrase: what follows the last "shares of"/"stock of" before the consideration ("each share of the
    Company's Class A common stock ..."), else what follows the last "each" ("each Mylan Share issued ...")."""
    hits = list(_SHARES_OF.finditer(before))
    if hits:
        return before[hits[-1].end():]
    hits = list(_EACH.finditer(before))
    return before[hits[-1].end():] if hits else before[-200:]


def statements(text: str) -> list[Statement]:
    """Every conversion statement of one filing's text (module docstring), parentheticals set aside."""
    out: list[Statement] = []
    for clause, sentence in _clauses(normalize(text)):
        bare = re.sub(r"\s+", " ", _PAREN.sub(" ", clause))
        shares = list(_CONSIDERATION.finditer(bare))
        cash_only = [c for c in _CASH_CONSIDERATION.finditer(bare)
                     if not any(s.start() <= c.start() < s.end() for s in shares)]
        matches = sorted(shares + cash_only, key=lambda m: m.start())
        prev = 0
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(bare)
            rest, before, prev = bare[m.end():end], bare[prev:m.start()], m.end()
            if m.re is _CASH_CONSIDERATION:          # "converted into the right to receive $74.28 in cash"
                if _VERB.search(before[-160:]):
                    subject = _subject_phrase(before)
                    out.append(Statement(0.0, True, subject.strip(" ,"), "", sentence,
                                         frozenset(_LETTER.findall(subject)), "", bool(_DISTRIBUTION.search(sentence))))
                continue
            ratio = _qty(m.group("qty"))
            if ratio is None:
                continue
            each = _FOR_EACH.search(rest)
            if m.group("lead").lower().startswith("receiv") and each is not None:
                subject, target = rest[each.end():][:160], rest[:each.start()]   # "received N of T for each of S"
            else:
                subject, target = _subject_phrase(before), rest
            if not _VERB.search(before[-160:] + " " + m.group("lead")):
                continue
            consideration = _DIVIDEND_LEG.sub(" ", _LIEU.sub(" ", _PAR.sub(" ", m.group(0) + target)))
            letters = _LETTER.findall(target)
            out.append(Statement(ratio, bool(_CASH.search(consideration)), subject.strip(" ,"), target.strip(" ,"),
                                 sentence, frozenset(_LETTER.findall(subject)), letters[0] if letters else "",
                                 bool(_DISTRIBUTION.search(sentence))))
    return out


def own_words(names: Iterable[str]) -> set[str]:
    """The words that name the registrant: each name's first word that is not a filler or a legal suffix (two
    letters or more: "SXC", "BJ"), and its first two such words joined ("LIONS GATE" is LIONSGATE). A later word
    of the name ("HEALTH" in "SXC Health Solutions") is too common to name it."""
    words: set[str] = set()
    for n in names:
        toks = [w for w in re.findall(r"[A-Z0-9][A-Z0-9&'-]*", (n or "").upper().replace("'S", "").replace(".", ""))
                if w not in _OWN_SKIP]
        if toks and len(toks[0]) >= 2:
            words.add(toks[0])
        if len(toks) >= 2:
            words.add(toks[0] + toks[1])
    return words


def _names_own(phrase: str, own: set[str]) -> bool:
    """A phrase names the registrant: one of its words, possessive or plural ("Walgreens", "SBG's"), not after "New"
    ("New Lionsgate" is another company than "Old Lionsgate")."""
    up = phrase.upper()
    for w in own:
        for m in re.finditer(rf"(?<![A-Z0-9]){re.escape(w)}(?:S|'S)?(?![A-Z0-9])", up):
            if not re.search(r"\bNEW\s+$", up[max(0, m.start() - 6):m.start()]):
                return True
    return False


def parties(phrase: str) -> list[str]:
    """The capitalized names a phrase carries, class words dropped ("BHGE's Class A common stock" -> ["BHGE"])."""
    out = []
    for m in _CAP_RUN.finditer(phrase):
        words = [w for w in m.group(0).replace("'s", "").split()
                 if w.upper().strip(".,") not in _CLASS_WORDS and not re.fullmatch(r"[A-Z]-?\d?", w)]
        name = " ".join(words).strip(" ,.")
        if name and name.upper() not in _NOT_PARTIES:
            out.append(name)
    return out


def _first_party_own(head: str, own: set[str]) -> bool | None:
    """Whose shares a subject is: True for the registrant ("the Company's", "its", one of its words, "Old"/"Legacy"
    before one), False when its first named party is another ("Liberty Media's ... Liberty SiriusXM common stock"),
    None when it names nobody."""
    names = parties(head)
    pronoun = _OWN_PRONOUN.search(head)
    if not names:
        return True if pronoun else None
    first = re.sub(r"^(?:Old|Legacy|Former|Predecessor)\s+", "", names[0])
    if pronoun and pronoun.start() < head.find(names[0]):
        return True
    return _names_own(first, own)


def _class_ok(st: Statement, letter: str | None, class_words: Sequence[str]) -> bool:
    """The subject is the security's class: no letter, or the security's (`letter` None: any class); and it names
    each word that sets the security's class apart ("Class A Special"), and none the security lacks."""
    if letter is None:
        return True
    if letter and st.subject_letters and letter not in st.subject_letters:
        return False
    if not letter and len(st.subject_letters) == 1:
        return False
    head = st.subject[:120].upper()
    mods = {w.upper() for w in class_words}
    return all((w in head) == (w in mods) for w in _CLASS_MODIFIERS)


def _terms_and_own(texts: Sequence[str], names: Sequence[str]) -> tuple[dict[str, str], set[str]]:
    terms: dict[str, str] = {}
    for t in texts:
        for k, v in defined_terms(t).items():
            terms.setdefault(k, v)
    own = own_words(names)
    # a defined term that stands for the registrant ("SBG", "Old CCOH": also without its "Old")
    aliases = [k for k, v in terms.items() if _names_own(v, own) and not _NEW_TERM.match(k)]
    own |= {k.upper() for k in aliases} | {_OLD_TERM.sub("", k).upper() for k in aliases}
    return terms, own


def own_statements(texts: Iterable[str], *, names: Sequence[str], class_letter: str | None = "",
                   class_words: Sequence[str] = ()) -> list[Statement]:
    """The exchange statements of `texts` (not distributions) about the security's own shares (module docstring)."""
    texts = [normalize(t) for t in texts if t]
    _, own = _terms_and_own(texts, names)
    out = []
    for t in texts:
        for st in statements(t):
            head = st.subject[:120]
            if st.distribution or _NOT_SHARES.search(head):
                continue
            if _first_party_own(head, own) is not False and _class_ok(st, class_letter, class_words):
                if _first_party_own(head, own) is None and not _OWN_PRONOUN.search(st.sentence) \
                        and not _names_own(st.sentence, own):
                    continue
                out.append(st)
    return out


def _cash_for_class(texts: Iterable[str], own: set[str], letter: str | None) -> bool:
    """A filing pays cash for each share of the security's class ("each holder of the Company's Class A common
    stock is entitled to receive cash in the amount of $28.00 for each share of Class A Common Stock held")."""
    for t in texts:
        for m in _CASH_FOR_SHARE.finditer(t):
            subj = re.split(r"\s+(?:held|and|or)\b|[,;(]", m.group("subj"), maxsplit=1)[0]
            letters = set(_LETTER.findall(subj))
            if letter and letters and letter not in letters:
                continue
            if not letter and letters:
                continue
            if _first_party_own(subj, own) is not False:
                return True
    return False


def own_exchange(texts: Iterable[str], *, names: Sequence[str], class_letter: str | None = "",
                 class_words: Sequence[str] = ()) -> OwnExchange | None:
    """What the security's own shares became (module docstring): `names` the registrant's names before the event
    (`registrant_names`), `class_letter` its class letter ("" for a plain common, None for any class),
    `class_words` the words that set its class apart (`class_of`). None when no filing states it."""
    texts = [normalize(t) for t in texts if t]
    found = own_statements(texts, names=names, class_letter=class_letter, class_words=class_words)
    if not found:
        return None
    terms, own = _terms_and_own(texts, names)
    st = found[0]
    named = _PAR.sub(" ", st.target)
    cut = _TARGET_END.search(named)
    named = named[:cut.start()] if cut else named
    target_names: list[str] = []
    for p in parties(named):
        target_names.append(p)
        target_names += [v for k, v in terms.items() if k.upper() == p.upper() or k.upper() in p.upper().split()]
    letter = st.target_letter or (class_letter or "" if re.search(r"corresponding\s+(?:series|class)", st.target, re.I)
                                  else "")
    target_own = bool(_OWN_PRONOUN.search(named)) or not parties(named)
    dividends = sorted({float((m.group(1) or m.group(2)).replace(",", ""))
                        for t in texts for m in _SPECIAL_DIVIDEND.finditer(t)})
    return OwnExchange(st.ratio, st.cash or _cash_for_class(texts, own, class_letter), st.target,
                       tuple(dict.fromkeys(target_names)), letter, target_own, st.sentence,
                       len({(s.ratio, s.cash) for s in found}) > 1, tuple(dividends))


def acquires(texts: Iterable[str], *, names: Sequence[str]) -> str:
    """The sentence in which another party's shares became the registrant's ("each outstanding share of common stock
    of Mirant was converted into the right to receive 2.835 ... shares of our common stock") or the registrant
    issued its shares to the other party under the merger agreement (Forest Oil 2014), else ""."""
    texts = [normalize(t) for t in texts if t]
    _, own = _terms_and_own(texts, names)
    for t in texts:
        for st in statements(t):
            head = st.subject[:120]
            if st.distribution or _NOT_SHARES.search(head) or _first_party_own(head, own) is not False:
                continue
            target = st.target[:160]
            if re.search(r"\b(?:our|its)\b|\bthe\s+Company\b", target) or (
                    _names_own(target, own) and not re.search(r"\bNew\s", target)):
                return st.sentence[:300]
        m = _ISSUED.search(t)
        if m is not None:
            return t[m.start():m.end()][:300]
    return ""


def distributes(texts: Iterable[str], *, names: Sequence[str]) -> str:
    """The sentence in which the registrant's holders received another company's shares and kept their own ("one
    share of News Corp Class A common stock for every four shares of the Company's Class A common stock held"),
    else ""."""
    texts = [normalize(t) for t in texts if t]
    _, own = _terms_and_own(texts, names)
    for t in texts:
        for m in _FOR_EVERY.finditer(t):
            subj = m.group("subj")[:120]
            if _first_party_own(subj, own):
                return t[max(0, m.start() - 200):m.end()][:300]
    return ""


def registrant_names(sub: dict | None, before: date, security_name: str = "") -> list[str]:
    """The registrant's names before the event: the EDGAR names it carried in the NAMES_BEFORE_DAYS up to two days
    before `before` (the earliest day the reading looks at: a registrant renamed at the closing, Schering-Plough
    as "Merck", Foundation Coal as "Alpha Natural Resources", is read by its old name), else its current one, then
    the security's own name."""
    names = names_between(sub, before - timedelta(days=NAMES_BEFORE_DAYS), before - timedelta(days=2)) \
        if isinstance(sub, dict) else []
    if not names and isinstance(sub, dict) and sub.get("name"):
        names = [sub["name"]]
    return [*names, security_name] if security_name else names


def class_of(share_class: str | None, name: str | None) -> tuple[str, tuple[str, ...]]:
    """The class letter a security's statements must name ("" for a plain common) and the words that set its class
    apart in its name ("COMCAST SPECIAL CORP CLASS A": ("SPECIAL",))."""
    up = (name or "").upper()
    return class_letter(share_class) or "", tuple(w for w in _CLASS_MODIFIERS if w in up)


def read_texts(edgar, cik: int, filings: Sequence, days: Iterable[date], form25=None) -> list[str]:
    """The texts one ending's reading uses: the registrant's 8-Ks (8-K12B and 8-K12G3 included) filed in
    [day - TEXT_BEFORE_DAYS, day + TEXT_AFTER_DAYS] of any of `days` (the ending's anchor, and the 8-K that decided
    it), in filing order, then the EX-99.25 notice of its matched Form 25 (`form25`, a `form25.Form25`). An
    unreadable text reads as ""."""
    windows = [(d - timedelta(days=TEXT_BEFORE_DAYS), d + timedelta(days=TEXT_AFTER_DAYS)) for d in days if d]
    out: list[str] = []
    for f in sorted(filings, key=lambda f: (f.filing_date, f.accession)):
        try:
            day = date.fromisoformat(f.filing_date[:10])
        except ValueError:
            continue
        if f.form.startswith("8-K") and any(lo <= day <= hi for lo, hi in windows):
            out.append(edgar.fetch_filing_text(cik, f.accession, f.primary_doc) or "")
    if form25 is not None and getattr(form25, "notice_text", ""):
        out.append(form25.notice_text)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_exchange_terms.py`
Expected: PASS (39 tests). Then the full suite: 2281 passed, 240 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/exchange_terms.py tests/test_exchange_terms.py
git commit -m "exchange_terms: what a filing says the registrant's own shares became, and its acquirer and distributor roles (sub-plan 5c, R1)"
```

---

### Task 3: A ticker symbol "changed from X to Y" names Y

Tier: cheap.

RRI Energy's 2010 8-K says "our ticker symbol was changed from “RRI” to “GEN,”": `_TEXT_SYMBOL` reads RRI (the old
symbol, which the line follow drops as its own), so stage 4b never scans GEN (research section 2).

**Files:**
- Modify: `src/delist_detection/line_follow.py`
- Test: `tests/test_line_follow.py`

**Interfaces:**
- Consumes: Task 1's `tests.issuer_role_cases.EDGAR` (RRI's 8-K text 0000950123-10-111604).
- Produces: `line_follow.text_symbols(texts)` also returns the symbol after "to" in "symbol … from X to Y".

- [ ] **Step 1: Write the failing test**

Append to `tests/test_line_follow.py`:

```python
# --- sub-plan 5c: "changed from X to Y" names Y ---

def test_a_symbol_changed_from_one_ticker_to_another_names_the_new_one():
    """RRI Energy's 2010 8-K: "our ticker symbol was changed from “RRI” to “GEN,”" -- the first pattern alone reads
    RRI, the old one, which the line follow drops as its own; GEN is the line's new symbol."""
    from delist_detection.line_follow import text_symbols  # noqa: E402
    from tests import issuer_role_cases as ic  # noqa: E402
    assert "GEN" in text_symbols([ic.EDGAR["texts"]["0000950123-10-111604"]])
    assert "XYZ" in text_symbols(['the trading symbol of the common stock changed from "ABC" to "XYZ" today'])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_line_follow.py -k changed_from`
Expected: FAIL (`assert 'GEN' in {'RRI'}`).

- [ ] **Step 3: Implement**

In `src/delist_detection/line_follow.py`, replace

```python
_STATE_TAG = re.compile(r"\s*/[A-Z]+/?\s*$")          # EDGAR's "AETNA INC /PA/"
# "the CUSIP number changed to 316645100": a nine-character CUSIP within 60 characters of the word
```

with

```python
# "our ticker symbol was changed from “RRI” to “GEN,”": the symbol after "to" (sub-plan 5c; the first pattern
# alone reads RRI, the old one)
_TEXT_SYMBOL_CHANGE = re.compile(r"(?i:symbol)[^.;]{0,60}?\b(?i:from)\s+[\"“'(]?[A-Z]{1,5}[\"”')]?,?\s+(?i:to)\s+"
                                 r"[\"“'(]?([A-Z]{1,5})\b(?![a-z])")
_STATE_TAG = re.compile(r"\s*/[A-Z]+/?\s*$")          # EDGAR's "AETNA INC /PA/"
# "the CUSIP number changed to 316645100": a nine-character CUSIP within 60 characters of the word
```

and replace

```python
    """The ticker symbols an 8-K's text names as the stock's new one ("under the ticker symbol "CHX""),
    upper-case."""
    return {m.group(1) for t in texts for m in _TEXT_SYMBOL.finditer(t or "")}
```

with

```python
    """The ticker symbols an 8-K's text names as the stock's new one ("under the ticker symbol "CHX"", "changed
    from "RRI" to "GEN""), upper-case."""
    return {m.group(1) for t in texts for rx in (_TEXT_SYMBOL, _TEXT_SYMBOL_CHANGE) for m in rx.finditer(t or "")}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_line_follow.py tests/test_line_follow_cases.py`
Expected: PASS (5a's real cases unchanged). Then the full suite: 2282 passed, 240 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/line_follow.py tests/test_line_follow.py
git commit -m "The line follow reads a ticker symbol changed from X to Y as Y (sub-plan 5c, RRI to GEN)"
```

---

### Task 4: Stage 5, the registrant's role (rule 1) and R1 without an item code

Tier: standard.

Before end-of-era branches 3 and 4 the classifier asks whether the registrant survived the transaction its 8-K items
call a merger (RRI, SXCI, NWS-A, NCRA, FST); before the no-evidence default it asks whether its filings state a
one-for-one exchange of its own class, with no cash (CWENA, OKE). Both readings are Task 2's.

**Files:**
- Modify: `src/delist_detection/end_of_era.py`, `src/delist_detection/classifier.py`,
  `src/delist_detection/review_triage.py`
- Test: `tests/test_end_of_era.py`, `tests/test_review_triage.py`, `tests/test_issuer_role_cases.py`

**Interfaces:**
- Consumes: Task 2's `exchange_terms.own_exchange`, `acquires`, `distributes`, `registrant_names`, `class_of`,
  `read_texts`.
- Produces: `end_of_era.EraSignals.survived: str = ""`; `end_of_era.merges(s: EraSignals) -> bool`;
  `DelistClassifier._matched_form25(cik, sub) -> Form25 | None`, `_survived(cik, name, filings, observed, era,
  form25) -> str`, `_one_for_one(cik, name, filings, days, form25) -> OwnExchange | None`; the record flag
  `r1_continuation`; `evidence["survived"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_end_of_era.py`:

```python
# --- sub-plan 5c, rule 1: a registrant that survived the transaction ---
from delist_detection.end_of_era import merges  # noqa: E402


def test_a_survivor_takes_no_merger_branch_and_goes_on_to_the_notice_or_the_continued_filings():
    """RRI Energy acquired Mirant (5.01), Forest Oil issued its shares to Sabine (2.01 with a proxy) and was then
    removed for its price: neither is a merger ending."""
    acquirer = "each outstanding share of common stock of Mirant was converted into ... shares of our common stock"
    v = resolve(_s(item_filed={"5.01": "2020-11-02"}, survived=acquirer), 231)
    assert (v.branch, v.crsp_code, v.bucket, v.reason) == ("continued_filings", 304, CrspBucket.EXCHANGE_TRANSFER,
                                                           CONTINUED)
    v = resolve(_s(item_filed={"2.01": "2020-11-02", "3.01": "2020-11-09"}, merger_filing="DEFM14A 2020-10-01",
                   deficiency_notice="8-K 2020-11-09", survived="the Company issued an aggregate of ..."), 200)
    assert (v.branch, v.crsp_code, v.bucket) == ("delisting_notice", 570, CrspBucket.COMPLIANCE_FAILURE)


def test_merges_says_when_branch_3_or_4_would_decide():
    assert merges(_s(item_filed={"5.01": "2020-11-02"}))
    assert merges(_s(item_filed={"2.01": "2020-11-02"}, delist_filing="25-NSE 2020-11-03"))
    assert not merges(_s(item_filed={"2.01": "2020-11-02"}))
    assert not merges(_s(item_filed={"5.01": "2020-11-02"}, successor_filing="8-K12B 2020-11-03"))
    assert not merges(_s(item_filed={"5.01": "2020-11-02"}, trading_after=True))
```

In `tests/test_issuer_role_cases.py`, replace

```python
RULES_DONE: set[str] = set()
```

with

```python
RULES_DONE: set[str] = {"stage5"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_end_of_era.py tests/test_issuer_role_cases.py`
Expected: FAIL: `ImportError: cannot import name 'merges'`; once that exists, the 7 cases of rule `stage5` (RRI,
SXCI, NWS-A, NCRA, FST, OKE, CWENA) fail with their old outcomes.

- [ ] **Step 3: The resolver's survived signal**

In `src/delist_detection/end_of_era.py`, replace

```python
   or before it: a Chapter 11 asset sale is a liquidation (470; 5g sub-rule 2, built
   in sub-plan 5b);
```

with

```python
   or before it: a Chapter 11 asset sale is a liquidation (470; 5g sub-rule 2, built
   in sub-plan 5b);
   branches 3 and 4 never fire for a registrant that survived the transaction (`survived`,
   sub-plan 5c rule 1: its own shares were not exchanged, and it acquired another party
   or distributed another company's shares to its holders): the resolution goes on to 5;
```

replace

```python
    bankruptcy_filing: str = ""       # "8-K <date>" of the first 8-K in the window whose item 1.03 text confirms
```

with

```python
    bankruptcy_filing: str = ""       # "8-K <date>" of the first 8-K in the window whose item 1.03 text confirms
    survived: str = ""                # the sentence that says the registrant acquired or distributed (rule 1, 5c)
```

replace

```python
def resolve(s: EraSignals, items_code: int | None) -> EraVerdict:
```

with

```python
def merges(s: EraSignals) -> bool:
    """Whether branch 3 or 4 would decide (a change in control, or a completed acquisition with a merger filing
    or a Form 25, and neither branch 1 nor branch 2 first): the only signals for which the classifier reads
    whether the registrant survived (`survived`)."""
    if s.trading_after or s.successor_filing:
        return False
    return "5.01" in s.item_filed or ("2.01" in s.item_filed and bool(s.merger_filing or s.delist_filing))


def resolve(s: EraSignals, items_code: int | None) -> EraVerdict:
```

replace

```python
    if "5.01" in s.item_filed:
        return EraVerdict("change_in_control", merger_code, CrspBucket.MERGER,
```

with

```python
    if "5.01" in s.item_filed and not s.survived:
        return EraVerdict("change_in_control", merger_code, CrspBucket.MERGER,
```

and replace

```python
    if "2.01" in s.item_filed and (s.merger_filing or s.delist_filing):
```

with

```python
    if "2.01" in s.item_filed and (s.merger_filing or s.delist_filing) and not s.survived:
```

- [ ] **Step 4: The classifier reads the role and R1**

In `src/delist_detection/classifier.py`, replace

```python
import re
from dataclasses import asdict, dataclass, field
```

with

```python
import re
from dataclasses import asdict, dataclass, field, replace
```

replace

```python
from . import end_of_era
from .crsp_codes import CrspBucket, bucket_for_code
```

with

```python
from . import end_of_era, exchange_terms
from .crsp_codes import CrspBucket, bucket_for_code
```

replace

```python
from .form25 import notice_says_acquired, parse_form25
```

with

```python
from .figi_resolution import share_class_from_name
from .form25 import Form25, notice_says_acquired, parse_form25
```

replace

```python
        if delinquent:
            return rec(580, CrspBucket.COMPLIANCE_FAILURE, "medium",
                       "Delinquent filer (NT 10-K/Q in the prior year), no merger evidence")
        flags.append("no_evidence_default")
```

with

```python
        if delinquent:
            return rec(580, CrspBucket.COMPLIANCE_FAILURE, "medium",
                       "Delinquent filer (NT 10-K/Q in the prior year), no merger evidence")
        # Sub-plan 5c, R1: no 8-K item code, but the filings state each share became one share, with no cash (a
        # reclassification into another class, Clearway 2026; a holding company's formation, ONEOK 2026)
        r1 = self._one_for_one(cik, evidence.get("name"), filings, [observed, anchor], delist_filing)
        if r1 is not None:
            _add_flag(flags, "r1_continuation")
            return rec(304, CrspBucket.EXCHANGE_TRANSFER, "medium",
                       f"Continuation (R1): each share became one share {r1.target[:80].strip()}, no cash")
        flags.append("no_evidence_default")
```

replace

```python
            items_code, _ = self._classify_items(set(era.item_filed))
            verdict = end_of_era.resolve(era, items_code)
            evidence["end_of_era"] = verdict.branch
```

with

```python
            if end_of_era.merges(era):
                era = replace(era, survived=self._survived(resolution.cik, resolution.name, filings, observed,
                                                           era, delist_filing_override))
            items_code, _ = self._classify_items(set(era.item_filed))
            verdict = end_of_era.resolve(era, items_code)
            evidence["end_of_era"] = verdict.branch
            if era.survived:
                evidence["survived"] = era.survived
```

and replace

```python
    def _notice_says_acquired(self, cik: int, sub: EdgarSubmission) -> bool:
```

with

```python
    def _matched_form25(self, cik: int, sub: EdgarSubmission | None) -> Form25 | None:
        """The parsed Form 25 the delisting finder matched (`sub`), for its EX-99.25 notice; None without one or
        when its text cannot be read."""
        fetch = getattr(self.edgar, "fetch_filing_raw", None)
        raw = fetch(cik, sub.accession) if sub is not None and fetch is not None else ""
        return parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date) if raw else None

    def _survived(self, cik: int, name: str | None, filings: list[EdgarSubmission], observed: date,
                  era: end_of_era.EraSignals, form25: EdgarSubmission | None) -> str:
        """Sub-plan 5c, rule 1: the sentence that says the registrant survived the transaction its 8-K items
        call a merger -- its own shares were not exchanged (`exchange_terms.own_exchange` finds no statement
        about them), and another party's shares became its own or it issued its shares to the other party
        (`acquires`: RRI Energy acquiring Mirant, SXC acquiring Catalyst, Forest Oil issuing shares to Sabine), or
        its holders received another company's shares and kept theirs (`distributes`: News Corp's 2013
        separation) -- else "". Read in the 8-Ks around the end and around the 5.01 and 2.01 8-Ks, and the
        matched Form 25's notice; names in force before the earliest of those days. Never rename or separation
        words alone (BNI, CAL, TXU, LGFA were targets renamed after closing)."""
        days = [observed] + [d for item in ("5.01", "2.01") if (d := _parse_date(era.item_filed.get(item, "")))]
        names = exchange_terms.registrant_names(self.edgar.submissions(cik), min(days), name or "")
        texts = exchange_terms.read_texts(self.edgar, cik, filings, days, self._matched_form25(cik, form25))
        if exchange_terms.own_exchange(texts, names=names, class_letter=None) is not None:
            return ""
        return exchange_terms.acquires(texts, names=names) or exchange_terms.distributes(texts, names=names)

    def _one_for_one(self, cik: int, name: str | None, filings: list[EdgarSubmission], days: list[date],
                     form25: EdgarSubmission | None) -> exchange_terms.OwnExchange | None:
        """Sub-plan 5c, R1: the filings around `days` state each share of the security's own class became one
        share, with no cash (`exchange_terms.own_exchange`, the class read from the security's name); else
        None."""
        days = [d for d in days if d]
        if not days:
            return None
        letter, words = exchange_terms.class_of(share_class_from_name(name), name)
        names = exchange_terms.registrant_names(self.edgar.submissions(cik), min(days), name or "")
        texts = exchange_terms.read_texts(self.edgar, cik, filings, days, self._matched_form25(cik, form25))
        own = exchange_terms.own_exchange(texts, names=names, class_letter=letter, class_words=words)
        return own if own is not None and own.one_for_one else None

    def _notice_says_acquired(self, cik: int, sub: EdgarSubmission) -> bool:
```

- [ ] **Step 5: The flag's catalog entry**

In `src/delist_detection/review_triage.py`, replace

```python
    "line_continuation": FlagInfo(
```

with

```python
    "r1_continuation": FlagInfo(
        "info", "The registrant's filings state each share of the security became one share, with no cash (ruling "
                "R1), so the row is an exchange transfer to successor_sec_id with a zero return (sub-plan 5c).",
        "Nothing unless the filing says holders were paid or got another ratio; then the row is a merger."),
    "line_continuation": FlagInfo(
```

In `tests/test_review_triage.py`, replace

```python
            "handoff_continuation", "line_followed", "line_follow_refused", "line_continuation"}
```

with

```python
            "handoff_continuation", "line_followed", "line_follow_refused", "line_continuation",
            "r1_continuation"}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_end_of_era.py tests/test_issuer_role_cases.py tests/test_classify_event.py tests/test_classifier.py tests/test_form25_reach_cases.py tests/test_review_triage.py`
Expected: PASS. Then the full suite: 2284 passed, 240 xfailed (5b's real cases and the golden replay unchanged).

- [ ] **Step 7: Commit**

```bash
git add src/delist_detection/end_of_era.py src/delist_detection/classifier.py src/delist_detection/review_triage.py tests/test_end_of_era.py tests/test_review_triage.py tests/test_issuer_role_cases.py
git commit -m "Stage 5 reads the registrant's role before a merger branch, and R1 without an item code (sub-plan 5c, rule 1)"
```

---

### Task 5: Stage 8b, the merger rows R1 makes continuations

Tier: standard.

A merger whose published terms are one share and no cash (DOW, MYL, SBGI, DISCK, DISCA, LLYVA, LLYVK, WAG, DTV,
KRFT; PX, AMSG and WR of 5e's rows) becomes an exchange transfer to its successor when the registrant's own filings
say the same of its own shares and the successor is a new issuer or the same issuer.

**Files:**
- Modify: `src/delist_detection/successors.py`, `src/delist_detection/pipeline.py`,
  `src/delist_detection/review_triage.py`
- Create: `tests/test_successor_terms.py`
- Test: `tests/test_review_triage.py`, `tests/test_run_provenance.py`, `tests/test_issuer_role_cases.py`

**Interfaces:**
- Consumes: Task 2's `exchange_terms.OwnExchange`, `own_exchange`, `read_texts`, `class_of`, `registrant_names`;
  today's `successors.successor_from_8k12b`, `successor_search_name`, `SUCCESSOR_BEFORE_DAYS`,
  `SUCCESSOR_AFTER_DAYS`; `pipeline._Payouts`, `for_delisting`, `DegradedWatch`, `degraded_item`,
  `CONTINUATION_CODE`, `edgar_names`.
- Produces: `successors.SecurityStart(first_seen, issuer_cik, tickers, last_seen="", share_class="")`;
  `successors.NEW_ISSUER_DAYS` (1095), `SAME_ISSUER_CLASS` ("same_issuer_class"), `NEW_ISSUER` ("new_issuer"),
  `successor_anchor(e) -> date`, `successor_by_terms(e, exchange, day, starts, *, issuer_since, issuer_names)
  -> (sec_id, how) | None`; `pipeline.R1_CONTINUATION`, `R1_REBUCKETED`, `BY_TERMS`, `BY_OWN_REGISTRATION`,
  `pipeline._starts(securities, sightings, added) -> dict[str, SecurityStart]`, `pipeline._IssuerAge(edgar)` with
  `since(cik)` and `names(cik)`, `pipeline._own_exchange(edgar, e, sec) -> (OwnExchange | None, texts, day)`,
  `pipeline._contract_terms(payouts, key)`, `pipeline._R1(links, added, review)`,
  `pipeline._r1_continuations(ctx, delistings, securities, sightings, payouts, overrides) -> _R1`; the review flag
  `r1_rebucketed`; the manifest stage "R1 continuations".

- [ ] **Step 1: Write the failing tests**

Create `tests/test_successor_terms.py`:

```python
"""successors.successor_by_terms and pipeline stage 8b (sub-plan 5c, ruling R1): the security a one-for-one, no-cash
exchange made the holders' shares, and the merger rows R1 rewrites as continuations."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from delist_detection import pipeline
from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import SUCCESSOR_UNKNOWN, Delisting
from delist_detection.exchange_terms import OwnExchange
from delist_detection.last_trade import LastTrade
from delist_detection.successors import (NEW_ISSUER, NEW_ISSUER_DAYS, SAME_ISSUER_CLASS, SecurityStart,
                                         successor_anchor, successor_by_terms)
from tests import issuer_role_cases as ic

DAY = date(2020, 6, 30)


def _delisting(cik=1, ticker="OLD", day=DAY):
    rec = DelistRecord(ticker, cik, day.isoformat(), 304, CrspBucket.EXCHANGE_TRANSFER, "medium", "r",
                       {"flags": [SUCCESSOR_UNKNOWN]}, sec_id="OLD-ID", delist_date="2020-07-10")
    return Delisting("OLD-ID", cik, ticker, "2020-07-10", rec, LastTrade(day, "midas", ()), None, None, "NYSE")


def _own(names=("Newco",), letter="", own=False, ratio=1.0, cash=False):
    return OwnExchange(ratio, cash, "of Newco common stock", tuple(names), letter, own, "s")


def _ask(starts, own, *, since=None, names=None):
    since = since or {}
    names = names or {}
    return successor_by_terms(_delisting(), own, DAY, starts, issuer_since=lambda c: since.get(c),
                              issuer_names=lambda c: names.get(c, ()))


def test_a_new_issuers_security_named_by_the_target_is_the_successor():
    starts = {"NEW": SecurityStart("2020-07-01", 2, {"NEWC"}, "2026-01-01", "COMMON")}
    assert _ask(starts, _own(), since={2: "2019-10-25"}, names={2: ("Newco Inc",)}) == ("NEW", NEW_ISSUER)
    # by its ticker alone (BHI: "one share of BHGE's Class A common stock")
    assert _ask(starts, _own(names=("NEWC",)), since={2: "2019-10-25"}) == ("NEW", NEW_ISSUER)


@pytest.mark.parametrize("age,linked", [(548, True), (NEW_ISSUER_DAYS, True), (NEW_ISSUER_DAYS + 1, False),
                                        (4125, False)], ids=["DowDuPont", "limit", "past", "Progressive"])
def test_only_a_new_issuer_is_a_continuation(age, linked):
    """DowDuPont was 548 days old (Linde 517, Viatris 388): new holding companies; Progressive Waste (4,125 days),
    GCI Liberty (8,442) and Willis (5,347) existed, so their deals stay mergers."""
    starts = {"NEW": SecurityStart("2020-07-01", 2, {"NEWC"}, "", "COMMON")}
    since = {2: (DAY - timedelta(days=age)).isoformat()}
    assert (_ask(starts, _own(), since=since, names={2: ("Newco Inc",)}) is not None) is linked


def test_without_a_name_tie_a_new_registrant_sighted_in_the_window_is_no_successor():
    """AABA and BHGE, MSG and Alphabet: a new registrant first sighted near the end is not named by the target."""
    starts = {"NEW": SecurityStart("2020-07-01", 2, {"BHGE"}, "", "COMMON")}
    assert _ask(starts, _own(names=("Holdco",)), since={2: "2020-01-01"}, names={2: ("Baker Hughes Co",)}) is None


def test_a_new_issuer_first_sighted_outside_the_window_is_no_successor():
    starts = {"NEW": SecurityStart("2020-08-01", 2, {"NEWC"}, "", "COMMON")}
    assert _ask(starts, _own(), since={2: "2020-01-01"}, names={2: ("Newco Inc",)}) is None


def test_the_same_issuers_class_the_target_names_alive_after_the_end():
    """CMCSK into CMCSA (Class A, sighted since 2007), CWENA into CWEN (Class C), HUB-B into HUBB (the common)."""
    starts = {"A": SecurityStart("2007-12-17", 1, {"CMCSA"}, "2026-09-25", "CLASS A"),
              "C": SecurityStart("2008-01-02", 1, {"CMCSC"}, "2026-09-25", "CLASS C"),
              "GONE": SecurityStart("2008-01-02", 1, {"CMCSG"}, "2020-06-01", "CLASS A")}
    assert _ask(starts, _own(names=(), letter="A", own=True)) == ("A", SAME_ISSUER_CLASS)
    assert _ask(starts, _own(names=(), letter="C", own=True)) == ("C", SAME_ISSUER_CLASS)
    assert _ask(starts, _own(names=(), letter="B", own=True)) is None


def test_two_new_lines_of_one_issuer_are_told_apart_by_the_class_letter_and_two_of_one_class_tie():
    """Liberty Live Holdings' Series A and Series C, both first sighted 2025-12-17."""
    starts = {"LA": SecurityStart("2020-07-02", 2, {"LLYVA"}, "", "CLASS A"),
              "LC": SecurityStart("2020-07-02", 2, {"LLYVK"}, "", "CLASS C")}
    names = {2: ("Liberty Live Holdings, Inc.",)}
    own = _own(names=("Liberty Live Holdings",), letter="A")
    assert _ask(starts, own, since={2: "2020-01-01"}, names=names) == ("LA", NEW_ISSUER)
    starts["LA2"] = SecurityStart("2020-07-02", 2, {"LLYVB"}, "", "CLASS A")
    assert _ask(starts, own, since={2: "2020-01-01"}, names=names) is None


def test_no_link_for_another_ratio_cash_or_two_readings():
    starts = {"NEW": SecurityStart("2020-07-01", 2, {"NEWC"}, "", "COMMON")}
    since, names = {2: "2020-01-01"}, {2: ("Newco Inc",)}
    for own in (_own(ratio=0.9042), _own(cash=True), replace(_own(), ambiguous=True)):
        assert _ask(starts, own, since=since, names=names) is None


def test_the_anchor_is_the_last_trade_then_the_form25_then_the_anchor_8k():
    d = _delisting()
    assert successor_anchor(d) == DAY
    d.last_trade = LastTrade(None, "", ())
    d.record.evidence["anchor_8k"] = {"filing_date": "2020-07-02"}
    assert successor_anchor(d) == date(2020, 7, 2)
    d.record.evidence = {}
    assert successor_anchor(d) == date(2020, 7, 10)


# --- stage 8b on the real cases (tests/fixtures/issuer_role/) ---

def _stage8b(sec_id, terms=None):
    c = ic.clients()
    found, _ = ic.find(sec_id, c)
    securities, _, cusips, ftd = ic.world()
    sightings = {sid: pipeline.ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    ctx = pipeline._RunContext(c, ic.AS_OF, lambda *a: None, 1, pipeline.run_manifest.StageMeter(lambda *a: None))
    payouts = ic._payouts(sec_id, found)
    if terms is not None:
        payouts.llm_terms = {k: replace(t, cash_per_share=terms[0], stock_ratio=terms[1])
                             for k, t in payouts.llm_terms.items()}
    r1 = pipeline._r1_continuations(ctx, found, securities, sightings, payouts, pipeline.Overrides())
    return found, payouts, r1


def test_a_rewritten_merger_drops_its_payout_reads_and_keeps_its_old_bucket_in_review():
    found, payouts, r1 = _stage8b("BBG000BHBK84")                                         # DOW 2017
    d = found[0]
    assert (d.record.bucket, d.record.crsp_code, d.record.successor_sec_id) == (
        CrspBucket.EXCHANGE_TRANSFER, 304, "BBG00BN961G4")
    assert pipeline.R1_CONTINUATION in d.flags and d.key not in payouts.llm_terms
    assert [i.flag for i in r1.review] == [pipeline.R1_REBUCKETED] and "was merger (CRSP 231" in r1.review[0].reason


@pytest.mark.parametrize("cash,flips", [(16.50, True), (16.00, False), (None, True)], ids=["dividend", "cash", "none"])
def test_a_special_dividend_is_no_cash_but_other_cash_keeps_the_merger(cash, flips):
    """KRFT 2015: the LLM read $16.50 and one Kraft Heinz share; the 8-K calls the $16.50 a special cash dividend
    (operator ruling 2026-10-04: never consideration). $16.00 is not the dividend: cash in the exchange."""
    found, _, _ = _stage8b("BBG001YMS0B8", terms=(cash, 1.0))
    assert (found[0].record.bucket is CrspBucket.EXCHANGE_TRANSFER) is flips


def test_a_merger_terms_override_decides_the_row():
    c = ic.clients()
    found, _ = ic.find("BBG000BHBK84", c)
    securities, _, cusips, ftd = ic.world()
    sightings = {sid: pipeline.ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    ctx = pipeline._RunContext(c, ic.AS_OF, lambda *a: None, 1, pipeline.run_manifest.StageMeter(lambda *a: None))
    over = pipeline.Overrides(merger_terms={"BBG000BHBK84": {"stock_ratio": 1.0}})
    pipeline._r1_continuations(ctx, found, securities, sightings, ic._payouts("BBG000BHBK84", found), over)
    assert found[0].record.bucket is CrspBucket.MERGER
```

In `tests/test_issuer_role_cases.py`, replace

```python
RULES_DONE: set[str] = {"stage5"}
```

with

```python
RULES_DONE: set[str] = {"stage5", "r1"}
```

In `tests/test_review_triage.py`, replace

```python
                 "handoff_rebucketed", "handoff_conflict", "handoff_takeover_no_delisting"):
```

with

```python
                 "handoff_rebucketed", "handoff_conflict", "handoff_takeover_no_delisting", "r1_rebucketed"):
```

In `tests/test_run_provenance.py`, replace

```python
                                "other issuers in force"}
```

with

```python
                                "other issuers in force", "R1 continuations"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_successor_terms.py tests/test_issuer_role_cases.py`
Expected: FAIL at collection: `ImportError: cannot import name 'NEW_ISSUER' from 'delist_detection.successors'`.

- [ ] **Step 3: The successor a one-for-one statement names**

In `src/delist_detection/successors.py`, replace

```python
import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import NamedTuple

from .delistings import SUCCESSOR_UNKNOWN, Delisting
from .figi_resolution import FigiCandidate, share_class_from_name, us_candidates
```

with

```python
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import NamedTuple

from .delistings import SUCCESSOR_UNKNOWN, Delisting
from .exchange_terms import OwnExchange
from .figi_resolution import FigiCandidate, class_letter, share_class_from_name, us_candidates
```

replace

```python
class SecurityStart(NamedTuple):
    """How a security of the run (observed or added) first shows up, for the
    in-run successor search: its first sighting, its issuer CIK, and every
    ticker it was sighted under."""
    first_seen: str
    issuer_cik: int | None
    tickers: set[str]
```

with

```python
class SecurityStart(NamedTuple):
    """How a security of the run (observed or added) shows up, for the in-run
    successor search: its first sighting, its issuer CIK, every ticker it was
    sighted under, its last sighting and its share class."""
    first_seen: str
    issuer_cik: int | None
    tickers: set[str]
    last_seen: str = ""
    share_class: str = ""
```

and append to the file:

```python
NEW_ISSUER_DAYS = 1095    # R1 (operator, 2026-10-04): an issuer that first filed with EDGAR at most this long before
#                           the event is a new one (new holding companies measured 0-548 days: DowDuPont 548, Linde
#                           517, Viatris 388; existing acquirers 4,125-8,442)
SAME_ISSUER_CLASS, NEW_ISSUER = "same_issuer_class", "new_issuer"


def successor_anchor(e: Delisting) -> date:
    """The day a successor of `e` is looked for around: its last trade, else its Form 25's filing date, else the
    8-K the classifier anchored on, else (approximate) its delisting date."""
    if e.last_trade.day is not None:
        return e.last_trade.day
    if e.form25_sub is not None:
        return date.fromisoformat(e.form25_sub.filing_date)
    filed = ((e.record.evidence or {}).get("anchor_8k") or {}).get("filing_date")
    return date.fromisoformat(filed) if filed else date.fromisoformat(e.delist_date)


def _named(exchange: OwnExchange, tickers: set[str], names: Sequence[str]) -> bool:
    """The R1 target clause names the candidate: one of its tickers (two letters or more) is a word of a target
    name ("BHGE's Class A common stock"), or a target name agrees with one of its EDGAR names
    (`names.names_agree`: "DowDuPont" and DowDuPont Inc.; "Holdco", expanded, and Howard Hughes Holdings Inc.)."""
    words = {w.upper() for t in exchange.target_names for w in re.findall(r"[A-Za-z0-9]+", t)}
    if {normalize_ticker(t).replace("-", "") for t in tickers if len(t) >= 2} & words:
        return True
    return any(names_agree(t, n) for t in exchange.target_names for n in names if n)


def successor_by_terms(e: Delisting, exchange: OwnExchange, day: date, starts: Mapping[str, SecurityStart], *,
                       issuer_since: Callable[[int], str | None],
                       issuer_names: Callable[[int], Sequence[str]]) -> tuple[str, str] | None:
    """The security the R1 statement says the holders' shares became, one for one with no cash
    (`exchange.one_for_one`), among the run's (`starts`):

    - of the same issuer (SAME_ISSUER_CLASS: a reclassification, CMCSK into CMCSA, Clearway's Class A into Class C,
      Discovery into WBD): of the class letter the target names ("" for a plain common), sighted by
      `day` + SUCCESSOR_AFTER_DAYS and not gone before `day`, the target naming the registrant or the security;
    - of a new issuer (NEW_ISSUER: a holding company, BHGE, Howard Hughes Holdings, Viatris): first sighted within
      [day - SUCCESSOR_BEFORE_DAYS, day + SUCCESSOR_AFTER_DAYS], its issuer's first EDGAR filing
      (`issuer_since`) at most NEW_ISSUER_DAYS before `day`, the target naming it (`_named`: a ticker or an EDGAR
      name, `issuer_names`). An existing company is never a continuation (LVNTA into GCI Liberty, WCN into
      Progressive Waste), and without the name tie a new registrant sighted in the window is not one either
      (AABA and BHGE, MSG and Alphabet).

    Several: the one of the class letter the target names. Returns (sec_id, how); None for none or a tie."""
    if not exchange.one_for_one:
        return None
    lo = (day - timedelta(days=SUCCESSOR_BEFORE_DAYS)).isoformat()
    hi = (day + timedelta(days=SUCCESSOR_AFTER_DAYS)).isoformat()
    found: dict[str, str] = {}
    for sid, st in starts.items():
        if sid == e.sec_id or st.issuer_cik is None:
            continue
        if st.issuer_cik == e.cik:
            alive = not st.last_seen or st.last_seen >= day.isoformat()
            if (st.first_seen <= hi and alive and (class_letter(st.share_class) or "") == exchange.target_letter
                    and (exchange.target_own or _named(exchange, st.tickers, issuer_names(st.issuer_cik)))):
                found[sid] = SAME_ISSUER_CLASS
        elif lo <= st.first_seen <= hi:
            since = issuer_since(st.issuer_cik)
            if since is None or (day - date.fromisoformat(since[:10])).days > NEW_ISSUER_DAYS:
                continue
            if _named(exchange, st.tickers, issuer_names(st.issuer_cik)):
                found[sid] = NEW_ISSUER
    if len(found) > 1:
        found = {sid: how for sid, how in found.items()
                 if (class_letter(starts[sid].share_class) or "") == exchange.target_letter}
    return next(iter(found.items())) if len(found) == 1 else None
```

- [ ] **Step 4: Stage 8b**

In `src/delist_detection/pipeline.py`, replace

```python
from . import manifest as run_manifest
from . import scorecard as run_scorecard
```

with

```python
from . import exchange_terms
from . import manifest as run_manifest
from . import scorecard as run_scorecard
```

replace

```python
from .successors import (
    SUCCESSOR_AFTER_DAYS, SUCCESSOR_BEFORE_DAYS, SecurityStart, successor_from_8k12b, successor_in_run,
    successor_query, successor_search_args,
)
```

with

```python
from .successors import (
    NEW_ISSUER_DAYS, SUCCESSOR_AFTER_DAYS, SUCCESSOR_BEFORE_DAYS, SecurityStart, successor_anchor, successor_by_terms,
    successor_from_8k12b, successor_in_run, successor_query, successor_search_args, successor_search_name,
)
```

replace

```python
LINE_FOLLOW, LINE_CONTINUATION = "line_follow", "line_continuation"
```

with

```python
R1_CONTINUATION, R1_REBUCKETED = "r1_continuation", "r1_rebucketed"
BY_TERMS, BY_OWN_REGISTRATION = "terms", "own_registration"
# the payout flags a merger row carries that a continuation does not
_PAYOUT_FLAGS = frozenset({"terms_gate_failed", "payout_gate_failed", "llm_gate_failed", "merger_at_par",
                           "acquirer_close_lagged"})


def _starts(securities: dict[str, Security], sightings: dict[str, list[Sighting]],
            added: Mapping[str, AddedSecurity]) -> dict[str, SecurityStart]:
    """How each security of the run shows up, for the successor searches (`successors.SecurityStart`): an observed
    one by its sightings, an added one by its span and ticker."""
    starts = {sid: SecurityStart(sig[0].day, securities[sid].issuer_cik, {x.value for x in sig}, sig[-1].day,
                                 securities[sid].share_class)
              for sid, sig in sightings.items() if sig and sid in securities}
    for sid, a in added.items():
        first, last = a.span()
        starts[sid] = SecurityStart(first, a.security.issuer_cik, {a.ticker}, last, a.security.share_class)
    return starts


class _IssuerAge:
    """Each issuer's first EDGAR filing and its EDGAR names, read once (the finder already read most of them)."""

    def __init__(self, edgar) -> None:
        self.edgar = edgar
        self._since: dict[int, str | None] = {}
        self._names: dict[int, tuple[str, ...]] = {}

    def since(self, cik: int) -> str | None:
        if cik not in self._since:
            dates = [f.filing_date for f in self.edgar.recent_filings(cik) if f.filing_date]
            self._since[cik] = min(dates) if dates else None
        return self._since[cik]

    def names(self, cik: int) -> tuple[str, ...]:
        if cik not in self._names:
            sub = self.edgar.submissions(cik)
            self._names[cik] = edgar_names(sub) if isinstance(sub, dict) else ()
        return self._names[cik]


def _own_exchange(edgar, e: Delisting, sec: Security) -> tuple[exchange_terms.OwnExchange | None, list[str], date]:
    """What `e`'s security's own shares became (`exchange_terms.own_exchange`), the texts it was read in and the
    day it was read around (`successors.successor_anchor`; the 8-K the classifier anchored on is read too)."""
    day = successor_anchor(e)
    days = [day]
    filed = ((e.record.evidence or {}).get("anchor_8k") or {}).get("filing_date")
    if filed:
        days.append(date.fromisoformat(filed))
    texts = exchange_terms.read_texts(edgar, e.cik, edgar.recent_filings(e.cik), days, e.form25)
    letter, words = exchange_terms.class_of(sec.share_class, sec.name)
    names = exchange_terms.registrant_names(edgar.submissions(e.cik), min(days), sec.name)
    return exchange_terms.own_exchange(texts, names=names, class_letter=letter, class_words=words), texts, day


def _contract_terms(payouts: _Payouts, key: DelistingKey) -> tuple[float | None, float | None] | None:
    """The (cash, stock ratio) the contract publishes for a merger without a --merger-terms row
    (`payout_rule._merger`'s order): the terms the payout gate kept, else the LLM's as read, else the regex cash;
    None with none."""
    gated = payouts.gated
    terms = for_delisting(gated.merged_terms, key) or {}
    cash = gated.payouts.get(key)
    if terms or cash is not None:
        return terms.get("cash_per_share", cash), terms.get("stock_ratio")
    llm = payouts.llm_terms.get(key)
    if llm is not None and (llm.cash_per_share or llm.stock_ratio):
        return llm.cash_per_share, llm.stock_ratio
    pr = payouts.raw.get(key)
    return (pr.value, None) if pr is not None and pr.value is not None else None


@dataclass
class _R1:
    """Stage 8b's answer: the merger rows it rewrote as continuations (by delisting: the successor and how it was
    found), the successors it adds as securities of their own, and its review items."""
    links: dict[DelistingKey, tuple[str, str]] = field(default_factory=dict)
    added: dict[str, AddedSecurity] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)


def _r1_successor(ctx: _RunContext, e: Delisting, sec: Security, own: exchange_terms.OwnExchange, day: date,
                  starts: dict[str, SecurityStart], ages: _IssuerAge, securities: dict[str, Security],
                  added: Mapping[str, AddedSecurity], out: _R1) -> tuple[str, str] | None:
    """The successor of a merger row R1 rewrites: a security of the run (`successors.successor_by_terms`), else
    the new issuer whose 8-K12B names the registrant (`successors.successor_from_8k12b`, its filer at most
    NEW_ISSUER_DAYS old), added as a security of its own (`AddedSuccessor`, seen from the day after `day`)."""
    link = successor_by_terms(e, own, day, starts, issuer_since=ages.since, issuer_names=ages.names)
    search = getattr(ctx.clients.edgar, "full_text_search", None)
    if link is not None or search is None:
        return link
    hit = successor_from_8k12b(search, ctx.clients.figi, name=successor_search_name(ctx.clients.edgar, e.cik, sec.name),
                               day=day, exclude_cik=e.cik, share_class=sec.share_class, edgar=ctx.clients.edgar,
                               own_tickers=sec.own_tickers() | {e.ticker})
    if hit is None:
        return None
    s_cik, cand, filed = hit
    since = ages.since(s_cik)
    if since is None or (day - date.fromisoformat(since[:10])).days > NEW_ISSUER_DAYS:
        return None
    if cand.composite not in securities and cand.composite not in added:
        not_before = (day + timedelta(days=1)).isoformat()
        out.added.setdefault(cand.composite, AddedSuccessor(
            Security(cand.composite, s_cik, share_class_from_name(cand.name), cand.name, cand.security_type, False,
                     "ticker"), cand.ticker, max(filed or not_before, not_before)))
    return cand.composite, BY_TERMS


def _r1_continuations(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                      sightings: dict[str, list[Sighting]], payouts: _Payouts, overrides: Overrides) -> _R1:
    """8b. A merger that ruling R1 makes a continuation (sub-plan 5c): its published terms are one share and no
    cash (a special dividend is no cash: operator ruling 2026-10-04), no --merger-terms row decides it, the
    registrant's own filings say the same of its own shares (`exchange_terms.own_exchange`, one reading: a
    multi-step deal's intermediate one-for-one, Jefferies 2013, has the LLM's 0.81 against it), and the holders'
    new shares are a new issuer's or the same issuer's (`_r1_successor`). The row becomes an exchange transfer
    (304) to that successor, flagged `r1_continuation`, its payout reads dropped (a continuation has no value),
    and an `r1_rebucketed` review item keeps its old bucket. An existing acquirer is never a continuation (LVNTA
    into GCI Liberty, Towers Watson into Willis, Waste Connections into Progressive Waste)."""
    edgar, out = ctx.clients.edgar, _R1()
    mark = ctx.meter.start()
    ages = _IssuerAge(edgar)
    starts = _starts(securities, sightings, payouts.added)
    gated = payouts.gated
    for e in delistings:
        if e.record.bucket is not CrspBucket.MERGER or e.sec_id not in securities \
                or for_delisting(overrides.merger_terms, e.key):
            continue
        terms = _contract_terms(payouts, e.key)
        if terms is None or terms[1] is None or abs(terms[1] - 1.0) > 1e-9:
            continue
        watch = DegradedWatch()
        sec = securities[e.sec_id]
        own, _, day = _own_exchange(edgar, e, sec)
        cash = terms[0]
        link = None
        if own is not None and own.one_for_one and (
                not cash or any(abs(cash - d) < 0.005 for d in own.special_dividends)):
            link = _r1_successor(ctx, e, sec, own, day, starts, ages, securities, payouts.added, out)
        if watch.tripped():
            out.review.append(degraded_item(e.sec_id, e.ticker, e.cik, "the R1 reading", delist_date=e.delist_date))
            continue
        if link is None:
            continue
        sid, how = link
        old = (e.record.bucket.value, e.record.crsp_code, e.record.reason)
        e.record.bucket, e.record.crsp_code = CrspBucket.EXCHANGE_TRANSFER, CONTINUATION_CODE
        e.record.confidence = "medium"
        e.record.reason = (f"Continuation (R1): each share became one {own.target[:80].strip(' ,')}, no cash; "
                           f"successor by {how.replace('_', ' ')}")
        e.record.evidence["flags"] = [f for f in e.flags if flag_name(f) not in _PAYOUT_FLAGS] + [R1_CONTINUATION]
        e.record.evidence["r1"] = {"sentence": own.sentence[:300], "was": f"{old[0]} {old[1]}"}
        e.record.evidence["successor_by"] = how
        for m in (payouts.raw, payouts.llm_terms, payouts.acquirer_ids, gated.payouts, gated.sources,
                  gated.confidences, gated.merged_terms, gated.flags):
            m.pop(e.key, None)
        e.set_successor(sid)
        out.links[e.key] = link
        out.review.append(ReviewItem(e.sec_id, e.ticker, e.cik, R1_REBUCKETED,
                                     f"was {old[0]} (CRSP {old[1]}: {old[2]}); R1 makes it a continuation into {sid}",
                                     delist_date=e.delist_date))
    ctx.log(f"R1 continuations: {len(out.links)} merger rows ({', '.join(sorted(k.sec_id for k in out.links))})")
    ctx.meter.done("R1 continuations", mark)
    return out


LINE_FOLLOW, LINE_CONTINUATION = "line_follow", "line_continuation"
```

replace

```python
    payouts = _merger_payouts(ctx, delistings, securities, sec_cusips, ftd, closes, overrides, tol) # 8
    review += payouts.review
    successors = _find_successors(ctx, delistings, securities, search.sightings, payouts.added,
                                  lines.successors, ftd)                                            # 9
    _link_successors(delistings, successors)
    review += successors.review
    added = {**payouts.added, **successors.added}         # the acquirers and successors the run adds
```

with

```python
    payouts = _merger_payouts(ctx, delistings, securities, sec_cusips, ftd, closes, overrides, tol) # 8
    review += payouts.review
    r1 = _r1_continuations(ctx, delistings, securities, search.sightings, payouts, overrides)      # 8b
    review += r1.review
    successors = _find_successors(ctx, delistings, securities, search.sightings, {**payouts.added, **r1.added},
                                  lines.successors, ftd)                                            # 9
    _link_successors(delistings, successors)
    review += successors.review
    added = {**payouts.added, **r1.added, **successors.added}     # the acquirers and successors the run adds
```

and replace

```python
    tables.update(_contract(ctx, _as_read(tables), verdicts, payouts, set(successors.added), overrides,
```

with

```python
    # an acquirer the run added that R1 made a merger row's successor is in the contract's history (Sinclair Inc)
    successor_ids = set(successors.added) | set(r1.added) | {sid for sid, _ in r1.links.values()}
    tables.update(_contract(ctx, _as_read(tables), verdicts, payouts, successor_ids, overrides,
```

- [ ] **Step 5: The review flag's catalog entry**

In `src/delist_detection/review_triage.py`, replace

```python
    "handoff_conflict": FlagInfo(
```

with

```python
    "r1_rebucketed": FlagInfo(
        "check", "A merger row ruling R1 rewrote as a continuation (an exchange transfer to successor_sec_id): its "
                 "terms were one share and no cash, the registrant's filings say each of its shares became one "
                 "share of the successor, and the successor is a new issuer's or the same issuer's (sub-plan 5c); "
                 "the reason keeps the old bucket and code.",
        f"Read the filing the delisting's evidence quotes: if holders received cash or another ratio, report it; "
        f"otherwise {_ACCEPT}."),
    "handoff_conflict": FlagInfo(
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_successor_terms.py tests/test_issuer_role_cases.py tests/test_review_triage.py tests/test_run_provenance.py tests/test_pipeline.py tests/test_handoffs.py`
Expected: PASS. Then the full suite: 2300 passed, 240 xfailed.

- [ ] **Step 7: Commit**

```bash
git add src/delist_detection/successors.py src/delist_detection/pipeline.py src/delist_detection/review_triage.py tests/test_successor_terms.py tests/test_issuer_role_cases.py tests/test_review_triage.py tests/test_run_provenance.py
git commit -m "Stage 8b: a one-for-one, no-cash merger into a new or the same issuer is a continuation (sub-plan 5c, R1)"
```

---

### Task 6: Stage 9, links from the registrant's own filings (rules 3 and 4)

Tier: standard.

An exchange transfer still without a successor (BHI, HHC, CMCSK, HUB-B, CWENA, CCO, OKE) takes the security its
registrant's R1 statement names, else the line its own same-CIK successor registration moved the holders to.

**Files:**
- Modify: `src/delist_detection/pipeline.py`
- Create: `tests/test_successor_links.py`
- Test: `tests/test_issuer_role_cases.py`

**Interfaces:**
- Consumes: Task 5's `pipeline._starts`, `_IssuerAge`, `_own_exchange`, `BY_OWN_REGISTRATION`,
  `successors.successor_by_terms`; today's `handoffs.own_continuation_filing`, `line_follow.text_cusips`,
  `composites`, `is_line_symbol`, `security_master.cusip_job`, `AddedLineSuccessor`.
- Produces: `pipeline._own_registration_link(ctx, e, texts, day, securities, sec_cusips, ftd, taken, found)
  -> (sec_id, how) | None`; `pipeline._terms_links(ctx, delistings, securities, starts, sec_cusips, ftd, taken,
  found) -> None`; `pipeline._find_successors(..., ftd=None, sec_cusips=None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_successor_links.py`:

```python
"""Pipeline stage 9's links from the registrant's own filings (sub-plan 5c, rules 3 and 4), on the real cases of
tests/fixtures/issuer_role/: what the shares became one for one, and the line a same-CIK successor registration
moved the holders to."""
from __future__ import annotations

import pytest

from tests import issuer_role_cases as ic

CCO, NEW_CUSIP = "BBG000J453J8", "18453H106"


def _rows(composite):
    return {"data": [dict(r, compositeFIGI=composite) for r in ic.FIGI[NEW_CUSIP]["data"]]}


def test_a_same_cik_registrations_new_cusip_with_its_own_composite_is_the_successor():
    """CCO 2019: Clear Channel Outdoor's 8-K12B under its own CIK; its new CUSIP 18453H106 first fails under CCO on
    2019-05-03, OpenFIGI's BBG000SSC5C9 (R2: two securities)."""
    assert ic.outcome(CCO) == [("2019-05-12", "exchange_transfer", 304, "BBG000SSC5C9", "own_registration")]


def test_a_new_cusip_on_the_securitys_own_composite_is_the_security_going_on(monkeypatch):
    monkeypatch.setitem(ic.FIGI, NEW_CUSIP, _rows(CCO))
    assert ic.outcome(CCO) == [("2019-05-12", "exchange_transfer", 304, CCO, "own_registration")]


@pytest.mark.parametrize("answer", [{"error": "No identifier found."}, "two"], ids=["error", "several"])
def test_an_unsettled_new_cusip_links_nothing(monkeypatch, answer):
    """OKE 2026's new CUSIP is not in the cache (an error answer); several composites settle nothing either: the
    row keeps successor_unknown."""
    if answer == "two":
        answer = {"data": _rows("BBG000SSC5C9")["data"] + _rows("BBG000SSC5C0")["data"]}
    monkeypatch.setitem(ic.FIGI, NEW_CUSIP, answer)
    assert ic.outcome(CCO) == [("2019-05-12", "exchange_transfer", 304, "", "")]
    assert ic.outcome("BBG000BQHGR6") == [("2026-09-28", "exchange_transfer", 304, "", "")]       # OKE 2026


def test_the_new_issuer_link_reads_the_registrants_own_conversion_sentence():
    """HHC 2023: "each outstanding share of the Company's common stock ... was automatically converted into one
    share of common stock ... of Holdco", Holdco being Howard Hughes Holdings Inc., first filed 2023-08-11."""
    edgar = ic.FixtureEdgar()
    assert ic.outcome("BBG000MJRJJ2", edgar=edgar) == [
        ("2023-08-24", "exchange_transfer", 304, "BBG01HTMDZ54", "new_issuer")]
    assert "0001104659-23-090461" in edgar.texts_read
```

In `tests/test_issuer_role_cases.py`, replace

```python
RULES_DONE: set[str] = {"stage5", "r1"}
```

with

```python
RULES_DONE: set[str] = {"stage5", "r1", "links"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_successor_links.py tests/test_issuer_role_cases.py`
Expected: FAIL: CCO, HHC, BHI, CMCSK, HUB-B and CWENA keep a blank successor (the two "links nothing" tests and
OKE pass already).

- [ ] **Step 3: Implement**

In `src/delist_detection/pipeline.py`, replace

```python
def _find_successors(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                     sightings: dict[str, list[Sighting]], acquirers: dict[str, AddedSecurity],
                     line_successors: Mapping[str, LineSuccessor] = {}, ftd: FtdIndex | None = None) -> _Successors:
```

with

```python
def _own_registration_link(ctx: _RunContext, e: Delisting, texts: list[str], day: date, securities: dict[str, Security],
                           sec_cusips: dict[str, list[str]], ftd: FtdIndex, taken: Collection[str],
                           found: _Successors) -> tuple[str, str] | None:
    """Sub-plan 5c, rule 4 under the same CIK: the registrant's own successor registration (8-K12B/8-K12G3 in its
    filing list, `handoffs.own_continuation_filing`) moved the holders, one for one, to a new CUSIP -- the one the
    texts name that is not the security's own (ONEOK 2026's notice: "ONEOK, Inc. (New, CUSIP: 30609A109)"), else
    the first fails row's under one of its tickers in [day, day + SUCCESSOR_AFTER_DAYS] (Clear Channel Outdoor
    2019's 18453H106). R2 on that CUSIP's one US composite: the security's own is the security going on (it is its
    own successor); another is its successor, added as a security of its own (`AddedLineSuccessor`) when the run
    has none. Several composites or an OpenFIGI error: no link."""
    if own_continuation_filing(ctx.clients.edgar.recent_filings(e.cik), day) is None:
        return None
    mine = set(sec_cusips.get(e.sec_id, []))
    named = sorted(text_cusips(texts) - mine)
    tickers = securities[e.sec_id].own_tickers() | {e.ticker}
    hi = (day + timedelta(days=SUCCESSOR_AFTER_DAYS)).isoformat()
    rows = sorted((r for t in tickers for r in ftd.by_symbol(t, day.isoformat(), hi)
                   if r.cusip not in mine and is_line_symbol(r.symbol)), key=lambda r: (r.date, r.cusip))
    cusip = named[0] if len(named) == 1 else (rows[0].cusip if rows and not named else None)
    if cusip is None:
        return None
    cands = composites(ctx.clients.figi.map([cusip_job(cusip)])[0])
    if cands is None or len(cands) != 1:
        return None
    x = cands[0]
    if x.composite == e.sec_id:
        return e.sec_id, BY_OWN_REGISTRATION
    new_rows = [r for r in ftd.trading_rows([cusip]) if r.symbol in tickers]
    if not new_rows:
        return None
    if x.composite not in securities and x.composite not in taken and x.composite not in found.added:
        found.added[x.composite] = AddedLineSuccessor(
            Security(x.composite, e.cik, share_class_from_name(x.name), x.name, x.security_type, False, "cusip"),
            new_rows[0].symbol, new_rows[0].date, new_rows)
    return x.composite, BY_OWN_REGISTRATION


def _terms_links(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                 starts: dict[str, SecurityStart], sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                 taken: Collection[str], found: _Successors) -> None:
    """Sub-plan 5c, rules 3 and 4: an exchange transfer still without a successor whose registrant's filings
    state each share of its class became one share, with no cash (R1, `exchange_terms.own_exchange` around
    `successors.successor_anchor`), takes the security of the run that statement names
    (`successors.successor_by_terms`: the same issuer's other class, CMCSK into CMCSA, HUB-B into HUBB, CWENA
    into CWEN; a new issuer's, BHI into BHGE, HHC into HHH), else the line its own successor registration moved
    the holders to (`_own_registration_link`: CCO 2019, OKE 2026). The link's `how` is "terms" or
    "own_registration"."""
    edgar = ctx.clients.edgar
    ages = _IssuerAge(edgar)
    for e in delistings:
        if e.key in found.links or SUCCESSOR_UNKNOWN not in e.flags or e.sec_id not in securities:
            continue
        watch = DegradedWatch()
        own, texts, day = _own_exchange(edgar, e, securities[e.sec_id])
        link = None
        if own is not None and own.one_for_one:
            link = successor_by_terms(e, own, day, starts, issuer_since=ages.since, issuer_names=ages.names)
            if link is None:
                link = _own_registration_link(ctx, e, texts, day, securities, sec_cusips, ftd, taken, found)
        if watch.tripped():
            found.review.append(degraded_item(e.sec_id, e.ticker, e.cik, "the successor terms reading",
                                              delist_date=e.delist_date))
            found.degraded.append(e.key)
        if link is not None:
            found.links[e.key] = link


def _find_successors(ctx: _RunContext, delistings: list[Delisting], securities: dict[str, Security],
                     sightings: dict[str, list[Sighting]], acquirers: dict[str, AddedSecurity],
                     line_successors: Mapping[str, LineSuccessor] = {}, ftd: FtdIndex | None = None,
                     sec_cusips: dict[str, list[str]] | None = None) -> _Successors:
```

replace

```python
    wired in default_clients). `_link_successors` records the answer on the
    delistings."""
```

with

```python
    wired in default_clients). Before the 8-K12B search, sub-plan 5c's links
    (`_terms_links`): the security or the line the registrant's own filings say
    the shares became, one for one. `_link_successors` records the answer on the
    delistings."""
```

replace

```python
    linked = set(found.links)
    starts: dict[str, SecurityStart] = {
        sid: SecurityStart(sig[0].day, securities[sid].issuer_cik, {x.value for x in sig})
        for sid, sig in sightings.items() if sig}
    for sid, a in acquirers.items():
        starts[sid] = SecurityStart(a.span()[0], a.security.issuer_cik, {a.ticker})
    for e in delistings:                       # a security of this run
        if e.key in linked:
            continue
        in_run = successor_in_run(e, starts) if SUCCESSOR_UNKNOWN in e.flags else None
        if in_run is not None:
            found.links[e.key] = in_run
```

with

```python
    linked = set(found.links)
    starts = _starts(securities, sightings, acquirers)
    for e in delistings:                       # a security of this run
        if e.key in linked:
            continue
        in_run = successor_in_run(e, starts) if SUCCESSOR_UNKNOWN in e.flags else None
        if in_run is not None:
            found.links[e.key] = in_run
    # what the registrant's filings say the shares became, one for one (sub-plan 5c, rules 3 and 4)
    _terms_links(ctx, delistings, securities, starts, sec_cusips or {}, ftd or FtdIndex(), set(acquirers), found)
    linked = set(found.links)
```

and replace

```python
    successors = _find_successors(ctx, delistings, securities, search.sightings, {**payouts.added, **r1.added},
                                  lines.successors, ftd)                                            # 9
```

with

```python
    successors = _find_successors(ctx, delistings, securities, search.sightings, {**payouts.added, **r1.added},
                                  lines.successors, ftd, sec_cusips)                                # 9
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_successor_links.py tests/test_issuer_role_cases.py tests/test_pipeline.py tests/test_pipeline_prefetch.py`
Expected: PASS. Then the full suite: 2305 passed, 240 xfailed.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/pipeline.py tests/test_successor_links.py tests/test_issuer_role_cases.py
git commit -m "Stage 9 links a transfer to what its registrant's filings say the shares became, one for one (sub-plan 5c, rules 3 and 4)"
```

---

### Task 7: Stage 9d, the added successors' own Form 25 endings

Tier: standard.

Carried from 5b (its Ruling 9): the line successors stage 4b adds (California Resources' 2016 line, Dynegy's 2010
line, ODP Corp) and the 8-K12B successors (TiVo Corp, which 5c adds for ROVI) have no observations, so stage 5 never
searched their Form 25s; their chains stop at a successor with no ending.

**Files:**
- Modify: `src/delist_detection/delistings.py`, `src/delist_detection/added_securities.py`,
  `src/delist_detection/pipeline.py`
- Create: `tests/test_successor_endings.py`
- Test: `tests/test_run_provenance.py`

**Interfaces:**
- Consumes: today's `DelistingFinder`, `pipeline._context_builder`, `listed_today`, `ticker_sightings`,
  `TickerEra`, `Observation`, `AddedLineSuccessor`, `AddedSuccessor`, `AddedAcquirer`, `pipeline._IssuerAnswers`.
- Produces: `DelistingFinder.find(ctx, *, fallback=True)`; `AddedSuccessor.last: str = ""`;
  `pipeline._DelistingSearch.finder`; `pipeline.PREDECESSOR_FORM25_DAYS` (30); `pipeline._SuccessorEndings(
  delistings, securities, cusips, review)`; `pipeline._successor_endings(ctx, finder, added, securities, sec_cusips,
  ftd, answers) -> _SuccessorEndings`; the manifest stage "successor endings".

- [ ] **Step 1: Write the failing tests**

Create `tests/test_successor_endings.py`:

```python
"""Pipeline stage 9d (sub-plan 5c): the Form 25 search for the successors the run added -- a line successor (seen
over its new CUSIP's fails rows) and an 8-K12B successor (alive from its 8-K12B until its issuer's Form 25)."""
from __future__ import annotations

from datetime import date

from delist_detection import pipeline
from delist_detection.added_securities import AddedAcquirer, AddedLineSuccessor, AddedSuccessor
from delist_detection.classifier import DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import DelistingFinder
from delist_detection.edgar import EdgarSubmission
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.manifest import StageMeter
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver

CIK, SID = 777001, "BBG000NEWLN1"
NYSE_RAW = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>New York Stock Exchange LLC</entityName>"
            "</exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
            "<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision></notificationOfRemoval>")


def _edgar(fake_edgar):
    fake_edgar.submissions_by_cik[CIK] = [
        EdgarSubmission("F25-1", "25-NSE", "2020-06-01", "", "", "primary_doc.xml"),
        EdgarSubmission("K-1", "8-K", "2020-06-01", "2020-06-01", "2.01,3.01,3.03,5.01,9.01", "k.htm"),
        EdgarSubmission("F15-1", "15-12B", "2020-06-11", "", "", "f.htm"),
        EdgarSubmission("Q-1", "10-Q", "2019-11-01", "", "", "q.htm"),
    ]
    fake_edgar.company_map["NEWC"] = {"cik_str": CIK, "ticker": "NEWC", "title": "Newco Corp"}
    fake_edgar.raws["F25-1"] = NYSE_RAW
    fake_edgar.texts["K-1"] = ("Item 3.01 Notice of Delisting. requested that trading be suspended prior to the "
                               "opening of trading on June 2, 2020 " + "x" * 300)
    return fake_edgar


def _ends(fake_edgar, monkeypatch, added, *, listed=False, form25=True):
    edgar = _edgar(fake_edgar)
    if not form25:
        edgar.submissions_by_cik[CIK] = [f for f in edgar.submissions_by_cik[CIK] if f.form != "25-NSE"]
    clients = pipeline.Clients(edgar=edgar, resolver=None, classifier=DelistClassifier(edgar, TickerResolver(edgar)),
                               figi=None, ftd_client=None, as_of=date(2026, 9, 25))
    monkeypatch.setattr(pipeline, "listed_today", lambda *a, **k: listed)
    ctx = pipeline._RunContext(clients, date(2026, 9, 25), lambda *a: None, 1, StageMeter(lambda *a: None))
    rows = [r for a in added.values() for r in getattr(a, "rows", [])]
    finder = DelistingFinder(edgar, clients.classifier)
    return pipeline._successor_endings(ctx, finder, added, {}, {}, FtdIndex(rows),
                                       pipeline._IssuerAnswers({}, {}, {}, set()))


def _security():
    return Security(SID, CIK, "COMMON", "NEWCO CORP", "Common Stock", False, "cusip")


def test_a_line_successor_takes_its_own_form25_ending(fake_edgar, monkeypatch):
    rows = [FtdRow(f"2020-0{m}-15", "65249B109", "NEWC", "NEWCO CORP", 10.0 + m) for m in range(1, 6)]
    ends = _ends(fake_edgar, monkeypatch, {SID: AddedLineSuccessor(_security(), "NEWC", "2019-06-03", rows)})
    assert [(d.sec_id, d.delist_date, d.record.bucket) for d in ends.delistings] == [
        (SID, "2020-06-11", CrspBucket.MERGER)]
    assert ends.securities[SID].eras[0].ticker == "NEWC" and ends.cusips[SID] == ["65249B109"]


def test_an_8k12b_successor_is_searched_to_the_run_date_and_its_span_runs_to_the_ending(fake_edgar, monkeypatch):
    """TiVo Corp, Rovi's successor (8-K12B 2016-09-08), merged into Xperi in 2020: no fails rows of its own."""
    a = AddedSuccessor(_security(), "NEWC", "2016-09-08")
    ends = _ends(fake_edgar, monkeypatch, {SID: a})
    assert [(d.delist_date, d.last_trade.day) for d in ends.delistings] == [("2020-06-11", date(2020, 6, 1))]
    assert a.span() == ("2016-09-08", "2020-06-01")


def test_a_successor_listed_today_or_an_acquirer_takes_no_ending(fake_edgar, monkeypatch):
    rows = [FtdRow("2020-03-15", "65249B109", "NEWC", "NEWCO CORP", 10.0)]
    assert _ends(fake_edgar, monkeypatch, {SID: AddedLineSuccessor(_security(), "NEWC", "2019-06-03", rows)},
                 listed=True).delistings == []
    assert _ends(fake_edgar, monkeypatch, {SID: AddedAcquirer(_security(), "NEWC", date(2019, 6, 3))}).delistings == []


def test_no_form25_means_no_fallback_ending(fake_edgar, monkeypatch):
    rows = [FtdRow("2020-03-15", "65249B109", "NEWC", "NEWCO CORP", 10.0)]
    ends = _ends(fake_edgar, monkeypatch, {SID: AddedLineSuccessor(_security(), "NEWC", "2019-06-03", rows)},
                 form25=False)
    assert ends.delistings == [] and ends.review == []


def test_the_predecessors_form25_at_the_successors_first_day_is_not_its_ending(fake_edgar, monkeypatch):
    """Clear Channel Outdoor 2019: the old line's 25-NSE is filed the day before the new line's first fails row."""
    rows = [FtdRow("2020-06-02", "65249B109", "NEWC", "NEWCO CORP", 10.0)]
    assert _ends(fake_edgar, monkeypatch, {SID: AddedLineSuccessor(_security(), "NEWC", "2020-05-20", rows)}
                 ).delistings == []
```

In `tests/test_run_provenance.py`, replace

```python
                                "other issuers in force", "R1 continuations"}
```

with

```python
                                "other issuers in force", "R1 continuations", "successor endings"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_successor_endings.py`
Expected: FAIL: `AttributeError: module 'delist_detection.pipeline' has no attribute '_successor_endings'`.

- [ ] **Step 3: The finder without its fallback, and an 8-K12B successor's span**

In `src/delist_detection/delistings.py`, replace

```python
    def find(self, ctx: SecurityContext) -> tuple[list[Delisting], list[ReviewItem]]:
        sec = ctx.security
```

with

```python
    def find(self, ctx: SecurityContext, *, fallback: bool = True) -> tuple[list[Delisting], list[ReviewItem]]:
        """The security's delistings and review items. `fallback=False` (pipeline stage 9d, a successor the run
        added): Form 25 matches only, no fallback ending and no review item for a security without one."""
        sec = ctx.security
```

and replace

```python
        review = scan.review
        if last_definitive is None:
```

with

```python
        review = scan.review
        if not fallback:
            return delistings, review
        if last_definitive is None:
```

In `src/delist_detection/added_securities.py`, replace

```python
    """An exchange transfer's successor, seen on its 8-K12B's filing date (never
    before the day after the predecessor's last trade)."""
    filing_date: str
    source: ClassVar[str] = "edgar_8k"

    def span(self) -> tuple[str, str]:
        return self.filing_date, self.filing_date
```

with

```python
    """An exchange transfer's successor, seen on its 8-K12B's filing date (never
    before the day after the predecessor's last trade), through `last`: the last
    trade of its own ending when the run found one (pipeline stage 9d), else that
    day alone."""
    filing_date: str
    last: str = ""
    source: ClassVar[str] = "edgar_8k"

    def span(self) -> tuple[str, str]:
        return self.filing_date, max(self.filing_date, self.last or self.filing_date)
```

- [ ] **Step 4: Stage 9d**

In `src/delist_detection/pipeline.py`, replace

```python
    ObservationError, ObservationIndex, TickerEra, eras_by_key, normalize_ticker, observation_conflicts,
)
```

with

```python
    Observation, ObservationError, ObservationIndex, TickerEra, eras_by_key, normalize_ticker, observation_conflicts,
)
```

replace (the end of `_DelistingSearch`)

```python
    sightings: dict[str, list[Sighting]]
    review: list[ReviewItem]


def _find_delistings(ctx: _RunContext, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
```

with

```python
    sightings: dict[str, list[Sighting]]
    review: list[ReviewItem]
    finder: DelistingFinder | None = None      # the sequential finder, which stage 9d reuses


def _find_delistings(ctx: _RunContext, securities: dict[str, Security], sec_cusips: dict[str, list[str]],
```

replace

```python
    ctx.meter.done("delisting search", mark)
    return _DelistingSearch(delistings, listed, sightings, review)
```

with

```python
    ctx.meter.done("delisting search", mark)
    return _DelistingSearch(delistings, listed, sightings, review, finder)
```

replace

```python
def _date_from_notices(ctx: _RunContext, added: list[Delisting], review: list[ReviewItem]) -> int:
```

with

```python
PREDECESSOR_FORM25_DAYS = 30     # stage 9d: a successor's Form 25 this close to its first day is its predecessor's


@dataclass
class _SuccessorEndings:
    """Stage 9d's answer: the endings found for the successors the run added, the securities they were searched
    as (one era over each successor's span) with their CUSIPs, and the degraded-answer review items."""
    delistings: list[Delisting] = field(default_factory=list)
    securities: dict[str, Security] = field(default_factory=dict)
    cusips: dict[str, list[str]] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)


def _successor_endings(ctx: _RunContext, finder: DelistingFinder, added: Mapping[str, AddedSecurity],
                       securities: dict[str, Security], sec_cusips: dict[str, list[str]], ftd: FtdIndex,
                       answers: _IssuerAnswers) -> _SuccessorEndings:
    """9d. The Form 25 search (`DelistingFinder.find`, Form 25 matches only: no fallback ending for a security no
    observation names) for each successor the run added: a line successor (`AddedLineSuccessor`, seen over its new
    CUSIP's fails rows: California Resources' 2016 line, Dynegy's 2010 line, ODP Corp) and an 8-K12B successor
    (`AddedSuccessor`, alive from its 8-K12B until its issuer's own Form 25: TiVo Corp, Rovi's successor). Each is
    searched as a security with one era over that span, beside the run's securities of its issuer; a successor
    listed today keeps no ending. An 8-K12B successor's span then runs to the ending's last trade."""
    clients, out = ctx.clients, _SuccessorEndings()
    mark = ctx.meter.start()
    for sid, a in sorted(added.items()):
        cik = a.security.issuer_cik
        if isinstance(a, AddedAcquirer) or cik is None or sid in securities:
            continue
        rows = list(getattr(a, "rows", []))
        first, last = a.span()
        end = last if rows else ctx.as_of.isoformat()
        era = TickerEra(a.ticker, first, end, [Observation(a.ticker, first, a.security.name),
                                               Observation(a.ticker, end, a.security.name)])
        s = replace(a.security, eras=[era])
        world = {x.sec_id: x for x in securities.values() if x.issuer_cik == cik} | {sid: s}
        cusips = {x: list(sec_cusips.get(x, [])) for x in world} | {sid: sorted({r.cusip for r in rows})}
        sightings = {x: ticker_sightings(world[x], ftd, cusips[x]) for x in world}
        watch = DegradedWatch()
        try:
            listed = listed_today(clients.figi, sid, edgar=clients.edgar, cik=cik, tickers=[a.ticker])
            found = [] if listed else finder.find(_context_builder(world, sightings, answers, ftd, cusips)(s, listed),
                                                  fallback=False)[0]
        except FATAL:
            raise
        except Exception as exc:  # one added successor must not abort the run
            ctx.log(f"{sid}: successor ending search ERROR {type(exc).__name__}: {exc}")
            out.review.append(ReviewItem(sid, a.ticker, cik, "error", f"{type(exc).__name__}: {exc}"))
            continue
        # a Form 25 filed within PREDECESSOR_FORM25_DAYS of the successor's first day removed its predecessor
        start = (date.fromisoformat(first) + timedelta(days=PREDECESSOR_FORM25_DAYS)).isoformat()
        endings = [d for d in found if d.record.successor_sec_id != sid
                   and not (d.form25_sub is not None and d.form25_sub.filing_date <= start)]
        watch.report(out.review, degraded_item(sid, a.ticker, cik, "the successor ending search",
                                               "; run again once SEC answers"), endings)
        if not endings:
            continue
        out.delistings += endings
        out.securities[sid] = s
        out.cusips[sid] = cusips[sid]
        if isinstance(a, AddedSuccessor) and endings[-1].last_trade.day is not None:
            a.last = endings[-1].last_trade.day.isoformat()
    ctx.log(f"successor endings: {len(out.delistings)} for {len(out.securities)} added successors "
            f"({', '.join(sorted(out.securities)) or 'none'})")
    ctx.meter.done("successor endings", mark)
    return out


def _date_from_notices(ctx: _RunContext, added: list[Delisting], review: list[ReviewItem]) -> int:
```

and replace

```python
        closes.update(_last_trade_closes(ctx, handoffs.added, securities, sec_cusips, ftd, ftd_lo, overrides))
```

with

```python
        closes.update(_last_trade_closes(ctx, handoffs.added, securities, sec_cusips, ftd, ftd_lo, overrides))
    ends = _successor_endings(ctx, search.finder, added, securities, sec_cusips, ftd, answers)      # 9d
    review += ends.review
    if ends.delistings:
        delistings += ends.delistings
        overrides = _apply_price_answers(given, delistings)
        closes.update(_last_trade_closes(ctx, ends.delistings, {**securities, **ends.securities},
                                         {**sec_cusips, **ends.cusips}, ftd, ftd_lo, overrides))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_successor_endings.py tests/test_run_provenance.py tests/test_pipeline.py tests/test_pipeline_prefetch.py tests/test_delistings.py`
Expected: PASS (the prefetch twin test: 9d builds no finder of its own). Then the full suite: 2310 passed, 240
xfailed.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/delistings.py src/delist_detection/added_securities.py src/delist_detection/pipeline.py tests/test_successor_endings.py tests/test_run_provenance.py
git commit -m "Stage 9d: the successors the run added take their own Form 25 endings (sub-plan 5c, carried from 5b)"
```

---

### Task 8: Docs

Tier: cheap.

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none.

- [ ] **Step 1: Commands**

In `CLAUDE.md`'s Commands block, after the line starting `python scripts/build_form25_fixtures.py`, add:

```bash
python scripts/build_issuer_role_fixtures.py  # offline: tests/fixtures/issuer_role/ (sub-plan 5c's real cases) from the local caches; rerun only to add a case
```

Run `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest` and in the line starting
`pytest   # full suite (` put the passed and xfailed counts it prints (2310 passed, 240 xfailed), and the number
of known-wrong golden cases `grep -c ',known_wrong,' data/golden_lifecycles.csv` gives.

- [ ] **Step 2: The stage list**

Replace

```
`_check_overrides`, `_last_trade_closes`, `_merger_payouts`,
`_find_successors`, `_handoffs`, `_date_from_notices` (stage 9c: a handoff continuation row's last trade day from its own Form 25's confirmed EX-99.25 notice, when before the successor's first sighting and no later than the effective date; metered as "handoff notice dates"), then the row builders and `_triage`), each with explicit
```

with

```
`_check_overrides`, `_last_trade_closes`, `_merger_payouts`,
`_r1_continuations` (stage 8b: a merger whose published terms are one share and no cash, whose registrant's filings say the same of its own shares (`exchange_terms.own_exchange`), into a new issuer at most `NEW_ISSUER_DAYS` old or the same issuer (`successors.successor_by_terms`, else the new issuer's 8-K12B), is an exchange transfer to that successor, flagged `r1_continuation`, its payout reads dropped; metered as "R1 continuations"),
`_find_successors` (stage 9, with sub-plan 5c's `_terms_links` before the 8-K12B search), `_handoffs`, `_date_from_notices` (stage 9c: a handoff continuation row's last trade day from its own Form 25's confirmed EX-99.25 notice, when before the successor's first sighting and no later than the effective date; metered as "handoff notice dates"), `_successor_endings` (stage 9d: the Form 25 search, matches only, for the line and 8-K12B successors the run added; metered as "successor endings"), then the row builders and `_triage`), each with explicit
```

(If the first line is not found exactly, find the sentence naming `_merger_payouts`, `_find_successors`, `_handoffs`
and `_date_from_notices` and make the same insertion.)

- [ ] **Step 3: The module entries**

After the `payout_extractor.py` bullet, add:

```markdown
- `exchange_terms.py` — what a filing says the registrant's own shares became (sub-plan 5c, R1): `statements`
  reads each "each share of S … converted into N shares of T" (and "received N shares of T for each share",
  "on a one-for-one basis", a cash one); `own_exchange` keeps those whose subject is the registrant's (its EDGAR
  names in the year before the event, a defined term for one, "the Company"/"its"/"our") and the security's class,
  and gives the ratio, cash in the exchange (par values, cash in lieu of fractions and special dividends set aside),
  the target clause and its names (defined terms expanded), the target's class letter, and whether readings
  disagree (`ambiguous`); `acquires` (another party's shares became the registrant's, or it issued shares under
  the merger agreement) and `distributes` ("for every four shares", kept) are the registrant's other roles;
  `read_texts` reads the 8-Ks around an ending's days and its Form 25 notice. Pure apart from `read_texts`.
```

Append one sentence to each named bullet:

- `end_of_era.py`: "Sub-plan 5c, rule 1: branches 3 and 4 never fire when `EraSignals.survived` holds (the
  classifier found no exchange of the registrant's own shares, and an acquirer's or a distributor's statement);
  `merges` says when they would."
- `classifier.py`: "Sub-plan 5c: `_survived` (rule 1, before end-of-era branches 3 and 4) and `_one_for_one` (R1:
  a one-for-one, no-cash statement of the security's class before the no-evidence default gives 304 with
  `r1_continuation`)."
- `successors.py`: "Sub-plan 5c: `successor_by_terms` (the security an R1 statement names: the same issuer's
  class the target names, or a new issuer's line, at most `NEW_ISSUER_DAYS` (1095) old, first sighted in the
  window and named by the target) and `successor_anchor` (last trade, Form 25, anchor 8-K, delisting date)."
- `added_securities.py`: "An `AddedSuccessor`'s span runs to its own ending's last trade when stage 9d found one
  (`last`)."
- `line_follow.py` (in its sentence on `_text_sources`/`text_symbols`, or as a new sentence): "`text_symbols` also
  reads "symbol … changed from X to Y" as Y (sub-plan 5c, RRI to GEN)."

- [ ] **Step 4: The invariant**

In "Non-obvious invariants", after the bullet that starts `- **A Form 25 is reached, matched and owns its row`,
add:

```markdown
- **An ending's kind follows the registrant's role and R1 (sub-plan 5c).** A registrant whose filings state no
  exchange of its own shares, and that acquired another party or distributed another company's shares, gets no
  merger from end-of-era branches 3 and 4. A one-for-one exchange with no cash (a special dividend is no cash) is a
  continuation only into a new issuer (first EDGAR filing at most 1,095 days before) or the same issuer: stage 5
  gives it when no 8-K item code decides, stage 8b rewrites a merger whose published terms say one share and no
  cash, stage 9 links a transfer to the security the statement names or to the new line its own same-CIK 8-K12B
  moved it to (OpenFIGI's CUSIP job, R2). The added successors take their own Form 25 endings (stage 9d). A text
  never decides a merger row alone: the LLM's terms must agree.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: the issuer role and successor link rules (sub-plan 5c) in CLAUDE.md"
```

---

### Task 9: The whole-branch review, one fix wave and the offline replay (controller)

Run by the controller. The review runs on model `opus`; fixes on `sonnet`, test first. Nothing here touches the
network or `output/`. **BASE** is `77d69c3`.

**Files:**
- Create: `/tmp/claude/delist_detection/5c/replay_5c.py`, `/tmp/claude/delist_detection/5c/base/` (the base
  commit's `src`), `/tmp/claude/delist_detection/5c/{base,new}_out/` (none committed).
- Modify: only what a finding's fix needs.

- [ ] **Step 1: The review**

Dispatch one reviewer (model `opus`) over `git diff 77d69c3..HEAD -- src tests scripts CLAUDE.md`, with this plan,
the spec's section 3 "5c" and the research note. Ask for defects only, each with the file, the line and an input
that breaks it, and in particular: the five Review Focus items; whether a text alone can ever decide a merger row
(stage 8b must need the published terms too); whether the role refusal can fire on a target (a statement whose
subject is the registrant's own shares, a cash one included, must block it; rename and separation words never
decide); whether a rewritten row keeps any payout read (`payouts.csv`, the contract's value columns, price
requests); whether a link can name a security of an existing issuer (more than `NEW_ISSUER_DAYS` old) or of
another class; whether stage 9d can give a successor its predecessor's Form 25; whether the prefetch pass reads
the texts the sequential pass reads (a cold run sends each text once).

- [ ] **Step 2: The offline replay over the real caches**

Write `/tmp/claude/delist_detection/5c/replay_5c.py`:

```python
"""Offline replay of the whole run (sub-plan 5c's review check): `pipeline.run` over the committed observations with
the source tree on PYTHONPATH, every client reading cache/ only, into a folder of its own; then the securities whose
contract rows or delistings changed between two such folders, and the truth set judged on each.

  PYTHONPATH=<src> python replay_5c.py run OUTDIR BASELINE_SECURITIES   # the whole run over that source tree
  python replay_5c.py diff BASEDIR NEWDIR                              # the securities whose rows changed
  PYTHONPATH=src python replay_5c.py judge BASEDIR NEWDIR              # D.mismatches on each, the cases that moved

Run from the repo root (cache/, data/, output/ and scripts/ are read from there). Offline: every request is
refused and every cache write is a no-op; an OpenFIGI job the cache lacks is an error answer; a filing text or raw
the cache lacks reads as "" (as if it said nothing), not as a failed request, so the reading rules are replayed
without the cold fetches; listed today (OpenFIGI's live answer, never cached) is the committed run's: an open
ticker_history range. The full-text searches the cache lacks fail as degraded answers (ROVI's 8-K12B search)."""
from __future__ import annotations

import csv
import importlib.util
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path.cwd()
AS_OF = date(2026, 9, 25)

# the securities the plan's prototype changed (25 in the truth set, 9 outside it)
EXPECTED = {
    "BBG000BD4VG8", "BBG000BFTJ91", "BBG000BHBK84", "BBG000BJXKD0", "BBG000BPQD31", "BBG000BQHGR6", "BBG000CGQ6M4",
    "BBG000CHWP52", "BBG000F2XXP2", "BBG000G0PPW3", "BBG000J453J8", "BBG000MJRJJ2", "BBG000VMWHH5", "BBG001YMS0B8",
    "BBG004P33PN3", "BBG01HMFL081", "BBG01HMFLTN1", "CIK104207-COMMON", "CIK1126294-COMMON", "CIK1308161-CLASS-A",
    "CIK1308161-COMMON", "CIK1363851-COMMON", "CIK38079-COMMON", "CIK48898-CLASS-B", "CIK944868-COMMON",
    "BBG000BCHG15", "BBG000BGFZR8", "BBG000BL9JQ1", "BBG000BNLX91", "BBG000F5YH15", "BBG000SSC5C9", "BBG0060B3M63",
    "BBG008FCJZ83", "BBG01GJ3NY88",
}


def offline() -> tuple[list[str], list[str]]:
    """Refuse every request and make every cache write a no-op (module docstring); returns the lists the refused
    URLs and the accessions read as blank go to."""
    import requests
    refused: list[str] = []
    blank: list[str] = []

    class Refuse:
        def __init__(self, *a, **k):
            pass

        def get(self, url, *a, **k):
            refused.append(str(url))
            raise requests.ConnectionError(f"offline: {url}")

        post = request = get

        def mount(self, *a, **k):
            pass

        def close(self):
            pass

    def refuse(url, *a, **k):
        refused.append(str(url))
        raise requests.ConnectionError(f"offline: {url}")

    requests.Session = Refuse
    requests.get = requests.post = refuse

    def no_write(*a, **k):
        return None
    for mod in ("edgar", "sec_http", "midas", "nasdaq_halts", "openfigi", "ticker_resolver", "cik_lookup", "ftd",
                "llm_merger_extractor"):
        m = __import__(f"delist_detection.{mod}", fromlist=["x"])
        for name in ("write_atomic", "clean_orphan_temps"):
            if hasattr(m, name):
                setattr(m, name, no_write)
    import delist_detection.atomic_io as aio
    import delist_detection.sec_limiter as lim
    aio.clean_orphan_temps = no_write
    lim.throttle = lambda *a, **k: None
    lim.use_machine_wide_limit = lambda *a, **k: None

    from delist_detection.edgar import EdgarClient
    from delist_detection.openfigi import OpenFigiClient
    real_text, real_raw = EdgarClient.fetch_filing_text, EdgarClient.fetch_filing_raw

    def text(self, cik, accession, primary_doc):
        if not (self.cache_dir / "text" / f"{accession.replace('-', '')}.txt").exists():
            blank.append(accession)
            return ""
        return real_text(self, cik, accession, primary_doc)

    def raw(self, cik, accession):
        if not (self.cache_dir / "raw" / f"{accession.replace('-', '')}.txt").exists():
            blank.append(accession)
            return ""
        return real_raw(self, cik, accession)

    def post(self, path, payload):
        refused.append(f"openfigi{path}")
        return [{"error": "offline"} for _ in payload] if path == "/mapping" else {"data": []}
    EdgarClient.fetch_filing_text, EdgarClient.fetch_filing_raw, OpenFigiClient._post = text, raw, post
    return refused, blank


def _listed_from_output() -> dict[str, bool]:
    with open(ROOT / "output" / "securities.csv", newline="", encoding="utf-8") as fh:
        out = {r["sec_id"]: False for r in csv.DictReader(fh)}           # no range at all: not listed
    with open(ROOT / "output" / "ticker_history.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["sec_id"]] = out.get(r["sec_id"], False) or r["valid_to"] == ""
    return out


def _clients(index):
    from delist_detection.cik_lookup import CikLookupClient
    from delist_detection.classifier import DelistClassifier
    from delist_detection.edgar import EdgarClient
    from delist_detection.ftd import FtdClient
    from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor
    from delist_detection.midas import MidasClient
    from delist_detection.nasdaq_halts import NasdaqHaltClient
    from delist_detection.openfigi import OpenFigiClient
    from delist_detection.payout_extractor import PayoutExtractor
    from delist_detection.pipeline import Clients
    from delist_detection.ticker_resolver import TickerResolver
    spec = importlib.util.spec_from_file_location("cu", ROOT / "scripts" / "classify_universe.py")
    cu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cu)
    cache = ROOT / "cache"
    edgar = EdgarClient(cache_dir=cache / "edgar", sleep=lambda s: None, today=AS_OF)
    resolver = TickerResolver(edgar, rename_map=cu.KNOWN_RENAMES,
                              manual_overrides={k: v for k, v in cu.MANUAL_OVERRIDES.items() if v > 0},
                              cache_path=cache / "ticker_resolution.json", observed_names=index.name_on,
                              cik_pins=index.cik_pin_on, today=AS_OF, batch_writes=True,
                              name_index=CikLookupClient(cache / "sec_data" / "cik_lookup").index)

    class NoLlm:                 # the committed run's LLM answers are all cached (model gpt-5.4)
        def extract(self, *a, **k):
            raise RuntimeError("offline: no LLM call")
    return Clients(edgar=edgar, resolver=resolver, classifier=DelistClassifier(edgar, resolver, today=AS_OF),
                   figi=OpenFigiClient(cache / "openfigi", "offline-key", sleep=lambda s: None),
                   ftd_client=FtdClient(cache / "sec_data" / "ftd"), midas=MidasClient(cache / "sec_data" / "midas"),
                   halts=NasdaqHaltClient(cache / "nasdaq_halts", sleep=lambda s: None, today=AS_OF),
                   payout_extractor=PayoutExtractor(edgar),
                   llm_extractor=LLMMergerTermsExtractor(edgar, NoLlm(), model="gpt-5.4", cache_dir=cache / "llm"),
                   as_of=AS_OF)


def run(out_dir: str, baseline: str) -> None:
    refused, blank = offline()
    import delist_detection.pipeline as P
    from delist_detection.observations import ObservationIndex, load_observations
    from delist_detection.review_triage import load_decisions
    from delist_detection.scorecard import load_config
    from delist_detection.store import read_table
    listed = _listed_from_output()
    P.listing_answers = lambda figi, ids: {}
    P.listed_today = lambda figi, sid, **k: listed.get(sid)
    index = ObservationIndex(load_observations(ROOT / "data" / "observations.csv"))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    summary = P.run(index, _clients(index), P.Overrides(), out_dir=Path(out_dir), tol=0.15, limit=None, sec_workers=1,
                    review_decisions=load_decisions(ROOT / "data" / "review_decisions.csv"),
                    scorecard=load_config(ROOT / "data" / "scorecard.json"),
                    id_baseline=read_table("securities", Path(baseline)))
    hosts: dict[str, int] = defaultdict(int)
    for u in refused:
        hosts[u.split("/")[2] if "//" in u else u[:40]] += 1
    print("buckets", summary.buckets)
    print("refused", len(refused), dict(hosts), "uncached texts read as blank", len(set(blank)))


def _rows(folder: str, name: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with open(Path(folder) / name, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["sec_id"]].append(r)
    return out


DL_KEYS = ("delist_date", "bucket", "crsp_code", "last_trade_date", "successor_sec_id", "ticker_successor_sec_id")


def diff(base: str, new: str) -> None:
    truth = {r["sec_id"]: r["ticker"] for r in csv.DictReader(open(ROOT / "data/diagnosis_truth.csv"))}
    changed: dict[str, list[str]] = defaultdict(list)
    for name, keys in (("contract/delistings.csv", None), ("contract/security_history.csv", None),
                       ("delistings.csv", DL_KEYS)):
        a, b = _rows(base, name), _rows(new, name)
        for sid in sorted(set(a) | set(b)):
            def view(rows):
                return sorted(tuple((k, r[k]) for k in (keys or [c for c in r if c != "verdict"])) for r in rows)
            if view(a.get(sid, [])) != view(b.get(sid, [])):
                changed[sid].append(name)
    secs_a, secs_b = _rows(base, "securities.csv"), _rows(new, "securities.csv")
    for sid in sorted(set(secs_b) - set(secs_a)):
        changed[sid].append("securities.csv (added)")
    for sid in sorted(set(secs_a) - set(secs_b)):
        changed[sid].append("securities.csv (removed)")
    da, db = _rows(base, "delistings.csv"), _rows(new, "delistings.csv")
    print(f"changed {len(changed)}: {sum(s in truth for s in changed)} in the truth set, "
          f"{sum(s not in truth for s in changed)} outside")
    for sid in sorted(changed, key=lambda s: (s not in truth, s)):
        tag = "" if sid in EXPECTED else "  << NOT EXPECTED"
        print(("T " if sid in truth else "  ") + f"{sid} {truth.get(sid, '')}: {', '.join(changed[sid])}{tag}")
        for label, rows in (("base", da.get(sid, [])), ("new ", db.get(sid, []))):
            print(f"   {label}: " + " | ".join(f"{r['delist_date']} {r['bucket']} {r['crsp_code']} "
                                              f"lt={r['last_trade_date']} succ={r['successor_sec_id']}" for r in rows))
    print("expected but unchanged:", sorted(EXPECTED - set(changed)) or "none")
    print("changed but not expected:", sorted(set(changed) - EXPECTED) or "none")


def judge(base: str, new: str) -> None:
    from delist_detection.diagnosis_truth import LibraryRows, judge_case, load_diagnosis_truth
    from delist_detection.lifecycle import Tables
    cases = load_diagnosis_truth(ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_legs.csv")
    libs = [LibraryRows.of(Tables.read(Path(d))) for d in (base, new)]
    totals, moved = [0, 0], []
    for c in cases:
        found = [judge_case(c, lib).mismatches for lib in libs]
        totals = [t + len(f) for t, f in zip(totals, found)]
        if [str(m) for m in found[0]] != [str(m) for m in found[1]]:
            moved.append((c.ticker, c.case_id, c.status, c.fixed_by, len(found[0]), len(found[1]),
                          [m.field for m in found[1]]))
    print(f"D.mismatches {totals[0]} -> {totals[1]}")
    for m in sorted(moved):
        print(*m)


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    {"run": run, "diff": diff, "judge": judge}[cmd](*rest)
```

Then, from the repo root (about 5 minutes for each run; run them one after the other):

```bash
mkdir -p /tmp/claude/delist_detection/5c/base
git archive -o /tmp/claude/delist_detection/5c/base.tar 77d69c3 src
~/miniconda3/envs/rdagent4qlib/bin/python -c "import tarfile; tarfile.open('/tmp/claude/delist_detection/5c/base.tar').extractall('/tmp/claude/delist_detection/5c/base')"
git show 77d69c3:output/securities.csv > /tmp/claude/delist_detection/5c/base_securities.csv
EDGAR_USER_AGENT="offline replay replay@example.com" PYTHONPATH=/tmp/claude/delist_detection/5c/base/src ~/miniconda3/envs/rdagent4qlib/bin/python /tmp/claude/delist_detection/5c/replay_5c.py run /tmp/claude/delist_detection/5c/base_out /tmp/claude/delist_detection/5c/base_securities.csv
EDGAR_USER_AGENT="offline replay replay@example.com" PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python /tmp/claude/delist_detection/5c/replay_5c.py run /tmp/claude/delist_detection/5c/new_out /tmp/claude/delist_detection/5c/base_securities.csv
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python /tmp/claude/delist_detection/5c/replay_5c.py diff /tmp/claude/delist_detection/5c/base_out /tmp/claude/delist_detection/5c/new_out
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python /tmp/claude/delist_detection/5c/replay_5c.py judge /tmp/claude/delist_detection/5c/base_out /tmp/claude/delist_detection/5c/new_out
```

(`git show ... > file` is a redirect, not a pipe.) Expected: the base run prints `refused 0` and
`uncached texts read as blank 0` (the committed run is fully cached); the new run prints
`uncached texts read as blank 127` and its `R1 continuations:` log line names 22 merger rows (the 13 truth rows of
the table above, ASH, CSC, HFC, WWE and STE, and XRX, PNFP, VNOM and ANAT, which the handoff rewrote before and now
keep the same successor). Then `changed 34: 25 in the truth set, 9 outside`, `expected but unchanged: none`,
`changed but not expected: none`, and `D.mismatches 588 -> 479` (the planning prototype's result). Any other
security in either list is a defect, or a change of the local cache since planning: read its rows before the fix
wave. The base replay itself differs from the committed `output/` on two securities (SKYF and AON 2012, an
offline-replay artefact of listed today and a resolver tier); they are the same in both replays.

- [ ] **Step 3: One fix wave**

Each finding of Steps 1 and 2 that the controller accepts becomes one fix (sonnet): a failing test first (on
`FakeEdgar`, the doubles, or a new case in `tests/fixtures/issuer_role/` by adding it to the builder's `CASES` or
`SUPPORT` and rebuilding), then the fix, then the full suite green. Rerun Step 2 after the wave; its result must be
the expected one, or each difference explained in the commit message. Record the findings that were not fixed, and
why, for Task 12's report.

- [ ] **Step 4: Commit**

```bash
git add -A src tests scripts CLAUDE.md
git commit -m "Sub-plan 5c: the whole-branch review's fixes"
```

(Skip when the wave changed nothing.)

---

### Task 10: The full network run (controller)

Run by the controller, not an implementer. **BASE** below is `77d69c3`, the commit 5c started from: its `output/`
is the run before 5c (no earlier task changes `output/`).

**Files:**
- Modify (by the run): `output/` (the nine tables, `output/contract/`, `scorecard.json`, `run_manifest.json`,
  `run.log`).
- Create: `output/diagnose_unknown_report/loop/5c/scorecard_before.txt`, `.../loop/5c/cases_before.md`;
  `/tmp/claude/delist_detection/5c/cases_5c.py` (not committed).

- [ ] **Step 1: Record the numbers before**

Write `/tmp/claude/delist_detection/5c/cases_5c.py` (Task 12 runs it again for "after"):

```python
"""The truth cases 5c moves (fixed_by 5c, and the other truth cases its rules move or must keep): each one's status
and its mismatches against the run under output/, as markdown table rows. Run from the repo root."""
from pathlib import Path

from delist_detection.diagnosis_truth import LibraryRows, judge_case, load_diagnosis_truth
from delist_detection.lifecycle import Tables

ROOT = Path.cwd()
OTHER = {"BBG000CGQ6M4", "BBG000G0PPW3", "BBG000BJXKD0",           # PX, AMSG, WR (5e rows R1 moves)
         "BBG0038K9G41", "BBG000BJCFP1", "BBG000BSVZM9", "BBG000BM1RP0", "BBG000K1T0M8", "BBG000BT0093",
         "BBG000PYZSR8"}                                             # LVNTA, JEF, SGP, FCL, LGFA, SIRI, CHTR
cases = load_diagnosis_truth(ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_legs.csv")
lib = LibraryRows.of(Tables.read(ROOT / "output"))
print("| ticker | case | status | fixed_by | mismatches | which |")
print("| --- | --- | --- | --- | --- | --- |")
for c in sorted((c for c in cases if c.fixed_by == "5c" or c.sec_id in OTHER), key=lambda c: (c.ticker, c.case_id)):
    j = judge_case(c, lib)
    print(f"| {c.ticker} | {c.case_id} | {c.status} | {c.fixed_by} | {len(j.mismatches)} | "
          f"{'; '.join(str(m) for m in j.mismatches)} |")
```

Then, before the run changes `output/`:

```bash
mkdir -p output/diagnose_unknown_report/loop/5c
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py > output/diagnose_unknown_report/loop/5c/scorecard_before.txt
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python /tmp/claude/delist_detection/5c/cases_5c.py > output/diagnose_unknown_report/loop/5c/cases_before.md
git show 77d69c3:output/securities.csv > /tmp/claude/delist_detection/5c/base_securities.csv
```

Expected: exit 0 each; the metric lines include `D.mismatches 588`; the cases table has 35 rows (the 25 rows with
fixed_by 5c and the 10 others).

- [ ] **Step 2: Make sure no other SEC client runs**

Ask the operator whether a terminal run is going (it uses another lock file), and check
`ps aux | grep -c classify_universe` shows none but the grep (not a git pipe). Do not start while one runs.

- [ ] **Step 3: Run**

With Bash `run_in_background: true`, `timeout: 7200000` and `allowed_domains`: `data.sec.gov`, `www.sec.gov`,
`efts.sec.gov`, `api.openfigi.com`, `api.nasdaq.com`, `www.nasdaqtrader.com`, `api.openai.com`:

```bash
DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations data/observations.csv --extract-merger-terms-llm --as-of 2026-09-25 --sec-workers 4 --id-baseline /tmp/claude/delist_detection/5c/base_securities.csv > output/run.log 2>&1
```

Expected: this run is not warm. It fetches about 130 8-K texts and Form 25 raws the readings need (stage 5's role
and R1 windows, stage 8b's and 9's), the submissions of a few new successor issuers (TiVo Corp, CIK 1675820), the
8-K12B search for ROVI ("Rovi Corp" around 2016-09-07), the OpenFIGI CUSIP jobs of the new CUSIPs (ONEOK's
30609A109, GenOn's 37244E107 for RRI's line follow), and ODP Corp's 2025 Form 25 raw. A rewritten merger sends no
new LLM call. Every rerun of this task passes the same `--id-baseline`.

- [ ] **Step 4: Check the run before trusting it**

- The tool output has no `<sandbox_violations>` block. A denied host means some answers rested on failures (a
  blocked api.openai.com fails silently: the LLM terms are missing): add the host and rerun.
- The exit code is 0, or 3 with only `resolution_degraded` rows the banner names (then rerun once SEC answers; a
  run is accepted only with no `error` or `resolution_degraded` row in `output/review.csv`).
- `grep -n "R1 continuations:" output/run.log` names the 22 rows of Task 9's replay, and ROVI (`BBG000BJ9D07`) when
  the 8-K12B search found TiVo Corp. Any other row: read its `r1_rebucketed` review row before going on.
- `grep -n "successor endings:" output/run.log` names DYN's (`BBG000BNLX91`) and CRC's (`BBG0060B3M63`) lines, and
  ODP Corp (`BBG00R24W7X2`) and TiVo Corp when their Form 25s are read.
- `grep -c "OpenFIGI unavailable" output/run.log` is 0.

- [ ] **Step 5: The numbers after**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py`
Expected: `D.mismatches` about 470 (479 offline, less OKE's and ROVI's network-only links). Note any `DROP`,
`GOLDEN FAILING` and `DIAGNOSIS FAILING` line for Task 12 (LVNTA, LGFA and SIRI, `pass` truth cases, must not
fail).

- [ ] **Step 6: Commit the run**

```bash
git add output
git commit -m "Sub-plan 5c: full run with the issuer role and successor link rules (before the truth loop)"
```

---

### Task 11: The truth loop (controller)

Run by the controller. At most 3 rounds, at most 5 agents at a time (the workflow enforces both).

**Files:**
- Modify (by the loop and the controller): `data/diagnosis_truth.csv`, `data/diagnosis_truth_changes.csv`,
  `output/diagnose_unknown_report/loop/diagnosed.csv`, `output/regression_report.csv`.
- Create (by the loop): `output/diagnose_unknown_report/loop/5c/round-<N>/{cases.csv,reports/,records/,summary.md}`;
  `/tmp/claude/delist_detection/5c/regression_kinds_5c.py`, `/tmp/claude/delist_detection/5c/preruling_5c.py` (not
  committed).

- [ ] **Step 1: Read round 1's regressions by kind before spending agents**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/truth_loop_round.py --label 5c --base 77d69c3 --round 1`
Expected: one JSON line with `renamed`, `mismatches_new`, `regressions_new` and the cases.

Write `/tmp/claude/delist_detection/5c/regression_kinds_5c.py`:

```python
"""Round 1's regression report (output/regression_report.csv) by security: what changed, and whether the plan's
offline replay expected the security to move. Run from the repo root after scripts/truth_loop_round.py."""
import csv
from collections import defaultdict
from pathlib import Path

EXPECTED = {
    "BBG000BCHG15": "ASH 2016 R1 continuation into Ashland Global (8b; expected new_right)",
    "BBG000BGFZR8": "CSC 2017 R1 continuation into DXC (8b; expected new_right)",
    "BBG000BL9JQ1": "HFC 2022 R1 continuation into HF Sinclair (8b; expected new_right)",
    "BBG000F5YH15": "WWE 2023 R1 continuation into TKO (8b; expected new_right)",
    "BBG008FCJZ83": "STE 2019 R1 continuation into STERIS plc (8b; expected new_right)",
}
POSSIBLE = {
    "BBG000BX5ZF5": "XRX 2019 (8b now; the handoff's successor before)",
    "BBG000C1XKF6": "PNFP 2026 (8b now; the handoff's successor before)",
    "BBG006G57XG0": "VNOM 2025 (8b now; the handoff's successor before)",
    "BBG000BBY4T5": "ANAT 2020 (8b now; the handoff's successor before)",
}
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

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python /tmp/claude/delist_detection/5c/regression_kinds_5c.py`
Expected: every regressed security is `expected` or `possible`; each expected one changes from a merger to an
exchange transfer whose successor is the new holding company (value rule `continuation`, its stock terms blank).
The 9d endings (DYN's and CRC's lines, ODP Corp, TiVo Corp) and the added successors (BBG000SSC5C9,
BBG01GJ3NY88) sit on truth successor chains, which the report leaves out. An `UNEXPECTED` security is read by
kind:
- a branch-3/4 merger the role refusal made a transfer or a compliance failure (its `evidence["survived"]`
  sentence came from a text the offline replay could not read): a target misread as an acquirer is a bug;
- a merger stage 8b rewrote (its `r1_rebucketed` row): a successor that is not a new holding company or the same
  issuer is a bug;
- anything else is a bug.
A bug: write its failing test (a case added to `scripts/build_issuer_role_fixtures.py`'s `CASES` and the fixture
rebuilt, or a `FakeEdgar` test), fix it as a new task (test first, sonnet), rerun Task 10 (its `--id-baseline` too),
move `loop/5c/round-1` aside and redo this step. That happened twice in 5a.

- [ ] **Step 2: The operator's pre-ruling (RRI, SXCI, NWS-A, NCRA)**

Write `/tmp/claude/delist_detection/5c/preruling_5c.py`:

```python
"""The operator's pre-ruling of 2026-10-04 for sub-plan 5c: RRI, SXCI, NWS-A and NCRA, "no ending" truth rows, are
re-shaped to ending_moved (every scored field `*`) when the run follows their line to a real later ending -- the
run's last real ending of the case's security (or of the security output/contract/id_changes.csv renamed it to,
which the row then names) is after the case's date -- with change-log rows. A case whose line the run did not
follow is left as it is and printed. Run from the repo root after round 1's script and before the workflow;
--dry-run prints only."""
import argparse
import csv
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection.diagnosis_truth import COLUMNS, NOT_SCORED, SCORED, load_legs, parse_rows

ROOT = Path.cwd()
CASES = {"CIK1126294-COMMON_2010-12-03": "RRI", "CIK1363851-COMMON_2012-07-24": "SXCI",
         "CIK1308161-COMMON_2013-07-01": "NWS-A", "CIK1308161-CLASS-A_2013-06-28": "NCRA"}
REPORT = "docs/superpowers/plans/research/2026-10-04-5c-issuer-successors.md"
WHY = ("operator pre-ruling 2026-10-04 (5c plan): the run follows the line to a real later ending ({}); the old "
       "event is not it")
p = argparse.ArgumentParser()
p.add_argument("--dry-run", action="store_true")
args = p.parse_args()


def read(name: str) -> list[dict[str, str]]:
    with open(ROOT / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


renames = {r["old_sec_id"]: r["new_sec_id"] for r in read("output/contract/id_changes.csv")}
endings: dict[str, str] = {}
for r in read("output/delistings.csv"):
    if r["successor_sec_id"] != r["sec_id"]:
        endings[r["sec_id"]] = max(endings.get(r["sec_id"], ""), r["delist_date"])
truth_path, changes_path = ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_changes.csv"
rows = dl.read_csv(truth_path)
changes = []


def set_cell(r: dict, field: str, value: str, why: str) -> None:
    if r[field] != value:
        changes.append({"case_id": r["case_id"], "field": field, "old": r[field], "new": value, "reason": why,
                        "report": REPORT})
        r[field] = value


for r in rows:
    if r["case_id"] not in CASES:
        continue
    sec = renames.get(r["sec_id"], r["sec_id"])
    last = endings.get(sec, "")
    if not last or last <= r["case_id"].rsplit("_", 1)[1]:
        print(f"{CASES[r['case_id']]}: not followed (its last real ending {last or 'none'}); left as it is")
        continue
    why = WHY.format(f"{sec} {last}")
    set_cell(r, "sec_id", sec, why)
    set_cell(r, "shape", "ending_moved", why)
    for f in SCORED:
        set_cell(r, f, NOT_SCORED, why)
    set_cell(r, "internal_last_trade_date", "", why)
    r["note"] = f"{r['note']}; {why}"
    print(f"{CASES[r['case_id']]}: re-shaped to ending_moved (the line ends {last} as {sec})")
parse_rows(rows, str(truth_path), load_legs(ROOT / "data/diagnosis_truth_legs.csv"))     # validates the rows
print(len(changes), "truth change rows")
if not args.dry_run and changes:
    dl.write_together([(truth_path, COLUMNS, rows),
                       (changes_path, dl.CHANGE_COLUMNS, dl.read_csv(changes_path) + changes)])
```

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python /tmp/claude/delist_detection/5c/preruling_5c.py --dry-run`,
check what it prints, then the same without `--dry-run`. Expected: RRI is re-shaped when the network run's line
follow took GEN to the 2012 NRG merger (its row then names the security RRI's placeholder was renamed to, if any);
SXCI, NWS-A and NCRA are left (their lines end at the case date, now as continuations into CTRX and FOXA or a
transfer: Ruling 9). Then rerun round 1's script (the Step 1 command): a re-shaped row that now matches leaves the
round's cases.

- [ ] **Step 3: Run the loop**

Run the Workflow tool with `scriptPath: ".claude/workflows/diagnosis-truth-loop.js"` and
`args: {"label": "5c", "base": "77d69c3"}`.

Expected: up to 3 rounds; each diagnoses and verifies its cases (regression mode for rows outside the truth set,
mismatch mode for truth rows), writes the records back, and runs `update_truth.py`, which flips every `known_wrong`
truth case the run now matches to `pass` (BHI, HHC, CMCSK, HUB-B, CWENA, CCO, DOW, SBGI, DISCK, DISCA, WAG, DTV,
KRFT, ROVI, and 5e's PX, AMSG and WR should). The agents judge R1 by the operator's reading: a one-for-one, no-cash
exchange into a new holding company (at most about 3 years old) or the same issuer is a continuation; a special
dividend is never consideration. Note the wall time and tokens for the report.

- [ ] **Step 4: Settle what the loop could not**

- A `pending` ledger row, or a regression with no record or no skeptic: settle it from the record's own text and
  the filings it cites, under the operator's delegated autonomy. In 5a and 5b most were pending only on "inferred"
  confidence with the skeptic upholding them; the agents sometimes label old and new against their own text (HON in
  5a): read the text, not the label. Record each ruling as a change-log row (`reason` starting `controller ruling
  (5c):`) and in the ledger (outcome `new_right` or `old_right`).
- A malformed record JSON: rerun that case's agent once; then settle it as above.
- A regression settled `old_right`: a 5c rule is wrong for that case. If one narrowing fixes it without moving a
  guard (`STAY`) or a truth case, make it a new task (its failing test from the case, then the fix), rerun Task 10
  and this task (moving the round folders aside first); otherwise keep the row as a truth row `known_wrong` with the
  sub-plan that owns it, and list it for the operator.
- A `ruling_pending` truth row left after round 3 is the operator's: list it in Task 12's report.

- [ ] **Step 5: Commit the loop**

```bash
git add data/diagnosis_truth.csv data/diagnosis_truth_changes.csv output/diagnose_unknown_report/loop output/regression_report.csv
git commit -m "Sub-plan 5c: the truth loop's rounds, diagnoses, pre-ruling and truth updates"
```

---

### Task 12: Acceptance and the operator report (controller)

Run by the controller.

**Files:**
- Create: `output/diagnose_unknown_report/loop/5c/report.md`, `.../loop/5c/cases_after.md`;
  `/tmp/claude/delist_detection/5c/relabel_5c.py` (not committed).
- Modify: `data/scorecard.json` (the floor), `output/scorecard.json`, `data/diagnosis_truth.csv`,
  `data/diagnosis_truth_changes.csv` (the relabels), the roadmap.

- [ ] **Step 1: Relabel the 5c truth rows that still mismatch**

Write `/tmp/claude/delist_detection/5c/relabel_5c.py`:

```python
"""After 5c's loop: each known_wrong truth row with fixed_by 5c that still mismatches gets the sub-plan that owns
its remaining fields (the last of them in roadmap order), with a change-log row. A row whose remaining mismatch is
its shape, its ending, its exit kind, its continuation, its successor or its sec_id is a 5c miss: it keeps 5c and
is printed for the report (RRI, SXCI, NWS-A and NCRA, when not re-shaped, are Ruling 9's residual). Run from the
repo root; --dry-run prints only."""
import argparse
from pathlib import Path

from delist_detection import diagnosis_loop as dl
from delist_detection.diagnosis_truth import COLUMNS, LibraryRows, judge_case, load_legs, parse_rows
from delist_detection.lifecycle import Tables

ROOT = Path.cwd()
ORDER = ["5d", "5e", "5f", "5g", "5h", "5i"]
OWNER = {"last_trade_date": "5d", "internal_last_trade_date": "5d", "price_sec_id": "5e", "price_ticker": "5e",
         "price_date": "5e", "value_rule": "5f", "cash_per_share": "5f", "cash_currency": "5f", "stock_ratio": "5f",
         "recovery_ratio": "5f", "drop_reason": "5g"}
p = argparse.ArgumentParser()
p.add_argument("--dry-run", action="store_true")
args = p.parse_args()
truth_path, changes_path = ROOT / "data/diagnosis_truth.csv", ROOT / "data/diagnosis_truth_changes.csv"
rows = dl.read_csv(truth_path)
cases = {c.case_id: c for c in parse_rows(rows, str(truth_path), load_legs(ROOT / "data/diagnosis_truth_legs.csv"))}
lib = LibraryRows.of(Tables.read(ROOT / "output"))
changes, misses = [], []
for r in rows:
    if r["status"] != "known_wrong" or r["fixed_by"] != "5c":
        continue
    fields = [m.field for m in judge_case(cases[r["case_id"]], lib).mismatches]
    owners = set()
    for f in fields:
        if f in ("price_sec_id", "price_ticker", "price_date") and r["value_rule"] == "otc_print":
            owners.add("5g")                    # the OTC print's symbol and date are 5g's
        elif f in OWNER:
            owners.add(OWNER[f])
        else:
            owners.add("5c")
    if not fields or "5c" in owners:
        misses.append((r["case_id"], r["ticker"], fields))
        continue
    new = max(owners, key=ORDER.index)
    changes.append({"case_id": r["case_id"], "field": "fixed_by", "old": "5c", "new": new,
                    "reason": f"relabel after 5c's loop: remaining {', '.join(fields)}", "report": r["report"]})
    r["fixed_by"] = new
for c in changes:
    print(c["case_id"], "->", c["new"], "|", c["reason"])
for m in misses:
    print("5c MISS (keeps 5c):", *m)
if not args.dry_run and changes:
    dl.write_together([(truth_path, COLUMNS, rows), (changes_path, dl.CHANGE_COLUMNS,
                                                     dl.read_csv(changes_path) + changes)])
```

Run it with `--dry-run`, then without. Likely relabels (the run decides): MYL, LLYVA, LLYVK, OKE, ODP and SPWRA to
5d (last trade fields), FST to 5g (the OTC print's ticker FSTO). Likely `5c MISS` lines: SXCI, NWS-A and NCRA (shape
`no_ending`, Ruling 9's residual), RRI unless re-shaped, and ROVI or OKE if their network links did not happen:
list each in the report with its remaining fields.

- [ ] **Step 2: The checks**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --check --base 77d69c3`
Expected: exit 0: no `DROP`, no `GOLDEN FAILING`, no `DIAGNOSIS FAILING`, and `D.unexplained_regressions 0`. For
each line that fails it:
- `D.unexplained_regressions` above 0: a regression the ledger has not settled (Task 11 Step 4).
- `DROP <metric>`: lower that floor entry by hand only when the drop is traced to a truth correction or to a change
  the loop settled as right (new endings of the added successors that are uncertain, review rows of rewritten
  rows, `r1_rebucketed` checks, ...), with the reason in the commit message; otherwise it is a defect to report.
- `DIAGNOSIS FAILING`: a `pass` truth case the run now fails (LVNTA, LGFA and SIRI must not): report it.

- [ ] **Step 3: Raise the floor**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --write --raise-floor`
Expected: `D.mismatches` and its fields move down in `data/scorecard.json`'s floor (never up).

- [ ] **Step 4: The suite**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest`
Expected: green apart from golden `known_wrong` cases the run now passes (strict XPASS in
tests/test_golden_lifecycles.py). Do not edit `data/golden_lifecycles.csv`: list each XPASS case for the operator
to flip, and wait. A diagnosis truth XPASS should not remain (the loop flips them); if one does, rerun the last
round's update:
`PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/update_truth.py --label 5c --round <last> --base 77d69c3`.

- [ ] **Step 5: The cases, after**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python /tmp/claude/delist_detection/5c/cases_5c.py > output/diagnose_unknown_report/loop/5c/cases_after.md`
(the script Task 10 Step 1 wrote; if it was cleared, write it again from there). Compare it row by row with
`cases_before.md`.

- [ ] **Step 6: The report**

Write `output/diagnose_unknown_report/loop/5c/report.md` with these sections, every number from the commands above:

1. **Result**: accepted or not; `D.mismatches` before (588 at `77d69c3`: 596 after 5b, 588 after the operator's
   pre-check rulings) and after; the floor raised; `--check --base` result; pytest result (and the golden XPASS
   cases waiting for the operator).
2. **Mismatches per field**: one row per `D.mismatches.<field>` from `scorecard_before.txt` and the scorecard now.
3. **The cases**: the table of Step 5, before and after, with this plan's Expected outcome beside each, and why each
   one that still mismatches does (the sub-plan its `fixed_by` now names).
4. **The rules**: per rule, the securities it moved in the run (rule 1's `evidence["survived"]` rows, stage 5's R1
   rows, the `R1 continuations:` line, stage 9's `terms` and `own_registration` links, the `successor endings:`
   line), and the Task 9 review's findings and fixes.
5. **Regressions**: how many, by kind (`regression_kinds_5c.py`), and how each was settled (new_right, old_right,
   pending), with the reports' paths.
6. **Truth changes**: every row of `data/diagnosis_truth_changes.csv` 5c added (the pre-ruling, the loop's updates,
   the controller's rulings, the relabels).
7. **Uncertain endings and coverage**: `V.uncertain_endings`, `V.uncertain_securities`, `L1.coverage_securities` and
   `L1.coverage_tickers`, before and after.
8. **For the operator**: rulings needed (pending rows, old_right regressions kept, floor drops lowered and why),
   golden cases to flip, `5c MISS` rows (SXCI, NWS-A, NCRA: residual without a step source, Ruling 9), the loop's
   time and tokens, and what was deferred (rule 6 to 5f, Ruling 3; LMCA 2016 and LMCK under R3 to 5f).

- [ ] **Step 7: Roadmap and commit**

In `docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md`, set the 5c row's Status to
`done (D.mismatches 588 -> <after>; <n> of 25 cases now pass)` once the operator accepts the report (until then:
`run, awaiting the operator`).

```bash
git add data/scorecard.json output/scorecard.json data/diagnosis_truth.csv data/diagnosis_truth_changes.csv output/diagnose_unknown_report/loop/5c docs/superpowers/plans/2026-10-03-diagnosis-truth-roadmap.md
git commit -m "Sub-plan 5c accepted: D.mismatches 588 -> <after>, floor raised; the operator report"
```

Send the operator the report's path and its sections 1, 3 and 8.

---

## Self-review

- **Spec coverage.** Section 3 "5c", rule by rule: (1) the registrant's role before end-of-era branches 3 and 4 --
  an acquirer (RRI, SXCI), a reverse-merger issuer (FST) and a spin-off distributor (NWS-A, NCRA) get no merger
  ending, and their own 2.01 is not one (Task 4), read from whose shares were exchanged, never from rename or
  separation words (binding narrowing; BNI, CAL, TXU, LGFA pinned in `STAY`); (2) continuation follows R1 (Tasks 4,
  5, 6: one share, no cash, special dividends set aside, a new issuer or the same issuer); (3) a same-CIK
  reclassification of X into Y links X to Y (Task 6's `same_issuer_class` link: CMCSK, HUB-B, CWENA; Task 5's for
  DISCA and DISCK into WBD); (4) a holdco with a new CIK links when the 8-K states a one-for-one conversion that
  names it (Tasks 5 and 6, the name tie binding), with the window anchored on the last trade, the Form 25 or the
  anchor 8-K, never a guessed `delist_date` first (`successors.successor_anchor`); its own 8-K12B names it in the
  8-K12B search Task 5 runs for an unobserved successor (ROVI); (5) a successor the run never observed is added:
  ROVI's TiVo Corp from its 8-K12B (`AddedSuccessor`), CCO's and OKE's new lines from the CUSIP their texts or fails
  rows name and OpenFIGI's CUSIP job (`AddedLineSuccessor`; binding narrowing, never the TICKER job); (6) another
  ratio or an election: deferred to 5f (Ruling 3, measured). The "where" list: `end_of_era.signals`/`resolve`
  (Task 4), `classifier._classify_items` (unchanged; R1 sits before the no-evidence default),
  `successors.successor_in_run` (unchanged; the same-issuer class branch is `successor_by_terms`),
  `successor_from_8k12b` (Task 5's unobserved successor), `handoffs.decide_handoff`/`own_continuation_filing` (no
  handoff change, Ruling 4; Task 6 reads `own_continuation_filing`), `pipeline._find_successors` (Task 6),
  `added_securities.AddedSuccessor` (Task 7), `pipeline._merger_payouts` (a row rule 1 makes a transfer is no
  merger at stage 8, so no LLM call; a row 8b rewrites drops its reads). Must-not-change: a true target merger
  (LVNTA, JEF, SGP, FCL, TW, WCN, BKW, BNI, CAL, TXU, LGFA in `STAY` and Task 2), each side's target in a merger of
  equals (DuPont's 1.282 beside DOW's own one share: Task 2), a takeover (the handoff pass unchanged). The carried
  items: stage 9d (Task 7), RRI's text-symbol fix (Task 3), the pre-ruling script (Task 11 Step 2). The spec
  question on LMCA 2016 and LMCK (one-to-many reclassification under R3): not one share per share, so R1 does not
  move them; their baskets are 5f's (schema 3). Section 1 (the loop, acceptance) is Tasks 10 to 12; the 5a and 5b
  lessons (controller order, `--id-baseline` on every run, round 1 read by kind, pending rows settled from the text)
  are in Tasks 9 to 12.
- **Placeholders.** None: every code step is complete. The counts the controller fills in (the after-numbers in
  Task 12) are measurements, not code.
- **Type consistency.** `exchange_terms.read_texts(edgar, cik, filings, days, form25)` takes a list of days in the
  classifier (Task 4) and the pipeline (Task 5); `own_exchange(..., class_letter=None)` means any class (Task 4's
  role refusal) and `""` a plain common. `successors.SecurityStart` gains `last_seen` and `share_class` with
  defaults in Task 5 (base `_find_successors` still builds three-field starts until Task 6 uses `_starts`).
  `pipeline._starts`, `_IssuerAge`, `_own_exchange` and `BY_OWN_REGISTRATION` come in Task 5 and are used in Task 6;
  `_find_successors(..., ftd=None, sec_cusips=None)` (Task 6) is called with `sec_cusips` by `_run` from Task 6 on
  and by the harness through `inspect.signature`; `DelistingFinder.find(ctx, *, fallback=True)` and
  `_DelistingSearch.finder` come in Task 7 with their one caller. The harness calls `pipeline._r1_continuations` only
  once it exists. The whole sequence was applied mechanically to a fresh copy of `77d69c3` while planning, task by
  task: each task's new tests fail before its code and the suite is green after it (2242, 2281, 2282, 2284, 2300, 2305, 2310 passed; 240 xfailed
  throughout); the fixture build reproduces the sha1 sums of Task 1; Task 9's replay of the result gives the
  Expected outcome.
- **Review Focus.** Each line has its test in the owning task (Tasks 2, 5, 5, 6, 7).

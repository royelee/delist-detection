# Diagnosis truth set and general library fixes: design

Date: 2026-10-03. Status: design approved in conversation; written spec awaiting review.

Inputs: the 282 diagnosis reports in `output/diagnose_unknown_report/` (commits e15100b, 78f538f), the spec
`docs/superpowers/specs/2026-10-02-delist-library-reset.md`, the reset roadmap
`docs/superpowers/plans/2026-10-02-delist-library-reset.md`, and five reader notes in
`docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes/` (one per group of cause tags; see Appendix A).

## Goal

The library's output for the 282 diagnosed securities matches each report's corrected classification, with no
difference, and every other row stays as it is unless the evidence makes us at least 99% sure the old value was
wrong. The fixes are general rules that fix classes of cases. No fix patches one report.

The reports are a truth set. Where a report's correction was refuted by its skeptic pass, the skeptic's correction is
the truth. Some cases may stay out of reach of a general rule; they go on a residual list the operator accepts.

## Success criteria

- `D.mismatches` (scored truth fields that differ from the library's contract output) falls with every sub-plan and
  reaches zero apart from the accepted residual list.
- `D.unexplained_regressions` is zero when each sub-plan is accepted: every contract row that changed outside the
  truth set has been diagnosed and settled in the truth file.
- Existing scorecard floors hold (L1, L2, R*, V and the golden cases). A floor is lowered only by hand, with the reason
  in the commit.
- Uncertain endings (288 today) and L1 coverage (173 of 2,209 securities uncovered today) are reported alongside, as
  information. This plan touches about 103 of the 173 uncovered securities; the 49 `closed_no_event` securities have no
  ending at all and need separate work, so the 99% coverage goal needs more than this plan.

## Baseline (2026-10-03)

A first, machine-only comparison of each report's corrected fields with `output/contract/delistings.csv`: 271 of 282
cases differ in at least one field. Fields that differ, with case counts: `cash_currency` 139, `value_rule` 103,
`last_trade_date` 98, `price_sec_id` 93, `price_ticker` 85, `exit_kind` 79, `stock_ratio` 62, `price_date` 56,
`successor_sec_id` 48, `continuation` 44, `cash_per_share` 26, `drop_reason` 23. Some of this is noise from section 3's
free text (for example "(not in the run)" for a blank) and from the contract's own rules (decision 12 blanks
worked-out dates); the truth build in sub-plan 5-0 removes both, so the real baseline is set there.

## 1. Truth set and evaluation loop (sub-plan 5-0)

### 1.1 The truth file

`data/diagnosis_truth.csv`, next to `data/golden_lifecycles.csv` and `data/accuracy_audit.csv`. One row per truth
case. Columns:

- `case_id`, `sec_id`, `ticker`, `report` (path), `confidence` (verified / inferred), `skeptic` (upheld / refuted /
  n/a), `status` (`pass`, `known_wrong`, `ruling_pending`), `fixed_by` (for `known_wrong`), `note`.
- `shape`:
  - `ending`: the security's contract delistings row must match the scored fields.
  - `no_ending`: the security has no real ending (a reverse split that kept one sec_id, a line still trading). The
    contract has no delistings row for it.
  - `ending_moved`: the ending the report examined is not the security's real last ending (a rename was not
    followed, and the line ended later). The contract row must not be the old event; the later ending's fields are
    scored only where the report states them.
- Scored fields, as the contract should publish them under the spec's rules: `exit_kind`, `drop_reason`,
  `continuation`, `successor_sec_id`, `last_trade_date`, `value_rule`, `cash_per_share`, `cash_currency`,
  `stock_ratio`, `price_sec_id`, `price_ticker`, `price_date`, `recovery_ratio`. A cell holds the value, a blank (the
  field must be blank), or `*` (not scored: the report leaves it open).
- `internal_last_trade_date`: the corrected last trade date for `delistings.csv` when the contract leaves it blank
  (a worked-out date; decision 12 publishes only exchange prints).
- Legs (ruling R3): a stock basket's legs are scored from a companion file `data/diagnosis_truth_legs.csv`
  (`case_id`, `leg`, `ratio`, `price_sec_id`, `price_ticker`, `price_date`).

The truth holds the corrected fact passed through the contract's publishing rules (operator decision, this design):
a worked-out last trade date is truth for `delistings.csv` but blank in the contract; `cash_currency` is truth where a
filing states it ("$" counts as USD).

### 1.2 Building it

`scripts/build_diagnosis_truth.py` reads `records/*.json` and each report's section 3, strips free-text commentary
from values, applies the skeptic's refuted fields from section 9 and the record's `verification`, decides `shape`, and
applies the publishing rules. One field needs a judgement per case: whether the corrected last trade date rests on a
publishable source (an exchange print, the Form 25 EX-99.25 notice, the 8-K item 3.01 text, a Nasdaq halt) or was
worked out. The build reads that from the report's section 4; where section 4 does not settle it, or any other field is
ambiguous, the row goes to `ruling_pending` with the question in `note`. Nothing is guessed. Identity follows ruling R2,
checked from the cached OpenFIGI answers for the new CUSIP.

The operator reviews the built file before anything is judged against it.

### 1.3 Judge and scorecard

`truth.py` gains a third truth kind beside golden and audit: `load_diagnosis_truth` and a judge that returns one
mismatch per scored field that disagrees (numbers compared to 6 significant figures, dates as ISO strings, `*` never
scored). `scorecard.build` adds:

- `D.mismatches` (total) and `D.mismatches.<field>`, floored (good direction: down).
- `D.cases_matching`, `D.known_wrong`, `D.ruling_pending`.
- `D.unexplained_regressions`, from the regression report (1.4), recomputed by `scripts/scorecard.py --base <commit>`
  (there is no such metric without `--base`); `--check --base` fails when it is above zero.
- `D.mismatches.sec_id`: a truth case whose sec_id is not in the run's securities (a placeholder folded into a FIGI
  line that the truth file was not renamed for) is judged by that one mismatch, in any shape.

`data/scorecard.json` names the truth file, as it names the other two. A `known_wrong` row is a strict xfail: when the
library starts matching it, the check fails until its status is flipped to `pass`, as the golden set does today.

### 1.4 Regression report

`scripts/regression_report.py --base <commit>` compares `output/contract/delistings.csv` and
`output/contract/security_history.csv` with the same files at the base commit (the commit the sub-plan started from),
for every security not in the truth file and not on a truth case's successor chain. It also lists placeholders whose
sec_id changed (`contract/id_changes.csv`). It writes `output/regression_report.csv`: one row per changed field,
with old and new values. A regressed row is "unexplained" until the loop settles it in the truth file (1.6).

The report compares the contract's own columns, not the ones that are functions of other columns and of prices:
`dlret`, `dlret_fill`, `terminal_value`, `value_formula`, `terms_source` and `terms_gate` are skipped, beside
`verdict`. A price answer then cannot flood the report with derived changes, and one verdict on such a column cannot
leave a whole regression case pending. The cost: a change in `dlret` alone, outside the truth set, is not reported
(the scorecard's R2 lines still count fills and assumed par). Renames are found by comparing the base commit's
`securities.csv` with the run's (`contract/id_changes.csv` is not cumulative) and merged with the run's own rows.

### 1.5 Diagnose modes

The diagnose-delisting skill (`.claude/skills/diagnose-delisting/`) and its workflow gain two input modes beside
today's uncertain-row mode:

- Regression mode: the input row carries the old and the new library values. The report decides which one the
  filings support, and says so in sections 2 and 3.
- Mismatch mode: the input row carries the truth value and the library value for each mismatched field. The report
  re-checks both against the filings.

Everything else stays: the same evidence order, report sections, record schema, the skeptic pass on every
`library_wrong` case, the 5-agent limit and the speed report.

### 1.6 Truth update rules

`scripts/update_truth.py` applies the new diagnosis records to the truth file:

| Error | Diagnosis outcome | Truth file change |
| --- | --- | --- |
| Regressed row (not in the truth file) | verified, skeptic upheld, new value right | added with the new value |
| | verified, skeptic upheld, old value right | added with the old value; it is now a mismatch and the rule must be narrowed |
| | inferred, unresolved, or refuted | added as `ruling_pending`; still counts as unexplained |
| Mismatch on a truth row | verified, skeptic upheld, and it cites a filing the earlier report missed or misread | the truth value changes |
| | anything else | no change; the mismatch stands |

So the truth cannot drift toward whatever the library now outputs. Every change is written to
`data/diagnosis_truth_changes.csv` (`case_id`, `field`, `old`, `new`, `reason`, `report`) and committed with the
diagnosis reports.

### 1.7 The loop

After every fix sub-plan, before it is accepted:

1. Truth file.
2. A full cached `classify_universe.py` run, then the judge and score report.
3. The regression report.
4. The diagnose workflow on the mismatches and regressions (modes 1.5).
5. `update_truth.py` writes the new truth file; back to step 2.

The loop stops when a round finds no new error to diagnose, or after 3 rounds. Then it reports to the operator: truth
changes, mismatches left, rows pending a ruling. A saved workflow runs steps 2 to 5 (at most 5 agents in parallel).

## 2. Rulings

### 2.1 Rulings that define the truth (accepted as recommended)

- **R1. One for one (decision 9).** A continuation is: the old holders receive exactly one new share per old share and
  no cash in the exchange, even when other holders join (BHI) and even when the class or the issuer changes (a class
  reclassification, a split-off into a new issuer). Any other ratio, or cash in the exchange, makes a stock or
  cash-plus-stock merger. Cases: CMCSK, DISCK, CWENA, HUB-B, SPB, DTV 2009, LLYVA, LLYVK continue; CHTR (0.9042) and
  UNIT (0.6029) are mergers.
- **R2. Identity across a CUSIP or ticker change follows the FIGI.** One security when OpenFIGI gives the new CUSIP the
  same composite or none (the truth shape is then `no_ending` or `ending_moved`); two securities linked as a
  continuation when the composites differ.
- **R3. Packages with several legs.** A side table `output/contract/payout_legs.csv` (`sec_id`, `leg`, `ratio`,
  `price_sec_id`, `price_ticker`, `price_date`) and a value rule `basket`; the main row keeps its columns. Contract
  schema version 3. Cases: LGFB, LMCA 2016, LMCK, MDP, VSTO, CCE 2010, FNF's FNFV leg.
- **R4. Election deals** publish the final prorated package when a filing states it, else the default (non-election)
  package, never the sum of the elections. A CVR is a note in `value_formula`, not priced.
- **R5. A non-USD cash leg** publishes `cash_currency` as the filing states it (USD for "$"), unconverted; the gate
  skips that leg with a flag instead of failing.
- **R6. A bankruptcy plan that exchanges old equity for new shares** is `stock` priced on the new line when the plan
  states the ratio and the old line did not trade OTC first; `otc_print` (decision 11) when it did. Cases: SDRL, WOLF.
- **R7. One FIGI over pre- and post-bankruptcy stock under a reused ticker** (EXE) goes on the residual list for now:
  splitting it needs a new id scheme for one case.
- **R8. A suspension "on D" with no timing word, or a halt at the open on D, means the last trade was the trading day
  before D** (operator ruling 2026-10-03, settling the truth file's pending rows: CBL 2020-10-30, WM 2008-09-25, CZR
  2020-07-17). "Suspended immediately on D" stays unscored, since trading may have happened that morning (IMB, MNI).
  Sub-plan 5d implements R8 in the library's 8-K and notice readers.

The same review settled the other pending rows: a worked-out internal date with no source is not scored; a price
date is the trading day after the published last trade; a security the run does not hold yet is `*` until a
sub-plan adds it; an OTC symbol from the security's own CUSIP after the last trade is accepted; an election's
default package is what non-electors got (SUG: 1.0 ETE unit); TDW's warrants, EP's warrant leg, GRUB's OTC ADS and
EXE are residual; PCYC's dollar-valued stock leg is unscored and left to 5f.

### 2.2 Existing rules the truth build applies (no ruling)

- EGL's $11.434 dividend: the BHI role test ("No cash" means no cash in the exchange), judged from EGL's deal documents.
- A same-FIGI successor (CCO, GTES): not a real ending, so no contract row (`no_ending`).
- A worked-out last trade date: blank in the contract, `internal_last_trade_date` in the truth.
- KING's Form 15 versus Form 25 date: the internal `delist_date` key, not a contract field, so not scored.

### 2.3 Rulings that change only the verdict (settled in sub-plan 5i)

These change `uncertain.csv` and not any truth field: an `unpriced` gate state for decision 4 (stale close, missing
acquirer price, GRUB); stale caller seeds after a confirmed ending; the matched Form 25's filer CIK as issuer evidence;
the continued-filings relabel on a row that has a matched Form 25; an 8-K12B or an 8-K item 3.03 as the confirming
filing of a continuation.

### 2.4 Residual list

Truth rows the library cannot reach with a general rule (data it does not have, such as GRUB's OTC ADS price; an id
scheme change, EXE) are `known_wrong` with the reason and a `fixed_by` placeholder. The operator accepts the list at the
end of each loop. No residual row is ever fixed by an override keyed on its sec_id.

## 3. Sub-plans

Each sub-plan is one implementation plan, run in this order, and accepted only after its loop (1.7). Case counts come
from the reader notes and `case_map.csv` (Appendix B); a case can need more than one sub-plan. Code locations are the
readers' greps, to be confirmed when each plan is written.

### 5-0. Truth set and loop

Section 1: the truth file and its build, the judge and `D.*` scorecard lines, the regression report, the two diagnose
modes, `update_truth.py`, the saved loop workflow, and the operator's review of the first truth file.

### 5a. One line across a CUSIP or ticker change (43 cases)

Rule: before the no-Form-25 fallback ends a security, follow the issuer's line. The line continues when the same CIK and
class hold, the old CUSIP's last fails row and the new CUSIP's first row under the same ticker are within days (or the
same CUSIP keeps trading under a new symbol), a rename or a filing states the change (8-K 5.03, 3.03, a reverse split
notice, an 8-K12B under the same CIK), and no bankruptcy filing (8-K 1.03) falls in the window. Identity follows R2. Also:
attach a new CUSIP forward from the fails rows (the counterpart of `history.backfill_cusips`); fold a duplicate
placeholder into the FIGI line of the same issuer, class and CUSIP; resolve a `-WI` ticker to its regular line.

Where: `security_master.cusip_handoffs` (today read only by `ticker_resolver.infer_issuers`), `candidate_cusips`,
`era_cusips`, `resolve_with_identity_guard`, `superseded_placeholders`; `history.backfill_cusips`;
`pipeline._resolve_securities`/`_security_cusips`; the fallback in `delistings.DelistingFinder` and
`classifier._detect_continued_filings`; `successors.successor_from_8k12b` (`exclude_cik`).

Must not change: UAL's 2006 emergence (same CIK, old shares cancelled); post-bankruptcy equity; a ticker passed to
another issuer (new LMCA 2013, new MSG); a spin-off on a new CUSIP; two classes of one issuer (MSG A and B).

Reader notes: E theme 1, B T6, D themes 1, 2, 6, E themes 10, 11.

### 5b. Form 25 reach, matching and ownership (50 cases)

Rules: (1) search an issuer's Form 25s from before the first sighting to today and match by class, CUSIP or ticker,
refusing only a match to a sibling alive on the filing date; (2) match one multi-class 25-NSE to each class it names;
(3) a Form 25 that relates only to rights, or names another tracking-stock group, does not match the common;
(4) ignore class-label noise such as "(New)"; (5) also search the CIK that holds the security's CUSIP or ticker;
(6) when a matched Form 25 exists its path owns the row: the continued-filings rule and a later SEC revocation do not
override it, and the end-of-era resolver only settles the code; (7) a Form 25 with a same-day 8-A12B for the same class
is an exchange transfer.

Where: `delistings.DelistingFinder.find` (`_alive_at`, `SIBLING_ALIVE_AFTER_DAYS`, `FORM25_LOOKBACK_DAYS`, `early`,
`SAME_EVENT_DAYS`), `form25.match_security`/`class_kind`, `listing_status.withdrawal_kind`, `classifier.classify_event`
(revocation branch order), `end_of_era.resolve`.

Must not change: a secondary-listing withdrawal (Apache/Chicago 2020); a Form 25 of another class of the issuer (APA);
a transfer Form 25 that continued the same security. Replay XMSR, SOV, TXU, RHDC, IDARQ and LKSD first: their reports
do not show why the Form 25 was missed.

Reader notes: B T8, T9, E themes 3, 4, 5 (ordering), 8, A theme 1.

### 5c. Issuer role and successor links (26 cases)

Rules: (1) before end-of-era branches 3 and 4, decide the registrant's role from the filing text and form; an acquirer,
a survivor, a reverse-merger issuer or a spin-off distributor gets no merger ending, and its own 2.01 is not a merger;
(2) continuation follows R1; (3) a same-CIK reclassification of class X into an existing class Y (8-K 3.03 or 5.03, or
the Form 25's substitution wording) links X to Y; (4) a holdco with a new CIK links when its 8-K12B or 12G3 names the
old class, or the 8-K states a one-for-one conversion (5.01 with 3.03 or a 12g-3 statement), with the window anchored on
the Form 25 effective date or the 8-K date, not a guessed `delist_date`; (5) a successor the run never observed is added
(`AddedSuccessor`) from the fails rows under its ticker and linked; (6) a successor registration with another ratio or
an election is a stock or cash-plus-stock merger priced on the successor line.

Where: `end_of_era.signals`/`resolve`, `classifier._classify_items`, `successors.successor_in_run` (anchor day, a
same-CIK other-class branch), `successors.successor_from_8k12b`, `handoffs.decide_handoff`/`own_continuation_filing`,
`pipeline._find_successors`, `added_securities.AddedSuccessor`, `pipeline._merger_payouts` (skip the LLM for a row
that ends non-merger).

Must not change: a true target merger (another CIK acquires, the registrant's shares are exchanged); in a merger of
equals each side's target still ends; a takeover (the successor traded before under another ticker).

Spec question for the plan to settle with the operator: LMCA 2016 and LMCK (one-to-many reclassification) under R3.

Reader notes: D themes 3, 4, 5, 7, E themes 2, 7, D "does not fit" (UNIT).

### 5d. Last trade date (33 cases)

Rules: (1) read the 8-K item 3.01 section sentence by sentence: a suspend, cease, halt, delist or last-day word within
one sentence of a full date, classified before the open (D−1) or after the close (D); "the Closing Date" resolves from
the whole filing; read the EX-99.25 notice for continuation and fallback rows too; (2) source order: an explicit timing
word beats a notice's bare date; a bare "suspended on D" is D−1; a halt that never resumed dates the last trade; a
MIDAS or halt day that conflicts with the text is checked against the security's own CUSIP's fails rows; (3) every read
by ticker (MIDAS, halts, fails closes) is bounded by the security's own tenure of the ticker; (4) when nothing states a
day, the closing day gives `internal_last_trade_date` in `delistings.csv` with a new unconfirmed source value; the
contract leaves it blank; (5) the ending's history clip uses the last trade day, not the Form 25 filing plus 10 days.

Where: `last_trade.eightk_last_trade`/`_closing_date`/`decide_last_trade`, `form25.notice_last_trade`,
`delistings._last_trade`/`_confirmations`/`_eightk_window`, `ftd.close_of`/`close_known_on`, pipeline stage 9c, the
clip in `pipeline._ends_the_security` and `history.history_rows`.

Must not change: a row where MIDAS or a halt agrees with the text within one trading day; a notice that says "after the
close". Never publish a day after the Form 25 effective date (decision 12).

Reader notes: B T1, T2, T3, T4.

### 5e. Acquirer security and the gate (35 cases)

Rules: (1) look up the acquirer for every published stock leg before the gate, including terms that failed or never
reached it: resolve the LLM's acquirer ticker, else its name, else the successor registrant, to a CIK; accept it when the
name matches a current or former EDGAR name and it is not the target's CIK; (2) take that CIK's line whose CUSIP begins
at the closing, by the share class the filing names when the CIK has several, and add the acquirer to the run when it
has no line; (3) price that CUSIP's close on the day after the last trade from the next day's fails row, skipping
placeholder rows ($0.01, ".", SIRIZZZZ-style symbols) and old-CUSIP rows that repeat a stale close; (4) publish
`price_sec_id` and take `price_ticker` from that CUSIP's symbol on the price date; start the line's ticker_history on
the first trading day a filing states; (5) repair the gate's false fails within decision 4: a stale last close is
compared with the nearest fresh close; a non-USD cash leg follows R5.

Where: `pipeline._gate`, `pipeline._add_acquirers` (moved before the gate, without the "passed only" filter),
`acquirers.find_acquirer`/`acquirer_cik`, `ftd` close look-ups, `payout_gate.gate_payouts`/`reconcile`,
`payout_rule._merger`, `history` (line start).

Must not change: a leg that still fails after correct pricing (the gate is doing its job); a row whose acquirer ticker
already resolves and passes; a ticker reused later (GEN is Gen Digital from 2022: every ticker look-up is dated).

Reader notes: C themes 1, 8, A theme 4; the CAL, RTN, MIR, THI, WR and LSXMA reports' section 8.

### 5f. Terms extraction (33 cases)

Rules: a new LLM schema and prompt version returning the currency, the share class, the deal type, the election
package (R4) and the legs (R3, with `payout_legs.csv` and contract schema 3); prefer the latest completion document
(closing 8-K, Form 25 notice, latest amendment before closing) over a proxy headline, and "shares issued per share" over
"equivalent" figures; run the LLM when the deal text mentions acquirer shares even after a cash read; read 6-K, 8-K 7.01
and Form 25 notice text for a filer without 8-K items; carry a dollar-value stock leg (PCYC) in `value_formula` with a
price request.

Where: `llm_merger_extractor`, `filing_selection`, `payout_extractor`, `payout_rule.merger_inputs`/`_merger`/
`VALUE_RULES`, `contract.py`, `store.CONTRACT_SCHEMA_VERSION`, `price_requests`.

Cost: the prompt version change invalidates `cache/llm/`; rerun `scripts/eval_merger_extractor.py` before the full run;
it needs `OPENAI_API_KEY` and api.openai.com.

Reader notes: C themes 3 to 7, E theme 6.

### 5g. Distress (13 cases, plus the endings 5a brings out)

Rules: the reset-4a3 bankruptcy branch as four sub-rules: (1) an 8-K 1.03 with a 3.01 suspension or Form 25 and
trading after under another symbol is dropped/bankruptcy valued by `otc_print`; (2) a bankruptcy within about 90 days
before a 2.01 beats the completed-acquisition branch (a Chapter 11 asset sale is not a merger); (3) a plan exchange of
old equity follows R6; (4) a prepackaged case whose stock stayed listed is dated at the plan's effective date with no
`otc_print`. Also: a later SEC revocation never outranks an earlier exchange removal or bankruptcy; `otc_print` takes
the security's own OTC symbol from its CUSIP's fails rows after the last trade, else the 3.01 text, else blank.

Where: `end_of_era.signals`/`resolve` (branch order), `classifier.py` (revocation branch), `delistings._fallback_date`,
`exit_kind.ending_fields`, `payout_rule._otc`, `price_requests`.

Must not change: a solvent liquidation; an exchange transfer or holdco continuation (XRX, CI, APA).

Reader notes: B T5, E theme 5, C theme 2.

### 5h. Identity (6 cases)

Rules: the name tier accepts a former EDGAR name only for the dates the issuer carried it, and the candidate that traded
the ticker then wins over an exact-name match from another period; a class-suffix ticker resolves to its base ticker
and class before the finder; an ending is never dated only by a caller's last sighting.

Where: `ticker_resolver._name_search`/`_index_candidates`, `cik_lookup.CikNameIndex`, `observations`/ticker
normalization, `delistings._fallback`. The resolver cache version goes up.

Reader notes: E theme 9, B T7.

### 5i. Verdict and evidence (40 truth cases, about 60 uncertain rows)

The verdict-only rulings of 2.3, each with its guard from reader note A. The loop must show no truth field and no
contract row changing.

Reader notes: A themes 1 (verdict part), 2, 3, 5, 6, 7.

## 4. Running, measuring and testing

Each sub-plan: write the plan, then run it with subagent-driven development (sonnet implementers and reviewers); rerun
the full universe on warm caches (`--sec-workers 1`, never a `--limit` subset into `output/`; cold fetches through
`DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock` and the seven allowed hosts; one SEC client at
a time); run the loop (1.7); commit the code, outputs, truth changes and new reports on this branch. Merging or pushing
is the operator's call.

Before the next sub-plan starts: `D.mismatches` fell and its floor was raised (`scripts/scorecard.py --raise-floor`);
`D.unexplained_regressions` is zero; existing floors hold; a short report goes to the operator (mismatches per field
before and after, regressions and how they were settled, truth changes, the uncertain and coverage deltas).

Tests stay offline: each rule gets unit tests on `FakeEdgar` and fixture-backed doubles built from its truth cases'
cached responses, at least one where the rule applies and one per "must not change" case its section names. The 31-case
golden replay stays green and the golden lifecycles stay strict.

Errors: a diagnose agent that does not write back is written back from the workflow journal; a truth field the build
cannot settle is `ruling_pending`, never guessed; a loop that reaches 3 rounds stops and reports.

## Appendix A. Reader notes

Five sonnet readers read sections 7 and 8 of every report, grouped by cause, and wrote fix themes with a rule, a place in
the code, a guard, the cases and the risks. Their notes are in
`docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes/`: `A_right_but_uncertain.md` (89 cases),
`B_last_trade_and_endings.md` (61), `C_terms_and_prices.md` (52), `D_successors_and_links.md` (48),
`E_exit_kind_and_identity.md` (32). They read sections 7 and 8 and grepped the code; they did not trace runs, so each
plan confirms the mechanism first.

## Appendix B. Case map

`docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes/case_map.csv`: every case with its cause group, whether the
library was wrong, the diagnosis confidence, the reader theme, the fix family and the sub-plan. Cases per sub-plan:
5a 43, 5b 50, 5c 26, 5d 33, 5e 35, 5f 33, 5g 13, 5h 6, 5i 40, no change 3.

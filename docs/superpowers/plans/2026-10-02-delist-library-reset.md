# Delist Library Reset: Roadmap

> **For agentic workers:** this file orders the reset's plans and is not executed task by task. Execute
> reset-1 (`docs/superpowers/plans/2026-10-02-reset-1-scorecard-golden-audit.md`) with
> superpowers:subagent-driven-development or superpowers:executing-plans. Each later plan is written in full
> when the plan before it lands.

**Goal:** Take the library from 88.8% lifecycle coverage to at least 99%, prove each lifecycle's
correctness, and publish the two-table contract qlib_practice reads.

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md`, a Markdown copy of
https://claude.ai/artifact/Y9MT7c869AXSyT4gvYQ852. Exit-kind and valuation rules: "How to handle a ticker event"
(https://claude.ai/artifact/76LqFYrd5D14NC53fKxC9x, a Claude Doc). Code removal: "Delist Library Cleanup"
(https://claude.ai/artifact/VP1F4A16ZsXgMTcjrwnBkq).

## Why several plans

The spec's "Order of work" has four steps: measure, one verdict per row, publish the contract, close the gaps.
Each step depends on what the step before it produces. The scorecard ranks the gaps, the verdict defines
`uncertain`, and the contract defines the columns the gap work fills. Each plan below produces working, tested
software on its own. Only reset-1 is written in full now. Writing reset-2 to reset-4 in detail first would fix
their designs against numbers that reset-1's audit is about to change, and against operator decisions not yet
taken.

## Baseline

Measured on 2026-10-02 from the committed `output/` (as_of 2026-09-25, library main `d1a367e`). reset-1's
scorecard reproduces these numbers from the tables.

| Line | Today |
| --- | --- |
| L1 coverage, input tickers | 1,970 of 2,219 (88.8%) |
| L1 coverage, securities | 1,962 of 2,210. Uncovered: 119 left view, 51 ended incomplete, 46 closed with no event, 32 with no interval |
| L2 quality of covered tickers | 1,547 high, 296 medium, 127 low |
| R1.1 sightings mapped | 35,419 of 35,955 |
| R1.2 identity | 2,060 FIGI via CUSIP, 50 ticker only, 100 placeholders, 14 FIGI rows with no CIK |
| R1.3 transfers with no successor | 126 (53 placeholders) |
| R1.4 review rows | 728 over 507 securities |
| R2.1 last trade date | 841 of 883 real endings; 41 missing inside the window |
| R2.2 unknown reason | 9; 139 endings from the continued-filings rule |
| R2.3 blank DLRT inside the window | 54: 32 wait for a last close, 22 have no value |
| R2.4 assumed par | 59 (51 inside the window) |
| R2.5 / R2.6 distress | 54 endings, 39 carry a flag |
| A.random | 11 wrong of 99 checked; the 95% upper bound on the error rate is 17.7% |
| A.census.left_view | 114 wrong of 115 |
| A.census.distress | 49 wrong of 54 (42 involve the liquidation-vs-dropped vocabulary, 7 differ in other ways; see below) |
| A.census.continuation | 27 wrong of 69 |
| A.census.blank_no_value | 11 wrong of 21 |
| A.census.assumed_par | 17 wrong of 58 |
| V.uncertain_securities | 55 (34 with seeds outside their history, 18 with a ticker overlap, 3 placeholders with no ticker filing) |
| V.uncertain_endings | 266 (234 inside the window, 19 distress) |
| V.uncertain_seeds | 390 listed |
| V.uncertain_input_tickers | 243 (11.0% of input tickers) |
| V.audit.confirmed_but_wrong | 76 |

The V lines were measured by reset-2's acceptance run on 2026-10-02, after `output/` was refreshed. The
committed tables could no longer be rebuilt from any cache on disk: the run that produced them (2026-09-28,
code `76edc38`) used a cache state that no longer exists. Reset-1's and reset-2's code give byte-identical
tables from the same caches, so the refresh changes data only: about 75 of 1,016 delisting rows and the
issuer CIKs of 8 securities. It lowered 14 floor entries by hand, among them L2 low 127 to 147, R2.4 assumed par
59 to 62 and securities coverage 88.8% to 88.5%. It also moved golden `CB-2010` to `known_wrong`
(`reset-4c`): the cached merger-terms answer now prices ACE under its post-merger ticker. `data/scorecard.json`
holds the current floor; the table above keeps the numbers the plans were written against. Reset-2's refresh run
and reset-3's first acceptance run had the LLM endpoint (api.openai.com) blocked by the agent sandbox. The
complete rebuild, with every input, changed one ending only (Z 2015, a continuation, now flagged
`terms_gate_failed`), so the 14 lowered numbers stand as a data change, and `R1.4.review_rows` moved 712 -> 713.

The A lines come from reset-1's accuracy audit (`data/accuracy_audit.csv`, filled from SEC filings on
2026-10-02; 416 of 421 rows filled, 5 left pending with the reason in `note`). A row is wrong when any field
the checker verified disagrees with the output. The wrong rows are the test set for the plan that owns them:

- **left_view goes to reset-4a.** Nearly every left-view ending is false. Most were acquisitions the library
  read as transfers. The rest kept trading (renames, reverse splits, holding-company moves) or were dropped
  to OTC after a bankruptcy.
- **distress goes to reset-4d.** 42 of the 49 involve the `liquidation` vs `dropped` vocabulary: 36 differ
  only in that, and 6 also in the last trade date. The truth uses the contract's `dropped` for a
  bankruptcy delisting, while today's bucket says `liquidation`; both get the same −0.90 mark. reset-3's mapping
  from the CRSP code removes the vocabulary difference. The other 7 differ in other ways: PDLI is a liquidation (the library says
  `dropped`); WOLF 2025, TDW 2017 and HTZ 2020 swapped old shares for new ones in bankruptcy plans at a ratio
  other than one for one (HTZ's old stock was cancelled for about 3% of the new stock, TDW's ended at its 2017
  effective date), so each is an `exchange`; CHK has no ending in the output; GGWPQ ends in 2010 where the
  line kept trading as GGP until 2018; and TMA's last trade date is off.
- **blank_no_value and assumed_par go to reset-4c.** Their notes record each deal's consideration, so reset-4c
  can value them.
- **continuation goes to reset-4a or reset-4b.** Several links were not one for one (CHTR, MTCH, DVMT,
  LMCA/LMCK, CSAL, S, AZPN), and one issuer was wrong (SPB).
- **random:** the 11 wrong rows are mostly identity or ending mistakes the census groups do not catch. CFFN's
  2008 issuer is the old Capitol Federal Financial (CIK 1074433), not 1490906. EPE and MER read "closed with no
  event": EPE was dropped to OTC in 2019 and MER merged into Bank of America in 2008. AQNT and AT ended in 2007,
  before their 2008 sightings.

Where this differs from the spec's hand count, the scorecard's definition is the one used from now on:

- R2.4: 59 and 51. The spec's 60 and 52 also counted one continuing merger row.
- R2.6 sub-counts: 33 rows with a last-trade-date flag, 8 with a ticker-map identity, 3 at a normal price. The
  spec has 29, 6 and 1. The total, 39 flagged, matches.
- R2.2: 139 real endings come from the continued-filings rule. The spec's 123 counted review rows.
- R1.4: 507 securities. The spec's 508 counted the blank `sec_id`.
- Continuations in the audit census: 70. The spec has 73.

Found while building the golden set, and not in the spec:

- **FOX/FOXA.** Twenty-First Century Fox's sightings from 2013 to 2018 (CIK 1308161, class A and class B) are
  mapped to Fox Corp's FIGIs (`BBG00JHNJW99`, `BBG00JHNKJY8`). The 2019 Disney merger ending is missing, and
  Fox Corp inherits 21CF's history. reset-1 pins both as known-wrong golden cases for reset-4b.
- **LVNTA.** The placeholder `CIK1355096-COMMON` has about 400 ticker intervals that alternate between LINTA,
  LCAPA, LVNTA and QVCA every few days. Liberty's tracking stocks are being merged into one line. This is for
  reset-4b.

## The plans

| ID | Plan | Needs | What it must move | Spec decisions it rests on |
| --- | --- | --- | --- | --- |
| reset-1 | Scorecard, golden set, accuracy audit (written) | nothing | M1 and R1.6. Sets the floor | 5, 17 |
| reset-2 | One verdict per row; `uncertain.csv` | reset-1 | R1.4. The library-side hard gates of decision 17 | 1, 4 |
| reset-3 | The contract, side by side with today's tables | reset-2 | golden `MRK-2008` | 6, 7, 9, 10, 12 |
| reset-3q | qlib_practice switches every reader (in the qlib_practice repo) | reset-3 | the consumer's gates | 8, 13, 15, 16 |
| reset-4a | End-of-era resolver | reset-2 | L1 left view and closed with no event (165). Golden `YHOO` and the 20 sampled rows | 9, 11 |
| reset-4b | Identity evidence | reset-1 | R1.2, L1 no interval. Golden `FOXA-2015`, `FOX-2015`, `ERA` | 1, 7 |
| reset-4c | Values: blank mergers and assumed par | reset-3 | R2.3, R2.4 | 2, 4 |
| reset-4d | Distress certainty and liquidation values | reset-2 | R2.5, R2.6. Golden `PDLI` | 3 |
| reset-4e | Missing last trade dates | reset-1 | R2.1 | 12 |
| reset-4f | Values of drops to OTC | reset-4a, reset-3 | the drops reset-4a separates | 11 |

The reset is done when `L1.coverage_tickers` reads at least 0.99 and the accuracy audit's census and random
sample meet decision 17. The golden set's `fixed_by` column uses these IDs.

Before each later plan is written, confirm with the operator the decisions it rests on. The spec lists 17
decisions with proposed answers. reset-1 adopts 5 and 17 as proposed. Decision 14 (spin-offs) is a store check
in qlib_practice and needs no library plan unless that check fails.

### reset-1: Scorecard, golden set, accuracy audit

Written: `docs/superpowers/plans/2026-10-02-reset-1-scorecard-golden-audit.md`. It adds `output/scorecard.json`
to every run, a floor in `data/scorecard.json` that no later change may lower, a 51-case lifecycle golden set
(27 pass and 24 known wrong), and the decision-17 audit worksheet (321 census rows and 100 random rows), filled
from sources.

### reset-2: One verdict per row

- A `verdict` module gives `confirmed` or `uncertain` to each seed, each security and each ending, under the
  spec's invariants ("Invariants the library's build enforces"). A confirmed security has a FIGI, or a unique
  CIK and class. A placeholder also needs a filing check that the ticker appears under that CIK (decision 1).
  Its dated intervals must cover every seed that resolved to it. A confirmed ending has a filing-backed exit
  kind and a last trade date from an exchange-print source (MIDAS, an exchange notice, 8-K item 3.01, a Nasdaq
  halt) that is not after the Form 25 effective date. The verdict never covers the value. The one exception is
  decision 4: assumed par after a failed payout gate (JCI 2016) is uncertain.
- `uncertain.csv` has the columns `kind` (seed, security or ending), `ticker`, `sec_id`, `date`, `reason` and
  `candidates`.
- The scorecard gains the uncertain counts. `R1.4.review_rows` leaves the floor by a deliberate floor edit.
  `review.csv` stays until reset-3 publishes the contract (cleanup step 4).
- Decision 17's library-side hard gate becomes a build check: no harsh fill on an ending whose identity or date
  is uncertain.
- Done 2026-10-02 (plan `2026-10-02-reset-2-verdicts.md`). Decision 1 was answered on 2026-10-02: an EDGAR
  check. Decision 4 was adopted as proposed. The check confirmed the ticker of 96 of the 99 placeholders,
  through a resolver tier or a filing, so 3 stay uncertain for that reason.

### reset-3: The contract

- `security_history` has 7 columns and carries the issuer CIK in force on each interval. Golden `MRK-2008`
  then flips: old Merck & Co was the issuer in 2008.
- `delistings` v2 has 11 columns: `exit_kind`, `drop_reason`, `continuation`, `successor_sec_id`,
  `ticker_successor_sec_id`, `dlret`, `dlret_fill`, `terminal_value` and `verdict`, keyed by `sec_id` with one
  ending per security. An earlier ending goes to `uncertain.csv`. Today's bucket and CRSP code map to
  `exit_kind` and `drop_reason`. Shumway values and assumed par move to `dlret_fill`. A continuation's `dlret`
  is blank.
- The run also writes the seed echo, `price_requests.csv` out and its answers in (`last_close`,
  `received_close`, `otc_print`; this replaces `--last-trade-closes`), `id_changes.csv` with placeholders built
  from a class code (decision 7), and `schema_version` in `run_manifest.json`.
- For one release the contract is written under `output/contract/`, beside today's tables (decision 6).
- `lifecycle.Tables` gains a reader for the contract tables. The golden judge and the scorecard then read
  `exit_kind` and `dlret_fill` from them, and `lifecycle.EXIT_KIND_OF_BUCKET` is deleted.
- **Risk to measure first: seeds-only input.** Today a ticker history ends at the security's last sighting, and
  later sightings are what carry it forward. Over-seeding is harmless, so qlib_practice can keep passing every
  sighting as a seed. Run the scorecard on a seeds-only input before qlib_practice drops the extra rows. If
  coverage falls, keep every sighting until reset-4a lands.
- Done 2026-10-02 (plan `2026-10-02-reset-3-contract.md`). Decisions 6, 7, 9, 10 and 12 were adopted as proposed.
  The acceptance rebuild left today's eight tables byte-identical; `uncertain.csv` changed only by `earlier_ending`
  reasons (6 earlier endings: APA, HNZ, IPHI, WFT, AOC, GGP). `output/contract/` has 2846 security intervals, 875
  endings (618 merger, 193 exchange of which 69 continuations, 53 dropped: 47 bankruptcy, 3 sec_order, 3
  filings_fees; 2 expiration; 9 blank; 148 blank `last_trade_date`), 35955 seeds, 964 price requests and 0 id
  changes. Golden `MRK-2008` flipped to `pass` (MRK intervals before 2009-11-04 carry issuer 64978). Floor entries
  lowered by hand because an earlier ending is uncertain (one ending per security, decision 12):
  `V.uncertain_distress` 19 -> 20, `V.uncertain_endings` 266 -> 268, `V.uncertain_endings_in_window` 234 -> 236.
  `--raise-floor` then raised `A.census.continuation.errors` 27 -> 25, `A.census.distress.errors` 49 -> 13,
  `V.audit.confirmed_but_wrong` 76 -> 45 and `G.pass` 26 -> 27.
  Seeds-only measurement (2952 seeds against 35955 observations): `L1.coverage_tickers` 0.8553 (full run 0.8851),
  `L1.coverage_securities` 0.8545 (0.8855), `L1.left_view` 157 (120), `L1.closed_no_event` 70 (49),
  `R1.1.mapped_share` 0.9766 (0.9850), `V.uncertain_seeds` 44 (390). Coverage falls, so by the rule above
  qlib_practice keeps passing every sighting until reset-4a lands. The published output comes from the run with
  every input, the LLM included; it also lowered `R1.4.review_rows` 712 -> 713 by hand (one more row flagged).

### reset-3q: qlib_practice switch (in the qlib_practice repo)

From the spec's step 3, in one qlib_practice change:

- Rename `issuer_cik`, `valid_from`/`valid_to` and `review_flags`.
- Split `bucket` and `dlret_method` into `exit_kind`, `drop_reason`, `continuation` and `dlret_fill`.
- Key the overrides and the drop list on `sec_id`.
- Build membership from the seed echo (decision 8).
- Answer `price_requests.csv` from the store.
- Bump the minimum library commit.

Decisions 13 (label compounding), 15 (exits booked in the account series) and 16 (the drop list never removes a
panel row) are changes in qlib_practice only.

### reset-4a: End-of-era resolver

This is the spec's "The end-of-era resolver (the R1.3 fix)". One function runs once per security, at the last
date its history is known, and answers "what happened next?" by trying the six branches in order. Each branch
needs evidence about the security, not only about the registrant. It replaces
`classifier._detect_continued_filings` and the clip decision now spread over `pipeline._delisting_endings`,
`_ends_the_security`, `_continues_after` and `listing_status`.

- Test set: the 20 sampled golden rows, golden `YHOO`, and the 117 `census:left_view` rows of reset-1's audit
  once they are filled.
- Acceptance: `L1.left_view` and `L1.closed_no_event` fall (165 today), the sampled golden cases flip to `pass`
  (except `ERA`, which waits for reset-4b), and no golden `pass` case breaks.
- Done (first step) 2026-10-02 (plan `2026-10-02-reset-4a-end-of-era.md`). Decision 11 holds as the overnight
  ruling. Only the classifier's continued-filings rule changed: it now asks `end_of_era.resolve`, EDGAR evidence
  only (still trading, successor registration, change in control, completed acquisition, listing-deficiency
  notice, else today's transfer). Task 6 keeps every relabelled ending uncertain (`resolved_from_continued_filings`).
  Two rebuilds (identical tables; the second after Task 6): 85 endings changed, all from `exchange_transfer`:
  44 to merger (change in control), 20 to merger (completed acquisition), 6 to compliance_failure (deficiency
  notice), 15 kept their bucket. Moved: `L1.left_view` 120 -> 63, `R2.2.continued_filings_rule` 136 -> 51,
  `R1.3.transfer_no_successor` 126 -> 63, coverage 0.885469 -> 0.909009 (tickers 0.885083 -> 0.907616),
  `A.census.left_view.errors` 114 -> 76. Golden flips known_wrong -> pass: MDC, SGP, ACF, BNI, UFS, CPN, CPGX
  (G.pass 27 -> 34); YHOO, EXBD, XON, WTW, LIZ, ACXM, DF, MNI, ESV, DRQ, STN, LVNTA stay known_wrong.
  Floor entries lowered by hand: `R2.*`, `L1.ended_incomplete` and `L2.*` ("reset-4a turns false transfers into
  mergers and distress endings whose values reset-4c and reset-4d still have to find": L1.ended_incomplete
  52 -> 57, L2.low 147 -> 169, L2.high_share 0.78055 -> 0.761668, R2.1.missing_last_trade_date 43 -> 46 (in
  window 42 -> 43), R2.3.blank_dlret_in_window 55 -> 61, R2.3.blank_no_value_in_window 22 -> 27, R2.4.assumed_par
  62 -> 79, R2.5.distress_blank_dlret 1 -> 3, R2.5.distress_no_last_trade_date 1 -> 2, R2.6.distress_flagged
  39 -> 45); `A.census.continuation.errors` 25 -> 28 (four continuations, XRX holdco, WBD, LLYVA, LLYVK, read
  as ended; the issuer-seen-after guard is reset-4a2); `V.uncertain_distress` 20 -> 26,
  `V.uncertain_securities` 55 -> 61, `V.uncertain_input_tickers_share` 0.109509 -> 0.111762 (new
  compliance-failure endings and histories clipped at real endings are honestly uncertain).
  Left for reset-4a2: the issuer-seen-after guard, holdco reorganizations, OpenFIGI's later ticker, a new CUSIP in
  the fails data, closed-with-no-event securities with no delisting row, and consolidating the clip logic
  (`_ends_the_security`, `_continues_after`, `listing_status`) into the resolver.

### reset-4b: Identity evidence

- The 50 ticker-only FIGIs, the tier that produced APTV and ITT.
- The 100 placeholders, with decision 1's filing check.
- The 14 FIGI rows with no CIK (Applied Materials, DuPont, Fannie Mae and US Airways among them).
- The 32 securities with no interval.
- FOX/FOXA, ERA, and LVNTA's tracking-stock intervals.
- Done (first step) 2026-10-02 (plan `2026-10-02-reset-4b-dead-before-sighting.md`). 31 securities that died before
  their first sighting (delisted 2006-12 to 2008-02, before the 2008-01-16 snapshot; the fails window began
  2007-12-17) now load fails rows for [end - 1095 d, end + 10 d] and take their CUSIPs from rows under their tickers
  in the 120 days before the end whose description names the issuer (pipeline stage 5b, `history.backfill_cusips`).
  No `sec_id` or issuer CIK changed. `L1.no_interval` 32 -> 1, coverage 0.909009 -> 0.918515 (securities) and
  0.907616 -> 0.91708 (tickers), `R2.3.blank_dlret_in_window` 61 -> 57, `A.random.upper95` 0.177208 -> 0.153275.
  SEC's 2007 fails files mask some symbols (`**********`, Aug-Dec 2007): a masked row is no longer a ticker
  sighting (it still shows the CUSIP trading). Floor entries lowered by hand (Ruling 4): `L1.ended_incomplete`
  57 -> 67, `L2.low` 169 -> 171, `L2.high_share` 0.761668 -> 0.753808, because those 31 securities now end incomplete
  or low-grade until their identity and values are worked. Left for the later reset-4b steps: the 50 ticker-only
  FIGIs, the 99 placeholders, the no-CIK FIGI rows, the 9 FOX/FOXA-style share-class contradictions (AA, ALEX, CB,
  CHK, FOX, FOXA, GM, IR, LBTYA), ERA, LVNTA.

### reset-4c: Values

- The 22 endings inside the window with a blank value. Decision 2: value them by hand through the deal-terms
  input, or publish assumed par as `dlret_fill = 0.0`, and never use the drop list.
- The 59 assumed-par rows (decision 4), including JCI 2016.
- Done (first step) 2026-10-02 (plan `2026-10-02-reset-4c-failed-gates.md`). Decision 4's rule: an ending valued at
  assumed par after a failed payout, LLM or terms gate is uncertain (`assumed_par_after_failed_gate`). 32 endings
  became uncertain (18 already uncertain gained the reason): `V.uncertain_endings` 266 -> 298,
  `V.uncertain_endings_in_window` 234 -> 264, `V.uncertain_input_tickers_share` 0.111762 -> 0.126183; the eight
  tables other than `uncertain.csv` are byte-identical, `contract/delistings.csv` changes only its verdict column.
  `V.audit.confirmed_but_wrong` 44 -> 40. Floor entries lowered by hand (Ruling 2, "decision 4: assumed par after a
  failed LLM or terms gate is uncertain"): those three. The research (137 blank or assumed-par merger endings): 33
  of 55 blanks have a cash payout but no last close and 37 have no last trade date (reset-4e's work); 24 are not
  merger exits (reset-4a2); only 8 have no consideration recorded. Left: decision 2's hand-valued terms, a sanity
  filter for placeholder fails prices (0.01, 1.00) and the price answers' received closes, all after reset-4e.

### reset-4d: Distress certainty and liquidation values

- The 33 distress endings whose last trade date is contested.
- The 8 identified through today's ticker map, and the 3 marked "distress at a normal price".
- PDLI: a voluntary wind-down that paid distributions. It is a liquidation, not `compliance_failure`.
- Liquidation payment schedules (none exist today), and the AABA and PDLI values from those payments
  (decision 3).

### reset-4e: Missing last trade dates

There are 42 real endings with no last trade date, 41 inside the window: 34 mergers, 5 transfers, 1
liquidation, 1 unknown and 1 expiration. Only exchange-print sources count. Feasibility from the spec: 230 of
1,017 endings have no exchange-print source, 62 of 183 of them before 2012.

### reset-4f: Values of drops to OTC

This is decision 11: the first off-exchange print within 10 trading days, requested through
`price_requests.csv` (`otc_print`). The spec measured 37 of 175 drops and distress endings with a usable print,
so expect fills, not OTC values, in the first release.

## Cleanup interleaving

The Delist Library Cleanup page runs after reset-1. Each removal group is one commit. `securities`,
`ticker_history`, `cusip_history` and `delistings` must come out byte-identical, and the scorecard must not
change. `review_triage.py` and its two tables are removed only after reset-3 publishes the verdict and
`uncertain.csv`. Simplifying the core modules comes last, one module at a time, each behind the golden set and
the scorecard.

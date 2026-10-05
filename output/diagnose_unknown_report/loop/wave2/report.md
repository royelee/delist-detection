# Wave 2 (sub-plans 5f, 5i): operator report

Base ca58ee1 (wave 1 accepted). 5f was built in the main worktree and 5i in a copy, in parallel. Each was reviewed,
fixed and then run together. The last network run (at 1244bc7, `--id-baseline` = ca58ee1's securities.csv,
`--as-of 2026-09-25`) exited 0. Each sub-plan's own result is in `../5f/report.md` and `../5i/report.md`. The choices
I made alone are in `docs/superpowers/plans/2026-10-03-diagnosis-truth-decisions.md`, under "Wave 2 review".

## Result

**Accepted by the controller.** `scorecard.py --check --base ca58ee1` exits 0. pytest: 3107 passed, 45 xfailed.

| Metric | 0de5d8f (before wave 1) | ca58ee1 (wave 1) | Wave 2 |
|---|---|---|---|
| D.mismatches | 478 | 294 | 121 |
| D.cases_matching | 103 | 167 | 284 |
| Truth cases pass / known_wrong | 103 / 213 | 167 / 151 | 284 / 37 (all residual) |
| G.pass | 42 | 44 | 44 |
| V.uncertain_endings | 251 | 206 | 98 |
| V.uncertain_securities | 49 | 42 | 48 |

114 known_wrong cases flipped to pass: 107 of 5f's, 2 of 5i's, and 5 residual rows that the R8 rulings settled (LEG,
OKE, ...). The roadmap is complete. The 37 cases left are all residual; each row's change log says what it still
lacks.

## How it went

1. **5i** (offline) returned four patches. Its replay changed no contract row, only `uncertain.csv`, as the spec
   requires.
   - Its review found 4 Important defects: rule E confirmed MEL and FRK, rule B confirmed an 8-K12B without reading
     its ratio (CHTR), the gate-failed set was defined twice, and GRUB's acquirer ticker was "NULL". All were fixed
     before merging.
2. **5f** ran its 10-deal calibration and two measurement runs with the new prompt (v3; every LLM answer is new).
   D.mismatches fell from 294 to 131 in its own measurement.
   - Its review hand-checked 41 changed mergers outside the truth set. 7 were wrong, all among the 18 whose value
     changed. The 23 rows that only gained a currency were right, and every one of the 512 published cash amounts is
     in dollars in its filing, except THI's C$65.50.
   - The fix wave (dea52c9) handled five Important defects: elections with no stated default, acquirers named by a
     defined term, a gate crash on one answer shape, basket legs that lost their class, and R4 consistency.
3. **The loop** (label wave2):
   - Round 1 listed 438 regression keys and 19 mismatch keys.
   - 419 keys over 380 securities were settled `new_right` by kind: 370 blank-to-USD currency fills, plus the value
     changes the review found right or the fix wave corrected.
   - The loop diagnosed TRH, NMX, PAS and 11 mismatch cases. TRH and NMX were regressions of the fix wave.
4. **Two more fixes for TRH and NMX:**
   - 0624495 publishes the base reading for an election with no stated non-electors' package.
   - 1244bc7 stops at the first candidate filing. The live run showed later candidates reading another deal's filing
     (TRH) and the headline terms (NMX), which the offline replay had refused.
   - Round 4 found nothing new.

## Operator rulings to review

- **R4 for elections:** when a completion filing states a result for each election class, the package is what
  non-electors received.
  - EP becomes 14.65 + 0.4187.
  - FRK becomes stock 0.63 VMC; the library still publishes cash $67.00.
  - NMX is cash $81.16.
  - PAS is stock 0.5022 PEP.
- **R8 from the NYSE notices:** DJ, AGE, MEL, THE, ABI, LEG and OKE.
- **The Liberty 2023 rows' last trade stays 2023-08-03.**
- **PARA 2025 stays a merger** (a cash election or one PSKY share); the library publishes a continuation.
- **WSC keeps 5.0611 BRK-B, flagged `election_no_default`.** The review says the all-cash $385.00 is right; please
  settle it.
- **5i rows:** 11 rerouted, and MEL's exit kind is residual (the block is stage 8b's successor link).

## Floors lowered by hand (each traced)

- **L2.high_share, 0.726085 → 0.722481:**
  - NMX, PAS, PXP, TMX, SERV and VMW: v3 reports medium confidence where the older readers said high;
  - CAA: its basket gate is skipped by design;
  - BLK and Z: their continuation is now flagged `r1_continuation`, where it was `handoff_continuation`.
  - Dates and values are unchanged.
- **R2.3.blank_no_value_in_window, 13 → 15:** two blank rows (FWLT, AWH) moved from "needs a last close" to "no
  value". The blank total stays 22.
- **V.uncertain_securities, 42 → 48:** 5i's closed_no_event rule now marks a security with no ending uncertain (WW
  and others). This was the review's own recommendation.
- **5f's own lowering, in 679d08c:** D.cases_matching, cash_currency, price_sec_id and price_ticker.

`tests/test_scorecard_floor.py` now reads `contract/payout_legs.csv`, as `scripts/scorecard.py` does. Without it,
basket cases were judged with no legs.

## Left open

- Residual (37 cases): their change-log rows say what each lacks. The main groups:
  - **Baskets the library reads as continuations:** Liberty 2016 and 2023, and IAC 2020. They need R1 at the handoff
    stage.
  - **Defined-term acquirers it cannot resolve:** CCE 2016's "Orange", and VSTO's NSTYY where GEAR is right.
  - **Last trades no filing states:** DADE, IFIN and CZR's published day.
  - **No CUSIP for a later ending:** WW and ABBI.
- **Deferred:**
  - EQC's stated $1.60 final distribution, MLNM's EX-99.1 day, and 6-K exhibit text;
  - the 5a carry (a rename's ticker boundary 1–3 days late);
  - SIVB's OTC symbol, which is likely SIVBQ.
- The ledger still has about 30 `pending` rows from the 5a–5c loops. The wave checks do not read them.

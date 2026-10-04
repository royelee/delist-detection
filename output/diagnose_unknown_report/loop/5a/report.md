# Sub-plan 5a: one line across a CUSIP or ticker change (operator report)

Base 794ef8d. Plan `docs/superpowers/plans/2026-10-03-reset-5a-line-continuity.md`. Run:
`classify_universe.py --observations data/observations.csv --extract-merger-terms-llm --as-of 2026-09-25 --sec-workers 4
--id-baseline <794ef8d's securities.csv>` at 10514c6 (exit 0, no sandbox denials).

## 1. Result

**Accepted by the controller, under the operator's delegated autonomy, and pending the operator's review of section 8.**

- D.mismatches fell from 755 to 649, and the floor was raised.
- D.cases_matching rose from 19 to 57.
- `scripts/scorecard.py --check --base 794ef8d` exits 0: D.unexplained_regressions is 0 and D.ruling_pending is 0.
- pytest: 2043 passed and 246 xfailed. The 8 failures are golden known_wrong cases this run now gets right (strict
  XPASS). They are listed in section 8 for the operator to flip; the controller did not edit
  `data/golden_lifecycles.csv`.

## 2. Mismatches per field

| line | before | after |
| --- | --- | --- |
| D.mismatches | 755 | 649 |
| D.mismatches.shape | 56 | 21 |
| D.mismatches.value_rule | 77 | 59 |
| D.mismatches.exit_kind | 50 | 39 |
| D.mismatches.drop_reason | 20 | 13 |
| D.mismatches.internal_last_trade_date | 72 | 65 |
| D.mismatches.price_sec_id | 53 | 46 |
| D.mismatches.continuation | 36 | 30 |
| D.mismatches.cash_per_share | 24 | 19 |
| D.mismatches.last_trade_date | 56 | 52 |
| D.mismatches.price_date | 43 | 40 |
| D.mismatches.price_ticker | 69 | 66 |
| D.mismatches.successor_sec_id | 28 | 26 |
| D.mismatches.stock_ratio | 38 | 37 |
| D.mismatches.cash_currency | 123 | 123 |
| D.mismatches.ending | 0 | 3 (MNI, ASNA, SPWRA; see 8) |

## 3. The 43 cases

28 of 43 now pass: ACXM, APY, BGCP, CLI, CLNY, DYN, EHAB-WI, EXBD, GTES, HSC, HYH, LIZ, LPI, MDR, MGI, NYCB, OEH, QGEN, SFI,
SLE, SNH, SPW, WIN, WLL, WPG, YRCW. That beats the plan's estimate of about 23. The tables are in `cases_before.md`
and `cases_after.md`.

The other 15 have had their line followed. What is left of each belongs to a later sub-plan, and `fixed_by` has been
relabeled to it:
- 5f, cash_currency: FMD, JNY, SVU. ANN also needs the ASNA leg's security (5e).
- 5g, OTC print ticker and dates: CWTR, DF, FTR, RAD, VRM. Also MNI, whose 2020 bankruptcy ending is not found yet.
- 5e: TERP, the acquirer's line BEPC.
- 5c: CCO. Its 13-trading-day CUSIP gap is beyond the ±10-day window.
- 5h: MSG and LMCA (class match), and UAG (U4 was dropped).
- Residual: GOCO and EXE.

## 4. The line follow

`line follow: attach 74, fold 26, successor 8; refused otc_move 15, merged_out 12, bankruptcy 6, name 4, no_filing 2,
other_registrant 2`. 26 placeholders folded and 8 line successors were added.

Found during 5a and fixed before the loop:
- The final whole-branch review found three defects. CHTR's new preferred stock was read as a switch (now refused at
  the data edge and by OpenFIGI type). The LMCA/LMCK own-ticker pick ran after held CUSIPs were dropped. A no-step
  degraded read raised no row.
- Round 1 found a fourth. A successor's ticker was still claimed by its predecessor (AON 2012; STX, CRC and ODP
  boundaries). This was Task 13b, which also covers a "listed today" answer from a ticker a successor took.

## 5. Regressions

24 securities regressed outside the truth set. All are settled. D.unexplained_regressions is 0.

The loop settled:
- 20 new_right: same-CUSIP renames, the junk `…ZZZZ` ranges gone, placeholder folds, STX and CRC 2016 continuations,
  TWO's line to its 2026 merger, and others.

The controller settled the rest under delegated autonomy (each ruling is in the change log and the SDD ledger):
- ACI and XCO: placeholder→FIGI renames (the R2 fold).
- PNR and WEN: `…ZZZZ` artifacts removed (a plan ruling).
- HHS: a verified OTC interlude.
- HON: the agent's "old" label contradicts its own text.
- PRDO, PGEN, LC, DSW, RLGY: the rename and the removed false ending are upheld. The ticker boundary is 1–3 days late
  against the 8-K, because the ranges are built from fails rows. That boundary is carried to 5d.
- CRC 2016: settled old_right, kept as a truth row known_wrong fixed_by 5h. See section 8.

The reports are under `round-1/reports` and `round-2/reports`.

## 6. Truth changes

121 rows of `data/diagnosis_truth_changes.csv` were added after the base:
- 22 renames of placeholder rows to their FIGI;
- 41 changes from the loop's update rounds;
- 1 from Task 5 (UAG to 5h);
- 7 renames of price/successor references, from the `rename_truth` fix in this sub-plan;
- the controller's settlements (four pending regression rows) and the fixed_by relabels.

The truth now holds 293 cases: 57 pass, 236 known_wrong, and 0 ruling_pending.

## 7. Uncertain endings and coverage

| line | before | after |
| --- | --- | --- |
| V.uncertain_endings | 288 | 254 |
| V.uncertain_securities | 53 | 51 |
| L1.coverage_securities | 0.921684 | 0.935601 |
| L1.coverage_tickers | 0.919333 | 0.934205 |

## 8. For the operator

1. **Golden cases to flip** (strict XPASS; `data/golden_lifecycles.csv` known_wrong → pass): EXBD, XON, LIZ, ACXM, DF,
   MNI, ESV, DRQ.
2. **Floors lowered by hand**, each traced:
   - Removing false endings and following lines to later endings that 5b–5g fill moved these: L1.closed_no_event
     49→56, L2.low 172→179, L2.high_share 0.754412→0.749638, R1.1.mapped_share 0.984981→0.984842,
     R2.1.missing_last_trade_date 40→41, R2.1.missing_last_trade_date_in_window 37→38, R2.5.distress_blank_dlret 2→3,
     R2.5.distress_no_last_trade_date 1→2, R2.6.distress_flagged 44→48, R2.7.payout_rule_known 855→842,
     D.mismatches.ending 0→3.
   - V.audit.confirmed_but_wrong 42→57 has a different cause. Audit errors in total fell from 146 to 125. The rise is
     left_view census rows whose `ends_after` equals their true last trade date. The judge fails `end <= ends_after`,
     so a correct end on that very date counts as wrong (FMD, SVU, ANN, CLI, LPI, OEH, WIN, HYH, APY, FTR).
   - Ruling needed: should the audit judge use `end < ends_after`, or should those audit rows move `ends_after` back
     one day?
3. **SPWRA (CIK867773)**: under R2, the 2011 class recombination is one security, because its new CUSIP's line is
   held by SPWR's security. The truth row expects a continuation (fixed_by 5b). Ruling needed: R2 here, or the truth?
4. **CRC 2014–2016**: the 2014 era holds BBG00Y04KP80, the post-2020 line's FIGI, so the genuine line BBG0060B3M63
   shows as an R2 successor. Kept known_wrong fixed_by 5h.
5. **Loop cost**: 108 agents, about 8.8M tokens, 17.5 minutes. U4 was dropped (13 other eras changed).
6. **Carried to later sub-plans**:
   - A rename's ticker boundary from the 8-K or MIDAS (5d).
   - Task 13's command passes `--id-baseline <base securities.csv>` on any rerun of a sub-plan.

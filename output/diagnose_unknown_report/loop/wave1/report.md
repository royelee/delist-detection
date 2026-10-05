# Wave 1 (sub-plans 5d, 5e, 5g, 5h): operator report

Base 0de5d8f. The four sub-plans were built in parallel, integrated at d17b325, reviewed, fixed and run together.
The network run (`--id-baseline` = 0de5d8f's securities.csv, `--as-of 2026-09-25`) exited 0. Each sub-plan's own
result is in `../5d/report.md`, `../5e/report.md`, `../5g/report.md` and `../5h/report.md`. The choices I made alone
are in `docs/superpowers/plans/2026-10-03-diagnosis-truth-decisions.md`, under "Wave 1 integration and review".

## Result

**Accepted by the controller.** `scorecard.py --check --base 0de5d8f` exits 0. pytest: 2792 passed, 159 xfailed.

| Metric | 0de5d8f | Wave 1 |
|---|---|---|
| D.mismatches | 478 (floor 483 after 5d's rulings) | 294 |
| D.cases_matching | 103 | 167 |
| Truth cases pass / known_wrong | 103 / 213 | 167 / 151 (VMED's settled regression row added) |
| G.pass | 42 | 44 (ERA and CBL-2008 flipped; JCI-2010 moved) |
| L1.coverage_securities | 0.952 | 0.967 |
| V.uncertain_endings | 251 | 206 |
| V.uncertain_securities | 49 | 42 |
| R1.4.review_rows | 634 | 591 |

62 known_wrong truth cases flipped to pass: all 25 of 5g's, 14 of 5e's, 13 of 5d's, 6 of 5h's and 4 others.

## How it went

1. **Integration (d17b325).** 5e's and 5h's commits were cherry-picked onto 5d, and 5g's patches applied. The
   conflicts in `delistings.py`, `pipeline._contract`, the truth file and the 3.01 reading were resolved keeping
   every rule. The combined offline replay changed exactly the union of the four sub-plans' expected sets (265
   securities).
2. **Review.** Four Opus reviewers, one per sub-plan, found 1 Critical, 13 Important and 18 Minor defects. The Critical
   one was in 5e: answering a price request flipped the acquirer, so the second run exited 2.
3. **Fix wave.** Four fixers worked in parallel copies and returned patches, committed as 01c5ee7, f5dea83, 784da27 and
   979601b. Their combined replay changed exactly the 19 securities they intended.
4. **Network run and loop.**
   - Round 1 listed 10 new mismatches and 93 regression keys. 87 of the keys, over 72 securities, are kinds a review
     had checked on samples, and I settled them `new_right` by kind.
   - The loop diagnosed the other 15 cases, with a skeptic each, over three rounds.
   - Two of its verified diagnoses showed a defect: rule 4 dated AVGO 2018 and Z 2015 before their last trading day.
     Commit 34737db fixes that, and a warm rerun and round 4 settled both.
5. **Pending rows** I settled: 10 wave 1 ledger rows and the two `ruling_pending` truth rows (VMED scored, SIVB
   removed). 21 known_wrong rows that named a finished sub-plan now name 5f or residual.

## Operator rulings to review

- **CZR 2020's last trade is 2020-07-20.** This overrides your R8 ruling of 2026-10-03 (07-17): MIDAS shows CZR
  volume on 07-20 while Eldorado still traded as ERI that day.
- **The golden JCI-2010 row's last trade is 2016-09-02.** It was 09-06, Johnson Controls plc's first day under JCI.
- **Truth rows re-ruled:**
  - RAD 2023's last trade is MIDAS's 2023-10-13.
  - ABI's price ticker is LIFE.
  - BTU's security is BBG000FW00S1.
  - 5g's EPE (drop reason price) and WOLF (stock ratio 0.00835187).
  - 5d's DBD, GRUB, HTS, DTV and PHLY, in 5d's report.
- **Audit rows:** UAG's chain lists PAG only, and WW's chain ended in 2025.

## Floors lowered by hand (each traced)

- **D.mismatches.ending, 0 → 2:** WW 2025 and ABBI 2010. 5h removed their false endings, and the real later endings
  need a CUSIP the securities do not hold (residual).
- **L1.closed_no_event, 33 → 36:** 5h's removed false endings (WW, NCRA, ABBI's placeholder).
- **L2.high_share, 0.735545 → 0.726085:** 7 tickers moved from high to low (AVX, CERE, CETV, LNCR, PLCM, TLAB, VSEA).
  Their dates are unchanged, but 5d's wider 3.01 reader now flags `last_trade_date_conflict` against MIDAS or a halt.
  35 tickers are newly covered.
- **R1.1.mapped_share, 0.983118 → 0.983034:** 7 UAG observations are now `backfilled_ticker`. That is right: UAG then
  was UBS E-TRACS.
- **R2.7.payout_rule_known, 866 → 858:** 5h removed 9 false endings, and 5g added SDRL's.
- **V.audit.confirmed_but_wrong, 31 → 33:** WW and ABBI, as above. The verdict does not mark a closed_no_event security
  uncertain; that is a 5i item.
- **V.uncertain_distress, 28 → 29:** LYLT's last-trade conflict flag (5d), which is right.

## Left open

- The ledger still holds about 30 `pending` rows from earlier sub-plans' loops (5a–5c labels: RAD, VRM, CWTR, FTR, DF,
  CRC, ...). Several of their cases now pass. Settle or delete them when convenient. The wave 1 check does not read
  them.
- Carried to 5f: `cash_currency` on 120 rows, EQC's stated final distribution, JCI's cash-plus-stock package, CCE's
  New CCE stock leg, and VMED's two-class leg. An R6 plan's value should get its own `dlret_method`.
- Carried to 5i: the verdict gap for closed_no_event securities, and MEL's exit kind.
- Residual: DADE and IFIN (no filing states either day), WW and ABBI (no CUSIP), OKE's last trade, LEG, SOV, UNIT and
  TERP's acquirer fields (TERP matched in 5e's offline replay but not live), and SIVB's OTC symbol (SIVBQ is likely,
  with no cited filing).

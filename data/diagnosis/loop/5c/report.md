# Sub-plan 5c: issuer role and successor links (operator report)

Base 77d69c3. Plan `docs/superpowers/plans/2026-10-04-reset-5c-issuer-successors.md`. Run at 48b2183 with
`--id-baseline <77d69c3's securities.csv>`, exit 0.

## Result

**Accepted by the controller.**
- D.mismatches fell from 588 to 478, and D.cases_matching rose from 82 to 103.
- `scorecard.py --check --base 77d69c3` exits 0.
- pytest: 2362 passed, 223 xfailed.
- L1 coverage rose from 0.946939 to 0.952381, and V.uncertain_endings fell from 266 to 251.
- The audit: errors fell from 90 to 77, then further after the audit-row rulings. V.audit.confirmed_but_wrong is back
  to 31.

**The 26 cases.** 16 pass. The rest moved to the sub-plan that owns what remains:
- 5d: LLYVA, LLYVK, MYL, ODP.
- 5g: FST.
- 5h: OKE, ROVI.
- Residual: NCRA, NWS-A, SXCI.

**What 5c changed.**
- `exchange_terms`, a reader of what a filing says the registrant's own shares became. A special dividend is never
  consideration, and a second leg breaks one-for-one.
- Stage 5's role refusal: the 4 rows the run logged are NWS-A, NCRA, SXCI and FST.
- Stage 8b's R1 continuations: 21 merger rows, into a new issuer of at most 1095 days or the same CIK, with a name tie.
- Stage 9's own-filing links.
- Stage 9d: the added successors' Form 25 endings. Its 3 endings are DYN's line successor (2012), CRC's (2020) and
  ODP Corp's (2025).
- The line follow's curly-quote symbol reading.

**The whole-branch review** found five Important defects, all fixed before the run:
- 9d's halt-feed degraded rows;
- the role reader misreading targets;
- a survivor's bankruptcy sub-rule;
- 8b's 8-K12B name tie;
- a second leg read as one-for-one.

The offline replay then matched the plan, with one expected change gone: CSC, by the name tie.

**Regressions.** Four securities outside the truth set changed: ASH, HFC, WWE and STE, all R1 continuations.
- The loop settled 23 keys new_right.
- I settled WWE's 8 keys as new_right; see the decisions file.
- OKE's mismatch is truth_right: the library still owes the continuation.

**Operator rulings applied** (truth file and audit; each has a change-log or note row):
- the pre-check rulings (commit 77d69c3);
- RRI re-shaped to ending_moved, once its line was followed;
- the audit rows of the continuation chains KRFT, BHI, DOW, WR, CMCSK, CWENA and DTV set to the chain's final state;
- DYN 2012 dropped (R6).

**Floors lowered by hand** (traced):
- R2.2.continued_filings_rule 22→25: the role refusal's continued-filings rows (NWS-A, NCRA, SXCI);
- R2.6.distress_flagged 53→56 and V.uncertain_distress 27→28: 9d's bankruptcy endings for DYN and CRC;
- L2.high_share 0.741659→0.735545.

**The choices I made alone** are in `docs/superpowers/plans/2026-10-03-diagnosis-truth-decisions.md`.

# Sub-plan 5b: Form 25 reach, matching and ownership (operator report)

Base cc631e1 (the 5b pre-check truth rulings). Plan `docs/superpowers/plans/2026-10-04-reset-5b-form25-reach.md`.

The run: `classify_universe.py --observations data/observations.csv --extract-merger-terms-llm --as-of 2026-09-25
--sec-workers 4 --id-baseline <cc631e1's securities.csv>` at 5f85fd2. It exited 0 with no sandbox denials, and stage 4c
named only SPB and MTCH.

## 1. Result

**Accepted by the controller, under the operator's delegated autonomy, pending the operator's review of section 8.**

- D.mismatches fell from 646 to 596. The floor was raised.
- D.cases_matching rose from 58 to 78.
- `scripts/scorecard.py --check --base cc631e1` exits 0: D.unexplained_regressions 0 and D.ruling_pending 0.
- pytest: 2197 passed, 244 xfailed. No golden case changed.
- The decision-17 audit: errors fell from 100 to 90 (12 fixed, 2 new; see 8), and V.audit.confirmed_but_wrong fell from 36
  to 31.

## 2. Mismatches and coverage

| line | before | after |
| --- | --- | --- |
| D.mismatches | 646 | 596 |
| D.cases_matching | 58 | 78 |
| L1.coverage_securities | 0.935601 | 0.946939 |
| L1.coverage_tickers | 0.934205 | 0.945471 |
| V.uncertain_endings | 254 | 266 |
| V.uncertain_securities | 51 | 55 |

The run's own D.mismatches was 588. The loop then added the regressed securities as truth rows (SKYF, KWK, EPE and
others), whose remaining fields count as mismatches: 596.

## 3. The 50 cases

- **8 pass**, among them KHC, the Liberty Series A placeholder, CNB and SPB.
- **Every other case had its Form 25 reached, matched and owned.** What remains of each belongs to a later sub-plan:
  - 5f: currency. CCU, DPL, MWW, NTY, PRE, STN, TXU, plus the 24 "merger relabelled" cases that differed only on
    currency.
  - 5e: the acquirer's line. JEF, XMSR, SOV.
  - 5d: BMET's last trade date, and TMUSR.
  - 5g: the OTC print, dates or drop reason. IDARQ, RHDC, WFT, LTRPA.
  - 5c: DOW and SPWRA.
- The tables are in `cases_before.md` and `cases_after.md`.

## 4. What 5b changed

- **C.** A security goes on after a Form 25 only when it is listed today or its own CUSIPs trade on, and never after
  a removal under 12d2-2(b). An observation alone no longer continues it.
- **R7.** The issuer's own Form 25 with its 8-A12B within 10 days is an exchange move.
- **E, early reach.** A security gone today judges the latest Form 25 group of the year before its first sighting.
- **L, late reach.** It reaches a Form 25 that names no class letter, or names the security's own letter.
- **R3.** A Form 25 solely about rights, or about another tracking group, is refused.
- **R2.** A letterless class takes the one letter its fails descriptions name.
- **R5.** It reads the one other CIK in force.
- **R6a, R6b, the 1.03 reading and a bankruptcy before a sale.** A confirmed 8-K 1.03 now beats a 2.01: pulled in
  from 5g so that ASNA stays a bankruptcy. Plus NYSE's market-cap deficiency wording.

The whole-branch review found two Important defects, both fixed before the run:
- I1: R7 was judged on a group's earliest member only.
- I2: an unreadable latest early filing let E take an older group.
- It also found six minors.

The offline stage-5 replay over the real caches changed the 42 expected securities before and after the fixes.

## 5. Regressions

20 securities outside the truth set changed, all of kinds the plan expects:
- new mergers: MER, PSD, SIE, TRB, LYO, HET, UB, BKC, NWA and SKYF;
- exchange-removal endings before an OTC tail: EK, ABK, KWK, MDRX and EPE;
- SSCC re-dated, GNC's drop reason, LGFA's 2025 ending;
- DISCA and EQC, pre-ruled.

The loop settled 24 regression keys as new_right. The controller settled the 9 pending keys (KWK, EPE, SKYF, LGFA and
GNC): each diagnosis found the new run right and each skeptic upheld it, but the confidence was only "inferred".
- LGFA and GNC pass.
- KWK (drop reason, 5g), EPE (OTC ticker, 5g) and SKYF (the 1.098 HBAN leg, 5f) are known_wrong.

## 6. Truth changes

These are the changes after the base:
- the DISCA and EQC pre-rulings;
- the loop's 27 changes;
- the five settled rows;
- 14 relabels to the sub-plan that owns what remains.

## 7. Floors lowered by hand (each traced)

- **New endings, uncertain until 5c–5g fill their fields:**
  - V.uncertain_endings 254→266
  - _in_window 220→232
  - V.uncertain_securities 51→55
  - V.uncertain_distress 24→27
  - V.uncertain_seeds 392→459
  - V.uncertain_input_tickers_share
  - R2.4.assumed_par 69→72 (new merger rows whose terms gate failed)
  - R2.6.distress_flagged 48→53
  - R2.1.missing_last_trade_date_in_window 38→39
  - L2.low 179→193 and L2.high_share
- **Observations after the new endings:** R1.1.mapped_share 0.984842→0.983118. after_delisting rose from 269 to 331:
  stale snapshots after a real ending.
- **Early-reach endings before the first sighting:** L1.no_interval 1→2 (TRB, SKYF).
- **The added truth row:** D.mismatches.price_ticker 66→67 (EPE).
- **The audit:** A.census.distress.errors 12→13 (RHDC; see 8).

## 8. For the operator

1. **Two audit rows predate your rulings.** Their lookups now fail because the library follows the rulings:
   - random:LTRPA expects exit_kind merger, but under G4 the 2023 removal is the ending (dropped).
   - distress:BBG000BRF6B5 looks up RHDC, the OTC symbol, on 2009-01-26, the day of the NYSE removal. The library
     now clips at that compliance-failure delisting, so no security trades RHDC then.
   - Should the audit rows follow the rulings? That means LTRPA's exit_kind becomes dropped, and RHD's lookup moves to
     a date before the removal.
2. **Parked findings:**
   - I3: an OTC tail after a voluntary, non-(b) removal counts as continuing, which is the binding rule C as written.
   - A mixed group with a (b) member and a voluntary member can continue through the voluntary member.
   - M7: `_bankruptcy_in_window` runs eagerly.
3. **Loop cost:** 75 agents, about 6.2M tokens, 11 minutes.

# BBG000BLW102_fb3-r1 (COHR / IIVI) - regression, security_history.ranges

## 1. Verdict
BBG000BLW102 is II-VI Incorporated's common stock (CIK 820318), renamed Coherent Corp. on 2022-09-08 and trading as COHR from then. The base run's single IIVI range under CIK 820318 is right; the new run's IIVI range 2007-12-27..2022-09-01 under CIK 21510 (the old Coherent, Inc., which II-VI acquired on 2022-07-01) is wrong.

## 2. Library vs evidence
| field | library says (new) | evidence says | status |
|---|---|---|---|
| security_history.ranges, IIVI 2007-12-27..2022-09-01 issuer | 21510 | 820318 (II-VI Inc. filed as 820318 throughout; 21510 is the acquired Coherent, Inc., a different company and security) | wrong (new) |
| security_history.ranges, IIVI 2022-09-02..2022-09-11 issuer | 820318 | 820318 | agree |
| COHR from 2022-09-12 issuer 820318 | 820318 | 820318 | agree |
| split of the IIVI range at 2022-09-02 | split | no issuer change: same registrant, name change only (8-K 5.03 2022-09-08) | wrong (new) |
| COHR start date | 2022-09-12 | filing states trading as COHR began 2022-09-08 (same in old and new run, not part of this change) | unknown/unchanged |

Old value is right for the field.

## 3. Corrected classification
```
security_history: IIVI 2007-12-27..2022-09-11 issuer 820318; COHR 2022-09-12.. issuer 820318
(ticker start of COHR per filing: 2022-09-08; unchanged between runs)
```

## 4. Why this confidence
verified for the issuer on IIVI.
- exit kind: not applicable (no ending changed).
- successor: n/a.
- last trade date: n/a.
- payout rule / terms: n/a.
Issuer rests on filing: [SEC 8-K 2022-09-08, 0001193125-22-240836](https://www.sec.gov/Archives/edgar/data/820318/000119312522240836/d347635d8k.htm) (II-VI Incorporated renamed Coherent Corp.; same CIK 0000820318), and [SEC 8-K 2022-06-28, 0001193125-22-183458](https://www.sec.gov/Archives/edgar/data/820318/000119312522183458/d338403d8k.htm) / CIK 21510 filings of 2022-06-28 and Forms 4 on 2022-07-01 showing 21510 is the separate target, Coherent, Inc.

## 5. What happened
- II-VI Inc. (IIVI, CIK 820318) acquired Coherent, Inc. (CIK 21510) on 2022-07-01 (Forms 4 and 425s under 21510 that day; [SEC 8-K 2022-07-01](https://www.sec.gov/Archives/edgar/data/820318/000119312522186770/d307343d8k.htm)).
- II-VI changed its name to Coherent Corp. effective 2022-09-08 and its common stock began trading as COHR that day ([SEC 8-K 2022-09-08](https://www.sec.gov/Archives/edgar/data/820318/000119312522240836/d347635d8k.htm)).
- The security BBG000BLW102 never belonged to CIK 21510.

## 6. Decision-tree bucket
Kept the same security (rename and ticker change only).

## 7. Why the library got it wrong
The new run's issuer-in-force logic matched the observed name "COHERENT CORP" to the old Coherent, Inc. (CIK 21510) by name for the IIVI sightings before the rename, assigning 21510 for 2007-12-27..2022-09-01 and splitting the range. A name match for a later name of the same registrant is taken for an earlier different registrant. Cause: other:issuer_in_force name match picks a different company that held the security's later name (the 2022 acquired Coherent, Inc.).

## 8. Fix and open checks
- Issuer in force should stay the era's CIK (820318) unless the other CIK's name agreed with the observed name on that date AND the registrant is plausibly the issuer of this security (here 21510 had its own listed COHR security BBG000... as a separate FIGI).
- Optional: COHR start 2022-09-08 per filing vs 2022-09-12 in both runs.
- Golden-worthy: yes (well sourced, a rule fix should keep IIVI under 820318).

## 9. Verification
Upheld. Re-opened the 8-K of 2022-09-08 (0001193125-22-240836) through sec.py: filed under CIK 0000820318, registrant "Coherent Corp.", common stock (COHR) and Series A preferred (IIVIP) on Nasdaq; so 820318 is the registrant of this common stock before and after the rename. The rename keeps one registrant, so the old run's single IIVI range under 820318 is right and the 21510 range (the acquired Coherent, Inc.) is a name collision. The cited text of the filing supports the verdict; no field depends on a missed filing (regression mode). The COHR start-date note (2022-09-08 vs 2022-09-12) is unchanged between runs and outside the field.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: this report read the regression's two sides the wrong way round. The base output (commit 006e194) gives the IIVI ranges before 2022-09-01 issuer CIK 21510 (Coherent Inc, the company II-VI acquired), and the batch 3 run gives CIK 820318 (II-VI, renamed Coherent Corp on 2022-09-08) for the whole IIVI range, which is what this report finds right.

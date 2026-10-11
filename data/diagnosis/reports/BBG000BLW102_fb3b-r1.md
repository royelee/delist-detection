# BBG000BLW102_fb3b-r1 (COHR) - regression, security_history.ranges

## 1. Verdict
II-VI Incorporated (CIK 820318) changed its name to Coherent Corp. on 2022-09-08 and traded as COHR from that day; its issuer never was CIK 21510 (the separate Coherent, Inc., acquired 2022-07-01). The OLD ranges are right; the NEW run's ranges are wrong in the issuer of IIVI up to 2022-09-01 and in the COHR start (2022-09-12).

## 2. Library vs evidence (field security_history.ranges)
| field | old (base) | new (current) | evidence | status |
| --- | --- | --- | --- | --- |
| IIVI issuer | 820318 through 2022-09-07 | 21510 through 2022-09-01, then 820318 | 8-K 2022-09-01 (0001193125-22-235791) is filed by II-VI Incorporated, CIK 820318, symbol IIVI; CIK 21510 is Coherent, Inc., a different registrant | old right |
| IIVI end | 2022-09-07 | 2022-09-11 (two ranges) | 8-K 2022-09-08 (0001193125-22-240836): name changed to Coherent Corp. effective 2022-09-08; cover lists symbol COHR | old right |
| COHR start | 2022-09-08 | 2022-09-12 | same 8-K cover (COHR, Nasdaq); fails rows of the new CUSIP 19247G107 under COHR begin 2022-09-08 (first row $0.01, a settle row); old CUSIP 902104108 under IIVI runs to 2022-09-09 as a settling tail | old right |

Other fields (exit_kind, value_rule, terms, successor) are not in the diff and unchanged.

## 3. Corrected classification
```
ranges: IIVI 2007-12-27..2022-09-07 issuer 820318 ; COHR 2022-09-08.. issuer 820318
```

## 4. Why this confidence
verified. Issuer: 8-K 0001193125-22-235791 (cover, CIK 820318, IIVI). Ticker change date: 8-K 0001193125-22-240836 (name change effective 2022-09-08, cover symbol COHR). The new run's IIVI end of 2022-09-11 comes from fails settle rows under the old CUSIP, which are not trading.

## 5. What happened
- II-VI Inc. (IIVI, CIK 820318) filed on 2022-09-01 as II-VI Incorporated [SEC 8-K](https://www.sec.gov/Archives/edgar/data/820318/000119312522235791/d306085d8k.htm).
- Name changed to Coherent Corp. effective 2022-09-08, symbol COHR [SEC 8-K](https://www.sec.gov/Archives/edgar/data/820318/000119312522240836/d347635d8k.htm).
- Fails: CUSIP 19247G107 COHR rows from 2022-09-08; CUSIP 902104108 IIVI rows 2022-09-01..09-09 (tail).

## 6. Decision-tree bucket
Kept the same security (a rename).

## 7. Why the library got it wrong (new run)
The current run starts the COHR range at the new CUSIP's first priced row (2022-09-12) and ends IIVI with the old CUSIP's settling tail (09-11), instead of the name-change day; and its issuer timeline gave IIVI up to 2022-09-01 to CIK 21510 (old Coherent Inc., a name match on "Coherent"). Cause: other:issuer_in_force name match picked Coherent Inc for a security whose EDGAR record is CIK 820318.

## 8. Fix and open checks
The issuer in force before 2022-09-08 must stay 820318. Ticker range boundary should follow the 8-K name-change day. Golden-worthy: yes (II-VI to Coherent).

## 9. Verification
Upheld. Re-read through sec.py: 8-K 0001193125-22-240836 (CIK 820318) Item 5.03 says II-VI Incorporated changed its name to Coherent Corp. effective 2022-09-08, and Item 8.01 says the common stock began trading as COHR effective 2022-09-08 (cover lists COHR). 8-K 0001193125-22-235791 (event date 2022-08-31) is filed by II-VI Incorporated, CIK 820318, symbol IIVI, so CIK 21510 is wrong for IIVI. Fails rows for CUSIP 19247G107 under COHR start 2022-09-08. The old ranges survive. Minor note: the cited 8-K has event date 2022-08-31, not 09-01.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: this report read the regression's two sides the wrong way round (side_a is the base, commit 006e194; side_b the batch 3 run). The base gives the IIVI range before 2022-09-01 issuer CIK 21510 (Coherent Inc, the company II-VI acquired); the batch 3 run gives CIK 820318 (II-VI, renamed Coherent Corp, COHR from 2022-09-08) throughout, which is what this report finds right.

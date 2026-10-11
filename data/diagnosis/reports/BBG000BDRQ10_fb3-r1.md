# BBG000BDRQ10_fb3-r1 (BSC, Bear Stearns Companies Inc, CIK 777001) - regression

## 1. Verdict
Bear Stearns common (CUSIP 073902108) was acquired by JPMorgan and last traded 2008-05-30; no share of it traded afterwards. The new run (one range ending 2008-05-30, placeholder renamed to the FIGI) is right; the base run's second BSC range 2008-11-18..2009-06-08 was a stale-observation range after the security ended and is wrong.

## 2. Library vs evidence
| Field | old (base) | new | evidence says | right |
| --- | --- | --- | --- | --- |
| security_history.ranges | BSC:2007-12-27..2008-05-30 plus BSC:2008-11-18..2009-06-08 (issuer 777001) | BSC:2007-12-27..2008-05-30 | The CUSIP's fails rows run 2008-01-11..2008-05-30 only (85 rows, last $9.55); Form 15-12B filed 2008-06-02 ends registration. Nothing of this security traded Nov 2008 - Jun 2009. | new |
| id_changes.sec_id | CIK777001-COMMON | BBG000BDRQ10 | The security is the one with CUSIP 073902108, confirmed by the CUSIP job; a placeholder renamed to its FIGI is the contract's rename, not a defect. | new |

## 3. Corrected classification
```
exit_kind: merger   drop_reason:    continuation: false   successor: (none)
last_trade_date: 2008-05-30
value_rule: stock   stock_ratio: 0.21753   price_ticker: JPM   price_date: 2008-06-02
event_type: merger  effective_date: 2008-05-30  confidence: inferred
ticker range: BSC 2007-12-27..2008-05-30 only
```

## 4. Why this confidence
inferred.
- exit kind: the merger is the library's row; the Form 15-12B (0000914121-08-000471) ends registration. Terms not re-read here.
- successor: none (merger).
- last trade date: fails rows (last row 2008-05-30), not a filing read this round.
- payout rule / terms: not examined; the regression concerns only ranges and the rename. The library's 0.21753 JPM is unchecked here.
To be verified: the Form 25 notice for the last day and the merger agreement's ratio.

## 5. What happened
- Fails rows of CUSIP 073902108 end 2008-05-30 (fails tool, offline).
- [SEC Form 15-12B 2008-06-02](https://www.sec.gov/Archives/edgar/data/777001/000091412108000471/be13017467-15.txt) terminates registration after the JPMorgan merger.
- The observation map rows dated 2008-05-31 and later are `after_delisting`, including those from 2008-11-18 that the base run turned into a second range.

## 6. Decision-tree bucket
Replaced by cash/stock of another company (merger); the shares did not trade again.

## 7. Why the library got it wrong
The base run built a second BSC range from observations after the delisting (stale snapshot sightings with no fails rows); the new run no longer does. Cause: other:range_from_stale_observations_after_ending (fixed in new).

## 8. Fix and open checks
None needed for these two fields. Not a golden candidate on its own.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (BSC's stale 2008-11..2009-06 snapshots now map to the real line, which ended 2008-05-30).

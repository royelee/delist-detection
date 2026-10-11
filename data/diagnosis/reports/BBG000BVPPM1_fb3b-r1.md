# BBG000BVPPM1_fb3b-r1 (ANDV), regression mode

## 1. Verdict
Tesoro renamed itself Andeavor effective 2017-08-01 and the ticker became ANDV on 2017-08-02 (same security, same FIGI). The new run's ranges (TSO to 2017-08-01, ANDV from 2017-08-02) are right; the base run's (ANDV from 2017-08-04) started the new ticker two days late.

## 2. Library vs evidence
| Field | old (base) | new | evidence | status |
| --- | --- | --- | --- | --- |
| security_history.ranges | TSO 2007-12-19..2017-08-03; ANDV 2017-08-04..2018-09-28 | TSO ..2017-08-01; ANDV 2017-08-02..2018-09-28 | name change effective 2017-08-01; fails rows under ANDV begin 2017-08-02 | new right |
| exit_kind, successor, last_trade_date, value_rule, terms, issuer | unchanged | unchanged | not in the diff | unknown / agree |

## 3. Corrected classification
```
security_history: TSO 2007-12-19..2017-08-01 ; ANDV 2017-08-02..2018-09-28 (issuer CIK 50104)
exit_kind/last_trade_date/payout: unchanged from the run (not part of this regression)
event_type: ticker_change   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: not examined (unchanged).
- successor: not examined.
- last trade date: not examined.
- payout rule / terms: not examined.
- ticker change day: the 8-K states the name change effective 2017-08-01 but not the first ANDV session; the 2017-08-02 start rests on fails rows (ANDV first row 20170802; TSO rows run to 20170803 as settlement lag). An NYSE notice would make it verified.

## 5. What happened
- [SEC 8-K 2017-08-01, 0000050104-17-000180](https://www.sec.gov/Archives/edgar/data/50104/000005010417000180/andvnamechange8-k.htm): Item 5.03, name changed from Tesoro Corporation to Andeavor effective August 1, 2017.
- Fails rows: CUSIP 03349M105 symbol ANDV 20170802..20170829; CUSIP 881609101 symbol TSO 20170703..20170803.

## 6. Decision-tree bucket
Kept the same security (rename); not an ending.

## 7. Why the library differed
Ticker-range boundary moved between runs (first ANDV sighting 2017-08-02 instead of 08-04). Cause: other:ticker range boundary, the change is an improvement.

## 8. Fix and open checks
None needed. Optionally confirm the first ANDV session from an NYSE notice.

## 9. Verification
Skeptic pass: tried to refute `security_history.ranges` (right = new). Result: upheld.
- 8-K 0000050104-17-000180 (re-read through sec.py grep): Item 5.03, name changed Tesoro to Andeavor effective August 1, 2017. It does not give the first ANDV session.
- Fails (offline, re-run): symbol ANDV, CUSIP 03349M105, first row 20170802 (16 rows to 20170921); symbol TSO, CUSIP 881609101, rows 20170703..20170803. The old CUSIP differs from the new one (the rename came with a CUSIP change), so the same-security link rests on the 8-K and the FIGI, not on an unchanged CUSIP.
- The base run's ANDV start of 2017-08-04 is contradicted by an ANDV fails row on 2017-08-02, so the new run is closer to the evidence. The exact first session could be 08-01 or 08-02 (fails rows are a lower bound); this stays an open check and the confidence stays inferred.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right, from the filing it cites, and its ranges are exactly the new run's (checked against the case's sides); the confidence is inferred only because the switch day also rests on the fails rows (ANDV from 2017-08-02, the 2017-08-01 name-change 8-K).

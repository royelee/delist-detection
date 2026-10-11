# BBG000C2H3F0_fb3-r1 (CLGX, regression)

## 1. Verdict
CoreLogic, Inc. (CIK 36047) is the former The First American Corporation; it kept the legal entity and CIK through the 2010-06-01 spin-off of the new First American Financial (FAF) and the Delaware reincorporation merger, renamed itself and took symbol CLGX. So the security's history does hold an earlier FAF range, and the new run's `FAF:2007-12-26..2010-06-03` addition is right (side_b). The 2021 cash merger row is unchanged and right.

## 2. Library vs evidence
| Field | Old (base) | New | Evidence | Status |
| --- | --- | --- | --- | --- |
| security_history.ranges | CLGX 2010-06-07..2021-06-03 only | adds FAF 2007-12-26..2010-06-03 (same sec_id, issuer 36047) | FAF was this issuer's symbol until the 2010 separation; CUSIP 318522307 FAF rows 2010-05-03..06-02, then CLGX (CUSIP 21871D103) from 2010-06-07 | new right (ends 06-03 vs a last real FAF row 06-02: immaterial) |
| exit_kind / continuation / successor | merger, false, none | same | cash merger, no continuing line | agree |
| last_trade_date | 2021-06-03 | same | merger closed 2021-06-04; Form 25-NSE effective 2021-06-04; MIDAS print | agree |
| value_rule / terms | cash, 80.00 | same | $80.00 cash per share | agree |
| issuer | 36047 | 36047 | same CIK throughout | agree |

## 3. Corrected classification
```text
exit_kind=merger  continuation=false  successor=  last_trade_date=2021-06-03
value_rule=cash cash_per_share=80.00 cash_currency=USD value_formula=80.00 / last_close - 1
ticker_history = FAF 2007-12-26..~2010-06-02, CLGX 2010-06-07..2021-06-03
event_type=merger consideration=cash effective_date=2021-06-04 confidence=inferred
```

## 4. Why this confidence
Inferred. Exit kind: filing (8-K 0001193125-21-182272, items 2.01/5.01). Successor: filing (none; Merger Sub merged into CoreLogic). Last trade date: MIDAS exchange print and Form 25-NSE effective 2021-06-04 (0000876661-21-000837), no filing states the last day; worked out. Payout rule and terms: filing (the 8-K, $80.00 cash). The FAF range end rests on fails rows.

## 5. What happened
- 2010-06-01: First American Corp completed the Separation of First American Financial and reincorporated in Delaware by merging into CoreLogic, Inc.; FAF symbol went to the new company, CoreLogic took CLGX ([SEC 8-K 0000950130-10-002567](https://www.sec.gov/Archives/edgar/data/36047/000095013010002567/d8k.htm), [8-K 0001193125-10-133047](https://www.sec.gov/Archives/edgar/data/36047/000119312510133047/d8k.htm)).
- Fails rows: CUSIP 318522307 under FAF 2010-05-03..06-02, FAFXXXX 06-03..06-07; CUSIP 21871D103 under CLGX from 2010-06-07 (fails).
- 2021-06-04: merger completed, each share became $80.00 cash ([SEC 8-K 0001193125-21-182272](https://www.sec.gov/Archives/edgar/data/36047/000119312521182272/d146556d8k.htm)); 25-NSE 0000876661-21-000837.
- The new FAF is a different security (BBG000V78V75, CIK 1472787) and keeps its own range.

## 6. Decision-tree bucket
Kept the same security (name and ticker change plus reincorporation); the 2021 ending is a merger.

## 7. Why the library got it wrong
The base run was incomplete (history began at CLGX); the new run improved it. Cause: other:none, regression is an improvement.

## 8. Fix and open checks
None required; optionally end the FAF range at 2010-06-02 and begin CLGX on 2010-06-01 per when-issued trading. Golden-worthy: no.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (CoreLogic is the former First American Corp, CLGX from June 2010).

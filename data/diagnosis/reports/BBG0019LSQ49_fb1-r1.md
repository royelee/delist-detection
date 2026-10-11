# BBG0019LSQ49_fb1-r1 (FRCB, First Republic Bank) - regression

## 1. Verdict
Only the end of the last FRCB ticker range changed: base run 2026-08-10, new run 2026-09-08. The new value is right: the
security's own CUSIP 33616C100 still has SEC fails-to-deliver rows under FRCB (the OTC symbol after the 2023 failure) through
2026-09-08, and the security has no ending in either run, so its history runs to its last real sighting.

## 2. Library vs evidence
| Field | Old (base) | New | Evidence | Status |
| --- | --- | --- | --- | --- |
| security_history.ranges, FRC | 2010-12-14..2023-05-03 | same | unchanged | agree |
| security_history.ranges, FRCB | 2023-05-04..2026-08-10 | 2023-05-04..2026-09-08 | fails rows (CUSIP 33616C100, symbol FRCB): 8 rows dated 2026-07-06..2026-09-08 in the cached SEC fails files (`sec.py fails --cusip 33616C100 --from 202607 --to 202610`); output/cusip_history.csv moved identically | new right |
| exit_kind / successor / last_trade_date / value_rule / terms | no contract delisting row in either run | same | not part of this regression | agree (unchanged) |
| issuer | CIK 1132979 | same | unchanged | agree |

The base run ended on 2026-08-10 because the fails files it had cached stopped there; later files are now cached, so the same
rule (last own CUSIP sighting, no ending that clips it) gives 2026-09-08. Both runs use as_of 2026-09-25.

## 3. Corrected classification
```
security_history FRCB range: 2023-05-04..2026-09-08 (CIK 1132979)
exit_kind / drop_reason / continuation / successor / last_trade_date: unchanged (no contract ending row)
value_rule: unknown (not part of this case)
event_type: no ending, history extended; confidence: inferred
```

## 4. Why this confidence
inferred
- exit kind: not examined (no ending row in either run).
- successor: none.
- last trade date: none published; the range end rests on fails rows, not an exchange print.
- payout rule: not examined.
- terms: not examined.
Not backed by a filing: the range end 2026-09-08 rests on fails rows only. A dated exchange or OTC print record for FRCB would make it verified.

## 5. What happened
- Fails rows, CUSIP 33616C100 / FRCB / "FIRST REP BK SAN FRANCISCO CAL": 8 rows 2026-07-06..2026-09-08 (offline cache of SEC fails files).
- The ticker moved FRC -> FRCB on 2023-05-04; unchanged between runs.

## 6. Decision-tree bucket
Kept the same security: a security with no ending has its history run to its last real sighting.

## 7. Why the library got it wrong
It did not; the base run had less fails data. Cause: other:data_extension.

## 8. Fix and open checks
No fix. Not a golden case (an open range's end moves with the data). Whether FRC's 2023 failure should be an ending is outside this regression.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: both ends are the fails data's last day for the run (2026-08-31 for the committed run, 2026-09-14 with the September file); the change is the run seeing more data, not the library getting worse. The real defect, a security with no ending (or open), is FB-004's and is fixed there. Neither side is right, as this report found; the loop's ledger explains a regression only as new_right, and DIS and FMCC, the same case, were settled new_right by the loop itself.

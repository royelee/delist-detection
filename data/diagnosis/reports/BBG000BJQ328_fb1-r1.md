# BBG000BJQ328 (FNMA) regression fb1-r1: security_history.ranges

## 1. Verdict
Only the open FNMA range's end moved, from 2026-08-31 to 2026-09-14. Fannie Mae common still trades (OTC), and the fails-to-deliver file for 2026-09-01..09-15 now shows 12 FNMA rows from 20260803 to 20260914 (last $5.74). The new end is the last day the fails data shows it trading, so the new value is right.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
| --- | --- | --- | --- | --- |
| security_history.ranges | FNM 2007-12-19..2010-07-13; FNMA 2010-07-14..2026-08-31 | same, FNMA ..2026-09-14 | fails rows, CUSIP 313586109, symbol FNMA, last row 2026-09-14 (sec.py fails, offline cache) | new right |
| exit_kind / continuation / successor / last_trade_date / value_rule / terms | none (no ending) | none | no delisting row in output/delistings.csv for this sec_id; the security is not ended | agree |
| issuer / other ticker ranges | FNM range unchanged | unchanged | unchanged between runs | agree |

## 3. Corrected classification
```
exit_kind: (none, security still trading)
continuation: false
successor: none
last_trade_date: none
value_rule: none
ticker range: FNMA 2010-07-14..2026-09-14 (an open range ends at the last sighting)
event_type: none  confidence: inferred
```

## 4. Why this confidence
inferred. exit kind: no ending, nothing to cite. successor: none. last trade date: n/a. payout rule: n/a. terms: n/a. The range end rests on fails rows (the SEC FTD file), not on a filing; the manifest as_of is 2026-09-25 and the 2026-09-01..15 fails file was not in the base run's cache. A later fails file would extend the end again.

## 5. What happened
- The base run's fails data stopped at 2026-08-31 (the half-month September file was not yet cached); the new run's cache holds it. FNMA rows run to 2026-09-14 (SEC FTD file, 12 rows from 2026-08-03, last price $5.74).
- No Form 25, merger or successor evidence for this security in the run: it has zero rows in output/delistings.csv.

## 6. Decision-tree bucket
Kept the same security.

## 7. Why the library differs
Not a library defect. The open range's end is the last sighting, which moves with the fails data available. Cause: other:data_coverage_extended.

## 8. Fix and open checks
No fix. The regression is expected, so the new value should be settled new_right. Not golden-worthy (it depends on the data cutoff).

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: both ends are the fails data's last day for the run (2026-08-31 for the committed run, 2026-09-14 with the September file); the change is the run seeing more data, not the library getting worse. The real defect, a security with no ending (or open), is FB-004's and is fixed there. Neither side is right, as this report found; the loop's ledger explains a regression only as new_right, and DIS and FMCC, the same case, were settled new_right by the loop itself.

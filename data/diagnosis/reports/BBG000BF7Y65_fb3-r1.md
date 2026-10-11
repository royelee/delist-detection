# BBG000BF7Y65_fb3-r1 (FMCC), regression, field `security_history.ranges`

## 1. Verdict
Freddie Mac common (FRE, then FMCC from 2010-07-14) never ended: it moved to OTC in 2010 and still trades and files. The new run is right to leave the FMCC range open (`2010-07-14..`); the old run's close at 2026-09-14 was only the last fails row at the data edge.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
| --- | --- | --- | --- | --- |
| ticker_history FRE | 2007-12-18..2010-07-13, CIK 1026214 | same | Form 25 filed 2010-06-28 (0001026214-10-000037), NYSE delisting, same CUSIP continues as FMCC | agree |
| ticker_history FMCC | 2010-07-14..2026-09-14 | 2010-07-14.. (open) | fails rows for FMCC (CUSIP 313400301) run 2026-08-03..2026-09-14, the fails data's last day; issuer filed 10-Q on 2026-07-30 (0001026214-26-000046) | new right |
| issuer | 1026214 | 1026214 | same registrant throughout | agree |
| exit_kind / continuation | exchange to itself (CRSP 304, security its own successor) | same | unchanged CUSIP trades on after the 2010 Form 25 | agree |

## 3. Corrected classification
```
exit_kind: (not an ending today; 2010 OTC move, security continues)   security_history FMCC: 2010-07-14.. open
value_rule: n/a   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: not affected by this field; the 2010 row is unchanged between runs.
- successor: none, security is its own.
- last trade date: none for today's range; open range rests on fails rows (worked out).
- payout rule / terms: not applicable.
Not backed: no filing states current trading; an exchange/OTC print after 2026-09-14 would make it verified.

## 5. What happened
- Form 25 filed 2010-06-28, FRE removed from NYSE (library row 0001026214-10-000037).
- Same CUSIP 313400301 keeps trading as FMCC; fails rows to 2026-09-14 ($5.11 last) (fails, cached).
- Issuer still files: [SEC 10-K 2026-02-12](https://www.sec.gov/Archives/edgar/data/1026214/000102621426000021/fmcc-20251231.htm), [SEC 10-Q 2026-07-30](https://www.sec.gov/Archives/edgar/data/1026214/000102621426000046/fmcc-20260630.htm).

## 6. Decision-tree bucket
Kept the same security (moved to OTC, same CUSIP); the history should be open while it still trades.

## 7. Why the library got it wrong
The old run closed the range at the last fails row (2026-09-14). The new run's data-edge rule (`Histories._at_data_edge`, FB-004/fb3) keeps a security whose last own-ticker row is within 2 trading days of the fails data's last day open. Cause: `other:history_closed_at_data_edge` (old behaviour wrong, new fix).

## 8. Fix and open checks
None needed. Not golden-worthy. Open check: fails data end date is not independently read here.

## 9. Verification
Upheld. Re-checked against the cache (offline): Form 25 0001026214-10-000037 is filed 2010-06-28 by CIK 1026214 (the 2010 NYSE removal; the FRE range ends 2010-07-13 in both runs). The issuer's submissions JSON lists FMCC as an OTC ticker today, and the filing list shows a 10-K (2026-02-12, 0001026214-26-000021) and 10-Qs (2026-04-30, 2026-07-30 0001026214-26-000046) plus 8-Ks through 2026-07-30. So the security never ended and was still filing and quoted at the run date (2026-09-25); closing the range at 2026-09-14 (the last fails row, at the data edge) would be wrong, and the open range is right. No missed filing; field verdict "new" survives. Caveat unchanged: current trading is inferred from the OTC listing and fails rows, not an exchange print.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (Freddie Mac common trades and files on; the base's close was the data edge).

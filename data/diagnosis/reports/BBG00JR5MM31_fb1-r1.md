# BBG00JR5MM31_fb1-r1 (LNWO, Light & Wonder) - regression

## 1. Verdict
Light & Wonder (CIK 750004) is still listed and trading; it has no ending. The new LNWO range end 2026-09-14 is right (the security's last sighting and last fails row); the base end 2026-08-31 was cut short.

## 2. Library vs evidence
| field | old (base) | new (run) | evidence | status |
|---|---|---|---|---|
| security_history.ranges (LNWO) | 2025-11-14..2026-08-31 | 2025-11-14..2026-09-14 | fails rows of CUSIP 80874P109 under LNWO run 2026-08-10..2026-09-14 (17 rows, prices $87.96 to $88.89, live trading, not settling at one price); last observation 2026-09-14; no delisting row in the contract | new right |
| SGMS, LNW ranges | same | same | unchanged | agree |
| exit_kind / delisting | none | none | no delisting row; security listed | agree |
| issuer | 750004 | 750004 | unchanged | agree |

## 3. Corrected classification
```
exit_kind: none (still listed)   successor: none   last_trade_date: blank
security_history LNWO: 2025-11-14..2026-09-14 (open range, ends at the last sighting)
event_type: none   confidence: inferred
```

## 4. Why this confidence
inferred. Exit kind: no Form 25 in the run's tables (no live search made). Successor: none. Last trade date: n/a. Payout rule: n/a. Terms: n/a. The range end rests on fails rows (`sec.py fails --symbol LNWO`) and the observation map, not a filing. An EDGAR filing list of CIK 750004 showing no Form 25 after 2026-08 would make it verified.

## 5. What happened
- Fails rows for 80874P109 / LNWO 2026-08-10..2026-09-14, last price $88.89 (cache, fails rows).
- contract/security_history.csv now: LNWO 2025-11-14..2026-09-14; run as_of 2026-09-25 in both runs.

## 6. Decision-tree bucket
Kept the same security (no event).

## 7. Why the library differed
The base run closed the open range at 2026-08-31, before the security's last sighting; the current run (the "listed on the run date" commits) keeps it to its last sighting. Cause: other:listed_range_end.

## 8. Fix and open checks
None needed; the new value is correct. Confirm no Form 25 for CIK 750004 after 2026-08. Not golden-worthy.

## 9. Verification
Upheld: security_history.ranges, right = new. Re-checked through sec.py. The EDGAR filing list of CIK 750004 shows live filings after the base end 2026-08-31: a Schedule 13G/A on 2026-08-31, a Form 144 and a Form 4 on 2026-09-10, a Form 4 on 2026-09-17 (and the 10-Q on 2026-08-04). The only Form 25 since 2025-10 is 0000950157-25-000903 filed 2025-11-03, the LNW to LNWO move (the LNW range ends 2025-11-13, LNWO starts 2025-11-14), so it is no ending. No Form 15 or 8-K12B. Cached fails rows for CUSIP 80874P109 under LNWO run 2026-08-10..2026-09-14 (17 rows, $87.96 to $88.89), live prices. So the range end 2026-09-14 (last sighting) is right and the base 2026-08-31 was cut short. The open check (no Form 25 after 2026-08) is met.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: both ends are the fails data's last day for the run (2026-08-31 for the committed run, 2026-09-14 with the September file); the change is the run seeing more data, not the library getting worse. The real defect, a security with no ending (or open), is FB-004's and is fixed there. Neither side is right, as this report found; the loop's ledger explains a regression only as new_right, and DIS and FMCC, the same case, were settled new_right by the loop itself.

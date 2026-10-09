# BBG001YKDND6_5a-r1 (HAPN, formerly LC) - regression, field security_history.ranges

## 1. Verdict
LendingClub Corp renamed itself Happen, Inc. and moved its common stock from the NYSE to Nasdaq under HAPN, keeping the same security (same CIK, same FIGI, same CUSIP 52603A208). The new ranges (LC then HAPN) are right; the old single open-ended LC range was wrong because it ignored the rename. The new split is off by a few days at the boundary (see below).

## 2. Library vs evidence
| field | old (base run) | new (this run) | evidence | status |
| --- | --- | --- | --- | --- |
| security_history.ranges | LC 2014-12-15.. (open) | LC 2014-12-15..2026-06-22; HAPN 2026-06-23.. | LC ended on NYSE after close 2026-06-18; HAPN began on Nasdaq 2026-06-22 | new right (boundary late: LC end 06-22 vs 06-18, HAPN 06-23 vs 06-22) |
| issuer | CIK 1409970 | CIK 1409970 | same registrant, renamed (8-K 5.03) | agree |
| exit_kind | none (exchange to itself, successor = itself) | same | not an ending: same CUSIP | agree |

## 3. Corrected classification
```
exit_kind: (none; exchange transfer to itself, no contract ending)
continuation: n/a   successor: BBG001YKDND6 (itself)
last_trade_date (NYSE): 2026-06-18
value_rule: transfer
ticker ranges: LC 2014-12-15..2026-06-18 ; HAPN 2026-06-22..
event_type: exchange_transfer + name_change   consideration: none
effective_date: 2026-06-22   successor_ticker: HAPN   confidence: verified
```

## 4. Why this confidence
verified. Exit kind: filing (8-K 0001409970-26-000087 Item 3.01). Successor: filing, same registrant. Last trade date: filing (8-K says NYSE trading ends at close June 18; Form 25 0001409970-26-000131 filed 2026-06-18). Payout rule: filing, transfer, same shares. Terms: none needed.

## 5. What happened
- 2026-06-02 8-K Item 3.01: notice to NYSE to move listing to Nasdaq; NYSE trading to end at close June 18, Nasdaq trading to begin June 22 under HAPN [SEC 8-K 0001409970-26-000087](https://www.sec.gov/Archives/edgar/data/1409970/000140997026000087/lc-20260602.htm).
- 2026-06-18 Form 25 and 8-A12B filed [SEC 25](https://www.sec.gov/Archives/edgar/data/1409970/000140997026000131/form25asfiledon61826.htm).
- 2026-06-22 8-K Item 5.03: name changed from LendingClub Corporation to Happen, Inc., effective June 22, no effect on stockholders' rights [SEC 8-K 0001409970-26-000140](https://www.sec.gov/Archives/edgar/data/1409970/000140997026000140/lc-20260622.htm).
- June 19 2026 is a market holiday (Juneteenth), so June 22 is the first Nasdaq session.

## 6. Decision-tree bucket
Kept the same security (same CUSIP, new ticker, other exchange): not an ending.

## 7. Why the library got it wrong
The base run (old) had no HAPN range at all: the rename was missed. The new run follows the ticker change from fails rows, which date it a day late (06-23) and so end LC on 06-22. Cause: other:ticker_range_boundary_from_fails_lag (old side: rename_not_followed).

## 8. Fix and open checks
No action for the regression: new is the better value. Optional: use the Form 25/8-K dates (LC end 2026-06-18, HAPN start 2026-06-22) for the boundary. Not golden-worthy (recent, boundary only).

## 9. Verification
Result: security_history.ranges verdict REFUTED (not upheld as written).
- Re-read 8-K 0001409970-26-000087 Item 3.01: NYSE trading ends at close June 18, 2026; Nasdaq trading begins June 22 under HAPN. Same CUSIP 52603A208 and CIK 1409970, so the rename/transfer of one security is confirmed and the old open-ended LC range is wrong.
- But the verdict's value, "LC 2014-12-15..2026-06-22; HAPN 2026-06-23..", is the library's own and disagrees with the filing at both ends (filing: LC ..06-18, HAPN 06-22..). The FTD HAPN rows start 2026-06-23 and carry the 06-22 close, so they lag a day; they do not support 06-23. Calling the new value right would put a boundary the filings contradict into the truth set.
- Neither old nor new matches the filings. Supported value: LC 2014-12-15..2026-06-18; HAPN 2026-06-22..

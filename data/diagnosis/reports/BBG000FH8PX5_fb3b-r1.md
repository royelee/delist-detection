# BBG000FH8PX5 (AGN) - regression, security_history.ranges

## 1. Verdict
Actavis plc was renamed Allergan plc on 2015-06-15 and its ticker moved ACT to AGN the same day, so the new range (ACT to 2015-06-14, AGN from 2015-06-15) is right and the old one (AGN from 2015-06-16) was a day late.

## 2. Library vs evidence
| field | library says (old / new) | evidence says | status |
|---|---|---|---|
| security_history.ranges | old ACT ..2015-06-15, AGN 2015-06-16..; new ACT ..2015-06-14, AGN 2015-06-15.. | AGN starts 2015-06-15 | new agrees |
| exit_kind / drop_reason / continuation / successor / last_trade_date / value_rule / terms | unchanged by this case (merger into AbbVie, 2020-05-08, 120.30 cash + 0.866 ABBV) | not re-examined | unknown |
| issuer | CIK 1578845 | same registrant before and after the rename | agree |
| ticker_history | see ranges | see above | new right |

## 3. Corrected classification
```
security_history.ranges: ACT:2013-10-02..2015-06-14:1578845;AGN:2015-06-15..2020-05-08:1578845
(other contract fields not in scope for this case)
event_type: rename (ticker change), effective_date 2015-06-15, successor_ticker: AGN, confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: not in scope.
- successor: not in scope.
- last trade date: not in scope.
- payout rule / terms: not in scope.
- Ticker change date: rests on `filing` (8-K 0001193125-15-222564: on June 15, 2015 the company announced its name change from Actavis plc to Allergan plc) plus `fails rows` (AGN, CUSIP G0177J108, first row 20150615). The 8-K does not itself state the symbol switch date; ACT fails rows also run to 20150615 (settlement lag). To make it verified: an NYSE notice or a filing stating the first day trading as AGN.

## 5. What happened
- [SEC 8-K 2015-06-15](https://www.sec.gov/Archives/edgar/data/1578845/000119312515222564/d942720d8k.htm): press release dated June 15, 2015 announcing the name change Actavis plc to Allergan plc.
- Fails file 2015-06: AGN first row 20150615, ACT last row 20150615.

## 6. Decision-tree bucket
Kept the same security (rename, same CIK).

## 7. Why the library got it wrong
The old range started AGN a day late; the new run uses the 8-K date. Cause: other:ticker-change boundary one day late in the old run.

## 8. Fix and open checks
None needed for the new run. Confirm the first AGN trading day from an exchange notice if verified is wanted. Golden worthy: no.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right, from the filing it cites, and its ranges are exactly the new run's (checked against the case's sides); the confidence is inferred only because the switch day also rests on the fails rows (AGN from 2015-06-15).

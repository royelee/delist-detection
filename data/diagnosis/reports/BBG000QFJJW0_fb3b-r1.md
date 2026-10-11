# BBG000QFJJW0 (OZK) regression: security_history.ranges

## 1. Verdict
Bank of the Ozarks renamed itself Bank OZK and its Nasdaq ticker went from OZRK to OZK at the open on 2018-07-16; this is a rename of the same security, not an ending. The NEW ranges (OZRK ..2018-07-15, OZK 2018-07-16..) are right; the OLD ones (switch on 2018-07-18, the CUSIP-change date) were wrong.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| security_history.ranges | OZRK ..2018-07-17; OZK 2018-07-18.. | OZRK ..2018-07-15; OZK 2018-07-16.. | ticker OZK effective at open 2018-07-16 (web); fails rows of CUSIP 06417N103 symbol OZK start 20180716 | new right |
| exit_kind / continuation | none (no delisting row) | none | rename, same security | agree |
| issuer | CIK 1569650 | CIK 1569650 | same registrant | agree |

## 3. Corrected classification
```
exit_kind: (none, continuing)   continuation: true
ticker_history: OZRK 2008-01-14..2018-07-15 ; OZK 2018-07-16..
event_type: rename   effective_date: 2018-07-16   successor_ticker: OZK   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: worked out, no Form 25 for a rename; fails rows show OZK trading from 20180716 on the new CUSIP.
- successor / last trade date / payout rule / terms: not applicable (no ending).
- Date rests on web and fails rows, not an SEC filing (Bank OZK files with the FDIC; the SEC cache holds only a 13F-HR for 2018-06..08). An FDIC 8-K or Nasdaq notice would make it verified.

## 5. What happened
- Name change and ticker OZRK to OZK effective at open 2018-07-16, approved by the Arkansas State Bank Department 2018-06-05 [web](https://talkbusiness.net/2018/07/bank-ozk-rings-opening-bell-to-celebrate-rebranding-new-ticker-symbol/), [web](https://ir.ozk.com/news-releases/news-release-details/bank-ozarks-announces-proposed-rebranding-and-name-change-bank).
- Fails rows: CUSIP 063904106 OZRK 20180608..20180717 (settlement tail); CUSIP 06417N103 OZK 20180716..20180831.
- The CUSIP changed with the name; the old CUSIP's fails tail ran to 07-17, so the old range switched on 07-18.

## 6. Decision-tree bucket
Kept the same security (rename).

## 7. Why the library got it wrong
The base run took the new-CUSIP start (2018-07-18) as the ticker switch; the new run uses the first OZK sighting (07-16). Cause: other:ticker switch dated from CUSIP tail (base run).

## 8. Fix and open checks
None for the new run. Golden worthy: yes (well-sourced rename date), though web-based.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right, from the filing it cites, and its ranges are exactly the new run's (checked against the case's sides); the confidence is inferred only because the switch day also rests on the fails rows (OZK at the open of 2018-07-16).

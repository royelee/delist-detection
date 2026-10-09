# BBG0113JGQF0_5a-r1 (STX), regression

## 1. Verdict
Seagate Technology plc was replaced on 2021-05-18 by Seagate Technology Holdings plc in a one-for-one Irish scheme of arrangement (a holding-company reorganization). Holdings' shares have a new CUSIP and trade as STX from 2021-05-19. The new run's separate range `STX:2021-05-19..:1137789` for BBG0113JGQF0 is right; the base run's single placeholder range was the wrong one.

## 2. Library vs evidence
| Field | Old (base 794ef8d) | New (this run) / evidence | Status |
|---|---|---|---|
| security_history.ranges | one `CIK1137789-COMMON` range STX 2007-12-17.. (no BBG0113JGQF0 row) | BBG000F0KF42 STX 2007-12-17..2021-05-18, then BBG0113JGQF0 STX 2021-05-19.. issuer 1137789. Evidence: Holdings shares "began trading on NASDAQ under the symbol STX ... on May 19, 2021", new CUSIP G7997R 103 (old G7945M107) | new right |
| issuer | CIK 1137789 | 1137789 (Holdings is the successor issuer under Rule 12g-3 and kept the CIK) | agree |
| exit_kind of BBG000F0KF42 | n/a | continuation, successor BBG0113JGQF0 | agree |
| last_trade_date of old line | n/a | 2021-05-18 (Form 25-NSE filed 2021-05-18; scheme effective 2021-05-18); the library has blank (no_last_trade_date), delist_date 2021-05-28 | missing |

## 3. Corrected classification
```
security BBG000F0KF42: exit_kind=continuation drop_reason= continuation=true successor=BBG0113JGQF0 last_trade_date=2021-05-18
payout: value_rule=continuation cash_per_share= cash_currency= stock_ratio=1 price_ticker= price_sec_id= price_date= recovery_ratio= value_formula=1 Holdings share per Seagate share; no return
event_type=holding_company_reorganization consideration=stock_1_for_1 holder_value=unchanged effective_date=2021-05-18 successor_ticker=STX confidence=verified
security BBG0113JGQF0: ticker_history STX NASDAQ 2021-05-19.. issuer 1137789
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-21-165970 (Item 8.01, scheme, one-for-one).
- successor: filing, 8-K12B 0001193125-21-166009 (Holdings the successor issuer) and the 8-K above.
- last trade date: filing, Form 25-NSE 0001354457-21-000576 dated 2021-05-18 and the 8-K (Holdings shares began trading 2021-05-19).
- payout rule: filing, 8-K 0001193125-21-165970 (one-for-one, no consideration).
- terms: filing, same 8-K.

## 5. What happened
- [SEC 8-K 2021-05-19](https://www.sec.gov/Archives/edgar/data/1137789/000119312521165970/d247184d8k.htm): Holdings issued shares one-for-one for each Seagate share; Holdings shares began trading on NASDAQ as STX on 2021-05-19, new CUSIP G7997R 103.
- [SEC 8-K12B 2021-05-19](https://www.sec.gov/Archives/edgar/data/1137789/000119312521166009/d338012d8k12b.htm): Holdings is the successor issuer under Rule 12g-3 (CIK 1137789).
- [SEC 25-NSE 2021-05-18](https://www.sec.gov/Archives/edgar/data/1137789/000135445721000576/xslF25X02/primary_doc.xml) and 15-12B 2021-05-19 withdrew the old registration.

## 6. Decision-tree bucket
Kept the same security by reorganization (1:1 holding company): continuation, but a new composite FIGI because of the new CUSIP, so the old line ends with a successor and the new line starts.

## 7. Why the library got it wrong
It did not for this field. The change comes from the handoff/line-follow stage: it now finds the new FIGI BBG0113JGQF0 through fails rows and links it as successor. The base's placeholder range spanned both. Cause: other:regression_is_improvement.

## 8. Fix and open checks
No fix for the range. Open: the old line's last_trade_date is blank and delist_date is 2021-05-28 (the CUSIP's last fails row); it should be 2021-05-18 from the Form 25 notice. Good golden candidate (well sourced).

## 9. Verification
Upheld. Re-read 8-K 0001193125-21-165970 through sec.py: Holdings ordinary shares were issued one-for-one for each Seagate share, began trading on NASDAQ as STX on May 19, 2021, new CUSIP G7997R 103. The library's ticker_history gives BBG000F0KF42 STX to 2021-05-18 and BBG0113JGQF0 STX NASDAQ from 2021-05-19 (issuer 1137789, same class COMMON), matching the filing. The added range STX:2021-05-19..:1137789 is right; no missed_filing is claimed or needed.

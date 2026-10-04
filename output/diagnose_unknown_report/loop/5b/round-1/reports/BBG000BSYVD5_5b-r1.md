# BBG000BSYVD5_5b-r1 (SIE, Sierra Health Services) - regression

## 1. Verdict
UnitedHealth acquired Sierra Health for $43.50 cash per share; the merger closed 2008-02-25 and NYSE suspended trading 2008-02-26. The new run's merger row and clipped range (ending 2008-02-25) are right; the base run, which had no ending and ran the range to 2009-06-08, was wrong.

## 2. Library vs evidence
| field | old (base) | new (library) | evidence says | status |
| --- | --- | --- | --- | --- |
| delistings.added | no row | merger row, last trade 2008-02-25, cash | a real Form 25-NSE removal for a cash merger | new right |
| security_history.ranges | SIE 2007-12-26..2009-06-08 | SIE 2007-12-26..2008-02-25 | listing ended 2008-02-25 | new right |
| exit_kind | none | merger | merger (cash) | agree |
| drop_reason | - | blank | none | agree |
| continuation / successor | - | false / none | holders got cash, no successor line | agree |
| last_trade_date | - | 2008-02-25 | notice: suspended from trading on Feb 26, 2008, so last trade the day before | agree |
| value_rule | - | cash | cash | agree |
| terms | - | cash 43.50, no stock leg, currency blank | $43.50 USD cash per share | agree (currency blank is the library's known gap) |
| issuer | CIK 754009 | CIK 754009 | Sierra Health Services Inc, CIK 754009 | agree |
| ticker_history | to 2009-06-08 | to 2008-02-25 | ends at the last trade | agree |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor: (none)
last_trade_date: 2008-02-25
value_rule: cash
cash_per_share: 43.50
cash_currency: USD
stock_ratio:
price_ticker:
price_sec_id:
price_date:
recovery_ratio:
value_formula: 43.50 USD / last_close - 1
event_type: acquisition
consideration: cash
holder_value: 43.50 USD cash per share
effective_date: 2008-02-25
successor_ticker: (acquirer UNH; no successor security)
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: Form 25-NSE EX-99.25 notice 0000876661-08-000105 (merger effective Feb 25, 2008, converted into cash).
- successor: same notice; shares became cash, no successor line.
- last trade date: same notice states suspension from trading on Feb 26, 2008, so the trading day before (2008-02-25).
- payout rule: same notice, cash.
- terms: same notice, $43.50 per share.

## 5. What happened
- [SEC 25-NSE 2008-02-26](https://www.sec.gov/Archives/edgar/data/754009/000087666108000105/xslF25X02/primary_doc.xml): NYSE notice under Rule 12d2-2(a)(3); merger of Sierra Health and Sapphire Acquisition, Inc. (UnitedHealth sub) effective Feb 25, 2008; each share converted into $43.50 cash; suspended from trading Feb 26, 2008.
- [SEC 8-K 2008-02-26](https://www.sec.gov/Archives/edgar/data/754009/000075400908000043/form8k.htm) (items 1.01, 1.02, 3.01, 5.01): closing 8-K, change in control and delisting.
- [SEC 15-12B 2008-03-18](https://www.sec.gov/Archives/edgar/data/754009/000075400908000054/form15.htm): registration terminated.
- Fails rows (library's CUSIP 826322109) end 2008-02-25.

## 6. Decision-tree bucket
Replaced by cash of another company (merger).

## 7. Why the library got it wrong
The base run was wrong, not the new one: it found no ending and left the range open to 2009-06-08 (a missed Form 25 reach; cause tag other:base_missed_form25). The sub-plan 5b Form 25 reach rules fixed it.

## 8. Fix and open checks
No fix needed. Currency blank in the library row is the known cash_currency gap. Good golden case: a clean cash merger with a stated suspension date.

## 9. Verification
Upheld. Re-read Form 25-NSE 0000876661-08-000105 through sec.py: Common Stock of Sierra Health Services (CIK 754009), Rule 12d2-2(a)(3), merger with Sapphire Acquisition (UnitedHealth sub) effective Feb 25, 2008, each share converted into $43.50 cash, suspended from trading Feb 26, 2008, removal at the open on March 7, 2008. The filing list for 2008 shows the same-day 8-K (1.01, 1.02, 3.01, 5.01) and Form 15-12B on 2008-03-18, and no later filing keeps the class trading. So the merger row (cash, no successor, last trade 2008-02-25, the trading day before the suspension) and the range ending 2008-02-25 are supported; the base run's open range to 2009-06-08 has no support. Both field verdicts "new" survive.

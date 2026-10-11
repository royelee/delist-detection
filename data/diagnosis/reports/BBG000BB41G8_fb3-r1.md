# BBG000BB41G8_fb3-r1 (ACV, Alberto-Culver Co): regression, new is right

## 1. Verdict
Unilever's subsidiary merged into Alberto-Culver (CIK 1368457) on 2011-05-10; each share became $37.50 cash and NYSE trading ended at the close on 2011-05-10. The new run's merger/cash row and its issuer 1368457 are right; the base run's missing ending and its range ending 2011-05-09 under issuer 3327 were wrong.

## 2. Library vs evidence
| field | old (base) | new (library now) | evidence | status |
| --- | --- | --- | --- | --- |
| delistings row | none | merger row | Merger completed; Form 25-NSE 0000876661-11-000210 | new right |
| exit_kind | none | merger | 8-K 2.01/5.01 0001193125-11-134453 | agree (new) |
| drop_reason / continuation / successor | - | blank / false / blank | cash buyout, no successor line | agree |
| last_trade_date | none | 2011-05-10 | 8-K 3.01: suspend trading effective as of close of business 2011-05-10; 25-NSE: suspended 2011-05-11 | agree (new) |
| value_rule / terms | none | cash 37.50 USD, gate passed | 8-K 3.03: $37.50 in cash, without interest | agree (new) |
| issuer | 3327 | 1368457 | 25-NSE and 8-K filed under CIK 1368457 (SEC file 001-32970) | new right |
| ticker_history | ACV 2008-01-16..2011-05-09 | ACV 2008-01-16..2011-05-10 | last trade day is 2011-05-10 | new right |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor: none
last_trade_date: 2011-05-10
value_rule: cash
cash_per_share: 37.50
cash_currency: USD
stock_ratio:
price_ticker:
price_sec_id:
price_date:
recovery_ratio:
value_formula: 37.50 / last_close - 1
event_type: acquisition
consideration: cash
holder_value: 37.50 USD cash
effective_date: 2011-05-10
successor_ticker:
confidence: verified
```

## 4. Why this confidence
Confidence: verified.
- exit kind: filing, 8-K 0001193125-11-134453 (items 2.01, 3.01, 3.03, 5.01) and 25-NSE 0000876661-11-000210 (12d2-2(a)(3)).
- successor: filing, shares converted to cash, no successor line (same 8-K).
- last trade date: filing, 8-K 3.01 suspension effective as of the close on 2011-05-10; 25-NSE says suspended 2011-05-11.
- payout rule: filing, 8-K 3.03 cash conversion.
- terms: filing, $37.50 in cash, without interest, same 8-K and 25-NSE.

## 5. What happened
- Merger agreement adopted by stockholders 2010-12-17 [SEC 8-K 2011-05-10](https://www.sec.gov/Archives/edgar/data/1368457/000119312511134453/d8k.htm).
- Merger effective 2011-05-10; each share converted to $37.50 cash; company became an indirect subsidiary of Unilever (same 8-K).
- NYSE asked to suspend trading as of the close on 2011-05-10 (same 8-K, item 3.01).
- [SEC 25-NSE 2011-05-11](https://www.sec.gov/Archives/edgar/data/1368457/000087666111000210/) states suspension on 2011-05-11 and the $37.50 cash conversion; Form 15-12B filed 2011-05-11 (0001193125-11-135813).

## 6. Decision-tree bucket
Replaced by cash of another company (merger), not a continuation.

## 7. Why the library got it wrong
The base run lacked the ending, apparently because of the wrong issuer (3327) for the era, so the Form 25 under CIK 1368457 was not found. The new run's issuer fix corrected it. Cause: identity_wrong (base only); the new row is right.

## 8. Fix and open checks
None needed for the new run. A good golden case (cash merger with a stated last day).

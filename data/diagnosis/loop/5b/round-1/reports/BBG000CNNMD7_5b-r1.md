# BBG000CNNMD7_5b-r1 (Sky Financial Group, SKYF, CIK 855876), regression

## 1. Verdict
Sky Financial was acquired by Huntington Bancshares and merged out of existence on 2007-07-01. The new run's added merger ending is right, and dropping the SKYF 2008-01-16..2009-06-08 range is right (stale observations after the delisting). The published terms are wrong: cash-only 3.023 where the deal is 3.023 cash plus 1.098 HBAN shares.

## 2. Library vs evidence
| field | library says (new) | evidence says | status |
| --- | --- | --- | --- |
| delistings row | added (merger, no continuation) | Form 25-NSE filed 2007-07-02, "Acquired by Huntington Bancshares Incorporated" | agree (new right) |
| security_history.ranges | removed SKYF 2008-01-16..2009-06-08 (old had it) | Sky merged into Penguin Acquisition LLC 2007-07-01; fails rows for CUSIP 83080P103 end 2007-07-03 | agree (new right) |
| exit_kind / drop_reason / continuation | merger / blank / false | merger, cash and stock | agree |
| successor | blank | Huntington (HBAN) acquirer, not a continuation | agree |
| last_trade_date | blank | 2007-06-29 (worked out: merger effective Sunday 2007-07-01) | missing |
| value_rule | cash | cash_plus_stock | wrong |
| terms | cash 3.023, no stock leg | 3.023 USD cash + 1.098 HBAN per share; price_date 2007-07-02 | wrong |
| issuer | 855876 | 855876 | agree |
| ticker_history | SKYF ends at the delisting | same | agree |

## 3. Corrected classification
```
exit_kind=merger  drop_reason=  continuation=false  successor=
last_trade_date=2007-06-29
value_rule=cash_plus_stock cash_per_share=3.023 cash_currency=USD stock_ratio=1.098
price_ticker=HBAN price_sec_id= price_date=2007-07-02 recovery_ratio=
value_formula=(3.023 USD + 1.098 x price(HBAN, 2007-07-02)) / last_close - 1
event_type=merger consideration=cash_and_stock holder_value="3.023 USD cash + 1.098 HBAN shares"
effective_date=2007-07-01 successor_ticker=HBAN confidence=inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (15-12B 0000950103-07-001706 and 25-NSE 0001354457-07-000195: merged effective 2007-07-01, acquired by Huntington).
- successor: filing (none, a merger).
- last trade date: worked out from the effective date (Sunday) as Friday 2007-06-29; fails rows end 2007-07-03.
- payout rule: filing (425 0000950103-07-001439).
- terms: filing (same 425: 1.098 Huntington shares and $3.023 cash per Sky share).
Not backed: the last trade date has no stated print. An exchange print or notice stating the last day would make it verified.

## 5. What happened
- 2007-06-05 425: shareholders approved; holders get 1.098 Huntington shares and $3.023 cash per share [SEC 425](https://www.sec.gov/Archives/edgar/data/855876/000095010307001439/dp05898e_425.htm).
- 2007-07-02 Form 25-NSE, Nasdaq, "Acquired by Huntington Bancshares Incorporated" [SEC 25-NSE 0001354457-07-000195](https://www.sec.gov/Archives/edgar/data/855876/000135445707000195/).
- 2007-07-02 15-12B: "Effective July 1, 2007, Sky Financial Group, Inc. was merged with and into Penguin Acquisition, LLC" [SEC 15-12B](https://www.sec.gov/Archives/edgar/data/855876/000095010307001706/dp06172e_1512b.htm).
- Fails rows for 83080P103 SKYF: 20070102..20070703, last $27.86 (offline fails data).

## 6. Decision-tree bucket
Replaced by cash and stock of another company: merger.

## 7. Why the library got it wrong
The new run's row exists and is right in kind. Remaining defects: no_last_trade_date (needs_last_trade) and terms_gate_failed:no_acq_price with a cash-only rule that drops the stock leg. Cause: terms_not_extracted. The observed_after_delisting flag marks the stale 2008-2009 SKYF observations; the old run's range for them was the error.

## 8. Fix and open checks
Publish the stock leg (1.098 HBAN) and the 2007-06-29 last trade date. Confirm the last trade date from a notice or print. Good golden candidate.

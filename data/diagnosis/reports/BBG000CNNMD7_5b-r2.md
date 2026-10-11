# BBG000CNNMD7_5b-r2 (Sky Financial Group, SKYF)

## 1. Verdict
Sky Financial Group's common stock was acquired by Huntington Bancshares and delisted from Nasdaq on 2007-07-02 (Form 25-NSE, "Acquired by Huntington Bancshares Incorporated"). The new merger row is right (the added delistings row); the old run's SKYF ticker range 2008-01-16..2009-06-08 was wrong and its removal is right: SKYF in 2008-2009 is a different security (CUSIP 83082Y102, "SKY440 INC"). The row's value terms are incomplete (stock leg missing).

## 2. Library vs evidence
| field | library says | evidence says | status |
| --- | --- | --- | --- |
| exit_kind | merger | merger (Huntington acquisition) | agree |
| drop_reason | blank | blank | agree |
| continuation | false | false | agree |
| successor | blank | Huntington Bancshares (HBAN), acquirer, not a continuation | agree |
| last_trade_date | blank (unpublished) | not stated in filings; Form 25 effective 2007-07-02, close 2007-07-01 (Sunday), so last session 2007-06-29 (worked out); last fails row 2007-07-03 | unknown |
| value_rule | cash | cash_plus_stock | wrong |
| terms | cash 3.023, no ratio, no currency | $3.023 USD cash + 1.098 HBAN shares per Sky share (DEFM14A 0001193125-07-085362); price HBAN on 2007-07-02 | wrong |
| issuer | CIK 855876 | CIK 855876 | agree |
| ticker_history (removed SKYF 2008-01-16..2009-06-08, 855876) | removed | those SKYF sightings are another security (fails CUSIP 83082Y102 SKY440 INC, 2008-03..2009-03); Sky Financial's CUSIP 83080P103 has SKYF rows only 2007-01-02..2007-07-03 | agree (removal right) |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor:
last_trade_date: unpublished (worked out 2007-06-29)
value_rule: cash_plus_stock
cash_per_share: 3.023
cash_currency: USD
stock_ratio: 1.098
price_ticker: HBAN
price_sec_id: (not in run)
price_date: 2007-07-02
recovery_ratio:
value_formula: (3.023 USD + 1.098 x price(HBAN, 2007-07-02)) / last_close - 1
event_type: acquisition
consideration: cash_and_stock
holder_value: 1.098 HBAN shares + $3.023 cash per Sky share
effective_date: 2007-07-02
successor_ticker: HBAN
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (25-NSE 0001354457-07-000195 "Acquired by Huntington"; 15-12B 0000950103-07-001706).
- successor: filing (DEFM14A: merger into Huntington).
- last trade date: worked out (close on the Sunday 2007-07-01 / Form 25 effective 2007-07-02; fails rows end 2007-07-03); no filing states it. An exchange print or a filing stating the last day would make it verified.
- payout rule: filing (DEFM14A).
- terms: filing (DEFM14A, 1.098 shares plus $3.023 cash); the closing 8-K was not read to confirm the final ratio.

## 5. What happened
- [SEC DEFM14A 2007-04-19](https://www.sec.gov/Archives/edgar/data/855876/000119312507085362/ddefm14a.htm): fixed exchange ratio 1.098 Huntington shares plus $3.023 cash per Sky share.
- [SEC 25-NSE 2007-07-02](https://www.sec.gov/Archives/edgar/data/855876/000135445707000195/xslF25X02/primary_doc.xml): Nasdaq removes Sky common, 12d2-2(a)(3), "Acquired by Huntington Bancshares Incorporated".
- [SEC 15-12B 2007-07-02](https://www.sec.gov/Archives/edgar/data/855876/000095010307001706/dp06172e_1512b.htm): deregistration.
- Fails rows (offline): CUSIP 83080P103 SKYF 2007-01-02..2007-07-03, last close 27.86; later SKYF rows (2008-03-12..2009-03-18) belong to CUSIP 83082Y102 SKY440 INC.

## 6. Decision-tree bucket
Replaced by cash and stock of another company: merger, not a continuation.

## 7. Why the library got it wrong
Row and exit kind are right. Terms: only the cash leg was read, and terms_gate_failed:no_acq_price dropped the stock leg (cause terms_not_extracted). The old ticker range came from 2008-2009 snapshot sightings of the reused ticker SKYF, which the delisting now clips (correct).

## 8. Fix and open checks
Publish the stock leg (1.098 HBAN, price date 2007-07-02) and USD currency. last_trade_date is unconfirmed: no filing states it. The 2008-2009 SKYF observations (observed_after_delisting) belong to SKY440 (CUSIP 83082Y102), not this FIGI. Golden-worthy: modestly.

## 9. Verification
Upheld. Re-opened through sec.py: the DEFM14A (0001193125-07-085362) states 1.098 Huntington shares plus $3.023 cash per Sky share, fixed ratio, which supports a cash_plus_stock merger row. The 25-NSE (0001354457-07-000195) covers Sky Financial common stock, effective 2007-07-02, "Acquired by Huntington Bancshares Incorporated", so the added merger row is right. The fails data show SKYF under CUSIP 83082Y102 (SKY440 INC) for 2008-03-12..2009-03-18, and Sky Financial's CUSIP 83080P103 ends 2007-07-03, so removing SKYF 2008-01-16..2009-06-08 from this security is right. Not refuted: nothing in the filings contradicts either verdict.

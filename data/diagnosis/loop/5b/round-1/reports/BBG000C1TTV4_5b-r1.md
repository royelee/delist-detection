# BBG000C1TTV4_5b-r1 (HET, Harrah's Entertainment) - regression

## 1. Verdict
Harrah's was acquired by Apollo/TPG (Hamlet Holdings) for $90.00 cash per share; the merger closed and the stock stopped trading at the close on 2008-01-28. The new run is right: it adds the merger ending and clips the ticker range at 2008-01-28. The base run had no ending and a range running to 2009-06-08, which was wrong.

## 2. Library vs evidence
| Field | Old (base) | New (run) | Evidence | Right |
| --- | --- | --- | --- | --- |
| delistings.added | no row | merger, last trade 2008-01-28, cash, continuation false | 8-K 0000898822-08-000159: Items 2.01, 3.01, 5.01; shares cancelled for $90.00, "cease to trade at the close of business on January 28, 2008" | new |
| security_history.ranges | HET:2007-12-26..2009-06-08 | HET:2007-12-26..2008-01-28 | same 8-K; Form 25-NSE 0000876661-08-000055 (NYSE, filed 2008-01-29), Form 15-12B 0001193125-08-013419 (2008-01-28) | new |
| exit_kind | none | merger | agrees with filing | agree |
| last_trade_date | none | 2008-01-28 | 8-K Item 3.01 | agree |
| value_rule / terms | none | cash 90.00 (USD) | 8-K Item 3.03: converted into $90.00 per share, no interest | agree (currency blank in library) |
| issuer | CIK 858339 | CIK 858339 | filings under 858339 | agree |
| ticker_history | to 2009-06-08 | to 2008-01-28 | the common stock was gone; the registrant kept filing only for its debt (8-K 2008-02-01) | new |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor: none
last_trade_date: 2008-01-28
value_rule: cash
cash_per_share: 90.00
cash_currency: USD
stock_ratio:
price_ticker:
price_sec_id:
price_date:
recovery_ratio:
value_formula: 90.00 / last_close - 1
event_type: cash merger (leveraged buyout)
consideration: $90.00 cash per share
holder_value: 90.00 USD
effective_date: 2008-01-28
successor_ticker:
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0000898822-08-000159 (Items 2.01, 3.01, 5.01).
- successor: filing, same 8-K; none, holders were cashed out.
- last trade date: filing, Item 3.01 requests delisting to cease trading at the close on 2008-01-28.
- payout rule: filing, Item 3.03.
- terms: filing, $90.00 per share without interest.

## 5. What happened
- Merger completed 2008-01-28 with Hamlet Merger Inc. [SEC 8-K 2008-02-01](https://www.sec.gov/Archives/edgar/data/858339/000089882208000159/newharrahs8k.htm)
- Each share converted into $90.00; delisted from NYSE, Chicago, Philadelphia at the close of business 2008-01-28 (same 8-K, Items 3.01 and 3.03).
- Form 15-12B filed 2008-01-28 [SEC](https://www.sec.gov/Archives/edgar/data/858339/000119312508013419/d1512b.htm); Form 25-NSE filed 2008-01-29 [SEC](https://www.sec.gov/Archives/edgar/data/858339/000087666108000055/xslF25X02/primary_doc.xml); a second 25-NSE 0000876882-08-000006 filed 2008-02-01.

## 6. Decision-tree bucket
Lost the old security, replaced by cash: terminal merger.

## 7. Why the library got it wrong
The base run found no ending and let the range run on from the post-LBO registrant's continued filings. Cause: other:base run missed the Form 25 for a registrant that kept filing; the sub-plan 5b Form 25 reach fixed it.

## 8. Fix and open checks
None for the new row; the currency should be USD. Flags `member_name_mismatch` and `last_trade_date_conflict` remain (halt-feed source on an NYSE stock; the date matches the filing). Golden-worthy: yes, well sourced.

## 9. Verification
Upheld. Re-read the cached 8-K 0000898822-08-000159 (Harrah's Entertainment, date of report 2008-01-28): the merger with Hamlet Merger Inc. completed that day, each common share was converted into $90.00 without interest, and the company asked NYSE, Chicago and Philadelphia to delist the Common Stock so it would cease to trade at the close of business on 2008-01-28. This supports both field verdicts: the added merger/cash ending with last trade 2008-01-28, and the HET range ending 2008-01-28. The security is the common stock, and the issuer CIK 858339 matches. No refuting evidence found.

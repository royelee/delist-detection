# BBG000BNY0W3_5b-r1 (MER, regression)

## 1. Verdict
Merrill Lynch common was converted 0.8595:1 into Bank of America common on 2009-01-01 and the NYSE suspended it on 2009-01-02; last trade 2008-12-31. The NEW run is right on both fields: the added merger row and the ticker range ending 2008-12-31. The old run had no ending and a range to 2009-06-08.

## 2. Library vs evidence (old = base run, new = this run)
| Field | old | new | evidence | status |
| --- | --- | --- | --- | --- |
| delistings.added | no row | merger, last trade 2008-12-31, value_rule stock | merger closed 2009-01-01; Form 25-NSE (NYSE, filed 2009-01-05) | new right |
| security_history.ranges | MER 2007-12-17..2009-06-08 | MER 2007-12-17..2008-12-31 | suspended 2009-01-02, Jan 1 holiday -> last session 2008-12-31 | new right |
| exit_kind / continuation / successor | n/a | merger / false / none | cash-free stock conversion into another company (BAC), not a 1:1 holdco | agree |
| value_rule / terms | n/a | stock, 0.8595, BAC, 2009-01-02 | 8-K Item 5.01: 0.8595 BAC share per MER share | agree |
| issuer | CIK 65100 | CIK 65100 | filer of all documents | agree |

## 3. Corrected classification
```
exit_kind: merger   drop_reason:   continuation: false   successor:
last_trade_date: 2008-12-31
value_rule: stock  cash_per_share:  cash_currency:  stock_ratio: 0.8595
price_ticker: BAC  price_sec_id: BBG000BCTLF6  price_date: 2009-01-02  recovery_ratio:
value_formula: 0.8595 x price(BAC, 2009-01-02) / last_close - 1
event_type: merger  consideration: stock  holder_value: 0.8595 BAC common per MER share
effective_date: 2009-01-01  successor_ticker:  confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0000950123-09-000005 (Items 3.01, 5.01).
- successor: filing, same 8-K (no continuation, acquirer BAC).
- last trade date: filing, Form 25-NSE 0000876661-09-000017 notice: suspended January 2, 2009 (Jan 1 a holiday) -> 2008-12-31.
- payout rule: filing, 8-K Item 5.01.
- terms: filing, 8-K Item 5.01 (0.8595).

## 5. What happened
- [SEC 8-K 2009-01-02](https://www.sec.gov/Archives/edgar/data/65100/000095012309000005/y73627e8vk.htm): merger with Bank of America effective 2009-01-01; each share converted into 0.8595 BAC share; NYSE and CHX asked to file Form 25.
- [SEC 25-NSE 2009-01-05](https://www.sec.gov/Archives/edgar/data/65100/000087666109000017/xslF25X02/primary_doc.xml): common stock suspended from trading January 2, 2009.
- [SEC 15-12B 2009-01-02](https://www.sec.gov/Archives/edgar/data/65100/000095012309000007/y73627ae15v12b.htm).

## 6. Decision-tree bucket
Replaced by stock of another company: merger.

## 7. Why the library got it wrong
The base run had no ending (range ran to 2009-06-08, probably the surviving registrant's later sightings); the sub-plan 5b Form 25 reach rules now find the Form 25 and the row. Not a library error now. Cause: library_right_but_uncertain (row flagged resolved_from_continued_filings; internal delist_date 2009-01-15 is later than the 2009-01-05 filing, harmless to the contract).

## 8. Fix and open checks
None needed. Good golden candidate (well sourced).

## 9. Verification
Upheld. Re-opened 8-K 0000950123-09-000005: Item 5.01 converts each MER share into 0.8595 BAC share; Item 3.01 says trading ceased before the open on 2009-01-02. Form 25-NSE 0000876661-09-000017 (NYSE, Rule 12d2-2(a)(3)): merger effective 12:01 a.m. 2009-01-01, 0.8595 BAC per share, suspended from trading 2009-01-02, removal at the open on 2009-01-15 (matches internal delist_date). Jan 1 is a holiday, so the last session is 2008-12-31. Both field verdicts (added merger row with last_trade_date 2008-12-31 and value_rule stock; range clipped to 2008-12-31) hold; no refutation found.

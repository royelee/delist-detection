# BBG000D3MB18_wave1-r1 (VMED, regression: price_sec_id)

## 1. Verdict
Virgin Media Inc. was acquired on 2013-06-07 by Liberty Global plc for $17.50 cash plus Class A and Class C ordinary shares. The new `price_sec_id` (BBG01K9HZH92, the LBTYA line) is right and the old blank was a missing term. The row still has a separate terms problem: the stock leg is published as 0.451 x LBTYA, but the filing gives 0.2582 Class A plus 0.1928 Class C (a different security with its own price).

## 2. Library vs evidence
| Field | Library says (old -> new) | Evidence says | Status |
| --- | --- | --- | --- |
| price_sec_id | blank -> BBG01K9HZH92 | The acquirer's Class A line, LBTYA (CUSIP 530555101 then G5480U104 in fails rows; ticker_history LBTYA from 2008). New is right | new right |
| exit_kind | merger | merger | agree |
| drop_reason / continuation / successor | blank / false / blank | cash+stock, holders get new shares of another issuer | agree |
| last_trade_date | 2013-06-07 (midas) | Mergers completed and Nasdaq notified 2013-06-07; Form 25-NSE/A filed 2013-06-07 | agree (inferred) |
| value_rule | cash_plus_stock | cash + stock | agree |
| terms | 17.50 + 0.451 x LBTYA @ 2013-06-10, currency blank | 17.50 USD + 0.2582 x LBTYA + 0.1928 x LBTYK (Class C) | wrong (Class C leg folded into Class A; ratio sum 0.451 equals 0.2582+0.1928) |
| issuer | CIK 1270400 | Virgin Media Inc. CIK 1270400 | agree |
| ticker_history | VMED 2007-12-17..2013-06-07 | consistent | agree |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor:
last_trade_date: 2013-06-07
value_rule: cash_plus_stock
cash_per_share: 17.50
cash_currency: USD
stock_ratio: 0.2582 (Class A, LBTYA) + 0.1928 (Class C, LBTYK)
price_ticker: LBTYA (and LBTYK for the Class C leg)
price_sec_id: BBG01K9HZH92 (LBTYA); Class C line not in run
price_date: 2013-06-10
recovery_ratio:
value_formula: (17.50 USD + 0.2582 x price(LBTYA, 2013-06-10) + 0.1928 x price(LBTYK, 2013-06-10)) / last_close - 1
event_type: acquisition
consideration: cash_and_stock
holder_value: 17.50 USD cash + 0.2582 Liberty Global plc Class A + 0.1928 Class C ordinary shares
effective_date: 2013-06-07
successor_ticker: LBTYA
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing, 8-K 0001193125-13-256243 items 2.01, 3.01, 5.01 (merger completed 2013-06-07).
- successor: n/a for a merger; acquirer named in the same 8-K.
- last trade date: MIDAS (an exchange print) plus the 8-K stating the 2013-06-07 completion and Nasdaq notice; no filing states "last day traded", so inferred.
- payout rule: filing, same 8-K.
- terms: filing for the three legs; the acquirer's LBTYA price_sec_id rests on fails rows (G5480U104 LBTYA rows 2013-06-12 on, name LIBERTY GLOBAL PLC SHS CL A) and the library's ticker_history.
To reach verified: an exchange print or filing stating the last day, and the Class C line's identity.

## 5. What happened
- Merger completed 2013-06-07; each Old VMI share became 0.2582 Class A + 0.1928 Class C + $17.50 [SEC 8-K 2013-06-12](https://www.sec.gov/Archives/edgar/data/1270400/000119312513256243/d552872d8k.htm).
- Nasdaq notified 2013-06-07 (same 8-K, Item 3.01).
- Form 25-NSE/A filed 2013-06-07 [SEC](https://www.sec.gov/Archives/edgar/data/1270400/000135445713000113/xslF25X02/primary_doc.xml).
- Form 15-12G filed 2013-06-19 (0001193125-13-264417).
- LBTYA (G5480U104, Liberty Global plc Class A) fails rows exist from 2013-06-12.

## 6. Decision-tree bucket
Replaced by cash and stock of another company: merger.

## 7. Why the library got it wrong
The regression field itself is not wrong: the new value fixes a missing price_sec_id. The remaining error is in `terms`: the LLM terms collapsed the two stock classes into one ratio of 0.451 priced on LBTYA. Cause: `terms_misread`.

## 8. Fix and open checks
- Publish both stock legs (Class A 0.2582, Class C 0.1928) or flag the Class C leg; cash currency USD.
- Check that BBG01K9HZH92 is the plc Class A composite across the re-domicile (cusip_history shows 530555101 then G61188101, both the LBTYA line).
- Golden candidate: yes, well sourced.

## 9. Verification
Upheld: price_sec_id new (BBG01K9HZH92) is right. I tried to refute it from the repo's tables and the report's cited 8-K (0001193125-13-256243). The securities table gives BBG01K9HZH92 as Liberty Global CLASS A common (CIK 1570585, the plc). ticker_history gives LBTYA from 2008-01-16, and cusip_history holds 530555101 then G61188101 on one composite, which matches the report. The merger gave $17.50 cash, 0.2582 Class A and 0.1928 Class C, so the Class A line is a correct price_sec_id for the stock leg, and a blank was a missing term. The contract row's 0.451 stock ratio is a separate terms_misread that the report flags and that is not part of this field's verdict. The Class C leg's composite is not in the run, so price_sec_id can name only the Class A leg.

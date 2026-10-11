# BBG000MMR2C9_5a-r2 (XCO, EXCO Resources common) - regression

## 1. Verdict
The base run held EXCO Resources common under the placeholder `CIK316300-COMMON`; this run holds it under the composite FIGI `BBG000MMR2C9` (figi_source=handoff). Both changed fields (`delistings.price_sec_id`, `id_changes.sec_id`) are one rename, and the new value is right: OpenFIGI's cached answer lists `BBG000MMR2C9` as the composite of EXCO RESOURCES INC common (ticker XCOOQ on other venues). The ending itself did not change.

## 2. Library vs evidence
| Field | Old (base) | New (this run) | Evidence | Status |
| --- | --- | --- | --- | --- |
| price_sec_id (delistings) | CIK316300-COMMON | BBG000MMR2C9 | OpenFIGI cache: composite BBG000MMR2C9, EXCO RESOURCES INC, Common Stock | new right |
| id_changes.sec_id | CIK316300-COMMON | renamed to BBG000MMR2C9 | securities.csv: BBG000MMR2C9, issuer 316300, COMMON | new right |
| exit_kind | dropped | dropped | NYSE removal under 802.01B (market cap); Chapter 11 on 2018-01-15 | agree |
| last_trade_date | 2017-12-22 | 2017-12-22 | Form 25-NSE notice and 8-K 3.01: suspended Dec 22, 2017 | agree |
| value_rule | otc_print | otc_print | first OTC print from 2017-12-26 (price not looked up) | agree |
| issuer | 316300 | 316300 | Form 25-NSE filer CIK 316300 | agree |
| ticker_history | XCO NYSE 2007-12-20..2017-12-22 | same under the new id | output/ticker_history.csv | agree |

## 3. Corrected classification
```
sec_id: BBG000MMR2C9
exit_kind: dropped   drop_reason: bankruptcy (capital is arguable, see 7)   continuation: false   successor: none
last_trade_date: 2017-12-22
value_rule: otc_print   cash_per_share: -   cash_currency: -   stock_ratio: -
price_ticker: XCO   price_sec_id: BBG000MMR2C9   price_date: 2017-12-26   recovery_ratio: -
value_formula: otc_print(XCO, from 2017-12-26) / last_close - 1
event_type: exchange_delisting then bankruptcy   consideration: none   holder_value: first OTC print
effective_date: 2018-01-22 (NYSE removal)   successor_ticker: none   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing - 8-K 0001193125-17-379926 (Item 3.01), Form 25-NSE 0000876661-18-000029, 8-K 0001193125-18-011684 (Item 1.03).
- successor: filing - none in these filings.
- last trade date: filing - the Form 25 notice says the NYSE suspended trading on Dec 22, 2017.
- payout rule: worked out - otc_print follows the dropped/bankruptcy row of the decision table; no filing states a price.
- terms: none needed for otc_print.
- The new sec_id rests on the OpenFIGI cache (cache/openfigi), not an SEC filing. `verified` would need a re-fetched OpenFIGI answer for CUSIP 269279501 and an exchange print for the last day.

## 5. What happened
- 2017-12-22: NYSE suspended the stock, market cap under $15M (802.01B) - [SEC 8-K 2017-12-27](https://www.sec.gov/Archives/edgar/data/316300/000119312517379926/d483766d8k.htm).
- 2018-01-10: NYSE filed Form 25-NSE, removal effective 2018-01-22 - [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/316300/000087666118000029/xslF25X02/primary_doc.xml).
- 2018-01-15: EXCO and subsidiaries filed Chapter 11 - [SEC 8-K 2018-01-17](https://www.sec.gov/Archives/edgar/data/316300/000119312518011684/d644828d8k.htm).
- OpenFIGI cache lists composite BBG000MMR2C9 for EXCO RESOURCES INC common (ticker XCOOQ on UA/UI venues).

## 6. Decision-tree bucket
Lost: delisted for a deficiency, then bankruptcy, then OTC. Not a continuation.

## 7. Why the library got it wrong
It did not: the base run's placeholder was the weaker answer; this run resolved the FIGI through the handoff route. Cause tag: `library_right_but_uncertain`. Side note outside the changed fields: the NYSE removal came from a market-cap deficiency three weeks before the petition, so drop_reason `capital` (560) is arguable against the library's bankruptcy (470) from the 1.03 item. Exit kind and value rule are the same either way.

## 8. Fix and open checks
No fix for the changed fields. Open: capital vs bankruptcy as drop reason (a rule question, not part of this regression); the first OTC print is qlib_practice's. Not golden-worthy.

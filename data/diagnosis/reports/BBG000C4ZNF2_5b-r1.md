# BBG000C4ZNF2_5b-r1 (ABK, Ambac Financial Group) - regression diagnosis

## 1. Verdict
Ambac filed Chapter 11 on 2010-11-08 and NYSE suspended trading in its common stock on 2010-11-09 and removed it by Form 25-NSE (effective 2010-12-27). The new run is right: it adds the bankruptcy ending (dropped / bankruptcy, last trade 2010-11-08, OTC-print value) and ends the ABK listing there. The old run had no ending and carried the OTC symbol ABKFQ to 2013 as if it were still the listing.

## 2. Library vs evidence
| field | old (base) | new (library) | evidence says | status |
| --- | --- | --- | --- | --- |
| delistings row | none | present | Form 25-NSE 0000876661-10-000471 | new right |
| exit_kind | none | dropped | bankruptcy, NYSE suspension, Form 25 | agree (new) |
| drop_reason | none | bankruptcy | 8-K item 1.03 | agree |
| continuation | none | false | no successor line; ending is loss of listing | agree |
| successor | none | blank | none in any filing | agree |
| last_trade_date | n/a | 2010-11-08 | NYSE suspended immediately on 2010-11-09; Form 25 effective 2010-12-27 | agree |
| value_rule | none | otc_print | decision 11 | agree |
| terms | none | otc_print(ABK, from 2010-11-09) | own OTC symbol is ABKFQ (fails rows from 2010-11-16); price date 2010-11-09 right | agree (symbol detail open) |
| issuer | CIK 874501 | CIK 874501 | Ambac Financial Group | agree |
| ticker_history | ABK 2007-12-17..2010-11-15; ABKFQ 2010-11-16..2013-05-07 | ABK 2007-12-17..2010-11-08 | ticker_history records exchange listings; ABKFQ is OTC trading of the same CUSIP 023139108 after the delisting | agree (new) |

## 3. Corrected classification
```
exit_kind: dropped
drop_reason: bankruptcy
continuation: false
successor: (none)
last_trade_date: 2010-11-08
value_rule: otc_print
cash_per_share: -
cash_currency: -
stock_ratio: -
price_ticker: ABKFQ (own OTC symbol)
price_sec_id: BBG000C4ZNF2
price_date: 2010-11-09
recovery_ratio: -
value_formula: otc_print(ABKFQ, from 2010-11-09) / last_close - 1
event_type: bankruptcy
consideration: none
holder_value: shares stay outstanding, trade OTC
effective_date: 2010-12-27
successor_ticker: (none)
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-10-256201 (items 1.03, 3.01) and Form 25-NSE 0000876661-10-000471.
- successor: filing, none named in the Form 25, the 8-K or later 8-Ks.
- last trade date: filing, 8-K item 3.01 and the Form 25 notice put the immediate suspension on 2010-11-09, so the last trade is 2010-11-08.
- payout rule: filing, bankruptcy delisting with OTC trading after (decision 11).
- terms: the rule needs no filing terms; the OTC print itself is qlib_practice's.

## 5. What happened
- 2010-11-08 Ambac announced a Chapter 11 filing; NYSE determined the same day to suspend ([SEC Form 25-NSE](https://www.sec.gov/Archives/edgar/data/874501/000087666110000471/xslF25X02/primary_doc.xml)).
- 2010-11-09 NYSE Regulation announced immediate suspension of trading under LCM 802.01D ([SEC 8-K 2010-11-10](https://www.sec.gov/Archives/edgar/data/874501/000119312510256201/d8k.htm), items 1.03, 2.04, 3.01, 8.01).
- 2010-12-17 Form 25-NSE filed; removal effective at the open 2010-12-27 (Form 25 link above); the stock had also fallen below the $1 average-price standard.
- Fails rows: CUSIP 023139108 under ABK to 2010-11-15, under ABKFQ from 2010-11-16 to 2013-05-07 (fails data).

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC. The same CUSIP trades OTC, which is not an exchange listing.

## 7. Why the library got it wrong
The base run was wrong (no ending, ABKFQ range kept); the new run's Form 25 reach rules found the 25-NSE. Cause: late_form25 (fixed in this run). The new run is not wrong.

## 8. Fix and open checks
No fix. Open: the symbol of the first OTC prints 2010-11-09 to 2010-11-15 (fails data shows ABK until 2010-11-15; the Q suffix appears from 2010-11-16); the published price_ticker is ABK. Good golden candidate.

## 9. Verification
Upheld, both field verdicts. Re-opened through sec.py: the Form 25-NSE 0000876661-10-000471 (filed 2010-12-17, class Common Stock, removal at the open 2010-12-27, NYSE determined 2010-11-08 to suspend immediately after the Chapter 11 announcement) and 8-K 0001193125-10-256201 (items 1.03, 3.01; NYSE suspended the common stock, ticker ABK, on 2010-11-09). Three sibling 25-NSEs filed the same day cover other securities. The fails rows show CUSIP 023139108 under ABK to 2010-11-15 and under ABKFQ from 2010-11-16, so the ABKFQ range is OTC trading after the delisting and the clipped ABK range ending 2010-11-08 is right. A bankruptcy drop valued by otc_print is the reference's decision 11. Minor: the filings do not exclude a last trade of 2010-11-09 (the suspension day), but 2010-11-08 matches the library's halt source; this does not change the verdict.

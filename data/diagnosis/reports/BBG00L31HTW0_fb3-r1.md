# BBG00L31HTW0_fb3-r1 (RVI, Retail Value Inc.) - regression

## 1. Verdict
Retail Value Inc. voluntarily delisted its common shares from the NYSE (Form 25 under Rule 12d2-2(c), filed 2022-03-28, effective before the open of 2022-04-07) and kept trading over the counter as RVIC on the same CUSIP. The new run is right on both fields: it adds the ending (dropped / moved_otc, last trade 2022-04-06, otc_print) and clips the exchange ticker range at 2022-04-06. The old run had no ending and carried RVI/RVIC as one listing to 2023-04-06.

## 2. Library vs evidence
| Field | Old (base) | New (library) | Evidence | Status |
| --- | --- | --- | --- | --- |
| delistings row | none | present | Form 25 0001193125-22-085937 and 8-K 3.01 0001564590-22-010694 | new right |
| exit_kind / drop_reason | blank | dropped / moved_otc | Voluntary NYSE delisting; shares quoted OTC as RVIC (fails rows); registrant kept filing (10-K filed 2023-02-24) | agree (new) |
| continuation / successor | - | false / none | same CUSIP, no exchange of shares, no successor | agree |
| last_trade_date | - | 2022-04-06 | 8-K: delisting effective prior to commencement of trading on 2022-04-07, so last trade 2022-04-06; fails rows: RVI symbol to 20220408 (settling), RVIC from 20220411 | agree |
| value_rule | - | otc_print (RVIC, from 2022-04-07) | first OTC symbol RVIC, fails rows from 2022-04-11 | agree |
| terms | - | no cash / ratio | none needed | agree |
| issuer | CIK 1735184 | CIK 1735184 | Form 25 filer | agree |
| ticker_history | RVI to 2022-04-10; RVIC 2022-04-11..2023-04-06 | RVI 2018-06-30..2022-04-06 | the exchange listing ended 2022-04-06; OTC trading is not the listing (clip rule) | new right |

## 3. Corrected classification
```
exit_kind: dropped
drop_reason: moved_otc
continuation: false
successor: none
last_trade_date: 2022-04-06
value_rule: otc_print
cash_per_share: null
cash_currency: ""
stock_ratio: null
price_ticker: RVIC
price_sec_id: BBG00L31HTW0
price_date: 2022-04-07
recovery_ratio: null
value_formula: otc_print(RVIC, from 2022-04-07) / last_close - 1
event_type: exchange_delisting (voluntary, moved to OTC)
consideration: none
holder_value: same shares, quoted OTC as RVIC
effective_date: 2022-04-07
successor_ticker: ""
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing - 8-K 3.01 (0001564590-22-010694) and Form 25 (0001193125-22-085937, Rule 12d2-2(c)); that the shares stayed quoted rests on fails rows (RVIC).
- successor: filing - none exists; the same CUSIP continues.
- last trade date: worked out from the 8-K ("effective prior to the commencement of trading on April 7, 2022", so April 6); no EX-99.25 print or MIDAS read.
- payout rule: fails rows (RVIC on the same CUSIP from 2022-04-11) and decision 11.
- terms: none needed.
Not backed by a filing: the OTC symbol (fails rows only). A filing or web page stating the OTC quotation of RVIC would make it verified.

## 5. What happened
- 2022-03-17: [SEC 8-K 3.01](https://www.sec.gov/Archives/edgar/data/1735184/000156459022010694/rvi-8k_20220316.htm) - notice to NYSE of voluntary de-listing; Form 25 to be filed 2022-03-28; effective prior to trading on 2022-04-07.
- 2022-03-28: [SEC Form 25](https://www.sec.gov/Archives/edgar/data/1735184/000119312522085937/d321246d25.htm) - issuer filing, Rule 12d2-2(c).
- 2022-04-14: [SEC 8-K 2.01](https://www.sec.gov/Archives/edgar/data/1735184/000156459022014461/rvi-8k_20220412.htm) - asset sale closing; the company keeps filing (10-Qs, [10-K 2023-02-24](https://www.sec.gov/Archives/edgar/data/1735184/000095017023004385/rvic-20221231.htm)).
- Fails rows for CUSIP 76133Q102: RVI 20220301..20220408 (17 rows), RVIC 20220411..20230406 (70 rows).

## 6. Decision-tree bucket
Lost: delisted by choice and moved to OTC. The holder keeps the same CUSIP but no longer holds an exchange-listed security; decision 11 makes it an ending valued at the first OTC print.

## 7. Why the library got it wrong
The base run did not find the ending (no row; the ranges ran on as RVIC to 2023). The new run finds the Form 25 and the OTC move (`Rule.MOVED_OTC`). The old run is wrong, the new right. Cause: other:base_missed_voluntary_otc_delisting.

## 8. Fix and open checks
Nothing to fix in the new run. Open: a source naming the OTC venue for RVIC. A good golden case for the moved_otc rule.

## 9. Verification
Skeptic pass, re-opened through sec.py. Both verdicts survive.
- Form 25 0001193125-22-085937 (filed 2022-03-28): issuer filing, 12d2-2(c) box checked, common shares, NYSE. A voluntary removal of this class.
- 8-K 0001564590-22-010694 (3.01): the delisting is expected effective prior to the commencement of trading on April 7, 2022, so the last NYSE trade is 2022-04-06. Matches the new run's last_trade_date.
- Fails rows for 76133Q102: RVI 20220301..20220408 (settling), RVIC from 20220411, same CUSIP. Supports moved_otc / otc_print and the clipped RVI range; the OTC symbol rests on fails rows only (already noted).
- No successor or exchange of shares in the filing list for 2022-03..05 (only PRE 14A, DEF 14A, the 3.01 8-K, the asset-sale 2.01 8-K). Not a continuation.
- delistings.added: upheld (new right). security_history.ranges: upheld (new right).

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (Retail Value Inc's 2022 voluntary NYSE delisting, OTC as RVIC).

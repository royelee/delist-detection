# BBG000MMR2C9_5a-r1 (XCO, EXCO Resources common): regression, mode regression

## 1. Verdict
The ending (NYSE removal of EXCO common, last trade 2017-12-22) is unchanged. What changed is only the key: the placeholder `CIK316300-COMMON` became the confirmed FIGI `BBG000MMR2C9`, and the `otc_print` rule's `price_sec_id` (the security itself) followed it. The new value is right; the old one was a placeholder for a security that now has a FIGI.

## 2. Library vs evidence
| Field | old (base run, side_a) | new (side_b) | evidence | status |
| --- | --- | --- | --- | --- |
| `delistings.price_sec_id` | CIK316300-COMMON | BBG000MMR2C9 | otc_print prices the security itself; its sec_id in the run is BBG000MMR2C9 (securities.csv, ticker_history.csv: XCO NYSE 2007-12-20 to 2017-12-22; CUSIPs 269279402, 269279501) | new right |
| `id_changes.sec_id` | CIK316300-COMMON | BBG000MMR2C9 | securities.csv lists BBG000MMR2C9 for CIK 316300 (EXCO RESOURCES INC, common); the base run's securities.csv held only the placeholder for CIK 316300 | new right |
| exit_kind / drop_reason | dropped / bankruptcy | same | see below | agree (see open check) |
| continuation, successor | false, none | same | no successor filing in 2017-12 to 2018-03 | agree |
| last_trade_date | 2017-12-22 | same | NYSE notice: determined 2017-12-22 to suspend trading | agree |
| value_rule / terms | otc_print, XCO from 2017-12-26 | same | decision 11 | agree |
| issuer | 316300 | 316300 | EDGAR CIK of EXCO Resources | agree |
| ticker_history | XCO NYSE 2007-12-20 to 2017-12-22 | same | Form 25-NSE | agree |

## 3. Corrected classification
```
sec_id: BBG000MMR2C9
exit_kind: dropped
drop_reason: bankruptcy   (NYSE removal reason was a market-cap deficiency; Chapter 11 followed 2018-01-15)
continuation: false
successor: none
last_trade_date: 2017-12-22
value_rule: otc_print
cash_per_share: -
cash_currency: -
stock_ratio: -
price_ticker: XCO
price_sec_id: BBG000MMR2C9
price_date: 2017-12-26 (session after the last exchange trade)
recovery_ratio: -
value_formula: otc_print(XCO, from 2017-12-26) / last_close - 1
event_type: bankruptcy / exchange_delisting
consideration: none
holder_value: first OTC print
effective_date: 2018-01-10 (Form 25-NSE; NYSE removal date 2018-01-22 per notice)
successor_ticker: none
confidence: verified for the changed fields
```

## 4. Why this confidence
Confidence: verified (for the two changed fields).
- exit kind: filing, Form 25-NSE 0000876661-18-000029 and 8-K 0001193125-18-011684 (item 1.03).
- successor: filing, none in the 8-K list 2017-12 to 2018-03.
- last trade date: filing, the 25-NSE notice and 8-K 0001193125-17-379926 (suspended 2017-12-22).
- payout rule: decision 11 (OTC print); no price looked up.
- terms: none to give; price_sec_id is the security's own sec_id.

## 5. What happened
- [SEC 8-K 2017-12-27](https://www.sec.gov/Archives/edgar/data/316300/000119312517379926/d483766d8k.htm): NYSE notice of 2017-12-22, delisting for average market cap below $15 million (802.01B); trading suspended.
- [SEC 25-NSE 2018-01-10](https://www.sec.gov/Archives/edgar/data/316300/000087666118000029/xslF25X02/primary_doc.xml): NYSE removes common stock on 2018-01-22 under Rule 12d2-2(b).
- [SEC 8-K 2018-01-17](https://www.sec.gov/Archives/edgar/data/316300/000119312518011684/d644828d8k.htm): items 1.03, 2.04 (Chapter 11).

## 6. Decision-tree bucket
Lost: delisted, then OTC, with a bankruptcy days later. The same shares kept existing; no replacement.

## 7. Why the library got it wrong
It did not. Cause: library_right_but_uncertain not applicable; the change is an improvement (placeholder to FIGI, `other:placeholder_to_figi_rename`).

## 8. Fix and open checks
- No fix. The `id_changes` row correctly records the rename; the base-run ledger should mark it explained.
- Open: the NYSE's stated reason is a market-cap deficiency (CRSP 570-style), not the bankruptcy, which was filed after the suspension; `drop_reason` could be `guidelines`. Unchanged between old and new, so outside this regression.
- Golden worthy: no.

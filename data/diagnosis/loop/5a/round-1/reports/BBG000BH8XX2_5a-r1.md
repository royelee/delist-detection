# BBG000BH8XX2_5a-r1 (CIE, Cobalt International Energy) - regression

## 1. Verdict
Cobalt's common stock was suspended by the NYSE at the close on 2017-12-13 (market-cap deficiency, Rule 12d2-2(b)) after the 2017-12-14 bankruptcy 8-K; the ending is a bankruptcy drop valued at the OTC print. The run's change is only an identity upgrade: the placeholder CIK1471261-COMMON is now the composite FIGI BBG000BH8XX2. The new value is right; no contract field changed except the id.

## 2. Library vs evidence
| field | old (base 794ef8d) | new | evidence | status |
| --- | --- | --- | --- | --- |
| delistings.price_sec_id | CIK1471261-COMMON | BBG000BH8XX2 | OpenFIGI cache: BBG000BH8XX2 is the composite FIGI of "COBALT INTERNATIONAL ENERGY" common stock (share class BBG001SKC776, later CIEIQ); the otc_print rule prices the security itself, so price_sec_id is its own sec_id | new right |
| id_changes.sec_id | CIK1471261-COMMON | BBG000BH8XX2 (2026-09-25) | same FIGI; the placeholder had no FIGI; CUSIPs 19075F106 / 19075F304 (FTD) are Cobalt's | new right |
| exit_kind / drop_reason | dropped / bankruptcy | same | 8-K items 1.03, 3.01 filed 2017-12-14 | agree |
| continuation / successor | false / none | same | none in filings 2017-12 to 2018-02 | agree |
| last_trade_date | 2017-12-13 | same | 25-NSE notice: "Trading in the Common Stock was suspended at the close of the market on December 13, 2017" | agree |
| value_rule / terms | otc_print, price CIE from 2017-12-14 | same | decision 11 | agree |
| issuer | 1471261 | 1471261 | Cobalt CIK | agree |
| ticker_history | CIE NYSE 2009-12-23..2017-12-13 | same | | agree |

## 3. Corrected classification
```
sec_id: BBG000BH8XX2
exit_kind: dropped
drop_reason: bankruptcy
continuation: false
successor: none
last_trade_date: 2017-12-13
value_rule: otc_print
cash_per_share: -
cash_currency: -
stock_ratio: -
price_ticker: CIE (post-drop OTC symbol CIEIQ per OpenFIGI)
price_sec_id: BBG000BH8XX2
price_date: 2017-12-14
recovery_ratio: -
value_formula: otc_print(CIE, from 2017-12-14) / last_close - 1
event_type: bankruptcy
consideration: none
holder_value: first OTC print
effective_date: 2018-01-12 (Form 25 effective; notice says delisted from opening of business 2018-01-16)
successor_ticker: -
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-17-368742 (items 1.03, 3.01) and 25-NSE 0000876661-18-000002.
- successor: filing, none in the issuer's filings 2017-12 to 2018-02.
- last trade date: filing, the 25-NSE notice states suspension at the close on 2017-12-13.
- payout rule: filing, Chapter 11 plus exchange suspension, decision 11.
- terms: none needed (no market price).

## 5. What happened
- 2017-12-14 8-K items 1.03, 2.04, 3.01 ([SEC 8-K](https://www.sec.gov/Archives/edgar/data/1471261/000119312517368742/d506127d8k.htm)).
- 2018-01-02 NYSE 25-NSE: market cap below $15M, suspended at the close 2017-12-13 ([SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/1471261/000087666118000002/xslF25X02/primary_doc.xml)).
- OpenFIGI cache (cache/openfigi) lists BBG000BH8XX2 as Cobalt International Energy common, ticker CIEIQ.

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC.

## 7. Why the library changed
A FIGI is now confirmed for the era (figi_source=handoff), so the placeholder was renamed and price_sec_id follows sec_id. Cause: other:placeholder_upgraded_to_figi (intended change; library right).

## 8. Fix and open checks
Nothing to fix. Open: published price_ticker is CIE while the post-drop symbol was CIEIQ (qlib_practice should key on sec_id). Not golden-worthy.

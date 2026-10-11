# BBG000BHNPN3_fb3-r1 (CHSI, Catalyst Health Solutions) - regression, field price_sec_id

## 1. Verdict
Catalyst Health was acquired by SXC Health Solutions Corp. (renamed Catamaran) on 2012-07-02 for $28.00 cash plus 0.6606 SXC share. The stock leg's price security is SXC's line, FIGI BBG000KBQZ88 (CIK 1363851, SXCI then CTRX). The new run's price_sec_id is right; the old run's placeholder CIK1363851-COMMON was the same line before stage 4b folded it into the FIGI.

## 2. Library vs evidence
| field | library says (new) | evidence says | status |
| --- | --- | --- | --- |
| exit_kind | merger | merger, 8-K 2.01 | agree |
| drop_reason / continuation / successor | blank / false / none | cash+stock merger, no successor | agree |
| last_trade_date | 2012-07-02 | merger effective 4:01 p.m. ET 2012-07-02 | agree |
| value_rule | cash_plus_stock | cash and stock | agree |
| terms | 28.00 USD + 0.6606 x SXCI on 2012-07-03 | $28.00 cash + 0.6606 SXC common | agree |
| price_sec_id | old CIK1363851-COMMON, new BBG000KBQZ88 | SXC Health Solutions Corp CIK 1363851 = Catamaran, FIGI BBG000KBQZ88 (output/securities.csv; SXCI to 2012-07-10, CTRX after) | new right (old is the same line before the fold) |
| issuer | 1090403 | Catalyst Health Solutions | agree |
| ticker_history | CHSI to 2012-07-02 | same | agree |

## 3. Corrected classification
```
exit_kind: merger   drop_reason:    continuation: false   successor:
last_trade_date: 2012-07-02
value_rule: cash_plus_stock  cash_per_share: 28.00  cash_currency: USD  stock_ratio: 0.6606
price_ticker: SXCI  price_sec_id: BBG000KBQZ88  price_date: 2012-07-03  recovery_ratio:
value_formula: (28.00 + 0.6606 x price(SXCI, 2012-07-03)) / last_close - 1
event_type: acquisition  consideration: cash_and_stock  holder_value: 28.00 USD + 0.6606 SXC shares
effective_date: 2012-07-02  successor_ticker:  confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-12-296108 item 2.01 (merger effective 4:01 p.m. 2012-07-02), Form 25-NSE 0001354457-12-000144.
- successor: filing, none (cash+stock merger into a subsidiary).
- last trade date: filing, effective time after the 4 p.m. close on 2012-07-02.
- payout rule: filing, same 8-K.
- terms: filing, same 8-K ($28.00 cash + 0.6606 SXC share); the price security SXC is named there.

## 5. What happened
- [SEC 8-K 2012-07-06](https://www.sec.gov/Archives/edgar/data/1090403/000119312512296108/d375233d8k.htm): each Catalyst share converted into $28.00 cash and 0.6606 SXC common share, effective 4:01 p.m. ET 2012-07-02.
- [SEC 25-NSE 2012-07-02](https://www.sec.gov/Archives/edgar/data/1090403/000135445712000144/xslF25X02/primary_doc.xml) and Form 15-12B 2012-07-12.
- SXC (CIK 1363851) took the name Catamaran; output/securities.csv holds it as BBG000KBQZ88, SXCI until 2012-07-10, then CTRX.

## 6. Decision-tree bucket
Replaced by cash and another company's stock: merger.

## 7. Why the library differed
Not an error: the base run held SXC's line as the placeholder CIK1363851-COMMON, and stage 4b (line follow) folded it into FIGI BBG000KBQZ88 (a contract/id_changes.csv rename). Cause: other:placeholder_folded_to_figi.

## 8. Fix and open checks
None. The regression guard should treat this price_sec_id change as a rename; no golden needed.

## 9. Verification
Upheld. Re-read 8-K 0001193125-12-296108 (cache/edgar/text): item 2.01, effective 4:01 p.m. ET 2012-07-02, each Catalyst common share became $28.00 cash plus 0.6606 of an SXC Health Solutions Corp. common share; the stock leg is SXC's common stock. output/securities.csv holds CIK 1363851 as BBG000KBQZ88 (Catamaran Corp, common), and output/contract/id_changes.csv records the rename CIK1363851-COMMON -> BBG000KBQZ88 (kind rename). The committed (base) contract row shows the placeholder, the new run shows the FIGI; price_ticker SXCI, price_date 2012-07-03 and the terms are unchanged. The change is a rename of the same line, so the new price_sec_id is right. No missed filing needed.

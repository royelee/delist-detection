# BBG000BH13K9_fb3b-r1 (DD, E I du Pont de Nemours) - regression

## 1. Verdict
DuPont merged with Dow on 2017-08-31; each DD share became 1.2820 DowDuPont (DWDP) shares, and NYSE suspended DD on 2017-09-01. The new run's merger row (last trade 2017-08-31, stock) and its ticker range ending 2017-08-31 are right; the base run had no ending and an open-ended range to 2017-09-05.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
| --- | --- | --- | --- | --- |
| delistings row | none | merger, last trade 2017-08-31, value_rule stock | [SEC 25-NSE 2017-09-01, 0000876661-17-000494](https://www.sec.gov/Archives/edgar/data/30554/000087666117000494/xslF25X02/primary_doc.xml): merger effective 2017-08-31, 1.2820 DWDP per DD share | new right |
| exit_kind / continuation | - | merger / false | not 1:1 (1.2820 ratio) so not a holdco continuation; 8-K 2.01/5.01 [0001193125-17-274840](https://www.sec.gov/Archives/edgar/data/30554/000119312517274840/d438565d8k.htm) | agree (new) |
| last_trade_date | - | 2017-08-31 | notice: suspended from trading on September 1, 2017, so the trading day before is 2017-08-31 | agree (new) |
| value_rule / terms | - | stock, 1.282 x DWDP, price date 2017-09-01 | notice: 1.2820 shares of (NEW) DowDuPont | agree (new) |
| ticker_history range | DD:2007-12-18..2017-09-05 | DD:2007-12-18..2017-08-31 (issuer 30554) | listing ended with suspension on 2017-09-01 | new right |

## 3. Corrected classification
```
exit_kind=merger drop_reason= continuation=false successor= last_trade_date=2017-08-31
value_rule=stock cash_per_share= cash_currency= stock_ratio=1.282 price_ticker=DWDP price_sec_id=BBG00BN961G4 price_date=2017-09-01 recovery_ratio=
value_formula=1.282 x price(DWDP, 2017-09-01) / last_close - 1
event_type=merger consideration=stock holder_value="1.2820 DowDuPont shares" effective_date=2017-08-31 successor_ticker=DWDP confidence=verified
```

## 4. Why this confidence
verified.
- exit kind: filing, Form 25-NSE 0000876661-17-000494 (merger effective 2017-08-31).
- successor: filing, same notice (DWDP is the acquirer, not a continuation).
- last trade date: filing, same notice (suspended Sept 1, 2017, so the trading day before).
- payout rule: filing, same notice (shares substituted).
- terms: filing, same notice (1.2820).

## 5. What happened
- Merger between DuPont and Dow effective 2017-08-31, 1.2820 DWDP per DuPont share ([SEC 25-NSE 2017-09-01](https://www.sec.gov/Archives/edgar/data/30554/000087666117000494/xslF25X02/primary_doc.xml)).
- DD suspended from trading 2017-09-01 (same notice); DuPont 8-K items 2.01, 3.01, 3.03, 5.01 filed 2017-09-01 (0001193125-17-274840).

## 6. Decision-tree bucket
Replaced by stock of another company (merger), not kept.

## 7. Why the library got it wrong
The base run had no ending for this security (history ran to the last sighting); the new run finds the Form 25 and values it. Cause: other:base run missed the Form 25 ending.

## 8. Fix and open checks
None for the new row. Good golden candidate.

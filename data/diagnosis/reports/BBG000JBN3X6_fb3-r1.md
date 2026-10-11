# BBG000JBN3X6_fb3-r1 (LCC, US Airways Group) - regression

## 1. Verdict
US Airways Group merged with AMR Merger Sub on 2013-12-09; each LCC share became one share of the reorganized AMR, American Airlines Group (AAL). The NEW row (merger, stock, last trade 2013-12-06, issuer 701345) is right; the old run had no contract ending and a blank issuer.

## 2. Library vs evidence
| field | old (base) | new (library) | evidence | status |
| --- | --- | --- | --- | --- |
| delistings.added | no contract row | merger row | the NYSE listing ended in the merger (Form 25-NSE 0000876661-13-000861; 8-K 0001193125-13-465950 Items 2.01, 3.01) | new right |
| exit_kind | none | merger | merger, holders received another issuer's stock | agree (new) |
| continuation | - | false | AAL is the reorganized AMR, a different issuer with other holders: not a 1:1 holding-company reorganization | agree (new) |
| last_trade_date | - | 2013-12-06 | NYSE suspension "prior to the opening of the market on December 9, 2013" -> Friday 2013-12-06; MIDAS agrees | agree (new) |
| value_rule / terms | - | stock, ratio 1.0, AAL, price date 2013-12-09 | "converted into the right to receive one share of common stock ... of the Company" (8-K 2013-12-09) | agree (new) |
| issuer | blank | 701345 | US Airways Group Inc, CIK 701345 | new right |
| security_history.ranges | LCC:2007-12-17..2013-12-06: (issuer blank) | same range, issuer 701345 | same | new right |

## 3. Corrected classification
```
exit_kind=merger drop_reason= continuation=false successor=
last_trade_date=2013-12-06
value_rule=stock cash_per_share= cash_currency= stock_ratio=1.0 price_ticker=AAL price_sec_id=BBG005P7Q881 price_date=2013-12-09
recovery_ratio= value_formula=1 x price(AAL, 2013-12-09) / last_close - 1
event_type=merger consideration=stock holder_value=1 AAL share effective_date=2013-12-09 successor_ticker=AAL confidence=verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-13-465950 (Item 2.01 merger consummated 2013-12-09) and 25-NSE 0000876661-13-000861.
- successor: filing, same 8-K (AAL, CUSIP 02376R102, listed on Nasdaq on the Effective Date); no continuation.
- last trade date: filing, the 8-K's Item 3.01 (NYSE suspended before the open on 2013-12-09 -> 2013-12-06).
- payout rule: filing, same 8-K (stock for stock).
- terms: filing, same 8-K (one share of AAL per share).

## 5. What happened
- [SEC 8-K 2013-12-09](https://www.sec.gov/Archives/edgar/data/701345/000119312513465950/d640604d8k.htm): Merger Sub merged into US Airways Group, which survives as a subsidiary of AMR; each US Airways share converted into one share of AMR common stock; AAL began on Nasdaq.
- Same 8-K, Item 3.01: US Airways requested NYSE suspension before the open on 2013-12-09 and a Form 25.
- [SEC 25-NSE 2013-12-09](https://www.sec.gov/Archives/edgar/data/701345/000087666113000861/xslF25X02/primary_doc.xml), effective 2013-12-09.

## 6. Decision-tree bucket
Replaced: holders of the old security received another issuer's stock (merger, not a same-claim continuation).

## 7. Why the library got it wrong
It did not for the new run. The old run missed this ending (no row, blank issuer); the new run found the Form 25 and matched it. Cause tag: other:old run missed the 25-NSE; fixed.

## 8. Fix and open checks
None needed. Golden-worthy: yes (well sourced, all five fields from one 8-K).

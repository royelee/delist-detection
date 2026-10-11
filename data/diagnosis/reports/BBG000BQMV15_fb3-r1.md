# BBG000BQMV15_fb3-r1 (OSG, Overseas Shipholding Group) - regression

## 1. Verdict
OSG filed Chapter 11 on 2012-11-14 and NYSE suspended trading at once; the old shares then traded OTC as OSGIQ until they were cancelled on emergence (2014-08-05). The new run's row (dropped / bankruptcy, last trade 2012-11-13, otc_print OSGIQ) is right; the base run had no ending at all and kept the listing range open through the OTC tail to 2014-05-27, which was wrong. New is right on both fields.

## 2. Library vs evidence
| field | old (base run) | new (this run) | evidence | right |
| --- | --- | --- | --- | --- |
| delistings.added | no contract row | dropped/bankruptcy, continuation false, last trade 2012-11-13, otc_print | 8-K 1.03/3.01 filed 2012-11-15; 25-NSE 2012-12-20 | new |
| security_history.ranges | OSG 2007-12-20..2012-11-20; OSGIQ 2012-11-21..2014-05-27 | OSG 2007-12-20..2012-11-13 (issuer 75208) | NYSE suspended 2012-11-14; OSGIQ is an OTC tail, not a listing | new |
| exit_kind | none | dropped | Item 1.03 + Item 3.01 | new agrees |
| drop_reason | none | bankruptcy | same | new agrees |
| successor | none | none | old common cancelled 2014-08-05, new Class A/B issued (CUSIPs 69036R...) | agree |
| last_trade_date | none | 2012-11-13 (MIDAS) | 8-K: NYSE announced "immediate suspension" on 2012-11-14, consistent with 11-13 as last print; flag last_trade_date_conflict | agree, not confirmed by a filing |
| value_rule | none | otc_print, OSGIQ from 2012-11-14 | fails rows: CUSIP 690368105 under OSGIQ from 2012-11-21 | agree |
| issuer | 75208 | 75208 | | agree |

## 3. Corrected classification
```
exit_kind: dropped
drop_reason: bankruptcy
continuation: false
successor: none
last_trade_date: 2012-11-13
value_rule: otc_print
cash_per_share: -
cash_currency: -
stock_ratio: -
price_ticker: OSGIQ
price_sec_id: BBG000BQMV15
price_date: 2012-11-14
recovery_ratio: -
value_formula: otc_print(OSGIQ, from 2012-11-14) / last_close - 1
event_type: bankruptcy
consideration: none (old equity cancelled 2014; new Class A/B and warrants issued under the Equity Plan)
holder_value: first OTC print
effective_date: 2012-12-20 (Form 25-NSE)
successor_ticker: -
confidence: inferred
```

## 4. Why this confidence: inferred
- exit kind: filing (8-K 0000075208-12-000032, Items 1.03 and 3.01).
- successor: filing (8-K 0001144204-14-048149: old common cancelled 2014-08-05, new classes issued).
- last trade date: worked out / MIDAS (SEC data, not a filing); the 8-K states only an "immediate suspension" on 2012-11-14. A 25-NSE notice or a filing stating the last session would make it verified.
- payout rule: filing (bankruptcy then OTC).
- terms: none needed for otc_print; the OTC symbol OSGIQ rests on fails rows.

## 5. What happened
- 2012-11-14 OSG filed Chapter 11 (D. Del., 12-20000); NYSE Regulation announced immediate suspension of trading [SEC 8-K 2012-11-15](https://www.sec.gov/Archives/edgar/data/75208/000007520812000032/chapter11form8-k.htm).
- 2012-12-20 NYSE filed Form 25-NSE [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/75208/000087666112000830/xslF25X02/primary_doc.xml).
- CUSIP 690368105 traded as OSG to 2012-11-20 (settlement lag), then as OSGIQ through 2014-05-27 (fails rows).
- 2014-08-05 Equity Plan effective; all old common cancelled, Class A and B common and warrants issued [SEC 8-K 2014-08-08](https://www.sec.gov/Archives/edgar/data/75208/000114420414048149/v386072_8k.htm). New securities trade under other CUSIPs (69036R301, 69036R863).

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC. Post-bankruptcy equity is a new security, so no continuation.

## 7. Why the library differed
The base run found no ending (the OTC tail kept the security alive in history); this run's bankruptcy branch finds it. The new output is right. Cause: library_right_but_uncertain.

## 8. Fix and open checks
No fix for the row. Open: confirm 2012-11-13 vs 2012-11-14 as the last NYSE session from a filing. Not golden-worthy as it stands (date unconfirmed).

## 9. Verification
Upheld both field verdicts (delistings.added, security_history.ranges: new is right).
- Re-read the 8-K (0000075208-12-000032): Item 3.01 says NYSE Regulation on 2012-11-14 announced the immediate suspension of trading of OSG common stock; Chapter 11 filed that day. A last NYSE session of 2012-11-13 follows.
- Fails rows for CUSIP 690368105: OSG through 2012-11-20, then OSGIQ from 2012-11-21, so the OTC tail is a drop, not a continued listing; the history range ending 2012-11-13 is right and the old OSGIQ range to 2014-05-27 was an OTC tail.
- Contract row: dropped / bankruptcy, no successor, otc_print priced under OSGIQ. Class is common, matching the 8-K.
- Caveat only: the 2012-11-13 date rests on MIDAS and the 8-K timing, not a filing stating the day. Not enough to refute.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (OSG's 2012 bankruptcy drop and its clipped range).

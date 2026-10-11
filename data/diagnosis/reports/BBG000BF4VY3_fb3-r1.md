# BBG000BF4VY3_fb3-r1 (CC, Circuit City Stores) - regression

## 1. Verdict
Circuit City filed Chapter 11 on 2008-11-10 and the NYSE suspended the common stock immediately that day (Form 25-NSE, Rule 12d2-2(b)); the ending is a bankruptcy drop. The new last trade 2008-11-07 (price date 2008-11-10) is the better-supported reading: the NYSE notice cites the 2008-11-07 close ($0.25) as the last price and no filing states a 2008-11-10 trade. Inferred, not verified.

## 2. Library vs evidence
| field | old (base) | new (library now) | evidence says | status |
| --- | --- | --- | --- | --- |
| last_trade_date | 2008-11-10 | 2008-11-07 | 2008-11-07, worked out: suspended "immediately" on 11-10 after a pre-market Chapter 11 filing; last cited close is 11-07 | new right (inferred) |
| price_date | 2008-11-11 | 2008-11-10 | trading day after last trade = 2008-11-10 | new right (follows last_trade_date) |
| security_history.ranges | CC:2007-12-17..2008-11-10 | CC:2007-12-17..2008-11-07 | range ends at the last trade | new right (follows last_trade_date) |
| exit_kind / drop_reason | dropped / bankruptcy | same | 8-K 1.03 + 3.01, 25-NSE | agree |
| value_rule | otc_print (CCTYQ) | same | CCTYQ traded from 2008-11-14 fails rows | agree |

## 3. Corrected classification
```
exit_kind: dropped   drop_reason: bankruptcy   continuation: false   successor: -
last_trade_date: 2008-11-07
value_rule: otc_print  price_ticker: CCTYQ  price_sec_id: BBG000BF4VY3  price_date: 2008-11-10
cash_per_share: -  stock_ratio: -  recovery_ratio: -
value_formula: otc_print(CCTYQ, from 2008-11-10) / last_close - 1
event_type: bankruptcy  consideration: none  effective_date: 2008-12-15  successor_ticker: -  confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 0000104599-08-000085 items 1.03, 3.01; 25-NSE 0000876661-08-000522).
- successor: none, filing.
- last trade date: worked out. The 25-NSE says the Exchange suspended trading "immediately" on 2008-11-10 and announced it on the ticker "immediately and at the close of the trading session on November 10"; it gives "a closing price of $0.25 on November 7, 2008". No filing states the last print. The fails rows (CC through 20081113 at a flat $0.25, CCTYQ from 20081114) cannot settle it, since fails settle days after trades.
- payout rule: fails rows (CCTYQ symbol under the same CUSIP 172737108).
- terms: none needed beyond the OTC symbol; fails rows.
To reach verified: an exchange print (MIDAS does not cover 2008) or a filing stating whether CC traded on 2008-11-10.

## 5. What happened
- Chapter 11 petition 2008-11-10; NYSE notified the company that day that listing was suspended immediately ([SEC 8-K 2008-11-12](https://www.sec.gov/Archives/edgar/data/104599/000010459908000085/ccs111208_8k.htm)).
- NYSE Form 25-NSE filed 2008-12-04: removal at the opening of business 2008-12-15 under 12d2-2(b); close $0.25 on 2008-11-07 ([SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/104599/000087666108000522/xslF25X02/primary_doc.xml)).
- Fails rows: CC to 2008-11-13, CCTYQ from 2008-11-14 (fails data).

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC.

## 7. Why the library differs from base
The sub-plan's date rule now reads the NYSE "suspended immediately" notice as the trading day before 2008-11-10 (source 8k_301); the base kept 11-10. Flag last_trade_date_conflict remains. Cause: other:last_trade_reading_of_immediate_suspension.

## 8. Fix and open checks
No fix needed if the date stands. Check whether the CC traded on 2008-11-10 (a halt print or a press account of the NYSE halt time). Not golden-worthy until the date is sourced.

## 9. Verification
Skeptic result: all three field verdicts upheld (confidence stays inferred).
- Re-read 25-NSE 0000876661-08-000522 (sec.py grep): "The Exchange, on November 10, 2008, determined that the Common Stock ... should be suspended immediately from trading"; it cites "a closing price of $0.25 on November 7, 2008", and the ticker announcement was made "immediately and at the close of the trading session on November 10". No text states a November 10 print.
- Re-read 8-K 0000104599-08-000085 Item 3.01: notice received November 10, 2008, listing suspended immediately (ruling R8: a suspension on D dates the last trade to the trading day before D). Common stock; 2008-11-07 (Fri) and 2008-11-10 (Mon) are both sessions.
- Fails rows (CUSIP 172737108): CC to 2008-11-13 flat at $0.25, CCTYQ from 2008-11-14. Settling rows, so they neither confirm nor refute 11-10; the OTC symbol agrees with the otc_print rule.
- price_date 2008-11-10 and the range end 2008-11-07 follow from last_trade_date; the date is within the Form 25 effective date (2008-12-15).
- Not refuted: no filing shows a 2008-11-10 trade. Residual risk: prints after the 11-10 open are unverifiable from SEC (MIDAS has no 2008).

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw; the 2008-11-07 last trade is worked out, not stated, and stays unpublished.

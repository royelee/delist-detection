# BBG000MW0PF2_fb3-r1 (CIT Group common, regression)

## 1. Verdict
CIT Group filed Chapter 11 on 2009-11-01 and the NYSE suspended its common stock before the open on 2009-11-03, so the last exchange trade was 2009-11-02. The new run is right: it has the bankruptcy drop row and ends the exchange ticker range on 2009-11-02. The base run had no ending and carried CIT through 2009-11-08, then a CITGQ range to 2009-12-16.

## 2. Library vs evidence (old = base run, new = this run)
| field | old (base) | new | evidence says | status |
| --- | --- | --- | --- | --- |
| delistings.added (exit_kind, drop_reason, continuation, successor, last_trade_date, value_rule) | no row | dropped / bankruptcy / false / none / 2009-11-02 / otc_print | 8-K Items 1.03/3.01 and 25-NSE: Chapter 11 on 2009-11-01, suspended before open 2009-11-03, plan cancels existing common | new right |
| security_history.ranges | CIT 2007-12-17..2009-11-08; CITGQ 2009-11-09..2009-12-16 | CIT 2007-12-17..2009-11-02 | exchange listing ends at last trade 2009-11-02; CITGQ is OTC trading after a bankruptcy delisting, not the listing (clip rule) | new right |
| issuer | 1171825 | 1171825 | CIT Group Inc, CIK 1171825 | agree |

## 3. Corrected classification
```
exit_kind=dropped  drop_reason=bankruptcy  continuation=false  successor=
last_trade_date=2009-11-02
value_rule=otc_print  cash_per_share=  cash_currency=  stock_ratio=  price_ticker=CITGQ
price_sec_id=BBG000MW0PF2  price_date=2009-11-03  recovery_ratio=
value_formula=otc_print(CITGQ, from 2009-11-03) / last_close - 1
event_type=bankruptcy  consideration=none  holder_value=old common cancelled under the plan; first OTC print
effective_date=2009-11-30 (removal from listing; 25-NSE filed 2009-11-18)  successor_ticker=  confidence=verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0000950123-09-057703 (Items 1.03, 3.01) and 25-NSE 0000876661-09-000439.
- successor: filing, 8-K 0000950123-09-069541 (1.03, 5.03) and the 25-NSE: existing common cancelled, new CIT stock is a new security (new 8-A12B 0000950123-09-069544); none.
- last trade date: filing, 25-NSE EX-99.25: "suspended before the opening of the trading session on November 3, 2009" -> 2009-11-02.
- payout rule: filing, 25-NSE: all existing common and preferred cancelled upon emergence; OTC print rule (decision 11).
- terms: the OTC symbol CITGQ is from fails rows (CUSIP 125581108 rows from 2009-11-09 under CITGQ); the filings state no symbol. No price is needed.

## 5. What happened
- 2009-11-01 CIT and CIT Funding began Chapter 11 prepackaged cases; NYSE announced on 2009-11-02 the suspension before the open on 2009-11-03 [SEC 8-K 2009-11-04](https://www.sec.gov/Archives/edgar/data/1171825/000095012309057703/y80157e8vk.htm).
- 25-NSE filed 2009-11-18 under 12d2-2(b), removal at the opening on 2009-11-30; trading suspended before open 2009-11-03; existing common to be cancelled [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/1171825/000087666109000439/xslF25X02/primary_doc.xml).
- Fails rows: CUSIP 125581108 under CIT to 2009-11-06, under CITGQ 2009-11-09..2009-12-16 (fails data).
- 2009-12-09/10 plan effective: 8-K 1.03/5.03, new 8-A12B, Form 15-12G [SEC 8-K 2009-12-09](https://www.sec.gov/Archives/edgar/data/1171825/000095012309069541/y02702e8vk.htm).

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC. Old equity cancelled; post-emergence stock is a new security.

## 7. Why the library got it wrong
The base run had no ending for this security (the Form 25 was not reached or matched), so it left the history open through the OTC tail. This run finds the 25-NSE and the 1.03 8-K. Cause: other:base run missed the Form 25 (late_form25 family); fixed in this run.

## 8. Fix and open checks
Nothing to fix. Suitable as a golden case. The OTC print price is qlib_practice's.

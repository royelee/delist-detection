# BBG000BF6F94_wave2-r1 (NMX, NYMEX Holdings), regression diagnosis

## 1. Verdict
CME Group acquired NYMEX Holdings by merger effective 2008-08-22 (cash-or-stock election, prorated). The merger ending is right. Of the two payout readings, the old one (cash 81.16, the default package) is the better published rule; the new one (7.29 cash + 0.2164 CME) is the stock electors' proration outcome, not the default. The new row's USD currency is correct and should be kept on the cash rule.

## 2. Library vs evidence
| field | old (base run) | new (this run) | evidence | right |
| --- | --- | --- | --- | --- |
| value_rule | cash | cash_plus_stock | default (non-election) package is all cash | old |
| cash_per_share | 81.16 | 7.29 | 81.16 = 36.00 + 0.1323 x 341.3720 (cash election and non-election) | old |
| cash_currency | blank | USD | filing states dollars | new (USD) |
| stock_ratio | blank | 0.2164 | 0.2164 applies only to stock electors after proration; stock election face = 0.2378 | old (blank) |
| price_sec_id / price_ticker / price_date | blank | BBG000BHLYP4 / CME / 2008-08-22 | only needed for a stock leg | old (blank) |
| exit_kind, last_trade_date, issuer | merger, 2008-08-21, CIK 1105018 | same | Form 25-NSE notice: suspended from trading Aug 22 | agree |

## 3. Corrected classification
```
exit_kind=merger drop_reason= continuation=false successor= last_trade_date=2008-08-21
value_rule=cash cash_per_share=81.16 cash_currency=USD stock_ratio= price_ticker= price_sec_id= price_date= recovery_ratio=
value_formula=81.16 / last_close - 1
event_type=acquisition consideration=cash_or_stock_election
holder_value="81.16 USD cash (default); stock electors: ~7.29 USD + 0.2164 CME after proration"
effective_date=2008-08-22 successor_ticker=CME confidence=verified
```

## 4. Why this confidence
verified.
- exit kind: filing (8-K 0001193125-08-187293 items 2.01/3.01/5.01; Form 25-NSE 0000876661-08-000336).
- successor: filing (none; a cash/stock merger into CME Group).
- last trade date: filing (Form 25-NSE notice: suspended from trading on August 22, 2008, so last trade 2008-08-21).
- payout rule: filing (8-K 0001193125-08-187293: non-electors receive all cash).
- terms: filing (same 8-K: $81.16 cash consideration; stock electors about $7.29 + 0.2164 CME).

## 5. What happened
- Merger effective 2008-08-22; each NYMEX share converted into cash $81.16 (= $36.00 + 0.1323 x $341.3720 average CME close) or stock 0.2378 CME, prorated ([SEC 8-K 2008-08-29](https://www.sec.gov/Archives/edgar/data/1105018/000119312508187293/d8k.htm)).
- Holders who fail to elect receive all cash, subject to proration ([SEC 25-NSE 2008-08-26](https://www.sec.gov/Archives/edgar/data/1105018/000087666108000336/xslF25X02/primary_doc.xml)).
- The $3.4bn mandatory cash component was undersubscribed, so stock electors (about 58M of about 95M shares) got about $7.29 + 0.2164 CME; cash electors (about 29M) and non-electors (about 8M) got $81.16 ([SEC 8-K 2008-08-22](https://www.sec.gov/Archives/edgar/data/1105018/000119312508182956/d8k.htm)).

## 6. Decision-tree bucket
Replaced by cash / stock of another company: merger.

## 7. Why the library got it wrong
The new run took the stock electors' package (cause: terms_misread, rule `llm_election_package`) over the agreement's default all-cash package; the published USD currency on the new row is an improvement, the old row lacked it (currency_missing).

## 8. Fix and open checks
Publish cash 81.16 USD for the default package; flag the election. If the policy is the aggregate package, the new reading is defensible, but the filings define non-election as all cash. Golden-worthy: yes (well sourced, election deal).

## 9. Verification
Upheld, all seven field verdicts. Rechecked: 8-K 0001193125-08-187293 (cached) states the cash election = $81.16 = $36.00 + 0.1323 x $341.3720, the stock election = 0.2378 CME, and the 7.29 + 0.2164 CME outcome only for stock electors after proration. Form 25-NSE 0000876661-08-000336 states that holders who fail to elect receive all cash (subject to proration), so 81.16 cash is the default package. Rule and cash term old is right, stock leg and price fields blank is right, USD on the new row is right. Minor: the share counts in section 5 (58M, 95M, 29M, 8M) are not in the cached 8-K 0001193125-08-182956 text (press release exhibit not cached); they affect no verdict. The two packages are worth about the same at the average CME price, so the choice is a policy one, as section 8 notes.

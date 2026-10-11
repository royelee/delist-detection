# BBG000BX0R13_fb3-r1 (WSC, Wesco Financial) - regression diagnosis

## 1. Verdict
Berkshire Hathaway acquired Wesco on 2011-06-24 for $385.00 per share, paid in cash or 5.0611 Berkshire Class B shares at each holder's election (no proration); holders who made no election got cash. The new row (cash 385 USD) is right; the old row (stock 5.0611 x BRK-B) took the non-default alternative as the package.

## 2. Library vs evidence
| Field | old (base) | new (run) | evidence | right |
| --- | --- | --- | --- | --- |
| exit_kind | merger | merger | merger, 8-K 2.01/5.01 | agree |
| continuation | false | false | false | agree |
| last_trade_date | 2011-06-24 | 2011-06-24 | 8-K 3.01: trading suspended prior to open next business day (June 27) | agree |
| value_rule | stock | cash | election, no proration; no-election default is cash | new |
| cash_per_share / cash_currency | blank | 385.00 USD | $385.00 stated in 8-K 2.01 | new |
| stock_ratio | 5.0611 | blank | 5.0611 is the alternative, not the default | new |
| price_ticker / price_sec_id / price_date | BRK-B / BBG000DWG505 / 2011-06-27 | blank | not needed for a cash rule | new |
| issuer | CIK 105729 | same | agree | agree |

## 3. Corrected classification
```
exit_kind: merger   drop_reason:   continuation: false   successor:
last_trade_date: 2011-06-24
value_rule: cash  cash_per_share: 385.00  cash_currency: USD  stock_ratio:  price_ticker:  price_sec_id:  price_date:  recovery_ratio:
value_formula: 385.00 / last_close - 1
event_type: acquisition  consideration: cash_or_stock_election
holder_value: 385.00 USD cash, or 5.0611 BRK-B (holder's choice, no proration; default cash)
effective_date: 2011-06-24  successor_ticker: BRK-B (stock alternative only)  confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-11-173360 (items 2.01, 3.01, 5.01).
- successor: filing, none (merger into a Berkshire subsidiary).
- last trade date: filing, same 8-K item 3.01 (suspension before open June 27) and 25-NSE 0001143313-11-000058; trading day before = 2011-06-24.
- payout rule: filing, DEFM14A 0001193125-11-144327: "Shareholders who fail to make an election will receive cash."
- terms: filing, 8-K 2.01: $385.00; exchange ratio 5.0611.

## 5. What happened
- Merger completed 2011-06-24; each Wesco share converted to $385.00 in cash or Berkshire Class B stock at the holder's election, exchange ratio 5.0611 [SEC 8-K 2011-06-24](https://www.sec.gov/Archives/edgar/data/105729/000119312511173360/d8k.htm).
- Elections are in any proportion, without proration or reallocation; non-electors receive cash [SEC DEFM14A 2011-05-18](https://www.sec.gov/Archives/edgar/data/105729/000119312511144327/ddefm14a.htm).
- Wesco asked NYSE Amex to suspend trading prior to market open on June 27 (same 8-K item 3.01); 25-NSE filed 2011-06-27 [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/105729/000114331311000058/xslF25X02/primary_doc.xml).

## 6. Decision-tree bucket
Replaced by cash / stock of another company: merger, not a continuation.

## 7. Why the library got it wrong
The base run published the election's stock alternative (llm_election_stock). The new run's llm_election_cash is the default package. The new row is right, so no library fault in this run.

## 8. Fix and open checks
None. The new row stands. Golden-worthy: yes (election with a cash default).

## 9. Verification
Re-read through sec.py. DEFM14A 0001193125-11-144327: "Shareholders can elect to receive cash or stock ... without proration or reallocation. Shareholders who fail to make an election will receive cash." 8-K 0001193125-11-173360 item 2.01: each share converted into $385.00 in cash or Berkshire Class B stock at the holder's election, exchange ratio 5.0611; item 3.01: suspension prior to market open June 27, so last trade 2011-06-24. Cash $385.00 USD is the default package; the stock leg is only the elected alternative, so value_rule cash, no stock_ratio and no price fields stand. All seven field verdicts upheld; none refuted.

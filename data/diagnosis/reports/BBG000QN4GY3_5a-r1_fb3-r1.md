# BBG000QN4GY3_5a-r1_fb3-r1 (HOUS, mismatch)

## 1. Verdict
Anywhere Real Estate Inc. (HOUS, formerly Realogy, CIK 1398987) was acquired by Compass, Inc. on 2026-01-09: each share became 1.436 Compass Class A shares. The library's merger ending is right; the truth row (shape no_ending) only recorded the 2022 RLGY->HOUS rename and missed this later ending.

## 2. Library vs evidence
| field | truth (side_a) | library (side_b) | evidence | status |
|---|---|---|---|---|
| shape | no_ending | ending | 25-NSE 0000876661-26-000018 (2026-01-09) and 8-K 0001193125-26-008327 (items 2.01, 3.01, 3.03, 5.01): merger completed 2026-01-09, stock ceased trading on the NYSE; Form 15-12G 2026-01-20 | library right |
| exit_kind | (not scored) | merger | same filings | agree |
| last_trade_date | (not scored) | 2026-01-08 | 25-NSE: suspended from trading on 2026-01-09, so last trade 2026-01-08 | agree |
| value_rule/terms | (not scored) | stock, 1.436 x COMP, price date 2026-01-09 | 25-NSE: 1.436 shares of Compass Class A per share, no cash | agree |
| issuer / ticker_history | (not scored) | CIK 1398987, RLGY then HOUS | filings under CIK 1398987 | agree |

## 3. Corrected classification
```
exit_kind: merger  drop_reason:  continuation: false  successor:  last_trade_date: 2026-01-08
value_rule: stock  cash_per_share:  cash_currency:  stock_ratio: 1.436  price_ticker: COMP
price_sec_id: BBG00J5SXTH3  price_date: 2026-01-09  recovery_ratio:
value_formula: 1.436 x price(COMP, 2026-01-09) / last_close - 1
event_type: acquisition  consideration: stock  holder_value: 1.436 Compass Class A shares
effective_date: 2026-01-09  successor_ticker: COMP  confidence: verified
```

## 4. Why this confidence
verified. Exit kind: 8-K 0001193125-26-008327 Items 2.01/5.01 plus 25-NSE. Successor: none (merger, not continuation). Last trade date: 25-NSE states suspension on 2026-01-09. Payout rule and terms: 25-NSE states the 1.436 ratio, no cash.

## 5. What happened
- [SEC 25-NSE 2026-01-09](https://www.sec.gov/Archives/edgar/data/1398987/000087666126000018/xslF25X02/primary_doc.xml): merger with Compass effective 2026-01-09; each share exchanged for 1.436 Compass Class A shares; suspended from trading 2026-01-09.
- [SEC 8-K 2026-01-09](https://www.sec.gov/Archives/edgar/data/1398987/000119312526008327/d33443d8k.htm): Merger Sub merged into the Company, which survives as a Compass subsidiary; common stock ceased trading on the NYSE.
- SEC Form 15-12G 0001398987-26-000047 filed 2026-01-20.

## 6. Decision-tree bucket
Replaced by stock of another company (merger).

## 7. Why the library got it wrong
It did not. The truth row came from the 5a regression about the 2022 rename (8-K 0001398987-22-000139) and judged only that no ending existed then; the 2026 merger came after it. Cause: truth_or_judge_issue.

## 8. Fix and open checks
Truth shape should be ending with the fields above. The earlier report read CIK 1355001 filings only up to 2023-08 and never looked at CIK 1398987 in 2026 (missed filing: 0000876661-26-000018). Golden-worthy: yes.

# BBG008NXC572_fb3-r1 (WRK), regression

## 1. Verdict
WestRock (WRK) ended on 2024-07-05 when it merged with Smurfit Kappa: each share became one Smurfit WestRock ordinary share plus 5.00 USD. The new run's added merger row (last trade 2024-07-05, cash_plus_stock) and its ranges ending 2024-07-05 are right; the old run's missing ending and 2024-07-09 range end were wrong.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| delistings.added | no contract row | merger, cash_plus_stock, 2024-07-05 | Form 25-NSE 0000876661-24-000561 | new right |
| exit_kind | none | merger | same notice | agree (new) |
| continuation | - | false | holders got cash + another issuer's shares | agree (new) |
| last_trade_date | - | 2024-07-05 | suspended July 8 2024, so previous trading day | agree (new) |
| value_rule / terms | - | 5.00 USD + 1 x price(SW, 2024-07-08) | notice: one Ordinary Share of Smurfit WestRock plc and 5.00 USD | agree (new) |
| ticker_history ranges | WRK 2015-07-02..2024-07-09, CIK 1636023 | WRK 2015-07-02..2018-11-06 (1636023); 2018-11-07..2024-07-05 (1732845) | 2018 holdco reorganization put new WestRock (CIK 1732845) in place; it filed the 25-NSE and the 15-12G | new right |

## 3. Corrected classification
```
exit_kind=merger drop_reason= continuation=false successor= last_trade_date=2024-07-05
value_rule=cash_plus_stock cash_per_share=5.00 cash_currency=USD stock_ratio=1 price_ticker=SW price_date=2024-07-08
value_formula=(5.00 + 1 x price(SW, 2024-07-08)) / last_close - 1
event_type=merger consideration=cash_and_stock effective_date=2024-07-05 successor_ticker=SW confidence=verified
```

## 4. Why this confidence
verified.
- exit kind: Form 25-NSE notice (merger effective July 5, 2024).
- successor: none; the acquirer is a different issuer.
- last trade date: same notice, suspended July 08, so July 5.
- payout rule: same notice (shares plus cash).
- terms: same notice (one ordinary share and 5.00 USD).

## 5. What happened
- [SEC 25-NSE 2024-07-08](https://www.sec.gov/Archives/edgar/data/1732845/000087666124000561/xslF25X02/primary_doc.xml): merger effective July 5, 2024; each share converted into one Smurfit WestRock ordinary share and 5.00 USD; suspended July 08, 2024.
- [SEC 8-K 2024-07-09](https://www.sec.gov/Archives/edgar/data/1732845/000095014224001867/eh240504483_8k.htm): items 2.01, 3.01, 3.03, 5.01 after the closing.
- [SEC 15-12G 2024-07-18](https://www.sec.gov/Archives/edgar/data/1732845/000110465924080840/tm2419498d4_1512g.htm): deregistration.

## 6. Decision-tree bucket
Replaced by cash and another company's stock: merger.

## 7. Why the library got it wrong
The base run had no contract ending for WRK (it treated the security as going on after the 2018 holdco change). The new run is correct. Cause: other:base missed the real 2024 ending.

## 8. Fix and open checks
None. Golden candidate: yes.

## 9. Verification
Skeptic re-check, both field verdicts upheld.
- delistings.added: re-read 25-NSE 0000876661-24-000561 (CIK 1732845, filed 2024-07-08): merger effective July 5, 2024; each share of WestRock Common Stock became one Smurfit WestRock ordinary share and 5.00 USD; suspended July 08, 2024 (Monday), so last trade Friday 2024-07-05. Class is the common. The contract row (2024-07-05, merger, cash_plus_stock, 5.00 USD, ratio 1, SW) matches.
- security_history.ranges: 8-K 0001171843-18-007567 (filed 2018-11-05, items 2.01/3.03/5.01) under CIK 1732845, and the old CIK 1636023's filings stopping 2018-10-31, support the issuer change; the 2018-11-07 split day is the library's convention, not contradicted. The end 2024-07-05 follows the confirmed last trade.

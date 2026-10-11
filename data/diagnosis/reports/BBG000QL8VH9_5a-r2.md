# BBG000QL8VH9_5a-r2 (PGEN, formerly XON), regression

## 1. Verdict
Intrexon moved its one common stock from the NYSE to Nasdaq on 2018-09-24 (same security, no ending) and renamed itself Precigen, changing the ticker XON to PGEN on 2020-02-03. The new run is right: no ending row, one security continuing under two tickers. The old row (exchange transfer, last trade 2020-01-31) was not a delisting.

## 2. Library vs evidence
| Field | old (side_a) | new (side_b) | evidence | right |
| --- | --- | --- | --- | --- |
| delistings row | exit_kind=exchange, last_trade 2020-01-31, transfer | removed | A rename and an earlier voluntary listing move; the same shares keep trading. Not an ending. | new |
| security_history.ranges | XON 2013-08-13..2020-01-31; PGEN 2020-02-05.. (gap 02-01..02-04) | XON ..2020-02-04; PGEN 2020-02-05.. | Symbol changed effective the open of 2020-02-03; same CIK 1356090 throughout. New has no gap; its boundary is 2 days late (fails rows), old has a 4-day gap. | new (closer, still imprecise) |
| id_changes.sec_id | CIK1356090-COMMON | BBG000QL8VH9 | The security now has a confirmed US composite FIGI; a rename of the placeholder is expected. | new |

Other fields agree with the new run: no exit_kind (not an ending), no successor, no value rule, issuer CIK 1356090.

## 3. Corrected classification
```
exit_kind: (no ending row)   drop_reason:    continuation: n/a   successor: none
last_trade_date: n/a
value_rule: continuation (not an exit)  cash_per_share:  cash_currency:  stock_ratio:  price_ticker:  price_sec_id:  price_date:  recovery_ratio:
value_formula: n/a
event_type: ticker_change (name change Intrexon -> Precigen); earlier exchange_transfer NYSE -> Nasdaq 2018-09-24
consideration: none   holder_value: same shares   effective_date: 2020-02-03   successor_ticker: PGEN   confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: not an ending; 8-K 2020-02-04 (0001193125-20-023400) reports a name change and symbol change only; 8-K 2018-09-12 (0001193125-18-271302) a listing transfer.
- successor: none; same registrant (CIK 1356090), same class "Common Stock, No Par Value".
- last trade date: not applicable; the symbol change is dated by the 8-K (effective with the opening on 2020-02-03).
- payout rule: not applicable, no exit.
- terms: not applicable.

## 5. What happened
- 2018-09-12: 8-K item 3.01, voluntary transfer of listing from NYSE to Nasdaq Global Select; NYSE trading ends at the close on 2018-09-24 [SEC 8-K 2018-09-12](https://www.sec.gov/Archives/edgar/data/1356090/000119312518271302/d622770d8k.htm).
- 2018-09-24: Form 25 (0001193125-18-281308) and 8-A12B for Nasdaq (0001193125-18-281244) [SEC 8-A12B 2018-09-24](https://www.sec.gov/Archives/edgar/data/1356090/000119312518281244/d612803d8a12b.htm).
- 2020-02-04: 8-K items 2.01, 5.03, 8.01: name change to Precigen and symbol XON to PGEN effective the open of 2020-02-03; cover shows PGEN on Nasdaq [SEC 8-K 2020-02-04](https://www.sec.gov/Archives/edgar/data/1356090/000119312520023400/d876809d8k.htm).
- The library's ticker_history shows the same security under PGEN from 2020-02-05 (source ftd).

## 6. Decision-tree bucket
Kept the same security (same registrant and class, new ticker; earlier a move to another exchange).

## 7. Why the library got it wrong (old run)
The old run produced a transfer row dated at the rename (last trade 2020-01-31) with no filing basis; the real Form 25 was in 2018. Cause: `rename_not_followed`. The new run correctly drops it.

## 8. Fix and open checks
No fix needed for the removal. Residual: ticker_history starts PGEN on 2020-02-05 instead of 2020-02-03 (XON runs 2 days long), minor. Golden-worthy: no.

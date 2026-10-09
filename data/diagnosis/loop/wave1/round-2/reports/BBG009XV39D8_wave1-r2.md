# BBG009XV39D8_wave1-r2 (AVGO, Broadcom Ltd) - regression

## 1. Verdict
Broadcom Ltd (Singapore) shares were exchanged one for one for Broadcom Inc (Delaware) shares by a scheme of arrangement that took effect after the close of trading on 2018-04-04; the old shares' last trade was 2018-04-04. The base run's range end (2018-04-05) is one day late and the new run's (2018-04-02) is two days early; neither is the filing's date.

## 2. Library vs evidence
| field | library says (old / new) | evidence says | status |
| --- | --- | --- | --- |
| security_history.ranges | AVGO 2016-02-01..2018-04-05 / 2016-02-01..2018-04-02 (CIK 1649338) | AVGO 2016-02-01..2018-04-04 (last trade after close 2018-04-04) | neither exact; old off by 1 day, new off by 2 days |
| exit_kind | exchange | exchange (1:1 redomiciliation) | agree |
| continuation / successor | true, BBG00KHY5S69 | Broadcom Inc, one for one, no cash | agree |
| last_trade_date | blank published (closing_day, unconfirmed) | 2018-04-04 (8-K: "After the close of market trading on April 4, 2018 ... Scheme became effective") | missing |
| value_rule | continuation | continuation | agree |
| terms | none | none | agree |
| issuer | 1649338 | Broadcom Ltd | agree |

## 3. Corrected classification
```
exit_kind: exchange   drop_reason:    continuation: true   successor: BBG00KHY5S69
last_trade_date: 2018-04-04
value_rule: continuation  cash_per_share:  cash_currency:  stock_ratio: 1  price_ticker:  price_date:  recovery_ratio:
value_formula: n/a (continuation)
event_type: reorganization  consideration: stock (1:1)  holder_value: 1 Broadcom Inc share per Broadcom Ltd share
effective_date: 2018-04-04 (after close)  successor_ticker: AVGO  confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-18-107587 (one-for-one scheme of arrangement).
- successor: filing, same 8-K; fails rows show CUSIP 11135F101 (Broadcom Inc) under AVGO from 2018-04-06 rows.
- last trade date: filing, same 8-K ("after the close of market trading on April 4, 2018"); Form 25-NSE 0001354457-18-000077 effective 2018-04-04.
- payout rule: filing, same 8-K (shares exchanged one for one, no cash).
- terms: filing, same 8-K.

## 5. What happened
- Court approval 2018-04-02; scheme effective after the close on 2018-04-04 ([SEC 8-K 2018-04-04](https://www.sec.gov/Archives/edgar/data/1649338/000119312518107587/d548692d8k.htm)).
- Nasdaq Form 25-NSE filed and effective 2018-04-04 under 12d2-2(a)(3) ([SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/1649338/000135445718000077/xslF25X02/primary_doc.xml)).
- Fails rows: Y09827109 (Singapore shares) under AVGO through 2018-04-05 (rows are dated a day after the print), Inc. CUSIP 11135F101 from 2018-04-06 (fails rows).

## 6. Decision-tree bucket
Replaced 1:1 by a new line of the same holders: continuation.

## 7. Why the library got it wrong
The range end follows the successor's first fails row (04-06, minus a day) in the old run, and the closing-day guess (04-02, the court approval day, flag last_trade_date_unconfirmed) in the new one; neither reads the 8-K's stated 04-04. Cause: no_last_trade_print.

## 8. Fix and open checks
Date the last trade from the 8-K's "after the close ... April 4" and clip the range there. Golden-worthy: yes (a stated last day, a 1:1 holdco move).

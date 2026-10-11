# CIK855876-COMMON_fb3-r1 (SKYF, Sky Financial Group) - regression

## 1. Verdict
Huntington Bancshares acquired Sky Financial for 1.098 HBAN shares plus $3.023 cash per share, effective 2007-07-01; Nasdaq filed Form 25-NSE on 2007-07-02. The new row (merger, cash_plus_stock, 1.098 HBAN + 3.023 USD) is right; the base run had no ending for this security, so `delistings.added` and the SKYF range 2004-07-07..2007-07-02 are both correct. The only open point is the last trade date, which the library correctly leaves blank.

## 2. Library vs evidence
| Field | library says (new) | evidence says | status |
| --- | --- | --- | --- |
| delistings.added (old: no row) | merger row added | Sky merged into Huntington's Penguin Acquisition LLC; [8-K 2007-07-02](https://www.sec.gov/Archives/edgar/data/49196/000129993307003961/htm_21224.htm) Item 2.01; Form 25-NSE 0001354457-07-000195 | agree (new right) |
| exit_kind | merger | merger | agree |
| drop_reason | blank | blank | agree |
| continuation / successor | false / none | cash+stock for another company, not 1:1 | agree |
| last_trade_date | blank (internal closing_day, unconfirmed) | no filing states the day; merger effective Sunday 2007-07-01, so the last session was Fri 2007-06-29 (worked out) | agree (blank is right: not an exchange print) |
| value_rule | cash_plus_stock | cash_plus_stock | agree |
| terms | 3.023 USD, 1.098, HBAN, llm, gate passed | 1.098 HBAN shares and $3.023 cash, without interest (8-K Item 2.01) | agree |
| issuer | CIK 855876 | Sky Financial Group, CIK 855876 | agree |
| security_history.ranges (old: none) | SKYF 2004-07-07..2007-07-02 | trading through the merger; Form 25 effective 2007-07-02 | agree (new right) |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor:
last_trade_date: (blank; worked out 2007-06-29)
value_rule: cash_plus_stock
cash_per_share: 3.023
cash_currency: USD
stock_ratio: 1.098
price_ticker: HBAN
price_sec_id: BBG000BKWSR6
price_date: 2007-07-02 (trading day after the last trade, worked out)
recovery_ratio:
value_formula: (3.023 USD + 1.098 x price(HBAN, 2007-07-02)) / last_close - 1
event_type: merger
consideration: cash_and_stock
holder_value: 3.023 USD cash + 1.098 HBAN shares
effective_date: 2007-07-01
successor_ticker: HBAN
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing, 8-K Item 2.01 (0001299933-07-003961) and Form 25-NSE 0001354457-07-000195.
- successor: filing, none (merger into Huntington).
- last trade date: worked out from the effective date 2007-07-01 (a Sunday), so the last session was 2007-06-29; no filing states it.
- payout rule: filing, 8-K Item 2.01.
- terms: filing, 8-K Item 2.01.
Not backed: the last trade day. A filing or exchange print stating it would make it verified (MIDAS starts 2012, so none exists).

## 5. What happened
- [SEC 8-K 2007-07-02](https://www.sec.gov/Archives/edgar/data/49196/000129993307003961/htm_21224.htm): merger effective July 1, 2007; each Sky share became 1.098 Huntington shares and $3.023 cash.
- [SEC 25-NSE 2007-07-02](https://www.sec.gov/Archives/edgar/data/855876/000135445707000195/xslF25X02/primary_doc.xml): Nasdaq removed Sky common stock, effective 2007-07-02.
- Sky 425 filed 2007-06-05, before the closing.

## 6. Decision-tree bucket
Replaced by cash and stock of another company: merger, not a continuation.

## 7. Why the library got it wrong
It did not: the base run had no ending for this security (a gap), and this run found the Form 25-NSE. Cause: library_right_but_uncertain (last trade date unconfirmed).

## 8. Fix and open checks
None needed. Observed_after_delisting is flagged only because the last observation is 2007-07-02. Could become a golden case once a last-trade source exists.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (Huntington acquired Sky Financial, 1.098 HBAN plus $3.023, 2007-07-01).

# CIK1611983-COMMON_fb3-r1 (LBKRV), regression

## 1. Verdict
LBKRV is a Liberty Broadband Series C subscription right (rights offering expiring 2015-01-09), not a common stock. The new run's `expiration` contract row (added) is right; its range extension to 2015-01-09 is consistent with the rights' life. The new side is right on both fields.

## 2. Library vs evidence
| field | library says (old -> new) | evidence says | status |
|---|---|---|---|
| delistings.added | no row -> exit_kind=expiration, last_trade_date blank, value_rule=expiration | Rights expired 5pm 2015-01-09 unless extended; Nasdaq Form 25-NSE for the "Subscription Rights to Purchase Shares of Series C Common Stock" filed 2015-01-09 | new right |
| exit_kind | (none) -> expiration | expiration | agree (new) |
| drop_reason / continuation / successor | blank / false / blank | none apply | agree |
| last_trade_date | blank | no filing states the last rights trading day; blank is correct (unconfirmed closing_day) | agree |
| value_rule / terms | expiration, no terms | a right: exercise at $40.36 per Series C share, or lapse; no payout | agree |
| issuer | 1611983 | Liberty Broadband Corp | agree |
| security_history.ranges | LBKRV 2014-12-31..2014-12-31 -> 2014-12-31..2015-01-09 | rights listed from 2014-12-11 (LBRKR), expired 2015-01-09; range to 2015-01-09 fits | new right (inferred) |

## 3. Corrected classification
```
exit_kind: expiration   drop_reason:    continuation: false   successor:
last_trade_date: (blank, unconfirmed)
value_rule: expiration  cash_per_share:  cash_currency:  stock_ratio:  price_ticker:  price_sec_id:  price_date:  recovery_ratio:
value_formula: none (right expired; exercise price 40.36 USD per Series C share)
event_type: expiration  consideration: none  holder_value: none  effective_date: 2015-01-09  successor_ticker:  confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing (Form 25-NSE 0001354457-15-000004, class text is rights; 8-K 0001611983-14-000013 expiry).
- successor: filing (none; a right has no successor).
- last trade date: left blank, which is the contract's rule for an unconfirmed day.
- payout rule: filing (8-K 0001611983-14-000013: right lapses at expiry).
- terms: none needed.

## 5. What happened
- [SEC 8-K 2014-12-05](https://www.sec.gov/Archives/edgar/data/1611983/000161198314000013/lbrd-20141204x8k.htm): rights offering, subscription price $40.36, commences 2014-12-11, expires 5:00 p.m. NYC 2015-01-09; rights trade as LBRKR on Nasdaq.
- [SEC Form 25-NSE 2015-01-09](https://www.sec.gov/Archives/edgar/data/1611983/000135445715000004/xslF25X02/primary_doc.xml): Nasdaq removes Subscription Rights to Purchase Shares of Series C Common Stock, rule 12d2-2(b).

## 6. Decision-tree bucket
Expired.

## 7. Why the library differs
Base run held the range only at 2014-12-31 and had no ending; the new run follows the Form 25 and classifies the right as expiration (CRSP 600). Cause: library_right_but_uncertain (improvement, no defect).

## 8. Fix and open checks
None needed. The exact last rights trading day is not in a filing read here. Not golden-worthy (a secondary right).

## 9. Verification
Upheld. Re-opened 8-K 0001611983-14-000013: Series C rights, $40.36 subscription price, trading as LBRKR from 2014-12-11, expiring 5:00 p.m. NYC 2015-01-09 unless extended. Re-opened Form 25-NSE 0001354457-15-000004 (filed and effective 2015-01-09): class is "Subscription Rights to Purchase Shares of Series C Common Stock". Both match the report. The new expiration row (blank last trade date, unconfirmed closing_day) and the range to 2015-01-09 (output/contract/security_history.csv) fit the right's life. No refuting evidence found. The exact last trading day remains unstated, as the report says.

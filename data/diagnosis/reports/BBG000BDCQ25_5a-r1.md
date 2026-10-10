# BBG000BDCQ25_5a-r1 (PRDO, regression)

## 1. Verdict
Career Education Corp renamed itself Perdoceo Education Corp and moved its Nasdaq common stock from CECO to PRDO on 2020-01-02 (new CUSIP, same holders, same claim, nothing paid). There was no delisting, so the new run is right to drop the 2019-12-31 `exchange` ending and to continue the ticker history under PRDO. The new range boundary is about one trading day late.

## 2. Library vs evidence
| Field | Old (base 794ef8d) | New (this run) | Evidence | Right |
| --- | --- | --- | --- | --- |
| delistings (row) | exit_kind=exchange, last_trade 2019-12-31, value_rule=transfer | no row | No Form 25 / 25-NSE and no Form 15 for CIK 1046568 between 2019-01-01 and 2021-01-01 (EDGAR filing list). The 8-K of 2019-12-18 is a name change (5.03) plus a ticker change (8.01), not a delisting. | new |
| exit_kind / continuation / successor | exchange / false / none | none | same security, renamed | new |
| security_history.ranges | CECO 2007-12-24..2019-12-31 only | CECO ..2020-01-02; PRDO 2020-01-03.. | 8-K 8.01: stock "will cease trading under CECO and will commence trading on January 2, 2020 under PRDO". Fails rows: CECO (141665109) 2019-12-03..2020-01-02, PRDO (71363P106) from 2020-01-03. Chain is continuous; true boundary is CECO through 2019-12-31, PRDO from 2020-01-02 (library 1-2 days late, fails dates lag). | new |
| id_changes.sec_id | CIK1046568-COMMON | BBG000BDCQ25 | The run now confirms a FIGI for the issuer and class; SEC filings cannot confirm a FIGI. Taken as a placeholder-to-FIGI upgrade (not checked against OpenFIGI here). | new |
| issuer | 1046568 | 1046568 | same CIK throughout | agree |

## 3. Corrected classification
```
event_type: name_change / ticker_change (not an ending; no delisting row)
exit_kind: (none)   drop_reason: (none)   continuation: n/a   successor: (none)
last_trade_date: n/a
value_rule: n/a (no row)   formula: n/a
consideration: none   holder_value: same share, new name/ticker/CUSIP 71363P106
effective_date: 2020-01-01 (name change, 12:01 a.m.); PRDO trading from 2020-01-02
successor_ticker: PRDO (same security)
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001564590-19-046273 (5.03 name change, 8.01 ticker/CUSIP change); no Form 25 or 15 listed.
- successor: filing, same registrant and class; none needed.
- last trade date: not applicable (no ending).
- payout rule: not applicable.
- terms: not applicable.
Open point: the exact first PRDO day rests on the filing's "expects ... January 2, 2020" and on fails rows.

## 5. What happened
- [SEC 8-K 2019-12-18](https://www.sec.gov/Archives/edgar/data/1046568/000156459019046273/ceco-8k_20191213.htm): name change to Perdoceo Education Corporation effective 12:01 a.m. 2020-01-01; common stock ceases trading as CECO and commences trading as PRDO on 2020-01-02; new CUSIP 71363P106; certificates need not be exchanged.
- [SEC 10-K 2020-02-19](https://www.sec.gov/Archives/edgar/data/1046568/000156459020005289/prdo-10k_20191231.htm), filed as prdo: the issuer carried on with the same CIK.
- Fails rows: CECO 141665109 last row 2020-01-02, PRDO 71363P106 first row 2020-01-03.

## 6. Decision-tree bucket
Kept the same security (rename, ticker change on the same stock; the CUSIP changed with the name).

## 7. Why the library got it wrong
The base run read the CECO to PRDO switch as an exchange transfer ending at 2019-12-31 (a ticker/CUSIP break), with PRDO not followed. This run follows the rename: cause `rename_not_followed` (fixed). Remaining: the PRDO range starts one trading day after the filing's date.

## 8. Fix and open checks
Nothing to fix for the regression. Optional: start PRDO on the filing's 2020-01-02 instead of the first fails row. Confirm FIGI BBG000BDCQ25 via OpenFIGI. Golden-worthy: yes, a CUSIP-changing rename with no Form 25 (the rule should never emit an ending).

## 9. Verification
Result: partly upheld.
- delistings.removed (new): upheld. The filing list for CIK 1046568 (2019-06-01..2021-01-01) holds no Form 25, 25-NSE or Form 15. 8-K 0001564590-19-046273 is Item 5.03 (name change effective 12:01 a.m. 2020-01-01) and 8.01 (CECO stops, PRDO starts 2020-01-02 on Nasdaq, new CUSIP 71363P106). A rename, not an ending.
- id_changes.sec_id (new): upheld. The OpenFIGI cache (cache/openfigi/40ba3af5...json) returns composite BBG000BDCQ25 for PERDOCEO EDUCATION CORP, PRDO, Common Stock. This closes the report's open FIGI check.
- security_history.ranges (new): refuted as stated. The recorded value is the new run's CECO..2020-01-02 / PRDO from 2020-01-03, yet the report itself finds the filing dates the switch as CECO to 2019-12-31 and PRDO from 2020-01-02. Storing that value as truth would keep a boundary the evidence shows 1-2 days late. The continuity (one security, PRDO taking over from CECO) is right; the exact dates are not. If a truth row is written, use PRDO from 2020-01-02 (CECO ending 2019-12-31) or leave the dates `*`.

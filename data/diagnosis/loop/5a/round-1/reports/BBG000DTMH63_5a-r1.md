# BBG000DTMH63_5a-r1 (NE, Noble Corp plc), regression

## 1. Verdict
The new ticker range (one NE row, 2009-03-30..2020-07-30) is right. The old ranges carved out NEZZZZ days, which are fails-file deleted-symbol markers on the two CUSIP-change days of 1:1 redomiciliations; NE traded continuously. The ending (bankruptcy drop, last trade 2020-07-30) is unchanged.

## 2. Library vs evidence
| field | old (base run) | new (this run) / evidence | status |
| --- | --- | --- | --- |
| security_history.ranges | NE 2009-03-30..2013-11-19; NE 2013-11-21..2020-07-30; NEZZZZ 2009-03-27..29; NEZZZZ 2013-11-20 | NE 2009-03-30..2020-07-30, one range. NEZZZZ has 1 FTD row each (20090327, CUSIP H5833N103; 20131120, CUSIP G65431101), the CUSIP-change days; the S-8 POS filings of 2013-11-20 state a merger effective 2013-11-20 exchanging each Noble-Switzerland share for one Noble-UK ordinary share. Same holder, same listing, no gap. | new right |
| exit_kind / drop_reason | dropped / bankruptcy | unchanged; 8-K 2020-07-31 items 1.03, 3.01; Form 25-NSE 2020-08-17 | agree |
| continuation / successor | none | none | agree |
| last_trade_date | 2020-07-30 | unchanged | agree |
| value_rule / terms | otc_print(NE) | unchanged, not in dispute | agree |
| issuer | CIK 1458891 | CIK 1458891 | agree |
| ticker_history | NEZZZZ rows | single NE range | new right |

## 3. Corrected classification
```
security_history.ranges: NE:2009-03-30..2020-07-30:1458891
exit_kind: dropped   drop_reason: bankruptcy   continuation: false   successor: -   last_trade_date: 2020-07-30
value_rule: otc_print  cash_per_share: -  cash_currency: -  stock_ratio: -  price_ticker: NE  price_sec_id: BBG000DTMH63  price_date: 2020-07-31  recovery_ratio: -
value_formula: otc_print(NE, from 2020-07-31) / last_close - 1
event_type: bankruptcy_delisting  consideration: otc print  holder_value: otc print  effective_date: 2020-08-27  successor_ticker: -  confidence: inferred
```

## 4. Why this confidence
Confidence: inferred (only the ticker range is at issue).
- exit kind: filing (8-K 0001193125-20-205998, items 1.03/3.01; 25-NSE 0000876661-20-000675), unchanged.
- successor: n/a, unchanged.
- last trade date: unchanged from the library, not re-derived here.
- payout rule / terms: unchanged, not in dispute.
- ticker range: S-8 POS 0001193125-13-447905 (1:1 merger effective 2013-11-20, same CIK); NEZZZZ evidence is fails rows (1 row each); that NE stayed the NYSE symbol across 2013-11-20 rests on the continuous observations, not a filing.
- Missing for verified: an exchange notice or 8-K stating NE continued under the new ordinary shares.

## 5. What happened
- Noble-Switzerland merged into Noble-UK, effective 2013-11-20, one share for one share ([SEC S-8 POS 2013-11-20](https://www.sec.gov/Archives/edgar/data/1458891/000119312513447905/d618153ds8pos.htm)).
- FTD rows under NEZZZZ: 1 row 2009-03-27 and 1 row 2013-11-20, each on the CUSIP-change day (fails-file check).
- Chapter 11 8-K 2020-07-31 ([SEC](https://www.sec.gov/Archives/edgar/data/1458891/000119312520205998/d85677d8k.htm)); Form 25-NSE 2020-08-17.

## 6. Decision-tree bucket
Kept the same security through both redomiciliations (1:1 reorganization); then lost to bankruptcy.

## 7. Why the library got it wrong
The base run took fails rows under a deleted-symbol marker (NEZZZZ) as ticker sightings, splitting the NE range. This run no longer does. Cause: other:deleted_symbol_marker_as_ticker (fixed in the new run).

## 8. Fix and open checks
No fix needed; the new row is right. Golden-worthy as a ticker-range case. Open: an exchange notice confirming NE continuity on 2013-11-20.

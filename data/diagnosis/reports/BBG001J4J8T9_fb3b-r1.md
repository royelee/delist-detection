# BBG001J4J8T9_fb3b-r1 (VER, regression)

## 1. Verdict
ARCP renamed itself VEREIT and moved its listing from Nasdaq to the NYSE with the same shares; the VER ticker began on 2015-07-31, so the NEW range (`ARCP` to 2015-07-30, `VER` from 2015-07-31) is right and the old one (VER from 2015-08-03) was wrong. Only `security_history.ranges` changed; the ending fields are identical in both runs.

## 2. Library vs evidence
| Field | Old (base run) | New (this run) | Evidence | Status |
| --- | --- | --- | --- | --- |
| security_history.ranges | ARCP 2011-09-12..2015-08-02; VER 2015-08-03..2021-10-29 | ARCP ..2015-07-30; VER 2015-07-31..2021-10-29 | 8-K 3.01 (2015-07-20): delist from Nasdaq after the close on 2015-07-30, begin trading on the NYSE on 2015-07-31 under the new name and ticker; Form 25 dated 2015-07-30; fails rows for 92339V100 symbol VER start 20150731 | new is right |
| exit_kind / value_rule / terms / last_trade_date / successor | merger, stock 0.705 O, 2021-10-29 | same | unchanged between runs, not re-examined | unknown |
| issuer | CIK 1507385 | same | VEREIT, Inc. CIK 1507385 on the 2015 filings | agree |

## 3. Corrected classification
```
ticker_history: ARCP 2011-09-12..2015-07-30 ; VER 2015-07-31..2021-10-29 (CIK 1507385)
exit_kind: merger (unchanged, not re-examined)  drop_reason:  continuation: false
successor: O  last_trade_date: 2021-10-29 (unchanged)
value_rule: stock  stock_ratio: 0.705  price_ticker: O  price_date: 2021-11-01  (unchanged)
event_type: merger  confidence: inferred
```

## 4. Why this confidence
inferred: the disputed field (ticker range) rests on filings; the rest of the row was not re-derived.
- exit kind: not re-examined (library row).
- successor: not re-examined.
- last trade date: not re-examined.
- payout rule / terms: not re-examined; library says 0.705 O, terms_source llm, gate passed.
- ticker range: filing, 8-K 0001507385-15-000053 and Form 25 0001507385-15-000060.
Would make it verified: the Realty Income / VEREIT merger 8-K 2.01 and the exchange's last-trade notice.

## 5. What happened
- [SEC 8-K 2015-07-20](https://www.sec.gov/Archives/edgar/data/1507385/000150738515000053/arcp8-ktransferoflisting.htm): voluntary Nasdaq delisting after the close on 2015-07-30, NYSE trading begins 2015-07-31 under a new name and ticker.
- [SEC 8-K 2015-07-28](https://www.sec.gov/Archives/edgar/data/1507385/000150738515000056/arcp8-k72815.htm): name changed to VEREIT, Inc. effective 2015-07-28.
- [SEC Form 25 2015-07-30](https://www.sec.gov/Archives/edgar/data/1507385/000150738515000060/form25.htm): Nasdaq removal, effective 2015-07-30, a listing transfer.
- Fails rows: CUSIP 92339V100 under VER from 20150731; CUSIP 02917T104 under ARCP through 20150731 (settlement lag), plus one T104PS row 20150803.

## 6. Decision-tree bucket
Kept the same security: a rename plus exchange transfer (name_change / exchange_transfer), no ending row for 2015.

## 7. Why the library got it wrong
The old run started VER at 2015-08-03, matching the CUSIP-switch boundary in cusip_history (02917T104 to 2015-08-03, 92339V100 from 2015-08-04), not the 8-K 3.01 transfer date. Cause tag: other:old run's range start came from CUSIP/fails dates rather than the transfer date. The new run is right.

## 8. Fix and open checks
No fix needed for the ranges. Open: cusip_history boundary 2015-08-03/04 versus the actual 2015-07-31 switch (not examined further); confirm the 2021 merger terms (0.705 O) from Realty Income filings. Not golden-worthy.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right, from the filing it cites, and its ranges are exactly the new run's (checked against the case's sides); the confidence is inferred only because the switch day also rests on the fails rows (ARCP to 2015-07-30, VER from 2015-07-31, the 8-K 3.01 and Form 25).

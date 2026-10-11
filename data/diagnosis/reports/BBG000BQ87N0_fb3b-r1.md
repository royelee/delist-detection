# BBG000BQ87N0_fb3b-r1 (ES, Eversource Energy, ex Northeast Utilities) - regression, security_history.ranges

## 1. Verdict
Northeast Utilities (NU) is the same security as Eversource (ES): a ticker change only, no ending. Its filings say ES trading began Thursday 2015-02-19, so NU's last day is 2015-02-18. Neither run is exact; the new run (ES from 2015-02-20, NU to 2015-02-19) is one trading day off, the old run (ES from 2015-02-23, NU to 2015-02-22) two trading days off. The new run is the closer one.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| security_history.ranges | ES:2015-02-23.., NU:2008-01-16..2015-02-22 | ES:2015-02-20.., NU:2008-01-16..2015-02-19 | ES from 2015-02-19, NU to 2015-02-18 | both off; new is closer |
| exit_kind / successor / value_rule | none (security continues) | same | rename only | agree |
| issuer | 72741 | 72741 | CIK 72741 throughout | agree |

Fails rows (offline, `sec.py fails`): ES CUSIP 30040W108 first row 20150219 at a $0.01 placeholder; NU CUSIP 664397106 last row 20150220. The fails rows are settlement-dated and lag trading, so they do not fix the first trading day; the filings do.

## 3. Corrected classification
```
exit_kind: none (no ending; ticker NU -> ES, same security, same CIK 72741)
ticker_history: NU 2008-01-16..2015-02-18 ; ES 2015-02-19..
event_type: ticker_change
confidence: verified
```

## 4. Why this confidence
Confidence verified (for the ticker change).
- exit kind: filing, 8-K 0000072741-15-000005 and 10-K 0000072741-15-000013 (no ending, a rename).
- successor: none needed.
- last trade date: not applicable; the NU/ES switch day is stated by filing (2015-02-19).
- payout rule / terms: not applicable.

## 5. What happened
- [SEC 8-K 2015-02-03](https://www.sec.gov/Archives/edgar/data/72741/000007274115000005/form8kedgar.htm): began operating as Eversource Energy on 2015-02-02; "Effective Thursday, February 19, 2015, the company is expected to commence trading under its new ticker symbol, ES, on the NYSE."
- [SEC 10-K 2015-02-25](https://www.sec.gov/Archives/edgar/data/72741/000007274115000013/f2014form10kedgar.htm): "Effective February 19, 2015, the ticker symbol is ES."

## 6. Decision-tree bucket
Kept the same security (name and ticker change).

## 7. Why the library got it wrong
Neither run is exactly right: both take a fails row (dated after the true first trading day) as the ES start. Cause: other:ticker_start_from_fails_rows_lags_filing_date. The new run moves the start one trading day closer; it is not a regression away from the truth.

## 8. Fix and open checks
The start 2015-02-19 comes from the 8-K, which the range builder does not read. No truth row needed; not golden-worthy, as the day-level difference depends on fails-row lag.

## 9. Verification
Skeptic re-check through sec.py. Verdict upheld.
- 8-K 0000072741-15-000005: "Effective Thursday, February 19, 2015, the company is expected to commence trading under its new ticker symbol, ES, on the New York Stock Exchange." 2015-02-19 was a Thursday.
- 10-K 0000072741-15-000013, Item 5: "Effective February 19, 2015, the ticker symbol is ES." Same NYSE common shares, same CIK 72741.
- So the true ranges are ES from 2015-02-19 and NU to 2015-02-18. Base (ES 02-23, NU to 02-22) and new (ES 02-20, NU to 02-19) both differ, so "neither" holds.
- Regression mode: no missed_filing claimed, none needed.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (8-K: ES from 2015-02-19; base 02-23, new 02-20). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

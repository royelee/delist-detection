# BBG000BNGTQ7_fb3b-r1 (BBWI), regression, security_history.ranges

## 1. Verdict
No ending: L Brands renamed itself Bath & Body Works and changed ticker LB to BBWI (same CUSIP line changes to 070830104, same CIK 701985) at the open on 2021-08-03. The new run (BBWI from 2021-08-05) is closer than the base (2021-08-09) but neither equals the filing: LB ends 2021-08-02, BBWI starts 2021-08-03.

## 2. Library vs evidence
| field | library says (old / new) | evidence says | status |
|---|---|---|---|
| exit_kind / continuation / successor | no ending | no ending, rename only | agree |
| security_history.ranges LB end | old 2021-08-08 / new 2021-08-04 | 2021-08-02 | wrong both, new closer |
| security_history.ranges BBWI start | old 2021-08-09 / new 2021-08-05 | 2021-08-03 | wrong both, new closer |
| issuer | 701985 | 701985 | agree |

Fails rows (offline): LB 501797104 last row 2021-08-06; BBWI 070830104 first row 2021-08-05. A fails row is dated at settlement, after the trade, so a first row cannot precede the real first day; the base's 08-09 came from the CUSIP's range start after a settling tail.

## 3. Corrected classification
```
exit_kind: none (rename)   continuation: n/a
ranges: LTD 2007-12-17..2013-12-03; LB 2013-12-04..2021-08-02; BBWI 2021-08-03..
event_type: ticker_and_name_change (with VS spin-off 2021-08-02)   confidence: verified
```

## 4. Why this confidence
verified for the ranges' filing facts. Ticker change: filing, 8-K 0001140361-21-026658 Item 5.03 "Effective at the open of business on August 3, 2021 ... began trading ... under the new ticker symbol BBWI and the new CUSIP 070830104". Other fields: no ending, nothing to value.

## 5. What happened
- [SEC 8-K 2021-08-03](https://www.sec.gov/Archives/edgar/data/701985/000114036121026658/nt10026698x7_8k.htm): spin-off of Victoria's Secret completed after close 2021-08-02; name changed effective 11:59 pm that day; BBWI and CUSIP 070830104 from the open on 2021-08-03.
- Fails rows: LB through 2021-08-06 (settlement tail), BBWI from 2021-08-05.

## 6. Decision-tree bucket
Kept the same security (rename, new CUSIP).

## 7. Why the library got it wrong
The ranges follow fails rows, which lag trades by two settlement days; the new run's LB end (08-04) and BBWI start (08-05) still rest on them. Cause: other:range edges from fails rows not the 8-K 5.03 date.

## 8. Fix and open checks
Optional: use an 8-K text-stated effective date for a ticker change. Not a regression; the new value is closer. Golden-worthy: yes, for the 08-03 date.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (8-K: BBWI from 2021-08-03; base 08-09, new 08-05). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

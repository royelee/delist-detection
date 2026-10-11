# BBG000BGZ832_fb3b-r1 (SITC, SITE Centers, formerly DDR) - regression, security_history.ranges

## 1. Verdict
DDR Corp. renamed itself SITE Centers and the NYSE ticker changed from DDR to SITC effective with the open on 2018-10-12. The new run's ranges (DDR to 2018-10-11, SITC from 2018-10-12) are right; the base run's (DDR to 2018-10-15, SITC from 2018-10-16) are wrong. The security is the same one (same FIGI, CIK 894315); no delisting.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| security_history.ranges | DDR ..2018-10-15; SITC 2018-10-16.. | DDR ..2018-10-11; SITC 2018-10-12.. | SITC trading effective at the open 2018-10-12 ([web](https://www.reit.com/news/blog/nareit-developments/ddr-change-name-site-centers-corp)); SITC fails rows start 2018-10-12 | new right |
| exit_kind / continuation / successor | none | none | no Form 25; name change only | agree |
| issuer | 894315 | 894315 | same registrant | agree |

## 3. Corrected classification
```
exit_kind: (none, still listed)   successor: none   ranges: DDR 2007-12-21..2018-10-11 ; SITC 2018-10-12..
event_type: ticker_rename   confidence: inferred
```

## 4. Why this confidence
- exit kind / successor / payout rule / terms: no ending; not applicable (filing: 8-K 0001193125-18-298358 states a name change only).
- ticker change date: web (company press release 2018-10-09 via REIT.com: effective with the open 2018-10-12) plus fails rows (SITC first row 2018-10-12, CUSIP 82981J109). The SEC 8-K 5.03 states the name change filed 2018-10-11 but no ticker date. To be verified: an SEC exhibit stating the ticker effective date.

## 5. What happened
- [SEC 8-K 2018-10-12](https://www.sec.gov/Archives/edgar/data/894315/000119312518298358/d630661d8k.htm): on 2018-10-11 the company changed its name from DDR Corp. to SITE Centers Corp. by amended articles.
- [web](https://www.reit.com/news/blog/nareit-developments/ddr-change-name-site-centers-corp): ticker SITC effective with the open on 2018-10-12.
- Fails rows: SITC 2018-10-12..2018-11-30; DDR symbol 2018-10-02..2018-10-15 (settling tail, its last price $11.99 equals SITC's first).

## 6. Decision-tree bucket
Kept the same security (rename).

## 7. Why the library got it wrong
The base run counted the DDR settling-tail fails rows (through 10-15) as DDR sightings and began SITC at the CUSIP's first date, 2018-10-16. The new run's tail handling (commit f56ff50) fixes this. Cause: other:ticker-tail sighting in base.

## 8. Fix and open checks
None needed. DDR's last trading day 2018-10-11; SITC's first 2018-10-12. Not golden-worthy.

## 9. Verification
Skeptic re-check, field security_history.ranges (right = new): UPHELD.
- Re-ran `sec.py fails`: SITC (CUSIP 82981J109) first row 2018-10-12, 15 rows to 2018-11-30, first $11.99; DDR (CUSIP 23317H854, a different CUSIP string than the SITC one only by the name-change CUSIP reissue, same issuer) 4 rows 2018-10-02..2018-10-15, last $11.99 = SITC's first price, so the DDR rows after 10-11 are a settling tail, not trading under DDR.
- Re-read 8-K 0001193125-18-298358 (filed 2018-10-12): Item 5.03, name changed DDR Corp. to SITE Centers Corp. on 2018-10-11, same registrant CIK 894315; no Form 25, no merger. Same security, no ending.
- The 2018-10-09 8-K (item 2.02) has no ticker text; the 2018-10-12 trading start rests on the fails rows and the web press release (not re-fetched here). A date of 10-16 for SITC (base) is contradicted by SITC fails rows dated 10-12. Open check unchanged: an SEC exhibit stating the effective date.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right, from the filing it cites, and its ranges are exactly the new run's (checked against the case's sides); the confidence is inferred only because the switch day also rests on a press release and the fails rows (DDR to 2018-10-11, SITC from 2018-10-12).

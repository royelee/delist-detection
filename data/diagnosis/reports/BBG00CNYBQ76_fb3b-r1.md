# BBG00CNYBQ76 (PR, formerly CDEV) - regression fb3b-r1

## 1. Verdict
Centennial Resource Development renamed itself Permian Resources at the 2022-09-01 closing and its Class A stock began trading as PR on Nasdaq at the start of trading on 2022-09-02. This is a rename of the same security. CDEV's last session was 2022-09-01, so the old range (CDEV to 09-07, PR from 09-08) and the new range (CDEV to 09-05, PR from 09-06) are both wrong; the new one is closer. Neither is right.

## 2. Library vs evidence
| Field | Library says (old / new) | Evidence says | Status |
| --- | --- | --- | --- |
| security_history.ranges | old: CDEV ..2022-09-07, PR 2022-09-08..; new: CDEV ..2022-09-05, PR 2022-09-06.. (CIK 1658566) | CDEV ..2022-09-01, PR 2022-09-02.. (8-K: "began trading under the new symbol PR ... at the start of trading on September 2, 2022") | wrong (both) |
| exit_kind / drop_reason / continuation / successor | none (no ending row) | rename, no ending. The Sept 12 Nasdaq-to-NYSE move (issuer's own Form 25, 8-A12B) is an exchange transfer, not a delisting | agree |
| last_trade_date | blank | n/a (no ending) | agree |
| value_rule / terms | none | none | agree |
| issuer | CIK 1658566 | CIK 1658566 (registrant before and after the name change) | agree |
| ticker_history | see ranges | boundary 09-01 / 09-02 | wrong |

Why the dates differ: the boundary comes from the fails-to-deliver files. CUSIP 15136A102 shows CDEV rows through 20220907; CUSIP 71424F105 shows PR rows from 20220906. FTD dates are settlement dates, lagging the trade by about T+2 (Sept 5 was a market holiday, so a Sept 2 trade settles Sept 6). The new range's PR start of 09-06 is the first settlement date, not the first trade date. The CUSIP history boundary (09-07 / 09-08) is likewise from fails data.

## 3. Corrected classification
```
exit_kind:        (none - rename)
drop_reason:
continuation:     n/a
successor:        none
last_trade_date:  CDEV last session 2022-09-01 (ticker range end)
value_rule:       continuation
cash_per_share:   null
cash_currency:
stock_ratio:      null
price_ticker:
price_sec_id:
price_date:
recovery_ratio:   null
value_formula:    n/a (not an exit)
event_type:       name_change / ticker_change
consideration:    none
holder_value:     same Class A shares ("continue to hold their shares of Class A Common Stock")
effective_date:   2022-09-01 (name change at closing); PR trading from 2022-09-02
successor_ticker: PR
confidence:       verified
ticker ranges:    CDEV 2016-10-13..2022-09-01 ; PR 2022-09-02..
```

## 4. Why this confidence
Confidence: verified.
- exit kind: filing - 8-K 0001193125-22-241104 (no ending; name change).
- successor: filing - same 8-K (same registrant).
- last trade date: filing - same 8-K states PR trading began 2022-09-02, so CDEV's last session is the prior trading day 2022-09-01.
- payout rule: filing - same 8-K (stockholders "continue to hold their shares").
- terms: not applicable; no exit.

## 5. What happened
- Closing of the Business Combination Agreement on 2022-09-01; the company changed its name from Centennial Resource Development, Inc. to Permian Resources Corporation. [SEC 8-K 2022-09-08](https://www.sec.gov/Archives/edgar/data/1658566/000119312522241104/d402395d8k.htm)
- Class A began trading as PR on Nasdaq at the start of trading on 2022-09-02; new CUSIP 71424F105. Same 8-K and [SEC 8-A12B 2022-09-08](https://www.sec.gov/Archives/edgar/data/1658566/000119312522241108/d359168d8a12b.htm).
- Listing transferred to the NYSE on about 2022-09-12; the issuer's own Form 25 (effective 2022-09-12) withdrew the Nasdaq listing. [SEC Form 25 2022-09-12](https://www.sec.gov/Archives/edgar/data/1658566/000119312522242336/d358175d25.htm)
- Fails rows (settlement dates): 15136A102 CDEV through 20220907; 71424F105 PR from 20220906.

## 6. Decision-tree bucket
Kept the same security: ticker and name change, same issuer, holders keep their shares.

## 7. Why the library got it wrong
The ranges are cut from fails settlement dates rather than the 8-K's stated first PR trading day. Both runs put the boundary late; the new run is 2 trading days late at PR's start (09-06 vs 09-02 over the Labor Day holiday), the old run 4. Cause: other:ticker range boundary from fails settlement dates, not the rename 8-K.

## 8. Fix and open checks
- The boundary should be CDEV ..2022-09-01, PR 2022-09-02.. (use the 8-K's "began trading under the new symbol" date; a T+2 settlement-lag adjustment would also give 09-02 from 09-06).
- No delistings row should appear for the Nasdaq-to-NYSE Form 25.
- Golden: not on its own.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (8-K 0001193125-22-241104: PR from 2022-09-02; base 09-08, new 09-06). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

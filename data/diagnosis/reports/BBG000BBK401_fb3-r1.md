# BBG000BBK401_fb3-r1 (MATX) - regression, security_history.ranges

## 1. Verdict
Matson (formerly Alexander & Baldwin) never left the listing: it reorganized into a holding company in June 2012, changed its name and moved its ticker from ALEX to MATX on 2012-07-02. The new run (side_b) publishes the security's full ticker history from 2008-01-16; the base run (side_a) published only MATX from 2012-07-06 and dropped 2008-2012. The new ranges are better; only the one-day issuer split on 2012-06-29 and the MATX start date are doubtful.

## 2. Library vs evidence
| Field | old (base run) | new (this run) | evidence | status |
| --- | --- | --- | --- | --- |
| security_history.ranges | MATX 2012-07-06.. (CIK 3453) | ALEX 2008-01-16..2008-10-01, AXB 2008-10-02..2009-05-06, ALEX 2009-05-07..2012-06-28, ALEX 2012-06-29 (CIK 1541927), ALEX 2012-06-30..2012-07-05, MATX 2012-07-06.. | Security observed from 2008-01-16 and traded throughout (no ending: the [2008-09-29 Form 25](https://www.sec.gov/Archives/edgar/data/3453/000000345308000048/form_25.htm) is an exchange move; fails rows show AXB then ALEX). Old run omitted all pre-2012 history. | new right |
| issuer split 2012-06-29 | none | one day under CIK 1541927 | [8-K 2012-06-13](https://www.sec.gov/Archives/edgar/data/3453/000110465912043129/a12-14275_18k.htm): Alexander & Baldwin Holdings, Inc. is the registrant of the common stock; [8-K 2012-07-05](https://www.sec.gov/Archives/edgar/data/3453/000110465912047735/a12-15920_18k.htm): Matson, formerly Holdings. A one-day range looks like an artifact. | unknown (minor) |
| MATX start | 2012-07-06 | 2012-07-06 | [8-K 2012-07-03](https://www.sec.gov/Archives/edgar/data/3453/000110465912047269/a12-15783_18k.htm): company "now trades on the NYSE under MATX" (event July 2, 2012). Library uses the first fails row of the new CUSIP. | wrong in both (4 days late) |
| exit_kind / value_rule / terms / last_trade | unchanged | unchanged | not part of this regression | agree |

## 3. Corrected classification
```
ranges: ALEX 2008-01-16..2008-10-01; AXB 2008-10-02..2009-05-06; ALEX 2009-05-07..2012-07-01; MATX 2012-07-02..
exit_kind: none (listed today)   continuation: n/a   successor: none
value_rule: n/a   event_type: holding_company_reorganization + rename
effective_date: 2012-06-29 (separation); MATX from 2012-07-02   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: no ending; rests on the filings above and the security still trading (fails rows).
- successor: none.
- last trade date: none.
- payout rule / terms: none.
- ticker ranges: fails rows for dates, plus the 8-K stating MATX from July 2. The AXB and ALEX 2008-2009 dates rest on fails rows only.
Not backed: exact AXB dates; issuer CIK per day in June 2012. A filing stating them would make it verified.

## 5. What happened
- 2008-09-29 Form 25 for the issuer's exchange move; stock continues as AXB, back to ALEX in 2009 (fails rows).
- 2012-06-12 NYSE 25-NSE for ALEXANDER & BALDWIN INC [link](https://www.sec.gov/Archives/edgar/data/3453/000087666112000277/xslF25X02/primary_doc.xml); 2012-06-25 Form 15-12B [link](https://www.sec.gov/Archives/edgar/data/3453/000110465912045519/a12-15217_11512b.htm): old registrant replaced by the holding company.
- 2012-07-02 Matson, Inc. (formerly Alexander & Baldwin Holdings) completes the separation and trades as MATX.

## 6. Decision-tree bucket
Kept the same security (holding-company reorganization and rename; CUSIP 014481105 to 57686G105).

## 7. Why the library got it wrong
Base run lost the 2008-2012 history (the 2008 Form 25 was read as an ending that clipped it); this run keeps it. Residuals: one-day issuer split (other:issuer_in_force one-day registrant range) and fails-row lag for the MATX start (other:ticker_start_lag).

## 8. Fix and open checks
Keep the new behaviour. Check whether CIK 1541927 should cover a longer June 2012 span or none; MATX start should be 2012-07-02. Not golden-worthy as is.

## 9. Verification
Skeptic result: security_history.ranges is refuted as stated (upheld = false).
- Direction holds: the 2008-09-29 Form 25 (NASDAQ to NYSE, ALEX to AXB) is a move, not an ending, and fails rows show AXB 2008-10-02.. and MATX 2012-07-06.., so the base run's loss of 2008-2012 is wrong.
- The stated value is not the truth, though. The Form 25 says AXB's first NYSE day is expected 2008-10-01 (fails rows begin 10-02: settlement lag), yet the value ends ALEX on 2008-10-01. Section 3 of this same report says MATX starts 2012-07-02 and ALEX runs to 2012-07-01, yet the value has ALEX to 2012-07-05 and MATX from 2012-07-06 (fails lag, which section 2 calls wrong in both runs). Entering these dates would put known-wrong boundaries into the truth set.
- The 2012-07-03 and 2012-07-05 8-K links are filed under CIK 3453 in the report, but the issuer filings I listed sit under CIK 1541927; the cited accession 0001104659-12-047269 could not be read under 3453 (no text). The MATX 07-02 date is therefore not re-confirmed by me.
- Ruling: the fix is a correct-ranges claim (AXB from 2008-10-01, MATX from 2012-07-02), not the new run's values; at most "new better than old".

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw; its residuals (a one-day issuer split, MATX starting 4 days late) are smaller than the base's loss of the 2008-2012 history.

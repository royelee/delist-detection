# BBG000C4VW39 (OA, Orbital ATK) - regression, security_history.ranges

## 1. Verdict
Alliant Techsystems (ATK) renamed itself Orbital ATK and began trading as OA on the NYSE on 2015-02-10, same issuer (CIK 866121). Neither the old ranges (ATK to 02-16, OA from 02-17) nor the new ones (ATK to 02-12, OA from 02-13) match the filing; the new ones are closer by four days but both are wrong. The right split is ATK to 2015-02-09 and OA from 2015-02-10.

## 2. Library vs evidence
| Field | old (base run) | new (this run) | evidence | status |
| --- | --- | --- | --- | --- |
| security_history.ranges | ATK:2008-01-16..2015-02-16; OA:2015-02-17..2018-06-06 | ATK:2008-01-16..2015-02-12; OA:2015-02-13..2018-06-06 | ATK:2008-01-16..2015-02-09; OA:2015-02-10..2018-06-06 | neither right; new closer |
| exit_kind | merger | merger | merger (Northrop, 2018; outside this diff) | agree |
| last_trade_date | 2018-06-06 | 2018-06-06 | not under dispute | agree |
| issuer | 866121 | 866121 | CIK 866121 for both tickers | agree |

Fails rows (`sec.py fails`): old CUSIP 018804104 (ATK) last row 20150213, new CUSIP 68557N103 (OA) first row 20150213. Fails dates are settlement dates and lag the trade date, so the library's boundary looks derived from them. The 8-K states the trading date directly.

## 3. Corrected classification
```
exit_kind: merger (unchanged)   drop_reason: ""   continuation: false   successor: ""
last_trade_date: 2018-06-06 (unchanged)
ticker_history: ATK 2008-01-16..2015-02-09 ; OA 2015-02-10..2018-06-06
value_rule: cash (unchanged, not examined)  cash_per_share: 134.50 USD (library's)  price_ticker: ""
event_type: ticker_change (2015 rename); the ending event is unchanged
confidence: verified for the ticker boundary
```

## 4. Why this confidence
verified, for the one field in dispute (the ticker boundary).
- exit kind: not examined, outside the diff.
- successor: not examined.
- last trade date: not examined.
- payout rule: not examined.
- terms: not examined.
- ticker boundary: filing, 8-K 0001104659-15-010426: "ATK began trading as Orbital ATK under the symbol OA on the NYSE on February 10, 2015".

## 5. What happened
- ATK spun off Vista Outdoor on 2015-02-09 and Orbital merged into a subsidiary that day: [SEC 8-K 2015-02-13](https://www.sec.gov/Archives/edgar/data/866121/000110465915010426/a15-4204_18k.htm).
- Same filing (press release): ATK stock begins trading as Orbital ATK under OA on the NYSE at the open on 02-10; Orbital stops trading after the close on 02-09.
- Fails rows: ATK CUSIP 018804104 last row 20150213; OA CUSIP 68557N103 first row 20150213 (settlement dates).

## 6. Decision-tree bucket
Kept the same security (rename / ticker change). Not an ending.

## 7. Why the library got it wrong
The boundary tracks fails-file settlement dates (about T+3), not the 8-K's stated first trading day. Cause: other:ticker_boundary_from_fails_lag.

## 8. Fix and open checks
Where an 8-K states the day a new symbol began trading, use it as the OA start, with the previous trading day as the ATK end: 2015-02-10 and 2015-02-09. Not golden-worthy on its own (a few days of boundary). Open: why the new run moved the boundary four days earlier than the base run (not checked; the code was not read).

## 9. Verification
Upheld. Re-opened 8-K 0001104659-15-010426 (CIK 866121) through sec.py: "Following the Merger, ATK began trading as Orbital ATK under the symbol "OA" on the NYSE on February 10, 2015"; the merger and the name change closed on February 9, 2015 (Vista Outdoor began trading February 10). Same issuer and class (ATK common), so the ticker change is a rename of one security: ATK ends 2015-02-09, OA starts 2015-02-10. Both base ranges (02-16/02-17) and new ranges (02-12/02-13) differ from this, so "neither" holds. Not re-checked: the report's claim that Orbital stopped trading after the 02-09 close (not needed for the verdict). No missed_filing is claimed or needed.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (8-K 0001104659-15-010426: OA from 2015-02-10). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

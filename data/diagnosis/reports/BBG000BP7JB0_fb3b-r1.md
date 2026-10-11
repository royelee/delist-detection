# BBG000BP7JB0_fb3b-r1 (VIAV), regression, security_history.ranges

## 1. Verdict
JDS Uniphase renamed itself Viavi Solutions on 2015-08-01 and its stock began regular-way trading as VIAV on 2015-08-04, after the Lumentum spin-off. Same security, same CIK 912093. Neither run is exact: the old run (JDSU to 08-11, VIAV from 08-12) is 6 trading days late; the new run (JDSU to 08-06, VIAV from 08-07) is 3 days late but closer. The new one is the better of the two and still wrong.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| ticker range JDSU | 2007-12-17..2015-08-11 | ..2015-08-06 | JDSU through 2015-08-03 (VIAV regular-way starts 08-04) | both wrong, new nearer |
| ticker range VIAV | from 2015-08-12 | from 2015-08-07 | from 2015-08-04 | both wrong, new nearer |
| issuer | 912093 | 912093 | 912093 | agree |
| exit_kind | none | none | no ending (rename) | agree |

Fails rows: CUSIP 46612J507 (JDSU) rows 20150701..20150810; CUSIP 925550105 (VIAV) rows from 20150807. Fails rows are dated by settlement (T+3), so 08-07 is the settlement of 08-04 trades.

## 3. Corrected classification
```
exit_kind: (none)   continuation: false (no ending, a rename of the same security)
ticker ranges: JDSU 2007-12-17..2015-08-03 ; VIAV 2015-08-04..
event_type: rename (Lumentum spin-off 2015-08-01)   confidence: inferred
```

## 4. Why this confidence
inferred. The VIAV start rests on a filing: 8-K 0001104659-15-056495 states regular-way VIAV trading from August 4, 2015. JDSU's last day (08-03) is worked out as the day before. No exit kind, successor or payout applies.

## 5. What happened
- [SEC 8-K 2015-08-05](https://www.sec.gov/Archives/edgar/data/912093/000110465915056495/a15-16911_18k.htm): distribution of 80.1% of Lumentum at 12:01 a.m. 2015-08-01; name change from JDS Uniphase to Viavi Solutions effective 2015-08-01 (Item 5.03); "Viavi commenced regular-way trading on August 4, 2015 on NASDAQ under the ticker symbol VIAV"; ex-dividend date August 4.

## 6. Decision-tree bucket
Kept the same security (rename).

## 7. Why the library got it wrong
Ranges follow the fails rows, which lag trades by settlement; the VIAV start tracks the CUSIP's first fails row (08-07 new, 08-12 old) rather than the filing's 08-04. Cause: other:ticker_range_from_fails_lag.

## 8. Fix and open checks
Prefer the 8-K's stated first VIAV day (08-04) and end JDSU the day before. Old to new is an improvement (5 days closer). Not golden-worthy until the library reads the filing.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (VIAV regular-way from 2015-08-04; base 08-12, new 08-07). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

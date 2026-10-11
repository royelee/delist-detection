# BBG000TJM7F0 (KDP) - regression, fb3b round 1

## 1. Verdict
DPS was renamed Keurig Dr Pepper Inc. and traded as KDP from the merger date, 2018-07-09, on the same legal entity (CIK 1418135); it is a ticker change, not an ending. The new ranges (DPS to 2018-07-10, KDP from 2018-07-11) are much closer to the filings than the old ones (to 2018-07-15 / from 2018-07-16, FTD settling-tail dates), but neither is exactly 07-09; new is the better of the two.

## 2. Library vs evidence
| Field | old (side_a) | new (side_b) | evidence | status |
| --- | --- | --- | --- | --- |
| security_history.ranges | DPS to 2018-07-15, KDP from 2018-07-16 | DPS to 2018-07-10, KDP from 2018-07-11 | rename effective 2018-07-09; 424B3 of 07-10 cites a NYSE close under KDP | new closer; not exact |
| exit_kind / continuation / successor / value_rule / terms | none | none | no Form 25; same issuer continues | agree |
| issuer | 1418135 | 1418135 | same | agree |

FTD rows: CUSIP 49271V100 (KDP) first row 20180711; 26138E109 (DPS) last row 20180713. FTD rows lag the trade by settlement, so the old 07-15/07-16 boundary is a settling-tail artefact.

## 3. Corrected classification
```
exit_kind: (none)   drop_reason:   continuation: false   successor: (none)
last_trade_date: n/a (no ending)
value_rule: unknown   cash_per_share: null   stock_ratio: null   recovery_ratio: null
value_formula: n/a (ticker change, no row)
event_type: ticker_change   consideration: none   effective_date: 2018-07-09
ticker ranges: DPS to about 2018-07-08/09 ; KDP from 2018-07-09/10   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: none; rests on 8-K 0001104659-18-044357 (name change and merger effective 2018-07-09) - filing.
- successor: n/a.
- last trade date: n/a; the ticker boundary rests on the FY2018 10-K ("on July 9, 2018 ... changed its name ... and began trading under KDP") and the 424B3 of 2018-07-10. The exact first KDP session (07-09 vs 07-10, with due-bill trading around the $103.75 special dividend payable 07-10) is not stated in a filing read; a web summary said 07-10 (unconfirmed).
- payout rule / terms: n/a.
Missing for verified: an NYSE notice or 8-K stating the first KDP session.

## 5. What happened
- [SEC 8-K 2018-07-02](https://www.sec.gov/Archives/edgar/data/1418135/000110465918043578/a18-16312_18k.htm): at closing DPS is renamed KDP and will trade as KDP on NYSE.
- [SEC 8-K 2018-07-09](https://www.sec.gov/Archives/edgar/data/1418135/000110465918044357/a18-16509_3ex99d1.htm) (0001104659-18-044357): charter amendment and merger effective 2018-07-09.
- [SEC 424B3 2018-07-10](https://www.sec.gov/Archives/edgar/data/1418135/000104746918004946/a2236214z424b3.htm): common stock trades as KDP; NYSE close cited for 2018-07-10.
- [SEC 10-K FY2018](https://www.sec.gov/Archives/edgar/data/1418135/000141813519000007/kdp-10kx12312018.htm): began trading as KDP on the Merger Date.
- Special dividend $103.75, record 2018-07-06, payable 2018-07-10 (8-K 0001104659-18-044358): a distribution, not an ending.

## 6. Decision-tree bucket
Kept the same security (same issuer, rename).

## 7. Why the library got it wrong
The old base run counted the DPS CUSIP's settling-tail FTD rows as ticker sightings. The new run fixed most of it.

## 8. Fix and open checks
The boundary could still be tightened to the filing's 2018-07-09. Confirm the first KDP session. Not golden-worthy until the date is sourced.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right, from the filing it cites, and its ranges are exactly the new run's (checked against the case's sides); the confidence is inferred only because the switch day also rests on the fails rows (DPS to 2018-07-10, KDP from 2018-07-11).

# BBG000BP8Z50_fb3b-r1 (MSI) - regression, security_history.ranges

## 1. Verdict
Motorola, Inc. renamed itself Motorola Solutions, did a 1-for-7 reverse split and spun off Motorola Mobility, all effective 2011-01-04, and the common stock "will continue to trade on the NYSE under the new symbol MSI". The same security, so no delisting. Neither run is exactly right: the old run (MSI from 2011-01-07) is three days late, the new run (MSI from 2011-01-06) two days late; the filing points to MOT through 2011-01-03 and MSI from 2011-01-04. The new run is closer.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| security_history.ranges | MOT 2007-12-17..2011-01-06; MSI 2011-01-07.. | MOT ..2011-01-05; MSI 2011-01-06.. | MOT ..2011-01-03; MSI 2011-01-04.. (worked out, below) | both wrong; new nearer |
| issuer | CIK 68505 | CIK 68505 | same registrant renamed | agree |
| exit_kind / successor / value | none | none | no ending; same security | agree |

## 3. Corrected classification
```
exit_kind: (none)   continuation: n/a   successor: n/a
ticker_history: MOT 2007-12-17..2011-01-03 ; MSI 2011-01-04..
event_type: rename + reverse split + spin-off   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 0001104659-11-001040: same registrant renamed, shares "continue to trade on the NYSE").
- successor: n/a.
- last trade date: n/a.
- payout rule: n/a.
- terms: n/a.
The range boundary rests on worked out dating: the 8-K states the name change and reverse split effective 2011-01-04 (6:00 and 6:15 a.m.) with "the new symbol MSI", but not the first trading session under MSI explicitly. Fails rows under MSI (CUSIP 620076307) begin 2011-01-06 with a post-split price, consistent with a trade day of 2011-01-04 plus settlement lag. A filing or exchange notice stating the first MSI session would make it verified.

## 5. What happened
- [SEC 8-K 2011-01-10, Items 2.01/5.03](https://www.sec.gov/Archives/edgar/data/68505/000110465911001040/a11-1944_18k.htm): Distribution Date 2011-01-04; reverse split effective 6:00 a.m. ET 2011-01-04; name change to Motorola Solutions effective 2011-01-04; new CUSIP 620076 307; shares continue to trade on the NYSE under new symbol MSI.
- Fails rows: MSI/620076307 first row 2011-01-06; MOT/620076109 last row 2011-01-06 (old CUSIP settling tail).

## 6. Decision-tree bucket
Kept the same security (rename, reverse split; the spin-off is a distribution, not an ending).

## 7. Why the library got it wrong
The MSI start follows the first MSI fails row (a settlement date) rather than the trade day; the MOT tail on the old CUSIP (rows to 2011-01-06) is a settling tail, not trading. Cause: other:ticker_change_dated_by_fails_settlement_lag. The change moved the boundary two days earlier, in the right direction.

## 8. Fix and open checks
Date a ticker change from the filing's effective date when an 8-K 5.03 states it. Confirm the first MSI session from an exchange notice. Golden-worthy: yes (well sourced rename).

## 9. Verification
Skeptic check, security_history.ranges (right = neither): UPHELD.
- Re-read the cached 8-K 0001104659-11-001040 (CIK 68505): reverse split effective 6:00 a.m. ET and name change effective 6:15 a.m. ET on 2011-01-04, both before the open; "will continue to trade on the NYSE, under the new symbol MSI"; new CUSIP 620076 307. So MSI starts 2011-01-04 and MOT ends 2011-01-03.
- Fails check (offline): CUSIP 620076307 (MSI) first row 2011-01-06; CUSIP 620076109 (MOT) last row 2011-01-06. Fails rows are settlement-lagged, so they cannot date the first session; base (MSI from 01-07) and new (MSI from 01-06) both differ from 01-04, so "neither" holds. A rename is not an ending (reference.md), so no delisting.
- Caveat: the first MSI session is inferred from the effective time, not stated outright; confidence "inferred" is right. No missed_filing is claimed, none needed.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (MSI from 2011-01-04; base 01-07, new 01-06). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

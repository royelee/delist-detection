# BBG000BR14K5_fb3b-r1 (CB, regression, security_history.ranges)

## 1. Verdict
ACE Limited was renamed Chubb Limited and its shares began trading as CB on the NYSE on 2016-01-15 (the same security, the same FIGI and CIK 896159). Neither run is right on the ticker boundary: the old run has ACE to 2016-01-20 and CB from 2016-01-21; the new run has ACE to 2016-01-18 and CB from 2016-01-19. The new run is 2 days closer; the filing-supported ranges are ACE to 2016-01-14 and CB from 2016-01-15.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| security_history.ranges (ACE end) | 2016-01-20 | 2016-01-18 | 2016-01-14 (last day as ACE; rename effective 01-15) | both wrong; new closer |
| security_history.ranges (CB start) | 2016-01-21 | 2016-01-19 | 2016-01-15 | both wrong; new closer |
| issuer (896159) | agree | agree | same CIK throughout | agree |
| sec_id / exit | no ending | no ending | name change, no delisting | agree |

## 3. Corrected classification
```
ranges: ACE:2009-12-17..2016-01-14:896159 ; CB:2016-01-15..:896159
exit_kind: (none; rename, not an ending)
```

## 4. Why this confidence
inferred. The ticker change date rests on a filing (8-K 0001193125-16-430900 states CB trading began 2016-01-15). The library's boundary comes from fails rows (the new CUSIP H1467J104's first row is 2016-01-19, the old CUSIP H0023R105's last is 2016-01-20), which are settlement-dated and lag trading; no fails evidence gives the exact trading day, so the exact boundary is a filing date, not reproducible from fails rows alone.

## 5. What happened
- [SEC 8-K 2016-01-15, Item 2.01](https://www.sec.gov/Archives/edgar/data/896159/000119312516430900/d113231d8k.htm): merger with Chubb Corp effective 5:30 p.m. EST 2016-01-14; "on January 15, 2016, the Registrant was renamed Chubb Limited and its common shares ... commenced trading on the New York Stock Exchange under the ticker symbol 'CB'."
- Fails rows (offline): CUSIP H0023R105 ACE rows 20160104..20160120; H1467J104 CB rows from 20160119 (settlement lag).
- The old Chubb Corp CUSIP 171232101 under CB ends 20160107 (a different security, not this sec_id).

## 6. Decision-tree bucket
Kept the same security (a rename).

## 7. Why the library got it wrong
The ticker boundary is derived from fails-row sightings, which settle days after trading; the new run's first-row rule moved it earlier by 2 days but not to the filing's date. Cause: other:ticker_range_boundary_from_settlement_lagged_fails_rows.

## 8. Fix and open checks
A rename's date should come from the filing when an 8-K states it (the line follow's text). Low priority: 2-4 days of ticker coverage. The regression is a move toward the right answer, not a loss.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (8-K: CB from 2016-01-15; base 01-21, new 01-19, the next session after the holiday). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

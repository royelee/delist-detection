# BBG000BFRF55 (CLF) regression, round 2: security_history.ranges

## 1. Verdict
Cleveland-Cliffs only renamed itself to Cliffs Natural Resources (effective 2008-10-15) and kept ticker CLF and its listing, so there is no ending and no ticker break. The new range `CLF:2007-12-18..` (side_b) is right; the old one, with a one-day `CLFZZZZ` range on 2008-10-15, was wrong.

## 2. Library vs evidence
| Field | Library says (old / new) | Evidence says | Status |
| --- | --- | --- | --- |
| security_history.ranges | old: CLF 2007-12-18..2008-10-14, CLFZZZZ 2008-10-15, CLF 2008-10-16..; new: CLF 2007-12-18.. | one ticker CLF throughout; ZZZZ is SEC's placeholder for a new CUSIP's first fails row | new agrees |
| exit_kind / continuation / successor | none | name change only, no Form 25 | agree |
| last_trade_date, value_rule, terms | none | not an exit | agree |
| issuer | 764065 | Cleveland-Cliffs / Cliffs Natural Resources, CIK 764065 | agree |
| ticker_history | new: CLF continuous | CLF before and after (fails rows 20081016+ under CLF, CUSIP 18683K101) | agree |

## 3. Corrected classification
```
exit_kind: (none)   drop_reason:   continuation: n/a   successor:   last_trade_date:
value_rule: unknown (no ending, no payout)
event_type: name_change   consideration: none   holder_value: same shares   effective_date: 2008-10-15
successor_ticker: CLF   confidence: verified
security_history.ranges: CLF:2007-12-18..:764065
```

## 4. Why this confidence
verified.
- exit kind: not an exit; 8-K 5.03 (0001299933-08-004746) is a name change.
- successor: none needed.
- last trade date: none (no ending).
- payout rule: none.
- terms: none.

## 5. What happened
- [SEC 8-K 2008-10-09, item 5.03](https://www.sec.gov/Archives/edgar/data/764065/000129993308004746/htm_29377.htm): name changed from Cleveland-Cliffs Inc to Cliffs Natural Resources Inc, effective 2008-10-15.
- Fails rows: CUSIP 185896107 under CLF to 20081014; CUSIP 18683K101 under CLFZZZZ on 20081015 (1 row, $0.01), then under CLF from 20081016 (46 rows). The ticker never changed.

## 6. Decision-tree bucket
Kept the same security (rename; a new CUSIP from the name change; same ticker).

## 7. Why the library got it wrong (base run)
The base run read the first-day CLFZZZZ fails row as a ticker sighting. Fixed by `ftd.is_unassigned_symbol` and the filter in `history.ticker_sightings` (commit 4cc898c). Cause: other:zzzz_first_day_symbol_counted_as_ticker (already fixed).

## 8. Fix and open checks
None; the current run is right. Keep as a regression guard; a golden case is optional.

## 9. Verification
Upheld. Re-opened the cached 8-K 0001299933-08-004746: Item 5.03, name changed from Cleveland-Cliffs Inc to Cliffs Natural Resources Inc, effective October 15, 2008; no Form 25 or listing change. `ftd.is_unassigned_symbol` treats a symbol over 4 characters ending in ZZZZ as a new CUSIP's pre-assignment placeholder, so CLFZZZZ is not a ticker. The current output has one CLF range from 2007-12-18 for BBG000BFRF55 and no delisting row for it. security_history.ranges: new is right.

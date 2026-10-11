# BBG00333FYS2_fb3b-r1 (IQV, regression, security_history.ranges)

## 1. Verdict
Quintiles IMS Holdings renamed itself IQVIA Holdings and changed its NYSE ticker Q to IQV with a new CUSIP; this is a rename, not an ending. Neither run's ranges are right: the 8-K says IQV starts on 2017-11-15 (Q's last day 2017-11-14); the old run (IQV from 11-16) is one day late, the new run (IQV from 11-21) is six days late.

## 2. Library vs evidence
| Field | Library says (old / new) | Evidence says | Status |
| --- | --- | --- | --- |
| exit_kind / drop_reason / continuation / successor | none (no row) | rename, no ending | agree |
| last_trade_date | none | n/a | agree |
| value_rule / terms | none | n/a | agree |
| issuer | CIK 1478242 throughout | same registrant (name change only) | agree |
| ticker_history | old: Q ..2017-11-15, IQV 2017-11-16.. ; new: Q ..2017-11-20, IQV 2017-11-21.. | Q ..2017-11-14, IQV 2017-11-15.. | wrong (both; old nearer) |

## 3. Corrected classification
```
exit_kind: (none)   drop_reason:    continuation: false   successor: none   last_trade_date: n/a
value_rule: unknown (no ending)   cash_per_share:    cash_currency:    stock_ratio:
price_ticker:   price_sec_id:   price_date:   recovery_ratio:   value_formula:
event_type: ticker_rename   consideration: none   holder_value: same shares
effective_date: 2017-11-15   successor_ticker:   confidence: inferred
ranges: Q:2013-05-14..2017-11-14:1478242;IQV:2017-11-15..:1478242
```

## 4. Why this confidence: inferred
- exit kind: filing (8-K 0001193125-17-335879, item 5.03 name change, no ending).
- successor: filing (same registrant, same sec_id).
- last trade date: not applicable.
- payout rule / terms: not applicable.
- ticker dates: the 8-K states in advance that shares "will commence trading" as IQV on November 15, 2017; fails rows show IQV from 2017-11-16 and Q (old CUSIP 74876Y101) rows to 2017-11-17 (settling tail). No filing states the actual first IQV session. A confirming source would be an NYSE notice or a post-event filing.

## 5. What happened
- Name change from Quintiles IMS Holdings to IQVIA Holdings effective 2017-11-06; bylaw requirement of symbol "Q" removed. [SEC 8-K 2017-11-07](https://www.sec.gov/Archives/edgar/data/1478242/000119312517335879/d484556d8k.htm)
- Same 8-K: "On November 15, 2017, shares of the Company will commence trading under a new NYSE ticker symbol, IQV, and a new CUSIP number, 46266C 105."
- Fails rows: IQV (46266C105) first row 2017-11-16; Q (74876Y101) rows 2017-11-15..17 only (settling tail of trades through 11-14). [SEC fails]

## 6. Decision-tree bucket
Kept the same security (same registrant and holders, name and CUSIP change only); not an ending.

## 7. Why the library got it wrong
The ranges follow the fails sightings (first IQV fails row, last Q fails row), not the filing's stated start date. The old run took IQV's first fails row (11-16); the new run lets Q's settling-tail rows (to 11-17 and later) count as sightings, pushing IQV to 11-21. Cause: other:ticker change date from fails sightings instead of the 8-K's stated date.

## 8. Fix and open checks
Use the 8-K item 5.03 stated start date (2017-11-15) for the change when a filing states it. Open: the actual first IQV session (NYSE notice). Not golden-worthy (date unconfirmed by a post-event source).

## 9. Verification
Skeptic re-check through sec.py. Upheld: security_history.ranges = neither.
- Re-opened 8-K 0001193125-17-335879 (CIK 1478242): item 5.03 states "On November 15, 2017, shares of the Company will commence trading under a new NYSE ticker symbol, IQV, and a new CUSIP number, 46266C 105." Name change effective 2017-11-06, same registrant, no ending.
- Fails check: 46266C105 (IQV) first row 20171116 (16 rows to 20171228); 74876Y101 (Q) only 3 rows, 20171115..20171117. Q rows on 11-15..17 are T+2 settlement of trades through 11-14, so they do not show Q trading after 11-14. IQV's first fails row is the day after the first session, consistent with IQV from 11-15.
- Old run (IQV 11-16, Q to 11-15) is one day late; new run (IQV 11-21, Q to 11-20) is six days late. Neither equals Q..11-14 / IQV 11-15... Verdict survives.
- Caveat (already in section 4): the 8-K is forward-looking, so the exact first session stays inferred, not confirmed.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: this report read the regression's two sides the wrong way round (side_a is the base, commit 006e194; side_b the batch 3 run). neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (8-K: IQV from 2017-11-15; base 2017-11-21, new 2017-11-16). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

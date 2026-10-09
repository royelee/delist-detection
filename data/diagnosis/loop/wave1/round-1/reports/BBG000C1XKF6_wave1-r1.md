# BBG000C1XKF6 (PNFP) wave1-r1, regression

## 1. Verdict
Old Pinnacle Financial Partners (CIK 1115055) merged with Synovus on 2026-01-01 through a holding company (Steel Newco, renamed Pinnacle Financial Partners, Inc.). Its common stock last traded 2025-12-31, so the new range end (2025-12-31) is right and the old end (2026-01-02) was wrong; the library's continuation row is otherwise right.

## 2. Library vs evidence
| field | library says | evidence says | status |
| --- | --- | --- | --- |
| security_history.ranges | old: PNFP 2007-12-21..2026-01-02; new: ..2025-12-31 | last trade 2025-12-31 (Jan 1 holiday, closing Jan 1); new CUSIP trades from Jan 2 | new right |
| exit_kind | exchange, continuation true, successor BBG01Z7V4LL1 | one Pinnacle share became one Newco share, no cash | agree |
| last_trade_date | blank (closing_day, unconfirmed) | 2025-12-31 worked out | agree (unpublished) |
| value_rule | continuation | continuation | agree |
| issuer | 1115055 | 1115055 | agree |

## 3. Corrected classification
```
exit_kind: exchange   drop_reason:    continuation: true   successor: BBG01Z7V4LL1
last_trade_date: 2025-12-31 (worked out, not published)
value_rule: continuation  cash: -  stock_ratio: 1 (Newco)  value_formula: n/a (continuation)
event_type: reorganization (merger of equals via holdco)  confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 0001115055-26-000002, item 2.01/3.03: each share converted into one Newco share).
- successor: filing (same 8-K, Newco renamed Pinnacle Financial Partners) plus fails rows (new CUSIP 72348N109 PNFP from 2026-01-05).
- last trade date: worked out from fails rows (old CUSIP last row 2026-01-02 priced 12-31) and closing on Jan 1 (market holiday); the 8-K states closing and suspension request but no last-trade day.
- payout rule: filing (one for one).
- terms: filing.
Not backed by a filing: the exact last trade day; an exchange print would settle it.

## 5. What happened
- Closing 2026-01-01; Pinnacle asked Nasdaq to suspend trading and file Form 25 on 2026-01-02 [SEC 8-K 2026-01-02](https://www.sec.gov/Archives/edgar/data/1115055/000111505526000002/pnfp-20260102.htm).
- Each Pinnacle share became one Newco share (same 8-K).
- 25-NSE/A filed 2026-01-02 [SEC](https://www.sec.gov/Archives/edgar/data/1115055/000135445726000001/xslF25X02/primary_doc.xml).
- Fails rows: old CUSIP 72346Q104 last row 2026-01-02 at 95.41; new CUSIP 72348N109 from 2026-01-05.

## 6. Decision-tree bucket
Replaced 1:1 by a new line of the same holders: continuation.

## 7. Why the library differs
The base run ended the range at 2026-01-02 (last fails row date, or the filing date); the new run uses the closing-day rule (Jan 1 holiday, trading day before = Dec 31). Cause: other:range end moved to the closing-day estimate; new is correct.

## 8. Fix and open checks
None needed. Confirm by an exchange print that 2025-12-31 was the last session. Not golden-worthy.

# BBG00B3T3HD3_fb3-r1 (AA, Alcoa Corp), mode: regression

## 1. Verdict
BBG00B3T3HD3 is Alcoa Corp (CIK 1675149), spun off from Alcoa Inc. on 2016-11-01. The new ticker range `AA:2016-11-03..:1675149` is right. The base range (`AA:2007-12-19..2016-06-30` under CIK 4281, then CIK 1675149 from 2016-07-01) wrongly gave this FIGI the history of Alcoa Inc. (now Arconic/Howmet, a different security and CUSIP). The new row is the better one.

## 2. Library vs evidence
| field | old (base run) | new (this run) | evidence | status |
| --- | --- | --- | --- | --- |
| security_history.ranges | AA 2007-12-19..2016-06-30 CIK 4281; AA 2016-07-01.. CIK 1675149 | AA 2016-11-03.. CIK 1675149 | Alcoa Corp 8-K 2016-11-01 (0001193125-16-755437): separation of Alcoa Inc. completed, "The Company is now an independent public company and its common stock is listed under the symbol AA on the New York Stock Exchange"; parent renamed Arconic Inc. (8-K 0001193125-16-755445 of CIK 4281, items 5.03/8.01). Alcoa Corp's filings before that are Form 10 amendments, Forms 3 and S-1; no listed stock. Fails: CUSIP 013872106 (ALCOA UPSTREAM CORP) first row 2016-11-03; old CUSIP 013817101 (ALCOA INC) rows end 2016-10-07. | new right |

The CIK-4281 span and 2016-07-01..2016-10-31 belong to Alcoa Inc. (or a not-yet-trading entity). The new range start is the first fails row; settlement lags the 2016-11-01 regular-way start by about two days (a data-edge effect).

## 3. Corrected classification
```
exit_kind: (no ending; no delisting row)
drop_reason: -
continuation: false
successor: -
last_trade_date: -
value_rule: - (not an exit)
event_type: spin-off listing (new security)
consideration: none
effective_date: 2016-11-01
successor_ticker: -
ticker_history: AA 2016-11-03.. (CIK 1675149, common, CUSIP 013872106)
confidence: inferred
```

## 4. Why this confidence
inferred: the only unbacked item is the exact range start day.
- exit kind: none; rests on filing (Alcoa Corp 8-K 0001193125-16-755437).
- successor: none.
- last trade date: none.
- payout rule: none.
- terms: none.
- range start 2016-11-03: fails rows; the 8-K shows AA listed as of 2016-11-01. A filing or exchange print stating the first regular-way day would make it verified.

## 5. What happened
- [SEC 8-K 2016-11-01 Alcoa Corp](https://www.sec.gov/Archives/edgar/data/1675149/000119312516755437/d281837d8k.htm): separation completed; AA listed on NYSE; Alcoa Inc. renamed Arconic Inc.
- [SEC 8-K 2016-11-01 CIK 4281](https://www.sec.gov/Archives/edgar/data/4281/000119312516755445/d273759d8k.htm): items 5.03, 8.01 (parent's name change).
- Fails rows (SEC): CUSIP 013872106 30 rows 2016-11-03..2016-12-29; CUSIP 013817101 last rows 2016-10-04..10-07.

## 6. Decision-tree bucket
Not an ending. Alcoa Corp is a new security that did not exist as a listed security before Nov 2016, so the 2007-2016 history under CIK 4281 is another security's.

## 7. Why the library got it wrong
The base run attached Alcoa Inc.'s observed AA history from 2007-12-19 to this FIGI and to CIK 4281 (base-run cause: identity_wrong / issuer_history_bug). This run drops it. Nothing is wrong now.

## 8. Fix and open checks
None for the new row. Separately, confirm the Alcoa Inc. 2007-2016 AA history sits on Arconic's own FIGI (out of scope here). Golden-worthy: no.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (Alcoa Corp's own AA range from 2016-11-03; Alcoa Inc's history left it).

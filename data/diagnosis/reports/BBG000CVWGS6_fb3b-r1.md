# BBG000CVWGS6 (ATVID / ATVI, Activision Blizzard) - regression, fb3b round 1

## 1. Verdict

Only the 2008 ticker ranges changed; the 2023 Microsoft cash merger row is unchanged and right. Neither the old nor the new ranges are right: ATVID was the ticker of the new CUSIP 00507V109 continuously from 2008-07-11 through 2008-08-07, and the "ATVI" days in between are an old-CUSIP settling tail. The new value is one day closer (ATVI ends 07-30 instead of 07-31) but is still wrong.

## 2. Library vs evidence

| Field | Library says (old -> new) | Evidence says | Status |
| --- | --- | --- | --- |
| `security_history.ranges` | old: ATVI 07-21..07-31, ATVID 08-01..08-07. new: ATVI 07-21..07-30, ATVID 07-31..08-07 (both after ATVID 07-11..07-20) | ATVID 2008-07-11..2008-08-07 unbroken, ATVI from 2008-08-08 | wrong (both) |
| `exit_kind` | merger | merger (Microsoft, $95.00 cash) | agree |
| `drop_reason` / `continuation` / `successor` | blank / false / none | same | agree |
| `last_trade_date` | 2023-10-12 (midas) | merger closed 2023-10-13; 25-NSE effective 2023-10-13 | agree |
| `value_rule` | cash_only (dlret method) | cash | agree |
| `terms` | $95.00 USD (not changed by this regression) | $95.00 cash per share | agree |
| `issuer` | CIK 718877 | same | agree |
| `ticker_history` | see first row | see first row | wrong |

Evidence for the ranges:
- Fails rows, new CUSIP 00507V109 (Activision Blizzard): symbol ATVID on every listed day 2008-07-11 .. 2008-08-07 (07-11, 14, 15, 17, 18, 21, 22, 25, 29, 30, 31, 08-01, 04, 05, 06, 07), symbol ATVI from 2008-08-08. Fails files list only days with fails, so the gaps are not absence of trading.
- Fails rows, old CUSIP 004930202 (Activision Inc): ATVI until 2008-07-10, then from 07-21 to 07-31 a constant quantity of 103800 shares on every day, a stale fail balance (a settling tail), not trading in a live line.
- [SEC 8-K 2008-07-31](https://www.sec.gov/Archives/edgar/data/718877/000110465908048923/a08-20484_18k.htm): press release dated July 31, 2008 says "Activision Blizzard, Inc. (Nasdaq: ATVID)".
- [SEC 8-K 2008-08-15](https://www.sec.gov/Archives/edgar/data/718877/000110465908053427/a08-21530_28k.htm): "(Nasdaq: ATVI)" by then, consistent with the 08-08 switch seen in the fails rows.

## 3. Corrected classification

```
exit_kind: merger
drop_reason:
continuation: false
successor: none
last_trade_date: 2023-10-12
value_rule: cash
cash_per_share: 95.00
cash_currency: USD
stock_ratio:
price_ticker:
price_sec_id:
price_date:
recovery_ratio:
value_formula: 95.00 / last_close - 1
event_type: acquisition
consideration: cash
holder_value: 95.00 USD cash per share
effective_date: 2023-10-13
successor_ticker:
confidence: verified for the merger; inferred for the 2008 ranges
ticker_history: ATVI 2008-01-03..2008-07-10; ATVID 2008-07-11..2008-08-07; ATVI 2008-08-08..2023-10-12
```

## 4. Why this confidence

Confidence: inferred (the case's one changed field, the 2008 ticker ranges, rests on fails rows plus a press-release symbol).
- exit kind: filing, [8-K 2023-10-13 item 2.01/3.01](https://www.sec.gov/Archives/edgar/data/718877/000110465923108985/tm2328253d1_8k.htm) and 25-NSE 0001354457-23-000768.
- successor: filing, same 8-K; Activision survived as a Microsoft subsidiary, no successor line.
- last trade date: worked out, merger closed 2023-10-13 per the 8-K, so the last session is 10-12; library's MIDAS print agrees.
- payout rule: filing, 8-K 2023-10-13 ("right to receive $95.00 in cash").
- terms: filing, same 8-K.
- ticker ranges: fails rows (CUSIP 00507V109 symbol per day) and the 2008-07-31 8-K press release. Not backed by an exchange symbol-change notice; a Nasdaq notice of the ATVID to ATVI change on 2008-08-08 would make it verified.

## 5. What happened

- Activision/Vivendi Games combination closed July 9, 2008; the new registrant got a new CUSIP and the Nasdaq symbol ATVID ([8-K 2008-07-31](https://www.sec.gov/Archives/edgar/data/718877/000110465908048923/a08-20484_18k.htm); [8-K 2008-07-15](https://www.sec.gov/Archives/edgar/data/718877/000110465908045739/a08-18354_18k.htm) items 2.01, 5.01, 5.03).
- Symbol returned to ATVI on 2008-08-08 (fails rows).
- Microsoft merger closed 2023-10-13 at $95.00 cash per share; Nasdaq filed 25-NSE the same day ([8-K](https://www.sec.gov/Archives/edgar/data/718877/000110465923108985/tm2328253d1_8k.htm)).

## 6. Decision-tree bucket

Replaced by cash of another company (2023). The 2008 CUSIP change is a ticker/CUSIP change within the same registrant line and not an ending.

## 7. Why the library got it wrong

The ranges are built from fails sightings; the old CUSIP's stale ATVI rows (07-21..07-31) still count as ATVI sightings next to the new CUSIP's ATVID rows, and the commit f56ff50 fix (an old CUSIP's settling tail is no ticker sighting once the new CUSIP began) trims only the 07-31 day, not 07-21..07-30. Cause: other:old-CUSIP tail still read as ticker sightings for 07-21..07-30 (a day-level tie-break between two CUSIPs' rows on the same date).

## 8. Fix and open checks

- On a day when the new CUSIP has a row, the old CUSIP's rows must not set the ticker; better, drop the old CUSIP's sightings entirely once the new CUSIP's first row (2008-07-11) exists. Expected ranges are in section 3.
- Open: a Nasdaq trader notice for the ATVID/ATVI symbol change. Not needed for the delisting row.
- Golden-worthy: yes, as a ticker-history case (dates and CUSIPs well sourced).

## 9. Verification

Skeptic result: the `neither` verdict on `security_history.ranges` is NOT upheld.

- The day-by-day claim rests on "fails rows" (ATVID every listed day 2008-07-11..08-07 under CUSIP 00507V109; constant 103800 stale fails on the old CUSIP). I could not reproduce them. SEC's fails-to-deliver index (https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data) lists files only from cnsfails200907a.zip onward; cnsfails200807a/b and 200808a return 404, and `cache/sec_data/ftd/` also starts at 200907a. The report names no file holding the 2008 rows.
- Re-opened the cited 8-Ks. The 2008-07-31 8-K body (a08-20484_18k.htm) has no ticker text; the press release is in exhibit a08-20484_1ex99d1.htm: "July 31, 2008 - Activision Blizzard, Inc. (Nasdaq: ATVID)". The 2008-08-15 exhibit (a08-21530_2ex99d1.htm) says "(Nasdaq: ATVI)". So the filings show only ATVID on 07-31 (which agrees with the new value and contradicts the old value's ATVI on 07-31) and ATVI by 08-15.
- Days 07-21..07-30 and the 08-08 switch are neither confirmed nor refuted, so "wrong (both)" and the "old-CUSIP tail" cause are unsupported. Status should be unverified. Missing: a reproducible 2008 fails source or a Nasdaq notice dating the symbol changes.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found: both runs keep a wrong ATVI range inside ATVID's 2008-07-11..08-07, and the new run's is one day shorter (ATVID from 2008-07-31, not 08-01). The 2023 Microsoft merger row is right in both.

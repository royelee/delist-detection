# BBG000BVK2W6_5b-r1 (Tribune Co, TRB) - regression

## 1. Verdict
Tribune Company's common stock was cashed out at $34.00 per share in the ESOP going-private merger completed 2007-12-20 and was suspended from the NYSE at the close that day. The new run's added merger ending and its removal of the TRB 2007-12-20..2009-06-08 range are both right; the base run was wrong to keep a listed range alive to 2009.

## 2. Library vs evidence (both sides)
| Field | Old (base) | New (now) | Evidence | Right |
| --- | --- | --- | --- | --- |
| delistings.added (exit_kind, last_trade, value_rule) | no ending row | merger, no drop, not continuation, 2007-12-20, cash | merger paid $34.00 cash; suspended as of close 2007-12-20 | new |
| exit_kind | none | merger | 8-K items 2.01/3.03/5.01: shares cancelled for $34.00 cash | new |
| last_trade_date | none | 2007-12-20 | 8-K 3.01: suspended "effective as of the close of market on December 20, 2007" | new |
| value_rule / terms | none | cash 34.00 (currency blank) | $34.00 USD, no stock leg | new (add currency USD) |
| successor | none | none | Tribune survived, owned by the ESOP; holders got cash, not a continuation | agree |
| security_history.ranges | TRB 2007-12-20..2009-06-08 | removed | the line ceased trading 2007-12-20; later TRB sightings (2008-01-16..2009-06-08 in observations) are stale snapshots, status after_delisting | new |
| issuer | 726513 | 726513 | Tribune Co | agree |
| ticker_history | TRB to 2009-06-08 | no row | TRB true to 2007-12-20; no observation before the end exists, so no row can be built from observations | new (a TRB range ending 2007-12-20 would be ideal, not required) |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor: none
last_trade_date: 2007-12-20
value_rule: cash
cash_per_share: 34.00
cash_currency: USD
stock_ratio:
price_ticker:
price_sec_id:
price_date:
recovery_ratio:
value_formula: 34.00 USD / last_close - 1
event_type: going_private (ESOP merger, Zell/Tribune)
consideration: cash
holder_value: 34.00 USD cash per share
effective_date: 2007-12-20
successor_ticker:
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0000898822-07-001492 (items 2.01, 3.01, 3.03, 5.01).
- successor: filing, same 8-K: Tribune survived as ESOP-owned, holders paid cash; none.
- last trade date: filing, same 8-K Item 3.01 (suspension effective at the close on 2007-12-20); Form 25-NSE 0000876661-07-000963 filed 2007-12-21.
- payout rule: filing, same 8-K: cancelled and converted into the right to receive $34.00.
- terms: filing, same 8-K: $34.00, no stock leg.

## 5. What happened
- [SEC 8-K 2007-12-28](https://www.sec.gov/Archives/edgar/data/726513/000089882207001492/tribune8krevised.htm): merger completed 2007-12-20 at 12:02 p.m. EST; each share converted into $34.00 cash; Tribune became wholly owned by the ESOP.
- Same 8-K Item 3.01: NYSE asked to suspend trading effective as of the close on 2007-12-20 and file Form 25.
- [SEC Form 15-12B 2007-12-20](https://www.sec.gov/Archives/edgar/data/726513/000089882207001467/tribuneform15.htm) and [Form 25-NSE 2007-12-21](https://www.sec.gov/Archives/edgar/data/726513/000087666107000963/xslF25X02/primary_doc.xml), NYSE, Common Stock (rule 12d2-2(b)); a second 25-NSE 0000876661-07-000968 the same day.
- Observations of TRB from 2008-01-16 to 2009-06-08 all post-date the end.

## 6. Decision-tree bucket
Replaced by cash of another entity (the ESOP's merger sub): merger, not a continuation.

## 7. Why the library got it wrong
The base run found no ending (continued filings; Tribune kept filing after the merger because of its public debt), so it left a TRB range running to 2009. The 5b Form 25 reach rules now find the 25-NSE. Cause: other:base_missed_form25 (fixed by 5b; the new row is right).

## 8. Fix and open checks
- Add cash_currency USD (currency_missing).
- Optional: backfill a TRB range up to 2007-12-20 from fails-to-deliver rows.
- Golden worthy: yes, well sourced by one 8-K.

## 9. Verification
Upheld. Re-opened 8-K 0000898822-07-001492 through sec.py. Items 3.01 and 5.01 confirm the merger closed 2007-12-20, each share became $34.00 cash, and the NYSE suspension was requested effective as of the close on 2007-12-20. Form 25-NSE 0000876661-07-000963 (filed 2007-12-21) is the one the new row cites. No stock leg, no successor line. A TRB range running to 2009-06-08 cannot stand after a cash-out that ended trading on 2007-12-20, so removing it is right. Both "new" verdicts survive; the cash_currency gap is a separate open check.

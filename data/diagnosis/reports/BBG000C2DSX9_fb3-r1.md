# BBG000C2DSX9_fb3-r1 (CG, Loews Corp - Carolina Group stock), regression mode

## 1. Verdict
Loews redeemed all 108,478,429 Carolina Group shares on 2008-06-10 at 9:00 a.m. for the same number of Lorillard (LO) shares, one for one, and filed a Form 25 the same day. This is a real terminal ending valued as Lorillard stock. The new run is right: it adds the ending (merger, stock, LO ratio 1.0) and ends the ticker range in 2008 instead of 2009-06-08. The only gap is the blank last trade date.

## 2. Library vs evidence
| Field | Old (base) | New (library now) | Evidence says | Right |
| --- | --- | --- | --- | --- |
| delistings.added (contract row) | no row | merger, stock, ratio 1.0, price LO, last_trade blank | an ending exists: Carolina Group stock redeemed for LO stock 1:1 | new |
| security_history.ranges | CG 2008-01-04..2009-06-08 | CG 2008-01-04..2008-06-20 | stock ceased to exist 2008-06-10 (0 shares outstanding); no CG trading after 2008-06-09 | new |
| exit_kind | none | merger | replaced by another company's stock (Lorillard), not a continuation | agree (new) |
| successor | none | none | Lorillard is not a security of the run; no successor link | agree |
| last_trade_date | n/a | blank | 2008-06-09 worked out: redemption at 9:00 a.m. June 10, before the open; last fails row 2008-06-09 | missing |
| value_rule / terms | n/a | stock, 1.0 x price(LO) | 1 LO share per CG share (108,478,429 for 108,478,429) | agree |
| issuer | CIK 60086 | CIK 60086 | Loews Corp | agree |
| ticker_history | to 2009-06-08 | to 2008-06-20 | ends 2008-06-09 (last trade); 06-20 is the Form 25 effective date | new closer, not exact |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor: (none)
last_trade_date: 2008-06-09
value_rule: stock
cash_per_share:
cash_currency:
stock_ratio: 1.0
price_ticker: LO
price_sec_id: (Lorillard, not in run)
price_date: 2008-06-10 (first LO session; to be confirmed)
recovery_ratio:
value_formula: 1.0 x price(LO, price_date) / last_close - 1
event_type: split-off redemption (exchange of tracking stock for Lorillard shares)
consideration: stock
holder_value: 1 Lorillard share per Carolina Group share
effective_date: 2008-06-10
successor_ticker: LO
confidence: inferred
```

## 4. Why this confidence: inferred
- exit kind: filing (Loews 8-K 2008-06-10, items 2.01 and 3.01, 0001193125-08-131150).
- successor: none; the filing states Lorillard shares were distributed, so no continuation.
- last trade date: worked out from the 9:00 a.m. June 10 redemption plus fails rows ending 2008-06-09; no filing states the last trading day.
- payout rule: filing (same 8-K).
- terms: filing, 108,478,429 LO for 108,478,429 CG shares.

Not backed: the exact last trade date. An exchange print or NYSE notice stating the last day would make it verified. The Lorillard price date is not read from a filing either.

## 5. What happened
- Loews 8-K filed 2008-06-10: distributed 108,478,429 Lorillard shares in exchange for and redemption of all 108,478,429 Carolina Group shares as of 9:00 a.m. on June 10, 2008 [SEC 8-K](https://www.sec.gov/Archives/edgar/data/60086/000119312508131150/d8k.htm).
- Same 8-K, Item 3.01: zero shares remain; Form 25 filed to delist from NYSE.
- Form 25 filed 2008-06-10, rule 12d2-2(c), voluntary by the issuer [SEC Form 25](https://www.sec.gov/Archives/edgar/data/60086/000119312508131145/d25.htm).
- Form 15-12B filed 2008-06-23 [SEC](https://www.sec.gov/Archives/edgar/data/60086/000119312508138040/d1512b.htm).
- Fails rows for CUSIP 540424207 (CG) run 2008-01-04 to 2008-06-09, last row at $72.85 (local fails data).

## 6. Decision-tree bucket
Replaced: holders surrendered a tracking stock and received the stock of a different company, so a merger-type terminal event valued as stock.

## 7. Why the library got it wrong
Base: no ending found, so the range ran to 2009-06-08 (an unclipped guess; cause `continued_filings_guess`). Now the Form 25 and 8-K 2.01 produce a merger with stock terms. Remaining defect: `no_last_trade_date`, so the gate has no close (`terms_gate_failed:no_last_close`) and the value stays blank until qlib_practice supplies prices.

## 8. Fix and open checks
- Publish last_trade_date 2008-06-09 if a rule can read "redeemed at 9:00 a.m. on D" as the trading day before D.
- Confirm LO's first trading day for price_date (not a price).
- Possible golden case after the date is fixed.

## 9. Verification
Skeptic re-read of Loews 8-K 0001193125-08-131150 (via sec.py) and the CG fails rows. Both field verdicts upheld.
- delistings.added: Item 2.01 states 108,478,429 Lorillard shares were distributed in exchange for and redemption of all 108,478,429 outstanding Carolina Group shares as of 9:00 a.m. June 10, 2008; Item 3.01 follows. Another company's stock replaced the tracking stock, so a merger-type row valued as stock is right. The blank last_trade_date is a gap in the new row, not a reason to prefer "no row" (the base).
- security_history.ranges: the stock ceased to exist on 2008-06-10; CUSIP 540424207 fails rows run 2008-01-04..2008-06-09 (28 rows, last $72.85). The base's end of 2009-06-08 is refuted; the new end 2008-06-20 is closer, though not exact (06-09 is the last trade).
- Not refuted: no counter-evidence found. Upheld.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new merger row valued as stock (Carolina Group redeemed for Lorillard shares on 2008-06-10) and its 2008 range end right where the base had no ending; the blank last trade (2008-06-09) is a gap in the new row.

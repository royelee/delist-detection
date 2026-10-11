# BBG000B9WH86_fb3-r1 (AA, Alcoa Inc)

## 1. Verdict
Alcoa Inc (CIK 4281) was not delisted. On 2016-11-01 it separated Alcoa Corporation (new CIK, took the symbol AA) and kept filing as Arconic Inc., trading as ARNC on the NYSE (later Howmet, HWM). It is a rename plus ticker move, a continuation. The new row (`exchange`, `transfer`, no successor, no last trade date) has the wrong shape: there is no Form 25, and the successor is the same issuer's ARNC line (BBG00DYNJGH9). Having no row (base) was also wrong, but closer to harmless.

## 2. Library vs evidence
| field | library says | evidence says | status |
|---|---|---|---|
| delistings.added (row exists) | new: row `exit_kind=exchange`, `value_rule=transfer`, no successor | no Form 25 or 25-NSE for CIK 4281 in the 2016-09..12 filing list; 8-K 2016-11-04 says the Company "trades under the symbol ARNC on the NYSE" | wrong (neither old nor new: should be a continuation to BBG00DYNJGH9) |
| exit_kind | exchange | continuation of the same issuer (rename; 8-K 2016-11-01 filed under the name Arconic Inc.) | wrong |
| successor | blank (`successor_unknown`) | BBG00DYNJGH9 (ARNC, same CIK 4281) | missing |
| last_trade_date | blank, unconfirmed | fails rows: CUSIP 013817507 under AA through 2016-11-01, then AAXXXX settle rows; no filing states the old-AA last day, probably 2016-10-31 | unknown |
| value_rule | transfer | transfer / no value (continuation) | agree |
| terms | none | none | agree |
| issuer | 4281 | 4281 (Arconic Inc., formerly Alcoa Inc) | agree |
| security_history.ranges | new: AA 2007-12-19..2016-11-01 (CIK 4281) | AA ends at the move to ARNC; ARNC follows from 2016-11-04 on BBG00DYNJGH9 | agree (new right) |

## 3. Corrected classification
```
exit_kind: continuation (rename / ticker change)  drop_reason:  continuation: true
successor: BBG00DYNJGH9 (ARNC)  last_trade_date: 2016-10-31 (worked out, unconfirmed)
value_rule: transfer  cash_per_share:  cash_currency:  stock_ratio:  price_ticker:  price_sec_id:  price_date:  recovery_ratio:
value_formula: none (continuation)
event_type: rename_spinoff_parent  consideration: none (the Alcoa Corp spin-off is a distribution, not a delisting)
holder_value: same shares  effective_date: 2016-11-01  successor_ticker: ARNC  confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 2016-11-04, 0001193125-16-760363; 8-K 2016-11-01, 0001193125-16-755445, filer name Arconic Inc., former Alcoa Inc.).
- successor: filing names the ticker ARNC (same CIK); the sec_id BBG00DYNJGH9 comes from the base ticker history.
- last trade date: worked out from fails rows (AA rows to 2016-11-01, then AAXXXX settle rows); no filing states it.
- payout rule: filing (no consideration; continuation).
- terms: none needed.
Not backed: the old-AA last day. An exchange print or a filing stating the last day under AA would make it verified.

## 5. What happened
- Reverse split 1-for-3, CUSIP 013817101 to 013817507 on 2016-10-07 ([SEC 8-K 2016-10-07](https://www.sec.gov/Archives/edgar/data/4281/000119312516733851/d264965d8k.htm)).
- 2016-11-01: 8-K Item 5.03 filed under the name Arconic Inc. ([SEC 8-K 2016-11-01](https://www.sec.gov/Archives/edgar/data/4281/000119312516755445/d273759d8k.htm)).
- [SEC 8-K 2016-11-04](https://www.sec.gov/Archives/edgar/data/4281/000119312516760363/d265925d8k.htm): Alcoa Corporation trades as AA on the NYSE; "the Company trades under the symbol ARNC".
- No Form 25 / 25-NSE appears in CIK 4281's filings 2016-09..12.

## 6. Decision-tree bucket
Kept the same security (same issuer, same shares, new ticker). Alcoa Corp's AA is a different, new security.

## 7. Why the library got it wrong
The row is a no-Form-25 fallback (`delist_date_approx`, `successor_unknown`, `last_trade_date_unconfirmed`): the AA ticker ends while the issuer keeps filing, so a continued-filings transfer is emitted, but nothing links it to the ARNC line of the same CIK. Cause: other:successor_not_linked_for_ticker_takeover (new Alcoa Corp took AA; the old line moved to ARNC).

## 8. Fix and open checks
The row should carry successor BBG00DYNJGH9 and continuation=true, or be absent. Confirm the old-AA last trading day. Golden-worthy: yes (a ticker taken over by a spun-off company while the parent renames).

## 9. Verification
Skeptic pass, both fields upheld.
- delistings.added (neither): re-read the cached 8-K 2016-11-04 (0001193125-16-760363): "the Company trades under the symbol ARNC on the New York Stock Exchange", Alcoa Corporation trades as AA. The 8-K 2016-11-01 (0001193125-16-755445) is filed under Arconic Inc., formerly Alcoa Inc. (CIK 4281), and says the common stock is now listed as ARNC. No Form 25 is cited. So the exchange/transfer row with no successor is wrong; a continuation to BBG00DYNJGH9 (ARNC, CIK 4281 in security_history) or no row fits. Could not refute.
- security_history.ranges (new right): AA ends at the ARNC move and BBG00DYNJGH9 starts 2016-11-04 under CIK 4281. The AA range end 2016-11-01 may be a day late (ARNC from 2016-11-01), but it is consistent with the filings. Upheld.

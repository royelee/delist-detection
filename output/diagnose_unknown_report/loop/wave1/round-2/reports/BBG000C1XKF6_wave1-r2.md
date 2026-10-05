# BBG000C1XKF6_wave1-r2 (PNFP, regression)

## 1. Verdict
Old Pinnacle Financial Partners (CIK 1115055) was replaced one-for-one by Newco (renamed Pinnacle Financial Partners, CIK 2082866, ticker PNFP) on the Synovus merger closing, effective January 1, 2026. Its last Nasdaq trade was 2025-12-31 (Jan 1 a market holiday), so the new range end 2025-12-31 is right and the old end 2026-01-02 was wrong.

## 2. Library vs evidence
| Field | Library says (new run; old run in brackets) | Evidence says | Status |
| --- | --- | --- | --- |
| security_history.ranges | PNFP 2007-12-21..2025-12-31 [old: ..2026-01-02] | last trade 2025-12-31; Newco PNFP trades from 2026-01-02 (fails rows under new CUSIP 72348N109 from 20260105) | agree (new right) |
| exit_kind / continuation / successor | exchange, true, BBG01Z7V4LL1 | 1:1 conversion into Newco shares, no cash | agree |
| last_trade_date | blank (internal closing_day, unconfirmed) | 2025-12-31 (worked out: effective Jan 1, 2026, a holiday) | missing |
| value_rule | continuation | continuation | agree |
| terms | none | one Newco share per share, no cash | agree |
| issuer / ticker_history | CIK 1115055, to 2025-12-31 | same | agree |

## 3. Corrected classification
```
exit_kind=exchange drop_reason= continuation=true successor=BBG01Z7V4LL1 last_trade_date=2025-12-31
value_rule=continuation cash_per_share= cash_currency= stock_ratio=1 price_ticker=PNFP price_sec_id=BBG01Z7V4LL1 price_date= recovery_ratio=
value_formula=n/a (not an exit)
event_type=reorganization consideration=stock holder_value="1 Newco (new PNFP) share per old share"
effective_date=2026-01-01 successor_ticker=PNFP confidence=inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 0001115055-26-000002: one-for-one conversion, no cash).
- successor: filing (same 8-K, Newco renamed Pinnacle Financial Partners) and fails rows (new CUSIP 72348N109 under PNFP).
- last trade date: worked out from the 8-K's January 1 event date, the Jan 1 holiday and fails rows (old CUSIP last priced at the 12-31 close); no filing states the last day.
- payout rule: filing (same 8-K).
- terms: filing (same 8-K).
Not backed: an exchange print or an 8-K 3.01 sentence naming the last trading day.

## 5. What happened
- [SEC 8-K 2026-01-02](https://www.sec.gov/Archives/edgar/data/1115055/000111505526000002/pnfp-20260102.htm): date of earliest event January 1, 2026; each Pinnacle share became one Newco share, each Synovus share 0.5237; Newco renamed Pinnacle Financial Partners.
- [SEC 25-NSE/A 2026-01-02](https://www.sec.gov/Archives/edgar/data/1115055/000135445726000001/xslF25X02/primary_doc.xml) removed old Pinnacle common from Nasdaq; Form 15-12G filed 2026-01-12.
- Fails rows (offline): old CUSIP 72346Q104 last row 20260102 at $95.41; new CUSIP 72348N109 from 20260105.

## 6. Decision-tree bucket
Replaced 1:1 by a new line of the same holders: continuation.

## 7. Why the library differed
Base run ended the range on the Form 25 day 2026-01-02; the new run clips at the worked-out closing day 2025-12-31 (`last_trade_date_unconfirmed`, source closing_day). The new value is correct. Cause: other:new value right.

## 8. Fix and open checks
No range fix needed. Open: an exchange print or filing stating the last trading day (published date is blank). Golden-worthy: no.

## 9. Verification
Upheld. Re-read 8-K 0001115055-26-000002 (cached text): Articles/Certificate of Merger effective January 1, 2026 (a market holiday); each Pinnacle common share became one Newco common share, no cash; Pinnacle asked Nasdaq to suspend trading and file Form 25 on January 2, 2026; Newco common lists on the NYSE as PNFP. No old-Pinnacle trading was possible after the December 31, 2025 session, so the range end 2025-12-31 (new) is right and 2026-01-02 (base) was the Form 25 day. Minor wording slip in section 5 (Newco lists on NYSE, not Nasdaq), which does not affect the verdict.

# BBG000CG9XT7_5a-r1 — INVA (Theravance Inc. renamed Innoviva), regression

## 1. Verdict
Theravance, Inc. changed its legal name to Innoviva, Inc. on 2016-01-07 (same CIK 1080014, same shares, ticker THRX to INVA on Nasdaq): a rename, not an ending. The new run is right to drop the 2016-01-08 `exchange` delisting and to carry INVA on the same security; the old run's ending was a rename read as an exchange transfer. One small defect remains in the new ranges (a stray THRX range 2016-01-22..24).

## 2. Library vs evidence (old = base run, new = this run)
| Field | Old says | New says | Evidence says | Status (new) |
| --- | --- | --- | --- | --- |
| delistings row | exchange, last trade 2016-01-08, transfer | no row | no Form 25 or Form 15 in 2015-12..2016-12; rename only | agree |
| exit_kind / continuation / successor | exchange, false, none | none | not an ending | agree |
| last_trade_date | 2016-01-08 | none | none (no ending) | agree |
| value_rule | transfer | none | none | agree |
| terms | none | none | none | agree |
| issuer | CIK 1080014 | CIK 1080014 | same registrant (8-K 5.03) | agree |
| ticker_history | THRX 2007-12-27..2016-01-08, then nothing | THRX ..2016-01-10; INVA 2016-01-11..01-21; THRX 2016-01-22..24; INVA 2016-01-25.. | THRX through Fri 2016-01-08, INVA from Mon 2016-01-11 onward | mostly agree; the THRX 2016-01-22..24 range is wrong |
| sec_id | CIK1080014-COMMON (placeholder) | BBG000CG9XT7 | a FIGI is confirmed for the line; the old placeholder was renamed | agree |

## 3. Corrected classification
```
event_type: name_change
exit_kind: (none, no ending)
drop_reason:
continuation: n/a
successor: none
last_trade_date: (none)
value_rule: continuation (not an exit; no delisting row)
cash_per_share:
cash_currency:
stock_ratio:
price_ticker:
price_sec_id:
price_date:
recovery_ratio:
value_formula: none; same shares, new ticker
consideration: none
holder_value: unchanged shares
effective_date: 2016-01-07 (name change); trading as INVA from 2016-01-11
successor_ticker: INVA
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: not an ending; rests on 8-K 0001104659-16-088785 Item 5.03 ("The merger and resulting name change do not in any way affect the ownership... or the rights or interests of the Company's securityholders") and no Form 25 or Form 15 in the filing list to 2016-06.
- successor: none needed; same CIK, same registrant in that filing.
- last trade date: none published; THRX ceased and INVA began (8-K Item 8.01, same accession).
- payout rule: none; same shares.
- terms: none.

## 5. What happened
- [SEC 8-K 2016-01-08](https://www.sec.gov/Archives/edgar/data/1080014/000110465916088785/a16-1366_18k.htm): on 2016-01-07 Theravance, Inc. changed its name to Innoviva, Inc. through a Section 253 short-form merger of a name-change subsidiary into it; the company survived. Item 8.01: the stock stops trading as THRX and trades as INVA on Nasdaq.
- Fails rows: CUSIP 88338T104 under THRX to 2016-01-22 (22 rows); CUSIP 45781M101 under INVA from 2016-01-11 (34 rows). The CUSIP changed with the name, but the security is the same shares; the later THRX rows are old-CUSIP settlements.
- No Form 25 or Form 15 filed by CIK 1080014 from 2015-12 to 2016-12; later filings (10-K 2016-02-24, 10-Q 2016-05-05) continue under Innoviva.

## 6. Decision-tree bucket
Kept the same security (rename; same CIK, same holders, one for one, no cash).

## 7. Why the library got it wrong (old run)
The old run produced an exchange-transfer row from the 5.03 rename; cause `rename_not_followed`. The new run fixed it. The residual defect: the THRX 2016-01-22..24 ticker range comes from fails rows under the old CUSIP 88338T104 that settle after the rename, read as a fresh THRX sighting. The truth case judge compares ranges as strings, so the changed ranges are expected.

## 8. Fix and open checks
- Accept the new run: no delisting row, INVA continues on BBG000CG9XT7. The id change CIK1080014-COMMON to BBG000CG9XT7 is a placeholder getting its FIGI.
- Fix the ticker blip: a ticker sighting from fails rows under a CUSIP that has already switched to the new symbol (old CUSIP rows after the switch) should not reopen the old ticker.
- Open check: confirm BBG000CG9XT7 is Theravance/Innoviva's composite FIGI through OpenFIGI (not done here; no web evidence used).
- Golden candidate: yes, a well-sourced rename with a CUSIP change (THRX to INVA 2016-01).

## 9. Verification
Skeptic result: upheld, all three field verdicts.
- delistings.removed (new): the filing list for CIK 1080014, 2015-12-01 to 2016-12-31, has no Form 25, 25-NSE or Form 15. The 8-K 0001104659-16-088785 (Items 5.03, 8.01, 9.01) shows a Section 253 name-change merger on 2016-01-07, the same CIK and file number, "securityholders' rights not affected", shares "need not be exchanged", and stock stops trading as THRX and trades as INVA. A rename, not an ending. Upheld.
- security_history.ranges (new): the fails rows for CUSIP 88338T104 (THRX) run only 6 rows, 2016-01-04..2016-01-22, last at $9.81, so the 2016-01-22..24 THRX range is a post-rename settlement tail and the stated truth (THRX to 2016-01-08, INVA from 2016-01-11) holds. The 8-K of 2016-01-15 is an unrelated bylaw amendment. Upheld.
- id_changes.sec_id (new): a placeholder renamed to a BBG id is the right direction; securities.csv shows BBG000CG9XT7, CIK 1080014, COMMON, figi_source=handoff. The report's open check (OpenFIGI confirmation of the id itself) stays open; it does not refute the id change. Upheld.

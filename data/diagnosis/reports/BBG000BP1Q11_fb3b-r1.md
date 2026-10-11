# BBG000BP1Q11_fb3b-r1 (SPGI), regression, mode regression

## 1. Verdict
McGraw Hill Financial renamed itself S&P Global Inc. on 2016-04-27 and its shares traded as SPGI from 2016-04-28 (same CUSIP 78409V104). The old range split (MHFI to 2016-04-27, SPGI from 2016-04-28) is right; the new split (MHFI to 2016-05-01, SPGI from 2016-05-02) is wrong.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| security_history.ranges | MHFI ..2016-04-27, SPGI 2016-04-28.. | MHFI ..2016-05-01, SPGI 2016-05-02.. | SPGI fails rows (CUSIP 78409V104) begin 20160428; MHFI rows end 20160429 (settlement tail under the old symbol); 8-K 5.03 says S&P Global Inc. (f/k/a McGraw Hill Financial) amended its charter 2016-04-27 | old right |

Other fields (exit_kind, successor, last_trade_date, value_rule, terms, issuer): unchanged, issuer CIK 64040 throughout; no ending (security is active), agree.

## 3. Corrected classification
```
exit_kind: none (active)   ranges: MHP 2007-12-18..2013-05-16; MHFI 2013-05-17..2016-04-27; SPGI 2016-04-28..
event_type: rename   confidence: inferred
```

## 4. Why this confidence
inferred. exit kind: no ending (filings). successor: none. last trade date: n/a. payout rule: n/a. terms: n/a. The switch day rests on fails rows (SPGI first row 20160428) plus the filed name change (8-K 0000064040-16-000062); no filing states the first SPGI trading day. Web (S&P Global's press release of the symbol change effective 2016-04-28) would make it verified.

## 5. What happened
- [SEC 8-K 2016-04-29](https://www.sec.gov/Archives/edgar/data/64040/000006404016000062/a04272016form8-k.htm): registrant is S&P Global Inc. (f/k/a McGraw Hill Financial), charter amended 2016-04-27.
- fails rows: SPGI CUSIP 78409V104 first row 20160428; MHFI same CUSIP last row 20160429 (settlement tail).

## 6. Decision-tree bucket
Kept the same security (rename).

## 7. Why the library got it wrong
The new run lets the old symbol's settlement-tail fails rows (to 04-29) set MHFI's range end to 05-01 and the SPGI start to the next trading day after; the SPGI start should be its first own row (04-28). Cause: other:ticker_range_settle_tail.

## 8. Fix and open checks
Do not move a rename's new-ticker start past its first own-symbol fails row because the old symbol's tail still settles. Not golden-worthy as yet.

## 9. Verification
Skeptic re-check: upheld.
- 8-K 0000064040-16-000062 (re-grepped): charter amendment filed 2016-04-27 renaming McGraw Hill Financial to S&P Global Inc.
- Fails (offline): CUSIP 78409V104 as SPGI has 14 rows from 20160428; MHFI has 15 rows 20160401..20160429. The MHFI 04-29 row is a settlement tail on the same CUSIP and overlaps SPGI's own rows, so it cannot move the SPGI start to 05-02. Old split (MHFI ..04-27, SPGI 04-28..) is supported; the new one is not.
- Caveat already in section 4: no filing states the first SPGI trading day, so confidence stays inferred.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: this report read the regression's two sides the wrong way round (side_a is the base, commit 006e194; side_b the batch 3 run). The base has MHFI to 2016-05-01 and SPGI from 2016-05-02; the batch 3 run has MHFI to 2016-04-27 and SPGI from 2016-04-28, which is what this report finds right.

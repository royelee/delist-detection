# BBG000GZQ728_fb3-r1 (XOM, regression)

## 1. Verdict
Exxon Mobil did not leave the market. On 2026-07-01 it redomiciled into ExxonMobil Holdings Corporation (CIK 2115436), one share for one share, and XOM kept trading on the NYSE. The correct output has no delisting row and an open XOM history. The new run's `delistings.added` row (`unknown`, `unexplained_ending`) is wrong; the base run (no row) is right on that field. The ranges field is wrong in both runs.

## 2. Library vs evidence
| field | old (base) | new (library) | evidence | right |
| --- | --- | --- | --- | --- |
| delistings row | none | exit_kind blank, value_rule unknown, last_trade 2026-07-01, flags `unexplained_ending` | no delisting; 1:1 holdco exchange, XOM stays on NYSE | old |
| security_history.ranges | XOM 2007-12-18..2026-07-02 (issuer 34088) | XOM 2007-12-18..2026-07-01 (issuer 34088) | XOM still listed; ticker continues, issuer in force from 2026-07-01 is CIK 2115436 | neither (open range, issuer 34088 then 2115436) |
| exit_kind / drop_reason / continuation / successor | n/a | blank / blank / false / blank | not an ending (security is its own successor) | old |
| terms | n/a | none | 1 share for 1 share, no cash | n/a |
| issuer | 34088 | 34088 | 34088, then 2115436 from 2026-07-01 | neither |

Fails rows: CUSIP 30231G102 under XOM to 2026-07-02 (settlement lag), CUSIP 30233Q108 "EXXONMOBIL HLDGS CORPORATION" under XOM from 2026-07-06 to 2026-08-26 (sec.py fails --symbol XOM). The ticker never left; only the CUSIP and registrant changed.

## 3. Corrected classification
```
no delisting row (security continues as itself)
exit_kind=  drop_reason=  continuation=false  successor=  last_trade_date=
value_rule=unknown (none: no ending)  stock_ratio=1 (own shares, no cash)
event_type=holdco_reorganization  consideration=one_for_one_no_cash  holder_value=unchanged
effective_date=2026-07-01  successor_ticker=XOM  confidence=verified
ticker_history: XOM from 2007-12-18, open; issuer 34088 until 2026-06-30, 2115436 from 2026-07-01
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K12B 0001193125-26-291990 (Redomiciliation Merger effective 2026-07-01, each share exchanged for one share of ExxonMobil Holdings).
- successor: filing, same 8-K12B (Holdings is successor registrant under Rule 12g-3; common stock listed as XOM on the NYSE).
- last trade date: none exists; fails rows show XOM trading on under a new CUSIP from 2026-07-06.
- payout rule: filing, same 8-K12B, 1:1, no cash.
- terms: filing, same 8-K12B.

## 5. What happened
- [SEC 8-K12B 2026-07-01](https://www.sec.gov/Archives/edgar/data/2115436/000119312526291990/d71068d8k12b.htm): ExxonMobil Holdings Corporation (Texas) becomes successor registrant; Redomiciliation Merger effective 2026-07-01; each ExxonMobil share exchanged for one Holdings share, par $0.001; cover lists Common Stock, XOM, New York Stock Exchange.
- [SEC S-8 POS 2026-07-01](https://www.sec.gov/Archives/edgar/data/2115436/000119312526292536/d159056ds8pos.htm) and following: Holdings takes over the plans.
- Fails rows (SEC fails-to-deliver files): XOM under 30231G102 to 2026-07-02, under 30233Q108 from 2026-07-06.

## 6. Decision-tree bucket
Kept the same security: a 1:1 holding-company reorganization is a continuation.

## 7. Why the library got it wrong
The stage "unexplained endings" (new since the base run) gives every security with no ending that is not listed today an `unknown` ending at its last fails row. XOM counts as "not listed today" only because the old registrant's CIK 34088 lists nothing after the reorganization, and no earlier stage links the new CUSIP 30233Q108 to the security: `registrants.goes_on` needs an ending to start from, and there is none. The old CUSIP's last row (2026-07-02) is a settlement tail, so the last trade is also off. Cause: the same holdco shape as WRK and DIS (FB-004), reached without an ending.

## 8. Fix and open checks
- The unexplained-endings stage should not fire for a security whose issuer was replaced by a successor registrant (8-K12B/12G3 naming it) whose own CUSIP trades under the same ticker. Better: stage 4b attaches CUSIP 30233Q108 to the XOM security (same ticker, 1:1 8-K12B), which also extends the range to the data edge.
- Ranges should extend to the data edge with issuer 2115436 from 2026-07-01 (open).
- Good golden case: XOM 2026, verified from one filing.

## 9. Verification
Skeptic pass, mode regression. Re-opened 8-K12B 0001193125-26-291990 (CIK 2115436) through sec.py, and the fails files (`sec.py fails --symbol XOM --from 202606 --to 202609`).
- delistings.added (right: old): upheld. Item 2.01: each ExxonMobil share was exchanged for one share of ExxonMobil Holdings Corporation (par $0.001) at the Effective Time, July 1, 2026; Holdings is the successor registrant under Rule 12g-3(a); the cover lists Common Stock, XOM, New York Stock Exchange. No cash, no second leg. The security continues as itself, so the new `unknown` ending is wrong and the base run's absence of a row is right.
- security_history.ranges (right: neither): upheld. Fails rows: CUSIP 30231G102 under XOM 2026-06-02..2026-07-02 (14 rows); CUSIP 30233Q108 "EXXONMOBIL HLDGS CORPORATION" under XOM 2026-07-06..2026-09-14 (32 rows). The ticker never left, so the range must be open. Base (..07-02) and new (..07-01) are both closed, so both are wrong. Issuer 34088, then 2115436 from 2026-07-01, stands.
- Correction to section 2: the new CUSIP's fails rows run to 2026-09-14, not 2026-08-26. Neither verdict changes.

## 10. Correction of 2026-10-13 (upstream feedback FB-027, consensus)
The verdict in section 1 and the classification in section 3 say "no delisting row (security continues as itself)". They were judged against a run that held one security for XOM and no FIGI for the new CUSIP. OpenFIGI gives CUSIP 30233Q108 its own composite, `BBG023CY9MM1`, and the contract's identity is the composite FIGI, so the run holds two securities. Two securities joined one share for one are a continuation, as old and new Cigna are.

The truth row is now `shape=ending`: `exit_kind=exchange`, `continuation=true`, `successor_sec_id=BBG023CY9MM1`, `value_rule=continuation`, no terms and no price request, last trade 2026-06-30 (the reorganization took effect on 2026-07-01, section 5, so the old shares last traded the day before). The evidence of sections 4, 5 and 9 is unchanged and supports it: the 8-K12B states one share for one, no cash, and names ExxonMobil Holdings Corporation the successor registrant. The new security starts on 2026-07-02 with issuer 2115436.

Section 8's proposed fix (attach the new CUSIP to the old security) is withdrawn with it: the new CUSIP is a security of its own.

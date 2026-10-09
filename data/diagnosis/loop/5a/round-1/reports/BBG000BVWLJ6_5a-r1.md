# BBG000BVWLJ6_5a-r1 (JCI, formerly TYC) - regression, security_history.ranges

## 1. Verdict
The new run is right. Tyco kept one ticker, TYC, from 2007-12-21 to 2016-09-07. The old run's one-day range `TYCZZZZ 2009-03-17..2009-03-17` came from a single fails-to-deliver row at $0.01, a placeholder symbol on the first day of the new Swiss CUSIP, and it split TYC in two.

## 2. Library vs evidence
| Field | Old (side_a) | New (side_b) | Evidence | Status |
| --- | --- | --- | --- | --- |
| `security_history.ranges` | TYC 2007-12-21..2009-03-16; TYCZZZZ 2009-03-17..2009-03-17; TYC 2009-03-18..2016-09-07; JCI 2016-09-08.. | TYC 2007-12-21..2016-09-07; JCI 2016-09-08.. | Fails rows of CUSIP H89128104: 1 row under TYCZZZZ on 20090317 ($0.01), then 65 rows under TYC from 20090318. CUSIP G9143X208 traded as TYC through 20090316 (42 rows). The 8-K of 2009-03-17 names no new ticker. | new right |
| issuer | CIK 833444 | CIK 833444 | The same registrant throughout (Tyco International Ltd, Bermuda, then Swiss). | agree |
| other contract fields | - | - | Not in this case's fields. | unknown |

## 3. Corrected classification
```
security_history ranges: TYC 2007-12-21..2016-09-07 (CIK 833444); JCI 2016-09-08.. (CIK 833444)
event_type: ticker unchanged through the 2009 Bermuda-to-Switzerland redomicile (CUSIP G9143X208 -> H89128104)
confidence: verified for the range question
```

## 4. Why this confidence
verified, for the question asked.
- exit kind: not in dispute; no ending in this window.
- successor: not in dispute.
- last trade date: not in dispute.
- payout rule and terms: not in dispute.
- ticker range: `fails rows` (the single TYCZZZZ row, the TYC rows before and after) and `filing` (the 8-K and 8-K12G3 of 2009-03-17 show a continuing registrant and no ticker change).

## 5. What happened
- [SEC 8-K 2009-03-17](https://www.sec.gov/Archives/edgar/data/833444/000110465909018106/a09-7751_18k.htm) (items 3.03, 5.03, 7.01, 8.01): Tyco International Ltd. discontinued as a Bermuda corporation and continued as a Swiss corporation, effective March 17, 2009.
- [SEC 8-K12G3 2009-03-17](https://www.sec.gov/Archives/edgar/data/833444/000110465909018105/a09-7749_18k12g3.htm): the Swiss Tyco's registered shares are the successor to the Bermuda shares under Rule 12g-3(a).
- Fails rows: CUSIP G9143X208 under TYC 20090102..20090316 (42 rows); CUSIP H89128104 under TYCZZZZ on 20090317 only (1 row, $0.01), then under TYC 20090318..20090630 (65 rows).

## 6. Decision-tree bucket
Kept the same security. The CUSIP changed with the redomicile, but the ticker and the issuer did not, so the ticker history stays one TYC run.

## 7. Why the library got it wrong (old run)
The old run took the TYCZZZZ fails symbol as a real ticker sighting. The new run drops it, so the range is continuous. Cause tag: `other:fails_placeholder_symbol_as_ticker`. This regression is a fix; there is nothing to roll back.

## 8. Fix and open checks
- Nothing to fix: the new output matches the evidence.
- Open check: whether the new run drops the placeholder by a rule (a one-day symbol with a non-ticker suffix and a $0.01 price) or by chance. A different security could carry a similar symbol.
- Golden case: possible, as a ticker-range case for TYC 2009.

## 9. Verification
Upheld. Re-checked offline through sec.py: `fails --cusip H89128104 --from 200903 --to 200903` gives 1 row under TYCZZZZ on 20090317 at $0.01, then 65 TYC rows from 20090318 (first $19.81); `fails --symbol TYC` gives CUSIP G9143X208 under TYC 20090102..20090316 (42 rows). `filings 833444` shows the 8-K (items 3.03, 5.03, 7.01, 8.01) and the 8-K12G3 on 2009-03-17, same CIK 833444 throughout. A $0.01 row under a ZZZZ-suffixed symbol is not a ticker; TYC is continuous across the redomicile. The output's ticker_history.csv holds one TYC row 2007-12-21..2016-09-07. The 8-K text itself was not re-opened (www.sec.gov blocked in this sandbox); the verdict does not depend on it. Open check stands: whether the placeholder is dropped by rule.

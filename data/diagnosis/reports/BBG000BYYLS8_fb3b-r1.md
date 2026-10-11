# BBG000BYYLS8 (TFC) - fb3b round 1, regression: security_history.ranges

## 1. Verdict
BB&T Corp (CIK 92230, renamed Truist Financial) is one issuer throughout. The SunTrust merger closed 2019-12-06 and the common stock first traded as TFC on 2019-12-09. The NEW ranges are right about the first interval's issuer (92230) and the TFC start (2019-12-09), but neither version is right about the two middle intervals (issuers 1072847 and 1108134 are not BB&T).

## 2. Library vs evidence
| Field | old (base run) says | new says | evidence says | status |
| --- | --- | --- | --- | --- |
| ticker_history, TFC start | BBT to 2019-12-10, TFC from 2019-12-11 | BBT to 2019-12-08, TFC from 2019-12-09 | TFC first traded Mon 2019-12-09 (fails: CUSIP 89832Q109 TFC first row 20191209; old CUSIP 054937107 BBT rows run to 20191210 only as a settlement tail) | new agrees, old wrong |
| issuer, 2007-12-18..2012-06-28 | 1108134 | 92230 | BB&T Corp = CIK 92230 (its 8-K of 2019-12-03 shows symbol BBT) | new agrees, old wrong |
| issuer, 2012-06-29..2014-12-30 | 1072847 | 1072847 | CIK 1072847 files 11-Ks of another registrant (2012 filing list); BB&T is 92230 | both wrong |
| issuer, 2014-12-31..2019-12-06 | 1108134 | 1108134 | CIK 1108134's Dec 2014 filings are deal documents (425, S-4), not BB&T's own; BB&T is 92230 | both wrong |
| issuer, 2019-12-07.. | 92230 | 92230 | 92230 | agree |

Other fields (exit_kind, continuation, value_rule, terms) are not in this case's diff.

## 3. Corrected classification
```
security_history.ranges (BBG000BYYLS8):
  BBT 2007-12-18..2019-12-08  issuer 92230
  TFC 2019-12-09..            issuer 92230
exit_kind: (none - not an ending)   continuation: n/a   value_rule: n/a
event_type: ticker_change   consideration: none   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: not in scope.
- successor: not in scope.
- last trade date: not in scope; the ticker switch date rests on `fails rows` (TFC CUSIP 89832Q109 first row 2019-12-09) and on `worked out` from the 8-K (merger effective Friday 2019-12-06, so Monday 12-09 is the first session).
- payout rule: not in scope.
- terms: not in scope.
Not backed: no filing states the first-TFC-session date; evidence that would make it verified is an NYSE notice or press release naming the date. The identity of CIKs 1072847 and 1108134 rests only on their filing lists.

## 5. What happened
- [SEC 8-K 2019-12-03](https://www.sec.gov/Archives/edgar/data/92230/000119312519304879/d837771d8k.htm): BB&T, symbol BBT; SunTrust merger expected to close 2019-12-06.
- [SEC 8-A12B 2019-12-06](https://www.sec.gov/Archives/edgar/data/92230/000119312519307978/d843161d8a12b.htm): registration filed on 12-06.
- [SEC 8-K 2019-12-09](https://www.sec.gov/Archives/edgar/data/92230/000119312519308844/d841243d8k.htm): merger consummated 2019-12-06 (5.03 dated 12-06; 1.295 shares per SunTrust share); cover lists Common Stock, $5 par, symbol TFC, NYSE.
- fails rows: CUSIP 054937107 (BBT) 20191108..20191210; CUSIP 89832Q109 (TFC) from 20191209.

## 6. Decision-tree bucket
Kept the same security (BB&T common continues as Truist's; ticker and name change). Not an ending for this sec_id.

## 7. Why the library got it wrong
The old run took the TFC start from the fails tail of the old CUSIP (last BBT row 12-10), the new run uses 12-09. The issuer per interval comes from a map that assigned BBT's early intervals to other CIKs (1072847, 1108134), still unfixed in the middle intervals. Cause tag: issuer_history_bug.

## 8. Fix and open checks
- Issuer for every BBT interval should be 92230.
- Confirm what registrants CIK 1072847 and 1108134 are.
- Golden-worthy: yes, as a ticker-start plus issuer-per-interval case.

## 9. Verification
Skeptic re-check through sec.py; the one field verdict (security_history.ranges, right = neither) is upheld.
- CIK 1072847 (2012-06..08 filings): 11-K "tower_11k", 8-K "tower_071212", Forms 3/4: a Tower-type registrant, not BB&T. BB&T's own filings in the same weeks are under CIK 92230 (11-K bbt11k.htm, 8-Ks 0000092230-12-*). The 2012-06-29..2014-12-30 interval is wrong in both versions.
- CIK 1108134 (2012-06 and 2014-12): 425s, S-4, 8-K with a bank-merger peer-group table (BHLB, NPBC), a Berkshire Hills-type registrant, not BB&T. The 2014-12-31..2019-12-06 interval is wrong in both; the first interval (old 1108134, new 92230) is right in new.
- Fails: CUSIP 89832Q109 (TFC) first row 20191209; CUSIP 054937107 (BBT) 5 rows 20191203..20191210, last $54.24 equal to TFC's first-day price (a settlement tail). TFC start 2019-12-09 holds; old 2019-12-11 is wrong.
- Result: "neither" is right (new fixes interval 1 and the TFC start but keeps two wrong middle issuers). Not refuted.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run fixes the first range's issuer (CIK 92230, BB&T) and the TFC start (2019-12-09), and keeps the base's two wrong middle ranges, so the change is the library getting better.

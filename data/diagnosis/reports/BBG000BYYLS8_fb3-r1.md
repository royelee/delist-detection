# BBG000BYYLS8_fb3-r1 (TFC / BBT), regression, security_history.ranges

## 1. Verdict
BB&T Corp (CIK 92230) was the issuer of BBT for the whole life of this security and became Truist Financial in Dec 2019 by renaming itself (not a successor). The new run's first range (2007-12-18..2012-06-28, issuer 92230) is right and the old run's 1108134 was wrong. But the new run still carries two wrong issuers in the middle ranges (1072847 for 2012-06-29..2014-12-30, 1108134 for 2014-12-31..2019-12-06), so neither side is fully right.

## 2. Library vs evidence
| field | old (base) says | new says | evidence says | status |
|---|---|---|---|---|
| ranges 2007-12-18..2012-06-28 issuer | 1108134 | 92230 | 92230 (BB&T Corp files its own 10-K for FY2007 and FY2011) | new right |
| ranges 2012-06-29..2014-12-30 issuer | 1072847 | 1072847 | 92230; 1072847 is Tower Financial Corp (Fort Wayne), a different bank | both wrong |
| ranges 2014-12-31..2019-12-06 issuer | 1108134 | 1108134 | 92230; 1108134 is Berkshire Hills Bancorp (BHLB), a different bank | both wrong |
| ranges 2019-12-07..2019-12-10, TFC from 2019-12-11 | 92230 | 92230 | 92230 | agree |
| tickers (BBT to TFC on 2019-12-11), CUSIP 054937107 to 89832Q109 | same | same | consistent with the rename | agree |

## 3. Corrected classification
```
security_history.ranges: BBT 2007-12-18..2019-12-10 issuer 92230 (one issuer throughout); TFC 2019-12-11.. issuer 92230
event_type: rename (BB&T Corp renamed Truist Financial Corp, effective 2019-12-09 per 8-K items 5.03)
confidence: inferred
```

## 4. Why this confidence
inferred.
- issuer: filing, BB&T Corp's own 10-Ks (0001193125-08-041900, 0001193125-12-081457, 0000092230-15-000021) filed under 92230 across all three disputed ranges.
- other CIKs: filing, 8-Ks 0001140361-12-003678 (Tower Financial Corp) and 0001104659-15-004915 (Berkshire Hills Bancorp) show 1072847 and 1108134 are other registrants.
- exit kind, successor, last trade date, payout rule, terms: not applicable to this field; I did not diagnose the ending.
- Not backed: why the library picked those CIKs (probably the name tier matching a ticker or name string such as "BBT"); the 2012 and 2014 CIK switches were not traced to a code path.

## 5. What happened
- [SEC 10-K 2008-02-28](https://www.sec.gov/Archives/edgar/data/92230/000119312508041900/d10k.htm) BB&T Corp, CIK 92230.
- [SEC 10-K 2012-02-27](https://www.sec.gov/Archives/edgar/data/92230/000119312512081457/d282790d10k.htm) same CIK.
- [SEC 10-K 2015-02-25](https://www.sec.gov/Archives/edgar/data/92230/000009223015000021/form10k.htm) same CIK.
- [SEC 8-K 2012-01-26](https://www.sec.gov/Archives/edgar/data/1072847/000114036112003678/form8k.htm) CIK 1072847 is Tower Financial Corporation.
- [SEC 8-K 2015-01-28](https://www.sec.gov/Archives/edgar/data/1108134/000110465915004915/a15-3180_18k.htm) CIK 1108134 is Berkshire Hills Bancorp.
- [SEC 8-K 2019-12-09](https://www.sec.gov/Archives/edgar/data/92230/000119312519308844/d841243d8k.htm) items 2.01, 5.03: the SunTrust merger closed and BB&T renamed Truist, same CIK; 8-A12B 0001193125-19-307978 registers the TFC stock.

## 6. Decision-tree bucket
Kept the same security: the ticker changed BBT to TFC, the FIGI stayed.

## 7. Why the library got it wrong
The issuer timeline swaps in another CIK whose EDGAR name agreed with the observed name that day (issuer_in_force). The change from 1108134 to 92230 in the first range is an improvement, while the 2012 and 2014 ranges still take unrelated small banks. Cause: other:issuer_in_force picks an unrelated registrant for BBT in 2012-2019.

## 8. Fix and open checks
Every range should be issuer 92230. Check why issuer_in_force names 1072847 and 1108134 for BBT. Golden-worthy: yes (simple, well sourced).

## 9. Verification
Skeptic result: upheld. security_history.ranges, verdict "neither": re-read through sec.py. 8-K 0001140361-12-003678 is signed by Tower Financial Corporation (Fort Wayne, CIK 1072847), dated 2012-01-26. 8-K 0001104659-15-004915 is Berkshire Hills Bancorp (CIK 1108134), dated 2015-01-28. Neither is BB&T. 10-K 0000092230-15-000021 (FY2014) is BB&T Corporation, CIK 92230, file no. 1-10853. 8-K 0001193125-19-308844 states the company (previously BB&T Corporation) changed its name to Truist and its ticker to TFC in the merger with SunTrust, so it is the same registrant: a rename, not a successor. The new run's 92230 for 2007-12-18..2012-06-28 is right, while 1072847 (2012-06-29..2014-12-30) and 1108134 (2014-12-31..2019-12-06) remain wrong, so "neither" holds. Minor: the 8-K says the merger and rename took effect 2019-12-06 (section 1 says 2019-12-09), which does not change the verdict.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact; the new run fixes the first range and keeps the base's two wrong middle ranges, so the change is the library getting better.

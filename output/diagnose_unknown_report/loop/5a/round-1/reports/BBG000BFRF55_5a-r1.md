# BBG000BFRF55_5a-r1 (CLF, regression)

## 1. Verdict
Cleveland-Cliffs (CIK 764065) kept ticker CLF throughout; it only renamed to Cliffs Natural Resources and changed CUSIP (185896107 -> 18683K101) on 2008-10-15. The old run's CLFZZZZ range is a one-row fails-to-deliver artifact, so the NEW single range CLF:2007-12-18.. is right.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
| --- | --- | --- | --- | --- |
| security_history.ranges | CLF to 2008-10-14, CLFZZZZ 2008-10-15, CLF from 2008-10-16 | CLF:2007-12-18.. | fails rows: CLF 2008-10-14 (CUSIP 185896107) and from 2008-10-16 (CUSIP 18683K101); CLFZZZZ is 1 row on 2008-10-15, $0.01, CUSIP 18683K101, name Cliffs Natural Resources | new right |
| exit_kind / continuation / successor / last_trade_date / value_rule / terms | none (no ending) | none | no Form 25 in 2008-09..11 filings | agree |

## 3. Corrected classification
```
exit_kind: (none, no ending)
security_history.ranges: CLF:2007-12-18..:764065
event_type: name_change (CUSIP change, same ticker)
confidence: inferred
```

## 4. Why this confidence
inferred. Exit kind: no ending (filing list for 2008-09..11 shows no Form 25). Ranges rest on fails rows (SEC FTD): symbol CLF on both sides of 2008-10-15, same issuer renamed. No filing read states the rename date; an 8-K item 5.03 around 2008-10-15 would make it verified.

## 5. What happened
- Fails rows, symbol CLF: 65 rows 2008-01-22..2008-10-14 under CUSIP 185896107 (Cleveland-Cliffs Inc); 46 rows 2008-10-16..2008-12-31 under CUSIP 18683K101 (Cliffs Natural Resources Inc). [SEC FTD]
- Fails rows, symbol CLFZZZZ: single row 2008-10-15, CUSIP 18683K101, $0.01 (SEC's ZZZZ deleted-symbol marker on the CUSIP-change day). [SEC FTD]
- [SEC filings 2008-09..11](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=764065): 8-K item 8.01, S-4/proxy materials (Alpha Natural Resources bid), no Form 25.

## 6. Decision-tree bucket
Kept the same security (rename; ticker unchanged).

## 7. Why the library got it wrong
The base run treated the ZZZZ-suffixed deleted symbol as a real ticker sighting; the new run does not. Cause: other:ftd_deleted_symbol_artifact (base wrong, new right).

## 8. Fix and open checks
No fix needed. Optionally confirm the Oct 2008 8-K item 5.03. Not golden-worthy.

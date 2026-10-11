# BBG000CNNMD7_5b-r2_fb3-r1 (Sky Financial Group, SKYF) - mismatch, field sec_id

## 1. Verdict
The truth file keys Sky Financial Group's 2007 Huntington merger to `BBG000CNNMD7`, but that composite FIGI is OpenFIGI's line for SKY440 INC (ticker SKYF, CUSIP 83082Y102), a different security that traded 2008-03..2009-03. Sky Financial's own CUSIP (83080P103) has no OpenFIGI answer in the cache, so the run correctly holds it as the placeholder `CIK855876-COMMON`. The library is right; the truth's sec_id is a mis-key inherited from the earlier base run.

## 2. Library vs evidence
| field | truth (side_a) | library (side_b) | evidence says | status |
| --- | --- | --- | --- | --- |
| sec_id | BBG000CNNMD7 | (not in the run); Sky Financial is `CIK855876-COMMON` (figi_source placeholder) | BBG000CNNMD7 = OpenFIGI composite of CUSIP 83082Y102 "SKY440 INC" (cache/openfigi mapping of ID_CUSIP 83082Y102: only composite BBG000CNNMD7, name SKY440 INC, ticker SKYF). Sky Financial's CUSIP is 83080P103 (fails rows SKYF 2007-01-02..2007-07-03); no OpenFIGI answer cached for it. | library right |
| exit_kind / value_rule / terms (run row `CIK855876-COMMON`) | merger, cash_plus_stock, stock_ratio 1.098 | merger, cash_plus_stock, 3.023 USD + 1.098 x HBAN | DEFM14A 0001193125-07-085362: 1.098 HBAN shares + $3.023 cash; 25-NSE 0001354457-07-000195 "Acquired by Huntington" | agree |
| issuer | 855876 | 855876 | 855876 | agree |

## 3. Corrected classification
```
sec_id: CIK855876-COMMON   (placeholder; BBG000CNNMD7 belongs to SKY440 INC, CUSIP 83082Y102)
exit_kind: merger
drop_reason:
continuation: false
successor:
last_trade_date: unpublished (worked out 2007-06-29; internal)
value_rule: cash_plus_stock
cash_per_share: 3.023
cash_currency: USD
stock_ratio: 1.098
price_ticker: HBAN
price_date: 2007-07-02
event_type: acquisition
consideration: cash_and_stock
effective_date: 2007-07-02
successor_ticker: HBAN
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (25-NSE 0001354457-07-000195, 15-12B 0000950103-07-001706).
- successor: filing (DEFM14A 0001193125-07-085362).
- last trade date: worked out (Form 25 effective 2007-07-02, fails rows end 2007-07-03); no filing states it.
- payout rule: filing (DEFM14A).
- terms: filing (DEFM14A). The identity (sec_id) rests on OpenFIGI's cached CUSIP mapping and the fails rows, not a filing; a live OpenFIGI answer for CUSIP 83080P103 would settle whether Sky Financial has a FIGI of its own.

## 5. What happened
- Fails rows (offline, sec.py): CUSIP 83082Y102 "SKY440 INC COMMON STOCK", symbol SKYF, 56 rows 2008-03-12..2009-03-18.
- Fails rows: CUSIP 83080P103 (Sky Financial) SKYF 2007-01-02..2007-07-03 (earlier report).
- OpenFIGI cache (mapping job ID_CUSIP 83082Y102): single composite BBG000CNNMD7, "SKY440 INC", SKYF. A ticker query for SKYF returns the same composite.
- [SEC 25-NSE 2007-07-02](https://www.sec.gov/Archives/edgar/data/855876/000135445707000195/xslF25X02/primary_doc.xml): Sky common removed, acquired by Huntington. The DEFM14A prints no CUSIP (grep of 0001193125-07-085362 for CUSIP / 83080P: 0 matches).
- Current run: `output/securities.csv` holds `CIK855876-COMMON`, issuer 855876, placeholder; the committed HEAD run had BBG000CNNMD7 with figi_source cusip, reached through 2008-2009 SKYF sightings backfilled onto CUSIP 83082Y102.

## 6. Decision-tree bucket
Sky Financial: replaced by cash and stock (merger). The FIGI question is identity only: BBG000CNNMD7 is a different security.

## 7. Why the truth and library differ
The earlier run attached the 2008-2009 SKYF observations to Sky Financial's era and OpenFIGI resolved CUSIP 83082Y102 (SKY440), so the FIGI was SKY440's. The earlier report (5b-r2) noted the 83082Y102 / SKY440 split but kept the base run's sec_id. Cause: other:truth_sec_id_from_misattributed_figi.

## 8. Fix and open checks
Truth row should be re-keyed to `CIK855876-COMMON`; no library change. Open: a live OpenFIGI ID_CUSIP 83080P103 query (not run here) to confirm no FIGI exists. Not golden-worthy.

## 9. Verification
Skeptic pass on field sec_id (library right). Re-checked cache/openfigi: the cached answers naming SKY440 give composite BBG000CNNMD7, name "SKY440 INC", ticker SKYF; no cached OpenFIGI answer mentions Sky Financial's CUSIP 83080P103. output/securities.csv holds `CIK855876-COMMON` (placeholder, issuer 855876) with CUSIP 83080P103 (2004-07-07..2007-07-02); HEAD's securities.csv had BBG000CNNMD7 for that issuer, reached via backfilled 2008-09 SKYF sightings. No filing is needed (blank missed_filing is correct: identity, not a filing question). Residual doubt: Bloomberg can rename a line, so BBG000CNNMD7 might once have been Sky Financial's; but the CUSIP evidence does not support that key and the truth cites no source tying it to 83080P103. Verdict upheld; the live OpenFIGI check for 83080P103 remains open.

## Operator ruling (2026-10-10)

Settled `library_right`; the truth row is ruled (controller ruling 2026-10-10 (batch 3 gate)): BBG000CNNMD7 is OpenFIGI's composite for SKY440 INC (CUSIP 83082Y102), not Sky Financial (CUSIP 83080P103); the run's placeholder CIK855876-COMMON holds Sky Financial (report reports/BBG000CNNMD7_5b-r2_fb3-r1.md).

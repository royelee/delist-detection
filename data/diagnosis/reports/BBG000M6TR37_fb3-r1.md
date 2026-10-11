# BBG000M6TR37_fb3-r1 (SBNY, Signature Bank), regression

## 1. Verdict
Signature Bank was closed by NYDFS on 2023-03-12 with the FDIC as receiver; its Nasdaq stock ended and moved to OTC (SBNYQ). The new run (a `dropped` ending, last trade 2023-03-10, ticker range clipped to 2023-03-10) is right; the old run (no ending, ticker open to 2026-09-04) is wrong.

## 2. Library vs evidence
| Field | Old run (side_a) | New run (side_b) | Evidence | Status |
| --- | --- | --- | --- | --- |
| delistings (row exists) | none | dropped row | bank closed and stock left Nasdaq 2023-03-12 ([web](https://huntonak.com/insights/legal/signature-bank-what-to-know-about-march-12-2023-closing-fdic-receivership-and-bridge-bank)) | new right |
| exit_kind / drop_reason | none | dropped / blank (CRSP 500, compliance_failure) | receivership; right kind is dropped; reason ideally bankruptcy-like (receivership, 574/470 family), not a price/guideline reason | kind agree, reason unknown |
| continuation / successor | n/a | false / none | assets went to Signature Bridge Bank, N.A., holders got nothing ([web](https://huntonak.com/insights/legal/signature-bank-what-to-know-about-march-12-2023-closing-fdic-receivership-and-bridge-bank)) | agree |
| last_trade_date | n/a | 2023-03-10 (MIDAS) | fails rows for 82669G104 run 2023-01-06..2023-03-13 at last $70.00; 03-10 was the last Friday session before the weekend closure | agree (inferred) |
| value_rule | n/a | otc_print, price ticker unknown | stock traded OTC as SBNYQ ([web](https://en.wikipedia.org/wiki/Signature_Bank)) | rule agree, terms missing (price_ticker should be SBNYQ) |
| issuer | CIK 1288784 | CIK 1288784 | EDGAR holds only 13G/13D filings under this CIK; the bank filed with the FDIC, not the SEC | agree |
| ticker_history | SBNY 2008-02-05..2026-09-04 | SBNY 2008-02-05..2023-03-10 | closed 2023-03-12; no later listing | new right |

## 3. Corrected classification
```
exit_kind: dropped
drop_reason: bankruptcy (receivership; library has blank)
continuation: false
successor: none
last_trade_date: 2023-03-10
value_rule: otc_print
cash_per_share: -
price_ticker: SBNYQ
price_date: 2023-03-13
value_formula: otc_print(SBNYQ, 2023-03-13) / last_close - 1
event_type: bank_failure
consideration: none
holder_value: equity expected worthless
effective_date: 2023-03-12
successor_ticker: -
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: web (Hunton; Wikipedia); EDGAR has no 8-K, Form 25 or Form 15 because a bank files with the FDIC.
- successor: web (assets to bridge bank, not a share exchange).
- last trade date: fails rows (last row dated 2023-03-13 settles trades) and MIDAS; worked out, no SEC filing states it.
- payout rule: web (SBNYQ OTC trading).
- terms: no filing; price_ticker SBNYQ from web.
Would become verified with an FDIC or Nasdaq notice stating the halt and delisting day.

## 5. What happened
- Closed 2023-03-12 by NYDFS, FDIC receiver ([web](https://huntonak.com/insights/legal/signature-bank-what-to-know-about-march-12-2023-closing-fdic-receivership-and-bridge-bank)).
- Stock later quoted OTC as SBNYQ ([web](https://en.wikipedia.org/wiki/Signature_Bank)).
- SEC filings list of CIK 1288784 for 2023-2025 holds only SC 13G/13D and an UPLOAD, no issuer filings [SEC filings list].
- Fails rows of CUSIP 82669G104: 31 rows 2023-01-06..2023-03-13, last $70.00.

## 6. Decision-tree bucket
Lost: the bank failed; shares replaced by nothing; stock moved to OTC.

## 7. Why the library differs
The old run had no Form 25 and the history stayed open; the new run's MIDAS drop rule finds the ending. Cause: other:old run missed the ending (bank files with FDIC, no EDGAR evidence); new run correct but reason/price_ticker thin.

## 8. Fix and open checks
New run needs drop_reason (receivership) and the OTC symbol SBNYQ for the print request (currently `?`). Confirm halt date from Nasdaq. Golden-worthy once an exchange notice is cited.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (Signature Bank's 2023-03-10 drop, dated by MIDAS).

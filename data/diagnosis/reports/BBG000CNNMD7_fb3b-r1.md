# BBG000CNNMD7_fb3b-r1 - regression, delistings.removed

## 1. Verdict
The merger row keyed `BBG000CNNMD7` (Sky Financial Group, acquired by Huntington 2007-07-02) disappeared because the same row is now keyed `CIK855876-COMMON`; no ending was lost. The new run is right: `BBG000CNNMD7` is OpenFIGI's composite for SKY440 INC (CUSIP 83082Y102), a different security, as the earlier report `data/diagnosis/reports/BBG000CNNMD7_5b-r2_fb3-r1.md` found.

## 2. Library vs evidence
| field | old (base) | new | evidence says | status |
| --- | --- | --- | --- | --- |
| delistings.removed (row keyed BBG000CNNMD7) | merger, cash_plus_stock, 3.023 USD + 1.098 x HBAN | row absent under this key; identical row under `CIK855876-COMMON` in `output/contract/delistings.csv` | BBG000CNNMD7 = SKY440 INC (cache/openfigi, per earlier report); Sky Financial CUSIP 83080P103 has no cached FIGI | new right |
| exit_kind | merger | merger (under CIK855876-COMMON) | 25-NSE 0001354457-07-000195 "acquired by Huntington" | agree |
| value_rule / terms | cash_plus_stock, 3.023 USD, 1.098 HBAN | same | DEFM14A 0001193125-07-085362 | agree |
| issuer | 855876 | 855876 | 855876 | agree |
| successor / last_trade_date | blank / blank | blank / blank | no filing states a date; Form 25 effective 2007-07-02 | agree |
| ticker_history | n/a | no ranges under BBG000CNNMD7 (nothing observed for it) | SKYF 2008-03..2009-03 belongs to SKY440 | agree |

## 3. Corrected classification
```
sec_id: CIK855876-COMMON (placeholder; BBG000CNNMD7 is SKY440 INC)
exit_kind: merger
drop_reason:
continuation: false
successor:
last_trade_date: unpublished (worked out 2007-06-29)
value_rule: cash_plus_stock
cash_per_share: 3.023
cash_currency: USD
stock_ratio: 1.098
price_ticker: HBAN
price_sec_id: BBG000BKWSR6
price_date: 2007-07-02
recovery_ratio:
value_formula: (3.023 USD + 1.098 x price(HBAN, 2007-07-02)) / last_close - 1
event_type: acquisition
consideration: cash_and_stock
holder_value: 3.023 USD cash + 1.098 HBAN shares
effective_date: 2007-07-02
successor_ticker: HBAN
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (25-NSE 0001354457-07-000195).
- successor: filing (DEFM14A 0001193125-07-085362).
- last trade date: worked out (Form 25 effective 2007-07-02, fails rows end 2007-07-03); no filing states it.
- payout rule: filing (DEFM14A).
- terms: filing (DEFM14A). The identity rests on the cached OpenFIGI mapping, not a filing; a live OpenFIGI answer for CUSIP 83080P103 would settle it. No new SEC or web evidence was gathered; this relies on the earlier report and the committed outputs.

## 5. What happened
- Old contract row: `BBG000CNNMD7,,merger,,false,...,cash_plus_stock,3.023,USD,1.098,BBG000BKWSR6,HBAN` (git HEAD `output/contract/delistings.csv`).
- New contract row: same terms under `CIK855876-COMMON`; `output/securities.csv` lists it as placeholder, issuer 855876, SKY FINANCIAL GROUP INC. No `SKY440` string anywhere in `output/*.csv`.
- [SEC 25-NSE 2007-07-02](https://www.sec.gov/Archives/edgar/data/855876/000135445707000195/xslF25X02/primary_doc.xml): Sky common removed, acquired by Huntington (cited by the earlier report).
- Earlier report: OpenFIGI cache maps CUSIP 83082Y102 to BBG000CNNMD7 "SKY440 INC"; fails rows show SKYF under 83080P103 in 2007 and under 83082Y102 in 2008-09.

## 6. Decision-tree bucket
Replaced by cash and stock of another company (merger). Identity change only.

## 7. Why the library got it wrong
The old base run backfilled 2008-09 SKYF sightings onto Sky Financial's era, so OpenFIGI's SKY440 composite became its key. The new run no longer does (fb3 line-follow and settling-tail fixes). Cause: other:base_sec_id_from_misattributed_figi (the new run is right).

## 8. Fix and open checks
No fix; the removal is correct and the added row exists under the placeholder. Open: live OpenFIGI ID_CUSIP 83080P103 query. Truth already ruled (operator 2026-10-10). Not golden-worthy.

## 9. Verification
Upheld. Checked: the cached 25-NSE 0001354457-07-000195 is Sky Financial Group, Nasdaq, Common Stock (the ending is real and one row exists). The cached OpenFIGI answers list compositeFIGI BBG000CNNMD7 with name "SKY440 INC", ticker SKYF, so that FIGI is not Sky Financial's. HEAD output/securities.csv keyed Sky Financial (issuer 855876) to BBG000CNNMD7 through the cusip source, while the new run holds it as CIK855876-COMMON with the same merger terms (3.023 USD + 1.098 HBAN). No cached OpenFIGI answer exists for CUSIP 83080P103, so the placeholder is the rule's result. The removal is a re-key, not a lost ending: "new" right. Residual: no live OpenFIGI check (as the report says).

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the removal right: the row was re-keyed to CIK855876-COMMON (Sky Financial, FB-009), and BBG000CNNMD7 is SKY440 Inc's line, which never had this ending.

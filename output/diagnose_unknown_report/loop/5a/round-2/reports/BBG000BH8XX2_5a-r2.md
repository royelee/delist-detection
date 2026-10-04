# BBG000BH8XX2_5a-r2 (CIE, Cobalt International Energy)

## 1. Verdict
Cobalt's common stock was suspended by the NYSE at the close on 2017-12-13 (market-cap standard), the company filed Chapter 11 on 2017-12-14, and the Form 25-NSE followed on 2018-01-02. The only change in this regression is the key: the placeholder `CIK1471261-COMMON` became the composite FIGI `BBG000BH8XX2`, and the new value is right; the ending itself is unchanged and consistent with the filings.

## 2. Library vs evidence
| Field | Old (base 794ef8d) | New (this run) | Evidence | Status |
| --- | --- | --- | --- | --- |
| `delistings.price_sec_id` | CIK1471261-COMMON | BBG000BH8XX2 | OpenFIGI answer for CIEIQ (cache/openfigi/5d3651df...json): common stock "COBALT INTERNATIONAL ENERGY", compositeFIGI BBG000BH8XX2, shareClassFIGI BBG001SKC776. Issuer CIK 1471261 matches the Form 25-NSE filer. | new is right |
| `id_changes.sec_id` | CIK1471261-COMMON | BBG000BH8XX2 | Same: the placeholder now holds a confirmed FIGI, so a rename row in `contract/id_changes.csv` is correct. | new is right |
| `exit_kind` / `drop_reason` | dropped / bankruptcy | same | 8-K 1.03 filed 2017-12-14 (0001193125-17-368742); NYSE suspension 2017-12-13 | agree |
| `continuation` / successor | false / none | same | no successor filings; 15-12B filed 2018-03-05 | agree |
| `last_trade_date` | 2017-12-13 | same | Form 25-NSE: "Trading in the Common Stock was suspended at the close of the market on December 13, 2017"; fails rows under CIE end 2017-12-15 (settlement lag), under CIEIQ from 2017-12-18 | agree |
| `value_rule` / terms | otc_print, price_ticker CIE, price_date 2017-12-14 | same | OTC trading under CIEIQ (fails rows 2017-12-18 to 2018-03-28) | agree (see open checks) |
| `issuer` | 1471261 | same | Form 25-NSE filer | agree |
| `ticker_history` | CIE NYSE 2009-12-23 to 2017-12-13 | same, now keyed by FIGI | | agree |

## 3. Corrected classification
```
exit_kind: dropped        drop_reason: bankruptcy     continuation: false     successor: none
last_trade_date: 2017-12-13
value_rule: otc_print     cash_per_share: -   cash_currency: -   stock_ratio: -
price_ticker: CIEIQ (own OTC symbol; library says CIE)   price_sec_id: BBG000BH8XX2   price_date: 2017-12-14
recovery_ratio: -
value_formula: otc_print(CIEIQ, first print from 2017-12-14) / last_close - 1
event_type: bankruptcy   consideration: none   holder_value: first OTC print   effective_date: 2018-01-16 (NYSE removal)
successor_ticker: -   confidence: verified
```

## 4. Why this confidence
verified for what the regression changes.
- exit kind: filing, 8-K 1.03 (0001193125-17-368742) and Form 25-NSE 0000876661-18-000002.
- successor: filing; none in the filing list to 2018-03; 15-12B 0001193125-18-069524.
- last trade date: filing, the Form 25-NSE notice (suspended at the close 2017-12-13).
- payout rule: filings (bankruptcy, then OTC) and fails rows (CIEIQ).
- terms: no market price needed; the FIGI is confirmed by OpenFIGI, not a filing (an identity key, not a payout term).

## 5. What happened
- NYSE determined 2017-12-13 to suspend and delist (market cap under $15M); suspended at the close that day ([SEC 25-NSE 2018-01-02](https://www.sec.gov/Archives/edgar/data/1471261/000087666118000002/xslF25X02/primary_doc.xml)).
- Chapter 11 petition, 8-K items 1.03, 2.04, 3.01 ([SEC 8-K 2017-12-14](https://www.sec.gov/Archives/edgar/data/1471261/000119312517368742/d506127d8k.htm)).
- Form 15-12B filed 2018-03-05 ([SEC](https://www.sec.gov/Archives/edgar/data/1471261/000119312518069524/d544781d1512b.htm)).
- Fails rows: CUSIP 19075F304 (after the 2017-06 reverse split) under CIE to 2017-12-15, under CIEIQ 2017-12-18 to 2018-03-28 (fails data).

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC. The same CUSIP trades as CIEIQ; the equity was not replaced.

## 7. Why the library differs from base
Not an error. The base run could not confirm a FIGI and used the placeholder; this run's OpenFIGI answer confirms BBG000BH8XX2. Cause: other:placeholder_now_figi (an improvement, not a defect).

## 8. Fix and open checks
- None needed for the key change; the `contract/id_changes.csv` row is correct.
- The published `price_ticker` is CIE; the security's own OTC symbol was CIEIQ (the reference says to give it if known). Not part of this regression.
- Golden worthiness: no.

## 9. Verification
Upheld. Re-checked the OpenFIGI cache entry (5d3651df...json): the composite BBG000BH8XX2 is "COBALT INTERNATIONAL ENERGY" common stock, share class BBG001SKC776, ticker CIEIQ, US venues. securities.csv lists BBG000BH8XX2 with CIK 1471261, class COMMON. The placeholder CIK1471261-COMMON is the same issuer and class, so the rename row in id_changes is a correct rename. Both `price_sec_id` and `id_changes.sec_id` verdicts (right: new) survive. Open check, not part of this regression: the published price_ticker is CIE where the own OTC symbol is CIEIQ.

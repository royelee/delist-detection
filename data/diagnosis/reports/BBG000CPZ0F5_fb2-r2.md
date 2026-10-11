# BBG000CPZ0F5_fb2-r2 (PDLI, regression)

## 1. Verdict
PDL BioPharma voluntarily delisted its common stock from Nasdaq under a shareholder-approved Plan of Dissolution (solvent wind-down), not for a listing deficiency. The new row (liquidation, recovery) is right; the old row (dropped / filings_fees, otc_print) is wrong.

## 2. Library vs evidence
| field | old (side_a) | new (side_b) | evidence | right |
| --- | --- | --- | --- | --- |
| exit_kind | dropped | liquidation | voluntary delisting "in connection with the Company's previously disclosed voluntary Plan of Dissolution" ([SEC 8-K 2020-12-08, 0000882104-20-000200](https://www.sec.gov/Archives/edgar/data/882104/000088210420000200/pdli-20201204.htm)) | new |
| drop_reason | filings_fees | blank | no exchange action or deficiency; issuer-initiated notice; drop_reason belongs only on `dropped` | new |
| value_rule | otc_print | recovery | a solvent liquidation is valued from its payments (decision 3), not an OTC print | new |
| price_sec_id | PDLI sec_id | blank | only an otc_print/stock rule needs a price security | new |
| price_date | 2020-12-31 | blank | same | new |
| last_trade_date (unchanged) | 2020-12-30 | 2020-12-30 | trading suspended before the open on 2020-12-31 (same 8-K; SC TO-I 0000882104-21-000009 repeats it) | agree |

## 3. Corrected classification
```
exit_kind: liquidation   drop_reason:   continuation: false   successor: none
last_trade_date: 2020-12-30
value_rule: recovery  cash_per_share: unknown  recovery_ratio: unknown (liquidating distributions not in the filings read)
price_ticker:   price_sec_id:   price_date:
value_formula: distributions(?, after the last trade) / last_close - 1
event_type: liquidation  consideration: other  effective_date: 2021-01-07 (Form 25 filed 2020-12-28 + 10 days)  successor_ticker:
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 0000882104-20-000200, Plan of Dissolution; Form 25 0000882104-20-000215; Form 15 0000882104-21-000003).
- successor: filing; none (no successor registration found).
- last trade date: filing, suspended before the open on 2020-12-31, so 2020-12-30.
- payout rule: worked out from decision 3 (solvent liquidation); no filing states the amounts.
- terms: not backed. Distribution amounts and dates are not in the filings read (Form 15 ended reporting). A liquidating-distribution press release or filing would make it verified.

## 5. What happened
- 2020-12-08: 8-K item 3.01, voluntary delisting notice to Nasdaq under the Plan of Dissolution; suspension before the open 2020-12-31; Form 25 expected about 2020-12-28, effective about 2021-01-07 ([SEC](https://www.sec.gov/Archives/edgar/data/882104/000088210420000200/pdli-20201204.htm)).
- 2020-12-28: Form 25 0000882104-20-000215 (issuer).
- 2021-01-08: Form 15-12G, 86 holders of record ([SEC](https://www.sec.gov/Archives/edgar/data/882104/000088210421000003/a20210108form15.htm)).
- 2021-01-15: SC TO-I for the convertible notes repeats the suspension and delisting dates ([SEC](https://www.sec.gov/Archives/edgar/data/882104/000088210421000009/a20210115todoc.htm)).
- Fails rows: 33 rows 2020-12-01..2021-01-26, last price 2.47 (no sign of an OTC print).

## 6. Decision-tree bucket
Lost: wound down (plan of dissolution) -> `liquidation`.

## 7. Why the library got it wrong
The old row read the removal as a dropped / filings_fees ending valued by an OTC print. The new row (liquidation branch for a plan of dissolution 3.01, recovery rule) matches the filings. Cause: other:old_row_misclassified_voluntary_dissolution_delisting (the new run fixes it).

## 8. Fix and open checks
Nothing needed for the kind. Open: the liquidating distributions (amount per share, dates) for the recovery terms. Golden-worthy: yes (well-sourced voluntary-dissolution delisting).

## Operator ruling (2026-10-10)

Operator ruling 2026-10-10 (FB-002): the report finds every regressed field right (a voluntary delisting under its Plan of Dissolution, 8-K 0000882104-20-000200; Form 25 0000882104-20-000215), upheld by its skeptic; its inferred confidence is the distribution amounts only, which no scored field holds. The ledger rows are settled `new_right` and the truth row is a scored `pass` row with these values; the value itself (the sum of the distributions) waits for FB-002's distributions reader.

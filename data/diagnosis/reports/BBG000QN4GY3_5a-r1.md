# BBG000QN4GY3_5a-r1 (HOUS, regression)

## 1. Verdict
Realogy Holdings Corp. renamed itself Anywhere Real Estate Inc. and its common stock moved from ticker RLGY to HOUS on the NYSE on 2022-06-09. It is a rename, not a delisting, so the base run's exchange-transfer row (removed now) was wrong and the new run is right to drop it. The new ticker ranges are one day late at the boundary.

## 2. Library vs evidence
| field | old (base) | new (library) | evidence | right |
|---|---|---|---|---|
| delistings.removed | exchange / transfer row, last trade 2022-06-08, no successor | no row | no Form 25 or 25-NSE filed by CIK 1355001 2022-05..2023-08; 8-K says the stock "began trading on the New York Stock Exchange under the symbol HOUS" | new |
| security_history.ranges | RLGY 2012-10-12..2022-06-08 | RLGY ..2022-06-09; HOUS 2022-06-10..2026-01-09 | 8-K: HOUS trading effective 2022-06-09, so RLGY ends 06-08 and HOUS starts 06-09 | neither (old RLGY end right; new HOUS start a day late) |

## 3. Corrected classification
```
exit_kind: (no ending)  continuation: n/a  successor: none (same security)
event_type: ticker_rename   consideration: none (shares unchanged)
holder_value: unchanged  effective_date: 2022-06-09  successor_ticker: HOUS
ticker ranges: RLGY 2012-10-12..2022-06-08 ; HOUS 2022-06-09..
confidence: verified
```

## 4. Why this confidence
verified. Exit kind (none): 8-K 0001398987-22-000139 Item 5.03 (name change by Section 253 merger, holders' rights unaffected) plus no Form 25 in the filing list. Successor: none, same company. Last trade date / ticker switch: the filing states HOUS trading effective June 9. Payout rule and terms: none apply.

## 5. What happened
- [SEC 8-K 2022-06-09](https://www.sec.gov/Archives/edgar/data/1355001/000139898722000139/rlgy-20220609.htm): effective June 9, 2022 Realogy Holdings Corp. changed its name to Anywhere Real Estate Inc.; common stock began trading on the NYSE under HOUS effective June 9, 2022.
- SEC filing list for CIK 1355001, 2022-05-01..2023-08-30, forms 25, 25-NSE, 8-A12B: none.

## 6. Decision-tree bucket
Kept the same security (rename).

## 7. Why the library got it wrong
The base run read the ticker change as an exchange transfer ending (last trade 2022-06-08); the new run removes it. Cause: other:ticker_rename_misread_as_transfer (fixed in the new run). Residual: HOUS range starts 2022-06-10 from fails rows (ftd) rather than the 8-K date.

## 8. Fix and open checks
Start HOUS at 2022-06-09 per the 8-K (the RLGY observation on 06-09 is likely a stale snapshot). Golden-worthy: yes, as a rename that must not produce a delisting.

## 9. Verification
Upheld. Re-read the cached 8-K 0001398987-22-000139: Item 5.03 name change by Section 253 merger (surviving company, holders' rights unaffected), common stock "began trading on the New York Stock Exchange under the symbol HOUS, effective June 9, 2022"; the cover page lists the common stock under HOUS on the NYSE. No Form 25 appears in the cached filing lists, so dropping the transfer row (new) is right. For ranges, neither run matches: the base has RLGY ..06-08 right but no HOUS range; the new run has RLGY ..06-09 and HOUS from 06-10, each a day late. Corrected: RLGY ..06-08, HOUS 06-09.. (caveat: the 8-K does not say 06-08 was a trading day for RLGY, but the 06-09 start is stated).

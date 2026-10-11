# BBG000NDZ417 (PXP), regression, fb3b round 1

## 1. Verdict
PXP was acquired by Freeport-McMoRan (FCX) on 2013-05-31 in a cash-or-stock election merger. A holder who made no valid election got about 99.5% of the cash consideration ($46.01) and 0.5% of the stock consideration (1.4302 FCX). The two changed fields differ only in rounding of that same package: old cash 45.780050 vs new 45.780000, old ratio 0.007151 vs new 0.007150. Neither move is a real error.

## 2. Library vs evidence
| Field | Old (base run) | New | Evidence says | Status |
| --- | --- | --- | --- | --- |
| exit_kind | merger | merger | merger (FCX acquisition) | agree |
| drop_reason / continuation | blank / false | blank / false | blank / false | agree |
| successor | none | none | none (acquirer FCX is `price_ticker`, not a successor) | agree |
| last_trade_date | 2013-05-30 | 2013-05-30 | closing and Form 25 on 2013-05-31, so 2013-05-30; the date rests on MIDAS | agree |
| value_rule | cash_plus_stock | cash_plus_stock | cash_plus_stock (non-electing default) | agree |
| terms: cash_per_share | 45.780050 | 45.780000 | 0.995 x 46.01 = 45.77995 ("approximately 99.5%" of "approximately $46.01") | new is closer (differs by 0.00005 vs 0.0001); both round to 45.78 |
| terms: stock_ratio | 0.007151 | 0.007150 | 0.005 x 1.4302 = 0.007151 (the stated remainder is "the remainder", approximately 0.5%) | old is the exact product; the gap is 1e-6 x FCX price, under 0.00005 in dollars |
| terms: currency / price security / date | USD / FCX / 2013-05-31 | same | USD; FCX; the first session after the 2013-05-30 last trade | agree |
| issuer | CIK 891456 | same | PLAINS EXPLORATION & PRODUCTION CO | agree |
| ticker_history | PXP 2007-12-17 to 2013-05-30 | same | consistent with the Form 25 | agree |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor: (none)
last_trade_date: 2013-05-30
value_rule: cash_plus_stock
cash_per_share: 45.78  (0.995 x 46.01 = 45.77995)
cash_currency: USD
stock_ratio: 0.007151  (0.005 x 1.4302)
price_ticker: FCX
price_sec_id: BBG000BJDB15
price_date: 2013-05-31
recovery_ratio:
value_formula: (45.78 + 0.007151 x price(FCX, 2013-05-31)) / last_close - 1
event_type: acquisition
consideration: cash_or_stock_election
holder_value: election: 46.01 USD cash or 1.4302 FCX; non-electing: about 99.5% cash plus about 0.5% stock = 45.78 USD + 0.007151 FCX
effective_date: 2013-05-31
successor_ticker:
confidence: inferred
```
Holders who elected stock (45.5% of shares) got 1.4302 FCX and holders who elected cash (29.1%) got $46.01; the non-electing 25.4% got the default package above. A separate $3.00 PXP special dividend, payable 2013-05-30 and conditioned on closing, is not part of the consideration.

## 4. Why this confidence
Confidence: inferred, because the last trade date rests on an exchange print.
- Exit kind: filing, PXP/FCX Oil & Gas 8-K filed 2013-06-03 (0001193125-13-244647), items 2.01, 3.01 and 5.01.
- Successor: filing, the same 8-K names FCX as acquirer. There is no continuation.
- Last trade date: MIDAS, with the Form 25-NSE (0000876661-13-000380) effective 2013-05-31. The date is worked out, not stated.
- Payout rule: filing, the 8-K states the election mechanics and the non-elector split.
- Terms: filing, the same 8-K gives $46.01, 1.4302 FCX and "approximately 99.5%" cash. The exact 45.77995 and 0.007151 are my arithmetic on those rounded figures.

Not backed: the exact last trading day. An exchange print or a notice stating it would make this `verified`.

## 5. What happened
- Special meeting approved the merger with FCX: [SEC 8-K 2013-05-24](https://www.sec.gov/Archives/edgar/data/891456/000119312513235569/d544139d8k.htm).
- Merger closed 2013-05-31. Each PXP share became about $46.01 cash or about 1.4302 FCX at the holder's election. Non-electors got about 99.5% cash and the rest stock: [SEC 8-K 2013-06-03](https://www.sec.gov/Archives/edgar/data/891456/000119312513244647/d547318d8k.htm).
- NYSE Form 25-NSE filed and effective 2013-05-31: [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/891456/000087666113000380/xslF25X02/primary_doc.xml).
- Form 15-12B filed 2013-06-11: [SEC 15-12B](https://www.sec.gov/Archives/edgar/data/891456/000119312513254463/d552368d1512b.htm).

## 6. Decision-tree bucket
Replaced by cash and stock of another company (FCX): merger, no continuation.

## 7. Why the library got it wrong
It did not. The library's `llm_election_package` read 99.5% / 0.5% of the stated figures. The 0.00005 and 0.000001 differences between the runs come from rounding precision in how the package is computed. Cause: `other:rounding_only_no_error`.

## 8. Fix and open checks
- No fix needed; the new run's cash (45.78) is within 0.0001 of the exact figure and the old run's ratio (0.007151) is the exact product. The 0.5% remainder is stated as approximate, so the filings cannot rank the two beyond this.
- Open check: the exact last exchange trade date, 2013-05-30 from MIDAS, no stronger source read.
- Golden case: no. The case is a rounding variant, not a rule flip.

## 9. Verification
Re-read the 8-K filed 2013-06-03 (0001193125-13-244647, CIK 891456) through sec.py. It states "approximately $46.01" cash, "approximately 1.4302 shares" of FCX, and that the 25.4% non-electors get "approximately 99.5%" of their consideration in Cash Consideration and "the remainder in Stock Consideration". This is the right security (PXP common, CIK 891456) and the right date (closing 2013-05-31).
- cash_per_share, new right (45.78): 0.995 x 46.01 = 45.77995. New 45.780000 is 0.00005 away, old 45.780050 is 0.0001 away. Both are inside the filing's rounding; the verdict survives as the closer figure.
- stock_ratio, old right (0.007151): 0.005 x 1.4302 = 0.007151 exactly. New 0.007150 is 1e-6 off. The verdict survives as the exact product.
Neither field is a real error: "approximately" in the filing means the filing cannot rank the two beyond this arithmetic. No library missed_filing is claimed, and none is needed. Both verdicts upheld.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: a rounding difference only, as the report and its skeptic found: both runs publish the same non-elector package of the 8-K 0001193125-13-244647 (about 99.5% of $46.01 cash and 0.5% of 1.4302 FCX); the batch 3 run's merger-terms model rounds it to 45.78 and 0.00715, the base's to 45.78005 and 0.007151.

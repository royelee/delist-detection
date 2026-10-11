# BBG000BJQ328 (FNM) regression fb3-r1: delistings.added, security_history.ranges

## 1. Verdict
Fannie Mae voluntarily withdrew its common stock from the NYSE and Chicago Stock Exchange at FHFA's direction (Form 25 under 12d2-2(c), filed 2010-06-28, effective 2010-07-08) and the stock went to OTC as FNMA. That is a real ending (moved to OTC, decision 11), so the new row `dropped / moved_otc / otc_print` and the exchange-listing range ending 2010-07-08 are right; the old run (no ending, FNMA range to 2026) is wrong.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
| --- | --- | --- | --- | --- |
| delistings row | none | dropped / moved_otc, value_rule otc_print, not a continuation, no successor, no last_trade_date | Form 25 0000950123-10-061714; 8-K 0001299933-10-002367 item 3.01 | new right |
| exit_kind / drop_reason | none | dropped / moved_otc | issuer delisted itself to OTC under FHFA direction after an NYSE sub-$1 price notice | new right |
| continuation / successor | none | false / none | same CUSIP 313586109 goes on OTC, but the exchange listing ended: decision 11, an ending valued at the first OTC print | new right |
| last_trade_date | none | blank (not published) | no exchange print found; Form 25 effective 2010-07-08 (filing 2010-06-28 + 10 d), so last NYSE session worked out as 2010-07-07 | unknown (blank is allowed) |
| value_rule / terms | none | otc_print, price_ticker FNMA, price_date blank | fails rows: CUSIP 313586109 as FNM to 2010-07-13, then FNMA from 2010-07-14 | new right; price_date missing (follows the last trade) |
| issuer | 310522 | 310522 | Form 25 filer CIK 310522 | agree |
| ticker_history | FNM 2007-12-19..2010-07-13; FNMA 2010-07-14..2026-09-14 | FNM 2007-12-19..2010-07-08 | exchange listing ended at the Form 25; FNMA is OTC, not a listing | new right |

## 3. Corrected classification
```
exit_kind: dropped
drop_reason: moved_otc
continuation: false
successor: none
last_trade_date: 2010-07-07 (worked out from the Form 25 effective date; not published)
value_rule: otc_print
cash_per_share: -  cash_currency: -  stock_ratio: -
price_ticker: FNMA  price_sec_id: BBG000BJQ328 (same security)  price_date: 2010-07-08 (session after the last exchange trade, worked out)
recovery_ratio: -
value_formula: otc_print(FNMA, 2010-07-08) / last_close - 1
event_type: exchange_delisting  consideration: none  holder_value: same shares, quoted OTC as FNMA
effective_date: 2010-07-08  successor_ticker: FNMA (OTC, same security)  confidence: inferred
```

## 4. Why this confidence
inferred. exit kind: 8-K 2010-06-16 item 3.01 and Form 25 2010-06-28 (filing). successor: none, the same CUSIP continues OTC (fails rows). last trade date: worked out from the Form 25 effective date (filing + 10 d), no exchange print or notice day. payout rule: otc_print by decision 11, resting on the filings. terms: OTC symbol FNMA from fails rows, not a filing. To become verified: the Form 25 EX-99.25 notice or an NYSE/MIDAS print stating the last session (not in the cache; the Form 25 text carries none).

## 5. What happened
- NYSE notified Fannie Mae on 2010-06-15 that its 30-day average close was below $1.00 (Section 802.01C). [SEC 8-K 2010-06-16](https://www.sec.gov/Archives/edgar/data/310522/000129993310002367/htm_38021.htm)
- On 2010-06-16 FHFA, as conservator, directed delisting of the common and preferred from the NYSE and any other exchange; Fannie Mae told NYSE and Chicago it would withdraw. Same 8-K.
- Form 25 filed 2010-06-28 for the common stock, NYSE and Chicago, ticked under 12d2-2(c) (voluntary withdrawal). [SEC Form 25](https://www.sec.gov/Archives/edgar/data/310522/000095012310061714/w78960a2e25.htm)
- Fails rows for CUSIP 313586109: FNM 2010-07-01..07-13 ($0.34 to $0.36), FNMA from 2010-07-14 ($0.32 to $0.38 by 07-30) (sec.py fails, offline cache). The symbol changed with the OTC move; fails data lags by days.
- Fails rows keep showing FNMA to 2026-09-14 (earlier report fb1-r1), so the stock trades on after the exchange listing ended.

## 6. Decision-tree bucket
Lost the exchange listing, then OTC (a price-deficiency notice, executed as a voluntary withdrawal at FHFA's direction): `dropped`.

## 7. Why the library got it wrong
The base run had no ending, so the OTC tail looked like continued listing. FB-004's moved-to-OTC rule now finds the group, sees the 10-K cover listing no exchange, and rewrites it to 520. The base run was the defect; the new run fixes it. Cause: other:base_run_missed_moved_otc (fixed).

## 8. Fix and open checks
No further fix for these two fields. Open: a published last trade date needs an exchange print, hence price_date blank in the contract; the worked-out 2010-07-07 vs the range end 2010-07-08 is a one-day convention. Golden-worthy: yes, with the last trade date blank until a print is found. Settle both fields new_right.

## 9. Verification
Skeptic pass, both field verdicts upheld.
- delistings.added: re-read Form 25 0000950123-10-061714 (filed 2010-06-28, Common Stock, NYSE and Chicago, 12d2-2(c) voluntary withdrawal, signed June 28, 2010) and 8-K 0001299933-10-002367 (Item 3.01: NYSE sub-$1 notice under 802.01C, FHFA direction of 2010-06-16 to delist, Form 25 effective 10 days after filing). Fails rows for CUSIP 313586109: FNM to 2010-07-13, FNMA from 2010-07-14, so the shares traded on OTC. A voluntary withdrawal after a price-deficiency notice with the stock continuing OTC is dropped / moved_otc / otc_print, not a continuation. Blank last_trade_date is correct (no exchange print published).
- security_history.ranges: the exchange listing ended at the Form 25 effective date 2010-07-08 (filing + 10 d); FNMA is OTC, not a listing. Range FNM 2007-12-19..2010-07-08 is consistent.
- Not refuted. Caveat only: the 10-K cover claim (no exchange listed) was taken from the library's reason, not re-opened.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (Fannie Mae's 2010 move to the OTC market).

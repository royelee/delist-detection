# BBG000BHRRV6_5b-r1 (EK, Eastman Kodak) - regression diagnosis

## 1. Verdict
Kodak filed Chapter 11 on 2012-01-19 and NYSE suspended the common stock immediately that day, then removed it by Form 25-NSE; the holders' shares stayed outstanding but traded OTC (EKDKQ). The new run (a bankruptcy drop, last trade 2012-01-18, ticker range ending 2012-01-18) is right; the base run (no delisting row, EK range running to 2012-01-19 and EKDKQ to 2013-09-04) is wrong.

## 2. Library vs evidence (old = base run, new = current run)
| field | old / new library says | evidence says | status |
| --- | --- | --- | --- |
| delistings row | old: none; new: one ending | a Form 25-NSE (0000876661-12-000045) removes the stock | new right |
| exit_kind | new: dropped | dropped (bankruptcy; NYSE 802.01D) | agree (new) |
| drop_reason | new: bankruptcy | bankruptcy | agree (new) |
| continuation / successor | new: false, none | same CUSIP 277461109 traded on as EKDKQ; not a new line, not a successor | agree |
| last_trade_date | new: 2012-01-18 (MIDAS) | Form 25 notice: suspended immediately on 2012-01-19, announced at the open; so last trade 2012-01-18 | agree (new) |
| value_rule | new: otc_print | first off-exchange print within 10 sessions (decision 11); fails rows show EKDKQ trading from 2012-01-20 | agree |
| terms | price_ticker EK, price_sec_id BBG000BHRRV6, price_date 2012-01-19 | the security's own OTC symbol is EKDKQ; price_date 2012-01-19 (session after last trade) | agree (price_ticker EK vs EKDKQ is cosmetic; price_sec_id is the key) |
| issuer | CIK 31235 | CIK 31235 | agree |
| ticker_history | old: EK to 2012-01-19 then EKDKQ to 2013-09-04; new: EK to 2012-01-18 | listing ended by suspension 2012-01-19; the EKDKQ OTC range is not an exchange listing | new right |

## 3. Corrected classification
```
exit_kind: dropped
drop_reason: bankruptcy
continuation: false
successor: none
last_trade_date: 2012-01-18
value_rule: otc_print
cash_per_share: -
cash_currency: -
stock_ratio: -
price_ticker: EKDKQ
price_sec_id: BBG000BHRRV6
price_date: 2012-01-19
recovery_ratio: -
value_formula: otc_print(EKDKQ, from 2012-01-19) / last_close - 1
event_type: bankruptcy
consideration: none
holder_value: old shares kept, trading OTC as EKDKQ
effective_date: 2012-01-19 (suspension); Form 25 effective 2012-02-14
successor_ticker: none
confidence: verified
```

## 4. Why this confidence
Confidence: verified.
- exit kind: filing - 8-K 1.03 0001193125-12-016443; Form 25-NSE 0000876661-12-000045 citing the Chapter 11 petition.
- successor: filing - none exists; fails rows show the same CUSIP under EKDKQ.
- last trade date: filing - Form 25 notice says suspended immediately on 2012-01-19, so last trade 2012-01-18 (MIDAS agrees).
- payout rule: filing - bankruptcy delisting, shares stay outstanding, decision 11.
- terms: no cash/stock terms apply; the first OTC print is qlib_practice's.

## 5. What happened
- 2012-01-03: 8-K item 3.01 (listing standard notice) [SEC 8-K 0000031235-12-000002].
- 2012-01-19: Chapter 11 petitions filed [SEC 8-K 0001193125-12-016443, items 1.03, 2.04].
- 2012-01-19: NYSE determined the stock be suspended immediately; Form 25-NSE filed 2012-02-03, delisting at the open on 2012-02-14 [SEC 25-NSE 0000876661-12-000045].
- Fails rows: EK 2012-01-03..2012-01-19; EKDKQ 2012-01-20..2013-03-28, same CUSIP 277461109.

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC. The old stock carried on only as an OTC line, which is an ending valued at the first OTC print.

## 7. Why the library got it wrong
Regression is an improvement: the base run missed the Form 25 and kept the OTC symbol in ticker_history. Cause: other:base_run_missed_form25_for_EK (the current row is correct).

## 8. Fix and open checks
No fix needed; keep the new row. Optional: set price_ticker to EKDKQ. Good golden candidate (NYSE immediate suspension on a bankruptcy).

## 9. Verification
Upheld both field verdicts (delistings.added = new, security_history.ranges = new). Re-read Form 25-NSE 0000876661-12-000045: NYSE determined on 2012-01-19 that the Common Stock be suspended immediately (LCM 802.01D), announced at the opening on 2012-01-19, after the Chapter 11 filing. Fails rows for CUSIP 277461109: EK 2012-01-03..2012-01-19 (last $0.55), EKDKQ from 2012-01-20 (OTC). This matches reference.md's "Lost: bankruptcy, then OTC" row: dropped/bankruptcy, last trade 2012-01-18, otc_print. The EK range ending 2012-01-18 is right and the EKDKQ OTC range is not an exchange listing. Minor: the 2012-01-19 fails row is dated the day after the last close, consistent with the 01-18 last trade.

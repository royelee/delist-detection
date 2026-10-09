# BBG000BT0CM2_wave1-r1 (SIVB, regression: price_ticker)

## 1. Verdict
SVB Financial Group filed Chapter 11 on 2023-03-17; Nasdaq halted the common on 2023-03-10 and delisted it. The ending is a dropped/bankruptcy otc_print. Of the two sides, the base run's `SIVB` is closer, but neither is right: the OTC symbol is `SIVBQ`. The new blank is wrong because the security's own OTC symbol is known (web); the old `SIVB` is wrong because it is the Nasdaq symbol.

## 2. Library vs evidence
| Field | Old (base) | New (now) | Evidence | Status |
| --- | --- | --- | --- | --- |
| price_ticker | SIVB | blank | SIVBQ (OTC Pink / Expert Market from 2023-03-28, web) | neither; blank is `missing`, SIVB `wrong` |
| exit_kind / drop_reason | dropped / bankruptcy | same | 8-K 2023-03-17 items 1.03, 3.01 | agree |
| continuation / successor | false / none | same | no successor; equity extinguished | agree |
| last_trade_date | 2023-03-09 | same | 8-K 0001193125-23-073665: halted March 10, 2023 (before open), so last trade 03-09; MIDAS agrees | agree |
| value_rule | otc_print | same | decision 11 | agree |
| price_date | 2023-03-10 | same | session after the last trade, by rule | agree |
| price_sec_id | own sec_id | own | own line | agree |

## 3. Corrected classification
```text
exit_kind        = dropped
drop_reason      = bankruptcy
continuation     = false
successor        =
last_trade_date  = 2023-03-09
value_rule       = otc_print
price_sec_id     = BBG000BT0CM2
price_ticker     = SIVBQ
price_date       = 2023-03-10
value_formula    = otc_print(SIVBQ, from 2023-03-10) / last_close - 1
event_type       = bankruptcy
consideration    = none
effective_date   = 2023-03-17 (Chapter 11); Nasdaq suspension 2023-03-28
confidence       = inferred
```

## 4. Why this confidence
Inferred.
- Exit kind: filing (8-K 2023-03-17, items 1.03 and 3.01).
- Successor: filing (none; no successor filing in the 2023 list).
- Last trade date: filing (the 8-K says Nasdaq halted trading March 10, 2023; MIDAS gives 03-09).
- Payout rule: decision 11 on a filing-backed bankruptcy drop.
- Terms: price_ticker SIVBQ rests on web only; the 8-K says only that the stock "may then be" quoted on OTC Pink. Needs a filing or OTC notice naming SIVBQ.

## 5. What happened
- [SEC 8-K 2023-03-17](https://www.sec.gov/Archives/edgar/data/719739/000119312523073665/d485308d8k.htm): Chapter 11; Nasdaq halted the common on 2023-03-10, suspended 2023-03-28; may be quoted on OTC Pink.
- [SEC 25-NSE 2023-05-02](https://www.sec.gov/Archives/edgar/data/719739/000135445723000327/xslF25X02/primary_doc.xml): Nasdaq's removal.
- [web](https://investorplace.com/2023/03/delisted-bank-stocks-signature-and-svb-financial-start-trading-otc/): traded OTC as SIVBQ from 2023-03-28 (about 13 sessions after the last Nasdaq trade; a long gap for decision 11's 10-day window, qlib_practice decides the print).

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC.

## 7. Why the library got it wrong
Base run published the Nasdaq ticker as the OTC price ticker; the new run publishes blank, since it no longer fills the ticker from the security's ticker history. Cause: other:price_ticker for otc_print should be the OTC symbol (SIVBQ), not the listed ticker or blank.

## 8. Fix and open checks
The library cannot know SIVBQ from SEC alone; blank (`*` in truth) is acceptable if no source is wired, SIVB is not. Confirm the first OTC print date is within 10 sessions (it appears to be 03-28, outside). Not golden-worthy.

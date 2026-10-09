# BBG000BT0CM2_wave1-r2 (SIVB, SVB Financial Group) - regression, field price_ticker

## 1. Verdict
SVB Financial Group filed Chapter 11 on 2023-03-17; Nasdaq halted the stock on 2023-03-10, suspended it 2023-03-28 and removed it by Form 25-NSE effective 2023-05-12. The ending (dropped / bankruptcy, otc_print, last trade 2023-03-09) is right. The only changed field is `price_ticker`: old run `SIVB`, new run blank. Neither is the right value; the OTC symbol is `SIVBQ` (not confirmed from a filing).

## 2. Library vs evidence
| field | library says (old / new) | evidence says | status |
| --- | --- | --- | --- |
| exit_kind / drop_reason | dropped / bankruptcy | 8-K 1.03 filed 2023-03-10 and 2023-03-17 (Chapter 11), Nasdaq 3.01 notice | agree |
| continuation / successor | false / none | equity not exchanged; no successor | agree |
| last_trade_date | 2023-03-09 | 8-K 0001193125-23-073665: halted March 10, 2023 (so last trade March 9); fails rows end 2023-03-10 | agree |
| value_rule | otc_print | equity stayed outstanding, traded OTC after 2023-03-28 suspension | agree |
| terms: price_ticker | old SIVB / new blank | OTC symbol after delisting: SIVBQ (web knowledge, unverified) | wrong in both (old: exchange ticker; new: missing) |
| terms: price_sec_id, price_date | BBG000BT0CM2, 2023-03-10 | same security; date is the session after last trade by rule | agree |
| issuer | CIK 719739 | 25-NSE filed under CIK 719739 | agree |
| ticker_history | SIVB, 2007-12-17 to 2023-03-09 | same | agree |

## 3. Corrected classification
```
exit_kind: dropped        drop_reason: bankruptcy     continuation: false     successor: none
last_trade_date: 2023-03-09
value_rule: otc_print     cash_per_share: -   cash_currency: -   stock_ratio: -
price_ticker: SIVBQ       price_sec_id: BBG000BT0CM2  price_date: 2023-03-10  recovery_ratio: -
value_formula: otc_print(SIVBQ, from 2023-03-10) / last_close - 1
event_type: bankruptcy    consideration: none   holder_value: equity stays outstanding, trades OTC Pink
effective_date: 2023-05-12 (Form 25 removal)   successor_ticker: -   confidence: inferred
```

## 4. Why this confidence: inferred
- exit kind: filing (8-K 0001193125-23-067777 item 1.03; 8-K 0001193125-23-073665 items 1.03, 3.01).
- successor: filing (none named; no exchange of shares).
- last trade date: filing (8-K 0001193125-23-073665: halted March 10, 2023, so March 9) plus fails rows ending 2023-03-10.
- payout rule: filing (3.01 says shares may be quoted on OTC Pink; 25-NSE under 12d2-2(b)).
- terms: the OTC symbol SIVBQ rests on web knowledge, not a cited filing. To make this verified: a source naming SIVBQ (OTC Markets page or press release).

## 5. What happened
- 2023-03-10 8-K 1.03/8.01: bank failure; Nasdaq halted trading March 10. [SEC 8-K 2023-03-10](https://www.sec.gov/Archives/edgar/data/719739/000119312523067777/d450664d8k.htm)
- 2023-03-17 8-K: Chapter 11 filed; Nasdaq notice, halted March 10, suspended March 28, may be quoted on OTC Pink. [SEC 8-K 2023-03-17](https://www.sec.gov/Archives/edgar/data/719739/000119312523073665/d485308d8k.htm)
- 2023-05-02 Form 25-NSE, removal effective at open 2023-05-12, securities suspended 2023-03-28. [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/719739/000135445723000327/xslF25X02/primary_doc.xml)
- Fails rows (CUSIP 78486Q101): 6 rows 2023-03-02..2023-03-10, last $106.04; none under SIVBQ (fails data for that symbol is empty).

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC. Value is the first OTC print.

## 7. Why the library got it wrong
Not wrong on the ending. The old run wrote the exchange ticker SIVB as the OTC price symbol; the new run writes blank (formula shows "?") because it no longer fills the exchange ticker and knows no OTC symbol. Cause: other:otc_symbol_unknown.

## 8. Fix and open checks
- Supply the OTC symbol (SIVBQ) or accept blank with price_sec_id as the key; blank is more honest than SIVB, so the new value is the better of the two, though incomplete.
- Confirm SIVBQ from a web source. Not golden-worthy (the symbol needs outside data).

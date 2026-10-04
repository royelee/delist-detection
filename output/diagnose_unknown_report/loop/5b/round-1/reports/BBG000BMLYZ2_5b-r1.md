# BBG000BMLYZ2_5b-r1 (KWK, Quicksilver Resources) - regression

## 1. Verdict
NYSE suspended KWK on 2015-01-08 for an abnormally low price and removed it via Form 25-NSE; the stock then traded OTC as KWKA (bankruptcy 2015-03-17, KWKAQ). The NEW run is right on both fields: the delisting row was added and the exchange ticker range is clipped at 2015-01-07. One detail of the new row is doubtful: drop_reason `guidelines` (the NYSE cites abnormally low price, so `price`).

## 2. Library vs evidence (regression: old = base run, new = this run)
| Field | old (base) | new | evidence | right |
| --- | --- | --- | --- | --- |
| delistings.added | no contract row | dropped / guidelines / no continuation / last trade 2015-01-07 / otc_print | Form 25-NSE 0000876661-15-000086 (filed 2015-02-19, removal at open 2015-03-02, NYSE 12d2-2(b), suspended 2015-01-08); 8-K 0001060990-15-000029 item 3.01: trading suspended immediately, now OTC, to be KWKA | new (row should exist) |
| security_history.ranges | KWK to 2015-01-13, KWKA 2015-01-14..2015-03-22, KWKAQ 2015-03-23..2017-03-27 | KWK 2007-12-21..2015-01-07 | NYSE listing ended at suspension; KWKA/KWKAQ are OTC lines of the same CUSIP 74837R104 (fails rows from 20150114 under KWKA, from 20150323 under KWKAQ). ticker_history records exchange listings and is clipped at a dropped ending | new |
| exit_kind | (none) | dropped | NYSE delisting, then OTC | agree (new) |
| drop_reason | - | guidelines | NYSE rule 802.01D "abnormally low" price and 802.01C $1 average: CRSP 550/552 = price | wrong in detail (price) |
| continuation / successor | - | false / none | no successor registration; same holders, bankruptcy follows | agree |
| last_trade_date | - | 2015-01-07 | MIDAS; 8-K says suspended "immediately" on 2015-01-08 (time not stated); fails rows KWK 20150107..20150113 | inferred 2015-01-07 |
| value_rule / terms | - | otc_print, price_ticker KWK, price_date 2015-01-08 | first OTC print under own OTC symbol KWKA (8-K); price_ticker should be KWKA | rule agrees, price_ticker wrong |
| issuer | CIK 1060990 | same | | agree |

## 3. Corrected classification
```
exit_kind: dropped
drop_reason: price
continuation: false
successor: none
last_trade_date: 2015-01-07
value_rule: otc_print
cash_per_share: -   cash_currency: -   stock_ratio: -
price_ticker: KWKA   price_sec_id: BBG000BMLYZ2 (same security)   price_date: 2015-01-08
recovery_ratio: -
value_formula: otc_print(KWKA, first print from 2015-01-08) / last_close - 1
event_type: exchange_delisting   consideration: none   holder_value: first OTC print
effective_date: 2015-03-02 (Form 25 removal; suspension 2015-01-08)   successor_ticker: none   confidence: inferred
```

## 4. Why this confidence: inferred
- exit kind: filing (Form 25-NSE EX-99.25, 8-K 3.01).
- successor: filing (none; no successor registration in the issuer's filing list).
- last trade date: worked out - the filings say suspended 2015-01-08 without a time; 2015-01-07 rests on MIDAS and fails rows.
- payout rule: filing (8-K: trades OTC, KWKA).
- terms: no consideration; the OTC symbol is from the 8-K.
Not backed: the exact last exchange session. An exchange print or a notice stating the session would make it verified.

## 5. What happened
- NYSE notice 2014-10-09 of average close below $1 (cited in the 8-K 3.01 of 2015-01-08).
- [SEC 8-K 2015-01-08](https://www.sec.gov/Archives/edgar/data/1060990/000106099015000029/kwk8-k20150108.htm): trading suspended immediately; OTC, expected on OTCQB as KWKA.
- [SEC 25-NSE 2015-02-19](https://www.sec.gov/Archives/edgar/data/1060990/000087666115000086/xslF25X02/primary_doc.xml): removal at opening of business 2015-03-02, 802.01D abnormally low price; suspended 2015-01-08.
- [SEC 8-K 2015-03-17](https://www.sec.gov/Archives/edgar/data/1060990/000106099015000056/kwk8-k20150317.htm): chapter 11.
- Fails rows (SEC): CUSIP 74837R104 KWK 2015-01-07..13, KWKA 2015-01-14..03-11, KWKAQ from 2015-03-23.

## 6. Decision-tree bucket
Lost: delisted for a deficiency (low price), then OTC. The bankruptcy came two months after the delisting.

## 7. Why the library got it wrong
The base run had no row (the Form 25 was filed late versus the suspension) and kept OTC KWKA/KWKAQ in ticker_history. The new run is correct; its remaining flaws are drop_reason from CRSP 570 (reason string "listing deficiency") instead of price, and price_ticker KWK. Cause: other:drop_reason_guidelines_vs_price.

## 8. Fix and open checks
Map an "abnormally low price" Form 25 notice to 550/552 (price); set price_ticker to the OTC symbol. Confirm whether the last session was 01-07 or 01-08. Golden-worthy: yes (late Form 25 plus OTC case).

## 9. Verification
Skeptic re-read of 8-K 0001060990-15-000029 and Form 25-NSE 0000876661-15-000086 through sec.py. Both confirmed: the 8-K item 3.01 says NYSE moved to delist for an "abnormally low trading price", trading suspended immediately on 2015-01-08, now on the OTC market; the EX-99.25 cites Rule 12d2-2(b), 802.01D (abnormally low price) and 802.01C ($1 average), removal at the opening of 2015-03-02. A real exchange delisting by Form 25 on common stock, so the added row is right and drop_reason is price (not guidelines). Range clip at 2015-01-07 follows from the last session before the 2015-01-08 suspension, consistent with the library's MIDAS date. Residual doubt: the suspension time on 2015-01-08 is not stated, so the exact last session is inferred. Both verdicts upheld.

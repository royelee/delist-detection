# BBG000C4FB79_wave2-r1 (TRH, TransAtlantic Holdings)

## 1. Verdict
Alleghany (Y) acquired TransAtlantic, effective before the open on 2012-03-06; holders got $14.22 cash + 0.145 Alleghany shares per share (election, prorated). The base run's terms were right; the new run's `value_rule=unknown` with blank terms is a regression.

## 2. Library vs evidence
| field | old (base) | new (library now) | evidence | status |
| --- | --- | --- | --- | --- |
| exit_kind | merger | merger | merger | agree |
| continuation / successor | false / none | false / none | acquired by Alleghany, not a continuation | agree |
| last_trade_date | 2012-03-05 | 2012-03-05 | notice: suspended March 6, merger effective before open Mar 6 -> Mar 5 | agree |
| value_rule | cash_plus_stock | unknown | cash_plus_stock | new wrong |
| cash_per_share | 14.22 | blank | 14.22 USD | new missing |
| stock_ratio | 0.145 | blank | 0.145 | new missing |
| price_ticker / price_sec_id | Y / BBG000BX6BJ3 | blank | Alleghany common (NYSE: Y) | new missing |
| price_date | 2012-03-06 | blank | session after last trade | new missing |
| issuer | CIK 862510 | same | TransAtlantic Holdings | agree |
| ticker_history | TRH to 2012-03-05 | same | n/a | agree |

## 3. Corrected classification
```
exit_kind: merger   drop_reason:    continuation: false   successor:    last_trade_date: 2012-03-05
value_rule: cash_plus_stock  cash_per_share: 14.22  cash_currency: USD  stock_ratio: 0.145
price_ticker: Y  price_sec_id: BBG000BX6BJ3  price_date: 2012-03-06  recovery_ratio:
value_formula: (14.22 USD + 0.145 x price(Y, 2012-03-06)) / last_close - 1
event_type: acquisition  consideration: cash_or_stock_election
holder_value: 14.22 cash + 0.145 Alleghany shares   effective_date: 2012-03-06  successor_ticker: Y  confidence: verified
```
The notice describes an election (Alleghany shares, or cash of 0.145 x the 5-day average Y close + $14.22, prorated); the cash + 0.145 shares package is the agreement's aggregate mix.

## 4. Why this confidence
verified.
- exit kind: filing, 25-NSE 0000876661-12-000106 (merger effective March 6).
- successor: filing, same notice (Alleghany; no continuation).
- last trade date: filing, same notice (suspended March 6 -> trading day before).
- payout rule: filing, same notice (cash plus Alleghany shares).
- terms: filing, same notice ($14.22, 0.145).

## 5. What happened
- [SEC 25-NSE 2012-03](https://www.sec.gov/Archives/edgar/data/862510/000087666112000106/): merger with Alleghany effective before the open March 6, 2012; per share 0.145 x 5-day average Y close + $14.22, or Alleghany shares, prorated; suspended March 6.
- [SEC 8-K 2012-02-06](https://www.sec.gov/Archives/edgar/data/862510/000119312512041318/d295886d8k.htm): items 5.07, 8.01 (shareholder vote on the merger).

## 6. Decision-tree bucket
Replaced by cash and another company's stock: merger.

## 7. Why the library got it wrong
Row shows `dlret_method=abstain_no_consideration`, flag `no_last_close`, reason "M&A 2.01+3.01+5.01"; the new run published no terms where the base run read them. Cause: terms_not_extracted.

## 8. Fix and open checks
Restore cash_plus_stock 14.22 USD / 0.145 / Y (BBG000BX6BJ3) / 2012-03-06, noting the election. Golden-worthy: yes. No prices needed.

## 9. Verification
Upheld, all six fields. Re-opened the cached filings: the 8-K 0001193125-12-098329 (March 6, 2012) says each share became either Alleghany stock or cash worth (i) 0.145 x the 5-day average NYSE close of Alleghany and (ii) $14.22, i.e. $61.14; the proxy 0001193125-12-003820 gives the same terms. A stock election and a cash election carry the same value, so cash 14.22 + 0.145 x price(Y) is the right value formula for an election deal (reference.md: give the aggregate package and say so). The Form 25 is dated 2012-03-06, so the last trade is 2012-03-05 and price_date 2012-03-06 is the next session. Alleghany (BBG000BX6BJ3, ALLEGHANY CORP, common) is in output/securities.csv, so price_sec_id is a real run security. Caution: the base run's terms_gate was `failed`, but that gate compares against a fails-based close; the terms themselves match the filings.

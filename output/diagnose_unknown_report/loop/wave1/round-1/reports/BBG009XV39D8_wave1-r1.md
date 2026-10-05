# BBG009XV39D8_wave1-r1 (AVGO, Broadcom Ltd) - regression, mode `regression`

## 1. Verdict
Broadcom Ltd (Singapore) became a subsidiary of Broadcom Inc (Delaware) by a one-for-one scheme of arrangement that took effect after the close on 2018-04-04, so its last trade was 2018-04-04. Neither the old range end (2018-04-05) nor the new one (2018-04-02, the `closing_day` guess) is right; the new one is further off. The row's kind (continuation to BBG00KHY5S69) is right.

## 2. Library vs evidence
| field | library says (old / new) | evidence says | status |
| --- | --- | --- | --- |
| `security_history.ranges` AVGO end | old 2018-04-05 / new 2018-04-02 | last trade 2018-04-04 (range should end 2018-04-04) | wrong (both) |
| `exit_kind` | exchange | exchange (continuation) | agree |
| `continuation` / successor | true / BBG00KHY5S69 | 1:1 exchange into Broadcom Inc | agree |
| `last_trade_date` (internal) | closing_day 2018-04-02, unconfirmed | 2018-04-04 | wrong |
| `value_rule` | transfer, 0 | transfer / continuation | agree |
| issuer | CIK 1649338 | same | agree |

## 3. Corrected classification
```
exit_kind=exchange  drop_reason=  continuation=true  successor=BBG00KHY5S69  last_trade_date=2018-04-04
value_rule=continuation  cash_per_share=  cash_currency=  stock_ratio=1  price_ticker=AVGO  price_date=
recovery_ratio=  value_formula=same shares, 1:1 (no exit)
event_type=redomiciliation_scheme  consideration=1 Broadcom Inc share per Broadcom Ltd share
holder_value=transfer  effective_date=2018-04-04 (after close)  successor_ticker=AVGO  confidence=inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 0001193125-18-107587, one-for-one scheme, no cash).
- successor: filing (same 8-K names Broadcom Inc); fails rows show the new CUSIP 11135F101 under AVGO from 2018-04-06.
- last trade date: worked out from the 8-K's "after the close of market trading on April 4, 2018 ... the Scheme of Arrangement became effective" and the fails rows (old CUSIP's last row 2018-04-05 is priced at the 04-04 close; the new CUSIP's first row 2018-04-06 at the 04-05 close). No filing states "last traded on". An exchange print or the exchange notice stating it would make it verified.
- payout rule: filing (continuation, no value).
- terms: filing (one-for-one).

## 5. What happened
- [SEC 8-K 2018-04-04](https://www.sec.gov/Archives/edgar/data/1649338/000119312518107587/d548692d8k.htm): court approval April 2; after the close on April 4 the scheme became effective; ordinary shares exchanged one-for-one for Broadcom-Delaware common stock.
- [SEC 25-NSE 2018-04-04](https://www.sec.gov/Archives/edgar/data/1649338/000135445718000077/xslF25X02/primary_doc.xml): Nasdaq, Ordinary Shares, 12d2-2(a)(3), filed 16:44 after the close, effectiveness date 2018-04-04.
- Fails rows (offline): Y09827109 under AVGO 20180301..20180405; 11135F101 under AVGO from 20180406.

## 6. Decision-tree bucket
Kept the same claim: 1:1 holding-company redomiciliation, a continuation (decision 9).

## 7. Why the library got it wrong
Reason says "last traded ... 2018-04-05 / took the ticker from 2018-04-06": the old end is a day late (fails row date, not trade date). The new rule 4 `closing_day` took 2018-04-02 (the court approval date in the 8-K's "April 4, 2018 (April 2, 2018)" header) as the closing, while the 8-K says the effect came after the close on April 4; flags `last_trade_date_unconfirmed`. Cause: last_trade_date (closing_day picked the approval date, not the effective time).

## 8. Fix and open checks
Closing-day reading should prefer "after the close of market trading on D ... became effective" over the event-date header; the range end then 2018-04-04. Confirm with an exchange print if desired. Good golden candidate.

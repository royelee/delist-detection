# CIK1334814-CLASS-A_wave1-r1 (Z, regression)

## 1. Verdict
Zillow Inc Class A became Zillow Group Class A one-for-one (holding company; Trulia merger closed 2015-02-17); trading in Zillow Inc Class A was halted at the close on 2015-02-17. Neither ticker range end is right: the old end (2015-02-18) is one day late, the new end (2015-02-13, last observation) is two trading days early; the right end is 2015-02-17.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| security_history.ranges | Z..2015-02-18 | Z..2015-02-13 | last trade 2015-02-17 | neither right (old +1 d, new -2 trading d) |
| exit_kind / continuation / successor | exchange, true, BBG000D13GN8 | same | holding-company exchange | agree |
| last_trade_date | blank | blank | 2015-02-17 | missing |
| value_rule | continuation | | transfer 1:1 | agree |
| issuer, ticker_history | CIK 1334814, Z | | | agree |

The library reason text says "last traded as Z on 2015-02-18" (fails row date, which is priced at the prior close); fails rows of 98954A107 run to 20150218, new CUSIP 98954M101 from 20150219 (offline `fails`).

## 3. Corrected classification
```
exit_kind=exchange continuation=true successor=BBG000D13GN8 (Zillow Group Class A)
last_trade_date=2015-02-17 value_rule=continuation (1 share = 1 share)
event_type=holding_company_reorg effective_date=2015-02-18 successor_ticker=Z confidence=verified
range: Z 2011-07-25..2015-02-17
```

## 4. Why this confidence
verified. Exit kind: Form 25-NSE/A notice (0001354457-15-000031). Successor: 8-K12B 0001193125-15-050788. Last trade date: that 8-K12B, Item 2.01, trading halted as of the close on February 17, 2015. Payout rule and terms: notice, one Zillow Group Class A share per Zillow Inc Class A share, effective 2/18/2015.

## 5. What happened
- [SEC 25-NSE/A 2015-02-17](https://www.sec.gov/Archives/edgar/data/1334814/000135445715000031/): each Zillow Inc Class A share exchanged for one Zillow Group Class A, effective 2/18/2015.
- [SEC 8-K12B 2015-02-17](https://www.sec.gov/Archives/edgar/data/1617640/000119312515050788/d871412d8k12b.htm): Zillow Class A halted as of the close on February 17, 2015.

## 6. Bucket
Kept (continuation into a new holding company line).

## 7. Why the library got it wrong
Last trade is unconfirmed (`closing_day`, `last_trade_date_unconfirmed`); the 8-K12B's halt sentence was not read. The ranges end at a sighting or fails-row date, not the stated halt. Cause: last_trade_date_unread_8k12b.

## 8. Fix and open checks
Read the halt date from an 8-K12B Item 2.01 for a handoff continuation. Golden-worthy.

## 9. Verification
Upheld. Re-read 8-K12B 0001193125-15-050788 (cached text): "Trading on the NASDAQ Global Select Market in shares of Zillow Class A common stock ... will be halted as of the close of trading on February 17, 2015." So the last trade is 2015-02-17. Base range end 2015-02-18 (fails-row date) is one day late; new end 2015-02-13 (last observation) is early. Verdict "neither" for security_history.ranges holds with value Z:2011-07-25..2015-02-17:1334814. No library verdict, so no missed_filing check applies.

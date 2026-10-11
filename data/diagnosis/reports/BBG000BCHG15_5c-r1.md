# BBG000BCHG15_5c-r1 (ASH, Ashland Inc.) - regression

## 1. Verdict
Ashland Inc. became a wholly-owned subsidiary of the new holding company Ashland Global Holdings Inc. on 2016-09-20; each share converted one for one into Ashland Global stock, no cash, and the new stock kept the ticker ASH. That is a continuation, so the NEW row (exchange, continuation true, successor BBG00D0Y81M1, no value) is right and the old row (merger, stock 1:1 priced on ASH) was wrong.

## 2. Library vs evidence (old = base run, new = this run)
| Field | old | new | evidence | right |
| --- | --- | --- | --- | --- |
| exit_kind | merger | exchange | 1:1 holdco merger, successor issuer under Rule 12g-3 | new |
| continuation | false | true | each share converted into one Ashland Global share, no cash | new |
| successor_sec_id | blank | BBG00D0Y81M1 | Ashland Global (CIK 1674862) stock trades as ASH from 2016-09-21 in ticker_history | new |
| value_rule | stock | continuation | not an exit | new |
| stock_ratio / price_sec_id / price_ticker / price_date | 1.0 / BBG00D0Y81M1 / ASH / 2016-09-20 | blank | a continuation has no value terms | new |
| last_trade_date | 2016-09-19 | 2016-09-19 | NYSE suspended trading before the open on 2016-09-20, so last trade 2016-09-19 (unchanged, agree) | agree |
| issuer | CIK 1305014 | CIK 1305014 | agree |
| ticker_history | ASH to 2016-09-19; new line ASH from 2016-09-21 | same | agree |

## 3. Corrected classification
```
exit_kind: exchange
drop_reason:
continuation: true
successor: BBG00D0Y81M1 (Ashland Global Holdings Inc., ASH)
last_trade_date: 2016-09-19
value_rule: continuation
cash_per_share: -   cash_currency: -   stock_ratio: -   price_ticker: -   price_sec_id: -   price_date: -   recovery_ratio: -
value_formula: not an exit
event_type: reorganization
consideration: stock (1 for 1, no cash)
holder_value: 1 Ashland Global Holdings share per Ashland Inc. share
effective_date: 2016-09-20
successor_ticker: ASH
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-16-716025 (merger conversion one for one, Rule 12g-3 successor issuer).
- successor: filing, same 8-K (Ashland Global is successor issuer, lists as ASH on NYSE).
- last trade date: filing, Form 25-NSE 0000876661-16-001288 EX-99.25 and the 8-K (suspended prior to the open on 2016-09-20).
- payout rule: filing, same 8-K (shares converted into shares, no cash).
- terms: filing, same 8-K (one for one, none else).

## 5. What happened
- [SEC 8-K 2016-09-21](https://www.sec.gov/Archives/edgar/data/1305014/000119312516716025/d265419d8k.htm): each Ashland common share was converted into the right to receive one Ashland Global common share; Ashland Global is the successor issuer under Rule 12g-3; Ashland stock suspended from NYSE trading before the open on 2016-09-20; Ashland Global trades as ASH.
- [SEC 25-NSE 2016-09-20](https://www.sec.gov/Archives/edgar/data/1305014/000087666116001288/xslF25X02/primary_doc.xml): holding company formation effective 2016-09-20, each share deemed to represent one Ashland Global share; removal from listing only, not a termination of Ashland Global's registration.
- [SEC Form 15-12B 2016-09-30](https://www.sec.gov/Archives/edgar/data/1305014/000119312516727635/d151023d1512b.htm) closes Ashland Inc.'s registration.

## 6. Decision-tree bucket
Replaced 1:1 by a new line of the same holders: reorganization, exchange, continuation true.

## 7. Why the library got it wrong
The base run (sub-plan 5b) read the Form 25 plus the successor as a merger and priced a 1:1 stock leg on ASH; the successor link and holdco rule of 5c (stage 9 linking a transfer to what the registrant's filings say, one for one) now give the continuation. Cause (of the old row): holdco_not_linked. The new row is right.

## 8. Fix and open checks
No fix needed. Both the old and new rows agree on the date. Golden-worthy: yes (well sourced 1:1 holdco reorganization where the ticker is kept).

## 9. Verification
Upheld, all eight fields. Re-read 8-K 0001193125-16-716025 through sec.py: each Ashland share was converted into the right to receive one Ashland Global share (no cash); Ashland Global is the successor issuer under Rule 12g-3(a); Ashland stock was suspended on NYSE before the open on 2016-09-20 and Ashland Global trades as ASH. That is a 1:1 holdco continuation (decision 9), so exit_kind exchange, continuation true, value_rule continuation and blank stock terms are right. securities.csv shows BBG00D0Y81M1 as CIK 1674862 (Ashland Global), so the successor link is right.

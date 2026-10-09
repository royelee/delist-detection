# BBG000QL8VH9_5a-r1 (XON -> PGEN, Intrexon / Precigen), regression mode

## 1. Verdict
Nothing ended. Intrexon moved NYSE to Nasdaq in Sept 2018 (same shares, ticker XON) and renamed itself Precigen, ticker PGEN, effective 2020-02-01. The new run is right to drop the 2020-01-31 `exchange`/`transfer` ending, to show XON continuing to 2020-02-04 then PGEN, and to rename the placeholder to the FIGI.

## 2. Library vs evidence
| Field | old (base) | new (now) | evidence | right |
| --- | --- | --- | --- | --- |
| delistings row | exit_kind=exchange, continuation=false, last_trade 2020-01-31, value_rule=transfer | no contract row (internal 2018-10-04 transfer has successor = itself) | no ending in 2020; the only Form 25 is the NYSE withdrawal of 2018-09-24 with a Nasdaq 8-A12B the same day | new |
| ticker ranges | XON 2013-08-13..2020-01-31 | XON ..2020-02-04, PGEN 2020-02-05.. | name change effective 2020-02-01 (8-K 2020-02-04); 8-K cover shows PGEN on Nasdaq Global Select | new |
| sec_id | CIK1356090-COMMON | BBG000QL8VH9 | a FIGI confirmed by ticker/CUSIP history | new |
| issuer | 1356090 | 1356090 | same registrant | agree |

## 3. Corrected classification
```
event_type: name_change (plus 2018 NYSE->Nasdaq exchange_transfer, same security)
exit_kind: (no ending)   drop_reason:   continuation: n/a   successor: none (same security)
last_trade_date: n/a
value_rule: continuation (not an exit)  cash_per_share:   cash_currency:   stock_ratio:
price_ticker:  price_sec_id:  price_date:  recovery_ratio:
value_formula: not an exit
consideration: none   holder_value: same shares   effective_date: 2020-02-01   successor_ticker: PGEN
confidence: verified
```

## 4. Why this confidence
- exit kind: filing, 8-K 0001193125-20-023400 (name change only; Item 2.01 is a sale of assets, not of the company's shares).
- successor: filing, same registrant CIK 1356090 files under the new name.
- last trade date: not applicable, no ending.
- payout rule: filing, holders keep their shares.
- terms: none apply.
The CUSIP changed (46122T102 to 74017N105, fails rows) with the name; that is a rename, one for one.

## 5. What happened
- 2018-09-24: Form 25 (NYSE, voluntary withdrawal, 12d2-2(c)) and 8-A12B the same day for Nasdaq listing [SEC 25 0001193125-18-281308](https://www.sec.gov/Archives/edgar/data/1356090/000119312518281308/d612803d25.htm); the 3.01 8-K of 2018-09-12 announced the transfer.
- 2020-01-31: Intrexon sold bioengineering assets to TS Biotechnology (Item 2.01); the company continued.
- Name changed to Precigen, Inc., effective 2020-02-01, ticker PGEN on Nasdaq [SEC 8-K 2020-02-04](https://www.sec.gov/Archives/edgar/data/1356090/000119312520023400/d876809d8k.htm). Fails rows show PGEN from 2020-02-05.

## 6. Decision-tree bucket
Kept the same security (rename, same issuer and holders).

## 7. Why the library got it wrong
The base run read the 2020-01-31 asset sale / name change as an ending (cause `rename_not_followed`); the new run follows the rename. The library's old row was wrong, the new run is right.

## 8. Fix and open checks
No fix needed. Whether the base's row came from a handoff of the XON and PGEN ranges is moot now. A golden case (rename with a CUSIP change and an asset sale in the same week) is worthwhile.

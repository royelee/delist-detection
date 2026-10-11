# BBG000D4LWF6_fb3-r1 (MDLZ, regression)

## 1. Verdict
Kraft Foods Inc. Class A never ended. In June 2012 it moved its listing from the NYSE to NASDAQ (Form 25 plus 8-A12B, same security, still KFT), and in October 2012 it was renamed Mondelez (CUSIP 50075N104 to 609207105, same issuer CIK 1103982, same class). The new run is right to publish no ending (old: an `exchange` continuation row dated 2012-10-01). The new run's ticker ranges are worse than the old ones: they flip KFT/MDLZ/KFT/MDLZ.

## 2. Library vs evidence
| field | old (base) | new | evidence | status |
|---|---|---|---|---|
| delistings (row) | exchange, continuation to itself, last trade 2012-10-01, value_rule continuation | no row | The only Form 25 (2012-06-25, 0001193125-12-282307) is the NYSE to NASDAQ move; 8-K 3.01 (0001193125-12-264319) says the stock "will continue to trade under the stock symbol KFT on NASDAQ"; 8-A12B filed the same day (0001193125-12-282325). Nothing ended on 2012-10-01 (that is the spin-off of Kraft Foods Group and the rename, 8-K 0001193125-12-411522). | new right (no ending) |
| security_history.ranges | KFT 2007-12-26..2012-10-01; MDLZ 2012-10-05.. | KFT ..2012-10-04; MDLZ 2012-10-05..14; KFT 2012-10-15..18; MDLZ 2012-10-19.. | One security, one ticker change KFT to MDLZ at the Oct 1-2 2012 rename. Fails rows: CUSIP 50075N104 under KFT 20120904..20121016 (settlement tail of the old CUSIP), 609207105 under MDLZ from 20121005. The new alternation is an artifact of the old CUSIP's fails tail, not of trading. | old closer (clean order); neither exact |
| id_changes.sec_id | CIK1103982-COMMON | BBG000D4LWF6 | Same issuer, same class A; the FIGI line is the same security. | new right (a placeholder now holds its FIGI) |
| issuer | 1103982 | 1103982 | agree | agree |

## 3. Corrected classification
```
exit_kind: (no ending)       drop_reason:            continuation: n/a   successor: n/a
last_trade_date: n/a         value_rule: n/a
event_type: exchange_transfer (2012-06) then name_change/ticker_change (2012-10)
consideration: none          holder_value: same shares
effective_date: 2012-06-26 (listing move); 2012-10-01 (rename)   successor_ticker: MDLZ
ticker ranges: KFT 2007-12-26..2012-10-01 ; MDLZ 2012-10-02.. (first fails row 2012-10-05 settles late)
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 3.01 0001193125-12-264319, Form 25 0001193125-12-282307, 8-A12B 0001193125-12-282325).
- successor: n/a, same security.
- last trade date: n/a (no ending).
- payout rule / terms: n/a.
- ticker ranges: fails rows plus 8-K 0001193125-12-411522 and 0001193125-12-416762 (the October 1 effective time); the exact first MDLZ trading day (2012-10-02) is not stated in a filing I read. A filing or exchange print stating it would make this verified.

## 5. What happened
- [SEC 8-K 2012-06-08](https://www.sec.gov/Archives/edgar/data/1103982/000119312512264319/d366358d8k.htm): voluntary NYSE withdrawal, transfer to NASDAQ, continues as KFT.
- [SEC Form 25 2012-06-25](https://www.sec.gov/Archives/edgar/data/1103982/000119312512282307/d368794d25.htm): NYSE removal, Class A Common Stock; 8-A12B filed the same day.
- [SEC 8-K 2012-10-01](https://www.sec.gov/Archives/edgar/data/1103982/000119312512411522/d418430d8k.htm): Mondelez (formerly Kraft Foods Inc.) completed the spin-off of Kraft Foods Group at 5 p.m. EDT Oct 1; holders keep their shares and receive KFG shares.
- [SEC 8-K 2012-10-05](https://www.sec.gov/Archives/edgar/data/1103982/000119312512416762/d420449d8k.htm): reports the spin-off under the new name.
- Fails rows: 50075N104 as KFT to 20121016; 609207105 as MDLZ from 20121005.

## 6. Decision-tree bucket
Kept the same security (an exchange move, then a rename with a CUSIP change). The spin-off pays holders a dividend in KFG shares and does not end their claim.

## 7. Why the library got it wrong
In the new run the right thing happened for the delisting (no row) and the clip that cut KFT at 2012-10-01 went with it. The ticker ranges now take the old CUSIP's fails tail under KFT (2012-10-15..18) as KFT sightings after MDLZ began, so the ranges alternate. Cause: `rename_not_followed` (the rename's old-CUSIP settlement rows are read as a return to KFT).

## 8. Fix and open checks
Ranges should end KFT when the new CUSIP's first row appears (the old CUSIP's `...ZZZZ`/settle tail should not reopen a ticker already replaced by the same security's new one). Open: the first MDLZ trading day from a filing. Golden candidate: yes, as a no-ending case with one ticker change.

## 9. Verification
Re-opened through sec.py. Upheld: delistings.removed (new). The only Form 25 (0001193125-12-282307, 2012-06-25) has the same-day 8-A12B (0001193125-12-282325) and the 3.01 8-K of 2012-06-08 (0001193125-12-264319) is a move to NASDAQ; the 2012-10-01 8-K (0001193125-12-411522) is a rename (Item 5.03) and spin-off, not an ending. Upheld: id_changes.sec_id (new), same issuer 1103982 and class.
Refuted: security_history.ranges "old". The old value is not right either: its MDLZ range starts 2012-10-05 (first fails row) while the rename took effect 2012-10-01 (8-K 0001193125-12-411522) and the report's own corrected ranges say MDLZ from 2012-10-02. The new value is wrong too (KFT reopens 2012-10-15..18 from the old CUSIP's settlement tail; fails: 50075N104 under KFT 20120904..20121016). Neither side is right; "old closer" is not "old right".

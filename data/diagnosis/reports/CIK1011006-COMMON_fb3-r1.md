# CIK1011006-COMMON_fb3-r1 (AABA, regression)

## 1. Verdict
Yahoo! Inc. (YHOO) renamed itself Altaba Inc. (AABA) on 2017-06-16 and kept the same registrant, listing and share (new CUSIP, no exchange of shares), so the 2017 "exchange" ending in the base run was not an ending. The real and only ending is the Nasdaq removal after the Plan of Complete Liquidation and Dissolution: last trade 2019-10-02. The new run is right on the last trade date and on the continuous ticker range; its blank exit kind and `unknown` value rule are still wrong (the ending is a liquidation).

## 2. Library vs evidence (old = base run, new = this run)
| field | old says | new says | evidence says | status |
| --- | --- | --- | --- | --- |
| last_trade_date | 2017-06-16 | 2019-10-02 | 2019-10-02: Nasdaq halted trading after the close on 2019-10-02 ([SEC 8-K 2019-10-04](https://www.sec.gov/Archives/edgar/data/1011006/000119312519262790/d794671d8k.htm)) | old wrong, new agree |
| exit_kind | exchange | blank | liquidation (dissolution under a liquidation plan; no merger, no bankruptcy) | both wrong |
| value_rule | transfer | unknown | recovery (liquidating distributions); amount not stated in the filings read | both wrong |
| security_history.ranges | YHOO to 2017-06-16 only | YHOO 2007-12-17..2017-06-20, AABA 2017-06-21..2019-10-02 | one security: YHOO through 2017-06-16, AABA from 2017-06-19 (8-K 2017-06-19: AABA and new CUSIP 021346101 from the open of 2017-06-19) to 2019-10-02 | new right (AABA start 2 days late, fails-row dating) |
| issuer | CIK 1011006 | CIK 1011006 | CIK 1011006, same registrant | agree |
| successor / continuation | exchange, none | none | none; not a continuation | new agree |

## 3. Corrected classification
```
exit_kind: liquidation     drop_reason:      continuation: false   successor: none
last_trade_date: 2019-10-02
value_rule: recovery  cash_per_share: (liquidating distributions, amounts not read)  cash_currency: USD
stock_ratio:   price_ticker:   price_sec_id:   price_date: 2019-10-03  recovery_ratio: unknown
value_formula: sum of post-dissolution liquidating distributions per share / last_close - 1
event_type: liquidation   consideration: other (liquidating distributions)   holder_value: pro rata liquidating distributions
effective_date: 2019-10-04 (dissolution)   successor_ticker:   confidence: inferred
```

## 4. Why this confidence: inferred
- exit kind: filing (8-K 2019-09-23 and 2019-10-04: Plan of Complete Liquidation and Dissolution, certificate of dissolution effective 4:00 p.m. 2019-10-04).
- successor: filing (none named; shares not transferable after dissolution).
- last trade date: filing (8-K 2019-10-04: "Nasdaq halted trading in the Shares on Nasdaq following the close of regular trading on October 2, 2019"; suspended before the 2019-10-07 open). Fails rows of CUSIP 021346101 run to 2019-10-04 ($19.63, settling tail).
- payout rule: filing for the kind; worked out for `recovery` (distribution amounts and timing not read).
- terms: not backed. Would be verified by the Fund's later 8-Ks or reports stating each liquidating distribution per share.

## 5. What happened
- 2017-06-13 sale of the operating business to Verizon; 2017-06-16 renamed Altaba, registered as a closed-end fund; ticker AABA and CUSIP 021346101 from 2017-06-19, same Nasdaq listing ([SEC 8-K 2017-06-19](https://www.sec.gov/Archives/edgar/data/1011006/000119312517206955/d389206d8k.htm)).
- 2019-09-23 Fund announces certificate of dissolution to be filed after the close on 2019-10-04 ([SEC 8-K](https://www.sec.gov/Archives/edgar/data/1011006/000119312519252251/d808429d8k.htm)).
- 2019-10-04 dissolution effective 4 p.m.; transfer books closed; Nasdaq halted after the 2019-10-02 close and suspended trading before the 2019-10-07 open ([SEC 8-K](https://www.sec.gov/Archives/edgar/data/1011006/000119312519262790/d794671d8k.htm)).
- 2019-10-07 Form 25-NSE by Nasdaq under 12d2-2(b) ([SEC 25-NSE 0001354457-19-000499](https://www.sec.gov/Archives/edgar/data/1011006/000135445719000499/xslF25X02/primary_doc.xml)).

## 6. Decision-tree bucket
2017: kept the same security (rename, same registrant and listing). 2019: lost to a solvent liquidation.

## 7. Why the library got it wrong
Base run: the 2017 name change with a new CUSIP was read as an exchange transfer ending (rename_not_followed) and the 2019 ending was not the row's. New run: the rename is followed, but the 2019 Form 25-NSE row is `unknown` (`no_evidence_default`) because the dissolution 8-K (Item 7.01, not 3.01 or 1.03) is not read as a liquidation. Cause tag: other:liquidation_item_7_01_not_read.

## 8. Fix and open checks
Read the plan-of-dissolution 8-K (7.01) as a liquidation; find the liquidating distribution amounts and dates. Good golden candidate (last trade and rename well sourced).

## 9. Verification
Skeptic re-read 8-K 0001193125-19-262790 (2019-10-04), 8-K 0001193125-17-206955 (2017-06-19), the filing list for 2019-09-15..10-15 and the fails rows of CUSIP 021346101.
- last_trade_date 2019-10-02 (new): upheld. "Nasdaq halted trading in the Shares on Nasdaq following the close of regular trading on October 2, 2019"; suspended before the 2019-10-07 open; 25-NSE 2019-10-07.
- exit_kind liquidation (neither): upheld. The text speaks of a certificate of dissolution and post-dissolution liquidating distributions; no merger, no bankruptcy; the new blank is wrong.
- value_rule recovery (neither): upheld; amounts unread, so unknown is wrong.
- security_history.ranges (new): REFUTED as stated. The 2017-06-19 8-K puts AABA and CUSIP 021346101 from the open of 2017-06-19 and YHOO traded "through June 16, 2017". The new run (YHOO to 2017-06-20, AABA from 2017-06-21; fails rows of 021346101 start 2017-06-21, a settling lag) is days off on both boundaries, and the old run had no AABA range. Right side: neither. True: YHOO 2007-12-17..2017-06-16, AABA 2017-06-19..2019-10-02, CIK 1011006.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the 2017 YHOO to AABA rename no ending, and the new run's 2019 liquidation ending dated right (last trade 2019-10-02) but left unclassified; the change is the library getting better. Classifying and valuing it is batch 4's liquidation reader (FB-002).

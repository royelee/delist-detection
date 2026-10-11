# BBG00RRH0RM9_fb3-r1 (GDI, regression)

## 1. Verdict
Gardner Denver Holdings (CIK 1699150) did not end: on 2020-03-02 it closed the Ingersoll Rand Industrial Reverse Morris Trust and renamed itself Ingersoll Rand Inc. (NYSE: IR), same registrant, same shares, new CUSIP. The new run (continuation to the IR line) is right; the base run (exchange, not a continuation, no successor, value rule transfer) is the weaker answer.

## 2. Library vs evidence
| field | old (base) | new (run) | evidence | right |
| --- | --- | --- | --- | --- |
| continuation | false | true | holders kept their shares one for one, no cash; registrant renamed | new |
| successor_sec_id | blank | BBG002R1CW27 (IR) | IR line begins 2020-03-04 under CUSIP 45687V106, same CIK | new |
| value_rule | transfer | continuation | no exit, no value | new |
| exit_kind | exchange | exchange | both agree | agree |

## 3. Corrected classification
```
exit_kind: exchange
continuation: true
successor: BBG002R1CW27 (IR)
last_trade_date: 2020-02-28 (not published by the contract; fails rows end 2020-02-27 settle date)
value_rule: continuation
event_type: reorganization (rename with RMT)
consideration: none
successor_ticker: IR
```

## 4. Why this confidence
Confidence: inferred.
- exit kind: filing (8-K 0001140361-20-004816 names the registrant "Ingersoll Rand Inc. (formerly Gardner Denver Holdings, Inc.)").
- successor: filing (same CIK) plus fails rows (CUSIP 45687V106 trades as IR from 2020-03-04).
- last trade date: worked out from fails rows (GDI CUSIP 36555P107 last row 20200227); no exchange print or filing read.
- payout rule: filing (no exchange of shares in the 8-K).
- terms: none needed.
Not backed: an exchange-printed last day. A filing or MIDAS print stating it would make this verified.

## 5. What happened
- [SEC 8-K 2020-03-04](https://www.sec.gov/Archives/edgar/data/1699150/000114036120004816/form8k.htm): Ingersoll Rand Inc. (formerly Gardner Denver Holdings) consummated the RMT on 2020-03-02; registrant on NYSE as IR.
- Fails rows: CUSIP 36555P107 (GDI) rows 2020-02-06..02-27; CUSIP 45687V106 (IR) from 2020-03-04.
- No Form 25 in CIK 1699150's filings 2020-02-01..04-15.

## 6. Decision-tree bucket
Kept the same security (a rename of the same registrant; the new CUSIP and FIGI come with the rename), so holders lost nothing. A continuation to the IR line is the acceptable model.

## 7. Why the library differs
Base run: no_form25, continued-filings transfer with no successor link. New run links the line successor (line follow). Cause: other:base lacked the line link (successor_not_in_run); the new run is right.

## 8. Fix and open checks
None needed. Open: an exchange-printed last trade day. Golden-worthy.

## 9. Verification
Upheld all three fields. Re-opened 8-K 0001140361-20-004816 (filed 2020-03-04, CIK 1699150): registrant "Ingersoll Rand Inc.", former name Gardner Denver Holdings, Inc., same file number 001-38095, common stock symbol IR on the NYSE; Item 1.01 says the RMT closed 2020-03-02. The filing list for CIK 1699150 for 2020-03 shows no Form 25 or Form 15, so the registrant and its listing continued. The run has BBG002R1CW27 (IR, CIK 1699150, COMMON, CUSIP 45687V106 from 2020-03-04) beside BBG00RRH0RM9 (GDI, ends 2020-02-28); the contract row is exit_kind exchange, continuation true, successor BBG002R1CW27, value_rule continuation. Weak spot, not a field verdict: the last trade date rests on fails rows only.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (GDI renamed Ingersoll Rand Inc., a continuation).

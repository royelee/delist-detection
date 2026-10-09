# BBG000BL9JQ1_5c-r1 (HFC, HollyFrontier) - regression diagnosis

## 1. Verdict
On 2022-03-14 HollyFrontier became a subsidiary of the new holding company HF Sinclair (DINO); each HFC share converted into one HF Sinclair share, no cash. This is a 1:1 holdco reorganization, a continuation. The NEW row (exchange, continuation true, successor BBG0135B2214, value_rule continuation) is right; the OLD row (merger, stock 1.0 DINO) is wrong.

## 2. Library vs evidence (old = base run, new = this run)
| field | old | new | evidence says | status of new |
| --- | --- | --- | --- | --- |
| exit_kind | merger | exchange | exchange (holdco reorganization) | agree |
| drop_reason | blank | blank | blank | agree |
| continuation | false | true | true | agree |
| successor | blank | BBG0135B2214 | HF Sinclair (DINO), CIK 1915657 | agree |
| last_trade_date | unchanged | 2022-03-14 (MIDAS) | DINO begins trading at start of 2022-03-15, so HFC's last day is 2022-03-14 | agree |
| value_rule | stock | continuation | continuation (not an exit; no value) | agree |
| terms | stock_ratio 1.0, DINO, 2022-03-15 | none | none for a continuation | agree |
| issuer | CIK 48039 | CIK 48039 | HollyFrontier, CIK 48039 | agree |
| ticker_history | HFC to 2022-03-14, DINO from 2022-03-16 | same | consistent | agree |

## 3. Corrected classification
```
exit_kind: exchange
drop_reason:
continuation: true
successor: BBG0135B2214
last_trade_date: 2022-03-14
value_rule: continuation
cash_per_share:
cash_currency:
stock_ratio:
price_ticker:
price_sec_id:
price_date:
recovery_ratio:
value_formula: not an exit (continuation into HF Sinclair, 1 for 1)
event_type: reorganization
consideration: stock (1 HF Sinclair share per HFC share, successor line, no cash)
holder_value: 1 share HF Sinclair Common Stock per HFC share
effective_date: 2022-03-14
successor_ticker: DINO
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K12B 0001193125-22-074381 (HFC Merger; HF Sinclair replaces HollyFrontier as the public company on NYSE).
- successor: filing, same 8-K12B (Rule 12g-3 successor issuer, symbol DINO).
- last trade date: filing, same 8-K12B (DINO begins trading at the start of 2022-03-15); Form 25-NSE 0000876661-22-000283 filed 2022-03-15.
- payout rule: filing, same 8-K12B (one-for-one conversion, no cash).
- terms: filing, same (one share per share; the Sinclair consideration went to Sinclair HoldCo, not to HFC holders).

## 5. What happened
- 2022-03-14: HFC Merger; each HFC share converted automatically into one HF Sinclair share. [SEC 8-K12B 2022-03-14](https://www.sec.gov/Archives/edgar/data/1915657/000119312522074381/d326950d8k12b.htm)
- HF Sinclair assumed HollyFrontier's NYSE listing; shares begin trading 2022-03-15 as DINO (same 8-K12B, Item 3.01 and Rule 12g-3 note).
- Sinclair HoldCo received 60,230,036 HF Sinclair shares for the Sinclair businesses; a separate issuance, not consideration to HFC holders (same 8-K12B).
- 2022-03-15: Form 25-NSE for HFC. [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/48039/000087666122000283/xslF25X02/primary_doc.xml)
- 2022-03-29 and 2022-04-29: Form 15-12B filings on HFC's CIK, the old registrant's deregistration (HFC filing list).

## 6. Decision-tree bucket
Replaced 1:1 by a new line of the same holders (holdco reorganization): exchange, continuation true, successor named.

## 7. Why the library got it wrong (old run)
The base run read the Form 25 as a merger and priced one DINO share per HFC share (stock rule). The new run's stage 9 successor link (the successor's 8-K12B, one for one) fixes it. Cause tag of the old behaviour: holdco_not_linked.

## 8. Fix and open checks
None needed; the new row is correct. Golden-worthy: yes (HFC 2022 holdco, clearly sourced).

## 9. Verification
Re-opened 8-K12B 0001193125-22-074381 (CIK 1915657) through sec.py. Items 2.01 and 3.03 state that each HFC share was automatically converted into one HF Sinclair share with the same designations and rights, and no cash is mentioned. Item 3.01 says HF Sinclair replaced HollyFrontier on the NYSE under DINO and began trading at the start of 2022-03-15. The 60,230,036 shares to Sinclair HoldCo are a separate issuance, not consideration to HFC holders. This is a one-for-one exchange with no cash, so decision 9 makes it a continuation, and the stage 9 link to BBG0135B2214 follows from the successor issuer's 8-K12B. The blank stock_ratio and price fields are right because a continuation has no value. All eight field verdicts survive. There is no mismatch-mode "library" verdict to check.

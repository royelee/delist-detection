# BBG00BFHDFR4_2023-08-13_wave2-r1 (FWONK, mismatch mode, field: legs)

## 1. Verdict
The truth file's two legs are right. The 2023-08-03 Reclassification gave each old Series C Formula One share one new FWONK share plus 0.0428 of a Liberty Live (LLYVK) share, so the holder received two securities and the row is a basket (R3), not a one-for-one continuation. The library publishes a continuation with no legs (0 legs): wrong on this field. No filing was missed by the earlier report; it cited the same 8-K.

## 2. Library vs evidence
| Field | Library says | Evidence says | Status |
| --- | --- | --- | --- |
| exit_kind | exchange | merger (basket, per truth) | wrong |
| drop_reason | none | none | agree |
| continuation | true | false (second security received: not one-for-one) | wrong |
| successor | BBG01HLMBCG3 | none; new FWONK line is leg 1 | wrong |
| last_trade_date | blank (internal 2023-08-04) | 2023-08-03 worked out (effective 5:00 pm 2023-08-03; new series expected to trade 2023-08-04) | wrong (internal) |
| value_rule | continuation | basket | wrong |
| terms (legs) | 0 legs | leg 1: ratio 1, FWONK (BBG01HLMBCG3); leg 2: ratio 0.0428, LLYVK (sec_id not in run); cash only for fractions | wrong |
| issuer | 1560385 | 1560385 | agree |
| ticker_history | old FWONK ends 2023-08-04 | old line should end 2023-08-03 | unknown |

## 3. Corrected classification
```text
exit_kind        = merger
drop_reason      =
continuation     = false
successor        =
last_trade_date  = (published only from an exchange print; none found)
value_rule       = basket
cash_per_share   =
cash_currency    =
stock_ratio      =
price_ticker     = FWONK (leg 1), LLYVK (leg 2)
price_sec_id     = BBG01HLMBCG3 (leg 1), * (leg 2)
price_date       = 2023-08-04
recovery_ratio   =
value_formula    = (1 x price(FWONK, 2023-08-04) + 0.0428 x price(LLYVK, 2023-08-04)) / last_close - 1
event_type       = reclassification of tracking stocks
consideration    = stock (1 new FWONK + 0.0428 LLYVK; cash in lieu of fractions)
holder_value     = 1 new Series C Liberty Formula One share + 0.0428 Series C Liberty Live share
effective_date   = 2023-08-03
successor_ticker = FWONK
confidence       = inferred
```

## 4. Why this confidence
Inferred.
- Exit kind: filing (8-K 0001104659-23-087380, Item 3.03).
- Successor: filing (same 8-K, new Series C Formula One stock).
- Last trade date: worked out from the 8-K's effective time and the stated first trading day; no print or notice states it.
- Payout rule: filing (two securities received per share).
- Terms: filing (1 and 0.0428, cash only for fractions).
- Not backed: an exchange print for the last old-line day; a MIDAS or Nasdaq record would make it verified.

## 5. What happened
- Restated Charter effective 5:00 p.m. 2023-08-03; each old Liberty Formula One share was reclassified into one share of the corresponding new series and 0.0428 of the corresponding Liberty Live series, cash in lieu of fractional Liberty Live shares ([SEC 8-K 2023-08-03](https://www.sec.gov/Archives/edgar/data/1560385/000110465923087380/)).
- Nasdaq Form 25-NSE 0001354457-23-000564 for the old series ([SEC](https://www.sec.gov/Archives/edgar/data/1560385/000135445723000564/)).

## 6. Decision-tree bucket
Replaced by something: a package of two securities, so not a 1:1 continuation (CLAUDE.md: a second leg after the first share is no one-for-one).

## 7. Why the library got it wrong
The ticker handoff (`handoff_continuation`, timing:cik) linked FWONK to the new line and no sub-plan reads a reclassification's second leg for a handoff row, so it publishes no basket legs. Cause tag: `other:handoff_continuation_ignores_second_leg`.

## 8. Fix and open checks
- Basket row with two legs in payout_legs.csv; leg 2's sec_id is unscored until the run holds LLYVK.
- Open: exchange print for the old line's last day (2023-08-03).
- Golden case: yes (already in the truth set as known_wrong).

## 9. Verification
Upheld. Re-opened 8-K 0001104659-23-087380 (CIK 1560385) through sec.py. Item 3.03: each outstanding Liberty Formula One share was reclassified into one share of the corresponding series of new Liberty Formula One stock and 0.0428 of a share of the corresponding series of Liberty Live stock, cash only in lieu of fractional Liberty Live shares; Restated Charter effective 5:00 p.m. 2023-08-03; new series (FWONK, LLYVK) expected to trade from 2023-08-04. Series C maps to FWONK and LLYVK. Two securities per old share, so basket (R3), not an R1 continuation; the library's 0 legs is wrong. The field verdict names no missed filing, and none is needed.

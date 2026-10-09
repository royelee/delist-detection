# BBG00BFHDCV6_2023-08-13_wave2-r1 (FWONA, old Liberty Formula One Series A) - mismatch on `legs`

## 1. Verdict

The truth is right. The 2023-08-03 reclassification gave each old FWONA share one new FWONA share plus 0.0428 Series A Liberty Live (LLYVA), a one-to-many reclassification. Under ruling R3 that is a `basket` with two legs, not an R1 continuation (R1 needs exactly one new share and nothing else). The library publishes a continuation with 0 legs, so the truth's 2 legs mismatch. The earlier report called it a continuation with the Live shares as a distribution; the truth row supersedes that under R3. No missed filing: the same 8-K the earlier report cited gives both legs.

## 2. Library vs evidence

| Field | Library says (side_b) | Evidence / truth (side_a) | Status |
| --- | --- | --- | --- |
| legs | 0 legs (value_rule continuation, successor BBG01HLMB809, no payout_legs rows) | 2 legs: leg 1 ratio 1 new FWONA (BBG01HLMB809), leg 2 ratio 0.0428 LLYVA (sec_id not yet in the run, `*`) | wrong |
| exit_kind / continuation | exchange / true | merger-type basket, continuation false (R1: more than one share per old share; the Live leg is a second security) | wrong (not a field of this case) |
| last_trade_date | blank | blank published; internal 2023-08-03 (8-K: Restated Charter effective 5:00 pm NYC time 2023-08-03, new series to begin trading 2023-08-04); library's internal 2023-08-04 is the last sighting | not a field of this case |
| issuer | 1560385 | 1560385 | agree |

## 3. Corrected classification

```text
exit_kind        = merger
continuation     = false
successor        =
last_trade_date  = (not published) internal 2023-08-03
value_rule       = basket
cash_per_share   =
legs             = 1: 1.0 x FWONA (BBG01HLMB809); 2: 0.0428 x LLYVA (sec_id * until the run holds it)
value_formula    = (1 x price(FWONA) + 0.0428 x price(LLYVA)) / last_close - 1
event_type       = reclassification (tracking stock, one-to-many)
effective_date   = 2023-08-03
confidence       = inferred
```

## 4. Why this confidence

Inferred.
- Exit kind: filing (8-K 0001104659-23-087380 item 3.03: one new FWONA plus 0.0428 LLYVA, cash only for fractions); the merger-versus-continuation call is the operator's R3 ruling.
- Successor: filing (same 8-K names the new Series A Liberty Formula One, FWONA).
- Last trade date: worked out from the 5:00 pm effective time and the 2023-08-04 start of trading; no filing says the old line stopped.
- Payout rule: filing for the terms, ruling R3 for `basket`.
- Terms: filing (1 and 0.0428); price date follows a published last trade, so blank.
- Not backed: a stated last trade (an exchange notice would settle it); the LLYVA sec_id.

## 5. What happened

- Restated Charter effective 5:00 pm NYC 2023-08-03; each Liberty Formula One share was reclassified into one share of the corresponding series of new Liberty Formula One and 0.0428 of the corresponding Liberty Live share, cash for fractional Live shares ([SEC 8-K 2023-08-03](https://www.sec.gov/Archives/edgar/data/1560385/000110465923087380/tm2320270d12_8k.htm)).
- New FWONA and LLYVA expected to begin trading on Nasdaq 2023-08-04 (same 8-K).
- Form 25-NSE 0001354457-23-000564 filed for the old series ([SEC](https://www.sec.gov/Archives/edgar/data/1560385/000135445723000564/xslF25X02/primary_doc.xml)).

## 6. Decision-tree bucket

Replaced: the holder got two securities per share, so by R1 and R3 it is a basket, not a one-for-one continuation.

## 7. Why the library got it wrong

The handoff stage linked the row as `handoff_continuation` by timing and CIK (`continuation_by_timing_only`), and no stage reads the reclassification's second leg for a handoff row, so the basket and its legs are never built. Cause: `other:one_to_many_reclassification_read_as_continuation`.

## 8. Fix and open checks

- A handoff row whose own 8-K 3.03 states a second share should become a basket with both legs (5f's basket work).
- LLYVA sec_id: confirm the run holds Liberty Live before scoring leg 2.
- Golden-worthy: yes, once the basket and the internal date are both fixed.

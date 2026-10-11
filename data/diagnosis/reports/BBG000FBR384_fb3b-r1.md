# BBG000FBR384_fb3b-r1 (BEAM, regression, security_history.ranges)

## 1. Verdict

Fortune Brands renamed itself Beam Inc. (same CIK 789073) effective 12:01 a.m. on 2011-10-04, after the spin-off of Fortune Brands Home & Security on 2011-10-03. The ticker history should switch from FO to BEAM at 2011-10-04. The old ranges (BEAM from 2011-10-07) and the new ranges (BEAM from 2011-10-06) are both late; the new one is closer. Neither is right.

## 2. Library vs evidence

Changed field: `security_history.ranges`.

| Field | Library says (old / new) | Evidence says | Status |
| --- | --- | --- | --- |
| ticker_history | old: FO 2008-01-16..2011-10-06, BEAM 2011-10-07..2014-04-30. new: FO ..2011-10-05, BEAM 2011-10-06..2014-04-30 | FO through 2011-10-03, BEAM from 2011-10-04 (name change effective 12:01 a.m. 2011-10-04) | wrong (both; new is 2 days late, old 3) |
| issuer | CIK 789073 | CIK 789073 throughout (same registrant renamed) | agree |
| exit_kind, drop_reason, continuation, successor, last_trade_date, value_rule, terms | not examined | not examined; the case is only about the ticker ranges | unknown |

Both library variants read the ticker switch from the CUSIP change (cusip_history: 349631101 to 2011-10-06, 073730103 from 2011-10-07, source ftd) and from fails-to-deliver rows. Fails rows lag the trade date. BEAM's CUSIP rows start 20111005 and FO's end 20111006, which are settlement-date artefacts of trades on 10-04 and earlier.

## 3. Corrected classification

```
ticker_history: FO 2008-01-16..2011-10-03 ; BEAM 2011-10-04..2014-04-30
exit_kind / drop_reason / continuation / successor / last_trade_date: unchanged (not examined)
value_rule: unchanged (not examined)
event_type: name_change (ticker change FO -> BEAM, after a spin-off of FBHS)
effective_date: 2011-10-04
confidence: inferred
```

## 4. Why this confidence

inferred.
- exit kind: not examined here.
- successor: not examined here.
- last trade date: not examined here.
- payout rule: not examined here.
- terms: not examined here.
- ticker switch date: the name change date rests on a filing (8-K Item 5.03). The first BEAM trading day is worked out: the filing states the name change but not the NYSE ticker or the first session. A rename effective at 12:01 a.m. on 2011-10-04 (Tuesday) implies the first BEAM session was 2011-10-04. The filing also states FBHS began trading on the NYSE on 2011-10-04. To make this verified, an exchange or press notice stating "BEAM begins trading on October 4" is needed.

## 5. What happened

- 2011-10-03: Fortune Brands completed the spin-off of Fortune Brands Home & Security by distributing 100% of its shares. No consideration, no exchange of shares. [SEC 8-K 2011-10-07, 0001193125-11-266911](https://www.sec.gov/Archives/edgar/data/789073/000119312511266911/d240798d8k.htm)
- 2011-10-04: FBHS began trading on the NYSE. Same filing.
- Effective 12:01 a.m. 2011-10-04: Fortune Brands, Inc. changed its name to Beam Inc. (Item 5.03), with the company the surviving corporation. Same filing.
- Fails rows for CUSIP 073730103 (BEAM) start 20111005; for CUSIP 349631101 (FO) they end 20111006. [fails rows, sec.py fails]

## 6. Decision-tree bucket

Kept the same security (same registrant, same issuer CIK, renamed). Not an ending.

## 7. Why the library got it wrong

The ticker switch date is taken from fails-to-deliver rows and the CUSIP history, which lag the real first session by a settlement cycle or more. The change moved it one day earlier but it did not reach the filing's date. Cause: `other:ticker_switch_from_fails_lag`.

## 8. Fix and open checks

- Take the switch from the 8-K Item 5.03 name-change effective date (2011-10-04) when it is later than the last fails row of the old ticker is not required; the filing date wins.
- Open: confirm the first BEAM session with an exchange or press source (not market prices).
- Golden candidate: no (inferred, not filing-stated for the ticker).

## 9. Verification

Skeptic re-check, mode regression. Field verdict: `security_history.ranges`, right = neither, value `FO:2008-01-16..2011-10-03;BEAM:2011-10-04..2014-04-30`. Result: upheld.

- Re-read the 8-K 0001193125-11-266911 (filed 2011-10-07, CIK 789073) through sec.py grep. Item 5.03: name change to Beam Inc. effective 12:01 a.m. on October 4, 2011, same registrant surviving (Section 253 merger). It says the outstanding shares "will continue to trade on the New York Stock Exchange, under the new symbol 'BEAM'", new CUSIP 073730 103. Same CIK, same class (common): a rename, not an ending.
- Item 2.01: spin-off completed 2011-10-03; FBHS began trading 2011-10-04.
- Item 5.02: option exercise price $44.75 is "the closing price per share of the Company's common stock on the NYSE on October 4, 2011", so the common traded on 2011-10-04, after the 12:01 a.m. rename. This supports BEAM as the 2011-10-04 symbol.
- Both library ranges (BEAM from 2011-10-07, and from 2011-10-06) start after 2011-10-04, so "neither" holds. The fails-based CUSIP dates (settlement lag) explain the lateness.
- Not refuted. Weakness kept: no filing names the first session's ticker, so confidence stays inferred. Not a golden candidate.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (8-K 5.03: BEAM from 2011-10-04; base 10-07, new 10-06). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

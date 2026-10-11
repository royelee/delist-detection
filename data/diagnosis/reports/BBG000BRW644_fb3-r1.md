# BBG000BRW644_fb3-r1 (EPC, regression, security_history.ranges)

## 1. Verdict
Edgewell Personal Care (CIK 1096752) is the old Energizer Holdings renamed on 2015-06-30; it traded as ENR until the spin-off of "New Energizer" and as EPC after. The new run's added ENR range (2007-12-17..2015-07-01) is right, since the base run dropped 7.5 years of this security's history. Its R108 range (2015-07-02..05) is a bogus ticker, and the EPC start of 2015-07-06 is the fails file's first row, not the first trading day. Neither side is exactly right; the new one is closer.

## 2. Library vs evidence
| field | base (old) says | new says | evidence says | status |
|---|---|---|---|---|
| security_history.ranges | EPC:2015-07-06.. only | ENR:2007-12-17..2015-07-01; R108:2015-07-02..2015-07-05; EPC:2015-07-06.. | ENR until the spin (last day about 2015-06-30/07-01), EPC from about 2015-07-01; no ticker R108 | new: ENR right, R108 wrong, EPC start late |
| issuer | 1096752 | 1096752 | 1096752 (same registrant, renamed) | agree |
| exit_kind etc. | none (security still listed) | none | no ending | agree |

## 3. Corrected classification
```
exit_kind: (none, listed today)   successor: (none)
ticker ranges: ENR 2007-12-17..2015-06-30 ; EPC 2015-07-01..   (issuer 1096752)
event_type: rename + spin-off of New Energizer (new CIK, new FIGI line)
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: no ending; Edgewell is the same registrant (8-K 0001193125-15-242462).
- successor: none.
- last ENR day / first EPC day: fails rows (ENR rows to 2015-07-01 at the settled close; EPC rows from 2015-07-06 on new CUSIP 28035Q102) and the 8-K, which gives the name change (effective 2015-06-30) and New Energizer's ENR regular-way start on 2015-07-01; the exact EPC first day is worked out, not read.
- payout rule, terms: not applicable.
To verify: an NYSE notice or press release stating EPC's first regular-way day.

## 5. What happened
- Name changed Energizer Holdings, Inc. to Edgewell Personal Care Company, effective 2015-06-30 [SEC 8-K 2015-07-01](https://www.sec.gov/Archives/edgar/data/1096752/000119312515242462/d40769d8k.htm).
- New Energizer (spun off, separate registrant) began regular-way trading as ENR on 2015-07-01, same 8-K.
- Fails rows: CUSIP 29266R108 under ENR 2015-06-01..07-01, then under "R108" 2015-07-02..07-08 at the unchanged settled price $131.55 (settlement tail, masked symbol); CUSIP 28035Q102 under EPC from 2015-07-06.

## 6. Decision-tree bucket
Kept the same security (rename; the holder keeps the same shares, in addition to receiving New Energizer shares).

## 7. Why the library got it wrong
Base: the ENR era's history was dropped, only the new CUSIP's range was kept. New: the old CUSIP's settle tail under the masked symbol "R108" is read as a ticker sighting, and the EPC range starts at its first fails row. Cause: other:fails-file masked symbol (CUSIP tail R108) taken as a ticker.

## 8. Fix and open checks
Do not treat a symbol equal to the last four characters of the CUSIP, with a flat settled price, as a ticker sighting; the old ticker should run to the day before EPC begins. Not a golden case until the dates are sourced.

## 9. Verification
Upheld: right = neither, value ENR:2007-12-17..2015-06-30;EPC:2015-07-01.. .
- 8-K 0001193125-15-242462 (CIK 1096752) states in Item 3.03/5.03 that the Company's common stock "began regular-way trading on the NYSE under the symbol 'EPC' with the CUSIP No. 28035Q 102 on July 1, 2015", and that New Energizer began as ENR on July 1, 2015. So the EPC first day is read, not worked out (stronger than section 4 says), and the new run's EPC start of 2015-07-06 is late.
- Fails rows of CUSIP 29266R108: ENR 2015-06-01..07-01 (last $131.55, the 06-30 close, as rows are priced at the prior close), then symbol R108 2015-07-02..07-08 flat at $131.55: a settlement tail, not a ticker. R108 is bogus. ENR runs to 2015-06-30.
- Same registrant and issuer 1096752 throughout; the new run's ENR start (2007-12-17) is not contradicted. Neither the base (EPC from 07-06 only) nor the new run matches. No missed filing.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run keeps the ENR 2007-2015 history the base dropped, and adds a six-day range under the masked settle-tail symbol R108 (2015-07-02..07-08) with EPC starting 2015-07-06 instead of 2015-07-01. The change is the library getting better; the masked-symbol tail is a residual for a later batch.

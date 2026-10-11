# BBG006FCB019 (ENR) - regression, field security_history.ranges

## 1. Verdict
New Energizer Holdings (CIK 1632790, ENR) is a different security from the old Energizer Holdings (CIK 1096752), which became Edgewell Personal Care (EPC) in the 2015-07-01 spin-off. The new run is right to stop attributing the 2007-2015 ENR range and CIK 1096752 to this FIGI; only its start day (07-02, the first fails row) is a day after the filing-stated first regular-way trading day (07-01).

## 2. Library vs evidence
| field | old (base run) | new (this run) | evidence | status |
|---|---|---|---|---|
| security_history.ranges | ENR 2007-12-17..2015-06-30 issuer 1096752; ENR 2015-07-01.. issuer 1632790 | ENR 2015-07-02.. issuer 1632790 | The 1096752 pre-spin range belongs to Edgewell (BBG000BRW644, CUSIP 29266R108, split off by id_changes). New ENR has CUSIP 29272W109, first fails row 2015-07-02. | new right (start day off by one: the 8-K says regular-way trading began 2015-07-01) |
| exit_kind / successor / last_trade_date / value_rule / terms | no ending | no ending | no delisting; the security is listed today | agree |
| issuer | 1096752 then 1632790 | 1632790 | the new registrant, formerly Energizer SpinCo | new right |

## 3. Corrected classification
```
sec_id: BBG006FCB019 (new Energizer Holdings, CIK 1632790)
ranges: ENR 2015-07-01.. issuer 1632790 (fails data first shows 2015-07-02)
exit_kind: none (active); the 2015-07-01 event is a spin-off of the new company, not an ending of this security
event_type: spin_off   confidence: inferred
```

## 4. Why this confidence
inferred. Issuer split: filing (Edgewell 8-K 0001193125-15-242462: spin-off completed 2015-07-01, New Energizer "began regular-way trading on the NYSE under the symbol ENR on July 1, 2015"; registrant is "Edgewell Personal Care Company (formerly Energizer Holdings, Inc.)"). The range start day: the filing states 07-01 but the library's range comes from fails rows (first 07-02), so the exact day is not backed by the run's own data.

## 5. What happened
- [SEC 8-K 2015-07-01, 0001193125-15-242462](https://www.sec.gov/Archives/edgar/data/1096752/000119312515242462/d40769d8k.htm): old Energizer renamed Edgewell, spun off New Energizer 1:1, ENR regular-way trading from 2015-07-01.
- [SEC 8-K 2015-06-30, 0001193125-15-241303](https://www.sec.gov/Archives/edgar/data/1632790/000119312515241303/d31222d8k.htm): New Energizer (CIK 1632790) becomes parent of the household products business.
- Fails rows: CUSIP 29266R108 under ENR to 2015-07-01 (Edgewell's line, BBG000BRW644, then EPC from 2015-07-06); CUSIP 29272W109 under ENR from 2015-07-02 (first row $34, a spun-off price level).

## 6. Decision-tree bucket
Kept the same security (the new ENR has had a single line since the spin-off); the old CUSIP's holders keep Edgewell.

## 7. Why the library got it wrong
The base run merged the old ENR line into the new FIGI via the shared ticker. The new run's split (id_changes `split`, BBG006FCB019 -> BBG000BRW644 for issuer 1096752) fixes it. Cause: other:ticker_reuse_spin_off.

## 8. Fix and open checks
None needed for the split. Minor: start day 07-02 vs 07-01 (fails settlement lag); Edgewell's BBG000BRW644 still shows ENR through 2015-07-01, overlapping the new ENR that day. Not a golden case yet.

## 9. Verification
Upheld. Re-read Edgewell 8-K 0001193125-15-242462 through sec.py: Energizer Holdings, Inc. (formerly Energizer SpinCo, CIK 1632790) is "New Energizer", whose common stock "began regular-way trading on the NYSE under the symbol ENR on July 1, 2015"; the old registrant (CIK 1096752) is Edgewell, regular-way EPC (CUSIP 28035Q 102) the same day. The run's tables agree: BBG000BRW644 (Edgewell, CUSIP 29266R108 then 28035Q102) holds the 1096752 ENR range through 2015-07-01; BBG006FCB019 (CUSIP 29272W109) has issuer 1632790 only, from 2015-07-02, and id_changes records the split. The old range 2007-12-17..2015-06-30 under issuer 1096752 on the new FIGI was wrong, so the new value is right on identity and issuer. The one-day-late start (fails first row 07-02 vs filing 07-01) is a data-edge limit, not a refutation.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw; the new Energizer's range starts a day late.

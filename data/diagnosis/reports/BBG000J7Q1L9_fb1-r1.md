# BBG000J7Q1L9_fb1-r1 (HLX -> HOS), regression, security_history.ranges

## 1. Verdict
Helix Energy Solutions (CIK 866829) completed its merger with Hornbeck on 2026-09-01 and survived as the legal acquirer, renamed Hornbeck Offshore Services, Inc., ticker HOS. The same security (same CIK, same CUSIP 42330P107, same FIGI) kept trading, so a ticker change is right: the NEW ranges (HLX then HOS) are correct in kind and the OLD single open HLX range is wrong. The new HOS start date, 2026-09-08, is the first fails row, not the first trading day: it should be 2026-09-02 (HLX ends 2026-09-01).

## 2. Library vs evidence
| field | old (base) | new (library) | evidence | status |
|---|---|---|---|---|
| security_history.ranges | HLX:2007-12-18.. open | HLX:2007-12-18..2026-09-07; HOS:2026-09-08.. | HLX..2026-09-01; HOS:2026-09-02.. (same FIGI) | new right in kind, HOS start 4 sessions late (inferred) |
| exit_kind / continuation | none | none | no ending: Helix is the surviving issuer, shares converted 1:1 into Helix Delaware | agree |
| issuer | 866829 | 866829 | same CIK | agree |

## 3. Corrected classification
```
ticker_history: HLX 2007-12-18..2026-09-01 ; HOS 2026-09-02.. (same sec_id BBG000J7Q1L9, CUSIP 42330P107)
exit_kind: none (no ending); continuation: n/a
value_rule: n/a
event_type: rename (registrant survives a merger and is renamed)
confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: no ending; filing, 8-K 0001193125-26-378529 (Helix converted, same company renamed).
- successor: none; filing, same.
- last trade date: not applicable.
- payout rule / terms: not applicable.
- ticker change date: the 8-K says HOS is "expected to commence trading ... on September 2, 2026" (an expectation, not a print). Fails rows: HLX last row 2026-09-02 (priced at the 09-01 close), HOS first row 2026-09-08 (settlement lag). Would be verified by an exchange notice or a first-day print.

## 5. What happened
- 2026-09-01: Helix converted from Minnesota to Delaware; Hornbeck merged into a subsidiary and then into LLC Sub; Helix Delaware renamed Hornbeck Offshore Services, Inc.; each Helix share became one share of Helix Delaware; HOS expected to trade from 2026-09-02 [SEC 8-K 2026-09-01](https://www.sec.gov/Archives/edgar/data/866829/000119312526378529/d102206d8k.htm).
- Fails rows: CUSIP 42330P107 as HLX 2026-08-11..2026-09-02, as HOS 2026-09-08..09-14: one CUSIP, one security.

## 6. Decision-tree bucket
Kept the same security (rename, same CUSIP).

## 7. Why the library got it wrong
The base run did not see the rename after the last observation; the new run does, but starts HOS at the first fails row (2026-09-08) rather than the first trading day. Cause: other:ticker range start taken from a lagging fails row.

## 8. Fix and open checks
Start HOS on the first trading day (2026-09-02); confirm by an exchange notice. Not golden-worthy until confirmed.

## 9. Verification
Skeptic re-check. Re-opened 8-K 0001193125-26-378529 (CIK 866829) through sec.py: it states "expected to begin trading on the New York Stock Exchange under the new name and ticker symbol 'HOS' on September 2, 2026"; the Effective Time converted each Helix share into one Helix Delaware share (same company, renamed). Fails rows of CUSIP 42330P107: HLX 20260811..20260902 (the 09-02 row is priced at the 09-01 close), HOS 20260908..20260914 (3 rows each; 09-08 is the first row, a settlement lag, not a first trade). One CUSIP, one FIGI: a rename, not an ending. Neither the old open HLX range nor the library's HLX..2026-09-07 / HOS 2026-09-08 split matches HLX..2026-09-01 / HOS 2026-09-02. Verdict "neither" survives; confidence stays inferred (the 09-02 start rests on an expectation plus fails-row timing, not a printed exchange notice).

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the rename HLX -> HOS (Helix became Hornbeck Offshore Services, same CUSIP, same FIGI) is right in kind and the old open HLX range is wrong. The HOS range starts at its first fails row (2026-09-08), not the first session (2026-09-02): the ticker-start rule, which this change did not touch. Neither side is right, as this report found; the loop's ledger explains a regression only as new_right, and DIS and FMCC, the same case, were settled new_right by the loop itself.

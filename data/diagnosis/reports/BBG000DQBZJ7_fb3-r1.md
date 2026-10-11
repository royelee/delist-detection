# BBG000DQBZJ7_fb3-r1 (CVSA, regression)

## 1. Verdict
DeVry Education Group renamed itself Adtalem Global Education on 2017-05-23 (ticker DV to ATGE, CUSIP 251893103 to 00737L103) and Covista in Feb 2026 (ATGE to CVSA). The company never left the exchange, so no ending exists. The new run (no delisting row, one FIGI line DV, ATGE, CVSA) is right; the base run's `exchange_transfer` guess under the placeholder CIK730464-COMMON was wrong.

## 2. Library vs evidence
| Field | old (base) | new | evidence | right |
| --- | --- | --- | --- | --- |
| delistings row | exchange / transfer, last trade 2017-05-23, no successor | none | no Form 25 in 2017-04..07; only a name-change 8-K (5.03); company kept filing; still on NYSE in 2026 | new |
| security_history ranges | DV 2007-12-18..2017-05-23 only | DV ..2017-05-24; ATGE 2017-05-25..2026-02-24; CVSA 2026-02-25.. | fails rows of 00737L103 start 2017-05-24 ("ADTALEM GLOBAL ED INC"); 8-K 2026-02-05 renames to Covista | new (CVSA start date not read from a filing) |
| sec_id | placeholder CIK730464-COMMON | BBG000DQBZJ7 | same issuer CIK 730464, class COMMON, one line across the rename | new |

## 3. Corrected classification
```
exit_kind: (none, no ending)   continuation: n/a   successor: none
event_type: name_change        confidence: verified
value_rule: none (not an exit)
```

## 4. Why this confidence
verified.
- exit kind: no ending; 8-K 0001157523-17-001644 (name change); no Form 25 in the 2017 filing list.
- successor: none; same CIK 730464, same security.
- last trade date: none; the security still trades (8-K 0001104659-26-011611 cover lists ATGE on NYSE and NYSE Texas).
- payout rule / terms: none; not an exit.

## 5. What happened
- [SEC 8-K 2017-05-24](https://www.sec.gov/Archives/edgar/data/730464/000115752317001644/a51564302.htm): name changed from DeVry Education Group Inc. to Adtalem Global Education Inc., effective on filing 2017-05-23.
- Fails rows: CUSIP 00737L103 under ATGE from 2017-05-24 (11 rows to 2017-06-22).
- [SEC 8-K 2026-02-06](https://www.sec.gov/Archives/edgar/data/730464/000110465926011611/atge-20260205x8k.htm): name changed to Covista Inc. on 2026-02-05.
- 8-Ks of 2026-02-24 and 2026-03-03 carry cvsa- file names, consistent with the CVSA ticker.

## 6. Decision-tree bucket
Kept the same security (rename and CUSIP change by the same issuer, no exchange of shares).

## 7. Why the library got it wrong (base run)
The base run did not follow the line past the observations and used the continued-filings transfer guess (`no_form25;delist_date_approx;successor_unknown`). Cause: rename_not_followed. The new run's line follow fixes it.

## 8. Fix and open checks
None; the new output is correct. CVSA's first trading day (2026-02-25) is not confirmed from a filing. Golden-worthy: yes (two renames, one with a CUSIP change).

## 9. Verification
Skeptic result: all three field verdicts upheld (new is right).
- delistings.removed: the 2017-04..08 filing list of CIK 730464 has no Form 25, 25-NSE or Form 15; only 8-K 0001157523-17-001644 (5.03: name change DeVry to Adtalem, effective on filing 2017-05-23). Fails rows of CUSIP 00737L103 under ATGE run 2017-05-24..2017-06-22 (11 rows), so it is a rename with a CUSIP change. 8-K 0000730464-26-000007 (2026-02-24) cover lists CVSA on NYSE and NYSE Texas, so the issuer never left the exchange. Upheld.
- security_history.ranges: DV..2017-05-24, ATGE from 2017-05-25 (the first ATGE fails row is 2017-05-24, one day before the range start; immaterial), the 2026-02-05 name change (8-K 0001104659-26-011611), CVSA on the cover by 2026-02-24. The CVSA start 2026-02-25 is not read from a filing, as the report says. Upheld.
- id_changes.sec_id: same CIK 730464, class COMMON, one line across both renames. Upheld.
- Wording fix: section 4's "cover lists ATGE" is the 2026-02-06 8-K's cover (still ATGE); the CVSA cover is the 2026-02-24 8-K's. The conclusion is unchanged.

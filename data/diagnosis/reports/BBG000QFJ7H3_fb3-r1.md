# BBG000QFJ7H3_fb3-r1 (OAS, Oasis Petroleum) - regression diagnosis

## 1. Verdict
Oasis filed Chapter 11 on 2020-09-30; Nasdaq delisted the old common at the open on 2020-10-12, so its last exchange trade was 2020-10-09, and the old equity was cancelled on 2020-11-19. The NEW run is right on both fields: a bankruptcy drop row is present, and the ticker range ends 2020-10-09 with no OTC tail.

## 2. Library vs evidence
| Field | Old (base) | New | Evidence | Status |
| --- | --- | --- | --- | --- |
| delistings.added | no contract row | dropped / bankruptcy, last trade 2020-10-09, otc_print | Ch.11 8-K 1.03 (0001486159-20-000075); Nasdaq delisting at open 2020-10-12 (8-K 3.01 0001486159-20-000080); 25-NSE 0001354457-20-000638; equity cancelled 2020-11-19 (0001486159-20-000115) | new right |
| security_history.ranges | OAS 2010-06-22..2020-10-12 and OASPQ 2020-10-13..2020-11-23 | OAS 2010-06-22..2020-10-09 | Last Nasdaq day 2020-10-09; OTC trading is not a listing (clip policy); fails: OAS rows end 20201009, OASPQ rows 20201013..20201123 on the same CUSIP 674215108 | new right |

## 3. Corrected classification
```text
exit_kind        = dropped
drop_reason      = bankruptcy
continuation     = false
successor        =
last_trade_date  = 2020-10-09
value_rule       = otc_print
cash_per_share   =
cash_currency    =
stock_ratio      =
price_ticker     = OASPQ (the 8-K expected OASAQ; fails rows show OASPQ)
price_sec_id     = BBG000QFJ7H3
price_date       = 2020-10-12
recovery_ratio   =
value_formula    = otc_print(OASPQ, 2020-10-12) / last_close - 1
event_type       = bankruptcy
consideration    = none (old equity cancelled; holders got warrants under the plan)
holder_value     = pro rata share of warrants for New Common Stock
effective_date   = 2020-11-19
successor_ticker =
confidence       = inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 1.03 0001486159-20-000075; 8-K 3.01 0001486159-20-000080; 8-K 0001486159-20-000115).
- successor: filing (none; new Oasis is a new security under the plan, CUSIP 674215207).
- last trade date: filing (8-K 3.01: delisted at the opening of business 2020-10-12, so 2020-10-09); fails rows agree.
- payout rule: filing (decision 11, bankruptcy drop valued at the first OTC print).
- terms: fails rows (OTC symbol OASPQ from fails; the 8-K said OASAQ). Not backed by a filing; a source naming the OTC symbol would verify.

## 5. What happened
- 2020-09-30 Chapter 11 filed [SEC 8-K 1.03](https://www.sec.gov/Archives/edgar/data/1486159/000148615920000075/oas-20200929.htm).
- 2020-10-02 8-K 3.01: Nasdaq will delist at the opening of business on 2020-10-12; OTC Pink from 2020-10-12 [SEC 8-K](https://www.sec.gov/Archives/edgar/data/1486159/000148615920000080/oas-20201002.htm).
- 2020-10-27 Form 25-NSE filed (0001354457-20-000638).
- 2020-11-19 plan effective; existing equity cancelled, holders receive warrants [SEC 8-K](https://www.sec.gov/Archives/edgar/data/1486159/000148615920000115/oas-20201119.htm).
- Fails: CUSIP 674215108 as OAS to 20201009, as OASPQ 20201013..20201123; new CUSIP 674215207 as OAS from 20201120.

## 6. Decision-tree bucket
Lost: bankruptcy, then OTC. Post-bankruptcy equity is a new security.

## 7. Why the library got it wrong
The base run published no ending and carried the OTC tail (OASPQ) in the ticker history; the new run corrects both. Cause: library_right_but_uncertain (the new output is right; only the OTC symbol is uncertain).

## 8. Fix and open checks
None for the library. Open: the OTC symbol (8-K says OASAQ, fails say OASPQ). Golden-worthy: yes.

## 9. Verification
Upheld, both fields. Re-read the cached 8-K 3.01 (0001486159-20-000080): Nasdaq delists the common at the opening of business 2020-10-12, so the last Nasdaq trade is 2020-10-09; OTC Pink under "OASAQ" expected from 2020-10-12. The 8-K 1.03 (0001486159-20-000075) confirms the 2020-09-30 Chapter 11. Fails for CUSIP 674215108: OAS rows 20201001..20201009, OASPQ rows 20201013..20201123, so the OTC tail is not a listing and the new range ending 2020-10-09 is right. output/contract has the dropped/bankruptcy row (last trade 2020-10-09, otc_print) and security_history OAS 2010-06-22..2020-10-09. Only the OTC symbol (OASAQ vs OASPQ) is unverified, and neither field verdict depends on it.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (Oasis's 2020 bankruptcy drop).

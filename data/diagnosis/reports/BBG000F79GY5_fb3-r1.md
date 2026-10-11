# BBG000F79GY5_fb3-r1 (HPT -> SVC, Service Properties Trust, CIK 945394), regression

## 1. Verdict
Hospitality Properties Trust renamed itself Service Properties Trust on 2019-09-23 (new CUSIP 81761L102) and began trading on Nasdaq as SVC at the open on 2019-09-25. It is the same issuer and the same shares, so there is no ending. The new run is right to drop the 2019-09-26 exchange-continuation row and to name the security by its FIGI. Neither run has the ticker ranges exactly right.

## 2. Library vs evidence
| Field | Old (base) | New | Evidence | Right |
| --- | --- | --- | --- | --- |
| delistings.removed (exit_kind=exchange, continuation=true, successor=itself, last_trade blank, value_rule=continuation) | row present, from a guessed 2019-09-26 "ticker change" ending (no Form 25, `last_trade_date_unconfirmed`, `delist_date_approx`) | no contract row; output/delistings.csv holds only the 2016-07-10 row, whose successor is the security itself, so it is no real ending | A rename on the same issuer is not an ending (decision table). The only Form 25 (2016-06-30) was the NYSE-to-Nasdaq move of the same shares, still HPT. | new |
| security_history.ranges | HPT:2007-12-20..2019-09-26; SVC:2019-09-25.. (overlap) | HPT:2007-12-20..2019-09-29; SVC:2019-09-30.. | 8-K 5.03: SVC trades from the open on 2019-09-25, so HPT ends 2019-09-24 and SVC starts 2019-09-25. Fails rows of the old CUSIP 44106M102 run to 2019-09-26 (settlement lag); those of the new CUSIP 81761L102 begin 2019-09-25. | neither (old has the right SVC start, new has no overlap; both HPT ends are late) |
| id_changes.sec_id | CIK945394-COMMON (placeholder) | BBG000F79GY5 | The issuer's one common-share line, now resolved to a FIGI; the rename row maps the placeholder to it. | new |

Other fields (issuer 945394) agree between the runs.

## 3. Corrected classification
```
sec_id: BBG000F79GY5   (no ending)
exit_kind: (none)   continuation: n/a   successor: n/a   last_trade_date: n/a
value_rule: n/a
ticker ranges: HPT 2007-12-20..2019-09-24 ; SVC 2019-09-25..
event_type: name_change / ticker_change (earlier, 2016-07-01: NYSE -> Nasdaq, still HPT)
consideration: none   confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 5.03 filed 2019-09-23 (0001410578-19-001384): a name change, same registrant, no exchange of shares.
- successor: filing, same 8-K; none needed.
- last trade date: none published; no ending.
- payout rule: filing, same 8-K; nothing paid or exchanged.
- terms: none.
The ticker-range dates rest on the same 8-K (SVC from the open on 2019-09-25).

## 5. What happened
- 2016-06-20: HPT told the NYSE it would move its common shares to Nasdaq from 2016-07-01, still symbol HPT ([SEC 8-K 0001104659-16-128205](https://www.sec.gov/Archives/edgar/data/945394/000110465916128205/a16-13505_18k.htm)); Form 25 filed 2016-06-30 ([0001104659-16-130403](https://www.sec.gov/Archives/edgar/data/945394/000110465916130403/a16-14254_125.htm)) with an 8-A12B for Nasdaq the same day ([0001104659-16-130383](https://www.sec.gov/Archives/edgar/data/945394/000110465916130383/a16-14254_48a12b.htm)).
- 2019-09-23: name changed to Service Properties Trust, new CUSIP 81761L 102, trading as SVC on Nasdaq from the open on 2019-09-25 ([SEC 8-K 0001410578-19-001384](https://www.sec.gov/Archives/edgar/data/945394/000141057819001384/tv529877_8k.htm)).
- Fails rows: CUSIP 44106M102 (HPT) last row 2019-09-26; CUSIP 81761L102 (SVC) first row 2019-09-25.
- The same registrant filed its Q3 2019 10-Q on 2019-11-08 as SVC ([0000945394-19-000035](https://www.sec.gov/Archives/edgar/data/945394/000094539419000035/svcq320198k.htm)).

## 6. Decision-tree bucket
Kept the same security: a rename and ticker change with a new CUSIP; same holders, no exchange.

## 7. Why the library got it wrong
Base run: the rename (new CUSIP, new ticker) was read as a 2019-09-26 ending with no Form 25 (`no_form25;last_trade_date_unconfirmed`), cause `rename_not_followed`. The new run no longer treats it as a real ending, which is correct. Residual: the ranges are cut at fails-row edges (HPT to 2019-09-29, SVC from 2019-09-30) instead of the dates the 8-K gives. Cause for the remaining ranges: other:ticker_range_edge_from_fails_rows.

## 8. Fix and open checks
- Ranges should switch on 2019-09-25 (SVC), with HPT ending 2019-09-24.
- Not golden-worthy for the removal (the new run is already right); the ranges could be a case once fixed.

## 9. Verification
Upheld, all three field verdicts. Re-read 8-K 0001410578-19-001384 (cached text): Item 5.03 says the name changed effective 12:01 a.m. 2019-09-23, new CUSIP 81761L 102, and the common shares begin trading on Nasdaq as SVC at the open on 2019-09-25. Same registrant (CIK 945394), same shares, no exchange of shares, so no ending: delistings.removed "new" holds. The id_changes rename to BBG000F79GY5 holds (one common line of one issuer). security_history.ranges "neither" holds: output/contract/security_history.csv has HPT ..2019-09-29 and SVC 2019-09-30.., while the filing gives HPT ..2019-09-24 and SVC 2019-09-25..; the base had SVC 2019-09-25 but HPT to 2019-09-26 (overlap). Caveat: the 8-K says the switch "will begin" on 2019-09-25, so the date is the filing's expectation; the new CUSIP's first fails row on 2019-09-25 corroborates it.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw; neither run has the HPT to SVC switch day (2019-09-25) exactly.

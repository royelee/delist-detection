# BBG000BVD6X4_fb3b-r1 (GL), regression

## 1. Verdict
Torchmark renamed itself Globe Life Inc. on 2019-08-08 and its NYSE ticker became GL on 2019-08-09. The new run's range (GL from 2019-08-09, TMK to 2019-08-08) is right; the old run's GL start of 2019-08-13 was late. No delisting: the same security and issuer (CIK 320335) continue.

## 2. Library vs evidence
| field | library says (old / new) | evidence says | status |
|---|---|---|---|
| security_history.ranges | old GL:2019-08-13.., TMK ..2019-08-12; new GL:2019-08-09.., TMK ..2019-08-08 | ticker GL from 2019-08-09 (web); fails rows of CUSIP 37959E102 under GL start 2019-08-09, TMK rows end 2019-08-12 only because fails settle late | new right |
| exit_kind / successor / last_trade_date / value_rule / terms | none (still listed) | none, rename only | agree |
| issuer | CIK 320335 | CIK 320335 (8-K 5.03) | agree |

## 3. Corrected classification
```
exit_kind: (none)  ticker_history: TMK 2008-01-10..2019-08-08; GL 2019-08-09..
event_type: rename  confidence: inferred
```

## 4. Why this confidence
inferred. Exit kind, successor, last trade date, payout rule, terms: not applicable (no ending). The ticker change date rests on web (company press release page) and fails rows, not a filing stating the day; the 8-K only states the name change effective 2019-08-08 and shows GL on its cover. A filing or NYSE notice stating the first GL trading day would make it verified.

## 5. What happened
- Name change to Globe Life Inc. effective 2019-08-08: [SEC 8-K 2019-08-08](https://www.sec.gov/Archives/edgar/data/320335/000032033519000033/a8-kamendedcertificate.htm), accession 0000320335-19-000033.
- NYSE ticker changed to GL on 2019-08-09: [web](https://home.globelifeinsurance.com/press-releases/2019/august-2019/torchmark-corporation-has-officially-been-renamed).
- Fails rows: CUSIP 37959E102 under GL first row 2019-08-09; TMK (891027104) rows 2019-07-01..2019-08-12 (old CUSIP differs; fails settle days later).

## 6. Decision-tree bucket
Kept the same security.

## 7. Why the library got it wrong
The old run started GL at the day after TMK's last fails row; the new run's change (ticker sighting rules for an old CUSIP's settling tail, f56ff50) dates it at the first GL row. Cause: other:old_run_range_start_from_settling_tail.

## 8. Fix and open checks
None needed. Optionally confirm the first GL trading day from an NYSE notice. Not golden-worthy.

## 9. Verification
Upheld: security_history.ranges (right: new). Re-checked through sec.py: the 8-K (0000320335-19-000033) states the Torchmark to Globe Life Inc. name change effective 2019-08-08 and shows GL on NYSE on its cover, same CIK 320335, so no delisting. Fails: CUSIP 37959E102 under GL has 11 rows from 20190809 to 20190830; TMK (891027104) has 8 rows 20190701..20190812, the old CUSIP's settling tail. A new-CUSIP row on 2019-08-09 cannot exist before the symbol was live, so GL from 2019-08-09 and TMK to 2019-08-08 fit; the old run's 2019-08-13 start came from the TMK tail. Not re-checked: the press release page (web reader quota error); the first GL trading day rests on fails rows and that page, as the report already says (inferred).

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right, from the filing it cites, and its ranges are exactly the new run's (checked against the case's sides); the confidence is inferred only because the switch day also rests on the fails rows (GL from 2019-08-09).

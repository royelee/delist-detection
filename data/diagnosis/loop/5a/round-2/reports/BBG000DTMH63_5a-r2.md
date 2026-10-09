# BBG000DTMH63_5a-r2 (NE, Noble Corp) - regression, field security_history.ranges

## 1. Verdict
The new ranges (one continuous NE range 2009-03-30..2020-07-30) are right. The old run's NEZZZZ ranges came from
fails-to-deliver rows under a deleted-symbol placeholder on the days the CUSIP changed; the ticker was NE throughout.

## 2. Library vs evidence
| field | old (side_a) | new (side_b) / evidence | status |
| --- | --- | --- | --- |
| security_history.ranges | NE 2009-03-30..2013-11-19; NE 2013-11-21..2020-07-30; NEZZZZ 2009-03-27..29; NEZZZZ 2013-11-20 | NE 2009-03-30..2020-07-30. Fails rows: NEZZZZ appears once per CUSIP (H5833N103 on 2009-03-27 at $0.01; G65431101 on 2013-11-20 at $1.00), both placeholder prices on the first day of a new CUSIP; NE rows run 2013-11-01..18 (old CUSIP) and 2013-11-21..29 (new CUSIP) at $37-39 | new right |
| exit_kind, last_trade_date, value_rule, terms, issuer | unchanged between runs; not in dispute (issuer CIK 1458891 in both) | not examined | unknown |

## 3. Corrected classification
```
ticker ranges: NE 2009-03-30..2020-07-30 (issuer 1458891), no NEZZZZ range
(ending fields not part of this case; library row: liquidation/470 bankruptcy, last trade 2020-07-30, unchanged)
confidence: verified for the ranges question
```

## 4. Why this confidence
inferred-free for this field: verified.
- exit kind: not in dispute.
- successor: not in dispute.
- last trade date: not in dispute.
- payout rule / terms: not in dispute.
- ranges: `fails rows` (SEC FTD data via sec.py: NEZZZZ rows are one-day placeholders at the CUSIP change dates, NE rows continue on both sides) plus the observed ticker NE.

## 5. What happened
- Noble Corp redomiciled twice: Swiss (CUSIP H5833N103) to Cayman/UK plc (G65431101); the plc line began 2013-11-20 per fails rows. The ticker NE stayed on NYSE.
- FTD rows under symbol NEZZZZ (a deleted/test symbol, priced $0.01 and $1.00) exist only on 2009-03-27 and 2013-11-20.

## 6. Decision-tree bucket
Kept the same security under the same ticker: not a ticker change, no new ticker range.

## 7. Why the library got it wrong (old run)
The old run counted the one-day NEZZZZ fails rows as ticker sightings (symbol has letters); the new run filters them (successor/deleted-symbol handling). Cause: other:ftd_placeholder_symbol_ranges (fixed in new run).

## 8. Fix and open checks
None for this field. Candidate golden case: NE ranges stay one NE range.

## 9. Verification
Upheld. Re-ran `sec.py fails` offline. NEZZZZ has exactly one row under each Noble CUSIP: H5833N103 on 2009-03-27 at $0.01 and G65431101 on 2013-11-20 at $1.00, the signature of a placeholder symbol on a CUSIP's first day. NE rows run on both sides: H5833N103 from 2009-03-30 (54 rows, $24.81 onward) and G65431101 from 2013-11-21 (5 rows, $39.43 to $38.25). One issuer (CIK 1458891) and one ticker throughout, so the single range NE 2009-03-30..2020-07-30 matches `output/ticker_history.csv`. Nothing found that refutes it.

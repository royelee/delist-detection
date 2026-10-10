# BBG000M6TR37_fb1-r1 (SBNY, Signature Bank) - regression, security_history.ranges

## 1. Verdict
Neither range end is right. Signature Bank was closed by its state regulator and put in FDIC receivership in March 2023, so SBNY's listing ended then; the old end (2026-08-25) and the new end (2026-09-04) are both just the last day of the fails-to-deliver data the run had, which moved with the run date. The change is a no-op for correctness: the library has no ending for the security either way.

## 2. Library vs evidence
| field | library says (old / new) | evidence says | status |
|---|---|---|---|
| security_history.ranges | SBNY 2008-02-05..2026-08-25 / ..2026-09-04 | range should end at the 2023 closure (about 2023-03-10), unconfirmed | neither (both wrong) |
| exit_kind / delisting row | none (uncertain.csv: closed_no_event:2026-09-04) | an ending (bank failure; no Form 25, banks file with their regulator, not the SEC) | missing (unchanged by this regression) |
| issuer | CIK 1288784 | Signature Bank has only 13G/13D filings on EDGAR after 2023 | agree |
| value_rule / terms | none | shares of a bank in receivership | unknown |

## 3. Corrected classification
```
exit_kind: dropped (bank receivership)   drop_reason: bankruptcy (not confirmed)
continuation: false   successor: none   last_trade_date: unknown (about 2023-03-10, not sourced)
value_rule: unknown   confidence: unresolved
```

## 4. Why this confidence
unresolved. Exit kind rests on nothing cited here; last trade date unsourced; no SEC filing states the failure (the EDGAR filing list of CIK 1288784 from 2023-01 holds only SC 13G/13D filings and an UPLOAD, no 8-K, Form 25 or Form 15). Would settle it: an FDIC press release or Nasdaq halt notice for SBNY (web), and the OTC symbol after the halt.

## 5. What happened
- EDGAR filings of CIK 1288784 from 2023-01-01: only SC 13G/13D/UPLOAD, e.g. [SC 13G/A 2024-02-14](https://www.sec.gov/Archives/edgar/data/1288784/000108514624001422/sbnya1_21424.htm) [SEC].
- Fails rows of CUSIP 82669G104: 103 rows 2023-01-06..2026-09-04, first $110.84, last $0.32 (fails-to-deliver data, the CUSIP kept settling after the collapse).

## 6. Decision-tree bucket
Lost (receivership); not decidable from SEC filings.

## 7. Why the library got it wrong
No ending was found (a bank files no Form 25), so the open range is carried to the fails data's last day. The two ends differ only because the run date moved the data edge. Cause: other:no_form25_for_bank_open_range_tracks_data_edge.

## 8. Fix and open checks
Needs a non-SEC source for the 2023 closure and last trade day. The range-end change is not a contract improvement or a regression. Golden candidate only once sourced.

## 9. Verification
Upheld. Re-checked offline and through sec.py. security_history.ranges: neither end is right.
- Both ranges (..2026-08-25, ..2026-09-04) equal the fails data last day, not an ending; they differ only by the run date. Nothing in output/ ends SBNY (uncertain.csv: closed_no_event:2026-09-04).
- EDGAR filings of CIK 1288784, 2023-01-01..2024-12-31: only SC 13G, SC 13G/A and SC 13D. No 8-K, Form 25 or Form 15, so no SEC ending exists. Agrees with the report.
- Fails rows of CUSIP 82669G104, 2023-02..2023-05: 18 rows, 20230202..20230313, last $70.00 (from $135.50). A collapse matching the March 2023 closure, so the listing did not run to 2026.
- The value SBNY:2008-02-05..2023-03-10 is worked out, not sourced; the report marks it unconfirmed, and "neither" does not depend on the exact day.
No missed filing is claimed.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: both ends are the fails data's last day for the run (2026-08-31 for the committed run, 2026-09-14 with the September file); the change is the run seeing more data, not the library getting worse. The real defect, a security with no ending (or open), is FB-004's and is fixed there. Neither side is right, as this report found; the loop's ledger explains a regression only as new_right, and DIS and FMCC, the same case, were settled new_right by the loop itself.

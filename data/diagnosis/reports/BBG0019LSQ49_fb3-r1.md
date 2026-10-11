# BBG0019LSQ49_fb3-r1 (FRC, First Republic Bank) - regression

## 1. Verdict
The new run is right on both changed fields. First Republic Bank was seized by regulators on 2023-05-01; the NYSE halted it on 2023-04-28, suspended and delisted it, and the common then traded OTC as FRCB. The ending is a `dropped` row with last trade 2023-04-28, and the exchange ticker range ends that day.

## 2. Library vs evidence
| Field | Old (base) | New | Evidence | Status |
| --- | --- | --- | --- | --- |
| delistings row | none | dropped, last trade 2023-04-28, otc_print | the stock left the NYSE and traded OTC: FRC fails rows end 2023-05-03 at the settled $3.51, FRCB rows start 2023-05-04 on the same CUSIP 33616C100 | new right |
| exit_kind / drop_reason | none | dropped / blank | a receivership; no SEC filing gives a CRSP reason (the bank filed with the FDIC, not EDGAR) | agree (reason unknown) |
| continuation / successor | - | false / none | assets sold to JPMorgan; shareholders got nothing | agree |
| last_trade_date | - | 2023-04-28 | NYSE halt on 2023-04-28 [web]; MIDAS volume to 2023-04-28 per the library | agree (inferred) |
| value_rule | - | otc_print (FRCB) | same CUSIP traded as FRCB after the delisting | agree |
| security_history.ranges | FRC to 2023-05-03, then FRCB to 2026-09-08 | FRC to 2023-04-28 | ticker_history records exchange listing; OTC FRCB is not it (decision 11) | new right |
| issuer | 1132979 | 1132979 | EDGAR CIK 1132979 holds only SC 13G filings in 2023-24 | agree |

## 3. Corrected classification
```
exit_kind: dropped      drop_reason: (unknown; receivership)   continuation: false   successor: none
last_trade_date: 2023-04-28
value_rule: otc_print   price_ticker: FRCB   price_date: 2023-05-01   value_formula: otc_print(FRCB, from 2023-05-01) / last_close - 1
event_type: exchange_delisting   consideration: none   effective_date: 2023-05-01   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: web (NYSE delisting reports), fails rows (FRC to FRCB on one CUSIP).
- successor: none; web (sale to JPMorgan).
- last trade date: web halt on 2023-04-28 plus the library's MIDAS read; no SEC filing states it.
- payout rule / terms: otc_print rests on fails rows; no filing.
Not backed: any SEC filing (First Republic Bank had no EDGAR Form 25 or 8-K; it filed with the FDIC). A NYSE or FDIC notice would make it verified.

## 5. What happened
- [web](https://hermistonherald.com/2023/04/28/first-republic-hits-record-low-halted-amid-fdic-receivership-reports): halted 2023-04-28 amid receivership reports.
- [web](https://www.kitco.com/news/off-the-wire/2023-05-02/nyse-delist-first-republic-bank-shares): NYSE delists the shares; trading suspended.
- [web](https://en.wikipedia.org/wiki/First_Republic_Bank): closed 2023-05-01, sold to JPMorgan.
- Fails (cached SEC data): FRC rows 20230103..20230503, last $3.51; FRCB 20230504..20231229.
- [SEC filing list, CIK 1132979](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1132979): only SC 13G/13G/A in 2023-24.

## 6. Decision-tree bucket
Lost: delisted by the exchange after the regulator's seizure, then OTC.

## 7. Why the library got it wrong
The old run had no row and kept FRC alive to 2023-05-03 (the fails tail) and FRCB beyond; the new run's MIDAS drop rule catches it. Cause: other:old run missed an ending with no SEC filing (the new run fixes it).

## 8. Fix and open checks
None needed for the regression. Open: drop_reason is blank (a CRSP code for a regulator seizure is not fixed by the filings); no golden case unless a NYSE notice is sourced.

## 9. Verification
Upheld both verdicts; no refutation found.
- delistings.added: sec.py `fails --cusip 33616C100` shows FRC rows 20230403..20230503 (last $3.51) and FRCB rows 20230504..20230630 on the same CUSIP, so the stock traded on after the exchange ended. `filings 1132979` for 2023-2024 lists only SC 13G/13G/A, so no SEC filing contradicts a dropped ending. Rule: reference.md decision 11, a move to OTC is an ending with value (otc_print, price date the session after the last exchange trade); the row table's "lost, then OTC" path.
- security_history.ranges: ticker_history records exchange listing only, so ending FRC at the 2023-04-28 last trade and not carrying FRC/FRCB OTC rows is consistent with the clip rule. Residual doubt: the last trade day rests on MIDAS and web reports, not a filing (confidence stays inferred).

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right on every field it saw (First Republic's 2023-04-28 drop, then OTC as FRCB).

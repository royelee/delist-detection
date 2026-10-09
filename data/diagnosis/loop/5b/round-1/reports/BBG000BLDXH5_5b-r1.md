# BBG000BLDXH5_5b-r1 (MDRXD) - regression diagnosis

## 1. Verdict
Veradigm (formerly Allscripts, CIK 1124804) was delisted by Nasdaq for failing to file its 10-K/10-Qs; trading was suspended on Nasdaq on 2024-02-29 (last Nasdaq trade 2024-02-28), Form 25-NSE filed 2024-04-25, and the same CUSIP then traded on the OTC Expert Market. The new row (dropped / guidelines, last trade 2024-02-28, otc_print, ticker range clipped at 2024-02-28) is right; the base run's missing ending and unclipped range to 2026-04-29 were wrong.

## 2. Library vs evidence
| Field | old (base) | new (library now) | evidence | right |
| --- | --- | --- | --- | --- |
| delistings.added (exit_kind) | no row | dropped | Nasdaq Hearings Panel delisted for Rules 5250(c)(1)/5620(a); Form 25-NSE 2024-04-25 | new |
| drop_reason | - | guidelines | listing deficiency (late filings) | new |
| continuation / successor | - | false / none | same company, no successor | new |
| last_trade_date | - | 2024-02-28 | 8-K 2024-04-25: suspended on Nasdaq Feb 29, 2024, "have not traded on Nasdaq since"; suspension effective Feb 29 means last trade the day before; MIDAS agrees. Before Form 25 effective date (2024-05-05) | new |
| value_rule | - | otc_print (MDRX, 2024-02-29) | 8-K cover: MDRX "N/A (OTC Expert Market)"; fails rows same CUSIP 01988P108 under MDRX to 2024-11 | new |
| terms | - | no cash/ratio; price_ticker MDRX, price_date 2024-02-29 | no consideration; an OTC print | agree |
| security_history.ranges | MDRX 2008-10-21..2026-04-29 | MDRX 2008-10-21..2024-02-28 | listing ended 2024-02-28; compliance-failure endings always clip | new |
| issuer | CIK 1124804 | same | agree | agree |

## 3. Corrected classification
```
exit_kind: dropped
drop_reason: guidelines
continuation: false
successor: (none)
last_trade_date: 2024-02-28
value_rule: otc_print
cash_per_share: ; cash_currency: ; stock_ratio: ; recovery_ratio:
price_ticker: MDRX (OTC Expert Market); price_sec_id: BBG000BLDXH5; price_date: 2024-02-29
value_formula: otc_print(MDRX, from 2024-02-29) / last_close - 1
event_type: exchange_delisting
consideration: none
holder_value: shares kept, moved to OTC Expert Market
effective_date: 2024-05-05 (Form 25 effective; internal delist_date)
successor_ticker:
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-24-049131 (Nasdaq Panel decision to delist) and 8-K 0001193125-24-113859 (Form 25 filed, suspended).
- successor: filing, none in any filing; same CUSIP traded on after (fails rows).
- last trade date: filing, 8-K 0001193125-24-113859 "suspended from trading on Nasdaq on February 29, 2024 and have not traded on Nasdaq since"; trading day before = 2024-02-28.
- payout rule: filing, 8-K 2024-04-25 cover shows OTC Expert Market; decision 11.
- terms: filing, no consideration exists; only an OTC print rule.

## 5. What happened
- [SEC 8-K 2024-02-27](https://www.sec.gov/Archives/edgar/data/1124804/000119312524047061/d793739d8k.htm): anticipated delisting for late 10-K/10-Qs, suspension expected.
- [SEC 8-K 2024-02-28](https://www.sec.gov/Archives/edgar/data/1124804/000119312524049131/d773269d8k.htm): Panel decision; trading suspended effective Feb 29, 2024.
- [SEC 25-NSE 2024-04-25](https://www.sec.gov/Archives/edgar/data/1124804/000135445724000297/xslF25X02/primary_doc.xml) (0001354457-24-000297).
- [SEC 8-K 2024-04-25](https://www.sec.gov/Archives/edgar/data/1124804/000119312524113859/d752248d8k.htm): suspended Feb 29, not traded on Nasdaq since; cover lists OTC Expert Market.
- Fails rows of CUSIP 01988P108 continue 2024-02-05..2024-11-22 (offline fails command).

## 6. Decision-tree bucket
Lost: delisted for a deficiency, then OTC. Same CUSIP, no successor.

## 7. Why the library got it wrong
The base run did not reach this Form 25 (or let later fails evidence unclip the range); the 5b reach rules now find it. Base cause: `late_form25`; the current row has no error.

## 8. Fix and open checks
None needed. The row stays uncertain only through flags (member_name_mismatch, last_trade_date_conflict); the filing's date matches MIDAS. Golden-worthy: yes (Form 25 filed 56 days after suspension, Nasdaq deficiency, OTC afterwards).

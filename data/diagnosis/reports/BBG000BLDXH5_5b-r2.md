# BBG000BLDXH5_5b-r2 (MDRX, Veradigm / Allscripts) - regression

## 1. Verdict
Nasdaq's Hearings Panel delisted Veradigm common stock for filing-delinquency (suspended effective 2024-02-29, Form 25-NSE 2024-04-25); the shares then quoted OTC under the same symbol. The new row (dropped / guidelines, last trade 2024-02-28, otc_print) and the new range end 2024-02-28 are right; the old run (no ending, range open to 2026-04-29) was wrong.

## 2. Library vs evidence
| field | old (base) | new (library now) | evidence | right |
| --- | --- | --- | --- | --- |
| delistings row | none | dropped / guidelines, not continuation | Nasdaq Panel delisting, Rule 5250(c)(1), 5620(a); Form 25-NSE | new |
| exit_kind | (none) | dropped | stock lost exchange listing, traded OTC | new |
| drop_reason | - | guidelines | listing-rule deficiency (CRSP 570) | new |
| continuation / successor | - | false / none | same security, no successor | agree |
| last_trade_date | - | 2024-02-28 | suspended effective 2024-02-29 -> last session 2024-02-28; Form 25 effective ~2024-05-05 so not after it | new |
| value_rule | - | otc_print | first OTC print; fails rows show MDRX (CUSIP 01988P108) still quoted Feb-Nov 2024 | new |
| terms | - | no cash/ratio; price_ticker MDRX, price_date 2024-02-29 | per decision 11 | agree |
| ticker_history MDRX range | ..2026-04-29 | ..2024-02-28 | listing ended 2024-02-28; OTC is not the exchange listing | new |
| issuer | CIK 1124804 | same | 8-K header | agree |

## 3. Corrected classification
```
exit_kind: dropped
drop_reason: guidelines
continuation: false
successor: none
last_trade_date: 2024-02-28
value_rule: otc_print
cash_per_share: null
cash_currency: ""
stock_ratio: null
price_ticker: MDRX (OTC)
price_sec_id: BBG000BLDXH5
price_date: 2024-02-29
recovery_ratio: null
value_formula: first OTC print of MDRX within 10 trading days of 2024-02-28 / last_close - 1
event_type: exchange_delisting
consideration: none
holder_value: same shares, quoted OTC
effective_date: 2024-02-29 (suspension); Form 25 filed 2024-04-25
successor_ticker: ""
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing - 8-K 0001193125-24-049131 (Nasdaq Panel decision to delist), Form 25-NSE 0001354457-24-000297.
- successor: filing - none named; same CUSIP continues OTC.
- last trade date: filing - 8-K says suspension effective 2024-02-29, so the trading day before.
- payout rule: filing - 8-K says shares expected to be quoted OTC under MDRX (decision 11).
- terms: filing - no consideration; OTC price is qlib_practice's.

## 5. What happened
- 2024-02-27: Nasdaq Hearings Panel decided to delist; trading suspended effective 2024-02-29; company will not appeal; shares expected OTC under MDRX. [SEC 8-K 2024-02-27](https://www.sec.gov/Archives/edgar/data/1124804/000119312524049131/d773269d8k.htm)
- 2024-02-28: further 3.01 8-K (0001193125-24-049131 is the Feb 27 item; 0001193125-24-049131 sibling filing 8-K items 3.01 on 2024-02-28 is the filing above).
- 2024-04-25: Nasdaq filed Form 25-NSE for common stock. [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/1124804/000135445724000297/xslF25X02/primary_doc.xml)
- Fails rows for CUSIP 01988P108 under MDRX continue 2024-02-05..2024-11-22 (same CUSIP, OTC). [fails data]
- Company kept filing (8-Ks through 2024-09), consistent with OTC quotation.

## 6. Decision-tree bucket
Lost: delisted for a deficiency, then OTC. Holders keep the same shares but the listing ended; decision 11 values it at the first OTC print.

## 7. Why the library got it wrong
Base run: no delisting row found, so the range stayed open to 2026-04-29. The new run found the Form 25-NSE (sub-plan 5b reach rules) and clipped. Cause: late_form25 (fixed by the change).

## 8. Fix and open checks
None needed for the new row. Library's bucket label is compliance_failure/570 (maps to dropped/guidelines): correct. Uncertain flags (member_name_mismatch, distress_at_normal_price) are about the name MDRX/Veradigm and a Shumway-style mark, not the ending. Golden-worthy: yes (late Form 25, OTC under same ticker). Note the 2024-02-28 8-K quoted as the Feb-28 filing is item 3.01/9.01 (0001193125-24-049131), the press-release 8-K.

## 9. Verification
Upheld, both field verdicts (delistings.added, security_history.ranges; right = new).
- Re-read 8-K 0001193125-24-049131 (filed 2024-02-28, item 3.01): the Nasdaq Hearings Panel decided to delist the common stock (Rules 5250(c)(1), 5620(a)); trading suspended effective 2024-02-29; no review requested; shares expected on an OTC market as MDRX. So dropped / guidelines, not a continuation, and the last exchange session is 2024-02-28.
- Form 25-NSE 0001354457-24-000297 filed 2024-04-25 (effective about 2024-05-05); the last trade date is before it, as required.
- The new range end 2024-02-28 follows. The report's "2024-02-27" date for this accession is a slip (filed 02-28; the 02-27 filing is 0001193125-24-047061); no field changes.

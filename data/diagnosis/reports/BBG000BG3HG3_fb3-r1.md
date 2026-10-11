# BBG000BG3HG3_fb3-r1 (GGP Inc., regression)

## 1. Verdict
GGP Inc. (NYSE: GGP, CUSIP 36174X101) was acquired by Brookfield Property Partners on 2018-08-28: its common was suspended from the NYSE before the open that day, so the last trade was 2018-08-27. The new run's merger row and its 2018-08-27 range end are right (old run: no ending, range cut at 2018-08-24 = last fails row). The new row's terms are wrong: it publishes cash 0.312 only, which is the small cash leg that follows the pre-closing dividend, not the package.

## 2. Library vs evidence
Fields of the case: `delistings.added` (old: no row; new: merger, last trade 2018-08-27, value_rule cash) and `security_history.ranges` (old GGP:2010-11-15..2018-08-24; new ..2018-08-27).

| field | library says (new) | evidence says | status |
|---|---|---|---|
| exit_kind (delistings.added) | merger | merger; shares became cash plus BPY units / BPR Class A, 8-K 2018-08-28 items 2.01, 3.01, 5.01 | agree (new right; old had no ending, wrong) |
| drop_reason | blank | blank | agree |
| continuation | false | false; old common cancelled for cash, the new BPR Class A (CUSIP 11282X103) is a different security | agree |
| successor | none | none | agree |
| last_trade_date | 2018-08-27 | 8-K 3.01: suspended "effective as of the opening of trading on August 28, 2018" so last trade 2018-08-27 | agree (new right) |
| security_history.ranges | GGP 2010-11-15..2018-08-27 | trades through 2018-08-27; old end 2018-08-24 only reflects the last fails row | agree (new right) |
| value_rule | cash | cash_plus_stock (non-electing/default package) | wrong |
| terms | cash 0.312 USD, gate failed | cash 14.642 USD + 0.376 BPY unit per share (default package, dividend plus merger cash), price BPY on 2018-08-28 | wrong |
| issuer | CIK 1496048 | CIK 1496048 (survives as Brookfield Property REIT Inc.) | agree |
| ticker_history | GGP | GGP until 2018-08-27 | agree |

## 3. Corrected classification
```
exit_kind: merger        drop_reason:        continuation: false   successor:
last_trade_date: 2018-08-27
value_rule: cash_plus_stock   cash_per_share: 14.642   cash_currency: USD
stock_ratio: 0.376   price_ticker: BPY   price_sec_id:   price_date: 2018-08-28   recovery_ratio:
value_formula: (14.642 + 0.376 x price(BPY, 2018-08-28)) / last_close - 1
event_type: acquisition   consideration: cash_or_stock_election
holder_value: non-electing default 14.642 USD cash + 0.376 BPY units (cash-elector 14.642 + 0.376 BPY/BPR A; stock-elector 0.986 BPY/BPR A + 0.312 cash)
effective_date: 2018-08-28   successor_ticker:   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 0001193125-18-260735 items 2.01, 5.01; 25-NSE 0000876661-18-000943).
- successor: filing (none; Class A stock is a new class, 8-K 3.01 / Introductory Note).
- last trade date: filing (8-K 3.01 "suspended ... opening of trading on August 28, 2018").
- payout rule: filing, but the package is in the Rule 425 of 2018-08-23 (0001193125-18-256393), BPY's expectation of the post-proration result, not the closing 8-K.
- terms: the 8-K states only $0.312 as "Per Share Merger Consideration"; the 14.642 / 0.376 / 0.986 figures are the 425's expectation after proration. The pre-closing dividend (record 2018-07-27, paid 2018-08-27) is treated as consideration because the 425 includes it and the 8-K values it with the merger consideration; its ex-date (whether the 2018-08-27 close still carries it) is not in the filings read. A final-proration filing (BPY 6-K or BPR 8-K) would make this verified.

## 5. What happened
- Merger Effective Time 8:20 a.m. 2018-08-28; GGP survived as Brookfield Property REIT Inc.; Per Share Merger Consideration $0.312 cash [SEC 8-K 2018-08-28](https://www.sec.gov/Archives/edgar/data/1496048/000119312518260735/d614210d8k.htm).
- Pre-Closing Dividend (cash, BPR Class A or BPY units by election, prorated) payable 2018-08-27 (same 8-K, Introductory Note).
- GGP common suspended from NYSE at the open of 2018-08-28; Form 25 filed 2018-08-28; BPR Class A began on Nasdaq as BPR (same 8-K, Item 3.01).
- Post-proration packages per share, dividend plus merger cash: cash-electing $14.642 + 0.376 BPY/BPR A; stock-electing 0.986 BPY/BPR A + $0.312; non-electing $14.642 + 0.376 BPY [SEC 425 2018-08-23](https://www.sec.gov/Archives/edgar/data/1496048/000119312518256393/d605844d425.htm).
- Fails rows: GGP (36174X101) 2018-08-03..08-24 (last settle row), BPR (11282X103) from 2018-08-30; two different CUSIPs.
- Form 15-12B filed 2018-09-07 for the old common [SEC](https://www.sec.gov/Archives/edgar/data/1496048/000119312518269113/d620780d1512b.htm).

## 6. Decision-tree bucket
Replaced by cash and stock of another company (a merger). The same issuer CIK survives and a Class A stock trades as BPR, but it is a new security obtained by election, not a one-for-one holdco swap, and cash is part of the exchange.

## 7. Why the library got it wrong
Old run: no ending found for a security whose issuer kept filing and whose successor-class listing looked like continued existence (the regression's cause, fixed by the new run). New run: the LLM/regex read the one stated "Per Share Merger Consideration" ($0.312) and missed that the pre-closing dividend is part of the deal consideration; flags `llm_gate_failed`, `merger_at_par`, `assumed_par_after_failed_gate`. Cause: terms_misread.

## 8. Fix and open checks
Terms need the dividend-plus-merger package (default non-elector). Open: confirm the final proration in BPY's 6-K / BPR's 8-K, and the NYSE ex-date of the dividend (due bill) so the last close is cum-dividend. Golden-worthy: yes, as a case for dividend-plus-merger-cash election packages.

## 9. Verification
Re-opened through sec.py. Both field verdicts upheld.
- delistings.added (exit_kind=merger, last_trade_date=2018-08-27): 8-K 0001193125-18-260735 (filed 2018-08-28, items 2.01, 3.01, 5.01) says the Merger Effective Time was 8:20 a.m. on 2018-08-28, each GGP common share was cancelled for the right to receive cash ($0.312 stated), and the common was "suspended from trading on the NYSE effective as of the opening of trading on August 28, 2018", so the last trade is 2018-08-27. The 25-NSE 0000876661-18-000943 (GGP Inc. Common Stock, 12d2-2(a)(3), filed and effective 2018-08-28) matches; -000944 is the preferred. The common was cancelled for consideration, so merger and not continuation (the new BPR Class A is a different CUSIP).
- security_history.ranges (GGP to 2018-08-27): follows from the same suspension; the old end 2018-08-24 was only the last fails row.
- Outside these verdicts: the report itself calls its value_rule and terms (14.642 + 0.376 BPY) inferred from a Rule 425, not a closing filing. That does not affect them.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new merger row, its 2018-08-27 last trade and its range end right where the base had no ending; its cash-only 0.312 terms are wrong (the package is about 14.642 cash plus 0.376 BPY), but the terms gate failed, so the contract publishes an assumed-par fill and verdict uncertain. The terms are a residual for the merger-terms reader.

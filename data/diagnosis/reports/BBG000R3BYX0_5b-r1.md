# BBG000R3BYX0_5b-r1 (BKC, Burger King Holdings) - regression

## 1. Verdict
Burger King Holdings was acquired by 3G (Blue Acquisition Sub) for $24.00 cash; merger effective 2010-10-19, last trade 2010-10-19. The new run's added merger row and the ticker range ending 2010-10-19 are right; the base run (no delisting, range to 2010-11-15) was wrong.

## 2. Library vs evidence
| Field | Old (base) | New (now) | Evidence | Right |
| --- | --- | --- | --- | --- |
| delistings.added | no contract row | merger, last trade 2010-10-19, cash, 24.00 | Form 25-NSE 0000876661-10-000412 filed 2010-10-20 | new |
| exit_kind | none | merger | $24.00 cash for each share not tendered | new |
| last_trade_date | none | 2010-10-19 | EX-99.25: suspended from trading on 2010-10-20, so last trade 2010-10-19 | new |
| value_rule / terms | none | cash 24.00 USD | EX-99.25 text | new |
| security_history.ranges | BKC 2008-01-08..2010-11-15 | BKC 2008-01-08..2010-10-19 | listing ended with the merger | new |
| issuer | 1352801 | 1352801 | filer of the Form 25 | agree |

## 3. Corrected classification
```
exit_kind=merger drop_reason= continuation=false successor=
last_trade_date=2010-10-19
value_rule=cash cash_per_share=24.00 cash_currency=USD stock_ratio= price_ticker= price_sec_id= price_date= recovery_ratio=
value_formula=24.00 USD / last_close - 1
event_type=acquisition consideration=cash holder_value=24.00 USD cash effective_date=2010-10-19 successor_ticker= confidence=verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 25-NSE 0000876661-10-000412 (merger agreement effective 2010-10-19, shares converted to cash).
- successor: filing, none named; cash conversion.
- last trade date: filing, same notice, suspended 2010-10-20.
- payout rule: filing, same notice.
- terms: filing, $24.00 per share; the tender offer is SC TO-T 0000950123-10-086742.

## 5. What happened
- [SEC SC TO-T 2010-09-16](https://www.sec.gov/Archives/edgar/data/1352801/000095012310086742/y86597sctovt.htm): tender offer by the 3G vehicle.
- [SEC 25-NSE 2010-10-20](https://www.sec.gov/Archives/edgar/data/1352801/000087666110000412/): merger effective 2010-10-19, $24.00 per share, suspended 2010-10-20.

## 6. Decision-tree bucket
Replaced by cash of another company (merger).

## 7. Why the library got it wrong
The base run published no delisting and left the range open to a later sighting; the sub-plan's Form 25 reach rules now find the 25-NSE. Cause: other:base run missed the Form 25 (fixed by 5b). The new run is right.

## 8. Fix and open checks
None for the new run. The `resolved_from_continued_filings` uncertainty is a weak reason string; the Form 25 and notice date are present. Golden-worthy: yes.

## 9. Verification
Upheld. Re-opened 25-NSE 0000876661-10-000412 (filed 2010-10-20, NYSE, class Common Stock, Rule 12d2-2(a)(3)): the merger with Blue Acquisition Sub became effective 2010-10-19, each share not tendered converted to $24.00, and the security was suspended from trading 2010-10-20, so the last trade is 2010-10-19. The issuer's filing list shows a 15-12B on 2010-11-01 and no BKC trading after the merger. Both field verdicts hold: delistings.added (merger, 2010-10-19, cash 24.00) and security_history.ranges (BKC ending 2010-10-19, CIK 1352801). No missed_filing is claimed, none needed for a "new" verdict.

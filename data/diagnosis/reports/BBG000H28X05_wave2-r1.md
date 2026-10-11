# BBG000H28X05_wave2-r1 (PAS, PepsiAmericas)

## 1. Verdict
PepsiAmericas merged into a PepsiCo subsidiary on 2010-02-26: each share became, at the holder's election, 0.5022 PEP shares or $28.50 cash, prorated 50/50 in aggregate; a non-electing share gets the PEP shares. The new row (stock, 0.5022 x PEP) is the better one: the old row (cash 28.50) published only the cash election. The ending itself is a merger on both sides.

## 2. Library vs evidence (regression: old = base run, new = current run)
| Field | old | new | evidence | status |
| --- | --- | --- | --- | --- |
| value_rule | cash | stock | election deal; default (no election) = stock | new right |
| cash_per_share | 28.50 | blank | 28.50 is the cash election only, not the default | new right (see note) |
| stock_ratio | blank | 0.5022 | 0.5022 PEP per PAS share | new right |
| price_ticker / price_sec_id | blank | PEP / BBG000DH7JK6 | acquirer PepsiCo | new right |
| price_date | blank | 2010-03-01 | trading day after 2010-02-26 close | new right |
| exit_kind | merger | merger | 8-K 5.01/3.01 | agree |
| last_trade_date | 2010-02-26 | 2010-02-26 | merger 8-K says completed 2010-02-26, NYSE notified that day | agree (inferred) |

Note: the agreement fixes an aggregate 50% cash / 50% stock. An aggregate package would be cash_plus_stock, 14.25 cash + 0.2511 PEP. Neither side published that; the new side matches the non-election default.

## 3. Corrected classification
```
exit_kind: merger   drop_reason:   continuation: false   successor:   last_trade_date: 2010-02-26
value_rule: stock   cash_per_share:   cash_currency: USD   stock_ratio: 0.5022
price_ticker: PEP   price_sec_id: BBG000DH7JK6   price_date: 2010-03-01   recovery_ratio:
value_formula: 0.5022 x price(PEP, 2010-03-01) / last_close - 1  (default package; election alternative $28.50 cash, 50/50 aggregate proration)
event_type: merger   consideration: cash_or_stock_election   holder_value: 0.5022 PEP shares or $28.50 cash, prorated 50/50
effective_date: 2010-02-26   successor_ticker: PEP   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing, 8-K 0000950103-10-000534 (merged with and into Metro).
- successor: filing, same 8-K (PepsiCo acquirer); none as continuation.
- last trade date: worked out from the 8-K's Feb 26 completion and NYSE notice; the Form 25-NSE 0000876661-10-000073 notice was not read in full. A filing stating the last trading day would make it verified.
- payout rule: filing (DEFM14A 0001193125-10-005743 and the 8-K), but which package to publish for an election deal is a convention choice (default stock vs aggregate 50/50).
- terms: filing, 0.5022 and $28.50 stated in both.

## 5. What happened
- DEFM14A 2010-01-13: either 0.5022 PEP shares or $28.50 cash per share, 50/50 aggregate proration, no-election shares get PEP stock [SEC DEFM14A](https://www.sec.gov/Archives/edgar/data/1084230/000119312510005743/ddefm14a.htm).
- 15-12B filed 2010-02-22 [SEC](https://www.sec.gov/Archives/edgar/data/1084230/000095012310015164/c56402e15v12b.htm) and 8-K 2010-03-01 (items 3.01, 3.03, 5.01): merger completed Feb 26 [SEC 8-K](https://www.sec.gov/Archives/edgar/data/1084230/000095010310000534/dp16634_8k-pepa.htm).
- Form 25-NSE filed 2010-03-01 [SEC](https://www.sec.gov/Archives/edgar/data/1084230/000087666110000073/xslF25X02/primary_doc.xml).

## 6. Decision-tree bucket
Replaced by stock/cash of another company: merger.

## 7. Why the library differs
The old run took the cash election as the whole payout; the new run takes the default package. Cause: terms_misread (old side).

## 8. Fix and open checks
None needed on the new row. Optional: publish the aggregate as cash_plus_stock (14.25 + 0.2511 PEP). Confirm the last trading day from the Form 25 notice. Golden-worthy: yes (election deal with a default).

## 9. Verification
Re-read the 8-K 0000950103-10-000534 (each PAS share became, at the holder's election, 0.5022 PEP shares or $28.50 cash, 50/50 aggregate proration; merger effective Feb 26 2010) and DEFM14A 0001193125-10-005743 (Example "No Election": non-electing shares all get 0.5022 PEP shares, no cash). Feb 26 2010 is a Friday, so the next trading day 2010-03-01 is the right price_date. The reference allows the default or aggregate package for an election deal; the default (stock) is stated and the cash leg is blank consistently. PEP is the acquirer. All six field verdicts survive. Caveat: the choice of default over the 50/50 aggregate is a convention, already disclosed in the report.

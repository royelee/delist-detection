# BBG000MRMY60_wave1-r1 (MHS, Medco Health Solutions) - regression, field price_sec_id

## 1. Verdict
Medco merged into Express Scripts Holding Co; each share became $28.80 cash plus 0.81 (new) ESRX share, effective before the open on 2012-04-02. The new run's `price_sec_id` = BBG000C15T95 (the ESRX composite) is right; the base run's blank was a missing term. The row is otherwise right.

## 2. Library vs evidence
| Field | Library says (old -> new) | Evidence says | Status |
| --- | --- | --- | --- |
| exit_kind | merger | merger | agree |
| drop_reason | blank | blank | agree |
| continuation | false | false (cash plus another company's stock) | agree |
| successor | blank | blank | agree |
| last_trade_date | 2012-03-30 (MIDAS) | merger effective before open 2012-04-02 (Monday), so Friday 2012-03-30 | agree |
| value_rule | cash_plus_stock | cash_plus_stock | agree |
| terms | cash 28.80, ratio 0.81, ESRX, 2012-04-02; price_sec_id old blank, new BBG000C15T95 | 28.80 USD + 0.81 ESRX; ESRX line in securities.csv is BBG000C15T95 (EXPRESS SCRIPTS HOLDING, ESRX 2007-12-24 to 2018-12-20) | agree (new); old was missing |
| issuer | CIK 1170650 | Medco CIK 1170650 | agree |
| ticker_history | MHS 2008-01-16 to 2012-03-30 | consistent with the last trade | agree |

## 3. Corrected classification
```
exit_kind: merger   drop_reason:    continuation: false   successor:
last_trade_date: 2012-03-30
value_rule: cash_plus_stock  cash_per_share: 28.80  cash_currency: USD  stock_ratio: 0.81
price_ticker: ESRX  price_sec_id: BBG000C15T95  price_date: 2012-04-02  recovery_ratio:
value_formula: (28.80 + 0.81 x price(ESRX, 2012-04-02)) / last_close - 1
event_type: merger  consideration: cash_and_stock  holder_value: 28.80 USD cash + 0.81 ESRX share
effective_date: 2012-04-02  successor_ticker: ESRX  confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, Form 25-NSE 0000876661-12-000148 notice (merger effective, shares converted).
- successor: none; filing, same notice (acquirer's shares, not a one-for-one continuation).
- last trade date: filing, the notice says effective before the opening on 2012-04-02, so the trading day before, 2012-03-30; matches MIDAS.
- payout rule: filing, same notice.
- terms: filing, same notice ($28.80 cash and 0.81 share); price_sec_id from the run's securities.csv.

## 5. What happened
- 2012-04-02 8-K items 3.01, 3.03, 5.01, 5.03 (0001193125-12-144957): [SEC](https://www.sec.gov/Archives/edgar/data/1170650/000119312512144957/d328745d8k.htm).
- 2012-04-03 Form 25-NSE by NYSE (0000876661-12-000148), rule 12d2-2(a)(3): merger effective before the opening on April 2, 2012; each Medco share converted into $28.80 cash and 0.81 share of (New) Express Scripts Holding Company: [SEC](https://www.sec.gov/Archives/edgar/data/1170650/000087666112000148/xslF25X02/primary_doc.xml).

## 6. Decision-tree bucket
Replaced by cash and another company's stock: merger, not a continuation.

## 7. Why the library got it wrong
It did not in the new run. The base run published a blank `price_sec_id`; the new run resolves ESRX to the run's security BBG000C15T95. Cause: other:old blank price_sec_id was a missing term, now filled.

## 8. Fix and open checks
Nothing to fix. The new value should stand. No market price checked. Not a golden case beyond what exists.

## 9. Verification
Upheld. Re-read the cached Form 25-NSE 0000876661-12-000148 (cache/edgar/raw): Medco CIK 1170650, Common Stock, rule 12d2-2(a)(3), notice says each share became $28.80 cash and 0.81 of a share of (New) Express Scripts Holding Company. The ESRX line BBG000C15T95 in securities.csv and contract/security_history.csv covers the old Express Scripts (CIK 885721, to 2011-11-18) and the holding company (CIK 1532063, from 2011-11-19), so the ESRX share received on 2012-04-02 is that composite. price_sec_id = BBG000C15T95 is right; the base run's blank was a missing term.

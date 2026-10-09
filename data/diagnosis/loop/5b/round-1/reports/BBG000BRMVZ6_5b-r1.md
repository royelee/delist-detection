# BBG000BRMVZ6_5b-r1 (PSD, Puget Energy) - regression

## 1. Verdict
Puget Energy's common stock was cashed out at $30.00 per share in the merger with Puget Holdings LLC (effective 2009-02-06) and removed by the NYSE (Form 25-NSE). The NEW row (merger ending, last trade 2009-02-06, range ending 2009-02-06) is right; the OLD run (no ending, range to 2009-06-08) was wrong, because it followed the issuer's continued filings (a debt registrant).

## 2. Library vs evidence
| field | library says (new) / old | evidence says | status |
| --- | --- | --- | --- |
| exit_kind | merger / (no row) | merger, cash-out | agree (new) |
| drop_reason | blank | blank | agree |
| continuation | false | false (cash paid for the shares) | agree |
| successor | none | none (Puget Holdings LLC is the private parent) | agree |
| last_trade_date | 2009-02-06 | merger effective Fri 2009-02-06; NYSE suspended trading 2009-02-09, so last trade 2009-02-06 | agree |
| value_rule | cash | cash | agree |
| terms | 30.00 cash, currency blank, no stock | $30.00 USD cash, no stock | agree (currency to be filled USD) |
| issuer | CIK 1085392 | Puget Energy, CIK 1085392 | agree |
| ticker_history | new PSD 2008-01-16..2009-02-06; old ..2009-06-08 | listing ended 2009-02-06 | new right |

## 3. Corrected classification
```
exit_kind: merger   drop_reason:   continuation: false   successor:   last_trade_date: 2009-02-06
value_rule: cash   cash_per_share: 30.00   cash_currency: USD   stock_ratio:   price_ticker:   price_sec_id:   price_date:   recovery_ratio:
value_formula: 30.00 USD / last_close - 1
event_type: acquisition (LBO, going private)   consideration: cash   holder_value: 30.00 USD cash per share
effective_date: 2009-02-06   successor_ticker:   confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing - Form 25-NSE 0000876661-09-000098 (merger effective 2009-02-06, cash conversion) and 8-K 0001193125-09-027209.
- successor: filing - none; the Form 25 says shares were converted to cash only.
- last trade date: filing - Form 25-NSE notice: merger effective 2009-02-06, suspended from trading 2009-02-09 (next trading day after Friday 02-06).
- payout rule: filing - Form 25-NSE: "converted into $30.00 in cash per share".
- terms: filing - same notice; USD is the unstated currency of a NYSE US deal.

## 5. What happened
- [SEC 25-NSE 2009-02-09](https://www.sec.gov/Archives/edgar/data/1085392/000087666109000098/xslF25X02/primary_doc.xml): merger between Puget Energy and Puget Holdings LLC effective 2009-02-06; each common share converted into $30.00 cash; suspended 2009-02-09; removal at open of business 2009-02-19.
- [SEC 8-K 2009-02-12](https://www.sec.gov/Archives/edgar/data/1085392/000119312509027209/d8k.htm): items 1.01, 2.03, 3.01, 5.01 - consummation of the merger; Puget Energy survives as an indirect wholly owned subsidiary.
- [SEC 15-12B 2009-02-09](https://www.sec.gov/Archives/edgar/data/1085392/000119312509022695/d1512b.htm) filed for the common stock; Puget Energy kept filing 10-K/10-Q afterwards (debt), which is what misled the old run.

## 6. Decision-tree bucket
Replaced by cash of another company (merger / going private).

## 7. Why the library got it wrong
The OLD base run had no ending: the continued 10-K/10-Q filings after the end hid the Form 25 (cause: continued_filings_guess). The new row is right; its `resolved_from_continued_filings` flag only reflects weak evidence.

## 8. Fix and open checks
No fix needed on the new row; publish cash_currency USD. The old range to 2009-06-08 was wrong. Good golden case (Form 25 + 8-K, simple cash LBO with a surviving filer).

## 9. Verification
Skeptic pass. Re-read Form 25-NSE 0000876661-09-000098 through sec.py: class "Common Stock (Holding Company)", Rule 12d2-2(a)(3); the EX-99.25 says the merger of Puget Energy and Puget Holdings LLC became effective 2009-02-06, each common share was converted into $30.00 cash, and the security was suspended from trading on 2009-02-09 (a Monday), so the last trade is Friday 2009-02-06. The security is the common stock, not a debt line. Both field verdicts survive.
- delistings.added (new right): exit kind merger, no successor, no continuation, last trade 2009-02-06, value_rule cash all supported.
- security_history.ranges (new right): the range ends 2009-02-06, not the old 2009-06-08.
Caveat: the library's 29.98 close is a price, not checked here; irrelevant to the verdicts.

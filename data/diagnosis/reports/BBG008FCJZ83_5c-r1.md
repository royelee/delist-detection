# BBG008FCJZ83_5c-r1 (STE, STERIS plc UK) - regression

## 1. Verdict
On 2019-03-28 STERIS plc (UK, CIK 1624899) became a wholly owned subsidiary of STERIS plc (Ireland, CIK 1757898) under an English scheme of arrangement; each share became one Irish share, which trades on the NYSE as STE. That is a 1:1 holding-company reorganization, a continuation. The new run (side b: exchange, continuation, successor BBG00MRHG523, value_rule continuation) is right; the base run's merger / stock 1:1 priced at STE was wrong.

## 2. Library vs evidence
| field | old (base) | new (library now) | evidence | status |
|---|---|---|---|---|
| exit_kind | merger | exchange | one-for-one share swap into the Irish parent, no cash | new right |
| continuation | false | true | Rule 12g-3 successor issuer, same ticker STE | new right |
| successor_sec_id | blank | BBG00MRHG523 | securities.csv: CIK 1757898, STE from 2019-03-28 | new right |
| value_rule | stock | continuation | no value event; holder keeps an equivalent share | new right |
| stock_ratio / price_ticker / price_date | 1.0 / STE / 2019-03-28 | blank | a continuation has no value | new right |
| last_trade_date | 2019-03-27 | 2019-03-27 | Form 25-NSE 0000876661-19-000290 notice, scheme effective 2019-03-28 | agree |

## 3. Corrected classification
```
exit_kind: exchange
drop_reason:
continuation: true
successor: BBG00MRHG523 (STERIS plc, Ireland, CIK 1757898, STE)
last_trade_date: 2019-03-27
value_rule: continuation
cash_per_share:
cash_currency:
stock_ratio:
price_ticker:
price_sec_id:
price_date:
recovery_ratio:
value_formula: none (continuation)
event_type: redomiciliation_scheme
consideration: one STERIS Ireland ordinary share per STERIS UK share
holder_value: unchanged
effective_date: 2019-03-28
successor_ticker: STE
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-19-089161 Items 2.01/3.01 (scheme, one-for-one).
- successor: filing, same 8-K (STERIS Ireland successor issuer under Rule 12g-3, NYSE symbol STE).
- last trade date: filing, Form 25-NSE 0000876661-19-000290 notice date, one trading day before the 2019-03-28 effective date.
- payout rule: filing, same 8-K (no cash, share for share).
- terms: none needed.

## 5. What happened
- Scheme of arrangement completed 2019-03-28; STERIS Ireland owns all STERIS UK share capital; holders receive one Irish share per scheme share ([SEC 8-K 2019-03-28](https://www.sec.gov/Archives/edgar/data/1624899/000119312519089161/d722899d8k.htm)).
- STERIS Ireland is the Rule 12g-3 successor issuer; its shares trade on NYSE as STE (same 8-K).
- NYSE Form 25-NSE filed 2019-03-28 for the UK shares; STERIS UK filed Form 15-12B 2019-04-08 ([SEC Form 25-NSE](https://www.sec.gov/Archives/edgar/data/1624899/000087666119000290/xslF25X02/primary_doc.xml)).

## 6. Decision-tree bucket
Kept the same security: 1:1 holding-company reorganization, only the issuer's domicile changed.

## 7. Why the library got it wrong
The base run (before sub-plan 5c) classified the Form 25 as a merger and priced a 1.0 stock leg on STE. The 5c rule linking a transfer to what the registrant's 8-K says the shares became, one for one, now fixes it. Cause: merger_misread_as_transfer (base only; current is correct).

## 8. Fix and open checks
No fix needed. Golden-worthy: well sourced 1:1 redomiciliation. No open checks.

## 9. Verification
Upheld, all seven field verdicts. Re-read 8-K 0001193125-19-089161 through sec.py: Item 2.01 says each Scheme Share holder receives one STERIS Ireland ordinary share per share held, no cash; STERIS Ireland is the Rule 12g-3(a) successor issuer; Item 3.01 says UK shares were suspended before the open on 2019-03-28 and Irish shares began trading as STE at the open. securities.csv holds BBG00MRHG523 as CIK 1757898, COMMON, STERIS. A 1:1 holdco scheme with no cash is a continuation (decision 9), so exit_kind exchange, continuation true, successor BBG00MRHG523, value_rule continuation and a blank stock leg are right; the base's stock 1.0 on STE was wrong. No refutation found.

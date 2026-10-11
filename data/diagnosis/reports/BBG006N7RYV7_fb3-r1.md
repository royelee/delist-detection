# BBG006N7RYV7_fb3-r1 (FNFV Group common stock), regression

## 1. Verdict
FNF redeemed all FNFV Group tracking stock on 2017-11-17 (5:00 p.m. ET) for Cannae Holdings common stock, one for one, no cash: a split-off into a new issuer, i.e. a 1:1 continuation (exchange), not a stock merger into Black Knight. The new run's row (merger, stock, 0.306632 BKI) is wrong in kind and terms; the old run had no row at all, also wrong. Only the new ticker range end (2017-11-17) is right.

## 2. Library vs evidence
| field | old (base) | new (library) | evidence | status |
| --- | --- | --- | --- | --- |
| delistings row | none | merger row | an ending exists (25-NSE 0000876661-17-000713, 8-K 0001104659-17-069547) | old wrong, new right that a row exists |
| exit_kind | n/a | merger | exchange (split-off, 1:1 into Cannae) | wrong |
| continuation / successor | n/a | false / none | true, successor Cannae Holdings (not in the run) | wrong |
| last_trade_date | n/a | 2017-11-17 | redemption effective 2017-11-17 5 p.m. ET; last session 2017-11-17 | agree |
| value_rule / terms | n/a | stock, 0.306632 x BKI | none (continuation); 0.3066322 BKI is the ratio for FNF Group holders (8-K 0001331875-17-000104), not FNFV | wrong |
| issuer | CIK 1331875 | 1331875 | FNF (registrant of the tracking stock) | agree |
| ticker_history | FNFV to 2017-11-21 | FNFV to 2017-11-17 | ends at last trade 2017-11-17 | new right |

## 3. Corrected classification
```
exit_kind: exchange       drop_reason:        continuation: true
successor: Cannae Holdings Inc (CNNE), sec_id not in run       last_trade_date: 2017-11-17
value_rule: continuation  cash_per_share:     cash_currency:     stock_ratio: 1 (Cannae per FNFV; no price needed)
price_ticker:  price_sec_id:  price_date:  recovery_ratio:
value_formula: n/a (continuation; 1 FNFV -> 1 Cannae share, cash only in lieu of fractions)
event_type: reorganization (split-off)   consideration: stock   holder_value: 1 Cannae share
effective_date: 2017-11-17   successor_ticker: CNNE   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: filing (8-K 2017-11-20, 0001104659-17-069547: redemption of all FNFV for Cannae shares).
- successor: filing names Cannae; its ticker CNNE and sec_id are worked out, not read from a filing here; the run lacks the security.
- last trade date: filing states the effective time 2017-11-17 5 p.m. ET; the library has MIDAS 2017-11-17.
- payout rule: filing (one for one, cash only for fractions).
- terms: filing.
Not backed: the successor ticker and sec_id; Cannae's own first filing or first-trade notice would make it verified.

## 5. What happened
- Split-off completed 2017-11-17 5:00 p.m. ET: each FNFV share redeemed for one Cannae share ([SEC 8-K 2017-11-20](https://www.sec.gov/Archives/edgar/data/1331875/000110465917069547/a17-27153_18k.htm)).
- Proxy: each FNFV share, restricted shares included, to one Splitco share; cash only for fractions ([SEC DEFM14A 2017-10-19](https://www.sec.gov/Archives/edgar/data/1331875/000104746917006453/a2233579zdefm14a.htm)).
- The 0.3066322 BKI ratio is the Black Knight spin-off to FNF Group holders ([SEC 8-K 0001331875-17-000104](https://www.sec.gov/Archives/edgar/data/1331875/000133187517000104/fnfbkdistribution8-k.htm)); the LLM cache entry for FNFV quotes it.
- 25-NSE for FNFV Group Common Stock filed 2017-11-20 ([SEC](https://www.sec.gov/Archives/edgar/data/1331875/000087666117000713/xslF25X02/primary_doc.xml)).
- Fails rows of CUSIP 31620R402 end 2017-11-21 (last 17.35).

## 6. Decision-tree bucket
Replaced 1:1 by a new line of the same holders (Cannae), no cash: continuation.

## 7. Why the library got it wrong
It relabelled the ending a merger from 8-K evidence and the LLM read the BKI spin-off 8-K (FNF Group's ratio) as FNFV's terms; the terms gate failed (`fail_sanity`) and the value is assumed par. Cause: terms_misread (with wrong_exit_kind).

## 8. Fix and open checks
Read the Splitco redemption 8-K for FNFV, not the BKI distribution 8-K; add Cannae as a successor line (not in the run). Confirm CNNE's first trade 2017-11-20 (web). Golden-worthy.

## 9. Verification
Upheld, both field verdicts.
- delistings.added (neither): 8-K 0001104659-17-069547 states the Split-Off at 5:00 p.m. ET on 2017-11-17, each FNFV share redeemed for one Cannae share. That is a 1:1 continuation into a new issuer, so the new merger/stock row is wrong. The base run had no row for an ending that exists, so it is wrong too. 8-K 0001331875-17-000104 gives the 0.3066322 ratio to holders of FNF Group common stock, not FNFV, so the BKI terms are a misread.
- security_history.ranges (new): the FNFV range ends 2017-11-17, the last session before the 5 p.m. redemption. The old end of 2017-11-21 was the fails-row tail.
- Weak point: the successor ticker CNNE is not read from a filing here. This does not change either verdict.

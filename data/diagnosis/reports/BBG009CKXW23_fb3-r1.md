# BBG009CKXW23_fb3-r1 (PTHN, Patheon N.V.) - regression

## 1. Verdict

Thermo Fisher bought Patheon in a $35.00 cash tender offer that closed 2017-08-29; Patheon asked the NYSE to suspend trading after the close on 2017-09-01 and filed the Form 25 that day. The new run is right on both changed fields: it adds the merger ending (it was missing in the base run) and it ends the ticker range at 2017-09-01 under issuer CIK 1643848 (Patheon N.V.) instead of 2017-10-10 under CIK 1400431.

## 2. Library vs evidence

| Field | Old (base) | New | Evidence says | Status |
| --- | --- | --- | --- | --- |
| `delistings.added` (exit_kind, drop_reason, continuation, successor, last_trade_date, value_rule) | no contract row | merger, none, false, none, 2017-09-01, cash | merger, no drop reason, not a continuation, no successor, 2017-09-01, cash | new right |
| `security_history.ranges` | PTHN 2016-07-26..2017-10-10, issuer 1400431 | PTHN 2016-07-26..2017-09-01, issuer 1643848 | listing ended after the close 2017-09-01; Patheon N.V. (1643848) filed the Form 25, the 8-Ks and the 15-12B | new right |
| terms | none | cash 35.00 USD, gate passed | $35.00 per share in cash, USD | agree |
| issuer | 1400431 | 1643848 | 1400431 shows one filing in 2016-2018 (SC TO-C 2017-05-15, a tender-offer communication), no Patheon filings; 1643848 is the registrant (Commission File 001-37837) | new right |

## 3. Corrected classification

```
exit_kind: merger        drop_reason:      continuation: false   successor:
last_trade_date: 2017-09-01
value_rule: cash   cash_per_share: 35.00   cash_currency: USD   stock_ratio:
price_ticker:   price_sec_id:   price_date:   recovery_ratio:
value_formula: 35.00 / last_close - 1
event_type: acquisition (tender offer)   consideration: cash   holder_value: 35.00 USD cash per share
effective_date: 2017-08-29 (offer closing)   successor_ticker:   confidence: verified
```

## 4. Why this confidence

verified.
- exit kind: filing, 8-K 2017-09-05 Items 2.01, 5.01 (Thermo Fisher acquired about 95.3% in the offer closing).
- successor: filing, none; cash purchase, no successor shares.
- last trade date: filing, the same 8-K Item 3.01 (NYSE asked to suspend trading after the close of business on 2017-09-01) and Form 25 dated 2017-09-01.
- payout rule: filing, 8-K Item 2.01 (tender offer at $35.00 per share, cash).
- terms: filing, the same Item 2.01: $35.00, no interest, USD.

## 5. What happened

- 2017-05-15: Patheon, Thermo Fisher and its Luxembourg purchaser sign the Purchase Agreement ([SEC 8-K 2017-09-05](https://www.sec.gov/Archives/edgar/data/1643848/000110465917055475/a17-21071_28k.htm), Item 2.01).
- Offer at $35.00 per share in cash, without interest ([SEC 8-K 2017-09-05](https://www.sec.gov/Archives/edgar/data/1643848/000110465917055475/a17-21071_28k.htm)).
- 2017-08-22: Patheon gave the NYSE notice of voluntary delisting, conditioned on the offer's expiry ([SEC 8-K 2017-08-22](https://www.sec.gov/Archives/edgar/data/1643848/000156761917001749/s001839x1_8k.htm)).
- 2017-09-01: Form 25 under Rule 12d2-2(c), signed 2017-09-01 ([SEC Form 25](https://www.sec.gov/Archives/edgar/data/1643848/000110465917055224/a17-21071_325.htm)); the 8-K says the NYSE was asked to suspend trading after the close of business that day.
- 2017-09-13: Form 15-12B ([SEC 15-12B](https://www.sec.gov/Archives/edgar/data/1643848/000110465917056944/a17-21980_11512b.htm)).

## 6. Decision-tree bucket

Replaced by cash of another company: merger, not a continuation.

## 7. Why the library got it wrong

The new run is not wrong. The base run lacked the ending and carried the range to 2017-10-10 under CIK 1400431, so the issuer lookup had resolved to a company that is not Patheon. Cause: `other:base run issuer misresolved (1400431), fixed in the new run`.

## 8. Fix and open checks

None needed for the new run. 1400431's identity was not established (only that it is not Patheon's filer). Candidate golden case: PTHN, well sourced, last trade date 2017-09-01.

## 9. Verification

Upheld. Both field verdicts survive.
- Re-read 8-K 0001104659-17-055475 (CIK 1643848): Item 3.01 says Patheon asked the NYSE to suspend trading after the close of business on 2017-09-01 and filed the Form 25 that day; the offer is $35.00 per share in cash, no interest, expired 2017-08-28, closed 2017-08-29 (95.3%). So `delistings.added` (merger, no continuation, last trade 2017-09-01, cash) holds.
- Filing lists: CIK 1643848 holds the tender-offer filings, 8-Ks, Form 3/4s and S-8 POS of Aug-Sep 2017; CIK 1400431 shows one filing in 2016-2018 (SC TO-C 2017-05-15). So the range ending 2017-09-01 under 1643848 holds.
- No missed filing; no contradicting evidence found.

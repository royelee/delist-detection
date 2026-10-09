# BBG000BF3BG8_5a-r2 — Harte Hanks (HHS / HRTH), regression

## 1. Verdict

Harte Hanks was delisted from the NYSE (Form 25-NSE, 2020-07-28), traded OTC as HRTH on the same CUSIP, and uplisted to Nasdaq as HHS on 2021-12-01. The new ranges (HHS, then HRTH, then HHS) are right; the old single HHS range hid the HRTH period. The new range edges come from fails rows and are a few days late, so confidence is inferred.

## 2. Library vs evidence

Field changed: `security_history.ranges`. Old (side_a): `HHS:2008-01-16..:45919`. New (side_b): `HHS:2008-01-16..2020-07-15:45919; HRTH:2020-07-16..2021-12-02:45919; HHS:2021-12-03..:45919`.

| Field | library says | evidence says | status |
| --- | --- | --- | --- |
| exit_kind | no contract delisting row (internal exchange_transfer 304, successor = itself) | NYSE delisting then OTC, same shares kept, later Nasdaq relisting; not part of this regression | unknown |
| drop_reason | blank | NYSE-initiated delisting (NYSE Regulation notice 2020-07-09) | unknown |
| continuation | no row | same CUSIP 416196202 throughout | agree |
| successor | none | none (same security) | agree |
| last_trade_date | blank in contract (internal 2020-07-10, source midas, flagged `last_trade_date_conflict`) | the filings give no exact NYSE last day; 8-K of 2020-07-13 says OTC trading under HRTH was allowed from 2020-07-13 | unknown |
| value_rule | none | not scored here | unknown |
| terms | none | none | agree |
| issuer | 45919 on every range | Harte Hanks, CIK 45919 | agree |
| ticker_history | HHS to 2020-07-15, HRTH 2020-07-16..2021-12-02, HHS from 2021-12-03 (new); one HHS range (old) | HHS (NYSE) -> HRTH (OTC, from about 2020-07-13) -> HHS (Nasdaq, 2021-12-01) | agree (new); boundaries a few days late |

Evidence for each side: old is contradicted by the 8-K of 2020-07-13, which names HRTH as the symbol, and by the 8-K of 2021-11-30, which says the stock is on OTCQX as "HRTH" and will trade as "HHS" on Nasdaq. New agrees with both.

## 3. Corrected classification

```
exit_kind:        (not scored; internal exchange_transfer, successor = itself)
drop_reason:      
continuation:     false (no successor row; same security)
successor:        
last_trade_date:  unknown from filings (NYSE last trade about 2020-07-10)
value_rule:       unknown (not part of this case)
cash_per_share / cash_currency / stock_ratio: -
price_ticker / price_sec_id / price_date / recovery_ratio: -
value_formula:    -
event_type:       exchange_delisting_to_OTC, then uplisting (name/ticker change HHS -> HRTH -> HHS, same CUSIP)
consideration:    none
holder_value:     same shares
effective_date:   2020-07-28 (Form 25-NSE); Nasdaq listing 2021-12-01
successor_ticker: HHS (same security)
confidence:       inferred
ticker_history:   HHS 2008-01-16..~2020-07-10 (NYSE); HRTH ~2020-07-13..2021-11-30 (OTC); HHS 2021-12-01.. (Nasdaq)
```

## 4. Why this confidence: inferred

- exit kind: not part of this diff; unscored.
- successor: filing (8-K 0001437749-20-015076: "The change in ticker symbol did not result in a change to the CUSIP number").
- last trade date: not backed by a filing; the NYSE's last day is not stated in the filings read (Form 25 text gives no suspension date); fails rows put the first HRTH row at 2020-07-16.
- payout rule: not applicable to this diff.
- terms: not applicable.
- Not backed: the exact day the ticker changed (range edges 2020-07-15/16 and 2021-12-02/03 come from fails rows, which lag trades). An exchange print or a FINRA/NYSE notice giving the first OTC day and the Nasdaq first day would make it verified.

## 5. What happened

- 2020-07-09 NYSE Regulation notified Harte Hanks it would start proceedings to delist the common stock. [SEC 8-K 2020-07-13](https://www.sec.gov/Archives/edgar/data/45919/000143774920015025/hhs20200710_8k.htm)
- 2020-07-13 FINRA notified the company the stock could trade OTC under "HRTH", with no CUSIP change. [SEC 8-K 2020-07-13](https://www.sec.gov/Archives/edgar/data/45919/000143774920015076/hhs20200713_8k.htm)
- 2020-07-28 NYSE filed Form 25-NSE. [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/45919/000087666120000587/xslF25X02/primary_doc.xml)
- 2021-11-30 8-K: stock trades on OTCQX as HRTH; uplisting to Nasdaq Global Market expected 2021-12-01 under "HHS". [SEC 8-K 2021-11-30](https://www.sec.gov/Archives/edgar/data/45919/000143774921027504/hrth20211128_8k.htm); 8-A12B filed same day (0001437749-21-027508).
- Fails rows under HRTH start 2020-07-16 on CUSIP 416196202, the same CUSIP the library holds from 2018-02-01.

## 6. Decision-tree bucket

Kept the same security (same CUSIP, same FIGI). The NYSE delisting moved it to OTC and it later returned to a Nasdaq listing; ticker by date was HHS, HRTH, HHS.

## 7. Why the library got it wrong

The old run (base) had no HRTH range: the delisting stage 5/ticker-history clip left HHS open-ended. The new run follows the symbol HRTH in fails rows. Cause tag: `other:old_range_missing_HRTH` (the old row was wrong, the new one is right).

## 8. Fix and open checks

No fix needed for the ranges. Open checks: the first OTC day (about 2020-07-13) and the Nasdaq first day (2021-12-01) are 2-3 days earlier than the ranges' edges (fails-row lag). Separately, the NYSE removal (a decision-11 OTC move) has no contract ending because the library treats it as an exchange transfer to itself; the library may need to treat this as dropped/moved_otc followed by a relisting. Golden-worthy: yes, a short well-sourced case for the HHS -> HRTH -> HHS ticker path.

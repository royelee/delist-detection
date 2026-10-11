# BBG000PRJCX9_fb3b-r1 (HR, regression: security_history.ranges)

## 1. Verdict
Healthcare Trust of America (HTA, CIK 1360604) closed its reverse-acquisition merger with legacy Healthcare Realty on 2022-07-20, was renamed Healthcare Realty Trust Inc. and traded as HR from the NYSE open on 2022-07-21 (HTA's last day: 2022-07-20). The new run's split (HTA to 2022-07-21, HR from 2022-07-22) is one day late; the old run's (HTA to 2022-07-28, HR from 2022-07-29) is a week late. The new value is much closer but neither is exact.

## 2. Library vs evidence
| field | library says (old / new) | evidence says | status |
| --- | --- | --- | --- |
| security_history.ranges | old HTA ..2022-07-28, HR 2022-07-29..; new HTA ..2022-07-21, HR 2022-07-22.. | HTA ..2022-07-20, HR from 2022-07-21 | new nearer but 1 day late; old 6 trading days late |
| exit_kind / drop_reason / continuation / successor | no ending row for this line (HTA renamed, same issuer) | rename of the surviving legal acquirer; no ending of this security | agree |
| last_trade_date | none | none (line continues) | agree |
| value_rule / terms | none | none | agree |
| issuer | 1360604 both ranges | 1360604 (HTA renamed Healthcare Realty Trust Incorporated) | agree |
| ticker_history | see ranges | see ranges | wrong (1 day, new) |

Library cusip_history shows the new CUSIP 42226K105 from 2022-07-29 (ftd), while fails rows (cache) show 42226K105 as HR from 2022-07-22 and 42225P501 as HTA through 2022-07-26 (settlement tail). Fails rows are by settlement date, so they lag trades by about 2 days; this is why the range start is late.

## 3. Corrected classification
```
exit_kind: (none)   drop_reason:    continuation: n/a   successor: n/a   last_trade_date: n/a
value_rule: continuation   cash_per_share: null   cash_currency:    stock_ratio: null
price_ticker:    price_sec_id:    price_date:    recovery_ratio: null
value_formula: n/a (rename of the legal acquirer; not an exit)
event_type: ticker_change (HTA -> HR; legacy HR is a separate security that ended)
consideration: none   holder_value: HTA holders keep their shares, renamed
effective_date: 2022-07-20   successor_ticker: HR
confidence: inferred
ticker ranges: HTA 2012-06-11..2022-07-20 ; HR 2022-07-21..
```

## 4. Why this confidence
inferred.
- exit kind: filing, 8-K 0001193125-22-202185 (item 5.03: Legacy HTA changed its name to Healthcare Realty Trust Incorporated).
- successor: n/a.
- last trade date: n/a.
- payout rule: n/a.
- terms: n/a.
The switch day is worked out, not read: the 8-K says legacy HR was removed from trading before the open on 2022-07-21 and the combined company trades as HR, so the HTA line took HR on 2022-07-21 and HTA's last day was 2022-07-20. No filing states the first HR-ticker session of the HTA shares; an exchange print or the NYSE notice would make it verified.

## 5. What happened
- Merger closed 2022-07-20; legacy HR (now HRTI, LLC) merged into a subsidiary of HTA; HTA renamed Healthcare Realty Trust Incorporated, continuing on NYSE as HR. [SEC 8-K 2022-07-26](https://www.sec.gov/Archives/edgar/data/1360604/000119312522202185/d384978d8k.htm), [SEC 8-K 2022-07-21](https://www.sec.gov/Archives/edgar/data/1360604/000119312522198653/d370743d8k.htm)
- Legacy HR (a different security) was removed from NYSE trading before the open on 2022-07-21; its Form 25 was filed. Same 8-K 2022-07-26, item 3.01.
- Fails rows: CUSIP 42226K105 as HR from 2022-07-22; CUSIP 42225P501 as HTA to 2022-07-26 (settlement lag).

## 6. Decision-tree bucket
Kept the same security (the HTA shares, same issuer, renamed and re-ticked HR). Not an ending.

## 7. Why the library got it wrong
The range boundary comes from fails rows by settlement date (new run) or from the CUSIP-history start (old run), not from the first trading day. Cause: other:ticker switch date from fails-settlement dates, 1 day late.

## 8. Fix and open checks
The new run is an improvement (HR from 07-22 vs 07-29). Residual 1-day lag: HR should start 2022-07-21. Confirm with the NYSE first-day notice. Golden candidate: yes, a reverse-merger rename with a known switch date.

## 9. Verification
Upheld. Re-opened through sec.py: 8-K 0001193125-22-202185 (item 3.01) says legacy HR common stock was "removed from trading on the NYSE on July 21, 2022 before the market opened", and its Introductory Note says the combined company (legacy HTA renamed) "will continue to trade on the NYSE under the ticker symbol HR". 8-K 0001193125-22-198653 (event date 2022-07-20) puts HR on the cover for the renamed HTA class A shares. Two securities cannot share HR, so the HTA line took HR from 2022-07-21 and HTA's last day was 2022-07-20. Fails rows for CUSIP 42225P501 (HTA) run 20220701..20220726, which is settlement lag, so they do not contradict this. Both library values differ from HTA ..2022-07-20 / HR 2022-07-21.. (old by 8 days, new by 1 day), so "neither" holds. Caveat: no filing states the first HR session of the old HTA shares, so confidence stays inferred.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (HR from 2022-07-21; base 07-29, new 07-22). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

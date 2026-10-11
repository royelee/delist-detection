# CIK105319-COMMON_fb3-r1 (WW), regression

## 1. Verdict
No ending happened on 2019-09-30. Weight Watchers renamed itself WW International on 2019-09-29 and its CUSIP changed 948626106 to 98262P101, but the common stock kept trading on Nasdaq as WW. The new contract row (exchange, transfer, no successor) and the ranges that stop on 2019-09-30 are wrong; the base run (no row) was right.

## 2. Library vs evidence
| Field | old (base) | new (library) | evidence | status |
| --- | --- | --- | --- | --- |
| delistings.added | no row | exchange / transfer / blank last trade | no Form 25 or listing change in 2019; 8-K 5.03/8.01 says shares "continue to trade on The Nasdaq Stock Market LLC under the symbol WW" | old right |
| security_history.ranges | no ranges ending at 2019-09-30 | WTW to 2019-04-22; WW 2019-04-23..2019-09-30 | fails rows: new CUSIP 98262P101 under WW 2019-10-01..2025-05-16 (659 rows), then WGHTQ from 2025-05-19 | old right (history should run on under WW) |

## 3. Corrected classification
```
exit_kind: (no ending in 2019)   drop_reason:   continuation: n/a   successor: none
last_trade_date: n/a (2019)      value_rule: n/a
event_type: name_change + CUSIP change   consideration: none   holder_value: same shares
effective_date: 2019-09-29   successor_ticker: WW (same security)   confidence: verified
history: WW range continues past 2019-09-30 on CUSIP 98262P101 (fails rows to 2025-05-16)
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-19-258827 (name change, shares continue on Nasdaq as WW).
- successor: filing, the same 8-K (same security, new CUSIP 98262P 101).
- last trade date: not applicable, no ending.
- payout rule: not applicable.
- terms: not applicable.

## 5. What happened
- [SEC 8-K 2019-09-30](https://www.sec.gov/Archives/edgar/data/105319/000119312519258827/d782308d8k.htm): Item 5.03 name change to WW International, Inc. effective 2019-09-29; Item 8.01 common stock continues on Nasdaq under WW, CUSIP changed to 98262P 101.
- Fails rows: 948626106 under WW 2019-09-03..2019-09-30, then 98262P101 under WW 2019-10-01 to 2025-05-16 and under WGHTQ 2025-05-19 onward (a later, separate event, not part of this case).

## 6. Decision-tree bucket
Kept the same security (rename with a CUSIP change). Not an ending.

## 7. Why the library got it wrong
The new row is the finder's fallback guess (flags `no_form25`, `delist_date_approx`, `last_trade_date_unconfirmed`, `successor_unknown`) anchored on the old CUSIP's last fails row. Stage 4b did not follow the line across the CUSIP change that the 8-K 8.01 states. Cause: `rename_not_followed`.

## 8. Fix and open checks
Line follow should attach 98262P101 (the 8-K text names it, same registrant carries on) so the line runs on and no 2019 ending is made. The real later ending (2025 bankruptcy, WGHTQ) is a separate case and was not examined here. Golden-worthy: yes (well sourced by one filing).

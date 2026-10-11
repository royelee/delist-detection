# BBG0081JXTR0_fb3b-r1 (WBT) regression: security_history.ranges

## 1. Verdict
Manitowoc Foodservice (MFS) renamed itself Welbilt and began trading as WBT on 2017-03-06 (a Monday), so MFS's last day was 2017-03-03. The old split (WBT from 2017-03-10) is wrong by four days; the new split (WBT from 2017-03-07) is wrong by one day. The new one is closer to the filing, but neither is exact. The Ali Group acquisition (last trade 2022-07-28) is untouched by this change.

## 2. Library vs evidence
| field | library says (old / new) | evidence says | status |
|---|---|---|---|
| exit_kind | merger (unchanged) | not part of this change, not re-read | unknown |
| drop_reason | unchanged | not examined | unknown |
| continuation | unchanged | not examined | unknown |
| successor | unchanged | not examined | unknown |
| last_trade_date | 2022-07-28 (unchanged) | not re-read | unknown |
| value_rule | cash_only (unchanged) | not examined | unknown |
| terms | unchanged | not examined | unknown |
| issuer | CIK 1650962 both | same CIK before and after the rename | agree |
| ticker_history (security_history.ranges) | old: MFS 2016-03-07..2017-03-09, WBT 2017-03-10..2022-07-28; new: MFS 2016-03-07..2017-03-06, WBT 2017-03-07..2022-07-28 | WBT trading began 2017-03-06 under a new CUSIP; MFS last 2017-03-03 | wrong (old by 4 days, new by 1 day) |

## 3. Corrected classification
```
security_history.ranges: MFS 2016-03-07..2017-03-03 ; WBT 2017-03-06..2022-07-28
(other fields as the library publishes; not re-diagnosed)
event_type: rename (ticker + CUSIP change)
effective_date: 2017-03-06
successor_ticker: WBT (same security, continuation)
confidence: verified for the rename date
```

## 4. Why this confidence
Verified for the field in dispute (ticker_history). The other fields are not part of this regression.
- exit kind: not in dispute.
- successor: not in dispute.
- last trade date: not in dispute.
- payout rule: not in dispute.
- terms: not in dispute.
- ticker change date: filing, 8-K 0001193125-17-076834: "On March 6, 2017, shares of the Company commenced trading under a new New York Stock Exchange ticker symbol, WBT, and a new CUSIP number, 949090 104."

## 5. What happened
- Name change from Manitowoc Foodservice, Inc. to Welbilt, Inc. filed and effective 2017-03-03 [SEC 8-K 2017-03-09](https://www.sec.gov/Archives/edgar/data/1650962/000119312517076834/d320074d8k.htm).
- Shares commenced trading as WBT with CUSIP 949090 104 on 2017-03-06, same filing.
- The 8-K was filed 2017-03-09; the old WBT start 2017-03-10 is that filing date plus one, not the trading date.

## 6. Decision-tree bucket
Kept the same security (rename, same CIK 1650962, same FIGI).

## 7. Why the library got it wrong
The old range effectively took the 8-K filing date (03-09) as the last MFS day. The new one ends MFS on 03-06 and starts WBT on 03-07, so it treats the first WBT trading day as the last old-ticker day (one day late). Cause: other:ticker_change_boundary_off_by_one.

## 8. Fix and open checks
- WBT should start 2017-03-06 and MFS end 2017-03-03.
- Which input the new boundary comes from (sightings or fails rows) was not checked; fails rows for CUSIP 949090104 could confirm 03-06.
- Golden-worthy: yes, a well-sourced ticker change date.

## 9. Verification
Skeptic re-read of 8-K 0001193125-17-076834 (CIK 1650962) through sec.py grep. It says the name change was effective 2017-03-03 and "On March 6, 2017, shares of the Company commenced trading under ... 'WBT,' and a new CUSIP number, 949090 104." March 6, 2017 was a Monday, so MFS's last day is Friday 2017-03-03. The published ranges (output/contract/security_history.csv) are MFS ..2017-03-06 and WBT from 2017-03-07, so each is one day late. The "neither" verdict holds for both old and new. The fails rows for CUSIP 949090104 start 20170307, which does not contradict this: fails files are sparse and the first row is not the first trade. Same CIK on both sides, so the issuer is unchanged. Verdict upheld; no missed_filing was claimed.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: neither side is exact, as the report found; the new run's switch day is nearer the filing's day than the base's (WBT from 2017-03-06; base 03-10, new 03-07). A rename's switch day is the first sighting under the new ticker, which runs a day or more after the day the 8-K states; dating a rename from its 8-K is batch 4 (filings, not sightings).

# BBG002WMH2F2_fb3b-r1 (TMX, Terminix Global Holdings), regression

## 1. Verdict
The ServiceMaster to Terminix rename took effect Monday 2020-10-05, and the new CUSIP and the TMX symbol traded from that day, so the new ticker range (SERV to 2020-10-04, TMX from 2020-10-05) is right and the old one (SERV to 2020-10-07, TMX from 2020-10-08) was wrong. Only `security_history.ranges` changed; the ending itself was not re-examined.

## 2. Library vs evidence
| Field | Old (base run) | New (this run) / evidence | Status |
| --- | --- | --- | --- |
| security_history.ranges | SERV 2014-07-01..2020-10-07; TMX 2020-10-08..2022-10-11 | SERV ..2020-10-04; TMX 2020-10-05..2022-10-11. 8-K filed 2020-10-05: charter amendment changing the name "became effective as of October 5, 2020", cover page lists TMX on NYSE. Fails rows: new CUSIP 88087E100 under TMX from 20201005; old CUSIP 81761R109 under SERV has rows only to 20201006 (settling tail of the old CUSIP, not new SERV trading). | new right |
| exit_kind | merger | merger (not re-examined) | unknown |
| last_trade_date | 2022-10-11 (range end) | unchanged, not re-examined | unknown |
| value_rule / terms | stock_only | not re-examined | unknown |
| issuer | CIK 1428875 | same CIK on the 2020 8-K | agree |
| ticker_history | old ranges | new ranges | agree (new) |

## 3. Corrected classification
```
security_history: SERV 2014-07-01..2020-10-04 ; TMX 2020-10-05..2022-10-11 (CIK 1428875)
exit_kind: merger (unchanged)   drop_reason:   continuation: false   successor: (unchanged)
last_trade_date: 2022-10-11 (unchanged)
value_rule/terms: not examined
event_type: name_change (2020-10-05)   effective_date: 2020-10-05   confidence: inferred
```

## 4. Why this confidence
inferred.
- exit kind: not re-examined (unchanged by this regression).
- successor: not re-examined.
- last trade date: not re-examined.
- payout rule and terms: not re-examined.
- ticker change date: rests on the 8-K 0001104659-20-112270 (name change effective 2020-10-05) and fails rows (TMX under the new CUSIP from 2020-10-05). Only the ranges field is decided here. A verified record needs the Rentokil merger 8-K / Form 25 re-read.

## 5. What happened
- [SEC 8-K 2020-10-05](https://www.sec.gov/Archives/edgar/data/1428875/000110465920112270/tm2032288d1_8k.htm): Charter Amendment renaming ServiceMaster Global Holdings to Terminix Global Holdings, and By-Laws, effective October 5, 2020; cover shows TMX on NYSE.
- Fails rows (SEC): 88087E100 TMX 20201005..20201124; 81761R109 SERV 20200902..20201006, the old CUSIP settling after the switch.

## 6. Decision-tree bucket
Kept the same security (rename, new CUSIP). The ticker history continues under TMX from the first trading day under the new name, 2020-10-05.

## 7. Why the library got it wrong (old)
The old range ends the SERV era on the old CUSIP's last fails row (2020-10-06/07 settling tail) and starts TMX the day after. Cause: other:old CUSIP settling tail counted as ticker sighting (fixed in f56ff50).

## 8. Fix and open checks
None for ranges. Not golden-worthy as it stands. Confirm the Rentokil ending separately if wanted.

## 9. Verification
Upheld. Re-read 8-K 0001104659-20-112270 (CIK 1428875): the Charter Amendment and Restatement "became effective as of October 5, 2020", and the cover lists TMX on NYSE. Fails: CUSIP 88087E100 under TMX has rows from 20201005; CUSIP 81761R109 under SERV ends 20201006, the old CUSIP's settling tail, which is not new SERV trading. So SERV to 2020-10-04 and TMX from 2020-10-05 holds, and the base's 2020-10-07/08 split was wrong. Residual: SERV's last day may be 2020-10-02 (Fri), since 10-03/04 are a weekend. That is a calendar-day boundary and does not change the verdict.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right, from the filing it cites, and its ranges are exactly the new run's (checked against the case's sides); the confidence is inferred only because the switch day also rests on the fails rows (SERV to 2020-10-04, TMX from 2020-10-05).

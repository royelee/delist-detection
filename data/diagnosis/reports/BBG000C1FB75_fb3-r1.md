# BBG000C1FB75_fb3-r1 (ICE, regression)

## 1. Verdict
ICE's 2013 holding-company reorganization (old IntercontinentalExchange, CIK 1174746, into IntercontinentalExchange Group, CIK 1571949) converted each old share into one ICE Group share, and OpenFIGI keeps one composite FIGI (BBG000C1FB75) across both CUSIPs. The new run is right on two of three changes: the placeholder `CIK1174746-COMMON` is folded into the FIGI (a rename), and the self-successor exchange row disappears because the security does not end. The ticker-range change is wrong: the issuer switches at 2013-06-29, four months before the reorganization. The base run's 2013-11-12/14 split is nearly right, since the correct switch is 2013-11-13.

## 2. Library vs evidence
| Field | Old (base) | New | Evidence | Status |
| --- | --- | --- | --- | --- |
| delistings row | placeholder `CIK1174746-COMMON` exchange continuation to BBG000C1FB75 (handoff, last trade unconfirmed) | no row for BBG000C1FB75 | The 8-K12B says each ICE share became one ICE Group share. The same composite FIGI covers CUSIP 45865V100 (to 2013-11-12) and 45866F104 (from 2013-11-13). One security goes on, so no ending row. | new right |
| id_changes | none (separate placeholder) | `CIK1174746-COMMON` renamed to `BBG000C1FB75` | One FIGI line, one issuer family; the placeholder is the same line | new right |
| ticker ranges / issuer | ICE 1174746 to 2013-11-12, then 1571949 from 2013-11-14 | 1174746 to 2013-06-28, then 1571949 from 2013-06-29 | Old ICE (1174746) filed its 10-Q on 2013-11-05, was the exchange-listed registrant until the merger closed on 2013-11-13, and filed the 25-NSE. ICE Group shares began regular-way trading on 2013-11-13. | old closer (exact switch 2013-11-13) |
| exit_kind / continuation | exchange / true | no ending | Holdco 1:1, no cash for the old share: a continuation, here inside one FIGI | agree (as no real ending) |
| last_trade_date | blank | none | Not applicable; no ending | agree |
| value_rule | continuation | none | No value | agree |

## 3. Corrected classification
```
exit_kind: (no ending for BBG000C1FB75)   continuation: n/a (same sec_id)
issuer in force: 1174746 through 2013-11-12; 1571949 from 2013-11-13
id_changes: CIK1174746-COMMON -> BBG000C1FB75 (rename)
event_type: reorganization   consideration: stock (1:1, no cash)   confidence: inferred
```

## 4. Why this confidence
inferred. Exit kind: `filing` (8-K12B 0001193125-13-440066). Successor: same FIGI, which rests on OpenFIGI and fails rows (CUSIP 45866F104 from 2013-11-14), not a filing. Last trade date: not needed. Payout: none. Terms: none. The exact issuer switch day rests on the 8-K12B's "began regular-way trading on November 13, 2013". The issuer range cause below is worked out from the outputs, not from code.

## 5. What happened
- [SEC 8-K12B 2013-11-13](https://www.sec.gov/Archives/edgar/data/1571949/000119312513440066/d625077d8k12b.htm): at the effective time of the ICE Merger, each ICE common share became the right to receive one ICE Group share; ICE Group shares began regular-way trading on the NYSE on 2013-11-13; the old ICE stock was delisted.
- [SEC 25-NSE 0000876661-13-000825](https://www.sec.gov/Archives/edgar/data/1174746/000087666113000825/), CIK 1174746, effective 2013-11-13.
- [SEC 10-Q 2013-11-05](https://www.sec.gov/Archives/edgar/data/1174746/000119312513426548/d596213d10q.htm) by old ICE, 1174746. Old ICE therefore remained the issuer after 2013-06-29.
- Fails rows: CUSIP 45865V100 under ICE 2013-06-03..2013-11-12; CUSIP 45866F104 under ICE from 2013-11-14.

## 6. Decision-tree bucket
Replaced 1:1 by a new line of the same holders (holdco reorganization), under one composite FIGI, so no ending row.

## 7. Why the library got it wrong
Only the ticker ranges. The last observation is 2013-06-28, and the folded line takes the new CIK as issuer from the next day. Cause: `issuer_history_bug`.

## 8. Fix and open checks
- Issuer timeline: switch 1174746 to 1571949 on the reorganization date (2013-11-13), not the day after the last observation.
- Whether the regression guard should treat a same-FIGI holdco as no ending: yes, per the decision table.
- Golden-worthy: yes, well sourced.

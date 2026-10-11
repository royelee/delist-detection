# BBG000PV2L86 (TNL) regression, security_history.ranges

## 1. Verdict
Wyndham Destinations (WYND) renamed itself Travel + Leisure Co. (TNL), effective 12:01 AM ET on 2021-02-17. It is a rename, not an ending. The new range (TNL from 2021-02-17, WYND to 2021-02-16) is right; the old range (TNL from 2021-02-19, WYND to 2021-02-18) started the new ticker two sessions late.

## 2. Library vs evidence
| Field | Old (side_a) | New (side_b) / evidence | Status |
| --- | --- | --- | --- |
| security_history.ranges | TNL 2021-02-19.., WYND 2018-06-04..2021-02-18 | TNL 2021-02-17.., WYND 2018-06-04..2021-02-16. The charter amendment was effective 12:01 AM ET on 2021-02-17 and the 8-K of that day carries TNL (NYSE) on its cover. Fails rows show TNL (CUSIP 894164102) from 2021-02-17 at $51.75. | new is right |
| WYN range 2007-12-17..2018-06-03 | same | same | agree |
| exit_kind / continuation / successor / last_trade_date / value_rule / terms | none (no ending) | none (a rename on the same issuer, CIK 1361658) | agree |
| issuer | 1361658 | 1361658 | agree |

## 3. Corrected classification
```text
exit_kind        =
drop_reason      =
continuation     =
successor        =
last_trade_date  =
value_rule       =
event_type       = name_change / ticker_change (WYND -> TNL)
effective_date   = 2021-02-17
successor_ticker = TNL
confidence       = inferred
ticker_history   = WYN 2007-12-17..2018-06-03; WYND 2018-06-04..2021-02-16; TNL 2021-02-17..
```

## 4. Why this confidence
Inferred.
- Exit kind: filing (8-K 2021-02-17, item 5.03: name change only, no delisting).
- Successor: not applicable.
- Last trade date: not applicable.
- Payout rule and terms: not applicable.
- The range boundary rests on the filing (name change effective 2021-02-17, TNL on the cover of the 8-K of that day) and on fails rows (first TNL row 2021-02-17). I did not read an exchange print or the press release stating the first session under TNL. That would make it verified.

## 5. What happened
- Charter amendment renaming Wyndham Destinations to Travel + Leisure Co., effective 12:01 AM ET on 2021-02-17; the 8-K cover lists "TNL, New York Stock Exchange" ([SEC 8-K 2021-02-17](https://www.sec.gov/Archives/edgar/data/1361658/000136165821000018/wyn-20210217.htm)).
- Fails rows: WYND (98310W108) 2021-02-02..2021-02-18, last $51.75; TNL (894164102) 2021-02-17..2021-02-26, first $51.75. The CUSIP changed with the name, which makes the same-price rows on 02-17/02-18 the old CUSIP's settling tail (fails).
- The library's cusip_history still starts the new CUSIP on 2021-02-19 (it follows the fails tail).

## 6. Decision-tree bucket
Kept the same security (same issuer and line, new name, ticker and CUSIP): a rename.

## 7. Why the library got it wrong
The old range used the old CUSIP's last fails row (2021-02-18) as the end of WYND, so TNL began 2021-02-19. The new build starts TNL on the name-change date. Cause tag: `rename_not_followed` (late start of the new ticker only).

## 8. Fix and open checks
- Keep the new ranges. The cusip_history start of 894164102 (2021-02-19) is still the fails-tail date and could move to 2021-02-17.
- Open: confirm the first NYSE session under TNL is 2021-02-17 from an exchange print.
- Golden case: no.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new run right, from the filing it cites, and its ranges are exactly the new run's (checked against the case's sides); the confidence is inferred only because the switch day also rests on the fails rows (TNL from 2021-02-17).

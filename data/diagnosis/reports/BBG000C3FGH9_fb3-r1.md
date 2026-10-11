# BBG000C3FGH9_fb3-r1 (GHC, regression)

## 1. Verdict
The Washington Post Company renamed itself Graham Holdings Company on 2013-11-29; Class B moved from WPO to GHC with a new CUSIP (939640108 to 384637104), same issuer, same holders, same security. This is a rename, not an ending. The new run is right: no delisting row, one FIGI line, and the old placeholder CIK104889-COMMON is the same security as BBG000C3FGH9.

## 2. Library vs evidence
| Field | Old (base) | New | Evidence | Status |
| --- | --- | --- | --- | --- |
| delistings (exit_kind etc.) | exchange, last trade 2013-11-27, transfer, no successor | no row | no ending; name and ticker change on one issuer | new right |
| security_history.ranges | GHC from 2012-06-29 (overlaps WPO); WPO to 2013-11-27 | WPO 2007-12-26..2013-11-28; GHC from 2013-11-29 | GHC symbol effective 2013-11-29 (8-K item 8.01); 11-28 was Thanksgiving, so WPO's last session was 11-27 and the new boundary is consistent | new right |
| id_changes.sec_id | CIK104889-COMMON | BBG000C3FGH9 | same issuer CIK 104889, same class B | new right (the rename is correct) |

## 3. Corrected classification
```text
exit_kind        = (no ending)
continuation     = false (no row at all; a rename)
last_trade_date  = n/a
value_rule       = n/a
event_type       = name_change / ticker_change
effective_date   = 2013-11-29
successor_ticker = GHC (same security)
confidence       = verified
```

## 4. Why this confidence
Verified.
- Exit kind: filing (8-K 2013-11-29, item 5.03: name change effective 2013-11-29; no Form 25 in the window).
- Successor: filing (same registrant, CIK 104889).
- Last trade date: not applicable; the symbol change is stated in 8-K item 8.01.
- Payout rule and terms: not applicable, nothing was exchanged.

## 5. What happened
- [SEC 8-K 2013-11-29](https://www.sec.gov/Archives/edgar/data/104889/000095015713000428/form8k.htm): "effective November 29, 2013, The Washington Post Company changed its name to Graham Holdings Company"; item 8.01: "the trading symbol of the Company's Class B common stock on the New York Stock Exchange changed to GHC. The new CUSIP number ... is 384637 104."
- Filings of CIK 104889 from 2013-10-15 to 2014-01-15 hold no Form 25, 15 or 8-K12B.
- Fails rows: CUSIP 939640108 (WPO) 20131101..20131125, CUSIP 384637104 (GHC) from 20131129.

## 6. Decision-tree bucket
Kept the same security (rename with a CUSIP change).

## 7. Why the library got it wrong (base run)
The base run could not follow the CUSIP change, left a placeholder CIK104889-COMMON ending at the name change and wrote a continued-filings transfer (`no_form25;delist_date_approx;successor_unknown`). Cause: rename_not_followed. The new run's line follow folds it into the FIGI line.

## 8. Fix and open checks
None needed; the new output is correct. Could be a golden case (rename with CUSIP change).

## 9. Verification
Upheld, all three field verdicts. Re-opened 8-K 0000950157-13-000428 (filed 2013-11-29): item 5.03 name change effective 2013-11-29, item 8.01 Class B symbol on the NYSE changed to GHC, new CUSIP 384637 104. Filing list of CIK 104889 for 2013-10-15..2014-01-15 holds only 8-Ks and a 10-Q: no Form 25, 15 or 8-K12B, so no ending. Fails rows: WPO CUSIP 939640108 ends 20131125, GHC CUSIP 384637104 starts 20131129 at a continuous price ($658.20 to $658.27), the same class B security. The new run's security_history (WPO ..2013-11-28, GHC 2013-11-29..) and id_changes rename CIK104889-COMMON to BBG000C3FGH9 match this. Nothing refuted.

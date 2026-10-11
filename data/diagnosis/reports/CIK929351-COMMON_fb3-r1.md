# CIK929351-COMMON_fb3-r1 (LGF, Lions Gate Entertainment Corp common shares), regression

## 1. Verdict
On 2016-12-08 Lions Gate reclassified each common share into 0.5 Class A voting (LGF.A) and 0.5 Class B non-voting (LGF.B) share of the same issuer, with no cash, as a step of the Starz merger. The old common line ended and the same holders own the new lines: a continuation (reclassification), not an unknown ending. The new run is right that an ending exists and that the range stops 2016-12-08 (old run: no ending, range to 2016-12-12), but its row (`unknown`, blank kind) is wrong. Neither run is fully right.

## 2. Library vs evidence
| Field | Old run | New run | Evidence | Status |
| --- | --- | --- | --- | --- |
| delistings.added | no contract row | row: exit_kind blank, continuation=false, no successor, no last trade, value_rule unknown | An ending exists: NYSE Form 25-NSE for "Common Shares" filed 2016-12-09, 8-K item 3.01/3.03 of 2016-12-08 | row should exist (new), contents wrong |
| exit_kind | none | blank (unknown) | `exchange` (reclassification into two classes of the same issuer) | wrong (both) |
| continuation / successor | none | false / none | true; successors LGFA BBG000K1T0M8 and LGFB BBG00FFJY867 (0.5 each); both are in the run (security_history, 2016-12-12 start) | wrong / missing |
| last_trade_date | n/a | blank (internal 2016-12-08 from fails rows, unconfirmed) | 2016-12-08 (Closing Date; reclassification "immediately prior to" the merger; new shares trade from the next session). Not stated as a print in a filing | agree (inferred), unpublished |
| value_rule | unknown | unknown | `continuation` (no value) | wrong |
| terms | none | none | 0.5 LGF.A + 0.5 LGF.B per common share, no cash | missing |
| issuer | 929351 | 929351 | 929351 (same registrant) | agree |
| ticker_history | LGF 2008-01-08..2016-12-12 | LGF 2008-01-08..2016-12-08 | Common last traded 2016-12-08; LGF.A/LGF.B begin 2016-12-12 in the run (fails rows for the old CUSIP 535919203 run to 2016-12-12 are settlement of the last trade) | new is right |

## 3. Corrected classification
```
exit_kind: exchange
drop_reason:
continuation: true
successor: CIK of same issuer, LGFA (BBG000K1T0M8) and LGFB (BBG00FFJY867), 0.5 each
last_trade_date: 2016-12-08
value_rule: continuation
cash_per_share:
cash_currency:
stock_ratio: 0.5 LGFA + 0.5 LGFB
price_ticker:
price_sec_id:
price_date:
recovery_ratio:
value_formula: none (continuation)
event_type: reorganization (share reclassification)
consideration: stock (same issuer, no cash)
holder_value: 0.5 LGF.A voting + 0.5 LGF.B non-voting per common share
effective_date: 2016-12-08
successor_ticker: LGF.A / LGF.B
confidence: inferred
```

## 4. Why this confidence: inferred
- exit kind: filing, 8-K 0001571049-16-020445 items 2.01, 3.01, 3.03 and 25-NSE 0000876661-16-001474.
- successor: filing (8-K says LGF.A and LGF.B trade on NYSE); the two sec_ids come from the run's security_history.
- last trade date: worked out. The 8-K gives the closing date 2016-12-08 but no "last traded" statement; fails rows for CUSIP 535919203 end 2016-12-12 (settlement). Would be verified by an exchange print or the NYSE notice stating the last day.
- payout rule: filing (no cash, a reclassification).
- terms: filing, 0.5 and 0.5.

## 5. What happened
- Reclassification: each common share became 0.5 Class A voting and 0.5 Class B non-voting share immediately before the Starz merger, no cash [SEC 8-K 2016-12-08](https://www.sec.gov/Archives/edgar/data/929351/000157104916020445/t1602966_8k.htm).
- Item 3.01: the company asked NYSE to delist the common shares; voting and non-voting shares trade on NYSE as LGF.A and LGF.B [same 8-K].
- NYSE filed Form 25-NSE for the Common Shares on 2016-12-09 under 12d2-2(b)/(c) [SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/929351/000087666116001474/xslF25X02/primary_doc.xml).
- Form 15-12B was filed 2016-12-19 for the old class [SEC 15-12B](https://www.sec.gov/Archives/edgar/data/929351/000157104916020691/t1603086_x1submission.htm); the issuer kept reporting (10-Q 2017-02-09).

## 6. Decision-tree bucket
Replaced 1:1 in value-neutral terms by new lines of the same holders in the same issuer (reorganization), with no cash: continuation.

## 7. Why the library got it wrong
The new run adds an ending but cannot classify it: it was dated only by fails rows (no Form 25 matched to this placeholder security, flags `unexplained_ending`, `last_trade_date_unconfirmed`). The Form 25-NSE for the "Common Shares" was not matched, and the reclassification into two successors (a split into two lines, which the one-successor R1 link cannot express) was not read. Cause: `successor_not_in_run` variant, here `other:reclassification_into_two_classes_unlinked`.

## 8. Fix and open checks
- Match the 25-NSE to the placeholder (the common is the only class of that kind) and treat the same-CIK reclassification as a continuation to LGFA (and LGFB).
- The placeholder CIK929351-COMMON could fold to a FIGI; not checked.
- Confirm the last common session (2016-12-08) from an exchange print.
- Golden-worthy: yes, once a one-to-two continuation is expressible.

## 9. Verification
Upheld. Re-read 8-K 0001571049-16-020445: Item 2.01 states that immediately prior to the merger on the Closing Date (2016-12-08) each common share was converted into 0.5 Class A voting and 0.5 Class B non-voting share of Lions Gate, no cash (Item 3.02 repeats it). Item 3.01 asks NYSE to delist the common shares and says LGF.A and LGF.B will trade on the NYSE. 25-NSE 0000876661-16-001474 was filed and effective 2016-12-09 for the old class. security_history holds BBG000K1T0M8 (LGFA) and BBG00FFJY867 (LGFB) for CIK 929351 from 2016-12-12, and CIK929351-COMMON ends 2016-12-08. So delistings.added is "neither" (the new run's row is blank, unknown and not a continuation, and the old run had none) and the new range end 2016-12-08 is right. Caveat: 2016-12-08 as last trade is inferred from the Closing Date, not from a printed last session.

## Operator ruling (2026-10-10)

Settled `new_right` in the ledger: the report finds the new range end (2016-12-08) right and the blank-kind row wrong, since the common was reclassified into 0.5 LGF.A + 0.5 LGF.B. A continuation into two lines is no row the contract can hold; the blank-kind uncertain ending with no published last trade is the representation FB-004's library response and consumer review agreed for an ending no rule can classify. It asserts no kind, so it states nothing wrong; the base had no ending.

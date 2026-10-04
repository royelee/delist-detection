# D. Successors and links (48 cases: rename_not_followed 23, holdco_not_linked 15, successor_not_in_run 6, reclassification_not_linked 4)

Reference rule (CAL/MIR reports, step 1: "link an issuer's lines across a ticker and CUSIP change as a continuation"):
same CIK and class; the old line stops and the new one starts within days; the issuer renamed at the switch, or a filing
states a transfer of the same stock; no bankruptcy (8-K 1.03) in the window (UAL 2006 must not link). Call it the LINK rule.
Coverage: it fixes themes 1, 2 and 6 directly (same CIK). Themes 3, 4, 5 and 7 need it for the follow-through but also
need their own rule (acquirer-side misread; same-issuer class reclassification; a successor with a NEW CIK in the run;
a successor the run never observed). The one-to-many split is a spec question, not a rule.

Code anchors (src/delist_detection/): `security_master.cusip_handoffs` (today consumed only by the issuer second pass,
`ticker_resolver.infer_issuers`), `history.ticker_sightings/cusip_sightings/backfill_cusips`, the 304 fallback
(`classifier._detect_continued_filings`, classifier.py:176/720; `delistings.DelistingFinder`), `end_of_era.signals/resolve`,
`successors.successor_in_run` (window last trade -5/+15 days, else Form 25 filing date, else delist_date; exactly one
candidate), `successors.successor_from_8k12b` (`exclude_cik`), `pipeline._find_successors` (stage 9),
`handoffs.find_handoffs/decide_handoff/own_continuation_filing/apply_handoffs` (`CONTINUATION_DAYS = 10`),
`pipeline._add_acquirers`, `added_securities.AddedSuccessor`.

---

## Theme 1. Follow a rename or CUSIP switch before the fallback ending is made (extend the one security)

**Pattern.** Observations stop under the old ticker, or the old CUSIP's fails rows stop. No Form 25 exists, so the
continued-filings fallback (304, flags `no_form25`, `delist_date_approx`, `successor_unknown`, often
`last_trade_date_unconfirmed`) makes an exchange_transfer ending at the last sighting and clips ticker_history and
cusip_history there. Either the same CUSIP trades on under a new symbol (HSC->NVRI, CLI->VRE, SFI->STAR, EXBD->CEB,
CLNY->DBRG) or the CUSIP changed at the rename and the new CUSIP's fails rows were never attached (JNY, ANN, WPG, SNH,
OEH, HYH, LMCA->STRZA, APY). Uncertain reasons: `continued_filings_rule`, `last_trade_date_unconfirmed`.

**Rule (LINK rule, run before the fallback).** Before the finder falls back to "10-K/Q filings kept coming", test
whether the issuer's line continues: (a) fails rows of the same CUSIP under another symbol after the last sighting
(extend ticker_history from them); or (b) a CUSIP switch (`cusip_handoffs` kind `switch`: old CUSIP stops, new CUSIP's
first fails row within `SWITCH_DAYS`, same CIK and class) corroborated by a rename (EDGAR name change, 8-K 5.03) or a
filing that states the transfer. When it holds, add the new CUSIP to cusip_history and the new ticker to ticker_history,
emit no ending, and let a later Form 25 on the new line match this security (JNY 2014, ANN 2015, OEH, APY, HYH, SFI, SNH
may each have a real later ending, to be found after the follow).

**Where.** Consume `cusip_handoffs` in `pipeline._resolve_securities`/`_security_cusips` (attach the switch CUSIP to the
era's security), add a forward counterpart of `history.backfill_cusips` (CUSIPs of fails rows under the successor symbols
after the end), and guard the fallback in `pipeline._find_delistings` / `classifier._detect_continued_filings` so it does
not fire when a followed line exists.

**Guard.** Same CIK and class; rename or filing evidence (never timing alone: decision 9 makes timing-only uncertain);
no 8-K 1.03 in the window (UAL 2006). Must NOT link: a spin-off whose CUSIP is new but whose issuer differs (the
resolver's rename check already refuses it); post-bankruptcy equity; a ticker passed to another issuer (LMCA 2013's new
Liberty Media CIK 1560385 is a ticker takeover, not a continuation). The 4a2 plan parked "15 no-Form-25 fallback endings
MIDAS shows still trading" as an operator call against the CLAUDE.md invariant on unconfirmed fallback days; this theme
needs that call (it is the same family).

**Cases (13).**
- rename_not_followed (12): BBG000BLH3P8_2023-06-20 HSC; BBG000C7WZ16_2010-10-15 JNY; BBG000C9N6Q9_2011-03-15 ANN;
  BBG000CL1HL7_2021-12-10 CLI; BBG005PWSVQ3_2016-08-31 WPG; BBG00D30HGP6_2021-06-23 CLNY; CIK1066104-COMMON_2012-08-13 EXBD;
  CIK1075415-COMMON_2020-01-07 SNH; CIK1095651-COMMON_2013-12-19 SFI; CIK1115836-COMMON_2014-07-01 OEH;
  CIK1606498-COMMON_2018-07-11 HYH; CIK1723089-COMMON_2021-01-10 APY (rename, then a real Nasdaq->NYSE transfer on a found
  Form 25 dated 2020-12-31; correct row is `exchange` with successor = itself, or no row).
- successor_not_in_run (1): CIK1507934-CLASS-A_2013-01-16 LMCA (old Liberty Capital renamed Starz, ticker STRZA, same CIK;
  the new LMCA is a ticker takeover; end the old LMCA ticker_history 2013-01-11).

**Effect.** Ending row disappears (or becomes `exchange` with successor = itself); ticker_history and cusip_history
extend; `continued_filings_rule`, `last_trade_date_unconfirmed`, `successor_unknown` go. Later real endings (JNY cash
merger 15.00 on 2014-04-08; ANN merger 37.34 + 0.68 ASNA ~2015-08-21) newly appear and need their own value/last-trade work.

**Risks.** Newly surfaced endings; extra fails-row reads on a cold run; SFI/EXBD/OEH rest on fails rows only (no filing
states the date); a renamed security whose CUSIP was really reused.

**Spec.** Decision 9 (rename and an unchanged CUSIP continue; a link on timing alone is uncertain, so the evidence must be a
rename or a filing). Open: is fails-row-only evidence enough for verdict certain?

---

## Theme 2. Merge two securities of the run that are one issuer line (placeholder + FIGI line, or an era split by a CUSIP change)

**Pattern.** The CUSIP change at a rename split one line into two securities (a placeholder `CIK...-COMMON` and a FIGI line,
or two eras). The old line ends by the 304 fallback, or two securities are tied by `continuation_by_timing_only`; a
placeholder may also absorb a stale or reused ticker. Reasons: `continued_filings_rule`, `continuation_by_timing_only`,
`security_uncertain` (`ticker_overlap:LVNTA`); flags `member_name_mismatch`, `successor_unknown`.

**Rule.** At the identity stage, when an era's issuer CIK and class match another security of the run and a shared CUSIP or a
CUSIP switch (`cusip_handoffs` `shared_cusip`/`switch`) joins them, resolve the era to that security's sec_id (a FIGI keeps
its composite through renames), so `build_securities` merges them and no ending is made. Extend `superseded_placeholders`
(today: a later FIGI line of the issuer and class that holds the ticker) to a CUSIP-switch holder. Stale-ticker observations
(UAG after the rename to PAG) resolve by CUSIP/issuer, not ticker+name.

**Where.** `security_master.build_securities`, `resolve_many`, `superseded_placeholders`, `cusip_handoffs`;
`observations.split_eras` must not split on a documented rename; `handoffs.decide_handoff` rule 2 stays as the fallback.

**Guard.** Same CIK + class + rename filing (8-K 5.03) or shared CUSIP; never merge across a bankruptcy window or two classes
(MSG Class A vs Class B). LVNTA is a different line (redeemed into GCI Liberty 2018-03-09) and must stay apart from
QVCA/QRTEA. A reused ticker (new MSG, different CIK) stays a ticker takeover.

**Cases (5).** CIK1019849-COMMON_2009-06-08 UAG (stale ticker; resolve to BBG000H6K1B0, ticker_history reads PAG);
CIK1469372-CLASS-A_2015-10-02 MSG (merge into BBG000NS03H7; new MSG is the takeover); CIK1355096-COMMON_2018-04-11 QRTEA
(library_wrong=False: the row is fine, uncertainty is the timing-only link and two securities for one line);
CIK352363-COMMON_2012-05-14 LIZ (LIZ/FNP/KATE one line; BBG000C4WJT9 holds KATE's FIGI); CIK23666-COMMON_2012-07-13 SLE
(merge into BBG000BT4T69; reverse-split CUSIP switch 803111103 -> 432589109). All rename_not_followed.

**Effect.** Placeholders vanish from securities.csv (contract/id_changes.csv lists them); ending rows vanish;
`continuation_by_timing_only`, `security_uncertain`, `continued_filings_rule` go; security_history gains the other ticker spans.

**Risks.** sec_id changes for callers keyed on a placeholder; OpenFIGI must give the same composite for the new CUSIP
(open in LIZ, SLE, MSG, QRTEA); over-merging.

**Spec.** Decisions 1 and 9. No new ruling.

---

## Theme 3. The registrant is the acquirer or survivor: end-of-era 2.01/5.01/425 read as "the registrant was acquired"

**Pattern.** `end_of_era.resolve` branch 3 (5.01 change in control) and branch 4 (2.01 plus a merger filing: 425, S-4,
DEFM14A) take the 8-K as the registrant being merged away. When the registrant is the acquirer or surviving issuer (a
merger that renamed it, a reverse merger, a Separation), a merger ending is made, the LLM reads the other side's ratio
(RRI: Mirant's 2.835; FI: Expro's 1.212; CEIX: Arch's), the gate fails and par is assumed. Reasons:
`resolved_from_continued_filings`, `assumed_par_after_failed_gate`; flags `merger_at_par`, `terms_gate_failed:*`, `no_form25`.

**Rule.** Branches 3 and 4 apply only when the registrant is the target. Add signals to `end_of_era.signals()`: the
merger filing's filer or the 2.01's subject is the registrant as offeror/issuer of the consideration; or the registrant's CIK
carries on, with an 8-K 5.03 name change and a new ticker or CUSIP in the days after. Then fall through to the continued-filings
branch and, with theme 1, to no ending. A 2.01 describing a Separation or spin-off is not a merger (NWS-A). The LLM terms call
must not run for a row that ends non-merger.

**Where.** `end_of_era.signals()` and `.resolve()`; `pipeline._merger_payouts` (skip when the verdict is not merger).

**Guard.** A true 2.01 + 5.01 target merger (other CIK acquires, registrant's shares exchanged, Form 25 or 15 follows) must still
read as merger. Run the test per security: in a merger of equals the *target* of each side still ends.

**Cases (6, all rename_not_followed).** CIK1126294-COMMON_2010-12-03 RRI (->GenOn GEN, CUSIP 74971X107 -> 37244E107; GenOn
not in run); CIK1363851-COMMON_2012-07-24 SXCI (->Catalyst CTRX); CIK1575828-COMMON_2021-10-01 FI (->XPRO, CUSIP N3144W105,
XPRO not in run); CIK1710366-COMMON_2025-01-16 CEIX (->CNR, 20854L108 -> 218937100, not observed);
CIK1042893-COMMON_2024-09-04 DRQ (5.01 reverse-merger rename ->INVX, CUSIP 457651107);
CIK1308161-COMMON_2013-07-01 NWS-A (2.01 for the Separation; the skeptic REFUTED the last_trade_date and successor claims:
the published last_trade is already blank and the successor blank, so do not build on those two; only "a Separation 2.01 is no
merger" stands).

**Effect.** `merger_at_par`, `assumed_par_after_failed_gate`, `terms_gate_failed:*`, `resolved_from_continued_filings` go; the
row is no ending (theme 1 follow, or the new line added as in theme 7: GenOn, XPRO, CNR). This is also the other half of the
CAL/MIR price-security fix (their acquirer line GEN/UAL becomes a real security).

**Risks.** The LLM-terms stage no longer sees these rows, so a mistaken skip hides a real merger; filer-is-acquirer needs text.

**Spec.** Decisions 4 and 9. None new.

---

## Theme 4. Same-issuer share-class reclassification or conversion, 1:1, successor class already in the run

**Pattern.** One class is reclassified or converted 1:1 into another class of the same issuer (CMCSK->CMCSA 2015; DISCK->WBD
2022 via 3.03; CWENA->CWEN 2026; Hubbell Class B->new common 2015). No rule reads 3.01/3.03/5.03 text or the Form 25's
"substitution" wording as a class conversion, so the row lands in the 304 fallback or `no_evidence_default`, or is priced as a
merger (DISCK: the issuer's own 2.01 read as the issuer being acquired). Reasons: `continued_filings_rule`,
`no_evidence_default`, `unknown_exit_kind`, `assumed_par_after_failed_gate`; flag `successor_unknown`.

**Rule.** A Form 25 (or the fallback) on class X plus an 8-K 3.03/5.03 stating "each share of class X is reclassified/converted
into one share of class Y" of the same CIK, with Y a security of the run: continuation, `successor_sec_id` = Y, no value. A same
issuer's 2.01 in that 8-K does not make a merger (theme 3 guard). Where class X also has a placeholder duplicating Y's FIGI
line (HUB-B), resolve it to Y so no ending exists (theme 2 route).

**Where.** New branch in `end_of_era.resolve` ahead of branch 4, or a text rule in `classifier._classify_items`; the link in
`pipeline._find_successors`: `successor_in_run` cannot do it today, since Y is OLD (first_seen years earlier, outside -5/+15)
and shares the CIK, so it needs its own "same CIK, other class, existed before" branch.

**Guard.** One for one and no cash in the exchange (decision 9, BHI ruling). Another ratio, or cash for one class (Hubbell Class A
got cash on the same 25-NSE: that class stays a merger/ending), is not this rule. Never another issuer's class.

**Cases (4).**
- holdco_not_linked (2): BBG000BFTJ91_2015-12-21 CMCSK (successor BBG000BFT2L4); BBG000VMWHH5_2022-04-18 DISCK (successor
  BBG011386VF4).
- reclassification_not_linked (2): BBG004P33PN3_2026-05-11 CWENA (Class A->Class C 1:1, successor CWEN);
  CIK48898-CLASS-B_2016-01-03 HUB-B (successor BBG000BLK267; confirm which 25-NSE covers which class).

**Effect.** `continuation=true`, `exit_kind=exchange`, successor named, `value_rule=continuation`, no value; `no_evidence_default`,
`unknown_exit_kind`, `assumed_par_after_failed_gate`, `continued_filings_rule` go.

**Risks.** Needs filing text, not item codes alone; a conversion that is part of a squeeze-out.

**Spec question.** Decision 9 says "same claim": CMCSK (non-voting) to CMCSA (voting), CWENA to CWEN's Class C change the
class's voting/economics. The four reports call it a continuation (1:1); the operator should confirm a class change counts.

---

## Theme 5. 1:1 holding-company reorganization (new CIK), successor line in the run but not linked

**Pattern.** 4a2 links a pair only through `find_handoffs` plus the successor's own 8-K12B/12G3 within the window. These are
not linked, so the row is a merger (2.01/5.01 read as acquisition, LLM reads 1.0 x successor ticker, no price date:
`terms_gate_failed:no_acq_price|no_acq_ticker`, `merger_at_par`) or an exchange_transfer with `successor_unknown`.
Reasons: `resolved_from_continued_filings`, `assumed_par_after_failed_gate`, `continued_filings_rule`, `last_trade_date_unconfirmed`.
Failure modes seen:
 (a) no 8-K12B; the 8-K carries the 5.01 plus a 3.03/12g-3 statement (SBGI, WAG, MYL, DTV);
 (b) the ending is anchored on a wrong date (Form 25 filing + 10, or approximate), so the successor's first sighting falls
 outside `successor_in_run`'s -5/+15 window (BHI end 2017-07-15; HHC end 2023-08-24 vs Form 25 08-14; MYL 2020-11-26 vs 11-16);
 (c) the successor starts much later because no observation covers the gap (ESV: starts 2012, stop 2009-12-23);
 (d) a split-off into a new issuer with no 8-K12B (LLYVA/LLYVK; 4a2 parked them).

**Rule.** A delisting whose successor line is in the run is a continuation (no value, `successor_sec_id` set) when (i) the
successor's own 8-K12B/12G3 names it, or the 8-K states the holders' shares converted one for one into the new parent's
(5.01 + 3.03 "converted into one share"), or the LLM terms read `stock_ratio == 1.0`, `cash == 0` with the acquirer being the
in-run security that holds the same ticker or begins within days; and (ii) no cash in the exchange (BHI ruling). Anchor the
window on the Form 25 effective date / 8-K date, not the guessed `delist_date`. A successor in the run with the same ticker,
class and issuer from the stop onward but starting later (ESV) is backfilled to start at the stop.

**Where.** `successors.successor_in_run` (anchor day; same-ticker branch outside the window); `handoffs.decide_handoff`
rule 1 and `own_continuation_filing` (add the 8-K text / 12g-3 path); `end_of_era.resolve` branch 3 (a 5.01 with a 1:1 new-parent
signal -> transfer with successor); `pipeline._merger_payouts`/`payout_rule` (a 1.0 stock leg on the same ticker reconciles as
continuation). Clip the old ticker_history at the last trade.

**Guard.** One for one AND the same holders. If the *listed holders* receive cash or other consideration for the old shares it is a
merger (decision 9 exception). Never link a takeover (successor existed before under another ticker, `decide_handoff` rule 3).

**Cases (9).**
- holdco_not_linked (8): BBG000BD4VG8_2017-07-15 BHI (BHGE; the $17.50 is BHGE's special dividend after the exchange, settled);
  BBG000BPQD31_2020-11-26 MYL (Viatris BBG00Y4RQNH4, clip at 2020-11-16); BBG000F2XXP2_2023-05-31 SBGI (BBG01GJ3NY88, Rule 12g-3 in an 8-K;
  library priced it as acquirer stock); BBG000MJRJJ2_2023-08-24 HHC (HHH BBG01HTMDZ54); BBG01HMFL081_2025-12-25 LLYVA (->BBG01YY256K1);
  BBG01HMFLTN1_2025-12-25 LLYVK (->BBG01YYX1Z14); CIK104207-COMMON_2015-01-09 WAG (WBA BBG000BWLMJ4); CIK944868-COMMON_2009-11-29 DTV
  (BBG000FL1TC8, overlap `ticker_overlap:DTV`, last trade 2009-11-19).
- successor_not_in_run (1; the successor IS in the run, non-adjacent): CIK314808-COMMON_2010-01-08 ESV (CIK314808-CLASS-A).

**Effect.** merger -> `exchange` continuation with `successor_sec_id`, `value_rule=continuation`, no value; `assumed_par_after_failed_gate`,
`merger_at_par`, `terms_gate_failed:*`, `continued_filings_rule`, `resolved_from_continued_filings`, `ticker_overlap` go; last trade
dated by the Form 25 notice (MYL 2020-11-16, LLYV* 2025-12-15, DTV 2009-11-19) where an exchange print allows.

**Risks.** Over-linking a real merger whose acquirer holds the same ticker at ratio 1.0; LLYVA/LLYVK, DTV and WAG carry other
consideration or dilution in the same transaction.

**Spec questions.** (A) LLYVA/LLYVK redeemed one for one into shares of a NEW, different issuer (a tracking-stock split-off): same
holders, but the claim moves to another company; the reports say continuation, decision 9 does not mention split-offs.
(B) DTV: 1:1 for DTV holders inside a dilutive co-merger; confirm that the 1:1 leg alone decides.

---

## Theme 6. Same-CIK successor registration (8-K12B filed by the same registrant): new CUSIP or domicile, same issuer

**Pattern.** The reorganization keeps the CIK (CCO, ACXM, BGCP, GTES). The end-of-era resolver reads the 8-K12B
(`resolved_from_continued_filings`) and makes an exchange_transfer with `successor_unknown`, or `no_evidence_default` /
`unknown_exit_kind`. `successor_from_8k12b` takes `exclude_cik=e.cik`, so a same-CIK hit is excluded; the new CUSIP line is either
missing or a separate unlinked security. Reasons: `resolved_from_continued_filings`, `issuer_from_todays_ticker_map`, `no_form25`,
`last_trade_date_unconfirmed`.

**Rule.** The LINK rule on the same CIK: when the 8-K12B/12G3 is filed under the delisted security's own CIK and the new CUSIP's
fails rows start the next session under the same ticker (or the transfer is dated by the Form 25), link the new CUSIP to the same
security. If OpenFIGI gives the new line the same composite (CCO, GTES expected), the ending is dropped (successor = itself;
histories continue); if not, add it (`AddedSuccessor`) and link as a continuation. A holdco step followed by an exchange transfer
(ACXM -> RAMP on NYSE, later Form 25 2018-10-01) dates the transfer on the later Form 25 and records the CUSIP switch
(005125109 -> 53815P108) in cusip_history, not as an ending.

**Where.** `successors.successor_from_8k12b` (`exclude_cik`), `pipeline._find_successors` (a same-CIK branch),
`added_securities.AddedSuccessor`, `FigiResolver` (same composite), `end_of_era.resolve` branch 2; the finder's anchor (GTES anchored
on the Form 15, 2026-07-30, instead of the earlier Form 25-NSE, 2026-07-20).

**Guard.** No bankruptcy in the window: CCO is flagged `bankruptcy_before_merger`, so the 1.03 check must be explicit.
A redomiciliation (GTES English to Bermuda scheme) is a continuation only at 1:1.

**Cases (4).**
- holdco_not_linked (2): BBG000J453J8_2019-05-12 CCO (CUSIP 18453H106, same CIK 1334978); CIK733269-COMMON_2018-09-30 ACXM (RAMP).
- successor_not_in_run (2): BBG000C4MWH4_2023-07-05 BGCP (BGC Group Class A, CUSIP 088929104, ticker BGC, 8-K12B under CIK 1094831,
  effective 2023-06-30); BBG00JM9V731_2026-07-30 GTES (New Gates, same CIK 1718512).

**Effect.** Ending removed or a continuation; ticker_history runs on; `resolved_from_continued_filings`, `successor_unknown`,
`no_evidence_default`, `unknown_exit_kind`, `issuer_from_todays_ticker_map` go.

**Risks.** The same-composite assumption is unchecked in every report (CCO, GTES, BGCP); the Form 15 vs Form 25 anchor is a separate
finder defect.

**Spec.** Decision 9. Open: for a same-FIGI successor publish no row, or an `exchange` row with successor = itself?

---

## Theme 7. Add an unobserved successor line (new CIK) and link it

**Pattern.** The 1:1 holdco successor is a different issuer whose line the run never observed, so `successor_in_run` finds nothing and
the full-text search either misses it or the line has no FIGI/sighting. Result: `successor_unknown`, 304/`unknown`, or a merger at assumed
par (ROVI: TiVo Corp, no price date). Reasons: `continued_filings_rule`, `resolved_from_continued_filings`, `no_evidence_default`,
`assumed_par_after_failed_gate`.

**Rule.** When a successor registration (8-K12B/12G3, or a 5.01 with a 1:1 conversion) names a new registrant, add its line as an
`AddedSuccessor` (CUSIP from fails rows under the new registrant's ticker, FIGI by CUSIP through OpenFIGI, ticker_history from the day
after the last trade) and link it as in theme 5. The machinery exists (`successor_from_8k12b` + `found.added`); the gaps are that it runs
only where the full-text search hits, not for a 5.01-only merger row, and not from the successor's own filing list
(`own_continuation_filing` is used only by `_handoffs`).

**Where.** `pipeline._find_successors`, `successors.successor_from_8k12b`, `added_securities.AddedSuccessor`, `acquirers.find_acquirer`.

**Guard.** One for one, same holders, no cash for the old shares (decision 9); the new line must show in fails rows.

**Cases (4).**
- holdco_not_linked (2): BBG000BJ9D07_2016-09-08 ROVI (TiVo Corp); BBG000BQHGR6_2026-09-28 OKE (new-CUSIP ONEOK line; confirm FIGI).
- successor_not_in_run (2): BBG000CNZC55_2020-07-11 ODP (ODP Corp, CUSIP 88337F105; last trade 2020-06-30 needs an exchange print);
  BBG001BP9474_2015-02-27 EGL (New Engility CUSIP 29286C107; skeptic REFUTED the "extend the old security's EGL ticker_history" claim:
  a continuation does not extend the old line; only the missing successor line stands).

**Effect.** merger/exchange row -> `exchange` continuation with a named successor; the added security appears in securities.csv and
security_history; `assumed_par_after_failed_gate`, `no_evidence_default`, `unknown_exit_kind`, `continued_filings_rule` go.

**Risks.** An added security with no FIGI becomes a placeholder; a wrong CUSIP pick; start date of the added line (the not_before clamp).

**Spec question.** EGL: the $11.434 special dividend. If it is consideration for the old shares the case is a merger (cash 11.434 plus
1 new share); if the successor pays it afterwards (the BHI ruling) it is a continuation. Needs the "role in the transaction" test applied.

---

## Spec question: one-to-many reclassification (no rule yet)

**Pattern.** One class is reclassified into several new securities (Liberty Media 2016). The handoff stage pairs the old ticker with the one
new line that inherited it (`continuation_by_timing_only`, `handoff_continuation`) and ignores the other legs.

**Question.** Is a one-to-many reclassification a continuation to the ticker heir, a merger with a multi-leg stock basket (the contract
holds one `stock_ratio` and one `price_ticker`), or an `exchange` with several successors? Decision 9 ("same claim, one for one") does not
settle it. No library rule until ruled. Independent of the answer: last trade 2016-04-15 (not 04-18); clip the old line there; the new
LMCA/LMCK begin 2016-04-18.

**Cases (2, both upheld).** BBG003P9ZSL3_2016-04-28 LMCA (other:one_to_many_reclassification); BBG005SW6TK5_2016-04-28 LMCK
(other:tracking_stock_reclassification_basket).

---

## No library change

None. No report says the library is right (QRTEA is library_wrong=False, but its fix is theme 2); none is a truth-file or diagnosis issue.

## Does not fit

- BBG002B67HB2_2025-08-01 UNIT (holdco_not_linked; skeptic REFUTED exit_kind, value_rule and ticker_history): a non-1:1 merger (ratio 0.6029,
  taxable merger consideration, Windstream holders get about 35.42% plus preferred and warrants), so the merger row stands and it is NOT a
  continuation. The real gap is the missing price_ticker (UNIT, the new line, CIK 2020795, CUSIP 912932100, a different security that took
  the ticker) and price_date (2025-08-04): a stock-leg pricing fix (add the acquirer line and price on it), not a link rule.

---

## Count

Theme 1: 13; theme 2: 5; theme 3: 6; theme 4: 4; theme 5: 9; theme 6: 4; theme 7: 4; spec question: 2; does not fit: 1; no library change: 0.
13 + 5 + 6 + 4 + 9 + 4 + 4 + 2 + 1 = 48.

By source group: rename_not_followed 23 = T1 12 + T2 5 + T3 6. holdco_not_linked 15 = T4 2 (CMCSK, DISCK) + T5 8 (BHI, MYL, SBGI, HHC, LLYVA,
LLYVK, WAG, DTV) + T6 2 (CCO, ACXM) + T7 2 (ROVI, OKE) + UNIT 1. successor_not_in_run 6 = T1 1 (LMCA 2013) + T5 1 (ESV) + T6 2 (BGCP, GTES)
+ T7 2 (ODP, EGL). reclassification_not_linked 4 = T4 2 (CWENA, HUB-B) + spec 2 (LMCA 2016, LMCK). 23 + 15 + 6 + 4 = 48.

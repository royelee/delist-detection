# Fix themes E: wrong exit kind, reverse split, Form 25 matching, identity (32 cases)

Code locations come from grepping src/delist_detection/ (line numbers approximate). Spec decision numbers refer to .claude/skills/diagnose-delisting/reference.md; I did not re-read each decision's text, so the "Decisions" lines name the area touched and flag what needs a ruling.

## Theme 1. A same-issuer CUSIP switch at a split is not an ending (7)
Pattern: the old CUSIP's fails rows stop on the split date and the new CUSIP is not attached to the security. With no Form 25 the finder falls to `continued_filings_rule` (CRSP 304 / exchange_transfer, or 570 when an 8-K 3.01 deficiency is in the window; flags `no_form25`, `delist_date_approx`, `last_trade_date_unconfirmed`, `successor_unknown`). QGEN is the variant with a Form 25-NSE: no merger/distress evidence gives `no_evidence_default`/unknown/assumed par, though the ticker kept trading on a new CUSIP. MDR is the same switch plus an acquirer's 2.01 (shares the mechanism of Theme 2).
Rule: a CUSIP switch is a continuation of the same security, not an ending, when (a) the same ticker keeps trading in the fails rows right after the old CUSIP's last row, (b) the issuer CIK and the description/name match, and (c) the switch is dated by an 8-K 5.03/3.03 reverse/forward split notice or the fails rows show the new CUSIP under the same symbol within days. Attach the new CUSIP to the security (cusip_history; ticker_history keeps running) and drop the ending; any later real ending is then dated from the line's real last sighting or Form 25. For QGEN the same test rules out a Form 25 delisting: a Form 25 followed by continued trading under the same ticker, issuer and listing is not an ending.
Where: `security_master.candidate_cusips`/`era_cusips` and `history.backfill_cusips` (the new CUSIP is never attached); the "security ended / continued" test in `delistings.DelistingFinder.find` (`continued`, passed as `trading_after`); the continued-filings rule in `classifier.py` and `end_of_era.resolve` branch 6; `pipeline._ends_the_security`/`_continues_after` already has a 20-rows/60-days continued-trading test, but it is skipped for unconfirmed no-Form-25 guesses, which is exactly these cases.
Guard: the new CUSIP's rows must appear under the same symbol with a matching issuer description within a few trading days of the old CUSIP's last row. Must NOT change: a CUSIP switch after a rename plus a successor registration (8-K12B; `handoffs.cusip_switch` handles that, a real continuation to another security) and a ticker takeover by a different issuer (`handoff_takeover`). The test separating them is issuer CIK.
Cases: BBG000DZCFX4_2020-06-02 LPI; BBG000GTYWL7_2026-01-18 QGEN; BBG00WYYC600_2017-11-09 WLL (report asks whether the FIGI should join BBG000PX3XC0); CIK1808220-CLASS-A_2022-11-17 GOCO; CIK708819-COMMON_2018-05-08 MDR; CIK716006-COMMON_2010-10-04 YRCW; CIK910073-COMMON_2024-07-12 NYCB. All skeptic upheld; cause group reverse_split_read_as_ending.
Effect: the uncertain ending row disappears (reasons `unknown_exit_kind`, `continued_filings_*`, last-trade unconfirmed, `successor_unknown` go with it); cusip_history gains the new CUSIP; security_history keeps running. For WLL, if two sec_ids are kept, a continuation row with last trade the day before the switch.
Risks: a fails-only signal could hide a real delisting followed by OTC trading on a new CUSIP under the same symbol. Mitigate by requiring old and new CUSIP rows to abut within days and by not applying when a merger/distress Form 25 exists (QGEN is a voluntary 25-NSE with continued NYSE trading; check `listing_status` that the class is still listed). Several have a later true ending the run must still find (YRCW 15-12G 2012, MDR 2020 bankruptcy, NYCB to FLG).
Decisions: needs a ruling that a reverse-split CUSIP change keeps one sec_id (reports assume it); touches the seed/security/ending identity invariants.

## Theme 2. The end-of-era resolver reads the issuer's own 2.01/5.01 as being acquired (3)
Pattern: `end_of_era.resolve` branches (3)/(4) (5.01 change in control; 2.01 completed acquisition with DEFM14A/Form 25/425) take any such filing as "the issuer was acquired"; the classifier returns merger; the LLM reads the counterparty's exchange ratio as the issuer's terms (`terms_gate_failed:fail_sanity` / `no_last_close`); the row is merger with assumed par (`merger_at_par`, `last_trade_date_conflict`).
Rule: before taking branch (3)/(4), decide the issuer's role. The filing's text ("the Company acquired", "distributing to its stockholders", "the Company is the surviving legal entity") and the form (S-4 filed by the issuer = acquirer; DEFM14A where the issuer is the solicited target; SC TO-T bidder) say acquirer, spin-off distributor or reverse-merger survivor; then no merger ending. A spin-off 2.01 is not consideration; a rename plus CUSIP switch is a continuation (Theme 1). A reverse merger where holders keep their shares is not a merger exit; fall to the 3.01/25-NSE rationale (listing standards -> dropped/guidelines, otc_print).
Where: `end_of_era.signals`/`resolve` (add an issuer-role signal), `classifier._classify_items` Item 2.01/5.01 mapping, the prompt and gate in `llm_merger_extractor` (reject a ratio quoted for the counterparty's holders).
Guard: apply only when the text names the issuer as acquirer/distributor/survivor. A 2.01 where the issuer's shares are exchanged or cashed out must stay a merger; a target's successor 2.01 filed after closing under the same CIK must stay a merger.
Cases: CIK314808-CLASS-A_2019-04-11 ESV (acquirer of Rowan, renamed VAL; other:acquirer_read_as_target); CIK1308161-CLASS-A_2013-06-28 NCRA (News Corp spin-off 2.01 read as acquisition; also a duplicate placeholder, see Theme 10; wrong_exit_kind); CIK38079-COMMON_2015-01-25 FST (reverse merger / asset-sale 2.01 plus DEFM14A over a 3.01 and 25-NSE; wrong_exit_kind). All upheld.
Effect: merger ending removed (ESV, NCRA) or reclassified to dropped/guidelines with `otc_print` (FST: `unknown_exit_kind`, `merger_at_par`, `last_trade_date_conflict` go).
Risks: text heuristics; keep the test to positive acquirer-evidence so merger recall does not fall.
Decisions: decision 11 (OTC move is the ending; FST's 520 moved_otc vs guidelines wording needs a ruling).

## Theme 3. A Form 25 for rights only, or a different class, is matched to the common (2)
Pattern: `form25.match_security` matches by class letter, or by class text "Common Shares; Preferred Share Purchase Rights" although the notice relates solely to the Rights (BMET: filing + 10 days gives the date), or a class naming another tracking-stock group (Liberty Capital) is matched to the observed Series A line (flags `member_name_mismatch`, `resolved_by_cik_map`), then end-of-era reads a 2.01 as a merger.
Rule: (1) a Form 25 whose class text or notice states it relates solely to rights, or where the Form 15/10-K shows the common continues, is not matched to the common; take the later 25-NSE. (2) Class letter alone is not enough: a class naming a tracking-stock group or series must share that name with the observed name/CUSIP description, else no match.
Where: `form25.class_kind` (rights branch near line 150: classify a rights-only notice as rights, not common), `form25.match_security`, `listing_status.withdrawal_kind` as the continues-after check, `delistings.DelistingFinder` grouping (the real 2007-09-25 25-NSE).
Guard: reject only on explicit rights-only or different-group evidence. A combined "Common; Rights" Form 25 that removes both (a merger) must still match; plain "Common Stock" matches are unchanged.
Cases: CIK351346-COMMON_2006-12-28 BMET (other:rights_only_form25_matched_to_common); CIK1355096-SERIES-A_2011-10-03 (Liberty; ticker blank; other:form25_class_matched_wrong_tracking_stock). Both upheld; group form25_matching.
Effect: BMET ending moves to 2007-09-25, merger cash 46.00 (the 570 reading and the wrong ticker_history end go); the Liberty row is deleted.
Risks: the Liberty QRTEA/Series A placeholder is an identity problem (Theme 10).
Decisions: none beyond the rule that a delisting is a Form 25 removal of the security.

## Theme 4. A real Form 25 exists but the finder reports `no_form25` (5)
Pattern: the issuer's 25-NSE is not matched, not grouped or not seen (filed before the first sighting, class text "Common Stock (New)", or filed under a successor-named CIK), so the finder falls to the bankruptcy 8-K 1.03 (CRSP 470, unconfirmed last trade, flags `no_form25`, `last_trade_date_unconfirmed`) or the continued-filings rule. For RHDC/IDARQ/LKSD the actual miss is unconfirmed in the reports.
Rule: (a) match a Form 25 to a security when the issuer CIK is right and the class kind agrees, ignoring label noise ("(New)"); (b) search a window that starts before the first sighting: an issuer's earlier Form 25 for the same class ends a security first seen later, later sightings become `after_delisting`; (c) when a 25-NSE and a 3.01/EX-99.25 deficiency precede a later 1.03, the exchange delisting is the ending (dropped/guidelines, otc_print) and the bankruptcy is not (decision 11); (d) also search the filings of the CIK that holds the security's CUSIP/ticker, not only `library_cik` (SPB: the 25-NSE is under CIK 1487730 "Spectrum Brands Legacy"; library_cik is the successor's 109177 from the current ticker map).
Where: `delistings.DelistingFinder.find` (Form 25 listing, window, `SAME_EVENT_DAYS` grouping), `form25.match_security`/`class_kind`, `ticker_resolver` (issuer from today's map), the bankruptcy fallback order in `classifier.py`.
Guard: do not take a Form 25 older than the first sighting unless class kind matches and no sibling security of the issuer shares the class (`SecurityContext.sibling_spans`); do not take a secondary-listing withdrawal (`listing_status.withdrawal_kind`).
Cases: BBG000BRF6B5_2009-05-29 RHDC (skeptic refuted field value_rule: otc_print is right and only price_ticker/price_date and the ending date are wrong; the finder-miss claim is not refuted); BBG000PSSG77_2009-03-31 IDARQ; BBG009R0CVG1_2020-04-13 LKSD; CIK898660-COMMON_2009-06-08 STN (form25_before_first_sighting); BBG000P4BQM9_2018-07-16 SPB (wrong_exit_kind, with a parent absorbing a subsidiary at 1:1 stock, see Decisions). Groups: form25_matching x4, wrong_exit_kind x1.
Effect: ending moves to the Form 25 date; exit kind from bankruptcy/continued-filings to dropped (`guidelines`/`price`) or merger (STN cash 90.00; SPB stock 1.0, price_sec_id BBG000DS5588); `no_form25`, `delist_date_approx`, `handoff_continuation`, `continuation_by_timing_only` go.
Risks: root cause unproven for RHDC/IDARQ/LKSD; probe the finder on cached filings before coding. Choice between bankruptcy and guidelines for a delisting followed by Chapter 11 within months should follow the 3.01 text.
Decisions: decision 11 (OTC move is the ending vs last real ending); SPB needs a ruling: merger or continuation for a parent absorbing its subsidiary at 1:1.

## Theme 5. A later SEC revocation outranks the real delisting reason (3)
Pattern: the "SEC REVOKED registration" branch (`classifier.py` ~652, form code `REVOKED` in the submissions JSON) fires on a revocation filed 1.5 to 4 years after the delisting (2010, 2011, 2012) and sets 573/`sec_order`, though the delisting was an exchange removal (12d2-2(b)) with an 8-K 3.01 deficiency or an 8-K 1.03 bankruptcy.
Rule: a REVOKED row is the ending only when no Form 25/exchange removal and no 1.03/3.01 evidence precede it; otherwise the exchange/bankruptcy evidence wins. With a bankruptcy 1.03 (including a bank receivership) in the window the drop reason is `bankruptcy` (574); a 3.01 price deficiency gives `price` (550). Date the last trade from the 3.01 text ("suspended prior to market opening on D" = prior session, `last_trade._OPEN`), not the last sighting or the notice date.
Where: `classifier.py` (revocation branch ordering), `last_trade.eightk_last_trade`/`decide_last_trade`, `exit_kind.ending_fields` (drop_reason).
Guard: apply when a Form 25 for the class exists and the revocation is later than its effective date; a revocation-only ending (no Form 25, no distress evidence) stays 573.
Cases: BBG000BBG3P1_2009-01-25 TMA (wrong_exit_kind, upheld; report did not trace which rule attached the 2012 text); BBG000BF2JS9_2009-09-18 CNB (upheld); BBG000BLY636_2008-08-17 IMB (skeptic refuted, the refuted field is not named in the header; do not build the 2008-07-11 last trade or first-print claims on it until the field is known; the drop_reason claim is shared with CNB/TMA).
Effect: drop_reason `sec_order`/573 -> `bankruptcy`/574 or `price`; `last_trade_date_unconfirmed` removed where the 3.01 text dates it.
Risks: IMB's refutation unresolved; TMA's revocation text may come from another filer on the same CIK.
Decisions: decision 11; the drop-reason vocabulary (bankruptcy vs sec_order).

## Theme 6. A foreign-filer or press-release-only deal has no 8-K items, so it ends `unknown` (3)
Pattern: no 8-K 2.01/5.01 (6-K filer, or a bare 7.01), so the classifier falls to `no_evidence_default` (`unknown_exit_kind`, assumed par, `no_last_close`/`no_last_trade_date`) though the Form 25 EX-99.25 notice or the 7.01/6-K text states the merger and terms.
Rule: when the Form 25's notice text states merger wording ("merger ... became effective", "converted ... in cash", "receive ... shares"), or the issuer has no 8-Ks (6-K/20-F filer) and its 6-K/7.01 says so, treat as merger evidence and extract terms from that text (cash, stock ratio, acquirer). A CVR stays outside the payout rule.
Where: `classifier._classify_items` (notice-text signal before `no_evidence_default`), `form25.py` (notice text; EX-99.25 is already read by `last_trade`), `payout_extractor`/`llm_merger_extractor`/`filing_selection` (accept 6-K and 7.01), `end_of_era.signals`.
Guard: the notice must say the issuer's securities were converted or cancelled; a bare transfer text stays a transfer; an issuer-as-acquirer 7.01 must not qualify (Theme 2 role test).
Cases: BBG000BDN878_2019-03-04 TAHO (6-K filer, 0.67 cash + 0.1929 PAAS); BBG0060HN0R3_2016-03-04 KING (6-K filer, cash scheme; contract delist_date is the Form 15 date 2016-03-04 vs 25-NSE effective 2016-02-23, a date ruling is needed); BBG00LT2PDY4_2021-08-05 BPYU (only a 7.01; multi-leg terms, preferred-unit pricing id unconfirmed). All wrong_exit_kind, upheld.
Effect: `unknown` -> merger; `no_evidence_default`, `no_last_close` replaced by terms (`value_rule` cash/cash_plus_stock); BPYU last trade 2021-07-26.
Risks: LLM extraction on 6-K/press releases is not calibrated (`eval_merger_extractor`); election packages depend on proration (TAHO).
Decisions: payout rule on election/proration and CVRs; `cash_currency` is always blank today while the reports want USD.

## Theme 7. Same-issuer holdco combinations with a ratio or election are read as continuations (3)
Pattern: an 8-K12B successor registration (CHTR), a ticker handoff by timing (`handoff_continuation`, `continuation_by_timing_only`, MTCH), or the continued-filings rule (DVMT, CRSP 304 "successor by same issuer") treats the event as a transfer/continuation with no value and ignores the exchange ratio or election.
Rule: where the successor registration or handoff carries an exchange ratio other than 1:1, or a cash/stock election, classify as a stock/cash_plus_stock merger priced on the successor line, not a transfer; a 1:1 same-name successor stays a continuation. A same-issuer election deal must not be reclassified by the continued-filings rule when the 8-K says shares were exchanged or cashed.
Where: `end_of_era.resolve` branch (2) (read the ratio from the 8-K12B), `handoffs.decide_handoff`/`apply_handoffs` (`continuation_by_timing_only` needs a terms check; test the Form 25 first), the continued-filings rule in `classifier.py`, `payout_rule.merger_inputs`.
Guard: ratio read from the filing, not assumed. MTCH needs IAC's Form 25 (CIK 891103) taken. Must NOT change a true continuation (exchange_transfer with successor itself, ratio 1).
Cases: BBG000PYZSR8_2016-05-18 CHTR (ratio 0.9042; operator ruling needed: if a technical parent merger ratio is a continuation, the library is right and only the last trade date remains); BBG00B6WH9G3_2020-07-10 MTCH (stock 1.0337 default); BBG00DJ2LJF5_2019-01-07 DVMT (cash+stock election, DELL price security). All wrong_exit_kind, upheld.
Effect: exit kind continuation/transfer -> merger; `continuation_by_timing_only`, `handoff_continuation`, `no_form25`, `last_trade_date_unconfirmed` go; value fields gain `stock_ratio`, `price_sec_id`.
Risks: CHTR ruling pending; election packages are aggregate, not per holder.
Decisions: continuation vs merger when ratio != 1 (CHTR); payout rule election handling.

## Theme 8. A Form 25 with a same-day 8-A12B for the same class is an exchange transfer (1)
Pattern: a voluntary 12d2-2(c) Form 25 with a paired new-exchange 8-A12B is not read as a transfer; `no_evidence_default`, `no_last_trade_date`, `no_last_close`.
Rule: Form 25 plus same-day 8-A12B by the same issuer and class -> exchange_transfer with successor itself (no clip of ticker_history, DLRET 0).
Where: `classifier._classify_items`/exchange-transfer detection; `delistings.DelistingFinder` (8-A12B in the Form 25 window); `listing_status`.
Guard: same issuer and same class on the 8-A12B; an 8-A12B for another class does not qualify; secondary-listing withdrawals keep their rule.
Cases: BBG005CPNTQ2_2026-09-18 KHC (form25_with_same_day_8A12B_not_read_as_transfer; upheld; group form25_matching).
Effect: `unknown` -> exchange transfer, no clip; `no_evidence_default` goes and the no_last_close/no_last_trade_date flags grade info on a transfer.
Risks: small; last Nasdaq session still unconfirmed.
Decisions: none (an existing transfer rule).

## Theme 9. The name tier picks the issuer that held the name, not the company the ticker belonged to (2)
Pattern: the observed name resolves through `ticker_resolver._name_search`/the cik-lookup index to a CIK that holds that name in a different period (`library_cik` source `name_search`). ABBI: the name is the former name of CIK 1141399 (APP, after a 2007 spin-off); the right issuer is CIK 1409012, ticker ABII. ERA: "Bristow Group" is a name CIK 73887 held in 2013; the issuer is Era Group CIK 1525221 (later Bristow). The wrong issuer gets no matching Form 25, so the continued-filings rule (304) or the wrong company's Form 25 ends it (`member_name_mismatch`, `no_last_trade_date`, `after_unconfirmed_delisting`).
Rule: prefer the issuer whose EDGAR name at the observation date matches the observed name AND that traded the ticker then (company_tickers history, filing cover, or fails rows by ticker). A CIK's former name counts only for the dates it carried that name (submissions `formerNames` from/to). When the exact-name candidate and the ticker-era candidate disagree, the ticker-era candidate wins, or the row gets a review flag rather than a silent pick.
Where: `ticker_resolver._name_search`/`_index_candidates`/`_one_filer`, `cik_lookup.CikNameIndex`, `infer_issuers` guard G, `security_master.issuers_by_era`.
Guard: only when two candidates hold the name in different periods or fails/filing evidence confirms the ticker's era. A caller's `cik` pin always wins. Must NOT change cases where the later name is the correct issuer (a plain rename).
Cases: CIK1141399-COMMON_2008-09-20 ABBI (identity_wrong); CIK73887-COMMON_2013-06-28 ERA (identity_wrong). Both upheld.
Effect: placeholder/ending swapped for the right issuer; ABBI then gets its 2010 Celgene merger ($58.00 + 0.2617 CELG); ERA's ending disappears; `member_name_mismatch`, `no_form25`, `delist_date_approx` go.
Risks: the resolver cache (version 4) would need a version bump; ABBI also needs an ABBI->ABII alias (typo or stale ticker).
Decisions: decision 1 (ticker evidence) should be checked for name-vs-ticker-era precedence.

## Theme 10. A placeholder is never folded into the real FIGI line it duplicates (2)
Pattern: observations resolve to `CIK<cik>-<CLASS>` while a real FIGI line of the same issuer, class and CUSIP exists (SPW), or a one-day when-issued ticker gets its own placeholder because `EHAB-WI` has no FIGI. The era then ends via the continued-filings rule or end_of_era (5.01 read as merger).
Rule: (1) strip a when-issued suffix (-WI) from the ticker before FIGI/issuer resolution and fold the era into the regular-way security of the same issuer; (2) the identity guard folds a placeholder into the real FIGI line when issuer, class and CUSIP agree (a CUSIP hit needs no name check in `figi_resolution.accept`); (3) a 5.01 filed by the registrant on its own separation date is not an acquisition (Theme 2).
Where: `security_master.resolve_with_identity_guard`/`guarded_eras`/`FigiResolver.resolve_many`, `figi_resolution.us_candidates` (already drops "when issued" securityType2) and `accept`, `observations.split_eras` and `ticker_resolver.resolve` (ticker normalization), `security_master.superseded_placeholders`.
Guard: fold only when issuer, class and a fails-row CUSIP agree. Must NOT merge two same-class siblings of one issuer (existing `resolve_many` rule) or two genuinely different tracking-stock series.
Cases: CIK88205-COMMON_2015-09-28 SPW (identity_wrong; placeholder never merged into BBG000BTGCV5; SPW->SPXC rename date unconfirmed); CIK1803737-COMMON_2022-06-30 EHAB-WI (other:when_issued_ticker_read_as_ending; BBG014QJ5BV6 unconfirmed). Both upheld. The same fold also supports NCRA's duplicate placeholder (placed in Theme 2) and the Liberty QRTEA half (placed in Theme 3).
Effect: the placeholder security and its uncertain ending disappear; `no_form25`, `delist_date_approx`, `successor_unknown`, `ticker_overlap:SPW` go.
Risks: folding changes sec_ids between runs (`contract/id_changes.csv` will list it).
Decisions: id_changes publication (placeholder -> FIGI) already covers the change.

## Theme 11. One sec_id spans a pre-bankruptcy stock and the re-listed new equity under a recycled ticker (1)
Pattern: BBG00Z6DX554 (CHK/EXE) merges the old stock (CUSIP 165167107, to 2021-02-11) and the new stock (CUSIP 165167735 from 2021-02-12), so ticker_history runs 2007-2024 and the OTC print rule is priced under `CHK` from 2020-06-29 (new stock's ticker, non-trading date). Flags `resolved_by_current_ticker_map`, `member_name_mismatch`; dlret fill is Shumway though a print exists.
Rule: split a security's CUSIP and ticker ranges where the same ticker is reused after a bankruptcy delisting and a new CUSIP appears after a gap (plan effective date); the old stock's OTC price symbol is the issuer's own OTC symbol (CHKAQ); the new stock is its own security with its own FIGI/start.
Where: `security_master.build_securities` (era merge by shared `sec_id`), `history.ticker_range_review`, `observations.split_eras`, `payout_rule.value_fields`/`price_requests` (price_ticker for otc_print), `pipeline._ends_the_security`.
Guard: split only after a confirmed delisting that ends the security and a new CUSIP after a gap with a Chapter 11 plan; must NOT split a reverse-split switch (Theme 1) or an exchange transfer.
Cases: BBG00Z6DX554_2020-07-30 EXE (identity_wrong; upheld; which composite FIGI the old stock holds is open).
Effect: price_ticker CHKAQ, price_date 2020-06-30; ticker_history ends 2020-06-26; `member_name_mismatch`, `resolved_by_current_ticker_map` go.
Risks: OpenFIGI may issue one composite for both, leaving two securities on one FIGI.
Decisions: decision 11; a ruling on a FIGI shared across pre/post-bankruptcy equity.

## No library change
None. Every case was upheld by the skeptic or only partly refuted (RHDC: value_rule refuted, finder miss stands, Theme 4; IMB: refuted field unnamed, flagged in Theme 5). Cases with open operator rulings (CHTR, SPB, KING date) are noted in their themes.

## Does not fit
None.

## Count
Theme 1: 7; Theme 2: 3; Theme 3: 2; Theme 4: 5; Theme 5: 3; Theme 6: 3; Theme 7: 3; Theme 8: 1; Theme 9: 2; Theme 10: 2; Theme 11: 1. Total 7+3+2+5+3+3+3+1+2+2+1 = 32.
Source files: wrong_exit_kind 13 (TMA, TAHO, CNB, IMB, SPB, CHTR, KING, MTCH, DVMT, BPYU, NCRA, ESV, FST) + reverse_split 7 + form25_matching 7 (RHDC, IDARQ, KHC, LKSD, Liberty, BMET, STN) + identity_wrong 5 (EXE, ABBI, EHAB-WI, ERA, SPW) = 32.

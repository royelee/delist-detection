# C. Terms and prices: fix themes (52 cases)

Code map (grepped): `payout_gate.reconcile` / `gate_payouts` (pass 1: regex + LLM election; pass 2: stock terms, drop reasons `no_acq_ticker`, `no_acq_price`, `no_last_close`, `fail_sanity`); `pipeline._gate`, `_add_acquirers`, `_merger_payouts`; `payout_rule._merger` (publishes `price_sec_id` = `inputs.acquirer_sec_id or row["acquirer_sec_id"]`, `price_ticker` = the LLM ticker, `price_date` = day after last trade; always `cash_currency=""`), `payout_rule._otc` (price_sec_id = own sec_id, price_ticker = `row["ticker"]`); `acquirers.find_acquirer` / `acquirer_cik`; `llm_merger_extractor` (terms schema has no currency, no election package, no class); `price_requests`.

Mechanism behind the CAL/RTN fix as I read it: `_add_acquirers` runs only for terms that passed the gate, and the gate prices the acquirer by the LLM's ticker. So a renamed acquirer or a missing ticker kills the gate (`no_acq_price` / `no_acq_ticker` / `fail_sanity`) and no acquirer lookup ever runs. Fix = acquirer lookup before the gate, by CIK, line chosen by CUSIP, priced by CUSIP.

---

## 1. Acquirer found by CIK and line, priced by CUSIP (the CAL/RTN fix) — 14 cases

**Pattern.** The stock leg is right (ratio, rule) but the acquirer is named by a ticker that is stale at the closing (UAUA to UAL, UTX to RTX, RRI to GEN, SPF to CAA, CHFC to TCF, IVGN renamed, old EVHC), empty (`terms_gate_failed:no_acq_ticker`), or ambiguous between share classes/lines. The gate fails (`no_acq_price` or `fail_sanity`) so `merger_at_par` / `assumed_par_after_failed_gate`; `price_sec_id` blank or wrong, `price_ticker` stale.

**Rule.**
1. Link an issuer's lines across a ticker+CUSIP change (CAL step 1) only where no link exists. Not needed for RTN/WR/LSXMA (the run already holds the lines); needed for CAL (placeholder UAUA) and MIR (the GenOn line must be added from fails rows under CUSIP 37244E107).
2. Run the acquirer lookup for EVERY published stock leg, including terms that failed or never reached the gate: resolve (LLM acquirer ticker, else the LLM acquirer name, else the 8-K12B/successor-registrant filer) to a CIK via `ticker_resolver.resolve(..., name=)`; accept when the name matches an EDGAR current/former name and the CIK is not the target's own; take that issuer's line whose CUSIP begins at the closing (not the line `ticker_history` lists on the price date).
3. Publish `price_sec_id` and `price_ticker` from that security's CUSIP-bearing sightings (the symbol on that CUSIP's fails rows at the price date), never from `ticker_history`, which can start days late. The gate prices that CUSIP's close on last-trade-day+1 from the NEXT day's fails row (rows are dated D, priced at D-1's close), skipping placeholder rows ($0.01, "." and SIRIZZZZ-style symbols) and old-CUSIP closes that repeat a stale pre-switch price.
4. When two lines of one CIK exist on the price date (SIRI), pick the one whose first sighting is on/after the switch. When the CIK holds several share classes (LBRDA/LBRDK), pick by the class the filing names (class kept in the extractor output, matched to the class letter).
5. When the acquirer has no line in the run (WR/GXP's Evergy, GRUB's JET ADS), `_add_acquirers`/`AddedAcquirer` adds it from the CUSIP found in fails rows. If none (OTC ADS with no fails row) keep price_sec_id blank and the stock rule unpriced rather than assumed par (needs ruling, below).

**Where.** `pipeline._add_acquirers` (reorder before `_gate`, drop the "passed gate only" filter), `pipeline._gate`, `acquirers.find_acquirer`/`acquirer_cik`, `ftd` close lookup (`close_known_on`/`close_after`: next-day row, placeholder skip, CUSIP-first), `payout_gate.gate_payouts` (acquirer price by sec_id/CUSIP, not ticker), `payout_rule._merger` (publish price_sec_id/price_ticker), `security_master`/`history` for step 1 (line linking; also makes ticker_history start at the switch day), `llm_merger_extractor` (return acquirer name and share class).

**Guard.** Step 1 link: same CIK and class; old line stops and new starts within days; a rename at the switch or a filing stating the same stock moved; no 8-K 1.03 in the window (UAL's 2006 emergence must NOT link). Step 2: acquirer CIK != target CIK. Tolerance unchanged (15%); a leg that still fails after correct pricing stays assumed par (the gate is doing its job). Do not change rows whose acquirer ticker already resolves and passes.

**Cases.**
- terms_misread: RTN (UTX to RTX, no link needed; CUSIP 75513E101 priced $49.93 via the next-day row), MIR (RRI to GEN; the line must be added; skip the $0.01 row), RYL (SPF to CAA, 1-for-5 reverse split: price by the new line BBG000BTFDR9; do not compare pre-split SPF prices), TCF (CHFC to TCF; acquirer FIGI BBG000BFK8Y6), GLIBA (LBRDA vs Series C LBRDK: class selection), AMSG (the acquirer is the surviving AmSurg renamed EVHC; EVHC on 2016-12-02 is old Envision. The skeptic REFUTED "ratio should be 0.334", so do NOT change stock_ratio; the fix is only the price security by CUSIP. Hypothesis: verify by rerun).
- terms_not_extracted: WR (no_acq_ticker; Evergy CIK 1711269, BBG00H433CR2, EVRG; the regex $25 is irrelevant once the stock leg passes), GXP (same Evergy, EVRG, ratio 0.5981), LSXMA (New Sirius BBG01KJQM3Y8 by CUSIP, SIRI), LEG (SGI acquirer ticker; sec_id check), GCI (acquirer NEWM renamed GCI on 2019-11-20, takes the target's ticker; price on that line, `ticker_successor_sec_id` if the run adds it).
- price_security_wrong: CAL (the worked case), GRUB (JET ADS OTC, acquirer security not found; library_wrong=False).
- currency_missing: ABI (IVGN retired, acquirer renamed at closing; its blank currency follows theme 7's mechanism).

**Effect.** `price_sec_id`, `price_ticker` published and correct; `terms_gate` failed to passed; `dlret_fill`/`merger_at_par` and uncertain reason `assumed_par_after_failed_gate` clear. `contract/price_requests.csv` `received_close` rows get the right security. Independent reasons stay: `resolved_from_continued_filings` (CAL, WR, LSXMA), `security_uncertain`. Last-trade dates (LEG, GCI, CAL) unchanged here.

**Risks.** Wrong CIK for a common name (guard: EDGAR name match and not-target rule); two lines of one CIK both beginning near the closing (spin-offs the same day: RTN's UTC spin-offs); a GRUB-type OTC ADS has no fails rows so cannot be priced; line linking moves ticker_history and the `ended_without_delisting`/`form25_unmatched` rows (CAL placeholder), which is scorecard-visible and may move floors.

**Decisions.** Touches decision 9 (continuation: the link makes UAUA an exchange continuation) and decision 4 (assumed par only after a PASSED gate; this fix makes more gates pass, it does not relax it). Needs a ruling: when the acquirer's price is unobtainable (GRUB), publish the stock rule with a blank price (preferred) vs assumed par.

---

## 2. OTC print priced under the security's own OTC symbol, CUSIP-aware — 5 cases

**Pattern.** `otc_print` endings publish `price_ticker = row["ticker"]` (the exchange symbol). After delisting that symbol is dead or reused (HTZ; GTX relisted 2021; GPOR reused after 2021-05; SPNV is another company's SPAC ticker) and the OTC print sits under a Q-suffix or other symbol. The fill is Shumway -0.30/-0.55 until priced.

**Rule.** For `otc_print`, publish `price_ticker` = the symbol of the security's OWN CUSIP in fails rows dated after the last trade (symbol differs from the exchange ticker; Q/Y/F suffix), else the symbol the 8-K 3.01 text names ("will trade under HTZGQ"), else blank rather than an exchange symbol that is not the security's own after the last trade (reuse). `price_sec_id` = own sec_id (already). Clip or split ticker_history at the ending for a reused ticker (GTX new stock on a new CUSIP; SPNV fails-derived history says SPNV where it was SPN).

**Where.** `payout_rule._otc` (needs the ftd index or an `otc_symbol` column on the delistings row); `ftd.FtdIndex.by_cusip` (post-ending symbols); the 8-K 3.01 reader in `last_trade`; `history.ticker_sightings` for the SPNV label error; `price_requests` (the `otc_print` request ticker).

**Guard.** Only `otc_print` endings (liquidation/compliance_failure, not a continuation). Do not touch rows where the exchange symbol is the OTC symbol. A new-CUSIP relisting (GTX 2021, GPOR reused ticker) must not be read as the old security's print: match by the security's own CUSIP only (same trap as WOLF in theme 3).

**Cases.** terms_misread: GPOR (GPORQ, price_date 2020-11-27), BTU (BTUUQ; keep last trade 2016-04-12; the 8-K date and MIDAS agree), SPNV (SPNX; also `last_trade_date_unconfirmed` although the 8-K/notice state 2020-09-17, and ticker_history should be SPN to 2020-09-17). price_security_wrong: HTZ (HTZGQ), GTX (GTXMQ; also decide whether the 2021 Nasdaq GTX line is the same FIGI).

**Effect.** `price_ticker` correct on 5 rows. A small adjacent fix: `issuer_from_todays_ticker_map` (GPOR, BTU, HTZ, GTX; CIK is right per the Form 25-NSE filer) can be cleared when the Form 25's filer CIK confirms the issuer. SPNV also fixes ticker_history and, if the notice date is accepted, last_trade_date. The value stays a fill until the caller prices the print.

**Risks.** OTC-symbol heuristics (Q suffix) may pick another instrument; blank is better than a wrong ticker.

**Decisions.** Decision 11 (OTC print; price_ticker = the security's own OTC symbol if known: this theme implements it); decision 12 for the SPNV last trade date.

---

## 3. Stock leg is a security other than the named acquirer; multi-leg and new-equity packages — 6 cases

**Pattern.** The consideration is (a) new shares of the SAME issuer or ticker on a new CUSIP (bankruptcy emergence WOLF; spin-and-merge CCE), (b) a spin-off or distribution share, not the acquirer's (VSTO Revelyst; MDP Holdings leg), (c) an issuer exchange offer (ARD to AMBP), or (d) two lines from one share (LGFB: LION and STRZ). The extractor reads one acquirer ticker, and ticker-keyed lookups hit the wrong line.

**Rule.** Publish one stock leg priced by sec_id/CUSIP, with these generalisations: (i) a bankruptcy ending whose old equity receives new shares gets `value_rule=stock` priced on the new CUSIP, and the old line's last close comes from the OLD CUSIP only, never the ticker, which returns the new stock (WOLF 22.10 vs 1.85); (ii) a spin-off/distribution leg is valued through the distributed security, and cash legs are summed only where the filing states the total (MDP 16.99 + 42.18 = 59.17); (iii) an issuer exchange offer with a stated ratio is a stock rule (ARD 2.5 AMBP; the $1.25 special dividend is a distribution, not consideration); (iv) a one-to-two separation (LGFB) needs a second leg: a second `price_*` triple in the contract, or a ruling to publish unknown with both legs in `value_formula`.

**Where.** `llm_merger_extractor` (prompt: legs, new-issuer shares, distributions; return a legs list), the last-close lookup in `delistings`/`dlret` (CUSIP-aware: `ftd.close_of` by CUSIP, not symbol, for a ticker with two CUSIPs), `payout_rule._merger`/`_otc` (prefer stock over otc_print when the filing states new shares), `contract.py` columns for a second leg (if ruled), `end_of_era` (LGFB and ARD reached merger without terms).

**Guard.** Only when the filing text states the new-share ratio. Not for a bankruptcy where old equity is cancelled (-1.0) or paid by an OTC print. The new CUSIP's close must never stand in as the old line's last close.

**Cases.** price_security_wrong: WOLF (stock_ratio 0.008352, price WOLF 2025-09-30, old CUSIP 977852102). terms_misread: CCE (price the New CCE line, a distinct line under the same ticker; LLM read one KO share), VSTO (price_ticker GEAR; Revelyst not in the run), MDP (cash 59.17 USD from two legs). terms_not_extracted: ARD (also last trade 2021-10-05 from the 425/SC TO-I press release; price AMBP; AMBP may not be in the run), LGFB (LION 1 + STRZ 1/15; needs two legs and added securities; the library's STRZ-like sec_id BBG000PCNTM2 is the old Liberty Starz, so do not link it).

**Effect.** `value_rule`, `stock_ratio`, `price_ticker/price_sec_id`, `terms_gate`; clears `assumed_par_after_failed_gate` and the wrong WOLF last close. ARD/LGFB/CCE/VSTO probably need `added_securities` for the priced security.

**Risks.** High: extractor changes, contract schema (two legs), and judgment on what counts as consideration. Distinct cases with one shared principle (price by the security that holders receive).

**Decisions.** Needs ruling: how a two-leg or spin-off package is published (new columns vs `value_formula` only vs unknown). The special-dividend rule in reference.md (a distribution, not consideration, unless the documents make it consideration) governs ARD/AWH-style dividends.

---

## 4. Election and proration packages — 8 cases

**Pattern.** Either/or deals (cash or stock at the holder's choice, prorated) are read two ways: both elections summed into one package (FRK 67 + 0.63 VMC; CZR 12.41 + 0.3085) or only one election (FWLT all-cash $32; BLUE closing $3 only; SLR cash only via 8K_1.01; CBSS cash 71.82 without the ADS leg; PARA the Class A $23 / 1.5333 read; RKT the cash-elector package instead of the default). Result: `terms_gate=failed`, `llm_gate_failed`, assumed par. The `deal_type=="election"` branch exists in `payout_gate.reconcile`, but the published terms still come out as one leg or the sum.

**Rule.** For an election deal publish the DEFAULT or AGGREGATE package the agreement fixes (the reference.md convention), stated as such. The extractor returns `deal_type=election` plus the default/aggregate legs (cash_per_share, stock_ratio) and keeps each election leg in a note or `value_formula`; never sum the two elections. Prefer the prorated final package when a filing states it (FWLT 16.00 + 0.8998 AMFW; RKT stock 1.0 WRK; PARA stock 1.0 PSKY with the $15 election as a note; BLUE $5.00 cash alternative with the CVR as a note). The gate then compares the package to last_close, with the acquirer priced per theme 1.

**Where.** `llm_merger_extractor` prompt and schema (`deal_type`, default/aggregate package, proration), `payout_gate.reconcile` election branch, `payout_rule.merger_inputs` (carry the chosen package), `payout_extractor`/`filing_selection` (pick the amendment/closing 8-K that states the final proration).

**Guard.** Only deals the extractor labels election; require the chosen package to pass the 15% gate against last_close. Not for cash-plus-stock deals with a fixed mix (theme 8). Where the filing does not state the aggregate (CBSS, SLR, BLUE's split), publish the default and flag, or leave unknown; do not guess a blend.

**Cases.** terms_misread: FRK (aggregate 46.90 + 0.189 VMC; last trade 2007-11-15 vs 11-16 needs an exchange source), FWLT (no last trade date, voluntary 12d2-2(c) Form 25), RKT, PARA, CZR (also `no_last_trade_date`, and ticker_history clipped at the Form 25 effective date instead of 2020-07-20; ERI sec_id check), BLUE. terms_not_extracted: CBSS (also no last trade date, pre-MIDAS), SLR (also stale post-delisting seeds, caller data).

**Effect.** `value_rule`, `cash_per_share`, `stock_ratio`, `terms_gate`; assumed par clears once the gate passes. The last-trade-date issues (FRK, FWLT, CZR, CBSS) are NOT fixed here (other fix groups).

**Risks.** The default package is a convention, not the holder's realized value; reviewers may dispute it. Proration needs the completion 8-K, and sources differ.

**Decisions.** Needs ruling: confirm "default or aggregate package" as the standing convention for election deals (reference.md states it; I did not find it as a numbered decision), and whether CVR legs are ignored (BLUE) or carried.

---

## 5. LLM reads the wrong figure for the operative consideration — 4 cases

**Pattern.** Right deal, wrong number: RAI stock_ratio 1.0 (filing 0.5260 BAT ADS); TWC "equivalent to 0.5409 Charter" vs 0.48908178 New Charter shares actually issued; BOT 0.35 from the June amendment vs the final 0.375; MIC the DEFM14A headline $41.18 (total proceeds of two asset sales) vs the $4.11 paid at closing. The gate catches three (`fail_sanity`/`llm_gate_failed`); BOT passed against a lagged close (`ftd_close_prior:2`, `acquirer_close_lagged`), so a wrong ratio was published.

**Rule.** Prefer the operative consideration of the latest completion document: choose the filing by tier (closing 8-K Item 2.01 / Form 25 notice / latest amendment) over a proxy headline or earlier 8-K; when several filings state the consideration, take the latest amendment dated before closing; prefer "shares issued per share" over "equivalent" figures; never take a proxy's "proceeds per share" headline when the closing 8-K states the cash. Re-check a gate pass that rests on a lagged close (`ftd_close_prior`/`acquirer_close_lagged`) against the next close.

**Where.** `filing_selection` (tier picker), `llm_merger_extractor` prompt (amendments, "equivalent" wording, ADS ratio), `payout_gate` (lag handling).

**Guard.** Apply the amendment rule only when an amendment predates closing; never override an explicit `--merger-terms` row.

**Cases.** terms_misread: RAI (also whether BTI is in the run), TWC (cash_currency USD; `ftd_close_prior:5`), BOT (`security_uncertain` is caller seeds), MIC (a separate issuer-in-force finding: after 2021-09-22 the issuer is CIK 1845290, the library holds 1289790).

**Effect.** `stock_ratio`/`cash_per_share` corrected; `terms_gate` passes; assumed par clears (RAI, TWC, MIC). BOT is a silent wrong-value fix (its gate passed before), so it moves a published number.

**Risks.** Prompt changes are non-deterministic and cache-keyed (`cache/llm`); each change needs `eval_merger_extractor.py` revalidation. MIC's issuer finding is outside this theme.

**Decisions.** None in the spec list; consistent with decision 4.

---

## 6. Stock leg not extracted when a cash read comes first, or the leg is a dollar value — 3 cases

**Pattern.** A lower-tier read (regex on the 8-K, or 8K_1.01 text) supplies only the cash leg, so `value_rule=cash` (AWH 23.00, CYTC 16.50) and the stock leg is never looked at; or the stock leg is a value over a VWAP, not a fixed ratio (PCYC $109 / ABBV VWAP), which the LLM cannot turn into a `stock_ratio`. Flags `terms_gate_failed:no_acq_price` / `llm_gate_failed`.

**Rule.** When the deal text mentions shares or units of an acquirer, run the LLM terms extraction regardless of the cash regex, and publish `cash_plus_stock` when both legs exist. For a dollar-denominated stock leg, add a value-rule form (dollar value over an averaging window) or keep the leg out of `stock_ratio` and put it in `value_formula` with a price request. Treat a special dividend (AWH $5.00) as a separate distribution.

**Where.** `payout_rule.merger_inputs`/`_merger` (tier order: regex vs LLM vs 8K_1.01), `pipeline._merger_payouts`, `payout_extractor` (do not stop at the first cash match), `llm_merger_extractor`, `payout_rule.VALUE_RULES`.

**Guard.** Do not let the LLM override a cash read that already passed the gate unless the text clearly shows a stock leg. `--merger-terms` stays the override.

**Cases.** terms_not_extracted: AWH (23.00 + 0.057937 FFH; also no last trade date), PCYC (152.25 + 109/ABBV VWAP; last trade 2015-05-22 unconfirmed). terms_misread: CYTC (16.50 + 0.52 HOLX, price_date 2007-10-23; last trade 2007-10-22 only if the pre-2012 fails-row rule is accepted).

**Effect.** `value_rule` becomes `cash_plus_stock`; `terms_gate` passes after theme 1 pricing; assumed par clears. PCYC needs a schema addition.

**Risks.** Over-extraction where a stock mention is incidental; the PCYC schema change.

**Decisions.** Needs ruling for PCYC: representation of a dollar-denominated stock leg. CYTC touches decision 12 (a fails-row date before 2012 is not an exchange print, so it is not published unless that rule is accepted).

---

## 7. cash_currency is always blank — 4 cases (and every cash row)

**Pattern.** `payout_rule` hard-codes `cash_currency=""` ("no source records one"); reference.md says to give the currency the filing states. Rule, terms and dates are right; the contract field is blank.

**Rule.** Add `cash_currency` to the LLM terms schema (and to the regex hit: USD when the filing says "$"/"U.S. dollars"; CAD only when it says C$/Canadian) and publish it through `payout_rule._merger`. The library carries the currency; it does not convert.

**Where.** `llm_merger_extractor` schema and `merger_inputs`, `payout_extractor` (regex currency token), `payout_rule._blank`/`_merger`/`value_fields`, `contract.py`/`store` (the column exists; schema version unchanged).

**Guard.** Blank stays when no source states it (never infer CAD vs USD from nationality). Rows without terms keep blank.

**Cases (currency only, gate passed).** currency_missing: UFS (also `resolved_from_continued_filings` although the 8-K 2.01 states the merger: a separate end-of-era fix), MDC (same label plus `member_name_mismatch`), MASI (also `issuer_from_todays_ticker_map`; CIK 937556 is right), TRI (stale seeds are caller data).

**Effect.** `cash_currency` populated on every cash/cash+stock row; this mechanism also covers the currency item on the rows in themes 1, 3, 4, 5, 6 and 8. No uncertain-reason change for these four, except as noted.

**Risks.** Low. The only risk is the LLM mislabelling USD/CAD (THI is a CAD case; see theme 8).

**Decisions.** None; a currency-known metric would need adding to the scorecard if floored.

---

## 8. Gate false-fails on correct terms (stale close, missing acquirer price, non-USD cash leg) — 7 cases

**Pattern.** LLM terms match the filing, yet `llm_gate_failed;merger_at_par`: NYX (ICE), SCS (HNI), EV (MS; `ftd_close_prior:5`, a stale close, not a misread), SUN (ETP; regex `payout_gate_failed:25` plus no ETP close), THE (HERO), EP (KMI; the skeptic REFUTED a terms misread: 14.53 / 0.4231 is the final prorated package, so only the currency and the 0.640 warrant leg are open), THI (C$65.50 cash against a USD close; QSR's first fails row 2014-12-17 carries the 12-16 close, so no 2014-12-15 price exists). Each is a mixed or election package whose acquirer price is missing or stale at the price date.

**Rule.** (a) The same acquirer-pricing repair as theme 1 (next-day row, CUSIP, skip placeholders). (b) A stale last close (`ftd_close_prior:n`, `ftd_close_lagged`) widens or defers the sanity check rather than failing it (EV: a gate failing on a stale close alone should not force assumed par). (c) A non-USD cash leg is converted or the gate skipped (THI: publish CAD, skip the cash leg in the gate with a flag). (d) A warrant/CVR leg the rule cannot carry (EP's 0.640 KMI warrant) goes in `value_formula` as a note and is not a reason to fail.

**Where.** `payout_gate.reconcile`/`gate_payouts`, `ftd.close_age`/`close_known_on`, `pipeline._gate`, `payout_rule._merger` (currency), `llm_merger_extractor` (currency).

**Guard.** The stale-close relaxation must not pass terms that fail by more than the tolerance on a fresh close (flag with the existing `ftd_close_*` flags). The library has no FX source, so only skip-with-flag for non-USD (needs a ruling).

**Cases.** currency_missing: NYX, SCS, EV, SUN, THE, THI. terms_misread: EP (terms claim refuted; keep terms, add currency and the warrant note).

**Effect.** `terms_gate` failed to passed (or skipped for non-USD); assumed par clears where the price repair works. THI does not pass by repair alone (no 2014-12-15 QSR row). `cash_currency` also fixed (theme 7).

**Risks.** Hypothesis-level: the reports say "probably" about why these gates failed (missing HNI/ETP/MS price, stale close). Reproduce with a cached `--limit` run before building. Relaxing the gate risks letting a misread through (the BOT lesson).

**Decisions.** Decision 4 (assumed par is acceptable only after a PASSED gate): do not relax it. A "terms unfalsified but unpriced" state would need a new verdict class; needs ruling if wanted.

---

## No library change (1)

- AVB BBG000BLPBL5_2026-08-27 (terms_misread, skeptic REFUTED terms): price_date 2026-08-17 follows the rule (session after the last trade 2026-08-14); the acquirer line (same CUSIP, same sec_id) traded 2026-08-17 under EQR, and only the ticker string VMRK began 2026-08-18. Do not move price_date. The only residual is the weak-issuer flag `issuer_from_todays_ticker_map`, which the Form 25 filer's CIK 915912 would clear (the small fix noted in theme 2, not a terms fix).

## Does not fit (0)

None. Dependencies on other fix groups (not mine): last trade dates for FRK, FWLT, CZR, CBSS, AWH, CYTC, PCYC, ARD, LEG; `resolved_from_continued_filings` for CAL, WR, LSXMA, UFS, MDC, LGFB; stale caller seeds for BOT, THE, TRI, SLR, ABI, GCI.

## Count check

- Theme 1: 14 (CAL, RTN, MIR, RYL, TCF, GLIBA, AMSG, WR, GXP, LSXMA, LEG, GCI, GRUB, ABI)
- Theme 2: 5 (GPOR, BTU, SPNV, HTZ, GTX)
- Theme 3: 6 (WOLF, CCE, VSTO, MDP, ARD, LGFB)
- Theme 4: 8 (FRK, FWLT, RKT, PARA, CZR, BLUE, CBSS, SLR)
- Theme 5: 4 (RAI, TWC, BOT, MIC)
- Theme 6: 3 (AWH, PCYC, CYTC)
- Theme 7: 4 (UFS, MDC, MASI, TRI)
- Theme 8: 7 (NYX, SCS, EV, SUN, THE, EP, THI)
- No library change: 1 (AVB); Does not fit: 0
- Total: 14+5+6+8+4+3+4+7+1 = 52.
- By source file: terms_misread 25 (RAI, GPOR, FRK, FWLT, AVB, MDP, RKT, RTN, RYL, TCF, PARA, MIR, EP, AMSG, BOT, TWC, MIC, BLUE, CZR, VSTO, BTU, GLIBA, CCE, CYTC, SPNV); terms_not_extracted 11 (WR, LEG, PCYC, GXP, AWH, ARD, GCI, LGFB, LSXMA, CBSS, SLR); currency_missing 11 (THI, NYX, UFS, SCS, MDC, SUN, MASI, EV, ABI, THE, TRI); price_security_wrong 5 (CAL, WOLF, GRUB, HTZ, GTX).

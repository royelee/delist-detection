# 5c research: issuer role and successor links

Date 2026-10-04, at commit 678658c (5b accepted, D.mismatches 596). Read-only. Every finding comes from cached data
(`cache/edgar`, `cache/edgar/text`, `cache/edgar/raw`, `cache/openfigi`) with network refused, over the committed
`output/`.

Probes are in the scratchpad (`/private/tmp/claude-501/.../scratchpad/`, prefix `r5c_`; not committed). They reuse
`r5b_offline.py`, which refuses every request and makes every cache write a no-op.
- `r5c_judge.py`: judges the 5c truth rows against `output/`.
- `r5c_rows.py`, `r5c_succ.py`: show each case's rows and its successor's presence in the run.
- `r5c_filings.py`, `r5c_texts.py`, `r5c_follow.py`: filing lists, 8-K conversion sentences, and line-follow text
  sources.
- `r5c_succsearch.py`: replays stage 9's 8-K12B full-text search.
- `r5c_figi.py`: reads cached OpenFIGI answers.
- `r5c_r1b.py`: an own-share conversion reader, prototyped over all 1,005 delisting rows. Its output is
  `r5c_r1b.jsonl`.
- `r5c_flip.py`, `r5c_links.py`, `r5c_role.py`, `r5c_age.py`: measure each proposed rule over the whole run.

The 5c target set is the 28 truth rows with `fixed_by` 5c. Together they hold **114 mismatches**:
- the 26 case-map rows less DRQ and CEIX, which already pass after 5a;
- plus DOW and SPWRA, routed here by 5a and 5b;
- plus DISCA (pre-ruled) and CCO.

## 1. Code map

Line numbers refer to 678658c.

**Where an ending's kind is decided (stage 5).**
- `DelistingFinder` calls `classifier.classify_event` with the matched Form 25 and `trading_after` (delistings.py:601).
- `_delisting` adds `successor_unknown` only to a not-continued `exchange_transfer` (delistings.py:620-625). A merger
  or `unknown` row never gets it, so stage 9 never looks for its successor.
- `_classify_resolved` (classifier.py:584) tries, in order: revocation, bankruptcy, `_rename_or_transfer` (381), SPAC,
  then the continued-filings rule.
  - The continued-filings rule calls `end_of_era.signals`/`resolve` (classifier.py:733-768).
  - Otherwise it goes to `_classify_filings` (779). That path maps the anchor 8-K's items through `_classify_items`
    (490): 2.01+3.01+5.01 gives 231, 2.01+5.01 gives 233, 5.01 with 3.01/3.03 gives 231, and 2.01+3.01 gives 200.
  - With no code it falls to `_default_without_fingerprint` (431, `no_evidence_default`, which gives `unknown`).
- `end_of_era.resolve` (end_of_era.py:98-123): branch 2 is "a successor registration in the registrant's own filing
  list gives 304". Branch 3 is "5.01 gives a merger" (109). Branch 4 is "2.01 with a merger filing or a Form 25 gives
  a merger" (112).
  - Nothing in `signals` (69) asks whose shares were exchanged. The deciding 8-K's text is never read.
  - The resolver runs only where the continued-filings rule fires: 180 days of filings after the end. So a 2026
    ending (OKE, CWENA) can never reach branch 2.
- **R1 today.** Nowhere is "one share for one, no cash" read from a filing. The only ratio in the run is the LLM's
  stage-8 terms (`pipeline._merger_payouts`, pipeline.py:1075). Those exist for merger rows only. They feed only the
  payout gate and `payout_rule`.

**Where a successor is linked (stages 4b, 9, 9b).**
- **Stage 4b line follow.** `pipeline._follow_lines` (519) runs `line_follow.candidate_steps`, `corroborate` and
  `decide`, which records `LineSuccessor` for a FIGI line whose new CUSIP has its own composite (R2).
  - New tickers come from EDGAR's tickers list today, and from `_text_sources` (485, via `line_follow.text_symbols`
    and `_TEXT_SYMBOL`, line_follow.py:54).
  - The window is ±10 trading days around the old CUSIP's settled last row.
- **Stage 9 `_find_successors`** (pipeline.py:1143) tries three things in order:
  1. `_line_successor_links` (1110): the step's first row within [-5, +15] of the anchor.
  2. `successors.successor_in_run` (successors.py:133): exactly one security whose first sighting falls in
     [anchor-5, anchor+15] and that has the same issuer CIK or the same ticker. It runs only on `successor_unknown`
     rows.
  3. `successor_from_8k12b` (35): full-text search for the predecessor's name, skipping `exclude_cik`, the
     predecessor's own CIK (78). `successor_search_args` (160) builds the search with `successor_search_name`
     (109), which uses the issuer's **current** EDGAR name.
  - The anchor is the last trade, else the Form 25 filing date, else `delist_date`. The fallback `delist_date` is
    approximate.
- `_link_successors` (1216) records the answer. `_mark_continuing_delistings` (1517) marks self-successors.
- **Stage 9b `_handoffs`** (1238, `handoffs.py`). `find_handoffs` pairs securities sharing one ticker.
  - `decide_handoff` (203) decides by:
    1. filing: an 8-K12B/12G3 naming the predecessor, or `own_continuation_filing` (136);
    2. timing plus the same CIK, or a CUSIP switch;
    3. takeover: B traded before, or B's issuer is older than `ISSUER_AGE_DAYS` = 365 (44).
  - `apply_handoffs` refuses to rewrite a merger on `timing:cusip` evidence and writes `handoff_conflict`
    (handoffs.py:401-406).

**Where the issuer in force is decided.**
- The era's CIK comes from the resolver (stage 2) and `security_master.issuers_by_era`.
- `issuer_in_force.issuer_changes` dates name-based issuer changes. Stage 4c (`pipeline._other_issuers`, 1732) makes
  the finder read the one other CIK in force (5b R5).
- None of these decides the role (target, survivor, distributor) in a transaction. That is 5c's rule 1.

**Data at each plug-in point.**
- Stage 5 has:
  - the registrant's filing list;
  - cached 8-K texts. The classifier already reads 3.01 and 1.03 texts. Every 5c 8-K text below is cached, and only
    58 of the 1,005 rows have only uncached 8-Ks in the window.
  - the matched Form 25 and its EX-99.25 notice in `cache/edgar/raw`. OKE's notice names the new CUSIP 30609A109.
- Stage 8 adds the LLM terms: ratio, cash and acquirer ticker. They are published even when the gate failed.
- Stage 9 adds every security's first sighting, issuer and ticker. It also has the fails index to the run date
  (extended in 4b) and the OpenFIGI client.

## 2. Per-case evidence

"Run" is the committed row. "Why" was replayed through the real code where possible.

The truth row cells are abbreviated:
- `cont` means `exit_kind` exchange, continuation true and `value_rule` continuation.
- "no row" means `no_ending`.

| Case | Run | Truth | Why the run differs | Minimal rule |
| --- | --- | --- | --- | --- |
| BHI | 304 B2, `successor_unknown` | cont → BHGE BBG00GBVBK51 | BHGE starts 06-30 in the window but has another CIK and ticker. The search used today's name "Baker Hughes Holdings LLC" (0 hits); the 2017 names were never searched. | N-link (new registrant, own 8-K12B 07-03, text "one share of BHGE's Class A") |
| HHC | 304 continued filings, no successor | cont → HHH BBG01HTMDZ54 | HHH starts 08-14 in the window. Search "Howard Hughes Corp": 0 hits. HHH's CIK is new (first filing 2023-08-11, its 8-K12B). | N-link (HHC 8-K: "converted into one share … of Holdco") |
| CMCSK | 304 continued filings | cont → CMCSA BBG000BFT2L4 | CMCSA has the same CIK but began in 2007, outside the window. | S-link (8-K 2015-12-15: "reclassify each … Class A Special … into one share of Class A") |
| HUB-B | 304 continued filings | cont → BBG000BLK267 | HUBB has the same CIK, existed since 2008 and also holds HUB-B's CUSIP 443510201 (a duplicate line). | S-link (8-K 12-23: "Class B … reclassified into one share of common stock") |
| CCO | 304 B2, no successor | cont, successor `*` | The 8-K12B is under the same CIK, which `exclude_cik` drops. 4b's ±10-day window misses the new CUSIP: 18451C109 last 04-12, 18453H106 first 05-03. | C-link (same-CIK 8-K12B: the new CUSIP under CCO in [anchor, +15]; OpenFIGI cached BBG000SSC5C9 ≠ own, so R2 gives two securities) |
| CWENA | `unknown` no-evidence | cont → CWEN BBG008LJ4TF3 | Items 1.01/3.03/5.03 give no code. It is too recent for the continued-filings rule. | Stage 5: own-share 1:1 gives 304. Then S-link (8-K 05-01: "Class A … converted into one share of … Class C") |
| OKE | `unknown` no-evidence | cont, successor `*`; ltd blank | Same as CWENA. The 8-K12B 09-10 is in OKE's own list. | Stage 5: 1:1 (8-K12B and Form 25 notice: "one share of ONEOK, Inc. (New, CUSIP 30609A109)"), then a C-link via the named CUSIP. Left: the last trade date (contract 2026-09-09 from the notice), which is 5d. |
| DOW | 231 branch 3 (5.01), LLM 1.0 DWDP | cont → BBG00BN961G4 | Branch 3 asks no role. DWDP has another CIK and ticker. | R1 flip (LLM 1.0, no cash; text "Dow … one … share of DowDuPont"; DWDP CIK 548 d old), then N-link |
| MYL | 231 M&A items, LLM 1.0 VTRS | cont → BBG00Y4RQNH4; internal ltd 2020-11-16 | Same as DOW | R1 flip (text "each Mylan Share … exchanged for one share of Viatris"; Viatris 388 d), then N-link. Left: the internal last trade date (5d). |
| SBGI | 231 branch 3, no Form 25, LLM 1.0 SBGI | cont → BBG01GJ3NY88 | Same; BBG01GJ3NY88 is an added acquirer with the same ticker | R1 flip (text "exchanged on a one-for-one basis"; Sinclair Inc 59 d), then `successor_in_run` same_ticker |
| DISCK, DISCA | 200 branch 4 (2.01 + 425), LLM 1.0 WBD | cont → WBD BBG011386VF4 | Branch 4 asks no role. WBD has the same CIK and starts 04-11. | R1 flip (text "Series A/C … reclassified and converted into one share of WBD"), then `successor_in_run` same_issuer |
| LLYVA, LLYVK | 200 branch 4, LLM 1.0; `handoff_conflict` timing:cusip | cont → BBG01YY256K1 / BBG01YYX1Z14; ltd 2025-12-15 | The handoff refuses a merger on timing:cusip | R1 flip (text "in exchange for one share of the corresponding series"; Liberty Live Holdings 143 d), then N-link by class letter. Left: the last trade date (5d; the handoff's `_last_day` would give 12-16). |
| WAG | 231 M&A 5.01+3.01+3.03, LLM 1.0, no price ticker | cont → WBA BBG000BWLMJ4 | Merger code; never searched | R1 flip (text "converted into one share of WBA"; WBA 106 d), then N-link |
| DTV | 231 M&A items; `handoff_conflict` | cont → BBG000FL1TC8; internal ltd 2009-11-19 | As LLYV | R1 flip (text "received one share of DIRECTV Class A … for each share"; 164 d). Left: the internal last trade date (5d). |
| ROVI | 233 M&A 2.01+5.01, no Form 25, LLM 1.0 TIVO | cont, successor `*`; ltd blank | The successor TiVo Corp (CIK 1675820, not cached) is not in the run, and the gate failed, so `_add_acquirers` skipped it | R1 flip, then add the successor from the terms' ticker or the 8-K12B search. Left: ltd, where the truth is blank but MIDAS gives 2016-09-07 (see 5). |
| EGL | One security over both CUSIPs; 2019 SAIC merger | 2015 cont, successor `*` | OpenFIGI: old CUSIP 29285W104 has no composite; the new 29286C107 is BBG001BP9474, the security's own. R2 makes it one security. | None: a truth conflict (5) |
| RRI | 231 branch 4 (2.01 + 425) | no row | RRI was the legal acquirer of Mirant. 4b's text reader took "RRI" from "changed from “RRI” to “GEN”" and dropped it as an own ticker, so GEN was never scanned. | Role refusal, plus 5a's `text_symbols` reading "from X to Y". That follows the line to the NRG 2012 ending, which is a truth conflict (5). |
| SXCI | 231 branch 4 | no row | Acquirer of Catalyst, renamed Catamaran (CTRX). No new symbol source: EDGAR tickers empty, no 5.03 8-K in ±30 d. | Role refusal leaves a 304 ending. Following needs a new step source (see 6); then the Catamaran 2015 ending is a truth conflict. |
| NWS-A, NCRA | 231 branch 4 (Separation 2.01) | no row | 21CF renamed; FOXA (90130A101) has no symbol source. NCRA is a duplicate placeholder. | As SXCI; 21CF later ends 2019 (Disney) |
| FI | Folded by 5a into BBG004K27P01 (XPRO); ending 2026-07-24 | no row | The 2026 ending is real: DEFM14A 2026-04-21, 25-NSE 2026-07-14, 15-12G | None: a truth shape conflict (5) |
| ESV (Class A) | BBG000BJ2VQ6; 2020-09-14 bankruptcy | no row | The 2020 Valaris ending is real | None: a truth shape conflict (5) |
| FST | 200 branch 4 (an asset-sale 2.01 + DEFM14A) | dropped/guidelines, `otc_print` FSTO | The registrant survived a reverse merger. Its CUSIP traded on as FSTO, and NYSE removed it under 102.01. | Role refusal, then branch 5 (3.01 deficiency) if its wording is covered. `otc_print` FSTO is 5g's rule. |
| ESV 2010 | Handoff row 2012-05-22 | 2010-01-08 cont, ltd 2009-12-22 | The placeholder holds the ADS CUSIP 29358Q109 (2009-12 to 2012-05), so the 2009 Form 25 is "continued". Neither CUSIP has a composite. | Identity split (5h) or residual. It also conflicts with R2 (5). |
| ODP | cont → BBG00R24W7X2 (5a) | internal ltd 2020-06-30 | Last trade date only | 5d (closing day) |
| SPWRA | cont → BBG000FVQ185 | internal ltd 2011-11-16 | Last trade date only (an effective-time date) | 5d |

**Tally.**
- **11 pass with 5c alone:** BHI, HHC, CMCSK, HUB-B, CCO, CWENA, DOW, SBGI, DISCK, DISCA, WAG (52 mismatches).
- **6 keep only a last-trade field**, which goes to 5d (or to a ruling for ROVI): MYL, DTV, OKE, LLYVA, LLYVK, ROVI
  (31 of 37 mismatches fixed).
- **4 need a truth ruling:** FI, ESV-A, EGL, RRI. RRI also needs the 5a text-symbol fix.
- **7 need another sub-plan:**
  - SXCI, NWS-A, NCRA need a step source. Their role refusal alone leaves a 304 ending.
  - FST needs 5g.
  - ODP and SPWRA need 5d.
  - ESV 2010 needs 5h.
- So 5c's rules fix 83 of 114 mismatches. The rulings would add about 12 more.
- **Bonus outside 5c's own rows:**
  - PX and AMSG (5e) also flip to the continuations their truth expects (Linde plc 517 d; new Envision 119 d).
  - Rule 6 turns CHTR (5f) into a 0.9042 stock merger.

## 3. Guard cases that must not change

Each was checked against the measured signals.

| Guard | What would wrongly fire | What stops it |
| --- | --- | --- |
| TW → WLTW (Willis reverse-consolidated to 1:1) | LLM 1.0, and WLTW's line starts 2016-01-05 in the window | Issuer age: Willis CIK 1140536 is 5,347 d old |
| WCN → Progressive (2.076843 then a consolidation) | LLM 1.0; text "converted into one common share" | Issuer age 4,125 d |
| LVNTA → GLIBA (pass: merger 1.0) | LLM 1.0; a 1:1 redemption | Issuer age: GCI CIK 808461 is 8,442 d old. Without this guard LVNTA and LLYV are indistinguishable. |
| JEF (1:1 into New Jefferies, then 0.81 LUK) | Text 1:1 (the intermediate step) | LLM final terms 0.81, so no flip. The text reader must not decide merger rows alone. |
| SGP (Old Merck → New Merck 1:1 in SGP's own 8-K) | Text 1:1 (wrong party: SGP's later EDGAR name is "Merck") | LLM 10.50 + 0.5767; subject names taken from **before** the event |
| FCL (survivor renamed Alpha; holders got 1.084) | The role signal "renamed + no Form 25" | The own-share statement 1.084 means a target-like merger; the role needs no own-share conversion |
| BKW → QSR (0.99 + $3.00, or 1 unit by election) | LLM 1.0 (the election leg) | Text 0.99 + cash gives "other". QSR's CIK is blank in the run. Risk: re-check when 5f adds elections. |
| KRFT (truth 5e: 16.50 + 1.0 KHC) | Text 1:1 | LLM cash 16.50, so no flip |
| CHTR 0.9042, MTCH 1.0337, WEN 4.25, IGT cash, EVHC 0.334, CCE cash | Handoff timing:cusip lift | The lift needs R1 terms (1.0, no cash) |
| BGCP, GTES, STX, SIRI, NRF, BKFS, BEPC, XRX, CI, APA (pass continuations) | Rule 6 (ratio ≠ 1) | Their own-share text is 1:1 or absent. Only CHTR reads ≠ 1. PNFP and VNOM read "mixed" because the counterparty's ratio is in the text, so only an unambiguous own-share statement may flip. |
| AABA (2017-06), MSG (2015 spin-off), HUB-B | N-link without a name tie: AABA → BHGE, MSG → Alphabet's two lines, HUB-B → two unrelated 2016 registrants (all measured) | The N-link requires the predecessor's conversion text to name the successor (EDGAR name or ticker), or the successor's 8-K12B to name the predecessor |
| LMCA 2013, MSG 2015 (spin-off took the ticker) | N-link and handoff | No own-share 1:1 statement (a distribution); `lived_on` and `issuer_carries_on` are unchanged |
| BNI, CAL, TXU, STOR (targets renamed after closing), LGFA (pass merger, "completed the separation") | A role rule on rename or separation words | The role is decided by whose shares were converted, never by rename words alone |
| KHC 2026 (pass, R7), ACXM (pass, no row), UAL 2006 | None | Untouched paths |

## 4. Blast radius (outside the truth set, measured over the run)

- **R1 flip of merger rows.** The rule:
  - contract terms 1.0, no cash;
  - the own-share text agrees;
  - the successor is a new line in [-5, +15] of a CIK ≤ 1,095 d old, or of the same CIK.

  The 28 ratio-1 merger rows give 7 flips outside the truth set: ASH (Ashland Global), HFC (HF Sinclair), WWE (TKO),
  NSAM (Colony NorthStar), STE (STERIS plc), CSC (DXC) and FTI (TechnipFMC). All are new-holdco 1:1 deals, so R1
  expects each to be new_right.
  - AAN and BKW are blocked by a blank successor CIK.
  - With the prototype reader's ~50% recall, only ASH and NSAM pass the text check. The real reader must recall the
    rest (fixtures in 6).
- **Handoff conflict lift.** 12 conflicts in the run. 6 have R1 terms: ASH, FTI and STE (outside), plus LLYVA, LLYVK
  and DTV. The other 6 stand.
- **Transfer and unknown links.** 21 + 6 rows lack a successor.
  - With the name tie: BHI, HHC, CMCSK, HUB-B, CWENA and OKE, all in the truth set. None outside.
  - Without the tie: 3 false links (AABA, MSG, HUB-B to the wrong registrants).
- **Same-CIK 8-K12B (C-link).** Only CCO and OKE.
- **Role refusal on branches 3 and 4.** 69 rows. "No own-share conversion, plus another party's shares converted into
  the registrant's or its own separation" fires on RRI, SXCI, NWS-A, NCRA, FST and SBGI. All are in the truth set.
  - FCL (1.084) must be refused by the own-share reading.
  - Scope: only branches 3 and 4. The 586 classifier M&A-item rows were not measured; leave them out.
- **Rule 6.** CHTR only.
- **Line successors' Form 25 search** (carried from 5b). Known: CRC BBG0060B3M63 2020, DYN BBG000BNLX91 2012 and ODP
  Corp BBG00R24W7X2 2025. Plus the added successors 5c creates: TiVo Corp merged into Xperi in 2020; BBG000SSC5C9 and
  the new OKE line are live. About 3–6 new endings.
- **Expected regression volume: about 10–13 securities** (5a had 24, 5b 20). There are also changes on truth
  successor chains, which the report excludes.
- **Audit (A.\*).** The flips change audit rows that predate R1 (see 5).

## 5. Truth conflicts (for the operator before the plan)

1. **"No row" on a line that has a real later ending.**
   - Cases: FI (Expro acquired 2026: DEFM14A 2026-04-21, 25-NSE 2026-07-14) and ESV Class A (Valaris bankruptcy
     2020). Once the line is followed, also RRI (GenOn to NRG 2012-12), SXCI (Catamaran to UnitedHealth 2015-07) and
     NWS-A/NCRA (21CF to Disney 2019).
   - The judge fails `no_ending` whenever a contract row exists, so these can never pass.
   - The audit already expects RRI to end 2012-12-13 and SXCI 2015-07-23.
   - **Recommend:** shape `ending_moved` (old date = the case date), later fields `*`.
2. **R2 against a continuation truth.**
   - EGL 2015: the old CUSIP has no composite, and the new one is the security's own FIGI. **Recommend:**
     `ending_moved` (the 2019 SAIC merger is the ending). The other option is the SPWRA precedent (keep the
     continuation), but that needs splitting one FIGI, which is residual like R7/EXE.
   - ESV 2010: neither CUSIP has a composite. **Recommend** the same reading, or residual. Fixing it needs an
     identity split (5h).
   - HUB-B: the placeholder duplicates HUBB's line. By R2 it would fold. **Recommend** keeping the truth (the SPWRA
     precedent), since the S-link produces it.
3. **The special-dividend rule is applied both ways.**
   - BHI ($17.50), EGL ($11.434) and SBGI ($0.25): "not consideration", so continuation.
   - KRFT (5e): "$16.50 merger-conditioned special dividend", so cash_plus_stock.
   - 5c's flip does not touch KRFT (the LLM reads cash), so there is no library conflict now.
   - **Recommend:** confirm one rule. Either a dividend paid by the successor after closing is not consideration and
     KRFT is re-ruled, or the dividend counts and BHI, EGL and SBGI become mergers.
4. **Audit rows that predate R1.**
   - `data/accuracy_audit.csv` expects `merger` for BHI, DOW, WR and EGL, against the diagnosis truth (an exchange
     continuation; EGL see 2).
   - **Recommend:** as with LTRPA in 5b, the audit rows follow R1.
5. **Last trade on ROVI.** The truth is blank, while MIDAS gives 2016-09-07.
   - The 5b pre-check's G2 makes a MIDAS print publishable. **Recommend:** 2016-09-07.
   - OKE's notice date (09-09, from "exchanged on September 10") is a similar question for 5d.
6. **LVNTA against LLYVA/LLYVK** (pass: merger 1.0 GLIBA, against continuation). The two are consistent only under
   the "successor issuer is new" reading of R1 ("a split-off into a new issuer").
   - **Recommend:** adopt the issuer-age guard as that reading.

## 6. Design proposal

Six units, in run order. Plus the carried Form 25 search.

**U1. `exchange_terms.py` (new, pure): the own-share conversion statement.**
- Signature: `own_exchange(texts, *, names, class_letter, class_words) -> OwnExchange | None`, where `OwnExchange`
  carries `ratio`, `cash`, `target_text`, `target_names`, `sentence` and `ambiguous`.
- It reads sentences of the forms "each (outstanding) share of S … (was/were/automatically) (converted / exchanged /
  reclassified / redeemed) … (into / for) (the right to receive) N … share(s) of T", "received N share(s) of T for
  each share of S", and "… on a one-for-one basis".
- S must name the registrant: its EDGAR names in force **before** the event, its defined terms ("SBG"), "the
  Company('s)" or "its".
- S must also name the security's class (letter plus distinguishing word: "Class A Special"). S must not name a
  Merger Sub, another party, options, preferred stock or units.
- Cash means a "$N" or "in cash" in the consideration clause, after par values and cash in lieu of fractions are
  removed.
- Several own-share statements with different terms make the result `ambiguous`.
- Tests on the cached texts: BHI 0001193125-17-220863, HHC 0001104659-23-090461, CMCSK 0000950103-15-009516, HUB-B
  0001193125-15-412174, CWENA 0001104659-26-053557, DISCK/DISCA 0001193125-22-103051, MYL 0001193125-20-298224, SBGI
  0001193125-23-158935, WAG 0001193125-14-457669, DTV 0001104659-09-066017, ROVI 0001193125-16-704222, OKE
  0001193125-26-387972 plus raw 0000876661-26-000770, LLYVA 0001104659-25-121236, and DOW 0001193125-17-274845
  (DuPont's 1.2820 sentence must be rejected).
- Guard tests: JEF, SGP, FCL, WCN, PNFP, VNOM, CHTR and BKW.
- The prototype `r5c_r1b.py` reached about 50% recall. Set the target from these fixtures.

**U2. Stage 5, the classifier.** `DelistClassifier` reads the registrant's 8-K/8-K12B/8-K12G3 texts filed in
[anchor-3, anchor+10] plus the matched Form 25 notice. That is cached for all cases; cold, about 1–3 texts a row.
- (a) In `end_of_era.signals`/`resolve` (end_of_era.py:69, 98), a new `EraSignals.own_exchange` and `survived`.
  Branches 3 and 4 fire unless `survived`. `survived` means no own-share statement plus the 8-K stating another
  party's shares converted into the registrant's shares, or the registrant's own separation or distribution. Then
  resolution falls through to branch 5 (FST) or 6. Never decide on rename words.
- (b) In `_classify_filings`'s no-code path (classifier.py:854), and before the continued-filings rule: an own-share
  1:1, no-cash statement makes 304 "continuation (R1)" with `successor_unknown` (CWENA, OKE).
- (c) Branch 2 (end_of_era.py:106) and the same 304 path: an unambiguous own-share statement with a ratio ≠ 1, or
  with cash, makes a merger (rule 6, CHTR), so stage 8 reads its terms.
- Also fix 5a's `line_follow.text_symbols` to read "changed from X to Y" as Y (RRI). It is a small change, measured on
  RRI only; re-run 4b's replay before taking it.

**U3. Stage 8b `pipeline._r1_continuations(delistings, payouts, securities, starts)` (new, after `_merger_payouts`).**
- A merger row becomes 304 "continuation (R1: one T share per share, no cash)" with `successor_unknown` and flag
  `r1_continuation`, when all of these hold:
  - its contract terms are a stock ratio of exactly 1, no cash leg, and no override;
  - its `own_exchange` is 1:1 with no cash and not ambiguous;
  - one candidate successor is either a security of the same CIK that is a new line in [anchor-5, +15], or a
    security of a CIK at most `NEW_ISSUER_DAYS = 1095` old (first EDGAR filing) whose first sighting is in the window.
- The row's payout, gated terms and LLM terms are dropped, so `payouts.csv` and the contract carry no value. The
  `handoff_rebucketed`-style review item is kept, so the old bucket is visible.
- Do not reuse handoffs' `ISSUER_AGE_DAYS = 365`. Measured new holdcos are 0–548 days old (DWDP 548, Linde 517,
  Viatris 388). Existing acquirers are 4,125–8,442 days.
- A "no periodic report before" test fails as well: WBA, LLYV Holdings, Viatris, Linde, DXC and TechnipFMC all filed
  one before closing.

**U4. Stage 9 `_find_successors` branches** (pipeline.py:1143; `successors.py`).
- **Anchor.** Last trade, else the Form 25 filing date, else the deciding 8-K's date, never the approximate
  `delist_date`.
- **S-link** (`successor_same_issuer`): a security of the same CIK, of the class `OwnExchange.target_text` names,
  sighted before and after the anchor. No first-sighting window (CMCSK, HUB-B, CWENA).
- **N-link** (`successor_by_terms`): one security whose first sighting falls in the window, of another CIK at most
  1,095 d old, whose name or ticker `OwnExchange.target_names` contains, or whose own 8-K12B/12G3 in [-30, +60] names
  the predecessor. Pick by class letter when several match (BHI, HHC, DOW, MYL, WAG, DTV, LLYVA/K).
- The existing `successor_in_run` same_ticker branch covers SBGI.
- **C-link** (same-CIK 8-K12B, `successor_from_own_registration`):
  - The new CUSIP comes from the Form 25 notice or the 8-K text (`line_follow.text_cusips`), else from the first new
    CUSIP under the security's ticker in [anchor, anchor+15] in the fails index.
  - It is resolved through OpenFIGI's CUSIP job and R2 (`line_follow.decide`). A different composite becomes an
    `AddedLineSuccessor` (CCO, OKE); the same one or none becomes a self-successor.
- **Search names.** `successor_search_args` searches with `handoffs.predecessor_names` (names in force within 30 d),
  not the current name (BHI).
- **Unobserved successor** (ROVI): from the terms' acquirer ticker through `acquirers.find_acquirer`, before 5e's
  gate move, else through the 8-K12B search. It becomes an `AddedSuccessor`.

**U5. Stage 9b.** In `apply_handoffs` (handoffs.py:401-406), a `timing:cusip` merger is rewritten when it carries
`r1_continuation`, or U3's evidence (LLYVA, LLYVK, DTV; outside the truth set ASH, FTI, STE).

**U6. Stage 9d (carried from 5b; recommend 5c owns it).** The Form 25 search for the added successors (line and 8-K12B
successors), built from each one's CUSIPs, ticker span and issuer.
- Form 25 matches only: no fallback ending for a security without observations.
- 5c owns it because 5c adds more such successors (TiVo Corp ended 2020), and their missing endings break the chains
  5c creates.
- Volume: about 10 securities, each one submissions read plus Form 25 raws.

**SEC traffic.**
- Cold reads: about 100 8-K texts.
- Full-text searches: about 15 rows times 1–3 names.
- A few submissions reads (TiVo).
- About 10 OpenFIGI CUSIP jobs (OKE 30609A109, RRI 37244E107, TiVo).
- A warm rerun is free.
- The full rerun passes `--id-baseline <678658c output/securities.csv>`.

**Spec rules unsafe or underspecified as written (measured).**
- **Rule 1 by "filing text and form".** Rename and separation words fire on targets (BNI, CAL, TXU, STOR, LGFA). Use
  the own-share statement instead. Restrict the rule to branches 3 and 4.
- **Rule 4 "its 8-K12B names the old class".** An in-run new registrant with an 8-K12B in the window links wrongly 3
  times without a name tie.
- **R1 from an 8-K12B alone.** CHTR (0.9042) and DuPont (1.282) also have successor registrations. The ratio must be
  read.
- **"Text decides" for merger rows.** Multi-step deals put an intermediate 1:1 in the text (JEF, SGP). Require the
  LLM's final terms to agree.
- **The issuer-age threshold is not in the spec.** 365 d (the handoff value) misclassifies DWDP, Linde and Viatris.
  Use about 3 years.
- **Rule 5** (`AddedSuccessor` "from the fails rows under its ticker"). A ticker answer today can be a later reuse.
  Use the CUSIP the notice or text names, or the first new CUSIP in the window, and use OpenFIGI's CUSIP job, never
  the TICKER job, except for an event within 120 days of the run (OKE).
- **No-ending acquirer cases need the line followed onto a new ticker.** The spec gives that to 5a, and 5a has no
  symbol source for SXCI or NWS-A. The plan should either:
  - add a fails-description step source (a new CUSIP whose descriptions name the issuer's post-event name, first row
    in the window), which is unmeasured and costly; or
  - accept SXCI, NWS-A and NCRA as residual after the role refusal.

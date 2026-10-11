# 5a research: one line across a CUSIP or ticker change

Date 2026-10-03. Read-only research for the 5a plan. Inputs: spec section 3 "5a", ruling R2, section 1; the roadmap's
carried task (N1); reader notes E themes 1/10/11, B T6, D themes 1/2/6; the 43 `case_map.csv` rows with sub_plan 5a;
the committed `output/` (commit fe511e2); cached data only (fails zips `cache/sec_data/ftd/`, `cache/edgar/`,
`cache/openfigi/`). Probes (scratchpad, not committed): `r5a_ftd_agg.py` (every cached fails row aggregated per
CUSIP and symbol), `r5a_evidence.py` (per case), `r5a_8k_cusip.py` (does the 8-K text name the new CUSIP or
symbol), `r5a_replay.py` (offline replay of `refine_eras` + `cusip_handoffs` over the cached zips),
`r5a_blast.py`/`r5a_blast_n.py`/`r5a_other_truth.py` (blast radius), `r5a_after.py` (filings after a switch). EDGAR
reads went through `EdgarClient` with `edgar.sec_get` replaced by a function that raises, so nothing left the
machine.

## 1. Code map

### 1.1 Why the line stops today (confirmed by replay)

1. Stage 1, `security_master._split_era` (security_master.py:129-144). `_switch_cuts` (119-121) splits an era's fails
   rows at a new CUSIP's first row. The part after the cut has no observation, so line 133-134 (`if not obs:
   continue`) drops it. The era keeps only the old CUSIP. Replay: `FMD@2008-01-16 ftd_cusips ('320771108',)`, though
   320771207 trades under FMD from 2013-12-04 to 2016-08-24. Every same-ticker case in the 43 fails this way: the
   caller's observations stop years before the switch.
2. Stage 3, `candidate_cusips`/`era_cusips` (200-251) only read `era.ftd_cusips`/`era.cusips`. Nothing adds a
   CUSIP after the era's window, and `FigiResolver.resolve_many` (466-671) never asks OpenFIGI about it.
3. Stage 4, `pipeline._security_cusips` (pipeline.py:398-406): `sec_cusips` = the eras' resolved CUSIPs, then
   `ftd.extend(..., cusips=...)` to the run date. Rows of the old CUSIP under any symbol are loaded, so a same-CUSIP
   rename (HSC to NVRI, CLI to VRE, EXBD to CEB, SFI to STAR, SPW to SPXC) is already in the index.
4. Stage 5, `history.ticker_sightings` (history.py:95-112) does include those new-symbol rows. But
   `history.own_last_seen` (135-145), `_context_builder`'s `ftd_seen_after` (pipeline.py:444) and `_continues_after`
   (1092) count only `{e.ticker for e in s.eras}`. So `SecurityContext.last_seen` is the old ticker's last row, and
   `_alive_at` (delistings.py:127-134) bounds the issuer's later Form 25s to `last + SIBLING_ALIVE_AFTER_DAYS` (400 d).
   The real later Form 25 is skipped, and the fallback runs.
5. `DelistingFinder._fallback` (delistings.py:494-533) calls `classify_event(anchor_date=ctx.last_seen)`. Then
   `classifier._detect_continued_filings` (classifier.py:176-193) fires (10-K/Q more than 180 d later), and
   `end_of_era.signals`/`resolve` (end_of_era.py:65-113) picks a branch at classifier.py:720-735: 304
   `continued_filings`, branch 2 `successor` (BGCP), branch 3/4 merger (TERP 5.01, MDR 2.01), or branch 5 570
   (FMD, GOCO, YRCW). `_fallback_date` (437-460) dates it at `ctx.last_seen` with `delist_date_approx`, and the last
   trade falls back to `last_trade_date_unconfirmed` (526).
6. `_ends_the_security` (pipeline.py:1102-1123) always clips at an unconfirmed day. `_continues_after` cannot rescue
   the row, even when it was confirmed (HSC is `midas`), because it counts only era tickers.

### 1.2 Unit by unit

| Unit (file:line) | In → out | Today, for a CUSIP or ticker change | Where 5a plugs in | Data there |
| --- | --- | --- | --- | --- |
| `security_master.refine_eras`/`_split_era` (147-197/129-144) | eras, FtdIndex → refined eras | drops the post-switch fails-only part | no change (no issuer known yet); this is the cause | rows by symbol only |
| `era_cusips`/`candidate_cusips` (200/233) | era, FtdIndex, issuer names → CUSIPs | own FTD CUSIPs that describe the issuer | no change in the chosen design (see 5.1) | issuer EDGAR names (no dates) |
| `cusip_handoffs` (320-373) | eras, FtdIndex → `Handoff`s (shared CUSIP, switch) | a switch needs both lines observed as eras and the new first row within ±`SWITCH_DAYS`=5 trading days of the old last row | U2: take the old CUSIP's last row at a changing price, not a settling tail (SLE: HSH's 432589109 starts 2012-07-03, 8 trading days before SLE's last fails row 2012-07-13; MIDAS last trade 2012-06-28) | rows by symbol and CUSIP |
| consumers of `cusip_handoffs` | | **The spec is wrong here.** It is read by `ticker_resolver.infer_issuers` (ticker_resolver.py:1067-1069) **and** by `pipeline._resolve_securities` (pipeline.py:356-359) → `resolve_with_identity_guard` → `resolve_many` → `_handoff_joins` (security_master.py:416-456, used at 581). run.log has about 200 "FIGI handoff" joins (ABI, CLNS→CLNY, COH→TPR, …) | U3 in `_handoff_joins` | |
| `_handoff_joins` (416-456) | eras, issuers, handoffs, unpicked, confirmed → era→composite | `reach` only counts links to `confirmed` eras, meaning a pin or a CUSIP (447-449). The group test needs the same CIK **and** the same `share_class_from_name` (429-433) | U3: a `shared_cusip` link also reaches an era with a non-weak ticker or name pick (SPW: shared-CUSIP link `SPW@2008`↔`SPXC@2015-12-31`; SPXC@2015 is a ticker pick, not `confirmed`, so SPW stays a placeholder). Optional U3b: a class wildcard (see 6.8) | `picks` is in scope at 581 |
| `resolve_with_identity_guard` (720-740) | → resolutions, detached | loops `resolve_many` with crossing weak picks barred | no change | |
| `unconfirmed_eras`/`guarded_eras` (829-844) | eras, FtdIndex → keys | any row under the ticker confirms the era. UAG@2008's ETN rows (902641760 "E-TRACS…", from 2008-09) confirm it, so `backfill_line` never places it on PAG (BBG000H6K1B0, same CIK) | optional U4: only rows whose description can name the era's issuer confirm it (needs `issuers`) | |
| `superseded_placeholders` (757-774) | securities → retired placeholder ids | a later FIGI line of the same issuer, class and ticker | no change needed once the folds land | |
| `build_securities` (783-818) | resolutions → securities | merges eras that share a sec_id | reused after the stage 4b fold (5.1) | |
| `history.backfill_cusips` (333-346), used by `pipeline._dead_before_sighting` (520-564) | tickers, end, FtdIndex, names → CUSIPs | backward counterpart (120 d before an end; drops CUSIPs another security holds, 554-555) | U1: add a forward counterpart, `line_follow.candidate_steps` (5.1) | |
| `history.ticker_sightings`/`cusip_sightings` (95/115) | security, FtdIndex, CUSIPs → sightings | all live rows of the security's CUSIPs, under any symbol with a letter | no change; they pick up attached CUSIPs. Treat `…ZZZZ` (a new CUSIP's first-day placeholder: FMDZZZZ, JNYZZZZ, NYCBZZZZ, …) like `…XXXX` | |
| `history.own_last_seen` (135-145); pipeline 186, 444, 492, 500, 551, 865, 1092; delistings 282, 405 | | "own tickers" = observed era tickers | U5: own tickers = era tickers ∪ the symbols the line follow added | |
| `pipeline._resolve_securities` (339-395) | stage 3 | | U3/U4 land here, inside `resolve_many` | |
| `pipeline._security_cusips` (398-406) | stage 4 | | **U1 main plug: new stage 4b `_follow_lines`, right after the extend and before `_find_delistings`** | rows by CUSIP to the run date; era tickers (add them to the same `extend` so they also reach the run date); `answers.issuers`; `clients.edgar` (submissions, `recent_filings`, `fetch_filing_text`, `full_text_search`, all cached and read by stage 5 anyway); `clients.figi` |
| `pipeline._find_delistings` (462-517), `_context_builder` (409-449) | stage 5 | | U5 own tickers; U6 `SecurityContext.cusip_switches` | sightings, sec_cusips, ftd |
| `DelistingFinder.find` main loop (delistings.py:302-354) | Form 25s → candidates | a continued Form 25 at the line's own CUSIP switch is still a delisting (QGEN `unknown`, GTES `unknown`, ACXM 2018-10-01) | U6: skip a Form 25 when `continued` and the security's own CUSIP switch (R2 one security) lies within 5 trading days of its filing date, as a secondary withdrawal is skipped (350-353) | needs `cusip_switches` in the context |
| `_fallback`/`_fallback_date` (494-533/437-460), `SecurityContext.last_seen`/`seen_after` (95-119) | | anchored on the old ticker's last row | no change: reached later, or not at all | |
| `classifier._detect_continued_filings` (176-193), `end_of_era.resolve` (92-113) | | | no change: once the line is followed before stage 5, the fallback is not reached for these cases. The spec asks to guard it; that would only matter for refused follows | |
| `successors.successor_from_8k12b` (35-102, `exclude_cik` 78) | | a same-CIK 8-K12B (CCO, BGCP, GTES, ACXM) is skipped by design (the iHeart guard in its docstring) | no change; U7 gives a same-CIK successor from the line follow instead | |
| `successors.successor_in_run` (133-157), `pipeline._find_successors` (828-887) | | links an ending with `successor_unknown` to a run security that starts within [−5, +15] d | U7: stage 9 also reads the stage 4b candidates (R2: a different composite), and makes an `AddedSuccessor` only when an ending needs it | |

## 2. Per-case evidence (43 cases, cached data only)

Columns:

- **gap**: trading days from the old CUSIP's last row under the line's ticker to the new rows' first row. That row is
  under the same ticker, `T+ZZZZ` or `T+D` for a switch; under the new symbol for a same-CUSIP or new-ticker change.
  A negative gap means the new rows begin before the old CUSIP's settling tail ends.
- **rename/filing**: an EDGAR formerNames rename within ±90 d; an 8-K 5.03/3.03/8-K12B by the same CIK within ±30 d.
  `text` means the cached 8-K text names the new CUSIP.
- **1.03**: an 8-K item 1.03 within ±90 d. There is none in any of the 43.
- **FIGI new**: the cached OpenFIGI US composite of the new CUSIP, using the `ID_CUSIP`+`includeUnlistedEquities` job
  that `build_diagnosis_truth.py` used. `same` means it equals sec_id; `unc.` means not cached.
- **run holds**: another security of the run that holds the new line.
- **fires**: whether the proposed design (section 5) removes the false ending or fixes the identity. **match**:
  whether the truth row would then match with 5a alone, and if not, what blocks it.

| case | ticker | truth (shape/status) | old → new CUSIP | kind | gap | rename/filing | FIGI new | run holds | fires | match after 5a alone |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BBG000BLH3P8_2023-06-20 | HSC | no_ending | 415864107 same → NVRI | same CUSIP | 1 | rename 2023-06-02; 5.03 | same | – | yes | no: later 25-NSE 2026-06-01 |
| BBG000BN6349_2013-12-02 | FMD | ending_moved merger cash 5.05 USD | 320771108 → 320771207 | switch | 1 | 3.03/5.03 | same | – | yes | no: cash_currency (5f); lt 2016-08-22 (5d) |
| BBG000BRWGG9_2019-04-22 | RAD | ending_moved dropped/bankruptcy otc RADCQ | 767754104 → 767754872 | switch | 0 | 3.03/5.03 text | same | – | yes | no: price_ticker RADCQ (5g) |
| BBG000BTQ9G8_2017-08-02 | SVU | ending_moved merger cash 32.50 USD | 868536103 → 868536301 | switch | 0 | 3.03/5.03 | same | – | yes | no: cash_currency (5f) |
| BBG000C4MWH4_2023-07-05 | BGCP | ending exchange cont=true succ * | 05541T101 → 088929104 (BGC) | new CUSIP + new ticker | −1 | rename; 8-K12B text | unc. | – | yes (EDGAR tickers or 8-K12B text) | if R2 differs, yes; if same or none, no (the row vanishes) |
| BBG000C7WZ16_2010-10-15 | JNY | ending_moved merger cash 15 USD | 480074103 → 48020T101 | switch | 1 | rename; 5.03 text | same | – | yes | no: currency |
| BBG000C9N6Q9_2011-03-15 | ANN | ending_moved cash+stock ASNA | 036115103 → 035623107 | switch | 1 | rename; 5.03 text | same | – | yes | no: legs (5e/5f) |
| BBG000CL1HL7_2021-12-10 | CLI | no_ending | 554489104 same → VRE | same CUSIP | 4 | rename; 5.03 | same | – | yes | no: later 25-NSE 2026-05-27 |
| BBG000DZCFX4_2020-06-02 | LPI | no_ending | 516806106 → 516806205 (→VTLE 2023) | switch, then same CUSIP | 2 | 5.03 text | same | – | yes | no: later 25-NSE 2025-12-15 |
| BBG000GTYWL7_2026-01-18 | QGEN | no_ending | N72482206 → N72482156 (already attached) | Form 25 at switch | 0 | 25-NSE 2026-01-08 | same | – | yes (U6) | yes |
| BBG000J453J8_2019-05-12 | CCO | ending exchange cont=true lt blank | 18451C109 → 18453H106 | switch at Form 25 | 13 (0 from the 8-K12B) | 3.03; 8-K12B same CIK | BBG000SSC5C9 (differs) | – | yes (U7 successor) | no: truth lt blank, but the Form 25 notice gives 2019-05-01 (publishable): a truth defect (6.6) |
| BBG000Q02P20_2011-11-14 | MGI | no_ending | 60935Y109 → 60935Y208 | switch | 1 | 5.03 | same | – | yes | no: later 25-NSE 2023-06-01 |
| BBG001D9S707_2010-05-25 | DYN | ending exchange cont=true lt 2012-07-05 | 26817G102 → 26817G300 | switch | 1 | no 5.03; 8-K 2010-05-25 text says reverse split | BBG000BNLX91 (differs) | – | yes, if the reverse-split text counts | no: truth lt 2012-07-05 belongs to the other line (6.6) |
| BBG005PWSVQ3_2016-08-31 | WPG | no_ending | 92939N102 → 93964W108 | switch | 1 | rename; 5.03 | same | – | yes | no: Form 25 ×3 2021-09-20 |
| BBG006KY8KV2_2017-10-17 | TERP | ending_moved stock 0.47625 BEPC | 88104R100 → 88104R209 | switch | 2 | 3.03/5.03 text (with 5.01, 2.01) | same | – | yes (the old CIK keeps filing) | no: stock leg (5e/5f) |
| BBG009NGKQ45_2024-02-13 | VRM | ending_moved dropped otc VRMMQ | 92918V109 → 92918V208 | switch | 3 | 5.03 text | same | – | yes; must not take 92918V307 (2025, after the bankruptcy) | no: otc ticker/date (5g) |
| BBG00D30HGP6_2021-06-23 | CLNY | no_ending | 19626G108 → 25401T108 (DBRG) | new CUSIP + new ticker | −1 | rename; 5.03 text | none (no US line) | – | yes (EDGAR tickers or 8-K text) | yes, if the 2021-08-16 25-NSE is not the common's |
| BBG00JM9V731_2026-07-30 | GTES | no_ending | G39108108 → G39104107 | Form 25 at switch | 0 | rename; 3.03/5.03; 8-K12B | none (asked as ID_CUSIP) | – | yes (U6) | yes, if ID_CINS also gives none (6.5) |
| BBG00WYYC600_2017-11-09 | WLL | ending pass | 966387102 → 966387409 | switch | 0 | 5.03 text | BBG000PX3XC0 | BBG000PX3XC0 | must not change (held CUSIP) | stays pass |
| BBG00Z6DX554_2020-07-30 | EXE | ending known_wrong residual (R7) | 165167107 + 165167735, both already on one FIGI | – | – | – | – | – | must not change | stays residual |
| CIK1018005-COMMON_2012-10-01 | CWTR | ending_moved dropped otc CWTRQ | 193068103 → 193068202 | switch | 4 | 5.03 (−18 d) | unc. | – | yes | no: otc (5g) |
| CIK1019849-COMMON_2009-06-08 | UAG | no_ending | (none) → 70959W103 (PAG) | stale ticker | – | – | BBG000H6K1B0 | BBG000H6K1B0 (same CIK) | only with U4 | yes after the rename |
| CIK1056087-COMMON_2016-05-25 | MNI | ending_moved dropped otc MNIQQ | 579489105 → 579489303 | switch | 8 | 3.03/5.03 text | unc. | – | yes at N ≥ 8 | no: otc (5g) |
| CIK1066104-COMMON_2012-08-13 | EXBD | no_ending | 21988R102 same → CEB | same CUSIP | 1 | none | No identifier | – | yes (a same CUSIP needs no filing) | no: later 25-NSE 2017-04-05 |
| CIK1075415-COMMON_2020-01-07 | SNH | no_ending | 81721M109 → 25525P107 (DHC) | new CUSIP + new ticker | −2 | rename; 5.03 text | unc. | BBG000BM2GS0 (DHC, same CIK, no CUSIP) | yes (fold if the FIGI is BBG000BM2GS0) | yes after the rename |
| CIK1095651-COMMON_2013-12-19 | SFI | no_ending | 45031U101 same → STAR | same CUSIP | 1 | 8.01 2013-12-13 names STAR | No identifier | – | yes | no: later 25-NSE 2023-03-31 |
| CIK1115836-COMMON_2014-07-01 | OEH | no_ending | G67743107 → G1154H107 (→BEL) | switch, then same CUSIP | 0 | rename; 5.03 | unc. | – | yes | no: later 25-NSE 2019-04-17 |
| CIK1282266-COMMON_2015-04-27 | WIN | no_ending | 97382A101 → 97382A200 → 97382A309 | two switches | 2; 0 | 5.03 text (with a 2.01 spin-off) | unc. | – | yes | no: later 25-NSE 2019-04-02 |
| CIK1469372-CLASS-A_2015-10-02 | MSG | no_ending | 55826P100 → 553573106 (MSGN) | new ticker | 2 | rename; 5.03 | BBG000NS03H7 | BBG000NS03H7 (same CIK, class COMMON); 55825T103 under MSG is the new MSG (CIK 1636519) | only with the class wildcard U3b | no: class blocks it; MSGN's 2021 merger in any case |
| CIK1507934-CLASS-A_2013-01-16 | LMCA | no_ending | 530322106 → 85571Q102 (STRZA) | new ticker | 1 | rename; 5.03 | BBG000PCNTM2 | BBG000PCNTM2 (same CIK, COMMON); 531229102 under LMCA is new Liberty (CIK 1560385) | only with U3b | no: as MSG; Starz 2016 merger |
| CIK1606498-COMMON_2018-07-11 | HYH | no_ending | 40650V100 → 05350V106 (AVNS) | new CUSIP + new ticker | (−7) | rename; 5.03 (−28 d) | unc. | – | yes (EDGAR tickers AVNS) | no: later 25-NSE 2026-07-27 |
| CIK1723089-COMMON_2021-01-10 | APY | no_ending | 03755L104 → 15872M104 (CHX) | new CUSIP + new ticker | −1 | rename; 5.03 text names CHX | unc. | – | yes (symbol from the 8-K text only; EDGAR tickers are empty) | no: later 25-NSE 2025-07-16 |
| CIK1803737-COMMON_2022-06-30 | EHAB-WI | no_ending | – → 29332G102 (EHAB) | when-issued | – | 5.03/5.01 | BBG014QJ5BV6 | BBG014QJ5BV6 | yes (U8 -WI) | no: EHAB's 2026 merger |
| CIK1808220-CLASS-A_2022-11-17 | GOCO | no_ending | 38046W105 → 38046W204 | switch | 162 | 5.03 reverse split | unc. | – | **no**: fails gap 2022-11-17 → 2023-07-14 | no; later 25-NSE 2026-07-10 in any case |
| CIK20520-COMMON_2017-07-10 | FTR | ending_moved dropped otc FTRCQ | 35906A108 → 35906A306 | switch | 0 | 3.03/5.03 text | unc. | BBG010MVVVW7 (FYBR, the post-bankruptcy line: must not link) | yes | no: otc (5g); the rename may miss id_changes (6.9) |
| CIK23666-COMMON_2012-07-13 | SLE | no_ending | 803111103 → 432589109 (HSH) | new CUSIP + new ticker | −8 (settling tail) | rename; 3.03/5.03 text | BBG000BT4T69 | BBG000BT4T69 (same CIK) | yes (U2 timing) | no: HSH's 2014 merger |
| CIK352363-COMMON_2012-05-14 | LIZ | no_ending | 539320101 → 316645100 (FNP) → 485865109 (KATE) | new CUSIP + new ticker | 1 | rename; 5.03 text | 316645100 unc.; KATE BBG000C4WJT9 | BBG000C4WJT9 (KATE) | yes (8-K text CUSIP) | no: KATE's 2017 merger |
| CIK708819-COMMON_2018-05-08 | MDR | no_ending | 580037109 → 580037703 | switch | 4 | 3.03/5.03 (2.01 as acquirer) | unc. | – | yes (the old CIK keeps filing) | no: 2020 bankruptcy 25-NSE |
| CIK716006-COMMON_2010-10-04 | YRCW | no_ending | 984249102 → 984249300 (YRCWD 20 d) | switch (T+D) | 1 | 5.03 | unc. | – | yes with T+D | no: 2023 bankruptcy 25-NSE |
| CIK733269-COMMON_2018-09-30 | ACXM | no_ending | 005125109 → 53815P108 (RAMP) | new CUSIP + new ticker at Form 25 | −1 | renames; 8-K12B ×2; 25 2018-10-01 | unc. | – | yes (EDGAR tickers RAMP + U6) | yes, if R2 is same or none |
| CIK88205-COMMON_2015-09-28 | SPW | no_ending | 784635104 same → SPXC | same CUSIP, placeholder duplicate | 1 | none | no US line | BBG000BTGCV5 (same CUSIP, same CIK) | yes (U3) | yes after the rename |
| CIK910073-COMMON_2024-07-12 | NYCB | no_ending | 649445103 → 649445400 (→FLG) | switch, then same CUSIP | 0 | 3.03/5.03 | unc. | – | yes | no: later 25-NSE 2025-10-20 |
| CIK931336-COMMON_2013-08-26 | DF | ending_moved dropped otc DFODQ | 242370104 → 242370203 | switch | 1 | 5.03 (−11 d) | unc. | – | yes | no: otc (5g) |

Tally:

- **The design fires on 37 of 43.** It does not fire on GOCO (fails gap), MSG and LMCA (class), UAG (needs the optional
  U4), EXE (must not change) and WLL (already pass).
- **The rule as literally specified** (same ticker or same CUSIP, a filing, no 1.03, fold on the same
  issuer/class/CUSIP, -WI) fires on about 24: 19 same-ticker switches, HSC, CLI, SFI, the SPW fold, and EHAB-WI.
  It misses:
  - the 8 new-CUSIP-plus-new-ticker cases (BGCP, CLNY, SNH, HYH, APY, ACXM, LIZ, SLE);
  - the 3 Form 25 paths (QGEN, GTES, CCO);
  - DYN (no 5.03, only reverse-split text);
  - EXBD (a same-CUSIP rename that no filing states).
- **Truth rows that fully match after 5a alone:** about 7 (QGEN, GTES, CLNY, SNH, SPW, ACXM, plus BGCP if R2 differs),
  plus UAG with U4.
  - 20 rows are blocked only by truth `no_ending` vs a later real ending of the followed line (6.1).
  - 11 `ending_moved` rows wait on 5d/5e/5f/5g for the later ending's fields.
  - CCO and DYN are truth-build defects (6.6).
  - GOCO, MSG and LMCA need more than 5a.

## 3. Guard cases (must not change)

| Guard | Cached evidence | Signal that would wrongly fire | What stops it |
| --- | --- | --- | --- |
| UAL 2006 emergence (CIK 100517) | 902549500 under UALAQ (OTC) to 2006-02-16; new 902549807 under UAUA from 2006-02-07; 8-K 1.03 2006-01-23 (plan); 8-K 2006-02-01 with 5.03; 8-A12B and 15-12B on 2006-02-01 | same CIK, a new CUSIP within days, an 8-K 5.03, a matching description ("UAL CORP") | the 8-K 1.03 within [−180, +30] d of the new first row; the old symbol is OTC-like (5 letters ending in Q); different tickers, so no same-ticker switch. The run's FTD window opens 2007-12-17 and observations start 2008, so the 2006 line is not in this run: a unit test must pin it. The 2010 rename UAUA (CIK100517-COMMON placeholder, no ending today) → UAL 910047109 (BBG000M65M61, same CIK) **will fold**: a 1:1 rename, which is correct, but it shows as a regression |
| Post-bankruptcy equity (VRM 2025, DYN 2012, FTR→FYBR 2021, CHK→EXE 2021, WIN/MDR) | VRM: 92918V208 under VRM to 2024-12-02, VRMMQ, then 92918V307 under VRM from 2025-02-21 (256 trading days). DYN: DYNIQ, then 26817R108 from 2012-10-03. FTR: FTRCQ, then FYBR 35909D109 2021 (held by BBG010MVVVW7) | same CIK, the same ticker reused, a matching name | the gap is far over N; the 8-K 1.03 is in the window; the OTC symbol (…Q) is never a line ticker, so the old line's last live row is the pre-OTC one; a CUSIP another run security holds is never attached |
| A ticker passed to another issuer: new LMCA 2013, new MSG 2015 | LMCA: 531229102 under LMCAD/LMCA from 2013-01-17, held by BBG003P9ZSL3 (CIK 1560385); desc "LIBERTY MEDIA CORP DELAWARE CL". MSG: 55825T103 under MSG from 2015-10-05, held by BBG007FG0C23 (CIK 1636519); desc "MADISON SQUARE GARDEN CO NEW" | same ticker, a new CUSIP within 1–2 trading days, an 8-K 5.03, and a description that matches a **former** name (1507934 was "Liberty Media Corp" until 2013-01-11; 1469372 was "Madison Square Garden Co" until 2015-09-28) | (a) the new CUSIP is held by another run security of another CIK, so it is never attached; (b) when not in the run, the description must name a name **in force from the new first row on** (`names_between(sub, first, first+30)`). LMCA's former name ended 6 days earlier, so this test is fragile: never widen it backward |
| A spin-off on a new CUSIP (AAN 2020, WIN 2015, GOOG 2014) | GOOG: 38259P508 continues under GOOGL (same CUSIP, 2014-04-07) while class C 38259P706 takes GOOG. AAN: the parent's 00258R109 continues as PRG 74319R101, and the spin-off 00258W108 takes AAN | same ticker, a new CUSIP, a matching name ("AARON'S" names both) | the old CUSIP keeps trading under another live symbol past `SWITCH_TAIL_DAYS`: take the same-CUSIP step, never the switch (reuse `cusip_handoffs`' tail rule, 359-361); a class-letter conflict (CL C vs CL A). AAN also has a Form 25 merger ending |
| Two classes of one issuer (MSG A/B) | the run has no MSG class B line; Discovery A/C, Liberty LMCA/LMCK and GOOG/GOOGL are | a fold or attach across classes | the existing group test (`_handoff_joins` 429-433, same CIK **and** class). A class wildcard (U3b) is allowed only when the issuer's eras in the run name at most one class letter |
| R1 merger with a kept composite (UNIT 2025, outside 5a) | 912932100 under UNIT from 2025-08-04, OpenFIGI **same** composite BBG002B67HB2; old CIK 1620280 "Uniti Group LLC" filed 15-12G 2025-08-04 and no 10-Q after | R2 says one security, against R1 (0.6029 is a merger) | **new guard**: the old CIK must keep filing 10-K/10-Q/20-F/40-F after the switch, or the switch must be the CIK's own 8-K12B; no 8-K12B/12G3 by **another** CIK naming the old issuer in [−30, +60] d (`successor_query`, cached by stage 9). This also stops BXS 2017 (the holdco merged into a bank that files with the FDIC) and SBGI 2023/NRF 2014 (new-CIK holdcos: stage 9 / 5c). It must not stop TERP or MDR: both CIKs kept filing |

## 4. Blast radius (whole run, cached fails rows)

Method: `r5a_blast.py` and `r5a_blast_n.py`. For each security whose ticker_history ends, start at the last CUSIP's
last row under the security's tickers:

- a **switch**: another CUSIP with no earlier row (from last − 5 trading days on), first under T, T+ZZZZ or T+D;
- a **same-CUSIP** step: the same CUSIP's first row under another live symbol.

Guards applied:

- the issuer's in-force names, word by word (`description_names`);
- no 8-K 1.03 in [−90, +30] d;
- a 5.03/3.03/8-K12B/rename within the window, for a switch;
- a letters-only, not OTC-like symbol, for a same-CUSIP step;
- a new CUSIP another security holds counts only when that security has the same CIK.

The counts move little with N:

| N (trading days) | securities with a step | in the truth set | outside: Form 25 ending (already linked) | outside: no-Form-25 ending (already linked) | outside: no ending |
| --- | --- | --- | --- | --- | --- |
| 5 | 80 | 58 | 16 (10) | 5 (3) | 1 |
| 10 | 81 | 59 | 16 (10) | 5 (3) | 1 |
| 30 | 83 | 60 | 17 (11) | 5 (3) | 1 |

Outside the truth set at N=10 (22), with the design's extra guards:

- **No change (10).** FIGI lines already linked to the successor that holds the new CUSIP: AON 2020, CR, J, S, OI, MNST,
  NLSN, ST, APTV, LIN. The new CUSIP is held, so it is never attached.
- **Refused (4).**
  - WCN 2016 and BXS 2017: the old registrant merged out. Expected; the filings after each switch are not checked.
  - AAN: the old CUSIP trades on.
  - TSP: Form 25 + OTC TSPH.
- **Placeholder folds into a same-CIK FIGI line that today is its continuation successor (3).** CBG 2011, WCRX 2009,
  AON 2012. This is consistent with the SLE truth ruling.
- **Endings removed (2).** QRTEA→QVCGA 2025, RLGY→HOUS 2022 (same CUSIP, no Form 25).
- **History only (1).** TWO 2022 (closed_no_event: its history extends).
- **Rename plus CUSIP history (2).** ACI, CIE (placeholder + reverse split before a Form 25 bankruptcy).
- **Also, new CUSIP + new ticker renames (8) if the EDGAR-tickers / 8-K-text source is built.** These are outside-truth
  no-Form-25 endings with `Ticker change / listing transfer: renamed from …`: KFT 2012, WPO 2013, AABA 2017, DSW 2019,
  HPT 2019, CECO 2020, XON 2020, GDI 2020.

**About 16 outside-truth regressions for the loop** (8 from fails-row steps and 8 renames), roughly 10 of them folds or
renames, so N1 matters. Run-wide, 96 last endings carry `no_form25`: 77 in the truth set, 19 outside. The fails-row
steps reach 58 of the 96.

The follow also reaches **16 truth cases of other sub-plans**: TMA, CCE, SDRL, ODP, WFT, SBGI, AWH, BLUE, EGL, UNIT,
GCI, ASNA, ESV ×2, FST, SPNV.

- **Expected to be refused by the guards (about 10).** Verified for UNIT and SBGI (`r5a_after.py`); the others are
  not verified one by one.
  - an OTC symbol: WFT's WFTIF, AWH's AWHHF;
  - a Form 25 or 3.01 near a same-CUSIP symbol change: TMA, FST;
  - a 1.03: SDRL;
  - the old registrant merged out, or another CIK's 8-K12B: CCE, ODP, SBGI, UNIT, GCI.
- **CUSIP and ticker history only (3).** BLUE, ASNA, SPNV.
- **May change a contract field (3).** ESV 2009, ESV 2019 and EGL. The loop's mismatch mode re-judges them, with
  every case above that a guard does not stop.

## 5. Design proposal

### 5.1 Units, in pipeline order

**U8 (stage 0, observations).** A when-issued ticker joins its regular line. `observations.normalize_ticker`
(observations.py:37-38), or `split_eras` (203), strips a `-WI` / `.WI` / ` WI` suffix and keeps the name.
EHAB-WI@2022-06-30 then joins EHAB's line through the fails rows (EHAB from 2022-07-06) and resolves to BBG014QJ5BV6.
Test: one observation `EHAB-WI` (name "ENHABIT INC WHEN ISSUED") plus `EHAB` rows and its FIGI gives one security,
with no placeholder.

**U2 (stage 3, `security_master.cusip_handoffs`).**

- `last` = the old CUSIP's last row before its settling tail: the trailing rows at one price after its last price
  change, the same idea as `_continues_after`'s two-prices rule.
- The window is [last − `SWITCH_DAYS`, last + `SWITCH_DAYS`].

The SLE→HSH link then forms, and `_handoff_joins` folds the SLE placeholder into BBG000BT4T69. Feeds
`infer_issuers` too, so add a regression test that the KORS/CPRI, NU/ES fixtures in `tests/test_figi_handoff.py` and
`test_resolver_renamed.py` are unchanged.

**U3 (stage 3, `_handoff_joins`).**

- Pass `picks` in.
- A `shared_cusip` link may also reach an era whose pick is non-weak (`picks[k][3]` False, source ticker or name).
  This adds to `confirmed`.
- `_contradicted` is still applied.
- Fixes SPW → BBG000BTGCV5.
- U3b (optional, MSG and LMCA): in the group test, `COMMON` matches a lettered class when the issuer's eras in the run
  name at most one class letter. Also needs `id_change_rows` to accept the class pair (6.9).

**U4 (optional, stage 3, `unconfirmed_eras`/`guarded_eras`).**

- Signature `(eras, ftd, issuers=None)`.
- A row confirms the ticker only if `description_matches(desc, era.names + issuer names)`.
- Fixes UAG → BBG000H6K1B0 through `backfill_line`.
- Unmeasured blast: it changes which eras skip the ticker and name tiers. Measure before adopting.

**U1 (new stage 4b, `pipeline._follow_lines`, called right after `_security_cusips` and before `_find_delistings`).**
New pure module `line_follow.py`, beside `handoffs.py`:

```python
@dataclass(frozen=True)
class LineStep:
    sec_id: str
    kind: str              # "cusip_switch" | "new_symbol"
    old_cusip: str
    new_cusip: str         # == old_cusip for "new_symbol"
    symbol: str            # the ticker the new rows trade under
    old_last: str          # the old CUSIP's last live row under the line's tickers (settling tail dropped)
    first: str             # the new rows' first row (a ...ZZZZ day counts for the date, not as a ticker)
    evidence: str          # "8-K 5.03 2013-12-02" | "renamed from X 2010-10-18" | "8-K12B 2019-05-02" | "same CUSIP"
    composite: str | None  # OpenFIGI's one US composite for new_cusip; None = no US line

def candidate_steps(cusips: Sequence[str], tickers: Collection[str], ftd: FtdIndex, *,
                    held: Collection[str], days: int = LINE_DAYS) -> list[LineStep]: ...
    # pure, fails rows only. A switch: a CUSIP not in `held`, with no row before old_last - 10 trading days,
    # first under T / T+"ZZZZ" / T+"D" within [old_last - 10, old_last + days]; refused when the old CUSIP trades
    # on (cusip_handoffs' SWITCH_TAIL_DAYS rule). A new symbol: the old CUSIP under a symbol that is letters only,
    # not ...XXXX/...ZZZZ, not 5 letters ending in Q/F/Y, not T+"Q", within days.
def extra_symbols(sub: dict, texts: Iterable[str], run_tickers_of_cik: Collection[str]) -> set[str]: ...
def named_cusips(texts: Iterable[str]) -> set[str]: ...
    # the new-ticker sources: EDGAR submissions "tickers" today; the run's other securities of the CIK and class;
    # symbols and CUSIPs the old CIK's 8-K 5.03/3.03/8.01/8-K12B text (±30 d) names
def corroborate(step: LineStep, filings: Sequence[EdgarSubmission], sub: dict, *, texts: Mapping[str, str],
                other_registrant: bool) -> str | None: ...
    # None = refused. Needs (switch and new-ticker kinds): 5.03/3.03 or a same-CIK 8-K12B/12G3 within ±30 d, a
    # formerNames rename within ±90 d, or an 8-K text in ±30 d saying "reverse split" / naming new_cusip.
    # Refuses: an 8-K 1.03 in [first - 180, first + 30] d; for "new_symbol" a 3.01 or a Form 25 in ±30 d (an OTC
    # move); the new rows' descriptions not naming (`description_names`) a name in force on [first, first + 30];
    # a class letter in them that conflicts with the security's; the old CIK filing no 10-K/10-Q/20-F/40-F after
    # `first` unless the evidence is its own 8-K12B; `other_registrant` (an 8-K12B/12G3 by another CIK naming
    # the old issuer in [-30, +60] d, from `successor_query`).
def decide(step: LineStep, sec: Security, run: Mapping[str, Security]) -> str: ...
    # R2: "attach" (composite == sec_id, or None); "fold:<X>" (sec is a placeholder and X is no other-CIK
    # security's); "successor:<X>" (sec is a FIGI line and X != sec_id); "unsettled" (more than one US composite)
```

The stage, `_follow_lines(ctx, securities, resolutions, sec_cusips, ftd, answers) -> _Lines`, loops at most 3 rounds,
for chains like WIN ×2, LPI→VTLE, OEH→BEL, CLNY's 2022 reverse split and LIZ→FNP→KATE:

1. `candidate_steps` per security with an issuer CIK.
2. `ftd.extend(client, lo, as_of, symbols=extra_symbols ∪ era tickers, cusips=new CUSIPs)`, one scan.
3. One batched `clients.figi.map([security_master._cusip_job(c) …])`, with the same job shape as `resolve_many` so the
   cache is shared; then `figi_resolution.us_candidates`.
4. `corroborate`, then `decide`:
   - **attach**: append the CUSIP to `sec_cusips[sid]`, and the symbol to `line_tickers[sid]`;
   - **fold or rename**: re-point the placeholder's eras' `EraResolution` to X (source `handoff`, CUSIPs added), then
     rebuild with `build_securities`;
   - **successor**: record `(sid, X, new_cusip, symbol, first)` in `_Lines.successors`, and stop following that line.
5. Review items: `line_followed` (info) and `line_follow_refused:<why>` (check), in `review_triage.CATALOG`.

It returns sec_cusips, line_tickers, the exact renames `{placeholder: X}` and the successors. Order in `_run`
(pipeline.py:1400-1404): after `_security_cusips`; `securities`/`resolutions` are replaced by the stage's output.

**U5 (stage 5, own tickers).** Give `Security` a field `line_tickers: frozenset[str] = frozenset()`, set by 4b.
A helper `own_tickers(s)` = era tickers ∪ line_tickers replaces `{e.ticker for e in s.eras}` at:

- history.py:143;
- pipeline.py:186, 444, 500, 551, 865, 1092;
- the finder's `ticker_last` (delistings.py:282), which becomes the line's latest ticker (the last sighting's value).

`listed_today(..., tickers=)` gets them too, which matters for a placeholder.

**U6 (stage 5, a Form 25 at the line's own switch).**

- `SecurityContext.cusip_switches: tuple[str, ...]` holds the first-row dates of each attached CUSIP after the
  security's first. It comes from `cusip_sightings` in `_context_builder`, which needs `ftd` and `sec_cusips`.
- In the main loop (delistings.py:346-353), when `continued` and a switch lies within 5 trading days of
  `sub.filing_date`, `continue`. Fixes QGEN, GTES and ACXM's 2018-10-01 Form 25.
- A same-CUSIP symbol change at a Form 25 is never skipped (TSP).

**U7 (stage 9, successors).**

- `_find_successors` (pipeline.py:828-887) first checks `_Lines.successors`. For a delisting with `successor_unknown`
  whose security has a line successor with `first` in [last trade − 5, + 15] d: link X.
- When X is not a run security, build an `AddedSuccessor(Security(X, cik, class, name, type, False, "cusip"), symbol,
  first)`. Never materialize one for an ending that does not need it (WCN, AAN).
- Fixes CCO and DYN (and BGCP if its R2 differs). WLL is unchanged (held CUSIP, link already found in run).

### 5.2 How R2 is checked

At stage 4b: `clients.figi.map` with `security_master._cusip_job(c)` (pipeline OpenFIGI client, disk cache
`cache/openfigi/`, exit 4 on outage as everywhere else). The US composites from `us_candidates`:

| composites | decision |
| --- | --- |
| none | one security (attach; a placeholder stays a placeholder) |
| one, equal to sec_id | attach |
| one, different, and sec_id a FIGI | successor (U7) |
| one, and sec_id a placeholder | fold or rename to X, refused when another-CIK security holds X |
| several | unsettled: no follow, and a review flag |

18 of the cases' new CUSIPs are not cached: BGCP, GTES (as CINS), MNI, SNH, HYH, APY, GOCO, FTR, LIZ's FNP, MDR,
YRCW, ACXM, NYCB, DF, WIN ×2, CWTR, OEH. The first full run asks OpenFIGI for about 40 to 60 new CUSIPs run-wide;
the OpenFIGI host is already allowed.

### 5.3 Tests (offline)

Doubles already in the repo:

- `tests/conftest.py` `_FakeEdgar`: `submissions_by_cik` (EdgarSubmission list, with 8-K `items`), `texts`, `raws`,
  `former_names` ((name, from, to) → formerNames), `listings` (tickers today), `company_map`.
- `tests/test_pipeline.py:1416-1452`: `_RowsFtdClient` (in-memory `FtdRow`s, filtered like the real client), `_MapFigi`
  (answers by `(idType, idValue)`), `_index_clients`, `_ftd(symbol, cusip, desc, dates, price)`, `_figi_answer`.
- `tests/test_figi_handoff.py` `_Figi`/`_RowsClient`, over `tests/fixtures/eras/renamed_*`.

A CUSIP-switch scenario is: observations of `RS` ending in 2009; rows `RS 11111A101` to 2012-10-01 and
`RSZZZZ/RS 11111A200` from 2012-10-02 (two prices); FakeEdgar 8-K `items="5.03,9.01"` on 2012-10-01, 10-Qs after, a
25-NSE in 2013 with a raw EX-99.25; `_MapFigi` answers for both CUSIPs.

Pure unit tests (`tests/test_line_follow.py`):

- a switch with a ZZZZ first day;
- a same-CUSIP rename;
- T+D (YRCW);
- a settling tail (SLE);
- a gap over N (GOCO) and a post-bankruptcy relist (VRM 2025): none;
- OTC symbols RADCQ and WFTIF, and `…XXXX`, `P105PS`: none;
- a held CUSIP (WLL, NRF): none;
- the old CUSIP trading on (GOOG/AAN): the same-CUSIP step only;
- `corroborate`:
  - 5.03 accepts; a rename accepts;
  - reverse-split text accepts (DYN);
  - 1.03 refuses (UAL 2006);
  - merged out refuses (UNIT: 15-12G, no 10-Q);
  - an other-CIK 8-K12B refuses (SBGI);
  - a former-name-only description refuses (new LMCA/new MSG);
  - a class letter conflict refuses;
- `decide` (all five R2 branches).

Pipeline tests (`tests/test_pipeline.py`):

1. A reverse split after the observations stop gives one sec_id, two cusip_history rows, ticker_history to the 2013
   Form 25, and only the 2013 delisting.
2. R2 differs: the old security ends at the switch, `successor_sec_id` = X (AddedSuccessor), and contract
   continuation true.
3. A same-CUSIP rename: ticker_history gains the new ticker and there is no ending.
4. A placeholder fold (SLE-like via U2, SPW-like via U3): one security, and `contract/id_changes.csv` lists it.
5. QGEN-like: a 25-NSE at a same-composite switch while listed gives no contract row.
6. The guards: UAL 2006; a takeover (another era of another CIK holds the new CUSIP under the ticker); a spin-off; two
   classes; UNIT-like merged out. Each one is unchanged.

Fixtures for the real cases: a new `tests/fixtures/lines/` set built once from the cache, in the shape of
`tests/fixtures/eras/renamed_*`. It holds fails rows for FMD, HSC, SLE/HSH, SPW/SPXC, QGEN, CCO, UAL, LMCA/new LMCA,
MSG/new MSG/MSGN, AAN, UNIT and GOOG; submissions slices; and OpenFIGI answers. The builder can reuse
`r5a_replay.py`'s local FTD client. The 31-case golden replay and the floor test must stay green.

### 5.4 N1: a folded placeholder outside the truth set

`regression.diff_contract` (regression.py:177-203) gains `renames: Sequence[Mapping[str, str]] = ()`, the id_changes
rows `build_report` already computes (115-123). Before diffing:

1. Re-key the base snapshot: a renamed placeholder P's delistings row becomes F's base row when F had none (F's own row
   wins otherwise), and P's ranges join F's.
2. Emit one row `(F, "id_changes", "sec_id", "renamed", P, F)` in place of `(P, …, removed)` and `(P, id_changes,
   added)`.

A placeholder that only moved its ending to F then shows as F's real changes. `excluded` (147-159) is unchanged.

`truth_update.apply_round` (truth_update.py:122-198) gains `run_sec_ids: Collection[str] | None = None` and
`renamed: Collection[str] = ()`. In the regression branch (150-152) it skips the truth row (the ledger rows are
still written) when `sec not in run_sec_ids` or `sec in renamed`. `scripts/update_truth.py` passes
`{r["sec_id"] for r in tables.securities}` and the old ids of `regression.id_changes_since(...)`.

Tests:

- `test_regression.py`:
  - a folded placeholder is one `renamed` row under its FIGI;
  - a folded placeholder whose ending changed shows the change under F;
  - a rename into a truth security is still excluded.
- `test_truth_update.py`:
  - a regression of a sec_id not in the run adds no truth row and is settled in the ledger;
  - a renamed placeholder adds no truth row.
- a script test: `update_truth.py` passes the run's securities.

`diagnosis_loop._field_name` already gives `id_changes.sec_id`.

## 6. Spec rules that are unsafe or underspecified

1. **Truth `no_ending` vs the followed line's later ending (the largest risk).** 20 of the 27 `no_ending` rows in 5a
   are lines whose issuer's cached filing list holds a later Form 25: HSC, CLI, LPI, MGI, WPG, EXBD, SFI, OEH, WIN,
   MSG, LMCA, HYH, APY, EHAB-WI, GOCO, SLE, LIZ, MDR, YRCW, NYCB. Following the line correctly makes that ending the
   contract row, and the judge reports `shape` (diagnosis_truth.py:314-316). `update_truth` sends a shape verdict to
   `ruling_pending` (truth_update.py:17-18, 189-192), so all 20 land on the operator. Recommend an operator ruling
   before the 5a loop: re-shape them to `ending_moved` with every field `*`. That shape passes as soon as the last
   ending is not the old event (318-324).
2. **R2 for a placeholder is undefined.** The old line has no composite. The truth (SLE, LIZ, UAG, SPW, SNH, MSG, LMCA,
   EHAB-WI) assumes a fold into the new CUSIP's composite, which is the existing `_handoff_joins` behaviour. The other
   reading ("differs", so a continuation) is what the library does for SLE today. Folding also turns CBG, WCRX and
   AON 2012 (outside truth) from continuations into one security. The operator should confirm the reading.
3. **R1 beats R2.** UNIT 2025 keeps its composite across a 0.6029 merger (and BXS 2017 across a holdco-into-bank
   merger). The "old registrant carries on" guard (section 3) is required; it is not in the spec.
4. **"Under the same ticker" is too narrow.** 8 cases (BGCP, CLNY, SNH, HYH, APY, ACXM, LIZ, SLE) change ticker and
   CUSIP together. They need the EDGAR-tickers, run-siblings and 8-K text sources (U1). APY and LIZ have only the 8-K
   text, since their EDGAR tickers list is empty.
5. **CINS job shape.** `build_diagnosis_truth.py:38` asks `ID_CUSIP` for every new CUSIP; the library's `_cusip_job`
   asks `ID_CINS` for a letter-first CUSIP. GTES's "no FIGI" answer is cached only as ID_CUSIP, and G39104107
   (GTES), G1154H107 (OEH) and N72482156 (QGEN) can answer differently. Truth_build also skips R2 for every placeholder
   (truth_build.py:44: `startswith("BBG")`), so the 19 placeholder cases that name a new CUSIP were never R2-checked.
6. **Truth-build defects from the R2 override** (truth_build.py:52-56, which does not reset `last_trade_date`/
   `internal_last_trade_date`):
   - DYN keeps 2012-07-05, the other line's bankruptcy date, on a 2010 continuation. It should be blank, with internal
     2010-05-25.
   - CCO is blank, but its Form 25 EX-99.25 gives 2019-05-01 (`ex99_notice`, publishable). BGCP's continuation keeps
     its MIDAS date, so the two rules disagree.
7. **The windows are unstated.** "Within days": the data say 0–4 trading days typically, MNI 8, CCO 13 from the old
   last row (0 from its 8-K12B), the settling-tail overlap down to −8 (SLE), GOCO 162. Proposed: [old live last − 10,
   + 10] trading days. "No 1.03 in the window": proposed [first − 180, first + 30] d. Blast is flat across N=5…30.
8. **The fold condition "same issuer, class and CUSIP"** misses UAG (no CUSIP; needs U4) and MSG/LMCA (CLASS-A vs
   COMMON; needs U3b). The spec's own guard "two classes (MSG A and B)" pulls against U3b, so it may stay residual.
9. **`contract.id_change_rows` (contract.py:109-128)** renames only when exactly one FIGI security holds the
   placeholder's (CIK, class). FTR's CIK 20520 also has FYBR BBG010MVVVW7, so if 4b renames the FTR placeholder, no
   id_changes row appears and the truth row is judged by `D.mismatches.sec_id`. The class mismatch blocks MSG/LMCA
   the same way. Pass 4b's exact renames to `id_change_rows`.
10. **Fails-file symbols the rule must know:**
    - `T+ZZZZ`: a new CUSIP's first day, often at $0.01/$1.00.
    - `T+D`: Nasdaq's post-split suffix (YRCWD 2010-10-05..28, LMCAD).
    - CUSIP-tail symbols after a merger: `P105PS`, `4107PS`, `F113PS`, `J106SC`.
    - OTC suffixes: …Q, …F, …Y.
11. **Cost.**
    - One extra symbol scan of the fails zips per follow round: about 50 s CPU; the full aggregate here took 46 s CPU.
    - About one 8-K text per candidate without item-code evidence.
    - About 40–60 OpenFIGI jobs on the first run.
    - Successor full-text searches are reused from stage 9's cache.
12. **The "old registrant carries on" guard has a timing edge.** A switch within about 120 d of the run date may have
    no later 10-Q yet. Count "listed today" (or the CIK's own 8-K12B) as carrying on there, or such a switch is
    refused and falls back to today's behaviour.
13. **Unreachable in 5a:** GOCO (an 8-month fails gap; only a filing-stated reverse split plus "the next CUSIP under the
    ticker, however late" would reach it, which is risky); EXE (R7 residual).

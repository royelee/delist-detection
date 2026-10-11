# missing-securities: cases/3_securities_in_one_run_only.csv (51)
Evidence files here: trace2.txt (per ticker timelines F vs S), eras.py (+eras_*.json: refine_eras output of both runs, reproduces 2468/2659 and 2442/2497),
obsS/F*.csv + outS/F* + run*.log (small reruns), obsP.csv/outP (one-row-added demo).

## Mechanisms
M1 new line/era after the first seed is never created. identity.py:406-422 _split_era: the CUSIP-switch (and gap) cut makes parts; `if not obs: continue` (identity.py:410) drops a part with no observation, with its CUSIP. Seeds keep one row per ticker while the name "agrees" (names_agree), so the part after a CUSIP switch has no observation. Full has observations there -> own era -> own FIGI/security, and also the CUSIP-switch handoff that lets the earlier era join a FIGI (security_master.py:134 cusip_handoffs, :250 _handoff_joins, log "FIGI handoff").
  Reproduced: adding ONE row (ARRS 2016-06-30, STE 2019-06-30) to the seeds creates BBG00928YVY7 and BBG00MRHG523 (outP). Subset reruns F vs S: ARRS, CIT, STE, WEN, ITT, TMA, ABI, IVGN, BSC, CCU, RRI/GEN, MDR(partly M2).
M2 issuer lookup date. identity.py:256 resolver.resolve(ticker, last_seen,...) with last_seen = era_last_seen (identity.py:543: last obs or FTD row within 400 days). Seeds era last = first seed -> anchor ~2009-02; full -> anchor 2010-07. The resolver answer is keyed by date and name; cache shows ANN@2009-02-18 -> 811211 (efts_name_mismatch) vs ANN@2010-07-13 -> 874214; GGP@2009-02-19 -> 811696 vs @2010-07-13 -> 895648; DISH@2009-02-19 -> 1350031 (EchoStar) vs full: miss, then second pass infers 1001082 (second pass only overrides misses, so seeds' wrong first-pass answer stands, flagged issuer_cusip_disagrees); CCE and MDR: seeds date/name gives a miss (unresolved), full gives CIK. Also IVGN (S 77551 Applera, wrong).
  Sub-case ABBI: identity.py:623/668 _name_in_force looks at [era.first, last_seen]; full replaces 1141399 by 1409012 (log "name checks: ABBI@2008-01-16 -> 1409012"), seeds does not (single-day window). Reproduced on ABBI subset (F2 vs S2).
  Reproduced by subset rerun: ANN, GGP, ABBI, CCE(2008), DISH, IVGN, MDR.
M3 share-class letter taken from the era's LATEST name. security_master.py:283 group(key) = (issuer cik, share_class_from_name(era.name)); era.name = last observation's name (observations.py:129); :288 linked() needs equal groups. CBS: seeds name "CBS CORPORATION" -> COMMON, PARA "...CLASS B" -> link refused; full latest name "CBS CORP CLASS B" -> CLASS B -> joins PARA line (log). Opposite direction: CBG and WCRX: full has later names "CBRE GROUP INC CLASS A" / "WARNER CHILCOTT PLC CLASS A" (COMMON vs CLASS A) -> link refused -> F keeps a placeholder; seeds (only unlettered names) links. share_class_from_name checked directly. CBG reproduced by subset (S2 handoff, F2 placeholder). WCRX reproduced as outcome (S2 FIGI via handoff, F2 placeholder), S-side link target not identified. CBS in subset was not reproduced (needs PARA era; full universe), from code+log only.
M4 foreign-ticker window. security_master.py:715 _confirm_window (era.first-30d, era.last+30d), :730 foreign_ticker_eras, :410-426 backfill_line. UAG: fails rows under UAG are UBS E-TRACS notes from 2008-09. Full era runs to 2009-06-08 -> sees them -> `foreign` -> placed on Penske's line by cusip_span (BBG000H6K1B0). Seeds era (one day) sees none -> merely unconfirmed; backfill needs an observed era of the line overlapping the dates (PAG observed from 2014 only) -> placeholder CIK1019849. Reproduced (F2 vs S2, with PAG, LAD rows).
M5 (consequence of M1) stale or wrong ticker-tier picks survive because the confirming later era is missing. Z: seeds keeps ticker pick BBG009NRSWJ4 (Class C); full withdraws it ("FIGI ticker pick withdrawn: Z@2014-06-30 ...", resolve_with_identity_guard, security_master.py:611) because Z@2015-06-30 is confirmed on BBG000D13GN8, leaving placeholder. ITT: seeds ITT@2008 takes BBG00CVQZQ96 (ticker), full has ITT@2012 era on BBG000BMB7R1 -> pick withdrawn. Reproduced in subset for ITT; Z from logs/data.
M6 acquirer securities (observed=false), not identity. FORTIS (ITC acquirer) and CRESCENT (VTLE acquirer) exist only because the ITC and VTLE endings exist in full (seeds: ITC ended_without_delisting; VTLE absent) -> consequence of other groups' lost endings. COMPASS (HOUS acquirer): the HOUS ending exists only in seeds (full: ended_without_delisting). REVELYST (VSTO acquirer): both runs have the VSTO ending, same LLM cache answer (acquirer "Revelyst", ticker null); seeds finds the acquirer line (no "acquirer names" stage line, i.e. todo empty), full does not (full logs "acquirer names: 1 of 2", VSTO gets terms_gate_failed:fail_sanity, merger_at_par). Cause not traced (terms stage 8a/8a', acquirer_line.issuer_by_name over the run's issuers, merger_value.py:~405) -> unexplained.

## Case table (V = verified by rerun/code+data, S = assigned by similarity or log only)
full_only
BBG000K9SSS5 FORTIS M6 V(data) | BBG013THLHZ4 CRESCENT M6 V(data)
CIK1409012 ABBI M2 V | ABI BBG000FJJW82 M1 V | AGN BBG000FH8PX5 M1 V(eras+log: ACT joins via AGN@2015 era; S has no AGN@2015 era)
ANN BBG000C9N6Q9 M2 V | ARRS M1 V | BG M1 V(eras: no BG@2023-12-31 era in S) | BSC CIK777001 M1 V
CBG CIK1138118 M3 V | CCE BBG000BF5RY1 M1 V(eras) | CCE CIK804055 M2 V | CCU CIK739708 M1 V | CIT M1 V
CR M1 V(eras) | DTV M1 V(eras) | ENDP M1 V(eras) | EVHC M1 V(eras) | FWONA M1 V(eras) | FWONK M1 S
GCI M1 V(eras) | GEN BBG000BDB3H1 (RRI) M1 V | GGP CIK895648 M2 V | HTZ BBG00D1WHZD9 M1 V(eras)
IGT M1 V(eras) | ITT BBG000BMB7R1 M1+M5 V | LMCA M1 V(eras) | LSXMA M1 V(eras) | LSXMK M1 S
MDR BBG000BNW1S8 M2 V (rerun; S unresolved) | STE M1 V | TCF BBG000BFK8Y6 M1 V(eras) | TMA BBG000BBG3P1 M1 V
WCRX CIK1323854 M3 V(outcome) | WEN BBG000D52545 M1 V | WLL BBG00WYYC600 unexplained (pair S BBG000PX3XC0 'handoff'; F gets own ticker pick for 2012 era and BBG000PX3XC0 only for the 2017 era; S-side handoff target not traced) | Z CIK1334814-CLASS-A M1+M5
seeds_only
COMPASS, REVELYST M6 | ABBI CIK1141399 M2 V | ACT CIK1578845 M1 V(log: F ACT@2014 joins AGN@2015 line) | ANN CIK811211 M2 V
CBS CIK813828 M3 (code+log; subset not reproduced) | DDR CIK894315 M1 S (F log: DDR@2008/2012 held by guard c, DDR@2018 era joins SITC line; no DDR@2018 era in S; subset rerun did NOT reproduce) | DISH CIK1350031 M2 V
GGP CIK811696 M2 V | HTA CIK1360604 M1 S (F log: HTA@2014-12-31 era joins HR line; absent in S; subset did not reproduce)
IVGN CIK77551 (carries ABI and IVGN eras) M1/M2 V (ABI era not handed over; IVGN anchor 2008-11-24 gives 77551) | RRI CIK1126294 M1 V | TMA CIK892535 M1 V | UAG CIK1019849 M4 V

## Pairs (same real security, two ids)
ABBI CIK1409012(F)=CIK1141399(S, wrong issuer) | ABI BBG000FJJW82(F) = S CIK77551 (merged with IVGN) | ACT(S CIK1578845) = BBG000FH8PX5 (F) | ANN BBG000C9N6Q9(F)=CIK811211(S)
GEN/RRI BBG000BDB3H1(F)=CIK1126294(S) | GGP CIK895648(F)=CIK811696(S) | TMA BBG000BBG3P1(F)=CIK892535(S)
S placeholder = a FIGI present in both runs: CBS->BBG000C496P7, DDR->BBG000BGZ832, DISH->BBG000C2YHG9, HTA->BBG000PRJCX9, IVGN->BBG000CKJ0P3, UAG->BBG000H6K1B0
F placeholder = FIGI present in both: CBG->BBG000C04224, WCRX->BBG000N7CH25
S ticker pick = FIGI in both: ITT->BBG00CVQZQ96, Z->BBG009NRSWJ4, WLL->BBG000PX3XC0

## What later sightings supplied
M1 a dated observation inside the post-switch CUSIP part (and its name), so the part becomes an era. M2 a later last sighting (anchor date) and later spellings of the name. M3 a later name that states (or changes) the class letter. M4 a long enough era span to reach the fails rows under the stale ticker. M5 the later confirming era. M6 nothing identity-related.

## Corrections to the brief
- "ticker T introduced only when name disagrees": names_agree treats ARRIS GROUP/INTERNATIONAL PLC, CRANE CO/CRANE, STERIS/STERIS PLC, BUNGE LTD/GLOBAL SA as one name, so the seed is NOT repeated at the new line; that is the heart of M1.
- ticker_resolution.json in both caches holds both runs' entries (the same start cache plus both runs), so a key present there does not prove which run wrote it; I used the key dates against each era's last_seen to attribute them.

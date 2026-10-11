# kind-flips report (29 cases, cases/2_exit_kind_changes.csv)

Method: instrumented copy of the tree (agents/kind-flips/tree; dumps handoff pairs/spans and the R1 link per merger row).
Full reruns of both runs from their own caches reproduce the original delistings.csv byte for byte (cmp identical).
Toggle reruns (small inputs, seeds rows of the case tickers +/- named observation rows):
 - obsA = seeds rows only; obsB = obsA + B's first full-run observation row; obsC = obsA2 + A's last full-run observation (+WFT 2009-03-20/06-08, +QRTEA/QVCA/LVNTA/LINTA/LCAPA rows);
   obsD/E = S, SPB with late A / late B rows. Outputs: out-smallA, out-smallB, out-smallA2, out-smallC, out-smallD, out-smallE.

## M1 successor line has no sighting in seeds -> no handoff pair (14 reproduced + SPB partly)
find_handoffs pairs only securities that have ticker sightings (pipeline.py:866-868, endings/handoffs.py:77-104, window [-10,120] days).
The successor B (new holding company / redomicile / new CUSIP line) is only a security of the run if some observation names it.
Its observations carry the same ticker and an agreeing name, so seeds_from_observations.py drops them (not a first snapshot, no gap, no new name).
In seeds B is at most an AddedAcquirer (observed=false, no sightings) so there is no pair, nothing decides continuation_filing, and the Form 25 row stays a merger (8-K 2.01/5.01 rules).
Reproduced: adding ONE row (B's first observation) flips seeds merger -> exchange_transfer continuation, same evidence as the full run:
APO (2022-06-30), ARRS (2016-06-30), AVGO (2018-06-30), AZPN (2022-06-30), BG (2023-12-31), CI (2018-12-31), DKNG (2022-06-30),
ENDP (2014-06-30), FERG (2024-12-31), FWONA, FWONK (2023-12-31), MRVL (2021-06-30), NCNO (2022-06-30), TEAM (2022-12-31).
SPB: needs B row 2018-12-31 AND A's late row 2018-06-30 (A's issuer is wrong in seeds, see M3); the pair is timing:cik (same CIK 109177) so the wrong A cik also blocks it. Not isolated which alone.
What the later rows supplied: an observation of B itself.

## M2 R1 continuation (4 reproduced)
ANAT, DTV, AMSG, STE: stage 8b (_r1_continuations pipeline.py:567-618). In both runs terms=(None,1.0), own.one_for_one=True. Full run: successor_by_terms
(endings/successors.py:175-213, pipeline.py:545) finds B in `starts` (built from sightings, pipeline.py:507-517) as new_issuer: first sighted within the window and named by the R1 statement. In seeds
B has no sighting (ANAT: AddedAcquirer with blank issuer_cik, skipped at successors.py:198) so link=None, row stays merger. Fallback successor_from_8k12b also returned None (not traced why).
Reproduced: adding B's first row (ANAT 2020-12-31, DTV 2012-06-29, EVHC 2016-12-30, STE 2019-06-30) gives r1_continuation. (AMSG B is under ticker EVHC.)
MYL also is R1 in full but see M3.

## M3 issuer lookup anchored at era's last sighting -> wrong issuer CIK (10 reproduced)
identity.py:246-256 resolves each era at era_last_seen (identity.py:543-548: last observation + FTD rows within 400 days only). A seed era has one observation, so the lookup is dated at the old
first snapshot (2008) and the Form-25 EFTS tier (ticker_resolver.py ~860-890) returns another company or an old predecessor (resolution_source efts_name_mismatch/name_search).
Seeds issuer vs full: VAL 1398931 vs 102741, PBCT 1406081 vs 1378946, PRE 877355 vs 911421, OMX 6176 vs 12978, PS 866368 vs 1725579, FTI 1106714 vs 1135152, MYL 69499 vs 1623613, S 65100 vs 101830 (B: 1268305 vs 101830), SPB 1487730 vs 109177.
Effects: wrong delisting (unknown 2009, liquidation 2008/2009 from another registrant's filings, exchange_transfer "continued filings") instead of the real merger (VAL, PBCT, PRE, OMX, PS, FTI);
MYL: old Mylan Inc. (2015 inversion row) instead of Mylan NV, R1 2020 never evaluated; S: handoff pair exists in seeds but evidence is timing:cusip across two (wrong) issuers, filing search keyed on the wrong CIK finds no 8-K12B,
so handoffs.py:392-396 keeps the merger with handoff_conflict.
Reproduced: adding A's last full-run observation (VAL 2016-12-30, PBCT 2021-12-31, PRE 2015-12-31, OMX 2009-06-08, PS 2020-12-31, FTI 2016-12-30, MYL 2020-06-30) restores the full kind and CIK. S needed A 2013-06-28 AND B 2019-12-31 (both issuers wrong; with only A fixed it stays merger).
What the later rows supplied: a lookup date near the real end of the security.

## M4 A's sec_id span not carried past a redomicile / class split (2, reproduced with several rows, not isolated to one)
WFT: seeds A ends 2009-02-25 (Bermuda line); full run has observations 2009-03-20/2009-06-08 that carry the sec to the Swiss/Irish lines until 2014-06-18, which meets B (Ireland, seeded 2015-06-30) -> handoff. Seeds: A gets an `unknown` ending 2009-03-08, no pair (gap 5 years). Adding the two 2009 rows restores the full result (obsC).
QRTEA: full run has one placeholder CIK1355096-COMMON holding LCAPA/LINTA/LVNTA/QRTEA/QVCA; seeds run puts the QRTEA@2012-06-29 era on CIK1355096-SERIES-A, so the QRTEA->BBG000PCQQL6 continuation is on SERIES-A and COMMON gets a "continued filings" exchange row. Adding the QRTEA/QVCA/LVNTA/LINTA/LCAPA rows restores it. Which row matters not isolated.

## Case table
WFT M4 (rerun) | QRTEA M4 (rerun, partly) | AMSG M2 | ANAT M2 | APO M1 | ARRS M1 | AVGO M1 | AZPN M1 | BG M1 | CI M1 | DKNG M1 | DTV M2 | ENDP M1 | FERG M1 | FWONA M1 | FWONK M1 | MRVL M1 | MYL M3 (+M2) | NCNO M1 | S M3 | SPB M1+M3 | STE M2 | TEAM M1 | VAL M3 | PBCT M3 | PRE M3 | OMX M3 | PS M3 | FTI M3
Verified by rerun: all 29. Assigned by similarity: none. Partly isolated: SPB, QRTEA, S, MYL.

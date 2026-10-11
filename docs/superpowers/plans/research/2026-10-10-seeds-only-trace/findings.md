# Seeds-only trace: findings (2026-10-10)

Evidence for `docs/superpowers/plans/2026-10-10-seeds-only-parity.md`.

## The two runs

Both at commit `6e43e09` (branch `worktree-reset-1-scorecard`), flags
`--as-of 2026-09-25 --extract-merger-terms-llm`, same starting cache, LLM `claude-sonnet-5-5`.

| | Full | Seeds only |
| --- | --- | --- |
| Input rows | 35,955 | 2,952 |
| `L1.coverage_tickers` | 0.9653 | 0.9486 |
| `L1.coverage_securities` | 0.9668 | 0.9512 |
| `L1.left_view` | 9 | 17 |
| `L1.closed_no_event` | 38 | 60 |
| Golden cases failing | 0 | 7 |
| Diagnosis cases failing | 3 | 35 |
| Contract endings | 871 | 847 |

Seed rows placed on the same `sec_id` in both runs: 2,921 of 2,946. Identification at entry is
nearly the same. The runs differ in what happens after entry.

Differences in the contract (`cases/`):

| File | Rows | What |
| --- | --- | --- |
| `1_endings_on_shared_securities_in_one_run_only.csv` | 42 | 26 endings only the full run has (21 mergers, 5 continuations), 16 only the seeds-only run has, all on securities both runs have |
| `2_exit_kind_changes.csv` | 29 | Same security, ending in both, different exit kind. 21 are a continuation in the full run and a merger in the seeds-only run |
| `3_securities_in_one_run_only.csv` | 51 | 37 securities only in the full run, 14 only in the seeds-only run |
| `4_same_kind_value_or_date_or_verdict_differences.csv` | 18 | Same exit kind, different `dlret`, date or verdict |
| `5_truth_failures.txt` | | The golden and diagnosis cases failing in each run |

## Causes

Five agents traced the cases. "Reproduced" means a small rerun showed the symptom appear and
disappear as observation rows were added or removed. Code paths are under
`src/delist_detection/` at `6e43e09`.

### C1. The era's last-seen date stops 400 days after its last observation

`identity/identity.py:543` `era_last_seen` returns the last observation, or a later fails row of
the era's own CUSIPs under its ticker within 400 days of that observation. A seed era has one
observation, so the date is the seed date plus at most 400 days.

That date feeds the issuer stage, and the damage follows from there:

- The issuer lookup, `identity/identity.py:256`, asks the resolver at that date. The Form 25
  search covers ±90 days (`identity/ticker_resolver.py:725`) and returns another company that
  used the ticker token, or nothing. The name tier's acceptance check needs a Form 25 within
  ±540 days (`ticker_resolver.py:664`, `:214`) and rejects the right issuer.
- The name-in-force check looks at [first, last seen] (`identity/identity.py:668`), and the
  second pass reads the same date.
- With no issuer the delisting search stops (`endings/delistings.py:425-431`,
  `ended_without_delisting`). With a wrong one it reads another company's filings.

Three related windows do not read `era_last_seen` (corrected after review, 2026-10-10). They
read the security's trading record (`endings/trading_record.py` `last_seen`, `known_until`),
which is built from the fails rows of all the security's CUSIPs, so the first fix does not reach
them:

- The finder judges a Form 25 only inside the security's life (`endings/delistings.py:50`,
  `:227`, `:468-472`).
- The no-Form-25 fallback dates an ending from the last sighting (`endings/delistings.py:667-705`).
- The foreign-ticker window is ±30 days around the era (`identity/security_master.py:715`).

Cases (reproduced unless noted):

| Group | Cases |
| --- | --- |
| Lost mergers, wrong or blank issuer | MEL, BKC, PPDI, CEG, HOT, ITC, NSAM, CST, S, SC, DNB, WBA, VTLE (seed under LPI), AL. Pinning the full run's CIK on the seed row restores all of them. SC and WBA get a different merger on the wrong company (SC 2015, WBA 2016). |
| Lost merger, a neighbour's wrong issuer | MER. Sprint's seed resolves to Merrill's CIK 65100, so Merrill's Form 25 matches several securities and is assigned to none (`endings/form25.py:319`, `endings/delistings.py:372-383`). |
| Lost mergers, Form 25 outside the life (the trading record's span, not this date) | SUNW (placeholder with no CUSIP), VIACA (Form 25 of 2025-08-07, last seen 2023-09-14) |
| Exit kind changed, wrong issuer | VAL, PBCT, PRE, OMX, PS, FTI, MYL, S, SPB (with C2) |
| Securities under another id, wrong issuer | ANN, GGP, DISH, CCE, MDR, IVGN, ABBI |
| Other | UAG (foreign-ticker window), MTCH (verdict only; the seeds-only answer is the confirmed one), TRH (its acquirer Alleghany, ticker Y, gets issuer 93410 instead of 775368) |

### C2. A line that begins at a CUSIP change is dropped when no observation falls in it

`identity/identity.py:406-422` `_split_era` cuts a ticker's fails rows at each CUSIP change and
keeps only the parts that hold an observation (`if not obs: continue`, line 410). With the full
input a later sighting sits in the part after the change, so it becomes an era with its own FIGI.
With seeds it is discarded silently. `seeds_from_observations.py` cuts no seed there because the
name still agrees (`names_agree`: ARRIS GROUP and ARRIS INTERNATIONAL PLC, STERIS and STERIS PLC,
CRANE CO and CRANE, BUNGE).

What follows from the missing line:

- No handoff pair forms. `endings/handoffs.py:77-104` `find_handoffs` pairs only securities with
  ticker sightings, so the 8-K12B check never runs and the Form 25 stays a merger.
- The R1 continuation finds no successor. `pipeline.py:507-517` `_starts` lists only securities
  with sightings, and `endings/successors.py:198` skips one with no issuer CIK.
- A merger's stock leg is priced on the wrong rows. `terms/merger_value.py:532-539` takes the
  first fails row under the acquirer's ticker. Without the acquirer's own line that row is the
  target's or another holder's, and `terms/payout_gate.py:251-266` fails the gate.
- The last close is read from another holder of the ticker. `pipeline.py:444-463` skips only
  CUSIPs of securities in the run.
- The issuer in force never changes (MRK keeps CIK 64978 after 2009 and is marked
  `ended_without_delisting`).
- An early event is taken as the ending (ATVI 2008 in place of 2023, CLWR 2008, LVNTA 2016).

Cases (reproduced unless noted):

| Group | Cases |
| --- | --- |
| Securities missing | ABI, AGN, ARRS, BG, BSC, CCE (BBG000BF5RY1), CCU, CIT, CR, DTV, ENDP, EVHC, FWONA, FWONK (similarity), GCI, GEN, HTZ, IGT, ITT, LMCA, LSXMA, LSXMK (similarity), STE, TCF, TMA, WEN, Z; and on the seeds-only side ACT, DDR (log only), HTA (log only), IVGN, RRI, TMA |
| Continuation read as merger, no handoff pair | APO, ARRS, AVGO, AZPN, BG, CI, DKNG, ENDP, FERG, FWONA, FWONK, MRVL, NCNO, TEAM, SPB (with C1) |
| Continuation read as merger, no R1 successor | ANAT, DTV, AMSG, STE |
| Lost mergers, later era missing | ANAT, AZPN, ALEX |
| Span not carried over a redomicile | WFT; QRTEA (not fully isolated) |
| Acquirer line missing: stock leg mispriced | EVHC, MIR, WEN |
| Acquirer line missing: last close from another holder | WEN, TCF |
| Target is an added successor, never valued | NRF, NLSN (see C5) |
| Early event taken as the ending | ATVI, CLWR, LVNTA |
| Continuation needs the successor's sighting | MNST, NE, NRF |
| Acquirer line picked from sightings | TWC (old Charter in place of new; the choice inside `terms/acquirer_line.py` was not traced) |
| Issuer in force | MRK, FOX class B |

Adding one row, the successor's first observation, flips most of these to the full run's result
(ARRS 2016-06-30, STE 2019-06-30, ANAT 2020-12-31, ATVI 2012-06-29, TCF 2020-12-31, and others).

### C3. The seed's ticker did not trade on the seed date

The caller's snapshots carry a later ticker or name backward. 25 of the 2,952 seeds have status
`backfilled_ticker` in both runs. Cases seen: APTV (seed 2012-06-29, ticker in use from 2017;
the 2024 holding-company line then starts in 2012 with a blank issuer and overlaps the earlier
line), ITT (same pattern, BBG00CVQZQ96 from 2008), SUNW (Sun traded as JAVA from 2007), MEL
(seed dated after the 2007 merger). Not traced to code.

### C4. The share class is read from the era's latest observed name

`identity/security_master.py:283` `group()` uses `share_class_from_name(era.name)`, and
`era.name` is the last observation's name (`identity/observations.py:129`). CBS: the seed's
"CBS CORPORATION" is COMMON, PARA is CLASS B, so no link; the full run's "CBS CORP CLASS B"
links. CBG and WCRX go the other way: the full run's later "CLASS A" names break a link the
seeds-only run makes.

### C5. Endings of added successors are never valued

`pipeline.py:1499` `_successor_endings` (stage 9d) creates them after `_merger_values`
(stage 8, `pipeline.py:1483`). In the seeds-only run NRF and NLSN are added successors
(`observed=false`), so their endings get no payout and no LLM read. This is independent of the
input: any successor the run adds has it.

### C6. A takeover inside a ticker gets no seed

FOX and FOXA passed from Twenty-First Century Fox to the new Fox Corp in 2019. `names_agree`
treats the names as the same, so no seed is cut. No filing says the caller's universe holds the
new company. The seeds-only run's ending for the old security (merger, 2019-03-19) is right, and
the new Fox Corp is absent. WEN (Triarc), TCF (Chemical Financial) and CHTR (2016) have the same
shape.

### C7. Not caused by the input

- LLM answers differ between the two runs' separate calls: NMX (one answer's quote begins
  "stockholders who elected", which sets `electors_only` at `terms/llm_merger_extractor.py:421-427`
  and discards the terms), VSTO (acquirer ticker null against GEAR), NVRI and PXP (a ratio's last
  digit).
- The full run answered almost every issuer lookup from old entries in
  `cache/ticker_resolution.json`: of its 6,045 keys, all but 3 were already there. NWA's issuer
  1058033 comes from the entry `NWA|2009-06-08|…`. Recomputed with the current code NWA gets no
  issuer, even with every observation.
- SUG, ABI and NMX fail the diagnosis truth in the full run too (gpt-5.4 against Claude terms).

### Unexplained

WLL (BBG00WYYC600: the full run picks by ticker for the 2012 era, the seeds-only run has
BBG000PX3XC0 by handoff). CEG 2008 and DNB 2020: the issuer stays blank after the C1 fix.
VIACA: the 2025 Form 25 is still not reached after the C1 fix.

## Truth cases failing only in the seeds-only run (39)

| Group | Count | Cases |
| --- | --- | --- |
| Ending missing | 11 | DOW, PPDI, ITC, SUNW, HOUS, DISCA, MER, BKC, NWA, QRTEA, FOXA-2020 |
| Exit kind changed | 7 | ANAT, PRE, MYL, AMSG, SPB, DTV, STE |
| Security missing | 13 | TMA, ITT, ANN, DTV (second line), GCI, HTZ, WLL, LSXMA, RRI, MDR, CCE, FRX, ITT golden |
| Value or date | 4 | CLWR, LVNTA, WEN, TCF |
| None of the above | 4 | MRK-2020 and FOX-2020 (issuer in force, C2), APTV (C3), TRH (C1, the acquirer's issuer) |

## Tests of the first two fixes

Inputs and row-by-row results are in `subsets/`. Each run used the seed rows of the named
tickers, a copy of the seeds-only run's cache, and the same flags.

**Fix 1, subset A (44 tickers, 53 seed rows).** `era_last_seen` follows the era's own CUSIP rows,
each step at most 400 days, stopping before the ticker's next era.

| | Original | Fix 1 |
| --- | --- | --- |
| Issuer matches the full run | 20 | 46 |
| Ending matches the full run | 13 | 34 |

22 endings fixed, 1 broken (ANN: the era now ends at its 2011 CUSIP change and the lookup there
returns CIK 34151). Unbounded following gave the same counts but changed three existing tests;
bounded at the next era it changes one expected value (`LUK@2008-01-16`: 2010-07-13 becomes
2012-06-26).

Limits of both tests, found in review:

- The subsets were drawn from the failing cases.
- The newest seed in each was 2023-06-30, and `identity._refine` opens the fails index only to
  the newest observation plus 400 days, so the follow was cut at 2024-08-03. DNB 2020 and VIACA,
  with endings in 2025, stayed unfixed and may be artifacts of that cut. With the cap removed
  (`hi = as_of`) the whole suite passes with one more expected value changed (a memo key for
  CPRI, 2026-02-04 becomes 2026-08-20).

How much of the full run the fix touches, computed offline on the full input: the last-seen
date changes for 638 of 2,659 eras (13 by up to 90 days, 107 by 91 to 400 days, 234 by 401 days
to 3 years, 284 by more than 3 years). Three of them have a delisting within 90 days of the old
date and not of the new one: CNDT, EXBD, PBYI, all exchange transfers resolved by today's
ticker map or the name search.

**Fixes 1 and 2, subset B (60 tickers, 73 seed rows).** Fix 2 as a rough patch: an FTD-only part
that follows an observed part by a CUSIP change, with a description that `names_agree` with the
era's names, becomes an era with one made-up observation at its first row, carrying the
predecessor's name.

| | Original | Fix 1 | Fixes 1 and 2 |
| --- | --- | --- | --- |
| Ending matches the full run | 30 | 29 | 53 |
| Issuer matches the full run | 65 | 71 | 71 |

26 endings fixed, 2 broken (ANN as above; EVHC, whose followed line took the old Envision's
issuer 1578318 in place of 1678531 and was then read as a continuation). What the rough patch
got wrong:

1. The followed line's issuer was looked up under the predecessor's name.
2. `names_agree` does not read fails-data abbreviations, so ANAT ("AMERICAN NATL GROUP"), MYL,
   ENDP and FERG were not followed.
3. The made-up observations appeared in `observation_map.csv` and `contract/seeds.csv` (119 rows
   in place of 74), and their securities counted as observed (99 in place of 66).

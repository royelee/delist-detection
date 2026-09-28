# Validation: ticker handoffs and the identity guard (plan 2026-09-28, Task 8)

Branch `feat/handoff-successor-links`. Checks the plan's case table
(`docs/superpowers/plans/2026-09-28-handoff-successor-links.md`) against a live
run on the case tickers.

## What was run

- **Case-ticker run.** `classify_universe.py --as-of 2026-09-25` on the 574
  observations of `data/observations.csv` for the case tickers and their
  neighbours (AON FWONA FWONK LSXMA LSXMK LH LIN MNST OI ST TEAM NLSN XL WCRX
  MTCH PNFP LMCA COHR CZR ITT APTV J IIVI JEC DLPH STRZA IAC SNV LMCK PX): 43
  observation eras, 65 after the FTD split. The caches were cold. The same
  input was run twice: once with the code at `8deab45` (the plan's base
  `c43bdd0` plus the plan itself), and once with this branch. Both used an
  empty review-decisions file.
- **Full run** (`data/observations.csv`, 2,469 eras): see *Full run* below.

## Case-ticker run: before and after

| review flag | before | after |
|---|---|---|
| `ended_without_delisting` | 21 | 2 (IAC 2020 and LSXMK 2024; neither is a same-ticker handoff) |
| `ticker_shared` | 7 | 1 (CZR: the takeover's 8-day overlap, left in review by design) |
| `form25_unmatched` | 32 | 11 |
| `successor_unknown` | 5 | 4 |
| `identity_detached` | – | 1 (ITT 2008) |
| `observation_unresolved` | – | 1 (APTV 2012-13, below) |

`run_manifest.json`'s `handoffs` key: 26 candidate pairs, 23 decided. There
were 12 continuations by filing, 9 by timing and 2 takeovers, with no
conflicts. The pass added 19 rows.

Apart from the CZR overlap, no two securities share a ticker on overlapping
dates in `ticker_history.csv`.

## Case table

"Evidence" is what the run decided on: an 8-K12B/8-K12G3 accession, or
`timing:cik`.

| Ticker | Result | Evidence | Old line ends / new line starts |
|---|---|---|---|
| AON | continuation, high | 8-K12B 0001193125-20-093512 | 2020-03-31 / 2020-04-01 |
| FWONA, FWONK, LSXMA, LSXMK | continuation, medium | timing:cik (CIK 1560385) | 2023-08-04 / 2023-08-07 |
| LH | continuation, high | 8-K12B 0000920148-24-000063 | 2024-04-24 / 2024-05-22 |
| LIN | continuation, high | 8-K12B 0001193125-23-055949 | 2023-03-02 / 2023-03-03 |
| MNST | continuation, medium | timing:cik | 2015-06-15 / 2015-06-16 |
| OI | continuation, high | 8-K12B 0001104659-19-076288 | 2019-12-27 / 2019-12-30 |
| ST | continuation, high | 8-K12B 0001477294-18-000050 | 2018-03-27 / 2018-03-28 |
| TEAM | continuation, medium | timing:cik | 2022-10-03 / 2022-10-04 |
| NLSN | continuation, high | 8-K12B 0001193125-15-309410 | 2015-08-28 / 2015-09-03 |
| XL | continuation, high | 8-K12B/A 0000875159-16-000167 | 2016-07-25 / 2016-07-26 |
| WCRX | continuation, high (placeholder predecessor) | 8-K12G3 0001193125-09-179684 | 2009-08-21 / 2009-08-24 |
| MTCH | continuation, medium | timing:cik | 2020-07-01 / 2020-07-02 |
| PNFP | continuation, high; merger row rewritten (`handoff_rebucketed`) | 8-K12B 0001140361-26-000050 | 2026-01-02 / 2026-01-05 |
| LMCA 2013 | no link (the old row keeps `successor_unknown`) | – | 2013-01-16 / 2013-01-23 |
| COHR | takeover: `ticker_successor_sec_id` = BBG000BLW102; merger row kept | timing (II-VI's earlier sightings) | 2022-06-30 / 2022-09-12 |
| CZR | takeover: `ticker_successor_sec_id` = BBG0074Q3NK6; merger row kept | timing:issuer | 2020-07-30 / 2020-07-22 |
| ITT | identity fixed, then continuation (the successor search had already linked it) | same issuer | 2016-05-17 / 2016-05-18 |
| APTV | identity fixed, then continuation | 8-K12G3 0001193125-24-280796 | 2024-12-18 / 2024-12-19 |
| J | identity fixed, then continuation | 8-K12G3 0001193125-22-232264 | 2022-08-29 / 2022-08-30 |

### The "verify" rows

- **PNFP (checked on EDGAR).** New Pinnacle (CIK 2082866) filed 8-K12B
  0001140361-26-000050 on 2026-01-02. Its EX-99.1 says "each share of legacy
  Pinnacle common stock was converted into the right to receive an equal
  number of shares of common stock of new Pinnacle". This is a one-for-one
  continuation, so rewriting the merger row is right.
  - Pinned by `test_a_merger_row_is_rewritten_on_filing_evidence_and_the_old_bucket_is_reviewed`.
  - The old line has no last-trade day of its own. It takes the day before
    the new line's first sighting, so the two ranges no longer overlap
    (`test_the_old_line_ends_before_the_new_one_begins`).
- **LH (resolved by filing).** Labcorp Holdings' 8-K12B settles it. The
  4-week gap (sparse fails rows) is past `CONTINUATION_DAYS`, but filing
  evidence has no gap limit. Pinned by
  `test_the_filing_wins_over_timing_and_over_a_long_gap`.
- **MTCH (documented exception, kept as a continuation).** Old Match Group's
  8-K of 2020-07-06 (0001104659-20-080741) shows how the separation worked:
  - Old IAC (CIK 891103) reclassified and became new Match Group under a new
    FIGI.
  - Old Match merged into it. Each old share became one new Match share, with
    a $3.00 cash-or-stock election (the "Match Loan" mechanics).
  - So `successor_sec_id` is right, but a zero DLRET ignores the $3.00 a
    cash-electing holder received (about 3% at the time).
  - Separately, the old line's issuer CIK came out as 891103 (IAC) rather than
    1575189 (old Match Group), through `company_tickers.json`. That makes the
    `timing:cik` evidence rest on a wrong CIK. The CUSIP switch would give the
    same answer, but the CIK is a resolver issue for a later plan.
- **LMCA 2013 (not a continuation; documented).** In January 2013 old Liberty
  Media (CIK 1507934) spun off the new Liberty Media (CIK 1560385) and went on
  as Starz (STRZA, a new line of the same issuer from 2013-01-17). The new
  company took LMCA. The run found a CUSIP switch under LMCA, and a first
  version of the pass called it a continuation.
  - The pass no longer does: A timing-based continuation is not taken while
    A's issuer starts a line of its own at the handoff and B belongs to
    another issuer (`issuer_carries_on`).
  - Pinned by `test_an_issuer_that_carries_on_in_another_line_hands_its_ticker_to_nobody`.
  - The old placeholder's own successor, Starz, is still not linked: the
    successor search's in-run step sees two candidates. That is left for a
    later plan.

### Found by the run and fixed

- **DLPH 2017 (spin-off).** Delphi Automotive renamed itself Aptiv and moved
  to APTV, and the spun-off Delphi Technologies took DLPH with a new CUSIP.
  The first version of the pass wrote an `exchange_transfer` from Delphi
  Automotive to Delphi Technologies (`timing:cusip`).
  - A line that lives on under another ticker is now continued by nobody,
    whatever the evidence.
  - Pinned by `test_a_line_that_lived_on_under_another_ticker_is_continued_by_nobody`.
- **CZR.** Eldorado is never observed as ERI, so its line has no sighting
  before the handoff, and the takeover rule missed it.
  - A B whose issuer is another company that filed with EDGAR more than a year
    before the handoff now counts as a taker (`timing:issuer`).
  - Pinned by `test_an_older_issuer_that_takes_the_ticker_is_a_takeover_even_unseen_before`.
- **Same-day overlaps (ST, AON).** A fails row is dated the day after the
  close it carries, so both lines were sighted on the handoff day. The old
  line now ends the day before the new one starts.

### Identity guard (Part 1)

- **ITT.** ITT@2008-01-16's ticker pick (today's ITT Inc,
  `BBG00CVQZQ96`) is detached (`identity_detached`).
  - Resolved again, the era joins `BBG000BMB7R1` through its CUSIP switch
    450911102 → 450911201 (2011-11-02): the same issuer and class, a 1-for-2
    reverse split alongside the 2011 spin-offs.
  - Chosen answer: the 2008-09 era is ITT Corporation's line before its 2011
    CUSIP change. `BBG000BMB7R1` now runs 2008-01-16..2016-05-17, and
    `BBG00CVQZQ96` starts 2016-05-18. They do not overlap.
- **APTV 2012-13.** The era has no fails row under APTV, so it takes no ticker
  pick. It also has no issuer CIK: the resolver finds none for "APTIV PLC"
  in 2012-13. So it cannot be placed on Delphi's line and is `unresolved`,
  with an `observation_unresolved` review row. This is the plan's second
  allowed answer. It is never `BBG01R914LT5` any more.
- **J 2012-14.** Traced in the plan. The era is placed on `BBG000BMFFQ0`
  (the JEC line) as a backfill, and its five observations are
  `backfilled_ticker`. The placeholder `CIK52988-COMMON` is gone.

### Other continuations the subset found

- **LMCA and LMCK 2016.** The April 2016 Liberty recapitalization into
  tracking stocks was decided as a `timing:cik` continuation into the
  Liberty Media Group tracker lines.
- **Caveat: distributions ignored.** Holders received a basket, not one share,
  so the zero return ignores the other trackers distributed. Liberty's 2023
  reclassification is the same: FWONA/LSXMA holders also received Liberty
  Live shares.
- The plan decided these reclassifications are continuations, so the
  caveat is recorded here rather than coded.

## Full run

The full run is still in progress (see below); results will be added here if it completes.

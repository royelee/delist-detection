# Validation: ticker handoffs and the identity guard (plan 2026-09-28, Task 8)

Branch `feat/handoff-successor-links`. Checks the plan's case table
(`docs/superpowers/plans/2026-09-28-handoff-successor-links.md`) against a live
run on the case tickers, then against the full universe.

## What was run

- **Case-ticker run.** `classify_universe.py --as-of 2026-09-25` on the 574
  observations of `data/observations.csv` for the case tickers and their
  neighbours (AON FWONA FWONK LSXMA LSXMK LH LIN MNST OI ST TEAM NLSN XL WCRX
  MTCH PNFP LMCA COHR CZR ITT APTV J IIVI JEC DLPH STRZA IAC SNV LMCK PX): 43
  observation eras, 65 after the FTD split. The caches were cold. The same
  input was run twice: once with the code at `8deab45` (the plan's base
  `c43bdd0` plus the plan itself), and once with this branch. Both used an
  empty review-decisions file.
- **Full run** (`data/observations.csv`, 2,469 eras, as_of 2026-09-25, 8 SEC
  workers, `--extract-merger-terms-llm` as the committed `c43bdd0` run): see
  *Full run* below. `output/` is that run, at `76edc38`.

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

The 11 `form25_unmatched` rows left are Form 25s whose class text
`form25.match_security` cannot pin to one observed security (`ambiguous
class`); the full run leaves the same 11:
- 6: Liberty Media's 2023-07-28 Form 25 for the Braves split-off ("Series A
  Liberty Braves Common Stock & Series C ..."), once on each Liberty tracker
  line of CIK 1560385.
- 2: Linde's Form 25 of 2023-11-16 ("Ordinary Shares"), on both LIN lines.
- 1: the 2024-09-19 Form 25 for Liberty SiriusXM's three series, on LSXMK.
- 2: IAC's Form 25 of the July 2020 separation ("Common Stock"), on both IAC
  lines.
Every row of the case table still has its delisting (from its own Form 25 or
from the handoff).

Apart from the CZR overlap, no two securities share a ticker on overlapping
dates in `ticker_history.csv`.

## Case table

"Evidence" is what the run decided on: an 8-K12B/8-K12G3 accession, or
`timing:cik`. The full run at `76edc38` gives every row below unchanged,
except the Liberty and LH delisting dates, which the Form 25 dating fix moved
(FWONA, FWONK, LSXMA, LSXMK on 2023-08-13; LH on 2024-05-30).

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

- **Narrowed after the full run.** As the plan wrote them, guard 1 (no ticker
  or name pick for an unconfirmed era) and rule 2 (own-name picks checked by
  `_contradicted`) turned about 40 correct FIGIs of the full universe into
  placeholders: stale snapshots list dead companies (DJ, MEL, TXU in 2008)
  whose ticker pick is their own dead line, and lines keep their composite
  through a change of issuer (Merck 2009, Medtronic, Eaton). Guard 1 now skips
  the ticker and name tiers only when the backfill placement has the era's
  line; rule 2 is dropped. The plan's *Deviations found by the full run*
  records both. ITT, J and APTV above are unchanged by it.

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

### How it got done

- **Three aborts on SEC 429s (2026-09-28).** Each cold attempt stopped in
  issuer resolution with `EdgarBlocked`: SEC answered HTTP 429 to its
  company-name search (`cgi-bin/browse-edgar`), the resolver's fallback tier,
  at 8, 2 and 1 workers (about 1 h, a few minutes, and 1.5 h after a
  25-minute pause).
- **The name index.** The name tier now reads SEC's `cik-lookup-data.txt`
  instead (`docs/superpowers/plans/2026-09-29-cik-lookup-name-index.md`); a
  full run sends no company search.
- **Five more full runs** found what the case run could not, each fixed test
  first before the next: the identity guard's cost (above), merger rows
  rewritten on timing across issuers, the 8-K12B search under older names, the
  Form 25 dating of a continuation (*Found by the full run*, below), and the
  name index's answers where the live search's differed (the index plan's
  *Rules found by the full runs*; every rule was replayed over the 698 cached
  name-tier answers before the next run).
- **LLM merger terms.** The committed `c43bdd0` run used
  `--extract-merger-terms-llm`; without it `merger_at_par` rose from 53 to 269,
  so the final run uses it too (`gpt-5.4-mini`, answers cached under
  `cache/llm/`).

### Found by the full run and fixed

- **Merger rows on timing across two issuers stand** (`handoff_conflict`, 14
  rows): WEN 2008, IGT 2015 and EVHC 2016 were acquisitions for other shares or
  cash; the first full run rewrote them as continuations. Timing rewrites a
  merger only on the same issuer.
- **The 8-K12B search** also tries the predecessor's EDGAR names around the
  handoff and its observed name (Ashland Inc's CIK is ASHLAND LLC today).
- **A continuation's Form 25** must take effect on or after A's last
  sighting, within 30 days of the later of A's last and B's first sighting:
  the Braves split-off's Form 25 had dated the Liberty trackers' handoff
  (now 2023-08-13), and LH's was 36 days away (now 2024-05-30).

### Result (`output/`, code `76edc38`, against the committed `c43bdd0` run)

| | `c43bdd0` | `76edc38` |
|---|---|---|
| delistings | 982 | 1,017 |
| merger / exchange_transfer / liquidation | 633 / 283 / 47 | 624 / 328 / 48 |
| compliance_failure / unknown / expiration | 6 / 12 / 1 | 6 / 9 / 2 |
| securities (FIGI by CUSIP / ticker / placeholder) | 2,077 / 50 / 99 | 2,078 / 50 / 100 |
| security pairs sharing a ticker on overlapping dates | 30 | 11 |
| review: fix / check | 137 / 618 | 100 / 628 |

`run_manifest.json`'s `handoffs`: 96 candidate pairs, 81 decided: 38
continuations by filing, 35 by timing, 8 takeovers, 14 conflicts; 26 rows
added.

Review flags that moved:

| flag | `c43bdd0` | `76edc38` |
|---|---|---|
| `ended_without_delisting` | 74 | 43 |
| `form25_unmatched` | 55 | 30 |
| `ticker_shared` | 29 | 10 |
| `no_dlret` | 63 | 56 |
| `no_last_trade_date` | 134 | 124 |
| `successor_unknown` | 128 | 126 |
| `merger_at_par` | 53 | 53 |
| `handoff_continuation` / `handoff_rebucketed` / `handoff_conflict` | – | 45 / 15 / 14 |
| `identity_detached` | – | 5 |
| `observation_unresolved` | – | 1 (APTV 2012-13) |

- **Case table.** Every row as above.
- **Ticker overlaps.** No new pair; the 11 left (APA, AVGO, CI, CZR, DTV, GCI,
  GOOG, IACI, LVNTA, QDEL, SPW) were all in `c43bdd0`. CZR is the takeover's
  8-day overlap, in review by design.
- **Delistings the committed run lacked** (besides the 26 the handoffs added):
  real ones its issuer answers missed, ACV 2011 (Unilever), WNR 2017
  (Andeavor), PTHN 2017 (Thermo Fisher), SCS 2025 (HNI), CIT 2022 (First
  Citizens), HTZ 2020 (bankruptcy), TMUSR 2020 (rights expired); and three
  below.
- **Delistings it had that this run does not:** WRK 2018 and ABBI 2008
  (below).
- **`sec_id` or issuer changes** (`observation_map.csv`: 153 observations of
  21 tickers): corrections ITT, XRX, HTZ (old lines instead of today's), J
  (backfill), TCF 2012-14 (old TCF's line), ACV (the 2006 spin-off, 1368457),
  PTHN (Patheon NV), RLGY (Realogy Holdings), WFT 2009 (Weatherford's Swiss
  CIK after its February 2009 move), APTV 2012-13 (no longer today's Aptiv
  line); issuers found where there were none: OCN, SCS, SEAS, WNR, CIT, TMUSR;
  the rest are the gaps below (WRK, ABBI, TWO, NWA, Z).

### Known gaps, left for later

- **XOM 2026-07-12, `merger`.** ExxonMobil's redomiciliation into a Texas
  holding company (8-K 0001193125-26-291986: one share for one, XOM kept
  trading), after the committed run. It is a continuation, but the run
  observes no new XOM line to hand the ticker to. WFT 2014-07-03 (Weatherford's
  move from Switzerland to Ireland, `merger_at_par`) is the same shape.
- **WRK.** The 2015-24 era spans WestRock's 2018 holding-company
  reorganization (CIK 1636023, then 1732845): no single issuer passes the
  resolver, so the era has none. The committed run's WRK 2018 `merger` was
  that reorganization, not an exit; neither run finds the real 2024 exit
  (Smurfit Westrock).
- **ABBI 2008-09.** The snapshots carry ABBI after Abraxis split in November
  2007 (the old company became APP Pharmaceuticals, APPX; the new one traded
  as ABII). The era now resolves to the new Abraxis (1409012) and gets a weak
  `exchange_transfer` guess (`no_form25`); the committed run's 2008 merger
  was APP's. Either answer rests on a stale ticker.
- **TWO 2013-17** takes CIK 1406587 (Capitol Acquisition, the SPAC Two
  Harbors merged with) from the EFTS tier with a name mismatch; the committed
  run had 1465740. **NWA 2008-09** (NORTHWEST AIRLS CORP) finds no issuer
  under that abbreviation. **Z 2014** is detached from Zillow Group's line
  (`identity_detached`: it would cross another line's confirmed Z range) onto
  its issuer's placeholder, `CIK1334814-CLASS-A`. None costs a delisting.
- **`output/web_verification.csv`** is still the `c43bdd0` run's; rerun
  `scripts/verify_against_web.py` on the new `delistings.csv` before relying on
  it.

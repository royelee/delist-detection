# Plan: ticker handoffs — continuation links, ticker takeovers, and an identity guard

Branch `feat/handoff-successor-links`, cut from `main` at `c43bdd0`. Written 2026-09-28 in a `qlib_practice`
session for a fresh session to implement. Everything the implementer needs is in this file. File:line references
are against `c43bdd0`.

## Context

`qlib_practice` builds its price store from this library's output. For every observed security, it picks the
Tiingo symbol that holds the security's history. It follows Tiingo's continuity: when a security's
`successor_sec_id` names another security, the predecessor's history is read from the successor's Tiingo series,
and the predecessor is marked "inherited". That consumer rule assumes one thing. A successor link means the
holders' shares became the successor's shares one for one, so the ticker's price series really is one series.

The first full `qlib_practice` build (as_of 2026-09-25, library output from `c43bdd0`) stopped on 91 issues.
51 of them trace back to this library. This plan fixes the first 31, plus 3 identity bugs found inside them. The
other 20 (groups 2 and 6 in the appendix) get their own plans later.

The 31 are ticker handoffs. One security stops trading under a ticker, and another in-run security starts
trading under the same ticker within days. Two kinds occur:

- **Continuation.** A holding-company reorganization, a redomicile, a rename or a share reclassification. The
  holders' shares become the new security's shares one for one, and the ticker's price series continues (AON
  2020, Jacobs 2022, Liberty's FWONA/FWONK 2023, LH 2024). The library writes no link. Usually it writes no
  delisting row at all.
- **Ticker takeover.** An acquirer buys the target, renames itself after the target and takes over its ticker.
  II-VI became Coherent Corp and took COHR in 2022; Eldorado became Caesars Entertainment Inc and took CZR in
  2020. The target has a correct merger row. Nothing records that the ticker now belongs to the acquirer, whose
  own earlier history sits in the vendor's series for that ticker. Linking these as successors would give the
  target the acquirer's prices, so they must stay apart from continuations.

Three of the 31 are not handoffs at all. APTV, ITT and J each have one share line split across two or three
`sec_id`s whose ticker ranges overlap by years. That is an identity bug in the FIGI resolver (Part 1).

## Outcome

- A continuation writes a delisting row for the predecessor: `exchange_transfer`, `dlret = 0`,
  `successor_sec_id` = the new security.
- A ticker takeover leaves the target's row as it is and fills a new column, `ticker_successor_sec_id`, with the
  security that took the ticker.
- No security's ticker range overlaps another security's range for the same ticker because of a date-less
  ticker or name lookup.
- Rerunning `scripts/classify_universe.py` on `data/observations.csv` (as_of 2026-09-25) gives the expected
  result for every case in the tables below.

## Decided with the user (2026-09-28)

1. **Scope.** This plan covers the reorganization handoffs (the two sub-causes 1a and 1b below) and the three
   duplicate-identity cases. Premature delisting calls (group 2) and bankruptcies that relist under the same FIGI
   (group 6) get separate plans later; see the appendix.
2. **Two fields.** `successor_sec_id` means continuation only: shares became the successor's one for one and the
   price series continues. A new column, `ticker_successor_sec_id`, records "another security took over this
   ticker" (e.g. an acquirer that renamed into it). Consumers can tell the two apart.
3. **Continuation evidence.** The first choice is a successor-issuer filing (8-K12B / 8-K12G3, Rule 12g-3) by the
   new security's issuer that names the old issuer. The library already searches these in
   `successors.successor_from_8k12b`. Without one, use timing and identity: same ticker; the new security's first
   sighting under the ticker is within a few days of the old one's last; the new security has no sighting under
   any ticker before that; and the two share an issuer CIK or a CUSIP handoff under the ticker.
4. **Takeover field scope.** Fill `ticker_successor_sec_id` when another in-run security starts trading under the
   same ticker within a window after the delisted security's last trade and the pair is not a continuation.
   Takers outside the run are not recorded: they have no `sec_id`.
5. **Approach A: one handoff pass.** A new step runs after delistings and successors are found. It decides every
   handoff in one place. It adds the missing delisting row, sets `successor_sec_id` or `ticker_successor_sec_id`,
   and gives a continuation `exchange_transfer` with `dlret = 0`. The Form 25 matcher (`form25.py`) and the
   classifier (`classifier.py`) are not changed. Spec decisions D11 and D16 are revised in the spec text (Task 7).
6. **Duplicates included.** The identity bug behind APTV/ITT/J is fixed in this plan (Part 1).

## Root causes at `c43bdd0`

### 1a. A same-class reorganization gets no delisting row

Cases: AON, FWONA, FWONK, LSXMA, LSXMK, MNST, LH, LIN, OI, ST, TEAM, MTCH, NLSN, WCRX, XL (and APTV, ITT and J
once Part 1 fixes their identities).

- The Form 25 names a plain class ("Common Stock", "Ordinary Shares"). Both the old and the new security are
  alive at the filing date (`delistings.py:127-134`: `_alive_at`, `SIBLING_ALIVE_BEFORE_DAYS=30`,
  `AFTER_DAYS=400`). No class letter and no name token tells them apart, so `match_securities` / `_class_matches`
  (`form25.py:249-297`) returns "ambiguous class".
- `DelistingFinder.find` (`delistings.py:327-341`) logs the filing to `review.csv` as `form25_unmatched` and
  builds no row. This is deliberate: spec D16 (`docs/superpowers/specs/2026-09-22-security-master-and-delistings-design.md:105-116`),
  pinned by `tests/test_delistings.py:113` and `:735`.
- `review.csv` for each case shows `ended_without_delisting`, `form25_unmatched ... ambiguous class`, and
  `ticker_shared "<T> <old span> (<old>) overlaps <T> <new span> (<new>)"`.

### 1b. A merger-bucketed handoff never gets a link

Cases: COHR, CZR (takeovers); PNFP (a 2026 holdco merger, to verify).

- `successor_sec_id` is set only for `exchange_transfer` (`delistings.py:423-427`). `SUCCESSOR_UNKNOWN`
  (`delistings.py:51`) is the only trigger of the successor search (`pipeline.py:719`,
  `successors.successor_search_args` at `successors.py:160-171`). Spec D11 (same design doc, `:85-87`) made this
  choice.
- COHR's row already carries `acquirer_sec_id = BBG000BLW102` (`pipeline.py:801`), and that acquirer is the
  security now trading as COHR. Nothing records that it took the ticker.
- `pipeline._mark_continuing_delistings` (`pipeline.py:893-908`) can only set a self-successor
  (`successor_sec_id = sec_id`), never a different `sec_id`.

### Identity: a date-less ticker lookup joins an old era to today's security (APTV, ITT, J)

- **ITT.** Era `ITT@2008-01-16` (2008-01-16..2009-06-08) has CUSIP `450911102`. OpenFIGI's answer for that CUSIP
  has no US line, so `accept` returns None (`figi_resolution.py:64-70`). The era falls to the TICKER tier
  (`security_master.py:496`), which returns today's holder, `BBG00CVQZQ96` (ITT INC). `names_agree` treats
  CORP/INC/PLC/LTD as filler (`names.py:7-10`, `:34-47`), so "ITT CORPORATION" agrees with "ITT INC". The
  `named()` branch (`security_master.py:513-523`) returns the pick as not weak and skips `_contradicted`
  (`:376-399`). `build_securities` (`:646-681`) then merges the era into `BBG00CVQZQ96`, whose ticker range becomes
  2008-01-16..open and swallows `BBG000BMB7R1`'s 2011-11-02..2016-05-17. `figi_source` shows `cusip` because the
  strongest era wins (`:637`, `:670`), which hides the weak pick. Correct identities: `BBG000BMB7R1`
  (CUSIP 450911201, 2011-11-02..2016-05-17) and `BBG00CVQZQ96` (CUSIP 45073V108, 2016-05-18..open). The 2008-09
  era is neither (CUSIP 450911102, pre-2011 ITT Corporation).
- **APTV.** Era `APTV@2012-06-29` (4 observations, 2012-06-29..2013-12-31) is a snapshot artifact: the constituent
  traded as DLPH then. It has no fails-to-deliver row under APTV, and hence no CUSIP. It goes straight to the
  TICKER tier and gets `BBG01R914LT5` (today's APTV, CUSIP G3265R107 from 2024-12-19), whose range becomes
  2012-06-29..open and overlaps `BBG001QD41M9` (CUSIP G6095L109, 2017-12-06..2024-12-18).
  `ticker_unconfirmed_review` (`security_master.py:687-703`) already flags this era, and its docstring names APTV
  as the motivating example. It runs only as a review check, after the era has already taken a FIGI.
- **J.** `CIK52988-COMMON` (placeholder, J 2012-06-29..open) re-covers the whole history of `BBG000BMFFQ0`
  (JEC→J, ..2022-08-29) and `BBG019C1BQR4` (2022-08-30..), all CIK 52988. Not yet traced; it probably comes from
  the placeholder path. Task 1 starts by tracing it.
- **General rule that fails.** When an era cannot be confirmed by its own CUSIP, the TICKER and name tiers answer
  with today's holder of the ticker. The acceptance check only needs one shared core word. The one guard against
  this (`_contradicted`) is skipped for plain own-name picks, and it compares pre-merge era bounds, so the overlap
  shows only afterwards, in `history.ticker_range_review` (`history.py:172-208`, wired at `pipeline.py:1068`).

### The data the fixes can use (all already in the run)

- `securities.csv`: `issuer_cik`, `share_class` for both sides of every pair.
- Sightings and ticker ranges per security (`history.py`), with the observation and fails-to-deliver sources.
- CUSIP history, from fails-to-deliver (`ftd.py`) and `security_master.cusip_handoffs`.
- `successors.successor_from_8k12b` (EDGAR full-text search of 8-K12B/8-K12G3), currently reached only through
  `SUCCESSOR_UNKNOWN`.
- `successors.successor_in_run` (`successors.py:133-157`), a same-issuer, first-seen-near-my-last-trade search
  that exists but is gated the same way.

## Design

### Part 1 — identity guard (`security_master.py`)

1. An era that has no fails-to-deliver row under its own ticker within its observation window (the fact
   `ticker_unconfirmed_review` computes) must not take a TICKER-tier or name-tier FIGI. It continues through the
   existing paths as if that tier had no answer: backfilled-ticker placement, placeholder or unresolved. For APTV
   2012-13 the expected result is the observations mapped to `BBG001QD41M9` with `observation_map` status
   `backfilled_ticker`, or else unresolved with a review row. It is never `BBG01R914LT5`.
2. A plain own-name pick from the TICKER or name tier goes through `_contradicted`, like the EDGAR-name and
   handoff picks.
3. After `build_securities`, a security whose merged ticker range crosses another security's CUSIP-confirmed range
   for the same ticker has its weak (ticker- or name-tier) era taken back out. That era is re-resolved without the
   weak pick: placeholder, unresolved, or the security its own CUSIP or backfill evidence points to. A `review.csv`
   row records it. For ITT, `BBG00CVQZQ96`'s range starts 2016-05-18, and `BBG000BMB7R1` keeps 2011-11-02..2016-05-17.
   The 2008-09 era gets its own identity or is unresolved. The implementer picks one, records why, and the choice
   must not overlap either security.
4. J: trace `CIK52988-COMMON` first. Then apply the smallest rule that stops a placeholder from covering dates a
   FIGI security of the same issuer and class already covers under the same ticker.

### Part 2 — the handoff pass (new module `handoffs.py`, wired into `pipeline.py`)

**Finding handoffs.** For each ticker T, look at in-run securities A and B with sightings under T, where A's last
sighting under T is date `a` and B's first sighting under T is date `b`. The pair is a candidate when
`-OVERLAP_DAYS <= b - a <= TAKEOVER_DAYS`. Proposed constants: `OVERLAP_DAYS = 10` (CZR's two ranges overlap
8 days; ST hands off on the same day), `CONTINUATION_DAYS = 10`, `TAKEOVER_DAYS = 120` (COHR's gap is about
74 days). Make them module constants, and check the proposed values against the case table before fixing them.

**Deciding a pair**, in order:

1. **Continuation by filing.** `successor_from_8k12b` finds an 8-K12B or 8-K12G3 by B's issuer that names A's
   issuer, within 60 days of `b`.
2. **Continuation by timing and identity.** `|b - a| <= CONTINUATION_DAYS`, B has no sighting under any ticker
   before `a - CONTINUATION_DAYS`, and either `issuer_cik` is equal or the ticker's CUSIP switches from A's last
   CUSIP to B's first near `b` in fails-to-deliver.
3. **Takeover.** Otherwise, when B has sightings before `a` (it existed under another ticker, e.g. IIVI or ERI)
   and `0 <= b - a <= TAKEOVER_DAYS`.
4. **Otherwise nothing.** The existing `ticker_shared` review row stays.

**Acting on a pair.**

- **Continuation.**
  - If A has no delisting row within `CONTINUATION_DAYS` of `a`, create one:
    - `delist_date`: the date of A's issuer's `form25_unmatched` Form 25 within ±30 days of `a` if one was logged,
      else the day after `a`.
    - `last_trade_date = a`.
    - `bucket = exchange_transfer`, with the CRSP code the classifier's `_rename_or_transfer` path uses.
    - `dlret = 0` with the existing exchange-transfer `dlret_method`.
    - `successor_sec_id = B`.
    - `confidence`: `high` for filing evidence, `medium` for timing.
    - A flag `handoff_continuation`, with the evidence (the 8-K12B accession, or `timing:cik`/`timing:cusip`) in
      the reason.
  - If A has a row there, set `successor_sec_id = B`. If that row is a merger, then:
    - with filing evidence, rewrite it to the continuation values above and keep the old bucket in a review row;
    - with timing evidence only, leave the row as it is when its `dlret_method` is a reconciled payout (not
      assumed or abstain), and add a `handoff_conflict` review row.
  - Drop the review rows the continuation resolves for A: `ended_without_delisting`, the matching
    `form25_unmatched` ambiguous-class row, and the pair's `ticker_shared` row.
  - A's ticker range ends at `a`, clipped by the existing rules for delisted securities.
- **Takeover.** On A's delisting row nearest `a`, set `ticker_successor_sec_id = B`. If A has no row, write a
  `handoff_takeover_no_delisting` review row and nothing else.

**Where in the pipeline.** After `_find_successors`, `_link_successors` and `_mark_continuing_delistings`
(`pipeline.py:702-908`), and before history rows and outputs are built (`_history_rows`, `pipeline.py:911-968`),
so that created rows clip ticker ranges like any other delisting. Add counts to `run_manifest.json`: handoffs
found, continuations by filing, continuations by timing, takeovers, conflicts.

### Part 3 — schema and docs

- `delistings.csv` gains `ticker_successor_sec_id`, right after `successor_sec_id`, blank by default. Update the
  table writer, any readers, README's outputs table, `docs/data-flow.md` and the test fixtures that list columns.
- `CONTEXT.md`: define **Handoff**, **Continuation** and **Ticker takeover**, and restate **Successor** as
  continuation only.
- In the 2026-09-22 design spec, add an amendment under D11 and D16. D16 stays true for the Form 25 matcher, but
  the handoff pass now creates the row a continuation needs. D11: `successor_sec_id` now also comes from the
  handoff pass for continuations of any original bucket, and takeovers go in the new column.

## Case table (expected results after this plan)

"Verify" marks cases where the rule's answer should be checked against the real filing before the case is
accepted as a test expectation. Dates are sightings under the ticker from the `c43bdd0` run.

| Ticker | Predecessor A | Successor / taker B | Expected | Evidence expected / note |
|---|---|---|---|---|
| AON | BBG000BC15S7 (..2020-04-01) | BBG00SSQFPK6 (2020-04-01..) | continuation | 8-K12B (UK→Ireland), same CIK 315293 |
| FWONA | BBG00BFHDCV6 (..2023-08-04) | BBG01HLMB809 (2023-08-07..) | continuation | 2023 Liberty reclassification, same CIK 1560385 |
| FWONK | BBG00BFHDFR4 (..2023-08-04) | BBG01HLMBCG3 (2023-08-07..) | continuation | same event |
| LSXMA | BBG00BFHD827 (..2023-08-04) | BBG01HLM8W28 (2023-08-07..) | continuation | same event |
| LSXMK | BBG00BFHD9S7 (..2023-08-04) | BBG01HLMB6H5 (2023-08-07..) | continuation | same event |
| LH | BBG000D9DMK0 (..2024-04-24) | BBG01MMT6PL7 (2024-05-22..) | continuation | 2024 holdco, same CIK 920148; the gap is about 4 weeks, so check it against CONTINUATION_DAYS (verify) |
| LIN | BBG00GVR8YQ9 (..2023-03-02) | BBG01FND0CC1 (2023-03-03..) | continuation | same CIK 1707925 |
| MNST | BBG000CXD6X9 (..2015-06-15) | BBG008NVB1C0 (2015-06-16..) | continuation | 2015 holdco, same CIK 865752 |
| OI | BBG000CNWNL6 (..2019-12-27) | BBG00R2JZG39 (2019-12-30..) | continuation | 2019 holdco, same CIK 812074 |
| ST | BBG000W4G3B9 (..2018-03-28) | BBG00JPGYW43 (2018-03-28..) | continuation | NL→UK, same day, same CIK 1477294 |
| TEAM | BBG00BDQ1H13 (..2022-10-03) | BBG01BGWHFR5 (2022-10-04..) | continuation | UK→US, same CIK 1650372 |
| NLSN | BBG000R06BX2 (..2015-08-28) | BBG0088CYPX8 (2015-09-03..) | continuation | NL→UK, same CIK 1492633 |
| XL | BBG000C9W1Y1 (..2016-07-25) | BBG00DBBG1M0 (2016-07-26..) | continuation | Ireland→Bermuda, same CIK 875159 |
| WCRX | CIK1323854-COMMON (..2009-08-21) | BBG000N7CH25 (2009-08-24..) | continuation | Bermuda→Ireland, same CIK 1323854; the predecessor is a placeholder |
| MTCH | BBG00B6WH9G3 (..2020-07-01) | BBG00VT0KNC3 (2020-07-02..) | verify | 2020 IAC/Match separation: B may be ex-IAC (earlier sightings, which makes it a takeover) or a new line (continuation). Check the filing and B's earlier sightings. |
| PNFP | BBG000C1XKF6 (..2026-01-12, merger row) | BBG01Z7V4LL1 (2026-01-05..) | verify | 2026 holdco with Synovus, new CIK 2082866; expect an 8-K12B, and if so, a continuation that rewrites the merger row |
| LMCA | CIK1507934-CLASS-A (..2013-01-16) | BBG003P9ZSL3 (2013-01-23..) | verify | 2013 Liberty spin-off: the old company may have continued as STRZA (then A is not a delisting; no link) |
| COHR | BBG000BG1DH3 (..2022-06-30, merger) | BBG000BLW102 (2022-09-12.., ex-IIVI) | takeover | acquirer renamed into the ticker; `acquirer_sec_id` is already B |
| CZR | BBG0017T9998 (..2020-07-30, merger) | BBG0074Q3NK6 (2020-07-22.., ex-ERI) | takeover | acquirer renamed into the ticker, different CIK |
| ITT | BBG000BMB7R1 (2011-11-02..2016-05-17) | BBG00CVQZQ96 (2016-05-18..) | identity fix, then continuation | Part 1 detaches the 2008-09 era; 2016 holdco, CUSIP 450911201→45073V108, same CIK 216228 |
| APTV | BBG001QD41M9 (2017-12-06..2024-12-18) | BBG01R914LT5 (2024-12-19..) | identity fix, then continuation | Part 1 removes the 2012-13 era from B; CUSIP G6095L109→G3265R107, same CIK 1521332 |
| J | BBG000BMFFQ0 (..2022-08-29) | BBG019C1BQR4 (2022-08-30..) | identity fix, then continuation | Part 1 removes the overlap from CIK52988-COMMON; 2022 holdco, same CIK 52988 |

The consumer's 31 issues also include `cut_removes_trading` and `ended_early` rows for the same pairs: COHR,
ITT, CZR, PNFP and LMCA (cut), and XL, NLSN, LMCA and WCRX (ended early). They go away once the pairs above
resolve.

## Tasks

Each task is test-first against offline fixtures (`pytest`, offline, about 1,344 tests at `c43bdd0`), and each
ends with the full suite green and a commit. Build fixtures in the style of the existing `tests/test_pipeline.py`
and `tests/test_delistings.py` fakes; no test may touch the network.

- **Task 0 — baseline.** Run `pytest` and record the count. Read `CONTEXT.md`, `docs/data-flow.md` (eras, issuer
  and FIGI resolution, delisting discovery, outputs) and the D11/D16 text.
- **Task 1 — identity guard (Part 1).** Trace J first and add its finding to this plan. Write tests: (a) an era
  with no fails-to-deliver row under its ticker in its window never takes a TICKER/name-tier FIGI (APTV-like
  fixture); (b) an own-name ticker pick is checked by `_contradicted`; (c) the post-merge check detaches a weak era
  whose merged range crosses another security's CUSIP-confirmed range for the same ticker (ITT-like fixture);
  (d) J's rule. Then implement.
- **Task 2 — the new column.** Add `ticker_successor_sec_id` to `delistings.csv` (writer, readers, column-list
  fixtures). Test the column order and the blank default.
- **Task 3 — finding handoffs.** Add a pure function in `handoffs.py` that turns securities, sightings and CUSIP
  history into candidate pairs. Tests: a clean adjoin, the same day, an 8-day overlap, a 74-day gap, a pair
  outside the window, and three securities on one ticker in sequence.
- **Task 4 — deciding a pair.** Continuation by filing (mock `successor_from_8k12b`), continuation by timing
  (same CIK; CUSIP switch), takeover (B with earlier sightings), and nothing. One test per branch, plus the
  precedence of filing over timing.
- **Task 5 — acting on a pair.** Create a continuation row; set the successor on an existing row; rewrite a merger
  row on filing evidence; leave a merger row with a reconciled payout on timing evidence and write
  `handoff_conflict`; set the takeover field; write the no-delisting takeover review row; drop the resolved review
  rows. One test each.
- **Task 6 — wiring.** Call the pass from `pipeline.py` at the point given above. Add the manifest counts. Write an
  integration test through the pipeline's existing fakes: a continuation clips A's ticker range at `a`, and B's
  range is unchanged.
- **Task 7 — docs.** `CONTEXT.md` terms, README outputs table, `docs/data-flow.md`, and the D11/D16 amendments in
  the 2026-09-22 design spec.
- **Task 8 — real run and verification.** This needs network access and the library `.env` (`EDGAR_USER_AGENT`,
  `OPEN_FIGI_API_KEY`). A cold cache makes the run slow. Run:

  `python scripts/classify_universe.py --observations data/observations.csv --as-of 2026-09-25`

  Check every row of the case table against `output/delistings.csv`, `ticker_history.csv` and
  `observation_map.csv`. Also check that no pair of securities has overlapping ranges for the same ticker, except
  where a `review.csv` row explains it. Resolve each "verify" row from the filings, and turn it into a pinned test
  expectation or a documented exception. Write a validation note under `docs/`. If network or keys are
  unavailable in this session, stop after Task 7 and say so; do not fake a run.

## After this lands (qlib_practice, not this library)

- `qlib_practice` reads `successor_sec_id` as continuation and `ticker_successor_sec_id` as takeover.
- A target whose ticker was taken over must not be matched to the taker's vendor series.
- Its security-master build then reruns with the new library, and its store build is repeated.

## Appendix — the other library causes (separate plans later)

### Group 2: premature or false delisting calls (16 consumer issues)

- **Continued filings read as a move to OTC.** `_detect_continued_filings` (`classifier.py:174-191`) returns
  `exchange_transfer` whenever any 10-K/10-Q/20-F/40-F was filed more than 180 days after the anchor date. Almost
  every operating registrant does that. It runs before the Form 25 branches (`classifier.py:696-708`), so it can
  override a matched Form 25.
  - Cases: CCO (BBG000J453J8, 2019-05-01) and WW (BBG000DY6735, 2013-12-31). Both still trade on their
    exchanges, yet each got `exchange_transfer` with `successor_unknown`. Why `listed_today` / `seen_after` was
    false for them is not yet traced.
  - The README's known limitations (`README.md:1088-1090`) describe the same mechanism for spin-offs.
- **No-evidence default.** OKE (BBG000BQHGR6, 2026-09-09) and QGEN (BBG000GTYWL7, 2026-01-07) fell to
  `_default_without_fingerprint` → `unknown`, `confidence=low`, `no_evidence_default` (`classifier.py:403-460`,
  `:457-460`), even though a Form 25-NSE was matched. Both still trade. Why a Form 25 was filed needs a live EDGAR
  look.
- **Other rows with the same shape, all reading `exchange_transfer` "continued 10-K/Q filings >180d", with real
  trading well past the recorded date:**

  | Ticker | sec_id | Recorded | Real stop |
  |---|---|---|---|
  | FMD | BBG000BN6349 | 2013-12-02 | 2016-08-30 |
  | SVU | BBG000BTQ9G8 | 2017-08-02 | 2018-10-19 |
  | JNY | BBG000C7WZ16 | 2010-10-15 | 2014-04-08 |
  | ANN | BBG000C9N6Q9 | 2011-03-15 | 2015-08-21 |
  | ODP | BBG000CNZC55 | 2014 and 2020 | 2025-12-09 |
  | MWW | BBG000DGZ1B6 | 2008 and 2009 | 2016-10-31 |
  | MGI | BBG000Q02P20 | 2011-11-14 | 2023-05-31 |
  | EGL | BBG001BP9474 | 2015-02-27 | 2019-01-11 |
  | TERP | BBG006KY8KV2 | 2017-10-17 | 2020-07-30 |
  | VRM | BBG009NGKQ45 | 2024-02-13 | still trading |
  | MNI | CIK1056087-COMMON | 2016-05-25 | 2020-02-12 |
  | MDR | CIK708819-COMMON | 2018-05-08 | 2020-01-21 |

- **Data a fix can use.** `listing_status.issuer_exchange` / `withdrawal_kind` and `listed_today`
  (`listing_status.py:118-142`) can check that the security actually left its exchange before the
  continued-filings rule fires. Fails-to-deliver continuity (`pipeline._continues_after`, `pipeline.py:820-850`)
  shows real trading after the date.

### Group 6: bankruptcy, then relisting under the same FIGI (4 consumer issues)

- **Cases.** OpenFIGI keeps one composite FIGI across each reorganization:

  | Ticker | sec_id | Cutoff | Note |
  |---|---|---|---|
  | TDW | BBG000BV18Z1 | 2017-07-31 | |
  | BTU | BBG00GBV88T6 | 2016-04-12 | |
  | GTX | BBG00HY28P97 | 2020-09-18 | |
  | EXE | BBG00Z6DX554 | 2020-06-26 | Chesapeake; the library row is keyed CHK |

  Each has a correct `liquidation` row (8-K item 1.03, `shumway_nyse_amex`, dlret -0.30) and one open ticker
  range that runs through the bankruptcy.
- **Cause.** `_ends_the_security` (`pipeline.py:853-874`) says a liquidation always ends the security. The clip in
  `_history_rows` is separately vetoed when `search.listed[sid]` is true (`pipeline.py:936-950`,
  `is_listed = bool(search.listed.get(sid))` at `:938`; the clip condition `not is_listed` at `:941`).
  `listed_today` is true for these four, so the range stays open.
- **Test gap.** `tests/test_pipeline.py:636` covers only an OTC-tail liquidation that never relisted.
- **Design question for that plan.** The FIGI does not change, so the security master's key cannot split the
  security by itself. Options include a post-emergence placeholder security linked as successor, or a clip with
  the relisted range kept under a new identity.

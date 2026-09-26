# Plan: observation map + complete ticker history (fold into PR #5)

## Context

The `qlib_practice` migration plan found two gaps in the library's outputs.

1. **Renamed tickers never become a security.** 47 tickers seen in the snapshots (341 observations) are absent from `ticker_history.csv` (KORS→CPRI, JDSU→VIAV, MHFI→SPGI, LUK→JEF, DSW, PAH, …), so `sec_id_for("KORS", 2015)` finds nothing and history can't be stitched across a rename.
   - **Main cause:** 31 eras are `observation_unresolved`, so they have no issuer CIK and no security. A renamed issuer files no Form 25 and keeps filing 10-Ks, so the resolver fails it at two tiers:
     - The 8-K frequency tier ranks the right CIK first but rejects it under strict validation (`ticker_resolver.py` 468-505).
     - The name-search tier sees only EDGAR's current name, and a nameless multi-company hit wins (KORS → Michael Baker).
   - **Minor causes:**
     - Observations after a history clip (WRK kept trading after its 2018 Form 25).
     - Separator spellings (BFB is shown as BF-B).
     - One wrong cached name-search answer that put ARCP and HTA on one CIK.
2. **No output says which security each observation became.** The library knows, because each observation sits in exactly one era and each era has a resolution after `_resolve_securities`, but it writes nothing out. Mapping through `ticker_history` matches 35,375 of 35,955 observations.

**Outcome.**
- `output/observation_map.csv` gives every observation its `sec_id`, or a blank and a status.
- Renamed tickers resolve to their issuer and join its FIGI.
- `ticker_history` covers every ticker a security actually traded under.

**Decided with the user:**
- Backfilled tickers go in the map only. `ticker_history` keeps only tickers a security actually traded under.
- Finish the paused round-3 cleanup first.
- Fold the result into PR #5.

## Phase 0 — Finish round 3 (the paused work on `fix/review-round3`)

- **Status.** The paused agent committed A1 (`--as-of`, 544fb26) and A2 (exit codes, afe366b). B3, B1 and B2 are uncommitted in the working tree, and `output/` holds a rerun that must be discarded (`git checkout -- output/`).
- **Ruling on B3 (option 2).** `figi_source` comes from the strongest era: pin > cusip > ticker > name > placeholder. `share_class` comes from that era, falling back to a class named by another era of the same security, earliest first. The result:
  - SBA stays CLASS A.
  - Cooper, Ralph Lauren and Discovery get their real classes.
  - About 100 securities' `figi_source` changes from ticker to cusip.
  - The new DISCA 2022 row (304, successor itself, DLRET 0, skipped by the handling layer) is accepted.
  - Every row is explained in the validation note.
- **Then:** commit B1/B2, do C1–C10 per `.superpowers/sdd/2026-09-26-review-round3-fixes/brief.md`, review, and fast-forward into PR #5.
- **Resume, don't start over.** Resume the same agent through SendMessage with this ruling.

## Phase 1 — Resolve renamed tickers (`ticker_resolver.py`, `pipeline._resolve_issuers`, `security_master.py`)

- **1a. Each era looks itself up under its own name.**
  - `resolve(..., name=)` takes the era's own name.
  - `_resolve_issuers` and its warm pass pass `name=e.name`.
  - This fixes KORS@2012 being looked up with the next era's name. That happened because FTD rows of a shared CUSIP push its last sighting forward.
  - Resolver cache key becomes `T|date|NAME`, with `CACHE_VERSION=4`. Version 2 and 3 entries are re-keyed from their stored `member_name`.
- **1b. Name search picks by EDGAR names (fix A, `ticker_resolver.py` 373-444).**
  - Drop nameless hits.
  - Score up to 5 distinct CIKs by name tokens shared with `evidence.edgar_names` (current and former), then by date gap.
  - Validate candidates in rank order with the existing `_accept_observed_name_candidate`.
  - Retire stored `name_search` answers via `_RETIRED_SOURCES`, so a warm cache gives the same CIKs as a cold run (this fixes ARCP/HTA). Decide after the Phase 5 replay; if it churns correct answers, pin ARCP → 1507385 and HTA 2022 → 1360604 instead.
- **1c. A second pass for eras with no CIK and no pin.** It runs after pass 1, in era-key order, and its answers are never cached, because they depend on the run's other eras.
  - **Input.** A new `era_rows(era, ftd, last_seen)` uses the same row choice as `era_last_seen`. An era with fewer than 3 rows gets no answer.
  - **Shared guard G(X).** Candidate CIK X must pass all three:
    - X's first filing is on or before the era's first FTD row.
    - On every row date, a name X carried within 30 days matches the row's description (`names.description_matches`).
    - Exactly one candidate passes.
  - **B: frequency fallback** (source `efts_frequency_renamed`). Candidates come from the existing 8-K frequency ranking. X must pass G, agree with the era's name at its last sighting (`names_near` plus `names_agree`), and have a filing within ±400 days.
  - **C: CUSIP handoff** (sources `shared_cusip` and `cusip_handoff`). It repeats until nothing new links, using a pure `cusip_handoffs(eras, ftd)` in `security_master.py`. There are two kinds of link:
    - **Shared CUSIP:** the era's FTD CUSIP is a CUSIP of an era already resolved to X.
    - **Switch:** the old CUSIP's last live row is within 5 trading days of the first row of a new CUSIP of an X era. That new CUSIP has no earlier row and starts at least 30 days after the FTD window opens. The old CUSIP has no live row more than 10 trading days later. X must also have a former name ending within 90 days of the switch (`evidence.renamed_near`) that matches the old rows.
  - **New flag.** Every B or C answer carries a new `info` flag, `issuer_inferred`, added to `review_triage.CATALOG`.
  - **Why a recycled ticker can't pass:**
    - B needs X to have existed and carried the era's name on the row dates.
    - C needs CUSIP continuity, or a CUSIP born within a week of the old one ending plus a rename.
    - NU → Nu Holdings, ALTR → Altair and MON have neither.
    - LMCA → 1560385 is refused because that CIK first filed after LMCA's rows.
- **Expected result.** About 26 of the 31 eras resolve. AABA and QRTEA (backfilled, no FTD rows), UAG (its FTD rows are an ETN's) and LCAPA/LMCA need `cik` pins in `data/observations.csv`, as does OZRK 2017-18.

## Phase 2 — Join a handoff to the new ticker's FIGI (`FigiResolver.resolve_many`)

- **The join.** Era E has no FIGI pick, issuer X and class K. If a shared-CUSIP or switch edge leads to an era F of the same issuer and class, and F sits on composite Y by pin or CUSIP, E takes Y.
- **How it spreads.** The join follows shared-CUSIP edges. If an era reaches two different composites, it takes none.
- **Guards:**
  - Guards (a) and (b) are checked through `_contradicted`.
  - Handoff picks are weak for guard (c): a chain joins all or none, and every withdrawal is logged.
- **New source.** `handoff` is added to the source ranking, after `name`.
- **Result.** KORS (G60754101) and CPRI (G1890L107) both end up on BBG0029SNR63.

## Phase 3 — `observation_map.csv` (new entry in `store.TABLES`; eight tables)

- **Columns:** `ticker, as_of, name, cusip, pin_cik, pin_sec_id, era, sec_id, issuer_cik, history_ticker, in_ticker_history, status`.
- **Key and sort:** the first six columns. The builder removes duplicate observations, as `load_observations` already does.
- **`status`** takes the first rule that applies:

  | Status | Rule |
  |---|---|
  | `unresolved` | the era has no `sec_id` |
  | `after_delisting` | the security is not listed today and `as_of` is after its history end (`_history_rows` returns that date) |
  | `conflict` | (ticker, as_of) is in `observations.observation_conflicts` |
  | `backfilled_ticker` | `as_of` ≥ 2004-01-31, no FTD row of the security's CUSIPs under the observed ticker (either spelling) within ±30 days, and at least one such row under another symbol |
  | `mapped` | everything else |

- **`history_ticker`** is `security_master.value_on(the security's ticker_history rows, as_of)`. That is the spelling to join on, so BFB gets BF-B.
- **`in_ticker_history`** is true when a range of that security, under that ticker, covers `as_of`.
- **Builder.** A pure `observation_map_rows()` in the module that holds the history rows, called at the row-building stage of `_run`.
- **`--limit` runs:** only the run's eras get rows, and the log says "N of M".

## Phase 4 — `ticker_history` changes (in the history-row builder only)

- **Clip at the last delisting that ends the security.** Skip a delisting whose successor is itself. Also skip one after which the security's own CUSIP keeps trading under its own ticker: at least 20 live FTD rows over at least 60 days, with 2 or more distinct prices. WRK stops being clipped; ARD and compliance failures stay clipped.
- **Backfilled tickers are excluded (the user's decision).** An observation the map marks `backfilled_ticker` is not a ticker sighting. Yahoo stays YHOO in 2012, and ACE's placeholder loses its CB ranges. `ticker_unconfirmed` review rows stay as they are.
- **Separators are unchanged.** The map's `history_ticker` gives the join spelling.

## Phase 5 — Verification

1. **Cache-only replay of stages 1–3** (scratch script with `fill_only()` and sessions that raise on any request). Run old and new code, each with an empty resolver cache and with a copy of the real one. List every era whose CIK, source, `sec_id` or `figi_source` changes, with the rule that changed it. Check every change; curl EDGAR for any that look doubtful. Decide the 1b cache retirement here.
2. **Pins for leftovers** in `data/observations.csv`.
3. **Warm rerun** with `--as-of 2026-09-25 --sec-workers 1`. If 1b retirement goes in, prefetch new company searches with `--sec-workers 8` first.
4. **Diff all eight tables** by key against the Phase 0 outputs, and give a cause for every change: new securities or joins, and delistings found for newly resolved eras.
5. **Rerun `verify_against_web.py`,** plus the offline suite and the golden set.
6. **The caller's metric.**
   - The map has one row per distinct observation (35,955).
   - Report `in_ticker_history` true against the old 35,375, broken down by status.
   - Give a cause for every row still false: `backfilled_ticker`, `after_delisting`, `conflict`, pinned leftovers.
7. **Tests.** Offline fixtures from real cases in `tests/fixtures/eras/` (formerNames plus FTD row excerpts):
   - **Name search (A):**
     - KORS drops nameless CIK 9263 and takes 1530721.
     - ARCP ranks 1507385 first.
     - Must refuse: NU → Nu Holdings, ALTR → Altair.
   - **Own name and cache:**
     - A spy resolver shows each KORS era looked up under its own name.
     - Version-3 cache entries are re-keyed to version 4.
   - **Frequency fallback (B):**
     - KORS@2014 → 1530721.
     - Must refuse: two passing candidates, a CIK founded after the date, UAG's ETN rows, no filing within ±400 days.
   - **CUSIP handoff (C):**
     - KORS → CPRI switch, KORS@2012 shared CUSIP, NU → ES, LUK → JEF.
     - Must refuse: LMCA → 1560385, NU → Nu Holdings, a spin-off, an ambiguous link.
   - **FIGI join:**
     - The KORS chain lands on BBG0029SNR63.
     - Must refuse: guard (a), guard (b), a sibling kept on the placeholder, a class mismatch, an issuer mismatch.
   - **Map:** each status; CB with two names on one date; BF-B; `--limit`; row count equals observation count.
   - **History:**
     - A continuing transfer is not clipped; a WRK-like merger is not clipped.
     - A compliance failure with same-symbol OTC rows is still clipped.
     - A backfilled observation adds no range.
   - **Table set:** update the pinned lists (`tests/test_pipeline.py` ~1143, `tests/test_pipeline_prefetch.py` ~601 → 8, `tests/test_store.py`) and "seven" → "eight" in CLAUDE.md, README, spec §7/§10/§17, `manifest.py` and `scripts/classify_universe.py`.

## Execution

- **Phase 0:** resume the paused agent, then a task review. Fast-forward into PR #5 after a clean review.
- **Phases 1–5:** a new branch `feat/observation-map` from the finished round-3 head, run as subagent-driven development with a plan doc at `docs/superpowers/plans/2026-09-26-observation-map.md`.
  - **Task 1:** phases 1a/1b/1c, with the replay as its acceptance check.
  - **Task 2:** Phase 2.
  - **Task 3:** phases 3 and 4.
  - **Task 4:** Phase 5 pins, rerun and metric.
  - Each task gets a background opus implementer and a task review. After all four, a final review on the most capable model, then fast-forward into PR #5, push, and update the PR description.
- **Rules:** frozen classifier, buckets, dlret and payout gate. Tests offline. No resolver cache of misses. One SEC client at a time, with the lock variable inline. Never `git stash`. Explicit-pathspec commits.

## Risks to watch

- **`description_matches` accepts one shared word.** Guard G's "every row, and existed by the first row" check carries the weight. Test LMCA and a same-word unrelated issuer with real names.
- **B loosens the last resolver tier.** An acquirer that took the target's name could pass. It is limited by the one-candidate rule and the name check at the last sighting.
- **Retiring about 944 cached name-search answers** costs SEC traffic and may change correct answers. Decide from the replay.
- **Guard (c)'s all-or-none rule** can keep a whole chain on the placeholder. The withdrawal log shows it.
- **Switch days can create 1-day ranges that flip between the old and new ticker** (KORS and CPRI overlap on 2019-01-02/03). Check the history rows around each switch.
- **The WRK un-clip rule** could mistake fails settling after a real merger for trading. The distinct-price condition guards against this.

## Critical files

- `src/delist_detection/ticker_resolver.py` (tiers, cache version, pass 2)
- `src/delist_detection/pipeline.py` (`_resolve_issuers`, `_resolve_securities`, row-building stage, `_history_rows` end date)
- `src/delist_detection/security_master.py` (or the history module after round-3 C8): `cusip_handoffs`, `FigiResolver.resolve_many`, `SOURCE_STRENGTH`, `ticker_sightings`, `history_rows`, `observation_map_rows`
- `src/delist_detection/store.py` (the new table)
- `src/delist_detection/review_triage.py` (the `issuer_inferred` flag)
- `src/delist_detection/evidence.py` and `names.py`: reuse `edgar_names`, `names_near`, `renamed_near`, `description_matches` and `names_agree`
- `ftd.py`: reuse `FtdIndex.by_symbol`, `by_cusip`, `trading_rows` and `descriptions`
- `data/observations.csv` (pins)

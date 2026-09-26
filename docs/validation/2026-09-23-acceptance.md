# Acceptance run — security master and delistings (2026-09-23, reruns 2026-09-24 to 2026-09-26)

Spec: `docs/superpowers/feature-spec.md` §13. Run on 2026-09-24 against live SEC
EDGAR, SEC fails-to-deliver (FTD), SEC MIDAS, the Nasdaq halt feed, OpenFIGI and
OpenAI (`--extract-merger-terms-llm`, model from `CHAT_MODEL`). This note describes
the run after review fix round 3, on the SEC speed-up (merged at 7779196) plus the
round-2 and round-3 fixes listed below, **updated for the code-review fixes,
rounds 1 and 2 (2026-09-25) and round 3 (2026-09-26)** (see the three
*Code-review fixes* sections at the end): every count below is from the round-3
rerun unless it says otherwise.

```bash
DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock \
  PYTHONPATH=src python scripts/classify_universe.py --observations data/observations.csv \
  --extract-merger-terms-llm --sec-workers 4
DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock \
  PYTHONPATH=src python scripts/verify_against_web.py
```

The lock variable points every SEC client on the machine at one shared rate limit;
set it inline on every CLI and verifier command.

Final run: exit 0, no `error` and no `resolution_degraded` rows (the CLI exits 3
when either appears, and still writes its outputs). Log: `output/run.log`.
Provenance: `output/run_manifest.json`, written next to the tables. It records the
run date, the code version, the worker count, SEC request counts by endpoint,
latency, the degraded-answer counts (`resolution_degraded`, and `warm_degraded` for
the warm threads' own reads), and `warm_failed`: the warm-pass stages that failed
and were left to the sequential pass (manifest only; empty in this run). It differs
between runs by design. Its code version reads `25dde28-dirty` because the previous
pass's tables were uncommitted in the tree when the run started.

**Speed.** Fix round 2 made four full runs and fix round 3 one, all with 4 SEC
workers:

- **First run** (code `da61707`, about 28 minutes). The caches had been written by
  the pre-speed-up code, which never cached empty company searches and wrote EFTS
  answers in an older format. So this run sent 1,178 SEC requests: company search
  750, full-text search 356, submissions 39, archives 33. Issuer resolution sent
  1,011 of them and took most of the run. Company-search latency was p50 2.1 s,
  p95 27.5 s, max 30 s; SEC's company search slows under sustained traffic. One
  warm-thread read failed (`warm_degraded: failed_request 1`, manifest only); no
  row rests on a degraded answer (`resolution_degraded` 0).
- **Three round-2 reruns** after the last three round-2 fixes (8b0e96e, 8ec70ca,
  0620016). Each sent 0 SEC requests and took about 5 minutes.
- **The round-3 run** (code `e5d340a`, about 5 minutes) sent 11 SEC requests: 10
  full-text searches for the successors of the new transfer rows, and 1 filing
  archive. One warm-thread read failed (`warm_degraded`, manifest only); no row
  rests on a degraded answer.
- **Before the speed-up**, a warm rerun took 40 to 70 minutes.

- **The code-review rerun** (2026-09-25, code `85ebf37`, `--sec-workers 1`): the
  first pass took 4 min 1 s and sent 56 SEC requests (submissions 36, archives
  15, full-text search 5), for the eras whose CUSIPs changed; one archive request
  failed, so 2 rows of Armor Holdings rested on it (`resolution_degraded`, exit
  3). The second pass, run to clear that, took 3 min 17 s, sent 0 SEC requests
  and exited 0 with no `error` or `resolution_degraded` row.
- **The code-review round-2 rerun** (2026-09-25, `--sec-workers 1`): the first
  pass (code `efa887d`) took 3 min 26 s, sent 9 SEC requests (5 archives in the
  delisting search, 4 full-text searches in the successor search) and exited 0;
  its tables showed the placeholder-split regression fixed in 25dde28 (see
  round 2 below), so they were not kept. The second pass (code `25dde28`) took
  3 min 17 s, sent 0 SEC requests and exited 0 with no `error` or
  `resolution_degraded` row.

- **The code-review round-3 rerun** (2026-09-26, code `bd1dcbd`, `--as-of
  2026-09-25 --sec-workers 1`, run date pinned to the round-2 run's): 3 min 26
  s, 0 SEC requests, exit 0, no `error` or `resolution_degraded` row. (A
  first pass of an earlier draft of the share-class rule sent 2 archive
  requests, 10-K covers around Discovery's 2022 Form 25, now cached.)

The tables below are from the code-review round-3 rerun.
`output/web_verification.csv` is from the round-2 rerun: the verifier was not
run again, so round 3's one new delisting row (Discovery Series A 2022) is not
in it.

## Input

`data/observations.csv`, built from the `qlib_practice` iShares Russell 1000 and
Wikipedia snapshot CSVs (equities only).

| | Count |
|---|---|
| Observations | 35,955 |
| Tickers | 2,219 |
| Snapshot dates | 36 (2008-01-16 .. 2026-06-30) |
| Rows with a `name` / `cusip` | 35,955 / 21 (FNM, FRE and UHALB carry their CUSIP; see the code-review fixes) |
| Rows with a `cik` pin | 1,665 (163 pin groups, table below) |
| Rows with a `sec_id` pin | 0 |
| Ticker eras (stage 1 / after the FTD split) | 2,469 / 2,660 |

### Known input issues

- **Two names for one ticker on one date (6 pairs).**
  - CB on 2012-06-29 .. 2014-06-30 is both ACE LTD and CHUBB CORP; AGN on
    2014-06-30 is both ALLERGAN INC and ALLERGAN PLC. One snapshot source
    backfilled today's ticker.
  - Every observation is kept; `review.csv` has one `observation_conflict:<date>`
    row per pair (6).
  - The CB rows are pinned: ACE LTD to Chubb Ltd (896159), CHUBB CORP to Chubb
    Corp (20171).
- **Backfilled tickers (12).** APTV, CBRE, IAC, J, LUMN, PEAK, QRTEA, SPXC, TCF, TT,
  UAA and UAC-C appear in the 2012-2014 snapshots under a ticker adopted later
  (Delphi traded as DLPH then). Each era is flagged `ticker_unconfirmed`: no FTD
  row under that ticker in its span.
- **Stale 2008-09 snapshots (34 eras).** The 2008-01-16 .. 2009-06-08 snapshots
  still list securities that ended in 2007 (A.G. Edwards, Alltel, Avaya, Hilton,
  First Data, Dow Jones, …).
  - Their Form 25s predate the first sighting, so the finder's scan window used to
    skip them, and each ended as `ended_without_delisting`.
  - Fixed in 981e45d: 31 of the 34 have their delisting, 24 of them through the
    `observed_after_delisting` path.
  - Avaya and Armor Holdings stayed `ended_without_delisting` until the
    2026-09-25 CUSIP check (D21): their eras had taken the next holders' CUSIPs
    (Aviva's ADR, Accretive Health), whose fails rows counted as sightings after
    the Form 25. Now Avaya is a 2007 delisting (304) and Armor Holdings a 2007
    merger (231, $88.00 cash), both `observed_after_delisting`; so are
    ServiceMaster (304), Triad Hospitals (231, $54.00) and Cytyc (231, $16.50).
  - Laureate (LAUR, taken private 2007) merged into today's Laureate Education
    security.
- **Snapshot name typos and abbreviations.** "AMERIPRISE FINANCE INC", "DUN BRADST
  HLDG INC", and others fail the resolver's name checks; the wrong answers they led
  to are pinned.

## Output tables

| Table | Rows |
|---|---|
| `securities.csv` | 2,271 (2,255 observed, 16 added acquirers) |
| `ticker_history.csv` | 2,851 |
| `cusip_history.csv` | 2,517 |
| `delistings.csv` | 1,001 |
| `payouts.csv` | 627 |
| `review.csv` | 782 (after triage; 1,220 raw rows before triage existed) |

The old `output/dlret.csv` and `output/delist_classifications.csv` are removed.

**Delistings by bucket:** merger 627, exchange_transfer 308, liquidation 47,
unknown 12, compliance_failure 6, expiration 1.

**Delistings by year:** 2006 1, 2007 29, 2008 40, 2009 40, 2010 32, 2011 41,
2012 36, 2013 40, 2014 35, 2015 67, 2016 86, 2017 63, 2018 70, 2019 54, 2020 61,
2021 62, 2022 62, 2023 46, 2024 40, 2025 54, 2026 42.

**Last trade date source:** MIDAS 531, EX-99.25 notice 192, 8-K item 3.01 30,
Nasdaq halt 27, none 221.

**DLRET method:** cash_only 313, exchange_transfer_zero 308, stock_only 123,
cash_plus_stock 83, assumed_par 59, shumway_nyse_amex 36, needs_last_trade 35,
abstain_no_consideration 22, shumway_nasdaq 16, unknown 6.

**FIGI source (securities):** cusip 2,076, ticker 49, placeholder 146 (a security's
strongest era since round 3; its earliest era's before: cusip 1,976, ticker 149).

**Resolution source (delistings):** name_search 544, efts 171, company_tickers 128,
cik_map (pins) 106, manual 37, efts_frequency 12, efts_name_mismatch 1, rename 1,
none 1.

**Review flags** (rows carrying each, before triage):
- no_last_close 163, no_figi 156, no_last_trade_date 133, ftd_close_lagged 131,
  resolved_by_current_ticker_map 128
- no_form25 128, successor_unknown 127, ftd_close_prior 119,
  form25_unclassified 118, delist_date_approx 114
- last_trade_date_unconfirmed 95, ended_without_delisting 93, form25_unmatched 75,
  ticker_unconfirmed 63, merger_at_par 51
- terms_gate_failed 50, last_trade_date_conflict 45, observation_unresolved 31,
  ticker_shared 31, member_name_mismatch 28
- acquirer_close_lagged 29, observed_after_delisting 29, llm_gate_failed 16,
  payout_gate_failed 12, no_evidence_default 12, resolved_by_cik_map 9
- observation_conflict 6, distress_at_normal_price 3, bankruptcy_before_merger 1,
  bankruptcy_tag_unconfirmed 1, resolved_by_manual_override 1
- resolution_degraded 0, error 0

`resolved_by_current_ticker_map` (128) is the restored pre-refactor flag on every
delisting whose CIK came from `company_tickers.json`. It is noise by design here.

## Acceptance checks (spec §13)

| # | Check | Result |
|---|---|---|
| 1 | `pytest` offline, golden set green | PASS: 1,163 passed |
| 2 | Full run writes all six files, no crash, prints coverage | PASS: exit 0, no `error` or `resolution_degraded` rows |
| 3a | AET: `sec_id` BBG000FJLFX8, one merger, last trade 2018-11-28, close 212.70 | PASS: MIDAS 2018-11-28, close 212.70 |
| 3b | ALTR (Altair): last trade 2025-03-25 | NOT IN INPUT (see below); PASS on a supplementary run |
| 3c | SAVE: last trade 2024-11-15 | PASS: MIDAS 2024-11-15 (it was the notice's 2024-11-18 before d1dd0e0) |
| 3d | MON: Monsanto 2018, no 2022 row | PASS: merger 2018-06-17, last trade 2018-06-06 |
| 3e | HOT, PE, TSS merger, not expiration | PASS: all three code 231 |
| 3f | Apache: no delisting from the 2020 Chicago withdrawal | PASS: only the 2021-03 APA holdco transfer, linked to APA Corp's line |
| 3g | GOOG / GOOGL two securities | PASS: BBG009S3NB30 / BBG009S39JX6 |
| 4 | Every observed security listed today, delisted, or in review | PASS: 2,255 = 1,297 listed + 875 delisted + 83 review, 0 missing (see below) |
| 5 | `verify_against_web.py` agreement ≥ 98.9% | PASS (round-2 tables; not rerun in round 3): 1 of 903 verifiable rows disagrees (99.9%). 97 rows cannot be checked (no Form 25/15 in the window). OK only: 899 / 1,000 = 89.9% |
| 6 | `last_trade_close` on ≥ 90% of 2004+ merger delistings | PASS: 570 / 627 = 90.9% with look-back closes; 488 / 627 = 77.8% without them |

**Check 4.** "Listed today" means an open `ticker_history` row, i.e. `listed_today`
is true. It has three branches:

- **A FIGI security with a known CIK** needs both:
  - an OpenFIGI exchange venue;
  - its ticker (or OpenFIGI's) on a major exchange in the issuer's EDGAR
    submissions.
- **A FIGI security with no CIK:** OpenFIGI alone decides.
- **A placeholder** (`CIK<cik>-<CLASS>`, no FIGI, so no venue to ask): it is listed
  only when its issuer's EDGAR submissions list one of the placeholder's own
  tickers on a major exchange, and (since round 3) its own CUSIP did not last fail
  only under a deleted symbol. SEC's fails files keep reporting a delisted
  security under its old symbol with `XXXX` appended (`HPQXXXX`); such a
  placeholder is an old line whose ticker a newer line of the issuer holds today.

Before fd0b8be, both of these counted as listed:

- A dead FIGI. OpenFIGI still returns venue rows for dead FIGIs, so 48 merged or
  liquidated securities (Celgene, TSS, Slack, Mylan, Alexion, Hess, Walgreens, old
  Apache, …) counted as listed.
- A placeholder whose issuer had any ticker on a major exchange. An old line whose
  issuer still trades under another ticker counted as listed.

The placeholder branch is where the increase in no-Form-25 `exchange_transfer`
(304) rows comes from:

- Fix round 1 raised that count from 86 to 114: 44 rows were new and 16 were gone.
- 43 of the 44 new rows are placeholders that this branch closed. They are no
  longer listed and have no Form 25, so the fallback classifier's continued-filings
  rule reads each of them as 304.
- The 44th is WLL 2017.
- Round 2 left the 114 rows unchanged. Round 3 makes them 125: the deleted-symbol
  rule closed 12 more placeholders (the old lines of NTAP 2008, ACAS 2008, CNO
  2010, SM 2010, WEC 2015, HPQ 2015, AGNC 2016, CXW 2016, CLF 2017, CNX 2017, AIV
  2019 and WW 2019), none with a Form 25. ACAS 2017 left the set: it is now a
  merger (see the pins).

Three securities still have both a definitive delisting and an open range:

- Peabody (BTU, 2016 bankruptcy);
- Garrett Motion (GTX, 2020);
- Chesapeake (CHK, 2020).

Each went bankrupt, and its eras before and after resolved to one FIGI, which is
listed today. The delisting belongs to the pre-bankruptcy line.

**Check 6.** 82 of the 570 merger closes are look-back closes
(`ftd_close_prior:<n>`, no fails row after the last trade); 43 of them are older than
one trading day (up to 10). Across all delistings the ages are: 1 day 69, 2 days 9,
3 days 14, 4 days 6, 5 days 9, 6 days 1, 7 days 5, 8 days 4, 9 days 1, 10 days 1. DLRET
uses the look-back close as the last close.

**ALTR (Altair).** The input has no Altair observation. Every ALTR row is ALTERA
CORP (2008-01-16 .. 2015-06-30), and Altera's delisting is in the table: merger,
last trade 2015-12-24, close 53.96, payout 54.00.

A supplementary run on four Altair observations (`ALTAIR ENGINEERING INC CLASS A`,
2023-06-30 .. 2024-12-31; not committed) gives:

- BBG000PN9NB9, merger 231, NASDAQ;
- last trade **2025-03-25** (MIDAS), close 111.85, payout 113.00, DLRET +1.03%;
- flags `last_trade_date_conflict` and `ftd_close_lagged`. The closing 8-K asked
  Nasdaq to suspend trading "at the close of the market on March 26, 2025", which
  reads as 2025-03-26. MIDAS shows no exchange volume that day, and MIDAS wins.

**Agreement definition.** Disagreements are `MISMATCH_*`, `WEAK_no_ma_items`,
`WEAK_no_3_01` and `WEAK_no_form15`; `WEAK_no_delist_form` and `no_*` are no evidence
either way. This reproduces the 98.9% baseline exactly (456 / 461 on the pre-refactor
file). Final verdicts: OK 899, OK_recycled_ticker 3, WEAK_no_delist_form 97,
MISMATCH_name 1.

## Independent verification: every mismatch and weak row

- **1 MISMATCH_name.** IAC 2021-05-25 (CIK 1800227, now "People Inc", formerly IAC
  Inc. / IAC/InterActiveCorp).
  - The CIK is right. The row is the post-2020 IAC line, which the May 2021 Vimeo
    spin-off replaced (successor linked, same issuer).
  - The verifier drops three-letter words, so "IAC INTERACTIVE" is compared on
    INTERACTIVE alone, and EDGAR writes that word only as "InterActiveCorp".
- **3 OK_recycled_ticker**, all with the right CIK:
  - Aaron's 2020: EDGAR writes "AARON'S INC", and the verifier's own tokenizer
    splits at the apostrophe.
  - Dun & Bradstreet 2025: the snapshot's abbreviated "DUN BRADST HLDG INC".
  - Wendy's 2012: the snapshot's bare "WENDYS".
- **97 WEAK_no_delist_form.** No evidence either way. The 2026-09-25 CUSIP
  check removed one (ES 2014, a row on EnergySolutions' FIGI) and added two
  fallback rows of stale or backfilled eras that no longer borrow another
  company's fails rows (STN 2009, ERA 2013; see the code-review fixes). Round 2
  removed 9 net: 11 placeholder rows went (the rename and placeholder-end rows
  of NTAP, CNO, SM, WEC, AGNC, CXW, CLF, CNX and WYND 2014, and TXU 2009 and
  WPG 2016, which came back as the same verdict on their FIGIs). Two OK rows
  went too (WPG 2015 and CBE 2009, whose lines now continue), and AnnTaylor
  2011 stays OK on its FIGI. They are `exchange_transfer`
  rows from the no-Form-25 fallback whose issuer filed no Form 25/15 in the window
  (renames, reverse splits, holdco reorganizations; see the 304 residual below),
  plus Tidewater's 2017 bankruptcy. Round 3 added 10 (the placeholders the
  deleted-symbol rule closed) and removed ACAS 2017, now a verified merger.
- **Earlier passes**, all explained and fixed:
  - 27 WEAK_no_ma_items: real mergers whose SC 14D9 / DEFM14A / 425 filings sat in
    older submissions files (d6021c6).
  - 6 WEAK_no_form15: bankruptcies without a Form 15, which the 8-K 1.03 confirms
    (d6021c6).
  - 6 MISMATCH_name: camelCase "BlackRock", and holdco reorganizations carrying the
    new holdco's CIK, now pinned per era.

## Successor links

`successor_sec_id` is filled on 181 of the 308 `exchange_transfer` rows:

- 127 point to the security itself (it kept trading after an exchange move;
  since round 3 this includes Discovery Series A 2022, see round 3).
- 54 point to another security of the run, all found by the same-issuer /
  same-ticker rule (024fddc, 700e6d5, 746f2ac). Examples: APA 2021 → APA Corp's
  line, Charter 2016, Apollo 2022, Dell's DVMT tracking stock, Discovery K,
  Brookfield Renewable 2025, Liberty Live's Series A and C 2025 → Liberty Live
  Holdings' LLYVA and LLYVK, and HP's pre-2015 line → HP Inc (BBG000KHWT55).
  Five such links went in the code-review round 2 (NTAP 2008, CBE 2009, SM
  2010, WPG 2015, CNX 2017): the old line and the new one are now one security.
- 127 transfers keep `successor_unknown`.

No link comes from the 8-K12B search. The previous run's only one, Clear Channel
Outdoor 2019 → iHeartMedia's IHRT, was wrong, and da61707 removed it:

- New CCOH filed its 8-K12B under the predecessor's own CIK 1334978, which the
  search excludes.
- That left iHeartMedia's 8-K12G3 for its own emergence, which names its
  subsidiary.
- The name check compared IHRT's FIGI name with iHeartMedia's own EDGAR name, so it
  always agreed.
- The pick now refuses a filer that is another company's own, still-listed stock:
  its EDGAR name disagrees with the predecessor's, none of its tickers is the
  predecessor's, and EDGAR lists it on a major exchange today.
- CCO 2019 keeps `successor_unknown`. The true successor, the new CCO line on the
  same CIK, is not in the run.

An earlier note claimed the 8-K12B search linked Alphabet and APA; that was wrong.

## Fixes made during the run (each with an offline, fixture-backed test)

| Commit | Fix |
|---|---|
| e85353b | docs(data-flow): two-stage era split in the pipeline diagram |
| 981e45d | A Form 25 before a stale first sighting becomes the delisting (`observed_after_delisting`); closes for last trades before the FTD window |
| cf2dc32 | Web verifier paced at 8 req/s; a 403/429 aborts it (exit 2) |
| 4d63d56 | MIDAS 2014 Q2 ships its CSV in a zip inside the zip (16 `error` rows in run 1) |
| ebaa339 | Nasdaq halt feed: parse bytes; the UTF-8 BOM failed every day (136 parse errors in run 1) |
| 5f2ac6f | MIDAS 2016 quarters write the date as a float ("20160104.0"); an empty summary is never cached |
| d1dd0e0 | MIDAS/halt confirmation asks for every ticker the security carried in the window (SAVE → SAVEQ) |
| 19841cc | Close look-back when no FTD row follows the last trade |
| 01e58f7 | Issuer-filed text Form 25: class read above its caption, not the rule checkbox |
| 45d7b29 | A rights plan's Form 25 is a rights class, not preferred |
| 041a251 | A merger/liquidation/compliance/expiration delisting ends the security even when sightings follow it |
| cb77e4b | (reverted in d17ddf1) resolver precedence for the SEC ticker map's holder |
| 9526f6f | Notice wordings "before market open on D" and "suspended by the Exchange on D" |
| 02a7cf0, 029d679 | Close look-back widened to ten trading days; FTD rows loaded to cover it |
| d6021c6 | Web verifier reads the older submissions files around the date and accepts merger documents / bankruptcy 8-Ks as evidence |
| 016e470 | Each era is resolved with its own `cik` pin, not the nearest era's |
| **Fix round 1** | |
| d17ddf1 | Revert cb77e4b: a recycled ticker's historical era could go to today's holder. Its 8 cases are pinned instead. The resolver cache stays version 3 and drops the reverted rule's answers |
| 40d6077 | `name_tokens` drops apostrophes inside words (MACY'S = MACYS) |
| 3e7bb1f | A look-back close carries its age: `ftd_close_prior:<n>`; the row date is kept in the evidence; `_cusip_on` shared |
| fd0b8be | `listed_today`: a dead FIGI with an OpenFIGI venue row is not listed unless EDGAR lists one of its tickers on a major exchange; a placeholder needs one of its own tickers |
| 024fddc, 700e6d5, 746f2ac | A transfer's successor is the one security of the run starting within [last trade − 5 d, + 15 d] under the same issuer or ticker (Form 25 date when the last trade is unknown; every ticker of the old line) |
| 5150ab4 | Pins: holdco reorganizations' old lines to their own issuers (15 issuers) |
| **SEC speed-up** (merged at 7779196) | `--sec-workers N` warm passes; machine-wide SEC rate lock; cached EFTS answers and empty company searches; `resolution_degraded`, exit code 3, `run_manifest.json` |
| **Fix round 2** | |
| c67e68a | An apostrophe word gives both its joined and its split spelling (O'REILLY = OREILLY = O REILLY; FRANK'S = FRANK S) |
| b3ba217 | EDGAR's bare "CBOE" exchange string is Cboe BZX |
| c1c9837 | Pins: MSGE/SPHR, STL, CLNY, VIA-B/VIAB/VIA to their own issuers |
| ec8ed6e | An acquirer on the target's own ticker, or resolved to the target's CIK, takes the SEC ticker map's holder when EDGAR lists it today; otherwise its CIK is left empty |
| 4cd60a5 | A Form 25 matches every class it names, and a tie of one letter is broken by the siblings' distinguishing name words (Liberty's tracking stocks) |
| 90be234 | Pin: Ashland's 2005-2016 line to CIK 1305014 (round 1 had pinned it to 7694, the pre-2005 Ashland Inc.) |
| da61707 | Another company's own, still-listed stock is not an 8-K12B successor (CCO 2019) |
| 8b0e96e | An acquirer on the target's ticker is never the target itself |
| 8ec70ca, 0620016 | A class a Form 25 leaves unresolved still goes to review (`form25_unmatched`) when another class matched |
| **Fix round 3** | |
| eb3b351 | A fails row under a deleted symbol (`…XXXX`) is not trading: it opens and extends no ticker or CUSIP range and counts in no `seen_after`, `last_seen` or sibling span (closes still read it by CUSIP); a placeholder whose own CUSIP last failed only under a deleted symbol is not listed today |
| 32e92e0 | Pin: ACAS to American Capital, Ltd (817473), not AGNC (1423689) |
| f4869b4 | A possessive word counts once toward the words two names must share ("Wendy's Co" = WENDYS ARBYS GROUP) |
| 8771fab | Test: an acquirer on another ticker resolved to the target's CIK (Tivity/Nutrisystem) |

Progress across runs: run 1 (before these fixes) had 16 `error` rows, 794
delistings, 75.5% merger closes and failed SAVE. This run has 0 errors, 0 degraded
rows, 1,004 delistings, and passes every check the input allows.

## Identity corrections (observation `cik` pins)

The resolver's lower tiers (EFTS second-pass fallback, 8-K frequency rank, company
name search) gave about 60 securities another company's CIK. This often produced a
false delisting row: Dillard's as Vaxart's 2025 Nasdaq move, CoreCivic as Cornell's
2010 merger, Qwest as Lazare Kaplan's revocation. Holding-company reorganizations
also gave the old line the new holdco's CIK.

**How they were found.** Observed names were compared with each CIK's EDGAR names
(`member_name_mismatch` rows and a table-wide check), and no-Form-25 transfers whose
issuer first filed after the security's first sighting were listed. Each correct
CIK was verified in its EDGAR submissions JSON (name, former names, filing span).

**The pins: 163 groups on 1,665 rows** (one table row each):
- 116 from the first pass, including 3 stale-snapshot eras.
- 7 for the cases the reverted resolver rule had fixed: AMP, DDS, GE, M, ORLY, PKG,
  SIRI.
- 33 for 15 reorganized issuers (old and new line each) and the Liberty Live
  split-off.
- 6 in fix round 2: MSGE, STL, CLNY, VIA-B, VIAB, VIA.
- 1 in fix round 3: ACAS (all 11 rows) to 817473.

Where a ticker-level `MANUAL_OVERRIDES` entry named a later holder of a recycled
ticker (IMCL, AH), or was simply wrong (CBH → 1018272 is Arrowhead Financial), the
pin overrides it for those rows.

**The pin audit.** Round 2 added an audit (workspace `pin_audit.py`): every pinned
CIK must have filed a 10-K, 10-Q, 20-F, 40-F, 8-K or 6-K while its rows were
observed. It found one wrong round-1 pin:

- ASH's old line was pinned to 7694, the Ashland Inc. that deregistered in 2005.
- It is now 1305014, the 2005-2016 Ashland Inc. (now Ashland LLC).

The other 7 groups the audit lists are expected:

- 6 stale 2008-09 snapshot eras (AGE, AH, AV, LI, THE, TRI), acquired in 2007
  before their first sighting.
- OZRK 2017-18. Its holding company merged into its bank, which files with the
  FDIC, not the SEC.

| Ticker | Rows (name / dates) | CIK | Was | Reason |
|---|---|---|---|---|
| AGE | all 2008-09 rows | 718482 | none (observation_unresolved) | A.G. Edwards (stale 2008-09 snapshot; Wachovia Oct 2007) |
| ASD | all 2008-09 rows | 836102 | none (observation_unresolved) | American Standard Cos (renamed Trane Inc; Ingersoll-Rand June 2008) |
| CEN | all 2008-09 rows | 1124887 | none (observation_unresolved) | Ceridian Corp (stale 2008-09 snapshot; THL/FNF Nov 2007) |
| ADS | all rows | 1101215 | 1838937 Zhangmen Education | Alliance Data Systems (now Bread Financial) |
| AAN | all rows | 706688 | 1454189 Auspex Pharmaceuticals | Aaron's Inc 2012-2015 |
| BEC | all rows | 840467 | 1003470 World Color Press | Beckman Coulter (stale 2008-09 snapshot; Danaher 2011) |
| BLUE | all rows | 1293971 | 1411494 Apollo | bluebird bio |
| CB | ACE LTD | 896159 | 1529979 FX Alliance | backfilled 2012-14 name: ACE Ltd (now Chubb Ltd) |
| CB | CHUBB CORP | 20171 | 1529979 FX Alliance | Chubb Corp (acquired by ACE 2016) |
| CXW | all rows | 1070985 | 1016152 Cornell Companies | CoreCivic / Corrections Corp of America |
| DV | DEVRY EDUCATION GROUP INC | 730464 | 1101783 Teliphone | DeVry Education Group (now Adtalem/Covista) |
| FCL | all rows | 1301063 | 1310243 Alpha Natural Resources/Old | Foundation Coal Holdings (legal survivor renamed Alpha Natural Resources 2009) |
| FO | all rows | 789073 | 1137417 Global Pari-Mutuel | Fortune Brands Inc (became Beam 2011) |
| GYI | all rows | 1047202 | 310316 CanArgo Energy | Getty Images |
| HB | all rows | 47518 | 1038217 Tarragon | Hillenbrand Industries (now Hill-Rom Holdings) |
| IACI | all rows | 891103 | 1139683 Blue Holdings | IAC/InterActiveCorp |
| IGT | INTERNATIONAL GAME TECHNOLOGY PLC | 1619762 | 1816101 dMY Technology II | International Game Technology PLC (now Brightstar Lottery) |
| IMCL | all rows | 765258 | 1520047 ImmunoClin (MANUAL_OVERRIDES) | ImClone Systems (stale 2008-09 snapshot; the ticker-level manual override names a later recycled holder) |
| JCP | all rows | 1166126 | 1172136 US Geothermal | J C Penney Co |
| JNPR | all rows | 1043604 | 1838814 Juniper II Corp | Juniper Networks |
| LTD | all rows | 701985 | 1487999 SeaCube | Limited Brands (now Bath & Body Works) |
| MI | all rows | 1399315 | 704328 Somanetics | Marshall & Ilsley (post-2007 'New M&I') |
| NE | NOBLE CORPORATION to 2009-03-31 | 1169055 | 1085392 Puget Energy / 1023516 EF Johnson | Noble Corp (Cayman) before the March 2009 Swiss redomicile |
| NE | NOBLE CORPORATION from 2009-04-01 | 1458891 | 1023516 EF Johnson | Noble Corp (Switzerland) after the redomicile |
| NE | NOBLE CORP PLC | 1458891 | 70487 National Research Corp | Noble Corp plc |
| Q | QWEST COMMUNICATIONS | 1037949 | 202375 Lazare Kaplan | Qwest Communications International |
| Q | IQVIA HOLDINGS INC | 1478242 | 844150 NatWest / 1448900 Coronus Solar | backfilled 2013-14 name: Quintiles Transnational (now IQVIA) |
| Q | QUINTILES TRANSNATIONAL HOLDINGS I | 1478242 | 844150 NatWest / 1501794 Chrysler Financial | Quintiles Transnational (now IQVIA) |
| Q | QUINTILES IMS INC | 1478242 | 1574963 World Point Terminals / 1409014 AAA Century | Quintiles IMS (now IQVIA) |
| Q | QNITY ELECTRONICS INC | 2058873 | 844150 NatWest | Qnity Electronics (2025 DuPont spin-off) |
| SNH | all rows | 1075415 | 1517401 Peak Resorts | Senior Housing Properties Trust (now Diversified Healthcare Trust) |
| TXU | all rows | 1023291 | 811696 TSIC/Sharper Image | TXU Corp (stale 2008-09 snapshot; LBO Oct 2007) |
| WEN | WENDYS INTERNATIONAL INC to 2008-09-28 | 105668 |  | Wendy's International before Triarc's 2008-09-29 acquisition |
| WEN | WENDYS INTERNATIONAL INC from 2008-09-29 | 30697 | 105668 Wendy's International | stale name: after 2008-09-29 WEN is Wendy's/Arby's Group (Triarc) |
| WEN | WENDYS | 30697 | none | The Wendy's Co |
| WEN | THE WENDYS CO. | 30697 | none | The Wendy's Co |
| WFR | all rows | 945436 | 1323715 Superior Well Services | MEMC Electronic Materials (later SunEdison) |
| WIN | all rows | 1282266 | 1175442 EZTD/Win Global Markets | Windstream |
| WPG | all rows | 1594686 | 912898 Glimcher Realty Trust | Washington Prime Group |
| XL | all rows | 875159 | 1166380 Quantum Fuel Systems | XL Capital / XL Group |
| ATK | all rows | 866121 | 820736 Orbital Sciences | Alliant Techsystems (renamed Orbital ATK 2015) |
| ESI | ITT EDUCATIONAL SVCS INC | 922475 | 1059025 Northeast Energy LP | ITT Educational Services |
| CC | CIRCUIT CITY STORES INC | 104599 | 912151 CE Franklin | Circuit City Stores |
| BJ | BJS WHOLESALE CLUB INC | 1037461 | 864328 BJ Services | BJ's Wholesale Club (taken private 2011) |
| CBH | all rows | 715096 | 1018272 Arrowhead (MANUAL_OVERRIDES) | Commerce Bancorp /NJ/ (TD 2008); the ticker-level manual override was wrong |
| SIX | all rows | 701374 | 1528188 Worldwide NFT / 1804583 Cloopen | Six Flags Entertainment Corp/OLD (merged with Cedar Fair 2024) |
| DO | all rows | 949039 | 1119639 Petrobras | Diamond Offshore Drilling |
| AV | all rows | 1116521 | 1436223 Telmex Internacional / 1038584 Unibanco | Avaya Inc (stale 2008-09 snapshot; taken private Oct 2007) |
| ABI | all rows | 77551 | 23341 Congoleum | Applera Corp |
| THE | all rows | 1210697 | 811040 First Carolina Investors | TODCO (stale 2008-09 snapshot; acquired July 2007) |
| UNIT | all rows | 1620280 | 1743725 Grid Dynamics | Uniti Group |
| COMM | all rows | 1517228 | 1561727 COMM 2012-CCRE5 Mortgage Trust | CommScope Holding (now Vistance Networks) |
| FLOW | all rows | 1641991 | 1604813 TrimTabs ETF Trust | SPX Flow |
| AT | all rows | 65873 | 1013871 NRG Energy | Alltel Corp (stale 2008-09 snapshot; acquired Nov 2007) |
| ACT | ACTAVIS INC. | 884629 | 1514604 Diamond Resorts | Actavis Inc (formerly Watson Pharmaceuticals) |
| ACT | ACTAVIS PLC | 1578845 | 1093728 Pacific Financial | Actavis plc (renamed Allergan plc 2015) |
| LI | all rows | 737874 | 1098865 California Grapes | Laidlaw International (stale 2008-09 snapshot; acquired Oct 2007) |
| LEAF | all rows | 1584207 | 1364728 Central GoldTrust | Springleaf Holdings (now OneMain Holdings) |
| WYND | all rows | 1361658 | 1378453 TravelCenters of America | Wyndham Destinations / Travel + Leisure |
| AH | all rows | 845752 | 1472595 R1 RCM (MANUAL_OVERRIDES) | Armor Holdings (stale 2008-09 snapshot; the ticker-level manual override names a later holder) |
| PEAK | all rows | 765880 | 1493144 Cloud Peak Energy | Healthpeak Properties (HCP) |
| DF | all rows | 931336 | 1517783 EVERTEC | Dean Foods |
| OZRK | all rows | 1038205 | 70858 Bank of America | Bank of the Ozarks |
| FI | FRANK S INTERNATIONAL NV | 1575828 | 1579695 Biotie / 831001 Citigroup | Frank's International (now Expro Group) |
| FI | FISERV INC | 798354 | 831001 Citigroup | Fiserv |
| AWH | all rows | 1163348 | 3906 Allied Capital | Allied World Assurance |
| ARD | all rows | 1689662 | 1845097 Ardagh Metal Packaging | Ardagh Group SA |
| CBE | all rows | 1141982 | 941548 Cameron International | Cooper Industries |
| DCT | DCT INDUSTRIAL TRUST REIT INC | 1170991 | 1604042 DCT Industrial Operating Partnership | DCT Industrial Trust |
| DCT | DCT INDUSTRIAL TRUST REIT INC TRUS | 1170991 | 1604042 DCT Industrial Operating Partnership | DCT Industrial Trust |
| BSC | all rows | 777001 | 1073050 Bear Stearns Capital Trust III | Bear Stearns Companies |
| LEH | all rows | 806085 | 1053521 Lehman Brothers Holdings Capital Trust III | Lehman Brothers Holdings |
| EV | all rows | 350797 | 1665817 Eaton Vance 2021 Target Term Trust | Eaton Vance Corp |
| CBS | all rows | 813828 | 1023421 CBS Operations | CBS Corp (now Paramount Global) |
| NYB | all rows | 910073 | 1211351 New York & Company | New York Community Bancorp (now Flagstar) |
| YHOO | all rows | 1011006 | 1446437 Yahoo Japan | Yahoo Inc (now Altaba) |
| MFS | all rows | 1650962 | 61986 Manitowoc Co | Manitowoc Foodservice (now Welbilt) |
| TRI | TRIAD HOSPITALS INC | 1074771 | 1304901 TRI-S Security | Triad Hospitals (stale 2008-09 snapshot; acquired July 2007) |
| AGN | ALLERGAN | 1578845 | 1620555 Allergan Capital Sarl | Allergan plc (formerly Actavis plc) |
| AGN | ALLERGAN ORD | 1578845 | 1620555 Allergan Capital Sarl | Allergan plc |
| AGN | ALLERGAN PLC | 1578845 | 1620555 Allergan Capital Sarl | Allergan plc |
| NATI | all rows | 935494 | 811696 TSIC | National Instruments |
| FRX | all rows | 38074 | 1089104 Quest Oil | Forest Laboratories |
| PAY | all rows | 1312073 | 895421 Morgan Stanley / 3952 Allied Defense | VeriFone |
| PCLN | all rows | 1075531 | 1125914 OpenTable | Priceline (now Booking Holdings) |
| RE | all rows | 1095073 | 887921 Revlon | Everest Re Group (now Everest Group) |
| SQ | all rows | 1512673 | 1089113 HSBC / 1387054 Firma Holdings | Square / Block |
| SRC | all rows | 1308606 | 1310067 Sears Holdings | Spirit Realty Capital |
| CDEV | all rows | 1658566 | 1725526 HighPoint Resources | Centennial Resource Development (now Permian Resources) |
| FL | all rows | 850209 | 1136893 FIS / 1839121 G&P Acquisition | Foot Locker |
| K | all rows | 55067 | 826675 Dynex Capital | Kellogg / Kellanova |
| IR | INGERSOLL-RAND CO LTD | 1160497 | 1214299 Telkom SA | Ingersoll-Rand Co Ltd (Bermuda) before its July 2009 Irish redomicile |
| AG | all rows | 880266 | 1107457 Infineon | AGCO Corp |
| LSXMA | all rows | 1560385 | 1831992 Liberty Media Acquisition Corp | Liberty Media Corp (Liberty SiriusXM tracking stock) |
| LSXMK | all rows | 1560385 | 1831992 Liberty Media Acquisition Corp | Liberty Media Corp (Liberty SiriusXM tracking stock) |
| BLK | all rows to 2024-06-30 | 1364742 | 2012383 new BlackRock holdco | BlackRock before the Oct 2024 holding-company reorganization (now BlackRock Finance) |
| NCNO | all rows to 2021-12-31 | 1566895 | 1902733 new nCino holdco | nCino before the Jan 2022 holding-company reorganization (nCino OpCo) |
| DKNG | all rows to 2021-12-31 | 1772757 | 1883685 new DraftKings holdco | DraftKings before the May 2022 holding-company reorganization (DraftKings Holdings) |
| IAC | IAC INTERACTIVE to 2020-06-30 | 891103 | 1800227 new IAC | IAC/InterActiveCorp before the July 2020 Match separation (renamed Match Group) |
| AGN | ALLERGAN INC | 850693 | (inherited the ALLERGAN pin of its stage-1 era) | Allergan Inc (acquired by Actavis plc 2015) |
| BJ | BJS WHOLESALE CLUB HOLDINGS INC | 1531152 | (inherited the BJ 2008 pin) | BJs Wholesale Club Holdings (2018 IPO) |
| BLK | all rows from 2024-07-01 | 2012383 | (inherited the pre-reorg pin) | BlackRock Inc after the Oct 2024 reorganization |
| CB | CHUBB LTD | 896159 | (inherited the CHUBB CORP pin) | Chubb Ltd (formerly ACE Ltd) |
| CB | CHUBB | 896159 | (inherited the CHUBB CORP pin) | Chubb Ltd (formerly ACE Ltd) |
| DKNG | all rows from 2022-01-01 | 1883685 | (inherited the pre-reorg pin) | DraftKings Inc after the May 2022 reorganization |
| IAC | all rows from 2020-07-01 | 1800227 | (inherited the pre-separation pin) | IAC after the July 2020 Match separation (now People Inc) |
| IGT | INTERNATIONAL GAME TECHNOLOGY | 353944 | (inherited the IGT PLC pin) | International Game Technology (acquired by GTECH/IGT PLC 2015) |
| IGT | INTL GAME TECHNOLOGY | 353944 | (inherited the IGT PLC pin) | International Game Technology |
| IR | INGERSOLL-RAND PLC | 1466258 | (inherited the Bermuda pin) | Ingersoll-Rand plc (now Trane Technologies) |
| IR | INGERSOLL RAND PLC | 1466258 | (inherited the Bermuda pin) | Ingersoll-Rand plc (now Trane Technologies) |
| IR | INGERSOLL RAND INC | 1699150 | (inherited the Bermuda pin) | Ingersoll Rand Inc (formerly Gardner Denver) |
| NCNO | all rows from 2022-01-01 | 1902733 | (inherited the pre-reorg pin) | nCino Inc after the Jan 2022 reorganization |
| OAS | all rows | 1486159 | 1552890 Javelin Mortgage | Oasis Petroleum (now Chord Energy) |
| ACE | all rows | 896159 | 20171 Chubb Corp / 1017526 ACE Comm | ACE Ltd (renamed Chubb Ltd 2016) |
| MSG | all rows to 2015-09-30 | 1469372 | 1547635 Madison County Financial | Madison Square Garden Co until the Sept 2015 spin-off (renamed MSG Networks) |
| MSG | all rows from 2015-10-01 | 1636519 | 1547635 Madison County Financial | Madison Square Garden Co spun off Oct 2015 (now MSG Sports) |
| AMP | AMERIPRISE FINANCE INC | 820027 | 1771146 via EFTS fallback (cb77e4b gave it; reverted) | Ameriprise Financial (snapshot name typo) |
| DDS | all rows | 28917 | 72444 Vaxart via EFTS frequency (cb77e4b gave it; reverted) | Dillards Inc |
| GE | all rows | 40545 | 1771146 / 1499655 ETF trusts via EFTS fallback (cb77e4b gave it; reverted) | General Electric / GE Aerospace |
| M | all rows | 794367 | 1771146 ETF Opportunities Trust via EFTS fallback (cb77e4b gave it; reverted) | Macys Inc |
| ORLY | all rows | 898173 | 1976322 Themes ETF Trust via EFTS fallback (cb77e4b gave it; reverted) | OReilly Automotive |
| PKG | PACKAGING CORP OF AMER | 75677 | 1161924 MiddleBrook Pharmaceuticals via EFTS fallback (cb77e4b gave it; reverted) | Packaging Corp of America |
| SIRI | SIRIUSXM HOLDINGS INC | 908937 | 320193 Apple via EFTS frequency (cb77e4b gave it; reverted) | Sirius XM Holdings (SEC ticker map holder of SIRI) |
| ASH | all rows to 2016-09-19 | 1305014 | 1674862 new Ashland holdco (then 7694, the pre-2005 Ashland Inc, in round 1) | Ashland Inc 2005-2016 (now Ashland LLC) before the Sept 2016 Ashland Global Holdings reorganization |
| ASH | all rows from 2016-09-20 | 1674862 | (split from the old line) | Ashland Global Holdings / Ashland Inc (new) |
| CI | all rows to 2018-12-19 | 701221 | 1739940 new Cigna holdco | Cigna Corp before the Dec 2018 Express Scripts reorganization (now Cigna Holding Co) |
| CI | all rows from 2018-12-20 | 1739940 | (split from the old line) | The Cigna Group |
| XRX | all rows to 2019-07-30 | 108772 | 1770450 Xerox Holdings | Xerox Corp before the July 2019 holding-company reorganization |
| XRX | all rows from 2019-07-31 | 1770450 | (split from the old line) | Xerox Holdings Corp |
| MRVL | all rows to 2021-04-19 | 1058057 | 1835632 Marvell Technology Inc | Marvell Technology Group Ltd (Bermuda) before the April 2021 redomicile |
| MRVL | all rows from 2021-04-20 | 1835632 | (split from the old line) | Marvell Technology Inc |
| PNFP | all rows to 2026-01-01 | 1115055 | 2082866 new Pinnacle holdco | Pinnacle Financial Partners before the Jan 2026 Synovus combination |
| PNFP | all rows from 2026-01-02 | 2082866 | (split from the old line) | Pinnacle Financial Partners (new holdco) |
| BG | all rows to 2023-10-31 | 1144519 | 1996862 Bunge Global SA | Bunge Ltd (Bermuda) before the Nov 2023 Swiss redomicile |
| BG | all rows from 2023-11-01 | 1996862 | (split from the old line) | Bunge Global SA |
| CZR | CAESARS ENTERTAINMENT CORP | 858339 | 1590895 Caesars Entertainment Inc (Eldorado) | Caesars Entertainment Corp (acquired by Eldorado July 2020) |
| CZR | CAESARS ENTERTAINMENT INC | 1590895 | (split from the old line) | Caesars Entertainment Inc (formerly Eldorado Resorts) |
| APO | APOLLO GLOBAL MANAGEMENT INC CLASS | 1411494 | 1858681 new Apollo holdco | Apollo Global Management before the Jan 2022 Athene merger (now Apollo Asset Management) |
| APO | APOLLO GLOBAL MANAGEMENT INC | 1858681 | (split from the old line) | Apollo Global Management Inc (new holdco) |
| VNOM | all rows to 2025-08-18 | 1602065 | 2074176 new Viper holdco | Viper Energy Inc before the Aug 2025 Sitio reorganization (now VNOM Sub) |
| VNOM | all rows from 2025-08-19 | 2074176 | (split from the old line) | Viper Energy Inc (new holdco) |
| STE | all rows to 2019-03-27 | 1624899 | 1757898 STERIS plc (Ireland) | STERIS plc (UK) before the March 2019 Irish redomicile |
| STE | all rows from 2019-03-28 | 1757898 | (split from the old line) | STERIS plc (Ireland) |
| AVGO | BROADCOM LTD | 1649338 | 1730168 Broadcom Inc | Broadcom Ltd (Singapore) before the April 2018 redomicile |
| AVGO | BROADCOM INC | 1730168 | (split from the old line) | Broadcom Inc |
| FERG | FERGUSON PLC | 1832433 | 2011641 Ferguson Enterprises | Ferguson plc before the Aug 2024 redomicile (now Ferguson Jersey) |
| FERG | FERGUSON ENTERPRISES INC | 2011641 | (split from the old line) | Ferguson Enterprises Inc |
| LLYVA | LIBERTY MEDIA LIBERTY LIVE CORP SE | 1560385 | 2078416 Liberty Live Holdings | Liberty Media's Liberty Live tracking stock before the 2025 split-off |
| LLYVK | LIBERTY MEDIA LIBERTY LIVE CORP SE | 1560385 | 2078416 Liberty Live Holdings | Liberty Media's Liberty Live tracking stock before the 2025 split-off |
| JCI | JOHNSON CONTROLS INC | 53669 | 833444 Johnson Controls International plc | Johnson Controls Inc before the Sept 2016 Tyco merger |
| JCI | JOHNSON CONTROLS INTERNATIONAL PLC | 833444 | (split from the old line) | Johnson Controls International plc (formerly Tyco) |
| WCN | all rows | 1057058 | 1318220 Waste Connections Inc (Canada) | Waste Connections Inc (Delaware) before the June 2016 Progressive Waste merger |
| LLYVA | LIBERTY LIVE HOLDINGS INC | 2078416 | (split from the old line) | Liberty Live Holdings (2025 split-off) |
| LLYVA | LIBERTY LIVE HOLDINGS INC SERIES A | 2078416 | (split from the old line) | Liberty Live Holdings (2025 split-off) |
| LLYVK | LIBERTY LIVE HOLDINGS INC | 2078416 | (split from the old line) | Liberty Live Holdings (2025 split-off) |
| LLYVK | LIBERTY LIVE HOLDINGS INC SERIES C | 2078416 | (split from the old line) | Liberty Live Holdings (2025 split-off) |
| MSGE | all rows | 1795250 | 1469372 MSG Networks | MSG Entertainment (now Sphere Entertainment); MSG Networks' 2021 Form 25 had been attached to it |
| STL | all rows | 1070154 | 93451 Sterling Bancorp (NY, acquired 2013) | Sterling Bancorp (formerly Provident New York Bancorp; merged into Webster Feb 2022) |
| CLNY | all rows | 1679688 | 1467076 Colony Capital (formerly Colony Financial) | Colony Capital 2017-2021 (formerly Colony NorthStar; now DigitalBridge Group) |
| VIA-B | all rows | 1339947 | 813828 CBS Corp | Viacom Inc (2006-2019) class B |
| VIAB | all rows | 1339947 | 813828 CBS Corp | Viacom Inc (2006-2019) class B |
| VIA | all rows | 1339947 | 813828 CBS Corp | Viacom Inc (2006-2019) class A |
| ACAS | all rows | 817473 | 1423689 AGNC Investment (formerly American Capital Agency) | American Capital Ltd (formerly American Capital Strategies; acquired by Ares Capital Jan 2017) |

## Residuals for the user

Carried from the reviews, updated for fix round 3.

- **Resolver precedence for today's ticker-map holder:** FIXED by reverting it
  (d17ddf1); the 8 cases are pins.
- **Look-back closes without their age:** FIXED with `ftd_close_prior:<n>`.
  - 81 merger closes are look-backs; 43 are older than one trading day.
  - Check 6 without them: 78.0% (487 of 624).
  - The look-back closes still feed DLRET.
- **Dead FIGIs counted as listed today:** FIXED for 45 of 48 (fd0b8be).
  - 3 bankrupt and relisted securities (BTU, GTX, CHK) remain open, because their
    old and new lines share one FIGI.
- **No-Form-25 `exchange_transfer` (304) rows:** STILL OPEN, reduced. 115 rows
  (126 after the first code-review rerun, 125 in round 3, 114 in rounds 1 and 2;
  the first code-review rerun dropped ES 2014 and added STN 2009 and ERA 2013;
  the round-2 rerun removed 11 rename and placeholder-end rows: NTAP 2008, CBE
  2009, CNO 2010, SM 2010, WYND 2014, WEC 2015, WPG 2015, AGNC 2016, CXW 2016,
  CLF 2017 and CNX 2017, whose eras now resolve to their issuer's own FIGI).
  - Round 1's increase from 86 came from the placeholder branch of `listed_today`,
    round 3's from the deleted-symbol rule (see check 4).
  - 46 of the 115 have a successor in the run; 69 do not.
  - The 69, by reading the names:
    - about 37 renames, holdco reorganizations or spin-offs whose new line starts
      outside the window or is not in the run (ITT, Yahoo → Altaba, WellPoint →
      Anthem, News Corp 2013, Delphi → Aptiv, TEGNA, Ensco → Valaris, …), and
      AnnTaylor 2011: its FIGI is found now, but the CUSIP change at the rename
      to Ann Inc ends its sightings, so its 2015 merger into Ascena is not
      reached;
    - about 15 reverse splits or recapitalizations with a new CUSIP (Rite Aid 2019,
      Supervalu 2017, Frontier 2017, Windstream 2015, McClatchy 2016, YRC 2010, …);
    - 7 stale or backfilled snapshot eras (TXU, now on its own dead FIGI, XM,
      Sovereign, PEAK/IAC 2014, UAC-C, SunPower 2009);
    - 2 old lines that the deleted-symbol rule closed in round 3 (AIV 2019, WW
      2019). The other five of that group (CNO 2010, WEC 2015, AGNC 2016, CXW
      2016, CLF 2017) are FIXED in code-review round 2: the old line resolves to
      the issuer's FIGI through the issuer's EDGAR names, so there is one
      security and no row. WW stays: its WTW era finds no FIGI, and the
      backfilled WW era stays on the placeholder with it;
    - 4 mergers whose target was the legal survivor or kept filing
      (Schering-Plough → Merck, Foundation Coal, McDermott, Engility);
    - 1 bankruptcy (CBL 2020);
    - 1 when-issued line (RXO-WI).
  - The classifier's continued-filings rule, which is frozen, is what yields 304
    here.
- **Holdco reorganizations with a Form 25:** STILL OPEN as a classification choice.
  - With per-era pins, the old line's Form 25 is found, and the classifier reads the
    reorganization 8-K as a merger:
    - code 231: BlackRock 2024, Cigna 2018, DraftKings 2022, Ashland 2016;
    - code 200: nCino 2022.
  - DLRET is about 0 or at par. No successor is recorded for a merger row.
  - Since 8b0e96e, the acquirer is the new line (Ashland, nCino) or none (MIC, UNIT,
    WRK), never the delisted security itself.
- **Identity errors that shared name words hide:** PARTLY FIXED.
  - The pins cover every case found (JNPR, Oasis; in round 2 SPHR/MSGN, STL, CLNY,
    Viacom, ASH; in round 3 ACAS).
  - The table-wide check lists 36 remaining low scores, all abbreviations or renames
    with the right CIK. That statement covers only the low scores. A wrong CIK whose
    EDGAR name shares enough words with the snapshot name scores high and is not
    listed: ACAS carried AGNC's CIK, whose former name "American Capital Agency"
    shares AMERICAN and CAPITAL with "AMERICAN CAPITAL LTD." The round-2 note
    counted American Capital among the mergers whose target kept filing; that was
    this wrong CIK (AGNC keeps filing), and the re-review found it.
  - Not every high-scoring match was reviewed by hand.
- **Possessive apostrophes:** FIXED (40d6077, then c67e68a). There are 31
  `member_name_mismatch` rows.
  - The previous note blamed FI 2021 on the snapshot's name. It came from the
    tokenizer: 40d6077 joined "Frank's" into FRANKS, which no longer met the
    snapshot's "FRANK S". c67e68a keeps both spellings, and FI 2021 is cleared.
  - One is new: VIACA 2019, where the snapshot writes the post-merger name
    "VIACOMCBS INC CLASS A" against the right CIK 813828.
  - Round 3: ACAS 2017 is cleared (now on its own CIK), and WW 2019 is new: a
    placeholder the deleted-symbol rule closed, on the right CIK 105319 (Weight
    Watchers, renamed WW International in 2018). Still 31 rows then; 28 after
    code-review round 2, whose merged placeholders took the WPG 2015, CBE 2009
    and WYND 2014 rows with them.
- **O'Reilly's phantom placeholder:** FIXED (c67e68a). The pre-2011 era is
  BBG000BGYWY6 again, and CIK898173-COMMON is gone.
- **CBOE counted as unlisted:** FIXED (b3ba217). Listed today on CBOE BZX.
- **SPHR, STL, CLNY and VIA-B on other issuers' CIKs:** FIXED (c1c9837).
  - MSG Networks' 2021 merger is back on MSGN.
  - Sterling's 2022 merger into Webster is back.
  - Viacom's 2019 merger into CBS is on VIA and VIA-B, plus VIA-B's 2011 NYSE →
    Nasdaq move.
  - With VIA/VIA-B off CBS's CIK, CBS's lines are no longer ambiguous: Paramount's
    2025 Skydance merger (PARA) and the 2019 NYSE → Nasdaq move of the class A
    (VIACA) appear.
- **WCN acquirer with the target's CIK:** FIXED (ec8ed6e).
  - WCN is 1318220.
  - The same rule removed the target's CIK from 4 other added acquirers, now empty
    because the SEC ticker map no longer lists them:
    - Tivity (carried Nutrisystem's 1096376);
    - Shire ADR (Baxalta's 1620546);
    - Encana (Newfield's 912750);
    - Aaron's Holdings (Aaron's 706688).
- **ASH, LLYVA and LLYVK old lines without a delisting:** FIXED.
  - ASH: the corrected pin (90be234) finds its 2016-09-20 Form 25: merger 231,
    delisted 2016-09-30, acquirer the new Ashland line.
  - LLYVA/LLYVK: Liberty Media's tracking stocks share class letters across groups
    (Series A/C of Formula One and of Liberty Live). 4cd60a5 matches each class the
    Form 25 names, and breaks a same-letter tie by the group name. Both lines are
    304, 2025-12-25.
  - The same change found other multi-class Form 25s: Google's class C 2015
    (`unknown`), Comcast's CMCSK 2015, Liberty SiriusXM's Series A 2024, Liberty
    Broadband's LBRDK 2026, and Lions Gate's class B 2025.
  - `form25_unmatched` rows: 113 → 78.
- **LLYVK's successor is itself:** FIXED (eb3b351). The fails rows past the
  delisting were under the deleted symbol LLYVKXXXX; they no longer count as
  trading, so the transfer is not continued, and the successor is the new LLYVK
  line (BBG01YYX1Z14).
- **Deleted-symbol (`…XXXX`) fails rows read as trading:** FIXED (eb3b351).
  - 37 `…XXXX` ticker ranges are gone from ticker_history (ORLY's 3-day ORLYXXXX
    row among them; ORLY is one open range from 2007).
  - TRI, CIM and SKLZ keep open ranges under their own tickers, not TRIXXXX,
    CIMXXXX, SKLZXXXX.
  - The HPQ, AGNC, CNO and CNX placeholders (and SM, NTAP, WEC, CXW, CLF, AIV, WW
    and ACAS 2008) are no longer listed today: each is a 304 row, HPQ, CNX, SM,
    NTAP and ACAS 2008 linked to the issuer's newer line. Code-review round 2
    merged AGNC, CNO, CNX, SM, NTAP, WEC, CXW and CLF into their issuer's FIGI
    (no row now); HPQ, AIV, WW and ACAS 2008 remain.
  - Bankrupt lines whose delisting ticker was the deleted symbol (BTU, CHK, WE,
    ACI, CIE, XCO, BLUE) now carry their own ticker, so MIDAS dates their last trade
    and the close is found: 6 liquidations gain a Shumway DLRET (-30%), BLUE 2025 a
    close.
  - Three `ticker_shared` rows are new (QDEL 2022, HTZ, ITT); the `…XXXX` ranges
    used to hide them. QDEL has no last trade date, so its range runs to the Form 25
    date, 6 days into QuidelOrtho. HTZ and ITT are old and new lines merged on one
    FIGI (as BTU, GTX, CHK), so their ranges span the intervening line for years
    (HTZ 2016-07-05..2020-11-02, ITT 2011-11-02..2016-05-17). Hertz's 2020
    bankruptcy has no delisting row (`form25_unmatched`). STILL OPEN.
- **ACAS 2017 on AGNC's CIK:** FIXED (32e92e0). Pinned to 817473 (checked live on
  EDGAR: American Capital, Ltd, formerly American Capital Strategies; 25-NSE/A and
  8-K items 2.01/3.01 on 2017-01-04, Form 15-12G on 2017-01-17). The delisting is
  now a merger (231) into Ares Capital, cash plus stock, DLRET +0.4%.
- **Possessive words counted twice:** FIXED (f4869b4). "WENDYS ARBYS GROUP INC"
  agrees with "Wendy's Co" and "MACYS RETAIL HOLDINGS INC" with "Macy's, Inc."
  again.
- **CLNY/DBRG open range with no exchange:** STILL OPEN. Colony Capital's FIGI is
  today's DigitalBridge (DBRG), but its sightings stop with the CLNY observations,
  so its open range reads CLNY, a ticker EDGAR no longer lists, with no exchange.
  15 open ranges have no exchange (22 in round 2, 8 of them `…XXXX` ranges now gone;
  SKLZ's own open range has none either): CLNY, a separator spelling (BRKB), a
  bankrupt tail (SDOCQ), and tickers EDGAR lists under another spelling or venue.
- **5 added acquirers with no issuer CIK:** STILL OPEN, by design of ec8ed6e. Tivity,
  Shire ADR, Encana, Alpha Natural Resources and Aaron's Holdings resolved to their
  target's CIK, and the SEC ticker map lists no holder today, so the CIK is left
  empty rather than copied.
- **Same-ticker acquirer priced by symbol:** STILL OPEN. The acquirer's price is
  looked up under its ticker, not its CUSIP, so where the target and acquirer share
  a ticker the price can be the target's; DLRETs were unchanged by 8b0e96e.
- **CCO 2019 → IHRT:** FIXED (da61707). `successor_unknown`.
- **Liberty SiriusXM's letter-less Series C lines and CBS's Class B placeholder:**
  STILL OPEN, in review as `form25_unmatched` (8ec70ca, 0620016). Their FIGI name
  carries no class letter, or a FIGI line and a placeholder hold the same stock.
- **Mergers without a close:** STILL OPEN: 57 of 627.
  - 40 have no last trade date (Cytyc 2007, new in the code-review rerun,
    among them). Mostly these are Nasdaq deals whose Form 25-NSE carries an
    empty EX-99.25 before MIDAS, or has no MIDAS row, and has no dated 3.01 8-K.
  - The rest have no priced FTD row within ten trading days before the last trade.
- **`form25_unclassified` (118):** STILL OPEN. These are structured notes, ETNs and
  "See Attached" Form 25s of issuers with many debt lines (BAC, JPM, GS, AIG); none
  is a common-stock delisting.
- **`form25_unmatched` (75):** PARTLY FIXED (113 → 78 → 77 → 75; Clear Channel's
  2008 Form 25 now matches its one line, see the code-review fixes; in round 2
  Cliffs' 2010 rights-plan Form 25 and RGA's 2008 class A/B Form 25s are no
  longer ambiguous between a placeholder and the FIGI line, and neither is a
  delisting). The rest are ambiguous-class
  Form 25s where one issuer has two observed securities of one kind, often a
  placeholder and a FIGI security for the same stock.
- **Stale-era merges:** STILL OPEN.
  - FDC's stale 2008-09 era resolved to the 2015 First Data Class A FIGI, and LAUR's
    to today's Laureate Education, so the 2007 delistings of the old securities are
    missing.
  - Xerox's pre-2017 eras resolved to the Xerox Holdings FIGI (its range starts
    2007).
- **GGP relisting** (review minor): STILL OPEN.
- **Resolver speed:** FIXED by the SEC speed-up.
  - EFTS answers are cached with a TTL, and empty company searches for 7 days.
  - A warm rerun here sent 0 to 11 SEC requests and took about 5 minutes (40 to 70
    minutes before).
  - Resolver misses are still never cached, by design.
- **Stale submissions can hide a new Form 25:** STILL OPEN (known follow-up). The
  delisting finder reads submissions without a freshness bound, so a copy cached
  before a Form 25 can hide it in the first run after that delisting. This is
  survivorship-relevant.
- **Company search keeps only its first match:** STILL OPEN (known follow-up).
  `_parse_company_atom` returns only the first company of a multi-match answer, so
  the name-search tier can miss the right company.
- **CLAUDE.md:** updated to 995 tests (bdfaf4e), then 1,147 (85ebf37), then
  1,163 (25dde28). FIXED.
- **SEC's other deleted-symbol spelling `…ZZZZ`** is still read as trading: 8
  `…ZZZZ` ranges (CLF, PNR, WEN ×2, HON, HLT ×3) and the delisting ticker
  `LBTYAZZZZ`. STILL OPEN (same fix as `…XXXX`).
- **17 listed securities keep a retired CUSIP as their open CUSIP range** (TRI,
  CIM, SKLZ, BTU, SPCE, …). STILL OPEN. Code-review round 2 adds one and closes
  five: CNO Financial's line (BBG000Q1GK24), found now through its EDGAR names,
  is seen only in its 2008-09 Conseco era, so its open range is Conseco's
  208464883; the listed placeholders of ICE, EQT, PVH, RGA and SWK, whose open
  range was the old CUSIP, merged into their FIGI line, where that range now
  ends at the CUSIP switch.
- **Shumway −30% vs the first post-suspension FTD price:** for 4 of the 6
  liquidations newly dated in round 3 (BTU, CHK, ACI, XCO) the first
  post-suspension FTD price implies −59% to −77%. The policy is unchanged; pass
  `--recoveries` where the realized loss matters. STILL OPEN.
- **`names_agree` counts a repeated word twice** ("BROWN & BROWN INC" vs "POE &
  BROWN INC" now disagree); no row in this run changed. STILL OPEN.

## Review triage

`review_triage.py` (2026-09-24 plan) turns the pipeline's raw review rows plus
`data/review_decisions.csv` into a severity-sorted `review.csv` and a new
`review_summary.csv`. Rerun with no decisions yet, `--sec-workers 1`, fully
warm caches (0 SEC requests):

| | Before | After |
|---|---|---|
| `review.csv` rows | 1,220 | 845 |
| `fix` | — | 93 |
| `check` | — | 752 |
| `info`-only rows hidden (flags stay on `delistings.csv`) | — | 375 |

`fix` is 31 `observation_unresolved` (a security that couldn't be identified)
plus 62 delisting rows with a blank DLRET. Every `info`-only row (`no_figi`,
`resolved_by_current_ticker_map`, `ftd_close_lagged`, `ftd_close_prior`,
`last_trade_date_unconfirmed`, `acquirer_close_lagged`, `resolved_by_cik_map`,
`resolved_by_manual_override`) left review.csv without changing
`delistings.csv`. `output/review_summary.csv` has 31 rows (one per flag); the
top five by row count:

| Severity | Flag | Rows | In review | Examples |
|---|---|---|---|---|
| `fix` | `observation_unresolved` | 31 | 31 | AABA; BWC; CBSO |
| `check` | `no_last_close` | 163 | 163 | ADCT@2010-12-19; ANAT@2020-07-12; TAHO@2019-03-04 |
| `check` | `no_form25` | 139 | 139 | RHD@2009-05-29; SSCC@2009-01-30; IAR@2009-03-31 |
| `check` | `no_last_trade_date` | 131 | 131 | ADCT@2010-12-19; ANAT@2020-07-12; CI@2018-12-31 |
| `check` | `successor_unknown` | 129 | 129 | CBL@2020-11-04; PRE@2016-03-28; GAS@2016-07-11 |

No decisions have been recorded yet (`data/review_decisions.csv` is
header-only): `accepted`/`cleared`/`unmatched_decisions` are all 0. Working
`review_summary.csv` top down and recording each accepted cause in
`data/review_decisions.csv` (or bulk-accepting with `scripts/accept_review.py
--flag NAME --note TEXT`) is the next validation step; none of the causes
above have been sampled yet.

### Fix round 1: `no_dlret`

The task review found that `triage()` dropped a delisting row with a blank
DLRET once every one of its *other* flags was accepted, so bulk-accepting a
cause like `no_last_close` could erase rows whose delisting return was still
missing (9 of the 93 `fix` rows above). Fix: `triage()` now injects the token
`no_dlret` (`fix`, acceptable) onto every delisting row whose DLRET is still
blank, before any decision is applied, so it survives its other flags being
accepted and is cleared only by supplying the value or explicitly accepting
`no_dlret`.

Rerun with no decisions still recorded, `--sec-workers 1`, fully warm caches
(0 SEC requests, exit 0):

| | Before this fix | After |
|---|---|---|
| `review.csv` rows | 845 | 845 |
| `fix` | 93 | 93 |
| `check` | 752 | 752 |
| `info`-only rows hidden | 375 | 375 |
| `review_summary.csv` rows | 31 | 32 |

The totals are unchanged, as expected: the fix doesn't change which rows are
`fix` (a blank-DLRET delisting row was already `fix` before this round, via a
special case inside `row_severity` instead of an explicit token), only makes
the reason visible and individually acceptable. The 62 blank-DLRET delisting
rows now each carry `no_dlret` explicitly in `review_flags` (e.g.
`no_last_trade_date;no_last_close;no_dlret` for ADCT@2010-12-19) instead of
being marked `fix` implicitly. `review_summary.csv`'s new row:

| Severity | Flag | Rows | In review | Accepted | Examples |
|---|---|---|---|---|---|
| `fix` | `no_dlret` | 62 | 62 | 0 | ADCT@2010-12-19; ANAT@2020-07-12; TAHO@2019-03-04 |

`git diff --stat -- output/` confirmed only `review.csv` (124 lines changed:
the 62 rows' `review_flags` column), `review_summary.csv` (+1 row),
`run_manifest.json` and `run.log` changed; `delistings.csv` and the other
four tables are byte-identical to before.

### Fix wave 2: final review (C1, I1, I2, I3, M1-M6)

The whole-feature review (`opus`, `final-review.md`) returned "With fixes":
one Critical (`append_decisions` could silently destroy an existing
`data/review_decisions.csv`, dropping extra columns and blanking rows on a
spaced header or a UTF-8 BOM), two Important routing defects (58
`ended_without_delisting` rows — a security with no delisting at all, which
can hide a return as large as -100% — sat at `check` and near the bottom of
`review.csv`, and the review action invited accepting them; ~80 rows of
`no_last_close`/`no_last_trade_date` sent a person hunting closes that
change no output on `exchange_transfer` rows, whose DLRET is always 0), a
reachable gap (a delisting with a blank DLRET and **no flags at all**, via a
`--last-trade-closes`/`--recoveries`/`--merger-terms` override resolving to
no consideration on a non-merger bucket, never reached `review.csv`), and
five minor fixes (a stale decision's row now names the flag it tried to
accept; `accept_review.py` refuses a mistyped or over-specific `--flag`
instead of silently matching nothing, and a bulk-accept of a `fix`-severity
flag now needs `--yes`; a `--limit` dev run no longer floods `review.csv`
with unmatched-decision noise; `successor_unknown`'s action asks the right
question; a stale doc table count). See `.superpowers/sdd/2026-09-24-review-triage/final-fix.md`
for the controller's exact rulings.

Rerun with no decisions still recorded, `--sec-workers 1`, fully warm caches
(0 SEC requests, exit 0):

| | Before this fix | After |
|---|---|---|
| `review.csv` rows | 845 | 766 |
| `fix` | 93 | 151 |
| `check` | 752 | 615 |
| `info`-only rows hidden | 375 | 454 |
| `review_summary.csv` rows | 32 | 32 |

`fix` rose by exactly **58** (I1: every `ended_without_delisting` row moved
from `check` to `fix`, no row count change). `check` fell by **137** = 58
(the same I1 rows) + 79 (I3: rows whose only remaining severity-bearing
flags were `no_last_close`/`no_last_trade_date` on an `exchange_transfer`
row, now graded `info` and hidden). `info_hidden` rose by exactly **79** to
match. `no_last_close`'s summary row: `rows` unchanged at 163, `in_review`
drops from 163 to 84 (79 fewer); `no_last_trade_date`: 131 rows, `in_review`
131 → 52 (also 79 fewer) — the same 79 rows carry both flags, so the net
`review.csv` row reduction is 79, not 158. I2 added no new rows in this run
(no override in this universe's inputs happens to resolve to a negative or
zero consideration on a non-merger bucket), which is expected — I2 closes a
reachable gap, not one this particular universe's overrides currently hit.

Top 10 `review_summary.csv` rows by severity, then row count:

| Severity | Flag | Rows | In review | Accepted | Examples |
|---|---|---|---|---|---|
| `fix` | `no_dlret` | 62 | 62 | 0 | ADCT@2010-12-19; ANAT@2020-07-12; TAHO@2019-03-04 |
| `fix` | `ended_without_delisting` | 58 | 58 | 0 | ACV; WNR; CCU |
| `fix` | `observation_unresolved` | 31 | 31 | 0 | AABA; BWC; CBSO |
| `check` | `no_last_close` | 163 | 84 | 0 | ADCT@2010-12-19; ANAT@2020-07-12; TAHO@2019-03-04 |
| `check` | `no_form25` | 139 | 139 | 0 | RHD@2009-05-29; SSCC@2009-01-30; IAR@2009-03-31 |
| `check` | `no_last_trade_date` | 131 | 52 | 0 | ADCT@2010-12-19; ANAT@2020-07-12; CI@2018-12-31 |
| `check` | `successor_unknown` | 129 | 129 | 0 | CBL@2020-11-04; PRE@2016-03-28; GAS@2016-07-11 |
| `check` | `delist_date_approx` | 123 | 123 | 0 | TMA@2008-09-29; CBL@2020-11-04; HSC@2023-06-20 |
| `check` | `form25_unclassified` | 118 | 118 | 0 | AIG@2012-12-13; LO@2015-07-05; AVT@2018-05-17 |
| `check` | `form25_unmatched` | 78 | 78 | 0 | TMA@2009-01-25; AON@2020-04-11; CCU@2008-08-10 |

`git diff --stat -- output/` confirmed only `review.csv` (195 lines
changed), `review_summary.csv` (10 lines changed, still 32 rows),
`run_manifest.json` and `run.log` changed; `delistings.csv` and the other
four tables are byte-identical to before. All 58 `ended_without_delisting`
rows verified `severity == fix`. The follow-ups the controller declined to
implement now (override-CSV exit-1 parity, `form25_unmatched`/
`form25_unclassified` escalation on securities with no delisting row, an
offline re-triage tool, a stale-decision prune tool, a bucket override) are
recorded in `final-fix.md`, not implemented here.

## Code-review fixes (2026-09-25)

A two-axis review of `main...HEAD` (Standards + Spec) found six items to fix
before merge. Each is FIXED, in its own commit with offline tests; the warm
rerun (two passes, the second 0 SEC requests, exit 0) and the verifier give the
numbers above. Against the round-3 tables: 6 `sec_id`s changed, delistings
+9 / -2 (1,004 → 1,011), review.csv 766 → 805 rows (`fix` 151 → 187, `check`
615 → 618, info-only hidden 454 → 465), verifier 1 disagreement of 905.

1. **Other companies' CUSIPs and FIGIs on stale or backfilled eras: FIXED
   (4f4be68).** An era's FTD CUSIP was checked against its names only when two
   eras shared a date, so a stale snapshot era took the next holder of its
   ticker. Now (spec D21) an era takes an FTD CUSIP only when a fails row of it
   names the era's company, by its observed names or its issuer's EDGAR names,
   current and former (`names.description_matches`, looser than `names_agree`:
   SEC truncates and abbreviates descriptions and keeps old names for years);
   an era with no issuer CIK also takes a CUSIP an era with a known issuer took.
   Checked offline on all 2,660 eras before the rerun: 14 eras change, all 14
   the other company's CUSIP; none of the control set (AAPL, JNJ, MSFT, XOM,
   DELL, DOW, FOXA, GOOG, MDLZ, MO, LUMN/CTL, SGEN, CLF, WAB, GE, TPR) changes.
   - **Six `sec_id`s leave another company's FIGI** for the issuer placeholder:
     Clear Channel's stale 2008-09 era (CCU: Cervecerías Unidas ADR →
     CIK739708-COMMON), Station Casinos (STN: Stantec → CIK898660-COMMON),
     ServiceMaster (SVM: Silvercorp → CIK1052045-COMMON), Avaya (AV: Aviva ADR →
     CIK1116521-COMMON), Northeast Utilities' backfilled 2012-14 ES era
     (EnergySolutions → CIK72741-COMMON) and Applera's stale 2009 ABI era
     (Safety First Trust → the existing CIK77551-COMMON).
   - **CUSIP only:** Armor Holdings (Accretive Health's), Triad Hospitals
     (Thomson Reuters'), Federated's backfilled FHI era (First Trust Strategic
     High Income's), Bear Stearns' stale era (an Elements ETN's), News Corp's
     NCRA (Nocera's), Cytyc (Cytta's), Era Group's ERA (Era Group's own CUSIP on
     old Bristow's CIK, see below) and Truist's backfilled 2012 TFC era (a
     Shelton fund's).
   - Federated's ticker history drops from 86 flipping FII/FHI rows to 12 (the
     rest come from the five backfilled FHI observations of 2012-14) and its
     CUSIP history from 67 rows to 1; BB&T loses its TFC flips.
   - With the other companies' fails rows gone from their sightings, 5 stale
     eras now get their real 2007 delisting through `observed_after_delisting`:
     Triad (merger, $54.00), Armor Holdings (merger, $88.00), Cytyc (merger,
     $16.50 cash leg, no close), Avaya and ServiceMaster (304: both went private
     and kept filing, the frozen continued-filings rule). Clear Channel's own line
     gets its 2008 Form 25 (304, same reason) now that no second line of CIK
     739708 was alive then, and News Corp's class A its 2008 NYSE → Nasdaq move
     (304), no longer blocked by the NCRA placeholder's borrowed rows.
   - Two rows go and two fallback rows come: ES 2014 (304 on EnergySolutions'
     FIGI) is gone, the Northeast Utilities placeholder being listed today
     (EDGAR lists ES for CIK 72741); ERA's 2019 liquidation (old Bristow's
     bankruptcy, carried to 2020 by Era Group's fails rows) becomes a 2013
     fallback 304 at its one observation, and Station Casinos gets a fallback
     304 at its last stale sighting (2009-06-08), its 2007 Form 25 not picked by
     the frozen-tail rule.
   - FNM, FRE and UHALB carry their CUSIP on the observations
     (`data/observations.csv`): their descriptions are a brand (FANNIE MAE,
     FREDDIE MAC) or an old name with no issuer CIK (AMERCO), which no name
     check can tie to the observed name. Their FIGIs and CUSIP ranges are
     unchanged (the CUSIP rows' source reads `observation`).
2. **`ended_without_delisting` next to Form 25 rows: FIXED (dad4af8).** Every
   security neither listed today nor delisted now has the row (spec 8.10): 58 →
   93. 42 are new next to `form25_unmatched`/`form25_unclassified`/
   `form25_unreadable` rows (Sprint Nextel, Hertz, UAL, CBS B, Merrill, Freddie
   Mac, the Liberty tracking stocks, …), 1 is the new Clear Channel placeholder,
   and 8 left (the stale eras above that now have a delisting or a new
   `sec_id`).
3. **`no_figi` not in review.csv: documented (0dfd6ae).** Spec §17 records the
   deviation: `no_figi` is `info`; `securities.csv` lists every placeholder
   (`figi_source=placeholder`, 165) and `review_summary.csv` counts them.
4. **Involuntary (b) notices counted as confirmed: FIXED (974360b).** Every date
   read from a rule 12d2-2(b) notice is the decision day and needs MIDAS or a
   halt: 6 rows gain `last_trade_date_unconfirmed` (PMI 2012, Colonial BancGroup
   2009, IndyMac 2008, Washington Mutual 2008, IAR 2009, SPNV 2020; all
   before MIDAS or without a MIDAS/halt answer), dates unchanged. `last_trade_date_unconfirmed` 99 → 105 (+6, and the fallback rows
   of item 1: +STN, +ERA, -ES, -ERA 2019).
5. **OpenFIGI outage exits as a refusal: FIXED (a0ad424).**
   `OpenFigiUnavailable` (timeouts/5xx after retries) stops the run before any
   table is written, caches nothing, never becomes a placeholder, and exits 1
   with "OpenFIGI unavailable after retries; no outputs written; rerun later".
   Not met in this run.
6. **Non-atomic cache writes: FIXED (d43a74c).** OpenFIGI answers and SEC index
   pages are written through `edgar.write_atomic`. No output effect.

New residuals, all visible in review.csv: ERA's era sits on old Bristow's CIK
73887 (the snapshot backfilled "BRISTOW GROUP INC" onto Era Group's ERA) and
needs a `cik` pin to Era Group's own CIK; Clear Channel's and Station Casinos' stale eras
are separate placeholders of their issuers (`ended_without_delisting` for CCU's);
the Northeast Utilities placeholder shares ES with Eversource from 2015
(`ticker_shared`; FIXED in round 2: one security, BBG000BQ87N0, from 2012); and,
as before this round, a security whose only delisting
predates its first sighting (now 29, `observed_after_delisting`) has no
`ticker_history` row.

## Code-review fixes, round 2 (2026-09-25)

A second two-axis review found two items to fix before merge. Both are FIXED,
with offline tests; the warm rerun (second pass: 0 SEC requests, exit 0) and
the verifier give the numbers above. Against the round-1 tables: 21 eras
change `sec_id` (19 placeholders merge into their issuer's FIGI line, 3 dead
FIGI lines join the table), securities 2,287 → 2,271, delistings 1,011 →
1,000 (11 rename and placeholder-end 304 rows gone, 3 re-keyed), review.csv
805 → 782 (`fix` 187 → 187, `check` 618 → 595, info-only hidden 465 → 446),
verifier 1 disagreement of 903 (IAC 2021, unchanged; OK 901 → 899,
WEAK_no_delist_form 106 → 97).

1. **FIGI acceptance ignored the issuer's EDGAR names (spec §8.3): FIXED
   (1ea4fd8, 25dde28).** A ticker or name-search hit was accepted only when its
   name agreed with the era's observed names, so an era seen under an old name
   (Northeast Utilities under ES in 2012) never matched Bloomberg's line under
   today's name (EVERSOURCE ENERGY) and fell to a duplicate placeholder, whose
   end was then read as a rename coded 304. Now the issuer's EDGAR names
   (current and former, the set the D21 CUSIP check already reads) are added
   when the observed names fail. A candidate only those names accept is
   dropped when (a) an era of another known issuer is confirmed on it by CUSIP
   or pin, (b) an era of the same issuer and class is confirmed on another
   composite over overlapping dates, or (c) taking it would leave a same-class
   sibling era alone on the issuer's placeholder. The CUSIP route is unchanged.
   - **Checked era by era** (cache-only replay over all 2,660 eras): 21 eras
     move, each from its issuer's placeholder to that issuer's own line, same
     CIK and class, CUSIPs unchanged: AGNC 2014-16 (American Capital Agency),
     ANN 2008-09 (AnnTaylor Stores → Ann Inc), CBE 2008-09 (Cooper Industries
     Ltd → plc), CLF 2012-14 (Cliffs Natural Resources), CNO 2008-09
     (Conseco), CNX 2008-17 (CONSOL Energy), CXW 2008-09 and 2014-16
     (Corrections Corp of America), EQT 2008-09 (Equitable Resources), ES
     2012-14 (Northeast Utilities → Eversource BBG000BQ87N0), ICE 2008-13 (old
     IntercontinentalExchange; the resolver gives its eras the holding
     company's CIK 1571949, as before), NTAP 2008 (Network Appliance), PVH
     2008-09 (Phillips-Van Heusen), RGA 2008 (Reinsurance Group of America,
     abbreviated), SM 2008-09 (St Mary Land), SWK 2008-09 (Stanley Works), TXU
     2008-09 (TXU's own dead line, renamed Energy Future Holdings with its
     issuer), WEC 2008-09 and 2014 (Wisconsin Energy), WPG 2015 (WP Glimcher)
     and WYND 2012-14 (Wyndham, backfilled). CCU, STN, SVM, AV stay issuer
     placeholders; round 1's control set is unchanged apart from CLF 2012.
   - **Rejected by the guards** (each keeps its round-1 placeholder): GGP 2008
     (old General Growth Properties is now "GGP, Inc.", the name of the new
     issuer's line BBG000BG3HG3, which GGP 2017 confirms by CUSIP: rule a); J
     2012 (Jacobs Engineering under a backfilled J matches today's Jacobs
     Solutions line, while its JEC era is confirmed on BBG000BMFFQ0: rule b);
     ACE LTD under CB 2012-14, Gannett under TGNA 2012-14 and Weight Watchers
     under WW 2012-13 (backfilled tickers whose real-ticker eras ACE, GCI and
     WTW find no FIGI: rule c). A first rerun without rule c moved the last
     three and split each stock across two `sec_id`s: a new rename-304 row for
     the ACE placeholder, old Gannett's 2015 row linked to new Gannett as
     successor, and a spurious 2013 exit for Weight Watchers; rule c (25dde28)
     keeps them together.
   - **Securities:** 19 placeholders gone, 3 FIGI lines added (TXU
     BBG000BVW841, AnnTaylor BBG000C9N6Q9, Conseco/CNO BBG000Q1GK24); 16 FIGI
     securities take the moved eras (ES, CLF, WEC, CXW, NTAP, SM, CNX, AGNC,
     EQT, ICE, PVH, RGA, SWK, CBE, WPG, Wyndham). `figi_source` reads `ticker`
     on 10 of them now, the label of their earliest era; Cooper's
     `share_class` reads COMMON (was CLASS A) for the same reason (both FIXED
     in round 3); WPG's name is its latest observation, WP GLIMCHER INC.
   - **Delistings:** 11 rows gone: the rename rows of NTAP 2008, CNO 2010, SM
     2010, WEC 2015, AGNC 2016, CXW 2016, CLF 2017 and CNX 2017, Cooper's 2009
     redomicile row, Wyndham's backfilled 2014 end and Washington Prime's 2015
     rename row. 3 are re-keyed onto the FIGI (TXU 2009, AnnTaylor 2011, WPG
     2016, same content). No payout, DLRET or merger row changes. 304 rows 318
     → 307; `successor_unknown` 133 → 127; `last_trade_date_unconfirmed` 105 →
     95; `member_name_mismatch` 31 → 28.
   - **Review:** `ticker_shared` 41 → 31 (a placeholder and its own FIGI line
     no longer share CLF, AGNC, CXW, ICE, EQT, ES, PVH, WEC, RGA, SWK);
     `form25_unmatched` 77 → 75 (Cliffs' 2010 rights-plan Form 25 and RGA's
     2008 class A/B Form 25s have one security to consider; RGA's is no
     delisting, since the next 10-K still names NYSE); `no_figi` 175 → 156.
   - **Ticker history:** each merged line now starts at its first sighting
     (ES from 2012-06-29, CXW, SWK, … from 2007-08); Wyndham's range flips to
     WYND on the five 2012-14 dates the snapshots list it as WYND (and gets a
     `ticker_unconfirmed` row, moved from the placeholder).
   - Spec §17 records the guards and, as the brief ruled, that §8.3's third
     route (a name matching the acquirer or successor in the delisting 8-K) is
     not built.
   - `run()`'s docstring no longer says an OpenFIGI outage exits 2 (it exits 1).
2. **Cache writes that were still not atomic: FIXED (53f140b).** MIDAS quarter
   summaries (a cut-off gzip raised on the next read), Nasdaq halt days (a
   cut-off XML raised), LLM answers and the SEC ZIP downloads now go through
   `edgar.write_atomic`, which takes bytes as well as text (temp file, fsync,
   rename, directory fsync). The download no longer writes a `.part` file;
   `clean_orphan_temps` removes a leftover `.part`, and every cache writer
   (FTD, MIDAS, halts, OpenFIGI, LLM) cleans a dead run's temp files in its
   directory at start. The remaining `open(..., "w")` calls in `src/` write
   `write_atomic`'s own temp file, the output tables (`store.replace_on_success`)
   or a caller's observations CSV (`observations.write_observations`), none a
   cache. No output effect.

New residuals, all visible in review.csv or the tables: the three backfilled
duplicates (ACE/CB, GCI/TGNA, WTW/WW) and J 2012 keep their placeholders, since
the real-ticker era of each finds no FIGI (OpenFIGI knows neither its old CUSIP
nor its old ticker); GGP 2008 keeps its placeholder and 2009 bankruptcy row;
AnnTaylor's 2011 rename still ends its sightings (its 2015 merger is not
reached); CNO's open CUSIP range is Conseco's retired one.

## Code-review fixes, round 3 (2026-09-26)

A third two-axis review. The items that change an output are listed with every
changed row; the rest change no table (checked by pinned warm reruns, below).

1. **`figi_source` and `share_class` came from a security's earliest era
   (spec §7.1, §8.4): FIXED (bd1dcbd).** `build_securities` now takes
   `figi_source` from the security's strongest era (pin, then CUSIP, then
   ticker, then name search, then placeholder; the earliest era on a tie) and
   `share_class` from that era; when that era's name gives no class, from the
   earliest other era of the security that names one. Against the round-2
   tables:
   - **`securities.csv`, `figi_source`:** 100 rows go from `ticker` to `cusip`
     (FIGI sources cusip 1,976 → 2,076, ticker 149 → 49, placeholder 146
     unchanged). Each is a security whose earliest era was resolved by its
     ticker and a later era by a CUSIP: 14 of round 2's moved lines (ES, CLF,
     WEC, CXW, NTAP, SM, CNX, AGNC, EQT, ICE, PVH, RGA, SWK, CBE; round 2's note
     counted 10) and 86 others, from American Tower and AIG to Aptiv. No
     `sec_id` changes.
   - **`securities.csv`, `share_class`, 5 rows:** Cooper Industries
     BBG000BF2KK4 COMMON → CLASS A (its CUSIP-confirmed plc era, "COOPER
     INDUSTRIES PLC CL A"); Ralph Lauren BBG000BS0ZF1 COMMON → CLASS A ("RALPH
     LAUREN CORP CLASS A", CUSIP-confirmed; the earliest era is "POLO RALPH
     LAUREN CO"); Discovery BBG000CHWP52 COMMON → SERIES A ("DISCOVERY INC
     SERIES A", CUSIP-confirmed; the earliest era is "DISCOVERY HOLDING CO");
     Zillow BBG009NRSWJ4 CLASS A → CLASS C (the line is Zillow's class C, Z:
     its CUSIP-confirmed era is "ZILLOW GROUP INC CLASS C", its earliest,
     ticker-resolved, Zillow Inc's "ZILLOW INC CLASS A" of 2014); CME Group
     BBG000BHLYP4 COMMON → CLASS A (its strongest era, the earliest of its
     CUSIP-confirmed ones, is "CHICAGO MERCANTILE HLDGS", which names no class;
     its later era "CME GROUP INC CLASS A" gives the class through the
     fallback). SBA
     Communications keeps CLASS A: its CUSIP-confirmed era is cut off at "SBA
     COMMUNICATIONS REIT CORP CLASS", and the fallback takes CLASS A from its
     earlier eras.
   - **Discovery Series A, through Form 25 class matching** (the finder
     matches a Form 25's class text against each security's `share_class`).
     With DISCA read as COMMON, Discovery's two 25-NSEs of 2022-04-08 were both
     "ambiguous class" for DISCA and DISCK. Now the Series A filing
     (0001354457-22-000229) matches DISCA:
     - `delistings.csv` +1 row: BBG000CHWP52 2022-04-18, DISCA,
       `exchange_transfer` 304 (medium), last trade 2022-04-08 (MIDAS), close
       24.43, NASDAQ, DLRET 0 (`exchange_transfer_zero`), no review flag. Its
       `successor_sec_id` is the security itself: fails rows of its CUSIP
       25470F104 continue after the effective date, so the finder reads the
       security as continuing. The handling layer skips such a row (no label,
       exit or correction). DISCK's row, unchanged, names Warner Bros.
       Discovery (BBG011386VF4) as successor.
     - `ticker_history.csv`: DISCA's last range ends 2022-04-08 on NASDAQ (was
       2022-04-12, no exchange).
     - `cusip_history.csv`: 25470F104 ends 2022-04-08 (was open to 2025-12-30,
       from those later fails rows).
     - `review.csv`: the two `form25_unmatched` rows of 2022-04-18 (DISCA,
       DISCK) no longer cite the Series A filing, only the Series B one
       (0001354457-22-000230). Row count, severities and `review_summary.csv`
       unchanged.
   - Counts: delistings 1,000 → 1,001 (exchange_transfer 307 → 308; MIDAS last
     trade 530 → 531; efts resolution 170 → 171); check 4 874 delisted + 84
     review → 875 + 83; successor links 180 → 181 (self 126 → 127).
     `payouts.csv`, `review_summary.csv` and every other row are unchanged.
2. **Spec §17 notes** (no output change): where `share_class` comes from and
   the strongest-era rule; that D21's check of a caller-supplied observation
   CUSIP is not built (FNM, FRE and UHALB rely on taking it as given); guard
   (c)'s wording (it holds whatever the two eras' dates).
3. **CLI** (no table change): `--as-of YYYY-MM-DD` pins the run date
   (544fb26), which every rerun above used; exit codes (afe366b): 1 only for
   an unexpected crash, 4 for an OpenFIGI outage, 2 with one line naming the
   file and line for a bad input file, including override rows that match no
   delisting.


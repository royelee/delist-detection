# Acceptance run — security master and delistings (2026-09-23, rerun 2026-09-24)

Spec: `docs/superpowers/feature-spec.md` §13. Run on 2026-09-24 against live SEC
EDGAR, SEC fails-to-deliver (FTD), SEC MIDAS, the Nasdaq halt feed, OpenFIGI and
OpenAI (`--extract-merger-terms-llm`, model from `CHAT_MODEL`). This note describes
the run after review fix round 2, on the SEC speed-up (merged at 7779196) plus the
round-2 fixes listed below.

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
latency, and degraded-answer counts. It differs between runs by design. Its code
version reads `0620016-dirty` because the previous run's tables were uncommitted
in the tree when the run started.

**Speed.** This round made four full runs, all with 4 SEC workers:

- **First run** (code `da61707`, about 28 minutes). The caches had been written by
  the pre-speed-up code, which never cached empty company searches and wrote EFTS
  answers in an older format. So this run sent 1,178 SEC requests: company search
  750, full-text search 356, submissions 39, archives 33. Issuer resolution sent
  1,011 of them and took most of the run. Company-search latency was p50 2.1 s,
  p95 27.5 s, max 30 s; SEC's company search slows under sustained traffic. One
  warm-thread read failed (`warm_degraded: failed_request 1`, manifest only); no
  row rests on a degraded answer (`resolution_degraded` 0).
- **Three reruns** after the last three fixes (8b0e96e, 8ec70ca, 0620016). Each sent
  0 SEC requests and took about 5 minutes.
- **Before the speed-up**, a warm rerun took 30 to 60 minutes.

The tables below are from the last rerun. The verifier ran once, on the first
run's tables. The three reruns changed only these, none of which the verifier
reads:

- `acquirer_sec_id` on 5 merger rows;
- the start of 2 acquirer ticker ranges;
- review rows.

The delisting rows' identity and classification columns are the same.

## Input

`data/observations.csv`, built from the `qlib_practice` iShares Russell 1000 and
Wikipedia snapshot CSVs (equities only).

| | Count |
|---|---|
| Observations | 35,955 |
| Tickers | 2,219 |
| Snapshot dates | 36 (2008-01-16 .. 2026-06-30) |
| Rows with a `name` / `cusip` | 35,955 / 0 |
| Rows with a `cik` pin | 1,654 (162 pin groups, table below) |
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
  - Avaya and Armor Holdings stay `ended_without_delisting`: the classifier's
    frozen-tail rule does not pick their 2007 Form 25 for a 2009 anchor.
  - Laureate (LAUR, taken private 2007) merged into today's Laureate Education
    security.
- **Snapshot name typos and abbreviations.** "AMERIPRISE FINANCE INC", "DUN BRADST
  HLDG INC", and others fail the resolver's name checks; the wrong answers they led
  to are pinned.

## Output tables

| Table | Rows |
|---|---|
| `securities.csv` | 2,287 (2,271 observed, 16 added acquirers) |
| `ticker_history.csv` | 3,013 |
| `cusip_history.csv` | 2,616 |
| `delistings.csv` | 992 |
| `payouts.csv` | 623 |
| `review.csv` | 1,213 |

The old `output/dlret.csv` and `output/delist_classifications.csv` are removed.

**Delistings by bucket:** merger 623, exchange_transfer 302, liquidation 48,
unknown 12, compliance_failure 6, expiration 1.

**Delistings by year:** 2006 1, 2007 24, 2008 38, 2009 39, 2010 32, 2011 41,
2012 36, 2013 39, 2014 37, 2015 67, 2016 86, 2017 63, 2018 70, 2019 53, 2020 61,
2021 62, 2022 61, 2023 46, 2024 40, 2025 54, 2026 42.

**Last trade date source:** MIDAS 523, EX-99.25 notice 193, 8-K item 3.01 31,
Nasdaq halt 27, none 218.

**DLRET method:** cash_only 311, exchange_transfer_zero 302, stock_only 123,
cash_plus_stock 82, assumed_par 58, needs_last_trade 34, shumway_nyse_amex 30,
abstain_no_consideration 23, shumway_nasdaq 17, unknown 12.

**FIGI source (securities):** cusip 1,992, ticker 136, placeholder 159.

**Resolution source (delistings):** name_search 540, efts 170, company_tickers 126,
cik_map (pins) 104, manual 37, efts_frequency 12, efts_name_mismatch 1, rename 1,
none 1.

**Review flags** (rows carrying each):
- no_last_close 170, no_figi 169, ftd_close_lagged 131, no_last_trade_date 131,
  no_form25 128
- resolved_by_current_ticker_map 126, successor_unknown 123, ftd_close_prior 119,
  form25_unclassified 118, delist_date_approx 113
- last_trade_date_unconfirmed 92, form25_unmatched 78, ticker_unconfirmed 63,
  ended_without_delisting 59, merger_at_par 50
- terms_gate_failed 49, ticker_shared 43, last_trade_date_conflict 41,
  observation_unresolved 32, member_name_mismatch 31
- acquirer_close_lagged 29, observed_after_delisting 24, llm_gate_failed 15,
  payout_gate_failed 12, no_evidence_default 12, resolved_by_cik_map 12
- observation_conflict 6, distress_at_normal_price 3, bankruptcy_before_merger 1,
  bankruptcy_tag_unconfirmed 1, resolved_by_manual_override 1
- resolution_degraded 0, error 0

`resolved_by_current_ticker_map` (126) is the restored pre-refactor flag on every
delisting whose CIK came from `company_tickers.json`. It is noise by design here.

## Acceptance checks (spec §13)

| # | Check | Result |
|---|---|---|
| 1 | `pytest` offline, golden set green | PASS: 988 passed |
| 2 | Full run writes all six files, no crash, prints coverage | PASS: exit 0, no `error` or `resolution_degraded` rows |
| 3a | AET: `sec_id` BBG000FJLFX8, one merger, last trade 2018-11-28, close 212.70 | PASS: MIDAS 2018-11-28, close 212.70 |
| 3b | ALTR (Altair): last trade 2025-03-25 | NOT IN INPUT (see below); PASS on a supplementary run |
| 3c | SAVE: last trade 2024-11-15 | PASS: MIDAS 2024-11-15 (it was the notice's 2024-11-18 before d1dd0e0) |
| 3d | MON: Monsanto 2018, no 2022 row | PASS: merger 2018-06-17, last trade 2018-06-06 |
| 3e | HOT, PE, TSS merger, not expiration | PASS: all three code 231 |
| 3f | Apache: no delisting from the 2020 Chicago withdrawal | PASS: only the 2021-03 APA holdco transfer, linked to APA Corp's line |
| 3g | GOOG / GOOGL two securities | PASS: BBG009S3NB30 / BBG009S39JX6 |
| 4 | Every observed security listed today, delisted, or in review | PASS: 2,271 = 1,312 listed + 867 delisted + 92 review, 0 missing (see below) |
| 5 | `verify_against_web.py` agreement ≥ 98.9% | PASS: 1 of 896 verifiable rows disagrees (99.9%). 96 rows cannot be checked (no Form 25/15 in the window). OK only: 892 / 992 = 89.9% |
| 6 | `last_trade_close` on ≥ 90% of 2004+ merger delistings | PASS: 566 / 623 = 90.9% with look-back closes; 485 / 623 = 77.8% without them |

**Check 4.** "Listed today" means an open `ticker_history` row, i.e. `listed_today`
is true. It has three branches:

- **A FIGI security with a known CIK** needs both:
  - an OpenFIGI exchange venue;
  - its ticker (or OpenFIGI's) on a major exchange in the issuer's EDGAR
    submissions.
- **A FIGI security with no CIK:** OpenFIGI alone decides.
- **A placeholder** (`CIK<cik>-<CLASS>`, no FIGI, so no venue to ask): it is listed
  only when its issuer's EDGAR submissions list one of the placeholder's own
  tickers on a major exchange.

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
- This round leaves the 114 rows unchanged.

Three securities still have both a definitive delisting and an open range:

- Peabody (BTU, 2016 bankruptcy);
- Garrett Motion (GTX, 2020);
- Chesapeake (CHK, 2020).

Each went bankrupt, and its eras before and after resolved to one FIGI, which is
listed today. The delisting belongs to the pre-bankruptcy line.

**Check 6.** 81 of the 566 merger closes are look-back closes
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
file). Final verdicts: OK 892, OK_recycled_ticker 3, WEAK_no_delist_form 96,
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
- **96 WEAK_no_delist_form.** No evidence either way. They are `exchange_transfer`
  rows from the no-Form-25 fallback whose issuer filed no Form 25/15 in the window
  (renames, reverse splits, holdco reorganizations; see the 304 residual below),
  plus Tidewater's 2017 bankruptcy.
- **Earlier passes**, all explained and fixed:
  - 27 WEAK_no_ma_items: real mergers whose SC 14D9 / DEFM14A / 425 filings sat in
    older submissions files (d6021c6).
  - 6 WEAK_no_form15: bankruptcies without a Form 15, which the 8-K 1.03 confirms
    (d6021c6).
  - 6 MISMATCH_name: camelCase "BlackRock", and holdco reorganizations carrying the
    new holdco's CIK, now pinned per era.

## Successor links

`successor_sec_id` is filled on 179 of the 302 `exchange_transfer` rows:

- 126 point to the security itself (it kept trading after an exchange move).
- 53 point to another security of the run, all found by the same-issuer /
  same-ticker rule (024fddc, 700e6d5, 746f2ac). Examples: APA 2021 → APA Corp's
  line, Charter 2016, Apollo 2022, Dell's DVMT tracking stock, Discovery K,
  Brookfield Renewable 2025, and Liberty Live's Series A 2025 → Liberty Live
  Holdings' LLYVA.
- 123 transfers keep `successor_unknown`.

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

Progress across runs: run 1 (before these fixes) had 16 `error` rows, 794
delistings, 75.5% merger closes and failed SAVE. This run has 0 errors, 0 degraded
rows, 992 delistings, and passes every check the input allows.

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

**The pins: 162 groups on 1,654 rows** (one table row each):
- 116 from the first pass, including 3 stale-snapshot eras.
- 7 for the cases the reverted resolver rule had fixed: AMP, DDS, GE, M, ORLY, PKG,
  SIRI.
- 33 for 15 reorganized issuers (old and new line each) and the Liberty Live
  split-off.
- 6 in fix round 2: MSGE, STL, CLNY, VIA-B, VIAB, VIA.

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

## Residuals for the user

Carried from the review, updated for fix round 2.

- **Resolver precedence for today's ticker-map holder:** FIXED by reverting it
  (d17ddf1); the 8 cases are pins.
- **Look-back closes without their age:** FIXED with `ftd_close_prior:<n>`.
  - 81 merger closes are look-backs; 43 are older than one trading day.
  - Check 6 without them: 77.8%.
  - The look-back closes still feed DLRET.
- **Dead FIGIs counted as listed today:** FIXED for 45 of 48 (fd0b8be).
  - 3 bankrupt and relisted securities (BTU, GTX, CHK) remain open, because their
    old and new lines share one FIGI.
- **No-Form-25 `exchange_transfer` (304) rows:** STILL OPEN. The same 114 rows as in
  round 1.
  - Round 1's increase from 86 came from the placeholder branch of `listed_today`
    (see check 4).
  - 46 of the 114 have a successor in the run; 68 do not.
  - The 68, by reading the names:
    - about 37 renames, holdco reorganizations or spin-offs whose new line starts
      outside the window or is not in the run (ITT, Yahoo → Altaba, WellPoint →
      Anthem, News Corp 2013, Delphi → Aptiv, Northeast Utilities → Eversource,
      TEGNA, Ensco → Valaris, …);
    - about 15 reverse splits or recapitalizations with a new CUSIP (Rite Aid 2019,
      Supervalu 2017, Frontier 2017, Windstream 2015, McClatchy 2016, YRC 2010, …);
    - 8 stale or backfilled snapshot eras (TXU, XM, Sovereign, PEAK/WYND/IAC 2014,
      UAC-C, SunPower 2009);
    - 5 mergers whose target was the legal survivor or kept filing
      (Schering-Plough → Merck, American Capital, Foundation Coal, McDermott,
      Engility);
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
- **Identity errors that a single shared name word hides:** PARTLY FIXED.
  - The pins cover every case found (JNPR, Oasis, and in round 2 SPHR/MSGN, STL,
    CLNY, Viacom, ASH).
  - The table-wide check lists 36 remaining low scores, all abbreviations or renames
    with the right CIK.
  - Not every one-word match was reviewed by hand.
- **Possessive apostrophes:** FIXED (40d6077, then c67e68a). There are 31
  `member_name_mismatch` rows.
  - The previous note blamed FI 2021 on the snapshot's name. It came from the
    tokenizer: 40d6077 joined "Frank's" into FRANKS, which no longer met the
    snapshot's "FRANK S". c67e68a keeps both spellings, and FI 2021 is cleared.
  - One is new: VIACA 2019, where the snapshot writes the post-merger name
    "VIACOMCBS INC CLASS A" against the right CIK 813828.
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
- **LLYVK's successor is itself:** STILL OPEN (new).
  - Fails rows under the retired CUSIP run past the delisting's 5-day continued
    window, so the transfer reads as continued trading.
  - The new LLYVK line (BBG01YYX1Z14) is not linked.
- **CCO 2019 → IHRT:** FIXED (da61707). `successor_unknown`.
- **Liberty SiriusXM's letter-less Series C lines and CBS's Class B placeholder:**
  STILL OPEN, in review as `form25_unmatched` (8ec70ca, 0620016). Their FIGI name
  carries no class letter, or a FIGI line and a placeholder hold the same stock.
- **Mergers without a close:** STILL OPEN: 57 of 623.
  - 39 have no last trade date. Mostly these are Nasdaq deals whose Form 25-NSE
    carries an empty EX-99.25 before MIDAS, or has no MIDAS row, and has no dated
    3.01 8-K.
  - The rest have no priced FTD row within ten trading days before the last trade.
- **`form25_unclassified` (118):** STILL OPEN. These are structured notes, ETNs and
  "See Attached" Form 25s of issuers with many debt lines (BAC, JPM, GS, AIG); none
  is a common-stock delisting.
- **`form25_unmatched` (78):** PARTLY FIXED (113 → 78). The rest are ambiguous-class
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
  - A warm rerun here sent 0 SEC requests and took about 5 minutes.
  - Resolver misses are still never cached, by design.
- **Stale submissions can hide a new Form 25:** STILL OPEN (known follow-up). The
  delisting finder reads submissions without a freshness bound, so a copy cached
  before a Form 25 can hide it in the first run after that delisting. This is
  survivorship-relevant.
- **Company search keeps only its first match:** STILL OPEN (known follow-up).
  `_parse_company_atom` returns only the first company of a multi-match answer, so
  the name-search tier can miss the right company.
- **CLAUDE.md:** the speed-up branch updated it (cache version 3, 980 tests). The
  suite is now 988; the controller updates CLAUDE.md.

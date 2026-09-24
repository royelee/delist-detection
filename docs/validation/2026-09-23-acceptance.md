# Acceptance run — security master and delistings (2026-09-23)

Spec: `docs/superpowers/feature-spec.md` §13. Run on 2026-09-23 against live SEC
EDGAR, SEC fails-to-deliver (FTD), SEC MIDAS, the Nasdaq halt feed, OpenFIGI and
OpenAI (`--extract-merger-terms-llm`, model from `CHAT_MODEL`).

```bash
PYTHONPATH=src python scripts/classify_universe.py --observations data/observations.csv --extract-merger-terms-llm
PYTHONPATH=src python scripts/verify_against_web.py
```

Final run: exit 0, no `error` rows. Log: `output/run.log`.

## Input

`data/observations.csv`, built from the `qlib_practice` iShares Russell 1000 and
Wikipedia snapshot CSVs (equities only).

| | Count |
|---|---|
| Observations | 35,955 |
| Tickers | 2,219 |
| Snapshot dates | 36 (2008-01-16 .. 2026-06-30) |
| Rows with a `name` / `cusip` | 35,955 / 0 |
| Rows with a `cik` pin | 1,121 (116 pin groups, table below) |
| Rows with a `sec_id` pin | 0 |
| Ticker eras (stage 1 / after the FTD split) | 2,462 / 2,668 |

### Known input issues

- **Two names for one ticker on one date (6 pairs).** CB on 2012-06-29 .. 2014-06-30
  is both ACE LTD and CHUBB CORP; AGN on 2014-06-30 both ALLERGAN INC and ALLERGAN
  PLC. One snapshot source backfilled today's ticker. Every observation is kept;
  `review.csv` has one `observation_conflict:<date>` row per pair (6). The CB rows
  are pinned: ACE LTD to Chubb Ltd (896159), CHUBB CORP to Chubb Corp (20171).
- **Backfilled tickers (12).** APTV, CBRE, IAC, J, LUMN, PEAK, QRTEA, SPXC, TCF, TT,
  UAA, UAC-C appear in the 2012-2014 snapshots under a ticker adopted later (Delphi
  traded as DLPH then). Each era is flagged `ticker_unconfirmed` (no FTD row under
  that ticker in its span); most merge into the security that later carried the
  ticker and show up as `ticker_shared` / overlapping ranges.
- **Stale 2008-09 snapshots (34 eras).** The 2008-01-16 .. 2009-06-08 snapshots still
  list securities that ended in 2007 (A.G. Edwards, Alltel, Avaya, Hilton, First
  Data, Dow Jones, …). Their Form 25s predate the first sighting, so the finder's
  scan window skipped them and each ended as `ended_without_delisting`. Fixed
  (981e45d, see below): 31 of the 34 now have their delisting, 24 of them through
  the new `observed_after_delisting` path. The other three: Avaya and Armor
  Holdings stay `ended_without_delisting` (the classifier's frozen-tail rule does
  not pick their 2007 Form 25 for a 2009 anchor), and Laureate (LAUR, taken
  private 2007) merged into today's Laureate Education security, which is listed.
- **Snapshot name typos.** "AMERIPRISE FINANCE INC", "DUN BRADST HLDG INC", …: the
  resolver's name checks fail on them; the resolver fix below covers the listed
  ones.

## Output tables

| Table | Rows |
|---|---|
| `securities.csv` | 2,287 (2,271 observed, 16 added acquirers/successors) |
| `ticker_history.csv` | 3,016 |
| `cusip_history.csv` | 2,615 |
| `delistings.csv` | 933 |
| `payouts.csv` | 604 |
| `review.csv` | 1,192 |

The old `output/dlret.csv` and `output/delist_classifications.csv` are removed.

**Delistings by bucket:** merger 604, exchange_transfer 263, liquidation 48,
unknown 11, compliance_failure 6, expiration 1.

**Delistings by year:** 2006 1, 2007 24, 2008 38, 2009 38, 2010 31, 2011 35,
2012 34, 2013 36, 2014 32, 2015 61, 2016 82, 2017 58, 2018 67, 2019 45, 2020 57,
2021 60, 2022 57, 2023 46, 2024 38, 2025 52, 2026 41.

**Last trade date source:** MIDAS 496, EX-99.25 notice 186, 8-K item 3.01 30,
Nasdaq halt 26, none 195.

**DLRET method:** cash_only 311, exchange_transfer_zero 263, stock_only 112,
cash_plus_stock 82, assumed_par 55, needs_last_trade 33, shumway_nyse_amex 30,
abstain_no_consideration 19, shumway_nasdaq 17, unknown 11.

**FIGI source (securities):** cusip 1,992, ticker 135, placeholder 160.

**Resolution source (delistings):** name_search 502, efts 170, company_tickers 143,
cik_map (pins) 70, manual 35, efts_frequency 12, none 1.

**Review flags** (rows carrying each): no_figi 170, no_last_close 154,
resolved_by_current_ticker_map 143, successor_unknown 135, ftd_close_lagged 127,
no_last_trade_date 121, form25_unclassified 118, ftd_close_prior_day 110,
form25_unmatched 101, no_form25 97, delist_date_approx 85,
last_trade_date_unconfirmed 79, ticker_unconfirmed 63, ticker_shared 55,
ended_without_delisting 52, merger_at_par 47, terms_gate_failed 44,
last_trade_date_conflict 39, observation_unresolved 33, acquirer_close_lagged 29,
member_name_mismatch 25, observed_after_delisting 24, llm_gate_failed 13,
no_evidence_default 11, payout_gate_failed 10, resolved_by_cik_map 7,
observation_conflict 6, distress_at_normal_price 3, bankruptcy_before_merger 1,
bankruptcy_tag_unconfirmed 1.

`resolved_by_current_ticker_map` (143) is the restored pre-refactor flag on every
delisting whose CIK came from `company_tickers.json`; it is noise by design here.

## Acceptance checks (spec §13)

| # | Check | Result |
|---|---|---|
| 1 | `pytest` offline, golden set green | PASS — 735 passed |
| 2 | Full run writes all six files, no crash, prints coverage | PASS — exit 0, no `error` rows |
| 3a | AET: `sec_id` BBG000FJLFX8, one merger, last trade 2018-11-28, close 212.70 | PASS — MIDAS 2018-11-28, close 212.70 |
| 3b | ALTR (Altair): last trade 2025-03-25 | NOT IN INPUT — see below; PASS on a supplementary run |
| 3c | SAVE: last trade 2024-11-15 | PASS — MIDAS 2024-11-15 (was the notice's 2024-11-18 before d1dd0e0) |
| 3d | MON: Monsanto 2018, no 2022 row | PASS — merger 2018-06-17, last trade 2018-06-06 |
| 3e | HOT, PE, TSS merger, not expiration | PASS — all three code 231 |
| 3f | Apache: no delisting from the 2020 Chicago withdrawal | PASS — only the 2021-03 APA holdco transfer |
| 3g | GOOG / GOOGL two securities | PASS — BBG009S3NB30 / BBG009S39JX6 |
| 4 | Every observed security listed today, delisted, or in review | PASS — 2,271 = 1,423 listed + 761 delisted + 87 review, 0 missing |
| 5 | `verify_against_web.py` agreement ≥ 98.9% | PASS — 100.0% (0 of 933 disagree; strict 92.1%) |
| 6 | `last_trade_close` on ≥ 90% of 2004+ merger delistings | PASS — 552 / 604 = 91.4% |

**ALTR (Altair).** The input has no Altair observation: every ALTR row is ALTERA
CORP (2008-01-16 .. 2015-06-30), and Altera's delisting is in the table (merger,
last trade 2015-12-24, close 53.96, payout 54.00). Altair Engineering listed in 2017
and was never an index member in these snapshots. A supplementary run on four
Altair observations (`ALTAIR ENGINEERING INC CLASS A`, 2023-06-30 .. 2024-12-31;
not committed) gives BBG000PN9NB9, merger 231, NASDAQ, last trade **2025-03-25**
(MIDAS), close 111.85, payout 113.00, DLRET +1.03%, flagged
`last_trade_date_conflict` (the closing 8-K asked Nasdaq to suspend trading "at the
close of the market on March 26, 2025", which reads 2025-03-26; MIDAS shows no
exchange volume that day, and MIDAS wins) and `ftd_close_lagged`.

**Agreement rate.** The 98.9% baseline is 456 / 461 on the pre-refactor file, counting
`MISMATCH_*`, `WEAK_no_ma_items`, `WEAK_no_3_01` and `WEAK_no_form15` as
disagreement and `WEAK_no_delist_form` / `no_*` as no evidence either way. Final
verdicts: OK 857, OK_recycled_ticker 2, WEAK_no_delist_form 74. The first pass on
the run-3 table (before d6021c6) was 95.8%: 27 WEAK_no_ma_items, 6 WEAK_no_form15, 6
MISMATCH_name; every one was checked and is explained below.

## Independent verification: every mismatch and weak row

- **27 WEAK_no_ma_items (run 3)** — real mergers the verifier could not see:
  Genentech/Roche 2009, Mellon/BNY 2007, National City/PNC 2008, Wachovia/Wells
  2008, BEA/Oracle 2008, Manor Care/Carlyle 2007, … Their filings sit in older
  submissions files the verifier did not read, and the target filed a tender offer
  (SC 14D9), a merger proxy (DEFM14A) or 425 communications, no 8-K 2.01/5.01. The
  verifier now reads the older files around the date and accepts merger documents
  (d6021c6); all 27 are OK.
- **6 WEAK_no_form15 (run 3)** — bankruptcies that never filed a Form 15 (ITT
  Educational, Wolfspeed, Tidewater, SunPower, Tupperware, Big Lots); the 8-K item
  1.03 confirms each (d6021c6). All OK.
- **6 MISMATCH_name (run 3)** — `BlackRock, Inc.` vs `BLACKROCK INC` (a camelCase
  split made them share no word; d6021c6), and five holding-company reorganizations
  where the security's pre-reorg years were resolved to the new holdco's CIK
  (BlackRock 2024, nCino 2022, DraftKings 2022, IAC 2020, BGC 2023). BLK, NCNO, DKNG
  and IAC are now pinned per era (the old entity's CIK before the reorg, the new
  one after); BGC's name agrees after d6021c6.
- **2 OK_recycled_ticker (final)** — Aaron's 2020 (AAN pinned to Aaron's Inc 706688;
  EDGAR's "AARON'S INC" splits at the apostrophe) and Dun & Bradstreet 2025 (the
  snapshot's abbreviated "DUN BRADST HLDG INC"); both CIKs are right. A third on an
  earlier pass, Oasis Petroleum 2016, had Javelin Mortgage's CIK — a wrong CIK the
  verifier accepted because Javelin filed a Form 25 near the date; it is pinned now.
- **74 WEAK_no_delist_form (final)** — no evidence either way: `exchange_transfer`
  rows from the no-Form-25 fallback (code 304: renames, holdco reorganizations and
  LBOs whose issuer kept filing: Fortune Brands → Beam, Sara Lee → Hillshire, Tesoro
  → Andeavor, Cigna, Xerox, Broadcom, Alltel, TXU, …) whose issuer filed no Form
  25/15 in the window, plus Tidewater's 2017 bankruptcy.

## Fixes made during the run (each with an offline, fixture-backed test)

| Commit | Fix |
|---|---|
| e85353b | docs(data-flow): two-stage era split in the pipeline diagram |
| 981e45d | A Form 25 before a stale first sighting becomes the delisting (`observed_after_delisting`); closes for last trades before the FTD window |
| cf2dc32 | Web verifier paced at 8 req/s; a 403/429 aborts it (exit 2) |
| 4d63d56 | MIDAS 2014 Q2 ships its CSV in a zip inside the zip (16 `error` rows in run 1) |
| ebaa339 | Nasdaq halt feed: parse bytes, the UTF-8 BOM failed every day (136 parse errors in run 1) |
| 5f2ac6f | MIDAS 2016 quarters write the date as a float ("20160104.0"); an empty summary is never cached |
| d1dd0e0 | MIDAS/halt confirmation asks for every ticker the security carried in the window (SAVE → SAVEQ) |
| 19841cc | Close look-back when no FTD row follows the last trade (`ftd_close_prior_day`) |
| 01e58f7 | Issuer-filed text Form 25: class read above its caption, not the rule checkbox (~200 of 315 `form25_unclassified`) |
| 45d7b29 | A rights plan's Form 25 is a rights class, not preferred |
| 041a251 | A merger/liquidation/compliance/expiration delisting ends the security even when sightings follow it (72 securities had a delisting and `ended_without_delisting`) |
| cb77e4b | Resolver: the SEC ticker map's holder beats a name-mismatched EFTS fallback or zero-score frequency winner (Macy's, GE, Ameriprise, O'Reilly, SiriusXM, Dillard's had ETF trusts', Apple's or Vaxart's CIK); resolver cache v3 |
| 9526f6f | Notice wordings "before market open on D" and "suspended by the Exchange on D" |
| 02a7cf0, 029d679 | Close look-back widened to ten trading days; FTD rows loaded to cover it |
| d6021c6 | Web verifier reads the older submissions files around the date and accepts merger documents / bankruptcy 8-Ks as evidence |
| 016e470 | Each era is resolved with its own `cik` pin, not the nearest era's (BlackRock's and DraftKings' pre-reorg lines took the new holdcos' CIKs) |

Progress across runs: run 1 (before these fixes) had 16 `error` rows, 794
delistings, 75.5% merger closes and failed SAVE; the final run has 0 errors, 933
delistings, 91.4% closes and passes every check the input allows.

## Identity corrections (observation `cik` pins)

The resolver's lower tiers (EFTS second-pass fallback, 8-K frequency rank, company
name search) gave about 60 securities another company's CIK, often a false delisting
row (Dillard's as Vaxart's 2025 Nasdaq move, CoreCivic as Cornell's 2010 merger,
Qwest as Lazare Kaplan's revocation). They were found by comparing each security's
observed names with its CIK's EDGAR names (`member_name_mismatch` rows and a
table-wide check), and each correct CIK was verified in its EDGAR submissions JSON
(name, former names, filing span). The pins are written on the affected observation
rows. Where a ticker-level `MANUAL_OVERRIDES` entry named a later holder of a recycled
ticker (IMCL, AH) or was simply wrong (CBH → 1018272 is Arrowhead Financial), the pin
overrides it for those rows.

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

## Residual issues

- **Identity errors not caught by name checks.** A CIK whose name shares a single
  word with the observed name passes both the resolver and the verifier (JNPR →
  "Juniper II Corp" was caught only by a table-wide review), and the verifier calls a
  wrong CIK with a Form 25 near the date a recycled ticker (Oasis Petroleum resolved
  to Javelin Mortgage). Both are pinned now. The table-wide check (observed names
  against each CIK's EDGAR names, token overlap < 0.5) listed 95 securities before the
  pins and 36 after; the 36 are abbreviations, share-class wording or renames with
  the right CIK. Securities whose CIK shares one word with the observed name were not
  all reviewed by hand.
- **Possessive apostrophes.** `names.name_tokens` reads "Macy's" as MACY and
  "DILLARD'S" as DILLARD, so they never agree with the snapshots' MACYS / DILLARDS.
  Normalizing apostrophes would fix the ticker-map tier for them, but would also let
  Triarc (renamed Wendy's/Arby's on 2008-09-29) take Wendy's International's last
  2008 era; not changed. cb77e4b covers the listed cases.
- **304 rows from the no-Form-25 fallback (86).** Renames, holdco reorganizations and
  LBOs of issuers with public debt get an `exchange_transfer` delisting at the
  security's last sighting because the classifier's continued-filings rule fires
  (Alltel, TXU, Ceridian, Nuveen). Spec §8.7 says a rename never yields 304 by itself;
  here the fallback yields it when the security's later life is not observed. The
  classifier rules are frozen (constraints), so this stays; all carry `no_form25`,
  `delist_date_approx` and `successor_unknown`.
- **Holding-company reorganizations** are split across two CIKs. With per-era pins
  the old line's Form 25 is found, and the classifier reads the reorganization 8-K
  (items 2.01/3.01/5.01) as a merger: BlackRock 2024 and DraftKings 2022 are code 231,
  nCino 2022 code 200, with DLRET ≈ 0 (at par, or stock ratio 1.0 into the new line),
  which is right for the holder; the bucket is `merger` rather than a transfer to the
  new FIGI. Without a Form 25 the fallback gives 304 with `successor_unknown` (135);
  the 8-K12B successor search finds some successors (Alphabet, APA), not all.
- **Mergers without a close (52 of 604).** 35 have no last trade date at all: most
  are Nasdaq deals whose Form 25-NSE carries an empty EX-99.25 ("myl-form25") before
  MIDAS (2012) or with no MIDAS row, and no 3.01 8-K with a date. The rest have no
  priced FTD row within ten trading days before the last trade (Cerner, Forest Labs,
  Scripps Networks, Santander Consumer, Paramount A, …).
- **`form25_unclassified` (118)** are mostly structured notes, ETNs and "See
  Attached" Form 25s of issuers with many debt lines (BAC, JPM, GS, AIG); none is a
  common-stock delisting. **`form25_unmatched` (101)** are ambiguous-class Form 25s
  where one issuer has two observed securities of one kind — often a placeholder and
  a FIGI security for the same stock (an era that failed FIGI resolution).
- **Stale-era merges.** FDC's stale 2008-09 era (First Data, LBO 2007) resolved to
  the 2015 First Data Class A FIGI, and LAUR's to today's Laureate Education, so the
  2007 delistings of the old securities are missing.
- **Resolver speed.** EFTS searches and empty company-search answers are never
  cached, and eras that resolve to no CIK are never persisted, so every run repeats
  their searches (about 30-60 minutes per rerun on this universe).
- **CLAUDE.md** still says "the resolver cache carries version 2" and "705 tests"
  (now version 3 and 735); not edited here.

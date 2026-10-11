# 5d design note: the last trade date

Date 2026-10-04, at base 0de5d8f (5c accepted, D.mismatches 478). Research, design and implementation by one agent
(the decisions log's 2026-10-04 flow). Cached data only, no network. Probes and the offline replay are in
`/tmp/claude/delist_detection/5d/` (`replay_5d.py`: 5c's replay, plus an uncached Nasdaq halt day read as "no
halts" instead of a failed read; `r5d_*.py` probes; `ruling_5d.py` applies the rulings below).

The target: the 33 case-map rows of 5d plus the truth rows with `fixed_by` 5d, 39 cases, 90 mismatches, of which 55
are last-trade fields (`last_trade_date`, `internal_last_trade_date`, `price_date`). The rest are `cash_currency`
(5f), `price_sec_id`/`price_ticker` (5e; the OTC symbols are 5g) and LTRPA's `drop_reason` (5g).

## 1. Mechanisms (what the run did, replayed through the code)

| Mechanism | Cases | Why the run differs |
| --- | --- | --- |
| M1. The 8-K reader missed the wording | GLBL, NOVL, SEPR, PPDI, CTRX, KG, BMET, DSEY, TMHC (8-K), LLYVA, LLYVK | `_CLOSE` needed "at/after/following the close" right before " on D": it missed "the closing of trading", "as of the close", "on NASDAQ on D", "listed through D", "following the Effective Time"; `item_text` cut NOVL's and WM's 3.01 at a cross-reference ("described in Item 1.01 above") |
| M2. Source order and R8 | TMHC, MNK, WM, PMI | The notice's bare "suspended from trading on D" (the 23rd) beat the 8-K's "following the closing of trading on D" (TMHC); a bare "suspended on D" read as D, unconfirmed, so the involuntary notice's decision day won (MNK); a halt at 09:30:06 counted as after the open, and the halt feed was asked around the wrong day (WM); "halted on D, which was the last day" was not read (PMI) |
| M3. A read by ticker after another security took it | CCE, JCI, GRUB (MIDAS); WEN (the fails close) | MIDAS's latest day under the ticker was the successor's first (CCEP, Johnson Controls plc, JET's ADS); the close by symbol took Wendy's/Arby's new CUSIP's $5.26 |
| M4. Nothing states the day | ADCT, CDWC, DADE, IFIN, GENZ, PHLY, MYL, HLTH, CHAP, SUNW, IMCL, CKFR, ODP, APA, MLNM, SPWRA; FCL, SGP, UNIT (no Form 25) | The row kept no day (`no_last_trade_date`), or the fallback's last sighting |
| M5. A rights class | TMUSR | The notice is empty; the class text says "Subscription Rights Expiring 7/27/2020" |

## 2. Rules

1. **Rule 1, the 3.01 reader** (`last_trade.eightk_last_trade`): every 3.01 section (`sections_3_01`, ending at the
   next item heading, not a cross-reference), sentence by sentence, a stop word (suspend, cease, halt, delist,
   withdraw, trading, listed) in the sentence, never a record date. Before the open (incl. a halt "at the NYSE
   market open") gives D−1; the close or closing of trading/business/market (on a venue) gives D; the Closing
   Date and an "after the Effective Time" at 4 p.m. or later resolve from the filing; "the last day ... traded",
   "which was the last day", "continue to be listed through D" give D. A stated timing ranks first, and
   `_eightk_window` keeps the best reading of the window. A rights or warrant class "Expiring M/D/YYYY" dates its
   last trade (`form25._class_expiry`, kind `notice_expiry`, source `ex99_notice`).
2. **Rule 2, source order** (`decide_last_trade`): R8, a bare "suspended (trading ...) on D" is D−1, confirmed
   (`8k_suspended`); "suspended immediately on D" stays D, unconfirmed (not scored). MIDAS, then a halt, except
   that an 8-K which puts the halt at the open of the halt day gives the day before (`OPEN_KINDS`: WM's feed stamp
   is 09:30:06; HET 2008's 09:30:05 halt on a day its 8-K says it traded to the close shows a feed stamp alone
   proves nothing, so the threshold stays 09:30:00). Then the notice's own timing; then an 8-K timing that
   disagrees with the notice's bare date (`BARE_NOTICE_KINDS`, TMHC); then the notice; then the 8-K. With no text
   day the halt feed is asked around the Form 25 day too (PHLY). Calibrated on the 572 MIDAS-dated rows: 8-K open
   readings agree with MIDAS 202 of 209, close readings 51 of 61, notice_a 252 of 259; where notice_a and an
   explicit 8-K reading disagree, MIDAS sides with the 8-K 4 times and the notice 3 times. The spec's "check a
   MIDAS/text conflict against the own CUSIP's fails rows" is not built: rule 3 settles the conflict cases, and
   DBD's check confirms MIDAS.
3. **Rule 3, the ticker's tenure** (`pipeline._ticker_taken`, `SecurityContext.ticker_taken`,
   `DelistingFinder._confirmations`): a MIDAS or halt day after a text day, under a ticker another CUSIP began
   trading under by then (the trading day before its first priced fails row there, on or after the own CUSIPs' last
   row under the ticker; a $0.01 placeholder is no trade; no own row in the window, no bound), is the other
   security's: MIDAS is read up to the day before, the halt dropped. Only on such a conflict: bounding every read
   gave wrong days where the successor's first fails rows lag its first day (Sinclair Inc 2023, the new TCF 2019,
   APA Corp's placeholder row), and a continuation's MIDAS stays unread as before. The fails close by symbol skips
   a CUSIP another security of the run holds (`FtdIndex.close_of(..., skip=)`, WEN).
4. **Rule 4, the closing day** (`last_trade.closing_day`, `DelistingFinder._closing_day`): a row still undated,
   not continued, under an exchange's Form 25 (25-NSE, not the issuer's 25), takes the latest completion its 8-Ks
   filed in [F − 10, F + 10] state for [F − 10, F] (a defined Closing Date, "On D, ... completed its acquisition",
   "Merger Sub merged with and into", "the closing of the transactions on D", "the evening of D", an effective
   time with a clock time; the trading day before when every clock time that day is before 9:30 a.m.), else the
   Form 25 day. A no-Form-25 merger fallback takes the closing day its latest 2.01/5.01 8-K near the last
   sighting states, never after the last sighting. Source `closing_day`, flagged `last_trade_date_unconfirmed`:
   the ranges clip there, the contract publishes nothing, and the classification keeps its anchor (the filing
   day).
5. **Rule 5** (the clip uses the last trade day) needed no code: `_history_rows` already clips at the last trade day
   when one exists, and rule 4 gives one.

## 3. Guards (must not change), pinned by `tests/test_last_trade_cases.py`

DBD 2023 (MIDAS 05-26 stays: the same CUSIP went to DBDQQ, no other CUSIP), BTU 2016 and CHK 2020 (no own row under
the ticker in the window: no bound), LTRPA 2023 (MIDAS stays), TDW 2017 (a bankruptcy fallback keeps its last
sighting), XMSR 2008 (the halt's day), HET 2008 (the feed's 09:30:05 halt against the 8-K's close), SIRI 2024, SBGI
2023 and TCF 2019 (no disagreeing text day: no bound). Unit guards: a record date, MYL's undated suspension, SUNW's "has been
suspended", the reporting obligations "suspended on D", "following the closing of the Merger on D", a notice
that states the close (it keeps winning), HLTH's asset sale ("completed the sale of Porex"), FCL's subsidiary
merger after the closing, a tender offer's completion, a closing on a holiday (PNFP 2026: the trading day before), a
handoff's successor's first day (a closing day never reaches it). The 5a, 5b and 5c harnesses stay green; five 5b outcomes
gain a last trade day (KHC 2026 and MSG 2015 are continuing moves, BMET, SPWRA and APA are 5d cases), recorded in
`tests/test_form25_reach_cases.py`.

## 4. Blast radius (the offline replay of the whole run, base 0de5d8f against HEAD)

`replay_5d.py run` over both trees, then `diff` and `judge`. The HEAD run asked what the cache lacks: 9 full-text
searches and 1 OpenFIGI CUSIP job (stage 9 anchors moved with the last trade days), 26 8-K texts (the closing-day
and 3.01 reads) and 92 halt days. The network run fetches them; the replay reads them as nothing.

- **D.mismatches 478 → 425** on the committed truth (−53); **483 → 414** with the rulings below (−69). The
  last-trade fields: `last_trade_date` 41 → 20, `internal_last_trade_date` 55 → 22, `price_date` 28 → 21.
  `D.known_wrong_now_right` 12 (APA, FCL, MYL, HLTH, ODP, GRUB, TMUSR, LLYVA, LLYVK, DTV, plus 5c's SPWRA and 5f's
  SKYF).
- **106 securities change: 56 in the truth set, 50 outside.** Outside, 10 change the contract:
  - CB 2016 (01-15 → 01-14, the 8-K's close of business on January 14; MIDAS's 01-15 is Chubb Ltd's), WCN 2016
    (06-01 → 05-31, its 8-K's before the opening on June 1), FTI 2017 (01-17 → 01-13, TechnipFMC took FTI on the
    17th): `last_trade_date` and the history end, rule 3;
  - seven continuations, the security_history end only (their contract `last_trade_date` stays blank: the source
    is `closing_day`): CI 2018 (12-21 → 12-20), MRVL 2021 (04-21 → 04-20), PNFP 2026 (01-02 → 12-31), AZPN 2022
    (05-17 → 05-16), VNOM 2025 (08-19 → 08-18), AVGO 2018 (04-05 → 04-04), Z 2015 (02-18 → 02-17): the closing
    day the 8-Ks state, a day before the successor's first sighting.
  The other 40 change delistings.csv only: 38 continuing exchange transfers gain their last day on the old
  exchange from their 8-K ("cease trading on the NYSE at the close of trading on D"), and IPHI's 2020 issuer
  Form 25 (a move to Nasdaq read as a merger) now continues the security.
- **Other scorecard lines (replay):** `R2.1.missing_last_trade_date` 38 → 4, `R2.1.exchange_print_source` 789 →
  802, `L1.ended_incomplete` 51 → 27 (L1 coverage 0.952 → 0.963), `V.uncertain_endings` 252 → 238; the audit's
  errors fall in every group.
- **Floored lines the network run will drop** (the controller lowers or settles them at acceptance):
  - `G.pass` 42 → 41: the golden case JCI-2010 pins `last_trade_date` 2016-09-06, but the 8-K says the NYSE
    suspended JCI before the open on September 6 and MIDAS's 09-06 under JCI is Johnson Controls plc's; the truth
    row agrees (2016-09-02, verified, upheld). The golden row needs 2016-09-02; this sub-plan may not edit it.
  - `D.mismatches.cash_per_share` 14 → 15: JCI. With its own close (45.04), the gate passes the LLM's all-stock
    election instead of failing, so the default package's $5.7293 is no longer published (R4: 5e/5f).
  - `L2.high_share` 0.7355 → 0.7276, `L2.low` 187 → 192: 24 more chains are covered, at the grade of a worked-out
    or text date.
  - `R2.6.distress_flagged` 56 → 57: a new 8-K reading that disagrees with MIDAS adds `last_trade_date_conflict`.
- **Floors lowered by hand in this commit**, because the rulings move truth cells on rows the committed (pre-5d)
  output still holds: `D.mismatches` 478 → 483, `D.cases_matching` 103 → 101, `D.mismatches.last_trade_date`
  38 → 41, `.internal_last_trade_date` 54 → 55, `.price_date` 27 → 28. The replay of HEAD is at 414.

## 5. Truth rulings (`ruling_5d.py`, written with the change log by `diagnosis_loop.write_together`)

| Case | Ruled | Evidence |
| --- | --- | --- |
| DBD 2023 | `last_trade_date` 2023-05-26, `price_date` 05-30, internal 05-26 (was blank, blank, 06-01) | MIDAS volume ends 05-26 in a quarter covered to 06-30; Nasdaq's code-D halt at 07:16 on 05-30; the own CUSIP's fails rows repeat one $0.25 close from 05-30 |
| GRUB 2021 | 06-15 → 06-14 (`price_date` 06-15, internal 06-14); pass → known_wrong 5d until a 5d run | R8 (8-K: suspended on June 15), the NYSE notice (06-14); MIDAS's 06-15 under GRUB is JET's ADS (its first row under GRUB, 06-16, carries the 06-15 close) |
| HTS 2016 | 07-11 → 07-12 (`price_date` 07-13, internal 07-12) | 8-K 0001193125-16-646386: "will cease trading on the NYSE following the close of trading on July 12, 2016", which the report did not read; rule 2 as in TMHC |
| DTV 2009 | `last_trade_date` blank → 2009-11-19; pass → known_wrong 5d | 8-K 0001104659-09-066017 item 3.01: suspended as of the close of trading on November 19 (an 8-K print), the day the truth worked out |
| PHLY 2008 | `last_trade_date` blank → 2008-11-28 | Nasdaq's code-D halt at 08:50 on 2008-12-01, the Form 25 day (a halt is publishable) |
| DADE 2007, IFIN 2007 | `fixed_by` residual | Nothing states the last session; the closing-day rule gives the Form 25 day and the halt feed is not cached for those days (the network run may answer) |
| 26 rows | `fixed_by` 5d → 5e (4), 5f (18) or 5g (4) | Their last trade fields match the replay; what is left is `cash_currency` (5f), an acquirer `price_sec_id`/`price_ticker` or JCI's package (5e), an OTC symbol (5g: PMI, WM, MNK, DBD); MLNM's published day is in the 8-K's EX-99.1 press release (with its 5f currency) |

No status flips: the committed output predates 5d, so the 12 rows that match the replay stay known_wrong until the
loop's `flip_statuses` runs on the network run.

## 6. Left for later sub-plans

- `cash_currency` on 23 of the 5d rows (5f), the OTC symbols (5g), the acquirer lines (5e), LTRPA's `drop_reason`
  (5g), JCI's election package (5e/5f).
- MLNM 2008: the last day ("after the close of market today") is in the press release exhibit; reading 8-K
  exhibits is new traffic, left to 5f's exhibit reading.
- The 5a carry (a same-CUSIP rename's ticker boundary 1–3 days late, PRDO, PGEN, LC, DSW, RLGY) is **deferred**: the
  run has 638 ticker boundaries inside one security (223 outside the truth set), all built from fails rows; moving
  them would rewrite hundreds of unscored security_history ranges, and needs MIDAS's first day under the new
  ticker per boundary, measured on its own. The continuations' ends that rule 4 moves (section 4) are the part of
  it this sub-plan reaches.
- The spec's fails-row check of a MIDAS/text conflict (rule 2): not built (section 2).

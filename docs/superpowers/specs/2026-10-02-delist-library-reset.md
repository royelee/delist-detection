<!-- Copy of the claude.ai artifact https://claude.ai/artifact/Y9MT7c869AXSyT4gvYQ852 (version 1790960982-2e84),
     converted to Markdown on 2026-10-02 so the reset plans' executors can read it offline. The artifact is the
     source of truth; linked pages: Life of a Delisted Ticker https://claude.ai/artifact/7N5kEwJyxs9NaXGGCJQLk6,
     How to handle a ticker event https://claude.ai/artifact/76LqFYrd5D14NC53fKxC9x,
     Delist Library Cleanup https://claude.ai/artifact/VP1F4A16ZsXgMTcjrwnBkq. -->

Handover · delist_detection × qlib_practice

# Delist Library Reset

What qlib_practice requires from the delist_detection library, how far the library's current output is from it, and the contract the library moves to. Written for the next phase: the design document and the implementation plans.

as of 2026-10-02 library main `d1a367e` (PR #6) numbers from the library's committed `output/`, run on qlib_practice's index snapshots background: [Life of a Delisted Ticker](https://claude.ai/artifact/7N5kEwJyxs9NaXGGCJQLk6) · rules: [How to handle a ticker event](https://claude.ai/artifact/76LqFYrd5D14NC53fKxC9x)

Part 1 of 3

## The real requirement

qlib_practice's universe arrives as `(ticker, start, end, name)` from the iShares and Wikipedia Russell 1000 snapshots. A ticker today does not say which company used it when it entered the index: COHR was Coherent Inc until 2022 and is II-VI (renamed Coherent Corp) since. Training needs the company that actually traded under the ticker at the time, and a correct final return for every company that stopped trading. The delist_detection library exists for exactly two jobs.

### What the library replaces in the traced ticker pipeline

The background page, Life of a Delisted Ticker, follows a delisted ticker through ten steps of qlib_practice's ticker-keyed pipeline. Five are now the library's; five stay in qlib_practice.

| Old step | How it worked | Now |
| --- | --- | --- |
| 2 · Fetch and cap | Alpha Vantage's delisting date cut the series; a denylist, a 158-row rename map and identity guards patched reused tickers. 484 capped, 160 unresolved. | **R1 + R2.** Identity picks the series; the last trade date cuts it. |
| 4 · Delisted set | A ticker counted as delisted when its series ended early. 495 events. A ticker another company took over never ended (107 member eras). | **R2.** Endings come from filings: 883 real endings, 48 liquidations instead of 16. |
| 5 · Identity | A hand table mapped 2,293 ticker eras to a CIK (SEC registrant number), passed as `--cik-map`. About 26 named the wrong company; the confidence column read “high” on every row. | **R1.** `sec_id` and a dated ticker history from CUSIP, CIK and FIGI (Bloomberg's open security identifier) evidence. |
| 6 · Classify | Form 25, Form 15, 8-K items and merger filings → one of six buckets. 104 review rows. | **R2.** Same job, whole universe. |
| 7 · Terminal return | One number per event: deal value ÷ last close − 1, Shumway (1997) default haircuts for distressed delistings. 482 valued, 13 blank. | **R2.** Same job; qlib_practice's last close feeds the library's second pass. |
| 1, 3, 8, 9, 10 | Membership list, price store, panel labels, inject and sanitize, training. | **qlib_practice.** Keyed by `sec_id` after the switch to the library's output. |

R1 · Identity

### Every seed resolves to one security

Question: Which security traded under ticker *T* on date *D*, and under which tickers did security *S* trade, from its first day to its last?

Input: One seed row per introduction: the ticker, the date it entered the Russell 1000, the company name on that date. A new row when a ticker re-enters after an absence or its name changes materially. No later snapshots, no index exit dates. Plus qlib_practice's reviewed identity pins. (Part 2 measures the library as it runs today, on every snapshot row; this page calls such a row a sighting.)

Output: A stable `sec_id` per security; its dated ticker history to its real end or to today, not to its last sighting in the index; handoff links (continuation, takeover); one verdict per seed.

Target: ≥ 99% confirmed by evidence; ≤ 1% flagged uncertain for human keep-or-drop.

R2 · Delisting return

### Every ended security gets a DLRT (delisting return)

Question: When did the security stop trading, why, and what did holders receive?

Input: The R1 securities, plus the prices the library requests from qlib_practice's store in a second pass.

Output: The date of the last price on the exchange; the kind of exit and, for a drop, its reason; whether holders continued one for one; the measured DLRT with any fill in its own column; the successor; a verdict. The library classifies by CRSP's three fields (kind of exit, form of payment, research status) internally and publishes the outcome, by the rules in [How to handle a ticker event](https://claude.ai/artifact/76LqFYrd5D14NC53fKxC9x).

Target: ≥ 99% complete and confirmed; ≤ 1% uncertain. No blank inside the training window unless qlib_practice drops the row on purpose.

### Hard constraints from qlib_practice, the consumer

Each one is a failure the background page found in the ticker pipeline. They define “complete” and “correct” for the library.
1. **1 · No blank DLRT inside train+valid (2006-01-02 → 2024-12-29).**Training has no NaN-label drop; a guard test requires 0 NaN labels in 6.1M train+valid rows. A blank is a value, a fill, or a drop-list row, never silence. The inject stops and lists blanks; the library's job is to leave it almost nothing to list.
2. **2 · The last trade date is the real one.**“Series end = delisting” placed ICPT 961 sessions late, XTO 955, ANAT 798, because the vendor kept printing a flat price; AABA read $19.63 for weeks it did not trade and its labels read 0.0. The date decides where the series is cut and which H+1 rows carry the delisting label.
3. **3 · A distress bucket is evidence-backed.**Liquidation and compliance failure become −0.90 and −1.0 on the security's last rows, the strongest labels in the panel. AABA carried −0.90 for a solvent liquidation that paid about +14%; IMCL carried −1.0 on the last day of another company's series.
4. **4 · A security's series is its own.**A ticker taken over by another company ends with a merger row and never inherits the taker's prices (COHR, CZR, CB, JCI, PLD). A rename carries the history forward as one security (FB → META, YHOO → AABA).

### What stays in qlib_practice, not the library
- Finding each security's price series at Tiingo (the vendor map), and leaving out what Tiingo cannot serve cleanly.
- Answering the library's price requests from the store: last closes, the received security's close on the ex-date, the first OTC print.
- The marking policy: harsh −1.0 / −0.90 only where the value is a fill (spec decision S10), so a liquidation with a known recovery keeps that value. A distress ending whose verdict is *uncertain* never gets a harsh mark; it goes to the drop list or an override. The drop list, for rows qlib_practice chooses not to train on.
- Membership, built from the seed echo: join is the seed date, leave is the security's ending or open. Index exits are not used (decision 8); the trade-time gate excludes only names that had not yet joined.
- Writing the labels, backtest exits, and live-trading ticker translation.

**How 99% is measured: one lifecycle per seed.** From the seed date to today the library must tell the whole story as a chain: ticker intervals, then a terminal state. The terminals are *active* (an open interval today), *ended* (an ending with a dated last trade, an exit kind and a value or a fill), or *continued* into a successor whose own lifecycle is then followed. A lifecycle is **covered** when it reaches active or ended with nothing missing on the way. **Coverage** is the share of seeds (2,219 input tickers today, one security each after resolution) whose lifecycle is covered; the target is ≥ 99%, about 22 left for the operator to keep or drop by hand. **Quality** is the weakest grade along each covered chain. The library's own confidence is not the measure: the old identity table read “high” on every row, and APTV, ITT and J were confidently wrong until library PR #6. Accuracy is proven as decision 17 says.

Part 2 of 3

## Requirement vs. today

### What the library already delivers

Against qlib_practice's ticker pipeline, the library finds 883 endings from filings where series ends gave 495, three times the liquidations, and real last trade dates where stale vendor tails used to set the date. The background page's named cases, then and now:

| Case | Then (ticker pipeline, 2026-09-22) | Now (library `d1a367e`) | Verdict |
| --- | --- | --- | --- |
| IMCL | −1.0 on 2018-10-05, the last day of another company's series under the ticker. | ImClone as its own security, 2007 → 2008-12-04, merger. The value waits on a last close qlib_practice may not have; a security with no vendor series gets no label cells, which is honest. | identity fixed |
| ICPT · XTO · ANAT | Delisting placed 961, 955 and 798 sessions late by flat vendor tails. | Last trade 2023-11-07, 2010-06-25, 2020-06-30. ANAT is split into the 2020 holding-company continuation and the 2022 merger. | fixed |
| CLWR · CTCM · HMA · LEAP · MON · TIN | Blank DLRT: NaN cells, or fake −0.90 / −1.0 marks still in the production panel. | Valued mergers: +0.2%, +7.8%, +0.1%, −14.4%, +0.0%, +0.4%, each with a last trade date. | fixed |
| BK · CB · JCI · PLD | The wrong company for years (reverse mergers and takeovers). | One security each, or split at the takeover with a merger row for the target. JCI's value is “assumed par” after the library's payout gate failed. | fixed |
| AABA / Yahoo | −0.90 for a solvent liquidation that paid holders about +14%. | A placeholder ID (no FIGI). The ticker history stops at YHOO on 2017-06-16; the rename to AABA is read as an exchange transfer with no successor, because Altaba left the index the same month. The 2019 liquidation is absent. Unless qlib_practice's vendor map finds the AABA series, Yahoo's 2000–2017 history drops out of qlib_practice's panel. | still wrong |
| PDLI | −1.0. | Bucket `compliance_failure`, Shumway −0.55, so qlib_practice's inject writes −1.0. PDL BioPharma delisted voluntarily to wind down and paid distributions. | still wrong |

AABA is one instance of a pattern: 126 endings are exchange transfers with an unknown successor, 53 of them placeholder IDs. The registrant left qlib_practice's universe and the library did not follow it to its next ticker or its real end.

### The gaps

The two lifecycle lines are the metric. The R1 and R2 lines break the shortfall into the pieces the library builds, so the work can be ordered. 1% of 2,219 is about 22.

met at or near target close within reach gap clearly short not measured no evidence either way

| # | Requirement | Today | Gap | Status |
| --- | --- | --- | --- | --- |
| Lifecycle · the headline |  |  |  |  |
| L1 | **Coverage**: input tickers whose lifecycle reaches a terminal with nothing missing | **1,970 of 2,219 (88.8%)** | Per security: 1,962 of 2,210 (88.8%). The 248 uncovered securities break in four ways: **119** left qlib_practice's view (the last event is an exchange transfer with no successor, the AABA pattern); **51** ended but incomplete (no last trade date, no DLRT, or reason unknown); **46** close with no event at all; **32** have no ticker interval. Two of the four, 165 securities, are one defect: the library stops at the last sighting instead of following the security to today. The 32 with no interval are a different defect: every sighting of each one falls after the library's delisting date for the security, so the library either placed the ending before qlib_practice first saw the ticker or attached the sightings to the wrong company. | gap |
| L2 | **Quality**: weakest confidence along each covered chain | high 1,547 (79%) · medium 296 · low 127 | Low means a Shumway or assumed-par value, a conflicting last trade date, or an identity through today's ticker map somewhere in the chain. Medium means the library's own confidence on an ending or on its value is medium, or the security's FIGI came from a ticker-only lookup. The 127 low chains are the first review queue after coverage. | close |
| R1 · Identity |  |  |  |  |
| R1.1 | Every sighting maps to a security | 35,419 of 35,955 mapped (98.5%) | 536 others: 267 seen after their delisting, 149 backfilled ticker (the retroactively renamed iShares rows, AABA 2012–2014 among them), 104 after an unconfirmed delisting, 12 conflicts, 4 unresolved. Each kind needs a confirmed-or-uncertain rule. | close |
| R1.2 | Identity backed by evidence | FIGI via CUSIP: 2,060 (93.2%) | 50 resolved by ticker only (2.3%), the tier that produced APTV and ITT. 100 placeholder IDs (4.5%) with no FIGI, every one with a CIK. 14 FIGI rows have no CIK (Applied Materials, DuPont, Fannie Mae, US Airways among them), so their statements and sector cannot be joined. | gap |
| R1.3 | Ticker history runs to the security's real end | Stops at the last index sighting | 126 endings are exchange transfers with an unknown successor (53 placeholders). Where the ticker changed at the same time (AABA), the vendor's series under the new ticker cannot be matched and the whole history is lost. A hand-checked sample of 20 ([below](#sample)) found no real transfer among them: 10 kept trading, 8 were acquired. To size the loss on the qlib_practice side: how many of the first vendor-map store build's 402 `no_vendor_data` are this pattern. | gap |
| R1.4 | One verdict per security | None | 728 review rows (628 “check”, 100 “fix”) spread over 508 securities (23%). Nothing says which of them are actually uncertain. | gap |
| R1.5 | Ticker handoffs (rename, reorganization, takeover) | Library PR #6 + qlib_practice fix `7fd5fe7` | Done in code; CB, JCI, PLD and ANAT come out right. Not yet confirmed on a rebuild. | met |
| R1.6 | Accuracy verified | 31 golden events | No random-sample audit. The 99% cannot be claimed without one. | not measured |
| R1.7 | Right Tiingo series (qlib_practice's side) | 91 issues, 402 no vendor data at library `c43bdd0` | 51 issues traced to the library; library PR #6 targeted 31. Not re-measured since. | not measured |
| R2 · Delisting return |  |  |  |  |
| R2.1 | Last trade date on every real ending | 841 of 883 (95.2%) | 42 real endings lack one, 41 inside train+valid: 34 mergers, 5 transfers, 1 liquidation, 1 unknown, 1 expiration. Without a last trade date the cut and the label window fall back to the series end, the failure in constraint 2. The 82 continuing exchange moves need none. | gap |
| R2.2 | Reason | 9 unknown (1%) | Complete. Correctness is open: 123 review rows say “continued 10-K/Q filings after delisting”, the pattern behind the false delisting calls, and voluntary wind-downs such as PDLI land in `compliance_failure`. | close |
| R2.3 | DLRT present (constraint 1) | 54 blank inside train+valid | 50 mergers, 2 unknown, 1 liquidation, 1 expiration. 32 fill on the library's second pass from qlib_practice's last close; 22 have no usable deal value (18 abstained, 3 unknown method, 1 expiration). Each of the 22 is NaN cells in training or a drop-list row. | gap |
| R2.4 | DLRT from evidence, not assumption | 60 “assumed par” | 60 merger returns assume the deal paid the last price, 52 inside train+valid; JCI 2016 is one, after the library's payout gate failed at $34.88. | gap |
| R2.5 | Distress endings complete | 54 (48 liquidation, 6 compliance) | 53 inside train+valid. 1 blank DLRT, 1 missing last trade date. This is the set the harsh marks apply to. | met |
| R2.6 | Distress endings certain (constraint 3) | 39 of 54 carry a flag | 29 flags are on the last trade date (conflict or unconfirmed), which is where the −0.90 / −1.0 rows land. 6 were identified through today's ticker map, the IMCL failure mode. 1 is “distress at a normal price”. PDLI is bucketed wrong with no flag at all. | gap |
| Measurement |  |  |  |  |
| M1 | A scorecard run on every rebuild | None | This table was assembled by hand for this review. | gap |

L1 and L2 were computed on 2026-09-30 by walking the library's tables: start at each input ticker's first mapped sighting; follow a delisting row that names a successor; an exchange move whose successor is the security itself is not an event; an open interval is active; an exchange transfer with no successor is “left view”; an ending is complete when its reason is known and both the last trade date and the DLRT are present; quality is the weakest grade along the chain. Script: `lifecycle.py`, to become the library's scorecard.

### Evidence for R1.3: 20 of the “left view” lifecycles, checked by hand

117 securities end in an exchange transfer with no successor as their own last event. 20 drawn at random (seed 7) and looked up at the library's end date: **none is an exchange transfer.** 10 kept trading, 8 were acquired at a known price, 2 are input or identity errors. One rule produces all 20: the library's `classifier._detect_continued_filings` reads “the registrant filed a 10-K or 10-Q more than 180 days after the last sighting” as “the stock moved to OTC”. A renamed company keeps filing because nothing ended; an acquired company often keeps filing because it still has public debt. Continued filings show the registrant exists, not that the security trades. The ten continuations are the expensive ones: each series is cut at a false end date or not matched at all, and DF and MNI lose a bankruptcy ending that should carry a distress mark. All 20 rows go into the golden set.

| Ticker | Library's end | What happened | What qlib_practice's panel loses |
| --- | --- | --- | --- |
| The same security kept trading: 10 of 20 |  |  |  |
| EXBD | 2012-08 | Ticker changed to CEB on 2012-08-13. Same company, same NYSE listing. | CEB's later years, to its acquisition by Gartner. |
| XON | 2020-01 | Renamed Precigen, ticker PGEN, on 2020-02-01. | Everything since; PGEN trades today. |
| YHOO | 2017-06 | Renamed Altaba, ticker AABA, on 2017-06-16. Dissolved 2019-10-04 after a stockholder-approved liquidation. | 2017–2019 and the real ending. |
| WTW | 2013-12 | Nothing: it left the index and kept trading as WTW on NYSE. It later moved to Nasdaq as WW. | Everything since. |
| LIZ | 2012-05 | Renamed Fifth & Pacific, ticker FNP, on 2012-05-15. | The FNP and Kate Spade years, to its acquisition. |
| ACXM | 2018-10 | Holding-company reorganization (8-K12B), renamed LiveRamp, ticker RAMP on NYSE from 2018-10-02. | Everything since; RAMP trades today. |
| DF | 2013-08 | 1-for-2 reverse split on 2013-08-26: same ticker, new CUSIP. | Six more years and the bankruptcy ending. |
| MNI | 2016-05 | 1-for-10 reverse split on 2016-06-07: same ticker, new CUSIP. | Four more years and the bankruptcy ending. |
| ESV | 2009-12 | Redomiciled to the UK on 2009-12-23 (8-K12B): each share became one ADS, same ticker ESV. | Ensco plc's whole later life. |
| DRQ | 2024-09 | Merged with Innovex on 2024-09-06. Dril-Quip is the surviving registrant, renamed, ticker INVX. | Everything since; INVX trades today. |
| Acquired, with a known price: 8 of 20 (the library writes a transfer with DLRT 0) |  |  |  |
| MDC | 2024-04 | Acquired by Sekisui House on 2024-04-19. | $63.00 cash |
| SGP | 2009-11 | Merged with Merck on 2009-11-03. The Schering-Plough entity survives as the new Merck (ticker MRK). | 0.5767 MRK + $10.50 |
| ACF | 2010-09 | Acquired by General Motors on 2010-10-01; renamed GM Financial, which still files. | cash |
| BNI | 2010-02 | Acquired by Berkshire Hathaway on 2010-02-12; BNSF still files. | about $100 in cash and stock |
| UFS | 2021-11 | Acquired by Paper Excellence on 2021-11-30. | $55.50 cash |
| CPN | 2018-03 | Taken private by Energy Capital Partners on 2018-03-08; Calpine still files. | $15.25 cash |
| CPGX | 2016-06 | Acquired by TransCanada on 2016-07-01. | $25.50 cash |
| STN | 2009-06 | Bought out on 2007-11-07, before qlib_practice's first snapshot. The 2008 sighting is a stale Wikipedia constituent. | cash; should not be in the universe |
| Other: 2 of 20 |  |  |  |
| LVNTA | 2018-03 | Split-off: each share redeemed 1:1 for GCI Liberty (GLIBA) on 2018-03-09. | A continuation with a known successor. |
| ERA | 2013-06 | One sighting of Era Group (CIK 1525221), attached to the old Bristow Group (CIK 73887). The two only merged in 2020. | Wrong company; an identity error, not an ending. |

The event at each end date was checked by web search on 2026-10-01: [EXBD](https://www.sec.gov/Archives/edgar/data/1066104/000119312512322777/d387593dex991.htm), [XON](https://www.sec.gov/Archives/edgar/data/1356090/000119312520023400/d876809dex991.htm), [YHOO](https://www.sec.gov/Archives/edgar/data/1011006/000119312519262790/d794671dex991.htm), [WTW](https://www.streetinsider.com/Corporate+News/Weight+Watchers+(WTW)+Announces+NASDAQ+Stock+Ticker+Symbol+Change+to+WW/15377344.html), [LIZ](https://streetinsider.com/Corporate+News/Liz+Claiborne+(LIZ)+Completes+Name+and+Ticker+Change;+Is+Now+Fifth+&+Pacific+Companies+(FNP)/7439631.html), [ACXM](https://www.sec.gov/Archives/edgar/data/0000733269/000119312518289748/d612393d8k12b.htm), [DF](https://www.sec.gov/Archives/edgar/data/0000931336/000119312513335750/d583800dex991.htm), [MNI](https://www.prnewswire.com/news-releases/mcclatchy-announces-completion-of-reverse-stock-split-300280463.html), [ESV](https://www.sec.gov/Archives/edgar/data/0000314808/000095012309072898/d70526e8vk12b.htm), [DRQ](https://www.nasdaq.com/press-release/innovex-and-dril-quip-complete-merger-creating-unique-energy-industrial-platform-0), [MDC](https://www.sekisuihouse.co.jp/english/company/release/library/2024/20240419/20240419e.pdf), [SGP](https://www.sec.gov/Archives/edgar/data/0000310158/000119312509223917/dex991.htm), [ACF](https://www.sec.gov/Archives/edgar/data/0001467858/000119312510263635/d424b1.htm), [BNI](https://www.sec.gov/Archives/edgar/data/0000934612/000093461211000005/d10k.htm), [UFS](https://www.pulpandpapercanada.com/paper-excellence-completes-acquisition-of-domtar/), [CPN](https://www.sec.gov/Archives/edgar/data/0000916457/000091645718000100/exhibit991-02212018.htm), [CPGX](https://www.worldpipelines.com/equipment-and-safety/04072016/transcanada-completes-columbia-pipeline-group-acquisition-276/), [STN](https://lasvegassun.com/news/2009/jul/28/station-casinos/), [LVNTA](https://investors.qvcgrp.com/news-media/press-releases/detail/14/liberty-interactive-and-gci-liberty-announce-completion-of), [ERA](https://www.bristowgroup.com/news-media/press-releases/detail/324/era-group-inc-begins-trading-on-nyse-as-an-independent). The later history in the last column (acquisitions, bankruptcies, today's tickers) is from general knowledge and was not checked.

Part 3 of 3

## The contract

The library publishes two tables in the shape of CRSP's `stksecurityinfohist` and `stkdelists`, a seed echo, `uncertain.csv`, and a price-request file. A column is published only if code in qlib_practice reads it or this page names the new reader; evidence the library uses to reach an outcome stays inside the library. The ending record follows the CRSP event tree in [How to handle a ticker event](https://claude.ai/artifact/76LqFYrd5D14NC53fKxC9x): classify (kind of exit, form of payment, research status), value, name the successor. Cleaning out library code that serves neither job is a separate page: [Delist Library Cleanup](https://claude.ai/artifact/VP1F4A16ZsXgMTcjrwnBkq).

### Three stages

### A · Identity (R1)

Seeds → `sec_id` as of the seed date by CUSIP/CIK/FIGI evidence → the security's history traced back to its first listing and forward to its real end or today → handoff links → verdict.

security_history · seed echo

### B · Ending (R2)

For each security that stopped trading on a covered exchange: the date of the last exchange price (MIDAS, fails-to-deliver, halts), then CRSP's three classifications from the filings.

delistings: last_trade_date, exit_kind, drop_reason, continuation, successor

### C · Value (R2)

What one share was worth at the first opportunity after the last exchange price: cash, ratio × the received security's close on the ex-date, the first off-exchange print within 10 trading days, or the sum of later payments, summed inside the library. Prices it lacks it requests from qlib_practice's store. Measured DLRT; any fill in its own column.

delistings: dlret, dlret_fill, verdict · price_requests.csv · uncertain.csv

### What crosses the boundary

| Direction | File | Contents and reader |
| --- | --- | --- |
| In | seeds.csv | One row per introduction to the Russell 1000: ticker, entry date, company name on that date. qlib_practice derives it from the snapshots, with a new row on re-entry or a material name change. Over-seeding is harmless (seeds that resolve to one security merge); under-seeding is the risk (a takeover inside a ticker that never left the index, by a company that was never a member, is found only if the name change produced a seed). |
| In | pins · deal terms | qlib_practice's reviewed identity pins; any merger-terms or recovery overrides. |
| Out | security_history · delistings | The two tables below. |
| Out | seeds.csv, echoed | The seed file with `sec_id` (blank when unplaced) and `verdict` appended. Readers: `membership.build_membership` (join = seed date, uncertain seeds left out) and `SecurityMaster.observed_sec_ids`, which feeds the vendor map, fundamentals, the store build, the app and the comparison gate. |
| Out, then In | price_requests.csv | Written after the library's first pass: one row per price it needs (`sec_id`, `last_trade_date`, kind = last_close \| received_close \| otc_print, the security or ticker to look up, the date). qlib_practice answers with the same file plus a price column (`last_trade_closes.py`); the second pass values the rows and may change value columns only. Rules: raw as-traded closes, never adjusted; OTC prints from the raw vendor files, volume above zero, within 10 sessions, stopping before any emergence or new-CUSIP date; an acquirer with no store series gets a fill of 0.0. |
| Out | uncertain.csv | Columns `kind` (seed \| security \| ending), `ticker`, `sec_id`, `date`, `reason`, `candidates`. A person writes a pin, an override or a drop-list row from it. Code reads rows of kind ending: the inject and the vendor-map build stop on a listed security that has store rows. Holds every seed the library could not place, every uncertain security and ending, and the earlier ending of a security that ended more than once. |
| Out | exit code · run_manifest.json | The gate is the exit code: qlib_practice stops on 2 (refused by SEC or OpenFIGI, or bad input) and 3 (degraded answers). The manifest carries one contract field, `schema_version`, asserted by the consumer's reader so a column change fails closed. qlib_practice records the library commit from git and hashes the tables itself. |
| Not published | observation_map · observed · last_trade_close · payouts · review · cusip_history · evidence columns | The seed echo replaces the observation map and the observed flag. The last close is qlib_practice's own number. Payments fold into `dlret` inside the library. CUSIPs, venues, filing ids, payment forms, research status, intermediate prices and run history stay inside; qlib_practice sees their outcome as `exit_kind`, `continuation`, a value or a fill, and a verdict. |

### security_history · one row per `sec_id` per interval in which every attribute holds

| Column | CRSP analog | Who reads it |
| --- | --- | --- |
| sec_id | PERMNO | Everything. The stable security-level ID (FIGI, or `CIK-` placeholder). |
| issuer_id | none (the SEC CIK, not a PERMCO) | Fundamentals per registrant, sector map, the comparison gate. The CIK in force on the interval; a holding-company reorganization changes it while the security continues. Fundamentals and the sector map take the latest interval's CIK. |
| start_date, end_date | secinfostartdt, secinfoenddt | Every lookup is as-of: vendor map, FINRA short flow, live orders, app labels. The last interval ends at the last trade date or stays open, never at the seed date or the last snapshot. |
| ticker | ticker | The same lookups; the only identifier Tiingo and Webull understand. |
| security_name | securitynm | The vendor-map name check (Tiingo names the security, e.g. “Alphabet Inc Class A”) and the app's name lookup. |
| share_class | shareclass | The comparison gate matches a placeholder that became a FIGI on issuer and class. |

Not published: `verdict` (on the seed echo), `cusip` (the library's Step 1 continuation test), `exchange` (how the library tells a covered exchange from OTC), `issuer_name`, `security_type`, and CRSP's remaining columns. Sector comes through the CIK; the universe is already equity-only Russell members plus SPY.

### delistings · one row per ended security

A move between covered exchanges is not a row. A move to OTC is a row (CRSP 520, a drop). In this version a security has at most one ending, its last; a security that ended, returned and ended again (5 today) keeps its last ending here and its earlier one in `uncertain.csv`. An ending whose last trade date cannot be established is still a row, with the date blank and the verdict uncertain.

| Column | CRSP analog | Who reads it |
| --- | --- | --- |
| sec_id | PERMNO | The key: one ending per security. Overrides and the drop list are keyed on it. |
| last_trade_date | DLSTDT, the date of the last price on the exchange | The series cut (`cuts.py`), the H+1 label window (`labels.py`), the exit date and the store close the exit is priced at, the vendor map's end check, membership leave. Only from an exchange-print source (MIDAS, an exchange notice, 8-K item 3.01, a Nasdaq halt), never a snapshot date, never after the Form 25 effective date; otherwise blank with the verdict uncertain, and the inject and vendor-map build stop when the security has store rows. |
| exit_kind | DelActionType | merger, exchange, liquidation, dropped, lost_source, expiration. `labels.HARSH_MARKS`, the comparison gate, the override file. Expiration keeps today's 0.0 (2 trust rows). |
| drop_reason | DelReasonType, dropped rows only | moved_otc, price, capital, went_private, bankruptcy, filings_fees, guidelines, sec_order. `labels.label_plan`: −1.0 for price, capital, filings_fees, guidelines or sec_order; −0.90 for bankruptcy and for liquidation; only when `dlret_fill` is set. |
| continuation | none; CRSP's PERMNO does not change | True when the same holders kept the same claim one for one, no cash, no bankruptcy; decided inside the library from the payment form, the ratio and the CUSIP. qlib_practice stitches the series under the successor, carries membership over, writes no label and no exit. |
| successor_sec_id | DelPERMNO | Set only when `continuation` is true: the security the same holders now own. Feeds the vendor map's inheritance and membership's carry-over. Merger acquirers are not published; nothing reads them. |
| ticker_successor_sec_id | none | Takeover: the vendor map refuses the taker's Tiingo series for the target (`vendor_map.py`, library ≥ `d1a367e`). Published even when the ending is uncertain. |
| dlret | DelRet | The label value and the exit return, measured only: terminal value over the last exchange close, minus one. Blank when not established; never a fill. |
| dlret_fill | none; CRSP leaves the fill to the researcher | The Shumway or other fill, apart from the measured value. Harsh marks only when it is set; labels and exits fall back to it when `dlret` is blank. Assumed par is published here as 0.0, never as `dlret`. A pending liquidation keeps its fill and its mark until payments arrive. |
| terminal_value | DelDivAmt + DelNextPrc | Reader today: `apply_delist_exits.py`. Leaves the contract if decision 15 books exits as position value × `dlret`. |
| verdict | none | confirmed / uncertain over identity, exit kind and the last trade date only, never over the value, or every pending liquidation would lose its mark. `labels.label_plan`: an uncertain distress ending never gets a harsh mark; it is drop-listed or overridden, else the inject stops. |

Not published: the Form 25 effective date, `crsp_code`, last-trade-date source, payment form, research status, the first off-exchange price and its date, value dates, missing-value reasons, fill source, known-as-of, per-payment rows and every filing-accession column. Their outcome reaches qlib_practice as `exit_kind`, `continuation`, a value or a fill, and the verdict. Point-in-time rollback is the git history of the committed tables; once liquidation payments exist, one `value_date` column is added and the fill is used wherever it is after the training end.

### Invariants the library's build enforces
- For one ticker on one date, at most one `sec_id` per share class.
- Every seed resolves to one security whose `security_history` covers the seed date, or is listed in `uncertain.csv` with its reason. Seeds that resolve to the same security merge.
- One verdict per seed and one per ending. The ending's verdict covers identity, exit kind and the last trade date, never the value.
- At most one `delistings` row per `sec_id`. Its `last_trade_date`, when present, falls inside one of the security's intervals and no interval spans it.
- `last_trade_date` comes only from an exchange-print source and is never after the Form 25 effective date; otherwise blank and uncertain.
- `continuation` implies `successor_sec_id` set, ratio one, no cash, no bankruptcy filing between the two securities, `dlret` blank. `successor_sec_id` is set on no other row.
- `dlret` and `dlret_fill` are never both set. Every ending inside the training window has one of them or the verdict uncertain; the library checks this at its build and the inject again before writing.
- `confirmed` requires a FIGI or a unique CIK + class, dated intervals covering every seed that resolved to the security, and, for an ending, a filing-backed exit kind and a dated last exchange price.

Two tables: `security_history` 7 columns, `delistings` 11 (10 if decision 15 removes `terminal_value`), plus two appended to the seed echo, against 35 in `delistings.csv` alone today.

### The CRSP event tree, applied: rules and the data they need

The tree answers three questions for any event on a listed stock: does the security continue, what is one share worth at the end, which security does the holder own afterwards. The library implements the rules; the right column is what it does not have today.

| Step | Rule | Data the library needs, and the source |
| --- | --- | --- |
| 1 · Does the security continue? | Decided by the holder's claim, not the legal entity. An unchanged CUSIP always continues the security. Shares exchanged for new ones end it; new equity after a bankruptcy is a new security. In a merger one issue survives, usually the largest. A security that leaves the covered exchanges and returns with the same holders is the same security with a gap. Under a FIGI-keyed `sec_id` a 1:1 reorganization is a continuation row with a successor link; a timing-only link with no filing or CUSIP evidence is uncertain, never a continuation. | CUSIP history as the binding test (2,660 rows today, used as evidence only). A venue on every interval to tell a covered exchange from OTC (blank on 793 of 2,828 interval rows). |
| 2 · Classify the terminal event | Three separate things: kind of exit (merger, exchange, liquidation, dropped, lost source), what holders received (tracked stock, untracked stock, cash, a mix, other), research status (verified, closed, pending, worthless, failed). Published as `exit_kind`, `drop_reason` and `continuation`; the rest surfaces through the verdict. | Payment form per merger from the terms the library already extracts (today `crsp_code` reads 231 on 603 of 624 mergers while the methods say 316 cash, 120 stock, 84 mixed). Research status from the library's run history (all 48 liquidations read pending). |
| 3 · Value it | Base price is the last price on the exchange. A stock leg is the ratio times the received security's close on the ex-date, the trading day after the last price. A drop is valued at the first off-exchange price within 10 trading days plus payments up to that date. Liquidation payments are summed, no discounting, for up to 10 years. Any unvalued leg leaves `dlret` blank. −1 only when a source declares the stock worthless. Fills live in their own column. | The received security's close on the ex-date and the first OTC print, through `price_requests.csv` (`acquirer_price` carries no date on 209 rows; 328 transfers read 0.0). Worthless evidence: a plan of liquidation or a Form 15 with no trading after it. Per-payment rows with ex-dates from 8-K item 2.01, redemption notices, plans of liquidation (today 639 payout rows, one per ending, no ex-date; zero for liquidations). |
| Spin-offs | A distribution on the parent, not an ending; the parent keeps its identifier and the price factor carries the value. | Whether Tiingo's adjusted close already carries the spin-off value (decision 14). Nothing published unless it does not. |
| Where the return appears | A separate table, compounded after the last day's return: (1 + RET) × (1 + DLRET) − 1. qlib_practice's label enters at t+1, so a row at date t whose window crosses the last price L carries close(L) over close(t+1) × (1 + dlret) − 1, and the row at L is NaN in training (decision 13). | Nothing new: the store's closes. |

Feasibility, measured on the committed output and raw Tiingo files: 230 of 1,017 endings have no exchange-print source for the last trade date (pre-2012: 62 of 183). Of 175 drops and distress endings, 37 have a post-drop print with volume within 10 sessions, 20 only a zero-volume tail, 12 nothing, 69 no raw file, 36 a recycled ticker, and several prints are new equity (TDW) or a frozen quote (SIVB): expect fills, not OTC values, in the first release. Stock-paid mergers: 204, of which 143 acquirers are members and 61 need a valuation-only vendor tier. Liquidation payment schedules do not exist in the library yet.

### The end-of-era resolver (the R1.3 fix)

One function in the library, run once per security at the last date its history is known, answers “what happened next?” before anything is written. It replaces the continued-filings rule and the clip logic in `_history_rows` and `_ends_the_security`, and it is the one place the end-of-era decision is made (today it is made in three: the classifier on filings, the pipeline on FTD rows, listing status on today's FIGI). Branches are tried in order; each needs evidence about the security, never only about the registrant.

| Branch | Evidence | Result | In the sample |
| --- | --- | --- | --- |
| 1 · Still trading under the same ticker | The same CUSIP keeps appearing in fails-to-deliver data, or a later seed names the same security, or OpenFIGI lists the ticker as active. | An index exit or a data gap. Extend the interval. | WTW |
| 2 · Same security, new exchange | Form 25 from one exchange and a later 10-K cover or FIGI record naming another. | Same `sec_id`, the interval continues (exchange is not a contract column). No delisting row. | 0 |
| 3 · Same security, new ticker or CUSIP | OpenFIGI's later ticker for the FIGI; the issuer's CUSIP changing in fails-to-deliver data; an 8-K item 5.03 (name change) or 3.03 (reverse split); an 8-K12B successor filing. | New interval, same `sec_id`, or a continuation to the successor. Then keep following from there. | EXBD, XON, YHOO, LIZ, ACXM, DF, MNI, ESV, DRQ |
| 4 · Merger, buyout or split-off | 8-K item 2.01, a merger proxy, a redemption notice, or a Form 25 the exchange filed for a completed deal. | A `delistings` row: reason merger with the consideration, or a continuation with `successor_sec_id`. | MDC, SGP, ACF, BNI, UFS, CPN, CPGX, LVNTA |
| 5 · Liquidation, bankruptcy, expiration | 8-K item 1.03 or 3.01, a plan of dissolution, or a Form 15 with no trading after it. | A `delistings` row, no successor. | 0 (YHOO, DF and MNI reach it later) |
| 6 · None of the above | Nothing found. | `verdict = uncertain`, a row in `uncertain.csv` with what was searched. No bucket is asserted. | 0 |

STN and ERA are input and identity errors upstream of the resolver: a constituent that had already been bought out, and a ticker attached to the wrong registrant. The golden set pins all 20 sampled rows.

### Order of work
1. **Measure first.** Make the scorecard a library output: coverage and quality per lifecycle plus the R1/R2 lines, computed on every rebuild. Seed the golden set: AABA, PDLI, IMCL, ICPT, XTO, ANAT, CLWR, CTCM, HMA, LEAP, MON, TIN, BK, CB, JCI, PLD, MRK, FOX/FOXA, COHR, CZR, APTV, ITT, J, and the 20 sampled rows. Prove accuracy as decision 17 says. Nothing later may lower a scorecard number.
2. **One verdict per row.** Replace the review triage with *confirmed* / *uncertain* under the invariants and write `uncertain.csv`.
3. **Publish the contract.** The two tables, the seed echo, `uncertain.csv`, `price_requests.csv`, `schema_version`, side by side with the six tables for one release (decision 6). In one qlib_practice change: rename `issuer_cik`, `valid_from`/`valid_to`, `review_flags`; split `bucket` and `dlret_method` into `exit_kind`, `drop_reason`, `continuation`, `dlret_fill`; key overrides and the drop list on `sec_id`; build membership from the seed echo; answer `price_requests.csv` from the store; bump the minimum library commit.
4. **Close the gaps, biggest first.** The end-of-era resolver (165 of the 248 uncovered lifecycles); identity evidence (50 ticker-tier, 100 placeholders); the 22 blank mergers inside the window; the 29 contested distress dates; the 42 missing last trade dates. Stop when coverage reads 99%.

For the operator

## Decisions needed

Each item is a question and the proposed answer. “Reviewers agree” means the quant and engineering reviews reached the same answer.
1. **1 · Placeholder IDs count as confirmed.**All 100 have a confirmed issuer CIK and class; only the FIGI is missing. Proposed: confirmed, but 94 of 100 have an ending (AABA among them), so require a filing check that the ticker appears under that CIK.
2. **2 · The 22 mergers with no deal value inside train+valid.**Proposed: hand-value them through the library's deal-terms input, or publish assumed par as a fill of 0.0. Never the drop list.
3. **3 · Harsh marks vs. known recoveries.**53 of 54 distress rows are fills today. Proposed: the library values solvent liquidations (AABA, PDLI) from their payments; harsh marks stay for rows that still carry a fill. The +7.7 pp found for the marks was in sample; re-measure at top-30 resolution.
4. **4 · Assumed par.**Proposed: acceptable as `dlret_fill` = 0.0 when the payout gate passed; a failed gate (JCI 2016) is uncertain. Reviewers agree.
5. **5 · The unit of the metric.**Input tickers (2,219), ticker eras (2,360) or securities (2,210) agree within 0.3% today. Proposed: the seed, which is one security after resolution, for R1; the ending for R2.
6. **6 · How the contract lands.**Proposed: side by side with the six tables for one release under a schema version, then one qlib_practice PR switches every reader and the library drops the old tables. Reviewers agree.
7. **7 · `sec_id` format.**Proposed: keep FIGI with CIK-class placeholders; the library publishes an `id_changes` file for placeholder-to-FIGI renames and builds placeholders from a class code, not class text. Code in both repositories assumes the `BBG…` / `CIK…-CLASS` formats. Reviewers agree.
8. **8 · Index exits leave membership.**Join is the seed date, leave is the ending or open. Two qlib_practice builders mask to point-in-time membership, the risk-model snapshots and the equal-weight benchmark; a name demoted to the Russell 2000 and still trading stays in both. Proposed: accept, rename the benchmark, report the non-member share, keep the old benchmark one cycle. Reviewers agree.
9. **9 · The continuation rule.**Proposed: CRSP's rule. Same holders, same claim, one for one, no cash, no bankruptcy; an unchanged CUSIP always continues. A 1:1 holding-company reorganization (Alphabet 2015, ANAT 2020) is a continuation row with a successor link and qlib_practice stitches the series; post-bankruptcy equity is a new security; a timing-only link is uncertain. Reviewers agree, given the boolean is enforced by the invariant.
10. **10 · Evidence columns stay inside the library.**`exchange`, `cusip`, `issuer_name`, `security_type` have no reader in qlib_practice; the library publishes their outcome. Nothing to decide unless a new reader appears.
11. **11 · A move to OTC is an ending with a value.**CRSP 520: the first off-exchange print within 10 trading days. 328 transfers carry 0.0 today, and most are not real drops. Proposed: adopt, after the resolver has separated the real drops; expect fills where Tiingo has no print.
12. **12 · Key and dates.**Proposed: the key is `sec_id`, one ending per security in this version; `last_trade_date` is the date, blank only when uncertain; the Form 25 date leaves the contract; overrides and the drop list key on `sec_id`. Securities that ended more than once wait for a later version.
13. **13 · Label compounding.**Spec S9 writes `dlret` flat into every H+1 row. Proposed: the CRSP form, close(L) over close(t+1) × (1 + dlret) − 1, with the row at L NaN; a correctness fix, with the top-30 comparison run as a diagnostic.
14. **14 · Spin-offs.**Outside this library. Proposed: check ABT 2013-01-02, EBAY 2015-07-20 and HPQ 2015-11-02 in Tiingo's adjusted close as store QA; only if the value is missing does the library publish a small distributions file with a named reader.
15. **15 · Exits booked in the account series.**Today exits are a sidecar: `pred.py` defaults them off and never changes the book's return series, and `apply_delist_exits.py` subtracts a raw-dollar terminal value from an adjusted close. A held distress name books 0% while the live account books the loss. Proposed: book each held exit in the account return series on the bar containing `last_trade_date` as position value × `dlret` (or the fill), through one function the live path also calls; `terminal_value` then leaves the contract.
16. **16 · The drop list never removes a panel row.**Today `drop_label_windows` removes a listed security's trailing rows in every window, so in test and live the name leaves the scorable set during its last H+1 days: look-ahead. Proposed: a drop-list entry blanks label cells dated on or before 2024-12-29 and removes those rows from training only; test and live keep the name scorable and book its exit.
17. **17 · How accuracy is proven.**100 clean hand-checked rows bound the error rate near 3%, not 1%. Proposed: a census of every high-impact row (54 distress, 73 continuations, 117 left-view, 22 blank mergers, 60 assumed par, about 326), a random 100 of the rest with a Clopper-Pearson bound, and three hard gates: zero NaN labels in train+valid, no harsh mark on an uncertain identity or date, no uncertain ending with store rows.

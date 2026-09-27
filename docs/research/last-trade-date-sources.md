# Where to Get a Delisted Security's Last Trade Date and Last Close

*Research report · 2026-09-22 · for review*

> **Scope.** Every realistic source, other than Tiingo, for the two inputs a
> delisting return needs: the **last day a security traded on its exchange**
> and **the close on that day** (plus, for stock deals, the acquirer's close on
> a given date). Sources were checked against primary documents (the CFR, SEC
> forms and releases, exchange and vendor documentation) and, where a keyless
> request was possible, tested live on 2026-09-22. SEC requests used a
> descriptive User-Agent and stayed under 8 requests per second. No accounts
> were created and no paid keys were used. Scratch scripts and downloads stayed
> in the session scratchpad and are not part of the repo.

---

## 1. Question and answer

**Question.** Where can a US-equity library get the last trade date, and
ideally the last close, of a delisted US security, other than Tiingo?

**Answer.** No single free, keyless source gives both for every era, but SEC
and SRO data cover most of it from 2012 onward without a vendor. For the
**date**, the best EDGAR evidence is the exchange's own notice attached to Form
25-NSE as EX-99.25: NYSE, NYSE American, NYSE Arca and Cboe BZX stated a dated
suspension in 86 of 89 sampled filings, while Nasdaq's merger notices are empty.
The closing 8-K's Item 3.01 text is the other EDGAR source; it gives a date,
explicit or relative to "the Closing Date", in 256 of 363 cached closing 8-Ks.
Both need interpretation ("prior to the open on D" and "after the close on D"
mean different last days), and both can be off by one day. The SEC's MIDAS
per-security files (2012 onward, exchange trades only, no price) and Nasdaq's
keyless trade-halt feed (halt code D with a timestamp, tested back to 2008)
confirm which day last had exchange trades. For the **close**, the SEC's
fails-to-deliver files (2004 onward) carry the previous day's close keyed by
CUSIP whenever fails exist. 42 of 45 sampled delistings had such a row, and its
price equalled Tiingo's close in 40. The same files give acquirer closes and the
first OTC prices after an involuntary delisting. Among vendors, Sharadar's
TICKERS table (`lastpricedate`, free) matched MIDAS in 40 of 45 events. Massive
(formerly Polygon.io), EODHD, Norgate, FMP and CRSP sell delisted prices behind
a key or subscription. Yahoo, Stooq and Nasdaq.com return nothing for delisted
tickers. Alpha Vantage's `delistingDate` copies the date of Tiingo's last row.
One side finding matters for the redesign: Tiingo's last date is often not a
trading day. 274 of the 461 delisted series end in zero-volume rows, and
Tiingo's raw last date matched MIDAS's last exchange-trade day in only 14 of 45
checked events.

---

## 2. Summary table

"Date" means the last day on the listing exchange. "Close" means the close on
that day.

| Source | Last trade date? | Last close? | Coverage | Access | How obtained | Caveats |
|---|---|---|---|---|---|---|
| **EDGAR Form 25-NSE, EX-99.25 notice** | Yes for NYSE family and Cboe (86/89 sampled); Nasdaq merger notices no (0/21); Nasdaq involuntary sometimes (5/9) | No | Electronic Form 25 from 2006 (compliance date 2006-04-24) | Free | `www.sec.gov/Archives/...` or EFTS | "Suspended on D" means before the open on D for merger-type (a)(3) notices. For involuntary (b) notices it is the decision day, which may or may not have traded. |
| **EDGAR closing 8-K, Item 3.01** | Often: explicit date 215/363, relative to "Closing Date" 41/363 | Rarely (LEH's 8-K states the close) | Item 3.01 from 2004-08-23 | Free | submissions JSON + filing text; EFTS | Not required for (a)(3) delistings. Wording can be off by a day (ALTR). |
| **EDGAR Form 25 XML / Form 15** | No (Form 25 gives the filing/signature date and rule provision; Form 15 gives no trading date) | No | 2006 onward / all | Free | EDGAR | The rule provision tells merger (a)(3) from involuntary (b). |
| **SEC MIDAS, metrics by individual security** | Yes: the last date with nonzero exchange volume | No (only a `PriceRank` decile) | 2012-01 to 2026-06 | Free | Quarterly ZIPs | Exchange trades only; keyed by ticker only; zero-trade rows exist; not every security (HZNP absent). |
| **SEC fails-to-deliver (FTD)** | Indirectly (a row dated D carries the close of D−1) | Yes, when fails exist that day | 2004-02 to 2026-08 (all fails since 2008-09-16; ≥10,000 shares before) | Free | Half-month ZIPs | No row on days without fails; price goes stale after the last trade; 2 decimals; LEH 0.13 vs the 8-K's $0.14. |
| **Nasdaq trade-halt RSS** | Yes when a code-D ("security deletion") halt exists; gives the timestamp | No | Tested 2008–2025 | Free, keyless | `rss.aspx?feed=tradehalts&haltdate=MMDDYYYY` | Many delistings have no entry (AET, MER, RSH, CTCM). Includes some NYSE/CQS names (LEH, SAVE). |
| **Nasdaq Daily List** | Deletions (per product page) | Not stated | 1999 onward | Paid monthly subscription | Nasdaq Trader login | Not tested. |
| **NYSE delistings page / halts page** | Pending delistings only; halts kept 1 year | No | Current / 1 year | Free | nyse.com | Not historical. |
| **FINRA OTC Daily List** | Proxy: the time an ex-exchange security was added to OTC ("Market Center Change … Delisted from NYSE") | No | 2014-11-17 onward | Free, keyless API | `api.finra.org/data/group/otcMarket/name/otcDailyList` | OTC side only; exists only when the security moves to OTC. |
| **Sharadar TICKERS / SEP** | `lastpricedate` (matched MIDAS 40/45) | SEP `closeunadj` (paid) | Prices from 1997-12; TICKERS from 1990 | TICKERS free (documented test key; non-premium on Nasdaq Data Link); SEP paid | `api.sharadar.com`, Nasdaq Data Link | `lastpricedate` can include an OTC tail (RSHCQ, LEHMQ). Recycled tickers get digit suffixes (ALTR1). `figi` filled for 3,862 of 14,650 delisted rows. |
| **Massive (Polygon.io)** | `delisted_utc`, documented as the last date traded | Aggregates (bars only on days with qualifying trades) | From 2003-09-10 | Key. Free tier: 5 calls/min, 2 years. All history from $199/mo (aggregates). Individual plans are non-business use. | REST | Not tested (keyless request returns 401). |
| **EODHD** | Delisted symbol list; EOD series ends at delisting | Yes (EOD) | EOD only before 2018; paid plans "30+ years"; free plan past year | Key. Free: 20 calls/day. $19.99/mo EOD personal use. | REST | The vendor's own ATVI example ends in a flat, zero-volume row dated the day trading was halted. |
| **Financial Modeling Prep** | `delistedDate` | Not in this endpoint | Not stated | Key. Full list on Premium/Ultimate; Basic/Starter get the first page only. | REST | Semantics of `delistedDate` undocumented; not tested (401). |
| **Alpha Vantage LISTING_STATUS** | `delistingDate` = Tiingo's last row date in 427/438 matched events | Free daily is `compact` (last 100 points) only | `date` parameter must be after 2010-01-01 | Key. 25 requests/day free. Personal, non-commercial licence. | CSV API | Includes Tiingo's zero-volume rows (ALTR, CTCM). One row per symbol (Altera, Spirit, Lehman missing). |
| **Yahoo Finance chart endpoint** | No (404 "symbol may be delisted") | Acquirer only (CVS 80.27) | n/a | Unofficial | `query1.finance.yahoo.com/v8/finance/chart` | Yahoo's terms prohibit automated collection without permission. |
| **Stooq** | No (AET, ALTR, SAVE "not in database") | Acquirer only; default close is dividend-adjusted | n/a | Free web | stooq.com | The CSV endpoint serves a JavaScript proof-of-work page to non-browser clients. |
| **Nasdaq.com quote API** | No ("Symbol not exists" for ALTR) | No | n/a | Unofficial | `api.nasdaq.com` | — |
| **Norgate Data** | Yes (delisted symbol suffix = year-month last traded) | Yes | 1990 (Platinum) or 1950 (Diamond) | Paid: $630 or $787.50 per year | Vendor software | Not tested. Names relegated to OTC are kept as "current", not delisted. |
| **CRSP (via WRDS)** | Yes: `DLSTDT` = "a security's last price on the current exchange" | Yes (`PRC` on that date; `DLPRC` after) | 1925 onward | Paid, institutional | WRDS | Not tested. crsp.org now redirects to Morningstar pages. |
| *Tiingo (baseline)* | Last row often a zero-volume filler (274/461) | Close on last nonzero-volume row | — | — | raw CSVs | See §3.14. |

---

## 3. Findings by source

### 3.1 The rules: what Rule 12d2-2 and Form 25 say about timing

- **Suspension and delisting are separate acts.** Rule 12d2-1(a): an exchange
  "may suspend from trading a security listed and registered thereon in
  accordance with its rules", and "shall promptly notify the Commission of any
  such suspension, the effective date thereof, and the reasons therefor"
  ([17 CFR 240.12d2-1](https://www.ecfr.gov/current/title-17/section-240.12d2-1)).
  I found no EDGAR form type that carries these 12d2-1 notices. In practice the
  suspension date surfaces inside the Form 25 attachment (§3.2).
- **Form 25 effectiveness.** Rule 12d2-2(d)(1): the Form 25 strike from listing
  "will be effective 10 days after Form 25 is filed with the Commission". Rule
  12d2-2(d)(2): withdrawal of 12(b) registration is effective 90 days after
  filing ([17 CFR 240.12d2-2](https://www.ecfr.gov/current/title-17/section-240.12d2-2)).
  For (a)-type removals (redemption, maturity, substitution by merger,
  extinguished rights), the exchange files "within a reasonable time after" it is
  reliably informed. For exchange-initiated (b) removals, its rules must give
  notice to the issuer, an opportunity to appeal, and public notice "no fewer
  than 10 days before the delisting becomes effective".
- **Form 25 instructions** repeat the 10-day and 90-day rules. They tell
  exchanges to "attach the delisting determination to this Form 25 to serve as
  the required Notice" under Rule 19d-1 (General Instruction 2,
  [Form 25](https://www.sec.gov/files/form25.pdf)). That attachment is the
  EX-99.25 exhibit read in §3.2.
- **History.** Release 34-52029 (effective 2005-08-22, compliance date
  2006-04-24) made Form 25 an electronic EDGAR filing for both exchange- and
  issuer-initiated delistings. Before it, exchange and issuer delisting
  applications "are currently submitted in paper only and cannot be filed on
  EDGAR". In the same release, the NYSE and Amex asked that the new rule not
  affect their power to suspend trading before a delisting takes effect
  ([34-52029](https://www.sec.gov/files/rules/final/34-52029.pdf)). EDGAR-native
  Form 25 evidence therefore starts in 2006.
- **Form 8-K Item 3.01** (added by Release 33-8400, effective 2004-08-23,
  [33-8400](https://www.sec.gov/files/rules/final/33-8400.pdf)) requires the
  date the registrant *received the notice*, not the date trading stopped.
  Instruction 1 exempts delistings caused by redemption, maturity, substitution
  of other securities (mergers) or extinguished rights from paragraph (a)
  ([Form 8-K](https://www.sec.gov/files/form8-k.pdf)). No rule requires an
  issuer to state its last trading day.
- **Consequence for the Form 25 date.** The filing date is a poor stand-in for
  the last trade date in involuntary cases. RSH was suspended after the close on
  2015-02-02, but its Form 25-NSE was filed 2015-03-20. LEH was suspended
  2008-09-17 and its Form 25-NSE was filed 2008-10-15. SAVE was halted
  2024-11-18 and its Form 25-NSE was filed 2024-12-05. For mergers the gap is
  small. Across this repo's classifications
  (`output/delist_classifications.csv`, Form 25/25-NSE rows only), the Form 25
  was filed one business day after Tiingo's last nonzero-volume day in 232 of
  342 merger events and on the same day in 63. For compliance failures (n=30)
  the gap was spread out: +1 day in 8 cases, 2–5 days in 5, 6–30 days in 7,
  more than 30 in 2, and 8 cases at zero or negative. Tiingo's nonzero-volume
  date is itself an imperfect baseline (§3.14), so these counts are
  approximate.

### 3.2 EDGAR Form 25-NSE: the exchange's EX-99.25 notice

**What it contains.** The XML primary document (`primary_doc.xml`) holds the
exchange, issuer, class of security, `ruleProvision` (e.g.
`17 CFR 240.12d2-2(a)(3)` or `…(b)`) and `signatureDate`. It has no trading
date. The exhibit is where the date is.

- **NYSE, merger-type (a)(3).** AET, accession `0000876661-18-001269`: the NYSE
  notice says the security "was suspended from trading on November 29, 2018",
  and that the merger "became effective before the opening on November 29,
  2018". MER, `0000876661-09-000017`: "suspended from trading on January 2,
  2009". In both cases the date is the **first day not traded**. Tiingo, MIDAS
  and the 8-Ks all put the last trade on the previous session (2018-11-28 and
  2008-12-31).
- **NYSE, involuntary (b).** RSH, `0000876661-15-000132`: NYSE Regulation "on
  February 2, 2015, determined that the Common Stock … should be suspended
  immediately", and made a ticker announcement "immediately and at the close of
  the trading session on February 2, 2015". LEH, `0000876661-08-000395`: the
  same template, with the announcement "at the close on September 17, 2008".
  SAVE, `0000876661-24-001142`: "On November 18, 2024, the Exchange determined …
  should be suspended from trading", with no time of day. RSH and LEH traded on
  the determination day; SAVE did not (§3.5, §3.6). The (b) date alone does not
  say whether that day traded.
- **Nasdaq, merger-type (a)(3).** ALTR, `0001354457-25-000243`: the EX-99.25
  file `altr-form25.txt` contains only its own file name. In the sample below,
  20 of 21 Nasdaq (a)-type notices had no text beyond that.
- **Nasdaq, involuntary (b).** Wording varies. CTCM, `0001354457-16-000458`:
  "notified the Company that trading in the Companys securities would be
  suspended on May 19, 2016". Exceed Co (EDS), `0001354457-15-000094`: gives
  the dates of notification and finality and the effective date of removal
  (June 1, 2015), but no suspension date.

**Consistency across eras (sample).** I drew Form 25-NSE filings from the EDGAR
quarterly `form.idx` for Q2 of 2007, 2010, 2014, 2018, 2022 and 2025. That is
up to 5 random filings per exchange filer agent per year, 123 in total, across
all security types (common, preferred, notes, ETFs). A filing counted as
"dated" if a sentence containing suspend/halt/"last day of trading" carried a
date.

| Exchange | Rule | Sampled | Dated |
|---|---|---|---|
| NYSE | (a) | 25 | 25 |
| NYSE | (b) | 4 | 4 |
| NYSE American / Amex / NYSE MKT | (a) | 22 | 22 |
| NYSE American / Amex / NYSE MKT | (b) | 7 | 4 |
| NYSE Arca | (a)+(b) | 24 | 24 |
| Cboe BZX | (a) | 7 | 7 |
| Boston SE (2007) | (b) | 4 | 3 |
| Nasdaq | (a) | 21 | 0 |
| Nasdaq | (b) | 9 | 5 |

The NYSE-family (a) template ("…this security was suspended from trading on
<date>") appears unchanged from 2007 (e.g. Houston Exploration,
`0000876661-07-000524`) through 2025.

**Search.** EDGAR full-text search indexes the EX-99.25 exhibits. A query for
the phrase "suspended from trading", restricted to form 25-NSE and 2015, returned
386 hits; the first 15 inspected were all EX-99.25 exhibits. A per-company query (`q=suspended&ciks=…`)
returns the closing 8-K and the Form 25 notice as the top two hits for AET and
RSH. The service covers filings "submitted electronically since 2001" including
all attachments ([EFTS FAQ](https://www.sec.gov/edgar/search/efts-faq.html)). It
returned transient HTTP 500s during testing; a retry succeeded.

### 3.3 EDGAR closing 8-K (Item 3.01 / 2.01) and exhibits

- **What issuers write.**
  - AET (`0001122304-18-000178`): requested that trading "be suspended prior to
    the opening of trading on November 29, 2018".
  - MER (`0000950123-09-000005`): trading "ceased before the opening of trading
    on January 2, 2009".
  - ALTR (`0001193125-25-066329`): requested that Nasdaq suspend trading "at the
    close of the market on March 26, 2025". Nasdaq's halt record shows ALTR
    halted at 19:50 on March 25 and never traded on March 26 (§3.6).
  - ATVI (`0001104659-23-108985`): requested a halt "prior to the open of
    trading on the Closing Date".
  - RSH (`0000096289-15-000007`): "Trading was suspended immediately after the
    close on February 2, 2015".
  - LEH (`0001104659-08-059900`): gives the suspension (September 17, 2008) and
    that the stock "closed at $0.14 per share on September 17, 2008". This was
    the only 8-K checked that states a last close.
  - SAVE (`0000950103-24-016594`): "trading in the Common Stock was suspended
    immediately on November 18, 2024", and trading moved to OTC Pink as SAVEQ.
- **How often a date is present.** The repo's EDGAR text cache
  (`cache/edgar/text/`, 1,025 stripped filings fetched by the classifier) holds
  388 filings containing "Item 3.01", and 363 of them also contain "Item 2.01"
  (closing 8-Ks). Regex classification of the Item 3.01 sections of those 363:
  - 215 (59%) contain an explicit dated phrase (prior to the open on D, at or
    after the close on D, suspended on D, ceased trading on D).
  - 41 (11%) are relative ("prior to market open on the Closing Date"), which
    can be resolved from Item 2.01.
  - 12 (3%) say only that trading "has been halted".
  - 95 (26%) matched none of the patterns.

  The cache is skewed to 2015 onward (2 filings from 2004–2009), so this does
  not measure early-era consistency.
- **Volume in full-text search.** 2024 8-Ks containing each phrase: "suspended
  from trading" 520, "prior to the opening of trading" 178, "ceased trading" 75,
  "last day of trading" 47, "will no longer trade" 33. EFTS hits carry the 8-K
  `items` array and `period_ending` fields, so results can be filtered to Item
  3.01 filings without fetching them.
- **Before August 2004** there is no Item 3.01. I did not test whether pre-2004
  8-Ks or their press-release exhibits state last trading days (unverified).

### 3.4 Form 15

AET's Form 15-12B (`0001122304-18-000184`) lists the classes, the rule relied
on and the approximate number of holders of record. Form 15 has no field for a
trading date. It is not a source for this question.

### 3.5 SEC MIDAS "Metrics by Individual Security"

- **What it is.** Daily rows per ticker from January 2012 to June 2026, in
  quarterly ZIPs of about 11–23 MB. Columns: `Date, Security, Ticker, McapRank,
  TurnRank, VolatilityRank, PriceRank, LitVol, OrderVol, Hidden, …, OddLotVol,
  TradeVolForOddLots`
  ([page](https://www.sec.gov/opa/data/market-structure/marketstructuredownloadshtml-by_security.html);
  file e.g. `/files/opa/data/market-structure/metrics-individual-security/individual_security_2018_q4.zip`).
  There is no price; `PriceRank` is a decile. The bundled README says volumes
  come from exchange direct feeds, and from the SIP for NYSE before May 2017 and
  for Amex. It covers exchanges only: no TRF/off-exchange and no OTC.
- **Tested.** The last day with nonzero `LitVol + HiddenVol`:
  - AET 2018-11-28
  - ALTR 2025-03-25
  - SAVE 2024-11-15
  - RSH 2015-02-02
  - CTCM 2016-05-18
  - ATVI 2023-10-12
  - VMW 2023-11-21

  ATVI (2023-10-13), VMW (2023-11-22) and AFSI (2018-11-29) each have a row
  with orders and cancels but zero trades on the halt day, so rows must be
  filtered on volume, not presence. HZNP (Nasdaq, delisted 2023-10-06) has no
  rows in the 2023 Q4 file, so coverage is not complete.
- **Agreement.** I took the 52 classified events whose Tiingo last date falls
  in six downloaded quarters (2015Q1, 2016Q2, 2018Q4, 2023Q4, 2024Q4, 2025Q1).
  45 had MIDAS trades. Against the MIDAS last exchange-trade day:
  - Tiingo's raw last date agreed in 14.
  - Tiingo's last nonzero-volume date agreed in 38.
  - Sharadar `lastpricedate` agreed in 40.

### 3.6 Nasdaq trade-halt feed

- **Endpoint.** `https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate=MMDDYYYY`
  returns the halts for that date, keyless. Fields: `IssueSymbol, Mkt,
  ReasonCode, HaltDate, HaltTime, ResumptionDate, ResumptionTradeTime`. Code D
  is "Security deletion from NASDAQ / CQS"
  ([halt codes](https://www.nasdaqtrader.com/Trader.aspx?id=TradeHaltCodes)).
  The Trade Halts page links a Halt Search and a Halt History
  ([page](https://www.nasdaqtrader.com/Trader.aspx?id=TradeHalts)).
- **Tested hits (all code D):**
  - ALTR: halted 2025-03-25 19:50, resumption 2025-03-27. Last trade day
    03-25; the 8-K's "close of the market on March 26" is off by one day.
  - ATVI: halted 2023-10-12 19:50.
  - Altera (the earlier ALTR): halted 2015-12-28 08:52 before the open, so its
    last day was 2015-12-24.
  - LEH (Mkt `C`): halted 2008-09-17 17:15, after the close.
  - SAVE (Mkt `N`): halted 2024-11-18 04:30, before the open, with resumption
    16:45. There was no regular-session trading on 2024-11-18.
- **Misses.** No entry for AET (11/28–29/2018), MER (12/31/2008, 1/2/2009), RSH
  (2/2/2015) or CTCM (5/17–5/20/2016). The feed confirms a date when a halt
  exists, but it is not a complete delisting register.

### 3.7 Other exchange and SRO lists

- **Nasdaq Daily List.** A monthly subscription product covering new listings,
  delistings, symbol and name changes and dividends, with historical
  corporate-action data back to 1999
  ([product page](https://www.nasdaqtrader.com/Trader.aspx?id=DailyListPD)).
  Not tested; whether it gives a last trading date rather than an effective
  deletion date is unverified.
- **NYSE.** The delistings page lists issues *pending* delisting from the Form
  25 filing until effectiveness, about 10 days
  ([page](https://www.nyse.com/regulation/delistings)). The trading-halts page
  keeps historical halts for one year ([page](https://www.nyse.com/trade-halt)).
  Neither is a historical source.
- **FINRA OTC Daily List.** OTC securities only. History from 2014-11-17
  ([user guide](https://www.finra.org/sites/default/files/OTCE_Daily_List_User_Guide.pdf)).
  The public API is keyless and partitioned by `calendarDay`; partitions run
  2016-01-18 to date, plus one backfill partition (2018-10-25) holding records
  from 2014-11-17 to 2017-02-06. Endpoint:
  `POST https://api.finra.org/data/group/otcMarket/name/otcDailyList`
  with `compareFilters`. Results:
  - SAVE: 2024-11-18 16:52, "Market Center Change Delisted from NYSE", SAVEQ
    added, comment "Market move from NYSE (SAVE)".
  - RSH: 2015-02-03 08:23, "Market Center Change", RSHC, "Delisted from NYSE
    (RSH)". Then 2015-02-06, RSHC→RSHCQ, "Bankruptcy Filed".

  This dates the move to OTC, which bounds the last exchange day from above. It
  does not cover mergers (no OTC continuation) or anything before November 2014.

### 3.8 SEC fails-to-deliver files

- **Semantics.** The SEC's data page says the price field "includes the
  closing price of the security on the previous day as long as the price is
  available and is greater than one penny". Records exist only when the net
  fail balance is nonzero, and before 2008-09-16 only when it is at least 10,000
  shares. Coverage runs February 2004 to August 2026, with CUSIP, symbol and
  description on each row
  ([page](https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data)).
  The price semantics are stated under "Data Starting July 2009". The page does
  not say whether they hold for earlier files.
- **Confirmed semantics.** A row dated D carries the close of the prior trading
  day:
  - CVS row 2018-11-29 = 80.27, the 2018-11-28 close.
  - BAC row 2009-01-02 = 14.08, the 2008-12-31 close.
  - MER row 2008-12-30 = 11.07, the 2008-12-29 close.

  Each matches Tiingo's close for that day.
- **Coverage of the last close.** For the 45 MIDAS-dated events above, 42 had
  an FTD row within five calendar days after the last exchange-trade day. RSH
  had to be checked by hand because its file sits under a different URL path.
  In 40 of the 42 the price equals Tiingo's close on the last trade day, to
  FTD's two decimals. The exceptions: KWK (FTD 0.06 vs Tiingo 0.146) and CTV
  (no Tiingo close). Rows after the last trade repeat the last close. ALTR's
  2025-03-27 row shows 111.85, the 03-25 close. So FTD gives the price but not
  its date; pair it with MIDAS or a halt record. The sample is mostly
  mid/large-cap merger targets, which are more likely to have fails.
- **Beyond the last close.** Because rows are keyed by CUSIP, they follow the
  security into OTC under its new symbol. They give the first post-delisting
  prints CRSP would use as a terminal value:
  - SAVE (CUSIP 848577102): 1.08 on the 11/18 row, then SAVEQ 0.15 on the 11/20
    row.
  - RSH (CUSIP 750438103): 0.24 on the 2/3 row, 0.11 on 2/4, then RSHC and
    RSHCQ at 0.13–0.20.
  - LEH (CUSIP 524908100): 0.13 on the 2008-09-18 row, 0.05 on 9/19, LEHMQ from
    9/23.
- **Known disagreement.** LEH's 9/18/2008 row says 0.13 while the issuer's 8-K
  says the 9/17 close was $0.14 (unresolved; pre-July-2009 price semantics are
  not documented).

### 3.9 Alpha Vantage

- **Docs.** `LISTING_STATUS` returns active or delisted US stocks and ETFs as of
  the latest day or a given `date`, which must be later than 2010-01-01. The
  docs do not define `delistingDate`. `TIME_SERIES_DAILY` `outputsize=full` is
  premium; the free `compact` output is the latest 100 points. The free tier is
  25 requests/day
  ([documentation](https://www.alphavantage.co/documentation/#listing-status),
  [support](https://www.alphavantage.co/support/)). The licence is "for
  personal, non-commercial use" unless agreed otherwise
  ([terms](https://www.alphavantage.co/terms_of_service/), §2).
- **Keyless.** `apikey=demo` answered only the exact documented example URL
  (delisted as of 2014-07-10, 430 rows). An undocumented variant returned `{}`.
- **Semantics, tested on the user's snapshot**
  (`qlib_practice/.../alphavantage_listing_status/listing_status_delisted_2026-09-12.csv`,
  9,464 rows):
  - `delistingDate` equals Tiingo's last row date in 427 of 438 matched events,
    including Tiingo's zero-volume filler days: ALTR 2025-03-26, CTCM
    2016-05-26 (Nasdaq suspended CTCM on 2016-05-19).
  - One row per symbol. Altera (ALTR, 2015), Spirit Airlines (SAVE) and Lehman
    (LEH) are absent.
  - AV's `delistingDate` is not an independent last-trade date.
  - Whether AV serves daily prices for delisted symbols is unverified (no key).

### 3.10 Massive (formerly Polygon.io)

- `polygon.io` now redirects to `massive.com`; `api.polygon.io` still answers
  and returns 401 "API Key was not provided" without a key.
- **All Tickers** (`GET /v3/reference/tickers`) accepts `date` for a
  point-in-time universe and `active=false`. It returns `delisted_utc`, "The
  last date that the asset was traded", plus `cik`, `composite_figi` and
  `share_class_figi`. It can be queried by CUSIP, but "due to legal reasons we
  do not return the CUSIP". Records date back to 2003-09-10; Stocks Basic
  (free) gets 2 years
  ([docs](https://massive.com/docs/rest/stocks/tickers/all-tickers.md)).
- **Custom Bars** (`/v2/aggs/ticker/{t}/range/…`) are built only from
  qualifying trades. With no eligible trades "no aggregate bar is produced", so
  the last daily bar should be a real trading day. `adjusted` defaults to true
  (split adjustment); pass `adjusted=false` for as-traded prices. History by
  plan: Basic 2 years, Starter 5, Developer 10, Advanced and Business all
  ([docs](https://massive.com/docs/rest/stocks/aggregates/custom-bars.md)).
- **Pricing.** Stocks Basic is $0 with 5 API calls/minute. Advanced is
  $199/month, "Individual use only"
  ([pricing](https://massive.com/pricing)). Individual plans are for "personal,
  individual, and non-business use"; business use needs the business terms
  ([terms](https://massive.com/terms)).
- Not tested with data. Whether `delisted_utc` includes filler or OTC days, and
  how aggregates behave for recycled tickers, are unverified.

### 3.11 Financial Modeling Prep

- **Endpoint.** `GET https://financialmodelingprep.com/stable/delisted-companies?page=0&limit=100`,
  requiring an `apikey`
  ([docs](https://site.financialmodelingprep.com/developer/docs/stable/delisted-companies)).
  An FMP article lists the output fields as symbol, company name, exchange, IPO
  date and delisted date
  ([article](https://site.financialmodelingprep.com/how-to/how-to-handle-delisted-companies-and-historical-symbols-with-a-free-api)).
  No price is included, and the meaning of `delistedDate` is not documented.
- **Plans.** From the pricing matrix, "Delisted Companies" is page-capped
  ("Page Maxed to 0") on Basic and Starter and "Full Access" on Premium and
  Ultimate. Basic: 250 calls/day. Starter: up to 5 years of history. Premium:
  up to 30 years. "Displaying or redistributing data sourced from FMP requires"
  a separate licensing agreement
  ([pricing](https://site.financialmodelingprep.com/pricing-plans)).
- A keyless request returned 401. FMP's docs pages returned 403 to curl and
  WebFetch; the docs page loaded with a browser User-Agent.

### 3.12 EODHD

- **Workflow.** List delisted symbols per exchange with
  `exchange-symbol-list/US?delisted=1`, then call the normal `/api/eod/{T}`.
  Availability by delisting year: after 2018, EOD plus fundamentals, dividends
  and splits; after 2021, intraday too; before 2018, EOD only. A US-only symbol
  change history endpoint exists
  ([docs](https://eodhd.com/financial-apis/delisted-stock-companies-data)).
- **Their own example.** The docs' ATVI.US response ends with
  `{"date":"2023-10-13","open":94.42,…,"close":94.42,"volume":0}`. ATVI was
  halted before the open on 2023-10-13 (§3.3, §3.6), so EODHD carries the same
  kind of filler row as Tiingo.
- **Plans.** Free: 20 calls/day, past year only. EOD Historical Data — All
  World: $19.99/month, "30+ years", personal use; commercial use needs a
  different plan ([pricing](https://eodhd.com/pricing)).
- **Keyless.** The `demo` token returned 403 for ATVI.US and for the delisted
  list, and 200 for AAPL.US.

### 3.13 Sharadar (direct API or Nasdaq Data Link)

- **Tables.**
  - `tickers` is the securities master. Fields include `permaticker`
    (permanent), `isdelisted`, `figi` ("Composite FIGI"), `cusips`,
    `firstpricedate` and `lastpricedate`; history from June 1990
    ([docs](https://sharadar.com/docs/tickers)).
  - `stocks` (SEP) has daily OHLCV including `closeunadj`, for active and
    delisted stocks, from December 1997 ([docs](https://sharadar.com/docs/stocks)).
  - `actions` covers listing and delisting dates, delist reasons and acquirer
    `contraticker` from January 1998 ([docs](https://sharadar.com/docs/actions)).
  - On Nasdaq Data Link, `SHARADAR/TICKERS` metadata shows `"premium": false`;
    `SEP` and `ACTIONS` are premium
    ([metadata](https://data.nasdaq.com/api/v3/datatables/SHARADAR/TICKERS/metadata.json)).
- **Access tested.** Sharadar's docs say the `test-api-key` queries any table
  "for AAPL data" ([auth](https://sharadar.com/docs/auth)). The tickers page
  gives an example with the same key for the whole `table=stocks` list
  "including delisted". With it, TICKERS returned 20,986 stock rows (14,650
  delisted) in three pages (`limit=10000&skip=…`). SEP returned AAPL but
  answered "Exceeds free tier" for AET. Limits: 30 tickers and 200 characters
  per `ticker` parameter.
- **What `lastpricedate` means in practice.** The last date in Sharadar's price
  series.
  - It agrees with MIDAS in 40 of 45 events and with Tiingo's last
    nonzero-volume date in 346 of 455 matched events. It agrees with Tiingo's
    raw last date in only 132 of 455.
  - It avoids Tiingo's filler days: ALTR 2025-03-25, ATVI 2023-10-12, CTCM
    2016-05-18, Altera `ALTR1` 2015-12-24.
  - It can run into OTC trading after an involuntary delisting: `RSHCQ`
    2015-03-19 and `LEHMQ` 2008-10-15, which fall close to the Form 25 filing
    dates.
  - For `SAVEQ` it gives 2024-11-18, a day with no exchange trading.
- **Identifiers.** Recycled tickers get numeric suffixes (`ALTR1` = Altera,
  `AAN1`). `figi` was blank for AET, MER, LEH and RSHCQ; overall it is filled
  for 3,862 of 14,650 delisted rows. It cannot serve as the FIGI key by itself.

### 3.14 Tiingo (the current baseline), for comparison

These results use the raw Tiingo panel
(`qlib_practice/fetch_data_aplha/data/tiingo_2026_05_22/raw_tiingo_csv/`) and
the repo's 461 delisted events.

- 274 series end in one or more **zero-volume rows**: 134 with one, 30 with
  2–5, 80 with 6–20, 30 with more than 20. 271 of those tails have
  open = high = low = close, so they look forward-filled.
- Some filler rows carry small nonzero volume on days MIDAS shows no exchange
  trades: ATVI 2023-10-13 (1 share), VMW 2023-11-22 (200), AFSI 2018-11-29
  (726), SAVE 2024-11-18 (19,128 at a flat 1.08). Their origin (off-exchange
  prints or vendor artifacts) is unverified.
- The repo's `observed_delist_date` is Tiingo's last row. It therefore often
  sits after the true last trade date. The close on that row equals the last
  real close in all but 13 of the 274 filler tails.

### 3.15 Yahoo Finance, Stooq, Nasdaq.com

- **Yahoo.** `query1.finance.yahoo.com/v8/finance/chart/{T}` returned 404 "No
  data found, symbol may be delisted" for AET, RSH, SAVE, SAVEQ, MER, LEH, CTCM
  and ALTR. It returned CVS with a 2018-11-28 close of 80.27. The endpoint is
  undocumented. Yahoo's terms forbid collecting data "using any automated
  means … without our express, prior permission"
  ([terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)).
- **Stooq.** The CSV download endpoint answers non-browser clients with a
  JavaScript proof-of-work page; I did not bypass it. In a browser, AET.US,
  ALTR.US and SAVE.US were reported as not in the database. CVS.US showed a
  2018-11-28 close of 71.7482, the dividend-adjusted default; the page offers a
  "Skip: dividends" option.
- **Nasdaq.com.** `api.nasdaq.com/api/quote/ALTR/historical` returned "Symbol
  not exists".

### 3.16 Norgate Data

- Delisted US securities are included in the Platinum (history to 1990,
  $630/year) and Diamond (history to 1950, $787.50/year) packages
  ([packages](https://norgatedata.com/stockmarketpackages.php)).
- The database page says it holds 25,222 delisted securities from 1950 to
  September 2022 ([content tables](https://norgatedata.com/data-content-tables.php)).
  A delisted symbol carries a year-and-month suffix "indicating when the
  security last traded" (e.g. `ALOG-201806`). A security relegated to OTC that
  still trades is not counted as delisted; it stays as current with its OTC
  history.
- Not tested. The licence and redistribution terms were not found (the obvious
  terms URLs returned 404).

### 3.17 CRSP (via WRDS)

- CRSP defines Delisting Date (`DLSTDT`) as the date "of a security's last
  price on the current exchange". Delisting Price is a trade price, or a
  bid/ask average if negative, on another exchange or OTC, dated by "Delisting
  Date of Next Available Information"
  ([archived CRSP data definitions, 2023-03-29](https://web.archive.org/web/20230329040425/https://www.crsp.org/products/documentation/data-definitions-d)).
- DLRET compares the value after delisting "against the price on the
  security's last trading date"
  ([CRSP Calculations chapter, university mirror](https://leiq.bus.umich.edu/docs/crsp_calculations_splits.pdf)).
- CRSP is the reference for both fields, but it is a paid institutional
  subscription.
- `www.crsp.org` documentation URLs now redirect to `indexes.morningstar.com`,
  and the Data Descriptions Guide link cited in `dlret-generation.md` returns
  404. The field names used by CRSP's newer CIZ format were not checked.

---

## 4. Spot checks

The Tiingo baseline comes from `output/delist_classifications.csv`, with closes
from `output/dlret.csv` and the raw Tiingo panel. **LEH is not in the CSV**, and
the raw panel has no LEH file. MER (Merrill Lynch → Bank of America, NYSE,
2008-12-31) is the substitute for a 2008 NYSE case. LEH is still checked
against EDGAR, Nasdaq, FTD and Sharadar. The exchange-transfer case is **SAVE**
(Spirit Airlines, NYSE → OTC SAVEQ, bucket `exchange_transfer`). ATVI, CTCM and
Altera are extra cases met during the research.

### 4.1 Last exchange trading day

| Ticker | Tiingo baseline | 8-K Item 3.01 | Form 25 EX-99.25 | Nasdaq halt feed | MIDAS last day with trades | Sharadar `lastpricedate` | AV `delistingDate` | Resolved last day | Tiingo agrees? |
|---|---|---|---|---|---|---|---|---|---|
| AET (NYSE, CVS merger) | 2018-11-28 | suspended prior to open 11-29 | suspended from trading 11-29 (filed 11-29) | no entry | 2018-11-28 | 2018-11-28 | 2018-11-28 | **2018-11-28** | yes |
| LEH (NYSE, Ch. 11; not in CSV) | n/a | NYSE suspended 9-17; "closed at $0.14 … on September 17" | decided 9-17, announced at the close 9-17 (filed 10-15) | halted 9-17 17:15, code D | n/a (pre-2012) | `LEHMQ` 2008-10-15 (OTC tail) | no row | **2008-09-17** | n/a |
| MER (substitute; NYSE, BAC stock merger) | 2008-12-31 | ceased before open 2009-01-02 | suspended from trading 2009-01-02 (filed 01-05) | no entry | n/a (pre-2012) | 2008-12-31 | 2008-12-31 | **2008-12-31** | yes |
| ALTR (Nasdaq, Siemens cash merger) | 2025-03-26 (volume 0) | suspend "at the close of the market on March 26" | exhibit empty (filed 3-26) | halted 3-25 19:50, code D, resumes 3-27 | 2025-03-25 | 2025-03-25 | 2025-03-26 | **2025-03-25** | no (+1 filler day) |
| RSH (NYSE, compliance) | 2015-02-02 | suspended immediately after the close 2-2 | decided 2-2, announced at the close 2-2 (filed 3-20) | no entry | 2015-02-02 | `RSHCQ` 2015-03-19 (OTC tail) | 2015-02-02 | **2015-02-02** | yes |
| SAVE (NYSE → OTC, `exchange_transfer`) | 2024-11-18 (volume 19,128, flat 1.08) | "suspended immediately on November 18" | decided 11-18 (filed 12-05) | halted 11-18 04:30 before the open, code D | 2024-11-15 | `SAVEQ` 2024-11-18 | no row | **2024-11-15** | no (+1) |
| ATVI (Nasdaq, extra) | 2023-10-13 (volume 1) | halt prior to open on Closing Date (10-13) | — | halted 10-12 19:50, code D | 2023-10-12 | 2023-10-12 | — | **2023-10-12** | no (+1) |
| CTCM (Nasdaq, extra) | 2016-05-26 (6 zero-volume rows) | — | Nasdaq: suspended May 19, 2016 | no entry | 2016-05-18 | 2016-05-18 | 2016-05-26 | **2016-05-18** | no (+6) |

Supporting OTC-side dates from FINRA: SAVE added to OTC as SAVEQ on 2024-11-18
at 16:52; RSH moved to OTC as RSHC on 2015-02-03 at 08:23. Altera (the 2015
holder of ALTR) is not an event in the CSV. Sharadar `ALTR1` gives 2015-12-24,
and Nasdaq's halt at 08:52 on 2015-12-28 confirms it.

### 4.2 Close on that day

| Ticker | Tiingo close on resolved day | FTD (row date: price) | Other |
|---|---|---|---|
| AET | 212.70 | 2018-11-29: 212.70 | Yahoo/Stooq: no data |
| CVS (AET acquirer, 2018-11-28) | 80.27 | 2018-11-29: 80.27 | Yahoo 80.27; Stooq default 71.75 (dividend-adjusted) |
| LEH | n/a | 2008-09-18: 0.13 | 8-K: $0.14. The two disagree. |
| MER | 11.64 | no row for 2009-01-02; last MER row 2008-12-30: 11.07 (the 12-29 close) | — |
| BAC (MER acquirer, 2008-12-31) | 14.08 | 2009-01-02: 14.08 | — |
| ALTR | 111.85 | 2025-03-27: 111.85 | Tiingo's 3-26 filler row repeats 111.85 |
| RSH | 0.2402 | 2015-02-03: 0.24 | next OTC rows: 0.11, then 0.13–0.20 as RSHC/RSHCQ |
| SAVE | 1.08 (11-15) | 2024-11-18: 1.08 | first OTC close: SAVEQ 2024-11-20 row: 0.15 |
| ATVI | 94.42 | 2023-10-13: 94.42 | EODHD doc example: 94.42 on 10-13, volume 0 |

**Reading the tables.** For merger-type delistings the last close barely
depends on the date. The filler rows repeat the last close, so DLRET is
unaffected, but any date-keyed join (month assignment, acquirer price date,
successor linking) is not. For involuntary delistings both matter. SAVE's
exchange close (1.08 on 11-15) and first OTC print (0.15) differ by a factor of
seven.

---

## 5. Open questions and what I could not verify

1. **Pre-2006 and pre-2004 EDGAR.** Electronic Form 25 starts in 2006 and Item
   3.01 in August 2004. I did not test how often earlier 8-Ks (old Item 5,
   press-release exhibits) state a last trading day. The cached 8-K sample has
   only two filings from 2004–2009.
2. **Nasdaq merger notices before 2007.** All sampled Nasdaq (a)-type notices
   were empty, and none were sampled before 2007. Whether any Nasdaq-era text
   gives the date is unknown.
3. **The 26% of closing 8-Ks with no detected date.** These were classified by
   regex only. Some may state the date in a form the patterns missed, or in
   the press-release exhibit (not scanned).
4. **Tiingo's small-volume filler rows** (1, 200, 726, 19,128 shares) on days
   with zero MIDAS exchange volume. Whether these are real off-exchange prints
   (TRF, after-hours) or vendor artifacts was not determined.
5. **FTD price semantics before July 2009.** The SEC page states the
   "previous day's close" rule under "Data Starting July 2009". LEH's
   2008-09-18 row (0.13) disagrees with the 8-K (0.14), and LEH's 2008-09-16
   row repeats the 09-12 close. Treat pre-2009 FTD prices as unverified.
6. **Massive/Polygon, FMP, EODHD, Norgate and CRSP data** were not tested
   (they need keys or subscriptions). Their date semantics (filler days, OTC
   tails, recycled tickers) are from documentation only. EODHD's own example
   suggests filler rows exist there too.
7. **Alpha Vantage daily prices for delisted symbols.** Not testable keyless.
   The docs do not say.
8. **Sharadar's terms** for bulk use of the TICKERS table via the test key, and
   **Norgate's** redistribution terms, were not found.
9. **Nasdaq halt-feed coverage.** It had entries for 5 of the 9 delistings
   checked (ALTR, ATVI, Altera, LEH, SAVE; none for AET, MER, RSH, CTCM). Which delistings get a code-D halt (by exchange, era, event type)
   was not measured. The Halt History page may have more than the RSS
   `haltdate` parameter; not explored.
10. **SEC trading suspensions** (Exchange Act 12(k) orders, relevant to the
    classifier's REVOKED path) are published under Enforcement & Litigation →
    Trading Suspensions on sec.gov. Their historical depth and format were not
    examined.
11. **MIDAS coverage.** HZNP was missing from the 2023 Q4 file. The rule for
    which securities MIDAS includes (the page says "more than 4,800
    securities") was not found.

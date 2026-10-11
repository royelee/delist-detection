# Fix themes B: last trade date and endings (61 cases)

Inputs: no_last_trade_print (28), continued_filings_guess (22), last_trade_date_misread (4), reused_ticker_data (3),
resolver_no_bankruptcy_branch (3), late_form25 (1). Every skeptic verdict in these six files is "upheld" or "n/a"; no
refuted claim, so every case below can carry a fix. Where I say "likely" for a code location, I grepped but did not
trace the run; verify before building.

How the last trade date is decided today: `delistings.DelistingFinder._last_trade` collects (a) the Form 25 notice date
(`notice_last_trade`), (b) the 8-K item 3.01 text (`last_trade.eightk_last_trade`: "before the open on D" = D-1,
"after the close on D" = D, "last day of trading was D", bare "suspended on D" = D flagged unconfirmed), (c) MIDAS
(2012+, by ticker, `_confirmations`) and (d) the Nasdaq halt feed. `last_trade.decide_last_trade` picks MIDAS > halt >
confirmed notice > confirmed 8-K > unconfirmed notice > unconfirmed 8-K > none (`no_last_trade_date`). The internal
`delist_date` is the Form 25 filing + 10 days and ticker_history is clipped at it, not at the last trade. The
no-Form-25 path is `_fallback`/`_fallback_date` (anchored on `ctx.last_seen`, flag `delist_date_approx`).

---

## T1. A stated last day in a filing the reader did not use (8 cases)

Pattern: `no_last_trade_date`, `no_last_close`, `dlret_method=needs_last_trade`, `last_trade_date_source` blank, though an
8-K item 3.01 sentence, a Form 25 notice or the 8-K's defined "Closing Date" gives the day. Wordings missed:
"suspended after the close of trading on December 1" (GLBL), "ceased trading ... close of business on April 27" (NOVL),
"ceased effective as of the close of trading on October 20" (SEPR), "will be suspended after the closing of trading on
December 5" (PPDI), a 3.01 that states the date in prose (CTRX 2015-07-23), "continue to be listed through" (KG), "the
Closing Date" resolved from the Introductory Note (CDWC 2007-10-12), and the EX-99.25 notice date 2021-03-02 for a
continuation resolved via 8-K12B (APA).

Rule: widen `eightk_last_trade` into a sentence-level reader of the 3.01 section (and the 8-K body when 3.01 only says
"the Closing Date"): any of {suspend, cease, halt, delist, last day} within one sentence of a full date, classified open
(D-1) or close (D) by its wording; "Closing Date" resolves through `_closing_date` from the whole filing (including the
Introductory Note and a term defined without a leading paren). Read the Form 25 EX-99.25 notice date for fallback and
continuation rows too (APA: the continuation path never calls `notice_last_trade`; stage 9c `_date_from_notices` only
covers handoff continuation rows). Never take a day after the Form 25 effective date (decision 12).

Where: `last_trade.py` (`_OPEN`, `_CLOSE`, `eightk_last_trade`, `_closing_date`); `delistings._eightk_window` (window
`EIGHTK_BEFORE_DAYS`=60, `EIGHTK_AFTER_DAYS`=5 around the Form 25 filing; check it reaches a 3.01 filed on the closing
day); pipeline stage 9c for APA.

Guard: only a sentence that names this security's exchange suspension or cessation, not a merger date alone (RESP, ADCT,
IFIN: 3.01 gives the merger date but no trading day: those are T2). Never publish after the Form 25 effective date. Must
NOT change rows where MIDAS or a halt already decided (they win).

Cases: GLBL (BBG000BH2T94), NOVL (BBG000BQ3F39), SEPR (BBG000C0BGS7), PPDI (BBG000FRVFM1), CTRX (BBG000KBQZ88),
KG (BBG000CB2ZY4), CDWC (BBG000BHD665), APA (BBG000BC2C10). All no_last_trade_print.

Effect: `last_trade_date` and `last_trade_date_source` (`8k_301` or `ex99_notice`) appear; `no_last_trade_date`,
`no_last_close` leave uncertain_reasons; a last_close request becomes possible. APA also: the clip moves to 2021-03-01 and
the reason becomes the 8-K12B reorganization (`resolved_from_continued_filings`). APA's old line carrying CIK 1841666
is a separate issuer_history_bug, not fixed here.

Risks: regex false positives on a merger-date sentence; a 3.01 about another class (preferred). Keep the existing
"this security" check. Decisions: 12 (reference.md already counts "8-K item 3.01" as a print source, no ruling needed).

## T2. No filing states the last session: infer it from the closing day (17 cases)

Pattern: pre-2012 (no MIDAS), Form 25-NSE with no suspension date, 8-K 3.01 states the merger/closing date but no
trading day (or none at all). The library leaves the date blank (`no_last_trade_date`, `no_last_close`,
`needs_last_trade`), internal `delist_date` = Form 25 filing + 10 days (ticker_history clipped up to 10 days late), and
`cash_currency` blank. The reports propose the same rule in different words: "same-day-closing merger: last trade =
closing day" (AQNT, RESP, CHAP, CKFR via the Form 25 date), "effective before the open on D means D-1" (IMCL),
"suspended on the completion date" (SUNW, DSEY).

Rule (needs ruling): when an exchange-filed Form 25-NSE (12d2-2(a)(3)) or a 2.01/3.01 pair dates the removal at the
closing day C, and no text gives a stronger date, publish the trading day on or before C (C if the merger took effect
after the close, else previous_trading_day(C)) with a new source value (`closing_day_inferred`) that stays unconfirmed,
so the row stays uncertain but carries a date and a last_close request. Independently, set the ending date and the
history clip from the last trade day (or the Form 25 filing date for a 25-NSE), not filing + 10. Separately
`cash_currency=USD` (a payout-theme item; every case here lists it).

Where: `last_trade.decide_last_trade` (an inferred tier below the confirmed text tiers); `delistings._last_trade`/
`_last_trade_group`; the delist_date computation (filing + 10 days) and the clip in `pipeline._ends_the_security`/
`history.history_rows`; `payout_rule.value_fields` for currency.

Guard: needs a matched Form 25 (or a confirmed 2.01 date for FCL, SGP, LTRPA with no Form 25); only when MIDAS, halt and
text give nothing; never after the Form 25 effective date. Must NOT touch rows with a print or a text date (T1) or a
bankruptcy (T5). A tender offer plus later short-form merger (GENZ, IMCL, MLNM, CHAP) has two dates: use the merger
effective date, never the tender expiry. CKFR: anchor on the 2007-12-04 Form 25, not the Form 15 date 2007-12-14.
FCL: date the ending at the 2.01 effective date 2009-07-31, not the last fails row. LTRPA is OTC with no Form 25: clip at
the merger effective date.

Cases (all no_last_trade_print): ADCT (BBG000BB5HV5), DADE (BBG000BJ3QD0), IFIN (BBG000BJXXX0), GENZ (BBG000BK7SL0),
PHLY (BBG000BKKXG0), AQNT (BBG000BMZLP6), RESP (BBG000BS3FD4), MLNM (BBG000BX67G5), HLTH (BBG000C1R174),
DSEY (BBG00ZHCT050), SUNW (CIK709519-COMMON), CHAP (CIK1319048-COMMON), IMCL (BBG000CGQ485), CKFR (BBG000FHN2M1),
SGP (BBG000BSVZM9), FCL (BBG000BM1RP0), LTRPA (BBG005DKMJ67).

Effect: `last_trade_date`, `last_trade_date_source` (new value) and `price_date` appear; ticker_history/cusip_history
end on the last trade; `no_last_trade_date` is replaced by `last_trade_not_exchange_print:<source>` or
`last_trade_date_unconfirmed` (row stays uncertain, no longer missing a date). R2.1 `missing_last_trade_date` falls.
HLTH, SGP, FCL are stock or reverse-structure mergers: price_date and the acquirer line follow the date (the acquirer
line itself is a terms theme).

Risks: an inference, not a print; one-day errors are common and RESP shows the Form-25-minus-10 error (03-14 vs 03-27).
Several reports call the golden case conditional on a sourced day.

Decisions: 12 is touched. The field says "published only from an exchange print"; an inferred day needs an operator
ruling that a closing-day tier is published but stays uncertain. Decision 4 if the value falls to assumed par.

## T3. Date-source precedence: halts, bare "suspended on D", after-close wording, MIDAS conflict (5 cases)

Pattern. PMI: halted 2011-10-21, bankruptcy 2011-11-23, then suspension; the notice's bankruptcy date was taken
(`ex99_notice`, `last_trade_date_unconfirmed`); the halt-and-never-resumed day is the true last trade. WM (2008): the
date 2008-09-29 is the notice suspension day; the 8-K says halted at the 2008-09-26 open. MNK: the notice's suspension
date 2020-10-12 was taken as the last trade (should be D-1 = 2020-10-09). TMHC: the notice "suspended on July 24" was
read as before-open (D-1 = 07-23, `ex99_notice`) but the 8-K says following the close on July 24. DBD: MIDAS gave
2023-05-26 and conflicts with the 8-K suspension (`last_trade_date_conflict`); the true last NYSE print is about
2023-06-01.

Rule: (1) the 8-K's explicit timing word ("following the closing of trading on D", "before the open on D") outranks the
notice's bare suspension date; a bare "suspended on D" with no timing word reads as D-1 (exchange-open convention,
MNK) unless the 8-K says after close (TMHC). Today the bare-date paths return D itself in both the notice and
`8k_suspended_unconfirmed`. (2) A halt-then-delist shape ("trading was halted on D and did not resume") dates the last
trade at D (D-1 if halted at the open). (3) A `last_trade_date_conflict` between MIDAS/halt and text is resolved by a
second check against fails rows under the security's own CUSIP, not by letting MIDAS win. DBD: the report does not say
why MIDAS stopped early; verify before building (could be T4-style or a real early stop).

Where: `last_trade.decide_last_trade` (precedence), `eightk_last_trade` (the bare-suspended branch), `form25.
notice_last_trade` (not read in detail), `delistings._confirmations`.

Guard: precedence applies only between text sources; MIDAS/halt keep winning when they agree with a text day within one
trading day or no text day exists. Must NOT change rows where all sources agree. Do not apply the D-1 default where the
notice itself says "after the close".

Cases: PMI (BBG000BCTL84, last_trade_date_misread), WM (BBG000FXYZF9, no_last_trade_print), MNK (BBG002BHBHM1,
last_trade_date_misread), TMHC (BBG003PGJHP5, last_trade_date_misread), DBD (BBG000BGYDX9, no_last_trade_print).

Effect: `last_trade_date`/source change by one day (MNK, TMHC) or months (PMI); `last_trade_date_conflict`/
`last_trade_date_unconfirmed` clear; for the distress rows the Shumway -0.30 gives way to an `otc_print` request on the
right session (WM, PMI, MNK, DBD).

Rider (not extra cases): in WM, MNK, DBD (and WFT in T8, CBL and ASNA in T5) the `otc_print` request names the dead
NYSE ticker instead of the OTC symbol (WAMUQ, MNKKQ, DBDQQ, WFTIF, CBLAQ, ASNAQ). Source: `payout_rule._otc` takes
`row["ticker"]`. The OTC symbol can come from fails rows of the security's CUSIP dated after the last trade under another
symbol (`ftd.by_cusip`, suffix check Q/F/QQ/KQ). Reports ask for a non-fails confirmation of the symbol.

Risks: the D-1 default for a bare "suspended on D" is a ruling; TMHC shows current patterns already guess both ways.
Decisions: 12 (the "before the open" rule extended to the notice).

## T4. Ticker reuse: volume, prints and closes read by ticker after another security took the symbol (3 cases)

Pattern. CCE (2016): MIDAS volume under CCE on 2016-05-31 was the new CCEP shares under the reused ticker; last trade
should be 2016-05-27 (the 8-K suspension). JCI (2016): MIDAS 2016-09-06 is the new JCI; `last_trade_date_conflict`;
should be 2016-09-02. WEN (2008): the last close read by symbol WEN picked the successor's CUSIP row ($5.26), not
Wendy's own CUSIP, giving `terms_gate_failed:fail_sanity` and `merger_at_par`.

Rule: every by-ticker read is bounded by the security's own tenure of the ticker. (1) MIDAS/halt: ignore a day on or
after the first sighting of the successor that took the ticker (`ticker_successor_sec_id`) and, with no handoff, a day
later than a text-stated suspension date plus a few days. (2) FTD: `close_of`/`close_known_on` by symbol is a fallback
only when the row's CUSIP is one of the security's own, or no other security in the run holds the symbol that day.

Where: `delistings.DelistingFinder._confirmations`/`_tickers` (`self.midas.last_trade_day(t, lo, hi)` takes the latest
day under any ticker); `ftd.FtdIndex.close_of`/`close_known_on`; `handoffs.find_handoffs` supplies the successor's
start. Ordering problem: handoffs run after the delisting search, so the finder does not yet know the takeover. Either
pass a "ticker reused by" hint from `security_master.cusip_handoffs`/observations, or re-select the last trade after
the handoff stage like stage 9c `_date_from_notices`.

Guard: only when a successor or other holder of the symbol is known; a security that merely traded to the end keeps its
MIDAS day. Must NOT drop MIDAS for ordinary exchange transfers where the same security keeps the ticker. CCE's
`no_acq_ticker` (acquirer price_ticker CCE) is a terms issue, not this theme.

Cases: CCE (BBG000BF5RY1, reused_ticker_data), JCI (BBG000BMDV41, reused_ticker_data), WEN (BBG000BWPN99,
reused_ticker_data, library_wrong=False but still a library fix).

Effect: `last_trade_date` moves to the pre-takeover day and `last_trade_date_conflict` clears (CCE, JCI); WEN: no
`fail_sanity`, no `merger_at_par`/`assumed_par_after_failed_gate`, stock rule published; the acquirer's price_date
follows.

Risks: needs the successor's first day before the delisting is decided; a wrong exclusion drops real MIDAS.
Decisions: 12; decision 4 (assumed par disappears once the close is the target's own).

## T5. Bankruptcy endings the resolver does not branch on, and reset-4a3 (4 cases)

Pattern. CBL: no Form 25 for the common, continued filings made it a 304 transfer (`no_form25`, `delist_date_approx`,
`successor_unknown`, `continued_filings_rule`); the 8-K 1.03 and 3.01 were unused. ASNA: 8-K 2.01 was a Chapter 11 asset
sale; branch 4 (completed acquisition) made it a merger at par (`resolved_from_continued_filings`, `merger_at_par`).
SDRL: the Form 25 filed at plan emergence, notice and 6-K state Chapter 11 and a 0.0037345 ratio into new shares; bucket
`unknown`, `no_evidence_default` (the 1.03 predates the search window). TDW: reason "Bankruptcy (8-K item 1.03 filed
2017-05-18)", liquidation 470, ending dated at the 1.03 filing, but a prepackaged case whose stock stayed on the NYSE,
so `otc_print` has no date and a Shumway -0.30 fill.

Relation to reset-4a3 (roadmap: "a bankruptcy branch ahead of 'still trading after the end'; 8-K 1.03 plus a 3.01
suspension near the end and trading after under another symbol -> dropped/bankruptcy 574/470, valued by otc_print"): CBL
is the roadmap's named golden case and ASNA is the same shape, with one extra requirement: the bankruptcy branch must
sit ahead of branch 4 (2.01) so a Chapter 11 asset sale is not a merger (require a 1.03 within about 90 days before the
2.01). SDRL and TDW are outside 4a3 as written. So specify 4a3 as four sub-rules: (i) drop to OTC (CBL), (ii) bankruptcy
beats branch 4 (ASNA), (iii) a Form 25 filed at emergence whose notice or 6-K states a plan exchange or cancellation
(SDRL: stock rule with the new line as `price_sec_id`, needs ruling vs decision 11), (iv) a prepackaged case where the
stock stays listed (TDW: dated at the plan effective date from 8-K 1.02/3.03, no `otc_print`; value from warrants
for old equity, else `unknown`).

Where: `end_of_era.resolve` (branch order; new first branch) and `end_of_era.signals` (the 1.03/3.01 windows; widen the
1.03 look-back for emergence); `classifier._classify_items`; `delistings._fallback_date` (its first key `bankruptcy_8k`
dates at the 1.03 filing day: TDW's date fault); `exit_kind.ending_fields`; `payout_rule._otc` and `price_requests`
(OTC symbol, and no request when no OTC session).

Guard: an 8-K 1.03 within about 30 days of the end (4a3) plus a 3.01 suspension or Form 25 on the security's class;
post-end trading under a different symbol, or the plan text (SDRL). Must NOT change exchange transfers and holdco
continuations (XRX, CI, APA): decision 9 says "no cash, no bankruptcy" so bankruptcy beats a continuation, but a
solvent liquidation must not become bankruptcy.

Cases: CBL (BBG000B9YSK6, resolver_no_bankruptcy_branch), ASNA (CIK1498301-COMMON, resolver_no_bankruptcy_branch),
SDRL (BBG000BKQ3V3, resolver_no_bankruptcy_branch), TDW (BBG000BV18Z1, last_trade_date_misread).

Effect: exit kind/bucket to dropped/bankruptcy (574/470); `continued_filings_rule`, `merger_at_par`,
`no_evidence_default` clear; value rule `otc_print` (CBL, ASNA) with price_ticker CBLAQ/ASNAQ; SDRL stock rule with New
Seadrill added as a run security (successor_not_in_run theme); TDW date moves from the 1.03 filing to the plan effective
date; Shumway fills fall.

Risks: CBL's last trade (2020-10-30 vs 2020-11-02) rests on a halt record; false positives where a bankruptcy 8-K
precedes an unrelated merger. Decisions: 9, 11 (plan exchange vs stock rule: ruling), 3 (TDW warrants).

## T6. A reverse split's new CUSIP read as the end of the security (12 cases)

Pattern: no Form 25 found, `continued_filings_rule` (304), `no_form25`, `delist_date_approx`,
`last_trade_date_unconfirmed`. The security's CUSIP history/fails rows stop at the old CUSIP on the split date and the
fallback dates the end on the last sighting. The real ending (Form 25-NSE, bankruptcy or merger) is years later and
unreached. TERP also: branch 3 (8-K 5.01) fired on a stake purchase while the stock kept trading
(`resolved_from_continued_filings`), and the LLM then misread the stake purchase as terms. FMD also: a 3.01 about
regained compliance read as a deficiency.

Rule: a CUSIP change is the same security when the issuer CIK is the same, the ticker is still sighted, the old CUSIP's
last fails row is within about 30 days of the new CUSIP's first row under the same symbol and description, and the
8-K 5.03/3.03 is a reverse split (or no cash/bankruptcy). Join the CUSIPs into one `cusip_history`; the security's last
sighting becomes the later CUSIP's, so the finder reaches the real Form 25. For the resolver: before branches 3/4/5,
require that the security is not still trading under its joined CUSIPs after the end. (reset-4a2 lists "a new CUSIP in
the fails data" as left to do; this is that item.)

Where: `security_master.cusip_handoffs`/`candidate_cusips`/`era_cusips`/`_cusip_runs` (a same-issuer successor CUSIP run);
`history.cusip_sightings`/`backfill_cusips`; `delistings.SecurityContext.seen_after`/`last_seen` (`SEEN_AFTER_DAYS`=5,
uses own CUSIPs); `end_of_era.signals`/`resolve` (still-trading guard). `cusip_handoff` today links two eras by a
switch; here it is one era whose CUSIP changed.

Guard: same ticker and name description across the switch, no Form 25 and no cash or bankruptcy 8-K between. Must NOT
merge a different issuer that reused the ticker (T4), and a reclassification or exchange of a different claim stays
separate (decision 9). WIN's spin-off day CUSIP change 97382A101 -> 97382A200 is still a reverse split: the spin
distribution is a dividend-type event for the return, not an exit.

Cases (all continued_filings_guess): FMD (BBG000BN6349), RAD (BBG000BRWGG9), SVU (BBG000BTQ9G8; the reverse split is
"probably", not confirmed), MGI (BBG000Q02P20), DYN (BBG001D9S707), VRM (BBG009NGKQ45), CWTR (CIK1018005-COMMON),
MNI (CIK1056087-COMMON), WIN (CIK1282266-COMMON), FTR (CIK20520-COMMON), DF (CIK931336-COMMON), TERP (BBG006KY8KV2).

Effect: the 304/`continued_filings_rule`/`delist_date_approx` row disappears (MGI and WIN: no ending at all); the later
real ending appears (merger FMD, SVU; dropped/bankruptcy RAD, DYN, VRM, CWTR, MNI, FTR, DF, which needs T5; stock merger
TERP); ticker_history and cusip_history extend. Removes about a dozen false exchange_transfer rows.

Risks: merging wrong CUSIPs (spin-off, split-off); the later ending then depends on T8's Form 25 reach. Decisions: 9
(continuation), 11 (later OTC drop value).

## T7. The fallback ends a security at the caller's last sighting (4 cases)

Pattern: the only evidence of an ending is that the caller's observations or one placeholder sighting stop; the issuer
keeps filing so `continued_filings_rule` (304) invents a transfer on the sighting date (`no_form25`,
`delist_date_approx`). WW: observations end 2013-12-31, real ending 2025. IAC: observations stop 2014-06-30, Form 25
2020. RXO-WI: a when-issued ticker treated as a final ticker while the issuer is still listed. UAC-C: a dotted/suffixed
class ticker not matched, a placeholder (`placeholder_without_ticker_filing`) with one sighting.

Rule: the fallback does not publish an ending dated on a sighting without independent evidence that trading stopped
there (own-CUSIP fails stop, a Form 25, a delisting 8-K, a deregistration). Otherwise: "no ending observed" (a review
row such as `ended_without_delisting`), not a transfer. Resolve a `-WI` or `-<class>` ticker to the base ticker and class
before the finder (UAC-C -> UA Class C; RXO-WI -> RXO). A placeholder's single sighting is never an end.

Where: `delistings._fallback`/`_fallback_date` (`ctx.listed_today` checks); `end_of_era.resolve` branch 6; 
`observations.py` (ticker normalization); `ticker_resolver`; `listing_status.listed_today`.

Guard: an own-CUSIP fails stop before the sighting end is still an ending; here no CUSIP exists or the CUSIP keeps
trading. Must NOT touch genuine no-Form-25 cases whose own-CUSIP evidence stops while the issuer keeps filing.

Cases (continued_filings_guess): WW (BBG000DY6735), IAC (CIK891103-COMMON), RXO-WI (CIK1929561-COMMON),
UAC-C (CIK1336917-CLASS-C).

Effect: the 304 rows go; `observation_map` status reads `mapped`; `continued_filings_rule`, `delist_date_approx` vanish.
WW and IAC real endings appear only if the caller's window reaches them (the reports say the honest answer for a short
window is no ending observed).

Risks: some true endings with no fails trace become `left_view`, which counts against reset-4a's "L1.left_view falls"
objective. Needs a ruling that "no ending observed" beats a guessed transfer.

## T8. The Form 25 exists but the finder never matches it to this security (7 cases)

Pattern: the era's last sighting is early, so a later Form 25 falls outside the security's alive span (`_alive_at`: last
sighting + `SIBLING_ALIVE_AFTER_DAYS`=400, treated as "plainly not about any security" and skipped with no review item),
or it precedes the first sighting (`FORM25_LOOKBACK_DAYS`=30; earlier filings go to `early`, usable only by the
fallback), or its class text does not match (SPWRA "Class A & Class B"; TMUSR "Subscription Rights Expiring"), so
`no_form25` and a fallback guess. WFT's Form 25 came 11 months after the suspension; the 8-K 3.01 gave a compliance
failure 570 and a guessed date.

Rule: (a) For a security with no Form 25 in its span, search every Form 25 of its issuer from first sighting minus a
longer lookback (TXU: the 2007 Form 25 precedes the stale-snapshot first sighting) to today and match by class/CUSIP/
ticker; refuse only when it matches a sibling alive then. (b) Match a multi-class 25-NSE to each class (SPWRA: one
delisting per matched class, a continuation to SPWR). (c) A rights class is an `expiration` ending (TMUSR). (d) Map
"abnormally low price" to drop reason `price` (550/552) (WFT).

Where: `delistings.DelistingFinder.find` (the candidate loop: `alive` check with `_alive_at`, `early`, `_early_group`),
constants `SIBLING_ALIVE_AFTER_DAYS`, `FORM25_LOOKBACK_DAYS`, `IGNORE_AFTER_DEFINITIVE_DAYS`;
`form25.match_securities`/`class_kind`/`class_letters`; the drop-reason map in `exit_kind`.

Guard: a late Form 25 must match by class and by absence of a live sibling. Must NOT attach a Form 25 for another class
of the same issuer (APA), nor a transfer Form 25 that continued the same security (WW 2018: no clip).

Cases: XMSR (BBG000C070N2, continued_filings_guess; 25-NSE 2008-07-29), SOV (BBG000JXRXK2, continued_filings_guess;
25-NSE 2009-02-02), SPWRA (CIK867773-COMMON, continued_filings_guess; 25-NSE 2011-11-16), MWW (BBG000DGZ1B6,
continued_filings_guess; 2016 25-NSE under the same CIK), TXU (BBG000BVW841, continued_filings_guess; 2007 Form 25
before the first sighting), WFT (BBG000DY8ZS4, late_form25), TMUSR (BBG00VNLZL95, no_last_trade_print; rights class
25-NSE 2020-07-27).

Effect: `no_form25`, `delist_date_approx`, `continued_filings_rule` clear; real ending and a notice-based last trade
(XMSR 2008-07-28, SOV 2009-01-29, TXU 2007-10-10, TMUSR 2020-07-27, MWW 2016-10-31); stock rule for XMSR and SOV; SPWRA
a continuation to SPWR; WFT drop reason `price`.

Risks: the mechanism is my inference from `_alive_at` and the loop; the reports only say "not found or not matched" (the
XMSR report guesses the 25-NSE form type, SOV's reason is not shown). Replay XMSR, SOV, TXU before building. Widening
the reach invites mismatches (shared tickers, T4). Decisions: 9 (SPWRA), 11 (WFT OTC), 12.

## T9. A found Form 25 is overridden by the continued-filings rule (1 case)

Pattern: NTY: the Form 25 is found, but later filings by the private issuer (a 2011 S-4) made the continued-filings
rule label it a 304 transfer before the cash-merger evidence (8-K 5.07, the Form 25 text) was used
(`continued_filings_rule`, `successor_unknown`).

Rule: with a matched Form 25 in hand, merger evidence in the Form 25 text/8-K outranks the continued-filings rule.
Branch 1 "still trading after the end" must come from the security's own prints, not issuer filings; a Form 25 notice
that states a merger and a cash price is a merger signal.

Where: `classifier._detect_continued_filings` / `end_of_era.resolve` ordering, `end_of_era.signals`.
Guard: 304 applies only when the Form 25's class is sighted after the effective date. Case: NTY (BBG000BPTDN6,
continued_filings_guess). Effect: 304 becomes merger 233 with cash 55.00 USD; `continued_filings_rule` and
`successor_unknown` clear. Risk: exchange transfers by a still-public issuer. Decisions: none.

---

## No library change
None. Every case has a library-side fix. The `library_wrong=False` cases (about 20) still need a change to publish a date
or currency (T1, T2, T4: WEN). Two caller-side items ride inside cases and need no library change: stale-snapshot
observations dated after the delisting (`seeds_outside_history`, `observed_after_delisting`) in CDWC, DADE, IFIN, AQNT,
CHAP, CKFR, TXU, XMSR, MWW, which stay listed seeds only; and APA's `issuer_history_bug` (CIK 1841666 on the old line),
a separate issuer theme.

## Does not fit
None.

## Count
T1 8 + T2 17 + T3 5 + T4 3 + T5 4 + T6 12 + T7 4 + T8 7 + T9 1 = 61. By file: no_last_trade_print 28 (T1 8, T2 17,
T3 WM and DBD, T8 TMUSR), continued_filings_guess 22 (T6 12, T7 4, T8 5, T9 1), last_trade_date_misread 4 (T3 PMI, MNK,
TMHC; T5 TDW), reused_ticker_data 3 (T4), resolver_no_bankruptcy_branch 3 (T5), late_form25 1 (T8 WFT).

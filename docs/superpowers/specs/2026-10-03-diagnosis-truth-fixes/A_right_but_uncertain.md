# Fix themes A: library_right_but_uncertain (89 cases)

Reason codes come from output/uncertain.csv (kind=ending for every case). Code sites:
`verdict.py` `_ending_reasons` (~136-175) and `_security_verdicts` (seeds_outside_history, ticker_overlap);
`end_of_era.py` `resolve` (the 5.01 / 2.01 relabel; tag `lifecycle.RESOLVED_FROM_CONTINUED_FILINGS`);
`classifier.py` (~597, sets `resolved_by_current_ticker_map` when `resolution.source == "company_tickers"`);
`payout_gate.py` `reconcile`; `handoffs.py` `decide_handoff` ("timing:cik"); `payout_rule.py` (`cash_currency` always blank).

Cross-cutting note (not a theme). Most reports also say `cash_currency` is blank. That is a published-field gap
(payout_rule.py: "always blank: no source records one"), not an uncertain reason, so it never keeps a row in uncertain.csv.
A rule "a cash leg whose filing text states US$/dollars publishes USD" is a separate small contract change; listed once here, not per theme.
It needs a ruling (reference.md: payout rule fields, schema v2, currency blank).

---

## Theme 1. Merger relabelled by the end-of-era resolver although the Form 25 path is complete (`resolved_from_continued_filings`)

Pattern. The finder's Form 25 path did not own the row (or the continued-filings rule fired first). `end_of_era.resolve` turned the
ending into a merger from the 8-K 5.01 branch (or 2.01 plus merger filing/Form 25) and appended "; the registrant kept filing after
it" to the reason. `verdict._ending_reasons` treats that suffix as a standing doubt (`resolved_from_continued_filings`) even when the
row also has a Form 25-NSE, an EX-99.25 notice date and a gate-passed payout. The registrant keeps filing only because debt or
preferred stays registered (PRE, DPL, Q, CCU, ACF, AT, CEN, JNC, SVM, AV, ...).

General rule. Count the resolver's merger ending as corroborated, and drop `resolved_from_continued_filings` from the verdict, when ALL hold:
(a) a Form 25 (25-NSE/25) of this security is on the row and its class matched (`form25.match_security`);
(b) an 8-K 2.01 or 5.01 of the same issuer lies in the window the resolver already reads;
(c) the last-trade date comes from an exchange source or EX-99.25 notice (`ex99_notice`, `midas`, `nasdaq_halt`, `8k_301`) or the Form 25 effective date.
The better root fix is upstream: when a matched Form 25 exists, let the finder's Form 25 path own the row (CCU, DISH, HNZ, SUG, PNY, POM,
STOR, PL: "why did the Form 25 path not own it?") and use `resolve` only to settle the code, keeping the branch in `evidence["end_of_era"]`,
so the reason string never gets the suffix. Two steps: (1) classifier/finder keep the Form 25-driven reason; (2) `verdict._ending_reasons`
emits `resolved_from_continued_filings` only when no Form 25 is on the row.

Where. `delistings.py` `DelistingFinder.find` (Form 25 group into classify_event), `classifier.py` `classify_event` (continued-filings branch
calling `end_of_era.resolve`), `end_of_era.py` `resolve`, `verdict.py` `_ending_reasons` (~146), `lifecycle.RESOLVED_FROM_CONTINUED_FILINGS`.

Guard. Do not clear when no Form 25 exists (theme 2), when the Form 25 is a secondary-listing withdrawal (`listing_status.withdrawal_kind`),
or when the resolver branch was 3.01/deficiency (a compliance_failure relabel). Keep `last_trade_not_exchange_print` (separate reason) where
the last trade is only a sighting. No case in this group must be left unchanged by this rule. SVM is marked library_wrong=True/skeptic upheld
but its report says "mostly did not"; its seeds reason (theme 5) is unaffected.

Cases (34). Single-reason (26):
BBG000BBBP59_2016-03-28 PRE; BBG000BCKC47_2016-07-11 GAS; BBG000BDKN87_2010-02-26 BNI; BBG000BF8BH2_2008-08-10 CCU;
BBG000BFVKZ6_2019-02-25 AHL; BBG000BHBGN6_2022-12-03 CLR; BBG000BHBK84_2017-09-11 DOW; BBG000BHCDF1_2011-12-08 DPL;
BBG000BJ27C4_2012-07-15 PGN; BBG000BJCFP1_2013-03-11 JEF; BBG000BL9439_2013-07-28 HNZ; BBG000BMZ7P7_2021-12-24 KSU;
BBG000BRF689_2016-10-14 PNY; BBG000BTMDX4_2012-04-06 SUG; BBG000C2YHG9_2024-01-08 DISH; BBG000C3JJC4_2015-02-12 PL;
BBG000C4Y9D6_2011-04-11 Q; BBG000CXLZ20_2010-10-11 ACF; BBG000DQX1D4_2016-04-03 POM; BBG000PJ88D0_2015-08-27 GTI;
BBG000QDST26_2016-10-24 ITC; BBG000V31J96_2018-03-24 CPN; BBG00265T6Q4_2023-02-13 STOR; BBG000HZFZX3_2017-11-11 LVLT;
BBG0077WYXF0_2016-07-11 CPGX; BBG00CW2JCN1_2022-01-13 ATH.
With a second reason (handled in the named theme): BBG000KZCJJ4_2020-04-09 AYR (+issuer map, theme 3); BBG000C7B169_2011-07-31 WMG
(+issuer map, theme 3; last trade source nasdaq_halt for an NYSE name, date agrees with the Form 25 notice); BBG000GYLKX3_2013-10-07 SFD
(+issuer map, theme 3); BBG000CS7CB8_2007-11-25 JNC (+seeds, theme 5); CIK1052045-COMMON_2007-08-04 SVM (+seeds, theme 5);
CIK1116521-COMMON_2007-11-05 AV (+seeds, theme 5); CIK1124887-COMMON_2007-11-23 CEN (+seeds, theme 5);
CIK65873-COMMON_2007-11-30 AT (+seeds, theme 5; also payout_gate_failed:481.37, see risks).

Effect. Removes `resolved_from_continued_filings` from uncertain.csv: the 26 single-reason rows leave the file; the 8 with a second reason stay
until that theme lands. Reason text reads as a Form 25 merger. No value fields change.

Risks. (1) The suffix is the library's only marker that the registrant kept filing; keep it in `evidence["end_of_era"]` or an info flag.
(2) A Form 25 for one listing's withdrawal must not qualify (existing listing_status check). (3) AT: the extractor read the Series D preferred
amount (481.37) next to 71.50; the published 71.50 is right; do not widen the rule to hide a gate failure; the extractor should prefer the
common-share amount (separate fix). (4) Several rows (HNZ, DISH, PRA, MCW, SFD, LVLT, CPGX, POM, STOR, PNY, PL) have delist_date = Form 25
filing + 10 d or the Form 15 date, and HNZ/PPP the later re-filed Form 25; that is a delist-date definition question, not an uncertain reason.

Spec decisions. Decision 12 untouched. Needs a ruling: is "2.01/5.01 plus Form 25 plus notice date" a confirmed ending (verdict rule)?

---

## Theme 2. Continuation or rename with no Form 25 that a successor filing already confirms

Pattern. No Form 25 exists (holdco reorganization, tracking-stock recap, rename), so `continued_filings_rule` fires, sometimes relabelled from an
8-K12B (`resolved_from_continued_filings`), the last trade is unconfirmed, and the issuer came from today's map (`issuer_from_todays_ticker_map`).
Successor, 1:1 terms and CUSIP switch are right. No code accepts an 8-K12B/8-K12G3 (or a 5.03 same-CIK name change) as the confirming filing.

General rule. A continuation is confirmed (no `continued_filings_rule`/`resolved_from_continued_filings`) when a successor registration (8-K12B,
8-K12G3, or a 5.03 name-change 8-K on the same CIK) is in the window and names the old class, AND the handoff/successor stage
(`handoffs.decide_handoff`, `successors.successor_from_8k12b`) linked a successor that starts within days with a CUSIP switch. Then date the
old line's end the day before the successor's first sighting (fixes the one-day overlaps in FNF/NRF/SIRI/CSAL) and take the effective date
for the last trade where the filing states it. The finder may read the 8-K12B as the confirming filing in place of a missing Form 25.

Where. `end_of_era.py` `resolve` (successor branch), `handoffs.py` `own_continuation_filing`/`decide_handoff`, `successors.py`
`successor_from_8k12b`, `verdict.py` `_ending_reasons`, `lifecycle.CONTINUED_FILINGS`.

Guard. A filing is required: a same-ticker/same-CIK pair with no successor registration stays timing-only (theme 7). Do not apply when the old
issuer carries on in another line (existing `decide_handoff` rule). A continued-filings ending with no successor filing stays uncertain.

Cases (7): BBG000BT0093_2024-09-10 SIRI (+issuer map; 1-for-10 successor reorg); BBG000Q5RW63_2014-07-01 NRF (8-K12B; delist_date is the 8-K12B
filing date, effective 2014-06-30); BBG007SV7NV3_2017-10-03 BKFS (8-K12B + CUSIP switch); BBG00W5FS571_2025-01-09 BEPC (Form 25 matched, 304 via
8-K12B; +issuer map); BBG000BMB7R1_2016-05-17 ITT (uncertain.csv: issuer map only; no_form25, delist_date_approx flags); BBG000JBSJZ4_2014-07-01
FNF (continued_filings_rule + issuer map; tracking-stock recap); CIK1620280-COMMON_2017-02-28 CSAL (continued_filings_rule; same-CIK 5.03 rename).

Effect. Clears `continued_filings_rule`, `resolved_from_continued_filings` and where the filing states it the unconfirmed last trade. SIRI, BEPC, ITT,
FNF also need theme 3. Continuation rows already carry no value, so value columns are unchanged.

Risks. FNF carries a side distribution (FNFV 0.3333) the contract does not carry; clearing the doubt must not hide it. CSAL is a rename: confirm the
contract treats it as an ending with a successor at all.

Spec decisions. Decision 9 (continuation/same-ticker rules) and decision 12 (last_trade only from an exchange print). Needs a ruling: is an
8-K12B naming the successor enough without a last-trade print?

---

## Theme 3. Issuer from today's company_tickers.json although the Form 25/8-K filer CIK confirms it (`issuer_from_todays_ticker_map`)

Pattern. `classifier.py` flags `resolved_by_current_ticker_map` whenever `resolution.source == "company_tickers"`; the verdict turns that into
`issuer_from_todays_ticker_map`. The row's own Form 25 and 8-K are filed under that same CIK, so it is independently proven; the flag only reflects
how the resolver found it. Recent (2026) rows always take this path.

General rule. Drop the reason when the issuer CIK equals the filer CIK of (a) the Form 25 that matched this security or (b) an 8-K/Form 15 in the
delisting window, and the resolver's `since=` check passed (the company had filed by the era's first sighting). Implement as an evidence test next
to `ticker_evidence.py` (`evidence_for`, decision 1's CIK/ticker evidence, which already reads a CIK's own filings), run at stage 10e/10f.

Where. `verdict.py` `_ending_reasons` (~142), `ticker_evidence.py`, `classifier.py` (~597; keep the flag on the row),
`review_triage.CATALOG["resolved_by_current_ticker_map"]` (stays as is).

Guard. Keep the doubt where there is no Form 25 of that CIK (theme 2 rows until their filing evidence lands) and for distress endings without one
(`lifecycle.LOW_FLAGS` treats the map as low quality; scorecard R2.6.distress_ticker_map counts it). Require the Form 25 passed `form25.match_security`
and the observation name agrees, so a sponsor-family Form 25 cannot launder a wrong issuer.

Cases (12 pure, all mergers with a Form 25): BBG000BP0KQ8_2026-08-14 EA; BBG000BWMX63_2026-08-30 WBS; BBG000FBWYH0_2026-07-06 PRA;
BBG000P1K2X6_2026-07-26 GTLS; BBG006GNRZ83_2026-08-30 LBRDA; BBG006GNSZW5_2026-08-30 LBRDK; BBG007KGRPY4_2026-05-24 APLS (CVR leg unpublished,
separate); BBG008417VN4_2026-08-01 NSA; BBG00GSNPM07_2026-07-11 JHG; BBG011FS2K38_2026-05-29 MCW; BBG012BV9SK0_2026-07-17 OLPX;
BBG014QJ5BV6_2026-05-25 EHAB.
Overlap, counted elsewhere: AYR, WMG, SFD (theme 1); SIRI, BEPC, ITT, FNF (theme 2); BLD (theme 4). LBRDA/LBRDK also have a halt-sourced last trade
(an exchange source, fine).

Effect. Removes `issuer_from_todays_ticker_map`; the 12 rows leave uncertain.csv and the overlap rows lose one reason.

Risks. A coincident CIK from a wrongly matched Form 25 could launder a bad issuer (guard above). PRA/MCW: delist_date is the Form 15 date, not the
Form 25 date (separate definition question).

Spec decisions. Decision 1 (ticker evidence) is the closest; extending it to company_tickers issuers needs a ruling that "filer of the matched Form 25"
counts as evidence.

---

## Theme 4. Assumed par after a failed gate whose terms are right (`assumed_par_after_failed_gate`)

Pattern. Terms (LLM or regex) match the filing, but `payout_gate.reconcile` compares them against a stale fails-based last close (`ftd_close_prior:n`,
`ftd_close_lagged`), an acquirer price that starts only on completion (`fail_sanity`/`no_acq_price` for stock legs), a pre-closing special dividend
(KRFT) or a per-ADS leg (AVP). The gate drops the terms, `dlret_method=assumed_par`, and the verdict says `assumed_par_after_failed_gate` (decision 4). The
contract still publishes the value rule and terms (schema 2), so the caller can price them.

General rule. A gate failure whose only cause is the price side is not a doubt about the terms. In `payout_gate.reconcile`:
(1) when the last close carries `ftd_close_prior:n` with n above a cap (about 3 trading days) or `ftd_close_lagged`, compare against the nearest fresh close
(last fails row inside the lagged window), or widen the tolerance by the close's age, instead of dropping the terms (FRX, HEW, MRD, HTS, PNRA);
(2) when the stock leg's acquirer price is missing or begins on completion, accept terms on the filing's evidence (8-K/Form 25 states ratio and ticker) and
publish `terms_gate=unpriced`, not `failed`, with no assumed par (BMS, IHS, JNS, PX, URS);
(3) include a stated pre-closing special dividend or per-ADS ratio in the terminal value used by the sanity test (KRFT, AVP).
`verdict` drops `assumed_par_after_failed_gate` only for terms accepted or unpriced-by-design; a sanity failure against a FRESH close keeps it.

Where. `payout_gate.py` `reconcile` and the drop at ~184 (`flag_terms_gate_drop`), `pipeline.py` `_last_trade_closes` (`ftd_close_prior`, ~655),
`ftd.py` `close_age`/`close_after`, `payout_rule.py` (`terms_gate`), `verdict.py` `_ending_reasons` (~152, GATE_FAILED), `dlret.py`, `review_triage.CATALOG`.

Guard. Do NOT change a row where terms disagree with the filing (none here) or a fresh close contradicts the terms (the gate is doing its job). Publish no value: the fill
stays 0.0 or `unpriced` until the caller prices it (price_requests.csv). The terms source must be a filing the library read, not a csv override (those
already bypass the gate).

Cases (14): BBG000BDHNB7_2019-06-21 BMS; BBG000BGMX22_2010-10-14 HEW; BBG000BJVZF7_2014-07-12 FRX (MIDAS close 97.46 available); BBG000BYD720_2017-06-09 JNS;
BBG000C3HNW5_2014-10-30 URS; BBG000CGQ6M4_2018-11-10 PX; BBG000FVQ434_2016-07-23 IHS; BBG000G6BN50_2017-07-28 PNRA (payout_gate_failed:315, close 198.17);
BBG000PTXBV3_2016-07-22 HTS (also last_trade_date_text_conflict); BBG001YMS0B8_2015-07-12 KRFT; BBG0069FL5L5_2016-09-26 MRD;
BBG0077VS2C0_2026-07-11 BLD (+issuer map, theme 3); CIK230463-COMMON_2008-02-07 PPP (+seeds, theme 5); BBG000BCNYT9_2020-01-16 AVP
(+resolved_from_continued_filings, theme 1).

Effect. Removes `assumed_par_after_failed_gate` (HTS keeps `last_trade_date_text_conflict`; BLD, AVP, PPP keep their second reason until themes 1/3/5 land).
Contract: `terms_gate` becomes ok/unpriced; `dlret_fill` may stay 0.0 until priced. Scorecard R2.4 assumed-par count drops (raise-floor).

Risks. This theme most easily hides a real doubt: decision 4 makes a failed gate uncertain on purpose. Mitigations: publish as `unpriced` so the caller
must price, keep `fail_sanity` against a fresh close, require the filing-read source. The staleness cap is a policy choice. KRFT's special dividend and AVP's
per-ADS ratio are each separate sub-rules.

Spec decisions. Decision 4 (assumed par after a failed payout/LLM/terms gate is uncertain): needs a ruling that a stale-close or missing-acquirer-price
failure is "unpriced", not "failed". Decision 12 untouched.

---

## Theme 5. Stale caller seeds after a confirmed ending make the security uncertain (`security_uncertain` / `seeds_outside_history`)

Pattern. The caller's snapshots kept the ticker after the merger (one observation from 2008-01-16 on for 2007 mergers). `_security_verdicts` appends
`seeds_outside_history:1 from 2008-01-16`; `_ending_reasons` adds `security_uncertain` to the ending. `observation_map` already marks those seeds
`after_delisting` / `observed_after_delisting`. Nothing in the library's evidence is doubtful: the ending is filing-backed.

General rule. In `_security_verdicts`, do not count an introduction as outside the history when its observation_map status is `after_delisting` and the
security's last ending is confirmed (Form 25 or merger, an exchange print or notice last trade, no `last_trade_date_unconfirmed`). Those seeds keep their
own seed verdict (listed as stale), but stop making the security and ending uncertain. Keep `seeds_outside_history` for any other status (`unresolved`,
`conflict`, `backfilled_ticker`) and when the delisting is unconfirmed (`after_unconfirmed_delisting`, whose purpose is the caller keeping and checking).

Where. `verdict.py` `_security_verdicts` (~128-131, `outside`), `history.observation_map_rows` (status values), `verdict.is_introduction`/`_covered`.

Guard. Must NOT apply to an unconfirmed ending or a continuation. Every ending in this group is a confirmed merger with a Form 25 and a notice or print date.

Cases (12 pure): BBG000BDLLR9_2007-11-05 BOL; BBG000BH5K72_2007-12-28 DJ (also ftd_close_prior:5, info); BBG000BNXLK1_2007-07-12 MEL (ex99_notice last trade);
BBG000BV3594_2007-12-06 TEK; BBG000BV52H0_2007-09-07 KSE; BBG000CG0HP5_2008-01-05 HCR; CIK1038914-COMMON_2007-12-23 GSF; CIK1156826-COMMON_2007-10-20 ASN;
CIK47580-COMMON_2007-11-04 HLT (placeholder sec_id); CIK718482-COMMON_2007-10-11 AGE; CIK737874-COMMON_2007-10-11 LI; CIK845752-COMMON_2007-08-11 AH.
Overlap, counted elsewhere: JNC, SVM, AV, CEN, AT (theme 1); PPP (theme 4).

Effect. `security_uncertain` leaves uncertain.csv for the 12 pure rows (they leave the file) and clears the seeds part for the 6 overlap rows. The seed rows
stay in uncertain.csv as stale-seed listings, the right place for the caller to see them. No value change.

Risks. This is the case where a real doubt (the caller sees the ticker after the end) is hidden by a rule; justified because the seed is the caller's stale data
and observation_map already says so. Needs "confirmed" defined: an `ex99_notice` last trade is not an exchange print under decision 12, but the Form 25
effective date backs it.

Spec decisions. Decision 12; the seeds coverage rule (verdict.py note in CLAUDE.md: an era's first sighting is a seed; later sightings outside the history are
listed seeds only). Needs a ruling: do stale after_delisting seeds make the security uncertain, or only the seed?

---

## Theme 6. Same-issuer holdco continuation: `no_evidence_default` and `ticker_overlap` against its own successor or a duplicate placeholder

Pattern. GOOGL/GOOG: the Form 25 path ended in the generic `exchange_transfer` 304 (`no_evidence_default`), then the handoff stage linked the continuation by an
8-K12B (`handoff_continuation`). Old and new line share a ticker, and the Class C security (GOOG) collides with the Class A line in the overlap test although
they are linked by the same holdco event. LVNTA: a duplicate placeholder (CIK1355096-COMMON) shares the ticker with the FIGI security.

General rule. (a) Clear `no_evidence_default` when `handoff_continuation` holds with an 8-K12B/8-K12G3 (the stage-9c handoff confirms the successor). (b) In
`_security_verdicts`, treat two securities as linked (no overlap) when they share the issuer CIK and one is the other's `successor_sec_id`, or both are share
classes of one 8-K12B event. (c) LVNTA: hide a placeholder from the overlap test when a FIGI security carries the same issuer CIK and class
(`security_master.superseded_placeholders` already marks these; extend). Cosmetic: the GOOGL/GOOG reason text says 2015-10-05 (the next session) where the last trade
is 2015-10-02: fix the string.

Where. `verdict.py` `_security_verdicts` (overlaps/linked), `handoffs.py` `apply_handoffs`, `classifier.py` (`no_evidence_default`), `security_master.py`
`superseded_placeholders`.

Guard. (b) applies only for the same issuer CIK or a successor link; a genuine two-issuer overlap (DTV, TGNA below) stays uncertain.

Cases (3): BBG000BHSKN9_2015-10-12 GOOGL (security_uncertain via ticker_overlap:GOOG; no_evidence_default); BBG002W96FT9_2015-10-12 GOOG (same);
BBG0038K9G41_2018-03-19 LVNTA (security_uncertain + resolved_from_continued_filings; the latter follows theme 1's rule if a Form 25 exists).

Effect. Clears `no_evidence_default` and `security_uncertain` for GOOGL and GOOG; LVNTA loses the overlap and with theme 1 its resolved reason. Continuation values unchanged.

Risks. Merging a placeholder into a FIGI security changes a sec_id (CLAUDE.md: placeholders must stay stable between runs); record it in `contract/id_changes.csv`.
The share-class test must require the same issuer and event, or it would hide a real collision.

Spec decisions. Decision 9 (same-ticker continuation) and decision 10 (id_changes); LVNTA's merge needs a ruling.

---

## Theme 7. Continuation linked by timing and same CIK only (`continuation_by_timing_only`) where an 8-K Item 3.03 reclassification states the exchange

Pattern. Tracking-stock reclassifications (Liberty SiriusXM and Formula One lines, 2023) and the TEAM domestication keep the CIK and ticker and get a new CUSIP.
`handoffs.decide_handoff` has no filing branch for an 8-K Item 3.03 (reclassification), an 8-A12B for the new class, or an Introductory Note naming a
scheme/domestication, so it returns `"timing:cik"` and the verdict emits `continuation_by_timing_only`; the last trade is only a last sighting (blank in the contract).

General rule. Extend `own_continuation_filing`/`continuation_filing` so a same-CIK 8-K with Item 3.03 whose date equals the Form 25 effective date, plus an
8-A12B for the new class (or, for TEAM, an Introductory Note on the same CIK naming the scheme), counts as a filing-backed continuation (reason `filing:3.03`
not `timing:cik`). Where an exchange source exists, date the old line's last trade from that effective date (reports suggest 2023-08-03 and 2022-09-30) and tighten
the successor start by a day (`_date_from_notices`, stage 9c).

Where. `handoffs.py` `own_continuation_filing`, `continuation_filing`, `decide_handoff` (~230), `verdict.py` (`"(timing:cik)" in row["reason"]`),
`pipeline._date_from_notices`.

Guard. The filing must be on the SAME CIK and state the exchange/reclassification; a link with no filing stays timing-only. The rule changes how the link is
evidenced; it does not decide whether a reclassification with a side distribution (LLYVA/LLYVK) is a continuation (open ruling in the FWON/LSXM reports).

Cases (5): BBG00BDQ1H13_2022-10-10 TEAM; BBG00BFHD827_2023-08-13 LSXMA; BBG00BFHD9S7_2023-08-13 LSXMK; BBG00BFHDCV6_2023-08-13 FWONA; BBG00BFHDFR4_2023-08-13 FWONK.

Effect. `continuation_by_timing_only` leaves uncertain.csv for the 5 rows (they leave the file). Contract: last_trade_date may become published where a notice states it.

Risks. A 3.03 8-K can describe an unrelated charter change; the Form 25 effective-date match and the new-class 8-A12B limit that. Side distributions are not carried by
the contract; decide before declaring such a continuation "confirmed" that no value is owed.

Spec decisions. Decision 9 (continuation by timing vs filing) and decision 12; ruling needed on side-distribution continuations.

---

## No library change

Cases whose report says the row is right and the doubt is genuine (unverified; no rule above should hide it):
- BBG000FL1TC8_2015-08-03 DTV: `ticker_overlap:DTV` with CIK 944868 (old DIRECTV Group), whose observations under DTV run to 2009-11-29 while this security starts
  2009-11-23. The report did not verify a stale snapshot. A different-issuer overlap, so theme 6's rule does not touch it.
- BBG000BK5DP1_2026-03-30 TGNA: `ticker_overlap:GCI` (old Gannett's 2007-2015 line on the same FIGI; whether a second security should own GCI is unchecked). An identity
  question to investigate separately.
(The blank `cash_currency`, the `ftd_close_*` info flags and cosmetic reason text noted on many cases are not uncertain reasons and need no row change.)

## Does not fit

None.

---

## Count

Theme 1: 34; Theme 2: 7; Theme 3: 12; Theme 4: 14; Theme 5: 12; Theme 6: 3; Theme 7: 5; No library change: 2; Does not fit: 0.
34 + 7 + 12 + 14 + 12 + 3 + 5 + 2 + 0 = 89. Each case is counted once, under its primary theme; cases with a second reason are named in the other theme as "overlap, counted elsewhere" only.

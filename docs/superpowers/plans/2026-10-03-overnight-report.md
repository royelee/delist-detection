# Overnight report, 2026-10-02 to 2026-10-03

The operator asked for the rest of the reset plans to be worked overnight, autonomously. Each plan was written,
executed subagent-driven (Sonnet for every dispatch), accepted with a network rebuild, and reviewed. A ruling stood
in for each decision a person would have made. Every ruling is listed below, with what it costs if it is wrong.
Nothing was merged or pushed. The branch is `worktree-reset-1-scorecard`.

## What was done

| Plan | Acceptance | What changed |
| --- | --- | --- |
| reset-4a, end-of-era resolver (first step) | 7509cf5 | Endings from the continued-filings rule are resolved from EDGAR evidence. Left-view lifecycles fall from 120 to 63, and 7 golden known_wrong cases now pass. |
| reset-4b, securities dead before their first sighting | 2b7ae6d, 214d6b2 | 31 securities take their 2004–2007 fails history. No-interval securities fall from 32 to 1. Masked fails symbols ("**********", Aug–Dec 2007) are no longer ticker sightings. |
| reset-4c, assumed par after any failed gate | bef8a4d | Assumed par after a failed LLM or terms gate is uncertain, as it already was after a failed payout gate (decision 4). 32 endings become uncertain, and confirmed-but-wrong falls from 44 to 40. |
| reset-4e, exchange-print dates the caches held | f7f36e7 | 10 handoff continuations take their Form 25 notice date (new stage 9c). 8-K item 3.01 reads four more "suspended before the open" wordings. 17 contract endings gain a published last trade date. |
| reset-4f, OTC prints requested and valued | 4e0dbee | price_requests.csv asks for 51 `otc_print` prices. An answered print values the drop (DLRET = print / last close − 1), including in the firm-month correction. |
| reset-4a2, holdco continuations (second step of 4a) | a059814 | The successor's own 8-K12B/8-K12G3 settles a 1:1 holding-company continuation (decision 9). CI 2018, XRX 2019, AVGO 2016 and 2018, QDEL 2022 and BG 2023 are no longer merger endings. |
| reset-4d, distress certainty and liquidation values | bb7334a (roadmap note) | Research only, not planned (see the decisions below). |

The suite went from 1648 passed, 24 xfailed (10119b1) to 1711 passed, 17 xfailed. There are 40 commits in all.

### Scorecard, start of night to now

- Coverage: securities 0.885 to 0.922, tickers 0.885 to 0.919.
- Lifecycles: left_view 120 to 63, no_interval 32 to 1. ended_incomplete rose from 52 to 60, because dead securities now have intervals.
- Golden cases: pass 27 to 34, known_wrong 24 to 17.
- Audit:
  - random errors 11 to 9, with the upper 95% bound from 0.177 to 0.153
  - left_view errors 114 to 76
  - blank_no_value errors 11 to 6
  - assumed_par errors 17 to 15
  - distress errors 13 to 12
  - continuation errors 25 to 28 (worse; see the floor entries below)
- Confirmed but wrong: 45 to 42.
- Endings resting on the continued-filings rule: 136 to 51.
- Missing last trade dates: 43 to 40.
- Blank DLRET in the window: 55 to 51.
- Uncertain endings: 268 to 288. These are honest additions: relabelled endings and assumed par after a failed gate.
- L2.high_share: 0.781 to 0.754.
- Assumed par: 62 to 77. The resolver turned continued-filings transfers into mergers that have no value yet.

Every floor entry that went down was lowered by hand, and the commit that lowered it gives the reason.

## Decisions waiting for the operator

1. **Branch integration.** Merge `worktree-reset-1-scorecard` into main locally, push it and open a PR, or keep it as it is.
2. **15 still-trading fallback endings (reset-4a2 research rule 1).** These are CWTR, ERA, DF, FMD, EGL, WIN, MNI, FTR, SVU, TERP, RAD, LPI, GOCO, VRM and NYCB. They are no-Form-25 fallback endings, but MIDAS shows the ticker trading for 20 or more days over 2 or more months after the end, and the issuer kept filing 10-K/10-Q.
   - The rule would un-end them and flip golden DF and MNI from known_wrong to right.
   - It reverses CLAUDE.md's invariant that an unconfirmed fallback day is not second-guessed (Monster Worldwide, SunPower), and it raises left_view.
   - Not built.
3. **reset-4d's payment source.** Decision 3 values solvent liquidations from their payments, but no payment is cached. The options are to fetch 8-K 8.01 liquidating distributions (a new extractor, with network and LLM cost) or to take them from the caller's `--recoveries`. The relabels the research found (BMET, TSP, FMD, GOCO, YRCW, PDLI; IMB, CNB and GNC to bankruptcy; 7 plan share swaps; 4 worthless) are listed in the roadmap.
4. **Audit row `blank_no_value:BBG009XV39D8` (AVGO 2016-02-01) in data/accuracy_audit.csv.** It asks for the last trade date of a final ending. The output now continues Broadcom Ltd into Broadcom Inc, which is what the row's own note says happened. Either clear the row's `last_trade_date` or have the judge read it on the continuation. Until then it counts as confirmed-but-wrong.
5. **GOOG 2015-10-05.** Google Inc's range now ends on its true last day, 2015-10-02. Alphabet's range starts at its first fails-row sighting, 2015-10-06, one trading day late. A successor's range could start on the trading day after its predecessor's last trade. That is a follow-up rule.
6. **Still parked from reset-4a:**
   - SC TO-I, 425 and S-4 in the merger forms
   - branch 4's Form 25 half
   - branch 3 trusting a 5.01 with no issuer-seen-after check
   - LLYVA and LLYVK (Liberty Live, no 8-K12B)
   - successor lines not in the run (ODP, UNIT)
   - the WBD continuation
7. **Not started:**
   - reset-4b's later steps: 9 share-class contradictions (AA, ALEX, CB, CHK, FOX, FOXA, GM, IR, LBTYA), 12 FIGI rows with no CIK, ERA and 99 placeholders. These change sec_ids that qlib_practice keys on.
   - reset-3q (the qlib_practice repo)
   - the Cleanup removals, which wait for reset-3q

## Rulings, plan by plan

Each ruling reads "what was decided — why — what it costs if wrong". They are copied from the plans' scratch
ledgers, which are deleted after this report; this file is the record. Rulings made before tonight (reset-1 to
reset-3) are in those plans' commits.

</content>
## Overnight queue


1. reset-4a rests on decisions 9 (adopted 2026-10-02 with reset-3) and 11; decision 11 adopted as proposed (a move to OTC is an ending, CRSP 520, dropped/moved_otc; its value waits for reset-4f) — the operator asked for autonomous work and the spec proposes this answer — cost if wrong: the resolver's OTC branch is relabelled later
2. reset-4f (OTC prints requested and valued from answers) runs before reset-4d — it is offline-buildable from the spec, while reset-4d's values need a payment source the cache lacks and its relabels are per-case — cost if wrong: order only
3. reset-4d stops at research tonight and gets a roadmap note instead of a plan — its values need a payment source the cache lacks (fetching liquidating distributions is a new extractor with network and LLM cost the operator has not weighed), its 1.03 relabel fits only 3 of the 6 rows (IMB, CNB, GNC; TMA, SPNV and WFT filed 1.03 after their delisting, so compliance is right) and changes no value, and the other relabels (BMET, FMD, GOCO, YRCW, TSP, PDLI) are per-case — cost if wrong: distress values and labels wait for the operator
4. reset-4a2's first step is the successor's own 8-K12B as the continuation filing (decision 9); rule 1 is NOT built tonight — it reverses CLAUDE.md's invariant that an unconfirmed no-Form-25 fallback day is not second-guessed (Monster Worldwide, SunPower), and it raises left_view, so it is the operator's call — cost if wrong: 15 false endings stay until the operator decides
5. reset-4e's first step takes the two cached groups (16 endings); PHLY's halt window, the event-day sentences and the 52 still-trading endings wait — they need new rules (halt window, a not-an-ending test) with no golden case to check them against tonight — cost if wrong: ~3 more datable endings wait
6. plans run in order 4b → 4c → 4e, then 4d and 4f if time permits (4e before 4d because most blank values wait on a last trade date) — cost if wrong: none beyond order
7. reset-4c's first step is decision 4 only — assumed par after any failed gate (payout, LLM or terms) is uncertain — and reset-4e (missing last trade dates) is planned next, before more value work, because most blank values wait on a last trade date or close; hand-valued terms and price sanity filters wait for 4e and qlib_practice's price answers — cost if wrong: about 20 valuable-now mergers stay unvalued tonight
8. reset-4b's first step covers only the 32 no-interval securities (dead before their first sighting); FOX/FOXA share-class contradictions, no-CIK FIGI rows, ERA, LVNTA, placeholders are later steps — the no-interval group has a clear cached-evidence fix; the others need identity rules that can break golden pass cases — cost if wrong: those groups wait

## reset-4a: end-of-era resolver (first step)


1. every dispatch uses model sonnet (standing instruction) — cost if wrong: weaker reviews.
2. decision 11 adopted as proposed (overnight; recorded in the overnight ledger) — cost if wrong: the OTC branch is relabelled later.
3. endings the resolver relabelled stay uncertain (verdict reason resolved_from_continued_filings, marker lifecycle.RESOLVED_FROM_CONTINUED_FILINGS) until reset-4a2's security-level checks — 12 of 13 newly confirmed-but-wrong rows were wrong before and only lost the continued-filings uncertain reason; a confirmed row must be right (decision 17) — cost if wrong: qlib_practice overrides or drop-lists those endings as it does today
4. accept the 4 continuation regressions (XRX, WBD, LLYVA, LLYVK) and lower A.census.continuation.errors by hand with that reason; V.uncertain_distress and V.uncertain_securities may be lowered by hand if they still drop (new compliance endings and clipped histories are honestly uncertain); the issuer-seen-after guard and holdco handling go to reset-4a2 — net audit +39/-4 — cost if wrong: four continuation lifecycles end early until reset-4a2
5. permit V.uncertain_input_tickers_share 0.109509 -> 0.111762 (and V.uncertain_input_tickers with it) by hand — it follows from the six newly uncertain securities and the relabelled endings kept uncertain (both ruled above) — cost if wrong: about 5 more input tickers listed as uncertain until reset-4a2
6. the final review's three Important rule weaknesses (SC TO-I is a self-tender and 425/S-4 are also acquirer-side forms in MERGER_FILING_FORMS; branch 4's Form 25 half is usually the security's own Form 25, so it reduces to "any 2.01 in the window"; branch 3 trusts a 5.01 with no check that the issuer is not seen afterward) go to reset-4a2, parked — every ending they can mislabel is kept uncertain by the resolved_from_continued_filings marker, and changing the forms now would change the published output and need another rebuild — cost if wrong: some relabelled endings carry a wrong exit kind (still uncertain) until reset-4a2

Deferred minors:

- Task 1: minor (deferred): 25-NSE/A and 8-K12B/A not counted (amendments); no window-edge tests; a time-suffixed date would reach the reason text
- Task 2: minor (deferred): a lost space at classifier.py:584 ("observed =_parse_date"); _deficiency_notice fetches 3.01 texts eagerly on the rule-8 path (cached, plan-mandated); no classifier-level test of the successor branch or of 2.01 with a Form 25 only; one test holds two cases
- Task 3: minor (deferred): the fallback test's all(...) would pass vacuously if classify_event were never reached
- Task 4: minor (deferred): CLAUDE.md says "rule 8" with no numbered list behind it; README and CLAUDE.md give 231 for the merger branches without the 200/233 caveat data-flow.md has
- Task 6: minor (deferred): mid-file import in the test; end_of_era depends on lifecycle for a reason constant (plan-mandated)
- Task 5: minor (deferred): commit message and roadmap do not mention the raised V.audit.confirmed_but_wrong 45->44 and V.uncertain_endings 268->266

## reset-4b: securities dead before their first sighting (first step)


1. every dispatch uses model sonnet (standing instruction) — cost if wrong: weaker reviews.
2. decisions 1 and 7 hold as adopted; this step changes no sec_id or issuer — cost if wrong: none.
3. backfill_cusips calls description_matches(..., empty=False) and a test pins that empty names give no CUSIP — the plan's rule says the description must name the issuer — cost if wrong: a security with no known names gets no backfill
4. a fails row is a ticker sighting only when its symbol has a letter (history.ticker_sightings); fix + test in Task 4's fix round, then rebuild — a masked symbol is not a ticker — cost if wrong: none found
5. is_backfilled's masked-row case stays a deferred minor — masked symbols occur only 2007-08..2007-12 in the cached files (1643, 558, 89, 49, 2 rows by month), and observations start 2008-01-16, so a ±30-day window can meet at most the 2 December rows (controller count, masked.py) — cost if wrong: one observation could read backfilled_ticker
6. the reviewer's co-author minor is dismissed — the commit trailers follow this session's attribution instruction (Claude Opus 5.5) — cost if wrong: none
7. 5b uses the last real ending (max), still required before the first observation — a security with a real ending after its first sighting was alive when seen, so it did not die before the fails window — cost if wrong: a security whose later ending is spurious loses its backfill (the rebuild shows whether the 31 shrink)
8. 5b decides eligibility for every security before loading any rows — the result must not depend on sec_id order — cost if wrong: none
9. 5b drops a found CUSIP another security already holds — a shared CUSIP would bring the other security's later rows into its ticker sightings — cost if wrong: a true shared CUSIP is lost to the dead security
10. finding 4 (meter), 6 (tests) and 7 (docs) go in the fix wave; finding 5 (an info review flag for backfilled securities) is deferred — a new flag changes review_summary.csv and needs a catalog entry, and the log line records the count — cost if wrong: a backfilled security is not visible in review.csv

Deferred minors:

- Task 1: minor (deferred): the docstring does not say tickers need the bare class spelling; no class-ticker or 120-day-edge test
- Task 2: minor (deferred): _context_builder and retired use pre-5b data (harmless: delistings already found, dead securities not listed); no test for several real endings, for the skip when fails rows exist, or for backfill finding nothing; the double compares ISO date strings
- Task 4: minor (deferred): is_backfilled should use the same letter filter
- Final review: minor (deferred): two dead securities claiming the same CUSIP — the first in sec_id order keeps it, since held reads the live sec_cusips (deterministic)
- Final review: residuals — finding 5 (no review flag for backfilled securities) deferred by ruling; the shared-CUSIP order minor deferred

## reset-4c: assumed par after any failed gate (first step)


1. every dispatch uses model sonnet (standing instruction) — cost if wrong: weaker reviews.
2. decision 4 adopted as proposed (reset-2); decision 2's hand-valued terms wait for reset-4e (plan Ruling 1) — cost if wrong: ~20 valuable-now mergers stay unvalued tonight.
3. Task 2's three-line docs diff is reviewed by the controller inline (CLAUDE.md:31 count 1680, CLAUDE.md:613 and README.md:218 name the three gates; all true of 9e9d67f) — a reviewer dispatch costs more than the diff — cost if wrong: a docs wording slip
4. Task 3's review and the plan's final review run as one reviewer — the plan is one rule, and both reviews read the same acceptance — cost if wrong: a cross-task issue a separate final review would see
5. the co-author minor is dismissed again — trailers follow this session's attribution instruction — cost if wrong: none

Deferred minors:

- Task 1: minor (deferred): the negative test covers llm_gate_failed only; verdict.GATE_FAILED shares its name with payout_gate.GATE_FAILED (the "payout_gate_failed:" prefix), a different thing

## reset-4e: exchange-print dates the caches held (first step)


1. every dispatch uses model sonnet (standing instruction) — cost if wrong: weaker reviews.
2. decision 12 adopted (reset-3); only exchange prints count — cost if wrong: none.
3. _OPEN keeps no verb anchor — the scan found no reachable false positive of a new kind, MIDAS, a halt and the notice beat the 8-K in decide_last_trade, and the acceptance rebuild counts the new 8k_301 dates — cost if wrong: a 3.01 record-date or rights-plan sentence could date an ending that has no measured print
4. the plan's catch was wrong — 9c brackets each read with DegradedWatch and reports a tripped one with watch.report_delisting(review, d, "the handoff row's Form 25 notice"), like _find_delistings — cost if wrong: none
5. a notice day is taken only before B's first sighting (evidence handoff.b_first) and no later than the row's delist_date (the Form 25 effective date) — keeps _last_day's guarantee and the contract's publish rule — cost if wrong: a notice later than B's first sighting is ignored
6. 9c is metered ("handoff notice dates"), like 5b; the a_last/reason-text minor is deferred (still a true statement of the sighting, no consumer parses it) — cost if wrong: none
7. Task 3's docs diff is reviewed by the controller inline (CLAUDE.md count 1695, stage list adds 9c with both caps and the meter, last_trade.py bullet lists the wordings; data-flow.md item 2 and a Stage 9c paragraph; all true of 72c2ad7) — small docs diff — cost if wrong: a docs wording slip
8. rerun the rebuild once so the halt day is fetched and cached; publish only if it exits 0 — a transient feed failure is not a code defect — cost if wrong: another rerun
9. A.census.continuation.errors 28->29 and V.audit.confirmed_but_wrong 40->41 may be lowered by hand with the reason "reset-4e dates Google Inc's last trade correctly (2015-10-02); Alphabet's ticker range starts at its first fails-row sighting (2015-10-06), one trading day late, so GOOG on 2015-10-05 has no holder" — the date is right and the gap is a sighting-precision issue outside this plan (a successor's range could start the trading day after its predecessor's last trade: queued as a follow-up) — cost if wrong: one audit case reads wrong until that follow-up
10. V.uncertain_seeds may be lowered by hand if, after the rerun, its rise is only SSCC's sightings after its now-dated delisting (2009-02-03), with the reason "SSCC's sightings after its Nasdaq delisting fall outside its history" — cost if wrong: two seeds listed uncertain
11. the extra table changes are consequences of the new dates and are permitted: securities.csv +1 acquirer (WTNY's merger terms now resolve), SSCC's observation_map rows backfilled_ticker -> after_delisting, contract/seeds.csv verdicts, one delistings ticker cell — cost if wrong: none found
12. no fix wave for reset-4e — only minors; (5) is folded into reset-4f's docs task (README sentence for 9c); (1)-(4) are deferred to the roadmap's follow-ups — cost if wrong: a notice earlier than a sighting is taken unchecked (none in today's 10)

Deferred minors:

- Task 1: minor (deferred): the negative test exercises no new alternative; no test for "before market open" without "the" or the Closing-Date forms of the new phrases
- Task 2: minor (deferred): no test for the delist_date cap; a_last and the reason text keep the sighting day
- Task 4: minor (deferred): SSCC's published 2009-02-03 is after its delist_date 2009-01-30 — a no-Form-25 row whose delist_date is the bankruptcy 8-K anchor, so the Form 25 rule does not apply (the old date was 2009-06-08)

## reset-4f: OTC prints requested and valued (first step)


1. every dispatch uses model sonnet (standing instruction) — cost if wrong: weaker reviews.
2. decision 11 adopted as proposed (overnight ruling); decision 3's "harsh marks stay for rows that still carry a fill" holds — an answered OTC print is a value, an unanswered drop keeps its mark — cost if wrong: none.
3. Task 3 (docs) also adds one README sentence on reset-4e's stage 9c to "Where each date and price comes from" (reset-4e final review minor 5) — cost if wrong: none
4. the firm-month path carries the print — compute_dlret, bmp_firm_month_return and build_firm_month_correction take `otc_print`, and apply_bmp_corrections passes the row's terminal_value when its dlret_method is otc_print; the event-level handling API stays unchanged (plan Ruling 2) — the firm-month correction is the CRSP convention the DLRET belongs to — cost if wrong: none
5. Task 1's fix-round re-review is done by the controller inline — 38 lines: otc_print threaded through compute_dlret, bmp_firm_month_return, build_firm_month_correction (both calls); apply_bmp_corrections reads terminal_value only when dlret_method is otc_print; event-level API untouched; 3 tests (compute_dlret, firm-month, apply_bmp_corrections) — finding ADDRESSED, no new breakage — cost if wrong: a slip in a 38-line diff
6. the price_requests.py docstring paragraph (a long joined line; the answers sentence omits the OTC print) is fixed in Task 3 (docs) — cost if wrong: none
7. Task 3's docs diff is reviewed by the controller inline (count 1705; dlret/exit_kind/price_requests bullets; README requests paragraph, DLRET table row, 9c sentence; data-flow 10g line; price_requests docstring rewrapped — all true of b1d997b) — cost if wrong: a wording slip
8. Task 4's review and the plan's final review run as one reviewer — the acceptance changed one contract file — cost if wrong: a cross-task issue a separate final review would see
9. the README minors go into reset-4a2's docs task (no separate fix wave); the unconfirmed-date case is deferred (the verdict already lists the ending uncertain) — cost if wrong: none

Deferred minors:

- Task 1: minor (deferred): duplicated branch in resolve_dlret; no test of a zero/negative print or of terminal_value/confidence in the table; a panel-close fallback in apply_bmp_corrections rebases the print on the panel close
- Task 2: minor (deferred): no test for the second-pass answer or for 10g refusing an otc_print answer; `dropped` includes non-distress drop reasons (moved_otc, went_private), as the brief says
- Task 3: minor (deferred): the docs do not say the firm-month path (apply_bmp_corrections) carries the print

## reset-4a2: holdco continuations by the successor's own 8-K12B


1. every dispatch uses model sonnet (standing instruction) — cost if wrong: weaker reviews.
2. decision 9 adopted (reset-3) — a 1:1 holdco reorganization is a continuation with a successor link — cost if wrong: none.
3. Task 2 (docs) also fixes reset-4f's README minors — README:273 measured methods add otc_print; README:709/723 and the Shumway section say a liquidation or compliance failure takes a --recoveries ratio (liquidation), else an answered OTC print, else the Shumway mark; one sentence that the event-level handling API ignores the print — cost if wrong: none
4. the fallback is not asked when A's issuer carries on (issuer_carries_on), applied in pipeline.find_filing to the fallback only, so a search hit (which names A) keeps today's behaviour — cost if wrong: a real holdco whose old issuer starts another line is left a merger
5. the reconciled-payout-merger-with-an-unrelated-8-K12B risk is covered by the acceptance listing every changed decision and the controller checking each — cost if wrong: one false continuation reaching the acceptance, where it stops
6. the fix-round re-review is done by the controller inline — a one-line guard, `issuer_carries_on(p, securities, first_seen)` with the decision loop's own arguments (pipeline.py:941 and 972), plus 2 tests and the monkeypatch swap — ADDRESSED, no new breakage — cost if wrong: a slip in a 4-line src diff
7. Task 2's docs diff is reviewed by the controller inline (CLAUDE.md handoffs bullet and count 1711; data-flow handoff paragraph with the carries-on skip; README values list, liquidation row, event-level note, Shumway section, confidence row — all true of 270dfff) — cost if wrong: a wording slip; the five named holdcos are confirmed by Task 3
8. BG is accepted — Bunge Limited (Bermuda) became Bunge Global SA (Switzerland) in Nov 2023 by a 1:1 share exchange, and its successor filed the 8-K12G3: a decision-9 holdco continuation the old merger-at-par row got wrong; APA and MNST keep their continuations on stronger evidence — cost if wrong: none found
9. V.audit.confirmed_but_wrong may be lowered by hand 41->42 with the reason "audit row blank_no_value:BBG009XV39D8 (AVGO 2016-02-01) asks the last trade date of a final ending; per its own note the 2018 Broadcom Ltd -> Broadcom Inc exchange is 1:1 with no exit kind, and the output now continues the chain (active), so the judge finds no final ending — the truth row, not the output, needs its last_trade_date read on the continuation" — the truth file is the operator's, so it is not edited tonight; the morning report names the row — cost if wrong: one audit case reads wrong until the operator fixes the row or the judge
10. Task 3's review and the plan's final review run as one reviewer — cost if wrong: a cross-task issue a separate final review would see

Deferred minors:

- Task 1: minor (deferred): window edges (exactly −30 / +60) untested; the reconciled-payout-merger risk is checked case by case at the acceptance
- Final review: Ready, no Critical or Important; Minor (deferred): an unrelated 8-K12B by an acquirer's issuer could still flip a merger pair (none today, all 8 checked); the fallback read is not prefetched; the AVGO 2016-02-01 audit row is the operator's


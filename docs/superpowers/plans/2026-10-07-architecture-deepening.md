# Architecture deepening of src/delist_detection: program plan and decision log

Branch `arch-deepening`, from f5b3c0d (PR #7's head). The architecture review (2026-10-06) found 11 candidates and 6
smaller ones. The operator asked for all of them, one by one, without rulings mid-run. This file holds the order, the
gate and every choice made along the way.

The vocabulary (module, interface, depth, seam, adapter, leverage, locality) is the codebase-design glossary. The
domain terms are CONTEXT.md's.

## The gate (every step)

A deepening moves behaviour behind a smaller interface. It changes nothing the library publishes.

- **The full suite passes.**
- **The offline whole-run replay is byte-identical** to the reference made at f5b3c0d
  (`/tmp/claude/delist_detection/arch/ref_out`, checked with `same_output.py`).
- **A declared defect fix may change rows.** Each changed row must be explained in the commit. Four defects were
  found by the review:
  - a failed EDGAR read in the handoff stage can crash the run;
  - AZPN 2022's stale payout flags on a continuation;
  - CNB, IMB and SPNV publish a last trade date flagged unconfirmed;
  - `plan_stock` gets "low" confidence.
- **Tests move to the deepened module's interface.** Tests that reached past it are deleted once covered.

## Order

| # | Candidate | Defect fixed | Status |
|---|---|---|---|
| 1 | Stage 8 as one merger value module, with the price request round trip (review 1, 2) | | done |
| 2 | One issuer record over EDGAR with the failed-read policy (review 4) | the handoff stage's uncaught read | done |
| 3 | One owner for rewriting an ending (review 3) | AZPN's stale flags | done |
| 4 | The last trade date as one module (review 5) | CNB, IMB, SPNV | |
| 5 | history owns where a security's history ends (review 6) | | |
| 6 | A security's identity behind security_master (review 7) | | |
| 7 | The line follow owns its rounds; one R1 reading per ending (review 8) | | |
| 8 | One run snapshot; one reading of a delistings row (review 9) | | |
| 9 | The truth set and the loop round as two modules (review 10) | | |
| 10 | dlret decides the value rule once (small) | plan_stock's confidence | |
| 11 | The Clients seam declares capabilities (small) | | |
| 12 | The fails index owns its loading (small) | | |
| 13 | One leaf module for ticker and share-class spelling (small) | | |
| 14 | The finder builds its own trading record (small) | | |
| 15 | One truth-case type (speculative) | | |
| 16 | Package layout: concept subpackages and a lazy package root (review 11) | | |

The issuer record (2) comes early because stages 8, 9 and 9b read issuers through closures that it replaces. The
layout (16) comes last, once steps 8 and 13 have made the pure leaf modules.

## Decision log

- **2026-10-07:** the work goes on its own branch, so PR #7 (the diagnosis-truth roadmap) stays reviewable as it is.
  This branch stacks on it.

### Step 1: stage 8 as one merger value module, with the price round trip

- **Order inside the step: `MergerTerms` first, then the module and the round trip in one commit.** The answer type
  had to answer for its own package before the module could ask it. The round trip went with the module, because
  stage 8's answer routing (`_answered_paths`) moved with the stage.
  - Alternative: the round trip as a commit of its own, before the module.
  - Cost if wrong: `_answered_paths` would have been rewritten twice. Nothing was lost by the order chosen.
- **"No ticker" is cleaned once, when a `MergerTerms` is built** (`__post_init__`, `NULL_TICKERS`). Before, three
  null lists were applied by the gate, stage 8a and the extractor.
  - Alternative: one shared `clean_ticker` called at every read.
  - Cost if wrong: an answer built by hand with "NULL" now reads as no ticker. The extractor already cleaned
    every answer it built, so no production answer changes.
- **"Holds stock" stays three named predicates, not one.** They are `has_stock` (any security: the gate and the
  rule), `stock_leg` (a ratio or a dollar value: what asks a received close and what stage 8a looks up) and
  `stock_ratio` (the gate's merged terms, `_stock_ticker`).
  - Alternative: one predicate.
  - Cost if wrong: none to output. Unifying them would change which legs ask a close or take a line (PCYC's
    dollar-valued leg), which is a behaviour change no step has declared.
- **The module is `merger_value.py`.** Its interface is `value_mergers(...) -> MergerValues`: one `MergerValue` per
  merger ending, plus one method per later reader (8b `read_terms` and `drop`, 9b `reconciled`, 10a
  `table_inputs`, 10c `payout_rows`, 10g `contract_inputs` and `requests`).
  - Alternative: hand the stages the records and let each one read its fields.
  - Cost if wrong: the class has eight methods. The rejected design is how the gate, the contract and the requests
    came to disagree. `table_inputs` still feeds `build_delistings_table`'s maps; step 10 (dlret decides the value
    rule once) can replace it.
- **`acquirer_line`, `acquirer_ticker`, `acquirers` and `payout_gate` stay collaborators, not internals.** Each is
  a rule module with its own interface and real-case tests (`test_payout_gate`, `terms_cases`,
  `test_acquirer_line`, the Ashland and TVTY unit tests). `merger_value` is now their only stage caller, and it owns
  the order and the failed-read policy.
  - Alternative: fold them into `merger_value`.
  - Cost if wrong: four public interfaces remain, and a second caller could grow. Folding them would have put
    2,400 lines in one file and pushed their rule tests through the whole stage. `acquirers` still imports
    `delistings.Delisting`; that is left for the layout step (16).
- **No lookups adapter seam yet.** The module takes the run's clients as they are. Its two EDGAR memo readers are
  one private class, `_IssuerReads`, which keeps both failure policies: 8a asks a failed CIK again, 8a' does not.
  - Alternative: an adapter over the fails index, OpenFIGI and EDGAR, now.
  - Cost if wrong: with one production adapter the seam would be hypothetical. Step 2 (the issuer record) replaces
    `_IssuerReads` and pipeline's `_IssuerAge` with the run's issuer reader.
- **`LineIndex.fresh()` replaces the four `LineIndex(...)` builds.** It shares the sighting ranges and starts a new
  first-row memo, because the gate extends the fails index between the builds.
  - Alternative: one shared index.
  - Cost if wrong: none. A shared index could remember a CUSIP's first row from before the extension and change
    `closing_cusip`.
- **A price answer is matched on the request's own key.** The key is the security, its last trade day and the kind,
  and for a received close also its ticker (`price_requests._input_key`). Before, `_apply_price_answers` gave a last
  close or an OTC print only to the delisting listed last with that security and day.
  - Alternative: keep the "listed last" binding inside `PriceAnswers`.
  - Cost if wrong: in a run with answers, a security with two delistings on one last trade day gives both rows the
    answered close. HNZ 2013 is the one case: its 25-NSE and 25-NSE/A rows share 2013-06-07. Before, the earlier
    row kept the fails close. Both rows already shared that fails close, so the answer now reaches both alike. The
    replay answers no request, so no reference row changes.
- **A received close is read per leg**, by the ticker its request names. Before, one slot per delisting let a
  basket's second-leg answer overwrite the main leg's.
  - Alternative: none worth keeping.
  - Cost if wrong: none. The gate prices no basket, so the old overwrite never reached a value.
- **A last close given both ways stops the run inside stage 7** (`PriceAnswers.last_closes`), naming the delistings
  in run order. It used to stop at stage 6b, in the answers file's order.
  - Alternative: keep the file's order.
  - Cost if wrong: only the order of a several-item message changes. The exit (2) and the point it stops at,
    before stage 7 reads any fails rows, are the same.
- **Readings kept as they were, and left for later steps.**
  - R1's `read_terms` reads both legs of an election that states no package, where the contract publishes only its
    all-cash alternative. Step 7 gives one R1 reading per ending.
  - An empty `--merger-terms` row (`{}`) counts as given for the gate and stage 8a, and as absent for R1 and the
    request. Each site keeps its own test.
  - The first gate pass now never flags and the last pass's lagged closes are flagged once. This is the same as the
    old `flag=not acquirer_prices`, because a pass with no answer for a merger repeats the first pass for it.

### Step 2: one issuer record over EDGAR, with the failed-read policy inside it

- **The module is `issuer_record.py`: one `IssuerRecord` per run.** The resolver builds it over its client, run
  date and name index unless one is given. The classifier takes its resolver's record, and `Clients.issuers` picks
  the same one up (`__post_init__`). `_run` makes it forget everything when a run starts.
  - Alternative: the pipeline builds the record and hands it to the resolver and the classifier.
  - Cost if wrong: none to output. The replay script and the tests build `TickerResolver`, `DelistClassifier` and
    `Clients` without a record, so the record must come from what they already pass. A caller who builds the
    resolver and the classifier over two records gets two memos; both keep the one policy.
- **The interface is the reads and what they answer.** The reads are `profile` (the submissions JSON without its
  filings block: name, former names, tickers, exchanges), `filings` and `text`. The answers are `names`,
  `names_near`/`names_between`/`names_until`, `first_filed`, `existed_by`, `recent_form_dates` and `exact_holders`
  (SEC's name index, which moved from the resolver). `about=` asks for a copy current for an event
  (`edgar.submissions_fresh_after`).
  - Alternative: answers only, no raw reads.
  - Cost if wrong: the line follow's `corroborate`, the handoffs' `predecessor_names`, the R1 reading, the acquirer
    lookups and the issuer in force take the profile or the filing list. Hiding them would mean rewriting those rule
    modules in this step. None of them reads the filings block, so `profile` leaves it out.
- **What it remembers: every issuer's profile and first filing, and at most `MEMO_SIZE` (512) filing lists**, the
  least recently asked dropped first. Only current copies are remembered.
  - Every refresh of the run goes through it: the resolver's reads and the classifier's up-front read. So a held
    profile is the client's cached copy's.
  - A copy that does not carry its fetch day is read again for an event. 1,046 of the 5,987 cached copies carry
    none; the client stamps every copy it fetches, so such a copy is the cached one, and it keeps the filing list.
  - A refreshed copy drops the filing list and the first filing it held from the old copy.
  - `recent_form_dates` reads the client's copy each time, as the resolver's `_form_dates` did. The recent block is
    the bulk of a copy and only the name tier asks for it.
  - Measured on the replay: the base reads 2,529 issuers' submissions 32,946 times, and its peak memory is 6.46 GB.
    The cache holds 5,987 copies, 496 MB on disk.
  - The first build held at most 512 whole copies. Stage 8a's name lookup (`acquirer_line.issuer_by_name`) reads
    every issuer of the run's names for each of 331 stock legs, so that bound made it read 91,901 copies (118,721
    in all). Profiles are a few kilobytes each, so all of them are kept.
  - Measured with profiles kept: 19,262 submissions reads (base 32,946) and a peak of 5.47 GB (base 6.46 GB).
  - Alternative: hold every issuer's whole copy for the run.
  - Cost if wrong: a filing list asked again after 512 others is read again from the disk cache. That costs time
    only. Holding all 2,529 parsed copies would have added gigabytes to a run that already peaks near 6.5 GB.
- **The failure policy.**
  - A `requests.RequestException` is unknown and never remembered.
  - `fatal.FATAL` stops the run.
  - Any other exception propagates.
  - A failed, stale or self-counted degraded read logs its CIK on the reading thread.
  - The resolver used to swallow every exception from its EDGAR checks. The instrumented base replay shows it
    swallowed none.
  - Alternative: keep the resolver's broad catch inside the record.
  - Cost if wrong: a malformed submissions payload that the resolver read as "no answer" now stops the run with
    exit 1. The stages already did so.
- **One watch for degraded reads: `ReadWatch`.**
  - `ciks`: the CIKs whose issuer reads failed or were stale. `failed`: the ones with no answer at all.
  - `tripped()`: either of those, or any other degraded SEC read on the thread. A stage that mixes issuer reads with
    searches and texts therefore asks one watch: 8a, 8a', 8b, the terms links of 9 and 9b.
  - It replaces `_IssuerAge.failures`, the `failed` sets and the `DegradedWatch` around the issuer reads.
  - It sees a failure even when the client did not count it (a test double). That is how the handoff defect test
    is written.
  - `DegradedWatch` stays where no issuer is read: the finder, payouts, notices, distress, continuation readings
    and the line follow's per-step watch.
  - Alternative: replace `DegradedWatch` at all 17 sites.
  - Cost if wrong: two watch types remain until step 11 or 16 folds them.
- **merger_value's two policies are not kept: 8a' asks a CIK whose read failed again.** The replay refuses no
  request, so the two policies give the same output.
  - Under the old "remember failures" policy, a second leg that touched a failed CIK got no answer, and its watch
    saw no read, so no degraded item was reported. Asking again reports it.
  - Alternative: keep "remember failures" inside a watch.
  - Cost if wrong: in an outage, 8a' asks a failed CIK once more per leg. There are a handful of legs, and the
    client retries each request already.
- **Stages 4c and 10g keep "not asked again in this stage" (`_in_force_reads`).** They read one CIK per sighting,
  35,955 sightings. The stage skips `reads.failed`, and every security that touches the CIK still gets its
  degraded row.
- **The line follow's `_IssuerReads` is replaced too,** although the step's list did not name it.
  - It read the same submissions and filing lists under the same policy, so keeping it would keep a second reader.
  - Its 8-K texts go through `IssuerRecord.text`, which is never remembered.
  - A failed other-registrant search stays a local set.
  - Alternative: leave it for step 7.
  - Cost if wrong: step 7 builds on the record instead of moving `_IssuerReads`.
- **In the loops this step rewrote, the stages' other reads of an issuer's own submissions and filing list go
  through the record too.** They are `_own_exchange` (8b, 9), `_own_registration_link`, the handoffs'
  `filing_args`/`find_filing` and 8a''s target filing list and text.
  - Like `issuer_since`, they had no catch: a failed read with no cached copy stopped the run.
  - Alternative: route only `issuer_since`.
  - Cost if wrong: none in the replay. In an outage those reads are unknown and `resolution_degraded` instead of
    exit 1.
  - Left for later steps, still read straight from the client:
    - `listing_status` (`issuer_exchange` in 9b and 10b can still stop a run);
    - `successors.successor_search_name`, stage 9e's 8-K list (`_eightks`) and stage 9g's `continuation_evidence`;
    - the finder's own reads (its per-security try turns a failure into an `error` row).
- **The classifier asks its issuer record, not the resolver's privates.** It reads `profile(cik, about=)` for
  the up-front refresh (`submissions_stale` from the watch) and `names_near(cik, day, about=day)` for the name check.
  `TickerResolver.expected_name` is now public. The warm finder's classifier copy holds a shadow record instead of a
  shadow resolver.
  - Kept: an unreadable issuer still flags `member_name_mismatch`.
  - Changed only on a failure: an up-front read that fails outright no longer raises at once. The classifier's next
    direct read raises as before; if it succeeds, the row carries `submissions_stale`.
  - The freshness bound is now the record's run date (the resolver's), not the classifier's own `today`. The two are
    equal in `default_clients` and the replay.
  - Alternative: keep the classifier's own read and pass `fresh_after`.
  - Cost if wrong: that read would refresh the disk copy behind the record's back, so a held copy could go stale
    for the rest of the run.
- **`successors.successor_by_terms` takes the record (`issuers=`)** in place of two callables. The `issuer_since`
  strings became `first_filed` dates. The day is the same, because EDGAR's filing dates are ISO dates.
- **The declared defect: the handoff stage's uncaught read.** The pair's `first_filed` read now sits inside the
  pair's watch. A failure gives the pair's `resolution_degraded` item ("the handoff search ...") and leaves the
  issuer's age unknown.
  - `tests/test_issuer_record.py` proves it with a FakeEdgar whose read of the successor issuer's filings fails.
    The run completes. The same scenario on the base code stops with `ConnectionError`.
  - The replay refuses no request, so it changes no row.

### Step 3: one owner for rewriting an ending

- **The module is `rewrites.py`: functions over the in-memory `Delisting`, not methods on it and not a run object.**
  The interface is `continuation`, `security_goes_on`, `mark_going_on` and `reclassify`, plus the readings
  `awaits_successor`, `is_real_ending`, `rewrite_by`, `successor_by` and `successor_note`. `Delisting.set_successor` is
  gone. The finder, stages 8b, 9, 9b and 9e and the clip check call it; no stage edits `crsp_code`, `bucket`,
  `successor_sec_id` or a continuation's flags itself.
  - Alternative: methods on `Delisting` in delistings.py, or a per-run `Rewriter` holding the merger values.
  - Cost if wrong: callers pass the merger values themselves (`payouts=`). A merger made a continuation without them
    raises, so a forgotten drop fails loudly instead of leaving stale reads. delistings.py stays the finder.
- **The rules are a closed set of nine (`Rule`).** `ISSUER_MOVE` (finder R7), `CONTINUED` (the finder's continued
  transfer), `TRADES_ON` (the clip check), `R1` (8b), `LINE_FOLLOW` and `SUCCESSOR_LINK` (9), `HANDOFF` (9b),
  `PLAN_BANKRUPTCY` and `PRICE_DEFICIENCY` (9e). `SUCCESSOR_LINK` covers the in-run, terms, own-registration and
  8-K12B links; the rewrite's `how` names which.
  - Alternative: one rule per link source.
  - Cost if wrong: the rule is coarser than the link; `how` carries the rest, as the reason always did.
- **One rule for every continuation, R1's: no no-evidence default, no `successor_unknown`, no payout or terms-gate
  flag (`PAYOUT_FLAGS`, matched by name) and no payout read (one `MergerValues.drop`).** Any kind leaving `unknown`
  drops the no-evidence default. A security that goes on keeps its kind and value (WRK, DIS mergers stay mergers).
  - The payout reads are the whole merger value: a continuation the handoff stage makes from a merger loses
    delistings.csv's `acquirer_sec_id`, `acquirer_ticker`, `stock_ratio`, `acquirer_price`, `payout_source` and raw
    payout columns, and its payouts.csv row. That is 18 rows, not the 5 the review counted by flag: 13 of them
    carried the one-for-one LLM terms and raw reads but no stale flag.
  - Alternative: drop the flags only, or the reads only on rows that also had a stale flag.
  - Cost if wrong: a reader of a continuation's payout columns finds them blank. Its DLRET is 0 whatever they say
    (`dlret`, `handling`, `bmp_correction` ignore them for a transfer), and the contract published no value for it
    already. Keeping them would leave R1 and the handoff with two rules again.
- **`PAYOUT_FLAGS` names every flag stage 8 raises**, three more than 8b's old set (`terms_gate_skipped`,
  `llm_election_package`, `election_no_default`). They live on the merger value, dropped with it, so the wider set
  changes no row. `acquirer_close_lagged` is the one stage 8 writes onto the delisting's own flags.
- **Typed provenance is `Delisting.rewrites: list[Rewrite]`** (rule, kind before, successor, how, evidence, a
  handoff's `successor_from`). It replaces `evidence["successor_by"]`, `evidence["r1"]` and `evidence["handoff"]`.
  Stage 9c's cap reads `successor_from`; the issuer-role harness reads `successor_by`. Never a column.
  - Alternative: typed fields on `DelistRecord`.
  - Cost if wrong: none to output. `DelistRecord` is the published record the handling side shares; provenance on it
    would invite a column.
- **The finder's `form25_*` review items carry the Form 25 typed (`review_triage.FilingRef`, `ReviewItem.filing`).**
  The handoff stage takes the ambiguous Form 25's form, accession and filing date from it (its regex over the reason
  is gone, and so is its "delist date less 10 days"), and stage 9d drops an owned Form 25's items by
  `filing.accession` (the OKE fix's reason split is gone).
  - Alternative: keep parsing the reason.
  - Cost if wrong: an item built by hand without `filing` is invisible to both readers; the tests' items carry one.
- **The order is enforced by structure: the clip check's marking is stage 9b's first step (`_handoffs` calls
  `mark_going_on` before `apply_handoffs`), its only call site.** `_run` no longer computes the first starts and
  endings; `_handoffs` takes `added` and computes them. Stage 9 now records its own links (`_find_successors` ends
  with `_link_successors`), so `_run` calls it once.
  - Alternative: a token from the marking that `apply_handoffs` requires, or a state flag.
  - Cost if wrong: a future stage between 9 and 9b that sets successors must run before `_handoffs`. The marking moved
    after the pair search inside 9b; the search reads no successor, and the replay shows no row moved by it.
- **The handoff stage's new row is built with no kind and made a continuation by the same rewrite** (`_continue`), so
  every continuation the stage makes has one path. Its `Rewrite.was_bucket` reads `unknown`.
  - Alternative: a row constructor in `rewrites.py`.
  - Cost if wrong: provenance only; a written row says it was `unknown`.
- **Constants defined once.**
  - `crsp_codes.CONTINUATION_CODE` (304) replaces the literals in classifier, end_of_era and the finder and
    `handoffs.CONTINUATION_CODE`. It lives in the code table: the classifier and the resolver are not rewrites.
  - The reason protocol lives with its writer, end_of_era: `CONTINUED_FILINGS`, `CONTINUED` built from it, and
    `RESOLVED_FROM_CONTINUED_FILINGS`. lifecycle's copies are gone, and end_of_era's EdgarSubmission import is
    type-only, so the finder, 9g, verdict, verdict_rules and scorecard import a pure leaf. This removes the
    classification-to-measurement import for these two.
  - The flags a continuation rule leaves (`r1_continuation`, `line_continuation`, `handoff_continuation`) and
    `successor_unknown` live in rewrites; the classifier's own R1 flag reads the same constant.
  - The "; successor by X" note is `successor_note`, used by 8b, 9 and 9b.
  - Cost if wrong: none to output; the published strings are byte-identical.
- **The table predicates have one definition, in exit_kind: `is_real_ending(row)` and `is_continuation(row)`.**
  contract, lifecycle, verdict, verdict_rules, scorecard and audit read them. The in-memory reading is
  `rewrites.is_real_ending(d)` (5b, 9d, the clip check).
  - Left: `continuation_evidence.needs_filing`/`needs_doubt_check` keep their scalar tests and their reading of the
    reason (stage 9g reads the same strings as the verdict; step 7 owns the R1 reading).
- **verdict.py's by-name workaround is removed** (`not successor_registration` on the `no_evidence_default` line), and
  verdict_rules' docstring no longer names GOOGL. GOOGL's and GOOG's verdicts stay confirmed in the replay.
  - The verdict real-case fixture's GOOGL row is the fixed one now (its `no_evidence_default` and its review row
    removed). The two verdict_rules tests of the workaround became tests of the rows as the library now writes them.
  - Cost if wrong: an offline recompute over an output written before this fix raises `no_evidence_default` on
    GOOGL and GOOG. The scorecard reads `uncertain.csv` as written, so the committed output's floor test is untouched.
- **Left as they were.** The ticker takeover's `ticker_successor_sec_id` (not a kind or successor change) and the
  handoff's last-trade edits (step 4) stay in handoffs. The classifier's own edits of the end-of-era verdict (rule 6,
  branch 5b, R6b) are not rewrites.
- **Tests.** `tests/test_rewrites.py` holds 14 tests at the interface, one per rule and each declared change. Of the 21
  whole-run tests that swap `pipeline.DelistingFinder`, none checks only a rewrite rule (they test the clip, stage 8,
  the successor search, the finder's context, triage, prefetch and provenance), so all stay. The four
  `_mark_continuing_delistings` tests: three now test the clip check (`_delisting_endings`) alone, and the
  "never overwrites" one moved to test_rewrites. The issuer-role harness calls stage 8b and stage 9 directly, reads
  `rewrites.successor_by`, and lost its `inspect.signature` and `getattr` workarounds.
- **The declared defect: a continuation carries no stale flag and no payout read.** The replay changes exactly these
  rows, all from the handoff stage's continuations (`Rule.HANDOFF`):
  - payout and terms-gate flags and payout reads: AZPN 2022;
  - `acquirer_close_lagged` and payout reads: AVGO 2016, ENDP 2014, NE 2009, ACT 2013;
  - payout reads only (the one rule's "no payout reads"): CI 2018, FCE-A 2016, ARRS 2016, MRVL 2021, QDEL 2022,
    BG 2023, SPB 2018, APO 2022, AVGO 2018, NCNO 2022, FERG 2024, DKNG 2022, ICE 2013;
  - `no_evidence_default`: GOOGL 2015, GOOG 2015.
  - Cascades: payouts.csv loses the 18 merger rows; review.csv loses AZPN's, GOOGL's and GOOG's `check` rows (their
    other flags are info); review_summary.csv's counts follow (no_evidence_default's row goes; payout_gate_failed
    10 to 9, terms_gate_failed 20 to 19, acquirer_close_lagged 46 to 42, handoff_continuation in review 7 to 4,
    last_trade_date_unconfirmed in review 34 to 33); the manifest's review counts (check 536 to 533, info hidden 601
    to 604); scorecard.json's R1.4.review_rows 592 to 589 and R1.4.review_securities 411 to 409 (so the
    R1.4.review_rows drop against the floor of 591 clears). uncertain.csv and the contract are unchanged; no `D.*`
    value moves.
- **Controller ruling: the 13 rows with payout reads only are accepted.** The prompt listed rows by stale flag; these
  13 follow from the same one rule. Each was checked: an `exchange_transfer` to another security, dlret 0.0 before
  and after, only payout-read columns changed, no flag added. All 13 are holding-company reorganizations or
  redomiciles (CI, ICE, AVGO 2018, FERG, BG and the rest), where a merger's payout read describes a deal the row no
  longer is.
  - Alternative: keep payout reads on a continuation and drop only the flags.
  - Cost if wrong: a caller reading payouts.csv or the raw payout columns for these 18 rows finds them blank. No
    DLRET, contract value or truth field changes. A row later turned back into a merger gets its reads back, because
    the rule runs only on a rewrite into a continuation.
- **The replay reference moves.** From step 4 on, the gate compares against step 3's accepted output
  (`/tmp/claude/delist_detection/arch/accepted_out`). Otherwise every later step would show these 20 rows.

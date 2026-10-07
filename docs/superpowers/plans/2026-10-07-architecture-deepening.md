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
| 4 | The last trade date as one module (review 5) | CNB, IMB, SPNV | done |
| 5 | history owns where a security's history ends (review 6) | | done |
| 6 | A security's identity behind one interface, `identity.py` (review 7) | | done |
| 7 | The line follow owns its rounds; one R1 reading per ending (review 8) | | done |
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

### Step 4: the last trade date as one module

Controller rulings, made before the step was dispatched:

- **Which side is right for CNB, IMB and SPNV: the flag.** The last trade module gives one answer, and a date is
  published only when it is confirmed. Decision 12 publishes only an exchange print. Spec 8.8 says an involuntary
  notice's date is the exchange's decision day, a print only when MIDAS or a halt confirms it.
  - Alternative: the source list wins, and the flag is cleared when the notice and an 8-K agree.
  - Cost if wrong: a few distress endings dated by an unconfirmed notice or "suspended immediately" lose their
    published date. Their internal date in delistings.csv stays.
- **SPNV 2020's date is confirmed by its own 8-K, which the reader missed.** The 8-K (0001193125-20-248926) says
  "Trading of the Company's common stock was suspended effective as of approximately 4:00 p.m. Eastern Time on
  September 17, 2020". The reader returns nothing for it. Step 4 teaches the reader a suspension at a stated clock
  time, so SPNV is dated 2020-09-17 from source `8k_301`, confirmed and published, as the verified truth case has it.
  - Alternative: leave the reader alone and let SPNV's date go unpublished.
  - Cost if wrong: other 8-Ks with this wording change too. Each must be checked against its own text.
- **CNB 2009's truth row stops scoring its contract last trade date.** CNB's 8-K says only that NYSE "determined
  that the Company's common stock ... should be suspended immediately" (announced 2009-08-17). The operator's
  2026-10-03 ruling for IMB 2008 ("suspended immediately on D: the last trade date is not scored") and the 5d
  decision ("stays D, unconfirmed") cover the same wording. The decision-17 audit leaves CNB's date blank too. So the
  row's `last_trade_date` becomes `*`, with a change-log row. Its `internal_last_trade_date` 2009-08-17 is still
  scored.
  - Alternative: keep scoring 2009-08-17 and count CNB as a new mismatch.
  - Cost if wrong: if CNB did trade on 2009-08-17, the truth set no longer checks the contract's date for it.

Decisions made in the step:

- **The module is last_trade.py, grown, not a new file.** It keeps the readers and the source order and gains
  `Dating` (the windows, the confirmations, rules 3 and 4, the fallback, 9c's re-dating), the handoff rule
  (`at_handoff`), the security's trading as data (`OwnTrading`), the derived facts and their row reading, and the
  sources and flags. The interface: `Dating(edgar, midas=, halts=)` with `of_group`, `of_fallback` and
  `from_notice`; `at_handoff`; `LastTrade.confirmed`, `worked_out`, `publishable`; `of_row`, `effective_of`,
  `published`; `anchor_day`, `first_day_after`; `ticker_taken` and `last_row_trade_day` (rule 3 and rule 4's
  floor, public for their unit tests); `SOURCES`, `EXCHANGE_PRINTS`, `MEASURED`, `UNCONFIRMED`, `CONFLICT`,
  `NO_DAY`.
  - Alternative: a new `dating.py` beside the readers.
  - Cost if wrong: one file of about 750 lines. The readers are only reached through `Dating` in production; their
    tests stay at the reader level, which is where their bugs were (TMA, IDARQ, CBL, CNDT).
- **MIDAS and the halt feed are `Dating`'s adapters, passed through the finder's existing `midas=`/`halts=`
  keywords.** The finder holds only `self.dating`; the 11 window constants and the nine dating methods left it.
  - Alternative: inject a `Dating` (`DelistingFinder(edgar, classifier, dating=...)`).
  - Cost if wrong: the finder's constructor names two adapters it never calls. Keeping it spares about 70 test
    constructions and the pipeline tests' `_Recorder` doubles; step 11 (the Clients seam) can make it one argument.
- **Rule 4 runs inside `of_group`.** The classification still anchors on the day the sources state (or the
  winner's filing date), read as `None if lt.worked_out else lt.day`: a `closing_day` source exists only after rule
  4, so this is the old pre-rule-4 day exactly.
  - Alternative: two calls, the reading then rule 4 after the classification.
  - Cost if wrong: a future worked-out source must be named in `LastTrade.worked_out`.
- **The security's trading reaches the module as data.** `SecurityContext.trading` (`OwnTrading`: sightings, own
  CUSIPs, their trading rows, the fails index) replaces three closures (`tickers_between`, `ticker_taken`,
  `rows_trade_until`); `pipeline._ticker_taken`, `_last_row_trade_day` and `PLACEHOLDER_PRICE` moved into the module.
  - Alternative: keep the closures, each calling the module.
  - Cost if wrong: step 14 (the finder's trading record) builds on `OwnTrading` or folds it in.
- **`from_notice` reads the Form 25 through the run's EDGAR client; stage 9c keeps the watch.** The stage wraps the
  call in a `DegradedWatch` and reports a tripped read, as stage 5 does around the finder. The module returns the
  row's own `LastTrade` unchanged when nothing re-dates it, so the stage tests identity.
  - Alternative: 9c reads and parses, the module decides on a parsed `Form25`.
  - Cost if wrong: none to output; the read sits behind the module like the finder's 8-K reads.
- **"Confirmed" is `LastTrade.confirmed`: dated and not flagged unconfirmed.** The clip check, the history end,
  the successor starts and 9c read it. A handoff's last sighting is confirmed, as it was (it never carried the flag).
- **"Publishable" is `LastTrade.publishable(effective)`, and the row side asks the same over a row read back
  (`of_row`, `effective_of`, `published`).** contract.py calls `published`; verdict's ending reasons are the parts
  of it that fail, from the same reading; scorecard counts `EXCHANGE_PRINTS`. `verdict.published_last_trade_date`,
  `form25_effective`, `FORM25_EFFECTIVE_DAYS`, `MEASURED_SOURCES` and `lifecycle.EXCHANGE_PRINT_SOURCES` are gone
  (the effective date is `form25.effective_date`, the same 10 days).
  - Alternative: keep verdict's reading and add the flag to it.
  - Cost if wrong: none; one definition, two readers (in memory and over a row).
- **Sources and flags are module constants, not an Enum.** The published strings stay byte-identical; the
  fallback's last sighting keeps its blank source as `UNSOURCED`.
  - Alternative: a `str` Enum.
  - Cost if wrong: a misspelled new source is not caught by a type; `SOURCES` lists them for tests.
- **`ISSUER_FORM25_FORMS` moved to form25.py** (rule 4 and the finder both read it; last_trade cannot import the
  finder).
- **The clock-time reading's kinds are `8k_close_clock` and `8k_open_clock`** (stated timings, rank 0; the open one
  is in `OPEN_KINDS`, as a suspension before the open is for the halt rule). A time at 9:30 is not before the open
  (`< OPEN_MINUTES`, as the effective-time and closing-day readers count); a time during the session reads nothing.
  - Alternative: reuse `8k_close`/`8k_open`; read 9:30 as before the open; read an intraday time as D.
  - Cost if wrong: AmTrust's "9:30 am EST on November 29, 2018" (0001193125-18-337455) and Apollo Education's
    "11:00 am EST on February 1, 2017" (0001193125-17-026959) give no reading, as before; their rows keep their
    other sources.
- **The harness (tests/last_trade_cases.py) stays on the finder and `pipeline._context_builder`.** It reaches the
  module through its one Form 25 caller, reads the flag by the module's constant, and its outcomes are unchanged.
  The context builder is step 14's; stage 7's fails close is not dating.
- **One anchor rule, `anchor_day` (`Delisting.anchor`): the last trade, else the Form 25's filing date, else the
  anchor 8-K's, else the delisting date.** Before, four orders over eight sites. Measured with two whole replays
  (every site on the one rule, and every site kept):
  - unified, no row moved: `successors.successor_in_run` and `_line_successor_links` (last trade, Form 25, delisting
    date: an undated row always has a Form 25, so the anchor 8-K is never reached), `successor_anchor` (removed: the
    R1 reading and the terms links read `Delisting.anchor`), `successor_search_args`, `handoffs._day_of`, stage 5b's
    end and the 8-K12B successor's first day (these four were the last trade, else the delisting date);
  - kept, as a named second fact, `end_day` (the last trade, else the delisting date, the Form 25's effective date):
    the history end (the clip) and stage 9e. On the anchor rule FWLT 2014, AWH 2017, WPG 2021 and ARD 2021 (undated,
    their issuers' own Form 25s) clip ten days early in ticker_history, cusip_history and security_history, and 9e
    reads WPG's OTC symbol as WPG instead of WPGGQ. The security stayed listed until the Form 25 took effect, so the
    end day is the right reading there, not a leftover order.
  - kept: the successor starts' window (the confirmed last trade, else the delisting date less 30 days). It bounds
    a successor's first day on a *confirmed* day, which is `LastTrade.confirmed`, not an anchor.
  - left for step 8 (one reading of a delistings row): the row side's `last_trade_date or delist_date` in
    `lifecycle.end_of` and `verdict_rules._within_days` (the end day over a row).
  - Alternative: every site on one order.
  - Cost if wrong: two named days instead of one; each says where it is used and why.
- **An added successor's first day is `first_day_after`, the next trading day, at all three sites** (the R1 8-K12B
  candidate, the own registration, the 8-K12B search). The replay changes no row (the two calendar-day sites take
  `max(filed, not_before)` with the 8-K12B's filing date, so a weekend day + 1 matters only when that filing came
  earlier).
- **The declared rows, all three classes checked** (the replay against `accepted_out`):
  - published only when confirmed: CNB 2009 (BBG000BF2JS9) and IMB 2008 (BBG000BLY636) lose their contract
    `last_trade_date`; their delistings.csv day, source `ex99_notice` and flag stay. Cascades: their contract
    `price_date` and `value_formula` follow the published date ("otc_print(?, from ?)"), and their four price
    requests (`last_close` and `otc_print`) go, since the requests are made only for a published date.
  - the clock-time reading: SPNV 2020 (CIK886835-COMMON) is dated 2020-09-17 from `8k_301`, its notice's
    unconfirmed day agreeing, and loses `last_trade_date_unconfirmed` in delistings.csv, review.csv and uncertain.csv
    (its ending stays uncertain on `resolved_from_continued_filings`); review_summary's
    `last_trade_date_unconfirmed` row 54 to 53 rows, 33 to 32 in review. Its contract row is unchanged (it was
    published already). Across the cache the new reading changes three texts (the old and new reader compared on
    1,556 cached texts that mention a suspension): SPNV's; Panera 2017's "9:00 am EST on July 18, 2017" (July 17) and
    General Cable 2018's "9:00 a.m. EST on June 6, 2018" (June 5), both before the open and both rows already dated
    by MIDAS: no row moves.
  - the trading-day first day: no row.
  - scorecard.json: R2.6.distress_date_flagged 43 to 42 (SPNV), and D.mismatches 121 to 122, D.cases_matching 284 to
    283, D.mismatches.price_date 7 to 8: CNB's truth row still scores `price_date` 2009-08-18.
- **CNB's price date goes blank with its published date, and the truth row needs the second cell of the IMB
  ruling.** Under the ruling, publishing the day after an unconfirmed day publishes that day. IMB's truth row, made
  under the operator's 2026-10-03 ruling, already reads `*` for both `last_trade_date` and `price_date`; the step 4
  ruling applied it to CNB's `last_trade_date` only. Every other contract row without a published date has a blank
  price date, so the price date follows the published date, as before.
  - Alternative: price the value from the exchange-print day even when unconfirmed (the old publish rule kept as a
    second predicate for the price date and the requests). CNB's D value would not move.
  - Cost if wrong: the two predicates this step removed would come back, and price_requests.csv would carry a last
    trade date the contract does not publish. With CNB's `price_date` set to `*` (a data change for the controller,
    with a change-log row, as 37e50dc), every D value equals the reference's.
- **CONTEXT.md gains "Last trade date"**, the concept the module is named after: where the day comes from, when it
  is confirmed and published, and the anchor and end days.
- **Tests.** tests/test_last_trade.py tests the module at its interface: 32 tests added (the clock-time reader, the
  derived facts and their row reading, the anchor and end days, the first day, the handoff rule, 9c's re-dating,
  the group's windows, the MIDAS and halt confirmations through fake adapters, rule 3's MIDAS bound and halt drop,
  rule 4's closing day, floor and refusals, the fallback, the tenure bound and the rows' last day). 18 deleted once
  covered: stage 9c's six private-name tests (test_pipeline.py), seven finder dating tests (test_delistings.py: the
  MIDAS window, the unconfirmed involuntary notice, every ticker of the window, the two halt-feed failures, the
  fallback's 8-K window, rule 4 under (b)), test_ticker_taken.py's four (moved, not missing: the tenure bound
  already had these unit tests of `pipeline._ticker_taken`; they now test `last_trade.ticker_taken` and
  `OwnTrading.taken`, and two new tests reach the bound through `Dating`, MIDAS's and a halt's), verdict's
  published-date test; the successor-anchor test now tests `Delisting.anchor`. The stage-5b double gained an
  `anchor`. Suite: 3165 passed, 45 xfailed (step 3: 3147).
- **Controller ruling after the step: CNB 2009's truth `price_date` is not scored either.** The contract's price date
  is the session after the published last trade, so it goes blank with it. The truth row still scored 2009-08-18,
  which made `D.mismatches` 121 to 122. IMB 2008's row, under the same ruling, has `*` for both dates. CNB's
  `price_date` becomes `*`, with a change-log row. Recomputed on step 4's replay, every `D` value equals the reference
  (121 mismatches, 284 cases matching).
  - Alternative: publish a price date for an unconfirmed last trade, which brings back the second predicate.
  - Cost if wrong: the truth set no longer checks CNB's price date. CNB and IMB also lose their `last_close` and
    `otc_print` price requests, so a caller cannot answer an OTC print for them; their dlret stays the Shumway fill.

### Step 5: history owns where a security's history ends

- **The module is history.py, grown; its interface is one class, `Histories`, plus `observation_map_rows`.** The
  caller passes the observed securities, their sightings, their CUSIPs, the fails index, one `Ending` per delisting,
  the listed-today answers, the securities the run adds and an `exchange_today(security, ticker)` adapter. It
  answers `going_on`, `end(sec_id)` (a `SecurityEnd`: the day, whether it is a confirmed last trade, whether the
  security is listed today), `ticker_rows` and `cusip_rows`. `observation_map_rows(eras, sec_id_of, issuer_cik_of,
  history, conflicts)` reads the history itself, not the 5-tuple spread over ten parameters.
  - Alternative: a free function returning a frozen answer, or a new module beside history.py.
  - Cost if wrong: one class with four answers. A function would have to build the ranges on stage 9b's call too,
    where only `going_on` is read.
- **The ending summary is `history.Ending`, built by `Delisting.ending`, next to `Delisting`.** It carries the key,
  the `LastTrade` itself, the bucket, the successor and the exchange. So "confirmed" is `LastTrade.confirmed` and the
  end is `last_trade.end_day`, step 4's definitions, read in one place; no flag token is tested. history imports no
  `Delisting` and no pipeline helper; delistings.py imports `Ending` from history.
  - Alternative: a summary of precomputed scalars (the end day, a confirmed bool).
  - Cost if wrong: history imports last_trade, a pure reader module. Scalars would copy step 4's definitions into
    the builder, where they could drift.
- **The AON 2012 rule needs nothing more than the summaries.** "A security with an ending that ends it whose ticker
  a successor took is not listed today" reads the final ending and the successor starts, both computed inside.
- **Two calls of the one interface, with the reason in one comment in `_run`.** Stage 9b's first step reads
  `going_on` over stage 9's delistings, because `mark_going_on` must run before `apply_handoffs`. The handoff stage
  then creates continuations (AON 2012) and sets successors, and 9c to 9e re-date, add and reclassify endings, so 10b
  and 10c2 read a second history over the final delistings. `pipeline._histories` builds both.
  - Alternative: one history after the handoffs, or 9b's history reused.
  - Cost if wrong: none to output. The first is impossible (the handoffs must see the marked rows); the second
    would clip AON 2012 and the handoffs' new continuations wrongly.
- **The ranges are built lazily (`cached_property`)**, so stage 9b's call builds none and asks EDGAR for no
  exchange. The adapter is a constructor argument for the same reason.
  - Alternative: a `rows(exchange_today)` method.
  - Cost if wrong: none; the observation map would then need the rows passed back in beside the history.
- **The ticker-takeover rule keeps its two conditions, both private behind the interface** (`_successor_starts`
  and `_clip_at_takeovers`).
  - They select different pairs. The successor starts need an ending of S whose successor X is first sighted under
    the ticker in the window, and they bound S's own sightings, CUSIP rows, continued trading and listing: AON 2012's
    old CUSIP keeps being sighted under AON after Aon plc took it. The 5h clip needs no ending: any security's first
    day inside S's built range, S last sighted under the ticker before it, and the range not S's end: MSG 2015's
    new MSG is no successor of the old line.
  - Neither can replace the other without changing rows. Measured with two whole replays and the suite, each with
    one condition switched off:
    - the 5h clip alone (no successor starts): the replay is SAME, but five tests fail, among them the whole-run
      AON 2012 handoff run (`test_a_handoff_continuation_clips_the_old_line_whose_ticker_the_issuer_still_lists`:
      the old line stays listed, open, and shares HC with the new one). The replay cannot see this rule: its
      listed-today answers are the committed run's open ranges (replay_wave1.py), which already carry the AON rule's
      answer. A live run reads OpenFIGI and EDGAR, where the old line's issuer still lists the ticker.
    - the successor starts alone (no 5h clip): the replay changes four ticker ranges, GOOG 2014 (BBG000BHSKN9),
      GCI 2015 (BBG000BK5DP1), MSG 2015 (BBG000NS03H7) and IACI 2008 (CIK891103-COMMON, to 2012-06-28), each
      overlapping the next holder: four `ticker_shared` rows, their contract history rows, and eleven more uncertain
      verdicts. The MSG 2015 identity test fails too.
  - Alternative: one mechanism, the 5h clip's takeovers fed back as successor starts. That needs the ranges built
    twice (the clip reads the other securities' built ranges), and would bring the AON listed-today rule to MSG-like
    cases: a listed security with a clipped earlier range and an ending would stop being listed.
  - Cost if wrong: two functions in one module, one docstring that says why.
- **The rows of the securities the run adds stay in pipeline (`_history_rows`)**, appended after the takeover clip as
  before. Their listed-today answer is a live OpenFIGI read; history reads only an added successor's first day and
  ticker (`AddedSecurity.span`, `ticker`). The observation map reads the observed securities' rows only, which is
  the same output: every add checks that the security is not an observed one, so an added row maps no observation.
  - Alternative: history takes a second adapter for the added securities' listing.
  - Cost if wrong: `ticker_history.csv` is assembled in two places (the observed ranges, then the added rows).
- **`rewrites.mark_going_on` takes a collection of keys** (`going_on`), not a key-to-bool map: "not in it" covers
  both "ends its security" and "no answer". A key two endings share keeps the old reading (the last one decides),
  because the answer is built as a map first.
  - Alternative: keep the map and have the history answer one.
  - Cost if wrong: none; the step 3 test moved with it.
- **Constants moved with their rule:** `CONTINUATION_MIN_ROWS`/`_DAYS`/`_PRICES`, `CONTINUATION_BUCKETS`,
  `SUCCESSOR_TICKER_LOOKBACK_DAYS`, and `TAKEOVER_DAYS`, the handoff window the successor starts share. It lives in
  history now and handoffs imports it, since handoffs already imports history; the reverse import would be a cycle.
- **`history_rows` and `clip_at_takeovers` became private** (`_security_rows`, `_clip_at_takeovers`); their tests
  moved to the interface. `cusip_sightings` and `filtered_ticker_sightings` stay public: stage 5b, the CUSIP switch
  days and the handoff pair search read them.
- **`SecurityEnd.listed` is a bool.** An unknown listed answer (None) was read as not listed by both its readers.
- **Tests.** tests/test_history.py gains 15 tests at the interface: the WRK/DIS continuation, a cash merger, a
  liquidation's OTC tail, the three unconfirmed endings, a security that is its own successor, the line tickers, the
  last ending that ends the security, AON 2012's and STX 2021's shapes, a sighting before a confirmed last trade,
  the listed-today rule with its window, a listed security that goes on, MWV's other ticker, WRK's own successor,
  and the ranges' exchanges. The 12 observation_map tests, the MSG 2015 clip test (test_identity_cases.py) and the
  `mark_going_on` test (test_rewrites.py) were rewritten at the new interfaces, assertions kept; the one listed
  security with a stale end now gets its listing from the history itself, since the history never answers both.
  19 deleted once covered: the 12 tests of `pipeline._delisting_endings`, `_ends_the_security` and
  `_successor_starts`; 6 whole-run tests that swapped `pipeline.DelistingFinder` only to read ticker_history back
  (the unconfirmed clip, the own-successor transfer, WRK, the bankruptcy tail, no last trade, the unconfirmed
  guess); and test_security_master's `history_rows` test. Kept: the three canned-finder tests that check stage 8's
  acquirer row and stage 9's 8-K12B successor and its first day, and the two AON handoff runs (the handoff stage).
  Suite: 3161 passed, 45 xfailed (step 4: 3165).
- **The gate:** the replay is SAME against `accepted4_out` and refuses no request. pipeline.py: 2226 lines to 2065.
- **Left open: the replay is blind to the listed-today rule.** It takes listed today from the committed run's open
  ranges, so a change to the AON rule (or anything else that decides a security is listed today) shows in no replay
  row. The interface tests and the AON handoff run are the only guard. Step 8 (one run snapshot) or a later replay
  could record stage 5's raw listed answers instead.

### Step 6: a security's identity (stages 1 to 4) behind one interface

- **The module is a new `identity.py`, not a grown security_master.py.** Its interface is `identify(index, clients,
  *, as_of, limit, log, workers, meter) -> Identity`. The era helpers moved into it from security_master
  (`refine_eras` and its split helpers, `era_cusips`, `candidate_cusips`, `era_last_seen`, `era_rows`), so a ticker
  era is built in two places only, `observations.split_eras` and `identity.refine_eras`, both run by `identify`.
  security_master keeps `Security`, `EraResolution`, `Issuer`, `FigiResolver` with its guards, `build_securities`, the
  CUSIP links (`Handoff`, `cusip_handoffs`, `trades_at_switch`) and the review-row builders. Sizes: identity.py 939
  lines, security_master.py 985 to 793, ticker_resolver.py 1319 to 960, pipeline.py 2065 to 1843.
  - Alternative: grow security_master (past 1,400 lines), or put the era helpers in their own `eras.py`.
  - Cost if wrong: one more module. The CUSIP links stay in security_master because `FigiResolver`'s joins read
    them; identity imports them, never the reverse, so there is no cycle.
- **`identify` covers stage 4 too** (each security's CUSIPs over its whole life, their fails rows loaded to the run
  date: `Identity.cusips`). The prompt named `_security_cusips` among the functions to move; it is the last read of
  who a security is before the line follow.
  - Alternative: stop at stage 3 and leave stage 4 in pipeline.
  - Cost if wrong: none to output. `Identity.ftd` is the extended index, so a test that wants stage 1's index alone
    cannot get it through the interface (the MSG ranges case now reads the extended one and still holds).
- **The answer is one dataclass with the facts as typed fields and methods.** Fields: `eras`, `era_by_key`, `ftd`,
  `ftd_lo`, `issuers`, `resolutions`, `securities`, `cusips`, `review`, `tiers`, `rows_decided`. Methods: `tier(era
  key)`, `resolution_source(security)`, `securities_of(resolutions)` and `renames(resolutions)`. pipeline's
  `_resolution_source`, `_era_tier`, `_era_renames`, `_IssuerAnswers` and the `TICKER_ROWS` token check are gone.
  Stage 5's context builder, stage 5 and stage 9d take a `resolution_source` callable, and 10e takes `tier`. Stage 4b
  takes the `Identity` and rebuilds through `securities_of`; 4c, 5b, 10c2 and 10g read `issuers` and `rows_decided`.
  - Alternative: pass the whole `Identity` to every later stage.
  - Cost if wrong: one callable per stage instead of one object. The four real-case harnesses that build a finder
    context (form25, distress, last trade, issuer role) now pass nothing for it; they used to pass an empty
    `_IssuerAnswers`, which gave the same default, "security_master".
- **The era-level passes are `identity.EraIssuers`, public, with their own state.** `check_names` is stage 2b and
  `infer` the second pass. They were moved word for word from `TickerResolver`, with their constants
  (`ERA_MIN_ROWS`, `GUARD_NAME_DAYS`, `RENAME_NEAR_DAYS`, `NAME_IN_FORCE`, `TICKER_ROWS`) and types (`InferredIssuer`,
  `SecondPass`). They read issuers through the run's issuer record. Their state is a per-era failed flag, a per-era
  `ReadWatch` and `degraded`, a set of era keys. The 21 second-pass rule tests and the two `_renamed_from` tests of
  `test_resolver_renamed.py` test the class, as
  step 4's `ticker_taken` stayed public for its unit tests.
  - Alternative: private passes tested only through `identify`. Rejected: the tests hand each case its first-pass
    answers and strip pins era by era, and a whole identity run would refine the eras again over a different fails
    load.
  - Cost if wrong: identity has two public classes besides its era helpers.
- **TickerResolver keeps only the memoized lookup, and imports no security_master, observations or ftd.** Its
  interface, as identity asks it, is `identity.IssuerLookup`: `resolve`, `is_degraded`, `frequency_candidates`,
  `shadow` and `flush`. The new `frequency_candidates(ticker, day) -> (ranked, failed)` gives the second pass's rule B
  the 8-K frequency tier and whether its search failed. It leaves the resolver's own `_transient` as it was, and it
  still goes through `_efts_pre_delist_frequency_ranked`, the patch point of conftest and the tests.
  - Alternative: the passes own the EFTS query.
  - Cost if wrong: one method that saves and restores a flag. Two copies of the query would drift.
- **No capability is probed.** `_name_period_checks`'s `getattr` is gone, so 2b runs for any lookup. `identify` calls
  `resolver.flush()` directly after the first pass. `tests/identity_cases.CommittedLookup` is a second adapter (it
  answers by era from the committed run), so the seam is real. `run()`'s own `_flush_memo` on the way out keeps its
  `getattr`; that is step 11's Clients seam.
  - Cost if wrong: a lookup double must implement five methods.
- **A degraded mark of the era-level passes is the era's, not a memo key's.** Before, `_mark_inferred` put the era's
  memo key (ticker, last sighting, observed name) into the resolver's `_degraded`. That had two side effects.
  - Two eras that shared the key were both flagged.
  - A later lookup that hit that memo entry was treated as resting on a failure. Only the memo persistence of a
    rename built on it could change, and stage 3 is the only reader of `is_degraded`.
  - Now stage 3 flags an era when the lookup's `is_degraded` says so, or when the era is in `EraIssuers.degraded`.
  - Alternative: keep marking memo keys.
  - Cost if wrong: an era that shares another era's memo key, and whose own reads did not fail, is no longer
    flagged. The replay refuses no request and changes no row.
- **The wiring is decided inside, once.**
  - `cusip_handoffs(eras, ftd)` is computed once in `identify` and passed to both `EraIssuers.infer(..., handoffs)`
    and stage 3. Before, the second pass computed it again. The fails index is not extended between the two, so the
    links are the same. `infer` still computes the links when no caller gives them (the rule tests).
  - `foreign_ticker_eras` is given once, to `FigiResolver(foreign=)`. `resolve_many` now guards a foreign era as an
    unconfirmed one itself; before, the caller also had to union it into `unconfirmed=`.
  - Alternative: keep both in the caller.
  - Cost if wrong: a `FigiResolver` caller can no longer give `foreign` without guarding those eras. No caller did.
- **The three era review-row builders stay in security_master** (`detached_review`, `ticker_unconfirmed_review`,
  `observation_conflict_review`). `identify` assembles every identity item in the old order.
  - Alternative: move them into identity.
  - Cost if wrong: `ticker_unconfirmed_review` reads security_master's private confirm window, so moving it would
    have made that window public.
- **CONTEXT.md gains "Identity"**, the concept the module is named after: which security an observation is.
- **Tests.**
  - Added: tests/test_identity.py, 9 tests at the interface, one of them moved from test_pipeline (the resolution
    source). They cover an empty run, a placeholder era's issuer, tier and review items, a degraded lookup answer, an
    unreadable issuer's names, an unresolved era, a tier for an era never asked, `securities_of` after a fold, and
    `renames` with its two guards. Also added: test_resolver_renamed's second-pass failed read (the era's own
    `resolution_degraded`, with a healthy control), and test_resolver_efts's `frequency_candidates`.
  - Moved to `identify`: test_resolver_renamed's four tests of pipeline privates (each era's own name; the second
    pass used, flagged and not saved; the CUSIP-handoff wiring, now `test_the_identity_stage_wires_cusip_handoffs_
    into_the_figi_stage`; the disagreement row).
  - The disagreement test now asserts both eras' rows. Run whole, rule C also flags LSTR@2012; before, the test
    built LSTR@2008's disagreement by hand.
  - The identity harness (tests/identity_cases.py) runs `identify` with `CommittedLookup` in place of the
    SimpleNamespace resolver fake. `stage3` and `name_checks` keep their names, which the fixture builder calls,
    and name checks also assert `rows_decided`.
  - The 21 second-pass rule tests call `EraIssuers.infer`. One passes its links as `handoffs=` instead of
    monkeypatching `ticker_resolver.cusip_handoffs`.
  - Gone from the tests, counted at 08259f8: 12 `_IssuerAnswers` builds, 4 `_resolve_securities`, 2
    `_resolve_issuers` and 1 `_refine` calls, and the `_era_renames` and `_resolution_source` calls. Stage 4b's
    tests build an `Identity`.
  - Suite: 3171 passed, 45 xfailed (step 5: 3161).
- **The gate:** the replay is SAME against `accepted4_out` and refuses no request; its log equals the reference's line for
  line, apart from the SEC meters (the name checks, the second pass's 76 answers, every FIGI handoff and withdrawal).

### Step 7a: the line follow owns its rounds

- **The interface is one entry, `line_follow.follow_lines(identity, clients, *, as_of, log, meter) -> Lines`.** It
  takes the whole `Identity`, as `identify` takes the observations, and the run's clients through `LineSources`
  (the issuer record, the EDGAR client for its full-text search, OpenFIGI, the fails files). `Lines` holds the
  securities, resolutions and CUSIPs after the follow, `renames`, `successors` and `review`. Stage 4b in `_run` is
  one call. `Identity` is imported for annotations only, so line_follow loads no identity or resolver module.
  - Alternative: pass the seven facts the stage reads (securities, resolutions, CUSIPs, fails index, its first day,
    review items, the rebuild after a fold) one by one.
  - Cost if wrong: a caller with no `Identity` must build one. The stage's tests already did since step 6.
- **`Lines.review` holds the review items of stages 1 to 4b**, the identity's first, a folded placeholder's moved to
  its FIGI line and its `no_figi` dropped. That rule is a consequence of the fold, so it moved from `_run` into the
  stage. `_run` reads `list(lines.review)`.
  - Alternative: the stage's own items only, merged in `_run` as before.
  - Cost if wrong: `review` is more than the stage's own items. The field's docstring says so, and the order is the
    one `_run` built.
- **`Lines.cusips`, not `sec_cusips`**, as `Identity.cusips` names the same fact.
- **The rule functions stay public; only `follow_lines` calls them in a run.** They are `candidate_steps`,
  `corroborate`, `decide`, `line_end`, `other_registrant`, `name_on`, `text_symbols` and `eightks_near`. Their tests
  are 453 lines of synthetic rows (test_line_follow.py), the real-case harness and the fixture builder. The
  precedent is step 6's `EraIssuers` and step 4's `ticker_taken`. The stage's own rules are private: `_Reads`,
  `_fold`, `_today_holder_fold`, `_cusip_holders`.
  - pipeline imports 5 names from line_follow (it imported 23): `follow_lines`, `LineSuccessor` (stage 9's links)
    and three readers.
  - Alternative: underscore the rules and test them only through the entry.
  - Cost if wrong: a second caller could call a rule outside the stage. None does.
- **Stage 9 keeps reading `is_line_symbol`, `text_cusips` and `composites` from line_follow.**
  `_own_registration_link` applies the same R2 reading to the new CUSIP of a same-CIK 8-K12B. Moving the readers
  would split the line follow's reading of a new CUSIP from its rule.
  - Alternative: `composites` to figi_resolution, `is_line_symbol` to ftd, `text_cusips` to evidence.
  - Cost if wrong: stage 9 imports stage 4b's module for three readers. Step 13 (one leaf module for ticker
    spelling) can take `is_line_symbol`.
- **Every EDGAR read of the stage goes through `_Reads`, one private class.**
  - The issuers' submissions, filing lists and 8-K texts go through the run's issuer record, as step 2 left them.
  - The stage-wide watch is the record's `ReadWatch`. The per-step watch is now one too (`issuers.watch()`), not a
    `DegradedWatch`. It trips on every SEC read of the thread that a `DegradedWatch` saw, and on the step's issuer
    reads, which `degraded(cik)` already reported. So no row changes.
  - **Listed today reads the issuer's profile** (`listing_status.lists_on_major_exchange`, split out of
    `edgar_lists`), not `edgar_lists(edgar, cik)` on the client. It is the same copy: a remembered profile is the
    client's cached copy's (step 2), and corroborate had just read it. It was the stage's one EDGAR read with no
    failure policy: with no cached copy and the network down, it stopped the run with a `ConnectionError`. That
    needs a step within `RECENT_DAYS` of the run date with no periodic report and no own successor registration.
    Now the read is unknown, the CIK is degraded, and the step is refused `merged_out` with a `resolution_degraded`
    row.
  - **The other-registrant search and its filer's listing stay on the EDGAR client**, inside `other_registrant`. A
    failure there is `READ_FAILED`: the step is refused `read_failed` and the security's CIK is degraded. Routing
    the filer's listing through the record would log the filer's CIK, not the security's. In an outage it would
    then refuse the step `other_registrant`, not `read_failed`.
  - Alternative: keep `edgar_lists` on the client for listed today.
  - Cost if wrong: none in the replay. In an outage, a run that stopped now completes with the row flagged.
- **`successor_query` moved to a new module, `filing_search.py`**, which imports nothing of the package.
  `successors`, `handoffs`, `line_follow`, pipeline, the prefetch test and the fixture builder import it there.
  The successors string `SUCCESSOR_FORMS` moved with it. Its window constants are named `SEARCH_BEFORE_DAYS` and
  `SEARCH_AFTER_DAYS`, since successors already names another window `SUCCESSOR_BEFORE_DAYS`.
  - The other spellings of the successor forms are left as they are, for step 13. They are line_follow's and
    end_of_era's frozensets, and the tuples of handoffs and continuation_evidence, which those modules match with
    `startswith`.
  - Alternative: edgar.py's search arguments.
  - Cost if wrong: one 20-line module. edgar.py is the client; what a stage asks of it is not its concern.
- **degraded.py imports `Delisting` for annotations only.** line_follow builds its `resolution_degraded` items with
  `degraded_item`, and degraded.py imported delistings, which imports the classifier. line_follow's import closure is
  now 25 modules, none of them a stage module: no successors, delistings, classifier, history or rewrites. Before,
  it loaded successors and the 37 modules behind it.
  - Alternative: build the item in line_follow by hand.
  - Cost if wrong: none. degraded's functions read a delisting's attributes only.
- **The tally line and the meter move with the stage**, as `identify` logs and meters its own. The run log is the
  reference's, line for line. The text sources' 30 days became a named constant, `TEXT_SOURCE_DAYS`.
- **The real-case harness is kept on the rules and pointed at the entry too.**
  - The rule-level cases stay. They express what the entry cannot: a case whose OpenFIGI answer the fixture lacks
    stops at corroborate, and the two-step cases and SBGI's search hit are handed explicit inputs.
  - Added: every case runs through `follow_lines` over an identity built from the fixture. The holders of the
    cases' next CUSIPs are in it but not followed, since their issuer is unknown there. The test asserts each case's
    first answer: the same step, refusal and decision, with DHC's unanswered CUSIP refused `unsettled`. The three
    no-step cases take no step.
  - Alternative: only one of the two.
  - Cost if wrong: the fixture is replayed twice, about a second.
- **Tests.**
  - tests/test_line_stage.py was rewritten at the entry. Every line's steps come from fails rows built there, its
    filings from an EDGAR double and its composites from an OpenFIGI double. No `pipeline.candidate_steps`,
    `pipeline.line_end` or `pipeline.corroborate` monkeypatching is left.
  - Kept, with every assertion: the 13 tests, including those of 8a3ffd9 and e80be70. They cover the rounds, any
    input order, the CUSIP and the composite held per round, the other-issuer refusal, the OpenFIGI and EDGAR
    refusals, the stale and failed reads, the no-step degraded rows, the text sources' filter before the cap, and the
    fold chain.
  - The fold chain is now reached through the stage: a placeholder folds into a ticker-tier FIGI line in round 1,
    and that line today-holder-folds in round 2. Both renames point at the last FIGI. Its CUSIP assertion is now
    the whole line's (the last FIGI holds every CUSIP). The hand-built state's leftover entry for the first
    placeholder cannot arise through the stage.
  - test_identity_rules' two private `_today_holder_fold` tests (4 assertions) became the CRC fold and its three
    guards at the entry.
  - Added: a folded placeholder's items moving, a failed other-registrant search (`read_failed`, degraded), and a
    step whose search answered from a stale copy. The last one is the only test that fails when the per-step watch
    is removed; before it, a mutation run found that gap.
  - Mutation runs (each rule switched off in a copy of the source) fail at least one stage test each: the two
    holders, the cap order, the today-holder fold, the rename chain, the no-step degraded rows, the review move,
    the per-step watch, the search-failure set, `MAX_ROUNDS`, and the rebuild after a fold.
  - Deleted: the 13 monkeypatched or private-name tests of test_line_stage and the 2 of test_identity_rules.
  - Suite: 3193 passed, 45 xfailed (step 6: 3171). The new tests are 20 in test_line_stage (7 more than before)
    and 17 in the harness, less the 2 removed.
- **The gate:** the replay is SAME against `accepted4_out` and refuses no request. Its log equals step 6's line for
  line, the line follow's tally and meter included.
- **pipeline.py: 1843 lines to 1617.** line_follow.py: 424 to 713.
- **Left open.**
  - A fold of a fold in one round, in the other order, is not collapsed. A FIGI line that today-holder-folds into
    X earlier in a round than a placeholder that folds into that FIGI line leaves `{line: X, placeholder: line}`.
    The rename loop only follows renames made before the fold. It needs a placeholder whose new CUSIP names a
    ticker-tier line of its issuer that itself steps in the same round, and no case of the run does. It was moved
    as it was; no defect is declared.
  - `follow_lines` probes `getattr(edgar, "full_text_search", None)` for the search, as `_follow_lines` did. That
    is step 11's capability seam.

### Step 7b: one own-share reading per ending (R1)

- **The module is `own_shares.py`, beside `exchange_terms`.** `exchange_terms` stays the pure statement reader: it
  lost `read_texts`, `registrant_names` and `class_of` (the reading's choices, now `own_shares`') and gained the
  statement's own judgments: `one_share_no_cash` (R1's shape), `split_factor`, `OwnExchange.split` and
  `OwnExchange.stake_changed` (rule 6). Its import closure lost `evidence` and `edgar`, so the verdict reads its split
  rule from a light leaf.
  - Alternative: the reading inside `exchange_terms`.
  - Cost if wrong: two modules for one concept. The statement reader is 480 lines of regex with its own real-case
    tests; the reading is 300 lines of choices and reads with theirs.
- **The interface.** `Reader(edgar, issuers).ending(cik, share_class=, name=, day=, form25=)` gives an `OwnShares`,
  lazy: nothing is read until a caller asks, and every answer is kept. It answers `statement`,
  `registrant_statement`, `one_for_one`, `consideration`, `names_target`, `target_issuer`, `survived(deal_days)`,
  `texts`, `filings`, `text_of` and `degraded`. `of(d, reader, security)` gives a stage the delisting's reading. The
  pure functions are the name tie (`names_target`), the new-issuer rule (`new_issuer`, `NEW_ISSUER_DAYS`), the roles
  (`other_role`), `registrant_names` and `class_of`. A new CONTEXT.md term, **Own-share reading**, names it.
- **Measured before choosing: one instrumented replay logged every reading at the six sites**, with its inputs and
  answer: rule 6 (11), stage 5's R1 (10), rule 1 (71), 8b (63), 9 (16) and 9g (58), on 179 endings. 46 endings were
  read by two or more sites, and for 19 the classification's anchor and the delisting's anchor differ. Each reading
  was then read again under candidate inputs, and each site's decision compared (scratchpad `s7b_analyze.py`).
  - **The class: one choice gives each caller the same answer.** The security's share class (its FIGI's) gives all
    229 answers. The name's class, which the classifier and 9g used, changes 4 of 8b's (SBGI, WWE: truncated names
    lose "CLASS A"). 58 securities of the run have a share class their name does not give.
  - **The days: one choice gives each caller the same answer.** The ending's anchor alone (`Delisting.anchor`: the
    last trade, worked out or not, else the Form 25's filing date) gives all 229. Adding the anchor 8-K's day (8b and
    9 read it) or the Form 25's filing day (stage 5's R1 read it) changes no answer. The Form 25 day and the
    classification's anchor need texts never read (stage 9's Yahoo 2017; three rule-1 readings): new requests in a
    live run, so they are not the choice.
  - **Rule 1 keeps its deal days.** Without the 5.01 and 2.01 8-Ks' windows one of its 71 answers changes; reading
    them for every site changes 5 of 9g's answers and needs 4 new texts. So `survived(deal_days)` reads them on top
    of the reading's own 8-Ks, and is not the statement the finder carries.
  - **The notice: no one choice keeps every answer.** Reading the Form 25 notice everywhere gives 9g a doubt for
    Actavis 2013 (`ratio:0.16`, the notice's sentence about Warner Chilcott's shares): its verdict would turn
    uncertain. Leaving it out everywhere changes 7 of 8b's answers. So one read keeps two statements: `statement`
    (the 8-Ks and the notice) and `registrant_statement` (the 8-Ks alone), which 9g asks, as its reading is "what the
    registrant's own filings say".
  - Alternative: keep each caller's days and class behind the interface.
  - Cost if wrong: an R1 statement only an anchor 8-K far from the anchor holds is missed (none in the run), and
    stage 5 and 9g now read the FIGI class. Each is a reviewable row, not a silent value.
- **Once per ending, carried on the delisting.** The finder makes the reading (at the ending's anchor; at the last
  sighting for an ending with no Form 25, whose last trade is dated after classification) and hands it to the
  classifier (`classify_event(..., own_shares=)`). The delisting keeps it when its statement was read (`stated`:
  rule 6 or R1), so the ratio the classification decided on is the one 9g and the verdict read (CHTR 2016). A stage
  that asks first makes it at the delisting's anchor (`of`). Without a reading handed in (`classify_ticker`, tests),
  the classifier makes one at its observed date, of the class its name gives, with the notice of the Form 25 it is
  anchored on.
  - Alternatives: the reading on `DelistRecord` (rejected: step 3 kept provenance off the published record); a
    reader memo keyed by delisting (rejected: the warm finder's classifier copies would share it, and a reading a
    warm thread made over a failed read would be reused by the sequential pass, so output would depend on the worker
    count); always carrying the finder's reading (rejected: a fallback's last-sighting anchor would make stage 9 read
    Yahoo 2017's at the wrong day and fetch a new text).
  - Cost if wrong: a fallback ending the classifier read keeps a reading at its last sighting. Six endings of the
    run are such (rule 6: SIRI 2024, CHTR 2016, NRF 2014 and three more); on each, the measured answers of 9g and
    stage 9 at the last sighting equal those at the delisting's later anchor.
- **A carried reading carries its failures (`OwnShares.degraded`).** 8b and 9 flag and 9g reports a reading that
  rested on a failed or stale read, now or when it was made. Before, each stage read again under its own watch.
  - Cost if wrong: none in the replay. In an outage, stage 5's failed read reaches 8b as degraded (the merger is
    kept, flagged) instead of being read again.
- **Rule 6 moved into the resolver.** Branch 2 reads `EraSignals.successor_terms` (the reading's statement, read only
  where branch 2 decides: `end_of_era.registers_successor`) and answers `successor_merger` when its stake changed.
  The classifier no longer builds an `EraVerdict` by hand. The reason is byte-identical: "Successor registration
  <form> <day>: each share became ...".
- **The resolver's text answers are typed.** `end_of_era.Filed(form, day)` replaces the "8-K <date>" strings (the
  deficiency, bankruptcy and liquidation 8-Ks, and the successor, merger and Form 25 filings). An 8-K item's first
  filing is a date. `str(Filed)` prints the old text, and the bankruptcy-before-sale test compares days, not a slice.
- **One split factor rule: `exchange_terms.split_factor`, n or 1/n for a whole n up to `SPLIT_FACTOR_MAX` (100), 1
  included.** Rule 6 and the verdict's `ratio_doubt` read it. `verdict_rules.reverse_split` (no upper bound) is gone.
  - The rows a bound changes: none. The run's readings state 0, 0.1, 0.16, 0.9042, 1 and 2. A 1/150 consolidation
    is now a doubt for the verdict, as it already was a merger for rule 6.
- **One R1 shape: `one_share_no_cash(ratio, cash)`** (a ratio within 1e-9 of one, no cash). The statement's
  `one_for_one`, 8b's terms check and 9b's `MergerValues.reconciled` read it. The latter two compared `== 1.0`. 8b
  sets a special dividend aside first (`OwnShares.consideration`).
- **One name tie, one new-issuer rule.** `own_shares.names_target` replaces `successors._named` (which pipeline
  imported by its private name), the classifier's own scan and `continuation_evidence._target_is_known`.
  `new_issuer(first_filed, day)` replaces the three `NEW_ISSUER_DAYS` checks. `OwnShares.target_issuer` is stage 5's
  R1 condition (`classifier._names_new_issuer`). It reads EDGAR's ticker file's candidates by title only, as before
  (its tickers are not passed: that would widen the tie), and their first filing through the issuer record, not the
  client.
- **The import cycle is gone.** The classifier imports `own_shares`, which imports no stage module. `successors`
  imports `own_shares` and `delistings`, and nothing imports `successors` from the classification side. Importing the
  classifier no longer loads `successors` or `delistings`.
- **Stage 9g's selection stays on the row's reason** (`needs_filing`, `needs_doubt_check`: step 3's leftover).
  - The verdict selects the same continuations from the same row text. A typed selection in 9g would make them two
    readings of one fact.
  - The reason prefixes are end_of_era's protocol (step 3), so the strings have one writer.
  - 9g no longer parses the successor registration's date out of the reason: its reading is at the anchor. Measured
    on 58 readings, no answer changes. `verdict_rules.successor_filing_date` is gone.
  - Alternative: a typed selection from `Delisting.rewrites` and the classifier's branch.
  - Cost if wrong: a rewrite that replaced a continuation's reason would hide it from 9g. No rule replaces a
    transfer's reason.
- **Stage 9b's rule-6 conflict stays on the classifier's recorded branch** (`evidence["end_of_era"] ==
  "successor_merger"`). The carried reading's `stake_changed` also holds for mergers other rules decided (8b reads
  every merger with one-share terms), so asking it there would add conflicts.
- **Step 1's leftover: 8b's `read_terms` still reads both legs of an election that states no package.** An election
  whose legs are one share and cash is no R1 continuation either way (its cash is cash), and one with no cash leg is
  no election. No row changes either way, so the reading the gate never published stays 8b's.
- **The classifier's reading reads the filing list and names through its issuer record**, as the pipeline's did.
  It is the same copy. A failed read is unknown, not an exception: that changes only an outage, and the finder's
  watch still flags the row.
- **Stage 9's own-registration link keeps its `texts` parameter** (the reading's `texts`), so sub-plan 5h's OKE tests
  call it as they did. `_r1_successor` takes the reading; `successor_by_terms` takes its statement, so its tests build
  statements, not readings.
- **Tests.**
  - Added: tests/test_own_shares.py, 25 at the interface (the texts and their order, laziness, the names, the
    class, SBGI's truncated name, the notice left out of the registrant's statement, a failed read, the name tie, the
    new issuer, whom the target names, a special dividend, rule 1's deal 8-Ks, carrying, and the issuer-role cases
    CHTR, SIRI, TW and OKE through the finder and stages 8b and 9); 3 in test_end_of_era (rule 6 in branch 2); 4 in
    test_continuation_evidence (no text read without a confirming form, a carried reading, the notice, a carried
    degraded reading).
  - Moved: the classifier's `_names_new_issuer` test (now `test_whom_the_target_names`), and exchange_terms'
    `registrant_names`, `class_of` and `read_texts` tests (now the reading's).
  - Rewritten at the interface: 8b's private `_r1_successor` test (now a stage test over a real reading); the 5f
    `_split_factor` test (now `split_factor` and `stake_changed`); verdict_rules' `reverse_split` assertion (now
    `ratio_doubt`); test_continuation_evidence and the 5i verdict harness (tests/verdict_cases.py and its builder)
    over the reading at the row's anchor (`last_trade.anchor_day`, `of_row`); test_end_of_era's signals typed. The
    issuer-role harness gained `later` (stages 8b and 9 over given delistings).
  - Suite: 3222 passed, 45 xfailed (step 7a: 3193).
- **The gate:** the replay is SAME against `accepted4_out`; it refuses no request and reads no uncached text, and its
  log equals step 7a's line for line.
- **pipeline.py: 1617 lines to 1613; classifier.py: 1102 to 1036.** own_shares.py is 303 lines.

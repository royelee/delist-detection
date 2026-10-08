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
| 8 | One run snapshot; one reading of a delistings row (review 9) | | done |
| 9 | The truth set and the loop round as two modules (review 10) | a loop-added ending_moved case's examined day | done |
| 10 | dlret decides the value rule once (small) | plan_stock's confidence | done |
| 11 | The Clients seam declares capabilities (small) | | done |
| 12 | The fails index owns its loading (small) | | done |
| 13 | One leaf module for ticker and share-class spelling (small) | | done |
| 14 | The finder builds its own trading record (small) | | done |
| 15 | One truth-case type (speculative; reduced: no re-key) | | done |
| 16 | Package layout: concept subpackages and a lazy package root (review 11) | | done |

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

### Step 8a: one reading of a delistings.csv row, below both layers

- **The module is `exit_kind.py`, grown into the row vocabulary, not a new file.** It imports nothing of the package.
  It holds seven sections: the contract's view (`ending_fields`, `is_distress`), real endings (`is_real_ending`,
  `is_continuation`, `last_endings`), flags, the evidence a reason names, `VALUE_RULES`, the last trade's facts, and
  stage 9g's answer. Producers write through it: end_of_era, handoffs, the finder, rewrites, the payout gate,
  last_trade, stage 9g, and the classifier's and stages 8b/9's continuation reasons. Readers read through it: the
  verdict, scorecard, contract, payout_rule, lifecycle, audit, truth, diagnosis_truth, regression, diagnosis_loop
  and review_triage.
  - Alternative: a new `rows.py`, with exit_kind kept as the contract's view only.
  - Cost if wrong: the module is named after its first section, not the whole. Step 16 (the layout) can rename it.
    Nothing outside the package imports it by name.
- **Each security's last ending: one definition, `last_endings`, the contract's sort.** Before the move I compared
  the three readings (scratchpad `s8a/last_agree.py`): the contract's sort, the verdict's `max` with its `settled`
  pick, and the lifecycle's `real[-1]` over its sorted list. They agreed on `accepted4_out`'s 998 rows and on 20,000
  random tables with ties and went-on rows: 0 disagreements. Of two endings on one day, all three keep the later
  row.
  - The verdict's `earlier_ending` and `settled` now read it.
  - The lifecycle walk follows it; its `_endings` map is gone.
  - The diagnosis judge and the loop's context read it from exit_kind, not contract.
- **Flags: one parse.** `flag_tokens`, `flag_name`, `flag_detail` and `flag_names` replace seven parses: lifecycle's
  `flag_names`, verdict_rules' `tokens` and its `partition`s, review_triage's `_tokens` and `flag_name`,
  payout_rule's `startswith`, rewrites' `_flag_name`, `last_trade.of_row`'s split and `pipeline._triage`'s. A blank,
  None or missing cell has no tokens.
  - payout_rule's `startswith("terms_gate_skipped")` became a name test. It answers the same on every token the
    library writes: no catalog flag has a longer name with that prefix.
- **The gate set is defined once, `GATE_FLAGS`.** It holds `PAYOUT_GATE_FAILED`, `LLM_GATE_FAILED`,
  `TERMS_GATE_FAILED` and `TERMS_GATE_SKIPPED`.
  - The payout gate builds its prefixes from them, and its `terms_gate_failed:` f-string too.
  - `rewrites.PAYOUT_FLAGS` is `GATE_FLAGS` and the other four value flags.
  - The verdict's ruling D reads it. `verdict.GATE_FAILED`, the `gates` argument and `verdict_rules.SKIPPED_GATE`
    are gone. This was the 5f review's Important 3: a second copy of the set.
  - The other flag names stay literals with their writers: "resolved_by_current_ticker_map", "no_evidence_default",
    "handoff_continuation" and "member_name_mismatch" in the verdict.
  - Alternative: every catalog flag as a constant here.
  - Cost if wrong: a renamed flag the verdict reads by literal goes unread. Its own tests would show it.
- **The evidence a reason names: each writer sits beside its reader, and the published text is byte-identical.**
  - The continued-filings rule: `CONTINUED`, read by `rests_on_continued_filings`.
  - A relabel: `relabel`, the suffix, read by `resolved_from_continued_filings`.
  - A merger relabel: `change_in_control_reason` and `completed_acquisition_reason`, read by `merger_relabel`.
    `MERGER_RELABELS` is gone, and so is the test that tied its copy of the prefixes to end_of_era's f-strings.
  - A successor registration: `successor_registration_reason` and `continuation_reason`, read by
    `names_successor_registration`. The regex is built from `SUCCESSOR_REGISTRATION`, `CONTINUATION` and
    `SUCCESSOR_FORMS`.
  - A link's note: `successor_note`, moved from rewrites.
  - A timing link: `TIMING_CIK`, written inside `continuation_reason` or `successor_note`, read by
    `linked_by_timing`. The handoff stage's evidence strings (`TIMING_CIK`, `TIMING_CUSIP`) are the vocabulary's
    too, and its `timing:cusip` conflict test reads the constant.
  - Who writes through them: end_of_era (all eight branch reasons), handoffs (the continuation reason and the note),
    the classifier's and 8b's R1 reasons, and the line follow's (all "Continuation (...)").
  - Readers: the finder (5h's no-CUSIP guard), stage 9g's selection, the verdict and the scorecard.
  - `SUCCESSOR_FORMS` is defined once for end_of_era's window, handoffs' own-continuation filter
    (`SUCCESSOR_FORMS_12G3` is gone), 9g's confirming forms and the reader. line_follow's set and filing_search's
    query string are left alone: neither is reason text.
  - Alternative: keep the constants in end_of_era (step 3) and only move the readers.
  - Cost if wrong: none to output. The tests pin the exact old strings, and the replay is SAME.
- **Stage 9g's answer is `exit_kind.ContinuationReading` (was `verdict_rules.Reading`).** It is the verdict's one
  input beside the tables. run_manifest.json records it, and step 8b's snapshot will carry it.
  - Alternative: keep it with its producer, continuation_evidence. Rejected: the verdict would import own_shares,
    which loads edgar.
  - Alternative: the verdict owns it, as payout_rule owns `MergerInputs`, and 9g returns plain values. Rejected:
    two types for one answer.
  - Renamed, because a bare `Reading` beside `of_row` reads as a row reading.
- **`ratio_doubt` moved to continuation_evidence, and `successor_filing_reason` became
  `exit_kind.names_successor_registration`.** `ratio_doubt` writes the doubt text the verdict publishes verbatim,
  and 9g is its one caller. continuation_evidence now imports no measurement module, and neither does the pipeline
  through it.
- **verdict_rules is folded into verdict.**
  - It had one real caller, the verdict.
  - Its docstring and the verdict's described the same reasons.
  - The gate set had to be passed across it as an argument: the split was by sub-plan (5i), not by concept.
  - The rulings are private helpers, lettered A to F in the verdict's docstring. verdict.py went from 301 to 473
    lines.
  - tests/test_verdict_rules.py became tests/test_verdict_rulings.py, through `decide`. Its five tests that called
    `unpriced_gate` now read decide's `assumed_par_after_failed_gate`, through a helper that first asserts the row is
    assumed par with a gate flag. Given that, the reason is raised exactly when the gate is not unpriced, so no
    assertion weakened.
  - Alternative: keep verdict_rules as "the 5i rulings".
  - Cost if wrong: a 470-line module. It still has one interface, `decide`.
- **The last trade's facts moved to exit_kind; last_trade imports them.** They are `LastTrade` (with `confirmed`,
  `worked_out` and `publishable`), the sources and flags, `end_day`, `effective_date` (from form25, as
  `FORM25_EFFECTIVE_DAYS`), `cites_form25`, and the row reading (`of_row`, `effective_of`, `published`).
  - New: `end_day_of(row)`, step 4's leftover. `lifecycle.end_of` and the verdict's stale-seed window
    (`_within_days`) both read the row's end day through it.
  - `cites_form25` is the one test of "the row cites a Form 25", for `effective_of` and the verdict's
    `_own_form25`.
  - The classification callers keep importing `LastTrade` and the constants from last_trade, which binds them for
    its own use. history and the pipeline import `end_day` from exit_kind.
  - The contract imports `published` from exit_kind, and never from the verdict.
  - Alternative: keep `LastTrade` in last_trade and give exit_kind a row-side type of its own. Rejected: two types
    and two `publishable`s for one fact.
  - Cost if wrong: the row vocabulary carries `halt_feed_failed`, an in-memory field that no row has.
- **`VALUE_RULES` moved to exit_kind.** The diagnosis judge and the scorecard no longer import payout_rule.
- **The contract loads no client, so the regression report keeps `contract.id_change_rows`.**
  - `DistressTerms` moved from distress.py to payout_rule, beside `MergerInputs`. Both are the payout rule's inputs
    beyond the row: stage 9e builds one, stage 8 the other.
  - payout_rule's `MergerTerms` import is type-only.
  - Before, contract imported distress, which loads ftd, sec_http and edgar.
  - Alternative: move `id_change_rows` to a new module, and leave the contract loading the clients.
  - Cost if wrong: stage 9e builds a payout_rule type. Three tests and price_requests changed one import path.
- **The import pin: tests/test_import_closure.py.**
  - Each measurement module (lifecycle, verdict, scorecard, truth, truth_build, diagnosis_truth, regression,
    diagnosis_loop, truth_update, audit), the contract modules (contract, payout_rule) and exit_kind are imported in
    a fresh interpreter, which must load none of the eight network clients.
  - exit_kind loads no other package module.
  - Ten classification modules load no measurement module.
  - Measured before and after (package modules loaded, the root left out): scorecard 43 to 8, diagnosis_truth 42 to
    6, regression 43 to 13, diagnosis_loop 44 to 14, truth_update 45 to 15, audit 44 to 9, contract 40 to 10,
    payout_rule 32 to 5, verdict 26 to 5. continuation_evidence no longer loads lifecycle or verdict_rules.
  - **The one known exception is the package root**, step 16's lazy root. `__init__.py` imports edgar,
    ticker_resolver and the classifier eagerly, so every import through it loads the clients. The test leaves the
    root's own imports out (a bare package module). A strict xfail (`test_the_package_root_loads_no_client`) flips
    when step 16 lands.
  - No listed module waits on an 8b move.
- **Left as they were.**
  - The verdict's `_doubted_ending` reads R1's shape at 1e-6 over the row's ratio string, not
    `exchange_terms.one_share_no_cash` (1e-9). Step 7b's sites did not include it. Changing the bound is a behaviour
    question, not a vocabulary one.
  - The audit's import of scorecard (`CENSUS_GROUPS`, `Window`) and the scorecard's of verdict (the uncertain.csv
    kinds) are inside measurement and load no client. They belong to steps 8b and 9.
- **Tests.**
  - Added: 12 in tests/test_exit_kind.py. Each tests the vocabulary at its interface: the last ending and its tie;
    the verdict, the lifecycle and the contract reading the same last ending; flag tokens; the gate flags the payout
    gate writes; a round trip for each piece of reason text; end_of_era.resolve's and apply_handoffs' own reasons
    read back; the value rules value_fields writes; the effective date and `end_day_of`.
  - Added: tests/test_import_closure.py, 24 cases and one strict xfail.
  - Added: one in test_continuation_evidence, 9g's selection over the vocabulary's text.
  - Moved: the four `LastTrade` facts and row-reading tests, from test_last_trade to test_exit_kind; `ratio_doubt`,
    from the rulings to test_continuation_evidence; the effective-date assertion, from test_form25.
  - Deleted once covered: the MERGER_RELABELS tie test; test_rewrites' `successor_note` test (its assertions are in
    exit_kind's timing round trip); test_continuation_evidence's `successor_filing_reason` test (now the selection
    test and exit_kind's successor-registration round trip).
  - Rewritten through `decide`: five rulings tests.
  - The real-case harness (tests/verdict_cases.py and its fixtures) is unchanged apart from the type's name and
    `of_row`'s module.
  - Suite: 3256 passed, 46 xfailed (step 7b: 3222 passed, 45 xfailed; the new xfail is the package root's).
- **The gate:** the replay of ac5ffbf is SAME against `accepted4_out`. It refuses no request and reads no uncached text,
  and its log equals step 7b's line for line.
- **pipeline.py: 1613 lines to 1617.** The three continuation reasons now go through `continuation_reason`, and
  there are two import lines. exit_kind.py went from 90 to 358 lines, last_trade.py from 756 to 681.

### Step 8b: one run snapshot, read from a folder, a commit or memory

- **The module is `run_snapshot.py`, named after a new domain term ("run snapshot", in CONTEXT.md).** `RunSnapshot`
  holds every table one run wrote and the two manifest fields measurement reads (`as_of`, and stage 9g's readings as
  `continuations`). It replaces `lifecycle.Tables` (both its constructors, `Tables.read` and `pipeline._as_read`),
  regression's `Snapshot` (`read_snapshot`, `snapshot_at`, `_at`, `REQUIRED_COLUMNS`) and the raw reads in scripts
  and tests. It loads no network client (tests/test_import_closure.py lists it first among the measurement modules).
  - Alternative: grow `lifecycle.Tables`. Rejected: the lifecycle walk would hold git and manifest reading, and the
    regression diff and the diagnosis judge read the run without the walk.
- **Three adapters behind one class, a real seam.** `RunSnapshot.read(out_dir)` (a folder), `RunSnapshot.at(repo,
  rev, out_dir)` (`git show` of the folder in commit `rev`; it checks at once that the folder lies inside the repo and
  that `rev` is a commit) and `RunSnapshot.of(tables, as_of=, continuations=)` (the rows the pipeline is about to
  write, through `store.formatted`). Each fills a private source with `rows(name)`, `where(name)` and `manifest()`.
  - **Each table is read the first time a reader asks, and once.** The regression report reads only the contract
    files and securities.csv of the base commit; the scorecard never reads cusip_history.csv.
  - Alternative: read every table up front. Rejected: 15 `git show`s per base commit, and a table no reader needs
    could refuse the whole snapshot.
  - Cost if wrong: a bad table surfaces when first read, not when the snapshot is built. scripts/scorecard.py builds
    the card inside its `SnapshotError` catch, so a bad table still exits 2.
  - The in-memory adapter copies each table's list when it is built and formats a table when first read, so stage
    10f's snapshot does not see 10g's tables.
- **Every `store.TABLES` name is an attribute, generated from store.TABLES.** A new contract table is added in one
  place, store.TABLES. `table(name)` is the same read, `has(name)` asks whether the run wrote it, and `require(name)`
  reads a table a reader cannot do without (the regression diff's contract delistings and security history).
  - Alternative: one hand-written property per table. Rejected: the second place every new table has to be added.
  - `test_every_store_table_is_an_attribute` pins the attributes against store.TABLES.
- **The older-schema rule, once.** The column check reads the file's header before any row.
  - A table newer than the first eight (`FIRST_TABLES`) is None when the run did not write it: uncertain before
    reset-2, the contract before reset-3, payout_legs before schema 3.
  - A missing first-eight table raises `SnapshotError` naming the file.
  - A file must have its table's columns in order. The one older layout read is a schema-1
    contract/delistings.csv (`CONTRACT_SCHEMA_1`: the columns before `value_rule`, which schema 2 appended): it reads
    as None, as for a run before schema 2. Any other header raises `SnapshotError` naming the file and the missing
    or unknown columns.
  - What changed against the two old rules:
    - lifecycle's "`value_rule` in the header" is now the exact schema-1 layout. Another header without
      `value_rule` raises instead of reading as None.
    - regression's subset check is now the exact check. A base commit between 4597a02 and dea52c9 (payout_legs.csv
      without `share_class`) and a schema-1 base now refuse the report.
    - `_at`'s securities special case is gone: securities.csv is checked like any table (its columns have not
      changed since the library merged).
    - review.csv is one of the first eight. `Tables.read` read a missing one as no rows; only test folders lacked
      it, and tests/test_scorecard_script.py's two fixtures now write it.
  - Cost if wrong: a regression report against a base before schema 2, or mid-5f, cannot be computed. None is used:
    the report came in 5f99ca2, after schema 2 (b177619), and every loop base since is schema 3 with `share_class`.
- **`SnapshotError` (a `ValueError`) replaces `RegressionInputError`.** A run that cannot be read is one error,
  whatever reads it. Every script catches it and exits 2, as before.
- **The run date.** It is the manifest's `as_of`, or today when the source holds no manifest (scripts/scorecard.py's
  `tables_as_of` rule, moved in). A manifest that is not JSON, not an object, or without a date raises.
  - `scorecard.build(snapshot, config=)` takes no `as_of` and no `legs_rows`. The card's date and the payout legs
    are the snapshot's, so the pipeline (stage 10h, `RunSnapshot.of`), scripts/scorecard.py and the floor test
    (`RunSnapshot.read`) agree by construction. tests/test_pipeline.py's run-versus-folder scorecard test now
    compares the two adapters.
- **Stage 9g's doubts are written too.** `continuation_filings` lists a doubted reading as well: a blank filing and a
  `doubt`. `run_snapshot.continuation_entries` writes the entries and `continuation_readings` reads them back, so the
  format lives beside its reader. The verdicts recomputed from a written folder are then the run's own.
  - A confirmation's entry keeps its three keys. The replay has 0 doubts ("0 contradicted"), so its manifest is
    unchanged.
  - Alternative: a new manifest key for the doubts. Rejected: every manifest changes (the gate's manifest compare,
    and test_run_provenance's key set).
  - Alternative: record only the confirmations, as before. Rejected: an offline recompute would miss a doubt like
    CHTR 2016's `ratio:0.9042`.
  - Cost if wrong: a consumer that reads `filing` from every entry sees a blank one on a doubt entry.
- **The verdict is `decide(snapshot, evidence)`.** It reads the continuations from the snapshot; the
  `continuations` argument and its bare-string shortcut are gone. Each placeholder's ticker evidence (stage 10e)
  stays an argument: the run records it nowhere, and recording it would add a manifest key. tests/test_pipeline.py
  adds `test_the_verdicts_recomputed_from_the_written_folder_are_the_runs`: the folder's snapshot gives the
  uncertain.csv the run wrote, an unresolved seed included.
- **regression reads snapshots.** `build_report(base, new, cases)`, `id_changes_since(base, new)` and
  `diff_contract(base, new)` take run snapshots. The scripts read each run once: truth_loop_round's base and folder
  feed the renames, the judge, the report and the case rows. The diff works on a private `_Contract` (the four
  contract lists) that `_rekeyed` rewrites. `id_changes_since` asks `has("securities")` on both sides, so "a missing
  securities.csv gives no computed renames" holds.
- **pipeline.py.** `_as_read` is gone. `partial(RunSnapshot.of, as_of=, continuations=)` gives stages 10f, 10g and 10h
  each a snapshot of the tables as they then are. `_scorecard` takes no legs, and the manifest's entries come from
  `continuation_entries`.
- **Readers moved to the snapshot.**
  - The lifecycle view, scorecard, verdict, contract, diagnosis judge (`LibraryRows.of(snapshot)`, legs from
    `payout_legs`), diagnosis loop and regression.
  - Scripts: scorecard (`legs_rows`, `tables_as_of` and `LEGS_FILE` are gone), truth_loop_round and update_truth (both
    `_legs_rows` are gone; update_truth's three reads of the folder are one), regression_report,
    apply_5h_truth_rulings (`_era_sec_ids` reads `observation_map`), build_diagnosis_truth, draw_audit_sample and
    build_verdict_fixtures.
  - Tests: the floor test (its `_legs_rows` and manifest read are gone), the diagnosis cases (their legs reader is
    gone), the golden cases, and the pipeline's scorecard test.
  - build_diagnosis_truth's judge now sees the run's payout legs. Before, it passed none ("(no payout_legs table)").
    It is the one-time 5-0 build, outside the gate.
- **The verdict harness reads 9g's readings from each case's snapshot.**
  - tests/fixtures/verdicts/cases.json gains each case's `continuation_filings`: 68 lines added, nothing else
    changed. They are what stage 9g gave those rows (APA, CMCSK, HHC, SPB and HUB-B confirmed, CHTR doubted), written
    by a one-off from the harness's own replay of 9g over the recorded EDGAR answers, because the builder reads
    today's output/, which has moved on since the fixture was built.
  - `verdicts(case)` is `decide(snapshot_of(case), evidence)`.
  - The replay (`readings`) stays as 9g's oracle. `test_stage_9g_names_the_confirming_filing_and_the_contradicting_ratio`
    is unchanged, and a new parametrized test holds each case's recorded readings equal to it.
    - Alternative: delete `readings`. Rejected: the 9g test would then assert only the fixture's own content, a
      weaker assertion.
  - The builder writes `continuation_filings` from the output snapshot's continuations. It records EDGAR's answers
    through `verdict_cases.readings`, so its own copy of 9g's selection loop is gone.
  - The builder has an argparse parser, so `--help` prints its usage and builds nothing.
- **Tests.**
  - Added: tests/test_run_snapshot.py, 25 tests:
    - the interface: every table an attribute;
    - the folder adapter: every table and the manifest, read once, a missing folder, no manifest, a bad manifest;
    - the older-schema rule: later tables None, a missing first table, schema 1, three bad layouts;
    - the commit adapter: the commit's rows and manifest, a missing table, a bad layout, a folder outside the repo, a
      revision that is no commit;
    - the in-memory adapter: equal to the written folder, an unknown table;
    - the 9g entries: their shape, their round trip, bad entries.
  - Added elsewhere:
    - test_verdict_cases: 31 (each case's recorded readings);
    - test_regression: 3 (the report over two snapshots, a run without the contract, renames over two commits);
    - test_pipeline: 1 (the folder's verdicts);
    - the import pin: 1 (run_snapshot).
  - Deleted once covered:
    - test_lifecycle's three `Tables.read` tests (the folder adapter's now);
    - test_regression's two `snapshot_at` tests (the commit adapter's now);
    - the floor test's and the diagnosis cases' private legs and manifest readers.
  - Rewritten at the interface:
    - test_scorecard's `build` calls: the date comes from the snapshot, and one new assertion checks it;
    - test_verdict_rulings' rule B: the readings ride in the snapshot;
    - test_exit_kind's `is last`: now identity with the snapshot's own copy, which equals `last`;
    - test_terms_5f_fixes' legs diff;
    - test_diagnosis_truth's `_lib`;
    - tests/lifecycle_tables.py's `tables()`, which now builds a `RunSnapshot.of`.
  - Suite: 3312 passed, 46 xfailed (step 8a: 3256 passed, 46 xfailed).
- **scripts/scorecard.py on the committed output/ gives the same numbers.** I ran it before and after, with
  `--lifecycles` and with `--base ca58ee1`, and ran scripts/regression_report.py against ca58ee1. All four outputs
  are identical (117 lines, 4421 lifecycle rows, 118 lines with the regression metric, 419 report rows), and
  `--check` passes.
- **Left as they were.** `store.read_table` (accept_review, verify_against_web and the tests' table checks call it);
  the golden judge reads the snapshot through the lifecycle view; the audit's `view.tables`.
- **The gate:** the replay of eb27ee5 is SAME against `accepted4_out` (scorecard.json, uncertain.csv, the contract
  files and the manifest included). It refuses no request and reads no uncached text, and its log equals step 8a's
  line for line. On that replay folder, `decide(RunSnapshot.read(folder), evidence)` gives its uncertain.csv (601
  rows, 5 readings from the manifest; a placeholder's evidence read back as the harness does), and
  `scorecard.build(RunSnapshot.read(folder))` gives its scorecard.json.
- **pipeline.py: 1617 lines to 1606.** regression.py went from 282 to 230 lines, lifecycle.py from 237 to 200;
  run_snapshot.py is 309.

### Step 9a: the diagnosis truth set as one module

- **The module is `truth_set.py`, named after a new domain term ("truth set", in CONTEXT.md).** `TruthSet` holds the
  truth rows, the legs, the change log and, when a change settles loop errors, the ledger, as one unit. diagnosis_truth
  keeps the rows' format (`parse_rows`, and `parse_legs`, which was `load_legs`'s body) and the judge.
  - Alternative: grow diagnosis_truth. Rejected: the file module would hold the judge, which step 9b's loop round
    reorganises.
  - Cost if wrong: one module more; merging the two is mechanical.
- **One validation, when a set is opened and again before `commit` writes.**
  - Each header must be exact. Every truth row passes `parse_rows` and every leg `parse_legs`. Legs with no case are
    refused. A row with a missing or an extra cell is a `DiagnosisTruthError` naming the file and line, not a
    `KeyError`. The change log's and the ledger's headers are checked too.
  - Gone: `load_diagnosis_truth`, `load_legs`, `write_diagnosis_truth`, `write_legs`, and diagnosis_loop's
    `write_together`, `read_ledger`, `write_ledger`, `write_changes`, `rename_truth`, `ledger_keys` and
    `CHANGE_COLUMNS` (now `truth_set.CHANGE_COLUMNS`). `dl.read_csv` stays for a round's cases.csv only.
  - What changed: the loop scripts and the apply scripts read the truth raw (`read_csv` + `parse_rows`, no header or
    legs check; apply_5f checked no legs at all). They now check everything the scorecard checked.
  - Cost if wrong: a hand-edited file the scripts used to read now refuses with exit 2, naming the line.
- **Finding: the change log's last row is malformed, and every old rewrite damaged it.** Step 4's f089b8a appended
  CNB's price_date ruling by hand with an unquoted comma in its reason, so the row reads as 7 cells. Every old script
  that rewrote the log (apply_5h, apply_5i, update_truth: `DictReader`, then `DictWriter`) dropped the 7th cell, the
  report path. The before-run on copies showed it: each of those runs, with no change to make, changed the log's
  bytes.
  - data/ is frozen in this step, so the row is not fixed here. The module keeps each change-log record's text as
    read and appends new records. A log record (only a log record) may carry cells past its six, and its text is
    kept. New reasons are quoted by the CSV writer.
  - Alternative: refuse the row. Rejected for this step: the truth set could not be opened until data/ changes, and
    the gate asks for a byte-identical round trip on the real files.
  - For the operator: quote that reason in data/diagnosis_truth_changes.csv (one line). The validation then holds the
    log to six cells like every other file, if that rule is wanted.
- **A ruling applies once, by its own change-log rows.** A `Ruling` sets a cell only when it differs and the change log
  does not already record this ruling (the same reason) setting that cell to that value. A cell a later change moved on
  is therefore never set back.
  - Finding: apply_5f was not idempotent on the current files. Its two carried rows (VMED and MHS) were made
    known_wrong for 5f, and the wave 2 loop then flipped them to pass (change-log rows 981 and 982). A rerun set them
    back to known_wrong 5f: 4 change rows. Its `CARRIED` special case only covered a row still at fixed_by 5f. With
    the once-rule, the rewritten script changes nothing.
  - Alternative: keep the cell-differs rule, with the special case. Rejected: it is what failed.
  - Cost if wrong: a ruling meant to be applied again after a later change has to be a new ruling, with a new reason.
- **The owner guard is one rule.** A ruling with an `owner` applies to a row whose fixed_by is the owner, or is already
  the fixed_by the ruling sets. A ruling with no owner applies to any row. This is 5h's and 5i's guard. 5f's maps onto
  it: owner 5f, or no owner for its carried and controller rows; `LEFT` rows have owner 5f, `RESTORED` owner residual.
  - A ruling on a case the truth file lacks raises. The old scripts skipped it silently.
- **A sub-plan's rulings are data.** The three scripts hold `Ruling` and `Correction` values and a `main` that opens
  the set, applies them in order and commits.
  - `s9a_rulings_diff.py` checked the data: each script's rulings (case, cells, reason, legs, report, owner) equal the
    old script's, ruling by ruling.
  - Order: rulings are applied in data order. The old loops went over the rows within each group, so the change-log
    order of a first application would differ. All rulings are already applied, so nothing changes today.
  - 5i's `NOTES` are rulings with no cells (one `note` log row, once). Its `CORRECTIONS` are `Correction`s: the reason
    is corrected in the note and the logged reasons, with no log row, as before.
  - apply_5h's `--after-run` stays a ruling whose sec_id the run's observation_map gives. It is not a rename (no
    id_changes row names those eras). It reads `--output-dir`, default output/.
  - Each script takes `--truth` and prints its old message ("no change" / "N changes", "N truth change rows",
    "N truth changes"). A bad truth set exits 2.
- **The note convention, once (`noted`).** The text is added as `note; tag: why`, or alone when the note is empty
  (truth_build's rule).
  - The old scripts and truth_update wrote `; text` on an empty note. No current row's note starts with "; ".
  - truth_build's `_note` now calls `noted`.
- **Renames: one chain rule, legs included.** `TruthSet.rename(id_changes)` maps through `regression.renamed_to` (P
  renamed to M and M to F is F, one change-log row). It renames sec_id, price_sec_id and successor_sec_id, and every
  leg's price_sec_id (logged as `legN.price_sec_id`, the judge's field name).
  - The old `rename_truth` took one step, renamed no leg, and would also map a blank old_sec_id.
  - Alternative: move `renamed_to` to contract.py. Rejected: the regression diff is its first user, and the loop
    modules already import regression.
- **Where the files are: data/scorecard.json names the truth file, and the rest derive from it.**
  - The legs and the change log are named after the truth file (`<stem>_legs.csv`, `<stem>_changes.csv`).
  - Every script's `--truth` defaults to `truth_set.configured(repo)`, the config's "diagnosis" entry. This holds for
    truth_loop_round, update_truth, regression_report, the apply scripts and build_diagnosis_truth's `--out`.
  - `--legs` and `--changes` are gone from truth_loop_round and update_truth, and `--legs` from
    build_diagnosis_truth. The workflow never passed them.
  - The config's "diagnosis_legs" entry is accepted only when it names the derived file (`truth_file_of`; data/ is
    frozen in this step, so the key stays until data/ next changes).
  - The fixture builders (build_terms_fixtures, build_acquirer_gate_fixtures), eval_merger_extractor and
    tests/test_diagnosis_truth_cases.py read through `TruthSet.open(configured(...))`. eval's `_truth_cases` gives the
    same 22 rows before and after.
  - Alternative: the module names data/diagnosis_truth.csv and the config follows it. Rejected: data/scorecard.json
    cannot change in this step, and its "diagnosis" key would be dead.
  - Cost if wrong: a config whose truth file has differently named legs is refused. test_scorecard's `l.csv` case is
    rewritten to `d_legs.csv`, plus one test of the refusal.
- **The ledger moves with the truth set.** `TruthSet.open(truth, ledger=)`, `settle(rows)`, and `commit` writes it
  with the rest. truth_loop_round's `--seed-ledger` now commits through the set; the old script wrote the ledger
  alone. `read_ledger(path)` is the validated read for scripts/scorecard.py's `--ledger`. The ledger's path stays the
  caller's: step 9b owns the loop folder.
- **`commit` writes only the files whose content changed, all of them together.** Each file is serialized and compared
  with the bytes read. A file that did not exist is written only once it has a row. `TruthSet.new` (the 5-0 build and
  tests) always writes its truth file and legs.
  - The old update_truth, apply_5h and apply_5i rewrote every file on every run; update_truth created an empty change
    log.
  - The round trip on the real files writes nothing (tested on copies). So the serializer reproduces the truth file,
    the legs and the ledger byte for byte, and the log's records are kept as read.
- **truth_update keeps its rules and loses its file handling.**
  - `apply_round(truth, ...)` edits the set through four public primitives: `set_cells`, `move_status`, `add_row` and
    `settle`. `TruthSet.apply_round` calls it and returns the `RoundResult` (rows, the round's change and ledger
    rows, the retries). The rule texts are unchanged.
  - Two edge differences, neither reachable on today's files: an empty note takes the text alone; and a second
    library-right verdict on a field the truth cannot take, on the same case, no longer logs a ruling_pending to
    ruling_pending row.
  - `flip_statuses` is `TruthSet.flip(lib)`: it judges the set's own cases against the run, so update_truth no longer
    re-parses the rows itself.
  - Alternative: move apply_round's body into truth_set. Rejected: step 9b's loop round restructures the round, and
    truth_update stays the rules' module. It imports truth_set only for typing.
- **Tests.**
  - Added: tests/test_truth_set.py, 44 tests:
    - the paths and the config;
    - the validation: the loader tests moved from test_diagnosis_truth, plus row widths, the log and the ledger;
    - each change kind, with idempotence and the once-rule;
    - the step-4 CNB rulings as data: the first gives the change log's row byte for byte, and the second's comma is
      quoted;
    - a correction;
    - the chain rename with legs, and a FIGI renamed to another FIGI;
    - the flip;
    - the settle;
    - the commit: only what changed, nothing on an invalid set or a failed write, the new set;
    - two round trips: a synthetic set with a two-line field and a 7-cell log record, and the real data/ files plus
      the ledger.
  - tests/test_apply_truth_rulings.py (renamed from test_apply_5h_truth_rulings.py; 1 test to 6): each script and
    5h's `--after-run`, run twice on copies of the committed files, leaves every byte as committed. Also: 5f's
    rulings still apply to a row they have not reached, and the carried rows stay flipped.
  - Moved to the interface:
    - test_truth_update's `_apply` builds a `TruthSet.new` and calls `apply_round`; every assertion is unchanged;
    - the round and update scripts' tests drop `--legs`/`--changes` and read the derived change log;
    - scorecard tests write through `write_truth` (tests/diagnosis_rows.py, with `ledger_row`).
  - Deleted once covered:
    - test_diagnosis_truth's 22 loader tests (now in test_truth_set);
    - test_diagnosis_loop's three `rename_truth` tests and its ledger round trip (a `settled_keys` test stays);
    - test_truth_update's `flip_statuses` test.
  - Added elsewhere: the import pin (truth_set, 1), test_scorecard (the legs refusal, 1).
  - Suite: 3343 passed, 46 xfailed (2a28ae3: 3318 passed, 46 xfailed).
- **The gate.**
  - The loop scripts were run before (the base clone's scripts at 2a28ae3) and after, on copies, against a shared
    clone's output/ and base commits (truth_loop_round: wave2 round 1 at ca58ee1, wave1 round 2 at 0de5d8f;
    update_truth, dry and real: wave2 rounds 1 and 2, wave1 round 1). Every stdout line, cases.csv,
    regression_report.csv, summary.md, ledger and truth file is identical. The one difference is the change log of
    the old real update_truth runs: the old code damaged the CNB row (the finding above), and the new code leaves the
    log as committed.
  - scripts/scorecard.py `--check`, and `--base ca58ee1`: output identical before and after, exit 0, and the `D.*`
    values unchanged (D.mismatches 121, D.cases_matching 284, D.unexplained_regressions 0).
  - `git diff --stat 2a28ae3 -- data` is empty.
  - The replay is SAME against `accepted4_out`, refuses no request, and its log equals step 8a's byte for byte.
- **pipeline.py: 1606 lines, unchanged** (stage 10h's scorecard config reads the truth set through `load_config`).
  - truth_set.py is 495 lines.
  - diagnosis_truth.py went from 338 to 299 lines, diagnosis_loop.py from 183 to 136, truth_update.py from 216 to 204.
  - The three apply scripts went from 399 to 347 lines; truth_loop_round and update_truth from 185 to 176.
- **Controller fix after the step: the change log's CNB `price_date` row is quoted.** Step 9a found that the row
  appended by hand in f089b8a had an unquoted comma in its reason, so it read as seven cells and the old rewrites
  (apply_5h, apply_5i, update_truth) would have dropped its report path. The row is rewritten quoted, and the test of
  the step-4 rulings now checks the module writes that row byte for byte. No cell's value changes. The truth set
  still tolerates extra cells in the log; every row now has six.
  - Cost if wrong: none. The row's six values are the ones the ruling wrote.

### Step 9b: the loop round behind one module that owns its error vocabulary

- **The module is `loop_round.py`, named after a new domain term ("loop round", in CONTEXT.md). It replaces
  diagnosis_loop.py** (deleted), whose bookkeeping it absorbs: the ledger's outcomes, the case rows and their context.
  - `Loop(folder, repo)` is the loop folder: `ledger` (the one place the ledger's path is named), `truth_set(truth)`,
    `seed(truth, run, label=)` and `round(label, n)`.
  - `Round` has the two operations. `open(truth, run, base, report=)` renames, judges, writes the report, filters by
    the ledger and writes the case rows. `close(truth, run, base, dry_run=)` applies the records
    (`TruthSet.apply_round`), re-judges and flips (`TruthSet.flip`), and commits and writes summary.md.
  - `unexplained(base, run, cases, ledger_rows)` gives `Unexplained`: its `count` is D.unexplained_regressions, its
    `passes` the gate (0), its `line()` the scorecard line. It is defined beside its gate, and scripts/scorecard.py
    asks it only with `--base`, as before.
  - The operations take run snapshots, not a repository and a revision. The scripts read the run and the base commit
    (`RunSnapshot.read`, `RunSnapshot.at`), and the tests give the base through a throwaway git repository.
  - Alternative: grow diagnosis_loop.py under its name. Rejected: its name says the whole loop, while the module is
    one round of it (the workflow runs the rounds).
  - Cost if wrong: a rename, mechanical.
- **The import graph: truth_update reads the loop round's tokens, and the loop round opens truth sets, so
  `TruthSet.apply_round` imports truth_update locally** (the precedent: handling.py's qlib_adapter import).
  `LEDGER_COLUMNS` moved to truth_set beside `CHANGE_COLUMNS`: the ledger's file format is the set's, while what its
  keys and outcomes mean is the loop round's.
  - Alternative: the tokens in a module below both (diagnosis_loop kept as the vocabulary). Rejected: the prompt's one
    owner of every token, and the tokens and the round would again live in two places.
  - Alternative: truth_update's rules moved into loop_round, `TruthSet.apply_round` deleted. Rejected: step 9a's
    TruthSet interface stays, and truth_update stays the rules' module.
  - Cost if wrong: one local import. tests/test_import_closure.py lists loop_round among the measurement modules.
- **Every token is built by one function and read back by its inverse in the same module.**
  - The key: `mismatch_key` and `regression_key` (moved from regression.py), read by `parse_key` (a Mismatch, or a
    report row) and `key_kind`. A key part holding `|` is refused, so every key reads back. No ledger key holds one
    today (1,536 rows checked: every `mis|` key has 5 parts, every `reg|` key 7).
  - A ledger row's kind is its key's (`ledger_row` derives it): one fewer argument, and the kind cannot disagree with
    the key. Every one of the 1,536 ledger rows already agrees.
    - Alternative: keep the kind as an argument. Rejected: a second spelling of what the key says.
    - Cost if wrong: test_truth_update's fake keys (`k-...`) became real keys, built by the module; every assertion
      on them names the same key.
  - The field name of a regression: `Field.of(row)` (a report row), `Field.name` (the text) and `parse_field` (its
    inverse). truth_update asks `Field.scored` and `Field.whole` instead of `f in SCORED` and the `WHOLE_ROW` tuple
    (gone). The same answers for every name a report row gives; `parse_field` refuses a name no report row has.
  - The case id: `case_id(subject, label, n)` and `parse_case_id`. A label holds letters, digits, `.` and `-`
    (every label in the ledger does), so the id reads back; `Round` refuses any other label with exit 2.
  - A mismatch's field name is the judge's own (`diagnosis_truth.MISMATCH_FIELDS`): the loop carries it. Its one
    built name, `legN.x`, is now `diagnosis_truth.leg_field`, with `field_key` (unchanged meaning) its inverse in the
    same module; `TruthSet.rename` logs through `leg_field` too.
    - Alternative: move the leg field into loop_round. Rejected: the judge would import the loop round, which imports
      the judge.
- **The round's cases are typed: `RoundCase.of(row)` reads a cases.csv row back** (its JSON cells as `CaseError`s:
  key, field, two sides; `delist_date`, the context's last real ending). The rules read attributes, never the case
  row's columns or JSON. `RoundCase.of` refuses an unknown mode and error lists of unequal lengths; the old rules
  treated any mode but `regression` as a mismatch and `zip` cut uneven lists short. No real cases.csv has either.
- **truth_update asks the judge for the keys a new truth row produces (`loop_round.new_row_keys`)**, instead of
  spelling the judge's wording (`present`, `(no contract row)`, the shapes). It judges the new row against the run
  and settles every mismatch as `truth_right`.
  - Why every mismatch: every scored cell of the new row other than a field the diagnosis found `old` is the run's
    own value (an unchanged field equals the base's; a `new` field is the run's), so the row's mismatches are exactly
    the `old` fields. No knowledge of the judge's field names is needed.
  - The keys are ordered by the case's fields (then the judge's order), so the ledger lists them in the old order:
    contract column order, `last_trade_date` before `exit_kind`, where the judge's order is SCORED's.
  - To judge, the rules take the run as the judge reads it: `apply_round(truth, cases, records, base_contract, run)`,
    `run` a `diagnosis_truth.LibraryRows`, replacing `new_contract` and `run_sec_ids` (`run.contract`,
    `run.sec_ids`). `TruthSet.apply_round` takes the same arguments. The scripts always passed the securities, so
    "None for no check" is gone; test_truth_update's helper passes every security its cases name by default.
  - Alternative: keep the two arguments and build a partial `LibraryRows` inside. Rejected: a hidden partial view of
    the run, and two arguments where one does.
- **The record vocabulary has one Python definition** (`MODES`, `RIGHTS` with `neither`, `CONFIDENCES`,
  `VERDICT_KEYS`, `RECORD_KEYS`, `VERIFIED`). tests/test_loop_round.py reads the workflow's RECORD schema (the
  `mode`, `right` and `confidence` enums, a field verdict's required keys, the write-back's "has all of the keys"),
  its round folder and file names, and its two commands (parsed by the scripts' own parsers), and checks the keys it
  reads from the open line. The JS is unchanged: it already agreed.
- **The scripts are argparse over the module.** truth_loop_round.py and update_truth.py each have a `parser()` and a
  `main` that reads the snapshots, calls `Loop.seed`, `Round.open` or `Round.close`, and prints its `line()`;
  scripts/scorecard.py has a `parser()` too, and its `--ledger` default is `Loop.of(ROOT).ledger`. Their command
  lines are unchanged.
  - Each script now catches `TruthFileError`, `SnapshotError`, `ValueError` and `OSError` around the whole call and
    exits 2. Before, truth_loop_round's seed commit and update_truth's commit and summary sat outside the catch (a
    failed write was a traceback, exit 1), and scripts/scorecard.py's `--base` catch gains `ValueError` (a key part
    holding `|`).
  - The order in which several bad inputs are reported can differ (the snapshots are read before cases.csv); each
    still exits 2.
- **Declared defect fix: the examined day is a column of its own** (its own commit, before the module's). data/diagnosis_truth.csv gains
  `examined_delist_date` after `shape`; `DiagnosisCase.old_delist_date` (the case_id's tail) is gone, and the judge's
  ending_moved check reads the column. `parse_rows` requires it on an ending_moved row and checks its date format.
  - The column alone changed in data/: every other cell is kept, no change-log row (a format change, not a ruling),
    and the truth set's round trip on the migrated files writes nothing.
  - Its values, by a one-off migration: the 284 rows of sub-plan 5-0's diagnosis take the date their id was built
    from (source.csv agrees for the 282 it lists). The 37 loop-added rows take the `delist_date` of their row in
    their round's cases.csv (the run's last real ending when the round was opened: the ending the case examined); 5
    removed-row cases have none and stay blank.
  - The one loop-added ending_moved row is CRC's, `BBG00Y04KP80_5a-r2` (now under BBG0060B3M63): its examined date is
    2016-06-01. Before, its check compared the last ending with a blank.
  - Going forward, a row the loop adds takes its case's `delist_date` (`RoundCase.delist_date`, from the context
    column cases.csv already had): derived where the case is built.
  - The 5-0 builder: `truth_build.assemble` takes `examined_delist_date` from its `meta`, and
    scripts/build_diagnosis_truth.py reads it from the diagnosis's source.csv.
  - Alternative: derive the date where the case is built and keep no column. Rejected: a loop-added case's examined
    ending exists nowhere else in data/ (only in output/'s round folders).
  - Cost if wrong: a hand-written ending_moved row without the date is refused (exit 2, naming the line).
- **Judgements on output/ and on the replay folder: none changed.** Every truth case judged with 26fa691's code and
  truth files and with this step's: 321 cases, 0 judgements changed, 121 mismatches before and after, on both
  folders. CRC's last real ending is 2020-08-10, not the 2016-06-01 it examined, so its shape holds either way.
- **Tests.**
  - Added: tests/test_loop_round.py, 48 tests:
    - each token and its inverse (keys, field names, case ids, labels, ledger rows, case rows);
    - the loop folder's files and the one ledger every script names;
    - the workflow's agreement (vocabulary, round folder, commands, the open line);
    - seeding, opening (renames, the report, the ledger filter, case rows and context, two cases of one security) and
      closing (dry run, real run, a missing cases.csv, a retried record, a security the run lacks, a flip, the
      examined ending a new row keeps) in a throwaway git repository with JSON records;
    - the judge-key agreement for 8 branches (a scored field old, two old in the case's order, one new and one old,
      an added row old or new, a removed row old or new, every field new): the ledger's `truth_right` keys are the
      judge's for the new row, and the next round lists nothing of it;
    - the unexplained count;
    - the two scripts' thin tests (their arguments reach `Round.open`, `Loop.seed`, `Round.close`; exit 2).
  - Added elsewhere: test_diagnosis_truth, 2 (the loop-added ending_moved case; the leg field round trip);
    test_truth_set, 3 (the column, never the id's tail; the ending_moved refusal; a bad date), replacing its 2
    `old_delist_date` checks; test_truth_build, 1 (the builder's examined date); test_truth_update, 1 (a new row keeps
    its case's examined ending); test_scorecard_script, 1 (`--base` asks the loop round, `--check` fails unless it
    passes).
  - Deleted once covered: tests/test_diagnosis_loop.py (9 tests, 3 of them loading the round script with importlib in
    throwaway repositories), test_truth_update's 3 script tests, test_regression's `unexplained` test, and
    test_scorecard_script's git-driven `--check --base` test.
  - Rewritten at the interface: test_truth_update's helper builds `RoundCase`s with real keys and passes the run as
    `LibraryRows`; its assertions name the same keys.
  - Suite: 3384 passed, 46 xfailed (26fa691: 3343 passed, 46 xfailed; the defect fix's commit alone: 3348).
- **The gate.**
  - The loop scripts were run before (a shared clone at 26fa691, its own scripts, src and data) and after (this
    worktree, its migrated data), on copies, against the clone's output/ and base commits: truth_loop_round (wave2
    round 1 at ca58ee1, wave1 round 2 at 0de5d8f); the seed on the committed ledger and on an empty one; update_truth
    dry and real (wave2 rounds 1 and 2 and 5a, 5b, 5c round 1 at ca58ee1, wave1 round 1 at 0de5d8f); and a synthetic
    round. In it the ledger is emptied, so every current mismatch (121) and regression against ca58ee1 (419) is a
    case; records are synthesized for each verdict kind, refuted, inferred and missing; update_truth runs dry and
    real; then round 2 opens on the result. Every stdout line, cases.csv, regression report, change log, ledger and
    summary.md is identical (the copies' own folder names read alike). The truth files are identical on the old
    columns, with `examined_delist_date` kept on every existing row and set on the 351 rows the synthetic round adds.
    Round 2 lists only the 32 retried cases, before and after: the judge's keys settled every mismatch the 351 new
    rows make, as the spelled keys did.
  - scripts/scorecard.py `--check`, and `--check --base ca58ee1`: output identical before and after, exit 0
    (D.mismatches 121, D.cases_matching 284, D.unexplained_regressions 0).
  - `git diff --stat 26fa691 -- data`: data/diagnosis_truth.csv only, the column.
  - The replay is SAME against `accepted4_out` (scorecard.json's `D.*` lines included), refuses no request, and its
    log equals step 9a's byte for byte.
  - The 5-0 builder, run offline on a copy (`--no-figi`), gives each of its 282 rows the date its id was built from.
- **pipeline.py: 1606 lines, unchanged.** loop_round.py is 560 lines (diagnosis_loop.py was 136, deleted).
  truth_update.py went from 204 to 186 lines, regression.py from 231 to 219; truth_loop_round.py and update_truth.py
  from 176 to 125.

### Step 10: dlret decides an ending's value once

- **The module is `dlret.py`, grown in place.** Its interface has three entry points over one input record:
  - `decide(ValueInputs) -> EndingValue`: the method (`DlretMethod`), the value, the terminal value, its confidence,
    its kind (measured, a fill, or no value), the table's cell (`table_dlret`) and the firm month's DLRET
    (`firm_month`);
  - `rule_of(row, merger, distress) -> Rule`: the value rule (`exit_kind.VALUE_RULES`) and the terms it publishes;
  - `contract_value(row) -> ContractValue`: the contract's `dlret`, `dlret_fill` and `terminal_value` cells.
  - Each method's kind and confidence sit beside the enum, in one table (`METHODS`); a test checks every method has
    an entry. The rule's two inputs beyond the row, `MergerInputs` and `DistressTerms`, moved here from payout_rule,
    with `OVERRIDE_SOURCE` and the `terms_gate` words.
  - It loads the row vocabulary, the bucket and exchange enums and the ticker spelling only (exit_kind, crsp_codes,
    exchanges, observations, names), pinned in tests/test_import_closure.py; dlret joined the contract modules there.
  - Alternative: a new `value.py` (step 16's layout names a `value/` group). Cost if wrong: a rename.
- **One typed input record per ending, `ValueInputs`.** It holds the bucket, the exchange, the last close, a merger's
  terms (`payout_per_share`, `stock_ratio`, `acquirer_price`), `recovery_ratio`, `otc_print`, `plan_value`, the cash
  read's `payout_confidence` and `deregistered`.
  - It replaces six parameter lists: `resolve_dlret` (9), `enrich` (12), `build_delistings_table` (10 maps),
    `compute_dlret` (8), `bmp_firm_month_return` (9) and `build_firm_month_correction` (8).
  - Its field names are the old keywords, so the README's keyword form passes `**value` straight through and cannot
    fall behind as `compute_dlret` did (it never got `plan_value`).
  - `enrich(record, value)` refuses value inputs of another bucket. `DelistRecord.deregistered` names the evidence
    the classifier writes (`evidence["deregistered"]`), so stage 10a does not read the evidence dict.
  - Alternative: `decide(bucket, inputs)`, with the bucket outside the record. Rejected: the bucket is the first
    input every branch reads.
- **The table's fills are decided in dlret, beside the value.** Assumed par moved from reconstruction (a merger or an
  expiration with no consideration and a last close; an unknown ending the classifier found deregistered), and so did
  the table's blanking (an abstain and an unknown). `EnrichedDelistRecord` carries dlret's answer (`answer`); its
  `dlret`, `dlret_method`, `terminal_value` and `dlret_confidence` are properties over it.
  - The two DLRETs per ending are kept exactly. They are now two fields of one answer: `value` is the table's,
    `firm_month` the value before the par fill.
- **The value rule is decided from the delistings.csv row, not at stage 10a.**
  - Why: the contract is built from the tables (decision 6), so a committed output's contract can be rebuilt from its
    tables alone. And the formula's digits are the row's six decimals: `f"{ratio:.6g}"` of the cell "0.012346" is not
    that of an in-memory 0.0123456.
  - The rule reads the table's answer from the row, never decides the value again: `worthless` is still the row's
    method (via `DlretMethod.WORTHLESS`), and the method is never emitted.
  - **One order for a liquidation or a drop** (`_distress_rule`): a recovery ratio, else a bankruptcy plan, else the
    first OTC print. The value asks it with what it can measure (an answered plan value), the rule with what was read
    (a plan's ratio). Before, payout_rule decided recovery, plan and print in its own order beside dlret's.
  - payout_rule's `or f.exit_kind == "dropped"` went: `exit_kind._kind` gives `dropped` only to a liquidation or a
    compliance failure, which the branch already names. No row changes.
  - Alternative: decide the rule at stage 10a from `ValueInputs` extended with the reads, and carry it to the
    contract. Rejected for both reasons above.
- **payout_rule writes the rule dlret decides** (`value_fields`, `basket_legs`): the eleven columns, the formula
  grammar and the price date (the trading calendar). It went from 231 to 114 lines.
  - Alternative: dlret writes the eleven columns and payout_rule goes by the deletion test. Rejected: the formula
    grammar is the contract's writing, not a decision; it would put the trading calendar and the contract's text into
    the module the table and the firm month read.
  - Cost if wrong: a new value kind touches payout_rule's `_formula` as well as dlret. The decision (which rule, which
    terms, whose price) is in dlret alone.
- **exit_kind's measured/fill split moved to dlret** (`contract_value`). The row vocabulary imports nothing of the
  package (pinned), so it could not read dlret's method table. `EndingFields` lost `dlret` and `dlret_fill`, and
  `MEASURED_METHODS` and `FILL_METHODS` are gone. The contract was their one reader in the package.
  - Alternative: exit_kind imports dlret and the pin is relaxed. Rejected: step 8a's pin keeps the measurement side
    free of everything but strings.
- **`MergerValues.table_terms(key) -> TableTerms` replaces `table_inputs()`'s five maps.** It answers for any
  delisting: the stock leg the gate priced, else the caller's --merger-terms row (by delisting, else by sec_id), the
  cash, and the gate's source, confidence and flags. The same precedence as the maps' `for_delisting` lookups.
  - It is not a `ValueInputs`: stage 8 knows only the merger's share. The last close, the exchange, the recovery and
    the answers are other stages' inputs, so stage 10a builds the record.
  - `build_delistings_table` is gone. Stage 10a is one loop: each delisting's `ValueInputs`, then `enrich`. Each row
    now pairs with its own delisting; before, a dict by key paired them. No key repeats in output/ or the replay
    (checked).
- **The deletion test.**
  - bmp_correction.py is deleted. Its compounding is `handling.firm_month_correction(record, prior, value)`, which
    asks dlret once; it asked twice before (`compute_dlret`, then `bmp_firm_month_return`, which called it again).
  - `resolve_dlret`, `DlretResult`, `compute_dlret` and `bmp_firm_month_return` are deleted. The package root no
    longer exports `compute_dlret` and `bmp_firm_month_return`; it exports the Shumway constants from dlret. No
    script, README example or the companion repo (qlib_practice, searched) uses either name.
  - `build_firm_month_correction` is kept, with the README's keyword signature, as one line over
    `firm_month_correction`.
  - Cost if wrong: an outside caller of the two names gets an ImportError. The fix is
    `decide(ValueInputs(...)).firm_month`, and the compound is `build_firm_month_correction(...).firm_month_return`.
- **The splicer reads a row back as one `ValueInputs`** (`qlib_adapter.value_inputs`).
  - A `plan_stock` row's terminal value is read as the plan value it is, no longer as an OTC print. dlret values both
    alike on a liquidation, so the output is the same for every row the library writes.
  - The one change is a row dlret never writes: a compliance failure under `plan_stock`. It now takes its Shumway
    mark, since a drop takes no plan; before, it took an OTC print. Only the harness's three synthetic `SYN_PLANC`
    rows show it.
- **The train-label and backtest-exit policies stay handling's own.** They are per-bucket handling policies (README),
  not a value rule, and the gate keeps their outputs.
- **Declared defect fix: `plan_stock` is graded medium** (its own commit, before the module's). This is the
  controller's ruling: a plan value is the caller's answered close of the new line times the plan's ratio, the same
  kind of measured value as an OTC print. It fell through to "low", and lifecycle reads `dlret_confidence` for
  quality.
  - Tested in reconstruction (a `plan_stock` row's `dlret_confidence`), dlret (`METHODS`, beside `otc_print`) and the
    WOLF 2025 real case (test_distress_cases).
  - The replay answers no price request: no `plan_stock` row, and no row changes.
- **Measured, open for the operator's ruling: the two DLRETs per ending.** This covers every row of the committed
  output/delistings.csv the firm-month splicer corrects (873: not a continuing security, with a date). It compares
  the table's dlret with the DLRET `apply_bmp_corrections` compounds from the row. A row with no last close takes the
  panel's close; it counts as equal when the value does not depend on that close.
  - 25 endings differ:
    - `abstain_no_consideration`, 14: table blank, firm month 0.0 (TAHO 2019, FRK 2007, IFIN 2007, FWLT 2014, PARAA
      2025: mergers with no terms and no last close);
    - `needs_last_trade`, 7: table blank, firm month payout over the panel's close − 1 (CERN 2022, CNW 2015, PLL
      2015, HSP 2015, N 2016);
    - `unknown`, 2: table blank, firm month the Shumway mark at the panel's close (WPG 2021 liquidation −0.55, SPNV
      2020 compliance failure −0.30);
    - `assumed_par`, 2: table 0.0, firm month a drop (STAY 2021 and TMUSR 2020, expirations).
  - The other 26 assumed-par mergers agree (0.0 both).
  - 588 more agree only at the table's six decimals: the firm month recomputes from the row's six-decimal cells.
  - Unchanged by this step; the same measurement on the new interface prints the same lines.
- **Tests.**
  - Added: tests/test_dlret.py rewritten at the interface, 30 tests (19 before). They cover each method's value,
    confidence and kind; the table's cell and the firm month; the method table; worthless never decided; the
    contract's value cells; each rule; the liquidation order shared by the value and the rule; and a merger's rule from
    its published terms.
  - Added elsewhere: test_firm_month_correction 4 (Shumway by venue, a degenerate last trade, a plan value, the two
    DLRETs); test_reconstruction 2 (the plan_stock grade, the bucket refusal); test_qlib_adapter_bmp 1 (a plan_stock
    row read back); test_import_closure 1 (dlret's closure).
  - Moved: exit_kind's value-cell assertions to test_dlret's `contract_value` tests, row for row; payout_rule's two
    ordering tests to test_dlret's rule tests (the writing of a recovery and of worthless stays in test_payout_rule).
  - Deleted once covered: tests/test_bmp_correction.py (21: its `compute_dlret` tests duplicate test_dlret's; its
    compound tests are test_firm_month_correction's, the NYSE −0.44 and the degenerate last trade added there);
    test_firm_month_correction's `compute_dlret` test; test_reconstruction's three `build_delistings_table` tests
    (the keying is `for_delisting`'s, tested, and test_delisting_rows' rewritten keying test).
  - Rewritten at the interface: test_known_cases_bmp (through `build_firm_month_correction`), the `table_inputs`
    assertions of test_merger_value, test_rewrites and test_handoffs (`table_terms`), test_delisting_rows' table
    tests, the WOLF plan test, and test_pipeline's spy (on `enrich`).
  - In all: 44 test functions added, 52 removed.
  - Suite: 3377 passed, 46 xfailed (57e2728: 3384 passed, 46 xfailed; the fix's commit alone adds one test).
- **The gate.**
  - The replay of 4dd5944 is SAME against `accepted4_out`, refuses no request, and its log equals step 9b's byte for byte. The fix's commit (1ae302e) changes no replay row: the replay answers no price request, so no ending is `plan_stock`.
  - The handling outputs, before (57e2728) and after, on a synthetic panel over the committed output/delistings.csv
    and outside output/ (scratchpad `s10/handling_harness.py`), are byte-identical:
    - `apply_bmp_corrections`, `inject_terminal_labels` and `apply_backtest_exits` (5,677 monthly rows, 42,040 daily
      rows), with their warnings;
    - scripts/compute_corrected_returns.py's `main` on the same panel as a file;
    - `adjustments_from_rows`.
  - The same harness also runs 31 synthetic rows the replay never writes: OTC prints and plan values on liquidations
    and drops, recoveries, rows with no close, mergers with no terminal value, expirations with a close, and unknown
    buckets. All are identical but the three `SYN_PLANC` rows above.
  - scripts/scorecard.py `--check`: output identical, exit 0.
- **pipeline.py: 1606 lines to 1604.** dlret.py went from 177 to 458 lines, payout_rule.py from 231 to 114,
  reconstruction.py from 356 to 249; bmp_correction.py (61) is deleted.
- **Controller ruling on the firm-month measurement: keep both, and document it.** The 25 endings that differ follow
  from the two conventions. The table publishes only what the library knows and flags the rest `no_dlret`. The BMP
  firm-month correction must give every ending a number, so it fills by bucket. The two assumed-par expirations come
  out the same either way: a 0.0 DLRET and no correction both leave the month's return unchanged. The 588 that agree
  at six decimals differ only by the table's rounding. CLAUDE.md's note on the two return-correction APIs now says so.
  - Alternative: make the firm month read the table's dlret, so a blank stays uncorrected.
  - Cost if wrong: a caller who expects the corrected panel to match delistings.csv finds 23 endings filled that the
    table leaves blank. Each is flagged `no_dlret` in the table.

### Step 11: the clients' optional capabilities declared at the `Clients` seam

- **The declarations are a leaf module, `capabilities.py`; `pipeline.Clients` reads them.** It holds the
  `FullTextSearch` protocol, `Capability(client, attribute, without)`, the table `CAPABILITIES`, and `stated`,
  `offers` and `Undeclared`. Stages ask the seam: `Clients.full_text_search`, `Clients.names_security`, and
  `Clients.absent()` for the run's log. `line_follow.LineSources` gained `full_text_search`, and merger_value reads
  `clients.names_security`.
  - Why a leaf: line_follow and merger_value read the same statements and cannot import pipeline.
  - Alternative: the declarations beside `Clients` in pipeline.
  - Cost if wrong: one 81-line module.
- **An adapter states a capability by its attribute: the capability, or None (False for a flag).** This is how
  Python's own `__hash__ = None` states an object unhashable. An adapter that states nothing is refused where the
  statement is read (`Undeclared`, a TypeError naming the client, the capability and how to state it).
  - The statements are read when asked (properties), not checked in `__post_init__`. Tests set a field of the
    `Clients` or `fake_edgar.full_text_search` after building it. `run` checks every statement at its start
    (`absent()`), so a run never stops partway on one.
  - Alternatives:
    - `runtime_checkable` Protocols. Rejected: `isinstance` discovers, so a double that leaves a method out is
      silently absent again.
    - A capability set per adapter class. Rejected: a test that sets `full_text_search` on an instance would also
      have to change the set.
  - Cost if wrong: every double carries a one-line statement.
- **Two capabilities are optional: EDGAR full-text search and the LLM extractor's named call. Every other probed
  read is required of each adapter.** Required now:
  - EDGAR's `submissions` (classifier's `_completes_as_acquirer`), `fetch_filing_raw` (own_shares' `read_form25`)
    and `company_tickers` (own_shares' `target_issuer`);
  - the resolver's `flush` (`_flush_memo`);
  - the halt feed's `failed_days` (`Dating`);
  - the classifier's `shadow()` (the delisting warm-up; below).
  - Why: production's adapters always have them. The classifier and the finder already call `submissions` and
    `fetch_filing_raw` unconditionally elsewhere, and `identify` already calls `flush`. A double answers each from
    its fixture: nothing ("", {}, ()), which is what each `getattr` default gave. So no rule changes.
  - Full-text search stays optional: the real-case fixtures recorded no searches. An absent search has a defined
    meaning (the 8-K12B and continuation-filing searches, the other-registrant check and the ticker evidence are
    not run); a present one that answers [] would be a made-up "searched, nothing found".
  - Alternative: every probed read optional and declared. Rejected: production never lacks them, so each would be
    a branch only doubles take, the friction the step removes.
  - Cost if wrong: a new double must provide those reads. It fails loudly (AttributeError), never silently.
- **The named LLM call stays optional only for one unit test, which fails with the capability: left for a ruling.**
  - The test is `test_pipeline_prefetch.py::test_payout_extraction_is_warmed_on_worker_threads_and_the_llm_is_not`.
    It asserts "paid calls are never warmed" (written at c43bdd0). Its `_Llm` took no `security_name`, so
    `inspect.signature` turned off the warm pass that sub-plan 5f (4597a02) added for every extractor that takes
    the name.
  - Given the named call, its LLM is filled ahead on a worker thread and `set(llm) == {MainThread}` fails
    (measured: `{'MainThread', 'sec-warm_0'}`). Production warms since 5f, and test_merger_value's
    `test_the_llm_calls_are_filled_ahead_on_worker_threads_with_the_same_answers` tests that.
  - Following the brief, the double keeps the old path, stated absent (`names_security = False`), with a comment.
    The assertion and the library are unchanged.
  - Ruling asked: drop `NAMED_LLM_CALL` and rewrite that assertion to production's behaviour (the LLM filled
    ahead, the sequential pass last on the main thread). The library then has one call shape.
  - Every other LLM double now takes the name and states `names_security = True`: test_pipeline's three,
    test_merger_value's two, acquirer_gate's `CaseExtractor`.
- **Absent capabilities are logged, not added to the manifest.** `run` logs one line per absent capability, before
  anything is read: `capability absent: <client>.<attribute>: <what the run goes without>`.
  - Why: the manifest records SEC traffic and versions. Production (the CLI's `default_clients`) never lacks a
    capability, so only a library caller's own adapters can. The manifest's keys are unchanged for every run.
  - Alternative: an `absent_capabilities` key, added only when one is absent.
  - Cost if wrong: a caller who reads only the manifest misses it. Adding the key is one line.
- **The resolver and the classifier state their issuer record (`issuers`, None for none of their own).**
  - `Clients.__post_init__` reads the statements. `DelistClassifier.__init__` also reads the resolver's,
    in place of `isinstance(resolver, TickerResolver)`.
  - Production: the same record (TickerResolver's). The suite passes, and no `DelistClassifier` test's resolver
    lacked the attribute.
  - The resolver doubles passed to `Clients` state None: `CommittedLookup`, `_UnsavableResolver` and
    `_OneAnswerResolver`.
  - Alternative: leave the classifier's `isinstance`. Rejected: a resolver double holding a record would then be
    shared by `Clients` but not by the classifier.
- **`DelistClassifier.shadow()` replaces the warm-up's copy and its `issuers` probe.** It returns a copy reading
  through `IssuerRecord.shadow()`, which is what `_warm_delisting_search` built inline. The worker-count
  determinism tests pass.
- **The LLM client states the model it calls (`model`, None for none).** `llm_client`'s interface says so.
  - The extractor reads it only when its caller names no model: `model or llm.model`. So the replay's `NoLlm` and
    a cache-only reader (`llm=None`) need no statement.
  - LLM client doubles that name no model state None: `_FakeLlm`, `_BoomLlm`.
  - A client that states nothing, with no model given, is refused (a new test).
- **Plain fields, left alone.** These are not capability probes:
  - `getattr(a, "rows", [])` (stage 9d): `AddedLineSuccessor` has rows and `AddedSuccessor` none;
  - `getattr(pr, ...)` in `MergerValues.contract_inputs`: `MergerValue.raw` is optional, a None guard;
  - `getattr(pr, "currency", "")` in the gate: a `PayoutResult` field;
  - `getattr(self.form25, "notice_text", "")` in own_shares: a `Form25` or an `EdgarSubmission`;
  - the response's `url` in edgar's error message;
  - the thread-local reads.
- **Harness doubles.**
  - Real-case harnesses, full-text search: none gained it. Their fixtures recorded no searches, so their EDGAR
    doubles state it absent: issuer_role (and last_trade, its subclass), distress, form25, acquirer_gate, identity,
    golden (whose EFTS answers are the resolver's, not the client's search). `_FakeEdgar` in conftest states it
    absent too. tests/test_line_follow_cases.py's double already answered from its recorded searches.
  - Real-case harnesses, other changes: acquirer_gate's 71 cases now make production's named LLM call. The case
    answers by sec_id, so every case gives the same result and passes. They run on one worker, so no warm pass.
  - No real-case test failed, so none keeps an old path.
  - Unit tests now on production's path, all passing:
    - test_pipeline's three LLM-driven runs (the named call);
    - test_pipeline_prefetch's `_Halts` (now asked `failed_days`, which answers none);
    - test_classifier's four `_TextEdgar` tests (own_shares now reads the Form 25 raw; it is "", unreadable as
      before);
    - test_terms_5f's KING 6-K test (`_completes_as_acquirer` now reads submissions; {} gives the same names).
  - The stage tests that handed a stage a `SimpleNamespace` as its clients now build `pipeline.Clients`:
    acquirer_gate, test_merger_value, test_line_stage, test_line_follow_cases, two test_pipeline stage tests and
    test_successor_terms' ROVI stage.
- **Tests.**
  - Added, 16 tests:
    - tests/test_capabilities.py, 14 (13 functions): each capability offered and stated absent; a client left out;
      an adapter stating nothing refused, with its message; the absent conditions logged once, first, by a run;
      none logged when all are offered; a run refused before writing; `default_clients` offering every capability
      and every required read; the issuer record taken from the statements; the classifier's shadow;
    - test_merger_value, 1: a named call stated absent is asked without the name and never ahead;
    - test_llm_merger_extractor, 1: an LLM client stating no model is refused.
  - Deleted: none. No test checked only a `getattr` fallback. The handoff test's `assert not hasattr(fake_edgar,
    "full_text_search")` now asserts the statement: `fake_edgar.full_text_search is None`.
  - Suite: 3393 passed, 46 xfailed (step 10: 3377).
- **The gate.** The replay is SAME against `accepted4_out` and refuses no request. Its log equals step 10's byte for
  byte: production's adapters offer every capability, so no line is added.
- **pipeline.py: 1604 lines to 1629.** The `Clients` docstring, its two properties and `absent()`. capabilities.py
  is new, 81 lines.
- **Controller ruling on the named LLM call: dropped; the LLM extractor has one call shape.** It is
  `extract(record, security_name=)`, required of every adapter (production's since sub-plan 5f; its calls are
  filled ahead on the worker threads). `NAMED_LLM_CALL`, `Clients.names_security` and the extractors'
  `names_security` flags are gone, so `CAPABILITIES` holds full-text search alone; merger_value always names the
  target and always fills the calls ahead with workers > 1.
  - The stale test became `test_payouts_and_llm_calls_are_filled_ahead_and_no_llm_answer_is_paid_for_twice`. It runs
    the real `LLMMergerTermsExtractor` over a fake LLM client and a tmp cache, with 4 workers, and asserts:
    - the regex reads are warmed on a sec-warm thread and finished on the main thread, as before;
    - every LLM call is made on a worker thread or the main thread;
    - the client's call count equals the distinct (filing, model, version, ticker) cache keys asked: no answer is
      paid for twice.
    Measured: one call, on `sec-warm_0`, for one key (`000112230418000178_m_v3_AET.json`); the sequential pass read
    the warm pass's cached answer.
  - Deleted with the capability: 3 tests (test_merger_value's absent-path test; test_capabilities' named-call test
    and the LLM case of its parametrized refusal), and the LLM lines of the refusal-message, run-log and
    default_clients tests (the run-log test now expects one line; the default_clients test checks the one call
    shape). Suite: 3390 passed, 46 xfailed.
  - Alternative: keep the capability for the one test.
  - Cost if wrong: none to output; the replay is SAME.
- **CONTEXT.md is unchanged.** A capability is design vocabulary (an adapter's statement at a seam), not a domain
  term. CLAUDE.md gained the capabilities module, the `Clients` seam in the stage text, the edgar, ticker_resolver,
  line_follow and LLM entries, and the doubles' contract in "Tests are fully offline".

### Step 12: the fails index owns its loading and its coverage

- **The index is the only reader of the fails files; a stage asks it for keys over days.** Its interface:
  - built as `FtdIndex(rows, source=, window=)` (the 69 constructions from rows unchanged) or
    `FtdIndex.opened(source, lo, hi, through=, symbols=, cusips=, names=, first_seen=)`, which `identify` calls once
    (stage 1), its run's fails window [lo, `through`] the run date;
  - four asks, each named for what a stage reads:
    - `follow(cusips=, symbols=)`: the keys' rows over the run's fails window (stage 4; stage 4b twice);
    - `around(days, before=, after=, cusips=, symbols=)`: from `before` days before the earliest day to `after`
      after the latest (stages 5b, 7 and 8's gate);
    - `apart(days, ...)`: a separate index of CUSIPs' rows around days, with this one's rows of them, this one
      left as it was (stage 8a's early mergers: what `FtdIndex.load` plus `add` did inline);
    - `every_row(lo, hi)`: every row of the files in a span, as spelled, held nowhere (stage 8a', which read the
      client directly; its degraded `ftd_scan` policy stays in the stage);
  - the queries, unchanged; and three coverage statements (below).
  - Gone from the interface: `load`, `extend`, `add`, `has_rows`, `scanned_from`, `last_date`. `Clients.ftd_client`
    stays the run's adapter, read only by `identify`. `LineSources.ftd_client` is gone, and so is `Identity`'s
    `ftd_lo` field (now a property, the index's `opened_from`).
  - Alternative: queries that load what they miss (a windowed `by_symbol` reading its span on a miss). Rejected:
    - a pass over the run's 419 files costs 20 to 27 s (measured, below), so the asks must come in batches only the
      stage knows;
    - today's windowless queries answer every row held, and later stages read across asks (stage 10's history
      sees 5b's and 7's early rows), so loading per query span would change rows;
    - the warm passes read the index on worker threads: a loading read would race them, and could make the output
      depend on the worker count. Now a query never reads the files (a test pins it), so the warm passes only read.
  - Cost if wrong: a stage still states its keys and days in one call; what it no longer does is hold the files,
    choose a window, or build a private index.
- **The coverage statements, each measured against the file index's meaning over the whole replay** (a probe
  recorded every call and its answer; /tmp/claude/delist_detection/arch/s12_probe_out):
  - `has_rows(lo, hi)` (60 calls, all from `guarded_eras`) is now `data_covers(lo, hi)`: a file of SEC's index has
    a period that meets the span, by the run date. Its answer equals today's for all 60.
  - `last_date()` (4,588 calls from the line follow's data edge, 2 from stage 9's OKE rule) is now `data_end()`:
    the end of the latest file period that begins by the run date, the run date inside it. All answers were
    2026-08-31 both ways (the data's last row and the last period's end).
  - `scanned_from(ticker)` (2,659 calls, `cusip_handoffs`) is now `opened_from`: the first day of the window the
    index was opened over, which no later ask moves. Every answer was 2007-12-17 both ways: every era's ticker is
    opened over that window, and `cusip_handoffs` runs before any other ask.
    - The file index's own start (2004-01-01) is the wrong statement here: the margin asks whether the index read
      a CUSIP's earlier days. Measured anyway (a replay with `FTD_START` there): SAME, its log identical. So no
      open coverage row is left for a ruling.
  - An index with no file index (built from rows, or over a double whose files carry no SEC period) answers
    `data_covers`/`data_end` from its rows held, which are then all its data. Every double of the suite keeps its
    answers, and the zip-fixture tests cover the file index.
  - Consequence outside the replay: a run whose tickers rarely fail (a `--limit` subset) now guards an unconfirmed
    era whenever the data covers its window, and its data edge is the data's end; before, only when one of its own
    tickers had a row then, and its own latest row. That is what the guard and the edge were written to read.
  - Alternative: keep the held-rows meanings, named for what they are. Rejected: the brief keeps today's meaning
    only where the file index's would change a replay row, and none does.
- **Two order dependences are kept as they were, each pinned by a test:**
  - a windowless query (`by_cusip(c)`) answers every row held, those another key's ask brought in too, so it
    depends on what was asked before it;
  - a row is relabelled when it is added, with the spellings asked for by then: a bare-spelled row ("BFB") held
    for a CUSIP before "BF-B" was asked is read again relabelled, a second row for one fail.
- **Open for a ruling: the replay's index holds 3,728 fails twice** (measured at the end of the timed run, below).
  They are every row of three CUSIPs: Berkshire's 084670207 and 084670702 and Lions Gate's 535919500. The files
  spell them BRKB and LGFB, one row a day (checked over the run's files), and so do the observations. Stage 8's
  gate then asks for the acquirer tickers BRK-B and LGF-B (Berkshire's acquisitions, Starz into Lions Gate). That
  ask learns the class spelling and reads the same rows again, relabelled. `by_cusip` of those CUSIPs then gives
  each fail twice, and `by_symbol("BRK-B")` gives the relabelled copies. It was so before this step (the gate's
  `extend` did the same), and no output row of the replay shows it (the sightings dedupe by spelling). But an ask
  order that put "BRK-B" first would hold each fail once, under a different symbol. A fix (relabel nothing an ask did not ask for, or
  relabel the rows held when a spelling is learned) can change rows, so it is not built here.
- **Stage 5b returns its CUSIPs and sightings (`_Backfill`), and `_run` merges them** (`sec_cusips = {**sec_cusips,
  **back.cusips}`; `search = replace(search, sightings=...)`), so the stage changes no input. A CUSIP an earlier
  security of the stage took is still held from a later one (the loop merges its own answers). No other in-place
  mutation of CUSIPs or sightings is left: stage 4b's fold and attach write `Lines.cusips`, the stage's own answer
  copied from the identity's (since 7a), and stage 9d builds its own.
- **Stage 5b's asks are left one security at a time: a faster batch is open for a ruling.** Its 34 securities make
  68 passes, 117 s of the replay's 587 s (the probe; each pass ~1.7 s over 13 files). One pass for every
  security's span of its tickers, and one for the CUSIPs, would take a few seconds. But a security's rebuilt
  sightings would then see rows a later security's ask brought in (today: only earlier ones'), so it is no pure
  move.
- **The relabel rules (`_relabel`, `_relabel_base`) stay in ftd.py.**
  - They decide how the index keys its rows, and every query reads that keying (`by_symbol`'s bare-spelling union,
    a base's rows left under it). Beside identity, half of a key's meaning would sit outside the index, behind a
    seam with one adapter (a hypothetical seam).
  - Their inputs are the observed names and first days the index is opened with, not identity's decisions.
  - Step 13's spelling leaf will take the separator-free spelling and the class-letter regexes; the relabel rules
    can then read them there. The `normalize_ticker` and `names_agree` imports are left for step 13.
  - Cost if wrong: the fails index keeps a domain import (`names.names_agree`).
- **The fixture builders and the data-flow diagram use the new names** (`opened`, `follow`); their output is the
  same rows.
- **Tests.**
  - Added: 12 in tests/test_ftd.py, at the index's interface, over SEC-named zip fixtures in a tmp folder (a real
    `FtdClient`, wrapped to count and record its reads) and rows. They cover: the opening and `follow` past it; a
    query that reads no file; `around`'s span and an ask already held; an index with no source; `apart` leaving
    the index as it was; `every_row`'s unrelabelled stream; a windowed answer the same in either ask order;
    `opened_from` unmoved by an earlier ask; `data_covers`/`data_end` from the file index (a span with no held row
    covered, the run date inside a period); their held-rows meaning with no file index; and the two kept order
    dependences.
  - Moved to the asks: test_ftd's five `extend` tests (follow, a CUSIP under another symbol, the gap, the adjacent
    spans, an acquirer spelling), with every assertion. The 5b stage tests read the returned values and now also
    assert the stage left its inputs as they were. test_merger_value's index takes its fails double as its source.
  - Deleted: none. No test checked only a stage's own `extend` call; the 5b test that the stage asks for no rows of
    an ineligible security checks a stage rule.
  - Suite: 3402 passed, 46 xfailed (step 11: 3390).
- **The gate.** The replay is SAME against `accepted4_out` and refuses no request. Its log equals step 11's byte for
  byte.
- **Peak memory and wall time of the replay** (one worker, `resource.getrusage`; macOS's `/usr/bin/time -l` needs a
  sysctl the sandbox refuses): before (HEAD 644a308) 580.1 s wall and 5.06 GiB maximum resident set; after
  581.5 s and 5.04 GiB. The asks read the same files for the same keys, so the rows held (3,997,194 at the end)
  and the passes are the same. The probe's passes over the files: 252 s of the run, 117 s of them stage 5b's. The
  memory is above CLAUDE.md's 1.8 to 4.2 GB (an older, unprofiled figure); its measured-speed note now gives these
  numbers.
- **pipeline.py: 1624 lines to 1637** (`_Backfill`). ftd.py: 502 to 628.
- **CONTEXT.md is unchanged:** the index, its asks and its coverage are design vocabulary over the fails data, a
  term the glossary's "era" already uses.
- **Controller rulings on step 12's open points.**
  - **The doubled rows (3,728 fails of Berkshire's two CUSIPs and Lions Gate's 535919500, held once under BRKB/LGFB
    and again relabelled under BRK-B/LGF-B) stay as they are, as a follow-up outside this program.** No output row
    shows them, but the answer depends on the order of asks, and a fix can change rows. That needs a fix sub-plan that
    passes the diagnosis truth loop, not a refactor step.
    - Cost if wrong: an ask that counts rows (`trades_after`'s 20-row test, a settled-last run) could count the same
      day twice for these three CUSIPs; none does in the replay.
  - **Stage 5b stays one pass per security.** Two batched passes would save about 110 s of the 580 s replay, but a
    security's sightings would then see rows from a later security's ask.
  - **A `--limit` subset's coverage now follows SEC's file index (accepted).** Over the whole replay every answer of
    `data_covers`, `data_end` and `opened_from` equals the old one, so the predicates now say what a full run already
    meant, and a subset answers as the full run would.

### Step 13: one leaf module for ticker and share-class spelling

- **The leaf is `identifiers.py`: how a security's identifiers are spelled and how its share class is read from
  text. It imports nothing of the package** (`tests/test_import_closure.py` pins it beside `exit_kind`). Its
  interface:
  - ticker spellings: `normalize_ticker`, `regular_way`, `bloomberg_ticker`, `bare_ticker` (the fails files' BRKB)
    and `class_suffix` (UAC-C is UAC and C);
  - the placeholder sec_id: `SHARE_CLASS_CODE`, `placeholder_id`, `is_placeholder`;
  - the class code's letter (`class_letter`) and one reader per kind of text (below).
  - Name: the review's. Alternatives: `spelling` (but half of it reads classes), `share_class` (but a ticker is no
    class). CONTEXT.md is unchanged: a security is one share class there already, and "identifiers" is the
    module's subject, not a new domain term.
  - `is_placeholder` moved with `placeholder_id`: it reads the spelling `placeholder_id` writes.
  - Cost if wrong: one rename across 20 modules' imports.
- **How a merge was decided: a probe of every reader's inputs over the replay.** A copy of the tree at 7ef60c4
  recorded each distinct input of each candidate reader (`/tmp/claude/delist_detection/arch/s13_probe.json`; the
  probe's own replay is SAME), and `s13_analyze.py` asked, per candidate rule, which recorded inputs would get
  another answer. When a rule gives every recorded input the answer it gets today, the run takes the same path, so
  the replay stays SAME. A merge was made only then, and only when the unit tests' cases agreed too.
- **Merges** (each with the replay's evidence):
  - **The class letter a security's name states: one reader, `name_class_letter`.** It was written four times as
    `class_letter(share_class_from_name(name))`: `observations._class_letter` (the era split), `identity._class_letter`
    (the old `ticker_resolver._class_letter`, the issuer inference), and inline in
    `security_master.one_class_issuers`. Same rule.
  - **The name without its class words: one regex (handoffs' and successors' `_CLASS_WORDS`), now
    `strip_class_words`, which also folds the spaces and strips " -" at the ends** (successors' tail moved in).
    handoffs then strips EDGAR's state tag and folds again, as before. Folding first changes none of the 89 names
    the handoffs asked over the replay; successors' fallback (no EDGAR name) was asked for none.
  - **One fails description's class letter: `description_class_letter` (ftd's `_DESC_CLASS`: CL or CLASS, a "-"
    allowed).** The fails index's base relabel used it; the line follow's class refusal read a step's descriptions
    with the name reader (which also reads SER X and a trailing -X). The CL rule gives the line follow's 12 recorded
    descriptions their answers ("SINCLAIR INC CL A", "STARZ ENTMT CORP COM (CAN)"), so the line follow now reads
    descriptions as descriptions.
  - **A filing's prose: one reader, `prose_class_letters` (exchange_terms' `_LETTER`: "Class X"/"Series X", the
    letter not followed by a word character or "-").** acquirer_line's `named_class` used `\b` after the letter.
    exchange_terms' rule keeps all 331 recorded quotes' answers; acquirer_line's rule would change 5 of
    exchange_terms' 527 sentences (Envision Healthcare's 2016 "Series A-1" preferred, Discovery's 2022 "Series A-1"
    preferred, read as series A). `named_class` keeps its quote parse (consideration, subject) in acquirer_line.
  - **The fails files' spelling `t.replace("-", "")`: one function, `bare_ticker`.** It was written in ftd
    (`_learn`), handoffs (`_bare`), history (`_bare` and the sightings' label), the line follow (six places) and
    own_shares (a ticker as a word of a target name). Same rule.
  - **OpenFIGI's spelling: successors' `t.replace("-", "/")` is `bloomberg_ticker(t)`.** `t` is already normalized,
    so the TICKER job and its cache key are the same.
  - **ftd's `_CLASS_SUFFIX` is `class_suffix`.** Same rule; the base relabel reads it.
  - **`class_of` and `CLASS_MODIFIERS` moved from own_shares and exchange_terms.** exchange_terms reads the
    modifiers in a statement's head, own_shares the class a statement must name.
- **Readers kept apart** (each its own rule; the probe shows the merge would change answers):
  - **`figi_class_letter` (the old `security_master.line_class_letter`): the letter an OpenFIGI name ends with,
    after a dash and spaces.** The name reader reads "MSG NETWORKS INC- A" and "STARZ - A" (2 of the 5 recorded) as
    COMMON. Widening the name reader to a spaced trailing dash would change 29 of its 4,114 recorded inputs.
    - Open point, outside this program: those 29 are OpenFIGI candidate names ("CBRE GROUP INC - A", "DOORDASH INC
      - A", "LIBERTY MEDIA CORP - C") that `share_class_from_name` reads as COMMON today. An observed security takes
      its class from its own name (securities.csv shows CBRE's as CLASS A), and `security_master` falls back to the
      era's name when a candidate's reads COMMON. But an added security named by OpenFIGI alone, or a successor's
      class match (`successor_from_8k12b`), could take COMMON for a class A. A fix can change rows, so it needs a fix
      sub-plan.
  - **`descriptions_class_letter` (the old `form25.letter_hint`, R2): CL, CLASS, SER or SERIES followed by a space,
    one letter over all of a CUSIP's descriptions.** Under the one-description CL rule, 15 of the 1,840 recorded
    description sets would change: "CONTL AIRLINES INC CL-B" and "HUBBELL INC CL-B" would gain a hint, Celanese's
    "SER A COM" and Liberty Interactive's "SER A" would lose theirs. Under the name rule, 16 would. And the hint's
    rule would change 2 of the relabel's 18 descriptions ("GREIF, INC. CL-A", "THE NEWS CORPORATION LTD CL-B").
  - **`answer_class_letter` (the old `llm_merger_extractor.leg_class_letter`): the whole answer one class.** The LLM
    answers a bare letter ("A", "B", "C": 3 of the 6 recorded answers), which the name reader reads as no class.
  - **A Form 25's class text stays in form25** (`class_label`, `class_letters`, `_lettered_segments`). It is read
    segment by segment, past attached rights and a common's preferred clauses, CLASS X before SERIES X across
    segments. The same segments feed the match (`_named_by`) and R3 (`other_class`), so moving the letter rule out
    would split one parse across two modules. Each label's letter is read with `identifiers.class_letter`.
    - Cost if wrong: one class-letter reading outside the leaf, documented there and in the leaf's docstring.
  - **exchange_terms' `_CLASS_WORDS` (a set of words dropped from party names) is not a class reader** and stays.
- **Outside spellings left in place:**
  - listing_status reads OpenFIGI's tickers back with `.replace("/", "-")`;
  - acquirers looks the acquirer up in EDGAR's ticker file under `acq.upper().replace(".", "-")`;
  - the LLM extractor's `clean_ticker` drops a spelled-out null.
  - Each reads one outside spelling for one lookup. `normalize_ticker` would also fold spaces and strip dashes;
    that is not measured, so it could change a lookup. Cost if wrong: three one-line spellings outside the leaf.
- **The fails index still imports `names`** (`names_agree`, its relabel rule's name check). names is a leaf too; the
  relabel rules stay in the index (step 12's decision), and step 16 moves `FtdClient` (the client) into the sources
  package. ftd, midas and nasdaq_halts no longer import observations (a test pins it).
- **The cycle is gone.** observations imports `identifiers` and `names` only; figi_resolution `identifiers` and
  `names`. A test pins that neither imports the other.
- **No old name is re-exported.** The callers were updated:
  - the two fixture builders (`build_acquirer_gate_fixtures.py`, `build_line_fixtures.py`);
  - every package module;
  - test_continuation_evidence.
  The README names none of them. `observations.normalize_ticker` still resolves, because observations imports it,
  but nothing imports it from there.
- **Tests.**
  - Added: tests/test_identifiers.py, 17 tests at the leaf's interface: each spelling and each reader, with the real
    cases the code cites (BRK-B/BRKB, LGF-B/LGFB, UAC-C, EHAB-WI, Liberty Capital's LCAPA name, Lennar's class B,
    Viacom's class A quote, CAA's Lennar class A and B, GLIBA's Series C, SunPower's CL A, Continental's CL-B,
    Celanese's SER A, MSG Networks' and Starz's OpenFIGI names, Comcast Special, Lions Gate's non-voting class B,
    Envision Healthcare's Series A-1).
  - Moved, every assertion kept: test_figi_resolution's two class and placeholder tests and its `bloomberg_ticker`
    lines; test_observations' `normalize_ticker` and `regular_way` tests; test_form25's `letter_hint` test;
    test_identity_rules' OpenFIGI-name test; test_own_shares' `class_of` test. 7 tests deleted from the old files.
  - test_import_closure: `identifiers` joins `exit_kind` as a leaf; the data clients read the spelling, not the
    observations (3); observations and figi_resolution import neither of each other; dlret's closure loses
    observations and names.
  - Suite: 3417 passed, 46 xfailed (step 12: 3402).
- **The gate.** The replay is SAME against `accepted4_out` and refuses no request (`refused 0`, as the reference).
  Its log equals step 12's byte for byte.
- **pipeline.py: 1637 lines to 1638** (an import and a wrapped line). identifiers.py is new, 203 lines;
  figi_resolution.py lost 42, observations.py 29.

### Step 14: the finder builds its own trading record

- **One trading-record type per security: `trading_record.TradingRecord`, a new module that replaces
  `last_trade.OwnTrading`.** The finder and the last trade module read the same record; `Dating`'s `trading=` now
  takes it (it asks `tickers`, `taken` and `trades_until`, as before). Its interface:
  - two constructors: `TradingRecord.observed(security, fails, cusips[, sightings])` (its sightings
    `history.ticker_sightings` unless given; its last era's ticker and name, its eras' first and last day) and
    `TradingRecord.added(security, ticker, span, fails, cusips)` (stage 9d, below);
  - what it is known by: `ticker`, `known_from`, `known_until`, `expected_name`, `own_tickers`, `has_cusips`;
  - what the sightings say: `ticker_on(day)`, `last_seen`, `seen_after(day)`, `seen_in_fails_after(day)`, `span`,
    `tickers(lo, hi)`;
  - what its own CUSIPs' rows say: `trades_after(day)`, `traded_within(day, days)`, `cusip_switches`,
    `letter_hint`, `taken(ticker, lo, hi)`, `trades_until()`.
  - Moved in, each with its rule unchanged: `history.ticker_on` and `history.own_last_seen` (their only callers were
    the context builder and stage 5's review row); `last_trade.ticker_taken`, `last_row_trade_day` and
    `PLACEHOLDER_PRICE` (rule 3's tenure and rule 4's floor are the record's answers; `Dating` asks the record);
    `pipeline._cusip_switches`, `_rows_near` and `_security_ref`'s letter hint.
  - Alternative: grow `OwnTrading` inside last_trade.py. Rejected: CUSIP switches, rows near a Form 25 and a
    sibling's span are the finder's reads, not dating; the module would hold the finder's facts behind the last
    trade date's name.
  - Cost if wrong: one more module (210 lines). last_trade.py imports the type only under `TYPE_CHECKING`, so its
    import closure is unchanged.
- **The finder's interface, `SecurityContext`, is five fields, all data, frozen:** `record`, `siblings` (the
  records of its issuer's securities, itself among them: added when absent), `listed_today`, `other_cik`,
  `resolution_source`. It derives `security`, `refs`, `own_ref` (each a `form25.SecurityRef` with the record's
  letter hint) and `spans` (each sibling's `TradingRecord.span`). Before: 16 fields, five of them closures over the
  sightings and rows (`ticker_on`, `seen_after`, `ftd_seen_after`, `trades_after`, `cusip_rows_near`) and two with
  "unknown" defaults (`has_cusips=None`, `trading=OwnTrading()`) that only hand-built contexts used.
  - Alternative: `find(record, siblings=, listed_today=, other_cik=, resolution_source=)` with no context type.
    Rejected: the context is passed to a dozen private methods, and its derived refs and spans are computed once per
    search.
  - Cost if wrong: a later sub-plan that needs a new fact of the security's trading adds a query to the record, not
    a field to the context.
- **The constructor sits next to the finder: `delistings.SecurityContexts`.** `SecurityContexts(records,
  other_ciks=, resolution_source=)` groups the records by issuer CIK (in the records' order, as the old builder
  grouped `securities.values()`; a security with no CIK stands alone) and answers `contexts(security, listed)`;
  `SecurityContexts.observed(securities, cusips, fails, ...)` builds each record over its own CUSIPs. `pipeline.
  _context_builder` and its three helpers are gone. Stage 5 reads the records' sightings back as its answer
  (`_DelistingSearch.sightings`) and its error row's last sighting from the record.
  - The sightings are built by the constructor (`history.ticker_sightings`), no longer passed in. Alternative: stage
    5 builds them and passes them, as before. Cost if wrong: none to output; one place builds them now, and the
    harnesses no longer repeat the comprehension.
- **One context for every worker count.** The warm pass and the sequential pass ask the one `SecurityContexts`
  object, so a security's record (and each sibling's) is built once and both passes read it. Its cached answers
  (rows, last sighting, switches, letter hint) are computed from the one fails index, which no query changes during
  stage 5 (step 12), so a warm thread and the sequential pass get the same answers whichever computes them first.
  Before, each pass built its own context; the sibling refs were built once per builder, the rows and switches once
  per call. A test pins that both passes read the same record objects.
- **Stage 9d searches an added successor from its span and CUSIPs, with no era or observation made up.**
  `TradingRecord.added(a.security, a.ticker, (first, last or the run date), fails, cusips)`: its sightings are the
  span's two days under its ticker (source `SPAN`, `history.span_sightings`, spelled as `ticker_sightings` spells
  them) and its CUSIPs' fails rows; its known days are the span, its expected name the security's own, its own
  tickers its ticker and its line's. The siblings are the run's securities of its issuer (records over the current
  index), then the added record: the order of the old one-off world. `_SuccessorEndings.securities` now holds the
  security as the run added it (no era); stage 7 reads only its `cusip_sightings`, to which the old era's
  observations (no CUSIP) added nothing.
  - Its issuer's lookup tier is none: "security_master". Before, `Identity.resolution_source` was asked over the
    made-up era key `TICKER@first`, which would have taken an observed era's tier only if an observed era of that
    ticker began the same day. Both 9d endings of the replay (DYN, BBG000BNLX91; ODP, BBG00R24W7X2) publish
    security_master either way. `_successor_endings` loses its `resolution_source` parameter.
  - Alternative: keep the made-up era and observations. Rejected by the step: they existed only to feed the
    builder, and a sighting labelled "observation" for a day nobody observed is a misreading waiting to happen.
  - Cost if wrong: the span's days are sightings with source `SPAN`; no reader keys on `OBSERVATION` for a 9d
    sighting (the fallback, which reads `FTD`, never runs in 9d).
- **The early window and the fallback's early group share one judgement, `_judge_early`** (the replay stays SAME):
  the main scan's `_judge`, quiet, against the security and the siblings alive on the filing date, the letter rule
  (`_names_other_letter`) when the security stands alone. `_early_group` repeated `_judge`'s checks by hand without
  that rule. It now judges each neighbour with `_judge_early` over a scratch `_Scan` (no review item; the main
  scan's state untouched), and reads the issuer's names once, passed in from `find` (which already read them),
  instead of once per early filing.
  - Consequence outside the replay: the fallback's early group no longer takes, for a letterless security alone, an
    early Form 25 naming another class letter (final review M1's rule, which the early window and the other CIK's
    reach already applied). A test pins it, and fails under the old rule (checked with a probe).
  - Alternative: keep both. Cost if wrong: a case like that, if the replay had one, would lose a fallback ending; the
    replay has none.
- **`has_cusips` and the unknown defaults are gone.** A record always knows its CUSIPs, so the 5h rule reads
  `not record.has_cusips`. test_identity_rules' WW guard looped over `has_cusips` True and None; None no longer
  exists, so the guard runs once, with a CUSIP. `_fallback_date` takes the last sighting, not a context (it is a
  pure function of it).
- **Tests.**
  - Added: tests/test_trading_record.py, 20 tests at the record's interface (5 new: an observed security's
    sightings, a fails row under an own ticker after a day, a sibling's span, the CUSIP switches, an added
    successor's span record; 15 moved, below). test_delistings.py, 6 at the finder's interface: the constructor's
    siblings and spans (the deleted run test's two classes and OTC tail), its other CIK and lookup tier, one record
    for every pass, a context from a record alone, an added successor searched from its span beside its issuer's
    earlier security, and the shared early judgement.
  - Moved, every assertion kept: test_last_trade's six tenure, rows' last day and window-tickers tests;
    test_history's two ticker-on-a-day tests and the line-follow last sighting; test_pipeline's two `own_last_seen`
    tests and its four `_one_security_context`/`_security_ref` tests (trading after a day under any symbol, rows
    near a day, unassigned and pair-off rows, the letter hint).
  - Deleted, covered at the record and the constructor: test_pipeline's two whole-run tests that replaced
    `pipeline.DelistingFinder` with a recorder to read the context's last sighting, sightings after a day, fails
    sightings, window tickers and sibling spans.
  - The four hand-built contexts (test_delistings' `_ctx`, its fallback-date and no-era tests, test_identity_rules'
    WW) are built by the constructor over rows. Each scenario a lambda stated is now data: a later observation, an
    OTC row of the security's own CUSIP, 21 weekly rows at two prices (trading after a day), a row a day before a
    Form 25 (the late reach), two CUSIPs (the switch), a description naming class B (the letter hint), securities of
    the issuer as siblings. Three cases' observation dates moved to the last sighting the lambda gave (AET's
    ambiguity row 2018-11-28, CBS's 2019-12-06, Kraft Heinz's 2026-09-04). test_successor_endings' line successor
    now asserts that the stage hands back the security as the run added it, no era, in place of the made-up era's
    ticker.
  - The real-case harnesses (form25_cases, distress_cases, last_trade_cases, issuer_role_cases) build their context
    with `SecurityContexts.observed`; their outcomes are unchanged. test_identity_rules' 9d test no longer patches
    the builder.
  - test_import_closure: `trading_record` joins the classification modules that load no measurement module.
  - Suite: 3427 passed, 46 xfailed (step 13: 3417).
- **The gate.** The replay is SAME against `accepted4_out` and refuses no request (`refused 0`). Its log equals step
  13's byte for byte. The four-worker replay (`replay_w4.py`, `sec_workers=4`) differs from `accepted4_out` only in
  run_manifest.json's `sec_workers` key (the count it records), is SAME against step 7b's four-worker replay
  (`w4_7b_out`), and its log equals that one's byte for byte.
- **pipeline.py: 1638 lines to 1557.** delistings.py 671 to 714, last_trade.py 680 to 624, history.py 619 to 612;
  trading_record.py is new, 210 lines.
- **CONTEXT.md gains "Trading record"**, the concept the type is named after.

### Step 15: one truth-case type, reduced to the parts with one meaning and two definitions

- **Rejected for this program: re-keying the diagnosis set from its `sec_id` to an anchor the run resolves**
  (the candidate's full form, controller ruling). The truth file's keys, the loop's ledger keys (`mis|<case_id>|...`,
  `reg|<sec_id>|...`) and the regression exclusion (`regression.excluded`: the truth cases' sec_ids and their successor
  chains) all use the truth's sec_ids, and the shapes `no_ending` and `ending_moved` have no golden counterpart, so a
  shared anchor would need its own rules for them. Changing the key needs a design with the operator.
  - What it would buy: a rename needs no truth edit. `TruthSet.rename`, apply_5h's `--after-run`, update_truth's
    `renamed` and `excluded(id_changes=)` would go, and 5h's D.mismatches.sec_id 0 to 8 (settled in three ordered
    steps) would not happen; the (ticker, date)-keyed audit judge survived the same renames unchanged.
  - Cost of not doing it: the rename machinery stays, as it is today.
- **Where the shared parts live: truth.py, not a new module.** It now opens with what every truth set shares: the
  statuses and their rule, the error, the judgement and its tally, the flip rule, the note convention. Then the golden
  and audit format and judge, as before. diagnosis_truth imports the shared names from it (it already imported
  `TruthFileError`).
  - Alternative: a fourth truth module below truth, diagnosis_truth and truth_set. Rejected: about 100 lines with no
    behaviour of their own beside truth.py, whose name is the concept.
  - Cost if wrong: moving the shared block out is mechanical.
- **One status vocabulary.** `PASS` and `KNOWN_WRONG` are defined in truth.py only. diagnosis_truth imports them and
  keeps `RULING_PENDING`, the one status only its set has. scorecard's `D_PASS`/`D_KNOWN_WRONG` aliases are gone, and
  truth_set, truth_update and truth_build import the two from truth.
  - The rule is one function, `check_status(status, fixed_by, where, allowed)`: a status outside the set's own, and a
    known_wrong case with no fixed_by, are refused.
  - What changed: the golden loader's message is now "is not one of ['', 'pass', 'known_wrong']" (was "is not pass or
    known_wrong"), and a golden fixed_by of spaces is refused, as the diagnosis loader did. No row has one.
  - Alternative: define `RULING_PENDING` in truth.py too. Rejected: the golden loader refuses it, and a status defined
    beside the golden format reads as one a golden case could hold.
- **One error.** `DiagnosisTruthError` is deleted; its 55 references raise or expect `truth.TruthFileError`. No caller
  caught the subclass alone: every script catches `TruthFileError`.
  - Alternative: keep it as an alias. Rejected: two names for one error is what the step removes.
- **One judgement type: `truth.Judgement(case, mismatches)`, each a `truth.Mismatch(case_id, field, truth, library,
  wording="")`.** Both judges keep their rules and return it. `CaseJudgement` and diagnosis_truth's `Mismatch` are
  gone. A judgement holds (`ok`) with no mismatch, knows its `case_id`, and reads as `case_id: m; m`.
  - The golden judge's mismatches are now structured. The field is the checked column, or `security` (no single
    security at the ticker and date) or `ending` (no final ending), the diagnosis judge's own name for that. Five
    messages do not read as `<field> <library> != <truth>`: the missing security, the missing tickers, the early end,
    the missing final ending and the missing successor. They carry the judge's `wording`. A missing exit kind's
    library value is `(none)`, as the text said.
  - Every text is unchanged. With the base code and this step's, all 789 judgements of the golden set, the audit and
    the diagnosis set on output/ read alike, including the 97 failing ones, which cover every wording.
  - `TruthCase.case` is now `case_id` (the file's column stays `case`), so both case types are known by the same name.
  - Alternative: keep golden mismatches as strings and make `Judgement` generic over its mismatch type. Rejected: the
    tally's field count and the failure text would branch on the type.
  - Alternative: the default text for every golden mismatch. Rejected: golden_failures lines and their tests assert
    the texts, and the gate wants the same output.
  - Cost if wrong: `wording` is a second text path, so a judge that words a mismatch must still set its field. The
    tests assert field and text together.
- **One counting: `truth.tally(judgements, key=)` gives a `Tally`.** It holds cases, matching, errors, pass holding
  and failing, known_wrong, now right, mismatches by field (through the set's `key`: the diagnosis set passes
  `field_key`, so a leg's fields count as `legs`) and the failing pass cases' text.
  - `_truth_lines` (G and A) and `_diagnosis_lines` (D) read it.
  - The golden failures are taken from the same tally. `build` judged the golden set a second time before.
  - `V.audit.confirmed_but_wrong` stays in the scorecard: it reads uncertain.csv.
- **One flip rule: `truth.now_right(judgements)`, the case ids of every known_wrong case whose judgement holds.**
  `TruthSet.flip` applies it through `move_status` (one change-log row, reason `truth.NOW_MATCHES`, moved from
  truth_set); the order and result are unchanged. `Tally.now_right` counts it, so `G.known_wrong_now_right` and
  `D.known_wrong_now_right` are exactly what a flip moves.
  - The golden set's flip is new: `truth.flip(path, view)`. Each flipped row gets status pass, a blank fixed_by and a
    note (`<note>; the library now matches, was known_wrong until <fixed_by>`). No other cell changes, and the file
    is written (`write_truth`) only when a case flipped. Both committed golden and audit files round-trip
    byte-identically through its reader and writer (checked).
  - The note stands in for a change log. The hand flips did not agree: 9c12f60 wrote no note, ca58ee1's
    flip_golden.py wrote "passes since <plan>, was known_wrong until <fixed_by>".
  - Alternative: a change log for the golden file. Rejected: a new data file, and data/ stays untouched.
  - Alternative: no note. Rejected: fixed_by is cleared, and nothing else would record which plan the case waited for.
  - `noted` moved from truth_set to truth: both sets' notes follow it.
- **The command: `scripts/scorecard.py --flip`, both sets (`scorecard.flip(snapshot, config)`, which returns
  `Flipped`).** It prints the flipped ids of each set.
  - The diagnosis set is flipped with its commit, and only when the run has a contract, the D lines' rule: without
    one, a known_wrong no_ending case would hold on nothing (a test pins it).
  - `ScorecardConfig` gains `golden_file` and `diagnosis_file`: the files `load_config` read, None when the config
    names none or the file is missing.
  - The loop's `Round.close` still flips the diagnosis set by the same rule; `--flip` serves a plan with no round,
    and the golden set, which had no command.
  - Alternative: `--flip` for the golden set only. Rejected: two commands for one rule, and a plan that fixes cases
    of both sets outside a loop would flip one by command and the other by hand.
  - Alternative: the script reads the config's paths itself, as `--raise-floor` reads the floor. Rejected: a second
    reading of where the truth files are.
  - Nothing in data/ was flipped. Against output/ no case of either set is right now (G and D `known_wrong_now_right`
    are 0), and a test runs both flips on copies of the real files and finds nothing to write.
- **The two meanings of `last_trade_date`, named in code; the CSV columns are unchanged.**
  - Golden and audit: `TruthCase.final_last_trade_date`, delistings.csv's internal day of the lifecycle's final
    ending (the chain's: a successor's when the chain continues). The judge's local `final` says it is that row.
  - Diagnosis: the scored `last_trade_date` is the contract's published day of the security's own last ending.
    `internal_last_trade_date` is delistings.csv's day of that same ending; the judge's local is `internal`.
  - Both readings are stated in both modules' docstrings, `TruthCase`, `DiagnosisCase` and `Mismatch`, and in
    CLAUDE.md. A golden mismatch's field stays `last_trade_date`, its file's column, so its text is unchanged.
  - A test pins the golden reading: the successor's day holds, the security's own ending's day does not.
  - Alternative: call the golden attribute `internal_last_trade_date`. Rejected: the diagnosis name means the
    security's own last ending, the golden one the chain's final ending, so one name would join two readings again.
  - Alternative: a `published_last_trade_date` property on `DiagnosisCase`. Rejected: no caller; the judge reads the
    scored fields by name from `SCORED`.
- **Deletion test, part by part.**
  - The statuses and the error remove two aliases and a subclass.
  - The judgement type removes a class pair and a counting block.
  - The flip rule gives the golden set a code path where there was none.
  - The naming is docstrings and one attribute.
  - No part only moves complexity, so none was skipped.
- **Tests.**
  - Added in tests/test_truth.py (31 to 45 collected), at the shared interface:
    - the status rule on both loaders (3 cases);
    - pass and known_wrong in both sets, ruling_pending only in the diagnosis set;
    - a mismatch's and a judgement's text;
    - the tally's counts, and its key;
    - one tally over both judges' judgements;
    - the flip rule's order;
    - the golden flip: only the flipped row's line changes, and a second flip writes nothing;
    - no write when nothing flips;
    - both flips on copies of the real files against output/: nothing flips, no byte changes;
    - the golden last trade date's reading.
  - Strengthened: the golden judge's eight field cases now assert the field with the text.
  - Added in test_scorecard (2): `flip` on both sets, and the diagnosis set left alone without a contract.
  - Added in test_scorecard_script (3): `--flip` flips both and prints the ids; a flip failure (a bad file, a failed
    write) exits 2.
  - Moved: test_truth_set's `noted` test, to test_truth.
  - Rewritten at the interface, with the same assertions:
    - every `DiagnosisTruthError` expectation, now `TruthFileError`;
    - `TruthCase(case=...)`, now `case_id`;
    - the golden judge's string comparisons, now through `str`.
  - Suite: 3445 passed, 46 xfailed (step 14: 3427).
  - tests/test_golden_lifecycles.py keeps 44 passed, 8 strict xfails, and tests/test_diagnosis_truth_cases.py keeps
    284 passed, 37 strict xfails. Their docstrings name `--flip`.
- **The gate.**
  - The replay is SAME against `accepted4_out` (scorecard.json's G, A, D and V lines included). It refuses no request
    (`refused 0`), and its log equals step 14's byte for byte.
  - scripts/scorecard.py on output/ printed the same output before (86c9bc7's src and scripts) and after: plain,
    `--check` (exit 0), `--lifecycles`, and `--check --base ca58ee1` with the loop's ledger (118 lines,
    D.unexplained_regressions 0, exit 0).
  - `git diff --stat 86c9bc7 -- data` is empty.
- **pipeline.py: 1557 lines, unchanged.** truth.py went from 221 to 361 lines, diagnosis_truth.py from 309 to 291,
  scorecard.py from 368 to 391, truth_set.py from 503 to 498, and scripts/scorecard.py from 119 to 132.
- **CONTEXT.md is unchanged:** no module is named after a new concept. "Truth case" and "truth set" already cover
  the terms.

### Step 16: the package layout: concept subpackages, imports one way, a lazy root

- **The layout.** The 82 flat modules move (`git mv`, history follows) into nine subpackages; `pipeline.py` stays at
  the root beside a lazy `__init__.py`:
  ```
  delist_detection/
    __init__.py   lazy: importing the package loads none of its modules
    pipeline.py   the run
    vocabulary/   the leaves, each importing nothing of the package (6)
    sources/      the SEC, OpenFIGI, Nasdaq and LLM clients and their plumbing (17)
    filings/      what SEC filings say, read by several stages (4)
    outputs/      what a run publishes, as rows (11)
    identity/     a security's identity, stages 1 to 4c (11)
    endings/      every delisting, found, dated and classified, stages 5 to 9g (12)
    terms/        what one share of a merger ending became, stage 8 (9)
    measurement/  how far a published run is from the truth (10)
    handling/     delistings.csv for training and backtests (2)
  ```
  - How each module was placed: by what it imports and what imports it, read from the import graph at 78f99b2
    (`/tmp/claude/delist_detection/arch/s16/graph.py`: top level, inside a function and under `TYPE_CHECKING`; the
    move itself is `s16/move.py`, and `s16/layout.py` holds the placement). Under the final placement
    only 5 of the graph's edges broke the direction; 3 of them were `DelistRecord` (below), 2 are the type-only
    exceptions.
  - Each subpackage's `__init__.py` is its docstring only: what it holds and what it imports.
- **The direction.**
  - The vocabulary imports nothing; sources import the vocabulary; filings and outputs import sources; identity
    imports filings and outputs; endings import identity; terms import endings. Each also imports everything below
    what it names.
  - measurement and handling import outputs and the vocabulary. Of the sources, the pure subpackages (outputs,
    measurement, handling) read only the plumbing that loads no client: `atomic_io` (the truth files, scorecard.json
    and the manifest are written atomically) and `sec_stats` (the manifest's counters, the degraded watch).
  - Nothing imports `pipeline.py`.
- **Named exceptions: two, both type only (`TYPE_CHECKING`), so neither loads anything.**
  - `outputs/dlret.py` names `terms.llm_merger_extractor.MergerTerms`: a `MergerInputs` carries the LLM's answer, and
    the value rule reads its published legs. The type is the extractor's, which builds it.
  - `outputs/degraded.py` names `endings.delistings.Delisting`: the `resolution_degraded` flag goes on a delisting's
    own row.
  - Alternative: a Protocol in outputs for each. Rejected: a second type for one object, written only to satisfy the
    test. Cost if wrong: two lines of the exception table; the test fails when either becomes a runtime import.
- **Where the code changed the proposal** (each with the alternative and its cost):
  - **A `vocabulary/` subpackage holds the six leaves** (identifiers, names, trading_calendar, crsp_codes, exchanges,
    exit_kind), not identity, endings, measurement and handling.
    - Why: the data clients (ftd, midas, nasdaq_halts) read the ticker spelling, the names and the calendar, and
      dlret reads the bucket and exchange enums. In their concept subpackages, sources would import identity and
      endings, and outputs would import handling.
    - Alternative: leaves in their concept subpackages, and the test exempts any import of a module that imports
      nothing. Rejected: every subpackage would import four others, and the picture would read as a web.
    - Cost if wrong: six modules move again.
    - exit_kind keeps its name (step 8a's open point). It is the row vocabulary, now `vocabulary/exit_kind.py`.
      Renaming it would touch 21 modules' imports and every doc for a name, in the step that moves everything.
  - **`filings/` is its own subpackage below identity** (evidence, form25, listing_status, filing_search), not
    `endings/filings`.
    - Why: the identity stages read evidence's name readers (issuer_record, ticker_resolver, issuer_in_force,
      identity, line_follow), and form25 and listing_status read evidence.
    - Alternative: evidence in identity, the rest in endings. Rejected: evidence also holds the 8-K item readers the
      classifier and the last trade date read.
    - Cost if wrong: one more subpackage of four modules.
  - **outputs sits below the stages, not above them.**
    - Why: every stage writes into it and it reads none of them. `ReviewItem` (8 modules), `DelistingKey` (5), the
      SEC meter and the degraded watch (identity, the line follow, the merger value), the value inputs and the price
      answers (the merger value, the payout gate).
    - verdict and run_snapshot go to outputs (proposal: measurement): the contract reads both, the verdict column and
      the snapshot it is built from. In measurement, outputs and measurement would import each other.
    - history stays in identity (proposal: outputs?): it is the security's dated history, which the finder, the
      trading record and the acquirer line read.
    - Alternative: outputs split in two, the stages' records (store, review_triage, degraded, manifest) below and the
      tables (contract, verdict, ...) above. Rejected: once `DelistRecord` moved, the tables read nothing above
      outputs either, so one subpackage holds.
    - Cost if wrong: a reader expects outputs at the end of the run; the subpackage's docstring and CLAUDE.md say why.
  - **The one class move: `DelistRecord` from `endings/classifier.py` into `outputs/reconstruction.py`**, beside the
    `EnrichedDelistRecord` it becomes.
    - reconstruction, handling, qlib_adapter, payout_extractor and llm_merger_extractor imported the classifier for
      it. Measured at 78f99b2 through the root, and now: handling 33 package modules (with `requests`) to 7,
      qlib_adapter 35 to 10, reconstruction 34 to 6 (and, the root no longer loading the clients, store 34 to 2 and
      verdict 37 to 7).
    - Alternative: a new `outputs/delist_record.py`. Rejected: one dataclass, and reconstruction already turns it into
      the row. Alternative: the proposal's `endings/record`. Rejected: outputs sits below endings.
    - `Delisting` stays in `endings/delistings.py` (proposal: endings/record): it carries the last trade, the Form 25,
      the rewrites and the own-share reading, all endings' types; only degraded names it, type only.
    - Cost if wrong: 24 test files and 3 scripts import it from its new path.
  - **line_follow, added_securities and ticker_evidence go to identity** (proposal: endings/successors and
    measurement).
    - line_follow: CONTEXT.md's Identity says the line follow carries identity past the observations; it is stage 4b,
      before the Form 25 search, and imports nothing of endings.
    - added_securities: history imports it (its one history row per added security).
    - ticker_evidence: what ties a placeholder's ticker to its CIK, an identity fact the verdict reads; it imports
      nothing.
  - **exchanges goes to the vocabulary** (proposal: handling): dlret reads `Exchange`.
  - **ftd stays whole in sources.** Steps 12 and 13 foresaw moving only `FtdClient`. The fails index's rules read only
    the vocabulary (names, identifiers, the calendar), so the whole module sits in sources without breaking the
    direction. Alternative: `FtdIndex` into identity. Rejected: 500 lines split for no direction gained. Cost: the
    index's relabel rules live beside the client.
  - **No nested subpackages.** endings, the largest group after sources, has 12 modules. The proposal's
    `endings/{record, filings, classify, dating, finder, successors}` would leave dating and record one module each
    once filings moved down and the record stayed with the finder.
  - **pipeline.py stays whole at the root** (proposal: "stage order only"). Its stage functions wire the clients
    into each stage; moving them out is a deepening per stage, not a move. The replay also patches
    `pipeline.listing_answers` and `listed_today` by module.
    - Cost: pipeline.py is still 1557 lines.
  - **Two names stutter: `identity/identity.py` and `handling/handling.py`.** Kept: CONTEXT.md and CLAUDE.md name the
    modules, and a rename is a second change.
- **The lazy root.** `import delist_detection` loads none of the package's modules (a test pins the empty closure).
  - It keeps, through a module `__getattr__`, the eight names the README and the scripts import from it:
    `EdgarClient`, `TickerResolver`, `DelistClassifier`, `PayoutExtractor`, `Exchange` and the three handling
    builders. Each is its module's own object, loaded on first use.
  - The other 13 are gone, since nothing in the repo used them: `CrspBucket`, `DLST_CODE_TO_BUCKET`,
    `bucket_for_code`, `EdgarSubmission`, `DelistRecord`, `TrainLabelAdjustment`, `BacktestExit`,
    `adjustments_from_rows`, `normalize_exchange`, `SHUMWAY_NYSE_AMEX`, `SHUMWAY_NASDAQ`, `FirmMonthReturn`,
    `PayoutResult`.
  - The step 8a strict xfail `test_the_package_root_loads_no_client` passes, its xfail removed. The closures are now
    measured through the real root; the bare-root mode is gone.
- **No old path is kept.** Every import was updated: src (each relative import recomputed from the module's new
  place), tests, scripts, the diagnose-delisting skill's `sec.py`, README.md (the examples, the links and a layout
  tree by subpackage), CLAUDE.md, CONTEXT.md and docs/data-flow.md.
  - Left as written: the dated records (docs/superpowers/plans and specs, docs/validation, docs/research,
    docs/2026-09-28-handoff-validation.md) and this plan's earlier steps. They describe the code of their date, and
    some name modules that no longer exist (diagnosis_loop, bmp_correction, verdict_rules). Cost if wrong: a snippet
    copied from a dated plan fails at import, naming the old module.
  - Three module-relative repo paths count one more parent: `settings.REPO_ENV`, the manifest's git checkout and
    `llm_client`'s `.env`.
  - Logger names follow the module paths (`delist_detection.sources.edgar`, ...); the tests' `caplog` names were
    updated. A caller filtering logs by the old names needs the new ones.
- **The direction test: tests/test_import_closure.py**, from the real graph (ast, every module):
  - the root holds only `__init__` and `pipeline`, and every subpackage has a direction;
  - the directions have no cycle;
  - each subpackage imports only those its concept rests on (9 cases);
  - nothing imports the run;
  - each named exception is real and type only (2);
  - a pure subpackage reads only the sources' plumbing (3).
  - The closure tests: every vocabulary module loads nothing else (was 2 leaves, now 6); the handling loads no
    network client (2, new); importing the package loads none of its modules; each root name is its module's object,
    and the root has no other.
- **Tests.** Added 32 in test_import_closure (35 collected to 67), and the strict xfail now passes; none deleted.
  The import updates touched 131 test files and 27 scripts. Suite: 3478 passed, 45 xfailed (step 15: 3445 passed,
  46 xfailed).
- **The gate.**
  - The replay copy `/tmp/claude/delist_detection/arch/replay_layout.py` differs from `replay_wave1.py` in module
    paths and in one addition: every package module that imports `write_atomic` or `clean_orphan_temps` is patched,
    the lists are checked against the package's imports at start, and a missing target raises.
    - `manifest` and `scorecard` write the run's own outputs (run_manifest.json, scorecard.json) through
      `write_atomic`, so a plain no-op there would drop two files from the gate. The five modules outside the
      original list get a patch that makes a write under cache/ a no-op, lets one under the run's folder through,
      and raises on any other.
    - The diff (`diff -u replay_wave1.py replay_layout.py`):

      ```diff
      --- /tmp/claude/delist_detection/wave1/replay_wave1.py	2026-10-04 17:02:25
      +++ /tmp/claude/delist_detection/arch/replay_layout.py	2026-10-08 01:18:45
      @@ -23,6 +23,7 @@

       ROOT = Path.cwd()
       AS_OF = date(2026, 9, 25)
      +OUT: Path | None = None        # the run's folder: the one place a write outside the cache may go (step 16)

       # each sub-plan's expected changed set (its own replay's measured list), keyed by sub-plan
       def _expected_of(path: str) -> set[str]:
      @@ -77,20 +78,69 @@

           def no_write(*a, **k):
               return None
      -    for mod in ("edgar", "sec_http", "midas", "nasdaq_halts", "openfigi", "ticker_resolver", "cik_lookup", "ftd",
      -                "llm_merger_extractor"):
      -        m = __import__(f"delist_detection.{mod}", fromlist=["x"])
      -        for name in ("write_atomic", "clean_orphan_temps"):
      -            if hasattr(m, name):
      -                setattr(m, name, no_write)
      -    import delist_detection.atomic_io as aio
      -    import delist_detection.sec_limiter as lim
      +    import delist_detection.sources.atomic_io as aio
      +    import delist_detection.sources.sec_limiter as lim
      +    # Every package module that imports write_atomic or clean_orphan_temps, with the names it imports (step 16), as
      +    #   grep -rnE "from \.+[a-z_.]*atomic_io import" src/delist_detection
      +    # lists them. NO_WRITE is the original list at its new paths (cik_lookup imports neither name, so it is not here:
      +    # its download writes through sec_http's): every write of theirs is a cache write, a no-op as before. The modules
      +    # of OUTSIDE_CACHE write outside the cache (outputs.manifest's run_manifest.json and measurement.scorecard's
      +    # scorecard.json are the run's own outputs; the truth and loop modules write no file in a run): a write under
      +    # cache/ is a no-op, one under the run's folder goes through, any other raises. A listed target that does not
      +    # exist raises, and so does a package module the lists miss.
      +    NO_WRITE = {
      +        "sources.edgar": ("write_atomic", "clean_orphan_temps"),
      +        "sources.sec_http": ("write_atomic",),
      +        "sources.midas": ("write_atomic", "clean_orphan_temps"),
      +        "sources.nasdaq_halts": ("write_atomic", "clean_orphan_temps"),
      +        "sources.openfigi": ("write_atomic", "clean_orphan_temps"),
      +        "identity.ticker_resolver": ("write_atomic", "clean_orphan_temps"),
      +        "sources.ftd": ("clean_orphan_temps",),
      +        "terms.llm_merger_extractor": ("write_atomic", "clean_orphan_temps"),
      +    }
      +    OUTSIDE_CACHE = {
      +        "outputs.manifest": ("write_atomic",),
      +        "measurement.scorecard": ("write_atomic",),
      +        "measurement.truth": ("write_atomic",),
      +        "measurement.regression": ("write_atomic",),
      +        "measurement.loop_round": ("write_atomic",),
      +    }
      +    import ast
      +    import importlib
      +    pkg = Path(aio.__file__).resolve().parent.parent
      +    found: dict[str, set[str]] = defaultdict(set)
      +    for path in pkg.rglob("*.py"):
      +        for node in ast.walk(ast.parse(path.read_text())):
      +            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("atomic_io"):
      +                names = {a.name for a in node.names} & {"write_atomic", "clean_orphan_temps"}
      +                if names:
      +                    found[".".join(path.relative_to(pkg).with_suffix("").parts)] |= names
      +    listed = {m: set(n) for m, n in {**NO_WRITE, **OUTSIDE_CACHE}.items()}
      +    if dict(found) != listed:
      +        raise RuntimeError(f"the patch lists differ from the package's imports: {dict(found)} != {listed}")
      +    real_write = aio.write_atomic
      +    cache_dir = (ROOT / "cache").resolve()
      +
      +    def outside_cache(path, data):
      +        p = Path(path).resolve()
      +        if p == cache_dir or cache_dir in p.parents:
      +            return None
      +        if OUT is not None and OUT in p.parents:
      +            return real_write(path, data)
      +        raise RuntimeError(f"replay: a write outside cache/ and the run's folder: {path}")
      +    for patch, table in ((no_write, NO_WRITE), (outside_cache, OUTSIDE_CACHE)):
      +        for mod, names in table.items():
      +            m = importlib.import_module(f"delist_detection.{mod}")
      +            for name in names:
      +                if not hasattr(m, name):
      +                    raise AttributeError(f"replay: delist_detection.{mod} has no {name} to patch")
      +                setattr(m, name, patch)
           aio.clean_orphan_temps = no_write
           lim.throttle = lambda *a, **k: None
           lim.use_machine_wide_limit = lambda *a, **k: None

      -    from delist_detection.edgar import EdgarClient
      -    from delist_detection.openfigi import OpenFigiClient
      +    from delist_detection.sources.edgar import EdgarClient
      +    from delist_detection.sources.openfigi import OpenFigiClient
           real_text, real_raw = EdgarClient.fetch_filing_text, EdgarClient.fetch_filing_raw

           def text(self, cik, accession, primary_doc):
      @@ -112,7 +162,7 @@

           # 5d: a halt day the cache lacks reads as no halts (the feed's 404), not as a failed read: 5d asks new days
           # (the Form 25 day when nothing states the last trade, the text days the new reader finds)
      -    from delist_detection.nasdaq_halts import NasdaqHaltClient, parse_halts_rss
      +    from delist_detection.sources.nasdaq_halts import NasdaqHaltClient, parse_halts_rss
           halt_days: list[str] = []

           def halts_on(self, day):
      @@ -136,17 +186,17 @@


       def _clients(index):
      -    from delist_detection.cik_lookup import CikLookupClient
      -    from delist_detection.classifier import DelistClassifier
      -    from delist_detection.edgar import EdgarClient
      -    from delist_detection.ftd import FtdClient
      -    from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor
      -    from delist_detection.midas import MidasClient
      -    from delist_detection.nasdaq_halts import NasdaqHaltClient
      -    from delist_detection.openfigi import OpenFigiClient
      -    from delist_detection.payout_extractor import PayoutExtractor
      +    from delist_detection.sources.cik_lookup import CikLookupClient
      +    from delist_detection.endings.classifier import DelistClassifier
      +    from delist_detection.sources.edgar import EdgarClient
      +    from delist_detection.sources.ftd import FtdClient
      +    from delist_detection.terms.llm_merger_extractor import LLMMergerTermsExtractor
      +    from delist_detection.sources.midas import MidasClient
      +    from delist_detection.sources.nasdaq_halts import NasdaqHaltClient
      +    from delist_detection.sources.openfigi import OpenFigiClient
      +    from delist_detection.terms.payout_extractor import PayoutExtractor
           from delist_detection.pipeline import Clients
      -    from delist_detection.ticker_resolver import TickerResolver
      +    from delist_detection.identity.ticker_resolver import TickerResolver
           import delist_detection as _dd                 # the scripts beside the source tree on PYTHONPATH (5h)
           scripts = Path(_dd.__file__).resolve().parents[2] / "scripts"
           spec = importlib.util.spec_from_file_location("cu", scripts / "classify_universe.py")
      @@ -173,12 +223,14 @@


       def run(out_dir: str, baseline: str) -> None:
      +    global OUT
      +    OUT = Path(out_dir).resolve()
           refused, blank = offline()
           import delist_detection.pipeline as P
      -    from delist_detection.observations import ObservationIndex, load_observations
      -    from delist_detection.review_triage import load_decisions
      -    from delist_detection.scorecard import load_config
      -    from delist_detection.store import read_table
      +    from delist_detection.identity.observations import ObservationIndex, load_observations
      +    from delist_detection.outputs.review_triage import load_decisions
      +    from delist_detection.measurement.scorecard import load_config
      +    from delist_detection.outputs.store import read_table
           listed = _listed_from_output()
           P.listing_answers = lambda figi, ids: {}
           P.listed_today = lambda figi, sid, **k: listed.get(sid)
      @@ -246,8 +298,8 @@
           """D.mismatches on each folder: plain (the truth file as written), and with the truth rows renamed by that
           folder's contract/id_changes.csv first (as truth_loop_round.py does, 5h's judge)."""
           from delist_detection import diagnosis_loop as dl
      -    from delist_detection.diagnosis_truth import LibraryRows, judge_case, load_legs, parse_rows
      -    from delist_detection.lifecycle import Tables
      +    from delist_detection.measurement.diagnosis_truth import LibraryRows, judge_case, load_legs, parse_rows
      +    from delist_detection.measurement.lifecycle import Tables
           legs = load_legs(ROOT / "data/diagnosis_truth_legs.csv")
           rows = dl.read_csv(ROOT / "data/diagnosis_truth.csv")
           libs = [LibraryRows.of(Tables.read(Path(d))) for d in (base, new)]
      ```

  - The replay ran twice at one worker: on the moves commit (eager root) and on the final tree (lazy root). Before
    each a marker was touched; `find cache -newer <marker>` listed nothing after it.
  - Both are SAME against `accepted4_out`, refuse no request (`refused 0`, no uncached text or halt day), and their
    logs equal step 15's `s15_run.log` line for line, byte for byte (no path appears in it).
  - The 4-worker replay (`replay_layout_w4.py`, `sec_workers=4`): every table SAME against `accepted4_out`,
    run_manifest.json differing only in `sec_workers`; SAME against step 14's four-worker replay (`s14_w4_out`), and
    its log equals that one's byte for byte.
  - `scripts/scorecard.py --check` on output/ prints what step 15's src and script print (exit 0), and `--check
    --base ca58ee1` gives its 118 lines, D.unexplained_regressions 0, exit 0.
  - Every script in scripts/ imports cleanly, and each with argparse answers `--help` (26 of 29;
    build_last_trade_fixtures, regen_payout_fixtures and verify_altair have no argparse and were imported only).
- **pipeline.py: 1557 lines, unchanged.** Its imports were rewritten in place (one rewrapped).
- **CONTEXT.md gains "Ending"** (the concept `endings/` is named after, used throughout the glossary but never
  defined) and a short "Package layout" note naming which subpackages are domain concepts.
- **The moved modules** (every old path under `src/delist_detection/`):

| Old path | New path |
|---|---|
| `identifiers.py` | `vocabulary/identifiers.py` |
| `names.py` | `vocabulary/names.py` |
| `trading_calendar.py` | `vocabulary/trading_calendar.py` |
| `crsp_codes.py` | `vocabulary/crsp_codes.py` |
| `exchanges.py` | `vocabulary/exchanges.py` |
| `exit_kind.py` | `vocabulary/exit_kind.py` |
| `atomic_io.py` | `sources/atomic_io.py` |
| `settings.py` | `sources/settings.py` |
| `retries.py` | `sources/retries.py` |
| `sec_limiter.py` | `sources/sec_limiter.py` |
| `sec_stats.py` | `sources/sec_stats.py` |
| `fatal.py` | `sources/fatal.py` |
| `html_text.py` | `sources/html_text.py` |
| `edgar.py` | `sources/edgar.py` |
| `sec_http.py` | `sources/sec_http.py` |
| `openfigi.py` | `sources/openfigi.py` |
| `cik_lookup.py` | `sources/cik_lookup.py` |
| `ftd.py` | `sources/ftd.py` |
| `midas.py` | `sources/midas.py` |
| `nasdaq_halts.py` | `sources/nasdaq_halts.py` |
| `llm_client.py` | `sources/llm_client.py` |
| `prefetch.py` | `sources/prefetch.py` |
| `capabilities.py` | `sources/capabilities.py` |
| `evidence.py` | `filings/evidence.py` |
| `form25.py` | `filings/form25.py` |
| `listing_status.py` | `filings/listing_status.py` |
| `filing_search.py` | `filings/filing_search.py` |
| `store.py` | `outputs/store.py` |
| `review_triage.py` | `outputs/review_triage.py` |
| `degraded.py` | `outputs/degraded.py` |
| `manifest.py` | `outputs/manifest.py` |
| `run_snapshot.py` | `outputs/run_snapshot.py` |
| `verdict.py` | `outputs/verdict.py` |
| `contract.py` | `outputs/contract.py` |
| `dlret.py` | `outputs/dlret.py` |
| `payout_rule.py` | `outputs/payout_rule.py` |
| `price_requests.py` | `outputs/price_requests.py` |
| `reconstruction.py` | `outputs/reconstruction.py` |
| `observations.py` | `identity/observations.py` |
| `figi_resolution.py` | `identity/figi_resolution.py` |
| `security_master.py` | `identity/security_master.py` |
| `ticker_resolver.py` | `identity/ticker_resolver.py` |
| `issuer_record.py` | `identity/issuer_record.py` |
| `issuer_in_force.py` | `identity/issuer_in_force.py` |
| `identity.py` | `identity/identity.py` |
| `history.py` | `identity/history.py` |
| `added_securities.py` | `identity/added_securities.py` |
| `ticker_evidence.py` | `identity/ticker_evidence.py` |
| `line_follow.py` | `identity/line_follow.py` |
| `delistings.py` | `endings/delistings.py` |
| `trading_record.py` | `endings/trading_record.py` |
| `classifier.py` | `endings/classifier.py` |
| `end_of_era.py` | `endings/end_of_era.py` |
| `distress.py` | `endings/distress.py` |
| `exchange_terms.py` | `endings/exchange_terms.py` |
| `own_shares.py` | `endings/own_shares.py` |
| `continuation_evidence.py` | `endings/continuation_evidence.py` |
| `last_trade.py` | `endings/last_trade.py` |
| `rewrites.py` | `endings/rewrites.py` |
| `successors.py` | `endings/successors.py` |
| `handoffs.py` | `endings/handoffs.py` |
| `merger_value.py` | `terms/merger_value.py` |
| `payout_gate.py` | `terms/payout_gate.py` |
| `payout_extractor.py` | `terms/payout_extractor.py` |
| `llm_merger_extractor.py` | `terms/llm_merger_extractor.py` |
| `filing_selection.py` | `terms/filing_selection.py` |
| `currency.py` | `terms/currency.py` |
| `acquirer_line.py` | `terms/acquirer_line.py` |
| `acquirers.py` | `terms/acquirers.py` |
| `acquirer_ticker.py` | `terms/acquirer_ticker.py` |
| `lifecycle.py` | `measurement/lifecycle.py` |
| `scorecard.py` | `measurement/scorecard.py` |
| `audit.py` | `measurement/audit.py` |
| `truth.py` | `measurement/truth.py` |
| `diagnosis_truth.py` | `measurement/diagnosis_truth.py` |
| `truth_set.py` | `measurement/truth_set.py` |
| `truth_build.py` | `measurement/truth_build.py` |
| `truth_update.py` | `measurement/truth_update.py` |
| `regression.py` | `measurement/regression.py` |
| `loop_round.py` | `measurement/loop_round.py` |
| `handling.py` | `handling/handling.py` |
| `qlib_adapter.py` | `handling/qlib_adapter.py` |

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
| 3 | One owner for rewriting an ending (review 3) | AZPN's stale flags | |
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
- **The interface is the reads and what they answer.** The reads are `submissions`, `filings` and `text`. The
  answers are `names`, `names_near`/`names_between`/`names_until`, `first_filed`, `existed_by`,
  `recent_form_dates` and `exact_holders` (SEC's name index, which moved from the resolver). `about=` asks for a copy
  current for an event (`edgar.submissions_fresh_after`).
  - Alternative: answers only, no raw reads.
  - Cost if wrong: the line follow's `corroborate`, the handoffs' `predecessor_names` and the R1 reading take the
    raw JSON or filing list. Hiding them would mean rewriting those rule modules in this step.
- **What it remembers.** It keeps only current copies: at most `MEMO_SIZE` (512) submissions copies and as many
  filing lists, the least recently asked dropped first, and every issuer's first filing.
  - Every refresh of the run goes through it: the resolver's reads and the classifier's up-front read. So a held
    copy is the client's cached copy.
  - A copy that does not carry its fetch day is read again for an event.
  - A refreshed copy drops the filing list and the first filing it held from the old copy.
  - Measured: the replay reads 2,529 issuers' submissions 32,946 times. The cache holds 5,987 copies, 496 MB on
    disk.
  - Alternative: hold every issuer's copy for the run.
  - Cost if wrong: an issuer asked again after 512 others is read again from the disk cache. That costs time only.
    Holding all 2,529 parsed copies would have added gigabytes to a run that already peaks at 6.5 GB.
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
- **The classifier asks its issuer record, not the resolver's privates.** It reads `submissions(cik, about=)` for
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
